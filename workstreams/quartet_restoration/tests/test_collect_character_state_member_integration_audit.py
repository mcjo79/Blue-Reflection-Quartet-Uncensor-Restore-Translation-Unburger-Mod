from __future__ import annotations

import csv
import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path

WORKSTREAM = Path(__file__).resolve().parents[1]
PROJECT = WORKSTREAM.parent.parent
TOOL_PATH = WORKSTREAM / "124_collect_character_state_member_integration_audit.py"
SPEC = importlib.util.spec_from_file_location("stage124_tool", TOOL_PATH)
assert SPEC and SPEC.loader
TOOL = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = TOOL
SPEC.loader.exec_module(TOOL)


def read_tsv(path: Path):
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


class CharacterStateMemberIntegrationAuditTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.tmp = tempfile.TemporaryDirectory(prefix="stage124-tests-")
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

    def test_stage123_prerequisite_is_exact(self):
        self.assertEqual(self.summary["stage123_report_sha256"], TOOL.STAGE123[2])
        self.assertEqual(self.summary["stage123_summary_sha256"], TOOL.STAGE123[3])

    def test_universal_matrix_is_preserved(self):
        self.assertEqual(self.summary["universal_state_token_rows"], 8)
        self.assertEqual(self.summary["universal_character_rows"], 15)
        self.assertEqual(self.summary["universal_logical_family_rows"], 120)
        self.assertEqual(self.summary["universal_asset_file_rows"], 240)

    def test_existing_member_coverage_is_exactly_39_of_120(self):
        self.assertEqual(self.summary["existing_member_coverage_family_rows"], 39)
        self.assertEqual(self.summary["missing_existing_member_coverage_family_rows"], 81)
        self.assertEqual(self.summary["existing_member_coverage_percent"], 32.5)
        self.assertFalse(self.summary["universal_member_integration_complete"])

    def test_token_coverage_is_only_nkd_tng_udw(self):
        rows = read_tsv(self.report / "UNIVERSAL_STATE_TOKEN_COVERAGE.tsv")
        by_token = {row["state_token"]: row for row in rows}
        self.assertEqual({token for token, row in by_token.items() if int(row["covered_family_rows"])}, {"nkd", "tng", "udw"})
        for token in ("nkd", "tng", "udw"):
            self.assertEqual(int(by_token[token]["covered_family_rows"]), 13)
            self.assertEqual(int(by_token[token]["uncovered_family_rows"]), 2)
        for token in ("nkd_w", "scl", "scl_w", "swm", "swm_w"):
            self.assertEqual(int(by_token[token]["covered_family_rows"]), 0)
            self.assertEqual(int(by_token[token]["uncovered_family_rows"]), 15)

    def test_pc08_and_pc12_have_no_existing_coverage(self):
        rows = read_tsv(self.report / "UNIVERSAL_STATE_CHARACTER_COVERAGE.tsv")
        by_pc = {row["character_id"]: row for row in rows}
        self.assertEqual(int(by_pc["pc08"]["covered_family_rows"]), 0)
        self.assertEqual(int(by_pc["pc12"]["covered_family_rows"]), 0)
        for pc, row in by_pc.items():
            if pc not in {"pc08", "pc12"}:
                self.assertEqual(int(row["covered_family_rows"]), 3)
                self.assertEqual(row["covered_state_tokens"], "nkd;tng;udw")

    def test_existing_earc_and_material_counts_are_fixed(self):
        self.assertEqual(self.summary["earc_context_rows"], 45)
        self.assertEqual(self.summary["earc_declared_member_rows"], 351)
        self.assertEqual(self.summary["material_member_group_rows"], 171)
        self.assertEqual(self.summary["material_member_identity_rows"], 149)
        self.assertEqual(self.summary["g1m_chunk_rows"], 824)
        self.assertEqual(self.summary["g1m_parameter_rows"], 4242)
        self.assertEqual(self.summary["g1m_parameter_member_identity_rows"], 146)

    def test_variant_member_ledger_is_metadata_only(self):
        self.assertEqual(self.summary["variant_member_comparison_rows"], 427)
        self.assertEqual(self.summary["variant_member_identity_rows"], 339)
        self.assertEqual(
            self.summary["variant_member_classification_counts"],
            {"candidate_only_member": 76, "changed_payload": 246, "counterpart_only_member": 31, "identical_payload": 74},
        )
        rows = read_tsv(self.report / "UNIVERSAL_STATE_MEMBER_IDENTITIES.tsv")
        self.assertEqual(len(rows), 339)
        self.assertTrue(all(row["semantics_confirmed"] == "False" for row in rows))
        self.assertTrue(all(row["write_authorized"] == "False" for row in rows))

    def test_material_deltas_are_not_direct_restore_candidates(self):
        self.assertEqual(self.summary["semantic_material_rows"], 3534)
        self.assertEqual(self.summary["base_to_base_semantic_material_rows"], 943)
        self.assertEqual(self.summary["quartet_base_to_variant_semantic_rows"], 2591)
        self.assertEqual(self.summary["high_value_parameter_rows"], 254)
        self.assertEqual(self.summary["base_high_value_parameter_rows"], 18)
        self.assertEqual(self.summary["base_high_value_family_rows"], 15)
        self.assertEqual(self.summary["direct_numeric_restore_candidate_rows"], 0)
        self.assertEqual(self.summary["structural_material_overlap_rows"], 0)

    def test_face_rig_paths_have_zero_existing_member_coverage(self):
        rows = read_tsv(self.report / "FACE_RIG_SUPPORT_INTEGRATION.tsv")
        self.assertEqual(len(rows), 4)
        self.assertTrue(all(row["existing_member_integration_present"] == "False" for row in rows))
        self.assertTrue(all(row["write_authorized"] == "False" for row in rows))
        self.assertEqual(self.summary["target_only_face_rig_existing_member_coverage_rows"], 0)

    def test_gap_register_requires_static_rehydration_not_saves(self):
        rows = read_tsv(self.report / "CHARACTER_STATE_INTEGRATION_GAPS.tsv")
        by_id = {row["gap_id"]: row for row in rows}
        self.assertEqual(by_id["uncovered_wet_school_swim_state_families"]["affected_logical_family_rows"], "75")
        self.assertEqual(by_id["pc08_pc12_base_state_member_coverage"]["affected_logical_family_rows"], "6")
        self.assertTrue(all(row["runtime_or_save_required"] == "False" for row in rows))
        self.assertTrue(all(row["write_authorized"] == "False" for row in rows))

    def test_all_input_hashes_are_fixed_and_verified(self):
        rows = read_tsv(self.report / "INPUT_HASHES.tsv")
        self.assertEqual(len(rows), 6)
        self.assertTrue(all(row["archive_sha256"] == row["expected_archive_sha256"] for row in rows))
        self.assertTrue(all(row["summary_sha256"] == row["expected_summary_sha256"] for row in rows))
        self.assertTrue(all(row["verified"] == "True" for row in rows))

    def test_evidence_is_metadata_only_and_no_write(self):
        self.assertTrue(self.archive and self.archive.is_file())
        forbidden = {".pak", ".g1e", ".g1em", ".g1m", ".g1s", ".g1t", ".elixir", ".ebd", ".ebm"}
        self.assertFalse(any(path.suffix.casefold() in forbidden for path in self.report.rglob("*") if path.is_file()))
        policy = self.summary["policy"]
        self.assertTrue(policy["existing_evidence_only"])
        self.assertTrue(policy["member_names_hashes_and_numeric_metadata_only"])
        for key in (
            "proprietary_payload_rehydrated", "visual_or_censorship_semantics_assigned", "runtime_validation_inferred",
            "save_or_runtime_required_for_next_step", "pak_built_or_repacked", "profile_or_registry_modified",
            "core_modified", "translation_modified", "legacy_dlc_modified", "installed_game_modified", "git_modified",
        ):
            self.assertFalse(policy[key])
        self.assertEqual(self.summary["runtime_confirmed_rows"], 0)
        self.assertEqual(self.summary["write_authorized_rows"], 0)

    def test_unsafe_relative_paths_are_rejected(self):
        for value in ("../escape", "/absolute", "a/../../b"):
            with self.assertRaises(TOOL.AuditError):
                TOOL.safe_relative(value, "test path")


if __name__ == "__main__":
    unittest.main()
