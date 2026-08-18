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
TRANSACTION_PREPARE_REPORT="$REPORT_DIR/BR_PATCHER_TRANSACTION_PREPARE_REPORT.json"
TRANSACTION_STATUS_REPORT="$REPORT_DIR/BR_PATCHER_TRANSACTION_STATUS_REPORT.json"
TRANSACTION_DISCARD_REPORT="$REPORT_DIR/BR_PATCHER_TRANSACTION_DISCARD_REPORT.json"
TRANSACTION_INSTALL_PREPARE_REPORT="$REPORT_DIR/BR_PATCHER_TRANSACTION_INSTALL_PREPARE_REPORT.json"
TRANSACTION_COMMIT_REPORT="$REPORT_DIR/BR_PATCHER_TRANSACTION_COMMIT_REPORT.json"
TRANSACTION_ROLLBACK_REPORT="$REPORT_DIR/BR_PATCHER_TRANSACTION_ROLLBACK_REPORT.json"
INSTALLATION_ACTIVE_STATUS_REPORT="$REPORT_DIR/BR_PATCHER_INSTALLATION_ACTIVE_STATUS_REPORT.json"
INSTALLATION_ROLLED_BACK_STATUS_REPORT="$REPORT_DIR/BR_PATCHER_INSTALLATION_ROLLED_BACK_STATUS_REPORT.json"
GUIDED_INSTALL_SELECTION_REPORT="$REPORT_DIR/BR_PATCHER_GUIDED_INSTALL_SELECTION_REPORT.json"
GUIDED_INSTALL_PAYLOAD_REPORT="$REPORT_DIR/BR_PATCHER_GUIDED_INSTALL_PAYLOAD_REPORT.json"
GUIDED_INSTALL_STATUS_REPORT="$REPORT_DIR/BR_PATCHER_GUIDED_INSTALL_STATUS_REPORT.json"
GUIDED_INSTALL_TRANSACTION_REPORT="$REPORT_DIR/BR_PATCHER_GUIDED_INSTALL_TRANSACTION_REPORT.json"
GUIDED_LOCAL_BUILD_SELECTION_REPORT="$REPORT_DIR/BR_PATCHER_GUIDED_LOCAL_BUILD_SELECTION_REPORT.json"
GUIDED_LOCAL_BUILD_PAYLOAD_REPORT="$REPORT_DIR/BR_PATCHER_GUIDED_LOCAL_BUILD_PAYLOAD_REPORT.json"
GUIDED_LOCAL_BUILD_STATUS_REPORT="$REPORT_DIR/BR_PATCHER_GUIDED_LOCAL_BUILD_STATUS_REPORT.json"
GUIDED_LOCAL_BUILD_TRANSACTION_REPORT="$REPORT_DIR/BR_PATCHER_GUIDED_LOCAL_BUILD_TRANSACTION_REPORT.json"
BASELINE_STATUS_REPORT="$REPORT_DIR/BR_PATCHER_BASELINE_STATUS_REPORT.json"
BASELINE_CHANGED_STATUS_REPORT="$REPORT_DIR/BR_PATCHER_BASELINE_CHANGED_STATUS_REPORT.json"
INSTALLATION_STATUS_REPORT="$REPORT_DIR/BR_PATCHER_INSTALLATION_STATUS_REPORT.json"
COMPOSED_PAYLOAD_PREVIEW_REPORT="$REPORT_DIR/BR_PATCHER_QUARTET_COMPOSED_PAYLOAD_PREVIEW_REPORT.json"
PAYLOAD_PREVIEW_TEST_ROOT="$BUILD_DIR/payload-preview-self-test"
TRANSACTION_PREPARE_STATE_ROOT="$PAYLOAD_PREVIEW_TEST_ROOT/state"
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
[[ -x "$PROJECT_ROOT/workstreams/core/07_prepare_local_translation_payloads.sh" ]] || fail "One-command Translation workflow is missing or not executable"
[[ -f "$PROJECT_ROOT/workstreams/core/local_translation_workflow.py" ]] || fail "Local Translation workflow implementation is missing"

python3 -m unittest discover \
  -s "$PROJECT_ROOT/workstreams/core/tests" \
  -p 'test_*.py'
python3 -m unittest discover \
  -s "$PROJECT_ROOT/workstreams/translation_tooling/tests" \
  -p 'test_current_baseline_rebase.py'
python3 "$PROJECT_ROOT/workstreams/translation_tooling/blue_reflection_title_marker.py" --self-test >/dev/null
"$PROJECT_ROOT/workstreams/core/07_prepare_local_translation_payloads.sh" --help >/dev/null

# shellcheck source=/dev/null
source "$PATHS_FILE"

# Machine-local game roots are inputs only to the checks that actually need them.
# BR1 Original + Quartet remain required because this validator explicitly exercises
# current-directory detection and the real Quartet module-selection envelope.
# Standalone Second Light is optional here: source-assets workflows are validated
# independently and normal runtime/build commands accept explicit source paths.
for required_name in BR1_ORIGINAL_ROOT BR1_QUARTET_ROOT; do
  required_value="${!required_name:-}"
  [[ -n "$required_value" && -d "$required_value" ]] || \
    fail "Required local validation root $required_name is missing or invalid: ${required_value:-<unset>}"
done

DETECTION_ROOT_ARGS=(
  --root "$BR1_ORIGINAL_ROOT"
  --root "$BR1_QUARTET_ROOT"
)
EXPECTED_DETECTION_TARGETS=(
  blue_reflection_original
  blue_reflection_quartet
)

# The real Quartet `start` command runs the integrated-content survey even for
# selection-only/default-state validation. Never make that survey rediscover BR1
# from default Steam paths: use the already configured explicit source root.
QUARTET_START_SOURCE_ARGS=(
  --legacy-source "$BR1_ORIGINAL_ROOT"
  --legacy-no-auto
)

if [[ -n "${BR_SECOND_LIGHT_ROOT:-}" && -d "$BR_SECOND_LIGHT_ROOT" ]]; then
  DETECTION_ROOT_ARGS+=(--root "$BR_SECOND_LIGHT_ROOT")
  EXPECTED_DETECTION_TARGETS+=(second_light_original)
  QUARTET_START_SOURCE_ARGS+=(
    --second-light-source "$BR_SECOND_LIGHT_ROOT"
    --dlc-sources blue_reflection,second_light
  )
  printf 'Second Light local validation root: PRESENT (%s)\n' "$BR_SECOND_LIGHT_ROOT"
