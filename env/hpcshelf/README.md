# `env/hpcshelf/` — the federation on HPC Shelf

The federation topology expressed as HPC Shelf component/application descriptors,
plus the proofs that the platform's own validator and planner accept them. The
design and its rationale live in
[`docs/HPC_SHELF_INTEGRATION.md`](../../docs/HPC_SHELF_INTEGRATION.md).

There is **one logical model and two physical realizations**. Both arms describe
the same federation (1 hub + 2 hospitals, `fleet` 9092 crossing the institution
boundary); they differ in how many Flower processes share a container, and
therefore in their privacy cost.

| Arm | Directory | Units | `appio` | Default? |
| --- | --- | --- | --- | --- |
| **grouped** | `arms/grouped/` | 6 (one per institution) | loopback inside the container | ✅ |
| **three-level** | `arms/three-level/` | 9 (one per Flower process) | published on the VPN | ❌ (measured) |

The grouped arm keeps `appio` (9091/9094) on loopback, so only `fleet` (9092)
leaves the unit — the privacy-conservative choice, at the cost of two processes
sharing a container. The three-level arm nests `link`/`node` inside
`exec-server`/`exec-client` (the direction the logical model calls for), keeps
the transport units free of any data, but must publish `appio` on the application
VPN because the platform has no `scope: parent` publication. Read each arm's
`README.md` for its reasoning and its measured cost.

## Shared

* `hosts.yaml` — the synthetic host inventory, used by **both** arms so they
  differ in topology and nothing else.

## Removed

* `patches/` — the `0001-unit-identity-environment.patch` was **withdrawn**
  (2026-09-25): the platform already injects `HPCSHELF_UNIT_PLAN` for every unit,
  root and nested, so the patch's premise was wrong. Removed from the tree;
  provenance is in git history and in `docs/HPC_SHELF_ROADMAP.md` (Fase 2).

## Running the proofs

```bash
scripts/validate_hpcshelf.sh                       # grouped arm: descriptors + negative controls + planner
scripts/build_hpcshelf_images.sh                   # grouped arm: unit images
scripts/smoke_hpcshelf_images.sh                   # grouped arm: Flower wiring, no platform

scripts/validate_hpcshelf_three_level.sh            # three-level arm: 39 checks, measures both arms
scripts/build_hpcshelf_three_level.sh               # three-level arm: 4 unit images
scripts/smoke_hpcshelf_three_level.sh               # three-level arm: 22 checks

scripts/publish_hpcshelf_images.sh --registry localhost:5000 --insecure   # grouped arm: publication
```

Nothing here deploys anything: the descriptors are validated read-only against a
clone of `hpcshelf-model` (`HPCSHELF_MODEL_ROOT`), and the images are built and
tested locally.
