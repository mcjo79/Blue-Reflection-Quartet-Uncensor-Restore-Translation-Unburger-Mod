#!/usr/bin/env python3
from __future__ import annotations

import csv
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "workstreams/quartet_restoration/collect_reflector_slot_light_identical_layout_value_transition_evidence.py"
SPEC = importlib.util.spec_from_file_location("stage110", SCRIPT)
assert SPEC and SPEC.loader
S = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(S)


def write_tsv(path: Path, fields: list[str], rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def section(path: str, key: str, side: str, endpoint: int, layout_hash: str, offsets: str, values: str) -> dict[str, object]:
    count = len(offsets.split(";"))
    return {
        "normalized_path": path,
        "member_key": key,
        "member_name": key.split("#", 1)[0],
        "side": side,
        "technical_member_role": "ringlight",
        "character_slot": "PC02",
        "normalized_endpoint": endpoint,
        "section_mode_or_flag_word": 0,
        "section_mode_or_flag_hex": "0x00000000",
        "section_count": count,
        "section_declared_span": 4096,
        "section_table_boundary_1": 56,
        "section_table_boundary_2": 60,
        "section_table_boundary_3": 64,
        "template_occurrences_in_section": count,
        "template_coverage_of_section_count": "full",
        "template_relative_offsets": offsets,
        "template_values_in_order": values,
        "first_template_relative_offset": offsets.split(";")[0],
        "last_template_end_relative_offset": int(offsets.split(";")[-1]) + 44,
        "declared_tail_after_last_template": 4096 - (int(offsets.split(";")[-1]) + 44),
        "exact_section_anchored_layout_sha256": layout_hash,
        "classification": "full_template_coverage_section",
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
        "previous_template_gap_bytes": "" if ordinal == 0 else 44,
        "next_template_gap_bytes": "" if ordinal + 1 == int(section_row["template_occurrences_in_section"]) else 44,
        "record_inside_declared_span": True,
        "classification": "additional_exact_format_valid_sibling_template_occurrence",
    }


def make_fixture(root: Path, *, corrupt_value_vector: bool = False) -> Path:
    reports = root / "reports"
    stage109 = reports / S.STAGE109_DIR
    stage109.mkdir(parents=True)
    path = "data/x64/effect/1002_pc02.elixir.gz"
    key = "test.g1e#0"
    shared_source = section(path, key, "source", 100, "a" * 64, "60;104", "1;2")
    shared_target = section(path, key, "target", 200, "a" * 64, "60;104", "1;3")
    source_only = section(path, key, "source", 300, "b" * 64, "60", "5")
    target_only = section(path, key, "target", 400, "c" * 64, "60", "7")
    sections = [shared_source, shared_target, source_only, target_only]
    occurrences = [
        occurrence(shared_source, 0, "1"), occurrence(shared_source, 1, "2"),
        occurrence(shared_target, 0, "1"), occurrence(shared_target, 1, "3"),
        occurrence(source_only, 0, "5"), occurrence(target_only, 0, "7"),
    ]
    if corrupt_value_vector:
        shared_source["template_values_in_order"] = "1;999"
    write_tsv(stage109 / "SLOT_LIGHT_SIBLING_SECTION_ANCHORED_LAYOUTS.tsv", list(sections[0]), sections)
    write_tsv(stage109 / "SLOT_LIGHT_SIBLING_SECTION_LAYOUT_OCCURRENCES.tsv", list(occurrences[0]), occurrences)
    (stage109 / "SUMMARY.json").write_text(json.dumps({
        "type": "br_quartet_restoration_reflector_slot_light_sibling_section_layout_evidence_summary",
        "tool_version": "0.1.23",
        "sibling_G1E_G1EM_pair_rows": 1,
        "revalidated_occurrence_rows": 6,
        "section_anchored_layout_rows": 4,
        "skipped_rows": 0,
        "technical_leaf_domain_semantics_resolved": False,
        "prototype_candidate_rows": 0,
        "policy": {
            "official_nonunderscore_archives_are_canonical": True,
            "underscore_archives_required": False,
        },
    }), encoding="utf-8")
    return reports


class Stage110Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.expected = (S.EXPECTED_OCCURRENCES, S.EXPECTED_SECTIONS, S.EXPECTED_PAIRS)
        S.EXPECTED_OCCURRENCES = 6
        S.EXPECTED_SECTIONS = 4
        S.EXPECTED_PAIRS = 1

    def tearDown(self) -> None:
        S.EXPECTED_OCCURRENCES, S.EXPECTED_SECTIONS, S.EXPECTED_PAIRS = self.expected

    def test_compares_values_only_inside_unique_identical_layout_classes(self) -> None:
        with tempfile.TemporaryDirectory(prefix="stage110-test-") as name:
            reports = make_fixture(Path(name))
            output, archive, summary = S.build_report(ROOT, create_archive=False, report_root=reports)
            self.assertIsNone(archive)
            self.assertEqual(summary["layout_class_rows"], 3)
            self.assertEqual(summary["shared_unique_identical_layout_class_rows"], 1)
            self.assertEqual(summary["source_only_layout_class_rows"], 1)
            self.assertEqual(summary["target_only_layout_class_rows"], 1)
            self.assertEqual(summary["matched_occurrence_transition_rows"], 2)
            self.assertEqual(summary["stable_value_transition_rows"], 1)
            self.assertEqual(summary["changed_value_transition_rows"], 1)
            self.assertFalse(summary["technical_leaf_domain_semantics_resolved"])
            self.assertTrue((output / "SLOT_LIGHT_IDENTICAL_LAYOUT_VALUE_TRANSITIONS.tsv").is_file())

    def test_fails_if_stage109_value_vector_does_not_match_occurrences(self) -> None:
        with tempfile.TemporaryDirectory(prefix="stage110-negative-") as name:
            reports = make_fixture(Path(name), corrupt_value_vector=True)
            with self.assertRaises(S.Stage110Error):
                S.build_report(ROOT, create_archive=False, report_root=reports)


if __name__ == "__main__":
    unittest.main()
