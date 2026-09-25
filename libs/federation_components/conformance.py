"""Conformance checks: does a realization agree with the component model?

A green result is worthless on its own — a checker that reports nothing is
indistinguishable from a checker that verifies nothing. Every code below has a
negative control in ``tests/test_federation_components.py``, which builds a
deliberately broken realization and asserts the code fires.

Codes
-----
``M001``-``M003`` mean the *model* is inconsistent with itself, which is a defect
in this repository and not in the deployment being checked.
``M101``-``M106`` mean a *realization* does not conform.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Tuple

from .model import (
    INTERFACES,
    REFERENCE_BINDINGS,
    REFERENCE_UNITS,
    Binding,
    Realization,
    Unit,
)


@dataclass(frozen=True)
class Finding:
    code: str
    message: str

    def __str__(self) -> str:
        return f"{self.code} {self.message}"


def check_model(
    units: Tuple[Unit, ...] = REFERENCE_UNITS,
    bindings: Tuple[Binding, ...] = REFERENCE_BINDINGS,
) -> Tuple[Finding, ...]:
    """Check that the model agrees with itself.

    ``provides`` and ``requires`` are declared per unit, while the bindings
    declare the same edges from the other direction. If the two disagree, every
    conformance result measured against the model is meaningless, so this runs
    before anything is compared against it.

    Takes its inputs as arguments so a test can feed it a broken model.
    """
    findings: List[Finding] = []
    by_key: Dict[str, Unit] = {}

    for unit in units:
        if unit.key in by_key:
            findings.append(Finding("M001", f"duplicate logical unit '{unit.key}'"))
        by_key[unit.key] = unit
        for name in unit.provides + unit.requires:
            if name not in INTERFACES:
                findings.append(Finding("M002", f"{unit.key}: unknown interface {name!r}"))
        for name in unit.provides:
            if name in unit.requires:
                findings.append(
                    Finding("M002", f"{unit.key} both provides and requires {name!r}")
                )

    for binding in bindings:
        consumer = by_key.get(binding.consumer.key)
        provider = by_key.get(binding.provider.key)
        edge = f"{binding.consumer.key} -> {binding.provider.key}"
        if consumer is None or provider is None:
            findings.append(Finding("M003", f"binding {edge} references an unknown unit"))
            continue
        if binding.interface not in INTERFACES:
            findings.append(Finding("M003", f"binding {edge} uses unknown interface "
                                            f"{binding.interface!r}"))
            continue
        if binding.interface not in consumer.requires:
            findings.append(Finding("M003", f"binding {edge} carries {binding.interface!r}, "
                                            f"which {consumer.key} does not require"))
        if binding.interface not in provider.provides:
            findings.append(Finding("M003", f"binding {edge} carries {binding.interface!r}, "
                                            f"which {provider.key} does not provide"))
        if binding.crosses_unit and binding.port <= 0:
            findings.append(Finding("M003", f"binding {edge} crosses a unit with no port"))
    return tuple(findings)


def check_conformance(realization: Realization) -> Tuple[Finding, ...]:
    """Check one deployment's realization against the model."""
    findings: List[Finding] = []
    where = realization.artifact

    # Which physical units realize each logical unit.
    hosts: Dict[str, List[str]] = {}
    for physical in realization.units:
        if not physical.realizes:
            findings.append(
                Finding("M106", f"{where}: physical unit '{physical.name}' realizes nothing")
            )
        for ref in physical.realizes:
            hosts.setdefault(ref.key, []).append(physical.name)

    for unit in REFERENCE_UNITS:
        seen = hosts.get(unit.key, [])
        if not seen:
            findings.append(Finding("M101", f"{where}: logical unit '{unit.key}' is not realized"))
        elif len(seen) > 1:
            findings.append(
                Finding("M102", f"{where}: logical unit '{unit.key}' is realized by "
                                f"{len(seen)} physical units: {', '.join(sorted(seen))}")
            )

    for binding in REFERENCE_BINDINGS:
        consumer_hosts = hosts.get(binding.consumer.key, [])
        provider_hosts = hosts.get(binding.provider.key, [])
        if not consumer_hosts or not provider_hosts:
            continue  # M101 already reported the missing end
        shares_unit = bool(set(consumer_hosts) & set(provider_hosts))
        edge = f"{binding.consumer.key} -> {binding.provider.key} ({binding.interface})"
        if binding.crosses_unit and shares_unit:
            findings.append(
                Finding("M104", f"{where}: {edge} must cross a unit boundary, but both ends "
                                f"are inside '{consumer_hosts[0]}'")
            )
        if not binding.crosses_unit and not shares_unit:
            findings.append(
                Finding("M103", f"{where}: {edge} must stay inside one unit, but it spans "
                                f"'{consumer_hosts[0]}' and '{provider_hosts[0]}'")
            )

    for unit in REFERENCE_UNITS:
        if not unit.touches_data:
            continue
        for name in hosts.get(unit.key, []):
            physical = realization.unit_named(name)
            if physical is None or not physical.data_boundary:
                findings.append(
                    Finding("M105", f"{where}: '{unit.key}' reads patient records but is "
                                    f"realized in '{name}', which is not a data boundary")
                )
    return tuple(findings)


def conforms(realization: Realization) -> bool:
    """True when ``realization`` conforms and the model is self-consistent."""
    return not check_model() and not check_conformance(realization)


def render(findings: Tuple[Finding, ...]) -> str:
    """One finding per line, for a checker's output."""
    return "\n".join(str(finding) for finding in findings)
