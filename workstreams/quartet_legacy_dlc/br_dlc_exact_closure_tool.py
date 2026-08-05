#!/usr/bin/env python3
"""Canonical owner and exact dependency-closure audit for legacy DLC.

Consumes the seed-independent 0.0.3 technical registry and re-parses the full
BR1 JP system tables.  It does not alter or replace the earlier registry.  The
purpose is to separate canonical content owners from companion records,
shared dependency pools and contextual false positives, then report exact
member/table/flag closure and remaining blockers.  Metadata only; no raw game
payloads and no game writes.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import re
import subprocess
import tempfile
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable, Sequence

import br_dlc_nonscenario_tool as base
import br_dlc_technical_registry_tool as technical

TOOL_VERSION = "0.0.4"
FORMAT_VERSION = 1
REPORT_DIR_NAME = "exact_closure_evidence"
REPORT_ARCHIVE_NAME = "BR_quartet_legacy_dlc_exact_closure_evidence.tar.zst"
FORBIDDEN_REPORT_SUFFIXES = base.FORBIDDEN_REPORT_SUFFIXES

COSTUME_OWNER_RE = re.compile(r"^costume_pc(?P<pc>\d{2})_(?P<code>[a-z0-9]+)$", re.I)
COSTUME_COMPANION_RE = re.compile(r"^costume_character_(?P<name>[a-z0-9]+)_(?P<code>[a-z0-9]+)$", re.I)
ITEM_OWNER_RE = re.compile(r"^dlc_item_(?P<num>\d+)$", re.I)
CONTEXTUAL_BASE_THEME_RE = re.compile(r"^identifier_str_channel_skin_(?:color\d+|pattern\d+)$", re.I)
SHARED_ID_RE = re.compile(r"^shared_asset_", re.I)
TECHNICAL_RECORD_RE = re.compile(r"^technical_record_", re.I)
DUMMY_RE = re.compile(r"dummy", re.I)
ACCESSORY_PATH_RE = re.compile(r"(?:^|/)item_accessory_(?P<num>\d{2})(?:/|\.)", re.I)
EXPLICIT_DLC_RE = re.compile(r"(?:^|[_/])dlc(?:[_/]|$)|_dlc_|dlc\d|dlc_", re.I)


class ClosureError(RuntimeError):
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


def read_tsv(path: Path) -> list[dict[str, str]]:
    if not path.is_file():
        raise ClosureError(f"missing prerequisite TSV: {path}")
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def write_tsv(path: Path, fields: Sequence[str], rows: Iterable[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, delimiter="\t", lineterminator="\n", extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({field: scalar(row.get(field, "")) for field in fields})


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=False) + "\n", encoding="utf-8")


def clean_dir(path: Path) -> None:
    if path.exists():
        for item in sorted(path.rglob("*"), key=lambda p: len(p.parts), reverse=True):
            if item.is_file() or item.is_symlink():
                item.unlink()
            elif item.is_dir():
                item.rmdir()
    path.mkdir(parents=True, exist_ok=True)


def split_list(value: str) -> list[str]:
    return [part for part in str(value or "").split(";") if part]


def explicit_owner_tokens(content_id: str) -> list[str]:
    value = content_id.casefold()
    match = COSTUME_OWNER_RE.match(value)
    if match:
        base_token = f"PC{match.group('pc')}_DLC_{match.group('code').upper()}"
        return [base_token, base_token + "_W"]
    match = ITEM_OWNER_RE.match(value)
    if match:
        number = match.group("num").zfill(2)
        return [f"ITEM_DLC_ITEM_{number}", f"STR_ITEM_NAME_DLC_ITEM_{number}"]
    if value == "freespace_dlc_skin_01":
        return ["STR_CHANNEL_SKIN_DLC01", "DLC_ADDSKIN000000000"]
    if value == "dlc_bgm_pack":
        return ["DLC_BGM", "STR_DLC_BGM"]
    if value == "dlc_effect_pack_3000":
        return ["3000_DLC01"]
    if value == "south_island_field_assets":
        return ["S120_DLC_BEACH_01"]
    if value.startswith("identifier_pc_dlc_dummy_"):
        return [value.removeprefix("identifier_").upper()]
    return []


def scope_classification(content_id: str, rows: list[dict[str, str]], member_rows: list[dict[str, str]]) -> tuple[str, str]:
    value = content_id.casefold()
    types = {row["technical_type"] for row in rows}
    if SHARED_ID_RE.match(value) or types == {"shared_asset_dependency"}:
        return "shared_dependency_pool", "shared member retained as an unassigned dependency pool"
    if CONTEXTUAL_BASE_THEME_RE.match(value):
        return "quarantined_contextual_false_positive", "ordinary channel skin record has no explicit DLC identifier"
    if COSTUME_COMPANION_RE.match(value):
        return "companion_record", "CHARA_*_DLC_* effect record is a companion record until an exact owner mapping is proven"
    if TECHNICAL_RECORD_RE.match(value):
        return "unresolved_table_candidate", "table record contains DLC context but has no stable canonical owner identifier"
    if DUMMY_RE.search(value):
        return "quarantined_dummy_placeholder", "dummy identifier is preserved for evidence but excluded from profile ownership"
    if member_rows:
        return "canonical_owner", "direct BR1 member binding proves a canonical technical owner"
    if explicit_owner_tokens(content_id):
        return "canonical_owner", "stable explicit DLC identifier proves a canonical technical owner"
    identifiers = []
    for row in rows:
        identifiers.extend(split_list(row.get("dlc_identifiers", "")))
        identifiers.extend(split_list(row.get("linked_identifiers", "")))
    if any(EXPLICIT_DLC_RE.search(token) for token in identifiers):
        return "owner_candidate_table_only", "explicit DLC identifier exists but direct member ownership is not yet proven"
    return "quarantined_contextual_candidate", "contextual signal lacks an explicit DLC identifier or direct member"


def required_roles(content_id: str, types: set[str], records: list[dict[str, str]], members: list[dict[str, str]], flags: list[dict[str, str]]) -> list[str]:
    roles: list[str] = []
    if "costume_or_outfit" in types:
        roles.extend(["dry_model_or_container", "dry_texture", "system_character_record", "unlock_or_availability_chain"])
        wet_evidence = any(row.get("variant_state") == "wet" or "_W" in row.get("linked_identifiers", "") for row in members + records)
        if wet_evidence:
            roles.extend(["wet_model_or_container", "wet_texture"])
        roles.extend(["nested_model_material_inventory", "cloth_physics_or_animation", "ui_icon_or_thumbnail"])
    if "accessory" in types:
        roles.extend(["accessory_model_or_container", "accessory_texture", "accessory_table_binding", "unlock_or_availability_chain", "ui_icon_or_thumbnail"])
    if "item_or_reward" in types:
        roles.extend(["item_definition", "inventory_or_library_record", "unlock_or_availability_chain", "reward_source", "ui_icon_or_thumbnail"])
    if "recipe_or_system_bonus" in types:
        roles.extend(["recipe_or_bonus_definition", "result_item_binding", "trigger_or_grant_source"])
    if "theme_or_ui_content" in types:
        roles.extend(["ui_or_theme_registration", "theme_member_or_skin_reference", "unlock_or_availability_chain", "icon_or_description_binding"])
    if "unknown_legacy_dlc_candidate" in types:
        roles.extend(["technical_type_resolution", "canonical_owner_resolution"])
    if "unlock_or_entitlement" in types and "unlock_or_availability_chain" not in roles:
        roles.append("unlock_or_availability_chain")
    return sorted(set(roles), key=str.casefold)


def role_evidence(role: str, content_id: str, records: list[dict[str, str]], members: list[dict[str, str]], flags: list[dict[str, str]]) -> tuple[str, list[str], str]:
    paths = [row.get("normalized_path", "") for row in members]
    dry_models = [p for p, row in zip(paths, members) if row.get("variant_state") == "dry" and row.get("member_role") == "model_material_or_container"]
    dry_textures = [p for p, row in zip(paths, members) if row.get("variant_state") == "dry" and row.get("member_role") == "texture_or_thumbnail"]
    wet_models = [p for p, row in zip(paths, members) if row.get("variant_state") == "wet" and row.get("member_role") == "model_material_or_container"]
    wet_textures = [p for p, row in zip(paths, members) if row.get("variant_state") == "wet" and row.get("member_role") == "texture_or_thumbnail"]
    model_members = [p for p, row in zip(paths, members) if row.get("member_role") == "model_material_or_container"]
    texture_members = [p for p, row in zip(paths, members) if row.get("member_role") in {"texture_or_thumbnail", "ui_icon_or_thumbnail"}]
    table_paths = sorted({row.get("table_path", "") for row in records if row.get("table_path")})
    flag_ids = sorted({row.get("flag_or_condition_id", "") for row in flags if row.get("flag_or_condition_id")})
    linked = ";".join(row.get("linked_identifiers", "") for row in records)

    exact: list[str] = []
    status = "unresolved"
    note = "no exact evidence"
    if role == "dry_model_or_container": exact, status, note = dry_models, "resolved" if dry_models else "missing", "exact dry member path"
    elif role == "dry_texture": exact, status, note = dry_textures, "resolved" if dry_textures else "missing", "exact dry texture path"
    elif role == "wet_model_or_container": exact, status, note = wet_models, "resolved" if wet_models else "missing", "exact wet member path"
    elif role == "wet_texture": exact, status, note = wet_textures, "resolved" if wet_textures else "missing", "exact wet texture path"
    elif role in {"accessory_model_or_container"}:
        exact, status, note = model_members, "resolved" if model_members else "missing", "exact accessory container path"
    elif role in {"accessory_texture"}:
        exact, status, note = texture_members, "resolved" if texture_members else "missing", "exact accessory texture path"
    elif role in {"system_character_record", "accessory_table_binding", "item_definition", "inventory_or_library_record", "recipe_or_bonus_definition", "ui_or_theme_registration"}:
        wanted = {
            "system_character_record": ("chara/", "costume/"),
            "accessory_table_binding": ("item/", "chara/", "costume/"),
            "item_definition": ("item/item_data",),
            "inventory_or_library_record": ("library/", "item/item_data_no"),
            "recipe_or_bonus_definition": ("makeitem/", "recipe", "bonus"),
            "ui_or_theme_registration": ("channel/", "layout/", "freespace"),
        }[role]
        exact = [p for p in table_paths if any(part in p.casefold() for part in wanted)]
        status = "resolved" if exact else "missing"
        note = "exact system-table record" if exact else "no exact system-table role record"
    elif role == "unlock_or_availability_chain":
        exact = flag_ids
        if exact:
            status, note = "metadata_resolved_semantics_unproven", "exact flag field recorded; runtime/platform semantics remain unproven"
        else:
            status, note = "missing", "no exact flag or availability field linked to this owner"
    elif role == "theme_member_or_skin_reference":
        exact = texture_members + model_members
        if not exact and content_id == "freespace_dlc_skin_01" and "STR_CHANNEL_SKIN_DLC01" in linked:
            status, note = "record_reference_only", "channel skin record and ref_skin exist; exact UI payload owner not mapped"
        else:
            status, note = ("resolved", "exact theme/UI member") if exact else ("missing", "no exact theme/UI member")
    elif role in {"nested_model_material_inventory", "cloth_physics_or_animation"}:
        if model_members:
            status = "container_present_nested_inventory_required"
            exact = model_members
            note = "parent Elixir/container is known but nested member closure is not yet inventoried"
        else:
            status, note = "missing", "no parent model/container member"
    elif role in {"ui_icon_or_thumbnail", "icon_or_description_binding"}:
        exact = [p for p in texture_members if "icon" in p.casefold() or "thumbnail" in p.casefold()]
        status = "resolved" if exact else "shared_atlas_or_table_index_unresolved"
        note = "exact icon member" if exact else "likely shared atlas/table index; no per-content member proven"
    elif role == "reward_source":
        exact = [p for p in table_paths if any(part in p.casefold() for part in ("reward", "quest", "shop", "library"))]
        status = "candidate_only" if exact else "missing"
        note = "candidate grant source; runtime path unproven" if exact else "no grant source record"
    elif role in {"result_item_binding"}:
        exact = [token for token in explicit_owner_tokens(content_id) if token.startswith("ITEM_")]
        status = "resolved" if exact else "missing"
        note = "canonical item identifier" if exact else "no exact result item"
    elif role in {"trigger_or_grant_source"}:
        exact = flag_ids
        status = "candidate_only" if exact else "missing"
        note = "activation metadata may be grant trigger" if exact else "no exact trigger or grant source"
    elif role in {"technical_type_resolution", "canonical_owner_resolution"}:
        status, note = "unresolved", "manual technical classification and exact owner proof required"
    else:
        status, note = "unresolved", "role not resolved by conservative exact rules"
    return status, sorted(set(exact), key=str.casefold), note


def aggregate_compatibility(rows: list[dict[str, str]]) -> str:
    return technical.aggregate_status(row.get("compatibility_status", "unknown_dependency") for row in rows)


def make_archive(report_root: Path, output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    output.unlink(missing_ok=True)
    fd, name = tempfile.mkstemp(prefix=f".{output.name}.", suffix=".tmp", dir=output.parent)
    os.close(fd)
    temp = Path(name)
    temp.unlink(missing_ok=True)
    command = ["tar", "--sort=name", "--mtime=@0", "--owner=0", "--group=0", "--numeric-owner", "-C", str(report_root.parent), "--zstd", "-cf", str(temp), report_root.name]
    result = subprocess.run(command, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, check=False)
    if result.returncode:
        temp.unlink(missing_ok=True)
        raise ClosureError(result.stderr.decode("utf-8", errors="replace")[:4000])
    os.replace(temp, output)


def audit(project_root: Path, create_archive: bool = True) -> tuple[Path, dict[str, Any]]:
    version = (project_root / "workstreams/quartet_legacy_dlc/VERSION").read_text(encoding="utf-8").strip()
    if version != TOOL_VERSION:
        raise ClosureError(f"tool/workstream version mismatch: {TOOL_VERSION} != {version}")
    prerequisite = project_root / ".local/reports/quartet_legacy_dlc/technical_registry_evidence"
    technical.validate_report_directory(prerequisite)
    print("[stage10] loading seed-independent registry", flush=True)
    registry = read_tsv(prerequisite / "DLC_TECHNICAL_REGISTRY.tsv")
    members = read_tsv(prerequisite / "DLC_TECHNICAL_MEMBER_BINDINGS.tsv")
    records = read_tsv(prerequisite / "DLC_TECHNICAL_SYSTEM_RECORDS.tsv")
    flags = read_tsv(prerequisite / "DLC_UNLOCK_FLAG_MAP.tsv")

    # Canonicalize direct accessory members.  The 0.0.3 registry intentionally
    # gave each shared-pattern member a stable hash ID; closure ownership must
    # merge the model and texture for item_accessory_XX into one content unit.
    canonical_by_original: dict[str, str] = {}
    for row in members:
        match = ACCESSORY_PATH_RE.search(row.get("normalized_path", ""))
        if match and row.get("technical_type") == "accessory":
            canonical_by_original[row["content_id"]] = f"accessory_item_accessory_{match.group('num')}"

    def canonical_id(row: dict[str, str]) -> str:
        return canonical_by_original.get(row.get("content_id", ""), row.get("content_id", ""))

    registry_by_content: dict[str, list[dict[str, str]]] = defaultdict(list)
    members_by_content: dict[str, list[dict[str, str]]] = defaultdict(list)
    records_by_content: dict[str, list[dict[str, str]]] = defaultdict(list)
    flags_by_content: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in registry: registry_by_content[canonical_id(row)].append(row)
    for row in members: members_by_content[canonical_id(row)].append(row)
    for row in records: records_by_content[canonical_id(row)].append(row)
    for row in flags: flags_by_content[canonical_id(row)].append(row)

    report_root = project_root / ".local/reports/quartet_legacy_dlc" / REPORT_DIR_NAME
    clean_dir(report_root)
    owner_rows: list[dict[str, Any]] = []
    role_rows: list[dict[str, Any]] = []
    table_flag_rows: list[dict[str, Any]] = []
    scope_rows: list[dict[str, Any]] = []
    gaps: list[dict[str, Any]] = []
    readiness_rows: list[dict[str, Any]] = []
    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []

    print(f"[stage10] resolving canonical ownership for {len(registry_by_content)} content identifiers", flush=True)
    for content_id in sorted(registry_by_content, key=str.casefold):
        reg_rows = registry_by_content[content_id]
        member_rows = members_by_content.get(content_id, [])
        record_rows = records_by_content.get(content_id, [])
        flag_rows = flags_by_content.get(content_id, [])
        types = {row["technical_type"] for row in reg_rows}
        scope, scope_note = scope_classification(content_id, reg_rows, member_rows)
        tokens = explicit_owner_tokens(content_id)
        closure_id = f"closure_{sha256_bytes(content_id.encode())[:20]}"
        scope_rows.append({
            "closure_id": closure_id, "content_id": content_id, "scope_classification": scope,
            "technical_types": sorted(types), "explicit_owner_tokens": tokens,
            "direct_member_count": len(member_rows), "system_record_count": len(record_rows),
            "flag_count": len(flag_rows), "reason": scope_note,
            "included_in_profile_readiness": scope in {"canonical_owner", "owner_candidate_table_only"},
        })
        nodes.append({"id": closure_id, "node_type": "canonical_content_closure", "content_id": content_id, "scope": scope})
        if scope not in {"canonical_owner", "owner_candidate_table_only"}:
            continue

        requirements = required_roles(content_id, types, record_rows, member_rows, flag_rows)
        role_statuses: dict[str, str] = {}
        for role in requirements:
            status, evidence, note = role_evidence(role, content_id, record_rows, member_rows, flag_rows)
            role_statuses[role] = status
            role_id = f"role:{sha256_bytes((content_id + ':' + role).encode())[:20]}"
            role_rows.append({
                "closure_id": closure_id, "content_id": content_id, "role": role,
                "resolution_status": status, "evidence_count": len(evidence), "evidence": evidence,
                "notes": note, "raw_payload_exported": False,
            })
            nodes.append({"id": role_id, "node_type": "closure_role", "role": role, "status": status})
            edges.append({"from": closure_id, "to": role_id, "relation": "requires_role", "exact": True})
            for value in evidence:
                evidence_id = f"evidence:{sha256_bytes(value.encode())[:20]}"
                nodes.append({"id": evidence_id, "node_type": "metadata_evidence", "value": value, "raw_payload_embedded": False})
                edges.append({"from": role_id, "to": evidence_id, "relation": "supported_by", "exact": status == "resolved"})
            if status not in {"resolved", "metadata_resolved_semantics_unproven"}:
                gaps.append({
                    "gap_id": f"{closure_id}:{role}", "closure_id": closure_id, "content_id": content_id,
                    "technical_types": sorted(types), "role": role, "resolution_status": status,
                    "priority": "critical" if role in {"dry_model_or_container", "dry_texture", "item_definition", "technical_type_resolution", "canonical_owner_resolution"} else "high",
                    "next_evidence_needed": note,
                })

        for row in record_rows:
            table_flag_rows.append({
                "closure_id": closure_id, "content_id": content_id, "evidence_type": "system_record",
                "source_table": row.get("table_path", ""), "record_key": row.get("record_key", ""),
                "field_name": "", "identifier": row.get("dlc_identifiers", "") or row.get("linked_identifiers", ""),
                "target_status": row.get("target_status", ""), "exact_owner_match": any(token in row.get("linked_identifiers", "") for token in tokens) if tokens else True,
                "semantics_proven": False, "raw_text_exported": False,
            })
        for row in flag_rows:
            table_flag_rows.append({
                "closure_id": closure_id, "content_id": content_id, "evidence_type": "unlock_or_flag",
                "source_table": row.get("source_table", ""), "record_key": row.get("record_key", ""),
                "field_name": row.get("field_name", ""), "identifier": row.get("flag_or_condition_id", ""),
                "target_status": row.get("target_status", ""), "exact_owner_match": True,
                "semantics_proven": False, "raw_text_exported": False,
            })

        resolved = sum(1 for status in role_statuses.values() if status == "resolved")
        semantic = sum(1 for status in role_statuses.values() if status == "metadata_resolved_semantics_unproven")
        unresolved = len(role_statuses) - resolved - semantic
        if unresolved == 0 and semantic == 0:
            readiness = "metadata_closure_complete_build_still_disabled"
        elif unresolved == 0:
            readiness = "metadata_closure_complete_runtime_semantics_unproven"
        elif any(status == "missing" for status in role_statuses.values()):
            readiness = "blocked_missing_exact_dependency"
        else:
            readiness = "blocked_unresolved_dependency"
        if any(status == "container_present_nested_inventory_required" for status in role_statuses.values()):
            readiness = "blocked_nested_container_closure"
        readiness_rows.append({
            "closure_id": closure_id, "content_id": content_id, "technical_types": sorted(types),
            "scope_classification": scope, "compatibility_status": aggregate_compatibility(reg_rows),
            "required_role_count": len(role_statuses), "resolved_role_count": resolved,
            "semantics_unproven_role_count": semantic, "unresolved_role_count": unresolved,
            "profile_readiness": readiness, "profile_build_allowed": False,
            "default_enabled": False, "runtime_validated": False,
        })
        owner_rows.append({
            "closure_id": closure_id, "content_id": content_id, "technical_types": sorted(types),
            "scope_classification": scope, "explicit_owner_tokens": tokens,
            "source_member_count": len(member_rows), "system_record_count": len(record_rows),
            "flag_count": len(flag_rows), "compatibility_status": aggregate_compatibility(reg_rows),
            "required_roles": requirements, "resolved_roles": resolved,
            "unresolved_roles": unresolved + semantic, "profile_readiness": readiness,
            "translation_text_source": "titles/blue_reflection/translation",
            "separate_translation_database": False, "raw_assets_embedded": False,
        })

    owner_ids = {row["content_id"] for row in owner_rows}
    shared_assignments: list[dict[str, Any]] = []
    for content_id, rows in sorted(registry_by_content.items(), key=lambda item: item[0].casefold()):
        if not SHARED_ID_RE.match(content_id):
            continue
        member_rows = members_by_content.get(content_id, [])
        signal = " ".join(row.get("normalized_path", "") for row in member_rows).casefold()
        if "item_icon" in signal or "libraryitem" in signal:
            candidate_owners = sorted(cid for cid in owner_ids if cid.startswith("dlc_item_") or "theme" in cid or "skin" in cid)
            basis = "class_level_item_or_ui_candidate"
        elif "costume" in signal:
            candidate_owners = sorted(cid for cid in owner_ids if cid.startswith("costume_pc"))
            basis = "class_level_costume_candidate"
        elif "channel" in signal or "freespace" in signal:
            candidate_owners = sorted(cid for cid in owner_ids if "skin" in cid or "theme" in cid)
            basis = "class_level_theme_candidate"
        else:
            candidate_owners = []
            basis = "unassigned_shared_dependency"
        shared_assignments.append({
            "shared_registry_content_id": content_id,
            "source_members": [row.get("normalized_path", "") for row in member_rows],
            "candidate_owner_count": len(candidate_owners), "candidate_owner_ids": candidate_owners,
            "assignment_basis": basis, "exact_owner_assignment": False,
            "profile_inclusion_allowed": False,
        })

    print("[stage10] writing canonical closure reports", flush=True)
    write_tsv(report_root / "DLC_CANONICAL_CONTENT_CLOSURE.tsv", [
        "closure_id", "content_id", "technical_types", "scope_classification", "explicit_owner_tokens",
        "source_member_count", "system_record_count", "flag_count", "compatibility_status",
        "required_roles", "resolved_roles", "unresolved_roles", "profile_readiness",
        "translation_text_source", "separate_translation_database", "raw_assets_embedded",
    ], owner_rows)
    write_tsv(report_root / "DLC_EXACT_ROLE_CLOSURE.tsv", [
        "closure_id", "content_id", "role", "resolution_status", "evidence_count", "evidence", "notes", "raw_payload_exported",
    ], role_rows)
    write_tsv(report_root / "DLC_TABLE_AND_UNLOCK_CLOSURE.tsv", [
        "closure_id", "content_id", "evidence_type", "source_table", "record_key", "field_name", "identifier",
        "target_status", "exact_owner_match", "semantics_proven", "raw_text_exported",
    ], table_flag_rows)
    write_tsv(report_root / "DLC_SCOPE_TRIAGE.tsv", [
        "closure_id", "content_id", "scope_classification", "technical_types", "explicit_owner_tokens",
        "direct_member_count", "system_record_count", "flag_count", "reason", "included_in_profile_readiness",
    ], scope_rows)
    write_tsv(report_root / "DLC_SHARED_DEPENDENCY_ASSIGNMENTS.tsv", [
        "shared_registry_content_id", "source_members", "candidate_owner_count", "candidate_owner_ids",
        "assignment_basis", "exact_owner_assignment", "profile_inclusion_allowed",
    ], shared_assignments)
    write_tsv(report_root / "DLC_CLOSURE_GAPS.tsv", [
        "gap_id", "closure_id", "content_id", "technical_types", "role", "resolution_status", "priority", "next_evidence_needed",
    ], gaps)
    write_tsv(report_root / "DLC_PROFILE_READINESS.tsv", [
        "closure_id", "content_id", "technical_types", "scope_classification", "compatibility_status",
        "required_role_count", "resolved_role_count", "semantics_unproven_role_count", "unresolved_role_count",
        "profile_readiness", "profile_build_allowed", "default_enabled", "runtime_validated",
    ], readiness_rows)
    write_json(report_root / "DLC_EXACT_CLOSURE_GRAPH.json", {
        "type": "br_quartet_legacy_dlc_exact_closure_graph", "format_version": FORMAT_VERSION,
        "tool_version": TOOL_VERSION, "nodes": nodes, "edges": edges,
        "policy": {"preserves_technical_registry_0_0_3": True, "member_level_only": True,
                   "raw_assets_embedded": False, "profile_build_allowed": False,
                   "translation_text_not_modified": True},
    })
    scope_counts = Counter(row["scope_classification"] for row in scope_rows)
    readiness_counts = Counter(row["profile_readiness"] for row in readiness_rows)
    role_counts = Counter(row["resolution_status"] for row in role_rows)
    summary = {
        "type": "br_quartet_legacy_dlc_exact_closure_summary", "format_version": FORMAT_VERSION,
        "tool_version": TOOL_VERSION, "status": "canonical_owner_and_exact_closure_audit_complete_metadata_only",
        "input_technical_registry_entries": len(registry), "unique_input_content_ids": len(registry_by_content),
        "canonical_owner_closures": len(owner_rows), "scope_classification_counts": dict(sorted(scope_counts.items())),
        "exact_role_rows": len(role_rows), "role_resolution_counts": dict(sorted(role_counts.items())),
        "closure_gaps": len(gaps), "profile_readiness_counts": dict(sorted(readiness_counts.items())),
        "shared_dependency_pools": len(shared_assignments),
        "policy": {"technical_registry_0_0_3_unchanged": True, "text_seed_unchanged": True,
                   "translation_text_source": "titles/blue_reflection/translation",
                   "separate_translation_database": False, "default_enabled": False,
                   "raw_assets_exported": False, "game_modified": False, "git_modified": False},
        "limitations": [
            "nested members inside BR1 Elixir containers are not yet inventoried by this stage",
            "shared UI atlases and release-condition tables are not assigned to an owner without exact identifiers",
            "flag fields are mapped exactly but runtime and platform entitlement semantics remain unproven",
            "quarantined contextual and dummy records remain in the 0.0.3 evidence and are not deleted",
        ],
        "next_action": "rehydrate canonical BR1-only costume/accessory containers and inventory nested G1M/G1T/physics dependencies before any local profile build",
    }
    write_json(report_root / "SUMMARY.json", summary)
    manifest = validate_report(report_root)
    write_json(report_root / "REPORT_MANIFEST.json", {"type": "br_quartet_legacy_dlc_exact_closure_manifest", "format_version": FORMAT_VERSION, "tool_version": TOOL_VERSION, "files": manifest, "raw_assets_embedded": False})
    if create_archive:
        make_archive(report_root, report_root.parent / REPORT_ARCHIVE_NAME)
    return report_root, summary


def validate_report(report_root: Path) -> list[dict[str, Any]]:
    required = {
        "DLC_CANONICAL_CONTENT_CLOSURE.tsv", "DLC_EXACT_ROLE_CLOSURE.tsv", "DLC_TABLE_AND_UNLOCK_CLOSURE.tsv",
        "DLC_SCOPE_TRIAGE.tsv", "DLC_SHARED_DEPENDENCY_ASSIGNMENTS.tsv", "DLC_CLOSURE_GAPS.tsv",
        "DLC_PROFILE_READINESS.tsv", "DLC_EXACT_CLOSURE_GRAPH.json", "SUMMARY.json",
    }
    names = {p.name for p in report_root.iterdir() if p.is_file()}
    missing = sorted(required - names)
    if missing:
        raise ClosureError("missing closure report files: " + ", ".join(missing))
    owners = read_tsv(report_root / "DLC_CANONICAL_CONTENT_CLOSURE.tsv")
    triage = read_tsv(report_root / "DLC_SCOPE_TRIAGE.tsv")
    readiness = read_tsv(report_root / "DLC_PROFILE_READINESS.tsv")
    if not owners or not triage or not readiness:
        raise ClosureError("closure reports are empty")
    if any(row.get("profile_build_allowed") != "False" for row in readiness):
        raise ClosureError("closure report unexpectedly allows profile building")
    if not any(row.get("scope_classification", "").startswith("quarantined_") for row in triage):
        raise ClosureError("scope triage contains no quarantined contextual candidates")
    summary = json.loads((report_root / "SUMMARY.json").read_text(encoding="utf-8"))
    if summary.get("policy", {}).get("technical_registry_0_0_3_unchanged") is not True:
        raise ClosureError("summary does not preserve 0.0.3 registry")
    manifest: list[dict[str, Any]] = []
    for path in sorted(report_root.rglob("*"), key=lambda p: p.relative_to(report_root).as_posix().casefold()):
        if not path.is_file() or path.name == "REPORT_MANIFEST.json":
            continue
        if {suffix.casefold() for suffix in path.suffixes} & FORBIDDEN_REPORT_SUFFIXES:
            raise ClosureError(f"forbidden raw asset in report: {path}")
        manifest.append({"path": path.relative_to(report_root).as_posix(), "size": path.stat().st_size, "sha256": sha256_file(path)})
    return manifest


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    audit_p = sub.add_parser("audit")
    audit_p.add_argument("--project-root", required=True)
    audit_p.add_argument("--no-report-archive", action="store_true")
    audit_p.set_defaults(func=lambda args: audit(Path(args.project_root).expanduser().resolve(), not args.no_report_archive) and 0)
    validate_p = sub.add_parser("validate-report")
    validate_p.add_argument("--report-root", required=True)
    validate_p.set_defaults(func=lambda args: (print(f"Validated exact closure report: {Path(args.report_root).resolve()}"), validate_report(Path(args.report_root).expanduser().resolve()), 0)[-1])
    bundle_p = sub.add_parser("bundle-report")
    bundle_p.add_argument("--report-root", required=True)
    bundle_p.add_argument("--output", required=True)
    def bundle(args: argparse.Namespace) -> int:
        root = Path(args.report_root).expanduser().resolve(); validate_report(root)
        out = Path(args.output).expanduser().resolve(); make_archive(root, out); print(out); return 0
    bundle_p.set_defaults(func=bundle)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        return int(args.func(args))
    except (ClosureError, technical.TechnicalRegistryError, base.NonscenarioAuditError) as exc:
        print(f"ERROR: {exc}", file=os.sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
