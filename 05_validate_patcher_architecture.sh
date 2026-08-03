#!/usr/bin/env bash
set -Eeuo pipefail

PROJECT_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PATHS_FILE="$PROJECT_ROOT/.local/paths.sh"
TOOL="$PROJECT_ROOT/Blue_Reflection_Text_Tool/br_distribution_tool.py"
PATCHER_ROOT="$PROJECT_ROOT/Blue_Reflection_Patcher"
MANIFEST="$PROJECT_ROOT/distribution/bundle/manifest.template.json"
REPORT_DIR="$PROJECT_ROOT/.local/reports"
BUILD_DIR="$PROJECT_ROOT/.local/build/patcher"
REPORT_JSON="$REPORT_DIR/BR_PC_PATCHER_ARCHITECTURE_VALIDATION.json"
REPORT_PACKAGE="$REPORT_DIR/BR_pc_patcher_architecture_validation.tar.zst"
DEVELOPMENT_BUNDLE="$BUILD_DIR/BlueReflection_Unburger_development.brpatch"
COMPILE_REPORT="$REPORT_DIR/BR_PATCHER_COMPILE_REPORT.tsv"
DETECTION_REPORT="$REPORT_DIR/BR_PATCHER_DETECTION_REPORT.json"
CWD_DETECTION_REPORT="$REPORT_DIR/BR_PATCHER_CWD_DETECTION_REPORT.json"
MODULE_SELECTION_REPORT="$REPORT_DIR/BR_PATCHER_MODULE_SELECTION_REPORT.json"
QUARTET_SELECTION_REPORT="$REPORT_DIR/BR_PATCHER_QUARTET_SELECTION_REPORT.json"
TRANSACTION_REPORT="$REPORT_DIR/BR_PATCHER_TRANSACTION_ENGINE_REPORT.json"
TRANSACTION_TEST_ROOT="$BUILD_DIR/transaction-self-test"
PAYLOAD_PREVIEW_REPORT="$REPORT_DIR/BR_PATCHER_LOCAL_PAYLOAD_PREVIEW_REPORT.json"
PAYLOAD_PREVIEW_TEST_ROOT="$BUILD_DIR/payload-preview-self-test"
COMPOSITION_PREVIEW_REPORT="$REPORT_DIR/BR_PATCHER_QUARTET_COMPOSITION_PREFLIGHT_REPORT.json"
COMPOSITION_PREVIEW_TEST_ROOT="$BUILD_DIR/quartet-composition-preflight-self-test"

fail() {
  printf 'ERROR: %s\n' "$*" >&2
  exit 1
}

for cmd in python3 tar zstd sha256sum; do
  command -v "$cmd" >/dev/null 2>&1 || fail "$cmd is required"
done
[[ -f "$PATHS_FILE" ]] || fail "Missing local path configuration: $PATHS_FILE"
[[ -f "$TOOL" ]] || fail "Distribution validator is missing: $TOOL"
[[ -f "$MANIFEST" ]] || fail "Bundle manifest template is missing: $MANIFEST"

# shellcheck source=/dev/null
source "$PATHS_FILE"

mkdir -p -- "$REPORT_DIR" "$BUILD_DIR"

python3 "$TOOL" validate \
  --project-root "$PROJECT_ROOT" \
  --manifest "$MANIFEST" \
  --output "$REPORT_JSON"

python3 "$TOOL" build-bundle \
  --manifest "$MANIFEST" \
  --output "$DEVELOPMENT_BUNDLE"

printf 'component\tstatus\tsha256\tpath\n' > "$COMPILE_REPORT"

