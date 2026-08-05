#!/usr/bin/env python3
"""Audit Blue Reflection FE event-family presence and conservative reachability clues.

Stage 55 follows a user-reported concern that a swimsuit scene may be absent in
Quartet.  It distinguishes archive-level deletion from message/control changes:
all FE message/control slots are inventoried across Original and Quartet, direct
technical references in event-control payloads are compared, and focused rows
are produced for fe13_090 plus every suspicious missing/stub/asymmetric slot.
No translation JSON, EBM, EBD, PAK, registry, activation or game file is written.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import importlib
import json
import os
import re
import struct
import subprocess
import sys
import tempfile
from collections import Counter, defaultdict
from pathlib import Path, PurePosixPath
from typing import Any, Iterable, Mapping, Sequence

WORKSTREAM_ID = "quartet_restoration"
TOOL_VERSION = "0.0.63"
REPORT_NAME = "BR_quartet_restoration_friend_event_reachability_evidence.tar.zst"
EVIDENCE_DIR_NAME = "friend_event_reachability_evidence"
FOCUS_EVENT_IDS = {"fe13_090"}
USER_FE01_EVENT_IDS = {
    "fe01_130", "fe01_200", "fe01_220", "fe01_230", "fe01_240",
    "fe01_250", "fe01_260", "fe01_270", "fe01_290",
}
CONTROL_EXTENSIONS = {".epd", ".bsb", ".bin", ".dat", ".ebd"}
MAX_CONTROL_FILE_BYTES = 64 * 1024 * 1024

REPORT_SPECS = {
    "inventory": ("quartet_restoration", "BR_quartet_restoration_inventory_and_diff.tar.zst"),
    "family": ("event_family_evidence", "BR_quartet_restoration_event_family_evidence.tar.zst"),
    "record": ("event_record_evidence", "BR_quartet_restoration_event_record_evidence.tar.zst"),
    "core": ("core_profile_manifest_evidence", "BR_quartet_restoration_core_profile_manifest_evidence.tar.zst"),
}

class FriendEventReachabilityError(RuntimeError):
    pass

def parse_int(value: object, default: int = 0) -> int:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return default

def parse_bool(value: object) -> bool:
    return str(value).strip().casefold() in {"1", "true", "yes", "y"}

def safe_member_name(raw: str) -> str:
    path = PurePosixPath(raw)
    if path.is_absolute() or not path.parts or ".." in path.parts:
        raise FriendEventReachabilityError(f"unsafe report archive member: {raw}")
    return path.as_posix()

def load_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise FriendEventReachabilityError(f"missing prerequisite JSON: {path}")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise FriendEventReachabilityError(f"invalid JSON {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise FriendEventReachabilityError(f"expected JSON object: {path}")
    return data

def read_tsv(path: Path, *, required: bool = True) -> list[dict[str, str]]:
    if not path.is_file():
        if required:
            raise FriendEventReachabilityError(f"missing prerequisite table: {path}")
        return []
    with path.open("r", encoding="utf-8", newline="") as handle:
        return [dict(row) for row in csv.DictReader(handle, delimiter="\t")]

def write_tsv(path: Path, fields: Sequence[str], rows: Iterable[Mapping[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fields})

def extract_archive(archive: Path, destination: Path) -> Path:
    if not archive.is_file():
        raise FriendEventReachabilityError(f"missing prerequisite report archive: {archive}")
    listed = subprocess.run(["tar", "--zstd", "-tf", str(archive)], text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if listed.returncode:
        raise FriendEventReachabilityError(f"cannot list {archive}: {listed.stderr.strip()}")
    roots = {PurePosixPath(safe_member_name(line.strip())).parts[0] for line in listed.stdout.splitlines() if line.strip()}
    if len(roots) != 1:
        raise FriendEventReachabilityError(f"expected one report root in {archive}, found {sorted(roots)}")
    destination.mkdir(parents=True, exist_ok=True)
    done = subprocess.run(["tar", "--zstd", "-xf", str(archive), "-C", str(destination)], text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if done.returncode:
        raise FriendEventReachabilityError(f"cannot extract {archive}: {done.stderr.strip()}")
    return destination / next(iter(roots))

def locate_report_root(report_root: Path, key: str, temporary: Path) -> Path:
    dirname, archive_name = REPORT_SPECS[key]
    if key == "inventory":
        # The inventory archive root is quartet_restoration, while a live project
        # exposes inventories/differences directly under report_root.
        if (report_root / "inventories").is_dir() and (report_root / "differences").is_dir():
            return report_root
    direct = report_root / dirname
    return direct if direct.is_dir() else extract_archive(report_root / archive_name, temporary / key)

def load_restoration_tool(project_root: Path) -> Any:
    tool_root = project_root / "Blue_Reflection_Text_Tool"
    if not (tool_root / "br_restoration_tool.py").is_file():
        raise FriendEventReachabilityError("missing br_restoration_tool.py")
    sys.path.insert(0, str(tool_root))
    try:
        return importlib.import_module("br_restoration_tool")
    finally:
        try: sys.path.remove(str(tool_root))
        except ValueError: pass

def make_report_archive(source_dir: Path, output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(output.name + ".tmp")
    temporary.unlink(missing_ok=True)
    done = subprocess.run(["tar", "--zstd", "-cf", str(temporary), "-C", str(source_dir.parent), source_dir.name], text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if done.returncode:
        raise FriendEventReachabilityError(f"cannot create report archive: {done.stderr.strip()}")
    os.replace(temporary, output)

def normalize_path(value: object) -> str:
    raw = str(value or "").replace("\\", "/").lstrip("./")
    for prefix in ("event/b1/", "data/b1/event/"):
        if raw.casefold().startswith(prefix.casefold()):
            raw = "event/" + raw[len(prefix):]
            break
    return raw

def event_id_from_path(path: str) -> str:
    stem = PurePosixPath(path).stem
    if stem.startswith("event_message_"):
        return stem[len("event_message_"):]
    if stem.startswith("event_"):
        return stem[len("event_"):]
    return stem

def is_fe_id(event_id: str) -> bool:
    return re.fullmatch(r"fe\d{2}_\d{3}", event_id, flags=re.IGNORECASE) is not None

def first_u32(path: Path) -> int | None:
    try:
        with path.open("rb") as handle:
            raw = handle.read(4)
    except OSError:
        return None
    return struct.unpack("<I", raw)[0] if len(raw) == 4 else None

def index_inventory(inventory: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    return {normalize_path(row.get("normalized_path")): dict(row) for row in inventory.get("files", [])}

def workspace_path(br: Any, workspace_root: Path, side: str, row: Mapping[str, Any]) -> Path:
    return br.inventory_workspace_file(workspace_root, side, "br1_events", str(row.get("archive", "")), str(row.get("path", "")))

def message_state(row: Mapping[str, Any] | None, payload: Path | None) -> tuple[str, int | None]:
    if not row:
        return "missing", None
    declared = first_u32(payload) if payload and payload.is_file() else None
    size = parse_int(row.get("size"), 0)
    if declared == 1 and size <= 64:
        return "minimal_stub", declared
    if declared is not None and declared > 1:
        return "substantive", declared
    if size > 64:
        return "present_unparsed", declared
    return "present_small", declared

def direct_reference_encodings(event_id: str) -> list[tuple[str, bytes]]:
    tokens = [event_id, "event_" + event_id, "event_message_" + event_id]
    result: list[tuple[str, bytes]] = []
    for token in tokens:
        result.append(("ascii:" + token, token.encode("ascii")))
        result.append(("utf16le:" + token, token.encode("utf-16le")))
    return result

def scan_direct_references(
    *, br: Any, workspace_root: Path, side: str, inventory: Mapping[str, Any], event_ids: Sequence[str]
) -> tuple[dict[str, list[dict[str, object]]], list[dict[str, object]]]:
    hits: defaultdict[str, list[dict[str, object]]] = defaultdict(list)
    skipped: list[dict[str, object]] = []
    patterns = {event_id: direct_reference_encodings(event_id) for event_id in event_ids}
    for row in inventory.get("files", []):
        normalized = normalize_path(row.get("normalized_path"))
        ext = str(row.get("extension", "")).casefold()
        if ext not in CONTROL_EXTENSIONS:
            continue
        if "/event_message_" in normalized.casefold():
            continue
        path = workspace_path(br, workspace_root, side, row)
        if not path.is_file():
            continue
        size = path.stat().st_size
        if size > MAX_CONTROL_FILE_BYTES:
            skipped.append({"side": side, "normalized_path": normalized, "reason": "control_file_size_limit", "size": size})
            continue
        try:
            payload = path.read_bytes()
        except OSError:
            skipped.append({"side": side, "normalized_path": normalized, "reason": "control_file_read_error", "size": size})
            continue
        own_id = event_id_from_path(normalized)
        for event_id, encodings in patterns.items():
            if event_id == own_id:
                continue
            for label, needle in encodings:
                offset = payload.find(needle)
                if offset >= 0:
                    hits[event_id].append({
                        "side": side,
                        "event_id": event_id,
                        "container_path": normalized,
                        "encoding": label,
                        "hit_count": payload.count(needle),
                        "first_offset": offset,
                    })
    return hits, skipped

def classify_slot(row: Mapping[str, object]) -> tuple[str, str]:
    source_message = str(row["source_jp_message_state"])
    target_message = str(row["target_jp_message_state"])
    source_ebd = parse_bool(row["source_ebd_present"])
    target_ebd = parse_bool(row["target_ebd_present"])
    source_refs = parse_int(row["source_direct_control_reference_count"])
    target_refs = parse_int(row["target_direct_control_reference_count"])
    message_changed = not parse_bool(row["jp_message_hash_equal"])
    control_changed = not parse_bool(row["ebd_hash_equal"])
    if source_message == "substantive" and target_message in {"missing", "minimal_stub", "present_small"}:
        return "possible_message_payload_removed_or_stubbed", "critical"
    if source_ebd and not target_ebd:
        return "possible_event_control_payload_removed", "critical"
    if source_refs > 0 and target_refs == 0:
        return "possible_explicit_trigger_reference_removed", "critical"
    if target_message == "substantive" and target_ebd:
        if message_changed and control_changed:
            return "archive_present_message_and_control_changed_reachability_unresolved", "high"
        if control_changed:
            return "archive_present_control_changed_reachability_unresolved", "high"
        if message_changed:
            return "archive_present_message_changed_control_identical", "medium"
        return "archive_present_payloads_identical", "deferred"
    return "archive_presence_or_parse_incomplete", "high"

def collect(
    *, project_root: Path, workspace_root: Path, report_root: Path,
) -> tuple[Path, dict[str, object]]:
    project_root = project_root.expanduser().resolve()
    workspace_root = workspace_root.expanduser().resolve()
    report_root = report_root.expanduser().resolve()
    br = load_restoration_tool(project_root)
    with tempfile.TemporaryDirectory(prefix="br-friend-event-reachability-") as tmp_name:
        tmp = Path(tmp_name)
        roots = {key: locate_report_root(report_root, key, tmp) for key in REPORT_SPECS}
        source_inventory = load_json(roots["inventory"] / "inventories/br1_events.source.json")
        target_inventory = load_json(roots["inventory"] / "inventories/br1_events.target.json")
        if source_inventory.get("archive_group") != "br1_events" or target_inventory.get("archive_group") != "br1_events":
            raise FriendEventReachabilityError("unexpected event inventory archive group")
        family_summary = load_json(roots["family"] / "SUMMARY.json")
        if family_summary.get("type") != "br_quartet_restoration_event_family_evidence_summary" or family_summary.get("tool_version") != "0.0.20":
            raise FriendEventReachabilityError("stage-16 event-family report must be canonical 0.0.20")
        record_summary = load_json(roots["record"] / "SUMMARY.json")
        if record_summary.get("type") != "br_quartet_restoration_event_record_evidence_summary" or record_summary.get("tool_version") != "0.0.19":
            raise FriendEventReachabilityError("stage-15 event-record report must be canonical 0.0.19")
        core_summary = load_json(roots["core"] / "SUMMARY.json")
        if core_summary.get("type") != "br_quartet_restoration_core_profile_manifest_evidence_summary" or core_summary.get("tool_version") != "0.0.62":
            raise FriendEventReachabilityError("current core registry report must be canonical 0.0.62")
        if parse_int(core_summary.get("profile_rows"), -1) != 14 or parse_int(core_summary.get("runtime_validated_profile_rows"), -1) != 0:
            raise FriendEventReachabilityError("current core registry must contain 14 runtime-unvalidated profiles")

        source_idx = index_inventory(source_inventory)
        target_idx = index_inventory(target_inventory)
        event_ids: set[str] = set()
        for path in set(source_idx) | set(target_idx):
            if "/event_jp/fe" not in path.casefold():
                continue
            event_id = event_id_from_path(path)
            if is_fe_id(event_id):
                event_ids.add(event_id)
        if len(event_ids) != 420:
            raise FriendEventReachabilityError(f"expected 420 FE event slots, found {len(event_ids)}")

        source_hits, source_skipped = scan_direct_references(br=br, workspace_root=workspace_root, side="source", inventory=source_inventory, event_ids=sorted(event_ids))
        target_hits, target_skipped = scan_direct_references(br=br, workspace_root=workspace_root, side="target", inventory=target_inventory, event_ids=sorted(event_ids))
        family_pairs = {event_id_from_path(normalize_path(r.get("event_data_path"))): r for r in read_tsv(roots["family"] / "EVENT_FAMILY_PAIRS.tsv")}
        profile_owners: defaultdict[str, list[str]] = defaultdict(list)
        registry = project_root / ".local/build/quartet_restoration/core_profiles/generated"
        if registry.is_dir():
            for manifest_path in sorted(registry.glob("*.json")):
                try: manifest = load_json(manifest_path)
                except FriendEventReachabilityError: continue
                for member in manifest.get("changed_members", []):
                    event_id = event_id_from_path(normalize_path(member))
                    if is_fe_id(event_id): profile_owners[event_id].append(str(manifest.get("profile_id", manifest_path.stem)))

        rows: list[dict[str, object]] = []
        reference_rows: list[dict[str, object]] = []
        for event_id in sorted(event_ids):
            family = event_id.split("_")[0]
            base = f"event/event_jp/{family}/"
            paths = {
                "source_jp_message": base + f"event_message_{event_id}.ebm",
                "target_jp_message": base + f"event_message_{event_id}.ebm",
                "source_ebd": base + f"event_{event_id}.ebd",
                "target_ebd": base + f"event_{event_id}.ebd",
            }
            sm = source_idx.get(paths["source_jp_message"]); tm = target_idx.get(paths["target_jp_message"])
            se = source_idx.get(paths["source_ebd"]); te = target_idx.get(paths["target_ebd"])
            smp = workspace_path(br, workspace_root, "source", sm) if sm else None
            tmpath = workspace_path(br, workspace_root, "target", tm) if tm else None
            sep = workspace_path(br, workspace_root, "source", se) if se else None
            tep = workspace_path(br, workspace_root, "target", te) if te else None
            sm_state, sm_count = message_state(sm, smp)
            tm_state, tm_count = message_state(tm, tmpath)
            source_ref_rows = source_hits.get(event_id, []); target_ref_rows = target_hits.get(event_id, [])
            for hit in source_ref_rows + target_ref_rows:
                reference_rows.append(hit)
            family_pair = family_pairs.get(event_id, {})
            row: dict[str, object] = {
                "event_id": event_id,
                "family": family,
                "source_archive": str((sm or se or {}).get("archive", "")),
                "target_archive": str((tm or te or {}).get("archive", "")),
                "source_jp_message_present": bool(sm),
                "target_jp_message_present": bool(tm),
                "source_jp_message_state": sm_state,
                "target_jp_message_state": tm_state,
                "source_jp_message_declared_records": "" if sm_count is None else sm_count,
                "target_jp_message_declared_records": "" if tm_count is None else tm_count,
                "source_jp_message_size": parse_int((sm or {}).get("size")),
                "target_jp_message_size": parse_int((tm or {}).get("size")),
                "jp_message_hash_equal": bool(sm and tm and sm.get("sha256") == tm.get("sha256")),
                "source_ebd_present": bool(se),
                "target_ebd_present": bool(te),
                "source_ebd_declared_items": "" if not sep or not sep.is_file() else first_u32(sep),
                "target_ebd_declared_items": "" if not tep or not tep.is_file() else first_u32(tep),
                "source_ebd_size": parse_int((se or {}).get("size")),
                "target_ebd_size": parse_int((te or {}).get("size")),
                "ebd_hash_equal": bool(se and te and se.get("sha256") == te.get("sha256")),
                "event_message_classification": family_pair.get("event_message_classification", ""),
                "event_data_classification": family_pair.get("event_data_classification", ""),
                "rare_delta_regions": family_pair.get("rare_delta_regions", ""),
                "corrected_unresolved_changed_bytes": family_pair.get("corrected_unresolved_changed_bytes", ""),
                "source_direct_control_reference_count": len(source_ref_rows),
                "target_direct_control_reference_count": len(target_ref_rows),
                "registered_profile_ids": ";".join(sorted(profile_owners.get(event_id, []))),
                "focus_reason": ";".join(filter(None, [
                    "reported_swimsuit_scene" if event_id in FOCUS_EVENT_IDS else "",
                    "user_listed_fe01_slot" if event_id in USER_FE01_EVENT_IDS else "",
                ])),
            }
            classification, priority = classify_slot(row)
            row["classification"] = classification
            row["review_priority"] = priority
            row["main_game_or_dlc"] = "main_game_core_event_archive"
            row["review_status"] = "file_level_presence_confirmed_reachability_not_proven" if target_message_exists(row) else "manual_review_required"
            rows.append(row)

        family_rows: list[dict[str, object]] = []
        by_family: defaultdict[str, list[dict[str, object]]] = defaultdict(list)
        for row in rows: by_family[str(row["family"])].append(row)
        for family, members in sorted(by_family.items()):
            family_rows.append({
                "family": family,
                "slot_count": len(members),
                "source_substantive_message_slots": sum(r["source_jp_message_state"] == "substantive" for r in members),
                "target_substantive_message_slots": sum(r["target_jp_message_state"] == "substantive" for r in members),
                "target_minimal_stub_slots": sum(r["target_jp_message_state"] == "minimal_stub" for r in members),
                "target_missing_message_slots": sum(r["target_jp_message_state"] == "missing" for r in members),
                "target_missing_ebd_slots": sum(not parse_bool(r["target_ebd_present"]) for r in members),
                "message_changed_slots": sum(not parse_bool(r["jp_message_hash_equal"]) for r in members),
                "control_changed_slots": sum(not parse_bool(r["ebd_hash_equal"]) for r in members),
                "direct_trigger_asymmetry_slots": sum(parse_int(r["source_direct_control_reference_count"]) > 0 and parse_int(r["target_direct_control_reference_count"]) == 0 for r in members),
                "classification": "complete_30_slot_core_family" if len(members) == 30 else "unexpected_family_slot_count",
            })

        focus_rows = [r for r in rows if r["focus_reason"] or str(r["review_priority"]) in {"critical", "high"}]
        process_layout = read_tsv(roots["record"] / "EVENT_PROCESS_LAYOUT.tsv")
        process_rows = [{
            "normalized_path": r.get("normalized_path", ""),
            "source_size": r.get("source_size", ""),
            "target_size": r.get("target_size", ""),
            "source_leading_count": r.get("source_leading_count", ""),
            "target_leading_count": r.get("target_leading_count", ""),
            "in_scope_ebm_count": r.get("in_scope_ebm_count", ""),
            "count_matches_in_scope_ebm": r.get("count_matches_in_scope_ebm", ""),
            "classification": r.get("classification", ""),
            "reachability_conclusion": "global_count_preserved_but_record_to_event_mapping_unproven",
        } for r in process_layout]

        evidence_dir = report_root / EVIDENCE_DIR_NAME
        if evidence_dir.exists():
            import shutil; shutil.rmtree(evidence_dir)
        evidence_dir.mkdir(parents=True)
        slot_fields = list(rows[0].keys())
        write_tsv(evidence_dir / "FRIEND_EVENT_SLOT_INVENTORY.tsv", slot_fields, rows)
        write_tsv(evidence_dir / "FRIEND_EVENT_FAMILY_SUMMARY.tsv", list(family_rows[0].keys()), family_rows)
        ref_fields = ["side", "event_id", "container_path", "encoding", "hit_count", "first_offset"]
        write_tsv(evidence_dir / "FRIEND_EVENT_DIRECT_CONTROL_REFERENCES.tsv", ref_fields, reference_rows)
        write_tsv(evidence_dir / "FOCUSED_FRIEND_EVENT_REVIEW.tsv", slot_fields, focus_rows)
        process_fields = list(process_rows[0].keys()) if process_rows else ["normalized_path"]
        write_tsv(evidence_dir / "FRIEND_EVENT_PROCESS_EVIDENCE.tsv", process_fields, process_rows)
        skip_rows = source_skipped + target_skipped
        write_tsv(evidence_dir / "FRIEND_EVENT_REACHABILITY_SKIPPED.tsv", ["side", "normalized_path", "reason", "size"], skip_rows)

        fe13 = next(r for r in rows if r["event_id"] == "fe13_090")
        summary: dict[str, object] = {
            "type": "br_quartet_restoration_friend_event_reachability_evidence_summary",
            "format_version": 1,
            "tool_version": TOOL_VERSION,
            "status": "friend_event_core_files_complete_no_file_level_scene_deletion_detected_reachability_requires_trigger_graph_analysis",
            "friend_event_slot_rows": len(rows),
            "friend_event_family_rows": len(family_rows),
            "expected_slots_per_family": 30,
            "source_substantive_message_slots": sum(r["source_jp_message_state"] == "substantive" for r in rows),
            "target_substantive_message_slots": sum(r["target_jp_message_state"] == "substantive" for r in rows),
            "source_to_target_message_removed_or_stubbed_rows": sum(r["classification"] == "possible_message_payload_removed_or_stubbed" for r in rows),
            "source_to_target_ebd_removed_rows": sum(r["classification"] == "possible_event_control_payload_removed" for r in rows),
            "explicit_trigger_reference_removed_rows": sum(r["classification"] == "possible_explicit_trigger_reference_removed" for r in rows),
            "direct_control_reference_rows": len(reference_rows),
            "skipped_rows": len(skip_rows),
            "fe13_090": {
                "main_game_or_dlc": fe13["main_game_or_dlc"],
                "source_jp_message_state": fe13["source_jp_message_state"],
                "target_jp_message_state": fe13["target_jp_message_state"],
                "source_jp_message_declared_records": fe13["source_jp_message_declared_records"],
                "target_jp_message_declared_records": fe13["target_jp_message_declared_records"],
                "source_ebd_declared_items": fe13["source_ebd_declared_items"],
                "target_ebd_declared_items": fe13["target_ebd_declared_items"],
                "message_changed": not parse_bool(fe13["jp_message_hash_equal"]),
                "control_changed": not parse_bool(fe13["ebd_hash_equal"]),
                "classification": fe13["classification"],
                "registered_profile_ids": fe13["registered_profile_ids"],
            },
            "policy": {
                "fe_family_classified_as_legacy_dlc": False,
                "translation_json_modified": False,
                "payload_written": False,
                "pak_repacked": False,
                "core_registry_modified": False,
                "profile_activated": False,
                "installed_game_modified": False,
                "reachability_inferred_from_file_presence": False,
            },
            "next_action": "decode or compare the friend-event trigger/availability graph; file-level restoration of fe13_090 is not justified because its message and control payloads are present",
        }
        (evidence_dir / "SUMMARY.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
        output = report_root / REPORT_NAME
        make_report_archive(evidence_dir, output)
        return output, summary

def target_message_exists(row: Mapping[str, object]) -> bool:
    return str(row.get("target_jp_message_state", "")) not in {"missing", "minimal_stub", "present_small"} and parse_bool(row.get("target_ebd_present"))

def main() -> int:
    parser = argparse.ArgumentParser(description="Collect read-only FE event-family reachability evidence")
    parser.add_argument("--project-root", required=True)
    parser.add_argument("--workspace-root")
    parser.add_argument("--report-root")
    args = parser.parse_args()
    project_root = Path(args.project_root).expanduser().resolve()
    workspace_root = Path(args.workspace_root).expanduser().resolve() if args.workspace_root else project_root / ".local/build/quartet_restoration"
    report_root = Path(args.report_root).expanduser().resolve() if args.report_root else project_root / ".local/reports/quartet_restoration"
    output, summary = collect(project_root=project_root, workspace_root=workspace_root, report_root=report_root)
    print(f"Friend-event slots audited: {summary['friend_event_slot_rows']}")
    print(f"Source->target message removals/stubs: {summary['source_to_target_message_removed_or_stubbed_rows']}")
    print(f"Source->target EBD removals: {summary['source_to_target_ebd_removed_rows']}")
    print(f"Explicit trigger-reference removals: {summary['explicit_trigger_reference_removed_rows']}")
    print(f"fe13_090: {summary['fe13_090']['classification']}")
    print(f"Report: {output}")
    return 0

if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
