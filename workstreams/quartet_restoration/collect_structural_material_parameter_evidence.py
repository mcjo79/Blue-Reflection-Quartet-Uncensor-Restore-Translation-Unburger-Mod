#!/usr/bin/env python3
"""Audit structural wet/water G1M parameter changes without writing payloads.

Stage 74 found no same-width numeric Original-to-Quartet candidates. Its direct
scene scope instead contains structural add/remove rows: repeated
``parameterForMeshBlend`` additions across bathroom, shower and pool members,
and one source-only ``atColor`` record in the Hinako bathroom model.

This stage rehydrates the exact G1M members, records parameter byte ranges and
shader-block mappings, simulates format-aware structural inverses in memory,
and separates recurrent structural changes from unique scene-local records. It
never writes G1M/Elixir/PAK payloads, changes registry state, activates a
profile, modifies the installed game, or assigns censorship semantics.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
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

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT_DEFAULT = SCRIPT_DIR.parent.parent
TEXT_TOOL_DIR = PROJECT_ROOT_DEFAULT / "Blue_Reflection_Text_Tool"
if str(TEXT_TOOL_DIR) not in sys.path:
    sys.path.insert(0, str(TEXT_TOOL_DIR))

import br_restoration_tool as BR  # noqa: E402

TOOL_VERSION = "0.0.87"
REPORT_NAME = "BR_quartet_restoration_structural_material_parameter_evidence.tar.zst"
EVIDENCE_DIR_NAME = "structural_material_parameter_evidence"
STAGE74_DIR = "wet_coverage_material_variant_evidence"
STAGE74_ARCHIVE = "BR_quartet_restoration_wet_coverage_material_variant_evidence.tar.zst"
EXPECTED_STAGE74_TOOL_VERSION = "0.0.84"
RECURRENT_THRESHOLD = 8


class StructuralMaterialError(RuntimeError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise StructuralMaterialError(message)


def parse_bool(value: object) -> bool:
    return str(value).strip().casefold() in {"1", "true", "yes", "y", "passed"}


def parse_int(value: object, default: int = 0) -> int:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return default


def safe_member_name(raw: str) -> str:
    path = PurePosixPath(raw)
    if path.is_absolute() or not path.parts or ".." in path.parts:
        raise StructuralMaterialError(f"unsafe report archive member: {raw}")
    return path.as_posix()


def read_tsv(path: Path, *, required: bool = True) -> list[dict[str, str]]:
    if not path.is_file():
        if required:
            raise StructuralMaterialError(f"missing prerequisite table: {path}")
        return []
    with path.open("r", encoding="utf-8", newline="") as handle:
        return [dict(row) for row in csv.DictReader(handle, delimiter="\t")]


def write_tsv(path: Path, fieldnames: Sequence[str], rows: Iterable[Mapping[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fieldnames})


def load_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise StructuralMaterialError(f"missing prerequisite JSON: {path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise StructuralMaterialError(f"invalid JSON {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise StructuralMaterialError(f"expected JSON object: {path}")
    return value


def atomic_json(path: Path, value: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def extract_archive(archive: Path, destination: Path) -> Path:
    if not archive.is_file():
        raise StructuralMaterialError(f"missing prerequisite report archive: {archive}")
    listed = subprocess.run(
        ["tar", "--zstd", "-tf", str(archive)], text=True,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False,
    )
    if listed.returncode != 0:
        raise StructuralMaterialError(f"cannot list {archive}: {listed.stderr.strip()}")
    roots: set[str] = set()
    for raw in listed.stdout.splitlines():
        if raw.strip():
            roots.add(PurePosixPath(safe_member_name(raw.strip())).parts[0])
    if len(roots) != 1:
        raise StructuralMaterialError(f"expected one report root in {archive}, found {sorted(roots)}")
    destination.mkdir(parents=True, exist_ok=True)
    completed = subprocess.run(
        ["tar", "--zstd", "-xf", str(archive), "-C", str(destination)], text=True,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False,
    )
    if completed.returncode != 0:
        raise StructuralMaterialError(f"cannot extract {archive}: {completed.stderr.strip()}")
    return destination / next(iter(roots))


def locate_stage74(report_root: Path, temporary: Path) -> Path:
    direct = report_root / STAGE74_DIR
    if direct.is_dir():
        return direct
    return extract_archive(report_root / STAGE74_ARCHIVE, temporary)


def make_report_archive(source_dir: Path, output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(output.name + ".tmp")
    if temporary.exists():
        temporary.unlink()
    completed = subprocess.run(
        ["tar", "--zstd", "-cf", str(temporary), "-C", str(source_dir.parent), source_dir.name],
        text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False,
    )
    if completed.returncode != 0:
        raise StructuralMaterialError(f"cannot create report archive: {completed.stderr.strip()}")
    os.replace(temporary, output)


def byte_distance(left: bytes, right: bytes) -> int:
    return sum(a != b for a, b in zip(left, right)) + abs(len(left) - len(right))


def decode_name(raw: bytes) -> str:
    value = raw.replace(b"\x00", b"")
    try:
        return value.decode("utf-8")
    except UnicodeDecodeError:
        return value.decode("cp932", errors="replace")


def parameter_key(record: Mapping[str, Any]) -> tuple[str, int, int, str]:
    return (
        str(record.get("parameter_name", "")).casefold(),
        int(record.get("buffer_type", 0)),
        int(record.get("buffer_count", 0)),
        str(record.get("value_hex", "")),
    )


def parse_g1m_layout(payload: bytes, *, label: str = "<memory>") -> dict[str, Any]:
    """Parse the stable G1M/G1MG shader-parameter envelope with byte ranges."""
    require(len(payload) >= BR.G1M_HEADER_SIZE, f"G1M payload too small: {label}")
    try:
        endian = BR.g1m_endian_from_magic(payload[:4], label=label)
    except Exception as exc:  # BR raises its own RestorationError
        raise StructuralMaterialError(str(exc)) from exc
    file_version, file_size, chunk_offset, reserved, chunk_count = struct.unpack_from(endian + "5I", payload, 4)
    require(file_size in {0, len(payload)}, f"G1M file-size mismatch: {label}")
    require(BR.G1M_HEADER_SIZE <= chunk_offset <= len(payload), f"unsafe G1M chunk offset: {label}")
    require(chunk_count <= 0x1000, f"unsafe G1M chunk count: {label}")

    chunks: list[dict[str, Any]] = []
    shader_sections: list[dict[str, Any]] = []
    offset = chunk_offset
    for chunk_index in range(chunk_count):
        require(offset + 12 <= len(payload), f"truncated G1M chunk {chunk_index}: {label}")
        magic = decode_name(payload[offset:offset + 4])
        version, size = struct.unpack_from(endian + "2I", payload, offset + 4)
        require(size >= 12 and offset + size <= len(payload), f"unsafe G1M chunk size: {label}")
        chunk = {
            "chunk_index": chunk_index,
            "magic": magic,
            "version": version,
            "start": offset,
            "end": offset + size,
            "size": size,
        }
        chunks.append(chunk)
        if magic in {"G1MG", "GM1G"}:
            require(size >= BR.G1MG_HEADER_SIZE, f"G1MG chunk too small: {label}")
            section_count = struct.unpack_from(endian + "I", payload, offset + 44)[0]
            require(section_count <= 0x1000, f"unsafe G1MG section count: {label}")
            section_rel = BR.G1MG_HEADER_SIZE
            for section_index in range(section_count):
                section_abs = offset + section_rel
                require(section_abs + 12 <= offset + size, f"truncated G1MG section: {label}")
                section_type, section_size, entries = struct.unpack_from(endian + "3I", payload, section_abs)
                require(section_size >= 12 and section_abs + section_size <= offset + size, f"unsafe G1MG section size: {label}")
                if section_type == BR.G1MG_SHADER_PARAMS_SECTION:
                    cursor = section_abs + 12
                    section_end = section_abs + section_size
                    blocks: list[dict[str, Any]] = []
                    for block_index in range(entries):
                        require(cursor + 4 <= section_end, f"truncated shader block: {label}")
                        count_offset = cursor
                        count = struct.unpack_from(endian + "I", payload, cursor)[0]
                        require(count <= 0x10000, f"unsafe shader parameter count: {label}")
                        cursor += 4
                        records: list[dict[str, Any]] = []
                        duplicate_names: Counter[str] = Counter()
                        for parameter_index in range(count):
                            start = cursor
                            require(start + 16 <= section_end, f"truncated shader parameter: {label}")
                            parameter_size, name_size, unknown, buffer_type, buffer_count = struct.unpack_from(
                                endian + "3I2H", payload, start
                            )
                            widths = {1: 4, 2: 8, 3: 12, 4: 16, 5: 4}
                            width = widths.get(buffer_type)
                            require(width is not None, f"unsupported buffer type {buffer_type}: {label}")
                            minimum = 16 + name_size + width * buffer_count
                            require(parameter_size >= minimum, f"undersized shader parameter: {label}")
                            end = start + parameter_size
                            require(end <= section_end, f"shader parameter exceeds section: {label}")
                            name_start = start + 16
                            name_end = name_start + name_size
                            value_start = name_end
                            value_end = value_start + width * buffer_count
                            name = decode_name(payload[name_start:name_end])
                            folded = name.casefold()
                            occurrence = duplicate_names[folded]
                            duplicate_names[folded] += 1
                            raw = payload[start:end]
                            records.append({
                                "block_index": block_index,
                                "parameter_index": parameter_index,
                                "parameter_name": name,
                                "parameter_occurrence": occurrence,
                                "buffer_type": buffer_type,
                                "buffer_count": buffer_count,
                                "unknown": unknown,
                                "start": start,
                                "end": end,
                                "size": parameter_size,
                                "name_start": name_start,
                                "value_start": value_start,
                                "value_end": value_end,
                                "value_hex": payload[value_start:value_end].hex(),
                                "raw": raw,
                                "raw_sha256": hashlib.sha256(raw).hexdigest(),
                            })
                            cursor = end
                        blocks.append({
                            "block_index": block_index,
                            "count_offset": count_offset,
                            "start": count_offset,
                            "end": cursor,
                            "records": records,
                        })
                    require(cursor == section_end, f"unparsed shader-section suffix: {label}")
                    shader_sections.append({
                        "chunk_index": chunk_index,
                        "chunk_start": offset,
                        "chunk_end": offset + size,
                        "section_index": section_index,
                        "section_start": section_abs,
                        "section_end": section_end,
                        "section_size": section_size,
                        "section_entries": entries,
                        "blocks": blocks,
                    })
                section_rel += section_size
        offset += size
    require(offset == len(payload), f"unparsed G1M file suffix: {label}")
    require(len(shader_sections) == 1, f"expected exactly one shader-parameter section: {label}")
    return {
        "endian": endian,
        "file_version": file_version,
        "file_size": len(payload),
        "chunk_offset": chunk_offset,
        "reserved": reserved,
        "chunk_count": chunk_count,
        "chunks": chunks,
        "shader_section": shader_sections[0],
        "payload_sha256": hashlib.sha256(payload).hexdigest(),
    }


def rebuild_with_blocks(payload: bytes, layout: Mapping[str, Any], block_records: Sequence[Sequence[bytes]]) -> bytes:
    endian = str(layout["endian"])
    section = dict(layout["shader_section"])
    require(len(block_records) == int(section["section_entries"]), "shader block-count changed unexpectedly")
    block_payload = bytearray()
    for records in block_records:
        block_payload.extend(struct.pack(endian + "I", len(records)))
        for raw in records:
            block_payload.extend(raw)
    old_section = payload[int(section["section_start"]):int(section["section_end"])]
    header = bytearray(old_section[:12])
    new_section_size = 12 + len(block_payload)
    struct.pack_into(endian + "I", header, 4, new_section_size)
    new_section = bytes(header) + bytes(block_payload)

    chunk_start = int(section["chunk_start"])
    chunk_end = int(section["chunk_end"])
    section_start = int(section["section_start"])
    section_end = int(section["section_end"])
    old_chunk = payload[chunk_start:chunk_end]
    rel_start = section_start - chunk_start
    rel_end = section_end - chunk_start
    new_chunk = bytearray(old_chunk[:rel_start] + new_section + old_chunk[rel_end:])
    struct.pack_into(endian + "I", new_chunk, 8, len(new_chunk))

    rebuilt = bytearray(payload[:chunk_start] + bytes(new_chunk) + payload[chunk_end:])
    struct.pack_into(endian + "I", rebuilt, 8, len(rebuilt))
    result = bytes(rebuilt)
    parse_g1m_layout(result, label="rebuilt")
    return result


def block_overlap(left: Sequence[Mapping[str, Any]], right: Sequence[Mapping[str, Any]]) -> int:
    a = Counter(parameter_key(row) for row in left)
    b = Counter(parameter_key(row) for row in right)
    return sum((a & b).values())


def map_blocks(source: Mapping[str, Any], target: Mapping[str, Any]) -> tuple[dict[int, int], list[dict[str, Any]]]:
    source_blocks = list(source["shader_section"]["blocks"])
    target_blocks = list(target["shader_section"]["blocks"])
    candidates: list[tuple[int, int, int, int]] = []
    for left in source_blocks:
        for right in target_blocks:
            score = block_overlap(left["records"], right["records"])
            same_index = int(left["block_index"] == right["block_index"])
            candidates.append((score, same_index, int(left["block_index"]), int(right["block_index"])))
    candidates.sort(key=lambda item: (-item[0], -item[1], item[2], item[3]))
    used_source: set[int] = set()
    used_target: set[int] = set()
    mapping: dict[int, int] = {}
    rows: list[dict[str, Any]] = []
    for score, same_index, source_index, target_index in candidates:
        if source_index in used_source or target_index in used_target:
            continue
        if score == 0 and source_index != target_index:
            continue
        used_source.add(source_index)
        used_target.add(target_index)
        mapping[source_index] = target_index
        source_count = len(source_blocks[source_index]["records"])
        target_count = len(target_blocks[target_index]["records"])
        rows.append({
            "source_block_index": source_index,
            "target_block_index": target_index,
            "exact_parameter_overlap": score,
            "source_parameter_count": source_count,
            "target_parameter_count": target_count,
            "same_index": bool(same_index),
            "mapping_status": "mapped_by_exact_parameter_overlap" if score else "mapped_by_stable_same_index_empty_overlap",
        })
    return mapping, rows


def find_record(blocks: Sequence[Mapping[str, Any]], block_index: int, parameter_index: int) -> Mapping[str, Any]:
    require(0 <= block_index < len(blocks), f"shader block index out of range: {block_index}")
    records = list(blocks[block_index]["records"])
    require(0 <= parameter_index < len(records), f"parameter index out of range: {block_index}:{parameter_index}")
    return records[parameter_index]


def insertion_index_from_source(
    source_records: Sequence[Mapping[str, Any]],
    target_records: Sequence[bytes],
    source_index: int,
) -> int | None:
    target_keys: list[tuple[str, int, int, str]] = []
    for raw in target_records:
        # Reparse a synthetic one-record block is excessive. The caller passes a
        # key cache through raw-record identity when possible, so this function
        # is used only after target keys are attached externally.
        target_keys.append((hashlib.sha256(raw).hexdigest(), 0, 0, ""))
    del target_keys  # documented guard; actual resolution happens in caller.
    if source_index == 0:
        return 0
    return len(target_records)


def resolve_insert_position(
    source_block: Mapping[str, Any],
    target_block: Mapping[str, Any],
    source_index: int,
    deleted_target_indices: set[int],
) -> int | None:
    source_records = list(source_block["records"])
    current = [row for index, row in enumerate(target_block["records"]) if index not in deleted_target_indices]
    positions: dict[tuple[str, int, int, str], list[int]] = defaultdict(list)
    for index, record in enumerate(current):
        positions[parameter_key(record)].append(index)

    previous_position: int | None = None
    for index in range(source_index - 1, -1, -1):
        matches = positions.get(parameter_key(source_records[index]), [])
        if matches:
            previous_position = matches[-1]
            break
    next_position: int | None = None
    for index in range(source_index + 1, len(source_records)):
        matches = positions.get(parameter_key(source_records[index]), [])
        if matches:
            next_position = matches[0]
            break
    if previous_position is not None and next_position is not None:
        return next_position if previous_position < next_position else None
    if previous_position is not None:
        return previous_position + 1
    if next_position is not None:
        return next_position
    if source_index == 0:
        return 0
    if source_index >= len(source_records) - 1:
        return len(current)
    return None


def build_candidate(
    *, target_payload: bytes, source_layout: Mapping[str, Any], target_layout: Mapping[str, Any],
    rows: Sequence[Mapping[str, Any]], include_recurrent: bool, include_unique: bool,
    recurrence_by_row_id: Mapping[str, int], mapping: Mapping[int, int],
) -> tuple[bytes | None, dict[str, Any]]:
    target_blocks = list(target_layout["shader_section"]["blocks"])
    source_blocks = list(source_layout["shader_section"]["blocks"])
    working: list[list[bytes]] = [[bytes(record["raw"]) for record in block["records"]] for block in target_blocks]
    deletions: dict[int, list[tuple[int, bytes]]] = defaultdict(list)
    insertions: list[tuple[int, int, bytes]] = []
    unresolved: list[str] = []

    selected = []
    for row in rows:
        recurrence = int(recurrence_by_row_id.get(str(row.get("row_id", "")), 1))
        recurrent = recurrence >= RECURRENT_THRESHOLD
        if recurrent and not include_recurrent:
            continue
        if not recurrent and not include_unique:
            continue
        selected.append(row)
        classification = str(row.get("classification", ""))
        if classification == "added_in_target":
            block_index = parse_int(row.get("target_shader_block_index"), -1)
            parameter_index = parse_int(row.get("target_parameter_index"), -1)
            try:
                record = find_record(target_blocks, block_index, parameter_index)
            except StructuralMaterialError as exc:
                unresolved.append(str(exc))
                continue
            deletions[block_index].append((parameter_index, bytes(record["raw"])))
        elif classification == "removed_in_target":
            source_block_index = parse_int(row.get("source_shader_block_index"), -1)
            source_parameter_index = parse_int(row.get("source_parameter_index"), -1)
            if source_block_index not in mapping:
                unresolved.append(f"source block {source_block_index} has no target mapping")
                continue
            target_block_index = int(mapping[source_block_index])
            try:
                record = find_record(source_blocks, source_block_index, source_parameter_index)
            except StructuralMaterialError as exc:
                unresolved.append(str(exc))
                continue
            deleted_indices = {index for index, _raw in deletions.get(target_block_index, [])}
            position = resolve_insert_position(
                source_blocks[source_block_index], target_blocks[target_block_index],
                source_parameter_index, deleted_indices,
            )
            if position is None:
                unresolved.append(f"cannot resolve insertion position for source {source_block_index}:{source_parameter_index}")
                continue
            insertions.append((target_block_index, position, bytes(record["raw"])))
        else:
            unresolved.append(f"unsupported structural classification: {classification}")

    if unresolved or not selected:
        return None, {
            "selected_row_count": len(selected),
            "unresolved_reasons": ";".join(unresolved) if unresolved else "no_rows_selected",
            "reverse_roundtrip": False,
        }

    for block_index, operations in deletions.items():
        for parameter_index, expected_raw in sorted(operations, reverse=True):
            if not (0 <= parameter_index < len(working[block_index])):
                unresolved.append(f"deletion index shifted out of range: {block_index}:{parameter_index}")
                continue
            if working[block_index][parameter_index] != expected_raw:
                unresolved.append(f"deletion raw mismatch: {block_index}:{parameter_index}")
                continue
            del working[block_index][parameter_index]
    if unresolved:
        return None, {"selected_row_count": len(selected), "unresolved_reasons": ";".join(unresolved), "reverse_roundtrip": False}

    applied_insertions: list[tuple[int, int, bytes]] = []
    for block_index, position, raw in sorted(insertions, key=lambda item: (item[0], item[1])):
        if not (0 <= position <= len(working[block_index])):
            unresolved.append(f"insertion position out of range: {block_index}:{position}")
            continue
        working[block_index].insert(position, raw)
        applied_insertions.append((block_index, position, raw))
    if unresolved:
        return None, {"selected_row_count": len(selected), "unresolved_reasons": ";".join(unresolved), "reverse_roundtrip": False}

    candidate = rebuild_with_blocks(target_payload, target_layout, working)

    # Reverse candidate to exact target: remove source-only insertions, then
    # restore target-only records at their original indices.
    candidate_layout = parse_g1m_layout(candidate, label="candidate")
    reverse_working: list[list[bytes]] = [
        [bytes(record["raw"]) for record in block["records"]]
        for block in candidate_layout["shader_section"]["blocks"]
    ]
    for block_index, position, raw in sorted(applied_insertions, key=lambda item: (item[0], item[1]), reverse=True):
        require(0 <= position < len(reverse_working[block_index]), "reverse insertion index out of range")
        require(reverse_working[block_index][position] == raw, "reverse insertion raw mismatch")
        del reverse_working[block_index][position]
    for block_index, operations in deletions.items():
        for parameter_index, raw in sorted(operations):
            require(0 <= parameter_index <= len(reverse_working[block_index]), "reverse deletion index out of range")
            reverse_working[block_index].insert(parameter_index, raw)
    reverse = rebuild_with_blocks(candidate, candidate_layout, reverse_working)
    return candidate, {
        "selected_row_count": len(selected),
        "deleted_record_count": sum(len(value) for value in deletions.values()),
        "inserted_record_count": len(applied_insertions),
        "unresolved_reasons": "",
        "reverse_roundtrip": reverse == target_payload,
        "reverse_sha256": hashlib.sha256(reverse).hexdigest(),
    }


def pair_key(row: Mapping[str, Any]) -> tuple[str, str, str]:
    return (
        str(row.get("candidate_id", "")),
        str(row.get("normalized_path", "")).casefold(),
        str(row.get("target_member_name") or row.get("source_member_name") or "").casefold(),
    )


def stable_pair_key(row: Mapping[str, Any]) -> tuple[str, str]:
    """Return the stable archive/member identity independent of recomputed rule IDs."""
    return (
        str(row.get("normalized_path") or row.get("target_archive_path") or row.get("source_archive_path") or "").casefold(),
        str(row.get("target_member_name") or row.get("source_member_name") or "").casefold(),
    )


def pair_payload_signature(row: Mapping[str, Any]) -> tuple[str, str]:
    def digest(value: object) -> str:
        return hashlib.sha256(bytes(value)).hexdigest() if isinstance(value, (bytes, bytearray)) else ""
    return digest(row.get("source_payload")), digest(row.get("target_payload"))


def resolve_pair(
    key: tuple[str, str, str],
    exact_lookup: Mapping[tuple[str, str, str], Mapping[str, Any]],
    stable_lookup: Mapping[tuple[str, str], Sequence[Mapping[str, Any]]],
) -> tuple[Mapping[str, Any] | None, str]:
    exact = exact_lookup.get(key)
    if exact is not None:
        return exact, "exact_context_archive_member"
    candidates = list(stable_lookup.get((key[1], key[2]), ()))
    if not candidates:
        return None, "missing"
    if len(candidates) == 1:
        return candidates[0], "stable_archive_member"
    signatures = {pair_payload_signature(candidate) for candidate in candidates}
    if len(signatures) == 1:
        return candidates[0], "stable_archive_member_identical_duplicates"
    raise StructuralMaterialError(
        f"ambiguous rehydrated payloads for stable archive/member key: {key[1]} :: {key[2]}"
    )


def structural_key(row: Mapping[str, Any]) -> tuple[str, str, str]:
    return (
        str(row.get("context_id", "")),
        str(row.get("target_archive_path") or row.get("source_archive_path", "")).casefold(),
        str(row.get("target_member_name") or row.get("source_member_name", "")).casefold(),
    )


def validate_stage74(root: Path) -> tuple[dict[str, Any], list[dict[str, str]]]:
    summary = load_json(root / "SUMMARY.json")
    require(summary.get("type") == "br_quartet_restoration_wet_coverage_material_variant_evidence_summary", "stage-74 report has unexpected type")
    require(summary.get("tool_version") == EXPECTED_STAGE74_TOOL_VERSION, "stage-74 report has unexpected tool version")
    require(parse_int(summary.get("registry_profile_rows"), -1) == 15, "stage-74 report must use the fifteen-profile registry")
    require(parse_int(summary.get("direct_numeric_restore_candidate_rows"), -1) == 0, "stage-74 report unexpectedly contains direct numeric candidates")
    structural = read_tsv(root / "STRUCTURAL_MATERIAL_CHANGES.tsv")
    require(len(structural) == parse_int(summary.get("structural_material_change_rows"), -1), "stage-74 structural row count mismatch")
    require(structural, "stage-74 report contains no structural material rows")
    policy = summary.get("policy") or {}
    require(isinstance(policy, dict), "stage-74 policy malformed")
    for field in ("installed_game_modified", "g1m_payload_written", "parent_elixir_rebuilt", "pak_repacked", "core_registry_modified", "profile_activated"):
        require(not parse_bool(policy.get(field)), f"stage-74 report performed forbidden action: {field}")
    return summary, structural



def load_structural_g1m_pairs(
    *,
    workspace_root: Path,
    report_root: Path,
    rules_file: Path,
    maximum_earc_bytes: int,
    structural_rows: Sequence[Mapping[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Rehydrate the exact G1M members referenced by stage-74 rows.

    The generic focused-render loader intentionally excludes ``.g1m`` members;
    stage 75 needs those members specifically.  Keep this loader local to the
    structural-material audit so earlier effect stages retain their established
    extension scope.
    """
    wanted: dict[str, set[str]] = defaultdict(set)
    for row in structural_rows:
        archive_path = str(row.get("target_archive_path") or row.get("source_archive_path") or "").casefold()
        member_name = str(row.get("target_member_name") or row.get("source_member_name") or "").casefold()
        require(bool(archive_path and member_name), "stage-74 structural row lacks archive/member identity")
        wanted[archive_path].add(member_name)

    differences = BR.load_report_jsons(report_root, "differences")
    effects = BR.build_effect_material_candidates(differences, BR.load_effect_material_rules(rules_file))
    by_path: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for effect in effects:
        normalized = str(effect.get("normalized_path", "")).casefold()
        if normalized in wanted:
            by_path[normalized].append(effect)

    pairs: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    found: set[tuple[str, str]] = set()
    seen_effect_refs: set[tuple[str, str, str, str, str]] = set()
    for archive_path, wanted_members in sorted(wanted.items()):
        candidates = by_path.get(archive_path, [])
        if not candidates:
            skipped.append({
                "candidate_id": "", "side": "both", "normalized_path": archive_path,
                "member_key": "<archive>", "member_name": "",
                "reason": "structural_archive_not_selected_by_effect_rules",
            })
            continue
        for effect in candidates:
            source_ref = effect.get("source") or {}
            target_ref = effect.get("target") or {}
            identity = (
                str(effect.get("pair_id", "")),
                str(source_ref.get("archive", "")), str(source_ref.get("path", "")),
                str(target_ref.get("archive", "")), str(target_ref.get("path", "")),
            )
            if identity in seen_effect_refs:
                continue
            seen_effect_refs.add(identity)
            archives: dict[str, dict[str, Any] | None] = {"source": None, "target": None}
            for side, ref in (("source", source_ref), ("target", target_ref)):
                if not ref:
                    continue
                local_path = BR.inventory_workspace_file(
                    workspace_root, side, str(effect.get("pair_id", "")),
                    str(ref.get("archive", "")), str(ref.get("path", "")),
                )
                if not local_path.is_file():
                    skipped.append({
                        "candidate_id": effect.get("candidate_id", ""), "side": side,
                        "normalized_path": archive_path, "member_key": "<archive>",
                        "member_name": "", "reason": "workspace_file_missing",
                    })
                    continue
                try:
                    archives[side] = BR.read_earc_archive(
                        local_path, maximum_bytes=maximum_earc_bytes, include_member_payloads=True
                    )
                except Exception as exc:
                    skipped.append({
                        "candidate_id": effect.get("candidate_id", ""), "side": side,
                        "normalized_path": archive_path, "member_key": "<archive>",
                        "member_name": "", "reason": str(exc),
                    })
            source_members = {str(row["comparison_key"]): row for row in (archives["source"] or {}).get("members", [])}
            target_members = {str(row["comparison_key"]): row for row in (archives["target"] or {}).get("members", [])}
            for member_key in sorted(set(source_members) | set(target_members), key=str.casefold):
                left = source_members.get(member_key)
                right = target_members.get(member_key)
                member_name = str((right or left or {}).get("name", ""))
                folded_name = member_name.casefold()
                if folded_name not in wanted_members:
                    continue
                extension = str((right or left or {}).get("extension", "")).casefold()
                if extension != ".g1m":
                    skipped.append({
                        "candidate_id": effect.get("candidate_id", ""), "side": "both",
                        "normalized_path": archive_path, "member_key": member_key,
                        "member_name": member_name, "reason": f"expected_g1m_member_found_{extension or 'without_extension'}",
                    })
                    continue
                pairs.append({
                    **effect,
                    "member_key": member_key,
                    "source_member_name": str((left or {}).get("name", "")),
                    "target_member_name": str((right or {}).get("name", "")),
                    "source_payload": (left or {}).get("payload"),
                    "target_payload": (right or {}).get("payload"),
                })
                found.add((archive_path, folded_name))

    for archive_path, members in wanted.items():
        for member_name in members:
            if (archive_path, member_name) not in found:
                skipped.append({
                    "candidate_id": "", "side": "both", "normalized_path": archive_path,
                    "member_key": "<member>", "member_name": member_name,
                    "reason": "structural_g1m_member_not_rehydrated",
                })
    return pairs, skipped

