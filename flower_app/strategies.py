"""Aggregation strategies for the federation layer.

The strategy decides *how* the server turns node updates into one global model,
so it is the single most policy-relevant knob of the whole project. Every
option here is an official Flower strategy; nothing is re-implemented locally.

References
----------
FedAvg
    McMahan, Moore, Ramage, Hampson, Arcas. "Communication-Efficient Learning of
    Deep Networks from Decentralized Data." AISTATS 2017.
    https://arxiv.org/abs/1602.05629
FedProx
    Li, Sahu, Zaheer, Sanjabi, Talwalkar, Smith. "Federated Optimization in
    Heterogeneous Networks." MLSys 2020 (arXiv 2018).
    https://arxiv.org/abs/1812.06127
"""

from __future__ import annotations

from typing import Optional

from flwr.serverapp.strategy import FedAvg, FedProx, Strategy

STRATEGY_FEDAVG = "fedavg"
STRATEGY_FEDPROX = "fedprox"
STRATEGIES = (STRATEGY_FEDAVG, STRATEGY_FEDPROX)


def build_strategy(
    name: str,
    *,
    fraction_train: float = 1.0,
    fraction_evaluate: float = 1.0,
    min_train_nodes: int = 2,
    min_evaluate_nodes: int = 2,
    min_available_nodes: int = 2,
    proximal_mu: float = 0.0,
) -> Strategy:
    """Return the configured aggregation strategy.

    ``fedavg`` is the baseline. ``fedprox`` adds the proximal term that keeps a
    node from drifting too far from the global model, which is what makes the
    non-IID partitions of ``task.partition_indices`` trainable.

    The returned strategy is unwrapped: differential privacy is applied on top
    by :mod:`flower_app.privacy` so that the two concerns stay independent.
    """
    common = {
        "fraction_train": fraction_train,
        "fraction_evaluate": fraction_evaluate,
        "min_train_nodes": min_train_nodes,
        "min_evaluate_nodes": min_evaluate_nodes,
        "min_available_nodes": min_available_nodes,
    }

    if name == STRATEGY_FEDAVG:
        return FedAvg(**common)

    if name == STRATEGY_FEDPROX:
        # FedProx sends "proximal-mu" inside the train ConfigRecord; the client
        # is responsible for adding the penalty to its local loss.
        return FedProx(proximal_mu=proximal_mu, **common)

    raise ValueError(f"unknown strategy {name!r}; expected one of {STRATEGIES}")


def strategy_label(name: str, proximal_mu: Optional[float] = None) -> str:
    """Human-readable label used in logs and in experiment metadata."""
    if name == STRATEGY_FEDPROX:
        return f"{name}(mu={proximal_mu})"
    return name
