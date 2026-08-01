#!/usr/bin/env bash
set -Eeuo pipefail

PROJECT_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
TOOL="$PROJECT_ROOT/Blue_Reflection_Text_Tool/br_text_tool.py"
REPORT_DIR="$PROJECT_ROOT/.local/reports"
REPORT_PACKAGE="$REPORT_DIR/BR_translation_base_report.tar.zst"

fail() {
  printf 'ERROR: %s\n' "$*" >&2
  exit 1
}

for cmd in python3 tar zstd; do
  command -v "$cmd" >/dev/null 2>&1 || fail "$cmd is required"
done

[[ -x "$TOOL" ]] || fail "Translation exporter is missing or not executable: $TOOL"
[[ -d "$PROJECT_ROOT/titles/blue_reflection/workspace/original/archives/PACK01" ]] || \
  fail "Blue Reflection text workspace is missing. Run 02_extract_text_sources.sh first."
[[ -d "$PROJECT_ROOT/titles/second_light/workspace/original/archives/PACK01" ]] || \
  fail "Second Light text workspace is missing. Run 02_extract_text_sources.sh first."

python3 "$TOOL" export --project-root "$PROJECT_ROOT"

mkdir -p -- "$REPORT_DIR"
rm -f -- "$REPORT_PACKAGE"

tar -C "$PROJECT_ROOT" --zstd -cf "$REPORT_PACKAGE" \
  config/project_version \
  config/series_targets.tsv \
  shared/schemas/translation_unit_v1.schema.json \
  .local/reports/BR_TRANSLATION_EXPORT_REPORT.json \
  .local/reports/BR_ALIGNMENT_EXCEPTIONS.json \
  titles/blue_reflection/translation/translation_manifest.json \
  titles/second_light/translation/translation_manifest.json

printf '\nCreated canonical translation databases in:\n'
printf '  %s\n' "$PROJECT_ROOT/titles/blue_reflection/translation"
printf '  %s\n' "$PROJECT_ROOT/titles/second_light/translation"
printf '\nEditable field: en\n'
printf 'Frozen reference fields: jp, en_original, en_auxiliary\n'
printf '\nCreated report package:\n  %s\n' "$REPORT_PACKAGE"
printf 'Upload this report before the import/build wrappers are added.\n'