def collect(
    *, project_root: Path, workspace_root: Path, report_root: Path,
    rules_file: Path | None = None, maximum_earc_bytes: int = 512 * 1024 * 1024,
    pair_loader: Callable[..., tuple[list[dict[str, Any]], list[dict[str, Any]]]] | None = None,
    progress_callback: Callable[[str], None] | None = None,
) -> tuple[Path, dict[str, Any]]:
    emit = progress_callback or (lambda message: print(f"[stage75] {message}", flush=True))
    with tempfile.TemporaryDirectory(prefix="br-stage75-") as temporary_name:
        temporary = Path(temporary_name)
        stage74_root = locate_stage74(report_root, temporary / "stage74")
        stage74_summary, structural_rows = validate_stage74(stage74_root)
        emit(f"validated {len(structural_rows)} structural material rows")

        rules = rules_file or project_root / "titles/blue_reflection/modules/quartet_restoration/mappings/effect_material_rules.tsv"
        if pair_loader is not None:
            pairs, loader_skipped = pair_loader(
                workspace_root=workspace_root,
                report_root=report_root,
                rules_file=rules,
                maximum_earc_bytes=maximum_earc_bytes,
            )
        else:
            pairs, loader_skipped = load_structural_g1m_pairs(
                workspace_root=workspace_root,
                report_root=report_root,
                rules_file=rules,
                maximum_earc_bytes=maximum_earc_bytes,
                structural_rows=structural_rows,
            )
        if loader_skipped:
            raise StructuralMaterialError(f"focused render loader skipped {len(loader_skipped)} rows")
        pair_lookup = {pair_key(row): row for row in pairs}
        require(len(pair_lookup) == len(pairs), "duplicate focused render pair keys")
        stable_pair_lookup: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
        for pair_row in pairs:
            stable_pair_lookup[stable_pair_key(pair_row)].append(pair_row)
        emit(f"rehydrated {len(pairs)} structural G1M member pairs")

        recurrence_counter = Counter(
            (
                str(row.get("classification", "")),
                str(row.get("parameter_name", "")).casefold(),
                str(row.get("buffer_type", "")),
                str(row.get("buffer_count", "")),
                str(row.get("source_value_hex") or row.get("target_value_hex", "")),
            )
            for row in structural_rows
        )
        recurrence_by_row_id = {
            str(row.get("row_id", "")): recurrence_counter[(
                str(row.get("classification", "")),
                str(row.get("parameter_name", "")).casefold(),
                str(row.get("buffer_type", "")),
                str(row.get("buffer_count", "")),
                str(row.get("source_value_hex") or row.get("target_value_hex", "")),
            )]
            for row in structural_rows
        }

        grouped: dict[tuple[str, str, str], list[dict[str, str]]] = defaultdict(list)
        for row in structural_rows:
            grouped[structural_key(row)].append(row)

        record_rows: list[dict[str, Any]] = []
        block_rows: list[dict[str, Any]] = []
        member_rows: list[dict[str, Any]] = []
        candidate_rows: list[dict[str, Any]] = []
        skipped_rows: list[dict[str, Any]] = []

        for member_index, (key, rows) in enumerate(sorted(grouped.items()), start=1):
            emit(f"auditing member {member_index}/{len(grouped)}: {key[1]} :: {key[2]}")
            pair, rehydration_match_basis = resolve_pair(key, pair_lookup, stable_pair_lookup)
            if pair is None:
                skipped_rows.append({"context_id": key[0], "archive_path": key[1], "member_name": key[2], "reason": "rehydrated_pair_missing"})
                continue
            source_payload = pair.get("source_payload")
            target_payload = pair.get("target_payload")
            if not isinstance(source_payload, (bytes, bytearray)) or not isinstance(target_payload, (bytes, bytearray)):
                skipped_rows.append({"context_id": key[0], "archive_path": key[1], "member_name": key[2], "reason": "source_or_target_payload_missing"})
                continue
            source_payload = bytes(source_payload)
            target_payload = bytes(target_payload)
            try:
                source_layout = parse_g1m_layout(source_payload, label=f"source:{key[2]}")
                target_layout = parse_g1m_layout(target_payload, label=f"target:{key[2]}")
            except StructuralMaterialError as exc:
                skipped_rows.append({"context_id": key[0], "archive_path": key[1], "member_name": key[2], "reason": str(exc)})
                continue
            mapping, mappings = map_blocks(source_layout, target_layout)
            reverse_mapping = {target: source for source, target in mapping.items()}
            for mapping_row in mappings:
                block_rows.append({
                    "context_id": key[0], "archive_path": key[1], "member_name": key[2],
                    **mapping_row,
                })

            member_record_failures = 0
            for row in rows:
                classification = str(row.get("classification", ""))
                recurrence = recurrence_by_row_id[str(row.get("row_id", ""))]
                recurrent = recurrence >= RECURRENT_THRESHOLD
                if classification == "added_in_target":
                    block_index = parse_int(row.get("target_shader_block_index"), -1)
                    parameter_index = parse_int(row.get("target_parameter_index"), -1)
                    try:
                        record = find_record(target_layout["shader_section"]["blocks"], block_index, parameter_index)
                    except StructuralMaterialError as exc:
                        member_record_failures += 1
                        record_rows.append({**row, "record_validation": "failed", "record_failure": str(exc), "recurrence_count": recurrence, "recurrent": recurrent})
                        continue
                    expected = str(row.get("target_value_hex", ""))
                    valid = (
                        str(record["parameter_name"]).casefold() == str(row.get("parameter_name", "")).casefold()
                        and int(record["buffer_type"]) == parse_int(row.get("buffer_type"), -1)
                        and int(record["buffer_count"]) == parse_int(row.get("buffer_count"), -1)
                        and str(record["value_hex"]) == expected
                    )
                    source_block = reverse_mapping.get(block_index, "")
                else:
                    block_index = parse_int(row.get("source_shader_block_index"), -1)
                    parameter_index = parse_int(row.get("source_parameter_index"), -1)
                    try:
                        record = find_record(source_layout["shader_section"]["blocks"], block_index, parameter_index)
                    except StructuralMaterialError as exc:
                        member_record_failures += 1
                        record_rows.append({**row, "record_validation": "failed", "record_failure": str(exc), "recurrence_count": recurrence, "recurrent": recurrent})
                        continue
                    expected = str(row.get("source_value_hex", ""))
                    valid = (
                        str(record["parameter_name"]).casefold() == str(row.get("parameter_name", "")).casefold()
                        and int(record["buffer_type"]) == parse_int(row.get("buffer_type"), -1)
                        and int(record["buffer_count"]) == parse_int(row.get("buffer_count"), -1)
                        and str(record["value_hex"]) == expected
                    )
                    source_block = block_index
                if not valid:
                    member_record_failures += 1
                record_rows.append({
                    **row,
                    "record_validation": "passed" if valid else "failed",
                    "record_failure": "" if valid else "reported locator/value does not match rehydrated record",
                    "record_start": record["start"],
                    "record_end": record["end"],
                    "record_size": record["size"],
                    "record_raw_sha256": record["raw_sha256"],
                    "record_value_hex": record["value_hex"],
                    "mapped_source_block_index": source_block,
                    "mapped_target_block_index": mapping.get(block_index, "") if classification == "removed_in_target" else block_index,
                    "recurrence_count": recurrence,
                    "recurrent": recurrent,
                    "structural_class": "recurrent_cross_scene_structure" if recurrent else "unique_scene_local_structure",
                    "semantics_inferred": False,
                })

            base_distance = byte_distance(source_payload, target_payload)
            mode_results: dict[str, dict[str, Any]] = {}
            for mode, include_recurrent, include_unique in (
                ("recurrent_only", True, False),
                ("unique_only", False, True),
                ("all_structural", True, True),
            ):
                candidate, details = build_candidate(
                    target_payload=target_payload,
                    source_layout=source_layout,
                    target_layout=target_layout,
                    rows=rows,
                    include_recurrent=include_recurrent,
                    include_unique=include_unique,
                    recurrence_by_row_id=recurrence_by_row_id,
                    mapping=mapping,
                )
                if candidate is None:
                    result = {
                        "candidate_mode": mode,
                        "candidate_available": False,
                        "candidate_size": "",
                        "candidate_sha256": "",
                        "candidate_distance_to_original": "",
                        "distance_improvement": "",
                        "exact_original": False,
                        **details,
                    }
                else:
                    distance = byte_distance(source_payload, candidate)
                    result = {
                        "candidate_mode": mode,
                        "candidate_available": True,
                        "candidate_size": len(candidate),
                        "candidate_sha256": hashlib.sha256(candidate).hexdigest(),
                        "candidate_distance_to_original": distance,
                        "distance_improvement": base_distance - distance,
                        "exact_original": candidate == source_payload,
                        **details,
                    }
                mode_results[mode] = result
                candidate_rows.append({
                    "context_id": key[0], "archive_path": key[1], "member_name": key[2],
                    "source_sha256": hashlib.sha256(source_payload).hexdigest(),
                    "target_sha256": hashlib.sha256(target_payload).hexdigest(),
                    "target_distance_to_original": base_distance,
                    **result,
                    "safe_to_build_payload_now": False,
                    "runtime_validated": False,
                    "semantics_inferred": False,
                })

            unique = mode_results["unique_only"]
            all_result = mode_results["all_structural"]
            unique_ready = (
                bool(unique.get("candidate_available"))
                and parse_int(unique.get("distance_improvement"), 0) > 0
                and parse_bool(unique.get("reverse_roundtrip"))
                and member_record_failures == 0
            )
            if unique_ready:
                classification = "unique_structural_inverse_candidate_ready_for_narrow_followup"
            elif parse_bool(all_result.get("exact_original")) and parse_bool(all_result.get("reverse_roundtrip")):
                classification = "exact_original_requires_recurrent_and_unique_structure_confounded"
            elif parse_int(all_result.get("distance_improvement"), 0) > 0 and parse_bool(all_result.get("reverse_roundtrip")):
                classification = "partial_structural_inverse_evidence_only"
            else:
                classification = "structural_material_member_evidence_only"
            member_rows.append({
                "context_id": key[0], "domain": rows[0].get("domain", ""),
                "archive_path": key[1], "member_name": key[2],
                "rehydration_match_basis": rehydration_match_basis,
                "source_size": len(source_payload), "target_size": len(target_payload),
                "source_sha256": hashlib.sha256(source_payload).hexdigest(),
                "target_sha256": hashlib.sha256(target_payload).hexdigest(),
                "target_distance_to_original": base_distance,
                "structural_row_count": len(rows),
                "recurrent_structural_row_count": sum(recurrence_by_row_id[str(row.get("row_id", ""))] >= RECURRENT_THRESHOLD for row in rows),
                "unique_structural_row_count": sum(recurrence_by_row_id[str(row.get("row_id", ""))] < RECURRENT_THRESHOLD for row in rows),
                "record_validation_failures": member_record_failures,
                "block_mapping_rows": len(mappings),
                "unique_candidate_available": unique.get("candidate_available", False),
                "unique_candidate_sha256": unique.get("candidate_sha256", ""),
                "unique_candidate_distance_to_original": unique.get("candidate_distance_to_original", ""),
                "unique_distance_improvement": unique.get("distance_improvement", ""),
                "unique_reverse_roundtrip": unique.get("reverse_roundtrip", False),
                "all_structural_exact_original": all_result.get("exact_original", False),
                "all_structural_reverse_roundtrip": all_result.get("reverse_roundtrip", False),
                "classification": classification,
                "safe_to_build_payload_now": False,
                "next_gate": (
                    "build_read_only_unique_record_prototype_only_after_uploaded_report_review"
                    if unique_ready
                    else "retain_recurrent_or_unresolved_structure_as_evidence_only"
                ),
                "runtime_validated": False,
                "semantics_inferred": False,
            })

    output = report_root / EVIDENCE_DIR_NAME
    if output.exists():
        shutil.rmtree(output)
    output.mkdir(parents=True)

    record_fields = list(structural_rows[0].keys()) + [
        "record_validation", "record_failure", "record_start", "record_end", "record_size",
        "record_raw_sha256", "record_value_hex", "mapped_source_block_index",
        "mapped_target_block_index", "recurrence_count", "recurrent", "structural_class",
        "semantics_inferred",
    ]
    write_tsv(output / "STRUCTURAL_PARAMETER_RECORDS.tsv", record_fields, record_rows)
    write_tsv(output / "STRUCTURAL_BLOCK_MAPPINGS.tsv", [
        "context_id", "archive_path", "member_name", "source_block_index", "target_block_index",
        "exact_parameter_overlap", "source_parameter_count", "target_parameter_count", "same_index", "mapping_status",
    ], block_rows)
    write_tsv(output / "STRUCTURAL_MEMBER_CANDIDATES.tsv", [
        "context_id", "archive_path", "member_name", "source_sha256", "target_sha256",
        "target_distance_to_original", "candidate_mode", "candidate_available", "candidate_size",
        "candidate_sha256", "candidate_distance_to_original", "distance_improvement", "exact_original",
        "selected_row_count", "deleted_record_count", "inserted_record_count", "unresolved_reasons",
        "reverse_roundtrip", "reverse_sha256", "safe_to_build_payload_now", "runtime_validated", "semantics_inferred",
    ], candidate_rows)
    write_tsv(output / "STRUCTURAL_MATERIAL_MEMBERS.tsv", [
        "context_id", "domain", "archive_path", "member_name", "rehydration_match_basis", "source_size", "target_size",
        "source_sha256", "target_sha256", "target_distance_to_original", "structural_row_count",
        "recurrent_structural_row_count", "unique_structural_row_count", "record_validation_failures",
        "block_mapping_rows", "unique_candidate_available", "unique_candidate_sha256",
        "unique_candidate_distance_to_original", "unique_distance_improvement", "unique_reverse_roundtrip",
        "all_structural_exact_original", "all_structural_reverse_roundtrip", "classification",
        "safe_to_build_payload_now", "next_gate", "runtime_validated", "semantics_inferred",
    ], member_rows)
    write_tsv(output / "STRUCTURAL_MATERIAL_SKIPPED.tsv", ["context_id", "archive_path", "member_name", "reason"], skipped_rows)

    counts = Counter(str(row.get("classification", "")) for row in member_rows)
    unique_ready_rows = [row for row in member_rows if row.get("classification") == "unique_structural_inverse_candidate_ready_for_narrow_followup"]
    summary = {
        "type": "br_quartet_restoration_structural_material_parameter_evidence_summary",
        "format_version": 1,
        "tool_version": TOOL_VERSION,
        "source_stage74_tool_version": stage74_summary.get("tool_version"),
        "status": "structural_material_parameter_occurrence_audit_complete_no_payload_written_runtime_deferred",
        "source_structural_rows": len(structural_rows),
        "audited_member_rows": len(member_rows),
        "record_rows": len(record_rows),
        "record_validation_failures": sum(str(row.get("record_validation")) != "passed" for row in record_rows),
        "recurrent_record_rows": sum(parse_bool(row.get("recurrent")) for row in record_rows),
        "unique_record_rows": sum(not parse_bool(row.get("recurrent")) for row in record_rows),
        "candidate_rows": len(candidate_rows),
        "unique_followup_candidate_member_rows": len(unique_ready_rows),
        "exact_original_all_structural_member_rows": sum(parse_bool(row.get("all_structural_exact_original")) for row in member_rows),
        "skipped_rows": len(skipped_rows),
        "stable_rehydration_fallback_member_rows": sum(
            str(row.get("rehydration_match_basis", "")).startswith("stable_archive_member")
            for row in member_rows
        ),
        "member_classification_counts": dict(sorted(counts.items())),
        "recurrent_threshold": RECURRENT_THRESHOLD,
        "policy": {
            "installed_game_modified": False,
            "g1m_payload_written": False,
            "parent_elixir_rebuilt": False,
            "pak_repacked": False,
            "core_registry_modified": False,
            "profile_activated": False,
            "runtime_validation_inferred": False,
            "censorship_semantics_inferred": False,
            "quartet_variant_rows_rebuilt": False,
            "recurrent_mesh_blend_additions_promoted": False,
            "canary_track_modified": False,
        },
        "next_action": (
            "Upload this report. Recurrent parameterForMeshBlend additions remain evidence-only. "
            "Only a unique scene-local structural inverse that strictly improves the member and reverses exactly "
            "may receive a separate local prototype stage after review."
        ),
    }
    atomic_json(output / "SUMMARY.json", summary)
    return output, summary


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit structural wet/water G1M parameter records")
    parser.add_argument("--project-root", type=Path, default=PROJECT_ROOT_DEFAULT)
    parser.add_argument("--workspace-root", type=Path)
    parser.add_argument("--report-root", type=Path)
    parser.add_argument("--rules-file", type=Path)
    parser.add_argument("--maximum-earc-bytes", type=int, default=512 * 1024 * 1024)
    parser.add_argument("--no-report-archive", action="store_true")
    args = parser.parse_args()

    project_root = args.project_root.expanduser().resolve()
    workspace_root = (args.workspace_root or project_root / ".local/build/quartet_restoration").expanduser().resolve()
    report_root = (args.report_root or project_root / ".local/reports/quartet_restoration").expanduser().resolve()
    output, summary = collect(
        project_root=project_root,
        workspace_root=workspace_root,
        report_root=report_root,
        rules_file=args.rules_file,
        maximum_earc_bytes=args.maximum_earc_bytes,
    )
    archive: Path | None = None
    if not args.no_report_archive:
        archive = report_root / REPORT_NAME
        make_report_archive(output, archive)
    print(f"Structural rows audited: {summary['source_structural_rows']}")
    print(f"G1M members audited: {summary['audited_member_rows']}")
    print(f"Recurrent structural records: {summary['recurrent_record_rows']}")
    print(f"Unique structural records: {summary['unique_record_rows']}")
    print(f"Unique follow-up members: {summary['unique_followup_candidate_member_rows']}")
    print(f"Report directory: {output}")
    if archive:
        print(f"Report: {archive}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except StructuralMaterialError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
