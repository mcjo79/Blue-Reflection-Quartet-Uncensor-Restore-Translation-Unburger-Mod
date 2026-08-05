#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import tempfile
from collections import Counter, defaultdict
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Optional

UNIT_TYPES = {"br_event_translation_unit", "br_system_translation_unit"}
PROJECTS = ("blue_reflection", "second_light", "blue_reflection_sun", "blue_reflection_ray")
REDACTIONS = {"-", "－", "--"}
TECHNICAL_JP = {"", "ダミー", "徃纃宁"}
SPACE_RE = re.compile(r"\s+")


class FinalizeError(RuntimeError):
    pass


def now_utc() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def atomic_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(data, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except FileNotFoundError:
            pass
        raise


def normalized(value: Any) -> str:
    text = str(value or "").replace("\r\n", "\n").replace("\r", "\n").replace("<CR>", "\n")
    return SPACE_RE.sub(" ", text).strip()


def nonempty(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def is_redaction(value: Any, jp: Any) -> bool:
    """Return whether an auxiliary English value is a redaction placeholder.

    A lone ``-``/``－``/``--`` is not usable English even when Quartet also
    replaced its JP-side record with the same placeholder.  The JP argument is
    retained for call-site compatibility and evidence reporting, but it must not
    turn a known placeholder into a translation candidate.
    """
    _ = jp
    return isinstance(value, str) and value.strip() in REDACTIONS


def is_technical_jp(value: Any) -> bool:
    return normalized(value) in TECHNICAL_JP


def rel(path: Optional[Path], root: Path) -> Optional[str]:
    if path is None:
        return None
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return str(path.resolve())


def resolve(root: Path, value: Any) -> Optional[Path]:
    if not isinstance(value, str) or not value:
        return None
    path = Path(value)
    return path if path.is_absolute() else root / path


def load_tool(root: Path):
    tool_dir = root / "Blue_Reflection_Text_Tool"
    if str(tool_dir) not in sys.path:
        sys.path.insert(0, str(tool_dir))
    import br_text_tool  # type: ignore
    return br_text_tool


def iter_units(root: Path, project: str) -> Iterable[tuple[Path, dict[str, Any]]]:
    base = root / "titles" / project / "translation"
    if not base.is_dir():
        return
    for path in sorted(base.rglob("*.json")):
        if path.name == "translation_manifest.json":
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if data.get("type") in UNIT_TYPES:
            yield path, data


def content_snapshot(root: Path) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for project in PROJECTS:
        for path, unit in iter_units(root, project):
            for record in unit.get("records", []):
                if not isinstance(record, dict):
                    continue
                logical_id = record.get("logical_id")
                if not isinstance(logical_id, str):
                    raise FinalizeError(f"record without logical_id: {path}")
                if logical_id in result:
                    raise FinalizeError(f"duplicate logical_id: {logical_id}")
                result[logical_id] = {
                    "en": record.get("en"),
                    "has_notes": "notes" in record,
                    "notes": record.get("notes"),
                    "has_status": "status" in record,
                    "status": record.get("status"),
                }
    return result


def parse_version(value: str) -> tuple[int, int, int]:
    match = re.fullmatch(r"(\d+)\.(\d+)\.(\d+)", value.strip())
    if not match:
        raise FinalizeError(f"unsupported version: {value!r}")
    return tuple(int(x) for x in match.groups())


def role_for(path: Path, unit: dict[str, Any]) -> str:
    role = unit.get("source_role")
    if isinstance(role, str):
        return role
    if "quartet_extensions" in path.as_posix():
        return "quartet_extension"
    return "canonical"


EXACT_MAPPING_METHODS = {
    "exact_string_no",
    "exact_string_id",
    "exact_index_key",
    "unique_key",
    "exact_index_msg_id",
    "exact_unique_msg_id",
    "unique_msg_id",
}
FALLBACK_MAPPING_METHODS = {"index_fallback_review", "same_count_index_review"}


def exact_mapping_method(method: Optional[str]) -> bool:
    return bool(method in EXACT_MAPPING_METHODS)


def index_context_confidence(
    mapping: list[Optional[int]],
    methods: list[str],
    source_count: int,
    target_count: int,
) -> list[bool]:
    """Confirm same-index fallback only inside a globally non-shifting unit.

    An index fallback is authoritative when both files have the same record count,
    no exact structural mapping establishes a shifted index, and at least one exact
    same-index anchor exists on either side of the fallback run. This admits JP text
    revisions while rejecting unanchored whole-file guesses.
    """
    result = [False] * source_count
    if source_count != target_count:
        return result

    exact_pairs = [
        (i, target)
        for i, target in enumerate(mapping)
        if target is not None and i < len(methods) and exact_mapping_method(methods[i])
    ]
    if any(i != target for i, target in exact_pairs):
        return result
    anchors = sorted(i for i, target in exact_pairs if i == target)
    if not anchors:
        return result

    for i, target in enumerate(mapping):
        method = methods[i] if i < len(methods) else ""
        if target != i or method not in FALLBACK_MAPPING_METHODS:
            continue
        has_left = any(anchor < i for anchor in anchors)
        has_right = any(anchor > i for anchor in anchors)
        # A one-sided anchor is sufficient at a file edge; an internal changed run
        # normally has both. Global no-shift exact mappings prevent crossing.
        if has_left or has_right:
            result[i] = True
    return result


def mapping_confidence(
    category: str,
    method: Optional[str],
    jp_equal: bool,
    same_count: bool,
    source_index: Optional[int],
    target_index: Optional[int],
    context_confirmed: bool = False,
) -> Optional[str]:
    if not method or source_index is None or target_index is None:
        return None
    if exact_mapping_method(method):
        return "exact_structural"
    if method in FALLBACK_MAPPING_METHODS and same_count and source_index == target_index:
        if jp_equal:
            return "same_index_exact_jp"
        if context_confirmed:
            return "same_index_context_anchored"
    return None


def parser_records(tool: Any, path: Path, category: str):
    if category == "event":
        return tool.parse_ebm(path)
    return tool.parse_xml_table(path)


def get_rows(parsed: Any, category: str):
    return parsed.messages if category == "event" else parsed.rows


def get_text(item: Any) -> str:
    return str(item.text or "")


def map_structural(tool: Any, source: Any, target: Any, category: str):
    if category == "event":
        return tool.align_messages(source, target)
    return tool.align_rows(source, target)


def exceptional_source_value(raw: Optional[str], value_status: str) -> Optional[str]:
    if raw is None or value_status == "available":
        return None
    return raw


def analyze(root: Path, apply_changes: bool, output_dir: Path) -> dict[str, Any]:
    tool = load_tool(root)
    before_content = content_snapshot(root)
    version_path = root / "workstreams/translation/VERSION"
    old_version = version_path.read_text(encoding="utf-8").strip()
    parse_version(old_version)
    if apply_changes and old_version != "0.0.112":
        raise FinalizeError(f"finalization requires translation 0.0.112, found {old_version}")

    totals: Counter[str] = Counter()
    value_statuses: Counter[str] = Counter()
    verification: Counter[str] = Counter()
    category_status: Counter[str] = Counter()
    mapping_methods: Counter[str] = Counter()
    changes: list[dict[str, Any]] = []
    conflicts: list[dict[str, Any]] = []
    unresolved_usable: list[dict[str, Any]] = []
    exceptions: list[dict[str, Any]] = []
    modified_units: list[tuple[Path, dict[str, Any]]] = []

    for path, unit in iter_units(root, "second_light"):
        category = str(unit.get("category") or "unknown")
        role = role_for(path, unit)
        records = unit.get("records")
        if not isinstance(records, list):
            raise FinalizeError(f"records is not a list: {path}")
        totals["units"] += 1
        totals[f"{role}_units"] += 1
        totals[f"{category}_units"] += 1

        source_meta = unit.get("source") if isinstance(unit.get("source"), dict) else {}
        source_path = resolve(root, source_meta.get("jp_path"))
        aux_jp_path = resolve(root, source_meta.get("auxiliary_jp_path"))
        aux_en_path = resolve(root, source_meta.get("auxiliary_en_path"))

        source_parsed = None
        aux_jp = None
        aux_en = None
        source_to_aux: list[Optional[int]] = [None] * len(records)
        source_status: list[str] = ["unavailable"] * len(records)
        aux_to_en: list[Optional[int]] = []
        aux_status: list[str] = []

        source_context_safe: list[bool] = [False] * len(records)
        if role != "quartet_extension":
            if source_path is None or not source_path.is_file():
                raise FinalizeError(f"missing canonical JP source for {path}: {source_path}")
            source_parsed = parser_records(tool, source_path, category)
            if len(get_rows(source_parsed, category)) != len(records):
                raise FinalizeError(f"canonical source/record count mismatch: {path}")
            if aux_jp_path and aux_jp_path.is_file():
                aux_jp = parser_records(tool, aux_jp_path, category)
                source_to_aux, source_status = map_structural(tool, source_parsed, aux_jp, category)
                source_context_safe = index_context_confidence(
                    source_to_aux,
                    source_status,
                    len(get_rows(source_parsed, category)),
                    len(get_rows(aux_jp, category)),
                )
            if aux_en_path and aux_en_path.is_file():
                aux_en = parser_records(tool, aux_en_path, category)
                if aux_jp is not None:
                    aux_to_en, aux_status = map_structural(tool, aux_jp, aux_en, category)

        unit_changed = False
        for index, record in enumerate(records):
            if not isinstance(record, dict):
                continue
            totals["records"] += 1
            totals[f"{role}_records"] += 1
            totals[f"{category}_records"] += 1
            logical_id = str(record.get("logical_id") or f"{path}:{index}")
            jp = str(record.get("jp") or "")
            existing = record.get("en_auxiliary")
            alignment = deepcopy(record.get("alignment")) if isinstance(record.get("alignment"), dict) else {}

            raw: Optional[str] = None
            value_status = "unavailable"
            verification_status = "not_applicable"
            mapping = "unavailable"
            source_index: Optional[int] = None
            en_index: Optional[int] = None
            source_method: Optional[str] = None
            en_method: Optional[str] = None
            aux_jp_text: Optional[str] = None
            invalid_class: Optional[str] = None

            if role == "quartet_extension":
                value_status = "not_applicable_target_extension"
                expected: Optional[str] = None
                verification_status = "not_applicable_target_extension"
            else:
                if aux_jp is None:
                    value_status = "quartet_unit_absent"
                    expected = None
                else:
                    source_index = source_to_aux[index] if index < len(source_to_aux) else None
                    source_method = source_status[index] if index < len(source_status) else None
                    if source_index is None:
                        value_status = "technical_record" if is_technical_jp(jp) else "quartet_record_absent_or_changed"
                        expected = None
                    else:
                        aux_jp_rows = get_rows(aux_jp, category)
                        aux_jp_text = get_text(aux_jp_rows[source_index])
                        jp_equal = normalized(jp) == normalized(aux_jp_text)
                        source_confidence = mapping_confidence(
                            category,
                            source_method,
                            jp_equal,
                            len(get_rows(source_parsed, category)) == len(aux_jp_rows),
                            index,
                            source_index,
                            source_context_safe[index] if index < len(source_context_safe) else False,
                        )
                        if source_confidence is None:
                            # Preserve evidence without attaching a possibly unrelated English
                            # sentence. A redaction/empty value at the same index can always be
                            # normalized safely; a usable value remains a hard preflight issue.
                            same_index_raw: Optional[str] = None
                            same_index_en_method: Optional[str] = None
                            if aux_en is not None and index < len(aux_to_en):
                                candidate_en_index = aux_to_en[index]
                                candidate_en_method = aux_status[index] if index < len(aux_status) else None
                                if candidate_en_index is not None:
                                    aux_en_rows = get_rows(aux_en, category)
                                    candidate_confidence = mapping_confidence(
                                        category,
                                        candidate_en_method,
                                        True,
                                        len(aux_jp_rows) == len(aux_en_rows),
                                        index,
                                        candidate_en_index,
                                        True,
                                    )
                                    if candidate_confidence is not None:
                                        same_index_raw = get_text(aux_en_rows[candidate_en_index])
                                        same_index_en_method = candidate_en_method
                            if same_index_raw == "":
                                raw = same_index_raw
                                value_status = "quartet_en_empty_unresolved_source_mapping"
                                expected = None
                            elif is_redaction(same_index_raw, aux_jp_text):
                                raw = same_index_raw
                                value_status = "quartet_en_redacted_unresolved_source_mapping"
                                expected = None
                            elif same_index_raw is not None:
                                candidate_invalid = tool.classify_auxiliary_japanese_copy(aux_jp_text, same_index_raw)
                                if candidate_invalid:
                                    raw = same_index_raw
                                    invalid_class = candidate_invalid
                                    value_status = f"quartet_en_invalid_copy_unresolved_source_mapping:{candidate_invalid}"
                                    expected = None
                                else:
                                    value_status = "quartet_source_mapping_unresolved_usable_candidate"
                                    expected = None
                                    unresolved_usable.append({
                                        "unit": rel(path, root),
                                        "logical_id": logical_id,
                                        "record_index": index,
                                        "jp": jp,
                                        "quartet_jp_same_index": aux_jp_text,
                                        "existing_en_auxiliary": existing,
                                        "same_index_quartet_en": same_index_raw,
                                        "source_method": source_method,
                                        "quartet_en_method": same_index_en_method,
                                    })
                            else:
                                value_status = "quartet_source_mapping_unresolved_no_en_record"
                                expected = None
                            mapping = f"{source_method or 'unmapped'}+{same_index_en_method or 'unmapped'}"
                        elif aux_en is None:
                            value_status = "quartet_en_unit_absent"
                            expected = None
                            mapping = f"{source_method}[{source_confidence}]+missing_en_unit"
                        else:
                            en_index = aux_to_en[source_index] if source_index < len(aux_to_en) else None
                            en_method = aux_status[source_index] if source_index < len(aux_status) else None
                            if en_index is None:
                                value_status = "technical_record" if is_technical_jp(jp) else "quartet_en_record_absent"
                                expected = None
                            else:
                                aux_en_rows = get_rows(aux_en, category)
                                raw = get_text(aux_en_rows[en_index])
                                en_confidence = mapping_confidence(
                                    category,
                                    en_method,
                                    True,
                                    len(aux_jp_rows) == len(aux_en_rows),
                                    source_index,
                                    en_index,
                                    True,
                                )
                                if en_confidence is None:
                                    value_status = "quartet_jp_to_en_mapping_unresolved"
                                    expected = None
                                    if raw and not is_redaction(raw, aux_jp_text):
                                        unresolved_usable.append({
                                            "unit": rel(path, root),
                                            "logical_id": logical_id,
                                            "record_index": index,
                                            "jp": jp,
                                            "quartet_jp": aux_jp_text,
                                            "existing_en_auxiliary": existing,
                                            "same_index_quartet_en": raw,
                                            "source_method": source_method,
                                            "quartet_en_method": en_method,
                                        })
                                else:
                                    invalid_class = tool.classify_auxiliary_japanese_copy(aux_jp_text, raw)
                                    if raw == "":
                                        value_status = "quartet_en_empty"
                                        expected = None
                                    elif is_redaction(raw, aux_jp_text):
                                        value_status = "quartet_en_redacted"
                                        expected = None
                                    elif invalid_class:
                                        value_status = f"quartet_en_invalid_copy:{invalid_class}"
                                        expected = None
                                    else:
                                        value_status = "available"
                                        expected = raw
                                mapping = (
                                    f"{source_method}[{source_confidence}]+"
                                    f"{en_method}[{en_confidence or 'unresolved'}]"
                                )

                if value_status == "available":
                    if existing == expected:
                        verification_status = "verified_authoritative_structural_mapping"
                    elif not nonempty(existing):
                        verification_status = "recover_authoritative_structural_mapping"
                    else:
                        verification_status = "conflict_existing_differs_from_authoritative"
                elif (
                    value_status in {
                        "quartet_en_empty",
                        "quartet_en_redacted",
                        "quartet_en_empty_unresolved_source_mapping",
                        "quartet_en_redacted_unresolved_source_mapping",
                    }
                    or value_status.startswith("quartet_en_invalid_copy:")
                    or value_status.startswith("quartet_en_invalid_copy_unresolved_source_mapping:")
                ):
                    if existing == expected or not nonempty(existing):
                        verification_status = "normalized_unusable_auxiliary_to_null"
                    elif raw is not None and existing == raw:
                        verification_status = "normalize_raw_unusable_auxiliary_to_null"
                    else:
                        verification_status = "conflict_unexpected_existing_unusable_auxiliary"
                else:
                    if not nonempty(existing):
                        verification_status = "verified_no_usable_auxiliary"
                    elif is_redaction(existing, jp):
                        verification_status = "normalize_unresolved_redaction_to_null"
                        expected = None
                    else:
                        verification_status = "conflict_existing_value_without_authoritative_source"

            if verification_status.startswith("conflict"):
                conflicts.append({
                    "unit": rel(path, root),
                    "logical_id": logical_id,
                    "record_index": index,
                    "jp": jp,
                    "existing_en_auxiliary": existing,
                    "authoritative_en_auxiliary": expected,
                    "raw_quartet_en": raw,
                    "value_status": value_status,
                    "mapping": mapping,
                })

            value_statuses[value_status] += 1
            verification[verification_status] += 1
            category_status[f"{category}:{role}:{value_status}"] += 1
            mapping_methods[mapping] += 1

            if role == "canonical" and category == "event" and value_status != "available":
                totals["canonical_event_without_usable_auxiliary"] += 1
                if is_technical_jp(jp):
                    totals["canonical_event_without_usable_auxiliary_technical"] += 1
                else:
                    totals["canonical_event_without_usable_auxiliary_nontechnical"] += 1
                if not nonempty(record.get("en")):
                    totals["canonical_event_without_usable_auxiliary_and_en_empty"] += 1
            if role == "quartet_extension" and category == "event" and not nonempty(record.get("en")):
                totals["quartet_extension_event_en_empty"] += 1
            if role == "quartet_extension" and category == "system" and not nonempty(record.get("en")):
                totals["quartet_extension_system_en_empty"] += 1
            if value_status == "available":
                totals["usable_en_auxiliary"] += 1
                totals[f"usable_{category}_en_auxiliary"] += 1
            elif value_status in {"quartet_en_redacted", "quartet_en_redacted_unresolved_source_mapping"}:
                totals["redacted_auxiliary_source_records"] += 1
            elif value_status in {"quartet_en_empty", "quartet_en_empty_unresolved_source_mapping"}:
                totals["empty_auxiliary_source_records"] += 1

            new_alignment = deepcopy(alignment)
            new_alignment["auxiliary_value_status"] = value_status
            new_alignment["auxiliary_verification"] = verification_status
            new_alignment["auxiliary_mapping_authoritative"] = mapping
            new_alignment["auxiliary_source_jp_relation"] = (
                "same" if aux_jp_text is not None and normalized(jp) == normalized(aux_jp_text)
                else "changed" if aux_jp_text is not None
                else "unavailable"
            )
            raw_evidence = exceptional_source_value(raw, value_status)
            if raw_evidence is not None:
                new_alignment["auxiliary_source_value"] = raw_evidence
            else:
                new_alignment.pop("auxiliary_source_value", None)
            if invalid_class:
                new_alignment["auxiliary_invalid_classification"] = invalid_class
            else:
                new_alignment.pop("auxiliary_invalid_classification", None)

            if record.get("en_auxiliary") != expected or record.get("alignment") != new_alignment:
                changes.append({
                    "unit": rel(path, root),
                    "logical_id": logical_id,
                    "record_index": index,
                    "old_en_auxiliary": record.get("en_auxiliary"),
                    "new_en_auxiliary": expected,
                    "value_status": value_status,
                    "verification": verification_status,
                })
                record["en_auxiliary"] = expected
                record["alignment"] = new_alignment
                unit_changed = True

            if value_status != "available" and role == "canonical":
                exceptions.append({
                    "unit": rel(path, root),
                    "logical_id": logical_id,
                    "record_index": index,
                    "category": category,
                    "jp": jp,
                    "en": record.get("en"),
                    "value_status": value_status,
                    "raw_quartet_en": raw,
                    "mapping": mapping,
                    "technical": is_technical_jp(jp),
                })

        if unit_changed:
            modified_units.append((path, unit))

    output_dir.mkdir(parents=True, exist_ok=True)
    atomic_json(output_dir / "PREFLIGHT_COUNTS.json", {
        "value_statuses": dict(sorted(value_statuses.items())),
        "verification": dict(sorted(verification.items())),
        "conflicts": len(conflicts),
        "unresolved_usable_candidates": len(unresolved_usable),
    })
    atomic_json(output_dir / "CONFLICTS.json", conflicts)
    atomic_json(output_dir / "UNRESOLVED_USABLE_CANDIDATES.json", unresolved_usable)
    if conflicts:
        raise FinalizeError(f"authoritative auxiliary conflicts found: {len(conflicts)}")
    if unresolved_usable:
        raise FinalizeError(
            f"unresolved usable auxiliary candidates remain: {len(unresolved_usable)}; "
            f"see {output_dir / 'UNRESOLVED_USABLE_CANDIDATES.json'}"
        )

    # Ensure the exact content fields owned by the translation chat are untouched.
    after_content: dict[str, dict[str, Any]] = {}
    for project in PROJECTS:
        for _, unit in iter_units(root, project):
            for record in unit.get("records", []):
                if isinstance(record, dict) and isinstance(record.get("logical_id"), str):
                    after_content[record["logical_id"]] = {
                        "en": record.get("en"),
                        "has_notes": "notes" in record,
                        "notes": record.get("notes"),
                        "has_status": "status" in record,
                        "status": record.get("status"),
                    }
    # The in-memory Second Light changes are not yet visible through iter_units,
    # so compare all touched records directly as well.
    for _, unit in modified_units:
        for record in unit.get("records", []):
            if isinstance(record, dict) and isinstance(record.get("logical_id"), str):
                after_content[record["logical_id"]] = {
                    "en": record.get("en"),
                    "has_notes": "notes" in record,
                    "notes": record.get("notes"),
                    "has_status": "status" in record,
                    "status": record.get("status"),
                }
    changed_content = [logical_id for logical_id, value in before_content.items() if after_content.get(logical_id) != value]
    if changed_content:
        raise FinalizeError(f"en/notes/status changed unexpectedly: {len(changed_content)}")

    # Hard readiness gates. There may be official EN gaps, but no unclassified or
    unresolved_gate = len(unresolved_usable)
    if verification["conflict_existing_differs_from_authoritative"]:
        raise FinalizeError("existing auxiliary conflicts remain")

    new_version = old_version
    if apply_changes:
        for path, unit in modified_units:
            atomic_json(path, unit)
        major, minor, patch = parse_version(old_version)
        new_version = f"{major}.{minor}.{patch + 1}"
        version_path.write_text(new_version + "\n", encoding="utf-8")

        status_path = root / "workstreams/translation/STATUS.json"
        status = json.loads(status_path.read_text(encoding="utf-8"))
        status["version"] = new_version
        status["second_light_auxiliary_policy"] = (
            "Quartet b4 auxiliary references are stored only when they contain usable English. "
            "Empty, redacted, invalid-copy and unavailable source values remain null and are "
            "classified precisely in alignment.auxiliary_value_status. Quartet-only extension "
            "records do not use en_auxiliary."
        )
        status["next_update"] = {
            "from_version": new_version,
            "to_version": f"{major}.{minor}.{patch + 2}",
            "workstream_id": "translation",
        }
        atomic_json(status_path, status)

        changelog_path = root / "workstreams/translation/CONTENT_CHANGELOG.json"
        previous_raw = changelog_path.read_bytes() if changelog_path.is_file() else b""
        try:
            previous = json.loads(previous_raw.decode("utf-8")) if previous_raw else None
        except Exception:
            previous = None
        changelog = {
            "type": "br_translation_second_light_auxiliary_finalization",
            "format_version": 1,
            "workstream_id": "translation",
            "from_version": old_version,
            "to_version": new_version,
            "status": "ready",
            "generated_utc": now_utc(),
            "changes": {
                "normalized_unusable_auxiliary_to_null": sum(
                    1 for row in changes if row["new_en_auxiliary"] is None and row["old_en_auxiliary"] is not None
                ),
                "recovered_authoritative_auxiliary": sum(
                    1 for row in changes if row["new_en_auxiliary"] is not None and not nonempty(row["old_en_auxiliary"])
                ),
                "alignment_metadata_updated": len(changes),
            },
            "guarantees": {
                "en_notes_status_changed": 0,
                "game_files_modified": False,
                "generic_auxiliary_classification_remaining": 0,
            },
            "readiness": dict(totals),
            "previous_content_changelog_sha256": hashlib.sha256(previous_raw).hexdigest(),
            "previous_content_changelog": previous,
        }
        atomic_json(changelog_path, changelog)

        history = root / "workstreams/translation/docs/RELEASE_HISTORY.md"
        with history.open("a", encoding="utf-8") as handle:
            handle.write(
                f"\n| {new_version} | Finalize Second Light ↔ Quartet b4 auxiliary semantics and evidence | "
                f"0 en/notes/status changes | usable auxiliary {totals['usable_en_auxiliary']}; "
                f"redacted normalized {totals['redacted_auxiliary_source_records']} |\n"
            )

    report = {
        "type": "br_second_light_quartet_alignment_finalization",
        "format_version": 1,
        "status": "applied" if apply_changes else "audit_complete",
        "generated_utc": now_utc(),
        "from_translation_version": old_version,
        "to_translation_version": new_version,
        "totals": dict(totals),
        "auxiliary_value_statuses": dict(sorted(value_statuses.items())),
        "verification": dict(sorted(verification.items())),
        "category_statuses": dict(sorted(category_status.items())),
        "mapping_methods": dict(sorted(mapping_methods.items())),
        "changes_planned_or_applied": len(changes),
        "modified_units": len(modified_units),
        "conflicts": len(conflicts),
        "unresolved_usable_candidates": len(unresolved_usable),
        "content_guarantees": {
            "en_notes_status_changed": 0,
            "game_files_modified": False,
        },
        "readiness_gates": {
            "authoritative_conflicts_zero": True,
            "unresolved_usable_candidates_zero": unresolved_gate == 0,
            "every_record_classified": sum(value_statuses.values()) == totals["records"],
            "unusable_auxiliary_values_normalized": True if apply_changes else False,
            "generic_manual_required_used_as_auxiliary_final_classification": False,
        },
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    atomic_json(output_dir / "SUMMARY.json", report)
    atomic_json(output_dir / "CHANGES.json", changes)
    atomic_json(output_dir / "CANONICAL_AUXILIARY_EXCEPTIONS.json", exceptions)

    if apply_changes:
        addendum = output_dir / f"Blue_Reflection_translation_chat_SECOND_LIGHT_AUXILIARY_FINALIZATION_{new_version}.md"
        addendum_text = (
            f"# Blue Reflection — finalizacja auxiliary Second Light / Quartet b4\n\n"
            f"Aktualna wersja Translation: **{new_version}**.\n\n"
            "Prawidłowe przypisanie pozostaje bez zmian: RAY = b2, SUN = b3, Second Light = b4. "
            "Ta wersja domyka semantykę `en_auxiliary` po korekcie partycji.\n\n"
            "## Wynik\n\n```text\n"
            f"usable en_auxiliary: {totals['usable_en_auxiliary']}\n"
            f"official redaction placeholders normalized to null: {totals['redacted_auxiliary_source_records']}\n"
            f"official empty auxiliary source records: {totals['empty_auxiliary_source_records']}\n"
            f"canonical event records without usable auxiliary: {totals['canonical_event_without_usable_auxiliary']}\n"
            f"technical among them: {totals['canonical_event_without_usable_auxiliary_technical']}\n"
            f"nontechnical among them: {totals['canonical_event_without_usable_auxiliary_nontechnical']}\n"
            "changed en/notes/status: 0\n```\n\n"
            "`en_auxiliary` przechowuje teraz wyłącznie rzeczywisty, użyteczny angielski tekst. "
            "Puste wpisy, placeholdery `-`, wadliwe kopie JP oraz brakujące rekordy EN są `null` i mają "
            "dokładną przyczynę w `alignment.auxiliary_value_status`. Rekordy istniejące tylko w Quartet "
            "nie używają `en_auxiliary`; ich właściwym polem roboczym pozostaje `en`.\n\n"
            "Nie utracono ani nie zmieniono żadnego istniejącego `en`, `notes` ani `status`.\n"
        )
        addendum.write_text(addendum_text, encoding="utf-8")
        report["addendum"] = str(addendum)
        atomic_json(output_dir / "SUMMARY.json", report)

    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Finalize Second Light / Quartet b4 auxiliary alignment semantics")
    parser.add_argument("command", choices=("audit", "apply"))
    parser.add_argument("--project-root", required=True)
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args()
    try:
        result = analyze(
            Path(args.project_root).resolve(),
            args.command == "apply",
            Path(args.output_dir).resolve(),
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except FinalizeError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
