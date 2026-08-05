#!/usr/bin/env python3
"""Expand the paired-leaf record template across the bounded G1E/G1EM corpus.

Stage 103 rejected the seven paired float values as unique technical member-role,
character-slot, and exact name-callsite identifiers.  This read-only stage
rehydrates the same four bounded parent effect containers used by stages 81-90,
scans all 540 paired G1E/G1EM members for the exact non-leaf record body from
stage 101, and accepts an occurrence only when:

* the 32-byte dword-2..9 body matches exactly;
* dwords 0 and 1 are bit-equal finite float32 values;
* dword 10 is a signed field-relative reference to an exact format-valid
  56-byte section header.

The stage correlates accepted sibling occurrences with technical member roles
from stage 79 and bounded name scopes from stage 81.  It exports metadata only
and cannot assign brightness/intensity or any other value-domain meaning.  It
must not write G1E/G1EM, create a prototype, alter registry, activate a profile,
or modify the installed game.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import importlib.util
import json
import math
import os
import re
import struct
import subprocess
import sys
import tempfile
from collections import defaultdict
from pathlib import Path, PurePosixPath
from typing import Any, Callable, Iterable, Mapping, Sequence

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT_DEFAULT = SCRIPT_DIR.parent.parent
TOOL_VERSION = "0.1.18"
REPORT_NAME = "BR_quartet_restoration_reflector_slot_light_sibling_template_expansion_evidence.tar.zst"
REPORT_DIR = "reflector_slot_light_sibling_template_expansion_evidence"
STAGE101_DIR = "reflector_slot_light_paired_leaf_context_role_evidence"
STAGE101_ARCHIVE = "BR_quartet_restoration_reflector_slot_light_paired_leaf_context_role_evidence.tar.zst"
STAGE103_DIR = "reflector_slot_light_paired_leaf_member_role_callsite_evidence"
STAGE103_ARCHIVE = "BR_quartet_restoration_reflector_slot_light_paired_leaf_member_role_callsite_evidence.tar.zst"
STAGE79_DIR = "reflector_character_slot_render_member_evidence"
STAGE79_ARCHIVE = "BR_quartet_restoration_reflector_character_slot_render_member_evidence.tar.zst"
STAGE81_DIR = "reflector_ringlight_control_callsite_evidence"
STAGE81_ARCHIVE = "BR_quartet_restoration_reflector_ringlight_control_callsite_evidence.tar.zst"
EXPECTED_SIBLING_PAIRS = 540
EXPECTED_PARENT_CONTAINERS = 4
EXPECTED_KNOWN_OCCURRENCES = 21
EXPECTED_FOCAL_VALUES = ("1", "2", "30", "50", "75", "100", "150")
RECORD_DWORDS = 11
RECORD_BYTES = RECORD_DWORDS * 4
BODY_START_DWORD = 2
BODY_END_DWORD_EXCLUSIVE = 10
BODY_BYTES = (BODY_END_DWORD_EXCLUSIVE - BODY_START_DWORD) * 4
REFERENCE_DWORD = 10
PC_RE = re.compile(r"(?i)(?:^|[_-])(PC\d{2})(?:[_-]|$)")


class Stage104Error(RuntimeError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise Stage104Error(message)


def progress(message: str) -> None:
    print(f"[stage104] {message}", file=sys.stderr, flush=True)


def parse_int(value: Any, default: int = 0) -> int:
    try:
        text = str(value).strip()
        return int(text, 16) if text.casefold().startswith("0x") else int(text)
    except (TypeError, ValueError):
        return default


def parse_bool(value: Any) -> bool:
    return str(value).strip().casefold() in {"1", "true", "yes", "y"}


def format_float(value: float) -> str:
    return f"{value:.9g}"


def signed_i32(value: int) -> int:
    return value - 0x100000000 if value & 0x80000000 else value


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


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
        raise Stage104Error(f"invalid JSON {path}: {exc}") from exc
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
    path = report_root / direct
    return path if path.is_dir() else extract_archive(report_root / archive, temporary)


def make_archive(source: Path, output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(output.name + ".tmp")
    temporary.unlink(missing_ok=True)
    completed = subprocess.run(["tar", "--zstd", "-cf", str(temporary), "-C", str(source.parent), source.name], text=True, capture_output=True)
    require(completed.returncode == 0, completed.stderr.strip())
    os.replace(temporary, output)


def load_module(path: Path, name: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    require(spec is not None and spec.loader is not None, f"cannot load module: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def stable_key(path: str, member_key: str) -> tuple[str, str]:
    return path.casefold(), member_key.casefold()


def validate_stage101(root: Path) -> dict[str, Any]:
    summary = load_json(root / "SUMMARY.json")
    require(summary.get("type") == "br_quartet_restoration_reflector_slot_light_paired_leaf_context_role_evidence_summary", "stage101 type mismatch")
    require(summary.get("tool_version") == "0.1.15", "stage101 tool version mismatch")
    require(parse_int(summary.get("reference_record_rows"), -1) == 177, "stage101 reference-record count mismatch")
    require(parse_int(summary.get("focal_context_record_rows"), -1) == EXPECTED_KNOWN_OCCURRENCES, "stage101 focal count mismatch")
    require(tuple(summary.get("focal_context_values", [])) == EXPECTED_FOCAL_VALUES, "stage101 focal value domain mismatch")
    require(parse_bool(summary.get("technical_leaf_storage_class_resolved")), "stage101 storage class unresolved")
    require(summary.get("technical_leaf_storage_class") == "paired_equal_finite_float_payload_leaves", "stage101 storage class mismatch")
    require(not parse_bool(summary.get("technical_leaf_domain_semantics_resolved")), "stage101 unexpectedly resolved domain semantics")
    require(parse_int(summary.get("prototype_candidate_rows"), -1) == 0, "stage101 unexpectedly authorized prototype")
    require(parse_int(summary.get("skipped_rows"), -1) == 0, "stage101 contains skipped rows")
    return summary


def validate_stage103(root: Path) -> dict[str, Any]:
    summary = load_json(root / "SUMMARY.json")
    require(summary.get("type") == "br_quartet_restoration_reflector_slot_light_paired_leaf_member_role_callsite_evidence_summary", "stage103 type mismatch")
    require(summary.get("tool_version") == "0.1.17", "stage103 tool version mismatch")
    require(parse_int(summary.get("focal_record_rows"), -1) == EXPECTED_KNOWN_OCCURRENCES, "stage103 focal count mismatch")
    require(parse_int(summary.get("exact_effect_container_callsite_rows"), -1) == 0, "stage103 effect callsites changed")
    require(parse_int(summary.get("exact_transformation_event_callsite_rows"), -1) == 0, "stage103 transformation callsites changed")
    require(not parse_bool(summary.get("exact_name_callsite_binding_resolved")), "stage103 unexpectedly resolved exact callsite")
    require(not parse_bool(summary.get("technical_leaf_domain_semantics_resolved")), "stage103 unexpectedly resolved domain semantics")
    require(parse_int(summary.get("prototype_candidate_rows"), -1) == 0, "stage103 unexpectedly authorized prototype")
    require(parse_int(summary.get("skipped_rows"), -1) == 0, "stage103 contains skipped rows")
    return summary


def find_all_aligned(payload: bytes, needle: bytes) -> list[int]:
    require(needle, "empty sibling-template needle")
    rows: list[int] = []
    cursor = 0
    while True:
        offset = payload.find(needle, cursor)
        if offset < 0:
            break
        if offset % 4 == 0:
            rows.append(offset)
        cursor = offset + 1
    return rows


def character_slot(member_name: str) -> str:
    match = PC_RE.search(member_name)
    return match.group(1).upper() if match else ""


def member_role_maps(stage79_root: Path) -> tuple[dict[tuple[str, str], dict[str, str]], list[dict[str, str]]]:
    rows = read_tsv(stage79_root / "REFLECTOR_SLOT_RENDER_MEMBERS.tsv")
    mapping: dict[tuple[str, str], dict[str, str]] = {}
    for row in rows:
        key = stable_key(str(row.get("normalized_path", "")), str(row.get("member_key", "")))
        if all(key):
            mapping[key] = row
    return mapping, rows


def scan_payload(
    *, payload: bytes, body: bytes, parse_header: Callable[[bytes, int], Mapping[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    accepted: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    for body_offset in find_all_aligned(payload, body):
        record_start = body_offset - BODY_START_DWORD * 4
        if record_start < 0 or record_start + RECORD_BYTES > len(payload):
            rejected.append({"body_offset": body_offset, "record_start": record_start, "reason": "record_out_of_bounds"})
            continue
        leaf0_bytes = payload[record_start:record_start + 4]
        leaf1_bytes = payload[record_start + 4:record_start + 8]
        if leaf0_bytes != leaf1_bytes:
            rejected.append({"body_offset": body_offset, "record_start": record_start, "reason": "paired_leaves_not_bit_equal"})
            continue
        leaf_float = struct.unpack("<f", leaf0_bytes)[0]
        if not math.isfinite(leaf_float):
            rejected.append({"body_offset": body_offset, "record_start": record_start, "reason": "paired_leaf_not_finite_float"})
            continue
        reference_offset = record_start + REFERENCE_DWORD * 4
        reference_u32 = int.from_bytes(payload[reference_offset:reference_offset + 4], "little")
        endpoint = reference_offset + signed_i32(reference_u32)
        header = dict(parse_header(payload, endpoint))
        if not parse_bool(header.get("exact_layout")):
            rejected.append({
                "body_offset": body_offset, "record_start": record_start, "reference_offset": reference_offset,
                "endpoint": endpoint, "header_layout_score": header.get("layout_score", 0),
                "reason": "reference_does_not_target_exact_section_header",
            })
            continue
        accepted.append({
            "record_start": record_start,
            "body_offset": body_offset,
            "reference_offset": reference_offset,
            "reference_u32_hex": f"0x{reference_u32:08x}",
            "reference_i32": signed_i32(reference_u32),
            "normalized_endpoint": endpoint,
            "leaf_u32_hex": f"0x{int.from_bytes(leaf0_bytes, 'little'):08x}",
            "paired_float_value": format_float(leaf_float),
            "section_count": parse_int(header.get("count"), -1),
            "section_declared_span": parse_int(header.get("declared_span"), -1),
            "section_header_sha256": str(header.get("header_sha256", "")),
            "record_sha256": sha256(payload[record_start:record_start + RECORD_BYTES]),
            "non_leaf_body_sha256": sha256(body),
        })
    return accepted, rejected


def build_report(
    project_root: Path,
    *,
    create_archive: bool = True,
    workspace_root: Path | None = None,
    report_root: Path | None = None,
    rules_file: Path | None = None,
    maximum_earc_bytes: int = 512 * 1024 * 1024,
    container_loader: Callable[..., tuple[list[dict[str, Any]], list[dict[str, Any]]]] | None = None,
) -> tuple[Path, Path | None, dict[str, Any]]:
    project_root = project_root.resolve()
    reports = (report_root or project_root / ".local/reports/quartet_restoration").resolve()
    workspace = (workspace_root or project_root / ".local/build/quartet_restoration").resolve()
    require(reports.is_dir(), f"missing report root: {reports}")

    stage81 = load_module(project_root / "workstreams/quartet_restoration/collect_reflector_ringlight_control_callsite_evidence.py", "stage81_for_stage104")
    stage86 = load_module(project_root / "workstreams/quartet_restoration/collect_reflector_slot_light_shared_record_template_evidence.py", "stage86_for_stage104")
    stage90 = load_module(project_root / "workstreams/quartet_restoration/collect_reflector_slot_light_target_section_layout_evidence.py", "stage90_for_stage104")

    progress("validating stage 79, 81, 101 and 103 reports")
    with tempfile.TemporaryDirectory(prefix="br-stage104-") as temporary_name:
        temporary = Path(temporary_name)
        stage101_root = locate(reports, STAGE101_DIR, STAGE101_ARCHIVE, temporary / "101")
        stage103_root = locate(reports, STAGE103_DIR, STAGE103_ARCHIVE, temporary / "103")
        stage79_root = locate(reports, STAGE79_DIR, STAGE79_ARCHIVE, temporary / "79")
        stage81_root = locate(reports, STAGE81_DIR, STAGE81_ARCHIVE, temporary / "81")
        summary101 = validate_stage101(stage101_root)
        summary103 = validate_stage103(stage103_root)
        summary79 = stage81.validate_stage79(stage79_root)
        summary81 = stage81.load_json(stage81_root / "SUMMARY.json")
        require(summary81.get("type") == "br_quartet_restoration_reflector_ringlight_control_callsite_evidence_summary", "stage81 type mismatch")
        require(summary81.get("tool_version") == "0.0.95", "stage81 tool version mismatch")
        require(parse_int(summary81.get("skipped_rows"), -1) == 0, "stage81 contains skipped rows")

        family_rows = read_tsv(stage101_root / "SLOT_LIGHT_FOCAL_EQUAL_FLOAT_FAMILY.tsv")
        inventory_rows = read_tsv(stage101_root / "SLOT_LIGHT_PAIRED_LEAF_CONTEXT_INVENTORY.tsv")
        require(len(family_rows) == EXPECTED_KNOWN_OCCURRENCES, "stage101 family row count mismatch")
        known_keys = {
            (
                str(row.get("normalized_path", "")).casefold(),
                str(row.get("member_key", "")).casefold(),
                str(row.get("side", "")),
                parse_int(row.get("record_start"), -1),
            )
            for row in family_rows
        }
        require(len(known_keys) == EXPECTED_KNOWN_OCCURRENCES, "stage101 known occurrence identity is not unique")
        seed_inventory = [row for row in inventory_rows if row.get("occurrence_role") == "candidate_source_150" and parse_bool(row.get("is_focal_context"))]
        require(len(seed_inventory) == 1, f"expected one stage101 candidate source seed, found {len(seed_inventory)}")
        seed_row = seed_inventory[0]
        focal_context_sha = str(seed_row.get("non_leaf_context_sha256", ""))
        require(len(focal_context_sha) == 64, "stage101 focal context hash missing")

        role_map, _role_rows = member_role_maps(stage79_root)
        parent_scope = stage81.select_parent_scope(stage79_root)
        actual_rules = rules_file or project_root / "titles/blue_reflection/modules/quartet_restoration/mappings/effect_material_rules.tsv"
        loader = container_loader or stage81.load_parent_containers
        progress("rehydrating four bounded parent effect containers")
        containers, loader_skipped = loader(
            scope_rows=parent_scope,
            workspace_root=workspace,
            report_root=reports,
            rules_file=actual_rules,
            maximum_earc_bytes=maximum_earc_bytes,
        )
        require(not loader_skipped, f"parent container loader skipped {len(loader_skipped)} rows")
        require(len(containers) == EXPECTED_PARENT_CONTAINERS, f"expected {EXPECTED_PARENT_CONTAINERS} parent containers, found {len(containers)}")
        pair_by_key, all_pairs = stage86.index_pairs(containers)
        require(len(all_pairs) == EXPECTED_SIBLING_PAIRS, f"expected {EXPECTED_SIBLING_PAIRS} sibling pairs, found {len(all_pairs)}")
        progress(f"indexed {len(all_pairs)} sibling G1E/G1EM pairs")

        seed_key = stable_key(str(seed_row.get("normalized_path", "")), str(seed_row.get("member_key", "")))
        seed_pair = pair_by_key.get(seed_key)
        require(seed_pair is not None, f"stage101 seed member missing from bounded corpus: {seed_key}")
        seed_payload = bytes(seed_pair.get("source_payload") or b"")
        seed_start = parse_int(seed_row.get("record_start"), -1)
        require(seed_start >= 0 and seed_start + RECORD_BYTES <= len(seed_payload), "stage101 seed record out of bounds")
        focal_body = seed_payload[seed_start + BODY_START_DWORD * 4:seed_start + BODY_END_DWORD_EXCLUSIVE * 4]
        require(len(focal_body) == BODY_BYTES, "focal body length mismatch")
        require(sha256(focal_body) == focal_context_sha, "rehydrated focal body hash mismatch")

        occurrence_rows: list[dict[str, Any]] = []
        raw_rejected_rows: list[dict[str, Any]] = []
        member_scan_rows: list[dict[str, Any]] = []
        found_known: set[tuple[str, str, str, int]] = set()
        for index, pair in enumerate(all_pairs, start=1):
            if index == 1 or index % 50 == 0 or index == len(all_pairs):
                progress(f"scanning sibling pair {index}/{len(all_pairs)}")
            path = str(pair.get("normalized_path", "")).casefold()
            member_key = str(pair.get("member_key", "")).casefold()
            member_name = str(pair.get("member_name", ""))
            inventory = role_map.get((path, member_key), {})
            asset_role = str(inventory.get("asset_role", ""))
            slot = str(inventory.get("character_slot", "")) or character_slot(member_name)
            scope = str(stage81.control_scope(member_name))
            technical_role = asset_role or scope
            for side in ("source", "target"):
                payload = bytes(pair.get(f"{side}_payload") or b"")
                accepted, rejected = scan_payload(payload=payload, body=focal_body, parse_header=stage90.parse_section_header)
                member_scan_rows.append({
                    "normalized_path": path,
                    "member_key": member_key,
                    "member_name": member_name,
                    "side": side,
                    "technical_member_role": technical_role,
                    "character_slot": slot,
                    "payload_size": len(payload),
                    "raw_aligned_body_hits": len(accepted) + len(rejected),
                    "format_valid_occurrence_rows": len(accepted),
                    "rejected_body_hits": len(rejected),
                })
                for row in rejected:
                    raw_rejected_rows.append({
                        "scope": "sibling_template_scan",
                        "normalized_path": path,
                        "member_key": member_key,
                        "member_name": member_name,
                        "side": side,
                        **row,
                    })
                for row in accepted:
                    occurrence_key = (path, member_key, side, int(row["record_start"]))
                    known = occurrence_key in known_keys
                    if known:
                        found_known.add(occurrence_key)
                    occurrence_rows.append({
                        "normalized_path": path,
                        "member_key": member_key,
                        "member_name": member_name,
                        "side": side,
                        "technical_member_role": technical_role,
                        "bounded_name_scope": scope,
                        "character_slot": slot,
                        **row,
                        "known_stage101_occurrence": known,
                        "additional_sibling_occurrence": not known,
                        "classification": "known_stage101_focal_occurrence" if known else "additional_exact_format_valid_sibling_template_occurrence",
                    })

        require(found_known == known_keys, f"stage104 did not rediscover all stage101 occurrences: {len(found_known)}/{len(known_keys)}")
        occurrence_rows.sort(key=lambda row: (row["normalized_path"], row["member_key"], row["side"], int(row["record_start"])))
        additional_rows = [row for row in occurrence_rows if parse_bool(row.get("additional_sibling_occurrence"))]
        known_rows = [row for row in occurrence_rows if parse_bool(row.get("known_stage101_occurrence"))]
        require(len(known_rows) == EXPECTED_KNOWN_OCCURRENCES, "rediscovered known occurrence count mismatch")

        value_groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
        role_groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for row in occurrence_rows:
            value_groups[str(row["paired_float_value"])].append(row)
            role_groups[str(row["technical_member_role"])].append(row)

        value_rows: list[dict[str, Any]] = []
        for value, rows in sorted(value_groups.items(), key=lambda item: float(item[0])):
            roles = sorted({str(row["technical_member_role"]) for row in rows})
            members = {(str(row["normalized_path"]), str(row["member_key"])) for row in rows}
            value_rows.append({
                "paired_float_value": value,
                "occurrence_rows": len(rows),
                "known_stage101_rows": sum(parse_bool(row.get("known_stage101_occurrence")) for row in rows),
                "additional_sibling_rows": sum(parse_bool(row.get("additional_sibling_occurrence")) for row in rows),
                "member_rows": len(members),
                "technical_member_roles": ";".join(roles),
                "technical_member_role_rows": len(roles),
                "character_slots": ";".join(sorted({str(row["character_slot"]) for row in rows if str(row["character_slot"])})),
                "includes_neutral_scope": any(row.get("bounded_name_scope") == "neutral_non_transformation_name_control" for row in rows),
                "classification": "expanded_sibling_value" if value not in EXPECTED_FOCAL_VALUES else "known_value_with_expanded_or_confirmed_coverage",
            })

        role_rows: list[dict[str, Any]] = []
        for role, rows in sorted(role_groups.items()):
            role_rows.append({
                "technical_member_role": role,
                "occurrence_rows": len(rows),
                "known_stage101_rows": sum(parse_bool(row.get("known_stage101_occurrence")) for row in rows),
                "additional_sibling_rows": sum(parse_bool(row.get("additional_sibling_occurrence")) for row in rows),
                "member_rows": len({(str(row["normalized_path"]), str(row["member_key"])) for row in rows}),
                "paired_float_values": ";".join(sorted({str(row["paired_float_value"]) for row in rows}, key=float)),
                "character_slots": ";".join(sorted({str(row["character_slot"]) for row in rows if str(row["character_slot"])})),
                "classification": "role_with_additional_sibling_template_occurrences" if any(parse_bool(row.get("additional_sibling_occurrence")) for row in rows) else "stage101_known_role_only",
            })

        known_roles = {str(row.get("technical_member_role", "")) for row in known_rows}
        expanded_roles = sorted({str(row.get("technical_member_role", "")) for row in additional_rows} - known_roles)
        discovered_values = sorted({str(row.get("paired_float_value", "")) for row in occurrence_rows}, key=float)
        new_values = [value for value in discovered_values if value not in EXPECTED_FOCAL_VALUES]
        decision_rows = [
            {"question": "were all 21 stage101 focal occurrences rediscovered with exact body and format gates", "answer": True, "classification": "complete_known_occurrence_coverage"},
            {"question": "were additional exact format-valid sibling-template occurrences found", "answer": bool(additional_rows), "classification": "additional_sibling_occurrences_present" if additional_rows else "no_additional_occurrences_in_bounded_corpus"},
            {"question": "did the exact template expand to new technical member roles", "answer": bool(expanded_roles), "classification": ";".join(expanded_roles) if expanded_roles else "no_new_roles"},
            {"question": "did the exact template expand to paired values outside the seven-value stage101 domain", "answer": bool(new_values), "classification": ";".join(new_values) if new_values else "no_new_values"},
            {"question": "does sibling-template expansion resolve brightness intensity or other domain semantics", "answer": False, "classification": "structural_and_role_coverage_only"},
            {"question": "does this authorize G1E write or prototype", "answer": False, "classification": "evidence_only_no_write"},
        ]

        output = reports / REPORT_DIR
        if output.exists():
            import shutil
            shutil.rmtree(output)
        output.mkdir(parents=True)
        occurrence_fields = [
            "normalized_path", "member_key", "member_name", "side", "technical_member_role", "bounded_name_scope", "character_slot",
            "record_start", "body_offset", "reference_offset", "reference_u32_hex", "reference_i32", "normalized_endpoint",
            "leaf_u32_hex", "paired_float_value", "section_count", "section_declared_span", "section_header_sha256",
            "record_sha256", "non_leaf_body_sha256", "known_stage101_occurrence", "additional_sibling_occurrence", "classification",
        ]
        write_tsv(output / "SLOT_LIGHT_SIBLING_TEMPLATE_OCCURRENCES.tsv", occurrence_fields, occurrence_rows)
        write_tsv(output / "SLOT_LIGHT_SIBLING_TEMPLATE_ADDITIONAL_OCCURRENCES.tsv", occurrence_fields, additional_rows)
        write_tsv(output / "SLOT_LIGHT_SIBLING_TEMPLATE_MEMBER_SCAN.tsv", [
            "normalized_path", "member_key", "member_name", "side", "technical_member_role", "character_slot", "payload_size",
            "raw_aligned_body_hits", "format_valid_occurrence_rows", "rejected_body_hits",
        ], member_scan_rows)
        write_tsv(output / "SLOT_LIGHT_SIBLING_TEMPLATE_VALUE_ROLE_DISTRIBUTION.tsv", [
            "paired_float_value", "occurrence_rows", "known_stage101_rows", "additional_sibling_rows", "member_rows",
            "technical_member_roles", "technical_member_role_rows", "character_slots", "includes_neutral_scope", "classification",
        ], value_rows)
        write_tsv(output / "SLOT_LIGHT_SIBLING_TEMPLATE_MEMBER_ROLE_DISTRIBUTION.tsv", [
            "technical_member_role", "occurrence_rows", "known_stage101_rows", "additional_sibling_rows", "member_rows",
            "paired_float_values", "character_slots", "classification",
        ], role_rows)
        write_tsv(output / "SLOT_LIGHT_SIBLING_TEMPLATE_KNOWN_COVERAGE.tsv", [
            "normalized_path", "member_key", "side", "record_start", "rediscovered",
        ], [
            {"normalized_path": key[0], "member_key": key[1], "side": key[2], "record_start": key[3], "rediscovered": key in found_known}
            for key in sorted(known_keys)
        ])
        write_tsv(output / "SLOT_LIGHT_SIBLING_TEMPLATE_EXPANSION_DECISION.tsv", ["question", "answer", "classification"], decision_rows)
        write_tsv(output / "SLOT_LIGHT_SIBLING_TEMPLATE_EXPANSION_SKIPPED.tsv", [
            "scope", "normalized_path", "member_key", "member_name", "side", "body_offset", "record_start", "reference_offset",
            "endpoint", "header_layout_score", "reason",
        ], raw_rejected_rows)

        summary = {
            "type": "br_quartet_restoration_reflector_slot_light_sibling_template_expansion_evidence_summary",
            "format_version": 1,
            "tool_version": TOOL_VERSION,
            "source_stage101_tool_version": summary101.get("tool_version"),
            "source_stage103_tool_version": summary103.get("tool_version"),
            "source_stage79_tool_version": summary79.get("tool_version"),
            "source_stage81_tool_version": summary81.get("tool_version"),
            "sibling_G1E_G1EM_pair_rows": len(all_pairs),
            "sibling_payload_side_rows": len(all_pairs) * 2,
            "raw_aligned_body_hit_rows": sum(parse_int(row.get("raw_aligned_body_hits"), 0) for row in member_scan_rows),
            "format_valid_sibling_occurrence_rows": len(occurrence_rows),
            "known_stage101_occurrence_rows": len(known_rows),
            "additional_sibling_occurrence_rows": len(additional_rows),
            "additional_sibling_member_rows": len({(str(row["normalized_path"]), str(row["member_key"])) for row in additional_rows}),
            "technical_member_role_rows": len(role_rows),
            "expanded_technical_member_roles": expanded_roles,
            "paired_value_rows": len(discovered_values),
            "paired_values": discovered_values,
            "new_paired_values_outside_stage101_domain": new_values,
            "rejected_raw_body_hit_rows": len(raw_rejected_rows),
            "technical_leaf_storage_class": "paired_equal_finite_float_payload_leaves",
            "technical_leaf_domain_semantics_resolved": False,
            "brightness_semantics_confirmed": False,
            "censorship_semantics_confirmed": False,
            "prototype_candidate_rows": 0,
            "skipped_rows": 0,
            "status": "exact_non_leaf_sibling_template_expanded_across_bounded_G1E_G1EM_corpus_domain_semantics_unresolved",
            "next_action": "Upload this report. Continue only with a read-only comparison of additional sibling-template occurrences by section-header mode/flag, declared span, and surrounding anchored-block layout. Do not infer brightness/intensity and do not write G1E.",
            "parameters": {
                "parent_container_rows": EXPECTED_PARENT_CONTAINERS,
                "expected_sibling_pair_rows": EXPECTED_SIBLING_PAIRS,
                "record_dwords": RECORD_DWORDS,
                "non_leaf_body_relative_dwords": list(range(BODY_START_DWORD, BODY_END_DWORD_EXCLUSIVE)),
                "reference_relative_dword": REFERENCE_DWORD,
                "stage101_focal_context_sha256": focal_context_sha,
            },
            "policy": {
                "installed_game_modified": False,
                "render_payload_written": False,
                "pak_repacked": False,
                "core_registry_modified": False,
                "profile_activated": False,
                "runtime_validation_inferred": False,
                "technical_leaf_domain_semantics_inferred": False,
                "brightness_semantics_inferred": False,
                "censorship_semantics_inferred": False,
                "canary_track_modified": False,
                "full_proprietary_payloads_exported": False,
            },
        }
        (output / "SUMMARY.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        archive = reports / REPORT_NAME if create_archive else None
        if archive is not None:
            progress("creating compressed report archive")
            make_archive(output, archive)
        return output, archive, summary


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path, default=PROJECT_ROOT_DEFAULT)
    parser.add_argument("--no-report-archive", action="store_true")
    args = parser.parse_args(argv)
    try:
        output, archive, summary = build_report(args.project_root, create_archive=not args.no_report_archive)
    except Stage104Error as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print(f"Sibling G1E/G1EM pairs: {summary['sibling_G1E_G1EM_pair_rows']}")
    print(f"Format-valid template occurrences: {summary['format_valid_sibling_occurrence_rows']}")
    print(f"Known stage101 occurrences: {summary['known_stage101_occurrence_rows']}")
    print(f"Additional sibling occurrences: {summary['additional_sibling_occurrence_rows']}")
    print(f"Domain semantics resolved: {summary['technical_leaf_domain_semantics_resolved']}")
    print(f"Report directory: {output}")
    if archive is not None:
        print(f"Report: {archive}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
