#!/usr/bin/env bash
set -Eeuo pipefail
PROJECT_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
REPORT_ROOT="$PROJECT_ROOT/.local/reports/quartet_legacy_dlc/nonscenario_inventory_evidence"
OUTPUT="$PROJECT_ROOT/.local/reports/quartet_legacy_dlc/BR_quartet_legacy_dlc_nonscenario_inventory_evidence.tar.zst"
exec python3 "$PROJECT_ROOT/workstreams/quartet_legacy_dlc/br_dlc_nonscenario_tool.py" bundle-report \
  --report-root "$REPORT_ROOT" --output "$OUTPUT"
