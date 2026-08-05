from __future__ import annotations

import csv
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

WORKSTREAM = Path(__file__).resolve().parents[1]
PROJECT = WORKSTREAM.parent.parent
TOOL_PATH = WORKSTREAM / "123_collect_character_asset_namespace_saturation_audit.py"
SPEC = importlib.util.spec_from_file_location("stage123_tool", TOOL_PATH)
assert SPEC and SPEC.loader
TOOL = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = TOOL
SPEC.loader.exec_module(TOOL)


def read_tsv(path: Path):
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


class CharacterAssetNamespaceSaturationAuditTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.tmp = tempfile.TemporaryDirectory(prefix="stage123-tests-")
        cls.root = Path(cls.tmp.name)
        cls.archive, cls.summary = TOOL.build_report(
            PROJECT,
            report_root=PROJECT / ".local/reports/quartet_restoration",
            output_report_root=cls.root / "reports",
            create_archive=True,
        )
        cls.report = cls.root / "reports" / TOOL.REPORT_DIR

    @classmethod
    def tearDownClass(cls) -> None:
        cls.tmp.cleanup()

    def test_summary_has_full_character_namespace_counts(self):
        self.assertEqual(self.summary["tool_version"], "0.1.41")
        self.assertEqual(self.summary["character_asset_file_rows"], 3525)
        self.assertEqual(self.summary["character_logical_family_rows"], 3056)
        self.assertEqual(
            self.summary["classification_file_rows"],
            {"changed": 327, "identical": 2906, "new_in_target": 48, "removed_in_target": 244},
        )
        self.assertEqual(
            self.summary["classification_logical_family_rows"],
            {"changed": 165, "identical": 2743, "new_in_target": 26, "removed_in_target": 122},
        )

    def test_stage122_prerequisite_is_exactly_preserved(self):
        self.assertEqual(self.summary["stage122_report_sha256"], TOOL.EXPECTED_STAGE122_ARCHIVE_SHA256)
        self.assertEqual(self.summary["stage122_summary_sha256"], TOOL.EXPECTED_STAGE122_SUMMARY_SHA256)

    def test_target_only_namespace_is_fully_accounted(self):
        self.assertEqual(self.summary["target_only_character_asset_file_rows"], 48)
        self.assertEqual(self.summary["target_only_character_logical_family_rows"], 26)
        self.assertEqual(self.summary["previously_known_target_only_candidate_family_rows"], 22)
        self.assertEqual(self.summary["previously_known_target_only_candidate_file_rows"], 44)
        self.assertEqual(self.summary["unclassified_target_only_character_file_rows"], 0)
        self.assertTrue(self.summary["target_only_character_namespace_saturation_achieved"])

    def test_four_new_face_rig_paths_are_the_only_inventory_expansion(self):
        rows = read_tsv(self.report / "TARGET_ONLY_CHARACTER_FAMILY_COVERAGE.tsv")
        rigs = [row for row in rows if row["static_disposition"] == "new_target_only_face_rig_support_asset"]
        self.assertEqual(len(rigs), 4)
        self.assertEqual(
            {row["logical_path"] for row in rigs},
            {
                "data/x64/character/pc00/face/pc00_rfl_face_rig",
                "data/x64/character/pc00/face/pc00_scl_face_rig",
                "data/x64/character/pc00/face/pc00_scl_w_face_rig",
                "data/x64/character/pc00_scl/face/pc00_scl_face_rig",
            },
        )
        self.assertEqual(self.summary["new_target_only_face_rig_file_rows"], 4)
        self.assertEqual(self.summary["new_target_only_face_rig_unique_payload_rows"], 3)

    def test_known_twenty_two_candidate_families_cover_exactly_44_files(self):
        rows = read_tsv(self.report / "TARGET_ONLY_CHARACTER_ASSETS.tsv")
        known = [row for row in rows if row["known_candidate_id"]]
        unknown = [row for row in rows if not row["known_candidate_id"]]
        self.assertEqual(len(known), 44)
        self.assertEqual(len(unknown), 4)
        self.assertEqual(len({row["known_candidate_id"] for row in known}), 22)

    def test_universal_changed_state_matrix_is_8_by_15(self):
        rows = read_tsv(self.report / "PLAYER_CHARACTER_STATE_MATRIX.tsv")
        universal = [row for row in rows if row["universal_across_pc00_pc14"] == "True"]
        self.assertEqual({row["state_token"] for row in universal}, TOOL.UNIVERSAL_CHANGED_STATE_TOKENS)
        self.assertEqual(len(universal), 8)
        self.assertTrue(all(int(row["changed_logical_family_rows"]) == 15 for row in universal))
        self.assertTrue(all(int(row["changed_asset_file_rows"]) == 30 for row in universal))
        self.assertTrue(all(int(row["character_id_rows"]) == 15 for row in universal))
        self.assertEqual(sum(int(row["changed_logical_family_rows"]) for row in universal), 120)
        self.assertEqual(sum(int(row["changed_asset_file_rows"]) for row in universal), 240)

    def test_selective_player_state_queue_is_preserved_without_semantics(self):
        rows = read_tsv(self.report / "PLAYER_CHARACTER_STATE_MATRIX.tsv")
        selective = [row for row in rows if row["universal_across_pc00_pc14"] == "False"]
        self.assertEqual(len(selective), 8)
        self.assertEqual(sum(int(row["changed_logical_family_rows"]) for row in selective), 17)
        self.assertEqual(sum(int(row["changed_asset_file_rows"]) for row in selective), 31)
        self.assertTrue(all(row["runtime_confirmed"] == "False" for row in rows))
        self.assertTrue(all(row["visual_semantics_confirmed"] == "False" for row in rows))

    def test_changed_namespace_split_is_exact(self):
        rows = read_tsv(self.report / "CHARACTER_NAMESPACE_CLASSIFICATION.tsv")
        changed = {row["namespace"]: row for row in rows if row["classification"] == "changed"}
        self.assertEqual((int(changed["player_character"]["asset_file_rows"]), int(changed["player_character"]["logical_family_rows"])), (271, 137))
        self.assertEqual((int(changed["npc"]["asset_file_rows"]), int(changed["npc"]["logical_family_rows"])), (50, 25))
        self.assertEqual((int(changed["mob"]["asset_file_rows"]), int(changed["mob"]["logical_family_rows"])), (6, 3))

    def test_removed_character_assets_are_all_legacy_dlc_boundary_rows(self):
        rows = read_tsv(self.report / "CHARACTER_LOGICAL_ASSET_FAMILIES.tsv")
        removed = [row for row in rows if row["classification"] == "removed_in_target"]
        self.assertEqual(len(removed), 122)
        self.assertEqual(sum(int(row["asset_file_rows"]) for row in removed), 244)
        self.assertTrue(all(row["static_disposition"] == "legacy_dlc_boundary_not_restoration" for row in removed))
        self.assertEqual(self.summary["removed_legacy_dlc_character_logical_family_rows"], 122)
        self.assertEqual(self.summary["removed_legacy_dlc_character_file_rows"], 244)

    def test_input_hashes_are_fixed_and_verified(self):
        rows = read_tsv(self.report / "INPUT_HASHES.tsv")
        self.assertEqual(len(rows), 2)
        self.assertTrue(all(row["sha256"] == row["expected_sha256"] for row in rows))
        self.assertTrue(all(row["verified"] == "True" for row in rows))

    def test_gap_register_keeps_static_discovery_first(self):
        rows = read_tsv(self.report / "CHARACTER_DISCOVERY_GAPS.tsv")
        self.assertEqual(len(rows), 5)
        by_id = {row["gap_id"]: row for row in rows}
        self.assertEqual(by_id["universal_player_state_member_semantics"]["affected_logical_family_rows"], "120")
        self.assertEqual(by_id["target_only_face_rig_support_assets"]["affected_asset_file_rows"], "4")
        self.assertEqual(by_id["coverage_selector_binding"]["affected_logical_family_rows"], "19")
        self.assertTrue(all(row["runtime_or_save_required"] == "False" for row in rows))
        self.assertTrue(all(row["write_authorized"] == "False" for row in rows))

    def test_evidence_archive_is_metadata_only_and_no_write(self):
        self.assertTrue(self.archive.is_file())
        forbidden = {".pak", ".g1e", ".g1em", ".g1m", ".g1s", ".g1t", ".elixir", ".ebd", ".ebm"}
        self.assertFalse(any(path.suffix.casefold() in forbidden for path in self.report.rglob("*") if path.is_file()))
        policy = self.summary["policy"]
        self.assertTrue(policy["existing_evidence_only"])
        self.assertTrue(policy["path_and_hash_metadata_only"])
        for key in (
            "proprietary_payload_rehydrated", "visual_or_censorship_semantics_assigned", "runtime_validation_inferred",
            "pak_built_or_repacked", "profile_or_registry_modified", "core_modified", "translation_modified",
            "legacy_dlc_modified", "installed_game_modified", "git_modified",
        ):
            self.assertFalse(policy[key])
        self.assertEqual(self.summary["runtime_confirmed_rows"], 0)
        self.assertEqual(self.summary["write_authorized_rows"], 0)

    def test_character_namespace_saturation_does_not_claim_global_saturation(self):
        self.assertTrue(self.summary["target_only_character_namespace_saturation_achieved"])
        self.assertFalse(self.summary["global_discovery_saturation_achieved"])
        self.assertFalse(self.summary["coverage_selector_binding_complete"])
        self.assertFalse(self.summary["universal_player_state_member_semantics_resolved"])

    def test_unsafe_relative_paths_are_rejected(self):
        for value in ("../escape", "/absolute", "a/../../b"):
            with self.assertRaises(TOOL.AuditError):
                TOOL.safe_relative(value, "test path")


if __name__ == "__main__":
    unittest.main()
