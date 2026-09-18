"""Flower ClientApp: local training and evaluation on one patient partition.

Each node owns a disjoint patient slice and never sees another node's records.
What crosses the process boundary is exactly two things: model parameters
(``ArrayRecord``) and scalars (``MetricRecord``). No sample, identifier or
attribution map is ever serialised into a ``Message``.
"""

from __future__ import annotations

import os
import tempfile
from typing import Dict, List, Tuple

import torch
from flwr.app import ArrayRecord, Context, Message, MetricRecord, RecordDict
from flwr.clientapp import ClientApp
from pyhealth.trainer import Trainer

from .model import build_model
from .task import (
    PARTITION_UNIFORM,
    build_loaders,
    load_samples,
    materialize,
    node_split,
)

app = ClientApp()

#: Reported to the server and used for checkpoint selection.
#:
#: ``pr_auc`` leads because a deterioration alarm targets a rare event, where
#: precision/recall trade-offs matter more than ranking over the whole cohort.
#: It must also appear here, not only in ``monitor``: PyHealth indexes the
#: metric dict by the monitor name and raises ``KeyError`` otherwise.
METRICS: List[str] = ["pr_auc", "roc_auc", "f1", "accuracy"]
MONITOR = "pr_auc"


def _partition(context: Context) -> Tuple[int, int]:
    """Resolve the node identity.

    Flower's Simulation Runtime fills ``node_config`` with
    ``{"partition-id": i, "num-partitions": n}`` per simulated SuperNode, and the
    Podman deployment sets the same keys through
    ``--node-config "partition-id=0 num-partitions=2"``. So ``partition-id`` is
    read from ``node_config`` in both topologies.

    It is deliberately *not* defaulted. ``node_id`` looks like a tempting
    fallback, but in simulation it is a 64-bit identifier (for example
    6677547757711064239), not an index, and defaulting to 0 would let every node
    silently train on the same partition. A run that reports federated results
    while every node saw identical data is worse than a run that fails, so a
    missing ``partition-id`` is an error.
    """
    if "partition-id" not in context.node_config:
        raise ValueError(
            "node_config has no 'partition-id'. The client cannot tell which "
            "partition it owns, and guessing would silently produce a run that "
            "is not actually federated. In simulation this is set by Flower; in "
            "a deployment pass --node-config \"partition-id=<i> "
            "num-partitions=<n>\"."
        )

    partition_id = int(context.node_config["partition-id"])
    num_partitions = int(
        context.node_config.get(
            "num-partitions",
            context.run_config.get("num-partitions", 1),
        )
    )
    if num_partitions < 1:
        raise ValueError("num-partitions must be >= 1")
    if not 0 <= partition_id < num_partitions:
        raise ValueError(
            f"partition-id {partition_id} is outside [0, {num_partitions})"
        )
    return partition_id, num_partitions


def _partition_scheme(context: Context) -> str:
    """IID baseline by default; ``label-skew`` for the heterogeneity study."""
    return str(
        os.environ.get(
            "PYHEALTH_PARTITION_SCHEME",
            context.run_config.get("partition-scheme", PARTITION_UNIFORM),
        )
    )


def _local_data(context: Context):
    """Materialise this node's slice of the cohort.

    The split is computed from patient ids, so a patient never spans two nodes
    and never spans two splits.
    """
    partition_id, num_partitions = _partition(context)
    scheme = _partition_scheme(context)
    batch_size = int(context.run_config.get("batch-size", 32))

    samples = load_samples()
    split = node_split(samples, partition_id, num_partitions, scheme)
    train_dataset, val_dataset, test_dataset = materialize(samples, split)
    loaders = build_loaders(train_dataset, val_dataset, test_dataset, batch_size)

    # Printed on every node: the node identity and cohort size are the first
    # things to check when a federated run looks wrong.
    print(
        f"[client] node {partition_id}/{num_partitions} scheme={scheme} "
        f"{split.describe()}"
    )
    return samples, loaders


def _trainer(model, partition_id: int) -> Trainer:
    """Build a node-scoped PyHealth trainer.

    The output path is derived from the partition id so that simulated nodes
    sharing one filesystem cannot overwrite each other's best checkpoint.
    """
    device = "cuda:0" if torch.cuda.is_available() else "cpu"
    output_path = os.environ.get("PYHEALTH_OUTPUT_DIR") or os.path.join(
        tempfile.gettempdir(), f"pyhealth-flwr-node-{partition_id}"
    )
    return Trainer(
        model=model,
        device=device,
        metrics=list(METRICS),
        enable_logging=False,
        output_path=output_path,
        exp_name=f"node-{partition_id}",
    )


@app.train()
def train(msg: Message, context: Context):
    """Fit the received global model on the local partition."""
    partition_id, _ = _partition(context)
    samples, (train_loader, val_loader, _) = _local_data(context)

    model = build_model(samples)
    global_state = msg.content["arrays"].to_torch_state_dict()
    # Shape agreement is structural here: every node derives the vocabulary from
    # the same dataset, so strict loading is expected to hold.
    model.load_state_dict(global_state, strict=True)

    # FedProx injects "proximal-mu" into the train configuration. Anchoring to
    # the received weights must happen after load_state_dict.
    mu = float(msg.content["config"].get("proximal-mu", 0.0))
    if mu > 0.0:
        model.enable_proximal(global_state, mu)

    trainer = _trainer(model, partition_id)
    trainer.train(
        train_dataloader=train_loader,
        val_dataloader=val_loader,
        epochs=int(context.run_config["local-epochs"]),
        optimizer_params={"lr": float(context.run_config["learning-rate"])},
        monitor=MONITOR,
    )

    scores = trainer.evaluate(train_loader)
    content = RecordDict(
        {
            "arrays": ArrayRecord(model.state_dict()),
            "metrics": MetricRecord(
                {
                    "train_loss": float(scores["loss"]),
                    "train_pr_auc": float(scores.get("pr_auc", float("nan"))),
                    # Weighting key for federated averaging.
                    "num-examples": len(train_loader.dataset),
                }
            ),
        }
    )
    return Message(content=content, reply_to=msg)


@app.evaluate()
def evaluate(msg: Message, context: Context):
    """Score the global model on this node's local validation partition.

    The held-out *test* split is deliberately not used here: it is reserved for
    the centralised-versus-federated comparison, which needs a shared corpus
    that no node trained on.
    """
    partition_id, _ = _partition(context)
    samples, (_, val_loader, _) = _local_data(context)

    model = build_model(samples)
    model.load_state_dict(msg.content["arrays"].to_torch_state_dict(), strict=True)

    results: Dict[str, float] = _trainer(model, partition_id).evaluate(val_loader)
    content = RecordDict(
        {
            "metrics": MetricRecord(
                {
                    "eval_loss": float(results["loss"]),
                    "eval_pr_auc": float(results.get("pr_auc", float("nan"))),
                    "eval_roc_auc": float(results.get("roc_auc", float("nan"))),
                    "eval_f1": float(results.get("f1", float("nan"))),
                    "eval_accuracy": float(results.get("accuracy", float("nan"))),
                    "num-examples": len(val_loader.dataset),
                }
            )
        }
    )
    return Message(content=content, reply_to=msg)
