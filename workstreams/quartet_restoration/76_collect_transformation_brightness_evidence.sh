#!/usr/bin/env bash
set -Eeuo pipefail

PROJECT_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
TOOL="$PROJECT_ROOT/workstreams/quartet_restoration/collect_transformation_brightness_evidence.py"
REPORT_ROOT="$PROJECT_ROOT/.local/reports/quartet_restoration"

fail() {
  printf 'ERROR: %s\n' "$*" >&2
  exit 1
}

[[ -f "$TOOL" ]] || fail "Missing stage-76 tool: $TOOL"
[[ -f "$REPORT_ROOT/core_profile_manifest_evidence/SUMMARY.json" ]] || fail "Missing stage-73 core registry report"
[[ -f "$REPORT_ROOT/structural_material_parameter_evidence/SUMMARY.json" ]] || fail "Missing completed stage-75 report"
[[ -f "$REPORT_ROOT/presentation_surface_evidence/SUMMARY.json" ]] || fail "Missing stage-12 presentation-surface report"
[[ -f "$REPORT_ROOT/shader_effect_evidence/SUMMARY.json" ]] || fail "Missing stage-7 shader/effect report"
[[ -f "$REPORT_ROOT/binary_delta_evidence/SUMMARY.json" ]] || fail "Missing stage-8 binary-delta report"
[[ -d "$REPORT_ROOT/differences" ]] || fail "Missing corrected difference reports"

exec python3 -u "$TOOL" --project-root "$PROJECT_ROOT" "$@"
