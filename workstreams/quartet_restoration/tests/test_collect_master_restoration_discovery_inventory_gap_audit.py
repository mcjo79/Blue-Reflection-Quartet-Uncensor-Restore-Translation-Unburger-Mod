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
TOOL_PATH = WORKSTREAM / "121_collect_master_restoration_discovery_inventory_gap_audit.py"
SPEC = importlib.util.spec_from_file_location("stage121_tool", TOOL_PATH)
assert SPEC and SPEC.loader
TOOL = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = TOOL
SPEC.loader.exec_module(TOOL)


def read_tsv(path: Path):
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


class MasterRestorationDiscoveryInventoryGapAuditTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.tmp = tempfile.TemporaryDirectory(prefix="stage121-tests-")
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

    def test_summary_reports_current_static_discovery_state(self):
        self.assertEqual(self.summary["tool_version"], "0.1.39")
        self.assertEqual(self.summary["completed_report_summary_rows"], 110)
        self.assertEqual(self.summary["candidate_asset_family_rows"], 22)
        self.assertEqual(self.summary["candidate_asset_file_rows"], 44)
        self.assertEqual(self.summary["focused_scene_effect_path_rows"], 22)
        self.assertEqual(self.summary["historical_event_candidate_path_rows"], 38)
        self.assertEqual(self.summary["reflector_render_member_family_rows"], 167)

    def test_cross_namespace_ledger_has_exact_bounded_counts(self):
        rows = read_tsv(self.report / "MASTER_DISCOVERY_IDENTITY_LEDGER.tsv")
        self.assertEqual(len(rows), 249)
        self.assertEqual(
            Counter(row["identity_namespace"] for row in rows),
            Counter({
                "coverage_asset_family": 22,
                "scene_effect_path": 22,
                "event_candidate_path": 38,
                "reflector_render_member_family": 167,
            }),
        )
        self.assertTrue(all(row["identity"] for row in rows))

    def test_ledger_count_is_not_claimed_as_independent_game_changes(self):
        self.assertFalse(self.summary["cross_namespace_candidate_rows_are_additive_game_changes"])
        self.assertFalse(self.summary["policy"]["single_total_of_game_censorship_changes_claimed"])
        rows = read_tsv(self.report / "MASTER_DISCOVERY_COUNT_INTERPRETATION.tsv")
        self.assertEqual(len(rows), 5)
        self.assertTrue(all(row["may_be_read_as_independent_game_changes"] == "False" for row in rows))

    def test_profiles_are_separate_implementation_units(self):
        rows = read_tsv(self.report / "MASTER_DISCOVERY_PROFILE_LEDGER.tsv")
        self.assertEqual(len(rows), 15)
        self.assertEqual(sum(int(row["changed_member_count"]) for row in rows), 30)
        self.assertTrue(all(row["runtime_validated"] == "False" for row in rows))
        self.assertTrue(all(row["production_eligible"] == "False" for row in rows))
        self.assertTrue(all(row["discovery_meaning"] == "implementation_unit_not_independent_game_change_count" for row in rows))

    def test_domain_summary_keeps_runtime_confirmation_at_zero(self):
        rows = read_tsv(self.report / "MASTER_DISCOVERY_DOMAIN_SUMMARY.tsv")
        self.assertEqual(len(rows), 9)
        self.assertTrue(all(row["runtime_confirmed_rows"] == "0" for row in rows))
        by_domain = {row["domain"]: row for row in rows}
        self.assertEqual(by_domain["costume_and_coverage_assets"]["primary_identity_rows"], "22")
        self.assertEqual(by_domain["restoration_profiles_and_composition"]["profile_ready_rows"], "15")

    def test_gap_register_prioritizes_save_independent_discovery(self):
        rows = read_tsv(self.report / "MASTER_DISCOVERY_GAP_REGISTER.tsv")
        self.assertEqual(len(rows), 9)
        by_id = {row["gap_id"]: row for row in rows}
        self.assertEqual(by_id["global_discovery_saturation"]["priority"], "critical")
        self.assertEqual(by_id["runtime_validation_without_saves"]["priority"], "deferred")
        self.assertEqual(by_id["runtime_validation_without_saves"]["runtime_or_save_required"], "True")
        self.assertTrue(all(row["write_authorized"] == "False" for row in rows))

    def test_material_and_structural_counts_are_preserved_without_semantic_claims(self):
        self.assertEqual(self.summary["structural_earc_archive_rows"], 92)
        self.assertEqual(self.summary["scene_effect_member_difference_rows"], 586)
        self.assertEqual(self.summary["variant_member_rows"], 452)
        self.assertEqual(self.summary["material_member_group_rows"], 357)
        self.assertEqual(self.summary["focused_material_evidence_rows"], 1508)
        self.assertEqual(self.summary["direct_numeric_material_restore_candidate_rows"], 0)

    def test_slot_light_branch_state_is_preserved(self):
        self.assertEqual(self.summary["resolved_noncanary_slot_light_pair_rows"], 5)
        self.assertEqual(self.summary["frozen_unresolved_swordflash_pair_rows"], 2)

    def test_stage120_does_not_authorize_real_composition(self):
        self.assertFalse(self.summary["individual_save_based_runtime_testing_is_current_priority"])
        self.assertEqual(self.summary["runtime_validated_profile_rows"], 0)
        self.assertEqual(self.summary["runtime_confirmed_discovery_rows"], 0)
        self.assertFalse(self.summary["discovery_exhaustive"])

    def test_report_catalog_is_complete_and_hashes_are_valid(self):
        rows = read_tsv(self.report / "MASTER_DISCOVERY_REPORT_CATALOG.tsv")
        self.assertEqual(len(rows), 110)
        self.assertEqual(len({row["report_id"] for row in rows}), 110)
        self.assertTrue(all(len(row["summary_sha256"]) == 64 for row in rows))

    def test_evidence_archive_contains_metadata_only(self):
        self.assertTrue(self.archive.is_file())
        forbidden = {".pak", ".g1e", ".g1em", ".g1m", ".g1s", ".elixir", ".ebd", ".ebm"}
        self.assertFalse(any(path.suffix.casefold() in forbidden for path in self.report.rglob("*") if path.is_file()))
        policy = self.summary["policy"]
        self.assertTrue(policy["existing_evidence_only"])
        self.assertFalse(policy["proprietary_payload_rehydrated"])
        self.assertFalse(policy["pak_built_or_repacked"])
        self.assertFalse(policy["installed_game_modified"])
        self.assertFalse(policy["git_modified"])

    def test_unsafe_archive_paths_are_rejected(self):
        for value in ("../escape", "/absolute", "a/../../b"):
            with self.assertRaises(TOOL.AuditError):
                TOOL.safe_relative(value, "test path")


if __name__ == "__main__":
    unittest.main()
