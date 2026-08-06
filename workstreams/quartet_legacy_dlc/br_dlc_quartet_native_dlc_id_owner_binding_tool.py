#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import re
import shutil
import struct
import subprocess
import tempfile
from bisect import bisect_right
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Iterator, Mapping, Sequence

TOOL_VERSION = "0.0.60"
EXPECTED_STAGE99_SHA256 = "06d6a3c1dd3541c6bec35d54b8808a63e5c6756f12f1b5bd33fa376959912b53"
EXPECTED_B1_SHA256 = "3e1ac6e1304c42b0050839fbeada6e952722bdb486fbf1585d75ff4d82c7fed4"
STAGE99_PREFIX = "BR_QUARTET_NATIVE_COSTUME_POSITIVE_CONTROL_AUDIT_"
TAG_RE = re.compile(rb"PC\d{2}_DLC_[A-Z0-9]{2,8}(?:_W)?")
SKIP_DIRS = {".git", "windows", "winsxs", "system32", "syswow64", "cache", "caches", "tmp", "temp", "logs", "log", "crashdumps", "webcache", "code cache", "gpucache"}
STATE_SUFFIXES = {".sav", ".save", ".dat", ".bin", ".slot", ".bak", ".json", ".ini", ".cfg", ".xml", ".txt"}
MAX_STATE_SIZE = 256 * 1024 * 1024
MAX_HITS = 4096


class AuditError(RuntimeError):
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


@dataclass(frozen=True)
class PeImage:
    image_base: int
    size_of_headers: int
    size_of_image: int
    sections: tuple[Section, ...]
    exception_rva: int
    exception_size: int

    def offset_to_rva(self, offset: int) -> tuple[int | None, Section | None]:
        if 0 <= offset < self.size_of_headers:
            return offset, None
        for section in self.sections:
            if section.raw_offset <= offset < section.raw_offset + section.raw_size:
                return section.virtual_address + offset - section.raw_offset, section
        return None, None

    def rva_to_offset(self, rva: int) -> tuple[int | None, Section | None]:
        if 0 <= rva < self.size_of_headers:
            return rva, None
        for section in self.sections:
            span = max(section.virtual_size, section.raw_size)
            if section.virtual_address <= rva < section.virtual_address + span:
                delta = rva - section.virtual_address
                if delta < section.raw_size:
                    return section.raw_offset + delta, section
                return None, section
        return None, None


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def scalar(value: object) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (dict, list, tuple)):
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    if value is None:
        return ""
    return str(value)


def write_tsv(path: Path, rows: Sequence[Mapping[str, object]], fields: Sequence[str] | None = None) -> None:
    if fields is None:
        ordered: list[str] = []
        for row in rows:
            for key in row:
                if key not in ordered:
                    ordered.append(key)
        fields = ordered or ["status"]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(fields), delimiter="\t", lineterminator="\n")
        writer.writeheader()
        if rows:
            for row in rows:
                writer.writerow({field: scalar(row.get(field, "")) for field in fields})
        else:
            writer.writerow({fields[0]: "no_rows"})


def u16(data: bytes, offset: int) -> int:
    if offset < 0 or offset + 2 > len(data):
        raise AuditError(f"truncated u16 at 0x{offset:x}")
    return struct.unpack_from("<H", data, offset)[0]


def u32(data: bytes, offset: int) -> int:
    if offset < 0 or offset + 4 > len(data):
        raise AuditError(f"truncated u32 at 0x{offset:x}")
    return struct.unpack_from("<I", data, offset)[0]


def u64(data: bytes, offset: int) -> int:
    if offset < 0 or offset + 8 > len(data):
        raise AuditError(f"truncated u64 at 0x{offset:x}")
    return struct.unpack_from("<Q", data, offset)[0]


