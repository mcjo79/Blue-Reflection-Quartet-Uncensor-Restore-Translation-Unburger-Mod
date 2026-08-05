#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import math
import sys
import unittest
from pathlib import Path

MODULE_PATH = Path(__file__).resolve().parents[1] / "collect_reflector_slot_light_trailer_algebraic_schema_evidence.py"
spec = importlib.util.spec_from_file_location("stage114", MODULE_PATH)
assert spec and spec.loader
S = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = S
spec.loader.exec_module(S)


class Stage114RelationTests(unittest.TestCase):
    def test_cube_relation_is_detected_without_semantic_label(self) -> None:
        relations, diagnostics = S.classify_relation_values({128: 0.0, 129: 150.0, 132: 9.0, 134: 3_375_000.0, 136: 9.0})
        self.assertEqual(relations, [S.CUBE_RELATION])
        self.assertTrue(diagnostics["cube_ok"])

    def test_cube_difference_relation_is_detected(self) -> None:
        relations, diagnostics = S.classify_relation_values({128: 300.0, 129: 500.0, 132: 9.0, 134: 98_000_000.0, 136: 9.0})
        self.assertEqual(relations, [S.CUBE_DIFFERENCE_RELATION])
        self.assertTrue(diagnostics["cube_difference_ok"])

    def test_cosine_relation_is_detected(self) -> None:
        angle = math.radians(20.0)
        relations, diagnostics = S.classify_relation_values({128: 0.0, 129: 0.0, 132: angle, 134: 0.0, 136: math.cos(angle)})
        self.assertEqual(relations, [S.COSINE_RELATION])
        self.assertTrue(diagnostics["cosine_ok"])

    def test_unique_nonempty_schema_model_can_resolve(self) -> None:
        models = [
            {"model_id": "cube-model", "identity_eligible_algebraic_schema_model": True},
            {"model_id": "mismatch-model", "identity_eligible_algebraic_schema_model": False},
        ]
        decision = S.decide_pair("pair", "member.g1e#0", models)
        self.assertEqual(decision["selected_model_id"], "cube-model")
        self.assertEqual(decision["classification"], "occurrence_identity_resolved_by_algebraic_trailer_schema")

    def test_multiple_or_empty_schema_models_remain_unresolved(self) -> None:
        multiple = [
            {"model_id": "a", "identity_eligible_algebraic_schema_model": True},
            {"model_id": "b", "identity_eligible_algebraic_schema_model": True},
        ]
        decision = S.decide_pair("pair", "member.g1e#0", multiple)
        self.assertEqual(decision["identity_eligible_model_rows"], 2)
        self.assertEqual(decision["classification"], "occurrence_identity_unresolved_after_algebraic_schema_audit")
        empty = [{"model_id": "none", "identity_eligible_algebraic_schema_model": False}]
        decision = S.decide_pair("pair", "member.g1e#0", empty)
        self.assertEqual(decision["identity_eligible_model_rows"], 0)
        self.assertFalse(decision["selected_model_id"])

    def test_canary_unique_contradiction_fails_closed(self) -> None:
        with self.assertRaises(S.Stage114Error):
            S.decide_pair(
                "canary-pair",
                S.CANARY_MEMBER_KEY,
                [{"model_id": "wrong", "identity_eligible_algebraic_schema_model": True}],
                "immutable",
            )


if __name__ == "__main__":
    unittest.main()
