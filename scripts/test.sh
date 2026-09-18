#!/usr/bin/env bash
#
# Run the test suite.
#
# The default run skips the `slow` marker, which loads the bundled MIMIC-IV demo
# and costs tens of seconds plus hundreds of megabytes. Use `scripts/test.sh all`
# to include it, which is what CI should do.
#
# Usage:
#   scripts/test.sh          # fast: contracts, partitioning, strategies, privacy
#   scripts/test.sh all      # everything, including the real data pipeline
#   scripts/test.sh slow     # only the real data pipeline
#
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

VENV="${PYHEALTH_VENV:-$ROOT/.venv}"
if [[ ! -x "$VENV/bin/python" ]]; then
    echo "error: no interpreter at $VENV/bin/python" >&2
    echo "       create the environment first: uv sync" >&2
    exit 1
fi

SELECTION="${1:-fast}"
case "$SELECTION" in
    fast) exec "$VENV/bin/python" -m pytest -m "not slow" "$@" ;;
    slow) exec "$VENV/bin/python" -m pytest -m "slow" -p no:cacheprovider "$@" ;;
    all)  exec "$VENV/bin/python" -m pytest -p no:cacheprovider "$@" ;;
    *)
        echo "error: unknown selection '$SELECTION' (expected: fast|slow|all)" >&2
        exit 1
        ;;
esac
