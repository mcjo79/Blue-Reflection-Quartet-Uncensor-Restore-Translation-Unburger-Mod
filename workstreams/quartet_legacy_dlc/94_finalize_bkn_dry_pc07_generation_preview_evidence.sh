#!/usr/bin/env bash
set -Eeuo pipefail

usage() {
  cat <<'EOF'
Usage:
  94_finalize_bkn_dry_pc07_generation_preview_evidence.sh [--evidence-dir PATH]

Finalizes an already-built PC07 generation-8 evidence directory whose only
failure is the stage-93 generation-number validation typo. It does not rebuild
PAKs, republish ACTIVE.json, call transaction Prepare/Commit, install files, or
write to a game installation.
EOF
}

fail() {
  printf 'ERROR: %s\n' "$*" >&2
  exit 1
}

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="${BR_PROJECT_ROOT:-$(cd -- "$SCRIPT_DIR/../.." && pwd)}"
EVIDENCE_DIR=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --evidence-dir)
      [[ $# -ge 2 ]] || fail "--evidence-dir requires a value"
      EVIDENCE_DIR="$2"
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
[[ "$(tr -d '\r\n' < "$PROJECT_ROOT/workstreams/quartet_legacy_dlc/VERSION")" == "0.0.53" ]] || fail "quartet_legacy_dlc 0.0.53 is required"

REPORTS="$PROJECT_ROOT/.local/reports/quartet_legacy_dlc"
[[ -d "$REPORTS" ]] || fail "report directory is missing: $REPORTS"

if [[ -z "$EVIDENCE_DIR" ]]; then
  mapfile -d '' candidates < <(
    find "$REPORTS" -maxdepth 1 -mindepth 1 -type d \
      -name 'BR_QUARTET_DLC_BKN_DRY_PC07_GENERATION_PREVIEW_*' \
      -printf '%T@ %p\0' | sort -z -nr
  )
  [[ ${#candidates[@]} -gt 0 ]] || fail "no PC07 generation-preview evidence directory was found"
  EVIDENCE_DIR="${candidates[0]#* }"
fi

EVIDENCE_DIR="$(realpath -e -- "$EVIDENCE_DIR")"
case "$EVIDENCE_DIR" in
  "$REPORTS"/BR_QUARTET_DLC_BKN_DRY_PC07_GENERATION_PREVIEW_*) ;;
  *) fail "evidence directory is outside the expected PC07 report scope: $EVIDENCE_DIR" ;;
esac
[[ ! -L "$EVIDENCE_DIR" ]] || fail "evidence directory must not be a symlink"

for command in python3 sha256sum tar zstd realpath; do
  command -v "$command" >/dev/null 2>&1 || fail "required command is missing: $command"
done

python3 - "$EVIDENCE_DIR" <<'PY'
import hashlib
import json
import pathlib
import re
import subprocess
import sys
import tempfile

root = pathlib.Path(sys.argv[1])
expected_members = [f"costume_pc{i:02d}_bkn" for i in range(8)]
required = [
    "ACTIVE_MANIFEST.json",
    "GENERATION_8_PUBLICATION.json",
    "GENERATION_8_EVIDENCE.json",
    "FINAL_VALIDATION.json",
    "CANDIDATE_REPORT/REPORT_MANIFEST.json",
    "CANDIDATE_REPORT/SUMMARY.json",
]
for rel in required:
    path = root / rel
    if not path.is_file() or path.is_symlink():
        raise SystemExit(f"missing or unsafe required file: {rel}")

def load(rel):
    return json.loads((root / rel).read_text(encoding="utf-8"))

manifest = load("ACTIVE_MANIFEST.json")
publication = load("GENERATION_8_PUBLICATION.json")
evidence = load("GENERATION_8_EVIDENCE.json")
old_validation = load("FINAL_VALIDATION.json")
summary = load("CANDIDATE_REPORT/SUMMARY.json")

if manifest.get("generation") != 8:
    raise SystemExit(f"ACTIVE generation is not 8: {manifest.get('generation')!r}")
if manifest.get("members") != expected_members:
    raise SystemExit("ACTIVE members mismatch")
if publication.get("status") != "pass" or publication.get("generation") != 8:
    raise SystemExit("generation-8 publication did not pass")
if publication.get("members") != expected_members:
    raise SystemExit("generation-8 publication members mismatch")
if evidence.get("generation") != 8 or evidence.get("members") != expected_members:
    raise SystemExit("generation-8 evidence mismatch")
if summary.get("content_ids") != expected_members:
    raise SystemExit("candidate summary members mismatch")
pre_fix_mode = old_validation.get("status") == "fail"
already_fixed_mode = (
    old_validation.get("status") == "pass"
    and old_validation.get("generation") == 8
    and old_validation.get("errors") == []
    and old_validation.get("all_or_none_ready") is True
)
if not pre_fix_mode and not already_fixed_mode:
    raise SystemExit("FINAL_VALIDATION.json is neither the expected pre-fix failure nor a valid finalized generation-8 report")
if pre_fix_mode and old_validation.get("errors") != ["ACTIVE generation is not 7"]:
    raise SystemExit(f"unexpected pre-fix validation errors: {old_validation.get('errors')!r}")
if old_validation.get("members") != expected_members:
    raise SystemExit("validation members mismatch")
if old_validation.get("artifact_paths") != ["Data/PACK10_02.PAK", "Data/PACK12.PAK"]:
    raise SystemExit("validation artifact paths mismatch")

archives = {
    "candidate": list(root.glob("BR_QUARTET_DLC_BKN_DRY_PC07_GENERATION_CANDIDATE_*.tar.zst")),
    "preview": list(root.glob("BR_QUARTET_LEGACY_DLC_MANIFEST_PREVIEW_*.tar.zst")),
}
for role, paths in archives.items():
    if len(paths) != 1:
        raise SystemExit(f"expected exactly one {role} archive, got {len(paths)}")
    path = paths[0]
    sidecar = pathlib.Path(str(path) + ".sha256")
    if not sidecar.is_file() or sidecar.is_symlink():
        raise SystemExit(f"missing or unsafe sidecar: {sidecar.name}")
    token = sidecar.read_text(encoding="utf-8").split()[0].lower()
    if not re.fullmatch(r"[0-9a-f]{64}", token):
        raise SystemExit(f"invalid sidecar digest: {sidecar.name}")
    actual = hashlib.sha256(path.read_bytes()).hexdigest()
    if actual != token:
        raise SystemExit(f"sidecar mismatch: {path.name}")

preview_archive = archives["preview"][0]
with tempfile.TemporaryDirectory(prefix="pc07-preview-") as td:
    subprocess.run(
        ["tar", "--zstd", "-xf", str(preview_archive), "-C", td],
        check=True,
        stdout=subprocess.DEVNULL,
    )
    validations = list(pathlib.Path(td).rglob("VALIDATION.json"))
    if len(validations) != 1:
        raise SystemExit(f"expected one preview VALIDATION.json, got {len(validations)}")
    preview_validation = json.loads(validations[0].read_text(encoding="utf-8"))

if preview_validation.get("status") != "pass":
    raise SystemExit("core canonical preview validation did not pass")
if preview_validation.get("artifact_paths") != ["Data/PACK10_02.PAK", "Data/PACK12.PAK"]:
    raise SystemExit("core canonical preview artifact paths mismatch")
for key in (
    "transaction_function_called",
    "transaction_prepare_called",
    "transaction_commit_called",
    "game_modified",
):
    if preview_validation.get(key) is not False:
        raise SystemExit(f"core canonical preview {key} is not false")

old_bytes = (root / "FINAL_VALIDATION.json").read_bytes()
old_hash = hashlib.sha256(old_bytes).hexdigest()
pre_fix = root / "FINAL_VALIDATION_PRE_FIX.json"
provenance_path = root / "FINAL_VALIDATION_FIX_PROVENANCE.json"
if pre_fix_mode:
    if pre_fix.exists():
        if hashlib.sha256(pre_fix.read_bytes()).hexdigest() != old_hash:
            raise SystemExit("existing FINAL_VALIDATION_PRE_FIX.json conflicts with current pre-fix report")
    else:
        pre_fix.write_bytes(old_bytes)
elif not pre_fix.is_file() or not provenance_path.is_file():
    raise SystemExit("already-fixed validation is missing pre-fix or provenance evidence")

result = {
    "type": "br_quartet_legacy_dlc_bkn_dry_pc07_generation_preview_validation",
    "format_version": 1,
    "status": "pass",
    "generation": 8,
    "members": expected_members,
    "artifact_count": 2,
    "artifact_paths": ["Data/PACK10_02.PAK", "Data/PACK12.PAK"],
    "all_or_none_ready": True,
    "commit_enabled": False,
    "transaction_function_called": False,
    "transaction_prepare_called": False,
    "transaction_commit_called": False,
    "candidate_installed": False,
    "profile_registered": False,
    "runtime_validated": False,
    "wet_variant_included": False,
    "game_modified": False,
    "errors": [],
}
new_bytes = (json.dumps(result, indent=2) + "\n").encode("utf-8")
new_hash = hashlib.sha256(new_bytes).hexdigest()
if pre_fix_mode:
    (root / "FINAL_VALIDATION.json").write_bytes(new_bytes)
elif hashlib.sha256(old_bytes).hexdigest() != new_hash:
    raise SystemExit("already-fixed FINAL_VALIDATION.json differs from the canonical finalized report")

provenance = {
    "type": "br_quartet_legacy_dlc_bkn_dry_pc07_final_validation_fix",
    "format_version": 1,
    "status": "pass",
    "reason": "stage-93 final validator compared the published generation 8 ACTIVE manifest against the stale expected value 7",
    "workstream_version": "0.0.53",
    "source_runner": "workstreams/quartet_legacy_dlc/93_run_bkn_dry_pc07_generation_preview_evidence.sh",
    "source_fix": {
        "expected_generation_before": 7,
        "expected_generation_after": 8,
    },
    "pre_fix_validation_sha256": hashlib.sha256(pre_fix.read_bytes()).hexdigest(),
    "post_fix_validation_sha256": new_hash,
    "candidate_rebuilt": False,
    "active_manifest_republished": False,
    "canonical_preview_rerun": False,
    "transaction_prepare_called": False,
    "transaction_commit_called": False,
    "candidate_installed": False,
    "runtime_validated": False,
    "game_modified": False,
}
if pre_fix_mode:
    provenance_path.write_text(json.dumps(provenance, indent=2) + "\n", encoding="utf-8")
else:
    existing_provenance = json.loads(provenance_path.read_text(encoding="utf-8"))
    if existing_provenance.get("status") != "pass" or existing_provenance.get("post_fix_validation_sha256") != new_hash:
        raise SystemExit("existing final-validation provenance is invalid")
print("PC07 generation-8 validation is finalized without rebuilding candidates or rerunning preview.")
PY

(
  cd -- "$EVIDENCE_DIR"
  rm -f -- SHA256SUMS
  find . -type f ! -name SHA256SUMS -print0 | LC_ALL=C sort -z | xargs -0 sha256sum > SHA256SUMS
  sha256sum -c SHA256SUMS
)

FINAL_ARCHIVE="$EVIDENCE_DIR.tar.zst"
TMP_ARCHIVE="$FINAL_ARCHIVE.tmp.$$"
rm -f -- "$TMP_ARCHIVE"
trap 'rm -f -- "$TMP_ARCHIVE"' EXIT

tar --sort=name --mtime='UTC 1970-01-01' --owner=0 --group=0 --numeric-owner \
  -C "$(dirname -- "$EVIDENCE_DIR")" -cf - "$(basename -- "$EVIDENCE_DIR")" \
  | zstd -T0 -19 -q -o "$TMP_ARCHIVE"
mv -f -- "$TMP_ARCHIVE" "$FINAL_ARCHIVE"
(
  cd -- "$(dirname -- "$FINAL_ARCHIVE")"
  sha256sum "$(basename -- "$FINAL_ARCHIVE")" > "$(basename -- "$FINAL_ARCHIVE").sha256"
  sha256sum -c "$(basename -- "$FINAL_ARCHIVE").sha256"
)
trap - EXIT

printf '\nPC07 generation-8 evidence finalized without rebuilding PAKs or rerunning canonical preview.\n'
printf 'Combined evidence: %s\n' "$FINAL_ARCHIVE"
printf 'SHA-256: %s.sha256\n' "$FINAL_ARCHIVE"
printf 'Prepare: false\nCommit: false\nInstallation: false\nRuntime validation: false\n'
