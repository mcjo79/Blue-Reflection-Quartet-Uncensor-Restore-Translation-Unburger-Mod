from __future__ import annotations

import csv
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
WS = ROOT / "workstreams/quartet_restoration"
TOOL_ROOT = ROOT / "Blue_Reflection_Text_Tool"
sys.path.insert(0, str(WS))
sys.path.insert(0, str(TOOL_ROOT))

spec = importlib.util.spec_from_file_location(
    "build_friend_event_message_payload_prototypes",
    WS / "build_friend_event_message_payload_prototypes.py",
)
assert spec and spec.loader
TOOL = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = TOOL
spec.loader.exec_module(TOOL)

import br_text_tool as TEXT


def message(index: int, text: str) -> TEXT.EBMMessage:
    return TEXT.EBMMessage(
        index=index,
        type=2,
        voice_id=100 + index,
        unknown1=0,
        name_id=10,
        extra_id=0xFFFFFFFF,
        expr_id=0,
        duration1=(1,),
        msg_id=1000 + index,
        unknown2=0,
        text=text,
        duration2=(2,),
    )


def ebm(path: str, texts: list[str]) -> TEXT.EBMFile:
    messages = tuple(message(i, text) for i, text in enumerate(texts))
    template = TEXT.EBMFile(
        Path(path),
        len(messages),
        1,
        1,
        messages,
        b"\x11\x22\x33\x44",
        b"",
    )
    raw = TEXT.serialize_ebm(template)
    return TEXT.parse_ebm_bytes(raw, Path(path), forced_layout=(1, 1))


class FriendEventMessagePayloadPrototypeTests(unittest.TestCase):
    def test_build_candidate_preserves_target_metadata_and_roundtrips(self) -> None:
        source = ebm("source.ebm", ["first", "second"])
        target = ebm("target.ebm", ["-", "-"])
        candidate, checks = TOOL.build_candidate(TEXT, source, target, label="fe01_200:event_en")
        self.assertTrue(all(checks.values()))
        parsed = TEXT.parse_ebm_bytes(candidate, Path("candidate.ebm"), forced_layout=(1, 1))
        self.assertEqual([m.text for m in parsed.messages], ["first", "second"])
        self.assertEqual(TOOL.metadata_sequence(parsed.messages), TOOL.metadata_sequence(target.messages))
        self.assertEqual(parsed.extra_data, target.extra_data)
        self.assertEqual(TEXT.serialize_ebm(parsed, ["-", "-"]), target.raw)

    def test_build_candidate_rejects_metadata_change(self) -> None:
        source = ebm("source.ebm", ["first"])
        target = ebm("target.ebm", ["-"])
        changed = TEXT.EBMMessage(**{**target.messages[0].__dict__, "voice_id": 999})
        target_changed_template = TEXT.EBMFile(
            target.path, target.signed_count, target.d1_len, target.d2_len,
            (changed,), target.extra_data, b"",
        )
        target_changed = TEXT.parse_ebm_bytes(
            TEXT.serialize_ebm(target_changed_template), Path("target_changed.ebm"), forced_layout=(1, 1)
        )
        with self.assertRaises(TOOL.FriendEventMessagePrototypeError):
            TOOL.build_candidate(TEXT, source, target_changed, label="bad")

    def test_validate_stage57_accepts_canonical_94_scene_report(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            summary = {
                "type": "br_quartet_restoration_fe01_message_placeholder_evidence_summary",
                "tool_version": "0.0.65",
                "status": "scene_wide_multilingual_dash_placeholders_detected_message_restoration_candidates",
                "safe_later_message_payload_prototype_rows": 94,
                "skipped_rows": 0,
            }
            (root / "SUMMARY.json").write_text(json.dumps(summary), encoding="utf-8")
            rows = []
            counts = {
                "fe01": 10,
                "fe03": 7, "fe04": 7, "fe05": 7, "fe06": 7, "fe07": 7,
                "fe08": 7, "fe09": 7, "fe10": 7, "fe11": 7, "fe12": 7,
                "fe13": 7, "fe14": 7,
            }
            for family, count in counts.items():
                for index in range(count):
                    rows.append({
                        "event_id": f"{family}_{200 + index * 10:03d}",
                        "family": family,
                        "classification": "scene_text_replaced_by_multilingual_dash_placeholders_control_identical",
                        "event_data_classification": "identical",
                        "all_target_languages_exact_dash_placeholders": "True",
                        "target_language_payload_hashes_identical": "True",
                        "jp_metadata_equal_excluding_text": "True",
                        "jp_msg_id_sequence_equal": "True",
                        "ebd_hash_equal": "True",
                        "safe_for_later_message_payload_prototype": "True",
                    })
            self.assertEqual(len(rows), 94)
            fields = list(rows[0])
            with (root / "FE_EVENT_PLACEHOLDER_SCENE_CANDIDATES.tsv").open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=fields, delimiter="\t", lineterminator="\n")
                writer.writeheader(); writer.writerows(rows)
            loaded_summary, safe = TOOL.validate_stage57(root)
            self.assertEqual(loaded_summary["tool_version"], "0.0.65")
            self.assertEqual(len(safe), 94)
            self.assertEqual(tuple(sorted({row["family"] for row in safe})), TOOL.EXPECTED_FAMILIES)

    def test_paths_are_family_scoped(self) -> None:
        self.assertEqual(TOOL.profile_id_for_family("fe01"), "friend_event_message_payload_fe01")
        self.assertEqual(
            TOOL.target_member_path("fe01_200", "event_en"),
            "event/b1/event_en/fe01/event_message_fe01_200.ebm",
        )


if __name__ == "__main__":
    unittest.main()
