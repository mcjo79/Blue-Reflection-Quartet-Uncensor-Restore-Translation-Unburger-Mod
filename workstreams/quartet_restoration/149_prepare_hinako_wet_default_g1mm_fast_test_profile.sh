#!/usr/bin/env bash
set -Eeuo pipefail
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
PROJECT_ROOT="$(cd -- "$SCRIPT_DIR/../.." && pwd -P)"
PATHS_FILE="$PROJECT_ROOT/.local/paths.sh"
PYTHON_TOOL="$SCRIPT_DIR/149_prepare_hinako_wet_default_g1mm_fast_test_profile.py"

fail() { printf '[wet-default-g1mm-profile] ERROR: %s\n' "$*" >&2; exit 1; }
[[ -f "$PATHS_FILE" ]] || fail "Missing local path configuration: $PATHS_FILE"
# shellcheck disable=SC1090
source "$PATHS_FILE"
[[ -n "${BR1_QUARTET_ROOT:-}" ]] || fail "BR1_QUARTET_ROOT is empty"
[[ -d "$BR1_QUARTET_ROOT" ]] || fail "Quartet game root not found: $BR1_QUARTET_ROOT"
if [[ -n "${BR1_ORIGINAL_ROOT:-}" ]]; then
  [[ -d "$BR1_ORIGINAL_ROOT" ]] || fail "Original game root not found: $BR1_ORIGINAL_ROOT"
fi
[[ -f "$PYTHON_TOOL" ]] || fail "Missing stage-149 builder: $PYTHON_TOOL"
GUST="${GUST_PAK_PATH:-$PROJECT_ROOT/.local/vendor/gust_tools/gust_pak}"
[[ -x "$GUST" ]] || fail "gust_pak missing or not executable: $GUST"

args=(
  --project-root "$PROJECT_ROOT"
  --quartet-root "$BR1_QUARTET_ROOT"
  --gust-pak "$GUST"
)
if [[ -n "${BR1_ORIGINAL_ROOT:-}" ]]; then
  args+=(--original-root "$BR1_ORIGINAL_ROOT")
fi

exec python3 "$PYTHON_TOOL" "${args[@]}" "$@"
