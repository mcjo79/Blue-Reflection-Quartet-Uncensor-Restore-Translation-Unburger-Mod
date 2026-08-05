#!/usr/bin/env python3
from __future__ import annotations

import csv
import hashlib
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
TOOL_PATH = ROOT / "workstreams/quartet_restoration/collect_reflector_slot_light_section_cardinality_record_role_evidence.py"
spec = importlib.util.spec_from_file_location("stage91", TOOL_PATH)
assert spec and spec.loader
TOOL = importlib.util.module_from_spec(spec)
spec.loader.exec_module(TOOL)


def write_tsv(path: Path, fields: list[str], rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def set_u32(data: bytearray, offset: int, value: int) -> None:
    data[offset:offset + 4] = int(value & 0xFFFFFFFF).to_bytes(4, "little")


def set_header(data: bytearray, endpoint: int, count: int, span: int, table_seed: int) -> None:
    words = [
        span, 0, count, count, count, 2, 56,
        56 + 4 * (count - 1),
        56 + 8 * (count - 1),
        56 + 12 * (count - 1),
        0x00010000, 0x3DCCCCCD, 0, 0x3F800000,
    ]
    for index, value in enumerate(words):
        set_u32(data, endpoint + index * 4, value)
    cursor = endpoint + 56
    for table_index in range(3):
        for entry_index in range(count - 1):
            set_u32(data, cursor, table_seed + table_index * 0x100 + entry_index * 4)
            cursor += 4


def put_reference(data: bytearray, endpoint: int, reference_offset: int) -> None:
    set_u32(data, reference_offset, (endpoint - reference_offset) & 0xFFFFFFFF)


def put_record(data: bytearray, start: int, endpoint: int, first: int) -> None:
    words = [first, first, 1, 2, 3, 4, 5, 6, 7, 8, (endpoint - (start + 40)) & 0xFFFFFFFF]
    for index, value in enumerate(words):
        set_u32(data, start + index * 4, value)


def add_plain_references(data: bytearray, endpoint: int, count: int, start: int, step: int = 64) -> list[int]:
    offsets = []
    for index in range(count):
        offset = start + index * step
        put_reference(data, endpoint, offset)
        offsets.append(offset)
    return offsets


def make_dummy_pair(name: str, size: int = 256) -> tuple[dict[str, object], dict[str, object]]:
    payload = bytes(size)
    key = name.casefold() + "#0"
    return (
        {"comparison_key": key, "name": name, "payload": payload},
        {"comparison_key": key, "name": name, "payload": payload},
    )


class HelperTests(unittest.TestCase):
    def test_lcs_length(self):
        self.assertEqual(TOOL.lcs_length([1, 2], [1, 9, 2]), 2)

    def test_masked_reference_record_uses_last_dword(self):
        payload = bytearray(128)
        put_record(payload, 32, 8, 150)
        start, masked, words = TOOL.masked_reference_record(bytes(payload), 72)
        self.assertEqual(start, 32)
        self.assertEqual(words[:2], [150, 150])
        self.assertEqual(masked[-4:], b"\0\0\0\0")


class SyntheticStage91Report(unittest.TestCase):
    def test_build_report_separates_shared_record_transition_from_count_delta(self):
        with tempfile.TemporaryDirectory(prefix="stage91-test-") as temp_name:
            temp = Path(temp_name)
            reports = temp / "reports"
            workspace = temp / "workspace"
            reports.mkdir()
            workspace.mkdir()

            stage79 = reports / TOOL.STAGE79_DIR
            stage79.mkdir()
            (stage79 / "SUMMARY.json").write_text(json.dumps({
                "type": "br_quartet_restoration_reflector_character_slot_render_member_evidence_summary",
                "tool_version": "0.0.92",
                "character_slot_rows": 15,
            }), encoding="utf-8")
            scope_rows = [{
                "candidate_id": f"c{index}",
                "normalized_path": f"data/x64/effect/fake{index % 4}.elixir.gz",
                "member_key": f"scope_{index}.g1e#0",
                "member_name": f"scope_{index}.g1e",
                "asset_role": "ringlight" if index < 19 else "eyelight",
            } for index in range(21)]
            write_tsv(stage79 / "REFLECTOR_SLOT_RENDER_MEMBERS.tsv", list(scope_rows[0]), scope_rows)

            candidate_path = "data/x64/effect/1002_pc02.elixir.gz"
            candidate_key = "candidate.g1e#0"
            neutral_path = "data/x64/effect/100_common.elixir.gz"
            neutral_key = "neutral.g1e#0"
            eye_path = "data/x64/effect/1000_pc00.elixir.gz"
            eye1_key = "eye1.g1e#0"
            eye2_key = "eye2.g1e#0"

            candidate_source = bytearray(4096)
            candidate_target = bytearray(4096)
            set_header(candidate_source, 128, 3, 3000, 0x200)
            set_header(candidate_target, 128, 4, 3200, 0x200)
            put_record(candidate_source, 512, 128, 150)
            put_record(candidate_target, 528, 128, 75)
            source_candidate_refs = [552] + add_plain_references(candidate_source, 128, 10, 800)
            target_candidate_refs = [568] + add_plain_references(candidate_target, 128, 13, 800)
            self.assertEqual(len(source_candidate_refs), 11)
            self.assertEqual(len(target_candidate_refs), 14)

            neutral_source = bytearray(4096)
            neutral_target = bytearray(4096)
            set_header(neutral_source, 64, 5, 3600, 0x300)
            set_header(neutral_target, 64, 5, 3600, 0x300)
            put_record(neutral_source, 512, 64, 150)
            put_record(neutral_target, 528, 64, 75)
            source_neutral_refs = [552] + add_plain_references(neutral_source, 64, 39, 800)
            target_neutral_refs = [568] + add_plain_references(neutral_target, 64, 39, 800)
            self.assertEqual(len(source_neutral_refs), 40)
            self.assertEqual(len(target_neutral_refs), 40)

            eye_members = []
            for index, name in enumerate(("eye1.g1e", "eye2.g1e"), 1):
                source = bytearray(2048)
                target = bytearray(2048)
                set_header(source, 64, 2, 1800, 0x400 + index * 0x20)
                set_header(target, 64, 2, 1800, 0x400 + index * 0x20)
                add_plain_references(source, 64, 18, 256)
                add_plain_references(target, 64, 18, 256)
                eye_members.append((name, source, target))

            stage87 = reports / TOOL.STAGE87_DIR
            stage87.mkdir()
            islands = [
                {"island_role": "candidate_ringlight", "normalized_path": candidate_path, "member_key": candidate_key, "member_name": "candidate.g1e", "source_start": 512, "source_end_exclusive": 556, "target_start": 528, "target_end_exclusive": 572},
                {"island_role": "neutral_control", "normalized_path": neutral_path, "member_key": neutral_key, "member_name": "neutral.g1e", "source_start": 512, "source_end_exclusive": 556, "target_start": 528, "target_end_exclusive": 572},
            ]
            write_tsv(stage87 / "SLOT_LIGHT_LOCAL_CHANGE_ISLANDS.tsv", list(islands[0]), islands)

            # Stage 89 only needs to exist because stage 91 preserves the explicit prerequisite chain.
            (reports / TOOL.STAGE89_DIR).mkdir()

            def masked_hash(payload: bytes, start: int) -> str:
                record = bytearray(payload[start:start + 44])
                record[40:44] = b"\0\0\0\0"
                return hashlib.sha256(record).hexdigest()

            source_focal_hash = masked_hash(candidate_source, 512)
            target_focal_hash = masked_hash(candidate_target, 528)
            self.assertEqual(source_focal_hash, masked_hash(neutral_source, 512))
            self.assertEqual(target_focal_hash, masked_hash(neutral_target, 528))

            stage90 = reports / TOOL.STAGE90_DIR
            stage90.mkdir()
            (stage90 / "SUMMARY.json").write_text(json.dumps({
                "type": "br_quartet_restoration_reflector_slot_light_target_section_layout_evidence_summary",
                "tool_version": "0.1.4",
                "sibling_G1E_G1EM_member_rows": 540,
                "reference_cluster_member_rows": 4,
                "reference_origin_rows": 177,
                "dword_start_exact_header_rows": 177,
                "dword_end_exact_header_rows": 0,
                "section_header_member_side_rows": 8,
                "section_header_exact_layout_rows": 8,
                "exact_field_origin_resolved": True,
                "resolved_field_origin": "dword_start_relative",
                "masked_record_template_exact_across_candidate_and_neutral": True,
                "shared_transition_candidate_specific": False,
                "prototype_candidate_rows": 0,
                "brightness_semantics_confirmed": False,
                "censorship_semantics_confirmed": False,
                "skipped_rows": 0,
                "policy": {"installed_game_modified": False, "render_payload_written": False, "pak_repacked": False, "core_registry_modified": False, "profile_activated": False},
            }), encoding="utf-8")
            header_rows = []
            members = [
                ("candidate_ringlight", candidate_path, candidate_key, "candidate.g1e", 128, 3, 4, 11, 14),
                ("neutral_control", neutral_path, neutral_key, "neutral.g1e", 64, 5, 5, 40, 40),
                ("neutral_control", eye_path, eye1_key, "eye1.g1e", 64, 2, 2, 18, 18),
                ("neutral_control", eye_path, eye2_key, "eye2.g1e", 64, 2, 2, 18, 18),
            ]
            for role, path, key, name, endpoint, scount, tcount, srefs, trefs in members:
                header_rows.append({"cluster_role": role, "normalized_path": path, "member_key": key, "member_name": name, "side": "source", "endpoint": endpoint, "count": scount, "inbound_reference_rows": srefs})
                header_rows.append({"cluster_role": role, "normalized_path": path, "member_key": key, "member_name": name, "side": "target", "endpoint": endpoint, "count": tcount, "inbound_reference_rows": trefs})
            write_tsv(stage90 / "SLOT_LIGHT_SECTION_HEADER_LAYOUT.tsv", list(header_rows[0]), header_rows)
            origin_rows = [{"row": index} for index in range(177)]
            write_tsv(stage90 / "SLOT_LIGHT_REFERENCE_ORIGIN_DISCRIMINATION.tsv", ["row"], origin_rows)
            bindings = [
                {"island_role": "candidate_ringlight", "member_name": "candidate.g1e", "source_record_masked_sha256": source_focal_hash, "target_record_masked_sha256": target_focal_hash, "shared_non_relocation_transition_count": 2},
                {"island_role": "neutral_control", "member_name": "neutral.g1e", "source_record_masked_sha256": source_focal_hash, "target_record_masked_sha256": target_focal_hash, "shared_non_relocation_transition_count": 2},
            ]
            write_tsv(stage90 / "SLOT_LIGHT_SHARED_RECORD_HEADER_BINDING.tsv", list(bindings[0]), bindings)

            containers = [
                {"normalized_path": candidate_path, "source_members": [{"comparison_key": candidate_key, "name": "candidate.g1e", "payload": bytes(candidate_source)}], "target_members": [{"comparison_key": candidate_key, "name": "candidate.g1e", "payload": bytes(candidate_target)}]},
                {"normalized_path": neutral_path, "source_members": [{"comparison_key": neutral_key, "name": "neutral.g1e", "payload": bytes(neutral_source)}], "target_members": [{"comparison_key": neutral_key, "name": "neutral.g1e", "payload": bytes(neutral_target)}]},
                {"normalized_path": eye_path, "source_members": [], "target_members": []},
                {"normalized_path": "data/x64/effect/dummies.elixir.gz", "source_members": [], "target_members": []},
            ]
            for name, source, target in eye_members:
                key = name.casefold() + "#0"
                containers[2]["source_members"].append({"comparison_key": key, "name": name, "payload": bytes(source)})
                containers[2]["target_members"].append({"comparison_key": key, "name": name, "payload": bytes(target)})
            for index in range(536):
                left, right = make_dummy_pair(f"dummy_{index:03d}.g1e")
                containers[3]["source_members"].append(left)
                containers[3]["target_members"].append(right)

            def fake_loader(**_kwargs):
                return containers, []

            output, archive, summary = TOOL.build_report(
                ROOT,
                create_archive=False,
                workspace_root=workspace,
                report_root=reports,
                container_loader=fake_loader,
            )
            self.assertIsNone(archive)
            self.assertEqual(summary["reference_record_rows"], 177)
            self.assertEqual(summary["section_count_delta_member_rows"], 1)
            self.assertEqual(summary["section_count_unchanged_member_rows"], 3)
            self.assertEqual(summary["reference_delta_equals_three_table_entry_delta_member_rows"], 4)
            self.assertTrue(summary["reference_delta_equals_three_table_entry_delta_all_members"])
            self.assertEqual(summary["shared_record_transition_distinct_count_delta_values"], 2)
            self.assertTrue(summary["shared_record_transition_independent_of_section_count_delta"])
            self.assertEqual(summary["record_structural_role"], "11_dword_section_header_reference_record")
            self.assertFalse(summary["technical_leaf_semantics_resolved"])
            self.assertEqual(summary["prototype_candidate_rows"], 0)
            self.assertFalse(summary["brightness_semantics_confirmed"])
            self.assertTrue((output / "SLOT_LIGHT_SECTION_TABLE_ENTRIES.tsv").is_file())
            self.assertTrue((output / "SLOT_LIGHT_SHARED_RECORD_TRANSITION_CARDINALITY.tsv").is_file())


if __name__ == "__main__":
    unittest.main()
