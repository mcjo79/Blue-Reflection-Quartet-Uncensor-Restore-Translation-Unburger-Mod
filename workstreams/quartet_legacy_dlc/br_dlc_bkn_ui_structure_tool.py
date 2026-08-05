#!/usr/bin/env python3
"""Read-only KSCL/KSLT structural classification for BKN UI index hits.

Stage 40 found isolated BKN/TWL/SCL integer values but no bounded ordered
sequence in the selected costume UI members. This stage reopens the same ten
hash-gated members, parses only their KSCL/KSLT structural envelope, classifies
all prior integer hits and source/target differences by structural region, and
compares embedded texture-table metadata without exporting payload bytes.

The parser is deliberately metadata-only. It does not infer UI ownership from
an integer collision, texture name, texture index, or changed texture payload.
No UI, table, PAK, module, profile, Translation record, Git state, or installed
game file is modified.
"""
from __future__ import annotations

import argparse
import bisect
import contextlib
import csv
import hashlib
import json
import shutil
import struct
import subprocess
import sys
import tarfile
import tempfile
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Iterator, Mapping, Sequence

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT_DEFAULT = SCRIPT_DIR.parent.parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import br_dlc_bkn_ui_index_tool as STAGE40  # noqa: E402

TOOL_VERSION = "0.0.18"
FORMAT_VERSION = 1
REPORT_DIR_NAME = "bkn_ui_structure_evidence"
REPORT_ARCHIVE_NAME = "BR_quartet_legacy_dlc_bkn_ui_structure_evidence.tar.zst"

KSCL_MAGIC = 0x4B53434C
KSLT_MAGIC = 0x4B534C54
KSCL_HEADER_SIZE = 0x8C
KSLT_HEADER_SIZE = 0x40
KSLT_TABLE_ENTRY_SIZE = 0x14
TEXTURE_HEADER_SIZE = 0x48
MAX_TEXTURES = 4096

FORBIDDEN_REPORT_SUFFIXES = {
    ".pak", ".ebm", ".ebd", ".g1m", ".g1t", ".g1a", ".g1e", ".g1s",
    ".elixir", ".gz", ".bin", ".swg", ".dds", ".wav", ".ogg", ".exe", ".dll",
    ".kscl", ".kslt",
}


class BknUiStructureError(RuntimeError):
    pass


@dataclass(frozen=True)
class Region:
    start: int
    end: int
    role: str
    texture_index: int | None = None
    texture_name: str = ""
    texture_name_sha256: str = ""

    @property
    def size(self) -> int:
        return self.end - self.start


@dataclass(frozen=True)
class ParsedUi:
    file_kind: str
    size: int
    kscl_length: int | None
    kslt_base: int
    texture_count: int
    headerless_size: int
    table_pointer: int
    name_length: int
    name_count: int
    table_base: int
    names_base: int
    names_end: int
    textures: tuple[dict[str, Any], ...]
    regions: tuple[Region, ...]


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def scalar(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (list, tuple, set, dict)):
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return str(value)


