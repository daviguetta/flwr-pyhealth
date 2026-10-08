#!/usr/bin/env bash
#
# Functional smoke test for the three-level arm's unit images.
#
# Proves, WITHOUT the HPC Shelf control plane, the two wirings the arm's
# descriptors depend on, plus the artefact properties the split exists to buy:
#
#   1. the COMMUNICATION images are transport only — no corpus, no ML stack, no
#      container runtime. This is the data-boundary property the split is for;
#   2. `link` binds BOTH Runtime APIs on 0.0.0.0 rather than loopback. That is the
#      arm's defining difference from the grouped arm, and it is what makes the
#      parent's `127.0.0.1:<published_port>` mapping reachable;
#   3. `node` reaches a `link` over the network, registers as a distinct node and
#      carries its own partition id; it refuses to start without the injected
#      SuperLink address and without a partition identity;
#   4. the VERTICAL mechanism: the exec supervisor reads the nested unit's
#      `appio` published port out of its OWN unit plan and dials
#      `127.0.0.1:<published_port>` — and fails fast when there is no such child
#      instead of idling.
#
# A unit plan is built here without the platform: `UnitPlan` is a plain protobuf
# and the images ship the platform's generated module
# (`/opt/hpcshelf/common_pb2.py`).
#
# Usage:
#   scripts/smoke_hpcshelf_three_level.sh
#   HPC_IMAGE_VERSION=0.1.0 scripts/smoke_hpcshelf_three_level.sh
#
# Requires the four images built by scripts/build_hpcshelf_three_level.sh. Cleans
# up its own containers, network and temporary plans.
#
# Logs are captured into variables and matched as strings: piping `podman logs`
# into `grep -q` under `set -o pipefail` fails with SIGPIPE as soon as grep finds
# a match, which would report a passing check as a failure.
#
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

VERSION="${HPC_IMAGE_VERSION:-0.1.0}"
LINK_IMAGE="localhost/flower-link:${VERSION}"
NODE_IMAGE="localhost/flower-node:${VERSION}"
EXEC_SERVER_IMAGE="localhost/flower-exec-server:${VERSION}"
NETWORK="hpcshelf-three-level"
LINK="hpcshelf-cmp-link"
NODES=("hpcshelf-cmp-node-0" "hpcshelf-cmp-node-1")
PLAN_NODE="hpcshelf-cmp-node-plan"
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

remove() {
    # In rootless mode `podman rm -f` can exit 125 with
    # "rootless netns: kill network process: permission denied" even though the
    # container IS removed, so the result is verified by asking Podman instead of
    # trusted from the exit code. Aborting the whole run on that noise would hide
    # the checks that come after it.
    podman rm -f "$1" >/dev/null 2>&1 || true
    ! podman container exists "$1" 2>/dev/null
}

cleanup() {
    for name in "${NODES[@]}" "$PLAN_NODE" "$LINK"; do
        podman rm -f "$name" >/dev/null 2>&1 || true
    done
    podman network rm -f "$NETWORK" >/dev/null 2>&1 || true
    if [[ -n "$PLAN_DIR" ]]; then
        rm -rf "$PLAN_DIR"
    fi
}
trap cleanup EXIT

for image in "$LINK_IMAGE" "$NODE_IMAGE" "$EXEC_SERVER_IMAGE"; do
    if ! podman image exists "$image"; then
        echo "error: image not found: $image" >&2
        echo "       run scripts/build_hpcshelf_three_level.sh first" >&2
        exit 1
    fi
done

echo ""
echo "==> transport-only invariants (the split's data boundary)"

# The transport units must not be able to read records even by accident. That is
# a property of the image, so it is asserted on the image.
transport="$(podman run --rm --entrypoint sh "$LINK_IMAGE" -c '
echo "platform_protobuf=$(/opt/hpcshelf/venv/bin/python -c "import google.protobuf as p; print(p.__version__)" 2>/dev/null)"
echo "app_protobuf=$(/opt/hpcshelf/app-venv/bin/python -c "import google.protobuf as p; print(p.__version__)" 2>/dev/null)"
echo "podman_binary=$(command -v podman || echo absent)"
echo "podman_runtime=${HPCSHELF_PODMAN_RUNTIME:-unset}"
echo "ml_packages=$(/opt/hpcshelf/app-venv/bin/pip list 2>/dev/null | grep -Ec "^(torch|pyhealth) ")"
echo "corpus_dirs=$(ls -d /application/data /data 2>/dev/null | wc -l)"
echo "application_entries=$(ls -A /application 2>/dev/null | wc -l)"
echo "role_files=$(ls /opt/hpcshelf/ | grep -Ec "^supervise-(link|node)\.sh$")"
')"

