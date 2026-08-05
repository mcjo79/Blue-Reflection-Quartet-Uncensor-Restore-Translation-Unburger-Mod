#!/usr/bin/env python3
from __future__ import annotations

import csv
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
TOOL_PATH = ROOT / "workstreams/quartet_restoration/collect_reflector_slot_light_anchored_block_internal_change_evidence.py"
spec = importlib.util.spec_from_file_location("stage96", TOOL_PATH)
assert spec and spec.loader
TOOL = importlib.util.module_from_spec(spec)
spec.loader.exec_module(TOOL)


def write_tsv(path: Path, fields: list[str], rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


class Stage96Tests(unittest.TestCase):
    def test_full_synthetic_internal_change_audit(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            temp = Path(name)
            reports = temp / "reports"
            stage79 = reports / "reflector_character_slot_render_member_evidence"
            stage95 = reports / "reflector_slot_light_anchored_block_envelope_evidence"
            stage79.mkdir(parents=True)
            stage95.mkdir(parents=True)

            (stage79 / "SUMMARY.json").write_text(json.dumps({
                "type": "br_quartet_restoration_reflector_character_slot_render_member_evidence_summary",
                "tool_version": "0.0.92",
                "character_slot_rows": 15,
            }), encoding="utf-8")
            render_rows = [{
                "candidate_id": f"c{i}",
                "normalized_path": f"data/x64/effect/container{i % 4}.elixir.gz",
                "member_key": f"m{i}.g1e#0",
                "asset_role": "ringlight" if i < 19 else "eyelight",
            } for i in range(21)]
            write_tsv(stage79 / "REFLECTOR_SLOT_RENDER_MEMBERS.tsv", ["candidate_id", "normalized_path", "member_key", "asset_role"], render_rows)

            (stage95 / "SUMMARY.json").write_text(json.dumps({
                "type": "br_quartet_restoration_reflector_slot_light_anchored_block_envelope_evidence_summary",
                "tool_version": "0.1.9",
                "sibling_G1E_G1EM_member_rows": 540,
                "focal_occurrence_rows": 21,
                "pairwise_comparison_rows": 5,
                "anchored_block_span_field_confirmed": True,
                "block_prefix_geometry_confirmed": True,
                "candidate_target_occurrence_identity_resolved": False,
                "prototype_candidate_rows": 0,
                "brightness_semantics_confirmed": False,
                "censorship_semantics_confirmed": False,
                "skipped_rows": 0,
            }), encoding="utf-8")

            candidate_path = "data/x64/effect/container0.elixir.gz"
            candidate_key = "e_pc02_w5_ringlight_01.g1e#0"
            neutral_path = "data/x64/effect/container1.elixir.gz"
            neutral_key = "e_cmn_pup_reflect_s.g1e#0"
            eye0_path = "data/x64/effect/container2.elixir.gz"
            eye0_key = "e_pc00_eyelight_00.g1e#0"
            eye1_path = "data/x64/effect/container3.elixir.gz"
            eye1_key = "e_pc00_eyelight_01.g1e#0"

            candidate_source = [(1000, "equal_float_30"), (1608, "equal_float_150"), (2216, "equal_float_2")]
            candidate_target = [(1016, "equal_float_30"), (1624, "equal_float_75"), (2232, "equal_float_75"), (2840, "equal_float_2")]
            neutral = [(400, "equal_float_1", 560), (960, "equal_float_100", 640), (1600, "equal_float_50", 640), (2240, "equal_float_150", 640), (2880, "equal_float_75", 640)]
            eyes = [(320, "equal_float_1", 560)]

            layout_fields = [
                "cluster_role", "normalized_path", "member_key", "member_name", "side", "reference_index", "variant_label",
                "endpoint", "anchor", "record_start", "reference_offset", "declared_block_span",
            ]
            layout_rows: list[dict[str, object]] = []

            def add_rows(role: str, path: str, key: str, side: str, values: list[tuple[int, str, int]]) -> None:
                for index, (anchor, variant, span) in enumerate(values):
                    record = anchor + 108
                    layout_rows.append({
                        "cluster_role": role, "normalized_path": path, "member_key": key, "member_name": key.split("#")[0],
                        "side": side, "reference_index": index, "variant_label": variant, "endpoint": 192,
                        "anchor": anchor, "record_start": record, "reference_offset": record + 40, "declared_block_span": span,
                    })

            add_rows("candidate_ringlight", candidate_path, candidate_key, "source", [(a, v, 608) for a, v in candidate_source])
            add_rows("candidate_ringlight", candidate_path, candidate_key, "target", [(a, v, 608) for a, v in candidate_target])
            add_rows("neutral_control", neutral_path, neutral_key, "source", neutral)
            add_rows("neutral_control", neutral_path, neutral_key, "target", neutral)
            add_rows("neutral_control", eye0_path, eye0_key, "source", eyes)
            add_rows("neutral_control", eye0_path, eye0_key, "target", eyes)
            add_rows("neutral_control", eye1_path, eye1_key, "source", eyes)
            add_rows("neutral_control", eye1_path, eye1_key, "target", eyes)
            self.assertEqual(len(layout_rows), 21)
            write_tsv(stage95 / "SLOT_LIGHT_ANCHORED_BLOCK_LAYOUT.tsv", layout_fields, layout_rows)
            write_tsv(stage95 / "SLOT_LIGHT_ANCHORED_BLOCK_PAIRWISE_COMPARISON.tsv", ["comparison"], [
                {"comparison": "stable_30_source_target"},
                {"comparison": "ambiguous_150_to_first_75"},
                {"comparison": "ambiguous_150_to_second_75"},
                {"comparison": "duplicate_target_75_pair"},
                {"comparison": "stable_2_source_target"},
            ])

            def put_u32(payload: bytearray, offset: int, value: int) -> None:
                payload[offset:offset + 4] = int(value & 0xFFFFFFFF).to_bytes(4, "little")

            def build_block(payload: bytearray, anchor: int, span: int, variant: str, endpoint: int) -> None:
                put_u32(payload, anchor, span)
                put_u32(payload, anchor + 4, 497)
                for relative in range(2, 27):
                    put_u32(payload, anchor + relative * 4, 0x3F800000)
                record = anchor + 108
                value = int(variant.rsplit("_", 1)[1])
                put_u32(payload, record, value)
                put_u32(payload, record + 4, value)
                for relative in range(2, 10):
                    put_u32(payload, record + relative * 4, 0x40000000 + relative)
                put_u32(payload, record + 40, endpoint - (record + 40))
                for offset in range(record + 44, anchor + span, 4):
                    put_u32(payload, offset, 0xABC00000 + ((offset - anchor) // 4))

            source_payload = bytearray(4096)
            target_payload = bytearray(4096)
            for anchor, variant in candidate_source:
                build_block(source_payload, anchor, 608, variant, 192)
            for anchor, variant in candidate_target:
                build_block(target_payload, anchor, 608, variant, 192)

            # Stable controls have non-consensus changes.
            put_u32(target_payload, candidate_target[0][0] + 200, 0x11111111)
            put_u32(target_payload, candidate_target[3][0] + 204, 0x22222222)
            put_u32(target_payload, candidate_target[3][0] + 208, 0x33333333)

            # Source 150 -> first 75: 2 record dwords + 7 trailer dwords = 9.
            first_anchor = candidate_target[1][0]
            for rel in (200, 204, 208, 212, 216, 220, 224):
                put_u32(target_payload, first_anchor + rel, 0x51000000 + rel)
            # Source 150 -> second 75: 2 record dwords + 2 trailer dwords = 4.
            second_anchor = candidate_target[2][0]
            for rel in (200, 228):
                put_u32(target_payload, second_anchor + rel, 0x52000000 + rel)

            neutral_source = bytearray(4096)
            neutral_target = bytearray(4096)
            for anchor, variant, span in neutral:
                build_block(neutral_source, anchor, span, variant, 192)
                build_block(neutral_target, anchor, span, variant, 192)
            eye0_source = bytearray(1024); eye0_target = bytearray(1024)
            eye1_source = bytearray(1024); eye1_target = bytearray(1024)
            for payload in (eye0_source, eye0_target, eye1_source, eye1_target):
                build_block(payload, 320, 560, "equal_float_1", 192)

            def member(key: str, payload: bytes) -> dict[str, object]:
                return {"name": key.split("#")[0], "comparison_key": key, "payload": payload}

            focal = {
                0: (candidate_key, bytes(source_payload), bytes(target_payload)),
                1: (neutral_key, bytes(neutral_source), bytes(neutral_target)),
                2: (eye0_key, bytes(eye0_source), bytes(eye0_target)),
                3: (eye1_key, bytes(eye1_source), bytes(eye1_target)),
            }
            containers = []
            dummy = 0
            for index in range(4):
                key, source, target = focal[index]
                source_members = [member(key, source)]
                target_members = [member(key, target)]
                while len(source_members) < 135:
                    dkey = f"dummy_{index}_{dummy}.g1e#0"
                    source_members.append(member(dkey, bytes(256)))
                    target_members.append(member(dkey, bytes(256)))
                    dummy += 1
                containers.append({
                    "normalized_path": f"data/x64/effect/container{index}.elixir.gz",
                    "source_members": source_members,
                    "target_members": target_members,
                })

            output, archive, summary = TOOL.build_report(
                ROOT,
                create_archive=False,
                report_root=reports,
                workspace_root=temp / "workspace",
                container_loader=lambda **_kwargs: (containers, []),
            )
            self.assertIsNone(archive)
            self.assertEqual(summary["focal_occurrence_rows"], 21)
            self.assertEqual(summary["candidate_source_150_to_first_target_75_residual_dword_differences"], 9)
            self.assertEqual(summary["candidate_source_150_to_second_target_75_residual_dword_differences"], 4)
            self.assertEqual(summary["candidate_closest_target_by_residual_distance"], "second_target_75")
            self.assertTrue(summary["candidate_target_duplicate_75_blocks_distinct"])
            self.assertFalse(summary["candidate_target_occurrence_identity_resolved"])
            self.assertEqual(summary["prototype_candidate_rows"], 0)
            self.assertEqual(summary["skipped_rows"], 0)
            self.assertTrue((output / "SLOT_LIGHT_INTERNAL_CHANGE_ISLANDS.tsv").is_file())
            self.assertTrue((output / "SLOT_LIGHT_INTERNAL_IDENTITY_DECISION.tsv").is_file())


if __name__ == "__main__":
    unittest.main()
