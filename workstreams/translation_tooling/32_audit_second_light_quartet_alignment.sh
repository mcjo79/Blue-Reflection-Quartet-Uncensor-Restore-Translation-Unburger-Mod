#!/usr/bin/env bash
set -Eeuo pipefail

PROJECT_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
TOOL="$PROJECT_ROOT/workstreams/translation_tooling/second_light_quartet_alignment_finalize.py"
VERSION="$(tr -d '[:space:]' < "$PROJECT_ROOT/workstreams/translation/VERSION")"
TOOLING_VERSION="$(tr -d '[:space:]' < "$PROJECT_ROOT/workstreams/translation_tooling/VERSION")"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
OUT="$PROJECT_ROOT/.local/reports/translation/second_light_b4_alignment_finalization_audit/$STAMP"
BUNDLE="$HOME/Downloads/BR_SECOND_LIGHT_B4_ALIGNMENT_FINALIZATION_AUDIT_${VERSION}_${STAMP}.tar.zst"

[[ -x "$TOOL" ]] || { echo "ERROR: missing finalization auditor: $TOOL" >&2; exit 1; }
[[ "$VERSION" == "0.0.112" ]] || {
  echo "ERROR: expected translation 0.0.112; found $VERSION" >&2
  exit 1
}
[[ "$TOOLING_VERSION" == "0.0.51" ]] || {
  echo "ERROR: expected translation_tooling 0.0.51; found $TOOLING_VERSION" >&2
  exit 1
}

mkdir -p "$OUT" "$HOME/Downloads"
python3 "$TOOL" audit \
  --project-root "$PROJECT_ROOT" \
  --output-dir "$OUT" \
  | tee "$OUT/TERMINAL_SUMMARY.json"

tar -C "$PROJECT_ROOT" --zstd -cf "$BUNDLE" \
  ".local/reports/translation/second_light_b4_alignment_finalization_audit/$STAMP" \
  workstreams/translation_tooling/second_light_quartet_alignment_finalize.py \
  workstreams/translation_tooling/32_audit_second_light_quartet_alignment.sh \
  workstreams/translation_tooling/VERSION
sha256sum "$BUNDLE" > "$BUNDLE.sha256"

printf '\nRefined read-only alignment audit completed.\nReport: %s\nBundle: %s\nSHA-256: %s\n' \
  "$OUT/SUMMARY.json" "$BUNDLE" "$BUNDLE.sha256"
