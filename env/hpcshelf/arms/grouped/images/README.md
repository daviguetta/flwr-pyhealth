# `env/hpcshelf/arms/grouped/images/` — the federation unit images

The two OCI images the HPC Shelf platform pulls to materialise the federation's
Podman units. Both are leaves: they host no nested components.

| Image | Unit | Runs | Published |
| --- | --- | --- | --- |
| `flower-hub` | `hub` | SuperLink + SuperExec (ServerApp) | `fleet` 9092 |
| `flower-hospital` | `hospital[*]` | SuperNode + SuperExec (ClientApp) | nothing |

Both are built by `Containerfile.flower-unit`, from the same base, differing only
in the supervisor script they carry. See
[`docs/HPC_SHELF_INTEGRATION.md`](../../../../docs/HPC_SHELF_INTEGRATION.md)
section 4 for why a Flower process pair shares one container.

## Build

```bash
scripts/build_hpcshelf_images.sh
```

The script builds the platform base locally when it is absent, because the
published base lives in the platform's own registry:

```text
localhost/podman-unit-base:local     from $HPCSHELF_MODEL_ROOT/podman-unit-base
localhost/flower-hub:0.1.0           <- localhost/pyhealth-flower-superexec:0.1.0
localhost/flower-hospital:0.1.0      <- localhost/pyhealth-flower-superexec:0.1.0
```

The application layer comes from `Containerfile.superexec` at the repository
root, which is already how this project containerises Flower. Build it first
with `scripts/deploy_containers.sh build`.

## Why the image carries two interpreters

This is a requirement, not an accident:

| Interpreter | Python | protobuf | Runs |
| --- | --- | --- | --- |
| `/opt/hpcshelf/venv` | 3.13 | 7.36.1 | the platform's UnitAgent |
| `/python/venv` | 3.13 | 6.33.6 | the Flower processes |

The platform's generated `*_pb2` modules were produced with protobuf gencode
**7.35.1**; Flower 1.34 pins a protobuf **6.x** runtime. Loading one into the
other raises:

```text
VersionError: Detected incompatible Protobuf Gencode/Runtime versions when
loading common.proto: gencode 7.35.1 runtime 6.33.6.
```

So the two dependency sets cannot share an interpreter. The UnitAgent's venv is
rebuilt from the platform's own pinned `requirements.txt` rather than copied,
because a virtualenv is not relocatable across base images — the platform base's
`venv/bin/python` points at `/usr/bin/python3.12`, which this image does not have.

The images are also **not** built `FROM podman-unit-base`, for two reasons: that
base has no Flower, PyHealth or Torch; and the application's protobuf 6.x cannot
share the interpreter the platform's UnitAgent needs. (The Python version is no
longer one of them — the project's floor dropped to `>=3.12` on 2026-10-03, which
is what makes `podman-unit-base` usable as the base for a **nesting** level.)

## Smoke test

```bash
scripts/smoke_hpcshelf_images.sh
```

Bypasses the UnitAgent (a real unit plan can only be produced by the platform)
and exercises what the platform would otherwise drive: the hub comes up with the
Fleet API on `0.0.0.0:9092` and the Runtime API on loopback only; two hospitals
register as distinct nodes with their own partition ids; and a hospital with no
partition identity refuses to start.

## Publishing

`scripts/publish_hpcshelf_images.sh` pushes the images, reads back the digest the
**registry** reports, writes the catalog tree and verifies it with the platform's
own `FilesystemCatalog`, integrity checks and `DeploymentPlanner`.

### Rehearsed end to end, against a local registry

```bash
podman run -d --name hpcshelf-registry -p 127.0.0.1:5000:5000 registry:2
scripts/publish_hpcshelf_images.sh --registry localhost:5000 --insecure
```

**18 checks, 0 failures.** The pushes succeeded and the registry's digest was
confirmed independently, straight from `HEAD /v2/…/manifests/…`, not only from
the client's `--digestfile` — a client-side mistake cannot become a pinned
digest. The catalog was then assembled and re-read by the platform's own code,
which accepted both components, confirmed the `descriptor_digest`, pinned every
image by digest, and planned the application from the published catalog:
3 Incus root units, 3 nested Podman units, the root image bound to the platform
archive digest.

One behaviour worth knowing: `CatalogComponentArtifact` **rejects** an artifact
whose image reference differs from the descriptor's `image` field. Publishing
somewhere other than the declared registry therefore rewrites the published
descriptor (and changes its `descriptor_digest`). The script says so out loud when
it happens, so a rehearsal cannot be mistaken for the production catalog.

### What the real publication still needs

1. **Authorisation and credentials** for the platform's registry. The platform's
   own developer workflow is explicit that registry writes require explicit
   operator scope.
2. **The confirmed project path.** The descriptors declare
   `catalog.hpcshelf.org/pyhealth/…`. That is an assumption on this side, not a
   fact; it must be confirmed before anything is pushed.
3. **The registry-reported digest**, which replaces the rehearsal digests.

Then, and only then:

```bash
scripts/publish_hpcshelf_images.sh --registry catalog.hpcshelf.org --project pyhealth
```

For that registry the descriptor is **not** retargeted, so the
`descriptor_digest` is the value already recorded in this repository:

```text
flower-federation:0.1    sha256:2f7772db5a9b236dfa3d6cd707e2929f38db7ae6f091f961d70b1e7837e96d93
```

### The root component's image belongs to the platform

`federation-root`'s `institution` unit uses `hpcshelf-unit-base`. Its digest and
its 501 MB Incus unified archive belong to the platform's catalog, so the script
**reuses them by exact digest** from
`<platform>/catalog_data/components/root-two-host/1.4/artifact.json` instead of
rebuilding anything. Reusing an unchanged image by exact digest is what the
platform's developer workflow prescribes; if the platform moves that base, the
source artifact is what has to change.

## Open items

| Item | Detail |
| --- | --- |
| **Runs as root** | The image follows the platform base, which runs units as root. The application image itself runs as `app`. For units that read patient data this should be narrowed once the UnitAgent no longer needs root — a real hardening item for Phase 5. |
| **`HPCSHELF_PODMAN_RUNTIME=mock`** | These units are leaves, so the Agent never materialises a child and the image ships no Podman binary. If a hub or hospital unit ever needs a nested child, the image must install Podman and switch to `real`. |
| **`--insecure`** | Every supervisor runs Flower in cleartext. Phase 5. |
| ~~**No `partition-id` injection yet**~~ **Resolved 2026-09-25** | The supervisor reads `partition-id` from the unit's own plan (`HPCSHELF_UNIT_PLAN` → `plan.replica`), which the platform injects for every unit, root and nested. `PYHEALTH_PARTITION_ID` remains as an explicit override for hand-launched units. No patch to the platform is needed; that was the withdrawn gap #1. |
| **No ServerApp submission** | The smoke test proves registration and wiring, not a completed federated round. Submitting a run needs `flwr run` against the hub's Control API (9093), which the platform must expose on the management network. |
