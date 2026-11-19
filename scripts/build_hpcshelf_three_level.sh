#!/usr/bin/env bash
#
# Build the four unit images of the three-level arm.
#
# Produces:
#   localhost/flower-exec-server:0.1.0   SuperExec -> ServerApp, nests `link`
#   localhost/flower-exec-client:0.1.0   SuperExec -> ClientApp, nests `node`
#   localhost/flower-link:0.1.0          SuperLink   (transport, leaf)
#   localhost/flower-node:0.1.0          SuperNode   (transport, leaf)
#
# Two build shapes, and the difference is the point of the arm:
#
#   * the EXEC images are built FROM the platform's podman-unit-base, because those
#     units NEST Podman and the base owns the nested runtime. They carry the
#     application (and therefore the corpus) because the ClientApp is what reads
#     a hospital's records;
#   * the COMM images come from the same base but install the Flower runtime
#     only: no application, no corpus, no torch/pyhealth, no Podman binary. A unit
#     whose whole job is to move parameters should not be able to read a record.
#
# Build contexts differ for the same reason: the exec images need the application
# source (repository root, `.containerignore` carries the exception for this
# directory), while the comm images need only their own supervisors.
#
# Prerequisites:
#   * the pinned platform OCI base already pulled into this user's Podman store;
#   * enough disk for the ML stack, corpus, temporary build layers and four output
#     images. CPU wheels reduce size, but peak space has not yet been measured.
#
# Usage:
#   scripts/build_hpcshelf_three_level.sh
#   scripts/build_hpcshelf_three_level.sh --show-bases
#   HPC_UNIT_BASE=localhost/my-validated-base:v1 scripts/build_hpcshelf_three_level.sh
#
# This builds and tags locally. It does not push anywhere or build/import Incus
# images. Root units reuse the Incus archive pinned in three-level-root's
# artifact.json (platform catalog release 1.4).
#
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

UNIT_BASE="${HPC_UNIT_BASE:-catalog.hpcshelf.org/hpcshelf/podman-unit-base@sha256:8166b4eed4a9476a91800869042a3e1a5a8a037f09d05fafe771da06364bfad2}"
VERSION="${HPC_IMAGE_VERSION:-1.21-test}"
IMAGES_DIR="env/hpcshelf/arms/three-level/images"
EXEC_CONTAINERFILE="$IMAGES_DIR/Containerfile.flower-exec"
COMM_CONTAINERFILE="$IMAGES_DIR/Containerfile.flower-comm"
ROOT_ARTIFACT="env/hpcshelf/arms/three-level/components/three-level-root/0.1/artifact.json"

if [[ "${1:-}" == "--show-bases" && "$#" == 1 ]]; then
    printf 'Podman: %s\nIncus manifest: %s\n' "$UNIT_BASE" "$ROOT_ARTIFACT"
    cat "$ROOT_ARTIFACT"
    exit 0
elif [[ "$#" != 0 ]]; then
    echo "usage: $0 [--show-bases]" >&2
    exit 2
fi

#: image name | role | supervisor file | the line its wrapper must contain
ROLES=(
    "flower-exec-server|exec-server|supervise-exec-server.sh|export FLWR_PLUGIN_TYPE=serverapp"
    "flower-exec-client|exec-client|supervise-exec-client.sh|export FLWR_PLUGIN_TYPE=clientapp"
    "flower-link|link|supervise-link.sh|export FLWR_ROLE=link"
    "flower-node|node|supervise-node.sh|export FLWR_ROLE=node"
)

if ! command -v podman >/dev/null 2>&1; then
    echo "error: podman is required" >&2
    exit 1
fi

if podman image exists "$UNIT_BASE"; then
    :
else
    status=$?
    echo "error: platform base unavailable (podman exit $status): $UNIT_BASE" >&2
    echo "       Pull the pinned image explicitly, with registry access configured:" >&2
    printf '       podman pull %q\n' "$UNIT_BASE" >&2
    echo "       Or set HPC_UNIT_BASE to a separately validated local base." >&2
    echo "       No replacement base will be built under a published identity." >&2
    exit "$status"
fi

