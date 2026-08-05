#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
exec python3 "$ROOT/workstreams/quartet_legacy_dlc/br_dlc_exact_closure_tool.py" validate-report --report-root "$ROOT/.local/reports/quartet_legacy_dlc/exact_closure_evidence"
