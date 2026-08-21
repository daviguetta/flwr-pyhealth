"""Shared MIMIC-IV dataset and StageNet construction helpers."""


from pyhealth.datasets import MIMIC3Dataset, get_dataloader, split_by_patient
from pyhealth.models import Transformer
from pyhealth.tasks import MortalityPredictionMIMIC3


ROOT = "https://storage.googleapis.com/pyhealth/Synthetic_MIMIC-III/"
TABLES = ["DIAGNOSES_ICD", "PROCEDURES_ICD", "PRESCRIPTIONS"]
SPLIT_RATIOS = [0.8, 0.1, 0.1]
SPLIT_SEED = 42


def load_samples():
    """Load MIMIC-IV and build the StageNet task schema."""
    dataset = MIMIC3Dataset(
        root=str(ROOT),
        tables=TABLES,
    )
    return dataset.set_task(MortalityPredictionMIMIC3())


def split_samples(samples):
    """Split samples by patient to prevent cross-split patient leakage."""
    return split_by_patient(samples, SPLIT_RATIOS, seed=SPLIT_SEED)


def build_model(samples):
    """Build the shared global StageNet architecture."""
    return Transformer(
        dataset=samples,
    )


def build_loaders(dataset, train_subset, val_subset, batch_size):
    """Partition train and validation subsets into deterministic node slices."""
    train_loader = get_dataloader(
        train_subset,
        batch_size=batch_size,
        shuffle=True,
    )
    val_loader = get_dataloader(
        val_subset,
        batch_size=batch_size,
        shuffle=False,
    )
    return dataset, train_loader, val_loader
