#!/usr/bin/env bash
#
# Functional smoke test for the federation unit images.
#
# Proves the supervisor chain that the gap #2 decision depends on, WITHOUT the
# HPC Shelf control plane: the UnitAgent is bypassed by overriding the
# entrypoint. What is exercised is the part the platform would otherwise drive —
# the Flower process pair inside one unit and the wiring the component
# dependency injects.
#
# A unit plan CAN be produced here without the platform: `UnitPlan` is a plain
# protobuf and the image ships the platform's own generated module
# (`/opt/hpcshelf/common_pb2.py`). That is what lets check 3 exercise the real
# identity path instead of only the test override.
#
# Checks:
#   1. the images keep the invariants the base image does not provide: two
#      interpreters whose protobuf runtimes are kept apart, no podman binary, and
#      a UnitAgent venv that was recreated rather than copied;
#   2. the hub starts SuperLink with the Fleet API on 0.0.0.0:9092 and the
#      Runtime API on loopback only;
#   3. two hospitals register with the hub as distinct nodes, each carrying its
#      own partition id;
#   4. a hospital with NO PYHEALTH_PARTITION_ID derives its partition from its
#      own unit plan, and the plan beats a conflicting override;
#   5. a hospital without a partition identity fails loudly instead of guessing
#      (the gap #1 guard).
#
# Usage:
#   scripts/smoke_hpcshelf_images.sh
#   HPC_IMAGE_VERSION=0.1.0 scripts/smoke_hpcshelf_images.sh
#
# Requires the images built by scripts/build_hpcshelf_images.sh. Cleans up its
# own containers and network.
#
# Logs are captured into variables and matched as strings: piping `podman logs`
# into `grep -q` under `set -o pipefail` fails with SIGPIPE as soon as grep
# finds a match, which would report a passing check as a failure.
#
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

VERSION="${HPC_IMAGE_VERSION:-0.1.0}"
HUB_IMAGE="localhost/flower-hub:${VERSION}"
HOSPITAL_IMAGE="localhost/flower-hospital:${VERSION}"
NETWORK="hpcshelf-smoke"
HUB="hpcshelf-smoke-hub"
HOSPITALS=("hpcshelf-smoke-hosp-0" "hpcshelf-smoke-hosp-1")
PLAN_HOSPITAL="hpcshelf-smoke-hosp-plan"
# Created lazily: `cleanup` runs once early to clear stale containers, so a
# directory made here would be removed before the plan checks could use it.
PLAN_DIR=""
READY_TRIES="${HPC_SMOKE_READY_TRIES:-60}"

pass=0
fail=0

check() {
    local label="$1" condition="$2"
    if [[ "$condition" == "0" ]]; then
        printf '  \033[32m✓\033[0m %s\n' "$label"
        pass=$((pass + 1))
    else
        printf '  \033[31m✗\033[0m %s\n' "$label"
        fail=$((fail + 1))
    fi
}

log_of() {
    podman logs "$1" 2>&1 || true
}

cleanup() {
    for name in "${HOSPITALS[@]}" "$PLAN_HOSPITAL" "$HUB"; do
        podman rm -f "$name" >/dev/null 2>&1 || true
    done
    podman network rm -f "$NETWORK" >/dev/null 2>&1 || true
    if [[ -n "$PLAN_DIR" ]]; then
        rm -rf "$PLAN_DIR"
    fi
}
trap cleanup EXIT

for image in "$HUB_IMAGE" "$HOSPITAL_IMAGE"; do
    if ! podman image exists "$image"; then
        echo "error: image not found: $image" >&2
        echo "       run scripts/build_hpcshelf_images.sh first" >&2
        exit 1
    fi
done

echo ""
echo "==> image invariants"

