#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import pathlib
import unittest
import json
import tempfile
from pathlib import Path

MODULE_PATH = pathlib.Path(__file__).resolve().parents[1] / "second_light_quartet_alignment_audit.py"
SPEC = importlib.util.spec_from_file_location("alignment_audit", MODULE_PATH)
assert SPEC and SPEC.loader
AUDIT = importlib.util.module_from_spec(SPEC)
import sys
sys.modules[SPEC.name] = AUDIT
SPEC.loader.exec_module(AUDIT)


class AlignmentAuditTests(unittest.TestCase):
    def msg(self, index: int, text: str, msg_id: int) -> object:
        return AUDIT.Message(index=index, text=text, msg_id=msg_id, metadata={"type": 2, "name_id": 1})

    def test_sequence_alignment_handles_inserted_quartet_record(self) -> None:
        source = [
            self.msg(0, "A", 1),
            self.msg(1, "B", 2),
            self.msg(2, "C", 3),
        ]
        target = [
            self.msg(0, "A", 1),
            self.msg(1, "EXTRA", 99),
            self.msg(2, "B", 2),
            self.msg(3, "C", 3),
        ]
        mapping, methods = AUDIT.exact_sequence_map(source, target)
        self.assertEqual(mapping, {0: 0, 1: 2, 2: 3})
        self.assertTrue(all(methods[i] == "sequence_exact_text" for i in range(3)))

    def test_repeated_text_is_disambiguated_by_sequence_context(self) -> None:
        source = [
            self.msg(0, "start", 1),
            self.msg(1, "yes", 2),
            self.msg(2, "middle", 3),
            self.msg(3, "yes", 4),
            self.msg(4, "end", 5),
        ]
        target = [
            self.msg(0, "start", 1),
            self.msg(1, "yes", 2),
            self.msg(2, "insert", 8),
            self.msg(3, "middle", 3),
            self.msg(4, "yes", 4),
            self.msg(5, "end", 5),
        ]
        mapping, _ = AUDIT.exact_sequence_map(source, target)
        self.assertEqual(mapping, {0: 0, 1: 1, 2: 3, 3: 4, 4: 5})

    def test_language_structure_uses_equal_index_msg_id(self) -> None:
        source = [self.msg(0, "JP1", 11), self.msg(1, "JP2", 12)]
        target = [self.msg(0, "EN1", 11), self.msg(1, "EN2", 12)]
        mapping, methods = AUDIT.language_structure_map(source, target)
        self.assertEqual(mapping, {0: 0, 1: 1})
        self.assertEqual(methods, {0: "exact_index_msg_id", 1: "exact_index_msg_id"})

    def test_normalization_handles_cr_and_unicode_width(self) -> None:
        self.assertEqual(AUDIT.normalized_text("Ａ<CR>Ｂ  "), "A B")


    def test_full_audit_emits_recovery_proposal_without_modifying_unit(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            unit_path = root / "titles/second_light/translation/events/ce00/sample.ebm.json"
            unit_path.parent.mkdir(parents=True)
            (root / "workstreams/translation").mkdir(parents=True)
            (root / "workstreams/translation_tooling").mkdir(parents=True)
            (root / "workstreams/translation/VERSION").write_text("0.0.112\n", encoding="utf-8")
            (root / "workstreams/translation_tooling/VERSION").write_text("0.0.50\n", encoding="utf-8")
            aux_jp = root / "aux_jp.ebm"
            aux_en = root / "aux_en.ebm"
            aux_jp.write_bytes(b"placeholder")
            aux_en.write_bytes(b"placeholder")
            unit = {
                "type": "br_event_translation_unit",
                "category": "event",
                "project": "second_light",
                "logical_path": "ce00/sample.ebm",
                "source": {
                    "auxiliary_jp_path": "aux_jp.ebm",
                    "auxiliary_en_path": "aux_en.ebm",
                },
                "records": [
                    {
                        "index": 0,
                        "logical_id": "second_light:event:sample:0",
                        "msg_id": 7,
                        "metadata": {"type": 2, "name_id": 1, "msg_id": 7},
                        "jp": "テスト",
                        "en_original": "Original",
                        "en_auxiliary": None,
                        "en": "Original",
                        "alignment": {"status": "manual_required"},
                    }
                ],
            }
            unit_path.write_text(json.dumps(unit, ensure_ascii=False), encoding="utf-8")
            original_bytes = unit_path.read_bytes()

            old_loader = AUDIT.load_parser_module
            old_parser = AUDIT.parsed_messages
            try:
                AUDIT.load_parser_module = lambda _root: object()
                def fake_parser(_tool, path, _category):
                    if path.name == "aux_jp.ebm":
                        return [AUDIT.Message(0, "テスト", 7, {"type": 2, "name_id": 1, "msg_id": 7})]
                    return [AUDIT.Message(0, "Quartet English", 7, {"type": 2, "name_id": 1, "msg_id": 7})]
                AUDIT.parsed_messages = fake_parser
                output = root / "report"
                result = AUDIT.audit(root, output)
            finally:
                AUDIT.load_parser_module = old_loader
                AUDIT.parsed_messages = old_parser

            self.assertEqual(result["proposed_high_confidence_recoveries"], 1)
            proposal = json.loads((output / "HIGH_CONFIDENCE_RECOVERY_PROPOSAL.json").read_text(encoding="utf-8"))
            self.assertEqual(proposal["records"][0]["new_en_auxiliary"], "Quartet English")
            self.assertEqual(unit_path.read_bytes(), original_bytes)


if __name__ == "__main__":
    unittest.main()
