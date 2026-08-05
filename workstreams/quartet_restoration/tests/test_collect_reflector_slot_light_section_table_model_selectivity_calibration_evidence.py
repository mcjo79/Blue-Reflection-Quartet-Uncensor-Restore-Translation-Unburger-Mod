#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

MODULE_PATH = Path(__file__).resolve().parents[1] / "collect_reflector_slot_light_section_table_model_selectivity_calibration_evidence.py"
spec = importlib.util.spec_from_file_location("stage118", MODULE_PATH)
assert spec and spec.loader
S = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = S
spec.loader.exec_module(S)


def model(model_id: str, ordinal: int, mapping: str) -> dict[str, str]:
    return {
        "pair_id": "pair",
        "model_id": model_id,
        "normalized_path": S.PC00_CONTAINER,
        "member_key": "member.g1e#0",
        "member_name": "member.g1e",
        "edit_kind": "target_deletion_piecewise_offset_shift",
        "edit_ordinal": str(ordinal),
        "matched_ordinal_pairs": mapping,
    }


def table(table_index: int, entry_index: int, relative: int, ordinal: int) -> dict[str, object]:
    return {
        "table_index": table_index,
        "entry_index": entry_index,
        "record_relative_dword": relative,
        "occurrence_ordinal": ordinal,
    }


