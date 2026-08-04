#!/usr/bin/env python3
"""Blue Reflection series translation database exporter.

This tool intentionally uses only the Python standard library.  It validates
Gust EBM files with byte-exact roundtrips, pairs Japanese and official English
records, and exports editable translation JSON files with target-neutral IDs.
"""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import os
import re
import shutil
import struct
import subprocess
import sys
import tempfile
import time
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Optional

TOOL_VERSION = "translation-0.0.15"
FORMAT_VERSION = 1
MAX_STRING_SIZE = 2048
DURATION1_LENGTHS = (0, 2)
DURATION2_LENGTHS = (0, 1, 2)


class ToolError(RuntimeError):
    pass


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def rel_posix(path: Path, root: Path) -> str:
    return path.relative_to(root).as_posix()


def atomic_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
            f.write("\n")
        os.replace(tmp_name, path)
    except Exception:
        try:
            os.unlink(tmp_name)
        except FileNotFoundError:
            pass
        raise


def u32(data: bytes, offset: int) -> int:
    if offset + 4 > len(data):
        raise ToolError("Unexpected end of EBM data")
    return struct.unpack_from("<I", data, offset)[0]


@dataclass(frozen=True)
class EBMMessage:
    index: int
    type: int
    voice_id: int
    unknown1: int
    name_id: int
    extra_id: int
    expr_id: int
    duration1: tuple[int, ...]
    msg_id: int
    unknown2: int
    text: str
    duration2: tuple[int, ...]

    def metadata(self) -> dict[str, Any]:
        return {
            "type": self.type,
            "voice_id": self.voice_id,
            "unknown1": self.unknown1,
            "name_id": self.name_id,
            "extra_id": self.extra_id,
            "expr_id": self.expr_id,
            "duration1": list(self.duration1),
            "msg_id": self.msg_id,
            "unknown2": self.unknown2,
            "duration2": list(self.duration2),
        }


@dataclass(frozen=True)
class EBMFile:
    path: Path
    signed_count: int
    d1_len: int
    d2_len: int
    messages: tuple[EBMMessage, ...]
    extra_data: bytes
    raw: bytes


def _parse_ebm_candidate(
    data: bytes,
    path: Path,
    signed_count: int,
    d1_len: int,
    d2_len: int,
) -> Optional[EBMFile]:
    count = abs(signed_count)
    offset = 4
    messages: list[EBMMessage] = []
    try:
        for index in range(count):
            fixed_words = 9 + d1_len
            if offset + fixed_words * 4 > len(data):
                return None
            vals = [u32(data, offset + j * 4) for j in range(fixed_words)]
            cursor = 0
            msg_type = vals[cursor]; cursor += 1
            voice_id = vals[cursor]; cursor += 1
            unknown1 = vals[cursor]; cursor += 1
            name_id = vals[cursor]; cursor += 1
            extra_id = vals[cursor]; cursor += 1
            expr_id = vals[cursor]; cursor += 1
            duration1 = tuple(vals[cursor:cursor + d1_len]); cursor += d1_len
            msg_id = vals[cursor]; cursor += 1
            unknown2 = vals[cursor]; cursor += 1
            msg_length = vals[cursor]
            if msg_length == 0 or msg_length > MAX_STRING_SIZE:
                return None
            string_offset = offset + fixed_words * 4
            string_end = string_offset + msg_length
            duration_end = string_end + d2_len * 4
            if duration_end > len(data):
                return None
            raw_string = data[string_offset:string_end]
            if not raw_string or raw_string[-1] != 0 or b"\0" in raw_string[:-1]:
                return None
            text = raw_string[:-1].decode("utf-8", errors="strict")
            duration2 = tuple(
                u32(data, string_end + j * 4) for j in range(d2_len)
            )
            offset = duration_end
            messages.append(
                EBMMessage(
                    index=index,
                    type=msg_type,
                    voice_id=voice_id,
                    unknown1=unknown1,
                    name_id=name_id,
                    extra_id=extra_id,
                    expr_id=expr_id,
                    duration1=duration1,
                    msg_id=msg_id,
                    unknown2=unknown2,
                    text=text,
                    duration2=duration2,
                )
            )
    except (ToolError, UnicodeDecodeError, IndexError, struct.error):
        return None

    extra_data = data[offset:]
    if len(extra_data) % 4:
        return None
    return EBMFile(
        path,
        signed_count,
        d1_len,
        d2_len,
        tuple(messages),
        extra_data,
        data,
    )


def _ebm_candidate_score(ebm: EBMFile) -> float:
    """Rank structurally valid layouts using message-header plausibility.

    Gust's reference utility accepts the first layout that can be walked.  In
    some Second Light files, a duration word also looks like the beginning of
    the next record.  This score uses fields that are stable throughout the
    complete extracted corpus, while ties deliberately keep the shorter
    layout so trailing data is never consumed speculatively.
    """
    score = 0.0
    for message in ebm.messages:
        if message.type == 2:
            score += 10.0
        elif message.type in {0, 3}:
            score += 8.0
        elif message.type <= 0x10:
            score += 2.0
        else:
            score -= 20.0

        for value, maximum, weight in (
            (message.voice_id, 1_000_000, 1.0),
            (message.name_id, 1_000_000, 1.0),
            (message.extra_id, 1_000_000, 0.5),
            (message.expr_id, 1_000_000, 0.5),
        ):
            score += weight if value == 0xFFFFFFFF or value <= maximum else -5.0 * weight

        if message.unknown1 in {0, 1, 2, 0xFFFFFFFF}:
            score += 1.0
        elif message.unknown1 < 100_000:
            score += 0.1
        else:
            score -= 3.0

        if message.unknown2 in {0, 1, 2, 0xFFFFFFFF}:
            score += 3.0
        elif message.unknown2 < 1_000:
            score += 0.2
        else:
            score -= 5.0

        if message.msg_id != 0xFFFFFFFF and message.msg_id < 100_000_000:
            score += 4.0
        elif message.msg_id == 0xFFFFFFFF:
            score -= 1.0
        else:
            score -= 5.0

        bad_controls = sum(
            1
            for character in message.text
            if ord(character) < 32 and character not in "\n\r\t"
        )
        score += 6.0 if bad_controls == 0 else -20.0 * bad_controls

    message_ids = [
        message.msg_id
        for message in ebm.messages
        if message.msg_id != 0xFFFFFFFF
    ]
    if len(message_ids) >= 2:
        pairs = list(zip(message_ids, message_ids[1:]))
        score += 6.0 * sum(b >= a for a, b in pairs) / len(pairs)
        score += 4.0 * sum((b - a) in {0, 1} for a, b in pairs) / len(pairs)
    return score


def _parse_ebm_data_with_diagnostics(
    data: bytes,
    path: Path,
    forced_layout: Optional[tuple[int, int]] = None,
) -> tuple[EBMFile, dict[str, Any]]:
    if len(data) < 4:
        raise ToolError(f"EBM too short: {path}")
    signed_count = struct.unpack_from("<i", data, 0)[0]

    if forced_layout is not None:
        d1_len, d2_len = forced_layout
        ebm = _parse_ebm_candidate(data, path, signed_count, d1_len, d2_len)
        if ebm is None:
            raise ToolError(
                f"EBM does not match forced record structure "
                f"d1={d1_len},d2={d2_len}: {path}"
            )
        return ebm, {
            "candidate_count": 1,
            "selected_layout": [d1_len, d2_len],
            "naive_layout": [d1_len, d2_len],
            "layout_disambiguated": False,
            "score_margin": None,
        }

    candidates: list[tuple[float, int, int, EBMFile]] = []
    for d1_len in DURATION1_LENGTHS:
        for d2_len in DURATION2_LENGTHS:
            ebm = _parse_ebm_candidate(data, path, signed_count, d1_len, d2_len)
            if ebm is not None:
                candidates.append((_ebm_candidate_score(ebm), d1_len, d2_len, ebm))
    if not candidates:
        raise ToolError(f"Unsupported EBM record structure: {path}")

    naive = candidates[0]
    ranked = sorted(candidates, key=lambda item: (-item[0], item[1], item[2]))
    selected = ranked[0]
    margin = selected[0] - ranked[1][0] if len(ranked) > 1 else None
    return selected[3], {
        "candidate_count": len(candidates),
        "selected_layout": [selected[1], selected[2]],
        "naive_layout": [naive[1], naive[2]],
        "layout_disambiguated": (selected[1], selected[2]) != (naive[1], naive[2]),
        "score_margin": round(margin, 6) if margin is not None else None,
    }


def _parse_ebm_with_diagnostics(
    path: Path,
    forced_layout: Optional[tuple[int, int]] = None,
) -> tuple[EBMFile, dict[str, Any]]:
    return _parse_ebm_data_with_diagnostics(
        path.read_bytes(), path, forced_layout
    )


def parse_ebm_bytes(
    data: bytes,
    path: Path,
    forced_layout: Optional[tuple[int, int]] = None,
) -> EBMFile:
    return _parse_ebm_data_with_diagnostics(data, path, forced_layout)[0]


def parse_ebm(
    path: Path,
    forced_layout: Optional[tuple[int, int]] = None,
) -> EBMFile:
    return _parse_ebm_with_diagnostics(path, forced_layout)[0]

def serialize_ebm(ebm: EBMFile, texts: Optional[list[str]] = None) -> bytes:
    if texts is not None and len(texts) != len(ebm.messages):
        raise ToolError("Replacement EBM text count does not match template")
    out = bytearray(struct.pack("<i", ebm.signed_count))
    for i, msg in enumerate(ebm.messages):
        text = msg.text if texts is None else texts[i]
        raw = text.encode("utf-8") + b"\0"
        words = [
            msg.type,
            msg.voice_id,
            msg.unknown1,
            msg.name_id,
            msg.extra_id,
            msg.expr_id,
            *msg.duration1,
            msg.msg_id,
            msg.unknown2,
            len(raw),
        ]
        out.extend(struct.pack(f"<{len(words)}I", *words))
        out.extend(raw)
        if msg.duration2:
            out.extend(struct.pack(f"<{len(msg.duration2)}I", *msg.duration2))
    out.extend(ebm.extra_data)
    return bytes(out)


def unique_msg_id_map(messages: Iterable[EBMMessage]) -> dict[int, int]:
    grouped: dict[int, list[int]] = defaultdict(list)
    for msg in messages:
        grouped[msg.msg_id].append(msg.index)
    return {key: indices[0] for key, indices in grouped.items() if len(indices) == 1}


def align_messages(source: EBMFile, target: Optional[EBMFile]) -> tuple[list[Optional[int]], list[str]]:
    if target is None:
        return [None] * len(source.messages), ["missing_target"] * len(source.messages)

    if len(source.messages) == len(target.messages) and all(
        a.msg_id == b.msg_id for a, b in zip(source.messages, target.messages)
    ):
        return list(range(len(source.messages))), ["exact_index_msg_id"] * len(source.messages)

    result: list[Optional[int]] = [None] * len(source.messages)
    status = ["unmatched"] * len(source.messages)
    used: set[int] = set()
    target_by_id = unique_msg_id_map(target.messages)
    source_counts = Counter(msg.msg_id for msg in source.messages)

    for msg in source.messages:
        target_index = target_by_id.get(msg.msg_id)
        if source_counts[msg.msg_id] == 1 and target_index is not None and target_index not in used:
            result[msg.index] = target_index
            status[msg.index] = "exact_unique_msg_id"
            used.add(target_index)

    # If both sides have the same number of records, preserving sequence is a
    # useful fallback, but it is explicitly marked for review.
    if len(source.messages) == len(target.messages):
        for i in range(len(source.messages)):
            if result[i] is None and i not in used:
                result[i] = i
                status[i] = "index_fallback_review"
                used.add(i)

    return result, status


def metadata_diff(a: EBMMessage, b: EBMMessage) -> bool:
    return a.metadata() != b.metadata()


def is_redaction_placeholder(text: Optional[str], source_text: str) -> bool:
    if text is None:
        return False
    normalized = text.strip()
    source_normalized = source_text.strip()
    return normalized in {"-", "－", "--"} and source_normalized not in {"-", "－", "--"}


ATTR_RE = re.compile(r'([A-Za-z_][A-Za-z0-9_:-]*)\s*=\s*"([^"]*)"')
ROW_RE = re.compile(r"<str\b([^>]*)/?>", re.IGNORECASE)


@dataclass(frozen=True)
class XMLRow:
    index: int
    attrs: dict[str, str]
    text: str

    @property
    def string_no(self) -> Optional[str]:
        return self.attrs.get("String_No")

    @property
    def string_id(self) -> Optional[str]:
        return self.attrs.get("String_ID")


@dataclass(frozen=True)
class XMLTable:
    path: Path
    encoding: str
    rows: tuple[XMLRow, ...]
    raw: bytes


def decode_xml_bytes(data: bytes, path: Path) -> tuple[str, str]:
    payload = data[3:] if data.startswith(b"\xef\xbb\xbf") else data
    for encoding in ("utf-8", "cp932"):
        try:
            return payload.decode(encoding), encoding
        except UnicodeDecodeError:
            continue
    raise ToolError(f"Unsupported XML encoding: {path}")


def parse_xml_table_bytes(data: bytes, path: Path) -> XMLTable:
    text, encoding = decode_xml_bytes(data, path)
    rows: list[XMLRow] = []
    for index, match in enumerate(ROW_RE.finditer(text)):
        attrs = {key: value for key, value in ATTR_RE.findall(match.group(1))}
        raw_text = attrs.get("Text", "")
        rows.append(XMLRow(index=index, attrs=attrs, text=html.unescape(raw_text)))
    return XMLTable(path=path, encoding=encoding, rows=tuple(rows), raw=data)


def parse_xml_table(path: Path) -> XMLTable:
    return parse_xml_table_bytes(path.read_bytes(), path)


def row_key(row: XMLRow) -> tuple[str, str]:
    if row.string_no is not None:
        return ("String_No", row.string_no)
    if row.string_id is not None:
        return ("String_ID", row.string_id)
    return ("index", str(row.index))


def align_rows(source: XMLTable, target: Optional[XMLTable]) -> tuple[list[Optional[int]], list[str]]:
    if target is None:
        return [None] * len(source.rows), ["missing_target"] * len(source.rows)

    by_key: dict[tuple[str, str], list[int]] = defaultdict(list)
    for row in target.rows:
        by_key[row_key(row)].append(row.index)
    result: list[Optional[int]] = [None] * len(source.rows)
    status = ["unmatched"] * len(source.rows)
    used: set[int] = set()
    source_counts = Counter(row_key(row) for row in source.rows)

    for row in source.rows:
        key = row_key(row)
        candidates = by_key.get(key, [])
        if source_counts[key] == 1 and len(candidates) == 1 and candidates[0] not in used:
            result[row.index] = candidates[0]
            status[row.index] = f"exact_{key[0].lower()}"
            used.add(candidates[0])

    if len(source.rows) == len(target.rows):
        for i in range(len(source.rows)):
            if result[i] is None and i not in used:
                result[i] = i
                status[i] = "index_fallback_review"
                used.add(i)
    return result, status