if command -v go >/dev/null 2>&1; then
  (
    cd -- "$PATCHER_ROOT"
    module_path="$(go list -m)"
    [[ "$module_path" == "local/blue-reflection-patcher" ]] || fail "Unexpected Go module path: $module_path"
    printf 'Go module namespace: %s (local, not a repository URL)\n' "$module_path"
    go test ./...
    go build -trimpath -o "$BUILD_DIR/blue-reflection-patcher-linux-x86_64" ./cmd/brpatcher
    env GOOS=windows GOARCH=amd64 CGO_ENABLED=0 \
      go build -trimpath -o "$BUILD_DIR/blue-reflection-patcher-windows-x86_64.exe" ./cmd/brpatcher
  )

  for artifact in \
    "$BUILD_DIR/blue-reflection-patcher-linux-x86_64" \
    "$BUILD_DIR/blue-reflection-patcher-windows-x86_64.exe"
  do
    printf '%s\tok\t%s\t%s\n' \
      "$(basename -- "$artifact")" \
      "$(sha256sum -- "$artifact" | awk '{print $1}')" \
      "${artifact#"$PROJECT_ROOT"/}" \
      >> "$COMPILE_REPORT"
  done

  "$BUILD_DIR/blue-reflection-patcher-linux-x86_64" detect \
    --root "$BR1_ORIGINAL_ROOT" \
    --root "$BR1_QUARTET_ROOT" \
    --root "$BR_SECOND_LIGHT_ROOT" \
    --json "$DETECTION_REPORT"

  python3 - "$DETECTION_REPORT" <<'PY'
import json
import sys
from pathlib import Path

path = Path(sys.argv[1])
data = json.loads(path.read_text(encoding="utf-8"))
expected = {
    "blue_reflection_original",
    "blue_reflection_quartet",
    "second_light_original",
}
found = {item["target_id"] for item in data}
if found != expected:
    raise SystemExit(f"Detection mismatch: expected {sorted(expected)}, found {sorted(found)}")
print("Detected all three configured PC installations.")
PY

  (
    cd -- "$BR1_ORIGINAL_ROOT"
    "$BUILD_DIR/blue-reflection-patcher-linux-x86_64" detect \
      --json "$CWD_DETECTION_REPORT"
  )

  python3 - "$CWD_DETECTION_REPORT" <<'PY'
import json
import sys
from pathlib import Path

path = Path(sys.argv[1])
data = json.loads(path.read_text(encoding="utf-8"))
if len(data) != 1 or data[0].get("target_id") != "blue_reflection_original":
    raise SystemExit(f"Current-directory detection mismatch: {data!r}")
if data[0].get("source") != "current_directory":
    raise SystemExit(f"Unexpected detection source: {data[0].get('source')!r}")
if data[0].get("confidence") != "structural_files":
    raise SystemExit(f"Unexpected confidence: {data[0].get('confidence')!r}")
if "steam_app_id" in data[0] or "build_id" in data[0]:
    raise SystemExit("Store metadata leaked into structural detection output")
print("Current-directory, store-independent identification is valid.")
PY

  (
    cd -- "$BR1_ORIGINAL_ROOT"
    "$BUILD_DIR/blue-reflection-patcher-linux-x86_64" start \
      --no-prompt \
      --json "$MODULE_SELECTION_REPORT"
  )

  "$BUILD_DIR/blue-reflection-patcher-linux-x86_64" start \
    --game-dir "$BR1_QUARTET_ROOT" \
    --no-prompt \
    --json "$QUARTET_SELECTION_REPORT"

  python3 - "$MODULE_SELECTION_REPORT" "$QUARTET_SELECTION_REPORT" "$MANIFEST" "$PATCHER_ROOT/internal/plan/catalog/catalog.json" <<'PYSEL'
import json
import sys
from pathlib import Path

br1 = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
quartet = json.loads(Path(sys.argv[2]).read_text(encoding="utf-8"))
manifest = json.loads(Path(sys.argv[3]).read_text(encoding="utf-8"))
catalog = json.loads(Path(sys.argv[4]).read_text(encoding="utf-8"))

if br1.get("type") != "br_module_selection" or br1.get("mode") != "defaults":
    raise SystemExit(f"Unexpected BR1 selection envelope: {br1!r}")