class Stage118Tests(unittest.TestCase):
    def test_zero_conflict_table_rule_selects_deletion_ordinal_two(self) -> None:
        d1 = model("d1", 1, "0->0;2->1")
        d2 = model("d2", 2, "0->0;1->1")
        source = [table(1, 0, -27, 0), table(2, 0, -27, 1)]
        target = [table(1, 0, -27, 0), table(2, 0, -27, 1)]
        r1 = S.evaluate_section_table_model(d1, source, target)
        r2 = S.evaluate_section_table_model(d2, source, target)
        self.assertFalse(S.parse_bool(r1["section_table_model_eligible"]))
        self.assertGreater(r1["section_table_conflict_rows"], 0)
        self.assertTrue(S.parse_bool(r2["section_table_model_eligible"]))
        self.assertEqual(r2["section_table_conflict_rows"], 0)

    def test_reference_passes_only_when_unique_model_matches_known_identity(self) -> None:
        pair = {"pair_id": "pair", "member_key": "m", "member_name": "m"}
        rows = [
            {"model_id": "known", "section_table_model_eligible": True},
            {"model_id": "other", "section_table_model_eligible": False},
        ]
        decision = S.calibrate_reference(pair, "known", rows)
        self.assertTrue(S.parse_bool(decision["calibration_reference_passed"]))
        wrong = S.calibrate_reference(pair, "other", rows)
        self.assertFalse(S.parse_bool(wrong["calibration_reference_passed"]))

    def test_reference_duplicate_eligible_models_fail_calibration(self) -> None:
        pair = {"pair_id": "pair", "member_key": "m", "member_name": "m"}
        rows = [
            {"model_id": "known", "section_table_model_eligible": True},
            {"model_id": "other", "section_table_model_eligible": True},
        ]
        decision = S.calibrate_reference(pair, "known", rows)
        self.assertFalse(S.parse_bool(decision["calibration_reference_passed"]))
        self.assertEqual(decision["eligible_section_table_model_rows"], 2)

    def test_swordflash_resolves_only_after_authoritative_calibration(self) -> None:
        pair = {"pair_id": "pair", "member_key": "m", "member_name": "m"}
        rows = [
            {"model_id": "d1", "section_table_model_eligible": False},
            {"model_id": "d2", "section_table_model_eligible": True},
        ]
        blocked = S.decide_swordflash(pair, rows, False)
        self.assertEqual(blocked["selected_model_id"], "")
        allowed = S.decide_swordflash(pair, rows, True)
        self.assertEqual(allowed["selected_model_id"], "d2")

    def test_swordflash_duplicate_models_remain_unresolved_after_calibration(self) -> None:
        pair = {"pair_id": "pair", "member_key": "m", "member_name": "m"}
        rows = [
            {"model_id": "d1", "section_table_model_eligible": True},
            {"model_id": "d2", "section_table_model_eligible": True},
        ]
        decision = S.decide_swordflash(pair, rows, True)
        self.assertEqual(decision["selected_model_id"], "")
        self.assertEqual(decision["eligible_section_table_model_rows"], 2)

    def test_parent_scope_requires_one_identity_per_container(self) -> None:
        rows = [
            {"normalized_path": S.PC00_CONTAINER, "candidate_id": "pc00", "member_key": "a"},
            {"normalized_path": S.PC00_CONTAINER, "candidate_id": "pc00", "member_key": "b"},
            {"normalized_path": S.PC02_CONTAINER, "candidate_id": "pc02", "member_key": "c"},
        ]
        scoped = S.validate_parent_scopes(rows)
        self.assertEqual(len(scoped), 3)
        bad = rows + [{"normalized_path": S.PC02_CONTAINER, "candidate_id": "pc02_other", "member_key": "d"}]
        with self.assertRaisesRegex(S.Stage118Error, "expected one parent identity"):
            S.validate_parent_scopes(bad)

    def test_real_prerequisite_summary_contracts(self) -> None:
        with tempfile.TemporaryDirectory(prefix="stage118-contract-") as tmp_name:
            tmp = Path(tmp_name)
            names = ("108", "109", "111", "115", "116", "117")
            roots = {name: tmp / name for name in names}
            for root in roots.values():
                root.mkdir()
            payloads = {
                "108": {"status": "underscore_archive_retirement_closed", "retirement_complete": True},
                "109": {"tool_version": "0.1.23", "revalidated_occurrence_rows": 1814},
                "111": {"tool_version": "0.1.25", "one_edit_alignment_model_rows": 23},
                "115": {"tool_version": "0.1.30", "total_resolved_noncanary_pair_rows_after_stage115": 4, "canary_identity_preserved": True, "prototype_candidate_rows": 0},
                "116": {"tool_version": "0.1.31", "total_resolved_noncanary_pair_rows_after_stage116": 5, "canary_identity_preserved": True, "prototype_candidate_rows": 0},
                "117": {"tool_version": "0.1.34", "still_unresolved_noncanary_pair_rows": 2, "same_stem_g1em_companion_rows": 0, "canary_identity_preserved": True, "prototype_candidate_rows": 0},
            }
            for name, payload in payloads.items():
                (roots[name] / "SUMMARY.json").write_text(json.dumps(payload), encoding="utf-8")
            result = S.validate_summaries(*(roots[name] for name in names))
            self.assertEqual(result[1]["revalidated_occurrence_rows"], 1814)

    def test_stage117_companion_drift_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory(prefix="stage118-contract-bad-") as tmp_name:
            tmp = Path(tmp_name)
            names = ("108", "109", "111", "115", "116", "117")
            roots = {name: tmp / name for name in names}
            for root in roots.values():
                root.mkdir()
            payloads = {
                "108": {"status": "underscore_archive_retirement_closed", "retirement_complete": True},
                "109": {"tool_version": "0.1.23", "revalidated_occurrence_rows": 1814},
                "111": {"tool_version": "0.1.25", "one_edit_alignment_model_rows": 23},
                "115": {"tool_version": "0.1.30", "total_resolved_noncanary_pair_rows_after_stage115": 4, "canary_identity_preserved": True, "prototype_candidate_rows": 0},
                "116": {"tool_version": "0.1.31", "total_resolved_noncanary_pair_rows_after_stage116": 5, "canary_identity_preserved": True, "prototype_candidate_rows": 0},
                "117": {"tool_version": "0.1.34", "still_unresolved_noncanary_pair_rows": 2, "same_stem_g1em_companion_rows": 1, "canary_identity_preserved": True, "prototype_candidate_rows": 0},
            }
            for name, payload in payloads.items():
                (roots[name] / "SUMMARY.json").write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaisesRegex(S.Stage118Error, "same-stem G1EM state drift"):
                S.validate_summaries(*(roots[name] for name in names))


if __name__ == "__main__":
    unittest.main()
