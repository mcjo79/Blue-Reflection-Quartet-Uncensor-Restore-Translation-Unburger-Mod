#!/usr/bin/env python3
"""Read-only nonscenario legacy DLC catalog for Blue Reflection Quartet.

The tool derives an independent DLC catalog from first-game member inventories
and JP system-table records. It does not treat the existing text/event candidate
list as complete and never writes to either game installation.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable, Sequence

TOOL_VERSION = "0.0.2"
FORMAT_VERSION = 1
ALLOWED_STATUSES = {
    "present_identical",
    "present_modified",
    "present_but_disabled",
    "missing_portable_from_br1",
    "missing_requires_conversion",
    "missing_requires_reconstruction",
    "unknown_dependency",
}
FORBIDDEN_REPORT_SUFFIXES = {
    ".pak", ".ebd", ".ebm", ".g1m", ".g1t", ".g1e", ".g1em", ".g1s",
    ".kps", ".gz", ".bin", ".dds", ".png", ".jpg", ".jpeg", ".wav",
    ".ogg", ".at9", ".ktss", ".elixir",
}
ID_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_./-]{2,}$")
DLC_ID_RE = re.compile(r"(?i)(?:[A-Z0-9]+_)*[A-Z0-9]*DLC[A-Z0-9_]*")
COSTUME_MEMBER_RE = re.compile(
    r"^data/x64/character/(?P<pc>pc\d{2})/(?P=pc)_dlc_(?P<code>[a-z0-9]+)(?P<wet>_w)?\.(?P<kind>elixir\.gz|g1t)$",
    re.I,
)
COSTUME_ID_RE = re.compile(r"^(?:CHARA_[A-Z0-9]+_|)(PC\d{2})_DLC_([A-Z0-9]+)(?:_W)?$", re.I)
ITEM_DLC_RE = re.compile(r"(?:STR_ITEM_NAME_)?ITEM_DLC_ITEM_(\d+)$", re.I)
GENERIC_IDS = {
    "TRUE", "FALSE", "NONE", "ROOT", "DLC", "DLC_NONE", "CHARACTER", "MODEL",
    "TEXTURE", "ITEM", "COSTUME", "DEFAULT", "EFFECT", "FIELD", "SHOP",
}
CODE_LABELS = {
    "bkn": "bikini_or_swimsuit_variant",
    "slr": "sailor_swimsuit_variant",
    "twl": "bath_towel_variant",
    "vac": "vacation_outfit_variant",
    "swm": "swimsuit_variant",
    "swr": "swimwear_variant",
    "hmf": "collaboration_outfit_variant_hmf",
    "hmm": "collaboration_outfit_variant_hmm",
    "als": "collaboration_outfit_variant_als",
    "rrn": "collaboration_outfit_variant_rrn",
    "arn": "collaboration_outfit_variant_arn",
    "cdn": "collaboration_outfit_variant_cdn",
    "dng": "dungeon_or_collaboration_outfit_variant",
    "pvt": "appearance_variant_pvt",
    "scl": "school_or_special_outfit_variant",
    "tns": "appearance_variant_tns",
    "trk": "appearance_variant_trk",
    "frs": "appearance_variant_frs",
}


class NonscenarioAuditError(RuntimeError):
    pass


def eprint(*args: object) -> None:
    print(*args, file=sys.stderr)


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def load_json(path: Path) -> Any:
    if not path.is_file():
        raise NonscenarioAuditError(f"missing required JSON: {path}")
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(value, ensure_ascii=False, indent=2, sort_keys=False) + "\n"
    path.write_text(text, encoding="utf-8")


def write_tsv(path: Path, fieldnames: Sequence[str], rows: Iterable[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, delimiter="\t", lineterminator="\n", extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({key: scalar(row.get(key, "")) for key in fieldnames})


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


def normalized_table_path(path: str) -> str:
    value = path.replace("\\", "/")
    for prefix in ("saves_jp/", "saves_en/", "saves_ch/", "saves/b1/", "saves/"):
        if value.casefold().startswith(prefix.casefold()):
            return "saves/" + value[len(prefix):]
    return value


def workspace_file(project_root: Path, side: str, archive: str, path: str) -> Path:
    archive_stem = Path(archive).stem
    branch = "original" if side == "source" else "quartet"
    return project_root / "titles/blue_reflection/workspace" / branch / "archives" / archive_stem / path


def decode_xml(path: Path) -> str:
    raw = path.read_bytes()
    for encoding in ("cp932", "shift_jis", "utf-8-sig", "utf-8"):
        try:
            text = raw.decode(encoding)
            return re.sub(r"<\?xml[^>]*\?>", "", text, count=1, flags=re.I)
        except UnicodeDecodeError:
            continue
    raise NonscenarioAuditError(f"unable to decode XML: {path}")


def parse_xml_records(path: Path) -> tuple[list[dict[str, Any]], str]:
    try:
        root = ET.fromstring(decode_xml(path))
    except Exception as exc:
        return [], f"parse_failed:{type(exc).__name__}"
    rows: list[dict[str, Any]] = []
    for index, element in enumerate(list(root)):
        attrs = {str(key): str(value) for key, value in element.attrib.items()}
        canonical = json.dumps({"element": element.tag, "attrs": attrs}, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        rows.append(
            {
                "index": index,
                "element": str(element.tag),
                "attrs": attrs,
                "record_sha256": sha256_bytes(canonical.encode("utf-8")),
                "identifiers": extract_identifiers(attrs.values()),
                "dlc_identifiers": extract_dlc_identifiers(attrs.values()),
                "record_key": record_key(str(element.tag), attrs, index),
            }
        )
    return rows, "parsed"


def extract_identifiers(values: Iterable[str]) -> list[str]:
    found: set[str] = set()
    for value in values:
        for token in re.split(r"[\s,;|]+", value):
            token = token.strip()
            if not ID_RE.fullmatch(token):
                continue
            upper = token.upper()
            if upper in GENERIC_IDS or len(upper) < 4:
                continue
            if upper.isdigit():
                continue
            found.add(upper)
    return sorted(found)


def extract_dlc_identifiers(values: Iterable[str]) -> list[str]:
    found: set[str] = set()
    for value in values:
        for match in DLC_ID_RE.findall(value):
            upper = match.upper()
            if upper not in {"DLC", "DLC_NONE", "DLCTAG"}:
                found.add(upper)
    return sorted(found)


def record_key(element: str, attrs: dict[str, str], index: int) -> str:
    preferred = (
        "tag", "BaseTag", "CharaTag", "item_tag", "name_str_id", "String_No",
        "st_ev_tag", "NameStrID", "make_item_tag", "ref_skin", "id", "no",
    )
    for key in preferred:
        if key in attrs and attrs[key]:
            return f"{element}:{key}={attrs[key]}"
    return f"{element}:index={index}"


def translation_owned(path: str) -> bool:
    p = path.casefold()
    return "/text/" in p or "/text_" in p or p.startswith("saves/text") or "str_" in Path(p).name


def build_difference_index(report: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {str(row.get("normalized_path", "")).casefold(): row for row in report.get("entries", [])}


def member_status(row: dict[str, Any]) -> tuple[str, str]:
    classification = str(row.get("classification", ""))
    source = row.get("source") or {}
    extension = str(source.get("extension", "")).casefold()
    asset_type = str(source.get("asset_type", ""))
    if classification == "identical":
        return "present_identical", "source and Quartet member hashes are identical"
    if classification == "changed":
        return "present_modified", "source and Quartet members both exist but differ"
    if classification == "removed_in_target":
        if extension in {".g1t", ".gz", ".g1m", ".g1e", ".g1em", ".g1s", ".koc", ".g1pf"}:
            return "missing_portable_from_br1", "same member/container families are supported by Quartet; local transfer still requires dependency and runtime validation"
        if extension in {".xml", ".e", ".dat"} or asset_type == "event_or_script":
            return "missing_requires_reconstruction", "copying a whole system table would overwrite Quartet records; member-level record merge is required"
        return "missing_requires_conversion", "source member is absent and compatibility has not been demonstrated"
    return "unknown_dependency", f"unhandled difference classification: {classification or 'missing'}"


def content_from_member(path: str) -> tuple[str, str, str, str]:
    p = path.casefold()
    match = COSTUME_MEMBER_RE.match(p)
    if match:
        pc = match.group("pc").lower()
        code = match.group("code").lower()
        state = "wet" if match.group("wet") else "dry"
        label = CODE_LABELS.get(code, f"costume_variant_{code}")
        return f"costume_{pc}_{code}", "costume_and_appearance", label, state
    if "s120_dlc_beach_01" in p:
        return "south_island_field_assets", "field_and_location", "south_island_or_dlc_beach_field", "shared"
    if "3000_dlc01" in p:
        return "dlc_effect_pack_3000", "effects", "dlc_effect_pack", "shared"
    if p.startswith("dlc/bgm/") or "str_dlc_bgm" in p:
        return "dlc_bgm_pack", "bgm_and_theme", "dlc_bgm_or_theme_pack", "shared"
    stem = re.sub(r"[^a-z0-9]+", "_", p).strip("_")
    return f"member_{hashlib.sha1(p.encode()).hexdigest()[:12]}", "uncategorized_explicit_dlc", stem[:80], "shared"


def content_from_identifier(identifier: str) -> tuple[str, str, str]:
    upper = identifier.upper()
    item = ITEM_DLC_RE.search(upper)
    if item:
        return f"dlc_item_{int(item.group(1)):02d}", "items_rewards_and_recipes", "dlc_item_or_reward"
    costume = COSTUME_ID_RE.match(upper)
    if costume:
        pc, code = costume.groups()
        code_lower = code.lower()
        return f"costume_{pc.lower()}_{code_lower}", "costume_and_appearance", CODE_LABELS.get(code_lower, f"costume_variant_{code_lower}")
    if upper.startswith("CHARA_") and "_DLC_" in upper:
        parts = upper.split("_DLC_", 1)
        who = re.sub(r"[^a-z0-9]+", "_", parts[0][6:].lower()).strip("_") or "unknown"
        code = parts[1].lower().removesuffix("_wet")
        return f"costume_character_{who}_{code}", "costume_and_appearance", CODE_LABELS.get(code, f"costume_variant_{code}")
    if upper.startswith("DLC_COSTUME") or upper.startswith("COSTUME_PC"):
        slug = re.sub(r"[^a-z0-9]+", "_", upper.lower()).strip("_")
        return f"table_{slug}", "costume_and_appearance", "table_defined_collaboration_costume"
    if upper.startswith("DLC_ADDSKIN") or upper.startswith("STR_CHANNEL_SKIN_DLC"):
        return "freespace_dlc_skin_01", "freespace_theme_and_ui", "freespace_skin_or_theme"
    if upper.startswith("3000_DLC"):
        return "dlc_effect_pack_3000", "effects", "dlc_effect_pack"
    slug = re.sub(r"[^a-z0-9]+", "_", upper.lower()).strip("_")
    return f"identifier_{slug[:80]}", "unknown_table_defined_dlc", "table_defined_dlc_identifier"


def explicit_member(path: str) -> bool:
    p = path.casefold()
    return "_dlc_" in p or "/dlc_" in p or p.startswith("dlc/") or "str_dlc_" in p or "s120_dlc_beach_01" in p or "3000_dlc01" in p


def target_record_status(source: dict[str, Any], target_records: list[dict[str, Any]]) -> tuple[str, str]:
    same_key = [row for row in target_records if row["record_key"].casefold() == source["record_key"].casefold()]
    exact = [row for row in same_key if row["record_sha256"] == source["record_sha256"]]
    attrs = source["attrs"]
    disabled = any(str(attrs.get(key, "")).casefold() in {"false", "0", "off", "disabled"} for key in ("permit", "enabled", "enable", "active"))
    if exact:
        if disabled or any(value.upper().startswith("DLC_") for value in attrs.values()):
            return "present_but_disabled", "record is preserved in Quartet but activation/entitlement remains unresolved or disabled"
        return "present_identical", "record is byte-semantically identical after XML normalization"
    if same_key:
        return "present_modified", "matching record key exists in Quartet with changed attributes"
    return "missing_requires_reconstruction", "source DLC record is absent from the corresponding Quartet table"


def aggregate_status(statuses: Iterable[str], has_activation_record: bool = False) -> str:
    values = list(statuses)
    if not values:
        return "unknown_dependency"
    if has_activation_record and any(value.startswith("missing_") for value in values):
        return "present_but_disabled"
    priority = [
        "missing_requires_reconstruction", "missing_requires_conversion", "missing_portable_from_br1",
        "present_but_disabled", "present_modified", "present_identical", "unknown_dependency",
    ]
    for value in priority:
        if value in values:
            return value
    return "unknown_dependency"


def load_prior_summary(project_root: Path) -> dict[str, Any]:
    path = project_root / ".local/reports/quartet_legacy_dlc/inventory_evidence/SUMMARY.json"
    summary = load_json(path)
    if summary.get("type") != "br_quartet_legacy_dlc_inventory_summary" or summary.get("tool_version") != "0.0.1":
        raise NonscenarioAuditError("stage-1 legacy DLC inventory summary is missing or incompatible")
    if int(summary.get("candidate_units", 0)) != 135 or int(summary.get("candidate_records", 0)) != 1247:
        raise NonscenarioAuditError("stage-1 summary does not contain the expected 135 units / 1247 records")
    return summary


def audit(project_root: Path, original_root: Path | None, quartet_root: Path | None, create_archive: bool = True) -> tuple[Path, dict[str, Any]]:
    version = (project_root / "workstreams/quartet_legacy_dlc/VERSION").read_text(encoding="utf-8").strip()
    if version != TOOL_VERSION:
        raise NonscenarioAuditError(f"tool/workstream version mismatch: {TOOL_VERSION} != {version}")
    prior = load_prior_summary(project_root)
    base = project_root / ".local/reports/quartet_restoration"
    pairs = {}
    for pair in ("br1_assets", "br1_language", "br1_events"):
        pairs[pair] = {
            "source_inventory": load_json(base / f"inventories/{pair}.source.json"),
            "target_inventory": load_json(base / f"inventories/{pair}.target.json"),
            "difference": load_json(base / f"differences/{pair}.json"),
        }

    report_root = project_root / ".local/reports/quartet_legacy_dlc/nonscenario_inventory_evidence"
    if report_root.exists():
        for path in sorted(report_root.rglob("*"), reverse=True):
            if path.is_file() or path.is_symlink():
                path.unlink()
            elif path.is_dir():
                path.rmdir()
    report_root.mkdir(parents=True, exist_ok=True)

    print("[stage04] indexing full first-game inventories", flush=True)
    differences = {pair: build_difference_index(data["difference"]) for pair, data in pairs.items()}
    source_entries: list[tuple[str, dict[str, Any]]] = []
    for pair, data in pairs.items():
        source_entries.extend((pair, row) for row in data["source_inventory"].get("files", []))

    content_meta: dict[str, dict[str, Any]] = {}
    member_rows: list[dict[str, Any]] = []
    content_members: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for pair, entry in source_entries:
        normalized = str(entry.get("normalized_path", ""))
        actual_path = str(entry.get("path", ""))
        if pair == "br1_language" and not actual_path.casefold().startswith("saves_jp/"):
            continue
        if not (explicit_member(normalized) or explicit_member(actual_path)):
            continue
        content_id, family, subtype, variant_state = content_from_member(normalized)
        content_meta.setdefault(content_id, {"family": family, "subtype": subtype, "source_signals": set(), "record_ids": set()})
        content_meta[content_id]["source_signals"].add("explicit_member_path")
        diff = differences[pair].get(normalized.casefold())
        if not diff:
            status, note = "unknown_dependency", "member exists in source inventory but has no difference entry"
            target = {}
            classification = ""
        else:
            status, note = member_status(diff)
            target = diff.get("target") or {}
            classification = str(diff.get("classification", ""))
        row = {
            "content_id": content_id,
            "family": family,
            "subtype": subtype,
            "variant_state": variant_state,
            "member_role": "translation_text" if translation_owned(actual_path) else ("system_table" if pair == "br1_language" else "asset_member"),
            "pair_id": pair,
            "normalized_path": normalized,
            "source_archive": entry.get("archive", ""),
            "source_path": actual_path,
            "source_size": entry.get("size", ""),
            "source_sha256": entry.get("sha256", ""),
            "target_archive": target.get("archive", ""),
            "target_path": target.get("path", ""),
            "target_size": target.get("size", ""),
            "target_sha256": target.get("sha256", ""),
            "difference_classification": classification,
            "status": status,
            "compatibility_basis": note,
            "fallback_from_br1_allowed": status in {"missing_portable_from_br1", "missing_requires_conversion"},
            "translation_owned": translation_owned(actual_path),
            "raw_payload_exported": False,
        }
        member_rows.append(row)
        content_members[content_id].append(row)

    print("[stage04] parsing JP system tables for explicit DLC identifiers", flush=True)
    lang_source = pairs["br1_language"]["source_inventory"].get("files", [])
    lang_target = pairs["br1_language"]["target_inventory"].get("files", [])
    target_entries_by_norm = {str(row.get("normalized_path", "")).casefold(): row for row in lang_target}
    parsed_source_files: dict[str, list[dict[str, Any]]] = {}
    parsed_target_files: dict[str, list[dict[str, Any]]] = {}
    parse_rows: list[dict[str, Any]] = []
    all_source_records: list[dict[str, Any]] = []

    for entry in lang_source:
        actual = str(entry.get("path", ""))
        if not actual.casefold().startswith("saves_jp/") or not actual.casefold().endswith(".xml"):
            continue
        local = workspace_file(project_root, "source", str(entry.get("archive", "")), actual)
        if not local.is_file():
            continue
        records, parse_status = parse_xml_records(local)
        norm = normalized_table_path(actual)
        parsed_source_files[norm.casefold()] = records
        parse_rows.append({"side": "source", "table_path": norm, "parse_status": parse_status, "record_count": len(records), "sha256": entry.get("sha256", "")})
        for record in records:
            record = dict(record)
            record["table_path"] = norm
            record["archive"] = entry.get("archive", "")
            record["source_path"] = actual
            all_source_records.append(record)

        target_entry = target_entries_by_norm.get(norm.casefold())
        if target_entry:
            target_local = workspace_file(project_root, "target", str(target_entry.get("archive", "")), str(target_entry.get("path", "")))
            if target_local.is_file():
                target_records, target_parse = parse_xml_records(target_local)
                parsed_target_files[norm.casefold()] = target_records
                parse_rows.append({"side": "target", "table_path": norm, "parse_status": target_parse, "record_count": len(target_records), "sha256": target_entry.get("sha256", "")})

    explicit_records = [record for record in all_source_records if record["dlc_identifiers"]]
    seed_ids = {identifier for record in explicit_records for identifier in record["dlc_identifiers"]}
    selected: dict[tuple[str, int], dict[str, Any]] = {(record["table_path"], record["index"]): record for record in explicit_records}
    frontier = set(seed_ids)
    for _ in range(2):
        next_frontier: set[str] = set()
        for record in all_source_records:
            key = (record["table_path"], record["index"])
            if key in selected:
                continue
            if frontier.intersection(record["identifiers"]):
                selected[key] = record
                next_frontier.update(identifier for identifier in record["identifiers"] if "DLC" in identifier or identifier.startswith(("COSTUME_", "CHARA_", "PC", "ITEM_", "STR_", "DLC_")))
        frontier = next_frontier - seed_ids
        seed_ids.update(next_frontier)
        if not frontier:
            break

    table_rows: list[dict[str, Any]] = []
    identifier_rows: list[dict[str, Any]] = []
    entitlement_rows: list[dict[str, Any]] = []
    content_record_statuses: dict[str, list[str]] = defaultdict(list)
    content_activation: dict[str, bool] = defaultdict(bool)
    record_nodes: list[dict[str, Any]] = []

    for record in sorted(selected.values(), key=lambda row: (row["table_path"].casefold(), row["index"])):
        dlc_ids = record["dlc_identifiers"] or [identifier for identifier in record["identifiers"] if "DLC" in identifier]
        if not dlc_ids:
            continue
        primary = sorted(dlc_ids)[0]
        content_id, family, subtype = content_from_identifier(primary)
        content_meta.setdefault(content_id, {"family": family, "subtype": subtype, "source_signals": set(), "record_ids": set()})
        content_meta[content_id]["source_signals"].add("explicit_or_linked_system_table_record")
        content_meta[content_id]["record_ids"].add(record["record_sha256"])
        target_records = parsed_target_files.get(record["table_path"].casefold(), [])
        status, note = target_record_status(record, target_records)
        content_record_statuses[content_id].append(status)
        is_activation = any(key.casefold() in {"dlctag", "st_ev_tag", "permit", "enabled", "enable", "active"} for key in record["attrs"])
        if is_activation:
            content_activation[content_id] = True
        table_rows.append(
            {
                "content_id": content_id,
                "family": family,
                "subtype": subtype,
                "table_path": record["table_path"],
                "record_index": record["index"],
                "element": record["element"],
                "record_key": record["record_key"],
                "record_sha256": record["record_sha256"],
                "dlc_identifiers": dlc_ids,
                "linked_identifiers": record["identifiers"],
                "attribute_names": sorted(record["attrs"]),
                "target_record_status": status,
                "status": status,
                "translation_owned": translation_owned(record["table_path"]),
                "activation_or_entitlement_record": is_activation,
                "raw_text_exported": False,
                "notes": note,
            }
        )
        record_nodes.append({"id": f"record:{record['record_sha256']}", "type": "system_table_record", "table": record["table_path"], "content_id": content_id})
        for identifier in record["identifiers"]:
            identifier_rows.append(
                {
                    "content_id": content_id,
                    "identifier": identifier,
                    "identifier_kind": "dlc_seed" if identifier in dlc_ids else "linked_identifier",
                    "source_table": record["table_path"],
                    "record_key": record["record_key"],
                    "target_record_status": status,
                    "translation_owned": translation_owned(record["table_path"]),
                }
            )
        if is_activation:
            entitlement_rows.append(
                {
                    "content_id": content_id,
                    "family": family,
                    "source_table": record["table_path"],
                    "record_key": record["record_key"],
                    "entitlement_identifiers": dlc_ids,
                    "source_activation_values_sha256": sha256_bytes(json.dumps(record["attrs"], sort_keys=True).encode("utf-8")),
                    "target_status": status,
                    "activation_status": "preserved_but_unresolved" if status in {"present_identical", "present_but_disabled"} else "requires_table_adaptation",
                    "notes": "No platform entitlement is synthesized; this row only records in-game activation metadata.",
                }
            )

    # Link table-defined costume/item identifiers to explicit member groups where names align.
    member_paths = [row["normalized_path"].casefold() for row in member_rows]
    for content_id, meta in list(content_meta.items()):
        if content_id in content_members:
            continue
        match = re.match(r"costume_(pc\d{2})_([a-z0-9]+)$", content_id)
        if match:
            pc, code = match.groups()
            matching = [row for row in member_rows if f"/{pc}/{pc}_dlc_{code}" in row["normalized_path"].casefold()]
            if matching:
                content_members[content_id].extend(matching)
        if content_id.startswith("dlc_item_"):
            # Item DLC is table-defined; icon/model binding needs record-level extraction in a later stage.
            pass

    catalog_rows: list[dict[str, Any]] = []
    unresolved_rows: list[dict[str, Any]] = []
    dependency_rows: list[dict[str, Any]] = []
    for content_id in sorted(content_meta, key=str.casefold):
        meta = content_meta[content_id]
        members = content_members.get(content_id, [])
        record_status_values = content_record_statuses.get(content_id, [])
        statuses = [row["status"] for row in members] + record_status_values
        status = aggregate_status(statuses, content_activation.get(content_id, False))
        if not members and record_status_values and status in {"present_identical", "present_modified"}:
            status = "present_but_disabled"
        source_member_count = len({row["normalized_path"] for row in members})
        target_member_count = sum(bool(row["target_path"]) for row in members)
        translation_count = sum(bool(row["translation_owned"]) for row in members) + sum(1 for row in table_rows if row["content_id"] == content_id and row["translation_owned"])
        record_count = sum(1 for row in table_rows if row["content_id"] == content_id)
        fallback = "allowed_after_hash_dependency_and_runtime_validation" if any(row["status"] in {"missing_portable_from_br1", "missing_requires_conversion"} for row in members) else "not_currently_required_or_not_yet_resolved"
        readiness = "metadata_only_not_buildable"
        catalog_rows.append(
            {
                "content_id": content_id,
                "family": meta["family"],
                "subtype": meta["subtype"],
                "source_signals": sorted(meta["source_signals"]),
                "source_record_count": record_count,
                "source_member_count": source_member_count,
                "target_member_count": target_member_count,
                "status": status,
                "entitlement_or_unlock_record_present": content_activation.get(content_id, False),
                "translation_owned_text_bindings": translation_count,
                "fallback_from_br1_policy": fallback,
                "dependency_closure": "open",
                "profile_readiness": readiness,
                "default_enabled": False,
                "raw_assets_embedded": False,
                "notes": "Status is member/table evidence only; runtime availability is not claimed.",
            }
        )
        required_kinds = ["member_closure", "activation_or_unlock", "ui_icon_or_thumbnail", "description_text_binding"]
        if meta["family"] == "costume_and_appearance":
            required_kinds.extend(["model_texture_material", "cloth_physics_or_wet_variant", "costume_table_binding"])
        if meta["family"] == "items_rewards_and_recipes":
            required_kinds.extend(["item_definition", "reward_or_recipe_binding", "inventory_icon"])
        if meta["family"] == "field_and_location":
            required_kinds.extend(["field_map_and_gimmick", "routing_and_unlock"])
        for kind in required_kinds:
            unresolved_rows.append(
                {
                    "dependency_id": f"{content_id}:{kind}",
                    "content_id": content_id,
                    "family": meta["family"],
                    "dependency_kind": kind,
                    "priority": "critical" if kind in {"member_closure", "activation_or_unlock"} else "high",
                    "status": "unknown_dependency",
                    "reason": "metadata inventory has not yet proven a complete member-level dependency chain",
                    "next_evidence_needed": "resolve exact table/member references and validate locally without exporting payloads",
                }
            )
            dependency_rows.append({"content_id": content_id, "dependency_kind": kind, "status": "unknown_dependency"})

    nodes = [{"id": f"content:{row['content_id']}", "type": "content", "family": row["family"], "status": row["status"]} for row in catalog_rows]
    nodes.extend(record_nodes)
    nodes.extend({"id": f"member:{sha256_bytes(row['normalized_path'].encode())[:20]}", "type": "member", "path": row["normalized_path"], "status": row["status"], "content_id": row["content_id"]} for row in member_rows)
    edges: list[dict[str, str]] = []
    for row in member_rows:
        edges.append({"from": f"content:{row['content_id']}", "to": f"member:{sha256_bytes(row['normalized_path'].encode())[:20]}", "relation": "requires_member"})
    for row in table_rows:
        edges.append({"from": f"content:{row['content_id']}", "to": f"record:{row['record_sha256']}", "relation": "defined_or_unlocked_by"})

    profiles = []
    for family in sorted({row["family"] for row in catalog_rows}, key=str.casefold):
        family_rows = [row for row in catalog_rows if row["family"] == family]
        profiles.append(
            {
                "profile_id": f"candidate_nonscenario_{family}_metadata_v1",
                "family": family,
                "status": "metadata_only_not_buildable",
                "default_enabled": False,
                "content_ids": [row["content_id"] for row in family_rows],
                "status_counts": dict(sorted(Counter(row["status"] for row in family_rows).items())),
                "raw_assets_included": False,
                "fallback_from_selected_br1_installation_allowed": True,
                "translation_text_source": "titles/blue_reflection/translation",
                "separate_translation_database": False,
                "runtime_validated": False,
            }
        )

    write_tsv(report_root / "DLC_FULL_CATALOG.tsv", [
        "content_id", "family", "subtype", "source_signals", "source_record_count", "source_member_count",
        "target_member_count", "status", "entitlement_or_unlock_record_present", "translation_owned_text_bindings",
        "fallback_from_br1_policy", "dependency_closure", "profile_readiness", "default_enabled", "raw_assets_embedded", "notes",
    ], catalog_rows)
    write_tsv(report_root / "DLC_NONSCRIPT_MEMBER_BINDINGS.tsv", [
        "content_id", "family", "subtype", "variant_state", "member_role", "pair_id", "normalized_path",
        "source_archive", "source_path", "source_size", "source_sha256", "target_archive", "target_path", "target_size",
        "target_sha256", "difference_classification", "status", "compatibility_basis", "fallback_from_br1_allowed",
        "translation_owned", "raw_payload_exported",
    ], sorted(member_rows, key=lambda row: (row["content_id"].casefold(), row["normalized_path"].casefold())))
    write_tsv(report_root / "DLC_SYSTEM_TABLE_RECORDS.tsv", [
        "content_id", "family", "subtype", "table_path", "record_index", "element", "record_key", "record_sha256",
        "dlc_identifiers", "linked_identifiers", "attribute_names", "target_record_status", "status", "translation_owned",
        "activation_or_entitlement_record", "raw_text_exported", "notes",
    ], table_rows)
    write_tsv(report_root / "DLC_IDENTIFIER_LINKS.tsv", [
        "content_id", "identifier", "identifier_kind", "source_table", "record_key", "target_record_status", "translation_owned",
    ], sorted(identifier_rows, key=lambda row: (row["content_id"].casefold(), row["identifier"].casefold(), row["source_table"].casefold())))
    write_tsv(report_root / "DLC_ENTITLEMENT_AND_UNLOCK_AUDIT.tsv", [
        "content_id", "family", "source_table", "record_key", "entitlement_identifiers", "source_activation_values_sha256",
        "target_status", "activation_status", "notes",
    ], entitlement_rows)
    shared_dependency_rows: list[dict[str, Any]] = []
    shared_patterns = (
        "item_towel_", "item_accessory_", "costume_change", "22_costume_change",
        "freespace", "freepsace", "channel_icon", "item_icon", "libraryitem",
        "mainmenustatusselectitemsreleasecondition", "mainmenutopselectitemsreleasecondition",
    )
    for pair, entry in source_entries:
        actual_path = str(entry.get("path", ""))
        normalized = str(entry.get("normalized_path", ""))
        if pair == "br1_language" and not actual_path.casefold().startswith("saves_jp/"):
            continue
        pcf = (normalized + " " + actual_path).casefold()
        matched = sorted({token for token in shared_patterns if token in pcf})
        if not matched or explicit_member(normalized) or explicit_member(actual_path):
            continue
        diff = differences[pair].get(normalized.casefold())
        if diff:
            status, note = member_status(diff)
            target = diff.get("target") or {}
        else:
            status, note, target = "unknown_dependency", "shared candidate has no unambiguous difference row", {}
        shared_dependency_rows.append({
            "candidate_id": f"shared_{sha256_bytes((pair + ':' + normalized).encode())[:16]}",
            "candidate_classes": matched,
            "pair_id": pair,
            "normalized_path": normalized,
            "source_archive": entry.get("archive", ""),
            "source_path": actual_path,
            "source_size": entry.get("size", ""),
            "source_sha256": entry.get("sha256", ""),
            "target_archive": target.get("archive", ""),
            "target_path": target.get("path", ""),
            "status": status,
            "translation_owned": translation_owned(actual_path),
            "evidence_role": "shared_dependency_candidate_not_proven_dlc",
            "notes": note,
        })

    write_tsv(report_root / "DLC_SHARED_DEPENDENCY_CANDIDATES.tsv", [
        "candidate_id", "candidate_classes", "pair_id", "normalized_path", "source_archive", "source_path",
        "source_size", "source_sha256", "target_archive", "target_path", "status", "translation_owned",
        "evidence_role", "notes",
    ], sorted(shared_dependency_rows, key=lambda row: (row["pair_id"], row["normalized_path"].casefold())))
    write_tsv(report_root / "DLC_NONSCRIPT_ASSET_COMPATIBILITY.tsv", [
        "content_id", "family", "normalized_path", "status", "compatibility_basis", "fallback_from_br1_allowed",
        "source_size", "target_size", "translation_owned",
    ], member_rows)
    write_tsv(report_root / "DLC_NONSCRIPT_UNRESOLVED_DEPENDENCIES.tsv", [
        "dependency_id", "content_id", "family", "dependency_kind", "priority", "status", "reason", "next_evidence_needed",
    ], unresolved_rows)
    write_tsv(report_root / "DLC_TABLE_PARSE_AUDIT.tsv", ["side", "table_path", "parse_status", "record_count", "sha256"], parse_rows)
    write_json(report_root / "DLC_NONSCRIPT_DEPENDENCY_GRAPH.json", {
        "type": "br_quartet_legacy_dlc_nonscenario_dependency_graph",
        "format_version": FORMAT_VERSION,
        "tool_version": TOOL_VERSION,
        "nodes": nodes,
        "edges": edges,
        "policy": {"member_level_only": True, "raw_assets_embedded": False, "translation_owned_text_not_modified": True},
    })
    write_json(report_root / "DLC_NONSCRIPT_PROFILE_CANDIDATES.json", {
        "type": "br_quartet_legacy_dlc_nonscenario_profile_candidates",
        "format_version": FORMAT_VERSION,
        "tool_version": TOOL_VERSION,
        "profiles": profiles,
        "policy": {"default_enabled": False, "profiles_activated": False, "game_modified": False, "raw_assets_embedded": False},
    })

    status_counts = Counter(row["status"] for row in catalog_rows)
    member_status_counts = Counter(row["status"] for row in member_rows)
    summary = {
        "type": "br_quartet_legacy_dlc_nonscenario_inventory_summary",
        "format_version": FORMAT_VERSION,
        "tool_version": TOOL_VERSION,
        "status": "independent_nonscenario_metadata_inventory_complete_no_build_or_game_write",
        "workstream_id": "quartet_legacy_dlc",
        "source_description": "transfer DLC from a selected first-game installation",
        "prior_text_scene_scope": {"units": prior["candidate_units"], "records": prior["candidate_records"], "treated_as_complete_dlc_catalog": False},
        "catalog_items": len(catalog_rows),
        "catalog_family_counts": dict(sorted(Counter(row["family"] for row in catalog_rows).items())),
        "catalog_status_counts": dict(sorted(status_counts.items())),
        "explicit_member_rows": len(member_rows),
        "member_status_counts": dict(sorted(member_status_counts.items())),
        "explicit_or_linked_table_records": len(table_rows),
        "unique_dlc_identifiers": len({row["identifier"] for row in identifier_rows if "DLC" in row["identifier"]}),
        "entitlement_or_unlock_rows": len(entitlement_rows),
        "shared_dependency_candidate_rows": len(shared_dependency_rows),
        "unresolved_dependency_rows": len(unresolved_rows),
        "profile_candidates": len(profiles),
        "original_root_checked": str(original_root) if original_root else "",
        "quartet_root_checked": str(quartet_root) if quartet_root else "",
        "policy": {
            "separate_from_translation": True,
            "translation_text_source": "titles/blue_reflection/translation",
            "separate_translation_database": False,
            "default_enabled": False,
            "fallback_asset_from_br1_allowed": True,
            "fallback_requires_explicit_documentation_and_validation": True,
            "raw_assets_exported": False,
            "game_modified": False,
            "git_modified": False,
        },
        "limitations": [
            "identifier and path evidence does not by itself prove that every engine-shared DLC-tagged record was sold or reachable in Blue Reflection",
            "member-level closure for nested Elixir contents, cloth physics, icons and table row references is not yet complete",
            "platform entitlement behavior is recorded but not synthesized",
            "profile candidates remain metadata-only and not buildable",
        ],
        "next_action": "close costume/item/theme dependency chains from table record to exact members and validate portable BR1 fallbacks locally",
    }
    write_json(report_root / "SUMMARY.json", summary)
    manifest = validate_report_directory(report_root)
    write_json(report_root / "REPORT_MANIFEST.json", {
        "type": "br_quartet_legacy_dlc_nonscenario_report_manifest",
        "format_version": FORMAT_VERSION,
        "tool_version": TOOL_VERSION,
        "files": manifest,
        "raw_assets_embedded": False,
    })
    if create_archive:
        make_report_archive(report_root, report_root.parent / "BR_quartet_legacy_dlc_nonscenario_inventory_evidence.tar.zst")
    return report_root, summary


def validate_report_directory(report_root: Path) -> list[dict[str, Any]]:
    required = {
        "DLC_FULL_CATALOG.tsv", "DLC_NONSCRIPT_MEMBER_BINDINGS.tsv", "DLC_SYSTEM_TABLE_RECORDS.tsv",
        "DLC_IDENTIFIER_LINKS.tsv", "DLC_ENTITLEMENT_AND_UNLOCK_AUDIT.tsv", "DLC_NONSCRIPT_ASSET_COMPATIBILITY.tsv",
        "DLC_NONSCRIPT_UNRESOLVED_DEPENDENCIES.tsv", "DLC_TABLE_PARSE_AUDIT.tsv", "DLC_SHARED_DEPENDENCY_CANDIDATES.tsv",
        "DLC_NONSCRIPT_DEPENDENCY_GRAPH.json", "DLC_NONSCRIPT_PROFILE_CANDIDATES.json", "SUMMARY.json",
    }
    missing = sorted(required - {path.name for path in report_root.iterdir() if path.is_file()})
    if missing:
        raise NonscenarioAuditError("missing report files: " + ", ".join(missing))
    with (report_root / "DLC_FULL_CATALOG.tsv").open("r", encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle, delimiter="\t"))
    if not rows:
        raise NonscenarioAuditError("full catalog is empty")
    bad = sorted({row.get("status", "") for row in rows} - ALLOWED_STATUSES)
    if bad:
        raise NonscenarioAuditError("invalid catalog status values: " + ", ".join(bad))
    manifest: list[dict[str, Any]] = []
    for path in sorted(report_root.rglob("*"), key=lambda item: item.relative_to(report_root).as_posix().casefold()):
        if not path.is_file() or path.name == "REPORT_MANIFEST.json":
            continue
        forbidden = {suffix.casefold() for suffix in path.suffixes} & FORBIDDEN_REPORT_SUFFIXES
        if forbidden:
            raise NonscenarioAuditError(f"raw or forbidden asset-like report member: {path}")
        manifest.append({"path": path.relative_to(report_root).as_posix(), "size": path.stat().st_size, "sha256": sha256_file(path)})
    return manifest


def make_report_archive(report_root: Path, output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    output.unlink(missing_ok=True)
    fd, temporary_name = tempfile.mkstemp(prefix=f".{output.name}.", suffix=".tmp", dir=output.parent)
    os.close(fd)
    temporary = Path(temporary_name)
    temporary.unlink(missing_ok=True)
    command = [
        "tar", "--sort=name", "--mtime=@0", "--owner=0", "--group=0", "--numeric-owner",
        "-C", str(report_root.parent), "--zstd", "-cf", str(temporary), report_root.name,
    ]
    result = subprocess.run(command, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, check=False)
    if result.returncode != 0:
        temporary.unlink(missing_ok=True)
        raise NonscenarioAuditError(result.stderr.decode("utf-8", errors="replace")[:4000])
    os.replace(temporary, output)


def cmd_audit(args: argparse.Namespace) -> int:
    report, summary = audit(
        Path(args.project_root).expanduser().resolve(),
        Path(args.original_root).expanduser().resolve() if args.original_root else None,
        Path(args.quartet_root).expanduser().resolve() if args.quartet_root else None,
        not args.no_report_archive,
    )
    print(f"Catalog items: {summary['catalog_items']}")
    print(f"Member rows: {summary['explicit_member_rows']}")
    print(f"Table records: {summary['explicit_or_linked_table_records']}")
    print(f"Report: {report}")
    return 0


def cmd_validate(args: argparse.Namespace) -> int:
    report = Path(args.report_root).expanduser().resolve()
    rows = validate_report_directory(report)
    print(f"Validated nonscenario metadata report: {report}")
    print(f"Files: {len(rows)}")
    return 0


def cmd_bundle(args: argparse.Namespace) -> int:
    report = Path(args.report_root).expanduser().resolve()
    validate_report_directory(report)
    output = Path(args.output).expanduser().resolve()
    make_report_archive(report, output)
    print(output)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    audit_parser = sub.add_parser("audit", help="build independent nonscenario DLC catalog")
    audit_parser.add_argument("--project-root", required=True)
    audit_parser.add_argument("--original-root")
    audit_parser.add_argument("--quartet-root")
    audit_parser.add_argument("--no-report-archive", action="store_true")
    audit_parser.set_defaults(func=cmd_audit)
    validate_parser = sub.add_parser("validate-report")
    validate_parser.add_argument("--report-root", required=True)
    validate_parser.set_defaults(func=cmd_validate)
    bundle_parser = sub.add_parser("bundle-report")
    bundle_parser.add_argument("--report-root", required=True)
    bundle_parser.add_argument("--output", required=True)
    bundle_parser.set_defaults(func=cmd_bundle)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        return int(args.func(args))
    except NonscenarioAuditError as exc:
        eprint(f"ERROR: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
