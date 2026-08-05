#!/usr/bin/env bash
set -Eeuo pipefail

PROJECT_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
TOOL="$PROJECT_ROOT/workstreams/quartet_restoration/prepare_bathroom_river_parent_elixir_repack_test.py"

fail() {
  printf 'ERROR: %s\n' "$*" >&2
  exit 1
}

[[ -f "$TOOL" ]] || fail "Missing stage-70 builder: $TOOL"
[[ -d "$PROJECT_ROOT/.local/build/quartet_restoration/target" ]] || fail "Missing Quartet extraction workspace"
[[ -f "$PROJECT_ROOT/.local/reports/quartet_restoration/BR_quartet_restoration_bathroom_river_member_prototype_evidence.tar.zst" ]] \
  || fail "Missing stage-69 bathroom river member prototype report"

exec python3 -u "$TOOL" --project-root "$PROJECT_ROOT"
