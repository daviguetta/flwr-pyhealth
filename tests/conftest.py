"""Shared fixtures.

Most tests avoid the real dataset on purpose: loading MIMIC-IV costs hundreds of
megabytes and tens of seconds, so only the end-to-end test pays that price. The
stub below exposes exactly the surface ``task.partition_indices`` relies on,
which keeps the partitioning rules testable in isolation.
"""

from __future__ import annotations

import pytest
import torch


class StubSamples:
    """Minimal stand-in for a PyHealth sample dataset.

    Only ``__getitem__`` returning a ``mortality`` label is needed to exercise
    the partitioning logic, and that is all this provides.
    """

    def __init__(self, labels):
        self._labels = list(labels)

    def __getitem__(self, index: int):
        return {"mortality": torch.tensor([float(self._labels[index])])}

    def __len__(self) -> int:
        return len(self._labels)


@pytest.fixture
def stub_samples():
    """Balanced two-class cohort: 4 controls, 4 cases."""
    return StubSamples([0, 0, 0, 0, 1, 1, 1, 1])


@pytest.fixture
def stub_samples_odd():
    """Seven samples, to check that the last node absorbs the remainder."""
    return StubSamples([0, 0, 0, 0, 1, 1, 1])


@pytest.fixture(scope="session")
def real_samples():
    """The real MIMIC-IV demo pipeline, built once per session.

    Returns ``(samples, patient_groups)``. Loading costs hundreds of megabytes
    and tens of seconds, and every node in a run derives its schema from the same
    dataset, so building it once is faithful as well as cheap.
    """
    from flower_app.task import load_samples, patient_groups

    samples = load_samples()
    return samples, patient_groups(samples)
