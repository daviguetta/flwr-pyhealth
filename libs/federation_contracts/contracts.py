"""Versioned descriptions of federation, privacy and experiment settings.

These dataclasses are deliberately dependency-free: a contract that can only be
read by installing Flower and PyHealth is not a contract another institution can
review. They serialise to plain dicts so a run can emit a manifest that
identifies exactly what was agreed and executed.

Governance note: these structures carry *settings*, never patient data. They are
safe to publish alongside results; attribution maps and record-level outputs are
not.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Dict, List, Tuple

#: Bumped when a field changes meaning, so old manifests stay interpretable.
CONTRACT_VERSION = "1.0.0"

PARTITION_SCHEMES: Tuple[str, ...] = ("uniform", "label-skew")
STRATEGIES: Tuple[str, ...] = ("fedavg", "fedprox")
DP_MODES: Tuple[str, ...] = (
    "none",
    "server-fixed-clipping",
    "server-adaptive-clipping",
    "client-fixed-clipping",
    "client-adaptive-clipping",
)


@dataclass(frozen=True)
class FederationContract:
    """Who takes part and how their data is sliced.

    ``num_partitions`` is the number of participating sites. In the prototype it
    is a run-config value; in production it is the number of onboarded
    institutions, and the contract is the record of that.
    """

    num_partitions: int = 2
    partition_scheme: str = "uniform"
    split_seed: int = 42
    split_ratios: Tuple[float, float, float] = (0.8, 0.1, 0.1)

    def __post_init__(self) -> None:
        if self.num_partitions < 1:
            raise ValueError("num_partitions must be >= 1")
        if self.partition_scheme not in PARTITION_SCHEMES:
            raise ValueError(
                f"partition_scheme must be one of {PARTITION_SCHEMES}, "
                f"got {self.partition_scheme!r}"
            )
        if len(self.split_ratios) != 3:
            raise ValueError("split_ratios must hold train/val/test ratios")
        if abs(sum(self.split_ratios) - 1.0) > 1e-9:
            raise ValueError("split_ratios must sum to 1.0")


@dataclass(frozen=True)
class PrivacyPolicy:
    """The declared privacy posture of a run.

    Defaults are the honest baseline: DP off, recorded explicitly, so a report
    cannot imply a guarantee that was never configured.
    """

    mode: str = "none"
    noise_multiplier: float = 0.0
    clipping_norm: float = 1.0
    delta: float = 1e-5
    epsilon: float | None = None

    def __post_init__(self) -> None:
        if self.mode not in DP_MODES:
            raise ValueError(f"mode must be one of {DP_MODES}, got {self.mode!r}")
        if self.mode != "none":
            if self.noise_multiplier <= 0.0:
                raise ValueError("noise_multiplier must be > 0 when DP is enabled")
            if self.clipping_norm <= 0.0:
                raise ValueError("clipping_norm must be > 0 when DP is enabled")

    @property
    def is_enabled(self) -> bool:
        return self.mode != "none"


@dataclass(frozen=True)
class ExperimentSpec:
    """Aggregation and optimisation settings for one federated run."""

    strategy: str = "fedavg"
    proximal_mu: float = 0.0
    num_server_rounds: int = 3
    local_epochs: int = 2
    learning_rate: float = 1e-5
    batch_size: int = 32

    def __post_init__(self) -> None:
        if self.strategy not in STRATEGIES:
            raise ValueError(f"strategy must be one of {STRATEGIES}")
        if self.strategy == "fedprox" and self.proximal_mu <= 0.0:
            raise ValueError("fedprox requires proximal_mu > 0")
        if self.num_server_rounds < 1:
            raise ValueError("num_server_rounds must be >= 1")


@dataclass(frozen=True)
class RunManifest:
    """Everything needed to identify and reproduce one experiment."""

    federation: FederationContract = field(default_factory=FederationContract)
    privacy: PrivacyPolicy = field(default_factory=PrivacyPolicy)
    experiment: ExperimentSpec = field(default_factory=ExperimentSpec)
    contract_version: str = CONTRACT_VERSION

    def to_dict(self) -> Dict[str, object]:
        payload = asdict(self)
        payload["contract_version"] = self.contract_version
        return payload

    def summary_lines(self) -> List[str]:
        """Compact, log-friendly rendering."""
        return [
            f"contract      v{self.contract_version}",
            f"partitions    {self.federation.num_partitions} "
            f"({self.federation.partition_scheme})",
            f"strategy      {self.experiment.strategy}"
            + (
                f" (mu={self.experiment.proximal_mu})"
                if self.experiment.strategy == "fedprox"
                else ""
            ),
            f"privacy       {self.privacy.mode}"
            + (
                f" (noise={self.privacy.noise_multiplier}, "
                f"clip={self.privacy.clipping_norm})"
                if self.privacy.is_enabled
                else ""
            ),
            f"optimisation  {self.experiment.num_server_rounds} rounds x "
            f"{self.experiment.local_epochs} epochs, "
            f"lr={self.experiment.learning_rate}, bs={self.experiment.batch_size}",
        ]