if len(br1.get("targets", [])) != 1:
    raise SystemExit(f"Unexpected BR1 target count: {br1!r}")
br1_target = br1["targets"][0]
if br1_target.get("target_id") != "blue_reflection_original":
    raise SystemExit(f"Unexpected BR1 target: {br1_target!r}")
if br1_target.get("selected_module_ids") != ["blue_reflection_translation"]:
    raise SystemExit(f"Unexpected BR1 defaults: {br1_target!r}")
if [m["module_id"] for m in br1_target.get("available_modules", [])] != ["blue_reflection_translation"]:
    raise SystemExit(f"Unexpected BR1 available modules: {br1_target!r}")

q_target = quartet["targets"][0]
if q_target.get("target_id") != "blue_reflection_quartet":
    raise SystemExit(f"Unexpected Quartet target: {q_target!r}")
if q_target.get("selected_module_ids") != ["blue_reflection_translation", "quartet_restoration"]:
    raise SystemExit(f"Unexpected default Quartet selection: {q_target!r}")
expected_q = {"blue_reflection_translation", "quartet_restoration", "quartet_legacy_dlc"}
found_q = {m["module_id"] for m in q_target.get("available_modules", [])}
if found_q != expected_q:
    raise SystemExit(f"Unexpected Quartet module catalog: {sorted(found_q)}")

manifest_modules = {m["module_id"]: m for m in manifest["modules"]}
catalog_modules = {m["module_id"]: m for m in catalog["modules"]}
if manifest_modules != catalog_modules:
    raise SystemExit("Embedded module catalog diverges from the development bundle manifest")
print("Target-aware defaults, Quartet translation/restoration defaults, and embedded catalog parity are valid.")
PYSEL

  rm -rf -- "$TRANSACTION_TEST_ROOT"
  mkdir -p -- "$TRANSACTION_TEST_ROOT"
  "$BUILD_DIR/blue-reflection-patcher-linux-x86_64" transaction-self-test \
    --work-dir "$TRANSACTION_TEST_ROOT" \
    --json "$TRANSACTION_REPORT"

  python3 - "$TRANSACTION_REPORT" <<'PYTX'
import json
import sys
from pathlib import Path

report = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
required = {
    "prepared_without_game_edit": True,
    "existing_file_committed": True,
    "new_file_committed": True,
    "original_file_restored": True,
    "added_file_removed": True,
    "final_journal_status": "rolled_back",
}
if report.get("status") != "ok":
    raise SystemExit(f"Transaction engine report is not ok: {report!r}")
for key, value in required.items():
    if report.get(key) != value:
        raise SystemExit(f"Transaction invariant failed for {key}: {report!r}")
print("Transactional prepare, commit, backup and rollback are valid on isolated synthetic files.")
PYTX

  rm -rf -- "$PAYLOAD_PREVIEW_TEST_ROOT"
  mkdir -p -- "$PAYLOAD_PREVIEW_TEST_ROOT/project/workstreams/core" \
    "$PAYLOAD_PREVIEW_TEST_ROOT/project/Blue_Reflection_Patcher" \
    "$PAYLOAD_PREVIEW_TEST_ROOT/game/DATA"
  printf '0.0.22\n' > "$PAYLOAD_PREVIEW_TEST_ROOT/project/workstreams/core/VERSION"
  printf 'module synthetic/payload-preview\n' > "$PAYLOAD_PREVIEW_TEST_ROOT/project/Blue_Reflection_Patcher/go.mod"

  python3 - "$PAYLOAD_PREVIEW_TEST_ROOT" <<'PYPAYLOADBUILD'
import hashlib
import json
import sys
from pathlib import Path

