#!/usr/bin/env bash
set -Eeuo pipefail

PROJECT_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
PATHS_FILE="$PROJECT_ROOT/.local/paths.sh"
TOOL="$PROJECT_ROOT/Blue_Reflection_Text_Tool/br_text_tool.py"
REPORT_ROOT="$PROJECT_ROOT/.local/reports/translation"
REPORT_JSON="$REPORT_ROOT/BR_TRANSLATION_PAK_REPACK_REPORT.json"
REPORT_PACKAGE="$REPORT_ROOT/BR_translation_pak_repack_report.tar.zst"

fail() {
  printf 'ERROR: %s\n' "$*" >&2
  exit 1
}

for cmd in realpath python3 tar zstd; do
  command -v "$cmd" >/dev/null 2>&1 || fail "$cmd is required"
done

[[ -f "$PATHS_FILE" ]] || fail "Local path configuration is missing: $PATHS_FILE"
# shellcheck source=/dev/null
source "$PATHS_FILE"

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
[[ -f "$PROJECT_ROOT/.local/build/translation/TRANSLATION_REPACK_PLAN.json" ]] || \
  fail "Loose build plan is missing. Run 07_build_translation_files.sh first."

mkdir -p -- "$REPORT_ROOT"

"$PROJECT_ROOT/Blue_Reflection_Text_Tool/workstream_lock.sh" \
  "$PROJECT_ROOT" translation_tooling -- \
  python3 "$TOOL" repack \
    --project-root "$PROJECT_ROOT" \
    --gust-pak "$GUST_PAK_BIN"

[[ -f "$REPORT_JSON" ]] || fail "PAK repack report was not created: $REPORT_JSON"

rm -f -- "$REPORT_PACKAGE"
tar -C "$PROJECT_ROOT" --zstd -cf "$REPORT_PACKAGE" \
  workstreams/translation_tooling/VERSION \
  workstreams/translation_tooling/STATUS.json \
  .local/reports/translation/BR_TRANSLATION_PAK_REPACK_REPORT.json \
  .local/build/translation/TRANSLATION_REPACK_PLAN.json

printf '\nDevelopment PAKs were created only under:\n'
printf '  %s\n' "$PROJECT_ROOT/.local/build/translation/archives"
printf 'No installed game file was modified.\n'
printf '\nUpload this report before any in-game installation wrapper is added:\n  %s\n' \
  "$REPORT_PACKAGE"
