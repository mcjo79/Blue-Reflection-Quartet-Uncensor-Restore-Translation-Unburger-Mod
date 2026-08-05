#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
PROJECT_ROOT="${BR_PROJECT_ROOT:-$(cd -- "$SCRIPT_DIR/../.." && pwd -P)}"
GAME_DIR="${BR_QUARTET_GAME_ROOT:-}"

usage() {
  printf 'Usage: %s --game-dir PATH\n' "$(basename "$0")" >&2
}

while (($#)); do
  case "$1" in
    --game-dir)
      (($# >= 2)) || { usage; exit 2; }
      GAME_DIR="$2"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) printf 'ERROR: unknown argument: %s\n' "$1" >&2; usage; exit 2 ;;
  esac
done

[[ -n "$GAME_DIR" ]] || { printf 'ERROR: pass --game-dir or set BR_QUARTET_GAME_ROOT\n' >&2; exit 1; }
[[ -d "$GAME_DIR" ]] || { printf 'ERROR: Quartet game directory does not exist: %s\n' "$GAME_DIR" >&2; exit 1; }

TOOL="$PROJECT_ROOT/workstreams/quartet_legacy_dlc/br_dlc_generic_manifest_publish_tool.py"
MANIFEST="$PROJECT_ROOT/workstreams/quartet_legacy_dlc/BKN_DRY_PC00_PC01_ACTIVE_MANIFEST.json"
RUNNER="$PROJECT_ROOT/workstreams/core/tools/validate_quartet_legacy_dlc_active_manifest.sh"
[[ -f "$TOOL" && ! -L "$TOOL" ]] || { printf 'ERROR: publication tool missing or symlink\n' >&2; exit 1; }
[[ -f "$MANIFEST" && ! -L "$MANIFEST" ]] || { printf 'ERROR: canonical source manifest missing or symlink\n' >&2; exit 1; }
[[ -f "$RUNNER" && ! -L "$RUNNER" ]] || { printf 'ERROR: core runner missing or symlink\n' >&2; exit 1; }

python3 "$TOOL" --project-root "$PROJECT_ROOT" --game-dir "$GAME_DIR" --manifest "$MANIFEST"

STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
OUTPUT_DIR="$PROJECT_ROOT/.local/reports/quartet_legacy_dlc/BR_QUARTET_LEGACY_DLC_MANIFEST_PREVIEW_$STAMP"
bash "$RUNNER" --project-root "$PROJECT_ROOT" --game-dir "$GAME_DIR" --output-dir "$OUTPUT_DIR"

ARCHIVE="$OUTPUT_DIR.tar.zst"
[[ -f "$ARCHIVE" && -f "$ARCHIVE.sha256" ]] || { printf 'ERROR: core runner did not create expected evidence\n' >&2; exit 1; }
(
  cd -- "$(dirname -- "$ARCHIVE")"
  sha256sum -c "$(basename -- "$ARCHIVE").sha256"
)

printf '\nPublished active manifest: %s\n' "$PROJECT_ROOT/.local/reports/quartet_legacy_dlc/validated_payloads/ACTIVE.json"
printf 'Canonical generic preview evidence: %s\n' "$ARCHIVE"
printf 'SHA-256 sidecar: %s.sha256\n' "$ARCHIVE"
printf 'No transaction was prepared or committed and no game file was modified.\n'
