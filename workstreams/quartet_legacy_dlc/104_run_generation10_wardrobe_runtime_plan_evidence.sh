#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
PROJECT_ROOT="$(cd -- "$SCRIPT_DIR/../.." && pwd -P)"
GAME_DIR=""
OUTPUT_DIR="$PROJECT_ROOT/.local/reports/quartet_legacy_dlc"
RECORDS="$SCRIPT_DIR/runtime_payloads/bkn_dry_generation10/wardrobe_records.json"

fail(){ printf 'ERROR: %s\n' "$*" >&2; exit 2; }
sha(){ sha256sum "$1" | awk '{print $1}'; }

while (($#)); do
  case "$1" in
    --game-dir) GAME_DIR="${2:?}"; shift 2;;
    --output-dir) OUTPUT_DIR="${2:?}"; shift 2;;
    --records) RECORDS="${2:?}"; shift 2;;
    *) fail "unknown argument: $1";;
  esac
done
[[ -n "$GAME_DIR" ]] || fail "--game-dir is required"
[[ -f "$GAME_DIR/B1.dll" && ! -L "$GAME_DIR/B1.dll" ]] || fail "safe B1.dll not found"
[[ -f "$RECORDS" && ! -L "$RECORDS" ]] || fail "safe records manifest not found"

mkdir -p "$OUTPUT_DIR" "$PROJECT_ROOT/.local/reports/quartet_legacy_dlc"
ts="$(date -u +%Y%m%dT%H%M%SZ)"
work="$(mktemp -d "$PROJECT_ROOT/.local/reports/quartet_legacy_dlc/.stage104.XXXXXX")"
trap 'rm -rf -- "$work"' EXIT
ev="$work/BR_QUARTET_DLC_GENERATION10_WARDROBE_RUNTIME_PLAN_${ts}"
mkdir -p "$ev"

before_sha="$(sha "$GAME_DIR/B1.dll")"
before_size="$(stat -c %s "$GAME_DIR/B1.dll")"
before_mtime="$(stat -c %Y "$GAME_DIR/B1.dll")"

python3 "$SCRIPT_DIR/br_dlc_wardrobe_runtime_pipeline.py" plan \
  --project-root "$PROJECT_ROOT" \
  --game-dir "$GAME_DIR" \
  --records "$RECORDS" \
  --evidence-dir "$ev" >"$ev/PIPELINE.stdout.json" 2>"$ev/PIPELINE.stderr.txt"

after_sha="$(sha "$GAME_DIR/B1.dll")"
after_size="$(stat -c %s "$GAME_DIR/B1.dll")"
after_mtime="$(stat -c %Y "$GAME_DIR/B1.dll")"
[[ "$before_sha" == "$after_sha" && "$before_size" == "$after_size" && "$before_mtime" == "$after_mtime" ]] || fail "B1.dll changed during read-only plan"

python3 - "$ev" "$PROJECT_ROOT" "$before_sha" "$before_size" "$before_mtime" <<'PY'
import json, pathlib, sys
ev=pathlib.Path(sys.argv[1]); project=pathlib.Path(sys.argv[2])
s=json.load(open(ev/"SUMMARY.json"))
p=json.load(open(ev/"RUNTIME_PLAN.json"))
expected=list(range(56,64))
ok=(s.get("status")=="pass" and s.get("logical_indices")==expected and s.get("record_count")==8
    and s.get("final_record_count")==64 and s.get("patch_count")==38
    and s.get("existing_records_preserved") is True and s.get("global_show_all") is False
    and s.get("save_mutation_required") is False and s.get("runtime_attach_called") is False)
if not ok: raise SystemExit("stage104 Generation 10 contract failed")
out={
 "type":"br_quartet_dlc_generation10_runtime_plan_acceptance","format_version":1,
 "status":"generation10_runtime_plan_pass_ready_for_controlled_runtime_test_design",
 "capability":"wardrobe_registry_append_v1","logical_indices":expected,
 "record_count":8,"final_record_count":64,"profiled_patch_sites":38,
 "runtime_attach_called":False,"game_modified":False,"save_modified":False,
 "on_disk_b1_modified":False,"generation10_installed":False,
 "pc08_in_scope":False,"wet_bkn_in_scope":False,
 "core_version": (project/"workstreams/core/VERSION").read_text().strip() if (project/"workstreams/core/VERSION").is_file() else None,
 "quartet_legacy_dlc_version": (project/"workstreams/quartet_legacy_dlc/VERSION").read_text().strip(),
 "b1_before_after":{"sha256":sys.argv[3],"size":int(sys.argv[4]),"mtime":int(sys.argv[5])},
 "next_action":"design one controlled PAK transaction + runtime attach test; do not return to core unless semantic capability/module validation fails"
}
(ev/"ACCEPTANCE.json").write_text(json.dumps(out,indent=2)+"\n")
PY

(
  cd "$ev"
  find . -type f ! -name SHA256SUMS -print0 | sort -z | xargs -0 sha256sum > SHA256SUMS
)
archive="$OUTPUT_DIR/$(basename "$ev").tar.zst"
tar --zstd -cf "$archive" -C "$work" "$(basename "$ev")"
sha256sum "$archive" > "$archive.sha256"
printf '%s\n%s\n' "$archive" "$archive.sha256"
