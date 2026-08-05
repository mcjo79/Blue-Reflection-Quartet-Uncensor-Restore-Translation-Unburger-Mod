#!/usr/bin/env python3
from __future__ import annotations

import csv
import importlib.util
import json
import struct
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
PATH = ROOT / "workstreams/quartet_restoration/collect_reflector_ringlight_control_callsite_evidence.py"
spec = importlib.util.spec_from_file_location("stage81", PATH)
assert spec and spec.loader
TOOL = importlib.util.module_from_spec(spec)
spec.loader.exec_module(TOOL)


def write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data) + "\n", encoding="utf-8")


def write_tsv(path: Path, fields: list[str], rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def member(name: str, key: str, payload: bytes) -> dict:
    return {
        "name": name,
        "comparison_key": key,
        "payload": payload,
        "sha256": TOOL.sha256(payload),
        "extension": Path(name).suffix.casefold(),
    }


class Stage81Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.project = Path(self.tmp.name)
        self.reports = self.project / ".local/reports/quartet_restoration"
        self.reports.mkdir(parents=True)

        stage79 = self.reports / TOOL.STAGE79_DIR
        write_json(stage79 / "SUMMARY.json", {
            "type": "br_quartet_restoration_reflector_character_slot_render_member_evidence_summary",
            "tool_version": "0.0.92", "character_slot_rows": 15,
        })
        self.scope: list[dict] = []
        for index in range(15):
            self.scope.append({
                "character_slot": f"PC{index:02d}", "asset_role": "ringlight",
                "family_key": TOOL.COMMON_FAMILY_KEY,
                "normalized_path": "data/x64/effect/100_common.elixir.gz",
                "member_name": f"e_cmn_ringlight_PC{index:02d}.g1e",
                "member_key": f"e_cmn_ringlight_pc{index:02d}.g1e#0",
                "candidate_id": "common",
            })
        extras = [
            ("PC00", "ringlight", "a", "data/x64/effect/1000_pc00.elixir.gz"),
            ("PC00", "eyelight", "b", "data/x64/effect/1000_pc00.elixir.gz"),
            ("PC01", "ringlight", "c", "data/x64/effect/1001_pc01.elixir.gz"),
            ("PC01", "eyelight", "d", "data/x64/effect/1001_pc01.elixir.gz"),
            ("PC02", "ringlight", "e", "data/x64/effect/1002_pc02.elixir.gz"),
            ("PC02", "ringlight", "f", "data/x64/effect/1002_pc02.elixir.gz"),
        ]
        for slot, role, suffix, path in extras:
            self.scope.append({
                "character_slot": slot, "asset_role": role,
                "family_key": f"{role}:extra_{suffix}", "normalized_path": path,
                "member_name": f"extra_{suffix}.g1e", "member_key": f"extra_{suffix}.g1e#0",
                "candidate_id": suffix,
            })
        write_tsv(stage79 / "REFLECTOR_SLOT_RENDER_MEMBERS.tsv", list(self.scope[0]), self.scope)

        stage80 = self.reports / TOOL.STAGE80_DIR
        write_json(stage80 / "SUMMARY.json", {
            "type": "br_quartet_restoration_reflector_light_family_binary_evidence_summary",
            "tool_version": "0.0.93", "common_ringlight_member_rows": 15,
            "common_ringlight_family_classification": "uniform_exact_delta_across_slots",
            "skipped_rows": 0, "policy": {},
        })

        self.common_source: dict[str, bytes] = {}
        self.common_target: dict[str, bytes] = {}
        audit_rows: list[dict] = []
        for row in self.scope:
            source = bytearray(64)
            target = bytearray(64)
            source[16:20] = struct.pack("<f", 1.0)
            target[16:20] = struct.pack("<f", 2.0)
            source[20:24] = struct.pack("<f", 0.5)
            target[20:24] = struct.pack("<f", 1.0)
            slot_value = int(row["character_slot"][2:])
            source[4] = target[4] = slot_value
            source_bytes = bytes(source); target_bytes = bytes(target)
            self.common_source[row["member_key"]] = source_bytes
            self.common_target[row["member_key"]] = target_bytes
            audit_rows.append({
                "normalized_path": row["normalized_path"],
                "member_key": row["member_key"], "source_sha256": TOOL.sha256(source_bytes),
                "target_sha256": TOOL.sha256(target_bytes), "exact_source_inverse": True,
                "exact_target_roundtrip": True,
            })
        write_tsv(stage80 / "REFLECTOR_LIGHT_MEMBER_BINARY_AUDIT.tsv", list(audit_rows[0]), audit_rows)

        stage78 = self.reports / TOOL.STAGE78_DIR
        write_json(stage78 / "SUMMARY.json", {
            "type": "br_quartet_restoration_all_reflector_transformation_family_evidence_summary",
            "tool_version": "0.0.91", "event_rows": 68, "changed_event_rows": 1,
        })
        event_rows: list[dict] = []
        for index in range(68):
            event_rows.append({
                "normalized_path": f"event/skill/test_rfl_{index}.ebd", "event_kind": "party",
                "family_id": "party:test", "family_name": "test", "slot": index,
                "classification": "changed" if index == 0 else "identical",
                "source_sha256": "", "target_sha256": "",
            })
        write_tsv(stage78 / "ALL_REFLECTOR_TRANSFORMATION_EVENTS.tsv", list(event_rows[0]), event_rows)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def container_loader(self, **kwargs):
        del kwargs
        containers = []
        grouped: dict[str, list[dict]] = {}
        for row in self.scope:
            grouped.setdefault(row["normalized_path"], []).append(row)
        for path, rows in sorted(grouped.items()):
            source_members = []
            target_members = []
            for row in rows:
                source = self.common_source[row["member_key"]]
                target = self.common_target[row["member_key"]]
                source_members.append(member(row["member_name"], row["member_key"], source))
                target_members.append(member(row["member_name"], row["member_key"], target))
            if path.endswith("100_common.elixir.gz"):
                neutral_source = bytearray(64); neutral_target = bytearray(64)
                neutral_source[8:12] = struct.pack("<f", 1.0)
                neutral_target[8:12] = struct.pack("<f", 2.0)
                source_members.append(member("e_idle_control.g1e", "e_idle_control.g1e#0", bytes(neutral_source)))
                target_members.append(member("e_idle_control.g1e", "e_idle_control.g1e#0", bytes(neutral_target)))
                ref_payload = b"prefix:e_cmn_ringlight_PC00.g1e:suffix"
                source_members.append(member("e_reference.g1e", "e_reference.g1e#0", ref_payload))
                target_members.append(member("e_reference.g1e", "e_reference.g1e#0", ref_payload))
            containers.append({
                "candidate_id": rows[0]["candidate_id"], "normalized_path": path,
                "scope_rows": rows, "source_members": source_members, "target_members": target_members,
            })
        return containers, []

    def event_loader(self, **kwargs):
        del kwargs
        rows = []
        for index in range(68):
            payload = b"none"
            if index == 0:
                payload = "e_cmn_ringlight_PC00".encode("utf-16le")
            rows.append({
                "normalized_path": f"event/skill/test_rfl_{index}.ebd", "family_id": "party:test",
                "family_name": "test", "slot": index, "classification": "changed" if index == 0 else "identical",
                "source_payload": payload, "target_payload": payload,
            })
        return rows, []

    def test_aligned_word_delta_decodes_float(self):
        source = bytearray(8); target = bytearray(8)
        source[4:8] = struct.pack("<f", 1.0); target[4:8] = struct.pack("<f", 2.0)
        rows = TOOL.aligned_word_deltas(bytes(source), bytes(target))
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["word_offset"], 4)
        self.assertEqual(rows[0]["source_float32"], "1")
        self.assertEqual(rows[0]["target_float32"], "2")

    def test_reference_scanner_finds_ascii_and_utf16(self):
        tokens = TOOL.reference_tokens(self.scope[:15])
        payload = b"e_cmn_ringlight_PC00.g1e" + "e_cmn_ringlight_PC01".encode("utf-16le")
        hits = TOOL.scan_references(payload, tokens)
        self.assertTrue(any(row["referenced_slot"] == "PC00" and row["encoding"] == "ascii" for row in hits))
        self.assertTrue(any(row["referenced_slot"] == "PC01" and row["encoding"] == "utf16le" for row in hits))

    def test_build_reports_neutral_overlap_and_exact_references(self):
        output, archive, summary = TOOL.build_report(
            self.project, create_archive=False,
            container_loader=self.container_loader, event_loader=self.event_loader,
        )
        self.assertIsNone(archive)
        self.assertEqual(summary["common_ringlight_member_rows"], 15)
        self.assertEqual(summary["common_ringlight_aligned_word_rows"], 2)
        self.assertGreater(summary["neutral_control_transition_match_rows"], 0)
        self.assertGreater(summary["container_nonself_exact_reference_rows"], 0)
        self.assertGreater(summary["transformation_event_exact_reference_rows"], 0)
        self.assertEqual(summary["prototype_candidate_rows"], 0)
        self.assertTrue((output / "COMMON_RINGLIGHT_ALIGNED_WORD_TRANSITIONS.tsv").is_file())

    def test_stage80_audit_identity_matches_real_schema_without_candidate_id(self):
        stage80 = self.reports / TOOL.STAGE80_DIR / "REFLECTOR_LIGHT_MEMBER_BINARY_AUDIT.tsv"
        rows = TOOL.read_tsv(stage80)
        self.assertNotIn("candidate_id", rows[0])
        output, archive, summary = TOOL.build_report(
            self.project, create_archive=False,
            container_loader=self.container_loader, event_loader=self.event_loader,
        )
        self.assertIsNone(archive)
        self.assertEqual(summary["common_ringlight_member_rows"], 15)
        self.assertTrue((output / "COMMON_RINGLIGHT_ALIGNED_WORD_TRANSITIONS.tsv").is_file())

    def test_duplicate_stage80_path_member_identity_rejected(self):
        stage80 = self.reports / TOOL.STAGE80_DIR / "REFLECTOR_LIGHT_MEMBER_BINARY_AUDIT.tsv"
        rows = TOOL.read_tsv(stage80)
        rows.append(dict(rows[0]))
        write_tsv(stage80, list(rows[0]), rows)
        with self.assertRaises(TOOL.Stage81Error):
            TOOL.build_report(
                self.project, create_archive=False,
                container_loader=self.container_loader, event_loader=self.event_loader,
            )

    def test_nonuniform_common_word_profile_rejected(self):
        original = self.common_target["e_cmn_ringlight_pc01.g1e#0"]
        changed = bytearray(original); changed[20:24] = struct.pack("<f", 3.0)
        self.common_target["e_cmn_ringlight_pc01.g1e#0"] = bytes(changed)
        stage80 = self.reports / TOOL.STAGE80_DIR / "REFLECTOR_LIGHT_MEMBER_BINARY_AUDIT.tsv"
        rows = TOOL.read_tsv(stage80)
        for row in rows:
            if row["member_key"] == "e_cmn_ringlight_pc01.g1e#0":
                row["target_sha256"] = TOOL.sha256(bytes(changed))
        write_tsv(stage80, list(rows[0]), rows)
        with self.assertRaises(TOOL.Stage81Error):
            TOOL.build_report(self.project, create_archive=False, container_loader=self.container_loader, event_loader=self.event_loader)


if __name__ == "__main__":
    unittest.main()
