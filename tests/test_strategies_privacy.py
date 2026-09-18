"""Strategy selection and the differential privacy wrapper."""

from __future__ import annotations

import pytest
from flwr.serverapp.strategy import (
    DifferentialPrivacyClientSideFixedClipping,
    DifferentialPrivacyServerSideFixedClipping,
    FedAvg,
    FedProx,
)

from flower_app.privacy import (
    DP_CLIENT_FIXED,
    DP_NONE,
    DP_SERVER_FIXED,
    epsilon_for,
    maybe_wrap_dp,
)
from flower_app.strategies import (
    STRATEGY_FEDAVG,
    STRATEGY_FEDPROX,
    build_strategy,
    strategy_label,
)


def test_fedavg_is_the_default_baseline():
    strategy = build_strategy(STRATEGY_FEDAVG)
    assert isinstance(strategy, FedAvg)
    assert not isinstance(strategy, FedProx)


def test_fedprox_is_built_with_its_coefficient():
    strategy = build_strategy(STRATEGY_FEDPROX, proximal_mu=0.25)
    assert isinstance(strategy, FedProx)
    assert strategy.proximal_mu == 0.25


def test_unknown_strategy_is_rejected_with_the_valid_options():
    with pytest.raises(ValueError, match="unknown strategy"):
        build_strategy("fedmedian")


def test_strategy_label_reports_mu_only_for_fedprox():
    assert strategy_label(STRATEGY_FEDAVG) == "fedavg"
    assert strategy_label(STRATEGY_FEDPROX, 0.1) == "fedprox(mu=0.1)"


def test_disabling_dp_returns_the_strategy_untouched():
    """A no-op must be a true no-op, or the baseline stops being a baseline."""
    strategy = build_strategy(STRATEGY_FEDAVG)
    assert maybe_wrap_dp(strategy, mode=DP_NONE) is strategy


def test_server_side_fixed_clipping_wraps_the_strategy():
    strategy = maybe_wrap_dp(
        build_strategy(STRATEGY_FEDAVG),
        mode=DP_SERVER_FIXED,
        noise_multiplier=1.0,
        clipping_norm=1.0,
        num_sampled_clients=2,
    )
    assert isinstance(strategy, DifferentialPrivacyServerSideFixedClipping)


def test_client_side_fixed_clipping_wraps_the_strategy():
    strategy = maybe_wrap_dp(
        build_strategy(STRATEGY_FEDAVG),
        mode=DP_CLIENT_FIXED,
        noise_multiplier=1.0,
        clipping_norm=1.0,
        num_sampled_clients=2,
    )
    assert isinstance(strategy, DifferentialPrivacyClientSideFixedClipping)


def test_dp_without_a_client_count_is_rejected():
    """Noise scale depends on how many updates are aggregated."""
    with pytest.raises(ValueError, match="num_sampled_clients"):
        maybe_wrap_dp(
            build_strategy(STRATEGY_FEDAVG),
            mode=DP_SERVER_FIXED,
            noise_multiplier=1.0,
            num_sampled_clients=0,
        )


def test_unknown_dp_mode_is_rejected():
    with pytest.raises(ValueError, match="unknown DP mode"):
        maybe_wrap_dp(
            build_strategy(STRATEGY_FEDAVG),
            mode="local-dp",
            noise_multiplier=1.0,
            num_sampled_clients=2,
        )


def test_dp_composes_with_fedprox():
    """Privacy and aggregation policy are independent knobs."""
    strategy = maybe_wrap_dp(
        build_strategy(STRATEGY_FEDPROX, proximal_mu=0.1),
        mode=DP_SERVER_FIXED,
        noise_multiplier=1.0,
        clipping_norm=1.0,
        num_sampled_clients=2,
    )
    assert isinstance(strategy, DifferentialPrivacyServerSideFixedClipping)


def test_epsilon_is_reported_or_honestly_absent():
    """A budget is either computed or declared unavailable, never guessed."""
    epsilon = epsilon_for(
        noise_multiplier=1.0, num_sampled_clients=2, total_clients=2, num_rounds=10
    )
    assert epsilon is None or epsilon > 0.0


def test_more_noise_buys_a_smaller_epsilon():
    """Sanity check on the direction of the privacy/utility trade-off."""
    quiet = epsilon_for(
        noise_multiplier=5.0, num_sampled_clients=2, total_clients=2, num_rounds=10
    )
    loud = epsilon_for(
        noise_multiplier=1.0, num_sampled_clients=2, total_clients=2, num_rounds=10
    )
    if quiet is None or loud is None:
        pytest.skip("dp-accounting is not installed")
    assert quiet < loud
