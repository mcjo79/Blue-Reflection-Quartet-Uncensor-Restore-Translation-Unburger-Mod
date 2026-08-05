#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
PROJECT="$(cd -- "$SCRIPT_DIR/../.." && pwd -P)"
GAME="${BR_QUARTET_GAME_ROOT:-}"

usage() {
  cat <<'EOF'
Usage:
  82_run_bkn_dry_canonical_payload_preview_evidence.sh --game-dir <quartet-installation>

Alternatively set BR_QUARTET_GAME_ROOT to the Quartet installation directory.
The project root is derived from this script's repository location.
EOF
}

while (($#)); do
  case "$1" in
    --game-dir)
      (($# >= 2)) || {
        echo "ERROR: --game-dir requires a directory argument" >&2
        usage >&2
        exit 2
      }
      GAME="$2"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "ERROR: unsupported argument: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

[[ -n "$GAME" ]] || {
  echo "ERROR: Quartet installation directory is required" >&2
  echo "Pass --game-dir <directory> or set BR_QUARTET_GAME_ROOT." >&2
  exit 2
}
[[ -d "$GAME" ]] || {
  echo "ERROR: Quartet installation directory does not exist: $GAME" >&2
  exit 1
}
GAME="$(cd -- "$GAME" && pwd -P)"

[[ -f "$PROJECT/workstreams/quartet_legacy_dlc/VERSION" ]] || {
  echo "ERROR: unable to derive the Blue Reflection project root from the script location" >&2
  exit 1
}
[[ -d "$PROJECT/Blue_Reflection_Patcher" ]] || {
  echo "ERROR: canonical patcher source is missing under the derived project root" >&2
  exit 1
}

OUT_BASE="${BR_EVIDENCE_OUT:-$PROJECT/.local/reports/quartet_legacy_dlc}"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
OUT="$OUT_BASE/BR_QUARTET_DLC_BKN_CANONICAL_PAYLOAD_PREVIEW_$STAMP"
PATCHER="$PROJECT/.local/build/patcher/blue-reflection-patcher-linux-x86_64"
mkdir -p "$OUT" "$(dirname "$PATCHER")"

[[ "$(tr -d '[:space:]' < "$PROJECT/workstreams/core/VERSION")" == "0.0.42" ]] || {
  echo "ERROR: core 0.0.42 is required" >&2
  exit 1
}

(
  cd "$PROJECT/Blue_Reflection_Patcher"
  go test ./internal/plan/payloadpreview -count=1 -v
) | tee "$OUT/PAYLOADPREVIEW_GO_TESTS.txt"

(
  cd "$PROJECT/Blue_Reflection_Patcher"
  go build -o "$PATCHER" ./cmd/brpatcher
)

"$PATCHER" payload-preview \
  --game-dir "$GAME" \
  --modules quartet_legacy_dlc \
  --no-prompt \
  --project-root "$PROJECT" \
  --json "$OUT/PAYLOAD_PREVIEW.json" \
  | tee "$OUT/PAYLOAD_PREVIEW.txt"

python3 - "$OUT/PAYLOAD_PREVIEW.json" "$OUT/VALIDATION.json" <<'PY_VALIDATE'
import json,sys
src,out=sys.argv[1:]
d=json.load(open(src,encoding='utf-8'))
expected={
 'Data/PACK10_02.PAK': {
  'source_bytes':11417346202,
  'source_sha256':'d1540211904948efd9edb0580094f70bfbc1b6b98f32a66c814ee9e1f3f1d9ef',
  'target_bytes':11402829898,
  'target_sha256':'e798f39c3bcdbb11381197bddf9bd3ad8de6ccf5d7c0c78b22613046d47f5302',
 },
 'Data/PACK12.PAK': {
  'source_bytes':26124657,
  'source_sha256':'68a360c58f30ac00721b6ed8f513c9d02f01cf15c5ef6f1772fe1102ec2ad139',
  'target_bytes':26124649,
  'target_sha256':'a108a22dd59116e79cf0fabcffd5d0427f72e13de267318869431d28717404f4',
 },
}
errors=[]
if d.get('commit_enabled') is not False: errors.append('CommitEnabled is not false')
if d.get('status')!='ready': errors.append(f"preview status={d.get('status')}")
targets=d.get('targets',[])
if len(targets)!=1: errors.append(f'target_count={len(targets)}')
mods=[]
if targets:
 t=targets[0]
 if t.get('target_id')!='blue_reflection_quartet': errors.append(f"target_id={t.get('target_id')}")
 if t.get('ready_artifact_count')!=2: errors.append(f"ready_artifact_count={t.get('ready_artifact_count')}")
 if t.get('pending_module_count')!=0: errors.append(f"pending_module_count={t.get('pending_module_count')}")
 mods=t.get('modules',[])
if len(mods)!=1: errors.append(f'module_count={len(mods)}')
arts=[]
if mods:
 m=mods[0]
 if m.get('module_id')!='quartet_legacy_dlc': errors.append(f"module_id={m.get('module_id')}")
 if m.get('source_kind')!='validated_quartet_legacy_dlc_handoff': errors.append(f"source_kind={m.get('source_kind')}")
 if m.get('ready') is not True: errors.append('module not ready')
 arts=m.get('artifacts',[])
if len(arts)!=2: errors.append(f'artifact_count={len(arts)}')
seen=set()
for a in arts:
 path=a.get('relative_path'); seen.add(path)
 exp=expected.get(path)
 if exp is None:
  errors.append(f'unexpected artifact {path}')
  continue
 for k,v in exp.items():
  if a.get(k)!=v: errors.append(f'{path} {k}={a.get(k)} expected={v}')
 if a.get('report_verified') is not True: errors.append(f'{path} report not verified')
 if a.get('transaction_ready') is not True: errors.append(f'{path} not all-or-none ready')
 if a.get('status')!='ready': errors.append(f'{path} status={a.get("status")}')
if seen != set(expected): errors.append(f'artifact paths={sorted(seen)}')
result={
 'type':'br_quartet_legacy_dlc_core_patch_return_validation',
 'format_version':1,
 'status':'pass' if not errors else 'fail',
 'commit_enabled':d.get('commit_enabled'),
 'transaction_function_called':False,
 'source_kind':'validated_quartet_legacy_dlc_handoff',
 'artifact_count':len(arts),
 'artifact_paths':sorted(seen),
 'all_or_none_ready':not errors,
 'production_candidate_and_baseline_hashes_reverified':not errors,
 'errors':errors,
}
json.dump(result,open(out,'w',encoding='utf-8'),indent=2); open(out,'a').write('\n')
if errors:
 for e in errors: print('ERROR:',e,file=sys.stderr)
 sys.exit(1)
PY_VALIDATE

cp "$PROJECT/workstreams/quartet_legacy_dlc/DLC_BKN_DRY_CORE_RETURN_ACCEPTANCE.json" "$OUT/"
cp "$PROJECT/workstreams/quartet_legacy_dlc/DLC_BKN_DRY_CORE_RETURN_CONTRACT_CHECK.tsv" "$OUT/"

python3 - "$OUT" <<'PY_MANIFEST'
import hashlib,json,os,sys
root=sys.argv[1]
files=[]
for name in sorted(os.listdir(root)):
 p=os.path.join(root,name)
 if not os.path.isfile(p) or name=='REPORT_MANIFEST.json': continue
 with open(p,'rb') as f: b=f.read()
 files.append({'path':name,'size':len(b),'sha256':hashlib.sha256(b).hexdigest()})
json.dump({'type':'br_report_manifest','format_version':1,'files':files},open(os.path.join(root,'REPORT_MANIFEST.json'),'w'),indent=2); open(os.path.join(root,'REPORT_MANIFEST.json'),'a').write('\n')
PY_MANIFEST

tar --zstd -cf "$OUT.tar.zst" -C "$(dirname "$OUT")" "$(basename "$OUT")"
(cd "$(dirname "$OUT.tar.zst")" && sha256sum "$(basename "$OUT.tar.zst")" > "$(basename "$OUT.tar.zst").sha256")
printf 'Canonical payload-preview evidence: %s\n' "$OUT.tar.zst"
printf 'SHA-256 sidecar: %s\n' "$OUT.tar.zst.sha256"
