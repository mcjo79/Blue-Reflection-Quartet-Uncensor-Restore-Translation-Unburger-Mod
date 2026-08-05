#!/usr/bin/env bash
set -Eeuo pipefail

PROJECT_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
REGISTRAR="$PROJECT_ROOT/workstreams/quartet_restoration/register_residual_shared_presentation_core_profile.py"
CORE_LIST="$PROJECT_ROOT/Blue_Reflection_Patcher/cmd/br_quartet_profiles.sh"
REPORT="$PROJECT_ROOT/.local/reports/quartet_restoration/BR_quartet_restoration_residual_shared_presentation_repack_test_evidence.tar.zst"

fail() {
  printf 'ERROR: %s\n' "$*" >&2
  exit 1
}

[[ -f "$REGISTRAR" ]] || fail "Missing stage-38 registrar: $REGISTRAR"
[[ -f "$CORE_LIST" ]] || fail "Core 0.0.17+ profile command is missing: $CORE_LIST"
[[ -f "$REPORT" ]] || fail "Missing stage-37 evidence report: $REPORT"

python3 "$REGISTRAR" --project-root "$PROJECT_ROOT"

printf '\nCore registry validation:\n'
cd "$PROJECT_ROOT"
exec bash "$CORE_LIST" list
