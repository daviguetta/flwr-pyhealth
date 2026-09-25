#!/usr/bin/env python3
"""Publish the federation unit images and materialise the HPC Shelf catalog.

Pushes `flower-hub` and `flower-hospital` to an OCI registry, reads back the
digest **the registry reports** (the only authority for what the catalog may
pin), writes `artifact.json` next to each `component.yaml`, and verifies the
result with the platform's own `FilesystemCatalog`, integrity checks and
`DeploymentPlanner`.

Nothing here is specific to the platform's registry. Point `--registry` at a
local rehearsal registry first, then at the platform's; the digests differ
between the two and the catalog must pin whichever registry actually serves the
images.

Usage:
    HPCSHELF_MODEL_ROOT=/path/to/hpcshelf-model \\
        /path/to/venv/bin/python env/hpcshelf/publish.py --registry localhost:5000

`scripts/publish_hpcshelf_images.sh` wraps the call with the environment checks.

This writes to the registry it is given and to `--catalog-root` (default
`build/hpcshelf-catalog`, which is not versioned). Publication to the platform's
registry requires explicit operator authorisation; see
env/hpcshelf/images/README.md.
"""

from __future__ import annotations

import argparse
import copy
import json
import os
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
COMPONENT_FILES = sorted((HERE / "components").glob("*/*/component.yaml"))
HOSTS_FILE = HERE / "hosts.yaml"
APPLICATION_FILE = HERE / "applications" / "pyhealth-federation.yaml"

DEFAULT_MODEL_ROOT = Path("/tmp/hpcshelf-model")

#: Local build tag -> published repository name.
ROLES = {"hub": "flower-hub", "hospital": "flower-hospital"}

#: The root component's Incus unit uses the platform's own base image. Its
#: digest and Incus archive belong to the platform's catalog, so they are reused
#: by exact digest rather than rebuilt here.
DEFAULT_UNIT_BASE_ARTIFACT = (
    "catalog_data/components/root-two-host/1.4/artifact.json"
)
UNIT_BASE_REFERENCE = "hpcshelf-unit-base"

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


def run(argv: list[str], **kwargs) -> subprocess.CompletedProcess:
    return subprocess.run(argv, capture_output=True, text=True, **kwargs)


def platform_root() -> Path:
    root = Path(
        os.environ.get("HPCSHELF_MODEL_ROOT", DEFAULT_MODEL_ROOT)
    ).resolve()
    if not (root / "catalog.py").is_file():
        sys.exit(
            f"invalid HPCSHELF_MODEL_ROOT: {root}\n"
            "Point it at a clone of hpcshelf-model (develop branch)."
        )
    return root


def load_yaml(path: Path) -> dict:
    with path.open(encoding="utf-8") as handle:
        return yaml.safe_load(handle)


