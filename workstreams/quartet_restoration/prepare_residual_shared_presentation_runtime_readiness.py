#!/usr/bin/env python3
"""Build a metadata-only runtime-test readiness report for the shared-presentation profile."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path, PurePosixPath
from typing import Iterable

WORKSTREAM_ID = "quartet_restoration"
SOURCE_REPORT_NAME = "BR_quartet_restoration_core_profile_manifest_evidence.tar.zst"
SOURCE_REPORT_DIR = "core_profile_manifest_evidence"
OUTPUT_REPORT_NAME = "BR_quartet_restoration_residual_shared_presentation_runtime_readiness.tar.zst"
OUTPUT_REPORT_DIR = "residual_shared_presentation_runtime_readiness"
PROFILE_ID = "shared_presentation_d88c7c3a6f"
TARGET_ARCHIVE = "Data/PACK11.PAK"
BASELINE_SHA256 = "bf53826c840cec9f5cb4044a121a4bada29dd14f56c9f1b1b7633b57cc067306"
BASELINE_SIZE = 13372318
PROFILE_SHA256 = "6fcb50fbf43643e147085b0cfbedc6961989fe3c8833dc9f36e87198c88b15b6"
PROFILE_SIZE = 13372318
LOCAL_PROFILE_PATH = ".local/build/quartet_restoration/repack_tests/residual_shared_presentation/profiles/shared_presentation_d88c7c3a6f/output/Data/PACK11.PAK"
MANIFEST_PATH = ".local/build/quartet_restoration/core_profiles/generated/shared_presentation_d88c7c3a6f.json"
EVENT_STATE_PATH = ".local/state/core_unified_patcher/quartet_event_profile.json"
SHADER_STATE_PATH = ".local/state/core_unified_patcher/quartet_shader_profile.json"
EXPECTED_MEMBERS = (
    "event/b1/event_jp/ce11/event_ce11_070.ebd",
    "event/b1/event_jp/em01/event_em01_090.ebd",
)
EXPECTED_SOURCE_FILES = {"CORE_PROFILE_MANIFESTS.tsv", "SUMMARY.json"}
OPEN_TRANSACTION_STATES = {
    "active",
    "prepared",
    "rolling_back",
    "activation_uncertain",
    "rollback_uncertain",
}
EXPECTED_PROFILE_IDS = {
    "candidate_single_scene_multishape_em01_050_954fadd61cac",
    "height_fog_shader_original_code",
    "repeated_context_69adef108a_c90700a5a2",
    "route_sequence_te02_a570203aa6",
    "shared_presentation_d88c7c3a6f",
    "single_scene_event_te02_230_0143f9822b",
    "water_shader_swater_original_code",
}
HEX64_RE = re.compile(r"^[0-9a-f]{64}$")


class ReadinessError(RuntimeError):
    """Raised when runtime-test readiness cannot be proven safely."""


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ReadinessError(message)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def checked_regular_file(path: Path, *, label: str) -> tuple[str, int]:
    if path.is_symlink() or not path.is_file():
        raise ReadinessError(f"{label} is missing or not a regular non-symlink file: {path}")
    return sha256_file(path), path.stat().st_size


def safe_member_name(raw: str) -> str:
    name = raw.rstrip("/")
    path = PurePosixPath(name)
    if path.is_absolute() or not path.parts or "." in path.parts or ".." in path.parts:
        raise ReadinessError(f"unsafe report member: {raw}")
    canonical = path.as_posix()
    if canonical != name:
        raise ReadinessError(f"non-canonical report member: {raw}")
    return canonical


def run_tar(args: list[str]) -> subprocess.CompletedProcess[str]:
    completed = subprocess.run(args, text=True, capture_output=True)
    if completed.returncode != 0:
        detail = completed.stderr.strip() or completed.stdout.strip() or "unknown tar error"
        raise ReadinessError(f"report archive operation failed: {detail}")
    return completed


def extract_source_report(report_path: Path, temporary: Path) -> Path:
    if report_path.is_symlink() or not report_path.is_file():
        raise ReadinessError(f"stage-38 report is missing or unsafe: {report_path}")
    listed = run_tar(["tar", "--zstd", "-tf", str(report_path)]).stdout.splitlines()
    names = [safe_member_name(raw) for raw in listed if raw.rstrip("/")]
    files = {
        PurePosixPath(name).name
        for name in names
        if len(PurePosixPath(name).parts) == 2
        and PurePosixPath(name).parts[0] == SOURCE_REPORT_DIR
    }
    unexpected = [
        name
        for name in names
        if PurePosixPath(name).parts[0] != SOURCE_REPORT_DIR
        or len(PurePosixPath(name).parts) > 2
    ]
    if unexpected:
        raise ReadinessError(f"unexpected stage-38 report members: {unexpected[:3]}")
    if files != EXPECTED_SOURCE_FILES:
        raise ReadinessError(
            f"stage-38 report file set mismatch: expected {sorted(EXPECTED_SOURCE_FILES)}, got {sorted(files)}"
        )
    run_tar(["tar", "--zstd", "-xf", str(report_path), "-C", str(temporary)])
    root = temporary / SOURCE_REPORT_DIR
    if root.is_symlink() or not root.is_dir():
        raise ReadinessError("stage-38 report root is missing or unsafe")
    for filename in EXPECTED_SOURCE_FILES:
        path = root / filename
        if path.is_symlink() or not path.is_file():
            raise ReadinessError(f"stage-38 report file is missing or unsafe: {filename}")
    return root


def read_tsv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def write_tsv(path: Path, fieldnames: list[str], rows: Iterable[dict[str, object]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def validate_stage38_report(report_path: Path) -> tuple[dict[str, object], list[dict[str, str]]]:
    with tempfile.TemporaryDirectory(prefix="br-stage38-readiness-") as raw_tmp:
        root = extract_source_report(report_path, Path(raw_tmp))
        summary = json.loads((root / "SUMMARY.json").read_text(encoding="utf-8"))
        require(summary.get("tool_version") == "0.0.50", "unexpected core-profile report tool version")
        require(
            summary.get("status") == "all_current_local_profiles_registered_runtime_unvalidated",
            "unexpected stage-38 status",
        )
        require(summary.get("profile_rows") == len(EXPECTED_PROFILE_IDS), "core-profile report count mismatch")
        require(summary.get("pack11_profile_rows") == 5, "core-profile PACK11 profile count is not five")
        require(summary.get("pack10_01_profile_rows") == 2, "stage-38 PACK10_01 profile count is not two")
        require(summary.get("runtime_validated_profile_rows") == 0, "a stage-38 profile is marked runtime-validated")
        policy = summary.get("policy")
        require(isinstance(policy, dict), "stage-38 policy is missing")
        for key in (
            "profile_paks_checksum_and_size_verified",
        ):
            require(policy.get(key) is True, f"required stage-38 policy gate is false: {key}")
        for key in (
            "local_paks_copied",
            "activation_or_rollback_scripts_generated",
            "core_transaction_state_modified",
            "core_backups_modified",
            "runtime_validation_inferred",
            "legacy_dlc_in_scope",
        ):
            require(policy.get(key) is False, f"forbidden stage-38 policy state is true: {key}")

        rows = read_tsv(root / "CORE_PROFILE_MANIFESTS.tsv")
        require(len(rows) == len(EXPECTED_PROFILE_IDS), "core-profile table count mismatch")
        require({row.get("profile_id") for row in rows} == EXPECTED_PROFILE_IDS, "core-profile ID set mismatch")
        require(all(row.get("validation_status") == "passed" for row in rows), "a stage-38 profile validation failed")
        require(all(row.get("runtime_validated") == "false" for row in rows), "a stage-38 profile is runtime-validated")
        target = [row for row in rows if row.get("profile_id") == PROFILE_ID]
        require(len(target) == 1, "target profile is missing or duplicated in stage-38 evidence")
        row = target[0]
        expected = {
            "target_relative_path": TARGET_ARCHIVE,
            "baseline_sha256": BASELINE_SHA256,
            "baseline_size": str(BASELINE_SIZE),
            "profile_sha256": PROFILE_SHA256,
            "profile_size": str(PROFILE_SIZE),
            "local_profile_path": LOCAL_PROFILE_PATH,
            "changed_member_count": "2",
            "manifest_relative_path": MANIFEST_PATH,
            "workstream_version": "0.0.50",
        }
        for key, value in expected.items():
            require(row.get(key) == value, f"stage-38 target profile field mismatch: {key}")
        return summary, rows


def load_generated_manifests(project_root: Path) -> list[dict[str, object]]:
    generated = project_root / ".local" / "build" / WORKSTREAM_ID / "core_profiles" / "generated"
    if generated.is_symlink() or not generated.is_dir():
        raise ReadinessError(f"generated core profile registry is missing or unsafe: {generated}")
    candidates = sorted(generated.glob("*.json"))
    require(len(candidates) == len(EXPECTED_PROFILE_IDS), "generated registry manifest count mismatch")
    manifests: list[dict[str, object]] = []
    for path in candidates:
        if path.is_symlink() or not path.is_file():
            raise ReadinessError(f"generated manifest is unsafe: {path}")
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            raise ReadinessError(f"cannot read generated manifest {path}: {exc}") from exc
        require(data.get("profile_id") == path.stem, f"manifest filename/profile_id mismatch: {path.name}")
        require(data.get("schema_version") == 1, f"unsupported manifest schema: {path.name}")
        require(data.get("workstream_id") == WORKSTREAM_ID, f"wrong manifest workstream: {path.name}")
        require(data.get("runtime_validated") is False, f"manifest unexpectedly runtime-validated: {path.name}")
        manifests.append(data)
    require({item.get("profile_id") for item in manifests} == EXPECTED_PROFILE_IDS, "generated manifest profile ID set mismatch")
    require(sum(item.get("target_relative_path") == TARGET_ARCHIVE for item in manifests) == 5, "generated PACK11 profile count mismatch")
    require(sum(item.get("target_relative_path") == "Data/PACK10_01.PAK" for item in manifests) == 2, "generated PACK10_01 profile count mismatch")
    return manifests


def validate_target_manifest(project_root: Path, manifests: list[dict[str, object]]) -> dict[str, object]:
    selected = [item for item in manifests if item.get("profile_id") == PROFILE_ID]
    require(len(selected) == 1, "target manifest is missing or duplicated")
    manifest = selected[0]
    expected: dict[str, object] = {
        "target_relative_path": TARGET_ARCHIVE,
        "baseline_sha256": BASELINE_SHA256,
        "baseline_size": BASELINE_SIZE,
        "profile_sha256": PROFILE_SHA256,
        "profile_size": PROFILE_SIZE,
        "local_profile_path": LOCAL_PROFILE_PATH,
        "changed_member_count": 2,
        "changed_members": list(EXPECTED_MEMBERS),
        "runtime_validated": False,
    }
    for key, value in expected.items():
        require(manifest.get(key) == value, f"target manifest field mismatch: {key}")
    manifest_path = project_root / MANIFEST_PATH
    require(not manifest_path.is_symlink() and manifest_path.is_file(), "target manifest path is missing or unsafe")
    require(json.loads(manifest_path.read_text(encoding="utf-8")) == manifest, "target manifest on disk differs from registry scan")
    profile_path = project_root / LOCAL_PROFILE_PATH
    digest, size = checked_regular_file(profile_path, label="local target profile PAK")
    require(digest == PROFILE_SHA256, "local target profile checksum mismatch")
    require(size == PROFILE_SIZE, "local target profile size mismatch")
    return manifest


def inspect_transaction_state(project_root: Path, relative_path: str, kind: str) -> dict[str, object]:
    path = project_root / relative_path
    if not path.exists():
        return {
            "kind": kind,
            "state_relative_path": relative_path,
            "state_present": False,
            "state_status": "absent",
            "open_transaction": False,
            "profile_id": "",
            "target_relative_path": "",
            "runtime_validated": False,
            "check_status": "passed_no_state",
        }
    if path.is_symlink() or not path.is_file():
        raise ReadinessError(f"{kind} transaction state is unsafe: {path}")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        raise ReadinessError(f"cannot read {kind} transaction state: {exc}") from exc
    status = str(data.get("status", "")).strip()
    require(status != "", f"{kind} transaction state has no status")
    open_transaction = status in OPEN_TRANSACTION_STATES
    return {
        "kind": kind,
        "state_relative_path": relative_path,
        "state_present": True,
        "state_status": status,
        "open_transaction": open_transaction,
        "profile_id": str(data.get("profile_id", "")),
        "target_relative_path": str(data.get("target_relative_path", "")),
        "runtime_validated": bool(data.get("runtime_validated", False)),
        "check_status": "blocked_open_transaction" if open_transaction else "passed_closed_state",
    }


def build_readiness(
    *,
    project_root: Path,
    quartet_root: Path,
    source_report_path: Path,
) -> tuple[dict[str, object], dict[str, list[dict[str, object]]]]:
    stage38_summary, stage38_rows = validate_stage38_report(source_report_path)
    manifests = load_generated_manifests(project_root)
    manifest = validate_target_manifest(project_root, manifests)

    installed_path = quartet_root / TARGET_ARCHIVE
    installed_sha, installed_size = checked_regular_file(installed_path, label="installed PACK11 baseline")
    require(installed_sha == BASELINE_SHA256, "installed PACK11 does not match the registered baseline")
    require(installed_size == BASELINE_SIZE, "installed PACK11 size does not match the registered baseline")

    transaction_rows = [
        inspect_transaction_state(project_root, EVENT_STATE_PATH, "event"),
        inspect_transaction_state(project_root, SHADER_STATE_PATH, "shader"),
    ]
    require(not any(bool(row["open_transaction"]) for row in transaction_rows), "an event or shader profile transaction is already open")

    registry_rows: list[dict[str, object]] = []
    by_id = {str(item["profile_id"]): item for item in manifests}
    for evidence in sorted(stage38_rows, key=lambda row: row["profile_id"]):
        profile_id = evidence["profile_id"]
        item = by_id[profile_id]
        profile_path = project_root / str(item["local_profile_path"])
        digest, size = checked_regular_file(profile_path, label=f"local profile {profile_id}")
        require(digest == item["profile_sha256"], f"local profile checksum mismatch: {profile_id}")
        require(size == item["profile_size"], f"local profile size mismatch: {profile_id}")
        registry_rows.append({
            "profile_id": profile_id,
            "target_relative_path": item["target_relative_path"],
            "local_profile_path": item["local_profile_path"],
            "profile_sha256": item["profile_sha256"],
            "profile_size": item["profile_size"],
            "runtime_validated": False,
            "manifest_status": "passed",
            "local_payload_status": "passed",
            "active": False,
            "baseline_status": "match",
        })

    target_readiness = [{
        "profile_id": PROFILE_ID,
        "target_relative_path": TARGET_ARCHIVE,
        "baseline_sha256": BASELINE_SHA256,
        "baseline_size": BASELINE_SIZE,
        "profile_sha256": PROFILE_SHA256,
        "profile_size": PROFILE_SIZE,
        "changed_member_count": 2,
        "registry_manifest_valid": True,
        "local_profile_checksum_valid": True,
        "installed_baseline_match": True,
        "event_transaction_closed": True,
        "shader_transaction_closed": True,
        "runtime_validated": False,
        "explicit_user_authorization_present": False,
        "scene_save_or_reachable_state_confirmed": False,
        "activation_performed": False,
        "readiness_status": "metadata_ready_activation_not_authorized_save_required",
    }]

    runtime_matrix = [
        {
            "test_order": 1,
            "profile_id": PROFILE_ID,
            "event_member": EXPECTED_MEMBERS[0],
            "event_id": "ce11_070",
            "cue_domains": "steam_or_vapor",
            "test_goal": "compare steam/vapor or presentation occlusion with the profile active",
            "isolation_requirement": "no other event or shader profile active",
            "save_requirement": "save or reachable state immediately before the exact event",
            "result_required": "visual observation plus transaction report; no runtime success inferred from metadata",
        },
        {
            "test_order": 2,
            "profile_id": PROFILE_ID,
            "event_member": EXPECTED_MEMBERS[1],
            "event_id": "em01_090",
            "cue_domains": "steam_or_vapor",
            "test_goal": "compare steam/vapor or presentation occlusion with the same isolated profile",
            "isolation_requirement": "same isolated activation; rollback immediately after both observations",
            "save_requirement": "save or reachable state immediately before the exact event",
            "result_required": "visual observation plus exact rollback verification",
        },
    ]

    rollback_rows = [
        {
            "invariant": "baseline_archive_identity",
            "expected_value": f"{BASELINE_SHA256}:{BASELINE_SIZE}",
            "verified_now": True,
            "required_after_test": True,
        },
        {
            "invariant": "profile_archive_identity",
            "expected_value": f"{PROFILE_SHA256}:{PROFILE_SIZE}",
            "verified_now": True,
            "required_after_test": False,
        },
        {
            "invariant": "isolated_event_transaction",
            "expected_value": "no shader transaction and no other event profile",
            "verified_now": True,
            "required_after_test": True,
        },
        {
            "invariant": "runtime_validation_flag",
            "expected_value": "false until both scenes are observed and rollback is exact",
            "verified_now": True,
            "required_after_test": True,
        },
    ]

    command_rows = [
        {
            "step": 1,
            "purpose": "list profiles",
            "command": "bash Blue_Reflection_Patcher/cmd/br_quartet_profiles.sh list",
            "executed_by_stage39": False,
            "requires_explicit_user_authorization": False,
        },
        {
            "step": 2,
            "purpose": "check event transaction status",
            "command": "bash Blue_Reflection_Patcher/cmd/br_quartet_event_profile.sh status",
            "executed_by_stage39": False,
            "requires_explicit_user_authorization": False,
        },
        {
            "step": 3,
            "purpose": "activate isolated profile",
            "command": f"bash Blue_Reflection_Patcher/cmd/br_quartet_event_profile.sh activate {PROFILE_ID}",
            "executed_by_stage39": False,
            "requires_explicit_user_authorization": True,
        },
        {
            "step": 4,
            "purpose": "rollback exact baseline",
            "command": "bash Blue_Reflection_Patcher/cmd/br_quartet_event_profile.sh rollback",
            "executed_by_stage39": False,
            "requires_explicit_user_authorization": True,
        },
    ]

    summary = {
        "type": "br_quartet_restoration_residual_shared_presentation_runtime_readiness_summary",
        "format_version": 1,
        "tool_version": "0.0.45",
        "source_core_profile_manifest_tool_version": stage38_summary["tool_version"],
        "status": "profile_metadata_ready_activation_not_authorized_save_required",
        "profile_id": PROFILE_ID,
        "registry_profile_rows": len(registry_rows),
        "target_event_rows": len(runtime_matrix),
        "transaction_state_rows": len(transaction_rows),
        "open_transaction_rows": 0,
        "installed_baseline_sha256": installed_sha,
        "installed_baseline_size": installed_size,
        "profile_sha256": manifest["profile_sha256"],
        "profile_size": manifest["profile_size"],
        "runtime_validated": False,
        "activation_authorized": False,
        "scene_save_or_reachable_state_confirmed": False,
        "policy": {
            "installed_game_read_only": True,
            "installed_game_modified": False,
            "activation_invoked": False,
            "rollback_invoked": False,
            "transaction_state_modified": False,
            "core_backups_modified": False,
            "profile_manifests_modified": False,
            "local_profile_payload_modified": False,
            "commands_previewed_only": True,
            "runtime_validation_inferred": False,
            "explicit_user_decision_required_before_activation": True,
            "suitable_scene_save_or_reachable_state_required": True,
            "legacy_dlc_in_scope": False,
        },
        "next_action": "Upload this report. Do not activate until the user explicitly chooses the test and supplies or confirms a save/reachable state for ce11_070 and/or em01_090.",
    }
    tables = {
        "CORE_PROFILE_REGISTRY_RECHECK.tsv": registry_rows,
        "TARGET_PROFILE_RUNTIME_READINESS.tsv": target_readiness,
        "TRANSACTION_STATE_CHECKS.tsv": transaction_rows,
        "RUNTIME_TEST_MATRIX.tsv": runtime_matrix,
        "ROLLBACK_INVARIANTS.tsv": rollback_rows,
        "COMMAND_PREVIEW.tsv": command_rows,
    }
    return summary, tables


def write_report(
    *,
    project_root: Path,
    summary: dict[str, object],
    tables: dict[str, list[dict[str, object]]],
    create_archive: bool,
) -> Path | None:
    report_root = project_root / ".local" / "reports" / WORKSTREAM_ID
    evidence_dir = report_root / OUTPUT_REPORT_DIR
    if evidence_dir.exists():
        shutil.rmtree(evidence_dir)
    evidence_dir.mkdir(parents=True, exist_ok=True)

    field_orders = {
        "CORE_PROFILE_REGISTRY_RECHECK.tsv": [
            "profile_id", "target_relative_path", "local_profile_path", "profile_sha256",
            "profile_size", "runtime_validated", "manifest_status", "local_payload_status",
            "active", "baseline_status",
        ],
        "TARGET_PROFILE_RUNTIME_READINESS.tsv": [
            "profile_id", "target_relative_path", "baseline_sha256", "baseline_size",
            "profile_sha256", "profile_size", "changed_member_count", "registry_manifest_valid",
            "local_profile_checksum_valid", "installed_baseline_match", "event_transaction_closed",
            "shader_transaction_closed", "runtime_validated", "explicit_user_authorization_present",
            "scene_save_or_reachable_state_confirmed", "activation_performed", "readiness_status",
        ],
        "TRANSACTION_STATE_CHECKS.tsv": [
            "kind", "state_relative_path", "state_present", "state_status", "open_transaction",
            "profile_id", "target_relative_path", "runtime_validated", "check_status",
        ],
        "RUNTIME_TEST_MATRIX.tsv": [
            "test_order", "profile_id", "event_member", "event_id", "cue_domains", "test_goal",
            "isolation_requirement", "save_requirement", "result_required",
        ],
        "ROLLBACK_INVARIANTS.tsv": [
            "invariant", "expected_value", "verified_now", "required_after_test",
        ],
        "COMMAND_PREVIEW.tsv": [
            "step", "purpose", "command", "executed_by_stage39", "requires_explicit_user_authorization",
        ],
    }
    for filename, rows in tables.items():
        write_tsv(evidence_dir / filename, field_orders[filename], rows)
    (evidence_dir / "SUMMARY.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    if not create_archive:
        return None
    report_root.mkdir(parents=True, exist_ok=True)
    archive = report_root / OUTPUT_REPORT_NAME
    temporary = archive.with_name(archive.name + f".tmp.{os.getpid()}")
    if temporary.exists():
        temporary.unlink()
    completed = subprocess.run(
        ["tar", "--zstd", "-cf", str(temporary), "-C", str(report_root), OUTPUT_REPORT_DIR],
        text=True,
        capture_output=True,
    )
    if completed.returncode != 0:
        temporary.unlink(missing_ok=True)
        detail = completed.stderr.strip() or completed.stdout.strip() or "unknown tar error"
        raise ReadinessError(f"cannot create readiness report: {detail}")
    os.replace(temporary, archive)
    return archive


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", required=True)
    parser.add_argument("--quartet-root", required=True)
    parser.add_argument("--no-report-archive", action="store_true")
    args = parser.parse_args()

    project_root = Path(args.project_root).expanduser().resolve()
    quartet_root = Path(args.quartet_root).expanduser().resolve()
    source_report = project_root / ".local" / "reports" / WORKSTREAM_ID / SOURCE_REPORT_NAME
    summary, tables = build_readiness(
        project_root=project_root,
        quartet_root=quartet_root,
        source_report_path=source_report,
    )
    report = write_report(
        project_root=project_root,
        summary=summary,
        tables=tables,
        create_archive=not args.no_report_archive,
    )
    print(f"Validated current core-profile report and seven-profile registry: {source_report}")
    print(f"Profile ready for an explicitly authorized isolated runtime test: {PROFILE_ID}")
    print("Activation performed: no")
    print("Suitable scene save/reachable state confirmed: no")
    if report is not None:
        print(f"Report: {report}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except ReadinessError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
