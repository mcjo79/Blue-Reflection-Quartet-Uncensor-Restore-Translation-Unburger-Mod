from __future__ import annotations

import importlib.util
import json
import pathlib
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
TOOL_PATH = ROOT / "br_dlc_bkn_dry_pc01_family_candidate_tool.py"


def load_tool():
    spec = importlib.util.spec_from_file_location("pc01_family_candidate_tool", TOOL_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class Pc01FamilyCandidateToolTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tool = load_tool()
        cls.acceptance = json.loads((ROOT / "DLC_BKN_DRY_PC01_PARAMETERIZATION_ACCEPTANCE.json").read_text(encoding="utf-8"))

    def sample_xml(self) -> bytes:
        return (
            '<?xml version="1.0" encoding="Shift_JIS"?>\n'
            '<Root>\n'
            '<CharaBase BaseTag="PC00_DLC_BKN" Model="PC00/PC00_DLC_Bkn" defaultTexture="PC00/PC00_DLC_Bkn" Facial="keep0" Motion1="keep0"/>\n'
            '<CharaBase BaseTag="PC00_DLC_BKN_W" Model="PC00/PC00_Scl_W" defaultTexture="PC00/PC00_Scl_W" Facial="wet0" Motion1="wet0"/>\n'
            '<CharaBase BaseTag="PC01_DLC_BKN" Model="PC01/PC01_Scl" defaultTexture="PC01/PC01_Scl" Facial="keep1" Motion1="keep1"/>\n'
            '<CharaBase BaseTag="PC01_DLC_BKN_W" Model="PC01/PC01_Scl_W" defaultTexture="PC01/PC01_Scl_W" Facial="wet1" Motion1="wet1"/>\n'
            '</Root>\n'
        ).encode("cp932")

    def test_patch_changes_only_pc01_dry_model_and_texture(self):
        before = self.sample_xml()
        after, detail = self.tool.patch_charabase(before, self.acceptance)
        self.assertEqual(sorted(detail["changed_fields"]), ["Model", "defaultTexture"])
        self.assertTrue(detail["wet_record_unchanged"])
        self.assertTrue(detail["pc00_records_unchanged"])
        self.assertTrue(detail["outside_pc01_record_unchanged"])
        before_text, _ = self.tool.decode_xml(before)
        after_text, _ = self.tool.decode_xml(after)
        self.assertIn('BaseTag="PC00_DLC_BKN" Model="PC00/PC00_DLC_Bkn"', after_text)
        self.assertIn('BaseTag="PC01_DLC_BKN" Model="PC01/PC01_DLC_Bkn" defaultTexture="PC01/PC01_DLC_Bkn"', after_text)
        self.assertNotEqual(before_text, after_text)

    def test_patch_rejects_unexpected_parent_value(self):
        broken = self.sample_xml().replace(b"PC01/PC01_Scl", b"PC01/PC01_Alt", 1)
        with self.assertRaises(self.tool.Pc01FamilyCandidateError):
            self.tool.patch_charabase(broken, self.acceptance)

    def test_acceptance_is_fail_closed(self):
        auth = self.acceptance["authorization"]
        self.assertTrue(auth["local_candidate_build"])
        for key, value in auth.items():
            if key != "local_candidate_build":
                self.assertFalse(value, key)
        self.assertEqual(self.acceptance["stage84_bundle"]["sha256"], "de3500e75b0b95c47355ddf11d0efefde3195ed8fa2fd056dcbcb71a6275dacb")
        self.assertEqual({row["role"] for row in self.acceptance["source_assets"]}, {"dry_parent", "dry_external_texture"})

    def test_production_files_contain_no_machine_specific_paths(self):
        for name in (
            "br_dlc_bkn_dry_pc01_family_candidate_tool.py",
            "85_run_bkn_dry_pc01_family_candidate_evidence.sh",
            "DLC_BKN_DRY_PC01_PARAMETERIZATION_ACCEPTANCE.json",
        ):
            text = (ROOT / name).read_text(encoding="utf-8")
            self.assertNotIn("/home/", text)
            self.assertNotRegex(text, r"(?i)[A-Z]:[\\/]Users[\\/]")


if __name__ == "__main__":
    unittest.main()
