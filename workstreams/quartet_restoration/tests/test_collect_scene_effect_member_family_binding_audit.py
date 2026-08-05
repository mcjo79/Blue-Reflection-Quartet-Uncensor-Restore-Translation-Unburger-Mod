from __future__ import annotations

import csv
import importlib.util
import json
import sys
import tempfile
import unittest
from collections import Counter
from pathlib import Path

WORKSTREAM = Path(__file__).resolve().parents[1]
PROJECT = WORKSTREAM.parent.parent
TOOL_PATH = WORKSTREAM / "122_collect_scene_effect_member_family_binding_audit.py"
SPEC = importlib.util.spec_from_file_location("stage122_tool", TOOL_PATH)
assert SPEC and SPEC.loader
TOOL = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = TOOL
SPEC.loader.exec_module(TOOL)


def read_tsv(path: Path):
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


class SceneEffectMemberFamilyBindingAuditTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.tmp = tempfile.TemporaryDirectory(prefix="stage122-tests-")
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

    def test_summary_has_exact_bounded_counts(self):
        self.assertEqual(self.summary["tool_version"], "0.1.40")
        self.assertEqual(self.summary["focused_scene_effect_path_rows"], 22)
        self.assertEqual(self.summary["scene_effect_member_difference_rows"], 586)
        self.assertEqual(self.summary["exact_binary_delta_family_rows"], 579)
        self.assertEqual(self.summary["deduplicated_occurrence_reduction_rows"], 7)

    def test_stage121_prerequisite_is_exactly_preserved(self):
        self.assertEqual(
            self.summary["stage121_summary_sha256"],
            "b074a9334a5f76e364e2df0a5e467c294bdd4ac636e7e5765eb4be03079e0654",
        )
        self.assertEqual(
            self.summary["stage121_report_sha256"],
            "a1f9e87ee273af0fece9b6722bc0e9b58fd6d818cefbdbf9113d75fef4216219",
        )

    def test_every_occurrence_maps_to_one_exact_delta_family(self):
        occurrences = read_tsv(self.report / "SCENE_EFFECT_MEMBER_OCCURRENCES.tsv")
        families = read_tsv(self.report / "SCENE_EFFECT_MEMBER_DELTA_FAMILIES.tsv")
        family_ids = {row["delta_family_id"] for row in families}
        self.assertEqual(len(occurrences), 586)
        self.assertEqual(len(families), 579)
        self.assertTrue(all(row["delta_family_id"] in family_ids for row in occurrences))
        self.assertEqual(sum(int(row["occurrence_rows"]) for row in families), 586)

    def test_exact_delta_frequency_is_573_5_1(self):
        rows = read_tsv(self.report / "SCENE_EFFECT_DELTA_FAMILY_FREQUENCY.tsv")
        by_count = {int(row["occurrences_per_exact_delta_family"]): int(row["exact_delta_family_rows"]) for row in rows}
        self.assertEqual(by_count, {1: 573, 2: 5, 3: 1})
        self.assertEqual(self.summary["repeated_exact_binary_delta_family_rows"], 6)
        self.assertEqual(self.summary["repeated_exact_binary_delta_occurrence_rows"], 13)

    def test_all_focused_paths_are_bound_and_five_are_non_earc(self):
        rows = read_tsv(self.report / "SCENE_EFFECT_PATH_BINDING_SUMMARY.tsv")
        self.assertEqual(len(rows), 22)
        with_members = [row for row in rows if int(row["member_difference_rows"]) > 0]
        without_members = [row for row in rows if int(row["member_difference_rows"]) == 0]
        self.assertEqual(len(with_members), 17)
        self.assertEqual(len(without_members), 5)
        self.assertEqual({row["focused_path"] for row in without_members}, TOOL.EXPECTED_NO_MEMBER_PATHS)
        self.assertTrue(all(row["static_disposition"] == "focused_non_earc_path_requires_format_specific_static_audit" for row in without_members))

    def test_exact_coverage_binding_finds_only_three_wet_reflector_assets(self):
        rows = read_tsv(self.report / "COVERAGE_ASSET_SCENE_EFFECT_BINDINGS.tsv")
        bound = [row for row in rows if int(row["exact_focused_path_binding_rows"]) > 0]
        unbound = [row for row in rows if int(row["exact_focused_path_binding_rows"]) == 0]
        self.assertEqual({row["token"] for row in bound}, {"pc00_rfl_w", "pc01_rfl_w", "pc02_rfl_w"})
        self.assertEqual(len(bound), 3)
        self.assertEqual(len(unbound), 19)
        self.assertEqual(sum(int(row["bound_member_difference_rows"]) for row in bound), 22)

    def test_exact_coverage_binding_does_not_claim_scene_use_or_semantics(self):
        rows = read_tsv(self.report / "COVERAGE_ASSET_SCENE_EFFECT_BINDINGS.tsv")
        self.assertTrue(all(row["runtime_confirmed"] == "False" for row in rows))
        self.assertTrue(all(row["semantic_binding_confirmed"] == "False" for row in rows))
        self.assertFalse(self.summary["coverage_scene_use_binding_complete"])
        self.assertFalse(self.summary["semantic_scene_effect_partition_authoritative"])

    def test_extension_partition_is_exact_and_nonsemantic(self):
        rows = read_tsv(self.report / "SCENE_EFFECT_MEMBER_EXTENSION_SUMMARY.tsv")
        self.assertEqual(len(rows), 9)
        occurrence_split = Counter({row["member_extension"]: int(row["occurrence_rows"]) for row in rows})
        family_split = Counter({row["member_extension"]: int(row["exact_delta_family_rows"]) for row in rows})
        self.assertEqual(occurrence_split, TOOL.EXPECTED_OCCURRENCE_EXTENSION_SPLIT)
        self.assertEqual(family_split, TOOL.EXPECTED_FAMILY_EXTENSION_SPLIT)
        self.assertTrue(all(row["semantic_meaning_assigned"] == "False" for row in rows))

    def test_family_identity_is_strict_binary_equality_only(self):
        rows = read_tsv(self.report / "SCENE_EFFECT_MEMBER_DELTA_FAMILIES.tsv")
        self.assertTrue(all(row["deduplication_basis"] == "exact_classification_size_and_source_target_sha256" for row in rows))
        self.assertTrue(all(row["visual_semantics_confirmed"] == "False" for row in rows))
        self.assertTrue(self.summary["policy"]["exact_binary_delta_identity_only"])
        self.assertFalse(self.summary["policy"]["numeric_similarity_used"])

    def test_input_hashes_are_fixed_and_verified(self):
        rows = read_tsv(self.report / "INPUT_HASHES.tsv")
        self.assertEqual(len(rows), 3)
        self.assertTrue(all(row["sha256"] == row["expected_sha256"] for row in rows))
        self.assertTrue(all(row["verified"] == "True" for row in rows))

    def test_gap_register_keeps_static_discovery_first(self):
        rows = read_tsv(self.report / "SCENE_EFFECT_MEMBER_FAMILY_GAPS.tsv")
        self.assertEqual(len(rows), 5)
        by_id = {row["gap_id"]: row for row in rows}
        self.assertEqual(by_id["coverage_asset_exact_binding"]["affected_rows"], "19")
        self.assertEqual(by_id["focused_non_earc_paths"]["affected_rows"], "5")
        self.assertTrue(all(row["runtime_or_save_required"] == "False" for row in rows))
        self.assertTrue(all(row["write_authorized"] == "False" for row in rows))

    def test_evidence_archive_is_metadata_only_and_no_write(self):
        self.assertTrue(self.archive.is_file())
        forbidden = {".pak", ".g1e", ".g1em", ".g1m", ".g1s", ".g1t", ".elixir", ".ebd", ".ebm"}
        self.assertFalse(any(path.suffix.casefold() in forbidden for path in self.report.rglob("*") if path.is_file()))
        policy = self.summary["policy"]
        self.assertTrue(policy["existing_evidence_only"])
        for key in (
            "proprietary_payload_rehydrated", "pak_built_or_repacked", "profile_or_registry_modified",
            "core_modified", "translation_modified", "legacy_dlc_modified", "installed_game_modified", "git_modified",
        ):
            self.assertFalse(policy[key])
        self.assertEqual(self.summary["write_authorized_rows"], 0)
        self.assertEqual(self.summary["runtime_confirmed_rows"], 0)

    def test_unsafe_relative_paths_are_rejected(self):
        for value in ("../escape", "/absolute", "a/../../b"):
            with self.assertRaises(TOOL.AuditError):
                TOOL.safe_relative(value, "test path")


if __name__ == "__main__":
    unittest.main()
