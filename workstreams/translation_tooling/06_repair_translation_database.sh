#!/usr/bin/env bash
set -Eeuo pipefail

PROJECT_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
TOOL="$PROJECT_ROOT/Blue_Reflection_Text_Tool/br_text_tool.py"
REPORT_ROOT="$PROJECT_ROOT/.local/reports/translation"
REPORT_JSON="$REPORT_ROOT/BR_EBM_LAYOUT_REPAIR_REPORT.json"
REPORT_PACKAGE="$REPORT_ROOT/BR_translation_ebm_layout_repair_report.tar.zst"
BACKUP_ROOT="$PROJECT_ROOT/.local/backups/translation_database"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
BACKUP_PACKAGE="$BACKUP_ROOT/before_active_english_target_refresh_$STAMP.tar.zst"

fail() { printf 'ERROR: %s\n' "$*" >&2; exit 1; }
for cmd in python3 tar zstd date; do command -v "$cmd" >/dev/null 2>&1 || fail "$cmd is required"; done
[[ -f "$TOOL" ]] || fail "Translation tool is missing: $TOOL"
[[ -f "$PROJECT_ROOT/titles/blue_reflection/translation/translation_manifest.json" ]] || fail "Blue Reflection translation database is missing"
[[ -f "$PROJECT_ROOT/titles/second_light/translation/translation_manifest.json" ]] || fail "Second Light translation database is missing"
mkdir -p -- "$REPORT_ROOT" "$BACKUP_ROOT"

tar -C "$PROJECT_ROOT" --zstd -cf "$BACKUP_PACKAGE" \
  titles/blue_reflection/translation \
  titles/second_light/translation \
  .local/reports/BR_TRANSLATION_EXPORT_REPORT.json \
  .local/reports/BR_ALIGNMENT_EXCEPTIONS.json

"$PROJECT_ROOT/Blue_Reflection_Text_Tool/workstream_lock.sh" \
  "$PROJECT_ROOT" translation -- \
  python3 "$TOOL" repair-export --project-root "$PROJECT_ROOT"

[[ -f "$REPORT_JSON" ]] || fail "Repair report was not created: $REPORT_JSON"
rm -rf -- "$PROJECT_ROOT/.local/build/translation/loose"
rm -f -- \
  "$PROJECT_ROOT/.local/build/translation/TRANSLATION_REPACK_PLAN.json" \
  "$REPORT_ROOT/BR_TRANSLATION_LOOSE_BUILD_REPORT.json" \
  "$REPORT_ROOT/BR_translation_loose_build_report.tar.zst" \
  "$REPORT_ROOT/BR_TRANSLATION_PAK_REPACK_REPORT.json" \
  "$REPORT_ROOT/BR_translation_pak_repack_report.tar.zst"

rm -f -- "$REPORT_PACKAGE"
tar -C "$PROJECT_ROOT" --zstd -cf "$REPORT_PACKAGE" \
  workstreams/translation_tooling/VERSION \
  workstreams/translation_tooling/STATUS.json \
  .local/reports/translation/BR_EBM_LAYOUT_REPAIR_REPORT.json \
  .local/reports/BR_TRANSLATION_EXPORT_REPORT.json \
  titles/blue_reflection/translation/translation_manifest.json \
  titles/second_light/translation/translation_manifest.json

printf '\nTranslation databases refreshed for the active English runtime targets; EBM layouts revalidated.\n'
printf 'Backup: %s\n' "$BACKUP_PACKAGE"
printf 'Upload this target-refresh report before rebuilding loose files:\n  %s\n' "$REPORT_PACKAGE"