EDIT_MIGRATION_STATS: Counter[str] = Counter()
AUXILIARY_FALLBACK_STATS: Counter[str] = Counter()

QUARTET_TARGET_ID = "blue_reflection_quartet"
QUARTET_POLICY_RELATIVE = Path(
    "workstreams/translation_tooling/config/quartet_target_adaptations.json"
)
QUARTET_TECHNICAL_TOKEN_RE = re.compile(r"<(?:IM\d+|KEY_ASSIGN_[A-Z0-9_]+)>")


def text_sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def classify_auxiliary_japanese_copy(
    auxiliary_jp_text: Optional[str], auxiliary_en_text: Optional[str]
) -> Optional[str]:
    """Recognize corpus-proven malformed Japanese copies in Quartet event_en.

    The raw auxiliary field remains untouched.  This only prevents malformed
    reference text from becoming editable English during a future export.
    """
    if not auxiliary_jp_text or not auxiliary_en_text:
        return None
    try:
        malformed = auxiliary_jp_text.encode("cp932").decode(
            "utf-16le", errors="replace"
        )
    except UnicodeEncodeError:
        malformed = None
    if malformed == auxiliary_en_text:
        return "invalid_cp932_bytes_as_utf16le_japanese_copy"
    if (auxiliary_jp_text, auxiliary_en_text) in {
        ("うん", "㼿㼿"),
        ("うん！", "㼿㼿I"),
    }:
        return "invalid_lossy_japanese_copy"
    return None


def load_quartet_target_policy(project_root: Path) -> dict[str, Any]:
    path = project_root / QUARTET_POLICY_RELATIVE
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ToolError(f"Quartet target adaptation policy is missing: {path}") from exc
    except json.JSONDecodeError as exc:
        raise ToolError(f"Invalid Quartet target adaptation policy {path}: {exc}") from exc
    if data.get("type") != "br_quartet_target_adaptation_policy":
        raise ToolError(f"Unexpected Quartet target policy type: {path}")
    if data.get("format_version") != 1 or data.get("target_id") != QUARTET_TARGET_ID:
        raise ToolError(f"Unsupported Quartet target adaptation policy: {path}")
    settings = data.get("policy")
    records = data.get("records")
    if not isinstance(settings, dict) or not isinstance(records, list):
        raise ToolError(f"Incomplete Quartet target adaptation policy: {path}")
    by_id: dict[str, dict[str, Any]] = {}
    for index, entry in enumerate(records):
        if not isinstance(entry, dict) or not isinstance(entry.get("logical_id"), str):
            raise ToolError(f"Invalid Quartet policy record {index}: {path}")
        logical_id = entry["logical_id"]
        if logical_id in by_id:
            raise ToolError(f"Duplicate Quartet policy logical_id: {logical_id}")
        if entry.get("action") not in {
            "shared_translation_allowed",
            "replace_technical_token_sequence",
            "literal_replacements",
            "preserve_target_template",
        }:
            raise ToolError(f"Unsupported Quartet policy action for {logical_id}")
        by_id[logical_id] = entry
    return {"path": path, "settings": settings, "records": by_id, "raw": data}


def validate_quartet_policy_fingerprints(
    entry: dict[str, Any], logical_id: str, source_jp: str, target_jp: str, target_en: str
) -> None:
    expected = {
        "source_jp_sha256": text_sha256(source_jp),
        "target_jp_sha256": text_sha256(target_jp),
        "target_template_en_sha256": text_sha256(target_en),
    }
    for key, actual in expected.items():
        if entry.get(key) != actual:
            raise ToolError(
                f"Quartet target policy fingerprint mismatch for {logical_id}: {key}"
            )


def replace_technical_token_sequence(
    text: str, expected_source: list[str], target_tokens: list[str], logical_id: str
) -> str:
    matches = list(QUARTET_TECHNICAL_TOKEN_RE.finditer(text))
    actual_source = [match.group(0) for match in matches]
    if actual_source != expected_source:
        raise ToolError(
            f"Quartet technical-token source sequence changed for {logical_id}: "
            f"expected {expected_source}, found {actual_source}"
        )
    if len(matches) != len(target_tokens):
        raise ToolError(
            f"Quartet token replacement count mismatch for {logical_id}; "
            "use preserve_target_template or literal_replacements"
        )
    pieces: list[str] = []
    cursor = 0
    for match, replacement in zip(matches, target_tokens):
        pieces.extend((text[cursor:match.start()], replacement))
        cursor = match.end()
    pieces.append(text[cursor:])
    return "".join(pieces)


def adapt_quartet_text(
    *,
    record: dict[str, Any],
    editable: str,
    target_jp: str,
    target_en: str,
    quartet_policy: dict[str, Any],
) -> tuple[Optional[str], str]:
    logical_id = str(record.get("logical_id", ""))
    source_jp = record.get("jp")
    if not isinstance(source_jp, str):
        raise ToolError(f"Record has no Japanese source text: {logical_id}")
    source_tokens = QUARTET_TECHNICAL_TOKEN_RE.findall(editable)
    target_tokens = QUARTET_TECHNICAL_TOKEN_RE.findall(target_en)
    if source_jp == target_jp and source_tokens == target_tokens:
        return editable, "shared_exact"

    settings = quartet_policy["settings"]
    marker = settings.get("redacted_target_marker", "-")
    if (
        settings.get("allow_redacted_target_import") is True
        and target_jp == marker
        and target_en == marker
    ):
        return editable, "redacted_target_import_allowed"

    entry = quartet_policy["records"].get(logical_id)
    if entry is None:
        raise ToolError(
            f"Unclassified Quartet target difference for {logical_id}; "
            f"update {quartet_policy['path']}"
        )
    validate_quartet_policy_fingerprints(
        entry, logical_id, source_jp, target_jp, target_en
    )
    action = entry["action"]
    if action == "shared_translation_allowed":
        return editable, action
    if action == "preserve_target_template":
        return None, action
    if action == "replace_technical_token_sequence":
        expected_source = entry.get("source_tokens")
        expected_target = entry.get("target_tokens")
        if not isinstance(expected_source, list) or not all(
            isinstance(value, str) for value in expected_source
        ):
            raise ToolError(f"Invalid source token policy for {logical_id}")
        if not isinstance(expected_target, list) or not all(
            isinstance(value, str) for value in expected_target
        ):
            raise ToolError(f"Invalid target token policy for {logical_id}")
        if target_tokens != expected_target:
            raise ToolError(
                f"Quartet target token sequence changed for {logical_id}: "
                f"expected {expected_target}, found {target_tokens}"
            )
        return (
            replace_technical_token_sequence(
                editable, expected_source, expected_target, logical_id
            ),
            action,
        )
    replacements = entry.get("replacements")
    if action != "literal_replacements" or not isinstance(replacements, list):
        raise ToolError(f"Invalid Quartet literal-replacement policy for {logical_id}")
    adapted = editable
    for replacement in replacements:
        if not isinstance(replacement, dict):
            raise ToolError(f"Invalid literal replacement for {logical_id}")
        old = replacement.get("old")
        new = replacement.get("new")
        expected_count = replacement.get("expected_occurrences", 1)
        if not isinstance(old, str) or not isinstance(new, str) or not isinstance(expected_count, int):
            raise ToolError(f"Invalid literal replacement values for {logical_id}")
        actual_count = adapted.count(old)
        if actual_count != expected_count:
            raise ToolError(
                f"Quartet literal replacement source changed for {logical_id}: "
                f"{old!r} expected {expected_count}, found {actual_count}"
            )
        adapted = adapted.replace(old, new)
    return adapted, action


def _initial_editable(record: dict[str, Any]) -> str:
    alignment = record.get("alignment")
    initial_source = alignment.get("initial_en_source") if isinstance(alignment, dict) else None
    if initial_source == "official_en":
        value = record.get("en_original")
        return value if isinstance(value, str) else ""
    if initial_source == "quartet_en":
        value = record.get("en_auxiliary")
        return value if isinstance(value, str) else ""
    return ""


def load_existing_edits(path: Path, unit_type: str) -> dict[str, dict[str, Any]]:
    if not path.exists():
        return {}
    try:
        existing = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ToolError(f"Cannot read existing translation unit {path}: {exc}") from exc
    if existing.get("type") != unit_type or existing.get("format_version") != FORMAT_VERSION:
        raise ToolError(f"Refusing to replace incompatible translation unit: {path}")

    edits: dict[str, dict[str, Any]] = {}
    for record in existing.get("records", []):
        logical_id = record.get("logical_id")
        index = record.get("index")
        current_en = record.get("en")
        manually_edited = isinstance(current_en, str) and current_en != _initial_editable(record)
        has_notes = "notes" in record and record.get("notes") not in (None, "", [])
        has_status = "status" in record
        if not (manually_edited or has_notes or has_status):
            EDIT_MIGRATION_STATS["baseline_records_refreshed"] += 1
            continue

        keep: dict[str, Any] = {}
        for key in ("en", "notes", "status"):
            if key in record:
                keep[key] = record[key]
        if isinstance(logical_id, str):
            edits[f"id:{logical_id}"] = keep
        if isinstance(index, int):
            edits[f"index:{index}"] = keep
        EDIT_MIGRATION_STATS["user_edited_records_found"] += 1
    return edits


def apply_existing(record: dict[str, Any], edits: dict[str, dict[str, Any]]) -> Optional[str]:
    previous = edits.get(f"id:{record['logical_id']}")
    method = "logical_id"
    if previous is None and isinstance(record.get("index"), int):
        previous = edits.get(f"index:{record['index']}")
        method = "source_index"
    if not previous:
        return None
    for key, value in previous.items():
        record[key] = value
    EDIT_MIGRATION_STATS[f"preserved_by_{method}"] += 1
    return method


@dataclass(frozen=True)
class EventSet:
    project: str
    translation_root: Path
    source_jp_root: Path
    official_en_root: Path
    target_templates: dict[str, Path]
    auxiliary_jp_root: Optional[Path] = None
    auxiliary_en_root: Optional[Path] = None
    allow_auxiliary_fallback: bool = True
    export_auxiliary_extensions: bool = False


@dataclass(frozen=True)
class SystemSet:
    project: str
    translation_root: Path
    source_jp_root: Path
    official_en_root: Path
    target_templates: dict[str, Path]
    auxiliary_jp_root: Optional[Path] = None
    auxiliary_en_root: Optional[Path] = None
    allow_auxiliary_fallback: bool = True


def files_by_relative(root: Path, suffix: str) -> dict[str, Path]:
    if not root.is_dir():
        raise ToolError(f"Required extracted directory is missing: {root}")
    return {
        path.relative_to(root).as_posix(): path
        for path in sorted(root.rglob(f"*{suffix}"))
        if path.is_file()
    }


def event_output_path(translation_root: Path, logical_path: str) -> Path:
    relative = Path(logical_path)
    return translation_root / "events" / relative.parent / f"{relative.name}.json"


