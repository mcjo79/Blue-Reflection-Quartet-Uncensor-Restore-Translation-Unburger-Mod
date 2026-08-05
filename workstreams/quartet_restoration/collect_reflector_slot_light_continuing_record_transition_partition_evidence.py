#!/usr/bin/env python3
"""Partition the four proven source-150 -> continuing-target-75 transitions.

Stage 99 resolved occurrence identity structurally: the first target 75 block is
inserted and the second target 75 block continues the single source 150 block.
This metadata-only stage combines stage-91 record inventory, stage-96 exact
internal differences and stage-99 shift continuity to separate:

* two paired numeric leaves (150 -> 75),
* one exact field-relative relocation rebase, and
* one bounded post-insertion trailer propagation field.

It also inventories dword-0/dword-1 value pairs across all 177 reference
records.  No field meaning, brightness/censorship claim, G1E write, prototype,
profile or activation is authorized.
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import subprocess
import sys
import tempfile
from collections import Counter, defaultdict
from pathlib import Path, PurePosixPath
from typing import Any, Iterable, Mapping, Sequence

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT_DEFAULT = SCRIPT_DIR.parent.parent

TOOL_VERSION = "0.1.14"
REPORT_NAME = "BR_quartet_restoration_reflector_slot_light_continuing_record_transition_partition_evidence.tar.zst"
REPORT_DIR = "reflector_slot_light_continuing_record_transition_partition_evidence"
STAGE91_DIR = "reflector_slot_light_section_cardinality_record_role_evidence"
STAGE91_ARCHIVE = "BR_quartet_restoration_reflector_slot_light_section_cardinality_record_role_evidence.tar.zst"
STAGE96_DIR = "reflector_slot_light_anchored_block_internal_change_evidence"
STAGE96_ARCHIVE = "BR_quartet_restoration_reflector_slot_light_anchored_block_internal_change_evidence.tar.zst"
STAGE99_DIR = "reflector_slot_light_insertion_shift_continuity_evidence"
STAGE99_ARCHIVE = "BR_quartet_restoration_reflector_slot_light_insertion_shift_continuity_evidence.tar.zst"

EXPECTED_RECORD_ROWS = 177
EXPECTED_RECORD_DWORD_ROWS = 1947
EXPECTED_INTERNAL_DIFF_ROWS = 23
EXPECTED_MATCHED_SHIFT_ROWS = 6
CONTINUING_COMPARISON = "ambiguous_150_to_second_75"
WINNING_MODEL = "insert_first_substitute_to_second"
EXPECTED_TRANSITION_DWORDS = (27, 28, 37, 104)


class Stage100Error(RuntimeError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise Stage100Error(message)


def progress(message: str) -> None:
    print(f"[stage100] {message}", file=sys.stderr, flush=True)


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
        raise Stage100Error(f"invalid JSON {path}: {exc}") from exc
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


def validate_stage91(root: Path) -> dict[str, Any]:
    summary = load_json(root / "SUMMARY.json")
    require(summary.get("type") == "br_quartet_restoration_reflector_slot_light_section_cardinality_record_role_evidence_summary", "stage91 type mismatch")
    require(summary.get("tool_version") == "0.1.5", "stage91 tool version mismatch")
    require(parse_int(summary.get("reference_record_rows"), -1) == EXPECTED_RECORD_ROWS, "stage91 record count mismatch")
    require(parse_int(summary.get("reference_record_dword_rows"), -1) == EXPECTED_RECORD_DWORD_ROWS, "stage91 record dword count mismatch")
    require(parse_int(summary.get("skipped_rows"), -1) == 0, "stage91 contains skipped rows")
    return summary


def validate_stage96(root: Path) -> dict[str, Any]:
    summary = load_json(root / "SUMMARY.json")
    require(summary.get("type") == "br_quartet_restoration_reflector_slot_light_anchored_block_internal_change_evidence_summary", "stage96 type mismatch")
    require(summary.get("tool_version") == "0.1.10", "stage96 tool version mismatch")
    require(parse_int(summary.get("internal_dword_difference_rows"), -1) == EXPECTED_INTERNAL_DIFF_ROWS, "stage96 difference count mismatch")
    require(not parse_bool(summary.get("candidate_target_occurrence_identity_resolved")), "stage96 unexpectedly resolved identity")
    require(parse_int(summary.get("skipped_rows"), -1) == 0, "stage96 contains skipped rows")
    return summary


def validate_stage99(root: Path) -> dict[str, Any]:
    summary = load_json(root / "SUMMARY.json")
    require(summary.get("type") == "br_quartet_restoration_reflector_slot_light_insertion_shift_continuity_evidence_summary", "stage99 type mismatch")
    require(summary.get("tool_version") == "0.1.13", "stage99 tool version mismatch")
    require(parse_bool(summary.get("candidate_target_occurrence_identity_resolved")), "stage99 did not resolve occurrence identity")
    require(summary.get("candidate_target_occurrence_identity") == "second_target_75", "stage99 continuation mismatch")
    require(summary.get("inserted_target_occurrence") == "first_target_75", "stage99 insertion mismatch")
    require(summary.get("winning_model_id") == WINNING_MODEL, "stage99 winning model mismatch")
    require(parse_int(summary.get("continuity_gate_passing_models"), -1) == 1, "stage99 continuity gate count mismatch")
    require(parse_int(summary.get("prototype_candidate_rows"), -1) == 0, "stage99 unexpectedly contains prototype candidates")
    require(parse_int(summary.get("skipped_rows"), -1) == 0, "stage99 contains skipped rows")
    return summary


def record_inventory(dword_rows: list[dict[str, str]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    grouped: dict[tuple[str, str, str, str, str], dict[int, dict[str, str]]] = defaultdict(dict)
    for row in dword_rows:
        key = (row.get("normalized_path", ""), row.get("member_key", ""), row.get("side", ""), row.get("reference_offset", ""), row.get("record_start", ""))
        grouped[key][parse_int(row.get("relative_dword"), -1)] = row
    require(len(grouped) == EXPECTED_RECORD_ROWS, f"expected {EXPECTED_RECORD_ROWS} reconstructed records, found {len(grouped)}")

    inventory: list[dict[str, Any]] = []
    distribution: Counter[tuple[str, str, str, str, str]] = Counter()
    for key, dwords in sorted(grouped.items()):
        require(0 in dwords and 1 in dwords, f"record lacks paired leaves: {key}")
        left, right = dwords[0], dwords[1]
        left_float = left.get("float32", "")
        right_float = right.get("float32", "")
        equal = left.get("u32_hex") == right.get("u32_hex")
        variant_interest = left_float in {"75", "150"} or right_float in {"75", "150"}
        row = {
            "normalized_path": key[0], "member_key": key[1], "member_name": left.get("member_name", ""),
            "side": key[2], "reference_offset": key[3], "record_start": key[4],
            "leaf0_u32_hex": left.get("u32_hex", ""), "leaf1_u32_hex": right.get("u32_hex", ""),
            "leaf0_float32": left_float, "leaf1_float32": right_float,
            "paired_equal_bits": equal, "is_75_or_150_variant": variant_interest,
            "variant_label": f"equal_float_{left_float}" if equal and left_float in {"75", "150"} else "other",
        }
        inventory.append(row)
        distribution[(key[2], left.get("u32_hex", ""), right.get("u32_hex", ""), left_float, right_float)] += 1

    dist_rows = [{
        "side": key[0], "leaf0_u32_hex": key[1], "leaf1_u32_hex": key[2],
        "leaf0_float32": key[3], "leaf1_float32": key[4], "record_rows": count,
        "paired_equal_bits": key[1] == key[2],
        "contains_75_or_150": key[3] in {"75", "150"} or key[4] in {"75", "150"},
    } for key, count in sorted(distribution.items())]
    return inventory, dist_rows


def build_report(project_root: Path, *, create_archive: bool = True, report_root: Path | None = None) -> tuple[Path, Path | None, dict[str, Any]]:
    report_root = report_root or project_root / ".local/reports/quartet_restoration"
    progress("validating prerequisite reports")
    with tempfile.TemporaryDirectory(prefix="br-stage100-") as temp_name:
        temp = Path(temp_name)
        stage91 = locate(report_root, STAGE91_DIR, STAGE91_ARCHIVE, temp / "stage91")
        stage96 = locate(report_root, STAGE96_DIR, STAGE96_ARCHIVE, temp / "stage96")
        stage99 = locate(report_root, STAGE99_DIR, STAGE99_ARCHIVE, temp / "stage99")
        validate_stage91(stage91)
        validate_stage96(stage96)
        validate_stage99(stage99)

        dword_rows = read_tsv(stage91 / "SLOT_LIGHT_REFERENCE_RECORD_DWORDS.tsv")
        require(len(dword_rows) == EXPECTED_RECORD_DWORD_ROWS, "stage91 dword TSV count mismatch")
        inventory, pair_distribution = record_inventory(dword_rows)

        internal = read_tsv(stage96 / "SLOT_LIGHT_INTERNAL_DWORD_DIFFERENCES.tsv")
        require(len(internal) == EXPECTED_INTERNAL_DIFF_ROWS, "stage96 difference TSV count mismatch")
        focal = [row for row in internal if row.get("comparison") == CONTINUING_COMPARISON]
        require(tuple(sorted(parse_int(row.get("relative_dword"), -1) for row in focal)) == EXPECTED_TRANSITION_DWORDS, "continuing comparison must contain exactly dwords 27, 28, 37 and 104")
        focal_by_dword = {parse_int(row.get("relative_dword"), -1): row for row in focal}

        shifts = read_tsv(stage99 / "SLOT_LIGHT_MATCHED_OCCURRENCE_SHIFTS.tsv")
        require(len(shifts) == EXPECTED_MATCHED_SHIFT_ROWS, "stage99 matched shift count mismatch")
        winning = [row for row in shifts if row.get("model_id") == WINNING_MODEL]
        require(len(winning) == 3, "stage99 winning model must contain three matched rows")
        continuing = next((row for row in winning if row.get("source_occurrence") == "source_150" and row.get("target_occurrence") == "target_75_second"), None)
        suffix = next((row for row in winning if row.get("source_occurrence") == "source_2" and row.get("target_occurrence") == "target_2"), None)
        require(continuing is not None and suffix is not None, "stage99 winning continuity rows missing")
        anchor_shift = parse_int(continuing.get("anchor_shift"), 0)
        require(anchor_shift == 624, "unexpected continuing anchor shift")
        require(parse_bool(continuing.get("reference_compensates_anchor_shift")), "continuing reference does not compensate shift")
        require(parse_int(continuing.get("trailer_dword104_delta"), 0) == parse_int(suffix.get("trailer_dword104_delta"), -1) == 656, "dword104 propagation mismatch")
        require(parse_int(continuing.get("trailer_delta_minus_anchor_shift"), 0) == parse_int(suffix.get("trailer_delta_minus_anchor_shift"), -1) == 32, "dword104 residual mismatch")

        source_anchor = parse_int(continuing.get("source_anchor"), 0)
        target_anchor = parse_int(continuing.get("target_anchor"), 0)
        source_ref_offset = source_anchor + 37 * 4
        target_ref_offset = target_anchor + 37 * 4
        ref_source = parse_int(focal_by_dword[37].get("left_i32"), 0)
        ref_target = parse_int(focal_by_dword[37].get("right_i32"), 0)
        source_endpoint = source_ref_offset + ref_source
        target_endpoint = target_ref_offset + ref_target
        require(source_endpoint == target_endpoint, "dword37 field-relative endpoint mismatch")

        interest = [row for row in inventory if row["is_75_or_150_variant"]]
        require(len(interest) == 7, f"expected seven 75/150 records, found {len(interest)}")
        require(all(row["paired_equal_bits"] for row in interest), "75/150 values must occur as equal pairs")
        count_150 = sum(row["variant_label"] == "equal_float_150" for row in interest)
        count_75 = sum(row["variant_label"] == "equal_float_75" for row in interest)
        require((count_150, count_75) == (3, 4), "75/150 occurrence counts mismatch")
        neutral = [row for row in interest if row["member_key"] == "e_cmn_pup_reflect_s.g1e#0"]
        require({(row["side"], row["variant_label"]) for row in neutral} == {
            ("source", "equal_float_150"), ("source", "equal_float_75"),
            ("target", "equal_float_150"), ("target", "equal_float_75"),
        }, "neutral member must stably contain both 150 and 75 variants")

        partition_rows: list[dict[str, Any]] = []
        for relative in EXPECTED_TRANSITION_DWORDS:
            row = focal_by_dword[relative]
            if relative in (27, 28):
                classification = "paired_equal_numeric_leaf_transition"
                role_resolved = False
                structural = False
                evidence = "150/150 and 75/75 are stable coexisting variants in the neutral member; numeric meaning unresolved"
            elif relative == 37:
                classification = "exact_field_relative_relocation_rebase"
                role_resolved = True
                structural = True
                evidence = f"delta {-anchor_shift} exactly compensates +{anchor_shift} anchor shift and preserves endpoint {source_endpoint}"
            else:
                classification = "bounded_post_insertion_trailer_propagation"
                role_resolved = False
                structural = True
                evidence = "delta +656 and delta-minus-anchor-shift +32 match the stable suffix record; exact field role unresolved"
            partition_rows.append({
                "relative_dword": relative,
                "relative_byte": parse_int(row.get("relative_byte"), relative * 4),
                "segment": row.get("segment", ""),
                "source_u32_hex": row.get("left_u32_hex", ""), "target_u32_hex": row.get("right_u32_hex", ""),
                "source_i32": row.get("left_i32", ""), "target_i32": row.get("right_i32", ""),
                "source_float32": row.get("left_float32", ""), "target_float32": row.get("right_float32", ""),
                "classification": classification, "structural_transition_supported": structural,
                "technical_field_role_resolved": role_resolved, "evidence": evidence,
            })

        normalization_rows = [
            {
                "field": "relative_dword_37", "source_value": ref_source, "target_value": ref_target,
                "source_anchor": source_anchor, "target_anchor": target_anchor, "anchor_shift": anchor_shift,
                "source_absolute_field_offset": source_ref_offset, "target_absolute_field_offset": target_ref_offset,
                "source_normalized_value": source_endpoint, "target_normalized_value": target_endpoint,
                "normalization": "absolute_field_offset + signed_i32(value)", "invariant_exact": True,
                "classification": "field_relative_section_reference",
            },
            {
                "field": "relative_dword_104", "source_value": parse_int(continuing.get("trailer_dword104_source_i32"), 0),
                "target_value": parse_int(continuing.get("trailer_dword104_target_i32"), 0),
                "source_anchor": source_anchor, "target_anchor": target_anchor, "anchor_shift": anchor_shift,
                "source_absolute_field_offset": source_anchor + 104 * 4, "target_absolute_field_offset": target_anchor + 104 * 4,
                "source_normalized_value": "", "target_normalized_value": "",
                "normalization": "target_delta - anchor_shift", "invariant_exact": True,
                "classification": "bounded_post_insertion_propagation_with_residual_32",
            },
        ]

        decision_rows = [
            {"question": "which target 75 structurally continues source 150", "answer": "second_target_75", "classification": "resolved_by_stage99_insertion_shift_continuity"},
            {"question": "which target 75 is inserted", "answer": "first_target_75", "classification": "resolved_by_stage99_insertion_shift_continuity"},
            {"question": "how many continuing-block transitions remain", "answer": 4, "classification": "two_numeric_leaves_one_relocation_one_trailer_field"},
            {"question": "is relative dword 37 a proven structural relocation", "answer": True, "classification": "exact_field_relative_endpoint_invariant"},
            {"question": "is relative dword 104 structurally propagated", "answer": True, "classification": "same_delta_and_delta_minus_shift_as_stable_suffix"},
            {"question": "is the exact technical role of dword 104 resolved", "answer": False, "classification": "bounded_propagation_only"},
            {"question": "do values 150 and 75 coexist stably in the neutral member", "answer": True, "classification": "separate_equal_pair_variants_not_global_migration"},
            {"question": "is the meaning of paired leaves 150 -> 75 resolved", "answer": False, "classification": "paired_numeric_variant_semantics_unresolved"},
            {"question": "does this authorize a G1E write or prototype", "answer": False, "classification": "evidence_only_no_write"},
        ]

        output = report_root / REPORT_DIR
        if output.exists():
            import shutil
            shutil.rmtree(output)
        output.mkdir(parents=True)
        write_tsv(output / "SLOT_LIGHT_CONTINUING_TRANSITION_PARTITION.tsv", [
            "relative_dword", "relative_byte", "segment", "source_u32_hex", "target_u32_hex", "source_i32", "target_i32",
            "source_float32", "target_float32", "classification", "structural_transition_supported", "technical_field_role_resolved", "evidence",
        ], partition_rows)
        write_tsv(output / "SLOT_LIGHT_PAIRED_LEAF_OCCURRENCE_INVENTORY.tsv", [
            "normalized_path", "member_key", "member_name", "side", "reference_offset", "record_start", "leaf0_u32_hex", "leaf1_u32_hex",
            "leaf0_float32", "leaf1_float32", "paired_equal_bits", "is_75_or_150_variant", "variant_label",
        ], interest)
        write_tsv(output / "SLOT_LIGHT_PAIRED_LEAF_PAIR_DISTRIBUTION.tsv", [
            "side", "leaf0_u32_hex", "leaf1_u32_hex", "leaf0_float32", "leaf1_float32", "record_rows", "paired_equal_bits", "contains_75_or_150",
        ], pair_distribution)
        write_tsv(output / "SLOT_LIGHT_STRUCTURAL_NORMALIZATION_INVARIANTS.tsv", [
            "field", "source_value", "target_value", "source_anchor", "target_anchor", "anchor_shift", "source_absolute_field_offset",
            "target_absolute_field_offset", "source_normalized_value", "target_normalized_value", "normalization", "invariant_exact", "classification",
        ], normalization_rows)
        write_tsv(output / "SLOT_LIGHT_CONTINUING_RECORD_LEAF_DECISION.tsv", ["question", "answer", "classification"], decision_rows)
        write_tsv(output / "SLOT_LIGHT_CONTINUING_RECORD_TRANSITION_PARTITION_SKIPPED.tsv", ["scope", "relative_dword", "reason"], [])

        equal_pair_rows = sum(parse_bool(row["paired_equal_bits"]) for row in inventory)
        summary: dict[str, Any] = {
            "type": "br_quartet_restoration_reflector_slot_light_continuing_record_transition_partition_evidence_summary",
            "format_version": 1, "tool_version": TOOL_VERSION,
            "source_stage91_tool_version": "0.1.5", "source_stage96_tool_version": "0.1.10", "source_stage99_tool_version": "0.1.13",
            "status": "occurrence_identity_resolved_four_transitions_partitioned_two_numeric_leaves_remain_semantically_unresolved",
            "reference_record_rows": len(inventory), "reference_record_pair_signature_rows": len(pair_distribution),
            "paired_equal_record_rows": equal_pair_rows, "paired_75_or_150_occurrence_rows": len(interest),
            "paired_150_occurrence_rows": count_150, "paired_75_occurrence_rows": count_75,
            "neutral_stable_150_and_75_variants_confirmed": True,
            "continuing_transition_rows": len(partition_rows), "proven_exact_relocation_rows": 1,
            "bounded_trailer_propagation_rows": 1, "unresolved_paired_numeric_leaf_rows": 2,
            "candidate_target_occurrence_identity_resolved": True, "candidate_target_occurrence_identity": "second_target_75",
            "inserted_target_occurrence": "first_target_75", "technical_leaf_semantics_resolved": False,
            "trailer_dword104_exact_role_resolved": False, "brightness_semantics_confirmed": False,
            "censorship_semantics_confirmed": False, "prototype_candidate_rows": 0, "skipped_rows": 0,
            "parameters": {
                "continuing_comparison": CONTINUING_COMPARISON, "transition_relative_dwords": list(EXPECTED_TRANSITION_DWORDS),
                "record_leaf_relative_dwords": [0, 1], "block_leaf_relative_dwords": [27, 28],
                "reference_relative_dword": 37, "trailer_propagation_relative_dword": 104,
            },
            "policy": {
                "technical_leaf_semantics_inferred": False, "brightness_semantics_inferred": False,
                "censorship_semantics_inferred": False, "render_payload_written": False, "full_proprietary_payloads_exported": False,
                "pak_repacked": False, "core_registry_modified": False, "profile_activated": False,
                "installed_game_modified": False, "runtime_validation_inferred": False, "canary_track_modified": False,
            },
            "next_action": "Upload this report. Continue only with a read-only field-role/context audit of paired record leaves 0 and 1 across the 177-record family. Do not infer brightness/censorship or write G1E.",
        }
        (output / "SUMMARY.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        archive = report_root / REPORT_NAME if create_archive else None
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
        output, archive, summary = build_report(args.project_root.resolve(), create_archive=not args.no_report_archive)
    except Stage100Error as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print(f"Report directory: {output}")
    if archive:
        print(f"Report: {archive}")
    print(f"Continuing transitions: {summary['continuing_transition_rows']}")
    print(f"Unresolved paired numeric leaves: {summary['unresolved_paired_numeric_leaf_rows']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
