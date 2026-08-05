from __future__ import annotations

import importlib.util
import struct
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
WORKSTREAM = ROOT / "workstreams/quartet_restoration"
sys.path.insert(0, str(WORKSTREAM))
path = WORKSTREAM / "collect_fe13_remaining_residual_evidence.py"
spec = importlib.util.spec_from_file_location("collect_fe13_remaining_residual_evidence", path)
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


class Stage59Tests(unittest.TestCase):
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

    def test_each_remaining_shape_and_pair_are_audited(self) -> None:
        source, target, shapes = self.fixture()
        event, combinations, selected, tests = TOOL.evaluate_remaining_combinations(
            BR,
            source,
            target,
            primary_shape_id=shapes[0],
            remaining_shape_ids=shapes[1:],
            expected_primary_sha256="",
        )
        self.assertEqual(event["tested_combination_rows"], 3)
        self.assertEqual(event["promotable_combination_rows"], 3)
        self.assertEqual(len(combinations), 3)
        self.assertEqual(len(selected), 4)
        self.assertTrue(all(row["passes_structural_gates"] for row in combinations))
        self.assertTrue(all(row["strict_improvement"] for row in combinations))
        pair = next(row for row in combinations if row["selected_shape_count"] == 2)
        self.assertEqual(pair["candidate_distance_to_original"], 0)
        self.assertGreater(pair["distance_improvement_over_stage51"], 0)
        structural_failures = [
            row
            for row in tests
            if row["validation"] != "strict_improvement_over_stage51" and not row["passed"]
        ]
        self.assertEqual(structural_failures, [])


    def test_canonical_core_summary_without_optional_rejection_counter_is_accepted(self) -> None:
        summary = {
            "type": "br_quartet_restoration_core_profile_manifest_evidence_summary",
            "tool_version": "0.0.62",
            "status": "all_current_local_profiles_registered_runtime_unvalidated",
            "profile_rows": 14,
            "pack11_profile_rows": 12,
            "pack10_01_profile_rows": 2,
            "runtime_validated_profile_rows": 0,
        }
        TOOL.validate_core_summary(summary)

    def test_present_nonzero_rejection_counter_is_rejected(self) -> None:
        summary = {
            "type": "br_quartet_restoration_core_profile_manifest_evidence_summary",
            "tool_version": "0.0.62",
            "profile_rows": 14,
            "pack11_profile_rows": 12,
            "pack10_01_profile_rows": 2,
            "runtime_validated_profile_rows": 0,
            "rejected_manifests": 1,
        }
        with self.assertRaises(TOOL.Fe13RemainingResidualError):
            TOOL.validate_core_summary(summary)

    def test_primary_candidate_hash_is_fail_closed(self) -> None:
        source, target, shapes = self.fixture()
        with self.assertRaises(TOOL.Fe13RemainingResidualError):
            TOOL.evaluate_remaining_combinations(
                BR,
                source,
                target,
                primary_shape_id=shapes[0],
                remaining_shape_ids=shapes[1:],
                expected_primary_sha256="0" * 64,
            )


if __name__ == "__main__":
    unittest.main()
