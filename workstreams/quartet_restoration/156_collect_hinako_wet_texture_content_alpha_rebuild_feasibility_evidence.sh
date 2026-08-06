#!/usr/bin/env bash
set -Eeuo pipefail
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
PROJECT_ROOT="$(cd -- "$SCRIPT_DIR/../.." && pwd -P)"
PATHS="$PROJECT_ROOT/.local/paths.sh"
[[ -f "$PATHS" ]] || { printf '[stage156] ERROR: missing %s\n' "$PATHS" >&2; exit 2; }
# shellcheck disable=SC1090
source "$PATHS"
[[ -n "${BR1_ORIGINAL_ROOT:-}" ]] || { printf '[stage156] ERROR: BR1_ORIGINAL_ROOT is not configured\n' >&2; exit 2; }
[[ -n "${BR1_QUARTET_ROOT:-}" ]] || { printf '[stage156] ERROR: BR1_QUARTET_ROOT is not configured\n' >&2; exit 2; }
exec python3 "$SCRIPT_DIR/156_collect_hinako_wet_texture_content_alpha_rebuild_feasibility_evidence.py" \
  --project-root "$PROJECT_ROOT" --original-root "$BR1_ORIGINAL_ROOT" --quartet-root "$BR1_QUARTET_ROOT"
