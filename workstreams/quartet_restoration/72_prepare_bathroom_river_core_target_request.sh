#!/usr/bin/env bash
set -Eeuo pipefail

PROJECT_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
TOOL="$PROJECT_ROOT/workstreams/quartet_restoration/prepare_bathroom_river_core_target_request.py"
REPORT="$PROJECT_ROOT/.local/reports/quartet_restoration/BR_quartet_restoration_bathroom_river_containing_pak_repack_test_evidence.tar.zst"

fail() {
  printf 'ERROR: %s\n' "$*" >&2
  exit 1
}

[[ -f "$TOOL" ]] || fail "Missing stage-72 tool: $TOOL"
[[ -f "$REPORT" ]] || fail "Missing stage-71 containing-PAK report: $REPORT"

exec python3 -u "$TOOL" --project-root "$PROJECT_ROOT" "$@"
