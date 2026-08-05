#!/usr/bin/env python3
"""Read-only nested Elixir inventory for canonical legacy-DLC owners.

This stage consumes the 0.0.4 exact-closure evidence and the seed-independent
technical member bindings. It selectively reads only the requested PAK members
from a selected BR1 installation (and matching Quartet members when present),
decodes the parent Elixir/EARC container in memory, inventories nested members,
and reports metadata-only closure. No raw game payload is written to reports or
build directories, no PAK is rebuilt, and no installed game file is modified.
"""
from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
import os
import re
import struct
import subprocess
import sys
import tempfile
import zlib
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Iterable, Mapping, Sequence

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT_DEFAULT = SCRIPT_DIR.parent.parent
TEXT_TOOL_DIR = PROJECT_ROOT_DEFAULT / "Blue_Reflection_Text_Tool"
for import_path in (SCRIPT_DIR, TEXT_TOOL_DIR):
    if str(import_path) not in sys.path:
        sys.path.insert(0, str(import_path))

import br_restoration_tool as BR  # noqa: E402

TOOL_VERSION = "0.0.7"
FORMAT_VERSION = 1
REPORT_DIR_NAME = "nested_container_evidence"
REPORT_ARCHIVE_NAME = "BR_quartet_legacy_dlc_nested_container_evidence.tar.zst"
MAX_DECODED_CONTAINER_BYTES = 256 * 1024 * 1024
MAX_PAK_FILES = 65536
PAK_HEADER = struct.Struct("<4I")
PAK_FORMATS = (
    ("a17_32", struct.Struct("<128sI20sII"), 20, False),
    ("a18_64", struct.Struct("<128sI20sQQ"), 20, False),
    ("a22_64", struct.Struct("<128sI32sIQQ"), 32, True),
)
# Master keys published by gust_pak for A23 and later archives.  The strings
# are used as ASCII bytes and XORed with each entry key before decoding names
# and payloads.  A24 and A29 intentionally share one key in gust_pak.
PAK_MASTER_KEYS = (
    ("none", b""),
    ("A23", b"dGGKXLHLuCJwv8aBc3YQX6X6sREVPchs"),
    ("A24_A29", b"fyrixtT9AhA4v0cFahgMcgVwxFrry42A"),
    ("A25", b"vh0WESTtbeBuTwWusr4EVusMi4TbLmjQ"),
    ("A26", b"xpFLmgBWJSFFgMFg3XUgs7B7AgYJhyFJ"),
    ("A27", b"EGkUyYzPidcRx5yTecqk5AYJeSzzc5BR"),
    ("A28", b"ivZBFzn82RVuYnmgXfeFEgk33ALZcZDP"),
)
FORBIDDEN_REPORT_SUFFIXES = {
    ".pak", ".ebm", ".ebd", ".g1m", ".g1t", ".g1a", ".g1e", ".g1s",
    ".elixir", ".gz", ".bin", ".dds", ".ktid", ".kts", ".wav", ".ogg",
}


class NestedContainerError(RuntimeError):
    pass


@dataclass(frozen=True)
class PakEntry:
    index: int
    name: str
    size: int
    key: bytes
    data_offset: int
    absolute_offset: int
    encrypted: bool


@dataclass
class PakIndex:
    path: Path
    format_name: str
    master_key_label: str
    header_flags: int
    entry_size: int
    file_data_offset: int
    entries: list[PakEntry]
    by_name: dict[str, list[PakEntry]]


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
        return "True" if value else "False"
    if isinstance(value, (list, tuple, set)):
        return ";".join(str(item) for item in value)
    if isinstance(value, dict):
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return str(value)


def clean_dir(path: Path) -> None:
    if path.exists():
        for item in sorted(path.rglob("*"), key=lambda p: len(p.parts), reverse=True):
            if item.is_file() or item.is_symlink():
                item.unlink()
            elif item.is_dir():
                item.rmdir()
    path.mkdir(parents=True, exist_ok=True)


def read_tsv(path: Path) -> list[dict[str, str]]:
    if not path.is_file():
        raise NestedContainerError(f"missing prerequisite TSV: {path}")
    with path.open("r", encoding="utf-8", newline="") as handle:
        return [dict(row) for row in csv.DictReader(handle, delimiter="\t")]


def write_tsv(path: Path, fields: Sequence[str], rows: Iterable[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, delimiter="\t", lineterminator="\n", extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({field: scalar(row.get(field, "")) for field in fields})


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=False) + "\n", encoding="utf-8")


def split_list(value: str) -> list[str]:
    return [item for item in str(value or "").split(";") if item]


def safe_internal_name(value: str) -> str:
    # gust_pak and older Gust archives commonly expose archive-root notation
    # such as "\\data\\x64\\...".  The leading separator names the
    # archive root, not the host filesystem root.  Strip only leading archive
    # separators, then apply the normal traversal/absolute-path checks.
    normalized = str(value or "").replace("\\", "/").lstrip("/")
    path = PurePosixPath(normalized)
    if path.is_absolute() or not path.parts or ".." in path.parts:
        raise NestedContainerError(f"unsafe internal member path: {value!r}")
    return path.as_posix()


