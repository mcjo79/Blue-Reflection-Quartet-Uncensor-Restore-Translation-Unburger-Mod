#!/usr/bin/env bash
set -Eeuo pipefail

usage() {
  cat <<'EOF'
Usage:
  103_run_bkn_generation9_append_only_label_preview_evidence.sh \
    --game-dir PATH [--gust-pak PATH]

Builds a non-installed generation-9 append-only BKN label candidate, publishes
the DLC-owned generic ACTIVE.json, and runs the core-owned read-only canonical
preview. It never prepares or commits a transaction and never writes to the
game installation or saves.
EOF
}

fail() {
  printf 'ERROR: %s\n' "$*" >&2
  exit 1
}

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="${BR_PROJECT_ROOT:-$(cd -- "$SCRIPT_DIR/../.." && pwd)}"
QUARTET_ROOT="${BR_QUARTET_GAME_ROOT:-}"
GUST_PAK="${BR_GUST_PAK:-}"

while [[ $# -gt 0 ]]; do
  case "$1" in
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
[[ "$(tr -d '\r\n' < "$PROJECT_ROOT/workstreams/quartet_legacy_dlc/VERSION")" == "0.0.65" ]] || fail "quartet_legacy_dlc 0.0.65 is required"
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
  workstreams.quartet_legacy_dlc.tests.test_br_dlc_bkn_generation9_label_candidate_tool \
  workstreams.quartet_legacy_dlc.tests.test_br_dlc_bkn_generation9_publish_tool \
  workstreams.quartet_legacy_dlc.tests.test_br_dlc_bkn_generation9_core_capability_gate \
  workstreams.quartet_legacy_dlc.tests.test_br_dlc_bkn_generation9_idempotent_publication

REPORT_ROOT="$PROJECT_ROOT/.local/reports/quartet_legacy_dlc/bkn_dry_generation9_append_only_label_candidate_evidence"
python3 workstreams/quartet_legacy_dlc/br_dlc_bkn_generation9_label_candidate_tool.py audit \
  --project-root "$PROJECT_ROOT" \
  --quartet-root "$QUARTET_ROOT" \
  --gust-pak "$GUST_PAK" \
  --output-root "$REPORT_ROOT"

python3 workstreams/quartet_legacy_dlc/br_dlc_bkn_generation9_label_candidate_tool.py validate-report \
  --report-root "$REPORT_ROOT" >/dev/null

stamp="$(date -u +%Y%m%dT%H%M%SZ)"
CANDIDATE_ARCHIVE="$PROJECT_ROOT/.local/reports/quartet_legacy_dlc/BR_QUARTET_DLC_BKN_GENERATION9_APPEND_ONLY_LABEL_CANDIDATE_${stamp}.tar.zst"
python3 workstreams/quartet_legacy_dlc/br_dlc_bkn_generation9_label_candidate_tool.py bundle-report \
  --report-root "$REPORT_ROOT" \
  --output "$CANDIDATE_ARCHIVE" >/dev/null
(
  cd -- "$(dirname -- "$CANDIDATE_ARCHIVE")"
  sha256sum "$(basename -- "$CANDIDATE_ARCHIVE")" > "$(basename -- "$CANDIDATE_ARCHIVE").sha256"
  sha256sum -c "$(basename -- "$CANDIDATE_ARCHIVE").sha256"
)

ACTIVE="$PROJECT_ROOT/.local/reports/quartet_legacy_dlc/validated_payloads/ACTIVE.json"
[[ -f "$ACTIVE" && ! -L "$ACTIVE" ]] || fail "ACTIVE.json is missing or unsafe"
active_backup="$(mktemp)"
cp -- "$ACTIVE" "$active_backup"
restore_active() {
  if [[ -f "$active_backup" ]]; then
    cp -- "$active_backup" "$ACTIVE"
    rm -f -- "$active_backup"
  fi
}
trap 'restore_active' ERR INT TERM

python3 workstreams/quartet_legacy_dlc/br_dlc_bkn_generation9_publish_tool.py \
  --project-root "$PROJECT_ROOT" \
  --game-dir "$QUARTET_ROOT" \
  --report-root "$REPORT_ROOT" \
  > "$PROJECT_ROOT/.local/reports/quartet_legacy_dlc/GENERATION_9_PUBLICATION_STDOUT.json"

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

rm -f -- "$active_backup"
trap - ERR INT TERM

FINAL_ROOT="$PROJECT_ROOT/.local/reports/quartet_legacy_dlc/BR_QUARTET_DLC_BKN_GENERATION9_APPEND_ONLY_LABEL_PREVIEW_${stamp}"
rm -rf -- "$FINAL_ROOT"
mkdir -p "$FINAL_ROOT/CANDIDATE_REPORT"
cp -a -- "$REPORT_ROOT/." "$FINAL_ROOT/CANDIDATE_REPORT/"
cp -- "$CANDIDATE_ARCHIVE" "$FINAL_ROOT/"
cp -- "$CANDIDATE_ARCHIVE.sha256" "$FINAL_ROOT/"
cp -- "$PREVIEW_ARCHIVE" "$FINAL_ROOT/"
cp -- "$PREVIEW_ARCHIVE.sha256" "$FINAL_ROOT/"
cp -- "$ACTIVE" "$FINAL_ROOT/ACTIVE_MANIFEST.json"
cp -- "$PROJECT_ROOT/.local/reports/quartet_legacy_dlc/validated_payloads/GENERATION_9_PUBLICATION.json" "$FINAL_ROOT/GENERATION_9_PUBLICATION.json"
cp -- "$PROJECT_ROOT/.local/reports/quartet_legacy_dlc/generations/bkn_dry_generation_9/EVIDENCE.json" "$FINAL_ROOT/GENERATION_9_EVIDENCE.json"
cp -- "$PROJECT_ROOT/workstreams/quartet_legacy_dlc/DLC_BKN_SYNTHETIC_LABEL_SLOT_RETURN_ACCEPTANCE.json" "$FINAL_ROOT/"
cp -- "$PROJECT_ROOT/workstreams/core/VERSION" "$FINAL_ROOT/CORE_VERSION.txt"
cp -- "$PROJECT_ROOT/workstreams/quartet_legacy_dlc/VERSION" "$FINAL_ROOT/DLC_VERSION.txt"

python3 - "$FINAL_ROOT" "$PREVIEW_DIR" <<'PY'
import json, pathlib, sys
root = pathlib.Path(sys.argv[1])
preview_root = pathlib.Path(sys.argv[2])
manifest = json.loads((root / 'ACTIVE_MANIFEST.json').read_text())
publication = json.loads((root / 'GENERATION_9_PUBLICATION.json').read_text())
validation = json.loads((preview_root / 'VALIDATION.json').read_text())
summary = json.loads((root / 'CANDIDATE_REPORT/SUMMARY.json').read_text())
errors = []
expected_members = [f'costume_pc{i:02d}_bkn' for i in range(8)]
expected_changed = [
    'saves/b1/chara/charabase.xml',
    'saves/b1/text_en/str_costume.xml',
    'saves/b1/text_jp/str_costume.xml',
    'saves/b1/text_sc/str_costume.xml',
    'saves/b1/text_tc/str_costume.xml',
]
if manifest.get('generation') != 9: errors.append('ACTIVE generation is not 9')
if manifest.get('members') != expected_members: errors.append('ACTIVE members mismatch')
if manifest.get('artifacts', [{}, {}])[1].get('member_delta', {}).get('changed') != expected_changed:
    errors.append('PACK12 changed-member list mismatch')
if publication.get('status') != 'pass': errors.append('publication did not pass')
if publication.get('commit_enabled') is not False: errors.append('publication CommitEnabled is not false')
if validation.get('status') != 'pass': errors.append('core preview validation did not pass')
if validation.get('artifact_paths') != ['Data/PACK10_02.PAK', 'Data/PACK12.PAK']:
    errors.append('core preview artifact paths mismatch')
for key in ('transaction_function_called', 'transaction_prepare_called', 'transaction_commit_called', 'game_modified'):
    if validation.get(key) is not False: errors.append(f'{key} is not false')
if summary.get('existing_records_replaced') != 0: errors.append('candidate replaced an existing label record')
if summary.get('protected_quartet_rows_preserved') is not True: errors.append('protected Quartet rows were not preserved')
result = {
  'type': 'br_quartet_legacy_dlc_bkn_generation9_append_only_label_preview_validation',
  'format_version': 1,
  'status': 'pass' if not errors else 'fail',
  'generation': 9,
  'parent_generation': 8,
  'members': expected_members,
  'artifact_count': 2,
  'artifact_paths': ['Data/PACK10_02.PAK', 'Data/PACK12.PAK'],
  'all_or_none_ready': not errors,
  'append_only_string_no_start': 393339,
  'append_only_string_no_end': 393346,
  'existing_records_replaced': 0,
  'protected_quartet_rows_preserved': True,
  'commit_enabled': False,
  'transaction_function_called': False,
  'transaction_prepare_called': False,
  'transaction_commit_called': False,
  'candidate_installed': False,
  'profile_registered': False,
  'runtime_validated': False,
  'wet_variant_included': False,
  'game_modified': False,
  'save_modified': False,
  'errors': errors,
}
(root / 'FINAL_VALIDATION.json').write_text(json.dumps(result, indent=2) + '\n')
if errors:
    raise SystemExit('\n'.join(errors))
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

printf '\nGeneration 9 append-only BKN label candidate built and previewed without installation.\n'
printf 'Combined evidence: %s\n' "$FINAL_ARCHIVE"
printf 'SHA-256: %s.sha256\n' "$FINAL_ARCHIVE"
printf 'Prepare: false\nCommit: false\nInstallation: false\nRuntime validation: false\n'
