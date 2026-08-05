#!/usr/bin/env bash
set -euo pipefail
PROJECT_ROOT="${BR_PROJECT_ROOT:-$(cd -- "$SCRIPT_DIR/../.." && pwd)}"
ORIGINAL_ROOT="${BR_ORIGINAL_ROOT:-${BR_ORIGINAL_GAME_ROOT:?set BR_ORIGINAL_GAME_ROOT to the original BLUE REFLECTION installation}}"
QUARTET_ROOT="${BR_QUARTET_ROOT:-${BR_QUARTET_GAME_ROOT:?set BR_QUARTET_GAME_ROOT to the BLUE REFLECTION Quartet installation}}"
exec python3 "$PROJECT_ROOT/workstreams/quartet_legacy_dlc/br_dlc_transfer_probe_tool.py" audit \
  --project-root "$PROJECT_ROOT" \
  --original-root "$ORIGINAL_ROOT" \
  --quartet-root "$QUARTET_ROOT"
