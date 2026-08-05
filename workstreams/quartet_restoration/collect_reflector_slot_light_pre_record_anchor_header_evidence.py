#!/usr/bin/env python3
"""Audit the 108-byte structures immediately preceding slot-light records.

Stage 93 found a dominant section-table binding in which signed table entries
land exactly 108 bytes before thirteen reference records.  The binding
distinguishes the duplicate target 75 occurrences but does not identify which
continues the Original 150 occurrence because the same target-side encoding
also covers the stable 30 prefix and has no source-side counterpart.

This read-only stage validates stages 91-93, rehydrates only the same four
bounded effect containers, verifies the dominant anchors against the actual
G1E/G1EM payloads, and inventories the 27 dwords between each anchor and its
record.  It classifies self-relative fields and compares raw and relocation-
normalized pre-record templates across candidate and neutral contexts.

Only offsets, numeric values, classifications, counts and SHA-256 hashes are
exported.  No G1E/G1EM, Elixir, PAK, registry or installed-game payload is
written, and no brightness or censorship semantics are inferred.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import importlib.util
import json
import math
import os
import struct
import subprocess
import sys
import tempfile
from collections import Counter, defaultdict
from pathlib import Path, PurePosixPath
from typing import Any, Callable, Iterable, Mapping, Sequence

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT_DEFAULT = SCRIPT_DIR.parent.parent

TOOL_VERSION = "0.1.8"
REPORT_NAME = "BR_quartet_restoration_reflector_slot_light_pre_record_anchor_header_evidence.tar.zst"
REPORT_DIR = "reflector_slot_light_pre_record_anchor_header_evidence"
STAGE79_DIR = "reflector_character_slot_render_member_evidence"
STAGE79_ARCHIVE = "BR_quartet_restoration_reflector_character_slot_render_member_evidence.tar.zst"
STAGE91_DIR = "reflector_slot_light_section_cardinality_record_role_evidence"
STAGE91_ARCHIVE = "BR_quartet_restoration_reflector_slot_light_section_cardinality_record_role_evidence.tar.zst"
STAGE92_DIR = "reflector_slot_light_record_occurrence_identity_evidence"
STAGE92_ARCHIVE = "BR_quartet_restoration_reflector_slot_light_record_occurrence_identity_evidence.tar.zst"
STAGE93_DIR = "reflector_slot_light_section_table_record_binding_evidence"
STAGE93_ARCHIVE = "BR_quartet_restoration_reflector_slot_light_section_table_record_binding_evidence.tar.zst"

EXPECTED_PARENT_CONTAINERS = 4
EXPECTED_SIBLING_PAIRS = 540
EXPECTED_REFERENCE_ROWS = 177
EXPECTED_TABLE_ENTRY_ROWS = 51
EXPECTED_DOMINANT_BINDING_ROWS = 13
PRE_RECORD_BYTES = 108
PRE_RECORD_DWORDS = PRE_RECORD_BYTES // 4
RECORD_DWORDS = 11
RECORD_BYTES = RECORD_DWORDS * 4
REFERENCE_DWORD = 10


class Stage94Error(RuntimeError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise Stage94Error(message)


def progress(message: str) -> None:
    print(f"[stage94] {message}", file=sys.stderr, flush=True)


def parse_int(value: Any, default: int = 0) -> int:
    try:
        text = str(value).strip()
        return int(text, 16) if text.casefold().startswith("0x") else int(text)
    except (TypeError, ValueError):
        return default


def parse_bool(value: Any) -> bool:
    return str(value).strip().casefold() in {"1", "true", "yes", "y"}


def signed_i32(value: int) -> int:
    value &= 0xFFFFFFFF
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
        raise Stage94Error(f"invalid JSON {path}: {exc}") from exc
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


def load_module(path: Path, name: str):
    require(path.is_file(), f"missing prerequisite collector: {path}")
    spec = importlib.util.spec_from_file_location(name, path)
    require(spec is not None and spec.loader is not None, f"cannot load module: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def stable_key(path: str, member_key: str) -> tuple[str, str]:
    return path.casefold(), member_key.casefold()


def stable_member_side(path: str, member_key: str, side: str) -> tuple[str, str, str]:
    return path.casefold(), member_key.casefold(), side.casefold()


def u32(payload: bytes, offset: int) -> int:
    require(offset >= 0 and offset + 4 <= len(payload) and offset % 4 == 0, f"invalid dword offset {offset}")
    return int.from_bytes(payload[offset:offset + 4], "little")


def float32(value: int) -> tuple[str, str]:
    result = struct.unpack("<f", int(value & 0xFFFFFFFF).to_bytes(4, "little"))[0]
    if math.isnan(result):
        return "nan", "nan"
    if math.isinf(result):
        return ("+inf" if result > 0 else "-inf"), "infinite"
    if result == 0.0:
        return "0", "zero"
    if abs(result) < 1e-30:
        return f"{result:.9g}", "subnormal_or_tiny"
    return f"{result:.9g}", "finite"


def relation_for_word(field_offset: int, value: int, *, endpoint: int, anchor: int, record_start: int, reference_offset: int) -> tuple[str, int]:
    displacement = signed_i32(value)
    target = field_offset + displacement
    relations = []
    for name, expected in (
        ("section_header", endpoint),
        ("pre_record_anchor", anchor),
        ("record_start", record_start),
        ("reference_field", reference_offset),
    ):
        if displacement and target == expected:
            relations.append(name)
    return ("|".join(relations) if relations else "", target)


def validate_stage91(root: Path) -> dict[str, Any]:
    summary = load_json(root / "SUMMARY.json")
    require(summary.get("type") == "br_quartet_restoration_reflector_slot_light_section_cardinality_record_role_evidence_summary", "stage91 type mismatch")
    require(summary.get("tool_version") == "0.1.5", "stage91 tool version mismatch")
    require(parse_int(summary.get("reference_record_rows"), -1) == EXPECTED_REFERENCE_ROWS, "stage91 reference count mismatch")
    require(parse_int(summary.get("section_table_entry_rows"), -1) == EXPECTED_TABLE_ENTRY_ROWS, "stage91 table-entry count mismatch")
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
    require(not parse_bool(summary.get("candidate_target_occurrence_identity_resolved")), "stage92 unexpectedly resolved target identity")
    require(parse_int(summary.get("prototype_candidate_rows"), -1) == 0, "stage92 unexpectedly authorized prototype")
    require(parse_int(summary.get("skipped_rows"), -1) == 0, "stage92 contains skipped rows")
    return summary


def validate_stage93(root: Path) -> dict[str, Any]:
    summary = load_json(root / "SUMMARY.json")
    require(summary.get("type") == "br_quartet_restoration_reflector_slot_light_section_table_record_binding_evidence_summary", "stage93 type mismatch")
    require(summary.get("tool_version") == "0.1.7", "stage93 tool version mismatch")
    require(parse_int(summary.get("reference_record_rows"), -1) == EXPECTED_REFERENCE_ROWS, "stage93 reference count mismatch")
    require(parse_int(summary.get("section_table_entry_rows"), -1) == EXPECTED_TABLE_ENTRY_ROWS, "stage93 table-entry count mismatch")
    require(parse_int(summary.get("dominant_record_relative_bytes"), 0) == -PRE_RECORD_BYTES, "stage93 dominant pre-record distance mismatch")
    require(parse_int(summary.get("dominant_record_relative_binding_rows"), -1) == EXPECTED_DOMINANT_BINDING_ROWS, "stage93 dominant binding count mismatch")
    require(parse_bool(summary.get("dominant_record_relative_offset_unique")), "stage93 dominant binding not unique")
    require(parse_bool(summary.get("target_table_binding_bulk_reencoding_supported")), "stage93 bulk-binding classification missing")
    require(not parse_bool(summary.get("candidate_target_occurrence_identity_resolved")), "stage93 unexpectedly resolved target identity")
    require(parse_int(summary.get("prototype_candidate_rows"), -1) == 0, "stage93 unexpectedly authorized prototype")
    require(not parse_bool(summary.get("brightness_semantics_confirmed")), "stage93 unexpectedly confirmed brightness")
    require(not parse_bool(summary.get("censorship_semantics_confirmed")), "stage93 unexpectedly confirmed censorship")
    require(parse_int(summary.get("skipped_rows"), -1) == 0, "stage93 contains skipped rows")
    return summary


def build_report(
    project_root: Path,
    *,
    create_archive: bool = True,
    report_root: Path | None = None,
    workspace_root: Path | None = None,
    rules_file: Path | None = None,
    maximum_earc_bytes: int = 512 * 1024 * 1024,
    container_loader: Callable[..., tuple[list[dict[str, Any]], list[dict[str, Any]]]] | None = None,
) -> tuple[Path, Path | None, dict[str, Any]]:
    project_root = project_root.resolve()
    reports = (report_root or project_root / ".local/reports/quartet_restoration").resolve()
    workspace = (workspace_root or project_root / ".local/build/quartet_restoration").resolve()
    require(reports.is_dir(), f"missing report root: {reports}")

    stage81 = load_module(project_root / "workstreams/quartet_restoration/collect_reflector_ringlight_control_callsite_evidence.py", "stage81_for_stage94")
    stage86 = load_module(project_root / "workstreams/quartet_restoration/collect_reflector_slot_light_shared_record_template_evidence.py", "stage86_for_stage94")

    progress("validating stage 79 and stage 91-93 reports")
    with tempfile.TemporaryDirectory(prefix="br-stage94-") as temporary_name:
        temporary = Path(temporary_name)
        stage79_root = locate(reports, STAGE79_DIR, STAGE79_ARCHIVE, temporary / "79")
        stage91_root = locate(reports, STAGE91_DIR, STAGE91_ARCHIVE, temporary / "91")
        stage92_root = locate(reports, STAGE92_DIR, STAGE92_ARCHIVE, temporary / "92")
        stage93_root = locate(reports, STAGE93_DIR, STAGE93_ARCHIVE, temporary / "93")
        stage81.validate_stage79(stage79_root)
        summary91 = validate_stage91(stage91_root)
        summary92 = validate_stage92(stage92_root)
        summary93 = validate_stage93(stage93_root)

        occurrence_rows = read_tsv(stage92_root / "SLOT_LIGHT_RECORD_OCCURRENCE_INVENTORY.tsv")
        binding_rows = read_tsv(stage93_root / "SLOT_LIGHT_SECTION_TABLE_RECORD_BINDING_CANDIDATES.tsv")
        decision_rows = read_tsv(stage93_root / "SLOT_LIGHT_TABLE_BINDING_IDENTITY_DECISION.tsv")
        cardinality_rows = read_tsv(stage91_root / "SLOT_LIGHT_SECTION_CARDINALITY.tsv")
        require(len(occurrence_rows) == EXPECTED_REFERENCE_ROWS, "stage92 occurrence inventory count mismatch")
        require(len(decision_rows) == 1 and not parse_bool(decision_rows[0].get("occurrence_identity_resolved")), "stage93 identity decision mismatch")

        dominant_rows = [row for row in binding_rows if parse_bool(row.get("exact_dominant_binding"))]
        require(len(dominant_rows) == EXPECTED_DOMINANT_BINDING_ROWS, "stage93 dominant binding row count mismatch")
        endpoint_by_member_side = {
            stable_member_side(row.get("normalized_path", ""), row.get("member_key", ""), row.get("side", "")): parse_int(row.get("endpoint"), -1)
            for row in cardinality_rows
        }

        parent_scope = stage81.select_parent_scope(stage79_root)
        actual_rules = rules_file or project_root / "titles/blue_reflection/modules/quartet_restoration/mappings/effect_material_rules.tsv"
        loader = container_loader or stage81.load_parent_containers
        progress("rehydrating the four bounded parent effect containers")
        containers, skipped = loader(
            scope_rows=parent_scope,
            workspace_root=workspace,
            report_root=reports,
            rules_file=actual_rules,
            maximum_earc_bytes=maximum_earc_bytes,
        )
        require(not skipped, f"parent container loader skipped {len(skipped)} rows")
        require(len(containers) == EXPECTED_PARENT_CONTAINERS, f"expected {EXPECTED_PARENT_CONTAINERS} parent containers, found {len(containers)}")
        pair_by_key, all_pairs = stage86.index_pairs(containers)
        require(len(all_pairs) == EXPECTED_SIBLING_PAIRS, f"expected {EXPECTED_SIBLING_PAIRS} sibling G1E/G1EM pairs, found {len(all_pairs)}")
        progress(f"indexed {len(all_pairs)} sibling G1E/G1EM payload pairs")

        dominant_by_occurrence: dict[tuple[str, str, str, int], dict[str, str]] = {}
        for row in dominant_rows:
            key = (
                row.get("normalized_path", "").casefold(),
                row.get("member_key", "").casefold(),
                row.get("side", "").casefold(),
                parse_int(row.get("best_record_start"), -1),
            )
            require(key not in dominant_by_occurrence, f"duplicate dominant binding occurrence: {key}")
            dominant_by_occurrence[key] = row

        focal_rows = [row for row in occurrence_rows if parse_bool(row.get("is_focal_family"))]
        require(focal_rows, "stage92 focal occurrence inventory is empty")
        audit_rows: list[dict[str, Any]] = []
        dword_rows: list[dict[str, Any]] = []
        skipped_rows: list[dict[str, Any]] = []
        normalized_roles: dict[str, set[str]] = defaultdict(set)
        normalized_members: dict[str, set[str]] = defaultdict(set)
        raw_groups: Counter[str] = Counter()

        for index, occurrence in enumerate(focal_rows, 1):
            path = occurrence.get("normalized_path", "")
            member_key = occurrence.get("member_key", "")
            side = occurrence.get("side", "").casefold()
            pair = pair_by_key.get(stable_key(path, member_key))
            require(pair is not None, f"missing focal payload pair: {path} {member_key}")
            require(side in {"source", "target"}, f"invalid occurrence side: {side}")
            payload = pair[f"{side}_payload"]
            record_start = parse_int(occurrence.get("record_start"), -1)
            reference_offset = parse_int(occurrence.get("reference_offset"), -1)
            anchor = record_start - PRE_RECORD_BYTES
            endpoint = endpoint_by_member_side.get(stable_member_side(path, member_key, side), -1)
            if anchor < 0 or anchor % 4 or record_start + RECORD_BYTES > len(payload):
                skipped_rows.append({
                    "scope": "occurrence", "member_name": occurrence.get("member_name", ""), "side": side,
                    "offset": record_start, "reason": "pre_record_window_out_of_bounds_or_unaligned",
                })
                continue
            require(reference_offset == record_start + REFERENCE_DWORD * 4, f"reference offset does not end record: {pair['member_name']} {side}@{record_start}")
            block = payload[anchor:record_start]
            require(len(block) == PRE_RECORD_BYTES, "pre-record block length mismatch")
            normalized = bytearray(block)
            relation_rows = 0
            relative_targets: Counter[str] = Counter()
            for relative in range(PRE_RECORD_DWORDS):
                field_offset = anchor + relative * 4
                value = u32(payload, field_offset)
                relation, target = relation_for_word(
                    field_offset, value, endpoint=endpoint, anchor=anchor,
                    record_start=record_start, reference_offset=reference_offset,
                )
                if relation:
                    relation_rows += 1
                    for name in relation.split("|"):
                        relative_targets[name] += 1
                    normalized[relative * 4:relative * 4 + 4] = b"\0\0\0\0"
                float_text, float_status = float32(value)
                dword_rows.append({
                    "cluster_role": occurrence.get("cluster_role", ""),
                    "normalized_path": path,
                    "member_key": member_key,
                    "member_name": occurrence.get("member_name", pair["member_name"]),
                    "side": side,
                    "reference_index": occurrence.get("reference_index", ""),
                    "variant_label": occurrence.get("variant_label", ""),
                    "anchor": anchor,
                    "record_start": record_start,
                    "relative_dword": relative,
                    "field_offset": field_offset,
                    "u32_hex": f"0x{value:08x}",
                    "i32": signed_i32(value),
                    "float32": float_text,
                    "float_status": float_status,
                    "field_relative_target": target,
                    "relative_relation": relation,
                    "normalized_as_relocation": bool(relation),
                })
            raw_hash = sha256(block)
            normalized_hash = sha256(bytes(normalized))
            raw_groups[raw_hash] += 1
            normalized_roles[normalized_hash].add(occurrence.get("cluster_role", ""))
            normalized_members[normalized_hash].add(occurrence.get("member_name", pair["member_name"]))
            bind_key = (path.casefold(), member_key.casefold(), side, record_start)
            binding = dominant_by_occurrence.get(bind_key)
            binding_anchor = parse_int(binding.get("signed_anchor"), -1) if binding else -1
            audit_rows.append({
                "cluster_role": occurrence.get("cluster_role", ""),
                "normalized_path": path,
                "member_key": member_key,
                "member_name": occurrence.get("member_name", pair["member_name"]),
                "side": side,
                "reference_index": occurrence.get("reference_index", ""),
                "variant_label": occurrence.get("variant_label", ""),
                "endpoint": endpoint,
                "anchor": anchor,
                "record_start": record_start,
                "reference_offset": reference_offset,
                "anchor_to_record_bytes": record_start - anchor,
                "anchor_aligned": anchor % 4 == 0,
                "window_in_bounds": True,
                "dominant_table_binding": binding is not None,
                "binding_table_index": binding.get("table_index", "") if binding else "",
                "binding_entry_index": binding.get("entry_index", "") if binding else "",
                "binding_signed_anchor": binding_anchor if binding else "",
                "binding_anchor_exact": bool(binding and binding_anchor == anchor),
                "raw_pre_record_sha256": raw_hash,
                "normalized_pre_record_sha256": normalized_hash,
                "self_relative_dword_rows": relation_rows,
                "relative_to_section_header_rows": relative_targets.get("section_header", 0),
                "relative_to_anchor_rows": relative_targets.get("pre_record_anchor", 0),
                "relative_to_record_start_rows": relative_targets.get("record_start", 0),
                "relative_to_reference_field_rows": relative_targets.get("reference_field", 0),
            })
            if index % 25 == 0 or index == len(focal_rows):
                progress(f"audited pre-record occurrence {index}/{len(focal_rows)}")

        require(not skipped_rows, f"pre-record audit skipped {len(skipped_rows)} focal occurrences")
        require(sum(parse_bool(row.get("dominant_table_binding")) for row in audit_rows) == EXPECTED_DOMINANT_BINDING_ROWS, "dominant occurrence coverage mismatch")
        require(all(parse_bool(row.get("binding_anchor_exact")) for row in audit_rows if parse_bool(row.get("dominant_table_binding"))), "dominant table anchor mismatch")

        audit_by_key = {
            (row["normalized_path"].casefold(), row["member_key"].casefold(), row["side"].casefold(), parse_int(row["record_start"], -1)): row
            for row in audit_rows
        }
        peer_rows: list[dict[str, Any]] = []
        occurrence_by_member_start: dict[tuple[str, str, int], dict[str, dict[str, Any]]] = defaultdict(dict)
        for row in audit_rows:
            occurrence_by_member_start[(row["normalized_path"].casefold(), row["member_key"].casefold(), parse_int(row["record_start"], -1))][row["side"]] = row
        for (_path, _key, start), peers in sorted(occurrence_by_member_start.items()):
            if set(peers) != {"source", "target"}:
                continue
            source = peers["source"]
            target = peers["target"]
            peer_rows.append({
                "member_name": source["member_name"],
                "record_start": start,
                "source_variant_label": source["variant_label"],
                "target_variant_label": target["variant_label"],
                "raw_pre_record_exact": source["raw_pre_record_sha256"] == target["raw_pre_record_sha256"],
                "normalized_pre_record_exact": source["normalized_pre_record_sha256"] == target["normalized_pre_record_sha256"],
                "source_raw_sha256": source["raw_pre_record_sha256"],
                "target_raw_sha256": target["raw_pre_record_sha256"],
                "source_normalized_sha256": source["normalized_pre_record_sha256"],
                "target_normalized_sha256": target["normalized_pre_record_sha256"],
            })

        chain_rows: list[dict[str, Any]] = []
        grouped_bindings: dict[tuple[str, str, str, int], list[dict[str, str]]] = defaultdict(list)
        for row in dominant_rows:
            grouped_bindings[(row.get("normalized_path", "").casefold(), row.get("member_key", "").casefold(), row.get("side", "").casefold(), parse_int(row.get("table_index"), -1))].append(row)
        for group_key, rows in sorted(grouped_bindings.items()):
            rows.sort(key=lambda row: parse_int(row.get("entry_index"), -1))
            previous: dict[str, str] | None = None
            for row in rows:
                current_anchor = parse_int(row.get("signed_anchor"), -1)
                current_record = parse_int(row.get("best_record_start"), -1)
                current_entry_offset = parse_int(row.get("entry_absolute_offset"), -1)
                current_entry_value = parse_int(row.get("entry_i32"), 0)
                if previous is None:
                    delta_entry_offset = delta_entry_value = delta_anchor = delta_record = ""
                    chain_exact = ""
                else:
                    delta_entry_offset = current_entry_offset - parse_int(previous.get("entry_absolute_offset"), -1)
                    delta_entry_value = current_entry_value - parse_int(previous.get("entry_i32"), 0)
                    delta_anchor = current_anchor - parse_int(previous.get("signed_anchor"), -1)
                    delta_record = current_record - parse_int(previous.get("best_record_start"), -1)
                    chain_exact = delta_anchor == delta_record == delta_entry_offset + delta_entry_value
                chain_rows.append({
                    "normalized_path": row.get("normalized_path", ""),
                    "member_key": row.get("member_key", ""),
                    "member_name": row.get("member_name", ""),
                    "side": row.get("side", ""),
                    "table_index": row.get("table_index", ""),
                    "entry_index": row.get("entry_index", ""),
                    "entry_absolute_offset": current_entry_offset,
                    "entry_i32": current_entry_value,
                    "signed_anchor": current_anchor,
                    "record_start": current_record,
                    "anchor_to_record_bytes": current_record - current_anchor,
                    "delta_entry_offset": delta_entry_offset,
                    "delta_entry_value": delta_entry_value,
                    "delta_signed_anchor": delta_anchor,
                    "delta_record_start": delta_record,
                    "chain_delta_exact": chain_exact,
                })
                previous = row

        template_rows: list[dict[str, Any]] = []
        by_normalized: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for row in audit_rows:
            by_normalized[row["normalized_pre_record_sha256"]].append(row)
        for template_hash, rows in sorted(by_normalized.items(), key=lambda item: (-len(item[1]), item[0])):
            template_rows.append({
                "normalized_pre_record_sha256": template_hash,
                "occurrence_rows": len(rows),
                "raw_template_rows": len({row["raw_pre_record_sha256"] for row in rows}),
                "cluster_roles": " | ".join(sorted({row["cluster_role"] for row in rows})),
                "member_names": " | ".join(sorted({row["member_name"] for row in rows})),
                "sides": " | ".join(sorted({row["side"] for row in rows})),
                "variant_labels": " | ".join(sorted({row["variant_label"] for row in rows})),
                "spans_candidate_and_neutral": {row["cluster_role"] for row in rows} >= {"candidate_ringlight", "neutral_control"},
            })

        candidate_rows = [row for row in audit_rows if row["cluster_role"] == "candidate_ringlight"]
        candidate_sequence_rows = sorted(candidate_rows, key=lambda row: (row["side"], parse_int(row["record_start"], -1)))
        duplicate_target_75 = [row for row in candidate_sequence_rows if row["side"] == "target" and row["variant_label"] == "equal_float_75"]
        duplicate_target_75_distinct_raw = len({row["raw_pre_record_sha256"] for row in duplicate_target_75}) == len(duplicate_target_75) if duplicate_target_75 else False
        duplicate_target_75_distinct_normalized = len({row["normalized_pre_record_sha256"] for row in duplicate_target_75}) == len(duplicate_target_75) if duplicate_target_75 else False
        common_templates = [row for row in template_rows if parse_bool(row.get("spans_candidate_and_neutral"))]
        exact_chain_rows = [row for row in chain_rows if row.get("chain_delta_exact") != "" and parse_bool(row.get("chain_delta_exact"))]
        chain_comparison_rows = [row for row in chain_rows if row.get("chain_delta_exact") != ""]

        summary = {
            "type": "br_quartet_restoration_reflector_slot_light_pre_record_anchor_header_evidence_summary",
            "format_version": 1,
            "tool_version": TOOL_VERSION,
            "source_stage91_tool_version": summary91.get("tool_version"),
            "source_stage92_tool_version": summary92.get("tool_version"),
            "source_stage93_tool_version": summary93.get("tool_version"),
            "status": "stage93_binding_valid_108_byte_pre_record_anchor_geometry_confirmed_header_role_and_duplicate_target_identity_unresolved",
            "sibling_G1E_G1EM_member_rows": len(all_pairs),
            "focal_occurrence_rows": len(audit_rows),
            "pre_record_dword_rows": len(dword_rows),
            "dominant_binding_rows": len(dominant_rows),
            "dominant_binding_anchor_exact_rows": sum(parse_bool(row.get("binding_anchor_exact")) for row in audit_rows),
            "dominant_anchor_to_record_bytes": PRE_RECORD_BYTES,
            "table_anchor_chain_comparison_rows": len(chain_comparison_rows),
            "table_anchor_chain_exact_rows": len(exact_chain_rows),
            "same_offset_source_target_peer_rows": len(peer_rows),
            "same_offset_raw_pre_record_exact_rows": sum(parse_bool(row.get("raw_pre_record_exact")) for row in peer_rows),
            "same_offset_normalized_pre_record_exact_rows": sum(parse_bool(row.get("normalized_pre_record_exact")) for row in peer_rows),
            "normalized_pre_record_template_groups": len(template_rows),
            "cross_candidate_neutral_normalized_template_groups": len(common_templates),
            "self_relative_dword_rows": sum(parse_int(row.get("self_relative_dword_rows"), 0) for row in audit_rows),
            "candidate_target_duplicate_75_rows": len(duplicate_target_75),
            "candidate_target_duplicate_75_raw_preambles_distinct": duplicate_target_75_distinct_raw,
            "candidate_target_duplicate_75_normalized_preambles_distinct": duplicate_target_75_distinct_normalized,
            "pre_record_anchor_geometry_confirmed": len(dominant_rows) == EXPECTED_DOMINANT_BINDING_ROWS and all(parse_bool(row.get("binding_anchor_exact")) for row in audit_rows if parse_bool(row.get("dominant_table_binding"))),
            "pre_record_header_role_resolved": False,
            "candidate_target_occurrence_identity_resolved": False,
            "technical_leaf_semantics_resolved": False,
            "prototype_candidate_rows": 0,
            "brightness_semantics_confirmed": False,
            "censorship_semantics_confirmed": False,
            "skipped_rows": len(skipped_rows),
            "parameters": {
                "pre_record_bytes": PRE_RECORD_BYTES,
                "pre_record_dwords": PRE_RECORD_DWORDS,
                "record_dwords": RECORD_DWORDS,
                "reference_dword": REFERENCE_DWORD,
                "normalization": "zero only dwords whose signed field-relative target equals section header, pre-record anchor, record start or reference field",
                "identity_gate": "pre-record structure may resolve duplicate occurrence identity only if one target 75 has an unambiguous source-side normalized preamble counterpart or a uniquely inserted preamble class",
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
            "next_action": "Upload this report. The dominant table entries must land exactly 108 bytes before their records, but the 27-dword structures must be compared before assigning a header role. If duplicate target identity remains unresolved, continue only with a read-only internal-field/ordinal audit of the pre-record structures; do not write G1E or infer brightness/censorship.",
        }

        output = reports / REPORT_DIR
        if output.exists():
            for child in output.iterdir():
                child.unlink() if child.is_file() or child.is_symlink() else None
        output.mkdir(parents=True, exist_ok=True)
        write_tsv(output / "SLOT_LIGHT_PRE_RECORD_ANCHOR_AUDIT.tsv", [
            "cluster_role", "normalized_path", "member_key", "member_name", "side", "reference_index", "variant_label",
            "endpoint", "anchor", "record_start", "reference_offset", "anchor_to_record_bytes", "anchor_aligned", "window_in_bounds",
            "dominant_table_binding", "binding_table_index", "binding_entry_index", "binding_signed_anchor", "binding_anchor_exact",
            "raw_pre_record_sha256", "normalized_pre_record_sha256", "self_relative_dword_rows", "relative_to_section_header_rows",
            "relative_to_anchor_rows", "relative_to_record_start_rows", "relative_to_reference_field_rows",
        ], audit_rows)
        write_tsv(output / "SLOT_LIGHT_PRE_RECORD_ANCHOR_DWORDS.tsv", [
            "cluster_role", "normalized_path", "member_key", "member_name", "side", "reference_index", "variant_label",
            "anchor", "record_start", "relative_dword", "field_offset", "u32_hex", "i32", "float32", "float_status",
            "field_relative_target", "relative_relation", "normalized_as_relocation",
        ], dword_rows)
        write_tsv(output / "SLOT_LIGHT_PRE_RECORD_TEMPLATE_GROUPS.tsv", [
            "normalized_pre_record_sha256", "occurrence_rows", "raw_template_rows", "cluster_roles", "member_names", "sides",
            "variant_labels", "spans_candidate_and_neutral",
        ], template_rows)
        write_tsv(output / "SLOT_LIGHT_PRE_RECORD_SOURCE_TARGET_PEERS.tsv", [
            "member_name", "record_start", "source_variant_label", "target_variant_label", "raw_pre_record_exact",
            "normalized_pre_record_exact", "source_raw_sha256", "target_raw_sha256", "source_normalized_sha256", "target_normalized_sha256",
        ], peer_rows)
        write_tsv(output / "SLOT_LIGHT_CANDIDATE_PRE_RECORD_SEQUENCE.tsv", [
            "cluster_role", "normalized_path", "member_key", "member_name", "side", "reference_index", "variant_label", "endpoint",
            "anchor", "record_start", "reference_offset", "dominant_table_binding", "raw_pre_record_sha256", "normalized_pre_record_sha256",
            "self_relative_dword_rows",
        ], candidate_sequence_rows)
        write_tsv(output / "SLOT_LIGHT_TABLE_ENTRY_ANCHOR_CHAIN.tsv", [
            "normalized_path", "member_key", "member_name", "side", "table_index", "entry_index", "entry_absolute_offset", "entry_i32",
            "signed_anchor", "record_start", "anchor_to_record_bytes", "delta_entry_offset", "delta_entry_value", "delta_signed_anchor",
            "delta_record_start", "chain_delta_exact",
        ], chain_rows)
        write_tsv(output / "SLOT_LIGHT_PRE_RECORD_HEADER_DECISION.tsv", [
            "question", "answer", "classification",
        ], [
            {
                "question": "do all dominant table bindings land exactly 108 bytes before their selected records",
                "answer": summary["pre_record_anchor_geometry_confirmed"],
                "classification": "dominant_pre_record_anchor_geometry_confirmed",
            },
            {
                "question": "is the 108-byte structure role formally resolved as a header",
                "answer": False,
                "classification": "role_unresolved_pending_internal_field_and_cross_context_template_audit",
            },
            {
                "question": "which duplicate target 75 continues the Original 150 occurrence",
                "answer": False,
                "classification": "target_occurrence_identity_unresolved",
            },
        ])
        write_tsv(output / "SLOT_LIGHT_PRE_RECORD_ANCHOR_HEADER_SKIPPED.tsv", ["scope", "member_name", "side", "offset", "reason"], skipped_rows)
        (output / "SUMMARY.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")

        archive: Path | None = None
        if create_archive:
            archive = reports / REPORT_NAME
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
    except Stage94Error as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print(f"Pre-record audit: {output}")
    if archive:
        print(f"Report: {archive}")
    print(f"Dominant anchors exact: {summary['dominant_binding_anchor_exact_rows']}/{summary['dominant_binding_rows']}")
    print(f"Header role resolved: {summary['pre_record_header_role_resolved']}")
    print(f"Target occurrence identity resolved: {summary['candidate_target_occurrence_identity_resolved']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