def parse_pe(data: bytes) -> PeImage:
    if len(data) < 0x100 or data[:2] != b"MZ":
        raise AuditError("B1.dll is not a PE image")
    pe_offset = u32(data, 0x3C)
    if data[pe_offset:pe_offset + 4] != b"PE\0\0":
        raise AuditError("missing PE signature")
    coff = pe_offset + 4
    section_count = u16(data, coff + 2)
    optional_size = u16(data, coff + 16)
    optional = coff + 20
    magic = u16(data, optional)
    if magic == 0x20B:
        image_base = u64(data, optional + 24)
        directory_count_offset = optional + 108
        directory_offset = optional + 112
    elif magic == 0x10B:
        image_base = u32(data, optional + 28)
        directory_count_offset = optional + 92
        directory_offset = optional + 96
    else:
        raise AuditError(f"unsupported PE magic 0x{magic:04x}")
    size_of_image = u32(data, optional + 56)
    size_of_headers = u32(data, optional + 60)
    directory_count = min(u32(data, directory_count_offset), 16)
    exception_rva = exception_size = 0
    if directory_count > 3 and directory_offset + 32 <= optional + optional_size:
        exception_rva = u32(data, directory_offset + 24)
        exception_size = u32(data, directory_offset + 28)
    section_table = optional + optional_size
    if not (0 < section_count <= 96) or section_table + section_count * 40 > len(data):
        raise AuditError("invalid PE section table")
    sections: list[Section] = []
    for index in range(section_count):
        base = section_table + index * 40
        name = data[base:base + 8].split(b"\0", 1)[0].decode("ascii", "replace") or f"section_{index}"
        section = Section(
            name=name,
            virtual_size=u32(data, base + 8),
            virtual_address=u32(data, base + 12),
            raw_size=u32(data, base + 16),
            raw_offset=u32(data, base + 20),
            characteristics=u32(data, base + 36),
        )
        if section.raw_offset + section.raw_size > len(data):
            raise AuditError(f"section exceeds module: {name}")
        sections.append(section)
    return PeImage(image_base, size_of_headers, size_of_image, tuple(sections), exception_rva, exception_size)


def runtime_functions(data: bytes, pe: PeImage) -> list[tuple[int, int]]:
    if pe.exception_rva == 0 or pe.exception_size < 12:
        return []
    offset, _ = pe.rva_to_offset(pe.exception_rva)
    if offset is None:
        return []
    rows: list[tuple[int, int]] = []
    limit = min(len(data), offset + pe.exception_size)
    for cursor in range(offset, limit - 11, 12):
        begin, end, _unwind = struct.unpack_from("<III", data, cursor)
        if 0 < begin < end <= pe.size_of_image:
            rows.append((begin, end))
    rows.sort()
    return rows


def containing_function(functions: Sequence[tuple[int, int]], rva: int) -> tuple[int, int] | None:
    if not functions:
        return None
    begins = [row[0] for row in functions]
    index = bisect_right(begins, rva) - 1
    if index >= 0 and functions[index][0] <= rva < functions[index][1]:
        return functions[index]
    return None


def all_offsets(data: bytes, needle: bytes, limit: int = MAX_HITS) -> list[int]:
    output: list[int] = []
    cursor = 0
    while len(output) < limit:
        found = data.find(needle, cursor)
        if found < 0:
            break
        output.append(found)
        cursor = found + 1
    return output


def section_row(pe: PeImage, offset: int) -> tuple[int | None, str, bool]:
    rva, section = pe.offset_to_rva(offset)
    return rva, section.name if section else "<headers>", bool(section and section.executable)


def parse_stage99(archive: Path) -> tuple[dict, dict]:
    if not archive.is_file() or archive.is_symlink():
        raise AuditError("stage-99 archive is missing or unsafe")
    actual = sha256_file(archive)
    if actual != EXPECTED_STAGE99_SHA256:
        raise AuditError(f"unexpected stage-99 SHA-256: {actual}")
    with tempfile.TemporaryDirectory(prefix="br_qdlc_stage99_") as td:
        temp = Path(td)
        listing = subprocess.run(["tar", "--zstd", "-tf", str(archive)], check=True, capture_output=True, text=True).stdout.splitlines()
        if not listing or any(name.startswith("/") or ".." in Path(name).parts for name in listing):
            raise AuditError("unsafe stage-99 archive member")
        subprocess.run(["tar", "--zstd", "-xf", str(archive), "-C", str(temp)], check=True)
        roots = [path for path in temp.iterdir() if path.is_dir()]
        if len(roots) != 1:
            raise AuditError("stage-99 archive must contain one root directory")
        root = roots[0]
        sums = root / "SHA256SUMS"
        if not sums.is_file():
            raise AuditError("stage-99 SHA256SUMS missing")
        for line in sums.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            expected, relative = line.split(None, 1)
            relative = relative.lstrip("*")
            path = root / relative
            if not path.is_file() or sha256_file(path) != expected:
                raise AuditError(f"stage-99 internal hash mismatch: {relative}")
        summary = json.loads((root / "SUMMARY.json").read_text(encoding="utf-8"))
        acceptance = json.loads((root / "POSITIVE_CONTROL_ACCEPTANCE.json").read_text(encoding="utf-8"))
        if summary.get("status") != "no_dlc_positive_control_proven":
            raise AuditError("stage-99 status is not the expected fail-closed result")
        if summary.get("conclusion", {}).get("valid_positive_control_found") is not False:
            raise AuditError("stage-99 unexpectedly claims a positive control")
        return summary, acceptance


