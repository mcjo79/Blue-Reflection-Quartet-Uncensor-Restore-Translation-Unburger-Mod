#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd -- "$SCRIPT_DIR/../.." && pwd)"
REPORTS_ROOT="$PROJECT_ROOT/.local/reports/quartet_legacy_dlc"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
NAME="BR_QUARTET_DLC_BKN_DRY_FAMILY_EXPANSION_${STAMP}"
OUT_DIR="$REPORTS_ROOT/$NAME"
ARCHIVE="$REPORTS_ROOT/$NAME.tar.zst"
SIDECAR="$ARCHIVE.sha256"

for command in python3 tar zstd sha256sum; do
  command -v "$command" >/dev/null 2>&1 || {
    printf 'ERROR: required command is missing: %s\n' "$command" >&2
    exit 1
  }
done

[[ -d "$REPORTS_ROOT" ]] || {
  printf 'ERROR: quartet_legacy_dlc reports directory is missing: %s\n' "$REPORTS_ROOT" >&2
  exit 1
}
[[ ! -e "$OUT_DIR" && ! -e "$ARCHIVE" && ! -e "$SIDECAR" ]] || {
  printf 'ERROR: output already exists for timestamp %s\n' "$STAMP" >&2
  exit 1
}

python3 "$SCRIPT_DIR/br_dlc_bkn_dry_family_expansion_tool.py" collect \
  --reports-root "$REPORTS_ROOT" \
  --output-dir "$OUT_DIR"

python3 "$SCRIPT_DIR/br_dlc_bkn_dry_family_expansion_tool.py" validate \
  --output-dir "$OUT_DIR"

tar --zstd -cf "$ARCHIVE" -C "$REPORTS_ROOT" "$NAME"
(
  cd -- "$REPORTS_ROOT"
  sha256sum "$(basename -- "$ARCHIVE")" > "$(basename -- "$SIDECAR")"
)

printf '\nDry BKN family-expansion evidence created.\n'
printf 'No game file was read or written. No PAK was built.\n'
printf 'Prepare: disabled\nCommit: disabled\nInstallation: disabled\nRuntime validation: disabled\nWet BKN: excluded\n'
printf 'Evidence: %s\n' "$ARCHIVE"
printf 'SHA-256 sidecar: %s\n' "$SIDECAR"
