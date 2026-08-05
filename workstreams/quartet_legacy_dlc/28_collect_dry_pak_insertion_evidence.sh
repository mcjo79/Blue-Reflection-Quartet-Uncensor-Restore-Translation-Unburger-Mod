#!/usr/bin/env bash
set -euo pipefail
PROJECT_ROOT="${BR_PROJECT_ROOT:-$(cd -- "$SCRIPT_DIR/../.." && pwd)}"
QUARTET_ROOT="${BR_QUARTET_ROOT:-${BR_QUARTET_GAME_ROOT:?set BR_QUARTET_GAME_ROOT to the BLUE REFLECTION Quartet installation}}"
GUST_PAK_BIN="${GUST_PAK:-$PROJECT_ROOT/.local/vendor/gust_tools/gust_pak}"
exec python3 "$PROJECT_ROOT/workstreams/quartet_legacy_dlc/br_dlc_dry_pak_insertion_tool.py" audit \
  --project-root "$PROJECT_ROOT" \
  --quartet-root "$QUARTET_ROOT" \
  --gust-pak "$GUST_PAK_BIN"