# Two interpreters, kept apart. The platform's `*_pb2` modules are generated
# against protobuf 7.x while Flower 1.34 pins a 6.x runtime; loading one in the
# other raises VersionError. Both are needed, so neither may drift.
#
# These were prose in docs/HPC_SHELF_DECISIONS.md section 7. Asserting them
# means a base-image change that breaks one is a red check, not a surprise
# discovered during a deployment.
invariants="$(podman run --rm --entrypoint sh "$HOSPITAL_IMAGE" -c '
echo "platform_protobuf=$(/opt/hpcshelf/venv/bin/python -c "import google.protobuf as p; print(p.__version__)" 2>/dev/null)"
echo "app_protobuf=$(/python/venv/bin/python -c "import google.protobuf as p; print(p.__version__)" 2>/dev/null)"
echo "podman_binary=$(command -v podman || echo absent)"
echo "podman_runtime=${HPCSHELF_PODMAN_RUNTIME:-unset}"
echo "unitagent_python=$(readlink -f /opt/hpcshelf/venv/bin/python)"
echo "unitagent_python_ok=$([ -x "$(readlink -f /opt/hpcshelf/venv/bin/python)" ] && echo yes || echo no)"
')"

value_of() { printf '%s\n' "$invariants" | sed -n "s/^$1=//p"; }

[[ "$(value_of platform_protobuf)" == 7.* ]]
check "platform venv carries protobuf 7.x (it owns the platform's *_pb2)" "$?"

[[ "$(value_of app_protobuf)" == 6.* ]]
check "Flower venv carries protobuf 6.x" "$?"

[[ -n "$(value_of platform_protobuf)" && \
   "$(value_of platform_protobuf)" != "$(value_of app_protobuf)" ]]
check "the two interpreters do not share a protobuf runtime" "$?"

[[ "$(value_of podman_binary)" == "absent" && "$(value_of podman_runtime)" == "mock" ]]
check "leaf unit: no podman binary and HPCSHELF_PODMAN_RUNTIME=mock" "$?"

[[ "$(value_of unitagent_python_ok)" == "yes" ]]
check "UnitAgent venv was recreated, not copied (its python exists here)" "$?"

[[ "$(value_of unitagent_python)" != *"python3.12"* ]]
check "UnitAgent venv does not point at the base image's python3.12" "$?"

cleanup
podman network create "$NETWORK" >/dev/null

echo ""
echo "==> hub"
podman run -d --name "$HUB" --network "$NETWORK" \
    --entrypoint /opt/hpcshelf/supervise-hub.sh "$HUB_IMAGE" >/dev/null

hub_log=""
for ((i = 0; i < READY_TRIES; i++)); do
    hub_log="$(log_of "$HUB")"
    [[ "$hub_log" == *"listening on 127.0.0.1:9091"* ]] && break
    sleep 1
done

[[ "$hub_log" == *"listening on 127.0.0.1:9091"* ]]
check "SuperLink became ready (Runtime API on loopback)" "$?"

[[ "$hub_log" == *"Fleet API (gRPC-rere) on 0.0.0.0:9092"* ]]
check "Fleet API is listening on 0.0.0.0:9092 (the only published port)" "$?"

[[ "$hub_log" == *"Runtime API on 127.0.0.1:9091"* ]]
check "Runtime API stayed on loopback (never leaves the unit)" "$?"

[[ "$hub_log" != *"Runtime API on 0.0.0.0"* ]]
check "Runtime API is not bound to a routable address" "$?"

echo ""
echo "==> hospitals"

for index in 0 1; do
    podman run -d --name "${HOSPITALS[$index]}" --network "$NETWORK" \
        -e SUPERLINK_HOST="$HUB" \
        -e SUPERLINK_PORT=9092 \
        -e "PYHEALTH_PARTITION_ID=$index" \
        -e PYHEALTH_NUM_PARTITIONS=2 \
        --entrypoint /opt/hpcshelf/supervise-hospital.sh \
        "$HOSPITAL_IMAGE" >/dev/null
done

