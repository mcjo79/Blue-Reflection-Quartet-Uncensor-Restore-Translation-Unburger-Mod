#!/usr/bin/env bash
set -Eeuo pipefail

PROJECT_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
PATHS_FILE="$PROJECT_ROOT/.local/paths.sh"
TOOL="$PROJECT_ROOT/workstreams/quartet_restoration/prepare_bathroom_river_containing_pak_repack_test.py"

fail() {
  printf 'ERROR: %s\n' "$*" >&2
  exit 1
}

[[ -f "$PATHS_FILE" ]] || fail "Missing local path configuration: $PATHS_FILE"
[[ -f "$TOOL" ]] || fail "Missing stage-71 builder: $TOOL"
[[ -f "$PROJECT_ROOT/.local/reports/quartet_restoration/BR_quartet_restoration_bathroom_river_parent_elixir_repack_test_evidence.tar.zst" ]] \
  || fail "Missing stage-70 bathroom river parent-Elixir repack report"

# shellcheck source=/dev/null
source "$PATHS_FILE"
[[ -n "${BR1_QUARTET_ROOT:-}" ]] || fail "BR1_QUARTET_ROOT is empty"
[[ -d "$BR1_QUARTET_ROOT" ]] || fail "Quartet game root not found: $BR1_QUARTET_ROOT"

find_gust_pak() {
  local candidate
  if [[ -n "${GUST_PAK:-}" && -x "$GUST_PAK" ]]; then
    realpath -- "$GUST_PAK"
    return 0
  fi
  for candidate in \
    "$PROJECT_ROOT/.local/vendor/gust_tools/gust_pak" \
    "$HOME/Downloads/gust_tools/gust_pak"
  do
    if [[ -x "$candidate" ]]; then
      realpath -- "$candidate"
      return 0
    fi
  done
  if command -v gust_pak >/dev/null 2>&1; then
    command -v gust_pak
    return 0
  fi
  return 1
}

GUST_PAK_BIN="$(find_gust_pak || true)"
[[ -n "$GUST_PAK_BIN" ]] || fail "gust_pak was not found"

exec python3 -u "$TOOL" \
  --project-root "$PROJECT_ROOT" \
  --quartet-root "$BR1_QUARTET_ROOT" \
  --gust-pak "$GUST_PAK_BIN" \
  "$@"