root = Path(sys.argv[1])
project = root / "project"
game = root / "game"
artifacts = {
    "DATA/PACK01.PAK": b"verified-translation-event",
    "DATA/PACK02_1.PAK": b"verified-translation-text",
    "DATA/PACK00_04_1.PAK": b"verified-title-marker",
}
archives = []
for relative, payload in artifacts.items():
    output = project / ".local/build/translation/archives/blue_reflection_original" / relative
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(payload)
    target = game / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(("stock-" + relative).encode("utf-8"))
    archives.append({
        "target_id": "blue_reflection_original",
        "archive_relative_path": relative,
        "output_path": output.relative_to(project).as_posix(),
        "output_sha256": hashlib.sha256(payload).hexdigest(),
        "output_bytes": len(payload),
        "failures": [],
    })
report = {"status": "ok", "archives": archives}
report_path = project / ".local/reports/translation/BR_TRANSLATION_PAK_REPACK_REPORT.json"
report_path.parent.mkdir(parents=True, exist_ok=True)
report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
PYPAYLOADBUILD

  "$BUILD_DIR/blue-reflection-patcher-linux-x86_64" payload-preview \
    --game-dir "$PAYLOAD_PREVIEW_TEST_ROOT/game" \
    --modules blue_reflection_translation \
    --no-prompt \
    --project-root "$PAYLOAD_PREVIEW_TEST_ROOT/project" \
    --json "$PAYLOAD_PREVIEW_REPORT"

  python3 - "$PAYLOAD_PREVIEW_REPORT" <<'PYPAYLOADCHECK'
import json
import sys
from pathlib import Path

preview = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
if preview.get("type") != "br_local_payload_transaction_preview":
    raise SystemExit(f"Unexpected payload preview type: {preview!r}")
if preview.get("status") != "ready" or preview.get("commit_enabled") is not False:
    raise SystemExit(f"Payload preview is not safe and ready: {preview!r}")
targets = preview.get("targets", [])
if len(targets) != 1 or targets[0].get("ready_artifact_count") != 3:
    raise SystemExit(f"Unexpected payload preview targets: {targets!r}")
modules = targets[0].get("modules", [])
if len(modules) != 1 or not modules[0].get("ready"):
    raise SystemExit(f"Translation module is not preview-ready: {modules!r}")
for artifact in modules[0].get("artifacts", []):
    if not artifact.get("report_verified") or not artifact.get("transaction_ready"):
        raise SystemExit(f"Unverified artifact entered the preview: {artifact!r}")
    if artifact.get("desired_action") != "replace":
        raise SystemExit(f"Unexpected synthetic desired action: {artifact!r}")
print("Verified local translation archives and title marker are connected to a non-destructive transaction preview.")
PYPAYLOADCHECK

  rm -rf -- "$COMPOSITION_PREVIEW_TEST_ROOT"
  mkdir -p -- "$COMPOSITION_PREVIEW_TEST_ROOT/project/workstreams/core" \
    "$COMPOSITION_PREVIEW_TEST_ROOT/project/Blue_Reflection_Patcher" \
    "$COMPOSITION_PREVIEW_TEST_ROOT/game/Data"
  printf '0.0.23\n' > "$COMPOSITION_PREVIEW_TEST_ROOT/project/workstreams/core/VERSION"
  printf 'module synthetic/quartet-composition\n' > "$COMPOSITION_PREVIEW_TEST_ROOT/project/Blue_Reflection_Patcher/go.mod"

  python3 - "$COMPOSITION_PREVIEW_TEST_ROOT" <<'PYCOMPOSEBUILD'
import hashlib
import json
import sys
from pathlib import Path

root = Path(sys.argv[1])
project = root / "project"
game = root / "game"
stock = {
    "Data/PACK00_04_01.PAK": b"stock-title",
    "Data/PACK10_01.PAK": b"stock-shader",
    "Data/PACK11.PAK": b"stock-event",
    "Data/PACK12.PAK": b"stock-text",
}
for relative, payload in stock.items():
    path = game / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)

