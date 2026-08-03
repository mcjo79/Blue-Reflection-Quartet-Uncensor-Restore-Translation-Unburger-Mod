#!/usr/bin/env python3
"""Metadata-only inventory and dependency audit for Blue Reflection Quartet legacy DLC.

This tool never writes to a game installation, never exports raw game members, and
never modifies Translation or Quartet Restoration. It consumes the existing
Original-versus-Quartet inventory/difference reports and produces deterministic
metadata-only evidence for the separate ``quartet_legacy_dlc`` workstream.
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
from pathlib import Path, PurePosixPath
from typing import Any, Iterable, Sequence

TOOL_VERSION = "0.0.1"
FORMAT_VERSION = 1
WORKSTREAM_ID = "quartet_legacy_dlc"
REPORT_DIR_NAME = "inventory_evidence"
REPORT_ARCHIVE_NAME = "BR_quartet_legacy_dlc_inventory_evidence.tar.zst"

FORBIDDEN_REPORT_SUFFIXES = {
    ".pak", ".ebm", ".ebd", ".g1m", ".g1t", ".g1a", ".g1e", ".g1em",
    ".g1s", ".kps", ".bin", ".gz", ".elixir", ".wav", ".hca", ".awb",
    ".acb", ".ogg", ".mp4", ".usm", ".dds", ".png", ".jpg", ".jpeg",
}

FAMILY_BY_SUBCATEGORY = {
    "south_island": "south_island",
    "final_fantasy_xv_collaboration": "ffxv",
    "dlc_installation_or_system_message": "yy",
    "dlc_costume_or_chat_registry": "system_registry",
}

TEXT_MANAGED_ROLES = {"event_message", "system_text_table"}


class DlcAuditError(RuntimeError):
    pass


def eprint(*args: object) -> None:
    print(*args, file=sys.stderr)


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def safe_relpath(raw: str) -> str:
    value = raw.replace("\\", "/")
    while value.startswith("./"):
        value = value[2:]
    path = PurePosixPath(value)
    if path.is_absolute() or not path.parts or ".." in path.parts:
        raise DlcAuditError(f"unsafe relative path: {raw!r}")
    return path.as_posix()


def canonical_member_path(raw: str) -> str:
    value = safe_relpath(raw).casefold()
    replacements = (
        ("event/b1/", "event/"),
        ("data/b1/", "data/"),
        ("saves/b1/", "saves/"),
    )
    for source, target in replacements:
        if value.startswith(source):
            value = target + value[len(source):]
            break
    return value


def load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise DlcAuditError(f"missing JSON input: {path}") from exc
    except json.JSONDecodeError as exc:
        raise DlcAuditError(f"invalid JSON input {path}: {exc}") from exc


def read_tsv(path: Path) -> list[dict[str, str]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as handle:
            return list(csv.DictReader(handle, delimiter="\t"))
    except FileNotFoundError as exc:
        raise DlcAuditError(f"missing TSV input: {path}") from exc


def write_tsv(path: Path, fieldnames: Sequence[str], rows: Iterable[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    ordered = list(rows)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=list(fieldnames),
            delimiter="\t",
            lineterminator="\n",
            extrasaction="ignore",
        )
        writer.writeheader()
        writer.writerows(ordered)


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(data, ensure_ascii=False, indent=2, sort_keys=False) + "\n"
    path.write_text(encoded, encoding="utf-8", newline="\n")


def parse_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().casefold() in {"1", "true", "yes"}


def parse_int(value: Any, default: int = 0) -> int:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return default


def event_identity(unit: dict[str, str]) -> tuple[str, str] | None:
    logical = unit.get("logical_path", "")
    match = re.fullmatch(r"(?P<family>[a-z0-9]+)/event_message_(?P<event>[a-z0-9]+_[0-9]+)\.ebm", logical)
    if not match:
        return None
    return match.group("family"), match.group("event")


def content_id_for_unit(unit: dict[str, str]) -> str:
    identity = event_identity(unit)
    if identity:
        return f"legacy_dlc_event_{identity[1]}"
    stem = Path(unit.get("logical_path", "unknown")).stem
    return f"legacy_dlc_system_{re.sub(r'[^a-z0-9]+', '_', stem.casefold()).strip('_')}"


def load_difference_entries(path: Path, expected_group: str) -> list[dict[str, Any]]:
    data = load_json(path)
    if data.get("type") != "br_asset_difference_report":
        raise DlcAuditError(f"not an asset difference report: {path}")
    if data.get("source_archive_group") != expected_group:
        raise DlcAuditError(f"unexpected archive group in {path}")
    entries = data.get("entries")
    if not isinstance(entries, list):
        raise DlcAuditError(f"difference report has no entries array: {path}")
    return [row for row in entries if isinstance(row, dict)]


def event_role_and_language(path: str) -> tuple[str, str]:
    folded = path.casefold()
    message = re.search(r"^event/event_([^/]+)/[^/]+/event_message_[^/]+\.ebm$", folded)
    if message:
        return "event_message", message.group(1)
    control = re.search(r"^event/event_([^/]+)/[^/]+/event_[^/]+\.ebd$", folded)
    if control:
        return "event_control", control.group(1)
    system = re.search(r"^saves/text_([^/]+)/str_(?:chat_msg|costume)\.xml$", folded)
    if system:
        return "system_text_table", system.group(1)
    return "other", ""


def classify_binding(
    *,
    difference: dict[str, Any],
    role: str,
    event_id: str,
    placeholder_events: set[str],
) -> tuple[str, str]:
    classification = str(difference.get("classification", "unknown"))
    source = difference.get("source") if isinstance(difference.get("source"), dict) else None
    target = difference.get("target") if isinstance(difference.get("target"), dict) else None
    if role == "event_message" and event_id in placeholder_events and target is not None:
        return "present_but_disabled", "scene-wide target dash placeholders recorded by stage 57"
    if source is not None and target is not None:
        if classification == "identical":
            return "present_identical", "source and target hashes are identical"
        return "present_modified", "source and target members both exist but differ"
    if source is not None and target is None:
        if role in {"event_message", "event_control", "system_text_table"}:
            return "missing_portable_from_br1", "source member exists and no target member is mapped"
        return "missing_requires_conversion", "source-only member requires format review"
    if source is None and target is not None:
        return "present_modified", "target-only locale or Quartet-specific member"
    return "unknown_dependency", "difference report contains neither side"


def aggregate_status(values: Sequence[str]) -> str:
    if not values:
        return "unknown_dependency"
    order = [
        "missing_requires_reconstruction",
        "missing_requires_conversion",
        "missing_portable_from_br1",
        "present_but_disabled",
        "present_modified",
        "present_identical",
        "unknown_dependency",
    ]
    for status in order:
        if status in values:
            return status
    return sorted(values)[0]


def load_restoration_changed_members(project_root: Path) -> set[str]:
    root = project_root / ".local/build/quartet_restoration/core_profiles/generated"
    changed: set[str] = set()
    if not root.is_dir():
        return changed
    for path in sorted(root.glob("*.json"), key=lambda item: item.name.casefold()):
        try:
            data = load_json(path)
        except DlcAuditError:
            continue
        members = data.get("changed_members")
        if not isinstance(members, list):
            continue
        for member in members:
            if isinstance(member, str):
                changed.add(canonical_member_path(member))
    return changed


def index_by(rows: Sequence[dict[str, str]], key: str) -> dict[str, dict[str, str]]:
    result: dict[str, dict[str, str]] = {}
    for row in rows:
        value = row.get(key, "")
        if value and value not in result:
            result[value] = row
    return result


def cue_index(rows: Sequence[dict[str, str]]) -> dict[str, list[dict[str, str]]]:
    result: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in rows:
        data_path = row.get("event_data_path", "")
        match = re.search(r"/event_([a-z0-9]+_[0-9]+)\.ebd$", data_path.casefold())
        if match:
            result[match.group(1)].append(row)
    return result


def stable_node_id(prefix: str, value: str) -> str:
    return f"{prefix}_{hashlib.sha256(value.encode('utf-8')).hexdigest()[:16]}"


def archive_installation_audit(
    *,
    archive_rows: Sequence[dict[str, str]],
    original_root: Path | None,
    quartet_root: Path | None,
    verify_hashes: bool,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for row in archive_rows:
        side = row.get("side", "")
        root = original_root if side == "source" else quartet_root
        archive_rel = row.get("archive", "")
        expected_size = parse_int(row.get("size"))
        expected_sha = row.get("sha256", "")
        path = root / archive_rel if root is not None else None
        present = bool(path and path.is_file())
        actual_size = path.stat().st_size if present and path is not None else ""
        size_match = present and actual_size == expected_size
        if verify_hashes and present and path is not None:
            actual_sha = sha256_file(path)
            hash_status = "match" if actual_sha == expected_sha else "mismatch"
        elif verify_hashes:
            actual_sha = ""
            hash_status = "missing"
        else:
            actual_sha = ""
            hash_status = "not_requested"
        rows.append(
            {
                "pair_id": row.get("pair_id", ""),
                "category": row.get("category", ""),
                "side": side,
                "archive": archive_rel,
                "expected_size": expected_size,
                "actual_size": actual_size,
                "file_present": present,
                "size_match": size_match,
                "expected_sha256": expected_sha,
                "actual_sha256": actual_sha,
                "hash_status": hash_status,
                "read_only": True,
            }
        )
    return rows


def source_target_fields(difference: dict[str, Any], prefix: str) -> dict[str, Any]:
    member = difference.get(prefix)
    if not isinstance(member, dict):
        return {
            f"{prefix}_archive": "",
            f"{prefix}_path": "",
            f"{prefix}_size": "",
            f"{prefix}_sha256": "",
            f"{prefix}_exists": False,
        }
    return {
        f"{prefix}_archive": member.get("archive", ""),
        f"{prefix}_path": member.get("path", ""),
        f"{prefix}_size": member.get("size", ""),
        f"{prefix}_sha256": member.get("sha256", ""),
        f"{prefix}_exists": True,
    }


def build_member_bindings(
    *,
    units: Sequence[dict[str, str]],
    event_differences: Sequence[dict[str, Any]],
    language_differences: Sequence[dict[str, Any]],
    placeholder_events: set[str],
    restoration_changed: set[str],
) -> list[dict[str, Any]]:
    bindings: list[dict[str, Any]] = []
    event_entries = sorted(event_differences, key=lambda row: str(row.get("normalized_path", "")).casefold())
    language_entries = sorted(language_differences, key=lambda row: str(row.get("normalized_path", "")).casefold())
    for unit in units:
        content_id = content_id_for_unit(unit)
        family_id = FAMILY_BY_SUBCATEGORY.get(unit.get("subcategory", ""), "unknown")
        identity = event_identity(unit)
        candidates: list[dict[str, Any]] = []
        event_id = ""
        if identity:
            family_dir, event_id = identity
            message_re = re.compile(
                rf"^event/event_[^/]+/{re.escape(family_dir)}/event_message_{re.escape(event_id)}\.ebm$",
                re.IGNORECASE,
            )
            control_re = re.compile(
                rf"^event/event_[^/]+/{re.escape(family_dir)}/event_{re.escape(event_id)}\.ebd$",
                re.IGNORECASE,
            )
            candidates = [
                row for row in event_entries
                if message_re.fullmatch(str(row.get("normalized_path", "")))
                or control_re.fullmatch(str(row.get("normalized_path", "")))
            ]
        else:
            basename = Path(unit.get("logical_path", "")).name.casefold()
            candidates = [
                row for row in language_entries
                if Path(str(row.get("normalized_path", ""))).name.casefold() == basename
                and "/text_" in str(row.get("normalized_path", "")).casefold()
            ]
        for difference in candidates:
            normalized_path = canonical_member_path(str(difference.get("normalized_path", "")))
            role, language = event_role_and_language(normalized_path)
            status, note = classify_binding(
                difference=difference,
                role=role,
                event_id=event_id,
                placeholder_events=placeholder_events,
            )
            row = {
                "content_id": content_id,
                "family_id": family_id,
                "subcategory": unit.get("subcategory", ""),
                "event_id": event_id,
                "member_role": role,
                "language": language,
                "normalized_path": normalized_path,
                "difference_id": difference.get("difference_id", ""),
                "difference_classification": difference.get("classification", ""),
                "binding_status": status,
                "mapping_basis": difference.get("mapping_basis", ""),
                "binary_similarity": difference.get("binary_similarity", ""),
                "text_managed_by_translation": role in TEXT_MANAGED_ROLES,
                "restoration_conflict": normalized_path in restoration_changed,
                "notes": note,
            }
            row.update(source_target_fields(difference, "source"))
            row.update(source_target_fields(difference, "target"))
            bindings.append(row)
    return sorted(
        bindings,
        key=lambda row: (
            row["family_id"], row["content_id"], row["member_role"],
            row["language"], row["normalized_path"],
        ),
    )


def build_content_inventory(
    *,
    units: Sequence[dict[str, str]],
    bindings: Sequence[dict[str, Any]],
    placeholder_by_event: dict[str, dict[str, str]],
    reachability_by_event: dict[str, dict[str, str]],
) -> list[dict[str, Any]]:
    by_content: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in bindings:
        by_content[row["content_id"]].append(row)
    output: list[dict[str, Any]] = []
    for unit in units:
        content_id = content_id_for_unit(unit)
        family_id = FAMILY_BY_SUBCATEGORY.get(unit.get("subcategory", ""), "unknown")
        identity = event_identity(unit)
        event_id = identity[1] if identity else ""
        rows = by_content.get(content_id, [])
        messages = [row["binding_status"] for row in rows if row["member_role"] == "event_message"]
        controls = [row["binding_status"] for row in rows if row["member_role"] == "event_control"]
        systems = [row["binding_status"] for row in rows if row["member_role"] == "system_text_table"]
        placeholder = placeholder_by_event.get(event_id, {})
        reachability = reachability_by_event.get(event_id, {})
        routing_status = "not_applicable" if not identity else "unresolved_event_process_framing"
        trigger_status = "not_applicable" if not identity else "unresolved_event_process_framing"
        flag_status = "unknown_system_registration" if not identity else "unknown_progress_or_dlc_flag_dependency"
        output.append(
            {
                "content_id": content_id,
                "family_id": family_id,
                "subcategory": unit.get("subcategory", ""),
                "content_type": unit.get("category", ""),
                "unit_path": unit.get("unit_path", ""),
                "logical_path": unit.get("logical_path", ""),
                "event_id": event_id,
                "record_count": parse_int(unit.get("record_count")),
                "translation_status": "canonical_translation_available",
                "source_member_count": sum(1 for row in rows if row["source_exists"]),
                "target_member_count": sum(1 for row in rows if row["target_exists"]),
                "mapped_member_count": len(rows),
                "event_message_status": aggregate_status(messages) if identity else "not_applicable",
                "event_control_status": aggregate_status(controls) if identity else "not_applicable",
                "system_table_status": aggregate_status(systems) if not identity else "not_applicable",
                "placeholder_status": placeholder.get("classification", "not_recorded"),
                "archive_presence_status": reachability.get("classification", "not_covered_by_friend_event_report"),
                "routing_status": routing_status,
                "trigger_status": trigger_status,
                "flag_status": flag_status,
                "asset_status": "unknown_dependency",
                "restoration_conflict_count": sum(1 for row in rows if row["restoration_conflict"]),
                "profile_readiness": "metadata_only_not_buildable",
                "default_enabled": False,
            }
        )
    return sorted(output, key=lambda row: (row["family_id"], row["event_id"], row["content_id"]))


def build_trigger_rows(
    *,
    units: Sequence[dict[str, str]],
    placeholder_by_event: dict[str, dict[str, str]],
    reachability_by_event: dict[str, dict[str, str]],
    cue_by_event: dict[str, list[dict[str, str]]],
    trigger_summary: dict[str, Any],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    global_mapping = str(trigger_summary.get("mapping_status", "unavailable"))
    global_framing = str(trigger_summary.get("framing_status", "unavailable"))
    for unit in units:
        identity = event_identity(unit)
        if not identity:
            continue
        _, event_id = identity
        family_id = FAMILY_BY_SUBCATEGORY.get(unit.get("subcategory", ""), "unknown")
        reach = reachability_by_event.get(event_id, {})
        placeholder = placeholder_by_event.get(event_id, {})
        cues = cue_by_event.get(event_id, [])
        cue_labels = sorted({row.get("cue_label", "") for row in cues if row.get("cue_label")})
        rows.append(
            {
                "content_id": content_id_for_unit(unit),
                "family_id": family_id,
                "event_id": event_id,
                "source_message_present": reach.get("source_jp_message_present", "unknown"),
                "target_message_present": reach.get("target_jp_message_present", "unknown"),
                "source_control_present": reach.get("source_ebd_present", "unknown"),
                "target_control_present": reach.get("target_ebd_present", "unknown"),
                "message_classification": reach.get("event_message_classification", "not_covered"),
                "control_classification": reach.get("event_data_classification", "not_covered"),
                "placeholder_classification": placeholder.get("classification", "not_recorded"),
                "source_direct_control_references": reach.get("source_direct_control_reference_count", "unknown"),
                "target_direct_control_references": reach.get("target_direct_control_reference_count", "unknown"),
                "event_process_framing_status": global_framing,
                "event_process_mapping_status": global_mapping,
                "routing_status": "unresolved_event_process_framing",
                "trigger_status": "unresolved_event_process_framing",
                "flag_status": "unknown_progress_or_dlc_flag_dependency",
                "cue_labels": ",".join(cue_labels),
                "evidence_status": "metadata_only_no_reachability_claim",
            }
        )
    return sorted(rows, key=lambda row: (row["family_id"], row["event_id"]))


def compatibility_for_binding(row: dict[str, Any]) -> tuple[str, str]:
    status = row["binding_status"]
    source_size = parse_int(row.get("source_size"), -1)
    target_size = parse_int(row.get("target_size"), -2)
    if status == "present_identical":
        return "directly_compatible", "same hash"
    if status == "present_but_disabled":
        if row["text_managed_by_translation"]:
            return "translation_supplies_text_adapter_must_not_duplicate", "target member exists as disabled text payload"
        return "disabled_member_requires_routing_review", "member exists but is not active"
    if status == "present_modified":
        if source_size >= 0 and source_size == target_size:
            return "same_size_format_review_required", "same-size member differs"
        return "format_or_structure_review_required", "member sizes differ or target-only member"
    if status == "missing_portable_from_br1":
        return "portable_candidate_unverified", "source-only member requires local transfer compatibility test"
    if status == "missing_requires_conversion":
        return "conversion_required_unverified", "source-only member is not directly portable"
    return "unknown_dependency", "no complete mapping"


def build_asset_compatibility(
    *,
    bindings: Sequence[dict[str, Any]],
    families: Sequence[str],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for binding in bindings:
        compatibility, note = compatibility_for_binding(binding)
        rows.append(
            {
                "family_id": binding["family_id"],
                "content_id": binding["content_id"],
                "asset_class": binding["member_role"],
                "normalized_path": binding["normalized_path"],
                "source_size": binding["source_size"],
                "target_size": binding["target_size"],
                "binding_status": binding["binding_status"],
                "compatibility_status": compatibility,
                "translation_owned": binding["text_managed_by_translation"],
                "restoration_conflict": binding["restoration_conflict"],
                "notes": note,
            }
        )
    generic_classes = (
        "maps_and_locations", "costumes_models_textures", "animations_and_cameras",
        "effects", "voices", "bgm_and_sound", "ui_and_messages", "rewards_and_flags",
    )
    for family_id in sorted(set(families) - {"system_registry"}):
        for asset_class in generic_classes:
            rows.append(
                {
                    "family_id": family_id,
                    "content_id": f"family:{family_id}",
                    "asset_class": asset_class,
                    "normalized_path": "",
                    "source_size": "",
                    "target_size": "",
                    "binding_status": "unknown_dependency",
                    "compatibility_status": "not_yet_mapped",
                    "translation_owned": False,
                    "restoration_conflict": False,
                    "notes": "metadata-only stage has not established the required member set",
                }
            )
    return sorted(rows, key=lambda row: (row["family_id"], row["content_id"], row["asset_class"], row["normalized_path"]))


def build_unresolved_dependencies(
    *,
    units: Sequence[dict[str, str]],
    bindings: Sequence[dict[str, Any]],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for unit in units:
        identity = event_identity(unit)
        if not identity:
            continue
        content_id = content_id_for_unit(unit)
        family_id = FAMILY_BY_SUBCATEGORY.get(unit.get("subcategory", ""), "unknown")
        event_id = identity[1]
        for kind, priority, reason in (
            ("routing", "critical", "event-process record framing and event order are unresolved"),
            ("trigger", "critical", "no confirmed incoming trigger edge exists in current reports"),
            ("progress_flag", "critical", "activation/completion flag fields are not decoded"),
            ("asset_bundle", "high", "required map/model/animation/effect/audio member closure is not mapped"),
        ):
            rows.append(
                {
                    "dependency_id": f"{content_id}:{kind}",
                    "family_id": family_id,
                    "content_id": content_id,
                    "event_id": event_id,
                    "dependency_kind": kind,
                    "priority": priority,
                    "status": "unknown_dependency",
                    "reason": reason,
                    "next_evidence_needed": {
                        "routing": "decode eventprocessdataall.epd record framing and map records to event IDs",
                        "trigger": "identify trigger edges or menu/availability registration",
                        "progress_flag": "locate flag read/write callsites or decoded event fields",
                        "asset_bundle": "extract technical references and close member-level dependencies",
                    }[kind],
                }
            )
    for binding in bindings:
        if binding["binding_status"] in {
            "missing_portable_from_br1", "missing_requires_conversion", "missing_requires_reconstruction",
        }:
            rows.append(
                {
                    "dependency_id": f"{binding['content_id']}:member:{stable_node_id('m', binding['normalized_path'])}",
                    "family_id": binding["family_id"],
                    "content_id": binding["content_id"],
                    "event_id": binding["event_id"],
                    "dependency_kind": "member_transfer_or_conversion",
                    "priority": "critical",
                    "status": binding["binding_status"],
                    "reason": binding["notes"],
                    "next_evidence_needed": "rehydrate the source and target parent containers locally and test conversion/repack",
                }
            )
    return sorted(rows, key=lambda row: (row["family_id"], row["content_id"], row["dependency_kind"], row["dependency_id"]))


def build_dependency_graph(
    *,
    units: Sequence[dict[str, str]],
    bindings: Sequence[dict[str, Any]],
) -> dict[str, Any]:
    nodes: dict[str, dict[str, Any]] = {}
    edges: list[dict[str, str]] = []
    families = sorted({FAMILY_BY_SUBCATEGORY.get(unit.get("subcategory", ""), "unknown") for unit in units})
    for family_id in families:
        node_id = f"family:{family_id}"
        nodes[node_id] = {"node_id": node_id, "node_type": "family", "label": family_id}
    shared = {
        "shared:canonical_translation": "canonical Translation records",
        "shared:event_process_routing": "event-process routing",
        "shared:progress_flags": "progress and DLC flags",
        "shared:asset_closure": "map/model/animation/effect/audio closure",
        "shared:system_registry": "str_chat_msg.xml and str_costume.xml",
    }
    for node_id, label in shared.items():
        nodes[node_id] = {"node_id": node_id, "node_type": "shared_dependency", "label": label}
    for unit in units:
        content_id = content_id_for_unit(unit)
        family_id = FAMILY_BY_SUBCATEGORY.get(unit.get("subcategory", ""), "unknown")
        node_id = f"content:{content_id}"
        nodes[node_id] = {
            "node_id": node_id,
            "node_type": "content_unit",
            "label": unit.get("logical_path", ""),
            "family_id": family_id,
        }
        edges.append({"from": node_id, "to": f"family:{family_id}", "relation": "belongs_to"})
        edges.append({"from": node_id, "to": "shared:canonical_translation", "relation": "text_supplied_by"})
        if event_identity(unit):
            edges.extend(
                [
                    {"from": node_id, "to": "shared:event_process_routing", "relation": "requires"},
                    {"from": node_id, "to": "shared:progress_flags", "relation": "requires"},
                    {"from": node_id, "to": "shared:asset_closure", "relation": "requires"},
                    {"from": node_id, "to": "shared:system_registry", "relation": "may_require"},
                ]
            )
    for binding in bindings:
        member_id = f"member:{stable_node_id('path', binding['normalized_path'])}"
        nodes.setdefault(
            member_id,
            {
                "node_id": member_id,
                "node_type": "member",
                "label": binding["normalized_path"],
                "binding_status": binding["binding_status"],
            },
        )
        edges.append(
            {
                "from": f"content:{binding['content_id']}",
                "to": member_id,
                "relation": "maps_member",
            }
        )
    node_rows = sorted(nodes.values(), key=lambda row: row["node_id"])
    edge_rows = sorted(edges, key=lambda row: (row["from"], row["to"], row["relation"]))
    return {
        "type": "br_quartet_legacy_dlc_dependency_graph",
        "format_version": FORMAT_VERSION,
        "tool_version": TOOL_VERSION,
        "nodes": node_rows,
        "edges": edge_rows,
        "policy": {
            "raw_assets_embedded": False,
            "translation_is_separate_database": False,
            "default_enabled": False,
        },
    }


def build_profile_candidates(
    *,
    content_rows: Sequence[dict[str, Any]],
    bindings: Sequence[dict[str, Any]],
    unresolved: Sequence[dict[str, Any]],
) -> dict[str, Any]:
    profiles: list[dict[str, Any]] = []
    for family_id in ("yy", "south_island", "ffxv"):
        family_content = [row for row in content_rows if row["family_id"] == family_id]
        family_bindings = [row for row in bindings if row["family_id"] == family_id]
        family_unresolved = [row for row in unresolved if row["family_id"] == family_id]
        transferable = [
            row for row in family_bindings
            if not row["text_managed_by_translation"]
            and row["binding_status"] in {
                "missing_portable_from_br1", "missing_requires_conversion", "missing_requires_reconstruction",
            }
        ]
        status_counts = Counter(row["binding_status"] for row in family_bindings)
        profiles.append(
            {
                "profile_id": f"candidate_legacy_dlc_{family_id}_metadata_v1",
                "family_id": family_id,
                "status": "metadata_only_not_buildable",
                "default_enabled": False,
                "source_description": "transfer DLC from a selected first-game installation",
                "translation_text_source": "titles/blue_reflection/translation",
                "separate_translation_database": False,
                "raw_assets_included": False,
                "content_ids": [row["content_id"] for row in family_content],
                "member_status_counts": dict(sorted(status_counts.items())),
                "transfer_member_candidates": [
                    {
                        "content_id": row["content_id"],
                        "normalized_path": row["normalized_path"],
                        "status": row["binding_status"],
                    }
                    for row in transferable
                ],
                "blocking_dependency_kinds": sorted({row["dependency_kind"] for row in family_unresolved}),
                "buildable": False,
                "runtime_validated": False,
            }
        )
    return {
        "type": "br_quartet_legacy_dlc_profile_candidates",
        "format_version": FORMAT_VERSION,
        "tool_version": TOOL_VERSION,
        "profiles": profiles,
        "policy": {
            "profiles_are_local_candidates_only": True,
            "profiles_activated": False,
            "game_modified": False,
            "raw_assets_embedded": False,
        },
    }


def validate_report_directory(report_root: Path) -> list[dict[str, Any]]:
    required = {
        "DLC_CONTENT_INVENTORY.tsv",
        "DLC_MEMBER_BINDINGS.tsv",
        "DLC_DEPENDENCY_GRAPH.json",
        "DLC_TRIGGER_AND_FLAG_AUDIT.tsv",
        "DLC_ASSET_COMPATIBILITY.tsv",
        "DLC_UNRESOLVED_DEPENDENCIES.tsv",
        "DLC_PROFILE_CANDIDATES.json",
        "DLC_SOURCE_INSTALLATION_AUDIT.tsv",
        "SUMMARY.json",
    }
    actual = {path.name for path in report_root.iterdir() if path.is_file()}
    missing = sorted(required - actual)
    if missing:
        raise DlcAuditError("missing report files: " + ", ".join(missing))
    manifest_rows: list[dict[str, Any]] = []
    for path in sorted(report_root.rglob("*"), key=lambda item: item.relative_to(report_root).as_posix().casefold()):
        if not path.is_file() or path.name == "REPORT_MANIFEST.json":
            continue
        suffixes = {suffix.casefold() for suffix in path.suffixes}
        forbidden = sorted(suffixes & FORBIDDEN_REPORT_SUFFIXES)
        if forbidden:
            raise DlcAuditError(f"raw or forbidden asset-like report member: {path}")
        manifest_rows.append(
            {
                "path": path.relative_to(report_root).as_posix(),
                "size": path.stat().st_size,
                "sha256": sha256_file(path),
            }
        )
    return manifest_rows


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
        raise DlcAuditError(result.stderr.decode("utf-8", errors="replace")[:4000])
    os.replace(temporary, output)


def audit(
    *,
    project_root: Path,
    original_root: Path | None,
    quartet_root: Path | None,
    verify_archive_hashes: bool,
    create_archive: bool,
) -> tuple[Path, dict[str, Any]]:
    workstream_root = project_root / "workstreams/quartet_legacy_dlc"
    version = (workstream_root / "VERSION").read_text(encoding="utf-8").strip()
    if version != TOOL_VERSION:
        raise DlcAuditError(f"tool/workstream version mismatch: {TOOL_VERSION} != {version}")

    mappings_root = project_root / "titles/blue_reflection/modules/quartet_legacy_dlc/mappings"
    candidate_path = mappings_root / "text_candidate_units.tsv"
    family_path = mappings_root / "legacy_dlc_families.tsv"
    units = read_tsv(candidate_path)
    family_rows = read_tsv(family_path)
    if len(units) != 135:
        raise DlcAuditError(f"expected 135 candidate units, found {len(units)}")
    if sum(parse_int(row.get("record_count")) for row in units) != 1247:
        raise DlcAuditError("candidate record total must remain 1247")

    restoration_root = project_root / ".local/reports/quartet_restoration"
    differences_root = restoration_root / "differences"
    event_differences = load_difference_entries(differences_root / "br1_events.json", "br1_events")
    language_differences = load_difference_entries(differences_root / "br1_language.json", "br1_language")

    placeholder_rows = read_tsv(restoration_root / "fe01_message_placeholder_evidence/FE_EVENT_PLACEHOLDER_SCENE_CANDIDATES.tsv")
    placeholder_by_event = index_by(placeholder_rows, "event_id")
    placeholder_events = set(placeholder_by_event)
    reachability_rows = read_tsv(restoration_root / "friend_event_reachability_evidence/FRIEND_EVENT_SLOT_INVENTORY.tsv")
    reachability_by_event = index_by(reachability_rows, "event_id")
    cue_rows = read_tsv(restoration_root / "event_scene_cue_evidence/EVENT_SCENE_CUE_HITS.tsv")
    cues = cue_index(cue_rows)
    trigger_summary = load_json(restoration_root / "friend_event_trigger_graph_evidence/SUMMARY.json")
    archive_rows = read_tsv(restoration_root / "ARCHIVE_INVENTORY.tsv")
    restoration_changed = load_restoration_changed_members(project_root)

    report_parent = project_root / ".local/reports/quartet_legacy_dlc"
    report_root = report_parent / REPORT_DIR_NAME
    if report_root.exists():
        for path in sorted(report_root.rglob("*"), reverse=True):
            if path.is_file() or path.is_symlink():
                path.unlink()
            elif path.is_dir():
                path.rmdir()
    report_root.mkdir(parents=True, exist_ok=True)

    bindings = build_member_bindings(
        units=units,
        event_differences=event_differences,
        language_differences=language_differences,
        placeholder_events=placeholder_events,
        restoration_changed=restoration_changed,
    )
    content_rows = build_content_inventory(
        units=units,
        bindings=bindings,
        placeholder_by_event=placeholder_by_event,
        reachability_by_event=reachability_by_event,
    )
    trigger_rows = build_trigger_rows(
        units=units,
        placeholder_by_event=placeholder_by_event,
        reachability_by_event=reachability_by_event,
        cue_by_event=cues,
        trigger_summary=trigger_summary,
    )
    families = [row.get("family_id", "") for row in family_rows]
    compatibility_rows = build_asset_compatibility(bindings=bindings, families=families)
    unresolved_rows = build_unresolved_dependencies(units=units, bindings=bindings)
    dependency_graph = build_dependency_graph(units=units, bindings=bindings)
    profile_candidates = build_profile_candidates(
        content_rows=content_rows,
        bindings=bindings,
        unresolved=unresolved_rows,
    )
    installation_rows = archive_installation_audit(
        archive_rows=archive_rows,
        original_root=original_root,
        quartet_root=quartet_root,
        verify_hashes=verify_archive_hashes,
    )

    write_tsv(
        report_root / "DLC_CONTENT_INVENTORY.tsv",
        [
            "content_id", "family_id", "subcategory", "content_type", "unit_path", "logical_path",
            "event_id", "record_count", "translation_status", "source_member_count", "target_member_count",
            "mapped_member_count", "event_message_status", "event_control_status", "system_table_status",
            "placeholder_status", "archive_presence_status", "routing_status", "trigger_status", "flag_status",
            "asset_status", "restoration_conflict_count", "profile_readiness", "default_enabled",
        ],
        content_rows,
    )
    write_tsv(
        report_root / "DLC_MEMBER_BINDINGS.tsv",
        [
            "content_id", "family_id", "subcategory", "event_id", "member_role", "language", "normalized_path",
            "difference_id", "difference_classification", "binding_status", "mapping_basis", "binary_similarity",
            "source_archive", "source_path", "source_size", "source_sha256", "source_exists",
            "target_archive", "target_path", "target_size", "target_sha256", "target_exists",
            "text_managed_by_translation", "restoration_conflict", "notes",
        ],
        bindings,
    )
    write_json(report_root / "DLC_DEPENDENCY_GRAPH.json", dependency_graph)
    write_tsv(
        report_root / "DLC_TRIGGER_AND_FLAG_AUDIT.tsv",
        [
            "content_id", "family_id", "event_id", "source_message_present", "target_message_present",
            "source_control_present", "target_control_present", "message_classification", "control_classification",
            "placeholder_classification", "source_direct_control_references", "target_direct_control_references",
            "event_process_framing_status", "event_process_mapping_status", "routing_status", "trigger_status",
            "flag_status", "cue_labels", "evidence_status",
        ],
        trigger_rows,
    )
    write_tsv(
        report_root / "DLC_ASSET_COMPATIBILITY.tsv",
        [
            "family_id", "content_id", "asset_class", "normalized_path", "source_size", "target_size",
            "binding_status", "compatibility_status", "translation_owned", "restoration_conflict", "notes",
        ],
        compatibility_rows,
    )
    write_tsv(
        report_root / "DLC_UNRESOLVED_DEPENDENCIES.tsv",
        [
            "dependency_id", "family_id", "content_id", "event_id", "dependency_kind", "priority", "status",
            "reason", "next_evidence_needed",
        ],
        unresolved_rows,
    )
    write_json(report_root / "DLC_PROFILE_CANDIDATES.json", profile_candidates)
    write_tsv(
        report_root / "DLC_SOURCE_INSTALLATION_AUDIT.tsv",
        [
            "pair_id", "category", "side", "archive", "expected_size", "actual_size", "file_present",
            "size_match", "expected_sha256", "actual_sha256", "hash_status", "read_only",
        ],
        installation_rows,
    )

    family_counts = Counter(row["family_id"] for row in content_rows)
    family_record_counts: Counter[str] = Counter()
    for row in content_rows:
        family_record_counts[row["family_id"]] += parse_int(row["record_count"])
    binding_counts = Counter(row["binding_status"] for row in bindings)
    summary = {
        "type": "br_quartet_legacy_dlc_inventory_summary",
        "format_version": FORMAT_VERSION,
        "tool_version": TOOL_VERSION,
        "status": "metadata_only_inventory_complete_no_build_or_game_write",
        "workstream_id": WORKSTREAM_ID,
        "source_description": "transfer DLC from a selected first-game installation",
        "candidate_units": len(content_rows),
        "candidate_records": sum(parse_int(row["record_count"]) for row in content_rows),
        "family_unit_counts": dict(sorted(family_counts.items())),
        "family_record_counts": dict(sorted(family_record_counts.items())),
        "member_binding_rows": len(bindings),
        "member_binding_status_counts": dict(sorted(binding_counts.items())),
        "trigger_and_flag_rows": len(trigger_rows),
        "asset_compatibility_rows": len(compatibility_rows),
        "unresolved_dependency_rows": len(unresolved_rows),
        "profile_candidates": len(profile_candidates["profiles"]),
        "installation_archive_rows": len(installation_rows),
        "installation_present_rows": sum(1 for row in installation_rows if row["file_present"]),
        "installation_size_match_rows": sum(1 for row in installation_rows if row["size_match"]),
        "archive_hash_verification_requested": verify_archive_hashes,
        "inputs": {
            "text_candidate_units_sha256": sha256_file(candidate_path),
            "legacy_dlc_families_sha256": sha256_file(family_path),
            "event_differences_sha256": sha256_file(differences_root / "br1_events.json"),
            "language_differences_sha256": sha256_file(differences_root / "br1_language.json"),
            "archive_inventory_sha256": sha256_file(restoration_root / "ARCHIVE_INVENTORY.tsv"),
            "placeholder_evidence_sha256": sha256_file(restoration_root / "fe01_message_placeholder_evidence/FE_EVENT_PLACEHOLDER_SCENE_CANDIDATES.tsv"),
            "reachability_evidence_sha256": sha256_file(restoration_root / "friend_event_reachability_evidence/FRIEND_EVENT_SLOT_INVENTORY.tsv"),
            "trigger_graph_summary_sha256": sha256_file(restoration_root / "friend_event_trigger_graph_evidence/SUMMARY.json"),
        },
        "policy": {
            "separate_workstream": True,
            "default_enabled": False,
            "translation_text_already_imported": True,
            "separate_translation_database": False,
            "translation_modified": False,
            "restoration_modified": False,
            "core_modified": False,
            "raw_assets_exported": False,
            "profiles_activated": False,
            "game_modified": False,
            "git_modified": False,
            "member_level_composition_required": True,
        },
        "limitations": [
            "event-process record framing and trigger mapping remain unresolved",
            "text presence does not prove runtime reachability",
            "asset closure for maps, costumes, animation, effects, audio, UI and rewards is not yet established",
            "profile candidates are metadata-only and not buildable",
        ],
        "next_action": "decode routing/trigger/flag structures and close source-to-target asset dependencies per family before any profile build",
    }
    write_json(report_root / "SUMMARY.json", summary)
    manifest_rows = validate_report_directory(report_root)
    write_json(
        report_root / "REPORT_MANIFEST.json",
        {
            "type": "br_quartet_legacy_dlc_metadata_report_manifest",
            "format_version": FORMAT_VERSION,
            "tool_version": TOOL_VERSION,
            "files": manifest_rows,
            "raw_assets_embedded": False,
        },
    )
    validate_report_directory(report_root)

    archive_path = report_parent / REPORT_ARCHIVE_NAME
    if create_archive:
        make_report_archive(report_root, archive_path)
    return report_root, summary


def cmd_audit(args: argparse.Namespace) -> int:
    project_root = Path(args.project_root).expanduser().resolve()
    original_root = Path(args.original_root).expanduser().resolve() if args.original_root else None
    quartet_root = Path(args.quartet_root).expanduser().resolve() if args.quartet_root else None
    report_root, summary = audit(
        project_root=project_root,
        original_root=original_root,
        quartet_root=quartet_root,
        verify_archive_hashes=args.verify_archive_hashes,
        create_archive=not args.no_report_archive,
    )
    print(f"Metadata-only DLC inventory complete: {report_root}")
    print(f"Candidate units: {summary['candidate_units']}")
    print(f"Member bindings: {summary['member_binding_rows']}")
    print(f"Unresolved dependencies: {summary['unresolved_dependency_rows']}")
    if not args.no_report_archive:
        print(f"Report: {report_root.parent / REPORT_ARCHIVE_NAME}")
    return 0


def cmd_validate(args: argparse.Namespace) -> int:
    report_root = Path(args.report_root).expanduser().resolve()
    rows = validate_report_directory(report_root)
    manifest = load_json(report_root / "REPORT_MANIFEST.json")
    expected = {row["path"]: row for row in manifest.get("files", []) if isinstance(row, dict)}
    actual = {row["path"]: row for row in rows}
    if expected != actual:
        raise DlcAuditError("REPORT_MANIFEST.json does not match report files")
    summary = load_json(report_root / "SUMMARY.json")
    if summary.get("policy", {}).get("game_modified") is not False:
        raise DlcAuditError("summary does not assert game_modified=false")
    print(f"Validated metadata-only report: {report_root}")
    print(f"Files: {len(rows)}")
    return 0


def cmd_bundle(args: argparse.Namespace) -> int:
    report_root = Path(args.report_root).expanduser().resolve()
    output = Path(args.output).expanduser().resolve()
    validate_report_directory(report_root)
    make_report_archive(report_root, output)
    print(f"Metadata-only evidence bundle: {output}")
    print(f"SHA-256: {sha256_file(output)}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    audit_parser = subparsers.add_parser("audit", help="build metadata-only DLC inventory")
    audit_parser.add_argument("--project-root", required=True)
    audit_parser.add_argument("--original-root")
    audit_parser.add_argument("--quartet-root")
    audit_parser.add_argument("--verify-archive-hashes", action="store_true")
    audit_parser.add_argument("--no-report-archive", action="store_true")
    audit_parser.set_defaults(func=cmd_audit)

    validate_parser = subparsers.add_parser("validate-report", help="validate a metadata-only report")
    validate_parser.add_argument("--report-root", required=True)
    validate_parser.set_defaults(func=cmd_validate)

    bundle_parser = subparsers.add_parser("bundle-report", help="build deterministic metadata evidence archive")
    bundle_parser.add_argument("--report-root", required=True)
    bundle_parser.add_argument("--output", required=True)
    bundle_parser.set_defaults(func=cmd_bundle)
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    try:
        return int(args.func(args))
    except DlcAuditError as exc:
        eprint(f"ERROR: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
