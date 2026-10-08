#!/usr/bin/env python3
"""Prove the Phase 0 frozen decomposition against the HPC Shelf platform.

Runs, with no infrastructure and **without writing to the platform repository**:

  1. `SemanticValidator` over the descriptors in this directory (positive proof);
  2. negative controls proving the validator really catches the violations the
     decomposition must avoid: C017, C007, D004, D007 and C002 — including the
     component model's own four-unit decomposition, so the R3/R6 collision is a
     reproducible result instead of an argument (`env/hpcshelf/arms/grouped/model_split.py`);
  3. `DeploymentPlanner`, proving the horizontal dependency resolves (R3) and
     that `SUPERLINK_HOST`/`SUPERLINK_PORT` are injected (R4/R5).

Platform modules are imported read-only from `HPCSHELF_MODEL_ROOT`. Nothing is
created, changed or committed there.

Usage:
    HPCSHELF_MODEL_ROOT=/path/to/hpcshelf-model \\
        /path/to/venv/bin/python env/hpcshelf/arms/grouped/validate.py

The interpreter needs the dependencies pinned in the platform's
`requirements.txt` (`pydantic==2.13.5`, `PyYAML==6.0.3`). Create one with:

    uv venv /tmp/hpcshelf-val-venv --python 3.12
    uv pip install --python /tmp/hpcshelf-val-venv/bin/python \\
        -r "$HPCSHELF_MODEL_ROOT/requirements.txt"

`scripts/validate_hpcshelf.sh` wraps the call with those checks.
"""

from __future__ import annotations

import copy
import os
import sys
from pathlib import Path

import yaml

# The platform is imported read-only; never drop bytecode into its checkout.
sys.dont_write_bytecode = True

HERE = Path(__file__).resolve().parent
APPLICATION_FILE = HERE / "applications" / "pyhealth-federation.yaml"
HOSTS_FILE = HERE.parent.parent / "hosts.yaml"
COMPONENT_FILES = sorted((HERE / "components").glob("*/*/component.yaml"))

DEFAULT_MODEL_ROOT = Path("/tmp/hpcshelf-model")

#: Codes the frozen decomposition must NOT produce.
FORBIDDEN_CODES = ("C017", "C007", "D004", "D007", "C002")

_ok = 0
_fail = 0


def check(label: str, condition: bool, detail: str = "") -> None:
    global _ok, _fail
    if condition:
        _ok += 1
        print(f"  \033[32m✓\033[0m {label}")
    else:
        _fail += 1
        print(f"  \033[31m✗\033[0m {label}")
        for line in detail.splitlines():
            print(f"      {line}")


def platform_root() -> Path:
    root = Path(
        os.environ.get("HPCSHELF_MODEL_ROOT", DEFAULT_MODEL_ROOT)
    ).resolve()
    if not (root / "semantic_validator.py").is_file():
        sys.exit(
            f"invalid HPCSHELF_MODEL_ROOT: {root}\n"
            "Point it at a clone of hpcshelf-model (develop branch)."
        )
    return root


def load(path: Path) -> dict:
    with path.open(encoding="utf-8") as handle:
        return yaml.safe_load(handle)


def codes(result) -> list[str]:
    return [issue.code for issue in result.errors]


def describe(result) -> str:
    return "\n".join(
        f"{issue.code} {issue.type} @ {issue.path}: {issue.message}"
        for issue in result.errors
    )


