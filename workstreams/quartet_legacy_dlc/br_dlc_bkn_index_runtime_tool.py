#!/usr/bin/env python3
"""Read-only BKN index-enumeration and runtime-module binding audit.

This stage validates the stage-31 BKN table/UI report, proves whether the full
PC00-PC14 BKN dry/wet index blocks remain stable across BR1 and Quartet, and
searches bounded executable modules for exact technical tokens or complete
integer sequences that could implement costume enumeration.

No table, binary, translation record, PAK, profile, registry, Git state, or game
installation is modified. Runtime-module payloads and XML text are never
exported; only hashes, offsets, structural indices, and classifications appear
in the report.
"""
from __future__ import annotations
import os

import argparse
import csv
import hashlib
import json
import re
import shutil
import struct
import subprocess
import sys
import tarfile
import tempfile
import xml.etree.ElementTree as ET
from collections import Counter
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT_DEFAULT = SCRIPT_DIR.parent.parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import br_dlc_bkn_activation_ui_tool as STAGE31  # noqa: E402

TOOL_VERSION = "0.0.15"
FORMAT_VERSION = 1
REPORT_DIR_NAME = "bkn_index_runtime_evidence"
REPORT_ARCHIVE_NAME = "BR_quartet_legacy_dlc_bkn_index_runtime_evidence.tar.zst"

SOURCE_TABLE_ROOT = STAGE31.SOURCE_TABLE_ROOT
TARGET_TABLE_ROOT = STAGE31.TARGET_TABLE_ROOT
SOURCE_TEXT = STAGE31.SOURCE_TEXT
TARGET_TEXT = STAGE31.TARGET_TEXT

BKN_TAGS = tuple(f"PC{pc:02d}_DLC_BKN{suffix}" for pc in range(15) for suffix in ("", "_W"))
BKN_DRY_TAGS = tuple(f"PC{pc:02d}_DLC_BKN" for pc in range(15))
BKN_WET_TAGS = tuple(f"PC{pc:02d}_DLC_BKN_W" for pc in range(15))
SCL_DRY_TAGS = tuple(f"PC{pc:02d}_SCL" for pc in range(15))
SCL_WET_TAGS = tuple(f"PC{pc:02d}_SCL_W" for pc in range(15))

TABLE_SPECS = (
    ("chara/chara.xml", "Chara", "BaseTag"),
    ("chara/chara_no.xml", "Chara", "BaseTag"),
    ("chara/charabase.xml", "CharaBase", "BaseTag"),
)
NON_ENUMERATION_TABLES = (
    "costume/costume.xml",
    "costume/coschangechara.xml",
    "ez_eff_player/costume_change.xml",
)

EXACT_RUNTIME_TOKENS = (
    "PC00_DLC_BKN",
    "PC00_DLC_BKN_W",
    "PC00_DLC_TWL",
    "PC00_DLC_TWL_W",
    "PC00_SCL",
    "PC00_SCL_W",
    "str_costume",
    "costume_change",
)
GENERIC_ENTITLEMENT_TOKENS = (
    "BIsDlcInstalled",
    "IsDlcInstalled",
    "SteamApps",
    "DLC",
    "entitlement",
    "downloadable content",
)
MODULE_SUFFIXES = {".exe", ".dll"}
MAX_MODULE_SIZE = 512 * 1024 * 1024
FORBIDDEN_REPORT_SUFFIXES = {
    ".pak", ".ebm", ".ebd", ".g1m", ".g1t", ".g1a", ".g1e", ".g1s",
    ".elixir", ".gz", ".bin", ".swg", ".dds", ".wav", ".ogg", ".exe", ".dll",
}


class BknIndexRuntimeError(RuntimeError):
    pass


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


def clean_dir(path: Path) -> None:
    if path.exists():
        shutil.rmtree(path)
    path.mkdir(parents=True, exist_ok=True)


