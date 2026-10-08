#!/usr/bin/env bash
#
# Application command for the federation HUB unit.
#
# Per the gap #2 decision (docs/HPC_SHELF_INTEGRATION.md, section 4): HPC Shelf
# accepts one application command per unit, and a horizontal dependency only
# resolves inside one component, so the hub's two Flower processes share this
# container and are supervised here.
#
#   SuperLink            fleet 0.0.0.0:9092   <- the only port that leaves the unit
#                        serverappio 127.0.0.1:9091  <- loopback, SuperExec only
#   SuperExec ServerApp  -> 127.0.0.1:9091
#
# Lifecycle: the SuperLink is the unit's critical process; if it exits, the unit
# has failed and this script exits non-zero so the UnitAgent reports failure.
# The SuperExec is restarted if it exits on its own, without taking the
# SuperLink down with it.
#
# TIMING: everything here is cleartext (`--insecure`). Turning on TLS is Phase 5;
# until then this unit must not be deployed across a network the institution
# does not control.
#
# Environment (all optional; defaults match Flower 1.34):
#   FLEET_ADDR          fleet listen address          (0.0.0.0:9092)
#   SERVERAPPIO_ADDR    serverappio listen address    (127.0.0.1:9091)
#   VENV_BIN            directory holding the Flower CLIs (/python/venv/bin)
#
set -euo pipefail

VENV_BIN="${VENV_BIN:-/python/venv/bin}"
FLEET_ADDR="${FLEET_ADDR:-0.0.0.0:9092}"
SERVERAPPIO_ADDR="${SERVERAPPIO_ADDR:-127.0.0.1:9091}"

log() { printf '[hub] %s\n' "$*"; }

# Wait until a TCP endpoint accepts connections. The SuperExec retries a closed
# port forever, which presents as a hang rather than a failure, so the SuperExec
# is not started until the SuperLink is actually listening.
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

superlink_pid=""
superexec_pid=""

cleanup() {
    log "stopping"
    [[ -n "$superexec_pid" ]] && kill "$superexec_pid" 2>/dev/null || true
    [[ -n "$superlink_pid" ]] && kill "$superlink_pid" 2>/dev/null || true
    wait 2>/dev/null || true
}
trap cleanup TERM INT

log "starting SuperLink (fleet=${FLEET_ADDR} serverappio=${SERVERAPPIO_ADDR})"
"$VENV_BIN/flower-superlink" \
    --insecure \
    --isolation process \
    --fleet-api-address "$FLEET_ADDR" \
    --serverappio-api-address "$SERVERAPPIO_ADDR" &
superlink_pid=$!

appio_host="${SERVERAPPIO_ADDR%:*}"
appio_port="${SERVERAPPIO_ADDR##*:}"

if ! wait_port "$appio_host" "$appio_port"; then
    log "FATAL: SuperLink did not open ${SERVERAPPIO_ADDR} within 60s"
    exit 1
fi
log "SuperLink is listening on ${SERVERAPPIO_ADDR}"

supervise_superexec() {
    "$VENV_BIN/flower-superexec" \
        --insecure \
        --plugin-type serverapp \
        --appio-api-address "${appio_host}:${appio_port}" &
    superexec_pid=$!
}

supervise_superexec

while true; do
    if ! kill -0 "$superlink_pid" 2>/dev/null; then
        wait "$superlink_pid" || true
        log "FATAL: SuperLink exited; the hub unit cannot serve the federation"
        exit 1
    fi

    if ! kill -0 "$superexec_pid" 2>/dev/null; then
        wait "$superexec_pid" 2>/dev/null || true
        log "SuperExec (ServerApp) exited; restarting"
        supervise_superexec
    fi

    sleep 2
done