else
  # Keep the outer Quartet DLC module selected (that is the production default),
  # but scope this machine-local source survey to the BR1 family that is actually
  # present. Standalone Second Light parity is covered by static/composer tests and
  # by the already validated combined .unburger-assets workflow.
  QUARTET_START_SOURCE_ARGS+=(--dlc-sources blue_reflection)
  printf 'Second Light local validation root: SKIPPED_MISSING_LOCAL_ROOT (%s)\n' "${BR_SECOND_LIGHT_ROOT:-<unset>}" >&2
fi

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
    "${DETECTION_ROOT_ARGS[@]}" \
    --json "$DETECTION_REPORT"

  python3 - "$DETECTION_REPORT" "${EXPECTED_DETECTION_TARGETS[@]}" <<'PY'
import json
import sys
from pathlib import Path

path = Path(sys.argv[1])
data = json.loads(path.read_text(encoding="utf-8"))
expected = set(sys.argv[2:])
found = {item["target_id"] for item in data}
if found != expected:
    raise SystemExit(f"Detection mismatch: expected {sorted(expected)}, found {sorted(found)}")
print("Detected all configured local validation roots that are present.")
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
    "${QUARTET_START_SOURCE_ARGS[@]}" \
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
expected_selected_q = [
    "blue_reflection_translation",
    "quartet_legacy_dlc",
    "quartet_movie_restoration",
    "quartet_restoration",
]
if q_target.get("selected_module_ids") != expected_selected_q:
    raise SystemExit(f"Unexpected default Quartet selection: {q_target!r}")
expected_q = {
    "blue_reflection_translation",
    "quartet_restoration",
    "quartet_movie_restoration",
    "quartet_legacy_dlc",
}
found_q = {m["module_id"] for m in q_target.get("available_modules", [])}
if found_q != expected_q:
    raise SystemExit(f"Unexpected Quartet module catalog: {sorted(found_q)}")

manifest_modules = {m["module_id"]: m for m in manifest["modules"]}
catalog_modules = {m["module_id"]: m for m in catalog["modules"]}
if manifest_modules != catalog_modules:
    raise SystemExit("Embedded module catalog diverges from the development bundle manifest")
print("Target-aware defaults, full Quartet default module set, explicit legacy-source routing, and embedded catalog parity are valid.")
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
    "persistent_baseline_created": True,
    "active_state_recorded": True,
    "active_state_matched_installed": True,
    "active_state_cleared_after_rollback": True,
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
    "$PAYLOAD_PREVIEW_TEST_ROOT/project/workstreams/translation" \
    "$PAYLOAD_PREVIEW_TEST_ROOT/project/workstreams/translation_tooling" \
    "$PAYLOAD_PREVIEW_TEST_ROOT/project/Blue_Reflection_Patcher" \
    "$PAYLOAD_PREVIEW_TEST_ROOT/game/DATA"
  printf '0.0.22\n' > "$PAYLOAD_PREVIEW_TEST_ROOT/project/workstreams/core/VERSION"
  printf '0.0.113\n' > "$PAYLOAD_PREVIEW_TEST_ROOT/project/workstreams/translation/VERSION"
  printf '0.0.54\n' > "$PAYLOAD_PREVIEW_TEST_ROOT/project/workstreams/translation_tooling/VERSION"
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
loose_report = {
    "type": "br_translation_loose_build_report",
    "format_version": 2,
    "status": "ok",
    "translation_version": "0.0.113",
    "translation_tooling_version": "0.0.54",
    "canonical_input_fingerprint": hashlib.sha256(b"synthetic-payload-preview").hexdigest(),
    "targets": {"blue_reflection_original": {"files": []}},
}
loose_path = project / ".local/reports/translation/BR_TRANSLATION_LOOSE_BUILD_REPORT.json"
loose_path.parent.mkdir(parents=True, exist_ok=True)
loose_payload = (json.dumps(loose_report, indent=2) + "\n").encode("utf-8")
loose_path.write_bytes(loose_payload)
for archive in archives:
    baseline = ("synthetic-baseline-" + archive["archive_relative_path"]).encode("utf-8")
    archive.update({
        "source_policy": "current_installation_baseline_extraction",
        "source_archive_sha256": hashlib.sha256(baseline).hexdigest(),
        "source_archive_bytes": len(baseline),
        "changed_members": [],
        "full_reextract_verified": True,
    })
report = {
    "type": "br_translation_pak_repack_report",
    "format_version": 2,
    "status": "ok",
    "translation_version": "0.0.113",
    "translation_tooling_version": "0.0.54",
    "minimum_translation_version": "0.0.113",
    "canonical_input_fingerprint": loose_report["canonical_input_fingerprint"],
    "loose_report_path": loose_path.relative_to(project).as_posix(),
    "loose_report_sha256": hashlib.sha256(loose_payload).hexdigest(),
    "loose_report_bytes": len(loose_payload),
    "selected_targets": ["blue_reflection_original"],
    "archives": archives,
}
report_path = project / ".local/reports/translation/BR_TRANSLATION_PAK_REPACK_REPORT.json"
report_path.parent.mkdir(parents=True, exist_ok=True)
report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
PYPAYLOADBUILD

  cp -a \
    "$PAYLOAD_PREVIEW_TEST_ROOT/project/.local/reports/translation/BR_TRANSLATION_PAK_REPACK_REPORT.json" \
    "$PAYLOAD_PREVIEW_TEST_ROOT/project/.local/reports/translation/BR_TRANSLATION_PAK_REPACK_REPORT.fixture.json"
  printf '# synthetic local workflow marker\n' \
    > "$PAYLOAD_PREVIEW_TEST_ROOT/project/workstreams/core/local_translation_workflow.py"
  cat > "$PAYLOAD_PREVIEW_TEST_ROOT/project/workstreams/core/07_prepare_local_translation_payloads.sh" <<'PYGUIDEDLOCALBUILDER'
#!/usr/bin/env bash
set -Eeuo pipefail
PROJECT_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
GAME_ROOT=""
MODULES=""
REPORT=""
PREVIEW_ONLY=0
while (($#)); do
  case "$1" in
    --game-dir) GAME_ROOT="$2"; shift 2 ;;
    --modules) MODULES="$2"; shift 2 ;;
    --preview-only) PREVIEW_ONLY=1; shift ;;
    --json) REPORT="$2"; shift 2 ;;
    *) printf 'unexpected synthetic workflow argument: %s\n' "$1" >&2; exit 2 ;;
  esac