echo "==> platform base: $UNIT_BASE"
echo "==> Incus roots reuse the archive in $ROOT_ARTIFACT; no Incus build/import"

for entry in "${ROLES[@]}"; do
    IFS='|' read -r name role supervisor _ <<<"$entry"
    tag="localhost/${name}:${VERSION}"

    case "$name" in
    flower-exec-*)
        containerfile="$EXEC_CONTAINERFILE"
        context="."
        base_arg="BASE_IMAGE=$UNIT_BASE"
        ;;
    *)
        containerfile="$COMM_CONTAINERFILE"
        context="$IMAGES_DIR"
        base_arg="UNIT_BASE=$UNIT_BASE"
        ;;
    esac

    echo ""
    echo "==> building $tag (role file: ${supervisor}, context: ${context})"
    podman build \
        --pull-never \
        -f "$containerfile" \
        --build-arg "$base_arg" \
        --build-arg "SUPERVISOR=${supervisor}" \
        -t "$tag" \
        "$context"
done

# ---------------------------------------------------------------- guard
#
# The roles MUST end up as four distinct images with the right role baked in. An
# earlier revision took the role from an ENV derived from a build-arg, and
# `ENV X=${ARG}` did not invalidate the build cache: both role images came out of
# one layer, both reporting the same role, under two tags. Tagging made that look
# like success. These assertions are why it cannot happen silently again.

fail=0
check() {
    local label="$1" condition="$2"
    if [[ "$condition" == "0" ]]; then
        printf '  \033[32m✓\033[0m %s\n' "$label"
    else
        printf '  \033[31m✗\033[0m %s\n' "$label"
        fail=1
    fi
}

echo ""
echo "==> role guard"

ids=()
for entry in "${ROLES[@]}"; do
    IFS='|' read -r name role supervisor needle <<<"$entry"
    tag="localhost/${name}:${VERSION}"
    ids+=("$(podman image inspect --format '{{.Id}}' "$tag")")
done

check "the four role images are four distinct layers" \
    "$([[ "$(printf '%s\n' "${ids[@]}" | sort -u | wc -l)" == "4" ]] && echo 0 || echo 1)"

for entry in "${ROLES[@]}"; do
    IFS='|' read -r name role supervisor needle <<<"$entry"
    tag="localhost/${name}:${VERSION}"

    # The shared body (supervise-exec.sh / supervise-comm.sh) is not a role: only
    # the wrapper is, and there must be exactly one of them.
    case "$name" in
    flower-exec-*) role_pattern='^supervise-exec-(server|client)\.sh$' ;;
    *) role_pattern='^supervise-(link|node)\.sh$' ;;
    esac

    wrappers="$(podman run --rm --entrypoint sh "$tag" -c \
        "ls /opt/hpcshelf/ | grep -Ec '${role_pattern}'")"
    carries="$(podman run --rm --entrypoint sh "$tag" -c \
        "grep -h '${needle}' /opt/hpcshelf/${supervisor} >/dev/null && echo yes || echo no")"

    check "${role}: carries its supervisor (${supervisor})" \
        "$([[ "$carries" == "yes" ]] && echo 0 || echo 1)"
    check "${role}: exactly one role wrapper in the image" \
        "$([[ "$wrappers" == "1" ]] && echo 0 || echo 1)"
done

echo ""
echo "built:"
for entry in "${ROLES[@]}"; do
    IFS='|' read -r name role _ _ <<<"$entry"
    tag="localhost/${name}:${VERSION}"
    printf '  %-38s %s  %s\n' "$tag" \
        "$(podman image inspect --format '{{.Digest}}' "$tag")" \
        "$(podman image inspect --format '{{.Size}}' "$tag" | numfmt --to=iec)"
done

echo ""
if [[ "$fail" -ne 0 ]]; then
    echo "role guard FAILED: the images cannot fill their roles." >&2
    exit 1
fi
echo "Tags are local. The three-level arm's measurement step is separate:"
echo "  scripts/smoke_hpcshelf_three_level.sh          (the units work, no platform)"
echo "  scripts/validate_hpcshelf_three_level.sh       (the descriptors, the plan, the cost)"
