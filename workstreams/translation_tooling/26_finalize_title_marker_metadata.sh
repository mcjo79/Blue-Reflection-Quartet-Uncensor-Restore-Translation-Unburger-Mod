#!/usr/bin/env bash
set -Eeuo pipefail
PROJECT_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
exec python3 \
  "$PROJECT_ROOT/workstreams/translation_tooling/title_marker_metadata_finalize.py" \
  --project-root "$PROJECT_ROOT"
