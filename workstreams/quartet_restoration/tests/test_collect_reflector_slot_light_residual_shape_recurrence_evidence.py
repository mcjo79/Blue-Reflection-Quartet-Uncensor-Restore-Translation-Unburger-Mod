#!/usr/bin/env python3
from __future__ import annotations

import csv
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
MODULE_PATH = ROOT / "workstreams/quartet_restoration/collect_reflector_slot_light_residual_shape_recurrence_evidence.py"
SPEC = importlib.util.spec_from_file_location("stage97", MODULE_PATH)
assert SPEC and SPEC.loader
TOOL = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(TOOL)


def write_tsv(path: Path, fields: list[str], rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


class Stage97Tests(unittest.TestCase):
    def test_recurrence_is_evidence_only_and_does_not_resolve_identity(self) -> None:
        with tempfile.TemporaryDirectory(prefix="stage97-test-") as temp_name:
            temp = Path(temp_name)
            reports = temp / "reports"
            stage84 = reports / TOOL.STAGE84_DIR
            stage96 = reports / TOOL.STAGE96_DIR
            stage84.mkdir(parents=True)
            stage96.mkdir(parents=True)

            (stage84 / "SUMMARY.json").write_text(json.dumps({
                "type": "br_quartet_restoration_reflector_slot_light_g1e_structure_evidence_summary",
                "tool_version": "0.0.98",
                "scope_member_rows": 6,
                "aligned_changed_dword_rows": 634,
                "prototype_candidate_rows": 0,
                "brightness_semantics_confirmed": False,
                "skipped_rows": 0,
            }), encoding="utf-8")
            (stage96 / "SUMMARY.json").write_text(json.dumps({
                "type": "br_quartet_restoration_reflector_slot_light_anchored_block_internal_change_evidence_summary",
                "tool_version": "0.1.10",
                "sibling_G1E_G1EM_member_rows": 540,
                "focal_occurrence_rows": 21,
                "comparison_rows": 5,
                "internal_dword_difference_rows": 23,
                "consensus_stable_transition_signatures": 0,
                "candidate_target_occurrence_identity_resolved": False,
                "prototype_candidate_rows": 0,
                "technical_leaf_semantics_resolved": False,
                "brightness_semantics_confirmed": False,
                "censorship_semantics_confirmed": False,
                "skipped_rows": 0,
            }), encoding="utf-8")

            aligned_fields = [
                "character_slot", "asset_role", "family_key", "normalized_path", "member_key", "member_name",
                "segment_id", "source_offset", "target_offset", "relative_offset", "source_u32_hex",
                "target_u32_hex", "source_float32", "target_float32", "source_float_status",
                "target_float_status", "transition_classification", "transition_id",
            ]
            aligned_rows: list[dict[str, object]] = []

            def add(member: str, source: int, target: int, index: int) -> None:
                aligned_rows.append({
                    "character_slot": "PC02" if member.casefold() == TOOL.FOCAL_MEMBER else "PC01",
                    "asset_role": "ringlight",
                    "family_key": "test",
                    "normalized_path": "data/x64/effect/test.elixir.gz",
                    "member_key": member.casefold() + "#0",
                    "member_name": member,
                    "segment_id": f"s{index}",
                    "source_offset": index * 4,
                    "target_offset": index * 4,
                    "relative_offset": index * 4,
                    "source_u32_hex": f"0x{source & 0xffffffff:08x}",
                    "target_u32_hex": f"0x{target & 0xffffffff:08x}",
                    "source_float32": "",
                    "target_float32": "",
                    "source_float_status": "",
                    "target_float_status": "",
                    "transition_classification": "opaque_dword_transition",
                    "transition_id": f"t{index}",
                })

            add("e_PC02_w5_ringlight_01.g1e", 0x43160000, 0x42960000, 0)
            add("e_PC02_w5_ringlight_01.g1e", 0x43160000, 0x42960000, 1)
            add("e_PC02_w5_ringlight_01.g1e", 0xFFFFFC8C, 0xFFFFFC7C, 2)
            add("e_PC01_ringlight_00.g1e", 100, 84, 3)  # same signed delta -16 outside focal
            add("e_PC02_w5_ringlight_01.g1e", 1488, 2096, 4)
            add("e_PC01_ringlight_00.g1e", 10, 618, 5)  # same signed delta +608 outside focal
            add("e_PC01_ringlight_00.g1e", 2000, 1376, 6)  # same delta as -884 -> -1508
            while len(aligned_rows) < 634:
                index = len(aligned_rows)
                add("e_PC00_eyelight_00.g1e", 0x10000000 + index, 0x10010000 + index, index)
            write_tsv(stage84 / "SLOT_LIGHT_ALIGNED_CHANGED_DWORDS.tsv", aligned_fields, aligned_rows)

            internal_fields = [
                "comparison", "comparison_role", "relative_dword", "relative_byte", "segment", "left_u32_hex",
                "right_u32_hex", "left_i32", "right_i32", "left_float32", "right_float32",
                "left_internal_target_relative", "right_internal_target_relative", "equivalent_intra_block_reference",
                "seen_in_any_stable_control_same_offset", "seen_in_both_stable_controls_same_offset",
                "same_offset_differs_between_target_75_blocks", "transition_signature",
            ]
            seeds = [
                ("ambiguous_150_to_first_75", 27, "reference_record", 0x43160000, 0x42960000),
                ("ambiguous_150_to_first_75", 28, "reference_record", 0x43160000, 0x42960000),
                ("ambiguous_150_to_first_75", 37, "reference_record", 0xFFFFFC8C, 0xFFFFFC7C),
                ("ambiguous_150_to_first_75", 104, "post_record_trailer", 1488, 2096),
                ("ambiguous_150_to_first_75", 126, "post_record_trailer", 0x42F00000, 0x41200000),
                ("ambiguous_150_to_first_75", 128, "post_record_trailer", 0, 0x40400000),
                ("ambiguous_150_to_first_75", 129, "post_record_trailer", 0x40400000, 0x40800000),
                ("ambiguous_150_to_first_75", 132, "post_record_trailer", 0x43A00000, 0x42C80000),
                ("ambiguous_150_to_first_75", 133, "post_record_trailer", 0x41100000, 0x40E00000),
                ("ambiguous_150_to_second_75", 27, "reference_record", 0x43160000, 0x42960000),
                ("ambiguous_150_to_second_75", 28, "reference_record", 0x43160000, 0x42960000),
                ("ambiguous_150_to_second_75", 37, "reference_record", 0xFFFFFC8C, 0xFFFFFA1C),
                ("ambiguous_150_to_second_75", 104, "post_record_trailer", 1488, 2144),
            ]
            rows: list[dict[str, object]] = []
            for comparison, relative, segment, source, target in seeds:
                rows.append({
                    "comparison": comparison,
                    "comparison_role": "ambiguous_candidate",
                    "relative_dword": relative,
                    "relative_byte": relative * 4,
                    "segment": segment,
                    "left_u32_hex": f"0x{source & 0xffffffff:08x}",
                    "right_u32_hex": f"0x{target & 0xffffffff:08x}",
                    "left_i32": TOOL.signed_i32(source),
                    "right_i32": TOOL.signed_i32(target),
                    "left_float32": "",
                    "right_float32": "",
                    "left_internal_target_relative": "",
                    "right_internal_target_relative": "",
                    "equivalent_intra_block_reference": False,
                    "seen_in_any_stable_control_same_offset": False,
                    "seen_in_both_stable_controls_same_offset": False,
                    "same_offset_differs_between_target_75_blocks": True,
                    "transition_signature": f"{relative}:0x{source & 0xffffffff:08x}->0x{target & 0xffffffff:08x}",
                })
            while len(rows) < 23:
                index = len(rows)
                rows.append({
                    "comparison": "stable_30_source_target",
                    "comparison_role": "stable_control",
                    "relative_dword": 200 + index,
                    "relative_byte": (200 + index) * 4,
                    "segment": "post_record_trailer",
                    "left_u32_hex": f"0x{index:08x}",
                    "right_u32_hex": f"0x{index + 1:08x}",
                    "left_i32": index,
                    "right_i32": index + 1,
                    "left_float32": "",
                    "right_float32": "",
                    "left_internal_target_relative": "",
                    "right_internal_target_relative": "",
                    "equivalent_intra_block_reference": False,
                    "seen_in_any_stable_control_same_offset": True,
                    "seen_in_both_stable_controls_same_offset": False,
                    "same_offset_differs_between_target_75_blocks": False,
                    "transition_signature": f"{200 + index}:0x{index:08x}->0x{index + 1:08x}",
                })
            write_tsv(stage96 / "SLOT_LIGHT_INTERNAL_DWORD_DIFFERENCES.tsv", internal_fields, rows)

            output, archive, summary = TOOL.build_report(ROOT, create_archive=False, report_root=reports)
            self.assertIsNone(archive)
            self.assertEqual(summary["ambiguous_residual_seed_rows"], 13)
            self.assertEqual(summary["unique_residual_transition_shapes"], 10)
            self.assertEqual(summary["source_150_to_target_75_exact_transition_hits"], 2)
            self.assertEqual(summary["source_150_to_target_75_exact_transition_hits_outside_focal_member"], 0)
            self.assertGreater(summary["transition_shapes_with_signed_delta_hits_outside_focal_member"], 0)
            self.assertFalse(summary["candidate_target_occurrence_identity_resolved"])
            self.assertEqual(summary["prototype_candidate_rows"], 0)
            self.assertTrue((output / "SLOT_LIGHT_RESIDUAL_SHAPE_CLASSIFICATION.tsv").is_file())
            self.assertTrue((output / "SLOT_LIGHT_RESIDUAL_RECURRENCE_IDENTITY_DECISION.tsv").is_file())


if __name__ == "__main__":
    unittest.main()
