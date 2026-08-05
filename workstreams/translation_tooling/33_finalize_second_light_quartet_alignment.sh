#!/usr/bin/env bash
set -Eeuo pipefail

PROJECT_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
TOOL="$PROJECT_ROOT/workstreams/translation_tooling/second_light_quartet_alignment_finalize.py"
LOCK="$PROJECT_ROOT/Blue_Reflection_Text_Tool/workstream_lock.sh"

[[ "${1:-}" == "--apply" ]] || {
  echo 'ERROR: finalization writes canonical auxiliary metadata; rerun with --apply' >&2
  exit 2
}

VERSION="$(tr -d '[:space:]' < "$PROJECT_ROOT/workstreams/translation/VERSION")"
TOOLING_VERSION="$(tr -d '[:space:]' < "$PROJECT_ROOT/workstreams/translation_tooling/VERSION")"
[[ "$VERSION" == "0.0.112" ]] || {
  echo "ERROR: expected translation 0.0.112; found $VERSION" >&2
  exit 1
}
[[ "$TOOLING_VERSION" == "0.0.53" ]] || {
  echo "ERROR: expected translation_tooling 0.0.53; found $TOOLING_VERSION" >&2
  exit 1
}
[[ -x "$TOOL" ]] || { echo "ERROR: missing finalizer: $TOOL" >&2; exit 1; }
[[ -x "$LOCK" ]] || { echo "ERROR: missing lock helper: $LOCK" >&2; exit 1; }

STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
OUT="$PROJECT_ROOT/.local/reports/translation/second_light_b4_alignment_finalization/$STAMP"
BACKUP="$PROJECT_ROOT/.local/backups/translation_auxiliary_finalization/$STAMP.tar.zst"
mkdir -p "$OUT" "$(dirname "$BACKUP")" "$HOME/Downloads"

tar -C "$PROJECT_ROOT" --zstd -cf "$BACKUP" \
  titles/second_light/translation \
  workstreams/translation

restore() {
  echo 'Finalization failed; restoring Translation state from the local backup.' >&2
  echo "Preflight diagnostics preserved in: $OUT" >&2
  rm -rf \
    "$PROJECT_ROOT/titles/second_light/translation" \
    "$PROJECT_ROOT/workstreams/translation"
  tar -C "$PROJECT_ROOT" --zstd -xf "$BACKUP"
}
trap 'rc=$?; if (( rc != 0 )); then restore; fi; exit $rc' EXIT

"$LOCK" "$PROJECT_ROOT" translation -- \
  python3 "$TOOL" apply \
    --project-root "$PROJECT_ROOT" \
    --output-dir "$OUT" \
  | tee "$OUT/TERMINAL_SUMMARY.json"

NEW_VERSION="$(tr -d '[:space:]' < "$PROJECT_ROOT/workstreams/translation/VERSION")"
[[ "$NEW_VERSION" == "0.0.113" ]] || {
  echo "ERROR: expected translation 0.0.113 after finalization; found $NEW_VERSION" >&2
  exit 1
}

BUNDLE="$HOME/Downloads/Blue_Reflection_translation_chat_second_light_auxiliary_finalization_${NEW_VERSION}_${STAMP}.tar.zst"
tar -C "$PROJECT_ROOT" --zstd -cf "$BUNDLE" \
  workstreams/translation \
  titles/blue_reflection/translation \
  titles/second_light/translation \
  titles/blue_reflection_sun/translation \
  titles/blue_reflection_ray/translation \
  ".local/reports/translation/second_light_b4_alignment_finalization/$STAMP"
sha256sum "$BUNDLE" > "$BUNDLE.sha256"

trap - EXIT
printf '\nSecond Light / Quartet b4 auxiliary finalization completed.\nTranslation version: %s\nBackup: %s\nReport: %s\nHandoff bundle: %s\nSHA-256: %s\n' \
  "$NEW_VERSION" "$BACKUP" "$OUT/SUMMARY.json" "$BUNDLE" "$BUNDLE.sha256"
