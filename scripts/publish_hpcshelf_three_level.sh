#!/usr/bin/env bash
#
# Publish the three-level arm's unit images and materialise the HPC Shelf catalog.
#
# Four images, three components, three artifact.json. Pushes the unit images to a
# registry, reads back the digest the registry reports, writes artifact.json next
# to each component.yaml, and verifies the result with the platform's own
# FilesystemCatalog, integrity checks and DeploymentPlanner.
#
# WHY THIS IS A SEPARATE ENTRY POINT
#
# The grouped arm's wrapper publishes one image-bearing component; this arm has
# two (`comunicacao` and `exec`), plus a root component that reuses the platform's
# base by exact digest. The unit -> repository map is therefore per component, and
# `env/hpcshelf/arms/three-level/publish.py` is what carries it. The catalog tree
# lands in a DIFFERENT default directory on purpose, so a three-level rehearsal
# cannot overwrite the grouped arm's.
#
# The platform's registry is a remote, credentialed target: pushing there needs
# explicit authorisation, and its project path must be confirmed first. This
# script is deliberately registry-agnostic so the whole path can be rehearsed
# against a local registry:
#
#   podman run -d --name hpcshelf-registry -p 127.0.0.1:5000:5000 registry:2
#   scripts/build_hpcshelf_three_level.sh
#   scripts/publish_hpcshelf_three_level.sh --registry localhost:5000 --insecure
#
# Usage:
#   scripts/publish_hpcshelf_three_level.sh --registry localhost:5000 --insecure
#   scripts/publish_hpcshelf_three_level.sh --registry catalog.example.org --project pyhealth
#
# The interpreter must carry the platform's pinned dependencies
# (pydantic==2.13.5, PyYAML==6.0.3); see scripts/validate_hpcshelf_three_level.sh.
#
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

MODEL_ROOT="${HPCSHELF_MODEL_ROOT:-/tmp/hpcshelf-model}"
if [[ ! -f "$MODEL_ROOT/catalog.py" ]]; then
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
    echo "       create the validation venv (see scripts/validate_hpcshelf_three_level.sh)" >&2
    exit 1
fi

echo "platform:    $MODEL_ROOT"
echo "interpreter: $PYTHON"

exec "$PYTHON" env/hpcshelf/arms/three-level/publish.py "$@"
