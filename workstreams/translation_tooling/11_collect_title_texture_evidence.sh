#!/usr/bin/env bash
set -Eeuo pipefail

PROJECT_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
PATHS_FILE="$PROJECT_ROOT/.local/paths.sh"
COLLECTOR="$PROJECT_ROOT/workstreams/translation_tooling/title_texture_evidence.py"
REPORT_ROOT="$PROJECT_ROOT/.local/reports/translation"
EVIDENCE_DIR="$REPORT_ROOT/title_texture_evidence"
REPORT_PACKAGE="$REPORT_ROOT/BR_title_texture_evidence.tar.zst"
VENDOR_DIR="$PROJECT_ROOT/.local/vendor/gust_tools"

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
  for candidate in \
    "$VENDOR_DIR/$name" \
    "$HOME/Downloads/gust_tools/$name"
  do
    [[ -x "$candidate" ]] && { printf '%s\n' "$candidate"; return 0; }
  done
  command -v "$name" 2>/dev/null || return 1
}

build_vendor_tool() {
  local name="$1"
  [[ -f "$VENDOR_DIR/Makefile" ]] || \
    fail "$name was not found and gust_tools source is missing: $VENDOR_DIR"
  printf 'Building %s from the local gust_tools source...\n' "$name" >&2
  make -C "$VENDOR_DIR" "$name" >&2
  [[ -x "$VENDOR_DIR/$name" ]] || fail "$name build failed: $VENDOR_DIR/$name"
  printf '%s\n' "$VENDOR_DIR/$name"
}

for command in python3 tar zstd make; do
  command -v "$command" >/dev/null 2>&1 || fail "$command is required"
done
[[ -f "$PATHS_FILE" ]] || fail "Missing local path configuration: $PATHS_FILE"
[[ -x "$COLLECTOR" ]] || fail "Missing evidence collector: $COLLECTOR"
# shellcheck source=/dev/null
source "$PATHS_FILE"

for variable in BR1_ORIGINAL_ROOT BR1_QUARTET_ROOT BR_SECOND_LIGHT_ROOT; do
  [[ -n "${!variable:-}" && -d "${!variable}" ]] || \
    fail "Invalid or missing $variable in $PATHS_FILE"
done

PAK_EXPLICIT="${GUST_PAK_BIN:-${GUST_PAK:-}}"
G1T_EXPLICIT="${GUST_G1T_BIN:-${GUST_G1T:-}}"
GUST_PAK_PATH="$(find_tool gust_pak "$PAK_EXPLICIT" || true)"
[[ -n "$GUST_PAK_PATH" ]] || GUST_PAK_PATH="$(build_vendor_tool gust_pak)"
GUST_G1T_PATH="$(find_tool gust_g1t "$G1T_EXPLICIT" || true)"
[[ -n "$GUST_G1T_PATH" ]] || GUST_G1T_PATH="$(build_vendor_tool gust_g1t)"

mkdir -p -- "$REPORT_ROOT"
rm -rf -- "$EVIDENCE_DIR"
rm -f -- "$REPORT_PACKAGE"

"$PROJECT_ROOT/Blue_Reflection_Text_Tool/workstream_lock.sh" \
  "$PROJECT_ROOT" translation_tooling -- \
  python3 "$COLLECTOR" \
    --project-root "$PROJECT_ROOT" \
    --original-root "$BR1_ORIGINAL_ROOT" \
    --quartet-root "$BR1_QUARTET_ROOT" \
    --second-light-root "$BR_SECOND_LIGHT_ROOT" \
    --gust-pak "$GUST_PAK_PATH" \
    --gust-g1t "$GUST_G1T_PATH" \
    --output-root "$EVIDENCE_DIR"

tar -C "$PROJECT_ROOT" --zstd -cf "$REPORT_PACKAGE" \
  .local/reports/translation/title_texture_evidence

printf '\nNo installed game file was modified.\n'
printf 'Upload this package:\n  %s\n' "$REPORT_PACKAGE"
