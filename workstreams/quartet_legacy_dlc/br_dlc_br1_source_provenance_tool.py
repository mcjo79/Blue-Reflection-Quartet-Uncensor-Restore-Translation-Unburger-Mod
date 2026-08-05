#!/usr/bin/env python3
"""Audit BR1 source-archive provenance at member level without exporting assets.

The audit compares user-preserved underscore archives with user-designated clean
Steam copies, identifies exact changed members, classifies likely DLC/UI/system
relevance, and cross-references existing quartet_legacy_dlc reports/build
metadata.  It never modifies either game, source archive, extracted payload, or
workstream owned by another module.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Iterator

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import br_dlc_nested_container_tool as NESTED

TOOL_VERSION = "0.0.23"
FORMAT_VERSION = 1
REPORT_DIR_NAME = "br1_source_provenance_evidence"
REPORT_ARCHIVE_NAME = "BR_quartet_legacy_dlc_br1_source_provenance_evidence.tar.zst"
EXPECTED_PACK00_02_OFFICIAL_SHA1 = "f4f10dd846bbb056b81e18050ad3edc680d0bc8b"
EXPECTED_PACK00_02_MODIFIED_SHA1 = "5a96b714d4fb828511049558e702f4b216f03522"
PAIR_SPECS = (
    ("PACK00_02", "DATA/PACK00_02.PAK_", "DATA/PACK00_02.PAK"),
    ("PACK00_04_1", "DATA/PACK00_04_1.PAK_", "DATA/PACK00_04_1.PAK"),
    ("PACK00_04_2", "DATA/PACK00_04_2.PAK_", "DATA/PACK00_04_2.PAK"),
    ("PACK00_04_3", "DATA/PACK00_04_3.PAK_", "DATA/PACK00_04_3.PAK"),
)
KNOWN_PACK00_02_DLC_CHANGED_BASENAMES = {
    "pc03_dlc_bkn_w.g1t", "pc03_dlc_slr_w.g1t", "pc03_dlc_twl_w.g1t", "pc03_dlc_vac_w.g1t",
    "pc04_dlc_bkn_w.g1t", "pc04_dlc_slr_w.g1t", "pc04_dlc_twl_w.g1t", "pc04_dlc_vac_w.g1t",
    "pc06_dlc_bkn_w.g1t", "pc06_dlc_slr_w.g1t", "pc06_dlc_twl_w.g1t", "pc06_dlc_vac_w.g1t",
    "pc14_dlc_slr_w.g1t",
}
CURRENT_DRY_BKN_MEMBERS = {
    "data/x64/character/pc00/pc00_dlc_bkn.elixir.gz",
    "data/x64/character/pc00/pc00_dlc_bkn.g1t",
}
TEXT_SCAN_SUFFIXES = {
    ".json", ".tsv", ".csv", ".md", ".txt", ".log", ".sh", ".py", ".yaml", ".yml",
}
FORBIDDEN_REPORT_SUFFIXES = {
    ".pak", ".g1t", ".g1m", ".g1a", ".g1e", ".g1s", ".elixir", ".gz", ".dds",
    ".kscl", ".kslt", ".xml", ".exe", ".dll", ".bin", ".ebm", ".ebd", ".swg", ".oid",
}
MAX_TEXT_FILE_SIZE = 64 * 1024 * 1024
CHUNK_SIZE = 16 * 1024 * 1024


class Br1SourceProvenanceError(RuntimeError):
    pass


@dataclass(frozen=True)
class PairResult:
    pair_id: str
    modified_path: Path
    official_path: Path
    modified_index: NESTED.PakIndex
    official_index: NESTED.PakIndex
    archive_row: dict[str, Any]
    member_rows: list[dict[str, Any]]
    changed_rows: list[dict[str, Any]]


def bool_text(value: Any) -> Any:
    if isinstance(value, bool):
        return "true" if value else "false"
    if value is None:
        return ""
    if isinstance(value, (dict, list, tuple, set)):
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return value


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def write_tsv(path: Path, fields: Iterable[str], rows: Iterable[dict[str, Any]]) -> None:
    fieldnames = list(fields)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, delimiter="\t", lineterminator="\n", extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({field: bool_text(row.get(field, "")) for field in fieldnames})


def read_tsv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def hash_file(path: Path, algorithm: str) -> str:
    digest = hashlib.new(algorithm)
    with path.open("rb") as handle:
        while True:
            block = handle.read(CHUNK_SIZE)
            if not block:
                break
            digest.update(block)
    return digest.hexdigest()


def sha256_file(path: Path) -> str:
    return hash_file(path, "sha256")


def sha1_file(path: Path) -> str:
    return hash_file(path, "sha1")


def hash_file_digests(path: Path) -> tuple[str, str]:
    sha1 = hashlib.sha1()
    sha256 = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            block = handle.read(CHUNK_SIZE)
            if not block:
                break
            sha1.update(block)
            sha256.update(block)
    return sha1.hexdigest(), sha256.hexdigest()


def make_archive(root: Path, output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(output.name + ".tmp")
    temporary.unlink(missing_ok=True)
    result = subprocess.run(
        ["tar", "--zstd", "-cf", str(temporary), "-C", str(root.parent), root.name],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    if result.returncode != 0:
        temporary.unlink(missing_ok=True)
        raise Br1SourceProvenanceError(f"cannot create report archive: {result.stderr.strip()}")
    os.replace(temporary, output)


def report_manifest(root: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.name == "REPORT_MANIFEST.json":
            continue
        if {suffix.casefold() for suffix in path.suffixes} & FORBIDDEN_REPORT_SUFFIXES:
            raise Br1SourceProvenanceError(f"raw asset-like file in report: {path}")
        rows.append({
            "path": path.relative_to(root).as_posix(),
            "size": path.stat().st_size,
            "sha256": sha256_file(path),
        })
    return rows


def xor_block(data: bytes, key: bytes, start: int) -> bytes:
    if not key or not any(key):
        return data
    key_len = len(key)
    return bytes(value ^ key[(start + index) % key_len] for index, value in enumerate(data))


def compare_payloads(
    modified_index: NESTED.PakIndex,
    modified_entry: NESTED.PakEntry,
    official_index: NESTED.PakIndex,
    official_entry: NESTED.PakEntry,
) -> tuple[bool, str, str]:
    """Return decoded equality and decoded SHA-256 values.

    Both sides are streamed.  Hashes are retained for changed members and make
    later extracted-payload provenance matching possible without exporting bytes.
    """
    modified_hash = hashlib.sha256()
    official_hash = hashlib.sha256()
    equal = modified_entry.size == official_entry.size
    position = 0
    with modified_index.path.open("rb") as modified_handle, official_index.path.open("rb") as official_handle:
        modified_handle.seek(modified_entry.absolute_offset)
        official_handle.seek(official_entry.absolute_offset)
        remaining_modified = modified_entry.size
        remaining_official = official_entry.size
        while remaining_modified or remaining_official:
            modified_raw = modified_handle.read(min(CHUNK_SIZE, remaining_modified)) if remaining_modified else b""
            official_raw = official_handle.read(min(CHUNK_SIZE, remaining_official)) if remaining_official else b""
            if remaining_modified and not modified_raw:
                raise Br1SourceProvenanceError(f"truncated modified member: {modified_entry.name}")
            if remaining_official and not official_raw:
                raise Br1SourceProvenanceError(f"truncated official member: {official_entry.name}")
            modified_data = xor_block(modified_raw, modified_entry.key, position) if modified_entry.encrypted else modified_raw
            official_data = xor_block(official_raw, official_entry.key, position) if official_entry.encrypted else official_raw
            modified_hash.update(modified_data)
            official_hash.update(official_data)
            if modified_data != official_data:
                equal = False
            position += max(len(modified_raw), len(official_raw))
            remaining_modified -= len(modified_raw)
            remaining_official -= len(official_raw)
    return equal, modified_hash.hexdigest(), official_hash.hexdigest()


def hash_decoded_entry(index: NESTED.PakIndex, entry: NESTED.PakEntry) -> str:
    digest = hashlib.sha256()
    position = 0
    remaining = entry.size
    with index.path.open("rb") as handle:
        handle.seek(entry.absolute_offset)
        while remaining:
            raw = handle.read(min(CHUNK_SIZE, remaining))
            if not raw:
                raise Br1SourceProvenanceError(f"truncated member: {entry.name}")
            data = xor_block(raw, entry.key, position) if entry.encrypted else raw
            digest.update(data)
            position += len(raw)
            remaining -= len(raw)
    return digest.hexdigest()


def resource_type(name: str) -> str:
    lower = name.casefold()
    if lower.endswith(".g1t"):
        return "texture_g1t"
    if lower.endswith(".g1m"):
        return "model_or_material_g1m"
    if lower.endswith(".g1a"):
        return "animation_g1a"
    if lower.endswith(".g1e"):
        return "effect_g1e"
    if lower.endswith(".swg"):
        return "cloth_or_physics_swg"
    if lower.endswith("oid.bin") or lower.endswith(".oid"):
        return "object_identifier"
    if lower.endswith(".elixir.gz") or lower.endswith(".elixir"):
        return "elixir_container"
    if lower.endswith(".kscl"):
        return "ui_layout_kscl"
    if lower.endswith(".kslt"):
        return "ui_texture_layout_kslt"
    if lower.endswith(".xml"):
        return "system_or_text_xml"
    if lower.endswith(".ebm") or lower.endswith(".ebd"):
        return "scenario_binary"
    return Path(lower).suffix.lstrip(".") or "unknown"


def classify_tags(name: str) -> list[str]:
    lower = name.casefold().replace("\\", "/")
    base = Path(lower).name
    tags: set[str] = set()
    if "_dlc_" in lower or "/dlc/" in lower:
        tags.add("dlc")
    for token in ("bkn", "twl", "slr", "vac"):
        if f"_{token}" in lower or f"/{token}" in lower:
            tags.add(token)
    if re.search(r"pc\d{2}(_dlc)?_", base) or "/character/pc" in lower:
        tags.add("character_or_costume")
    if any(token in lower for token in ("costume", "coschange", "chara/", "character/")):
        tags.add("costume_or_character")
    if any(token in lower for token in ("mainmenu", "/ui/", "kscl", "kslt", "icon", "menu")):
        tags.add("ui_or_icon")
    if any(token in lower for token in ("unlock", "releasecondition", "entitlement", "license", "ticket")):
        tags.add("unlock_or_entitlement")
    if lower.endswith(".xml") or any(token in lower for token in ("/saves/", "/table/", "/system/")):
        tags.add("system_or_text_table")
    if any(token in lower for token in ("_scl", "school", "swimsuit", "_swm", "_nude", "_nud", "/npc", "npc_")):
        tags.add("shared_restoration_candidate")
    if base in KNOWN_PACK00_02_DLC_CHANGED_BASENAMES:
        tags.add("user_reported_dlc_changed_texture")
    return sorted(tags)


def relevance_class(tags: list[str]) -> str:
    values = set(tags)
    if "unlock_or_entitlement" in values:
        return "unlock_or_entitlement"
    if "ui_or_icon" in values:
        return "ui_or_icon"
    if "dlc" in values:
        return "direct_dlc_asset"
    if "shared_restoration_candidate" in values:
        return "shared_restoration_candidate"
    if "system_or_text_table" in values:
        return "system_or_text_table"
    return "other_or_unclassified"


def unique_map(index: NESTED.PakIndex) -> dict[str, NESTED.PakEntry]:
    result: dict[str, NESTED.PakEntry] = {}
    for key, entries in index.by_name.items():
        if len(entries) != 1:
            raise Br1SourceProvenanceError(f"duplicate member name in {index.path}: {entries[0].name}")
        result[key] = entries[0]
    return result


def compare_pair(pair_id: str, modified_path: Path, official_path: Path) -> PairResult:
    modified_stat = modified_path.stat()
    official_stat = official_path.stat()
    modified_sha1, modified_sha256 = hash_file_digests(modified_path)
    official_sha1, official_sha256 = hash_file_digests(official_path)
    if pair_id == "PACK00_02":
        if modified_sha1 != EXPECTED_PACK00_02_MODIFIED_SHA1:
            raise Br1SourceProvenanceError(
                f"PACK00_02.PAK_ SHA-1 mismatch: expected {EXPECTED_PACK00_02_MODIFIED_SHA1}, got {modified_sha1}"
            )
        if official_sha1 != EXPECTED_PACK00_02_OFFICIAL_SHA1:
            raise Br1SourceProvenanceError(
                f"official PACK00_02.PAK SHA-1 mismatch: expected {EXPECTED_PACK00_02_OFFICIAL_SHA1}, got {official_sha1}"
            )
    modified_index = NESTED.index_pak(modified_path)
    official_index = NESTED.index_pak(official_path)
    modified_map = unique_map(modified_index)
    official_map = unique_map(official_index)
    rows: list[dict[str, Any]] = []
    changed: list[dict[str, Any]] = []
    for key in sorted(set(modified_map) | set(official_map)):
        modified_entry = modified_map.get(key)
        official_entry = official_map.get(key)
        if modified_entry and official_entry:
            payload_equal, modified_payload_hash, official_payload_hash = compare_payloads(
                modified_index, modified_entry, official_index, official_entry
            )
            status = "identical" if payload_equal else "changed"
            name = official_entry.name
        elif modified_entry:
            status = "modified_only_removed_from_official"
            name = modified_entry.name
            modified_payload_hash = hash_decoded_entry(modified_index, modified_entry)
            official_payload_hash = ""
        else:
            assert official_entry is not None
            status = "official_only_added_in_official"
            name = official_entry.name
            modified_payload_hash = ""
            official_payload_hash = hash_decoded_entry(official_index, official_entry)
        tags = classify_tags(name)
        row = {
            "pair_id": pair_id,
            "member_name": name,
            "status": status,
            "resource_type": resource_type(name),
            "relevance_class": relevance_class(tags),
            "tags": ";".join(tags),
            "modified_index": modified_entry.index if modified_entry else "",
            "official_index": official_entry.index if official_entry else "",
            "modified_size": modified_entry.size if modified_entry else "",
            "official_size": official_entry.size if official_entry else "",
            "size_changed": bool(modified_entry and official_entry and modified_entry.size != official_entry.size),
            "modified_data_offset": modified_entry.data_offset if modified_entry else "",
            "official_data_offset": official_entry.data_offset if official_entry else "",
            "data_offset_changed": bool(modified_entry and official_entry and modified_entry.data_offset != official_entry.data_offset),
            "modified_absolute_offset": modified_entry.absolute_offset if modified_entry else "",
            "official_absolute_offset": official_entry.absolute_offset if official_entry else "",
            "absolute_offset_changed": bool(modified_entry and official_entry and modified_entry.absolute_offset != official_entry.absolute_offset),
            "modified_payload_sha256": modified_payload_hash,
            "official_payload_sha256": official_payload_hash,
            "known_user_reported_pack00_02_dlc_change": Path(name.casefold()).name in KNOWN_PACK00_02_DLC_CHANGED_BASENAMES,
        }
        rows.append(row)
        if status != "identical":
            changed.append(row.copy())
    status_counts = Counter(row["status"] for row in rows)
    archive_row = {
        "pair_id": pair_id,
        "modified_relative_path": modified_path.name,
        "official_relative_path": official_path.name,
        "modified_designation": "untrusted_modified_candidate",
        "official_designation": "user_designated_official_steam_copy",
        "modified_size": modified_stat.st_size,
        "official_size": official_stat.st_size,
        "archive_size_equal": modified_stat.st_size == official_stat.st_size,
        "modified_sha1": modified_sha1,
        "official_sha1": official_sha1,
        "modified_sha256": modified_sha256,
        "official_sha256": official_sha256,
        "modified_format": modified_index.format_name,
        "official_format": official_index.format_name,
        "modified_master_key": modified_index.master_key_label,
        "official_master_key": official_index.master_key_label,
        "modified_entry_count": len(modified_index.entries),
        "official_entry_count": len(official_index.entries),
        "identical_member_count": status_counts["identical"],
        "changed_member_count": status_counts["changed"],
        "modified_only_member_count": status_counts["modified_only_removed_from_official"],
        "official_only_member_count": status_counts["official_only_added_in_official"],
        "same_member_name_set": set(modified_map) == set(official_map),
        "all_common_offsets_equal": all(not row["data_offset_changed"] for row in rows if row["status"] in {"identical", "changed"}),
        "all_common_sizes_equal": all(not row["size_changed"] for row in rows if row["status"] in {"identical", "changed"}),
        "pack00_02_expected_modified_sha1_verified": pair_id != "PACK00_02" or modified_sha1 == EXPECTED_PACK00_02_MODIFIED_SHA1,
        "pack00_02_expected_official_sha1_verified": pair_id != "PACK00_02" or official_sha1 == EXPECTED_PACK00_02_OFFICIAL_SHA1,
    }
    return PairResult(pair_id, modified_path, official_path, modified_index, official_index, archive_row, rows, changed)


def iter_text_files(root: Path) -> Iterator[Path]:
    if not root.exists():
        return
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.is_symlink():
            continue
        if path.suffix.casefold() not in TEXT_SCAN_SUFFIXES:
            continue
        try:
            size = path.stat().st_size
        except OSError:
            continue
        if size > MAX_TEXT_FILE_SIZE:
            continue
        yield path


def path_scope(project_root: Path, path: Path) -> str:
    relative = path.relative_to(project_root).as_posix()
    if relative.startswith(".local/reports/quartet_legacy_dlc/"):
        return "report_metadata"
    if relative.startswith(".local/build/quartet_legacy_dlc/"):
        return "build_metadata"
    if relative.startswith("workstreams/quartet_legacy_dlc/"):
        return "workstream_source_or_docs"
    return "project_metadata"


def scan_references(project_root: Path, pair_results: list[PairResult]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    changed_by_key: dict[str, list[dict[str, Any]]] = defaultdict(list)
    archive_tokens: dict[str, dict[str, Any]] = {}
    pair_archive_rows = {result.pair_id: result.archive_row for result in pair_results}
    for result in pair_results:
        archive_tokens[result.archive_row["modified_sha1"]] = {"pair_id": result.pair_id, "token_type": "modified_archive_sha1"}
        archive_tokens[result.archive_row["official_sha1"]] = {"pair_id": result.pair_id, "token_type": "official_archive_sha1"}
        archive_tokens[result.archive_row["modified_sha256"]] = {"pair_id": result.pair_id, "token_type": "modified_archive_sha256"}
        archive_tokens[result.archive_row["official_sha256"]] = {"pair_id": result.pair_id, "token_type": "official_archive_sha256"}
        for row in result.changed_rows:
            changed_by_key[row["member_name"].casefold()].append(row)
            changed_by_key[Path(row["member_name"]).name.casefold()].append(row)
    reference_rows: list[dict[str, Any]] = []
    archive_reference_rows: list[dict[str, Any]] = []
    seen_member_hits: set[tuple[str, str, str]] = set()
    seen_archive_hits: set[tuple[str, str, str]] = set()

    def inspect_text(reference_name: str, scope: str, text: str) -> None:
        lower = text.casefold()
        lines = lower.splitlines()
        for token, rows in changed_by_key.items():
            matching_lines = [line for line in lines if token in line]
            if not matching_lines:
                continue
            joined = "\n".join(matching_lines)
            for changed in rows:
                marker = (reference_name, changed["pair_id"], changed["member_name"].casefold())
                if marker in seen_member_hits:
                    continue
                seen_member_hits.add(marker)
                archive_row = pair_archive_rows[changed["pair_id"]]
                modified_hash = str(changed["modified_payload_sha256"]).casefold()
                official_hash = str(changed["official_payload_sha256"]).casefold()
                if modified_hash and modified_hash in joined and modified_hash != official_hash:
                    interpretation = "confirmed_untrusted_modified_member_hash"
                elif official_hash and official_hash in joined:
                    interpretation = "confirmed_official_member_hash"
                elif archive_row["modified_sha1"] in lower or archive_row["modified_sha256"] in lower:
                    interpretation = "member_reference_with_confirmed_modified_archive"
                elif archive_row["official_sha1"] in lower or archive_row["official_sha256"] in lower:
                    interpretation = "member_reference_with_confirmed_official_archive"
                elif changed["status"] != "changed" or changed["size_changed"] or changed["data_offset_changed"]:
                    interpretation = "structural_member_reference_requires_review"
                else:
                    interpretation = "name_or_identity_metadata_only_no_payload_provenance"
                reference_rows.append({
                    "reference_file": reference_name,
                    "reference_scope": scope,
                    "pair_id": changed["pair_id"],
                    "member_name": changed["member_name"],
                    "member_status": changed["status"],
                    "relevance_class": changed["relevance_class"],
                    "match_kind": "full_path_or_basename_text_reference",
                    "provenance_interpretation": interpretation,
                    "matched_line_count": len(matching_lines),
                })
        for token, metadata in archive_tokens.items():
            if token.casefold() not in lower:
                continue
            marker = (reference_name, metadata["pair_id"], metadata["token_type"])
            if marker in seen_archive_hits:
                continue
            seen_archive_hits.add(marker)
            archive_reference_rows.append({
                "reference_file": reference_name,
                "reference_scope": scope,
                "pair_id": metadata["pair_id"],
                "token_type": metadata["token_type"],
                "token_sha": token,
                "provenance_interpretation": "confirmed_modified_archive_provenance" if metadata["token_type"].startswith("modified") else "confirmed_official_archive_provenance",
            })

    scan_roots = [
        project_root / "workstreams/quartet_legacy_dlc",
        project_root / ".local/reports/quartet_legacy_dlc",
        project_root / ".local/build/quartet_legacy_dlc",
    ]
    for root in scan_roots:
        for path in iter_text_files(root):
            try:
                text = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            inspect_text(path.relative_to(project_root).as_posix(), path_scope(project_root, path), text)

    report_parent = project_root / ".local/reports/quartet_legacy_dlc"
    if report_parent.is_dir():
        with tempfile.TemporaryDirectory(prefix="br-dlc-provenance-bundles-") as temp_name:
            temp = Path(temp_name)
            for archive in sorted(report_parent.glob("*.tar.zst")):
                destination = temp / archive.name.replace(".tar.zst", "")
                destination.mkdir()
                result = subprocess.run(
                    ["tar", "--zstd", "-xf", str(archive), "-C", str(destination)],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                )
                if result.returncode != 0:
                    raise Br1SourceProvenanceError(f"cannot inspect report bundle {archive}: {result.stderr.strip()}")
                for path in iter_text_files(destination):
                    try:
                        text = path.read_text(encoding="utf-8", errors="replace")
                    except OSError:
                        continue
                    inner = path.relative_to(destination).as_posix()
                    inspect_text(
                        f"{archive.relative_to(project_root).as_posix()}::{inner}",
                        "report_bundle_metadata",
                        text,
                    )
    return reference_rows, archive_reference_rows


def scan_extracted_payloads(project_root: Path, changed_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    build_root = project_root / ".local/build/quartet_legacy_dlc"
    if not build_root.is_dir():
        return []
    by_basename: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in changed_rows:
        by_basename[Path(row["member_name"]).name.casefold()].append(row)
    output: list[dict[str, Any]] = []
    for path in sorted(build_root.rglob("*")):
        if not path.is_file() or path.is_symlink() or path.suffix.casefold() == ".pak":
            continue
        matches = by_basename.get(path.name.casefold(), [])
        if not matches:
            continue
        digest = sha256_file(path)
        for changed in matches:
            if digest == changed["modified_payload_sha256"] and digest != changed["official_payload_sha256"]:
                provenance = "matches_untrusted_modified_member"
                action = "rebuild_from_official_member"
            elif digest == changed["official_payload_sha256"]:
                provenance = "matches_official_member"
                action = "retain"
            elif digest == changed["modified_payload_sha256"] == changed["official_payload_sha256"]:
                provenance = "matches_both_identical_member"
                action = "retain"
            else:
                provenance = "does_not_match_either_compared_member"
                action = "manual_provenance_review"
            output.append({
                "local_payload": path.relative_to(project_root).as_posix(),
                "local_size": path.stat().st_size,
                "local_sha256": digest,
                "pair_id": changed["pair_id"],
                "member_name": changed["member_name"],
                "modified_payload_sha256": changed["modified_payload_sha256"],
                "official_payload_sha256": changed["official_payload_sha256"],
                "provenance": provenance,
                "required_action": action,
            })
    return output


def build_rebuild_plan(
    changed_rows: list[dict[str, Any]],
    member_references: list[dict[str, Any]],
    archive_references: list[dict[str, Any]],
    extracted_payloads: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    modified_archive_files = {
        row["reference_file"] for row in archive_references
        if row["provenance_interpretation"] == "confirmed_modified_archive_provenance"
    }
    member_ref_map: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in member_references:
        member_ref_map[(row["pair_id"], row["member_name"])].append(row)
    payload_map: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in extracted_payloads:
        payload_map[(row["pair_id"], row["member_name"])].append(row)
    for changed in changed_rows:
        key = (changed["pair_id"], changed["member_name"])
        refs = member_ref_map.get(key, [])
        payloads = payload_map.get(key, [])
        dependency_scopes = {"report_metadata", "report_bundle_metadata", "build_metadata"}
        dependent_refs = [row for row in refs if row["reference_scope"] in dependency_scopes]
        dependent_files = sorted({row["reference_file"] for row in dependent_refs})
        confirmed_old_files = sorted({
            row["reference_file"] for row in dependent_refs
            if row["provenance_interpretation"] in {
                "confirmed_untrusted_modified_member_hash",
                "member_reference_with_confirmed_modified_archive",
            }
        } | (set(dependent_files) & modified_archive_files))
        confirmed_official_files = sorted({
            row["reference_file"] for row in dependent_refs
            if row["provenance_interpretation"] in {
                "confirmed_official_member_hash",
                "member_reference_with_confirmed_official_archive",
            }
        })
        structural_review_files = sorted({
            row["reference_file"] for row in dependent_refs
            if row["provenance_interpretation"] == "structural_member_reference_requires_review"
        })
        old_payloads = sorted(row["local_payload"] for row in payloads if row["provenance"] == "matches_untrusted_modified_member")
        if old_payloads or confirmed_old_files:
            action = "rebuild_only_listed_dependencies_from_official_member"
            priority = "required"
        elif structural_review_files:
            action = "review_structural_inventory_dependency_then_rebuild_if_based_on_old_archive"
            priority = "conditional"
        elif confirmed_official_files:
            action = "retain_confirmed_official_dependencies"
            priority = "none"
        elif dependent_files:
            action = "retain_name_or_identity_only_metadata_no_payload_dependency_proven"
            priority = "none"
        else:
            action = "no_workstream_dependency_found"
            priority = "none"
        rows.append({
            "pair_id": changed["pair_id"],
            "member_name": changed["member_name"],
            "member_status": changed["status"],
            "relevance_class": changed["relevance_class"],
            "dependent_metadata_files": ";".join(dependent_files),
            "confirmed_old_provenance_files": ";".join(confirmed_old_files),
            "confirmed_official_provenance_files": ";".join(confirmed_official_files),
            "structural_review_files": ";".join(structural_review_files),
            "old_modified_payloads": ";".join(old_payloads),
            "required_action": action,
            "priority": priority,
            "canonical_source_role": "official_no_trailing_underscore",
            "modified_source_role": "untrusted_modified_candidate_research_only",
        })
    return rows


def critical_payload_impact(pair_results: list[PairResult], project_root: Path) -> list[dict[str, Any]]:
    all_rows = [row for result in pair_results for row in result.member_rows]
    by_name = {(row["pair_id"], row["member_name"].casefold()): row for row in all_rows}
    output: list[dict[str, Any]] = []
    for member in sorted(CURRENT_DRY_BKN_MEMBERS):
        row = by_name.get(("PACK00_02", member.casefold()))
        if row is None:
            output.append({
                "content_id": "costume_pc00_bkn",
                "member_name": member,
                "pair_id": "PACK00_02",
                "comparison_status": "missing_from_comparison",
                "current_payload_affected": True,
                "required_action": "block_and_investigate_missing_member",
            })
            continue
        output.append({
            "content_id": "costume_pc00_bkn",
            "member_name": member,
            "pair_id": "PACK00_02",
            "comparison_status": row["status"],
            "modified_payload_sha256": row["modified_payload_sha256"],
            "official_payload_sha256": row["official_payload_sha256"],
            "current_payload_affected": row["status"] != "identical",
            "required_action": "rebuild_current_dry_candidate" if row["status"] != "identical" else "retain_current_dry_candidate_payload",
        })
    return output


def audit(project_root: Path, br1_root: Path, output_root: Path) -> tuple[Path, dict[str, Any]]:
    project_root = project_root.resolve()
    br1_root = br1_root.resolve()
    output_root = output_root.resolve()
    if output_root.exists():
        shutil.rmtree(output_root)
    output_root.mkdir(parents=True)
    pair_results: list[PairResult] = []
    for pair_id, modified_relative, official_relative in PAIR_SPECS:
        modified = br1_root / modified_relative
        official = br1_root / official_relative
        if not modified.is_file():
            raise Br1SourceProvenanceError(f"missing preserved modified archive: {modified}")
        if not official.is_file():
            raise Br1SourceProvenanceError(f"missing official archive: {official}")
        print(f"[stage58] comparing {pair_id}: {modified.name} -> {official.name}", flush=True)
        result = compare_pair(pair_id, modified, official)
        pair_results.append(result)
        print(
            f"[stage58] {pair_id}: identical={result.archive_row['identical_member_count']} "
            f"changed={result.archive_row['changed_member_count']} "
            f"modified_only={result.archive_row['modified_only_member_count']} "
            f"official_only={result.archive_row['official_only_member_count']}",
            flush=True,
        )

    archive_rows = [result.archive_row for result in pair_results]
    member_rows = [row for result in pair_results for row in result.member_rows]
    changed_rows = [row for result in pair_results for row in result.changed_rows]
    reference_rows, archive_reference_rows = scan_references(project_root, pair_results)
    extracted_payload_rows = scan_extracted_payloads(project_root, changed_rows)
    rebuild_rows = build_rebuild_plan(changed_rows, reference_rows, archive_reference_rows, extracted_payload_rows)
    critical_rows = critical_payload_impact(pair_results, project_root)

    known_pack02_changed = [row for row in changed_rows if row["pair_id"] == "PACK00_02"]
    known_dlc_found = {
        Path(row["member_name"].casefold()).name for row in known_pack02_changed
        if Path(row["member_name"].casefold()).name in KNOWN_PACK00_02_DLC_CHANGED_BASENAMES
    }
    missing_reported = sorted(KNOWN_PACK00_02_DLC_CHANGED_BASENAMES - known_dlc_found)
    gaps: list[dict[str, Any]] = []
    if missing_reported:
        gaps.append({
            "gap_id": "reported_pack00_02_dlc_member_not_changed_in_local_pair",
            "severity": "blocking_provenance_discrepancy",
            "details": ";".join(missing_reported),
            "required_action": "verify local archive pair and names",
        })
    unresolved_refs = [row for row in rebuild_rows if row["priority"] == "conditional"]
    if unresolved_refs:
        gaps.append({
            "gap_id": "member_reference_without_confirmed_archive_hash",
            "severity": "conditional_rebuild_review",
            "details": str(len(unresolved_refs)),
            "required_action": "use report manifests and local payload hashes before selective regeneration",
        })
    if not gaps:
        gaps.append({
            "gap_id": "none_for_member_diff",
            "severity": "none",
            "details": "all four pairs were compared and all reported PACK00_02 DLC changes were resolved",
            "required_action": "follow selective rebuild plan only",
        })

    write_tsv(output_root / "DLC_BR1_SOURCE_ARCHIVE_PROVENANCE.tsv", archive_rows[0].keys(), archive_rows)
    write_tsv(output_root / "DLC_BR1_SOURCE_MEMBER_AUDIT.tsv", member_rows[0].keys(), member_rows)
    write_tsv(output_root / "DLC_BR1_CHANGED_MEMBER_CLASSIFICATION.tsv", changed_rows[0].keys() if changed_rows else ["pair_id", "member_name", "status"], changed_rows)
    write_tsv(output_root / "DLC_BR1_WORKSTREAM_MEMBER_REFERENCES.tsv", (
        reference_rows[0].keys() if reference_rows else [
            "reference_file", "reference_scope", "pair_id", "member_name", "member_status",
            "relevance_class", "match_kind", "provenance_interpretation",
        ]
    ), reference_rows)
    write_tsv(output_root / "DLC_BR1_WORKSTREAM_ARCHIVE_HASH_REFERENCES.tsv", (
        archive_reference_rows[0].keys() if archive_reference_rows else [
            "reference_file", "reference_scope", "pair_id", "token_type", "token_sha", "provenance_interpretation",
        ]
    ), archive_reference_rows)
    write_tsv(output_root / "DLC_BR1_EXTRACTED_PAYLOAD_PROVENANCE.tsv", (
        extracted_payload_rows[0].keys() if extracted_payload_rows else [
            "local_payload", "local_size", "local_sha256", "pair_id", "member_name",
            "modified_payload_sha256", "official_payload_sha256", "provenance", "required_action",
        ]
    ), extracted_payload_rows)
    write_tsv(output_root / "DLC_BR1_SELECTIVE_REBUILD_PLAN.tsv", rebuild_rows[0].keys() if rebuild_rows else ["pair_id", "member_name", "required_action"], rebuild_rows)
    write_tsv(output_root / "DLC_BR1_CURRENT_DRY_BKN_IMPACT.tsv", critical_rows[0].keys(), critical_rows)
    write_tsv(output_root / "DLC_BR1_SOURCE_PROVENANCE_GAPS.tsv", gaps[0].keys(), gaps)

    status_counts = Counter(row["status"] for row in member_rows)
    relevance_counts = Counter(row["relevance_class"] for row in changed_rows)
    required_rebuild = [row for row in rebuild_rows if row["priority"] == "required"]
    conditional_rebuild = [row for row in rebuild_rows if row["priority"] == "conditional"]
    current_dry_affected = any(row["current_payload_affected"] for row in critical_rows)
    summary = {
        "type": "br_quartet_legacy_dlc_br1_source_provenance_summary",
        "format_version": FORMAT_VERSION,
        "tool_version": TOOL_VERSION,
        "status": "member_level_source_provenance_audited_selective_rebuild_plan_ready_no_game_writes",
        "archive_pair_count": len(pair_results),
        "member_rows": len(member_rows),
        "identical_members": status_counts["identical"],
        "changed_members": status_counts["changed"],
        "modified_only_members": status_counts["modified_only_removed_from_official"],
        "official_only_members": status_counts["official_only_added_in_official"],
        "changed_by_relevance": dict(sorted(relevance_counts.items())),
        "pack00_02_changed_members": len(known_pack02_changed),
        "pack00_02_user_reported_dlc_changed_members_verified": len(known_dlc_found),
        "pack00_02_user_reported_dlc_changed_members_missing": missing_reported,
        "workstream_member_reference_hits": len(reference_rows),
        "workstream_archive_hash_reference_hits": len(archive_reference_rows),
        "extracted_payload_provenance_rows": len(extracted_payload_rows),
        "required_selective_rebuild_rows": len(required_rebuild),
        "conditional_selective_rebuild_rows": len(conditional_rebuild),
        "current_dry_bkn_payload_affected": current_dry_affected,
        "findings": [
            "ordinary archive names without a trailing underscore are treated as canonical user-designated Steam sources",
            "underscore archives are retained only as untrusted_modified_candidate comparison sources",
            "member identity, decoded payload, size and offset changes are reported separately for all four archive pairs",
            "only changed members and metadata/build outputs that reference them are eligible for selective rebuild",
            "no prior text, routing or unrelated asset audit is invalidated merely because an archive-level hash changed",
        ],
        "next_action": "review the changed-member and selective-rebuild tables; regenerate only rows proven or conditionally shown to depend on an untrusted modified member",
        "policy": {
            "game_modified": False,
            "source_archives_modified": False,
            "git_modified": False,
            "translation_modified": False,
            "restoration_modified": False,
            "profile_build_allowed": False,
            "candidate_installed": False,
            "runtime_validated": False,
            "raw_assets_exported_in_report": False,
            "official_no_underscore_source_required": True,
            "underscore_source_canonical_allowed": False,
            "selective_rebuild_only": True,
        },
    }
    write_json(output_root / "SUMMARY.json", summary)
    write_json(output_root / "REPORT_MANIFEST.json", {"type": "br_report_manifest", "format_version": 1, "files": report_manifest(output_root)})
    report_parent = project_root / ".local/reports/quartet_legacy_dlc"
    archive = report_parent / REPORT_ARCHIVE_NAME
    make_archive(output_root, archive)
    print(f"[stage58] changed members: {len(changed_rows)}", flush=True)
    print(f"[stage58] report: {archive}", flush=True)
    return archive, summary


def validate_report(report_root: Path) -> dict[str, Any]:
    report_root = report_root.resolve()
    required = (
        "DLC_BR1_SOURCE_ARCHIVE_PROVENANCE.tsv",
        "DLC_BR1_SOURCE_MEMBER_AUDIT.tsv",
        "DLC_BR1_CHANGED_MEMBER_CLASSIFICATION.tsv",
        "DLC_BR1_WORKSTREAM_MEMBER_REFERENCES.tsv",
        "DLC_BR1_WORKSTREAM_ARCHIVE_HASH_REFERENCES.tsv",
        "DLC_BR1_EXTRACTED_PAYLOAD_PROVENANCE.tsv",
        "DLC_BR1_SELECTIVE_REBUILD_PLAN.tsv",
        "DLC_BR1_CURRENT_DRY_BKN_IMPACT.tsv",
        "DLC_BR1_SOURCE_PROVENANCE_GAPS.tsv",
        "SUMMARY.json",
        "REPORT_MANIFEST.json",
    )
    for name in required:
        if not (report_root / name).is_file():
            raise Br1SourceProvenanceError(f"missing report file: {name}")
    summary = json.loads((report_root / "SUMMARY.json").read_text(encoding="utf-8"))
    if summary.get("type") != "br_quartet_legacy_dlc_br1_source_provenance_summary" or summary.get("tool_version") != TOOL_VERSION:
        raise Br1SourceProvenanceError("invalid provenance summary")
    if summary.get("status") != "member_level_source_provenance_audited_selective_rebuild_plan_ready_no_game_writes":
        raise Br1SourceProvenanceError("unexpected provenance status")
    if summary.get("archive_pair_count") != 4:
        raise Br1SourceProvenanceError("not all four archive pairs were audited")
    archive_rows = read_tsv(report_root / "DLC_BR1_SOURCE_ARCHIVE_PROVENANCE.tsv")
    if len(archive_rows) != 4 or {row["pair_id"] for row in archive_rows} != {item[0] for item in PAIR_SPECS}:
        raise Br1SourceProvenanceError("archive provenance pair set is incomplete")
    pack02 = next(row for row in archive_rows if row["pair_id"] == "PACK00_02")
    if pack02["modified_sha1"] != EXPECTED_PACK00_02_MODIFIED_SHA1 or pack02["official_sha1"] != EXPECTED_PACK00_02_OFFICIAL_SHA1:
        raise Br1SourceProvenanceError("PACK00_02 provenance hashes are not the required pair")
    members = read_tsv(report_root / "DLC_BR1_SOURCE_MEMBER_AUDIT.tsv")
    changed = read_tsv(report_root / "DLC_BR1_CHANGED_MEMBER_CLASSIFICATION.tsv")
    if len(members) != int(summary.get("member_rows", -1)) or len(changed) != (
        int(summary.get("changed_members", 0)) + int(summary.get("modified_only_members", 0)) + int(summary.get("official_only_members", 0))
    ):
        raise Br1SourceProvenanceError("member counts do not match summary")
    if any(row.get("status") == "identical" for row in changed):
        raise Br1SourceProvenanceError("changed-member table contains an identical member")
    policy = summary.get("policy", {})
    false_keys = (
        "game_modified", "source_archives_modified", "git_modified", "translation_modified",
        "restoration_modified", "profile_build_allowed", "candidate_installed", "runtime_validated",
        "raw_assets_exported_in_report", "underscore_source_canonical_allowed",
    )
    if any(policy.get(key) is not False for key in false_keys):
        raise Br1SourceProvenanceError("provenance report violates fail-closed policy")
    if policy.get("official_no_underscore_source_required") is not True or policy.get("selective_rebuild_only") is not True:
        raise Br1SourceProvenanceError("canonical-source or selective-rebuild policy is missing")
    manifest = json.loads((report_root / "REPORT_MANIFEST.json").read_text(encoding="utf-8"))
    for row in manifest.get("files", []):
        path = report_root / row["path"]
        if not path.is_file() or path.stat().st_size != row["size"] or sha256_file(path) != row["sha256"]:
            raise Br1SourceProvenanceError(f"report manifest mismatch: {row.get('path')}")
        if {suffix.casefold() for suffix in path.suffixes} & FORBIDDEN_REPORT_SUFFIXES:
            raise Br1SourceProvenanceError(f"raw asset in report: {path}")
    return summary


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    audit_parser = sub.add_parser("audit")
    audit_parser.add_argument("--project-root", type=Path, required=True)
    audit_parser.add_argument("--br1-root", type=Path, required=True)
    audit_parser.add_argument("--output-root", type=Path)
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
            audit(project, args.br1_root, output)
        elif args.command == "validate-report":
            print(json.dumps(validate_report(args.report_root), ensure_ascii=False, sort_keys=True))
        elif args.command == "bundle-report":
            validate_report(args.report_root)
            make_archive(args.report_root.resolve(), args.output.resolve())
        else:
            raise Br1SourceProvenanceError("unsupported command")
    except (Br1SourceProvenanceError, NESTED.NestedContainerError, OSError, subprocess.TimeoutExpired) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
