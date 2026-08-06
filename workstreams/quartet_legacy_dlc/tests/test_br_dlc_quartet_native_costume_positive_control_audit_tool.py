import importlib.util
import tempfile
import unittest
from pathlib import Path
import sys

MODULE_PATH = Path(__file__).resolve().parents[1] / "br_dlc_quartet_native_costume_positive_control_audit_tool.py"
spec = importlib.util.spec_from_file_location("positive_control", MODULE_PATH)
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)


class PositiveControlTests(unittest.TestCase):
    def test_visible_base_and_quartet_only_labels_never_auto_prove_dlc(self):
        acceptance = {
            "runtime_visible_labels": [
                {"label": "Hoshinomiya Uniform", "classification": "retained_base_label", "reason": "base"},
                {"label": "School Swimsuit", "classification": "retained_base_label", "reason": "base"},
                {"label": "Gym Uniform", "classification": "quartet_only_visible_label_owner_unproven", "reason": "owner"},
                {"label": "Cami", "classification": "quartet_only_visible_label_owner_unproven", "reason": "owner"},
            ]
        }
        rows = [
            {"string_no": "393217", "status": "identical", "original_text": "Hoshinomiya Uniform", "quartet_text": "Hoshinomiya Uniform"},
            {"string_no": "393337", "status": "quartet_only", "original_text": "", "quartet_text": "Gym Uniform"},
        ]
        output = module.classify_visible_labels(rows, acceptance)
        self.assertEqual(len(output), 4)
        self.assertTrue(all(not row["positive_control_eligible"] for row in output))

    def test_legacy_labels_require_dash_in_quartet(self):
        rows = [{"original_text": label, "quartet_text": "-"} for label in module.LEGACY_LABELS]
        output = module.classify_legacy_labels(rows)
        self.assertTrue(all(row["all_replaced_by_dash"] for row in output))

    def test_platform_config_is_auxiliary_only(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "steam_emu.ini"
            path.write_text("[DLC]\n123456=Example Costume\nDLCUnlockall=0\n", encoding="utf-8")
            rows = module.parse_auxiliary_dlc_config(path)
            self.assertTrue(rows)
            self.assertTrue(all(row["semantic_authority"] is False for row in rows))
            self.assertTrue(all(row["original_appid_mapping_used"] is False for row in rows))

    def test_token_hits_find_exact_costume_tag(self):
        encoding, hits = module.text_token_hits(b"selected=PC00_DLC_TWL\n", ["PC00_DLC_TWL"])
        self.assertEqual(encoding, "utf-8-sig")
        self.assertEqual(hits[0]["tokens"], ["PC00_DLC_TWL"])

    def test_candidate_evaluation_is_fail_closed(self):
        visible = [{"label": "Gym Uniform", "reason": "owner unproven"}]
        rows = module.candidate_rows(visible, [], [], [], [])
        self.assertTrue(rows)
        self.assertTrue(all(row["positive_control_proven"] is False for row in rows))


if __name__ == "__main__":
    unittest.main()
