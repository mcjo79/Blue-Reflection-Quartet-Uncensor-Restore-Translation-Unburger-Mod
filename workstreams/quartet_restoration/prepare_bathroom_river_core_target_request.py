#!/usr/bin/env python3
"""Validate stage 71 and emit a restoration-only core interface request for PACK10_03."""

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
import tarfile
import tempfile
from collections import Counter
from pathlib import Path, PurePosixPath

WORKSTREAM_ID = "quartet_restoration"
REPORT_NAME = "BR_quartet_restoration_bathroom_river_containing_pak_repack_test_evidence.tar.zst"
REPORT_DIR = "bathroom_river_containing_pak_repack_test_evidence"
OUTPUT_NAME = "BR_quartet_restoration_bathroom_river_core_target_request_evidence.tar.zst"
OUTPUT_DIR = "bathroom_river_core_target_request_evidence"
PROFILE_ID = "candidate_bathroom_river_containing_pak_static_inverse_062e39915e7d"
SOURCE_PROFILE_ID = "candidate_bathroom_river_parent_elixir_static_inverse_062e39915e7d"
TARGET_ARCHIVE = "Data/PACK10_03.PAK"
TARGET_MEMBER = "data/b1/x64/field/s89_s_hinako_bath_room_01/s89_s_hinako_bath_room_01.elixir.gz"
BASELINE_SHA256 = "1f96cc82f869643232445586777d189310de56fb7ad1c90fac9785dc95e8d762"
BASELINE_SIZE = 10082928931
PROFILE_SHA256 = "f0eb8da6f2ea2ad9baa1e0eaab26d577f17225968542b7d7b2f66a0ecd14c10d"
PROFILE_SIZE = 10082518244
PARENT_SHA256 = "21cfd65c38545af757e5b2b136a594d5d7106c88c8bf3d3c4266f81f86996d00"
LOCAL_PROFILE_PATH = (
    ".local/build/quartet_restoration/repack_tests/bathroom_river_containing_pak/"
    "profiles/candidate_bathroom_river_containing_pak_static_inverse_062e39915e7d/"
    "output/Data/PACK10_03.PAK"
)
EXPECTED_REPORT_FILES = {
    "SUMMARY.json",
    "BATHROOM_RIVER_CONTAINING_PAK_REPACK_FILES.tsv",
    "BATHROOM_RIVER_CONTAINING_PAK_REPACK_MANIFEST_DIFFERENCES.tsv",
    "BATHROOM_RIVER_CONTAINING_PAK_REPACK_PROFILES.tsv",
    "BATHROOM_RIVER_CONTAINING_PAK_REPACK_SKIPPED.tsv",
    "BATHROOM_RIVER_CONTAINING_PAK_REPACK_VALIDATIONS.tsv",
}
HEX64_RE = re.compile(r"^[0-9a-f]{64}$")