translation = {
    "Data/PACK00_04_01.PAK": b"translation-title",
    "Data/PACK11.PAK": b"translation-event",
    "Data/PACK12.PAK": b"translation-text",
}
archives = []
for relative, payload in translation.items():
    output = project / ".local/build/translation/archives/blue_reflection_quartet" / relative
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(payload)
    archives.append({
        "target_id": "blue_reflection_quartet",
        "archive_relative_path": relative,
        "output_path": output.relative_to(project).as_posix(),
        "output_sha256": hashlib.sha256(payload).hexdigest(),
        "output_bytes": len(payload),
        "failures": [],
    })
repack = project / ".local/reports/translation/BR_TRANSLATION_PAK_REPACK_REPORT.json"
repack.parent.mkdir(parents=True, exist_ok=True)
repack.write_text(json.dumps({"status": "ok", "archives": archives}, indent=2) + "\n", encoding="utf-8")

loose = project / ".local/reports/translation/BR_TRANSLATION_LOOSE_BUILD_REPORT.json"
loose.write_text(json.dumps({
    "status": "ok",
    "targets": {
        "blue_reflection_quartet": {
            "files": [{
                "archive_relative_path": "Data/PACK11.PAK",
                "internal_path": "event/b1/event_en/test.ebm",
                "changed": True,
            }]
        }
    },
}, indent=2) + "\n", encoding="utf-8")

profile_payload = b"runtime-validated-restoration-profile"
profile_rel = ".local/build/quartet_restoration/synthetic/runtime_profile/Data/PACK11.PAK"
profile_path = project / profile_rel
profile_path.parent.mkdir(parents=True, exist_ok=True)
profile_path.write_bytes(profile_payload)
manifest = {
    "schema_version": 1,
    "profile_id": "synthetic_runtime_validated_profile",
    "target_relative_path": "Data/PACK11.PAK",
    "baseline_sha256": hashlib.sha256(stock["Data/PACK11.PAK"]).hexdigest(),
    "baseline_size": len(stock["Data/PACK11.PAK"]),
    "profile_sha256": hashlib.sha256(profile_payload).hexdigest(),
    "profile_size": len(profile_payload),
    "local_profile_path": profile_rel,
    "changed_member_count": 1,
    "changed_members": ["event/b1/event_jp/test.ebd"],
    "runtime_validated": True,
    "workstream_id": "quartet_restoration",
    "workstream_version": "0.0.76-synthetic",
}
manifest_path = project / ".local/build/quartet_restoration/core_profiles/synthetic_runtime_validated_profile.json"
manifest_path.parent.mkdir(parents=True, exist_ok=True)
manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
PYCOMPOSEBUILD

  "$BUILD_DIR/blue-reflection-patcher-linux-x86_64" quartet-composition-preview \
    --game-dir "$COMPOSITION_PREVIEW_TEST_ROOT/game" \
    --project-root "$COMPOSITION_PREVIEW_TEST_ROOT/project" \
    --json "$COMPOSITION_PREVIEW_REPORT"

  python3 - "$COMPOSITION_PREVIEW_REPORT" <<'PYCOMPOSECHECK'
import json
import sys
from pathlib import Path

preview = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
if preview.get("type") != "br_quartet_translation_restoration_composition_preflight":
    raise SystemExit(f"Unexpected composition preview type: {preview!r}")
if preview.get("status") != "ready_for_composition_build" or preview.get("commit_enabled") is not False:
    raise SystemExit(f"Composition preflight is not safe and ready: {preview!r}")
if preview.get("production_eligible_count") != 1:
    raise SystemExit(f"Runtime-validated profile did not enter the production set: {preview!r}")
profiles = preview.get("profiles", [])
if len(profiles) != 1 or not profiles[0].get("production_eligible"):
    raise SystemExit(f"Unexpected composition profile result: {profiles!r}")
if profiles[0].get("translation_conflicts"):
    raise SystemExit(f"Disjoint translation/restoration members were reported as conflicting: {profiles[0]!r}")