done
[[ "$PREVIEW_ONLY" == 1 ]] || exit 3
[[ "$MODULES" == blue_reflection_translation ]] || exit 4
cp -a \
  "$PROJECT_ROOT/.local/reports/translation/BR_TRANSLATION_PAK_REPACK_REPORT.fixture.json" \
  "$PROJECT_ROOT/.local/reports/translation/BR_TRANSLATION_PAK_REPACK_REPORT.json"
python3 - "$GAME_ROOT" "$REPORT" <<'PYGUIDEDLOCALREPORT'
import json
import sys
from pathlib import Path
game = str(Path(sys.argv[1]).resolve())
report = Path(sys.argv[2])
report.parent.mkdir(parents=True, exist_ok=True)
report.write_text(json.dumps({
    "type": "br_local_translation_workflow_report",
    "format_version": 5,
    "status": "ready_preview_only",
    "target_id": "blue_reflection_original",
    "game_root": game,
    "preview_only": True,
    "game_files_modified": False,
    "commit_enabled": False,
}, indent=2) + "\n", encoding="utf-8")
PYGUIDEDLOCALREPORT
PYGUIDEDLOCALBUILDER
  chmod 0755 "$PAYLOAD_PREVIEW_TEST_ROOT/project/workstreams/core/07_prepare_local_translation_payloads.sh"

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

  rm -rf -- "$TRANSACTION_PREPARE_STATE_ROOT"
  mkdir -p -- "$TRANSACTION_PREPARE_STATE_ROOT"
  game_hashes_before="$(find "$PAYLOAD_PREVIEW_TEST_ROOT/game" -type f -print0 | sort -z | xargs -0 sha256sum)"
  XDG_STATE_HOME="$TRANSACTION_PREPARE_STATE_ROOT" \
    "$BUILD_DIR/blue-reflection-patcher-linux-x86_64" transaction-prepare \
      --game-dir "$PAYLOAD_PREVIEW_TEST_ROOT/game" \
      --modules blue_reflection_translation \
      --no-prompt \
      --project-root "$PAYLOAD_PREVIEW_TEST_ROOT/project" \
      --json "$TRANSACTION_PREPARE_REPORT"

  XDG_STATE_HOME="$TRANSACTION_PREPARE_STATE_ROOT" \
    "$BUILD_DIR/blue-reflection-patcher-linux-x86_64" transaction-status \
      --game-dir "$PAYLOAD_PREVIEW_TEST_ROOT/game" \
      --json "$TRANSACTION_STATUS_REPORT"

  XDG_STATE_HOME="$TRANSACTION_PREPARE_STATE_ROOT" \
    "$BUILD_DIR/blue-reflection-patcher-linux-x86_64" baseline-status \
      --game-dir "$PAYLOAD_PREVIEW_TEST_ROOT/game" \
      --json "$BASELINE_STATUS_REPORT"

  XDG_STATE_HOME="$TRANSACTION_PREPARE_STATE_ROOT" \
    "$BUILD_DIR/blue-reflection-patcher-linux-x86_64" installation-status \
      --game-dir "$PAYLOAD_PREVIEW_TEST_ROOT/game" \
      --json "$INSTALLATION_STATUS_REPORT"

  python3 - "$TRANSACTION_PREPARE_REPORT" "$TRANSACTION_STATUS_REPORT" "$BASELINE_STATUS_REPORT" "$INSTALLATION_STATUS_REPORT" <<'PYTRANSACTIONPREPARE'
import json
import sys
from pathlib import Path

prepared = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
status = json.loads(Path(sys.argv[2]).read_text(encoding="utf-8"))
baseline = json.loads(Path(sys.argv[3]).read_text(encoding="utf-8"))
installation = json.loads(Path(sys.argv[4]).read_text(encoding="utf-8"))
if prepared.get("type") != "br_transaction_prepare_report" or prepared.get("status") != "prepared":
    raise SystemExit(f"Translation transaction was not prepared: {prepared!r}")
if prepared.get("commit_enabled") is not True:
    raise SystemExit(f"Prepared transaction does not expose explicit commit: {prepared!r}")
if prepared.get("format_version") != 6:
    raise SystemExit(f"Unexpected transaction prepare format: {prepared!r}")
if prepared.get("baseline_action") != "created" or not prepared.get("baseline_id"):
    raise SystemExit(f"Persistent baseline was not created: {prepared!r}")
if prepared.get("baseline_source") != "observed_current_preinstall_state" or prepared.get("active_state_status") != "not_active":
    raise SystemExit(f"Unexpected initial active/baseline source state: {prepared!r}")
manifest = Path(prepared.get("baseline_manifest_path", ""))
if not manifest.is_file():
    raise SystemExit(f"Persistent baseline manifest is missing: {manifest}")
inspection = baseline.get("inspection", {})
if inspection.get("status") != "matches_known_baseline" or inspection.get("baseline_count") != 1:
    raise SystemExit(f"Current synthetic game does not match its preserved baseline: {baseline!r}")
if inspection.get("matching_baseline_id") != prepared.get("baseline_id"):
    raise SystemExit(f"Baseline identity mismatch: prepared={prepared!r} status={baseline!r}")
if installation.get("status") != "inactive_matches_known_baseline" or installation.get("automatic_prepare_allowed") is not True:
    raise SystemExit(f"Inactive installation status is not safely classified: {installation!r}")
if prepared.get("prepared_change_count") != 3 or prepared.get("backup_count") != 3 or prepared.get("staged_count") != 3:
    raise SystemExit(f"Unexpected prepared transaction counts: {prepared!r}")
journal = Path(prepared.get("journal_path", ""))
if not journal.is_file():
    raise SystemExit(f"Prepared transaction journal is missing: {journal}")
for item in prepared.get("files", []):
    if not item.get("backup_prepared") or not item.get("staged_prepared"):
        raise SystemExit(f"Prepared file lacks verified private state: {item!r}")
if status.get("transaction_count") != 1 or status.get("transactions", [{}])[0].get("status") != "prepared":
    raise SystemExit(f"Prepared transaction was not discoverable: {status!r}")
