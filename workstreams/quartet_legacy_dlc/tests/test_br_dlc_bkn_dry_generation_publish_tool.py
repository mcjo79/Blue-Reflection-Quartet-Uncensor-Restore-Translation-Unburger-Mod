from __future__ import annotations

import importlib.util
import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
TOOL_PATH = ROOT / "br_dlc_bkn_dry_generation_publish_tool.py"
RUNNER_PATH = ROOT / "91_run_bkn_dry_pc05_generation_preview_evidence.sh"


def load_tool():
    spec = importlib.util.spec_from_file_location("generation_publish_tool", TOOL_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class GenerationPublishToolTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tool = load_tool()

    def test_build_manifest_generation_6(self):
        composition = {
            "Data/PACK10_02.PAK": {
                "candidate_relative_path": self.tool.EXPECTED_CANDIDATES["Data/PACK10_02.PAK"],
                "candidate_size": "123",
                "candidate_sha256": "a" * 64,
            },
            "Data/PACK12.PAK": {
                "candidate_relative_path": self.tool.EXPECTED_CANDIDATES["Data/PACK12.PAK"],
                "candidate_size": "456",
                "candidate_sha256": "b" * 64,
            },
        }
        acceptance = {
            "installed_baselines": [
                {"relative_path": "Data/PACK10_02.PAK", "size": 111, "sha256": "c" * 64},
                {"relative_path": "Data/PACK12.PAK", "size": 222, "sha256": "d" * 64},
            ]
        }
        manifest = self.tool.build_manifest(composition, acceptance, "e" * 64)
        self.tool.validate_manifest_semantics(manifest)
        self.assertEqual(manifest["generation"], 6)
        self.assertEqual(manifest["members"], self.tool.MEMBERS)
        self.assertEqual(manifest["artifacts"][0]["member_delta"]["added"], self.tool.ADDED_MEMBERS)
        self.assertEqual(manifest["artifacts"][1]["member_delta"]["changed"], ["saves/b1/chara/charabase.xml"])
        self.assertFalse(manifest["transaction"]["commit_enabled"])

    def test_version_gate(self):
        self.assertEqual(self.tool.TOOL_VERSION, "0.0.50")
        self.assertEqual(self.tool.version_tuple("0.0.47"), (0, 0, 47))
        self.assertGreater(self.tool.version_tuple("0.0.50"), self.tool.version_tuple("0.0.47"))
        with self.assertRaises(self.tool.GenerationPublishError):
            self.tool.version_tuple("0.0")

    def test_stage91_runner_requires_current_workstream_version(self):
        text = RUNNER_PATH.read_text(encoding="utf-8")
        self.assertIn('== "0.0.50"', text)
        self.assertIn('quartet_legacy_dlc 0.0.50 is required', text)
        self.assertNotIn('quartet_legacy_dlc 0.0.49 is required', text)

    def test_production_source_contains_no_machine_specific_paths(self):
        text = TOOL_PATH.read_text(encoding="utf-8")
        self.assertNotIn("/home/", text)
        self.assertNotRegex(text, r"(?i)[A-Z]:[\\/]Users[\\/]")


if __name__ == "__main__":
    unittest.main()