def export_event_set(spec: EventSet, project_root: Path, report: dict[str, Any]) -> list[dict[str, Any]]:
    source_files = files_by_relative(spec.source_jp_root, ".ebm")
    official_files = files_by_relative(spec.official_en_root, ".ebm")
    aux_jp_files = files_by_relative(spec.auxiliary_jp_root, ".ebm") if spec.auxiliary_jp_root else {}
    aux_en_files = files_by_relative(spec.auxiliary_en_root, ".ebm") if spec.auxiliary_en_root else {}
    target_files = {
        target: files_by_relative(root, ".ebm") for target, root in spec.target_templates.items()
    }

    units: list[dict[str, Any]] = []
    project_counts = Counter()
    exceptions: list[dict[str, Any]] = []

    for logical_path, source_path in source_files.items():
        source = parse_ebm(source_path)
        official_path = official_files.get(logical_path)
        official = parse_ebm(official_path) if official_path else None
        official_map, official_status = align_messages(source, official)

        aux_jp_path = aux_jp_files.get(logical_path)
        aux_en_path = aux_en_files.get(logical_path)
        aux_jp = parse_ebm(aux_jp_path) if aux_jp_path else None
        aux_en = parse_ebm(aux_en_path) if aux_en_path else None
        source_to_aux, source_to_aux_status = align_messages(source, aux_jp)
        aux_to_en, aux_to_en_status = align_messages(aux_jp, aux_en) if aux_jp else ([], [])

        target_maps: dict[str, tuple[list[Optional[int]], list[str], Optional[EBMFile], Optional[Path]]] = {}
        for target, mapping in target_files.items():
            target_path = mapping.get(logical_path)
            target_ebm = parse_ebm(target_path) if target_path else None
            indices, statuses = align_messages(source, target_ebm)
            target_maps[target] = (indices, statuses, target_ebm, target_path)

        output_path = event_output_path(spec.translation_root, logical_path)
        existing = load_existing_edits(output_path, "br_event_translation_unit")
        carried = 0
        records: list[dict[str, Any]] = []

        for msg in source.messages:
            primary_index = official_map[msg.index]
            primary_text = official.messages[primary_index].text if official is not None and primary_index is not None else None

            aux_source_index = source_to_aux[msg.index] if aux_jp else None
            auxiliary_text: Optional[str] = None
            auxiliary_classification: Optional[str] = None
            auxiliary_index: Optional[int] = None
            aux_status = "unavailable"
            if aux_source_index is not None and aux_en is not None and aux_source_index < len(aux_to_en):
                auxiliary_index = aux_to_en[aux_source_index]
                if auxiliary_index is not None:
                    auxiliary_jp_text = aux_jp.messages[aux_source_index].text if aux_jp else None
                    auxiliary_text = aux_en.messages[auxiliary_index].text
                    auxiliary_classification = classify_auxiliary_japanese_copy(
                        auxiliary_jp_text, auxiliary_text
                    )
                    if auxiliary_classification is not None:
                        AUXILIARY_FALLBACK_STATS[auxiliary_classification] += 1
                    aux_status = f"{source_to_aux_status[msg.index]}+{aux_to_en_status[aux_source_index]}"

            primary_redacted = is_redaction_placeholder(primary_text, msg.text)
            auxiliary_redacted = is_redaction_placeholder(auxiliary_text, msg.text)
            if primary_text is not None and not primary_redacted:
                editable = primary_text
                alignment_status = official_status[msg.index]
                source_of_initial_en = "official_en"
            elif (
                spec.allow_auxiliary_fallback
                and auxiliary_text is not None
                and not auxiliary_redacted
                and auxiliary_classification is None
            ):
                editable = auxiliary_text
                alignment_status = "auxiliary_fallback_review"
                source_of_initial_en = "quartet_en"
                AUXILIARY_FALLBACK_STATS["accepted_event_auxiliary_fallback"] += 1
            else:
                editable = ""
                if primary_redacted or auxiliary_redacted:
                    alignment_status = "redacted_official_manual_required"
                else:
                    alignment_status = "manual_required"
                source_of_initial_en = "none"

            target_indices = {
                target: indices[msg.index] for target, (indices, _, _, _) in target_maps.items()
            }
            target_statuses = {
                target: statuses[msg.index] for target, (_, statuses, _, _) in target_maps.items()
            }

            logical_id = f"{spec.project}:event:{logical_path}:source_index:{msg.index}:msg_id:{msg.msg_id}"
            record: dict[str, Any] = {
                "index": msg.index,
                "logical_id": logical_id,
                "msg_id": msg.msg_id,
                "voice_id": msg.voice_id,
                "name_id": msg.name_id,
                "expr_id": msg.expr_id,
                "metadata": msg.metadata(),
                "jp": msg.text,
                "en_original": primary_text,
                "en_auxiliary": auxiliary_text,
                "en": editable,
                "alignment": {
                    "status": alignment_status,
                    "initial_en_source": source_of_initial_en,
                    "official_en_index": primary_index,
                    "official_en_mapping": official_status[msg.index],
                    "auxiliary_en_index": auxiliary_index,
                    "auxiliary_mapping": aux_status,
                    "target_indices": target_indices,
                    "target_mapping": target_statuses,
                },
            }
            if apply_existing(record, existing):
                carried += 1
            records.append(record)
            project_counts[alignment_status] += 1
            if alignment_status != "exact_index_msg_id":
                exceptions.append({
                    "logical_path": logical_path,
                    "record_index": msg.index,
                    "msg_id": msg.msg_id,
                    "status": alignment_status,
                    "official_en_index": primary_index,
                    "auxiliary_en_index": auxiliary_index,
                    "target_mapping": target_statuses,
                })

        targets_json: dict[str, Any] = {}
        for target, (indices, statuses, target_ebm, target_path) in target_maps.items():
            targets_json[target] = {
                "template_language": "en",
                "template_path": rel_posix(target_path, project_root) if target_path else None,
                "template_sha256": sha256_file(target_path) if target_path else None,
                "message_count": len(target_ebm.messages) if target_ebm else None,
                "mapping_status_counts": dict(sorted(Counter(statuses).items())),
                "complete_mapping": all(index is not None for index in indices),
            }

        unit = {
            "type": "br_event_translation_unit",
            "format_version": FORMAT_VERSION,
            "tool_version": TOOL_VERSION,
            "project": spec.project,
            "category": "event",
            "logical_path": logical_path,
            "source": {
                "jp_path": rel_posix(source_path, project_root),
                "jp_sha256": sha256_file(source_path),
                "signed_message_count": source.signed_count,
                "record_structure": {"duration1_words": source.d1_len, "duration2_words": source.d2_len},
                "official_en_path": rel_posix(official_path, project_root) if official_path else None,
                "official_en_sha256": sha256_file(official_path) if official_path else None,
                "auxiliary_jp_path": rel_posix(aux_jp_path, project_root) if aux_jp_path else None,
                "auxiliary_en_path": rel_posix(aux_en_path, project_root) if aux_en_path else None,
            },
            "targets": targets_json,
            "records": records,
        }
        atomic_json(output_path, unit)
        units.append({
            "path": rel_posix(output_path, spec.translation_root),
            "category": "event",
            "logical_path": logical_path,
            "records": len(records),
            "carried_over": carried,
            "alignment_status_counts": dict(sorted(Counter(r["alignment"]["status"] for r in records).items())),
        })

    extension_units, extension_exceptions = export_event_extension_units(
        spec, project_root, source_files, aux_jp_files, aux_en_files
    )
    units.extend(extension_units)
    exceptions.extend(extension_exceptions)
    missing_official = sorted(set(source_files) - set(official_files))
    extra_official = sorted(set(official_files) - set(source_files))
    report[spec.project]["events"] = {
        "source_files": len(source_files),
        "official_en_files": len(official_files),
        "missing_official_files": missing_official,
        "extra_official_files": extra_official,
        "quartet_extension_files": len(extension_units),
        "records": sum(unit["records"] for unit in units),
        "status_counts": dict(sorted(project_counts.items())),
        "exceptions": exceptions,
    }
    return units



