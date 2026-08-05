#!/usr/bin/env bash
set -Eeuo pipefail

PROJECT_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
TOOL="$PROJECT_ROOT/workstreams/quartet_restoration/collect_bathroom_sibling_descriptor_comparison_evidence.py"

fail() {
  printf 'ERROR: %s\n' "$*" >&2
  exit 1
}

[[ -f "$TOOL" ]] || fail "Missing stage-67 collector: $TOOL"
[[ -d "$PROJECT_ROOT/.local/build/quartet_restoration/source" ]] || fail "Missing Original extraction workspace"
[[ -d "$PROJECT_ROOT/.local/build/quartet_restoration/target" ]] || fail "Missing Quartet extraction workspace"

exec python3 -u "$TOOL" --project-root "$PROJECT_ROOT"
