#!/usr/bin/env python3
"""Stage 146: isolated GlowLight Fast Test Lab harness.

This stage prepares and validates a GlowLight-only runtime transaction using the
existing core-owned PACK10_01 shader-profile route. It never edits game archives
itself. Activation remains impossible from the shell wrapper without an explicit
user-authorization token. PACK10_03 is guarded by hash/size across activation and
rollback so the independently validated bathroom-water profile is not disturbed.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Iterable, Mapping, Sequence

TOOL_VERSION = "0.1.64"
GAMMA_PROFILE_ID = "fast_test_kps_posteffectgamma_target_dword_3c4565adce04"
GLOWLIGHT_PROFILE_ID = "fast_test_kps_posteffectglowlight_target_dword_61389ebb65bb"
TARGET_RELATIVE_PATH = "Data/PACK10_01.PAK"
PROTECTED_PACK10_03_RELATIVE_PATH = "Data/PACK10_03.PAK"
BASELINE_SHA256 = "cc44e01cca2b1f68714dbe6a3c51b3e3894e612add1e440285e77fd4da5a00b1"
BASELINE_SIZE = 194151990
GLOWLIGHT_PROFILE_SHA256 = "ecc301ef0dd0e99b2149ecd4509d6766c1b635d0eb6a3852aa29bb46a3482b9e"
GLOWLIGHT_PROFILE_SIZE = 194149646
STAGE143_REPORT = "BR_quartet_restoration_effect_posteffect_kps_fast_test_lab_profile_preparation_evidence.tar.zst"
STAGE143_SHA256 = "a104e1129e2f6dc544fb16b43cfaaae95c77617dea1d7540beebf958e2d87c86"
STAGE143_ROOT = "effect_posteffect_kps_fast_test_lab_profile_preparation_evidence"
STAGE145_REPORT = "BR_quartet_restoration_gamma_runtime_observation_glowlight_readiness_evidence.tar.zst"
STAGE145_SHA256 = "1299fd78cda821b887a975e2fd69538cab73c931633e395622c8406be9ee841a"
STAGE145_ROOT = "gamma_runtime_observation_glowlight_readiness_evidence"
MANIFEST_RELATIVE_PATH = f".local/build/quartet_restoration/core_profiles/fast_test_lab/{GLOWLIGHT_PROFILE_ID}.json"
STATE_RELATIVE_PATH = ".local/state/core_unified_patcher/quartet_shader_profile.json"
CORE_REPORT_RELATIVE_PATH = ".local/reports/core/BR_QUARTET_SHADER_PROFILE_TRANSACTION_REPORT.json"
GUARD_RELATIVE_PATH = ".local/state/quartet_restoration/glowlight_fast_test_pack10_03_guard.json"
ACTIVATION_REPORT_DIR = "kps_glowlight_fast_test_lab_activation_evidence"
ACTIVATION_REPORT_NAME = "BR_quartet_restoration_kps_glowlight_fast_test_lab_activation_evidence.tar.zst"
ROLLBACK_REPORT_DIR = "kps_glowlight_fast_test_lab_rollback_evidence"
ROLLBACK_REPORT_NAME = "BR_quartet_restoration_kps_glowlight_fast_test_lab_rollback_evidence.tar.zst"
OPEN_STATES = {"prepared", "active", "rolling_back", "activation_uncertain", "rollback_uncertain"}
FORBIDDEN_REPORT_EXTENSIONS = (
    ".pak", ".kps", ".dxbc", ".elixir", ".elixir.gz", ".g1e", ".g1em",
    ".g1m", ".g1s", ".g1t", ".ebd", ".ebm",
)


class GlowLightFastTestError(RuntimeError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise GlowLightFastTestError(message)


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def safe_relative(value: str, label: str) -> str:
    path = PurePosixPath(str(value).replace("\\", "/"))
    require(path.parts and not path.is_absolute() and ".." not in path.parts, f"unsafe {label}: {value}")
    return path.as_posix()


def read_json(path: Path, label: str) -> dict[str, Any]:
    require(path.is_file(), f"missing {label}: {path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise GlowLightFastTestError(f"cannot parse {label}: {path}: {exc}") from exc
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


def extract_report(archive: Path, expected_sha256: str, expected_root: str, temporary_root: Path, label: str) -> Path:
    require(archive.is_file(), f"missing {label}: {archive}")
    actual = sha256_file(archive)
    require(actual == expected_sha256, f"{label} SHA-256 drift: {actual}")
    listed = subprocess.run(["tar", "--zstd", "-tf", str(archive)], text=True, capture_output=True)
    require(listed.returncode == 0, listed.stderr.strip() or f"cannot list {label}")
    names = [safe_relative(line.strip(), f"{label} member") for line in listed.stdout.splitlines() if line.strip()]
    require(names and {PurePosixPath(name).parts[0] for name in names} == {expected_root}, f"unexpected {label} archive root")
    require(not any(name.casefold().endswith(FORBIDDEN_REPORT_EXTENSIONS) for name in names), f"proprietary payload extension in {label}")
    cp = subprocess.run(["tar", "--zstd", "-xf", str(archive), "-C", str(temporary_root)], text=True, capture_output=True)
    require(cp.returncode == 0, cp.stderr.strip() or f"cannot extract {label}")
    root = temporary_root / expected_root
    require(root.is_dir(), f"missing extracted {label} root")
    return root


def validate_stage145(report_root: Path) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="stage146-stage145-") as td:
        root = extract_report(report_root / STAGE145_REPORT, STAGE145_SHA256, STAGE145_ROOT, Path(td), "stage-145 evidence")
        summary = read_json(root / "SUMMARY.json", "stage-145 SUMMARY")
        expected = {
            "tool_version": "0.1.63",
            "status": "gamma_runtime_stable_visual_effect_unconfirmed_canonically_verified_glowlight_separate_test_technically_ready_but_not_authorized",
            "gamma_runtime_tested": True,
            "gamma_runtime_stable": True,
            "gamma_visible_effect_confirmed": False,
            "gamma_runtime_validated": False,
            "gamma_production_eligible": False,
            "gamma_retest_required": False,
            "exact_pack10_01_baseline_restored": True,
            "glowlight_runtime_tested": False,
            "glowlight_runtime_validated": False,
            "glowlight_production_eligible": False,
            "glowlight_separate_test_technically_ready_after_exact_baseline_preflight": True,
            "glowlight_activation_authorized": False,
            "glowlight_requires_separate_user_authorization": True,
            "glowlight_profile_id": GLOWLIGHT_PROFILE_ID,
            "glowlight_profile_sha256": GLOWLIGHT_PROFILE_SHA256,
            "pack10_01_baseline_sha256": BASELINE_SHA256,
            "skipped_rows": 0,
        }
        for key, value in expected.items():
            require(summary.get(key) == value, f"stage-145 summary mismatch: {key}: {summary.get(key)!r} != {value!r}")
        policy = summary.get("policy") or {}
        require(policy.get("glowlight_must_be_tested_separately") is True, "stage-145 separate-test policy drift")
        require(policy.get("glowlight_exact_pack10_01_baseline_preflight_required") is True, "stage-145 baseline-preflight policy drift")
        require(policy.get("glowlight_exact_rollback_required") is True, "stage-145 rollback policy drift")
        require(policy.get("pack10_03_must_not_be_modified") is True, "stage-145 PACK10_03 policy drift")
        return summary


def validate_gamma_registry(project_root: Path) -> dict[str, Any]:
    registry = read_json(project_root / "workstreams/quartet_restoration/RUNTIME_VALIDATION_REGISTRY.json", "runtime validation registry")
    results = registry.get("fast_test_results") or {}
    gamma = results.get(GAMMA_PROFILE_ID)
    require(isinstance(gamma, dict), "canonical Gamma Fast Test result missing")
    require(gamma.get("runtime_status") == "runtime_stable_visual_effect_unconfirmed", "Gamma runtime status drift")
    require(gamma.get("runtime_tested") is True and gamma.get("runtime_stable") is True, "Gamma stability record drift")
    require(gamma.get("visible_effect_confirmed") is False, "Gamma visual result drift")
    require(gamma.get("runtime_validated") is False and gamma.get("production_eligible") is False, "Gamma was unexpectedly promoted")
    require(gamma.get("exact_pack10_01_baseline_restored") is True, "Gamma exact rollback record drift")
    require(gamma.get("pack10_01_baseline_sha256") == BASELINE_SHA256, "Gamma baseline hash drift")
    require(GLOWLIGHT_PROFILE_ID not in results, "GlowLight runtime result already exists; do not retest automatically")
    policy = registry.get("policy") or {}
    require(policy.get("glowlight_requires_separate_runtime_evidence") is True, "GlowLight evidence policy drift")
    require(policy.get("glowlight_activation_requires_separate_user_authorization") is True, "GlowLight authorization policy drift")
    return registry


def validate_stage143_glowlight(project_root: Path, report_root: Path) -> tuple[dict[str, Any], Path, dict[str, str]]:
    with tempfile.TemporaryDirectory(prefix="stage146-stage143-") as td:
        root = extract_report(report_root / STAGE143_REPORT, STAGE143_SHA256, STAGE143_ROOT, Path(td), "stage-143 evidence")
        rows = read_tsv(root / "FAST_TEST_LAB_PROFILES.tsv")
        require(len(rows) == 2, "stage-143 profile count drift")
        by_id = {row["profile_id"]: row for row in rows}
        require(set(by_id) == {GAMMA_PROFILE_ID, GLOWLIGHT_PROFILE_ID}, "stage-143 profile IDs drift")
        glow = by_id[GLOWLIGHT_PROFILE_ID]
        require(glow.get("test_order") == "2", "GlowLight stage-143 test order drift")
        require(glow.get("member_name") == "PostEffectGlowLight.kps", "GlowLight member drift")
        require(glow.get("profile_pak_sha256") == GLOWLIGHT_PROFILE_SHA256, "GlowLight stage-143 PAK hash drift")
        require(int(glow.get("profile_pak_size", "-1")) == GLOWLIGHT_PROFILE_SIZE, "GlowLight stage-143 PAK size drift")
        require(glow.get("runtime_validated") == "False" and glow.get("normal_composer_eligible") == "False" and glow.get("installed") == "False", "unsafe GlowLight stage-143 flags")
        order = read_tsv(root / "FAST_TEST_ORDER.tsv")
        require(len(order) == 2 and order[1].get("profile_id") == GLOWLIGHT_PROFILE_ID, "GlowLight test-order row drift")
        require(order[1].get("must_be_tested_alone") == "True", "GlowLight must-be-tested-alone policy drift")
        require(order[1].get("rollback_required_before_next_variant") == "True", "GlowLight rollback policy drift")
        require(order[1].get("automatic_activation_authorized") == "False", "GlowLight automatic activation unexpectedly authorized")
        manifest_path = project_root / MANIFEST_RELATIVE_PATH
        manifest = read_json(manifest_path, "GlowLight manifest")
        expected = {
            "schema_version": 1,
            "profile_id": GLOWLIGHT_PROFILE_ID,
            "target_relative_path": TARGET_RELATIVE_PATH,
            "baseline_sha256": BASELINE_SHA256,
            "baseline_size": BASELINE_SIZE,
            "profile_sha256": GLOWLIGHT_PROFILE_SHA256,
            "profile_size": GLOWLIGHT_PROFILE_SIZE,
            "changed_member_count": 1,
            "runtime_validated": False,
            "workstream_id": "quartet_restoration",
        }
        for key, value in expected.items():
            require(manifest.get(key) == value, f"GlowLight manifest mismatch: {key}: {manifest.get(key)!r} != {value!r}")
        require(manifest.get("changed_members") == ["data/b1/x64/posteffect/pe_pack.elixir.gz"], "GlowLight changed member drift")
        require(str(manifest.get("local_profile_path", "")) == glow.get("local_profile_path"), "GlowLight local profile path drift")
        profile_path = project_root / safe_relative(str(manifest["local_profile_path"]), "GlowLight local profile path")
        require(profile_path.is_file(), f"missing GlowLight profile PAK: {profile_path}")
        require(profile_path.stat().st_size == GLOWLIGHT_PROFILE_SIZE, "GlowLight profile PAK size drift")
        require(sha256_file(profile_path) == GLOWLIGHT_PROFILE_SHA256, "GlowLight profile PAK SHA-256 drift")
        return manifest, profile_path, dict(glow)


def inspect_state_files(project_root: Path) -> dict[str, Any]:
    paths = {
        "event": project_root / ".local/state/core_unified_patcher/quartet_event_profile.json",
        "shader": project_root / STATE_RELATIVE_PATH,
        "field": project_root / ".local/state/core_unified_patcher/quartet_field_profile.json",
    }
    result: dict[str, Any] = {}
    for kind, path in paths.items():
        result[kind] = read_json(path, f"{kind} transaction state") if path.is_file() else None
    return result


def preflight(project_root: Path, quartet_root: Path, report_root: Path) -> dict[str, Any]:
    require(project_root.is_dir(), f"invalid project root: {project_root}")
    require(quartet_root.is_dir(), f"invalid Quartet root: {quartet_root}")
    version = (project_root / "workstreams/quartet_restoration/VERSION").read_text(encoding="utf-8").strip()
    require(version == TOOL_VERSION, f"quartet_restoration version must be {TOOL_VERSION}, got {version}")
    stage145 = validate_stage145(report_root)
    validate_gamma_registry(project_root)
    manifest, profile_path, glow_row = validate_stage143_glowlight(project_root, report_root)
    installed = quartet_root / TARGET_RELATIVE_PATH
    protected = quartet_root / PROTECTED_PACK10_03_RELATIVE_PATH
    require(installed.is_file(), f"missing installed target: {installed}")
    require(protected.is_file(), f"missing protected PACK10_03: {protected}")
    installed_hash, installed_size = sha256_file(installed), installed.stat().st_size
    protected_hash, protected_size = sha256_file(protected), protected.stat().st_size
    states = inspect_state_files(project_root)
    shader = states["shader"]
    if shader and str(shader.get("status")) in OPEN_STATES:
        require(shader.get("profile_id") == GLOWLIGHT_PROFILE_ID, f"another PACK10_01 profile is open: {shader.get('profile_id')}")
        require(shader.get("status") == "active", f"GlowLight transaction is open but not safely active: {shader.get('status')}")
        require(installed_hash == GLOWLIGHT_PROFILE_SHA256 and installed_size == GLOWLIGHT_PROFILE_SIZE, "active GlowLight state does not match installed target")
        mode = "already_active"
    else:
        require(installed_hash == BASELINE_SHA256 and installed_size == BASELINE_SIZE, f"installed PACK10_01 baseline drift: {installed_hash} ({installed_size})")
        mode = "activate"
    for kind in ("event", "field"):
        state = states[kind]
        if state and str(state.get("status")) in OPEN_STATES:
            raise GlowLightFastTestError(f"open {kind} profile transaction blocks GlowLight: {state.get('profile_id')} ({state.get('status')})")
    core_script = project_root / "Blue_Reflection_Patcher/cmd/br_quartet_shader_profile.sh"
    require(core_script.is_file(), f"missing core shader profile route: {core_script}")
    return {
        "mode": mode,
        "version": version,
        "installed_sha256": installed_hash,
        "installed_size": installed_size,
        "pack10_03_sha256": protected_hash,
        "pack10_03_size": protected_size,
        "manifest": manifest,
        "profile_path": str(profile_path),
        "glow_row": glow_row,
        "stage145": stage145,
    }


def prepare_guard(project_root: Path, quartet_root: Path, report_root: Path) -> Path:
    result = preflight(project_root, quartet_root, report_root)
    guard_path = project_root / GUARD_RELATIVE_PATH
    if result["mode"] == "already_active":
        guard = read_json(guard_path, "GlowLight PACK10_03 guard")
        require(guard.get("profile_id") == GLOWLIGHT_PROFILE_ID, "GlowLight guard profile drift")
        require(guard.get("pack10_03_sha256") == result["pack10_03_sha256"], "PACK10_03 changed since GlowLight guard creation")
        require(int(guard.get("pack10_03_size", -1)) == result["pack10_03_size"], "PACK10_03 size changed since GlowLight guard creation")
        return guard_path
    guard = {
        "type": "br_quartet_restoration_glowlight_fast_test_pack10_03_guard",
        "format_version": 1,
        "tool_version": TOOL_VERSION,
        "created_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "profile_id": GLOWLIGHT_PROFILE_ID,
        "target_relative_path": TARGET_RELATIVE_PATH,
        "pack10_01_pre_activation_sha256": result["installed_sha256"],
        "pack10_01_pre_activation_size": result["installed_size"],
        "protected_relative_path": PROTECTED_PACK10_03_RELATIVE_PATH,
        "pack10_03_sha256": result["pack10_03_sha256"],
        "pack10_03_size": result["pack10_03_size"],
        "stage145_report_sha256": STAGE145_SHA256,
        "exact_pack10_01_baseline_verified": True,
        "pack10_03_read_only_guard": True,
    }
    atomic_json(guard_path, guard)
    return guard_path


def validate_pack10_03_guard(project_root: Path, quartet_root: Path) -> dict[str, Any]:
    guard = read_json(project_root / GUARD_RELATIVE_PATH, "GlowLight PACK10_03 guard")
    require(guard.get("profile_id") == GLOWLIGHT_PROFILE_ID, "GlowLight guard profile drift")
    path = quartet_root / PROTECTED_PACK10_03_RELATIVE_PATH
    require(path.is_file(), f"missing protected PACK10_03: {path}")
    require(sha256_file(path) == guard.get("pack10_03_sha256"), "PACK10_03 changed during GlowLight workflow")
    require(path.stat().st_size == int(guard.get("pack10_03_size", -1)), "PACK10_03 size changed during GlowLight workflow")
    return guard


def validate_active(project_root: Path, quartet_root: Path) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    installed = quartet_root / TARGET_RELATIVE_PATH
    require(installed.is_file(), f"missing installed target: {installed}")
    require(installed.stat().st_size == GLOWLIGHT_PROFILE_SIZE, "active GlowLight target size drift")
    require(sha256_file(installed) == GLOWLIGHT_PROFILE_SHA256, "active GlowLight target hash drift")
    guard = validate_pack10_03_guard(project_root, quartet_root)
    state = read_json(project_root / STATE_RELATIVE_PATH, "shader transaction state")
    require(state.get("status") == "active", f"shader transaction is not active: {state.get('status')}")
    require(state.get("profile_id") == GLOWLIGHT_PROFILE_ID, f"unexpected active profile: {state.get('profile_id')}")
    require(state.get("target_relative_path") == TARGET_RELATIVE_PATH, "active target path drift")
    require(state.get("baseline_sha256") == BASELINE_SHA256, "active baseline hash drift")
    require(state.get("active_profile_sha256") == GLOWLIGHT_PROFILE_SHA256, "active profile hash drift")
    require(state.get("runtime_validated") is False, "GlowLight was promoted before runtime validation")
    report = read_json(project_root / CORE_REPORT_RELATIVE_PATH, "core transaction report")
    require(report.get("status") == "ok", f"core activation report status: {report.get('status')}")
    require(report.get("operation") in {"activate", "activate_recovered", "status"}, f"unexpected core report operation: {report.get('operation')}")
    require(report.get("profile_id") == GLOWLIGHT_PROFILE_ID, "core report profile drift")
    require(report.get("state_status") == "active", f"core report state is not active: {report.get('state_status')}")
    require(report.get("runtime_validated") is False, "core report promoted GlowLight unexpectedly")
    return state, report, guard


def validate_rolled_back(project_root: Path, quartet_root: Path) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    installed = quartet_root / TARGET_RELATIVE_PATH
    require(installed.is_file(), f"missing installed target: {installed}")
    require(installed.stat().st_size == BASELINE_SIZE, "rolled-back baseline size drift")
    require(sha256_file(installed) == BASELINE_SHA256, "rolled-back baseline hash drift")
    guard = validate_pack10_03_guard(project_root, quartet_root)
    state = read_json(project_root / STATE_RELATIVE_PATH, "shader transaction state")
    require(state.get("status") == "rolled_back", f"shader transaction was not rolled back: {state.get('status')}")
    require(state.get("profile_id") == GLOWLIGHT_PROFILE_ID, f"rollback belongs to unexpected profile: {state.get('profile_id')}")
    report = read_json(project_root / CORE_REPORT_RELATIVE_PATH, "core rollback report")
    require(report.get("status") == "ok", f"core rollback report status: {report.get('status')}")
    require(report.get("operation") in {"rollback", "status"}, f"unexpected rollback report operation: {report.get('operation')}")
    require(report.get("profile_id") == GLOWLIGHT_PROFILE_ID, "rollback report profile drift")
    require(report.get("state_status") == "rolled_back", f"rollback report state drift: {report.get('state_status')}")
    return state, report, guard


def make_archive(source: Path, output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    temp = output.with_name(output.name + ".tmp")
    temp.unlink(missing_ok=True)
    cp = subprocess.run(["tar", "--zstd", "-cf", str(temp), "-C", str(source.parent), source.name], text=True, capture_output=True)
    require(cp.returncode == 0, cp.stderr.strip() or "cannot create evidence archive")
    os.replace(temp, output)


def write_report(project_root: Path, quartet_root: Path, report_root: Path, *, operation: str) -> Path:
    require(operation in {"activation", "rollback"}, "unsupported report operation")
    validate_stage145(report_root)
    validate_gamma_registry(project_root)
    _, profile_path, _ = validate_stage143_glowlight(project_root, report_root)
    if operation == "activation":
        state, core_report, guard = validate_active(project_root, quartet_root)
        report_dir_name, report_name = ACTIVATION_REPORT_DIR, ACTIVATION_REPORT_NAME
        status = "glowlight_fast_test_lab_profile_active_runtime_result_pending_exact_rollback_required"
        installed_hash, installed_size = GLOWLIGHT_PROFILE_SHA256, GLOWLIGHT_PROFILE_SIZE
        next_action = "Launch Quartet and use the available no-save-required New Game route. Observe stability and any clearly distinguishable GlowLight/posteffect change. Exit the game completely, then run the stage-146 rollback command. Do not modify PACK10_03."
    else:
        state, core_report, guard = validate_rolled_back(project_root, quartet_root)
        report_dir_name, report_name = ROLLBACK_REPORT_DIR, ROLLBACK_REPORT_NAME
        status = "glowlight_fast_test_lab_profile_rolled_back_exact_pack10_01_baseline_restored_pack10_03_unchanged"
        installed_hash, installed_size = BASELINE_SHA256, BASELINE_SIZE
        next_action = "Upload activation and rollback evidence together with the observed GlowLight runtime result. Keep runtime_validated=false until that explicit observation is reviewed."
    output_dir = report_root / report_dir_name
    if output_dir.exists():
        import shutil
        shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    atomic_json(output_dir / "CORE_TRANSACTION_STATE.json", state)
    atomic_json(output_dir / "CORE_TRANSACTION_REPORT.json", core_report)
    atomic_json(output_dir / "PACK10_03_GUARD.json", guard)
    write_tsv(output_dir / "INPUT_HASHES.tsv", ["input_id", "relative_path", "sha256", "verified"], [
        {"input_id": "stage145_report", "relative_path": f".local/reports/quartet_restoration/{STAGE145_REPORT}", "sha256": STAGE145_SHA256, "verified": True},
        {"input_id": "glowlight_profile_pak", "relative_path": str(profile_path.relative_to(project_root)), "sha256": GLOWLIGHT_PROFILE_SHA256, "verified": True},
        {"input_id": "installed_pack10_01", "relative_path": TARGET_RELATIVE_PATH, "sha256": installed_hash, "verified": True},
        {"input_id": "protected_pack10_03", "relative_path": PROTECTED_PACK10_03_RELATIVE_PATH, "sha256": guard["pack10_03_sha256"], "verified": True},
    ])
    write_tsv(output_dir / "RUNTIME_TEST_MATRIX.tsv", ["test_order", "variant", "required_action", "expected_safety_gate", "result_status"], [
        {"test_order": 1, "variant": "glowlight", "required_action": "launch game through New Game route and observe stability plus any clearly distinguishable GlowLight/posteffect change", "expected_safety_gate": "GlowLight only; Gamma inactive; runtime_validated remains false; PACK10_03 unchanged", "result_status": "pending" if operation == "activation" else "user_observation_required"},
        {"test_order": 2, "variant": "rollback", "required_action": "exit game completely and restore exact PACK10_01 baseline", "expected_safety_gate": "baseline SHA-256 restored and PACK10_03 guard unchanged", "result_status": "pending" if operation == "activation" else "passed"},
    ])
    summary = {
        "type": f"br_quartet_restoration_kps_glowlight_fast_test_lab_{operation}_evidence_summary",
        "format_version": 1,
        "tool_version": TOOL_VERSION,
        "status": status,
        "operation": operation,
        "profile_id": GLOWLIGHT_PROFILE_ID,
        "gamma_profile_id": GAMMA_PROFILE_ID,
        "target_relative_path": TARGET_RELATIVE_PATH,
        "protected_pack10_03_relative_path": PROTECTED_PACK10_03_RELATIVE_PATH,
        "baseline_sha256": BASELINE_SHA256,
        "baseline_size": BASELINE_SIZE,
        "glowlight_profile_sha256": GLOWLIGHT_PROFILE_SHA256,
        "glowlight_profile_size": GLOWLIGHT_PROFILE_SIZE,
        "installed_target_sha256": installed_hash,
        "installed_target_size": installed_size,
        "pack10_03_guard_sha256": guard["pack10_03_sha256"],
        "pack10_03_guard_size": guard["pack10_03_size"],
        "pack10_03_unchanged": True,
        "stage145_report_sha256": STAGE145_SHA256,
        "runtime_validated": False,
        "runtime_result_recorded": False,
        "gamma_retested": False,
        "rollback_required": operation == "activation",
        "exact_pack10_01_baseline_restored": operation == "rollback",
        "core_transaction_id": state.get("transaction_id", ""),
        "core_state_status": state.get("status", ""),
        "skipped_rows": 0,
        "policy": {
            "existing_core_transaction_route_used": True,
            "only_glowlight_profile_selected": True,
            "gamma_profile_selected": False,
            "explicit_user_authorization_required_by_wrapper": True,
            "runtime_validation_inferred": False,
            "runtime_validated_flag_changed": False,
            "pack10_03_guard_enforced": True,
            "normal_composer_modified": False,
            "core_source_modified": False,
            "translation_modified": False,
            "legacy_dlc_modified": False,
            "git_modified": False,
            "proprietary_payloads_in_report": False,
            "exact_rollback_required": True,
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
    parser.add_argument("mode", choices=("preflight", "prepare-guard", "collect-activation", "collect-rollback"))
    parser.add_argument("--project-root", required=True, type=Path)
    parser.add_argument("--quartet-root", required=True, type=Path)
    parser.add_argument("--report-root", type=Path)
    args = parser.parse_args()
    project = args.project_root.resolve()
    quartet = args.quartet_root.resolve()
    report_root = (args.report_root or project / ".local/reports/quartet_restoration").resolve()
    if args.mode == "preflight":
        result = preflight(project, quartet, report_root)
        print(json.dumps({"status": "ok", "mode": result["mode"], "profile_id": GLOWLIGHT_PROFILE_ID, "pack10_01_sha256": result["installed_sha256"], "pack10_03_sha256": result["pack10_03_sha256"]}, sort_keys=True))
    elif args.mode == "prepare-guard":
        print(prepare_guard(project, quartet, report_root))
    elif args.mode == "collect-activation":
        print(write_report(project, quartet, report_root, operation="activation"))
    else:
        print(write_report(project, quartet, report_root, operation="rollback"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
