#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
exec python3 "$ROOT/workstreams/quartet_legacy_dlc/br_dlc_nested_container_tool.py" validate-report \
  --report-root "$ROOT/.local/reports/quartet_legacy_dlc/nested_container_evidence"
