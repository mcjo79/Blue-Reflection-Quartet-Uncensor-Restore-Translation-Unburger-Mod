from __future__ import annotations

import csv
import importlib.util
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
MODULE_PATH = PROJECT_ROOT / "workstreams/quartet_restoration/141_collect_effect_posteffect_kps_target_dword_prototype_plan_evidence.py"
SPEC = importlib.util.spec_from_file_location("stage141", MODULE_PATH)
assert SPEC and SPEC.loader
stage141 = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = stage141
SPEC.loader.exec_module(stage141)

UPLOADED_STAGE140 = PROJECT_ROOT / ".local/reports/quartet_restoration" / stage141.STAGE140_NAME


def read_tsv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


class KpsTargetDwordPrototypePlanTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        if not UPLOADED_STAGE140.is_file():
            raise unittest.SkipTest("uploaded stage-140 report unavailable")
        cls.temporary = tempfile.TemporaryDirectory(prefix="stage141-test-")
        cls.root = Path(cls.temporary.name)
        cls.report_root = cls.root / "reports"
        cls.output_root = cls.root / "output"
        cls.report_root.mkdir(parents=True)
        shutil.copy2(UPLOADED_STAGE140, cls.report_root / stage141.STAGE140_NAME)
        cls.archive, cls.summary = stage141.build_report(
            PROJECT_ROOT,
            report_root=cls.report_root,
            output_report_root=cls.output_root,
            create_archive=True,
        )
        cls.report = cls.output_root / stage141.REPORT_DIR

    @classmethod
    def tearDownClass(cls) -> None:
        cls.temporary.cleanup()

    def test_summary_cardinality(self) -> None:
        self.assertEqual(self.summary["kps_admitted_program_rows"], 15)
        self.assertEqual(self.summary["kps_admitted_member_rows"], 2)
        self.assertEqual(self.summary["kps_planned_target_dword_edit_rows"], 227)
        self.assertEqual(self.summary["kps_changed_instruction_rows"], 58)

    def test_every_planned_coordinate_is_unique(self) -> None:
        rows = read_tsv(self.report / "KPS_TARGET_DWORD_EDIT_PLAN.tsv")
        keys = {
            (r["member_key"], r["program_pair_index"], r["code_chunk_key"], r["instruction_index"], r["instruction_dword_index"])
            for r in rows
        }
        self.assertEqual(len(rows), 227)
        self.assertEqual(len(keys), 227)

    def test_every_edit_has_exact_target_precondition(self) -> None:
        rows = read_tsv(self.report / "KPS_TARGET_DWORD_EDIT_PLAN.tsv")
        self.assertTrue(all(r["precondition_required"] == "True" for r in rows))
        self.assertTrue(all(r["expected_target_u32_hex"] != r["proposed_original_u32_hex"] for r in rows))

    def test_plan_contains_only_gamma_and_glowlight(self) -> None:
        rows = read_tsv(self.report / "KPS_PROGRAM_TARGET_DWORD_PROTOTYPE_PLAN.tsv")
        self.assertEqual({r["member_name"] for r in rows}, {"PostEffectGamma.kps", "PostEffectGlowLight.kps"})
        self.assertEqual(sum(r["member_name"] == "PostEffectGlowLight.kps" for r in rows), 14)

    def test_vitahdr_is_excluded_as_whole_program(self) -> None:
        rows = read_tsv(self.report / "KPS_EXCLUDED_PROGRAMS.tsv")
        vita = [r for r in rows if r["member_name"] == "PostEffectVitaHDR.kps"]
        self.assertEqual(len(vita), 1)
        self.assertEqual(vita[0]["exclusion_reason"], "opcode_inventory_equal_but_instruction_envelope_delta")

    def test_all_nonminimal_programs_are_carried(self) -> None:
        rows = read_tsv(self.report / "KPS_EXCLUDED_PROGRAMS.tsv")
        self.assertEqual(len(rows), 28)
        self.assertEqual(self.summary["kps_excluded_program_rows"], 28)

    def test_no_coordinate_conflicts(self) -> None:
        self.assertEqual(read_tsv(self.report / "KPS_EDIT_COORDINATE_CONFLICTS.tsv"), [])
        self.assertEqual(self.summary["kps_edit_coordinate_conflict_rows"], 0)

    def test_program_and_edit_ids_are_unique(self) -> None:
        programs = read_tsv(self.report / "KPS_PROGRAM_TARGET_DWORD_PROTOTYPE_PLAN.tsv")
        edits = read_tsv(self.report / "KPS_TARGET_DWORD_EDIT_PLAN.tsv")
        self.assertEqual(len({r["program_plan_id"] for r in programs}), 15)
        self.assertEqual(len({r["edit_plan_id"] for r in edits}), 227)

    def test_g1e_families_remain_unresolved_calibration_only(self) -> None:
        rows = read_tsv(self.report / "G1E_UNRESOLVED_CALIBRATION_CARRY_FORWARD.tsv")
        self.assertEqual(len(rows), 7)
        self.assertTrue(all(r["whole_family_layout_resolved"] == "False" for r in rows))

    def test_runtime_state_is_preserved(self) -> None:
        self.assertEqual(self.summary["runtime_validated_profile_rows_preserved"], 1)
        self.assertEqual(
            self.summary["runtime_validated_profile_id_preserved"],
            "candidate_bathroom_river_containing_pak_static_inverse_062e39915e7d",
        )
        self.assertEqual(self.summary["runtime_failed_shader_rows_preserved"], 2)

    def test_report_contains_no_proprietary_payload_extensions(self) -> None:
        forbidden = stage141.FORBIDDEN_EXTENSIONS
        names = [p.name.casefold() for p in self.report.rglob("*") if p.is_file()]
        self.assertFalse(any(name.endswith(forbidden) for name in names))

    def test_safety_contract(self) -> None:
        policy = self.summary["policy"]
        self.assertTrue(policy["existing_evidence_only"])
        self.assertTrue(policy["target_dword_precondition_required_for_every_planned_edit"])
        self.assertFalse(policy["prototype_or_patch_built"])
        self.assertFalse(policy["installed_game_modified"])
        self.assertFalse(policy["core_modified"])
        self.assertEqual(self.summary["write_authorized_rows"], 0)

    def test_archive_and_summary_are_emitted(self) -> None:
        self.assertIsNotNone(self.archive)
        self.assertTrue(self.archive.is_file())
        stored = json.loads((self.report / "SUMMARY.json").read_text(encoding="utf-8"))
        self.assertEqual(stored, self.summary)


if __name__ == "__main__":
    unittest.main()