print("Verified translation payloads were staged from an immutable persistent baseline with backups and a journal; installation still required explicit confirmation.")
PYTRANSACTIONPREPARE

  # While the transaction is still prepared, its verified rollback store is alive.
  # This is the correct point to prove baseline classification semantics. Terminal
  # rollback/removal intentionally retires first-install baseline storage afterwards.
  printf 'synthetic-game-update' > "$PAYLOAD_PREVIEW_TEST_ROOT/game/DATA/PACK01.PAK"
  XDG_STATE_HOME="$TRANSACTION_PREPARE_STATE_ROOT" \
    "$BUILD_DIR/blue-reflection-patcher-linux-x86_64" baseline-status \
      --game-dir "$PAYLOAD_PREVIEW_TEST_ROOT/game" \
      --json "$BASELINE_CHANGED_STATUS_REPORT"
  printf 'stock-DATA/PACK01.PAK' > "$PAYLOAD_PREVIEW_TEST_ROOT/game/DATA/PACK01.PAK"

  python3 - "$BASELINE_CHANGED_STATUS_REPORT" <<'PYPREPAREDBASELINECHANGE'
import json
import sys
from pathlib import Path
changed = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))["inspection"]
if changed.get("status") != "mixed_changes":
    raise SystemExit(f"Prepared persistent baseline did not conservatively classify a changed installation: {changed!r}")
print("Prepared persistent baseline classifies changed files conservatively while its rollback source is still live.")
PYPREPAREDBASELINECHANGE

  if XDG_STATE_HOME="$TRANSACTION_PREPARE_STATE_ROOT" \
      "$BUILD_DIR/blue-reflection-patcher-linux-x86_64" transaction-prepare \
        --game-dir "$PAYLOAD_PREVIEW_TEST_ROOT/game" \
        --modules blue_reflection_translation \
        --no-prompt \
        --project-root "$PAYLOAD_PREVIEW_TEST_ROOT/project" >/dev/null 2>&1; then
    fail "A second transaction prepare was accepted while a prepared transaction was active"
  fi

  prepared_journal="$(python3 - "$TRANSACTION_PREPARE_REPORT" <<'PYJOURNAL'
import json
import sys
from pathlib import Path
print(json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))["journal_path"])
PYJOURNAL
)"
  "$BUILD_DIR/blue-reflection-patcher-linux-x86_64" transaction-discard \
    --journal "$prepared_journal" \
    --json "$TRANSACTION_DISCARD_REPORT"

  game_hashes_after="$(find "$PAYLOAD_PREVIEW_TEST_ROOT/game" -type f -print0 | sort -z | xargs -0 sha256sum)"
  [[ "$game_hashes_after" == "$game_hashes_before" ]] || fail "Transaction prepare/discard modified synthetic game files"

  python3 - "$TRANSACTION_DISCARD_REPORT" "$prepared_journal" <<'PYTRANSACTIONDISCARD'
import json
import sys
from pathlib import Path

report = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
journal_path = Path(sys.argv[2])
if report.get("status") != "discarded" or report.get("game_files_edited") is not False:
    raise SystemExit(f"Prepared transaction was not safely discarded: {report!r}")
journal = json.loads(journal_path.read_text(encoding="utf-8"))
if journal.get("status") != "discarded":
    raise SystemExit(f"Discard audit journal was not retained: {journal!r}")
root = journal_path.parent
if (root / "staged").exists() or (root / "backup").exists():
    raise SystemExit("Discard retained staged payloads or backups")
print("Prepared transaction discard retained the audit journal, removed private payload copies and left the game unchanged.")
PYTRANSACTIONDISCARD

  XDG_STATE_HOME="$TRANSACTION_PREPARE_STATE_ROOT" \
    "$BUILD_DIR/blue-reflection-patcher-linux-x86_64" transaction-prepare \
      --game-dir "$PAYLOAD_PREVIEW_TEST_ROOT/game" \
      --modules blue_reflection_translation \
      --no-prompt \
      --project-root "$PAYLOAD_PREVIEW_TEST_ROOT/project" \
      --json "$TRANSACTION_INSTALL_PREPARE_REPORT"

  install_journal="$(python3 - "$TRANSACTION_INSTALL_PREPARE_REPORT" <<'PYINSTALLJOURNAL'
import json
import sys
from pathlib import Path
print(json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))["journal_path"])
PYINSTALLJOURNAL
)"

  if "$BUILD_DIR/blue-reflection-patcher-linux-x86_64" transaction-commit \
      --journal "$install_journal" >/dev/null 2>&1; then
    fail "Transaction commit was accepted without explicit --yes confirmation"
  fi

  "$BUILD_DIR/blue-reflection-patcher-linux-x86_64" transaction-commit \
    --journal "$install_journal" \
    --yes \
    --json "$TRANSACTION_COMMIT_REPORT"

  XDG_STATE_HOME="$TRANSACTION_PREPARE_STATE_ROOT" \
    "$BUILD_DIR/blue-reflection-patcher-linux-x86_64" installation-status \
      --game-dir "$PAYLOAD_PREVIEW_TEST_ROOT/game" \
      --json "$INSTALLATION_ACTIVE_STATUS_REPORT"

  python3 - "$TRANSACTION_COMMIT_REPORT" "$INSTALLATION_ACTIVE_STATUS_REPORT" "$TRANSACTION_INSTALL_PREPARE_REPORT" <<'PYTRANSACTIONCOMMIT'
import hashlib
import json
import sys
from pathlib import Path

commit = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
status = json.loads(Path(sys.argv[2]).read_text(encoding="utf-8"))
prepared = json.loads(Path(sys.argv[3]).read_text(encoding="utf-8"))
if commit.get("status") != "installed" or commit.get("game_files_modified") is not True:
    raise SystemExit(f"Transaction was not publicly committed: {commit!r}")
if commit.get("atomic_per_file") is not True or commit.get("file_count") != 3:
    raise SystemExit(f"Commit safety metadata is incomplete: {commit!r}")
if status.get("status") != "active_matches_installed" or status.get("automatic_prepare_allowed") is not True:
    raise SystemExit(f"Committed installation is not tracked as active: {status!r}")
for item in prepared.get("files", []):
    if item.get("desired_action") not in {"add", "replace"}:
        continue
    installed = Path(item["target_path"])
    payload = Path(item["source_path"])
    if hashlib.sha256(installed.read_bytes()).hexdigest() != hashlib.sha256(payload.read_bytes()).hexdigest():
        raise SystemExit(f"Committed payload mismatch: {item.get('relative_path')}")
