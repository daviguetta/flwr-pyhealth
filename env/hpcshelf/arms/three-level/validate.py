#!/usr/bin/env python3
"""Measure the three-level arm against the HPC Shelf platform, offline.

This is the arm the logical model calls for — one unit per Flower process,
`link`/`node` nested inside `exec-server`/`exec-client` — expressed in the
platform's own descriptors. It answers three questions, all of them with the
platform's code rather than with prose:

  1. **Positive proof.** Does `SemanticValidator` accept the three descriptors and
     the application, and does `DeploymentPlanner` materialise the three levels?
  2. **Why the wiring looks like this.** The vertical bindings
     (`exec-server -> link.appio`, `exec-client -> node.appio`) are NOT declarable:
     `dependencies` resolves inside one `component_path` and the validator refuses
     anything else. The negative controls prove the refusal instead of asserting
     it, so the plan-reading in `images/supervise-exec.sh` stays a necessity
     rather than a shortcut.
  3. **What the arm costs.** `appio` has to be declared as a service for the parent
     unit to learn its address, and a declared service is published on the
     application VPN by `hostagent/endpoint_publisher.py` — recursively, without
     filtering. The same function is run over the grouped arm's descriptors here,
     so the two arms are measured by the same yardstick in the same process.

Platform modules are imported read-only from `HPCSHELF_MODEL_ROOT`. Nothing is
created, changed or written there.

Usage:
    HPCSHELF_MODEL_ROOT=/path/to/hpcshelf-model \\
        /path/to/venv/bin/python env/hpcshelf/arms/three-level/validate.py

The interpreter needs the platform's pinned dependencies
(`pydantic==2.13.5`, `PyYAML==6.0.3`); `scripts/validate_hpcshelf.sh` documents
how that venv is built, and `scripts/validate_hpcshelf_three_level.sh` wraps this
call with the same checks.
"""

from __future__ import annotations

import copy
import os
import sys
import tomllib
from pathlib import Path

import yaml

# The platform is imported read-only; never drop bytecode into its checkout.
sys.dont_write_bytecode = True

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[3]

COMPONENT_FILES = sorted((HERE / "components").glob("*/*/component.yaml"))
APPLICATION_FILE = HERE / "applications" / "pyhealth-federation-three-level.yaml"
HOSTS_FILE = HERE.parent.parent / "hosts.yaml"

#: The grouped arm: same federation, one physical unit per role instead of two.
#: Used only as the baseline of the measurement in step 5.
BASELINE_COMPONENT_FILES = sorted((HERE.parent / "grouped" / "components").glob("*/*/component.yaml"))
BASELINE_APPLICATION_FILE = HERE.parent / "grouped" / "applications" / "pyhealth-federation.yaml"

DEFAULT_MODEL_ROOT = Path("/tmp/hpcshelf-model")

