#!/usr/bin/env python3
"""Audit section cardinality and the structural role of shared slot-light records.

Stage 90 resolved the focal relocation fields as signed dword-start-relative
references to reproducible 56-byte section headers. It also showed that the
candidate and neutral 11-dword records are the same source template and the
same target template after masking only the relocation field. This read-only
stage parses the three count-dependent header tables, inventories every inbound
reference record, and tests whether the shared 150 -> 75 record transition is
independent of section-cardinality changes.

Only technical metadata, offsets, integer/float renderings and SHA-256 hashes
are exported. No G1E/G1EM, Elixir, PAK, registry or installed-game payload is
written, and no brightness or censorship semantics are inferred.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import importlib.util
import json
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

TOOL_VERSION = "0.1.5"
REPORT_NAME = "BR_quartet_restoration_reflector_slot_light_section_cardinality_record_role_evidence.tar.zst"
REPORT_DIR = "reflector_slot_light_section_cardinality_record_role_evidence"
STAGE90_DIR = "reflector_slot_light_target_section_layout_evidence"
STAGE90_ARCHIVE = "BR_quartet_restoration_reflector_slot_light_target_section_layout_evidence.tar.zst"
STAGE89_DIR = "reflector_slot_light_reference_target_header_evidence"
STAGE89_ARCHIVE = "BR_quartet_restoration_reflector_slot_light_reference_target_header_evidence.tar.zst"
STAGE87_DIR = "reflector_slot_light_local_change_island_evidence"
STAGE87_ARCHIVE = "BR_quartet_restoration_reflector_slot_light_local_change_island_evidence.tar.zst"
STAGE79_DIR = "reflector_character_slot_render_member_evidence"
STAGE79_ARCHIVE = "BR_quartet_restoration_reflector_character_slot_render_member_evidence.tar.zst"
EXPECTED_PARENT_CONTAINERS = 4
EXPECTED_SIBLING_PAIRS = 540
EXPECTED_CLUSTER_MEMBERS = 4
EXPECTED_MEMBER_SIDE_ROWS = 8
EXPECTED_REFERENCE_ROWS = 177
EXPECTED_FOCAL_CONTEXTS = 2
HEADER_BYTES = 56
RECORD_DWORDS = 11
RECORD_BYTES = RECORD_DWORDS * 4
RELOCATION_DWORD = 10
TABLE_COUNT = 3


class Stage91Error(RuntimeError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise Stage91Error(message)


def progress(message: str) -> None:
    print(f"[stage91] {message}", file=sys.stderr, flush=True)


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


def float32_text(value: int) -> tuple[str, str]:
    number = struct.unpack("<f", int(value & 0xFFFFFFFF).to_bytes(4, "little"))[0]
    if number != number or number in (float("inf"), float("-inf")):
        return "", "nonfinite"
    if number == 0.0:
        return "0", "zero"
    if abs(number) < 1e-30:
        return f"{number:.9g}", "subnormal_or_tiny"
    return f"{number:.9g}", "finite"


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def safe_name(raw: str) -> str:
    path = PurePosixPath(raw)
    require(not path.is_absolute() and path.parts and ".." not in path.parts, f"unsafe archive member: {raw}")
    return path.as_posix()


def read_tsv(path: Path, required: bool = True) -> list[dict[str, str]]:
    if not path.is_file():
        if required:
            raise Stage91Error(f"missing required TSV: {path}")
        return []
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
        raise Stage91Error(f"invalid JSON {path}: {exc}") from exc
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


def load_module(path: Path, name: str):
    require(path.is_file(), f"missing prerequisite collector: {path}")
    spec = importlib.util.spec_from_file_location(name, path)
    require(spec is not None and spec.loader is not None, f"cannot load module: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def stable_key(path: str, member_key: str) -> tuple[str, str]:
    return path.casefold(), member_key.casefold()


def u32(payload: bytes, offset: int) -> int:
    require(offset >= 0 and offset + 4 <= len(payload) and offset % 4 == 0, f"invalid dword offset {offset}")
    return int.from_bytes(payload[offset:offset + 4], "little")


def masked_reference_record(payload: bytes, reference_offset: int) -> tuple[int, bytes, list[int]]:
    record_start = reference_offset - RELOCATION_DWORD * 4
    require(record_start >= 0 and reference_offset + 4 <= len(payload), f"reference record outside payload at {reference_offset}")
    require(record_start % 4 == 0, f"unaligned record start at {record_start}")
    record = bytearray(payload[record_start:reference_offset + 4])
    require(len(record) == RECORD_BYTES, f"reference record length mismatch at {reference_offset}")
    words = [int.from_bytes(record[index:index + 4], "little") for index in range(0, RECORD_BYTES, 4)]
    record[RELOCATION_DWORD * 4:(RELOCATION_DWORD + 1) * 4] = b"\0\0\0\0"
    return record_start, bytes(record), words


def lcs_length(left: Sequence[int], right: Sequence[int]) -> int:
    if len(right) > len(left):
        left, right = right, left
    previous = [0] * (len(right) + 1)
    for left_value in left:
        current = [0]
        for index, right_value in enumerate(right, 1):
            current.append(previous[index - 1] + 1 if left_value == right_value else max(previous[index], current[-1]))
        previous = current
    return previous[-1]


def validate_stage90(root: Path) -> dict[str, Any]:
    summary = load_json(root / "SUMMARY.json")
    require(summary.get("type") == "br_quartet_restoration_reflector_slot_light_target_section_layout_evidence_summary", "stage90 type mismatch")
    require(summary.get("tool_version") == "0.1.4", "stage90 tool version mismatch")
    require(parse_int(summary.get("sibling_G1E_G1EM_member_rows"), -1) == EXPECTED_SIBLING_PAIRS, "stage90 sibling count mismatch")
    require(parse_int(summary.get("reference_cluster_member_rows"), -1) == EXPECTED_CLUSTER_MEMBERS, "stage90 cluster-member count mismatch")
    require(parse_int(summary.get("reference_origin_rows"), -1) == EXPECTED_REFERENCE_ROWS, "stage90 reference count mismatch")
    require(parse_int(summary.get("dword_start_exact_header_rows"), -1) == EXPECTED_REFERENCE_ROWS, "stage90 dword-start header count mismatch")
    require(parse_int(summary.get("dword_end_exact_header_rows"), -1) == 0, "stage90 unexpectedly accepted dword-end references")
    require(parse_int(summary.get("section_header_member_side_rows"), -1) == EXPECTED_MEMBER_SIDE_ROWS, "stage90 header row count mismatch")
    require(parse_int(summary.get("section_header_exact_layout_rows"), -1) == EXPECTED_MEMBER_SIDE_ROWS, "stage90 exact header layout count mismatch")
    require(parse_bool(summary.get("exact_field_origin_resolved")), "stage90 did not resolve exact origin")
    require(summary.get("resolved_field_origin") == "dword_start_relative", "stage90 resolved unexpected origin")
    require(parse_bool(summary.get("masked_record_template_exact_across_candidate_and_neutral")), "stage90 masked template mismatch")
    require(not parse_bool(summary.get("shared_transition_candidate_specific")), "stage90 incorrectly marked transition candidate-specific")
    require(parse_int(summary.get("prototype_candidate_rows"), -1) == 0, "stage90 unexpectedly authorized prototype")
    require(not parse_bool(summary.get("brightness_semantics_confirmed")), "stage90 unexpectedly confirmed brightness")
    require(not parse_bool(summary.get("censorship_semantics_confirmed")), "stage90 unexpectedly confirmed censorship")
    require(parse_int(summary.get("skipped_rows"), -1) == 0, "stage90 contains skipped rows")
    policy = summary.get("policy") or {}
    require(isinstance(policy, dict), "stage90 policy malformed")
    for field in ("installed_game_modified", "render_payload_written", "pak_repacked", "core_registry_modified", "profile_activated"):
        require(not parse_bool(policy.get(field)), f"stage90 performed forbidden action: {field}")
    return summary


def table_regions(header: Mapping[str, Any]) -> list[tuple[int, int, int]]:
    fixed = parse_int(header.get("fixed_header_size"), -1)
    b1 = parse_int(header.get("table_boundary_1"), -1)
    b2 = parse_int(header.get("table_boundary_2"), -1)
    b3 = parse_int(header.get("table_boundary_3"), -1)
    return [(1, fixed, b1), (2, b1, b2), (3, b2, b3)]


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

    stage81 = load_module(project_root / "workstreams/quartet_restoration/collect_reflector_ringlight_control_callsite_evidence.py", "stage81_for_stage91")
    stage86 = load_module(project_root / "workstreams/quartet_restoration/collect_reflector_slot_light_shared_record_template_evidence.py", "stage86_for_stage91")
    stage90 = load_module(project_root / "workstreams/quartet_restoration/collect_reflector_slot_light_target_section_layout_evidence.py", "stage90_for_stage91")

    progress("validating stage 79, 87, 89 and 90 reports")
    with tempfile.TemporaryDirectory(prefix="br-stage91-") as temporary_name:
        temporary = Path(temporary_name)
        stage90_root = locate(reports, STAGE90_DIR, STAGE90_ARCHIVE, temporary / "90")
        stage89_root = locate(reports, STAGE89_DIR, STAGE89_ARCHIVE, temporary / "89")
        stage87_root = locate(reports, STAGE87_DIR, STAGE87_ARCHIVE, temporary / "87")
        stage79_root = locate(reports, STAGE79_DIR, STAGE79_ARCHIVE, temporary / "79")
        summary90 = validate_stage90(stage90_root)
        stage81.validate_stage79(stage79_root)

        header_report_rows = read_tsv(stage90_root / "SLOT_LIGHT_SECTION_HEADER_LAYOUT.tsv")
        origin_report_rows = read_tsv(stage90_root / "SLOT_LIGHT_REFERENCE_ORIGIN_DISCRIMINATION.tsv")
        binding_report_rows = read_tsv(stage90_root / "SLOT_LIGHT_SHARED_RECORD_HEADER_BINDING.tsv")
        island_rows = read_tsv(stage87_root / "SLOT_LIGHT_LOCAL_CHANGE_ISLANDS.tsv")
        require(len(header_report_rows) == EXPECTED_MEMBER_SIDE_ROWS, "stage90 header table count mismatch")
        require(len(origin_report_rows) == EXPECTED_REFERENCE_ROWS, "stage90 origin row count mismatch")
        require(len(binding_report_rows) == EXPECTED_FOCAL_CONTEXTS, "stage90 binding row count mismatch")
        require(len(island_rows) == EXPECTED_FOCAL_CONTEXTS, "stage87 island row count mismatch")

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
        require(len(all_pairs) == EXPECTED_SIBLING_PAIRS, f"expected {EXPECTED_SIBLING_PAIRS} sibling pairs, found {len(all_pairs)}")
        progress(f"indexed {len(all_pairs)} sibling G1E/G1EM payload pairs")

        header_by_member_side: dict[tuple[tuple[str, str], str], dict[str, str]] = {}
        for row in header_report_rows:
            key = stable_key(row.get("normalized_path", ""), row.get("member_key", ""))
            side = row.get("side", "")
            require(side in {"source", "target"}, f"invalid stage90 side: {side}")
            require((key, side) not in header_by_member_side, f"duplicate stage90 header row: {key} {side}")
            header_by_member_side[(key, side)] = row
        require(len(header_by_member_side) == EXPECTED_MEMBER_SIDE_ROWS, "stage90 member-side index mismatch")

        cardinality_rows: list[dict[str, Any]] = []
        table_entry_rows: list[dict[str, Any]] = []
        table_delta_rows: list[dict[str, Any]] = []
        reference_record_rows: list[dict[str, Any]] = []
        reference_dword_rows: list[dict[str, Any]] = []
        skipped_rows: list[dict[str, Any]] = []
        table_values_by_member_side: dict[tuple[tuple[str, str], str, int], list[int]] = {}
        record_hash_counts: Counter[tuple[str, str]] = Counter()
        record_member_sets: dict[tuple[str, str], set[tuple[str, str]]] = defaultdict(set)

        member_keys = sorted({key for key, _side in header_by_member_side})
        require(len(member_keys) == EXPECTED_CLUSTER_MEMBERS, "stage90 member count mismatch")
        for member_index, key in enumerate(member_keys, 1):
            pair = pair_by_key.get(key)
            require(pair is not None, f"missing payload pair for stage90 member: {key}")
            progress(f"auditing cardinality and references {member_index}/{len(member_keys)}: {pair['member_name']}")
            side_data: dict[str, dict[str, Any]] = {}
            for side in ("source", "target"):
                report_row = header_by_member_side[(key, side)]
                payload = pair[f"{side}_payload"]
                endpoint = parse_int(report_row.get("endpoint"), -1)
                header = stage90.parse_section_header(payload, endpoint)
                require(parse_bool(header.get("exact_layout")), f"header layout no longer exact: {pair['member_name']} {side}")
                require(parse_int(header.get("count"), -1) == parse_int(report_row.get("count"), -2), f"header count drift: {pair['member_name']} {side}")
                count = parse_int(header.get("count"), -1)
                declared_span = parse_int(header.get("declared_span"), -1)
                require(count >= 1 and declared_span >= HEADER_BYTES, f"invalid header count/span: {pair['member_name']} {side}")
                table_hashes: list[str] = []
                table_values: dict[int, list[int]] = {}
                for table_index, start_relative, end_relative in table_regions(header):
                    require(start_relative >= HEADER_BYTES and end_relative >= start_relative, f"invalid table boundary: {pair['member_name']} {side} table {table_index}")
                    require((end_relative - start_relative) == 4 * (count - 1), f"table cardinality mismatch: {pair['member_name']} {side} table {table_index}")
                    start_absolute = endpoint + start_relative
                    end_absolute = endpoint + end_relative
                    require(end_absolute <= endpoint + declared_span <= len(payload), f"table/span outside payload: {pair['member_name']} {side}")
                    values = [u32(payload, offset) for offset in range(start_absolute, end_absolute, 4)]
                    require(len(values) == count - 1, f"table entry count mismatch: {pair['member_name']} {side} table {table_index}")
                    table_values_by_member_side[(key, side, table_index)] = values
                    table_values[table_index] = values
                    table_hashes.append(sha256(payload[start_absolute:end_absolute]))
                    for entry_index, value in enumerate(values):
                        relative_offset = start_relative + entry_index * 4
                        float_text, float_status = float32_text(value)
                        table_entry_rows.append({
                            "cluster_role": report_row.get("cluster_role", ""),
                            "normalized_path": pair["normalized_path"],
                            "member_key": pair["member_key"],
                            "member_name": pair["member_name"],
                            "side": side,
                            "endpoint": endpoint,
                            "section_count": count,
                            "table_index": table_index,
                            "entry_index": entry_index,
                            "entry_relative_offset": relative_offset,
                            "entry_absolute_offset": endpoint + relative_offset,
                            "entry_u32_hex": f"0x{value:08x}",
                            "entry_i32": signed_i32(value),
                            "entry_float32": float_text,
                            "entry_float_status": float_status,
                            "entry_aligned": value % 4 == 0,
                            "entry_within_declared_span": 0 <= value < declared_span,
                            "entry_at_or_after_table_region": value >= parse_int(header.get("table_boundary_3"), 0),
                        })

                references = stage90.inbound_reference_offsets(payload, endpoint)
                expected_reference_count = parse_int(report_row.get("inbound_reference_rows"), -1)
                require(len(references) == expected_reference_count, f"reference count drift: {pair['member_name']} {side}")
                for reference_index, reference_offset in enumerate(references):
                    try:
                        record_start, masked, words = masked_reference_record(payload, reference_offset)
                    except Stage91Error as exc:
                        skipped_rows.append({"scope": "reference_record", "member_name": pair["member_name"], "side": side, "offset": reference_offset, "reason": str(exc)})
                        continue
                    masked_hash = sha256(masked)
                    record_hash_counts[(side, masked_hash)] += 1
                    record_member_sets[(side, masked_hash)].add(key)
                    record_class = "other_section_reference_record"
                    reference_record_rows.append({
                        "cluster_role": report_row.get("cluster_role", ""),
                        "normalized_path": pair["normalized_path"],
                        "member_key": pair["member_key"],
                        "member_name": pair["member_name"],
                        "side": side,
                        "endpoint": endpoint,
                        "section_count": count,
                        "reference_index": reference_index,
                        "reference_offset": reference_offset,
                        "reference_u32_hex": f"0x{words[RELOCATION_DWORD]:08x}",
                        "reference_i32": signed_i32(words[RELOCATION_DWORD]),
                        "record_start": record_start,
                        "record_end_exclusive": reference_offset + 4,
                        "record_length": RECORD_BYTES,
                        "masked_template_sha256": masked_hash,
                        "record_classification": record_class,
                    })
                    for relative_dword, value in enumerate(words):
                        float_text, float_status = float32_text(value)
                        reference_dword_rows.append({
                            "normalized_path": pair["normalized_path"],
                            "member_key": pair["member_key"],
                            "member_name": pair["member_name"],
                            "side": side,
                            "reference_offset": reference_offset,
                            "record_start": record_start,
                            "relative_dword": relative_dword,
                            "is_relocation_dword": relative_dword == RELOCATION_DWORD,
                            "u32_hex": f"0x{value:08x}",
                            "i32": signed_i32(value),
                            "float32": float_text,
                            "float_status": float_status,
                        })
                side_data[side] = {
                    "row": report_row,
                    "header": header,
                    "count": count,
                    "declared_span": declared_span,
                    "references": references,
                    "table_hashes": table_hashes,
                    "table_values": table_values,
                }

            source = side_data["source"]
            target = side_data["target"]
            count_delta = target["count"] - source["count"]
            reference_delta = len(target["references"]) - len(source["references"])
            cardinality_rows.append({
                "cluster_role": source["row"].get("cluster_role", ""),
                "normalized_path": pair["normalized_path"],
                "member_key": pair["member_key"],
                "member_name": pair["member_name"],
                "source_count": source["count"],
                "target_count": target["count"],
                "count_delta": count_delta,
                "source_declared_span": source["declared_span"],
                "target_declared_span": target["declared_span"],
                "declared_span_delta": target["declared_span"] - source["declared_span"],
                "source_inbound_reference_rows": len(source["references"]),
                "target_inbound_reference_rows": len(target["references"]),
                "inbound_reference_delta": reference_delta,
                "three_table_entry_delta": TABLE_COUNT * count_delta,
                "reference_delta_equals_three_table_entry_delta": reference_delta == TABLE_COUNT * count_delta,
                "source_table_1_sha256": source["table_hashes"][0],
                "target_table_1_sha256": target["table_hashes"][0],
                "source_table_2_sha256": source["table_hashes"][1],
                "target_table_2_sha256": target["table_hashes"][1],
                "source_table_3_sha256": source["table_hashes"][2],
                "target_table_3_sha256": target["table_hashes"][2],
            })
            for table_index in range(1, TABLE_COUNT + 1):
                left = source["table_values"][table_index]
                right = target["table_values"][table_index]
                common = lcs_length(left, right)
                if left == right:
                    classification = "unchanged"
                elif len(right) != len(left) and common == min(len(left), len(right)):
                    classification = "cardinality_change_with_order_preserving_subset"
                elif len(right) == len(left):
                    classification = "same_cardinality_value_change"
                else:
                    classification = "mixed_cardinality_and_value_change"
                table_delta_rows.append({
                    "cluster_role": source["row"].get("cluster_role", ""),
                    "normalized_path": pair["normalized_path"],
                    "member_key": pair["member_key"],
                    "member_name": pair["member_name"],
                    "table_index": table_index,
                    "source_entry_rows": len(left),
                    "target_entry_rows": len(right),
                    "entry_row_delta": len(right) - len(left),
                    "lcs_entry_rows": common,
                    "source_only_entry_rows": len(left) - common,
                    "target_only_entry_rows": len(right) - common,
                    "source_target_exact": left == right,
                    "delta_classification": classification,
                })

        require(not skipped_rows, f"reference-record audit skipped {len(skipped_rows)} rows")
        require(len(reference_record_rows) == EXPECTED_REFERENCE_ROWS, f"expected {EXPECTED_REFERENCE_ROWS} reference records, found {len(reference_record_rows)}")
        require(len(reference_dword_rows) == EXPECTED_REFERENCE_ROWS * RECORD_DWORDS, "reference dword row count mismatch")

        binding_by_role = {row.get("island_role", ""): row for row in binding_report_rows}
        island_by_role = {row.get("island_role", ""): row for row in island_rows}
        require(set(binding_by_role) == {"candidate_ringlight", "neutral_control"}, "unexpected stage90 binding roles")
        require(set(island_by_role) == set(binding_by_role), "stage87/stage90 role mismatch")
        source_focal_hashes = {row.get("source_record_masked_sha256", "") for row in binding_report_rows}
        target_focal_hashes = {row.get("target_record_masked_sha256", "") for row in binding_report_rows}
        require(len(source_focal_hashes) == 1 and "" not in source_focal_hashes, "source focal template disagreement")
        require(len(target_focal_hashes) == 1 and "" not in target_focal_hashes, "target focal template disagreement")
        source_focal_hash = next(iter(source_focal_hashes))
        target_focal_hash = next(iter(target_focal_hashes))
        require(source_focal_hash != target_focal_hash, "source and target focal templates unexpectedly equal")

        # Reclassify the already collected rows now that the focal hashes are known.
        for row in reference_record_rows:
            masked_hash = row["masked_template_sha256"]
            side = row["side"]
            if side == "source" and masked_hash == source_focal_hash:
                row["record_classification"] = "focal_shared_source_template"
            elif side == "target" and masked_hash == target_focal_hash:
                row["record_classification"] = "focal_shared_target_template"

        group_rows: list[dict[str, Any]] = []
        for (side, template_hash), count in sorted(record_hash_counts.items()):
            if side == "source" and template_hash == source_focal_hash:
                classification = "focal_shared_source_template"
            elif side == "target" and template_hash == target_focal_hash:
                classification = "focal_shared_target_template"
            else:
                classification = "other_section_reference_template"
            group_rows.append({
                "side": side,
                "masked_template_sha256": template_hash,
                "reference_record_rows": count,
                "member_rows": len(record_member_sets[(side, template_hash)]),
                "template_classification": classification,
            })

        cardinality_by_key = {stable_key(row["normalized_path"], row["member_key"]): row for row in cardinality_rows}
        transition_rows: list[dict[str, Any]] = []
        transition_count_deltas: set[int] = set()
        for role in ("candidate_ringlight", "neutral_control"):
            island = island_by_role[role]
            binding = binding_by_role[role]
            key = stable_key(island.get("normalized_path", ""), island.get("member_key", ""))
            pair = pair_by_key.get(key)
            require(pair is not None, f"missing focal payload pair: {role}")
            cardinality = cardinality_by_key.get(key)
            require(cardinality is not None, f"missing focal cardinality row: {role}")
            source_start = parse_int(island.get("source_start"), -1)
            target_start = parse_int(island.get("target_start"), -1)
            require(source_start >= 0 and target_start >= 0, f"invalid focal record starts: {role}")
            source_record = bytearray(pair["source_payload"][source_start:source_start + RECORD_BYTES])
            target_record = bytearray(pair["target_payload"][target_start:target_start + RECORD_BYTES])
            require(len(source_record) == RECORD_BYTES and len(target_record) == RECORD_BYTES, f"focal record outside payload: {role}")
            source_record[RELOCATION_DWORD * 4:(RELOCATION_DWORD + 1) * 4] = b"\0\0\0\0"
            target_record[RELOCATION_DWORD * 4:(RELOCATION_DWORD + 1) * 4] = b"\0\0\0\0"
            source_hash = sha256(bytes(source_record))
            target_hash = sha256(bytes(target_record))
            require(source_hash == source_focal_hash == binding.get("source_record_masked_sha256"), f"source focal hash mismatch: {role}")
            require(target_hash == target_focal_hash == binding.get("target_record_masked_sha256"), f"target focal hash mismatch: {role}")
            count_delta = parse_int(cardinality.get("count_delta"), 0)
            transition_count_deltas.add(count_delta)
            transition_rows.append({
                "island_role": role,
                "normalized_path": pair["normalized_path"],
                "member_key": pair["member_key"],
                "member_name": pair["member_name"],
                "source_count": cardinality["source_count"],
                "target_count": cardinality["target_count"],
                "count_delta": count_delta,
                "source_inbound_reference_rows": cardinality["source_inbound_reference_rows"],
                "target_inbound_reference_rows": cardinality["target_inbound_reference_rows"],
                "inbound_reference_delta": cardinality["inbound_reference_delta"],
                "source_record_masked_sha256": source_hash,
                "target_record_masked_sha256": target_hash,
                "shared_transition_hash_pair": f"{source_hash}->{target_hash}",
                "non_relocation_changed_dword_rows": parse_int(binding.get("shared_non_relocation_transition_count"), -1),
                "record_structural_role": "11_dword_section_header_reference_record",
            })

        transition_independent = len(transition_count_deltas) >= 2 and len({row["shared_transition_hash_pair"] for row in transition_rows}) == 1
        require(transition_independent, "shared record transition was not demonstrated across distinct section-count deltas")
        triple_relation_rows = sum(parse_bool(row.get("reference_delta_equals_three_table_entry_delta")) for row in cardinality_rows)

        output = reports / REPORT_DIR
        if output.exists():
            import shutil
            shutil.rmtree(output)
        output.mkdir(parents=True)

        write_tsv(output / "SLOT_LIGHT_SECTION_CARDINALITY.tsv", [
            "cluster_role", "normalized_path", "member_key", "member_name",
            "source_count", "target_count", "count_delta",
            "source_declared_span", "target_declared_span", "declared_span_delta",
            "source_inbound_reference_rows", "target_inbound_reference_rows", "inbound_reference_delta",
            "three_table_entry_delta", "reference_delta_equals_three_table_entry_delta",
            "source_table_1_sha256", "target_table_1_sha256",
            "source_table_2_sha256", "target_table_2_sha256",
            "source_table_3_sha256", "target_table_3_sha256",
        ], cardinality_rows)
        write_tsv(output / "SLOT_LIGHT_SECTION_TABLE_ENTRIES.tsv", [
            "cluster_role", "normalized_path", "member_key", "member_name", "side", "endpoint",
            "section_count", "table_index", "entry_index", "entry_relative_offset", "entry_absolute_offset",
            "entry_u32_hex", "entry_i32", "entry_float32", "entry_float_status",
            "entry_aligned", "entry_within_declared_span", "entry_at_or_after_table_region",
        ], table_entry_rows)
        write_tsv(output / "SLOT_LIGHT_SECTION_TABLE_DELTA.tsv", [
            "cluster_role", "normalized_path", "member_key", "member_name", "table_index",
            "source_entry_rows", "target_entry_rows", "entry_row_delta", "lcs_entry_rows",
            "source_only_entry_rows", "target_only_entry_rows", "source_target_exact", "delta_classification",
        ], table_delta_rows)
        write_tsv(output / "SLOT_LIGHT_REFERENCE_RECORD_TEMPLATES.tsv", [
            "cluster_role", "normalized_path", "member_key", "member_name", "side", "endpoint", "section_count",
            "reference_index", "reference_offset", "reference_u32_hex", "reference_i32",
            "record_start", "record_end_exclusive", "record_length", "masked_template_sha256", "record_classification",
        ], reference_record_rows)
        write_tsv(output / "SLOT_LIGHT_REFERENCE_RECORD_DWORDS.tsv", [
            "normalized_path", "member_key", "member_name", "side", "reference_offset", "record_start",
            "relative_dword", "is_relocation_dword", "u32_hex", "i32", "float32", "float_status",
        ], reference_dword_rows)
        write_tsv(output / "SLOT_LIGHT_REFERENCE_RECORD_TEMPLATE_GROUPS.tsv", [
            "side", "masked_template_sha256", "reference_record_rows", "member_rows", "template_classification",
        ], group_rows)
        write_tsv(output / "SLOT_LIGHT_SHARED_RECORD_TRANSITION_CARDINALITY.tsv", [
            "island_role", "normalized_path", "member_key", "member_name",
            "source_count", "target_count", "count_delta",
            "source_inbound_reference_rows", "target_inbound_reference_rows", "inbound_reference_delta",
            "source_record_masked_sha256", "target_record_masked_sha256", "shared_transition_hash_pair",
            "non_relocation_changed_dword_rows", "record_structural_role",
        ], transition_rows)
        write_tsv(output / "SLOT_LIGHT_SECTION_CARDINALITY_RECORD_ROLE_SKIPPED.tsv", ["scope", "member_name", "side", "offset", "reason"], skipped_rows)

        summary: dict[str, Any] = {
            "type": "br_quartet_restoration_reflector_slot_light_section_cardinality_record_role_evidence_summary",
            "format_version": 1,
            "tool_version": TOOL_VERSION,
            "source_stage90_tool_version": summary90.get("tool_version"),
            "source_stage79_tool_version": "0.0.92",
            "status": "stage90_dword_start_section_header_origin_confirmed_three_table_cardinality_and_shared_reference_record_role_audited_without_semantic_write_authorization",
            "sibling_G1E_G1EM_member_rows": len(all_pairs),
            "reference_cluster_member_rows": len(member_keys),
            "section_member_rows": len(cardinality_rows),
            "section_member_side_rows": len(header_report_rows),
            "section_count_delta_member_rows": sum(parse_int(row.get("count_delta"), 0) != 0 for row in cardinality_rows),
            "section_count_unchanged_member_rows": sum(parse_int(row.get("count_delta"), 0) == 0 for row in cardinality_rows),
            "section_table_rows": len(table_delta_rows),
            "section_table_entry_rows": len(table_entry_rows),
            "reference_record_rows": len(reference_record_rows),
            "reference_record_dword_rows": len(reference_dword_rows),
            "reference_record_template_group_rows": len(group_rows),
            "focal_source_template_occurrence_rows": record_hash_counts[("source", source_focal_hash)],
            "focal_target_template_occurrence_rows": record_hash_counts[("target", target_focal_hash)],
            "shared_record_transition_context_rows": len(transition_rows),
            "shared_record_transition_distinct_count_delta_values": len(transition_count_deltas),
            "shared_record_transition_independent_of_section_count_delta": transition_independent,
            "reference_delta_equals_three_table_entry_delta_member_rows": triple_relation_rows,
            "reference_delta_equals_three_table_entry_delta_all_members": triple_relation_rows == len(cardinality_rows),
            "resolved_reference_origin": "dword_start_relative",
            "record_structural_role": "11_dword_section_header_reference_record",
            "technical_leaf_semantics_resolved": False,
            "prototype_candidate_rows": 0,
            "brightness_semantics_confirmed": False,
            "censorship_semantics_confirmed": False,
            "skipped_rows": len(skipped_rows),
            "parameters": {
                "section_header_bytes": HEADER_BYTES,
                "section_table_count": TABLE_COUNT,
                "entries_per_table": "count - 1",
                "reference_record_dwords": RECORD_DWORDS,
                "relocation_relative_dword": RELOCATION_DWORD,
                "reference_record_start_rule": "record_start = reference_offset - 40",
                "reference_equation": "reference_offset + signed_i32(reference_value) == section_header_start",
                "cardinality_reference_relation_test": "inbound_reference_delta == 3 * section_count_delta",
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
            "next_action": "Upload this report. If the shared source-to-target 11-dword record transition is confirmed across both changing and unchanged section cardinalities, classify it as a cross-context structural record migration rather than a PC02-specific brightness candidate. Continue only with a read-only record-family/leaf-distribution audit if numeric field roles are still technically necessary; do not write G1E or infer censorship.",
        }
        (output / "SUMMARY.json").write_text(json.dumps(summary, indent=2, sort_keys=False) + "\n", encoding="utf-8")

        archive = reports / REPORT_NAME if create_archive else None
        if archive is not None:
            progress("creating compressed metadata-only report archive")
            make_archive(output, archive)
        progress("completed")
        return output, archive, summary


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path, default=PROJECT_ROOT_DEFAULT)
    parser.add_argument("--no-report-archive", action="store_true")
    parser.add_argument("--maximum-earc-bytes", type=int, default=512 * 1024 * 1024)
    args = parser.parse_args(argv)
    try:
        output, archive, summary = build_report(
            args.project_root,
            create_archive=not args.no_report_archive,
            maximum_earc_bytes=args.maximum_earc_bytes,
        )
    except Stage91Error as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print(f"Report directory: {output}")
    if archive is not None:
        print(f"Report archive: {archive}")
    print(f"Reference records: {summary['reference_record_rows']}")
    print(f"Shared transition independent of section count: {summary['shared_record_transition_independent_of_section_count_delta']}")
    print(f"Prototype candidates: {summary['prototype_candidate_rows']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
