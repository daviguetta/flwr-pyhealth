#!/usr/bin/env bash
#
# Run a federated simulation using Flower's Simulation Runtime (Ray backend).
#
# Simulation is the default mode of `flwr run`, so this script is the primary
# entry point for development and for reproducing experiments. Everything is
# overridable through environment variables, which keeps a run describable in
# one line without editing pyproject.toml.
#
# Usage:
#   scripts/simulate.sh
#   ROUNDS=5 STRATEGY=fedprox MU=0.1 SCHEME=label-skew scripts/simulate.sh
#   DP_MODE=server-fixed-clipping DP_NOISE=1.0 scripts/simulate.sh
#
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

VENV="${PYHEALTH_VENV:-$ROOT/.venv}"
if [[ ! -x "$VENV/bin/flwr" ]]; then
    echo "error: no Flower CLI at $VENV/bin/flwr" >&2
    echo "       create the environment first: uv sync" >&2
    exit 1
fi
# The Flower CLI launches flower-superlink as a subprocess, so it must be on PATH.
export PATH="$VENV/bin:$PATH"

# Ray collapses identical log lines across workers by default. That hides the
# per-node cohort sizes, which are the first evidence that a run is actually
# federated rather than every node training on the same partition. Keep them.
export RAY_DEDUP_LOGS="${RAY_DEDUP_LOGS:-0}"

ROUNDS="${ROUNDS:-2}"
EPOCHS="${EPOCHS:-1}"
LR="${LR:-0.00001}"
BATCH_SIZE="${BATCH_SIZE:-32}"
PARTITIONS="${PARTITIONS:-2}"
SCHEME="${SCHEME:-uniform}"
STRATEGY="${STRATEGY:-fedavg}"
MU="${MU:-0.0}"
DP_MODE="${DP_MODE:-none}"
DP_NOISE="${DP_NOISE:-0.0}"
DP_CLIP="${DP_CLIP:-1.0}"

echo "──────────────────────────────────────────────────────────────"
echo " Federated simulation"
echo "   partitions   : $PARTITIONS ($SCHEME)"
echo "   strategy     : $STRATEGY (mu=$MU)"
echo "   rounds/epochs: $ROUNDS / $EPOCHS"
echo "   privacy      : $DP_MODE"
echo "──────────────────────────────────────────────────────────────"

exec flwr run . \
    --federation-config "num-supernodes=$PARTITIONS" \
    --run-config "num-server-rounds=$ROUNDS local-epochs=$EPOCHS learning-rate=$LR batch-size=$BATCH_SIZE num-partitions=$PARTITIONS strategy=\"$STRATEGY\" proximal-mu=$MU partition-scheme=\"$SCHEME\" dp-mode=\"$DP_MODE\" dp-noise-multiplier=$DP_NOISE dp-clipping-norm=$DP_CLIP" \
    --stream