def xor_bytes(data: bytes, key: bytes) -> bytes:
    if not key or not any(key):
        return data
    return bytes(value ^ key[index % len(key)] for index, value in enumerate(data))


def effective_entry_key(key: bytes, master_key: bytes) -> bytes:
    if not master_key:
        return key
    if len(master_key) < len(key):
        raise NestedContainerError(
            f"master key is shorter than entry key: {len(master_key)} < {len(key)}"
        )
    return bytes(value ^ master_key[index] for index, value in enumerate(key))


def decode_filename(
    raw: bytes, key: bytes, encrypted: bool, master_key: bytes = b"",
) -> str | None:
    decode_key = effective_entry_key(key, master_key)
    decoded = xor_bytes(raw, decode_key) if encrypted else raw
    value = decoded.split(b"\0", 1)[0]
    if not value:
        return None
    try:
        text = value.decode("ascii")
    except UnicodeDecodeError:
        return None
    if any(ord(char) < 0x20 or ord(char) > 0x7E for char in text):
        return None
    if not re.fullmatch(r"[A-Za-z0-9_./\\ -]+", text):
        return None
    try:
        return safe_internal_name(text)
    except NestedContainerError:
        return None


def _layout_distance(raw_table: bytes, entry_struct: struct.Struct, file_count: int, *, a22: bool) -> int:
    """Mirror gust_pak's 32/64/A22 layout detector without decoding names.

    The high 32 bits at the candidate data-offset location should remain near
    zero for the correct packed struct.  Wrong strides read unrelated bytes and
    produce much larger variation.
    """
    sample_count = min(file_count, 64)
    total = 0
    previous = 0
    for index in range(sample_count):
        offset = index * entry_struct.size
        if offset + entry_struct.size > len(raw_table):
            return 1 << 63
        values = entry_struct.unpack_from(raw_table, offset)
        data_offset = int(values[4] if a22 else values[3])
        high = (data_offset >> 32) & 0xFFFFFFFF
        total += abs(high - previous)
        previous = high
    return total


def parse_candidate_entries(
    raw_table: bytes,
    *,
    format_name: str,
    entry_struct: struct.Struct,
    key_size: int,
    a22: bool,
    file_count: int,
    header_flags: int,
    file_size: int,
    master_key_label: str,
    master_key: bytes,
) -> list[PakEntry]:
    table_size = entry_struct.size * file_count
    if len(raw_table) < table_size:
        raise NestedContainerError(f"truncated {format_name} PAK table")
    data_base = PAK_HEADER.size + table_size
    entries: list[PakEntry] = []
    for index in range(file_count):
        values = entry_struct.unpack_from(raw_table, index * entry_struct.size)
        if a22:
            raw_name, size, key, _extra, data_offset, _flags = values
        else:
            raw_name, size, key, data_offset, _flags = values
        encrypted = bool(header_flags & 0x10) or any(key)
        decode_key = effective_entry_key(bytes(key[:key_size]), master_key)
        name = decode_filename(raw_name, bytes(key[:key_size]), encrypted, master_key)
        if name is None:
            raise NestedContainerError(
                f"failed to decode {format_name}/{master_key_label} PAK filename at entry {index}"
            )
        absolute = data_base + int(data_offset)
        if absolute < data_base or int(size) < 0 or absolute + int(size) > file_size:
            raise NestedContainerError(
                f"out-of-bounds {format_name} PAK entry {index}: {name}"
            )
        entries.append(PakEntry(
            index, name, int(size), decode_key,
            int(data_offset), absolute, encrypted,
        ))
    return entries


