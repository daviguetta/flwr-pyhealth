#!/usr/bin/env bash
#
# Application command for a MIDDLE-LEVEL unit (three-level arm).
#
# This unit is a SuperExec. It hosts the communication component's unit (`link`
# or `node`) as a NESTED Podman child, and calls that child's AppIO over gRPC —
# that is the vertical link the three-level architecture is built on.
#
#   exec-server  ->  the nested `link` unit's appio  (SuperLink's Runtime API)
#   exec-client  ->  the nested `node` unit's appio  (SuperNode's Runtime API)
#
# WHERE THE ADDRESS COMES FROM
#
# The platform does not inject a child's address into its parent's environment:
# `dependencies` resolves only inside one `component_path`, and the parent and
# the child are units of different components. It does not need to. The parent's
# unit plan already carries its whole subtree, including each child's
# `ServiceEndpoint`, and the runtime forwards the child's service into this
# unit's namespace at the SAME `published_port`:
#
#     real_podman_runtime._collect_forwarded_services
#         parent:published_port -> child:container_port
#         "the published port propagates through intermediate namespaces until
#          the service-owning unit is reached"
#
# So this script reads its own plan and dials 127.0.0.1:<published_port>. No
# platform patch is involved.
#
# WHY THE WAIT IS MANDATORY
#
# `run_guarded_startup` starts the application BEFORE creating the children:
#
#     application_manager.start()           <- this script runs here
#     bootstrap_controller.run(unit_plan)   <- the child is created after
#
# So the nested unit does not exist yet when this script starts. The grouped arm
# has no such ordering, because its supervisor starts both processes itself.
# This wait — and the startup race it exists to absorb — is a property of the
# separated topology, and one of the things the three-level arm measures.
#
# Cleartext (`--insecure`); TLS is Phase 5 of the roadmap.
#
set -euo pipefail

VENV_BIN="${VENV_BIN:-/opt/hpcshelf/app-venv/bin}"
# The plan is generated against protobuf 7.x, so it is parsed with the platform's
# interpreter, not the application's (Flower declares protobuf <7).
PLAN_PY="${PLAN_PY:-/opt/hpcshelf/venv/bin/python}"
PLUGIN_TYPE="${FLWR_PLUGIN_TYPE:?the image sets FLWR_PLUGIN_TYPE to serverapp or clientapp}"
WAIT_TRIES="${WAIT_TRIES:-180}"

role="${PLUGIN_TYPE%app}"
log() { printf '[exec-%s] %s\n' "$role" "$*"; }

# The nested unit's AppIO endpoint, read from this unit's own plan.
read_nested_appio_port() {
    local plan_path="${HPCSHELF_UNIT_PLAN:-}"
    [[ -n "$plan_path" && -f "$plan_path" ]] || return 1
    "$PLAN_PY" - "$plan_path" <<'PY'
import sys

sys.path.insert(0, "/opt/hpcshelf")
import common_pb2

plan = common_pb2.UnitPlan()
plan.ParseFromString(open(sys.argv[1], "rb").read())

for child in plan.children:
    for service in child.services:
        if service.name == "appio":
            sys.stdout.write(str(int(service.published_port)))
            raise SystemExit(0)

raise SystemExit("no nested unit exposes an 'appio' service")
PY
}

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

if [[ -z "${HPCSHELF_UNIT_PLAN:-}" ]]; then
    log "FATAL: HPCSHELF_UNIT_PLAN is unset, so the nested unit's AppIO cannot be located."
    exit 1
fi

appio_port="$(read_nested_appio_port)" || {
    log "FATAL: no 'appio' service found in this unit's plan (${HPCSHELF_UNIT_PLAN})."
    log "       This unit must nest a component that exposes one."
    exit 1
}
appio_addr="127.0.0.1:${appio_port}"
log "nested AppIO endpoint ${appio_addr} (read from the unit plan)"

exec_pid=""

cleanup() {
    log "stopping"
    [[ -n "$exec_pid" ]] && kill "$exec_pid" 2>/dev/null || true
    wait 2>/dev/null || true
}
trap cleanup TERM INT

if ! wait_port 127.0.0.1 "$appio_port" "$WAIT_TRIES"; then
    log "FATAL: the nested unit's AppIO never opened on ${appio_addr} within ${WAIT_TRIES}s."
    log "       The UnitAgent creates children AFTER the application starts, so a"
    log "       nested unit that fails to come up leaves this SuperExec with nowhere"
    log "       to connect. Refusing to run rather than idling."
    exit 1
fi
log "nested AppIO is reachable"

supervise_exec() {
    "$VENV_BIN/flower-superexec" \
        --insecure \
        --plugin-type "$PLUGIN_TYPE" \
        --appio-api-address "$appio_addr" &
    exec_pid=$!
}

supervise_exec

# The SuperExec is the whole point of this unit, but a crash-restart here is
# cheap and does not disturb the nested unit, which this unit's UnitAgent owns.
while true; do
    if ! kill -0 "$exec_pid" 2>/dev/null; then
        wait "$exec_pid" 2>/dev/null || true
        log "SuperExec exited; restarting"
        supervise_exec
    fi
    sleep 2
done
