from __future__ import annotations

import csv
import importlib.util
import tempfile
import unittest
from pathlib import Path

MODULE_PATH = Path(__file__).resolve().parents[1] / "collect_registered_profile_shape_propagation_evidence.py"
SPEC = importlib.util.spec_from_file_location("collect_registered_profile_shape_propagation_evidence", MODULE_PATH)
assert SPEC and SPEC.loader
TOOL = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(TOOL)


def write_tsv(path: Path, fieldnames: list[str], rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


class RegisteredProfileShapePropagationTests(unittest.TestCase):
    def test_classification_requires_cue_and_strict_improvement(self) -> None:
        exact = TOOL.classify_propagation_result(
            binary_structural_pass=True, strict_improvement=True, cue_positive=True,
            no_shared_context=True, exact_context_support_count=1,
        )
        self.assertEqual(exact[0], "registered_profile_exact_context_strict_improvement_candidate")
        self.assertTrue(exact[3])

        cross = TOOL.classify_propagation_result(
            binary_structural_pass=True, strict_improvement=True, cue_positive=True,
            no_shared_context=True, exact_context_support_count=0,
        )
        self.assertEqual(cross[0], "registered_profile_cross_context_strict_improvement_candidate")
        self.assertTrue(cross[3])

        noncue = TOOL.classify_propagation_result(
            binary_structural_pass=True, strict_improvement=True, cue_positive=False,
            no_shared_context=True, exact_context_support_count=1,
        )
        self.assertEqual(noncue[0], "registered_profile_shape_noncue_state_candidate")
        self.assertFalse(noncue[3])

        shared = TOOL.classify_propagation_result(
            binary_structural_pass=True, strict_improvement=True, cue_positive=True,
            no_shared_context=False, exact_context_support_count=1,
        )
        self.assertFalse(shared[3])

    def test_collect_support_rows_uses_only_registered_and_promoted_inputs(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            roots = {name: root / name for name in (
                "event_prototypes", "single_scene", "residual_exact", "backlog_prototype", "subset_search"
            )}
            for path in roots.values():
                path.mkdir(parents=True)

            write_tsv(roots["event_prototypes"] / "EVENT_PROTOTYPE_FILES.tsv",
                      ["profile_id", "normalized_path", "shape_id", "occurrence_index"], [
                {"profile_id": "old_profile", "normalized_path": "event/event_jp/a/event_a_010.ebd", "shape_id": "shape_old", "occurrence_index": 0},
                {"profile_id": "not_registered", "normalized_path": "event/event_jp/z/event_z_010.ebd", "shape_id": "shape_z", "occurrence_index": 0},
            ])
            write_tsv(roots["single_scene"] / "SINGLE_SCENE_COMPOSITE_SPLICES.tsv",
                      ["normalized_path", "shape_id", "occurrence_index"], [
                {"normalized_path": "event/event_jp/b/event_b_020.ebd", "shape_id": "shape_single", "occurrence_index": 0},
            ])
            write_tsv(roots["residual_exact"] / "RESIDUAL_SHAPE_PROMOTION_GATES.tsv",
                      ["shape_id", "stage36_gate"], [
                {"shape_id": "shape_promoted", "stage36_gate": "eligible_for_stage_36_local_prototype_review"},
                {"shape_id": "shape_rejected", "stage36_gate": "not_eligible_for_stage_36"},
            ])
            write_tsv(roots["residual_exact"] / "RESIDUAL_EXACT_CONTEXT_OCCURRENCES.tsv",
                      ["normalized_path", "shape_id", "occurrence_index"], [
                {"normalized_path": "event/event_jp/c/event_c_030.ebd", "shape_id": "shape_promoted", "occurrence_index": 0},
                {"normalized_path": "event/event_jp/c/event_c_030.ebd", "shape_id": "shape_rejected", "occurrence_index": 0},
            ])
            write_tsv(roots["backlog_prototype"] / "PRESENTATION_EVENT_BACKLOG_PROFILES.tsv",
                      ["profile_id", "validation_status"], [
                {"profile_id": "backlog_profile", "validation_status": "passed"},
            ])
            write_tsv(roots["backlog_prototype"] / "PRESENTATION_EVENT_BACKLOG_SELECTED_SPLICES.tsv",
                      ["profile_id", "normalized_path", "shape_id", "occurrence_index", "input_validation_status"], [
                {"profile_id": "backlog_profile", "normalized_path": "event/event_jp/d/event_d_040.ebd", "shape_id": "shape_backlog", "occurrence_index": 0, "input_validation_status": "passed"},
            ])
            write_tsv(roots["subset_search"] / "PRESENTATION_EVENT_SUBSET_SEARCH_SELECTED_OCCURRENCES.tsv",
                      ["normalized_path", "shape_id", "occurrence_index"], [
                {"normalized_path": "event/event_jp/e/event_e_050.ebd", "shape_id": "shape_subset", "occurrence_index": 0},
            ])

            manifests = {profile: {} for profile in (
                "old_profile", "single_scene_event_b", "shared_presentation_c", "backlog_profile", "candidate_subset_e"
            )}
            owners = {
                "event/event_jp/a/event_a_010.ebd": ["old_profile"],
                "event/event_jp/b/event_b_020.ebd": ["single_scene_event_b"],
                "event/event_jp/c/event_c_030.ebd": ["shared_presentation_c"],
                "event/event_jp/d/event_d_040.ebd": ["backlog_profile"],
                "event/event_jp/e/event_e_050.ebd": ["candidate_subset_e"],
            }
            keys = [
                ("event/event_jp/a/event_a_010.ebd", "shape_old", 0),
                ("event/event_jp/b/event_b_020.ebd", "shape_single", 0),
                ("event/event_jp/c/event_c_030.ebd", "shape_promoted", 0),
                ("event/event_jp/c/event_c_030.ebd", "shape_rejected", 0),
                ("event/event_jp/d/event_d_040.ebd", "shape_backlog", 0),
                ("event/event_jp/e/event_e_050.ebd", "shape_subset", 0),
            ]
            occurrence_index = {
                key: {
                    "normalized_path": key[0], "shape_id": key[1], "occurrence_index": str(key[2]),
                    "pair_context_archetype_id": "ctx_" + key[1], "cue_positive_occurrence": "True", "cue_domains": "bath",
                }
                for key in keys
            }
            rows = TOOL.collect_support_rows(
                roots=roots, manifests=manifests, owners=owners, occurrence_index=occurrence_index,
            )
            shapes = {str(row["shape_id"]) for row in rows}
            self.assertEqual(shapes, {"shape_old", "shape_single", "shape_promoted", "shape_backlog", "shape_subset"})
            self.assertNotIn("shape_rejected", shapes)
            self.assertNotIn("shape_z", shapes)

    def test_normalize_event_member(self) -> None:
        self.assertEqual(
            TOOL.normalize_event_member("event/b1/event_jp/ce01/event_ce01_010.ebd"),
            "event/event_jp/ce01/event_ce01_010.ebd",
        )


if __name__ == "__main__":
    unittest.main()