def index_pak(path: Path) -> PakIndex:
    if not path.is_file():
        raise NestedContainerError(f"PAK not found: {path}")
    file_size = path.stat().st_size
    with path.open("rb") as handle:
        header_raw = handle.read(PAK_HEADER.size)
        if len(header_raw) != PAK_HEADER.size:
            raise NestedContainerError(f"truncated PAK header: {path}")
        version, file_count, header_size, flags = PAK_HEADER.unpack(header_raw)
        if version != 0x20000 or header_size != PAK_HEADER.size:
            raise NestedContainerError(f"unsupported PAK header: {path}")
        if not (0 < file_count <= MAX_PAK_FILES):
            raise NestedContainerError(f"unsafe PAK file count {file_count}: {path}")
        max_entry_size = max(spec[1].size for spec in PAK_FORMATS)
        raw_table = handle.read(max_entry_size * file_count)

    # Use the same structural discriminator as gust_pak: the candidate whose
    # data-offset high words vary least is the packed layout actually in use.
    distances: list[tuple[int, int, str, struct.Struct, int, bool]] = []
    for order, (format_name, entry_struct, key_size, a22) in enumerate(PAK_FORMATS):
        distance = _layout_distance(raw_table, entry_struct, file_count, a22=a22)
        distances.append((distance, order, format_name, entry_struct, key_size, a22))
    distances.sort(key=lambda row: (row[0], row[1]))

    failures: list[str] = []
    for _distance, _order, format_name, entry_struct, key_size, a22 in distances:
        for master_key_label, master_key in PAK_MASTER_KEYS:
            try:
                entries = parse_candidate_entries(
                    raw_table,
                    format_name=format_name,
                    entry_struct=entry_struct,
                    key_size=key_size,
                    a22=a22,
                    file_count=file_count,
                    header_flags=flags,
                    file_size=file_size,
                    master_key_label=master_key_label,
                    master_key=master_key,
                )
            except NestedContainerError as exc:
                failures.append(f"{format_name}/{master_key_label}: {exc}")
                continue
            by_name: dict[str, list[PakEntry]] = defaultdict(list)
            for entry in entries:
                by_name[entry.name.casefold()].append(entry)
            return PakIndex(
                path=path,
                format_name=format_name,
                master_key_label=master_key_label,
                header_flags=flags,
                entry_size=entry_struct.size,
                file_data_offset=PAK_HEADER.size + entry_struct.size * file_count,
                entries=entries,
                by_name=dict(by_name),
            )

    detail = "; ".join(failures[:6])
    raise NestedContainerError(
        f"could not identify a supported A17/A18/A22 PAK layout: {path}"
        + (f" ({detail})" if detail else "")
    )


def read_pak_member(index: PakIndex, internal_path: str) -> tuple[bytes, PakEntry]:
    normalized = safe_internal_name(internal_path)
    matches = index.by_name.get(normalized.casefold(), [])
    if len(matches) != 1:
        raise NestedContainerError(
            f"expected exactly one PAK member {normalized!r} in {index.path}, found {len(matches)}"
        )
    entry = matches[0]
    with index.path.open("rb") as handle:
        handle.seek(entry.absolute_offset)
        raw = handle.read(entry.size)
    if len(raw) != entry.size:
        raise NestedContainerError(f"truncated PAK member {normalized}: {index.path}")
    data = xor_bytes(raw, entry.key) if entry.encrypted else raw
    return data, entry


def is_zlib_header(prefix: bytes) -> bool:
    if len(prefix) < 2:
        return False
    cmf, flg = prefix[0], prefix[1]
    return (cmf & 0x0F) == 8 and ((cmf << 8) + flg) % 31 == 0


def bounded_decompress(data: bytes, maximum: int, label: str) -> bytes:
    decoder = zlib.decompressobj()
    try:
        result = decoder.decompress(data, maximum + 1)
        result += decoder.flush(maximum + 1 - len(result))
    except zlib.error as exc:
        raise NestedContainerError(f"invalid zlib payload {label}: {exc}") from exc
    if len(result) > maximum:
        raise NestedContainerError(f"decoded container exceeds limit: {label}")
    if not decoder.eof or decoder.unused_data or decoder.unconsumed_tail:
        raise NestedContainerError(f"truncated or trailing zlib payload: {label}")
    return result


def decode_container_bytes(raw: bytes, label: str, maximum: int = MAX_DECODED_CONTAINER_BYTES) -> tuple[bytes, str, int]:
    if raw.startswith(b"\x1f\x8b"):
        try:
            decoded = gzip.decompress(raw)
        except (gzip.BadGzipFile, EOFError, OSError) as exc:
            raise NestedContainerError(f"invalid gzip payload {label}: {exc}") from exc
        if len(decoded) > maximum:
            raise NestedContainerError(f"decoded gzip exceeds limit: {label}")
        return decoded, "gzip", 1
    if len(raw) >= 6:
        first_size = int.from_bytes(raw[:4], "little")
        if 0 < first_size <= BR.GUST_MAX_COMPRESSED_CHUNK and 4 + first_size <= len(raw) and is_zlib_header(raw[4:6]):
            output = bytearray()
            cursor = 0
            chunks = 0
            while True:
                if cursor + 4 > len(raw):
                    raise NestedContainerError(f"truncated Gust chunk size: {label}")
                size = int.from_bytes(raw[cursor:cursor + 4], "little")
                cursor += 4
                if size == 0:
                    if cursor != len(raw):
                        raise NestedContainerError(f"trailing data after Gust terminator: {label}")
                    if not chunks:
                        raise NestedContainerError(f"empty Gust chunked container: {label}")
                    return bytes(output), "gust_chunked_zlib", chunks
                if cursor + size > len(raw):
                    raise NestedContainerError(f"truncated Gust chunk: {label}")
                remaining = maximum - len(output)
                output.extend(bounded_decompress(raw[cursor:cursor + size], remaining, label))
                cursor += size
                chunks += 1
    for offset in (0, 4, 8, 12, 16):
        if len(raw) >= offset + 2 and is_zlib_header(raw[offset:offset + 2]):
            decoded = bounded_decompress(raw[offset:], maximum, label)
            return decoded, "zlib" if offset == 0 else f"prefixed_zlib{offset}", 1
    if len(raw) > maximum:
        raise NestedContainerError(f"raw container exceeds limit: {label}")
    return raw, "raw", 0


