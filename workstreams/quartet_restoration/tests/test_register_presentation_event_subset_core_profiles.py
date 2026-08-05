from __future__ import annotations

import csv
import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

ROOT = Path(__file__).resolve().parents[3]
TOOL_PATH = ROOT / "workstreams" / "quartet_restoration" / "register_presentation_event_subset_core_profiles.py"
SPEC = importlib.util.spec_from_file_location("register_presentation_event_subset_core_profiles", TOOL_PATH)
assert SPEC and SPEC.loader
TOOL = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = TOOL
SPEC.loader.exec_module(TOOL)


def write_tsv(path: Path, fieldnames: list[str], rows: list[dict[str, object]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def build_report(root: Path, *, failed_validation: bool = False, stable_difference: bool = False) -> Path:
    report_root = root / TOOL.REPORT_DIR
    report_root.mkdir(parents=True)
    summary = {
        "tool_version": "0.0.53",
        "status": "six_separate_checksum_gated_local_presentation_event_subset_pack11_profiles_built_reextracted_and_validated_not_installed",
        "profile_rows": 6,
        "file_rows": 6,
        "validation_rows": 102,
        "validation_failures": 1 if failed_validation else 0,
        "stable_manifest_difference_rows": 1 if stable_difference else 0,
        "derived_manifest_difference_rows": 56382,
        "skipped_rows": 0,
        "input_archive_sha256": TOOL.BASELINE_SHA256,
        "input_archive_size": TOOL.BASELINE_SIZE,
        "inventory_pristine_archive_match": True,
        "policy": {
            "installed_game_read_only": True,
            "installed_game_modified": False,
            "current_pack11_used_as_repack_base": True,
            "candidate_members_replaced_per_profile": 1,
            "profile_archives_kept_separate": True,
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
    write_tsv(report_root / "PRESENTATION_EVENT_SUBSET_REPACK_BUILD_SKIPPED.tsv", ["profile_id", "target_member_path", "reason"], [])

    profile_rows = []
    file_rows = []
    validation_rows = []
    difference_rows = []
    for profile_index, expected in enumerate(TOOL.EXPECTED_PROFILES):
        profile_rows.append({
            "profile_id": expected.profile_id,
            "profile_classification": "experimental_bounded_subset_static_candidate",
            "prototype_confidence": "experimental_metadata_gated",
            "source_stage45_profile_id": expected.profile_id,
            "input_archive_relative_path": TOOL.TARGET_ARCHIVE,
            "input_archive_sha256": TOOL.BASELINE_SHA256,
            "input_archive_size": TOOL.BASELINE_SIZE,
            "inventory_pristine_archive_match": True,
            "output_archive_sha256": expected.profile_sha256,
            "output_archive_size": expected.profile_size,
            "replaced_member_count": 1,
            "unchanged_member_count_verified": 9396,
            "local_output_archive": expected.local_profile_path,
            "validation_status": "passed",
            "activation_status": "not_generated_generic_core_manifest_required",
        })
        file_rows.append({
            "profile_id": expected.profile_id,
            "target_archive": TOOL.TARGET_ARCHIVE,
            "target_member_path": expected.changed_member,
            "candidate_sha256": expected.changed_member_sha256,
            "repacked_member_sha256": expected.changed_member_sha256,
            "validation_status": "passed",
        })
        for check_index in range(17):
            validation_rows.append({
                "profile_id": expected.profile_id,
                "check_name": f"check_{check_index:02d}",
                "passed": "False" if failed_validation and profile_index == 0 and check_index == 0 else "True",
                "details": "",
            })
        for _ in range(9396):
            difference_rows.append({
                "profile_id": expected.profile_id,
                "classification": "derived_unchanged_member_metadata",
                "gate_effect": "diagnostic_only",
            })
        difference_rows.append({
            "profile_id": expected.profile_id,
            "classification": "stable_unexpected_difference" if stable_difference and profile_index == 0 else "derived_modified_member_metadata",
            "gate_effect": "blocking" if stable_difference and profile_index == 0 else "diagnostic_only",
        })

    write_tsv(
        report_root / "PRESENTATION_EVENT_SUBSET_REPACK_PROFILES.tsv",
        list(profile_rows[0].keys()),
        profile_rows,
    )
    write_tsv(
        report_root / "PRESENTATION_EVENT_SUBSET_REPACK_FILES.tsv",
        list(file_rows[0].keys()),
        file_rows,
    )
    write_tsv(
        report_root / "PRESENTATION_EVENT_SUBSET_REPACK_VALIDATION.tsv",
        list(validation_rows[0].keys()),
        validation_rows,
    )
    write_tsv(
        report_root / "PRESENTATION_EVENT_SUBSET_REPACK_MANIFEST_DIFFERENCES.tsv",
        list(difference_rows[0].keys()),
        difference_rows,
    )
    archive = root / TOOL.REPORT_NAME
    completed = subprocess.run(
        ["tar", "--zstd", "-cf", str(archive), "-C", str(root), TOOL.REPORT_DIR],
        text=True,
        capture_output=True,
    )
    if completed.returncode != 0:
        raise RuntimeError(completed.stderr)
    return archive


class PresentationEventSubsetRegistrationTests(unittest.TestCase):
    def test_validates_complete_stage46_report(self):
        with tempfile.TemporaryDirectory() as temporary:
            summary = TOOL.validate_stage46_report(build_report(Path(temporary)))
            self.assertEqual(summary["profile_rows"], 6)
            self.assertEqual(summary["validation_failures"], 0)

    def test_rejects_failed_stage46_gate(self):
        with tempfile.TemporaryDirectory() as temporary:
            with self.assertRaisesRegex(TOOL.RegistrationError, "validation failures"):
                TOOL.validate_stage46_report(build_report(Path(temporary), failed_validation=True))

    def test_rejects_stable_manifest_difference(self):
        with tempfile.TemporaryDirectory() as temporary:
            with self.assertRaisesRegex(TOOL.RegistrationError, "stable manifest differences"):
                TOOL.validate_stage46_report(build_report(Path(temporary), stable_difference=True))

    def test_registration_requires_thirteen_manifests_and_all_six_new_profiles(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            report = build_report(root)
            manifests = [{"profile_id": f"old_{index}", "runtime_validated": False} for index in range(7)]
            for expected in TOOL.EXPECTED_PROFILES:
                manifests.append({
                    "profile_id": expected.profile_id,
                    "target_relative_path": TOOL.TARGET_ARCHIVE,
                    "baseline_sha256": TOOL.BASELINE_SHA256,
                    "profile_sha256": expected.profile_sha256,
                    "profile_size": expected.profile_size,
                    "local_profile_path": expected.local_profile_path,
                    "changed_members": [expected.changed_member],
                    "runtime_validated": False,
                })
            fake = SimpleNamespace(generate_manifests=lambda **kwargs: (root / "generated", None, manifests))
            with mock.patch.object(TOOL, "load_generator", return_value=fake):
                generated, evidence, result = TOOL.register_profiles(root, report, create_report_archive=False)
            self.assertEqual(generated, root / "generated")
            self.assertIsNone(evidence)
            self.assertEqual(len(result), 13)

    def test_generic_generator_contains_all_six_new_profile_specs(self):
        generator_path = ROOT / "workstreams" / "quartet_restoration" / "generate_core_profile_manifests.py"
        spec = importlib.util.spec_from_file_location("generator_for_stage47_test", generator_path)
        assert spec and spec.loader
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        actual = {item.profile_id: item for item in module.CURRENT_PROFILE_SPECS}
        self.assertGreaterEqual(len(actual), 13)
        for expected in TOOL.EXPECTED_PROFILES:
            self.assertIn(expected.profile_id, actual)
            item = actual[expected.profile_id]
            self.assertEqual(item.profile_sha256, expected.profile_sha256)
            self.assertEqual(item.profile_size, expected.profile_size)
            self.assertEqual(item.local_profile_path, expected.local_profile_path)
            self.assertEqual(item.changed_members, (expected.changed_member,))


if __name__ == "__main__":
    unittest.main()
