from __future__ import annotations

import csv
import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
TOOL_PATH = ROOT / "workstreams/quartet_restoration/prepare_bathroom_river_core_target_request.py"
SPEC = importlib.util.spec_from_file_location("prepare_bathroom_river_core_target_request", TOOL_PATH)
assert SPEC and SPEC.loader
TOOL = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = TOOL
SPEC.loader.exec_module(TOOL)


def write_tsv(path: Path, fields: list[str], rows: list[dict[str, object]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def build_report(root: Path) -> Path:
    report = root / TOOL.REPORT_DIR
    report.mkdir(parents=True)
    summary = {
        "type": "br_quartet_restoration_bathroom_river_containing_pak_repack_test_evidence_summary",
        "format_version": 1,
        "tool_version": "0.0.81",
        "source_stage70_tool_version": "0.0.80",
        "status": "bathroom_river_containing_pak_local_repack_verified_not_registered_or_installed",
        "proposed_profile_rows": 1,
        "repacked_profile_rows": 1,
        "file_rows": 1,
        "validation_rows": 20,
        "validation_failures": 0,
        "manifest_difference_rows": 427,
        "stable_manifest_difference_rows": 0,
        "derived_manifest_difference_rows": 427,
        "skipped_rows": 0,
        "target_archive": TOOL.TARGET_ARCHIVE,
        "target_member_path": TOOL.TARGET_MEMBER,
        "input_archive_sha256": TOOL.BASELINE_SHA256,
        "output_archive_sha256": TOOL.PROFILE_SHA256,
        "input_archive_size": TOOL.BASELINE_SIZE,
        "output_archive_size": TOOL.PROFILE_SIZE,
        "unchanged_member_count_verified": 426,
        "candidate_parent_sha256": TOOL.PARENT_SHA256,
        "inventory_pristine_archive_sha256": TOOL.BASELINE_SHA256,
        "inventory_pristine_archive_match": True,
        "policy": {
            "installed_game_read_only": True,
            "installed_game_modified": False,
            "current_archive_used_as_repack_base": True,
            "unrelated_translation_or_other_member_changes_preserved": True,
            "all_unchanged_members_verified_by_reextraction_hash": True,
            "stable_manifest_fields_used_as_validation_gate": True,
            "derived_gust_manifest_keys_used_as_validation_gate": False,
            "local_rollback_baseline_copied": True,
            "candidate_pak_written_only_under_local_workspace": True,
            "proprietary_pak_exported_in_report": False,
            "candidate_parent_payload_exported_in_report": False,
            "core_registry_modified": False,
            "activation_or_rollback_invoked": False,
            "runtime_validation_inferred": False,
            "censorship_classification_inferred": False,
            "opaque_binary_field_semantics_inferred": False,
            "opl2_payload_modified": False,
            "translation_or_dlc_workstreams_modified": False,
            "canary_track_modified": False,
        },
    }
    (report / "SUMMARY.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    write_tsv(report / "BATHROOM_RIVER_CONTAINING_PAK_REPACK_PROFILES.tsv", [
        "profile_id", "source_profile_id", "classification", "target_archive", "target_member_path",
        "input_archive_sha256", "output_archive_sha256", "rollback_archive_sha256",
        "input_archive_size", "output_archive_size", "replaced_member_count",
        "unchanged_member_count_verified", "inventory_pristine_archive_match",
        "baseline_manifest_parse_mode", "verification_manifest_parse_mode", "local_output_archive",
        "local_rollback_archive", "validation_status", "runtime_validated", "review_status",
    ], [{
        "profile_id": TOOL.PROFILE_ID,
        "source_profile_id": TOOL.SOURCE_PROFILE_ID,
        "classification": "single_parent_elixir_member_containing_pak_repack_test",
        "target_archive": TOOL.TARGET_ARCHIVE,
        "target_member_path": TOOL.TARGET_MEMBER,
        "input_archive_sha256": TOOL.BASELINE_SHA256,
        "output_archive_sha256": TOOL.PROFILE_SHA256,
        "rollback_archive_sha256": TOOL.BASELINE_SHA256,
        "input_archive_size": TOOL.BASELINE_SIZE,
        "output_archive_size": TOOL.PROFILE_SIZE,
        "replaced_member_count": 1,
        "unchanged_member_count_verified": 426,
        "inventory_pristine_archive_match": True,
        "baseline_manifest_parse_mode": "gust_json_compatible:hex_numbers",
        "verification_manifest_parse_mode": "gust_json_compatible:hex_numbers",
        "local_output_archive": TOOL.LOCAL_PROFILE_PATH,
        "local_rollback_archive": ".local/build/quartet_restoration/repack_tests/bathroom_river_containing_pak/baseline/Data/PACK10_03.PAK",
        "validation_status": "passed",
        "runtime_validated": False,
        "review_status": "local_containing_pak_only_not_registered_not_installed",
    }])
    write_tsv(report / "BATHROOM_RIVER_CONTAINING_PAK_REPACK_FILES.tsv", [
        "profile_id", "normalized_path", "target_archive", "target_member_path",
        "target_member_sha256", "candidate_member_sha256", "repacked_member_sha256",
        "validation_status", "review_status",
    ], [{
        "profile_id": TOOL.PROFILE_ID,
        "normalized_path": "data/x64/field/s89_s_hinako_bath_room_01/s89_s_hinako_bath_room_01.elixir.gz",
        "target_archive": TOOL.TARGET_ARCHIVE,
        "target_member_path": TOOL.TARGET_MEMBER,
        "target_member_sha256": "6d9aaf32b7eebd9e927b1b4e6e5521b9696d75738ba55499f3c64fcee0d76af8",
        "candidate_member_sha256": TOOL.PARENT_SHA256,
        "repacked_member_sha256": TOOL.PARENT_SHA256,
        "validation_status": "passed",
        "review_status": "single_parent_elixir_member_repacked_all_other_pak_members_preserved",
    }])
    write_tsv(report / "BATHROOM_RIVER_CONTAINING_PAK_REPACK_VALIDATIONS.tsv", [
        "profile_id", "target_archive", "check_name", "passed", "details",
    ], [{
        "profile_id": TOOL.PROFILE_ID,
        "target_archive": TOOL.TARGET_ARCHIVE,
        "check_name": f"check_{index:02d}",
        "passed": True,
        "details": "",
    } for index in range(20)])
    differences = [{"classification": "derived_unchanged_member_metadata", "gate_effect": "diagnostic_only"} for _ in range(426)]
    differences.append({"classification": "derived_modified_member_metadata", "gate_effect": "diagnostic_only"})
    write_tsv(report / "BATHROOM_RIVER_CONTAINING_PAK_REPACK_MANIFEST_DIFFERENCES.tsv", ["classification", "gate_effect"], differences)
    write_tsv(report / "BATHROOM_RIVER_CONTAINING_PAK_REPACK_SKIPPED.tsv", ["profile_id", "target_archive", "target_member_path", "reason"], [])
    archive = root / TOOL.REPORT_NAME
    completed = subprocess.run(["tar", "--zstd", "-cf", str(archive), "-C", str(root), TOOL.REPORT_DIR], text=True, capture_output=True)
    if completed.returncode != 0:
        raise RuntimeError(completed.stderr)
    return archive


def write_core_sources(root: Path, *, supported: bool = False, partial: bool = False) -> None:
    base = root / "Blue_Reflection_Patcher/cmd/brpatcher"
    base.mkdir(parents=True)
    target = '\n\t"Data/PACK10_03.PAK": {RelativePath: "Data/PACK10_03.PAK"},\n' if (supported or partial) else ""
    scalar = "" if supported else " OtherState string\n"
    (base / "local_profile_registry.go").write_text(
        'type localProfileTargetSpec struct {\n' + scalar + '}\nvar x = map[string]localProfileTargetSpec{\n'
        '\t"Data/PACK11.PAK": {RelativePath: "Data/PACK11.PAK"},\n'
        '\t"Data/PACK10_01.PAK": {RelativePath: "Data/PACK10_01.PAK"},\n' + target + '}\n',
        encoding="utf-8",
    )
    commands = ""
    if supported:
        commands = "\n".join([
            'case "quartet-field-profile-activate":',
            'case "quartet-field-profile-status":',
            'case "quartet-field-profile-rollback":',
        ])
    (base / "main.go").write_text(commands, encoding="utf-8")
    transaction = ""
    if supported:
        transaction = 'for target := range localProfileTargets {\n if target != spec.RelativePath {}\n}\n'
    (base / "local_profile_transaction.go").write_text(transaction, encoding="utf-8")
    wrapper = root / "Blue_Reflection_Patcher/cmd/br_quartet_field_profile.sh"
    wrapper.parent.mkdir(parents=True, exist_ok=True)
    wrapper_text = "field profile wrapper\n"
    if supported:
        wrapper_text = "\n".join([
            "quartet-field-profile-activate",
            "quartet-field-profile-status",
            "quartet-field-profile-rollback",
        ]) + "\n"
    wrapper.write_text(wrapper_text, encoding="utf-8")


class BathroomRiverCoreTargetRequestTests(unittest.TestCase):
    def test_validates_actual_shape_of_stage71_report(self):
        with tempfile.TemporaryDirectory() as temporary:
            summary = TOOL.validate_stage71_report(build_report(Path(temporary)))
            self.assertEqual(summary["validation_rows"], 20)
            self.assertEqual(summary["unchanged_member_count_verified"], 426)

    def test_detects_current_unsupported_core(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            write_core_sources(root)
            result = TOOL.inspect_core_support(root)
            self.assertFalse(result["fully_supported"])
            self.assertTrue(result["current_other_state_is_scalar"])

    def test_detects_complete_three_target_core(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            write_core_sources(root, supported=True)
            result = TOOL.inspect_core_support(root)
            self.assertTrue(result["fully_supported"])
            self.assertTrue(result["generic_mutual_exclusion_present"])
            self.assertEqual(result["current_target_count"], 3)
            self.assertFalse(result["current_other_state_is_scalar"])

    def test_rejects_partial_core_interface(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            write_core_sources(root, partial=True)
            with self.assertRaisesRegex(TOOL.CoreTargetRequestError, "partial"):
                TOOL.inspect_core_support(root)

    def test_builds_request_without_modifying_registry(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            report_dir = root / ".local/reports/quartet_restoration"
            report_dir.mkdir(parents=True)
            source = build_report(root)
            source.replace(report_dir / TOOL.REPORT_NAME)
            write_core_sources(root)
            output, archive, request = TOOL.build_request(root, report_dir / TOOL.REPORT_NAME)
            self.assertTrue((output / "CORE_INTERFACE_REQUEST.json").is_file())
            self.assertTrue(archive and archive.is_file())
            self.assertEqual(request["restoration_registry_state"]["current_profiles"], 14)
            self.assertEqual(request["restoration_registry_state"]["expected_profiles_after_registration"], 15)
            self.assertFalse(request["policy"]["core_sources_modified"])


if __name__ == "__main__":
    unittest.main()
