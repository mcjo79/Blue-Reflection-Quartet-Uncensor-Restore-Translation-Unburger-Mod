#!/usr/bin/env bash
set -Eeuo pipefail

PROJECT_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
TEXT_TOOL="$PROJECT_ROOT/Blue_Reflection_Text_Tool/br_text_tool.py"
AUDIT_TOOL="$PROJECT_ROOT/workstreams/translation_tooling/quartet_translation_mapping_audit.py"
REPORT_DIR="$PROJECT_ROOT/.local/reports/translation"
BUILD_REPORT="$REPORT_DIR/BR_TRANSLATION_LOOSE_BUILD_REPORT.json"
AUDIT_REPORT="$REPORT_DIR/BR_QUARTET_TRANSLATION_MAPPING_AUDIT.json"
PLAN="$PROJECT_ROOT/.local/build/translation/TRANSLATION_REPACK_PLAN.json"
PACKAGE="$REPORT_DIR/BR_quartet_translation_preview.tar.zst"

fail() { printf 'ERROR: %s\n' "$*" >&2; exit 1; }
for cmd in python3 tar zstd; do command -v "$cmd" >/dev/null 2>&1 || fail "$cmd is required"; done
[[ -f "$TEXT_TOOL" ]] || fail "Translation tool is missing: $TEXT_TOOL"
[[ -f "$AUDIT_TOOL" ]] || fail "Audit tool is missing: $AUDIT_TOOL"
mkdir -p -- "$REPORT_DIR"

"$PROJECT_ROOT/Blue_Reflection_Text_Tool/workstream_lock.sh" \
  "$PROJECT_ROOT" translation -- \
  python3 "$TEXT_TOOL" build-loose \
    --project-root "$PROJECT_ROOT" \
    --target blue_reflection_quartet \
    --title-marker none

python3 "$AUDIT_TOOL" \
  --project-root "$PROJECT_ROOT" \
  --report "$AUDIT_REPORT" \
  --verify-loose-build

[[ -f "$BUILD_REPORT" ]] || fail "Loose build report is missing: $BUILD_REPORT"
[[ -f "$PLAN" ]] || fail "Repack plan is missing: $PLAN"
rm -f -- "$PACKAGE"
tar -C "$PROJECT_ROOT" --zstd -cf "$PACKAGE" \
  workstreams/translation_tooling/VERSION \
  workstreams/translation_tooling/config/quartet_target_adaptations.json \
  .local/reports/translation/BR_TRANSLATION_LOOSE_BUILD_REPORT.json \
  .local/reports/translation/BR_QUARTET_TRANSLATION_MAPPING_AUDIT.json \
  .local/build/translation/TRANSLATION_REPACK_PLAN.json

printf '\nQuartet loose preview built and fully checked without repacking or writing game PAKs.\n'
printf 'Preview package:\n  %s\n' "$PACKAGE"
