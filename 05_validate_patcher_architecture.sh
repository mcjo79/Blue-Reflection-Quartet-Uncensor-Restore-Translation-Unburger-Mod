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
COMPOSITION_BUILD_REPORT="$REPORT_DIR/BR_PATCHER_QUARTET_COMPOSITION_BUILD_REPORT.json"
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
  printf '0.0.24\n' > "$COMPOSITION_PREVIEW_TEST_ROOT/project/workstreams/core/VERSION"
  printf 'module synthetic/quartet-composition\n' > "$COMPOSITION_PREVIEW_TEST_ROOT/project/Blue_Reflection_Patcher/go.mod"

  GUST_PAK_BIN="${GUST_PAK:-$PROJECT_ROOT/.local/vendor/gust_tools/gust_pak}"
  [[ -f "$GUST_PAK_BIN" && -x "$GUST_PAK_BIN" ]] || fail "gust_pak is required for the composition build self-test: $GUST_PAK_BIN"

  python3 - "$COMPOSITION_PREVIEW_TEST_ROOT" "$GUST_PAK_BIN" <<'PYCOMPOSEBUILD'
import hashlib
import json
import subprocess
import sys
from pathlib import Path

root = Path(sys.argv[1])
gust_pak = Path(sys.argv[2])
project = root / "project"
game = root / "game"


def sha_size(path: Path) -> tuple[str, int]:
    data = path.read_bytes()
    return hashlib.sha256(data).hexdigest(), len(data)


def make_pak(stage: Path, name: str, members: dict[str, bytes]) -> Path:
    stage.mkdir(parents=True, exist_ok=True)
    for relative, payload in members.items():
        path = stage / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(payload)
    manifest = {
        "name": Path(name).stem + ".pak",
        "version": 131072,
        "header_size": 16,
        "flags": 0,
        "nb_files": len(members),
        "64-bit": True,
        "files": [
            {"name": relative, "key": "0" * 40}
            for relative in members
        ],
    }
    manifest_path = stage / (Path(name).stem + ".json")
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    subprocess.run(
        [str(gust_pak), manifest_path.name],
        cwd=stage,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        check=True,
    )
    paks = [path for path in stage.iterdir() if path.is_file() and path.suffix.lower() == ".pak"]
    if len(paks) != 1:
        raise SystemExit(f"Expected one synthetic PAK in {stage}, found {paks}")
    return paks[0]


baseline_members = {
    "event/b1/event_en/test.ebm": b"baseline-en-" * 200,
    "event/b1/event_jp/test.ebd": b"baseline-jp-" * 200,
    "event/b1/common/keep.bin": b"keep-" * 300,
}
translation_members = dict(baseline_members)
translation_members["event/b1/event_en/test.ebm"] = b"translated-en-" * 200
profile_members = dict(baseline_members)
profile_members["event/b1/event_jp/test.ebd"] = b"restored-jp-" * 200

baseline_pack11 = make_pak(root / "pak_sources/baseline_pack11", "PACK11.PAK", baseline_members)
translation_pack11 = make_pak(root / "pak_sources/translation_pack11", "PACK11.PAK", translation_members)
profile_pack11 = make_pak(root / "pak_sources/profile_pack11", "PACK11.PAK", profile_members)
translation_pack12 = make_pak(
    root / "pak_sources/translation_pack12",
    "PACK12.PAK",
    {"text/main.bin": b"translation-text-" * 300},
)
translation_title = make_pak(
    root / "pak_sources/translation_title",
    "PACK00_04_01.PAK",
    {"ui/title.bin": b"translation-title-" * 300},
)

(game / "Data/PACK11.PAK").write_bytes(baseline_pack11.read_bytes())
# Structural markers used for target detection. Unselected restoration archives
# need not be valid synthetic PAKs in this test.
(game / "Data/PACK10_01.PAK").write_bytes(b"synthetic-shader-marker")
(game / "Data/PACK10_03.PAK").write_bytes(b"synthetic-field-marker")
(game / "Data/PACK12.PAK").write_bytes(b"synthetic-text-marker")
(game / "Data/PACK00_04_01.PAK").write_bytes(b"synthetic-title-marker")

