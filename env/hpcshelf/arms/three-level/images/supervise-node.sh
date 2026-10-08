#!/usr/bin/env bash
#
# Role: node (SuperNode). Pins the role and hands off to the shared body.
#
# See supervise-link.sh for why the role is a file, and supervise-comm.sh for the
# partition-identity rule and the 0.0.0.0 binding.
set -euo pipefail

export FLWR_ROLE=node
exec /opt/hpcshelf/supervise-comm.sh
