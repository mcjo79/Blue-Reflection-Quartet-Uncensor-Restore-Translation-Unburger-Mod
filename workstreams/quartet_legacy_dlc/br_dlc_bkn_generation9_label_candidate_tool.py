#!/usr/bin/env python3
"""Build a local generation-9 PACK12 candidate with append-only BKN labels.

PACK10_02 from generation 8 is reused byte-for-byte. The generation-8 PACK12
candidate is rebuilt locally with exactly four locale str_costume.xml members
changed. Existing rows are preserved and String_No 393339-393346 are appended.
No installed game file, save, transaction, profile, core source, Translation
source or Restoration source is modified.
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
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT_DEFAULT = SCRIPT_DIR.parent.parent
for import_path in (SCRIPT_DIR, PROJECT_ROOT_DEFAULT / "Blue_Reflection_Text_Tool"):
    if str(import_path) not in sys.path:
        sys.path.insert(0, str(import_path))

import br_dlc_nested_container_tool as NESTED  # noqa: E402
import br_dlc_dry_pak_insertion_tool as DRY  # noqa: E402

TOOL_VERSION = "0.0.63"
FORMAT_VERSION = 1
ACCEPTANCE_RELATIVE = Path("workstreams/quartet_legacy_dlc/DLC_BKN_SYNTHETIC_LABEL_SLOT_RETURN_ACCEPTANCE.json")
BUILD_RELATIVE = Path(".local/build/quartet_legacy_dlc/visibility_probe/bkn_dry_generation9_append_only_labels")
REPORT_DIR_NAME = "bkn_dry_generation9_append_only_label_candidate_evidence"
TARGET_PACK10 = "Data/PACK10_02.PAK"
TARGET_PACK12 = "Data/PACK12.PAK"
COPY_BLOCK_SIZE = 8 * 1024 * 1024
FREE_SPACE_MARGIN = 128 * 1024 * 1024
FORBIDDEN_REPORT_SUFFIXES = {".pak", ".xml", ".ebm", ".ebd", ".g1m", ".g1t", ".bin", ".dll", ".exe"}


class Generation9CandidateError(RuntimeError):
    pass


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(COPY_BLOCK_SIZE), b""):
            digest.update(block)
    return digest.hexdigest()


def scalar(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (list, tuple, set)):
        return json.dumps(list(value), ensure_ascii=False, separators=(",", ":"))
    if isinstance(value, dict):
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return str(value)


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")


def write_tsv(path: Path, fields: Sequence[str], rows: Iterable[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(fields), delimiter="\t", lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow({field: scalar(row.get(field, "")) for field in fields})


def read_tsv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def clean_dir(path: Path) -> None:
    if path.exists():
        shutil.rmtree(path)
    path.mkdir(parents=True, exist_ok=True)


def require_identity(path: Path, *, size: int, sha256: str, label: str) -> dict[str, Any]:
    if not path.is_file() or path.is_symlink():
        raise Generation9CandidateError(f"{label} is missing or unsafe: {path}")
    actual_size = path.stat().st_size
    actual_sha = sha256_file(path)
    if actual_size != size or actual_sha != sha256:
        raise Generation9CandidateError(
            f"{label} identity mismatch: size {actual_size}/{size}, sha256 {actual_sha}/{sha256}"
        )
    return {"path": path, "size": actual_size, "sha256": actual_sha, "mtime_ns": path.stat().st_mtime_ns}


def resolve_under(root: Path, relative: str, label: str) -> Path:
    relative_path = Path(relative)
    if relative_path.is_absolute() or ".." in relative_path.parts:
        raise Generation9CandidateError(f"unsafe {label} path: {relative}")
    root_real = root.resolve(strict=True)
    candidate = (root_real / relative_path).resolve(strict=False)
    try:
        candidate.relative_to(root_real)
    except ValueError as exc:
        raise Generation9CandidateError(f"{label} escapes root: {relative}") from exc
    return candidate


def load_acceptance(project_root: Path) -> dict[str, Any]:
    path = project_root / ACCEPTANCE_RELATIVE
    if not path.is_file() or path.is_symlink():
        raise Generation9CandidateError(f"missing acceptance: {path}")
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("type") != "br_quartet_legacy_dlc_bkn_synthetic_label_slot_return_acceptance":
        raise Generation9CandidateError("unexpected acceptance type")
    if data.get("status") != "accepted_for_generation9_append_only_synthetic_label_candidate_build":
        raise Generation9CandidateError("generation 9 candidate build is not accepted")
    authorization = data.get("authorization", {})
    if authorization.get("local_candidate_build") is not True:
        raise Generation9CandidateError("local candidate build is not authorized")
    forbidden = (
        "prepare", "commit", "installation", "profile_registration", "runtime_validation",
        "existing_costume_replacement", "global_show_all", "pc08", "wet_bkn",
        "translation_workstream_modification", "restoration_modification", "core_modification", "git_modification",
    )
    if any(authorization.get(key) is not False for key in forbidden):
        raise Generation9CandidateError("acceptance does not fail closed")
    return data


def report_manifest(root: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for path in sorted(root.iterdir(), key=lambda item: item.name.casefold()):
        if not path.is_file() or path.name == "REPORT_MANIFEST.json":
            continue
        if {suffix.casefold() for suffix in path.suffixes} & FORBIDDEN_REPORT_SUFFIXES:
            raise Generation9CandidateError(f"raw asset-like file in report: {path}")
        rows.append({"path": path.name, "size": path.stat().st_size, "sha256": sha256_file(path)})
    return rows


def make_archive(source: Path, output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(output.name + ".tmp")
    temporary.unlink(missing_ok=True)
    result = subprocess.run(
        ["tar", "--zstd", "--sort=name", "--mtime=@0", "--owner=0", "--group=0", "--numeric-owner",
         "-cf", str(temporary), "-C", str(source.parent), source.name],
        text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False,
    )
    if result.returncode:
        raise Generation9CandidateError(f"cannot create report archive: {result.stderr.strip()}")
    os.replace(temporary, output)


def decode_xml(raw: bytes) -> tuple[str, str, bool]:
    bom = raw.startswith(b"\xef\xbb\xbf")
    try:
        text = raw.decode("utf-8-sig" if bom else "utf-8")
    except UnicodeDecodeError as exc:
        raise Generation9CandidateError("str_costume.xml is not UTF-8") from exc
    if "\r\n" not in text:
        raise Generation9CandidateError("str_costume.xml does not preserve expected CRLF layout")
    return text, "utf-8", bom


def encode_xml(text: str, encoding: str, bom: bool) -> bytes:
    raw = text.encode(encoding)
    return (b"\xef\xbb\xbf" + raw) if bom else raw


def parse_string_rows(raw: bytes) -> list[tuple[int, str]]:
    text, _, _ = decode_xml(raw)
    try:
        root = ET.fromstring(text)
    except ET.ParseError as exc:
        raise Generation9CandidateError(f"invalid str_costume XML: {exc}") from exc
    rows: list[tuple[int, str]] = []
    for element in root.findall(".//str"):
        try:
            number = int(element.attrib["String_No"])
        except (KeyError, ValueError) as exc:
            raise Generation9CandidateError("invalid str_costume row") from exc
        rows.append((number, element.attrib.get("Text", "")))
    return rows


def patch_str_costume(raw: bytes, *, label: str, start: int, end: int) -> tuple[bytes, list[dict[str, Any]]]:
    rows_before = parse_string_rows(raw)
    numbers_before = [number for number, _ in rows_before]
    if not rows_before or max(numbers_before) != start - 1:
        raise Generation9CandidateError(
            f"unexpected str_costume tail: max={max(numbers_before) if numbers_before else None}, expected={start - 1}"
        )
    proposed = list(range(start, end + 1))
    if set(proposed) & set(numbers_before):
        raise Generation9CandidateError("append range collides with existing String_No values")
    protected = {number: text for number, text in rows_before if 393335 <= number <= 393338}
    if set(protected) != {393335, 393336, 393337, 393338}:
        raise Generation9CandidateError("protected Quartet-only rows 393335-393338 are incomplete")

    text, encoding, bom = decode_xml(raw)
    marker = "</Root>"
    position = text.find(marker)
    if position < 0 or text.find(marker, position + 1) >= 0:
        raise Generation9CandidateError("expected exactly one </Root> marker")
    indent = "\t"
    lines = "".join(
        f'{indent}<str Text="{label}" String_No="{number}"/>\r\n'
        for number in proposed
    )
    candidate_text = text[:position] + lines + text[position:]
    candidate = encode_xml(candidate_text, encoding, bom)
    rows_after = parse_string_rows(candidate)
    if rows_after[:len(rows_before)] != rows_before:
        raise Generation9CandidateError("existing str_costume rows changed or were reordered")
    if rows_after[len(rows_before):] != [(number, label) for number in proposed]:
        raise Generation9CandidateError("appended str_costume rows mismatch")
    protected_after = {number: text for number, text in rows_after if 393335 <= number <= 393338}
    if protected_after != protected:
        raise Generation9CandidateError("protected Quartet-only rows changed")
    details = [
        {
            "string_no": number,
            "label": label,
            "operation": "append_new_record",
            "existing_record_replaced": False,
        }
        for number in proposed
    ]
    return candidate, details



def pack_raw_entry(
    raw_name: bytes, size: int, raw_key: bytes, extra: int, data_offset: int, flags: int,
    *, entry_struct: struct.Struct, a22: bool,
) -> bytes:
    if a22:
        return entry_struct.pack(raw_name, size, raw_key, extra, data_offset, flags)
    return entry_struct.pack(raw_name, size, raw_key, data_offset, flags)


def read_entry_plain(index: NESTED.PakIndex, entry: NESTED.PakEntry) -> bytes:
    with index.path.open("rb") as handle:
        handle.seek(entry.absolute_offset)
        raw = handle.read(entry.size)
    if len(raw) != entry.size:
        raise Generation9CandidateError(f"truncated entry {entry.index}: {entry.name}")
    return NESTED.xor_bytes(raw, entry.key) if entry.encrypted else raw

def copy_region(source: Path, offset: int, size: int, output: Any) -> None:
    if size < 0:
        raise Generation9CandidateError("negative copy size")
    remaining = size
    with source.open("rb") as handle:
        handle.seek(offset)
        while remaining:
            block = handle.read(min(COPY_BLOCK_SIZE, remaining))
            if not block:
                raise Generation9CandidateError(f"truncated source region: {source}")
            output.write(block)
            remaining -= len(block)


def build_multi_replace_candidate(parent: Path, output: Path, replacements: Mapping[str, bytes]) -> tuple[NESTED.PakIndex, list[dict[str, Any]]]:
    parent_index = NESTED.index_pak(parent)
    layout = DRY.read_raw_layout(parent, parent_index)
    target_by_index: dict[int, bytes] = {}
    target_name_by_index: dict[int, str] = {}
    for requested_name, payload in replacements.items():
        safe = NESTED.safe_internal_name(requested_name).casefold()
        matches = parent_index.by_name.get(safe, [])
        if len(matches) != 1:
            raise Generation9CandidateError(f"expected one {requested_name}, found {len(matches)}")
        target_by_index[matches[0].index] = payload
        target_name_by_index[matches[0].index] = requested_name

    data_size = parent.stat().st_size - parent_index.file_data_offset
    ordered = sorted(parent_index.entries, key=lambda row: (row.data_offset, row.index))
    cursor_old = 0
    cursor_new = 0
    geometry: dict[int, tuple[int, int]] = {}
    for entry in ordered:
        if entry.data_offset < cursor_old:
            raise Generation9CandidateError(f"overlapping PAK member: {entry.name}")
        gap = entry.data_offset - cursor_old
        cursor_new += gap
        new_size = len(target_by_index[entry.index]) if entry.index in target_by_index else entry.size
        geometry[entry.index] = (cursor_new, new_size)
        cursor_new += new_size
        cursor_old = entry.data_offset + entry.size
    if cursor_old > data_size:
        raise Generation9CandidateError("PAK member data exceeds archive")
    tail_size = data_size - cursor_old
    output_data_size = cursor_new + tail_size

    raw_table = bytearray()
    table_rows: list[dict[str, Any]] = []
    for index in range(layout.file_count):
        start = index * layout.entry_struct.size
        raw_entry = layout.raw_table[start:start + layout.entry_struct.size]
        raw_name, old_size, raw_key, extra, old_offset, entry_flags = DRY.raw_entry_parts(
            raw_entry, layout.entry_struct, a22=layout.a22
        )
        indexed = parent_index.entries[index]
        if old_size != indexed.size or old_offset != indexed.data_offset:
            raise Generation9CandidateError(f"raw/indexed mismatch at entry {index}")
        new_offset, new_size = geometry[index]
        raw_table.extend(pack_raw_entry(
            raw_name, new_size, raw_key, extra, new_offset, entry_flags,
            entry_struct=layout.entry_struct, a22=layout.a22,
        ))
        table_rows.append({
            "entry_index": index,
            "entry_name": indexed.name,
            "parent_size": old_size,
            "candidate_size": new_size,
            "parent_relative_offset": old_offset,
            "candidate_relative_offset": new_offset,
            "target_replaced": index in target_by_index,
            "raw_name_preserved": True,
            "raw_key_preserved": True,
            "entry_flags_preserved": True,
            "entry_extra_preserved": True,
        })

    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name("." + output.name + ".tmp")
    temporary.unlink(missing_ok=True)
    with temporary.open("wb") as handle:
        handle.write(NESTED.PAK_HEADER.pack(layout.version, layout.file_count, layout.header_size, layout.flags))
        handle.write(raw_table)
        cursor_old = 0
        for entry in ordered:
            gap = entry.data_offset - cursor_old
            copy_region(parent, parent_index.file_data_offset + cursor_old, gap, handle)
            if entry.index in target_by_index:
                payload = target_by_index[entry.index]
                encoded = NESTED.xor_bytes(payload, entry.key) if entry.encrypted else payload
                handle.write(encoded)
            else:
                copy_region(parent, entry.absolute_offset, entry.size, handle)
            cursor_old = entry.data_offset + entry.size
        copy_region(parent, parent_index.file_data_offset + cursor_old, tail_size, handle)
        handle.flush()
        os.fsync(handle.fileno())
    expected_size = parent_index.file_data_offset + output_data_size
    if temporary.stat().st_size != expected_size:
        raise Generation9CandidateError(f"candidate size mismatch: {temporary.stat().st_size} != {expected_size}")
    os.replace(temporary, output)

    candidate_index = NESTED.index_pak(output)
    if (candidate_index.format_name, candidate_index.master_key_label, len(candidate_index.entries)) != (
        parent_index.format_name, parent_index.master_key_label, len(parent_index.entries)
    ):
        raise Generation9CandidateError("candidate PAK layout identity changed")

    validation_rows: list[dict[str, Any]] = []
    for parent_entry, candidate_entry in zip(parent_index.entries, candidate_index.entries):
        parent_plain = read_entry_plain(parent_index, parent_entry)
        candidate_plain = read_entry_plain(candidate_index, candidate_entry)
        is_target = parent_entry.index in target_by_index
        expected = target_by_index[parent_entry.index] if is_target else parent_plain
        if candidate_plain != expected:
            raise Generation9CandidateError(f"candidate plaintext mismatch: {parent_entry.name}")
        validation_rows.append({
            "entry_index": parent_entry.index,
            "entry_name": parent_entry.name,
            "parent_size": len(parent_plain),
            "candidate_size": len(candidate_plain),
            "parent_sha256": sha256_bytes(parent_plain),
            "candidate_sha256": sha256_bytes(candidate_plain),
            "member_status": "target_replaced_append_only" if is_target else "non_target_identical",
            "validation_status": "passed",
        })
    return candidate_index, validation_rows


def run_gust_list(gust_pak: Path, candidate: Path, required_members: Sequence[str], log_path: Path, timeout: int) -> dict[str, Any]:
    if not gust_pak.is_file() or not os.access(gust_pak, os.X_OK):
        raise Generation9CandidateError(f"gust_pak is not executable: {gust_pak}")
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("wb") as log:
        try:
            result = subprocess.run(
                [str(gust_pak), "-l", str(candidate)], stdin=subprocess.DEVNULL,
                stdout=log, stderr=subprocess.STDOUT, timeout=timeout, check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise Generation9CandidateError(f"gust_pak listing timed out after {timeout}s") from exc
    text = log_path.read_text(encoding="utf-8", errors="replace").replace("\\", "/").casefold()
    missing = [member for member in required_members if member.casefold() not in text]
    if result.returncode != 0 or missing:
        raise Generation9CandidateError(f"gust_pak list validation failed: exit={result.returncode}, missing={missing}")
    return {"returncode": result.returncode, "log_size": log_path.stat().st_size, "log_sha256": sha256_file(log_path), "required_members_found": True}


def audit(project_root: Path, quartet_root: Path, gust_pak: Path, output_root: Path, *, timeout: int = 600) -> tuple[Path, dict[str, Any]]:
    project_root = project_root.resolve(strict=True)
    quartet_root = quartet_root.resolve(strict=True)
    output_root = output_root.resolve()
    acceptance = load_acceptance(project_root)
    active_path = resolve_under(project_root, acceptance["active_generation8"]["relative_path"], "ACTIVE manifest")
    require_identity(active_path, size=active_path.stat().st_size, sha256=acceptance["active_generation8"]["sha256"], label="generation-8 ACTIVE manifest")
    active = json.loads(active_path.read_text(encoding="utf-8"))
    if active.get("generation") != 8 or active.get("members") != acceptance["members"]:
        raise Generation9CandidateError("ACTIVE manifest is not accepted generation 8")

    candidate_meta = {row["target_path"]: row for row in acceptance["generation8_candidates"]}
    pack10_meta = candidate_meta[TARGET_PACK10]
    pack12_meta = candidate_meta[TARGET_PACK12]
    pack10 = resolve_under(project_root, pack10_meta["relative_path"], "generation-8 PACK10 candidate")
    pack12_parent = resolve_under(project_root, pack12_meta["relative_path"], "generation-8 PACK12 candidate")
    pack10_identity = require_identity(pack10, size=int(pack10_meta["size"]), sha256=pack10_meta["sha256"], label="generation-8 PACK10 candidate")
    pack12_parent_identity = require_identity(pack12_parent, size=int(pack12_meta["size"]), sha256=pack12_meta["sha256"], label="generation-8 PACK12 candidate")

    baseline_rows: list[dict[str, Any]] = []
    baseline_snapshots: dict[str, dict[str, Any]] = {}
    for row in acceptance["installed_baselines"]:
        path = resolve_under(quartet_root, row["relative_path"], f"installed baseline {row['target_path']}")
        identity = require_identity(path, size=int(row["size"]), sha256=row["sha256"], label=f"installed baseline {row['target_path']}")
        baseline_snapshots[row["target_path"]] = identity
        baseline_rows.append({
            "target_path": row["target_path"], "actual_size": identity["size"], "actual_sha256": identity["sha256"],
            "expected_size": row["size"], "expected_sha256": row["sha256"], "state": "baseline", "modified_by_stage": False,
        })

    build_root = resolve_under(project_root, BUILD_RELATIVE.as_posix(), "build root")
    if not str(build_root).startswith(str((project_root / ".local/build").resolve()) + os.sep):
        raise Generation9CandidateError("unsafe build root")
    free = shutil.disk_usage(build_root.parent if build_root.parent.exists() else project_root).free
    if free < pack12_parent.stat().st_size + FREE_SPACE_MARGIN:
        raise Generation9CandidateError("insufficient free space for local PACK12 candidate")
    clean_dir(build_root)
    candidate_pack12 = build_root / "candidate/PACK12.PAK"
    member_dir = build_root / "candidate_members"
    metadata_dir = build_root / "metadata"
    member_dir.mkdir(parents=True)
    metadata_dir.mkdir(parents=True)

    parent_index = NESTED.index_pak(pack12_parent)
    replacements: dict[str, bytes] = {}
    append_rows: list[dict[str, Any]] = []
    member_rows: list[dict[str, Any]] = []
    plan = acceptance["append_plan"]
    start, end = int(plan["string_no_start"]), int(plan["string_no_end"])
    for member in plan["target_members"]:
        safe = NESTED.safe_internal_name(member).casefold()
        matches = parent_index.by_name.get(safe, [])
        if len(matches) != 1:
            raise Generation9CandidateError(f"expected one {member}, found {len(matches)}")
        parent_raw = read_entry_plain(parent_index, matches[0])
        candidate_raw, rows = patch_str_costume(parent_raw, label=plan["labels"][member], start=start, end=end)
        replacements[member] = candidate_raw
        output_member = member_dir / member
        output_member.parent.mkdir(parents=True, exist_ok=True)
        output_member.write_bytes(candidate_raw)
        append_rows.extend({"target_member": member, **row} for row in rows)
        member_rows.append({
            "target_member": member,
            "entry_index": matches[0].index,
            "parent_size": len(parent_raw),
            "candidate_size": len(candidate_raw),
            "parent_sha256": sha256_bytes(parent_raw),
            "candidate_sha256": sha256_bytes(candidate_raw),
            "appended_record_count": len(rows),
            "string_no_start": start,
            "string_no_end": end,
            "existing_rows_preserved": True,
            "protected_rows_393335_393338_preserved": True,
            "validation_status": "passed",
        })

    candidate_index, validation_rows = build_multi_replace_candidate(pack12_parent, candidate_pack12, replacements)
    gust_result = run_gust_list(gust_pak, candidate_pack12, list(replacements), metadata_dir / "PACK12_gust_pak_list.log", timeout)

    require_identity(pack10, size=pack10_identity["size"], sha256=pack10_identity["sha256"], label="generation-8 PACK10 candidate after build")
    require_identity(pack12_parent, size=pack12_parent_identity["size"], sha256=pack12_parent_identity["sha256"], label="generation-8 PACK12 parent after build")
    for row in acceptance["installed_baselines"]:
        identity = baseline_snapshots[row["target_path"]]
        path = resolve_under(quartet_root, row["relative_path"], f"installed baseline {row['target_path']} after build")
        current = require_identity(path, size=identity["size"], sha256=identity["sha256"], label=f"installed baseline {row['target_path']} after build")
        if current["mtime_ns"] != identity["mtime_ns"]:
            raise Generation9CandidateError(f"installed baseline mtime changed: {row['target_path']}")

    clean_dir(output_root)
    write_tsv(output_root / "GENERATION9_INSTALLATION_BASELINE_GATES.tsv", list(baseline_rows[0]), baseline_rows)
    write_tsv(output_root / "GENERATION9_STR_COSTUME_MEMBER_PATCHES.tsv", list(member_rows[0]), member_rows)
    write_tsv(output_root / "GENERATION9_APPENDED_LABEL_ROWS.tsv", list(append_rows[0]), append_rows)
    write_tsv(output_root / "GENERATION9_PACK12_ENTRY_VALIDATION.tsv", list(validation_rows[0]), validation_rows)
    write_tsv(output_root / "GENERATION9_GUST_LIST_VALIDATION.tsv", [*gust_result, "validation_status"], [{**gust_result, "validation_status": "passed"}])
    composition_rows = [
        {
            "target_path": TARGET_PACK10,
            "role": "generation8_candidate_reused_byte_identical",
            "candidate_relative_path": pack10.relative_to(project_root).as_posix(),
            "candidate_size": pack10.stat().st_size,
            "candidate_sha256": sha256_file(pack10),
            "changed_members": [],
            "candidate_installed": False,
            "profile_registered": False,
            "runtime_validated": False,
        },
        {
            "target_path": TARGET_PACK12,
            "role": "generation9_append_only_label_candidate",
            "candidate_relative_path": candidate_pack12.relative_to(project_root).as_posix(),
            "candidate_size": candidate_pack12.stat().st_size,
            "candidate_sha256": sha256_file(candidate_pack12),
            "changed_members": list(replacements),
            "candidate_installed": False,
            "profile_registered": False,
            "runtime_validated": False,
        },
    ]
    write_tsv(output_root / "GENERATION9_TWO_ARCHIVE_COMPOSITION.tsv", list(composition_rows[0]), composition_rows)

    summary = {
        "type": "br_quartet_legacy_dlc_bkn_generation9_append_only_label_candidate_summary",
        "format_version": FORMAT_VERSION,
        "tool_version": TOOL_VERSION,
        "status": "generation9_append_only_label_candidate_built_validated_not_installed",
        "generation": 9,
        "parent_generation": 8,
        "members": acceptance["members"],
        "candidate_artifact_count": 2,
        "pack10_reused_byte_identical": True,
        "pack12_parent_unchanged": True,
        "pack12_candidate_relative_path": candidate_pack12.relative_to(project_root).as_posix(),
        "pack12_candidate_size": candidate_pack12.stat().st_size,
        "pack12_candidate_sha256": sha256_file(candidate_pack12),
        "changed_members": list(replacements),
        "appended_records_per_locale": end - start + 1,
        "appended_record_count_total": len(append_rows),
        "string_no_start": start,
        "string_no_end": end,
        "existing_records_replaced": 0,
        "existing_records_reordered": False,
        "protected_quartet_rows_preserved": True,
        "non_target_pack12_entries_validated": sum(row["member_status"] == "non_target_identical" for row in validation_rows),
        "installed_game_archives_unchanged": True,
        "required_next_action": "publish generation 9 through the existing generic manifest adapter and run canonical preview; do not install it",
        "policy": {
            "prepare_called": False,
            "commit_called": False,
            "candidate_installed": False,
            "profile_registered": False,
            "runtime_validated": False,
            "game_modified": False,
            "save_modified": False,
            "core_modified": False,
            "translation_workstream_modified": False,
            "restoration_modified": False,
            "git_modified": False,
            "pc08_included": False,
            "wet_variant_included": False,
            "global_show_all_enabled": False,
            "existing_costume_replaced": False,
        },
    }
    write_json(output_root / "SUMMARY.json", summary)
    write_json(output_root / "REPORT_MANIFEST.json", {"type": "br_report_manifest", "format_version": 1, "files": report_manifest(output_root)})
    archive = output_root.parent / "BR_QUARTET_DLC_BKN_GENERATION9_APPEND_ONLY_LABEL_CANDIDATE.tar.zst"
    make_archive(output_root, archive)
    return archive, summary


def validate_report(report_root: Path) -> dict[str, Any]:
    required = (
        "GENERATION9_INSTALLATION_BASELINE_GATES.tsv",
        "GENERATION9_STR_COSTUME_MEMBER_PATCHES.tsv",
        "GENERATION9_APPENDED_LABEL_ROWS.tsv",
        "GENERATION9_PACK12_ENTRY_VALIDATION.tsv",
        "GENERATION9_GUST_LIST_VALIDATION.tsv",
        "GENERATION9_TWO_ARCHIVE_COMPOSITION.tsv",
        "SUMMARY.json",
        "REPORT_MANIFEST.json",
    )
    for name in required:
        if not (report_root / name).is_file():
            raise Generation9CandidateError(f"missing report file: {name}")
    summary = json.loads((report_root / "SUMMARY.json").read_text(encoding="utf-8"))
    if summary.get("type") != "br_quartet_legacy_dlc_bkn_generation9_append_only_label_candidate_summary" or summary.get("tool_version") != TOOL_VERSION:
        raise Generation9CandidateError("invalid generation9 summary")
    if summary.get("status") != "generation9_append_only_label_candidate_built_validated_not_installed":
        raise Generation9CandidateError("unexpected generation9 status")
    if summary.get("generation") != 9 or summary.get("parent_generation") != 8:
        raise Generation9CandidateError("generation mismatch")
    if summary.get("candidate_artifact_count") != 2 or summary.get("existing_records_replaced") != 0:
        raise Generation9CandidateError("candidate artifact or replacement policy mismatch")
    if summary.get("changed_members") != [
        "saves/b1/text_en/str_costume.xml",
        "saves/b1/text_jp/str_costume.xml",
        "saves/b1/text_sc/str_costume.xml",
        "saves/b1/text_tc/str_costume.xml",
    ]:
        raise Generation9CandidateError("changed member set mismatch")
    policy = summary.get("policy", {})
    if any(policy.get(key) is not False for key in policy):
        raise Generation9CandidateError("generation9 report violates fail-closed policy")
    member_rows = read_tsv(report_root / "GENERATION9_STR_COSTUME_MEMBER_PATCHES.tsv")
    if len(member_rows) != 4 or any(row.get("validation_status") != "passed" for row in member_rows):
        raise Generation9CandidateError("locale member validation incomplete")
    appended = read_tsv(report_root / "GENERATION9_APPENDED_LABEL_ROWS.tsv")
    if len(appended) != 32 or any(row.get("existing_record_replaced") != "false" for row in appended):
        raise Generation9CandidateError("append row validation incomplete")
    gust_rows = read_tsv(report_root / "GENERATION9_GUST_LIST_VALIDATION.tsv")
    if len(gust_rows) != 1 or gust_rows[0].get("validation_status") != "passed" or gust_rows[0].get("required_members_found") != "true":
        raise Generation9CandidateError("gust_pak validation missing or failed")
    baseline_rows = read_tsv(report_root / "GENERATION9_INSTALLATION_BASELINE_GATES.tsv")
    if len(baseline_rows) != 2 or any(row.get("state") != "baseline" or row.get("modified_by_stage") != "false" for row in baseline_rows):
        raise Generation9CandidateError("installed baseline validation missing or failed")
    composition = read_tsv(report_root / "GENERATION9_TWO_ARCHIVE_COMPOSITION.tsv")
    if len(composition) != 2 or [row.get("target_path") for row in composition] != [TARGET_PACK10, TARGET_PACK12]:
        raise Generation9CandidateError("two-archive composition mismatch")
    manifest = json.loads((report_root / "REPORT_MANIFEST.json").read_text(encoding="utf-8"))
    for row in manifest.get("files", []):
        path = report_root / row["path"]
        if not path.is_file() or path.stat().st_size != row["size"] or sha256_file(path) != row["sha256"]:
            raise Generation9CandidateError(f"report manifest mismatch: {row.get('path')}")
    return summary


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    audit_parser = sub.add_parser("audit")
    audit_parser.add_argument("--project-root", type=Path, default=PROJECT_ROOT_DEFAULT)
    audit_parser.add_argument("--quartet-root", type=Path, required=True)
    audit_parser.add_argument("--gust-pak", type=Path, required=True)
    audit_parser.add_argument("--output-root", type=Path)
    audit_parser.add_argument("--timeout", type=int, default=600)
    validate_parser = sub.add_parser("validate-report")
    validate_parser.add_argument("--report-root", type=Path, required=True)
    bundle_parser = sub.add_parser("bundle-report")
    bundle_parser.add_argument("--report-root", type=Path, required=True)
    bundle_parser.add_argument("--output", type=Path, required=True)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        if args.command == "audit":
            project = args.project_root.resolve()
            output = args.output_root or project / ".local/reports/quartet_legacy_dlc" / REPORT_DIR_NAME
            archive, _ = audit(project, args.quartet_root, args.gust_pak, output, timeout=args.timeout)
            print(archive)
        elif args.command == "validate-report":
            print(json.dumps(validate_report(args.report_root), ensure_ascii=False, sort_keys=True))
        elif args.command == "bundle-report":
            validate_report(args.report_root)
            make_archive(args.report_root, args.output)
            print(args.output)
        return 0
    except (Generation9CandidateError, NESTED.NestedContainerError, DRY.DryPakInsertionError, OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
