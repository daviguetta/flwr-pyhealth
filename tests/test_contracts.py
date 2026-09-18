"""Invariants of the federation contracts.

These run without Flower, PyHealth or any data, because a contract that cannot
be checked cheaply will not be checked at all.
"""

from __future__ import annotations

import pytest

from libs.federation_contracts import (
    CONTRACT_VERSION,
    ExperimentSpec,
    FederationContract,
    PrivacyPolicy,
    RunManifest,
)


def test_default_manifest_is_the_honest_baseline():
    """Defaults must not imply guarantees that were never configured."""
    manifest = RunManifest()
    assert manifest.contract_version == CONTRACT_VERSION
    assert manifest.privacy.is_enabled is False
    assert manifest.privacy.mode == "none"
    assert manifest.experiment.strategy == "fedavg"


def test_manifest_round_trips_to_a_flat_dict():
    payload = RunManifest().to_dict()
    assert payload["contract_version"] == CONTRACT_VERSION
    assert payload["federation"]["num_partitions"] == 2
    assert payload["privacy"]["mode"] == "none"


@pytest.mark.parametrize("num_partitions", [0, -1])
def test_federation_rejects_non_positive_partition_counts(num_partitions):
    with pytest.raises(ValueError, match="num_partitions"):
        FederationContract(num_partitions=num_partitions)


def test_federation_rejects_unknown_partition_scheme():
    with pytest.raises(ValueError, match="partition_scheme"):
        FederationContract(partition_scheme="shuffled-per-node")


def test_federation_rejects_split_ratios_that_do_not_sum_to_one():
    with pytest.raises(ValueError, match="sum to 1.0"):
        FederationContract(split_ratios=(0.8, 0.1, 0.2))


@pytest.mark.parametrize(
    "mode", ["server-fixed-clipping", "server-adaptive-clipping"]
)
def test_enabling_dp_without_noise_is_rejected(mode):
    """A DP mode with zero noise is not a privacy guarantee."""
    with pytest.raises(ValueError, match="noise_multiplier"):
        PrivacyPolicy(mode=mode, noise_multiplier=0.0)


def test_enabling_dp_without_clipping_is_rejected():
    with pytest.raises(ValueError, match="clipping_norm"):
        PrivacyPolicy(mode="server-fixed-clipping", noise_multiplier=1.0, clipping_norm=0.0)


def test_fedprox_requires_a_positive_mu():
    """mu=0 is FedAvg wearing a FedProx label."""
    with pytest.raises(ValueError, match="proximal_mu"):
        ExperimentSpec(strategy="fedprox", proximal_mu=0.0)


def test_fedprox_accepts_a_positive_mu():
    spec = ExperimentSpec(strategy="fedprox", proximal_mu=0.1)
    assert spec.proximal_mu == 0.1


def test_summary_lines_name_strategy_and_privacy():
    manifest = RunManifest(
        privacy=PrivacyPolicy(mode="server-fixed-clipping", noise_multiplier=1.0),
        experiment=ExperimentSpec(strategy="fedprox", proximal_mu=0.5),
    )
    rendered = "\n".join(manifest.summary_lines())
    assert "fedprox (mu=0.5)" in rendered
    assert "server-fixed-clipping" in rendered
