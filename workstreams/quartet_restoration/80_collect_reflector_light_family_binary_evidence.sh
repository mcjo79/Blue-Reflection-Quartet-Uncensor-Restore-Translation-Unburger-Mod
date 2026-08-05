#!/usr/bin/env bash
set -euo pipefail
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
export PYTHONUNBUFFERED=1
exec "${PYTHON:-python3}" -u "$PROJECT_ROOT/workstreams/quartet_restoration/collect_reflector_light_family_binary_evidence.py" --project-root "$PROJECT_ROOT"
