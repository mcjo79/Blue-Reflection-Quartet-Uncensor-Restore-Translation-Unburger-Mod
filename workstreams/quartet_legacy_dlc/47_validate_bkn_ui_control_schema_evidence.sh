#!/usr/bin/env bash
set -euo pipefail
PROJECT_ROOT="${BR_PROJECT_ROOT:-$(cd -- "$SCRIPT_DIR/../.." && pwd)}"
REPORT_ROOT="$PROJECT_ROOT/.local/reports/quartet_legacy_dlc/bkn_ui_control_schema_evidence"
exec python3 "$PROJECT_ROOT/workstreams/quartet_legacy_dlc/br_dlc_bkn_ui_control_schema_tool.py" validate-report --report-root "$REPORT_ROOT"
