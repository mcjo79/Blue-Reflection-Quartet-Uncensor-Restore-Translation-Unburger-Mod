#!/usr/bin/env python3
"""Checksum-gated local PACK10_02 insertion test for the dry BKN fallback.

The stage extends a local copy of Quartet's PACK10_02 without extracting the
archive. Existing entry-table bytes and the complete encrypted data region are
copied through unchanged. Two new members are appended:

* data/b1/x64/character/pc00/pc00_dlc_bkn.elixir.gz
* data/b1/x64/character/pc00/pc00_dlc_bkn.g1t

The installed archive is opened read-only and hashed before and after. The
candidate remains under .local/build, is independently parsed, listed with the
project's authoritative gust_pak binary, and is never installed or registered
as a profile. Evidence archives contain metadata only.
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
import tarfile
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT_DEFAULT = SCRIPT_DIR.parent.parent
TEXT_TOOL_DIR = PROJECT_ROOT_DEFAULT / "Blue_Reflection_Text_Tool"
for item in (SCRIPT_DIR, TEXT_TOOL_DIR):
    if str(item) not in sys.path:
        sys.path.insert(0, str(item))

import br_dlc_nested_container_tool as NESTED  # noqa: E402

TOOL_VERSION = "0.0.13"
FORMAT_VERSION = 1
REPORT_DIR_NAME = "dry_pak_insertion_evidence"
REPORT_ARCHIVE_NAME = "BR_quartet_legacy_dlc_dry_pak_insertion_evidence.tar.zst"
BUILD_RELATIVE = Path(".local/build/quartet_legacy_dlc/pak_insertion_tests/costume_pc00_bkn_dry")
TRANSFER_BUILD_RELATIVE = Path(".local/build/quartet_legacy_dlc/transfer_probes/costume_pc00_bkn_dry")
TARGET_ARCHIVE_RELATIVE = Path("Data/PACK10_02.PAK")
ADDED_MEMBERS = (
    {
        "role": "dry_parent",
        "source_relative": Path("source_exact/data/x64/character/pc00/pc00_dlc_bkn.elixir.gz"),
        "target_path": "data/b1/x64/character/pc00/pc00_dlc_bkn.elixir.gz",
    },
    {
        "role": "dry_external_texture",
        "source_relative": Path("source_exact/data/x64/character/pc00/pc00_dlc_bkn.g1t"),
        "target_path": "data/b1/x64/character/pc00/pc00_dlc_bkn.g1t",
    },
)
FORBIDDEN_REPORT_SUFFIXES = {
    ".pak", ".ebm", ".ebd", ".g1m", ".g1t", ".g1a", ".g1e", ".g1s",
    ".elixir", ".gz", ".bin", ".swg", ".dds", ".wav", ".ogg",
}
COPY_BLOCK_SIZE = 8 * 1024 * 1024
FREE_SPACE_MARGIN = 256 * 1024 * 1024


class DryPakInsertionError(RuntimeError):
    pass


@dataclass(frozen=True)
class RawPakLayout:
    format_name: str
    entry_struct: struct.Struct
    key_size: int
    a22: bool
    version: int
    file_count: int
    header_size: int
    flags: int
    raw_table: bytes
    raw_data_size: int
    archive_root_prefix: str
    path_separator: str


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(COPY_BLOCK_SIZE), b""):
            digest.update(block)
    return digest.hexdigest()


def sha256_region(path: Path, offset: int, size: int) -> str:
    digest = hashlib.sha256()
    remaining = size
    with path.open("rb") as handle:
        handle.seek(offset)
        while remaining:
            block = handle.read(min(COPY_BLOCK_SIZE, remaining))
            if not block:
                raise DryPakInsertionError(f"truncated region while hashing: {path}")
            digest.update(block)
            remaining -= len(block)
    return digest.hexdigest()


def scalar(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (list, tuple, set, dict)):
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return str(value)


def read_tsv(path: Path) -> list[dict[str, str]]:
    if not path.is_file():
        raise DryPakInsertionError(f"missing prerequisite TSV: {path}")
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
        raise DryPakInsertionError(f"missing prerequisite report: {direct} / {packed}")
    extract_root = temporary / directory
    extract_root.mkdir(parents=True, exist_ok=True)
    subprocess.run(["tar", "--zstd", "-xf", str(packed), "-C", str(extract_root)], check=True)
    expected = extract_root / directory
    if expected.is_dir():
        return expected
    candidates = [item for item in extract_root.iterdir() if item.is_dir()]
    if len(candidates) == 1:
        return candidates[0]
    raise DryPakInsertionError(f"could not locate extracted prerequisite for {packed}")


def make_archive(source: Path, output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="br_dlc_dry_pak_bundle_") as temp_name:
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
            raise DryPakInsertionError(f"raw asset-like file in evidence report: {path}")
        rows.append({
            "path": path.relative_to(report_root).as_posix(),
            "size": path.stat().st_size,
            "sha256": sha256_file(path),
        })
    return rows


def pak_spec(format_name: str) -> tuple[struct.Struct, int, bool]:
    for name, entry_struct, key_size, a22 in NESTED.PAK_FORMATS:
        if name == format_name:
            return entry_struct, key_size, a22
    raise DryPakInsertionError(f"unsupported indexed PAK format: {format_name}")


def master_key_bytes(label: str) -> bytes:
    for key_label, value in NESTED.PAK_MASTER_KEYS:
        if key_label == label:
            return value
    raise DryPakInsertionError(f"unknown indexed PAK master key: {label}")


def raw_entry_parts(raw_entry: bytes, entry_struct: struct.Struct, *, a22: bool) -> tuple[bytes, int, bytes, int, int, int]:
    values = entry_struct.unpack(raw_entry)
    if a22:
        raw_name, size, key, extra, data_offset, flags = values
    else:
        raw_name, size, key, data_offset, flags = values
        extra = 0
    return bytes(raw_name), int(size), bytes(key), int(extra), int(data_offset), int(flags)


def decode_raw_name(raw_name: bytes, raw_key: bytes, *, encrypted: bool, master_key: bytes) -> str:
    effective = NESTED.effective_entry_key(raw_key, master_key)
    decoded = NESTED.xor_bytes(raw_name, effective) if encrypted else raw_name
    value = decoded.split(b"\0", 1)[0]
    try:
        return value.decode("ascii")
    except UnicodeDecodeError as exc:
        raise DryPakInsertionError("failed to decode baseline naming convention") from exc


def read_raw_layout(path: Path, index: NESTED.PakIndex) -> RawPakLayout:
    entry_struct, key_size, a22 = pak_spec(index.format_name)
    with path.open("rb") as handle:
        header_raw = handle.read(NESTED.PAK_HEADER.size)
        if len(header_raw) != NESTED.PAK_HEADER.size:
            raise DryPakInsertionError(f"truncated PAK header: {path}")
        version, file_count, header_size, flags = NESTED.PAK_HEADER.unpack(header_raw)
        if file_count != len(index.entries):
            raise DryPakInsertionError("indexed file count differs from raw header")
        raw_table = handle.read(entry_struct.size * file_count)
        if len(raw_table) != entry_struct.size * file_count:
            raise DryPakInsertionError(f"truncated PAK table: {path}")
    if header_size != NESTED.PAK_HEADER.size or index.file_data_offset != header_size + len(raw_table):
        raise DryPakInsertionError("baseline PAK table geometry mismatch")
    first = raw_table[:entry_struct.size]
    raw_name, _size, raw_key, _extra, _offset, _entry_flags = raw_entry_parts(first, entry_struct, a22=a22)
    encrypted = bool(flags & 0x10) or any(raw_key)
    decoded_name = decode_raw_name(raw_name, raw_key[:key_size], encrypted=encrypted, master_key=master_key_bytes(index.master_key_label))
    archive_root_prefix = "\\" if decoded_name.startswith(("\\", "/")) else ""
    path_separator = "\\" if "\\" in decoded_name else "/"
    raw_data_size = path.stat().st_size - index.file_data_offset
    if raw_data_size < 0:
        raise DryPakInsertionError("negative baseline PAK data size")
    return RawPakLayout(
        format_name=index.format_name,
        entry_struct=entry_struct,
        key_size=key_size,
        a22=a22,
        version=version,
        file_count=file_count,
        header_size=header_size,
        flags=flags,
        raw_table=raw_table,
        raw_data_size=raw_data_size,
        archive_root_prefix=archive_root_prefix,
        path_separator=path_separator,
    )


def deterministic_entry_key(target_path: str, key_size: int) -> bytes:
    material = hashlib.sha512(("BR_QUARTET_LEGACY_DLC_DRY_BKN\0" + target_path).encode("utf-8")).digest()
    key = material[:key_size]
    if not any(key):
        raise DryPakInsertionError("deterministic entry key unexpectedly all zero")
    return key


def archive_style_name(normalized: str, layout: RawPakLayout) -> str:
    safe = NESTED.safe_internal_name(normalized)
    styled = safe.replace("/", layout.path_separator)
    return layout.archive_root_prefix + styled


def build_raw_added_entry(
    *, target_path: str, payload: bytes, relative_offset: int,
    layout: RawPakLayout, master_key: bytes,
) -> tuple[bytes, bytes, dict[str, Any]]:
    styled_name = archive_style_name(target_path, layout)
    encoded_name = styled_name.encode("ascii")
    if len(encoded_name) >= 128:
        raise DryPakInsertionError(f"PAK member name too long: {styled_name}")
    raw_key = deterministic_entry_key(target_path, layout.key_size)
    effective_key = NESTED.effective_entry_key(raw_key, master_key)
    plain_name = encoded_name + b"\0" * (128 - len(encoded_name))
    raw_name = NESTED.xor_bytes(plain_name, effective_key)
    encoded_payload = NESTED.xor_bytes(payload, effective_key)
    if layout.a22:
        raw_entry = layout.entry_struct.pack(raw_name, len(payload), raw_key, 0, relative_offset, 0)
    else:
        raw_entry = layout.entry_struct.pack(raw_name, len(payload), raw_key, relative_offset, 0)
    return raw_entry, encoded_payload, {
        "target_path": NESTED.safe_internal_name(target_path),
        "archive_style_name": styled_name,
        "size": len(payload),
        "sha256": sha256_bytes(payload),
        "relative_data_offset": relative_offset,
        "entry_key_sha256": sha256_bytes(raw_key),
        "effective_key_sha256": sha256_bytes(effective_key),
        "entry_flags": 0,
        "entry_extra": 0,
    }


def copy_region(source: Path, source_offset: int, size: int, output_handle: Any) -> None:
    remaining = size
    with source.open("rb") as handle:
        handle.seek(source_offset)
        while remaining:
            block = handle.read(min(COPY_BLOCK_SIZE, remaining))
            if not block:
                raise DryPakInsertionError(f"truncated baseline data region: {source}")
            output_handle.write(block)
            remaining -= len(block)


def fsync_file(path: Path) -> None:
    with path.open("rb") as handle:
        os.fsync(handle.fileno())


def compare_existing_entries(baseline: NESTED.PakIndex, candidate: NESTED.PakIndex) -> list[dict[str, Any]]:
    if len(candidate.entries) != len(baseline.entries) + len(ADDED_MEMBERS):
        raise DryPakInsertionError("candidate PAK entry count mismatch")
    rows: list[dict[str, Any]] = []
    for original, rebuilt in zip(baseline.entries, candidate.entries[:len(baseline.entries)]):
        table_growth = (len(candidate.entries) - len(baseline.entries)) * candidate.entry_size
        checks = {
            "name_identical": original.name == rebuilt.name,
            "size_identical": original.size == rebuilt.size,
            "key_identical": original.key == rebuilt.key,
            "relative_offset_identical": original.data_offset == rebuilt.data_offset,
            "absolute_offset_shift_matches_table_growth": rebuilt.absolute_offset == original.absolute_offset + table_growth,
            "encryption_identical": original.encrypted == rebuilt.encrypted,
        }
        if not all(checks.values()):
            raise DryPakInsertionError(f"existing PAK entry metadata changed at index {original.index}: {checks}")
        rows.append({"entry_index": original.index, "entry_name": original.name, **checks, "validation_status": "passed"})
    return rows


def run_gust_list(gust_pak: Path, candidate: Path, log_path: Path, timeout: int) -> dict[str, Any]:
    if not gust_pak.is_file() or not os.access(gust_pak, os.X_OK):
        raise DryPakInsertionError(f"gust_pak is not executable: {gust_pak}")
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("wb") as log:
        try:
            result = subprocess.run(
                [str(gust_pak), "-l", str(candidate)],
                stdin=subprocess.DEVNULL,
                stdout=log,
                stderr=subprocess.STDOUT,
                timeout=timeout,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise DryPakInsertionError(f"gust_pak listing timed out after {timeout}s") from exc
    text = log_path.read_text(encoding="utf-8", errors="replace")
    normalized = text.replace("\\", "/").casefold()
    found = {
        item["target_path"]: item["target_path"].casefold() in normalized
        for item in ADDED_MEMBERS
    }
    if result.returncode != 0 or not all(found.values()):
        tail = "\n".join(text.splitlines()[-20:])
        raise DryPakInsertionError(
            f"gust_pak list validation failed (exit {result.returncode}, found={found})\n{tail}"
        )
    return {
        "returncode": result.returncode,
        "log_size": log_path.stat().st_size,
        "log_sha256": sha256_file(log_path),
        "added_members_found": found,
        "detected_format_line": next((line for line in text.splitlines() if line.startswith("Detected ")), ""),
        "master_key_line": next((line for line in text.splitlines() if line.startswith("Using ")), ""),
    }


def load_transfer_identity(report_root: Path, temporary: Path) -> dict[str, dict[str, str]]:
    transfer = locate(
        report_root, "transfer_probe_evidence",
        "BR_quartet_legacy_dlc_transfer_probe_evidence.tar.zst", temporary,
    )
    summary_path = transfer / "SUMMARY.json"
    if not summary_path.is_file():
        raise DryPakInsertionError("missing transfer-probe SUMMARY.json")
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    if summary.get("tool_version") != "0.0.12" or summary.get("status") != "dry_local_workspace_built_and_wet_control_schema_ranges_located":
        raise DryPakInsertionError("transfer-probe report is not the validated 0.0.12 result")
    policy = summary.get("policy", {})
    required_false = ("game_modified", "profile_build_allowed", "profile_built", "profiles_activated", "target_pak_repacked")
    if any(policy.get(key) is not False for key in required_false):
        raise DryPakInsertionError("transfer-probe prerequisite violates no-write/profile policy")
    rows = read_tsv(transfer / "DLC_BKN_DRY_TRANSFER_WORKSPACE.tsv")
    identities: dict[str, dict[str, str]] = {}
    for row in rows:
        role = row.get("payload_role", "")
        if role in {"dry_parent_source_exact", "dry_external_texture_source_exact"}:
            identities[role] = row
    if set(identities) != {"dry_parent_source_exact", "dry_external_texture_source_exact"}:
        raise DryPakInsertionError("transfer workspace lacks exact dry parent/G1T identities")
    if summary.get("dry_parent_decoded_roundtrip_identical") is not True:
        raise DryPakInsertionError("dry parent decoded round-trip prerequisite failed")
    return identities


def audit(
    project_root: Path,
    quartet_root: Path,
    gust_pak: Path,
    output_root: Path,
    *,
    timeout: int = 600,
) -> tuple[Path, dict[str, Any]]:
    project_root = project_root.resolve()
    quartet_root = quartet_root.resolve()
    output_root = output_root.resolve()
    report_parent = project_root / ".local/reports/quartet_legacy_dlc"
    build_root = (project_root / BUILD_RELATIVE).resolve()
    transfer_build = (project_root / TRANSFER_BUILD_RELATIVE).resolve()
    baseline_pak = (quartet_root / TARGET_ARCHIVE_RELATIVE).resolve()
    if not baseline_pak.is_file():
        raise DryPakInsertionError(f"Quartet target PAK not found: {baseline_pak}")
    if not str(build_root).startswith(str((project_root / ".local/build").resolve()) + os.sep):
        raise DryPakInsertionError("unsafe local build root")

    print("[stage28] validating transfer-probe prerequisite", flush=True)
    with tempfile.TemporaryDirectory(prefix="br_dlc_dry_pak_prereq_") as temporary_name:
        identities = load_transfer_identity(report_parent, Path(temporary_name))

    payloads: list[dict[str, Any]] = []
    role_to_prereq = {
        "dry_parent": identities["dry_parent_source_exact"],
        "dry_external_texture": identities["dry_external_texture_source_exact"],
    }
    for spec in ADDED_MEMBERS:
        source = transfer_build / spec["source_relative"]
        prerequisite = role_to_prereq[spec["role"]]
        if not source.is_file():
            raise DryPakInsertionError(f"missing local stage-25 source payload: {source}")
        size = source.stat().st_size
        sha = sha256_file(source)
        if size != int(prerequisite["size"]) or sha != prerequisite["sha256"]:
            raise DryPakInsertionError(f"local stage-25 source identity mismatch: {source}")
        payloads.append({**spec, "source": source, "size": size, "sha256": sha, "data": source.read_bytes()})

    print("[stage28] indexing installed Quartet PACK10_02 read-only", flush=True)
    baseline_sha_before = sha256_file(baseline_pak)
    baseline_size = baseline_pak.stat().st_size
    baseline_stat = baseline_pak.stat()
    baseline_index = NESTED.index_pak(baseline_pak)
    layout = read_raw_layout(baseline_pak, baseline_index)
    for item in payloads:
        matches = baseline_index.by_name.get(NESTED.safe_internal_name(item["target_path"]).casefold(), [])
        if matches:
            raise DryPakInsertionError(f"target PAK already contains dry BKN member: {item['target_path']}")

    output_size = baseline_size + len(payloads) * layout.entry_struct.size + sum(item["size"] for item in payloads)
    free = shutil.disk_usage(build_root.parent if build_root.parent.exists() else project_root).free
    if free < output_size + FREE_SPACE_MARGIN:
        raise DryPakInsertionError(
            f"insufficient free space for local PAK candidate: need at least {output_size + FREE_SPACE_MARGIN}, have {free}"
        )

    clean_dir(build_root)
    candidate_dir = build_root / "candidate"
    metadata_dir = build_root / "metadata"
    candidate_dir.mkdir(parents=True)
    metadata_dir.mkdir(parents=True)
    candidate = candidate_dir / "PACK10_02.PAK"
    temp_candidate = candidate_dir / ".PACK10_02.PAK.tmp"
    master_key = master_key_bytes(baseline_index.master_key_label)
    added_raw_entries: list[bytes] = []
    added_encoded_payloads: list[bytes] = []
    added_metadata: list[dict[str, Any]] = []
    relative_offset = layout.raw_data_size
    for item in payloads:
        raw_entry, encoded_payload, metadata = build_raw_added_entry(
            target_path=item["target_path"], payload=item["data"], relative_offset=relative_offset,
            layout=layout, master_key=master_key,
        )
        added_raw_entries.append(raw_entry)
        added_encoded_payloads.append(encoded_payload)
        added_metadata.append({**metadata, "role": item["role"], "source_size": item["size"], "source_sha256": item["sha256"]})
        relative_offset += len(encoded_payload)

    print(f"[stage28] building local copy-through candidate ({output_size} bytes)", flush=True)
    new_header = NESTED.PAK_HEADER.pack(layout.version, layout.file_count + len(payloads), layout.header_size, layout.flags)
    try:
        with temp_candidate.open("wb") as out:
            out.write(new_header)
            out.write(layout.raw_table)
            for raw_entry in added_raw_entries:
                out.write(raw_entry)
            copy_region(baseline_pak, baseline_index.file_data_offset, layout.raw_data_size, out)
            for encoded_payload in added_encoded_payloads:
                out.write(encoded_payload)
            out.flush()
            os.fsync(out.fileno())
        if temp_candidate.stat().st_size != output_size:
            raise DryPakInsertionError(
                f"candidate size mismatch: {temp_candidate.stat().st_size} != {output_size}"
            )
        os.replace(temp_candidate, candidate)
        fsync_file(candidate)
    finally:
        if temp_candidate.exists():
            temp_candidate.unlink()

    print("[stage28] validating local candidate with internal parser", flush=True)
    candidate_index = NESTED.index_pak(candidate)
    existing_entry_rows = compare_existing_entries(baseline_index, candidate_index)
    candidate_header_size = NESTED.PAK_HEADER.size + candidate_index.entry_size * len(candidate_index.entries)
    baseline_region_sha = sha256_region(baseline_pak, baseline_index.file_data_offset, layout.raw_data_size)
    candidate_region_sha = sha256_region(candidate, candidate_header_size, layout.raw_data_size)
    if baseline_region_sha != candidate_region_sha:
        raise DryPakInsertionError("existing encrypted PAK data region changed in candidate")
    with candidate.open("rb") as handle:
        handle.seek(NESTED.PAK_HEADER.size)
        candidate_existing_table = handle.read(len(layout.raw_table))
    if candidate_existing_table != layout.raw_table:
        raise DryPakInsertionError("existing PAK table bytes changed in candidate")

    inserted_rows: list[dict[str, Any]] = []
    for item in added_metadata:
        decoded, entry = NESTED.read_pak_member(candidate_index, item["target_path"])
        actual_sha = sha256_bytes(decoded)
        passed = len(decoded) == item["source_size"] and actual_sha == item["source_sha256"]
        if not passed:
            raise DryPakInsertionError(f"inserted member verification failed: {item['target_path']}")
        inserted_rows.append({
            **item,
            "candidate_entry_index": entry.index,
            "candidate_decoded_size": len(decoded),
            "candidate_decoded_sha256": actual_sha,
            "validation_status": "passed",
            "raw_payload_exported_in_report": False,
        })

    print("[stage28] validating local candidate with gust_pak -l", flush=True)
    gust_result = run_gust_list(gust_pak, candidate, metadata_dir / "gust_pak_list.log", timeout)

    baseline_sha_after = sha256_file(baseline_pak)
    baseline_stat_after = baseline_pak.stat()
    game_unchanged = (
        baseline_sha_before == baseline_sha_after
        and baseline_size == baseline_stat_after.st_size
        and baseline_stat.st_mtime_ns == baseline_stat_after.st_mtime_ns
    )
    if not game_unchanged:
        raise DryPakInsertionError("installed Quartet PACK10_02 changed during local insertion test")

    candidate_sha = sha256_file(candidate)
    marker = {
        "type": "br_quartet_legacy_dlc_local_dry_pak_insertion_test",
        "format_version": FORMAT_VERSION,
        "tool_version": TOOL_VERSION,
        "content_id": "costume_pc00_bkn",
        "baseline_archive": str(TARGET_ARCHIVE_RELATIVE).replace("\\", "/"),
        "baseline_size": baseline_size,
        "baseline_sha256": baseline_sha_before,
        "candidate_relative_path": candidate.relative_to(project_root).as_posix(),
        "candidate_size": candidate.stat().st_size,
        "candidate_sha256": candidate_sha,
        "format_name": candidate_index.format_name,
        "master_key_label": candidate_index.master_key_label,
        "existing_entry_count": len(baseline_index.entries),
        "candidate_entry_count": len(candidate_index.entries),
        "added_members": inserted_rows,
        "existing_table_prefix_identical": True,
        "existing_encrypted_data_region_identical": True,
        "gust_pak_list_validation": gust_result,
        "installed_archive_unchanged": True,
        "warning": "Local asset-only PAK candidate. Do not install: UI, unlock/availability, runtime and wet-variant dependencies remain unresolved.",
    }
    write_json(metadata_dir / "PAK_INSERTION_TEST.json", marker)

    clean_dir(output_root)
    archive_rows = [{
        "content_id": "costume_pc00_bkn",
        "baseline_archive": str(TARGET_ARCHIVE_RELATIVE).replace("\\", "/"),
        "baseline_size": baseline_size,
        "baseline_sha256_before": baseline_sha_before,
        "baseline_sha256_after": baseline_sha_after,
        "baseline_format": baseline_index.format_name,
        "baseline_master_key": baseline_index.master_key_label,
        "baseline_entry_count": len(baseline_index.entries),
        "candidate_entry_count": len(candidate_index.entries),
        "candidate_size": candidate.stat().st_size,
        "candidate_sha256": candidate_sha,
        "candidate_local_path": candidate.relative_to(project_root).as_posix(),
        "installed_archive_unchanged": game_unchanged,
        "candidate_installed": False,
        "profile_registered": False,
        "runtime_validated": False,
    }]
    write_tsv(output_root / "DLC_DRY_PAK_INSERTION_ARCHIVE.tsv", list(archive_rows[0]), archive_rows)
    write_tsv(output_root / "DLC_DRY_PAK_INSERTED_MEMBERS.tsv", [
        "role", "target_path", "archive_style_name", "source_size", "source_sha256",
        "candidate_entry_index", "candidate_decoded_size", "candidate_decoded_sha256",
        "relative_data_offset", "entry_key_sha256", "effective_key_sha256",
        "validation_status", "raw_payload_exported_in_report",
    ], inserted_rows)
    write_tsv(output_root / "DLC_DRY_PAK_BASELINE_PRESERVATION.tsv", [
        "baseline_entry_count", "validated_existing_entries", "existing_table_prefix_identical",
        "existing_data_region_size", "baseline_data_region_sha256", "candidate_data_region_sha256",
        "existing_data_region_identical", "absolute_offsets_shifted_only_by_table_growth",
        "raw_existing_payloads_reencoded", "validation_status",
    ], [{
        "baseline_entry_count": len(baseline_index.entries),
        "validated_existing_entries": len(existing_entry_rows),
        "existing_table_prefix_identical": True,
        "existing_data_region_size": layout.raw_data_size,
        "baseline_data_region_sha256": baseline_region_sha,
        "candidate_data_region_sha256": candidate_region_sha,
        "existing_data_region_identical": baseline_region_sha == candidate_region_sha,
        "absolute_offsets_shifted_only_by_table_growth": True,
        "raw_existing_payloads_reencoded": False,
        "validation_status": "passed",
    }])
    write_tsv(output_root / "DLC_DRY_PAK_LAYOUT_VALIDATION.tsv", [
        "baseline_format", "candidate_format", "baseline_master_key", "candidate_master_key",
        "entry_size", "old_file_count", "new_file_count", "header_flags",
        "archive_root_prefix_preserved", "path_separator_preserved", "validation_status",
    ], [{
        "baseline_format": baseline_index.format_name,
        "candidate_format": candidate_index.format_name,
        "baseline_master_key": baseline_index.master_key_label,
        "candidate_master_key": candidate_index.master_key_label,
        "entry_size": layout.entry_struct.size,
        "old_file_count": len(baseline_index.entries),
        "new_file_count": len(candidate_index.entries),
        "header_flags": layout.flags,
        "archive_root_prefix_preserved": bool(layout.archive_root_prefix),
        "path_separator_preserved": layout.path_separator,
        "validation_status": "passed",
    }])
    write_tsv(output_root / "DLC_DRY_PAK_GUST_LIST_VALIDATION.tsv", [
        "gust_pak_sha256", "returncode", "log_size", "log_sha256", "detected_format_line",
        "master_key_line", "added_members_found", "validation_status",
    ], [{
        "gust_pak_sha256": sha256_file(gust_pak),
        **gust_result,
        "validation_status": "passed",
    }])
    gaps = [
        {
            "content_id": "costume_pc00_bkn",
            "dependency_type": "owner_ui_icon_or_thumbnail",
            "status": "unresolved",
            "next_evidence_needed": "resolve exact BKN owner-specific UI icon or shared-atlas index",
            "blocks_installation": True,
        },
        {
            "content_id": "costume_pc00_bkn",
            "dependency_type": "unlock_or_availability_chain",
            "status": "unresolved",
            "next_evidence_needed": "prove exact Quartet costume availability/entitlement path for PC00_DLC_BKN",
            "blocks_installation": True,
        },
        {
            "content_id": "costume_pc00_bkn",
            "dependency_type": "wet_variant_conversion",
            "status": "blocked",
            "next_evidence_needed": "complete wet G1M base-envelope, SWG insertion and exact G1M-to-G1T binding evidence",
            "blocks_installation": True,
        },
        {
            "content_id": "costume_pc00_bkn",
            "dependency_type": "runtime_validation",
            "status": "not_started",
            "next_evidence_needed": "only after asset plus table/unlock composition is checksum-gated and explicitly approved",
            "blocks_installation": True,
        },
    ]
    write_tsv(output_root / "DLC_DRY_PAK_INSERTION_GAPS.tsv", list(gaps[0]), gaps)

    summary = {
        "type": "br_quartet_legacy_dlc_dry_pak_insertion_summary",
        "format_version": FORMAT_VERSION,
        "tool_version": TOOL_VERSION,
        "status": "local_asset_only_pack10_02_candidate_built_not_installed",
        "content_id": "costume_pc00_bkn",
        "baseline_archive": str(TARGET_ARCHIVE_RELATIVE).replace("\\", "/"),
        "baseline_format": baseline_index.format_name,
        "baseline_master_key": baseline_index.master_key_label,
        "baseline_size": baseline_size,
        "baseline_sha256": baseline_sha_before,
        "baseline_entry_count": len(baseline_index.entries),
        "candidate_size": candidate.stat().st_size,
        "candidate_sha256": candidate_sha,
        "candidate_entry_count": len(candidate_index.entries),
        "added_member_count": len(inserted_rows),
        "existing_entry_metadata_validated": len(existing_entry_rows),
        "existing_table_prefix_identical": True,
        "existing_encrypted_data_region_identical": True,
        "gust_pak_list_passed": True,
        "unresolved_installation_blockers": len(gaps),
        "local_build_root": build_root.relative_to(project_root).as_posix(),
        "findings": [
            "the current installed PACK10_02 was used read-only as the baseline",
            "existing entry-table bytes and the complete encrypted data region were copied through unchanged",
            "only the dry BKN parent and dry external G1T were appended as new encrypted members",
            "the candidate was parsed internally and listed successfully by the authoritative gust_pak binary",
            "the installed PACK10_02 hash, size and mtime remained unchanged",
            "the candidate remains asset-only and is blocked from installation by UI, unlock, wet-variant and runtime dependencies",
        ],
        "next_action": "audit exact PC00_DLC_BKN availability/unlock and UI ownership, then compose them with this local asset candidate; do not install the asset-only PAK",
        "policy": {
            "game_modified": False,
            "git_modified": False,
            "candidate_installed": False,
            "profile_registered": False,
            "profile_build_allowed": False,
            "profiles_activated": False,
            "runtime_validated": False,
            "target_pak_repacked_locally": True,
            "existing_pak_payloads_reencoded": False,
            "raw_assets_in_local_build": True,
            "raw_assets_exported_in_report": False,
            "raw_assets_in_update": False,
            "text_seed_unchanged": True,
            "wet_variant_included": False,
        },
    }
    write_json(output_root / "SUMMARY.json", summary)
    manifest_rows = report_manifest(output_root)
    write_json(output_root / "REPORT_MANIFEST.json", {
        "type": "br_report_manifest", "format_version": 1, "files": manifest_rows,
    })
    archive = report_parent / REPORT_ARCHIVE_NAME
    make_archive(output_root, archive)
    print(f"[stage28] local candidate: {candidate}", flush=True)
    print(f"[stage28] report: {archive}", flush=True)
    return archive, summary


def validate_report(report_root: Path) -> dict[str, Any]:
    report_root = report_root.resolve()
    required = (
        "DLC_DRY_PAK_INSERTION_ARCHIVE.tsv",
        "DLC_DRY_PAK_INSERTED_MEMBERS.tsv",
        "DLC_DRY_PAK_BASELINE_PRESERVATION.tsv",
        "DLC_DRY_PAK_LAYOUT_VALIDATION.tsv",
        "DLC_DRY_PAK_GUST_LIST_VALIDATION.tsv",
        "DLC_DRY_PAK_INSERTION_GAPS.tsv",
        "SUMMARY.json",
        "REPORT_MANIFEST.json",
    )
    for name in required:
        if not (report_root / name).is_file():
            raise DryPakInsertionError(f"missing report file: {name}")
    summary = json.loads((report_root / "SUMMARY.json").read_text(encoding="utf-8"))
    if summary.get("type") != "br_quartet_legacy_dlc_dry_pak_insertion_summary" or summary.get("tool_version") != TOOL_VERSION:
        raise DryPakInsertionError("invalid dry-PAK insertion summary")
    if summary.get("status") != "local_asset_only_pack10_02_candidate_built_not_installed":
        raise DryPakInsertionError("unexpected dry-PAK insertion status")
    if summary.get("added_member_count") != 2:
        raise DryPakInsertionError("dry-PAK insertion report must contain exactly two added members")
    if not all(summary.get(key) is True for key in (
        "existing_table_prefix_identical", "existing_encrypted_data_region_identical", "gust_pak_list_passed",
    )):
        raise DryPakInsertionError("dry-PAK insertion validation gates did not all pass")
    policy = summary.get("policy", {})
    false_keys = (
        "game_modified", "git_modified", "candidate_installed", "profile_registered",
        "profile_build_allowed", "profiles_activated", "runtime_validated",
        "existing_pak_payloads_reencoded", "raw_assets_exported_in_report", "raw_assets_in_update",
        "wet_variant_included",
    )
    if any(policy.get(key) is not False for key in false_keys):
        raise DryPakInsertionError("dry-PAK insertion report violates fail-closed policy")
    if policy.get("target_pak_repacked_locally") is not True or policy.get("raw_assets_in_local_build") is not True:
        raise DryPakInsertionError("dry-PAK insertion report lacks local-build declarations")
    inserted = read_tsv(report_root / "DLC_DRY_PAK_INSERTED_MEMBERS.tsv")
    if len(inserted) != 2 or {row.get("validation_status") for row in inserted} != {"passed"}:
        raise DryPakInsertionError("inserted-member validation rows are not exactly two passed rows")
    expected_paths = {item["target_path"] for item in ADDED_MEMBERS}
    if {row.get("target_path") for row in inserted} != expected_paths:
        raise DryPakInsertionError("inserted-member target paths differ from the fixed dry BKN scope")
    archive_rows = read_tsv(report_root / "DLC_DRY_PAK_INSERTION_ARCHIVE.tsv")
    if len(archive_rows) != 1 or archive_rows[0].get("installed_archive_unchanged") != "true":
        raise DryPakInsertionError("archive validation does not prove the installed PAK remained unchanged")
    preservation = read_tsv(report_root / "DLC_DRY_PAK_BASELINE_PRESERVATION.tsv")
    if len(preservation) != 1 or preservation[0].get("validation_status") != "passed":
        raise DryPakInsertionError("baseline-preservation validation missing or failed")
    if preservation[0].get("raw_existing_payloads_reencoded") != "false":
        raise DryPakInsertionError("existing payloads must not be reencoded")
    gaps = read_tsv(report_root / "DLC_DRY_PAK_INSERTION_GAPS.tsv")
    if len(gaps) < 4 or any(row.get("blocks_installation") != "true" for row in gaps):
        raise DryPakInsertionError("installation blockers are missing from dry-PAK evidence")
    manifest = json.loads((report_root / "REPORT_MANIFEST.json").read_text(encoding="utf-8"))
    files = manifest.get("files", [])
    for row in files:
        path = report_root / row["path"]
        if not path.is_file() or path.stat().st_size != row["size"] or sha256_file(path) != row["sha256"]:
            raise DryPakInsertionError(f"report manifest mismatch: {row.get('path')}")
        if {suffix.casefold() for suffix in path.suffixes} & FORBIDDEN_REPORT_SUFFIXES:
            raise DryPakInsertionError(f"raw asset in report: {path}")
    return summary


def main() -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    audit_parser = sub.add_parser("audit")
    audit_parser.add_argument("--project-root", required=True)
    audit_parser.add_argument("--quartet-root", required=True)
    audit_parser.add_argument("--gust-pak", required=True)
    audit_parser.add_argument("--output-root")
    audit_parser.add_argument("--timeout", type=int, default=600)
    validate_parser = sub.add_parser("validate-report")
    validate_parser.add_argument("--report-root", required=True)
    bundle_parser = sub.add_parser("bundle-report")
    bundle_parser.add_argument("--report-root", required=True)
    bundle_parser.add_argument("--output", required=True)
    args = parser.parse_args()
    try:
        if args.command == "audit":
            project = Path(args.project_root)
            output = Path(args.output_root) if args.output_root else project / ".local/reports/quartet_legacy_dlc" / REPORT_DIR_NAME
            audit(project, Path(args.quartet_root), Path(args.gust_pak), output, timeout=args.timeout)
        elif args.command == "validate-report":
            validate_report(Path(args.report_root))
            print("Dry PACK10_02 insertion evidence validated.")
        else:
            report_root = Path(args.report_root)
            validate_report(report_root)
            make_archive(report_root, Path(args.output))
    except (DryPakInsertionError, NESTED.NestedContainerError, OSError, subprocess.SubprocessError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
