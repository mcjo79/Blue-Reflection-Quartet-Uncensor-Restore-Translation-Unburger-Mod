#!/usr/bin/env bash
set -Eeuo pipefail

usage() {
  cat <<'EOF'
Usage:
  85_run_bkn_dry_pc01_family_candidate_evidence.sh \
    --original-dir PATH --game-dir PATH [--gust-pak PATH]

Builds local, uninstalled PC00+PC01 dry BKN PACK10_02/PACK12 candidates and a
metadata-only evidence bundle. It never prepares or commits a transaction and
never writes to either game installation.
EOF
}

fail() {
  printf 'ERROR: %s\n' "$*" >&2
  exit 1
}

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="${BR_PROJECT_ROOT:-$(cd -- "$SCRIPT_DIR/../.." && pwd)}"
ORIGINAL_ROOT="${BR_ORIGINAL_GAME_ROOT:-}"
QUARTET_ROOT="${BR_QUARTET_GAME_ROOT:-}"
GUST_PAK="${BR_GUST_PAK:-}"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --original-dir)
      [[ $# -ge 2 ]] || fail "--original-dir requires a value"
      ORIGINAL_ROOT="$2"
      shift 2
      ;;
    --game-dir)
      [[ $# -ge 2 ]] || fail "--game-dir requires a value"
      QUARTET_ROOT="$2"
      shift 2
      ;;
    --gust-pak)
      [[ $# -ge 2 ]] || fail "--gust-pak requires a value"
      GUST_PAK="$2"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      fail "unknown argument: $1"
      ;;
  esac
done

[[ -d "$PROJECT_ROOT/workstreams/quartet_legacy_dlc" ]] || fail "invalid project root: $PROJECT_ROOT"
[[ "$(tr -d '\r\n' < "$PROJECT_ROOT/workstreams/quartet_legacy_dlc/VERSION")" == "0.0.41" ]] || fail "quartet_legacy_dlc 0.0.41 is required"
[[ -n "$ORIGINAL_ROOT" && -d "$ORIGINAL_ROOT" ]] || fail "provide a valid --original-dir or BR_ORIGINAL_GAME_ROOT"
[[ -n "$QUARTET_ROOT" && -d "$QUARTET_ROOT" ]] || fail "provide a valid --game-dir or BR_QUARTET_GAME_ROOT"

if [[ -z "$GUST_PAK" ]]; then
  if command -v gust_pak >/dev/null 2>&1; then
    GUST_PAK="$(command -v gust_pak)"
  else
    mapfile -t candidates < <(
      find "$PROJECT_ROOT" -xdev -type f -name gust_pak -perm -u+x \
        -not -path '*/.git/*' -not -path '*/.local/backups/*' 2>/dev/null | sort -u
    )
    if [[ ${#candidates[@]} -eq 1 ]]; then
      GUST_PAK="${candidates[0]}"
    elif [[ ${#candidates[@]} -eq 0 ]]; then
      fail "gust_pak was not found; pass --gust-pak PATH or set BR_GUST_PAK"
    else
      printf 'Found multiple gust_pak binaries:\n' >&2
      printf '  %s\n' "${candidates[@]}" >&2
      fail "pass the intended binary through --gust-pak PATH"
    fi
  fi
fi
[[ -x "$GUST_PAK" ]] || fail "gust_pak is not executable: $GUST_PAK"

for command in python3 sha256sum tar zstd; do
  command -v "$command" >/dev/null 2>&1 || fail "required command is missing: $command"
done

cd -- "$PROJECT_ROOT"
python3 -m unittest \
  workstreams.quartet_legacy_dlc.tests.test_br_dlc_bkn_dry_pc01_family_candidate_tool

REPORT_ROOT="$PROJECT_ROOT/.local/reports/quartet_legacy_dlc/bkn_dry_pc01_family_candidate_evidence"
python3 workstreams/quartet_legacy_dlc/br_dlc_bkn_dry_pc01_family_candidate_tool.py audit \
  --project-root "$PROJECT_ROOT" \
  --original-root "$ORIGINAL_ROOT" \
  --quartet-root "$QUARTET_ROOT" \
  --gust-pak "$GUST_PAK" \
  --output-root "$REPORT_ROOT"

python3 workstreams/quartet_legacy_dlc/br_dlc_bkn_dry_pc01_family_candidate_tool.py validate-report \
  --report-root "$REPORT_ROOT" >/dev/null

stamp="$(date -u +%Y%m%dT%H%M%SZ)"
archive_name="BR_QUARTET_DLC_BKN_DRY_PC01_FAMILY_CANDIDATE_${stamp}.tar.zst"
archive="$PROJECT_ROOT/.local/reports/quartet_legacy_dlc/$archive_name"
python3 workstreams/quartet_legacy_dlc/br_dlc_bkn_dry_pc01_family_candidate_tool.py bundle-report \
  --report-root "$REPORT_ROOT" \
  --output "$archive" >/dev/null
(
  cd -- "$(dirname -- "$archive")"
  sha256sum "$archive_name" > "$archive_name.sha256"
)

printf '\nPC00+PC01 dry family candidates built locally and not installed.\n'
printf 'Evidence: %s\n' "$archive"
printf 'SHA-256: %s.sha256\n' "$archive"
printf 'Prepare: false\nCommit: false\nInstallation: false\nRuntime validation: false\n'