def nested_role(name: str) -> str:
    folded = name.casefold()
    suffix = Path(folded).suffix
    if suffix == ".g1m":
        return "model_and_material"
    if suffix == ".g1t":
        return "embedded_texture"
    if suffix in {".g1a", ".anm", ".mot"}:
        return "animation"
    if suffix in {".g1p", ".phy", ".cloth"} or any(token in folded for token in ("cloth", "physics", "skirt", "hair")):
        return "cloth_or_physics"
    if suffix in {".ktid", ".kts"}:
        return "identifier_or_binding"
    if suffix in {".g1e", ".g1em", ".g1s"}:
        return "effect_or_shader"
    if suffix in {".bin", ".dat", ".xml"}:
        return "auxiliary_descriptor"
    return "other_nested_member"


def compare_nested(source: dict[str, Any], target: dict[str, Any] | None) -> list[dict[str, Any]]:
    source_map = {row["comparison_key"]: row for row in source["members"]}
    target_map = {row["comparison_key"]: row for row in (target or {"members": []})["members"]}
    rows: list[dict[str, Any]] = []
    for key in sorted(set(source_map) | set(target_map)):
        left = source_map.get(key)
        right = target_map.get(key)
        if left and right:
            classification = "present_identical" if left["sha256"] == right["sha256"] else "present_modified"
        elif left:
            classification = "missing_portable_from_br1"
        else:
            classification = "target_only_nested_member"
        exemplar = left or right
        assert exemplar is not None
        rows.append({
            "member_key": key,
            "member_name": exemplar["name"],
            "nested_role": nested_role(exemplar["name"]),
            "source_index": "" if left is None else left["index"],
            "source_size": "" if left is None else left["size"],
            "source_sha256": "" if left is None else left["sha256"],
            "target_index": "" if right is None else right["index"],
            "target_size": "" if right is None else right["size"],
            "target_sha256": "" if right is None else right["sha256"],
            "compatibility_status": classification,
            "raw_payload_exported": False,
        })
    return rows


