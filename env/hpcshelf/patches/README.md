# Patches proposed for the HPC Shelf platform

Diffs against `hpcshelf-model`, branch `develop`, commit
`68f0ace62160191f082ee783601c48b9fb3f85f1`.

These are **proposals**. Nothing here has been applied, committed or pushed to
the platform repository. Each patch was developed and tested in a separate copy,
so the platform checkout stays untouched — `git status` there is clean and the
patch is only checked against it with `git apply --check`.

> **WITHDRAWN — 2026-09-25. Do not send this patch.**
>
> The premise below is **wrong**: the platform already gives every unit a way to
> learn which replica it is. The UnitAgent writes the unit's own `UnitPlan` and
> injects `HPCSHELF_UNIT_PLAN=/etc/hpcshelf/unit-plan.pb` into the application
> process for root **and** nested units (`hostagent/incus_bootstrap.py`,
> `unitagent/server.py`, `unitagent/real_podman_runtime.py`), and `plan.replica`
> **is** the partition id — which is how the platform's own
> `fl_unit/plan_identity.py` reads it.
>
> `env/hpcshelf/images/supervise-hospital.sh` now reads the same plan with the
> platform's interpreter, so gap #1 closes without touching the platform.
> Verified: `scripts/smoke_hpcshelf_images.sh` → **10 passed, 0 failed**,
> including "a hospital derived its partition from its own unit plan", with a
> deliberately conflicting `PYHEALTH_PARTITION_ID` proving the plan wins.
>
> The patch is kept for provenance, and as the fallback should
> `HPCSHELF_UNIT_PLAN` ever disappear. It is no longer a request.

## `0001-unit-identity-environment.patch` — per-replica unit identity

**Withdrawn; see the notice above. The text below is the original proposal.**

### Problem

A component descriptor's `application.environment` binding carries **one value,
shared by every replica**. There is therefore no way for a unit to learn *which*
replica it is.

That is fine for a stateless service and wrong for a partitioned workload. In
this federation each hospital owns a disjoint shard of the cohort, and its
SuperNode has to be told which:

```text
--node-config "partition-id=0 num-partitions=2"
```

Today that value would have to come from the descriptor — which cannot express
it — or be guessed at runtime. A guessed partition means two hospitals training
on the same shard while the run still reports federated results. Our client
refuses to guess, so this blocks any real deployment.

### Change

The UnitAgent already resolves `unit_plan.replica`, and already has the unit's
`id` and `unit_name`. The patch exposes them to the application process:

| Variable | Value |
| --- | --- |
| `UNIT_ID` | the unit's logical id, e.g. `…/hospital[1]` |
| `UNIT_NAME` | the public unit name, e.g. `hospital` |
| `UNIT_REPLICA_ID` | the resolved 0-based replica index, e.g. `1` |

A descriptor that defines one of these names is **rejected at startup** rather
than silently overridden. A descriptor binding is shared by all replicas, so
honouring it could make two of them claim the same identity — the exact failure
the variables exist to prevent.

### Shape

One constant and one function in `unitagent/application_manager.py`, a three-line
call in `unitagent/server.py::serve()`, four tests. No validator change, no
descriptor-format change, no platform invariant touched.

### Mirrored copies

`podman-unit-base/unitagent/` is a packaged copy of `unitagent/`. The two were
byte-identical before the patch, so the patch changes both, as the platform's
developer workflow requires. Keeping them consistent is why the diff touches
five files for what is a three-line behavioural change.

### Verification

```bash
cd hpcshelf-model
git apply --check /path/to/0001-unit-identity-environment.patch

/tmp/hpcshelf-val-venv/bin/python -m pytest tests/test_application_manager.py
# 6 passed

/tmp/hpcshelf-val-venv/bin/python -m pytest
# 785 passed, 38 errors
```

The same suite on the **unpatched** checkout gives **781 passed, 38 errors**.

So the patch adds 4 passing tests and introduces no regression. The 38 errors are
pre-existing and unrelated — `AttributeError: module 'os' has no attribute
'pidfd_open'` in `tests/test_full_lifecycle.py`, a property of the machine the
suite runs on, identical with and without the patch.

The environment is isolated: `pydantic==2.13.5`, `PyYAML==6.0.3`, Python 3.12,
pytest 9.1.1.

### Open design point

Rejecting a conflicting descriptor binding is a choice; warning and overriding
would be the softer alternative. It fails loudly because the failure mode it
guards against is silent — but this is the platform owner's call, and it is one
`raise` away from being a log line.

### Applying

```bash
git checkout develop
git checkout -b feature/unit-identity-environment
git apply /path/to/0001-unit-identity-environment.patch
python -m pytest tests/test_application_manager.py
```

### What it unblocks

With `UNIT_REPLICA_ID` in the application environment, the hospital supervisor
can pass `--node-config "partition-id=${UNIT_REPLICA_ID}"` instead of requiring
an operator to set `PYHEALTH_PARTITION_ID` by hand. That closes gap #1 in
[`docs/HPC_SHELF_INTEGRATION.md`](../../../docs/HPC_SHELF_INTEGRATION.md) and is
the last change needed before a federated round can actually run on the platform.
