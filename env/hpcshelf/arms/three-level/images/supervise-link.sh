#!/usr/bin/env bash
#
# Role: link (SuperLink). Pins the role and hands off to the shared body.
#
# The role lives in a FILE rather than in a build-arg-derived ENV on purpose:
# the three-level arm's exec images learned that `ENV X=${ARG}` does not invalidate the
# build cache, so both roles came out of one layer under two tags. A per-role file
# cannot be shared by accident, and it makes the role visible in the unit's
# application command.
#
# See supervise-comm.sh for the mechanism and for why the Runtime API here binds
# 0.0.0.0 instead of loopback.
set -euo pipefail

export FLWR_ROLE=link
exec /opt/hpcshelf/supervise-comm.sh
