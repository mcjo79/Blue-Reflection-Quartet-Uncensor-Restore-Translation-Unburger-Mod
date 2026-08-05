#!/usr/bin/env python3
"""Local dry-transfer workspace and wet positive-control schema locator.

This stage consumes the validated 0.0.7-0.0.11 evidence. It selectively reads
only the BKN dry source parent/G1T and the TWL wet source/target parents. It
creates a local-only dry transfer workspace, verifies a wrapper round-trip for
the source Elixir, and emits metadata-only byte-range evidence for Quartet's wet
G1M/SWG augmentation. It never writes to either game, repacks a containing PAK,
authorizes a profile, or includes raw assets in the evidence archive.
"""
from __future__ import annotations

import argparse
import csv
import difflib
import hashlib
import json
import shutil
import struct
import subprocess
import sys
import tarfile
import tempfile
import zlib
from collections import Counter
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT_DEFAULT = SCRIPT_DIR.parent.parent
TEXT_TOOL_DIR = PROJECT_ROOT_DEFAULT / "Blue_Reflection_Text_Tool"
for item in (SCRIPT_DIR, TEXT_TOOL_DIR):
    if str(item) not in sys.path:
        sys.path.insert(0, str(item))

import br_dlc_nested_container_tool as NESTED  # noqa: E402
import br_restoration_tool as BR  # noqa: E402

TOOL_VERSION = "0.0.12"
FORMAT_VERSION = 1
REPORT_DIR_NAME = "transfer_probe_evidence"
REPORT_ARCHIVE_NAME = "BR_quartet_legacy_dlc_transfer_probe_evidence.tar.zst"
BUILD_RELATIVE = Path(".local/build/quartet_legacy_dlc/transfer_probes/costume_pc00_bkn_dry")
FORBIDDEN_REPORT_SUFFIXES = {
    ".pak", ".ebm", ".ebd", ".g1m", ".g1t", ".g1a", ".g1e", ".g1s",
    ".elixir", ".gz", ".bin", ".swg", ".dds", ".wav", ".ogg",
}


class TransferProbeError(RuntimeError):
    pass


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def scalar(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (list, tuple, set, dict)):
        return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return str(value)


def read_tsv(path: Path) -> list[dict[str, str]]:
    if not path.is_file():
        raise TransferProbeError(f"missing prerequisite TSV: {path}")
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return [dict(row) for row in csv.DictReader(handle, delimiter="\t")]


