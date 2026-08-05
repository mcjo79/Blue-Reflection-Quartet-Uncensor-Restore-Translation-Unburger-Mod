from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path

MODULE_PATH = Path(__file__).resolve().parents[1] / "collect_registered_profile_anchor_subset_evidence.py"
SPEC = importlib.util.spec_from_file_location("collect_registered_profile_anchor_subset_evidence", MODULE_PATH)
assert SPEC and SPEC.loader
TOOL = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(TOOL)


class RegisteredProfileAnchorSubsetEvidenceTests(unittest.TestCase):
    def test_enumerate_anchor_subsets_keeps_anchor_mandatory(self) -> None:
        anchor = {"shape_id": "anchor", "occurrence_index": 0}
        optional = [
            {"shape_id": "a", "occurrence_index": 0},
            {"shape_id": "b", "occurrence_index": 0},
        ]
        rows = list(TOOL.enumerate_anchor_subsets(anchor, optional))
        self.assertEqual(len(rows), 4)
        self.assertEqual(rows[0][0], ())
        for _, selected in rows:
            self.assertIs(selected[0], anchor)
            self.assertIn(anchor, selected)

    def test_filter_optional_occurrences_excludes_migrations_and_shared_contexts(self) -> None:
        anchor = {"shape_id": "anchor", "occurrence_index": 0}
        residuals = [
            anchor,
            {"shape_id": "ok", "occurrence_index": 0},
            {"shape_id": "broad", "occurrence_index": 0},
            {"shape_id": "shared", "occurrence_index": 0},
        ]
        optional, excluded = TOOL.filter_optional_occurrences(
            residual_occurrences=residuals,
            anchor=anchor,
            broad_shape_ids={"broad"},
            control_by_shape={"shared": {"shared_cue_noncue_context_archetype_count": "1"}},
        )
        self.assertEqual([row["shape_id"] for row in optional], ["ok"])
        self.assertEqual(
            {row["shape_id"]: row["exclusion_reason"] for row in excluded},
            {
                "broad": "broad_or_recurrent_schema_shape",
                "shared": "known_cue_noncue_shared_context_shape",
            },
        )

    def test_classification_requires_structural_pass_and_strict_improvement(self) -> None:
        ready = TOOL.classify_anchor_subset_result(
            passes_structural=True,
            strict_improvement=True,
            anchor_cue_positive=True,
            anchor_no_shared_context=True,
        )
        self.assertEqual(ready[0], "anchored_subset_strict_improvement_ready_for_local_prototype")
        self.assertTrue(ready[2])

        flat = TOOL.classify_anchor_subset_result(
            passes_structural=True,
            strict_improvement=False,
            anchor_cue_positive=True,
            anchor_no_shared_context=True,
        )
        self.assertEqual(flat[0], "anchored_subset_structurally_valid_without_strict_improvement")
        self.assertFalse(flat[2])

        noncue = TOOL.classify_anchor_subset_result(
            passes_structural=True,
            strict_improvement=True,
            anchor_cue_positive=False,
            anchor_no_shared_context=True,
        )
        self.assertEqual(noncue[0], "anchored_subset_anchor_evidence_not_isolated")
        self.assertFalse(noncue[2])


if __name__ == "__main__":
    unittest.main()
