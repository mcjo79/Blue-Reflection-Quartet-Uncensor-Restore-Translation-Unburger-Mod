#!/usr/bin/env bash
set -Eeuo pipefail
PROJECT_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPORT_DIR="$PROJECT_ROOT/.local/reports/core"
REPORT="$REPORT_DIR/BR_PARALLEL_WORKSTREAM_VALIDATION.json"
mkdir -p -- "$REPORT_DIR"
python3 "$PROJECT_ROOT/Blue_Reflection_Text_Tool/workstream_guard.py" \
  --project-root "$PROJECT_ROOT" \
  --output "$REPORT"
printf '\nTranslation and restoration packages may now be applied in either order.\n'
printf 'Report: %s\n' "$REPORT"
