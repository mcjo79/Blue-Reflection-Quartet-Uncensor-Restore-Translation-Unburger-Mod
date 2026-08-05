#!/usr/bin/env bash
set -Eeuo pipefail

PROJECT_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
PATHS="$PROJECT_ROOT/.local/paths.sh"
HELPER="$PROJECT_ROOT/Blue_Reflection_Text_Tool/extract_text_archives.sh"
TOOL="$PROJECT_ROOT/Blue_Reflection_Text_Tool/br_text_tool.py"
SYNC="$PROJECT_ROOT/workstreams/translation_tooling/quartet_translation_source_sync.py"
LOCK="$PROJECT_ROOT/Blue_Reflection_Text_Tool/workstream_lock.sh"

[[ "${1:-}" == "--apply" ]] || {
  echo 'ERROR: this correction writes canonical translation databases; rerun with --apply' >&2
  exit 2
}
[[ -f "$PATHS" ]] || { echo "ERROR: missing $PATHS" >&2; exit 1; }
# shellcheck source=/dev/null
source "$PATHS"
[[ -n "${BR1_QUARTET_ROOT:-}" && -d "$BR1_QUARTET_ROOT" ]] || {
  echo 'ERROR: BR1_QUARTET_ROOT is missing' >&2
  exit 1
}

find_gust() {
  local candidate
  for candidate in \
    "${GUST_PAK:-}" \
    "$PROJECT_ROOT/.local/vendor/gust_tools/gust_pak" \
    "$HOME/Downloads/gust_tools/gust_pak"; do
    [[ -n "$candidate" && -x "$candidate" ]] && { realpath "$candidate"; return; }
  done
  command -v gust_pak 2>/dev/null || return 1
}
GUST="$(find_gust)" || { echo 'ERROR: gust_pak not found' >&2; exit 1; }

STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
TMP="$(mktemp -d "$PROJECT_ROOT/.local/.quartet-partition-correction.XXXXXX")"
BACKUP="$PROJECT_ROOT/.local/backups/translation_partition_correction/$STAMP.tar.zst"
OUT="$HOME/Downloads/Blue_Reflection_translation_quartet_partition_correction_$STAMP"
mkdir -p "$(dirname "$BACKUP")" "$OUT"
BEFORE="$TMP/before.json"

# This preflight verifies the known wrong state and refuses to discard any
# authored content from the false Second Light extensions or b4-backed RAY tree.
python3 "$SYNC" snapshot \
  --project-root "$PROJECT_ROOT" \
  --output "$BEFORE"

BACKUP_PATHS=(
  titles/blue_reflection/translation
  titles/second_light/translation
  titles/blue_reflection_sun/translation
  titles/blue_reflection_ray/translation
  workstreams/translation
)
tar -C "$PROJECT_ROOT" --zstd -cf "$BACKUP" "${BACKUP_PATHS[@]}"

restore() {
  echo 'Correction failed; restoring canonical Translation state from the local backup.' >&2
  rm -rf \
    "$PROJECT_ROOT/titles/blue_reflection/translation" \
    "$PROJECT_ROOT/titles/second_light/translation" \
    "$PROJECT_ROOT/titles/blue_reflection_sun/translation" \
    "$PROJECT_ROOT/titles/blue_reflection_ray/translation" \
    "$PROJECT_ROOT/workstreams/translation"
  tar -C "$PROJECT_ROOT" --zstd -xf "$BACKUP"
}
trap 'rc=$?; if (( rc != 0 )); then restore; fi; rm -rf "$TMP"; exit $rc' EXIT

# Remove only generated canonical output known to have been sourced from the
# wrong game partition. Existing standalone Second Light units remain in place
# so br_text_tool can preserve every authored en/notes/status value by logical_id.
rm -rf \
  "$PROJECT_ROOT/titles/second_light/translation/events_quartet_extensions" \
  "$PROJECT_ROOT/titles/second_light/translation/system_quartet_extensions" \
  "$PROJECT_ROOT/titles/blue_reflection_ray/translation"

"$HELPER" "$GUST" "$PROJECT_ROOT" \
  second_light_quartet "$BR1_QUARTET_ROOT" second_light quartet Data/PACK01_03.PAK \
  second_light_quartet "$BR1_QUARTET_ROOT" second_light quartet Data/PACK02_03.PAK \
  blue_reflection_ray_quartet "$BR1_QUARTET_ROOT" blue_reflection_ray quartet Data/PACK01_01.PAK \
  blue_reflection_ray_quartet "$BR1_QUARTET_ROOT" blue_reflection_ray quartet Data/PACK02_01.PAK

"$LOCK" "$PROJECT_ROOT" translation -- \
  python3 "$TOOL" export \
    --project-root "$PROJECT_ROOT" \
    --project second_light \
    --project blue_reflection_ray

python3 "$SYNC" finalize \
  --project-root "$PROJECT_ROOT" \
  --before "$BEFORE" \
  --output-dir "$OUT"

VERSION="$(cat "$PROJECT_ROOT/workstreams/translation/VERSION")"
BUNDLE="$HOME/Downloads/Blue_Reflection_translation_chat_partition_correction_${VERSION}_$STAMP.tar.zst"
tar --zstd -cf "$BUNDLE" \
  -C "$PROJECT_ROOT" \
  workstreams/translation \
  titles/blue_reflection/translation \
  titles/second_light/translation \
  titles/blue_reflection_sun/translation \
  titles/blue_reflection_ray/translation \
  .local/reports/BR_TRANSLATION_EXPORT_REPORT.json \
  .local/reports/BR_ALIGNMENT_EXCEPTIONS.json \
  .local/reports/translation/BR_QUARTET_TRANSLATION_PARTITION_CORRECTION.json \
  -C "$OUT" .
sha256sum "$BUNDLE" > "$BUNDLE.sha256"

trap - EXIT
rm -rf "$TMP"
printf '\nQuartet game partition correction completed.\nTranslation version: %s\nBackup: %s\nHandoff bundle: %s\nSHA-256: %s\n' \
  "$VERSION" "$BACKUP" "$BUNDLE" "$BUNDLE.sha256"
