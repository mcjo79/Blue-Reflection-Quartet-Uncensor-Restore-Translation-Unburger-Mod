from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

MODULE_PATH = Path(__file__).resolve().parents[1] / "br_dlc_controlled_visibility_force_point_tool.py"
SPEC = importlib.util.spec_from_file_location("force_point", MODULE_PATH)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


def rec(side: str, index: int, attrs: dict[str, str], text: str = ""):
    return MODULE.XmlRecord(side, f"{side}/str_costume.xml", index, "str", attrs, text, f"h{index}")


class ForcePointTests(unittest.TestCase):
    def test_bkn_block_maps_exact_fifteen_slots_and_placeholders(self):
        original = [rec("original", i, {"String_No": str(100 + i), "Text": "Bikini"}) for i in range(15)]
        quartet = [rec("quartet", i, {"String_No": str(100 + i), "Text": "-"}) for i in range(15)]
        rows, exact = MODULE.bkn_label_block(original, quartet)
        self.assertTrue(exact)
        self.assertEqual(rows[0]["base_tag"], "PC00_DLC_BKN")
        self.assertEqual(rows[7]["base_tag"], "PC07_DLC_BKN")
        self.assertTrue(all(row["quartet_is_placeholder"] for row in rows))

    def test_visible_control_rows_are_non_placeholder(self):
        rows = [rec("quartet", i, {"String_No": str(i), "Text": label}) for i, label in enumerate(MODULE.VISIBLE_LABELS)]
        controls = MODULE.visible_control_rows(rows)
        self.assertEqual({row["label"] for row in controls}, set(MODULE.VISIBLE_LABELS))
        self.assertFalse(any(row["is_placeholder"] for row in controls))

    def test_placeholder_blocks_keep_source_labels_but_do_not_modify_data(self):
        original = [rec("original", 0, {"String_No": "1", "Text": "Bikini"})]
        quartet = [rec("quartet", 0, {"String_No": "1", "Text": "-"})]
        rows = MODULE.all_placeholder_blocks(original, quartet)
        self.assertEqual(rows, [{
            "source_label": "Bikini",
            "record_count": 1,
            "first_string_no": "1",
            "last_string_no": "1",
            "all_target_placeholders": True,
            "candidate_for_future_allowlisted_restoration": True,
            "raw_records_exported": False,
        }])

    def test_strategy_requires_complete_allowlisted_chain(self):
        label_rows = [{"pc_slot": f"PC{i:02d}", "quartet_record_present": True, "quartet_is_placeholder": True} for i in range(15)]
        controls = [{"label": label} for label in MODULE.VISIBLE_LABELS]
        chain = [{"chara_record_identical": True, "chara_no_record_identical": True, "quartet_baseline_is_school_uniform_fallback": True} for _ in range(8)]
        candidate = [{"routes_to_bkn_assets": True} for _ in range(8)]
        ranking, eligible, blockers = MODULE.build_force_strategy(label_rows, controls, chain, candidate)
        self.assertTrue(eligible)
        self.assertEqual(blockers, [])
        self.assertEqual(ranking[0]["strategy_id"], "restore_allowlisted_bkn_str_costume_rows")
        self.assertFalse(ranking[0]["global_show_all"])
        self.assertFalse(ranking[0]["replaces_existing_costume"])

    def test_strategy_blocks_incomplete_target_placeholders(self):
        label_rows = [{"pc_slot": f"PC{i:02d}", "quartet_record_present": True, "quartet_is_placeholder": i != 3} for i in range(15)]
        controls = [{"label": label} for label in MODULE.VISIBLE_LABELS]
        chain = [{"chara_record_identical": True, "chara_no_record_identical": True, "quartet_baseline_is_school_uniform_fallback": True} for _ in range(8)]
        candidate = [{"routes_to_bkn_assets": True} for _ in range(8)]
        _, eligible, blockers = MODULE.build_force_strategy(label_rows, controls, chain, candidate)
        self.assertFalse(eligible)
        self.assertTrue(any("placeholders" in blocker for blocker in blockers))


if __name__ == "__main__":
    unittest.main()
