#!/usr/bin/env python3
"""Read-only PC00 BKN activation, table-stub, and UI-reference audit.

The stage validates the local asset-only PACK10_02 candidate from stage 28, then
examines the exact BR1/Quartet system-table records for PC00_DLC_BKN and
PC00_DLC_BKN_W.  It also selectively reads the JP costume-change UI members
from their containing PAKs and searches for exact technical identifiers without
exporting payloads.

No table, text, PAK, profile, or game file is modified.  The generated record
patch candidates are metadata-only and remain build-forbidden.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import shutil
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
for item in (SCRIPT_DIR, PROJECT_ROOT_DEFAULT / "Blue_Reflection_Text_Tool"):
    if str(item) not in sys.path:
        sys.path.insert(0, str(item))

import br_dlc_dry_pak_insertion_tool as DRY  # noqa: E402
import br_dlc_nested_container_tool as NESTED  # noqa: E402

TOOL_VERSION = "0.0.14"
FORMAT_VERSION = 1
REPORT_DIR_NAME = "bkn_activation_ui_evidence"
REPORT_ARCHIVE_NAME = "BR_quartet_legacy_dlc_bkn_activation_ui_evidence.tar.zst"

SOURCE_TABLE_ROOT = Path("titles/blue_reflection/workspace/original/archives/PACK02_3/saves_jp")
TARGET_TABLE_ROOT = Path("titles/blue_reflection/workspace/quartet/archives/PACK12/saves/b1")
SOURCE_TEXT = SOURCE_TABLE_ROOT / "text/str_costume.xml"
TARGET_TEXT = TARGET_TABLE_ROOT / "text_jp/str_costume.xml"

BKN_TAGS = ("PC00_DLC_BKN", "PC00_DLC_BKN_W")
CONTROL_TAGS = ("PC00_DLC_TWL", "PC00_DLC_TWL_W")
FALLBACK_TAGS = ("PC00_SCL", "PC00_SCL_W")
ALL_TECHNICAL_TOKENS = BKN_TAGS + CONTROL_TAGS + FALLBACK_TAGS + (
    "PC00/PC00_DLC_Bkn", "PC00/PC00_DLC_Bkn_W", "PC00/PC00_Scl", "PC00/PC00_Scl_W",
)

SYSTEM_TABLES = (
    "chara/chara.xml",
    "chara/chara_no.xml",
    "chara/charabase.xml",
    "costume/costume.xml",
    "costume/coschangechara.xml",
    "ez_eff_player/costume_change.xml",
    "mainmenu/mainmenustatusselectitemsreleasecondition.xml",
    "mainmenu/mainmenutopselectitemsreleasecondition.xml",
)

UI_MEMBER_NAMES = (
    "22_costume_change.kscl",
    "22_costume_change_bg.kscl",
    "22_costume_change_sl.kscl",
    "22_costume_change_vl.kscl",
    "external/x0_cmn_item_icon.kslt",
)

FORBIDDEN_REPORT_SUFFIXES = {
    ".pak", ".ebm", ".ebd", ".g1m", ".g1t", ".g1a", ".g1e", ".g1s",
    ".elixir", ".gz", ".bin", ".swg", ".dds", ".wav", ".ogg", ".kscl", ".kslt",
}

ACTIVATION_FIELD = re.compile(
    r"(?:^|_)(?:dlc|entitlement|permit|enable|active|unlock|release|condition|flag|st_ev|event|product|shop|availability)(?:$|_)",
    re.I,
)


class BknActivationUiError(RuntimeError):
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


def decode_text(path: Path) -> str:
    raw = path.read_bytes()
    for encoding in ("cp932", "shift_jis", "utf-8-sig", "utf-8"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise BknActivationUiError(f"unable to decode XML: {path}")


def parse_xml(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        raise BknActivationUiError(f"missing table workspace file: {path}")
    text = re.sub(r"<\?xml[^>]*\?>", "", decode_text(path), count=1, flags=re.I)
    try:
        root = ET.fromstring(text)
    except ET.ParseError as exc:
        raise BknActivationUiError(f"failed to parse XML {path}: {exc}") from exc
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


def record_by_basetag(rows: list[dict[str, Any]], tag: str) -> dict[str, Any] | None:
    found = [row for row in rows if row["attrs"].get("BaseTag") == tag]
    if len(found) > 1:
        raise BknActivationUiError(f"duplicate BaseTag {tag}")
    return found[0] if found else None


def attr_diffs(source: Mapping[str, str], target: Mapping[str, str]) -> list[dict[str, str]]:
    rows = []
    for key in sorted(set(source) | set(target), key=str.casefold):
        before = source.get(key, "")
        after = target.get(key, "")
        if before != after:
            rows.append({"field": key, "source_value": before, "target_value": after})
    return rows


def scan_xml_references(base: Path, side: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    references: list[dict[str, Any]] = []
    activation: list[dict[str, Any]] = []
    for relative in SYSTEM_TABLES:
        path = base / relative
        rows = parse_xml(path)
        for row in rows:
            attrs = row["attrs"]
            hits = sorted({token for token in ALL_TECHNICAL_TOKENS if any(token.casefold() in str(v).casefold() for v in attrs.values())})
            if hits:
                references.append({
                    "side": side,
                    "table_path": relative,
                    "record_index": row["index"],
                    "element": row["element"],
                    "record_sha256": row["record_sha256"],
                    "matched_tokens": hits,
                    "attribute_names": sorted(attrs),
                    "raw_text_exported": False,
                })
            for field, value in attrs.items():
                if ACTIVATION_FIELD.search(field) and any(token.casefold() in value.casefold() for token in BKN_TAGS):
                    activation.append({
                        "side": side,
                        "table_path": relative,
                        "record_index": row["index"],
                        "record_sha256": row["record_sha256"],
                        "field_name": field,
                        "value_sha256": sha256_bytes(value.encode("utf-8")),
                        "matched_token": next(token for token in BKN_TAGS if token.casefold() in value.casefold()),
                        "semantics_proven": False,
                    })
    return references, activation


def load_inventory(project_root: Path, side: str) -> list[dict[str, Any]]:
    path = project_root / f".local/reports/quartet_restoration/inventories/br1_assets.{side}.json"
    if not path.is_file():
        raise BknActivationUiError(f"missing asset inventory: {path}")
    value = json.loads(path.read_text(encoding="utf-8"))
    return list(value.get("files", []))


def select_ui_members(project_root: Path) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []
    for side, language, inventory_side in (("source", "res_jp", "source"), ("target", "res_jp", "target")):
        for row in load_inventory(project_root, inventory_side):
            normalized = str(row.get("normalized_path", "")).replace("\\", "/")
            folded = normalized.casefold()
            if f"data/x64/{language}/layout/" not in folded:
                continue
            if not any(folded.endswith(name.casefold()) for name in UI_MEMBER_NAMES):
                continue
            selected.append({
                "side": side,
                "archive": str(row.get("archive", "")),
                "inventory_path": str(row.get("path", "")),
                "normalized_path": normalized,
                "expected_size": int(row.get("size", 0)),
                "expected_sha256": str(row.get("sha256", "")),
            })
    if len([x for x in selected if x["side"] == "source"]) != len(UI_MEMBER_NAMES):
        raise BknActivationUiError("source JP costume UI member selection is incomplete")
    if len([x for x in selected if x["side"] == "target"]) != len(UI_MEMBER_NAMES):
        raise BknActivationUiError("target JP costume UI member selection is incomplete")
    return sorted(selected, key=lambda r: (r["side"], r["normalized_path"].casefold()))


def archive_path(game_root: Path, archive: str) -> Path:
    candidate = game_root / archive
    if candidate.is_file():
        return candidate
    candidate = game_root / Path(archive).name
    if candidate.is_file():
        return candidate
    raise BknActivationUiError(f"missing local archive required for UI scan: {archive}")


def find_bytes(payload: bytes, needle: bytes) -> list[int]:
    result: list[int] = []
    start = 0
    while True:
        index = payload.find(needle, start)
        if index < 0:
            return result
        result.append(index)
        start = index + 1


def scan_ui_payload(side: str, row: dict[str, Any], payload: bytes) -> list[dict[str, Any]]:
    hits: list[dict[str, Any]] = []
    for token in ALL_TECHNICAL_TOKENS:
        for encoding, needle in (("ascii", token.encode("ascii")), ("utf16le", token.encode("utf-16le"))):
            for offset in find_bytes(payload, needle):
                hits.append({
                    "side": side,
                    "archive": row["archive"],
                    "member_path": row["normalized_path"],
                    "member_sha256": sha256_bytes(payload),
                    "token": token,
                    "token_sha256": sha256_bytes(token.encode("utf-8")),
                    "encoding": encoding,
                    "offset": offset,
                    "raw_payload_exported": False,
                })
    return hits


def scan_ui_members(project_root: Path, br1_root: Path, quartet_root: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    selected = select_ui_members(project_root)
    indexes: dict[tuple[str, str], Any] = {}
    audit_rows: list[dict[str, Any]] = []
    hits: list[dict[str, Any]] = []
    for row in selected:
        root = br1_root if row["side"] == "source" else quartet_root
        key = (row["side"], row["archive"])
        if key not in indexes:
            indexes[key] = NESTED.index_pak(archive_path(root, row["archive"]))
        index = indexes[key]
        payload, entry = NESTED.read_pak_member(index, row["inventory_path"])
        actual_sha = sha256_bytes(payload)
        if len(payload) != row["expected_size"] or actual_sha != row["expected_sha256"]:
            raise BknActivationUiError(f"UI member changed since inventory: {row['side']} {row['normalized_path']}")
        member_hits = scan_ui_payload(row["side"], row, payload)
        hits.extend(member_hits)
        audit_rows.append({
            **row,
            "detected_pak_format": index.format_name,
            "detected_master_key": index.master_key_label,
            "decoded_size": len(payload),
            "decoded_sha256": actual_sha,
            "technical_token_hits": len(member_hits),
            "validation_status": "passed",
            "raw_payload_exported": False,
        })
    return audit_rows, sorted(hits, key=lambda r: (r["side"], r["member_path"], r["offset"], r["token"]))


def text_table_audit(project_root: Path) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for side, relative in (("source", SOURCE_TEXT), ("target", TARGET_TEXT)):
        path = project_root / relative
        rows = parse_xml(path)
        identifiers = 0
        placeholders = 0
        for row in rows:
            values = list(row["attrs"].values())
            if any(any(token.casefold() in value.casefold() for token in BKN_TAGS) for value in values):
                identifiers += 1
            if row["attrs"].get("Text") == "-":
                placeholders += 1
        result.append({
            "side": side,
            "table_path": str(relative),
            "record_count": len(rows),
            "direct_bkn_identifier_records": identifiers,
            "placeholder_records": placeholders,
            "binding_status": "no_explicit_bkn_identifier_binding" if identifiers == 0 else "explicit_binding_found",
            "translation_owned": True,
            "raw_text_exported": False,
        })
    return result


def make_archive(source: Path, output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="br_dlc_bkn_ui_bundle_") as temp_name:
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
    rows = []
    for path in sorted(root.rglob("*"), key=lambda p: p.relative_to(root).as_posix().casefold()):
        if path.is_file() and path.name != "REPORT_MANIFEST.json":
            rows.append({"path": path.relative_to(root).as_posix(), "size": path.stat().st_size, "sha256": sha256_file(path)})
    return rows


def validate_dry_prerequisite(project_root: Path) -> dict[str, Any]:
    report_parent = project_root / ".local/reports/quartet_legacy_dlc"
    direct = report_parent / DRY.REPORT_DIR_NAME
    if direct.is_dir():
        return DRY.validate_report(direct)
    archive = report_parent / DRY.REPORT_ARCHIVE_NAME
    if not archive.is_file():
        raise BknActivationUiError("missing stage-28 dry PAK insertion report")
    with tempfile.TemporaryDirectory(prefix="br_dlc_bkn_prereq_") as temp_name:
        temp = Path(temp_name)
        subprocess.run(["tar", "--zstd", "-xf", str(archive), "-C", str(temp)], check=True)
        candidates = [p for p in temp.iterdir() if p.is_dir()]
        if len(candidates) != 1:
            raise BknActivationUiError("could not locate extracted stage-28 report")
        return DRY.validate_report(candidates[0])


def audit(project_root: Path, br1_root: Path, quartet_root: Path, output_root: Path) -> tuple[Path, dict[str, Any]]:
    print("[stage31] validating dry PACK10_02 candidate evidence", flush=True)
    dry = validate_dry_prerequisite(project_root)
    if dry.get("content_id") != "costume_pc00_bkn" or dry.get("candidate_installed") is True:
        raise BknActivationUiError("stage-28 report is not the expected uninstalled PC00 BKN candidate")

    clean_dir(output_root)
    source_root = project_root / SOURCE_TABLE_ROOT
    target_root = project_root / TARGET_TABLE_ROOT
    print("[stage31] parsing exact BR1 and Quartet system-table records", flush=True)

    record_rows: list[dict[str, Any]] = []
    diff_rows: list[dict[str, Any]] = []
    stub_rows: list[dict[str, Any]] = []
    for relative in ("chara/chara.xml", "chara/chara_no.xml", "chara/charabase.xml"):
        source_records = parse_xml(source_root / relative)
        target_records = parse_xml(target_root / relative)
        for tag in BKN_TAGS + CONTROL_TAGS + FALLBACK_TAGS:
            source = record_by_basetag(source_records, tag)
            target = record_by_basetag(target_records, tag)
            status = "missing"
            if source and target:
                status = "present_identical" if source["record_sha256"] == target["record_sha256"] else "present_modified"
            elif source:
                status = "missing_in_target"
            elif target:
                status = "target_only"
            record_rows.append({
                "table_path": relative,
                "base_tag": tag,
                "role": "bkn_candidate" if tag in BKN_TAGS else ("positive_control" if tag in CONTROL_TAGS else "fallback_target"),
                "source_index": source["index"] if source else "",
                "source_record_sha256": source["record_sha256"] if source else "",
                "target_index": target["index"] if target else "",
                "target_record_sha256": target["record_sha256"] if target else "",
                "status": status,
                "raw_record_exported": False,
            })
            if source and target:
                for change in attr_diffs(source["attrs"], target["attrs"]):
                    diff_rows.append({"table_path": relative, "base_tag": tag, **change})
            if relative == "chara/charabase.xml" and tag in BKN_TAGS and source and target:
                source_model = source["attrs"].get("Model", "")
                target_model = target["attrs"].get("Model", "")
                source_texture = source["attrs"].get("defaultTexture", "")
                target_texture = target["attrs"].get("defaultTexture", "")
                expected_fallback = "PC00/PC00_Scl_W" if tag.endswith("_W") else "PC00/PC00_Scl"
                stub = target_model == expected_fallback and target_texture == expected_fallback
                stub_rows.append({
                    "base_tag": tag,
                    "source_model": source_model,
                    "source_default_texture": source_texture,
                    "target_model": target_model,
                    "target_default_texture": target_texture,
                    "target_redirects_to_scl_fallback": stub,
                    "classification": "present_but_disabled_via_scl_fallback" if stub else "present_modified_unknown_mapping",
                    "future_patch_fields": ["Model", "defaultTexture"],
                    "preserve_target_only_fields": sorted(set(target["attrs"]) - set(source["attrs"])),
                    "profile_build_allowed": False,
                })

    source_refs, source_activation = scan_xml_references(source_root, "source")
    target_refs, target_activation = scan_xml_references(target_root, "target")
    print("[stage31] selectively scanning JP costume UI members", flush=True)
    ui_members, ui_hits = scan_ui_members(project_root, br1_root, quartet_root)
    text_rows = text_table_audit(project_root)

    patch_candidates = []
    for row in stub_rows:
        tag = row["base_tag"]
        patch_candidates.append({
            "record_key": f"CharaBase:BaseTag={tag}",
            "target_table": "saves/b1/chara/charabase.xml",
            "expected_old_values": {"Model": row["target_model"], "defaultTexture": row["target_default_texture"]},
            "new_values": {"Model": row["source_model"], "defaultTexture": row["source_default_texture"]},
            "preserve_all_other_target_attributes": True,
            "candidate_status": "metadata_only_not_buildable",
            "profile_build_allowed": False,
        })

    activation_rows = source_activation + target_activation
    direct_ui_bkn_hits = [r for r in ui_hits if r["token"] in BKN_TAGS or "DLC_Bkn" in r["token"]]
    direct_xml_bkn_refs = [r for r in source_refs + target_refs if any(t in BKN_TAGS for t in r["matched_tokens"])]
    findings = [
        "PC00_DLC_BKN and PC00_DLC_BKN_W records remain present in Quartet chara/chara_no tables",
        "Quartet charabase redirects both BKN records to the PC00_Scl dry/wet fallback instead of the missing BKN assets",
        "future activation must patch only Model/defaultTexture and preserve Quartet-only remaster attributes",
        "no entitlement is synthesized and no UI or text table is modified",
    ]
    if not activation_rows:
        findings.append("no exact BKN unlock/entitlement field was found in the scanned system tables")
    if not direct_ui_bkn_hits:
        findings.append("no exact BKN technical identifier was found as an ASCII/UTF-16 token in the selected JP costume UI members")

    gaps = [
        {"dependency": "exact_unlock_or_entitlement", "status": "unresolved" if not activation_rows else "candidate_only", "blocks_installation": True, "next_evidence": "locate runtime costume enumeration or platform entitlement binding; do not invent one"},
        {"dependency": "owner_ui_slot", "status": "unresolved" if not direct_ui_bkn_hits else "candidate_only", "blocks_installation": True, "next_evidence": "resolve index-based costume UI ownership or shared atlas slot without modifying Translation"},
        {"dependency": "wet_variant", "status": "conversion_blocked", "blocks_installation": True, "next_evidence": "complete G1M/SWG conversion and texture-slot binding"},
        {"dependency": "runtime_validation", "status": "not_started", "blocks_installation": True, "next_evidence": "only after asset and record composition is checksum-gated and explicitly approved"},
    ]

    write_tsv(output_root / "DLC_BKN_TABLE_RECORD_AUDIT.tsv", [
        "table_path", "base_tag", "role", "source_index", "source_record_sha256", "target_index", "target_record_sha256", "status", "raw_record_exported",
    ], record_rows)
    write_tsv(output_root / "DLC_BKN_TABLE_ATTRIBUTE_DIFFS.tsv", ["table_path", "base_tag", "field", "source_value", "target_value"], diff_rows)
    write_tsv(output_root / "DLC_BKN_CHARABASE_STUB_MAPPING.tsv", [
        "base_tag", "source_model", "source_default_texture", "target_model", "target_default_texture", "target_redirects_to_scl_fallback", "classification", "future_patch_fields", "preserve_target_only_fields", "profile_build_allowed",
    ], stub_rows)
    write_tsv(output_root / "DLC_BKN_SYSTEM_REFERENCE_SCAN.tsv", [
        "side", "table_path", "record_index", "element", "record_sha256", "matched_tokens", "attribute_names", "raw_text_exported",
    ], source_refs + target_refs)
    write_tsv(output_root / "DLC_BKN_UNLOCK_REFERENCE_SCAN.tsv", [
        "side", "table_path", "record_index", "record_sha256", "field_name", "value_sha256", "matched_token", "semantics_proven",
    ], activation_rows)
    write_tsv(output_root / "DLC_BKN_UI_MEMBER_AUDIT.tsv", [
        "side", "archive", "inventory_path", "normalized_path", "expected_size", "expected_sha256", "detected_pak_format", "detected_master_key", "decoded_size", "decoded_sha256", "technical_token_hits", "validation_status", "raw_payload_exported",
    ], ui_members)
    write_tsv(output_root / "DLC_BKN_UI_TECHNICAL_TOKEN_HITS.tsv", [
        "side", "archive", "member_path", "member_sha256", "token", "token_sha256", "encoding", "offset", "raw_payload_exported",
    ], ui_hits)
    write_tsv(output_root / "DLC_BKN_TEXT_BINDING_AUDIT.tsv", [
        "side", "table_path", "record_count", "direct_bkn_identifier_records", "placeholder_records", "binding_status", "translation_owned", "raw_text_exported",
    ], text_rows)
    write_json(output_root / "DLC_BKN_CHARABASE_PATCH_CANDIDATES.json", {
        "type": "br_quartet_legacy_dlc_bkn_charabase_patch_candidates",
        "format_version": 1,
        "content_id": "costume_pc00_bkn",
        "candidates": patch_candidates,
        "policy": {"metadata_only": True, "profile_build_allowed": False, "table_modified": False, "translation_modified": False},
    })
    write_tsv(output_root / "DLC_BKN_ACTIVATION_UI_GAPS.tsv", ["dependency", "status", "blocks_installation", "next_evidence"], gaps)

    summary = {
        "type": "br_quartet_legacy_dlc_bkn_activation_ui_summary",
        "format_version": FORMAT_VERSION,
        "tool_version": TOOL_VERSION,
        "content_id": "costume_pc00_bkn",
        "status": "bkn_table_stub_proven_activation_and_ui_still_fail_closed",
        "dry_candidate_sha256": dry.get("candidate_sha256", ""),
        "table_record_rows": len(record_rows),
        "table_attribute_differences": len(diff_rows),
        "bkn_stub_rows": len(stub_rows),
        "system_reference_rows": len(source_refs) + len(target_refs),
        "direct_bkn_system_reference_rows": len(direct_xml_bkn_refs),
        "exact_unlock_reference_rows": len(activation_rows),
        "ui_members_scanned": len(ui_members),
        "ui_technical_token_hits": len(ui_hits),
        "direct_bkn_ui_token_hits": len(direct_ui_bkn_hits),
        "text_tables_audited": len(text_rows),
        "charabase_patch_candidates": len(patch_candidates),
        "unresolved_installation_blockers": sum(1 for row in gaps if row["blocks_installation"]),
        "findings": findings,
        "next_action": "audit index-based costume enumeration and exact runtime availability path; keep the local asset-only PAK uninstalled and wet BKN conversion blocked",
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
            "text_seed_unchanged": True,
        },
    }
    write_json(output_root / "SUMMARY.json", summary)
    write_json(output_root / "REPORT_MANIFEST.json", {"type": "br_report_manifest", "format_version": 1, "files": report_manifest(output_root)})
    archive = output_root.parent / REPORT_ARCHIVE_NAME
    make_archive(output_root, archive)
    print(f"[stage31] report: {archive}", flush=True)
    return archive, summary


def validate_report(report_root: Path) -> dict[str, Any]:
    required = (
        "DLC_BKN_TABLE_RECORD_AUDIT.tsv", "DLC_BKN_TABLE_ATTRIBUTE_DIFFS.tsv",
        "DLC_BKN_CHARABASE_STUB_MAPPING.tsv", "DLC_BKN_SYSTEM_REFERENCE_SCAN.tsv",
        "DLC_BKN_UNLOCK_REFERENCE_SCAN.tsv", "DLC_BKN_UI_MEMBER_AUDIT.tsv",
        "DLC_BKN_UI_TECHNICAL_TOKEN_HITS.tsv", "DLC_BKN_TEXT_BINDING_AUDIT.tsv",
        "DLC_BKN_CHARABASE_PATCH_CANDIDATES.json", "DLC_BKN_ACTIVATION_UI_GAPS.tsv",
        "SUMMARY.json", "REPORT_MANIFEST.json",
    )
    for name in required:
        if not (report_root / name).is_file():
            raise BknActivationUiError(f"missing report file: {name}")
    summary = json.loads((report_root / "SUMMARY.json").read_text(encoding="utf-8"))
    if summary.get("type") != "br_quartet_legacy_dlc_bkn_activation_ui_summary" or summary.get("tool_version") != TOOL_VERSION:
        raise BknActivationUiError("invalid BKN activation/UI summary")
    if summary.get("status") != "bkn_table_stub_proven_activation_and_ui_still_fail_closed":
        raise BknActivationUiError("unexpected BKN activation/UI status")
    if summary.get("bkn_stub_rows") != 2 or summary.get("charabase_patch_candidates") != 2:
        raise BknActivationUiError("expected exactly two dry/wet PC00 BKN stub records")
    if summary.get("ui_members_scanned") != 10 or summary.get("text_tables_audited") != 2:
        raise BknActivationUiError("incomplete UI/text audit")
    policy = summary.get("policy", {})
    for key in (
        "game_modified", "git_modified", "candidate_installed", "profile_registered", "profile_build_allowed",
        "profiles_activated", "runtime_validated", "system_table_modified", "ui_modified", "translation_modified",
        "raw_assets_exported_in_report", "raw_assets_in_update",
    ):
        if policy.get(key) is not False:
            raise BknActivationUiError(f"fail-closed policy violation: {key}")
    if policy.get("text_seed_unchanged") is not True:
        raise BknActivationUiError("text seed must remain unchanged")
    with (report_root / "DLC_BKN_CHARABASE_STUB_MAPPING.tsv").open("r", encoding="utf-8-sig", newline="") as handle:
        stubs = list(csv.DictReader(handle, delimiter="\t"))
    if {row["base_tag"] for row in stubs} != set(BKN_TAGS):
        raise BknActivationUiError("BKN stub mapping tags differ from fixed scope")
    if not all(row["target_redirects_to_scl_fallback"] == "true" and row["profile_build_allowed"] == "false" for row in stubs):
        raise BknActivationUiError("BKN stub mapping did not prove the SCL fallback")
    candidates = json.loads((report_root / "DLC_BKN_CHARABASE_PATCH_CANDIDATES.json").read_text(encoding="utf-8"))
    if candidates.get("policy", {}).get("profile_build_allowed") is not False:
        raise BknActivationUiError("record patch candidates must remain metadata-only")
    for path in report_root.rglob("*"):
        if path.is_file() and ({suffix.casefold() for suffix in path.suffixes} & FORBIDDEN_REPORT_SUFFIXES):
            raise BknActivationUiError(f"raw asset in report: {path}")
    manifest = json.loads((report_root / "REPORT_MANIFEST.json").read_text(encoding="utf-8"))
    for row in manifest.get("files", []):
        path = report_root / row["path"]
        if not path.is_file() or path.stat().st_size != row["size"] or sha256_file(path) != row["sha256"]:
            raise BknActivationUiError(f"report manifest mismatch: {row['path']}")
    return summary


def main() -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    audit_parser = sub.add_parser("audit")
    audit_parser.add_argument("--project-root", required=True)
    audit_parser.add_argument("--br1-root", required=True)
    audit_parser.add_argument("--quartet-root", required=True)
    audit_parser.add_argument("--output-root")
    validate_parser = sub.add_parser("validate-report")
    validate_parser.add_argument("--report-root", required=True)
    bundle_parser = sub.add_parser("bundle-report")
    bundle_parser.add_argument("--report-root", required=True)
    bundle_parser.add_argument("--output", required=True)
    args = parser.parse_args()
    try:
        if args.command == "audit":
            project = Path(args.project_root).resolve()
            output = Path(args.output_root).resolve() if args.output_root else project / ".local/reports/quartet_legacy_dlc" / REPORT_DIR_NAME
            audit(project, Path(args.br1_root).resolve(), Path(args.quartet_root).resolve(), output)
        elif args.command == "validate-report":
            validate_report(Path(args.report_root).resolve())
            print("BKN activation/UI evidence validated.")
        else:
            root = Path(args.report_root).resolve()
            validate_report(root)
            make_archive(root, Path(args.output).resolve())
    except (BknActivationUiError, DRY.DryPakInsertionError, NESTED.NestedContainerError, OSError, subprocess.SubprocessError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
