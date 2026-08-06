from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

MODULE_PATH = Path(__file__).resolve().parents[1] / "br_dlc_bkn_synthetic_label_slot_audit_tool.py"
spec = importlib.util.spec_from_file_location("slot_audit", MODULE_PATH)
assert spec and spec.loader
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)


class SyntheticLabelSlotAuditTests(unittest.TestCase):
    def test_sequence_accepts_collision_free_append_without_replacing_rows(self):
        rows = [
            {
                "string_no": str(100 + index),
                "status": "identical",
                "original_text": f"Original {index}",
                "quartet_text": f"Original {index}",
                "quartet_record_index": str(index),
                "runtime_visible_label": "false",
                "quartet_record_sha256": "a" * 64,
            }
            for index in range(3)
        ]
        rows.extend([
            {
                "string_no": "103",
                "status": "quartet_only",
                "original_text": "",
                "quartet_text": "-",
                "quartet_record_index": "3",
                "runtime_visible_label": "false",
                "quartet_record_sha256": "b" * 64,
            },
            {
                "string_no": "104",
                "status": "quartet_only",
                "original_text": "",
                "quartet_text": "Gym Uniform",
                "quartet_record_index": "4",
                "runtime_visible_label": "true",
                "quartet_record_sha256": "c" * 64,
            },
        ])
        quartet_only, summary, plan = module.analyze_sequence(rows)
        self.assertEqual([row["string_no"] for row in quartet_only], [103, 104])
        self.assertTrue(summary["quartet_only_contiguous_append"])
        self.assertEqual(summary["proposed_append_start"], 105)
        self.assertEqual(summary["proposed_append_end"], 112)
        self.assertTrue(summary["proposed_range_collision_free"])
        self.assertTrue(all(row["existing_record_replaced"] is False for row in plan))

    def test_existing_two_placeholders_are_insufficient_for_eight_members(self):
        rows = []
        for index in range(4):
            rows.append({
                "string_no": str(200 + index),
                "status": "identical" if index < 2 else "quartet_only",
                "original_text": f"Base {index}" if index < 2 else "",
                "quartet_text": f"Base {index}" if index < 2 else "-",
                "quartet_record_index": str(index),
                "runtime_visible_label": "false",
                "quartet_record_sha256": "d" * 64,
            })
        _, summary, _ = module.analyze_sequence(rows)
        self.assertEqual(summary["quartet_only_placeholder_count"], 2)
        self.assertFalse(summary["existing_placeholder_capacity_sufficient_current"])
        self.assertFalse(summary["existing_placeholder_capacity_sufficient_full"])

    def test_strategy_never_authorizes_existing_costume_replacement(self):
        summary = {
            "quartet_only_contiguous_append": True,
            "proposed_range_collision_free": True,
        }
        rows = module.options(summary)
        append = next(row for row in rows if row["strategy"] == "append_eight_new_bkn_label_records")
        insert = next(row for row in rows if row["strategy"] == "insert_rows_inside_existing_per_character_blocks")
        self.assertTrue(append["eligible"])
        self.assertFalse(append["replaces_existing_costume"])
        self.assertFalse(insert["eligible"])


if __name__ == "__main__":
    unittest.main()
