#!/usr/bin/env python3
from __future__ import annotations

import csv
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
MODULE_PATH = ROOT / "workstreams/quartet_restoration/collect_reflector_slot_light_section_table_record_binding_evidence.py"
spec = importlib.util.spec_from_file_location("stage93", MODULE_PATH)
assert spec and spec.loader
TOOL = importlib.util.module_from_spec(spec)
spec.loader.exec_module(TOOL)


def write_tsv(path: Path, fields: list[str], rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


class Stage93Test(unittest.TestCase):
    def test_target_table_bindings_do_not_resolve_duplicate_identity(self) -> None:
        with tempfile.TemporaryDirectory() as temp_name:
            temp = Path(temp_name)
            reports = temp / "reports"
            stage91 = reports / TOOL.STAGE91_DIR
            stage92 = reports / TOOL.STAGE92_DIR
            stage91.mkdir(parents=True)
            stage92.mkdir(parents=True)

            (stage91 / "SUMMARY.json").write_text(json.dumps({
                "type": "br_quartet_restoration_reflector_slot_light_section_cardinality_record_role_evidence_summary",
                "tool_version": "0.1.5",
                "reference_cluster_member_rows": 4,
                "section_table_entry_rows": 51,
                "reference_record_rows": 177,
                "resolved_reference_origin": "dword_start_relative",
                "prototype_candidate_rows": 0,
                "brightness_semantics_confirmed": False,
                "censorship_semantics_confirmed": False,
                "skipped_rows": 0,
            }), encoding="utf-8")
            (stage92 / "SUMMARY.json").write_text(json.dumps({
                "type": "br_quartet_restoration_reflector_slot_light_record_occurrence_identity_evidence_summary",
                "tool_version": "0.1.6",
                "reference_record_rows": 177,
                "neutral_focal_variants_coexist_unchanged": True,
                "neutral_150_to_75_transition_supported": False,
                "prior_transition_interpretation_corrected": True,
                "candidate_middle_target_duplicate_rows": 2,
                "candidate_minimum_edit_model_rows": 2,
                "candidate_target_occurrence_identity_resolved": False,
                "prototype_candidate_rows": 0,
                "brightness_semantics_confirmed": False,
                "censorship_semantics_confirmed": False,
                "skipped_rows": 0,
            }), encoding="utf-8")

            candidate_path = "data/x64/effect/candidate.elixir.gz"
            candidate_key = "e_pc02_w5_ringlight_01.g1e#0"
            neutral_path = "data/x64/effect/neutral.elixir.gz"
            neutral_key = "neutral.g1e#0"
            occurrence_fields = [
                "cluster_role", "normalized_path", "member_key", "member_name", "side", "reference_index",
                "reference_offset", "record_start", "masked_template_sha256", "family_core_sha256",
                "leaf0_u32_hex", "leaf1_u32_hex", "leaf0_float32", "leaf1_float32", "variant_label",
                "is_focal_family", "is_stage91_source_template", "is_stage91_target_template", "member_focal_role",
                "exact_same_offset_peer", "exact_same_offset_peer_side", "exact_same_offset_peer_reference_offset",
            ]
            occurrences: list[dict[str, object]] = []

            def add_occurrence(path: str, key: str, side: str, index: int, start: int, variant: str, focal: bool) -> None:
                occurrences.append({
                    "cluster_role": "candidate_ringlight" if key == candidate_key else "neutral_control",
                    "normalized_path": path,
                    "member_key": key,
                    "member_name": key.split("#", 1)[0],
                    "side": side,
                    "reference_index": index,
                    "reference_offset": start + 40,
                    "record_start": start,
                    "masked_template_sha256": f"template-{side}-{index}-{start}",
                    "family_core_sha256": "focal-family" if focal else "other-family",
                    "leaf0_u32_hex": "0x0",
                    "leaf1_u32_hex": "0x0",
                    "leaf0_float32": variant.rsplit("_", 1)[-1] if variant.startswith("equal_float_") else "",
                    "leaf1_float32": variant.rsplit("_", 1)[-1] if variant.startswith("equal_float_") else "",
                    "variant_label": variant,
                    "is_focal_family": focal,
                    "is_stage91_source_template": variant == "equal_float_150",
                    "is_stage91_target_template": variant == "equal_float_75",
                    "member_focal_role": "candidate" if key == candidate_key else "control",
                    "exact_same_offset_peer": False,
                    "exact_same_offset_peer_side": "",
                    "exact_same_offset_peer_reference_offset": "",
                })

            for index, (start, variant) in enumerate([(10236, "equal_float_30"), (10844, "equal_float_150"), (11452, "equal_float_2")]):
                add_occurrence(candidate_path, candidate_key, "source", index, start, variant, True)
            for index, (start, variant) in enumerate([(10252, "equal_float_30"), (10860, "equal_float_75"), (11468, "equal_float_75"), (12076, "equal_float_2")]):
                add_occurrence(candidate_path, candidate_key, "target", index, start, variant, True)
            add_occurrence(neutral_path, neutral_key, "source", 0, 50000, "equal_float_1", False)
            add_occurrence(neutral_path, neutral_key, "target", 0, 50000, "equal_float_1", False)
            for index in range(168):
                side = "source" if index % 2 == 0 else "target"
                add_occurrence(neutral_path, neutral_key, side, index + 1, 60000 + index * 256, f"leaf_{index}", False)
            self.assertEqual(len(occurrences), 177)
            write_tsv(stage92 / "SLOT_LIGHT_RECORD_OCCURRENCE_INVENTORY.tsv", occurrence_fields, occurrences)

            sequence_fields = ["member_role", "normalized_path", "member_key", "member_name", "side", "family_sequence_index", "alignment_region", "reference_offset", "record_start", "masked_template_sha256", "variant_label"]
            write_tsv(stage92 / "SLOT_LIGHT_CANDIDATE_FAMILY_SEQUENCE_ALIGNMENT.tsv", sequence_fields, [])
            edit_fields = ["model_id", "source_middle_variants", "target_middle_variants", "substitution_rows", "insertion_rows", "deletion_rows", "edit_cost", "continuing_target_middle_index", "minimal_edit_model", "occurrence_identity_resolved", "classification"]
            write_tsv(stage92 / "SLOT_LIGHT_CANDIDATE_EDIT_MODELS.tsv", edit_fields, [
                {"model_id": "a"}, {"model_id": "b"}, {"model_id": "c"},
            ])

            table_fields = [
                "cluster_role", "normalized_path", "member_key", "member_name", "side", "endpoint", "section_count",
                "table_index", "entry_index", "entry_relative_offset", "entry_absolute_offset", "entry_u32_hex", "entry_i32",
                "entry_float32", "entry_float_status", "entry_aligned", "entry_within_declared_span", "entry_at_or_after_table_region",
            ]
            tables: list[dict[str, object]] = []

            def add_table(path: str, key: str, side: str, count: int, table: int, index: int, absolute: int, value: int) -> None:
                tables.append({
                    "cluster_role": "candidate_ringlight" if key == candidate_key else "neutral_control",
                    "normalized_path": path,
                    "member_key": key,
                    "member_name": key.split("#", 1)[0],
                    "side": side,
                    "endpoint": 10000 if key == candidate_key else 100,
                    "section_count": count,
                    "table_index": table,
                    "entry_index": index,
                    "entry_relative_offset": absolute - (10000 if key == candidate_key else 100),
                    "entry_absolute_offset": absolute,
                    "entry_u32_hex": f"0x{value & 0xffffffff:08x}",
                    "entry_i32": value,
                    "entry_float32": "",
                    "entry_float_status": "",
                    "entry_aligned": value % 4 == 0,
                    "entry_within_declared_span": False,
                    "entry_at_or_after_table_region": False,
                })

            # Candidate source: six zero entries, no dominant bindings.
            absolute = 10056
            for table in (1, 2, 3):
                for index in range(2):
                    add_table(candidate_path, candidate_key, "source", 3, table, index, absolute, 0)
                    absolute += 4
            # Candidate target: third table binds 30,75,75 at record_start - 108.
            absolute = 10056
            for table, values in ((1, [0, 0, 0]), (2, [0x3e000000, 0, 0]), (3, [64, 668, 1272])):
                for index, value in enumerate(values):
                    add_table(candidate_path, candidate_key, "target", 4, table, index, absolute, value)
                    absolute += 4
            # Remaining 36 neutral entries are zeros and do not bind nearby records.
            absolute = 156
            for side in ("source", "target"):
                for table in (1, 2, 3):
                    for index in range(6):
                        add_table(neutral_path, neutral_key, side, 7, table, index, absolute, 0)
                        absolute += 4
            self.assertEqual(len(tables), 51)
            write_tsv(stage91 / "SLOT_LIGHT_SECTION_TABLE_ENTRIES.tsv", table_fields, tables)

            delta_fields = ["cluster_role", "normalized_path", "member_key", "member_name", "table_index", "source_entry_rows", "target_entry_rows", "entry_row_delta", "lcs_entry_rows", "source_only_entry_rows", "target_only_entry_rows", "source_target_exact", "delta_classification"]
            write_tsv(stage91 / "SLOT_LIGHT_SECTION_TABLE_DELTA.tsv", delta_fields, [
                {"member_key": candidate_key, "table_index": 1, "delta_classification": "cardinality_change_with_order_preserving_subset"},
                {"member_key": candidate_key, "table_index": 2, "delta_classification": "mixed_cardinality_and_value_change"},
                {"member_key": candidate_key, "table_index": 3, "delta_classification": "mixed_cardinality_and_value_change"},
            ])

            output, archive, summary = TOOL.build_report(
                ROOT,
                create_archive=False,
                report_root=reports,
                workspace_root=temp / "workspace",
            )
            self.assertIsNone(archive)
            self.assertEqual(summary["dominant_record_relative_dword"], -27)
            self.assertEqual(summary["candidate_target_table3_dominant_binding_rows"], 3)
            self.assertEqual(summary["candidate_target_table3_variant_sequence"], ["equal_float_30", "equal_float_75", "equal_float_75"])
            self.assertEqual(summary["candidate_target_duplicate_75_binding_rows"], 2)
            self.assertTrue(summary["candidate_target_duplicate_75_bindings_distinct"])
            self.assertTrue(summary["stable_prefix_record_also_target_table_bound"])
            self.assertTrue(summary["target_table_binding_bulk_reencoding_supported"])
            self.assertFalse(summary["target_table_binding_unique_insertion_marker"])
            self.assertFalse(summary["candidate_target_occurrence_identity_resolved"])
            self.assertEqual(summary["prototype_candidate_rows"], 0)
            self.assertTrue((output / "SLOT_LIGHT_TABLE_BINDING_IDENTITY_DECISION.tsv").is_file())
            self.assertTrue((output / "SLOT_LIGHT_DUPLICATE_TARGET_OCCURRENCE_BINDING.tsv").is_file())


if __name__ == "__main__":
    unittest.main()
