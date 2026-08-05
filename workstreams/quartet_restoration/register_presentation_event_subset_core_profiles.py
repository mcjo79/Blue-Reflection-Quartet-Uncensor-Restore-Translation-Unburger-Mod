#!/usr/bin/env python3
"""Validate stage-46 evidence and atomically register six subset PACK11 profiles."""

from __future__ import annotations

import argparse
import csv
import importlib.util
import json
import re
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

WORKSTREAM_ID = "quartet_restoration"
REPORT_NAME = "BR_quartet_restoration_presentation_event_subset_repack_test_evidence.tar.zst"
REPORT_DIR = "presentation_event_subset_repack_test_evidence"
TARGET_ARCHIVE = "Data/PACK11.PAK"
BASELINE_SHA256 = "bf53826c840cec9f5cb4044a121a4bada29dd14f56c9f1b1b7633b57cc067306"
BASELINE_SIZE = 13372318
EXPECTED_REPORT_FILES = {
    "SUMMARY.json",
    "PRESENTATION_EVENT_SUBSET_REPACK_BUILD_SKIPPED.tsv",
    "PRESENTATION_EVENT_SUBSET_REPACK_FILES.tsv",
    "PRESENTATION_EVENT_SUBSET_REPACK_MANIFEST_DIFFERENCES.tsv",
    "PRESENTATION_EVENT_SUBSET_REPACK_PROFILES.tsv",
    "PRESENTATION_EVENT_SUBSET_REPACK_VALIDATION.tsv",
}
HEX64_RE = re.compile(r"^[0-9a-f]{64}$")


class RegistrationError(RuntimeError):
    """Raised when stage-46 evidence is not safe to register."""


@dataclass(frozen=True)
class ExpectedProfile:
    profile_id: str
    profile_sha256: str
    profile_size: int
    local_profile_path: str
    changed_member: str
    changed_member_sha256: str


EXPECTED_PROFILES: tuple[ExpectedProfile, ...] = (
    ExpectedProfile(
        "candidate_subset_ce07_060_1cddf6cac60969c4",
        "ce7d5975de799c222483bc794f4d2b2e884bb64d7a322282d3cf06f3fc07920f",
        13372366,
        ".local/build/quartet_restoration/repack_tests/presentation_event_subset/profiles/candidate_subset_ce07_060_1cddf6cac60969c4/output/Data/PACK11.PAK",
        "event/b1/event_jp/ce07/event_ce07_060.ebd",
        "b094588a141e575b3bd492c5f0d7f4ec651ded8541f11b0556336984e918007e",
    ),
    ExpectedProfile(
        "candidate_subset_ce11_010_abc7939e4ff69ead",
        "e7cebe041ed620142ee386683769299e577dd85ba964ebe33aeda0786a5fbc0b",
        13372278,
        ".local/build/quartet_restoration/repack_tests/presentation_event_subset/profiles/candidate_subset_ce11_010_abc7939e4ff69ead/output/Data/PACK11.PAK",
        "event/b1/event_jp/ce11/event_ce11_010.ebd",
        "1c7a36781d9a72e936ec41b5aa8efdfed634b83e862177e1eab94a5901fcef90",
    ),
    ExpectedProfile(
        "candidate_subset_em01_060_43f9052741640b35",
        "391d228247246f9ee54cbc0109b99777265b8476803bf0d11a2f2bd7aa9036b3",
        13372258,
        ".local/build/quartet_restoration/repack_tests/presentation_event_subset/profiles/candidate_subset_em01_060_43f9052741640b35/output/Data/PACK11.PAK",
        "event/b1/event_jp/em01/event_em01_060.ebd",
        "dc0371c27031749cefedf86d2eb9196c02ef8681a51f3b2f4aa0d3ef5057e56b",
    ),
    ExpectedProfile(
        "candidate_subset_em02_030_552c84999f656afb",
        "95f2a4129abc81b3c0caa68cc8fe36e9bd166634b15ee1fe64095962749d00dd",
        13372230,
        ".local/build/quartet_restoration/repack_tests/presentation_event_subset/profiles/candidate_subset_em02_030_552c84999f656afb/output/Data/PACK11.PAK",
        "event/b1/event_jp/em02/event_em02_030.ebd",
        "3d518d903d4094d0e514da09576c34b7c6d7cbb1a3f8b674760e98675448b8bb",
    ),
    ExpectedProfile(
        "candidate_subset_te01_270_f6e3b892ac7ba1b9",
        "a91189fcdd4e6ae1695e7182a00735ba500cc1da50b76b7d2dedc6cbc7880c57",
        13371706,
        ".local/build/quartet_restoration/repack_tests/presentation_event_subset/profiles/candidate_subset_te01_270_f6e3b892ac7ba1b9/output/Data/PACK11.PAK",
        "event/b1/event_jp/te01/event_te01_270.ebd",
        "d054958864a1a958356bc55d5c6ac821de50e2210ace9821df33855b6c23031a",
    ),
    ExpectedProfile(
        "candidate_subset_xf07_030_d85e6afc33b5802b",
        "946a61f64ed3c89f23ff8f0bb3d932804e7b3c16bde26477c436dbf81182b344",
        13372298,
        ".local/build/quartet_restoration/repack_tests/presentation_event_subset/profiles/candidate_subset_xf07_030_d85e6afc33b5802b/output/Data/PACK11.PAK",
        "event/b1/event_jp/xf07/event_xf07_030.ebd",
        "43bd49ca9f604dc332f471ef9e5f964985bad16047e207a8e58bea3ae4b436e6",
    ),
)
EXPECTED_BY_ID = {item.profile_id: item for item in EXPECTED_PROFILES}