archives = {item["archive_relative_path"]: item for item in preview.get("archives", [])}
pack11 = archives.get("Data/PACK11.PAK")
if not pack11 or pack11.get("status") != "ready_for_member_overlay":
    raise SystemExit(f"PACK11 member-overlay plan is not ready: {archives!r}")
if pack11.get("base_source_kind") != "verified_translation_archive" or pack11.get("overlay_member_count") != 1:
    raise SystemExit(f"PACK11 composition base/overlay is wrong: {pack11!r}")
print("Quartet translation/restoration inputs are conflict-checked at member level without composing or modifying a game archive.")
PYCOMPOSECHECK

  "$BUILD_DIR/blue-reflection-patcher-linux-x86_64" inspect-bundle \
    --bundle "$DEVELOPMENT_BUNDLE" >/dev/null
  "$BUILD_DIR/blue-reflection-patcher-linux-x86_64" plan \
    --bundle "$DEVELOPMENT_BUNDLE" \
    --root "$BR1_ORIGINAL_ROOT" \
    --root "$BR1_QUARTET_ROOT" \
    --root "$BR_SECOND_LIGHT_ROOT" \
    --json "$REPORT_DIR/BR_PATCHER_DEVELOPMENT_PLAN.json"
else
  printf 'go\tskipped\t-\tGo compiler not installed; source validation only\n' \
    >> "$COMPILE_REPORT"
  printf 'WARNING: Go is not installed; cross-platform binaries were not rebuilt locally.\n' >&2
fi

printf 'development_bundle\tok\t%s\t%s\n' \
  "$(sha256sum -- "$DEVELOPMENT_BUNDLE" | awk '{print $1}')" \
  "${DEVELOPMENT_BUNDLE#"$PROJECT_ROOT"/}" \
  >> "$COMPILE_REPORT"

rm -f -- "$REPORT_PACKAGE"
package_files=(
  config/project_version
  config/modules.tsv
  config/series_targets.tsv
  distribution/bundle/manifest.template.json
  .local/reports/BR_PC_PATCHER_ARCHITECTURE_VALIDATION.json
  .local/reports/BR_PATCHER_COMPILE_REPORT.tsv
)
[[ -f "$DETECTION_REPORT" ]] && package_files+=(.local/reports/BR_PATCHER_DETECTION_REPORT.json)
[[ -f "$CWD_DETECTION_REPORT" ]] && package_files+=(.local/reports/BR_PATCHER_CWD_DETECTION_REPORT.json)
[[ -f "$MODULE_SELECTION_REPORT" ]] && package_files+=(.local/reports/BR_PATCHER_MODULE_SELECTION_REPORT.json)
[[ -f "$QUARTET_SELECTION_REPORT" ]] && package_files+=(.local/reports/BR_PATCHER_QUARTET_SELECTION_REPORT.json)
[[ -f "$TRANSACTION_REPORT" ]] && package_files+=(.local/reports/BR_PATCHER_TRANSACTION_ENGINE_REPORT.json)
[[ -f "$PAYLOAD_PREVIEW_REPORT" ]] && package_files+=(.local/reports/BR_PATCHER_LOCAL_PAYLOAD_PREVIEW_REPORT.json)
[[ -f "$COMPOSITION_PREVIEW_REPORT" ]] && package_files+=(.local/reports/BR_PATCHER_QUARTET_COMPOSITION_PREFLIGHT_REPORT.json)
[[ -f "$REPORT_DIR/BR_PATCHER_DEVELOPMENT_PLAN.json" ]] && package_files+=(.local/reports/BR_PATCHER_DEVELOPMENT_PLAN.json)

tar -C "$PROJECT_ROOT" --zstd -cf "$REPORT_PACKAGE" "${package_files[@]}"

printf '\nValidated unified Windows/Linux patcher architecture.\n'
printf 'The guided installer still does not modify configured game files.\n'
printf 'The transaction engine, local payload preview and Quartet composition preflight were validated on isolated synthetic files.\n'
printf 'Created report package:\n  %s\n' "$REPORT_PACKAGE"
