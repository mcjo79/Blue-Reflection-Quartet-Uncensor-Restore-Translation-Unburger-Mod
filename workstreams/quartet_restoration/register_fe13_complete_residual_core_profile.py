#!/usr/bin/env python3
"""Validate stage-61 evidence and atomically replace the superseded fe13_090 core profile."""

from __future__ import annotations

import argparse
import csv
import importlib.util
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path, PurePosixPath

WORKSTREAM_ID = "quartet_restoration"
REPORT_NAME = "BR_quartet_restoration_fe13_complete_residual_repack_test_evidence.tar.zst"
REPORT_DIR = "fe13_complete_residual_repack_test_evidence"
PROFILE_ID = "candidate_fe13_090_complete_residual_inverse_9a57d11730c0"
SUPERSEDES_PROFILE_ID = "candidate_unselected_cue_residual_fe13_090_8330c2a15d46"
TARGET_ARCHIVE = "Data/PACK11.PAK"
BASELINE_SHA256 = "bf53826c840cec9f5cb4044a121a4bada29dd14f56c9f1b1b7633b57cc067306"
BASELINE_SIZE = 13372318
PROFILE_SHA256 = "950a037d16f888281b1c071f35054aec1b5da44e68cfa832af442f9a719e847c"
PROFILE_SIZE = 13372230
LOCAL_PROFILE_PATH = ".local/build/quartet_restoration/repack_tests/fe13_complete_residual/profiles/candidate_fe13_090_complete_residual_inverse_9a57d11730c0/output/Data/PACK11.PAK"
EXPECTED_MEMBERS = {
    "event/b1/event_jp/fe13/event_fe13_090.ebd":
        "9a57d11730c0f952ee0abcb6083efeaec243f87720279997e3dcae5a88bd88c7",
}
EXPECTED_REPORT_FILES = {
    "SUMMARY.json",
    "FE13_COMPLETE_RESIDUAL_REPACK_TEST_BUILD_SKIPPED.tsv",
    "FE13_COMPLETE_RESIDUAL_REPACK_TEST_FILES.tsv",
    "FE13_COMPLETE_RESIDUAL_REPACK_TEST_MANIFEST_DIFFERENCES.tsv",
    "FE13_COMPLETE_RESIDUAL_REPACK_TEST_PROFILES.tsv",
    "FE13_COMPLETE_RESIDUAL_REPACK_TEST_VALIDATION.tsv",
}
HEX64_RE = re.compile(r"^[0-9a-f]{64}$")


class RegistrationError(RuntimeError):
    """Raised when stage-61 evidence or replacement registry state is unsafe."""


