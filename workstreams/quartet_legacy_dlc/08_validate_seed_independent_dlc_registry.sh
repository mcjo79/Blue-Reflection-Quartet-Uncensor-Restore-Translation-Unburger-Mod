#!/usr/bin/env bash
set -Eeuo pipefail
PROJECT_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
exec python3 "$PROJECT_ROOT/workstreams/quartet_legacy_dlc/br_dlc_technical_registry_tool.py" validate-report \
  --report-root "$PROJECT_ROOT/.local/reports/quartet_legacy_dlc/technical_registry_evidence"
