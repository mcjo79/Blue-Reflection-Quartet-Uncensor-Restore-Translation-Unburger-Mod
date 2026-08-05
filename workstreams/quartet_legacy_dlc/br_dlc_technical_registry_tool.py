#!/usr/bin/env python3
"""Seed-independent technical legacy DLC registry for Blue Reflection Quartet.

Discovery starts from complete BR1 member inventories and JP system tables.  The
text/event candidate list is optional and is used only to annotate overlap after
technical discovery has completed.  The tool is metadata-only: it never exports
raw members, modifies Translation/Restoration, or writes to either game.
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
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable, Sequence

import br_dlc_nonscenario_tool as base

TOOL_VERSION = "0.0.3"
FORMAT_VERSION = 1
REPORT_DIR_NAME = "technical_registry_evidence"
REPORT_ARCHIVE_NAME = "BR_quartet_legacy_dlc_technical_registry_evidence.tar.zst"
TECHNICAL_TYPES = {
    "costume_or_outfit",
    "accessory",
    "item_or_reward",
    "recipe_or_system_bonus",
    "theme_or_ui_content",
    "unlock_or_entitlement",
    "shared_asset_dependency",
    "unknown_legacy_dlc_candidate",
}
ALLOWED_STATUSES = base.ALLOWED_STATUSES
FORBIDDEN_REPORT_SUFFIXES = base.FORBIDDEN_REPORT_SUFFIXES

ACTIVATION_KEY_RE = re.compile(
    r"(?:^|_)(?:dlc|entitlement|permit|enable|enabled|active|unlock|release|condition|flag|"
    r"st_ev|event|product|appid|app_id|shop|availability)(?:$|_)", re.I
)
COSTUME_RE = re.compile(r"costume|outfit|swim|bikini|towel|uniform|wear|chara_.*_dlc|pc\d{2}_dlc", re.I)
ACCESSORY_RE = re.compile(r"accessory|ornament|headgear|head_item|item_accessory", re.I)
RECIPE_RE = re.compile(r"recipe|make_item|craft|synthesis|bonus|system_bonus", re.I)
ITEM_RE = re.compile(r"item_dlc|dlc_item|item_or_reward|reward|equipment|equip", re.I)
THEME_RE = re.compile(r"freespace|freepsace|channel_skin|theme|skin_dlc|(?:^|[_/])icon(?:[_/]|$)|thumbnail|bgm|wallpaper|(?:^|[_/])ui(?:[_/]|$)", re.I)
SHARED_RE = re.compile(
    r"item_towel_|item_accessory_|costume_change|22_costume_change|freespace|freepsace|"
    r"channel_icon|item_icon|libraryitem|releasecondition", re.I
)
IDENTIFIER_TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z0-9_./-]{2,}")


class TechnicalRegistryError(RuntimeError):
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
        return "True" if value else "False"
    if isinstance(value, (list, tuple, set)):
        return ";".join(str(item) for item in value)
    if isinstance(value, dict):
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return str(value)


def write_tsv(path: Path, fieldnames: Sequence[str], rows: Iterable[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, delimiter="\t", lineterminator="\n", extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({name: scalar(row.get(name, "")) for name in fieldnames})


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=False) + "\n", encoding="utf-8")


def clean_report_root(path: Path) -> None:
    if path.exists():
        for item in sorted(path.rglob("*"), key=lambda p: len(p.parts), reverse=True):
            if item.is_file() or item.is_symlink():
                item.unlink()
            elif item.is_dir():
                item.rmdir()
    path.mkdir(parents=True, exist_ok=True)


def load_pair(project_root: Path, pair: str) -> dict[str, Any]:
    root = project_root / ".local/reports/quartet_restoration"
    return {
        "source_inventory": base.load_json(root / f"inventories/{pair}.source.json"),
        "target_inventory": base.load_json(root / f"inventories/{pair}.target.json"),
        "difference": base.load_json(root / f"differences/{pair}.json"),
    }


def normalize_identifier(value: str) -> str:
    return value.strip().upper()


def record_activation_fields(record: dict[str, Any]) -> list[tuple[str, str]]:
    result: list[tuple[str, str]] = []
    for key, value in record.get("attrs", {}).items():
        key_text = str(key)
        value_text = str(value)
        # A DLC-looking value in BaseTag/CharaTag identifies content, not an
        # entitlement.  Only fields whose names encode activation semantics are
        # admitted to the unlock map.
        if ACTIVATION_KEY_RE.search(key_text):
            result.append((key_text, value_text))
    return sorted(result, key=lambda pair: (pair[0].casefold(), pair[1].casefold()))


def record_signal(record: dict[str, Any]) -> str:
    attrs = record.get("attrs", {})
    return " ".join(
        [record.get("table_path", ""), record.get("element", ""), record.get("record_key", "")]
        + list(attrs.keys())
        + list(attrs.values())
        + list(record.get("identifiers", []))
        + list(record.get("dlc_identifiers", []))
    )


def technical_type_for_signal(signal: str, *, activation: bool = False, shared: bool = False) -> str:
    if shared:
        return "shared_asset_dependency"
    if activation:
        return "unlock_or_entitlement"
    if ACCESSORY_RE.search(signal):
        return "accessory"
    if COSTUME_RE.search(signal):
        return "costume_or_outfit"
    if RECIPE_RE.search(signal):
        return "recipe_or_system_bonus"
    if ITEM_RE.search(signal):
        return "item_or_reward"
    if THEME_RE.search(signal):
        return "theme_or_ui_content"
    return "unknown_legacy_dlc_candidate"


def primary_content_from_record(record: dict[str, Any], known_ids: set[str]) -> tuple[str, str, str]:
    identifiers = [normalize_identifier(x) for x in record.get("dlc_identifiers", [])]
    identifiers.extend(normalize_identifier(x) for x in record.get("identifiers", []) if normalize_identifier(x) in known_ids)
    identifiers = sorted(set(identifiers), key=lambda x: (0 if "DLC" in x else 1, x.casefold()))
    for identifier in identifiers:
        content_id, family, subtype = base.content_from_identifier(identifier)
        if content_id:
            return content_id, family, subtype
    digest = record.get("record_sha256") or sha256_bytes(record_signal(record).encode("utf-8"))
    return f"technical_record_{digest[:16]}", "unknown_table_defined_dlc", "seed_independent_table_candidate"


def member_technical_type(path: str, family: str, subtype: str, *, shared: bool) -> str:
    signal = f"{path} {family} {subtype}"
    if ACCESSORY_RE.search(signal):
        return "accessory"
    if COSTUME_RE.search(signal):
        return "costume_or_outfit"
    if RECIPE_RE.search(signal):
        return "recipe_or_system_bonus"
    if ITEM_RE.search(signal):
        return "item_or_reward"
    if THEME_RE.search(signal):
        return "theme_or_ui_content"
    return "shared_asset_dependency" if shared else "unknown_legacy_dlc_candidate"


def shared_member(path: str) -> bool:
    return bool(SHARED_RE.search(path)) and not base.explicit_member(path)


def member_role(path: str, technical_type: str) -> str:
    p = path.casefold()
    if base.translation_owned(path):
        return "translation_owned_text_reference"
    if p.endswith(".g1t") or "texture" in p:
        return "texture_or_thumbnail"
    if p.endswith(".g1m") or p.endswith(".elixir.gz"):
        return "model_material_or_container"
    if "icon" in p or "thumbnail" in p:
        return "ui_icon_or_thumbnail"
    if "physics" in p or "cloth" in p or p.endswith(".g1a"):
        return "cloth_physics_or_animation"
    if technical_type == "unlock_or_entitlement":
        return "activation_metadata"
    return "asset_member"


def aggregate_status(statuses: Iterable[str]) -> str:
    values = list(statuses)
    if not values:
        return "unknown_dependency"
    priority = [
        "missing_requires_reconstruction",
        "missing_requires_conversion",
        "missing_portable_from_br1",
        "present_but_disabled",
        "present_modified",
        "present_identical",
        "unknown_dependency",
    ]
    for status in priority:
        if status in values:
            return status
    return "unknown_dependency"


def load_optional_text_seed(project_root: Path) -> tuple[set[str], str]:
    path = project_root / "titles/blue_reflection/modules/quartet_legacy_dlc/mappings/text_candidate_units.tsv"
    if not path.is_file():
        return set(), "not_available_discovery_still_complete"
    values: set[str] = set()
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle, delimiter="\t"):
            for key in ("logical_path", "internal_path"):
                value = str(row.get(key, "")).replace("\\", "/").casefold()
                if value:
                    values.add(value)
    return values, "optional_overlap_annotation_only"


def text_seed_overlap(paths: Iterable[str], text_seed_paths: set[str]) -> str:
    if not text_seed_paths:
        return "not_evaluated"
    normalized = [str(path).replace("\\", "/").casefold() for path in paths if path]
    for path in normalized:
        if path in text_seed_paths:
            return "yes"
        name = Path(path).name
        if any(Path(seed).name == name for seed in text_seed_paths):
            return "yes"
    return "no"


def parse_system_tables(project_root: Path, pair: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[str, list[dict[str, Any]]], list[dict[str, Any]]]:
    source_files = pair["source_inventory"].get("files", [])
    target_files = pair["target_inventory"].get("files", [])
    target_by_norm = {str(row.get("normalized_path", "")).casefold(): row for row in target_files}
    source_records: list[dict[str, Any]] = []
    target_records_by_table: dict[str, list[dict[str, Any]]] = {}
    parse_audit: list[dict[str, Any]] = []

    for source in source_files:
        actual = str(source.get("path", ""))
        if not actual.casefold().startswith("saves_jp/") or not actual.casefold().endswith(".xml"):
            continue
        normalized = base.normalized_table_path(actual)
        local = base.workspace_file(project_root, "source", str(source.get("archive", "")), actual)
        if not local.is_file():
            parse_audit.append({"side": "source", "table_path": normalized, "parse_status": "workspace_missing", "record_count": 0, "sha256": source.get("sha256", "")})
            continue
        records, status = base.parse_xml_records(local)
        parse_audit.append({"side": "source", "table_path": normalized, "parse_status": status, "record_count": len(records), "sha256": source.get("sha256", "")})
        for record in records:
            enriched = dict(record)
            enriched.update({"table_path": normalized, "source_archive": source.get("archive", ""), "source_path": actual, "table_sha256": source.get("sha256", "")})
            source_records.append(enriched)

        target = target_by_norm.get(str(source.get("normalized_path", "")).casefold())
        if not target:
            target_records_by_table[normalized.casefold()] = []
            parse_audit.append({"side": "target", "table_path": normalized, "parse_status": "table_missing", "record_count": 0, "sha256": ""})
            continue
        target_actual = str(target.get("path", ""))
        target_local = base.workspace_file(project_root, "target", str(target.get("archive", "")), target_actual)
        if not target_local.is_file():
            target_records_by_table[normalized.casefold()] = []
            parse_audit.append({"side": "target", "table_path": normalized, "parse_status": "workspace_missing", "record_count": 0, "sha256": target.get("sha256", "")})
            continue
        target_records, target_status = base.parse_xml_records(target_local)
        target_records_by_table[normalized.casefold()] = target_records
        parse_audit.append({"side": "target", "table_path": normalized, "parse_status": target_status, "record_count": len(target_records), "sha256": target.get("sha256", "")})
    return source_records, target_records_by_table, parse_audit


def strong_content_identifier(identifier: str) -> bool:
    value = normalize_identifier(identifier)
    return bool(
        "DLC" in value
        or COSTUME_RE.search(value)
        or ACCESSORY_RE.search(value)
        or ITEM_RE.search(value)
        or RECIPE_RE.search(value)
        or THEME_RE.search(value)
    )


def discover_records(records: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], set[str]]:
    explicit: list[dict[str, Any]] = []
    known_ids: set[str] = set()
    for record in records:
        if base.translation_owned(record.get("table_path", "")):
            continue
        ids = {normalize_identifier(x) for x in record.get("identifiers", [])}
        dlc_ids = {normalize_identifier(x) for x in record.get("dlc_identifiers", [])}
        strong_ids = {value for value in ids | dlc_ids if strong_content_identifier(value)}
        signal = record_signal(record)
        if dlc_ids or base.DLC_ID_RE.search(signal):
            explicit.append(record)
            known_ids.update(strong_ids)
            known_ids.update(dlc_ids)

    selected = {record["record_sha256"]: record for record in explicit}
    # One bounded reference-closure pass.  It accepts only records sharing a
    # strong DLC/content identifier and avoids generic IDs that would pull most
    # of the game's ordinary tables into the registry.
    for record in records:
        if record["record_sha256"] in selected or base.translation_owned(record.get("table_path", "")):
            continue
        ids = {normalize_identifier(x) for x in record.get("identifiers", [])}
        shared = ids & known_ids
        if shared and any(strong_content_identifier(value) for value in shared):
            selected[record["record_sha256"]] = record
    return sorted(selected.values(), key=lambda r: (r["table_path"].casefold(), int(r["index"]), r["record_sha256"])), known_ids


def audit(project_root: Path, original_root: Path | None, quartet_root: Path | None, create_archive: bool = True) -> tuple[Path, dict[str, Any]]:
    version = (project_root / "workstreams/quartet_legacy_dlc/VERSION").read_text(encoding="utf-8").strip()
    if version != TOOL_VERSION:
        raise TechnicalRegistryError(f"tool/workstream version mismatch: {TOOL_VERSION} != {version}")

    print("[stage07] loading complete BR1/Quartet inventories", flush=True)
    pairs = {pair: load_pair(project_root, pair) for pair in ("br1_assets", "br1_language")}
    diff_indexes = {pair: base.build_difference_index(data["difference"]) for pair, data in pairs.items()}
    text_seed_paths, text_seed_mode = load_optional_text_seed(project_root)

    print("[stage07] parsing complete JP system tables without text-seed gating", flush=True)
    all_records, target_records_by_table, parse_rows = parse_system_tables(project_root, pairs["br1_language"])
    candidate_records, known_ids = discover_records(all_records)

    report_root = project_root / ".local/reports/quartet_legacy_dlc" / REPORT_DIR_NAME
    clean_report_root(report_root)

    content: dict[str, dict[str, Any]] = {}
    table_rows: list[dict[str, Any]] = []
    flag_rows: list[dict[str, Any]] = []
    member_rows: list[dict[str, Any]] = []
    shared_entries: set[str] = set()

    def ensure_content(content_id: str, technical_type: str, subtype: str, signal: str) -> dict[str, Any]:
        key = f"{content_id}:{technical_type}"
        row = content.setdefault(key, {
            "registry_id": f"registry_{sha256_bytes(key.encode())[:20]}",
            "content_id": content_id,
            "technical_type": technical_type,
            "subtype": subtype,
            "discovery_signals": set(),
            "source_members": set(),
            "target_members": set(),
            "source_tables": set(),
            "flag_ids": set(),
            "dependency_ids": set(),
            "statuses": [],
            "compatibility_notes": set(),
            "record_ids": set(),
        })
        row["discovery_signals"].add(signal)
        return row

    print(f"[stage07] classifying {len(candidate_records)} seed-independent system records", flush=True)
    for record in candidate_records:
        content_id, family, subtype = primary_content_from_record(record, known_ids)
        signal = record_signal(record)
        primary_type = technical_type_for_signal(signal)
        target_records = target_records_by_table.get(record["table_path"].casefold(), [])
        status, note = base.target_record_status(record, target_records)
        primary = ensure_content(content_id, primary_type, subtype, "system_table_record")
        primary["source_tables"].add(record["table_path"])
        primary["record_ids"].add(record["record_sha256"])
        primary["statuses"].append(status)
        primary["compatibility_notes"].add(note)

        # A single technical record may define a DLC item and independently bind
        # a recipe/bonus, accessory or UI registration.  Preserve those roles as
        # separate registry types rather than collapsing them into one label.
        secondary_types: list[str] = []
        if RECIPE_RE.search(signal) and primary_type != "recipe_or_system_bonus":
            secondary_types.append("recipe_or_system_bonus")
        if ACCESSORY_RE.search(signal) and primary_type != "accessory":
            secondary_types.append("accessory")
        if THEME_RE.search(signal) and primary_type != "theme_or_ui_content":
            secondary_types.append("theme_or_ui_content")
        for secondary_type in sorted(set(secondary_types)):
            secondary = ensure_content(content_id, secondary_type, f"linked_{secondary_type}", "system_table_secondary_role")
            secondary["source_tables"].add(record["table_path"])
            secondary["record_ids"].add(record["record_sha256"])
            secondary["statuses"].append(status)
            secondary["compatibility_notes"].add(note)
            primary["dependency_ids"].add(secondary["registry_id"])

        activation_fields = record_activation_fields(record)
        activation = bool(activation_fields)
        table_rows.append({
            "registry_id": primary["registry_id"],
            "content_id": content_id,
            "technical_type": primary_type,
            "table_path": record["table_path"],
            "record_index": record["index"],
            "element": record["element"],
            "record_key": record["record_key"],
            "record_sha256": record["record_sha256"],
            "linked_identifiers": record.get("identifiers", []),
            "dlc_identifiers": record.get("dlc_identifiers", []),
            "attribute_names": sorted(record.get("attrs", {})),
            "target_status": status,
            "activation_or_unlock_evidence": activation,
            "translation_owned": base.translation_owned(record["table_path"]),
            "raw_text_exported": False,
        })

        if activation:
            unlock = ensure_content(content_id, "unlock_or_entitlement", "activation_or_release_condition", "flag_or_condition_record")
            unlock["source_tables"].add(record["table_path"])
            unlock["record_ids"].add(record["record_sha256"])
            unlock["statuses"].append("present_but_disabled" if status in {"present_identical", "present_modified"} else status)
            unlock["compatibility_notes"].add("activation metadata recorded; no platform entitlement synthesized")
            primary["dependency_ids"].add(unlock["registry_id"])
            for key_name, value in activation_fields:
                identifiers = sorted(set(base.extract_identifiers([value]) + base.extract_dlc_identifiers([value])))
                flag_id = identifiers[0] if identifiers else f"value_sha256:{sha256_bytes(value.encode())[:16]}"
                unlock["flag_ids"].add(flag_id)
                flag_rows.append({
                    "registry_id": unlock["registry_id"],
                    "content_id": content_id,
                    "source_table": record["table_path"],
                    "record_key": record["record_key"],
                    "field_name": key_name,
                    "flag_or_condition_id": flag_id,
                    "source_record_sha256": record["record_sha256"],
                    "source_value_sha256": sha256_bytes(value.encode("utf-8")),
                    "target_status": status,
                    "activation_status": "preserved_but_unresolved" if status in {"present_identical", "present_modified", "present_but_disabled"} else "requires_record_adaptation",
                    "platform_entitlement_synthesized": False,
                    "notes": "Metadata only; no entitlement or unlock condition is activated.",
                })

    print("[stage07] mapping explicit and shared BR1 members", flush=True)
    for pair_name, pair in pairs.items():
        for entry in pair["source_inventory"].get("files", []):
            actual = str(entry.get("path", ""))
            normalized = str(entry.get("normalized_path", ""))
            if pair_name == "br1_language" and not actual.casefold().startswith("saves_jp/"):
                continue
            is_explicit = base.explicit_member(normalized) or base.explicit_member(actual)
            is_shared = shared_member(normalized) or shared_member(actual)
            if not is_explicit and not is_shared:
                continue
            if is_explicit:
                content_id, family, subtype, variant_state = base.content_from_member(normalized)
            else:
                digest = sha256_bytes((pair_name + ":" + normalized).encode())[:16]
                content_id, family, subtype, variant_state = f"shared_asset_{digest}", "shared_asset_dependency", "shared_member_candidate", "shared"
            technical_type = member_technical_type(normalized, family, subtype, shared=is_shared)
            registry = ensure_content(content_id, technical_type, subtype, "explicit_member_path" if is_explicit else "shared_member_pattern")
            if is_shared:
                shared_entries.add(registry["registry_id"])
            diff = diff_indexes[pair_name].get(normalized.casefold())
            if diff:
                status, note = base.member_status(diff)
                target = diff.get("target") or {}
                classification = str(diff.get("classification", ""))
            else:
                status, note, target, classification = "unknown_dependency", "member has no unambiguous difference row", {}, ""
            registry["source_members"].add(normalized)
            if target.get("path"):
                registry["target_members"].add(str(target.get("path")))
            registry["statuses"].append(status)
            registry["compatibility_notes"].add(note)
            member_rows.append({
                "registry_id": registry["registry_id"],
                "content_id": content_id,
                "technical_type": technical_type,
                "subtype": subtype,
                "variant_state": variant_state,
                "member_role": member_role(normalized, technical_type),
                "pair_id": pair_name,
                "normalized_path": normalized,
                "source_archive": entry.get("archive", ""),
                "source_path": actual,
                "source_size": entry.get("size", ""),
                "source_sha256": entry.get("sha256", ""),
                "target_archive": target.get("archive", ""),
                "target_path": target.get("path", ""),
                "target_size": target.get("size", ""),
                "target_sha256": target.get("sha256", ""),
                "difference_classification": classification,
                "compatibility_status": status,
                "compatibility_basis": note,
                "fallback_from_br1_allowed": status in {"missing_portable_from_br1", "missing_requires_conversion"},
                "translation_owned": base.translation_owned(actual),
                "raw_payload_exported": False,
            })

    # Every DLC item/reward is also audited for a possible recipe or system
    # bonus path.  When no concrete recipe record was found, retain a separate
    # unknown dependency entry rather than silently assuming that no recipe or
    # bonus exists.
    item_rows = [row for row in list(content.values()) if row["technical_type"] == "item_or_reward"]
    for item in item_rows:
        recipe_key = f"{item['content_id']}:recipe_or_system_bonus"
        if recipe_key not in content:
            recipe = ensure_content(item["content_id"], "recipe_or_system_bonus", "unresolved_recipe_or_system_bonus_dependency", "required_dependency_class")
            recipe["statuses"].append("unknown_dependency")
            recipe["compatibility_notes"].add("no exact recipe or system bonus record has been proven yet")
            item["dependency_ids"].add(recipe["registry_id"])

    # Connect shared technical dependencies to content classes without claiming exact runtime use.
    shared_rows = [row for row in content.values() if row["registry_id"] in shared_entries]
    normal_rows = [row for row in content.values() if row["registry_id"] not in shared_entries]
    for shared in shared_rows:
        signal = " ".join(shared["source_members"]) + " " + shared["subtype"]
        if ACCESSORY_RE.search(signal):
            compatible_types = {"accessory", "costume_or_outfit"}
        elif THEME_RE.search(signal):
            compatible_types = {"theme_or_ui_content", "item_or_reward"}
        elif COSTUME_RE.search(signal):
            compatible_types = {"costume_or_outfit"}
        else:
            compatible_types = {"costume_or_outfit", "accessory", "item_or_reward", "theme_or_ui_content"}
        for target in normal_rows:
            if target["technical_type"] in compatible_types:
                target["dependency_ids"].add(shared["registry_id"])

    registry_rows: list[dict[str, Any]] = []
    unresolved_rows: list[dict[str, Any]] = []
    for key in sorted(content, key=str.casefold):
        item = content[key]
        status = aggregate_status(item["statuses"])
        paths = sorted(item["source_members"]) + sorted(item["source_tables"])
        overlap = text_seed_overlap(paths, text_seed_paths)
        missing_kinds: list[str] = []
        if not item["source_members"] and item["technical_type"] not in {"unlock_or_entitlement", "unknown_legacy_dlc_candidate"}:
            missing_kinds.append("exact_source_member_binding")
        if not item["source_tables"] and item["technical_type"] not in {"shared_asset_dependency"}:
            missing_kinds.append("system_table_binding")
        if item["technical_type"] in {"costume_or_outfit", "accessory"}:
            missing_kinds.extend(["model_texture_material_closure", "cloth_physics_or_variant_closure", "icon_or_thumbnail_binding"])
        elif item["technical_type"] == "item_or_reward":
            missing_kinds.extend(["item_definition_and_inventory_binding", "reward_source", "icon_or_thumbnail_binding"])
        elif item["technical_type"] == "recipe_or_system_bonus":
            missing_kinds.extend(["recipe_or_bonus_trigger", "result_item_binding"])
        elif item["technical_type"] == "theme_or_ui_content":
            missing_kinds.extend(["ui_registration", "icon_description_or_skin_binding"])
        elif item["technical_type"] == "unlock_or_entitlement":
            missing_kinds.extend(["activation_semantics", "platform_entitlement_mapping"])
        elif item["technical_type"] == "unknown_legacy_dlc_candidate":
            missing_kinds.extend(["technical_type_resolution", "dependency_owner_resolution"])
        if not item["dependency_ids"] and item["technical_type"] not in {"shared_asset_dependency", "unlock_or_entitlement"}:
            missing_kinds.append("dependency_graph_closure")
        missing_kinds = sorted(set(missing_kinds), key=str.casefold)

        registry_rows.append({
            "registry_id": item["registry_id"],
            "content_id": item["content_id"],
            "technical_type": item["technical_type"],
            "subtype": item["subtype"],
            "discovery_basis": sorted(item["discovery_signals"]),
            "text_seed_overlap": overlap,
            "source_member_count": len(item["source_members"]),
            "target_member_count": len(item["target_members"]),
            "source_members": sorted(item["source_members"]),
            "quartet_members": sorted(item["target_members"]),
            "source_tables": sorted(item["source_tables"]),
            "flag_or_condition_ids": sorted(item["flag_ids"]),
            "asset_dependency_ids": sorted(item["dependency_ids"]),
            "compatibility_status": status,
            "compatibility_classification": sorted(item["compatibility_notes"]),
            "unresolved_dependency_count": len(missing_kinds),
            "fallback_from_br1_allowed": status in {"missing_portable_from_br1", "missing_requires_conversion"},
            "fallback_policy": "allowed_after_member_hash_format_dependency_and_runtime_validation",
            "translation_text_source": "titles/blue_reflection/translation",
            "separate_translation_database": False,
            "default_enabled": False,
            "raw_assets_embedded": False,
            "notes": "Technical discovery is independent of text candidate units; overlap is annotation only.",
        })
        for dependency_kind in missing_kinds:
            unresolved_rows.append({
                "candidate_id": f"{item['registry_id']}:{dependency_kind}",
                "registry_id": item["registry_id"],
                "content_id": item["content_id"],
                "technical_type": item["technical_type"],
                "dependency_kind": dependency_kind,
                "priority": "critical" if dependency_kind in {"exact_source_member_binding", "activation_semantics", "technical_type_resolution"} else "high",
                "compatibility_status": status,
                "text_seed_overlap": overlap,
                "reason": "seed-independent audit has not proven this dependency at exact member/record level",
                "next_evidence_needed": "resolve exact BR1 member/table/flag references and verify Quartet compatibility locally",
            })

    inventory_rows = [row for row in registry_rows if row["text_seed_overlap"] != "yes"]

    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []
    for row in registry_rows:
        nodes.append({"id": row["registry_id"], "node_type": "technical_registry_entry", "content_id": row["content_id"], "technical_type": row["technical_type"], "status": row["compatibility_status"]})
        for dep in row["asset_dependency_ids"]:
            edges.append({"from": row["registry_id"], "to": dep, "relation": "depends_on_shared_asset_candidate", "proven_runtime_dependency": False})
    for row in member_rows:
        member_id = f"member:{sha256_bytes((row['pair_id'] + ':' + row['normalized_path']).encode())[:20]}"
        nodes.append({"id": member_id, "node_type": "member", "path": row["normalized_path"], "status": row["compatibility_status"], "raw_payload_embedded": False})
        edges.append({"from": row["registry_id"], "to": member_id, "relation": "source_or_target_member_binding"})
    for row in table_rows:
        record_id = f"record:{row['record_sha256']}"
        nodes.append({"id": record_id, "node_type": "system_table_record", "table": row["table_path"], "status": row["target_status"]})
        edges.append({"from": row["registry_id"], "to": record_id, "relation": "defined_by_system_record"})
    for row in flag_rows:
        flag_id = f"flag:{sha256_bytes((row['source_table'] + ':' + row['record_key'] + ':' + row['field_name']).encode())[:20]}"
        nodes.append({"id": flag_id, "node_type": "unlock_or_entitlement_condition", "identifier": row["flag_or_condition_id"], "target_status": row["target_status"]})
        edges.append({"from": row["registry_id"], "to": flag_id, "relation": "controlled_by"})

    print("[stage07] writing technical registry and dependency reports", flush=True)
    registry_fields = [
        "registry_id", "content_id", "technical_type", "subtype", "discovery_basis", "text_seed_overlap",
        "source_member_count", "target_member_count", "source_members", "quartet_members", "source_tables",
        "flag_or_condition_ids", "asset_dependency_ids", "compatibility_status", "compatibility_classification",
        "unresolved_dependency_count", "fallback_from_br1_allowed", "fallback_policy", "translation_text_source",
        "separate_translation_database", "default_enabled", "raw_assets_embedded", "notes",
    ]
    write_tsv(report_root / "DLC_TECHNICAL_REGISTRY.tsv", registry_fields, registry_rows)
    write_tsv(report_root / "DLC_TEXT_INDEPENDENT_INVENTORY.tsv", registry_fields, inventory_rows)
    write_tsv(report_root / "DLC_TECHNICAL_MEMBER_BINDINGS.tsv", [
        "registry_id", "content_id", "technical_type", "subtype", "variant_state", "member_role", "pair_id",
        "normalized_path", "source_archive", "source_path", "source_size", "source_sha256", "target_archive",
        "target_path", "target_size", "target_sha256", "difference_classification", "compatibility_status",
        "compatibility_basis", "fallback_from_br1_allowed", "translation_owned", "raw_payload_exported",
    ], sorted(member_rows, key=lambda row: (row["registry_id"], row["normalized_path"].casefold())))
    write_tsv(report_root / "DLC_TECHNICAL_SYSTEM_RECORDS.tsv", [
        "registry_id", "content_id", "technical_type", "table_path", "record_index", "element", "record_key",
        "record_sha256", "linked_identifiers", "dlc_identifiers", "attribute_names", "target_status",
        "activation_or_unlock_evidence", "translation_owned", "raw_text_exported",
    ], table_rows)
    write_tsv(report_root / "DLC_UNLOCK_FLAG_MAP.tsv", [
        "registry_id", "content_id", "source_table", "record_key", "field_name", "flag_or_condition_id",
        "source_record_sha256", "source_value_sha256", "target_status", "activation_status",
        "platform_entitlement_synthesized", "notes",
    ], flag_rows)
    write_tsv(report_root / "DLC_UNRESOLVED_TECHNICAL_CANDIDATES.tsv", [
        "candidate_id", "registry_id", "content_id", "technical_type", "dependency_kind", "priority",
        "compatibility_status", "text_seed_overlap", "reason", "next_evidence_needed",
    ], unresolved_rows)
    write_tsv(report_root / "DLC_TECHNICAL_TABLE_PARSE_AUDIT.tsv", ["side", "table_path", "parse_status", "record_count", "sha256"], parse_rows)
    write_json(report_root / "DLC_ASSET_DEPENDENCY_GRAPH.json", {
        "type": "br_quartet_legacy_dlc_seed_independent_asset_dependency_graph",
        "format_version": FORMAT_VERSION,
        "tool_version": TOOL_VERSION,
        "nodes": nodes,
        "edges": edges,
        "policy": {
            "member_level_only": True,
            "discovery_depends_on_text_candidate_units": False,
            "text_seed_overlap_is_annotation_only": True,
            "raw_assets_embedded": False,
            "translation_owned_text_not_modified": True,
        },
    })

    type_counts = Counter(row["technical_type"] for row in registry_rows)
    status_counts = Counter(row["compatibility_status"] for row in registry_rows)
    summary = {
        "type": "br_quartet_legacy_dlc_seed_independent_technical_registry_summary",
        "format_version": FORMAT_VERSION,
        "tool_version": TOOL_VERSION,
        "status": "seed_independent_metadata_registry_complete_no_build_or_game_write",
        "workstream_id": "quartet_legacy_dlc",
        "discovery_entry_point": "complete_br1_system_tables_flags_and_asset_member_inventories",
        "text_candidate_units_required": False,
        "text_seed_mode": text_seed_mode,
        "technical_registry_entries": len(registry_rows),
        "text_independent_inventory_entries": len(inventory_rows),
        "technical_type_counts": dict(sorted(type_counts.items())),
        "compatibility_status_counts": dict(sorted(status_counts.items())),
        "source_system_records_scanned": len(all_records),
        "candidate_system_records": len(candidate_records),
        "technical_member_bindings": len(member_rows),
        "unlock_or_flag_rows": len(flag_rows),
        "dependency_graph_nodes": len(nodes),
        "dependency_graph_edges": len(edges),
        "unresolved_candidates": len(unresolved_rows),
        "original_root_checked": str(original_root) if original_root else "",
        "quartet_root_checked": str(quartet_root) if quartet_root else "",
        "policy": {
            "translation_text_source": "titles/blue_reflection/translation",
            "separate_translation_database": False,
            "text_seed_unchanged": True,
            "default_enabled": False,
            "fallback_asset_from_br1_allowed": True,
            "fallback_requires_explicit_documentation_and_validation": True,
            "raw_assets_exported": False,
            "game_modified": False,
            "git_modified": False,
        },
        "limitations": [
            "shared asset links are dependency candidates until exact table/member references or runtime behavior confirm ownership",
            "platform entitlement behavior is mapped but never synthesized",
            "nested Elixir model/texture/material/physics closure remains incomplete for some entries",
            "technical registry entries remain metadata-only and not buildable",
        ],
        "next_action": "resolve exact member closure for costumes/accessories/items/themes and prove unlock chains before building any local profile",
    }
    write_json(report_root / "SUMMARY.json", summary)
    manifest = validate_report_directory(report_root)
    write_json(report_root / "REPORT_MANIFEST.json", {
        "type": "br_quartet_legacy_dlc_seed_independent_technical_registry_manifest",
        "format_version": FORMAT_VERSION,
        "tool_version": TOOL_VERSION,
        "files": manifest,
        "raw_assets_embedded": False,
    })
    if create_archive:
        make_report_archive(report_root, report_root.parent / REPORT_ARCHIVE_NAME)
    return report_root, summary


def validate_report_directory(report_root: Path) -> list[dict[str, Any]]:
    required = {
        "DLC_TECHNICAL_REGISTRY.tsv",
        "DLC_TEXT_INDEPENDENT_INVENTORY.tsv",
        "DLC_TECHNICAL_MEMBER_BINDINGS.tsv",
        "DLC_TECHNICAL_SYSTEM_RECORDS.tsv",
        "DLC_UNLOCK_FLAG_MAP.tsv",
        "DLC_ASSET_DEPENDENCY_GRAPH.json",
        "DLC_UNRESOLVED_TECHNICAL_CANDIDATES.tsv",
        "DLC_TECHNICAL_TABLE_PARSE_AUDIT.tsv",
        "SUMMARY.json",
    }
    names = {path.name for path in report_root.iterdir() if path.is_file()}
    missing = sorted(required - names)
    if missing:
        raise TechnicalRegistryError("missing report files: " + ", ".join(missing))
    with (report_root / "DLC_TECHNICAL_REGISTRY.tsv").open("r", encoding="utf-8", newline="") as handle:
        registry = list(csv.DictReader(handle, delimiter="\t"))
    if not registry:
        raise TechnicalRegistryError("technical registry is empty")
    bad_types = sorted({row.get("technical_type", "") for row in registry} - TECHNICAL_TYPES)
    if bad_types:
        raise TechnicalRegistryError("invalid technical types: " + ", ".join(bad_types))
    bad_statuses = sorted({row.get("compatibility_status", "") for row in registry} - ALLOWED_STATUSES)
    if bad_statuses:
        raise TechnicalRegistryError("invalid compatibility statuses: " + ", ".join(bad_statuses))
    summary = base.load_json(report_root / "SUMMARY.json")
    if summary.get("text_candidate_units_required") is not False:
        raise TechnicalRegistryError("technical registry is not marked as text-seed independent")
    if set(summary.get("technical_type_counts", {})) - TECHNICAL_TYPES:
        raise TechnicalRegistryError("summary contains unsupported technical types")
    manifest: list[dict[str, Any]] = []
    for path in sorted(report_root.rglob("*"), key=lambda item: item.relative_to(report_root).as_posix().casefold()):
        if not path.is_file() or path.name == "REPORT_MANIFEST.json":
            continue
        if {suffix.casefold() for suffix in path.suffixes} & FORBIDDEN_REPORT_SUFFIXES:
            raise TechnicalRegistryError(f"forbidden asset-like report file: {path}")
        manifest.append({"path": path.relative_to(report_root).as_posix(), "size": path.stat().st_size, "sha256": sha256_file(path)})
    return manifest


def make_report_archive(report_root: Path, output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    output.unlink(missing_ok=True)
    fd, name = tempfile.mkstemp(prefix=f".{output.name}.", suffix=".tmp", dir=output.parent)
    os.close(fd)
    temporary = Path(name)
    temporary.unlink(missing_ok=True)
    command = [
        "tar", "--sort=name", "--mtime=@0", "--owner=0", "--group=0", "--numeric-owner",
        "-C", str(report_root.parent), "--zstd", "-cf", str(temporary), report_root.name,
    ]
    result = subprocess.run(command, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, check=False)
    if result.returncode != 0:
        temporary.unlink(missing_ok=True)
        raise TechnicalRegistryError(result.stderr.decode("utf-8", errors="replace")[:4000])
    os.replace(temporary, output)


def cmd_audit(args: argparse.Namespace) -> int:
    report, summary = audit(
        Path(args.project_root).expanduser().resolve(),
        Path(args.original_root).expanduser().resolve() if args.original_root else None,
        Path(args.quartet_root).expanduser().resolve() if args.quartet_root else None,
        not args.no_report_archive,
    )
    print(f"Technical registry entries: {summary['technical_registry_entries']}")
    print(f"Text-independent inventory entries: {summary['text_independent_inventory_entries']}")
    print(f"Unlock/flag rows: {summary['unlock_or_flag_rows']}")
    print(f"Report: {report}")
    return 0


def cmd_validate(args: argparse.Namespace) -> int:
    report = Path(args.report_root).expanduser().resolve()
    rows = validate_report_directory(report)
    print(f"Validated seed-independent technical registry: {report}")
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
    audit_parser = sub.add_parser("audit", help="build technical registry without requiring text candidate units")
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
    except (TechnicalRegistryError, base.NonscenarioAuditError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
