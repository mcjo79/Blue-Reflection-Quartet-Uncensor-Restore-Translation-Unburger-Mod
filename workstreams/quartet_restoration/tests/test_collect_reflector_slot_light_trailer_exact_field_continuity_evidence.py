#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

MODULE_PATH = Path(__file__).resolve().parents[1] / "collect_reflector_slot_light_trailer_exact_field_continuity_evidence.py"
spec = importlib.util.spec_from_file_location("stage115", MODULE_PATH)
assert spec and spec.loader
S = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = S
spec.loader.exec_module(S)


class Stage115ContinuityTests(unittest.TestCase):
    def test_unique_strict_score_resolves(self) -> None:
        decision = S.decide_pair("pair", [
            {"model_id": "best", "exact_five_field_vector_rows": 3, "exact_individual_field_rows": 18, "exact_block_span_rows": 4},
            {"model_id": "other", "exact_five_field_vector_rows": 3, "exact_individual_field_rows": 17, "exact_block_span_rows": 4},
        ])
        self.assertEqual(decision["selected_model_id"], "best")
        self.assertEqual(decision["classification"], "occurrence_identity_resolved_by_exact_trailer_field_continuity")

    def test_tied_duplicate_blocks_remain_unresolved(self) -> None:
        decision = S.decide_pair("pair", [
            {"model_id": "a", "exact_five_field_vector_rows": 3, "exact_individual_field_rows": 15, "exact_block_span_rows": 3},
            {"model_id": "b", "exact_five_field_vector_rows": 3, "exact_individual_field_rows": 15, "exact_block_span_rows": 3},
        ])
        self.assertEqual(decision["top_score_model_rows"], 2)
        self.assertFalse(decision["selected_model_id"])
        self.assertEqual(decision["classification"], "occurrence_identity_unresolved_after_exact_trailer_field_continuity")

    def test_no_exact_vector_cannot_resolve(self) -> None:
        decision = S.decide_pair("pair", [
            {"model_id": "a", "exact_five_field_vector_rows": 0, "exact_individual_field_rows": 9, "exact_block_span_rows": 2},
            {"model_id": "b", "exact_five_field_vector_rows": 0, "exact_individual_field_rows": 8, "exact_block_span_rows": 2},
        ])
        self.assertFalse(decision["selected_model_id"])

    def test_model_score_uses_exact_text_not_closeness(self) -> None:
        comparisons = [{"pair_id": "p", "model_id": "m", "source_ordinal": "0", "target_ordinal": "0"}]
        source = {"block_span": "624", "relation_signature": "schema"}
        target = {"block_span": "624", "relation_signature": "schema"}
        for dword in S.FIELD_DWORDS:
            source[f"dword_{dword}_float"] = "1"
            target[f"dword_{dword}_float"] = "1"
        target["dword_128_float"] = "1.00000012"
        detail, summary = S.model_score("m", comparisons, {("p", "source", 0): source, ("p", "target", 0): target})
        self.assertEqual(summary["exact_five_field_vector_rows"], 0)
        self.assertEqual(summary["exact_individual_field_rows"], 4)
        self.assertFalse(detail[0]["canonical_f32_equal"])


if __name__ == "__main__":
    unittest.main()