class CoreTargetRequestError(RuntimeError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise CoreTargetRequestError(message)


def parse_int(value: object, default: int = -1) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def safe_extract(archive: Path, destination: Path) -> Path:
    completed = subprocess.run(
        ["tar", "--zstd", "-xf", str(archive), "-C", str(destination)],
        text=True,
        capture_output=True,
    )
    if completed.returncode != 0:
        detail = completed.stderr.strip() or completed.stdout.strip() or "unknown tar error"
        raise CoreTargetRequestError(f"failed to extract stage-71 report: {detail}")
    root = destination / REPORT_DIR
    require(root.is_dir(), f"stage-71 report root is missing: {REPORT_DIR}")
    for path in destination.rglob("*"):
        require(not path.is_symlink(), f"stage-71 report contains a symlink: {path}")
        rel = path.relative_to(destination).as_posix()
        pure = PurePosixPath(rel)
        require(not pure.is_absolute() and ".." not in pure.parts, f"unsafe report path: {rel}")
    files = {path.relative_to(root).as_posix() for path in root.rglob("*") if path.is_file()}
    require(files == EXPECTED_REPORT_FILES, "stage-71 report file set is not canonical")
    return root


def read_tsv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def validate_stage71_report(archive: Path) -> dict[str, object]:
    require(archive.is_file(), f"missing stage-71 report: {archive}")
    with tempfile.TemporaryDirectory(prefix="br-stage71-validate-") as temporary:
        root = safe_extract(archive, Path(temporary))
        summary = json.loads((root / "SUMMARY.json").read_text(encoding="utf-8"))
        require(summary.get("type") == "br_quartet_restoration_bathroom_river_containing_pak_repack_test_evidence_summary", "stage-71 summary type mismatch")
        require(summary.get("format_version") == 1, "stage-71 format version mismatch")
        require(summary.get("tool_version") == "0.0.81", "stage-71 tool version mismatch")
        require(summary.get("source_stage70_tool_version") == "0.0.80", "stage-70 source version mismatch")
        require(summary.get("status") == "bathroom_river_containing_pak_local_repack_verified_not_registered_or_installed", "stage-71 status mismatch")
        expected_numbers = {
            "proposed_profile_rows": 1,
            "repacked_profile_rows": 1,
            "file_rows": 1,
            "validation_rows": 20,
            "validation_failures": 0,
            "manifest_difference_rows": 427,
            "stable_manifest_difference_rows": 0,
            "derived_manifest_difference_rows": 427,
            "skipped_rows": 0,
            "input_archive_size": BASELINE_SIZE,
            "output_archive_size": PROFILE_SIZE,
            "unchanged_member_count_verified": 426,
        }
        for key, expected in expected_numbers.items():
            require(parse_int(summary.get(key)) == expected, f"stage-71 summary mismatch for {key}")
        expected_text = {
            "target_archive": TARGET_ARCHIVE,
            "target_member_path": TARGET_MEMBER,
            "input_archive_sha256": BASELINE_SHA256,
            "output_archive_sha256": PROFILE_SHA256,
            "inventory_pristine_archive_sha256": BASELINE_SHA256,
            "candidate_parent_sha256": PARENT_SHA256,
        }
        for key, expected in expected_text.items():
            require(summary.get(key) == expected, f"stage-71 summary mismatch for {key}")
        require(summary.get("inventory_pristine_archive_match") is True, "stage-71 baseline is not pristine")
        policy = summary.get("policy")
        require(isinstance(policy, dict), "stage-71 policy is missing")
        for key in (
            "installed_game_read_only",
            "current_archive_used_as_repack_base",
            "unrelated_translation_or_other_member_changes_preserved",
            "all_unchanged_members_verified_by_reextraction_hash",
            "stable_manifest_fields_used_as_validation_gate",
            "local_rollback_baseline_copied",
            "candidate_pak_written_only_under_local_workspace",
        ):
            require(policy.get(key) is True, f"required stage-71 policy gate is false: {key}")
        for key in (
            "installed_game_modified",
            "proprietary_pak_exported_in_report",
            "candidate_parent_payload_exported_in_report",
            "core_registry_modified",
            "activation_or_rollback_invoked",
            "runtime_validation_inferred",
            "censorship_classification_inferred",
            "opaque_binary_field_semantics_inferred",
            "opl2_payload_modified",
            "translation_or_dlc_workstreams_modified",
            "canary_track_modified",
        ):
            require(policy.get(key) is False, f"forbidden stage-71 policy state is true: {key}")

        profiles = read_tsv(root / "BATHROOM_RIVER_CONTAINING_PAK_REPACK_PROFILES.tsv")
        require(len(profiles) == 1, "stage-71 profile table must contain one row")
        profile = profiles[0]
        expected_profile = {
            "profile_id": PROFILE_ID,
            "source_profile_id": SOURCE_PROFILE_ID,
            "classification": "single_parent_elixir_member_containing_pak_repack_test",
            "target_archive": TARGET_ARCHIVE,
            "target_member_path": TARGET_MEMBER,
            "input_archive_sha256": BASELINE_SHA256,
            "output_archive_sha256": PROFILE_SHA256,
            "rollback_archive_sha256": BASELINE_SHA256,
            "input_archive_size": str(BASELINE_SIZE),
            "output_archive_size": str(PROFILE_SIZE),
            "replaced_member_count": "1",
            "unchanged_member_count_verified": "426",
            "inventory_pristine_archive_match": "True",
            "local_output_archive": LOCAL_PROFILE_PATH,
            "validation_status": "passed",
            "runtime_validated": "False",
            "review_status": "local_containing_pak_only_not_registered_not_installed",
        }
        for key, expected in expected_profile.items():
            require(profile.get(key) == expected, f"stage-71 profile mismatch for {key}")

        files = read_tsv(root / "BATHROOM_RIVER_CONTAINING_PAK_REPACK_FILES.tsv")
        require(len(files) == 1, "stage-71 file table must contain one row")
        row = files[0]
        expected_file = {
            "profile_id": PROFILE_ID,
            "normalized_path": "data/x64/field/s89_s_hinako_bath_room_01/s89_s_hinako_bath_room_01.elixir.gz",
            "target_archive": TARGET_ARCHIVE,
            "target_member_path": TARGET_MEMBER,
            "target_member_sha256": "6d9aaf32b7eebd9e927b1b4e6e5521b9696d75738ba55499f3c64fcee0d76af8",
            "candidate_member_sha256": PARENT_SHA256,
            "repacked_member_sha256": PARENT_SHA256,
            "validation_status": "passed",
        }
        for key, expected in expected_file.items():
            require(row.get(key) == expected, f"stage-71 file mismatch for {key}")

        validations = read_tsv(root / "BATHROOM_RIVER_CONTAINING_PAK_REPACK_VALIDATIONS.tsv")
        require(len(validations) == 20, "stage-71 validation table must contain 20 rows")
        require(len({row.get("check_name") for row in validations}) == 20, "stage-71 validation checks are duplicated")
        require(all(row.get("profile_id") == PROFILE_ID for row in validations), "stage-71 validation profile mismatch")
        require(all(row.get("target_archive") == TARGET_ARCHIVE for row in validations), "stage-71 validation target mismatch")
        require(all(row.get("passed") == "True" for row in validations), "one or more stage-71 gates failed")

        differences = read_tsv(root / "BATHROOM_RIVER_CONTAINING_PAK_REPACK_MANIFEST_DIFFERENCES.tsv")
        require(len(differences) == 427, "stage-71 manifest difference count mismatch")
        classes = Counter(row.get("classification") for row in differences)
        require(classes == Counter({"derived_unchanged_member_metadata": 426, "derived_modified_member_metadata": 1}), "stage-71 manifest difference classes mismatch")
        require(all(row.get("gate_effect") == "diagnostic_only" for row in differences), "stage-71 manifest difference unexpectedly affects a gate")
        require(not read_tsv(root / "BATHROOM_RIVER_CONTAINING_PAK_REPACK_SKIPPED.tsv"), "stage-71 report contains skipped rows")
        return summary


def inspect_core_support(project_root: Path) -> dict[str, object]:
    registry_source = project_root / "Blue_Reflection_Patcher/cmd/brpatcher/local_profile_registry.go"
    main_source = project_root / "Blue_Reflection_Patcher/cmd/brpatcher/main.go"
    transaction_source = project_root / "Blue_Reflection_Patcher/cmd/brpatcher/local_profile_transaction.go"
    wrapper = project_root / "Blue_Reflection_Patcher/cmd/br_quartet_field_profile.sh"
    for path in (registry_source, main_source, transaction_source, wrapper):
        require(path.is_file(), f"missing core source required for interface audit: {path}")
    registry_text = registry_source.read_text(encoding="utf-8")
    main_text = main_source.read_text(encoding="utf-8")
    transaction_text = transaction_source.read_text(encoding="utf-8")
    wrapper_text = wrapper.read_text(encoding="utf-8")
    target_present = f'"{TARGET_ARCHIVE}"' in registry_text
    command_present = all(command in main_text for command in (
        "quartet-field-profile-activate",
        "quartet-field-profile-status",
        "quartet-field-profile-rollback",
    ))
    wrapper_present = all(token in wrapper_text for token in (
        "quartet-field-profile-activate",
        "quartet-field-profile-status",
        "quartet-field-profile-rollback",
    ))
    generic_exclusion_present = (
        "for target := range localProfileTargets" in transaction_text
        and "target != spec.RelativePath" in transaction_text
        and re.search(r"\bOtherState\s+string\b", registry_text) is None
    )
    partial = any((target_present, command_present, wrapper_present, generic_exclusion_present)) and not all((target_present, command_present, wrapper_present, generic_exclusion_present))
    require(not partial, "core PACK10_03 support is partial; orchestrator must audit the incomplete interface before registration")
    return {
        "target_registered": target_present,
        "activation_commands_present": command_present,
        "wrapper_support_present": wrapper_present,
        "generic_mutual_exclusion_present": generic_exclusion_present,
        "fully_supported": all((target_present, command_present, wrapper_present, generic_exclusion_present)),
        "current_target_count": registry_text.count('RelativePath: "Data/PACK'),
        "current_other_state_is_scalar": re.search(r"\bOtherState\s+string\b", registry_text) is not None,
    }


def write_json(path: Path, data: object) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_tsv(path: Path, fields: list[str], rows: list[dict[str, object]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def build_request(project_root: Path, report_path: Path, *, create_archive: bool = True) -> tuple[Path, Path | None, dict[str, object]]:
    stage71 = validate_stage71_report(report_path)
    core = inspect_core_support(project_root)
    report_root = project_root / ".local/reports" / WORKSTREAM_ID
    output = report_root / OUTPUT_DIR
    if output.exists():
        shutil.rmtree(output)
    output.mkdir(parents=True)

    interface_status = "core_target_already_supported_registration_stage_can_follow" if core["fully_supported"] else "core_target_extension_required_before_profile_registration"
    request = {
        "type": "br_quartet_restoration_core_target_interface_request",
        "format_version": 1,
        "tool_version": "0.0.82",
        "status": interface_status,
        "requested_target_relative_path": TARGET_ARCHIVE,
        "requested_target_kind": "field",
        "requested_state_path": ".local/state/core_unified_patcher/quartet_field_profile.json",
        "requested_report_latest": ".local/reports/core/BR_QUARTET_FIELD_PROFILE_TRANSACTION_REPORT.json",
        "requested_report_dir": ".local/reports/core/quartet_field_profiles",
        "requested_commands": [
            "quartet-field-profile-activate",
            "quartet-field-profile-status",
            "quartet-field-profile-rollback",
        ],
        "required_transaction_change": "generalize scalar OtherState to all other target states or an equivalent grouped mutual-exclusion check before activation",
        "profile_to_register_after_core_update": {
            "profile_id": PROFILE_ID,
            "target_relative_path": TARGET_ARCHIVE,
            "baseline_sha256": BASELINE_SHA256,
            "baseline_size": BASELINE_SIZE,
            "profile_sha256": PROFILE_SHA256,
            "profile_size": PROFILE_SIZE,
            "local_profile_path": LOCAL_PROFILE_PATH,
            "changed_members": [TARGET_MEMBER],
            "runtime_validated": False,
        },
        "current_core_support": core,
        "restoration_registry_state": {
            "current_profiles": 14,
            "pending_profiles": 1,
            "expected_profiles_after_registration": 15,
            "pack11_profiles_after_registration": 12,
            "pack10_01_profiles_after_registration": 2,
            "pack10_03_profiles_after_registration": 1,
        },
        "policy": {
            "restoration_only_update": True,
            "core_sources_modified": False,
            "registry_modified": False,
            "profile_activated": False,
            "installed_game_modified": False,
            "runtime_validation_inferred": False,
            "opaque_binary_semantics_inferred": False,
            "canary_track_modified": False,
        },
        "next_action": "Have the orchestrator/core workstream add checksum-gated PACK10_03 local-profile support. Then return the core update/result and register this pending profile as stage 73.",
        "source_stage71_report_sha256": sha256_file(report_path),
        "source_stage71_output_archive_sha256": stage71["output_archive_sha256"],
    }
    write_json(output / "SUMMARY.json", request)
    write_json(output / "CORE_INTERFACE_REQUEST.json", request)
    write_tsv(
        output / "PENDING_PROFILE.tsv",
        ["profile_id", "target_relative_path", "baseline_sha256", "baseline_size", "profile_sha256", "profile_size", "local_profile_path", "changed_member", "runtime_validated"],
        [{
            "profile_id": PROFILE_ID,
            "target_relative_path": TARGET_ARCHIVE,
            "baseline_sha256": BASELINE_SHA256,
            "baseline_size": BASELINE_SIZE,
            "profile_sha256": PROFILE_SHA256,
            "profile_size": PROFILE_SIZE,
            "local_profile_path": LOCAL_PROFILE_PATH,
            "changed_member": TARGET_MEMBER,
            "runtime_validated": False,
        }],
    )
    validation_rows = [
        ("stage71_report_canonical", True, "20/20 gates, 426 unchanged members, zero stable differences"),
        ("stage71_profile_local_only", True, "not registered, activated or installed"),
        ("pack10_03_target_support_complete", bool(core["fully_supported"]), "false is the expected dependency state before orchestrator update"),
        ("core_partial_support_absent", True, "no inconsistent partial interface detected"),
        ("restoration_registry_left_unchanged", True, "current registry remains fourteen profiles"),
    ]
    write_tsv(
        output / "VALIDATIONS.tsv",
        ["check_name", "passed", "gate_effect", "details"],
        [{"check_name": name, "passed": passed, "gate_effect": "dependency_status" if name == "pack10_03_target_support_complete" else "passed", "details": details} for name, passed, details in validation_rows],
    )
    (output / "CORE_INTERFACE_REQUEST.md").write_text(
        "# Quartet PACK10_03 local-profile interface request\n\n"
        "Stage 71 verified one local `PACK10_03.PAK` candidate that changes only the Hinako bathroom parent Elixir. "
        "The current core registry recognizes only `PACK11.PAK` and `PACK10_01.PAK`, so registration is intentionally blocked.\n\n"
        "The core workstream should add a third checksum-gated target for `Data/PACK10_03.PAK`, dedicated activate/status/rollback commands and transaction reports. "
        "Because the current target definition stores only one scalar `OtherState`, the implementation must also generalize mutual exclusion so the new field profile cannot be activated while either event or shader state is active, and vice versa.\n\n"
        "After the core update, restoration stage 73 may add the pending profile to the generic registry. No proprietary payload is included here.\n",
        encoding="utf-8",
    )

    archive: Path | None = None
    if create_archive:
        archive = report_root / OUTPUT_NAME
        temporary = archive.with_name(archive.name + f".tmp.{os.getpid()}")
        completed = subprocess.run(["tar", "--zstd", "-cf", str(temporary), "-C", str(report_root), OUTPUT_DIR], text=True, capture_output=True)
        if completed.returncode != 0:
            temporary.unlink(missing_ok=True)
            detail = completed.stderr.strip() or completed.stdout.strip() or "unknown tar error"
            raise CoreTargetRequestError(f"failed to create core request report: {detail}")
        os.replace(temporary, archive)
    return output, archive, request


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", required=True)
    parser.add_argument("--no-report-archive", action="store_true")
    args = parser.parse_args()
    project_root = Path(args.project_root).expanduser().resolve()
    report = project_root / ".local/reports" / WORKSTREAM_ID / REPORT_NAME
    output, archive, request = build_request(project_root, report, create_archive=not args.no_report_archive)
    print(f"Validated stage-71 report: {report}")
    print(f"Core PACK10_03 support complete: {request['current_core_support']['fully_supported']}")
    print(f"Pending profile: {PROFILE_ID}")
    print(f"Request directory: {output}")
    if archive is not None:
        print(f"Report: {archive}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except CoreTargetRequestError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
