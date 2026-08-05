from __future__ import annotations

import importlib.util
import json
import pathlib
import sys
import types
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
TOOL_PATH = ROOT / "br_dlc_bkn_dry_pc02_generation_tool.py"


def _stub(name: str, error_name: str) -> None:
    if name in sys.modules:
        return
    module = types.ModuleType(name)
    setattr(module, error_name, type(error_name, (RuntimeError,), {}))
    sys.modules[name] = module


def load_tool():
    _stub("br_dlc_bkn_dry_pack12_repack_tool", "BknDryPack12RepackError")
    _stub("br_dlc_dry_pak_insertion_tool", "DryPakInsertionError")
    _stub("br_dlc_nested_container_tool", "NestedContainerError")
    _stub("br_dlc_transfer_probe_tool", "TransferProbeError")
    _stub("br_restoration_tool", "RestorationError")
    spec = importlib.util.spec_from_file_location("pc02_generation_tool", TOOL_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class Pc02GenerationToolTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tool = load_tool()
        cls.acceptance = json.loads((ROOT / "DLC_BKN_DRY_PC02_GENERATION_ACCEPTANCE.json").read_text(encoding="utf-8"))

    def sample_xml(self) -> bytes:
        return (
            '<?xml version="1.0" encoding="Shift_JIS"?>\n'
            '<Root>\n'
            '<CharaBase BaseTag="PC00_DLC_BKN" Model="PC00/PC00_DLC_Bkn" defaultTexture="PC00/PC00_DLC_Bkn" Facial="keep0" Motion1="keep0"/>\n'
            '<CharaBase BaseTag="PC00_DLC_BKN_W" Model="PC00/PC00_Scl_W" defaultTexture="PC00/PC00_Scl_W" Facial="wet0" Motion1="wet0"/>\n'
            '<CharaBase BaseTag="PC01_DLC_BKN" Model="PC01/PC01_DLC_Bkn" defaultTexture="PC01/PC01_DLC_Bkn" Facial="keep1" Motion1="keep1"/>\n'
            '<CharaBase BaseTag="PC01_DLC_BKN_W" Model="PC01/PC01_Scl_W" defaultTexture="PC01/PC01_Scl_W" Facial="wet1" Motion1="wet1"/>\n'
            '<CharaBase BaseTag="PC02_DLC_BKN" Model="PC02/PC02_Scl" defaultTexture="PC02/PC02_Scl" Facial="keep2" Motion1="keep2"/>\n'
            '<CharaBase BaseTag="PC02_DLC_BKN_W" Model="PC02/PC02_Scl_W" defaultTexture="PC02/PC02_Scl_W" Facial="wet2" Motion1="wet2"/>\n'
            '</Root>\n'
        ).encode("cp932")

    def test_patch_changes_only_pc02_dry_model_and_texture(self):
        before = self.sample_xml()
        after, detail = self.tool.patch_charabase(before, self.acceptance)
        self.assertEqual(sorted(detail["changed_fields"]), ["Model", "defaultTexture"])
        self.assertTrue(detail["wet_record_unchanged"])
        self.assertTrue(detail["prior_family_records_unchanged"])
        self.assertTrue(detail["outside_pc02_record_unchanged"])
        after_text, _ = self.tool.decode_xml(after)
        self.assertIn('BaseTag="PC00_DLC_BKN" Model="PC00/PC00_DLC_Bkn"', after_text)
        self.assertIn('BaseTag="PC01_DLC_BKN" Model="PC01/PC01_DLC_Bkn"', after_text)
        self.assertIn('BaseTag="PC02_DLC_BKN" Model="PC02/PC02_DLC_Bkn" defaultTexture="PC02/PC02_DLC_Bkn"', after_text)

    def test_patch_rejects_unexpected_parent_value(self):
        broken = self.sample_xml().replace(b"PC02/PC02_Scl", b"PC02/PC02_Alt", 1)
        with self.assertRaises(self.tool.Pc02FamilyCandidateError):
            self.tool.patch_charabase(broken, self.acceptance)

    def test_acceptance_is_fail_closed(self):
        auth = self.acceptance["authorization"]
        self.assertTrue(auth["local_candidate_build"])
        self.assertTrue(auth["active_manifest_generation_3_publication"])
        self.assertTrue(auth["read_only_canonical_preview"])
        for key in (
            "prepare", "commit", "installation", "profile_registration", "runtime_validation",
            "wet_bkn", "translation_modification", "restoration_modification", "core_modification",
            "git_modification",
        ):
            self.assertFalse(auth[key], key)
        self.assertEqual(self.acceptance["source_evidence"]["selected_character_id"], "PC02")
        self.assertEqual({row["role"] for row in self.acceptance["source_assets"]}, {"dry_parent", "dry_external_texture"})

    def test_production_files_contain_no_machine_specific_paths(self):
        for name in (
            "br_dlc_bkn_dry_pc02_generation_tool.py",
            "br_dlc_bkn_dry_generation_publish_tool.py",
            "88_run_bkn_dry_pc02_generation_preview_evidence.sh",
            "DLC_BKN_DRY_PC02_GENERATION_ACCEPTANCE.json",
            "DLC_BKN_DRY_PC00_PC01_GENERIC_PREVIEW_ACCEPTANCE.json",
        ):
            text = (ROOT / name).read_text(encoding="utf-8")
            self.assertNotIn("/home/", text)
            self.assertNotRegex(text, r"(?i)[A-Z]:[\\/]Users[\\/]")


if __name__ == "__main__":
    unittest.main()
