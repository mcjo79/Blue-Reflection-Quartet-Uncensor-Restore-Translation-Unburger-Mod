#!/usr/bin/env bash
set -Eeuo pipefail

PROJECT_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
PATHS_FILE="$PROJECT_ROOT/.local/paths.sh"
TOOL="$PROJECT_ROOT/workstreams/translation_tooling/quartet_b0_title_texture_probe.py"
REPORT_ROOT="$PROJECT_ROOT/.local/reports/translation"
REPORT_JSON="$REPORT_ROOT/BR_QUARTET_B0_TITLE_TEXTURE_PROBE_REPORT.json"
REPORT_PACKAGE="$REPORT_ROOT/BR_quartet_b0_title_texture_probe_report.tar.zst"

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
[[ -f "$PROJECT_ROOT/.local/reports/translation/BR_TRANSLATION_PAK_REPACK_REPORT.json" ]] || fail "Run steps 07 and 08 first"
mkdir -p "$REPORT_ROOT"

"$PROJECT_ROOT/Blue_Reflection_Text_Tool/workstream_lock.sh" "$PROJECT_ROOT" translation_tooling -- \
  python3 "$TOOL" \
    --project-root "$PROJECT_ROOT" \
    --quartet-root "$BR1_QUARTET_ROOT" \
    --gust-pak "$GUST_PAK_BIN" \
    --gust-g1t "$GUST_G1T_BIN"

[[ -f "$REPORT_JSON" ]] || fail "Probe report missing: $REPORT_JSON"
rm -f "$REPORT_PACKAGE"
tar -C "$PROJECT_ROOT" --zstd -cf "$REPORT_PACKAGE" \
  workstreams/translation_tooling/VERSION \
  .local/reports/translation/BR_TRANSLATION_PAK_REPACK_REPORT.json \
  .local/reports/translation/BR_QUARTET_B0_TITLE_TEXTURE_PROBE_REPORT.json

printf '\nQuartet b0_title texture-index probe built.\n'
printf 'Only data/b4/x64/res_en/ui/b0_title.g1t was modified:\n'
printf '  red   = 000.dds (1152x1600)\n'
printf '  green = 001.dds (672x152)\n'
printf '  blue  = 002.dds (1760x100)\n'
printf 'Install only blue_reflection_quartet with step 09, take a screenshot, then restore it.\n'
printf 'Upload after restore:\n  %s\n' "$REPORT_PACKAGE"
