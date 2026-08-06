#!/usr/bin/env bash
set -Eeuo pipefail
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
PROJECT_ROOT="$(cd -- "$SCRIPT_DIR/../.." && pwd -P)"
PATHS_FILE="$PROJECT_ROOT/.local/paths.sh"
if [[ -f "$PATHS_FILE" ]]; then
  # shellcheck disable=SC1090
  source "$PATHS_FILE"
fi
args=(--project-root "$PROJECT_ROOT")
[[ -n "${BR1_ORIGINAL_ROOT:-}" ]] && args+=(--original-root "$BR1_ORIGINAL_ROOT")
[[ -n "${BR1_QUARTET_ROOT:-}" ]] && args+=(--quartet-root "$BR1_QUARTET_ROOT")
exec python3 -u "$SCRIPT_DIR/133_collect_shader_namespace_executable_signature_reflection_sweep_evidence.py" "${args[@]}" "$@"
