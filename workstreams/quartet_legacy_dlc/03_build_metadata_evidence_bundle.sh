#!/usr/bin/env bash
set -Eeuo pipefail
PROJECT_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
TOOL="$PROJECT_ROOT/Blue_Reflection_Text_Tool/br_dlc_tool.py"
REPORT_ROOT="$PROJECT_ROOT/.local/reports/quartet_legacy_dlc/inventory_evidence"
OUTPUT="$PROJECT_ROOT/.local/reports/quartet_legacy_dlc/BR_quartet_legacy_dlc_inventory_evidence.tar.zst"
exec python3 "$TOOL" bundle-report --report-root "$REPORT_ROOT" --output "$OUTPUT"
