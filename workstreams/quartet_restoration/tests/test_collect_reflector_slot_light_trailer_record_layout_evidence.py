#!/usr/bin/env python3
from __future__ import annotations

import csv
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
TOOL_PATH = ROOT / "workstreams/quartet_restoration/collect_reflector_slot_light_trailer_record_layout_evidence.py"
spec = importlib.util.spec_from_file_location("stage98_test_tool", TOOL_PATH)
assert spec and spec.loader
TOOL = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = TOOL
spec.loader.exec_module(TOOL)


def write_tsv(path: Path, fields: list[str], rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


class Stage98Tests(unittest.TestCase):
    def test_local_same_variant_audit_stays_evidence_only(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            temp = Path(td)
            reports = temp / "reports"
            stage79 = reports / "reflector_character_slot_render_member_evidence"
            stage95 = reports / "reflector_slot_light_anchored_block_envelope_evidence"
            stage96 = reports / "reflector_slot_light_anchored_block_internal_change_evidence"
            stage97 = reports / "reflector_slot_light_residual_shape_recurrence_evidence"
            for path in (stage79, stage95, stage96, stage97):
                path.mkdir(parents=True)

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
                "focal_occurrence_rows": 21,
                "anchored_block_span_field_confirmed": True,
                "candidate_target_occurrence_identity_resolved": False,
                "skipped_rows": 0,
            }), encoding="utf-8")
            (stage96 / "SUMMARY.json").write_text(json.dumps({
                "type": "br_quartet_restoration_reflector_slot_light_anchored_block_internal_change_evidence_summary",
                "tool_version": "0.1.10",
                "internal_dword_difference_rows": 23,
                "candidate_source_150_to_second_target_75_residual_dword_differences": 4,
                "candidate_target_occurrence_identity_resolved": False,
                "skipped_rows": 0,
            }), encoding="utf-8")
            (stage97 / "SUMMARY.json").write_text(json.dumps({
                "type": "br_quartet_restoration_reflector_slot_light_residual_shape_recurrence_evidence_summary",
                "tool_version": "0.1.11",
                "ambiguous_residual_seed_rows": 13,
                "unique_residual_transition_shapes": 10,
                "transition_shapes_with_exact_hits_outside_focal_member": 0,
                "candidate_target_occurrence_identity_resolved": False,
                "prototype_candidate_rows": 0,
                "skipped_rows": 0,
            }), encoding="utf-8")
            seed_rows = []
            for index, pos in enumerate((27, 28, 37, 104, 126, 128, 129, 132, 133, 27, 28, 37, 104)):
                seed_rows.append({"comparison": "a" if index < 9 else "b", "relative_dword": pos})
            write_tsv(stage97 / "SLOT_LIGHT_RESIDUAL_SHAPE_SEEDS.tsv", ["comparison", "relative_dword"], seed_rows)

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
            fields = ["cluster_role", "normalized_path", "member_key", "member_name", "side", "reference_index", "variant_label", "endpoint", "anchor", "record_start", "reference_offset", "declared_block_span"]
            layout: list[dict[str, object]] = []

            def add(role: str, path: str, key: str, side: str, values: list[tuple[int, str, int]]) -> None:
                for idx, (anchor, variant, span) in enumerate(values):
                    record = anchor + 108
                    layout.append({"cluster_role": role, "normalized_path": path, "member_key": key, "member_name": key.split("#")[0], "side": side, "reference_index": idx, "variant_label": variant, "endpoint": 192, "anchor": anchor, "record_start": record, "reference_offset": record + 40, "declared_block_span": span})

            add("candidate_ringlight", candidate_path, candidate_key, "source", [(a, v, 608) for a, v in candidate_source])
            add("candidate_ringlight", candidate_path, candidate_key, "target", [(a, v, 608) for a, v in candidate_target])
            add("neutral_control", neutral_path, neutral_key, "source", neutral)
            add("neutral_control", neutral_path, neutral_key, "target", neutral)
            add("neutral_control", eye0_path, eye0_key, "source", eyes)
            add("neutral_control", eye0_path, eye0_key, "target", eyes)
            add("neutral_control", eye1_path, eye1_key, "source", eyes)
            add("neutral_control", eye1_path, eye1_key, "target", eyes)
            self.assertEqual(len(layout), 21)
            write_tsv(stage95 / "SLOT_LIGHT_ANCHORED_BLOCK_LAYOUT.tsv", fields, layout)

            def put(payload: bytearray, offset: int, value: int) -> None:
                payload[offset:offset + 4] = int(value & 0xFFFFFFFF).to_bytes(4, "little")

            def block(payload: bytearray, anchor: int, span: int, variant: str, endpoint: int, flavor: int = 0) -> None:
                put(payload, anchor, span)
                put(payload, anchor + 4, 497)
                for rel in range(2, 27):
                    put(payload, anchor + rel * 4, 0x3F800000)
                record = anchor + 108
                value = int(variant.rsplit("_", 1)[1])
                put(payload, record, value)
                put(payload, record + 4, value)
                for rel in range(2, 10):
                    put(payload, record + rel * 4, 0x40000000 + rel)
                put(payload, record + 40, endpoint - (record + 40))
                for offset in range(record + 44, anchor + span, 4):
                    put(payload, offset, 0xABC00000 + ((offset - anchor) // 4))
                put(payload, anchor + 104 * 4, 0x500 + flavor)

            source = bytearray(4096); target = bytearray(4096)
            for anchor, variant in candidate_source:
                block(source, anchor, 608, variant, 192)
            for idx, (anchor, variant) in enumerate(candidate_target):
                block(target, anchor, 608, variant, 192, flavor=idx * 0x10)
            neutral_source = bytearray(4096); neutral_target = bytearray(4096)
            for anchor, variant, span in neutral:
                block(neutral_source, anchor, span, variant, 192)
                block(neutral_target, anchor, span, variant, 192)
            eye0s = bytearray(1024); eye0t = bytearray(1024); eye1s = bytearray(1024); eye1t = bytearray(1024)
            for payload in (eye0s, eye0t, eye1s, eye1t):
                block(payload, 320, 560, "equal_float_1", 192)

            def member(key: str, payload: bytes) -> dict[str, object]:
                return {"name": key.split("#")[0], "comparison_key": key, "payload": payload}

            focal = {
                0: (candidate_key, bytes(source), bytes(target)),
                1: (neutral_key, bytes(neutral_source), bytes(neutral_target)),
                2: (eye0_key, bytes(eye0s), bytes(eye0t)),
                3: (eye1_key, bytes(eye1s), bytes(eye1t)),
            }
            containers = []
            dummy = 0
            for idx in range(4):
                key, left, right = focal[idx]
                source_members = [member(key, left)]
                target_members = [member(key, right)]
                while len(source_members) < 135:
                    dkey = f"dummy_{idx}_{dummy}.g1e#0"
                    source_members.append(member(dkey, bytes(256)))
                    target_members.append(member(dkey, bytes(256)))
                    dummy += 1
                containers.append({"normalized_path": f"data/x64/effect/container{idx}.elixir.gz", "source_members": source_members, "target_members": target_members})

            output, archive, summary = TOOL.build_report(ROOT, create_archive=False, report_root=reports, workspace_root=temp / "workspace", container_loader=lambda **_kwargs: (containers, []))
            self.assertIsNone(archive)
            self.assertEqual(summary["same_variant_occurrence_rows"], 7)
            self.assertEqual(summary["residual_seed_rows"], 13)
            self.assertEqual(summary["same_variant_block_comparison_rows"], 9)
            self.assertFalse(summary["candidate_target_occurrence_identity_resolved"])
            self.assertEqual(summary["prototype_candidate_rows"], 0)
            self.assertEqual(summary["skipped_rows"], 0)
            self.assertTrue((output / "SLOT_LIGHT_TRAILER_RECORD_DWORD_VALUES.tsv").is_file())
            self.assertTrue((output / "SLOT_LIGHT_TARGET_75_TRAILER_RECORD_DECISION.tsv").is_file())


if __name__ == "__main__":
    unittest.main()
