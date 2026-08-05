#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

MODULE_PATH = Path(__file__).resolve().parents[1] / "collect_reflector_slot_light_trailer_residual_recurrence_evidence.py"
spec = importlib.util.spec_from_file_location("stage113", MODULE_PATH)
assert spec and spec.loader
S = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = S
spec.loader.exec_module(S)


def residual(pair: str, member: str, *, source: str = "0x0000000a", target: str = "0x00000014", dword: int = 40, segment: str = "trailer") -> dict[str, object]:
    return {
        "pair_id": pair,
        "model_id": pair + "|model",
        "member_key": member,
        "source_ordinal": 0,
        "target_ordinal": 0,
        "source_block_span": 608,
        "target_block_span": 608,
        "relative_dword": dword,
        "segment": segment,
        "source_u32_hex": source,
        "target_u32_hex": target,
        "source_i32": int(source, 16),
        "target_i32": int(target, 16),
        "signed_delta": int(target, 16) - int(source, 16),
        "byte_differences": 1,
        "length_mismatch": False,
        "corpus_role": "resolved_zero_edit_reference",
    }


def model(model_id: str, pair_id: str = "ambiguous") -> dict[str, object]:
    return {
        "pair_id": pair_id,
        "model_id": model_id,
        "edit_kind": "target_insertion_piecewise_offset_shift",
        "edit_ordinal": 1,
        "matched_occurrence_rows": 2,
    }


class Stage113Tests(unittest.TestCase):
    def test_cross_member_exact_trailer_recurrence_can_uniquely_resolve(self) -> None:
        refs = [residual("ref-a", "member-a"), residual("ref-b", "member-b")]
        classes, lookup = S.build_recurrence_classes(refs)
        self.assertEqual(len(classes), 1)
        self.assertTrue(classes[0]["recurrence_mask_eligible"])

        supported = S.annotate_candidate_rows([residual("ambiguous", "ambiguous-member")], lookup)
        unsupported = S.annotate_candidate_rows([
            residual("ambiguous", "ambiguous-member", source="0x0000000a", target="0x0000001e")
        ], lookup)
        continuity = {
            "all_reference_deltas_compensate_anchor_shift": True,
            "edit_block_distinct_from_all_matched_blocks": True,
        }
        first = S.aggregate_model(model("m-supported"), supported, continuity)
        second = S.aggregate_model(model("m-unsupported"), unsupported, continuity)
        decision = S.decide_pair("ambiguous", "ambiguous-member", [first, second])
        self.assertEqual(decision["selected_model_id"], "m-supported")
        self.assertEqual(decision["classification"], "occurrence_identity_resolved_by_recurrent_trailer_transition_mask")

    def test_two_recurrence_normalized_models_remain_unresolved(self) -> None:
        refs = [residual("ref-a", "member-a"), residual("ref-b", "member-b")]
        _classes, lookup = S.build_recurrence_classes(refs)
        continuity = {
            "all_reference_deltas_compensate_anchor_shift": True,
            "edit_block_distinct_from_all_matched_blocks": True,
        }
        rows = S.annotate_candidate_rows([residual("ambiguous", "ambiguous-member")], lookup)
        first = S.aggregate_model(model("m1"), rows, continuity)
        second = S.aggregate_model(model("m2"), rows, continuity)
        decision = S.decide_pair("ambiguous", "ambiguous-member", [first, second])
        self.assertEqual(decision["identity_eligible_model_rows"], 2)
        self.assertEqual(decision["classification"], "occurrence_identity_unresolved_after_recurrence_mask")

    def test_prefix_and_single_member_recurrence_never_mask(self) -> None:
        prefix_refs = [
            residual("ref-a", "member-a", segment="prefix"),
            residual("ref-b", "member-b", segment="prefix"),
        ]
        classes, _lookup = S.build_recurrence_classes(prefix_refs)
        self.assertFalse(classes[0]["recurrence_mask_eligible"])

        one_member_refs = [residual("ref-a", "member-a"), residual("ref-b", "member-a")]
        classes, _lookup = S.build_recurrence_classes(one_member_refs)
        self.assertFalse(classes[0]["recurrence_mask_eligible"])

    def test_canary_contradiction_fails_closed(self) -> None:
        eligible_wrong = {
            "pair_id": "canary",
            "model_id": "wrong-model",
            "identity_eligible_after_recurrence_mask": True,
        }
        with self.assertRaises(S.Stage113Error):
            S.decide_pair("canary", S.CANARY_MEMBER_KEY, [eligible_wrong], "immutable-model")