def decode_xml(path: Path) -> str:
    raw = path.read_bytes()
    if raw.startswith(b"\xef\xbb\xbf"):
        return raw.decode("utf-8-sig")
    if raw.startswith((b"\xff\xfe", b"\xfe\xff")):
        return raw.decode("utf-16")
    declaration = re.search(br"encoding=[\"']([^\"']+)", raw[:256], re.I)
    declared = declaration.group(1).decode("ascii", "replace") if declaration else "utf-8"
    aliases = {
        "SHIFT-JIS": "cp932", "Shift_JIS": "cp932", "shift-jis": "cp932",
        "UTF-8": "utf-8", "utf-8": "utf-8",
    }
    candidates = [aliases.get(declared, declared), "cp932", "utf-8"]
    errors: list[str] = []
    for encoding in dict.fromkeys(candidates):
        try:
            return raw.decode(encoding)
        except (UnicodeDecodeError, LookupError) as exc:
            errors.append(f"{encoding}: {exc}")
    raise BknIndexRuntimeError(f"unable to decode XML {path}: {'; '.join(errors)}")


def parse_xml(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        raise BknIndexRuntimeError(f"missing workspace XML: {path}")
    text = re.sub(r"<\?xml[^>]*\?>", "", decode_xml(path), count=1, flags=re.I)
    try:
        root = ET.fromstring(text)
    except ET.ParseError as exc:
        raise BknIndexRuntimeError(f"failed to parse XML {path}: {exc}") from exc
    rows: list[dict[str, Any]] = []
    for index, element in enumerate(list(root)):
        attrs = {str(k): str(v) for k, v in element.attrib.items()}
        canonical = json.dumps({"element": element.tag, "attrs": attrs}, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        rows.append({
            "index": index,
            "element": str(element.tag),
            "attrs": attrs,
            "record_sha256": sha256_bytes(canonical.encode("utf-8")),
        })
    return rows


def selected_by_attr(rows: Sequence[Mapping[str, Any]], field: str, wanted: Sequence[str]) -> dict[str, Mapping[str, Any]]:
    wanted_set = set(wanted)
    buckets: dict[str, list[Mapping[str, Any]]] = {value: [] for value in wanted_set}
    for row in rows:
        value = str(row["attrs"].get(field, ""))
        if value in buckets:
            buckets[value].append(row)
    result: dict[str, Mapping[str, Any]] = {}
    for value, matches in buckets.items():
        if len(matches) != 1:
            raise BknIndexRuntimeError(f"expected exactly one {field}={value}, found {len(matches)}")
        result[value] = matches[0]
    return result


def expected_fallback(tag: str) -> str:
    match = re.fullmatch(r"PC(\d{2})_DLC_BKN(_W)?", tag)
    if not match:
        raise BknIndexRuntimeError(f"not a BKN tag: {tag}")
    return f"PC{match.group(1)}_SCL{match.group(2) or ''}"


def expected_model(tag: str, family: str) -> str:
    match = re.fullmatch(r"PC(\d{2})_(?:DLC_BKN|SCL)(_W)?", tag)
    if not match:
        raise BknIndexRuntimeError(f"unsupported model tag: {tag}")
    pc = match.group(1)
    wet = match.group(2) or ""
    suffix = "Bkn" if family == "bkn" else "Scl"
    return f"PC{pc}/PC{pc}_{'DLC_' if family == 'bkn' else ''}{suffix}{wet}"


def audit_index_tables(project_root: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, list[int]]]:
    index_rows: list[dict[str, Any]] = []
    fallback_rows: list[dict[str, Any]] = []
    sequences: dict[str, list[int]] = {}
    for relative, element_name, key_field in TABLE_SPECS:
        source_rows = parse_xml(project_root / SOURCE_TABLE_ROOT / relative)
        target_rows = parse_xml(project_root / TARGET_TABLE_ROOT / relative)
        source_index = selected_by_attr(source_rows, key_field, BKN_TAGS)
        target_index = selected_by_attr(target_rows, key_field, BKN_TAGS)
        for family_name, tags in (("dry", BKN_DRY_TAGS), ("wet", BKN_WET_TAGS)):
            source_values: list[int] = []
            target_values: list[int] = []
            for tag in tags:
                source = source_index.get(tag)
                target = target_index.get(tag)
                if source is None or target is None:
                    raise BknIndexRuntimeError(f"missing {tag} in {relative}")
                same_index = int(source["index"]) == int(target["index"])
                same_record = source["record_sha256"] == target["record_sha256"]
                index_rows.append({
                    "table_path": relative,
                    "element": element_name,
                    "base_tag": tag,
                    "variant": family_name,
                    "source_index": source["index"],
                    "target_index": target["index"],
                    "index_preserved": same_index,
                    "source_record_sha256": source["record_sha256"],
                    "target_record_sha256": target["record_sha256"],
                    "record_identical": same_record,
                    "raw_record_exported": False,
                })
                source_values.append(int(source["index"]))
                target_values.append(int(target["index"]))
                if relative == "chara/charabase.xml":
                    fallback_tag = expected_fallback(tag)
                    expected_target = expected_model(fallback_tag, "scl")
                    source_attrs = source["attrs"]
                    target_attrs = target["attrs"]
                    target_fields = {
                        "Model": target_attrs.get("Model", ""),
                        "defaultTexture": target_attrs.get("defaultTexture", ""),
                    }
                    redirects = all(value == expected_target for value in target_fields.values())
                    changed_fields = sorted(k for k in set(source_attrs) | set(target_attrs) if source_attrs.get(k, "") != target_attrs.get(k, ""))
                    preserved_target_fields = sorted(k for k in target_attrs if k not in {"Model", "defaultTexture"} and source_attrs.get(k, "") != target_attrs.get(k, ""))
                    fallback_rows.append({
                        "base_tag": tag,
                        "pc_slot": tag[2:4],
                        "variant": family_name,
                        "source_index": source["index"],
                        "target_index": target["index"],
                        "source_model": source_attrs.get("Model", ""),
                        "source_default_texture": source_attrs.get("defaultTexture", ""),
                        "target_model": target_attrs.get("Model", ""),
                        "target_default_texture": target_attrs.get("defaultTexture", ""),
                        "expected_fallback_tag": fallback_tag,
                        "expected_fallback_model": expected_target,
                        "redirects_to_expected_scl_fallback": redirects,
                        "changed_fields": changed_fields,
                        "target_only_or_remaster_fields_to_preserve": preserved_target_fields,
                        "classification": "present_but_disabled_via_scl_fallback" if redirects else "unexpected_target_mapping",
                        "profile_build_allowed": False,
                    })
            sequences[f"{relative}:bkn_{family_name}:source"] = source_values
            sequences[f"{relative}:bkn_{family_name}:target"] = target_values
            if source_values != target_values:
                raise BknIndexRuntimeError(f"BKN {family_name} sequence drift in {relative}")
            expected_step = 2
            if any(b - a != expected_step for a, b in zip(source_values, source_values[1:])):
                raise BknIndexRuntimeError(f"BKN {family_name} sequence is not a stable +2 block in {relative}")
    return index_rows, fallback_rows, sequences


def audit_non_enumeration_tables(project_root: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for relative in NON_ENUMERATION_TABLES:
        for side, root in (("source", SOURCE_TABLE_ROOT), ("target", TARGET_TABLE_ROOT)):
            records = parse_xml(project_root / root / relative)
            direct = []
            generic_pc = []
            for record in records:
                values = list(record["attrs"].values())
                if any(any(tag.casefold() in value.casefold() for value in values) for tag in BKN_TAGS):
                    direct.append(record["index"])
                if any("PC00" in value.upper() or "CHARA_AKO" in value.upper() for value in values):
                    generic_pc.append(record["index"])
            rows.append({
                "side": side,
                "table_path": relative,
                "record_count": len(records),
                "direct_bkn_reference_count": len(direct),
                "direct_bkn_record_indices": direct,
                "pc00_or_ako_reference_count": len(generic_pc),
                "classification": "not_bkn_costume_enumeration_table" if not direct else "contains_direct_bkn_reference",
                "raw_record_exported": False,
            })
    return rows


def audit_text_structure(project_root: Path) -> list[dict[str, Any]]:
    source = parse_xml(project_root / SOURCE_TEXT)
    target = parse_xml(project_root / TARGET_TEXT)
    rows: list[dict[str, Any]] = []
    for index in range(max(len(source), len(target))):
        s = source[index] if index < len(source) else None
        t = target[index] if index < len(target) else None
        s_attrs = s["attrs"] if s else {}
        t_attrs = t["attrs"] if t else {}
        s_no = s_attrs.get("String_No", "")
        t_no = t_attrs.get("String_No", "")
        s_text = s_attrs.get("Text", "")
        t_text = t_attrs.get("Text", "")
        rows.append({
            "record_index": index,
            "source_string_no": s_no,
            "target_string_no": t_no,
            "string_no_aligned": bool(s and t and s_no == t_no),
            "source_text_sha256": sha256_bytes(s_text.encode("utf-8")) if s else "",
            "target_text_sha256": sha256_bytes(t_text.encode("utf-8")) if t else "",
            "target_is_placeholder": t_text == "-",
            "source_record_present": s is not None,
            "target_record_present": t is not None,
            "direct_bkn_identifier_present": any(token.casefold() in value.casefold() for token in BKN_TAGS for value in (s_text, t_text, s_no, t_no)),
            "binding_status": "identifier_absent_structure_only" if not any(token.casefold() in value.casefold() for token in BKN_TAGS for value in (s_text, t_text, s_no, t_no)) else "direct_identifier_present",
            "translation_owned": True,
            "raw_text_exported": False,
        })
    return rows


def discover_modules(game_root: Path, side: str) -> list[dict[str, Any]]:
    if not game_root.is_dir():
        return []
    candidates: dict[Path, str] = {}
    for path in sorted(game_root.iterdir(), key=lambda p: p.name.casefold()):
        if path.is_file() and path.suffix.casefold() in MODULE_SUFFIXES:
            candidates[path] = "game_root_module"
    for dirname in ("bin", "Bin", "x64", "Binaries", "binaries"):
        base = game_root / dirname
        if not base.is_dir():
            continue
        for path in sorted(base.rglob("*"), key=lambda p: str(p).casefold()):
            if path.is_file() and path.suffix.casefold() in MODULE_SUFFIXES:
                candidates.setdefault(path, f"{dirname}_module")
    rows = []
    for path, reason in sorted(candidates.items(), key=lambda kv: str(kv[0]).casefold()):
        size = path.stat().st_size
        if size <= 0 or size > MAX_MODULE_SIZE:
            rows.append({
                "side": side,
                "absolute_path": str(path),
                "relative_path": str(path.relative_to(game_root)),
                "size": size,
                "sha256": "",
                "selection_reason": reason,
                "scan_status": "skipped_size_limit",
            })
            continue
        rows.append({
            "side": side,
            "absolute_path": str(path),
            "relative_path": str(path.relative_to(game_root)),
            "size": size,
            "sha256": sha256_file(path),
            "selection_reason": reason,
            "scan_status": "selected",
        })
    return rows


def all_offsets(data: bytes, needle: bytes, *, limit: int = 4096) -> list[int]:
    if not needle:
        return []
    offsets: list[int] = []
    start = 0
    while len(offsets) < limit:
        found = data.find(needle, start)
        if found < 0:
            break
        offsets.append(found)
        start = found + 1
    return offsets


def token_patterns(token: str) -> tuple[tuple[str, bytes], ...]:
    return (
        ("ascii", token.encode("ascii", "ignore")),
        ("utf16le", token.encode("utf-16le")),
    )


def sequence_patterns(values: Sequence[int]) -> tuple[tuple[str, bytes], ...]:
    if not values:
        return ()
    patterns: list[tuple[str, bytes]] = []
    if all(0 <= value <= 0xFFFF for value in values):
        patterns.append(("u16le", b"".join(struct.pack("<H", value) for value in values)))
    patterns.append(("u32le", b"".join(struct.pack("<I", value) for value in values)))
    return tuple(patterns)


def scan_modules(module_rows: list[dict[str, Any]], sequences: Mapping[str, Sequence[int]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    audited: list[dict[str, Any]] = []
    token_hits: list[dict[str, Any]] = []
    sequence_hits: list[dict[str, Any]] = []
    unique_sequences: dict[tuple[int, ...], list[str]] = {}
    for sequence_id, values in sequences.items():
        unique_sequences.setdefault(tuple(values), []).append(sequence_id)
    for module in module_rows:
        row = dict(module)
        row.pop("absolute_path", None)
        row.update({
            "exact_runtime_token_hits": 0,
            "generic_entitlement_token_hits": 0,
            "complete_index_sequence_hits": 0,
            "raw_module_exported": False,
        })
        if module["scan_status"] != "selected":
            audited.append(row)
            continue
        path = Path(module["absolute_path"])
        data = path.read_bytes()
        for token_class, tokens in (("exact_runtime", EXACT_RUNTIME_TOKENS), ("generic_entitlement", GENERIC_ENTITLEMENT_TOKENS)):
            for token in tokens:
                for encoding, pattern in token_patterns(token):
                    for offset in all_offsets(data, pattern):
                        left = max(0, offset - 32)
                        right = min(len(data), offset + len(pattern) + 32)
                        token_hits.append({
                            "side": module["side"],
                            "module_path": module["relative_path"],
                            "module_sha256": module["sha256"],
                            "token_class": token_class,
                            "token": token,
                            "encoding": encoding,
                            "offset": offset,
                            "context_sha256": sha256_bytes(data[left:right]),
                            "raw_context_exported": False,
                        })
                        if token_class == "exact_runtime":
                            row["exact_runtime_token_hits"] += 1
                        else:
                            row["generic_entitlement_token_hits"] += 1
        for values, ids in unique_sequences.items():
            for width, pattern in sequence_patterns(values):
                for offset in all_offsets(data, pattern, limit=256):
                    sequence_hits.append({
                        "side": module["side"],
                        "module_path": module["relative_path"],
                        "module_sha256": module["sha256"],
                        "sequence_ids": sorted(ids),
                        "value_count": len(values),
                        "encoding": width,
                        "offset": offset,
                        "sequence_sha256": sha256_bytes(pattern),
                        "context_sha256": sha256_bytes(data[max(0, offset - 32):min(len(data), offset + len(pattern) + 32)]),
                        "raw_context_exported": False,
                    })
                    row["complete_index_sequence_hits"] += 1
        row["scan_status"] = "passed"
        audited.append(row)
    return audited, token_hits, sequence_hits


def create_manifest(report_dir: Path) -> None:
    files = []
    for path in sorted(report_dir.iterdir(), key=lambda p: p.name.casefold()):
        if not path.is_file() or path.name == "REPORT_MANIFEST.json":
            continue
        if path.suffix.casefold() in FORBIDDEN_REPORT_SUFFIXES:
            raise BknIndexRuntimeError(f"raw asset/module forbidden in report: {path.name}")
        files.append({"path": path.name, "size": path.stat().st_size, "sha256": sha256_file(path)})
    write_json(report_dir / "REPORT_MANIFEST.json", {
        "type": "br_report_manifest",
        "format_version": 1,
        "files": files,
    })


def create_archive(report_dir: Path, archive_path: Path) -> None:
    archive_path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="bkn_index_bundle_") as temp_name:
        staging = Path(temp_name) / REPORT_DIR_NAME
        shutil.copytree(report_dir, staging)
        subprocess.run([
            "tar", "--zstd", "--sort=name", "--mtime=@0", "--owner=0", "--group=0", "--numeric-owner",
            "-cf", str(archive_path), "-C", str(staging.parent), staging.name,
        ], check=True)


def prerequisite_dir(project_root: Path) -> Path:
    path = project_root / ".local/reports/quartet_legacy_dlc" / STAGE31.REPORT_DIR_NAME
    if not path.is_dir():
        raise BknIndexRuntimeError(f"missing stage-31 report directory: {path}")
    summary = STAGE31.validate_report(path)
    if summary.get("status") != "bkn_table_stub_proven_activation_and_ui_still_fail_closed":
        raise BknIndexRuntimeError("stage-31 report status is not accepted")
    return path


def audit(project_root: Path, source_game: Path, target_game: Path, output_dir: Path, *, create_report_archive: bool = True) -> tuple[Path | None, dict[str, Any]]:
    prerequisite_dir(project_root)
    clean_dir(output_dir)

    index_rows, fallback_rows, sequences = audit_index_tables(project_root)
    non_enum_rows = audit_non_enumeration_tables(project_root)
    text_rows = audit_text_structure(project_root)

    source_modules = discover_modules(source_game, "source")
    target_modules = discover_modules(target_game, "target")
    module_rows, token_hits, sequence_hits = scan_modules(source_modules + target_modules, sequences)

    binding_candidates: list[dict[str, Any]] = []
    for hit in token_hits:
        if hit["token_class"] == "exact_runtime" and "BKN" in hit["token"]:
            binding_candidates.append({
                "candidate_type": "exact_bkn_runtime_token",
                "side": hit["side"],
                "module_path": hit["module_path"],
                "offset": hit["offset"],
                "evidence_sha256": hit["context_sha256"],
                "binding_proven": False,
                "next_probe": "resolve code/data references around the exact BKN token without modifying the module",
            })
    for hit in sequence_hits:
        binding_candidates.append({
            "candidate_type": "complete_bkn_index_sequence",
            "side": hit["side"],
            "module_path": hit["module_path"],
            "offset": hit["offset"],
            "evidence_sha256": hit["context_sha256"],
            "binding_proven": False,
            "next_probe": "classify the sequence as code/data and compare BR1/Quartet references",
        })

    exact_bkn_hits = sum(1 for row in token_hits if row["token_class"] == "exact_runtime" and "BKN" in row["token"])
    complete_sequence_hits = len(sequence_hits)
    modules_scanned = sum(1 for row in module_rows if row["scan_status"] == "passed")
    fallback_count = sum(1 for row in fallback_rows if row["redirects_to_expected_scl_fallback"])
    index_preserved = sum(1 for row in index_rows if row["index_preserved"])
    identical_records = sum(1 for row in index_rows if row["record_identical"])
    aligned_text = sum(1 for row in text_rows if row["string_no_aligned"])
    placeholders = sum(1 for row in text_rows if row["target_is_placeholder"])

    if binding_candidates:
        status = "bkn_static_runtime_binding_candidates_found_but_not_proven"
        next_action = "perform read-only reference classification for the bounded runtime-module candidates; keep activation and installation blocked"
    elif modules_scanned:
        status = "bkn_index_blocks_preserved_no_static_runtime_binding_found"
        next_action = "audit platform entitlement/runtime enumeration dynamically or through bounded disassembly; do not infer availability from preserved indices alone"
    else:
        status = "bkn_index_blocks_preserved_runtime_modules_not_found"
        next_action = "provide or locate the root-level BR1/Quartet EXE/DLL modules for a bounded static binding scan"

    gaps = [
        {"dependency": "exact_runtime_enumeration_reference", "status": "candidate_found" if binding_candidates else "unresolved", "blocks_installation": True, "next_evidence": next_action},
        {"dependency": "owner_ui_slot", "status": "unresolved", "blocks_installation": True, "next_evidence": "resolve index-based UI ownership; no raw UI or Translation edit"},
        {"dependency": "wet_variant", "status": "conversion_blocked", "blocks_installation": True, "next_evidence": "complete G1M/SWG conversion and exact G1M-to-G1T binding"},
        {"dependency": "runtime_validation", "status": "not_started", "blocks_installation": True, "next_evidence": "only after checksum-gated asset/table composition and explicit approval"},
    ]

    write_tsv(output_dir / "DLC_BKN_INDEX_BLOCK_AUDIT.tsv", [
        "table_path", "element", "base_tag", "variant", "source_index", "target_index", "index_preserved",
        "source_record_sha256", "target_record_sha256", "record_identical", "raw_record_exported",
    ], index_rows)
    write_tsv(output_dir / "DLC_BKN_FAMILY_FALLBACK_MAP.tsv", [
        "base_tag", "pc_slot", "variant", "source_index", "target_index", "source_model", "source_default_texture",
        "target_model", "target_default_texture", "expected_fallback_tag", "expected_fallback_model",
        "redirects_to_expected_scl_fallback", "changed_fields", "target_only_or_remaster_fields_to_preserve",
        "classification", "profile_build_allowed",
    ], fallback_rows)
    write_tsv(output_dir / "DLC_BKN_NON_ENUMERATION_TABLE_AUDIT.tsv", [
        "side", "table_path", "record_count", "direct_bkn_reference_count", "direct_bkn_record_indices",
        "pc00_or_ako_reference_count", "classification", "raw_record_exported",
    ], non_enum_rows)
    write_tsv(output_dir / "DLC_BKN_TEXT_STRUCTURE_AUDIT.tsv", [
        "record_index", "source_string_no", "target_string_no", "string_no_aligned", "source_text_sha256",
        "target_text_sha256", "target_is_placeholder", "source_record_present", "target_record_present",
        "direct_bkn_identifier_present", "binding_status", "translation_owned", "raw_text_exported",
    ], text_rows)
    write_tsv(output_dir / "DLC_BKN_RUNTIME_MODULE_AUDIT.tsv", [
        "side", "relative_path", "size", "sha256", "selection_reason", "scan_status", "exact_runtime_token_hits",
        "generic_entitlement_token_hits", "complete_index_sequence_hits", "raw_module_exported",
    ], module_rows)
    write_tsv(output_dir / "DLC_BKN_RUNTIME_TOKEN_HITS.tsv", [
        "side", "module_path", "module_sha256", "token_class", "token", "encoding", "offset", "context_sha256",
        "raw_context_exported",
    ], token_hits)
    write_tsv(output_dir / "DLC_BKN_RUNTIME_INDEX_SEQUENCE_HITS.tsv", [
        "side", "module_path", "module_sha256", "sequence_ids", "value_count", "encoding", "offset",
        "sequence_sha256", "context_sha256", "raw_context_exported",
    ], sequence_hits)
    write_tsv(output_dir / "DLC_BKN_RUNTIME_BINDING_CANDIDATES.tsv", [
        "candidate_type", "side", "module_path", "offset", "evidence_sha256", "binding_proven", "next_probe",
    ], binding_candidates)
    write_tsv(output_dir / "DLC_BKN_INDEX_RUNTIME_GAPS.tsv", [
        "dependency", "status", "blocks_installation", "next_evidence",
    ], gaps)

    summary = {
        "type": "br_quartet_legacy_dlc_bkn_index_runtime_summary",
        "format_version": FORMAT_VERSION,
        "tool_version": TOOL_VERSION,
        "content_id": "costume_pc00_bkn",
        "status": status,
        "bkn_index_rows": len(index_rows),
        "bkn_indices_preserved": index_preserved,
        "bkn_records_identical": identical_records,
        "full_family_fallback_rows": len(fallback_rows),
        "expected_scl_fallback_rows": fallback_count,
        "non_enumeration_table_rows": len(non_enum_rows),
        "non_enumeration_direct_bkn_refs": sum(int(row["direct_bkn_reference_count"]) for row in non_enum_rows),
        "text_structure_rows": len(text_rows),
        "aligned_existing_string_numbers": aligned_text,
        "target_placeholders": placeholders,
        "runtime_modules_discovered": len(module_rows),
        "runtime_modules_scanned": modules_scanned,
        "exact_bkn_runtime_token_hits": exact_bkn_hits,
        "complete_bkn_index_sequence_hits": complete_sequence_hits,
        "runtime_binding_candidates": len(binding_candidates),
        "unresolved_installation_blockers": len(gaps),
        "next_action": next_action,
        "findings": [
            "all PC00-PC14 BKN dry/wet rows preserve their exact indices in chara, chara_no and charabase",
            "all thirty Quartet charabase BKN rows redirect Model/defaultTexture to the corresponding school-uniform fallback",
            "costume.xml, coschangechara.xml and costume_change.xml contain no direct BKN enumeration record",
            "the first shared str_costume String_No range remains structurally aligned but contains no technical BKN identifier",
            "static runtime token/index evidence is only a candidate and never proves entitlement or availability by itself",
        ],
        "policy": {
            "game_modified": False,
            "git_modified": False,
            "translation_modified": False,
            "text_seed_unchanged": True,
            "system_table_modified": False,
            "runtime_module_modified": False,
            "raw_modules_exported": False,
            "raw_assets_exported_in_report": False,
            "raw_assets_in_update": False,
            "candidate_installed": False,
            "profile_registered": False,
            "profile_build_allowed": False,
            "profiles_activated": False,
            "runtime_validated": False,
            "index_preservation_is_runtime_binding_proof": False,
            "static_token_or_sequence_hit_is_runtime_binding_proof": False,
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


def read_tsv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def validate_report(report_dir: Path) -> dict[str, Any]:
    required = {
        "DLC_BKN_INDEX_BLOCK_AUDIT.tsv",
        "DLC_BKN_FAMILY_FALLBACK_MAP.tsv",
        "DLC_BKN_NON_ENUMERATION_TABLE_AUDIT.tsv",
        "DLC_BKN_TEXT_STRUCTURE_AUDIT.tsv",
        "DLC_BKN_RUNTIME_MODULE_AUDIT.tsv",
        "DLC_BKN_RUNTIME_TOKEN_HITS.tsv",
        "DLC_BKN_RUNTIME_INDEX_SEQUENCE_HITS.tsv",
        "DLC_BKN_RUNTIME_BINDING_CANDIDATES.tsv",
        "DLC_BKN_INDEX_RUNTIME_GAPS.tsv",
        "SUMMARY.json",
        "REPORT_MANIFEST.json",
    }
    missing = sorted(name for name in required if not (report_dir / name).is_file())
    if missing:
        raise BknIndexRuntimeError(f"missing report files: {missing}")
    summary = json.loads((report_dir / "SUMMARY.json").read_text(encoding="utf-8"))
    if summary.get("tool_version") != TOOL_VERSION:
        raise BknIndexRuntimeError("unexpected tool version")
    if summary.get("status") not in {
        "bkn_static_runtime_binding_candidates_found_but_not_proven",
        "bkn_index_blocks_preserved_no_static_runtime_binding_found",
        "bkn_index_blocks_preserved_runtime_modules_not_found",
    }:
        raise BknIndexRuntimeError("unexpected report status")
    if summary.get("bkn_index_rows") != 90 or summary.get("bkn_indices_preserved") != 90:
        raise BknIndexRuntimeError("expected 90 preserved BKN index rows")
    if summary.get("full_family_fallback_rows") != 30 or summary.get("expected_scl_fallback_rows") != 30:
        raise BknIndexRuntimeError("expected thirty BKN charabase fallback rows")
    policy = summary.get("policy", {})
    forbidden_true = (
        "game_modified", "git_modified", "translation_modified", "system_table_modified", "runtime_module_modified",
        "raw_modules_exported", "raw_assets_exported_in_report", "raw_assets_in_update", "candidate_installed",
        "profile_registered", "profile_build_allowed", "profiles_activated", "runtime_validated",
        "index_preservation_is_runtime_binding_proof", "static_token_or_sequence_hit_is_runtime_binding_proof",
        "translation_owned_text_exported",
    )
    if any(policy.get(name) is not False for name in forbidden_true):
        raise BknIndexRuntimeError("report violates fail-closed policy")
    if policy.get("text_seed_unchanged") is not True:
        raise BknIndexRuntimeError("text seed must remain unchanged")
    index_rows = read_tsv(report_dir / "DLC_BKN_INDEX_BLOCK_AUDIT.tsv")
    if len(index_rows) != 90 or any(row["index_preserved"] != "true" for row in index_rows):
        raise BknIndexRuntimeError("invalid BKN index table")
    fallback_rows = read_tsv(report_dir / "DLC_BKN_FAMILY_FALLBACK_MAP.tsv")
    if len(fallback_rows) != 30 or any(row["redirects_to_expected_scl_fallback"] != "true" for row in fallback_rows):
        raise BknIndexRuntimeError("invalid BKN fallback map")
    gaps = read_tsv(report_dir / "DLC_BKN_INDEX_RUNTIME_GAPS.tsv")
    if len(gaps) != 4 or any(row["blocks_installation"] != "true" for row in gaps):
        raise BknIndexRuntimeError("installation blockers are incomplete")
    manifest = json.loads((report_dir / "REPORT_MANIFEST.json").read_text(encoding="utf-8"))
    for item in manifest.get("files", []):
        path = report_dir / item["path"]
        if path.suffix.casefold() in FORBIDDEN_REPORT_SUFFIXES:
            raise BknIndexRuntimeError(f"forbidden payload in report manifest: {path.name}")
        if path.stat().st_size != item["size"] or sha256_file(path) != item["sha256"]:
            raise BknIndexRuntimeError(f"manifest mismatch: {path.name}")
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
        print(f"Validated BKN index/runtime report: {output_dir}")
        print(f"Status: {summary['status']}")
        return 0
    archive_path, summary = audit(
        project_root,
        args.source_game.resolve(),
        args.target_game.resolve(),
        output_dir,
        create_report_archive=not args.no_report_archive,
    )
    print(f"BKN index rows: {summary['bkn_index_rows']}")
    print(f"BKN fallback rows: {summary['expected_scl_fallback_rows']}")
    print(f"Runtime modules scanned: {summary['runtime_modules_scanned']}")
    print(f"Runtime binding candidates: {summary['runtime_binding_candidates']}")
    print(f"Report directory: {output_dir}")
    if archive_path:
        print(f"Report: {archive_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
