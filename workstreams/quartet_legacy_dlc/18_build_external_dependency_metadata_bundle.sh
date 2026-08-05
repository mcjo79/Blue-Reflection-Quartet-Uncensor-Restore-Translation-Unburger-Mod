#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
exec python3 "$ROOT/workstreams/quartet_legacy_dlc/br_dlc_external_closure_tool.py" bundle-report \
  --report-root "$ROOT/.local/reports/quartet_legacy_dlc/external_dependency_closure_evidence" \
  --output "$ROOT/.local/reports/quartet_legacy_dlc/BR_quartet_legacy_dlc_external_dependency_closure_evidence.tar.zst"