def load_generator(project_root: Path):
    path = project_root / "workstreams" / WORKSTREAM_ID / "generate_core_profile_manifests.py"
    spec = importlib.util.spec_from_file_location("generate_core_profile_manifests_stage47", path)
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
        if len(PurePosixPath(name).parts) == 2 and PurePosixPath(name).parts[0] == REPORT_DIR
    }
    unexpected = [
        name for name in names
        if PurePosixPath(name).parts[0] != REPORT_DIR or len(PurePosixPath(name).parts) > 2
    ]
    if unexpected:
        raise RegistrationError(f"unexpected report members: {unexpected[:3]}")
    if files != EXPECTED_REPORT_FILES:
        raise RegistrationError(
            f"report file set mismatch: expected {sorted(EXPECTED_REPORT_FILES)}, got {sorted(files)}"
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


def validate_stage46_report(report_path: Path) -> dict[str, object]:
    if report_path.is_symlink() or not report_path.is_file():
        raise RegistrationError(f"stage-46 report is missing or unsafe: {report_path}")
    with tempfile.TemporaryDirectory(prefix="br-stage46-profiles-") as raw_tmp:
        root = extract_report(report_path, Path(raw_tmp))
        summary = json.loads((root / "SUMMARY.json").read_text(encoding="utf-8"))
        require(summary.get("tool_version") == "0.0.53", "unexpected stage-46 tool version")
        require(
            summary.get("status") == "six_separate_checksum_gated_local_presentation_event_subset_pack11_profiles_built_reextracted_and_validated_not_installed",
            "unexpected stage-46 status",
        )
        require(summary.get("profile_rows") == 6, "stage-46 profile count is not six")
        require(summary.get("file_rows") == 6, "stage-46 file count is not six")
        require(summary.get("validation_rows") == 102, "stage-46 validation count is not 102")
        require(summary.get("validation_failures") == 0, "stage-46 validation failures are nonzero")
        require(summary.get("stable_manifest_difference_rows") == 0, "stable manifest differences are nonzero")
        require(summary.get("derived_manifest_difference_rows") == 56382, "derived manifest diagnostic count mismatch")
        require(summary.get("skipped_rows") == 0, "stage-46 skipped rows are nonzero")
        require(summary.get("input_archive_sha256") == BASELINE_SHA256, "baseline archive checksum mismatch")
        require(summary.get("input_archive_size") == BASELINE_SIZE, "baseline archive size mismatch")
        require(summary.get("inventory_pristine_archive_match") is True, "baseline does not match inventory")
        policy = summary.get("policy")
        require(isinstance(policy, dict), "stage-46 policy is missing")
        for key in (
            "installed_game_read_only",
            "current_pack11_used_as_repack_base",
            "profile_archives_kept_separate",
            "all_unchanged_members_verified_by_reextraction_hash",
            "unrelated_translation_and_other_mod_members_preserved",
            "existing_pack11_profiles_left_untouched",
            "local_rollback_baseline_copied",
        ):
            require(policy.get(key) is True, f"required policy gate is false: {key}")
        require(policy.get("candidate_members_replaced_per_profile") == 1, "unexpected replaced-member policy count")
        for key in (
            "installed_game_modified",
            "core_profile_manifest_generated",
            "activation_or_installer_generated",
            "runtime_validation_inferred",
        ):
            require(policy.get(key) is False, f"forbidden policy state is true: {key}")

        skipped = read_tsv(root / "PRESENTATION_EVENT_SUBSET_REPACK_BUILD_SKIPPED.tsv")
        require(not skipped, "stage-46 report contains skipped builds")

        profiles = read_tsv(root / "PRESENTATION_EVENT_SUBSET_REPACK_PROFILES.tsv")
        require(len(profiles) == 6, "stage-46 profile table does not contain six rows")
        require(len({row.get("profile_id") for row in profiles}) == 6, "duplicate stage-46 profile rows")
        for row in profiles:
            profile_id = row.get("profile_id", "")
            require(profile_id in EXPECTED_BY_ID, f"unexpected stage-46 profile: {profile_id}")
            expected = EXPECTED_BY_ID[profile_id]
            expected_fields = {
                "profile_classification": "experimental_bounded_subset_static_candidate",
                "prototype_confidence": "experimental_metadata_gated",
                "source_stage45_profile_id": profile_id,
                "input_archive_relative_path": TARGET_ARCHIVE,
                "input_archive_sha256": BASELINE_SHA256,
                "input_archive_size": str(BASELINE_SIZE),
                "inventory_pristine_archive_match": "True",
                "output_archive_sha256": expected.profile_sha256,
                "output_archive_size": str(expected.profile_size),
                "replaced_member_count": "1",
                "unchanged_member_count_verified": "9396",
                "local_output_archive": expected.local_profile_path,
                "validation_status": "passed",
                "activation_status": "not_generated_generic_core_manifest_required",
            }
            for key, value in expected_fields.items():
                require(row.get(key) == value, f"profile field mismatch for {profile_id}:{key}")

        files = read_tsv(root / "PRESENTATION_EVENT_SUBSET_REPACK_FILES.tsv")
        require(len(files) == 6, "stage-46 file table does not contain six rows")
        require(len({row.get("profile_id") for row in files}) == 6, "duplicate stage-46 file rows")
        for row in files:
            profile_id = row.get("profile_id", "")
            require(profile_id in EXPECTED_BY_ID, f"unexpected file profile: {profile_id}")
            expected = EXPECTED_BY_ID[profile_id]
            require(row.get("target_archive") == TARGET_ARCHIVE, f"target archive mismatch for {profile_id}")
            require(row.get("target_member_path") == expected.changed_member, f"changed member mismatch for {profile_id}")
            digest = row.get("repacked_member_sha256", "")
            require(HEX64_RE.fullmatch(digest) is not None, f"invalid repacked member checksum for {profile_id}")
            require(digest == expected.changed_member_sha256, f"repacked member checksum mismatch for {profile_id}")
            require(row.get("candidate_sha256") == digest, f"candidate/repacked mismatch for {profile_id}")
            require(row.get("validation_status") == "passed", f"file validation failed for {profile_id}")

        validations = read_tsv(root / "PRESENTATION_EVENT_SUBSET_REPACK_VALIDATION.tsv")
        require(len(validations) == 102, "stage-46 validation table does not contain 102 rows")
        for expected in EXPECTED_PROFILES:
            rows = [row for row in validations if row.get("profile_id") == expected.profile_id]
            require(len(rows) == 17, f"validation count is not 17 for {expected.profile_id}")
            require(len({row.get("check_name") for row in rows}) == 17, f"duplicate validation checks for {expected.profile_id}")
            require(all(row.get("passed") == "True" for row in rows), f"validation gate failed for {expected.profile_id}")

        differences = read_tsv(root / "PRESENTATION_EVENT_SUBSET_REPACK_MANIFEST_DIFFERENCES.tsv")
        require(len(differences) == 56382, "unexpected manifest-difference diagnostic row count")
        for expected in EXPECTED_PROFILES:
            rows = [row for row in differences if row.get("profile_id") == expected.profile_id]
            require(len(rows) == 9397, f"manifest diagnostic count mismatch for {expected.profile_id}")
            classifications = [row.get("classification") for row in rows]
            require(classifications.count("derived_unchanged_member_metadata") == 9396,
                    f"unexpected unchanged-member diagnostic count for {expected.profile_id}")
            require(classifications.count("derived_modified_member_metadata") == 1,
                    f"unexpected modified-member diagnostic count for {expected.profile_id}")
            require(set(classifications) == {
                "derived_unchanged_member_metadata",
                "derived_modified_member_metadata",
            }, f"stable or unknown manifest differences for {expected.profile_id}")
            require(all(row.get("gate_effect") == "diagnostic_only" for row in rows),
                    f"manifest difference unexpectedly affects a gate for {expected.profile_id}")
        return summary


def register_profiles(project_root: Path, report_path: Path, *, create_report_archive: bool = True):
    validate_stage46_report(report_path)
    generator = load_generator(project_root)
    generated, report, manifests = generator.generate_manifests(
        project_root=project_root,
        create_report_archive=create_report_archive,
    )
    require(len(manifests) >= 13, "generic registry generated fewer than thirteen manifests")
    manifest_by_id = {item.get("profile_id"): item for item in manifests}
    require(len(manifest_by_id) == len(manifests), "generic registry contains duplicate profile IDs")
    for expected in EXPECTED_PROFILES:
        require(expected.profile_id in manifest_by_id, f"new subset manifest is missing: {expected.profile_id}")
        manifest = manifest_by_id[expected.profile_id]
        require(manifest.get("target_relative_path") == TARGET_ARCHIVE, f"manifest target mismatch for {expected.profile_id}")
        require(manifest.get("baseline_sha256") == BASELINE_SHA256, f"manifest baseline mismatch for {expected.profile_id}")
        require(manifest.get("profile_sha256") == expected.profile_sha256, f"manifest profile checksum mismatch for {expected.profile_id}")
        require(manifest.get("profile_size") == expected.profile_size, f"manifest profile size mismatch for {expected.profile_id}")
        require(manifest.get("local_profile_path") == expected.local_profile_path, f"manifest local path mismatch for {expected.profile_id}")
        require(manifest.get("changed_members") == [expected.changed_member], f"manifest member list mismatch for {expected.profile_id}")
        require(manifest.get("runtime_validated") is False, f"manifest must remain runtime-unvalidated: {expected.profile_id}")
    return generated, report, manifests


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", required=True)
    parser.add_argument("--no-report-archive", action="store_true")
    args = parser.parse_args()
    project_root = Path(args.project_root).expanduser().resolve()
    report_path = project_root / ".local" / "reports" / WORKSTREAM_ID / REPORT_NAME
    generated, report, manifests = register_profiles(
        project_root,
        report_path,
        create_report_archive=not args.no_report_archive,
    )
    print(f"Validated stage-46 report: {report_path}")
    print(f"Generated manifests: {len(manifests)}")
    print(f"Manifest directory: {generated}")
    print("Registered profiles:")
    for expected in EXPECTED_PROFILES:
        print(f"- {expected.profile_id} (runtime_validated=false)")
    if report is not None:
        print(f"Report: {report}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except RegistrationError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
