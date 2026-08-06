#!/usr/bin/env bash
set -Eeuo pipefail
PROJECT_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd -P)"
exec python3 "$PROJECT_ROOT/workstreams/quartet_restoration/138_integrate_runtime_validation_core_return.py" \
  --project-root "$PROJECT_ROOT" "$@"