def decode_configs(path: Path) -> list[tuple[str, str]]:
    raw = path.read_bytes()
    output: list[tuple[str, str]] = []
    for encoding in ("utf-8-sig", "utf-16-le", "cp932", "latin-1"):
        try:
            text = raw.decode(encoding)
        except UnicodeDecodeError:
            continue
        if encoding == "latin-1" or "\x00" not in text[:2048]:
            output.append((encoding, text))
    return output


def quartet_dlc_catalog(game_root: Path) -> tuple[str, list[dict]]:
    config = game_root / "steam_emu.ini"
    if not config.is_file() or config.is_symlink():
        raise AuditError("Quartet steam_emu.ini is required as auxiliary catalog evidence")
    app_id = ""
    rows: list[dict] = []
    for encoding, text in decode_configs(config):
        section = ""
        for line_no, raw_line in enumerate(text.splitlines(), 1):
            line = raw_line.strip()
            if not line or line.startswith((";", "#")):
                continue
            if line.startswith("[") and line.endswith("]"):
                section = line[1:-1].strip()
                continue
            if "=" not in line:
                continue
            key, value = (part.strip() for part in line.split("=", 1))
            if section.casefold() == "settings" and key.casefold() in {"appid", "app_id"} and value.isdigit():
                app_id = value
            if section.casefold() == "dlc" and key.isdigit():
                rows.append({
                    "dlc_id": key,
                    "name": value,
                    "line": line_no,
                    "encoding": encoding,
                    "costume_candidate": "uniform" in value.casefold() or "costume" in value.casefold() or "outfit" in value.casefold(),
                    "evidence_role": "auxiliary_platform_configuration",
                    "semantic_authority": False,
                    "original_appid_mapping_used": False,
                })
        if rows or app_id:
            break
    if not app_id or not rows:
        raise AuditError("Quartet platform catalog did not expose AppID and DLC rows")
    return app_id, rows


def find_targets(data: bytes, pe: PeImage, app_id: str, dlc_rows: Sequence[Mapping[str, object]]) -> tuple[list[dict], list[dict]]:
    app_rows: list[dict] = []
    identifiers = [("app_id", app_id)] + [("dlc_id", str(row["dlc_id"])) for row in dlc_rows]
    for kind, identifier in identifiers:
        value = int(identifier)
        patterns = [
            ("ascii_decimal", identifier.encode("ascii")),
            ("utf16le_decimal", identifier.encode("utf-16le")),
            ("uint32_le", struct.pack("<I", value)),
        ]
        for representation, needle in patterns:
            for offset in all_offsets(data, needle):
                rva, section, executable = section_row(pe, offset)
                app_rows.append({
                    "id_kind": kind,
                    "identifier": identifier,
                    "representation": representation,
                    "offset": offset,
                    "rva": rva,
                    "section": section,
                    "section_executable": executable,
                    "binding_proven": False,
                })
    tags: list[dict] = []
    for match in TAG_RE.finditer(data):
        token = match.group(0).decode("ascii")
        rva, section, executable = section_row(pe, match.start())
        tags.append({
            "token": token,
            "offset": match.start(),
            "rva": rva,
            "section": section,
            "section_executable": executable,
            "family": token.split("_DLC_", 1)[1].removesuffix("_W"),
            "binding_proven": False,
        })
    unique_tags = {(row["offset"], row["token"]): row for row in tags}
    return app_rows, list(unique_tags.values())


