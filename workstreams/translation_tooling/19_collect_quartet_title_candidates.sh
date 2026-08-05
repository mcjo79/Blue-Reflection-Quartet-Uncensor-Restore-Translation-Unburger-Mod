#!/usr/bin/env bash
set -Eeuo pipefail
PROJECT_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
PATHS_FILE="$PROJECT_ROOT/.local/paths.sh"
TOOL="$PROJECT_ROOT/workstreams/translation_tooling/quartet_title_candidate_collector.py"
REPORT_DIR="$PROJECT_ROOT/.local/reports/translation/quartet_title_candidates"
REPORT_PACKAGE="$PROJECT_ROOT/.local/reports/translation/BR_quartet_title_candidate_report.tar.zst"
fail() { printf 'ERROR: %s\n' "$*" >&2; exit 1; }
for cmd in realpath python3 tar zstd; do command -v "$cmd" >/dev/null 2>&1 || fail "$cmd is required"; done
[[ -f "$PATHS_FILE" ]] || fail "Missing local path configuration: $PATHS_FILE"
# shellcheck source=/dev/null
source "$PATHS_FILE"
[[ -n "${BR1_QUARTET_ROOT:-}" && -d "$BR1_QUARTET_ROOT" ]] || fail "BR1_QUARTET_ROOT is missing or invalid"
find_gust_pak() {
  local candidate configured="${GUST_PAK:-}"
  if [[ -n "$configured" && -x "$configured" ]]; then realpath -- "$configured"; return 0; fi
  for candidate in "$PROJECT_ROOT/.local/vendor/gust_tools/gust_pak" "$HOME/Downloads/gust_tools/gust_pak"; do
    if [[ -x "$candidate" ]]; then realpath -- "$candidate"; return 0; fi
  done
  command -v gust_pak 2>/dev/null || return 1
}
GUST_PAK_BIN="$(find_gust_pak || true)"
[[ -n "$GUST_PAK_BIN" ]] || fail "gust_pak was not found"
rm -rf -- "$REPORT_DIR"
"$PROJECT_ROOT/Blue_Reflection_Text_Tool/workstream_lock.sh" \
  "$PROJECT_ROOT" translation_tooling -- \
  python3 "$TOOL" --project-root "$PROJECT_ROOT" --quartet-root "$BR1_QUARTET_ROOT" --gust-pak "$GUST_PAK_BIN"
[[ -f "$REPORT_DIR/BR_QUARTET_TITLE_CANDIDATE_REPORT.json" ]] || fail "Candidate report was not created"
rm -f -- "$REPORT_PACKAGE"
tar -C "$PROJECT_ROOT" --zstd -cf "$REPORT_PACKAGE" \
  .local/reports/translation/quartet_title_candidates
printf '\nUpload:\n  %s\n' "$REPORT_PACKAGE"
