#!/usr/bin/env bash
set -Eeuo pipefail
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
PROJECT_ROOT="$(cd -- "$SCRIPT_DIR/../.." && pwd -P)"
PATHS_FILE="$PROJECT_ROOT/.local/paths.sh"
[[ -f "$PATHS_FILE" ]] || { printf 'ERROR: Missing local path configuration: %s\n' "$PATHS_FILE" >&2; exit 1; }
# shellcheck disable=SC1090
source "$PATHS_FILE"
[[ -n "${BR1_QUARTET_ROOT:-}" ]] || { printf 'ERROR: BR1_QUARTET_ROOT is empty\n' >&2; exit 1; }
GUST="${GUST_PAK_PATH:-$PROJECT_ROOT/.local/vendor/gust_tools/gust_pak}"
exec python3 "$SCRIPT_DIR/143_prepare_effect_posteffect_kps_fast_test_lab_profiles.py" \
  --project-root "$PROJECT_ROOT" \
  --quartet-root "$BR1_QUARTET_ROOT" \
  --gust-pak "$GUST" \
  "$@"
