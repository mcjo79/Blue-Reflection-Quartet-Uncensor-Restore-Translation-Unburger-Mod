#!/usr/bin/env bash
set -euo pipefail

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
      GAME_DIR="$2"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      printf 'ERROR: unknown argument: %s\n' "$1" >&2
      usage
      exit 2
      ;;
  esac
done

[[ -n "$GAME_DIR" ]] || { printf 'ERROR: pass --game-dir or set BR_QUARTET_GAME_ROOT\n' >&2; exit 1; }
[[ -d "$GAME_DIR" ]] || { printf 'ERROR: Quartet game directory does not exist: %s\n' "$GAME_DIR" >&2; exit 1; }

TOOL="$PROJECT_ROOT/workstreams/quartet_legacy_dlc/br_dlc_bkn_dry_pc00_pc01_core_preview_handoff_tool.py"
REPORT_ROOT="$PROJECT_ROOT/.local/reports/quartet_legacy_dlc/bkn_dry_pc00_pc01_core_preview_handoff_evidence"
OUTPUT="$PROJECT_ROOT/.local/reports/quartet_legacy_dlc/BR_quartet_legacy_dlc_bkn_dry_pc00_pc01_core_preview_handoff_evidence.tar.zst"

python3 "$TOOL" build-handoff --project-root "$PROJECT_ROOT" --game-dir "$GAME_DIR"
python3 "$TOOL" validate-report --report-root "$REPORT_ROOT"
python3 "$TOOL" bundle-report --report-root "$REPORT_ROOT" --output "$OUTPUT"
(
  cd -- "$(dirname -- "$OUTPUT")"
  sha256sum "$(basename -- "$OUTPUT")" > "$(basename -- "$OUTPUT").sha256"
)

printf '\nCore handoff evidence: %s\n' "$OUTPUT"
printf 'SHA-256 sidecar: %s.sha256\n' "$OUTPUT"
printf 'No transaction was prepared or committed and no game file was modified.\n'