def export_event_extension_units(
    spec: EventSet,
    project_root: Path,
    source_files: dict[str, Path],
    aux_jp_files: dict[str, Path],
    aux_en_files: dict[str, Path],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Export target-only event units found in an auxiliary Quartet branch."""
    if not spec.export_auxiliary_extensions or not spec.auxiliary_jp_root:
        return [], []
    units: list[dict[str, Any]] = []
    exceptions: list[dict[str, Any]] = []
    for logical_path in sorted(set(aux_jp_files) - set(source_files)):
        source_path = aux_jp_files[logical_path]
        official_path = aux_en_files.get(logical_path)
        source = parse_ebm(source_path)
        official = parse_ebm(official_path) if official_path else None
        official_map, official_status = align_messages(source, official)
        output_path = spec.translation_root / "events_quartet_extensions" / Path(logical_path).parent / f"{Path(logical_path).name}.json"
        existing = load_existing_edits(output_path, "br_event_translation_unit")
        records: list[dict[str, Any]] = []
        carried = 0
        target_id = next((key for key in spec.target_templates if key.endswith("quartet")), None)
        for msg in source.messages:
            primary_index = official_map[msg.index]
            primary_text = official.messages[primary_index].text if official is not None and primary_index is not None else None
            logical_id = f"{spec.project}:event_quartet_extension:{logical_path}:source_index:{msg.index}:msg_id:{msg.msg_id}"
            record: dict[str, Any] = {
                "index": msg.index,
                "logical_id": logical_id,
                "msg_id": msg.msg_id,
                "voice_id": msg.voice_id,
                "name_id": msg.name_id,
                "expr_id": msg.expr_id,
                "metadata": msg.metadata(),
                "jp": msg.text,
                "en_original": primary_text,
                "en_auxiliary": None,
                "en": primary_text or "",
                "alignment": {
                    "status": official_status[msg.index] if primary_text is not None else "manual_required",
                    "initial_en_source": "quartet_official_en" if primary_text is not None else "none",
                    "official_en_index": primary_index,
                    "official_en_mapping": official_status[msg.index],
                    "auxiliary_en_index": None,
                    "auxiliary_mapping": "not_applicable_target_extension",
                    "target_indices": {target_id: primary_index} if target_id else {},
                    "target_mapping": {target_id: official_status[msg.index]} if target_id else {},
                },
            }
            if apply_existing(record, existing):
                carried += 1
            records.append(record)
            if primary_text is None:
                exceptions.append({"logical_path": logical_path, "logical_id": logical_id, "status": "manual_required", "source_role": "quartet_extension"})
        targets = {}
        if target_id:
            targets[target_id] = {
                "template_language": "en",
                "template_path": rel_posix(official_path, project_root) if official_path else None,
                "template_sha256": sha256_file(official_path) if official_path else None,
                "message_count": len(official.messages) if official else None,
                "mapping_status_counts": dict(sorted(Counter(official_status).items())),
                "complete_mapping": all(index is not None for index in official_map),
            }
        unit = {
            "type": "br_event_translation_unit",
            "format_version": FORMAT_VERSION,
            "tool_version": TOOL_VERSION,
            "project": spec.project,
            "category": "event",
            "source_role": "quartet_extension",
            "logical_path": logical_path,
            "source": {
                "jp_path": rel_posix(source_path, project_root),
                "jp_sha256": sha256_file(source_path),
                "signed_message_count": source.signed_count,
                "record_structure": {"duration1_words": source.d1_len, "duration2_words": source.d2_len},
                "official_en_path": rel_posix(official_path, project_root) if official_path else None,
                "official_en_sha256": sha256_file(official_path) if official_path else None,
                "auxiliary_jp_path": None,
                "auxiliary_en_path": None,
            },
            "targets": targets,
            "records": records,
        }
        atomic_json(output_path, unit)
        units.append({
            "path": rel_posix(output_path, spec.translation_root),
            "category": "event",
            "source_role": "quartet_extension",
            "logical_path": logical_path,
            "records": len(records),
            "carried_over": carried,
            "alignment_status_counts": dict(sorted(Counter(r["alignment"]["status"] for r in records).items())),
        })
    return units, exceptions

def xml_output_path(translation_root: Path, group: str, logical_path: str) -> Path:
    relative = Path(logical_path)
    return translation_root / group / relative.parent / f"{relative.name}.json"


def export_xml_unit(
    *,
    spec: SystemSet,
    project_root: Path,
    logical_path: str,
    source_path: Path,
    official_path: Optional[Path],
    target_paths: dict[str, Optional[Path]],
    auxiliary_jp_path: Optional[Path],
    auxiliary_en_path: Optional[Path],
    group: str,
    source_role: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    source = parse_xml_table(source_path)
    official = parse_xml_table(official_path) if official_path else None
    official_map, official_status = align_rows(source, official)
    aux_jp = parse_xml_table(auxiliary_jp_path) if auxiliary_jp_path else None
    aux_en = parse_xml_table(auxiliary_en_path) if auxiliary_en_path else None
    source_to_aux, source_to_aux_status = align_rows(source, aux_jp)
    aux_to_en, aux_to_en_status = align_rows(aux_jp, aux_en) if aux_jp else ([], [])

    target_data: dict[str, tuple[Optional[XMLTable], list[Optional[int]], list[str], Optional[Path]]] = {}
    for target, path in target_paths.items():
        table = parse_xml_table(path) if path else None
        indices, statuses = align_rows(source, table)
        target_data[target] = (table, indices, statuses, path)

    output_path = xml_output_path(spec.translation_root, group, logical_path)
    existing = load_existing_edits(output_path, "br_system_translation_unit")
    carried = 0
    records: list[dict[str, Any]] = []

    for row in source.rows:
        primary_index = official_map[row.index]
        primary_text = official.rows[primary_index].text if official is not None and primary_index is not None else None
        auxiliary_index: Optional[int] = None
        auxiliary_text: Optional[str] = None
        auxiliary_classification: Optional[str] = None
        aux_status = "unavailable"
        aux_source_index = source_to_aux[row.index] if aux_jp else None
        if aux_source_index is not None and aux_en is not None and aux_source_index < len(aux_to_en):
            auxiliary_index = aux_to_en[aux_source_index]
            if auxiliary_index is not None:
                auxiliary_jp_text = aux_jp.rows[aux_source_index].text if aux_jp else None
                auxiliary_text = aux_en.rows[auxiliary_index].text
                auxiliary_classification = classify_auxiliary_japanese_copy(
                    auxiliary_jp_text, auxiliary_text
                )
                if auxiliary_classification is not None:
                    AUXILIARY_FALLBACK_STATS[auxiliary_classification] += 1
                aux_status = f"{source_to_aux_status[row.index]}+{aux_to_en_status[aux_source_index]}"

        if primary_text is not None:
            editable = primary_text
            alignment_status = official_status[row.index]
            initial_source = "official_en"
        elif spec.allow_auxiliary_fallback and auxiliary_text is not None and auxiliary_classification is None:
            editable = auxiliary_text
            alignment_status = "auxiliary_fallback_review"
            initial_source = "quartet_en"
            AUXILIARY_FALLBACK_STATS["accepted_system_auxiliary_fallback"] += 1
        else:
            editable = ""
            alignment_status = "manual_required"
            initial_source = "none"

        key_kind, key_value = row_key(row)
        logical_id = f"{spec.project}:system:{logical_path}:{key_kind}:{key_value}"
        target_indices = {target: indices[row.index] for target, (_, indices, _, _) in target_data.items()}
        target_statuses = {target: statuses[row.index] for target, (_, _, statuses, _) in target_data.items()}
        attrs = {key: value for key, value in row.attrs.items() if key != "Text"}
        record: dict[str, Any] = {
            "index": row.index,
            "logical_id": logical_id,
            "string_no": row.string_no,
            "string_id": row.string_id,
            "attributes": attrs,
            "jp": row.text,
            "en_original": primary_text,
            "en_auxiliary": auxiliary_text,
            "en": editable,
            "alignment": {
                "status": alignment_status,
                "initial_en_source": initial_source,
                "official_en_index": primary_index,
                "official_en_mapping": official_status[row.index],
                "auxiliary_en_index": auxiliary_index,
                "auxiliary_mapping": aux_status,
                "target_indices": target_indices,
                "target_mapping": target_statuses,
            },
        }
        if apply_existing(record, existing):
            carried += 1
        records.append(record)

    targets_json: dict[str, Any] = {}
    for target, (table, indices, statuses, path) in target_data.items():
        targets_json[target] = {
            "template_language": "en",
            "template_path": rel_posix(path, project_root) if path else None,
            "template_sha256": sha256_file(path) if path else None,
            "row_count": len(table.rows) if table else None,
            "encoding": table.encoding if table else None,
            "mapping_status_counts": dict(sorted(Counter(statuses).items())),
            "complete_mapping": all(index is not None for index in indices),
        }

    unit = {
        "type": "br_system_translation_unit",
        "format_version": FORMAT_VERSION,
        "tool_version": TOOL_VERSION,
        "project": spec.project,
        "category": "system",
        "source_role": source_role,
        "logical_path": logical_path,
        "source": {
            "jp_path": rel_posix(source_path, project_root),
            "jp_sha256": sha256_file(source_path),
            "jp_encoding": source.encoding,
            "official_en_path": rel_posix(official_path, project_root) if official_path else None,
            "official_en_sha256": sha256_file(official_path) if official_path else None,
            "auxiliary_jp_path": rel_posix(auxiliary_jp_path, project_root) if auxiliary_jp_path else None,
            "auxiliary_en_path": rel_posix(auxiliary_en_path, project_root) if auxiliary_en_path else None,
        },
        "targets": targets_json,
        "records": records,
    }
    atomic_json(output_path, unit)
    summary = {
        "path": rel_posix(output_path, spec.translation_root),
        "category": "system",
        "source_role": source_role,
        "logical_path": logical_path,
        "records": len(records),
        "carried_over": carried,
        "alignment_status_counts": dict(sorted(Counter(r["alignment"]["status"] for r in records).items())),
    }
    return summary, unit


def export_system_set(spec: SystemSet, project_root: Path, report: dict[str, Any]) -> list[dict[str, Any]]:
    source_files = files_by_relative(spec.source_jp_root, ".xml")
    official_files = files_by_relative(spec.official_en_root, ".xml")
    source_files.pop("strcombineall.xml", None)
    official_files.pop("strcombineall.xml", None)

    aux_jp_files = files_by_relative(spec.auxiliary_jp_root, ".xml") if spec.auxiliary_jp_root else {}
    aux_en_files = files_by_relative(spec.auxiliary_en_root, ".xml") if spec.auxiliary_en_root else {}
    aux_jp_files.pop("strcombineall.xml", None)
    aux_en_files.pop("strcombineall.xml", None)

    target_files = {
        target: files_by_relative(root, ".xml") for target, root in spec.target_templates.items()
    }
    for mapping in target_files.values():
        mapping.pop("strcombineall.xml", None)

    units: list[dict[str, Any]] = []
    exceptions: list[dict[str, Any]] = []
    status_counts = Counter()

    for logical_path, source_path in source_files.items():
        target_paths = {target: mapping.get(logical_path) for target, mapping in target_files.items()}
        summary, unit = export_xml_unit(
            spec=spec,
            project_root=project_root,
            logical_path=logical_path,
            source_path=source_path,
            official_path=official_files.get(logical_path),
            target_paths=target_paths,
            auxiliary_jp_path=aux_jp_files.get(logical_path),
            auxiliary_en_path=aux_en_files.get(logical_path),
            group="system",
            source_role="canonical",
        )
        units.append(summary)
        for record in unit["records"]:
            status = record["alignment"]["status"]
            status_counts[status] += 1
            if not status.startswith("exact_"):
                exceptions.append({
                    "logical_path": logical_path,
                    "logical_id": record["logical_id"],
                    "status": status,
                    "target_mapping": record["alignment"]["target_mapping"],
                })

    # Quartet-specific extensions are part of the same first-game translation
    # set but have no original-2017 counterpart.
    if spec.auxiliary_jp_root and spec.auxiliary_en_root:
        extension_paths = sorted(set(aux_jp_files) - set(source_files))
        for logical_path in extension_paths:
            source_path = aux_jp_files[logical_path]
            target_paths = {
                target: (mapping.get(logical_path) if target.endswith("quartet") else None)
                for target, mapping in target_files.items()
            }
            summary, unit = export_xml_unit(
                spec=spec,
                project_root=project_root,
                logical_path=logical_path,
                source_path=source_path,
                official_path=aux_en_files.get(logical_path),
                target_paths=target_paths,
                auxiliary_jp_path=None,
                auxiliary_en_path=None,
                group="system_quartet_extensions",
                source_role="quartet_extension",
            )
            units.append(summary)
            for record in unit["records"]:
                status = record["alignment"]["status"]
                status_counts[status] += 1
                if not status.startswith("exact_"):
                    exceptions.append({
                        "logical_path": logical_path,
                        "logical_id": record["logical_id"],
                        "status": status,
                        "source_role": "quartet_extension",
                    })
    else:
        extension_paths = []

    report[spec.project]["system"] = {
        "canonical_tables": len(source_files),
        "official_en_tables": len(official_files),
        "quartet_extension_tables": extension_paths,
        "records": sum(unit["records"] for unit in units),
        "status_counts": dict(sorted(status_counts.items())),
        "exceptions": exceptions,
    }
    return units


def validate_all_ebm(project_root: Path) -> dict[str, Any]:
    ebm_paths = sorted((project_root / "titles").rglob("*.ebm"))
    structures = Counter()
    candidate_counts = Counter()
    failures: list[dict[str, str]] = []
    disambiguations: list[dict[str, Any]] = []
    max_length = 0
    total_messages = 0
    for path in ebm_paths:
        try:
            ebm, diagnostics = _parse_ebm_with_diagnostics(path)
            rebuilt = serialize_ebm(ebm)
            if rebuilt != ebm.raw:
                raise ToolError("byte-exact roundtrip mismatch")
            structures[f"d1={ebm.d1_len},d2={ebm.d2_len}"] += 1
            candidate_counts[str(diagnostics["candidate_count"])] += 1
            if diagnostics["layout_disambiguated"]:
                disambiguations.append({
                    "path": rel_posix(path, project_root),
                    "naive_layout": diagnostics["naive_layout"],
                    "selected_layout": diagnostics["selected_layout"],
                    "score_margin": diagnostics["score_margin"],
                })
            total_messages += len(ebm.messages)
            for message in ebm.messages:
                max_length = max(max_length, len(message.text.encode("utf-8")))
        except Exception as exc:
            failures.append({"path": rel_posix(path, project_root), "error": str(exc)})
    return {
        "files": len(ebm_paths),
        "messages": total_messages,
        "record_structures": dict(sorted(structures.items())),
        "valid_candidate_counts": dict(sorted(candidate_counts.items())),
        "layout_disambiguations": len(disambiguations),
        "layout_disambiguation_files": disambiguations,
        "max_utf8_message_bytes": max_length,
        "failures": failures,
        "byte_exact_roundtrip": len(failures) == 0,
    }

def project_specs(project_root: Path) -> tuple[list[EventSet], list[SystemSet]]:
    br = project_root / "titles/blue_reflection"
    sl = project_root / "titles/second_light"
    sun = project_root / "titles/blue_reflection_sun"
    ray = project_root / "titles/blue_reflection_ray"
    br_orig = br / "workspace/original/archives"
    br_quart = br / "workspace/quartet/archives"
    sl_orig = sl / "workspace/original/archives"
    sl_quart = sl / "workspace/quartet/archives"
    sun_quart = sun / "workspace/quartet/archives"
    ray_quart = ray / "workspace/quartet/archives"

    event_sets = [
        EventSet(
            project="blue_reflection",
            translation_root=br / "translation",
            source_jp_root=br_orig / "PACK01/event/event_jp",
            official_en_root=br_orig / "PACK01/event/event_en",
            auxiliary_jp_root=br_quart / "PACK11/event/b1/event_jp",
            auxiliary_en_root=br_quart / "PACK11/event/b1/event_en",
            target_templates={
                "blue_reflection_original": br_orig / "PACK01/event/event_en",
                "blue_reflection_quartet": br_quart / "PACK11/event/b1/event_en",
            },
        ),
        EventSet(
            project="second_light",
            translation_root=sl / "translation",
            source_jp_root=sl_orig / "PACK01/event/event_jp",
            official_en_root=sl_orig / "PACK01/event/event_en",
            auxiliary_jp_root=sl_quart / "PACK01_01/event/b2/event_jp",
            auxiliary_en_root=sl_quart / "PACK01_01/event/b2/event_en",
            allow_auxiliary_fallback=False,
            export_auxiliary_extensions=True,
            target_templates={
                "second_light_original": sl_orig / "PACK01/event/event_en",
                "second_light_quartet": sl_quart / "PACK01_01/event/b2/event_en",
            },
        ),
        EventSet(
            project="blue_reflection_sun",
            translation_root=sun / "translation",
            source_jp_root=sun_quart / "PACK01_02/event/b3/event_jp",
            official_en_root=sun_quart / "PACK01_02/event/b3/event_en",
            target_templates={
                "blue_reflection_sun_quartet": sun_quart / "PACK01_02/event/b3/event_en",
            },
        ),
        EventSet(
            project="blue_reflection_ray",
            translation_root=ray / "translation",
            source_jp_root=ray_quart / "PACK01_03/event/b4/event_jp",
            official_en_root=ray_quart / "PACK01_03/event/b4/event_en",
            target_templates={
                "blue_reflection_ray_quartet": ray_quart / "PACK01_03/event/b4/event_en",
            },
        ),
    ]
    system_sets = [
        SystemSet(
            project="blue_reflection",
            translation_root=br / "translation",
            source_jp_root=br_orig / "PACK02_3/saves_jp/text",
            official_en_root=br_orig / "PACK02_1/saves_en/text",
            auxiliary_jp_root=br_quart / "PACK12/saves/b1/text_jp",
            auxiliary_en_root=br_quart / "PACK12/saves/b1/text_en",
            target_templates={
                "blue_reflection_original": br_orig / "PACK02_1/saves_en/text",
                "blue_reflection_quartet": br_quart / "PACK12/saves/b1/text_en",
            },
        ),
        SystemSet(
            project="second_light",
            translation_root=sl / "translation",
            source_jp_root=sl_orig / "PACK02/saves/text_jp",
            official_en_root=sl_orig / "PACK02/saves/text_en",
            auxiliary_jp_root=sl_quart / "PACK02_01/saves/b2/text_jp",
            auxiliary_en_root=sl_quart / "PACK02_01/saves/b2/text_en",
            allow_auxiliary_fallback=False,
            target_templates={
                "second_light_original": sl_orig / "PACK02/saves/text_en",
                "second_light_quartet": sl_quart / "PACK02_01/saves/b2/text_en",
            },
        ),
        SystemSet(
            project="blue_reflection_sun",
            translation_root=sun / "translation",
            source_jp_root=sun_quart / "PACK02_02/saves/b3/text_jp",
            official_en_root=sun_quart / "PACK02_02/saves/b3/text_en",
            target_templates={
                "blue_reflection_sun_quartet": sun_quart / "PACK02_02/saves/b3/text_en",
            },
        ),
        SystemSet(
            project="blue_reflection_ray",
            translation_root=ray / "translation",
            source_jp_root=ray_quart / "PACK02_03/saves/b4/text_jp",
            official_en_root=ray_quart / "PACK02_03/saves/b4/text_en",
            target_templates={
                "blue_reflection_ray_quartet": ray_quart / "PACK02_03/saves/b4/text_en",
            },
        ),
    ]
    return event_sets, system_sets


def write_manifest(translation_root: Path, project: str, units: list[dict[str, Any]]) -> None:
    manifest = {
        "type": "br_translation_project",
        "format_version": FORMAT_VERSION,
        "tool_version": TOOL_VERSION,
        "project": project,
        "workspace_hint": "../workspace",
        "editable_field": "en",
        "canonical_source_language": "jp",
        "units": sorted(units, key=lambda unit: unit["path"]),
        "summary": {
            "units": len(units),
            "records": sum(unit["records"] for unit in units),
            "carried_over": sum(unit.get("carried_over", 0) for unit in units),
            "categories": dict(sorted(Counter(unit["category"] for unit in units).items())),
        },
    }
    atomic_json(translation_root / "translation_manifest.json", manifest)


def cmd_export(args: argparse.Namespace) -> int:
    EDIT_MIGRATION_STATS.clear()
    AUXILIARY_FALLBACK_STATS.clear()
    project_root = Path(args.project_root).expanduser().resolve()
    if not (project_root / "config/project_version").is_file():
        raise ToolError(f"Not a Blue Reflection project root: {project_root}")

    report: dict[str, Any] = {
        "type": "br_translation_export_report",
        "format_version": FORMAT_VERSION,
        "tool_version": TOOL_VERSION,
        "project_root": "<PROJECT_ROOT>",
        "runtime_target_adapter": "active_english",
        "ebm_validation": validate_all_ebm(project_root),
        "blue_reflection": {},
        "second_light": {},
        "blue_reflection_sun": {},
        "blue_reflection_ray": {},
    }
    if report["ebm_validation"]["failures"]:
        raise ToolError(
            f"EBM validation failed for {len(report['ebm_validation']['failures'])} files"
        )

    event_sets, system_sets = project_specs(project_root)
    units_by_project: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for spec in event_sets:
        print(f"Exporting {spec.project} event dialogue...")
        units_by_project[spec.project].extend(export_event_set(spec, project_root, report))
    for spec in system_sets:
        print(f"Exporting {spec.project} system text...")
        units_by_project[spec.project].extend(export_system_set(spec, project_root, report))

    for project, units in units_by_project.items():
        translation_root = project_root / "titles" / project / "translation"
        write_manifest(translation_root, project, units)

    project_ids = ("blue_reflection", "second_light", "blue_reflection_sun", "blue_reflection_ray")
    exceptions = {
        "type": "br_alignment_exceptions",
        "format_version": FORMAT_VERSION,
        "tool_version": TOOL_VERSION,
    }
    for project in project_ids:
        exceptions[project] = {
            "events": report[project]["events"]["exceptions"],
            "system": report[project]["system"]["exceptions"],
        }
    # Keep the main report concise; detailed exception rows live separately.
    for project in project_ids:
        for category in ("events", "system"):
            rows = report[project][category].pop("exceptions")
            report[project][category]["exception_records"] = len(rows)

    report["edit_migration"] = dict(sorted(EDIT_MIGRATION_STATS.items()))
    report["auxiliary_fallback_safety"] = dict(
        sorted(AUXILIARY_FALLBACK_STATS.items())
    )
    reports_dir = project_root / ".local/reports"
    atomic_json(reports_dir / "BR_TRANSLATION_EXPORT_REPORT.json", report)
    if getattr(args, "repair_layouts", False):
        repair_report = {
            "type": "br_ebm_layout_repair_report",
            "format_version": FORMAT_VERSION,
            "tool_version": TOOL_VERSION,
            "project_root": "<PROJECT_ROOT>",
            "status": "ok",
            "runtime_target_adapter": "active_english",
            "runtime_target_roots": {
                "blue_reflection_original": {
                    "events": "PACK01/event/event_en",
                    "system": "PACK02_1/saves_en/text",
                },
                "blue_reflection_quartet": {
                    "events": "PACK11/event/b1/event_en",
                    "system": "PACK12/saves/b1/text_en",
                },
                "second_light_original": {
                    "events": "PACK01/event/event_en",
                    "system": "PACK02/saves/text_en",
                },
            },
            "ebm_files": report["ebm_validation"]["files"],
            "byte_exact_roundtrip": report["ebm_validation"]["byte_exact_roundtrip"],
            "record_structures": report["ebm_validation"]["record_structures"],
            "layout_disambiguations": report["ebm_validation"]["layout_disambiguations"],
            "layout_disambiguation_files": report["ebm_validation"]["layout_disambiguation_files"],
            "edit_migration": report["edit_migration"],
            "translation_records": {
                "blue_reflection": report["blue_reflection"]["events"]["records"] + report["blue_reflection"]["system"]["records"],
                "second_light": report["second_light"]["events"]["records"] + report["second_light"]["system"]["records"],
            },
        }
        atomic_json(
            project_root / ".local/reports/translation/BR_EBM_LAYOUT_REPAIR_REPORT.json",
            repair_report,
        )
    atomic_json(reports_dir / "BR_ALIGNMENT_EXCEPTIONS.json", exceptions)

    print("Translation databases created successfully.")
    print(f"EBM files validated: {report['ebm_validation']['files']}")
    print(f"EBM byte-exact roundtrip: {report['ebm_validation']['byte_exact_roundtrip']}")
    for project in ("blue_reflection", "second_light", "blue_reflection_sun", "blue_reflection_ray"):
        manifest = json.loads(
            (project_root / "titles" / project / "translation/translation_manifest.json").read_text(encoding="utf-8")
        )
        print(f"{project}: {manifest['summary']['units']} units, {manifest['summary']['records']} records")
    return 0



# ---------------------------------------------------------------------------
# Translation import and development PAK build
# ---------------------------------------------------------------------------

BUILD_FORMAT_VERSION = 1
MAX_OUTPUT_STRING_BYTES = 1024 * 1024


@dataclass(frozen=True)
class TargetWorkspaceOverride:
    target_id: str
    archive_stem: str
    workspace_archive_root: Path
    source_manifest: Path
    source_archive_relative: str
    source_archive_sha256: str
    source_archive_bytes: int


def load_target_workspace_overrides(
    project_root: Path, raw_path: Optional[str]
) -> dict[tuple[str, str], TargetWorkspaceOverride]:
    if not raw_path:
        return {}
    path = Path(raw_path).expanduser()
    if not path.is_absolute():
        path = project_root / path
    path = path.resolve()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ToolError(f"Target workspace map is missing: {path}") from exc
    except json.JSONDecodeError as exc:
        raise ToolError(f"Invalid target workspace map {path}: {exc}") from exc
    if data.get("type") != "br_target_workspace_map" or data.get("format_version") != 1:
        raise ToolError(f"Unsupported target workspace map: {path}")
    result: dict[tuple[str, str], TargetWorkspaceOverride] = {}
    for row in data.get("archives", []):
        if not isinstance(row, dict):
            raise ToolError(f"Invalid target workspace map row: {path}")
        target_id = str(row.get("target_id", ""))
        archive_stem = str(row.get("archive_stem", ""))
        root_value = str(row.get("workspace_archive_root", ""))
        manifest_value = str(row.get("source_manifest", ""))
        if not target_id or not archive_stem or not root_value or not manifest_value:
            raise ToolError(f"Incomplete target workspace map row: {row!r}")
        root = (project_root / root_value).resolve()
        manifest = (project_root / manifest_value).resolve()
        try:
            root.relative_to(project_root)
            manifest.relative_to(project_root)
        except ValueError as exc:
            raise ToolError("Target workspace map paths must remain inside the project root") from exc
        if not root.is_dir() or not manifest.is_file():
            raise ToolError(f"Target workspace extraction is incomplete: {root}")
        key = (target_id, archive_stem)
        if key in result:
            raise ToolError(f"Duplicate target workspace override: {target_id}/{archive_stem}")
        result[key] = TargetWorkspaceOverride(
            target_id=target_id,
            archive_stem=archive_stem,
            workspace_archive_root=root,
            source_manifest=manifest,
            source_archive_relative=str(row.get("source_archive_relative", "")),
            source_archive_sha256=str(row.get("source_archive_sha256", "")),
            source_archive_bytes=int(row.get("source_archive_bytes", -1)),
        )
    return result


def resolve_workspace_template(
    project_root: Path,
    target_id: str,
    template_path_value: str,
    overrides: dict[tuple[str, str], TargetWorkspaceOverride],
) -> tuple[str, str, str, str, Path, Path]:
    project, workspace, archive_stem, internal_path, canonical = parse_workspace_template(
        project_root, template_path_value
    )
    override = overrides.get((target_id, archive_stem))
    current = override.workspace_archive_root / internal_path if override else canonical
    return project, workspace, archive_stem, internal_path, canonical, current


def resolve_related_workspace_file(
    project_root: Path,
    target_id: str,
    path_value: str,
    overrides: dict[tuple[str, str], TargetWorkspaceOverride],
) -> Path:
    _, _, archive_stem, internal_path, canonical = parse_workspace_template(project_root, path_value)
    override = overrides.get((target_id, archive_stem))
    return override.workspace_archive_root / internal_path if override else canonical


def encode_xml_text(value: str) -> str:
    """Escape XML attribute text while preserving apostrophes."""
    return (
        value.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


TEXT_ATTR_RE = re.compile(r'(\bText\s*=\s*")([^"]*)(")', re.IGNORECASE)


def serialize_xml_table(table: XMLTable, replacements: dict[int, str]) -> bytes:
    """Replace only Text attributes, preserving all other XML formatting."""
    payload = table.raw[3:] if table.raw.startswith(b"\xef\xbb\xbf") else table.raw
    decoded = payload.decode(table.encoding)
    row_matches = list(ROW_RE.finditer(decoded))
    if len(row_matches) != len(table.rows):
        raise ToolError(f"XML row scan changed unexpectedly: {table.path}")

    edits: list[tuple[int, int, str]] = []
    for row_index, value in replacements.items():
        if row_index < 0 or row_index >= len(row_matches):
            raise ToolError(
                f"XML replacement index out of range: {table.path} row {row_index}"
            )
        match = row_matches[row_index]
        attrs_text = match.group(1)
        attr_match = TEXT_ATTR_RE.search(attrs_text)
        if attr_match is None:
            raise ToolError(
                f"XML row has no Text attribute: {table.path} row {row_index}"
            )
        start = match.start(1) + attr_match.start(2)
        end = match.start(1) + attr_match.end(2)
        edits.append((start, end, encode_xml_text(value)))

    for start, end, escaped in sorted(edits, reverse=True):
        decoded = decoded[:start] + escaped + decoded[end:]

    encoded = decoded.encode(table.encoding)
    if table.raw.startswith(b"\xef\xbb\xbf"):
        encoded = b"\xef\xbb\xbf" + encoded
    return encoded


def atomic_bytes(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
        os.replace(tmp_name, path)
    except Exception:
        try:
            os.unlink(tmp_name)
        except FileNotFoundError:
            pass
        raise


def load_translation_manifest(project_root: Path, project: str) -> tuple[Path, dict[str, Any]]:
    root = project_root / "titles" / project / "translation"
    path = root / "translation_manifest.json"
    if not path.is_file():
        raise ToolError(f"Translation manifest is missing: {path}")
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ToolError(f"Invalid translation manifest {path}: {exc}") from exc
    if manifest.get("type") != "br_translation_project":
        raise ToolError(f"Unsupported translation manifest: {path}")
    return root, manifest


def parse_workspace_template(
    project_root: Path,
    template_path: str,
) -> tuple[str, str, str, Path]:
    """Return project, workspace, archive stem and internal path."""
    path = Path(template_path)
    parts = path.parts
    try:
        titles_index = parts.index("titles")
        workspace_index = parts.index("workspace", titles_index + 2)
        archives_index = parts.index("archives", workspace_index + 2)
    except ValueError as exc:
        raise ToolError(f"Template path is outside a generated archive workspace: {template_path}") from exc
    if archives_index + 2 > len(parts):
        raise ToolError(f"Malformed template path: {template_path}")
    project = parts[titles_index + 1]
    workspace = parts[workspace_index + 1]
    archive_stem = parts[archives_index + 1]
    internal = Path(*parts[archives_index + 2:]).as_posix()
    absolute = project_root / path
    return project, workspace, archive_stem, internal, absolute


def target_archive_relative(target_id: str, archive_stem: str) -> str:
    mapping = {
        ("blue_reflection_original", "PACK01"): "DATA/PACK01.PAK",
        ("blue_reflection_original", "PACK02_1"): "DATA/PACK02_1.PAK",
        ("blue_reflection_original", "PACK02_3"): "DATA/PACK02_3.PAK",
        ("blue_reflection_quartet", "PACK11"): "Data/PACK11.PAK",
        ("blue_reflection_quartet", "PACK12"): "Data/PACK12.PAK",
        ("second_light_original", "PACK01"): "Data/PACK01.PAK",
        ("second_light_original", "PACK02"): "Data/PACK02.PAK",
    }
    try:
        return mapping[(target_id, archive_stem)]
    except KeyError as exc:
        raise ToolError(
            f"No development archive mapping for {target_id}/{archive_stem}"
        ) from exc


def validate_record_text(record: dict[str, Any], unit_path: Path) -> str:
    value = record.get("en")
    if not isinstance(value, str):
        raise ToolError(
            f"Editable en field must be a string: {unit_path} / "
            f"{record.get('logical_id', '<unknown>')}"
        )
    if "\0" in value:
        raise ToolError(
            f"NUL is not allowed in translation text: "
            f"{record.get('logical_id', '<unknown>')}"
        )
    if len(value.encode("utf-8")) > MAX_OUTPUT_STRING_BYTES:
        raise ToolError(
            f"Translation text exceeds {MAX_OUTPUT_STRING_BYTES} UTF-8 bytes: "
            f"{record.get('logical_id', '<unknown>')}"
        )
    return value


def load_unit(path: Path) -> dict[str, Any]:
    try:
        unit = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ToolError(f"Translation unit is missing: {path}") from exc
    except json.JSONDecodeError as exc:
        raise ToolError(f"Invalid translation unit {path}: {exc}") from exc
    if unit.get("type") not in {
        "br_event_translation_unit",
        "br_system_translation_unit",
    }:
        raise ToolError(f"Unsupported translation unit type: {path}")
    if not isinstance(unit.get("records"), list):
        raise ToolError(f"Translation unit has no records array: {path}")
    return unit


def apply_event_unit(
    project_root: Path,
    translation_root: Path,
    unit_path: Path,
    unit: dict[str, Any],
    target_id: str,
    quartet_policy: Optional[dict[str, Any]] = None,
    runtime_canary: bool = False,
    workspace_overrides: Optional[dict[tuple[str, str], TargetWorkspaceOverride]] = None,
) -> tuple[bytes, dict[str, Any]]:
    overrides = workspace_overrides or {}
    target = unit.get("targets", {}).get(target_id)
    if not isinstance(target, dict) or not target.get("template_path"):
        raise ToolError(f"Unit does not support target {target_id}: {unit_path}")
    _, _, _, _, canonical_path, template_path = resolve_workspace_template(
        project_root, target_id, str(target["template_path"]), overrides
    )
    if not template_path.is_file():
        raise ToolError(f"Target template is missing: {template_path}")
    template = parse_ebm(template_path)
    canonical_template = template if template_path == canonical_path else parse_ebm(canonical_path)
    canonical_to_current, canonical_status = align_messages(canonical_template, template)
    texts = [message.text for message in template.messages]

    quartet_jp: Optional[EBMFile] = None
    quartet_en_to_jp: list[Optional[int]] = []
    if target_id == QUARTET_TARGET_ID:
        if quartet_policy is None:
            raise ToolError("Quartet target policy was not loaded")
        value = (
            unit.get("source", {}).get("auxiliary_jp_path")
            or unit.get("source", {}).get("jp_path")
        )
        if not isinstance(value, str):
            raise ToolError(f"Quartet Japanese target template is missing: {unit_path}")
        quartet_jp_path = resolve_related_workspace_file(
            project_root, target_id, value, overrides
        )
        quartet_jp = parse_ebm(quartet_jp_path)
        quartet_en_to_jp, _ = align_messages(template, quartet_jp)

    assignments: dict[int, tuple[str, str]] = {}
    adaptation_counts: Counter[str] = Counter()
    version_alignment_counts: Counter[str] = Counter()
    blank_preserved = 0
    target_template_preserved = 0
    version_unmapped = 0
    version_rebased = 0
    applied = 0

    for record in unit["records"]:
        alignment = record.get("alignment")
        if not isinstance(alignment, dict):
            raise ToolError(f"Record has invalid alignment: {unit_path}")
        target_indices = alignment.get("target_indices")
        if not isinstance(target_indices, dict):
            raise ToolError(f"Record has no target_indices: {unit_path}")
        canonical_index = target_indices.get(target_id)
        if canonical_index is None:
            continue
        if not isinstance(canonical_index, int) or not (0 <= canonical_index < len(canonical_template.messages)):
            raise ToolError(
                f"Canonical target index out of range in {unit_path}: {canonical_index}"
            )
        target_index = canonical_to_current[canonical_index]
        status = canonical_status[canonical_index]
        version_alignment_counts[status] += 1
        # Index-only fallback can silently apply a translation to a newly inserted
        # or reordered record. Preserve the current game's text instead.
        if target_index is None or status in {"unmatched", "missing_target", "index_fallback_review"}:
            version_unmapped += 1
            continue
        if not (0 <= target_index < len(texts)):
            raise ToolError(f"Rebased target index out of range in {unit_path}: {target_index}")
        if template_path != canonical_path or target_index != canonical_index:
            version_rebased += 1

        editable: Optional[str] = validate_record_text(record, unit_path)
        logical_id = str(record.get("logical_id", ""))
        if target_id == QUARTET_TARGET_ID:
            assert quartet_jp is not None and quartet_policy is not None
            quartet_jp_index = quartet_en_to_jp[target_index]
            if quartet_jp_index is None:
                version_unmapped += 1
                continue
            editable, adaptation = adapt_quartet_text(
                record=record,
                editable=editable,
                target_jp=quartet_jp.messages[quartet_jp_index].text,
                target_en=template.messages[target_index].text,
                quartet_policy=quartet_policy,
            )
            adaptation_counts[adaptation] += 1
            if editable is None:
                target_template_preserved += 1
                continue
        if editable == "":
            blank_preserved += 1
            continue
        assert editable is not None
        previous = assignments.get(target_index)
        if previous is not None and previous[0] != editable:
            raise ToolError(
                f"Conflicting translations map to target index {target_index} "
                f"in {unit_path}: {previous[1]} vs {logical_id}"
            )
        assignments[target_index] = (editable, logical_id)

    for index, (editable, _) in assignments.items():
        texts[index] = editable
        applied += 1

    runtime_canary_applied = 0
    output = serialize_ebm(template, texts)
    parsed = parse_ebm_bytes(
        output,
        unit_path,
        forced_layout=(template.d1_len, template.d2_len),
    )
    if len(parsed.messages) != len(template.messages):
        raise ToolError(f"EBM output count mismatch: {unit_path}")
    for index, (editable, _) in assignments.items():
        if parsed.messages[index].text != texts[index]:
            raise ToolError(
                f"EBM output verification failed: {unit_path} index {index}"
            )

    return output, {
        "records": len(unit["records"]),
        "target_records": len(template.messages),
        "applied_records": applied,
        "blank_preserved_records": blank_preserved,
        "target_template_preserved_records": target_template_preserved,
        "quartet_adaptation_counts": dict(sorted(adaptation_counts.items())),
        "runtime_canary_records": runtime_canary_applied,
        "version_rebased_records": version_rebased,
        "version_unmapped_records": version_unmapped,
        "version_alignment_counts": dict(sorted(version_alignment_counts.items())),
        "mapped_records": sum(
            1
            for record in unit["records"]
            if isinstance(record.get("alignment"), dict)
            and isinstance(record["alignment"].get("target_indices"), dict)
            and record["alignment"]["target_indices"].get(target_id) is not None
        ) - version_unmapped,
    }


def apply_system_unit(
    project_root: Path,
    translation_root: Path,
    unit_path: Path,
    unit: dict[str, Any],
    target_id: str,
    quartet_policy: Optional[dict[str, Any]] = None,
    workspace_overrides: Optional[dict[tuple[str, str], TargetWorkspaceOverride]] = None,
) -> tuple[bytes, dict[str, Any]]:
    overrides = workspace_overrides or {}
    target = unit.get("targets", {}).get(target_id)
    if not isinstance(target, dict) or not target.get("template_path"):
        raise ToolError(f"Unit does not support target {target_id}: {unit_path}")
    _, _, _, _, canonical_path, template_path = resolve_workspace_template(
        project_root, target_id, str(target["template_path"]), overrides
    )
    if not template_path.is_file():
        raise ToolError(f"Target XML template is missing: {template_path}")
    template = parse_xml_table(template_path)
    canonical_template = template if template_path == canonical_path else parse_xml_table(canonical_path)
    canonical_to_current, canonical_status = align_rows(canonical_template, template)

    quartet_jp: Optional[XMLTable] = None
    quartet_en_to_jp: list[Optional[int]] = []
    if target_id == QUARTET_TARGET_ID:
        if quartet_policy is None:
            raise ToolError("Quartet target policy was not loaded")
        value = (
            unit.get("source", {}).get("auxiliary_jp_path")
            or unit.get("source", {}).get("jp_path")
        )
        if not isinstance(value, str):
            raise ToolError(f"Quartet Japanese XML target is missing: {unit_path}")
        quartet_jp_path = resolve_related_workspace_file(
            project_root, target_id, value, overrides
        )
        quartet_jp = parse_xml_table(quartet_jp_path)
        quartet_en_to_jp, _ = align_rows(template, quartet_jp)

    assignments: dict[int, tuple[str, str]] = {}
    adaptation_counts: Counter[str] = Counter()
    version_alignment_counts: Counter[str] = Counter()
    blank_preserved = 0
    target_template_preserved = 0
    version_unmapped = 0
    version_rebased = 0

    for record in unit["records"]:
        alignment = record.get("alignment")
        if not isinstance(alignment, dict):
            raise ToolError(f"Record has invalid alignment: {unit_path}")
        target_indices = alignment.get("target_indices")
        if not isinstance(target_indices, dict):
            raise ToolError(f"Record has no target_indices: {unit_path}")
        canonical_index = target_indices.get(target_id)
        if canonical_index is None:
            continue
        if not isinstance(canonical_index, int) or not (0 <= canonical_index < len(canonical_template.rows)):
            raise ToolError(
                f"Canonical target XML row out of range in {unit_path}: {canonical_index}"
            )
        target_index = canonical_to_current[canonical_index]
        status = canonical_status[canonical_index]
        version_alignment_counts[status] += 1
        if target_index is None or status in {"unmatched", "missing_target", "index_fallback_review"}:
            version_unmapped += 1
            continue
        if not (0 <= target_index < len(template.rows)):
            raise ToolError(f"Rebased target XML row out of range in {unit_path}: {target_index}")
        if template_path != canonical_path or target_index != canonical_index:
            version_rebased += 1

        editable: Optional[str] = validate_record_text(record, unit_path)
        logical_id = str(record.get("logical_id", ""))
        if target_id == QUARTET_TARGET_ID:
            assert quartet_jp is not None and quartet_policy is not None
            quartet_jp_index = quartet_en_to_jp[target_index]
            if quartet_jp_index is None:
                version_unmapped += 1
                continue
            editable, adaptation = adapt_quartet_text(
                record=record,
                editable=editable,
                target_jp=quartet_jp.rows[quartet_jp_index].text,
                target_en=template.rows[target_index].text,
                quartet_policy=quartet_policy,
            )
            adaptation_counts[adaptation] += 1
            if editable is None:
                target_template_preserved += 1
                continue
        if editable == "":
            blank_preserved += 1
            continue
        assert editable is not None
        previous = assignments.get(target_index)
        if previous is not None and previous[0] != editable:
            raise ToolError(
                f"Conflicting translations map to XML row {target_index} "
                f"in {unit_path}: {previous[1]} vs {logical_id}"
            )
        assignments[target_index] = (editable, logical_id)

    replacements = {index: value for index, (value, _) in assignments.items()}
    output = serialize_xml_table(template, replacements)
    parsed = parse_xml_table_bytes(output, unit_path)
    if len(parsed.rows) != len(template.rows):
        raise ToolError(f"XML output row count mismatch: {unit_path}")
    for index, value in replacements.items():
        if parsed.rows[index].text != value:
            raise ToolError(
                f"XML output verification failed: {unit_path} row {index}"
            )

    return output, {
        "records": len(unit["records"]),
        "target_records": len(template.rows),
        "applied_records": len(replacements),
        "blank_preserved_records": blank_preserved,
        "target_template_preserved_records": target_template_preserved,
        "quartet_adaptation_counts": dict(sorted(adaptation_counts.items())),
        "version_rebased_records": version_rebased,
        "version_unmapped_records": version_unmapped,
        "version_alignment_counts": dict(sorted(version_alignment_counts.items())),
        "mapped_records": sum(
            1
            for record in unit["records"]
            if isinstance(record.get("alignment"), dict)
            and isinstance(record["alignment"].get("target_indices"), dict)
            and record["alignment"]["target_indices"].get(target_id) is not None
        ) - version_unmapped,
    }


def development_targets() -> dict[str, str]:
    return {
        "blue_reflection_original": "blue_reflection",
        "blue_reflection_quartet": "blue_reflection",
        "second_light_original": "second_light",
    }



TITLE_MARKER_MAX_LENGTH = 48

TITLE_MARKER_LAYOUTS: dict[str, tuple[dict[str, str], ...]] = {
    "blue_reflection_original": (
        {
            "project": "blue_reflection",
            "workspace": "original",
            "archive_stem": "PACK02_1",
            "internal_path": "saves_en/ui/a17_title/uil_title02.xml",
            "layout_kind": "blue_reflection_a17",
            "runtime_locale": "english",
        },
        {
            "project": "blue_reflection",
            "workspace": "original",
            "archive_stem": "PACK02_1",
            "internal_path": "saves_en/ui/a18_title/uil_a18_title02.xml",
            "layout_kind": "blue_reflection_a18",
            "runtime_locale": "english",
        },
        {
            "project": "blue_reflection",
            "workspace": "original",
            "archive_stem": "PACK02_3",
            "internal_path": "saves_jp/ui/a17_title/uil_title02.xml",
            "layout_kind": "blue_reflection_a17",
            "runtime_locale": "japanese",
        },
        {
            "project": "blue_reflection",
            "workspace": "original",
            "archive_stem": "PACK02_3",
            "internal_path": "saves_jp/ui/a18_title/uil_a18_title02.xml",
            "layout_kind": "blue_reflection_a18",
            "runtime_locale": "japanese",
        },
    ),
    "blue_reflection_quartet": (
        {
            "project": "blue_reflection",
            "workspace": "quartet",
            "archive_stem": "PACK12",
            "internal_path": "saves/b1/ui/a17_title/uil_title02.xml",
            "layout_kind": "blue_reflection_a17",
        },
        {
            "project": "blue_reflection",
            "workspace": "quartet",
            "archive_stem": "PACK12",
            "internal_path": "saves/b1/ui/a18_title/uil_a18_title02.xml",
            "layout_kind": "blue_reflection_a18",
        },
    ),
    "second_light_original": tuple(
        {
            "project": "second_light",
            "workspace": "original",
            "archive_stem": "PACK02",
            "internal_path": f"saves/{language}/seed_title/uil_seed_title.xml",
            "layout_kind": "second_light",
        }
        for language in ("ui_cmn", "ui_en", "ui_sc", "ui_tc")
    ),
}


def validate_title_marker(value: str | None) -> str | None:
    if value is None:
        return None
    marker = value.strip()
    if marker.lower() in {"", "none", "off", "disabled"}:
        return None
    if len(marker) > TITLE_MARKER_MAX_LENGTH:
        raise ToolError(
            f"Title marker exceeds {TITLE_MARKER_MAX_LENGTH} characters"
        )
    if any(ord(ch) < 0x20 or ord(ch) == 0x7F for ch in marker):
        raise ToolError("Title marker contains a control character")
    return marker


def xml_attr_escape(value: str) -> str:
    return (
        value.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def encode_layout_text(
    original: bytes,
    text: str,
    encoding: str,
) -> bytes:
    encoded = text.encode(encoding)
    if original.startswith(b"\xef\xbb\xbf"):
        encoded = b"\xef\xbb\xbf" + encoded
    return encoded


BR_COPYRIGHT_RE = re.compile(
    r'(?m)^(?P<indent>[ \t]*)<image\b'
    r'(?=[^>\r\n]*\bname="copyright")'
    r'[^>\r\n]*/>[ \t]*(?P<eol>\r?\n|$)'
)

SECOND_LIGHT_COPYRIGHT_RE = re.compile(
    r'(?ms)^(?P<indent>[ \t]*)<node\b'
    r'(?=[^>\r\n]*\bname="copyright")'
    r'(?P<open>[^>\r\n]*>)'
    r'(?P<body>.*?)'
    r'^(?P=indent)</node>[ \t]*(?P<eol>\r?\n|$)'
)


def patch_title_marker_layout(
    data: bytes,
    path: Path,
    layout_kind: str,
    marker: str,
) -> bytes:
    """Replace the rendered copyright with an animated text marker.

    Blue Reflection keeps the runtime animation binding by preserving a node
    named ``copyright``. Second Light already has a proven text-capable
    ``patch`` node, so the marker is placed there while the image copyright
    node is left empty. No G1T texture is modified.
    """
    text, encoding = decode_xml_bytes(data, path)
    escaped = xml_attr_escape(marker)

    if layout_kind in {"blue_reflection_a17", "blue_reflection_a18"}:
        matches = list(BR_COPYRIGHT_RE.finditer(text))
        if len(matches) != 1:
            raise ToolError(
                f"Expected one Blue Reflection copyright image in {path}, "
                f"found {len(matches)}"
            )
        match = matches[0]
        indent = match.group("indent")
        eol = match.group("eol")
        node_visible = (
            ' visible="false" viewer_visible="true"'
            if layout_kind == "blue_reflection_a18"
            else ' visible="true" viewer_visible="true"'
        )
        y = "676.00" if layout_kind == "blue_reflection_a17" else "678.00"
        replacement = (
            f'{indent}<node name="copyright" pos="0.00, 0.00, 0.00"'
            f'{node_visible}>{eol}'
            f'{indent}\t<text text="{escaped}" name="mod_marker" '
            f'align="center" font_size="22.00" '
            f'color="255.00, 255.00, 255.00, 255.00" '
            f'bold_size="1.00" drop_shadow="true" '
            f'pos="640.00, {y}, 0.00" '
            f'visible="true" viewer_visible="true"/>{eol}'
            f'{indent}</node>{eol}'
        )
        patched = text[:match.start()] + replacement + text[match.end():]

    elif layout_kind == "second_light":
        copyright_matches = list(SECOND_LIGHT_COPYRIGHT_RE.finditer(text))
        if len(copyright_matches) != 1:
            raise ToolError(
                f"Expected one Second Light copyright node in {path}, "
                f"found {len(copyright_matches)}"
            )
        copyright = copyright_matches[0]
        empty_copyright = (
            f'{copyright.group("indent")}<node name="copyright" '
            f'visible="false" viewer_visible="true">'
            f'{copyright.group("eol")}'
            f'{copyright.group("indent")}</node>{copyright.group("eol")}'
        )
        patched = (
            text[:copyright.start()] + empty_copyright + text[copyright.end():]
        )

        patch_node_re = re.compile(
            r'(?ms)^(?P<indent>[ \t]*)<node\b'
            r'(?=[^>\r\n]*\bname="patch")'
            r'(?P<open>[^>\r\n]*>)'
            r'(?P<body>.*?)'
            r'^(?P=indent)</node>[ \t]*(?P<eol>\r?\n|$)'
        )
        patch_matches = list(patch_node_re.finditer(patched))
        if len(patch_matches) != 1:
            raise ToolError(
                f"Expected one Second Light patch node in {path}, "
                f"found {len(patch_matches)}"
            )
        patch = patch_matches[0]
        child_indent = patch.group("indent") + "\t"
        replacement = (
            f'{patch.group("indent")}<node{patch.group("open")}'
            f'{patch.group("eol")}'
            f'{child_indent}<text text="{escaped}" name="mod_marker" '
            f'align="left" visible="true" viewer_visible="true" '
            f'font="MainFont01" font_size="16.000" '
            f'font_color="234.000, 234.000, 234.000, 255.000" '
            f'drop_shadow="true" pos="-1162.000, -16.000, 0.000"/>'
            f'{patch.group("eol")}'
            f'{patch.group("indent")}</node>{patch.group("eol")}'
        )
        patched = patched[:patch.start()] + replacement + patched[patch.end():]
    else:
        raise ToolError(f"Unsupported title marker layout kind: {layout_kind}")

    if marker not in html.unescape(patched):
        raise ToolError(f"Title marker was not inserted into {path}")
    if 'style="gen_a17_title01_copyright"' in patched:
        raise ToolError(f"A17 copyright image remained active in {path}")
    if 'style="gen_a18_title01_copyright"' in patched:
        raise ToolError(f"A18 copyright image remained active in {path}")
    if layout_kind == "second_light" and "gen_seed_Title_copyrights" in patched:
        raise ToolError(f"Second Light copyright image remained active in {path}")
    return encode_layout_text(data, patched, encoding)


def ensure_archive_plan(
    archive_plans: dict[tuple[str, str], dict[str, Any]],
    target_id: str,
    project: str,
    workspace: str,
    archive_stem: str,
    project_root: Path,
    workspace_overrides: Optional[dict[tuple[str, str], TargetWorkspaceOverride]] = None,
) -> dict[str, Any]:
    archive_key = (target_id, archive_stem)
    overrides = workspace_overrides or {}
    override = overrides.get(archive_key)
    if override:
        workspace_root = rel_posix(override.workspace_archive_root, project_root)
        source_manifest = rel_posix(override.source_manifest, project_root)
        source_policy = "current_installation_baseline_extraction"
        source_archive_sha256 = override.source_archive_sha256
        source_archive_bytes = override.source_archive_bytes
    else:
        workspace_root = f"titles/{project}/workspace/{workspace}/archives/{archive_stem}"
        source_manifest = (
            f"titles/{project}/workspace/{workspace}/archives/"
            f"{archive_stem}/{archive_stem}.json"
        )
        source_policy = "canonical_development_workspace"
        source_archive_sha256 = ""
        source_archive_bytes = -1
    return archive_plans.setdefault(
        archive_key,
        {
            "target_id": target_id,
            "project": project,
            "workspace": workspace,
            "archive_stem": archive_stem,
            "archive_relative_path": target_archive_relative(
                target_id, archive_stem
            ),
            "workspace_archive_root": workspace_root,
            "source_manifest": source_manifest,
            "source_policy": source_policy,
            "source_archive_sha256": source_archive_sha256,
            "source_archive_bytes": source_archive_bytes,
            "files": [],
        },
    )


def add_title_marker_outputs(
    project_root: Path,
    loose_root: Path,
    target_id: str,
    marker: str | None,
    archive_plans: dict[tuple[str, str], dict[str, Any]],
    target_report: dict[str, Any],
    workspace_overrides: Optional[dict[tuple[str, str], TargetWorkspaceOverride]] = None,
) -> None:
    if marker is None:
        return

    specs = TITLE_MARKER_LAYOUTS.get(target_id)
    if not specs:
        raise ToolError(f"No title marker layouts configured for {target_id}")

    for spec in specs:
        project = spec["project"]
        workspace = spec["workspace"]
        archive_stem = spec["archive_stem"]
        internal_path = spec["internal_path"]
        override = (workspace_overrides or {}).get((target_id, archive_stem))
        template_path = (
            override.workspace_archive_root / internal_path
            if override
            else project_root / "titles" / project / "workspace" / workspace
            / "archives" / archive_stem / internal_path
        )
        if not template_path.is_file():
            raise ToolError(f"Title marker template is missing: {template_path}")

        original = template_path.read_bytes()
        output = patch_title_marker_layout(
            original,
            template_path,
            spec["layout_kind"],
            marker,
        )
        output_path = loose_root / target_id / archive_stem / internal_path
        atomic_bytes(output_path, output)

        template_sha = hashlib.sha256(original).hexdigest()
        output_sha = hashlib.sha256(output).hexdigest()
        if output_sha == template_sha:
            raise ToolError(f"Title marker did not change {template_path}")

        file_entry = {
            "unit_path": None,
            "unit_type": "br_title_marker_layout",
            "logical_path": internal_path,
            "archive_stem": archive_stem,
            "archive_relative_path": target_archive_relative(
                target_id, archive_stem
            ),
            "internal_path": internal_path,
            "template_path": rel_posix(template_path, project_root),
            "template_sha256": template_sha,
            "output_path": rel_posix(output_path, project_root),
            "output_sha256": output_sha,
            "output_bytes": len(output),
            "changed": True,
            "records": 0,
            "target_records": 0,
            "applied_records": 0,
            "blank_preserved_records": 0,
            "mapped_records": 0,
            "title_marker": marker,
            "layout_kind": spec["layout_kind"],
        }
        target_report["files"].append(file_entry)
        target_report["output_files"] += 1
        target_report["changed_files"] += 1
        target_report["title_marker_files"] += 1

        archive = ensure_archive_plan(
            archive_plans,
            target_id,
            project,
            workspace,
            archive_stem,
            project_root,
            workspace_overrides,
        )
        archive["files"].append(
            {
                "internal_path": internal_path,
                "output_path": rel_posix(output_path, project_root),
                "output_sha256": output_sha,
                "template_sha256": template_sha,
                "operation": "title_marker_layout",
            }
        )



QUICK_RUNTIME_CANARIES: dict[str, dict[str, Any]] = {
    "blue_reflection_original": {
        "project": "blue_reflection",
        "workspace": "original",
        "archive_stem": "PACK02_1",
        "internal_paths": (
            "saves_en/text/str_npc_s77_mess.xml",
            "saves_en/text/strcombineall.xml",
        ),
        "string_no": "35192864",
    },
    "blue_reflection_quartet": {
        "project": "blue_reflection",
        "workspace": "quartet",
        "archive_stem": "PACK12",
        "internal_paths": (
            "saves/b1/text_en/str_npc_s77_mess.xml",
            "saves/b1/text_en/strcombineall.xml",
        ),
        "string_no": "35192864",
    },
}


def patch_xml_runtime_canary(
    data: bytes,
    path: Path,
    string_no: str,
) -> tuple[bytes, int, str]:
    table = parse_xml_table_bytes(data, path)
    matches = [row for row in table.rows if row.string_no == string_no]
    if len(matches) != 1:
        raise ToolError(
            f"Expected one runtime-canary String_No={string_no} in {path}, "
            f"found {len(matches)}"
        )
    row = matches[0]
    suffix = " [UNBURGER MOD]"
    value = row.text if row.text.endswith(suffix) else row.text + suffix
    output = serialize_xml_table(table, {row.index: value})
    parsed = parse_xml_table_bytes(output, path)
    if parsed.rows[row.index].text != value:
        raise ToolError(f"Runtime canary verification failed: {path}")
    return output, row.index, value


def add_active_runtime_canary_output(
    project_root: Path,
    loose_root: Path,
    target_id: str,
    enabled: bool,
    archive_plans: dict[tuple[str, str], dict[str, Any]],
    target_report: dict[str, Any],
    workspace_overrides: Optional[dict[tuple[str, str], TargetWorkspaceOverride]] = None,
) -> None:
    """Patch the first dialogue available from the user's test save.

    Both the dedicated NPC table and strcombineall are patched so the canary is
    visible regardless of which English system-text table the runtime selects.
    """
    if not enabled:
        return
    spec = QUICK_RUNTIME_CANARIES.get(target_id)
    if spec is None:
        return

    project = str(spec["project"])
    workspace = str(spec["workspace"])
    archive_stem = str(spec["archive_stem"])
    string_no = str(spec["string_no"])
    archive = ensure_archive_plan(
        archive_plans, target_id, project, workspace, archive_stem,
        project_root, workspace_overrides
    )

    for internal_path_value in spec["internal_paths"]:
        internal_path = str(internal_path_value)
        override = (workspace_overrides or {}).get((target_id, archive_stem))
        template_path = (
            override.workspace_archive_root / internal_path
            if override
            else project_root / "titles" / project / "workspace" / workspace
            / "archives" / archive_stem / internal_path
        )
        if not template_path.is_file():
            raise ToolError(f"Quick runtime-canary template is missing: {template_path}")

        output_path = loose_root / target_id / archive_stem / internal_path
        base_data = output_path.read_bytes() if output_path.is_file() else template_path.read_bytes()
        output, row_index, canary_text = patch_xml_runtime_canary(
            base_data, template_path, string_no
        )
        atomic_bytes(output_path, output)

        template_sha = sha256_file(template_path)
        output_sha = hashlib.sha256(output).hexdigest()
        existing_file = next(
            (entry for entry in target_report["files"]
             if entry.get("archive_stem") == archive_stem
             and entry.get("internal_path") == internal_path),
            None,
        )
        if existing_file is None:
            existing_file = {
                "unit_path": None,
                "unit_type": "br_quick_runtime_canary",
                "logical_path": internal_path,
                "archive_stem": archive_stem,
                "archive_relative_path": target_archive_relative(target_id, archive_stem),
                "internal_path": internal_path,
                "template_path": rel_posix(template_path, project_root),
                "template_sha256": template_sha,
                "records": 0,
                "target_records": 0,
                "applied_records": 0,
                "blank_preserved_records": 0,
                "mapped_records": 0,
                "changed": True,
            }
            target_report["files"].append(existing_file)
            target_report["output_files"] += 1
            target_report["changed_files"] += 1
        elif not existing_file.get("changed"):
            target_report["changed_files"] += 1

        existing_file.update({
            "output_path": rel_posix(output_path, project_root),
            "output_sha256": output_sha,
            "output_bytes": len(output),
            "changed": True,
            "runtime_canary_records": 1,
            "runtime_locale": "english",
            "string_no": string_no,
            "row_index": row_index,
            "canary_text": canary_text,
            "canary_profile": "saved_game_tardy_kashiwagi",
        })

        plan_file = next(
            (entry for entry in archive["files"]
             if entry.get("internal_path") == internal_path),
            None,
        )
        if plan_file is None:
            archive["files"].append({
                "internal_path": internal_path,
                "output_path": rel_posix(output_path, project_root),
                "output_sha256": output_sha,
                "template_sha256": template_sha,
                "operation": "quick_runtime_canary",
            })
        else:
            plan_file.update({
                "output_path": rel_posix(output_path, project_root),
                "output_sha256": output_sha,
                "template_sha256": template_sha,
                "operation": "translation_plus_quick_runtime_canary",
            })

    target_report["runtime_canary_records"] += 1


def cmd_build_loose(args: argparse.Namespace) -> int:
    project_root = Path(args.project_root).expanduser().resolve()
    build_root = project_root / ".local/build/translation"
    loose_root = build_root / "loose"
    reports_root = project_root / ".local/reports/translation"
    reports_root.mkdir(parents=True, exist_ok=True)

    if loose_root.exists():
        shutil.rmtree(loose_root)
    loose_root.mkdir(parents=True)

    target_filter = set(args.target or development_targets())
    unknown = target_filter - set(development_targets())
    workspace_overrides = load_target_workspace_overrides(
        project_root, getattr(args, "target_workspace_map", None)
    )
    title_marker = validate_title_marker(args.title_marker)
    runtime_canary = bool(args.runtime_canary)
    if unknown:
        raise ToolError(f"Unsupported translation build target(s): {', '.join(sorted(unknown))}")
    quartet_policy = (
        load_quartet_target_policy(project_root)
        if QUARTET_TARGET_ID in target_filter
        else None
    )

    report: dict[str, Any] = {
        "type": "br_translation_loose_build_report",
        "format_version": BUILD_FORMAT_VERSION,
        "tool_version": TOOL_VERSION,
        "project_root": "<PROJECT_ROOT>",
        "status": "ok",
        "runtime_target_adapter": "active_english",
        "title_marker": title_marker,
        "runtime_canary": runtime_canary,
        "targets": {},
        "summary": {
            "units": 0,
            "output_files": 0,
            "changed_files": 0,
            "records": 0,
            "applied_records": 0,
            "blank_preserved_records": 0,
            "target_template_preserved_records": 0,
            "quartet_adapted_records": 0,
            "version_rebased_records": 0,
            "version_unmapped_records": 0,
            "title_marker_files": 0,
            "runtime_canary_records": 0,
            "errors": 0,
        },
        "errors": [],
    }
    archive_plans: dict[tuple[str, str], dict[str, Any]] = {}

    for target_id, project in development_targets().items():
        if target_id not in target_filter:
            continue
        translation_root, manifest = load_translation_manifest(project_root, project)
        target_report = {
            "project": project,
            "units": 0,
            "output_files": 0,
            "changed_files": 0,
            "records": 0,
            "applied_records": 0,
            "blank_preserved_records": 0,
            "target_template_preserved_records": 0,
            "version_rebased_records": 0,
            "version_unmapped_records": 0,
            "version_alignment_counts": {},
            "quartet_adaptation_counts": {},
            "title_marker_files": 0,
            "runtime_canary_records": 0,
            "archives": {},
            "files": [],
        }
        report["targets"][target_id] = target_report

        for summary in manifest.get("units", []):
            if not isinstance(summary, dict) or not isinstance(summary.get("path"), str):
                raise ToolError(f"Invalid unit summary in {project} manifest")
            unit_path = translation_root / summary["path"]
            unit = load_unit(unit_path)
            target_info = unit.get("targets", {}).get(target_id)
            if not isinstance(target_info, dict) or not target_info.get("template_path"):
                continue

            _, workspace, archive_stem, internal_path, canonical_template_path, template_path = resolve_workspace_template(
                project_root, target_id, target_info["template_path"], workspace_overrides
            )
            if not template_path.is_file():
                raise ToolError(f"Target template is missing: {template_path}")

            if unit["type"] == "br_event_translation_unit":
                output, stats = apply_event_unit(
                    project_root,
                    translation_root,
                    unit_path,
                    unit,
                    target_id,
                    quartet_policy=quartet_policy,
                    workspace_overrides=workspace_overrides,
                )
            else:
                output, stats = apply_system_unit(
                    project_root,
                    translation_root,
                    unit_path,
                    unit,
                    target_id,
                    quartet_policy=quartet_policy,
                    workspace_overrides=workspace_overrides,
                )

            output_path = loose_root / target_id / archive_stem / internal_path
            atomic_bytes(output_path, output)
            template_sha = sha256_file(template_path)
            output_sha = hashlib.sha256(output).hexdigest()
            changed = output_sha != template_sha

            file_entry = {
                "unit_path": rel_posix(unit_path, project_root),
                "unit_type": unit["type"],
                "logical_path": unit.get("logical_path"),
                "archive_stem": archive_stem,
                "archive_relative_path": target_archive_relative(target_id, archive_stem),
                "internal_path": internal_path,
                "template_path": rel_posix(template_path, project_root),
                "template_sha256": template_sha,
                "output_path": rel_posix(output_path, project_root),
                "output_sha256": output_sha,
                "output_bytes": len(output),
                "changed": changed,
                **stats,
            }
            target_report["files"].append(file_entry)
            target_report["units"] += 1
            target_report["output_files"] += 1
            target_report["records"] += stats["records"]
            target_report["applied_records"] += stats["applied_records"]
            target_report["blank_preserved_records"] += stats["blank_preserved_records"]
            target_report["target_template_preserved_records"] += stats.get(
                "target_template_preserved_records", 0
            )
            target_report["version_rebased_records"] += stats.get("version_rebased_records", 0)
            target_report["version_unmapped_records"] += stats.get("version_unmapped_records", 0)
            version_alignment_totals = Counter(target_report["version_alignment_counts"])
            version_alignment_totals.update(stats.get("version_alignment_counts", {}))
            target_report["version_alignment_counts"] = dict(sorted(version_alignment_totals.items()))
            adaptation_totals = Counter(target_report["quartet_adaptation_counts"])
            adaptation_totals.update(stats.get("quartet_adaptation_counts", {}))
            target_report["quartet_adaptation_counts"] = dict(
                sorted(adaptation_totals.items())
            )
            target_report["runtime_canary_records"] += stats.get(
                "runtime_canary_records", 0
            )
            if changed:
                target_report["changed_files"] += 1

            archive = ensure_archive_plan(
                archive_plans,
                target_id,
                project,
                workspace,
                archive_stem,
                project_root,
                workspace_overrides,
            )
            if changed:
                archive["files"].append(
                    {
                        "internal_path": internal_path,
                        "output_path": rel_posix(output_path, project_root),
                        "output_sha256": output_sha,
                        "template_sha256": template_sha,
                    }
                )

        add_title_marker_outputs(
            project_root,
            loose_root,
            target_id,
            title_marker,
            archive_plans,
            target_report,
            workspace_overrides,
        )
        add_active_runtime_canary_output(
            project_root,
            loose_root,
            target_id,
            runtime_canary,
            archive_plans,
            target_report,
            workspace_overrides,
        )

        archive_counts = {}
        for (archive_target, archive_stem), plan in sorted(archive_plans.items()):
            if archive_target != target_id:
                continue
            archive_counts[archive_stem] = {
                "archive_relative_path": plan["archive_relative_path"],
                "changed_files": len(plan["files"]),
            }
        target_report["archives"] = archive_counts

        for key in (
            "units", "output_files", "changed_files", "records",
            "applied_records", "blank_preserved_records",
            "target_template_preserved_records",
            "version_rebased_records", "version_unmapped_records",
            "title_marker_files", "runtime_canary_records",
        ):
            report["summary"][key] += target_report[key]
        report["summary"]["quartet_adapted_records"] += sum(
            count
            for action, count in target_report["quartet_adaptation_counts"].items()
            if action not in {"shared_exact", "redacted_target_import_allowed"}
        )

    plan = {
        "type": "br_translation_repack_plan",
        "format_version": BUILD_FORMAT_VERSION,
        "tool_version": TOOL_VERSION,
        "generated_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "title_marker": title_marker,
        "runtime_canary": runtime_canary,
        "archives": sorted(
            archive_plans.values(),
            key=lambda item: (item["target_id"], item["archive_stem"]),
        ),
    }
    atomic_json(build_root / "TRANSLATION_REPACK_PLAN.json", plan)
    atomic_json(reports_root / "BR_TRANSLATION_LOOSE_BUILD_REPORT.json", report)

    print("Translation loose-file build completed.")
    print(f"Units: {report['summary']['units']}")
    print(f"Output files: {report['summary']['output_files']}")
    print(f"Changed files: {report['summary']['changed_files']}")
    print(f"Applied records: {report['summary']['applied_records']}")
    print(f"Blank/manual records preserved from JP templates: "
          f"{report['summary']['blank_preserved_records']}")
    print(f"Quartet target-template records preserved: "
          f"{report['summary']['target_template_preserved_records']}")
    print(f"Quartet target adaptations applied: "
          f"{report['summary']['quartet_adapted_records']}")
    print(f"Title marker files: {report['summary']['title_marker_files']}")
    print(f"Title marker: {title_marker or '(disabled)'}")
    print(
        f"Runtime canary records: "
        f"{report['summary']['runtime_canary_records']}"
    )
    return 0


def hardlink_clone_tree(source: Path, destination: Path) -> None:
    if destination.exists():
        shutil.rmtree(destination)
    destination.mkdir(parents=True)
    for path in sorted(source.rglob("*")):
        relative = path.relative_to(source)
        target = destination / relative
        if path.is_dir():
            target.mkdir(parents=True, exist_ok=True)
        elif path.is_symlink():
            target.parent.mkdir(parents=True, exist_ok=True)
            target.symlink_to(os.readlink(path))
        elif path.is_file():
            target.parent.mkdir(parents=True, exist_ok=True)
            try:
                os.link(path, target)
            except OSError:
                shutil.copy2(path, target)


def overlay_file(source: Path, destination: Path) -> None:
    data = source.read_bytes()
    atomic_bytes(destination, data)


def normalize_archive_entry_path(name: str) -> str:
    """Convert gust_pak's archive-root notation to a safe relative path.

    gust_pak lists internal entries with one or more leading backslashes.
    Those separators describe the root of the archive, not an operating-system
    absolute path. Only that leading archive-root marker is stripped.
    """
    normalized = name.replace("\\", "/")
    normalized = normalized.lstrip("/")

    # A Windows drive prefix remains unsafe after archive-root stripping.
    if re.match(r"^[A-Za-z]:", normalized):
        raise ToolError(f"Unsafe archive entry path reported by gust_pak: {name!r}")

    parts = normalized.split("/")
    if not normalized or any(part in {"", ".", ".."} for part in parts):
        raise ToolError(f"Unsafe archive entry path reported by gust_pak: {name!r}")

    return "/".join(parts)


def list_pak_entries(
    gust_pak: Path,
    pak_path: Path,
    cwd: Path,
    timeout: int,
) -> tuple[list[str], list[str]]:
    """Use gust_pak itself as the authoritative archive-list parser."""
    process = subprocess.run(
        [str(gust_pak), "-l", str(pak_path)],
        cwd=cwd,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    if process.returncode != 0:
        raise ToolError(
            f"gust_pak list failed for {pak_path}: "
            f"{process.stderr or process.stdout}"
        )

    entries: list[str] = []
    seen: set[str] = set()
    for line in process.stdout.splitlines():
        if len(line) < 20:
            continue
        offset = line[0:9]
        size = line[10:18]
        if (
            line[9:10] != " "
            or line[18:19] != " "
            or any(ch not in "0123456789abcdefABCDEF" for ch in offset)
            or any(ch not in "0123456789abcdefABCDEF" for ch in size)
        ):
            continue
        raw_name = line[19:]
        if raw_name.endswith("*") or raw_name.endswith(" "):
            raw_name = raw_name[:-1]
        name = normalize_archive_entry_path(raw_name)
        if name in seen:
            raise ToolError(f"Duplicate path in rebuilt PAK listing: {name}")
        seen.add(name)
        entries.append(name)

    if not entries:
        raise ToolError(f"gust_pak returned an empty entry list for {pak_path}")
    return entries, process.stdout.splitlines()[-10:]


def compare_repacked_extraction(
    expected_root: Path,
    actual_root: Path,
    entry_names: list[str],
) -> tuple[int, list[dict[str, str]]]:
    failures: list[dict[str, str]] = []
    checked = 0
    for name in entry_names:
        relative = Path(name)
        expected = expected_root / relative
        actual = actual_root / relative
        if not expected.is_file():
            failures.append({"path": name, "error": "expected staged file missing"})
            continue
        if not actual.is_file():
            failures.append({"path": name, "error": "re-extracted file missing"})
            continue
        checked += 1
        if sha256_file(expected) != sha256_file(actual):
            failures.append({"path": name, "error": "content hash mismatch"})
    return checked, failures


def newly_created_pak(stage: Path, before: set[Path], archive_stem: str) -> Path:
    after = {
        path.relative_to(stage)
        for path in stage.rglob("*")
        if path.is_file() and path.suffix.lower() == ".pak"
    }
    created = sorted(after - before)
    if len(created) != 1:
        rendered = ", ".join(path.as_posix() for path in created) or "(none)"
        raise ToolError(
            f"Expected exactly one PAK from gust_pak for {archive_stem}, "
            f"found {len(created)}: {rendered}"
        )
    return stage / created[0]


def cmd_repack(args: argparse.Namespace) -> int:
    project_root = Path(args.project_root).expanduser().resolve()
    gust_pak = Path(args.gust_pak).expanduser().resolve()
    if not gust_pak.is_file() or not os.access(gust_pak, os.X_OK):
        raise ToolError(f"gust_pak is not executable: {gust_pak}")

    build_root = project_root / ".local/build/translation"
    plan_path = build_root / "TRANSLATION_REPACK_PLAN.json"
    if not plan_path.is_file():
        raise ToolError("Loose build plan is missing. Run build-loose first.")
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    if plan.get("type") != "br_translation_repack_plan":
        raise ToolError(f"Invalid repack plan: {plan_path}")

    repack_root = build_root / "repack"
    archive_output_root = build_root / "archives"
    reports_root = project_root / ".local/reports/translation"
    reports_root.mkdir(parents=True, exist_ok=True)
    if repack_root.exists():
        shutil.rmtree(repack_root)
    repack_root.mkdir(parents=True)
    if archive_output_root.exists():
        shutil.rmtree(archive_output_root)
    archive_output_root.mkdir(parents=True)

    report: dict[str, Any] = {
        "type": "br_translation_pak_repack_report",
        "format_version": BUILD_FORMAT_VERSION,
        "tool_version": TOOL_VERSION,
        "project_root": "<PROJECT_ROOT>",
        "status": "ok",
        "gust_pak_sha256": sha256_file(gust_pak),
        "archives": [],
        "summary": {
            "archives": 0,
            "entries_checked": 0,
            "changed_files": 0,
            "failures": 0,
        },
    }

    for archive in plan.get("archives", []):
        target_id = archive["target_id"]
        archive_stem = archive["archive_stem"]
        source_root = project_root / archive["workspace_archive_root"]
        source_manifest = project_root / archive["source_manifest"]
        if not source_root.is_dir() or not source_manifest.is_file():
            raise ToolError(f"Workspace archive is missing: {source_root}")

        stage = repack_root / target_id / archive_stem
        hardlink_clone_tree(source_root, stage)
        for file_entry in archive.get("files", []):
            overlay_file(
                project_root / file_entry["output_path"],
                stage / file_entry["internal_path"],
            )

        stage_manifest = stage / source_manifest.name
        if not stage_manifest.is_file():
            raise ToolError(f"PAK reconstruction manifest is missing: {stage_manifest}")

        # The reconstruction manifest belongs to gust_pak. Do not parse,
        # normalize or rewrite it with Python's stricter JSON implementation.
        pak_files_before = {
            path.relative_to(stage)
            for path in stage.rglob("*")
            if path.is_file() and path.suffix.lower() == ".pak"
        }
        process = subprocess.run(
            [str(gust_pak), str(stage_manifest)],
            cwd=stage,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=args.timeout,
        )
        if process.returncode != 0:
            raise ToolError(
                f"gust_pak repack failed for {target_id}/{archive_stem}: "
                f"{process.stderr or process.stdout}"
            )

        built_pak = newly_created_pak(stage, pak_files_before, archive_stem)
        output_name = built_pak.name
        entry_names, listing_tail = list_pak_entries(
            gust_pak, built_pak, stage, args.timeout
        )

        final_pak = (
            archive_output_root / target_id / archive["archive_relative_path"]
        )
        final_pak.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(built_pak, final_pak)

        verify_root = Path(
            tempfile.mkdtemp(
                prefix=f"verify-{target_id}-{archive_stem}-",
                dir=repack_root,
            )
        )
        try:
            verify_pak = verify_root / output_name
            try:
                os.link(final_pak, verify_pak)
            except OSError:
                shutil.copy2(final_pak, verify_pak)
            verify_process = subprocess.run(
                [str(gust_pak), str(verify_pak)],
                cwd=verify_root,
                stdin=subprocess.DEVNULL,
                capture_output=True,
                text=True,
                timeout=args.timeout,
            )
            if verify_process.returncode != 0:
                raise ToolError(
                    f"gust_pak verification extract failed for "
                    f"{target_id}/{archive_stem}: "
                    f"{verify_process.stderr or verify_process.stdout}"
                )
            verify_pak.unlink(missing_ok=True)
            checked, failures = compare_repacked_extraction(
                stage, verify_root, entry_names
            )
        finally:
            shutil.rmtree(verify_root, ignore_errors=True)

        entry = {
            "target_id": target_id,
            "archive_stem": archive_stem,
            "archive_relative_path": archive["archive_relative_path"],
            "output_path": rel_posix(final_pak, project_root),
            "output_sha256": sha256_file(final_pak),
            "output_bytes": final_pak.stat().st_size,
            "changed_files": len(archive.get("files", [])),
            "listed_entries": len(entry_names),
            "entries_checked": checked,
            "failures": failures,
            "repack_stdout_tail": process.stdout.splitlines()[-10:],
            "listing_stdout_tail": listing_tail,
            "manifest_policy": "opaque_gust_pak_input",
        }
        report["archives"].append(entry)
        report["summary"]["archives"] += 1
        report["summary"]["entries_checked"] += checked
        report["summary"]["changed_files"] += len(archive.get("files", []))
        report["summary"]["failures"] += len(failures)

    if report["summary"]["failures"]:
        report["status"] = "failed"
    atomic_json(reports_root / "BR_TRANSLATION_PAK_REPACK_REPORT.json", report)

    if report["status"] != "ok":
        raise ToolError(
            f"Repacked PAK verification found {report['summary']['failures']} failure(s)"
        )
    print("Translation PAK development repack completed.")
    print(f"Archives: {report['summary']['archives']}")
    print(f"Entries verified: {report['summary']['entries_checked']}")
    print(f"Output root: {archive_output_root}")
    return 0

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    export = sub.add_parser(
        "export",
        help="validate sources and export translation JSON files",
    )
    export.add_argument("--project-root", required=True)
    export.set_defaults(func=cmd_export, repair_layouts=False)

    repair = sub.add_parser(
        "repair-export",
        help="re-detect ambiguous EBM layouts and safely refresh translation JSON",
    )
    repair.add_argument("--project-root", required=True)
    repair.set_defaults(func=cmd_export, repair_layouts=True)

    build = sub.add_parser(
        "build-loose",
        help="import editable en fields into target EBM/XML templates",
    )
    build.add_argument("--project-root", required=True)
    build.add_argument(
        "--target",
        action="append",
        choices=sorted(development_targets()),
        help="limit build to one or more targets",
    )
    build.add_argument(
        "--title-marker",
        default="none",
        help=(
            "legacy experimental UIL marker; use none to disable "
            "(default: none; runtime rendering was not confirmed)"
        ),
    )
    build.add_argument(
        "--target-workspace-map",
        help=(
            "JSON map of per-installation extracted target archives; translations are "
            "rebased structurally onto those current templates and repacked from them"
        ),
    )
    build.add_argument(
        "--runtime-canary",
        action="store_true",
        help=(
            "append [UNBURGER MOD] to the Tardy Kashiwagi NPC line "
            "available immediately after loading the test save"
        ),
    )
    build.set_defaults(func=cmd_build_loose)

    repack = sub.add_parser(
        "repack",
        help="rebuild and fully verify text PAKs in the local development build",
    )
    repack.add_argument("--project-root", required=True)
    repack.add_argument("--gust-pak", required=True)
    repack.add_argument("--timeout", type=int, default=1800)
    repack.set_defaults(func=cmd_repack)
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    try:
        return int(args.func(args))
    except ToolError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
