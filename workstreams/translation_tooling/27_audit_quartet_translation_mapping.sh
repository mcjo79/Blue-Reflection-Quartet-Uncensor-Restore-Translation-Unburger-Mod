#!/usr/bin/env bash
set -Eeuo pipefail

PROJECT_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
TOOL="$PROJECT_ROOT/workstreams/translation_tooling/quartet_translation_mapping_audit.py"
REPORT_DIR="$PROJECT_ROOT/.local/reports/translation"
REPORT_JSON="$REPORT_DIR/BR_QUARTET_TRANSLATION_MAPPING_AUDIT.json"
REPORT_PACKAGE="$REPORT_DIR/BR_quartet_translation_mapping_audit.tar.zst"

fail() { printf 'ERROR: %s\n' "$*" >&2; exit 1; }
for cmd in python3 tar zstd; do command -v "$cmd" >/dev/null 2>&1 || fail "$cmd is required"; done
[[ -f "$TOOL" ]] || fail "Audit tool is missing: $TOOL"
mkdir -p -- "$REPORT_DIR"

python3 "$TOOL" \
  --project-root "$PROJECT_ROOT" \
  --report "$REPORT_JSON"

rm -f -- "$REPORT_PACKAGE"
tar -C "$PROJECT_ROOT" --zstd -cf "$REPORT_PACKAGE" \
  workstreams/translation_tooling/VERSION \
  workstreams/translation_tooling/config/quartet_target_adaptations.json \
  .local/reports/translation/BR_QUARTET_TRANSLATION_MAPPING_AUDIT.json

printf '\nRead-only audit complete. No translation JSON or game file was modified.\n'
printf 'Report package:\n  %s\n' "$REPORT_PACKAGE"