print("Explicit transaction commit atomically installed verified payloads and published the active installation state.")
PYTRANSACTIONCOMMIT

  if "$BUILD_DIR/blue-reflection-patcher-linux-x86_64" transaction-rollback \
      --journal "$install_journal" >/dev/null 2>&1; then
    fail "Transaction rollback was accepted without explicit --yes confirmation"
  fi

  "$BUILD_DIR/blue-reflection-patcher-linux-x86_64" transaction-rollback \
    --journal "$install_journal" \
    --yes \
    --json "$TRANSACTION_ROLLBACK_REPORT"

  XDG_STATE_HOME="$TRANSACTION_PREPARE_STATE_ROOT" \
    "$BUILD_DIR/blue-reflection-patcher-linux-x86_64" installation-status \
      --game-dir "$PAYLOAD_PREVIEW_TEST_ROOT/game" \
      --json "$INSTALLATION_ROLLED_BACK_STATUS_REPORT"

  XDG_STATE_HOME="$TRANSACTION_PREPARE_STATE_ROOT" \
    "$BUILD_DIR/blue-reflection-patcher-linux-x86_64" baseline-status \
      --game-dir "$PAYLOAD_PREVIEW_TEST_ROOT/game" \
      --json "$BASELINE_STATUS_REPORT"

  game_hashes_after_rollback="$(find "$PAYLOAD_PREVIEW_TEST_ROOT/game" -type f -print0 | sort -z | xargs -0 sha256sum)"
  [[ "$game_hashes_after_rollback" == "$game_hashes_before" ]] || fail "Public rollback did not restore synthetic game files"

  python3 - "$TRANSACTION_ROLLBACK_REPORT" "$INSTALLATION_ROLLED_BACK_STATUS_REPORT" "$BASELINE_STATUS_REPORT" <<'PYTRANSACTIONROLLBACK'
import json
import sys
from pathlib import Path
rollback = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
status = json.loads(Path(sys.argv[2]).read_text(encoding="utf-8"))
baseline = json.loads(Path(sys.argv[3]).read_text(encoding="utf-8"))["inspection"]
if rollback.get("status") != "rolled_back" or rollback.get("game_files_modified") is not True:
    raise SystemExit(f"Transaction was not publicly rolled back: {rollback!r}")
if rollback.get("active_after_rollback") is not False:
    raise SystemExit(f"First-install rollback unexpectedly retained an active state: {rollback!r}")
if status.get("status") != "untracked":
    raise SystemExit(f"Terminal first-install rollback did not clear managed installation state: {status!r}")
if baseline.get("status") != "not_captured" or baseline.get("baseline_count") != 0:
    raise SystemExit(f"Terminal first-install rollback retained obsolete baseline storage: {baseline!r}")
print("Explicit rollback restored the original files, cleared active state, and retired now-unneeded first-install baseline storage.")
PYTRANSACTIONROLLBACK

  printf '{"status":"ok","archives":[]}\n' \
    > "$PAYLOAD_PREVIEW_TEST_ROOT/project/.local/reports/translation/BR_TRANSLATION_PAK_REPACK_REPORT.json"

  XDG_STATE_HOME="$TRANSACTION_PREPARE_STATE_ROOT" \
    "$BUILD_DIR/blue-reflection-patcher-linux-x86_64" start \
      --game-dir "$PAYLOAD_PREVIEW_TEST_ROOT/game" \
      --modules blue_reflection_translation \
      --project-root "$PAYLOAD_PREVIEW_TEST_ROOT/project" \
      --no-prompt \
      --build-local \
      --install \
      --yes \
      --json "$GUIDED_LOCAL_BUILD_SELECTION_REPORT" \
      --payload-json "$GUIDED_LOCAL_BUILD_PAYLOAD_REPORT"

  XDG_STATE_HOME="$TRANSACTION_PREPARE_STATE_ROOT" \
    "$BUILD_DIR/blue-reflection-patcher-linux-x86_64" installation-status \
      --game-dir "$PAYLOAD_PREVIEW_TEST_ROOT/game" \
      --json "$GUIDED_LOCAL_BUILD_STATUS_REPORT"

  XDG_STATE_HOME="$TRANSACTION_PREPARE_STATE_ROOT" \
    "$BUILD_DIR/blue-reflection-patcher-linux-x86_64" transaction-status \
      --game-dir "$PAYLOAD_PREVIEW_TEST_ROOT/game" \
      --json "$GUIDED_LOCAL_BUILD_TRANSACTION_REPORT"

  guided_local_journal="$(python3 - "$GUIDED_LOCAL_BUILD_TRANSACTION_REPORT" <<'PYGUIDEDLOCALJOURNAL'
import json
import sys
from pathlib import Path
report = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
items = [item for item in report.get("transactions", []) if item.get("status") == "committed"]
if not items:
    raise SystemExit("Guided local build did not create a committed transaction")
items.sort(key=lambda item: item.get("created_utc", ""))
print(items[-1]["journal_path"])
PYGUIDEDLOCALJOURNAL
)"

  python3 - "$GUIDED_LOCAL_BUILD_PAYLOAD_REPORT" "$GUIDED_LOCAL_BUILD_STATUS_REPORT" <<'PYGUIDEDLOCALCHECK'
import json
import sys
from pathlib import Path
payload = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
status = json.loads(Path(sys.argv[2]).read_text(encoding="utf-8"))
if payload.get("status") != "ready":
    raise SystemExit(f"Guided local build did not refresh payload readiness: {payload!r}")
if status.get("status") != "active_matches_installed":
    raise SystemExit(f"Guided local build did not install the refreshed payloads: {status!r}")
