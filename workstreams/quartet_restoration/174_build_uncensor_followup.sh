#!/usr/bin/env bash
set -Eeuo pipefail
PROJECT_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
source "$PROJECT_ROOT/.local/paths.sh"
exec python3 "$PROJECT_ROOT/workstreams/quartet_restoration/174_build_uncensor_followup.py" \
  --project-root "$PROJECT_ROOT" --game-root "$BR1_QUARTET_ROOT" "$@"
