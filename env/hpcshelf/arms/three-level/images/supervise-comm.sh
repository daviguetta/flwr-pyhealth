#!/usr/bin/env bash
#
# Application command for a COMMUNICATION unit: `link` (SuperLink) or `node`
# (SuperNode). The role comes from a per-role wrapper file
# (`supervise-link.sh` / `supervise-node.sh`).
#
# WHAT THIS UNIT IS
#
# Transport only. It carries no patient records, no model code and no ML stack —
# the image is built without them on purpose, so "the data boundary is the exec
# unit" is a property of the artefact rather than a claim about behaviour.
#
# THE ONE THING THAT DIFFERS FROM THE GROUPED ARM
#
# Every Runtime API here binds 0.0.0.0, not 127.0.0.1:
#
#   link   fleet 0.0.0.0:9092     appio 0.0.0.0:9091     control: default, undeclared
#   node   clientappio 0.0.0.0:9094                     outbound to $SUPERLINK_HOST:$SUPERLINK_PORT
#
# In the grouped arm the SuperExec shares its container with the process it calls,
# so `appio` stays on loopback. Here the caller is the PARENT unit: the platform
# creates the mapping inside the parent's namespace
# (`parent:published_port -> this unit:container_port`, see
# `unitagent/real_podman_runtime._collect_forwarded_services`) and the parent
# dials `127.0.0.1:<published_port>`. A service bound to loopback inside THIS
# container could not be reached through that mapping.
#
# The Control API (9093) keeps Flower's default binding and is NOT declared as a
# service in the component descriptor, so the platform neither maps nor publishes
# it: it is unreachable from outside this container. Publishing it is the
# management-network decision of Phase 6, and it is the same open item the grouped
# arm has.
#
# Environment:
#   FL_APPIO_PORT            injected by the descriptor (`services.*.environment.port`)
#   FL_FLEET_PORT            injected by the descriptor (link only)
#   SUPERLINK_HOST / _PORT   injected by the platform from the `link.fleet`
#                            dependency (node only)
#   PYHEALTH_NUM_PARTITIONS  optional; appended to node-config when set
#   PYHEALTH_PARTITION_ID    explicit override, for hand-launched units and tests
#
# Replica identity: unchanged from the grouped arm — `partition-id = plan.replica`,
# read from this unit's own plan. The overlap maps `node[i]` onto `exec-client[i]`,
# so the partition this SuperNode publishes is the partition the ClientApp in its
# parent unit owns. With no plan and no override the unit fails instead of
# guessing; a run that reports federated numbers while every node saw the same
# records is worse than a run that fails.
#
# Lifecycle: the Flower process IS the unit. There is no second process to
# supervise here, which is the whole point of the split — the grouped arm needs a
# supervisor script for exactly this reason. `exec` makes the unit's exit status
# the transport process's exit status, so the UnitAgent reports a dead
# SuperLink/SuperNode as a failed unit.
#
# Cleartext (`--insecure`); TLS is Phase 5/7 of the roadmap.
set -euo pipefail

VENV_BIN="${VENV_BIN:-/opt/hpcshelf/app-venv/bin}"
# The unit plan is generated against protobuf 7.x, so it is parsed with the
# platform's interpreter, not the application's (Flower pins protobuf <7).
PLAN_PY="${PLAN_PY:-/opt/hpcshelf/venv/bin/python}"
ROLE="${FLWR_ROLE:?the role wrapper (supervise-link.sh / supervise-node.sh) must export FLWR_ROLE}"

log() { printf '[%s] %s\n' "$ROLE" "$*"; }

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

case "$ROLE" in
link)
    # The owning unit is told its own container port by the descriptor, so the
    # listener and the descriptor cannot drift apart.
    appio_port="${FL_APPIO_PORT:-9091}"
    fleet_port="${FL_FLEET_PORT:-9092}"

    log "starting SuperLink (fleet=0.0.0.0:${fleet_port} appio=0.0.0.0:${appio_port})"
    exec "$VENV_BIN/flower-superlink" \
        --insecure \
        --isolation process \
        --fleet-api-address "0.0.0.0:${fleet_port}" \
        --serverappio-api-address "0.0.0.0:${appio_port}"
    ;;

node)
    : "${SUPERLINK_HOST:?the platform must inject it through the link.fleet dependency}"
    : "${SUPERLINK_PORT:?the platform must inject it through the link.fleet dependency}"

    appio_port="${FL_APPIO_PORT:-9094}"

    partition_id="$(read_partition_from_plan || true)"
    if [[ -n "$partition_id" ]]; then
        log "partition ${partition_id} from unit plan (${HPCSHELF_UNIT_PLAN})"
    else
        partition_id="${PYHEALTH_PARTITION_ID:-}"
        if [[ -n "$partition_id" ]]; then
            log "partition ${partition_id} from explicit PYHEALTH_PARTITION_ID override"
        fi
    fi

    if [[ -z "$partition_id" ]]; then
        log "FATAL: no partition identity."
        log "       The platform injects HPCSHELF_UNIT_PLAN for every unit; with no"
        log "       plan and no PYHEALTH_PARTITION_ID this node cannot tell which"
        log "       partition its parent unit owns. Guessing would make the"
        log "       ClientApp train on another hospital's records while the run"
        log "       still reported federated results."
        exit 1
    fi

    node_config="partition-id=${partition_id}"
    if [[ -n "${PYHEALTH_NUM_PARTITIONS:-}" ]]; then
        node_config+=" num-partitions=${PYHEALTH_NUM_PARTITIONS}"
    fi

    log "starting SuperNode (superlink=${SUPERLINK_HOST}:${SUPERLINK_PORT} appio=0.0.0.0:${appio_port} node-config='${node_config}')"
    exec "$VENV_BIN/flower-supernode" \
        --insecure \
        --isolation process \
        --superlink "${SUPERLINK_HOST}:${SUPERLINK_PORT}" \
        --clientappio-api-address "0.0.0.0:${appio_port}" \
        --node-config "$node_config"
    ;;

*)
    log "FATAL: unknown FLWR_ROLE '${ROLE}' (expected 'link' or 'node')"
    exit 1
    ;;
esac
