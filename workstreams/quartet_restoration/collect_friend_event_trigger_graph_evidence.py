#!/usr/bin/env python3
"""Infer conservative record framing and index-edge evidence for eventprocessdataall.epd.

Stage 56 follows the stage-55 finding that all 420 FE message/control slots are
physically present in Original and Quartet.  It therefore investigates the
remaining reachability question without assuming that archive presence means a
scene is playable.  The collector tests exact record-framing hypotheses for the
1758-entry global event-process table, evaluates deterministic event-order
hypotheses against record metadata, and exports only record/index metadata and
opaque candidate edges.  It never writes EBM, EBD, EPD, PAK, registry state or
the installed game.
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
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Iterable, Mapping, Sequence

WORKSTREAM_ID = "quartet_restoration"
TOOL_VERSION = "0.0.64"
REPORT_NAME = "BR_quartet_restoration_friend_event_trigger_graph_evidence.tar.zst"
EVIDENCE_DIR_NAME = "friend_event_trigger_graph_evidence"
STAGE55_REPORT_NAME = "BR_quartet_restoration_friend_event_reachability_evidence.tar.zst"
STAGE55_DIR_NAME = "friend_event_reachability_evidence"
PROCESS_PATH = "event/eventprocess/eventprocessdataall.epd"
FOCUS_EVENT_IDS = {
    "fe13_090",
    "fe01_130", "fe01_200", "fe01_220", "fe01_230", "fe01_240",
    "fe01_250", "fe01_260", "fe01_270", "fe01_290",
}
MAX_RECORD_FIELD_OFFSET = 64


class TriggerGraphError(RuntimeError):
    pass


@dataclass(frozen=True)
class RecordSpan:
    index: int
    start: int
    end: int

    @property
    def size(self) -> int:
        return self.end - self.start


@dataclass
class FramingResult:
    side: str
    layout_type: str
    schema_key: str
    parameter_text: str
    records: list[RecordSpan]
    header_bytes: int
    trailer_bytes: int
    empty_records: int
    exact_eof: bool
    score: float
    classification: str


def parse_int(value: object, default: int = 0) -> int:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return default


def parse_bool(value: object) -> bool:
    return str(value).strip().casefold() in {"1", "true", "yes", "y"}


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def safe_member_name(raw: str) -> str:
    path = PurePosixPath(raw)
    if path.is_absolute() or not path.parts or ".." in path.parts:
        raise TriggerGraphError(f"unsafe report archive member: {raw}")
    return path.as_posix()


def load_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise TriggerGraphError(f"missing prerequisite JSON: {path}")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise TriggerGraphError(f"invalid JSON {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise TriggerGraphError(f"expected JSON object: {path}")
    return data


def read_tsv(path: Path, *, required: bool = True) -> list[dict[str, str]]:
    if not path.is_file():
        if required:
            raise TriggerGraphError(f"missing prerequisite table: {path}")
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
        raise TriggerGraphError(f"missing prerequisite report archive: {archive}")
    listed = subprocess.run(
        ["tar", "--zstd", "-tf", str(archive)], text=True,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    if listed.returncode:
        raise TriggerGraphError(f"cannot list {archive}: {listed.stderr.strip()}")
    roots = {
        PurePosixPath(safe_member_name(line.strip())).parts[0]
        for line in listed.stdout.splitlines() if line.strip()
    }
    if len(roots) != 1:
        raise TriggerGraphError(f"expected one report root in {archive}, found {sorted(roots)}")
    destination.mkdir(parents=True, exist_ok=True)
    done = subprocess.run(
        ["tar", "--zstd", "-xf", str(archive), "-C", str(destination)],
        text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    if done.returncode:
        raise TriggerGraphError(f"cannot extract {archive}: {done.stderr.strip()}")
    return destination / next(iter(roots))


def locate_stage55_root(report_root: Path, temporary: Path) -> Path:
    direct = report_root / STAGE55_DIR_NAME
    return direct if direct.is_dir() else extract_archive(report_root / STAGE55_REPORT_NAME, temporary / "stage55")


def make_report_archive(source_dir: Path, output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(output.name + ".tmp")
    temporary.unlink(missing_ok=True)
    done = subprocess.run(
        ["tar", "--zstd", "-cf", str(temporary), "-C", str(source_dir.parent), source_dir.name],
        text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    if done.returncode:
        raise TriggerGraphError(f"cannot create report archive: {done.stderr.strip()}")
    os.replace(temporary, output)


def load_restoration_tool(project_root: Path) -> Any:
    tool_root = project_root / "Blue_Reflection_Text_Tool"
    if not (tool_root / "br_restoration_tool.py").is_file():
        raise TriggerGraphError("missing br_restoration_tool.py")
    sys.path.insert(0, str(tool_root))
    try:
        return importlib.import_module("br_restoration_tool")
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


def event_id_from_path(path: str) -> str:
    stem = PurePosixPath(path).stem
    if stem.startswith("event_message_"):
        return stem[len("event_message_"):]
    if stem.startswith("event_"):
        return stem[len("event_"):]
    return stem


def is_jp_message_path(path: str) -> bool:
    folded = normalize_path(path).casefold()
    return "/event_jp/" in folded and PurePosixPath(folded).name.startswith("event_message_") and folded.endswith(".ebm")


def natural_event_key(event_id: str) -> tuple[object, ...]:
    match = re.fullmatch(r"([a-z]+)(\d*)_(\d+)", event_id.casefold())
    if not match:
        return (event_id.casefold(), 0, 0)
    prefix, family, slot = match.groups()
    return (prefix, int(family or 0), int(slot))


def first_u32(path: Path) -> int | None:
    try:
        raw = path.read_bytes()[:4]
    except OSError:
        return None
    return struct.unpack("<I", raw)[0] if len(raw) == 4 else None


def inventory_workspace_path(br: Any, workspace_root: Path, side: str, row: Mapping[str, Any]) -> Path:
    return br.inventory_workspace_file(
        workspace_root, side, "br1_events", str(row.get("archive", "")), str(row.get("path", ""))
    )


def index_inventory(inventory: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    return {normalize_path(row.get("normalized_path")): dict(row) for row in inventory.get("files", [])}


def process_inventory_row(inventory: Mapping[str, Any]) -> dict[str, Any] | None:
    for row in inventory.get("files", []):
        if normalize_path(row.get("normalized_path")) == PROCESS_PATH:
            return dict(row)
    return None


def message_rows_in_inventory(inventory: Mapping[str, Any]) -> list[dict[str, Any]]:
    return [dict(row) for row in inventory.get("files", []) if is_jp_message_path(str(row.get("normalized_path", "")))]


def ebd_path_for_message(path: str) -> str:
    p = PurePosixPath(normalize_path(path))
    name = p.name
    if not name.startswith("event_message_"):
        return ""
    return (p.parent / ("event_" + name[len("event_message_"):])).as_posix().replace(".ebm", ".ebd")


def build_event_metadata(
    *, br: Any, workspace_root: Path, side: str, inventory: Mapping[str, Any]
) -> tuple[dict[str, dict[str, object]], list[str], list[dict[str, object]]]:
    indexed = index_inventory(inventory)
    metadata: dict[str, dict[str, object]] = {}
    order: list[str] = []
    skipped: list[dict[str, object]] = []
    for row in message_rows_in_inventory(inventory):
        path = normalize_path(row.get("normalized_path"))
        event_id = event_id_from_path(path)
        if event_id in metadata:
            skipped.append({"side": side, "normalized_path": path, "reason": "duplicate_event_id"})
            continue
        ebd_path = ebd_path_for_message(path)
        ebd_row = indexed.get(ebd_path)
        message_file = inventory_workspace_path(br, workspace_root, side, row)
        ebd_file = inventory_workspace_path(br, workspace_root, side, ebd_row) if ebd_row else None
        metadata[event_id] = {
            "event_id": event_id,
            "message_path": path,
            "ebd_path": ebd_path,
            "ebm_declared_records": first_u32(message_file) if message_file.is_file() else None,
            "ebd_declared_items": first_u32(ebd_file) if ebd_file and ebd_file.is_file() else None,
            "ebm_size": parse_int(row.get("size"), 0),
            "ebd_size": parse_int(ebd_row.get("size"), 0) if ebd_row else None,
        }
        order.append(event_id)
    return metadata, order, skipped


def unpack_uint(payload: bytes, offset: int, width: int) -> int | None:
    if offset < 0 or offset + width > len(payload):
        return None
    if width == 1:
        return payload[offset]
    if width == 2:
        return struct.unpack_from("<H", payload, offset)[0]
    if width == 4:
        return struct.unpack_from("<I", payload, offset)[0]
    raise ValueError(width)


def score_framing(*, count: int, records: Sequence[RecordSpan], trailer: int, exact_eof: bool) -> float:
    if len(records) != count:
        return -1.0
    empty = sum(record.size <= 0 for record in records)
    nonempty_ratio = 1.0 - (empty / max(1, count))
    trailer_score = max(0.0, 1.0 - trailer / 64.0)
    return round(nonempty_ratio * 60.0 + trailer_score * 20.0 + (20.0 if exact_eof else 0.0), 6)


def make_framing(
    *, side: str, layout_type: str, schema_key: str, parameter_text: str,
    records: list[RecordSpan], header_bytes: int, payload_size: int,
) -> FramingResult:
    trailer = payload_size - (records[-1].end if records else header_bytes)
    exact = trailer == 0
    empty = sum(record.size <= 0 for record in records)
    score = score_framing(count=len(records), records=records, trailer=trailer, exact_eof=exact)
    classification = "exact_record_framing_candidate" if exact and empty == 0 else "partial_record_framing_candidate"
    return FramingResult(
        side=side, layout_type=layout_type, schema_key=schema_key, parameter_text=parameter_text,
        records=records, header_bytes=header_bytes, trailer_bytes=trailer,
        empty_records=empty, exact_eof=exact, score=score, classification=classification,
    )


def offset_table_hypotheses(payload: bytes, count: int, side: str) -> list[FramingResult]:
    results: list[FramingResult] = []
    for table_start in range(4, min(68, len(payload)), 4):
        for entry_count in (count, count + 1):
            table_end = table_start + entry_count * 4
            if table_end > len(payload):
                continue
            raw = [struct.unpack_from("<I", payload, table_start + i * 4)[0] for i in range(entry_count)]
            for base_name, base in (("absolute", 0), ("relative_table_end", table_end), ("relative_table_start", table_start)):
                boundaries = [value + base for value in raw]
                if entry_count == count:
                    boundaries.append(len(payload))
                if len(boundaries) != count + 1:
                    continue
                if boundaries[0] < table_end or boundaries[-1] > len(payload):
                    continue
                if any(a > b for a, b in zip(boundaries, boundaries[1:])):
                    continue
                records = [RecordSpan(i, boundaries[i], boundaries[i + 1]) for i in range(count)]
                result = make_framing(
                    side=side, layout_type="offset_table_u32", schema_key=f"offset_table_u32:{table_start}:{entry_count}:{base_name}",
                    parameter_text=f"table_start={table_start};entry_count={entry_count};base={base_name}",
                    records=records, header_bytes=boundaries[0], payload_size=len(payload),
                )
                if result.empty_records <= max(1, count // 100):
                    results.append(result)
    return results


def offset_size_table_hypotheses(payload: bytes, count: int, side: str) -> list[FramingResult]:
    results: list[FramingResult] = []
    for table_start in range(4, min(68, len(payload)), 4):
        for entry_stride in (8, 12, 16):
            table_end = table_start + count * entry_stride
            if table_end > len(payload):
                continue
            for base_name, base in (("absolute", 0), ("relative_table_end", table_end), ("relative_table_start", table_start)):
                spans: list[RecordSpan] = []
                valid = True
                previous_end = table_end
                for index in range(count):
                    offset = struct.unpack_from("<I", payload, table_start + index * entry_stride)[0] + base
                    size = struct.unpack_from("<I", payload, table_start + index * entry_stride + 4)[0]
                    end = offset + size
                    if offset < table_end or end > len(payload) or offset < previous_end:
                        valid = False
                        break
                    spans.append(RecordSpan(index, offset, end))
                    previous_end = end
                if not valid:
                    continue
                result = make_framing(
                    side=side, layout_type="offset_size_table_u32", schema_key=f"offset_size_table_u32:{table_start}:{entry_stride}:{base_name}",
                    parameter_text=f"table_start={table_start};entry_stride={entry_stride};base={base_name}",
                    records=spans, header_bytes=spans[0].start if spans else table_end, payload_size=len(payload),
                )
                if result.empty_records <= max(1, count // 100):
                    results.append(result)
    return results


def align_up(value: int, alignment: int) -> int:
    return value if alignment <= 1 else (value + alignment - 1) // alignment * alignment


def length_prefixed_hypotheses(payload: bytes, count: int, side: str) -> list[FramingResult]:
    results: list[FramingResult] = []
    for start in range(4, min(129, len(payload))):
        for width in (1, 2, 4):
            for extra in (0, 2, 4, 8):
                for semantic in ("payload", "total"):
                    for alignment in (1, 2, 4, 8):
                        position = start
                        records: list[RecordSpan] = []
                        valid = True
                        for index in range(count):
                            length = unpack_uint(payload, position, width)
                            if length is None:
                                valid = False
                                break
                            if semantic == "payload":
                                record_start = position
                                end = position + width + extra + length
                            else:
                                record_start = position
                                end = position + length
                            if end <= position or end > len(payload):
                                valid = False
                                break
                            aligned_end = align_up(end, alignment)
                            if aligned_end > len(payload):
                                valid = False
                                break
                            records.append(RecordSpan(index, record_start, end))
                            position = aligned_end
                        if not valid:
                            continue
                        trailer = len(payload) - position
                        if trailer < 0 or trailer > 32:
                            continue
                        schema = f"length_prefix:{start}:{width}:{extra}:{semantic}:{alignment}"
                        result = make_framing(
                            side=side, layout_type="length_prefixed", schema_key=schema,
                            parameter_text=f"start={start};width={width};extra={extra};semantic={semantic};alignment={alignment}",
                            records=records, header_bytes=start, payload_size=position,
                        )
                        # make_framing saw payload_size=position, so preserve the real trailer.
                        result.trailer_bytes = trailer
                        result.exact_eof = trailer == 0
                        result.score = score_framing(count=count, records=records, trailer=trailer, exact_eof=trailer == 0)
                        result.classification = "exact_record_framing_candidate" if trailer == 0 and result.empty_records == 0 else "partial_record_framing_candidate"
                        results.append(result)
    return results


def fixed_stride_hypotheses(payload: bytes, count: int, side: str) -> list[FramingResult]:
    results: list[FramingResult] = []
    for start in range(4, min(257, len(payload)), 4):
        remaining = len(payload) - start
        for trailer in range(0, min(65, remaining + 1)):
            body = remaining - trailer
            if body <= 0 or body % count:
                continue
            stride = body // count
            if stride < 4 or stride > 256:
                continue
            records = [RecordSpan(i, start + i * stride, start + (i + 1) * stride) for i in range(count)]
            result = make_framing(
                side=side, layout_type="fixed_stride", schema_key=f"fixed_stride:{start}:{stride}",
                parameter_text=f"start={start};stride={stride}", records=records,
                header_bytes=start, payload_size=len(payload) - trailer,
            )
            result.trailer_bytes = trailer
            result.exact_eof = trailer == 0
            result.score = score_framing(count=count, records=records, trailer=trailer, exact_eof=trailer == 0)
            result.classification = "exact_record_framing_candidate" if trailer == 0 else "partial_record_framing_candidate"
            results.append(result)
    return results


def collect_framing_hypotheses(payload: bytes, count: int, side: str) -> list[FramingResult]:
    candidates = (
        offset_table_hypotheses(payload, count, side)
        + offset_size_table_hypotheses(payload, count, side)
        + length_prefixed_hypotheses(payload, count, side)
        + fixed_stride_hypotheses(payload, count, side)
    )
    unique: dict[tuple[str, tuple[tuple[int, int], ...]], FramingResult] = {}
    for candidate in candidates:
        signature = (candidate.schema_key, tuple((r.start, r.end) for r in candidate.records[:16]))
        previous = unique.get(signature)
        if previous is None or candidate.score > previous.score:
            unique[signature] = candidate
    return sorted(unique.values(), key=lambda r: (-r.score, r.empty_records, r.trailer_bytes, r.schema_key))[:200]


def choose_common_framing(source: Sequence[FramingResult], target: Sequence[FramingResult]) -> tuple[FramingResult | None, FramingResult | None, str]:
    target_by_schema: defaultdict[str, list[FramingResult]] = defaultdict(list)
    for item in target:
        target_by_schema[item.schema_key].append(item)
    pairs: list[tuple[float, FramingResult, FramingResult]] = []
    for left in source:
        for right in target_by_schema.get(left.schema_key, []):
            if len(left.records) != len(right.records):
                continue
            score = min(left.score, right.score) + (10.0 if left.exact_eof and right.exact_eof else 0.0)
            pairs.append((score, left, right))
    if pairs:
        layout_priority = {
            "offset_table_u32": 4,
            "offset_size_table_u32": 4,
            "length_prefixed": 3,
            "fixed_stride": 1,
        }
        _, left, right = max(
            pairs,
            key=lambda item: (
                item[0],
                layout_priority.get(item[1].layout_type, 0),
                -item[1].trailer_bytes - item[2].trailer_bytes,
                -item[1].header_bytes - item[2].header_bytes,
            ),
        )
        status = "common_exact_framing_selected" if left.exact_eof and right.exact_eof and not left.empty_records and not right.empty_records else "common_partial_framing_selected"
        return left, right, status
    exact_source = [item for item in source if item.exact_eof and item.empty_records == 0]
    exact_target = [item for item in target if item.exact_eof and item.empty_records == 0]
    if exact_source and exact_target:
        return exact_source[0], exact_target[0], "side_specific_exact_framing_selected"
    return None, None, "event_process_framing_unresolved"


def record_bytes(payload: bytes, records: Sequence[RecordSpan]) -> list[bytes]:
    return [payload[item.start:item.end] for item in records]


def byte_distance(left: bytes, right: bytes) -> int:
    common = min(len(left), len(right))
    return sum(a != b for a, b in zip(left[:common], right[:common])) + abs(len(left) - len(right))


def build_order_hypotheses(source_order: Sequence[str], target_order: Sequence[str]) -> dict[str, list[str]]:
    source_unique = list(dict.fromkeys(source_order))
    target_unique = list(dict.fromkeys(target_order))
    shared = set(source_unique) & set(target_unique)
    source_shared = [item for item in source_unique if item in shared]
    target_shared = [item for item in target_unique if item in shared]
    lexical = sorted(shared, key=str.casefold)
    natural = sorted(shared, key=natural_event_key)
    return {
        "source_inventory_order": source_shared,
        "target_inventory_order": target_shared,
        "normalized_event_id_lexical": lexical,
        "natural_event_id_order": natural,
    }


def metric_value(meta: Mapping[str, object], metric: str) -> int | None:
    value = meta.get(metric)
    return value if isinstance(value, int) else None


def top_mapping_fields(
    *, records: Sequence[bytes], order: Sequence[str], metadata: Mapping[str, Mapping[str, object]], metric: str,
) -> list[dict[str, object]]:
    if len(records) != len(order) or not records:
        return []
    reverse_order = list(reversed(order))
    rows: list[dict[str, object]] = []
    for width in (1, 2, 4):
        for offset in range(0, MAX_RECORD_FIELD_OFFSET - width + 1):
            eligible = actual = reverse = 0
            for index, payload in enumerate(records):
                decoded = unpack_uint(payload, offset, width)
                if decoded is None:
                    continue
                expected = metric_value(metadata.get(order[index], {}), metric)
                reverse_expected = metric_value(metadata.get(reverse_order[index], {}), metric)
                if expected is None or reverse_expected is None:
                    continue
                eligible += 1
                actual += decoded == expected
                reverse += decoded == reverse_expected
            if eligible < max(4, len(records) // 10):
                continue
            support = actual / eligible
            reverse_support = reverse / eligible
            lift = support - reverse_support
            if support < 0.10:
                continue
            rows.append({
                "metric": metric, "width": width, "offset": offset, "eligible_rows": eligible,
                "match_rows": actual, "support_ratio": round(support, 6),
                "reverse_baseline_match_rows": reverse, "reverse_baseline_ratio": round(reverse_support, 6),
                "support_lift": round(lift, 6),
            })
    return sorted(rows, key=lambda row: (-float(row["support_ratio"]), -float(row["support_lift"]), int(row["width"]), int(row["offset"])))[:5]


def classify_mapping_support(rows: Sequence[Mapping[str, object]]) -> tuple[str, float]:
    strong = [row for row in rows if float(row["support_ratio"]) >= 0.65 and float(row["support_lift"]) >= 0.20]
    moderate = [row for row in rows if float(row["support_ratio"]) >= 0.45 and float(row["support_lift"]) >= 0.15]
    if len(strong) >= 2:
        return "strong_record_to_event_order_support", sum(float(row["support_ratio"]) + float(row["support_lift"]) for row in strong[:4])
    if strong or len(moderate) >= 2:
        return "moderate_record_to_event_order_support", sum(float(row["support_ratio"]) + float(row["support_lift"]) for row in (strong + moderate)[:4])
    return "record_to_event_order_unconfirmed", sum(max(0.0, float(row["support_lift"])) for row in rows[:4])


def detect_index_fields(records: Sequence[bytes], count: int, excluded: set[tuple[int, int]]) -> list[dict[str, object]]:
    candidates: list[dict[str, object]] = []
    for width in (2, 4):
        for offset in range(0, MAX_RECORD_FIELD_OFFSET - width + 1):
            if (width, offset) in excluded:
                continue
            for base_mode in ("zero_based", "one_based"):
                eligible = matches = 0
                values: set[int] = set()
                for payload in records:
                    value = unpack_uint(payload, offset, width)
                    if value is None:
                        continue
                    eligible += 1
                    index = value if base_mode == "zero_based" else value - 1
                    if 0 <= index < count:
                        matches += 1
                        values.add(index)
                if eligible < max(4, len(records) // 10):
                    continue
                support = matches / eligible
                if support < 0.15 or len(values) < min(8, max(2, count // 20)):
                    continue
                candidates.append({
                    "width": width, "offset": offset, "base_mode": base_mode,
                    "eligible_rows": eligible, "index_rows": matches,
                    "support_ratio": round(support, 6), "distinct_indices": len(values),
                })
    return sorted(candidates, key=lambda row: (-float(row["support_ratio"]), -int(row["distinct_indices"]), int(row["width"]), int(row["offset"])))[:12]


def decoded_index(payload: bytes, field: Mapping[str, object], count: int) -> int | None:
    value = unpack_uint(payload, int(field["offset"]), int(field["width"]))
    if value is None:
        return None
    index = value if field["base_mode"] == "zero_based" else value - 1
    return index if 0 <= index < count else None


def collect(*, project_root: Path, workspace_root: Path, report_root: Path) -> tuple[Path, dict[str, object]]:
    br = load_restoration_tool(project_root)
    with tempfile.TemporaryDirectory(prefix="br_fe_trigger_graph_") as temp_dir:
        temporary = Path(temp_dir)
        stage55_root = locate_stage55_root(report_root, temporary)
        stage55_summary = load_json(stage55_root / "SUMMARY.json")
        if stage55_summary.get("type") != "br_quartet_restoration_friend_event_reachability_evidence_summary":
            raise TriggerGraphError("stage-55 report type mismatch")
        if str(stage55_summary.get("tool_version")) != "0.0.63":
            raise TriggerGraphError(f"expected stage-55 tool version 0.0.63, found {stage55_summary.get('tool_version')}")
        if parse_int(stage55_summary.get("friend_event_slot_rows")) != 420:
            raise TriggerGraphError("stage-55 report does not contain 420 FE slots")
        if parse_int(stage55_summary.get("source_to_target_message_removed_or_stubbed_rows")) != 0:
            raise TriggerGraphError("stage-55 report contains removed/stubbed FE message payloads")
        if parse_int(stage55_summary.get("source_to_target_ebd_removed_rows")) != 0:
            raise TriggerGraphError("stage-55 report contains removed FE EBD payloads")

        source_inventory = load_json(report_root / "inventories/br1_events.source.json")
        target_inventory = load_json(report_root / "inventories/br1_events.target.json")
        source_meta, source_order, skipped_source = build_event_metadata(
            br=br, workspace_root=workspace_root, side="source", inventory=source_inventory,
        )
        target_meta, target_order, skipped_target = build_event_metadata(
            br=br, workspace_root=workspace_root, side="target", inventory=target_inventory,
        )
        skipped_rows: list[dict[str, object]] = skipped_source + skipped_target
        order_hypotheses = build_order_hypotheses(source_order, target_order)
        shared_event_ids = set(source_meta) & set(target_meta)

        source_process_row = process_inventory_row(source_inventory)
        target_process_row = process_inventory_row(target_inventory)
        if not source_process_row or not target_process_row:
            raise TriggerGraphError("eventprocessdataall.epd missing from source or target inventory")
        source_process_path = inventory_workspace_path(br, workspace_root, "source", source_process_row)
        target_process_path = inventory_workspace_path(br, workspace_root, "target", target_process_row)
        if not source_process_path.is_file() or not target_process_path.is_file():
            raise TriggerGraphError("eventprocessdataall.epd workspace payload missing")
        source_payload = source_process_path.read_bytes()
        target_payload = target_process_path.read_bytes()
        if len(source_payload) < 4 or len(target_payload) < 4:
            raise TriggerGraphError("eventprocessdataall.epd is too small")
        source_count = struct.unpack_from("<I", source_payload, 0)[0]
        target_count = struct.unpack_from("<I", target_payload, 0)[0]
        if source_count != target_count:
            raise TriggerGraphError(f"event-process count differs: {source_count} vs {target_count}")
        if source_count != len(shared_event_ids):
            raise TriggerGraphError(
                f"event-process count {source_count} does not match shared JP event-message count {len(shared_event_ids)}"
            )
        count = source_count

        source_hypotheses = collect_framing_hypotheses(source_payload, count, "source")
        target_hypotheses = collect_framing_hypotheses(target_payload, count, "target")
        selected_source, selected_target, framing_status = choose_common_framing(source_hypotheses, target_hypotheses)

        framing_rows: list[dict[str, object]] = []
        for hypothesis in source_hypotheses[:50] + target_hypotheses[:50]:
            framing_rows.append({
                "side": hypothesis.side, "layout_type": hypothesis.layout_type,
                "schema_key": hypothesis.schema_key, "parameters": hypothesis.parameter_text,
                "record_count": len(hypothesis.records), "header_bytes": hypothesis.header_bytes,
                "trailer_bytes": hypothesis.trailer_bytes, "empty_records": hypothesis.empty_records,
                "exact_eof": hypothesis.exact_eof, "score": hypothesis.score,
                "classification": hypothesis.classification,
                "selected": hypothesis is selected_source or hypothesis is selected_target,
            })

        order_rows: list[dict[str, object]] = []
        for order_id, order in order_hypotheses.items():
            order_rows.append({
                "order_id": order_id, "event_count": len(order),
                "order_sha256": sha256_text("\n".join(order)),
                "first_event_ids": ";".join(order[:8]), "last_event_ids": ";".join(order[-8:]),
                "fe13_090_index": order.index("fe13_090") if "fe13_090" in order else "",
                "matches_source_inventory_order": order == order_hypotheses["source_inventory_order"],
                "matches_target_inventory_order": order == order_hypotheses["target_inventory_order"],
                "classification": "deterministic_order_hypothesis_not_record_mapping_proof",
            })

        mapping_rows: list[dict[str, object]] = []
        selected_order_id = ""
        mapping_status = "record_to_event_order_unconfirmed"
        mapping_score = -1.0
        selected_order: list[str] = []
        source_record_payloads: list[bytes] = []
        target_record_payloads: list[bytes] = []
        excluded_fields: set[tuple[int, int]] = set()
        if selected_source and selected_target:
            source_record_payloads = record_bytes(source_payload, selected_source.records)
            target_record_payloads = record_bytes(target_payload, selected_target.records)
            for order_id, order in order_hypotheses.items():
                if len(order) != count:
                    continue
                support_for_order: list[dict[str, object]] = []
                for side, records, meta in (
                    ("source", source_record_payloads, source_meta),
                    ("target", target_record_payloads, target_meta),
                ):
                    for metric in ("ebm_declared_records", "ebd_declared_items", "ebm_size", "ebd_size"):
                        for rank, row in enumerate(top_mapping_fields(records=records, order=order, metadata=meta, metric=metric), 1):
                            exported = {
                                "order_id": order_id, "side": side, "metric": metric, "rank": rank,
                                **row, "classification": "opaque_record_field_mapping_support_not_semantic_proof",
                            }
                            mapping_rows.append(exported)
                            support_for_order.append(exported)
                status, score = classify_mapping_support(support_for_order)
                if score > mapping_score:
                    mapping_score = score
                    mapping_status = status
                    selected_order_id = order_id
                    selected_order = list(order)
            if mapping_status == "record_to_event_order_unconfirmed":
                selected_order_id = "normalized_event_id_lexical"
                selected_order = list(order_hypotheses[selected_order_id])
            for row in mapping_rows:
                if row["order_id"] == selected_order_id and float(row["support_ratio"]) >= 0.45:
                    excluded_fields.add((int(row["width"]), int(row["offset"])))

        record_rows: list[dict[str, object]] = []
        friend_record_rows: list[dict[str, object]] = []
        edge_field_rows: list[dict[str, object]] = []
        edge_rows: list[dict[str, object]] = []
        focused_rows: list[dict[str, object]] = []
        index_fields_source: list[dict[str, object]] = []
        index_fields_target: list[dict[str, object]] = []
        if selected_source and selected_target and selected_order:
            index_fields_source = detect_index_fields(source_record_payloads, count, excluded_fields)
            index_fields_target = detect_index_fields(target_record_payloads, count, excluded_fields)
            common_fields = {
                (int(row["width"]), int(row["offset"]), str(row["base_mode"])): row for row in index_fields_source
            }
            common_keys = set(common_fields) & {
                (int(row["width"]), int(row["offset"]), str(row["base_mode"])) for row in index_fields_target
            }
            for side, fields in (("source", index_fields_source), ("target", index_fields_target)):
                for row in fields:
                    key = (int(row["width"]), int(row["offset"]), str(row["base_mode"]))
                    edge_field_rows.append({
                        "side": side, **row, "present_on_both_sides": key in common_keys,
                        "classification": "opaque_index_field_candidate_not_confirmed_trigger_edge",
                    })
            incoming: defaultdict[str, dict[str, int]] = defaultdict(lambda: {"source": 0, "target": 0, "removed": 0, "added": 0, "retargeted": 0})
            outgoing: defaultdict[str, dict[str, int]] = defaultdict(lambda: {"source": 0, "target": 0, "changed": 0})
            for index in range(count):
                event_id = selected_order[index]
                source_record = source_record_payloads[index]
                target_record = target_record_payloads[index]
                changed = source_record != target_record
                base_row = {
                    "record_index": index, "event_id": event_id,
                    "source_start": selected_source.records[index].start,
                    "source_size": len(source_record), "source_sha256": sha256_bytes(source_record),
                    "target_start": selected_target.records[index].start,
                    "target_size": len(target_record), "target_sha256": sha256_bytes(target_record),
                    "record_changed": changed, "changed_bytes": byte_distance(source_record, target_record),
                    "order_id": selected_order_id, "mapping_status": mapping_status,
                    "classification": "opaque_event_process_record_metadata",
                }
                record_rows.append(base_row)
                if event_id.startswith("fe"):
                    friend_record_rows.append(dict(base_row))
                for key in sorted(common_keys):
                    field = common_fields[key]
                    source_target_index = decoded_index(source_record, field, count)
                    target_target_index = decoded_index(target_record, field, count)
                    source_destination = selected_order[source_target_index] if source_target_index is not None else ""
                    target_destination = selected_order[target_target_index] if target_target_index is not None else ""
                    if source_target_index is not None:
                        outgoing[event_id]["source"] += 1
                        incoming[source_destination]["source"] += 1
                    if target_target_index is not None:
                        outgoing[event_id]["target"] += 1
                        incoming[target_destination]["target"] += 1
                    if source_target_index == target_target_index:
                        continue
                    if source_target_index is not None and target_target_index is None:
                        edge_class = "candidate_index_edge_removed"
                        incoming[source_destination]["removed"] += 1
                    elif source_target_index is None and target_target_index is not None:
                        edge_class = "candidate_index_edge_added"
                        incoming[target_destination]["added"] += 1
                    else:
                        edge_class = "candidate_index_edge_retargeted"
                        incoming[source_destination]["retargeted"] += 1
                        incoming[target_destination]["retargeted"] += 1
                    outgoing[event_id]["changed"] += 1
                    if event_id.startswith("fe") or source_destination.startswith("fe") or target_destination.startswith("fe"):
                        edge_rows.append({
                            "source_record_index": index, "source_event_id": event_id,
                            "field_width": field["width"], "field_offset": field["offset"], "base_mode": field["base_mode"],
                            "source_destination_index": source_target_index if source_target_index is not None else "",
                            "source_destination_event_id": source_destination,
                            "target_destination_index": target_target_index if target_target_index is not None else "",
                            "target_destination_event_id": target_destination,
                            "classification": edge_class,
                            "mapping_status": mapping_status,
                            "review_status": "opaque_index_delta_not_trigger_semantics",
                        })
            for event_id in sorted(FOCUS_EVENT_IDS):
                if event_id not in selected_order:
                    continue
                index = selected_order.index(event_id)
                rec = record_rows[index]
                incoming_counts = incoming[event_id]
                outgoing_counts = outgoing[event_id]
                if mapping_status == "strong_record_to_event_order_support" and incoming_counts["removed"]:
                    classification = "possible_incoming_trigger_index_removed_requires_semantic_confirmation"
                    priority = "critical"
                elif rec["record_changed"]:
                    classification = "event_process_record_changed_reachability_effect_unresolved"
                    priority = "high"
                else:
                    classification = "event_process_record_identical_no_direct_reachability_change_found"
                    priority = "medium"
                focused_rows.append({
                    "event_id": event_id, "record_index": index,
                    "record_changed": rec["record_changed"], "record_changed_bytes": rec["changed_bytes"],
                    "source_record_size": rec["source_size"], "target_record_size": rec["target_size"],
                    "source_candidate_incoming_edges": incoming_counts["source"],
                    "target_candidate_incoming_edges": incoming_counts["target"],
                    "candidate_incoming_removed": incoming_counts["removed"],
                    "candidate_incoming_added": incoming_counts["added"],
                    "candidate_incoming_retargeted": incoming_counts["retargeted"],
                    "source_candidate_outgoing_edges": outgoing_counts["source"],
                    "target_candidate_outgoing_edges": outgoing_counts["target"],
                    "candidate_outgoing_changed": outgoing_counts["changed"],
                    "order_id": selected_order_id, "mapping_status": mapping_status,
                    "classification": classification, "review_priority": priority,
                    "review_status": "trigger_graph_metadata_requires_runtime_or_format_confirmation",
                })

        evidence_dir = report_root / EVIDENCE_DIR_NAME
        if evidence_dir.exists():
            import shutil
            shutil.rmtree(evidence_dir)
        evidence_dir.mkdir(parents=True, exist_ok=True)
        write_tsv(evidence_dir / "EVENT_PROCESS_ORDER_HYPOTHESES.tsv", [
            "order_id", "event_count", "order_sha256", "first_event_ids", "last_event_ids", "fe13_090_index",
            "matches_source_inventory_order", "matches_target_inventory_order", "classification",
        ], order_rows)
        write_tsv(evidence_dir / "EVENT_PROCESS_FRAMING_HYPOTHESES.tsv", [
            "side", "layout_type", "schema_key", "parameters", "record_count", "header_bytes", "trailer_bytes",
            "empty_records", "exact_eof", "score", "classification", "selected",
        ], framing_rows)
        write_tsv(evidence_dir / "EVENT_PROCESS_MAPPING_SUPPORT.tsv", [
            "order_id", "side", "metric", "rank", "width", "offset", "eligible_rows", "match_rows",
            "support_ratio", "reverse_baseline_match_rows", "reverse_baseline_ratio", "support_lift", "classification",
        ], mapping_rows)
        write_tsv(evidence_dir / "EVENT_PROCESS_RECORDS.tsv", [
            "record_index", "event_id", "source_start", "source_size", "source_sha256", "target_start", "target_size",
            "target_sha256", "record_changed", "changed_bytes", "order_id", "mapping_status", "classification",
        ], record_rows)
        write_tsv(evidence_dir / "FRIEND_EVENT_PROCESS_RECORDS.tsv", [
            "record_index", "event_id", "source_start", "source_size", "source_sha256", "target_start", "target_size",
            "target_sha256", "record_changed", "changed_bytes", "order_id", "mapping_status", "classification",
        ], friend_record_rows)
        write_tsv(evidence_dir / "EVENT_PROCESS_INDEX_FIELD_CANDIDATES.tsv", [
            "side", "width", "offset", "base_mode", "eligible_rows", "index_rows", "support_ratio", "distinct_indices",
            "present_on_both_sides", "classification",
        ], edge_field_rows)
        write_tsv(evidence_dir / "FRIEND_EVENT_TRIGGER_EDGE_CANDIDATES.tsv", [
            "source_record_index", "source_event_id", "field_width", "field_offset", "base_mode",
            "source_destination_index", "source_destination_event_id", "target_destination_index",
            "target_destination_event_id", "classification", "mapping_status", "review_status",
        ], edge_rows)
        write_tsv(evidence_dir / "FOCUSED_FRIEND_EVENT_TRIGGER_REVIEW.tsv", [
            "event_id", "record_index", "record_changed", "record_changed_bytes", "source_record_size", "target_record_size",
            "source_candidate_incoming_edges", "target_candidate_incoming_edges", "candidate_incoming_removed",
            "candidate_incoming_added", "candidate_incoming_retargeted", "source_candidate_outgoing_edges",
            "target_candidate_outgoing_edges", "candidate_outgoing_changed", "order_id", "mapping_status",
            "classification", "review_priority", "review_status",
        ], focused_rows)
        write_tsv(evidence_dir / "FRIEND_EVENT_TRIGGER_GRAPH_SKIPPED.tsv", ["side", "normalized_path", "reason"], skipped_rows)

        changed_records = sum(parse_bool(row["record_changed"]) for row in record_rows)
        changed_fe_records = sum(parse_bool(row["record_changed"]) for row in friend_record_rows)
        fe13_focus = next((row for row in focused_rows if row["event_id"] == "fe13_090"), None)
        if not selected_source or not selected_target:
            status = "event_process_framing_unresolved_no_trigger_graph_claim"
            next_action = "Use the framing hypotheses and local EPD payload to decode the record container before mapping any FE trigger state."
        elif mapping_status == "record_to_event_order_unconfirmed":
            status = "event_process_records_framed_event_order_mapping_unconfirmed"
            next_action = "Decode one stable record field or correlate it with known EBM/EBD metadata before treating record indices as event identities."
        elif fe13_focus and parse_int(fe13_focus.get("candidate_incoming_removed")) > 0:
            status = "fe13_090_candidate_trigger_index_asymmetry_found_semantics_unconfirmed"
            next_action = "Inspect the exact opaque index fields and compare adjacent FE records; do not patch the trigger table until field semantics are confirmed."
        else:
            status = "event_process_records_and_order_evidence_collected_no_confirmed_fe_scene_removal"
            next_action = "Continue trigger/availability table decoding or runtime observation; no file-level or confirmed index-edge removal currently justifies a trigger patch."
        summary = {
            "type": "br_quartet_restoration_friend_event_trigger_graph_evidence_summary",
            "format_version": 1,
            "tool_version": TOOL_VERSION,
            "source_stage55_tool_version": stage55_summary.get("tool_version"),
            "status": status,
            "event_process_count": count,
            "source_event_process_size": len(source_payload),
            "target_event_process_size": len(target_payload),
            "size_delta": len(target_payload) - len(source_payload),
            "source_framing_hypothesis_rows": len(source_hypotheses),
            "target_framing_hypothesis_rows": len(target_hypotheses),
            "framing_status": framing_status,
            "selected_source_schema": selected_source.schema_key if selected_source else "",
            "selected_target_schema": selected_target.schema_key if selected_target else "",
            "record_rows": len(record_rows),
            "changed_record_rows": changed_records,
            "friend_event_record_rows": len(friend_record_rows),
            "changed_friend_event_record_rows": changed_fe_records,
            "selected_order_id": selected_order_id,
            "mapping_status": mapping_status,
            "mapping_score": round(mapping_score, 6) if mapping_score >= 0 else 0,
            "mapping_support_rows": len(mapping_rows),
            "index_field_candidate_rows": len(edge_field_rows),
            "friend_event_trigger_edge_candidate_rows": len(edge_rows),
            "focused_friend_event_rows": len(focused_rows),
            "fe13_090": fe13_focus or {
                "classification": "record_mapping_unavailable", "review_status": "reachability_unresolved"
            },
            "skipped_rows": len(skipped_rows),
            "policy": {
                "record_framing_is_trigger_semantics": False,
                "inventory_order_is_record_mapping_proof": False,
                "opaque_index_fields_are_confirmed_edges": False,
                "file_presence_is_reachability_proof": False,
                "translation_json_modified": False,
                "event_payload_written": False,
                "pak_repacked": False,
                "core_registry_modified": False,
                "profile_activated": False,
                "installed_game_modified": False,
                "raw_record_payloads_exported": False,
            },
            "next_action": next_action,
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
        raise TriggerGraphError(f"project root does not exist: {project_root}")
    default_workspace = project_root / ".local/build/quartet_restoration"
    default_reports = project_root / ".local/reports/quartet_restoration"
    workspace_root = Path(args.workspace_root).expanduser().resolve() if args.workspace_root else default_workspace
    report_root = Path(args.report_root).expanduser().resolve() if args.report_root else default_reports
    output, summary = collect(project_root=project_root, workspace_root=workspace_root, report_root=report_root)
    print(f"Event-process count: {summary['event_process_count']}")
    print(f"Framing status: {summary['framing_status']}")
    print(f"Mapping status: {summary['mapping_status']}")
    print(f"Changed FE records: {summary['changed_friend_event_record_rows']}")
    print(f"Report: {output}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except TriggerGraphError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(2)
