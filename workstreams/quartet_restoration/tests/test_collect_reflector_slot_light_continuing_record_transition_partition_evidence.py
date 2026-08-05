from __future__ import annotations

import csv
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "workstreams/quartet_restoration/collect_reflector_slot_light_continuing_record_transition_partition_evidence.py"
SPEC = importlib.util.spec_from_file_location("stage100_tool", SCRIPT)
assert SPEC and SPEC.loader
TOOL = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(TOOL)


def write_tsv(path: Path, fields: list[str], rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def prepare_reports(root: Path, *, resolved_identity: str = "second_target_75") -> Path:
    reports = root / "reports"
    stage91 = reports / TOOL.STAGE91_DIR
    stage96 = reports / TOOL.STAGE96_DIR
    stage99 = reports / TOOL.STAGE99_DIR
    for directory in (stage91, stage96, stage99):
        directory.mkdir(parents=True)

    (stage91 / "SUMMARY.json").write_text(json.dumps({
        "type": "br_quartet_restoration_reflector_slot_light_section_cardinality_record_role_evidence_summary",
        "tool_version": "0.1.5",
        "reference_record_rows": 177,
        "reference_record_dword_rows": 1947,
        "skipped_rows": 0,
    }), encoding="utf-8")
    fields = ["normalized_path", "member_key", "member_name", "side", "reference_offset", "record_start", "relative_dword", "u32_hex", "float32"]
    records: list[tuple[str, str, str, str, int, int, str]] = [
        ("data/x64/effect/1002_pc02.elixir.gz", "e_pc02_w5_ringlight_01.g1e#0", "e_PC02_w5_ringlight_01.g1e", "source", 21160, 21120, "150"),
        ("data/x64/effect/1002_pc02.elixir.gz", "e_pc02_w5_ringlight_01.g1e#0", "e_PC02_w5_ringlight_01.g1e", "target", 21176, 21136, "75"),
        ("data/x64/effect/1002_pc02.elixir.gz", "e_pc02_w5_ringlight_01.g1e#0", "e_PC02_w5_ringlight_01.g1e", "target", 21784, 21744, "75"),
        ("data/x64/effect/100_common.elixir.gz", "e_cmn_pup_reflect_s.g1e#0", "e_cmn_pup_reflect_s.g1e", "source", 2324, 2284, "150"),
        ("data/x64/effect/100_common.elixir.gz", "e_cmn_pup_reflect_s.g1e#0", "e_cmn_pup_reflect_s.g1e", "source", 2964, 2924, "75"),
        ("data/x64/effect/100_common.elixir.gz", "e_cmn_pup_reflect_s.g1e#0", "e_cmn_pup_reflect_s.g1e", "target", 2324, 2284, "150"),
        ("data/x64/effect/100_common.elixir.gz", "e_cmn_pup_reflect_s.g1e#0", "e_cmn_pup_reflect_s.g1e", "target", 2964, 2924, "75"),
    ]
    for index in range(170):
        side = "source" if index % 2 == 0 else "target"
        records.append(("dummy/path", f"dummy_{index}.g1e#0", f"dummy_{index}.g1e", side, 1000 + index * 64 + 40, 1000 + index * 64, "0"))
    rows: list[dict[str, object]] = []
    for path, key, name, side, ref, start, value in records:
        u32 = {"150": "0x43160000", "75": "0x42960000", "0": "0x00000000"}[value]
        for dword in range(11):
            rows.append({
                "normalized_path": path, "member_key": key, "member_name": name, "side": side,
                "reference_offset": ref, "record_start": start, "relative_dword": dword,
                "u32_hex": u32 if dword in (0, 1) else "0x00000000",
                "float32": value if dword in (0, 1) else "0",
            })
    write_tsv(stage91 / "SLOT_LIGHT_REFERENCE_RECORD_DWORDS.tsv", fields, rows)

    (stage96 / "SUMMARY.json").write_text(json.dumps({
        "type": "br_quartet_restoration_reflector_slot_light_anchored_block_internal_change_evidence_summary",
        "tool_version": "0.1.10", "internal_dword_difference_rows": 23,
        "candidate_target_occurrence_identity_resolved": False, "skipped_rows": 0,
    }), encoding="utf-8")
    diff_fields = ["comparison", "relative_dword", "relative_byte", "segment", "left_u32_hex", "right_u32_hex", "left_i32", "right_i32", "left_float32", "right_float32"]
    diffs = [
        {"comparison": TOOL.CONTINUING_COMPARISON, "relative_dword": 27, "relative_byte": 108, "segment": "reference_record", "left_u32_hex": "0x43160000", "right_u32_hex": "0x42960000", "left_i32": 1125515264, "right_i32": 1117126656, "left_float32": "150", "right_float32": "75"},
        {"comparison": TOOL.CONTINUING_COMPARISON, "relative_dword": 28, "relative_byte": 112, "segment": "reference_record", "left_u32_hex": "0x43160000", "right_u32_hex": "0x42960000", "left_i32": 1125515264, "right_i32": 1117126656, "left_float32": "150", "right_float32": "75"},
        {"comparison": TOOL.CONTINUING_COMPARISON, "relative_dword": 37, "relative_byte": 148, "segment": "reference_record", "left_u32_hex": "0xfffffc8c", "right_u32_hex": "0xfffffa1c", "left_i32": -884, "right_i32": -1508, "left_float32": "", "right_float32": ""},
        {"comparison": TOOL.CONTINUING_COMPARISON, "relative_dword": 104, "relative_byte": 416, "segment": "post_record_trailer", "left_u32_hex": "0x000005d0", "right_u32_hex": "0x00000860", "left_i32": 1488, "right_i32": 2144, "left_float32": "", "right_float32": ""},
    ]
    while len(diffs) < 23:
        i = len(diffs)
        diffs.append({"comparison": f"dummy_{i}", "relative_dword": 200 + i, "relative_byte": (200 + i) * 4, "segment": "dummy", "left_u32_hex": "0x0", "right_u32_hex": "0x1", "left_i32": 0, "right_i32": 1, "left_float32": "", "right_float32": ""})
    write_tsv(stage96 / "SLOT_LIGHT_INTERNAL_DWORD_DIFFERENCES.tsv", diff_fields, diffs)

    (stage99 / "SUMMARY.json").write_text(json.dumps({
        "type": "br_quartet_restoration_reflector_slot_light_insertion_shift_continuity_evidence_summary",
        "tool_version": "0.1.13", "candidate_target_occurrence_identity_resolved": resolved_identity == "second_target_75",
        "candidate_target_occurrence_identity": resolved_identity, "inserted_target_occurrence": "first_target_75",
        "winning_model_id": TOOL.WINNING_MODEL, "continuity_gate_passing_models": 1,
        "prototype_candidate_rows": 0, "skipped_rows": 0,
    }), encoding="utf-8")
    shift_fields = ["model_id", "source_occurrence", "target_occurrence", "source_anchor", "target_anchor", "anchor_shift", "reference_compensates_anchor_shift", "trailer_dword104_source_i32", "trailer_dword104_target_i32", "trailer_dword104_delta", "trailer_delta_minus_anchor_shift"]
    shifts = [
        {"model_id": TOOL.WINNING_MODEL, "source_occurrence": "source_30", "target_occurrence": "target_30", "source_anchor": 20404, "target_anchor": 20420, "anchor_shift": 16, "reference_compensates_anchor_shift": True, "trailer_dword104_source_i32": "", "trailer_dword104_target_i32": "", "trailer_dword104_delta": 0, "trailer_delta_minus_anchor_shift": -16},
        {"model_id": TOOL.WINNING_MODEL, "source_occurrence": "source_150", "target_occurrence": "target_75_second", "source_anchor": 21012, "target_anchor": 21636, "anchor_shift": 624, "reference_compensates_anchor_shift": True, "trailer_dword104_source_i32": 1488, "trailer_dword104_target_i32": 2144, "trailer_dword104_delta": 656, "trailer_delta_minus_anchor_shift": 32},
        {"model_id": TOOL.WINNING_MODEL, "source_occurrence": "source_2", "target_occurrence": "target_2", "source_anchor": 21620, "target_anchor": 22244, "anchor_shift": 624, "reference_compensates_anchor_shift": True, "trailer_dword104_source_i32": 1536, "trailer_dword104_target_i32": 2192, "trailer_dword104_delta": 656, "trailer_delta_minus_anchor_shift": 32},
    ]
    shifts += [dict(row, model_id="losing_model") for row in shifts]
    write_tsv(stage99 / "SLOT_LIGHT_MATCHED_OCCURRENCE_SHIFTS.tsv", shift_fields, shifts)
    return reports


class Stage100Tests(unittest.TestCase):
    def test_partitions_four_transitions_and_keeps_two_leaf_semantics_unresolved(self) -> None:
        with tempfile.TemporaryDirectory(prefix="stage100-test-") as temp_name:
            reports = prepare_reports(Path(temp_name))
            output, archive, summary = TOOL.build_report(ROOT, create_archive=False, report_root=reports)
            self.assertIsNone(archive)
            self.assertTrue(summary["candidate_target_occurrence_identity_resolved"])
            self.assertEqual(summary["candidate_target_occurrence_identity"], "second_target_75")
            self.assertEqual(summary["continuing_transition_rows"], 4)
            self.assertEqual(summary["proven_exact_relocation_rows"], 1)
            self.assertEqual(summary["bounded_trailer_propagation_rows"], 1)
            self.assertEqual(summary["unresolved_paired_numeric_leaf_rows"], 2)
            self.assertEqual(summary["paired_75_or_150_occurrence_rows"], 7)
            self.assertTrue(summary["neutral_stable_150_and_75_variants_confirmed"])
            self.assertFalse(summary["technical_leaf_semantics_resolved"])
            self.assertTrue((output / "SLOT_LIGHT_CONTINUING_TRANSITION_PARTITION.tsv").is_file())

    def test_rejects_unresolved_or_wrong_stage99_identity(self) -> None:
        with tempfile.TemporaryDirectory(prefix="stage100-negative-") as temp_name:
            reports = prepare_reports(Path(temp_name), resolved_identity="first_target_75")
            with self.assertRaises(TOOL.Stage100Error):
                TOOL.build_report(ROOT, create_archive=False, report_root=reports)


if __name__ == "__main__":
    unittest.main()