def main() -> int:
    sys.path.insert(0, str(platform_root()))

    from catalog import InMemoryCatalog, descriptor_digest
    from deployment_planner import (
        DeploymentPlanner,
        HostInfo,
        InMemoryNetworkAllocator,
        PortAllocator,
    )
    from models import (
        ApplicationDeployment,
        ComponentDescriptor,
        HostInventory,
    )
    from semantic_validator import SemanticValidator

    # ----------------------------------------------------------------
    # Descriptors
    # ----------------------------------------------------------------

    print("\n\033[1m[1/4] Descriptors\033[0m")

    component_files = {path.parent.parent.name: path for path in COMPONENT_FILES}
    components = [
        ComponentDescriptor.model_validate(load(path))
        for path in COMPONENT_FILES
    ]
    application = ApplicationDeployment.model_validate(load(APPLICATION_FILE))
    inventory = HostInventory.model_validate(load(HOSTS_FILE))

    for component in components:
        print(f"  · {component.ref}  ({len(component.spec.units)} unit(s))")
    print(f"  · application: {application.metadata.name}")
    print(f"  · hosts: {', '.join(host.id for host in inventory.hosts)}")

    # The catalog pins each descriptor by this digest (artifact.json,
    # `descriptor_digest`). Printing it here keeps the published artefact and the
    # proven descriptor in step: change a descriptor and this value changes.
    print("\n  descriptor digests (for the catalog artifact.json):")
    for component in components:
        print(f"    {component.ref:<24} {descriptor_digest(component)}")

    available_hosts = {host.id for host in inventory.hosts}
    catalog = InMemoryCatalog(components)

    validator = SemanticValidator(
        catalog=catalog,
        available_hosts=available_hosts,
    )

    # ----------------------------------------------------------------
    # 2. Positive proof: semantic validator
    # ----------------------------------------------------------------

    print("\n\033[1m[2/4] SemanticValidator — positive proof\033[0m")

    component_codes: list[str] = []
    for component in components:
        result = validator.validate_component(component)
        component_codes.extend(codes(result))
        check(
            f"validate_component({component.ref}) is error-free",
            result.valid,
            describe(result),
        )

    app_result = validator.validate_application(application)
    check(
        "validate_application(pyhealth-federation) is error-free",
        app_result.valid,
        describe(app_result),
    )

    all_codes = component_codes + codes(app_result)
    for forbidden in FORBIDDEN_CODES:
        check(f"{forbidden} absent (no occurrence)", forbidden not in all_codes)

    # ----------------------------------------------------------------
    # 3. Negative controls: does the validator really catch the violations?
    # ----------------------------------------------------------------

    print("\n\033[1m[3/4] Negative controls\033[0m")

    root_dict = load(component_files["federation-root"])
    app_dict = load(APPLICATION_FILE)

    def catalog_replacing_root(mutated_root_dict: dict) -> "InMemoryCatalog":
        """The real catalog with the root swapped for the mutated version."""
        mutated = ComponentDescriptor.model_validate(mutated_root_dict)
        others = [c for c in components if c.ref != mutated.ref]
        return InMemoryCatalog(others + [mutated])

    def validate_with(catalog_to_use, application_dict: dict):
        return SemanticValidator(
            catalog=catalog_to_use,
            available_hosts=available_hosts,
        ).validate_application(
            ApplicationDeployment.model_validate(application_dict)
        )

    # --- C017: hub and hospital[0] on the same host replica ---------

    collided = copy.deepcopy(root_dict)
    collided["spec"]["nestedComponents"]["federation"]["overlap"]["hospital"][
        "mapping"
    ]["instances"][0]["hostReplica"] = 0
    result = validate_with(catalog_replacing_root(collided), app_dict)
    check(
        "C017 fires when two inner replicas occupy the same host replica",
        "C017" in codes(result),
        describe(result),
    )

    # --- C007: child unit without an overlap mapping ----------------

    missing_overlap = copy.deepcopy(root_dict)
    del missing_overlap["spec"]["nestedComponents"]["federation"]["overlap"][
        "hospital"
    ]
    result = validate_with(catalog_replacing_root(missing_overlap), app_dict)
    check(
        "C007 fires when a child unit has no overlap",
        "C007" in codes(result),
        describe(result),
    )

    # --- D004: placement on a non-root unit -------------------------

    bad_placement = copy.deepcopy(app_dict)
    bad_placement["spec"]["placement"]["hub"] = {
        "instances": [{"replica": 0, "host": "host-hub"}]
    }
    result = validate_with(catalog, bad_placement)
    check(
        "D004 fires when placement references a non-root unit",
        "D004" in codes(result),
        describe(result),
    )

    # --- D007: oneToOne with unequal cardinalities ------------------

    bad_mapping = copy.deepcopy(root_dict)
    bad_mapping["spec"]["nestedComponents"]["federation"]["overlap"]["hospital"][
        "mapping"
    ] = {"type": "oneToOne"}
    result = validate_with(catalog_replacing_root(bad_mapping), app_dict)
    check(
        "D007 fires on oneToOne with unequal cardinalities (2 != 3)",
        "D007" in codes(result),
        describe(result),
    )

    # --- C002 / R3: dependency reaching into another component -------

    hub_only = copy.deepcopy(load(component_files["flower-federation"]))
    hub_only["metadata"]["name"] = "flower-hub-only"
    del hub_only["spec"]["units"]["hospital"]

    hospital_only = copy.deepcopy(load(component_files["flower-federation"]))
    hospital_only["metadata"]["name"] = "flower-hospital-only"
    del hospital_only["spec"]["units"]["hub"]

    split_root = {
        "apiVersion": "hpcshelf.org/v1",
        "kind": "Component",
        "metadata": {"name": "split-root", "version": "0.1"},
        "spec": {
            "units": {
                "institution": {
                    "image": "hpcshelf-unit-base",
                    "replicas": {"min": 1, "max": 8, "default": 3},
                }
            },
            "nestedComponents": {
                "hub_stage": {
                    "component": {"ref": "flower-hub-only:0.1"},
                    "units": {"hub": {"replicas": 1}},
                    "overlap": {
                        "hub": {
                            "hostUnit": "institution",
                            "mapping": {
                                "type": "explicit",
                                "instances": [
                                    {"innerReplica": 0, "hostReplica": 0}
                                ],
                            },
                        }
                    },
                },
                "hospital_stage": {
                    "component": {"ref": "flower-hospital-only:0.1"},
                    "units": {"hospital": {"replicas": 2}},
                    "overlap": {
                        "hospital": {
                            "hostUnit": "institution",
                            "mapping": {
                                "type": "explicit",
                                "instances": [
                                    {"innerReplica": 0, "hostReplica": 1},
                                    {"innerReplica": 1, "hostReplica": 2},
                                ],
                            },
                        }
                    },
                },
            },
        },
    }

    split_components = [
        ComponentDescriptor.model_validate(hub_only),
        ComponentDescriptor.model_validate(hospital_only),
        ComponentDescriptor.model_validate(split_root),
    ]
    split_app = copy.deepcopy(app_dict)
    split_app["spec"]["component"]["ref"] = "split-root:0.1"
    result = validate_with(InMemoryCatalog(split_components), split_app)
    check(
        "C002 fires when hub and hospital live in separate components (R3)",
        "C002" in codes(result),
        describe(result),
    )

    # --- the component model's own four-unit decomposition (Phase 3) --
    #
    # docs/ARCHITECTURE.md 2.1 describes `link`, `node`, `exec-server` and
    # `exec-client`. Two descriptor sets put that decomposition on the platform.
    # Both must fail with the codes the R3/R6 collision predicts, so "the
    # platform will not allow it" becomes a result instead of an argument.

    from model_split import mono_variant, split_variant

    mono_components, mono_application = mono_variant()
    mono_result = validate_with(
        InMemoryCatalog([ComponentDescriptor.model_validate(d) for d in mono_components]),
        mono_application,
    )
    check(
        "C017 fires when the four logical units share one composition (R6)",
        "C017" in codes(mono_result),
        describe(mono_result),
    )

    split_components, split_application = split_variant()
    split_descriptors = [ComponentDescriptor.model_validate(d) for d in split_components]
    comunicacao = next(c for c in split_descriptors if c.ref.startswith("comunicacao"))
    alone = SemanticValidator(
        catalog=InMemoryCatalog([comunicacao]),
        available_hosts=available_hosts,
    ).validate_component(comunicacao)
    check(
        "`comunicacao` {link, node} validates alone (fleet resolves inside it)",
        alone.valid,
        describe(alone),
    )

    split_result = validate_with(InMemoryCatalog(split_descriptors), split_application)
    check(
        "C002 fires when `exec` depends on a sibling component's unit (R3)",
        "C002" in codes(split_result),
        describe(split_result),
    )

    # ----------------------------------------------------------------
    # 4. Positive proof: planner and environment injection
    # ----------------------------------------------------------------

    print("\n\033[1m[4/4] DeploymentPlanner — positive proof\033[0m")

    hosts = [
        HostInfo(
            id=host.id,
            address=host.address,
            vpn_address=host.vpnAddress,
        )
        for host in inventory.hosts
    ]

    planner = DeploymentPlanner(
        catalog=catalog,
        hosts=hosts,
        # The application VPN subnet must contain the preallocated VPN
        # addresses from the inventory (10.201.0.0/24).
        network_allocator=InMemoryNetworkAllocator(
            base_network="10.201.0.0/16",
            prefix_length=24,
        ),
        port_allocator=PortAllocator(),
    )

    plan = planner.plan(application, application_id="phase1-proof")

    roots = [unit for unit in plan.units if unit.runtime.type == "incus"]
    nested = [unit for unit in plan.units if unit.runtime.type == "podman"]

    print("\n  Materialised plan:")
    for unit in sorted(
        plan.units, key=lambda u: (u.component_path, u.unit_name, u.replica)
    ):
        parent = unit.runtime.parent_unit_id or "—"
        print(
            f"    {unit.runtime.type:<6} {unit.unit_name}[{unit.replica}]"
            f" host={unit.host_id} parent={parent}"
        )
        env = " ".join(f"{b.name}={b.value}" for b in unit.environment)
        ports = " ".join(
            f"{s.name}:{s.container_port}->{s.published_port}" for s in unit.services
        )
        if env:
            print(f"           env: {env}")
        if ports:
            print(f"           svc: {ports}")

    print()
    check(
        "3 Incus root units (institution[0..2])",
        len(roots) == 3,
        f"got: {len(roots)}",
    )
    check(
        "root units have no parent_unit_id (R1)",
        all(unit.runtime.parent_unit_id is None for unit in roots),
    )
    check("3 nested Podman units", len(nested) == 3, f"got: {len(nested)}")

    institution = {unit.replica: unit for unit in roots}
    hub = next(unit for unit in nested if unit.unit_name == "hub")
    hospitals = sorted(
        (unit for unit in nested if unit.unit_name == "hospital"),
        key=lambda unit: unit.replica,
    )

    check(
        "hub[0] is nested in institution[0] (host-hub)",
        hub.runtime.parent_unit_id == institution[0].id,
        f"hub.parent={hub.runtime.parent_unit_id} institution[0].id={institution[0].id}",
    )
    check(
        "hospital[0] is nested in institution[1] (host-a)",
        hospitals[0].runtime.parent_unit_id == institution[1].id,
    )
    check(
        "hospital[1] is nested in institution[2] (host-b)",
        hospitals[1].runtime.parent_unit_id == institution[2].id,
    )
    check(
        "hospitals sit on distinct physical hosts",
        hospitals[0].host_id != hospitals[1].host_id,
    )

    fleet = next(service for service in hub.services if service.name == "fleet")
    check(
        "`fleet` service (9092) received a published port",
        fleet.published_port is not None,
        f"container_port={fleet.container_port}",
    )

    for index, hospital in enumerate(hospitals):
        env = {binding.name: binding.value for binding in hospital.environment}
        check(
            f"hospital[{index}]: SUPERLINK_HOST == hub VPN address (R4)",
            env.get("SUPERLINK_HOST") == "10.201.0.1",
            f"got: {env.get('SUPERLINK_HOST')!r}",
        )
        check(
            f"hospital[{index}]: SUPERLINK_PORT == published fleet port (R4)",
            env.get("SUPERLINK_PORT") == str(fleet.published_port),
            f"got: {env.get('SUPERLINK_PORT')!r} expected: {fleet.published_port}",
        )

    # ----------------------------------------------------------------

    print(f"\n\033[1mResult:\033[0m {_ok} passed, {_fail} failed\n")
    return 1 if _fail else 0


if __name__ == "__main__":
    raise SystemExit(main())
