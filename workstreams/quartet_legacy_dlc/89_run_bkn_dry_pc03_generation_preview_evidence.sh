#!/usr/bin/env bash
set -Eeuo pipefail

usage() {
  cat <<'EOF'
Usage:
  89_run_bkn_dry_pc03_generation_preview_evidence.sh \
    --original-dir PATH --game-dir PATH [--gust-pak PATH]

Builds the local PC00+PC01+PC02+PC03 dry-BKN candidates, publishes generation 4 of
the DLC-owned generic ACTIVE.json manifest, and runs the core-owned read-only
canonical preview. It never prepares or commits a transaction and never writes
to either game installation.
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
[[ "$(tr -d '\r\n' < "$PROJECT_ROOT/workstreams/quartet_legacy_dlc/VERSION")" == "0.0.46" ]] || fail "quartet_legacy_dlc 0.0.46 is required"
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

for command in python3 sha256sum tar zstd go realpath stat; do
  command -v "$command" >/dev/null 2>&1 || fail "required command is missing: $command"
done

CORE_RUNNER="$PROJECT_ROOT/workstreams/core/tools/validate_quartet_legacy_dlc_active_manifest.sh"
[[ -x "$CORE_RUNNER" && ! -L "$CORE_RUNNER" ]] || fail "core-owned generic manifest runner is missing or unsafe: $CORE_RUNNER"

cd -- "$PROJECT_ROOT"
python3 -m unittest \
  workstreams.quartet_legacy_dlc.tests.test_br_dlc_bkn_dry_pc03_generation_tool \
  workstreams.quartet_legacy_dlc.tests.test_br_dlc_bkn_dry_generation_publish_tool

REPORT_ROOT="$PROJECT_ROOT/.local/reports/quartet_legacy_dlc/bkn_dry_pc03_generation_evidence"
python3 workstreams/quartet_legacy_dlc/br_dlc_bkn_dry_pc03_generation_tool.py audit \
  --project-root "$PROJECT_ROOT" \
  --original-root "$ORIGINAL_ROOT" \
  --quartet-root "$QUARTET_ROOT" \
  --gust-pak "$GUST_PAK" \
  --output-root "$REPORT_ROOT"

python3 workstreams/quartet_legacy_dlc/br_dlc_bkn_dry_pc03_generation_tool.py validate-report \
  --report-root "$REPORT_ROOT" >/dev/null

stamp="$(date -u +%Y%m%dT%H%M%SZ)"
CANDIDATE_ARCHIVE="$PROJECT_ROOT/.local/reports/quartet_legacy_dlc/BR_QUARTET_DLC_BKN_DRY_PC03_GENERATION_CANDIDATE_${stamp}.tar.zst"
python3 workstreams/quartet_legacy_dlc/br_dlc_bkn_dry_pc03_generation_tool.py bundle-report \
  --report-root "$REPORT_ROOT" \
  --output "$CANDIDATE_ARCHIVE" >/dev/null
(
  cd -- "$(dirname -- "$CANDIDATE_ARCHIVE")"
  sha256sum "$(basename -- "$CANDIDATE_ARCHIVE")" > "$(basename -- "$CANDIDATE_ARCHIVE").sha256"
  sha256sum -c "$(basename -- "$CANDIDATE_ARCHIVE").sha256"
)

python3 workstreams/quartet_legacy_dlc/br_dlc_bkn_dry_generation_publish_tool.py \
  --project-root "$PROJECT_ROOT" \
  --game-dir "$QUARTET_ROOT" \
  --report-root "$REPORT_ROOT" \
  > "$PROJECT_ROOT/.local/reports/quartet_legacy_dlc/GENERATION_4_PUBLICATION_STDOUT.json"

PREVIEW_DIR="$PROJECT_ROOT/.local/reports/quartet_legacy_dlc/BR_QUARTET_LEGACY_DLC_MANIFEST_PREVIEW_${stamp}"
bash "$CORE_RUNNER" \
  --project-root "$PROJECT_ROOT" \
  --game-dir "$QUARTET_ROOT" \
  --output-dir "$PREVIEW_DIR"

PREVIEW_ARCHIVE="$PREVIEW_DIR.tar.zst"
[[ -f "$PREVIEW_ARCHIVE" && -f "$PREVIEW_ARCHIVE.sha256" ]] || fail "core preview archive was not produced"
(
  cd -- "$(dirname -- "$PREVIEW_ARCHIVE")"
  sha256sum -c "$(basename -- "$PREVIEW_ARCHIVE").sha256"
)

FINAL_ROOT="$PROJECT_ROOT/.local/reports/quartet_legacy_dlc/BR_QUARTET_DLC_BKN_DRY_PC03_GENERATION_PREVIEW_${stamp}"
rm -rf -- "$FINAL_ROOT"
mkdir -p "$FINAL_ROOT/CANDIDATE_REPORT"
cp -a -- "$REPORT_ROOT/." "$FINAL_ROOT/CANDIDATE_REPORT/"
cp -- "$CANDIDATE_ARCHIVE" "$FINAL_ROOT/"
cp -- "$CANDIDATE_ARCHIVE.sha256" "$FINAL_ROOT/"
cp -- "$PREVIEW_ARCHIVE" "$FINAL_ROOT/"
cp -- "$PREVIEW_ARCHIVE.sha256" "$FINAL_ROOT/"
cp -- "$PROJECT_ROOT/.local/reports/quartet_legacy_dlc/validated_payloads/ACTIVE.json" "$FINAL_ROOT/ACTIVE_MANIFEST.json"
cp -- "$PROJECT_ROOT/.local/reports/quartet_legacy_dlc/validated_payloads/GENERATION_4_PUBLICATION.json" "$FINAL_ROOT/GENERATION_4_PUBLICATION.json"
cp -- "$PROJECT_ROOT/.local/reports/quartet_legacy_dlc/generations/bkn_dry_generation_4/EVIDENCE.json" "$FINAL_ROOT/GENERATION_4_EVIDENCE.json"
cp -- "$PROJECT_ROOT/workstreams/quartet_legacy_dlc/DLC_BKN_DRY_PC00_PC01_GENERIC_PREVIEW_ACCEPTANCE.json" "$FINAL_ROOT/"
cp -- "$PROJECT_ROOT/workstreams/quartet_legacy_dlc/DLC_BKN_DRY_PC03_GENERATION_ACCEPTANCE.json" "$FINAL_ROOT/"
cp -- "$PROJECT_ROOT/workstreams/core/VERSION" "$FINAL_ROOT/CORE_VERSION.txt"
cp -- "$PROJECT_ROOT/workstreams/quartet_legacy_dlc/VERSION" "$FINAL_ROOT/DLC_VERSION.txt"

python3 - "$FINAL_ROOT" "$PREVIEW_DIR" <<'PY'
import json, pathlib, sys
root=pathlib.Path(sys.argv[1])
preview_root=pathlib.Path(sys.argv[2])
manifest=json.loads((root/'ACTIVE_MANIFEST.json').read_text())
publication=json.loads((root/'GENERATION_4_PUBLICATION.json').read_text())
validation=json.loads((preview_root/'VALIDATION.json').read_text())
errors=[]
if manifest.get('generation') != 4: errors.append('ACTIVE generation is not 4')
if manifest.get('members') != ['costume_pc00_bkn','costume_pc01_bkn','costume_pc02_bkn','costume_pc03_bkn']:
    errors.append('ACTIVE members mismatch')
if publication.get('status') != 'pass': errors.append('publication did not pass')
if publication.get('commit_enabled') is not False: errors.append('publication CommitEnabled is not false')
if validation.get('status') != 'pass': errors.append('core preview validation did not pass')
if validation.get('artifact_paths') != ['Data/PACK10_02.PAK','Data/PACK12.PAK']:
    errors.append('core preview artifact paths mismatch')
for key in ('transaction_function_called','transaction_prepare_called','transaction_commit_called','game_modified'):
    if validation.get(key) is not False: errors.append(f'{key} is not false')
result={
  'type':'br_quartet_legacy_dlc_bkn_dry_pc03_generation_preview_validation',
  'format_version':1,
  'status':'pass' if not errors else 'fail',
  'generation':4,
  'members':['costume_pc00_bkn','costume_pc01_bkn','costume_pc02_bkn','costume_pc03_bkn'],
  'artifact_count':2,
  'artifact_paths':['Data/PACK10_02.PAK','Data/PACK12.PAK'],
  'all_or_none_ready':not errors,
  'commit_enabled':False,
  'transaction_function_called':False,
  'transaction_prepare_called':False,
  'transaction_commit_called':False,
  'candidate_installed':False,
  'profile_registered':False,
  'runtime_validated':False,
  'wet_variant_included':False,
  'game_modified':False,
  'errors':errors,
}
(root/'FINAL_VALIDATION.json').write_text(json.dumps(result,indent=2)+'\n')
if errors: raise SystemExit('\n'.join(errors))
PY

(
  cd -- "$FINAL_ROOT"
  find . -type f ! -name SHA256SUMS -print0 | sort -z | xargs -0 sha256sum > SHA256SUMS
  sha256sum -c SHA256SUMS >/dev/null
)
FINAL_ARCHIVE="$FINAL_ROOT.tar.zst"
tar --sort=name --mtime='UTC 1970-01-01' --owner=0 --group=0 --numeric-owner \
  -C "$(dirname -- "$FINAL_ROOT")" -cf - "$(basename -- "$FINAL_ROOT")" \
  | zstd -T0 -19 -q -o "$FINAL_ARCHIVE"
(
  cd -- "$(dirname -- "$FINAL_ARCHIVE")"
  sha256sum "$(basename -- "$FINAL_ARCHIVE")" > "$(basename -- "$FINAL_ARCHIVE").sha256"
  sha256sum -c "$(basename -- "$FINAL_ARCHIVE").sha256"
)

printf '\nPC00+PC01+PC02+PC03 dry BKN generation 4 built and previewed without installation.\n'
printf 'Combined evidence: %s\n' "$FINAL_ARCHIVE"
printf 'SHA-256: %s.sha256\n' "$FINAL_ARCHIVE"
printf 'Prepare: false\nCommit: false\nInstallation: false\nRuntime validation: false\n'
