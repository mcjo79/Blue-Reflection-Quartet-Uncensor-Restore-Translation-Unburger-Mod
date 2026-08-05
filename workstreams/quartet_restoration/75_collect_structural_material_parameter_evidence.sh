#!/usr/bin/env bash
set -Eeuo pipefail

PROJECT_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
TOOL="$PROJECT_ROOT/workstreams/quartet_restoration/collect_structural_material_parameter_evidence.py"
REPORT_ROOT="$PROJECT_ROOT/.local/reports/quartet_restoration"
WORKSPACE_ROOT="$PROJECT_ROOT/.local/build/quartet_restoration"

fail() {
  printf 'ERROR: %s\n' "$*" >&2
  exit 1
}

[[ -f "$TOOL" ]] || fail "Missing stage-75 collector: $TOOL"
[[ -d "$WORKSPACE_ROOT/source" ]] || fail "Missing Original extraction workspace"
[[ -d "$WORKSPACE_ROOT/target" ]] || fail "Missing Quartet extraction workspace"
if [[ ! -f "$REPORT_ROOT/wet_coverage_material_variant_evidence/SUMMARY.json" \
      && ! -f "$REPORT_ROOT/BR_quartet_restoration_wet_coverage_material_variant_evidence.tar.zst" ]]; then
  fail "Missing stage-74 material-variant evidence"
fi
[[ -d "$REPORT_ROOT/differences" ]] || fail "Missing canonical difference reports"

exec python3 -u "$TOOL" --project-root "$PROJECT_ROOT" "$@"
