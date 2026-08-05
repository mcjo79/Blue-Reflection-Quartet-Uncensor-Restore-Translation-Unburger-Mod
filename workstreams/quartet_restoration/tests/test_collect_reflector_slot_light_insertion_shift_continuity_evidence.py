from __future__ import annotations

import csv
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "workstreams/quartet_restoration/collect_reflector_slot_light_insertion_shift_continuity_evidence.py"
SPEC = importlib.util.spec_from_file_location("stage99_tool", SCRIPT)
assert SPEC and SPEC.loader
TOOL = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(TOOL)


def write_tsv(path: Path, fields: list[str], rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def prepare_reports(root: Path, *, second_dword104_target: int = 2144) -> Path:
    reports = root / "reports"
    stage92 = reports / TOOL.STAGE92_DIR
    stage95 = reports / TOOL.STAGE95_DIR
    stage96 = reports / TOOL.STAGE96_DIR
    stage98 = reports / TOOL.STAGE98_DIR
    for directory in (stage92, stage95, stage96, stage98):
        directory.mkdir(parents=True)

    (stage92 / "SUMMARY.json").write_text(json.dumps({
        "type": "br_quartet_restoration_reflector_slot_light_record_occurrence_identity_evidence_summary",
        "tool_version": "0.1.6",
        "candidate_minimum_edit_model_rows": 2,
        "candidate_target_occurrence_identity_resolved": False,
        "skipped_rows": 0,
    }), encoding="utf-8")
    write_tsv(stage92 / "SLOT_LIGHT_CANDIDATE_EDIT_MODELS.tsv", [
        "model_id", "minimal_edit_model",
    ], [
        {"model_id": "first", "minimal_edit_model": True},
        {"model_id": "second", "minimal_edit_model": True},
        {"model_id": "nonminimal", "minimal_edit_model": False},
    ])

    (stage95 / "SUMMARY.json").write_text(json.dumps({
        "type": "br_quartet_restoration_reflector_slot_light_anchored_block_envelope_evidence_summary",
        "tool_version": "0.1.9",
        "focal_occurrence_rows": 21,
        "anchored_block_span_field_confirmed": True,
        "candidate_target_occurrence_identity_resolved": False,
        "skipped_rows": 0,
    }), encoding="utf-8")
    layout_fields = ["cluster_role", "side", "reference_index", "variant_label", "anchor"]
    layout_rows = [
        {"cluster_role": "candidate_ringlight", "side": "source", "reference_index": 0, "variant_label": "equal_float_30", "anchor": 20404},
        {"cluster_role": "candidate_ringlight", "side": "source", "reference_index": 1, "variant_label": "equal_float_150", "anchor": 21012},
        {"cluster_role": "candidate_ringlight", "side": "source", "reference_index": 2, "variant_label": "equal_float_2", "anchor": 21620},
        {"cluster_role": "candidate_ringlight", "side": "target", "reference_index": 0, "variant_label": "equal_float_30", "anchor": 20420},
        {"cluster_role": "candidate_ringlight", "side": "target", "reference_index": 1, "variant_label": "equal_float_75", "anchor": 21028},
        {"cluster_role": "candidate_ringlight", "side": "target", "reference_index": 2, "variant_label": "equal_float_75", "anchor": 21636},
        {"cluster_role": "candidate_ringlight", "side": "target", "reference_index": 3, "variant_label": "equal_float_2", "anchor": 22244},
    ]
    write_tsv(stage95 / "SLOT_LIGHT_ANCHORED_BLOCK_LAYOUT.tsv", layout_fields, layout_rows)

    (stage96 / "SUMMARY.json").write_text(json.dumps({
        "type": "br_quartet_restoration_reflector_slot_light_anchored_block_internal_change_evidence_summary",
        "tool_version": "0.1.10",
        "internal_dword_difference_rows": 23,
        "candidate_target_occurrence_identity_resolved": False,
        "skipped_rows": 0,
    }), encoding="utf-8")
    internal_fields = ["comparison", "relative_dword", "left_i32", "right_i32"]
    internal_rows = [
        {"comparison": "stable_30_source_target", "relative_dword": 37, "left_i32": -276, "right_i32": -292},
        {"comparison": "stable_2_source_target", "relative_dword": 37, "left_i32": -1492, "right_i32": -2116},
        {"comparison": "stable_2_source_target", "relative_dword": 104, "left_i32": 1536, "right_i32": 2192},
        {"comparison": "ambiguous_150_to_first_75", "relative_dword": 37, "left_i32": -884, "right_i32": -900},
        {"comparison": "ambiguous_150_to_first_75", "relative_dword": 104, "left_i32": 1488, "right_i32": 2096},
        {"comparison": "ambiguous_150_to_second_75", "relative_dword": 37, "left_i32": -884, "right_i32": -1508},
        {"comparison": "ambiguous_150_to_second_75", "relative_dword": 104, "left_i32": 1488, "right_i32": second_dword104_target},
    ]
    while len(internal_rows) < 23:
        i = len(internal_rows)
        internal_rows.append({"comparison": f"dummy_{i}", "relative_dword": 200 + i, "left_i32": i, "right_i32": i + 1})
    write_tsv(stage96 / "SLOT_LIGHT_INTERNAL_DWORD_DIFFERENCES.tsv", internal_fields, internal_rows)

    (stage98 / "SUMMARY.json").write_text(json.dumps({
        "type": "br_quartet_restoration_reflector_slot_light_trailer_record_layout_evidence_summary",
        "tool_version": "0.1.12",
        "same_variant_occurrence_rows": 7,
        "same_variant_block_comparison_rows": 9,
        "candidate_target_occurrence_identity_resolved": False,
        "prototype_candidate_rows": 0,
        "skipped_rows": 0,
    }), encoding="utf-8")
    comparison_fields = ["comparison", "full_shared_span_dword_differences"]
    comparison_rows = [{"comparison": "candidate_target75_duplicate_pair", "full_shared_span_dword_differences": 7}]
    while len(comparison_rows) < 9:
        comparison_rows.append({"comparison": f"dummy_{len(comparison_rows)}", "full_shared_span_dword_differences": 0})
    write_tsv(stage98 / "SLOT_LIGHT_SAME_VARIANT_BLOCK_COMPARISON.tsv", comparison_fields, comparison_rows)
    local_fields = ["comparison", "relative_dword", "center_exact"]
    write_tsv(stage98 / "SLOT_LIGHT_RESIDUAL_LOCAL_WINDOW_COMPARISON.tsv", local_fields, [
        {"comparison": "candidate_target75_duplicate_pair", "relative_dword": pos, "center_exact": False}
        for pos in (126, 128, 129, 132, 133)
    ])
    return reports


class Stage99Tests(unittest.TestCase):
    def test_unique_shift_propagation_resolves_second_target_as_structural_continuation(self) -> None:
        with tempfile.TemporaryDirectory(prefix="stage99-test-") as temp_name:
            reports = prepare_reports(Path(temp_name))
            output, archive, summary = TOOL.build_report(ROOT, create_archive=False, report_root=reports)
            self.assertIsNone(archive)
            self.assertTrue(summary["candidate_target_occurrence_identity_resolved"])
            self.assertEqual(summary["candidate_target_occurrence_identity"], "second_target_75")
            self.assertEqual(summary["inserted_target_occurrence"], "first_target_75")
            self.assertEqual(summary["continuity_gate_passing_models"], 1)
            self.assertEqual(summary["prototype_candidate_rows"], 0)
            self.assertFalse(summary["brightness_semantics_confirmed"])
            self.assertTrue((output / "SLOT_LIGHT_OCCURRENCE_CONTINUITY_DECISION.tsv").is_file())

    def test_inconsistent_dword104_propagation_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory(prefix="stage99-negative-") as temp_name:
            reports = prepare_reports(Path(temp_name), second_dword104_target=2200)
            with self.assertRaises(TOOL.Stage99Error):
                TOOL.build_report(ROOT, create_archive=False, report_root=reports)


if __name__ == "__main__":
    unittest.main()
