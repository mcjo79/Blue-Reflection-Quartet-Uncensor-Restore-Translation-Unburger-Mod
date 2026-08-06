#!/usr/bin/env bash
set -Eeuo pipefail
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
PROJECT_ROOT="$(cd -- "$SCRIPT_DIR/../.." && pwd -P)"
exec python3 "$SCRIPT_DIR/145_collect_gamma_runtime_observation_glowlight_readiness_evidence.py" \
  --project-root "$PROJECT_ROOT" "$@"