def rip_relative_xrefs(data: bytes, pe: PeImage, targets: Sequence[Mapping[str, object]], functions: Sequence[tuple[int, int]]) -> list[dict]:
    target_by_rva: list[tuple[int, int, Mapping[str, object]]] = []
    for target in targets:
        if target.get("rva") is None:
            continue
        length = len(str(target.get("token") or target.get("identifier")).encode("ascii", "ignore"))
        if target.get("representation") == "utf16le_decimal":
            length *= 2
        if target.get("representation") == "uint32_le":
            length = 4
        target_by_rva.append((int(target["rva"]), max(1, length), target))
    pattern = re.compile(
        rb"(?:(?P<rex>[\x40-\x4f]))?(?P<opcode>[\x8d\x8b\x89\x3b\x39])"
        rb"(?P<modrm>[\x05\x0d\x15\x1d\x25\x2d\x35\x3d])(?P<disp>.{4})",
        re.DOTALL,
    )
    rows: list[dict] = []
    for section in pe.sections:
        if not section.executable:
            continue
        body = data[section.raw_offset:section.raw_offset + section.raw_size]
        for match in pattern.finditer(body):
            instruction_rva = section.virtual_address + match.start()
            length = match.end() - match.start()
            displacement = struct.unpack("<i", match.group("disp"))[0]
            referenced_rva = instruction_rva + length + displacement
            for target_rva, target_len, target in target_by_rva:
                if target_rva <= referenced_rva < target_rva + target_len:
                    function = containing_function(functions, instruction_rva)
                    rows.append({
                        "target_kind": "costume_tag" if "token" in target else target.get("id_kind", "identifier"),
                        "target_value": target.get("token") or target.get("identifier"),
                        "target_representation": target.get("representation", "ascii_tag"),
                        "target_offset": target.get("offset"),
                        "target_rva": target_rva,
                        "reference_offset": section.raw_offset + match.start(),
                        "reference_rva": instruction_rva,
                        "reference_section": section.name,
                        "function_begin_rva": function[0] if function else "",
                        "function_end_rva": function[1] if function else "",
                        "reference_strength": "executable_rip_relative_candidate",
                        "binding_proven": False,
                    })
    return rows


def immediate_function_hits(data: bytes, pe: PeImage, app_rows: Sequence[Mapping[str, object]], functions: Sequence[tuple[int, int]]) -> list[dict]:
    rows: list[dict] = []
    for hit in app_rows:
        if hit.get("representation") != "uint32_le" or hit.get("section_executable") is not True or hit.get("rva") is None:
            continue
        function = containing_function(functions, int(hit["rva"]))
        rows.append({
            "identifier": hit["identifier"],
            "id_kind": hit["id_kind"],
            "offset": hit["offset"],
            "rva": hit["rva"],
            "section": hit["section"],
            "function_begin_rva": function[0] if function else "",
            "function_end_rva": function[1] if function else "",
            "reference_strength": "raw_uint32_in_executable_section",
            "binding_proven": False,
        })
    return rows


def function_correlations(immediates: Sequence[Mapping[str, object]], xrefs: Sequence[Mapping[str, object]]) -> list[dict]:
    tag_xrefs = [row for row in xrefs if row.get("target_kind") == "costume_tag" and row.get("function_begin_rva") != ""]
    rows: list[dict] = []
    for immediate in immediates:
        if immediate.get("function_begin_rva") == "":
            continue
        for xref in tag_xrefs:
            if (immediate["function_begin_rva"], immediate["function_end_rva"]) != (xref["function_begin_rva"], xref["function_end_rva"]):
                continue
            rows.append({
                "identifier": immediate["identifier"],
                "id_kind": immediate["id_kind"],
                "costume_tag": xref["target_value"],
                "function_begin_rva": immediate["function_begin_rva"],
                "function_end_rva": immediate["function_end_rva"],
                "appid_evidence": immediate["reference_strength"],
                "tag_evidence": xref["reference_strength"],
                "classification": "same_function_static_candidate",
                "exact_owner_binding_proven": False,
                "reason": "Static same-function correlation is a candidate only; runtime/state ownership remains unproven.",
            })
    unique = {(row["identifier"], row["costume_tag"], row["function_begin_rva"]): row for row in rows}
    return list(unique.values())


