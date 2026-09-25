"""FedAvg with one local step per round *is* centralised SGD, not an approximation.

Why this is the strongest property the federation can be checked against
-----------------------------------------------------------------------
Write ``B`` for the union of the nodes' batches, ``B_i`` for node ``i``'s, ``N``
for ``|B|`` and ``n_i`` for ``|B_i|``. One centralised step with a mean loss is

    theta_c = theta_0 - eta * grad L(B),      L(B) = (1/N) * sum_{x in B} loss(x)

One FedAvg round, where each node takes one local step and the server averages
the updates weighted by ``num-examples``, is

    theta_f = sum_i (n_i / N) * (theta_0 - eta * grad L(B_i))
            = theta_0 - eta * sum_i (n_i / N) * (1/n_i) * sum_{x in B_i} grad loss(x)
            = theta_0 - eta * (1/N) * sum_{x in B} grad loss(x)
            = theta_c

The two are equal, so the equality holds whatever the partition sizes are — as
long as the weighting is by ``num-examples`` and each node takes exactly one
step. That makes it a test of the three things a federated run can get wrong:

* the server weighting the updates by the wrong key (FedAvg would stop being the
  mean gradient);
* a node training on data it does not own, or two nodes sharing a partition (the
  union would no longer be the union);
* more than one local step per round (the equality is a per-step identity, so it
  does not survive composition).

Each of those is a negative control below. Without them, a green identity would
be indistinguishable from a test whose arithmetic cancels out.

The test deliberately uses upstream code rather than a local reimplementation:
partitioning comes from ``flower_app.task.shard``, the weighting key comes from
``flower_app.strategies.build_strategy``, and the aggregation is Flower's own
``aggregate_arrayrecords``, which is the function ``FedAvg.aggregate_train``
calls.
"""

from __future__ import annotations

import copy

import pytest
import torch
from flwr.app import ArrayRecord, MetricRecord, RecordDict
from flwr.serverapp.strategy.strategy_utils import aggregate_arrayrecords

from flower_app.strategies import build_strategy
from flower_app.task import shard

#: The equality is exact arithmetic, so the tolerance only absorbs float32.
TOLERANCE = 1e-5

#: A step that moved the parameters less than this would make the identity
#: vacuously true — both sides equal to the initial weights. Every identity test
#: asserts real movement before comparing.
MIN_MOVEMENT = 1e-3

#: The key whose value the server weights by. The identity depends on it.
WEIGHTING_KEY = "num-examples"

FEATURES = 4
SEED = 7


def _cohort(num_samples: int):
    """A deterministic two-class cohort, small enough to be instant."""
    generator = torch.Generator().manual_seed(SEED)
    features = torch.randn(num_samples, FEATURES, generator=generator)
    labels = (features.sum(dim=1, keepdim=True) > 0).to(torch.float32)
    return features, labels


def _fresh_model() -> torch.nn.Linear:
    """Same initial weights everywhere, so the comparison is meaningful."""
    torch.manual_seed(0)
    return torch.nn.Linear(FEATURES, 1)


def _local_step(model, features, labels, learning_rate: float):
    """One SGD step from ``model``, returning a new model."""
    stepped = copy.deepcopy(model)
    optimizer = torch.optim.SGD(stepped.parameters(), lr=learning_rate)
    optimizer.zero_grad()
    torch.nn.functional.mse_loss(stepped(features), labels).backward()
    optimizer.step()
    return stepped


def _reply(model, num_examples: int, weighting_key: str = WEIGHTING_KEY) -> RecordDict:
    """A node's reply, shaped as ``ClientApp.train`` shapes it."""
    return RecordDict(
        {
            "arrays": ArrayRecord(model.state_dict()),
            "metrics": MetricRecord({weighting_key: float(num_examples)}),
        }
    )


def _federated_round(initial, shards, features, labels, learning_rate, weighting_key):
    """One FedAvg round over ``shards``, aggregated by Flower's own function."""
    replies = []
    for indices in shards:
        local = _local_step(
            initial, features[indices], labels[indices], learning_rate
        )
        replies.append(_reply(local, len(indices), weighting_key))

    aggregated = aggregate_arrayrecords(replies, weighting_key)
    result = _fresh_model()
    result.load_state_dict(aggregated.to_torch_state_dict())
    return result


def _centralised_step(initial, features, labels, learning_rate):
    """One SGD step on the union: the thing FedAvg must reproduce."""
    return _local_step(initial, features, labels, learning_rate)


def _max_parameter_gap(left, right) -> float:
    return max(
        (a - b).abs().max().item()
        for a, b in zip(left.parameters(), right.parameters(), strict=True)
    )


def _assert_identity_reproduced(federated, centralised, initial) -> None:
    """The equality, guarded against holding because nothing happened.

    Without the movement check, a learning rate of zero — or a loss that never
    varies — would make both sides equal the initial weights and the test would
    pass while proving nothing.
    """
    movement = _max_parameter_gap(initial, centralised)
    assert movement > MIN_MOVEMENT, (
        f"the centralised step moved the parameters by only {movement:.3e}, so "
        f"the identity would hold vacuously"
    )
    gap = _max_parameter_gap(federated, centralised)
    assert gap <= TOLERANCE, f"FedAvg and centralised SGD differ by {gap:.3e}"


