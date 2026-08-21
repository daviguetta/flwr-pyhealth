"""Flower ClientApp for federated StageNet mortality prediction."""

import torch
from flwr.app import ArrayRecord, Context, Message, MetricRecord, RecordDict
from flwr.clientapp import ClientApp
from pyhealth.trainer import Trainer

from .task import build_loaders, build_model, load_samples, split_samples


app = ClientApp()


def _partition(context: Context) -> tuple[int, int]:
    partition_id = int(context.node_config.get("partition-id", 0))
    num_partitions = int(
        context.node_config.get(
            "num-partitions",
            context.run_config.get("num-partitions", 1),
        )
    )
    if num_partitions < 1 or not 0 <= partition_id < num_partitions:
        raise ValueError("partition-id must be within num-partitions")
    return partition_id, num_partitions


def _config_value(msg: Message, context: Context, key: str, default):
    return msg.content["config"].get(key, context.run_config.get(key, default))


def _local_data(context: Context):
    partition_id, num_partitions = _partition(context)
    batch_size = int(context.run_config.get("batch-size", 32))
    samples = load_samples()
    train_subset, val_subset, _ = split_samples(samples)
    train_indices = train_subset.indices[partition_id::num_partitions]
    val_indices = val_subset.indices[partition_id::num_partitions]
    train_subset = torch.utils.data.Subset(samples, train_indices)
    val_subset = torch.utils.data.Subset(samples, val_indices)
    return build_loaders(samples, train_subset, val_subset, batch_size)


def _trainer(model):
    device = torch.device("cuda:0" if torch.cuda.is_available() else "cpu")
    return Trainer(
        model=model,
        device=str(device),
        metrics=["roc_auc", "f1", "accuracy"],
        enable_logging=False,
    )


@app.train()
def train(msg: Message, context: Context):
    """Train the received global model on the local patient partition."""
    samples, train_loader, val_loader = _local_data(context)
    model = build_model(samples)
    model.load_state_dict(msg.content["arrays"].to_torch_state_dict())
    trainer = _trainer(model)
    trainer.train(
        train_dataloader=train_loader,
        val_dataloader=val_loader,
        epochs=int(_config_value(msg, context, "local-epochs", 1)),
        monitor="pr_auc",
    )
    scores = trainer.evaluate(train_loader)
    content = RecordDict(
        {
            "arrays": ArrayRecord(model.state_dict()),
            "metrics": MetricRecord(
                {
                    "train_loss": float(scores["loss"]),
                    "num-examples": len(train_loader.dataset),
                }
            ),
        }
    )
    return Message(content=content, reply_to=msg)


@app.evaluate()
def evaluate(msg: Message, context: Context):
    """Evaluate the received global model on the local validation partition."""
    samples, _, val_loader = _local_data(context)
    model = build_model(samples)
    model.load_state_dict(msg.content["arrays"].to_torch_state_dict())
    results = _trainer(model).evaluate(val_loader)
    content = RecordDict(
        {
            "metrics": MetricRecord(
                {
                    "eval_loss": float(results["loss"]),
                    "eval_roc_auc": float(results["roc_auc"]),
                    "eval_f1": float(results["f1"]),
                    "eval_accuracy": float(results["accuracy"]),
                    "num-examples": len(val_loader.dataset),
                }
            )
        }
    )
    return Message(content=content, reply_to=msg)