def write_tsv(path: Path, fields: Sequence[str], rows: Iterable[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(fields), delimiter="\t", lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow({field: scalar(row.get(field, "")) for field in fields})


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def read_tsv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def clean_dir(path: Path) -> None:
    if path.exists():
        shutil.rmtree(path)
    path.mkdir(parents=True, exist_ok=True)


def make_archive(source: Path, output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="br_dlc_bkn_ui_structure_bundle_") as temp_name:
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


def report_manifest(root: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for path in sorted(root.rglob("*"), key=lambda p: p.relative_to(root).as_posix().casefold()):
        if path.is_file() and path.name != "REPORT_MANIFEST.json":
            rows.append({"path": path.relative_to(root).as_posix(), "size": path.stat().st_size, "sha256": sha256_file(path)})
    return rows


@contextlib.contextmanager
def prerequisite_report(project_root: Path) -> Iterator[Path]:
    parent = project_root / ".local/reports/quartet_legacy_dlc"
    direct = parent / STAGE40.REPORT_DIR_NAME
    if direct.is_dir():
        STAGE40.validate_report(direct)
        yield direct
        return
    archive = parent / STAGE40.REPORT_ARCHIVE_NAME
    if not archive.is_file():
        raise BknUiStructureError(f"missing prerequisite report: {STAGE40.REPORT_ARCHIVE_NAME}")
    with tempfile.TemporaryDirectory(prefix="br_dlc_bkn_ui_structure_prereq_") as temp_name:
        temp = Path(temp_name)
        subprocess.run(["tar", "--zstd", "-xf", str(archive), "-C", str(temp)], check=True)
        candidates = [path for path in temp.iterdir() if path.is_dir()]
        if len(candidates) != 1:
            raise BknUiStructureError("could not locate extracted stage-40 report")
        STAGE40.validate_report(candidates[0])
        yield candidates[0]


def u16(data: bytes, offset: int) -> int:
    if offset < 0 or offset + 2 > len(data):
        raise BknUiStructureError(f"out-of-range uint16 at 0x{offset:x}")
    return struct.unpack_from("<H", data, offset)[0]


def u32(data: bytes, offset: int) -> int:
    if offset < 0 or offset + 4 > len(data):
        raise BknUiStructureError(f"out-of-range uint32 at 0x{offset:x}")
    return struct.unpack_from("<I", data, offset)[0]


def read_c_string(data: bytes, offset: int, limit: int) -> tuple[str, int]:
    if offset < 0 or offset >= limit or limit > len(data):
        raise BknUiStructureError(f"out-of-range KSLT name at 0x{offset:x}")
    end = data.find(b"\0", offset, limit)
    if end < 0:
        raise BknUiStructureError(f"unterminated KSLT name at 0x{offset:x}")
    raw = data[offset:end]
    try:
        value = raw.decode("ascii")
    except UnicodeDecodeError:
        value = f"non_ascii_{hashlib.sha256(raw).hexdigest()[:16]}"
    return value, end + 1


def add_known(regions: list[Region], start: int, end: int, role: str, **kwargs: Any) -> None:
    if start < 0 or end < start:
        raise BknUiStructureError(f"invalid region {role}: 0x{start:x}-0x{end:x}")
    if end > start:
        regions.append(Region(start, end, role, **kwargs))


def fill_unclassified(size: int, known: Sequence[Region]) -> tuple[Region, ...]:
    ordered = sorted(known, key=lambda row: (row.start, row.end, row.role))
    previous_end = 0
    result: list[Region] = []
    for region in ordered:
        if region.start < previous_end:
            raise BknUiStructureError(
                f"overlapping structural regions: previous end 0x{previous_end:x}, {region.role} starts 0x{region.start:x}"
            )
        if region.start > previous_end:
            result.append(Region(previous_end, region.start, "unclassified_or_padding"))
        result.append(region)
        previous_end = region.end
    if previous_end < size:
        result.append(Region(previous_end, size, "unclassified_or_padding"))
    if previous_end > size:
        raise BknUiStructureError("structural region extends beyond file")
    return tuple(result)


def parse_kslt(data: bytes, base: int, file_kind: str, kscl_length: int | None) -> ParsedUi:
    if base < 0 or base + KSLT_HEADER_SIZE > len(data):
        raise BknUiStructureError("KSLT header is outside the member")
    if u32(data, base) != KSLT_MAGIC:
        raise BknUiStructureError(f"missing KSLT magic at 0x{base:x}")

    texture_count = u32(data, base + 8)
    headerless_size = u32(data, base + 12)
    table_pointer = u32(data, base + 16)
    name_length = u32(data, base + 20)
    name_count = u32(data, base + 24)
    if texture_count <= 0 or texture_count > MAX_TEXTURES:
        raise BknUiStructureError(f"implausible KSLT texture count: {texture_count}")

    table_base = base + table_pointer + KSLT_HEADER_SIZE
    table_end = table_base + KSLT_TABLE_ENTRY_SIZE * texture_count
    names_base = table_end
    if table_base < base + KSLT_HEADER_SIZE or table_end > len(data):
        raise BknUiStructureError("KSLT table points outside the member")

    names: list[str] = []
    cursor = names_base
    name_limit = min(len(data), names_base + name_length) if name_length else len(data)
    for index in range(texture_count):
        if cursor >= name_limit:
            names.append(f"texture_{index:03d}")
            continue
        try:
            name, cursor = read_c_string(data, cursor, name_limit)
        except BknUiStructureError:
            name = f"texture_{index:03d}"
        names.append(name or f"texture_{index:03d}")
    names_end = cursor

    textures: list[dict[str, Any]] = []
    ranges: list[tuple[int, int, int]] = []
    known: list[Region] = []
    if file_kind == "kscl_with_embedded_kslt":
        assert kscl_length is not None
        add_known(known, 0, min(KSCL_HEADER_SIZE, kscl_length), "kscl_header")
        add_known(known, min(KSCL_HEADER_SIZE, kscl_length), kscl_length, "kscl_control_body")
    add_known(known, base, base + KSLT_HEADER_SIZE, "kslt_header")
    add_known(known, table_base, table_end, "kslt_texture_table")
    add_known(known, names_base, names_end, "kslt_texture_names")

    for index in range(texture_count):
        entry = table_base + index * KSLT_TABLE_ENTRY_SIZE
        pointer = u32(data, entry)
        header = base + pointer
        if header < base or header + TEXTURE_HEADER_SIZE > len(data):
            raise BknUiStructureError(f"texture {index} header points outside the member")
        format_type = u32(data, header)
        width = u16(data, header + 4)
        height = u16(data, header + 6)
        raw_size = u32(data, header + 0x1C)
        raw_offset = header + TEXTURE_HEADER_SIZE
        raw_end = raw_offset + raw_size
        if width <= 0 or height <= 0 or width > 32768 or height > 32768:
            raise BknUiStructureError(f"texture {index} has invalid dimensions {width}x{height}")
        if raw_size <= 0 or raw_end > len(data):
            raise BknUiStructureError(f"texture {index} raw payload points outside the member")
        name = names[index]
        name_hash = sha256_bytes(name.encode("utf-8"))
        ranges.append((header, raw_end, index))
        add_known(
            known,
            header,
            raw_offset,
            "texture_header",
            texture_index=index,
            texture_name=name,
            texture_name_sha256=name_hash,
        )
        add_known(
            known,
            raw_offset,
            raw_end,
            "texture_payload",
            texture_index=index,
            texture_name=name,
            texture_name_sha256=name_hash,
        )
        textures.append({
            "index": index,
            "name": name,
            "name_sha256": name_hash,
            "table_entry_offset": entry,
            "texture_header_offset": header,
            "raw_offset": raw_offset,
            "raw_size": raw_size,
            "raw_sha256": sha256_bytes(data[raw_offset:raw_end]),
            "format_type": format_type,
            "width": width,
            "height": height,
        })

    ranges.sort()
    for previous, current in zip(ranges, ranges[1:]):
        if previous[1] > current[0]:
            raise BknUiStructureError(f"texture payload ranges overlap: {previous[2]} and {current[2]}")

    regions = fill_unclassified(len(data), known)
    return ParsedUi(
        file_kind=file_kind,
        size=len(data),
        kscl_length=kscl_length,
        kslt_base=base,
        texture_count=texture_count,
        headerless_size=headerless_size,
        table_pointer=table_pointer,
        name_length=name_length,
        name_count=name_count,
        table_base=table_base,
        names_base=names_base,
        names_end=names_end,
        textures=tuple(textures),
        regions=regions,
    )


def parse_ui_member(data: bytes) -> ParsedUi:
    if len(data) < 4:
        raise BknUiStructureError("UI member is too small")
    magic = u32(data, 0)
    if magic == KSCL_MAGIC:
        if len(data) < KSCL_HEADER_SIZE:
            raise BknUiStructureError("truncated KSCL header")
        kscl_length = u32(data, 8) + KSCL_HEADER_SIZE
        if kscl_length < KSCL_HEADER_SIZE or kscl_length + KSLT_HEADER_SIZE > len(data):
            raise BknUiStructureError("KSCL embedded KSLT offset points outside the member")
        return parse_kslt(data, kscl_length, "kscl_with_embedded_kslt", kscl_length)
    if magic == KSLT_MAGIC:
        return parse_kslt(data, 0, "standalone_kslt", None)
    raise BknUiStructureError(f"unsupported UI magic: 0x{magic:08x}")


def region_for(parsed: ParsedUi, offset: int, width: int = 1) -> tuple[str, Region | None]:
    if offset < 0 or width <= 0 or offset + width > parsed.size:
        return "outside_member", None
    starts = [row.start for row in parsed.regions]
    index = bisect.bisect_right(starts, offset) - 1
    if index < 0:
        return "outside_member", None
    region = parsed.regions[index]
    if offset >= region.start and offset + width <= region.end:
        return region.role, region
    return "cross_region", region


def classification_for_region(role: str) -> tuple[str, str]:
    if role == "texture_payload":
        return "numeric_collision_in_texture_payload", "not_owner_binding_evidence"
    if role == "unclassified_or_padding":
        return "unclassified_numeric_candidate", "candidate_only"
    if role == "cross_region":
        return "cross_region_numeric_candidate", "candidate_only"
    if role == "outside_member":
        return "invalid_outside_member", "invalid"
    return "structural_region_numeric_candidate", "candidate_only"


def overlap_length(ranges: Sequence[tuple[int, int]], start: int, end: int) -> int:
    total = 0
    for left, right in ranges:
        if right <= start:
            continue
        if left >= end:
            break
        total += max(0, min(end, right) - max(start, left))
    return total


def texture_key(texture: Mapping[str, Any]) -> tuple[str, int]:
    return str(texture["name_sha256"]), int(texture["index"])


def audit(
    project_root: Path,
    br1_root: Path,
    quartet_root: Path,
    output_root: Path,
    *,
    create_report_archive: bool = True,
) -> tuple[Path | None, dict[str, Any]]:
    with prerequisite_report(project_root) as stage40_root:
        stage40_summary = json.loads((stage40_root / "SUMMARY.json").read_text(encoding="utf-8"))
        if int(stage40_summary.get("sequence_candidates", -1)) != 0:
            raise BknUiStructureError("stage 43 is reserved for the no-index-sequence path")
        member_rows = read_tsv(stage40_root / "DLC_BKN_UI_INDEX_MEMBER_AUDIT.tsv")
        value_hits = read_tsv(stage40_root / "DLC_BKN_UI_INDEX_VALUE_HITS.tsv")

    clean_dir(output_root)
    print("[stage43] reopening ten stage-40 hash-gated KSCL/KSLT members", flush=True)
    payload_rows: list[dict[str, Any]] = []
    for row in member_rows:
        if row.get("validation_status") != "passed" or row.get("raw_payload_exported") != "false":
            raise BknUiStructureError("stage-40 member audit row is not clean")
        payload_rows.append({
            "side": row["side"],
            "archive": row["archive"],
            "inventory_path": row["inventory_path"],
            "normalized_path": row["normalized_path"],
            "expected_size": int(row["actual_size"]),
            "expected_sha256": row["actual_sha256"],
        })
    payloads, rehydration_rows = STAGE40.read_ui_payloads(payload_rows, br1_root, quartet_root)

    parsed_map: dict[tuple[str, str], ParsedUi] = {}
    structure_rows: list[dict[str, Any]] = []
    region_rows: list[dict[str, Any]] = []
    for (side, normalized), payload in sorted(payloads.items()):
        parsed = parse_ui_member(payload)
        parsed_map[(side, normalized)] = parsed
        structure_rows.append({
            "side": side,
            "member_path": normalized,
            "member_size": len(payload),
            "member_sha256": sha256_bytes(payload),
            "file_kind": parsed.file_kind,
            "kscl_length": parsed.kscl_length,
            "kslt_base": parsed.kslt_base,
            "texture_count": parsed.texture_count,
            "headerless_size": parsed.headerless_size,
            "table_pointer": parsed.table_pointer,
            "name_length": parsed.name_length,
            "name_count": parsed.name_count,
            "table_base": parsed.table_base,
            "names_base": parsed.names_base,
            "names_end": parsed.names_end,
            "structural_region_count": len(parsed.regions),
            "parse_status": "passed",
            "raw_payload_exported": False,
        })
        for region_index, region in enumerate(parsed.regions):
            region_rows.append({
                "side": side,
                "member_path": normalized,
                "region_index": region_index,
                "region_role": region.role,
                "start_offset": region.start,
                "end_offset": region.end,
                "size": region.size,
                "texture_index": region.texture_index,
                "texture_name": region.texture_name,
                "texture_name_sha256": region.texture_name_sha256,
                "raw_payload_exported": False,
            })
        print(f"[stage43] parsed {side}: {normalized} kind={parsed.file_kind} textures={parsed.texture_count}", flush=True)

    hit_rows: list[dict[str, Any]] = []
    for row in value_hits:
        side = row["side"]
        normalized = row["member_path"]
        parsed = parsed_map.get((side, normalized))
        if parsed is None:
            raise BknUiStructureError(f"stage-40 hit references an unknown member: {side} {normalized}")
        width = int(row["width_bits"]) // 8
        offset = int(row["offset"])
        role, region = region_for(parsed, offset, width)
        classification, evidence_strength = classification_for_region(role)
        hit_rows.append({
            **row,
            "region_role": role,
            "region_start": region.start if region else "",
            "region_end": region.end if region else "",
            "texture_index": region.texture_index if region else "",
            "texture_name": region.texture_name if region else "",
            "texture_name_sha256": region.texture_name_sha256 if region else "",
            "structural_classification": classification,
            "owner_binding_evidence_strength": evidence_strength,
            "raw_payload_exported": False,
        })

    paired: dict[str, dict[str, bytes]] = defaultdict(dict)
    for (side, normalized), payload in payloads.items():
        paired[normalized][side] = payload
    delta_region_rows: list[dict[str, Any]] = []
    texture_rows: list[dict[str, Any]] = []
    for normalized, sides in sorted(paired.items()):
        if set(sides) != {"source", "target"}:
            raise BknUiStructureError(f"incomplete UI pair: {normalized}")
        _changed, ranges = STAGE40.diff_ranges(sides["source"], sides["target"])
        ranges = sorted(ranges)
        for side in ("source", "target"):
            parsed = parsed_map[(side, normalized)]
            classified = 0
            for region in parsed.regions:
                changed_bytes = overlap_length(ranges, region.start, region.end)
                classified += changed_bytes
                delta_region_rows.append({
                    "side": side,
                    "member_path": normalized,
                    "region_role": region.role,
                    "region_start": region.start,
                    "region_end": region.end,
                    "region_size": region.size,
                    "texture_index": region.texture_index,
                    "texture_name": region.texture_name,
                    "texture_name_sha256": region.texture_name_sha256,
                    "same_offset_changed_bytes_in_region": changed_bytes,
                    "region_changed_ratio": changed_bytes / region.size if region.size else 0.0,
                    "raw_payload_exported": False,
                })
            if side == "source" and len(sides["target"]) > len(sides["source"]):
                delta_region_rows.append({
                    "side": side,
                    "member_path": normalized,
                    "region_role": "target_only_tail_absent_from_source",
                    "region_start": len(sides["source"]),
                    "region_end": len(sides["target"]),
                    "region_size": len(sides["target"]) - len(sides["source"]),
                    "texture_index": "",
                    "texture_name": "",
                    "texture_name_sha256": "",
                    "same_offset_changed_bytes_in_region": len(sides["target"]) - len(sides["source"]),
                    "region_changed_ratio": 1.0,
                    "raw_payload_exported": False,
                })
            if side == "target" and len(sides["source"]) > len(sides["target"]):
                delta_region_rows.append({
                    "side": side,
                    "member_path": normalized,
                    "region_role": "source_only_tail_absent_from_target",
                    "region_start": len(sides["target"]),
                    "region_end": len(sides["source"]),
                    "region_size": len(sides["source"]) - len(sides["target"]),
                    "texture_index": "",
                    "texture_name": "",
                    "texture_name_sha256": "",
                    "same_offset_changed_bytes_in_region": len(sides["source"]) - len(sides["target"]),
                    "region_changed_ratio": 1.0,
                    "raw_payload_exported": False,
                })

        source_textures = {texture_key(row): row for row in parsed_map[("source", normalized)].textures}
        target_textures = {texture_key(row): row for row in parsed_map[("target", normalized)].textures}
        for key in sorted(set(source_textures) | set(target_textures)):
            source = source_textures.get(key)
            target = target_textures.get(key)
            if source and target:
                status = "present_identical" if (
                    source["format_type"] == target["format_type"]
                    and source["width"] == target["width"]
                    and source["height"] == target["height"]
                    and source["raw_size"] == target["raw_size"]
                    and source["raw_sha256"] == target["raw_sha256"]
                ) else "present_modified"
            elif source:
                status = "source_only_texture"
            else:
                status = "target_only_texture"
            exemplar = source or target
            assert exemplar is not None
            texture_rows.append({
                "member_path": normalized,
                "texture_name": exemplar["name"],
                "texture_name_sha256": exemplar["name_sha256"],
                "source_index": source["index"] if source else "",
                "target_index": target["index"] if target else "",
                "source_format_type": source["format_type"] if source else "",
                "target_format_type": target["format_type"] if target else "",
                "source_width": source["width"] if source else "",
                "target_width": target["width"] if target else "",
                "source_height": source["height"] if source else "",
                "target_height": target["height"] if target else "",
                "source_raw_size": source["raw_size"] if source else "",
                "target_raw_size": target["raw_size"] if target else "",
                "source_raw_sha256": source["raw_sha256"] if source else "",
                "target_raw_sha256": target["raw_sha256"] if target else "",
                "compatibility_status": status,
                "raw_payload_exported": False,
            })

    target_bkn = [row for row in hit_rows if row["side"] == "target" and row["family"] == "bkn"]
    target_bkn_payload = [row for row in target_bkn if row["region_role"] == "texture_payload"]
    target_bkn_structural = [row for row in target_bkn if row["owner_binding_evidence_strength"] == "candidate_only"]
    region_counts = Counter(row["region_role"] for row in target_bkn)
    if target_bkn_structural:
        status = "bkn_ui_structural_numeric_candidates_found_semantics_unproven"
        owner_status = "candidate_only"
    elif target_bkn and len(target_bkn_payload) == len(target_bkn):
        status = "bkn_ui_numeric_hits_confined_to_texture_payloads"
        owner_status = "unresolved_numeric_route_closed_for_selected_members"
    elif target_bkn:
        status = "bkn_ui_numeric_hits_structurally_classified_no_owner_binding"
        owner_status = "unresolved"
    else:
        status = "bkn_ui_numeric_hits_absent"
        owner_status = "unresolved"

    gaps = [
        {
            "dependency": "owner_ui_slot",
            "status": owner_status,
            "blocks_installation": True,
            "next_evidence": "only non-texture structural hits may justify a narrower format probe; texture-payload collisions are not UI routing evidence",
        },
        {
            "dependency": "exact_unlock_or_entitlement",
            "status": "unresolved",
            "blocks_installation": True,
            "next_evidence": "identify a proven availability condition without inventing an entitlement",
        },
        {
            "dependency": "wet_variant",
            "status": "conversion_blocked",
            "blocks_installation": True,
            "next_evidence": "complete G1M/SWG conversion and exact G1M-to-G1T binding",
        },
        {
            "dependency": "runtime_validation",
            "status": "not_performed",
            "blocks_installation": True,
            "next_evidence": "runtime validation remains forbidden until a complete transactional profile exists",
        },
    ]

    write_tsv(output_root / "DLC_BKN_UI_STRUCTURE_MEMBER_AUDIT.tsv", [
        "side", "member_path", "member_size", "member_sha256", "file_kind", "kscl_length", "kslt_base",
        "texture_count", "headerless_size", "table_pointer", "name_length", "name_count", "table_base",
        "names_base", "names_end", "structural_region_count", "parse_status", "raw_payload_exported",
    ], structure_rows)
    write_tsv(output_root / "DLC_BKN_UI_STRUCTURE_REGIONS.tsv", [
        "side", "member_path", "region_index", "region_role", "start_offset", "end_offset", "size",
        "texture_index", "texture_name", "texture_name_sha256", "raw_payload_exported",
    ], region_rows)
    write_tsv(output_root / "DLC_BKN_UI_INDEX_REGION_CLASSIFICATION.tsv", [
        "side", "member_path", "member_sha256", "index_space", "family", "variant", "ordinal", "numeric_value",
        "width_bits", "endianness", "offset", "offset_aligned", "overlaps_source_target_delta", "region_role",
        "region_start", "region_end", "texture_index", "texture_name", "texture_name_sha256",
        "structural_classification", "owner_binding_evidence_strength", "raw_payload_exported",
    ], sorted(hit_rows, key=lambda row: (row["side"], row["member_path"], int(row["offset"]), int(row["width_bits"]), row["family"])))
    write_tsv(output_root / "DLC_BKN_UI_DELTA_REGION_CLASSIFICATION.tsv", [
        "side", "member_path", "region_role", "region_start", "region_end", "region_size", "texture_index",
        "texture_name", "texture_name_sha256", "same_offset_changed_bytes_in_region", "region_changed_ratio",
        "raw_payload_exported",
    ], delta_region_rows)
    write_tsv(output_root / "DLC_BKN_UI_TEXTURE_TABLE_COMPARISON.tsv", [
        "member_path", "texture_name", "texture_name_sha256", "source_index", "target_index", "source_format_type",
        "target_format_type", "source_width", "target_width", "source_height", "target_height", "source_raw_size",
        "target_raw_size", "source_raw_sha256", "target_raw_sha256", "compatibility_status", "raw_payload_exported",
    ], texture_rows)
    write_tsv(output_root / "DLC_BKN_UI_STRUCTURE_GAPS.tsv", [
        "dependency", "status", "blocks_installation", "next_evidence",
    ], gaps)

    summary = {
        "type": "br_quartet_legacy_dlc_bkn_ui_structure_summary",
        "format_version": FORMAT_VERSION,
        "tool_version": TOOL_VERSION,
        "content_id": "costume_pc00_bkn",
        "status": status,
        "ui_members_scanned": len(structure_rows),
        "ui_member_pairs": len(paired),
        "kscl_members": sum(1 for row in structure_rows if row["file_kind"] == "kscl_with_embedded_kslt"),
        "standalone_kslt_members": sum(1 for row in structure_rows if row["file_kind"] == "standalone_kslt"),
        "textures_inventoried": sum(int(row["texture_count"]) for row in structure_rows),
        "prior_index_hits_classified": len(hit_rows),
        "target_bkn_hits": len(target_bkn),
        "target_bkn_texture_payload_hits": len(target_bkn_payload),
        "target_bkn_structural_candidate_hits": len(target_bkn_structural),
        "target_bkn_region_counts": dict(sorted(region_counts.items())),
        "texture_comparison_rows": len(texture_rows),
        "modified_texture_rows": sum(1 for row in texture_rows if row["compatibility_status"] == "present_modified"),
        "unresolved_installation_blockers": len(gaps),
        "findings": [
            "stage 40 found isolated BKN numeric values but no ordered or strided BKN sequence in the selected UI members",
            "KSCL control data, embedded KSLT headers/tables/names, texture headers and texture payloads are classified independently",
            "integer hits inside texture payloads are treated as binary collisions rather than UI routing evidence",
            "source-target changes are aggregated by structural region and embedded textures are compared by metadata and hashes only",
            "no KSCL/KSLT payload bytes, textures, UI files, tables, PAKs, modules, profiles, Translation records, Git state or installed game files are modified or exported",
        ],
        "next_action": "retain only non-texture structural candidates for a narrower schema probe; if BKN hits are confined to texture payloads, close the selected numeric-index route and continue availability discovery from proven table/runtime behavior",
        "policy": {
            "game_modified": False,
            "git_modified": False,
            "candidate_installed": False,
            "profile_registered": False,
            "profile_build_allowed": False,
            "profiles_activated": False,
            "runtime_validated": False,
            "system_table_modified": False,
            "ui_modified": False,
            "translation_modified": False,
            "raw_assets_exported_in_report": False,
            "raw_assets_in_update": False,
            "raw_ui_payload_exported": False,
            "texture_payload_numeric_hit_is_ui_binding_proof": False,
            "structural_numeric_hit_is_ui_binding_proof": False,
            "texture_name_or_index_is_ui_owner_proof": False,
            "text_seed_unchanged": True,
        },
    }
    write_json(output_root / "SUMMARY.json", summary)
    write_json(output_root / "REPORT_MANIFEST.json", {"type": "br_report_manifest", "format_version": 1, "files": report_manifest(output_root)})
    archive: Path | None = None
    if create_report_archive:
        archive = output_root.parent / REPORT_ARCHIVE_NAME
        make_archive(output_root, archive)
        print(f"[stage43] report: {archive}", flush=True)
    return archive, summary


def validate_report(report_root: Path) -> dict[str, Any]:
    required = (
        "DLC_BKN_UI_STRUCTURE_MEMBER_AUDIT.tsv",
        "DLC_BKN_UI_STRUCTURE_REGIONS.tsv",
        "DLC_BKN_UI_INDEX_REGION_CLASSIFICATION.tsv",
        "DLC_BKN_UI_DELTA_REGION_CLASSIFICATION.tsv",
        "DLC_BKN_UI_TEXTURE_TABLE_COMPARISON.tsv",
        "DLC_BKN_UI_STRUCTURE_GAPS.tsv",
        "SUMMARY.json",
        "REPORT_MANIFEST.json",
    )
    for name in required:
        if not (report_root / name).is_file():
            raise BknUiStructureError(f"missing report file: {name}")
    summary = json.loads((report_root / "SUMMARY.json").read_text(encoding="utf-8"))
    if summary.get("type") != "br_quartet_legacy_dlc_bkn_ui_structure_summary" or summary.get("tool_version") != TOOL_VERSION:
        raise BknUiStructureError("invalid BKN UI structure summary")
    if summary.get("ui_members_scanned") != 10 or summary.get("ui_member_pairs") != 5:
        raise BknUiStructureError("incomplete BKN UI structure audit")
    if summary.get("kscl_members") != 8 or summary.get("standalone_kslt_members") != 2:
        raise BknUiStructureError("unexpected KSCL/KSLT member split")
    if summary.get("prior_index_hits_classified", -1) < summary.get("target_bkn_hits", 0):
        raise BknUiStructureError("index hit classification counts are inconsistent")
    if summary.get("unresolved_installation_blockers") != 4:
        raise BknUiStructureError("expected four fail-closed blockers")
    policy = summary.get("policy", {})
    for key in (
        "game_modified", "git_modified", "candidate_installed", "profile_registered", "profile_build_allowed",
        "profiles_activated", "runtime_validated", "system_table_modified", "ui_modified", "translation_modified",
        "raw_assets_exported_in_report", "raw_assets_in_update", "raw_ui_payload_exported",
        "texture_payload_numeric_hit_is_ui_binding_proof", "structural_numeric_hit_is_ui_binding_proof",
        "texture_name_or_index_is_ui_owner_proof",
    ):
        if policy.get(key) is not False:
            raise BknUiStructureError(f"fail-closed policy violation: {key}")
    if policy.get("text_seed_unchanged") is not True:
        raise BknUiStructureError("text seed must remain unchanged")
    member_rows = read_tsv(report_root / "DLC_BKN_UI_STRUCTURE_MEMBER_AUDIT.tsv")
    if len(member_rows) != 10 or not all(row.get("parse_status") == "passed" and row.get("raw_payload_exported") == "false" for row in member_rows):
        raise BknUiStructureError("invalid structure member rows")
    gaps = read_tsv(report_root / "DLC_BKN_UI_STRUCTURE_GAPS.tsv")
    if len(gaps) != 4 or not all(row.get("blocks_installation") == "true" for row in gaps):
        raise BknUiStructureError("installation blockers were weakened")
    for path in report_root.rglob("*"):
        if path.is_file() and ({suffix.casefold() for suffix in path.suffixes} & FORBIDDEN_REPORT_SUFFIXES):
            raise BknUiStructureError(f"raw asset in report: {path}")
    manifest = json.loads((report_root / "REPORT_MANIFEST.json").read_text(encoding="utf-8"))
    for row in manifest.get("files", []):
        path = report_root / row["path"]
        if not path.is_file() or path.stat().st_size != row["size"] or sha256_file(path) != row["sha256"]:
            raise BknUiStructureError(f"report manifest mismatch: {row['path']}")
    return summary


def main() -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    audit_parser = sub.add_parser("audit")
    audit_parser.add_argument("--project-root", required=True)
    audit_parser.add_argument("--source-game", required=True)
    audit_parser.add_argument("--target-game", required=True)
    audit_parser.add_argument("--output-root")
    audit_parser.add_argument("--no-report-archive", action="store_true")
    validate_parser = sub.add_parser("validate-report")
    validate_parser.add_argument("--report-root", required=True)
    args = parser.parse_args()
    try:
        if args.command == "audit":
            project_root = Path(args.project_root).resolve()
            output = Path(args.output_root).resolve() if args.output_root else project_root / ".local/reports/quartet_legacy_dlc" / REPORT_DIR_NAME
            audit(project_root, Path(args.source_game).resolve(), Path(args.target_game).resolve(), output, create_report_archive=not args.no_report_archive)
        else:
            validate_report(Path(args.report_root).resolve())
    except (BknUiStructureError, STAGE40.BknUiIndexError, OSError, subprocess.SubprocessError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
