#!/usr/bin/env bash
set -Eeuo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
exec python3 -u "$ROOT/workstreams/quartet_restoration/128_collect_coverage_selector_standalone_render_path_audit.py" \
  --project-root "$ROOT" \
  "$@"