value_of() { printf '%s\n' "$transport" | sed -n "s/^$1=//p"; }

[[ "$(value_of platform_protobuf)" == 7.* ]]
check "platform venv carries protobuf 7.x (it owns the platform's *_pb2)" "$?"

[[ "$(value_of app_protobuf)" == 6.* ]]
check "Flower venv carries protobuf 6.x (Flower pins <7)" "$?"

[[ -n "$(value_of platform_protobuf)" && \
   "$(value_of platform_protobuf)" != "$(value_of app_protobuf)" ]]
check "the two interpreters do not share a protobuf runtime" "$?"

[[ "$(value_of ml_packages)" == "0" ]]
check "no torch and no pyhealth in the transport image (no ML stack)" "$?"

[[ "$(value_of corpus_dirs)" == "0" && "$(value_of application_entries)" == "0" ]]
check "no corpus in the transport image (nothing to read patient records from)" "$?"

[[ "$(value_of podman_binary)" == "absent" && "$(value_of podman_runtime)" == "mock" ]]
check "leaf unit: no podman binary and HPCSHELF_PODMAN_RUNTIME=mock" "$?"

[[ "$(value_of role_files)" == "1" ]]
check "exactly one role wrapper per image (a role cannot be shared by accident)" "$?"

echo ""
echo "==> link: both Runtime APIs on 0.0.0.0 (the arm's defining difference)"

cleanup
podman network create "$NETWORK" >/dev/null

podman run -d --name "$LINK" --network "$NETWORK" \
    --entrypoint /opt/hpcshelf/supervise-link.sh "$LINK_IMAGE" >/dev/null

link_log=""
for ((i = 0; i < READY_TRIES; i++)); do
    link_log="$(log_of "$LINK")"
    [[ "$link_log" == *"Starting Runtime API"* ]] && break
    sleep 1
done

[[ "$link_log" == *"Fleet API (gRPC-rere) on 0.0.0.0:9092"* ]]
check "Fleet API on 0.0.0.0:9092 (the only interface that crosses an institution)" "$?"

[[ "$link_log" == *"Starting Runtime API on 0.0.0.0:9091"* ]]
check "Runtime API (appio) on 0.0.0.0:9091, so the parent's mapping can reach it" "$?"

[[ "$link_log" != *"Starting Runtime API on 127.0.0.1:9091"* ]]
check "Runtime API is NOT on loopback — the grouped arm's invariant is deliberately spent" "$?"

[[ "$link_log" == *"Starting Control API on 0.0.0.0:9093"* ]]
check "Control API binds in-container but is undeclared: the planner never maps it" "$?"

# The descriptor injects the port, so the listener and the descriptor cannot
# drift apart. Overriding it must move the listener with it.
remove "$LINK"
podman run -d --name "$LINK" --network "$NETWORK" \
    -e FL_APPIO_PORT=19091 -e FL_FLEET_PORT=19092 \
    --entrypoint /opt/hpcshelf/supervise-link.sh "$LINK_IMAGE" >/dev/null

link_log=""
for ((i = 0; i < READY_TRIES; i++)); do
    link_log="$(log_of "$LINK")"
    [[ "$link_log" == *"Starting Runtime API"* ]] && break
    sleep 1
done

[[ "$link_log" == *"Starting Runtime API on 0.0.0.0:19091"* ]]
check "FL_APPIO_PORT from the descriptor moves the listener (no port drift)" "$?"

# Back to the declared ports for the registration checks.
remove "$LINK"
podman run -d --name "$LINK" --network "$NETWORK" \
    --entrypoint /opt/hpcshelf/supervise-link.sh "$LINK_IMAGE" >/dev/null
