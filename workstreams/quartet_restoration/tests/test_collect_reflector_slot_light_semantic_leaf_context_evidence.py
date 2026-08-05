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
PATH = ROOT / "workstreams/quartet_restoration/collect_reflector_slot_light_semantic_leaf_context_evidence.py"
spec = importlib.util.spec_from_file_location("stage85", PATH)
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


def payload(seed: int, size: int = 512) -> bytearray:
    out = bytearray((i * 17 + seed * 31) & 0xFF for i in range(size))
    out[0:8] = b"G1FX5200"
    return out


def member(name: str, data: bytes) -> dict:
    return {"name": name, "comparison_key": name.casefold() + "#0", "payload": data}


class PureTests(unittest.TestCase):
    def test_packed_low_word_change_is_not_float_leaf(self):
        self.assertTrue(TOOL.packed_index_like(0x4010002E, 0x4010002D))

    def test_masked_context_finds_center(self):
        data = bytes(range(128))
        pre = data[32:48]
        post = data[52:68]
        self.assertEqual(TOOL.find_masked_context(data, pre, post), [48])

    def test_reverse_transition_or_multiset_blocks_leaf(self):
        source = bytearray(128)
        target = bytearray(128)
        source[32:36] = struct.pack("<f", 1.0)
        source[36:40] = struct.pack("<f", 2.0)
        target[32:36] = struct.pack("<f", 2.0)
        target[36:40] = struct.pack("<f", 1.0)
        row = {
            "source_u32_hex": "0x3f800000", "target_u32_hex": "0x40000000",
            "source_offset": "32", "target_offset": "32", "source_float32": "1", "target_float32": "2",
            "transition_id": "a",
        }
        reverse = {**row, "source_u32_hex": "0x40000000", "target_u32_hex": "0x3f800000", "source_offset": "36", "target_offset": "36"}
        segment = {"source_start": "32", "source_end_exclusive": "40", "target_start": "32", "target_end_exclusive": "40", "segment_type": "same_size_replacement"}
        result = TOOL.classify_float_lead(row, source_payload=bytes(source), target_payload=bytes(target), segment=segment, finite_rows_for_member=[row, reverse])
        self.assertEqual(result["lead_classification"], "record_permutation_or_reordering_not_leaf")


class BuildTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.project = Path(self.tmp.name)
        reports = self.project / ".local/reports/quartet_restoration"
        reports.mkdir(parents=True)
        workstream = self.project / "workstreams/quartet_restoration"
        workstream.mkdir(parents=True)
        shutil.copy2(ROOT / "workstreams/quartet_restoration/collect_reflector_light_family_binary_evidence.py", workstream)
        shutil.copy2(ROOT / "workstreams/quartet_restoration/collect_reflector_ringlight_control_callsite_evidence.py", workstream)
        shutil.copytree(ROOT / "Blue_Reflection_Text_Tool", self.project / "Blue_Reflection_Text_Tool")

        common = []
        for index in range(15):
            common.append({
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
        self.extra_rows = []
        self.pairs = {}
        for idx, (cid, slot, role, family, path) in enumerate(extras):
            name = f"member_{cid}.g1e"
            row = {
                "candidate_id": cid, "character_slot": slot, "asset_role": role, "family_key": family,
                "normalized_path": path, "member_name": name, "member_key": name.casefold() + "#0",
            }
            self.extra_rows.append(row)
            left = payload(idx + 1)
            right = bytearray(left)
            if cid == "f":
                left[256:260] = struct.pack("<f", 150.0)
                right[256:260] = struct.pack("<f", 75.0)
            elif cid == "a":
                left[256:260] = struct.pack("<I", 0x4010002E)
                right[256:260] = struct.pack("<I", 0x4010002D)
            self.pairs[(path.casefold(), row["member_key"].casefold())] = (bytes(left), bytes(right), name)

        stage79 = reports / TOOL.STAGE79_DIR
        write_json(stage79 / "SUMMARY.json", {
            "type": "br_quartet_restoration_reflector_character_slot_render_member_evidence_summary",
            "tool_version": "0.0.92", "character_slot_rows": 15, "slot_member_rows": 220,
            "ringlight_family_rows": 5, "eyelight_family_rows": 2,
            "policy": {"installed_game_modified": False, "render_payload_written": False, "pak_repacked": False, "core_registry_modified": False, "profile_activated": False},
        })
        scope = common + self.extra_rows
        write_tsv(stage79 / "REFLECTOR_SLOT_RENDER_MEMBERS.tsv", list(scope[0]), scope)

        stage84 = reports / TOOL.STAGE84_DIR
        write_json(stage84 / "SUMMARY.json", {
            "type": "br_quartet_restoration_reflector_slot_light_g1e_structure_evidence_summary",
            "tool_version": "0.0.98",
            "status": "non_common_reflector_light_members_structurally_aligned_semantic_brightness_values_not_yet_resolved",
            "scope_member_rows": 6, "finite_float_lead_rows": 62, "prototype_candidate_rows": 0,
            "skipped_rows": 0, "common_ringlight_closed_as_structural_compaction": True,
        })
        audits = []
        segments = []
        finite = []
        dwords = []
        for row in self.extra_rows:
            left, right, name = self.pairs[(row["normalized_path"].casefold(), row["member_key"].casefold())]
            audits.append({**row, "source_size": len(left), "target_size": len(right), "size_delta": 0,
                           "source_sha256": TOOL.sha256(left), "target_sha256": TOOL.sha256(right)})
            segment_id = row["candidate_id"] + "_seg"
            segments.append({**row, "segment_id": segment_id, "segment_type": "same_size_replacement",
                             "source_start": 240, "source_end_exclusive": 272,
                             "target_start": 240, "target_end_exclusive": 272})
        candidate = next(row for row in self.extra_rows if row["candidate_id"] == "f")
        for index in range(62):
            if index == 0:
                row = candidate
                s_hex, t_hex, sf, tf = "0x43160000", "0x42960000", "150", "75"
            else:
                row = next(item for item in self.extra_rows if item["candidate_id"] == "a")
                s_hex, t_hex, sf, tf = "0x4010002e", "0x4010002d", "2.25001097", "2.25001073"
            finite.append({**row, "segment_id": row["candidate_id"] + "_seg", "source_offset": 256, "target_offset": 256,
                           "relative_offset": 16, "source_u32_hex": s_hex, "target_u32_hex": t_hex,
                           "source_float32": sf, "target_float32": tf, "transition_id": f"t{index}",
                           "transition_classification": "finite_float_transition_unresolved"})
            dwords.append(finite[-1])
        write_tsv(stage84 / "SLOT_LIGHT_MEMBER_STRUCTURE_AUDIT.tsv", list(audits[0]), audits)
        write_tsv(stage84 / "SLOT_LIGHT_ALIGNMENT_SEGMENTS.tsv", list(segments[0]), segments)
        write_tsv(stage84 / "SLOT_LIGHT_FINITE_FLOAT_LEADS.tsv", list(finite[0]), finite)
        write_tsv(stage84 / "SLOT_LIGHT_ALIGNED_CHANGED_DWORDS.tsv", list(dwords[0]), dwords)

        # Stable sibling record with the same masked context but unchanged value.
        left, _right, _name = self.pairs[(candidate["normalized_path"].casefold(), candidate["member_key"].casefold())]
        sibling_source = bytearray(left)
        sibling_target = bytearray(left)
        sibling_source[256:260] = struct.pack("<f", 100.0)
        sibling_target[256:260] = struct.pack("<f", 100.0)
        self.sibling = (bytes(sibling_source), bytes(sibling_target))

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def loader(self, **kwargs):
        containers = []
        for path in [
            "data/x64/effect/1000_pc00.elixir.gz",
            "data/x64/effect/1001_pc01.elixir.gz",
            "data/x64/effect/1002_pc02.elixir.gz",
            "data/x64/effect/100_common.elixir.gz",
        ]:
            source_members = []
            target_members = []
            for (member_path, key), (left, right, name) in self.pairs.items():
                if member_path != path:
                    continue
                source_members.append(member(name, left))
                target_members.append(member(name, right))
            if path.endswith("1002_pc02.elixir.gz"):
                source_members.append(member("neutral_control.g1e", self.sibling[0]))
                target_members.append(member("neutral_control.g1e", self.sibling[1]))
            containers.append({"normalized_path": path, "source_members": source_members, "target_members": target_members})
        return containers, []

    def test_build_isolates_candidate_and_finds_stable_sibling(self):
        output, archive, summary = TOOL.build_report(self.project, create_archive=False, container_loader=self.loader)
        self.assertIsNone(archive)
        self.assertEqual(summary["finite_float_input_rows"], 62)
        self.assertEqual(summary["semantic_leaf_candidate_rows"], 1)
        self.assertGreaterEqual(summary["stable_value_sibling_rows"], 1)
        self.assertEqual(summary["prototype_candidate_rows"], 0)
        self.assertTrue((output / "SLOT_LIGHT_SEMANTIC_LEAF_CANDIDATES.tsv").is_file())


if __name__ == "__main__":
    unittest.main()