if __name__ == "__main__":
    unittest.main()

# Full synthetic build-report regression.  This is intentionally defined after
# the focused unit tests so the small helpers above remain readable.
import csv
import json
import struct
import tempfile

ROOT = Path(__file__).resolve().parents[3]
SYN_PATH = "data/x64/effect/1002_pc02.elixir.gz"
SYN_ENDPOINT = 192
SYN_SPAN = 608
SYN_CANARY = "canary.g1e#0"


def _write_tsv(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    assert rows
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]), delimiter="\t", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def _block(value: float, marker: int, anchor: int) -> bytes:
    block = bytearray(SYN_SPAN)
    block[0:4] = SYN_SPAN.to_bytes(4, "little")
    for offset in range(4, 108, 4):
        block[offset:offset + 4] = ((offset // 4) + 100).to_bytes(4, "little")
    packed = struct.pack("<f", value)
    block[108:112] = packed
    block[112:116] = packed
    for dword in range(2, 10):
        block[108 + dword * 4:108 + dword * 4 + 4] = (0x1000 + dword).to_bytes(4, "little")
    ref_offset = anchor + 108 + 10 * 4
    displacement = SYN_ENDPOINT - ref_offset
    block[108 + 10 * 4:108 + 11 * 4] = (displacement & 0xFFFFFFFF).to_bytes(4, "little")
    block[108 + 44 + 8:108 + 44 + 12] = marker.to_bytes(4, "little")
    return bytes(block)


def _payload(values: list[float], markers: list[int], anchors: list[int]) -> bytes:
    out = bytearray(max(anchor + SYN_SPAN for anchor in anchors) + 64)
    for value, marker, anchor in zip(values, markers, anchors):
        out[anchor:anchor + SYN_SPAN] = _block(value, marker, anchor)
    return bytes(out)


def _occurrence(member: str, side: str, ordinal: int, anchor: int, value: float, count: int) -> dict[str, object]:
    return {
        "normalized_path": SYN_PATH,
        "member_key": member,
        "member_name": member.split("#", 1)[0],
        "side": side,
        "technical_member_role": "character_effect_container",
        "bounded_name_scope": "synthetic",
        "character_slot": "PC02",
        "record_start": anchor + 108,
        "normalized_endpoint": SYN_ENDPOINT,
        "paired_float_value": f"{value:.9g}",
        "known_stage101_occurrence": False,
        "additional_sibling_occurrence": True,
        "section_mode_or_flag_word": 2,
        "section_mode_or_flag_hex": "0x00000002",
        "section_count": count,
        "section_declared_span": max(anchors := [anchor], default=anchor) + SYN_SPAN - SYN_ENDPOINT,
        "section_declared_end": anchor + SYN_SPAN,
        "section_table_boundary_1": 56 + 4 * (count - 1),
        "section_table_boundary_2": 56 + 8 * (count - 1),
        "section_table_boundary_3": 56 + 12 * (count - 1),
        "record_relative_offset": anchor + 108 - SYN_ENDPOINT,
        "record_end_relative_offset": anchor + 108 + 44 - SYN_ENDPOINT,
        "distance_after_table_boundary_3": 0,
        "declared_tail_bytes_after_record": SYN_SPAN - 108 - 44,
        "template_ordinal_within_section": ordinal,
        "template_occurrences_in_section": count,
        "template_coverage_of_section_count": "full",
        "previous_template_gap_bytes": "",
        "next_template_gap_bytes": "",
        "record_inside_declared_span": True,
        "classification": "additional_exact_format_valid_sibling_template_occurrence",
    }


def _zero_model(pair_id: str, member: str, count: int) -> dict[str, object]:
    return {
        "pair_id": pair_id,
        "model_id": pair_id + "|zero_edit_uniform_offset_shift|",
        "normalized_path": SYN_PATH,
        "member_key": member,
        "member_name": member.split("#", 1)[0],
        "source_endpoint": SYN_ENDPOINT,
        "target_endpoint": SYN_ENDPOINT,
        "edit_kind": "zero_edit_uniform_offset_shift",
        "edit_ordinal": "",
        "matched_ordinal_pairs": ";".join(f"{i}->{i}" for i in range(count)),
        "offset_delta_vector": ";".join("0" for _ in range(count)),
        "pre_edit_offset_shift": 0,
        "post_edit_offset_shift": "",
        "matched_occurrence_rows": count,
        "stable_value_rows_diagnostic": count,
        "changed_value_rows_diagnostic": 0,
        "mutual_unique_section_pair": True,
        "selected_for_resolved_transitions": True,
        "selection_basis": "unique_zero_edit_uniform_offset_alignment",
        "classification": "selected_bounded_alignment_model",
    }


def _insert_model(pair_id: str, member: str, ordinal: int, source_count: int, *, selected: bool = False) -> dict[str, object]:
    pairs = [(i, i if i < ordinal else i + 1) for i in range(source_count)]
    return {
        "pair_id": pair_id,
        "model_id": f"{pair_id}|target_insertion_piecewise_offset_shift|{ordinal}",
        "normalized_path": SYN_PATH,
        "member_key": member,
        "member_name": member.split("#", 1)[0],
        "source_endpoint": SYN_ENDPOINT,
        "target_endpoint": SYN_ENDPOINT,
        "edit_kind": "target_insertion_piecewise_offset_shift",
        "edit_ordinal": ordinal,
        "matched_ordinal_pairs": ";".join(f"{a}->{b}" for a, b in pairs),
        "offset_delta_vector": ";".join("0" for _ in pairs),
        "pre_edit_offset_shift": 0,
        "post_edit_offset_shift": 0,
        "matched_occurrence_rows": len(pairs),
        "stable_value_rows_diagnostic": 0,
        "changed_value_rows_diagnostic": len(pairs),
        "mutual_unique_section_pair": True,
        "selected_for_resolved_transitions": selected,
        "selection_basis": "stage99_independent_insertion_shift_continuity_canary" if selected else "",
        "classification": "selected_bounded_alignment_model" if selected else "one_edit_alignment_model",
    }


def _full_fixture(root: Path) -> tuple[Path, object]:
    reports = root / "reports"
    for directory in (S.STAGE108_DIR, S.STAGE109_DIR, S.STAGE111_DIR, S.STAGE112_DIR):
        (reports / directory).mkdir(parents=True, exist_ok=True)
    (reports / S.STAGE108_DIR / "SUMMARY.json").write_text(json.dumps({
        "type": "br_quartet_restoration_br1_official_source_retirement_closure_evidence_summary",
        "tool_version": "0.1.22", "status": "underscore_archive_retirement_closed",
        "retirement_complete": True, "underscore_archives_required_for_normal_workflow": False,
    }), encoding="utf-8")

    specs = {
        "ref_a.g1e#0": ([1.0, 2.0], [10, 30], [1.0, 2.0], [20, 30]),
        "ref_b.g1e#0": ([3.0, 4.0], [10, 40], [3.0, 4.0], [20, 40]),
        "ambiguous.g1e#0": ([5.0, 6.0], [10, 30], [5.0, 7.0, 6.0], [20, 99, 30]),
        SYN_CANARY: ([30.0, 150.0, 2.0], [100, 300, 400], [30.0, 75.0, 75.0, 2.0], [100, 200, 300, 400]),
    }
    occurrence_rows: list[dict[str, object]] = []
    source_members = []
    target_members = []
    decisions = []
    models = []
    continuity = []
    stage112_decisions = []
    base = 400
    for index, (member, (svals, smarks, tvals, tmarks)) in enumerate(specs.items()):
        source_anchors = [base + i * SYN_SPAN for i in range(len(svals))]
        target_anchors = [base + i * SYN_SPAN for i in range(len(tvals))]
        for side, anchors, values in (("source", source_anchors, svals), ("target", target_anchors, tvals)):
            for ordinal, (anchor, value) in enumerate(zip(anchors, values)):
                occurrence_rows.append(_occurrence(member, side, ordinal, anchor, value, len(values)))
        source_members.append({"comparison_key": member, "name": member.split("#", 1)[0], "payload": _payload(svals, smarks, source_anchors)})
        target_members.append({"comparison_key": member, "name": member.split("#", 1)[0], "payload": _payload(tvals, tmarks, target_anchors)})
        pair_id = f"{SYN_PATH}|{member}|{SYN_ENDPOINT}|{SYN_ENDPOINT}"
        if member.startswith("ref_"):
            decisions.append({
                "pair_id": pair_id, "normalized_path": SYN_PATH, "member_key": member, "member_name": member.split("#", 1)[0],
                "technical_member_role": "character_effect_container", "source_endpoint": SYN_ENDPOINT, "target_endpoint": SYN_ENDPOINT,
                "source_values": ";".join(f"{v:.9g}" for v in svals), "target_values": ";".join(f"{v:.9g}" for v in tvals),
                "alignment_model_rows": 1, "selected_model_id": pair_id + "|zero_edit_uniform_offset_shift|",
                "selection_basis": "unique_zero_edit_uniform_offset_alignment", "classification": "resolved_zero_edit_normalized_pair",
            })
            models.append(_zero_model(pair_id, member, len(svals)))
        else:
            inserted_models = [_insert_model(pair_id, member, i, len(svals), selected=(member == SYN_CANARY and i == 1)) for i in range(len(tvals))]
            models.extend(inserted_models)
            is_canary = member == SYN_CANARY
            decisions.append({
                "pair_id": pair_id, "normalized_path": SYN_PATH, "member_key": member, "member_name": member.split("#", 1)[0],
                "technical_member_role": "ringlight" if is_canary else "character_effect_container",
                "source_endpoint": SYN_ENDPOINT, "target_endpoint": SYN_ENDPOINT,
                "source_values": ";".join(f"{v:.9g}" for v in svals), "target_values": ";".join(f"{v:.9g}" for v in tvals),
                "alignment_model_rows": len(inserted_models),
                "selected_model_id": inserted_models[1]["model_id"] if is_canary else "",
                "selection_basis": "stage99_independent_insertion_shift_continuity_canary" if is_canary else "",
                "classification": "resolved_one_edit_canary_pair" if is_canary else "unresolved_multiple_one_edit_models",
            })
            stage112_decisions.append({
                "pair_id": pair_id, "normalized_path": SYN_PATH, "member_key": member, "member_name": member.split("#", 1)[0],
                "source_values": ";".join(f"{v:.9g}" for v in svals), "target_values": ";".join(f"{v:.9g}" for v in tvals),
                "model_rows": len(inserted_models), "identity_eligible_model_rows": 0,
                "selected_model_id": inserted_models[1]["model_id"] if is_canary else "",
                "selection_basis": "stage99_immutable_canary_decision" if is_canary else "",
                "classification": "canary_identity_preserved" if is_canary else "occurrence_identity_unresolved_no_unique_exact_block_model",
            })
            for item in inserted_models:
                continuity.append({
                    "pair_id": pair_id, "model_id": item["model_id"],
                    "all_reference_deltas_compensate_anchor_shift": True,
                    "edit_block_distinct_from_all_matched_blocks": True,
                })
        base += 5000

    _write_tsv(reports / S.STAGE109_DIR / "SLOT_LIGHT_SIBLING_SECTION_LAYOUT_OCCURRENCES.tsv", occurrence_rows)
    (reports / S.STAGE109_DIR / "SUMMARY.json").write_text(json.dumps({
        "type": "br_quartet_restoration_reflector_slot_light_sibling_section_layout_evidence_summary",
        "tool_version": "0.1.23", "revalidated_occurrence_rows": len(occurrence_rows), "skipped_rows": 0,
    }), encoding="utf-8")
    _write_tsv(reports / S.STAGE111_DIR / "SLOT_LIGHT_EDIT_NORMALIZED_SECTION_PAIR_DECISIONS.tsv", decisions)
    _write_tsv(reports / S.STAGE111_DIR / "SLOT_LIGHT_EDIT_NORMALIZED_ALIGNMENT_MODELS.tsv", models)
    (reports / S.STAGE111_DIR / "SUMMARY.json").write_text(json.dumps({
        "type": "br_quartet_restoration_reflector_slot_light_edit_normalized_layout_alignment_evidence_summary",
        "tool_version": "0.1.25", "zero_edit_resolved_pair_rows": 2, "unresolved_one_edit_pair_rows": 1,
        "one_edit_alignment_model_rows": 7, "independently_resolved_canary_pair_rows": 1, "prototype_candidate_rows": 0,
    }), encoding="utf-8")
    _write_tsv(reports / S.STAGE112_DIR / "SLOT_LIGHT_UNRESOLVED_EDIT_MODEL_CONTINUITY.tsv", continuity)
    _write_tsv(reports / S.STAGE112_DIR / "SLOT_LIGHT_UNRESOLVED_EDIT_PAIR_DECISIONS.tsv", stage112_decisions)
    (reports / S.STAGE112_DIR / "SUMMARY.json").write_text(json.dumps({
        "type": "br_quartet_restoration_reflector_slot_light_unresolved_edit_block_continuity_evidence_summary",
        "tool_version": "0.1.27", "input_unresolved_one_edit_pair_rows": 1, "input_unresolved_one_edit_model_rows": 3,
        "canary_model_rows": 4, "newly_resolved_noncanary_pair_rows": 0, "still_unresolved_noncanary_pair_rows": 1,
        "canary_identity_preserved": True, "skipped_rows": 0,
    }), encoding="utf-8")

    def loader(**_kwargs: object):
        return ([{"normalized_path": SYN_PATH, "source_members": source_members, "target_members": target_members}], [])
    return reports, loader


class Stage113FullBuildTests(unittest.TestCase):
    def test_full_build_uses_independent_reference_and_resolves_unique_model(self) -> None:
        names = [name for name in vars(S) if name.startswith("EXPECTED_")]
        originals = {name: getattr(S, name) for name in names}
        original_paths = S.SCOPED_PATHS
        original_canary_path = S.CANARY_PATH
        original_canary_key = S.CANARY_MEMBER_KEY
        try:
            S.EXPECTED_STAGE109_OCCURRENCES = 20
            S.EXPECTED_STAGE111_ZERO_EDIT_PAIRS = 2
            S.EXPECTED_REFERENCE_ZERO_EDIT_PAIRS = 2
            S.EXPECTED_UNRESOLVED_PAIRS = 1
            S.EXPECTED_UNRESOLVED_MODELS = 3
            S.EXPECTED_CANARY_MODELS = 4
            S.EXPECTED_PARENT_CONTAINERS = 1
            S.EXPECTED_TOTAL_SCOPED_DECISIONS = 4
            S.EXPECTED_TOTAL_SCOPED_MEMBER_PAIRS = 4
            S.SCOPED_PATHS = {SYN_PATH}
            S.CANARY_PATH = SYN_PATH
            S.CANARY_MEMBER_KEY = SYN_CANARY
            with tempfile.TemporaryDirectory(prefix="stage113-full-") as name:
                reports, loader = _full_fixture(Path(name))
                output, archive, summary = S.build_report(
                    ROOT, create_archive=False, report_root=reports, container_loader=loader,
                    scope_rows_override=[{"normalized_path": SYN_PATH}],
                )
                self.assertIsNone(archive)
                self.assertEqual(summary["resolved_zero_edit_reference_pair_rows"], 2)
                self.assertEqual(summary["recurrence_mask_eligible_transition_class_rows"], 1)
                self.assertEqual(summary["newly_resolved_noncanary_pair_rows"], 1)
                self.assertEqual(summary["still_unresolved_noncanary_pair_rows"], 0)
                self.assertTrue(summary["canary_identity_preserved"])
                self.assertTrue((output / "SLOT_LIGHT_UNRESOLVED_PAIR_RECURRENCE_DECISIONS.tsv").is_file())
        finally:
            for key, value in originals.items():
                setattr(S, key, value)
            S.SCOPED_PATHS = original_paths
            S.CANARY_PATH = original_canary_path
            S.CANARY_MEMBER_KEY = original_canary_key
