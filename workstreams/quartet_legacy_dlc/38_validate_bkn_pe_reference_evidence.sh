#!/usr/bin/env bash
set -euo pipefail
PROJECT_ROOT="${BR_PROJECT_ROOT:-$(cd -- "$SCRIPT_DIR/../.." && pwd)}"
REPORT_ROOT="$PROJECT_ROOT/.local/reports/quartet_legacy_dlc/bkn_pe_reference_evidence"
exec python3 "$PROJECT_ROOT/workstreams/quartet_legacy_dlc/br_dlc_bkn_pe_reference_tool.py" \
  --project-root "$PROJECT_ROOT" \
  --output-dir "$REPORT_ROOT" \
  --validate-only
