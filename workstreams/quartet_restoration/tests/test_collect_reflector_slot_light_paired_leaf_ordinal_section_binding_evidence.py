from __future__ import annotations

import csv
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "workstreams/quartet_restoration/collect_reflector_slot_light_paired_leaf_ordinal_section_binding_evidence.py"
SPEC = importlib.util.spec_from_file_location("stage102_tool", SCRIPT)
assert SPEC and SPEC.loader
TOOL = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(TOOL)


def write_tsv(path: Path, fields: list[str], rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def prepare_reports(root: Path, *, omit_binding: bool = False) -> Path:
    reports = root / "reports"
    stage101 = reports / TOOL.STAGE101_DIR
    stage91 = reports / TOOL.STAGE91_DIR
    stage93 = reports / TOOL.STAGE93_DIR
    stage101.mkdir(parents=True)
    stage91.mkdir(parents=True)
    stage93.mkdir(parents=True)

    (stage101 / "SUMMARY.json").write_text(json.dumps({
        "type": "br_quartet_restoration_reflector_slot_light_paired_leaf_context_role_evidence_summary",
        "tool_version": "0.1.15",
        "technical_leaf_storage_class": "paired_equal_finite_float_payload_leaves",
        "technical_leaf_storage_class_resolved": True,
        "technical_leaf_domain_semantics_resolved": False,
        "focal_context_record_rows": 21,
        "focal_context_values": ["1", "2", "30", "50", "75", "100", "150"],
        "skipped_rows": 0,
    }), encoding="utf-8")

    specs = [
        ("data/x64/effect/1000_pc00.elixir.gz", "e_pc00_eyelight_00.g1e#0", "e_PC00_eyelight_00.g1e", "source", 412, 452, 192, "1", "other_focal_template_occurrence"),
        ("data/x64/effect/1000_pc00.elixir.gz", "e_pc00_eyelight_00.g1e#0", "e_PC00_eyelight_00.g1e", "target", 412, 452, 192, "1", "other_focal_template_occurrence"),
        ("data/x64/effect/1000_pc00.elixir.gz", "e_pc00_eyelight_01.g1e#0", "e_PC00_eyelight_01.g1e", "source", 412, 452, 192, "1", "other_focal_template_occurrence"),
        ("data/x64/effect/1000_pc00.elixir.gz", "e_pc00_eyelight_01.g1e#0", "e_PC00_eyelight_01.g1e", "target", 412, 452, 192, "1", "other_focal_template_occurrence"),
        ("data/x64/effect/1002_pc02.elixir.gz", "e_pc02_w5_ringlight_01.g1e#0", "e_PC02_w5_ringlight_01.g1e", "source", 20512, 20552, 20276, "30", "other_focal_template_occurrence"),
        ("data/x64/effect/1002_pc02.elixir.gz", "e_pc02_w5_ringlight_01.g1e#0", "e_PC02_w5_ringlight_01.g1e", "source", 21120, 21160, 20276, "150", "candidate_source_150"),
        ("data/x64/effect/1002_pc02.elixir.gz", "e_pc02_w5_ringlight_01.g1e#0", "e_PC02_w5_ringlight_01.g1e", "source", 21728, 21768, 20276, "2", "other_focal_template_occurrence"),
        ("data/x64/effect/1002_pc02.elixir.gz", "e_pc02_w5_ringlight_01.g1e#0", "e_PC02_w5_ringlight_01.g1e", "target", 20528, 20568, 20276, "30", "other_focal_template_occurrence"),
        ("data/x64/effect/1002_pc02.elixir.gz", "e_pc02_w5_ringlight_01.g1e#0", "e_PC02_w5_ringlight_01.g1e", "target", 21136, 21176, 20276, "75", "candidate_first_target_75_inserted"),
        ("data/x64/effect/1002_pc02.elixir.gz", "e_pc02_w5_ringlight_01.g1e#0", "e_PC02_w5_ringlight_01.g1e", "target", 21744, 21784, 20276, "75", "candidate_second_target_75_continuing"),
        ("data/x64/effect/1002_pc02.elixir.gz", "e_pc02_w5_ringlight_01.g1e#0", "e_PC02_w5_ringlight_01.g1e", "target", 22352, 22392, 20276, "2", "other_focal_template_occurrence"),
        ("data/x64/effect/100_common.elixir.gz", "e_cmn_pup_reflect_s.g1e#0", "e_cmn_pup_reflect_s.g1e", "source", 444, 484, 192, "1", "other_focal_template_occurrence"),
        ("data/x64/effect/100_common.elixir.gz", "e_cmn_pup_reflect_s.g1e#0", "e_cmn_pup_reflect_s.g1e", "source", 1004, 1044, 192, "100", "other_focal_template_occurrence"),
        ("data/x64/effect/100_common.elixir.gz", "e_cmn_pup_reflect_s.g1e#0", "e_cmn_pup_reflect_s.g1e", "source", 1644, 1684, 192, "50", "other_focal_template_occurrence"),
        ("data/x64/effect/100_common.elixir.gz", "e_cmn_pup_reflect_s.g1e#0", "e_cmn_pup_reflect_s.g1e", "source", 2284, 2324, 192, "150", "neutral_stable_150_source"),
        ("data/x64/effect/100_common.elixir.gz", "e_cmn_pup_reflect_s.g1e#0", "e_cmn_pup_reflect_s.g1e", "source", 2924, 2964, 192, "75", "neutral_stable_75_source"),
        ("data/x64/effect/100_common.elixir.gz", "e_cmn_pup_reflect_s.g1e#0", "e_cmn_pup_reflect_s.g1e", "target", 444, 484, 192, "1", "other_focal_template_occurrence"),
        ("data/x64/effect/100_common.elixir.gz", "e_cmn_pup_reflect_s.g1e#0", "e_cmn_pup_reflect_s.g1e", "target", 1004, 1044, 192, "100", "other_focal_template_occurrence"),
        ("data/x64/effect/100_common.elixir.gz", "e_cmn_pup_reflect_s.g1e#0", "e_cmn_pup_reflect_s.g1e", "target", 1644, 1684, 192, "50", "other_focal_template_occurrence"),
        ("data/x64/effect/100_common.elixir.gz", "e_cmn_pup_reflect_s.g1e#0", "e_cmn_pup_reflect_s.g1e", "target", 2284, 2324, 192, "150", "neutral_stable_150_target"),
        ("data/x64/effect/100_common.elixir.gz", "e_cmn_pup_reflect_s.g1e#0", "e_cmn_pup_reflect_s.g1e", "target", 2924, 2964, 192, "75", "neutral_stable_75_target"),
    ]
    focal_fields = ["normalized_path", "member_key", "member_name", "side", "record_start", "reference_offset", "normalized_endpoint", "leaf0_float32", "leaf1_float32", "leaf0_u32_hex", "leaf1_u32_hex", "paired_equal_bits", "paired_finite_floats", "occurrence_role"]
    focal_rows = [{
        "normalized_path": p, "member_key": k, "member_name": n, "side": s, "record_start": start,
        "reference_offset": ref, "normalized_endpoint": endpoint, "leaf0_float32": value, "leaf1_float32": value,
        "leaf0_u32_hex": "", "leaf1_u32_hex": "", "paired_equal_bits": True, "paired_finite_floats": True,
        "occurrence_role": role,
    } for p, k, n, s, start, ref, endpoint, value, role in specs]
    write_tsv(stage101 / "SLOT_LIGHT_FOCAL_EQUAL_FLOAT_FAMILY.tsv", focal_fields, focal_rows)

    (stage91 / "SUMMARY.json").write_text(json.dumps({
        "type": "br_quartet_restoration_reflector_slot_light_section_cardinality_record_role_evidence_summary",
        "tool_version": "0.1.5", "section_member_side_rows": 8, "skipped_rows": 0,
    }), encoding="utf-8")
    card_fields = ["member_key", "member_name", "source_count", "target_count"]
    write_tsv(stage91 / "SLOT_LIGHT_SECTION_CARDINALITY.tsv", card_fields, [
        {"member_key": "e_pc00_eyelight_00.g1e#0", "member_name": "e_PC00_eyelight_00.g1e", "source_count": 2, "target_count": 2},
        {"member_key": "e_pc00_eyelight_01.g1e#0", "member_name": "e_PC00_eyelight_01.g1e", "source_count": 2, "target_count": 2},
        {"member_key": "e_pc02_w5_ringlight_01.g1e#0", "member_name": "e_PC02_w5_ringlight_01.g1e", "source_count": 3, "target_count": 4},
        {"member_key": "e_cmn_pup_reflect_s.g1e#0", "member_name": "e_cmn_pup_reflect_s.g1e", "source_count": 5, "target_count": 5},
    ])

    (stage93 / "SUMMARY.json").write_text(json.dumps({
        "type": "br_quartet_restoration_reflector_slot_light_section_table_record_binding_evidence_summary",
        "tool_version": "0.1.7", "dominant_record_relative_binding_rows": 13,
        "target_table_binding_bulk_reencoding_supported": True, "technical_leaf_semantics_resolved": False,
        "skipped_rows": 0,
    }), encoding="utf-8")
    bind_fields = ["member_key", "side", "table_index", "entry_index", "best_record_start", "best_record_relative_dword", "best_is_focal_family", "exact_dominant_binding", "binding_classification"]
    bindings = []
    for entry, start in enumerate((20528, 21136, 21744)):
        bindings.append({"member_key": "e_pc02_w5_ringlight_01.g1e#0", "side": "target", "table_index": 3, "entry_index": entry, "best_record_start": start, "best_record_relative_dword": -27, "best_is_focal_family": True, "exact_dominant_binding": True, "binding_classification": "dominant_record_relative_binding"})
    for side in ("source", "target"):
        for table, entry, start in ((2, 2, 444), (2, 3, 1004), (3, 0, 1644), (3, 1, 2284), (3, 2, 2924)):
            bindings.append({"member_key": "e_cmn_pup_reflect_s.g1e#0", "side": side, "table_index": table, "entry_index": entry, "best_record_start": start, "best_record_relative_dword": -27, "best_is_focal_family": True, "exact_dominant_binding": True, "binding_classification": "dominant_record_relative_binding"})
    if omit_binding:
        bindings.pop()
    write_tsv(stage93 / "SLOT_LIGHT_SECTION_TABLE_RECORD_BINDING_CANDIDATES.tsv", bind_fields, bindings)
    return reports


class Stage102Tests(unittest.TestCase):
    def test_classifies_values_as_context_dependent_not_ordinals(self) -> None:
        with tempfile.TemporaryDirectory(prefix="stage102-test-") as temp_name:
            reports = prepare_reports(Path(temp_name))
            output, archive, summary = TOOL.build_report(ROOT, create_archive=False, report_root=reports)
            self.assertIsNone(archive)
            self.assertEqual(summary["focal_record_rows"], 21)
            self.assertEqual(summary["focal_member_side_rows"], 8)
            self.assertEqual(summary["full_focal_cardinality_member_side_rows"], 4)
            self.assertEqual(summary["partial_focal_cardinality_member_side_rows"], 4)
            self.assertEqual(summary["exact_focal_table_binding_rows"], 13)
            self.assertEqual(summary["candidate_source_sequence"], ["30", "150", "2"])
            self.assertEqual(summary["candidate_target_sequence"], ["30", "75", "75", "2"])
            self.assertFalse(summary["paired_leaf_is_section_ordinal"])
            self.assertFalse(summary["paired_leaf_is_section_cardinality"])
            self.assertFalse(summary["paired_leaf_is_unique_table_slot_identifier"])
            self.assertFalse(summary["technical_leaf_domain_semantics_resolved"])
            self.assertTrue((output / "SLOT_LIGHT_CANDIDATE_INSERTION_ORDINAL_CONTINUITY.tsv").is_file())

    def test_rejects_incomplete_exact_binding_set(self) -> None:
        with tempfile.TemporaryDirectory(prefix="stage102-negative-") as temp_name:
            reports = prepare_reports(Path(temp_name), omit_binding=True)
            with self.assertRaises(TOOL.Stage102Error):
                TOOL.build_report(ROOT, create_archive=False, report_root=reports)


if __name__ == "__main__":
    unittest.main()