def candidate_state_files(root: Path) -> Iterator[Path]:
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        dirnames[:] = [name for name in dirnames if name.casefold() not in SKIP_DIRS]
        base = Path(dirpath)
        for name in filenames:
            path = base / name
            try:
                if path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_STATE_SIZE:
                    continue
            except OSError:
                continue
            rel = path.relative_to(root).as_posix().casefold()
            suffix = path.suffix.casefold()
            if suffix in STATE_SUFFIXES or any(token in rel for token in ("save", "savedata", "systemdata", "profile", "3825390", "quartet", "koeitecmo")):
                yield path


def scan_states(roots: Sequence[Path], identifiers: Sequence[str], tags: Sequence[str]) -> tuple[list[dict], list[dict]]:
    inventory: list[dict] = []
    hits: list[dict] = []
    needles: list[tuple[str, str, bytes]] = []
    for identifier in identifiers:
        needles.extend([
            ("identifier_ascii", identifier, identifier.encode("ascii")),
            ("identifier_utf16le", identifier, identifier.encode("utf-16le")),
            ("identifier_uint32_le", identifier, struct.pack("<I", int(identifier))),
        ])
    for tag in tags:
        needles.extend([("tag_ascii", tag, tag.encode("ascii")), ("tag_utf16le", tag, tag.encode("utf-16le"))])
    for index, root in enumerate(roots, 1):
        root = root.resolve()
        if not root.exists():
            inventory.append({"root": f"state_root_{index}", "relative_path": "", "status": "missing_root"})
            continue
        for path in candidate_state_files(root):
            rel = path.relative_to(root).as_posix()
            payload = path.read_bytes()
            inventory.append({
                "root": f"state_root_{index}",
                "relative_path": rel,
                "size": len(payload),
                "sha256": hashlib.sha256(payload).hexdigest(),
                "mtime_ns": path.stat().st_mtime_ns,
                "raw_content_exported": False,
            })
            for kind, value, needle in needles:
                for offset in all_offsets(payload, needle, limit=64):
                    hits.append({
                        "root": f"state_root_{index}",
                        "relative_path": rel,
                        "needle_kind": kind,
                        "value": value,
                        "offset": offset,
                        "raw_content_exported": False,
                        "binding_proven": False,
                    })
    return inventory, hits


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-root", required=True)
    parser.add_argument("--game-dir", required=True)
    parser.add_argument("--stage99-evidence", required=True)
    parser.add_argument("--state-root", action="append", default=[])
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args()

    project_root = Path(args.project_root).resolve()
    game_root = Path(args.game_dir).resolve()
    output = Path(args.output_dir).resolve()
    if output.exists():
        shutil.rmtree(output)
    output.mkdir(parents=True)

    version = (project_root / "workstreams/quartet_legacy_dlc/VERSION").read_text(encoding="utf-8").strip()
    if version != TOOL_VERSION:
        raise AuditError(f"quartet_legacy_dlc {TOOL_VERSION} is required, got {version}")

    stage99_summary, stage99_acceptance = parse_stage99(Path(args.stage99_evidence))
    app_id, catalog = quartet_dlc_catalog(game_root)
    b1 = game_root / "B1.dll"
    if not b1.is_file() or b1.is_symlink():
        raise AuditError("B1.dll is missing or unsafe")
    b1_sha = sha256_file(b1)
    if b1_sha != EXPECTED_B1_SHA256:
        raise AuditError(f"B1.dll changed: {b1_sha}")
    payload = b1.read_bytes()
    pe = parse_pe(payload)
    functions = runtime_functions(payload, pe)
    app_hits, tags = find_targets(payload, pe, app_id, catalog)
    target_rows = app_hits + tags
    xrefs = rip_relative_xrefs(payload, pe, target_rows, functions)
    immediates = immediate_function_hits(payload, pe, app_hits, functions)
    correlations = function_correlations(immediates, xrefs)

    identifiers = [app_id] + [str(row["dlc_id"]) for row in catalog]
    state_inventory, state_hits = scan_states([Path(value) for value in args.state_root], identifiers, [str(row["token"]) for row in tags])

    costume_ids = [row for row in catalog if row["costume_candidate"]]
    costume_correlations = [row for row in correlations if any(row["identifier"] == item["dlc_id"] for item in costume_ids)]
    exact_owner = False

    write_tsv(output / "QUARTET_PLATFORM_DLC_CATALOG.tsv", catalog)
    write_tsv(output / "B1_PE_SECTIONS.tsv", [{
        "name": section.name,
        "virtual_address": section.virtual_address,
        "virtual_size": section.virtual_size,
        "raw_offset": section.raw_offset,
        "raw_size": section.raw_size,
        "executable": section.executable,
    } for section in pe.sections])
    write_tsv(output / "QUARTET_DLC_ID_BINARY_HITS.tsv", app_hits)
    write_tsv(output / "QUARTET_COSTUME_TAG_TABLE.tsv", tags)
    write_tsv(output / "QUARTET_STATIC_XREF_CANDIDATES.tsv", xrefs)
    write_tsv(output / "QUARTET_DLC_ID_EXECUTABLE_IMMEDIATES.tsv", immediates)
    write_tsv(output / "QUARTET_DLC_ID_COSTUME_TAG_FUNCTION_CORRELATION.tsv", correlations)
    write_tsv(output / "STATE_CANDIDATE_INVENTORY.tsv", state_inventory)
    write_tsv(output / "STATE_DLC_AND_COSTUME_TOKEN_HITS.tsv", state_hits)

    acceptance = {
        "type": "br_quartet_native_dlc_id_owner_binding_acceptance",
        "format_version": 1,
        "tool_version": TOOL_VERSION,
        "status": "exact_owner_not_proven" if not exact_owner else "exact_owner_proven",
        "quartet_app_id": app_id,
        "quartet_costume_dlc_candidates": costume_ids,
        "same_function_static_candidates": costume_correlations,
        "exact_quartet_native_owner_binding_proven": exact_owner,
        "positive_control_proven": False,
        "static_proximity_is_owner_proof": False,
        "emulator_configuration_is_semantic_authority": False,
        "original_appid_semantics_used": False,
        "state_roots_supplied": len(args.state_root),
        "state_token_hits": len(state_hits),
        "required_next_action": "If no exact owner is proven, use this bounded candidate set to select an explicitly user-confirmed Quartet costume for a separately authorized state differential. Do not reinstall BKN or treat static correlation as ownership.",
        "authorization": stage99_summary["authorization"],
    }
    write_json(output / "OWNER_BINDING_ACCEPTANCE.json", acceptance)
    summary = {
        "type": "br_quartet_native_dlc_id_owner_binding_audit",
        "format_version": 1,
        "tool_version": TOOL_VERSION,
        "status": acceptance["status"],
        "stage99_bundle_sha256": EXPECTED_STAGE99_SHA256,
        "stage99_status": stage99_summary["status"],
        "quartet_app_id": app_id,
        "platform_dlc_rows": len(catalog),
        "costume_dlc_rows": len(costume_ids),
        "b1_sha256": b1_sha,
        "pe_sections": len(pe.sections),
        "runtime_functions": len(functions),
        "dlc_id_binary_hits": len(app_hits),
        "costume_tag_rows": len(tags),
        "static_xref_candidates": len(xrefs),
        "executable_immediate_candidates": len(immediates),
        "same_function_correlations": len(correlations),
        "costume_same_function_correlations": len(costume_correlations),
        "state_roots_supplied": len(args.state_root),
        "state_files_inventoried": len(state_inventory),
        "state_token_hits": len(state_hits),
        "exact_owner_binding_proven": exact_owner,
        "positive_control_proven": False,
        "game_files_modified": False,
        "save_files_modified": False,
        "raw_binary_exported": False,
        "raw_state_exported": False,
        "original_appid_semantics_used": False,
        "platform_configuration_semantic_authority": False,
    }
    write_json(output / "SUMMARY.json", summary)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (AuditError, OSError, ValueError, subprocess.CalledProcessError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}", file=os.sys.stderr)
        raise SystemExit(1)