print("Guided start rebuilt an absent target-specific repack set, refreshed preview and installed only after explicit confirmation.")
PYGUIDEDLOCALCHECK

  "$BUILD_DIR/blue-reflection-patcher-linux-x86_64" transaction-rollback \
    --journal "$guided_local_journal" \
    --yes >/dev/null

  game_hashes_after_guided_local_rollback="$(find "$PAYLOAD_PREVIEW_TEST_ROOT/game" -type f -print0 | sort -z | xargs -0 sha256sum)"
  [[ "$game_hashes_after_guided_local_rollback" == "$game_hashes_before" ]] || fail "Guided local build rollback did not restore synthetic game files"

  if XDG_STATE_HOME="$TRANSACTION_PREPARE_STATE_ROOT" \
      "$BUILD_DIR/blue-reflection-patcher-linux-x86_64" start \
        --game-dir "$PAYLOAD_PREVIEW_TEST_ROOT/game" \
        --modules blue_reflection_translation \
        --project-root "$PAYLOAD_PREVIEW_TEST_ROOT/project" \
        --no-prompt \
        --install >/dev/null 2>&1; then
    fail "Guided non-interactive installation was accepted without --yes"
  fi

  XDG_STATE_HOME="$TRANSACTION_PREPARE_STATE_ROOT" \
    "$BUILD_DIR/blue-reflection-patcher-linux-x86_64" start \
      --game-dir "$PAYLOAD_PREVIEW_TEST_ROOT/game" \
      --modules blue_reflection_translation \
      --project-root "$PAYLOAD_PREVIEW_TEST_ROOT/project" \
      --no-prompt \
      --install \
      --yes \
      --json "$GUIDED_INSTALL_SELECTION_REPORT" \
      --payload-json "$GUIDED_INSTALL_PAYLOAD_REPORT"

  XDG_STATE_HOME="$TRANSACTION_PREPARE_STATE_ROOT" \
    "$BUILD_DIR/blue-reflection-patcher-linux-x86_64" installation-status \
      --game-dir "$PAYLOAD_PREVIEW_TEST_ROOT/game" \
      --json "$GUIDED_INSTALL_STATUS_REPORT"

  XDG_STATE_HOME="$TRANSACTION_PREPARE_STATE_ROOT" \
    "$BUILD_DIR/blue-reflection-patcher-linux-x86_64" transaction-status \
      --game-dir "$PAYLOAD_PREVIEW_TEST_ROOT/game" \
      --json "$GUIDED_INSTALL_TRANSACTION_REPORT"

  guided_journal="$(python3 - "$GUIDED_INSTALL_TRANSACTION_REPORT" <<'PYGUIDEDJOURNAL'
import json
import sys
from pathlib import Path
report = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
items = [item for item in report.get("transactions", []) if item.get("status") == "committed"]
if not items:
    raise SystemExit("Guided start did not create a committed transaction")
items.sort(key=lambda item: item.get("created_utc", ""))
print(items[-1]["journal_path"])
PYGUIDEDJOURNAL
)"

  python3 - "$GUIDED_INSTALL_SELECTION_REPORT" "$GUIDED_INSTALL_PAYLOAD_REPORT" "$GUIDED_INSTALL_STATUS_REPORT" <<'PYGUIDEDCHECK'
import json
import sys
from pathlib import Path
selection = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
payload = json.loads(Path(sys.argv[2]).read_text(encoding="utf-8"))
status = json.loads(Path(sys.argv[3]).read_text(encoding="utf-8"))
if selection.get("targets", [{}])[0].get("selected_module_ids") != ["blue_reflection_translation"]:
    raise SystemExit(f"Guided selection mismatch: {selection!r}")
if payload.get("status") != "ready" or payload.get("commit_enabled") is not False:
    raise SystemExit(f"Guided payload preview mismatch: {payload!r}")
if status.get("status") != "active_matches_installed":
    raise SystemExit(f"Guided start did not install and publish active state: {status!r}")
print("Guided start joined detection, module selection, verified preview, prepare and explicit installation in one workflow.")
PYGUIDEDCHECK

  if XDG_STATE_HOME="$TRANSACTION_PREPARE_STATE_ROOT" \
      "$BUILD_DIR/blue-reflection-patcher-linux-x86_64" start \
        --game-dir "$PAYLOAD_PREVIEW_TEST_ROOT/game" \
        --no-prompt \
        --remove >/dev/null 2>&1; then
    fail "Guided non-interactive complete removal was accepted without --yes"
  fi

  XDG_STATE_HOME="$TRANSACTION_PREPARE_STATE_ROOT" \
    "$BUILD_DIR/blue-reflection-patcher-linux-x86_64" start \
      --game-dir "$PAYLOAD_PREVIEW_TEST_ROOT/game" \
      --no-prompt \
      --remove \
      --yes

  game_hashes_after_guided_rollback="$(find "$PAYLOAD_PREVIEW_TEST_ROOT/game" -type f -print0 | sort -z | xargs -0 sha256sum)"
  [[ "$game_hashes_after_guided_rollback" == "$game_hashes_before" ]] || fail "Guided complete removal did not restore synthetic game files"

  XDG_STATE_HOME="$TRANSACTION_PREPARE_STATE_ROOT" \
    "$BUILD_DIR/blue-reflection-patcher-linux-x86_64" installation-status \
      --game-dir "$PAYLOAD_PREVIEW_TEST_ROOT/game" \
      --json "$GUIDED_INSTALL_STATUS_REPORT"

  XDG_STATE_HOME="$TRANSACTION_PREPARE_STATE_ROOT" \
    "$BUILD_DIR/blue-reflection-patcher-linux-x86_64" baseline-status \
      --game-dir "$PAYLOAD_PREVIEW_TEST_ROOT/game" \
      --json "$BASELINE_STATUS_REPORT"

  python3 - "$GUIDED_INSTALL_STATUS_REPORT" "$BASELINE_STATUS_REPORT" <<'PYGUIDEDREMOVECHECK'
import json
import sys
from pathlib import Path
status = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
baseline = json.loads(Path(sys.argv[2]).read_text(encoding="utf-8"))["inspection"]
if status.get("status") != "untracked":
    raise SystemExit(f"Guided complete removal did not clear managed installation state: {status!r}")
if baseline.get("status") != "not_captured" or baseline.get("baseline_count") != 0:
    raise SystemExit(f"Guided complete removal retained obsolete baseline storage: {baseline!r}")
print("Guided complete removal restored original files, cleared managed state and retired terminal baseline storage after explicit confirmation.")
PYGUIDEDREMOVECHECK

  rm -rf -- "$COMPOSITION_PREVIEW_TEST_ROOT"
  mkdir -p -- "$COMPOSITION_PREVIEW_TEST_ROOT/project/workstreams/core" \
    "$COMPOSITION_PREVIEW_TEST_ROOT/project/workstreams/translation" \
    "$COMPOSITION_PREVIEW_TEST_ROOT/project/workstreams/translation_tooling" \
    "$COMPOSITION_PREVIEW_TEST_ROOT/project/Blue_Reflection_Patcher" \
    "$COMPOSITION_PREVIEW_TEST_ROOT/game/Data"
  printf '0.0.24\n' > "$COMPOSITION_PREVIEW_TEST_ROOT/project/workstreams/core/VERSION"
  printf '0.0.113\n' > "$COMPOSITION_PREVIEW_TEST_ROOT/project/workstreams/translation/VERSION"
  printf '0.0.54\n' > "$COMPOSITION_PREVIEW_TEST_ROOT/project/workstreams/translation_tooling/VERSION"
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
translation_partitions = {}
for partition_name in (
    "PACK01_01.PAK",
    "PACK02_01.PAK",
    "PACK01_02.PAK",
    "PACK02_02.PAK",
    "PACK01_03.PAK",
    "PACK02_03.PAK",
):
    translation_partitions[partition_name] = make_pak(
        root / "pak_sources" / ("translation_" + Path(partition_name).stem.lower()),
        partition_name,
        {
            "synthetic/" + Path(partition_name).stem.lower() + ".bin":
                ("translation-" + partition_name + "-").encode("utf-8") * 200
        },
    )

