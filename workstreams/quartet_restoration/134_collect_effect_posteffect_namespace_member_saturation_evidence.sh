#!/usr/bin/env bash
set -Eeuo pipefail
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
PROJECT_ROOT="$(cd -- "$SCRIPT_DIR/../.." && pwd -P)"
PATHS_FILE="$PROJECT_ROOT/.local/paths.sh"
[[ -f "$PATHS_FILE" ]] && source "$PATHS_FILE"
args=(--project-root "$PROJECT_ROOT")
[[ -n "${BR1_ORIGINAL_ROOT:-}" ]] && args+=(--original-root "$BR1_ORIGINAL_ROOT")
[[ -n "${BR1_QUARTET_ROOT:-}" ]] && args+=(--quartet-root "$BR1_QUARTET_ROOT")
python3 "$SCRIPT_DIR/134_collect_effect_posteffect_namespace_member_saturation_evidence.py" "${args[@]}" "$@"
