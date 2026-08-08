from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
import sys
from pathlib import Path

TOOL = Path(__file__).resolve().parents[1] / "br_dlc_bkn_dry_exact_availability_closure_tool.py"
spec = importlib.util.spec_from_file_location("closure_tool", TOOL)
assert spec and spec.loader
mod = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = mod
spec.loader.exec_module(mod)


class ExactClosureTests(unittest.TestCase):
    def make_project(self, root: Path, reference: bool = True) -> tuple[Path, Path, Path, Path]:
        project = root / "project"
        ws = project / "workstreams/quartet_legacy_dlc"
        ws.mkdir(parents=True)
        (ws / "VERSION").write_text("0.0.57\n", encoding="utf-8")
        (ws / "DLC_BKN_DRY_GENERATION8_AVAILABILITY_ROUTING_ACCEPTANCE.json").write_text(
            json.dumps({
                "status": "accepted_for_read_only_exact_availability_closure",
                "evidence_bundle_sha256": mod.EXPECTED_ROUTING_BUNDLE_SHA256,
            }), encoding="utf-8")
        active = project / ".local/reports/quartet_legacy_dlc/validated_payloads/ACTIVE.json"
        active.parent.mkdir(parents=True)
        active.write_text(json.dumps({"generation": 8, "members": mod.EXPECTED_MEMBERS}), encoding="utf-8")
        workspace = project / "titles/blue_reflection/workspace"

        def put(rel: str, body: str) -> None:
            p = workspace / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(body, encoding="utf-8")

        put("original/archives/PACK02_1/saves_en/text/str_costume.xml",
            '<root><str String_No="1" Text="Hoshinomiya Uniform"/><str String_No="2" Text="Bikini"/><str String_No="3" Text="School Swimsuit"/></root>')
        put("quartet/archives/PACK12/saves/b1/text_en/str_costume.xml",
            '<root><str String_No="1" Text="Hoshinomiya Uniform"/><str String_No="3" Text="School Swimsuit"/></root>')
        ref_attr = ' NameStringNo="2"' if reference else ''
        put("original/archives/PACK02_1/saves_en/chara/chara.xml",
            f'<root><Chara BaseTag="PC00_SCL"{ref_attr}/><Chara BaseTag="PC00_DLC_BKN"/></root>')
        put("quartet/archives/PACK12/saves/b1/chara/chara.xml",
            f'<root><Chara BaseTag="PC00_SCL"{ref_attr}/><Chara BaseTag="PC00_DLC_BKN"/></root>')
        put("original/archives/PACK02_1/saves_en/chara/chara_no.xml", '<root><Chara BaseTag="PC00_DLC_BKN"/></root>')
        put("quartet/archives/PACK12/saves/b1/chara/chara_no.xml", '<root><Chara BaseTag="PC00_DLC_BKN"/></root>')
        put("original/archives/PACK02_1/saves_en/chara/charabase.xml", '<root><CharaBase BaseTag="PC00_DLC_BKN" Model="PC00/PC00_DLC_Bkn"/></root>')
        put("quartet/archives/PACK12/saves/b1/chara/charabase.xml", '<root><CharaBase BaseTag="PC00_DLC_BKN" Model="PC00/PC00_DLC_Bkn"/></root>')
        original = root / "original_game"; original.mkdir()
        quartet = root / "quartet_game"; quartet.mkdir()
        out = root / "out"
        return project, original, quartet, out

    def test_original_only_string_with_xml_reference_is_table_candidate(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project, original, quartet, out = self.make_project(Path(tmp), reference=True)
            summary = mod.run(project, original, quartet, out)
            self.assertEqual(summary["str_costume"]["original_only_string_numbers"], [2])
            self.assertGreater(summary["references"]["xml_references_to_original_only_string_numbers"], 0)
            self.assertEqual(summary["conclusion"]["route_classification"], "table_or_index_driven_candidate")
            self.assertFalse(summary["conclusion"]["next_payload_generation_allowed"])

    def test_no_reference_requires_save_or_entitlement_differential(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project, original, quartet, out = self.make_project(Path(tmp), reference=False)
            summary = mod.run(project, original, quartet, out)
            self.assertEqual(summary["conclusion"]["route_classification"], "string_sequence_truncated_but_no_owner_reference_found")
            self.assertTrue(summary["conclusion"]["save_or_entitlement_state_differential_may_be_required"])

    def test_misleading_utf8_bom_falls_back_to_cp932(self) -> None:
        raw = b"\xef\xbb\xbf" + '<root><str Text="テスト"/></root>'.encode("cp932")
        self.assertIn("テスト", mod.decode_xml(raw, "synthetic"))

    def test_production_source_has_no_machine_specific_path(self) -> None:
        text = TOOL.read_text(encoding="utf-8")
        self.assertNotRegex(text, r"/home/[^/\\s]+/")
        self.assertNotIn("/mnt/data", text)


if __name__ == "__main__":
    unittest.main()
