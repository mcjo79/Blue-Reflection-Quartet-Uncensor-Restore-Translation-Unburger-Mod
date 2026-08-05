#!/usr/bin/env bash
set -Eeuo pipefail
PROJECT_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
PATHS_FILE="$PROJECT_ROOT/.local/paths.sh"
TOOL="$PROJECT_ROOT/workstreams/quartet_legacy_dlc/br_dlc_nested_container_tool.py"
fail() { printf 'ERROR: %s\n' "$*" >&2; exit 1; }
[[ -f "$PATHS_FILE" ]] || fail "Missing local path configuration: $PATHS_FILE"
[[ -f "$TOOL" ]] || fail "Missing nested-container tool: $TOOL"
# shellcheck source=/dev/null
source "$PATHS_FILE"
[[ -n "${BR1_ORIGINAL_ROOT:-}" ]] || fail "BR1_ORIGINAL_ROOT is empty"
[[ -d "$BR1_ORIGINAL_ROOT" ]] || fail "Original game root not found: $BR1_ORIGINAL_ROOT"
[[ -n "${BR1_QUARTET_ROOT:-}" ]] || fail "BR1_QUARTET_ROOT is empty"
[[ -d "$BR1_QUARTET_ROOT" ]] || fail "Quartet game root not found: $BR1_QUARTET_ROOT"
exec python3 "$TOOL" audit \
  --project-root "$PROJECT_ROOT" \
  --original-root "$BR1_ORIGINAL_ROOT" \
  --quartet-root "$BR1_QUARTET_ROOT"
