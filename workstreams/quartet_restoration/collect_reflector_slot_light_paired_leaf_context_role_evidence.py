#!/usr/bin/env python3
"""Classify the paired dword-0/dword-1 leaves without assigning semantics.

Stage 100 partitioned the continuing source-150 -> second-target-75 block into
four transitions and left only record dwords 0 and 1 semantically unresolved.
This metadata-only stage reconstructs all 177 stage-91 reference records,
groups them by the exact non-leaf record body (dwords 2..9), normalizes the
section reference at dword 10 to its absolute endpoint, and audits the value
domain of the focal shared template.

The strongest permitted conclusion is a storage/layout classification:
dwords 0 and 1 are bit-equal finite-float payload leaves inside a shared
11-dword record template.  Their domain meaning (brightness, distance,
duration, intensity, angle, opacity, or anything else) remains unresolved.
No G1E/G1EM write, prototype, profile, activation or runtime claim is allowed.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import struct
import subprocess
import sys
import tempfile
from collections import Counter, defaultdict
from pathlib import Path, PurePosixPath
from typing import Any, Iterable, Mapping, Sequence

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT_DEFAULT = SCRIPT_DIR.parent.parent

TOOL_VERSION = "0.1.15"
REPORT_NAME = "BR_quartet_restoration_reflector_slot_light_paired_leaf_context_role_evidence.tar.zst"
REPORT_DIR = "reflector_slot_light_paired_leaf_context_role_evidence"
STAGE91_DIR = "reflector_slot_light_section_cardinality_record_role_evidence"
STAGE91_ARCHIVE = "BR_quartet_restoration_reflector_slot_light_section_cardinality_record_role_evidence.tar.zst"
STAGE100_DIR = "reflector_slot_light_continuing_record_transition_partition_evidence"
STAGE100_ARCHIVE = "BR_quartet_restoration_reflector_slot_light_continuing_record_transition_partition_evidence.tar.zst"

EXPECTED_RECORD_ROWS = 177
EXPECTED_RECORD_DWORD_ROWS = 1947
EXPECTED_PAIRED_EQUAL_ROWS = 53
EXPECTED_INTEREST_ROWS = 7
EXPECTED_FOCAL_CONTEXT_ROWS = 21
EXPECTED_FOCAL_MEMBER_ROWS = 4
EXPECTED_FOCAL_ENDPOINT_ROWS = 2
EXPECTED_FOCAL_VALUES = (1.0, 2.0, 30.0, 50.0, 75.0, 100.0, 150.0)
CANDIDATE_MEMBER = "e_pc02_w5_ringlight_01.g1e#0"
NEUTRAL_MEMBER = "e_cmn_pup_reflect_s.g1e#0"


class Stage101Error(RuntimeError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise Stage101Error(message)


def progress(message: str) -> None:
    print(f"[stage101] {message}", file=sys.stderr, flush=True)


def parse_int(value: Any, default: int = 0) -> int:
    try:
        text = str(value).strip()
        return int(text, 16) if text.casefold().startswith("0x") else int(text)
    except (TypeError, ValueError):
        return default


def parse_bool(value: Any) -> bool:
    return str(value).strip().casefold() in {"1", "true", "yes", "y"}


def parse_float(value: Any) -> float | None:
    try:
        result = float(str(value).strip())
    except (TypeError, ValueError):
        return None
    return result if result == result and abs(result) != float("inf") else None


def format_float(value: float) -> str:
    return str(int(value)) if value.is_integer() else format(value, ".9g")


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
        raise Stage101Error(f"invalid JSON {path}: {exc}") from exc
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


def validate_stage100(root: Path) -> dict[str, Any]:
    summary = load_json(root / "SUMMARY.json")
    require(summary.get("type") == "br_quartet_restoration_reflector_slot_light_continuing_record_transition_partition_evidence_summary", "stage100 type mismatch")
    require(summary.get("tool_version") == "0.1.14", "stage100 tool version mismatch")
    require(summary.get("status") == "occurrence_identity_resolved_four_transitions_partitioned_two_numeric_leaves_remain_semantically_unresolved", "stage100 status mismatch")
    require(parse_int(summary.get("reference_record_rows"), -1) == EXPECTED_RECORD_ROWS, "stage100 record count mismatch")
    require(parse_int(summary.get("paired_equal_record_rows"), -1) == EXPECTED_PAIRED_EQUAL_ROWS, "stage100 equal-pair count mismatch")
    require(parse_int(summary.get("paired_75_or_150_occurrence_rows"), -1) == EXPECTED_INTEREST_ROWS, "stage100 focal variant count mismatch")
    require(parse_int(summary.get("unresolved_paired_numeric_leaf_rows"), -1) == 2, "stage100 unresolved leaf count mismatch")
    require(parse_bool(summary.get("candidate_target_occurrence_identity_resolved")), "stage100 occurrence identity unresolved")
    require(summary.get("candidate_target_occurrence_identity") == "second_target_75", "stage100 continuing target mismatch")
    require(summary.get("inserted_target_occurrence") == "first_target_75", "stage100 inserted target mismatch")
    require(not parse_bool(summary.get("technical_leaf_semantics_resolved")), "stage100 unexpectedly resolved leaf semantics")
    require(parse_int(summary.get("prototype_candidate_rows"), -1) == 0, "stage100 unexpectedly contains prototype candidates")
    require(parse_int(summary.get("skipped_rows"), -1) == 0, "stage100 contains skipped rows")
    return summary


def hash_words(words: Sequence[int]) -> str:
    return hashlib.sha256(b"".join(struct.pack("<I", word & 0xFFFFFFFF) for word in words)).hexdigest()


def reconstruct_records(dword_rows: list[dict[str, str]]) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str, str, str, int, int], dict[int, dict[str, str]]] = defaultdict(dict)
    for row in dword_rows:
        key = (
            row.get("normalized_path", ""), row.get("member_key", ""), row.get("member_name", ""), row.get("side", ""),
            parse_int(row.get("reference_offset"), -1), parse_int(row.get("record_start"), -1),
        )
        relative = parse_int(row.get("relative_dword"), -1)
        require(relative not in grouped[key], f"duplicate record dword {relative}: {key}")
        grouped[key][relative] = row
    require(len(grouped) == EXPECTED_RECORD_ROWS, f"expected {EXPECTED_RECORD_ROWS} records, found {len(grouped)}")

    records: list[dict[str, Any]] = []
    for key, dwords in sorted(grouped.items()):
        require(set(dwords) == set(range(11)), f"record must contain exactly dwords 0..10: {key}")
        values = [parse_int(dwords[index].get("u32_hex"), -1) for index in range(11)]
        require(all(value >= 0 for value in values), f"invalid dword value: {key}")
        floats = [parse_float(dwords[index].get("float32")) for index in range(11)]
        statuses = [dwords[index].get("float_status", "") for index in range(11)]
        reference_i32 = parse_int(dwords[10].get("i32"), 0)
        if "i32" not in dwords[10] or not str(dwords[10].get("i32", "")).strip():
            raw = values[10]
            reference_i32 = raw - (1 << 32) if raw & 0x80000000 else raw
        endpoint = key[4] + reference_i32
        context_words = values[2:10]
        context_sha = hash_words(context_words)
        context_endpoint_sha = hashlib.sha256(
            b"".join(struct.pack("<I", word) for word in context_words) + struct.pack("<q", endpoint)
        ).hexdigest()
        records.append({
            "normalized_path": key[0], "member_key": key[1], "member_name": key[2], "side": key[3],
            "reference_offset": key[4], "record_start": key[5], "values": values, "floats": floats, "statuses": statuses,
            "leaf0_u32_hex": f"0x{values[0]:08x}", "leaf1_u32_hex": f"0x{values[1]:08x}",
            "leaf0_float32": "" if floats[0] is None else format_float(floats[0]),
            "leaf1_float32": "" if floats[1] is None else format_float(floats[1]),
            "leaf0_float_status": statuses[0], "leaf1_float_status": statuses[1],
            "paired_equal_bits": values[0] == values[1],
            "paired_finite_floats": floats[0] is not None and floats[1] is not None,
            "non_leaf_context_sha256": context_sha, "normalized_endpoint": endpoint,
            "context_endpoint_sha256": context_endpoint_sha,
        })
    return records


def cross_check_stage100(records: list[dict[str, Any]], stage100_root: Path) -> list[dict[str, str]]:
    interest = read_tsv(stage100_root / "SLOT_LIGHT_PAIRED_LEAF_OCCURRENCE_INVENTORY.tsv")
    require(len(interest) == EXPECTED_INTEREST_ROWS, f"expected {EXPECTED_INTEREST_ROWS} stage100 focal rows, found {len(interest)}")
    lookup = {
        (row["normalized_path"], row["member_key"], row["side"], str(row["reference_offset"]), str(row["record_start"])): row
        for row in records
    }
    for row in interest:
        key = (row.get("normalized_path", ""), row.get("member_key", ""), row.get("side", ""), row.get("reference_offset", ""), row.get("record_start", ""))
        require(key in lookup, f"stage100 focal occurrence missing from stage91: {key}")
        actual = lookup[key]
        require(actual["leaf0_u32_hex"] == row.get("leaf0_u32_hex"), f"stage100 leaf0 mismatch: {key}")
        require(actual["leaf1_u32_hex"] == row.get("leaf1_u32_hex"), f"stage100 leaf1 mismatch: {key}")
    return interest


def occurrence_role(record: Mapping[str, Any]) -> str:
    key = str(record.get("member_key", "")).casefold()
    side = str(record.get("side", ""))
    start = parse_int(record.get("record_start"), -1)
    leaf = (record.get("leaf0_float32", ""), record.get("leaf1_float32", ""))
    if key == CANDIDATE_MEMBER:
        if side == "source" and leaf == ("150", "150"):
            return "candidate_source_150"
        if side == "target" and leaf == ("75", "75") and start == 21136:
            return "candidate_first_target_75_inserted"
        if side == "target" and leaf == ("75", "75") and start == 21744:
            return "candidate_second_target_75_continuing"
    if key == NEUTRAL_MEMBER and leaf == ("150", "150"):
        return f"neutral_stable_150_{side}"
    if key == NEUTRAL_MEMBER and leaf == ("75", "75"):
        return f"neutral_stable_75_{side}"
    return "other_focal_template_occurrence"


def build_report(project_root: Path, *, create_archive: bool = True, report_root: Path | None = None) -> tuple[Path, Path | None, dict[str, Any]]:
    report_root = report_root or project_root / ".local/reports/quartet_restoration"
    progress("validating stage-91 and stage-100 reports")
    with tempfile.TemporaryDirectory(prefix="br-stage101-") as temporary_name:
        temporary = Path(temporary_name)
        stage91 = locate(report_root, STAGE91_DIR, STAGE91_ARCHIVE, temporary / "stage91")
        stage100 = locate(report_root, STAGE100_DIR, STAGE100_ARCHIVE, temporary / "stage100")
        validate_stage91(stage91)
        validate_stage100(stage100)

        progress("reconstructing 177 reference records")
        records = reconstruct_records(read_tsv(stage91 / "SLOT_LIGHT_REFERENCE_RECORD_DWORDS.tsv"))
        cross_check_stage100(records, stage100)
        require(sum(bool(row["paired_equal_bits"]) for row in records) == EXPECTED_PAIRED_EQUAL_ROWS, "reconstructed equal-pair count mismatch")

        candidate_source = [
            row for row in records
            if str(row["member_key"]).casefold() == CANDIDATE_MEMBER and row["side"] == "source"
            and row["leaf0_float32"] == "150" and row["leaf1_float32"] == "150"
        ]
        require(len(candidate_source) == 1, f"expected one candidate source 150 record, found {len(candidate_source)}")
        focal_context_sha = candidate_source[0]["non_leaf_context_sha256"]
        focal_records = [row for row in records if row["non_leaf_context_sha256"] == focal_context_sha]
        require(len(focal_records) == EXPECTED_FOCAL_CONTEXT_ROWS, f"expected {EXPECTED_FOCAL_CONTEXT_ROWS} focal context rows, found {len(focal_records)}")
        require(len({str(row["member_key"]).casefold() for row in focal_records}) == EXPECTED_FOCAL_MEMBER_ROWS, "focal member count mismatch")
        require(len({row["normalized_endpoint"] for row in focal_records}) == EXPECTED_FOCAL_ENDPOINT_ROWS, "focal endpoint group count mismatch")
        require(all(row["paired_equal_bits"] for row in focal_records), "focal template contains unequal paired leaves")
        require(all(row["paired_finite_floats"] for row in focal_records), "focal template contains non-finite paired leaves")
        focal_values = sorted({float(row["leaf0_float32"]) for row in focal_records})
        require(tuple(focal_values) == EXPECTED_FOCAL_VALUES, f"unexpected focal value domain: {focal_values}")

        progress("grouping exact non-leaf contexts and value domains")
        context_groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for row in records:
            context_groups[row["non_leaf_context_sha256"]].append(row)

        inventory_rows: list[dict[str, Any]] = []
        for row in records:
            inventory_rows.append({
                **{field: row[field] for field in (
                    "normalized_path", "member_key", "member_name", "side", "reference_offset", "record_start",
                    "leaf0_u32_hex", "leaf1_u32_hex", "leaf0_float32", "leaf1_float32", "leaf0_float_status", "leaf1_float_status",
                    "paired_equal_bits", "paired_finite_floats", "non_leaf_context_sha256", "normalized_endpoint", "context_endpoint_sha256",
                )},
                "is_focal_context": row["non_leaf_context_sha256"] == focal_context_sha,
                "occurrence_role": occurrence_role(row) if row["non_leaf_context_sha256"] == focal_context_sha else "outside_focal_context",
            })

        group_rows: list[dict[str, Any]] = []
        multi_leaf_groups = 0
        for context_sha, group in sorted(context_groups.items()):
            pairs = Counter((row["leaf0_u32_hex"], row["leaf1_u32_hex"], row["leaf0_float32"], row["leaf1_float32"]) for row in group)
            if len(pairs) > 1:
                multi_leaf_groups += 1
            pair_text = ";".join(f"{leftf}/{rightf}:{count}" for (_, _, leftf, rightf), count in sorted(pairs.items()))
            group_rows.append({
                "non_leaf_context_sha256": context_sha,
                "record_rows": len(group),
                "member_rows": len({str(row["member_key"]).casefold() for row in group}),
                "side_rows": len({row["side"] for row in group}),
                "endpoint_rows": len({row["normalized_endpoint"] for row in group}),
                "unique_leaf_pair_rows": len(pairs),
                "paired_equal_rows": sum(bool(row["paired_equal_bits"]) for row in group),
                "paired_finite_float_rows": sum(bool(row["paired_finite_floats"]) for row in group),
                "leaf_pair_distribution": pair_text,
                "is_focal_context": context_sha == focal_context_sha,
                "classification": "shared_equal_float_variant_template" if context_sha == focal_context_sha else (
                    "multi_leaf_non_focal_context" if len(pairs) > 1 else "single_leaf_pair_context"
                ),
            })

        focal_inventory_rows: list[dict[str, Any]] = []
        for row in sorted(focal_records, key=lambda item: (item["normalized_path"], item["member_key"], item["side"], item["record_start"])):
            focal_inventory_rows.append({
                "normalized_path": row["normalized_path"], "member_key": row["member_key"], "member_name": row["member_name"],
                "side": row["side"], "record_start": row["record_start"], "reference_offset": row["reference_offset"],
                "normalized_endpoint": row["normalized_endpoint"], "leaf0_float32": row["leaf0_float32"], "leaf1_float32": row["leaf1_float32"],
                "leaf0_u32_hex": row["leaf0_u32_hex"], "leaf1_u32_hex": row["leaf1_u32_hex"],
                "paired_equal_bits": row["paired_equal_bits"], "paired_finite_floats": row["paired_finite_floats"],
                "occurrence_role": occurrence_role(row),
            })

        value_rows: list[dict[str, Any]] = []
        for value in focal_values:
            matching = [row for row in focal_records if float(row["leaf0_float32"]) == value]
            value_rows.append({
                "paired_float_value": format_float(value),
                "paired_u32_hex": matching[0]["leaf0_u32_hex"],
                "record_rows": len(matching),
                "source_rows": sum(row["side"] == "source" for row in matching),
                "target_rows": sum(row["side"] == "target" for row in matching),
                "member_rows": len({str(row["member_key"]).casefold() for row in matching}),
                "endpoint_rows": len({row["normalized_endpoint"] for row in matching}),
                "candidate_rows": sum(str(row["member_key"]).casefold() == CANDIDATE_MEMBER for row in matching),
                "neutral_rows": sum(str(row["member_key"]).casefold() != CANDIDATE_MEMBER for row in matching),
                "classification": "stable_neutral_and_candidate_variant" if value in {75.0, 150.0} else "stable_family_value",
            })

        decision_rows = [
            {"question": "are record leaves 0 and 1 bit-equal throughout the focal shared template", "answer": True, "classification": "21_of_21_exact_bit_pairs"},
            {"question": "are both focal leaves finite IEEE-754 values", "answer": True, "classification": "21_of_21_finite_float_storage"},
            {"question": "does one exact non-leaf template carry multiple paired values", "answer": True, "classification": "seven_value_domain_same_dwords_2_to_9"},
            {"question": "what is the bounded technical storage classification", "answer": "paired_equal_finite_float_payload_leaves", "classification": "layout_storage_class_resolved"},
            {"question": "do 150/150 and 75/75 coexist stably outside the focal transition", "answer": True, "classification": "neutral_source_and_target_cohabitation"},
            {"question": "is 150 to 75 a global format migration", "answer": False, "classification": "values_are_coexisting_record_variants"},
            {"question": "is the domain meaning of the pair resolved", "answer": False, "classification": "brightness_distance_duration_intensity_angle_and_other_meanings_unresolved"},
            {"question": "does this authorize G1E write or prototype", "answer": False, "classification": "evidence_only_no_write"},
        ]

        output = report_root / REPORT_DIR
        if output.exists():
            import shutil
            shutil.rmtree(output)
        output.mkdir(parents=True)
        write_tsv(output / "SLOT_LIGHT_PAIRED_LEAF_CONTEXT_INVENTORY.tsv", [
            "normalized_path", "member_key", "member_name", "side", "reference_offset", "record_start",
            "leaf0_u32_hex", "leaf1_u32_hex", "leaf0_float32", "leaf1_float32", "leaf0_float_status", "leaf1_float_status",
            "paired_equal_bits", "paired_finite_floats", "non_leaf_context_sha256", "normalized_endpoint", "context_endpoint_sha256",
            "is_focal_context", "occurrence_role",
        ], inventory_rows)
        write_tsv(output / "SLOT_LIGHT_PAIRED_LEAF_CONTEXT_GROUPS.tsv", [
            "non_leaf_context_sha256", "record_rows", "member_rows", "side_rows", "endpoint_rows", "unique_leaf_pair_rows",
            "paired_equal_rows", "paired_finite_float_rows", "leaf_pair_distribution", "is_focal_context", "classification",
        ], group_rows)
        write_tsv(output / "SLOT_LIGHT_FOCAL_EQUAL_FLOAT_FAMILY.tsv", [
            "normalized_path", "member_key", "member_name", "side", "record_start", "reference_offset", "normalized_endpoint",
            "leaf0_float32", "leaf1_float32", "leaf0_u32_hex", "leaf1_u32_hex", "paired_equal_bits", "paired_finite_floats", "occurrence_role",
        ], focal_inventory_rows)
        write_tsv(output / "SLOT_LIGHT_FOCAL_EQUAL_FLOAT_VALUE_DOMAIN.tsv", [
            "paired_float_value", "paired_u32_hex", "record_rows", "source_rows", "target_rows", "member_rows", "endpoint_rows",
            "candidate_rows", "neutral_rows", "classification",
        ], value_rows)
        write_tsv(output / "SLOT_LIGHT_PAIRED_LEAF_ROLE_DECISION.tsv", ["question", "answer", "classification"], decision_rows)
        write_tsv(output / "SLOT_LIGHT_PAIRED_LEAF_CONTEXT_ROLE_SKIPPED.tsv", ["scope", "member_key", "side", "record_start", "reason"], [])

        summary: dict[str, Any] = {
            "type": "br_quartet_restoration_reflector_slot_light_paired_leaf_context_role_evidence_summary",
            "format_version": 1,
            "tool_version": TOOL_VERSION,
            "source_stage91_tool_version": "0.1.5",
            "source_stage100_tool_version": "0.1.14",
            "status": "paired_leaves_classified_as_equal_finite_float_payload_slots_domain_semantics_unresolved",
            "reference_record_rows": len(records),
            "record_context_group_rows": len(context_groups),
            "multi_leaf_context_group_rows": multi_leaf_groups,
            "paired_equal_record_rows": sum(bool(row["paired_equal_bits"]) for row in records),
            "focal_context_record_rows": len(focal_records),
            "focal_context_member_rows": len({str(row["member_key"]).casefold() for row in focal_records}),
            "focal_context_endpoint_rows": len({row["normalized_endpoint"] for row in focal_records}),
            "focal_context_unique_value_rows": len(focal_values),
            "focal_context_equal_pair_rows": sum(bool(row["paired_equal_bits"]) for row in focal_records),
            "focal_context_finite_float_rows": sum(bool(row["paired_finite_floats"]) for row in focal_records),
            "focal_context_values": [format_float(value) for value in focal_values],
            "candidate_target_occurrence_identity_resolved": True,
            "candidate_target_occurrence_identity": "second_target_75",
            "inserted_target_occurrence": "first_target_75",
            "technical_leaf_storage_class_resolved": True,
            "technical_leaf_storage_class": "paired_equal_finite_float_payload_leaves",
            "technical_leaf_domain_semantics_resolved": False,
            "brightness_semantics_confirmed": False,
            "censorship_semantics_confirmed": False,
            "prototype_candidate_rows": 0,
            "skipped_rows": 0,
            "parameters": {
                "record_leaf_relative_dwords": [0, 1],
                "non_leaf_context_relative_dwords": list(range(2, 10)),
                "normalized_reference_relative_dword": 10,
                "expected_focal_values": [format_float(value) for value in EXPECTED_FOCAL_VALUES],
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
            "next_action": "Upload this report. Continue only with a read-only ordinal/section-binding audit of the seven-value equal-float family. Do not name the values brightness/intensity and do not write G1E.",
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
    except Stage101Error as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print(f"Report directory: {output}")
    if archive:
        print(f"Report: {archive}")
    print(f"Focal template records: {summary['focal_context_record_rows']}")
    print(f"Focal value domain: {', '.join(summary['focal_context_values'])}")
    print(f"Storage class: {summary['technical_leaf_storage_class']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
