# `env/` — execution environments

This directory holds everything that describes *where* the federated components
run, kept separate from *what* they compute (`flower_app/`) and from *what* the
institutions agreed (`libs/federation_contracts/`).

| Path | What it is |
| --- | --- |
| `podman/` | The containerised Flower deployment runtime used for development and for the first real deployments. |
| `incus/` | The Incus unit topology that hosts one Podman deployment per institution. |
| `hpcshelf/` | The federation on HPC Shelf, as two arms — `arms/grouped/` (default) and `arms/three-level/` — plus the proofs that the platform's own validator and planner accept them. |

The project's platform model is **nested containers**: an Incus unit represents
an institution (server unit or client unit), and inside each unit Podman runs the
Flower components. See `docs/ARCHITECTURE.md` for the full topology.

## Which one do I want?

* **Reproducing an experiment, or developing** → you do not need any of this. Use
  `scripts/simulate.sh`, which runs Flower's Simulation Runtime (Ray) on a single
  machine.
* **Exercising the real communication stack** → `podman/`, driven by
  `scripts/deploy_containers.sh`.
* **Modelling an actual multi-institution rollout** → `incus/`, which is a
  template rather than a working deployment.
* **Checking the topology against the HPC Shelf platform** → `hpcshelf/`, which
  runs the platform's SemanticValidator and DeploymentPlanner over the
  descriptors with no infrastructure. See `docs/HPC_SHELF_DECISIONS.md`.

## Security note

Nothing in this directory may contain patient data, private keys, or credentials.
`podman/.gitignore` excludes generated certificate material and SuperLink state,
and `env/*/superlink-certificates/` and `env/*/state/` are excluded at the
repository root as well. Certificate generation is a one-off operator step, never
a committed artefact.
