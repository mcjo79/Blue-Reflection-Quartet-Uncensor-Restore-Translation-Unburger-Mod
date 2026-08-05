#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import json
import struct
import sys
import tempfile
import unittest
from pathlib import Path

MODULE_PATH = Path(__file__).resolve().parents[1] / "collect_reflector_slot_light_swordflash_g1em_section_table_binding_evidence.py"
spec = importlib.util.spec_from_file_location("stage117", MODULE_PATH)
assert spec and spec.loader
S = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = S
spec.loader.exec_module(S)


def model(model_id: str, ordinal: int, mapping: str) -> dict[str, str]:
    return {
        "pair_id": "pair",
        "model_id": model_id,
        "edit_kind": "target_deletion_piecewise_offset_shift",
        "edit_ordinal": str(ordinal),
        "matched_ordinal_pairs": mapping,
    }


def table(side: str, table_index: int, entry_index: int, relative: int, ordinal: int) -> dict[str, object]:
    return {
        "side": side,
        "table_index": table_index,
        "entry_index": entry_index,
        "record_relative_dword": relative,
        "occurrence_ordinal": ordinal,
    }


def g1em(side: str, offset: int, encoding: str, ordinal: int) -> dict[str, object]:
    return {
        "side": side,
        "g1em_dword_offset": offset,
        "encoding": encoding,
        "occurrence_ordinal": ordinal,
    }


