from __future__ import annotations

import csv
import hashlib
import importlib.util
import json
import struct
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
WS = ROOT / "workstreams/quartet_restoration"
spec = importlib.util.spec_from_file_location(
    "collect_fe01_message_placeholder_evidence",
    WS / "collect_fe01_message_placeholder_evidence.py",
)
assert spec and spec.loader
TOOL = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = TOOL
spec.loader.exec_module(TOOL)
sys.path.insert(0, str(ROOT / "Blue_Reflection_Text_Tool"))
import br_restoration_tool as BR
import br_text_tool as TEXT


def sha(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def ebm(texts: list[str], *, metadata_bias: int = 0) -> bytes:
    output = bytearray(struct.pack("<i", len(texts)))
    for index, text in enumerate(texts):
        raw = text.encode("utf-8") + b"\0"
        words = [
            2, 100 + index, 0, 10 + index, 0xFFFFFFFF, 20 + metadata_bias,
            1000 + index, 0, len(raw),
        ]
        output.extend(struct.pack("<9I", *words))
        output.extend(raw)
    return bytes(output)


def write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")


def write_tsv(path: Path, fields: list[str], rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def read_tsv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


class Stage57Tests(unittest.TestCase):
    def test_exact_dash_classification(self) -> None:
        parsed = TEXT.parse_ebm_bytes(ebm(["-", "-"]), Path("placeholder.ebm"))
        self.assertEqual(TOOL.classify_texts(parsed.messages), "all_exact_dash_placeholders")
        substantive = TEXT.parse_ebm_bytes(ebm(["scene", "text"]), Path("scene.ebm"))
        self.assertEqual(TOOL.classify_texts(substantive.messages), "substantive_text_payload")

    def test_event_classification_requires_metadata_and_all_target_languages(self) -> None:
        source_file = TEXT.parse_ebm_bytes(ebm(["one", "two"]), Path("source.ebm"))
        target_file = TEXT.parse_ebm_bytes(ebm(["-", "-"]), Path("target.ebm"))
        source = TOOL.summarize_ebm(source_file, {}, {"size": len(source_file.raw), "sha256": sha(source_file.raw)})
        target = TOOL.summarize_ebm(target_file, {}, {"size": len(target_file.raw), "sha256": sha(target_file.raw)})
        classification, priority = TOOL.event_classification(
            jp_source=source, jp_target=target, en_source=source, en_target=target,
            target_languages=[target, target, target, target], ebd_hash_equal=True,
        )
        self.assertEqual(classification, "scene_text_replaced_by_multilingual_dash_placeholders_control_identical")
        self.assertEqual(priority, "critical")

    def test_collect_finds_eight_user_listed_placeholder_scenes(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            reports = base / "reports"
            workspace = base / "workspace"
            (reports / "inventories").mkdir(parents=True)
            (reports / "differences").mkdir()
            source_files: list[dict] = []
            target_files: list[dict] = []
            slot_rows: list[dict] = []

            for event_id in TOOL.FOCUS_EVENT_IDS:
                placeholder = event_id != "fe01_130"
                source_texts = [f"source line {index}" for index in range(3)]
                target_jp_texts = ["-", "-", "-"] if placeholder else source_texts
                target_en_texts = ["-", "-", "-"] if placeholder else [f"translated line {index}" for index in range(3)]
                payloads: list[tuple[str, str, bytes]] = []
                for language, texts in (
                    ("event_jp", source_texts),
                    ("event_en", source_texts),
                    ("event_tc", source_texts),
                ):
                    payloads.append(("source", language, ebm(texts)))
                for language, texts in (
                    ("event_jp", target_jp_texts),
                    ("event_en", target_en_texts),
                    ("event_sc", target_jp_texts if placeholder else source_texts),
                    ("event_tc", target_jp_texts if placeholder else source_texts),
                ):
                    payloads.append(("target", language, ebm(texts)))

                family = event_id.split("_", 1)[0]
                for side, language, payload in payloads:
                    normalized = f"event/{language}/{family}/event_message_{event_id}.ebm"
                    if side == "source":
                        archive = "DATA/PACK01.PAK"
                        path = normalized
                    else:
                        archive = "Data/PACK11.PAK"
                        path = f"event/b1/{language}/{family}/event_message_{event_id}.ebm"
                    row = {
                        "archive": archive, "path": path, "normalized_path": normalized,
                        "size": len(payload), "sha256": sha(payload), "extension": ".ebm",
                    }
                    (source_files if side == "source" else target_files).append(row)
                    file_path = BR.inventory_workspace_file(workspace, side, "br1_events", archive, path)
                    file_path.parent.mkdir(parents=True, exist_ok=True)
                    file_path.write_bytes(payload)

                slot_rows.append({
                    "event_id": event_id, "family": family,
                    "ebd_hash_equal": "True", "event_data_classification": "identical",
                })

            write_json(reports / "inventories/br1_events.source.json", {"archive_group": "br1_events", "files": source_files})
            write_json(reports / "inventories/br1_events.target.json", {"archive_group": "br1_events", "files": target_files})
            stage55 = reports / TOOL.STAGE55_DIR_NAME
            write_json(stage55 / "SUMMARY.json", {
                "type": "br_quartet_restoration_friend_event_reachability_evidence_summary",
                "tool_version": "0.0.63", "friend_event_slot_rows": len(slot_rows),
            })
            write_tsv(stage55 / "FRIEND_EVENT_SLOT_INVENTORY.tsv", list(slot_rows[0]), slot_rows)
            stage56 = reports / TOOL.STAGE56_DIR_NAME
            write_json(stage56 / "SUMMARY.json", {
                "type": "br_quartet_restoration_friend_event_trigger_graph_evidence_summary",
                "tool_version": "0.0.64",
                "status": "event_process_framing_unresolved_no_trigger_graph_claim",
                "framing_status": "event_process_framing_unresolved",
                "mapping_status": "record_to_event_order_unconfirmed",
            })

            output, summary = TOOL.collect(project_root=ROOT, workspace_root=workspace, report_root=reports)
            self.assertTrue(output.is_file())
            self.assertEqual(summary["friend_event_rows"], 9)
            self.assertEqual(summary["placeholder_scene_rows"], 8)
            self.assertEqual(summary["critical_placeholder_scene_rows"], 8)
            self.assertEqual(summary["user_listed_placeholder_rows"], 8)
            self.assertEqual(summary["user_listed_safe_prototype_rows"], 8)
            focused = {row["event_id"]: row for row in read_tsv(reports / TOOL.EVIDENCE_DIR_NAME / "FOCUSED_FE01_MESSAGE_REVIEW.tsv")}
            self.assertEqual(focused["fe01_130"]["classification"], "japanese_payload_identical_other_language_or_metadata_changed")
            self.assertEqual(
                focused["fe01_200"]["classification"],
                "scene_text_replaced_by_multilingual_dash_placeholders_control_identical",
            )
            records = read_tsv(reports / TOOL.EVIDENCE_DIR_NAME / "FE_EVENT_MESSAGE_RECORD_AUDIT.tsv")
            fe200_jp = [row for row in records if row["event_id"] == "fe01_200" and row["language"] == "event_jp"]
            self.assertEqual(len(fe200_jp), 3)
            self.assertTrue(all(row["target_exact_dash_placeholder"] == "True" for row in fe200_jp))
            self.assertNotIn("source line", json.dumps(summary))


if __name__ == "__main__":
    unittest.main()
