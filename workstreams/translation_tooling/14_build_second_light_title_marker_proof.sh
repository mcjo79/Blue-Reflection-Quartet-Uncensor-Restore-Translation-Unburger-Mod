#!/usr/bin/env bash
set -Eeuo pipefail

PROJECT_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
PATHS_FILE="$PROJECT_ROOT/.local/paths.sh"
TOOL="$PROJECT_ROOT/workstreams/translation_tooling/second_light_title_marker_proof.py"
REPORT_ROOT="$PROJECT_ROOT/.local/reports/translation"
REPORT_JSON="$REPORT_ROOT/BR_SECOND_LIGHT_TITLE_MARKER_PROOF_REPORT.json"
REPORT_PACKAGE="$REPORT_ROOT/BR_second_light_title_marker_proof_report.tar.zst"

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

find_gust_tool() {
  local variable_name="$1"
  local executable_name="$2"
  local configured="${!variable_name:-}"
  local candidate
  if [[ -n "$configured" && -x "$configured" ]]; then
    realpath -- "$configured"
    return 0
  fi
  for candidate in \
    "$PROJECT_ROOT/.local/vendor/gust_tools/$executable_name" \
    "$HOME/Downloads/gust_tools/$executable_name"
  do
    if [[ -x "$candidate" ]]; then
      realpath -- "$candidate"
      return 0
    fi
  done
  if command -v "$executable_name" >/dev/null 2>&1; then
    command -v "$executable_name"
    return 0
  fi
  return 1
}

GUST_PAK_BIN="$(find_gust_tool GUST_PAK gust_pak || true)"
GUST_G1T_BIN="$(find_gust_tool GUST_G1T gust_g1t || true)"
[[ -n "$GUST_PAK_BIN" ]] || fail "gust_pak was not found"
[[ -n "$GUST_G1T_BIN" ]] || fail "gust_g1t was not found"
[[ -n "${BR_SECOND_LIGHT_ROOT:-}" ]] || fail "BR_SECOND_LIGHT_ROOT is missing from $PATHS_FILE"
[[ -d "$BR_SECOND_LIGHT_ROOT" ]] || fail "Second Light root does not exist: $BR_SECOND_LIGHT_ROOT"
[[ -f "$PROJECT_ROOT/.local/reports/translation/BR_TRANSLATION_PAK_REPACK_REPORT.json" ]] || \
  fail "Clean PAK report is missing. Run 07_build_translation_files.sh and 08_repack_translation_archives.sh first."

MARKER="${BR_TITLE_MARKER:-UNBURGER / UNCENSOR}"
case "${MARKER,,}" in
  ''|none|off|disabled) fail "BR_TITLE_MARKER must contain the proof label" ;;
esac

mkdir -p -- "$REPORT_ROOT"

"$PROJECT_ROOT/Blue_Reflection_Text_Tool/workstream_lock.sh" \
  "$PROJECT_ROOT" translation_tooling -- \
  python3 "$TOOL" \
    --project-root "$PROJECT_ROOT" \
    --game-root "$BR_SECOND_LIGHT_ROOT" \
    --gust-pak "$GUST_PAK_BIN" \
    --gust-g1t "$GUST_G1T_BIN" \
    --marker "$MARKER"

[[ -f "$REPORT_JSON" ]] || fail "Title-marker proof report was not created: $REPORT_JSON"

rm -f -- "$REPORT_PACKAGE"
tar -C "$PROJECT_ROOT" --zstd -cf "$REPORT_PACKAGE" \
  workstreams/translation_tooling/VERSION \
  workstreams/translation_tooling/STATUS.json \
  .local/reports/translation/BR_TRANSLATION_PAK_REPACK_REPORT.json \
  .local/reports/translation/BR_SECOND_LIGHT_TITLE_MARKER_PROOF_REPORT.json \
  .local/build/translation/title_marker_proof/UNBURGER_UNCENSOR_preview.png

printf '\nSynthetic title-marker proof was created only under:\n'
printf '  %s\n' "$PROJECT_ROOT/.local/build/translation"
printf 'No installed game file was modified.\n'
printf '\nPreview:\n  %s\n' \
  "$PROJECT_ROOT/.local/build/translation/title_marker_proof/UNBURGER_UNCENSOR_preview.png"
printf '\nNext test step:\n'
printf '  %q install second_light_original\n' \
  "$PROJECT_ROOT/workstreams/translation_tooling/09_test_translation_in_game.sh"
printf '\nUpload after restore:\n  %s\n' "$REPORT_PACKAGE"
