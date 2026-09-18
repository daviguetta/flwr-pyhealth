"""Flower ServerApp: global model, aggregation strategy and privacy wrapping.

This is the policy surface of the project. Strategy selection, the FedProx
coefficient and the differential-privacy mechanism are all resolved here, from
run configuration, so a single ``flwr run`` flag produces a reproducible
experiment without touching code.

The server never touches patient records: it builds the model from the shared
*schema* only, then exchanges parameters and scalars.
"""

from __future__ import annotations

import os

from flwr.app import ArrayRecord, ConfigRecord, Context
from flwr.serverapp import Grid, ServerApp

from .model import build_model
from .privacy import DP_NONE, DP_MODES, maybe_wrap_dp
from .strategies import STRATEGIES, STRATEGY_FEDAVG, build_strategy, strategy_label
from .task import load_samples

app = ServerApp()


def _config(context: Context, key: str, default):
    """Read a run-config value, letting an environment variable override it.

    The environment override exists so the container topology can pin the
    strategy per deployment without editing ``pyproject.toml``.
    """
    env_key = f"PYHEALTH_{key.upper().replace('-', '_')}"
    return os.environ.get(env_key, context.run_config.get(key, default))


@app.main()
def main(grid: Grid, context: Context) -> None:
    """Run the configured federated experiment."""
    strategy_name = str(_config(context, "strategy", STRATEGY_FEDAVG))
    proximal_mu = float(_config(context, "proximal-mu", 0.0))
    dp_mode = str(_config(context, "dp-mode", DP_NONE))
    num_partitions = int(_config(context, "num-partitions", 2))

    if strategy_name not in STRATEGIES:
        raise ValueError(f"strategy must be one of {STRATEGIES}, got {strategy_name!r}")
    if dp_mode not in DP_MODES:
        raise ValueError(f"dp-mode must be one of {DP_MODES}, got {dp_mode!r}")

    # The schema, not the data: this fixes vocabulary and embedding shapes so
    # every node's state_dict is interchangeable.
    samples = load_samples()
    model = build_model(samples)

    strategy = build_strategy(
        strategy_name,
        fraction_train=float(context.run_config["fraction-train"]),
        fraction_evaluate=float(context.run_config["fraction-evaluate"]),
        proximal_mu=proximal_mu,
    )

    # DP wraps whatever strategy was chosen, keeping the two concerns
    # independently switchable.
    strategy = maybe_wrap_dp(
        strategy,
        mode=dp_mode,
        noise_multiplier=float(_config(context, "dp-noise-multiplier", 0.0)),
        clipping_norm=float(_config(context, "dp-clipping-norm", 1.0)),
        num_sampled_clients=num_partitions,
    )

    print(
        f"[server] strategy={strategy_label(strategy_name, proximal_mu)} "
        f"dp={dp_mode} clients={num_partitions} "
        f"rounds={int(context.run_config['num-server-rounds'])}"
    )

    strategy.start(
        grid=grid,
        initial_arrays=ArrayRecord(model.state_dict()),
        train_config=ConfigRecord(
            {
                "lr": float(context.run_config["learning-rate"]),
                "local-epochs": int(context.run_config["local-epochs"]),
            }
        ),
        num_rounds=int(context.run_config["num-server-rounds"]),
    )