def _shards(num_samples: int, num_nodes: int):
    """Node index lists from the project's own partitioning."""
    items = list(range(num_samples))
    return [
        shard(items, partition_id=index, num_partitions=num_nodes)
        for index in range(num_nodes)
    ]


# --- the identity ------------------------------------------------------------


def test_the_strategy_weights_by_num_examples():
    """Guard: the identity below is only true for this key."""
    strategy = build_strategy("fedavg")
    assert strategy.weighted_by_key == WEIGHTING_KEY


def test_one_fedavg_round_equals_one_centralised_step():
    """Equal partitions, one local step each: the doc's headline case."""
    features, labels = _cohort(8)
    shards = _shards(8, 2)
    assert [len(s) for s in shards] == [4, 4]

    initial = _fresh_model()
    federated = _federated_round(
        initial, shards, features, labels, 0.1, WEIGHTING_KEY
    )
    centralised = _centralised_step(initial, features, labels, 0.1)

    _assert_identity_reproduced(federated, centralised, initial)


def test_identity_holds_for_unequal_partitions_too():
    """Weighting by ``num-examples`` makes size irrelevant — a stronger claim."""
    features, labels = _cohort(7)
    shards = _shards(7, 2)
    assert [len(s) for s in shards] == [4, 3]

    initial = _fresh_model()
    federated = _federated_round(
        initial, shards, features, labels, 0.1, WEIGHTING_KEY
    )
    centralised = _centralised_step(initial, features, labels, 0.1)

    _assert_identity_reproduced(federated, centralised, initial)


def test_identity_composes_over_several_rounds():
    """The per-step equality survives repetition when each round takes one step."""
    features, labels = _cohort(12)
    shards = _shards(12, 3)
    assert [len(s) for s in shards] == [4, 4, 4]

    federated = _fresh_model()
    centralised = _fresh_model()
    for _ in range(3):
        federated = _federated_round(
            federated, shards, features, labels, 0.05, WEIGHTING_KEY
        )
        centralised = _centralised_step(centralised, features, labels, 0.05)

    _assert_identity_reproduced(federated, centralised, _fresh_model())


# --- negative controls -------------------------------------------------------


def test_unweighted_average_diverges_on_unequal_partitions():
    """Control 1: the wrong weighting key breaks it.

    A constant key makes the server take a plain mean of the updates. With
    partitions of 4 and 3 that is no longer the mean gradient over the union.
    """
    features, labels = _cohort(7)
    shards = _shards(7, 2)

    initial = _fresh_model()
    equal_weight = "weight"
    replies = []
    for indices in shards:
        local = _local_step(initial, features[indices], labels[indices], 0.1)
        replies.append(
            RecordDict(
                {
                    "arrays": ArrayRecord(local.state_dict()),
                    "metrics": MetricRecord({equal_weight: 1.0}),
                }
            )
        )
    aggregated = aggregate_arrayrecords(replies, equal_weight)
    unweighted = _fresh_model()
    unweighted.load_state_dict(aggregated.to_torch_state_dict())

    centralised = _centralised_step(initial, features, labels, 0.1)
    assert _max_parameter_gap(unweighted, centralised) > TOLERANCE


def test_a_duplicated_partition_diverges():
    """Control 2: a node training on data it does not own breaks it.

    Node 1 is given node 0's shard, so the union the server sees is missing a
    quarter of the cohort. Every node still reports a plausible size.
    """
    features, labels = _cohort(8)
    shards = _shards(8, 2)
    duplicated = [shards[0], shards[0]]

    initial = _fresh_model()
    federated = _federated_round(
        initial, duplicated, features, labels, 0.1, WEIGHTING_KEY
    )
    centralised = _centralised_step(initial, features, labels, 0.1)

    assert _max_parameter_gap(federated, centralised) > TOLERANCE


def test_two_local_steps_per_round_diverge():
    """Control 3: the identity is per step, so it does not survive composition."""
    features, labels = _cohort(8)
    shards = _shards(8, 2)

    initial = _fresh_model()
    replies = []
    for indices in shards:
        once = _local_step(initial, features[indices], labels[indices], 0.1)
        twice = _local_step(once, features[indices], labels[indices], 0.1)
        replies.append(_reply(twice, len(indices)))
    aggregated = aggregate_arrayrecords(replies, WEIGHTING_KEY)
    federated = _fresh_model()
    federated.load_state_dict(aggregated.to_torch_state_dict())

    centralised = _centralised_step(initial, features, labels, 0.1)
    assert _max_parameter_gap(federated, centralised) > TOLERANCE


def test_the_identity_guard_rejects_a_step_that_moved_nothing():
    """Meta-control: the movement guard is not decorative.

    With a zero learning rate both sides equal the initial weights, so the
    equality holds while meaning nothing. The guard has to refuse it.
    """
    features, labels = _cohort(8)
    frozen = _fresh_model()

    assert (
        _max_parameter_gap(frozen, _centralised_step(frozen, features, labels, 0.0))
        == 0.0
    )

    with pytest.raises(AssertionError, match="vacuously"):
        _assert_identity_reproduced(frozen, frozen, frozen)
