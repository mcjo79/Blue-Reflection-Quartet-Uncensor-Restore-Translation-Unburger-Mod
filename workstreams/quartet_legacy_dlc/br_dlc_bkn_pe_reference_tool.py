#!/usr/bin/env python3
"""Read-only PE section and static-reference classification for BKN runtime tokens.

The tool consumes the validated stage-34 metadata report, reopens only modules
that contained exact technical tokens, verifies their hashes, parses PE headers,
and classifies bounded static references. It never modifies or exports modules,
never disassembles complete functions, and never treats a token/xref as proof of
DLC entitlement, UI ownership, activation, or runtime compatibility.
"""
from __future__ import annotations
import os

import argparse
import bisect
import csv
import hashlib
import importlib.util
import json
import re
import shutil
import struct
import subprocess
import tempfile
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

TOOL_VERSION = "0.0.16"
FORMAT_VERSION = 1
REPORT_DIR_NAME = "bkn_pe_reference_evidence"
REPORT_ARCHIVE_NAME = "BR_quartet_legacy_dlc_bkn_pe_reference_evidence.tar.zst"
PROJECT_ROOT_DEFAULT = Path((os.environ.get("BR_PROJECT_ROOT") or os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))))
FORBIDDEN_REPORT_SUFFIXES = {
    ".exe", ".dll", ".pak", ".ebd", ".ebm", ".g1m", ".g1t", ".g1s", ".g1e",
    ".swg", ".bin", ".gz", ".kscl", ".kslt",
}

SCRIPT_DIR = Path(__file__).resolve().parent
_STAGE34_PATH = SCRIPT_DIR / "br_dlc_bkn_index_runtime_tool.py"
_spec = importlib.util.spec_from_file_location("br_dlc_bkn_index_runtime_for_stage37", _STAGE34_PATH)
if _spec is None or _spec.loader is None:
    raise RuntimeError(f"unable to load stage-34 tool: {_STAGE34_PATH}")
STAGE34 = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(STAGE34)


class BknPeReferenceError(RuntimeError):
    pass


@dataclass(frozen=True)
class Section:
    name: str
    virtual_size: int
    virtual_address: int
    raw_size: int
    raw_offset: int
    characteristics: int

    @property
    def executable(self) -> bool:
        return bool(self.characteristics & 0x20000000)

    @property
    def readable(self) -> bool:
        return bool(self.characteristics & 0x40000000)

    @property
    def writable(self) -> bool:
        return bool(self.characteristics & 0x80000000)

    @property
    def contains_code(self) -> bool:
        return bool(self.characteristics & 0x00000020)

    @property
    def contains_initialized_data(self) -> bool:
        return bool(self.characteristics & 0x00000040)


@dataclass(frozen=True)
class PeImage:
    machine: int
    pe_kind: str
    image_base: int
    size_of_headers: int
    size_of_image: int
    sections: tuple[Section, ...]
    data_directories: tuple[tuple[int, int], ...]

    def offset_to_rva(self, offset: int) -> tuple[int | None, Section | None]:
        if 0 <= offset < self.size_of_headers:
            return offset, None
        for section in self.sections:
            if section.raw_offset <= offset < section.raw_offset + section.raw_size:
                return section.virtual_address + (offset - section.raw_offset), section
        return None, None

    def rva_to_offset(self, rva: int) -> tuple[int | None, Section | None]:
        if 0 <= rva < self.size_of_headers:
            return rva, None
        for section in self.sections:
            span = max(section.virtual_size, section.raw_size)
            if section.virtual_address <= rva < section.virtual_address + span:
                delta = rva - section.virtual_address
                if delta >= section.raw_size:
                    return None, section
                return section.raw_offset + delta, section
        return None, None


@dataclass(frozen=True)
class TokenTarget:
    side: str
    module_path: str
    module_sha256: str
    offset: int
    rva: int
    va: int
    section_name: str
    encoding: str
    primary_token: str
    aliases: tuple[str, ...]
    family: str
    byte_length: int


def require(condition: bool, message: str) -> None:
    if not condition:
        raise BknPeReferenceError(message)


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def json_cell(value: Any) -> str:
    if isinstance(value, (list, tuple, dict)):
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    if isinstance(value, bool):
        return "true" if value else "false"
    if value is None:
        return ""
    return str(value)


