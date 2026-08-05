#!/usr/bin/env bash
set -euo pipefail
PROJECT_ROOT="${BR_PROJECT_ROOT:-$(cd -- "$SCRIPT_DIR/../.." && pwd)}"
REPORT_ROOT="$PROJECT_ROOT/.local/reports/quartet_legacy_dlc/bkn_dry_canonical_patch_proposal_evidence"
OUTPUT="$PROJECT_ROOT/.local/reports/quartet_legacy_dlc/BR_quartet_legacy_dlc_bkn_dry_canonical_patch_proposal_evidence.tar.zst"
exec python3 "$PROJECT_ROOT/workstreams/quartet_legacy_dlc/br_dlc_bkn_dry_canonical_patch_proposal_tool.py" bundle-report \
  --report-root "$REPORT_ROOT" \
  --output "$OUTPUT"
