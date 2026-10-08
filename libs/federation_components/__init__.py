"""The federation's component model and its conformance checks.

The model is deliberately small and dependency-free: it describes *shape*
(components, units, interfaces, bindings), so it can be read by anyone reviewing
the architecture and checked against any deployment descriptor set.

See ``docs/ARCHITECTURE.md`` for the narrative and
``docs/HPC_SHELF_DECISIONS.md`` Fase 0 for why it exists.
"""

from .conformance import Finding, check_conformance, check_model, conforms, render
from .model import (
    APPIO,
    COMMUNICATION,
    COMPONENT_MODEL_VERSION,
    CONTROL,
    EXEC_CLIENT,
    EXEC_SERVER,
    EXECUTION,
    FLEET,
    INTER_UNIT_INTERFACES,
    INTERFACES,
    LINK,
    NODE,
    REALIZATION_PLATFORM,
    REALIZATION_PROJECT,
    REALIZATIONS,
    REFERENCE_BINDINGS,
    REFERENCE_UNITS,
    Binding,
    PhysicalUnit,
    Realization,
    Unit,
    UnitRef,
    units_by_key,
)

__all__ = [
    "APPIO",
    "COMMUNICATION",
    "COMPONENT_MODEL_VERSION",
    "CONTROL",
    "EXEC_CLIENT",
    "EXEC_SERVER",
    "EXECUTION",
    "FLEET",
    "INTERFACES",
    "INTER_UNIT_INTERFACES",
    "LINK",
    "NODE",
    "REALIZATIONS",
    "REALIZATION_PLATFORM",
    "REALIZATION_PROJECT",
    "REFERENCE_BINDINGS",
    "REFERENCE_UNITS",
    "Binding",
    "Finding",
    "PhysicalUnit",
    "Realization",
    "Unit",
    "UnitRef",
    "check_conformance",
    "check_model",
    "conforms",
    "render",
    "units_by_key",
]
