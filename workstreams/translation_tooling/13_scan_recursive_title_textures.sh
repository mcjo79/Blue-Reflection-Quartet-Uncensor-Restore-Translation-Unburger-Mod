#!/usr/bin/env bash
set -Eeuo pipefail

PROJECT_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
PATHS_FILE="$PROJECT_ROOT/.local/paths.sh"
TOOL="$PROJECT_ROOT/workstreams/translation_tooling/recursive_title_g1t_scan.py"
VENDOR_DIR="$PROJECT_ROOT/.local/vendor/gust_tools"
REPORT_ROOT="$PROJECT_ROOT/.local/reports/translation"
OUTPUT_ROOT="$REPORT_ROOT/recursive_title_g1t_scan"
PACKAGE="$REPORT_ROOT/BR_recursive_title_g1t_scan_report.tar.zst"

fail() {
  printf 'ERROR: %s\n' "$*" >&2
  exit 1
}

find_tool() {
  local name="$1"
  local explicit="${2:-}"
  local candidate
  if [[ -n "$explicit" && -x "$explicit" ]]; then
    printf '%s\n' "$explicit"
    return 0
  fi
  for candidate in "$VENDOR_DIR/$name" "$HOME/Downloads/gust_tools/$name"; do
    [[ -x "$candidate" ]] && { printf '%s\n' "$candidate"; return 0; }
  done
  command -v "$name" 2>/dev/null || return 1
}

build_vendor_tool() {
  local name="$1"
  [[ -f "$VENDOR_DIR/Makefile" ]] || fail "Missing gust_tools source tree: $VENDOR_DIR"
  printf 'Building %s...\n' "$name" >&2
  make -C "$VENDOR_DIR" "$name" >&2
  [[ -x "$VENDOR_DIR/$name" ]] || fail "$name build failed: $VENDOR_DIR/$name"
  printf '%s\n' "$VENDOR_DIR/$name"
}

for command in python3 tar zstd make cc; do
  command -v "$command" >/dev/null 2>&1 || fail "$command is required"
done
[[ -f "$PATHS_FILE" ]] || fail "Missing local path configuration: $PATHS_FILE"
[[ -x "$TOOL" ]] || fail "Missing executable scanner: $TOOL"
# shellcheck source=/dev/null
source "$PATHS_FILE"

ORIGINAL_ROOT="${BR1_ORIGINAL_ROOT:-}"
QUARTET_ROOT="${BR1_QUARTET_ROOT:-}"
[[ -n "$ORIGINAL_ROOT" && -d "$ORIGINAL_ROOT" ]] || fail "Invalid BR1_ORIGINAL_ROOT: $ORIGINAL_ROOT"
[[ -n "$QUARTET_ROOT" && -d "$QUARTET_ROOT" ]] || fail "Invalid BR1_QUARTET_ROOT: $QUARTET_ROOT"

PAK_EXPLICIT="${GUST_PAK_BIN:-${GUST_PAK:-}}"
G1T_EXPLICIT="${GUST_G1T_BIN:-${GUST_G1T:-}}"
GUST_PAK_PATH="$(find_tool gust_pak "$PAK_EXPLICIT" || true)"
[[ -n "$GUST_PAK_PATH" ]] || GUST_PAK_PATH="$(build_vendor_tool gust_pak)"
GUST_G1T_PATH="$(find_tool gust_g1t "$G1T_EXPLICIT" || true)"
[[ -n "$GUST_G1T_PATH" ]] || GUST_G1T_PATH="$(build_vendor_tool gust_g1t)"

rm -rf -- "$OUTPUT_ROOT"
mkdir -p -- "$REPORT_ROOT"

printf 'This step temporarily extracts focused UI/resource PAKs one at a time.\n'
printf 'Installed game files remain read-only. Temporary trees are removed.\n\n'

"$PROJECT_ROOT/Blue_Reflection_Text_Tool/workstream_lock.sh" \
  "$PROJECT_ROOT" translation_tooling -- \
  python3 "$TOOL" \
    --project-root "$PROJECT_ROOT" \
    --original-root "$ORIGINAL_ROOT" \
    --quartet-root "$QUARTET_ROOT" \
    --gust-pak "$GUST_PAK_PATH" \
    --gust-g1t "$GUST_G1T_PATH" \
    --output-root "$OUTPUT_ROOT" \
    --max-depth 2

[[ -f "$OUTPUT_ROOT/BR_RECURSIVE_TITLE_G1T_SCAN_REPORT.json" ]] || fail "Recursive scan report was not created"
rm -f -- "$PACKAGE"
tar -C "$PROJECT_ROOT" --zstd -cf "$PACKAGE" \
  .local/reports/translation/recursive_title_g1t_scan

printf '\nUpload this package:\n  %s\n' "$PACKAGE"