#: Codes this arm must NOT produce. The first two are the R3/R6 pair the arm is
#: built around; the rest guard the wiring conventions it has to keep.
FORBIDDEN_CODES = ("C002", "C017", "C007", "D004", "D007", "D012", "C016")

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
    root = Path(os.environ.get("HPCSHELF_MODEL_ROOT", DEFAULT_MODEL_ROOT)).resolve()
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
    from models import ApplicationDeployment, ComponentDescriptor, HostInventory
    from semantic_validator import SemanticValidator

    # ----------------------------------------------------------------
    # 1. Descriptors
    # ----------------------------------------------------------------

    print("\n\033[1m[1/5] Descriptors — three levels\033[0m")

    component_files = {path.parent.parent.name: path for path in COMPONENT_FILES}
    components = [
        ComponentDescriptor.model_validate(load(path)) for path in COMPONENT_FILES
    ]
    application = ApplicationDeployment.model_validate(load(APPLICATION_FILE))
    inventory = HostInventory.model_validate(load(HOSTS_FILE))

    baseline_components = [
        ComponentDescriptor.model_validate(load(path))
        for path in BASELINE_COMPONENT_FILES
    ]
    baseline_application = ApplicationDeployment.model_validate(
        load(BASELINE_APPLICATION_FILE)
    )

    for component in components:
        units = ", ".join(sorted(component.spec.units))
        print(f"  · {component.ref:<24} units: {units}")
    print(f"  · application: {application.metadata.name}")
    print(f"  · hosts: {', '.join(host.id for host in inventory.hosts)}")

    print("\n  descriptor digests (for the catalog artifact.json):")
    for component in components:
        print(f"    {component.ref:<24} {descriptor_digest(component)}")

    available_hosts = {host.id for host in inventory.hosts}
    catalog = InMemoryCatalog(components + baseline_components)

    validator = SemanticValidator(catalog=catalog, available_hosts=available_hosts)

    # ----------------------------------------------------------------
    # 2. Positive proof
    # ----------------------------------------------------------------

    print("\n\033[1m[2/5] SemanticValidator — positive proof\033[0m")

    collected: list[str] = []
    for component in components:
        result = validator.validate_component(component)
        collected.extend(codes(result))
        check(
            f"validate_component({component.ref}) is error-free",
            result.valid,
            describe(result),
        )

    app_result = validator.validate_application(application)
    collected.extend(codes(app_result))
    check(
        f"validate_application({application.metadata.name}) is error-free",
        app_result.valid,
        describe(app_result),
    )

    for forbidden in FORBIDDEN_CODES:
        check(f"{forbidden} absent (no occurrence)", forbidden not in collected)

    # ----------------------------------------------------------------
    # 3. Negative controls — why the wiring is what it is
    # ----------------------------------------------------------------

    print("\n\033[1m[3/5] Negative controls\033[0m")

    exec_dict = load(component_files["exec"])
    root_dict = load(component_files["three-level-root"])
    app_dict = load(APPLICATION_FILE)

    def catalog_replacing(name: str, mutated: dict) -> "InMemoryCatalog":
        """The real catalog with component `name` swapped for a mutated version."""
        replacement = ComponentDescriptor.model_validate(mutated)
        others = [c for c in components if c.metadata.name != name]
        return InMemoryCatalog(others + baseline_components + [replacement])

    def validate_app(catalog_to_use, application_dict: dict):
        return SemanticValidator(
            catalog=catalog_to_use, available_hosts=available_hosts
        ).validate_application(
            ApplicationDeployment.model_validate(application_dict)
        )

    # --- C002: the vertical binding, declared the way the model wants it ---
    #
    # This is the arm's central finding. `exec-server` is the parent that hosts
    # `link`, and the only honest way to say "exec-server calls link" in a
    # descriptor is a dependency — which the validator refuses, because the target
    # is a unit of another component. The refusal is what makes reading the unit
    # plan (`UnitPlan.children[].services[]`) necessary rather than convenient.

    declared_vertical = copy.deepcopy(exec_dict)
    declared_vertical["spec"]["units"]["exec-server"]["dependencies"] = {
        "comm": {
            "target": {"unit": "link", "service": "appio"},
            "environment": {"host": "APPIO_HOST", "port": "APPIO_PORT"},
        }
    }
    result = validate_app(
        catalog_replacing("exec", declared_vertical), app_dict
    )
    check(
        "C002 fires when the parent declares the vertical appio binding (R3)",
        "C002" in codes(result),
        describe(result),
    )

    # --- D012: an inner replica with no host replica ---

    unmapped = copy.deepcopy(exec_dict)
    node_instances = unmapped["spec"]["nestedComponents"]["comm"]["overlap"]["node"][
        "mapping"
    ]["instances"]
    del node_instances[1]
    result = validate_app(catalog_replacing("exec", unmapped), app_dict)
    check(
        "D012 fires when a node replica has no exec-client to sit in",
        "D012" in codes(result),
        describe(result),
    )

    # --- C017: link and node on the same host replica ---

    collided = copy.deepcopy(exec_dict)
    collided["spec"]["nestedComponents"]["comm"]["units"]["node"]["replicas"] = 1
    collided["spec"]["nestedComponents"]["comm"]["overlap"]["node"] = {
        "hostUnit": "exec-server",
        "mapping": {
            "type": "explicit",
            "instances": [{"innerReplica": 0, "hostReplica": 0}],
        },
    }
    result = validate_app(catalog_replacing("exec", collided), app_dict)
    check(
        "C017 fires when `node` is nested in the same host replica as `link` (R6)",
        "C017" in codes(result),
        describe(result),
    )

    # --- C017 again: the whole federation on ONE host ---
    #
    # The nested composition admits one inner replica per host replica, so the
    # server site and a hospital site cannot share a host: a single-host
    # federation would have to put `exec-server` and `exec-client` on the same
    # `institution`, which is exactly what C017 refuses. Co-location through
    # SEPARATE compositions is allowed by the validator, but it severs the
    # `node -> link` binding, because a dependency resolves only inside one
    # `component_path` (the C002 control above, and `../grouped/model_split.py`, already
    # establish that half). So: one host = one role = one data boundary.

    single_host = copy.deepcopy(root_dict)
    single_host["spec"]["nestedComponents"]["ex"]["overlap"]["exec-client"][
        "mapping"
    ]["instances"][0]["hostReplica"] = 0
    result = validate_app(catalog_replacing("three-level-root", single_host), app_dict)
    check(
        "C017 fires when a whole federation is placed on a single host replica",
        "C017" in codes(result),
        describe(result),
    )

    # ----------------------------------------------------------------
    # 4. Positive proof: the three levels materialise
    # ----------------------------------------------------------------

    print("\n\033[1m[4/5] DeploymentPlanner — the three levels\033[0m")

    hosts = [
        HostInfo(id=host.id, address=host.address, vpn_address=host.vpnAddress)
        for host in inventory.hosts
    ]

    def make_planner() -> "DeploymentPlanner":
        """A planner with fresh allocators.

        The VPN allocator assigns one /24 per application instance, so planning the
        baseline arm with the same instance would put it in a different subnet and
        the preallocated addresses in `hosts.yaml` would fall outside it. Each arm
        is planned as its own application, which is also what a real deployment
        would do.
        """
        return DeploymentPlanner(
            catalog=catalog,
            hosts=[
                HostInfo(id=host.id, address=host.address, vpn_address=host.vpnAddress)
                for host in inventory.hosts
            ],
            # The application VPN subnet must contain the preallocated VPN addresses
            # from the inventory (10.201.0.0/16 with a /24 per host).
            network_allocator=InMemoryNetworkAllocator(
                base_network="10.201.0.0/16", prefix_length=24
            ),
            port_allocator=PortAllocator(),
        )

    planner = make_planner()
    plan = planner.plan(application, application_id="comparison-three-level")
    by_id = {unit.id: unit for unit in plan.units}

    print("\n  Materialised plan:")
    for unit in sorted(
        plan.units, key=lambda u: (len(u.component_path.split("/")), u.component_path, u.replica)
    ):
        depth = len(unit.component_path.split("/"))
        parent = by_id.get(unit.runtime.parent_unit_id or "")
        parent_name = (
            f"{parent.unit_name}[{parent.replica}]" if parent else "—"
        )
        print(
            f"    {'  ' * (depth - 1)}{unit.runtime.type:<6} {unit.unit_name}[{unit.replica}]"
            f"  path={unit.component_path} host={unit.host_id} parent={parent_name}"
        )
        for service in unit.services:
            print(
                f"    {'  ' * (depth - 1)}        svc {service.name}:"
                f"{service.container_port} -> VPN {service.vpn_address}:{service.published_port}"
            )

    roots = [unit for unit in plan.units if unit.runtime.type == "incus"]
    exec_server = next(unit for unit in plan.units if unit.unit_name == "exec-server")
    exec_clients = sorted(
        (unit for unit in plan.units if unit.unit_name == "exec-client"),
        key=lambda unit: unit.replica,
    )
    link = next(unit for unit in plan.units if unit.unit_name == "link")
    nodes = sorted(
        (unit for unit in plan.units if unit.unit_name == "node"),
        key=lambda unit: unit.replica,
    )
    institutions = {unit.replica: unit for unit in roots}

    print()
    check("3 Incus root units (institution[0..2])", len(roots) == 3, f"got {len(roots)}")
    check("9 units in total (3 levels x 3 sites)", len(plan.units) == 9, f"got {len(plan.units)}")
    check(
        "root units have no parent_unit_id (R1)",
        all(unit.runtime.parent_unit_id is None for unit in roots),
    )
    root_ids = {unit.id for unit in roots}
    check(
        "every non-root unit is Podman with a parent (2 nesting levels)",
        all(
            unit.runtime.type == "podman" and unit.runtime.parent_unit_id
            for unit in plan.units
            if unit.id not in root_ids
        ),
    )

    check(
        "exec-server[0] is nested in institution[0] (host-hub)",
        exec_server.runtime.parent_unit_id == institutions[0].id,
        f"parent={exec_server.runtime.parent_unit_id} institution[0]={institutions[0].id}",
    )
    check(
        "link[0] is nested in exec-server[0] (level 3)",
        link.runtime.parent_unit_id == exec_server.id,
    )
    check(
        "exec-client[i] is nested in institution[i+1]",
        all(
            client.runtime.parent_unit_id == institutions[index + 1].id
            for index, client in enumerate(exec_clients)
        ),
    )
    check(
        "node[i] is nested in exec-client[i] (level 3)",
        all(
            node.runtime.parent_unit_id == client.id
            for node, client in zip(nodes, exec_clients)
        ),
    )
    check(
        "node[i].replica == exec-client[i].replica (partition identity alignment)",
        all(node.replica == client.replica for node, client in zip(nodes, exec_clients)),
        "the SuperNode publishes partition-id = its own plan replica, and the "
        "ClientApp in the parent unit reads it from context.node_config",
    )
    check(
        "a nested unit shares the physical host of its parent (the mapping is intra-host)",
        all(
            child.host_id == by_id[child.runtime.parent_unit_id].host_id
            for child in (link, *nodes)
        ),
    )
    check(
        "the server site is alone on its host (no node on host-hub)",
        link.host_id == "host-hub"
        and all(node.host_id != "host-hub" for node in nodes),
        f"link={link.host_id} nodes={[node.host_id for node in nodes]}",
    )
    check(
        "nodes sit on distinct physical hosts",
        len({node.host_id for node in nodes}) == len(nodes),
        f"got {[node.host_id for node in nodes]}",
    )

    # --- the horizontal binding: node -> link.fleet ---

    fleet = next(service for service in link.services if service.name == "fleet")
    for index, node in enumerate(nodes):
        env = {binding.name: binding.value for binding in node.environment}
        check(
            f"node[{index}]: FL_SUPERLINK_HOST == link VPN address (R4)",
            env.get("FL_SUPERLINK_HOST") == fleet.vpn_address,
            f"got {env.get('FL_SUPERLINK_HOST')!r} expected {fleet.vpn_address!r}",
        )
        check(
            f"node[{index}]: FL_SUPERLINK_PORT == published fleet port (R5)",
            env.get("FL_SUPERLINK_PORT") == str(fleet.published_port),
            f"got {env.get('FL_SUPERLINK_PORT')!r} expected {fleet.published_port}",
        )

    # --- published ports are unique per host ---

    per_host: dict[str, list[int]] = {}
    for unit in plan.units:
        for service in unit.services:
            per_host.setdefault(unit.host_id, []).append(service.published_port)
    check(
        "published ports are unique within each host",
        all(len(ports) == len(set(ports)) for ports in per_host.values()),
        f"{per_host}",
    )

    # --- declared cardinalities cannot drift ---

    node_unit = next(c for c in components if c.metadata.name == "comunicacao")
    declared_node = int(node_unit.spec.units["node"].application.environment[
        "PYHEALTH_NUM_PARTITIONS"
    ])
    exec_component = next(c for c in components if c.metadata.name == "exec")
    declared_server = int(
        exec_component.spec.units["exec-server"].application.environment[
            "PYHEALTH_NUM_PARTITIONS"
        ]
    )
    with (REPO_ROOT / "pyproject.toml").open("rb") as handle:
        app_config = tomllib.load(handle)["tool"]["flwr"]["app"]["config"]
    declared_app = int(app_config["num-partitions"])

    print()
    check(
        "node replicas == comunicacao num-partitions (no node without a partition)",
        len(nodes) == declared_node,
        f"nodes={len(nodes)} declared={declared_node}",
    )
    check(
        "exec-server and node agree on num-partitions",
        declared_server == declared_node,
        f"exec-server={declared_server} node={declared_node}",
    )
    check(
        "the app's num-partitions == the deployment's num-partitions",
        declared_app == declared_node,
        f"pyproject={declared_app} descriptors={declared_node} — a mismatch changes "
        "the DP sampling budget and the reported client count without failing",
    )

    # ----------------------------------------------------------------
    # 5. What the arm costs: the appio exposure, measured
    # ----------------------------------------------------------------

    print("\n\033[1m[5/5] Cost of the split — `appio` on the application VPN\033[0m")

    appio_endpoints = [
        (unit, service)
        for unit in plan.units
        for service in unit.services
        if service.name == "appio"
    ]

    print("\n  arm `3 níveis` (this directory):")
    for unit, service in sorted(appio_endpoints, key=lambda pair: pair[0].unit_name):
        print(
            f"    {unit.unit_name}[{unit.replica}] appio:{service.container_port}"
            f" -> {service.vpn_address}:{service.published_port}  (host {unit.host_id})"
        )
    print(
        "    The parent namespace also reaches it at 127.0.0.1:<published_port>,"
        " which is how the exec supervisor dials it."
    )

    check(
        "the vertical address exists: every SuperExec's child exposes an `appio` endpoint",
        sorted(unit.unit_name for unit, _ in appio_endpoints)
        == sorted(["link"] + ["node"] * len(nodes)),
        f"got {[(unit.unit_name, unit.replica) for unit, _ in appio_endpoints]}",
    )
    check(
        "COST: every `appio` endpoint is published on the application VPN, not on loopback",
        all(service.vpn_address != "127.0.0.1" for _, service in appio_endpoints),
        "hostagent/endpoint_publisher.build_publications is recursive and does not "
        "filter: a declared service of a descendant is published for every host of "
        "the federation. This is what M103 protects and what the split spends.",
    )
    check(
        "COST: `control` is not published (undeclared, so never mapped)",
        all(service.name != "control" for unit in plan.units for service in unit.services),
    )

    baseline_plan = make_planner().plan(
        baseline_application, application_id="comparison-grouped"
    )
    baseline_appio = [
        (unit, service)
        for unit in baseline_plan.units
        for service in unit.services
        if service.name == "appio"
    ]
    baseline_fleet = [
        (unit, service)
        for unit in baseline_plan.units
        for service in unit.services
        if service.name == "fleet"
    ]

    print("\n  arm `agrupado` (baseline: ../grouped/components/flower-federation):")
    for unit, service in baseline_fleet:
        print(
            f"    {unit.unit_name}[{unit.replica}] fleet:{service.container_port}"
            f" -> {service.vpn_address}:{service.published_port}  (host {unit.host_id})"
        )
    print("    (no `appio` declared: the SuperExec shares the container, so it is loopback)")

    check(
        "baseline publishes `fleet` and nothing else (no appio endpoint exists)",
        not baseline_appio and len(baseline_fleet) == 1,
        f"appio={len(baseline_appio)} fleet={len(baseline_fleet)}",
    )

    print("\n  \033[1mComparison\033[0m")
    print("    arm                units  appio published  per-host  data in transport image")
    print(
        f"    agrupado (baseline) {len(baseline_plan.units):>4}  "
        f"{len(baseline_appio)} (loopback)     fleet     n/a (one image)"
    )
    print(
        f"    3 níveis (this arm) {len(plan.units):>4}  "
        f"{len(appio_endpoints)} (VPN)          fleet     no"
    )
    print(
        "\n  Reading: the split buys one process per unit — and therefore one"
        "\n  responsibility per container — and pays for it by widening the reachable"
        "\n  surface of `appio` from a loopback inside one container to the whole"
        "\n  application VPN. `scope: parent` on a service (absent from"
        "\n  `ServiceDefinition` today) is the missing capability that would make the"
        "\n  split free; see docs/HPC_SHELF_DECISIONS.md, section 5."
    )

    # ----------------------------------------------------------------

    print(f"\n\033[1mResult:\033[0m {_ok} passed, {_fail} failed\n")
    return 1 if _fail else 0


if __name__ == "__main__":
    raise SystemExit(main())