for ((i = 0; i < READY_TRIES; i++)); do
    link_log="$(log_of "$LINK")"
    [[ "$link_log" == *"Starting Runtime API"* ]] && break
    sleep 1
done

echo ""
echo "==> node: reaches the link across the network, carrying its own partition"

for index in 0 1; do
    podman run -d --name "${NODES[$index]}" --network "$NETWORK" \
        -e SUPERLINK_HOST="$LINK" \
        -e SUPERLINK_PORT=9092 \
        -e "PYHEALTH_PARTITION_ID=$index" \
        -e PYHEALTH_NUM_PARTITIONS=2 \
        --entrypoint /opt/hpcshelf/supervise-node.sh \
        "$NODE_IMAGE" >/dev/null
done

registered=0
for ((i = 0; i < READY_TRIES; i++)); do
    registered="$(printf '%s' "$(log_of "$LINK")" | grep -c "ActivateNode" || true)"
    [[ "$registered" -ge 2 ]] && break
    sleep 1
done
[[ "$registered" -ge 2 ]]
check "both nodes registered with the link (${registered} nodes) — the cross-host path works" "$?"

own_partition=0
for index in 0 1; do
    node_log="$(log_of "${NODES[$index]}")"
    [[ "$node_log" == *"Starting Runtime API on 0.0.0.0:9094"* ]] || own_partition=1
    [[ "$node_log" == *"node-config='partition-id=${index} num-partitions=2'"* ]] \
        || own_partition=1
done
check "each node exposes appio on 0.0.0.0:9094 and carried its own partition id" "$own_partition"

echo ""
echo "==> negative controls: the node refuses to guess"

set +e
podman run --rm --network "$NETWORK" \
    -e PYHEALTH_PARTITION_ID=0 \
    --entrypoint /opt/hpcshelf/supervise-node.sh "$NODE_IMAGE" >/dev/null 2>&1
no_superlink_exit=$?
set -e

[[ "$no_superlink_exit" -ne 0 ]]
check "a node with no injected SUPERLINK_HOST refuses to start" "$?"

set +e
podman run --rm --network "$NETWORK" \
    -e SUPERLINK_HOST="$LINK" -e SUPERLINK_PORT=9092 \
    --entrypoint /opt/hpcshelf/supervise-node.sh "$NODE_IMAGE" >/dev/null 2>&1
no_partition_exit=$?
set -e

[[ "$no_partition_exit" -eq 1 ]]
check "a node with no partition identity fails with exit code 1 (no silent default)" "$?"

echo ""
echo "==> identity from the unit plan (no platform patch)"

PLAN_DIR="$(mktemp -d)"
podman run --rm -i -v "${PLAN_DIR}:/plan" \
    --entrypoint /opt/hpcshelf/venv/bin/python \
    "$NODE_IMAGE" - <<'PY'
import sys

sys.path.insert(0, "/opt/hpcshelf")
import common_pb2

plan = common_pb2.UnitPlan()
plan.id = "smoke/root/ex/comm/node[2]"
plan.unit_name = "node"
plan.replica = 2
plan.runtime.type = common_pb2.RUNTIME_TYPE_PODMAN
open("/plan/unit-plan.pb", "wb").write(plan.SerializeToString())
PY

# PYHEALTH_PARTITION_ID carries a CONFLICTING value on purpose: a shared binding
# must never beat per-replica placement, so the plan has to win.
podman run -d --name "$PLAN_NODE" --network "$NETWORK" \
    -v "${PLAN_DIR}/unit-plan.pb:/etc/hpcshelf/unit-plan.pb:ro" \
    -e HPCSHELF_UNIT_PLAN=/etc/hpcshelf/unit-plan.pb \
    -e PYHEALTH_PARTITION_ID=0 \
    -e SUPERLINK_HOST="$LINK" \
    -e SUPERLINK_PORT=9092 \
    --entrypoint /opt/hpcshelf/supervise-node.sh \
    "$NODE_IMAGE" >/dev/null

plan_node_log=""
for ((i = 0; i < READY_TRIES; i++)); do
    plan_node_log="$(log_of "$PLAN_NODE")"
    [[ "$plan_node_log" == *"from unit plan"* ]] && break
    sleep 1
