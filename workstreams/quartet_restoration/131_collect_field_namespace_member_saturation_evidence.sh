#!/usr/bin/env bash
set -Eeuo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
PATHS_FILE="$ROOT/.local/paths.sh"
if [[ -f "$PATHS_FILE" ]]; then
  # shellcheck disable=SC1090
  source "$PATHS_FILE"
fi
args=(--project-root "$ROOT")
[[ -n "${BR1_ORIGINAL_ROOT:-}" ]] && args+=(--original-root "$BR1_ORIGINAL_ROOT")
[[ -n "${BR1_QUARTET_ROOT:-}" ]] && args+=(--quartet-root "$BR1_QUARTET_ROOT")
exec python3 -u "$ROOT/workstreams/quartet_restoration/131_collect_field_namespace_member_saturation_evidence.py" "${args[@]}" "$@"
