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
[[ -f "$REPORT_ROOT/SUMMARY.json" ]] || fail "Run 01_inventory_and_compare.sh first"
[[ -d "$REPORT_ROOT/inventories" ]] || fail "Missing corrected inventory reports"
[[ -d "$REPORT_ROOT/differences" ]] || fail "Missing corrected difference reports"
[[ -d "$WORKSPACE_ROOT/source" ]] || fail "Missing Original extraction workspace: $WORKSPACE_ROOT/source"
[[ -d "$WORKSPACE_ROOT/target" ]] || fail "Missing Quartet extraction workspace: $WORKSPACE_ROOT/target"

exec python3 "$TOOL" collect-structural \
  --project-root "$PROJECT_ROOT"
