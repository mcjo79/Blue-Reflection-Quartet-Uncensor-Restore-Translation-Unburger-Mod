from __future__ import annotations

import csv
import hashlib
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

WORKSTREAM = Path(__file__).resolve().parents[1]
TOOL_PATH = WORKSTREAM / "build_bathroom_river_member_prototype.py"
SPEC = importlib.util.spec_from_file_location("stage69_tool", TOOL_PATH)
assert SPEC and SPEC.loader
TOOL = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = TOOL
SPEC.loader.exec_module(TOOL)


def write_tsv(path: Path, fields: list[str], rows: list[dict[str, object]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def river_fixture() -> tuple[bytes, bytes]:
    source = bytearray((index * 17 + 3) & 0xFF for index in range(252))
    target = bytearray(source)
    repeated_source = bytes.fromhex("00008842")
    repeated_target = bytes.fromhex("9f579442")
    for offset in (64, 128, 240):
        source[offset:offset + 4] = repeated_source
        target[offset:offset + 4] = repeated_target
    unique = [
        (80, b"\x01\x02\x03\x04", b"\x05\x06\x07\x08"),
        (96, b"\x11\x12\x13\x14", b"\x15\x16\x17\x18"),
        (144, b"\x21\x22\x23\x24", b"\x25\x26\x27\x28"),
        (176, b"\x31\x32\x33\x34", b"\x35\x36\x37\x38"),
    ]
    for offset, left, right in unique:
        source[offset:offset + 4] = left
        target[offset:offset + 4] = right
    return bytes(source), bytes(target)


class Stage69Tests(unittest.TestCase):
    def test_reconstructs_exact_original_and_reverse_roundtrip(self) -> None:
        source, target = river_fixture()
        old = (
            TOOL.EXPECTED_CANDIDATE_SHA256,
            TOOL.EXPECTED_CANDIDATE_SIZE,
            TOOL.EXPECTED_TARGET_DISTANCE,
        )
        try:
            TOOL.EXPECTED_CANDIDATE_SHA256 = hashlib.sha256(source).hexdigest()
            TOOL.EXPECTED_CANDIDATE_SIZE = len(source)
            TOOL.EXPECTED_TARGET_DISTANCE = TOOL.STAGE66.hamming_distance(source, target)
            candidate, cells, checks = TOOL.reconstruct_river_candidate(source, target)
        finally:
            (
                TOOL.EXPECTED_CANDIDATE_SHA256,
                TOOL.EXPECTED_CANDIDATE_SIZE,
                TOOL.EXPECTED_TARGET_DISTANCE,
            ) = old
        self.assertEqual(candidate, source)
        self.assertEqual(len(cells), 7)
        self.assertTrue(all(checks.values()))

    def test_rejects_tail_transition_without_two_normal_supports(self) -> None:
        source, target = river_fixture()
        altered = bytearray(target)
        altered[128:132] = bytes.fromhex("aaaaaaaa")
        old = (
            TOOL.EXPECTED_CANDIDATE_SHA256,
            TOOL.EXPECTED_CANDIDATE_SIZE,
            TOOL.EXPECTED_TARGET_DISTANCE,
        )
        try:
            TOOL.EXPECTED_CANDIDATE_SHA256 = hashlib.sha256(source).hexdigest()
            TOOL.EXPECTED_CANDIDATE_SIZE = len(source)
            TOOL.EXPECTED_TARGET_DISTANCE = TOOL.STAGE66.hamming_distance(source, bytes(altered))
            _candidate, _cells, checks = TOOL.reconstruct_river_candidate(source, bytes(altered))
            self.assertFalse(checks["tail_transition_occurs_three_times"])
            self.assertFalse(checks["tail_transition_has_two_normal_supports"])
        finally:
            (
                TOOL.EXPECTED_CANDIDATE_SHA256,
                TOOL.EXPECTED_CANDIDATE_SIZE,
                TOOL.EXPECTED_TARGET_DISTANCE,
            ) = old

    def write_stage68(self, root: Path, *, authorized: bool = True) -> None:
        summary = {
            "type": "br_quartet_restoration_bathroom_ordinary_field_control_evidence_summary",
            "tool_version": "0.0.78",
            "status": "bathroom_ordinary_field_control_and_river_static_promotion_audit_complete_no_payload_written",
            "ordinary_control_member_rows": 3,
            "ordinary_control_scope_sufficient": True,
            "target_opl2_cell_rows": 61,
            "opl2_safe_local_prototype_rows": 0,
            "river_static_promotion_review_rows": 1,
            "river_static_local_prototype_authorized_rows": 1 if authorized else 0,
            "safe_local_prototype_rows": 1 if authorized else 0,
            "policy": {
                "installed_games_modified": False,
                "candidate_member_payloads_written": False,
                "parent_archive_repack_performed": False,
                "pak_repack_performed": False,
                "core_registry_modified": False,
                "activation_or_rollback_invoked": False,
                "runtime_validation_inferred": False,
                "censorship_classification_inferred": False,
                "opaque_binary_field_semantics_inferred": False,
                "translation_or_dlc_workstreams_modified": False,
                "river_authorization_is_limited_to_a_local_member_prototype": True,
            },
        }
        (root / "SUMMARY.json").write_text(json.dumps(summary), encoding="utf-8")
        row = {
            "member_key": TOOL.MEMBER_KEY,
            "candidate_kind": "complete_word_set_with_repeated_tail_guard_exception",
            "selected_cell_indices": "0;1;2;3;4;5;6",
            "selected_cell_count": 7,
            "candidate_sha256": TOOL.EXPECTED_CANDIDATE_SHA256,
            "candidate_size": TOOL.EXPECTED_CANDIDATE_SIZE,
            "target_distance_to_source": TOOL.EXPECTED_TARGET_DISTANCE,
            "candidate_distance_to_source": 0,
            "distance_improvement": TOOL.EXPECTED_TARGET_DISTANCE,
            "exact_original": True,
            "exact_target_reverse_roundtrip": True,
            "repeated_tail_guard_exception_rows": 1,
            "tail_transition_occurrence_count": 3,
            "tail_eligible_support_occurrence_count": 2,
            "bytes_after_tail_word_identical": True,
            "static_local_prototype_authorized": authorized,
            "semantics_assigned": False,
            "classification": "exact_original_small_river_descriptor_supported_by_repeated_tail_transition",
        }
        write_tsv(root / "BATHROOM_RIVER_STATIC_PROMOTION_REVIEW.tsv", list(row), [row])

    def test_validate_stage68_accepts_authorized_row(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            self.write_stage68(root)
            summary, row = TOOL.validate_stage68(root)
            self.assertEqual(summary["tool_version"], "0.0.78")
            self.assertTrue(TOOL.parse_bool(row["static_local_prototype_authorized"]))

    def test_validate_stage68_rejects_unauthorized_row(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            self.write_stage68(root, authorized=False)
            with self.assertRaises(TOOL.BathroomRiverPrototypeError):
                TOOL.validate_stage68(root)


if __name__ == "__main__":
    unittest.main()
