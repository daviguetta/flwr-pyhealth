#!/usr/bin/env bash
#
# Prove the frozen federation decomposition against the HPC Shelf platform.
#
# Runs the platform's own SemanticValidator and DeploymentPlanner over the
# descriptors in env/hpcshelf/. No infrastructure is needed and nothing is
# written to the platform repository: its modules are imported read-only from
# HPCSHELF_MODEL_ROOT.
#
# Usage:
#   scripts/validate_hpcshelf.sh
#   HPCSHELF_MODEL_ROOT=~/src/hpcshelf-model scripts/validate_hpcshelf.sh
#   HPCSHELF_VAL_PYTHON=/path/to/venv/bin/python scripts/validate_hpcshelf.sh
#
# The interpreter must carry the platform's pinned dependencies
# (pydantic==2.13.5, PyYAML==6.0.3). Create it once with:
#
#   uv venv /tmp/hpcshelf-val-venv --python 3.12
#   uv pip install --python /tmp/hpcshelf-val-venv/bin/python \
#       -r "$HPCSHELF_MODEL_ROOT/requirements.txt"
#
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

MODEL_ROOT="${HPCSHELF_MODEL_ROOT:-/tmp/hpcshelf-model}"
if [[ ! -f "$MODEL_ROOT/semantic_validator.py" ]]; then
    echo "error: no hpcshelf-model checkout at $MODEL_ROOT" >&2
    echo "       point HPCSHELF_MODEL_ROOT at a clone of the platform" >&2
    exit 1
fi
export HPCSHELF_MODEL_ROOT="$MODEL_ROOT"
export PYTHONDONTWRITEBYTECODE=1

PYTHON="${HPCSHELF_VAL_PYTHON:-/tmp/hpcshelf-val-venv/bin/python}"
if [[ ! -x "$PYTHON" ]]; then
    PYTHON="$(command -v python3 || true)"
fi
if [[ -z "$PYTHON" ]]; then
    echo "error: no interpreter found; set HPCSHELF_VAL_PYTHON" >&2
    exit 1
fi

if ! "$PYTHON" -c 'import pydantic, yaml' 2>/dev/null; then
    echo "error: $PYTHON cannot import pydantic/PyYAML" >&2
    echo "       create the validation venv (see the header of this script)" >&2
    exit 1
fi

echo "platform:    $MODEL_ROOT"
echo "interpreter: $PYTHON"
"$PYTHON" -c 'import pydantic; print("pydantic:    " + pydantic.VERSION)'

exec "$PYTHON" env/hpcshelf/validate.py
