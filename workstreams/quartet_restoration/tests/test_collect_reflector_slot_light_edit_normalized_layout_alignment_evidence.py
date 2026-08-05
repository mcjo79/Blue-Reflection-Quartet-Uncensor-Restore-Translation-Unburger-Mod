#!/usr/bin/env python3
from __future__ import annotations

import csv
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "workstreams/quartet_restoration/collect_reflector_slot_light_edit_normalized_layout_alignment_evidence.py"
SPEC = importlib.util.spec_from_file_location("stage111", SCRIPT)
assert SPEC and SPEC.loader
S = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(S)


def write_tsv(path: Path, fields: list[str], rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def section(path: str, key: str, side: str, endpoint: int, layout_hash: str, offsets: str, values: str, count: int | None = None) -> dict[str, object]:
    occurrence_count = len(offsets.split(";"))
    section_count = occurrence_count if count is None else count
    span = 4096 + occurrence_count * 16
    return {
        "normalized_path": path,
        "member_key": key,
        "member_name": key.split("#", 1)[0],
        "side": side,
        "technical_member_role": "ringlight",
        "character_slot": "PC02",
        "normalized_endpoint": endpoint,
        "section_mode_or_flag_word": 2,
        "section_mode_or_flag_hex": "0x00000002",
        "section_count": section_count,
        "section_declared_span": span,
        "section_table_boundary_1": 56 + 4 * (section_count - 1),
        "section_table_boundary_2": 56 + 8 * (section_count - 1),
        "section_table_boundary_3": 56 + 12 * (section_count - 1),
        "template_occurrences_in_section": occurrence_count,
        "template_coverage_of_section_count": "full" if occurrence_count == section_count else "partial",
        "template_relative_offsets": offsets,
        "template_values_in_order": values,
        "first_template_relative_offset": offsets.split(";")[0],
        "last_template_end_relative_offset": int(offsets.split(";")[-1]) + 44,
        "declared_tail_after_last_template": span - (int(offsets.split(";")[-1]) + 44),
        "exact_section_anchored_layout_sha256": layout_hash,
        "classification": "full_template_coverage_section" if occurrence_count == section_count else "partial_template_coverage_section",
    }


def occurrence(section_row: dict[str, object], ordinal: int, value: str) -> dict[str, object]:
    offset = int(str(section_row["template_relative_offsets"]).split(";")[ordinal])
    endpoint = int(section_row["normalized_endpoint"])
    return {
        "normalized_path": section_row["normalized_path"],
        "member_key": section_row["member_key"],
        "member_name": section_row["member_name"],
        "side": section_row["side"],
        "technical_member_role": section_row["technical_member_role"],
        "bounded_name_scope": "ringlight",
        "character_slot": section_row["character_slot"],
        "record_start": endpoint + offset,
        "normalized_endpoint": endpoint,
        "paired_float_value": value,
        "known_stage101_occurrence": False,
        "additional_sibling_occurrence": True,
        "section_mode_or_flag_word": section_row["section_mode_or_flag_word"],
        "section_mode_or_flag_hex": section_row["section_mode_or_flag_hex"],
        "section_count": section_row["section_count"],
        "section_declared_span": section_row["section_declared_span"],
        "section_declared_end": endpoint + int(section_row["section_declared_span"]),
        "section_table_boundary_1": section_row["section_table_boundary_1"],
        "section_table_boundary_2": section_row["section_table_boundary_2"],
        "section_table_boundary_3": section_row["section_table_boundary_3"],
        "record_relative_offset": offset,
        "record_end_relative_offset": offset + 44,
        "distance_after_table_boundary_3": offset - int(section_row["section_table_boundary_3"]),
        "declared_tail_bytes_after_record": int(section_row["section_declared_span"]) - (offset + 44),
        "template_ordinal_within_section": ordinal,
        "template_occurrences_in_section": section_row["template_occurrences_in_section"],
        "template_coverage_of_section_count": section_row["template_coverage_of_section_count"],
        "previous_template_gap_bytes": "",
        "next_template_gap_bytes": "",
        "record_inside_declared_span": True,
        "classification": "additional_exact_format_valid_sibling_template_occurrence",
    }


def make_fixture(root: Path, *, corrupt_stage99: bool = False) -> Path:
    reports = root / "reports"
    stage109 = reports / S.STAGE109_DIR
    stage110 = reports / S.STAGE110_DIR
    stage99 = reports / S.STAGE99_DIR
    stage109.mkdir(parents=True)
    stage110.mkdir(parents=True)
    stage99.mkdir(parents=True)

    zero_source = section("data/x64/effect/1000_pc00.elixir.gz", "zero.g1e#0", "source", 192, "a" * 64, "204;812", "1;2")
    zero_target = section("data/x64/effect/1000_pc00.elixir.gz", "zero.g1e#0", "target", 192, "b" * 64, "204;812", "1;3")
    canary_source = section(S.CANARY_PATH, S.CANARY_MEMBER_KEY, "source", S.CANARY_ENDPOINT, "c" * 64, "236;844;1452", "30;150;2")
    canary_target = section(S.CANARY_PATH, S.CANARY_MEMBER_KEY, "target", S.CANARY_ENDPOINT, "d" * 64, "252;860;1468;2076", "30;75;75;2")
    ambiguous_source = section("data/x64/effect/1002_pc02.elixir.gz", "ambiguous.g1e#0", "source", 192, "e" * 64, "236;844;1452", "1;2;3")
    ambiguous_target = section("data/x64/effect/1002_pc02.elixir.gz", "ambiguous.g1e#0", "target", 192, "f" * 64, "252;860;1468;2076", "1;2;3;4")
    sections = [zero_source, zero_target, canary_source, canary_target, ambiguous_source, ambiguous_target]
    occurrences: list[dict[str, object]] = []
    for row in sections:
        for ordinal, value in enumerate(str(row["template_values_in_order"]).split(";")):
            occurrences.append(occurrence(row, ordinal, value))

    write_tsv(stage109 / "SLOT_LIGHT_SIBLING_SECTION_ANCHORED_LAYOUTS.tsv", list(sections[0]), sections)
    write_tsv(stage109 / "SLOT_LIGHT_SIBLING_SECTION_LAYOUT_OCCURRENCES.tsv", list(occurrences[0]), occurrences)
    (stage109 / "SUMMARY.json").write_text(json.dumps({
        "type": "br_quartet_restoration_reflector_slot_light_sibling_section_layout_evidence_summary",
        "tool_version": "0.1.23",
        "section_anchored_layout_rows": len(sections),
        "revalidated_occurrence_rows": len(occurrences),
        "skipped_rows": 0,
        "technical_leaf_domain_semantics_resolved": False,
    }), encoding="utf-8")

    class_rows = []
    for row in sections:
        class_rows.append({
            "normalized_path": row["normalized_path"],
            "member_key": row["member_key"],
            "member_name": row["member_name"],
            "technical_member_role": row["technical_member_role"],
            "character_slot": row["character_slot"],
            "exact_section_anchored_layout_sha256": row["exact_section_anchored_layout_sha256"],
            "section_mode_or_flag_word": row["section_mode_or_flag_word"],
            "section_mode_or_flag_hex": row["section_mode_or_flag_hex"],
            "section_count": row["section_count"],
            "section_declared_span": row["section_declared_span"],
            "template_relative_offsets": row["template_relative_offsets"],
            "template_occurrences_in_section": row["template_occurrences_in_section"],
            "template_coverage_of_section_count": row["template_coverage_of_section_count"],
            "source_section_rows": 1 if row["side"] == "source" else 0,
            "target_section_rows": 1 if row["side"] == "target" else 0,
            "classification": "source_only_layout_class" if row["side"] == "source" else "target_only_layout_class",
        })
    write_tsv(stage110 / "SLOT_LIGHT_IDENTICAL_LAYOUT_CLASSES.tsv", list(class_rows[0]), class_rows)
    (stage110 / "SUMMARY.json").write_text(json.dumps({
        "type": "br_quartet_restoration_reflector_slot_light_identical_layout_value_transition_evidence_summary",
        "tool_version": "0.1.24",
        "layout_class_rows": len(class_rows),
        "source_only_layout_class_rows": 3,
        "target_only_layout_class_rows": 3,
        "changed_value_transition_rows": 0,
        "skipped_rows": 0,
    }), encoding="utf-8")

    (stage99 / "SUMMARY.json").write_text(json.dumps({
        "type": "br_quartet_restoration_reflector_slot_light_insertion_shift_continuity_evidence_summary",
        "tool_version": "0.1.13",
        "candidate_target_occurrence_identity_resolved": True,
        "winning_model_id": "wrong" if corrupt_stage99 else "insert_first_substitute_to_second",
        "inserted_target_occurrence": "first_target_75",
        "candidate_target_occurrence_identity": "second_target_75",
        "parameters": {
            "candidate_source_sequence": ["30", "150", "2"],
            "candidate_target_sequence": ["30", "75", "75", "2"],
        },
        "skipped_rows": 0,
    }), encoding="utf-8")
    return reports


class Stage111Tests(unittest.TestCase):
    def setUp(self) -> None:
        names = [name for name in vars(S) if name.startswith("EXPECTED_")]
        self.originals = {name: getattr(S, name) for name in names}
        S.EXPECTED_STAGE109_SECTIONS = 6
        S.EXPECTED_STAGE109_OCCURRENCES = 18
        S.EXPECTED_STAGE110_CLASSES = 6
        S.EXPECTED_SOURCE_ONLY_CLASSES = 3
        S.EXPECTED_TARGET_ONLY_CLASSES = 3
        S.EXPECTED_CANDIDATE_SECTION_PAIRS = 3
        S.EXPECTED_ALIGNMENT_MODELS = 9
        S.EXPECTED_MUTUAL_UNIQUE_PAIRS = 3
        S.EXPECTED_ZERO_EDIT_PAIRS = 1
        S.EXPECTED_ONE_EDIT_PAIRS = 2
        S.EXPECTED_ONE_EDIT_MODELS = 8
        S.EXPECTED_RESOLVED_PAIRS = 2
        S.EXPECTED_UNRESOLVED_ONE_EDIT_PAIRS = 1
        S.EXPECTED_RESOLVED_TRANSITIONS = 5
        S.EXPECTED_STABLE_TRANSITIONS = 3
        S.EXPECTED_CHANGED_TRANSITIONS = 2
        S.EXPECTED_INSERTED_OCCURRENCES = 1
        S.EXPECTED_DELETED_OCCURRENCES = 0

    def tearDown(self) -> None:
        for name, value in self.originals.items():
            setattr(S, name, value)

    def test_resolves_zero_edit_and_stage99_canary_but_excludes_ambiguous_edit_pair(self) -> None:
        with tempfile.TemporaryDirectory(prefix="stage111-test-") as name:
            reports = make_fixture(Path(name))
            output, archive, summary = S.build_report(ROOT, create_archive=False, report_root=reports)
            self.assertIsNone(archive)
            self.assertEqual(summary["mutual_unique_section_pair_rows"], 3)
            self.assertEqual(summary["resolved_section_pair_rows"], 2)
            self.assertEqual(summary["unresolved_one_edit_pair_rows"], 1)
            self.assertEqual(summary["resolved_occurrence_transition_rows"], 5)
            self.assertEqual(summary["changed_value_transition_rows"], 2)
            self.assertEqual(summary["inserted_occurrence_rows"], 1)
            self.assertFalse(summary["technical_leaf_domain_semantics_resolved"])
            self.assertTrue((output / "SLOT_LIGHT_EDIT_NORMALIZED_ALIGNMENT_MODELS.tsv").is_file())

    def test_fails_closed_if_stage99_canary_decision_drifts(self) -> None:
        with tempfile.TemporaryDirectory(prefix="stage111-negative-") as name:
            reports = make_fixture(Path(name), corrupt_stage99=True)
            with self.assertRaises(S.Stage111Error):
                S.build_report(ROOT, create_archive=False, report_root=reports)


if __name__ == "__main__":
    unittest.main()
