#!/usr/bin/env bash
set -euo pipefail
PROJECT_ROOT="${BR_PROJECT_ROOT:-$(cd -- "$SCRIPT_DIR/../.." && pwd)}"
BR1_ROOT="${BR_ORIGINAL_ROOT:-${BR_ORIGINAL_GAME_ROOT:?set BR_ORIGINAL_GAME_ROOT to the original BLUE REFLECTION installation}}"
exec python3 "$PROJECT_ROOT/workstreams/quartet_legacy_dlc/br_dlc_br1_canonical_source_tool.py" build-contract \
  --project-root "$PROJECT_ROOT" \
  --br1-root "$BR1_ROOT"
