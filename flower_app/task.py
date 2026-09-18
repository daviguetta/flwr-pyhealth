"""PyHealth data pipeline and patient-level partitioning.

Data only: model construction lives in :mod:`flower_app.model` so the FedProx
proximal term has a single, testable home.

Why the split is implemented here
---------------------------------
The natural call would be ``pyhealth.datasets.split_by_patient``. It is not used
because the subsets it returns do not expose a usable index mapping: their
``patient_to_index`` still lists *every* patient, not just the subset's, and
their integer indices are re-based to the subset. Both properties make it easy
to build a split that leaks a patient across nodes while looking correct.

So patients are split here, from ``patient_to_index``, which is authoritative.
The result is a patient-level, seeded, reproducible partition that can be
inspected and reported.

Cohort layout
-------------
``ratios`` are applied to *patients*, globally:

* the train and validation pools are each partitioned across the nodes, so a node
  validates on patients no node trained on;
* the test pool is the **shared hold-out**. It is identical on every node and is
  never trained on, which is what makes the federated-versus-centralised
  comparison meaningful.

Data source
-----------
The default corpus is the MIMIC-IV Clinical Database Demo bundled under ``data/``
and licensed under ODbL-1.0 (see ``data/LICENSE.txt``). It holds 100
de-identified patients, enough to exercise the whole federated pipeline without
credentialed access but not enough for statistical conclusions: the validation
pool is single-digit in size, so its metrics are noisy by construction.

Point ``PYHEALTH_EHR_ROOT`` at a credentialed MIMIC-IV copy to scale up::

    export PYHEALTH_EHR_ROOT=/path/to/mimic-iv/2.2

SESA-CE data is never read, written or transmitted by this module. See
``docs/DATA_GOVERNANCE.md``.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from typing import Dict, List, Mapping, Optional, Sequence, Tuple

import numpy as np

from pyhealth.datasets import MIMIC4Dataset, get_dataloader
from pyhealth.tasks import MortalityPredictionMIMIC4

# ``patients`` and ``admissions`` are the base tables of ``MIMIC4Dataset``; the
# remaining three feed the task's ``conditions``/``procedures``/``drugs`` input
# schema. Keep this list in sync with ``MortalityPredictionMIMIC4``.
DEFAULT_EHR_TABLES: Tuple[str, ...] = (
    "patients",
    "admissions",
    "diagnoses_icd",
    "procedures_icd",
    "prescriptions",
)

DEFAULT_EHR_ROOT = "data"
DEFAULT_SPLIT_RATIOS: Tuple[float, float, float] = (0.8, 0.1, 0.1)
DEFAULT_SPLIT_SEED = 42

PARTITION_UNIFORM = "uniform"
PARTITION_LABEL_SKEW = "label-skew"
PARTITION_SCHEMES = (PARTITION_UNIFORM, PARTITION_LABEL_SKEW)


@dataclass(frozen=True)
class NodeSplit:
    """Global sample indices belonging to one node, per split."""

    train: List[int]
    val: List[int]
    test: List[int]

    def describe(self) -> str:
        return (
            f"train={len(self.train)} val={len(self.val)} test={len(self.test)}"
        )


def ehr_root() -> str:
    """Location of the MIMIC-IV root holding the ``hosp/`` and ``icu/`` dirs."""
    return os.environ.get("PYHEALTH_EHR_ROOT", DEFAULT_EHR_ROOT)


def ehr_tables() -> List[str]:
    """Tables to load, overridable through ``PYHEALTH_EHR_TABLES``."""
    raw = os.environ.get("PYHEALTH_EHR_TABLES")
    if raw:
        return [table.strip() for table in raw.split(",") if table.strip()]
    return list(DEFAULT_EHR_TABLES)


@lru_cache(maxsize=1)
def load_samples():
    """Build the mortality-prediction samples once per process."""
    dataset = MIMIC4Dataset(ehr_root=ehr_root(), ehr_tables=ehr_tables())
    return dataset.set_task(MortalityPredictionMIMIC4())


def _as_int(value) -> int:
    """Read a label that may be a tensor, a float or an int."""
    return int(value.item()) if hasattr(value, "item") else int(value)


def patient_groups(samples) -> Dict[str, List[int]]:
    """Map ``patient_id`` to its global sample indices."""
    groups = {str(pid): [int(i) for i in indices] for pid, indices in samples.patient_to_index.items()}
    if not groups:
        raise ValueError(
            "no patients found: check PYHEALTH_EHR_ROOT and PYHEALTH_EHR_TABLES"
        )
    return groups


def patient_label(samples, groups: Mapping[str, Sequence[int]], patient_id: str) -> int:
    """Majority mortality label of a patient, used to skew the partition."""
    values = [_as_int(samples[index]["mortality"]) for index in groups[patient_id]]
    return int(round(sum(values) / len(values)))


def split_patient_ids(
    groups: Mapping[str, Sequence[int]],
    ratios: Sequence[float] = DEFAULT_SPLIT_RATIOS,
    seed: int = DEFAULT_SPLIT_SEED,
) -> Tuple[List[str], List[str], List[str]]:
    """Seeded patient-level split into train, validation and test pools.

    ``sorted`` before shuffling so the outcome does not depend on dictionary
    insertion order.
    """
    if len(ratios) != 3 or abs(sum(ratios) - 1.0) > 1e-9:
        raise ValueError("ratios must be three values summing to 1.0")

    rng = np.random.default_rng(seed)
    patient_ids = sorted(groups)
    rng.shuffle(patient_ids)

    total = len(patient_ids)
    first = int(total * ratios[0])
    second = int(total * (ratios[0] + ratios[1]))
    return (
        list(patient_ids[:first]),
        list(patient_ids[first:second]),
        list(patient_ids[second:]),
    )


def _check_node(partition_id: int, num_partitions: int) -> None:
    if num_partitions < 1:
        raise ValueError("num_partitions must be >= 1")
    if not 0 <= partition_id < num_partitions:
        raise ValueError(
            f"partition_id {partition_id} is outside [0, {num_partitions})"
        )


def shard(
    items: Sequence,
    labels: Optional[Mapping] = None,
    partition_id: int = 0,
    num_partitions: int = 1,
    scheme: str = PARTITION_UNIFORM,
) -> List:
    """Split ``items`` across ``num_partitions`` nodes.

    ``uniform``
        Round-robin interleaving. The IID baseline and the reference point for
        every heterogeneity experiment.
    ``label-skew``
        Contiguous shards over label-sorted items. A deliberately pathological
        non-IID split: with few nodes, some of them see a single class, which is
        the regime FedProx (Li et al., 2018) was designed for.
    """
    items = list(items)
    _check_node(partition_id, num_partitions)

    if scheme == PARTITION_UNIFORM:
        return items[partition_id::num_partitions]

    if scheme == PARTITION_LABEL_SKEW:
        if labels is None:
            raise ValueError("label-skew requires a label for every item")
        ordered = sorted(items, key=lambda item: (labels[item], item))
        size = len(ordered) // num_partitions
        start = partition_id * size
        # The last node absorbs the remainder so no item is dropped.
        end = len(ordered) if partition_id == num_partitions - 1 else start + size
        return ordered[start:end]

    raise ValueError(
        f"unknown partition scheme {scheme!r}; expected one of {PARTITION_SCHEMES}"
    )


def partition_patient_ids(
    samples,
    groups: Mapping[str, Sequence[int]],
    patient_ids: Sequence[str],
    partition_id: int,
    num_partitions: int,
    scheme: str = PARTITION_UNIFORM,
) -> List[str]:
    """Assign a pool of patients to one node."""
    labels = None
    if scheme == PARTITION_LABEL_SKEW:
        labels = {
            patient_id: patient_label(samples, groups, patient_id)
            for patient_id in patient_ids
        }
    return shard(patient_ids, labels, partition_id, num_partitions, scheme)


def sample_indices(
    groups: Mapping[str, Sequence[int]], patient_ids: Sequence[str]
) -> List[int]:
    """Global sample indices owned by a set of patients."""
    return [int(index) for patient_id in patient_ids for index in groups[patient_id]]


def node_split(
    samples,
    partition_id: int,
    num_partitions: int,
    scheme: str = PARTITION_UNIFORM,
    ratios: Sequence[float] = DEFAULT_SPLIT_RATIOS,
    seed: int = DEFAULT_SPLIT_SEED,
) -> NodeSplit:
    """Compute one node's train/val/test indices.

    The test pool is returned whole on every node: it is the shared hold-out,
    never trained on and never partitioned.
    """
    _check_node(partition_id, num_partitions)
    groups = patient_groups(samples)
    train_pool, val_pool, test_pool = split_patient_ids(groups, ratios, seed)

    split = NodeSplit(
        train=sample_indices(
            groups,
            partition_patient_ids(
                samples, groups, train_pool, partition_id, num_partitions, scheme
            ),
        ),
        val=sample_indices(
            groups,
            partition_patient_ids(
                samples, groups, val_pool, partition_id, num_partitions, scheme
            ),
        ),
        test=sample_indices(groups, test_pool),
    )

    for name in ("train", "val"):
        if not getattr(split, name):
            raise ValueError(
                f"node {partition_id} received an empty {name} split with "
                f"num_partitions={num_partitions}: reduce the number of nodes or "
                "use a larger cohort than the bundled demo"
            )
    return split


def materialize(samples, split: NodeSplit):
    """Turn global indices into the three node-local dataset objects."""
    return (
        samples.subset(list(split.train)),
        samples.subset(list(split.val)),
        samples.subset(list(split.test)),
    )


def build_loaders(train_dataset, val_dataset, test_dataset, batch_size: int):
    """Wrap the three node-local datasets into PyHealth dataloaders."""
    return (
        get_dataloader(train_dataset, batch_size=batch_size, shuffle=True),
        get_dataloader(val_dataset, batch_size=batch_size, shuffle=False),
        get_dataloader(test_dataset, batch_size=batch_size, shuffle=False),
    )
