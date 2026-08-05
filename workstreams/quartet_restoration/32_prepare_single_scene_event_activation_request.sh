#!/usr/bin/env bash
set -Eeuo pipefail

PROJECT_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
PATHS_FILE="$PROJECT_ROOT/.local/paths.sh"
TOOL="$PROJECT_ROOT/Blue_Reflection_Text_Tool/br_restoration_tool.py"

fail() {
  printf 'ERROR: %s\n' "$*" >&2
  exit 1
}

[[ -f "$PATHS_FILE" ]] || fail "Missing local path configuration: $PATHS_FILE"
[[ -f "$TOOL" ]] || fail "Missing restoration tool: $TOOL"

# shellcheck source=/dev/null
source "$PATHS_FILE"

[[ -n "${BR1_QUARTET_ROOT:-}" ]] || fail "BR1_QUARTET_ROOT is empty"
[[ -d "$BR1_QUARTET_ROOT" ]] || fail "Quartet game root not found: $BR1_QUARTET_ROOT"

exec python3 "$TOOL" prepare-single-scene-event-activation-request \
  --project-root "$PROJECT_ROOT" \
  --quartet-root "$BR1_QUARTET_ROOT" \
  "$@"
