#!/usr/bin/env python3
"""Stage 144: isolate, activate, inspect and roll back the Gamma Fast Test Lab profile.

This module never edits a game archive itself. It validates the immutable stage-143
profile-preparation evidence and the local profile manifest/payload, then validates
metadata emitted by the existing core-owned PACK10_01 transaction route. The shell
wrapper invokes that existing route for activation/status/rollback.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import subprocess
import tempfile
from pathlib import Path, PurePosixPath
from typing import Any, Iterable, Mapping, Sequence

TOOL_VERSION = "0.1.62"
GAMMA_PROFILE_ID = "fast_test_kps_posteffectgamma_target_dword_3c4565adce04"
GLOWLIGHT_PROFILE_ID = "fast_test_kps_posteffectglowlight_target_dword_61389ebb65bb"
TARGET_RELATIVE_PATH = "Data/PACK10_01.PAK"
BASELINE_SHA256 = "cc44e01cca2b1f68714dbe6a3c51b3e3894e612add1e440285e77fd4da5a00b1"
BASELINE_SIZE = 194151990
GAMMA_PROFILE_SHA256 = "3356e32f1660ab9f301c74d1d105a032a8f55566deeb4ec30394d3afe43f3b14"
GAMMA_PROFILE_SIZE = 194149643
STAGE143_REPORT = "BR_quartet_restoration_effect_posteffect_kps_fast_test_lab_profile_preparation_evidence.tar.zst"
STAGE143_SHA256 = "a104e1129e2f6dc544fb16b43cfaaae95c77617dea1d7540beebf958e2d87c86"
STAGE143_ROOT = "effect_posteffect_kps_fast_test_lab_profile_preparation_evidence"
ACTIVATION_REPORT_DIR = "kps_gamma_fast_test_lab_activation_evidence"
ACTIVATION_REPORT_NAME = "BR_quartet_restoration_kps_gamma_fast_test_lab_activation_evidence.tar.zst"
ROLLBACK_REPORT_DIR = "kps_gamma_fast_test_lab_rollback_evidence"
ROLLBACK_REPORT_NAME = "BR_quartet_restoration_kps_gamma_fast_test_lab_rollback_evidence.tar.zst"
MANIFEST_RELATIVE_PATH = f".local/build/quartet_restoration/core_profiles/fast_test_lab/{GAMMA_PROFILE_ID}.json"
STATE_RELATIVE_PATH = ".local/state/core_unified_patcher/quartet_shader_profile.json"
CORE_REPORT_RELATIVE_PATH = ".local/reports/core/BR_QUARTET_SHADER_PROFILE_TRANSACTION_REPORT.json"
FORBIDDEN_REPORT_EXTENSIONS = (
    ".pak", ".kps", ".dxbc", ".elixir", ".elixir.gz", ".g1e", ".g1em",
    ".g1m", ".g1s", ".g1t", ".ebd", ".ebm",
)
OPEN_STATES = {"prepared", "active", "rolling_back", "activation_uncertain", "rollback_uncertain"}


class GammaFastTestError(RuntimeError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise GammaFastTestError(message)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def safe_relative(value: str, label: str) -> str:
    path = PurePosixPath(str(value).replace("\\", "/"))
    require(path.parts and not path.is_absolute() and ".." not in path.parts, f"unsafe {label}: {value}")
    return path.as_posix()


def read_json(path: Path, label: str) -> dict[str, Any]:
    require(path.is_file(), f"missing {label}: {path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise GammaFastTestError(f"cannot parse {label}: {path}: {exc}") from exc
    require(isinstance(value, dict), f"{label} must be a JSON object")
    return value


def read_tsv(path: Path) -> list[dict[str, str]]:
    require(path.is_file(), f"missing TSV: {path}")
    with path.open(encoding="utf-8", newline="") as handle:
        return [dict(row) for row in csv.DictReader(handle, delimiter="\t")]


def write_tsv(path: Path, fields: Sequence[str], rows: Iterable[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(fields), delimiter="\t", lineterminator="\n", extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fields})


def atomic_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + ".tmp")
    temp.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temp, path)


def extract_stage143(report_root: Path, temporary_root: Path) -> Path:
    archive = report_root / STAGE143_REPORT
    require(archive.is_file(), f"missing stage-143 evidence: {archive}")
    actual = sha256_file(archive)
    require(actual == STAGE143_SHA256, f"stage-143 SHA-256 drift: {actual}")
    listed = subprocess.run(["tar", "--zstd", "-tf", str(archive)], text=True, capture_output=True)
    require(listed.returncode == 0, listed.stderr.strip() or "cannot list stage-143 evidence")
    names = [safe_relative(line.strip(), "stage-143 member") for line in listed.stdout.splitlines() if line.strip()]
    require(names and {PurePosixPath(name).parts[0] for name in names} == {STAGE143_ROOT}, "unexpected stage-143 archive root")
    require(not any(name.casefold().endswith(FORBIDDEN_REPORT_EXTENSIONS) for name in names), "proprietary payload extension in stage-143 evidence")
    extracted = subprocess.run(["tar", "--zstd", "-xf", str(archive), "-C", str(temporary_root)], text=True, capture_output=True)
    require(extracted.returncode == 0, extracted.stderr.strip() or "cannot extract stage-143 evidence")
    root = temporary_root / STAGE143_ROOT
    require(root.is_dir(), "missing extracted stage-143 root")
    return root


def validate_stage143(report_root: Path) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="stage144-stage143-") as td:
        root = extract_stage143(report_root, Path(td))
        summary = read_json(root / "SUMMARY.json", "stage-143 SUMMARY")
        expected = {
            "tool_version": "0.1.61",
            "status": "two_isolated_runtime_unvalidated_kps_fast_test_lab_profiles_built_and_reextracted_no_install",
            "target_relative_path": TARGET_RELATIVE_PATH,
            "baseline_sha256": BASELINE_SHA256,
            "baseline_size": BASELINE_SIZE,
            "fast_test_profile_rows": 2,
            "gamma_profile_rows": 1,
            "glowlight_profile_rows": 1,
            "runtime_validated_profile_rows_created": 0,
            "normal_composer_eligible_profile_rows_created": 0,
            "profile_pak_rows_built": 2,
            "profile_pak_full_reextraction_pass_rows": 2,
            "automatic_activation_rows": 0,
            "installed_artifact_rows": 0,
            "skipped_rows": 0,
        }
        for key, value in expected.items():
            require(summary.get(key) == value, f"stage-143 summary mismatch: {key}: {summary.get(key)!r} != {value!r}")
        policy = summary.get("policy") or {}
        for key in ("profile_paks_fully_reextracted", "test_order_gamma_before_glowlight", "rollback_required_between_variants"):
            require(policy.get(key) is True, f"stage-143 policy not true: {key}")
        for key in ("profiles_runtime_validated", "profiles_normal_composer_eligible", "automatic_activation_authorized", "installed_game_modified"):
            require(policy.get(key) is False, f"stage-143 policy not false: {key}")
        profiles = read_tsv(root / "FAST_TEST_LAB_PROFILES.tsv")
        require(len(profiles) == 2, "stage-143 profile count drift")
        by_id = {row["profile_id"]: row for row in profiles}
        require(set(by_id) == {GAMMA_PROFILE_ID, GLOWLIGHT_PROFILE_ID}, "stage-143 profile IDs drift")
        gamma = by_id[GAMMA_PROFILE_ID]
        glow = by_id[GLOWLIGHT_PROFILE_ID]
        require(gamma["test_order"] == "1" and gamma["member_name"] == "PostEffectGamma.kps", "Gamma order or member drift")
        require(glow["test_order"] == "2" and glow["member_name"] == "PostEffectGlowLight.kps", "GlowLight order or member drift")
        require(gamma["profile_pak_sha256"] == GAMMA_PROFILE_SHA256 and int(gamma["profile_pak_size"]) == GAMMA_PROFILE_SIZE, "Gamma profile hash or size drift")
        for row in profiles:
            require(row["runtime_validated"] == "False" and row["normal_composer_eligible"] == "False" and row["installed"] == "False", f"unsafe stage-143 profile flags: {row['profile_id']}")
        order = read_tsv(root / "FAST_TEST_ORDER.tsv")
        require(len(order) == 2 and order[0]["profile_id"] == GAMMA_PROFILE_ID and order[1]["profile_id"] == GLOWLIGHT_PROFILE_ID, "Fast Test Lab order drift")
        require(all(row["rollback_required_before_next_variant"] == "True" for row in order), "rollback contract drift")
        return {"summary": summary, "gamma": gamma, "glowlight": glow}


def validate_manifest_and_payload(project_root: Path, gamma_row: Mapping[str, str]) -> tuple[dict[str, Any], Path]:
    manifest_path = project_root / MANIFEST_RELATIVE_PATH
    manifest = read_json(manifest_path, "Gamma manifest")
    expected = {
        "schema_version": 1,
        "profile_id": GAMMA_PROFILE_ID,
        "target_relative_path": TARGET_RELATIVE_PATH,
        "baseline_sha256": BASELINE_SHA256,
        "baseline_size": BASELINE_SIZE,
        "profile_sha256": GAMMA_PROFILE_SHA256,
        "profile_size": GAMMA_PROFILE_SIZE,
        "changed_member_count": 1,
        "runtime_validated": False,
        "workstream_id": "quartet_restoration",
    }
    for key, value in expected.items():
        require(manifest.get(key) == value, f"Gamma manifest mismatch: {key}: {manifest.get(key)!r} != {value!r}")
    require(manifest.get("changed_members") == ["data/b1/x64/posteffect/pe_pack.elixir.gz"], "Gamma changed member drift")
    require(str(manifest.get("local_profile_path", "")) == gamma_row["local_profile_path"], "Gamma local profile path drift")
    profile_path = project_root / safe_relative(str(manifest["local_profile_path"]), "Gamma local profile path")
    require(profile_path.is_file(), f"missing Gamma profile PAK: {profile_path}")
    require(profile_path.stat().st_size == GAMMA_PROFILE_SIZE, "Gamma profile PAK size drift")
    require(sha256_file(profile_path) == GAMMA_PROFILE_SHA256, "Gamma profile PAK SHA-256 drift")
    return manifest, profile_path


def inspect_state_files(project_root: Path) -> dict[str, Any]:
    paths = {
        "event": project_root / ".local/state/core_unified_patcher/quartet_event_profile.json",
        "shader": project_root / STATE_RELATIVE_PATH,
        "field": project_root / ".local/state/core_unified_patcher/quartet_field_profile.json",
    }
    result: dict[str, Any] = {}
    for kind, path in paths.items():
        if not path.is_file():
            result[kind] = None
            continue
        value = read_json(path, f"{kind} transaction state")
        result[kind] = value
    return result


def preflight(project_root: Path, quartet_root: Path, report_root: Path) -> dict[str, Any]:
    require(project_root.is_dir(), f"invalid project root: {project_root}")
    require(quartet_root.is_dir(), f"invalid Quartet root: {quartet_root}")
    version = (project_root / "workstreams/quartet_restoration/VERSION").read_text(encoding="utf-8").strip()
    require(version == TOOL_VERSION, f"quartet_restoration version must be {TOOL_VERSION}, got {version}")
    stage143 = validate_stage143(report_root)
    manifest, profile_path = validate_manifest_and_payload(project_root, stage143["gamma"])
    installed = quartet_root / TARGET_RELATIVE_PATH
    require(installed.is_file(), f"missing installed target: {installed}")
    installed_hash = sha256_file(installed)
    installed_size = installed.stat().st_size
    states = inspect_state_files(project_root)
    shader = states["shader"]
    if shader and str(shader.get("status")) in OPEN_STATES:
        require(shader.get("profile_id") == GAMMA_PROFILE_ID, f"another PACK10_01 profile is open: {shader.get('profile_id')}")
        require(shader.get("status") == "active", f"Gamma transaction is open but not safely active: {shader.get('status')}")
        require(installed_hash == GAMMA_PROFILE_SHA256 and installed_size == GAMMA_PROFILE_SIZE, "active Gamma state does not match installed target")
        mode = "already_active"
    else:
        require(installed_hash == BASELINE_SHA256 and installed_size == BASELINE_SIZE, f"installed PACK10_01 baseline drift: {installed_hash} ({installed_size})")
        mode = "activate"
    for kind in ("event", "field"):
        state = states[kind]
        if state and str(state.get("status")) in OPEN_STATES:
            raise GammaFastTestError(f"open {kind} profile transaction blocks Gamma: {state.get('profile_id')} ({state.get('status')})")
    core_script = project_root / "Blue_Reflection_Patcher/cmd/br_quartet_shader_profile.sh"
    require(core_script.is_file(), f"missing core shader profile route: {core_script}")
    return {
        "mode": mode,
        "version": version,
        "installed_sha256": installed_hash,
        "installed_size": installed_size,
        "manifest": manifest,
        "profile_path": str(profile_path),
        "stage143": stage143,
    }


def validate_active(project_root: Path, quartet_root: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    installed = quartet_root / TARGET_RELATIVE_PATH
    require(installed.is_file(), f"missing installed target: {installed}")
    require(installed.stat().st_size == GAMMA_PROFILE_SIZE, "active Gamma target size drift")
    require(sha256_file(installed) == GAMMA_PROFILE_SHA256, "active Gamma target hash drift")
    state = read_json(project_root / STATE_RELATIVE_PATH, "shader transaction state")
    require(state.get("status") == "active", f"shader transaction is not active: {state.get('status')}")
    require(state.get("profile_id") == GAMMA_PROFILE_ID, f"unexpected active profile: {state.get('profile_id')}")
    require(state.get("target_relative_path") == TARGET_RELATIVE_PATH, "active target path drift")
    require(state.get("baseline_sha256") == BASELINE_SHA256, "active baseline hash drift")
    require(state.get("active_profile_sha256") == GAMMA_PROFILE_SHA256, "active profile hash drift")
    require(state.get("runtime_validated") is False, "Gamma was promoted before runtime validation")
    report = read_json(project_root / CORE_REPORT_RELATIVE_PATH, "core transaction report")
    require(report.get("status") == "ok", f"core activation report status: {report.get('status')}")
    require(report.get("operation") in {"activate", "activate_recovered", "status"}, f"unexpected core report operation: {report.get('operation')}")
    require(report.get("profile_id") == GAMMA_PROFILE_ID, "core report profile drift")
    require(report.get("state_status") == "active", f"core report state is not active: {report.get('state_status')}")
    require(report.get("runtime_validated") is False, "core report promoted Gamma unexpectedly")
    return state, report


def validate_rolled_back(project_root: Path, quartet_root: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    installed = quartet_root / TARGET_RELATIVE_PATH
    require(installed.is_file(), f"missing installed target: {installed}")
    require(installed.stat().st_size == BASELINE_SIZE, "rolled-back baseline size drift")
    require(sha256_file(installed) == BASELINE_SHA256, "rolled-back baseline hash drift")
    state = read_json(project_root / STATE_RELATIVE_PATH, "shader transaction state")
    require(state.get("status") == "rolled_back", f"shader transaction was not rolled back: {state.get('status')}")
    require(state.get("profile_id") == GAMMA_PROFILE_ID, f"rollback belongs to unexpected profile: {state.get('profile_id')}")
    report = read_json(project_root / CORE_REPORT_RELATIVE_PATH, "core rollback report")
    require(report.get("status") == "ok", f"core rollback report status: {report.get('status')}")
    require(report.get("operation") in {"rollback", "status"}, f"unexpected rollback report operation: {report.get('operation')}")
    require(report.get("profile_id") == GAMMA_PROFILE_ID, "rollback report profile drift")
    require(report.get("state_status") == "rolled_back", f"rollback report state drift: {report.get('state_status')}")
    return state, report


def make_archive(source: Path, output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    temp = output.with_name(output.name + ".tmp")
    temp.unlink(missing_ok=True)
    cp = subprocess.run(["tar", "--zstd", "-cf", str(temp), "-C", str(source.parent), source.name], text=True, capture_output=True)
    require(cp.returncode == 0, cp.stderr.strip() or "cannot create evidence archive")
    os.replace(temp, output)


def write_report(
    project_root: Path,
    quartet_root: Path,
    report_root: Path,
    *,
    operation: str,
) -> Path:
    require(operation in {"activation", "rollback"}, "unsupported report operation")
    stage143 = validate_stage143(report_root)
    validate_manifest_and_payload(project_root, stage143["gamma"])
    if operation == "activation":
        state, core_report = validate_active(project_root, quartet_root)
        report_dir_name = ACTIVATION_REPORT_DIR
        report_name = ACTIVATION_REPORT_NAME
        status = "gamma_fast_test_lab_profile_active_runtime_result_pending_rollback_required"
        installed_hash = GAMMA_PROFILE_SHA256
        installed_size = GAMMA_PROFILE_SIZE
        next_action = "Launch Quartet, start New Game, record stability and any visible Gamma/posteffect difference, exit the game completely, then run the stage-144 rollback command before any other profile test."
    else:
        state, core_report = validate_rolled_back(project_root, quartet_root)
        report_dir_name = ROLLBACK_REPORT_DIR
        report_name = ROLLBACK_REPORT_NAME
        status = "gamma_fast_test_lab_profile_rolled_back_exact_baseline_restored"
        installed_hash = BASELINE_SHA256
        installed_size = BASELINE_SIZE
        next_action = "Upload activation and rollback evidence together with the observed runtime result. Do not activate GlowLight until the Gamma result is recorded and reviewed."
    output_dir = report_root / report_dir_name
    if output_dir.exists():
        for child in output_dir.iterdir():
            if child.is_dir():
                import shutil
                shutil.rmtree(child)
            else:
                child.unlink()
    output_dir.mkdir(parents=True, exist_ok=True)
    atomic_json(output_dir / "CORE_TRANSACTION_STATE.json", state)
    atomic_json(output_dir / "CORE_TRANSACTION_REPORT.json", core_report)
    write_tsv(output_dir / "INPUT_HASHES.tsv", ["input_id", "relative_path", "sha256", "verified"], [
        {"input_id": "stage143_report", "relative_path": f".local/reports/quartet_restoration/{STAGE143_REPORT}", "sha256": STAGE143_SHA256, "verified": True},
        {"input_id": "gamma_profile_pak", "relative_path": stage143["gamma"]["local_profile_path"], "sha256": GAMMA_PROFILE_SHA256, "verified": True},
        {"input_id": "installed_pack10_01", "relative_path": TARGET_RELATIVE_PATH, "sha256": installed_hash, "verified": True},
    ])
    write_tsv(output_dir / "RUNTIME_TEST_MATRIX.tsv", ["test_order", "variant", "required_action", "expected_safety_gate", "result_status"], [
        {"test_order": 1, "variant": "gamma", "required_action": "launch game and start New Game; observe boot, first cutscene, transition after cutscene and visible posteffect changes", "expected_safety_gate": "Gamma only; no GlowLight; runtime_validated remains false", "result_status": "pending" if operation == "activation" else "user_observation_required"},
        {"test_order": 2, "variant": "rollback", "required_action": "exit game completely and restore exact PACK10_01 baseline", "expected_safety_gate": "baseline SHA-256 restored before any other profile", "result_status": "pending" if operation == "activation" else "passed"},
        {"test_order": 3, "variant": "glowlight", "required_action": "blocked until Gamma activation, observation and rollback are reviewed", "expected_safety_gate": "must remain inactive", "result_status": "blocked"},
    ])
    summary = {
        "type": f"br_quartet_restoration_kps_gamma_fast_test_lab_{operation}_evidence_summary",
        "format_version": 1,
        "tool_version": TOOL_VERSION,
        "status": status,
        "operation": operation,
        "profile_id": GAMMA_PROFILE_ID,
        "blocked_profile_id": GLOWLIGHT_PROFILE_ID,
        "target_relative_path": TARGET_RELATIVE_PATH,
        "baseline_sha256": BASELINE_SHA256,
        "baseline_size": BASELINE_SIZE,
        "gamma_profile_sha256": GAMMA_PROFILE_SHA256,
        "gamma_profile_size": GAMMA_PROFILE_SIZE,
        "installed_target_sha256": installed_hash,
        "installed_target_size": installed_size,
        "stage143_report_sha256": STAGE143_SHA256,
        "runtime_validated": False,
        "runtime_result_recorded": False,
        "glowlight_activated": False,
        "rollback_required": operation == "activation",
        "exact_baseline_restored": operation == "rollback",
        "core_transaction_id": state.get("transaction_id", ""),
        "core_state_status": state.get("status", ""),
        "skipped_rows": 0,
        "policy": {
            "existing_core_transaction_route_used": True,
            "only_gamma_profile_selected": True,
            "glowlight_activation_authorized": False,
            "runtime_validation_inferred": False,
            "runtime_validated_flag_changed": False,
            "normal_composer_modified": False,
            "core_source_modified": False,
            "translation_modified": False,
            "legacy_dlc_modified": False,
            "git_modified": False,
            "proprietary_payloads_in_report": False,
            "rollback_required_before_next_variant": True,
        },
        "next_action": next_action,
    }
    atomic_json(output_dir / "SUMMARY.json", summary)
    archive = report_root / report_name
    archive.unlink(missing_ok=True)
    make_archive(output_dir, archive)
    return archive


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("preflight", "collect-activation", "collect-rollback"))
    parser.add_argument("--project-root", required=True, type=Path)
    parser.add_argument("--quartet-root", required=True, type=Path)
    parser.add_argument("--report-root", type=Path)
    args = parser.parse_args()
    project = args.project_root.resolve()
    quartet = args.quartet_root.resolve()
    report_root = (args.report_root or project / ".local/reports/quartet_restoration").resolve()
    if args.mode == "preflight":
        result = preflight(project, quartet, report_root)
        print(json.dumps({"status": "ok", "mode": result["mode"], "profile_id": GAMMA_PROFILE_ID}, sort_keys=True))
    elif args.mode == "collect-activation":
        archive = write_report(project, quartet, report_root, operation="activation")
        print(archive)
    else:
        archive = write_report(project, quartet, report_root, operation="rollback")
        print(archive)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
