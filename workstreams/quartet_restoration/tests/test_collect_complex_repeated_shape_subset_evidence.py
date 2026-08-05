from __future__ import annotations

import importlib.util
import struct
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
WORKSTREAM_ROOT = ROOT / "workstreams/quartet_restoration"
sys.path.insert(0, str(WORKSTREAM_ROOT))
TOOL_PATH = WORKSTREAM_ROOT / "collect_complex_repeated_shape_subset_evidence.py"
SPEC = importlib.util.spec_from_file_location("collect_complex_repeated_shape_subset_evidence", TOOL_PATH)
assert SPEC and SPEC.loader
TOOL = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = TOOL
SPEC.loader.exec_module(TOOL)

sys.path.insert(0, str(ROOT / "Blue_Reflection_Text_Tool"))
import br_restoration_tool as BR  # noqa: E402


def lp(raw: bytes) -> bytes:
    return struct.pack("<I", len(raw)) + raw


def make_payload(words: list[int]) -> bytes:
    prefix = struct.pack("<II", 2, 0) + lp(b"name\0") + lp("説明".encode("cp932") + b"\0")
    return prefix + struct.pack(f"<{len(words)}I", *words)


class ComplexRepeatedShapeSubsetTests(unittest.TestCase):
    def repeated_fixture(self):
        source = make_payload([
            1, 0x75400009, 0x7F000000,
            0x7540000A, 0x7F000000,
        ])
        target = make_payload([
            1, 0x75400009, 0x74100014, 0x7F000000,
            0x7540000A, 0x74100014, 0x7F000000,
        ])
        sh = BR.parse_ebd_header_schema(source)
        th = BR.parse_ebd_header_schema(target)
        sp = BR.profile_ebd_post_header_words(source, int(sh["header_end"]))
        tp = BR.profile_ebd_post_header_words(target, int(th["header_end"]))
        deltas = BR.compare_ebd_tag_atoms(sp["atoms"], tp["atoms"])
        shapes = [BR.event_residual_delta_shape_id(row) for row in deltas]
        self.assertEqual(len(shapes), 2)
        self.assertEqual(shapes[0], shapes[1])
        occurrences = [
            {"shape_id": shapes[0], "occurrence_index": index, "cue_positive_occurrence": True}
            for index in range(2)
        ]
        return source, target, shapes[0], occurrences


    def target_evidence_rows(self, *, include_selected: bool = True, fe13_count: int = 3):
        selected = []
        if include_selected:
            selected.append({
                "shape_id": TOOL.TARGET_COMPLEX_SHAPE_ID,
                "selection_priority": "high",
                "sequence_tag": "replace",
                "source_atom_count": "2",
                "target_atom_count": "2",
                "simple_inverse_splice_eligible": "False",
            })
        comparison = [{
            "shape_id": TOOL.TARGET_COMPLEX_SHAPE_ID,
            "cue_occurrence_count": "4",
            "noncue_occurrence_count": "14",
            "shared_cue_noncue_context_archetype_count": "0",
        }]
        occurrences = []
        for index in range(fe13_count):
            occurrences.append({
                "shape_id": TOOL.TARGET_COMPLEX_SHAPE_ID,
                "normalized_path": TOOL.TARGET_EVENT_PATH,
                "occurrence_index": str(index),
                "cue_positive_occurrence": "True",
                "sequence_tag": "replace",
            })
        while len([row for row in occurrences if row["cue_positive_occurrence"] == "True"]) < 4:
            occurrences.append({
                "shape_id": TOOL.TARGET_COMPLEX_SHAPE_ID,
                "normalized_path": "event/event_jp/te02/event_te02_180.ebd",
                "occurrence_index": "0",
                "cue_positive_occurrence": "True",
                "sequence_tag": "replace",
            })
        for index in range(14):
            occurrences.append({
                "shape_id": TOOL.TARGET_COMPLEX_SHAPE_ID,
                "normalized_path": f"event/event_jp/control/event_control_{index:03d}.ebd",
                "occurrence_index": "0",
                "cue_positive_occurrence": "False",
                "sequence_tag": "replace",
            })
        return selected, comparison, occurrences

    def test_target_selection_falls_back_to_occurrence_evidence(self) -> None:
        selected, comparison, occurrences = self.target_evidence_rows(include_selected=False)
        shapes, diagnostics = TOOL.select_target_complex_shape(
            selected_shapes=selected, comparison_rows=comparison, occurrence_rows=occurrences,
        )
        self.assertEqual(shapes, {TOOL.TARGET_COMPLEX_SHAPE_ID})
        self.assertEqual(diagnostics["selection_mode"], "validated_occurrence_evidence_fallback")
        self.assertEqual(diagnostics["target_fe13_cue_occurrence_rows"], 3)

    def test_target_selection_uses_selected_row_when_available(self) -> None:
        selected, comparison, occurrences = self.target_evidence_rows(include_selected=True)
        shapes, diagnostics = TOOL.select_target_complex_shape(
            selected_shapes=selected, comparison_rows=comparison, occurrence_rows=occurrences,
        )
        self.assertEqual(shapes, {TOOL.TARGET_COMPLEX_SHAPE_ID})
        self.assertEqual(diagnostics["selection_mode"], "selected_shape_and_occurrence_evidence")
        self.assertEqual(diagnostics["target_selected_shape_rows"], 1)

    def test_target_selection_rejects_missing_fe13_triplet(self) -> None:
        selected, comparison, occurrences = self.target_evidence_rows(include_selected=True, fe13_count=2)
        with self.assertRaises(TOOL.ComplexRepeatedShapeError):
            TOOL.select_target_complex_shape(
                selected_shapes=selected, comparison_rows=comparison, occurrence_rows=occurrences,
            )

    def test_enumerate_nonempty_subsets(self) -> None:
        rows = [{"occurrence_index": index} for index in range(3)]
        subsets = list(TOOL.enumerate_nonempty_subsets(rows))
        self.assertEqual(len(subsets), 7)
        self.assertNotIn((), [indices for indices, _ in subsets])

    def test_single_occurrence_reduces_repeated_shape_exactly(self) -> None:
        source, target, shape, occurrences = self.repeated_fixture()
        result, _ = TOOL.evaluate_repeated_subset(
            br=BR, source_payload=source, target_payload=target,
            occurrences=[occurrences[0]], shape_id=shape,
        )
        self.assertTrue(result["passes_structural"])
        self.assertTrue(result["strict_improvement"])
        self.assertEqual(result["shape_occurrence_count_before"], 2)
        self.assertEqual(result["shape_occurrence_count_after"], 1)
        self.assertEqual(result["expected_shape_occurrence_count_after"], 1)

    def test_full_subset_reconstructs_original(self) -> None:
        source, target, shape, occurrences = self.repeated_fixture()
        result, residuals = TOOL.evaluate_repeated_subset(
            br=BR, source_payload=source, target_payload=target,
            occurrences=occurrences, shape_id=shape,
        )
        self.assertTrue(result["passes_structural"])
        self.assertTrue(result["strict_improvement"])
        self.assertTrue(result["exact_original"])
        self.assertEqual(result["shape_occurrence_count_after"], 0)
        self.assertEqual(residuals, [])


if __name__ == "__main__":
    unittest.main()