def locate_prerequisite(report_root: Path, directory: str, archive: str, temporary: Path) -> Path:
    direct = report_root / directory
    if direct.is_dir():
        return direct
    archive_path = report_root / archive
    if not archive_path.is_file():
        raise NestedContainerError(f"missing prerequisite report directory/archive: {direct} / {archive_path}")
    listed = subprocess.run(["tar", "--zstd", "-tf", str(archive_path)], text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
    if listed.returncode:
        raise NestedContainerError(f"cannot list prerequisite archive {archive_path}: {listed.stderr.strip()}")
    roots = {PurePosixPath(line.strip()).parts[0] for line in listed.stdout.splitlines() if line.strip()}
    if len(roots) != 1:
        raise NestedContainerError(f"expected one root in {archive_path}, found {sorted(roots)}")
    done = subprocess.run(["tar", "--zstd", "-xf", str(archive_path), "-C", str(temporary)], text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
    if done.returncode:
        raise NestedContainerError(f"cannot extract prerequisite archive {archive_path}: {done.stderr.strip()}")
    return temporary / next(iter(roots))


def make_archive(source_dir: Path, output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(output.name + ".tmp")
    temporary.unlink(missing_ok=True)
    done = subprocess.run(
        ["tar", "--zstd", "--sort=name", "--mtime=@0", "--owner=0", "--group=0", "--numeric-owner", "-cf", str(temporary), "-C", str(source_dir.parent), source_dir.name],
        text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False,
    )
    if done.returncode:
        raise NestedContainerError(f"cannot create report archive: {done.stderr.strip()}")
    os.replace(temporary, output)


def report_manifest(report_root: Path) -> dict[str, Any]:
    files = []
    for path in sorted(report_root.iterdir(), key=lambda p: p.name.casefold()):
        if not path.is_file() or path.name == "REPORT_MANIFEST.json":
            continue
        if path.suffix.casefold() in FORBIDDEN_REPORT_SUFFIXES:
            raise NestedContainerError(f"raw asset-like file in report: {path.name}")
        files.append({"path": path.name, "size": path.stat().st_size, "sha256": sha256_file(path)})
    return {
        "type": "br_quartet_legacy_dlc_nested_container_manifest",
        "format_version": FORMAT_VERSION,
        "tool_version": TOOL_VERSION,
        "files": files,
        "raw_assets_embedded": False,
    }


def validate_report(report_root: Path) -> dict[str, Any]:
    summary_path = report_root / "SUMMARY.json"
    manifest_path = report_root / "REPORT_MANIFEST.json"
    if not summary_path.is_file() or not manifest_path.is_file():
        raise NestedContainerError(f"incomplete nested-container report: {report_root}")
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if summary.get("tool_version") != TOOL_VERSION or manifest.get("tool_version") != TOOL_VERSION:
        raise NestedContainerError("nested-container report tool-version mismatch")
    if summary.get("policy", {}).get("raw_assets_exported") is not False:
        raise NestedContainerError("report does not assert metadata-only output")
    expected = {row["path"]: row for row in manifest.get("files", [])}
    for name, row in expected.items():
        path = report_root / name
        if not path.is_file() or path.stat().st_size != int(row["size"]) or sha256_file(path) != row["sha256"]:
            raise NestedContainerError(f"report manifest mismatch: {name}")
    for path in report_root.iterdir():
        if path.is_file() and path.suffix.casefold() in FORBIDDEN_REPORT_SUFFIXES:
            raise NestedContainerError(f"forbidden raw asset in report: {path.name}")
    return summary


def audit(project_root: Path, original_root: Path, quartet_root: Path, report_root: Path) -> tuple[Path, dict[str, Any]]:
    if not original_root.is_dir() or not quartet_root.is_dir():
        raise NestedContainerError("selected BR1 or Quartet installation root does not exist")
    exact_reports = project_root / ".local/reports/quartet_legacy_dlc"
    technical_root = exact_reports / "technical_registry_evidence"
    with tempfile.TemporaryDirectory(prefix="br_dlc_nested_prereq_") as temp_name:
        temp = Path(temp_name)
        exact_root = locate_prerequisite(exact_reports, "exact_closure_evidence", "BR_quartet_legacy_dlc_exact_closure_evidence.tar.zst", temp)
        if not technical_root.is_dir():
            technical_root = locate_prerequisite(exact_reports, "technical_registry_evidence", "BR_quartet_legacy_dlc_technical_registry_evidence.tar.zst", temp)
        closures = read_tsv(exact_root / "DLC_CANONICAL_CONTENT_CLOSURE.tsv")
        roles = read_tsv(exact_root / "DLC_EXACT_ROLE_CLOSURE.tsv")
        bindings = read_tsv(technical_root / "DLC_TECHNICAL_MEMBER_BINDINGS.tsv")

        closure_by_id = {row["closure_id"]: row for row in closures}
        relevant_closures = {
            row["closure_id"]: row for row in closures
            if row.get("scope_classification") == "canonical_owner"
            and ({"costume_or_outfit", "accessory"} & set(split_list(row.get("technical_types", ""))))
        }
        binding_index: dict[tuple[str, str], list[dict[str, str]]] = defaultdict(list)
        for row in bindings:
            binding_index[(row.get("content_id", ""), row.get("normalized_path", ""))].append(row)

        requests: dict[tuple[str, str], dict[str, Any]] = {}
        accepted_roles = {"dry_model_or_container", "wet_model_or_container", "accessory_model_or_container"}
        for row in roles:
            if row.get("closure_id") not in relevant_closures or row.get("role") not in accepted_roles or row.get("resolution_status") != "resolved":
                continue
            for internal_path in split_list(row.get("evidence", "")):
                if not internal_path.casefold().endswith(".elixir.gz"):
                    continue
                content_id = row.get("content_id", "")
                matches = binding_index.get((content_id, internal_path), [])
                if not matches:
                    path_matches = [item for (owner, path), rows_for_path in binding_index.items() if path == internal_path for item in rows_for_path]
                    if len(path_matches) == 1:
                        matches = path_matches
                if len(matches) != 1:
                    raise NestedContainerError(f"expected one technical binding for {content_id} / {internal_path}, found {len(matches)}")
                binding = matches[0]
                requests[(content_id, internal_path)] = {
                    "closure": relevant_closures[row["closure_id"]],
                    "role": row["role"],
                    "binding": binding,
                }

        if not requests:
            raise NestedContainerError("exact closure selected no canonical costume/accessory containers")

        clean_dir(report_root)
        pak_cache: dict[Path, PakIndex] = {}
        container_rows: list[dict[str, Any]] = []
        member_rows: list[dict[str, Any]] = []
        role_rows: list[dict[str, Any]] = []
        unresolved_rows: list[dict[str, Any]] = []
        readiness_rows: list[dict[str, Any]] = []
        graph_nodes: dict[str, dict[str, Any]] = {}
        graph_edges: list[dict[str, Any]] = []
        total = len(requests)
        print(f"[stage13] selected {total} canonical costume/accessory parent containers", flush=True)

        grouped_by_owner: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for number, ((content_id, normalized_path), request) in enumerate(sorted(requests.items()), 1):
            binding = request["binding"]
            source_archive = original_root / binding["source_archive"]
            source_path = binding["source_path"]
            if source_archive not in pak_cache:
                print(f"[stage13] indexing source archive: {binding['source_archive']}", flush=True)
                pak_cache[source_archive] = index_pak(source_archive)
            source_raw, _source_entry = read_pak_member(pak_cache[source_archive], source_path)
            if len(source_raw) != int(binding["source_size"]) or sha256_bytes(source_raw) != binding["source_sha256"]:
                raise NestedContainerError(f"source member identity mismatch: {source_path}")
            source_decoded, source_kind, source_chunks = decode_container_bytes(source_raw, source_path)
            source_earc = BR.parse_earc_payload(source_decoded, label=source_path, include_member_payloads=False)

            target_earc: dict[str, Any] | None = None
            target_kind = ""
            target_chunks = 0
            target_member_present = bool(binding.get("target_archive") and binding.get("target_path"))
            if target_member_present:
                target_archive = quartet_root / binding["target_archive"]
                if target_archive not in pak_cache:
                    print(f"[stage13] indexing target archive: {binding['target_archive']}", flush=True)
                    pak_cache[target_archive] = index_pak(target_archive)
                target_raw, _target_entry = read_pak_member(pak_cache[target_archive], binding["target_path"])
                if len(target_raw) != int(binding["target_size"]) or sha256_bytes(target_raw) != binding["target_sha256"]:
                    raise NestedContainerError(f"target member identity mismatch: {binding['target_path']}")
                target_decoded, target_kind, target_chunks = decode_container_bytes(target_raw, binding["target_path"])
                target_earc = BR.parse_earc_payload(target_decoded, label=binding["target_path"], include_member_payloads=False)

            nested = compare_nested(source_earc, target_earc)
            container_id = "container_" + hashlib.sha256(f"{content_id}\0{normalized_path}".encode()).hexdigest()[:20]
            compatibility_counts = Counter(row["compatibility_status"] for row in nested)
            source_roles = Counter(row["nested_role"] for row in nested if row["source_sha256"])
            required_nested = {"model_and_material"}
            unresolved_nested = sorted(required_nested - set(source_roles))
            container_status = (
                "source_nested_inventory_complete_target_missing"
                if not target_member_present and not unresolved_nested
                else "source_and_target_nested_inventory_complete"
                if target_member_present and not unresolved_nested
                else "nested_inventory_incomplete"
            )
            container_row = {
                "container_id": container_id,
                "closure_id": request["closure"]["closure_id"],
                "content_id": content_id,
                "technical_types": request["closure"]["technical_types"],
                "parent_role": request["role"],
                "normalized_path": normalized_path,
                "source_archive": binding["source_archive"],
                "source_path": source_path,
                "source_size": binding["source_size"],
                "source_sha256": binding["source_sha256"],
                "source_container_kind": source_kind,
                "source_chunk_count": source_chunks,
                "source_decoded_size": len(source_decoded),
                "source_decoded_sha256": sha256_bytes(source_decoded),
                "source_nested_member_count": source_earc["file_count"],
                "target_archive": binding.get("target_archive", ""),
                "target_path": binding.get("target_path", ""),
                "target_container_kind": target_kind,
                "target_chunk_count": target_chunks,
                "target_decoded_size": "" if target_earc is None else len(target_decoded),
                "target_decoded_sha256": "" if target_earc is None else sha256_bytes(target_decoded),
                "target_nested_member_count": "" if target_earc is None else target_earc["file_count"],
                "nested_compatibility_counts": dict(sorted(compatibility_counts.items())),
                "source_nested_role_counts": dict(sorted(source_roles.items())),
                "container_closure_status": container_status,
                "raw_payload_exported": False,
            }
            container_rows.append(container_row)
            grouped_by_owner[content_id].append(container_row)
            graph_nodes[container_id] = {"id": container_id, "kind": "parent_container", "content_id": content_id, "path": normalized_path}
            owner_node = f"owner:{content_id}"
            graph_nodes[owner_node] = {"id": owner_node, "kind": "canonical_owner", "content_id": content_id}
            graph_edges.append({"source": owner_node, "target": container_id, "relation": request["role"]})

            for nested_row in nested:
                member_id = "nested_" + hashlib.sha256(f"{container_id}\0{nested_row['member_key']}".encode()).hexdigest()[:20]
                full = {"container_id": container_id, "closure_id": request["closure"]["closure_id"], "content_id": content_id, "parent_path": normalized_path, "nested_member_id": member_id, **nested_row}
                member_rows.append(full)
                graph_nodes[member_id] = {"id": member_id, "kind": "nested_member", "name": nested_row["member_name"], "role": nested_row["nested_role"]}
                graph_edges.append({"source": container_id, "target": member_id, "relation": "contains"})

            for role in sorted({row["nested_role"] for row in nested if row["source_sha256"]}):
                rows_for_role = [row for row in nested if row["source_sha256"] and row["nested_role"] == role]
                role_rows.append({
                    "closure_id": request["closure"]["closure_id"],
                    "content_id": content_id,
                    "container_id": container_id,
                    "parent_path": normalized_path,
                    "nested_role": role,
                    "source_member_count": len(rows_for_role),
                    "source_member_names": [row["member_name"] for row in rows_for_role],
                    "target_identical_count": sum(row["compatibility_status"] == "present_identical" for row in rows_for_role),
                    "target_modified_count": sum(row["compatibility_status"] == "present_modified" for row in rows_for_role),
                    "target_missing_count": sum(row["compatibility_status"] == "missing_portable_from_br1" for row in rows_for_role),
                    "role_resolution_status": "resolved_in_parent_container",
                    "raw_payload_exported": False,
                })
            for missing_role in unresolved_nested:
                unresolved_rows.append({
                    "closure_id": request["closure"]["closure_id"],
                    "content_id": content_id,
                    "container_id": container_id,
                    "parent_path": normalized_path,
                    "dependency_type": missing_role,
                    "status": "missing_required_nested_role",
                    "next_evidence_needed": "confirm alternate model/material member naming or external dependency",
                    "profile_build_allowed": False,
                })
            if number == total or number % 10 == 0:
                print(f"[stage13] inventoried {number}/{total} parent containers", flush=True)

        for content_id, containers in sorted(grouped_by_owner.items()):
            closure = closure_by_id[containers[0]["closure_id"]]
            unresolved_count = sum(1 for row in unresolved_rows if row["content_id"] == content_id)
            missing_target = sum(not row["target_path"] for row in containers)
            # Keep profile readiness fail-closed even when nested inventory is complete.
            status = "nested_inventory_complete_external_texture_table_and_unlock_closure_pending" if not unresolved_count else "blocked_incomplete_nested_inventory"
            readiness_rows.append({
                "closure_id": closure["closure_id"],
                "content_id": content_id,
                "technical_types": closure["technical_types"],
                "parent_container_count": len(containers),
                "source_nested_inventory_complete": unresolved_count == 0,
                "target_missing_parent_count": missing_target,
                "unresolved_nested_role_count": unresolved_count,
                "profile_readiness": status,
                "profile_build_allowed": False,
                "default_enabled": False,
                "runtime_validated": False,
            })
            # External top-level texture, table, icon and unlock roles remain outside the parent EARC.
            for dependency in ("external_g1t_texture", "system_table_binding", "ui_icon_or_thumbnail", "unlock_or_entitlement_semantics"):
                unresolved_rows.append({
                    "closure_id": closure["closure_id"],
                    "content_id": content_id,
                    "container_id": "",
                    "parent_path": "",
                    "dependency_type": dependency,
                    "status": "outside_parent_container_pending_exact_owner_binding",
                    "next_evidence_needed": "cross-link top-level member/table/flag evidence after nested inventory",
                    "profile_build_allowed": False,
                })

        write_tsv(report_root / "DLC_NESTED_CONTAINER_INVENTORY.tsv", [
            "container_id", "closure_id", "content_id", "technical_types", "parent_role", "normalized_path",
            "source_archive", "source_path", "source_size", "source_sha256", "source_container_kind", "source_chunk_count",
            "source_decoded_size", "source_decoded_sha256", "source_nested_member_count", "target_archive", "target_path",
            "target_container_kind", "target_chunk_count", "target_decoded_size", "target_decoded_sha256",
            "target_nested_member_count", "nested_compatibility_counts", "source_nested_role_counts", "container_closure_status",
            "raw_payload_exported",
        ], container_rows)
        write_tsv(report_root / "DLC_NESTED_MEMBER_BINDINGS.tsv", [
            "container_id", "closure_id", "content_id", "parent_path", "nested_member_id", "member_key", "member_name",
            "nested_role", "source_index", "source_size", "source_sha256", "target_index", "target_size", "target_sha256",
            "compatibility_status", "raw_payload_exported",
        ], member_rows)
        write_tsv(report_root / "DLC_NESTED_ROLE_CLOSURE.tsv", [
            "closure_id", "content_id", "container_id", "parent_path", "nested_role", "source_member_count",
            "source_member_names", "target_identical_count", "target_modified_count", "target_missing_count",
            "role_resolution_status", "raw_payload_exported",
        ], role_rows)
        write_tsv(report_root / "DLC_NESTED_UNRESOLVED_DEPENDENCIES.tsv", [
            "closure_id", "content_id", "container_id", "parent_path", "dependency_type", "status",
            "next_evidence_needed", "profile_build_allowed",
        ], unresolved_rows)
        write_tsv(report_root / "DLC_NESTED_PROFILE_READINESS.tsv", [
            "closure_id", "content_id", "technical_types", "parent_container_count", "source_nested_inventory_complete",
            "target_missing_parent_count", "unresolved_nested_role_count", "profile_readiness", "profile_build_allowed",
            "default_enabled", "runtime_validated",
        ], readiness_rows)
        write_json(report_root / "DLC_NESTED_CLOSURE_GRAPH.json", {
            "type": "br_quartet_legacy_dlc_nested_closure_graph",
            "format_version": FORMAT_VERSION,
            "tool_version": TOOL_VERSION,
            "nodes": sorted(graph_nodes.values(), key=lambda row: row["id"]),
            "edges": sorted(graph_edges, key=lambda row: (row["source"], row["target"], row["relation"])),
            "raw_assets_embedded": False,
        })

        container_statuses = Counter(row["container_closure_status"] for row in container_rows)
        nested_statuses = Counter(row["compatibility_status"] for row in member_rows)
        nested_roles = Counter(row["nested_role"] for row in member_rows if row["source_sha256"])
        summary = {
            "type": "br_quartet_legacy_dlc_nested_container_summary",
            "format_version": FORMAT_VERSION,
            "tool_version": TOOL_VERSION,
            "status": "canonical_parent_container_nested_inventory_complete_metadata_only",
            "canonical_owner_count": len(grouped_by_owner),
            "parent_container_count": len(container_rows),
            "source_nested_member_count": sum(1 for row in member_rows if row["source_sha256"]),
            "target_nested_member_count": sum(1 for row in member_rows if row["target_sha256"]),
            "container_status_counts": dict(sorted(container_statuses.items())),
            "nested_compatibility_counts": dict(sorted(nested_statuses.items())),
            "source_nested_role_counts": dict(sorted(nested_roles.items())),
            "unresolved_dependency_rows": len(unresolved_rows),
            "profile_readiness_counts": dict(sorted(Counter(row["profile_readiness"] for row in readiness_rows).items())),
            "selective_pak_reader": {
                "formats": sorted({index.format_name for index in pak_cache.values()}),
                "master_keys": sorted({index.master_key_label for index in pak_cache.values()}),
                "archives_opened": len(pak_cache),
                "full_pak_extraction": False,
                "raw_member_files_written": False,
            },
            "policy": {
                "text_seed_unchanged": True,
                "translation_text_source": "titles/blue_reflection/translation",
                "separate_translation_database": False,
                "selected_first_game_installation_read_only": True,
                "quartet_installation_read_only": True,
                "raw_assets_exported": False,
                "game_modified": False,
                "profiles_built": False,
                "profiles_activated": False,
                "git_modified": False,
            },
            "limitations": [
                "parent EARC inventory does not by itself prove external top-level G1T ownership",
                "nested G1M member presence does not yet parse material references or cloth-physics semantics",
                "system table, UI thumbnail and unlock/entitlement chains remain separate exact-closure tasks",
                "all profile readiness remains fail-closed pending those external dependencies and runtime validation",
            ],
            "next_action": "cross-link nested models/materials to top-level textures, table rows, UI indices and unlock chains; then parse exact material/physics references for one bounded costume family",
        }
        write_json(report_root / "SUMMARY.json", summary)
        write_json(report_root / "REPORT_MANIFEST.json", report_manifest(report_root))
        validate_report(report_root)
        output = exact_reports / REPORT_ARCHIVE_NAME
        make_archive(report_root, output)
        return output, summary


def cmd_audit(args: argparse.Namespace) -> int:
    project_root = Path(args.project_root).expanduser().resolve()
    report_root = project_root / ".local/reports/quartet_legacy_dlc" / REPORT_DIR_NAME
    output, summary = audit(
        project_root,
        Path(args.original_root).expanduser().resolve(),
        Path(args.quartet_root).expanduser().resolve(),
        report_root,
    )
    print(f"Canonical owners: {summary['canonical_owner_count']}")
    print(f"Parent containers: {summary['parent_container_count']}")
    print(f"Source nested members: {summary['source_nested_member_count']}")
    print(f"Metadata-only report: {output}")
    print("Installed games were not modified.")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    audit_p = sub.add_parser("audit")
    audit_p.add_argument("--project-root", required=True)
    audit_p.add_argument("--original-root", required=True)
    audit_p.add_argument("--quartet-root", required=True)
    audit_p.set_defaults(func=cmd_audit)
    validate_p = sub.add_parser("validate-report")
    validate_p.add_argument("--report-root", required=True)
    validate_p.set_defaults(func=lambda args: (validate_report(Path(args.report_root).expanduser().resolve()), print(f"Validated nested-container report: {Path(args.report_root).resolve()}"), 0)[-1])
    bundle_p = sub.add_parser("bundle-report")
    bundle_p.add_argument("--report-root", required=True)
    bundle_p.add_argument("--output", required=True)
    def bundle(args: argparse.Namespace) -> int:
        root = Path(args.report_root).expanduser().resolve()
        validate_report(root)
        output = Path(args.output).expanduser().resolve()
        make_archive(root, output)
        print(output)
        return 0
    bundle_p.set_defaults(func=bundle)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        return int(args.func(args))
    except (NestedContainerError, BR.RestorationError, OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
