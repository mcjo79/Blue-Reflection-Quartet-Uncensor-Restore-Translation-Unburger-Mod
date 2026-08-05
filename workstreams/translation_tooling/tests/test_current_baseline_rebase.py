from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path

MODULE_PATH = Path(__file__).resolve().parents[3] / "Blue_Reflection_Text_Tool/br_text_tool.py"
SPEC = importlib.util.spec_from_file_location("br_text_tool_rebase", MODULE_PATH)
assert SPEC and SPEC.loader
mod = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = mod
SPEC.loader.exec_module(mod)


class CurrentBaselineRebaseTests(unittest.TestCase):
    def make_ebm(self, path: Path, rows: list[tuple[int, str]]) -> None:
        messages = []
        for index, (msg_id, text) in enumerate(rows):
            messages.append(
                mod.EBMMessage(
                    index=index,
                    type=0,
                    voice_id=0,
                    unknown1=0,
                    name_id=0,
                    extra_id=0,
                    expr_id=0,
                    duration1=(),
                    msg_id=msg_id,
                    unknown2=0,
                    text=text,
                    duration2=(),
                )
            )
        ebm = mod.EBMFile(
            path=path,
            signed_count=len(messages),
            d1_len=0,
            d2_len=0,
            messages=tuple(messages),
            extra_data=b"",
            raw=b"",
        )
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(mod.serialize_ebm(ebm))

    def test_event_translation_rebases_by_unique_msg_id(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            canonical = root / "titles/blue_reflection/workspace/original/archives/PACK01/event/event_en/test.ebm"
            current_root = root / ".local/build/core/version/PACK01"
            current = current_root / "event/event_en/test.ebm"
            self.make_ebm(canonical, [(10, "A"), (20, "B")])
            self.make_ebm(current, [(10, "A2"), (15, "NEW"), (20, "B2")])
            unit_path = root / "titles/blue_reflection/translation/event/test.json"
            unit = {
                "type": "br_event_translation_unit",
                "targets": {
                    "blue_reflection_original": {
                        "template_path": canonical.relative_to(root).as_posix()
                    }
                },
                "records": [
                    {
                        "logical_id": "event:test:20",
                        "en": "Translated B",
                        "alignment": {"target_indices": {"blue_reflection_original": 1}},
                    }
                ],
            }
            override = mod.TargetWorkspaceOverride(
                target_id="blue_reflection_original",
                archive_stem="PACK01",
                workspace_archive_root=current_root,
                source_manifest=current_root / "PACK01.json",
                source_archive_relative="DATA/PACK01.PAK",
                source_archive_sha256="1" * 64,
                source_archive_bytes=123,
            )
            output, stats = mod.apply_event_unit(
                root,
                root / "titles/blue_reflection/translation",
                unit_path,
                unit,
                "blue_reflection_original",
                workspace_overrides={("blue_reflection_original", "PACK01"): override},
            )
            parsed = mod.parse_ebm_bytes(output, unit_path)
            self.assertEqual([m.text for m in parsed.messages], ["A2", "NEW", "Translated B"])
            self.assertEqual(stats["applied_records"], 1)
            self.assertEqual(stats["version_rebased_records"], 1)
            self.assertEqual(stats["version_unmapped_records"], 0)

    def test_system_translation_rebases_by_string_id(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            canonical = root / "titles/blue_reflection/workspace/original/archives/PACK02_1/saves_en/text/test.xml"
            current_root = root / ".local/build/core/version/PACK02_1"
            current = current_root / "saves_en/text/test.xml"
            canonical.parent.mkdir(parents=True, exist_ok=True)
            current.parent.mkdir(parents=True, exist_ok=True)
            canonical.write_text('<root><str String_ID="A" Text="Old A"/><str String_ID="B" Text="Old B"/></root>', encoding="utf-8")
            current.write_text('<root><str String_ID="X" Text="New row"/><str String_ID="B" Text="Current B"/><str String_ID="A" Text="Current A"/></root>', encoding="utf-8")
            unit_path = root / "titles/blue_reflection/translation/system/test.json"
            unit = {
                "type": "br_system_translation_unit",
                "targets": {
                    "blue_reflection_original": {
                        "template_path": canonical.relative_to(root).as_posix()
                    }
                },
                "records": [
                    {
                        "logical_id": "system:test:B",
                        "en": "Translated B",
                        "alignment": {"target_indices": {"blue_reflection_original": 1}},
                    }
                ],
            }
            override = mod.TargetWorkspaceOverride(
                target_id="blue_reflection_original",
                archive_stem="PACK02_1",
                workspace_archive_root=current_root,
                source_manifest=current_root / "PACK02_1.json",
                source_archive_relative="DATA/PACK02_1.PAK",
                source_archive_sha256="2" * 64,
                source_archive_bytes=456,
            )
            output, stats = mod.apply_system_unit(
                root,
                root / "titles/blue_reflection/translation",
                unit_path,
                unit,
                "blue_reflection_original",
                workspace_overrides={("blue_reflection_original", "PACK02_1"): override},
            )
            parsed = mod.parse_xml_table_bytes(output, unit_path)
            self.assertEqual([row.text for row in parsed.rows], ["New row", "Translated B", "Current A"])
            self.assertEqual(stats["applied_records"], 1)
            self.assertEqual(stats["version_rebased_records"], 1)
            self.assertEqual(stats["version_unmapped_records"], 0)


if __name__ == "__main__":
    unittest.main()
