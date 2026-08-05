#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
TOOL_PATH = ROOT / "workstreams/quartet_restoration/collect_reflector_slot_light_record_boundary_residual_evidence.py"
spec = importlib.util.spec_from_file_location("stage88", TOOL_PATH)
assert spec and spec.loader
TOOL = importlib.util.module_from_spec(spec)
spec.loader.exec_module(TOOL)


class ResidualModelTests(unittest.TestCase):
    def test_signed_i32_decodes_stage87_values(self):
        self.assertEqual(TOOL.signed_i32(0xFFFFFC8C), -884)
        self.assertEqual(TOOL.signed_i32(0xFFFFFC7C), -900)
        self.assertEqual(TOOL.signed_i32(0xFFFFF7AC), -2132)
        self.assertEqual(TOOL.signed_i32(0xFFFFF52C), -2772)

    def test_candidate_residual_exactly_compensates_shift(self):
        self.assertTrue(TOOL.compensation_holds(21160, 21176, 0xFFFFFC8C, 0xFFFFFC7C))

    def test_neutral_residual_exactly_compensates_shift(self):
        self.assertTrue(TOOL.compensation_holds(2324, 2964, 0xFFFFF7AC, 0xFFFFF52C))

    def test_non_compensating_transition_is_rejected(self):
        self.assertFalse(TOOL.compensation_holds(100, 116, 0xFFFFFF00, 0xFFFFFEF8))

    def test_models_preserve_endpoint_but_do_not_resolve_origin(self):
        rows = TOOL.model_endpoints(
            source_offset=21160,
            target_offset=21176,
            source_value=0xFFFFFC8C,
            target_value=0xFFFFFC7C,
            island_source_start=21120,
            island_target_start=21136,
            island_source_end=21164,
            island_target_end=21180,
        )
        by_name = {row["model"]: row for row in rows}
        self.assertEqual(by_name["dword_start_relative"]["source_endpoint"], 20276)
        self.assertEqual(by_name["dword_start_relative"]["target_endpoint"], 20276)
        self.assertEqual(by_name["dword_end_relative"]["source_endpoint"], 20280)
        self.assertTrue(by_name["island_start_relative"]["endpoint_equal"])
        self.assertFalse(by_name["member_start_signed_absolute"]["endpoint_equal"])

    def test_nearest_run_and_containing_segment(self):
        runs = [
            {"source_start": "80", "length": "16"},
            {"source_start": "120", "length": "20"},
        ]
        self.assertEqual(TOOL.nearest_run(runs, 100, before=True)["source_start"], "80")
        self.assertEqual(TOOL.nearest_run(runs, 100, before=False)["source_start"], "120")
        segments = [{"source_start": "96", "source_end_exclusive": "112", "segment_id": "s"}]
        self.assertEqual(TOOL.containing_segment(segments, 100)["segment_id"], "s")


if __name__ == "__main__":
    unittest.main()
