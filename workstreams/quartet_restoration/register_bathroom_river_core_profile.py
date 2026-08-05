#!/usr/bin/env python3
"""Validate the PACK10_03 core extension and register the bathroom river profile."""

from __future__ import annotations

import argparse
import csv
import importlib.util
import json
import subprocess
import sys
import tempfile
from pathlib import Path, PurePosixPath

WORKSTREAM_ID = "quartet_restoration"
STAGE71_REPORT = "BR_quartet_restoration_bathroom_river_containing_pak_repack_test_evidence.tar.zst"
STAGE72_REPORT = "BR_quartet_restoration_bathroom_river_core_target_request_evidence.tar.zst"
STAGE72_ROOT = "bathroom_river_core_target_request_evidence"
STAGE72_FILES = {
    "SUMMARY.json",
    "CORE_INTERFACE_REQUEST.json",
    "CORE_INTERFACE_REQUEST.md",
    "PENDING_PROFILE.tsv",
    "VALIDATIONS.tsv",
}
PROFILE_ID = "candidate_bathroom_river_containing_pak_static_inverse_062e39915e7d"
TARGET_ARCHIVE = "Data/PACK10_03.PAK"
TARGET_MEMBER = "data/b1/x64/field/s89_s_hinako_bath_room_01/s89_s_hinako_bath_room_01.elixir.gz"
BASELINE_SHA256 = "1f96cc82f869643232445586777d189310de56fb7ad1c90fac9785dc95e8d762"
BASELINE_SIZE = 10082928931
PROFILE_SHA256 = "f0eb8da6f2ea2ad9baa1e0eaab26d577f17225968542b7d7b2f66a0ecd14c10d"
PROFILE_SIZE = 10082518244
LOCAL_PROFILE_PATH = (
    ".local/build/quartet_restoration/repack_tests/bathroom_river_containing_pak/"
    "profiles/candidate_bathroom_river_containing_pak_static_inverse_062e39915e7d/"
    "output/Data/PACK10_03.PAK"
)