def load_generator(project_root: Path):
    path = project_root / "workstreams" / WORKSTREAM_ID / "generate_core_profile_manifests.py"
    spec = importlib.util.spec_from_file_location(
        "generate_core_profile_manifests_stage62", path
    )
    if not spec or not spec.loader:
        raise RegistrationError(f"cannot load manifest generator: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def safe_member_name(raw: str) -> str:
    name = raw.rstrip("/")
    path = PurePosixPath(name)
    if path.is_absolute() or not path.parts or "." in path.parts or ".." in path.parts:
        raise RegistrationError(f"unsafe report member: {raw}")
    canonical = path.as_posix()
    if canonical != name:
        raise RegistrationError(f"non-canonical report member: {raw}")
    return canonical


def run_tar(args: list[str]) -> subprocess.CompletedProcess[str]:
    completed = subprocess.run(args, text=True, capture_output=True)
    if completed.returncode != 0:
        detail = completed.stderr.strip() or completed.stdout.strip() or "unknown tar error"
        raise RegistrationError(f"report archive operation failed: {detail}")
    return completed


def extract_report(report_path: Path, temporary: Path) -> Path:
    listed = run_tar(["tar", "--zstd", "-tf", str(report_path)]).stdout.splitlines()
    names = [safe_member_name(raw) for raw in listed if raw.rstrip("/")]
    files = {
        PurePosixPath(name).name
        for name in names
        if len(PurePosixPath(name).parts) == 2
        and PurePosixPath(name).parts[0] == REPORT_DIR
    }
    unexpected = [
        name
        for name in names
        if PurePosixPath(name).parts[0] != REPORT_DIR
        or len(PurePosixPath(name).parts) > 2
    ]
    if unexpected:
        raise RegistrationError(f"unexpected report members: {unexpected[:3]}")
    if files != EXPECTED_REPORT_FILES:
        raise RegistrationError(
            f"report file set mismatch: expected {sorted(EXPECTED_REPORT_FILES)}, "
            f"got {sorted(files)}"
        )
    run_tar(["tar", "--zstd", "-xf", str(report_path), "-C", str(temporary)])
    root = temporary / REPORT_DIR
    if root.is_symlink() or not root.is_dir():
        raise RegistrationError("report root is missing or unsafe")
    for filename in EXPECTED_REPORT_FILES:
        path = root / filename
        if path.is_symlink() or not path.is_file():
            raise RegistrationError(f"report file is missing or unsafe: {filename}")
    return root


def read_tsv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RegistrationError(message)


def validate_stage61_report(report_path: Path) -> dict[str, object]:
    if report_path.is_symlink() or not report_path.is_file():
        raise RegistrationError(f"stage-61 report is missing or unsafe: {report_path}")
    with tempfile.TemporaryDirectory(prefix="br-stage61-profile-") as raw_tmp:
        root = extract_report(report_path, Path(raw_tmp))
        summary = json.loads((root / "SUMMARY.json").read_text(encoding="utf-8"))
        require(summary.get("tool_version") == "0.0.70", "unexpected stage-61 tool version")
        require(
            summary.get("status")
            == "one_checksum_gated_local_fe13_complete_residual_pack11_profile_built_reextracted_and_validated_not_installed",
            "unexpected stage-61 status",
        )
        require(summary.get("source_fe13_complete_residual_prototype_tool_version") == "0.0.69",
                "unexpected stage-60 source version")
        require(summary.get("repack_engine_tool_version") == "0.0.38",
                "unexpected repack-engine version")
        require(summary.get("profile_rows") == 1, "stage-61 profile count is not one")
        require(summary.get("file_rows") == 1, "stage-61 file count is not one")
        require(summary.get("validation_rows") == 17, "stage-61 validation count is not 17")
        require(summary.get("validation_failures") == 0,
                "stage-61 validation failures are nonzero")
        require(summary.get("manifest_difference_rows") == 9397,
                "manifest-difference diagnostic count mismatch")
        require(summary.get("stable_manifest_difference_rows") == 0,
                "stable manifest differences are nonzero")
        require(summary.get("derived_manifest_difference_rows") == 9397,
                "derived manifest diagnostic count mismatch")
        require(summary.get("skipped_rows") == 0, "stage-61 skipped rows are nonzero")
        require(summary.get("input_archive_relative_path") == TARGET_ARCHIVE,
                "stage-61 target archive mismatch")
        require(summary.get("input_archive_sha256") == BASELINE_SHA256,
                "baseline archive checksum mismatch")
        require(summary.get("input_archive_size") == BASELINE_SIZE,
                "baseline archive size mismatch")
        require(summary.get("inventory_pristine_archive_sha256") == BASELINE_SHA256,
                "inventory baseline checksum mismatch")
        require(summary.get("inventory_pristine_archive_match") is True,
                "baseline does not match inventory")
        require(summary.get("local_profile_archive") == LOCAL_PROFILE_PATH,
                "summary local profile path mismatch")

        policy = summary.get("policy")
        require(isinstance(policy, dict), "stage-61 policy is missing")
        for key in (
            "installed_game_read_only",
            "current_pack11_used_as_repack_base",
            "all_unchanged_members_verified_by_reextraction_hash",
            "unrelated_translation_and_other_mod_members_preserved",
            "existing_pack11_profiles_left_untouched",
            "local_rollback_baseline_copied",
        ):
            require(policy.get(key) is True, f"required policy gate is false: {key}")
        require(policy.get("candidate_members_replaced") == 1,
                "unexpected replaced-member policy count")
        for key in (
            "installed_game_modified",
            "core_profile_manifest_generated",
            "activation_or_installer_generated",
            "runtime_validation_inferred",
            "censorship_semantics_inferred",
            "proprietary_pak_exported_in_report",
            "legacy_dlc_in_scope",
            "translation_or_core_files_modified",
        ):
            require(policy.get(key) is False, f"forbidden policy state is true: {key}")

        skipped = read_tsv(root / "FE13_COMPLETE_RESIDUAL_REPACK_TEST_BUILD_SKIPPED.tsv")
        require(not skipped, "stage-61 report contains skipped builds")

        profiles = read_tsv(root / "FE13_COMPLETE_RESIDUAL_REPACK_TEST_PROFILES.tsv")
        require(len(profiles) == 1, "stage-61 profile table does not contain exactly one row")
        profile = profiles[0]
        expected_profile = {
            "profile_id": PROFILE_ID,
            "profile_classification":
                "experimental_single_scene_complete_residual_inverse_candidate",
            "prototype_confidence": "experimental_metadata_gated",
            "source_stage60_profile_id": PROFILE_ID,
            "supersedes_profile_id": SUPERSEDES_PROFILE_ID,
            "input_archive_relative_path": TARGET_ARCHIVE,
            "input_archive_sha256": BASELINE_SHA256,
            "input_archive_size": str(BASELINE_SIZE),
            "inventory_pristine_archive_match": "True",
            "output_archive_sha256": PROFILE_SHA256,
            "output_archive_size": str(PROFILE_SIZE),
            "replaced_member_count": "1",
            "unchanged_member_count_verified": "9396",
            "local_output_archive": LOCAL_PROFILE_PATH,
            "validation_status": "passed",
            "activation_status": "not_generated_generic_core_manifest_required",
        }
        for key, expected in expected_profile.items():
            require(profile.get(key) == expected, f"profile field mismatch for {key}")

        files = read_tsv(root / "FE13_COMPLETE_RESIDUAL_REPACK_TEST_FILES.tsv")
        require(len(files) == 1, "stage-61 file table does not contain exactly one row")
        row = files[0]
        require(row.get("profile_id") == PROFILE_ID, "unexpected profile_id in file table")
        require(row.get("target_archive") == TARGET_ARCHIVE, "file target archive mismatch")
        require(row.get("validation_status") == "passed",
                "repacked member validation did not pass")
        member = row.get("target_member_path", "")
        digest = row.get("repacked_member_sha256", "")
        require(HEX64_RE.fullmatch(digest) is not None, "invalid repacked member checksum")
        require(row.get("candidate_sha256") == digest,
                "repacked member differs from candidate")
        require(EXPECTED_MEMBERS == {member: digest},
                "stage-61 changed member or checksum differs")

        validations = read_tsv(root / "FE13_COMPLETE_RESIDUAL_REPACK_TEST_VALIDATION.tsv")
        require(len(validations) == 17, "stage-61 validation table does not contain 17 rows")
        require(len({row.get("check_name") for row in validations}) == 17,
                "duplicate validation checks")
        require(all(row.get("profile_id") == PROFILE_ID for row in validations),
                "unexpected validation profile")
        require(all(row.get("passed") == "True" for row in validations),
                "one or more validation gates failed")

        differences = read_tsv(
            root / "FE13_COMPLETE_RESIDUAL_REPACK_TEST_MANIFEST_DIFFERENCES.tsv"
        )
        require(len(differences) == 9397,
                "unexpected manifest-difference diagnostic row count")
        classifications = [row.get("classification") for row in differences]
        require(classifications.count("derived_unchanged_member_metadata") == 9396,
                "unexpected unchanged-member manifest diagnostic count")
        require(classifications.count("derived_modified_member_metadata") == 1,
                "unexpected modified-member manifest diagnostic count")
        require(
            set(classifications)
            == {"derived_unchanged_member_metadata", "derived_modified_member_metadata"},
            "stable or unknown manifest differences are present",
        )
        require(
            all(row.get("gate_effect") == "diagnostic_only" for row in differences),
            "manifest difference unexpectedly affects a gate",
        )
        return summary


def validate_generator_replacement(generator) -> None:
    specs = list(getattr(generator, "CURRENT_PROFILE_SPECS", ()))
    require(len(specs) >= 14, "generic generator must contain at least fourteen profiles")
    ids = [item.profile_id for item in specs]
    require(len(ids) == len(set(ids)), "generic generator contains duplicate profile IDs")
    require(ids.count(PROFILE_ID) == 1, "replacement fe13_090 profile spec is missing or duplicated")
    require(SUPERSEDES_PROFILE_ID not in ids, "superseded fe13_090 profile spec is still present")
    require(sum(item.target_relative_path == "Data/PACK11.PAK" for item in specs) == 12,
            "generic generator must contain twelve PACK11 profiles")
    require(sum(item.target_relative_path == "Data/PACK10_01.PAK" for item in specs) == 2,
            "generic generator must contain two PACK10_01 profiles")
    require(sum(item.target_relative_path == "Data/PACK10_03.PAK" for item in specs) <= 1,
            "generic generator contains duplicate PACK10_03 profiles")


def register_profile(
    project_root: Path,
    report_path: Path,
    *,
    create_report_archive: bool = True,
):
    validate_stage61_report(report_path)
    generator = load_generator(project_root)
    validate_generator_replacement(generator)
    generated, report, manifests = generator.generate_manifests(
        project_root=project_root,
        create_report_archive=create_report_archive,
    )
    require(len(manifests) >= 14, "generic registry generated fewer than fourteen manifests")
    ids = [str(item.get("profile_id", "")) for item in manifests]
    require(len(ids) == len(set(ids)), "generated registry contains duplicate profile IDs")
    require(SUPERSEDES_PROFILE_ID not in ids,
            "superseded fe13_090 manifest remains in generated registry")
    selected = [item for item in manifests if item.get("profile_id") == PROFILE_ID]
    require(len(selected) == 1, "replacement fe13_090 manifest is missing or duplicated")
    manifest = selected[0]
    require(manifest.get("target_relative_path") == TARGET_ARCHIVE,
            "replacement manifest target mismatch")
    require(manifest.get("baseline_sha256") == BASELINE_SHA256,
            "replacement manifest baseline mismatch")
    require(manifest.get("baseline_size") == BASELINE_SIZE,
            "replacement manifest baseline size mismatch")
    require(manifest.get("profile_sha256") == PROFILE_SHA256,
            "replacement manifest profile checksum mismatch")
    require(manifest.get("profile_size") == PROFILE_SIZE,
            "replacement manifest profile size mismatch")
    require(manifest.get("local_profile_path") == LOCAL_PROFILE_PATH,
            "replacement manifest local path mismatch")
    require(manifest.get("changed_members") == list(EXPECTED_MEMBERS),
            "replacement manifest member list mismatch")
    require(manifest.get("runtime_validated") is False,
            "replacement manifest must remain runtime-unvalidated")
    require(sum(item.get("target_relative_path") == "Data/PACK11.PAK" for item in manifests) == 12,
            "generated registry PACK11 count mismatch")
    require(sum(item.get("target_relative_path") == "Data/PACK10_01.PAK" for item in manifests) == 2,
            "generated registry PACK10_01 count mismatch")
    require(sum(item.get("target_relative_path") == "Data/PACK10_03.PAK" for item in manifests) <= 1,
            "generated registry PACK10_03 count mismatch")
    require(all(item.get("runtime_validated") is False for item in manifests),
            "one or more generated profiles are runtime-validated")
    return generated, report, manifests


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", required=True)
    parser.add_argument("--no-report-archive", action="store_true")
    args = parser.parse_args()
    project_root = Path(args.project_root).expanduser().resolve()
    report_path = project_root / ".local" / "reports" / WORKSTREAM_ID / REPORT_NAME
    generated, report, manifests = register_profile(
        project_root,
        report_path,
        create_report_archive=not args.no_report_archive,
    )
    print(f"Validated stage-61 report: {report_path}")
    print(f"Generated manifests: {len(manifests)}")
    print(f"Manifest directory: {generated}")
    print(f"Removed superseded profile: {SUPERSEDES_PROFILE_ID}")
    print(f"Registered replacement profile: {PROFILE_ID} (runtime_validated=false)")
    if report is not None:
        print(f"Report: {report}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except RegistrationError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
