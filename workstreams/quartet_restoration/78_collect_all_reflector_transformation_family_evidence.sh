#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
PYTHON_BIN="${PYTHON:-python3}"

export PYTHONUNBUFFERED=1

exec "$PYTHON_BIN" -u \
  "$PROJECT_ROOT/workstreams/quartet_restoration/collect_all_reflector_transformation_family_evidence.py" \
  --project-root "$PROJECT_ROOT"
