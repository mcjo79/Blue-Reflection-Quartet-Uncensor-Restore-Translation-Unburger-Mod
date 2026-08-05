#!/usr/bin/env python3
"""Audit section-table entries against slot-light reference-record occurrences.

Stage 92 corrected the neutral cross-occurrence pairing and left two equally
valid PC02 alignments because the target contains duplicate 75/75 records. This
metadata-only stage combines the stage-91 section tables with the stage-92
occurrence inventory. It tests whether signed table entries land at stable
record-relative positions and whether any table binding uniquely identifies
which target 75 continues the Original 150 occurrence.

No G1E/G1EM, Elixir, PAK, registry or installed-game payload is written. The
stage does not infer brightness, censorship, timing, intensity or radius.
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import subprocess
import sys
from collections import Counter, defaultdict
from pathlib import Path, PurePosixPath
from typing import Any, Iterable, Mapping, Sequence

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT_DEFAULT = SCRIPT_DIR.parent.parent

TOOL_VERSION = "0.1.7"
REPORT_NAME = "BR_quartet_restoration_reflector_slot_light_section_table_record_binding_evidence.tar.zst"
REPORT_DIR = "reflector_slot_light_section_table_record_binding_evidence"
STAGE91_DIR = "reflector_slot_light_section_cardinality_record_role_evidence"
STAGE91_ARCHIVE = "BR_quartet_restoration_reflector_slot_light_section_cardinality_record_role_evidence.tar.zst"
STAGE92_DIR = "reflector_slot_light_record_occurrence_identity_evidence"
STAGE92_ARCHIVE = "BR_quartet_restoration_reflector_slot_light_record_occurrence_identity_evidence.tar.zst"
EXPECTED_REFERENCE_ROWS = 177
EXPECTED_TABLE_ENTRY_ROWS = 51
EXPECTED_CLUSTER_MEMBERS = 4
RECORD_DWORDS = 11
SEARCH_MIN_DWORD = -64
SEARCH_MAX_DWORD = 10


class Stage93Error(RuntimeError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise Stage93Error(message)


def progress(message: str) -> None:
    print(f"[stage93] {message}", file=sys.stderr, flush=True)


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


def load_json(path: Path) -> dict[str, Any]:
    require(path.is_file(), f"missing required JSON: {path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise Stage93Error(f"invalid JSON {path}: {exc}") from exc
    require(isinstance(value, dict), f"JSON root must be object: {path}")
    return value


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


def stable_member_side(row: Mapping[str, Any]) -> tuple[str, str, str]:
    return (
        str(row.get("normalized_path", "")).casefold(),
        str(row.get("member_key", "")).casefold(),
        str(row.get("side", "")).casefold(),
    )


def validate_stage91(root: Path) -> dict[str, Any]:
    summary = load_json(root / "SUMMARY.json")
    require(summary.get("type") == "br_quartet_restoration_reflector_slot_light_section_cardinality_record_role_evidence_summary", "stage91 type mismatch")
    require(summary.get("tool_version") == "0.1.5", "stage91 tool version mismatch")
    require(parse_int(summary.get("reference_cluster_member_rows"), -1) == EXPECTED_CLUSTER_MEMBERS, "stage91 member count mismatch")
    require(parse_int(summary.get("section_table_entry_rows"), -1) == EXPECTED_TABLE_ENTRY_ROWS, "stage91 table-entry count mismatch")
    require(parse_int(summary.get("reference_record_rows"), -1) == EXPECTED_REFERENCE_ROWS, "stage91 reference count mismatch")
    require(summary.get("resolved_reference_origin") == "dword_start_relative", "stage91 reference origin mismatch")
    require(parse_int(summary.get("prototype_candidate_rows"), -1) == 0, "stage91 unexpectedly authorized prototype")
    require(not parse_bool(summary.get("brightness_semantics_confirmed")), "stage91 unexpectedly confirmed brightness")
    require(not parse_bool(summary.get("censorship_semantics_confirmed")), "stage91 unexpectedly confirmed censorship")
    require(parse_int(summary.get("skipped_rows"), -1) == 0, "stage91 contains skipped rows")
    return summary


def validate_stage92(root: Path) -> dict[str, Any]:
    summary = load_json(root / "SUMMARY.json")
    require(summary.get("type") == "br_quartet_restoration_reflector_slot_light_record_occurrence_identity_evidence_summary", "stage92 type mismatch")
    require(summary.get("tool_version") == "0.1.6", "stage92 tool version mismatch")
    require(parse_int(summary.get("reference_record_rows"), -1) == EXPECTED_REFERENCE_ROWS, "stage92 reference count mismatch")
    require(parse_bool(summary.get("neutral_focal_variants_coexist_unchanged")), "stage92 neutral correction missing")
    require(not parse_bool(summary.get("neutral_150_to_75_transition_supported")), "stage92 unexpectedly supports neutral transition")
    require(parse_bool(summary.get("prior_transition_interpretation_corrected")), "stage92 correction flag missing")
    require(parse_int(summary.get("candidate_middle_target_duplicate_rows"), -1) == 2, "stage92 duplicate-target count mismatch")
    require(parse_int(summary.get("candidate_minimum_edit_model_rows"), -1) == 2, "stage92 edit-model count mismatch")
    require(not parse_bool(summary.get("candidate_target_occurrence_identity_resolved")), "stage92 unexpectedly resolved identity")
    require(parse_int(summary.get("prototype_candidate_rows"), -1) == 0, "stage92 unexpectedly authorized prototype")
    require(not parse_bool(summary.get("brightness_semantics_confirmed")), "stage92 unexpectedly confirmed brightness")
    require(not parse_bool(summary.get("censorship_semantics_confirmed")), "stage92 unexpectedly confirmed censorship")
    require(parse_int(summary.get("skipped_rows"), -1) == 0, "stage92 contains skipped rows")
    return summary


def build_report(
    project_root: Path,
    *,
    create_archive: bool = True,
    report_root: Path | None = None,
    workspace_root: Path | None = None,
) -> tuple[Path, Path | None, dict[str, Any]]:
    project_root = project_root.resolve()
    reports = (report_root or project_root / ".local/reports/quartet_restoration").resolve()
    workspace = (workspace_root or project_root / ".local/build/quartet_restoration/stage93_section_table_record_binding").resolve()
    reports.mkdir(parents=True, exist_ok=True)
    workspace.mkdir(parents=True, exist_ok=True)

    progress("validating stage-91 and stage-92 reports")
    stage91 = locate(reports, STAGE91_DIR, STAGE91_ARCHIVE, workspace / "stage91")
    stage92 = locate(reports, STAGE92_DIR, STAGE92_ARCHIVE, workspace / "stage92")
    summary91 = validate_stage91(stage91)
    summary92 = validate_stage92(stage92)

    table_rows = read_tsv(stage91 / "SLOT_LIGHT_SECTION_TABLE_ENTRIES.tsv")
    table_delta_rows = read_tsv(stage91 / "SLOT_LIGHT_SECTION_TABLE_DELTA.tsv")
    occurrence_rows = read_tsv(stage92 / "SLOT_LIGHT_RECORD_OCCURRENCE_INVENTORY.tsv")
    sequence_rows = read_tsv(stage92 / "SLOT_LIGHT_CANDIDATE_FAMILY_SEQUENCE_ALIGNMENT.tsv")
    edit_model_rows = read_tsv(stage92 / "SLOT_LIGHT_CANDIDATE_EDIT_MODELS.tsv")
    require(len(table_rows) == EXPECTED_TABLE_ENTRY_ROWS, "table-entry row count mismatch")
    require(len(occurrence_rows) == EXPECTED_REFERENCE_ROWS, "occurrence row count mismatch")
    require(len(edit_model_rows) == 3, "stage92 edit-model table mismatch")

    occurrences_by_member_side: dict[tuple[str, str, str], list[dict[str, str]]] = defaultdict(list)
    for row in occurrence_rows:
        occurrences_by_member_side[stable_member_side(row)].append(row)
    for rows in occurrences_by_member_side.values():
        rows.sort(key=lambda row: parse_int(row.get("record_start"), -1))

    progress("testing signed table-entry anchors against all record occurrences")
    binding_rows: list[dict[str, Any]] = []
    exact_displacement_counts: Counter[int] = Counter()
    exact_binding_keys: set[tuple[str, str, str, int, int]] = set()
    skipped_rows: list[dict[str, Any]] = []
    for table in table_rows:
        key = stable_member_side(table)
        records = occurrences_by_member_side.get(key, [])
        require(records, f"missing occurrence inventory for {key}")
        absolute = parse_int(table.get("entry_absolute_offset"), -1)
        value = parse_int(table.get("entry_i32"), 0)
        anchor = absolute + value
        aligned_value = parse_bool(table.get("entry_aligned"))
        candidates: list[tuple[int, int, dict[str, str]]] = []
        if aligned_value:
            for record in records:
                start = parse_int(record.get("record_start"), -1)
                delta = anchor - start
                if delta % 4 == 0 and SEARCH_MIN_DWORD <= delta // 4 <= SEARCH_MAX_DWORD:
                    candidates.append((abs(delta), delta // 4, record))
        candidates.sort(key=lambda item: (item[0], parse_int(item[2].get("reference_index"), -1)))
        if not candidates:
            binding_rows.append({
                **table,
                "signed_anchor": anchor,
                "binding_candidate_rows": 0,
                "best_record_relative_dword": "",
                "best_record_start": "",
                "best_reference_offset": "",
                "best_reference_index": "",
                "best_variant_label": "",
                "best_is_focal_family": "",
                "best_distance_bytes": "",
                "exact_dominant_binding": False,
                "binding_classification": "no_record_relative_binding_in_search_window" if aligned_value else "non_aligned_or_float_like_table_value",
            })
            continue
        best_distance, relative_dword, best = candidates[0]
        exact_displacement_counts[relative_dword] += 1
        binding_rows.append({
            **table,
            "signed_anchor": anchor,
            "binding_candidate_rows": len(candidates),
            "best_record_relative_dword": relative_dword,
            "best_record_start": best.get("record_start", ""),
            "best_reference_offset": best.get("reference_offset", ""),
            "best_reference_index": best.get("reference_index", ""),
            "best_variant_label": best.get("variant_label", ""),
            "best_is_focal_family": best.get("is_focal_family", ""),
            "best_distance_bytes": best_distance,
            "exact_dominant_binding": False,
            "binding_classification": "record_relative_candidate",
        })

    require(exact_displacement_counts, "no aligned table-entry/record relations found")
    dominant_relative_dword, dominant_rows = sorted(exact_displacement_counts.items(), key=lambda item: (-item[1], item[0]))[0]
    dominant_unique = sum(1 for displacement, count in exact_displacement_counts.items() if count == dominant_rows) == 1
    for row in binding_rows:
        is_dominant = parse_int(row.get("best_record_relative_dword"), 9999) == dominant_relative_dword
        row["exact_dominant_binding"] = is_dominant
        if is_dominant:
            row["binding_classification"] = "dominant_record_relative_binding"
            exact_binding_keys.add((
                str(row.get("member_key", "")).casefold(),
                str(row.get("side", "")).casefold(),
                parse_int(row.get("table_index"), -1),
                parse_int(row.get("entry_index"), -1),
                parse_int(row.get("best_reference_index"), -1),
            ))

    displacement_rows = [
        {
            "record_relative_dword": displacement,
            "record_relative_bytes": displacement * 4,
            "binding_rows": count,
            "is_dominant": displacement == dominant_relative_dword,
            "dominant_unique": dominant_unique if displacement == dominant_relative_dword else "",
        }
        for displacement, count in sorted(exact_displacement_counts.items(), key=lambda item: (-item[1], item[0]))
    ]

    candidate_key = "e_pc02_w5_ringlight_01.g1e#0"
    candidate_target_t3 = [
        row for row in binding_rows
        if str(row.get("member_key", "")).casefold() == candidate_key
        and str(row.get("side", "")).casefold() == "target"
        and parse_int(row.get("table_index"), -1) == 3
        and parse_bool(row.get("exact_dominant_binding"))
    ]
    candidate_target_t3.sort(key=lambda row: parse_int(row.get("entry_index"), -1))
    require(len(candidate_target_t3) == 3, f"expected three candidate target table-3 bindings, found {len(candidate_target_t3)}")
    target_t3_variants = [str(row.get("best_variant_label", "")) for row in candidate_target_t3]
    require(target_t3_variants == ["equal_float_30", "equal_float_75", "equal_float_75"], f"unexpected candidate target table-3 sequence: {target_t3_variants}")

    candidate_source_dominant = [
        row for row in binding_rows
        if str(row.get("member_key", "")).casefold() == candidate_key
        and str(row.get("side", "")).casefold() == "source"
        and parse_bool(row.get("exact_dominant_binding"))
    ]
    require(not candidate_source_dominant, "candidate source unexpectedly has dominant table-to-record bindings")

    target_binding_rows: list[dict[str, Any]] = []
    for row in candidate_target_t3:
        target_binding_rows.append({
            "table_index": row.get("table_index", ""),
            "entry_index": row.get("entry_index", ""),
            "entry_absolute_offset": row.get("entry_absolute_offset", ""),
            "entry_i32": row.get("entry_i32", ""),
            "signed_anchor": row.get("signed_anchor", ""),
            "record_relative_dword": row.get("best_record_relative_dword", ""),
            "record_start": row.get("best_record_start", ""),
            "reference_offset": row.get("best_reference_offset", ""),
            "reference_index": row.get("best_reference_index", ""),
            "variant_label": row.get("best_variant_label", ""),
            "binding_role": "candidate_target_table3_focal_family_binding",
        })

    duplicate_75_bindings = [row for row in target_binding_rows if row["variant_label"] == "equal_float_75"]
    require(len(duplicate_75_bindings) == 2, "target duplicate-75 binding count mismatch")
    distinct_table_entries = len({parse_int(row["entry_index"], -1) for row in duplicate_75_bindings}) == 2
    distinct_record_occurrences = len({parse_int(row["record_start"], -1) for row in duplicate_75_bindings}) == 2
    require(distinct_table_entries and distinct_record_occurrences, "duplicate target occurrences were not independently bound")

    stable_prefix_bound = any(row["variant_label"] == "equal_float_30" for row in target_binding_rows)
    source_counterpart_binding_rows = len(candidate_source_dominant)
    target_binding_bulk_reencoding = stable_prefix_bound and source_counterpart_binding_rows == 0
    identity_resolved = False
    decision_rows = [{
        "question": "which target 75 continues the Original 150 occurrence",
        "target_duplicate_occurrences_bound_individually": True,
        "target_duplicate_table_entry_indices": " | ".join(str(row["entry_index"]) for row in duplicate_75_bindings),
        "target_duplicate_record_starts": " | ".join(str(row["record_start"]) for row in duplicate_75_bindings),
        "stable_prefix_record_also_newly_bound": stable_prefix_bound,
        "source_focal_family_dominant_binding_rows": source_counterpart_binding_rows,
        "target_table_binding_is_unique_insertion_marker": False,
        "occurrence_identity_resolved": identity_resolved,
        "classification": "target_table3_distinguishes_duplicate_occurrences_but_bulk_binding_change_has_no_source_counterpart; continuation_identity_unresolved",
    }]

    table_delta_by_index = {parse_int(row.get("table_index"), -1): row for row in table_delta_rows if str(row.get("member_key", "")).casefold() == candidate_key}
    comparison_rows: list[dict[str, Any]] = []
    for table_index in (1, 2, 3):
        source_rows = [row for row in binding_rows if str(row.get("member_key", "")).casefold() == candidate_key and str(row.get("side", "")).casefold() == "source" and parse_int(row.get("table_index"), -1) == table_index]
        target_rows = [row for row in binding_rows if str(row.get("member_key", "")).casefold() == candidate_key and str(row.get("side", "")).casefold() == "target" and parse_int(row.get("table_index"), -1) == table_index]
        delta = table_delta_by_index.get(table_index, {})
        comparison_rows.append({
            "table_index": table_index,
            "source_entry_rows": len(source_rows),
            "target_entry_rows": len(target_rows),
            "source_dominant_binding_rows": sum(parse_bool(row.get("exact_dominant_binding")) for row in source_rows),
            "target_dominant_binding_rows": sum(parse_bool(row.get("exact_dominant_binding")) for row in target_rows),
            "source_entry_values": " | ".join(str(row.get("entry_u32_hex", "")) for row in source_rows),
            "target_entry_values": " | ".join(str(row.get("entry_u32_hex", "")) for row in target_rows),
            "stage91_delta_classification": delta.get("delta_classification", ""),
            "binding_interpretation": "target_focal_family_bulk_binding" if table_index == 3 else "no_unique_occurrence_binding",
        })

    output = reports / REPORT_DIR
    if output.exists():
        import shutil
        shutil.rmtree(output)
    output.mkdir(parents=True)

    write_tsv(output / "SLOT_LIGHT_SECTION_TABLE_RECORD_BINDING_CANDIDATES.tsv", [
        "cluster_role", "normalized_path", "member_key", "member_name", "side", "endpoint", "section_count",
        "table_index", "entry_index", "entry_relative_offset", "entry_absolute_offset", "entry_u32_hex", "entry_i32",
        "entry_float32", "entry_float_status", "entry_aligned", "signed_anchor", "binding_candidate_rows",
        "best_record_relative_dword", "best_record_start", "best_reference_offset", "best_reference_index",
        "best_variant_label", "best_is_focal_family", "best_distance_bytes", "exact_dominant_binding", "binding_classification",
    ], binding_rows)
    write_tsv(output / "SLOT_LIGHT_SECTION_TABLE_RECORD_OFFSET_DISTRIBUTION.tsv", [
        "record_relative_dword", "record_relative_bytes", "binding_rows", "is_dominant", "dominant_unique",
    ], displacement_rows)
    write_tsv(output / "SLOT_LIGHT_CANDIDATE_TARGET_TABLE3_BINDINGS.tsv", [
        "table_index", "entry_index", "entry_absolute_offset", "entry_i32", "signed_anchor", "record_relative_dword",
        "record_start", "reference_offset", "reference_index", "variant_label", "binding_role",
    ], target_binding_rows)
    write_tsv(output / "SLOT_LIGHT_CANDIDATE_TABLE_BINDING_COMPARISON.tsv", [
        "table_index", "source_entry_rows", "target_entry_rows", "source_dominant_binding_rows", "target_dominant_binding_rows",
        "source_entry_values", "target_entry_values", "stage91_delta_classification", "binding_interpretation",
    ], comparison_rows)
    write_tsv(output / "SLOT_LIGHT_DUPLICATE_TARGET_OCCURRENCE_BINDING.tsv", [
        "table_index", "entry_index", "entry_absolute_offset", "entry_i32", "signed_anchor", "record_relative_dword",
        "record_start", "reference_offset", "reference_index", "variant_label", "binding_role",
    ], duplicate_75_bindings)
    write_tsv(output / "SLOT_LIGHT_TABLE_BINDING_IDENTITY_DECISION.tsv", [
        "question", "target_duplicate_occurrences_bound_individually", "target_duplicate_table_entry_indices",
        "target_duplicate_record_starts", "stable_prefix_record_also_newly_bound", "source_focal_family_dominant_binding_rows",
        "target_table_binding_is_unique_insertion_marker", "occurrence_identity_resolved", "classification",
    ], decision_rows)
    write_tsv(output / "SLOT_LIGHT_SECTION_TABLE_RECORD_BINDING_SKIPPED.tsv", ["scope", "member_name", "side", "offset", "reason"], skipped_rows)

    summary: dict[str, Any] = {
        "type": "br_quartet_restoration_reflector_slot_light_section_table_record_binding_evidence_summary",
        "format_version": 1,
        "tool_version": TOOL_VERSION,
        "source_stage91_tool_version": summary91.get("tool_version"),
        "source_stage92_tool_version": summary92.get("tool_version"),
        "status": "stage92_occurrence_identity_valid_target_table3_distinguishes_duplicate_occurrences_but_bulk_binding_change_does_not_resolve_continuation_identity",
        "reference_record_rows": len(occurrence_rows),
        "section_table_entry_rows": len(table_rows),
        "aligned_table_entry_record_candidate_rows": sum(bool(str(row.get("best_record_start", ""))) for row in binding_rows),
        "record_relative_offset_classes": len(exact_displacement_counts),
        "dominant_record_relative_dword": dominant_relative_dword,
        "dominant_record_relative_bytes": dominant_relative_dword * 4,
        "dominant_record_relative_binding_rows": dominant_rows,
        "dominant_record_relative_offset_unique": dominant_unique,
        "candidate_source_dominant_binding_rows": len(candidate_source_dominant),
        "candidate_target_table3_dominant_binding_rows": len(candidate_target_t3),
        "candidate_target_table3_variant_sequence": target_t3_variants,
        "candidate_target_duplicate_75_binding_rows": len(duplicate_75_bindings),
        "candidate_target_duplicate_75_bindings_distinct": distinct_table_entries and distinct_record_occurrences,
        "stable_prefix_record_also_target_table_bound": stable_prefix_bound,
        "target_table_binding_bulk_reencoding_supported": target_binding_bulk_reencoding,
        "target_table_binding_unique_insertion_marker": False,
        "candidate_target_occurrence_identity_resolved": identity_resolved,
        "technical_leaf_semantics_resolved": False,
        "prototype_candidate_rows": 0,
        "brightness_semantics_confirmed": False,
        "censorship_semantics_confirmed": False,
        "skipped_rows": len(skipped_rows),
        "parameters": {
            "record_dwords": RECORD_DWORDS,
            "signed_table_anchor_equation": "entry_absolute_offset + signed_i32(entry_value)",
            "record_relative_search_dwords": [SEARCH_MIN_DWORD, SEARCH_MAX_DWORD],
            "binding_selection": "nearest aligned record-relative candidate within search window",
            "identity_resolution_gate": "a target binding must have an unambiguous source-side counterpart or uniquely mark only the inserted occurrence",
        },
        "policy": {
            "installed_game_modified": False,
            "render_payload_written": False,
            "event_payload_written": False,
            "pak_repacked": False,
            "core_registry_modified": False,
            "profile_activated": False,
            "runtime_validation_inferred": False,
            "censorship_semantics_inferred": False,
            "brightness_semantics_inferred": False,
            "record_numeric_leaf_semantics_inferred": False,
            "canary_track_modified": False,
            "full_proprietary_payloads_exported": False,
        },
        "next_action": "Upload this report. The target table-3 entries distinguish the two duplicate 75 occurrences, but the same new target-side binding also covers the stable 30 prefix and has no source-side counterpart, so it is a bulk encoding change rather than a unique insertion marker. Continue only with a read-only pre-record anchor/header audit around the dominant record-relative target to determine what the table entries reference; do not write G1E or infer brightness/censorship.",
    }
    require(summary["reference_record_rows"] == EXPECTED_REFERENCE_ROWS, "summary reference count mismatch")
    require(summary["section_table_entry_rows"] == EXPECTED_TABLE_ENTRY_ROWS, "summary table-entry count mismatch")
    require(summary["candidate_target_table3_dominant_binding_rows"] == 3, "summary target binding count mismatch")
    require(summary["candidate_target_duplicate_75_binding_rows"] == 2, "summary duplicate binding count mismatch")
    require(not summary["candidate_target_occurrence_identity_resolved"], "stage93 must not resolve target occurrence identity")
    require(summary["prototype_candidate_rows"] == 0, "stage93 must not authorize a prototype")

    (output / "SUMMARY.json").write_text(json.dumps(summary, indent=2, sort_keys=False) + "\n", encoding="utf-8")
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
    except Stage93Error as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print(f"Output: {output}")
    if archive:
        print(f"Report: {archive}")
    print(f"Dominant record-relative dword: {summary['dominant_record_relative_dword']}")
    print(f"Target table-3 focal bindings: {summary['candidate_target_table3_dominant_binding_rows']}")
    print(f"Target occurrence identity resolved: {summary['candidate_target_occurrence_identity_resolved']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
