#!/usr/bin/env python3
"""Audit FE message records for scene-wide placeholder replacement in Quartet.

Stage 57 was prompted by nine user-listed fe01 translation records that lacked
useful Quartet auxiliary text.  The earlier archive audit proved that the files
exist, but file presence is not content preservation.  This stage parses EBM
records from Original and Quartet across available languages, compares message
metadata without exporting dialogue, and detects exact scene-wide placeholder
payloads such as one literal '-' in every record.

No translation JSON, EBM, EBD, PAK, registry state, activation state or
installed-game file is modified.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import importlib
import json
import os
import subprocess
import sys
import tempfile
from collections import Counter
from pathlib import Path, PurePosixPath
from typing import Any, Iterable, Mapping, Sequence

WORKSTREAM_ID = "quartet_restoration"
TOOL_VERSION = "0.0.65"
REPORT_NAME = "BR_quartet_restoration_fe01_message_placeholder_evidence.tar.zst"
EVIDENCE_DIR_NAME = "fe01_message_placeholder_evidence"
STAGE55_REPORT_NAME = "BR_quartet_restoration_friend_event_reachability_evidence.tar.zst"
STAGE55_DIR_NAME = "friend_event_reachability_evidence"
STAGE56_REPORT_NAME = "BR_quartet_restoration_friend_event_trigger_graph_evidence.tar.zst"
STAGE56_DIR_NAME = "friend_event_trigger_graph_evidence"
INVENTORY_REPORT_NAME = "BR_quartet_restoration_inventory_and_diff.tar.zst"
FOCUS_EVENT_IDS = (
    "fe01_130", "fe01_200", "fe01_220", "fe01_230", "fe01_240",
    "fe01_250", "fe01_260", "fe01_270", "fe01_290",
)
SOURCE_LANGUAGES = ("event_jp", "event_en", "event_tc")
TARGET_LANGUAGES = ("event_jp", "event_en", "event_sc", "event_tc")
PLACEHOLDER_TEXT = "-"


class PlaceholderAuditError(RuntimeError):
    pass


def parse_bool(value: object) -> bool:
    return str(value).strip().casefold() in {"1", "true", "yes", "y"}


def parse_int(value: object, default: int = 0) -> int:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return default


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def sha256_text(value: str) -> str:
    return sha256_bytes(value.encode("utf-8"))


def load_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise PlaceholderAuditError(f"missing prerequisite JSON: {path}")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PlaceholderAuditError(f"invalid JSON {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise PlaceholderAuditError(f"expected JSON object: {path}")
    return data


def read_tsv(path: Path, *, required: bool = True) -> list[dict[str, str]]:
    if not path.is_file():
        if required:
            raise PlaceholderAuditError(f"missing prerequisite table: {path}")
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


def safe_member_name(raw: str) -> str:
    path = PurePosixPath(raw)
    if path.is_absolute() or not path.parts or ".." in path.parts:
        raise PlaceholderAuditError(f"unsafe report archive member: {raw}")
    return path.as_posix()


def extract_archive(archive: Path, destination: Path) -> Path:
    if not archive.is_file():
        raise PlaceholderAuditError(f"missing prerequisite report archive: {archive}")
    listed = subprocess.run(
        ["tar", "--zstd", "-tf", str(archive)], text=True,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    if listed.returncode:
        raise PlaceholderAuditError(f"cannot list {archive}: {listed.stderr.strip()}")
    roots = {
        PurePosixPath(safe_member_name(line.strip())).parts[0]
        for line in listed.stdout.splitlines() if line.strip()
    }
    if len(roots) != 1:
        raise PlaceholderAuditError(f"expected one report root in {archive}, found {sorted(roots)}")
    destination.mkdir(parents=True, exist_ok=True)
    done = subprocess.run(
        ["tar", "--zstd", "-xf", str(archive), "-C", str(destination)], text=True,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    if done.returncode:
        raise PlaceholderAuditError(f"cannot extract {archive}: {done.stderr.strip()}")
    return destination / next(iter(roots))


def locate_named_root(report_root: Path, dirname: str, archive_name: str, temporary: Path) -> Path:
    direct = report_root / dirname
    return direct if direct.is_dir() else extract_archive(report_root / archive_name, temporary)


def locate_inventory_root(report_root: Path, temporary: Path) -> Path:
    if (report_root / "inventories").is_dir() and (report_root / "differences").is_dir():
        return report_root
    direct = report_root / "quartet_restoration"
    if (direct / "inventories").is_dir():
        return direct
    return extract_archive(report_root / INVENTORY_REPORT_NAME, temporary)


def make_report_archive(source_dir: Path, output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(output.name + ".tmp")
    temporary.unlink(missing_ok=True)
    done = subprocess.run(
        ["tar", "--zstd", "-cf", str(temporary), "-C", str(source_dir.parent), source_dir.name],
        text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    if done.returncode:
        raise PlaceholderAuditError(f"cannot create report archive: {done.stderr.strip()}")
    os.replace(temporary, output)


def load_tools(project_root: Path) -> tuple[Any, Any]:
    tool_root = project_root / "Blue_Reflection_Text_Tool"
    if not (tool_root / "br_restoration_tool.py").is_file():
        raise PlaceholderAuditError("missing br_restoration_tool.py")
    if not (tool_root / "br_text_tool.py").is_file():
        raise PlaceholderAuditError("missing br_text_tool.py")
    sys.path.insert(0, str(tool_root))
    try:
        return importlib.import_module("br_restoration_tool"), importlib.import_module("br_text_tool")
    finally:
        try:
            sys.path.remove(str(tool_root))
        except ValueError:
            pass


def normalize_path(value: object) -> str:
    raw = str(value or "").replace("\\", "/").lstrip("./")
    for prefix in ("event/b1/", "data/b1/event/"):
        if raw.casefold().startswith(prefix.casefold()):
            raw = "event/" + raw[len(prefix):]
            break
    return raw


def index_inventory(inventory: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    return {normalize_path(row.get("normalized_path")): dict(row) for row in inventory.get("files", [])}


def event_message_path(event_id: str, language: str) -> str:
    family = event_id.split("_", 1)[0]
    return f"event/{language}/{family}/event_message_{event_id}.ebm"


def workspace_path(br: Any, workspace_root: Path, side: str, row: Mapping[str, Any]) -> Path:
    return br.inventory_workspace_file(
        workspace_root, side, "br1_events", str(row.get("archive", "")), str(row.get("path", ""))
    )


def metadata_tuple(message: Any) -> tuple[object, ...]:
    return (
        message.type, message.voice_id, message.unknown1, message.name_id,
        message.extra_id, message.expr_id, tuple(message.duration1),
        message.msg_id, message.unknown2, tuple(message.duration2),
    )


def metadata_sequence_sha(messages: Sequence[Any]) -> str:
    encoded = json.dumps([metadata_tuple(message) for message in messages], separators=(",", ":"), ensure_ascii=True)
    return sha256_text(encoded)


def text_sequence_sha(messages: Sequence[Any]) -> str:
    digest = hashlib.sha256()
    for message in messages:
        raw = message.text.encode("utf-8")
        digest.update(len(raw).to_bytes(4, "little"))
        digest.update(raw)
    return digest.hexdigest()


def classify_texts(messages: Sequence[Any]) -> str:
    if not messages:
        return "no_records"
    texts = [message.text for message in messages]
    if all(text == PLACEHOLDER_TEXT for text in texts):
        return "all_exact_dash_placeholders"
    if all(text == "" for text in texts):
        return "all_empty_placeholders"
    if all(text.strip() in {"", PLACEHOLDER_TEXT} for text in texts):
        return "all_empty_or_dash_placeholders"
    if any(text == PLACEHOLDER_TEXT for text in texts):
        return "mixed_with_dash_placeholders"
    return "substantive_text_payload"


def summarize_ebm(ebm: Any, diagnostics: Mapping[str, Any], row: Mapping[str, Any]) -> dict[str, object]:
    messages = list(ebm.messages)
    texts = [message.text for message in messages]
    encoded_lengths = [len(text.encode("utf-8")) for text in texts]
    return {
        "present": True,
        "parse_status": "parsed",
        "size": parse_int(row.get("size"), len(ebm.raw)),
        "sha256": str(row.get("sha256", "")),
        "signed_count": ebm.signed_count,
        "record_count": len(messages),
        "d1_len": ebm.d1_len,
        "d2_len": ebm.d2_len,
        "extra_data_bytes": len(ebm.extra_data),
        "text_classification": classify_texts(messages),
        "text_utf8_bytes": sum(encoded_lengths),
        "text_characters": sum(len(text) for text in texts),
        "dash_record_count": sum(text == PLACEHOLDER_TEXT for text in texts),
        "empty_record_count": sum(text == "" for text in texts),
        "substantive_record_count": sum(text.strip() not in {"", PLACEHOLDER_TEXT} for text in texts),
        "distinct_text_count": len(set(texts)),
        "text_sequence_sha256": text_sequence_sha(messages),
        "metadata_sequence_sha256": metadata_sequence_sha(messages),
        "layout_candidate_count": diagnostics.get("candidate_count", ""),
        "layout_disambiguated": diagnostics.get("layout_disambiguated", False),
        "messages": messages,
    }


def parse_inventory_ebm(
    *, br: Any, text_tool: Any, workspace_root: Path, side: str,
    indexed: Mapping[str, Mapping[str, Any]], normalized_path: str,
) -> tuple[dict[str, object], list[dict[str, object]]]:
    row = indexed.get(normalized_path)
    if not row:
        return {
            "present": False, "parse_status": "missing", "size": 0, "sha256": "",
            "record_count": 0, "text_classification": "missing", "messages": [],
        }, []
    payload_path = workspace_path(br, workspace_root, side, row)
    if not payload_path.is_file():
        return {
            "present": True, "parse_status": "workspace_file_missing", "size": parse_int(row.get("size")),
            "sha256": str(row.get("sha256", "")), "record_count": 0,
            "text_classification": "unparsed", "messages": [],
        }, [{"side": side, "normalized_path": normalized_path, "reason": "workspace_file_missing"}]
    try:
        ebm, diagnostics = text_tool._parse_ebm_with_diagnostics(payload_path)
    except Exception as exc:
        return {
            "present": True, "parse_status": "parse_error", "size": parse_int(row.get("size")),
            "sha256": str(row.get("sha256", "")), "record_count": 0,
            "text_classification": "unparsed", "messages": [],
        }, [{"side": side, "normalized_path": normalized_path, "reason": "ebm_parse_error", "detail": type(exc).__name__}]
    rebuilt = text_tool.serialize_ebm(ebm)
    if rebuilt != ebm.raw:
        raise PlaceholderAuditError(f"EBM byte-exact round-trip failed: {payload_path}")
    return summarize_ebm(ebm, diagnostics, row), []


def record_rows_for_pair(
    *, event_id: str, language: str, source: Mapping[str, object], target: Mapping[str, object],
) -> list[dict[str, object]]:
    source_messages = list(source.get("messages", []))
    target_messages = list(target.get("messages", []))
    count = max(len(source_messages), len(target_messages))
    rows: list[dict[str, object]] = []
    for index in range(count):
        source_message = source_messages[index] if index < len(source_messages) else None
        target_message = target_messages[index] if index < len(target_messages) else None
        source_text = source_message.text if source_message is not None else ""
        target_text = target_message.text if target_message is not None else ""
        source_metadata = metadata_tuple(source_message) if source_message is not None else None
        target_metadata = metadata_tuple(target_message) if target_message is not None else None
        rows.append({
            "event_id": event_id,
            "language": language,
            "record_index": index,
            "source_present": source_message is not None,
            "target_present": target_message is not None,
            "source_msg_id": source_message.msg_id if source_message is not None else "",
            "target_msg_id": target_message.msg_id if target_message is not None else "",
            "msg_id_equal": source_message is not None and target_message is not None and source_message.msg_id == target_message.msg_id,
            "metadata_equal_excluding_text": source_metadata is not None and source_metadata == target_metadata,
            "source_text_utf8_bytes": len(source_text.encode("utf-8")) if source_message is not None else "",
            "target_text_utf8_bytes": len(target_text.encode("utf-8")) if target_message is not None else "",
            "source_text_characters": len(source_text) if source_message is not None else "",
            "target_text_characters": len(target_text) if target_message is not None else "",
            "source_text_sha256": sha256_text(source_text) if source_message is not None else "",
            "target_text_sha256": sha256_text(target_text) if target_message is not None else "",
            "target_exact_dash_placeholder": target_message is not None and target_text == PLACEHOLDER_TEXT,
            "target_empty_placeholder": target_message is not None and target_text == "",
            "text_equal": source_message is not None and target_message is not None and source_text == target_text,
            "classification": (
                "target_exact_dash_placeholder" if target_message is not None and target_text == PLACEHOLDER_TEXT
                else "target_empty_placeholder" if target_message is not None and target_text == ""
                else "text_identical" if source_message is not None and target_message is not None and source_text == target_text
                else "text_changed" if source_message is not None and target_message is not None
                else "record_missing_on_one_side"
            ),
        })
    return rows


def event_classification(
    *, jp_source: Mapping[str, object], jp_target: Mapping[str, object],
    en_source: Mapping[str, object], en_target: Mapping[str, object],
    target_languages: Sequence[Mapping[str, object]], ebd_hash_equal: bool,
) -> tuple[str, str]:
    target_present = [row for row in target_languages if row.get("present")]
    all_target_dash = bool(target_present) and all(row.get("text_classification") == "all_exact_dash_placeholders" for row in target_present)
    target_hashes = {str(row.get("sha256", "")) for row in target_present}
    all_target_copies_identical = len(target_hashes) == 1 and len(target_present) >= 2
    metadata_equal = (
        bool(jp_source.get("present")) and bool(jp_target.get("present"))
        and jp_source.get("metadata_sequence_sha256") == jp_target.get("metadata_sequence_sha256")
    )
    source_substantive = jp_source.get("text_classification") == "substantive_text_payload"
    if all_target_dash and all_target_copies_identical and source_substantive and metadata_equal:
        return (
            "scene_text_replaced_by_multilingual_dash_placeholders_control_identical" if ebd_hash_equal
            else "scene_text_replaced_by_multilingual_dash_placeholders_control_changed",
            "critical",
        )
    if jp_target.get("text_classification") == "all_exact_dash_placeholders" and source_substantive:
        return "japanese_scene_text_replaced_by_dash_placeholders", "critical"
    if en_target.get("text_classification") == "all_exact_dash_placeholders" and en_source.get("text_classification") == "substantive_text_payload":
        return "english_scene_text_replaced_by_dash_placeholders", "high"
    if jp_source.get("sha256") == jp_target.get("sha256") and en_source.get("sha256") == en_target.get("sha256"):
        return "message_payloads_identical", "low"
    if jp_source.get("sha256") == jp_target.get("sha256"):
        return "japanese_payload_identical_other_language_or_metadata_changed", "medium"
    return "message_payload_changed_not_scene_wide_placeholder", "medium"


def collect(*, project_root: Path, workspace_root: Path, report_root: Path) -> tuple[Path, dict[str, Any]]:
    br, text_tool = load_tools(project_root)
    report_root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="br-fe01-placeholder-") as td:
        temporary = Path(td)
        inventory_root = locate_inventory_root(report_root, temporary / "inventory")
        stage55_root = locate_named_root(report_root, STAGE55_DIR_NAME, STAGE55_REPORT_NAME, temporary / "stage55")
        stage56_root = locate_named_root(report_root, STAGE56_DIR_NAME, STAGE56_REPORT_NAME, temporary / "stage56")
        source_inventory = load_json(inventory_root / "inventories/br1_events.source.json")
        target_inventory = load_json(inventory_root / "inventories/br1_events.target.json")
        stage55_summary = load_json(stage55_root / "SUMMARY.json")
        stage56_summary = load_json(stage56_root / "SUMMARY.json")
        slot_rows = read_tsv(stage55_root / "FRIEND_EVENT_SLOT_INVENTORY.tsv")

        if str(stage55_summary.get("tool_version")) != "0.0.63":
            raise PlaceholderAuditError("stage-55 report tool version is not 0.0.63")
        if str(stage56_summary.get("tool_version")) != "0.0.64":
            raise PlaceholderAuditError("stage-56 report tool version is not 0.0.64")
        if parse_int(stage55_summary.get("friend_event_slot_rows"), -1) != len(slot_rows) or not slot_rows:
            raise PlaceholderAuditError("stage-55 slot inventory count mismatch")

        source_index = index_inventory(source_inventory)
        target_index = index_inventory(target_inventory)
        stage55_by_event = {row["event_id"]: row for row in slot_rows}
        event_ids = sorted(stage55_by_event)
        language_rows: list[dict[str, object]] = []
        record_rows: list[dict[str, object]] = []
        event_rows: list[dict[str, object]] = []
        focused_rows: list[dict[str, object]] = []
        skipped_rows: list[dict[str, object]] = []

        for event_id in event_ids:
            parsed: dict[tuple[str, str], dict[str, object]] = {}
            for side, languages, indexed in (
                ("source", SOURCE_LANGUAGES, source_index),
                ("target", TARGET_LANGUAGES, target_index),
            ):
                for language in languages:
                    normalized = event_message_path(event_id, language)
                    summary, skips = parse_inventory_ebm(
                        br=br, text_tool=text_tool, workspace_root=workspace_root,
                        side=side, indexed=indexed, normalized_path=normalized,
                    )
                    parsed[(side, language)] = summary
                    skipped_rows.extend(skips)
                    language_rows.append({
                        "event_id": event_id, "side": side, "language": language,
                        "normalized_path": normalized, "present": summary.get("present", False),
                        "parse_status": summary.get("parse_status", ""), "size": summary.get("size", ""),
                        "sha256": summary.get("sha256", ""), "record_count": summary.get("record_count", ""),
                        "d1_len": summary.get("d1_len", ""), "d2_len": summary.get("d2_len", ""),
                        "extra_data_bytes": summary.get("extra_data_bytes", ""),
                        "text_classification": summary.get("text_classification", ""),
                        "text_utf8_bytes": summary.get("text_utf8_bytes", ""),
                        "text_characters": summary.get("text_characters", ""),
                        "dash_record_count": summary.get("dash_record_count", ""),
                        "empty_record_count": summary.get("empty_record_count", ""),
                        "substantive_record_count": summary.get("substantive_record_count", ""),
                        "distinct_text_count": summary.get("distinct_text_count", ""),
                        "text_sequence_sha256": summary.get("text_sequence_sha256", ""),
                        "metadata_sequence_sha256": summary.get("metadata_sequence_sha256", ""),
                        "layout_candidate_count": summary.get("layout_candidate_count", ""),
                        "layout_disambiguated": summary.get("layout_disambiguated", ""),
                    })

            for language in ("event_jp", "event_en"):
                record_rows.extend(record_rows_for_pair(
                    event_id=event_id, language=language,
                    source=parsed[("source", language)], target=parsed[("target", language)],
                ))

            jp_source = parsed[("source", "event_jp")]
            jp_target = parsed[("target", "event_jp")]
            en_source = parsed[("source", "event_en")]
            en_target = parsed[("target", "event_en")]
            target_copies = [parsed[("target", language)] for language in TARGET_LANGUAGES]
            stage55_row = stage55_by_event[event_id]
            classification, priority = event_classification(
                jp_source=jp_source, jp_target=jp_target, en_source=en_source, en_target=en_target,
                target_languages=target_copies, ebd_hash_equal=parse_bool(stage55_row.get("ebd_hash_equal")),
            )
            target_hashes = {str(row.get("sha256", "")) for row in target_copies if row.get("present")}
            all_target_dash = all(
                row.get("present") and row.get("text_classification") == "all_exact_dash_placeholders"
                for row in target_copies
            )
            metadata_equal = jp_source.get("metadata_sequence_sha256") == jp_target.get("metadata_sequence_sha256") and bool(jp_source.get("present"))
            row = {
                "event_id": event_id,
                "family": event_id.split("_", 1)[0],
                "user_listed": event_id in FOCUS_EVENT_IDS,
                "source_jp_records": jp_source.get("record_count", ""),
                "target_jp_records": jp_target.get("record_count", ""),
                "source_jp_text_utf8_bytes": jp_source.get("text_utf8_bytes", ""),
                "target_jp_text_utf8_bytes": jp_target.get("text_utf8_bytes", ""),
                "target_jp_dash_records": jp_target.get("dash_record_count", ""),
                "source_en_records": en_source.get("record_count", ""),
                "target_en_records": en_target.get("record_count", ""),
                "source_en_text_utf8_bytes": en_source.get("text_utf8_bytes", ""),
                "target_en_text_utf8_bytes": en_target.get("text_utf8_bytes", ""),
                "target_en_dash_records": en_target.get("dash_record_count", ""),
                "target_available_language_copies": sum(bool(item.get("present")) for item in target_copies),
                "target_language_payload_hashes_identical": len(target_hashes) == 1 and len(target_hashes) > 0,
                "all_target_languages_exact_dash_placeholders": all_target_dash,
                "jp_metadata_equal_excluding_text": metadata_equal,
                "jp_msg_id_sequence_equal": (
                    [m.msg_id for m in jp_source.get("messages", [])] == [m.msg_id for m in jp_target.get("messages", [])]
                    and bool(jp_source.get("present")) and bool(jp_target.get("present"))
                ),
                "ebd_hash_equal": parse_bool(stage55_row.get("ebd_hash_equal")),
                "event_data_classification": stage55_row.get("event_data_classification", ""),
                "classification": classification,
                "review_priority": priority,
                "safe_for_later_message_payload_prototype": (
                    classification == "scene_text_replaced_by_multilingual_dash_placeholders_control_identical"
                    and metadata_equal
                ),
                "reachability_status": "unresolved_stage56_framing_unavailable",
                "review_status": "record_payload_audited_no_runtime_claim",
            }
            event_rows.append(row)
            if event_id in FOCUS_EVENT_IDS or "placeholder" in classification:
                focused_rows.append(row)

        placeholder_rows = [row for row in event_rows if "placeholder" in str(row["classification"])]
        critical_rows = [row for row in placeholder_rows if str(row["review_priority"]) == "critical"]
        focus_map = {row["event_id"]: row for row in focused_rows}
        for event_id in FOCUS_EVENT_IDS:
            if event_id not in focus_map:
                raise PlaceholderAuditError(f"focused event missing from audit: {event_id}")

        evidence_dir = report_root / EVIDENCE_DIR_NAME
        if evidence_dir.exists():
            import shutil
            shutil.rmtree(evidence_dir)
        evidence_dir.mkdir(parents=True)

        write_tsv(evidence_dir / "FE_EVENT_MESSAGE_PAYLOAD_AUDIT.tsv", [
            "event_id", "family", "user_listed", "source_jp_records", "target_jp_records",
            "source_jp_text_utf8_bytes", "target_jp_text_utf8_bytes", "target_jp_dash_records",
            "source_en_records", "target_en_records", "source_en_text_utf8_bytes",
            "target_en_text_utf8_bytes", "target_en_dash_records", "target_available_language_copies",
            "target_language_payload_hashes_identical", "all_target_languages_exact_dash_placeholders",
            "jp_metadata_equal_excluding_text", "jp_msg_id_sequence_equal", "ebd_hash_equal",
            "event_data_classification", "classification", "review_priority",
            "safe_for_later_message_payload_prototype", "reachability_status", "review_status",
        ], event_rows)
        write_tsv(evidence_dir / "FE_EVENT_LANGUAGE_COPY_AUDIT.tsv", [
            "event_id", "side", "language", "normalized_path", "present", "parse_status", "size", "sha256",
            "record_count", "d1_len", "d2_len", "extra_data_bytes", "text_classification",
            "text_utf8_bytes", "text_characters", "dash_record_count", "empty_record_count",
            "substantive_record_count", "distinct_text_count", "text_sequence_sha256",
            "metadata_sequence_sha256", "layout_candidate_count", "layout_disambiguated",
        ], language_rows)
        write_tsv(evidence_dir / "FE_EVENT_MESSAGE_RECORD_AUDIT.tsv", [
            "event_id", "language", "record_index", "source_present", "target_present",
            "source_msg_id", "target_msg_id", "msg_id_equal", "metadata_equal_excluding_text",
            "source_text_utf8_bytes", "target_text_utf8_bytes", "source_text_characters",
            "target_text_characters", "source_text_sha256", "target_text_sha256",
            "target_exact_dash_placeholder", "target_empty_placeholder", "text_equal", "classification",
        ], record_rows)
        write_tsv(evidence_dir / "FE_EVENT_PLACEHOLDER_SCENE_CANDIDATES.tsv", list(event_rows[0].keys()), placeholder_rows)
        write_tsv(evidence_dir / "FOCUSED_FE01_MESSAGE_REVIEW.tsv", list(event_rows[0].keys()), focused_rows)
        write_tsv(evidence_dir / "FE_EVENT_MESSAGE_AUDIT_SKIPPED.tsv", ["side", "normalized_path", "reason", "detail"], skipped_rows)

        stage56_status = str(stage56_summary.get("status", ""))
        summary = {
            "type": "br_quartet_restoration_fe01_message_placeholder_evidence_summary",
            "format_version": 1,
            "tool_version": TOOL_VERSION,
            "source_stage55_tool_version": str(stage55_summary.get("tool_version", "")),
            "source_stage56_tool_version": str(stage56_summary.get("tool_version", "")),
            "status": "scene_wide_multilingual_dash_placeholders_detected_message_restoration_candidates",
            "stage56_status": stage56_status,
            "stage56_framing_status": str(stage56_summary.get("framing_status", "")),
            "stage56_mapping_status": str(stage56_summary.get("mapping_status", "")),
            "friend_event_rows": len(event_rows),
            "language_copy_rows": len(language_rows),
            "record_audit_rows": len(record_rows),
            "placeholder_scene_rows": len(placeholder_rows),
            "critical_placeholder_scene_rows": len(critical_rows),
            "safe_later_message_payload_prototype_rows": sum(parse_bool(row["safe_for_later_message_payload_prototype"]) for row in event_rows),
            "user_listed_event_rows": len(FOCUS_EVENT_IDS),
            "user_listed_placeholder_rows": sum("placeholder" in str(focus_map[event_id]["classification"]) for event_id in FOCUS_EVENT_IDS),
            "user_listed_safe_prototype_rows": sum(parse_bool(focus_map[event_id]["safe_for_later_message_payload_prototype"]) for event_id in FOCUS_EVENT_IDS),
            "user_listed_classifications": {event_id: focus_map[event_id]["classification"] for event_id in FOCUS_EVENT_IDS},
            "skipped_rows": len(skipped_rows),
            "policy": {
                "placeholder_literal_exported": PLACEHOLDER_TEXT,
                "dialogue_text_exported": False,
                "translation_json_modified": False,
                "br_text_tool_modified": False,
                "ebm_written": False,
                "ebd_written": False,
                "pak_repacked": False,
                "core_registry_modified": False,
                "profile_activated": False,
                "installed_game_modified": False,
                "file_presence_treated_as_content_preservation": False,
                "placeholder_detection_treated_as_reachability_proof": False,
            },
            "next_action": "Build separate local message-payload restoration prototypes only for metadata-identical scene-wide dash placeholders with unchanged EBD; keep trigger reachability unresolved.",
        }
        (evidence_dir / "SUMMARY.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        output = report_root / REPORT_NAME
        make_report_archive(evidence_dir, output)
        return output, summary


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--project-root", required=True)
    p.add_argument("--workspace-root")
    p.add_argument("--report-root")
    return p


def main(argv: Sequence[str] | None = None) -> int:
    args = parser().parse_args(argv)
    project_root = Path(args.project_root).expanduser().resolve()
    if not project_root.is_dir():
        raise PlaceholderAuditError(f"project root does not exist: {project_root}")
    workspace_root = Path(args.workspace_root).expanduser().resolve() if args.workspace_root else project_root / ".local/build/quartet_restoration"
    report_root = Path(args.report_root).expanduser().resolve() if args.report_root else project_root / ".local/reports/quartet_restoration"
    output, summary = collect(project_root=project_root, workspace_root=workspace_root, report_root=report_root)
    print(f"FE events audited: {summary['friend_event_rows']}")
    print(f"Scene-wide placeholder candidates: {summary['placeholder_scene_rows']}")
    print(f"Safe later message prototypes: {summary['safe_later_message_payload_prototype_rows']}")
    print(f"User-listed placeholder rows: {summary['user_listed_placeholder_rows']}/{summary['user_listed_event_rows']}")
    print(f"Report: {output}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except PlaceholderAuditError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(2)
