"""End-to-end pipeline checks against the bundled MIMIC-IV demo.

Marked ``slow`` because parsing the data takes tens of seconds and hundreds of
megabytes. Run with ``pytest -m slow`` or as part of the full suite.
"""

from __future__ import annotations

import pytest
import torch

from flower_app.explain import available_methods, supports_interpretability
from flower_app.model import ProximalTransformer, build_model
from flower_app.task import (
    build_loaders,
    materialize,
    node_split,
    patient_groups,
    split_patient_ids,
)

pytestmark = pytest.mark.slow

EXPECTED_BATCH_KEYS = {"visit_id", "patient_id", "conditions", "procedures", "drugs", "mortality"}


def test_bundled_demo_produces_samples(real_samples):
    samples, _ = real_samples
    assert len(samples) > 0
    assert len(patient_groups(samples)) > 0


def test_patient_pools_are_disjoint_and_cover_every_patient(real_samples):
    samples, _ = real_samples
    groups = patient_groups(samples)
    train, val, test = split_patient_ids(groups)

    assert set(train).isdisjoint(val)
    assert set(train).isdisjoint(test)
    assert set(val).isdisjoint(test)
    assert set(train) | set(val) | set(test) == set(groups)


def test_patient_split_is_reproducible(real_samples):
    """Same seed, same cohort, same partition: otherwise results are not reported."""
    samples, _ = real_samples
    groups = patient_groups(samples)
    assert split_patient_ids(groups, seed=7) == split_patient_ids(groups, seed=7)


def test_node_splits_are_patient_disjoint_across_nodes(real_samples):
    """The property that makes a federated run a federated run."""
    samples, _ = real_samples
    first = node_split(samples, 0, 2)
    second = node_split(samples, 1, 2)

    assert set(first.train).isdisjoint(second.train)
    assert set(first.val).isdisjoint(second.val)


def test_the_shared_holdout_is_identical_on_every_node(real_samples):
    """The test pool is the common ground for federated-vs-centralised scoring."""
    samples, _ = real_samples
    first = node_split(samples, 0, 2)
    second = node_split(samples, 1, 2)

    assert first.test == second.test
    assert set(first.test).isdisjoint(first.train)
    assert set(first.test).isdisjoint(second.train)


def test_materialised_node_data_loads_into_batches(real_samples):
    samples, _ = real_samples
    split = node_split(samples, 0, 2)
    train_dataset, val_dataset, test_dataset = materialize(samples, split)

    assert len(train_dataset) == len(split.train)
    assert len(val_dataset) == len(split.val)
    assert len(test_dataset) == len(split.test)

    loader, _, _ = build_loaders(train_dataset, val_dataset, test_dataset, batch_size=8)
    batch = next(iter(loader))
    assert EXPECTED_BATCH_KEYS.issubset(batch.keys())


def test_label_skew_produces_a_more_skewed_cohort_than_uniform(real_samples):
    """Sanity check on the heterogeneity knob itself."""
    samples, _ = real_samples

    def positive_rate(split):
        labels = [int(samples[i]["mortality"].item()) for i in split.train]
        return sum(labels) / len(labels) if labels else 0.0

    uniform = positive_rate(node_split(samples, 0, 2, scheme="uniform"))
    skewed = positive_rate(node_split(samples, 0, 2, scheme="label-skew"))

    assert skewed != uniform


def test_models_built_on_different_nodes_are_interchangeable(real_samples):
    """The property that removes the old vocabulary-mismatch workaround.

    Every node derives its schema from the same dataset, so a state_dict built
    on one node must load into another with ``strict=True``.
    """
    samples, _ = real_samples
    sender = build_model(samples)
    receiver = build_model(samples)

    receiver.load_state_dict(sender.state_dict(), strict=True)

    for name, tensor in sender.state_dict().items():
        assert torch.equal(tensor, receiver.state_dict()[name])


def test_proximal_variant_is_shape_compatible_with_the_plain_model(real_samples):
    """FedProx must not change the parameter set the server aggregates."""
    from pyhealth.models import Transformer

    samples, _ = real_samples
    proximal = build_model(samples)
    plain = Transformer(dataset=samples)

    assert isinstance(proximal, ProximalTransformer)
    assert set(proximal.state_dict()) == set(plain.state_dict())


def test_forward_pass_populates_the_proximal_penalty(real_samples):
    samples, _ = real_samples
    split = node_split(samples, 0, 2)
    model = build_model(samples)
    model.eval()

    loader, _, _ = build_loaders(*materialize(samples, split), batch_size=8)
    batch = next(iter(loader))

    plain = model(**batch)["loss"].detach()
    reference = {
        name: tensor.detach().clone() for name, tensor in model.state_dict().items()
    }
    # Move the model away from the reference so the penalty is non-zero.
    with torch.no_grad():
        for parameter in model.parameters():
            parameter.add_(1.0)
    model.enable_proximal(reference, mu=1.0)

    output = model(**batch)

    assert float(output["proximal_penalty"]) > 0.0
    assert float(output["loss"]) > float(plain)


def test_interpretability_is_available_for_the_chosen_architecture(real_samples):
    """XAI is a project requirement, so it must hold for the real model."""
    samples, _ = real_samples
    model = build_model(samples)

    assert supports_interpretability(model)
    assert "integrated_gradients" in available_methods()
