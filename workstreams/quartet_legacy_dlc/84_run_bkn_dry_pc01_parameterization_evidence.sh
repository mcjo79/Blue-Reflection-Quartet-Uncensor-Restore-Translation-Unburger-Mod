#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd -- "$SCRIPT_DIR/../.." && pwd)"
REPORTS_ROOT="$PROJECT_ROOT/.local/reports/quartet_legacy_dlc"
WORKSTREAM_ROOT="$PROJECT_ROOT/workstreams/quartet_legacy_dlc"

for command in python3 tar zstd sha256sum; do
  command -v "$command" >/dev/null 2>&1 || {
    printf 'ERROR: required command is missing: %s\n' "$command" >&2
    exit 1
  }
done

mapfile -t STAGE83_ARCHIVES < <(
  find "$REPORTS_ROOT" -maxdepth 1 -type f \
    -name 'BR_QUARTET_DLC_BKN_DRY_FAMILY_EXPANSION_*.tar.zst' \
    -printf '%T@\t%p\n' | sort -nr | cut -f2-
)
[[ ${#STAGE83_ARCHIVES[@]} -gt 0 ]] || {
  printf 'ERROR: no stage-83 family-expansion evidence archive was found under %s\n' "$REPORTS_ROOT" >&2
  exit 1
}
STAGE83_ARCHIVE="${STAGE83_ARCHIVES[0]}"

STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
NAME="BR_QUARTET_DLC_BKN_DRY_PC01_PARAMETERIZATION_${STAMP}"
OUT_DIR="$REPORTS_ROOT/$NAME"
ARCHIVE="$REPORTS_ROOT/$NAME.tar.zst"
SIDECAR="$ARCHIVE.sha256"
[[ ! -e "$OUT_DIR" && ! -e "$ARCHIVE" && ! -e "$SIDECAR" ]] || {
  printf 'ERROR: output already exists for timestamp %s\n' "$STAMP" >&2
  exit 1
}

python3 "$SCRIPT_DIR/br_dlc_bkn_dry_pc01_parameterization_tool.py" collect \
  --workstream-root "$WORKSTREAM_ROOT" \
  --stage83-archive "$STAGE83_ARCHIVE" \
  --output-dir "$OUT_DIR"

python3 "$SCRIPT_DIR/br_dlc_bkn_dry_pc01_parameterization_tool.py" validate \
  --output-dir "$OUT_DIR"

tar --zstd -cf "$ARCHIVE" -C "$REPORTS_ROOT" "$NAME"
(
  cd -- "$REPORTS_ROOT"
  sha256sum "$(basename -- "$ARCHIVE")" > "$(basename -- "$SIDECAR")"
)

printf '\nPC01 dry BKN parameterization evidence created.\n'
printf 'Selected candidate: PC01\n'
printf 'Inputs: stage-83 metadata and repository source text only\n'
printf 'Game read/write: no\nRaw assets or PAKs exported: no\n'
printf 'Prepare: disabled\nCommit: disabled\nInstallation: disabled\nRuntime validation: disabled\nWet BKN: excluded\n'
printf 'Evidence: %s\n' "$ARCHIVE"
printf 'SHA-256 sidecar: %s\n' "$SIDECAR"