class Stage117Tests(unittest.TestCase):
    def test_companion_key(self) -> None:
        self.assertEqual(S.companion_key("e_pc00_test.g1e#0"), "e_pc00_test.g1em#0")

    def test_joint_channels_select_deletion_ordinal_two(self) -> None:
        d1 = model("d1", 1, "0->0;2->1")
        d2 = model("d2", 2, "0->0;1->1")
        source_table = [table("source", 1, 0, -27, 0), table("source", 2, 0, -27, 1)]
        target_table = [table("target", 1, 0, -27, 0), table("target", 2, 0, -27, 1)]
        source_g1em = [g1em("source", 4, "absolute_dword_offset", 1)]
        target_g1em = [g1em("target", 4, "absolute_dword_offset", 1)]
        r1 = S.evaluate_model(d1, source_table, target_table, source_g1em, target_g1em)
        r2 = S.evaluate_model(d2, source_table, target_table, source_g1em, target_g1em)
        self.assertFalse(S.parse_bool(r1["identity_eligible_joint_topology_model"]))
        self.assertTrue(S.parse_bool(r2["identity_eligible_joint_topology_model"]))
        pair = {"pair_id": "pair", "member_key": "x", "member_name": "x"}
        decision = S.decide_pair(pair, [r1, r2])
        self.assertEqual(decision["selected_model_id"], "d2")

    def test_missing_g1em_never_resolves(self) -> None:
        d2 = model("d2", 2, "0->0;1->1")
        source_table = [table("source", 1, 0, -27, 0), table("source", 2, 0, -27, 1)]
        target_table = [table("target", 1, 0, -27, 0), table("target", 2, 0, -27, 1)]
        row = S.evaluate_model(d2, source_table, target_table, [], [])
        self.assertFalse(S.parse_bool(row["identity_eligible_joint_topology_model"]))
        self.assertEqual(row["g1em_support_rows"], 0)

    def test_conflicting_companion_binding_never_resolves(self) -> None:
        d2 = model("d2", 2, "0->0;1->1")
        source_table = [table("source", 1, 0, -27, 0), table("source", 2, 0, -27, 1)]
        target_table = [table("target", 1, 0, -27, 0), table("target", 2, 0, -27, 1)]
        source_g1em = [g1em("source", 4, "absolute_dword_offset", 2)]
        target_g1em = [g1em("target", 4, "absolute_dword_offset", 1)]
        row = S.evaluate_model(d2, source_table, target_table, source_g1em, target_g1em)
        self.assertFalse(S.parse_bool(row["identity_eligible_joint_topology_model"]))
        self.assertGreater(row["g1em_conflict_rows"], 0)

    def test_duplicate_eligible_models_remain_unresolved(self) -> None:
        pair = {"pair_id": "pair", "member_key": "x", "member_name": "x"}
        rows = [
            {"model_id": "a", "identity_eligible_joint_topology_model": True},
            {"model_id": "b", "identity_eligible_joint_topology_model": True},
        ]
        decision = S.decide_pair(pair, rows)
        self.assertEqual(decision["selected_model_id"], "")
        self.assertEqual(decision["eligible_joint_topology_model_rows"], 2)


    def test_stage109_real_summary_contract_is_accepted(self) -> None:
        with tempfile.TemporaryDirectory(prefix="stage117-summary-contract-") as tmp_name:
            tmp = Path(tmp_name)
            roots = {name: tmp / name for name in ("108", "109", "111", "116")}
            for path in roots.values():
                path.mkdir()
            summaries = {
                "108": {"status": "underscore_archive_retirement_closed", "retirement_complete": True},
                "109": {"tool_version": "0.1.23", "revalidated_occurrence_rows": 1814},
                "111": {"tool_version": "0.1.25", "one_edit_alignment_model_rows": 23},
                "116": {
                    "tool_version": "0.1.31",
                    "still_unresolved_noncanary_pair_rows": 2,
                    "canary_identity_preserved": True,
                    "prototype_candidate_rows": 0,
                    "skipped_rows": 0,
                },
            }
            for name, payload in summaries.items():
                (roots[name] / "SUMMARY.json").write_text(json.dumps(payload), encoding="utf-8")
            validated = S.validate_summaries(roots["108"], roots["109"], roots["111"], roots["116"])
            self.assertEqual(validated[1]["revalidated_occurrence_rows"], 1814)

    def test_stage109_legacy_wrong_field_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory(prefix="stage117-summary-contract-bad-") as tmp_name:
            tmp = Path(tmp_name)
            roots = {name: tmp / name for name in ("108", "109", "111", "116")}
            for path in roots.values():
                path.mkdir()
            summaries = {
                "108": {"status": "underscore_archive_retirement_closed", "retirement_complete": True},
                "109": {"tool_version": "0.1.23", "format_valid_sibling_occurrence_rows": 1814},
                "111": {"tool_version": "0.1.25", "one_edit_alignment_model_rows": 23},
                "116": {
                    "tool_version": "0.1.31",
                    "still_unresolved_noncanary_pair_rows": 2,
                    "canary_identity_preserved": True,
                    "prototype_candidate_rows": 0,
                    "skipped_rows": 0,
                },
            }
            for name, payload in summaries.items():
                (roots[name] / "SUMMARY.json").write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaisesRegex(S.Stage117Error, "stage109 summary mismatch"):
                S.validate_summaries(roots["108"], roots["109"], roots["111"], roots["116"])

    def test_pc00_parent_scope_accepts_three_member_rows_for_one_container(self) -> None:
        rows = [
            {
                "normalized_path": S.PC00_CONTAINER,
                "candidate_id": "effectcand_pc00",
                "member_key": member,
            }
            for member in sorted(S.EXPECTED_PC00_PARENT_SCOPE_MEMBERS)
        ]
        scoped = S.validate_pc00_parent_scope(rows)
        self.assertEqual(len(scoped), 3)
        self.assertEqual({row["candidate_id"] for row in scoped}, {"effectcand_pc00"})

    def test_pc00_parent_scope_rejects_multiple_parent_identities(self) -> None:
        rows = [
            {
                "normalized_path": S.PC00_CONTAINER,
                "candidate_id": "effectcand_pc00_a" if index < 2 else "effectcand_pc00_b",
                "member_key": member,
            }
            for index, member in enumerate(sorted(S.EXPECTED_PC00_PARENT_SCOPE_MEMBERS))
        ]
        with self.assertRaisesRegex(S.Stage117Error, "expected one PC00 parent identity"):
            S.validate_pc00_parent_scope(rows)

    def test_pc00_parent_scope_rejects_member_set_drift(self) -> None:
        rows = [
            {
                "normalized_path": S.PC00_CONTAINER,
                "candidate_id": "effectcand_pc00",
                "member_key": member,
            }
            for member in (
                "e_pc00_eyelight_00.g1e#0",
                "e_pc00_eyelight_01.g1e#0",
                "e_pc00_unexpected.g1e#0",
            )
        ]
        with self.assertRaisesRegex(S.Stage117Error, "scope set mismatch"):
            S.validate_pc00_parent_scope(rows)

    def test_section_table_parser(self) -> None:
        payload = bytearray(256)
        endpoint = 32
        # Three tables, two entries each: 56..64, 64..72, 72..80.
        for i, value in enumerate((1, 2, 3, 4, 5, 6)):
            struct.pack_into("<I", payload, endpoint + 56 + i * 4, value)
        header = {
            "exact_layout": True,
            "fixed_header_size": 56,
            "table_boundary_1": 64,
            "table_boundary_2": 72,
            "table_boundary_3": 80,
        }
        rows = S.extract_section_table_entries(bytes(payload), endpoint, header)
        self.assertEqual(len(rows), 6)
        self.assertEqual(rows[0]["table_index"], 1)
        self.assertEqual(rows[-1]["table_index"], 3)


if __name__ == "__main__":
    unittest.main()
