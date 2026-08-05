#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

MODULE_PATH = Path(__file__).resolve().parents[1] / "collect_reflector_slot_light_companion_topology_binding_evidence.py"
spec = importlib.util.spec_from_file_location("stage116", MODULE_PATH)
assert spec and spec.loader
S = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = S
spec.loader.exec_module(S)


def pair(pair_id: str, member_key: str, source: str, target: str) -> dict[str, str]:
    return {
        "pair_id": pair_id,
        "member_key": member_key,
        "member_name": member_key.split("#", 1)[0],
        "source_values": source,
        "target_values": target,
    }


def model(pair_id: str, member_key: str, ordinal: int, source_count: int, target_count: int) -> dict[str, str]:
    pairs = []
    if target_count == source_count + 1:
        for source_ordinal in range(source_count):
            target_ordinal = source_ordinal if source_ordinal < ordinal else source_ordinal + 1
            pairs.append(f"{source_ordinal}->{target_ordinal}")
        kind = "target_insertion_piecewise_offset_shift"
    else:
        for source_ordinal in range(source_count):
            if source_ordinal == ordinal:
                continue
            target_ordinal = source_ordinal if source_ordinal < ordinal else source_ordinal - 1
            pairs.append(f"{source_ordinal}->{target_ordinal}")
        kind = "target_deletion_piecewise_offset_shift"
    return {
        "pair_id": pair_id,
        "member_key": member_key,
        "model_id": f"{pair_id}|{kind}|{ordinal}",
        "edit_kind": kind,
        "edit_ordinal": str(ordinal),
        "matched_ordinal_pairs": ";".join(pairs),
    }


class Stage116CompanionTopologyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.pairs = {
            "charge00": pair("charge00", "e_pc02_m4_charge_00.g1e#0", "1;400;60;2", "1;200;200;60;2"),
            "charge01": pair("charge01", "e_pc02_m4_charge_01.g1e#0", "1;600;2;600;800;500", "1;300;300;2;600;800;500"),
            "beard": pair("beard", "e_pc02_m4_beardivision.g1e#0", "1;200;1000", "1;200;200;1000"),
        }
        self.models = {
            "m00": model("charge00", "e_pc02_m4_charge_00.g1e#0", 1, 4, 5),
            "m01": model("charge01", "e_pc02_m4_charge_01.g1e#0", 1, 6, 7),
            "b1": model("beard", "e_pc02_m4_beardivision.g1e#0", 1, 3, 4),
            "b2": model("beard", "e_pc02_m4_beardivision.g1e#0", 2, 3, 4),
            "b3": model("beard", "e_pc02_m4_beardivision.g1e#0", 3, 3, 4),
        }

    def test_two_independent_companions_form_consensus(self) -> None:
        resolved = [
            {**self.pairs["charge00"], "selected_model_id": self.models["m00"]["model_id"], "selection_basis": "independent_a"},
            {**self.pairs["charge01"], "selected_model_id": self.models["m01"]["model_id"], "selection_basis": "independent_b"},
        ]
        by_id = {row["model_id"]: row for row in self.models.values()}
        consensus = S.build_consensus_classes(resolved, by_id, self.pairs)
        self.assertEqual(len(consensus), 1)
        self.assertTrue(S.parse_bool(consensus[0]["consensus_eligible"]))
        self.assertEqual(consensus[0]["edit_ordinal"], 1)
        self.assertEqual(consensus[0]["distinct_resolved_members"], 2)

    def test_beardivision_resolves_only_ordinal_one(self) -> None:
        resolved = [
            {**self.pairs["charge00"], "selected_model_id": self.models["m00"]["model_id"], "selection_basis": "independent_a"},
            {**self.pairs["charge01"], "selected_model_id": self.models["m01"]["model_id"], "selection_basis": "independent_b"},
        ]
        by_id = {row["model_id"]: row for row in self.models.values()}
        consensus = S.build_consensus_classes(resolved, by_id, self.pairs)
        decision, bindings = S.decide_unresolved_pair(self.pairs["beard"], [self.models["b1"], self.models["b2"], self.models["b3"]], consensus)
        self.assertEqual(decision["selected_model_id"], self.models["b1"]["model_id"])
        self.assertEqual(decision["classification"], "occurrence_identity_resolved_by_companion_topology_consensus")
        self.assertEqual(sum(S.parse_bool(row["companion_consensus_supported"]) for row in bindings), 1)

    def test_one_reference_is_not_independent_consensus(self) -> None:
        resolved = [{**self.pairs["charge00"], "selected_model_id": self.models["m00"]["model_id"], "selection_basis": "only_one"}]
        by_id = {row["model_id"]: row for row in self.models.values()}
        consensus = S.build_consensus_classes(resolved, by_id, self.pairs)
        self.assertEqual(len(consensus), 1)
        self.assertFalse(S.parse_bool(consensus[0]["consensus_eligible"]))
        decision, _ = S.decide_unresolved_pair(self.pairs["beard"], [self.models["b1"], self.models["b2"]], consensus)
        self.assertFalse(decision["selected_model_id"])

    def test_companion_pair_without_resolved_reference_stays_unresolved(self) -> None:
        bullet_pair = pair("bullet", "e_pc00_swordflash_02_bullet.g1e#0", "1;6000;2000", "1;6000")
        d1 = model("bullet", "e_pc00_swordflash_02_bullet.g1e#0", 1, 3, 2)
        d2 = model("bullet", "e_pc00_swordflash_02_bullet.g1e#0", 2, 3, 2)
        decision, bindings = S.decide_unresolved_pair(bullet_pair, [d1, d2], [])
        self.assertFalse(decision["selected_model_id"])
        self.assertEqual(decision["consensus_supported_model_rows"], 0)
        self.assertTrue(all(not S.parse_bool(row["companion_consensus_supported"]) for row in bindings))


if __name__ == "__main__":
    unittest.main()
