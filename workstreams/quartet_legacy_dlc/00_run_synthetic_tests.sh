#!/usr/bin/env bash
set -Eeuo pipefail
PROJECT_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
exec python3 -m unittest discover \
  -s "$PROJECT_ROOT/workstreams/quartet_legacy_dlc/tests" \
  -p 'test_*.py' -v