(game / "Data/PACK11.PAK").write_bytes(baseline_pack11.read_bytes())
# Structural markers used for target detection. Unselected restoration archives
# need not be valid synthetic PAKs in this test.
(game / "Data/PACK10_01.PAK").write_bytes(b"synthetic-shader-marker")
(game / "Data/PACK10_03.PAK").write_bytes(b"synthetic-field-marker")
(game / "Data/PACK12.PAK").write_bytes(b"synthetic-text-marker")
(game / "Data/PACK00_04_01.PAK").write_bytes(b"synthetic-title-marker")
for partition_marker in (
    "PACK01_01.PAK",
    "PACK02_01.PAK",
    "PACK01_02.PAK",
    "PACK02_02.PAK",
    "PACK01_03.PAK",
    "PACK02_03.PAK",
):
    (game / "Data" / partition_marker).write_bytes(
        ("synthetic-partition-marker-" + partition_marker).encode("utf-8")
    )

archives = []
translation_archive_sources = [
    (translation_pack11, "blue_reflection_quartet", "Data/PACK11.PAK"),
    (translation_pack12, "blue_reflection_quartet", "Data/PACK12.PAK"),
    (translation_partitions["PACK01_01.PAK"], "blue_reflection_ray_quartet", "Data/PACK01_01.PAK"),
    (translation_partitions["PACK02_01.PAK"], "blue_reflection_ray_quartet", "Data/PACK02_01.PAK"),
    (translation_partitions["PACK01_02.PAK"], "blue_reflection_sun_quartet", "Data/PACK01_02.PAK"),
    (translation_partitions["PACK02_02.PAK"], "blue_reflection_sun_quartet", "Data/PACK02_02.PAK"),
    (translation_partitions["PACK01_03.PAK"], "second_light_quartet", "Data/PACK01_03.PAK"),
    (translation_partitions["PACK02_03.PAK"], "second_light_quartet", "Data/PACK02_03.PAK"),
    (translation_title, "blue_reflection_quartet", "Data/PACK00_04_01.PAK"),
]
for source, content_target_id, relative in translation_archive_sources:
    output = project / ".local/build/translation/archives" / content_target_id / relative
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(source.read_bytes())
    digest, size = sha_size(output)
    archives.append({
        "target_id": content_target_id,
        "archive_relative_path": relative,
        "output_path": output.relative_to(project).as_posix(),
        "output_sha256": digest,
        "output_bytes": size,
        "failures": [],
    })

fingerprint = hashlib.sha256(b"synthetic-quartet-composition").hexdigest()
loose = project / ".local/reports/translation/BR_TRANSLATION_LOOSE_BUILD_REPORT.json"
loose.parent.mkdir(parents=True, exist_ok=True)
loose_payload = (json.dumps({
    "type": "br_translation_loose_build_report",
    "format_version": 2,
    "status": "ok",
    "translation_version": "0.0.113",
    "translation_tooling_version": "0.0.54",
    "canonical_input_fingerprint": fingerprint,
    "targets": {
        "blue_reflection_quartet": {
            "files": [{
                "archive_relative_path": "Data/PACK11.PAK",
                "internal_path": "event/b1/event_en/test.ebm",
                "changed": True,
            }]
        },
        "blue_reflection_ray_quartet": {"files": []},
        "blue_reflection_sun_quartet": {"files": []},
        "second_light_quartet": {"files": []},
    },
}, indent=2) + "\n").encode("utf-8")
loose.write_bytes(loose_payload)