def write_tsv(path: Path, fields: Sequence[str], rows: Iterable[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(fields), delimiter="\t", lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow({field: json_cell(row.get(field, "")) for field in fields})


def read_tsv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def clean_dir(path: Path) -> None:
    if path.exists():
        shutil.rmtree(path)
    path.mkdir(parents=True, exist_ok=True)


def u16(data: bytes, offset: int) -> int:
    require(offset + 2 <= len(data), f"truncated u16 at {offset}")
    return struct.unpack_from("<H", data, offset)[0]


def u32(data: bytes, offset: int) -> int:
    require(offset + 4 <= len(data), f"truncated u32 at {offset}")
    return struct.unpack_from("<I", data, offset)[0]


def u64(data: bytes, offset: int) -> int:
    require(offset + 8 <= len(data), f"truncated u64 at {offset}")
    return struct.unpack_from("<Q", data, offset)[0]


def parse_pe(data: bytes) -> PeImage:
    require(len(data) >= 0x100 and data[:2] == b"MZ", "module is not a DOS/PE image")
    pe_offset = u32(data, 0x3C)
    require(pe_offset + 24 <= len(data), "truncated PE header")
    require(data[pe_offset:pe_offset + 4] == b"PE\0\0", "missing PE signature")
    coff = pe_offset + 4
    machine = u16(data, coff)
    section_count = u16(data, coff + 2)
    optional_size = u16(data, coff + 16)
    require(0 < section_count <= 96, f"unsupported PE section count: {section_count}")
    optional = coff + 20
    require(optional + optional_size <= len(data), "truncated PE optional header")
    magic = u16(data, optional)
    if magic == 0x20B:
        pe_kind = "pe32_plus"
        image_base = u64(data, optional + 24)
        directory_count_offset = optional + 108
        directory_offset = optional + 112
    elif magic == 0x10B:
        pe_kind = "pe32"
        image_base = u32(data, optional + 28)
        directory_count_offset = optional + 92
        directory_offset = optional + 96
    else:
        raise BknPeReferenceError(f"unsupported PE optional-header magic: 0x{magic:04x}")
    size_of_image = u32(data, optional + 56)
    size_of_headers = u32(data, optional + 60)
    directory_count = min(u32(data, directory_count_offset), 16)
    directories: list[tuple[int, int]] = []
    for index in range(directory_count):
        entry = directory_offset + index * 8
        if entry + 8 > optional + optional_size:
            break
        directories.append((u32(data, entry), u32(data, entry + 4)))
    while len(directories) < 16:
        directories.append((0, 0))

    section_table = optional + optional_size
    require(section_table + section_count * 40 <= len(data), "truncated PE section table")
    sections: list[Section] = []
    for index in range(section_count):
        base = section_table + index * 40
        raw_name = data[base:base + 8].split(b"\0", 1)[0]
        name = raw_name.decode("ascii", "replace") or f"section_{index}"
        section = Section(
            name=name,
            virtual_size=u32(data, base + 8),
            virtual_address=u32(data, base + 12),
            raw_size=u32(data, base + 16),
            raw_offset=u32(data, base + 20),
            characteristics=u32(data, base + 36),
        )
        require(section.raw_offset + section.raw_size <= len(data), f"section exceeds module: {name}")
        sections.append(section)
    return PeImage(
        machine=machine,
        pe_kind=pe_kind,
        image_base=image_base,
        size_of_headers=size_of_headers,
        size_of_image=size_of_image,
        sections=tuple(sections),
        data_directories=tuple(directories),
    )


def parse_runtime_functions(data: bytes, pe: PeImage) -> list[tuple[int, int, int]]:
    if pe.pe_kind != "pe32_plus":
        return []
    exception_rva, exception_size = pe.data_directories[3]
    if exception_rva == 0 or exception_size < 12:
        return []
    offset, _ = pe.rva_to_offset(exception_rva)
    if offset is None:
        return []
    limit = min(len(data), offset + exception_size)
    rows: list[tuple[int, int, int]] = []
    cursor = offset
    while cursor + 12 <= limit:
        begin, end, unwind = struct.unpack_from("<III", data, cursor)
        cursor += 12
        if begin == 0 and end == 0:
            continue
        if begin < end <= pe.size_of_image:
            rows.append((begin, end, unwind))
    rows.sort()
    return rows


def find_runtime_function(functions: Sequence[tuple[int, int, int]], rva: int) -> tuple[int, int, int] | None:
    if not functions:
        return None
    begins = [item[0] for item in functions]
    index = bisect.bisect_right(begins, rva) - 1
    if index >= 0:
        item = functions[index]
        if item[0] <= rva < item[1]:
            return item
    return None


def token_family(token: str) -> str:
    upper = token.upper()
    if "_DLC_BKN" in upper:
        return "bkn"
    if "_DLC_TWL" in upper:
        return "twl"
    if "_SCL" in upper:
        return "scl"
    if token.casefold() == "costume_change":
        return "costume_change"
    if token.casefold() == "str_costume":
        return "str_costume"
    return "other_exact_runtime"


def encoded_length(token: str, encoding: str) -> int:
    if encoding == "utf16le":
        return len(token.encode("utf-16le"))
    return len(token.encode("ascii", "ignore"))


def deduplicate_token_hits(rows: Sequence[Mapping[str, str]], modules: Mapping[tuple[str, str], Mapping[str, str]], pe_by_module: Mapping[tuple[str, str], PeImage]) -> list[TokenTarget]:
    grouped: dict[tuple[str, str, int, str], list[Mapping[str, str]]] = defaultdict(list)
    for row in rows:
        if row.get("token_class") != "exact_runtime":
            continue
        key = (row["side"], row["module_path"], int(row["offset"]), row["encoding"])
        grouped[key].append(row)
    targets: list[TokenTarget] = []
    for (side, module_path, offset, encoding), matches in sorted(grouped.items()):
        module_key = (side, module_path)
        require(module_key in modules, f"token references unknown module: {module_key}")
        pe = pe_by_module[module_key]
        rva, section = pe.offset_to_rva(offset)
        require(rva is not None, f"token offset is outside PE sections: {module_path}@{offset}")
        aliases = tuple(sorted({row["token"] for row in matches}, key=lambda value: (len(value), value)))
        primary = max(aliases, key=lambda value: (len(value), value))
        targets.append(TokenTarget(
            side=side,
            module_path=module_path,
            module_sha256=modules[module_key]["sha256"],
            offset=offset,
            rva=rva,
            va=pe.image_base + rva,
            section_name=section.name if section else "<headers>",
            encoding=encoding,
            primary_token=primary,
            aliases=aliases,
            family=token_family(primary),
            byte_length=encoded_length(primary, encoding),
        ))
    return targets


def target_for_rva(targets: Sequence[TokenTarget], rva: int) -> TokenTarget | None:
    exact = [target for target in targets if target.rva == rva]
    if exact:
        return max(exact, key=lambda target: target.byte_length)
    for target in targets:
        if target.rva <= rva < target.rva + target.byte_length:
            return target
    return None


def all_offsets(data: bytes, needle: bytes, limit: int = 4096) -> list[int]:
    if not needle:
        return []
    result: list[int] = []
    cursor = 0
    while len(result) < limit:
        found = data.find(needle, cursor)
        if found < 0:
            break
        result.append(found)
        cursor = found + 1
    return result


def scan_rip_relative(data: bytes, pe: PeImage, targets: Sequence[TokenTarget], functions: Sequence[tuple[int, int, int]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    opcode_names = {0x8D: "lea", 0x8B: "mov_load", 0x89: "mov_store", 0x3B: "cmp_load", 0x39: "cmp_store"}
    # Run the candidate-instruction discovery in the regex engine rather than
    # iterating over every byte in Python. The ModRM class is exactly mod=00,
    # r/m=101 (RIP-relative), with any register field.
    pattern = re.compile(
        rb"(?:(?P<rex>[\x40-\x4f]))?(?P<opcode>[\x8d\x8b\x89\x3b\x39])"
        rb"(?P<modrm>[\x05\x0d\x15\x1d\x25\x2d\x35\x3d])(?P<disp>.{4})",
        re.DOTALL,
    )
    for section in pe.sections:
        if not section.executable or section.raw_size < 6:
            continue
        body = data[section.raw_offset:section.raw_offset + section.raw_size]
        for match in pattern.finditer(body):
            start = match.start()
            rex = match.group("rex") is not None
            opcode = match.group("opcode")[0]
            displacement = struct.unpack("<i", match.group("disp"))[0]
            length = match.end() - match.start()
            instruction_rva = section.virtual_address + start
            referenced_rva = instruction_rva + length + displacement
            target = target_for_rva(targets, referenced_rva)
            if target is None:
                continue
            function = find_runtime_function(functions, instruction_rva)
            instruction = match.group(0)
            rows.append({
                "reference_kind": f"rip_relative_{opcode_names[opcode]}",
                "reference_strength": "executable_code_xref_candidate",
                "reference_offset": section.raw_offset + start,
                "reference_rva": instruction_rva,
                "reference_section": section.name,
                "reference_section_executable": True,
                "target_offset": target.offset,
                "target_rva": target.rva,
                "target_primary_token": target.primary_token,
                "target_aliases": list(target.aliases),
                "target_family": target.family,
                "target_interior_delta": referenced_rva - target.rva,
                "instruction_length": length,
                "instruction_sha256": sha256_bytes(instruction),
                "rex_prefix_present": rex,
                "function_begin_rva": function[0] if function else "",
                "function_end_rva": function[1] if function else "",
                "function_unwind_rva": function[2] if function else "",
                "function_boundary_source": "pe_exception_directory" if function else "unresolved",
                "binding_proven": False,
            })
    return rows


def scan_pointer_references(data: bytes, pe: PeImage, targets: Sequence[TokenTarget], functions: Sequence[tuple[int, int, int]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    seen: set[tuple[int, str, int]] = set()
    for target in targets:
        patterns: list[tuple[str, bytes]] = [("rva32_value", struct.pack("<I", target.rva))]
        if pe.pe_kind == "pe32_plus":
            patterns.append(("absolute_va64_pointer", struct.pack("<Q", target.va)))
        elif target.va <= 0xFFFFFFFF:
            patterns.append(("absolute_va32_pointer", struct.pack("<I", target.va)))
        for kind, pattern in patterns:
            for offset in all_offsets(data, pattern):
                if target.offset <= offset < target.offset + target.byte_length:
                    continue
                key = (offset, kind, target.rva)
                if key in seen:
                    continue
                seen.add(key)
                reference_rva, section = pe.offset_to_rva(offset)
                if reference_rva is None:
                    continue
                executable = bool(section and section.executable)
                function = find_runtime_function(functions, reference_rva) if executable else None
                rows.append({
                    "reference_kind": kind,
                    "reference_strength": "data_pointer_candidate" if "pointer" in kind else "rva_value_candidate",
                    "reference_offset": offset,
                    "reference_rva": reference_rva,
                    "reference_section": section.name if section else "<headers>",
                    "reference_section_executable": executable,
                    "target_offset": target.offset,
                    "target_rva": target.rva,
                    "target_primary_token": target.primary_token,
                    "target_aliases": list(target.aliases),
                    "target_family": target.family,
                    "target_interior_delta": 0,
                    "instruction_length": "",
                    "instruction_sha256": sha256_bytes(pattern),
                    "rex_prefix_present": "",
                    "function_begin_rva": function[0] if function else "",
                    "function_end_rva": function[1] if function else "",
                    "function_unwind_rva": function[2] if function else "",
                    "function_boundary_source": "pe_exception_directory" if function else "unresolved",
                    "binding_proven": False,
                })
    return rows


def technical_cluster_tokens(data: bytes, target: TokenTarget, known_tokens: Sequence[str]) -> tuple[list[str], str]:
    left = max(0, target.offset - 256)
    right = min(len(data), target.offset + target.byte_length + 256)
    region = data[left:right]
    found: set[str] = set()
    for token in known_tokens:
        if token.encode("ascii", "ignore") in region or token.encode("utf-16le") in region:
            found.add(token)
    return sorted(found), sha256_bytes(region)


def section_rows(side: str, module_path: str, pe: PeImage) -> list[dict[str, Any]]:
    return [{
        "side": side,
        "module_path": module_path,
        "section_index": index,
        "section_name": section.name,
        "virtual_address": section.virtual_address,
        "virtual_size": section.virtual_size,
        "raw_offset": section.raw_offset,
        "raw_size": section.raw_size,
        "characteristics": f"0x{section.characteristics:08x}",
        "executable": section.executable,
        "readable": section.readable,
        "writable": section.writable,
        "contains_code": section.contains_code,
        "contains_initialized_data": section.contains_initialized_data,
    } for index, section in enumerate(pe.sections)]


def create_manifest(report_dir: Path) -> None:
    files = []
    for path in sorted(report_dir.iterdir(), key=lambda item: item.name.casefold()):
        if not path.is_file() or path.name == "REPORT_MANIFEST.json":
            continue
        if path.suffix.casefold() in FORBIDDEN_REPORT_SUFFIXES:
            raise BknPeReferenceError(f"raw module/asset forbidden in report: {path.name}")
        files.append({"path": path.name, "size": path.stat().st_size, "sha256": sha256_file(path)})
    write_json(report_dir / "REPORT_MANIFEST.json", {"type": "br_report_manifest", "format_version": 1, "files": files})


def create_archive(report_dir: Path, archive_path: Path) -> None:
    archive_path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="bkn_pe_ref_bundle_") as temp_name:
        staging = Path(temp_name) / REPORT_DIR_NAME
        shutil.copytree(report_dir, staging)
        subprocess.run([
            "tar", "--zstd", "--sort=name", "--mtime=@0", "--owner=0", "--group=0", "--numeric-owner",
            "-cf", str(archive_path), "-C", str(staging.parent), staging.name,
        ], check=True)


def prerequisite_dir(project_root: Path) -> Path:
    path = project_root / ".local/reports/quartet_legacy_dlc" / STAGE34.REPORT_DIR_NAME
    if not path.is_dir():
        raise BknPeReferenceError(f"missing stage-34 report directory: {path}")
    summary = STAGE34.validate_report(path)
    if summary.get("status") != "bkn_static_runtime_binding_candidates_found_but_not_proven":
        raise BknPeReferenceError("stage-34 report does not contain static runtime candidates")
    return path


def module_path(side: str, relative: str, source_game: Path, target_game: Path) -> Path:
    root = source_game if side == "source" else target_game
    return root / Path(relative)


def audit(project_root: Path, source_game: Path, target_game: Path, output_dir: Path, *, create_report_archive: bool = True) -> tuple[Path | None, dict[str, Any]]:
    previous = prerequisite_dir(project_root)
    clean_dir(output_dir)
    module_audit = read_tsv(previous / "DLC_BKN_RUNTIME_MODULE_AUDIT.tsv")
    token_hits = read_tsv(previous / "DLC_BKN_RUNTIME_TOKEN_HITS.tsv")
    selected = {
        (row["side"], row["relative_path"]): row
        for row in module_audit
        if row["scan_status"] == "passed" and int(row["exact_runtime_token_hits"] or 0) > 0
    }
    require(selected, "stage-34 report contains no exact-token modules")
    known_tokens = sorted({row["token"] for row in token_hits if row["token_class"] == "exact_runtime"})

    module_rows: list[dict[str, Any]] = []
    all_sections: list[dict[str, Any]] = []
    all_tokens: list[dict[str, Any]] = []
    all_xrefs: list[dict[str, Any]] = []
    function_rows: list[dict[str, Any]] = []
    pe_by_module: dict[tuple[str, str], PeImage] = {}
    data_by_module: dict[tuple[str, str], bytes] = {}

    print(f"[stage37] validating {len(selected)} exact-token PE modules", flush=True)
    for index, ((side, relative), metadata) in enumerate(sorted(selected.items()), 1):
        path = module_path(side, relative, source_game, target_game)
        print(f"[stage37] module {index}/{len(selected)}: {side}:{relative}", flush=True)
        require(path.is_file(), f"runtime module disappeared: {path}")
        require(path.stat().st_size == int(metadata["size"]), f"runtime module size changed: {path}")
        require(sha256_file(path) == metadata["sha256"], f"runtime module hash changed: {path}")
        data = path.read_bytes()
        try:
            pe = parse_pe(data)
        except BknPeReferenceError as exc:
            raise BknPeReferenceError(f"exact-token module is not a supported PE image: {path}: {exc}") from exc
        key = (side, relative)
        pe_by_module[key] = pe
        data_by_module[key] = data
        all_sections.extend(section_rows(side, relative, pe))

    targets = deduplicate_token_hits(token_hits, selected, pe_by_module)
    by_module: dict[tuple[str, str], list[TokenTarget]] = defaultdict(list)
    for target in targets:
        by_module[(target.side, target.module_path)].append(target)

    for analysis_index, key in enumerate(sorted(selected), 1):
        side, relative = key
        print(f"[stage37] classifying references {analysis_index}/{len(selected)}: {side}:{relative}", flush=True)
        data = data_by_module[key]
        pe = pe_by_module[key]
        module_targets = sorted(by_module[key], key=lambda item: (item.offset, item.primary_token))
        functions = parse_runtime_functions(data, pe)
        rip_rows = scan_rip_relative(data, pe, module_targets, functions)
        pointer_rows = scan_pointer_references(data, pe, module_targets, functions)
        xrefs = rip_rows + pointer_rows
        for row in xrefs:
            row.update({"side": side, "module_path": relative, "module_sha256": selected[key]["sha256"]})
        all_xrefs.extend(xrefs)

        for target in module_targets:
            clusters, cluster_hash = technical_cluster_tokens(data, target, known_tokens)
            matching = [row for row in xrefs if int(row["target_offset"]) == target.offset]
            code_count = sum(row["reference_strength"] == "executable_code_xref_candidate" for row in matching)
            pointer_count = sum(row["reference_strength"] == "data_pointer_candidate" for row in matching)
            rva_count = sum(row["reference_strength"] == "rva_value_candidate" for row in matching)
            all_tokens.append({
                "side": side,
                "module_path": relative,
                "module_sha256": target.module_sha256,
                "token_offset": target.offset,
                "token_rva": target.rva,
                "token_va": target.va,
                "token_section": target.section_name,
                "encoding": target.encoding,
                "primary_token": target.primary_token,
                "aliases": list(target.aliases),
                "family": target.family,
                "byte_length": target.byte_length,
                "technical_cluster_tokens": clusters,
                "technical_cluster_sha256": cluster_hash,
                "code_xref_candidates": code_count,
                "data_pointer_candidates": pointer_count,
                "rva_value_candidates": rva_count,
                "binding_proven": False,
            })

        function_buckets: dict[tuple[int, int], list[dict[str, Any]]] = defaultdict(list)
        for row in xrefs:
            if row["function_begin_rva"] != "":
                function_buckets[(int(row["function_begin_rva"]), int(row["function_end_rva"]))].append(row)
        for (begin, end), rows in sorted(function_buckets.items()):
            offset, section = pe.rva_to_offset(begin)
            function_hash = ""
            if offset is not None and end > begin and offset + (end - begin) <= len(data):
                function_hash = sha256_bytes(data[offset:offset + (end - begin)])
            function_rows.append({
                "side": side,
                "module_path": relative,
                "function_begin_rva": begin,
                "function_end_rva": end,
                "function_size": end - begin,
                "function_section": section.name if section else "",
                "function_sha256": function_hash,
                "reference_count": len(rows),
                "reference_families": sorted({row["target_family"] for row in rows}),
                "target_tokens": sorted({row["target_primary_token"] for row in rows}),
                "contains_bkn_reference": any(row["target_family"] == "bkn" for row in rows),
                "contains_control_reference": any(row["target_family"] in {"twl", "scl", "costume_change"} for row in rows),
                "function_semantics_proven": False,
            })

        module_xrefs = [row for row in all_xrefs if row["side"] == side and row["module_path"] == relative]
        module_tokens = [row for row in all_tokens if row["side"] == side and row["module_path"] == relative]
        module_rows.append({
            "side": side,
            "module_path": relative,
            "size": int(selected[key]["size"]),
            "sha256": selected[key]["sha256"],
            "machine": f"0x{pe.machine:04x}",
            "pe_kind": pe.pe_kind,
            "image_base": pe.image_base,
            "size_of_image": pe.size_of_image,
            "section_count": len(pe.sections),
            "runtime_function_entries": len(functions),
            "deduplicated_exact_token_locations": len(module_targets),
            "code_xref_candidates": sum(row["reference_strength"] == "executable_code_xref_candidate" for row in module_xrefs),
            "data_pointer_candidates": sum(row["reference_strength"] == "data_pointer_candidate" for row in module_xrefs),
            "rva_value_candidates": sum(row["reference_strength"] == "rva_value_candidate" for row in module_xrefs),
            "bkn_token_locations": sum(row["family"] == "bkn" for row in module_tokens),
            "control_token_locations": sum(row["family"] in {"twl", "scl", "costume_change"} for row in module_tokens),
            "scan_status": "passed",
            "raw_module_exported": False,
        })

    comparison_rows: list[dict[str, Any]] = []
    grouped_tokens: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in all_tokens:
        grouped_tokens[(row["side"], row["module_path"], row["family"])].append(row)
    for key, rows in sorted(grouped_tokens.items()):
        side, relative, family = key
        comparison_rows.append({
            "side": side,
            "module_path": relative,
            "family": family,
            "token_locations": len(rows),
            "code_xref_candidates": sum(int(row["code_xref_candidates"]) for row in rows),
            "data_pointer_candidates": sum(int(row["data_pointer_candidates"]) for row in rows),
            "rva_value_candidates": sum(int(row["rva_value_candidates"]) for row in rows),
            "primary_tokens": sorted({row["primary_token"] for row in rows}),
            "classification": "static_reference_candidates_present" if any(
                int(row["code_xref_candidates"]) + int(row["data_pointer_candidates"]) + int(row["rva_value_candidates"]) > 0
                for row in rows
            ) else "token_storage_only_no_resolved_reference",
            "runtime_binding_proven": False,
        })

    code_xrefs = sum(row["reference_strength"] == "executable_code_xref_candidate" for row in all_xrefs)
    bkn_code_xrefs = sum(row["reference_strength"] == "executable_code_xref_candidate" and row["target_family"] == "bkn" for row in all_xrefs)
    bkn_any_xrefs = sum(row["target_family"] == "bkn" for row in all_xrefs)
    status = "bkn_pe_code_reference_candidates_found_semantics_unproven" if bkn_code_xrefs else (
        "bkn_pe_data_reference_candidates_found_semantics_unproven" if bkn_any_xrefs else "bkn_tokens_present_without_resolved_pe_references"
    )
    next_action = (
        "perform bounded function-level control comparison for BKN/TWL/SCL xref candidates without modifying modules"
        if bkn_code_xrefs else
        "retain static token evidence only and continue table/UI/runtime discovery without patching modules"
    )
    gaps = [
        {"dependency": "runtime_reference_semantics", "status": "candidate_found" if bkn_any_xrefs else "unresolved", "blocks_installation": True, "next_evidence": next_action},
        {"dependency": "runtime_entitlement_or_availability_condition", "status": "unresolved", "blocks_installation": True, "next_evidence": "identify a proven availability condition; static xrefs are insufficient"},
        {"dependency": "owner_ui_slot", "status": "unresolved", "blocks_installation": True, "next_evidence": "resolve index-based UI ownership without editing Translation or UI payloads"},
        {"dependency": "wet_variant", "status": "conversion_blocked", "blocks_installation": True, "next_evidence": "complete G1M/SWG conversion and exact G1M-to-G1T binding"},
        {"dependency": "runtime_validation", "status": "not_performed", "blocks_installation": True, "next_evidence": "runtime validation is forbidden until a complete transactional profile exists"},
    ]

    write_tsv(output_dir / "DLC_BKN_PE_MODULE_AUDIT.tsv", [
        "side", "module_path", "size", "sha256", "machine", "pe_kind", "image_base", "size_of_image",
        "section_count", "runtime_function_entries", "deduplicated_exact_token_locations", "code_xref_candidates",
        "data_pointer_candidates", "rva_value_candidates", "bkn_token_locations", "control_token_locations",
        "scan_status", "raw_module_exported",
    ], module_rows)
    write_tsv(output_dir / "DLC_BKN_PE_SECTION_MAP.tsv", [
        "side", "module_path", "section_index", "section_name", "virtual_address", "virtual_size", "raw_offset",
        "raw_size", "characteristics", "executable", "readable", "writable", "contains_code", "contains_initialized_data",
    ], all_sections)
    write_tsv(output_dir / "DLC_BKN_RUNTIME_TOKEN_CLASSIFICATION.tsv", [
        "side", "module_path", "module_sha256", "token_offset", "token_rva", "token_va", "token_section", "encoding",
        "primary_token", "aliases", "family", "byte_length", "technical_cluster_tokens", "technical_cluster_sha256",
        "code_xref_candidates", "data_pointer_candidates", "rva_value_candidates", "binding_proven",
    ], all_tokens)
    write_tsv(output_dir / "DLC_BKN_RUNTIME_XREF_CANDIDATES.tsv", [
        "side", "module_path", "module_sha256", "reference_kind", "reference_strength", "reference_offset", "reference_rva",
        "reference_section", "reference_section_executable", "target_offset", "target_rva", "target_primary_token", "target_aliases",
        "target_family", "target_interior_delta", "instruction_length", "instruction_sha256", "rex_prefix_present",
        "function_begin_rva", "function_end_rva", "function_unwind_rva", "function_boundary_source", "binding_proven",
    ], sorted(all_xrefs, key=lambda row: (row["side"], row["module_path"], int(row["reference_offset"]), row["reference_kind"], row["target_primary_token"])))
    write_tsv(output_dir / "DLC_BKN_RUNTIME_FUNCTION_CLUSTERS.tsv", [
        "side", "module_path", "function_begin_rva", "function_end_rva", "function_size", "function_section", "function_sha256",
        "reference_count", "reference_families", "target_tokens", "contains_bkn_reference", "contains_control_reference",
        "function_semantics_proven",
    ], function_rows)
    write_tsv(output_dir / "DLC_BKN_CONTROL_REFERENCE_COMPARISON.tsv", [
        "side", "module_path", "family", "token_locations", "code_xref_candidates", "data_pointer_candidates",
        "rva_value_candidates", "primary_tokens", "classification", "runtime_binding_proven",
    ], comparison_rows)
    write_tsv(output_dir / "DLC_BKN_PE_REFERENCE_GAPS.tsv", [
        "dependency", "status", "blocks_installation", "next_evidence",
    ], gaps)

    summary = {
        "type": "br_quartet_legacy_dlc_bkn_pe_reference_summary",
        "format_version": FORMAT_VERSION,
        "tool_version": TOOL_VERSION,
        "content_id": "costume_pc00_bkn",
        "status": status,
        "exact_token_modules": len(module_rows),
        "pe_sections": len(all_sections),
        "deduplicated_exact_token_locations": len(all_tokens),
        "bkn_token_locations": sum(row["family"] == "bkn" for row in all_tokens),
        "control_token_locations": sum(row["family"] in {"twl", "scl", "costume_change"} for row in all_tokens),
        "xref_candidates": len(all_xrefs),
        "code_xref_candidates": code_xrefs,
        "bkn_code_xref_candidates": bkn_code_xrefs,
        "bkn_total_xref_candidates": bkn_any_xrefs,
        "function_clusters": len(function_rows),
        "control_comparison_rows": len(comparison_rows),
        "unresolved_installation_blockers": len(gaps),
        "next_action": next_action,
        "findings": [
            "exact token offsets are mapped to verified PE sections and deduplicated so prefix aliases such as BKN/BKN_W are not double-counted",
            "RIP-relative code references, absolute pointers and raw RVA values are separated by reference strength",
            "PE exception-directory function ranges are used only when present; no full disassembly or function payload is exported",
            "BKN references are compared with TWL, SCL and costume_change controls without treating similarity or difference as entitlement proof",
            "static strings, pointers and code xrefs remain non-binding evidence and never authorize a module patch or profile build",
        ],
        "policy": {
            "game_modified": False,
            "git_modified": False,
            "translation_modified": False,
            "text_seed_unchanged": True,
            "system_table_modified": False,
            "runtime_module_modified": False,
            "raw_modules_exported": False,
            "raw_instruction_bytes_exported": False,
            "full_disassembly_exported": False,
            "raw_assets_exported_in_report": False,
            "raw_assets_in_update": False,
            "candidate_installed": False,
            "profile_registered": False,
            "profile_build_allowed": False,
            "profiles_activated": False,
            "runtime_validated": False,
            "static_pe_reference_is_runtime_binding_proof": False,
            "static_pe_reference_is_entitlement_proof": False,
            "runtime_module_patch_allowed": False,
            "translation_owned_text_exported": False,
        },
    }
    write_json(output_dir / "SUMMARY.json", summary)
    create_manifest(output_dir)
    archive_path = project_root / ".local/reports/quartet_legacy_dlc" / REPORT_ARCHIVE_NAME
    if create_report_archive:
        create_archive(output_dir, archive_path)
    else:
        archive_path = None
    return archive_path, summary


def validate_report(report_dir: Path) -> dict[str, Any]:
    required = {
        "DLC_BKN_PE_MODULE_AUDIT.tsv", "DLC_BKN_PE_SECTION_MAP.tsv", "DLC_BKN_RUNTIME_TOKEN_CLASSIFICATION.tsv",
        "DLC_BKN_RUNTIME_XREF_CANDIDATES.tsv", "DLC_BKN_RUNTIME_FUNCTION_CLUSTERS.tsv",
        "DLC_BKN_CONTROL_REFERENCE_COMPARISON.tsv", "DLC_BKN_PE_REFERENCE_GAPS.tsv", "SUMMARY.json", "REPORT_MANIFEST.json",
    }
    missing = sorted(name for name in required if not (report_dir / name).is_file())
    if missing:
        raise BknPeReferenceError(f"missing report files: {missing}")
    summary = json.loads((report_dir / "SUMMARY.json").read_text(encoding="utf-8"))
    if summary.get("tool_version") != TOOL_VERSION:
        raise BknPeReferenceError("unexpected tool version")
    if summary.get("status") not in {
        "bkn_pe_code_reference_candidates_found_semantics_unproven",
        "bkn_pe_data_reference_candidates_found_semantics_unproven",
        "bkn_tokens_present_without_resolved_pe_references",
    }:
        raise BknPeReferenceError("unexpected report status")
    policy = summary.get("policy", {})
    false_fields = (
        "game_modified", "git_modified", "translation_modified", "system_table_modified", "runtime_module_modified",
        "raw_modules_exported", "raw_instruction_bytes_exported", "full_disassembly_exported", "raw_assets_exported_in_report",
        "raw_assets_in_update", "candidate_installed", "profile_registered", "profile_build_allowed", "profiles_activated",
        "runtime_validated", "static_pe_reference_is_runtime_binding_proof", "static_pe_reference_is_entitlement_proof",
        "runtime_module_patch_allowed", "translation_owned_text_exported",
    )
    if any(policy.get(field) is not False for field in false_fields):
        raise BknPeReferenceError("report violates fail-closed policy")
    if policy.get("text_seed_unchanged") is not True:
        raise BknPeReferenceError("text seed must remain unchanged")
    modules = read_tsv(report_dir / "DLC_BKN_PE_MODULE_AUDIT.tsv")
    if not modules or any(row["scan_status"] != "passed" or row["raw_module_exported"] != "false" for row in modules):
        raise BknPeReferenceError("invalid PE module audit")
    tokens = read_tsv(report_dir / "DLC_BKN_RUNTIME_TOKEN_CLASSIFICATION.tsv")
    if not tokens or not any(row["family"] == "bkn" for row in tokens):
        raise BknPeReferenceError("BKN token classification is empty")
    if any(row["binding_proven"] != "false" for row in tokens):
        raise BknPeReferenceError("token binding must remain unproven")
    xrefs = read_tsv(report_dir / "DLC_BKN_RUNTIME_XREF_CANDIDATES.tsv")
    if any(row["binding_proven"] != "false" for row in xrefs):
        raise BknPeReferenceError("xref binding must remain unproven")
    gaps = read_tsv(report_dir / "DLC_BKN_PE_REFERENCE_GAPS.tsv")
    if len(gaps) != 5 or any(row["blocks_installation"] != "true" for row in gaps):
        raise BknPeReferenceError("installation blockers are incomplete")
    manifest = json.loads((report_dir / "REPORT_MANIFEST.json").read_text(encoding="utf-8"))
    for item in manifest.get("files", []):
        path = report_dir / item["path"]
        if path.suffix.casefold() in FORBIDDEN_REPORT_SUFFIXES:
            raise BknPeReferenceError(f"forbidden payload in report manifest: {path.name}")
        if path.stat().st_size != item["size"] or sha256_file(path) != item["sha256"]:
            raise BknPeReferenceError(f"manifest mismatch: {path.name}")
    return summary


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser(description=__doc__)
    value.add_argument("--project-root", type=Path, default=PROJECT_ROOT_DEFAULT)
    value.add_argument("--source-game", type=Path, default=Path(os.environ.get("BR_ORIGINAL_GAME_ROOT")))
    value.add_argument("--target-game", type=Path, default=Path(os.environ.get("BR_QUARTET_GAME_ROOT")))
    value.add_argument("--output-dir", type=Path)
    value.add_argument("--validate-only", action="store_true")
    value.add_argument("--no-report-archive", action="store_true")
    return value


def main() -> int:
    args = parser().parse_args()
    project_root = args.project_root.resolve()
    output_dir = args.output_dir or project_root / ".local/reports/quartet_legacy_dlc" / REPORT_DIR_NAME
    if args.validate_only:
        summary = validate_report(output_dir)
        print(f"Validated BKN PE-reference report: {output_dir}")
        print(f"Status: {summary['status']}")
        return 0
    archive_path, summary = audit(
        project_root,
        args.source_game.resolve(),
        args.target_game.resolve(),
        output_dir,
        create_report_archive=not args.no_report_archive,
    )
    print(f"PE modules: {summary['exact_token_modules']}")
    print(f"Deduplicated token locations: {summary['deduplicated_exact_token_locations']}")
    print(f"Xref candidates: {summary['xref_candidates']}")
    print(f"BKN code xrefs: {summary['bkn_code_xref_candidates']}")
    print(f"Report directory: {output_dir}")
    if archive_path:
        print(f"Report: {archive_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
