# `env/hpcshelf/arms/grouped/` — the grouped arm (default realization)

Where the federation topology stops being a document and becomes machine-checked
descriptors. The design and its rationale live in
[`docs/HPC_SHELF_INTEGRATION.md`](../../../docs/HPC_SHELF_INTEGRATION.md); this
directory holds the artifacts that the platform's own validators and planner
consume.

```text
env/hpcshelf/arms/grouped/                       # this arm: the DEFAULT realization
├── components/
│   ├── federation-root/0.1/component.yaml      # Incus units: one per institution
│   └── flower-federation/0.1/component.yaml    # Podman units: hub + hospital
├── applications/pyhealth-federation.yaml       # placement: 1 hub + 2 hospitals
├── images/                                     # the unit images the platform pulls
│   ├── Containerfile.flower-unit
│   ├── supervise-hub.sh
│   ├── supervise-hospital.sh
│   └── README.md
├── model_split.py                              # model's 4-unit decomposition (negative controls)
├── validate.py                                 # runs the platform's own checker
└── publish.py                                  # publishes and materialises the catalog
```

`hosts.yaml` is shared with the sibling arm and lives one level up, in
`env/hpcshelf/`. The sibling arm — one unit per Flower process, nested three
levels — is `env/hpcshelf/arms/three-level/`.

## What the descriptors say

| Unit | Runtime | Runs | Network |
| --- | --- | --- | --- |
| `institution[*]` | Incus | the unit host (UnitAgent + nested Podman) | none published |
| `hub[0]` | Podman | SuperLink + SuperExec ServerApp | publishes `fleet` (9092) |
| `hospital[*]` | Podman | SuperNode + SuperExec ClientApp | outbound only |

Only `fleet` (9092) crosses a unit boundary. The SuperLink AppIO (9091) and the
SuperNode AppIO (9094) are loopback inside their own container — which is why the
design groups a Flower process pair per institution instead of one container per
process. See section 4 of the integration document.

## Running the proof

No infrastructure, no containers, no network, and **nothing is written to the
platform repository**: its modules are imported read-only.

```bash
scripts/validate_hpcshelf.sh
```

And the functional proof of the unit images (Flower wiring, not the platform's
control plane):

```bash
scripts/build_hpcshelf_images.sh
scripts/smoke_hpcshelf_images.sh
```

And the publication path (rehearsable against any registry):

```bash
scripts/publish_hpcshelf_images.sh --registry localhost:5000 --insecure
```

Or directly, with any interpreter carrying the platform's pinned dependencies:

```bash
HPCSHELF_MODEL_ROOT=/path/to/hpcshelf-model \
    /tmp/hpcshelf-val-venv/bin/python env/hpcshelf/arms/grouped/validate.py
```

The script reports four groups: a positive semantic validation, negative controls
for each validation code the decomposition must avoid, a positive planner run,
and the environment bindings the planner produced.

### Creating the validation environment

The platform pins `pydantic==2.13.5` and `PyYAML==6.0.3`; the project's own venv
carries different versions, so use a separate one:

```bash
uv venv /tmp/hpcshelf-val-venv --python 3.12
uv pip install --python /tmp/hpcshelf-val-venv/bin/python \
    -r "$HPCSHELF_MODEL_ROOT/requirements.txt"
```

## What the proof establishes — and what it does not

**Established:** the decomposition is accepted by the platform's
`SemanticValidator` with no errors, and specifically produces none of `C017`
(host-replica occupancy collision), `C007` (child unit without overlap), `D004`
(placement on a non-root unit), `D007` (`oneToOne` cardinality mismatch) or
`C002` (dependency target outside the component). The `DeploymentPlanner` then
materialises 3 Incus root units and 3 nested Podman units, wires
`hospital[*]` under `institution[1..2]`, and injects `SUPERLINK_HOST` (the hub's
VPN address) and `SUPERLINK_PORT` (the published port of `fleet`).

Each negative control deliberately introduces one violation and asserts the
corresponding code fires. Without them, a passing validation would be
indistinguishable from a validator that checks nothing.

**Not established:** that any of this deploys. The host inventory is synthetic and
nothing here has been run against the HPC Shelf control plane. This is a design
proof, not a deployment. The unit images themselves are built and functionally
tested separately — see `images/README.md`.

## Status

Phase 1 of the integration plan: the descriptors are frozen and proven. Phase 2
built the unit images (`images/`); their publication is a separate, authorised
step. The next functional work is Phase 3, the per-replica `partition-id`
injection.
