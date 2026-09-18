"""Partitioning rules: the knob that decides how non-IID a run is.

Exercised through ``shard``, which is a pure function over a list, so these run
instantly and need neither PyHealth nor the dataset.
"""

from __future__ import annotations

import pytest

from flower_app.task import PARTITION_LABEL_SKEW, PARTITION_UNIFORM, shard

ITEMS = list(range(8))
# Round-robin (step 2) hands node 0 the even items and node 1 the odd ones. These
# labels make each node see both classes, which is what the IID baseline means.
BALANCED_LABELS = {item: (item // 2) % 2 for item in ITEMS}
# Sorted, this is four 0s followed by four 1s: a perfectly separable cohort.
SEPARABLE_LABELS = {item: int(item >= 4) for item in ITEMS}


def test_uniform_shards_form_a_partition(stub_samples):
    shards = [shard(ITEMS, None, node, 4, PARTITION_UNIFORM) for node in range(4)]

    assert sorted(item for one in shards for item in one) == ITEMS
    assert all(len(one) == 2 for one in shards)


def test_uniform_shards_carry_both_classes():
    """The IID baseline should not accidentally be non-IID."""
    for node in range(2):
        labels = {
            BALANCED_LABELS[item]
            for item in shard(ITEMS, BALANCED_LABELS, node, 2, PARTITION_UNIFORM)
        }
        assert labels == {0, 1}


def test_label_skew_isolates_classes_per_node():
    """The pathological case FedProx exists to survive."""
    first = shard(ITEMS, SEPARABLE_LABELS, 0, 2, PARTITION_LABEL_SKEW)
    second = shard(ITEMS, SEPARABLE_LABELS, 1, 2, PARTITION_LABEL_SKEW)

    assert {SEPARABLE_LABELS[item] for item in first} == {0}
    assert {SEPARABLE_LABELS[item] for item in second} == {1}


def test_label_skew_gives_the_remainder_to_the_last_node():
    items = list(range(7))
    labels = {item: int(item >= 4) for item in items}

    first = shard(items, labels, 0, 2, PARTITION_LABEL_SKEW)
    second = shard(items, labels, 1, 2, PARTITION_LABEL_SKEW)

    assert len(first) == 3
    assert len(second) == 4
    assert sorted(first + second) == items


@pytest.mark.parametrize("scheme", [PARTITION_UNIFORM, PARTITION_LABEL_SKEW])
def test_shards_are_disjoint(scheme):
    labels = BALANCED_LABELS if scheme == PARTITION_LABEL_SKEW else None
    first = set(shard(ITEMS, labels, 0, 2, scheme))
    second = set(shard(ITEMS, labels, 1, 2, scheme))
    assert first.isdisjoint(second)


def test_label_skew_without_labels_is_rejected():
    with pytest.raises(ValueError, match="requires a label"):
        shard(ITEMS, None, 0, 2, PARTITION_LABEL_SKEW)


def test_unknown_scheme_is_rejected():
    with pytest.raises(ValueError, match="unknown partition scheme"):
        shard(ITEMS, None, 0, 2, "random-shuffle")


@pytest.mark.parametrize("partition_id,num_partitions", [(2, 2), (-1, 2), (0, 0)])
def test_out_of_range_node_identity_is_rejected(partition_id, num_partitions):
    with pytest.raises(ValueError):
        shard(ITEMS, None, partition_id, num_partitions, PARTITION_UNIFORM)