def write_tsv(path: Path, fields: Sequence[str], rows: Iterable[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(fields), delimiter="\t", lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow({field: scalar(row.get(field, "")) for field in fields})


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")


def clean_dir(path: Path) -> None:
    if path.exists():
        shutil.rmtree(path)
    path.mkdir(parents=True, exist_ok=True)


def locate(report_root: Path, directory: str, archive: str, temporary: Path) -> Path:
    direct = report_root / directory
    if direct.is_dir():
        return direct
    packed = report_root / archive
    if not packed.is_file():
        raise TransferProbeError(f"missing prerequisite report: {direct} / {packed}")
    extract_root = temporary / directory
    extract_root.mkdir(parents=True, exist_ok=True)
    subprocess.run(["tar", "--zstd", "-xf", str(packed), "-C", str(extract_root)], check=True)
    expected = extract_root / directory
    if expected.is_dir():
        return expected
    candidates = [item for item in extract_root.iterdir() if item.is_dir()]
    if len(candidates) == 1:
        return candidates[0]
    raise TransferProbeError(f"could not locate extracted prerequisite for {packed}")


def make_archive(source: Path, output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="br_dlc_transfer_bundle_") as temp_name:
        temp_tar = Path(temp_name) / "report.tar"
        with tarfile.open(temp_tar, "w", format=tarfile.PAX_FORMAT) as archive:
            for path in sorted(source.rglob("*"), key=lambda p: p.relative_to(source).as_posix().casefold()):
                if not path.is_file():
                    continue
                info = archive.gettarinfo(str(path), arcname=f"{source.name}/{path.relative_to(source).as_posix()}")
                info.uid = info.gid = 0
                info.uname = info.gname = ""
                info.mtime = 0
                with path.open("rb") as handle:
                    archive.addfile(info, handle)
        subprocess.run(["zstd", "-q", "-f", "-19", str(temp_tar), "-o", str(output)], check=True)


def report_manifest(report_root: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for path in sorted(report_root.rglob("*"), key=lambda p: p.relative_to(report_root).as_posix().casefold()):
        if not path.is_file() or path.name == "REPORT_MANIFEST.json":
            continue
        if {suffix.casefold() for suffix in path.suffixes} & FORBIDDEN_REPORT_SUFFIXES:
            raise TransferProbeError(f"raw asset-like file in evidence report: {path}")
        rows.append({
            "path": path.relative_to(report_root).as_posix(),
            "size": path.stat().st_size,
            "sha256": sha256_file(path),
        })
    return rows


def gust_chunk_layout(raw: bytes, label: str) -> tuple[bytes, list[int], list[int]]:
    cursor = 0
    decoded = bytearray()
    decoded_sizes: list[int] = []
    compressed_sizes: list[int] = []
    while True:
        if cursor + 4 > len(raw):
            raise TransferProbeError(f"truncated Gust chunk header: {label}")
        size = int.from_bytes(raw[cursor:cursor + 4], "little")
        cursor += 4
        if size == 0:
            if cursor != len(raw):
                raise TransferProbeError(f"trailing data after Gust chunk terminator: {label}")
            break
        if size <= 0 or cursor + size > len(raw):
            raise TransferProbeError(f"invalid Gust chunk size {size}: {label}")
        compressed = raw[cursor:cursor + size]
        cursor += size
        try:
            chunk = zlib.decompress(compressed)
        except zlib.error as exc:
            raise TransferProbeError(f"invalid Gust zlib chunk: {label}: {exc}") from exc
        compressed_sizes.append(size)
        decoded_sizes.append(len(chunk))
        decoded.extend(chunk)
    if not decoded_sizes:
        raise TransferProbeError(f"empty Gust chunk stream: {label}")
    return bytes(decoded), decoded_sizes, compressed_sizes


def encode_gust_chunks(decoded: bytes, decoded_sizes: Sequence[int]) -> bytes:
    if sum(decoded_sizes) != len(decoded):
        raise TransferProbeError("decoded chunk sizes do not cover the payload")
    output = bytearray()
    cursor = 0
    for size in decoded_sizes:
        if size <= 0:
            raise TransferProbeError("non-positive decoded chunk size")
        compressed = zlib.compress(decoded[cursor:cursor + size], level=9)
        output.extend(len(compressed).to_bytes(4, "little"))
        output.extend(compressed)
        cursor += size
    output.extend(b"\0\0\0\0")
    return bytes(output)


def copy_local_payload(path: Path, payload: bytes) -> dict[str, Any]:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)
    return {"local_path": path, "size": len(payload), "sha256": sha256_bytes(payload)}


def _name(raw: bytes) -> str:
    try:
        return raw.replace(b"\0", b"").decode("utf-8")
    except UnicodeDecodeError:
        return raw.replace(b"\0", b"").decode("cp932", errors="replace")


def parse_g1m_layout(payload: bytes, label: str) -> dict[str, Any]:
    if len(payload) < BR.G1M_HEADER_SIZE:
        raise TransferProbeError(f"G1M too small: {label}")
    try:
        endian = BR.g1m_endian_from_magic(payload[:4], label=label)
    except Exception as exc:
        raise TransferProbeError(str(exc)) from exc
    file_version, file_size, chunk_offset, reserved, chunk_count = struct.unpack_from(endian + "5I", payload, 4)
    if file_size and file_size != len(payload):
        raise TransferProbeError(f"G1M declared size mismatch for {label}: {file_size} != {len(payload)}")
    chunks: list[dict[str, Any]] = []
    parameters: list[dict[str, Any]] = []
    offset = chunk_offset
    for chunk_index in range(chunk_count):
        if offset + 12 > len(payload):
            raise TransferProbeError(f"truncated G1M chunk: {label}")
        magic = _name(payload[offset:offset + 4])
        version, chunk_size = struct.unpack_from(endian + "2I", payload, offset + 4)
        if chunk_size < 12 or offset + chunk_size > len(payload):
            raise TransferProbeError(f"invalid G1M chunk size: {label}")
        chunk_row = {
            "chunk_index": chunk_index,
            "chunk_magic": magic,
            "chunk_offset": offset,
            "chunk_size": chunk_size,
            "chunk_size_field_offset": offset + 8,
            "chunk_sha256": sha256_bytes(payload[offset:offset + chunk_size]),
        }
        chunks.append(chunk_row)
        if magic in {"G1MG", "GM1G"}:
            if chunk_size < BR.G1MG_HEADER_SIZE:
                raise TransferProbeError(f"G1MG too small: {label}")
            section_count = struct.unpack_from(endian + "I", payload, offset + 44)[0]
            section_cursor = offset + BR.G1MG_HEADER_SIZE
            for section_index in range(section_count):
                if section_cursor + 12 > offset + chunk_size:
                    raise TransferProbeError(f"truncated G1MG section: {label}")
                section_type, section_size, section_entries = struct.unpack_from(endian + "3I", payload, section_cursor)
                section_end = section_cursor + section_size
                if section_size < 12 or section_end > offset + chunk_size:
                    raise TransferProbeError(f"invalid G1MG section size: {label}")
                if section_type == BR.G1MG_SHADER_PARAMS_SECTION:
                    cursor = section_cursor + 12
                    for block_index in range(section_entries):
                        count_offset = cursor
                        parameter_count = struct.unpack_from(endian + "I", payload, cursor)[0]
                        cursor += 4
                        duplicates: Counter[str] = Counter()
                        for parameter_index in range(parameter_count):
                            start = cursor
                            if cursor + 16 > section_end:
                                raise TransferProbeError(f"truncated G1MG parameter: {label}")
                            parameter_size, name_size, unknown, buffer_type, buffer_count = struct.unpack_from(endian + "3I2H", payload, cursor)
                            widths = {1: 4, 2: 8, 3: 12, 4: 16, 5: 4}
                            width = widths.get(buffer_type)
                            if width is None:
                                raise TransferProbeError(f"unsupported G1MG buffer type {buffer_type}: {label}")
                            end = start + parameter_size
                            if parameter_size < 16 + name_size + width * buffer_count or end > section_end:
                                raise TransferProbeError(f"invalid G1MG parameter size: {label}")
                            name = _name(payload[start + 16:start + 16 + name_size])
                            folded = name.casefold()
                            occurrence = duplicates[folded]
                            duplicates[folded] += 1
                            value_offset = start + 16 + name_size
                            value_size = width * buffer_count
                            parameters.append({
                                "chunk_index": chunk_index,
                                "section_index": section_index,
                                "shader_block_index": block_index,
                                "parameter_index": parameter_index,
                                "parameter_name": name,
                                "parameter_occurrence": occurrence,
                                "parameter_key": f"{block_index}|{folded}|{occurrence}",
                                "record_offset": start,
                                "record_size": parameter_size,
                                "record_sha256": sha256_bytes(payload[start:end]),
                                "name_size": name_size,
                                "buffer_type": buffer_type,
                                "buffer_count": buffer_count,
                                "value_offset": value_offset,
                                "value_size": value_size,
                                "value_sha256": sha256_bytes(payload[value_offset:value_offset + value_size]),
                                "parameter_count_field_offset": count_offset,
                                "parameter_count": parameter_count,
                                "section_size_field_offset": section_cursor + 4,
                                "section_size": section_size,
                                "chunk_size_field_offset": offset + 8,
                                "chunk_size": chunk_size,
                                "file_size_field_offset": 8,
                                "file_size": len(payload),
                            })
                            cursor = end
                section_cursor = section_end
        offset += chunk_size
    return {
        "file_size": len(payload),
        "file_size_field_offset": 8,
        "chunk_count": chunk_count,
        "chunks": chunks,
        "parameters": parameters,
    }


def prefix_suffix_envelope(source: bytes, target: bytes) -> dict[str, int]:
    prefix = 0
    limit = min(len(source), len(target))
    while prefix < limit and source[prefix] == target[prefix]:
        prefix += 1
    suffix = 0
    while suffix < limit - prefix and source[len(source) - 1 - suffix] == target[len(target) - 1 - suffix]:
        suffix += 1
    return {
        "common_prefix": prefix,
        "common_suffix": suffix,
        "source_offset": prefix,
        "source_size": len(source) - prefix - suffix,
        "target_offset": prefix,
        "target_size": len(target) - prefix - suffix,
    }


def diff_ranges(source: bytes, target: bytes) -> list[dict[str, Any]]:
    matcher = difflib.SequenceMatcher(None, source, target, autojunk=False)
    rows: list[dict[str, Any]] = []
    rebuilt = bytearray()
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            rebuilt.extend(source[i1:i2])
            continue
        rebuilt.extend(target[j1:j2])
        rows.append({
            "operation": tag,
            "source_offset": i1,
            "source_size": i2 - i1,
            "target_offset": j1,
            "target_size": j2 - j1,
            "source_range_sha256": sha256_bytes(source[i1:i2]),
            "target_range_sha256": sha256_bytes(target[j1:j2]),
        })
    if bytes(rebuilt) != target:
        raise TransferProbeError("diff range reconstruction failed")
    return rows


def _one(rows: Sequence[dict[str, str]], **criteria: str) -> dict[str, str]:
    matches = [row for row in rows if all(row.get(key) == value for key, value in criteria.items())]
    if len(matches) != 1:
        raise TransferProbeError(f"expected one row for {criteria}, got {len(matches)}")
    return matches[0]


def _member_payload(archive: dict[str, Any], name: str) -> bytes:
    matches = [row for row in archive["members"] if str(row["name"]).casefold() == name.casefold()]
    if len(matches) != 1:
        raise TransferProbeError(f"expected one nested member {name}, got {len(matches)}")
    return bytes(matches[0]["payload"])


def audit(project_root: Path, original_root: Path, quartet_root: Path, output_root: Path) -> tuple[Path, dict[str, Any]]:
    reports = project_root / ".local/reports/quartet_legacy_dlc"
    with tempfile.TemporaryDirectory(prefix="br_dlc_transfer_prereq_") as temp_name:
        temp = Path(temp_name)
        control = locate(reports, "control_compatibility_evidence", "BR_quartet_legacy_dlc_control_compatibility_evidence.tar.zst", temp)
        bounded = locate(reports, "bounded_family_evidence", "BR_quartet_legacy_dlc_bounded_family_evidence.tar.zst", temp)
        nested = locate(reports, "nested_container_evidence", "BR_quartet_legacy_dlc_nested_container_evidence.tar.zst", temp)
        external = locate(reports, "external_dependency_closure_evidence", "BR_quartet_legacy_dlc_external_dependency_closure_evidence.tar.zst", temp)
        summaries = {
            "control": json.loads((control / "SUMMARY.json").read_text(encoding="utf-8")),
            "bounded": json.loads((bounded / "SUMMARY.json").read_text(encoding="utf-8")),
            "nested": json.loads((nested / "SUMMARY.json").read_text(encoding="utf-8")),
            "external": json.loads((external / "SUMMARY.json").read_text(encoding="utf-8")),
        }
        expected_versions = {"control": "0.0.11", "bounded": "0.0.10", "nested": "0.0.7", "external": "0.0.8"}
        for key, expected in expected_versions.items():
            if summaries[key].get("tool_version") != expected:
                raise TransferProbeError(f"expected {key} report {expected}, got {summaries[key].get('tool_version')}")

        containers = read_tsv(nested / "DLC_NESTED_CONTAINER_INVENTORY.tsv")
        bindings = read_tsv(nested / "DLC_NESTED_MEMBER_BINDINGS.tsv")
        textures = read_tsv(external / "DLC_EXTERNAL_TEXTURE_BINDINGS.tsv")
        mapping = read_tsv(control / "DLC_CONTROL_MATERIAL_BLOCK_MAPPING.tsv")
        transfer = read_tsv(control / "DLC_CANDIDATE_TRANSFER_CLASSIFICATION.tsv")

        clean_dir(output_root)
        build_root = project_root / BUILD_RELATIVE
        clean_dir(build_root)

        original_indices: dict[str, NESTED.PakIndex] = {}
        quartet_indices: dict[str, NESTED.PakIndex] = {}
        def index_for(root: Path, archive: str, cache: dict[str, NESTED.PakIndex]) -> NESTED.PakIndex:
            key = archive.replace("\\", "/").casefold()
            if key not in cache:
                path = root / archive
                if not path.is_file():
                    # tolerate case differences in DATA/Data
                    candidates = [p for p in root.rglob(Path(archive).name) if p.is_file()]
                    if len(candidates) != 1:
                        raise TransferProbeError(f"could not locate archive {archive} under {root}")
                    path = candidates[0]
                cache[key] = NESTED.index_pak(path)
            return cache[key]

        dry_parent_row = _one(containers, content_id="costume_pc00_bkn", parent_role="dry_model_or_container")
        dry_texture_row = _one(textures, content_id="costume_pc00_bkn", texture_role="dry_texture")
        source_parent, parent_entry = NESTED.read_pak_member(
            index_for(original_root, dry_parent_row["source_archive"], original_indices), dry_parent_row["source_path"]
        )
        source_texture, texture_entry = NESTED.read_pak_member(
            index_for(original_root, dry_texture_row["source_archive"], original_indices), dry_texture_row["source_path"]
        )
        if sha256_bytes(source_parent) != dry_parent_row["source_sha256"] or len(source_parent) != int(dry_parent_row["source_size"]):
            raise TransferProbeError("BKN dry parent no longer matches prerequisite evidence")
        if sha256_bytes(source_texture) != dry_texture_row["source_sha256"] or len(source_texture) != int(dry_texture_row["source_size"]):
            raise TransferProbeError("BKN dry texture no longer matches prerequisite evidence")

        decoded_parent, decoded_sizes, compressed_sizes = gust_chunk_layout(source_parent, dry_parent_row["source_path"])
        roundtrip_parent = encode_gust_chunks(decoded_parent, decoded_sizes)
        roundtrip_decoded, roundtrip_sizes, _ = gust_chunk_layout(roundtrip_parent, "roundtrip BKN dry parent")
        if roundtrip_decoded != decoded_parent or roundtrip_sizes != decoded_sizes:
            raise TransferProbeError("BKN dry parent wrapper round-trip changed decoded bytes")
        source_earc = BR.parse_earc_payload(decoded_parent, label="BKN dry source", include_member_payloads=True)
        roundtrip_earc = BR.parse_earc_payload(roundtrip_decoded, label="BKN dry roundtrip", include_member_payloads=True)
        if [(r["name"], r["sha256"], r["size"]) for r in source_earc["members"]] != [(r["name"], r["sha256"], r["size"]) for r in roundtrip_earc["members"]]:
            raise TransferProbeError("BKN dry parent nested inventory changed during round-trip")

        exact_parent_path = build_root / "source_exact" / dry_parent_row["source_path"]
        roundtrip_parent_path = build_root / "roundtrip" / dry_parent_row["source_path"]
        texture_path = build_root / "source_exact" / dry_texture_row["source_path"]
        exact_parent_meta = copy_local_payload(exact_parent_path, source_parent)
        roundtrip_meta = copy_local_payload(roundtrip_parent_path, roundtrip_parent)
        texture_meta = copy_local_payload(texture_path, source_texture)
        workspace_rows = [
            {
                "content_id": "costume_pc00_bkn", "payload_role": "dry_parent_source_exact",
                "source_archive": dry_parent_row["source_archive"], "source_member": dry_parent_row["source_path"],
                "local_path": exact_parent_path.relative_to(project_root).as_posix(), "size": exact_parent_meta["size"],
                "sha256": exact_parent_meta["sha256"], "decoded_sha256": sha256_bytes(decoded_parent),
                "decoded_roundtrip_identical": True, "target_pak_repacked": False, "game_modified": False,
            },
            {
                "content_id": "costume_pc00_bkn", "payload_role": "dry_parent_wrapper_roundtrip",
                "source_archive": dry_parent_row["source_archive"], "source_member": dry_parent_row["source_path"],
                "local_path": roundtrip_parent_path.relative_to(project_root).as_posix(), "size": roundtrip_meta["size"],
                "sha256": roundtrip_meta["sha256"], "decoded_sha256": sha256_bytes(roundtrip_decoded),
                "decoded_roundtrip_identical": True, "target_pak_repacked": False, "game_modified": False,
            },
            {
                "content_id": "costume_pc00_bkn", "payload_role": "dry_external_texture_source_exact",
                "source_archive": dry_texture_row["source_archive"], "source_member": dry_texture_row["source_path"],
                "local_path": texture_path.relative_to(project_root).as_posix(), "size": texture_meta["size"],
                "sha256": texture_meta["sha256"], "decoded_sha256": "",
                "decoded_roundtrip_identical": "", "target_pak_repacked": False, "game_modified": False,
            },
        ]
        nested_roundtrip_rows = []
        for row in source_earc["members"]:
            nested_roundtrip_rows.append({
                "content_id": "costume_pc00_bkn", "parent_role": "dry_model_or_container",
                "member_key": row["comparison_key"], "member_name": row["name"], "member_size": row["size"],
                "source_sha256": row["sha256"], "roundtrip_sha256": row["sha256"],
                "roundtrip_identical": True, "raw_payload_exported_in_report": False,
            })

        wet_source_row = _one(containers, content_id="costume_pc00_twl", parent_role="wet_model_or_container")
        source_wet_raw, _ = NESTED.read_pak_member(
            index_for(original_root, wet_source_row["source_archive"], original_indices), wet_source_row["source_path"]
        )
        target_wet_raw, _ = NESTED.read_pak_member(
            index_for(quartet_root, wet_source_row["target_archive"], quartet_indices), wet_source_row["target_path"]
        )
        if sha256_bytes(source_wet_raw) != wet_source_row["source_sha256"]:
            raise TransferProbeError("TWL wet source parent mismatch")
        source_wet_decoded, _, _ = NESTED.decode_container_bytes(source_wet_raw, wet_source_row["source_path"])
        target_wet_decoded, _, _ = NESTED.decode_container_bytes(target_wet_raw, wet_source_row["target_path"])
        if sha256_bytes(target_wet_decoded) != wet_source_row["target_decoded_sha256"]:
            raise TransferProbeError("TWL wet target decoded parent mismatch")
        source_wet_earc = BR.parse_earc_payload(source_wet_decoded, label="TWL wet source", include_member_payloads=True)
        target_wet_earc = BR.parse_earc_payload(target_wet_decoded, label="TWL wet target", include_member_payloads=True)
        source_members = {str(row["name"]).casefold(): row for row in source_wet_earc["members"]}
        target_members = {str(row["name"]).casefold(): row for row in target_wet_earc["members"]}

        parameter_rows: list[dict[str, Any]] = []
        envelope_rows: list[dict[str, Any]] = []
        swg_rows: list[dict[str, Any]] = []
        modified_control_rows = [
            row for row in bindings
            if row["content_id"] == "costume_pc00_twl"
            and row["parent_path"] == wet_source_row["source_path"]
            and row["compatibility_status"] == "present_modified"
        ]
        for binding in modified_control_rows:
            name = binding["member_name"]
            source_member = source_members.get(name.casefold())
            target_member = target_members.get(name.casefold())
            if not source_member or not target_member:
                raise TransferProbeError(f"modified TWL wet member missing from parent: {name}")
            source_payload = bytes(source_member["payload"])
            target_payload = bytes(target_member["payload"])
            if name.casefold().endswith(".g1m"):
                source_layout = parse_g1m_layout(source_payload, f"source {name}")
                target_layout = parse_g1m_layout(target_payload, f"target {name}")
                source_params = {str(row["parameter_key"]): row for row in source_layout["parameters"]}
                for row in target_layout["parameters"]:
                    if row["parameter_key"] in source_params:
                        continue
                    if str(row["parameter_name"]).casefold() != "parameterformeshblend":
                        continue
                    source_count = ""
                    same_block = [p for p in source_layout["parameters"] if p["shader_block_index"] == row["shader_block_index"]]
                    if same_block:
                        source_count = same_block[0]["parameter_count"]
                    parameter_rows.append({
                        "content_id": "costume_pc00_twl", "member_name": name,
                        "shader_block_index": row["shader_block_index"], "parameter_key": row["parameter_key"],
                        "target_record_offset": row["record_offset"], "target_record_size": row["record_size"],
                        "target_record_sha256": row["record_sha256"], "target_value_sha256": row["value_sha256"],
                        "source_parameter_count": source_count, "target_parameter_count": row["parameter_count"],
                        "parameter_count_field_offset": row["parameter_count_field_offset"],
                        "section_size_field_offset": row["section_size_field_offset"],
                        "chunk_size_field_offset": row["chunk_size_field_offset"],
                        "file_size_field_offset": row["file_size_field_offset"],
                        "semantic_assignment": "unassigned_quartet_wet_schema_augmentation",
                        "raw_record_exported": False,
                    })
                source_chunks = {row["chunk_index"]: row for row in source_layout["chunks"]}
                for target_chunk in target_layout["chunks"]:
                    source_chunk = source_chunks.get(target_chunk["chunk_index"])
                    if not source_chunk:
                        continue
                    source_chunk_bytes = source_payload[source_chunk["chunk_offset"]:source_chunk["chunk_offset"] + source_chunk["chunk_size"]]
                    target_chunk_bytes = target_payload[target_chunk["chunk_offset"]:target_chunk["chunk_offset"] + target_chunk["chunk_size"]]
                    if source_chunk_bytes == target_chunk_bytes:
                        continue
                    env = prefix_suffix_envelope(source_chunk_bytes, target_chunk_bytes)
                    envelope_rows.append({
                        "content_id": "costume_pc00_twl", "member_name": name,
                        "chunk_index": target_chunk["chunk_index"], "chunk_magic": target_chunk["chunk_magic"],
                        "source_chunk_offset": source_chunk["chunk_offset"], "target_chunk_offset": target_chunk["chunk_offset"],
                        "source_chunk_size": source_chunk["chunk_size"], "target_chunk_size": target_chunk["chunk_size"],
                        **env,
                        "source_changed_range_sha256": sha256_bytes(source_chunk_bytes[env["source_offset"]:env["source_offset"] + env["source_size"]]),
                        "target_changed_range_sha256": sha256_bytes(target_chunk_bytes[env["target_offset"]:env["target_offset"] + env["target_size"]]),
                        "exact_semantics_proven": False,
                    })
            elif name.casefold().endswith(".swg"):
                for index, row in enumerate(diff_ranges(source_payload, target_payload)):
                    swg_rows.append({
                        "content_id": "costume_pc00_twl", "member_name": name, "range_index": index,
                        **row, "size_delta": row["target_size"] - row["source_size"],
                        "semantic_assignment": "unassigned_cloth_structure_envelope",
                        "forward_reconstruction_verified": True, "raw_range_exported": False,
                    })

        plan_rows: list[dict[str, Any]] = []
        for row in mapping:
            if row["content_id"] != "costume_pc00_bkn" or row["parent_role"] != "wet_model_or_container":
                continue
            status = row["transitive_mapping_status"]
            if status == "unique_control_bridge" and "parameterForMeshBlend" in row["target_control_added_parameters"]:
                action = "mapped_parameter_record_insertion_candidate"
                blocker = "requires exact binary reconstruction and target parser round-trip"
            elif status == "ambiguous_control_bridge":
                action = "blocked_ambiguous_material_block"
                blocker = "multiple control blocks share the same source signature"
            else:
                action = "blocked_unresolved_material_block"
                blocker = "no unique positive-control bridge"
            plan_rows.append({
                "content_id": "costume_pc00_bkn", "candidate_component": "wet_g1m_material_block",
                "member_part": row["member_part"], "candidate_block_index": row["candidate_block_index"],
                "control_bridge_status": status, "conversion_action": action,
                "required_control_delta": row["target_control_added_parameters"],
                "remaining_blocker": blocker, "converted_payload_built": False,
                "profile_build_allowed": False,
            })
        plan_rows.extend([
            {
                "content_id": "costume_pc00_bkn", "candidate_component": "wet_base_g1m_envelope",
                "member_part": "base", "candidate_block_index": "", "control_bridge_status": "unparsed_control_size_augmentation",
                "conversion_action": "blocked_byte_range_semantics_unknown", "required_control_delta": "Quartet TWL base G1M +156-byte structural envelope",
                "remaining_blocker": "positive control contains non-parameter structural additions not parsed by the bounded G1MG parameter parser",
                "converted_payload_built": False, "profile_build_allowed": False,
            },
            {
                "content_id": "costume_pc00_bkn", "candidate_component": "wet_swg_envelope",
                "member_part": "cloth_structure", "candidate_block_index": "", "control_bridge_status": "exact_control_delta_ranges_located",
                "conversion_action": "blocked_semantics_unassigned", "required_control_delta": f"{sum(int(r['size_delta']) for r in swg_rows)}-byte net TWL SWG augmentation",
                "remaining_blocker": "field meaning and safe BKN insertion location are not proven",
                "converted_payload_built": False, "profile_build_allowed": False,
            },
            {
                "content_id": "costume_pc00_bkn", "candidate_component": "wet_external_texture",
                "member_part": "external_texture", "candidate_block_index": "", "control_bridge_status": "texture_slot_binding_unresolved",
                "conversion_action": "blocked_exact_slot_binding", "required_control_delta": "none assigned",
                "remaining_blocker": "stable G1M-to-G1T KTID/index binding is not proven",
                "converted_payload_built": False, "profile_build_allowed": False,
            },
        ])

        write_tsv(output_root / "DLC_BKN_DRY_TRANSFER_WORKSPACE.tsv", [
            "content_id", "payload_role", "source_archive", "source_member", "local_path", "size", "sha256",
            "decoded_sha256", "decoded_roundtrip_identical", "target_pak_repacked", "game_modified",
        ], workspace_rows)
        write_tsv(output_root / "DLC_BKN_DRY_PARENT_ROUNDTRIP.tsv", [
            "content_id", "parent_role", "member_key", "member_name", "member_size", "source_sha256",
            "roundtrip_sha256", "roundtrip_identical", "raw_payload_exported_in_report",
        ], nested_roundtrip_rows)
        write_tsv(output_root / "DLC_TWL_WET_G1M_PARAMETER_INSERT_RANGES.tsv", [
            "content_id", "member_name", "shader_block_index", "parameter_key", "target_record_offset",
            "target_record_size", "target_record_sha256", "target_value_sha256", "source_parameter_count",
            "target_parameter_count", "parameter_count_field_offset", "section_size_field_offset",
            "chunk_size_field_offset", "file_size_field_offset", "semantic_assignment", "raw_record_exported",
        ], parameter_rows)
        write_tsv(output_root / "DLC_TWL_WET_G1M_CHUNK_ENVELOPES.tsv", [
            "content_id", "member_name", "chunk_index", "chunk_magic", "source_chunk_offset", "target_chunk_offset",
            "source_chunk_size", "target_chunk_size", "common_prefix", "common_suffix", "source_offset", "source_size",
            "target_offset", "target_size", "source_changed_range_sha256", "target_changed_range_sha256",
            "exact_semantics_proven",
        ], envelope_rows)
        write_tsv(output_root / "DLC_TWL_WET_SWG_DELTA_RANGES.tsv", [
            "content_id", "member_name", "range_index", "operation", "source_offset", "source_size", "target_offset",
            "target_size", "source_range_sha256", "target_range_sha256", "size_delta", "semantic_assignment",
            "forward_reconstruction_verified", "raw_range_exported",
        ], swg_rows)
        write_tsv(output_root / "DLC_BKN_WET_CONVERSION_PLAN.tsv", [
            "content_id", "candidate_component", "member_part", "candidate_block_index", "control_bridge_status",
            "conversion_action", "required_control_delta", "remaining_blocker", "converted_payload_built",
            "profile_build_allowed",
        ], plan_rows)
        gaps = [
            {"content_id": "costume_pc00_bkn", "dependency_type": "containing_target_pak_repack", "status": "not_started", "next_evidence_needed": "insert dry parent and dry G1T into a local copy of the correct Quartet PAK and verify every member", "profile_build_allowed": False},
            {"content_id": "costume_pc00_bkn", "dependency_type": "wet_base_g1m_schema", "status": "unresolved", "next_evidence_needed": "parse or reconstruct the non-material structural additions in the TWL wet base G1M", "profile_build_allowed": False},
            {"content_id": "costume_pc00_bkn", "dependency_type": "wet_swg_semantics", "status": "unresolved", "next_evidence_needed": "identify safe owner-relative insertion position without assigning unsupported cloth semantics", "profile_build_allowed": False},
            {"content_id": "costume_pc00_bkn", "dependency_type": "texture_slot_ui_unlock_runtime", "status": "unresolved", "next_evidence_needed": "prove G1M-to-G1T binding, owner UI, availability chain and later transactional runtime behavior", "profile_build_allowed": False},
        ]
        write_tsv(output_root / "DLC_TRANSFER_PROBE_GAPS.tsv", [
            "content_id", "dependency_type", "status", "next_evidence_needed", "profile_build_allowed",
        ], gaps)

        write_json(build_root / "TRANSFER_PROBE.json", {
            "type": "br_quartet_legacy_dlc_local_dry_transfer_probe",
            "format_version": 1,
            "tool_version": TOOL_VERSION,
            "content_id": "costume_pc00_bkn",
            "source_parent": exact_parent_path.relative_to(project_root).as_posix(),
            "roundtrip_parent": roundtrip_parent_path.relative_to(project_root).as_posix(),
            "source_texture": texture_path.relative_to(project_root).as_posix(),
            "source_parent_sha256": sha256_bytes(source_parent),
            "roundtrip_parent_sha256": sha256_bytes(roundtrip_parent),
            "decoded_parent_sha256": sha256_bytes(decoded_parent),
            "dry_texture_sha256": sha256_bytes(source_texture),
            "decoded_chunk_sizes": decoded_sizes,
            "source_compressed_chunk_sizes_sha256": sha256_bytes(json.dumps(compressed_sizes, separators=(",", ":")).encode()),
            "roundtrip_compressed_bytes_may_differ": True,
            "target_pak_repacked": False,
            "profile_built": False,
            "game_modified": False,
        })

        summary = {
            "type": "br_quartet_legacy_dlc_transfer_probe_summary",
            "format_version": FORMAT_VERSION,
            "tool_version": TOOL_VERSION,
            "status": "dry_local_workspace_built_and_wet_control_schema_ranges_located",
            "dry_workspace_payload_rows": len(workspace_rows),
            "dry_parent_nested_roundtrip_rows": len(nested_roundtrip_rows),
            "dry_parent_decoded_roundtrip_identical": True,
            "dry_parent_source_compressed_sha256": sha256_bytes(source_parent),
            "dry_parent_roundtrip_compressed_sha256": sha256_bytes(roundtrip_parent),
            "dry_parent_compressed_byte_identical": source_parent == roundtrip_parent,
            "dry_texture_sha256": sha256_bytes(source_texture),
            "wet_added_parameter_records": len(parameter_rows),
            "wet_changed_g1m_chunk_envelopes": len(envelope_rows),
            "wet_swg_delta_ranges": len(swg_rows),
            "wet_swg_net_size_delta": sum(int(row["size_delta"]) for row in swg_rows),
            "bkn_wet_conversion_plan_rows": len(plan_rows),
            "conversion_action_counts": dict(sorted(Counter(str(row["conversion_action"]) for row in plan_rows).items())),
            "local_build_root": BUILD_RELATIVE.as_posix(),
            "findings": [
                "the exact BKN dry parent and external G1T were copied only to the local build workspace",
                "the BKN dry parent wrapper round-trip preserves decoded EARC bytes and every nested member",
                "Quartet wet control parameterForMeshBlend records are located by exact target offsets and hashes",
                "the TWL wet SWG delta ranges are exactly reconstructible but retain unassigned semantics",
                "no containing Quartet PAK was repacked and no BKN wet conversion payload was built",
            ],
            "policy": {
                "raw_assets_in_local_build": True,
                "raw_assets_exported_in_report": False,
                "raw_assets_in_update": False,
                "target_pak_repacked": False,
                "profile_built": False,
                "profile_build_allowed": False,
                "profiles_activated": False,
                "game_modified": False,
                "git_modified": False,
                "text_seed_unchanged": True,
            },
            "next_action": "prepare a checksum-gated local target-PAK insertion test for the dry BKN parent/G1T; keep wet conversion blocked until base-G1M, SWG and texture-slot evidence is complete",
        }
        write_json(output_root / "SUMMARY.json", summary)
        write_json(output_root / "REPORT_MANIFEST.json", {
            "type": "br_report_manifest", "format_version": 1, "files": report_manifest(output_root)
        })

    archive = reports / REPORT_ARCHIVE_NAME
    make_archive(output_root, archive)
    return archive, summary


def validate_report(report_root: Path) -> dict[str, Any]:
    required = {
        "DLC_BKN_DRY_TRANSFER_WORKSPACE.tsv", "DLC_BKN_DRY_PARENT_ROUNDTRIP.tsv",
        "DLC_TWL_WET_G1M_PARAMETER_INSERT_RANGES.tsv", "DLC_TWL_WET_G1M_CHUNK_ENVELOPES.tsv",
        "DLC_TWL_WET_SWG_DELTA_RANGES.tsv", "DLC_BKN_WET_CONVERSION_PLAN.tsv",
        "DLC_TRANSFER_PROBE_GAPS.tsv", "SUMMARY.json", "REPORT_MANIFEST.json",
    }
    missing = sorted(name for name in required if not (report_root / name).is_file())
    if missing:
        raise TransferProbeError("missing report files: " + ", ".join(missing))
    summary = json.loads((report_root / "SUMMARY.json").read_text(encoding="utf-8"))
    if summary.get("tool_version") != TOOL_VERSION:
        raise TransferProbeError("tool version mismatch")
    policy = summary.get("policy", {})
    for key in ("raw_assets_exported_in_report", "target_pak_repacked", "profile_built", "profile_build_allowed", "profiles_activated", "game_modified", "git_modified"):
        if policy.get(key) is not False:
            raise TransferProbeError(f"forbidden policy state: {key}")
    if summary.get("dry_parent_decoded_roundtrip_identical") is not True:
        raise TransferProbeError("dry parent decoded round-trip did not pass")
    workspace = read_tsv(report_root / "DLC_BKN_DRY_TRANSFER_WORKSPACE.tsv")
    if len(workspace) != 3 or any(row["target_pak_repacked"] != "false" for row in workspace):
        raise TransferProbeError("invalid dry transfer workspace rows")
    roundtrip = read_tsv(report_root / "DLC_BKN_DRY_PARENT_ROUNDTRIP.tsv")
    if not roundtrip or any(row["roundtrip_identical"] != "true" for row in roundtrip):
        raise TransferProbeError("nested dry parent round-trip failure")
    plan = read_tsv(report_root / "DLC_BKN_WET_CONVERSION_PLAN.tsv")
    if not plan or any(row["profile_build_allowed"] != "false" or row["converted_payload_built"] != "false" for row in plan):
        raise TransferProbeError("wet plan improperly authorizes a payload/profile")
    manifest = json.loads((report_root / "REPORT_MANIFEST.json").read_text(encoding="utf-8"))
    expected = {row["path"]: row for row in manifest.get("files", [])}
    for path in report_root.iterdir():
        if not path.is_file() or path.name == "REPORT_MANIFEST.json":
            continue
        row = expected.get(path.name)
        if not row or row["sha256"] != sha256_file(path) or int(row["size"]) != path.stat().st_size:
            raise TransferProbeError(f"manifest mismatch: {path.name}")
        if {suffix.casefold() for suffix in path.suffixes} & FORBIDDEN_REPORT_SUFFIXES:
            raise TransferProbeError(f"raw asset in report: {path.name}")
    return summary


def main() -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    audit_parser = sub.add_parser("audit")
    audit_parser.add_argument("--project-root", type=Path, default=PROJECT_ROOT_DEFAULT)
    audit_parser.add_argument("--original-root", type=Path, required=True)
    audit_parser.add_argument("--quartet-root", type=Path, required=True)
    audit_parser.add_argument("--output-root", type=Path)
    validate_parser = sub.add_parser("validate-report")
    validate_parser.add_argument("--report-root", type=Path, required=True)
    bundle_parser = sub.add_parser("bundle-report")
    bundle_parser.add_argument("--report-root", type=Path, required=True)
    bundle_parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "audit":
        project = args.project_root.resolve()
        output = args.output_root or project / ".local/reports/quartet_legacy_dlc" / REPORT_DIR_NAME
        archive, summary = audit(project, args.original_root.resolve(), args.quartet_root.resolve(), output)
        print(f"Dry workspace payloads: {summary['dry_workspace_payload_rows']}")
        print(f"Wet parameter records: {summary['wet_added_parameter_records']}")
        print(f"Report: {archive}")
    elif args.command == "validate-report":
        print(json.dumps(validate_report(args.report_root), sort_keys=True))
    else:
        validate_report(args.report_root)
        make_archive(args.report_root, args.output)
        print(args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
