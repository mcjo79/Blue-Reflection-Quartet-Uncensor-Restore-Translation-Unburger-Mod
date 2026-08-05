#!/usr/bin/env bash
set -Eeuo pipefail
PROJECT_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
TOOL="$PROJECT_ROOT/Blue_Reflection_Text_Tool/br_dlc_tool.py"
REPORT_ROOT="$PROJECT_ROOT/.local/reports/quartet_legacy_dlc/inventory_evidence"
exec python3 "$TOOL" validate-report --report-root "$REPORT_ROOT"
