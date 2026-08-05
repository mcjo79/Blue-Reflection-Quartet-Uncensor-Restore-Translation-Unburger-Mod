from __future__ import annotations

import hashlib
import importlib.util
import json
import struct
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
WORKSTREAM = ROOT / "workstreams/quartet_restoration"
sys.path.insert(0, str(WORKSTREAM))
path = WORKSTREAM / "build_fe13_remaining_residual_prototype.py"
spec = importlib.util.spec_from_file_location("build_fe13_remaining_residual_prototype", path)
assert spec and spec.loader
TOOL = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = TOOL
spec.loader.exec_module(TOOL)

sys.path.insert(0, str(ROOT / "Blue_Reflection_Text_Tool"))
import br_restoration_tool as BR


def length_prefixed(raw: bytes) -> bytes:
    return struct.pack("<I", len(raw)) + raw


def payload(words: list[int]) -> bytes:
    prefix = (
        struct.pack("<II", 2, 0)
        + length_prefixed(b"name\0")
        + length_prefixed("説明".encode("cp932") + b"\0")
    )
    return prefix + struct.pack(f"<{len(words)}I", *words)


def shape_ids(source: bytes, target: bytes) -> list[str]:
    source_header = BR.parse_ebd_header_schema(source)
    target_header = BR.parse_ebd_header_schema(target)
    source_profile = BR.profile_ebd_post_header_words(source, int(source_header["header_end"]))
    target_profile = BR.profile_ebd_post_header_words(target, int(target_header["header_end"]))
    return [
        BR.event_residual_delta_shape_id(row)
        for row in BR.compare_ebd_tag_atoms(source_profile["atoms"], target_profile["atoms"])
    ]


