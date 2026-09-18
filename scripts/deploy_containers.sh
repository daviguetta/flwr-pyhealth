#!/usr/bin/env bash
#
# Drive the container topology: a Flower SuperLink, two SuperNodes and three
# SuperExec processes, matching the distributed-component model used by the
# Incus/Podman deployment.
#
# Usage:
#   scripts/deploy_containers.sh up        # build and start the topology
#   scripts/deploy_containers.sh run       # submit the app to it and stream logs
#   scripts/deploy_containers.sh logs      # follow container logs
#   scripts/deploy_containers.sh down      # stop and remove the topology
#
# The `run` step needs a SuperLink connection named `local-deployment` in the
# Flower configuration. Print the exact command with:
#   flwr config list
#
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

COMPOSE_FILE="${COMPOSE_FILE:-podman-compose.yml}"
IMAGE="${IMAGE:-pyhealth-flower-superexec:0.1.0}"
SUPERLINK_CONNECTION="${SUPERLINK_CONNECTION:-local-deployment}"

# `podman compose` needs an external provider; fall back to podman-compose.
if podman compose version >/dev/null 2>&1; then
    COMPOSE=(podman compose -f "$COMPOSE_FILE")
elif command -v podman-compose >/dev/null 2>&1; then
    COMPOSE=(podman-compose -f "$COMPOSE_FILE")
else
    echo "error: neither 'podman compose' nor 'podman-compose' is available" >&2
    echo "       install podman-compose or configure the Docker Compose provider" >&2
    exit 1
fi

ensure_connection_hint() {
    cat <<EOF

The deployment runtime needs a SuperLink connection in the Flower configuration.
If 'flwr config list' does not show '${SUPERLINK_CONNECTION}', add this to
~/.flwr/config.toml:

  [superlink.${SUPERLINK_CONNECTION}]
  address = "127.0.0.1:9093"
  insecure = true

EOF
}

case "${1:-}" in
    up)
        echo "──────────────────────────────────────────────────────────────"
        echo " Building $IMAGE and starting the Flower topology"
        echo "──────────────────────────────────────────────────────────────"
        "${COMPOSE[@]}" up -d --build
        echo
        "${COMPOSE[@]}" ps
        ensure_connection_hint
        ;;
    run)
        # Each SuperNode is configured with its own partition-id, so no
        # num-partitions guessing happens at run time.
        flwr run . "$SUPERLINK_CONNECTION" --stream
        ;;
    logs)
        "${COMPOSE[@]}" logs -f
        ;;
    down)
        "${COMPOSE[@]}" down
        ;;
    *)
        echo "usage: $0 {up|run|logs|down}" >&2
        exit 1
        ;;
esac
