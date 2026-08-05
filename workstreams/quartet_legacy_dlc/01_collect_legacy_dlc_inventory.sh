#!/usr/bin/env bash
set -Eeuo pipefail
PROJECT_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
PATHS_FILE="$PROJECT_ROOT/.local/paths.sh"
TOOL="$PROJECT_ROOT/Blue_Reflection_Text_Tool/br_dlc_tool.py"

fail() {
  printf 'ERROR: %s\n' "$*" >&2
  exit 1
}

[[ -f "$PATHS_FILE" ]] || fail "Missing local path configuration: $PATHS_FILE"
[[ -f "$TOOL" ]] || fail "Missing DLC audit tool: $TOOL"

# shellcheck source=/dev/null
source "$PATHS_FILE"

[[ -n "${BR1_ORIGINAL_ROOT:-}" ]] || fail "BR1_ORIGINAL_ROOT is empty"
[[ -d "$BR1_ORIGINAL_ROOT" ]] || fail "First-game root not found: $BR1_ORIGINAL_ROOT"
[[ -n "${BR1_QUARTET_ROOT:-}" ]] || fail "BR1_QUARTET_ROOT is empty"
[[ -d "$BR1_QUARTET_ROOT" ]] || fail "Quartet root not found: $BR1_QUARTET_ROOT"

printf '[quartet_legacy_dlc] metadata-only inventory\n'
printf '[quartet_legacy_dlc] source: %s\n' "$BR1_ORIGINAL_ROOT"
printf '[quartet_legacy_dlc] target: %s\n' "$BR1_QUARTET_ROOT"
printf '[quartet_legacy_dlc] no game files will be written\n'

exec python3 "$TOOL" audit \
  --project-root "$PROJECT_ROOT" \
  --original-root "$BR1_ORIGINAL_ROOT" \
  --quartet-root "$BR1_QUARTET_ROOT"
