#!/usr/bin/env bash
set -Eeuo pipefail

PROJECT_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PATHS_FILE="$PROJECT_ROOT/.local/paths.sh"
HELPER="$PROJECT_ROOT/Blue_Reflection_Text_Tool/extract_text_archives.sh"
REPORT_DIR="$PROJECT_ROOT/.local/reports"
REPORT_FILE="$REPORT_DIR/BR_text_sources_all_pc_targets.tar.zst"

die() {
  printf 'ERROR: %s\n' "$*" >&2
  exit 1
}

for cmd in realpath tar zstd find; do
  command -v "$cmd" >/dev/null 2>&1 || die "$cmd is required"
done

[[ -f "$PATHS_FILE" ]] || die "Missing local path configuration: $PATHS_FILE"
[[ -x "$HELPER" ]] || die "Extraction helper missing: $HELPER"

# shellcheck source=/dev/null
source "$PATHS_FILE"

for spec in \
  "BR1_ORIGINAL_ROOT:BLUE REFLECTION original" \
  "BR1_QUARTET_ROOT:BLUE REFLECTION Quartet" \
  "BR_SECOND_LIGHT_ROOT:BLUE REFLECTION Second Light"
do
  variable="${spec%%:*}"
  label="${spec#*:}"
  value="${!variable:-}"
  [[ -n "$value" ]] || die "$variable is empty ($label)"
  [[ -d "$value" ]] || die "$label directory not found: $value"
done

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
[[ -n "$GUST_PAK_BIN" ]] || die "gust_pak was not found"

"$HELPER" \
  "$GUST_PAK_BIN" "$PROJECT_ROOT" \
  blue_reflection_original "$BR1_ORIGINAL_ROOT" blue_reflection original DATA/PACK01.PAK \
  blue_reflection_original "$BR1_ORIGINAL_ROOT" blue_reflection original DATA/PACK02_1.PAK \
  blue_reflection_original "$BR1_ORIGINAL_ROOT" blue_reflection original DATA/PACK02_3.PAK \
  blue_reflection_quartet "$BR1_QUARTET_ROOT" blue_reflection quartet Data/PACK11.PAK \
  blue_reflection_quartet "$BR1_QUARTET_ROOT" blue_reflection quartet Data/PACK12.PAK \
  second_light_original "$BR_SECOND_LIGHT_ROOT" second_light original Data/PACK01.PAK \
  second_light_original "$BR_SECOND_LIGHT_ROOT" second_light original Data/PACK02.PAK

mkdir -p -- "$REPORT_DIR"
rm -f -- "$REPORT_FILE"

tar -C "$PROJECT_ROOT" --zstd -cf "$REPORT_FILE" \
  config/project_version \
  config/series_targets.tsv \
  config/text_source_archives.tsv \
  .local/reports/BR_text_extraction_summary.tsv \
  titles/blue_reflection/workspace/original/archives \
  titles/blue_reflection/workspace/quartet/archives \
  titles/second_light/workspace/original/archives

printf '\nCreated analysis package:\n  %s\n' "$REPORT_FILE"
printf 'It contains extracted text-source archives and PAK reconstruction manifests, not the source PAK files.\n'
printf 'Upload this package before running any later conversion/build step.\n'
