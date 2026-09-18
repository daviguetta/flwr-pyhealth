#!/usr/bin/env python
"""Train the same architecture centrally and score it on the shared hold-out.

This is the comparison partner for the federated runs. It is the only way to
answer the question the project actually asks: does federating cost accuracy?

The comparison is fair because the shared test pool is never trained on in
either setting. The script asserts that the hold-out it scores on is byte-for-byte
the same index set that :func:`flower_app.task.node_split` hands to every
federated node, so the two numbers cannot silently diverge.

Usage:
    scripts/central_baseline.py --epochs 5
    scripts/central_baseline.py --epochs 5 --json
"""

from __future__ import annotations

import argparse
import json
import os
import tempfile

import torch
from pyhealth.trainer import Trainer

from flower_app.client_app import METRICS, MONITOR
from flower_app.model import build_model
from flower_app.task import (
    build_loaders,
    load_samples,
    node_split,
    patient_groups,
    sample_indices,
    split_patient_ids,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--epochs", type=int, default=5)
    parser.add_argument("--learning-rate", type=float, default=1e-5)
    parser.add_argument("--batch-size", type=int, default=32)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument(
        "--json",
        action="store_true",
        help="emit the metrics as JSON instead of a table",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    samples = load_samples()
    groups = patient_groups(samples)
    train_pool, val_pool, test_pool = split_patient_ids(groups, seed=args.seed)

    train_index = sample_indices(groups, train_pool)
    val_index = sample_indices(groups, val_pool)
    test_index = sample_indices(groups, test_pool)

    # Guard the comparison: the federated nodes report on this exact hold-out.
    federated_holdout = node_split(samples, 0, 2, seed=args.seed).test
    if sorted(federated_holdout) != sorted(test_index):
        raise SystemExit(
            "the shared hold-out does not match the one used by the federated "
            "nodes; the comparison would not be valid"
        )

    train_loader, val_loader, test_loader = build_loaders(
        samples.subset(train_index),
        samples.subset(val_index),
        samples.subset(test_index),
        args.batch_size,
    )

    device = "cuda:0" if torch.cuda.is_available() else "cpu"
    trainer = Trainer(
        model=build_model(samples),
        device=device,
        metrics=list(METRICS),
        enable_logging=False,
        output_path=os.environ.get("PYHEALTH_OUTPUT_DIR")
        or os.path.join(tempfile.gettempdir(), "pyhealth-central-baseline"),
        exp_name="central-baseline",
    )

    print(
        f"[central] train={len(train_index)} val={len(val_index)} "
        f"holdout={len(test_index)} device={device} epochs={args.epochs}"
    )

    trainer.train(
        train_dataloader=train_loader,
        val_dataloader=val_loader,
        epochs=args.epochs,
        optimizer_params={"lr": args.learning_rate},
        monitor=MONITOR,
    )

    results = trainer.evaluate(test_loader)
    metrics = {
        "holdout_loss": round(float(results["loss"]), 4),
        "holdout_pr_auc": round(float(results.get("pr_auc", float("nan"))), 4),
        "holdout_roc_auc": round(float(results.get("roc_auc", float("nan"))), 4),
        "holdout_f1": round(float(results.get("f1", float("nan"))), 4),
        "holdout_accuracy": round(float(results.get("accuracy", float("nan"))), 4),
        "num-holdout-examples": len(test_index),
    }

    if args.json:
        print(json.dumps(metrics, indent=2))
    else:
        print()
        for name, value in metrics.items():
            print(f"  {name:<24} {value}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
