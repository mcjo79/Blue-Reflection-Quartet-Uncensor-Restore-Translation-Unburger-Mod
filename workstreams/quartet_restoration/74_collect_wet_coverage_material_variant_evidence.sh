#!/usr/bin/env bash
set -Eeuo pipefail

PROJECT_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
TOOL="$PROJECT_ROOT/workstreams/quartet_restoration/collect_wet_coverage_material_variant_evidence.py"
REPORT_ROOT="$PROJECT_ROOT/.local/reports/quartet_restoration"

fail() {
  printf 'ERROR: %s\n' "$*" >&2
  exit 1
}

[[ -f "$TOOL" ]] || fail "Missing stage-74 tool: $TOOL"
[[ -f "$REPORT_ROOT/core_profile_manifest_evidence/SUMMARY.json" ]] || \
  fail "Missing stage-73 core profile manifest evidence directory"
[[ -f "$REPORT_ROOT/material_delta_evidence/SUMMARY.json" ]] || \
  fail "Missing material-delta evidence; run stage 6 only if the local report was removed"
[[ -f "$REPORT_ROOT/material_delta_evidence/FOCUSED_MATERIAL_REVIEW.tsv" ]] || \
  fail "Missing focused material review table"

exec python3 -u "$TOOL" --project-root "$PROJECT_ROOT" "$@"
