#!/usr/bin/env bash
set -euo pipefail
PROJECT_ROOT="${BR_PROJECT_ROOT:-$(cd -- "$SCRIPT_DIR/../.." && pwd)}"
REPORT_ROOT="$PROJECT_ROOT/.local/reports/quartet_legacy_dlc/bkn_pe_reference_evidence"
OUTPUT="$PROJECT_ROOT/.local/reports/quartet_legacy_dlc/BR_quartet_legacy_dlc_bkn_pe_reference_evidence.tar.zst"
python3 "$PROJECT_ROOT/workstreams/quartet_legacy_dlc/br_dlc_bkn_pe_reference_tool.py" \
  --project-root "$PROJECT_ROOT" \
  --output-dir "$REPORT_ROOT" \
  --validate-only
rm -f -- "$OUTPUT"
tar --zstd --sort=name --mtime=@0 --owner=0 --group=0 --numeric-owner \
  -cf "$OUTPUT" -C "$(dirname "$REPORT_ROOT")" "$(basename "$REPORT_ROOT")"
printf 'Report: %s\n' "$OUTPUT"
