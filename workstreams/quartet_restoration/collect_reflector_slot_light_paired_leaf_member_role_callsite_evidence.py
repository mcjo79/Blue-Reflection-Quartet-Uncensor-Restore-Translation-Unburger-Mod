#!/usr/bin/env python3
"""Correlate paired-float record values with technical member roles and callsites.

Stage 102 established that the seven paired values are not section ordinals,
section cardinalities, or unique section-table-slot identifiers.  This
metadata-only stage joins the 21 focal occurrences to the technical member-role
inventory from stage 79 and the bounded control/callsite audit from stage 81.

The stage may determine whether a value uniquely identifies a technical member
role, PC slot, or exact name callsite.  It must not assign a domain meaning such
as brightness, intensity, distance, duration, angle, opacity, or scale.  No G1E
write, prototype, profile, activation, installed-game write, or runtime claim is
allowed.
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import subprocess
import sys
import tempfile
from collections import defaultdict
from pathlib import Path, PurePosixPath
from typing import Any, Iterable, Mapping, Sequence

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT_DEFAULT = SCRIPT_DIR.parent.parent
TOOL_VERSION = "0.1.17"
REPORT_NAME = "BR_quartet_restoration_reflector_slot_light_paired_leaf_member_role_callsite_evidence.tar.zst"
REPORT_DIR = "reflector_slot_light_paired_leaf_member_role_callsite_evidence"
STAGE102_DIR = "reflector_slot_light_paired_leaf_ordinal_section_binding_evidence"
STAGE102_ARCHIVE = "BR_quartet_restoration_reflector_slot_light_paired_leaf_ordinal_section_binding_evidence.tar.zst"
STAGE79_DIR = "reflector_character_slot_render_member_evidence"
STAGE79_ARCHIVE = "BR_quartet_restoration_reflector_character_slot_render_member_evidence.tar.zst"
STAGE81_DIR = "reflector_ringlight_control_callsite_evidence"
STAGE81_ARCHIVE = "BR_quartet_restoration_reflector_ringlight_control_callsite_evidence.tar.zst"

EXPECTED_FOCAL_ROWS = 21
EXPECTED_MEMBER_SIDE_ROWS = 8
EXPECTED_MEMBER_ROWS = 4
EXPECTED_VALUES = ("1", "2", "30", "50", "75", "100", "150")
FOCAL_MEMBERS = {
    "e_cmn_pup_reflect_s.g1e#0",
    "e_pc00_eyelight_00.g1e#0",
    "e_pc00_eyelight_01.g1e#0",
    "e_pc02_w5_ringlight_01.g1e#0",
}


class Stage103Error(RuntimeError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise Stage103Error(message)


def progress(message: str) -> None:
    print(f"[stage103] {message}", file=sys.stderr, flush=True)


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
        raise Stage103Error(f"invalid JSON {path}: {exc}") from exc
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


def validate_stage102(root: Path) -> dict[str, Any]:
    summary = load_json(root / "SUMMARY.json")
    require(summary.get("type") == "br_quartet_restoration_reflector_slot_light_paired_leaf_ordinal_section_binding_evidence_summary", "stage102 type mismatch")
    require(summary.get("tool_version") == "0.1.16", "stage102 tool version mismatch")
    require(parse_int(summary.get("focal_record_rows"), -1) == EXPECTED_FOCAL_ROWS, "stage102 focal row count mismatch")
    require(parse_int(summary.get("focal_member_side_rows"), -1) == EXPECTED_MEMBER_SIDE_ROWS, "stage102 member-side count mismatch")
    require(tuple(summary.get("parameters", {}).get("expected_values", [])) == EXPECTED_VALUES, "stage102 value domain mismatch")
    require(not parse_bool(summary.get("paired_leaf_is_section_ordinal")), "stage102 unexpectedly classified ordinal")
    require(not parse_bool(summary.get("paired_leaf_is_section_cardinality")), "stage102 unexpectedly classified cardinality")
    require(not parse_bool(summary.get("paired_leaf_is_unique_table_slot_identifier")), "stage102 unexpectedly classified table slot")
    require(not parse_bool(summary.get("technical_leaf_domain_semantics_resolved")), "stage102 unexpectedly resolved domain semantics")
    require(parse_int(summary.get("skipped_rows"), -1) == 0, "stage102 contains skipped rows")
    return summary


def validate_stage79(root: Path) -> dict[str, Any]:
    summary = load_json(root / "SUMMARY.json")
    require(summary.get("type") == "br_quartet_restoration_reflector_character_slot_render_member_evidence_summary", "stage79 type mismatch")
    require(summary.get("tool_version") == "0.0.92", "stage79 tool version mismatch")
    require(parse_int(summary.get("slot_member_rows"), -1) == 220, "stage79 slot-member count mismatch")
    require(parse_int(summary.get("skipped_rows"), 0) == 0, "stage79 contains skipped rows")
    return summary


def validate_stage81(root: Path) -> dict[str, Any]:
    summary = load_json(root / "SUMMARY.json")
    require(summary.get("type") == "br_quartet_restoration_reflector_ringlight_control_callsite_evidence_summary", "stage81 type mismatch")
    require(summary.get("tool_version") == "0.0.95", "stage81 tool version mismatch")
    require(parse_int(summary.get("control_member_rows"), -1) == 525, "stage81 control-member count mismatch")
    require(parse_int(summary.get("container_exact_reference_rows"), -1) == 0, "stage81 container exact-reference count changed")
    require(parse_int(summary.get("transformation_event_exact_reference_rows"), -1) == 0, "stage81 event exact-reference count changed")
    require(not parse_bool(summary.get("exact_name_callsite_binding_resolved")), "stage81 unexpectedly resolved exact callsite")
    require(parse_int(summary.get("skipped_rows"), -1) == 0, "stage81 contains skipped rows")
    return summary


def technical_role(member_key: str, slot_row: Mapping[str, str] | None, control_row: Mapping[str, str]) -> tuple[str, str]:
    if slot_row:
        role = slot_row.get("asset_role", "").strip().casefold()
        require(role in {"eyelight", "ringlight"}, f"unexpected slot asset role for {member_key}: {role}")
        return role, slot_row.get("character_slot", "")
    scope = control_row.get("control_scope", "").strip()
    require(scope == "neutral_non_transformation_name_control", f"unexpected neutral control scope for {member_key}: {scope}")
    return "neutral_pupil_reflect_control", ""


def build_report(project_root: Path, *, create_archive: bool = True, report_root: Path | None = None) -> tuple[Path, Path | None, dict[str, Any]]:
    report_root = report_root or project_root / ".local/reports/quartet_restoration"
    progress("validating stage-79, stage-81 and stage-102 metadata")
    with tempfile.TemporaryDirectory(prefix="br-stage103-") as temporary_name:
        temporary = Path(temporary_name)
        stage102 = locate(report_root, STAGE102_DIR, STAGE102_ARCHIVE, temporary / "stage102")
        stage79 = locate(report_root, STAGE79_DIR, STAGE79_ARCHIVE, temporary / "stage79")
        stage81 = locate(report_root, STAGE81_DIR, STAGE81_ARCHIVE, temporary / "stage81")
        validate_stage102(stage102)
        validate_stage79(stage79)
        stage81_summary = validate_stage81(stage81)

        ordinal_rows = read_tsv(stage102 / "SLOT_LIGHT_FOCAL_ORDINAL_INVENTORY.tsv")
        require(len(ordinal_rows) == EXPECTED_FOCAL_ROWS, f"expected {EXPECTED_FOCAL_ROWS} stage102 rows, found {len(ordinal_rows)}")
        require({row.get("member_key", "").casefold() for row in ordinal_rows} == FOCAL_MEMBERS, "stage102 focal member set mismatch")

        slot_rows = read_tsv(stage79 / "REFLECTOR_SLOT_RENDER_MEMBERS.tsv")
        slot_lookup = {row.get("member_key", "").casefold(): row for row in slot_rows if row.get("member_key", "").casefold() in FOCAL_MEMBERS}
        require(set(slot_lookup) == FOCAL_MEMBERS - {"e_cmn_pup_reflect_s.g1e#0"}, "stage79 focal slot-role coverage mismatch")

        parent_rows = read_tsv(stage81 / "RINGLIGHT_PARENT_CONTAINER_CONTROLS.tsv")
        parent_lookup = {row.get("member_key", "").casefold(): row for row in parent_rows if row.get("member_key", "").casefold() in FOCAL_MEMBERS}
        require(set(parent_lookup) == FOCAL_MEMBERS, "stage81 focal parent-control coverage mismatch")

        container_refs = read_tsv(stage81 / "RINGLIGHT_EFFECT_CONTAINER_EXACT_REFERENCES.tsv")
        event_refs = read_tsv(stage81 / "RINGLIGHT_TRANSFORMATION_EVENT_EXACT_REFERENCES.tsv")
        require(len(container_refs) == 0 and len(event_refs) == 0, "stage81 exact callsite tables are no longer empty")

        progress("joining focal occurrences to technical member roles")
        member_side_groups: dict[tuple[str, str], list[dict[str, str]]] = defaultdict(list)
        for row in ordinal_rows:
            member_side_groups[(row.get("member_key", "").casefold(), row.get("side", ""))].append(row)
        require(len(member_side_groups) == EXPECTED_MEMBER_SIDE_ROWS, "focal member-side grouping mismatch")

        inventory_rows: list[dict[str, Any]] = []
        occurrence_rows: list[dict[str, Any]] = []
        role_set: set[str] = set()
        member_roles: dict[str, tuple[str, str]] = {}
        for member_key in sorted(FOCAL_MEMBERS):
            parent = parent_lookup[member_key]
            role, slot = technical_role(member_key, slot_lookup.get(member_key), parent)
            member_roles[member_key] = (role, slot)
            role_set.add(role)
            for side in ("source", "target"):
                rows = sorted(member_side_groups[(member_key, side)], key=lambda row: parse_int(row.get("focal_ordinal_zero_based"), -1))
                require(rows, f"missing {side} rows for {member_key}")
                inventory_rows.append({
                    "normalized_path": rows[0].get("normalized_path", ""),
                    "member_key": rows[0].get("member_key", ""),
                    "member_name": rows[0].get("member_name", ""),
                    "side": side,
                    "technical_member_role": role,
                    "character_slot": slot,
                    "parent_control_scope": parent.get("control_scope", ""),
                    "change_classification": parent.get("classification", ""),
                    "member_record_rows": len(rows),
                    "value_sequence": " | ".join(row.get("paired_float_value", "") for row in rows),
                    "exact_table_binding_rows": sum(parse_bool(row.get("exact_table_binding")) for row in rows),
                    "exact_name_callsite_rows": 0,
                    "callsite_binding_status": "unresolved_no_exact_name_reference",
                })
                for row in rows:
                    occurrence_rows.append({
                        **row,
                        "technical_member_role": role,
                        "character_slot": slot,
                        "parent_control_scope": parent.get("control_scope", ""),
                        "exact_name_callsite": False,
                    })
        require(len(inventory_rows) == EXPECTED_MEMBER_SIDE_ROWS, "member-role inventory row count mismatch")
        require(role_set == {"eyelight", "ringlight", "neutral_pupil_reflect_control"}, "technical member-role set mismatch")

        progress("auditing value reuse across technical roles and slots")
        by_value: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for row in occurrence_rows:
            by_value[str(row.get("paired_float_value", ""))].append(row)
        require(tuple(sorted(by_value, key=float)) == EXPECTED_VALUES, "unexpected value domain")

        value_role_rows: list[dict[str, Any]] = []
        cross_role_values: list[str] = []
        cross_slot_values: list[str] = []
        for value in sorted(by_value, key=float):
            rows = by_value[value]
            roles = sorted({str(row["technical_member_role"]) for row in rows})
            slots = sorted({str(row["character_slot"]) for row in rows if str(row["character_slot"])})
            member_keys = sorted({str(row.get("member_key", "")).casefold() for row in rows})
            if len(roles) > 1:
                cross_role_values.append(value)
            if len(slots) > 1 or (slots and any(not str(row["character_slot"]) for row in rows)):
                cross_slot_values.append(value)
            value_role_rows.append({
                "paired_float_value": value,
                "occurrence_rows": len(rows),
                "member_rows": len(member_keys),
                "side_rows": len({str(row.get("side", "")) for row in rows}),
                "technical_member_roles": " | ".join(roles),
                "unique_member_role_rows": len(roles),
                "character_slots": " | ".join(slots),
                "unique_character_slot_rows": len(slots),
                "includes_neutral_control": any(row["technical_member_role"] == "neutral_pupil_reflect_control" for row in rows),
                "exact_table_binding_rows": sum(parse_bool(row.get("exact_table_binding")) for row in rows),
                "exact_name_callsite_rows": 0,
                "observed_single_member_role": len(roles) == 1,
                "value_is_proven_member_role_identifier": False,
                "classification": "cross_member_role_reuse" if len(roles) > 1 else "single_observed_role_not_semantic_proof",
            })

        require(cross_role_values == ["1", "75", "150"], f"unexpected cross-role values: {cross_role_values}")
        require(cross_slot_values == ["1", "75", "150"], f"unexpected cross-slot/neutral values: {cross_slot_values}")

        role_sequence_rows = []
        for row in inventory_rows:
            role_sequence_rows.append({
                "member_key": row["member_key"],
                "member_name": row["member_name"],
                "side": row["side"],
                "technical_member_role": row["technical_member_role"],
                "character_slot": row["character_slot"],
                "member_record_rows": row["member_record_rows"],
                "value_sequence": row["value_sequence"],
                "sequence_stable_source_target": False,
                "sequence_classification": "",
            })
        sequence_lookup = {(row["member_key"].casefold(), row["side"]): row for row in role_sequence_rows}
        for member_key in FOCAL_MEMBERS:
            source = sequence_lookup[(member_key, "source")]
            target = sequence_lookup[(member_key, "target")]
            stable = source["value_sequence"] == target["value_sequence"]
            source["sequence_stable_source_target"] = stable
            target["sequence_stable_source_target"] = stable
            classification = "stable_role_sequence" if stable else "member_local_insert_and_value_transition"
            source["sequence_classification"] = classification
            target["sequence_classification"] = classification

        callsite_rows = [
            {
                "scope": "effect_container_exact_name_references",
                "rows_scanned": parse_int(stage81_summary.get("control_member_rows"), 0),
                "exact_reference_rows": len(container_refs),
                "binding_resolved": False,
                "classification": "no_exact_name_callsite_binding",
            },
            {
                "scope": "transformation_event_exact_name_references",
                "rows_scanned": parse_int(stage81_summary.get("transformation_event_rows_scanned"), 0),
                "exact_reference_rows": len(event_refs),
                "binding_resolved": False,
                "classification": "no_exact_name_callsite_binding",
            },
            {
                "scope": "focal_parent_member_role_inventory",
                "rows_scanned": len(parent_lookup),
                "exact_reference_rows": 0,
                "binding_resolved": True,
                "classification": "technical_role_from_member_and_parent_control_metadata_only",
            },
        ]

        decision_rows = [
            {"question": "does one paired value uniquely identify one technical member role", "answer": False, "classification": "values_1_75_150_cross_member_roles"},
            {"question": "does one paired value uniquely identify one character slot", "answer": False, "classification": "values_1_75_150_cross_slot_or_neutral_boundaries"},
            {"question": "is an exact effect-container or transformation-event name callsite resolved", "answer": False, "classification": "zero_exact_name_reference_rows_in_stage81"},
            {"question": "is technical member role known for all focal members", "answer": True, "classification": "eyelight_ringlight_and_neutral_pupil_reflect_control"},
            {"question": "what bounded role is supported for paired leaves", "answer": "context-dependent payload values reused across technical member roles in one shared record family", "classification": "not_member_role_id_not_character_slot_id_not_exact_callsite_id"},
            {"question": "is technical value-domain meaning resolved", "answer": False, "classification": "brightness_intensity_distance_duration_angle_opacity_scale_and_other_meanings_unresolved"},
            {"question": "does this authorize G1E write or prototype", "answer": False, "classification": "evidence_only_no_write"},
        ]

        output = report_root / REPORT_DIR
        if output.exists():
            import shutil
            shutil.rmtree(output)
        output.mkdir(parents=True)
        write_tsv(output / "SLOT_LIGHT_FOCAL_MEMBER_ROLE_INVENTORY.tsv", [
            "normalized_path", "member_key", "member_name", "side", "technical_member_role", "character_slot",
            "parent_control_scope", "change_classification", "member_record_rows", "value_sequence",
            "exact_table_binding_rows", "exact_name_callsite_rows", "callsite_binding_status",
        ], inventory_rows)
        write_tsv(output / "SLOT_LIGHT_VALUE_MEMBER_ROLE_DISTRIBUTION.tsv", [
            "paired_float_value", "occurrence_rows", "member_rows", "side_rows", "technical_member_roles",
            "unique_member_role_rows", "character_slots", "unique_character_slot_rows", "includes_neutral_control",
            "exact_table_binding_rows", "exact_name_callsite_rows", "observed_single_member_role", "value_is_proven_member_role_identifier", "classification",
        ], value_role_rows)
        write_tsv(output / "SLOT_LIGHT_MEMBER_ROLE_SEQUENCE_COMPARISON.tsv", [
            "member_key", "member_name", "side", "technical_member_role", "character_slot", "member_record_rows",
            "value_sequence", "sequence_stable_source_target", "sequence_classification",
        ], role_sequence_rows)
        write_tsv(output / "SLOT_LIGHT_CALLSITE_BINDING_COVERAGE.tsv", [
            "scope", "rows_scanned", "exact_reference_rows", "binding_resolved", "classification",
        ], callsite_rows)
        write_tsv(output / "SLOT_LIGHT_PAIRED_LEAF_MEMBER_ROLE_DECISION.tsv", ["question", "answer", "classification"], decision_rows)
        write_tsv(output / "SLOT_LIGHT_PAIRED_LEAF_MEMBER_ROLE_CALLSITE_SKIPPED.tsv", ["scope", "member_key", "side", "record_start", "reason"], [])

        summary = {
            "type": "br_quartet_restoration_reflector_slot_light_paired_leaf_member_role_callsite_evidence_summary",
            "format_version": 1,
            "tool_version": TOOL_VERSION,
            "source_stage102_tool_version": "0.1.16",
            "source_stage79_tool_version": "0.0.92",
            "source_stage81_tool_version": "0.0.95",
            "status": "paired_float_values_cross_member_roles_without_exact_callsite_binding_domain_semantics_unresolved",
            "focal_record_rows": len(occurrence_rows),
            "focal_member_rows": EXPECTED_MEMBER_ROWS,
            "focal_member_side_rows": len(inventory_rows),
            "technical_member_role_rows": len(role_set),
            "focal_unique_value_rows": len(value_role_rows),
            "cross_member_role_value_rows": len(cross_role_values),
            "cross_member_role_values": cross_role_values,
            "cross_slot_or_neutral_value_rows": len(cross_slot_values),
            "cross_slot_or_neutral_values": cross_slot_values,
            "exact_effect_container_callsite_rows": len(container_refs),
            "exact_transformation_event_callsite_rows": len(event_refs),
            "paired_leaf_is_unique_member_role_identifier": False,
            "paired_leaf_is_unique_character_slot_identifier": False,
            "exact_name_callsite_binding_resolved": False,
            "technical_leaf_storage_class": "paired_equal_finite_float_payload_leaves",
            "technical_leaf_domain_semantics_resolved": False,
            "brightness_semantics_confirmed": False,
            "censorship_semantics_confirmed": False,
            "prototype_candidate_rows": 0,
            "skipped_rows": 0,
            "parameters": {
                "member_role_source": "stage79 slot render-member inventory plus stage81 parent-control scope",
                "callsite_source": "stage81 exact ASCII/UTF-16LE member-name reference tables",
                "expected_values": list(EXPECTED_VALUES),
                "focal_member_keys": sorted(FOCAL_MEMBERS),
            },
            "policy": {
                "technical_leaf_domain_semantics_inferred": False,
                "brightness_semantics_inferred": False,
                "censorship_semantics_inferred": False,
                "full_proprietary_payloads_exported": False,
                "render_payload_written": False,
                "pak_repacked": False,
                "core_registry_modified": False,
                "profile_activated": False,
                "installed_game_modified": False,
                "runtime_validation_inferred": False,
                "canary_track_modified": False,
            },
            "next_action": "Upload this report. Continue only with a read-only format-aware sibling-template expansion across the bounded G1E/G1EM corpus to locate additional exact non-leaf record-body occurrences and correlate them with technical member roles. Do not infer brightness/intensity and do not write G1E.",
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
    parser.add_argument("--report-root", type=Path)
    parser.add_argument("--no-report-archive", action="store_true")
    args = parser.parse_args(argv)
    try:
        output, archive, summary = build_report(
            args.project_root.resolve(),
            create_archive=not args.no_report_archive,
            report_root=args.report_root.resolve() if args.report_root else None,
        )
    except Stage103Error as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print(f"Report directory: {output}")
    if archive:
        print(f"Report: {archive}")
    print(f"Focal records: {summary['focal_record_rows']}")
    print(f"Cross-role values: {summary['cross_member_role_values']}")
    print(f"Exact name callsite binding: {summary['exact_name_callsite_binding_resolved']}")
    print("G1E write/prototype: blocked")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
