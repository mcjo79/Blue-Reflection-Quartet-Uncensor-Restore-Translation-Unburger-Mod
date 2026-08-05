#!/usr/bin/env python3
from __future__ import annotations

import csv
import importlib.util
import json
import struct
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "workstreams/quartet_restoration/collect_reflector_slot_light_unresolved_edit_block_continuity_evidence.py"
SPEC = importlib.util.spec_from_file_location("stage112", SCRIPT)
assert SPEC and SPEC.loader
S = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(S)

PATH = "data/x64/effect/1002_pc02.elixir.gz"
UNRESOLVED_KEY = "ambiguous.g1e#0"
CANARY_KEY = S.CANARY_MEMBER_KEY
ENDPOINT = 192
SPAN = 608


def write_tsv(path: Path, fields: list[str], rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def model(pair_id: str, ordinal: int, source_count: int, *, selected: bool = False) -> dict[str, object]:
    pairs = [(index, index if index < ordinal else index + 1) for index in range(source_count)]
    return {
        "pair_id": pair_id,
        "model_id": f"{pair_id}|target_insertion_piecewise_offset_shift|{ordinal}",
        "normalized_path": PATH,
        "member_key": CANARY_KEY if "ringlight" in pair_id else UNRESOLVED_KEY,
        "member_name": "member.g1e",
        "source_endpoint": ENDPOINT,
        "target_endpoint": ENDPOINT,
        "edit_kind": "target_insertion_piecewise_offset_shift",
        "edit_ordinal": ordinal,
        "matched_ordinal_pairs": ";".join(f"{left}->{right}" for left, right in pairs),
        "offset_delta_vector": ";".join("16" if right == left else "624" for left, right in pairs),
        "pre_edit_offset_shift": 16,
        "post_edit_offset_shift": 624,
        "matched_occurrence_rows": len(pairs),
        "stable_value_rows_diagnostic": 0,
        "changed_value_rows_diagnostic": len(pairs),
        "mutual_unique_section_pair": True,
        "selected_for_resolved_transitions": selected,
        "selection_basis": "stage99_independent_insertion_shift_continuity_canary" if selected else "",
        "classification": "one_edit_alignment_model",
    }


def occurrence(key: str, side: str, endpoint: int, ordinal: int, anchor: int, value: float, count: int) -> dict[str, object]:
    return {
        "normalized_path": PATH,
        "member_key": key,
        "member_name": key.split("#", 1)[0],
        "side": side,
        "technical_member_role": "character_effect_container",
        "bounded_name_scope": "ringlight",
        "character_slot": "PC02",
        "record_start": anchor + S.PRE_RECORD_BYTES,
        "normalized_endpoint": endpoint,
        "paired_float_value": f"{value:.9g}",
        "known_stage101_occurrence": False,
        "additional_sibling_occurrence": True,
        "section_mode_or_flag_word": 2,
        "section_mode_or_flag_hex": "0x00000002",
        "section_count": count,
        "section_declared_span": anchor + SPAN - endpoint,
        "section_declared_end": anchor + SPAN,
        "section_table_boundary_1": 56 + 4 * (count - 1),
        "section_table_boundary_2": 56 + 8 * (count - 1),
        "section_table_boundary_3": 56 + 12 * (count - 1),
        "record_relative_offset": anchor + S.PRE_RECORD_BYTES - endpoint,
        "record_end_relative_offset": anchor + S.PRE_RECORD_BYTES + S.RECORD_BYTES - endpoint,
        "distance_after_table_boundary_3": 0,
        "declared_tail_bytes_after_record": SPAN - S.PRE_RECORD_BYTES - S.RECORD_BYTES,
        "template_ordinal_within_section": ordinal,
        "template_occurrences_in_section": count,
        "template_coverage_of_section_count": "full",
        "previous_template_gap_bytes": "",
        "next_template_gap_bytes": "",
        "record_inside_declared_span": True,
        "classification": "additional_exact_format_valid_sibling_template_occurrence",
    }


def block_bytes(value: float, marker: int, anchor: int, endpoint: int) -> bytes:
    block = bytearray(SPAN)
    block[0:4] = SPAN.to_bytes(4, "little")
    for offset in range(4, S.PRE_RECORD_BYTES, 4):
        block[offset:offset + 4] = ((offset // 4) + 100).to_bytes(4, "little")
    record = S.PRE_RECORD_BYTES
    packed = struct.pack("<f", value)
    block[record:record + 4] = packed
    block[record + 4:record + 8] = packed
    for dword in range(2, 10):
        block[record + dword * 4:record + dword * 4 + 4] = (0x1000 + dword).to_bytes(4, "little")
    reference_offset = anchor + record + S.REFERENCE_DWORD * 4
    displacement = endpoint - reference_offset
    block[record + S.REFERENCE_DWORD * 4:record + S.REFERENCE_DWORD * 4 + 4] = (displacement & 0xFFFFFFFF).to_bytes(4, "little")
    block[record + S.RECORD_BYTES + 8:record + S.RECORD_BYTES + 12] = marker.to_bytes(4, "little")
    return bytes(block)


def payload(values: list[float], markers: list[int], anchors: list[int], endpoint: int = ENDPOINT) -> bytes:
    size = max(anchor + SPAN for anchor in anchors) + 64
    result = bytearray(size)
    for value, marker, anchor in zip(values, markers, anchors):
        result[anchor:anchor + SPAN] = block_bytes(value, marker, anchor, endpoint)
    return bytes(result)


def make_fixture(root: Path, *, ambiguous_duplicate: bool = False, contradict_canary: bool = False) -> tuple[Path, object]:
    reports = root / "reports"
    for directory in (S.STAGE108_DIR, S.STAGE109_DIR, S.STAGE111_DIR, S.STAGE99_DIR):
        (reports / directory).mkdir(parents=True, exist_ok=True)

    (reports / S.STAGE108_DIR / "SUMMARY.json").write_text(json.dumps({
        "type": "br_quartet_restoration_br1_official_source_retirement_closure_evidence_summary",
        "tool_version": "0.1.22",
        "status": "underscore_archive_retirement_closed",
        "retirement_complete": True,
        "official_archives_verified": 4,
        "underscore_archives_absent": 4,
        "underscore_archives_required_for_normal_workflow": False,
    }), encoding="utf-8")

    source_anchors = [400, 1008]
    target_anchors = [416, 1024, 1632]
    canary_source_anchors = [3000, 3608, 4216]
    canary_target_anchors = [3016, 3624, 4232, 4840]
    unresolved_target_markers = [10, 20, 20 if ambiguous_duplicate else 30]
    canary_target_markers = [100, 200, 300, 400]
    if contradict_canary:
        canary_target_markers = [100, 300, 200, 400]

    occurrence_rows: list[dict[str, object]] = []
    for side, anchors, values, key in (
        ("source", source_anchors, [1.0, 10.0], UNRESOLVED_KEY),
        ("target", target_anchors, [1.0, 5.0, 10.0], UNRESOLVED_KEY),
        ("source", canary_source_anchors, [30.0, 150.0, 2.0], CANARY_KEY),
        ("target", canary_target_anchors, [30.0, 75.0, 75.0, 2.0], CANARY_KEY),
    ):
        for ordinal, (anchor, value) in enumerate(zip(anchors, values)):
            occurrence_rows.append(occurrence(key, side, ENDPOINT, ordinal, anchor, value, len(values)))
    write_tsv(reports / S.STAGE109_DIR / "SLOT_LIGHT_SIBLING_SECTION_LAYOUT_OCCURRENCES.tsv", list(occurrence_rows[0]), occurrence_rows)
    (reports / S.STAGE109_DIR / "SUMMARY.json").write_text(json.dumps({
        "type": "br_quartet_restoration_reflector_slot_light_sibling_section_layout_evidence_summary",
        "tool_version": "0.1.23",
        "revalidated_occurrence_rows": len(occurrence_rows),
        "skipped_rows": 0,
        "technical_leaf_domain_semantics_resolved": False,
    }), encoding="utf-8")

    unresolved_pair = f"{PATH}|{UNRESOLVED_KEY}|{ENDPOINT}|{ENDPOINT}"
    canary_pair = f"{PATH}|{CANARY_KEY}|{ENDPOINT}|{ENDPOINT}"
    decisions = [
        {
            "pair_id": unresolved_pair, "normalized_path": PATH, "member_key": UNRESOLVED_KEY, "member_name": "ambiguous.g1e",
            "technical_member_role": "character_effect_container", "source_endpoint": ENDPOINT, "target_endpoint": ENDPOINT,
            "source_values": "1;10", "target_values": "1;5;10", "alignment_model_rows": 3,
            "selected_model_id": "", "selection_basis": "", "classification": "unresolved_multiple_one_edit_models",
        },
        {
            "pair_id": canary_pair, "normalized_path": PATH, "member_key": CANARY_KEY, "member_name": "e_PC02_w5_ringlight_01.g1e",
            "technical_member_role": "ringlight", "source_endpoint": ENDPOINT, "target_endpoint": ENDPOINT,
            "source_values": "30;150;2", "target_values": "30;75;75;2", "alignment_model_rows": 4,
            "selected_model_id": f"{canary_pair}|target_insertion_piecewise_offset_shift|1",
            "selection_basis": "stage99_independent_insertion_shift_continuity_canary", "classification": "resolved_stage99_canary",
        },
    ]
    write_tsv(reports / S.STAGE111_DIR / "SLOT_LIGHT_EDIT_NORMALIZED_SECTION_PAIR_DECISIONS.tsv", list(decisions[0]), decisions)
    models = [model(unresolved_pair, ordinal, 2) for ordinal in range(3)]
    models.extend(model(canary_pair, ordinal, 3, selected=ordinal == 1) for ordinal in range(4))
    write_tsv(reports / S.STAGE111_DIR / "SLOT_LIGHT_EDIT_NORMALIZED_ALIGNMENT_MODELS.tsv", list(models[0]), models)
    (reports / S.STAGE111_DIR / "SUMMARY.json").write_text(json.dumps({
        "type": "br_quartet_restoration_reflector_slot_light_edit_normalized_layout_alignment_evidence_summary",
        "tool_version": "0.1.25",
        "unresolved_one_edit_pair_rows": 1,
        "one_edit_alignment_model_rows": 7,
        "independently_resolved_canary_pair_rows": 1,
        "prototype_candidate_rows": 0,
        "technical_leaf_domain_semantics_resolved": False,
    }), encoding="utf-8")
    (reports / S.STAGE99_DIR / "SUMMARY.json").write_text(json.dumps({
        "type": "br_quartet_restoration_reflector_slot_light_insertion_shift_continuity_evidence_summary",
        "tool_version": "0.1.13",
        "candidate_target_occurrence_identity_resolved": True,
        "winning_model_id": "insert_first_substitute_to_second",
        "inserted_target_occurrence": "first_target_75",
        "candidate_target_occurrence_identity": "second_target_75",
        "skipped_rows": 0,
    }), encoding="utf-8")

    source_members = [
        {"comparison_key": UNRESOLVED_KEY, "name": "ambiguous.g1e", "payload": payload([1.0, 10.0], [10, 30], source_anchors)},
        {"comparison_key": CANARY_KEY, "name": "e_PC02_w5_ringlight_01.g1e", "payload": payload([30.0, 150.0, 2.0], [100, 300, 400], canary_source_anchors)},
    ]
    target_members = [
        {"comparison_key": UNRESOLVED_KEY, "name": "ambiguous.g1e", "payload": payload([1.0, 5.0, 10.0], unresolved_target_markers, target_anchors)},
        {"comparison_key": CANARY_KEY, "name": "e_PC02_w5_ringlight_01.g1e", "payload": payload([30.0, 75.0, 75.0, 2.0], canary_target_markers, canary_target_anchors)},
    ]

    def loader(**_kwargs: object):
        return ([{"normalized_path": PATH, "source_members": source_members, "target_members": target_members}], [])

    return reports, loader


class Stage112Tests(unittest.TestCase):
    def setUp(self) -> None:
        names = [name for name in vars(S) if name.startswith("EXPECTED_")]
        self.originals = {name: getattr(S, name) for name in names}
        self.original_identities = S.EXPECTED_UNRESOLVED_IDENTITIES
        S.EXPECTED_STAGE109_OCCURRENCES = 12
        S.EXPECTED_STAGE111_UNRESOLVED_PAIRS = 1
        S.EXPECTED_STAGE111_TOTAL_ONE_EDIT_MODELS = 7
        S.EXPECTED_STAGE111_UNRESOLVED_MODELS = 3
        S.EXPECTED_STAGE111_CANARY_MODELS = 4
        S.EXPECTED_PARENT_CONTAINERS = 1
        S.EXPECTED_SCOPED_MEMBER_PAIRS = 2
        S.EXPECTED_BLOCK_ROWS = 12
        S.EXPECTED_MODEL_COMPARISON_ROWS = 18
        S.EXPECTED_UNRESOLVED_IDENTITIES = {(PATH, UNRESOLVED_KEY)}

    def tearDown(self) -> None:
        for name, value in self.originals.items():
            setattr(S, name, value)
        S.EXPECTED_UNRESOLVED_IDENTITIES = self.original_identities

    def test_resolves_only_unique_zero_residual_distinct_edit_model(self) -> None:
        with tempfile.TemporaryDirectory(prefix="stage112-test-") as name:
            reports, loader = make_fixture(Path(name))
            output, archive, summary = S.build_report(
                ROOT, create_archive=False, report_root=reports, container_loader=loader,
                scope_rows_override=[{"normalized_path": PATH}],
            )
            self.assertIsNone(archive)
            self.assertEqual(summary["newly_resolved_noncanary_pair_rows"], 1)
            self.assertEqual(summary["still_unresolved_noncanary_pair_rows"], 0)
            self.assertTrue(summary["canary_identity_preserved"])
            self.assertEqual(summary["input_unresolved_one_edit_model_rows"], 3)
            self.assertEqual(summary["canary_model_rows"], 4)
            self.assertEqual(summary["model_continuity_rows"], 7)
            self.assertTrue((output / "SLOT_LIGHT_UNRESOLVED_EDIT_MODEL_CONTINUITY.tsv").is_file())

    def test_keeps_duplicate_structural_edit_block_unresolved(self) -> None:
        with tempfile.TemporaryDirectory(prefix="stage112-ambiguous-") as name:
            reports, loader = make_fixture(Path(name), ambiguous_duplicate=True)
            _output, _archive, summary = S.build_report(
                ROOT, create_archive=False, report_root=reports, container_loader=loader,
                scope_rows_override=[{"normalized_path": PATH}],
            )
            self.assertEqual(summary["newly_resolved_noncanary_pair_rows"], 0)
            self.assertEqual(summary["still_unresolved_noncanary_pair_rows"], 1)

    def test_fails_closed_if_structural_gate_contradicts_stage99_canary(self) -> None:
        with tempfile.TemporaryDirectory(prefix="stage112-canary-negative-") as name:
            reports, loader = make_fixture(Path(name), contradict_canary=True)
            with self.assertRaises(S.Stage112Error):
                S.build_report(
                    ROOT, create_archive=False, report_root=reports, container_loader=loader,
                    scope_rows_override=[{"normalized_path": PATH}],
                )


if __name__ == "__main__":
    unittest.main()
