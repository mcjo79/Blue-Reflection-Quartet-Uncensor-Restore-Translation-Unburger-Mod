#!/usr/bin/env python3
"""Audit ordinal and section-table binding of the seven-value paired-float family.

Stage 101 established only the storage/layout class of record dwords 0 and 1:
bit-equal finite-float payload leaves.  This metadata-only stage correlates the
21 focal-template occurrences with their within-member ordinal, section
cardinality and the exact dominant table bindings already reported by stage 93.

The stage may determine whether the paired values are consistent with ordinal,
cardinality or table-slot fields.  It must not assign a domain meaning such as
brightness, intensity, distance, duration, angle, opacity or scale.  No G1E
write, prototype, profile, activation or runtime claim is allowed.
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
TOOL_VERSION = "0.1.16"
REPORT_NAME = "BR_quartet_restoration_reflector_slot_light_paired_leaf_ordinal_section_binding_evidence.tar.zst"
REPORT_DIR = "reflector_slot_light_paired_leaf_ordinal_section_binding_evidence"
STAGE101_DIR = "reflector_slot_light_paired_leaf_context_role_evidence"
STAGE101_ARCHIVE = "BR_quartet_restoration_reflector_slot_light_paired_leaf_context_role_evidence.tar.zst"
STAGE91_DIR = "reflector_slot_light_section_cardinality_record_role_evidence"
STAGE91_ARCHIVE = "BR_quartet_restoration_reflector_slot_light_section_cardinality_record_role_evidence.tar.zst"
STAGE93_DIR = "reflector_slot_light_section_table_record_binding_evidence"
STAGE93_ARCHIVE = "BR_quartet_restoration_reflector_slot_light_section_table_record_binding_evidence.tar.zst"

EXPECTED_FOCAL_ROWS = 21
EXPECTED_MEMBER_SIDE_ROWS = 8
EXPECTED_VALUES = ("1", "2", "30", "50", "75", "100", "150")
EXPECTED_EXACT_BINDINGS = 13
CANDIDATE_MEMBER = "e_pc02_w5_ringlight_01.g1e#0"
NEUTRAL_MEMBER = "e_cmn_pup_reflect_s.g1e#0"


class Stage102Error(RuntimeError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise Stage102Error(message)


def progress(message: str) -> None:
    print(f"[stage102] {message}", file=sys.stderr, flush=True)


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
        raise Stage102Error(f"invalid JSON {path}: {exc}") from exc
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


def validate_stage101(root: Path) -> dict[str, Any]:
    summary = load_json(root / "SUMMARY.json")
    require(summary.get("type") == "br_quartet_restoration_reflector_slot_light_paired_leaf_context_role_evidence_summary", "stage101 type mismatch")
    require(summary.get("tool_version") == "0.1.15", "stage101 tool version mismatch")
    require(summary.get("technical_leaf_storage_class") == "paired_equal_finite_float_payload_leaves", "stage101 storage class mismatch")
    require(parse_bool(summary.get("technical_leaf_storage_class_resolved")), "stage101 storage class unresolved")
    require(not parse_bool(summary.get("technical_leaf_domain_semantics_resolved")), "stage101 unexpectedly resolved domain semantics")
    require(parse_int(summary.get("focal_context_record_rows"), -1) == EXPECTED_FOCAL_ROWS, "stage101 focal row count mismatch")
    require(tuple(summary.get("focal_context_values", [])) == EXPECTED_VALUES, "stage101 value domain mismatch")
    require(parse_int(summary.get("skipped_rows"), -1) == 0, "stage101 contains skipped rows")
    return summary


def validate_stage91(root: Path) -> dict[str, Any]:
    summary = load_json(root / "SUMMARY.json")
    require(summary.get("type") == "br_quartet_restoration_reflector_slot_light_section_cardinality_record_role_evidence_summary", "stage91 type mismatch")
    require(summary.get("tool_version") == "0.1.5", "stage91 tool version mismatch")
    require(parse_int(summary.get("section_member_side_rows"), -1) == 8, "stage91 member-side count mismatch")
    require(parse_int(summary.get("skipped_rows"), -1) == 0, "stage91 contains skipped rows")
    return summary


def validate_stage93(root: Path) -> dict[str, Any]:
    summary = load_json(root / "SUMMARY.json")
    require(summary.get("type") == "br_quartet_restoration_reflector_slot_light_section_table_record_binding_evidence_summary", "stage93 type mismatch")
    require(summary.get("tool_version") == "0.1.7", "stage93 tool version mismatch")
    require(parse_int(summary.get("dominant_record_relative_binding_rows"), -1) == EXPECTED_EXACT_BINDINGS, "stage93 dominant binding count mismatch")
    require(parse_bool(summary.get("target_table_binding_bulk_reencoding_supported")), "stage93 bulk binding conclusion missing")
    require(not parse_bool(summary.get("technical_leaf_semantics_resolved")), "stage93 unexpectedly resolved leaf semantics")
    require(parse_int(summary.get("skipped_rows"), -1) == 0, "stage93 contains skipped rows")
    return summary


def build_report(project_root: Path, *, create_archive: bool = True, report_root: Path | None = None) -> tuple[Path, Path | None, dict[str, Any]]:
    report_root = report_root or project_root / ".local/reports/quartet_restoration"
    progress("validating stage-91, stage-93 and stage-101 metadata")
    with tempfile.TemporaryDirectory(prefix="br-stage102-") as temporary_name:
        temporary = Path(temporary_name)
        stage101 = locate(report_root, STAGE101_DIR, STAGE101_ARCHIVE, temporary / "stage101")
        stage91 = locate(report_root, STAGE91_DIR, STAGE91_ARCHIVE, temporary / "stage91")
        stage93 = locate(report_root, STAGE93_DIR, STAGE93_ARCHIVE, temporary / "stage93")
        validate_stage101(stage101)
        validate_stage91(stage91)
        validate_stage93(stage93)

        focal = read_tsv(stage101 / "SLOT_LIGHT_FOCAL_EQUAL_FLOAT_FAMILY.tsv")
        require(len(focal) == EXPECTED_FOCAL_ROWS, f"expected {EXPECTED_FOCAL_ROWS} focal rows, found {len(focal)}")
        cardinality_rows = read_tsv(stage91 / "SLOT_LIGHT_SECTION_CARDINALITY.tsv")
        cardinality_lookup: dict[tuple[str, str], int] = {}
        for row in cardinality_rows:
            key = (row.get("member_key", "").casefold(), "source")
            cardinality_lookup[key] = parse_int(row.get("source_count"), -1)
            cardinality_lookup[(row.get("member_key", "").casefold(), "target")] = parse_int(row.get("target_count"), -1)
        require(len(cardinality_lookup) == EXPECTED_MEMBER_SIDE_ROWS, "section cardinality lookup mismatch")

        binding_rows = read_tsv(stage93 / "SLOT_LIGHT_SECTION_TABLE_RECORD_BINDING_CANDIDATES.tsv")
        exact_bindings = [
            row for row in binding_rows
            if parse_bool(row.get("exact_dominant_binding")) and parse_bool(row.get("best_is_focal_family"))
        ]
        require(len(exact_bindings) == EXPECTED_EXACT_BINDINGS, f"expected {EXPECTED_EXACT_BINDINGS} exact focal bindings, found {len(exact_bindings)}")
        binding_lookup: dict[tuple[str, str, int], dict[str, str]] = {}
        for row in exact_bindings:
            key = (row.get("member_key", "").casefold(), row.get("side", ""), parse_int(row.get("best_record_start"), -1))
            require(key not in binding_lookup, f"duplicate exact binding for {key}")
            binding_lookup[key] = row

        progress("assigning within-member ordinals and section bindings")
        grouped: dict[tuple[str, str], list[dict[str, str]]] = defaultdict(list)
        for row in focal:
            grouped[(row.get("member_key", "").casefold(), row.get("side", ""))].append(row)
        require(len(grouped) == EXPECTED_MEMBER_SIDE_ROWS, f"expected {EXPECTED_MEMBER_SIDE_ROWS} focal member-side groups, found {len(grouped)}")

        ordinal_rows: list[dict[str, Any]] = []
        member_side_rows: list[dict[str, Any]] = []
        sequences: dict[tuple[str, str], list[dict[str, Any]]] = {}
        for key, rows in sorted(grouped.items()):
            rows = sorted(rows, key=lambda row: parse_int(row.get("record_start"), -1))
            sequences[key] = []
            section_count = cardinality_lookup[key]
            for ordinal, row in enumerate(rows):
                record_start = parse_int(row.get("record_start"), -1)
                binding = binding_lookup.get((key[0], key[1], record_start))
                item = {
                    "normalized_path": row.get("normalized_path", ""),
                    "member_key": row.get("member_key", ""),
                    "member_name": row.get("member_name", ""),
                    "side": row.get("side", ""),
                    "record_start": record_start,
                    "reference_offset": parse_int(row.get("reference_offset"), -1),
                    "normalized_endpoint": parse_int(row.get("normalized_endpoint"), -1),
                    "paired_float_value": row.get("leaf0_float32", ""),
                    "occurrence_role": row.get("occurrence_role", ""),
                    "focal_ordinal_zero_based": ordinal,
                    "focal_ordinal_one_based": ordinal + 1,
                    "focal_record_count": len(rows),
                    "section_count": section_count,
                    "focal_count_equals_section_count": len(rows) == section_count,
                    "exact_table_binding": binding is not None,
                    "table_index": parse_int(binding.get("table_index"), -1) if binding else "",
                    "entry_index": parse_int(binding.get("entry_index"), -1) if binding else "",
                    "binding_record_relative_dword": parse_int(binding.get("best_record_relative_dword"), 0) if binding else "",
                    "binding_role": binding.get("binding_classification", "") if binding else "unbound_by_dominant_relation",
                }
                ordinal_rows.append(item)
                sequences[key].append(item)
            member_side_rows.append({
                "member_key": rows[0].get("member_key", ""),
                "member_name": rows[0].get("member_name", ""),
                "side": key[1],
                "section_count": section_count,
                "focal_record_rows": len(rows),
                "focal_count_equals_section_count": len(rows) == section_count,
                "focal_value_sequence": " | ".join(row.get("leaf0_float32", "") for row in rows),
                "exact_binding_rows": sum(binding_lookup.get((key[0], key[1], parse_int(row.get("record_start"), -1))) is not None for row in rows),
                "bound_table_slots": " | ".join(
                    f"t{binding_lookup[(key[0], key[1], parse_int(row.get('record_start'), -1))]['table_index']}:e{binding_lookup[(key[0], key[1], parse_int(row.get('record_start'), -1))]['entry_index']}"
                    for row in rows if (key[0], key[1], parse_int(row.get("record_start"), -1)) in binding_lookup
                ),
                "classification": "full_focal_cardinality_coverage" if len(rows) == section_count else "partial_focal_template_coverage",
            })

        progress("auditing value-to-ordinal and value-to-table-slot consistency")
        by_value: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for row in ordinal_rows:
            by_value[str(row["paired_float_value"])].append(row)
        require(tuple(sorted(by_value, key=float)) == EXPECTED_VALUES, "unexpected reconstructed value domain")
        value_rows: list[dict[str, Any]] = []
        values_with_multiple_ordinals = 0
        values_with_multiple_table_slots = 0
        for value in sorted(by_value, key=float):
            rows = by_value[value]
            ordinals = sorted({int(row["focal_ordinal_zero_based"]) for row in rows})
            slots = sorted({(int(row["table_index"]), int(row["entry_index"])) for row in rows if row["exact_table_binding"]})
            if len(ordinals) > 1:
                values_with_multiple_ordinals += 1
            if len(slots) > 1:
                values_with_multiple_table_slots += 1
            value_rows.append({
                "paired_float_value": value,
                "occurrence_rows": len(rows),
                "member_rows": len({str(row["member_key"]).casefold() for row in rows}),
                "side_rows": len({str(row["side"]) for row in rows}),
                "ordinal_zero_based_values": " | ".join(map(str, ordinals)),
                "unique_ordinal_rows": len(ordinals),
                "exact_binding_rows": sum(bool(row["exact_table_binding"]) for row in rows),
                "exact_table_slots": " | ".join(f"t{table}:e{entry}" for table, entry in slots),
                "unique_table_slot_rows": len(slots),
                "value_is_consistent_unique_ordinal": len(ordinals) == 1,
                "value_is_consistent_unique_table_slot": bool(slots) and len(slots) == 1,
                "classification": "context_dependent_ordinal_or_slot" if len(ordinals) > 1 or len(slots) > 1 else "insufficient_or_single_position_evidence",
            })

        candidate_source = sequences[(CANDIDATE_MEMBER, "source")]
        candidate_target = sequences[(CANDIDATE_MEMBER, "target")]
        require([row["paired_float_value"] for row in candidate_source] == ["30", "150", "2"], "candidate source sequence mismatch")
        require([row["paired_float_value"] for row in candidate_target] == ["30", "75", "75", "2"], "candidate target sequence mismatch")
        role_lookup = {row["occurrence_role"]: row for row in candidate_source + candidate_target}
        required_roles = {
            "candidate_source_150", "candidate_first_target_75_inserted", "candidate_second_target_75_continuing"
        }
        require(required_roles <= set(role_lookup), "candidate role inventory incomplete")
        source30 = candidate_source[0]
        target30 = candidate_target[0]
        source150 = role_lookup["candidate_source_150"]
        target75 = role_lookup["candidate_second_target_75_continuing"]
        source2 = candidate_source[2]
        target2 = candidate_target[3]
        insertion_rows = [
            {"source_role": "stable_30", "source_value": "30", "source_ordinal": source30["focal_ordinal_zero_based"], "target_role": "stable_30", "target_value": "30", "target_ordinal": target30["focal_ordinal_zero_based"], "ordinal_shift": target30["focal_ordinal_zero_based"] - source30["focal_ordinal_zero_based"], "continuity_classification": "pre_insertion_stable"},
            {"source_role": "source_150", "source_value": "150", "source_ordinal": source150["focal_ordinal_zero_based"], "target_role": "second_target_75_continuing", "target_value": "75", "target_ordinal": target75["focal_ordinal_zero_based"], "ordinal_shift": target75["focal_ordinal_zero_based"] - source150["focal_ordinal_zero_based"], "continuity_classification": "post_insertion_continuing"},
            {"source_role": "stable_2", "source_value": "2", "source_ordinal": source2["focal_ordinal_zero_based"], "target_role": "stable_2", "target_value": "2", "target_ordinal": target2["focal_ordinal_zero_based"], "ordinal_shift": target2["focal_ordinal_zero_based"] - source2["focal_ordinal_zero_based"], "continuity_classification": "post_insertion_stable"},
            {"source_role": "none", "source_value": "", "source_ordinal": "", "target_role": "first_target_75_inserted", "target_value": "75", "target_ordinal": role_lookup["candidate_first_target_75_inserted"]["focal_ordinal_zero_based"], "ordinal_shift": "inserted", "continuity_classification": "inserted_occurrence"},
        ]
        require([row["ordinal_shift"] for row in insertion_rows[:3]] == [0, 1, 1], "candidate insertion ordinal continuity mismatch")

        exact_cardinality_groups = sum(parse_bool(row["focal_count_equals_section_count"]) for row in member_side_rows)
        partial_cardinality_groups = len(member_side_rows) - exact_cardinality_groups
        target_candidate_bindings = [row for row in ordinal_rows if str(row["member_key"]).casefold() == CANDIDATE_MEMBER and row["side"] == "target" and row["exact_table_binding"]]
        source_candidate_bindings = [row for row in ordinal_rows if str(row["member_key"]).casefold() == CANDIDATE_MEMBER and row["side"] == "source" and row["exact_table_binding"]]
        neutral_bindings = [row for row in ordinal_rows if str(row["member_key"]).casefold() == NEUTRAL_MEMBER and row["exact_table_binding"]]
        require(len(target_candidate_bindings) == 3, "candidate target binding count mismatch")
        require(len(source_candidate_bindings) == 0, "candidate source unexpectedly has dominant focal bindings")
        require(len(neutral_bindings) == 10, "neutral binding count mismatch")
        require([(row["table_index"], row["entry_index"], row["paired_float_value"]) for row in target_candidate_bindings] == [(3, 0, "30"), (3, 1, "75"), (3, 2, "75")], "candidate target table sequence mismatch")

        decision_rows = [
            {"question": "does section count universally equal focal-template record count", "answer": False, "classification": f"exact_{exact_cardinality_groups}_of_{len(member_side_rows)}_member_sides_partial_{partial_cardinality_groups}"},
            {"question": "does paired value encode one stable within-member ordinal", "answer": False, "classification": f"{values_with_multiple_ordinals}_of_7_values_occupy_multiple_ordinals"},
            {"question": "does paired value encode one stable section-table slot", "answer": False, "classification": f"{values_with_multiple_table_slots}_values_have_multiple_exact_slots_and_many_occurrences_are_unbound"},
            {"question": "does candidate insertion preserve ordinal continuity of continuing records", "answer": True, "classification": "stable_30_shift_0_continuing_150_to_75_shift_1_stable_2_shift_1"},
            {"question": "do target table-3 entries distinguish inserted and continuing 75 occurrences", "answer": True, "classification": "entry1_inserted_first_75_entry2_continuing_second_75"},
            {"question": "is target table-3 binding a value-specific semantic map", "answer": False, "classification": "same_bulk_binding_also_covers_stable_30_and_has_no_source_counterpart"},
            {"question": "what bounded role is supported for paired leaves", "answer": "context-dependent payload values inside an occurrence-ordered record family", "classification": "not_section_ordinal_not_cardinality_not_unique_table_slot"},
            {"question": "is technical value-domain meaning resolved", "answer": False, "classification": "brightness_intensity_distance_duration_angle_opacity_scale_and_other_meanings_unresolved"},
            {"question": "does this authorize G1E write or prototype", "answer": False, "classification": "evidence_only_no_write"},
        ]

        output = report_root / REPORT_DIR
        if output.exists():
            import shutil
            shutil.rmtree(output)
        output.mkdir(parents=True)
        write_tsv(output / "SLOT_LIGHT_FOCAL_ORDINAL_INVENTORY.tsv", [
            "normalized_path", "member_key", "member_name", "side", "record_start", "reference_offset", "normalized_endpoint",
            "paired_float_value", "occurrence_role", "focal_ordinal_zero_based", "focal_ordinal_one_based", "focal_record_count",
            "section_count", "focal_count_equals_section_count", "exact_table_binding", "table_index", "entry_index",
            "binding_record_relative_dword", "binding_role",
        ], ordinal_rows)
        write_tsv(output / "SLOT_LIGHT_FOCAL_MEMBER_SIDE_CARDINALITY.tsv", [
            "member_key", "member_name", "side", "section_count", "focal_record_rows", "focal_count_equals_section_count",
            "focal_value_sequence", "exact_binding_rows", "bound_table_slots", "classification",
        ], member_side_rows)
        write_tsv(output / "SLOT_LIGHT_FOCAL_VALUE_ORDINAL_DISTRIBUTION.tsv", [
            "paired_float_value", "occurrence_rows", "member_rows", "side_rows", "ordinal_zero_based_values", "unique_ordinal_rows",
            "exact_binding_rows", "exact_table_slots", "unique_table_slot_rows", "value_is_consistent_unique_ordinal",
            "value_is_consistent_unique_table_slot", "classification",
        ], value_rows)
        write_tsv(output / "SLOT_LIGHT_FOCAL_SECTION_TABLE_BINDINGS.tsv", [
            "normalized_path", "member_key", "member_name", "side", "record_start", "paired_float_value", "occurrence_role",
            "focal_ordinal_zero_based", "section_count", "table_index", "entry_index", "binding_record_relative_dword", "binding_role",
        ], [row for row in ordinal_rows if row["exact_table_binding"]])
        write_tsv(output / "SLOT_LIGHT_CANDIDATE_INSERTION_ORDINAL_CONTINUITY.tsv", [
            "source_role", "source_value", "source_ordinal", "target_role", "target_value", "target_ordinal", "ordinal_shift", "continuity_classification",
        ], insertion_rows)
        write_tsv(output / "SLOT_LIGHT_PAIRED_LEAF_ORDINAL_SECTION_ROLE_DECISION.tsv", ["question", "answer", "classification"], decision_rows)
        write_tsv(output / "SLOT_LIGHT_PAIRED_LEAF_ORDINAL_SECTION_BINDING_SKIPPED.tsv", ["scope", "member_key", "side", "record_start", "reason"], [])

        summary: dict[str, Any] = {
            "type": "br_quartet_restoration_reflector_slot_light_paired_leaf_ordinal_section_binding_evidence_summary",
            "format_version": 1,
            "tool_version": TOOL_VERSION,
            "source_stage101_tool_version": "0.1.15",
            "source_stage91_tool_version": "0.1.5",
            "source_stage93_tool_version": "0.1.7",
            "status": "paired_float_values_are_context_dependent_payloads_not_section_ordinals_cardinality_or_unique_table_slots_domain_semantics_unresolved",
            "focal_record_rows": len(ordinal_rows),
            "focal_member_side_rows": len(member_side_rows),
            "full_focal_cardinality_member_side_rows": exact_cardinality_groups,
            "partial_focal_cardinality_member_side_rows": partial_cardinality_groups,
            "focal_unique_value_rows": len(value_rows),
            "values_with_multiple_ordinal_rows": values_with_multiple_ordinals,
            "values_with_multiple_table_slot_rows": values_with_multiple_table_slots,
            "exact_focal_table_binding_rows": sum(bool(row["exact_table_binding"]) for row in ordinal_rows),
            "candidate_source_exact_binding_rows": len(source_candidate_bindings),
            "candidate_target_exact_binding_rows": len(target_candidate_bindings),
            "neutral_exact_binding_rows": len(neutral_bindings),
            "candidate_source_sequence": [row["paired_float_value"] for row in candidate_source],
            "candidate_target_sequence": [row["paired_float_value"] for row in candidate_target],
            "candidate_target_occurrence_identity_resolved": True,
            "candidate_target_occurrence_identity": "second_target_75",
            "inserted_target_occurrence": "first_target_75",
            "candidate_post_insertion_ordinal_shift": 1,
            "paired_leaf_is_section_ordinal": False,
            "paired_leaf_is_section_cardinality": False,
            "paired_leaf_is_unique_table_slot_identifier": False,
            "technical_leaf_storage_class": "paired_equal_finite_float_payload_leaves",
            "technical_leaf_domain_semantics_resolved": False,
            "brightness_semantics_confirmed": False,
            "censorship_semantics_confirmed": False,
            "prototype_candidate_rows": 0,
            "skipped_rows": 0,
            "parameters": {
                "ordinal_scope": "focal shared-template records sorted by record_start within member and side",
                "exact_binding_source": "stage93 dominant record_start_minus_108 relation",
                "candidate_continuity_source": "stage99-resolved occurrence identity carried by stage101 roles",
                "expected_values": list(EXPECTED_VALUES),
            },
            "policy": {
                "technical_leaf_domain_semantics_inferred": False,
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
            "next_action": "Upload this report. Continue only with a read-only sibling callsite/member-role correlation audit for the occurrence-ordered equal-float family. Do not infer brightness/intensity and do not write G1E.",
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
    except Stage102Error as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print(f"Report directory: {output}")
    if archive:
        print(f"Report: {archive}")
    print(f"Focal records: {summary['focal_record_rows']}")
    print(f"Exact focal table bindings: {summary['exact_focal_table_binding_rows']}")
    print(f"Candidate sequence: {' -> '.join(summary['candidate_source_sequence'])} / {' -> '.join(summary['candidate_target_sequence'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