archives = []
for source, relative in (
    (translation_pack11, "Data/PACK11.PAK"),
    (translation_pack12, "Data/PACK12.PAK"),
    (translation_title, "Data/PACK00_04_01.PAK"),
):
    output = project / ".local/build/translation/archives/blue_reflection_quartet" / relative
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(source.read_bytes())
    digest, size = sha_size(output)
    archives.append({
        "target_id": "blue_reflection_quartet",
        "archive_relative_path": relative,
        "output_path": output.relative_to(project).as_posix(),
        "output_sha256": digest,
        "output_bytes": size,
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

profile_relative = ".local/build/quartet_restoration/synthetic/runtime_profile/Data/PACK11.PAK"
profile_path = project / profile_relative
profile_path.parent.mkdir(parents=True, exist_ok=True)
profile_path.write_bytes(profile_pack11.read_bytes())
baseline_sha, baseline_size = sha_size(game / "Data/PACK11.PAK")
profile_sha, profile_size = sha_size(profile_path)
manifest = {
    "schema_version": 1,
    "profile_id": "synthetic_runtime_validated_profile",
    "target_relative_path": "Data/PACK11.PAK",
    "baseline_sha256": baseline_sha,
    "baseline_size": baseline_size,
    "profile_sha256": profile_sha,
    "profile_size": profile_size,
    "local_profile_path": profile_relative,
    "changed_member_count": 1,
    "changed_members": ["event/b1/event_jp/test.ebd"],
    "runtime_validated": True,
    "workstream_id": "quartet_restoration",
    "workstream_version": "0.0.87-synthetic",
}
manifest_path = project / ".local/build/quartet_restoration/core_profiles/synthetic_runtime_validated_profile.json"
manifest_path.parent.mkdir(parents=True, exist_ok=True)
manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")

(root / "GAME_PACK11_SHA256_BEFORE").write_text(sha_size(game / "Data/PACK11.PAK")[0] + "\n", encoding="utf-8")
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
pack1003 = archives.get("Data/PACK10_03.PAK")
if not pack1003 or pack1003.get("status") != "not_selected":
    raise SystemExit(f"Unselected PACK10_03 should remain non-blocking: {pack1003!r}")
print("Quartet translation/restoration inputs are conflict-checked at member level without modifying a game archive.")
PYCOMPOSECHECK

  "$BUILD_DIR/blue-reflection-patcher-linux-x86_64" quartet-composition-build \
    --game-dir "$COMPOSITION_PREVIEW_TEST_ROOT/game" \
    --project-root "$COMPOSITION_PREVIEW_TEST_ROOT/project" \
    --gust-pak "$GUST_PAK_BIN" \
    --timeout 2m \
    --json "$COMPOSITION_BUILD_REPORT"

  python3 - "$COMPOSITION_BUILD_REPORT" "$COMPOSITION_PREVIEW_TEST_ROOT" "$GUST_PAK_BIN" <<'PYCOMPOSEVERIFY'
import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path

report = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
root = Path(sys.argv[2])
gust_pak = Path(sys.argv[3])
project = root / "project"
game = root / "game"
if report.get("type") != "br_quartet_translation_restoration_composition_build":
    raise SystemExit(f"Unexpected composition build type: {report!r}")
if report.get("status") != "ok" or report.get("commit_enabled") is not False:
    raise SystemExit(f"Composition build is not safe and complete: {report!r}")
if report.get("published_archive_count") != 3 or report.get("composed_archive_count") != 1:
    raise SystemExit(f"Unexpected composition build summary: {report!r}")
archives = {item["archive_relative_path"]: item for item in report.get("archives", [])}
pack11 = archives.get("Data/PACK11.PAK")
if not pack11 or not pack11.get("full_reextract_verified") or not pack11.get("manifest_declaration_checked"):
    raise SystemExit(f"PACK11 did not pass full composition verification: {pack11!r}")
output = project / ".local/build/composition/blue_reflection_quartet/Data/PACK11.PAK"
verify = root / "final_verify"
shutil.rmtree(verify, ignore_errors=True)
verify.mkdir(parents=True)
shutil.copy2(output, verify / output.name)
subprocess.run([str(gust_pak), output.name], cwd=verify, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
if (verify / "event/b1/event_en/test.ebm").read_bytes() != b"translated-en-" * 200:
    raise SystemExit("Composed PAK lost the translation member")
if (verify / "event/b1/event_jp/test.ebd").read_bytes() != b"restored-jp-" * 200:
    raise SystemExit("Composed PAK lost the restoration member")
if (verify / "event/b1/common/keep.bin").read_bytes() != b"keep-" * 300:
    raise SystemExit("Composed PAK changed an unrelated member")
current_game_hash = hashlib.sha256((game / "Data/PACK11.PAK").read_bytes()).hexdigest()
expected_game_hash = (root / "GAME_PACK11_SHA256_BEFORE").read_text(encoding="utf-8").strip()
if current_game_hash != expected_game_hash:
    raise SystemExit("Composition build modified the synthetic game installation")
print("Content-aware composer preserved translation, applied only the declared restoration member, fully re-extracted the result and left the game untouched.")
PYCOMPOSEVERIFY

  composed_hash_before="$(sha256sum -- "$COMPOSITION_PREVIEW_TEST_ROOT/project/.local/build/composition/blue_reflection_quartet/Data/PACK11.PAK" | awk '{print $1}')"
  python3 - "$COMPOSITION_PREVIEW_TEST_ROOT" "$GUST_PAK_BIN" <<'PYCOMPOSEBAD'
import hashlib
import json
import subprocess
import sys
from pathlib import Path

root = Path(sys.argv[1])
gust_pak = Path(sys.argv[2])
project = root / "project"
stage = root / "pak_sources/bad_profile_pack11"
stage.mkdir(parents=True, exist_ok=True)
members = {
    "event/b1/event_en/test.ebm": b"baseline-en-" * 200,
    "event/b1/event_jp/test.ebd": b"restored-jp-" * 200,
    "event/b1/common/keep.bin": b"undeclared-change-" * 200,
}
for relative, payload in members.items():
    path = stage / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)
manifest = {
    "name": "PACK11.pak",
    "version": 131072,
    "header_size": 16,
    "flags": 0,
    "nb_files": len(members),
    "64-bit": True,
    "files": [{"name": relative, "key": "0" * 40} for relative in members],
}
(stage / "PACK11.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
subprocess.run([str(gust_pak), "PACK11.json"], cwd=stage, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
bad_pak = next(path for path in stage.iterdir() if path.is_file() and path.suffix.lower() == ".pak")
profile_path = project / ".local/build/quartet_restoration/synthetic/runtime_profile/Data/PACK11.PAK"
profile_path.write_bytes(bad_pak.read_bytes())
profile_manifest = project / ".local/build/quartet_restoration/core_profiles/synthetic_runtime_validated_profile.json"
data = json.loads(profile_manifest.read_text(encoding="utf-8"))
payload = profile_path.read_bytes()
data["profile_sha256"] = hashlib.sha256(payload).hexdigest()
data["profile_size"] = len(payload)
# Deliberately keep changed_members restricted to event_jp/test.ebd.
profile_manifest.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
PYCOMPOSEBAD

  if "$BUILD_DIR/blue-reflection-patcher-linux-x86_64" quartet-composition-build \
      --game-dir "$COMPOSITION_PREVIEW_TEST_ROOT/game" \
      --project-root "$COMPOSITION_PREVIEW_TEST_ROOT/project" \
      --gust-pak "$GUST_PAK_BIN" \
      --timeout 2m >/dev/null 2>&1; then
    fail "Composer accepted a profile PAK with an undeclared changed member"
  fi
  composed_hash_after="$(sha256sum -- "$COMPOSITION_PREVIEW_TEST_ROOT/project/.local/build/composition/blue_reflection_quartet/Data/PACK11.PAK" | awk '{print $1}')"
  [[ "$composed_hash_after" == "$composed_hash_before" ]] || fail "Failed composition replaced the last verified local payload"

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
[[ -f "$COMPOSITION_BUILD_REPORT" ]] && package_files+=(.local/reports/BR_PATCHER_QUARTET_COMPOSITION_BUILD_REPORT.json)
[[ -f "$REPORT_DIR/BR_PATCHER_DEVELOPMENT_PLAN.json" ]] && package_files+=(.local/reports/BR_PATCHER_DEVELOPMENT_PLAN.json)

tar -C "$PROJECT_ROOT" --zstd -cf "$REPORT_PACKAGE" "${package_files[@]}"

printf '\nValidated unified Windows/Linux patcher architecture.\n'
printf 'The guided installer still does not modify configured game files.\n'
printf 'The transaction engine, local payload preview, Quartet composition preflight and content-aware composer were validated on isolated synthetic files.\n'
printf 'Created report package:\n  %s\n' "$REPORT_PACKAGE"
