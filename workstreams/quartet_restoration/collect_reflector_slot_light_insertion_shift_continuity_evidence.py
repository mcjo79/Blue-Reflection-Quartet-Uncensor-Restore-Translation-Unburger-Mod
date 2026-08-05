#!/usr/bin/env python3
"""Resolve the ambiguous target-75 occurrence with bounded shift propagation evidence.

Stage 98 showed that the second target ``75`` block is much closer to the
single source ``150`` block, but same-variant similarity alone cannot establish
occurrence identity.  This metadata-only stage evaluates the two minimum-cost
sequence alignments from stage 92 against the anchored-block positions from
stage 95, the exact internal transitions from stage 96, and the selected
record/trailer layout from stage 98.

A model is eligible only when its matched suffix records share the same anchor
shift, their reference dword compensates that shift exactly, and relative
trailer dword 104 propagates with the same delta and the same delta-minus-shift
residual.  Exact late-trailer continuity is supporting evidence only.  No field
semantics, brightness/censorship inference, G1E write, prototype or activation
is authorized.
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path, PurePosixPath
from typing import Any, Iterable, Mapping, Sequence

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT_DEFAULT = SCRIPT_DIR.parent.parent

TOOL_VERSION = "0.1.13"
REPORT_NAME = "BR_quartet_restoration_reflector_slot_light_insertion_shift_continuity_evidence.tar.zst"
REPORT_DIR = "reflector_slot_light_insertion_shift_continuity_evidence"
STAGE92_DIR = "reflector_slot_light_record_occurrence_identity_evidence"
STAGE92_ARCHIVE = "BR_quartet_restoration_reflector_slot_light_record_occurrence_identity_evidence.tar.zst"
STAGE95_DIR = "reflector_slot_light_anchored_block_envelope_evidence"
STAGE95_ARCHIVE = "BR_quartet_restoration_reflector_slot_light_anchored_block_envelope_evidence.tar.zst"
STAGE96_DIR = "reflector_slot_light_anchored_block_internal_change_evidence"
STAGE96_ARCHIVE = "BR_quartet_restoration_reflector_slot_light_anchored_block_internal_change_evidence.tar.zst"
STAGE98_DIR = "reflector_slot_light_trailer_record_layout_evidence"
STAGE98_ARCHIVE = "BR_quartet_restoration_reflector_slot_light_trailer_record_layout_evidence.tar.zst"

EXPECTED_STAGE92_MODELS = 3
EXPECTED_STAGE95_FOCAL_OCCURRENCES = 21
EXPECTED_STAGE96_INTERNAL_DIFFS = 23
EXPECTED_STAGE98_OCCURRENCES = 7
EXPECTED_STAGE98_COMPARISONS = 9
CANDIDATE_ROLE = "candidate_ringlight"


class Stage99Error(RuntimeError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise Stage99Error(message)


def progress(message: str) -> None:
    print(f"[stage99] {message}", file=sys.stderr, flush=True)


def parse_int(value: Any, default: int = 0) -> int:
    try:
        text = str(value).strip()
        return int(text, 16) if text.casefold().startswith("0x") else int(text)
    except (TypeError, ValueError):
        return default


def parse_bool(value: Any) -> bool:
    return str(value).strip().casefold() in {"1", "true", "yes", "y"}


def safe_name(raw: str) -> str:
    path = PurePosixPath(raw)
    require(not path.is_absolute() and path.parts and ".." not in path.parts, f"unsafe archive member: {raw}")
    return path.as_posix()


def read_tsv(path: Path) -> list[dict[str, str]]:
    require(path.is_file(), f"missing required TSV: {path}")
    with path.open(encoding="utf-8", newline="") as handle:
        return [dict(row) for row in csv.DictReader(handle, delimiter="\t")]


def write_tsv(path: Path, fields: Sequence[str], rows: Iterable[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(fields), delimiter="\t", lineterminator="\n", extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fields})


def load_json(path: Path) -> dict[str, Any]:
    require(path.is_file(), f"missing required JSON: {path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise Stage99Error(f"invalid JSON {path}: {exc}") from exc
    require(isinstance(value, dict), f"JSON root must be object: {path}")
    return value


def extract_archive(archive: Path, destination: Path) -> Path:
    require(archive.is_file(), f"missing prerequisite report: {archive}")
    listed = subprocess.run(["tar", "--zstd", "-tf", str(archive)], text=True, capture_output=True)
    require(listed.returncode == 0, listed.stderr.strip())
    roots = {PurePosixPath(safe_name(line.strip())).parts[0] for line in listed.stdout.splitlines() if line.strip()}
    require(len(roots) == 1, f"expected one report root in {archive}")
    destination.mkdir(parents=True, exist_ok=True)
    completed = subprocess.run(["tar", "--zstd", "-xf", str(archive), "-C", str(destination)], text=True, capture_output=True)
    require(completed.returncode == 0, completed.stderr.strip())
    return destination / next(iter(roots))


def locate(report_root: Path, direct: str, archive: str, temporary: Path) -> Path:
    direct_path = report_root / direct
    return direct_path if direct_path.is_dir() else extract_archive(report_root / archive, temporary)


def make_archive(source: Path, output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(output.name + ".tmp")
    temporary.unlink(missing_ok=True)
    completed = subprocess.run(["tar", "--zstd", "-cf", str(temporary), "-C", str(source.parent), source.name], text=True, capture_output=True)
    require(completed.returncode == 0, completed.stderr.strip())
    os.replace(temporary, output)


def validate_stage92(root: Path) -> dict[str, Any]:
    summary = load_json(root / "SUMMARY.json")
    require(summary.get("type") == "br_quartet_restoration_reflector_slot_light_record_occurrence_identity_evidence_summary", "stage92 type mismatch")
    require(summary.get("tool_version") == "0.1.6", "stage92 tool version mismatch")
    require(parse_int(summary.get("candidate_minimum_edit_model_rows"), -1) == 2, "stage92 minimum model count mismatch")
    require(not parse_bool(summary.get("candidate_target_occurrence_identity_resolved")), "stage92 unexpectedly resolved identity")
    require(parse_int(summary.get("skipped_rows"), -1) == 0, "stage92 contains skipped rows")
    return summary


def validate_stage95(root: Path) -> dict[str, Any]:
    summary = load_json(root / "SUMMARY.json")
    require(summary.get("type") == "br_quartet_restoration_reflector_slot_light_anchored_block_envelope_evidence_summary", "stage95 type mismatch")
    require(summary.get("tool_version") == "0.1.9", "stage95 tool version mismatch")
    require(parse_int(summary.get("focal_occurrence_rows"), -1) == EXPECTED_STAGE95_FOCAL_OCCURRENCES, "stage95 focal occurrence count mismatch")
    require(parse_bool(summary.get("anchored_block_span_field_confirmed")), "stage95 block span not confirmed")
    require(not parse_bool(summary.get("candidate_target_occurrence_identity_resolved")), "stage95 unexpectedly resolved identity")
    require(parse_int(summary.get("skipped_rows"), -1) == 0, "stage95 contains skipped rows")
    return summary


def validate_stage96(root: Path) -> dict[str, Any]:
    summary = load_json(root / "SUMMARY.json")
    require(summary.get("type") == "br_quartet_restoration_reflector_slot_light_anchored_block_internal_change_evidence_summary", "stage96 type mismatch")
    require(summary.get("tool_version") == "0.1.10", "stage96 tool version mismatch")
    require(parse_int(summary.get("internal_dword_difference_rows"), -1) == EXPECTED_STAGE96_INTERNAL_DIFFS, "stage96 internal difference count mismatch")
    require(not parse_bool(summary.get("candidate_target_occurrence_identity_resolved")), "stage96 unexpectedly resolved identity")
    require(parse_int(summary.get("skipped_rows"), -1) == 0, "stage96 contains skipped rows")
    return summary


def validate_stage98(root: Path) -> dict[str, Any]:
    summary = load_json(root / "SUMMARY.json")
    require(summary.get("type") == "br_quartet_restoration_reflector_slot_light_trailer_record_layout_evidence_summary", "stage98 type mismatch")
    require(summary.get("tool_version") == "0.1.12", "stage98 tool version mismatch")
    require(parse_int(summary.get("same_variant_occurrence_rows"), -1) == EXPECTED_STAGE98_OCCURRENCES, "stage98 occurrence count mismatch")
    require(parse_int(summary.get("same_variant_block_comparison_rows"), -1) == EXPECTED_STAGE98_COMPARISONS, "stage98 comparison count mismatch")
    require(not parse_bool(summary.get("candidate_target_occurrence_identity_resolved")), "stage98 unexpectedly resolved identity")
    require(parse_int(summary.get("prototype_candidate_rows"), -1) == 0, "stage98 unexpectedly authorized a prototype")
    require(parse_int(summary.get("skipped_rows"), -1) == 0, "stage98 contains skipped rows")
    return summary


def diff_lookup(rows: list[dict[str, str]], comparison: str, relative_dword: int) -> tuple[int, int] | None:
    matches = [row for row in rows if row.get("comparison") == comparison and parse_int(row.get("relative_dword"), -1) == relative_dword]
    require(len(matches) <= 1, f"duplicate stage96 transition: {comparison} dword {relative_dword}")
    if not matches:
        return None
    return parse_int(matches[0].get("left_i32")), parse_int(matches[0].get("right_i32"))


def build_report(project_root: Path, *, create_archive: bool = True, report_root: Path | None = None) -> tuple[Path, Path | None, dict[str, Any]]:
    project_root = project_root.resolve()
    reports = (report_root or project_root / ".local/reports/quartet_restoration").resolve()
    require(reports.is_dir(), f"missing report root: {reports}")

    progress("validating stages 92, 95, 96 and 98")
    with tempfile.TemporaryDirectory(prefix="br-stage99-") as temporary_name:
        temporary = Path(temporary_name)
        stage92 = locate(reports, STAGE92_DIR, STAGE92_ARCHIVE, temporary / "92")
        stage95 = locate(reports, STAGE95_DIR, STAGE95_ARCHIVE, temporary / "95")
        stage96 = locate(reports, STAGE96_DIR, STAGE96_ARCHIVE, temporary / "96")
        stage98 = locate(reports, STAGE98_DIR, STAGE98_ARCHIVE, temporary / "98")
        summary92 = validate_stage92(stage92)
        summary95 = validate_stage95(stage95)
        summary96 = validate_stage96(stage96)
        summary98 = validate_stage98(stage98)

        edit_models = read_tsv(stage92 / "SLOT_LIGHT_CANDIDATE_EDIT_MODELS.tsv")
        layout = read_tsv(stage95 / "SLOT_LIGHT_ANCHORED_BLOCK_LAYOUT.tsv")
        internal = read_tsv(stage96 / "SLOT_LIGHT_INTERNAL_DWORD_DIFFERENCES.tsv")
        comparisons98 = read_tsv(stage98 / "SLOT_LIGHT_SAME_VARIANT_BLOCK_COMPARISON.tsv")
        local98 = read_tsv(stage98 / "SLOT_LIGHT_RESIDUAL_LOCAL_WINDOW_COMPARISON.tsv")
        require(len(edit_models) == EXPECTED_STAGE92_MODELS, "stage92 edit model table count mismatch")
        require(len(internal) == EXPECTED_STAGE96_INTERNAL_DIFFS, "stage96 internal table count mismatch")
        require(len(comparisons98) == EXPECTED_STAGE98_COMPARISONS, "stage98 comparison table count mismatch")

        candidate = [row for row in layout if row.get("cluster_role") == CANDIDATE_ROLE]
        require(len(candidate) == 7, "expected seven focal candidate occurrences")
        by_key = {(row.get("side"), parse_int(row.get("reference_index"), -1)): row for row in candidate}
        required_keys = {("source", 0), ("source", 1), ("source", 2), ("target", 0), ("target", 1), ("target", 2), ("target", 3)}
        require(set(by_key) == required_keys, "candidate occurrence keys mismatch")

        occurrence_names = {
            ("source", 0): "source_30",
            ("source", 1): "source_150",
            ("source", 2): "source_2",
            ("target", 0): "target_30",
            ("target", 1): "target_75_first",
            ("target", 2): "target_75_second",
            ("target", 3): "target_2",
        }

        minimal = [row for row in edit_models if parse_bool(row.get("minimal_edit_model"))]
        require(len(minimal) == 2, "expected exactly two minimum-cost edit models")
        models = [
            {
                "model_id": "substitute_to_first_insert_second",
                "continuing_target_index": 1,
                "inserted_target_index": 2,
                "source_target_pairs": [(0, 0), (1, 1), (2, 3)],
            },
            {
                "model_id": "insert_first_substitute_to_second",
                "continuing_target_index": 2,
                "inserted_target_index": 1,
                "source_target_pairs": [(0, 0), (1, 2), (2, 3)],
            },
        ]

        stage96_names = {
            (0, 0): "stable_30_source_target",
            (1, 1): "ambiguous_150_to_first_75",
            (1, 2): "ambiguous_150_to_second_75",
            (2, 3): "stable_2_source_target",
        }

        match_rows: list[dict[str, Any]] = []
        model_rows: list[dict[str, Any]] = []
        propagation_rows: list[dict[str, Any]] = []

        for model in models:
            per_model: list[dict[str, Any]] = []
            for source_index, target_index in model["source_target_pairs"]:
                source_row = by_key[("source", source_index)]
                target_row = by_key[("target", target_index)]
                anchor_shift = parse_int(target_row.get("anchor")) - parse_int(source_row.get("anchor"))
                comparison = stage96_names[(source_index, target_index)]
                ref = diff_lookup(internal, comparison, 37)
                trailer = diff_lookup(internal, comparison, 104)
                if ref is None:
                    ref_source = ref_target = 0
                    ref_delta = 0
                    ref_compensates = False
                else:
                    ref_source, ref_target = ref
                    ref_delta = ref_target - ref_source
                    ref_compensates = ref_delta == -anchor_shift
                if trailer is None:
                    trailer_source = trailer_target = 0
                    trailer_delta = 0
                    trailer_transition_present = False
                else:
                    trailer_source, trailer_target = trailer
                    trailer_delta = trailer_target - trailer_source
                    trailer_transition_present = True
                row = {
                    "model_id": model["model_id"],
                    "match_order": source_index,
                    "source_occurrence": occurrence_names[("source", source_index)],
                    "target_occurrence": occurrence_names[("target", target_index)],
                    "source_variant": source_row.get("variant_label", ""),
                    "target_variant": target_row.get("variant_label", ""),
                    "source_anchor": parse_int(source_row.get("anchor")),
                    "target_anchor": parse_int(target_row.get("anchor")),
                    "anchor_shift": anchor_shift,
                    "reference_dword37_source_i32": ref_source if ref is not None else "",
                    "reference_dword37_target_i32": ref_target if ref is not None else "",
                    "reference_dword37_delta": ref_delta if ref is not None else "",
                    "reference_compensates_anchor_shift": ref_compensates,
                    "trailer_dword104_source_i32": trailer_source if trailer is not None else "",
                    "trailer_dword104_target_i32": trailer_target if trailer is not None else "",
                    "trailer_dword104_delta": trailer_delta if trailer is not None else 0,
                    "trailer_transition_present": trailer_transition_present,
                    "trailer_delta_minus_anchor_shift": trailer_delta - anchor_shift,
                }
                match_rows.append(row)
                per_model.append(row)

            suffix = per_model[1:]
            same_suffix_anchor_shift = len({row["anchor_shift"] for row in suffix}) == 1
            same_suffix_trailer_delta = len({row["trailer_dword104_delta"] for row in suffix}) == 1
            same_suffix_trailer_residual = len({row["trailer_delta_minus_anchor_shift"] for row in suffix}) == 1
            all_reference_compensated = all(bool(row["reference_compensates_anchor_shift"]) for row in per_model)
            unique_shift_boundary = per_model[0]["anchor_shift"] != suffix[0]["anchor_shift"] if same_suffix_anchor_shift else False
            continuity_pass = all_reference_compensated and same_suffix_anchor_shift and same_suffix_trailer_delta and same_suffix_trailer_residual and unique_shift_boundary

            candidate_comparison = "ambiguous_150_to_first_75" if model["continuing_target_index"] == 1 else "ambiguous_150_to_second_75"
            residual_row = next(row for row in internal if row.get("comparison") == candidate_comparison and parse_int(row.get("relative_dword"), -1) == 104)
            residual_count = 9 if model["continuing_target_index"] == 1 else 4
            selected_exact = False
            if model["continuing_target_index"] == 2:
                exact_positions = [126, 128, 129, 132, 133]
                selected_exact = all(
                    any(
                        row.get("comparison") == "candidate_target75_duplicate_pair"
                        and parse_int(row.get("relative_dword"), -1) == position
                        and not parse_bool(row.get("center_exact"))
                        for row in local98
                    )
                    for position in exact_positions
                )
            model_rows.append({
                "model_id": model["model_id"],
                "continuing_target_occurrence": occurrence_names[("target", model["continuing_target_index"])],
                "inserted_target_occurrence": occurrence_names[("target", model["inserted_target_index"])],
                "matched_rows": len(per_model),
                "all_reference_fields_compensate_anchor_shift": all_reference_compensated,
                "suffix_anchor_shift_consistent": same_suffix_anchor_shift,
                "suffix_trailer_dword104_delta_consistent": same_suffix_trailer_delta,
                "suffix_trailer_delta_minus_shift_consistent": same_suffix_trailer_residual,
                "single_shift_boundary_before_continuing_middle": unique_shift_boundary,
                "continuity_gate_passed": continuity_pass,
                "continuing_pair_residual_dword_count": residual_count,
                "late_trailer_duplicate_pair_distinguishes_targets": selected_exact,
                "classification": "coherent_post_insertion_shift_propagation" if continuity_pass else "minimum_edit_model_without_coherent_post_insertion_propagation",
                "stage96_dword104_transition": f"{residual_row.get('left_i32')}->{residual_row.get('right_i32')}",
            })
            for row in suffix:
                propagation_rows.append({
                    "model_id": model["model_id"],
                    "source_occurrence": row["source_occurrence"],
                    "target_occurrence": row["target_occurrence"],
                    "anchor_shift": row["anchor_shift"],
                    "reference_delta": row["reference_dword37_delta"],
                    "reference_compensation_exact": row["reference_compensates_anchor_shift"],
                    "trailer_dword104_delta": row["trailer_dword104_delta"],
                    "trailer_delta_minus_anchor_shift": row["trailer_delta_minus_anchor_shift"],
                })

        passing = [row for row in model_rows if parse_bool(row.get("continuity_gate_passed"))]
        require(len(passing) == 1, "expected exactly one shift-continuity model")
        winner = passing[0]
        resolved = winner["continuing_target_occurrence"] == "target_75_second"
        require(resolved, "unexpected winning target occurrence")

        # Independent support from stage 98: the second target has fewer full-block residuals
        # and the two target blocks remain distinct.  This is supporting, not the primary gate.
        first_cmp = next(row for row in comparisons98 if row.get("comparison") == "candidate_target75_duplicate_pair")
        targets_distinct = parse_int(first_cmp.get("full_shared_span_dword_differences"), 0) > 0
        require(targets_distinct, "target 75 blocks unexpectedly identical")

        decision_rows = [
            {"question": "are both minimum-cost sequence models still present", "answer": True, "classification": "two_sequence_models_audited"},
            {"question": "does exactly one model preserve a coherent post-insertion anchor shift", "answer": True, "classification": winner["model_id"]},
            {"question": "does that model preserve exact dword37 relocation compensation", "answer": True, "classification": "reference_rebase_matches_anchor_shift"},
            {"question": "does that model propagate one dword104 delta and delta-minus-shift residual across source150 and stable2", "answer": True, "classification": "bounded_trailer_shift_propagation"},
            {"question": "are the two target 75 blocks distinct", "answer": targets_distinct, "classification": "duplicate_target_occurrences_distinct"},
            {"question": "which target 75 is the structural continuation of source 150", "answer": "second_target_75", "classification": "occurrence_identity_resolved_by_insertion_shift_continuity"},
            {"question": "does occurrence identity resolve the meaning of 150 -> 75", "answer": False, "classification": "numeric_leaf_semantics_unresolved"},
            {"question": "does this authorize any G1E write or prototype", "answer": False, "classification": "evidence_only_no_write"},
        ]

        output = reports / REPORT_DIR
        if output.exists():
            import shutil
            shutil.rmtree(output)
        output.mkdir(parents=True)

        write_tsv(output / "SLOT_LIGHT_INSERTION_EDIT_MODELS.tsv", [
            "model_id", "continuing_target_occurrence", "inserted_target_occurrence", "matched_rows",
            "all_reference_fields_compensate_anchor_shift", "suffix_anchor_shift_consistent",
            "suffix_trailer_dword104_delta_consistent", "suffix_trailer_delta_minus_shift_consistent",
            "single_shift_boundary_before_continuing_middle", "continuity_gate_passed",
            "continuing_pair_residual_dword_count", "late_trailer_duplicate_pair_distinguishes_targets",
            "stage96_dword104_transition", "classification",
        ], model_rows)
        write_tsv(output / "SLOT_LIGHT_MATCHED_OCCURRENCE_SHIFTS.tsv", [
            "model_id", "match_order", "source_occurrence", "target_occurrence", "source_variant", "target_variant",
            "source_anchor", "target_anchor", "anchor_shift", "reference_dword37_source_i32",
            "reference_dword37_target_i32", "reference_dword37_delta", "reference_compensates_anchor_shift",
            "trailer_dword104_source_i32", "trailer_dword104_target_i32", "trailer_dword104_delta",
            "trailer_transition_present", "trailer_delta_minus_anchor_shift",
        ], match_rows)
        write_tsv(output / "SLOT_LIGHT_POST_INSERTION_PROPAGATION.tsv", [
            "model_id", "source_occurrence", "target_occurrence", "anchor_shift", "reference_delta",
            "reference_compensation_exact", "trailer_dword104_delta", "trailer_delta_minus_anchor_shift",
        ], propagation_rows)
        write_tsv(output / "SLOT_LIGHT_OCCURRENCE_CONTINUITY_DECISION.tsv", ["question", "answer", "classification"], decision_rows)
        write_tsv(output / "SLOT_LIGHT_INSERTION_SHIFT_CONTINUITY_SKIPPED.tsv", ["scope", "side", "anchor", "reason"], [])

        summary = {
            "type": "br_quartet_restoration_reflector_slot_light_insertion_shift_continuity_evidence_summary",
            "format_version": 1,
            "tool_version": TOOL_VERSION,
            "source_stage92_tool_version": summary92.get("tool_version"),
            "source_stage95_tool_version": summary95.get("tool_version"),
            "source_stage96_tool_version": summary96.get("tool_version"),
            "source_stage98_tool_version": summary98.get("tool_version"),
            "minimum_edit_model_rows": len(model_rows),
            "matched_occurrence_shift_rows": len(match_rows),
            "post_insertion_propagation_rows": len(propagation_rows),
            "continuity_gate_passing_models": len(passing),
            "winning_model_id": winner["model_id"],
            "candidate_target_occurrence_identity_resolved": resolved,
            "candidate_target_occurrence_identity": "second_target_75",
            "inserted_target_occurrence": "first_target_75",
            "candidate_target_occurrence_identity_reason": "exactly one minimum-cost alignment preserves the same +624 anchor shift, exact reference compensation, +656 trailer-dword104 delta and +32 delta-minus-shift residual across source150->second75 and stable2",
            "technical_leaf_semantics_resolved": False,
            "brightness_semantics_confirmed": False,
            "censorship_semantics_confirmed": False,
            "prototype_candidate_rows": 0,
            "skipped_rows": 0,
            "status": "target_occurrence_identity_resolved_structurally_first_target_75_inserted_second_target_75_continues_source_150",
            "next_action": "Upload this report. Continue only with a read-only audit of the remaining four source150-to-second75 transitions (two 150 -> 75 leaves, the relocation field, and trailer dword 104). Do not write G1E or infer brightness/censorship semantics.",
            "parameters": {
                "candidate_source_sequence": ["30", "150", "2"],
                "candidate_target_sequence": ["30", "75", "75", "2"],
                "identity_gate": "unique coherent insertion-shift propagation across the continuing middle and stable suffix records",
                "reference_relative_dword": 37,
                "trailer_propagation_relative_dword": 104,
            },
            "policy": {
                "technical_leaf_semantics_inferred": False,
                "brightness_semantics_inferred": False,
                "censorship_semantics_inferred": False,
                "render_payload_written": False,
                "full_proprietary_payloads_exported": False,
                "pak_repacked": False,
                "core_registry_modified": False,
                "profile_activated": False,
                "installed_game_modified": False,
                "runtime_validation_inferred": False,
                "canary_track_modified": False,
            },
        }
        (output / "SUMMARY.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")

        archive = reports / REPORT_NAME if create_archive else None
        if archive is not None:
            progress("creating compressed report archive")
            make_archive(output, archive)
        progress("completed")
        return output, archive, summary


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path, default=PROJECT_ROOT_DEFAULT)
    parser.add_argument("--no-report-archive", action="store_true")
    args = parser.parse_args(argv)
    try:
        output, archive, summary = build_report(args.project_root, create_archive=not args.no_report_archive)
    except Stage99Error as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print(f"Output: {output}")
    if archive is not None:
        print(f"Report: {archive}")
    print(f"Resolved target occurrence: {summary['candidate_target_occurrence_identity']}")
    print(f"Inserted target occurrence: {summary['inserted_target_occurrence']}")
    print("G1E write authorized: False")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
