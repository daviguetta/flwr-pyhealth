"""The federation's component model, and the realizations that conform to it.

Why this exists
---------------
The federation can be deployed more than one way: one container per Flower
process, or one container per institution that bundles two processes. Those are
*physical* choices. The *logical* shape — which component owns which unit, which
interface a unit requires, and which interfaces may leave a unit — does not change
with them.

Recording that shape once makes it something a deployment can be checked
against, instead of something a reader has to be trusted to remember. Two
descriptor sets that look different are then provably the same model.

The invariant that matters most is the boundary: ``appio`` never leaves a unit.
A SuperExec talks to the SuperLink or SuperNode beside it, and only ``fleet``
crosses a unit boundary. A deployment that separates a SuperExec from its
runtime-API host either cannot work or works by widening the boundary — and
widening the boundary silently is the failure this module exists to make loud.

The level of that boundary is deliberate.
``env/incus/PORTS.md`` states the rule at the institution (Incus unit) level;
this model states it at the container level, which is strictly stronger. The two
agree for every realization listed here, because a bundled deployment keeps
``appio`` on loopback inside a single container. Separating the units would
satisfy the institution reading while breaking this one, and that is the trade the
project declined on 2026-09-25: process isolation was not judged worth putting the
runtime API on a network. See ``docs/HPC_SHELF_DECISIONS.md`` Fase 3.

Governance note: this describes *shape*. It carries no patient data.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Optional, Tuple

#: Bumped when the model changes meaning, so old realizations stay interpretable.
COMPONENT_MODEL_VERSION = "1.0.0"

# --- interfaces -------------------------------------------------------------

#: SuperExec -> its runtime-API host. Flower 1.34 calls this the AppIO API.
APPIO = "appio"

#: SuperNode -> SuperLink. The only interface that may cross a unit boundary.
FLEET = "fleet"

#: Operator -> SuperLink. Run submission and observation; not part of the loop.
CONTROL = "control"

INTERFACES: Tuple[str, ...] = (APPIO, FLEET, CONTROL)

#: Interfaces the model permits to leave a unit boundary. Everything else is
#: intra-unit, and a deployment that routes it out is not the same model.
INTER_UNIT_INTERFACES: Tuple[str, ...] = (FLEET,)


# --- the logical model ------------------------------------------------------


@dataclass(frozen=True)
class UnitRef:
    """A logical unit, addressed as ``component/unit``."""

    component: str
    unit: str

    @property
    def key(self) -> str:
        return f"{self.component}/{self.unit}"


@dataclass(frozen=True)
class Unit:
    """One logical unit: what it runs, what it offers, what it needs.

    ``touches_data`` records whether the unit may read patient records. It is
    what makes the data boundary checkable: a unit that touches data belongs
    inside an institution's boundary, and one that does not belongs nowhere near
    it.
    """

    ref: UnitRef
    process: str
    provides: Tuple[str, ...]
    requires: Tuple[str, ...]
    touches_data: bool = False

    @property
    def key(self) -> str:
        return self.ref.key


@dataclass(frozen=True)
class Binding:
    """A ``requires -> provides`` edge, served on a port.

    Whether the binding may cross a unit boundary is derived from the interface
    rather than declared, so it cannot drift from :data:`INTER_UNIT_INTERFACES`.
    """

    consumer: UnitRef
    provider: UnitRef
    interface: str
    port: int

    @property
    def crosses_unit(self) -> bool:
        return self.interface in INTER_UNIT_INTERFACES


#: The two components. The names are the ones agreed with the advisor; the
#: processes in parentheses are what Flower calls them.
COMMUNICATION = "comunicacao"
EXECUTION = "exec"

LINK = UnitRef(COMMUNICATION, "link")
NODE = UnitRef(COMMUNICATION, "node")
EXEC_SERVER = UnitRef(EXECUTION, "exec-server")
EXEC_CLIENT = UnitRef(EXECUTION, "exec-client")

#: The logical units. The processes are Flower 1.34 binaries.
REFERENCE_UNITS: Tuple[Unit, ...] = (
    Unit(
        ref=LINK,
        process="flower-superlink",
        provides=(APPIO, FLEET, CONTROL),
        requires=(),
    ),
    Unit(
        ref=NODE,
        process="flower-supernode",
        provides=(APPIO,),
        requires=(FLEET,),
    ),
    Unit(
        ref=EXEC_SERVER,
        process="flower-superexec --plugin-type serverapp",
        provides=(),
        requires=(APPIO,),
    ),
    Unit(
        ref=EXEC_CLIENT,
        process="flower-superexec --plugin-type clientapp",
        provides=(),
        requires=(APPIO,),
        # The only unit that reads patient records: the ClientApp materialises
        # its own partition. The SuperNode beside it only routes messages.
        touches_data=True,
    ),
)

#: The bindings. Ports are the Flower 1.34 container ports.
REFERENCE_BINDINGS: Tuple[Binding, ...] = (
    Binding(consumer=EXEC_SERVER, provider=LINK, interface=APPIO, port=9091),
    Binding(consumer=EXEC_CLIENT, provider=NODE, interface=APPIO, port=9094),
    Binding(consumer=NODE, provider=LINK, interface=FLEET, port=9092),
)


def units_by_key() -> Dict[str, Unit]:
    """The reference units, indexed by ``component/unit``."""
    return {unit.key: unit for unit in REFERENCE_UNITS}


# --- physical realizations --------------------------------------------------


@dataclass(frozen=True)
class PhysicalUnit:
    """One physical unit in a concrete deployment.

    A physical unit with N replicas is described once: replica counts are a
    deployment concern, not a shape concern.
    """

    name: str
    realizes: Tuple[UnitRef, ...]
    #: True when this physical unit is an institution's data boundary, i.e. the
    #: point past which records never travel.
    data_boundary: bool = False


@dataclass(frozen=True)
class Realization:
    """How one deployment physically realizes the logical model."""

    artifact: str
    descriptors: str
    units: Tuple[PhysicalUnit, ...]

    def host_of(self, ref: UnitRef) -> Optional[PhysicalUnit]:
        """The physical unit that realizes ``ref``, or ``None``."""
        for physical in self.units:
            if ref in physical.realizes:
                return physical
        return None

    def unit_named(self, name: str) -> Optional[PhysicalUnit]:
        for physical in self.units:
            if physical.name == name:
                return physical
        return None


#: This repository's descriptors. `hub` bundles the server-side pair and
#: `hospital` the client-side pair, because HPC Shelf resolves a horizontal
#: dependency only inside one component and admits one inner replica per host
#: replica. See docs/HPC_SHELF_DECISIONS.md section 5.
REALIZATION_PROJECT = Realization(
    artifact="env/hpcshelf/arms/grouped (project descriptors)",
    descriptors="env/hpcshelf/arms/grouped/components/flower-federation/0.1/component.yaml",
    units=(
        PhysicalUnit("hub", realizes=(LINK, EXEC_SERVER)),
        PhysicalUnit("hospital", realizes=(NODE, EXEC_CLIENT), data_boundary=True),
    ),
)

#: The platform catalogue's own federated-learning component, which bundles the
#: same two pairs under different names. It is listed here because a model that
#: only fits one spelling of the deployment is not a model.
REALIZATION_PLATFORM = Realization(
    artifact="catalog_data/components/federated-learning (platform catalogue)",
    descriptors="catalog_data/components/federated-learning/1.0/component.yaml",
    units=(
        PhysicalUnit("aggregator", realizes=(LINK, EXEC_SERVER)),
        PhysicalUnit("client", realizes=(NODE, EXEC_CLIENT), data_boundary=True),
    ),
)

REALIZATIONS: Tuple[Realization, ...] = (REALIZATION_PROJECT, REALIZATION_PLATFORM)
