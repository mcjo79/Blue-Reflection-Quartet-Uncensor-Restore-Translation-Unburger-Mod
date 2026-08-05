#!/usr/bin/env python3
from __future__ import annotations

import csv
import hashlib
import importlib.util
import json
import shutil
import struct
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
PATH = ROOT / "workstreams/quartet_restoration/collect_reflector_slot_light_g1e_structure_evidence.py"
spec = importlib.util.spec_from_file_location("stage84", PATH)
assert spec and spec.loader
TOOL = importlib.util.module_from_spec(spec)
spec.loader.exec_module(TOOL)


def write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value) + "\n", encoding="utf-8")


def write_tsv(path: Path, fields: list[str], rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def pseudorandom_bytes(length: int, seed: str) -> bytes:
    out = bytearray()
    counter = 0
    while len(out) < length:
        out.extend(hashlib.sha256(f"{seed}:{counter}".encode()).digest())
        counter += 1
    out = out[:length]
    out[0:8] = b"G1FX5200"
    return bytes(out)


def replace_dword(payload: bytes, offset: int, value: int) -> bytes:
    result = bytearray(payload)
    result[offset:offset + 4] = struct.pack("<I", value)
    return bytes(result)


class Stage84PureTests(unittest.TestCase):
    def test_alignment_detects_target_insertion(self):
        source = pseudorandom_bytes(1024, "insert")
        target = source[:400] + b"\0" * 16 + source[400:]
        segments, runs = TOOL.build_alignment_segments(source, target)
        self.assertTrue(runs)
        self.assertTrue(any(row["segment_type"] == "target_insertion" and row["target_length"] == 16 for row in segments))

    def test_alignment_detects_same_size_replacement(self):
        source = pseudorandom_bytes(512, "replace")
        target = replace_dword(source, 128, 0x40000000)
        segments, _runs = TOOL.build_alignment_segments(source, target)
        self.assertTrue(any(row["segment_type"] == "same_size_replacement" for row in segments))

    def test_finite_float_transition_is_unresolved_not_brightness(self):
        source = bytearray(pseudorandom_bytes(256, "float"))
        target = bytearray(source)
        source[128:132] = struct.pack("<f", 1.0)
        target[128:132] = struct.pack("<f", 2.0)
        segment = {
            "source_start": 128, "target_start": 128,
            "source_length": 4, "target_length": 4,
        }
        rows = TOOL.changed_words_for_segment(bytes(source), bytes(target), segment, 0)
        self.assertEqual(rows[0]["transition_classification"], "finite_float_transition_unresolved")

    def test_offset_rebase_is_not_float_lead(self):
        source = struct.pack("<I", 0x280)
        target = struct.pack("<I", 0x290)
        segment = {"source_start": 0, "target_start": 0, "source_length": 4, "target_length": 4}
        rows = TOOL.changed_words_for_segment(source, target, segment, 16)
        self.assertEqual(rows[0]["transition_classification"], "possible_relative_offset_or_length_rebase")

    def test_stage83_validator_requires_zero_residuals(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            summary = {
                "type": "br_quartet_restoration_reflector_ringlight_structural_shift_evidence_summary",
                "tool_version": "0.0.97",
                "status": "common_ringlight_delta_fully_explained_by_uniform_eight_byte_record_compaction_no_brightness_leaf_residual",
                "common_ringlight_member_rows": 15,
                "common_ringlight_changed_dword_rows": 36,
                "model_shift_values": [8],
                "uniform_shift_across_clusters": True,
                "complete_cluster_model_rows": 3,
                "explained_dword_rows": 36,
                "residual_dword_rows": 1,
                "exact_slot_model_rows": 15,
                "brightness_leaf_residual_rows": 0,
                "prototype_candidate_rows": 0,
                "skipped_rows": 0,
            }
            write_json(root / "SUMMARY.json", summary)
            with self.assertRaises(TOOL.Stage84Error):
                TOOL.validate_stage83(root)


class Stage84BuildTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.project = Path(self.tmp.name)
        reports = self.project / ".local/reports/quartet_restoration"
        reports.mkdir(parents=True)
        workstream = self.project / "workstreams/quartet_restoration"
        workstream.mkdir(parents=True)
        shutil.copy2(ROOT / "workstreams/quartet_restoration/collect_reflector_light_family_binary_evidence.py", workstream)
        shutil.copytree(ROOT / "Blue_Reflection_Text_Tool", self.project / "Blue_Reflection_Text_Tool")

        self.scope: list[dict] = []
        for index in range(15):
            self.scope.append({
                "candidate_id": "common", "character_slot": f"PC{index:02d}", "asset_role": "ringlight",
                "family_key": "ringlight:e_cmn_ringlight_PCXX.g1e", "normalized_path": "data/x64/effect/100_common.elixir.gz",
                "member_name": f"e_cmn_ringlight_PC{index:02d}.g1e", "member_key": f"e_cmn_ringlight_pc{index:02d}.g1e#0",
            })
        extras = [
            ("a", "PC00", "ringlight", "ringlight:e_PCXX_ringlight_a.g1e", "data/x64/effect/1000_pc00.elixir.gz"),
            ("b", "PC00", "eyelight", "eyelight:e_PCXX_eyelight_00.g1e", "data/x64/effect/1000_pc00.elixir.gz"),
            ("c", "PC00", "eyelight", "eyelight:e_PCXX_eyelight_01.g1e", "data/x64/effect/1000_pc00.elixir.gz"),
            ("d", "PC01", "ringlight", "ringlight:e_PCXX_h2_ringlight_00.g1e", "data/x64/effect/1001_pc01.elixir.gz"),
            ("e", "PC01", "ringlight", "ringlight:e_PCXX_ringlight_00.g1e", "data/x64/effect/1001_pc01.elixir.gz"),
            ("f", "PC02", "ringlight", "ringlight:e_PCXX_w5_ringlight_01.g1e", "data/x64/effect/1002_pc02.elixir.gz"),
        ]
        self.extra_rows: list[dict] = []
        self.pairs: list[dict] = []
        for idx, (cid, slot, role, family, path) in enumerate(extras):
            row = {
                "candidate_id": cid, "character_slot": slot, "asset_role": role, "family_key": family,
                "normalized_path": path, "member_name": f"member_{cid}.g1e", "member_key": f"member_{cid}.g1e#0",
            }
            self.scope.append(row); self.extra_rows.append(row)
            source = pseudorandom_bytes(768 + idx * 64, cid)
            if cid == "a":
                source = replace_dword(source, 128, 0x3F800000)
                target = replace_dword(source, 128, 0x40000000)
            else:
                insertion = bytes([idx + 1]) * (16 if idx in {3, 4} else 32)
                target = source[:320] + insertion + source[320:]
            self.pairs.append({**row, "source_payload": source, "target_payload": target, "source_member_name": row["member_name"], "target_member_name": row["member_name"]})

        stage79 = reports / TOOL.STAGE79_DIR
        write_json(stage79 / "SUMMARY.json", {
            "type": "br_quartet_restoration_reflector_character_slot_render_member_evidence_summary",
            "tool_version": "0.0.92", "character_slot_rows": 15, "slot_member_rows": 220,
            "ringlight_family_rows": 5, "eyelight_family_rows": 2, "policy": {},
        })
        write_tsv(stage79 / "REFLECTOR_SLOT_RENDER_MEMBERS.tsv", list(self.scope[0]), self.scope)

        stage80 = reports / TOOL.STAGE80_DIR
        write_json(stage80 / "SUMMARY.json", {
            "type": "br_quartet_restoration_reflector_light_family_binary_evidence_summary",
            "tool_version": "0.0.93", "scope_member_rows": 21, "skipped_rows": 0,
        })
        audits = []
        for pair in self.pairs:
            audits.append({
                "normalized_path": pair["normalized_path"], "member_key": pair["member_key"],
                "source_size": len(pair["source_payload"]), "target_size": len(pair["target_payload"]),
                "source_sha256": TOOL.sha256(pair["source_payload"]), "target_sha256": TOOL.sha256(pair["target_payload"]),
                "audit_status": "test_changed",
            })
        write_tsv(stage80 / "REFLECTOR_LIGHT_MEMBER_BINARY_AUDIT.tsv", list(audits[0]), audits)

        stage83 = reports / TOOL.STAGE83_DIR
        write_json(stage83 / "SUMMARY.json", {
            "type": "br_quartet_restoration_reflector_ringlight_structural_shift_evidence_summary",
            "tool_version": "0.0.97",
            "status": "common_ringlight_delta_fully_explained_by_uniform_eight_byte_record_compaction_no_brightness_leaf_residual",
            "common_ringlight_member_rows": 15, "common_ringlight_changed_dword_rows": 36,
            "model_shift_values": [8], "uniform_shift_across_clusters": True,
            "complete_cluster_model_rows": 3, "explained_dword_rows": 36, "residual_dword_rows": 0,
            "exact_slot_model_rows": 15, "brightness_leaf_residual_rows": 0,
            "prototype_candidate_rows": 0, "skipped_rows": 0,
        })

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def pair_loader(self, **kwargs):
        scope = kwargs["scope_rows"]
        wanted = {(row["candidate_id"], row["normalized_path"].casefold(), row["member_key"].casefold()) for row in scope}
        return [pair for pair in self.pairs if (pair["candidate_id"], pair["normalized_path"].casefold(), pair["member_key"].casefold()) in wanted], []

    def test_build_report_audits_six_members_without_prototype(self):
        output, archive, summary = TOOL.build_report(self.project, create_archive=False, pair_loader=self.pair_loader)
        self.assertIsNone(archive)
        self.assertEqual(summary["scope_member_rows"], 6)
        self.assertEqual(summary["ringlight_member_rows"], 4)
        self.assertEqual(summary["eyelight_member_rows"], 2)
        self.assertEqual(summary["prototype_candidate_rows"], 0)
        self.assertTrue(summary["common_ringlight_closed_as_structural_compaction"])
        self.assertTrue((output / "SLOT_LIGHT_ALIGNMENT_SEGMENTS.tsv").is_file())
        self.assertGreater(summary["alignment_segment_rows"], 0)


if __name__ == "__main__":
    unittest.main()