registered=0
for ((i = 0; i < READY_TRIES; i++)); do
    registered="$(printf '%s' "$(log_of "$HUB")" | grep -c "ActivateNode" || true)"
    [[ "$registered" -ge 2 ]] && break
    sleep 1
done
[[ "$registered" -ge 2 ]]
check "both hospitals registered with the hub (${registered} nodes)" "$?"

own_partition=0
for index in 0 1; do
    hospital_log="$(log_of "${HOSPITALS[$index]}")"
    [[ "$hospital_log" == *"node-config='partition-id=${index} num-partitions=2'"* ]] \
        || own_partition=1
done
check "each hospital carried its own partition id" "$own_partition"

echo ""
echo "==> plan-derived identity (gap #1, no platform patch)"

# Serialize the plan the planner would emit for hospital[2]: replica index 2.
PLAN_DIR="$(mktemp -d)"
podman run --rm -i -v "${PLAN_DIR}:/plan" \
    --entrypoint /opt/hpcshelf/venv/bin/python \
    "$HOSPITAL_IMAGE" - <<'PY'
import sys

sys.path.insert(0, "/opt/hpcshelf")
import common_pb2

plan = common_pb2.UnitPlan()
plan.id = "smoke/root/institution[2]/hospital[2]"
plan.unit_name = "hospital"
plan.replica = 2
plan.runtime.type = common_pb2.RUNTIME_TYPE_PODMAN
open("/plan/unit-plan.pb", "wb").write(plan.SerializeToString())
PY

# PYHEALTH_PARTITION_ID carries a *conflicting* value on purpose. A shared
# binding must never beat per-replica placement, so the plan has to win.
podman run -d --name "$PLAN_HOSPITAL" --network "$NETWORK" \
    -v "${PLAN_DIR}/unit-plan.pb:/etc/hpcshelf/unit-plan.pb:ro" \
    -e HPCSHELF_UNIT_PLAN=/etc/hpcshelf/unit-plan.pb \
    -e PYHEALTH_PARTITION_ID=0 \
    -e SUPERLINK_HOST="$HUB" \
    -e SUPERLINK_PORT=9092 \
    --entrypoint /opt/hpcshelf/supervise-hospital.sh \
    "$HOSPITAL_IMAGE" >/dev/null

plan_log=""
for ((i = 0; i < READY_TRIES; i++)); do
    plan_log="$(log_of "$PLAN_HOSPITAL")"
    [[ "$plan_log" == *"from unit plan"* ]] && break
    sleep 1
done

[[ "$plan_log" == *"partition 2 from unit plan"* ]]
check "a hospital derived its partition from its own unit plan" "$?"

[[ "$plan_log" == *"node-config='partition-id=2'"* ]]
check "the plan beat the conflicting PYHEALTH_PARTITION_ID override" "$?"

echo ""
echo "==> negative control: no partition identity"

set +e
podman run --rm --network "$NETWORK" \
    -e SUPERLINK_HOST="$HUB" \
    -e SUPERLINK_PORT=9092 \
    --entrypoint /opt/hpcshelf/supervise-hospital.sh \
    "$HOSPITAL_IMAGE" >/dev/null 2>&1
missing_id_exit=$?
set -e

[[ "$missing_id_exit" -ne 0 ]]
check "a hospital with no partition id refuses to start" "$?"

[[ "$missing_id_exit" -eq 1 ]]
check "it fails with exit code 1 (not a silent default)" "$?"

echo ""
if [[ "$fail" -eq 0 ]]; then
    printf '\033[1mResult:\033[0m %d passed, 0 failed\n\n' "$pass"
else
    printf '\033[1mResult:\033[0m %d passed, %d failed\n\n' "$pass" "$fail"
    echo "hub log:"; log_of "$HUB" | tail -30
    for index in 0 1; do
        echo "${HOSPITALS[$index]} log:"; log_of "${HOSPITALS[$index]}" | tail -10
    done
fi

exit $((fail > 0))