repack = project / ".local/reports/translation/BR_TRANSLATION_PAK_REPACK_REPORT.json"
repack.parent.mkdir(parents=True, exist_ok=True)
repack.write_text(json.dumps({
    "type": "br_translation_pak_repack_report",
    "format_version": 2,
    "status": "ok",
    "translation_version": "0.0.113",
    "translation_tooling_version": "0.0.54",
    "minimum_translation_version": "0.0.113",
    "canonical_input_fingerprint": fingerprint,
    "loose_report_path": loose.relative_to(project).as_posix(),
    "loose_report_sha256": hashlib.sha256(loose_payload).hexdigest(),
    "loose_report_bytes": len(loose_payload),
    "selected_targets": [
        "blue_reflection_quartet",
        "blue_reflection_ray_quartet",
        "blue_reflection_sun_quartet",
        "second_light_quartet",
    ],
    "archives": archives,
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
if report.get("type") != "br_quartet_translation_restoration_composition_build" or report.get("format_version") != 4:
    raise SystemExit(f"Unexpected composition build type/version: {report!r}")
if report.get("status") != "ok" or report.get("commit_enabled") is not False:
    raise SystemExit(f"Composition build is not safe and complete: {report!r}")
if report.get("published_archive_count") != 9 or report.get("composed_archive_count") != 1:
    raise SystemExit(f"Unexpected composition build summary: {report!r}")
for key in ("translation_loose_report_sha256", "translation_repack_report_sha256"):
    if len(report.get(key, "")) != 64:
        raise SystemExit(f"Missing composition input fingerprint {key}: {report!r}")
profile_inputs = report.get("profile_inputs", [])
if len(profile_inputs) != 1 or profile_inputs[0].get("profile_id") != "synthetic_runtime_validated_profile":
    raise SystemExit(f"Composition profile inputs were not fingerprinted: {profile_inputs!r}")
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

  "$BUILD_DIR/blue-reflection-patcher-linux-x86_64" payload-preview \
    --game-dir "$COMPOSITION_PREVIEW_TEST_ROOT/game" \
    --modules blue_reflection_translation,quartet_restoration \
    --no-prompt \
    --project-root "$COMPOSITION_PREVIEW_TEST_ROOT/project" \
    --json "$COMPOSED_PAYLOAD_PREVIEW_REPORT"

  python3 - "$COMPOSED_PAYLOAD_PREVIEW_REPORT" "$COMPOSITION_PREVIEW_TEST_ROOT" <<'PYCOMPOSEDPREVIEW'
import json
import sys
from pathlib import Path

preview = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
root = Path(sys.argv[2])
if preview.get("format_version") != 2 or preview.get("status") != "ready" or preview.get("commit_enabled") is not False:
    raise SystemExit(f"Composed payload preview is not safe and ready: {preview!r}")
targets = preview.get("targets", [])
if len(targets) != 1 or targets[0].get("pending_module_count") != 0 or targets[0].get("ready_artifact_count") != 9:
    raise SystemExit(f"Unexpected composed payload target: {targets!r}")
modules = {item["module_id"]: item for item in targets[0].get("modules", [])}
translation = modules.get("blue_reflection_translation")
restoration = modules.get("quartet_restoration")
if not translation or not translation.get("ready") or len(translation.get("artifacts", [])) != 9:
    raise SystemExit(f"Composed Translation module is not ready: {translation!r}")
if not restoration or not restoration.get("ready") or restoration.get("artifacts"):
    raise SystemExit(f"Restoration was not represented by the shared composition set: {restoration!r}")
composition_root = root / "project/.local/build/composition/blue_reflection_quartet"
for artifact in translation["artifacts"]:
    if not artifact.get("report_verified") or not artifact.get("composition_verified") or not artifact.get("transaction_ready"):
        raise SystemExit(f"Unverified composition artifact entered transaction preview: {artifact!r}")
    source = Path(artifact["source_path"])
    try:
        source.relative_to(composition_root)
    except ValueError:
        raise SystemExit(f"Raw translation artifact was used instead of composition output: {artifact!r}")
print("Verified composed Quartet payloads are connected to transaction preview without preparing or committing a transaction.")
PYCOMPOSEDPREVIEW

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
    "${DETECTION_ROOT_ARGS[@]}" \
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
[[ -f "$TRANSACTION_PREPARE_REPORT" ]] && package_files+=(.local/reports/BR_PATCHER_TRANSACTION_PREPARE_REPORT.json)
[[ -f "$TRANSACTION_STATUS_REPORT" ]] && package_files+=(.local/reports/BR_PATCHER_TRANSACTION_STATUS_REPORT.json)
[[ -f "$TRANSACTION_DISCARD_REPORT" ]] && package_files+=(.local/reports/BR_PATCHER_TRANSACTION_DISCARD_REPORT.json)
[[ -f "$BASELINE_STATUS_REPORT" ]] && package_files+=(.local/reports/BR_PATCHER_BASELINE_STATUS_REPORT.json)
[[ -f "$BASELINE_CHANGED_STATUS_REPORT" ]] && package_files+=(.local/reports/BR_PATCHER_BASELINE_CHANGED_STATUS_REPORT.json)
[[ -f "$INSTALLATION_STATUS_REPORT" ]] && package_files+=(.local/reports/BR_PATCHER_INSTALLATION_STATUS_REPORT.json)
[[ -f "$GUIDED_INSTALL_SELECTION_REPORT" ]] && package_files+=(.local/reports/BR_PATCHER_GUIDED_INSTALL_SELECTION_REPORT.json)
[[ -f "$GUIDED_INSTALL_PAYLOAD_REPORT" ]] && package_files+=(.local/reports/BR_PATCHER_GUIDED_INSTALL_PAYLOAD_REPORT.json)
[[ -f "$GUIDED_INSTALL_STATUS_REPORT" ]] && package_files+=(.local/reports/BR_PATCHER_GUIDED_INSTALL_STATUS_REPORT.json)
[[ -f "$GUIDED_INSTALL_TRANSACTION_REPORT" ]] && package_files+=(.local/reports/BR_PATCHER_GUIDED_INSTALL_TRANSACTION_REPORT.json)
[[ -f "$GUIDED_LOCAL_BUILD_SELECTION_REPORT" ]] && package_files+=(.local/reports/BR_PATCHER_GUIDED_LOCAL_BUILD_SELECTION_REPORT.json)
[[ -f "$GUIDED_LOCAL_BUILD_PAYLOAD_REPORT" ]] && package_files+=(.local/reports/BR_PATCHER_GUIDED_LOCAL_BUILD_PAYLOAD_REPORT.json)
[[ -f "$GUIDED_LOCAL_BUILD_STATUS_REPORT" ]] && package_files+=(.local/reports/BR_PATCHER_GUIDED_LOCAL_BUILD_STATUS_REPORT.json)
[[ -f "$GUIDED_LOCAL_BUILD_TRANSACTION_REPORT" ]] && package_files+=(.local/reports/BR_PATCHER_GUIDED_LOCAL_BUILD_TRANSACTION_REPORT.json)
[[ -f "$COMPOSED_PAYLOAD_PREVIEW_REPORT" ]] && package_files+=(.local/reports/BR_PATCHER_QUARTET_COMPOSED_PAYLOAD_PREVIEW_REPORT.json)
[[ -f "$COMPOSITION_PREVIEW_REPORT" ]] && package_files+=(.local/reports/BR_PATCHER_QUARTET_COMPOSITION_PREFLIGHT_REPORT.json)
[[ -f "$COMPOSITION_BUILD_REPORT" ]] && package_files+=(.local/reports/BR_PATCHER_QUARTET_COMPOSITION_BUILD_REPORT.json)
[[ -f "$REPORT_DIR/BR_PATCHER_DEVELOPMENT_PLAN.json" ]] && package_files+=(.local/reports/BR_PATCHER_DEVELOPMENT_PLAN.json)

tar -C "$PROJECT_ROOT" --zstd -cf "$REPORT_PACKAGE" "${package_files[@]}"

printf '\nValidated unified Windows/Linux patcher architecture.\n'
printf 'Configured game installations were only detected and previewed; guided write operations ran exclusively on isolated synthetic files.\n'
printf 'The interactive/non-interactive guided install and complete-removal paths, automatic guided local Translation rebuild, transaction engine, explicit commit/rollback, versioned persistent baselines, active installation-state tracking, one-command local Translation workflow, payload preview, prepare/discard, Quartet composition preflight, content-aware composer and composed-payload preview were validated.\n'
printf 'Created report package:\n  %s\n' "$REPORT_PACKAGE"
