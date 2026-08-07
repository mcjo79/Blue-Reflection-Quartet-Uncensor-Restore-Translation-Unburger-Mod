#!/usr/bin/env bash
set -Eeuo pipefail
HERE="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
PROJECT_ROOT="$(cd -- "$HERE/../.." && pwd -P)"
[[ -f "$PROJECT_ROOT/.local/paths.sh" ]] || { echo "Missing $PROJECT_ROOT/.local/paths.sh" >&2; exit 1; }
# shellcheck disable=SC1091
source "$PROJECT_ROOT/.local/paths.sh"
: "${BR1_ORIGINAL_ROOT:?BR1_ORIGINAL_ROOT missing from .local/paths.sh}"
: "${BR1_QUARTET_ROOT:?BR1_QUARTET_ROOT missing from .local/paths.sh}"
exec python3 "$HERE/163_collect_wetness_transition_structured_selector_binding_evidence.py" \
  "$PROJECT_ROOT" \
  --original-root "$BR1_ORIGINAL_ROOT" \
  --quartet-root "$BR1_QUARTET_ROOT" \
  "$@"
