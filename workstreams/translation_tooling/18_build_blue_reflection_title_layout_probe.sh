#!/usr/bin/env bash
set -Eeuo pipefail

PROJECT_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
PATHS_FILE="$PROJECT_ROOT/.local/paths.sh"
TOOL="$PROJECT_ROOT/workstreams/translation_tooling/blue_reflection_title_layout_probe.py"
REPORT_ROOT="$PROJECT_ROOT/.local/reports/translation"
REPORT_JSON="$REPORT_ROOT/BR_BLUE_REFLECTION_TITLE_LAYOUT_PROBE_REPORT.json"
REPORT_PACKAGE="$REPORT_ROOT/BR_blue_reflection_title_layout_probe_report.tar.zst"

fail() { printf 'ERROR: %s\n' "$*" >&2; exit 1; }
for cmd in realpath python3 tar zstd; do command -v "$cmd" >/dev/null 2>&1 || fail "$cmd is required"; done
[[ -f "$PATHS_FILE" ]] || fail "Local path configuration is missing: $PATHS_FILE"
# shellcheck source=/dev/null
source "$PATHS_FILE"

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
[[ -f "$PROJECT_ROOT/.local/reports/translation/BR_TRANSLATION_PAK_REPACK_REPORT.json" ]] || \
  fail "Clean PAK report is missing. Run steps 07 and 08 first."
mkdir -p -- "$REPORT_ROOT"

"$PROJECT_ROOT/Blue_Reflection_Text_Tool/workstream_lock.sh" \
  "$PROJECT_ROOT" translation_tooling -- \
  python3 "$TOOL" --project-root "$PROJECT_ROOT" --gust-pak "$GUST_PAK_BIN"

[[ -f "$REPORT_JSON" ]] || fail "Probe report was not created: $REPORT_JSON"
rm -f -- "$REPORT_PACKAGE"
tar -C "$PROJECT_ROOT" --zstd -cf "$REPORT_PACKAGE" \
  workstreams/translation_tooling/VERSION \
  .local/reports/translation/BR_TRANSLATION_PAK_REPACK_REPORT.json \
  .local/reports/translation/BR_BLUE_REFLECTION_TITLE_LAYOUT_PROBE_REPORT.json

printf '\nProbe build is ready. Test and restore Original first, then Quartet.\n'
printf 'Interpretation:\n'
printf '  a17: small magenta logo upper-left + help strip lower-left\n'
printf '  a18: small cyan logo upper-right + A-button strip lower-right\n'
printf '  moved logo but no strip: layout active, cross-atlas binding absent\n'
printf '  unchanged: neither localized layout is active for that screen\n'
printf '\nUpload after both restores:\n  %s\n' "$REPORT_PACKAGE"
