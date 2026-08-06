#!/usr/bin/env python3
"""Stage 140: bounded exact-section content and KPS minimal-patch feasibility.

Consumes the locally verified stage-139 exact-layout/interface report and the
canonical stage-138 runtime integration. It rehydrates only the same seven
bounded effect/posteffect containers and:

* parses the three ordinal u32 tables and opaque body regions of every paired
  exact G1E section found by stage 139;
* classifies table-triplet and body deltas without treating table entries as
  authoritative record bindings or assigning leaf semantics;
* carries every changed segment outside or only partially covered by an exact
  section as an explicit opaque residual;
* examines only the sixteen KPS programs whose exact RDEF/signature interface
  and opcode inventory are equal, then tests whether their instruction
  envelopes permit a bounded target-side dword edit in principle.

The report is metadata-only. It builds no patch, authorizes no write, changes no
profile or registry, and does not runtime-validate anything.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import importlib.util
import json
import os
import shutil
import struct
import subprocess
import sys
import tempfile
from collections import Counter, defaultdict
from pathlib import Path, PurePosixPath
from typing import Any, Callable, Iterable, Mapping, Sequence

TOOL_VERSION = "0.1.58"
REPORT_DIR = "effect_posteffect_exact_section_content_kps_minimal_patch_feasibility_evidence"
REPORT_NAME = "BR_quartet_restoration_effect_posteffect_exact_section_content_kps_minimal_patch_feasibility_evidence.tar.zst"

STAGE139_NAME = "BR_quartet_restoration_effect_posteffect_broad_g1e_exact_layout_kps_interface_evidence.tar.zst"
STAGE139_SHA256 = "38a307d02d6de8918357aa137585492d41dc07587990b7c0ee973c38f9eb223d"
STAGE139_DIR = "effect_posteffect_broad_g1e_exact_layout_kps_interface_evidence"
STAGE139_SUMMARY_SHA256 = "88b05745c8a88b5c7c922b57dd0ccfcea04b09595eb7e38ed0d9e9666a1c8c55"

STAGE138_NAME = "BR_quartet_restoration_runtime_validation_canonical_integration_evidence.tar.zst"
STAGE138_SHA256 = "8d818ee5035ece1221efda5d66388b6480cef8cbf128374dec2027c002e04089"
STAGE138_DIR = "runtime_validation_canonical_integration_evidence"
STAGE138_SUMMARY_SHA256 = "233ae264468623c84d094ce794e7ce095730d72c61af7041439a97ad608d2cdb"

STAGE134_DIR = "effect_posteffect_namespace_member_saturation_evidence"
EXPECTED_FAMILIES = 7
EXPECTED_MEMBERS = 288
EXPECTED_MEMBERS_WITH_SECTIONS = 235
EXPECTED_SECTION_PAIRS = 261
EXPECTED_CHANGED_SEGMENTS = 57173
EXPECTED_FULLY_BOUND_SEGMENTS = 38614
EXPECTED_KPS_PATHS = 6
EXPECTED_KPS_PROGRAMS = 43
EXPECTED_KPS_STABLE_PROGRAMS = 16
EXPECTED_CONTAINERS = 7
MAX_EARC_BYTES = 1024 * 1024 * 1024
FORBIDDEN_EXTENSIONS = (
    ".pak", ".g1e", ".g1em", ".g1m", ".g1s", ".g1t", ".g1pf",
    ".elixir", ".elixir.gz", ".ebd", ".ebm", ".kps", ".dxbc",
)


class CollectorError(RuntimeError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise CollectorError(message)


def progress(message: str) -> None:
    print(f"[exact-section-kps-feasibility] {message}", file=sys.stderr, flush=True)


def version_tuple(value: str) -> tuple[int, ...]:
    try:
        return tuple(int(part) for part in value.strip().split("."))
    except ValueError as exc:
        raise CollectorError(f"invalid version: {value}") from exc


def parse_bool(value: object) -> bool:
    return str(value).strip().casefold() in {"1", "true", "yes", "y"}


def parse_int(value: object, default: int = 0) -> int:
    try:
        return int(str(value).strip(), 0)
    except (TypeError, ValueError):
        return default


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def stable_json_sha256(value: object) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def safe_relative(value: str, label: str) -> str:
    path = PurePosixPath(str(value).replace("\\", "/"))
    require(bool(path.parts), f"empty {label}")
    require(not path.is_absolute() and ".." not in path.parts, f"unsafe {label}: {value}")
    return path.as_posix()


def read_tsv(path: Path) -> list[dict[str, str]]:
    require(path.is_file(), f"missing TSV: {path}")
    with path.open(encoding="utf-8", newline="") as handle:
        return [dict(row) for row in csv.DictReader(handle, delimiter="\t")]


def write_tsv(path: Path, fields: Sequence[str], rows: Iterable[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(fields), delimiter="\t", lineterminator="\n", extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fields})


def atomic_json(path: Path, value: Mapping[str, Any]) -> None:
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def make_archive(source: Path, output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(output.name + ".tmp")
    temporary.unlink(missing_ok=True)
    completed = subprocess.run(
        ["tar", "--zstd", "-cf", str(temporary), "-C", str(source.parent), source.name],
        text=True, capture_output=True,
    )
    require(completed.returncode == 0, completed.stderr.strip() or "archive creation failed")
    os.replace(temporary, output)


def extract_report(archive: Path, destination: Path, expected_root: str) -> Path:
    listed = subprocess.run(["tar", "--zstd", "-tf", str(archive)], text=True, capture_output=True)
    require(listed.returncode == 0, listed.stderr.strip() or f"cannot list {archive}")
    names = [safe_relative(line, "report member") for line in listed.stdout.splitlines() if line.strip()]
    require(names, f"empty report archive: {archive}")
    require({PurePosixPath(name).parts[0] for name in names} == {expected_root}, f"unexpected report root: {archive}")
    destination.mkdir(parents=True, exist_ok=True)
    completed = subprocess.run(["tar", "--zstd", "-xf", str(archive), "-C", str(destination)], text=True, capture_output=True)
    require(completed.returncode == 0, completed.stderr.strip() or f"cannot extract {archive}")
    root = destination / expected_root
    require(root.is_dir(), f"missing extracted report root: {root}")
    return root


def locate_report(
    report_root: Path,
    temporary: Path,
    archive_name: str,
    archive_hash: str,
    root_name: str,
    summary_hash: str,
) -> tuple[Path, dict[str, Any], list[dict[str, Any]]]:
    archive = report_root / archive_name
    require(archive.is_file(), f"missing prerequisite report: {archive}")
    actual_archive_hash = sha256_file(archive)
    require(actual_archive_hash == archive_hash, f"unexpected {archive_name} SHA-256: {actual_archive_hash}")
    root = report_root / root_name
    if not root.is_dir():
        root = extract_report(archive, temporary / root_name, root_name)
    summary_path = root / "SUMMARY.json"
    require(summary_path.is_file(), f"missing prerequisite summary: {summary_path}")
    actual_summary_hash = sha256_file(summary_path)
    require(actual_summary_hash == summary_hash, f"unexpected {root_name} summary SHA-256: {actual_summary_hash}")
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    return root, summary, [
        {"input_id": root_name, "relative_path": archive_name, "sha256": actual_archive_hash, "verified": True},
        {"input_id": f"{root_name}_summary", "relative_path": f"{root_name}/SUMMARY.json", "sha256": actual_summary_hash, "verified": True},
    ]


def load_module(path: Path, name: str):
    require(path.is_file(), f"missing module: {path}")
    spec = importlib.util.spec_from_file_location(name, path)
    require(spec is not None and spec.loader is not None, f"cannot load module: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def section_components(payload: bytes, header: Mapping[str, Any]) -> dict[str, Any]:
    endpoint = parse_int(header.get("endpoint"), -1)
    declared_end = parse_int(header.get("declared_end"), -1)
    count = parse_int(header.get("count"), -1)
    b1 = parse_int(header.get("table_boundary_1"), -1)
    b2 = parse_int(header.get("table_boundary_2"), -1)
    b3 = parse_int(header.get("table_boundary_3"), -1)
    require(endpoint >= 0 and declared_end <= len(payload), "section bounds invalid")
    require(count >= 1 and 56 <= b1 <= b2 <= b3 <= declared_end - endpoint, "section table boundaries invalid")
    row_count = count - 1
    tables: list[list[int]] = []
    for start, end in ((endpoint + 56, endpoint + b1), (endpoint + b1, endpoint + b2), (endpoint + b2, endpoint + b3)):
        raw = payload[start:end]
        require(len(raw) == row_count * 4, "section table size/cardinality mismatch")
        tables.append(list(struct.unpack(f"<{row_count}I", raw)) if row_count else [])
    body = payload[endpoint + b3:declared_end]
    return {"tables": tables, "body": body, "row_count": row_count}


def changed_body_segments(stage84: Any, source: bytes, target: bytes) -> list[dict[str, Any]]:
    segments, _runs = stage84.build_alignment_segments(source, target)
    rows: list[dict[str, Any]] = []
    for index, segment in enumerate(segments):
        if segment["segment_type"] == "identical":
            continue
        ss = int(segment["source_start"]); se = int(segment["source_end_exclusive"])
        ts = int(segment["target_start"]); te = int(segment["target_end_exclusive"])
        rows.append({
            "body_segment_index": index,
            **segment,
            "source_segment_sha256": sha256_bytes(source[ss:se]),
            "target_segment_sha256": sha256_bytes(target[ts:te]),
        })
    return rows


def code_chunks(br: Any, payload: bytes, program: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        row["comparison_key"]: row
        for row in br.parse_dxbc_chunk_payloads(payload, dict(program))
        if row["fourcc"] in {"SHDR", "SHEX"}
    }


def instruction_envelope_rows(br: Any, chunk_payload: bytes) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    parsed = br.parse_dxbc_instruction_stream(chunk_payload)
    rows = [dict(row) for row in parsed.get("instructions", [])]
    return parsed, rows


def build_report(
    project_root: Path,
    *,
    report_root: Path | None = None,
    output_report_root: Path | None = None,
    workspace_root: Path | None = None,
    original_root: Path | None = None,
    quartet_root: Path | None = None,
    gust_pak_path: Path | None = None,
    create_archive: bool = True,
    timeout_seconds: int = 1800,
    verify_payload_hashes: bool = True,
    payload_provider: Callable[[str, str, str], bytes | None] | None = None,
    enforce_production_cardinality: bool = True,
) -> tuple[Path | None, dict[str, Any]]:
    project_root = project_root.resolve()
    version_path = project_root / "workstreams/quartet_restoration/VERSION"
    require(version_path.is_file(), f"missing VERSION: {version_path}")
    version = version_path.read_text(encoding="utf-8").strip()
    require(version_tuple(version) >= version_tuple(TOOL_VERSION), f"expected quartet_restoration {TOOL_VERSION} or newer, found {version}")

    report_root = (report_root or project_root / ".local/reports/quartet_restoration").resolve()
    output_report_root = (output_report_root or report_root).resolve()
    workspace_root = (workspace_root or project_root / ".local/build/quartet_restoration").resolve()
    output = output_report_root / REPORT_DIR
    archive = output_report_root / REPORT_NAME
    shutil.rmtree(output, ignore_errors=True)
    output.mkdir(parents=True, exist_ok=True)

    stage134 = load_module(project_root / "workstreams/quartet_restoration/134_collect_effect_posteffect_namespace_member_saturation_evidence.py", "stage140_stage134")
    stage139 = load_module(project_root / "workstreams/quartet_restoration/139_collect_effect_posteffect_broad_g1e_exact_layout_kps_interface_evidence.py", "stage140_stage139")
    stage84 = load_module(project_root / "workstreams/quartet_restoration/collect_reflector_slot_light_g1e_structure_evidence.py", "stage140_stage84")
    stage90 = load_module(project_root / "workstreams/quartet_restoration/collect_reflector_slot_light_target_section_layout_evidence.py", "stage140_stage90")
    stage133 = load_module(project_root / "workstreams/quartet_restoration/133_collect_shader_namespace_executable_signature_reflection_sweep_evidence.py", "stage140_stage133")
    br = stage134.load_br_tool(project_root)

    with tempfile.TemporaryDirectory(prefix="stage140-prereq-") as temporary_text:
        temporary = Path(temporary_text)
        root139, summary139, hashes139 = locate_report(report_root, temporary, STAGE139_NAME, STAGE139_SHA256, STAGE139_DIR, STAGE139_SUMMARY_SHA256)
        root138, summary138, hashes138 = locate_report(report_root, temporary, STAGE138_NAME, STAGE138_SHA256, STAGE138_DIR, STAGE138_SUMMARY_SHA256)
        root134 = report_root / STAGE134_DIR
        require(root134.is_dir(), f"missing extracted stage-134 report: {root134}")

        require(summary139.get("broad_g1e_structure_family_rows") == EXPECTED_FAMILIES, "stage-139 family count drift")
        require(summary139.get("broad_g1e_member_rows") == EXPECTED_MEMBERS, "stage-139 member count drift")
        require(summary139.get("g1e_members_with_any_exact_section_rows") == EXPECTED_MEMBERS_WITH_SECTIONS, "stage-139 exact-section member count drift")
        require(summary139.get("g1e_paired_exact_section_rows") == EXPECTED_SECTION_PAIRS, "stage-139 section-pair count drift")
        require(summary139.get("g1e_changed_segment_rows") == EXPECTED_CHANGED_SEGMENTS, "stage-139 changed-segment count drift")
        require(summary139.get("g1e_fully_bound_changed_segment_rows") == EXPECTED_FULLY_BOUND_SEGMENTS, "stage-139 bound-segment count drift")
        require(summary139.get("g1e_members_all_changed_segments_exactly_bound") == 0, "stage-139 unexpectedly resolved whole G1E member")
        require(summary139.get("kps_exact_path_rows") == EXPECTED_KPS_PATHS, "stage-139 KPS path count drift")
        require(summary139.get("kps_exact_program_rows") == EXPECTED_KPS_PROGRAMS, "stage-139 KPS program count drift")
        require(summary139.get("kps_exact_interface_equal_program_rows") == EXPECTED_KPS_STABLE_PROGRAMS, "stage-139 stable KPS interface count drift")
        require(summary139.get("kps_exact_opcode_inventory_equal_program_rows") == EXPECTED_KPS_STABLE_PROGRAMS, "stage-139 stable opcode inventory count drift")
        require(summary138.get("runtime_validated_profile_rows") == 1, "stage-138 runtime profile count drift")
        require(summary138.get("runtime_validated_profile_ids") == ["candidate_bathroom_river_containing_pak_static_inverse_062e39915e7d"], "stage-138 production profile drift")

        member_rows = read_tsv(root139 / "G1E_BROAD_FAMILY_MEMBER_LAYOUT.tsv")
        pair_rows139 = read_tsv(root139 / "G1E_EXACT_SECTION_PAIRS.tsv")
        segment_rows139 = read_tsv(root139 / "G1E_CHANGE_SEGMENT_SECTION_BINDING.tsv")
        kps_program_rows139 = read_tsv(root139 / "KPS_EXACT_PROGRAM_LAYOUT.tsv")
        carry_rows = read_tsv(root139 / "UNRESOLVED_G1EM_G1T_SHADER_CARRY_FORWARD.tsv")
        require(len(member_rows) == EXPECTED_MEMBERS, "stage-139 G1E member table drift")
        require(len(pair_rows139) == EXPECTED_SECTION_PAIRS, "stage-139 section pair table drift")
        require(len(segment_rows139) == EXPECTED_CHANGED_SEGMENTS, "stage-139 segment table drift")
        require(len(kps_program_rows139) == EXPECTED_KPS_PROGRAMS, "stage-139 KPS program table drift")
        stable_program_rows = [row for row in kps_program_rows139 if parse_bool(row["exact_interface_equal"]) and parse_bool(row["exact_opcode_inventory_equal"])]
        require(len(stable_program_rows) == EXPECTED_KPS_STABLE_PROGRAMS, "stage-139 stable KPS row drift")

        container_candidates = [
            {"namespace": row["namespace"], "normalized_path": row["normalized_path"]}
            for row in read_tsv(root134 / "EFFECT_POSTEFFECT_PATH_SUMMARY.tsv")
        ]
        require(len(container_candidates) == EXPECTED_CONTAINERS, "container count drift")

        payload_maps: dict[tuple[str, str], dict[str, dict[str, Any]]] = {}
        container_input_rows: list[dict[str, Any]] = []
        extraction_rows: list[dict[str, Any]] = []
        payload_bytes_read = 0
        if payload_provider is None:
            inventories = {side: stage134.load_inventory(project_root, side) for side in ("source", "target")}
            extraction_rows = stage134.ensure_extraction_cache(
                project_root=project_root,
                workspace_root=workspace_root,
                candidates=container_candidates,
                inventories=inventories,
                original_root=original_root,
                quartet_root=quartet_root,
                gust_pak_path=gust_pak_path,
                br=br,
                timeout_seconds=timeout_seconds,
            )
            for index, candidate in enumerate(sorted(container_candidates, key=lambda row: row["normalized_path"]), start=1):
                normalized = candidate["normalized_path"].casefold()
                progress(f"reading container {index}/{EXPECTED_CONTAINERS}: {normalized}")
                for side in ("source", "target"):
                    entry = inventories[side].get(normalized)
                    require(entry is not None, f"missing inventory entry: {side}:{normalized}")
                    local = br.inventory_workspace_file(workspace_root, side, "br1_assets", str(entry["archive"]), str(entry["path"]))
                    require(local.is_file(), f"missing cached input: {local}")
                    actual_hash = sha256_file(local)
                    if verify_payload_hashes:
                        require(actual_hash == str(entry["sha256"]), f"payload hash drift: {side}:{normalized}:{actual_hash}")
                        require(local.stat().st_size == int(entry["size"]), f"payload size drift: {side}:{normalized}")
                    parsed = br.read_earc_archive(local, maximum_bytes=MAX_EARC_BYTES, include_member_payloads=True)
                    payload_bytes_read += int(parsed["decoded_bytes"])
                    payload_maps[(side, normalized)] = {str(row["comparison_key"]): row for row in parsed["members"]}
                    container_input_rows.append({
                        "side": side,
                        "namespace": candidate["namespace"],
                        "normalized_path": normalized,
                        "container_archive": entry["archive"],
                        "input_size": local.stat().st_size,
                        "input_sha256": actual_hash,
                        "decoded_bytes": parsed["decoded_bytes"],
                        "decoded_sha256": parsed["decoded_sha256"],
                        "member_count": parsed["file_count"],
                        "payload_in_evidence": False,
                        "write_authorized": False,
                    })

        def get_payload(side: str, normalized: str, member_key: str) -> bytes | None:
            if payload_provider is not None:
                return payload_provider(side, normalized, member_key)
            row = payload_maps.get((side, normalized), {}).get(member_key)
            return bytes(row["payload"]) if row is not None else None

        pair_index139 = {
            (row["normalized_path"].casefold(), row["member_key"], parse_int(row["section_ordinal"], -1)): row
            for row in pair_rows139
        }
        segment_by_member: dict[tuple[str, str], list[dict[str, str]]] = defaultdict(list)
        for row in segment_rows139:
            segment_by_member[(row["normalized_path"].casefold(), row["member_key"])].append(row)

        section_summary_rows: list[dict[str, Any]] = []
        table_triplet_rows: list[dict[str, Any]] = []
        body_segment_rows: list[dict[str, Any]] = []
        body_transition_counter: Counter[tuple[str, str]] = Counter()
        body_transition_members: dict[tuple[str, str], set[str]] = defaultdict(set)
        member_scope_rows: list[dict[str, Any]] = []
        family_acc: dict[str, dict[str, Any]] = defaultdict(lambda: {
            "member_rows": 0, "members_with_sections": 0, "section_pairs": 0,
            "table_triplet_rows": 0, "changed_table_triplet_rows": 0,
            "body_changed_segment_rows": 0, "fully_bound_segments": 0,
            "partial_segments": 0, "outside_segments": 0,
        })

        for member_index, row in enumerate(sorted(member_rows, key=lambda item: (item["normalized_path"], item["member_key"])), start=1):
            if member_index == 1 or member_index % 40 == 0 or member_index == EXPECTED_MEMBERS:
                progress(f"section-content G1E {member_index}/{EXPECTED_MEMBERS}")
            normalized = row["normalized_path"].casefold(); key = row["member_key"]
            source = get_payload("source", normalized, key); target = get_payload("target", normalized, key)
            require(source is not None and target is not None, f"missing G1E payload pair: {normalized}:{key}")
            source_headers = stage139.scan_exact_section_headers(source, stage90.parse_section_header)
            target_headers = stage139.scan_exact_section_headers(target, stage90.parse_section_header)
            pairs = stage139.pair_section_headers(source_headers, target_headers)
            require(len(pairs) == parse_int(row["paired_exact_section_rows"]) + parse_int(row["unpaired_exact_section_rows"]), f"section pair cardinality drift: {normalized}:{key}")
            family_id = row["structure_family_id"]
            acc = family_acc[family_id]
            acc["member_rows"] += 1
            acc["members_with_sections"] += bool(pairs)
            acc["section_pairs"] += len(pairs)

            for pair in pairs:
                ordinal = parse_int(pair["section_ordinal"], -1)
                prior = pair_index139.get((normalized, key, ordinal))
                require(prior is not None, f"stage-139 section pair missing: {normalized}:{key}:{ordinal}")
                require(prior["section_pair_disposition"] == pair["section_pair_disposition"], f"section disposition drift: {normalized}:{key}:{ordinal}")
                require(pair["source_endpoint"] != "" and pair["target_endpoint"] != "", f"unexpected unpaired section: {normalized}:{key}:{ordinal}")
                source_header = source_headers[ordinal]; target_header = target_headers[ordinal]
                source_parts = section_components(source, source_header); target_parts = section_components(target, target_header)
                require(source_parts["row_count"] == target_parts["row_count"], f"table cardinality drift: {normalized}:{key}:{ordinal}")
                changed_triplets = 0
                for triplet_ordinal in range(source_parts["row_count"]):
                    svals = [source_parts["tables"][i][triplet_ordinal] for i in range(3)]
                    tvals = [target_parts["tables"][i][triplet_ordinal] for i in range(3)]
                    equal = svals == tvals
                    changed_triplets += not equal
                    table_triplet_rows.append({
                        "structure_family_id": family_id, "normalized_path": normalized, "member_key": key,
                        "member_name": row["member_name"], "section_ordinal": ordinal, "triplet_ordinal": triplet_ordinal,
                        "source_table1_u32_hex": f"0x{svals[0]:08x}", "target_table1_u32_hex": f"0x{tvals[0]:08x}",
                        "source_table2_u32_hex": f"0x{svals[1]:08x}", "target_table2_u32_hex": f"0x{tvals[1]:08x}",
                        "source_table3_u32_hex": f"0x{svals[2]:08x}", "target_table3_u32_hex": f"0x{tvals[2]:08x}",
                        "triplet_identical": equal,
                        "table_entries_treated_as_record_bindings": False,
                        "field_semantics_confirmed": False, "visual_or_censorship_semantics_confirmed": False,
                        "runtime_confirmed": False, "write_authorized": False,
                    })
                body_segments = changed_body_segments(stage84, source_parts["body"], target_parts["body"])
                for segment in body_segments:
                    body_segment_rows.append({
                        "structure_family_id": family_id, "normalized_path": normalized, "member_key": key,
                        "member_name": row["member_name"], "section_ordinal": ordinal, **segment,
                        "body_segment_treated_as_record_semantics": False,
                        "field_semantics_confirmed": False, "visual_or_censorship_semantics_confirmed": False,
                        "runtime_confirmed": False, "write_authorized": False,
                    })
                    if segment["segment_type"] == "same_size_replacement":
                        ss = int(segment["source_start"]); se = int(segment["source_end_exclusive"])
                        ts = int(segment["target_start"]); te = int(segment["target_end_exclusive"])
                        left = source_parts["body"][ss:se]; right = target_parts["body"][ts:te]
                        aligned = min(len(left), len(right)) // 4
                        for i in range(aligned):
                            sv = struct.unpack_from("<I", left, i * 4)[0]
                            tv = struct.unpack_from("<I", right, i * 4)[0]
                            if sv == tv:
                                continue
                            transition = (f"0x{sv:08x}", f"0x{tv:08x}")
                            body_transition_counter[transition] += 1
                            body_transition_members[transition].add(f"{normalized}::{key}")
                body_equal = source_parts["body"] == target_parts["body"]
                tables_equal = changed_triplets == 0
                if tables_equal and body_equal:
                    content_disposition = "tables_and_body_identical"
                elif tables_equal:
                    content_disposition = "tables_identical_body_delta"
                elif body_equal:
                    content_disposition = "table_delta_body_identical"
                else:
                    content_disposition = "table_and_body_delta"
                section_summary_rows.append({
                    "structure_family_id": family_id, "normalized_path": normalized, "member_key": key,
                    "member_name": row["member_name"], "section_ordinal": ordinal,
                    "section_pair_disposition": pair["section_pair_disposition"],
                    "table_triplet_rows": source_parts["row_count"], "changed_table_triplet_rows": changed_triplets,
                    "source_body_size": len(source_parts["body"]), "target_body_size": len(target_parts["body"]),
                    "body_changed_segment_rows": len(body_segments), "section_content_disposition": content_disposition,
                    "table_entries_treated_as_record_bindings": False, "body_treated_as_record_semantics": False,
                    "field_semantics_confirmed": False, "visual_or_censorship_semantics_confirmed": False,
                    "runtime_confirmed": False, "write_authorized": False,
                })
                acc["table_triplet_rows"] += source_parts["row_count"]
                acc["changed_table_triplet_rows"] += changed_triplets
                acc["body_changed_segment_rows"] += len(body_segments)

            member_segments = segment_by_member[(normalized, key)]
            fully = sum(parse_bool(item["fully_bound_by_exact_sections"]) for item in member_segments)
            partial = sum(item["source_section_binding"] == "partially_overlaps_exact_section" or item["target_section_binding"] == "partially_overlaps_exact_section" for item in member_segments)
            outside = sum(item["source_section_binding"] == "outside_exact_section_envelope" or item["target_section_binding"] == "outside_exact_section_envelope" for item in member_segments)
            acc["fully_bound_segments"] += fully; acc["partial_segments"] += partial; acc["outside_segments"] += outside
            if not pairs:
                residual_disposition = "opaque_no_exact_section_layout"
            elif fully == len(member_segments) and member_segments:
                residual_disposition = "all_changed_segments_exactly_bound"
            else:
                residual_disposition = "partial_exact_section_coverage_with_opaque_residual"
            member_scope_rows.append({
                "structure_family_id": family_id, "normalized_path": normalized, "member_key": key, "member_name": row["member_name"],
                "exact_section_rows": len(pairs), "changed_segment_rows": len(member_segments),
                "fully_bound_changed_segment_rows": fully, "partially_overlapping_changed_segment_rows": partial,
                "outside_exact_section_changed_segment_rows": outside, "residual_disposition": residual_disposition,
                "whole_member_layout_resolved": residual_disposition == "all_changed_segments_exactly_bound",
                "field_semantics_confirmed": False, "visual_or_censorship_semantics_confirmed": False,
                "runtime_confirmed": False, "write_authorized": False,
            })

        family_rows: list[dict[str, Any]] = []
        for family_id, acc in sorted(family_acc.items()):
            family_rows.append({
                "structure_family_id": family_id, **acc,
                "whole_family_layout_resolved": False,
                "field_semantics_confirmed": False, "visual_or_censorship_semantics_confirmed": False,
                "runtime_confirmed": False, "write_authorized": False,
            })

        transition_rows = [
            {
                "source_u32_hex": source_value, "target_u32_hex": target_value,
                "transition_rows": count, "member_rows": len(body_transition_members[(source_value, target_value)]),
                "body_dword_transition_treated_as_leaf_semantics": False,
                "field_semantics_confirmed": False, "visual_or_censorship_semantics_confirmed": False,
                "runtime_confirmed": False, "write_authorized": False,
            }
            for (source_value, target_value), count in sorted(body_transition_counter.items(), key=lambda item: (-item[1], item[0]))
        ]

        kps_paths = sorted({(row["normalized_path"].casefold(), row["member_key"], row["member_name"]) for row in kps_program_rows139})
        program_by_identity = {
            (row["normalized_path"].casefold(), row["member_key"], parse_int(row["program_pair_index"], -1)): row
            for row in stable_program_rows
        }
        kps_feasibility_rows: list[dict[str, Any]] = []
        kps_instruction_rows: list[dict[str, Any]] = []
        kps_dword_diff_rows: list[dict[str, Any]] = []
        for path_index, (normalized, key, member_name) in enumerate(kps_paths, start=1):
            progress(f"minimal-patch KPS {path_index}/{EXPECTED_KPS_PATHS}: {member_name}")
            source = get_payload("source", normalized, key); target = get_payload("target", normalized, key)
            require(target is not None, f"missing target KPS payload: {normalized}:{key}")
            source_programs = br.find_dxbc_programs(source or b"", label=f"source:{normalized}:{key}")
            target_programs = br.find_dxbc_programs(target, label=f"target:{normalized}:{key}")
            pairs = stage133.pair_programs(source_programs, target_programs)
            for pair_index, pair in enumerate(pairs):
                prior = program_by_identity.get((normalized, key, pair_index))
                if prior is None:
                    continue
                source_program = pair.get("source"); target_program = pair.get("target")
                require(source is not None and source_program is not None and target_program is not None, f"stable KPS program pair missing: {normalized}:{key}:{pair_index}")
                source_chunks = code_chunks(br, source, source_program); target_chunks = code_chunks(br, target, target_program)
                same_chunk_keys = sorted(source_chunks) == sorted(target_chunks) and bool(source_chunks)
                envelope_equal = same_chunk_keys
                changed_instruction_rows = 0; changed_dword_rows = 0; paired_instruction_rows = 0
                opcode_sequence_equal = True; length_sequence_equal = True; version_equal = True; declared_equal = True
                for chunk_key in sorted(set(source_chunks) | set(target_chunks)):
                    left = source_chunks.get(chunk_key); right = target_chunks.get(chunk_key)
                    if left is None or right is None:
                        envelope_equal = False; opcode_sequence_equal = False; length_sequence_equal = False
                        continue
                    source_parsed, source_instructions = instruction_envelope_rows(br, left["payload"])
                    target_parsed, target_instructions = instruction_envelope_rows(br, right["payload"])
                    version_equal &= source_parsed.get("version_token") == target_parsed.get("version_token")
                    declared_equal &= source_parsed.get("declared_dwords") == target_parsed.get("declared_dwords")
                    if len(source_instructions) != len(target_instructions):
                        envelope_equal = False; opcode_sequence_equal = False; length_sequence_equal = False
                    for instruction_index in range(max(len(source_instructions), len(target_instructions))):
                        left_i = source_instructions[instruction_index] if instruction_index < len(source_instructions) else None
                        right_i = target_instructions[instruction_index] if instruction_index < len(target_instructions) else None
                        if left_i is None or right_i is None:
                            kps_instruction_rows.append({
                                "normalized_path": normalized, "member_key": key, "member_name": member_name,
                                "program_pair_index": pair_index, "code_chunk_key": chunk_key, "instruction_index": instruction_index,
                                "source_opcode_id": left_i.get("opcode_id", "") if left_i else "", "target_opcode_id": right_i.get("opcode_id", "") if right_i else "",
                                "source_length_dwords": left_i.get("length_dwords", "") if left_i else "", "target_length_dwords": right_i.get("length_dwords", "") if right_i else "",
                                "instruction_envelope_equal": False, "instruction_payload_equal": False,
                                "field_semantics_confirmed": False, "visual_or_censorship_semantics_confirmed": False,
                                "runtime_confirmed": False, "write_authorized": False,
                            })
                            continue
                        paired_instruction_rows += 1
                        same_opcode = int(left_i["opcode_id"]) == int(right_i["opcode_id"])
                        same_length = int(left_i["length_dwords"]) == int(right_i["length_dwords"])
                        same_payload = list(left_i["words"]) == list(right_i["words"])
                        opcode_sequence_equal &= same_opcode; length_sequence_equal &= same_length
                        instruction_envelope_equal = same_opcode and same_length
                        envelope_equal &= instruction_envelope_equal
                        changed_instruction_rows += not same_payload
                        kps_instruction_rows.append({
                            "normalized_path": normalized, "member_key": key, "member_name": member_name,
                            "program_pair_index": pair_index, "code_chunk_key": chunk_key, "instruction_index": instruction_index,
                            "source_opcode_id": left_i["opcode_id"], "target_opcode_id": right_i["opcode_id"],
                            "source_length_dwords": left_i["length_dwords"], "target_length_dwords": right_i["length_dwords"],
                            "instruction_envelope_equal": instruction_envelope_equal, "instruction_payload_equal": same_payload,
                            "field_semantics_confirmed": False, "visual_or_censorship_semantics_confirmed": False,
                            "runtime_confirmed": False, "write_authorized": False,
                        })
                        if same_length:
                            for word_index, (sv, tv) in enumerate(zip(left_i["words"], right_i["words"])):
                                if sv == tv:
                                    continue
                                changed_dword_rows += 1
                                kps_dword_diff_rows.append({
                                    "normalized_path": normalized, "member_key": key, "member_name": member_name,
                                    "program_pair_index": pair_index, "code_chunk_key": chunk_key, "instruction_index": instruction_index,
                                    "instruction_dword_index": word_index, "word_role": "opcode_token" if word_index == 0 else "operand_or_immediate_word",
                                    "source_u32_hex": f"0x{int(sv):08x}", "target_u32_hex": f"0x{int(tv):08x}",
                                    "minimal_patch_word_candidate": instruction_envelope_equal,
                                    "field_semantics_confirmed": False, "visual_or_censorship_semantics_confirmed": False,
                                    "runtime_confirmed": False, "write_authorized": False,
                                })
                feasibility = (
                    "bounded_target_dword_edit_candidate"
                    if envelope_equal and version_equal and declared_equal and opcode_sequence_equal and length_sequence_equal
                    else "opcode_inventory_equal_but_instruction_envelope_delta"
                )
                kps_feasibility_rows.append({
                    "normalized_path": normalized, "member_key": key, "member_name": member_name,
                    "program_pair_index": pair_index, "classification": prior["classification"],
                    "exact_interface_equal": True, "exact_opcode_inventory_equal": True,
                    "code_chunk_keys_equal": same_chunk_keys, "version_tokens_equal": version_equal,
                    "declared_dwords_equal": declared_equal, "opcode_sequence_equal": opcode_sequence_equal,
                    "instruction_length_sequence_equal": length_sequence_equal,
                    "paired_instruction_rows": paired_instruction_rows, "changed_instruction_rows": changed_instruction_rows,
                    "changed_dword_rows": changed_dword_rows, "minimal_patch_feasibility": feasibility,
                    "patch_built": False, "write_authorized": False,
                    "field_semantics_confirmed": False, "visual_or_censorship_semantics_confirmed": False,
                    "runtime_confirmed": False,
                })

        require(len(kps_feasibility_rows) == EXPECTED_KPS_STABLE_PROGRAMS, f"stable KPS feasibility count drift: {len(kps_feasibility_rows)}")
        nonminimal_rows = [
            {**row, "minimal_patch_feasibility": "not_in_exact_interface_and_opcode_inventory_subset", "patch_built": False}
            for row in kps_program_rows139 if row not in stable_program_rows
        ]

        write_tsv(output / "INPUT_HASHES.tsv", ["input_id", "relative_path", "sha256", "verified"], hashes139 + hashes138)
        write_tsv(output / "EXTRACTION_INPUTS.tsv", ["side", "archive", "status"], extraction_rows)
        write_tsv(output / "CONTAINER_INPUTS.tsv", list(container_input_rows[0]) if container_input_rows else ["side"], container_input_rows)
        write_tsv(output / "G1E_EXACT_SECTION_CONTENT_SUMMARY.tsv", [
            "structure_family_id", "normalized_path", "member_key", "member_name", "section_ordinal", "section_pair_disposition",
            "table_triplet_rows", "changed_table_triplet_rows", "source_body_size", "target_body_size", "body_changed_segment_rows",
            "section_content_disposition", "table_entries_treated_as_record_bindings", "body_treated_as_record_semantics",
            "field_semantics_confirmed", "visual_or_censorship_semantics_confirmed", "runtime_confirmed", "write_authorized",
        ], section_summary_rows)
        write_tsv(output / "G1E_EXACT_SECTION_TABLE_TRIPLETS.tsv", [
            "structure_family_id", "normalized_path", "member_key", "member_name", "section_ordinal", "triplet_ordinal",
            "source_table1_u32_hex", "target_table1_u32_hex", "source_table2_u32_hex", "target_table2_u32_hex",
            "source_table3_u32_hex", "target_table3_u32_hex", "triplet_identical", "table_entries_treated_as_record_bindings",
            "field_semantics_confirmed", "visual_or_censorship_semantics_confirmed", "runtime_confirmed", "write_authorized",
        ], table_triplet_rows)
        write_tsv(output / "G1E_EXACT_SECTION_BODY_SEGMENTS.tsv", [
            "structure_family_id", "normalized_path", "member_key", "member_name", "section_ordinal", "body_segment_index",
            "segment_type", "source_start", "source_end_exclusive", "target_start", "target_end_exclusive", "source_length",
            "target_length", "size_delta", "shift_before", "shift_after", "source_segment_sha256", "target_segment_sha256",
            "body_segment_treated_as_record_semantics", "field_semantics_confirmed", "visual_or_censorship_semantics_confirmed",
            "runtime_confirmed", "write_authorized",
        ], body_segment_rows)
        write_tsv(output / "G1E_EXACT_SECTION_BODY_DWORD_TRANSITIONS.tsv", [
            "source_u32_hex", "target_u32_hex", "transition_rows", "member_rows", "body_dword_transition_treated_as_leaf_semantics",
            "field_semantics_confirmed", "visual_or_censorship_semantics_confirmed", "runtime_confirmed", "write_authorized",
        ], transition_rows)
        write_tsv(output / "G1E_MEMBER_EXACT_SECTION_RESIDUAL_SCOPE.tsv", [
            "structure_family_id", "normalized_path", "member_key", "member_name", "exact_section_rows", "changed_segment_rows",
            "fully_bound_changed_segment_rows", "partially_overlapping_changed_segment_rows", "outside_exact_section_changed_segment_rows",
            "residual_disposition", "whole_member_layout_resolved", "field_semantics_confirmed",
            "visual_or_censorship_semantics_confirmed", "runtime_confirmed", "write_authorized",
        ], member_scope_rows)
        write_tsv(output / "G1E_FAMILY_EXACT_SECTION_RESIDUAL_SUMMARY.tsv", [
            "structure_family_id", "member_rows", "members_with_sections", "section_pairs", "table_triplet_rows",
            "changed_table_triplet_rows", "body_changed_segment_rows", "fully_bound_segments", "partial_segments", "outside_segments",
            "whole_family_layout_resolved", "field_semantics_confirmed", "visual_or_censorship_semantics_confirmed",
            "runtime_confirmed", "write_authorized",
        ], family_rows)
        write_tsv(output / "KPS_MINIMAL_PATCH_FEASIBILITY.tsv", [
            "normalized_path", "member_key", "member_name", "program_pair_index", "classification", "exact_interface_equal",
            "exact_opcode_inventory_equal", "code_chunk_keys_equal", "version_tokens_equal", "declared_dwords_equal",
            "opcode_sequence_equal", "instruction_length_sequence_equal", "paired_instruction_rows", "changed_instruction_rows",
            "changed_dword_rows", "minimal_patch_feasibility", "patch_built", "field_semantics_confirmed",
            "visual_or_censorship_semantics_confirmed", "runtime_confirmed", "write_authorized",
        ], kps_feasibility_rows)
        write_tsv(output / "KPS_INSTRUCTION_ENVELOPE_COMPARISON.tsv", [
            "normalized_path", "member_key", "member_name", "program_pair_index", "code_chunk_key", "instruction_index",
            "source_opcode_id", "target_opcode_id", "source_length_dwords", "target_length_dwords", "instruction_envelope_equal",
            "instruction_payload_equal", "field_semantics_confirmed", "visual_or_censorship_semantics_confirmed",
            "runtime_confirmed", "write_authorized",
        ], kps_instruction_rows)
        write_tsv(output / "KPS_BOUNDED_DWORD_EDIT_CANDIDATES.tsv", [
            "normalized_path", "member_key", "member_name", "program_pair_index", "code_chunk_key", "instruction_index",
            "instruction_dword_index", "word_role", "source_u32_hex", "target_u32_hex", "minimal_patch_word_candidate",
            "field_semantics_confirmed", "visual_or_censorship_semantics_confirmed", "runtime_confirmed", "write_authorized",
        ], kps_dword_diff_rows)
        write_tsv(output / "KPS_NONMINIMAL_PROGRAM_CARRY_FORWARD.tsv", list(nonminimal_rows[0]) if nonminimal_rows else ["normalized_path"], nonminimal_rows)
        write_tsv(output / "UNRESOLVED_G1EM_G1T_SHADER_CARRY_FORWARD.tsv", list(carry_rows[0]), carry_rows)
        write_tsv(output / "PARSER_SKIPPED.tsv", ["scope", "identity", "reason"], [])

        residual_counts = Counter(row["residual_disposition"] for row in member_scope_rows)
        section_content_counts = Counter(row["section_content_disposition"] for row in section_summary_rows)
        feasibility_counts = Counter(row["minimal_patch_feasibility"] for row in kps_feasibility_rows)
        summary = {
            "type": "br_quartet_restoration_effect_posteffect_exact_section_content_kps_minimal_patch_feasibility_evidence_summary",
            "format_version": 1,
            "tool_version": TOOL_VERSION,
            "status": "exact_section_table_triplets_and_opaque_bodies_parsed_kps_minimal_patch_feasibility_bounded_semantics_unresolved_no_write",
            "stage139_report_sha256": STAGE139_SHA256,
            "stage138_report_sha256": STAGE138_SHA256,
            "runtime_validated_profile_rows_preserved": 1,
            "runtime_validated_profile_id_preserved": summary138["runtime_validated_profile_ids"][0],
            "g1e_structure_family_rows": len(family_rows),
            "g1e_member_rows": len(member_scope_rows),
            "g1e_section_pair_rows": len(section_summary_rows),
            "g1e_table_triplet_rows": len(table_triplet_rows),
            "g1e_changed_table_triplet_rows": sum(not parse_bool(row["triplet_identical"]) for row in table_triplet_rows),
            "g1e_body_changed_segment_rows": len(body_segment_rows),
            "g1e_body_dword_transition_family_rows": len(transition_rows),
            "g1e_member_residual_dispositions": dict(sorted(residual_counts.items())),
            "g1e_section_content_dispositions": dict(sorted(section_content_counts.items())),
            "g1e_whole_member_layout_resolved_rows": sum(parse_bool(row["whole_member_layout_resolved"]) for row in member_scope_rows),
            "g1e_whole_family_layout_resolved_rows": sum(parse_bool(row["whole_family_layout_resolved"]) for row in family_rows),
            "kps_exact_interface_opcode_stable_program_rows": len(kps_feasibility_rows),
            "kps_minimal_patch_feasibility": dict(sorted(feasibility_counts.items())),
            "kps_instruction_comparison_rows": len(kps_instruction_rows),
            "kps_changed_instruction_rows": sum(not parse_bool(row["instruction_payload_equal"]) for row in kps_instruction_rows),
            "kps_bounded_dword_edit_candidate_rows": len(kps_dword_diff_rows),
            "kps_nonminimal_program_rows": len(nonminimal_rows),
            "unresolved_g1em_g1t_shader_rows": len(carry_rows),
            "runtime_failed_shader_rows_preserved": sum(row["identity"] in {"data/x64/shader/heightfog.g1s", "data/x64/shader/swater.g1s"} for row in carry_rows),
            "payload_bytes_read": payload_bytes_read,
            "skipped_rows": 0,
            "field_semantics_confirmed_rows": 0,
            "visual_or_censorship_semantics_confirmed_rows": 0,
            "new_runtime_confirmed_rows": 0,
            "patch_built_rows": 0,
            "write_authorized_rows": 0,
            "policy": {
                "local_proprietary_payloads_read": payload_provider is None,
                "proprietary_payloads_in_report": False,
                "section_table_entries_treated_as_authoritative_record_bindings": False,
                "section_body_alignment_treated_as_record_or_leaf_semantics": False,
                "partial_exact_section_coverage_treated_as_whole_member_resolution": False,
                "kps_minimal_patch_feasibility_treated_as_patch_or_runtime_validation": False,
                "runtime_failed_shader_promoted": False,
                "event_profiles_promoted": False,
                "runtime_or_save_required": False,
                "pak_built_or_repacked": False,
                "installed_game_modified": False,
                "profile_or_registry_modified": False,
                "core_modified": False,
                "translation_modified": False,
                "legacy_dlc_modified": False,
                "git_modified": False,
            },
            "next_action": (
                "Retain all seven broad G1E families as unresolved because no whole member is covered by the exact-section layout. "
                "Use recurring table-triplet and opaque-body transition families only as calibration evidence for a separate format parser. "
                "For KPS, carry only programs classified as bounded_target_dword_edit_candidate into a no-write target-side prototype planner; "
                "keep every interface/sequence/inventory delta nonminimal and preserve both runtime-failed shaders as nonproduction."
            ),
        }
        atomic_json(output / "SUMMARY.json", summary)

    if enforce_production_cardinality:
        require(summary["g1e_structure_family_rows"] == EXPECTED_FAMILIES, "production family count mismatch")
        require(summary["g1e_member_rows"] == EXPECTED_MEMBERS, "production member count mismatch")
        require(summary["g1e_section_pair_rows"] == EXPECTED_SECTION_PAIRS, "production section count mismatch")
        require(summary["g1e_whole_member_layout_resolved_rows"] == 0, "whole G1E member unexpectedly resolved")
        require(summary["kps_exact_interface_opcode_stable_program_rows"] == EXPECTED_KPS_STABLE_PROGRAMS, "production KPS stable count mismatch")
        require(summary["kps_nonminimal_program_rows"] == EXPECTED_KPS_PROGRAMS - EXPECTED_KPS_STABLE_PROGRAMS, "production KPS carry count mismatch")

    forbidden = [path for path in output.rglob("*") if path.is_file() and any(path.name.casefold().endswith(ext) for ext in FORBIDDEN_EXTENSIONS)]
    require(not forbidden, f"forbidden payload files in report: {[path.name for path in forbidden]}")
    if create_archive:
        make_archive(output, archive)
        return archive, summary
    return None, summary


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--report-root", type=Path)
    parser.add_argument("--output-report-root", type=Path)
    parser.add_argument("--workspace-root", type=Path)
    parser.add_argument("--original-root", type=Path)
    parser.add_argument("--quartet-root", type=Path)
    parser.add_argument("--gust-pak", type=Path)
    parser.add_argument("--timeout-seconds", type=int, default=1800)
    parser.add_argument("--skip-payload-hash-verification", action="store_true")
    parser.add_argument("--no-archive", action="store_true")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    archive, summary = build_report(
        args.project_root,
        report_root=args.report_root,
        output_report_root=args.output_report_root,
        workspace_root=args.workspace_root,
        original_root=args.original_root,
        quartet_root=args.quartet_root,
        gust_pak_path=args.gust_pak,
        create_archive=not args.no_archive,
        timeout_seconds=args.timeout_seconds,
        verify_payload_hashes=not args.skip_payload_hash_verification,
    )
    print(json.dumps(summary, indent=2, sort_keys=True))
    if archive:
        print(f"[exact-section-kps-feasibility] report archive: {archive}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
