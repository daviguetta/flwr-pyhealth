#!/usr/bin/env bash
#
# Build the two HPC Shelf unit images for the federation.
#
# Produces:
#   localhost/flower-hub:0.1.0        SuperLink + SuperExec(ServerApp)
#   localhost/flower-hospital:0.1.0   SuperNode + SuperExec(ClientApp)
#
# Both are thin layers over this project's Flower application image, carrying
# the HPC Shelf unit bootstrap (UnitAgent + entrypoint) copied from the
# platform's base image. See env/hpcshelf/arms/grouped/images/Containerfile.flower-unit for
# why the layering is required rather than merely convenient.
#
# Prerequisites:
#   * the application image, built by scripts/deploy_containers.sh build;
#   * the platform base, or a platform checkout to build it from. The published
#     base lives in the platform's registry, so a local checkout is used when
#     the tag is absent.
#
# Usage:
#   scripts/build_hpcshelf_images.sh
#   HPCSHELF_MODEL_ROOT=~/src/hpcshelf-model scripts/build_hpcshelf_images.sh
#
# This builds and tags locally. It does not push anywhere.
#
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

APP_IMAGE="${HPC_APP_IMAGE:-localhost/pyhealth-flower-superexec:0.1.0}"
UNIT_BASE="${HPC_UNIT_BASE:-localhost/podman-unit-base:local}"
VERSION="${HPC_IMAGE_VERSION:-0.1.0}"
CONTEXT="$ROOT/env/hpcshelf/arms/grouped/images"
MODEL_ROOT="${HPCSHELF_MODEL_ROOT:-/tmp/hpcshelf-model}"

if ! command -v podman >/dev/null 2>&1; then
    echo "error: podman is required" >&2
    exit 1
fi

image_exists() {
    podman image exists "$1"
}

if ! image_exists "$APP_IMAGE"; then
    echo "error: application image not found: $APP_IMAGE" >&2
    echo "       build it first: scripts/deploy_containers.sh build" >&2
    exit 1
fi

if ! image_exists "$UNIT_BASE"; then
    if [[ ! -d "$MODEL_ROOT/podman-unit-base" ]]; then
        echo "error: platform base not found: $UNIT_BASE" >&2
        echo "       and no platform checkout at $MODEL_ROOT to build it from." >&2
        echo "       set HPCSHELF_MODEL_ROOT to a clone of hpcshelf-model." >&2
        exit 1
    fi
    echo "==> building platform base $UNIT_BASE from $MODEL_ROOT/podman-unit-base"
    podman build -t "$UNIT_BASE" "$MODEL_ROOT/podman-unit-base"
fi

echo "==> application image: $APP_IMAGE"
echo "==> platform base:     $UNIT_BASE"

for role in hub hospital; do
    tag="localhost/flower-${role}:${VERSION}"
    echo ""
    echo "==> building $tag (supervisor: supervise-${role}.sh)"
    podman build \
        -f "$CONTEXT/Containerfile.flower-unit" \
        --build-arg "APP_IMAGE=$APP_IMAGE" \
        --build-arg "UNIT_BASE=$UNIT_BASE" \
        --build-arg "SUPERVISOR=supervise-${role}.sh" \
        -t "$tag" \
        "$CONTEXT"
done

echo ""
echo "built:"
for role in hub hospital; do
    tag="localhost/flower-${role}:${VERSION}"
    digest="$(podman image inspect --format '{{.Digest}}' "$tag")"
    printf '  %-38s %s\n' "$tag" "${digest:-<none>}"
done
echo ""
echo "These tags are local. Publishing to the HPC Shelf catalog is a separate,"
echo "authorised step; see env/hpcshelf/arms/grouped/images/README.md."
