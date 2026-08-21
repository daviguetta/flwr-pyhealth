"""Flower ServerApp for federated StageNet mortality prediction."""

from flwr.app import ArrayRecord, ConfigRecord, Context
from flwr.serverapp import Grid, ServerApp
from flwr.serverapp.strategy import FedAvg

from .task import build_model, load_samples


app = ServerApp()


@app.main()
def main(grid: Grid, context: Context) -> None:
    """Start FedAvg with a model initialized from the shared MIMIC schema."""
    samples = load_samples()
    model = build_model(samples)
    strategy = FedAvg(
        fraction_train=float(context.run_config["fraction-train"]),
        fraction_evaluate=float(context.run_config["fraction-evaluate"]),
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
