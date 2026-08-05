#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
exec python3 "$ROOT/workstreams/quartet_legacy_dlc/br_dlc_bounded_family_tool.py" validate-report \
  --report-root "$ROOT/.local/reports/quartet_legacy_dlc/bounded_family_evidence"
