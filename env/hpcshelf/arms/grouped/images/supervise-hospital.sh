#!/usr/bin/env bash
#
# Application command for a federation HOSPITAL unit.
#
# Per the gap #2 decision (docs/HPC_SHELF_DECISIONS.md, section 5): the
# hospital's two Flower processes share this container.
#
#   SuperNode            connects out to $SUPERLINK_HOST:$SUPERLINK_PORT (9092)
#                        clientappio 127.0.0.1:9094  <- loopback, SuperExec only
#   SuperExec ClientApp  -> 127.0.0.1:9094
#
# No port is published by this unit: the only flow that crosses the institution
# boundary is the outbound 9092 the platform injects through the component
# dependency, reached over the application VPN.
#
# The platform injects, from the component descriptor's `dependencies`:
#   SUPERLINK_HOST   the hub's VPN address
#   SUPERLINK_PORT   the published port of the hub's `fleet` service
#
# Replica identity (gap #1, resolved in Phase 2 of docs/HPC_SHELF_DECISIONS.md):
#
#   1. HPCSHELF_UNIT_PLAN       the unit's own plan, written by the UnitAgent.
#                               plan.replica IS the partition id, so the
#                               platform's placement is the single source of
#                               truth. No patch to the platform is needed.
#   2. PYHEALTH_PARTITION_ID    explicit override, for hand-launched units and
#                               tests, where no plan exists.
#
# The plan wins over the override on purpose. A descriptor binding is shared by
# every replica, so a PYHEALTH_PARTITION_ID that travelled that way would hand
# every hospital the same partition. plan.replica cannot: the planner resolves
# it per replica.
#
# PYHEALTH_NUM_PARTITIONS  optional. It is a cardinality, identical across
#                          replicas, so a shared binding is correct for it — but
#                          it must still equal the number of hospitals, and
#                          drift is not detected here.
#
# The partition id has NO default. A hospital that cannot tell which partition
# it owns would train on data it does not own while the run still reported
# "federated" results, so this script fails loudly instead of guessing. This
# mirrors the check already in flower_app/client_app.py.
#
# TIMING: cleartext (`--insecure`); TLS is Phase 5.
#
set -euo pipefail

VENV_BIN="${VENV_BIN:-/python/venv/bin}"
# The plan is a protobuf generated against protobuf 7.x, so it is parsed with
# the platform's interpreter, not the Flower one (protobuf 6.x) — mixing them
# raises VersionError. See docs/HPC_SHELF_DECISIONS.md section 7.
PLAN_PY="${PLAN_PY:-/opt/hpcshelf/venv/bin/python}"
CLIENTAPPIO_ADDR="${CLIENTAPPIO_ADDR:-127.0.0.1:9094}"

log() { printf '[hospital] %s\n' "$*"; }

: "${SUPERLINK_HOST:?the platform must inject it through the component dependency}"
: "${SUPERLINK_PORT:?the platform must inject it through the component dependency}"

# Reads this unit's replica index out of its own plan. Returns non-zero when
# there is no plan to read, so the caller can fall back to an explicit override.
read_partition_from_plan() {
    local plan_path="${HPCSHELF_UNIT_PLAN:-}"
    [[ -n "$plan_path" && -f "$plan_path" ]] || return 1
    "$PLAN_PY" - "$plan_path" <<'PY'
import sys

sys.path.insert(0, "/opt/hpcshelf")
import common_pb2

plan = common_pb2.UnitPlan()
plan.ParseFromString(open(sys.argv[1], "rb").read())
if not plan.id:
    raise SystemExit("unit plan carries no unit id")
sys.stdout.write(str(int(plan.replica)))
PY
}

PARTITION_ID="$(read_partition_from_plan || true)"
if [[ -n "$PARTITION_ID" ]]; then
    log "partition ${PARTITION_ID} from unit plan (${HPCSHELF_UNIT_PLAN})"
else
    PARTITION_ID="${PYHEALTH_PARTITION_ID:-}"
    if [[ -n "$PARTITION_ID" ]]; then
        log "partition ${PARTITION_ID} from explicit PYHEALTH_PARTITION_ID override"
    fi
fi

if [[ -z "$PARTITION_ID" ]]; then
    log "FATAL: no partition identity."
    log "       The platform injects HPCSHELF_UNIT_PLAN for every unit; with no"
    log "       plan and no PYHEALTH_PARTITION_ID this hospital cannot tell which"
    log "       partition it owns. Guessing would put it on another hospital's"
    log "       partition while the run still reported federated results."
    exit 1
fi

node_config="partition-id=${PARTITION_ID}"
if [[ -n "${PYHEALTH_NUM_PARTITIONS:-}" ]]; then
    node_config+=" num-partitions=${PYHEALTH_NUM_PARTITIONS}"
fi

wait_port() {
    local host="$1" port="$2" tries="${3:-60}"
    local i
    for ((i = 0; i < tries; i++)); do
        if (exec 3<>"/dev/tcp/${host}/${port}") 2>/dev/null; then
            exec 3>&- 2>/dev/null || true
            return 0
        fi
        sleep 1
    done
    return 1
}

supernode_pid=""
superexec_pid=""

cleanup() {
    log "stopping"
    [[ -n "$superexec_pid" ]] && kill "$superexec_pid" 2>/dev/null || true
    [[ -n "$supernode_pid" ]] && kill "$supernode_pid" 2>/dev/null || true
    wait 2>/dev/null || true
}
trap cleanup TERM INT

log "starting SuperNode (superlink=${SUPERLINK_HOST}:${SUPERLINK_PORT} node-config='${node_config}')"
"$VENV_BIN/flower-supernode" \
    --insecure \
    --isolation process \
    --superlink "${SUPERLINK_HOST}:${SUPERLINK_PORT}" \
    --clientappio-api-address "$CLIENTAPPIO_ADDR" \
    --node-config "$node_config" &
supernode_pid=$!

appio_host="${CLIENTAPPIO_ADDR%:*}"
appio_port="${CLIENTAPPIO_ADDR##*:}"

if ! wait_port "$appio_host" "$appio_port"; then
    log "FATAL: SuperNode did not open ${CLIENTAPPIO_ADDR} within 60s"
    exit 1
fi
log "SuperNode is listening on ${CLIENTAPPIO_ADDR}"

supervise_superexec() {
    "$VENV_BIN/flower-superexec" \
        --insecure \
        --plugin-type clientapp \
        --appio-api-address "${appio_host}:${appio_port}" &
    superexec_pid=$!
}

supervise_superexec

while true; do
    if ! kill -0 "$supernode_pid" 2>/dev/null; then
        wait "$supernode_pid" || true
        log "FATAL: SuperNode exited; this hospital has left the federation"
        exit 1
    fi

    if ! kill -0 "$superexec_pid" 2>/dev/null; then
        wait "$superexec_pid" 2>/dev/null || true
        log "SuperExec (ClientApp) exited; restarting"
        supervise_superexec
    fi

    sleep 2
done
