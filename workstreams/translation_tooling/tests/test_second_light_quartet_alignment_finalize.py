from __future__ import annotations

import importlib.util
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "workstreams/translation_tooling/second_light_quartet_alignment_finalize.py"
TOOL = ROOT / "Blue_Reflection_Text_Tool/br_text_tool.py"

SPEC = importlib.util.spec_from_file_location("br_text_tool_finalize_test", TOOL)
assert SPEC and SPEC.loader
BR = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = BR
SPEC.loader.exec_module(BR)


class SecondLightAlignmentFinalizeTests(unittest.TestCase):
    def make_project(self, root: Path) -> Path:
        (root / "Blue_Reflection_Text_Tool").mkdir(parents=True)
        shutil.copy2(TOOL, root / "Blue_Reflection_Text_Tool/br_text_tool.py")
        (root / "workstreams/translation").mkdir(parents=True)
        (root / "workstreams/translation/VERSION").write_text("0.0.112\n", encoding="utf-8")
        (root / "workstreams/translation/STATUS.json").write_text(
            json.dumps({"version": "0.0.112"}) + "\n", encoding="utf-8"
        )
        (root / "workstreams/translation/CONTENT_CHANGELOG.json").write_text("{}\n", encoding="utf-8")
        (root / "workstreams/translation/docs").mkdir(parents=True)
        (root / "workstreams/translation/docs/RELEASE_HISTORY.md").write_text("# History\n", encoding="utf-8")

        src = root / "titles/second_light/workspace/original/test_jp.xml"
        aux_jp = root / "titles/second_light/workspace/quartet/test_jp.xml"
        aux_en = root / "titles/second_light/workspace/quartet/test_en.xml"
        src.parent.mkdir(parents=True, exist_ok=True)
        aux_jp.parent.mkdir(parents=True, exist_ok=True)
        src.write_text(
            '<root>'
            '<str String_No="1" Text="A"/>'
            '<str String_No="2" Text="B"/>'
            '<str String_No="3" Text="C"/>'
            '<str String_No="4" Text="D"/>'
            '</root>', encoding="utf-8"
        )
        aux_jp.write_text(
            '<root>'
            '<str String_No="1" Text="A"/>'
            '<str String_No="2" Text="B changed"/>'
            '<str String_No="3" Text="C"/>'
            '<str String_No="4" Text="D"/>'
            '</root>', encoding="utf-8"
        )
        aux_en.write_text(
            '<root>'
            '<str String_No="1" Text="Alpha"/>'
            '<str String_No="2" Text="-"/>'
            '<str String_No="3" Text=""/>'
            '<str String_No="4" Text="Delta"/>'
            '</root>', encoding="utf-8"
        )
        unit_dir = root / "titles/second_light/translation/system"
        unit_dir.mkdir(parents=True)
        unit = {
            "type": "br_system_translation_unit",
            "format_version": 1,
            "project": "second_light",
            "category": "system",
            "source_role": "canonical",
            "logical_path": "test.xml",
            "source": {
                "jp_path": src.relative_to(root).as_posix(),
                "auxiliary_jp_path": aux_jp.relative_to(root).as_posix(),
                "auxiliary_en_path": aux_en.relative_to(root).as_posix(),
            },
            "targets": {},
            "records": [
                {"index": 0, "logical_id": "sl:1", "string_no": "1", "jp": "A", "en_original": "A old", "en_auxiliary": "Alpha", "en": "Edited A", "alignment": {}},
                {"index": 1, "logical_id": "sl:2", "string_no": "2", "jp": "B", "en_original": "B old", "en_auxiliary": "-", "en": "Edited B", "alignment": {}},
                {"index": 2, "logical_id": "sl:3", "string_no": "3", "jp": "C", "en_original": "C old", "en_auxiliary": "", "en": "Edited C", "alignment": {}},
                {"index": 3, "logical_id": "sl:4", "string_no": "4", "jp": "D", "en_original": "D old", "en_auxiliary": None, "en": "Edited D", "notes": "keep", "status": "reviewed", "alignment": {}},
            ],
        }
        (unit_dir / "test.xml.json").write_text(json.dumps(unit, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

        ext_dir = root / "titles/second_light/translation/events_quartet_extensions"
        ext_dir.mkdir(parents=True)
        extension = {
            "type": "br_event_translation_unit",
            "format_version": 1,
            "project": "second_light",
            "category": "event",
            "source_role": "quartet_extension",
            "logical_path": "ext.ebm",
            "source": {},
            "targets": {},
            "records": [
                {"index": 0, "logical_id": "sl:ext:0", "msg_id": 0, "jp": "New", "en_original": None, "en_auxiliary": None, "en": "", "alignment": {"status": "manual_required"}}
            ],
        }
        (ext_dir / "ext.ebm.json").write_text(json.dumps(extension, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return unit_dir / "test.xml.json"

    def make_ebm(self, path: Path, rows: list[tuple[int, str]]) -> None:
        messages = []
        for index, (msg_id, text) in enumerate(rows):
            messages.append(BR.EBMMessage(
                index=index, type=0, voice_id=0, unknown1=0, name_id=0,
                extra_id=0, expr_id=0, duration1=(), msg_id=msg_id,
                unknown2=0, text=text, duration2=(),
            ))
        ebm = BR.EBMFile(
            path=path, signed_count=len(messages), d1_len=0, d2_len=0,
            messages=tuple(messages), extra_data=b"", raw=b"",
        )
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(BR.serialize_ebm(ebm))

    def run_tool(self, root: Path, command: str, out: Path) -> dict:
        result = subprocess.run(
            [sys.executable, str(SCRIPT), command, "--project-root", str(root), "--output-dir", str(out)],
            check=True,
            text=True,
            capture_output=True,
        )
        return json.loads(result.stdout)

    def test_exporter_normalizes_unusable_auxiliary_values(self) -> None:
        self.assertEqual(BR.normalize_auxiliary_reference("JP", "English"), ("English", "available", None))
        self.assertEqual(BR.normalize_auxiliary_reference("JP", "-"), (None, "redacted", None))
        self.assertEqual(BR.normalize_auxiliary_reference("JP", ""), (None, "empty", None))
        self.assertEqual(BR.normalize_auxiliary_reference("JP", None), (None, "unavailable", None))

    def test_audit_then_apply_normalizes_only_auxiliary_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            unit_path = self.make_project(root)
            original = unit_path.read_bytes()
            audit = self.run_tool(root, "audit", root / "audit")
            self.assertEqual(audit["status"], "audit_complete")
            self.assertEqual(unit_path.read_bytes(), original)
            self.assertEqual(audit["auxiliary_value_statuses"]["available"], 2)
            self.assertEqual(audit["auxiliary_value_statuses"]["quartet_en_redacted"], 1)
            self.assertEqual(audit["auxiliary_value_statuses"]["quartet_en_empty"], 1)

            applied = self.run_tool(root, "apply", root / "applied")
            self.assertEqual(applied["to_translation_version"], "0.0.113")
            data = json.loads(unit_path.read_text(encoding="utf-8"))
            records = data["records"]
            self.assertEqual(records[0]["en_auxiliary"], "Alpha")
            self.assertIsNone(records[1]["en_auxiliary"])
            self.assertIsNone(records[2]["en_auxiliary"])
            self.assertEqual(records[3]["en_auxiliary"], "Delta")
            self.assertEqual([row["en"] for row in records], ["Edited A", "Edited B", "Edited C", "Edited D"])
            self.assertEqual(records[3]["notes"], "keep")
            self.assertEqual(records[3]["status"], "reviewed")
            self.assertEqual(records[1]["alignment"]["auxiliary_source_value"], "-")
            self.assertEqual(records[1]["alignment"]["auxiliary_value_status"], "quartet_en_redacted")
            self.assertEqual((root / "workstreams/translation/VERSION").read_text().strip(), "0.0.113")

    def test_event_structural_identity_and_short_english_file(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            self.make_project(root)
            source = root / "titles/second_light/workspace/original/event_jp/test.ebm"
            aux_jp = root / "titles/second_light/workspace/quartet/event_jp/test.ebm"
            aux_en = root / "titles/second_light/workspace/quartet/event_en/test.ebm"
            self.make_ebm(source, [(1, "JP one"), (2, "JP two")])
            self.make_ebm(aux_jp, [(1, "JP one changed"), (2, "JP two")])
            self.make_ebm(aux_en, [(1, "-")])
            unit_dir = root / "titles/second_light/translation/events/test"
            unit_dir.mkdir(parents=True)
            unit = {
                "type": "br_event_translation_unit", "format_version": 1,
                "project": "second_light", "category": "event",
                "source_role": "canonical", "logical_path": "test/test.ebm",
                "source": {
                    "jp_path": source.relative_to(root).as_posix(),
                    "auxiliary_jp_path": aux_jp.relative_to(root).as_posix(),
                    "auxiliary_en_path": aux_en.relative_to(root).as_posix(),
                },
                "targets": {},
                "records": [
                    {"index": 0, "logical_id": "event:0", "msg_id": 1, "jp": "JP one", "en_original": "One", "en_auxiliary": "-", "en": "Translated one", "alignment": {}},
                    {"index": 1, "logical_id": "event:1", "msg_id": 2, "jp": "JP two", "en_original": "Two", "en_auxiliary": None, "en": "Translated two", "alignment": {}},
                ],
            }
            path = unit_dir / "test.ebm.json"
            path.write_text(json.dumps(unit, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            result = self.run_tool(root, "apply", root / "event-result")
            data = json.loads(path.read_text(encoding="utf-8"))
            self.assertIsNone(data["records"][0]["en_auxiliary"])
            self.assertEqual(data["records"][0]["alignment"]["auxiliary_source_jp_relation"], "changed")
            self.assertEqual(data["records"][0]["alignment"]["auxiliary_value_status"], "quartet_en_redacted")
            self.assertIsNone(data["records"][1]["en_auxiliary"])
            self.assertEqual(data["records"][1]["alignment"]["auxiliary_value_status"], "quartet_en_record_absent")
            self.assertEqual(result["totals"]["canonical_event_without_usable_auxiliary"], 2)
            self.assertEqual(result["totals"].get("canonical_event_without_usable_auxiliary_and_en_empty", 0), 0)

    def test_changed_jp_fallback_is_accepted_only_between_no_shift_anchors(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            self.make_project(root)
            source = root / "titles/second_light/workspace/original/event_jp/anchored.ebm"
            aux_jp = root / "titles/second_light/workspace/quartet/event_jp/anchored.ebm"
            aux_en = root / "titles/second_light/workspace/quartet/event_en/anchored.ebm"
            self.make_ebm(source, [(10, "Anchor A"), (20, "Original JP"), (30, "Anchor C")])
            self.make_ebm(aux_jp, [(10, "Anchor A"), (21, "Changed JP"), (30, "Anchor C")])
            self.make_ebm(aux_en, [(10, "Alpha"), (21, "Recovered English"), (30, "Charlie")])
            unit_dir = root / "titles/second_light/translation/events/anchored"
            unit_dir.mkdir(parents=True)
            path = unit_dir / "anchored.ebm.json"
            path.write_text(json.dumps({
                "type": "br_event_translation_unit", "format_version": 1,
                "project": "second_light", "category": "event",
                "source_role": "canonical", "logical_path": "anchored/anchored.ebm",
                "source": {
                    "jp_path": source.relative_to(root).as_posix(),
                    "auxiliary_jp_path": aux_jp.relative_to(root).as_posix(),
                    "auxiliary_en_path": aux_en.relative_to(root).as_posix(),
                },
                "targets": {},
                "records": [
                    {"index": 0, "logical_id": "anchor:0", "msg_id": 10, "jp": "Anchor A", "en_auxiliary": "Alpha", "en": "A", "alignment": {}},
                    {"index": 1, "logical_id": "anchor:1", "msg_id": 20, "jp": "Original JP", "en_auxiliary": "Recovered English", "en": "B", "alignment": {}},
                    {"index": 2, "logical_id": "anchor:2", "msg_id": 30, "jp": "Anchor C", "en_auxiliary": "Charlie", "en": "C", "alignment": {}},
                ],
            }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            result = self.run_tool(root, "apply", root / "anchored-result")
            data = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(data["records"][1]["en_auxiliary"], "Recovered English")
            self.assertIn("same_index_context_anchored", data["records"][1]["alignment"]["auxiliary_mapping_authoritative"])
            self.assertEqual(result["unresolved_usable_candidates"], 0)

    def test_unanchored_usable_same_index_candidate_stops_with_report(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            self.make_project(root)
            source = root / "titles/second_light/workspace/original/event_jp/unanchored.ebm"
            aux_jp = root / "titles/second_light/workspace/quartet/event_jp/unanchored.ebm"
            aux_en = root / "titles/second_light/workspace/quartet/event_en/unanchored.ebm"
            self.make_ebm(source, [(10, "Original JP")])
            self.make_ebm(aux_jp, [(20, "Changed JP")])
            self.make_ebm(aux_en, [(20, "Possible English")])
            unit_dir = root / "titles/second_light/translation/events/unanchored"
            unit_dir.mkdir(parents=True)
            path = unit_dir / "unanchored.ebm.json"
            path.write_text(json.dumps({
                "type": "br_event_translation_unit", "format_version": 1,
                "project": "second_light", "category": "event",
                "source_role": "canonical", "logical_path": "unanchored/unanchored.ebm",
                "source": {
                    "jp_path": source.relative_to(root).as_posix(),
                    "auxiliary_jp_path": aux_jp.relative_to(root).as_posix(),
                    "auxiliary_en_path": aux_en.relative_to(root).as_posix(),
                },
                "targets": {},
                "records": [
                    {"index": 0, "logical_id": "unanchored:0", "msg_id": 10, "jp": "Original JP", "en_auxiliary": None, "en": "Translated", "alignment": {}},
                ],
            }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            out = root / "unanchored-result"
            result = subprocess.run(
                [sys.executable, str(SCRIPT), "audit", "--project-root", str(root), "--output-dir", str(out)],
                text=True, capture_output=True,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("unresolved usable auxiliary candidates remain: 1", result.stderr)
            rows = json.loads((out / "UNRESOLVED_USABLE_CANDIDATES.json").read_text(encoding="utf-8"))
            self.assertEqual(rows[0]["same_index_quartet_en"], "Possible English")


    def test_unanchored_quartet_jp_and_en_redaction_is_normalized_not_blocked(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            self.make_project(root)
            source = root / "titles/second_light/workspace/original/event_jp/redacted.ebm"
            aux_jp = root / "titles/second_light/workspace/quartet/event_jp/redacted.ebm"
            aux_en = root / "titles/second_light/workspace/quartet/event_en/redacted.ebm"
            self.make_ebm(source, [(10, "Original visible JP")])
            self.make_ebm(aux_jp, [(20, "-")])
            self.make_ebm(aux_en, [(20, "-")])
            unit_dir = root / "titles/second_light/translation/events/redacted"
            unit_dir.mkdir(parents=True)
            path = unit_dir / "redacted.ebm.json"
            path.write_text(json.dumps({
                "type": "br_event_translation_unit", "format_version": 1,
                "project": "second_light", "category": "event",
                "source_role": "canonical", "logical_path": "redacted/redacted.ebm",
                "source": {
                    "jp_path": source.relative_to(root).as_posix(),
                    "auxiliary_jp_path": aux_jp.relative_to(root).as_posix(),
                    "auxiliary_en_path": aux_en.relative_to(root).as_posix(),
                },
                "targets": {},
                "records": [
                    {"index": 0, "logical_id": "redacted:0", "msg_id": 10,
                     "jp": "Original visible JP", "en_auxiliary": "-",
                     "en": "Preserved translation", "alignment": {}},
                ],
            }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            result = self.run_tool(root, "apply", root / "redacted-result")
            data = json.loads(path.read_text(encoding="utf-8"))
            record = data["records"][0]
            self.assertIsNone(record["en_auxiliary"])
            self.assertEqual(record["en"], "Preserved translation")
            self.assertEqual(
                record["alignment"]["auxiliary_value_status"],
                "quartet_en_redacted_unresolved_source_mapping",
            )
            self.assertEqual(record["alignment"]["auxiliary_source_value"], "-")
            self.assertEqual(result["unresolved_usable_candidates"], 0)



if __name__ == "__main__":
    unittest.main()
