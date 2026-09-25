"""Conformance of the federation's component model.

Two deployments that look nothing alike — this repository's ``hub``/``hospital``
and the platform catalogue's ``aggregator``/``client`` — must reduce to the same
model. That is the claim Phase 0-C rests on.

Every check also has a negative control here: a deliberately broken realization
that names the code it must produce. Without them, a clean result would be
indistinguishable from a checker that verifies nothing — the same reason
``env/hpcshelf/validate.py`` carries its own controls.
"""

from __future__ import annotations

import pytest

from libs.federation_components import (
    EXEC_CLIENT,
    EXEC_SERVER,
    FLEET,
    LINK,
    NODE,
    REALIZATIONS,
    REFERENCE_BINDINGS,
    REFERENCE_UNITS,
    Binding,
    PhysicalUnit,
    Realization,
    Unit,
    UnitRef,
    check_conformance,
    check_model,
    conforms,
)


def realization(*physical_units: PhysicalUnit) -> Realization:
    return Realization(artifact="test", descriptors="-", units=tuple(physical_units))


def codes(findings) -> set[str]:
    return {finding.code for finding in findings}


# --- the model agrees with itself -------------------------------------------


def test_reference_model_is_self_consistent():
    """`provides`/`requires` and the bindings say the same thing."""
    assert check_model() == ()


def test_model_rejects_a_binding_the_consumer_does_not_require():
    broken = (
        Binding(consumer=LINK, provider=NODE, interface=FLEET, port=9092),
    )
    assert "M003" in codes(check_model(bindings=broken))


def test_model_rejects_an_unknown_interface():
    unit = Unit(ref=UnitRef("c", "u"), process="p", provides=("nope",), requires=())
    assert "M002" in codes(check_model(units=(unit,), bindings=()))


def test_model_rejects_a_duplicate_unit():
    duplicated = (REFERENCE_UNITS[0], REFERENCE_UNITS[0])
    assert "M001" in codes(check_model(units=duplicated, bindings=()))


def test_reference_units_are_indexed_by_name_not_position():
    """Guards the tests below: they refer to units by name, not by index."""
    assert {unit.key for unit in REFERENCE_UNITS} == {
        LINK.key,
        NODE.key,
        EXEC_SERVER.key,
        EXEC_CLIENT.key,
    }


# --- both artifacts conform --------------------------------------------------


@pytest.mark.parametrize("artifact", REALIZATIONS, ids=lambda r: r.artifact)
def test_every_realization_conforms(artifact):
    assert check_conformance(artifact) == ()
    assert conforms(artifact)


def test_both_artifacts_reduce_to_the_same_shape():
    """Different descriptors, identical model — the point of Phase 0-C."""
    shapes = []
    for artifact in REALIZATIONS:
        shapes.append(
            {
                binding.interface: (
                    artifact.host_of(binding.consumer) is artifact.host_of(binding.provider)
                )
                for binding in REFERENCE_BINDINGS
            }
        )
    assert shapes[0] == shapes[1]


def test_only_fleet_crosses_a_unit_boundary():
    """The invariant the whole boundary rests on."""
    for artifact in REALIZATIONS:
        for binding in REFERENCE_BINDINGS:
            shares = artifact.host_of(binding.consumer) is artifact.host_of(binding.provider)
            assert shares is not binding.crosses_unit, (
                f"{artifact.artifact}: {binding.consumer.key} -> {binding.provider.key} "
                f"({binding.interface})"
            )
        crossing = {
            binding.interface
            for binding in REFERENCE_BINDINGS
            if not (
                artifact.host_of(binding.consumer) is artifact.host_of(binding.provider)
            )
        }
        assert crossing == {FLEET}


def test_the_data_reading_unit_is_the_client_app():
    reading = {unit.key for unit in REFERENCE_UNITS if unit.touches_data}
    assert reading == {"exec/exec-client"}


# --- negative controls -------------------------------------------------------


def test_separating_a_superexec_from_its_runtime_api_host_is_rejected():
    """`appio` leaving a unit is the failure the model exists to catch.

    This is the shape the platform refuses too (C002/R3), reached here without
    the platform.
    """
    broken = realization(
        PhysicalUnit("link", realizes=(LINK,)),
        PhysicalUnit("node", realizes=(NODE,)),
        PhysicalUnit("serverapp", realizes=(EXEC_SERVER,)),
        PhysicalUnit("clientapp", realizes=(EXEC_CLIENT,)),
    )
    assert "M103" in codes(check_conformance(broken))


def test_a_missing_logical_unit_is_rejected():
    broken = realization(PhysicalUnit("hub", realizes=(LINK,)))
    assert "M101" in codes(check_conformance(broken))


def test_a_logical_unit_realized_twice_is_rejected():
    broken = realization(
        PhysicalUnit("hub-a", realizes=(LINK, EXEC_SERVER)),
        PhysicalUnit("hub-b", realizes=(LINK,)),
        PhysicalUnit("hospital", realizes=(NODE, EXEC_CLIENT), data_boundary=True),
    )
    assert "M102" in codes(check_conformance(broken))


def test_a_data_reading_unit_outside_a_boundary_is_rejected():
    broken = realization(
        PhysicalUnit("hub", realizes=(LINK, EXEC_SERVER, EXEC_CLIENT)),
        PhysicalUnit("hospital", realizes=(NODE,), data_boundary=True),
    )
    assert "M105" in codes(check_conformance(broken))


def test_a_physical_unit_realizing_nothing_is_rejected():
    broken = realization(
        PhysicalUnit("hub", realizes=(LINK, EXEC_SERVER)),
        PhysicalUnit("hospital", realizes=(NODE, EXEC_CLIENT), data_boundary=True),
        PhysicalUnit("ghost", realizes=()),
    )
    assert "M106" in codes(check_conformance(broken))


def test_fleet_that_never_leaves_a_unit_is_rejected():
    """Everything in one physical unit is safe but is not a federation."""
    everything = tuple(unit.ref for unit in REFERENCE_UNITS)
    broken = realization(PhysicalUnit("monolith", realizes=everything, data_boundary=True))
    findings = codes(check_conformance(broken))
    assert "M104" in findings
