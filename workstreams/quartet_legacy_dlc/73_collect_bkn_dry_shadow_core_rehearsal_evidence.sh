#!/usr/bin/env bash
set -euo pipefail
PROJECT_ROOT="${BR_PROJECT_ROOT:-$(cd -- "$SCRIPT_DIR/../.." && pwd)}"
exec python3 "$PROJECT_ROOT/workstreams/quartet_legacy_dlc/br_dlc_bkn_dry_shadow_core_rehearsal_tool.py" build-rehearsal \
  --project-root "$PROJECT_ROOT"
