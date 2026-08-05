#!/usr/bin/env python3
"""Build and validate a local dry-BKN PACK12 replace-member candidate.

The stage consumes the validated 0.0.20 dry-composition preflight, uses the
currently installed Quartet PACK12 only as a read-only baseline, replaces
exactly saves/b1/chara/charabase.xml in a local copy-through candidate, and
proves that every non-target member remains byte-identical after decryption.
No candidate is installed, registered, activated, or exported in the report.
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
from pathlib import Path, PurePosixPath
from typing import Any, Iterable, Mapping, Sequence

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT_DEFAULT = SCRIPT_DIR.parent.parent
for import_path in (SCRIPT_DIR, PROJECT_ROOT_DEFAULT / "Blue_Reflection_Text_Tool"):
    if str(import_path) not in sys.path:
        sys.path.insert(0, str(import_path))

import br_dlc_nested_container_tool as NESTED  # noqa: E402
import br_dlc_dry_pak_insertion_tool as DRY  # noqa: E402
import br_dlc_bkn_dry_composition_preflight_tool as PREFLIGHT  # noqa: E402

TOOL_VERSION = "0.0.21"
FORMAT_VERSION = 1
REPORT_DIR_NAME = "bkn_dry_pack12_repack_evidence"
REPORT_ARCHIVE_NAME = "BR_quartet_legacy_dlc_bkn_dry_pack12_repack_evidence.tar.zst"
PREFLIGHT_DIR_NAME = "bkn_dry_composition_preflight_evidence"
PREFLIGHT_ARCHIVE_NAME = "BR_quartet_legacy_dlc_bkn_dry_composition_preflight_evidence.tar.zst"
TARGET_ARCHIVE_RELATIVE = Path("Data/PACK12.PAK")
TARGET_MEMBER = "saves/b1/chara/charabase.xml"
BUILD_RELATIVE = Path(".local/build/quartet_legacy_dlc/pack12_repack_tests/costume_pc00_bkn_dry")
PREFLIGHT_MEMBER_RELATIVE = PREFLIGHT.BUILD_RELATIVE / "candidate" / TARGET_MEMBER
DRY_PACK_RELATIVE = PREFLIGHT.DRY_PAK_RELATIVE
COPY_BLOCK_SIZE = 8 * 1024 * 1024
FREE_SPACE_MARGIN = 128 * 1024 * 1024
FORBIDDEN_REPORT_SUFFIXES = {
    ".pak", ".xml", ".ebm", ".ebd", ".g1m", ".g1t", ".g1a", ".g1e",
    ".g1s", ".elixir", ".gz", ".bin", ".dds", ".ktid", ".kts", ".exe", ".dll",
}


class BknDryPack12RepackError(RuntimeError):
    pass


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def sha256_region(path: Path, offset: int, size: int) -> str:
    if offset < 0 or size < 0:
        raise BknDryPack12RepackError("negative region geometry")
    h = hashlib.sha256()
    remaining = size
    with path.open("rb") as handle:
        handle.seek(offset)
        while remaining:
            block = handle.read(min(COPY_BLOCK_SIZE, remaining))
            if not block:
                raise BknDryPack12RepackError(f"truncated region in {path}")
            h.update(block)
            remaining -= len(block)
    return h.hexdigest()


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


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")


def clean_dir(path: Path) -> None:
    if path.exists():
        shutil.rmtree(path)
    path.mkdir(parents=True, exist_ok=True)


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
        raise BknDryPack12RepackError(f"cannot create report archive: {result.stderr.strip()}")
    os.replace(temporary, output)


def report_manifest(root: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for path in sorted(root.iterdir(), key=lambda item: item.name.casefold()):
        if not path.is_file() or path.name == "REPORT_MANIFEST.json":
            continue
        if {suffix.casefold() for suffix in path.suffixes} & FORBIDDEN_REPORT_SUFFIXES:
            raise BknDryPack12RepackError(f"raw asset-like file in report: {path}")
        rows.append({"path": path.name, "size": path.stat().st_size, "sha256": sha256_file(path)})
    return rows


def locate_report(report_parent: Path, directory: str, archive_name: str, temporary: Path) -> Path:
    direct = report_parent / directory
    if direct.is_dir():
        return direct
    archive = report_parent / archive_name
    if not archive.is_file():
        raise BknDryPack12RepackError(f"missing prerequisite report: {direct} / {archive}")
    listed = subprocess.run(["tar", "--zstd", "-tf", str(archive)], text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
    if listed.returncode:
        raise BknDryPack12RepackError(f"cannot list prerequisite archive: {listed.stderr.strip()}")
    roots = {PurePosixPath(line.strip()).parts[0] for line in listed.stdout.splitlines() if line.strip()}
    if len(roots) != 1:
        raise BknDryPack12RepackError(f"expected one root in prerequisite archive, found {sorted(roots)}")
    extracted = subprocess.run(["tar", "--zstd", "-xf", str(archive), "-C", str(temporary)], text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
    if extracted.returncode:
        raise BknDryPack12RepackError(f"cannot extract prerequisite archive: {extracted.stderr.strip()}")
    return temporary / next(iter(roots))


def validate_prerequisite(project_root: Path, temporary: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    report_parent = project_root / ".local/reports/quartet_legacy_dlc"
    root = locate_report(report_parent, PREFLIGHT_DIR_NAME, PREFLIGHT_ARCHIVE_NAME, temporary)
    summary = PREFLIGHT.validate_report(root)
    if summary.get("tool_version") != "0.0.20" or summary.get("status") != "local_dry_bkn_composition_preflight_ready_not_built_not_installed":
        raise BknDryPack12RepackError("preflight report is not the validated 0.0.20 result")
    policy = summary.get("policy", {})
    if policy.get("local_pack12_repack_test_allowed") is not True or policy.get("local_two_archive_composition_build_allowed") is not True:
        raise BknDryPack12RepackError("preflight does not authorize local PACK12 repack testing")
    forbidden_true = ("candidate_installed", "game_modified", "profile_build_allowed", "profile_registered", "runtime_validated", "target_pak_repacked")
    if any(policy.get(key) is not False for key in forbidden_true):
        raise BknDryPack12RepackError("preflight violates fail-closed policy")
    plan = json.loads((root / "DLC_BKN_DRY_COMPOSITION_PLAN.json").read_text(encoding="utf-8"))
    return summary, plan


def pack_raw_entry(
    raw_name: bytes, size: int, raw_key: bytes, extra: int, data_offset: int, flags: int,
    *, entry_struct: struct.Struct, a22: bool,
) -> bytes:
    if a22:
        return entry_struct.pack(raw_name, size, raw_key, extra, data_offset, flags)
    return entry_struct.pack(raw_name, size, raw_key, data_offset, flags)


def rewrite_table_for_replacement(
    layout: DRY.RawPakLayout, baseline_index: NESTED.PakIndex, target: NESTED.PakEntry, new_size: int,
) -> tuple[bytes, list[dict[str, Any]], int]:
    old_start = target.data_offset
    old_end = old_start + target.size
    delta = new_size - target.size
    table = bytearray()
    rows: list[dict[str, Any]] = []
    for idx in range(layout.file_count):
        start = idx * layout.entry_struct.size
        raw_entry = layout.raw_table[start:start + layout.entry_struct.size]
        raw_name, old_size, raw_key, extra, old_offset, entry_flags = DRY.raw_entry_parts(raw_entry, layout.entry_struct, a22=layout.a22)
        indexed = baseline_index.entries[idx]
        if old_size != indexed.size or old_offset != indexed.data_offset:
            raise BknDryPack12RepackError(f"raw/indexed entry mismatch at {idx}")
        entry_end = old_offset + old_size
        if idx != target.index and old_offset < old_end and entry_end > old_start:
            raise BknDryPack12RepackError(f"target member overlaps entry {idx}: {indexed.name}")
        if idx == target.index:
            next_size = new_size
            next_offset = old_offset
            change = "target_size_replaced"
        elif old_offset >= old_end:
            next_size = old_size
            next_offset = old_offset + delta
            change = "offset_shifted_after_target" if delta else "unchanged"
        else:
            next_size = old_size
            next_offset = old_offset
            change = "unchanged_before_target"
        if next_offset < 0:
            raise BknDryPack12RepackError(f"negative candidate offset at entry {idx}")
        table.extend(pack_raw_entry(raw_name, next_size, raw_key, extra, next_offset, entry_flags, entry_struct=layout.entry_struct, a22=layout.a22))
        rows.append({
            "entry_index": idx,
            "entry_name": indexed.name,
            "baseline_size": old_size,
            "candidate_size": next_size,
            "baseline_relative_offset": old_offset,
            "candidate_relative_offset": next_offset,
            "expected_change": change,
            "raw_name_preserved": True,
            "raw_key_preserved": True,
            "entry_flags_preserved": True,
            "entry_extra_preserved": True,
        })
    return bytes(table), rows, delta


def copy_region(source: Path, offset: int, size: int, output: Any) -> None:
    remaining = size
    with source.open("rb") as handle:
        handle.seek(offset)
        while remaining:
            block = handle.read(min(COPY_BLOCK_SIZE, remaining))
            if not block:
                raise BknDryPack12RepackError(f"truncated baseline region: {source}")
            output.write(block)
            remaining -= len(block)


def read_entry_plain(index: NESTED.PakIndex, entry: NESTED.PakEntry) -> bytes:
    with index.path.open("rb") as handle:
        handle.seek(entry.absolute_offset)
        raw = handle.read(entry.size)
    if len(raw) != entry.size:
        raise BknDryPack12RepackError(f"truncated entry {entry.index}: {entry.name}")
    return NESTED.xor_bytes(raw, entry.key) if entry.encrypted else raw


def run_gust_list(gust_pak: Path, candidate: Path, target_member: str, log_path: Path, timeout: int) -> dict[str, Any]:
    if not gust_pak.is_file() or not os.access(gust_pak, os.X_OK):
        raise BknDryPack12RepackError(f"gust_pak is not executable: {gust_pak}")
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("wb") as log:
        try:
            result = subprocess.run([str(gust_pak), "-l", str(candidate)], stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT, timeout=timeout, check=False)
        except subprocess.TimeoutExpired as exc:
            raise BknDryPack12RepackError(f"gust_pak listing timed out after {timeout}s") from exc
    text = log_path.read_text(encoding="utf-8", errors="replace")
    found = target_member.casefold() in text.replace("\\", "/").casefold()
    if result.returncode != 0 or not found:
        tail = "\n".join(text.splitlines()[-20:])
        raise BknDryPack12RepackError(f"gust_pak list validation failed (exit {result.returncode}, target_found={found})\n{tail}")
    return {
        "returncode": result.returncode,
        "log_size": log_path.stat().st_size,
        "log_sha256": sha256_file(log_path),
        "target_member_found": found,
        "detected_format_line": next((line for line in text.splitlines() if line.startswith("Detected ")), ""),
        "master_key_line": next((line for line in text.splitlines() if line.startswith("Using ")), ""),
    }


def audit(project_root: Path, quartet_root: Path, gust_pak: Path, output_root: Path, *, timeout: int = 600) -> tuple[Path, dict[str, Any]]:
    project_root = project_root.resolve()
    quartet_root = quartet_root.resolve()
    output_root = output_root.resolve()
    report_parent = project_root / ".local/reports/quartet_legacy_dlc"
    build_root = (project_root / BUILD_RELATIVE).resolve()
    baseline_pak = (quartet_root / TARGET_ARCHIVE_RELATIVE).resolve()
    candidate_member = (project_root / PREFLIGHT_MEMBER_RELATIVE).resolve()
    dry_pack_candidate = (project_root / DRY_PACK_RELATIVE).resolve()
    if not baseline_pak.is_file():
        raise BknDryPack12RepackError(f"Quartet PACK12 not found: {baseline_pak}")
    if not candidate_member.is_file():
        raise BknDryPack12RepackError(f"missing local preflight charabase candidate: {candidate_member}")
    if not dry_pack_candidate.is_file():
        raise BknDryPack12RepackError(f"missing local dry PACK10_02 candidate: {dry_pack_candidate}")
    if not str(build_root).startswith(str((project_root / ".local/build").resolve()) + os.sep):
        raise BknDryPack12RepackError("unsafe local build root")

    print("[stage52] validating 0.0.20 composition preflight", flush=True)
    with tempfile.TemporaryDirectory(prefix="br_dlc_pack12_prereq_") as temp_name:
        preflight, plan = validate_prerequisite(project_root, Path(temp_name))

    expected_member_sha = preflight["candidate_charabase_sha256"]
    expected_dry_sha = preflight["dry_pack10_02_candidate_sha256"]
    if sha256_file(candidate_member) != expected_member_sha or candidate_member.stat().st_size != int(plan["inputs"][1]["size"]):
        raise BknDryPack12RepackError("local charabase candidate differs from preflight")
    if sha256_file(dry_pack_candidate) != expected_dry_sha:
        raise BknDryPack12RepackError("local dry PACK10_02 candidate differs from preflight")

    print("[stage52] indexing installed Quartet PACK12 read-only", flush=True)
    baseline_stat = baseline_pak.stat()
    baseline_sha_before = sha256_file(baseline_pak)
    if baseline_sha_before != plan["inputs"][2]["sha256"] or baseline_stat.st_size != int(plan["inputs"][2]["size"]):
        raise BknDryPack12RepackError("installed PACK12 differs from preflight baseline")
    baseline_index = NESTED.index_pak(baseline_pak)
    layout = DRY.read_raw_layout(baseline_pak, baseline_index)
    matches = baseline_index.by_name.get(NESTED.safe_internal_name(TARGET_MEMBER).casefold(), [])
    if len(matches) != 1:
        raise BknDryPack12RepackError(f"expected one {TARGET_MEMBER} in PACK12, found {len(matches)}")
    target = matches[0]
    baseline_member = read_entry_plain(baseline_index, target)
    if target.index != int(preflight["installed_charabase_entry_index"]):
        raise BknDryPack12RepackError("charabase entry index differs from preflight")
    if sha256_bytes(baseline_member) != preflight["installed_charabase_sha256"]:
        raise BknDryPack12RepackError("installed charabase member differs from preflight")
    new_member = candidate_member.read_bytes()

    raw_table, table_rows, delta = rewrite_table_for_replacement(layout, baseline_index, target, len(new_member))
    output_size = baseline_stat.st_size + delta
    if output_size <= NESTED.PAK_HEADER.size + len(raw_table):
        raise BknDryPack12RepackError("invalid candidate output size")
    free = shutil.disk_usage(build_root.parent if build_root.parent.exists() else project_root).free
    if free < output_size + FREE_SPACE_MARGIN:
        raise BknDryPack12RepackError(f"insufficient free space: need {output_size + FREE_SPACE_MARGIN}, have {free}")

    clean_dir(build_root)
    candidate_dir = build_root / "candidate"
    metadata_dir = build_root / "metadata"
    candidate_dir.mkdir(parents=True)
    metadata_dir.mkdir(parents=True)
    candidate_pak = candidate_dir / "PACK12.PAK"
    temporary_pak = candidate_dir / ".PACK12.PAK.tmp"
    encoded_member = NESTED.xor_bytes(new_member, target.key) if target.encrypted else new_member
    old_start = target.data_offset
    old_end = old_start + target.size
    data_size = baseline_stat.st_size - baseline_index.file_data_offset

    print(f"[stage52] building local PACK12 replace-member candidate ({output_size} bytes)", flush=True)
    try:
        with temporary_pak.open("wb") as output:
            output.write(NESTED.PAK_HEADER.pack(layout.version, layout.file_count, layout.header_size, layout.flags))
            output.write(raw_table)
            copy_region(baseline_pak, baseline_index.file_data_offset, old_start, output)
            output.write(encoded_member)
            copy_region(baseline_pak, baseline_index.file_data_offset + old_end, data_size - old_end, output)
            output.flush()
            os.fsync(output.fileno())
        if temporary_pak.stat().st_size != output_size:
            raise BknDryPack12RepackError(f"candidate size mismatch: {temporary_pak.stat().st_size} != {output_size}")
        os.replace(temporary_pak, candidate_pak)
    finally:
        temporary_pak.unlink(missing_ok=True)

    print("[stage52] validating candidate with internal parser and all member hashes", flush=True)
    candidate_index = NESTED.index_pak(candidate_pak)
    if (candidate_index.format_name, candidate_index.master_key_label, len(candidate_index.entries)) != (
        baseline_index.format_name, baseline_index.master_key_label, len(baseline_index.entries)
    ):
        raise BknDryPack12RepackError("candidate layout/master-key/entry-count differs from baseline")

    validation_rows: list[dict[str, Any]] = []
    non_target_identical = 0
    for original, rebuilt, planned in zip(baseline_index.entries, candidate_index.entries, table_rows):
        if original.name != rebuilt.name or original.key != rebuilt.key or original.encrypted != rebuilt.encrypted:
            raise BknDryPack12RepackError(f"entry identity changed at index {original.index}")
        source_plain = read_entry_plain(baseline_index, original)
        target_plain = read_entry_plain(candidate_index, rebuilt)
        if original.index == target.index:
            passed = len(target_plain) == len(new_member) and sha256_bytes(target_plain) == expected_member_sha
            member_status = "target_replaced_exact_candidate"
        else:
            passed = len(source_plain) == len(target_plain) and sha256_bytes(source_plain) == sha256_bytes(target_plain)
            member_status = "non_target_identical"
            non_target_identical += int(passed)
        if not passed:
            raise BknDryPack12RepackError(f"member preservation failed at {original.index}: {original.name}")
        if rebuilt.size != int(planned["candidate_size"]) or rebuilt.data_offset != int(planned["candidate_relative_offset"]):
            raise BknDryPack12RepackError(f"candidate table geometry differs at {original.index}")
        validation_rows.append({
            **planned,
            "source_plain_sha256": sha256_bytes(source_plain),
            "candidate_plain_sha256": sha256_bytes(target_plain),
            "member_status": member_status,
            "validation_status": "passed",
        })

    pre_region_size = old_start
    post_region_size = data_size - old_end
    candidate_data_base = candidate_index.file_data_offset
    pre_source_sha = sha256_region(baseline_pak, baseline_index.file_data_offset, pre_region_size)
    pre_candidate_sha = sha256_region(candidate_pak, candidate_data_base, pre_region_size)
    post_source_sha = sha256_region(baseline_pak, baseline_index.file_data_offset + old_end, post_region_size)
    post_candidate_sha = sha256_region(candidate_pak, candidate_data_base + old_start + len(new_member), post_region_size)
    if pre_source_sha != pre_candidate_sha or post_source_sha != post_candidate_sha:
        raise BknDryPack12RepackError("non-target encrypted data regions changed")

    print("[stage52] validating candidate with gust_pak -l", flush=True)
    gust_result = run_gust_list(gust_pak, candidate_pak, TARGET_MEMBER, metadata_dir / "gust_pak_list.log", timeout)

    baseline_sha_after = sha256_file(baseline_pak)
    baseline_stat_after = baseline_pak.stat()
    installed_unchanged = (
        baseline_sha_before == baseline_sha_after
        and baseline_stat.st_size == baseline_stat_after.st_size
        and baseline_stat.st_mtime_ns == baseline_stat_after.st_mtime_ns
    )
    if not installed_unchanged:
        raise BknDryPack12RepackError("installed PACK12 changed during local repack test")

    candidate_sha = sha256_file(candidate_pak)
    composition = {
        "type": "br_quartet_legacy_dlc_local_bkn_dry_two_archive_composition",
        "format_version": FORMAT_VERSION,
        "tool_version": TOOL_VERSION,
        "content_id": "costume_pc00_bkn",
        "archives": [
            {
                "archive": "Data/PACK10_02.PAK",
                "candidate_relative_path": DRY_PACK_RELATIVE.as_posix(),
                "candidate_size": dry_pack_candidate.stat().st_size,
                "candidate_sha256": expected_dry_sha,
                "role": "dry_parent_and_external_texture",
            },
            {
                "archive": "Data/PACK12.PAK",
                "candidate_relative_path": candidate_pak.relative_to(project_root).as_posix(),
                "candidate_size": candidate_pak.stat().st_size,
                "candidate_sha256": candidate_sha,
                "role": "dry_charabase_fallback_removal",
            },
        ],
        "transaction_state": "local_composition_built_not_installable_not_registered",
        "install_order_defined": False,
        "rollback_defined": False,
        "profile_build_allowed": False,
        "candidate_installed": False,
        "runtime_validated": False,
        "wet_variant_included": False,
    }
    write_json(metadata_dir / "BKN_DRY_TWO_ARCHIVE_COMPOSITION.json", composition)

    clean_dir(output_root)
    archive_row = {
        "archive": TARGET_ARCHIVE_RELATIVE.as_posix(),
        "baseline_size": baseline_stat.st_size,
        "baseline_sha256_before": baseline_sha_before,
        "baseline_sha256_after": baseline_sha_after,
        "baseline_format": baseline_index.format_name,
        "baseline_master_key": baseline_index.master_key_label,
        "baseline_entry_count": len(baseline_index.entries),
        "candidate_size": candidate_pak.stat().st_size,
        "candidate_sha256": candidate_sha,
        "candidate_entry_count": len(candidate_index.entries),
        "size_delta": delta,
        "target_entry_index": target.index,
        "non_target_entries_validated": non_target_identical,
        "installed_archive_unchanged": installed_unchanged,
        "candidate_installed": False,
        "profile_registered": False,
        "runtime_validated": False,
    }
    write_tsv(output_root / "DLC_BKN_DRY_PACK12_REPACK_ARCHIVE.tsv", list(archive_row), [archive_row])
    target_row = {
        "archive": TARGET_ARCHIVE_RELATIVE.as_posix(),
        "member": TARGET_MEMBER,
        "entry_index": target.index,
        "source_size": len(baseline_member),
        "source_sha256": sha256_bytes(baseline_member),
        "candidate_size": len(new_member),
        "candidate_sha256": sha256_bytes(new_member),
        "changed_fields": ["Model", "defaultTexture"],
        "wet_record_unchanged": True,
        "outside_dry_record_unchanged": True,
        "validation_status": "passed",
        "raw_payload_exported_in_report": False,
    }
    write_tsv(output_root / "DLC_BKN_DRY_PACK12_TARGET_MEMBER.tsv", list(target_row), [target_row])
    write_tsv(output_root / "DLC_BKN_DRY_PACK12_ENTRY_VALIDATION.tsv", list(validation_rows[0]), validation_rows)
    region_rows = [
        {
            "region": "encrypted_data_before_target",
            "source_size": pre_region_size,
            "source_sha256": pre_source_sha,
            "candidate_size": pre_region_size,
            "candidate_sha256": pre_candidate_sha,
            "validation_status": "passed",
        },
        {
            "region": "encrypted_data_after_target",
            "source_size": post_region_size,
            "source_sha256": post_source_sha,
            "candidate_size": post_region_size,
            "candidate_sha256": post_candidate_sha,
            "validation_status": "passed",
        },
    ]
    write_tsv(output_root / "DLC_BKN_DRY_PACK12_DATA_REGION_PRESERVATION.tsv", list(region_rows[0]), region_rows)
    layout_row = {
        "baseline_format": baseline_index.format_name,
        "candidate_format": candidate_index.format_name,
        "baseline_master_key": baseline_index.master_key_label,
        "candidate_master_key": candidate_index.master_key_label,
        "entry_size": layout.entry_struct.size,
        "entry_count": len(candidate_index.entries),
        "target_old_size": target.size,
        "target_new_size": len(new_member),
        "target_relative_offset_preserved": True,
        "post_target_offset_delta": delta,
        "validation_status": "passed",
    }
    write_tsv(output_root / "DLC_BKN_DRY_PACK12_LAYOUT_VALIDATION.tsv", list(layout_row), [layout_row])
    gust_row = {
        "gust_pak_sha256": sha256_file(gust_pak),
        **gust_result,
        "validation_status": "passed",
    }
    write_tsv(output_root / "DLC_BKN_DRY_PACK12_GUST_LIST_VALIDATION.tsv", list(gust_row), [gust_row])
    comp_rows = [
        {
            "archive": item["archive"],
            "role": item["role"],
            "candidate_relative_path": item["candidate_relative_path"],
            "candidate_size": item["candidate_size"],
            "candidate_sha256": item["candidate_sha256"],
            "candidate_installed": False,
            "profile_registered": False,
            "runtime_validated": False,
        }
        for item in composition["archives"]
    ]
    write_tsv(output_root / "DLC_BKN_DRY_TWO_ARCHIVE_COMPOSITION.tsv", list(comp_rows[0]), comp_rows)
    gaps = [
        {
            "dependency": "transactional_two_archive_install_and_rollback_harness",
            "status": "not_implemented",
            "blocks_installation": True,
            "next_evidence": "request or implement core support for one checksum-gated transaction spanning PACK10_02 and PACK12; do not install ad hoc",
        },
        {
            "dependency": "runtime_availability_and_costume_selection",
            "status": "not_validated",
            "blocks_installation": True,
            "next_evidence": "perform runtime validation only after a transactional local composition is explicitly approved",
        },
        {
            "dependency": "owner_ui_icon_or_thumbnail",
            "status": "unresolved_but_selected_ui_numeric_route_closed",
            "blocks_installation": True,
            "next_evidence": "runtime observation or format-proven owner binding; do not patch isolated KSCL/KSLT integers",
        },
        {
            "dependency": "wet_variant_conversion",
            "status": "conversion_blocked",
            "blocks_installation": True,
            "next_evidence": "complete G1M/SWG conversion and exact wet texture binding separately",
        },
    ]
    write_tsv(output_root / "DLC_BKN_DRY_PACK12_REPACK_GAPS.tsv", list(gaps[0]), gaps)

    summary = {
        "type": "br_quartet_legacy_dlc_bkn_dry_pack12_repack_summary",
        "format_version": FORMAT_VERSION,
        "tool_version": TOOL_VERSION,
        "status": "local_pack12_candidate_built_two_archive_composition_recorded_not_installed",
        "content_id": "costume_pc00_bkn",
        "baseline_pack12_sha256": baseline_sha_before,
        "candidate_pack12_sha256": candidate_sha,
        "candidate_pack12_size": candidate_pak.stat().st_size,
        "candidate_pack12_entry_count": len(candidate_index.entries),
        "target_member": TARGET_MEMBER,
        "target_member_candidate_sha256": expected_member_sha,
        "non_target_entries_validated": non_target_identical,
        "dry_pack10_02_candidate_sha256": expected_dry_sha,
        "two_archive_candidate_count": 2,
        "unresolved_installation_blockers": len(gaps),
        "local_build_root": build_root.relative_to(project_root).as_posix(),
        "findings": [
            "the installed PACK12 was used read-only and remained hash/size/mtime identical",
            "the local PACK12 candidate replaces exactly charabase.xml and preserves every non-target member plaintext hash",
            "the target member is the exact dry-only preflight candidate changing only Model/defaultTexture for PC00_DLC_BKN",
            "the local PACK10_02 and PACK12 candidate hashes are recorded as one dry-only composition",
            "the composition is not transactionally installable, registered, installed or runtime-validated",
        ],
        "next_action": "prepare a core-target request or local transactional composition harness for PACK10_02 plus PACK12 with atomic rollback; do not install either candidate independently",
        "policy": {
            "game_modified": False,
            "git_modified": False,
            "candidate_installed": False,
            "profile_registered": False,
            "profile_build_allowed": False,
            "runtime_validated": False,
            "local_pack12_repacked": True,
            "local_two_archive_composition_recorded": True,
            "transactional_install_harness_present": False,
            "raw_assets_in_local_build": True,
            "raw_assets_exported_in_report": False,
            "raw_assets_in_update": False,
            "translation_modified": False,
            "wet_variant_included": False,
        },
    }
    write_json(output_root / "SUMMARY.json", summary)
    write_json(output_root / "REPORT_MANIFEST.json", {"type": "br_report_manifest", "format_version": 1, "files": report_manifest(output_root)})
    archive = report_parent / REPORT_ARCHIVE_NAME
    make_archive(output_root, archive)
    print(f"[stage52] local candidate: {candidate_pak}", flush=True)
    print(f"[stage52] report: {archive}", flush=True)
    return archive, summary


def validate_report(report_root: Path) -> dict[str, Any]:
    report_root = report_root.resolve()
    required = (
        "DLC_BKN_DRY_PACK12_REPACK_ARCHIVE.tsv",
        "DLC_BKN_DRY_PACK12_TARGET_MEMBER.tsv",
        "DLC_BKN_DRY_PACK12_ENTRY_VALIDATION.tsv",
        "DLC_BKN_DRY_PACK12_DATA_REGION_PRESERVATION.tsv",
        "DLC_BKN_DRY_PACK12_LAYOUT_VALIDATION.tsv",
        "DLC_BKN_DRY_PACK12_GUST_LIST_VALIDATION.tsv",
        "DLC_BKN_DRY_TWO_ARCHIVE_COMPOSITION.tsv",
        "DLC_BKN_DRY_PACK12_REPACK_GAPS.tsv",
        "SUMMARY.json",
        "REPORT_MANIFEST.json",
    )
    for name in required:
        if not (report_root / name).is_file():
            raise BknDryPack12RepackError(f"missing report file: {name}")
    summary = json.loads((report_root / "SUMMARY.json").read_text(encoding="utf-8"))
    if summary.get("type") != "br_quartet_legacy_dlc_bkn_dry_pack12_repack_summary" or summary.get("tool_version") != TOOL_VERSION:
        raise BknDryPack12RepackError("invalid PACK12 repack summary")
    if summary.get("status") != "local_pack12_candidate_built_two_archive_composition_recorded_not_installed":
        raise BknDryPack12RepackError("unexpected PACK12 repack status")
    if summary.get("two_archive_candidate_count") != 2 or summary.get("non_target_entries_validated", 0) < 1:
        raise BknDryPack12RepackError("incomplete two-archive or non-target validation")
    policy = summary.get("policy", {})
    false_keys = (
        "game_modified", "git_modified", "candidate_installed", "profile_registered",
        "profile_build_allowed", "runtime_validated", "transactional_install_harness_present",
        "raw_assets_exported_in_report", "raw_assets_in_update", "translation_modified", "wet_variant_included",
    )
    if any(policy.get(key) is not False for key in false_keys):
        raise BknDryPack12RepackError("PACK12 repack report violates fail-closed policy")
    if policy.get("local_pack12_repacked") is not True or policy.get("local_two_archive_composition_recorded") is not True:
        raise BknDryPack12RepackError("PACK12 local-build declarations missing")
    archive_rows = read_tsv(report_root / "DLC_BKN_DRY_PACK12_REPACK_ARCHIVE.tsv")
    if len(archive_rows) != 1 or archive_rows[0].get("installed_archive_unchanged") != "true":
        raise BknDryPack12RepackError("installed PACK12 preservation not proven")
    target_rows = read_tsv(report_root / "DLC_BKN_DRY_PACK12_TARGET_MEMBER.tsv")
    if len(target_rows) != 1 or target_rows[0].get("validation_status") != "passed" or target_rows[0].get("wet_record_unchanged") != "true":
        raise BknDryPack12RepackError("target-member validation missing or failed")
    entry_rows = read_tsv(report_root / "DLC_BKN_DRY_PACK12_ENTRY_VALIDATION.tsv")
    expected_count = int(archive_rows[0]["candidate_entry_count"])
    if len(entry_rows) != expected_count or any(row.get("validation_status") != "passed" for row in entry_rows):
        raise BknDryPack12RepackError("entry-level validation incomplete")
    if sum(row.get("member_status") == "target_replaced_exact_candidate" for row in entry_rows) != 1:
        raise BknDryPack12RepackError("expected exactly one replaced target member")
    region_rows = read_tsv(report_root / "DLC_BKN_DRY_PACK12_DATA_REGION_PRESERVATION.tsv")
    if len(region_rows) != 2 or any(row.get("validation_status") != "passed" for row in region_rows):
        raise BknDryPack12RepackError("data-region preservation failed")
    composition = read_tsv(report_root / "DLC_BKN_DRY_TWO_ARCHIVE_COMPOSITION.tsv")
    if len(composition) != 2 or {row.get("archive") for row in composition} != {"Data/PACK10_02.PAK", "Data/PACK12.PAK"}:
        raise BknDryPack12RepackError("two-archive composition is incomplete")
    gaps = read_tsv(report_root / "DLC_BKN_DRY_PACK12_REPACK_GAPS.tsv")
    if len(gaps) < 4 or any(row.get("blocks_installation") != "true" for row in gaps):
        raise BknDryPack12RepackError("installation blockers missing")
    manifest = json.loads((report_root / "REPORT_MANIFEST.json").read_text(encoding="utf-8"))
    for row in manifest.get("files", []):
        path = report_root / row["path"]
        if not path.is_file() or path.stat().st_size != row["size"] or sha256_file(path) != row["sha256"]:
            raise BknDryPack12RepackError(f"report manifest mismatch: {row.get('path')}")
        if {suffix.casefold() for suffix in path.suffixes} & FORBIDDEN_REPORT_SUFFIXES:
            raise BknDryPack12RepackError(f"raw asset in report: {path}")
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
            audit(project, args.quartet_root, args.gust_pak, output, timeout=args.timeout)
        elif args.command == "validate-report":
            summary = validate_report(args.report_root)
            print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
        elif args.command == "bundle-report":
            validate_report(args.report_root)
            make_archive(args.report_root, args.output)
            print(args.output)
        return 0
    except (BknDryPack12RepackError, NESTED.NestedContainerError, DRY.DryPakInsertionError, PREFLIGHT.BknDryCompositionPreflightError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
