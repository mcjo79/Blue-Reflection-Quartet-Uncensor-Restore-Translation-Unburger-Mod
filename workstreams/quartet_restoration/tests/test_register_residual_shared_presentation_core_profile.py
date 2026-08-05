from __future__ import annotations

import csv
import importlib.util
import json
import sys
import tarfile
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock


ROOT = Path(__file__).resolve().parents[3]
TOOL_PATH = ROOT / "workstreams" / "quartet_restoration" / "register_residual_shared_presentation_core_profile.py"
SPEC = importlib.util.spec_from_file_location("register_residual_shared_presentation_core_profile", TOOL_PATH)
assert SPEC and SPEC.loader
TOOL = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = TOOL
SPEC.loader.exec_module(TOOL)


def write_tsv(path: Path, fieldnames: list[str], rows: list[dict[str, object]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def build_report(root: Path, *, failed_validation: bool = False) -> Path:
    report_root = root / TOOL.REPORT_DIR
    report_root.mkdir(parents=True)
    summary = {
        "tool_version": "0.0.43",
        "profile_rows": 1,
        "file_rows": 2,
        "validation_rows": 17,
        "validation_failures": 1 if failed_validation else 0,
        "stable_manifest_difference_rows": 0,
        "skipped_rows": 0,
        "input_archive_sha256": TOOL.BASELINE_SHA256,
        "input_archive_size": TOOL.BASELINE_SIZE,
        "inventory_pristine_archive_match": True,
        "policy": {
            "installed_game_read_only": True,
            "installed_game_modified": False,
            "all_unchanged_members_verified_by_reextraction_hash": True,
            "unrelated_translation_and_other_mod_members_preserved": True,
            "existing_pack11_profiles_left_untouched": True,
            "local_rollback_baseline_copied": True,
            "core_profile_manifest_generated": False,
            "activation_or_installer_generated": False,
            "runtime_validation_inferred": False,
        },
    }
    (report_root / "SUMMARY.json").write_text(json.dumps(summary), encoding="utf-8")
    write_tsv(
        report_root / "RESIDUAL_SHARED_PRESENTATION_REPACK_BUILD_SKIPPED.tsv",
        ["profile_id", "target_member_path", "reason"],
        [],
    )
    write_tsv(
        report_root / "RESIDUAL_SHARED_PRESENTATION_REPACK_PROFILES.tsv",
        [
            "profile_id", "input_archive_relative_path", "input_archive_sha256",
            "input_archive_size", "output_archive_sha256", "output_archive_size",
            "replaced_member_count", "unchanged_member_count_verified",
            "local_output_archive", "validation_status", "activation_status",
        ],
        [{
            "profile_id": TOOL.PROFILE_ID,
            "input_archive_relative_path": TOOL.TARGET_ARCHIVE,
            "input_archive_sha256": TOOL.BASELINE_SHA256,
            "input_archive_size": TOOL.BASELINE_SIZE,
            "output_archive_sha256": TOOL.PROFILE_SHA256,
            "output_archive_size": TOOL.PROFILE_SIZE,
            "replaced_member_count": 2,
            "unchanged_member_count_verified": 9395,
            "local_output_archive": TOOL.LOCAL_PROFILE_PATH,
            "validation_status": "passed",
            "activation_status": "not_generated_generic_core_manifest_required",
        }],
    )
    file_rows = []
    for member, digest in TOOL.EXPECTED_MEMBERS.items():
        file_rows.append({
            "profile_id": TOOL.PROFILE_ID,
            "target_member_path": member,
            "candidate_sha256": digest,
            "repacked_member_sha256": digest,
            "validation_status": "passed",
        })
    write_tsv(
        report_root / "RESIDUAL_SHARED_PRESENTATION_REPACK_FILES.tsv",
        ["profile_id", "target_member_path", "candidate_sha256", "repacked_member_sha256", "validation_status"],
        file_rows,
    )
    validation_rows = []
    for index in range(17):
        validation_rows.append({
            "profile_id": TOOL.PROFILE_ID,
            "check_name": f"check_{index:02d}",
            "passed": "False" if failed_validation and index == 0 else "True",
            "details": "",
        })
    write_tsv(
        report_root / "RESIDUAL_SHARED_PRESENTATION_REPACK_VALIDATION.tsv",
        ["profile_id", "check_name", "passed", "details"],
        validation_rows,
    )
    diff_rows = [{
        "classification": "derived_unchanged_member_metadata",
        "gate_effect": "diagnostic_only",
    } for _ in range(9395)]
    diff_rows.extend({
        "classification": "derived_modified_member_metadata",
        "gate_effect": "diagnostic_only",
    } for _ in range(2))
    write_tsv(
        report_root / "RESIDUAL_SHARED_PRESENTATION_REPACK_MANIFEST_DIFFERENCES.tsv",
        ["classification", "gate_effect"],
        diff_rows,
    )
    archive = root / TOOL.REPORT_NAME
    import subprocess
    completed = subprocess.run(
        ["tar", "--zstd", "-cf", str(archive), "-C", str(root), TOOL.REPORT_DIR],
        text=True,
        capture_output=True,
    )
    if completed.returncode != 0:
        raise RuntimeError(completed.stderr)
    return archive


class ResidualSharedPresentationRegistrationTests(unittest.TestCase):
    def test_validates_complete_stage37_report(self):
        with tempfile.TemporaryDirectory() as temporary:
            report = build_report(Path(temporary))
            summary = TOOL.validate_stage37_report(report)
            self.assertEqual(summary["profile_rows"], 1)
            self.assertEqual(summary["validation_failures"], 0)

    def test_rejects_failed_stage37_gate(self):
        with tempfile.TemporaryDirectory() as temporary:
            report = build_report(Path(temporary), failed_validation=True)
            with self.assertRaisesRegex(TOOL.RegistrationError, "validation failures"):
                TOOL.validate_stage37_report(report)

    def test_registration_requires_seven_manifests_and_new_profile(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            report = build_report(root)
            manifests = [
                {"profile_id": f"old_{index}", "runtime_validated": False}
                for index in range(6)
            ]
            manifests.append({
                "profile_id": TOOL.PROFILE_ID,
                "target_relative_path": TOOL.TARGET_ARCHIVE,
                "baseline_sha256": TOOL.BASELINE_SHA256,
                "profile_sha256": TOOL.PROFILE_SHA256,
                "local_profile_path": TOOL.LOCAL_PROFILE_PATH,
                "changed_members": list(TOOL.EXPECTED_MEMBERS),
                "runtime_validated": False,
            })
            fake = SimpleNamespace(
                generate_manifests=lambda **kwargs: (root / "generated", None, manifests)
            )
            with mock.patch.object(TOOL, "load_generator", return_value=fake):
                generated, evidence, result = TOOL.register_profile(
                    root, report, create_report_archive=False
                )
            self.assertEqual(generated, root / "generated")
            self.assertIsNone(evidence)
            self.assertEqual(len(result), 7)

    def test_generic_generator_contains_new_profile_spec(self):
        generator_path = ROOT / "workstreams" / "quartet_restoration" / "generate_core_profile_manifests.py"
        spec = importlib.util.spec_from_file_location("generator_for_stage38_test", generator_path)
        assert spec and spec.loader
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        matches = [item for item in module.CURRENT_PROFILE_SPECS if item.profile_id == TOOL.PROFILE_ID]
        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0].profile_sha256, TOOL.PROFILE_SHA256)
        self.assertEqual(matches[0].changed_members, tuple(TOOL.EXPECTED_MEMBERS))


if __name__ == "__main__":
    unittest.main()