class Stage60Tests(unittest.TestCase):
    def fixture(self) -> tuple[bytes, bytes, list[str]]:
        source = payload(
            [
                1,
                0x7B96EE8A,
                0x7F000000,
                0x75400009,
                0x7F000000,
                0x7540000A,
                0x7F000000,
            ]
        )
        target = payload(
            [
                1,
                0x7B96EE8A,
                0x75834283,
                0x7F000000,
                0x75400009,
                0x74100014,
                0x7F000000,
                0x7540000A,
                0x74200015,
                0x7F000000,
            ]
        )
        shapes = shape_ids(source, target)
        self.assertEqual(len(shapes), 3)
        return source, target, shapes

    def test_reconstruct_best_candidate_removes_all_three_residuals_and_roundtrips(self) -> None:
        source, target, shapes = self.fixture()
        primary, _, _, _ = TOOL.stage59.inverse_candidate(
            br=BR, source_payload=source, target_payload=target, shape_ids=[shapes[0]]
        )
        final, _, _, _ = TOOL.stage59.inverse_candidate(
            br=BR, source_payload=source, target_payload=primary, shape_ids=shapes[1:]
        )
        old = (
            TOOL.PRIMARY_SHAPE_ID,
            TOOL.SELECTED_SHAPE_IDS,
            TOOL.EXPECTED_CANDIDATE_SHA256,
            TOOL.EXPECTED_CANDIDATE_SIZE,
            TOOL.EXPECTED_STAGE51_DISTANCE,
            TOOL.EXPECTED_CANDIDATE_DISTANCE,
            TOOL.EXPECTED_IMPROVEMENT_OVER_STAGE51,
            TOOL.EXPECTED_QUARTET_DISTANCE,
            TOOL.stage59.PRIMARY_CANDIDATE_SHA256,
        )
        try:
            TOOL.PRIMARY_SHAPE_ID = shapes[0]
            TOOL.SELECTED_SHAPE_IDS = tuple(shapes[1:])
            TOOL.EXPECTED_CANDIDATE_SHA256 = hashlib.sha256(final).hexdigest()
            TOOL.EXPECTED_CANDIDATE_SIZE = len(final)
            TOOL.EXPECTED_STAGE51_DISTANCE = TOOL.subset.byte_difference_count(primary, source)
            TOOL.EXPECTED_CANDIDATE_DISTANCE = TOOL.subset.byte_difference_count(final, source)
            TOOL.EXPECTED_IMPROVEMENT_OVER_STAGE51 = (
                TOOL.EXPECTED_STAGE51_DISTANCE - TOOL.EXPECTED_CANDIDATE_DISTANCE
            )
            TOOL.EXPECTED_QUARTET_DISTANCE = TOOL.subset.byte_difference_count(target, source)
            TOOL.stage59.PRIMARY_CANDIDATE_SHA256 = hashlib.sha256(primary).hexdigest()
            candidate, metadata, residuals = TOOL.reconstruct_best_candidate(BR, source, target)
        finally:
            (
                TOOL.PRIMARY_SHAPE_ID,
                TOOL.SELECTED_SHAPE_IDS,
                TOOL.EXPECTED_CANDIDATE_SHA256,
                TOOL.EXPECTED_CANDIDATE_SIZE,
                TOOL.EXPECTED_STAGE51_DISTANCE,
                TOOL.EXPECTED_CANDIDATE_DISTANCE,
                TOOL.EXPECTED_IMPROVEMENT_OVER_STAGE51,
                TOOL.EXPECTED_QUARTET_DISTANCE,
                TOOL.stage59.PRIMARY_CANDIDATE_SHA256,
            ) = old
        self.assertEqual(candidate, source)
        self.assertEqual(residuals, [])
        self.assertTrue(all(metadata["checks"].values()))

    def write_canonical_stage59(self, root: Path, *, failed: bool = False) -> None:
        (root / "SUMMARY.json").write_text(
            json.dumps(
                {
                    "type": "br_quartet_restoration_fe13_remaining_residual_evidence_summary",
                    "tool_version": "0.0.68",
                    "target_event_rows": 1,
                    "analyzed_event_rows": 1,
                    "tested_combination_rows": 3,
                    "selected_occurrence_rows": 4,
                    "promotable_combination_rows": 3,
                    "validation_rows": 39,
                    "validation_failures": 0,
                    "strict_improvement_failures": 0,
                    "skipped_rows": 0,
                    "remaining_shape_ids": list(TOOL.SELECTED_SHAPE_IDS),
                }
            ),
            encoding="utf-8",
        )
        BR.write_tsv(
            root / "FE13_REMAINING_RESIDUAL_EVENTS.tsv",
            [
                "normalized_path", "registered_profile_id", "primary_removed_shape_id",
                "primary_candidate_sha256", "quartet_distance_to_original",
                "stage51_distance_to_original", "best_combination_id", "best_selected_shape_ids",
                "best_candidate_distance_to_original", "best_distance_improvement_over_stage51",
                "best_classification",
            ],
            [
                {
                    "normalized_path": TOOL.TARGET_EVENT_PATH,
                    "registered_profile_id": TOOL.SOURCE_PROFILE_ID,
                    "primary_removed_shape_id": TOOL.PRIMARY_SHAPE_ID,
                    "primary_candidate_sha256": TOOL.stage59.PRIMARY_CANDIDATE_SHA256,
                    "quartet_distance_to_original": TOOL.EXPECTED_QUARTET_DISTANCE,
                    "stage51_distance_to_original": TOOL.EXPECTED_STAGE51_DISTANCE,
                    "best_combination_id": TOOL.EXPECTED_COMBINATION_ID,
                    "best_selected_shape_ids": ";".join(TOOL.SELECTED_SHAPE_IDS),
                    "best_candidate_distance_to_original": TOOL.EXPECTED_CANDIDATE_DISTANCE,
                    "best_distance_improvement_over_stage51": TOOL.EXPECTED_IMPROVEMENT_OVER_STAGE51,
                    "best_classification": "strict_improvement_ready_for_separate_local_prototype",
                }
            ],
        )
        rows = []
        for index, shape_text in enumerate(
            [TOOL.SELECTED_SHAPE_IDS[0], TOOL.SELECTED_SHAPE_IDS[1], ";".join(TOOL.SELECTED_SHAPE_IDS)],
            start=1,
        ):
            pair = index == 3
            rows.append(
                {
                    "combination_id": f"fe13_090_remaining_{index}",
                    "selected_shape_ids": shape_text,
                    "selected_shape_count": 2 if pair else 1,
                    "stage51_distance_to_original": TOOL.EXPECTED_STAGE51_DISTANCE,
                    "candidate_distance_to_original": TOOL.EXPECTED_CANDIDATE_DISTANCE if pair else TOOL.EXPECTED_STAGE51_DISTANCE - index,
                    "distance_improvement_over_stage51": TOOL.EXPECTED_IMPROVEMENT_OVER_STAGE51 if pair else index,
                    "candidate_sha256": TOOL.EXPECTED_CANDIDATE_SHA256 if pair else "a" * 64,
                    "candidate_size": TOOL.EXPECTED_CANDIDATE_SIZE if pair else TOOL.EXPECTED_CANDIDATE_SIZE + index,
                    "remaining_residual_rows": 0 if pair else 1,
                    "passes_structural_gates": True,
                    "strict_improvement": True,
                    "safe_to_build_separate_local_profile": True,
                    "classification": "strict_improvement_ready_for_separate_local_prototype",
                }
            )
        BR.write_tsv(root / "FE13_REMAINING_RESIDUAL_COMBINATIONS.tsv", list(rows[0]), rows)
        BR.write_tsv(
            root / "FE13_REMAINING_RESIDUAL_SELECTED_OCCURRENCES.tsv",
            [
                "combination_id", "shape_id", "occurrence_index", "sequence_tag",
                "source_atom_count", "target_atom_count", "semantic_status",
            ],
            [
                {
                    "combination_id": TOOL.EXPECTED_COMBINATION_ID,
                    "shape_id": shape,
                    "occurrence_index": 0,
                    "sequence_tag": "insert",
                    "source_atom_count": 0,
                    "target_atom_count": 1,
                    "semantic_status": "unassigned",
                }
                for shape in TOOL.SELECTED_SHAPE_IDS
            ]
            + [
                {
                    "combination_id": "fe13_090_remaining_1",
                    "shape_id": TOOL.SELECTED_SHAPE_IDS[0],
                    "occurrence_index": 0,
                    "sequence_tag": "insert",
                    "source_atom_count": 0,
                    "target_atom_count": 1,
                    "semantic_status": "unassigned",
                },
                {
                    "combination_id": "fe13_090_remaining_2",
                    "shape_id": TOOL.SELECTED_SHAPE_IDS[1],
                    "occurrence_index": 0,
                    "sequence_tag": "insert",
                    "source_atom_count": 0,
                    "target_atom_count": 1,
                    "semantic_status": "unassigned",
                },
            ],
        )
        tests = []
        for index in range(1, 4):
            for n in range(13):
                tests.append(
                    {
                        "combination_id": f"fe13_090_remaining_{index}",
                        "passed": not (failed and index == 3 and n == 0),
                    }
                )
        BR.write_tsv(root / "FE13_REMAINING_RESIDUAL_TESTS.tsv", ["combination_id", "passed"], tests)
        BR.write_tsv(root / "FE13_REMAINING_RESIDUAL_SKIPPED.tsv", ["reason"], [])

    def test_validate_stage59_accepts_canonical_best_pair(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            self.write_canonical_stage59(root)
            summary, event, pair, tests = TOOL.validate_stage59(root)
            self.assertEqual(summary["tool_version"], "0.0.68")
            self.assertEqual(event["best_combination_id"], TOOL.EXPECTED_COMBINATION_ID)
            self.assertEqual(pair["candidate_sha256"], TOOL.EXPECTED_CANDIDATE_SHA256)
            self.assertEqual(len(tests), 13)

    def test_validate_stage59_rejects_failed_pair_validation(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            self.write_canonical_stage59(root, failed=True)
            with self.assertRaises(TOOL.Fe13RemainingPrototypeError):
                TOOL.validate_stage59(root)


if __name__ == "__main__":
    unittest.main()
