#!/usr/bin/env python3
from __future__ import annotations

import csv
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "collect_reflector_slot_light_paired_leaf_member_role_callsite_evidence.py"
SPEC = importlib.util.spec_from_file_location("stage103", MODULE_PATH)
assert SPEC and SPEC.loader
TOOL = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(TOOL)


def write_tsv(path: Path, fields: list[str], rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def prepare_reports(root: Path, *, add_exact_callsite: bool = False) -> Path:
    reports = root / "reports"
    stage102 = reports / TOOL.STAGE102_DIR
    stage79 = reports / TOOL.STAGE79_DIR
    stage81 = reports / TOOL.STAGE81_DIR
    stage102.mkdir(parents=True)
    stage79.mkdir(parents=True)
    stage81.mkdir(parents=True)

    (stage102 / "SUMMARY.json").write_text(json.dumps({
        "type": "br_quartet_restoration_reflector_slot_light_paired_leaf_ordinal_section_binding_evidence_summary",
        "tool_version": "0.1.16",
        "focal_record_rows": 21,
        "focal_member_side_rows": 8,
        "paired_leaf_is_section_ordinal": False,
        "paired_leaf_is_section_cardinality": False,
        "paired_leaf_is_unique_table_slot_identifier": False,
        "technical_leaf_domain_semantics_resolved": False,
        "skipped_rows": 0,
        "parameters": {"expected_values": ["1", "2", "30", "50", "75", "100", "150"]},
    }), encoding="utf-8")

    specs = [
        ("data/x64/effect/1000_pc00.elixir.gz", "e_pc00_eyelight_00.g1e#0", "e_PC00_eyelight_00.g1e", "source", ["1"]),
        ("data/x64/effect/1000_pc00.elixir.gz", "e_pc00_eyelight_00.g1e#0", "e_PC00_eyelight_00.g1e", "target", ["1"]),
        ("data/x64/effect/1000_pc00.elixir.gz", "e_pc00_eyelight_01.g1e#0", "e_PC00_eyelight_01.g1e", "source", ["1"]),
        ("data/x64/effect/1000_pc00.elixir.gz", "e_pc00_eyelight_01.g1e#0", "e_PC00_eyelight_01.g1e", "target", ["1"]),
        ("data/x64/effect/1002_pc02.elixir.gz", "e_pc02_w5_ringlight_01.g1e#0", "e_PC02_w5_ringlight_01.g1e", "source", ["30", "150", "2"]),
        ("data/x64/effect/1002_pc02.elixir.gz", "e_pc02_w5_ringlight_01.g1e#0", "e_PC02_w5_ringlight_01.g1e", "target", ["30", "75", "75", "2"]),
        ("data/x64/effect/100_common.elixir.gz", "e_cmn_pup_reflect_s.g1e#0", "e_cmn_pup_reflect_s.g1e", "source", ["1", "100", "50", "150", "75"]),
        ("data/x64/effect/100_common.elixir.gz", "e_cmn_pup_reflect_s.g1e#0", "e_cmn_pup_reflect_s.g1e", "target", ["1", "100", "50", "150", "75"]),
    ]
    ordinal_fields = [
        "normalized_path", "member_key", "member_name", "side", "record_start", "reference_offset",
        "normalized_endpoint", "paired_float_value", "occurrence_role", "focal_ordinal_zero_based",
        "focal_ordinal_one_based", "focal_record_count", "section_count", "focal_count_equals_section_count",
        "exact_table_binding", "table_index", "entry_index", "binding_record_relative_dword", "binding_role",
    ]
    rows: list[dict[str, object]] = []
    start = 100
    for path, key, name, side, values in specs:
        for ordinal, value in enumerate(values):
            role = "other_focal_template_occurrence"
            if key == "e_pc02_w5_ringlight_01.g1e#0" and side == "source" and value == "150":
                role = "candidate_source_150"
            elif key == "e_pc02_w5_ringlight_01.g1e#0" and side == "target" and ordinal == 1:
                role = "candidate_first_target_75_inserted"
            elif key == "e_pc02_w5_ringlight_01.g1e#0" and side == "target" and ordinal == 2:
                role = "candidate_second_target_75_continuing"
            rows.append({
                "normalized_path": path, "member_key": key, "member_name": name, "side": side,
                "record_start": start, "reference_offset": start + 40, "normalized_endpoint": 192,
                "paired_float_value": value, "occurrence_role": role,
                "focal_ordinal_zero_based": ordinal, "focal_ordinal_one_based": ordinal + 1,
                "focal_record_count": len(values), "section_count": len(values),
                "focal_count_equals_section_count": True,
                "exact_table_binding": key == "e_cmn_pup_reflect_s.g1e#0" or (key == "e_pc02_w5_ringlight_01.g1e#0" and side == "target" and ordinal < 3),
                "table_index": 3, "entry_index": ordinal, "binding_record_relative_dword": -27,
                "binding_role": "dominant_record_relative_binding",
            })
            start += 100
    write_tsv(stage102 / "SLOT_LIGHT_FOCAL_ORDINAL_INVENTORY.tsv", ordinal_fields, rows)

    (stage79 / "SUMMARY.json").write_text(json.dumps({
        "type": "br_quartet_restoration_reflector_character_slot_render_member_evidence_summary",
        "tool_version": "0.0.92", "slot_member_rows": 220, "skipped_rows": 0,
    }), encoding="utf-8")
    slot_fields = ["character_slot", "asset_role", "family_key", "normalized_path", "member_name", "member_key", "candidate_id", "domain", "priority", "change_classification", "evidence_sources", "lead_classification", "review_status"]
    write_tsv(stage79 / "REFLECTOR_SLOT_RENDER_MEMBERS.tsv", slot_fields, [
        {"character_slot": "PC00", "asset_role": "eyelight", "normalized_path": "data/x64/effect/1000_pc00.elixir.gz", "member_name": "e_PC00_eyelight_00.g1e", "member_key": "e_pc00_eyelight_00.g1e#0"},
        {"character_slot": "PC00", "asset_role": "eyelight", "normalized_path": "data/x64/effect/1000_pc00.elixir.gz", "member_name": "e_PC00_eyelight_01.g1e", "member_key": "e_pc00_eyelight_01.g1e#0"},
        {"character_slot": "PC02", "asset_role": "ringlight", "normalized_path": "data/x64/effect/1002_pc02.elixir.gz", "member_name": "e_PC02_w5_ringlight_01.g1e", "member_key": "e_pc02_w5_ringlight_01.g1e#0"},
    ])

    (stage81 / "SUMMARY.json").write_text(json.dumps({
        "type": "br_quartet_restoration_reflector_ringlight_control_callsite_evidence_summary",
        "tool_version": "0.0.95", "control_member_rows": 525,
        "container_exact_reference_rows": 1 if add_exact_callsite else 0,
        "transformation_event_rows_scanned": 68,
        "transformation_event_exact_reference_rows": 0,
        "exact_name_callsite_binding_resolved": add_exact_callsite,
        "skipped_rows": 0,
    }), encoding="utf-8")
    parent_fields = ["normalized_path", "member_key", "member_name", "extension", "source_size", "target_size", "classification", "control_scope", "changed_word_rows", "matched_common_transition_rows", "review_status"]
    write_tsv(stage81 / "RINGLIGHT_PARENT_CONTAINER_CONTROLS.tsv", parent_fields, [
        {"normalized_path": "data/x64/effect/100_common.elixir.gz", "member_key": "e_cmn_pup_reflect_s.g1e#0", "member_name": "e_cmn_pup_reflect_s.g1e", "classification": "size_or_structure_changed_control", "control_scope": "neutral_non_transformation_name_control"},
        {"normalized_path": "data/x64/effect/1000_pc00.elixir.gz", "member_key": "e_pc00_eyelight_00.g1e#0", "member_name": "e_PC00_eyelight_00.g1e", "classification": "size_or_structure_changed_control", "control_scope": "eyelight_named_control"},
        {"normalized_path": "data/x64/effect/1000_pc00.elixir.gz", "member_key": "e_pc00_eyelight_01.g1e#0", "member_name": "e_PC00_eyelight_01.g1e", "classification": "size_or_structure_changed_control", "control_scope": "eyelight_named_control"},
        {"normalized_path": "data/x64/effect/1002_pc02.elixir.gz", "member_key": "e_pc02_w5_ringlight_01.g1e#0", "member_name": "e_PC02_w5_ringlight_01.g1e", "classification": "size_or_structure_changed_control", "control_scope": "ringlight_named_control"},
    ])
    ref_fields = ["normalized_path", "side", "referencing_member_key", "referencing_member_name", "referenced_slot", "token_form", "encoding", "token_sha256", "hit_count", "first_offsets", "self_reference", "binding_status"]
    write_tsv(stage81 / "RINGLIGHT_EFFECT_CONTAINER_EXACT_REFERENCES.tsv", ref_fields, ([{"normalized_path": "x", "side": "source"}] if add_exact_callsite else []))
    event_fields = ["normalized_path", "family_id", "family_name", "event_slot", "event_classification", "side", "referenced_slot", "token_form", "encoding", "token_sha256", "hit_count", "first_offsets", "binding_status"]
    write_tsv(stage81 / "RINGLIGHT_TRANSFORMATION_EVENT_EXACT_REFERENCES.tsv", event_fields, [])
    return reports


class Stage103Tests(unittest.TestCase):
    def test_cross_role_reuse_and_no_exact_callsite(self) -> None:
        with tempfile.TemporaryDirectory(prefix="stage103-test-") as temp_name:
            reports = prepare_reports(Path(temp_name))
            output, archive, summary = TOOL.build_report(ROOT, create_archive=False, report_root=reports)
            self.assertIsNone(archive)
            self.assertEqual(summary["focal_record_rows"], 21)
            self.assertEqual(summary["focal_member_rows"], 4)
            self.assertEqual(summary["technical_member_role_rows"], 3)
            self.assertEqual(summary["cross_member_role_values"], ["1", "75", "150"])
            self.assertFalse(summary["paired_leaf_is_unique_member_role_identifier"])
            self.assertFalse(summary["paired_leaf_is_unique_character_slot_identifier"])
            self.assertFalse(summary["exact_name_callsite_binding_resolved"])
            self.assertFalse(summary["technical_leaf_domain_semantics_resolved"])
            self.assertTrue((output / "SLOT_LIGHT_VALUE_MEMBER_ROLE_DISTRIBUTION.tsv").is_file())

    def test_rejects_changed_exact_callsite_prerequisite(self) -> None:
        with tempfile.TemporaryDirectory(prefix="stage103-negative-") as temp_name:
            reports = prepare_reports(Path(temp_name), add_exact_callsite=True)
            with self.assertRaises(TOOL.Stage103Error):
                TOOL.build_report(ROOT, create_archive=False, report_root=reports)


if __name__ == "__main__":
    unittest.main()
