#!/usr/bin/env bash
set -Eeuo pipefail

PROJECT_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
TOOL="$PROJECT_ROOT/workstreams/quartet_restoration/collect_yuzuki_rfl50_event_binding_evidence.py"
REPORT_ROOT="$PROJECT_ROOT/.local/reports/quartet_restoration"
WORKSPACE_ROOT="$PROJECT_ROOT/.local/build/quartet_restoration"

fail() {
  printf 'ERROR: %s\n' "$*" >&2
  exit 1
}

[[ -f "$TOOL" ]] || fail "Missing stage-77 tool: $TOOL"
[[ -d "$REPORT_ROOT/differences" ]] || fail "Missing corrected difference reports"
[[ -d "$WORKSPACE_ROOT" ]] || fail "Missing restoration workspace"
if [[ ! -f "$REPORT_ROOT/transformation_brightness_evidence/SUMMARY.json" \
   && ! -f "$REPORT_ROOT/BR_quartet_restoration_transformation_brightness_evidence.tar.zst" ]]; then
  fail "Missing completed stage-76 transformation-brightness report"
fi

exec python3 -u "$TOOL" --project-root "$PROJECT_ROOT" "$@"
