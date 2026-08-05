#!/usr/bin/env bash
set -Eeuo pipefail

PROJECT_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
TOOL="$PROJECT_ROOT/Blue_Reflection_Text_Tool/br_restoration_tool.py"
REPORT_ROOT="$PROJECT_ROOT/.local/reports/quartet_restoration"
WORKSPACE_ROOT="$PROJECT_ROOT/.local/build/quartet_restoration"

fail() {
  printf 'ERROR: %s\n' "$*" >&2
  exit 1
}

[[ -f "$TOOL" ]] || fail "Missing restoration tool: $TOOL"
[[ -f "$REPORT_ROOT/material_parameter_evidence/SUMMARY.json" ]] || \
  fail "Run 05_collect_material_parameter_evidence.sh first"
[[ -d "$REPORT_ROOT/inventories" ]] || fail "Missing corrected inventory reports"
[[ -d "$REPORT_ROOT/differences" ]] || fail "Missing corrected difference reports"
[[ -d "$WORKSPACE_ROOT/source" ]] || fail "Missing Original extraction workspace: $WORKSPACE_ROOT/source"
[[ -d "$WORKSPACE_ROOT/target" ]] || fail "Missing Quartet extraction workspace: $WORKSPACE_ROOT/target"

exec python3 "$TOOL" collect-material-deltas \
  --project-root "$PROJECT_ROOT"
