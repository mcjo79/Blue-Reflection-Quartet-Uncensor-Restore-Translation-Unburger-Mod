#!/usr/bin/env bash
set -Eeuo pipefail
PROJECT_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
TOOL="$PROJECT_ROOT/Blue_Reflection_Text_Tool/br_restoration_tool.py"
REPORT_ROOT="$PROJECT_ROOT/.local/reports/quartet_restoration"
WORKSPACE_ROOT="$PROJECT_ROOT/.local/build/quartet_restoration"
REFLECTION_SUMMARY="$REPORT_ROOT/dxbc_reflection_evidence/SUMMARY.json"
RULES_FILE="$PROJECT_ROOT/titles/blue_reflection/modules/quartet_restoration/mappings/effect_material_rules.tsv"

[[ -f "$TOOL" ]] || { printf 'Missing restoration tool: %s\n' "$TOOL" >&2; exit 1; }
[[ -f "$REFLECTION_SUMMARY" ]] || {
  printf 'Missing DXBC reflection evidence: %s\n' "$REFLECTION_SUMMARY" >&2
  printf 'Run stage 09 first.\n' >&2
  exit 1
}
[[ -d "$WORKSPACE_ROOT" ]] || { printf 'Missing restoration workspace: %s\n' "$WORKSPACE_ROOT" >&2; exit 1; }
[[ -f "$RULES_FILE" ]] || { printf 'Missing restoration rules: %s\n' "$RULES_FILE" >&2; exit 1; }

exec python3 "$TOOL" collect-g1s-envelope \
  --project-root "$PROJECT_ROOT"