done

[[ "$plan_node_log" == *"partition 2 from unit plan"* ]]
check "a node derived its partition from its own unit plan" "$?"

[[ "$plan_node_log" == *"node-config='partition-id=2'"* ]]
check "the plan beat the conflicting PYHEALTH_PARTITION_ID override" "$?"

echo ""
echo "==> the vertical mechanism: the SuperExec reads its child's appio from its plan"

# The plan the planner would emit for exec-server[0]: its subtree carries link[0]
# with the `appio` service already published at a concrete port.
podman run --rm -i -v "${PLAN_DIR}:/plan" \
    --entrypoint /opt/hpcshelf/venv/bin/python \
    "$EXEC_SERVER_IMAGE" - <<'PY'
import sys

sys.path.insert(0, "/opt/hpcshelf")
import common_pb2

plan = common_pb2.UnitPlan()
plan.id = "smoke/root/ex[0]/exec-server[0]"
plan.unit_name = "exec-server"
plan.replica = 0
plan.runtime.type = common_pb2.RUNTIME_TYPE_PODMAN

child = plan.children.add()
child.id = "smoke/root/ex/comm/link[0]"
child.unit_name = "link"
child.replica = 0
child.runtime.type = common_pb2.RUNTIME_TYPE_PODMAN

service = child.services.add()
service.name = "appio"
service.protocol = common_pb2.SERVICE_PROTOCOL_GRPC
service.container_port = 9091
service.vpn_address = "10.201.0.1"
service.published_port = 30000

open("/plan/parent-plan.pb", "wb").write(plan.SerializeToString())
PY

set +e
vertical_out="$(podman run --rm \
    -v "${PLAN_DIR}/parent-plan.pb:/etc/hpcshelf/unit-plan.pb:ro" \
    -e HPCSHELF_UNIT_PLAN=/etc/hpcshelf/unit-plan.pb \
    -e WAIT_TRIES=2 \
    --entrypoint /opt/hpcshelf/supervise-exec-server.sh \
    "$EXEC_SERVER_IMAGE" 2>&1)"
vertical_exit=$?
set -e

[[ "$vertical_out" == *"nested AppIO endpoint 127.0.0.1:30000 (read from the unit plan)"* ]]
check "the parent learned its child's appio port from its own plan (no platform patch)" "$?"

[[ "$vertical_exit" -ne 0 ]]
check "with no child listening it fails loudly instead of idling" "$?"

set +e
no_service_out="$(podman run --rm \
    -e HPCSHELF_UNIT_PLAN=/etc/hpcshelf/does-not-exist.pb \
    -e WAIT_TRIES=2 \
    --entrypoint /opt/hpcshelf/supervise-exec-server.sh \
    "$EXEC_SERVER_IMAGE" 2>&1)"
no_service_exit=$?
set -e

[[ "$no_service_out" == *"no 'appio' service found in this unit's plan"* && "$no_service_exit" -ne 0 ]]
check "a SuperExec whose plan declares no nested appio fails fast" "$?"

set +e
unset_plan_out="$(podman run --rm \
    -e HPCSHELF_UNIT_PLAN= \
    -e WAIT_TRIES=2 \
    --entrypoint /opt/hpcshelf/supervise-exec-server.sh \
    "$EXEC_SERVER_IMAGE" 2>&1)"
unset_plan_exit=$?
set -e

[[ "$unset_plan_out" == *"HPCSHELF_UNIT_PLAN is unset"* && "$unset_plan_exit" -ne 0 ]]
check "a SuperExec with no plan at all fails before opening a connection" "$?"

echo ""
if [[ "$fail" -eq 0 ]]; then
    printf '\033[1mResult:\033[0m %d passed, 0 failed\n\n' "$pass"
else
    printf '\033[1mResult:\033[0m %d passed, %d failed\n\n' "$pass" "$fail"
    echo "link log:"; log_of "$LINK" | tail -20
    for index in 0 1; do
        echo "${NODES[$index]} log:"; log_of "${NODES[$index]}" | tail -10
    done
fi

exit $((fail > 0))
