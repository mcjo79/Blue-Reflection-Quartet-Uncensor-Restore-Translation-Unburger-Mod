#!/usr/bin/env bash
set -Eeuo pipefail

PROJECT_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
TOOL="$PROJECT_ROOT/Blue_Reflection_Text_Tool/br_extension_tool.py"
REPORT_DIR="$PROJECT_ROOT/.local/reports"
REPORT_JSON="$REPORT_DIR/BR_PROJECT_BASE_VALIDATION.json"
REPORT_PACKAGE="$REPORT_DIR/BR_project_base_validation.tar.zst"

fail() {
  printf 'ERROR: %s\n' "$*" >&2
  exit 1
}

for cmd in python3 tar zstd; do
  command -v "$cmd" >/dev/null 2>&1 || fail "$cmd is required"
done

[[ -f "$TOOL" ]] || fail "Project validator is missing: $TOOL"
[[ -f "$PROJECT_ROOT/titles/blue_reflection/translation/translation_manifest.json" ]] || \
  fail "Blue Reflection translation base is missing. Run 03_create_translation_base.sh."
[[ -f "$PROJECT_ROOT/titles/second_light/translation/translation_manifest.json" ]] || \
  fail "Second Light translation base is missing. Run 03_create_translation_base.sh."

mkdir -p -- "$REPORT_DIR"

python3 "$TOOL" validate-project \
  --project-root "$PROJECT_ROOT" \
  --require-translation \
  --output "$REPORT_JSON"

python3 -m unittest -q \
  workstreams.core.tests.test_distribution_catalog_parity \
  workstreams.core.tests.test_canonical_state_consistency

rm -f -- "$REPORT_PACKAGE"
tar -C "$PROJECT_ROOT" --zstd -cf "$REPORT_PACKAGE" \
  config/project_version \
  config/canonical_state.json \
  config/modules.tsv \
  config/series_targets.tsv \
  config/quartet_archive_equivalence.tsv \
  .local/reports/BR_PROJECT_BASE_VALIDATION.json \
  titles/blue_reflection/config/project.json \
  titles/blue_reflection/translation/translation_manifest.json \
  titles/blue_reflection/modules/translation/module.json \
  titles/blue_reflection/modules/quartet_restoration/module.json \
  titles/blue_reflection/modules/quartet_restoration/registry/restoration_items.json \
  titles/blue_reflection/modules/quartet_movie_restoration/module.json \
  titles/blue_reflection/modules/quartet_legacy_dlc/module.json \
  titles/blue_reflection/modules/quartet_legacy_dlc/registry/content_registry.json \
  titles/second_light/config/project.json \
  titles/second_light/translation/translation_manifest.json \
  titles/second_light/modules/translation/module.json

printf '\nValidated canonical translation bases and current module architecture.\n'
printf 'Quartet Translation, UNCENSOR/movie restoration and DLC metadata agree with the current embedded catalog.\n'
printf '\nCreated report package:\n  %s\n' "$REPORT_PACKAGE"
