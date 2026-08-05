#!/usr/bin/env bash
set -Eeuo pipefail

PROJECT_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
TOOL="$PROJECT_ROOT/Blue_Reflection_Text_Tool/br_text_tool.py"
REPORT_ROOT="$PROJECT_ROOT/.local/reports/translation"
REPORT_JSON="$REPORT_ROOT/BR_TRANSLATION_LOOSE_BUILD_REPORT.json"
REPORT_PACKAGE="$REPORT_ROOT/BR_translation_loose_build_report.tar.zst"
PLAN="$PROJECT_ROOT/.local/build/translation/TRANSLATION_REPACK_PLAN.json"

fail() {
  printf 'ERROR: %s\n' "$*" >&2
  exit 1
}

for cmd in python3 tar zstd; do
  command -v "$cmd" >/dev/null 2>&1 || fail "$cmd is required"
done

[[ -f "$TOOL" ]] || fail "Translation tool is missing: $TOOL"
REFRESH_REPORT="$PROJECT_ROOT/.local/reports/translation/BR_EBM_LAYOUT_REPAIR_REPORT.json"
[[ -f "$REFRESH_REPORT" ]] ||   fail "Active-English target refresh is required first. Run 06_repair_translation_database.sh."
python3 - "$REFRESH_REPORT" <<'PY' ||   fail "Translation database still targets inactive JP paths. Run 06_repair_translation_database.sh."
import json
import sys
report = json.load(open(sys.argv[1], encoding="utf-8"))
assert report.get("status") == "ok"
assert report.get("runtime_target_adapter") == "active_english"
assert report.get("tool_version") in {"translation-0.0.11", "translation-0.0.12", "translation-0.0.13", "translation-0.0.14"}
PY
[[ -f "$PROJECT_ROOT/titles/blue_reflection/translation/translation_manifest.json" ]] || \
  fail "Blue Reflection translation database is missing."
[[ -f "$PROJECT_ROOT/titles/second_light/translation/translation_manifest.json" ]] || \
  fail "Second Light translation database is missing."

mkdir -p -- "$REPORT_ROOT"
TITLE_MARKER="${BR_TITLE_MARKER:-none}"
case "${TITLE_MARKER,,}" in
  ''|none|off|disabled) TITLE_MARKER="none" ;;
  *) fail "UIL title markers are retired. Run step 07 with BR_TITLE_MARKER=none, then step 08, then step 14 for the synthetic Second Light G1T proof." ;;
esac
BUILD_ARGS=(
  build-loose
  --project-root "$PROJECT_ROOT"
  --title-marker "$TITLE_MARKER"
)
case "${BR_RUNTIME_CANARY:-0}" in
  1|true|TRUE|yes|YES|on|ON) BUILD_ARGS+=(--runtime-canary) ;;
  0|false|FALSE|no|NO|off|OFF|'') ;;
  *) fail "BR_RUNTIME_CANARY must be 0/1, true/false, yes/no or on/off" ;;
esac

"$PROJECT_ROOT/Blue_Reflection_Text_Tool/workstream_lock.sh" \
  "$PROJECT_ROOT" translation -- \
  python3 "$TOOL" "${BUILD_ARGS[@]}"

QUARTET_AUDIT="$PROJECT_ROOT/workstreams/translation_tooling/quartet_translation_mapping_audit.py"
QUARTET_AUDIT_JSON="$REPORT_ROOT/BR_QUARTET_TRANSLATION_MAPPING_AUDIT.json"
[[ -f "$QUARTET_AUDIT" ]] || fail "Quartet mapping audit tool is missing: $QUARTET_AUDIT"
python3 "$QUARTET_AUDIT" \
  --project-root "$PROJECT_ROOT" \
  --report "$QUARTET_AUDIT_JSON" \
  --verify-loose-build

[[ -f "$REPORT_JSON" ]] || fail "Loose-build report was not created: $REPORT_JSON"
[[ -f "$PLAN" ]] || fail "Repack plan was not created: $PLAN"

rm -f -- "$REPORT_PACKAGE"
tar -C "$PROJECT_ROOT" --zstd -cf "$REPORT_PACKAGE" \
  workstreams/translation_tooling/VERSION \
  workstreams/translation_tooling/STATUS.json \
  .local/reports/translation/BR_TRANSLATION_LOOSE_BUILD_REPORT.json \
  .local/reports/translation/BR_QUARTET_TRANSLATION_MAPPING_AUDIT.json \
  workstreams/translation_tooling/config/quartet_target_adaptations.json \
  .local/build/translation/TRANSLATION_REPACK_PLAN.json

printf '\nLoose EBM/XML build completed without writing any game PAK.\n'
printf 'Upload this report before running the development repack:\n  %s\n' \
  "$REPORT_PACKAGE"
