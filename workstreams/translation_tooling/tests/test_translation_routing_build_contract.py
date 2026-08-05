from __future__ import annotations

import argparse
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

TOOL_PATH = Path(__file__).resolve().parents[3] / "Blue_Reflection_Text_Tool/br_text_tool.py"
SPEC = importlib.util.spec_from_file_location("br_text_tool_routing_test", TOOL_PATH)
assert SPEC and SPEC.loader
mod = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = mod
SPEC.loader.exec_module(mod)


class TranslationRoutingBuildContractTests(unittest.TestCase):
    def test_registry_exposes_all_six_content_targets(self) -> None:
        root = Path(__file__).resolve().parents[3]
        targets = mod.development_targets(root)
        self.assertEqual(set(targets), {
            "blue_reflection_original",
            "second_light_original",
            "blue_reflection_quartet",
            "blue_reflection_ray_quartet",
            "blue_reflection_sun_quartet",
            "second_light_quartet",
        })
        self.assertEqual(mod.target_archive_relative(root, "blue_reflection_ray_quartet", "PACK01_01"), "Data/PACK01_01.PAK")
        self.assertEqual(mod.target_archive_relative(root, "blue_reflection_sun_quartet", "PACK02_02"), "Data/PACK02_02.PAK")
        self.assertEqual(mod.target_archive_relative(root, "second_light_quartet", "PACK01_03"), "Data/PACK01_03.PAK")

    def test_production_text_reads_only_canonical_en(self) -> None:
        record = {
            "logical_id": "test:1",
            "jp": "JP",
            "en_original": "Original",
            "en_auxiliary": "Auxiliary must never be built",
            "en": "Canonical production English",
        }
        self.assertEqual(mod.validate_record_text(record, Path("unit.json")), "Canonical production English")

    def test_pre_0113_translation_is_blocked_before_build(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "config").mkdir(parents=True)
            source_routes = Path(__file__).resolve().parents[3] / "config/translation_target_routes.json"
            (root / "config/translation_target_routes.json").write_bytes(source_routes.read_bytes())
            for workstream, version in {"translation": "0.0.112", "translation_tooling": "0.0.54"}.items():
                path = root / "workstreams" / workstream / "VERSION"
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(version + "\n", encoding="utf-8")
            args = argparse.Namespace(
                project_root=str(root), target=["blue_reflection_original"],
                target_workspace_map=None, title_marker="none", runtime_canary=False,
            )
            with self.assertRaises(mod.ToolError) as raised:
                mod.cmd_build_loose(args)
            self.assertIn("older than the corrected routing boundary", str(raised.exception))

    def test_workspace_map_rejects_wrong_partition_archive(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "config").mkdir(parents=True)
            source_routes = Path(__file__).resolve().parents[3] / "config/translation_target_routes.json"
            (root / "config/translation_target_routes.json").write_bytes(source_routes.read_bytes())
            workspace = root / ".local/workspace"
            workspace.mkdir(parents=True)
            manifest = workspace / "PACK01_03.json"
            manifest.write_text("{}\n", encoding="utf-8")
            mapping = root / "map.json"
            mapping.write_text(json.dumps({
                "type": "br_target_workspace_map", "format_version": 1,
                "archives": [{
                    "target_id": "second_light_quartet",
                    "archive_stem": "PACK01_03",
                    "workspace_archive_root": ".local/workspace",
                    "source_manifest": ".local/workspace/PACK01_03.json",
                    "source_archive_relative": "Data/PACK01_01.PAK",
                    "source_archive_sha256": "0" * 64,
                    "source_archive_bytes": 1,
                }],
            }), encoding="utf-8")
            with self.assertRaises(mod.ToolError) as raised:
                mod.load_target_workspace_overrides(root, str(mapping))
            self.assertIn("source route mismatch", str(raised.exception))


if __name__ == "__main__":
    unittest.main()