class RegistrationError(RuntimeError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RegistrationError(message)


def load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    require(spec is not None and spec.loader is not None, f"cannot load module: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def safe_extract(archive: Path, destination: Path) -> Path:
    require(archive.is_file(), f"missing stage-72 report: {archive}")
    listed = subprocess.run(
        ["tar", "--zstd", "-tf", str(archive)],
        text=True,
        capture_output=True,
    )
    require(listed.returncode == 0, "failed to list stage-72 report: " + (listed.stderr.strip() or listed.stdout.strip()))
    for raw in listed.stdout.splitlines():
        pure = PurePosixPath(raw)
        require(not pure.is_absolute() and ".." not in pure.parts, f"unsafe report path: {raw}")
    extracted = subprocess.run(
        ["tar", "--zstd", "-xf", str(archive), "-C", str(destination)],
        text=True,
        capture_output=True,
    )
    require(extracted.returncode == 0, "failed to extract stage-72 report: " + (extracted.stderr.strip() or extracted.stdout.strip()))
    for path in destination.rglob("*"):
        require(not path.is_symlink(), f"stage-72 report contains a symlink: {path}")
    root = destination / STAGE72_ROOT
    require(root.is_dir(), f"stage-72 report root is missing: {STAGE72_ROOT}")
    files = {path.relative_to(root).as_posix() for path in root.rglob("*") if path.is_file()}
    require(files == STAGE72_FILES, "stage-72 report file set is not canonical")
    return root


def read_tsv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def validate_stage72_report(archive: Path) -> dict[str, object]:
    with tempfile.TemporaryDirectory(prefix="br-stage72-validate-") as temporary:
        root = safe_extract(archive, Path(temporary))
        summary = json.loads((root / "SUMMARY.json").read_text(encoding="utf-8"))
        mirror = json.loads((root / "CORE_INTERFACE_REQUEST.json").read_text(encoding="utf-8"))
        require(summary == mirror, "stage-72 summary and interface request differ")
        require(summary.get("type") == "br_quartet_restoration_core_target_interface_request", "stage-72 summary type mismatch")
        require(summary.get("format_version") == 1, "stage-72 format version mismatch")
        require(summary.get("tool_version") == "0.0.82", "stage-72 tool version mismatch")
        require(summary.get("status") in {
            "core_target_extension_required_before_profile_registration",
            "core_target_already_supported_registration_stage_can_follow",
        }, "stage-72 status mismatch")
        expected = {
            "requested_target_relative_path": TARGET_ARCHIVE,
            "requested_target_kind": "field",
            "requested_state_path": ".local/state/core_unified_patcher/quartet_field_profile.json",
            "requested_report_latest": ".local/reports/core/BR_QUARTET_FIELD_PROFILE_TRANSACTION_REPORT.json",
            "requested_report_dir": ".local/reports/core/quartet_field_profiles",
        }
        for key, value in expected.items():
            require(summary.get(key) == value, f"stage-72 field mismatch: {key}")
        require(summary.get("requested_commands") == [
            "quartet-field-profile-activate",
            "quartet-field-profile-status",
            "quartet-field-profile-rollback",
        ], "stage-72 command request mismatch")
        pending = summary.get("profile_to_register_after_core_update")
        require(isinstance(pending, dict), "stage-72 pending profile is missing")
        expected_pending = {
            "profile_id": PROFILE_ID,
            "target_relative_path": TARGET_ARCHIVE,
            "baseline_sha256": BASELINE_SHA256,
            "baseline_size": BASELINE_SIZE,
            "profile_sha256": PROFILE_SHA256,
            "profile_size": PROFILE_SIZE,
            "local_profile_path": LOCAL_PROFILE_PATH,
            "changed_members": [TARGET_MEMBER],
            "runtime_validated": False,
        }
        require(pending == expected_pending, "stage-72 pending profile metadata mismatch")
        registry = summary.get("restoration_registry_state")
        require(isinstance(registry, dict), "stage-72 registry state is missing")
        require(registry.get("current_profiles") == 14, "stage-72 source registry count mismatch")
        require(registry.get("expected_profiles_after_registration") == 15, "stage-72 expected registry count mismatch")
        require(registry.get("pack11_profiles_after_registration") == 12, "stage-72 PACK11 count mismatch")
        require(registry.get("pack10_01_profiles_after_registration") == 2, "stage-72 PACK10_01 count mismatch")
        require(registry.get("pack10_03_profiles_after_registration") == 1, "stage-72 PACK10_03 count mismatch")
        policy = summary.get("policy")
        require(isinstance(policy, dict), "stage-72 policy is missing")
        for key in (
            "restoration_only_update",
        ):
            require(policy.get(key) is True, f"stage-72 required policy is false: {key}")
        for key in (
            "core_sources_modified",
            "registry_modified",
            "profile_activated",
            "installed_game_modified",
            "runtime_validation_inferred",
            "opaque_binary_semantics_inferred",
            "canary_track_modified",
        ):
            require(policy.get(key) is False, f"stage-72 forbidden policy is true: {key}")
        rows = read_tsv(root / "PENDING_PROFILE.tsv")
        require(len(rows) == 1, "stage-72 pending profile table must contain one row")
        row = rows[0]
        require(row.get("profile_id") == PROFILE_ID, "stage-72 pending profile ID mismatch")
        require(row.get("target_relative_path") == TARGET_ARCHIVE, "stage-72 pending target mismatch")
        require(row.get("profile_sha256") == PROFILE_SHA256, "stage-72 pending checksum mismatch")
        require(row.get("changed_member") == TARGET_MEMBER, "stage-72 pending member mismatch")
        validations = read_tsv(root / "VALIDATIONS.tsv")
        require(len(validations) == 5, "stage-72 validation row count mismatch")
        require(len({row.get("check_name") for row in validations}) == 5, "stage-72 validation checks are duplicated")
        require(all(row.get("passed") in {"True", "False"} for row in validations), "stage-72 validation boolean mismatch")
        return summary


def validate_core_extension(project_root: Path, request_module) -> dict[str, object]:
    support = request_module.inspect_core_support(project_root)
    require(support.get("fully_supported") is True, "core PACK10_03 support is incomplete")
    require(support.get("target_registered") is True, "core target allowlist lacks PACK10_03")
    require(support.get("activation_commands_present") is True, "core field commands are missing")
    require(support.get("wrapper_support_present") is True, "field profile wrapper is missing")
    require(support.get("generic_mutual_exclusion_present") is True, "generic three-target mutual exclusion is missing")
    require(support.get("current_target_count") == 3, "core must expose exactly three local-profile targets")
    require(support.get("current_other_state_is_scalar") is False, "legacy scalar OtherState remains in core")
    completed = subprocess.run(
        ["go", "test", "./cmd/brpatcher"],
        cwd=project_root / "Blue_Reflection_Patcher",
        text=True,
        capture_output=True,
    )
    require(completed.returncode == 0, "core local-profile tests failed: " + (completed.stderr.strip() or completed.stdout.strip()))
    return support


def validate_generator_extension(generator) -> None:
    specs = list(getattr(generator, "CURRENT_PROFILE_SPECS", ()))
    require(len(specs) == 15, "generic generator must contain exactly fifteen profiles")
    ids = [item.profile_id for item in specs]
    require(len(ids) == len(set(ids)), "generic generator contains duplicate profile IDs")
    require(ids.count(PROFILE_ID) == 1, "bathroom river profile spec is missing or duplicated")
    require(sum(item.target_relative_path == "Data/PACK11.PAK" for item in specs) == 12, "generator PACK11 count mismatch")
    require(sum(item.target_relative_path == "Data/PACK10_01.PAK" for item in specs) == 2, "generator PACK10_01 count mismatch")
    require(sum(item.target_relative_path == "Data/PACK10_03.PAK" for item in specs) == 1, "generator PACK10_03 count mismatch")
    selected = next(item for item in specs if item.profile_id == PROFILE_ID)
    require(selected.target_relative_path == TARGET_ARCHIVE, "field profile target mismatch")
    require(selected.baseline_sha256 == BASELINE_SHA256 and selected.baseline_size == BASELINE_SIZE, "field profile baseline mismatch")
    require(selected.profile_sha256 == PROFILE_SHA256 and selected.profile_size == PROFILE_SIZE, "field profile output mismatch")
    require(selected.local_profile_path == LOCAL_PROFILE_PATH, "field profile local path mismatch")
    require(selected.changed_members == (TARGET_MEMBER,), "field profile member mismatch")


def register_profile(project_root: Path, *, create_report_archive: bool = True):
    request_module = load_module(
        project_root / "workstreams/quartet_restoration/prepare_bathroom_river_core_target_request.py",
        "prepare_bathroom_river_core_target_request_for_stage73",
    )
    stage71 = project_root / ".local/reports" / WORKSTREAM_ID / STAGE71_REPORT
    stage72 = project_root / ".local/reports" / WORKSTREAM_ID / STAGE72_REPORT
    request_module.validate_stage71_report(stage71)
    validate_stage72_report(stage72)
    support = validate_core_extension(project_root, request_module)
    generator = load_module(
        project_root / "workstreams/quartet_restoration/generate_core_profile_manifests.py",
        "generate_core_profile_manifests_for_stage73",
    )
    validate_generator_extension(generator)
    generated, report, manifests = generator.generate_manifests(
        project_root=project_root,
        create_report_archive=create_report_archive,
    )
    require(len(manifests) == 15, "generic registry did not generate exactly fifteen manifests")
    require(all(item.get("runtime_validated") is False for item in manifests), "one or more profiles are runtime-validated")
    selected = [item for item in manifests if item.get("profile_id") == PROFILE_ID]
    require(len(selected) == 1, "field manifest is missing or duplicated")
    manifest = selected[0]
    require(manifest.get("target_relative_path") == TARGET_ARCHIVE, "field manifest target mismatch")
    require(manifest.get("baseline_sha256") == BASELINE_SHA256, "field manifest baseline mismatch")
    require(manifest.get("baseline_size") == BASELINE_SIZE, "field manifest baseline size mismatch")
    require(manifest.get("profile_sha256") == PROFILE_SHA256, "field manifest checksum mismatch")
    require(manifest.get("profile_size") == PROFILE_SIZE, "field manifest size mismatch")
    require(manifest.get("local_profile_path") == LOCAL_PROFILE_PATH, "field manifest local path mismatch")
    require(manifest.get("changed_members") == [TARGET_MEMBER], "field manifest member mismatch")
    require(sum(item.get("target_relative_path") == "Data/PACK11.PAK" for item in manifests) == 12, "generated PACK11 count mismatch")
    require(sum(item.get("target_relative_path") == "Data/PACK10_01.PAK" for item in manifests) == 2, "generated PACK10_01 count mismatch")
    require(sum(item.get("target_relative_path") == "Data/PACK10_03.PAK" for item in manifests) == 1, "generated PACK10_03 count mismatch")
    return generated, report, manifests, support


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", required=True)
    parser.add_argument("--no-report-archive", action="store_true")
    args = parser.parse_args()
    project_root = Path(args.project_root).expanduser().resolve()
    generated, report, manifests, support = register_profile(
        project_root,
        create_report_archive=not args.no_report_archive,
    )
    print(f"Core PACK10_03 target verified: {support['fully_supported']}")
    print(f"Generated manifests: {len(manifests)}")
    print(f"Manifest directory: {generated}")
    print(f"Registered field profile: {PROFILE_ID} (runtime_validated=false)")
    if report is not None:
        print(f"Report: {report}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except RegistrationError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
