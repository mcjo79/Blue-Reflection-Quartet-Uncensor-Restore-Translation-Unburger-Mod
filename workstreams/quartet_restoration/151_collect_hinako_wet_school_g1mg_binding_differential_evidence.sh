#!/usr/bin/env bash
set -Eeuo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd -P)"
PATHS="$ROOT/.local/paths.sh"
[[ -f "$PATHS" ]] && source "$PATHS"
: "${BR1_ORIGINAL_ROOT:?BR1_ORIGINAL_ROOT is required (normally from .local/paths.sh)}"
: "${BR1_QUARTET_ROOT:?BR1_QUARTET_ROOT is required (normally from .local/paths.sh)}"
exec python3 -u "$ROOT/workstreams/quartet_restoration/151_collect_hinako_wet_school_g1mg_binding_differential_evidence.py" \
  --project-root "$ROOT" \
  --original-root "$BR1_ORIGINAL_ROOT" \
  --quartet-root "$BR1_QUARTET_ROOT" \
  "$@"
