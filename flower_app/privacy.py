"""Differential privacy for the federation layer.

DP is an architectural requirement of this project, so it is kept in exactly one
place: the server wraps whichever aggregation strategy it was handed. That keeps
the *aggregation policy* (:mod:`flower_app.strategies`) and the *privacy
mechanism* independently switchable, which is what makes the privacy/utility
trade-off measurable.

Flower 1.34 already ships these mechanisms, so nothing is re-implemented here.

Chosen default: server-side fixed clipping
------------------------------------------
The server clips each received update to ``clipping_norm`` and adds Gaussian
noise scaled by ``noise_multiplier`` before aggregating. It needs no change on
the client side and gives *central* DP at a known mechanism, which is the
cheapest thing to run inside a single SESA-controlled environment.

Security caveat
---------------
Central DP still requires trusting the aggregation server, because it sees the
individual updates. A deployment that must not trust the server needs
client-side clipping plus secure aggregation; both are out of scope for this
prototype. Local DP (noise added on the node) is available through the
client-side variants but is only meaningful with a per-node privacy budget.

References
----------
McMahan, Andrew, Erlingsson, Talwar. "Learning Differentially Private Recurrent
Language Models." ICLR 2018. https://arxiv.org/abs/1710.06963
Abadi et al. "Deep Learning with Differential Privacy." CCS 2016.
https://arxiv.org/abs/1607.00133
"""

from __future__ import annotations

from typing import Optional

from flwr.serverapp.strategy import (
    DifferentialPrivacyClientSideAdaptiveClipping,
    DifferentialPrivacyClientSideFixedClipping,
    DifferentialPrivacyServerSideAdaptiveClipping,
    DifferentialPrivacyServerSideFixedClipping,
    Strategy,
)

DP_NONE = "none"
DP_SERVER_FIXED = "server-fixed-clipping"
DP_SERVER_ADAPTIVE = "server-adaptive-clipping"
DP_CLIENT_FIXED = "client-fixed-clipping"
DP_CLIENT_ADAPTIVE = "client-adaptive-clipping"

DP_MODES = (
    DP_NONE,
    DP_SERVER_FIXED,
    DP_SERVER_ADAPTIVE,
    DP_CLIENT_FIXED,
    DP_CLIENT_ADAPTIVE,
)

CLIENT_SIDE_MODES = (DP_CLIENT_FIXED, DP_CLIENT_ADAPTIVE)

# Modifiers a ClientApp must attach for the client-side mechanisms to work.
CLIENT_SIDE_MODIFIERS = {
    DP_CLIENT_FIXED: "fixedclipping_mod",
    DP_CLIENT_ADAPTIVE: "adaptiveclipping_mod",
}


def maybe_wrap_dp(
    strategy: Strategy,
    *,
    mode: str = DP_NONE,
    noise_multiplier: float = 0.0,
    clipping_norm: float = 1.0,
    num_sampled_clients: int = 0,
    initial_clipping_norm: float = 0.1,
    target_clipped_quantile: float = 0.5,
    clip_norm_lr: float = 0.2,
) -> Strategy:
    """Return ``strategy``, optionally wrapped in a DP mechanism.

    ``mode="none"`` returns the strategy untouched, which is the honest default
    for early experiments: enabling DP changes the numbers, so the privacy
    budget must be a deliberate, recorded choice rather than a silent default.

    ``num_sampled_clients`` is required by every mechanism because the noise
    scale depends on how many updates are aggregated per round.
    """
    if mode == DP_NONE:
        return strategy

    if mode not in DP_MODES:
        raise ValueError(f"unknown DP mode {mode!r}; expected one of {DP_MODES}")

    if num_sampled_clients < 1:
        raise ValueError(
            "num_sampled_clients must be >= 1 when DP is enabled, because the "
            "noise scale depends on the number of updates aggregated per round"
        )

    if mode == DP_SERVER_FIXED:
        return DifferentialPrivacyServerSideFixedClipping(
            strategy,
            noise_multiplier=noise_multiplier,
            clipping_norm=clipping_norm,
            num_sampled_clients=num_sampled_clients,
        )

    if mode == DP_SERVER_ADAPTIVE:
        return DifferentialPrivacyServerSideAdaptiveClipping(
            strategy,
            noise_multiplier=noise_multiplier,
            num_sampled_clients=num_sampled_clients,
            initial_clipping_norm=initial_clipping_norm,
            target_clipped_quantile=target_clipped_quantile,
            clip_norm_lr=clip_norm_lr,
        )

    if mode == DP_CLIENT_FIXED:
        return DifferentialPrivacyClientSideFixedClipping(
            strategy,
            noise_multiplier=noise_multiplier,
            clipping_norm=clipping_norm,
            num_sampled_clients=num_sampled_clients,
        )

    return DifferentialPrivacyClientSideAdaptiveClipping(
        strategy,
        noise_multiplier=noise_multiplier,
        num_sampled_clients=num_sampled_clients,
        initial_clipping_norm=initial_clipping_norm,
        target_clipped_quantile=target_clipped_quantile,
        clip_norm_lr=clip_norm_lr,
    )


def epsilon_for(
    *,
    noise_multiplier: float,
    num_sampled_clients: int,
    total_clients: int,
    num_rounds: int,
    delta: float = 1e-5,
    sampling_probability: Optional[float] = None,
) -> Optional[float]:
    """Estimate the central-DP epsilon of a run, or ``None`` if unavailable.

    Reported per run so that every experiment can state its privacy budget
    instead of only its accuracy. Requires the ``flwr[dp]`` extra
    (``dp-accounting``); returns ``None`` when that library is absent rather
    than inventing a number.
    """
    try:
        from dp_accounting import dp_event
        from dp_accounting.pld import pld_privacy_accountant
    except ImportError:
        return None

    if sampling_probability is None:
        if total_clients < 1:
            return None
        sampling_probability = min(1.0, num_sampled_clients / total_clients)

    event = dp_event.PoissonSampledDpEvent(
        sampling_probability,
        dp_event.GaussianDpEvent(noise_multiplier),
    )
    accountant = pld_privacy_accountant.PLDAccountant()
    accountant.compose(event, num_rounds)
    return accountant.get_epsilon(delta)