def registry_digest(registry: str, repository: str, tag: str) -> str | None:
    """Ask the registry what digest it stored, independently of the client.

    `podman push --digestfile` already reports it; this is a second, independent
    reading straight from the registry API, so a client-side mistake cannot
    become a pinned digest.
    """
    url = f"http://{registry}/v2/{repository}/manifests/{tag}"
    request = urllib.request.Request(url, method="HEAD")
    request.add_header(
        "Accept",
        "application/vnd.oci.image.manifest.v1+json,"
        "application/vnd.docker.distribution.manifest.v2+json",
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            return response.headers.get("Docker-Content-Digest")
    except (urllib.error.URLError, OSError):
        return None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--registry",
        required=True,
        help="registry host[:port] without a scheme, e.g. localhost:5000",
    )
    parser.add_argument("--project", default="pyhealth")
    parser.add_argument("--tag", default="0.1.0")
    parser.add_argument(
        "--catalog-root",
        default=str(ROOT / "build" / "hpcshelf-catalog"),
        help="where the components/<name>/<version>/ tree is written",
    )
    parser.add_argument(
        "--insecure",
        action="store_true",
        help="push with --tls-verify=false (local rehearsal registries)",
    )
    parser.add_argument(
        "--unit-base-artifact",
        default=None,
        help="platform catalog artifact.json to reuse for the root unit's image",
    )
    args = parser.parse_args()

    sys.path.insert(0, str(platform_root()))

    from catalog import descriptor_digest
    from catalog_repository import FilesystemCatalog
    from deployment_planner import (
        DeploymentPlanner,
        HostInfo,
        InMemoryNetworkAllocator,
        PortAllocator,
    )
    from models import ApplicationDeployment, ComponentDescriptor, HostInventory

    registry = args.registry.rstrip("/")
    catalog_root = Path(args.catalog_root).resolve()

    if shutil.which("podman") is None:
        sys.exit("podman is required")

    components: dict[str, tuple[ComponentDescriptor, Path]] = {}
    for path in COMPONENT_FILES:
        descriptor = ComponentDescriptor.model_validate(load_yaml(path))
        components[descriptor.ref] = (descriptor, path)

    # ----------------------------------------------------------------
    # 1. Push the unit images
    # ----------------------------------------------------------------

    print(f"\n\033[1m[1/4] Push to {registry}\033[0m")

    digests: dict[str, str] = {}
    references: dict[str, str] = {}

    for role, repository in ROLES.items():
        local = f"localhost/{repository}:{args.tag}"
        remote = f"{registry}/{args.project}/{repository}:{args.tag}"
        references[role] = remote

        if run(["podman", "image", "exists", local]).returncode != 0:
            check(f"{local} exists locally", False, "run scripts/build_hpcshelf_images.sh")
            continue

        check(f"{local} exists locally", True)

        run(["podman", "tag", local, remote])

        push = ["podman", "push"]
        if args.insecure:
            push.append("--tls-verify=false")
        digest_file = Path(f"/tmp/hpcshelf-digest-{role}.txt")
        digest_file.unlink(missing_ok=True)
        push += ["--digestfile", str(digest_file), remote]

        result = run(push)
        pushed = result.returncode == 0 and digest_file.is_file()
        check(
            f"pushed {remote}",
            pushed,
            (result.stderr or result.stdout or "").strip()[-800:],
        )
        if not pushed:
            continue

        client_digest = digest_file.read_text(encoding="utf-8").strip()
        digest_file.unlink(missing_ok=True)

        reported = registry_digest(registry, f"{args.project}/{repository}", args.tag)
        if reported is None:
            digests[role] = client_digest
            check(
                f"{repository}: registry digest confirmed",
                False,
                "registry did not answer HEAD /v2/.../manifests/...; "
                f"falling back to the client digest {client_digest}",
            )
        else:
            digests[role] = reported
            check(
                f"{repository}: registry digest confirms the client's",
                reported == client_digest,
                f"registry={reported} client={client_digest}",
            )
        print(f"    {remote}@{digests[role]}")

    if len(digests) != len(ROLES):
        print("\ncannot build the catalog without both digests\n")
        return 1

    # ----------------------------------------------------------------
    # 2. Write the catalog tree
    # ----------------------------------------------------------------

    print(f"\n\033[1m[2/4] Catalog artifacts -> {catalog_root}\033[0m")

    unit_base_artifact = Path(
        args.unit_base_artifact
        or platform_root() / DEFAULT_UNIT_BASE_ARTIFACT
    )
    if not unit_base_artifact.is_file():
        check(
            "platform unit-base artifact available for the root unit",
            False,
            f"{unit_base_artifact} not found; pass --unit-base-artifact. The root "
            "component's Incus unit uses the platform's own base image, whose "
            "digest and archive this repository does not own.",
        )
        return 1

    platform_artifact = json.loads(unit_base_artifact.read_text(encoding="utf-8"))
    base_entry = next(iter(platform_artifact["images"].values()))
    check(
        f"platform unit-base artifact reused by digest ({base_entry['digest'][:19]}…)",
        base_entry["reference"] == UNIT_BASE_REFERENCE,
        f"unexpected reference: {base_entry['reference']}",
    )

    for ref, (descriptor, source) in components.items():
        # The published descriptor must carry the reference of the registry that
        # actually serves the image: CatalogComponentArtifact rejects an artifact
        # whose image reference differs from the descriptor's `image` field.
        raw = copy.deepcopy(load_yaml(source))

        if descriptor.metadata.name == "flower-federation":
            declared = descriptor.spec.units["hub"].image
            if not declared.startswith(f"{registry}/"):
                print(
                    f"\n  note: {descriptor.ref} declares '{declared}'.\n"
                    f"        The PUBLISHED descriptor is retargeted to "
                    f"'{registry}/{args.project}/…' so that the catalog's\n"
                    f"        reference matches the registry serving the images. "
                    f"This produces a\n        rehearsal catalog, not the production one, "
                    f"and its descriptor_digest\n        therefore differs from the "
                    f"production value."
                )
            for role, repository in ROLES.items():
                raw["spec"]["units"][role]["image"] = references[role]
            images = {
                role: {"reference": references[role], "digest": digests[role]}
                for role in ROLES
            }
        else:
            # The root unit's image is the platform's; only the unit key changes,
            # because our root descriptor names it `institution`.
            images = {}
            for unit_name, unit in descriptor.spec.units.items():
                if unit.image != base_entry["reference"]:
                    check(
                        f"root unit '{unit_name}' uses the platform base image",
                        False,
                        f"descriptor says '{unit.image}', artifact says "
                        f"'{base_entry['reference']}'",
                    )
                    return 1
                images[unit_name] = base_entry

        published = ComponentDescriptor.model_validate(raw)
        digest = descriptor_digest(published)

        target_dir = (
            catalog_root
            / "components"
            / published.metadata.name
            / published.metadata.version
        )
        target_dir.mkdir(parents=True, exist_ok=True)
        (target_dir / "component.yaml").write_text(
            yaml.safe_dump(raw, sort_keys=False, allow_unicode=True),
            encoding="utf-8",
        )
        (target_dir / "artifact.json").write_text(
            json.dumps(
                {"descriptor_digest": digest, "images": images},
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        print(f"    components/{published.metadata.name}/{published.metadata.version}/")
        print(f"      descriptor_digest {digest}")
        for unit_name, image in images.items():
            print(f"      {unit_name:<12} {image['reference']}@{image['digest']}")

    # ----------------------------------------------------------------
    # 3. Verify with the platform's own catalog code
    # ----------------------------------------------------------------

    print("\n\033[1m[3/4] Platform catalog verification\033[0m")

    catalog = FilesystemCatalog(catalog_root)

    for ref, (descriptor, _) in components.items():
        try:
            artifact = catalog.resolve_component(ref)
        except Exception as exc:  # noqa: BLE001 - report any catalog failure verbatim
            check(f"resolve_component({ref})", False, f"{type(exc).__name__}: {exc}")
            continue

        check(f"resolve_component({ref}) passes integrity checks", True)
        check(
            f"{ref}: descriptor_digest matches the descriptor on disk",
            artifact.descriptor_digest == descriptor_digest(artifact.descriptor),
        )
        for unit_name, image in artifact.images.items():
            expected = (
                f"{image.reference}@{image.digest}"
                if image.digest
                else image.reference
            )
            check(
                f"{ref}/{unit_name}: runtime reference is digest-pinned",
                image.runtime_reference == expected and "@sha256:" in expected,
                f"runtime_reference={image.runtime_reference}",
            )

    # ----------------------------------------------------------------
    # 4. Plan from the published catalog
    # ----------------------------------------------------------------

    print("\n\033[1m[4/4] DeploymentPlanner over the published catalog\033[0m")

    inventory = HostInventory.model_validate(load_yaml(HOSTS_FILE))
    application = ApplicationDeployment.model_validate(load_yaml(APPLICATION_FILE))
    hosts = [
        HostInfo(id=host.id, address=host.address, vpn_address=host.vpnAddress)
        for host in inventory.hosts
    ]
    planner = DeploymentPlanner(
        catalog=catalog,
        hosts=hosts,
        network_allocator=InMemoryNetworkAllocator(
            base_network="10.201.0.0/16", prefix_length=24
        ),
        port_allocator=PortAllocator(),
    )

    try:
        plan = planner.plan(application, application_id="publish-rehearsal")
    except Exception as exc:  # noqa: BLE001
        check("planner accepts the published catalog", False, f"{type(exc).__name__}: {exc}")
        print(f"\n\033[1mResult:\033[0m {_ok} passed, {_fail} failed\n")
        return 1

    check("planner accepts the published catalog", True)

    roots = [unit for unit in plan.units if unit.runtime.type == "incus"]
    nested = [unit for unit in plan.units if unit.runtime.type == "podman"]
    check("3 Incus root units", len(roots) == 3)
    check("3 nested Podman units", len(nested) == 3)

    root_image = roots[0].image
    check(
        "root unit image is pinned to the platform archive digest",
        "@sha256:" in root_image,
        f"image={root_image}",
    )
    print(f"    root image: {root_image}")
    for unit in sorted(nested, key=lambda u: (u.unit_name, u.replica)):
        print(f"    {unit.unit_name}[{unit.replica}] image: {unit.image}")

    # ----------------------------------------------------------------

    print(f"\n\033[1mResult:\033[0m {_ok} passed, {_fail} failed")
    print("\nFor the platform's registry, re-run the same command with")
    print(f"  --registry <catalog host> --project <confirmed project path>")
    print("after obtaining authorisation and credentials, then publish the tree at")
    print(f"  {catalog_root}")
    print("with the platform's catalog service.\n")

    return 1 if _fail else 0


if __name__ == "__main__":
    raise SystemExit(main())
