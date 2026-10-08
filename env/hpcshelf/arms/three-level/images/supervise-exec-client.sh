#!/usr/bin/env bash
#
# Role: exec-client. Sets the Flower plugin type and hands off to the shared
# supervisor body.
#
# The role lives in a FILE rather than in a build-arg-derived ENV on purpose:
# `ENV X=${ARG}` did not invalidate the build cache here, so both role images
# came out of the same layer with the same plugin type and the same image ID.
# A per-role file cannot be silently shared, and it makes the role visible in
# the unit's application command.
#
# See supervise-exec.sh for the mechanism and the ordering caveat.
set -euo pipefail

export FLWR_PLUGIN_TYPE=clientapp
exec /opt/hpcshelf/supervise-exec.sh
