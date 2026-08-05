#!/usr/bin/env bash
set -Eeuo pipefail

PROJECT_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
PATHS_FILE="$PROJECT_ROOT/.local/paths.sh"
TOOL="$PROJECT_ROOT/workstreams/translation_tooling/quartet_title_marker.py"
REPORT_ROOT="$PROJECT_ROOT/.local/reports/translation"
REPORT_JSON="$REPORT_ROOT/BR_QUARTET_TITLE_MARKER_REPORT.json"
REPORT_PACKAGE="$REPORT_ROOT/BR_quartet_title_marker_report.tar.zst"
VARIANT="${BR_QUARTET_TITLE_VARIANT:-combined}"

fail() { printf 'ERROR: %s\n' "$*" >&2; exit 1; }
for cmd in realpath python3 tar zstd; do
  command -v "$cmd" >/dev/null 2>&1 || fail "$cmd is required"
done
[[ -f "$PATHS_FILE" ]] || fail "Local path configuration missing: $PATHS_FILE"
# shellcheck source=/dev/null
source "$PATHS_FILE"

find_tool() {
  local var="$1"
  local exe="$2"
  local configured="${!var-}"
  local candidate
  if [[ -n "$configured" && -x "$configured" ]]; then
    realpath -- "$configured"
    return
  fi
  for candidate in \
    "$PROJECT_ROOT/.local/vendor/gust_tools/$exe" \
    "$HOME/Downloads/gust_tools/$exe"
  do
    if [[ -x "$candidate" ]]; then
      realpath -- "$candidate"
      return
    fi
  done
  command -v "$exe" 2>/dev/null || return 1
}

GUST_PAK_BIN="$(find_tool GUST_PAK gust_pak || true)"
GUST_G1T_BIN="$(find_tool GUST_G1T gust_g1t || true)"
[[ -n "$GUST_PAK_BIN" ]] || fail "gust_pak not found"
[[ -n "$GUST_G1T_BIN" ]] || fail "gust_g1t not found"
[[ -n "${BR1_QUARTET_ROOT:-}" && -d "$BR1_QUARTET_ROOT" ]] || fail "BR1_QUARTET_ROOT invalid"
[[ -f "$PROJECT_ROOT/.local/reports/translation/BR_TRANSLATION_PAK_REPACK_REPORT.json" ]] || fail "Run clean steps 07 and 08 first"
mkdir -p "$REPORT_ROOT"

case "$VARIANT" in
  unburger|uncensor|combined) ;;
  *) fail "BR_QUARTET_TITLE_VARIANT must be unburger, uncensor, or combined" ;;
esac

"$PROJECT_ROOT/Blue_Reflection_Text_Tool/workstream_lock.sh" "$PROJECT_ROOT" translation_tooling -- \
  python3 "$TOOL" \
    --project-root "$PROJECT_ROOT" \
    --quartet-root "$BR1_QUARTET_ROOT" \
    --gust-pak "$GUST_PAK_BIN" \
    --gust-g1t "$GUST_G1T_BIN" \
    --variant "$VARIANT"

[[ -f "$REPORT_JSON" ]] || fail "Marker report missing: $REPORT_JSON"
rm -f "$REPORT_PACKAGE"
tar -C "$PROJECT_ROOT" --zstd -cf "$REPORT_PACKAGE" \
  workstreams/translation_tooling/VERSION \
  workstreams/translation/VERSION \
  workstreams/quartet_restoration/VERSION \
  .local/reports/translation/BR_TRANSLATION_PAK_REPACK_REPORT.json \
  .local/reports/translation/BR_QUARTET_TITLE_MARKER_REPORT.json \
  .local/build/translation/quartet_title_marker/QUARTET_TITLE_MARKER_preview.png

printf '\nQuartet production title marker built.\n'
printf 'Variant: %s\n' "$VARIANT"
printf 'Version sources are read directly from translation and quartet_restoration VERSION files.\n'
printf 'Production marker is runtime-approved; use step 09 only for an explicit regression test.\n'
printf 'Optional regression report after restore:\n  %s\n' "$REPORT_PACKAGE"
