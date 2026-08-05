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
    "collect_friend_event_trigger_graph_evidence",
    WS / "collect_friend_event_trigger_graph_evidence.py",
)
assert spec and spec.loader
TOOL = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = TOOL
spec.loader.exec_module(TOOL)
sys.path.insert(0, str(ROOT / "Blue_Reflection_Text_Tool"))
import br_restoration_tool as BR


def sha(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def ebm(count: int) -> bytes:
    return struct.pack("<I", count) + bytes([count & 0xFF]) * 60


def ebd(count: int) -> bytes:
    return struct.pack("<I", count) + b"EBD!" + bytes([count & 0xFF]) * 56


def offset_table(records: list[bytes]) -> bytes:
    count = len(records)
    table_end = 4 + (count + 1) * 4
    offsets = [table_end]
    for record in records:
        offsets.append(offsets[-1] + len(record))
    return struct.pack("<I", count) + b"".join(struct.pack("<I", value) for value in offsets) + b"".join(records)


def write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")


def read_tsv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


class Stage56Tests(unittest.TestCase):
    def test_offset_table_framing_is_exact(self) -> None:
        payload = offset_table([b"A" * 8, b"B" * 12, b"C" * 16])
        rows = TOOL.offset_table_hypotheses(payload, 3, "source")
        exact = [row for row in rows if row.exact_eof and row.empty_records == 0]
        self.assertTrue(exact)
        self.assertEqual([record.size for record in exact[0].records], [8, 12, 16])

    def test_mapping_support_detects_declared_count_field(self) -> None:
        order = ["a_001", "a_002", "a_003", "a_004"]
        metadata = {event_id: {"ebm_declared_records": value} for event_id, value in zip(order, [5, 7, 50, 9])}
        records = [struct.pack("<III", value, index, 100 + index) for index, value in enumerate([5, 7, 50, 9])]
        rows = TOOL.top_mapping_fields(records=records, order=order, metadata=metadata, metric="ebm_declared_records")
        self.assertTrue(rows)
        self.assertEqual(rows[0]["width"], 1)
        self.assertEqual(rows[0]["offset"], 0)
        self.assertEqual(rows[0]["support_ratio"], 1.0)

    def test_collect_frames_maps_and_reports_fe13_record(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            reports = base / "reports"
            workspace = base / "workspace"
            stage55 = reports / TOOL.STAGE55_DIR_NAME
            write_json(stage55 / "SUMMARY.json", {
                "type": "br_quartet_restoration_friend_event_reachability_evidence_summary",
                "tool_version": "0.0.63",
                "friend_event_slot_rows": 420,
                "source_to_target_message_removed_or_stubbed_rows": 0,
                "source_to_target_ebd_removed_rows": 0,
                "explicit_trigger_reference_removed_rows": 0,
            })

            event_ids = ["ce01_010", "fe13_080", "fe13_090", "fe13_100"]
            ebm_counts = [5, 7, 50, 9]
            ebd_counts = [2, 3, 39, 4]
            source_files = []
            target_files = []
            for event_id, message_count, control_count in zip(event_ids, ebm_counts, ebd_counts):
                family = event_id.split("_")[0]
                for kind, extension, payload in (
                    ("event_message_", ".ebm", ebm(message_count)),
                    ("event_", ".ebd", ebd(control_count)),
                ):
                    name = kind + event_id + extension
                    normalized = f"event/event_jp/{family}/{name}"
                    source_row = {
                        "archive": "DATA/PACK01.PAK", "path": normalized,
                        "normalized_path": normalized, "size": len(payload),
                        "sha256": sha(payload), "extension": extension,
                    }
                    target_path = f"event/b1/event_jp/{family}/{name}"
                    target_row = {
                        "archive": "Data/PACK11.PAK", "path": target_path,
                        "normalized_path": normalized, "size": len(payload),
                        "sha256": sha(payload), "extension": extension,
                    }
                    source_files.append(source_row)
                    target_files.append(target_row)
                    spath = BR.inventory_workspace_file(workspace, "source", "br1_events", source_row["archive"], source_row["path"])
                    tpath = BR.inventory_workspace_file(workspace, "target", "br1_events", target_row["archive"], target_row["path"])
                    spath.parent.mkdir(parents=True, exist_ok=True)
                    tpath.parent.mkdir(parents=True, exist_ok=True)
                    spath.write_bytes(payload)
                    tpath.write_bytes(payload)

            source_records = [
                struct.pack("<III", 5, 2, 2),
                struct.pack("<III", 7, 3, 1),
                struct.pack("<III", 50, 39, 3),
                struct.pack("<III", 9, 4, 0),
            ]
            target_records = [
                struct.pack("<III", 5, 2, 3),  # incoming edge retargeted away from fe13_090
                struct.pack("<III", 7, 3, 1),
                struct.pack("<III", 50, 39, 0),  # fe13_090 record changed
                struct.pack("<III", 9, 4, 0),
            ]
            source_epd = offset_table(source_records)
            target_epd = offset_table(target_records)
            for side, inventory_rows, archive, path, payload in (
                ("source", source_files, "DATA/PACK01.PAK", "event/eventprocess/eventprocessdataall.epd", source_epd),
                ("target", target_files, "Data/PACK11.PAK", "event/b1/eventprocess/eventprocessdataall.epd", target_epd),
            ):
                row = {
                    "archive": archive, "path": path, "normalized_path": TOOL.PROCESS_PATH,
                    "size": len(payload), "sha256": sha(payload), "extension": ".epd",
                }
                inventory_rows.append(row)
                file_path = BR.inventory_workspace_file(workspace, side, "br1_events", archive, path)
                file_path.parent.mkdir(parents=True, exist_ok=True)
                file_path.write_bytes(payload)

            write_json(reports / "inventories/br1_events.source.json", {"archive_group": "br1_events", "files": source_files})
            write_json(reports / "inventories/br1_events.target.json", {"archive_group": "br1_events", "files": target_files})

            output, summary = TOOL.collect(project_root=ROOT, workspace_root=workspace, report_root=reports)
            self.assertTrue(output.is_file())
            self.assertEqual(summary["event_process_count"], 4)
            self.assertIn(summary["framing_status"], {"common_exact_framing_selected", "side_specific_exact_framing_selected"})
            self.assertNotEqual(summary["mapping_status"], "record_to_event_order_unconfirmed")
            self.assertEqual(summary["friend_event_record_rows"], 3)
            self.assertTrue(summary["fe13_090"]["record_changed"])
            self.assertGreaterEqual(int(summary["fe13_090"]["candidate_incoming_retargeted"]), 1)
            focused = read_tsv(reports / TOOL.EVIDENCE_DIR_NAME / "FOCUSED_FRIEND_EVENT_TRIGGER_REVIEW.tsv")
            fe13 = next(row for row in focused if row["event_id"] == "fe13_090")
            self.assertEqual(fe13["record_changed"], "True")

    def test_stage55_fail_closed_on_removed_payload(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            stage55 = base / "reports" / TOOL.STAGE55_DIR_NAME
            write_json(stage55 / "SUMMARY.json", {
                "type": "br_quartet_restoration_friend_event_reachability_evidence_summary",
                "tool_version": "0.0.63",
                "friend_event_slot_rows": 420,
                "source_to_target_message_removed_or_stubbed_rows": 1,
                "source_to_target_ebd_removed_rows": 0,
            })
            with self.assertRaises(TOOL.TriggerGraphError):
                TOOL.collect(project_root=ROOT, workspace_root=base / "workspace", report_root=base / "reports")


if __name__ == "__main__":
    unittest.main()
