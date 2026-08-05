#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import difflib
import hashlib
import json
import os
import re
import sys
import tarfile
import tempfile
import unicodedata
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Optional

UNIT_TYPES = {"br_event_translation_unit", "br_system_translation_unit"}
REDaction = {"-", "－", "--"}
SPACE_RE = re.compile(r"\s+")


class AuditError(RuntimeError):
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


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def normalized_text(value: str) -> str:
    value = unicodedata.normalize("NFKC", value or "")
    value = value.replace("\r\n", "\n").replace("\r", "\n")
    value = value.replace("<CR>", "\n")
    value = SPACE_RE.sub(" ", value).strip()
    return value


def nonempty(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def is_redaction(value: Optional[str], source: str) -> bool:
    if value is None:
        return False
    return value.strip() in REDaction and source.strip() not in REDaction


def rel(path: Optional[Path], root: Path) -> Optional[str]:
    if path is None:
        return None
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return str(path.resolve())


def load_unit(path: Path) -> Optional[dict[str, Any]]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if data.get("type") not in UNIT_TYPES:
        return None
    return data


def iter_units(root: Path) -> Iterable[tuple[Path, dict[str, Any]]]:
    translation = root / "titles/second_light/translation"
    if not translation.is_dir():
        raise AuditError(f"missing Second Light translation database: {translation}")
    for path in sorted(translation.rglob("*.json")):
        if path.name == "translation_manifest.json":
            continue
        unit = load_unit(path)
        if unit is not None:
            yield path, unit


def resolve_source(root: Path, value: Any) -> Optional[Path]:
    if not isinstance(value, str) or not value:
        return None
    path = Path(value)
    return path if path.is_absolute() else root / path


@dataclass(frozen=True)
class Message:
    index: int
    text: str
    msg_id: Optional[int]
    metadata: dict[str, Any]
    key: Optional[tuple[str, str]] = None


def load_parser_module(root: Path):
    tool_dir = root / "Blue_Reflection_Text_Tool"
    if str(tool_dir) not in sys.path:
        sys.path.insert(0, str(tool_dir))
    import br_text_tool  # type: ignore
    return br_text_tool


def canonical_messages(unit: dict[str, Any]) -> list[Message]:
    category = unit.get("category")
    result: list[Message] = []
    for fallback, record in enumerate(unit.get("records", [])):
        if not isinstance(record, dict):
            continue
        index = record.get("index")
        if not isinstance(index, int):
            index = fallback
        key = None
        if category == "system":
            if record.get("string_no") is not None:
                key = ("String_No", str(record.get("string_no")))
            elif record.get("string_id") is not None:
                key = ("String_ID", str(record.get("string_id")))
            else:
                key = ("index", str(index))
        result.append(Message(
            index=index,
            text=str(record.get("jp") or ""),
            msg_id=record.get("msg_id") if isinstance(record.get("msg_id"), int) else None,
            metadata=record.get("metadata") if isinstance(record.get("metadata"), dict) else {},
            key=key,
        ))
    return result


def parsed_messages(tool: Any, path: Path, category: str) -> list[Message]:
    if category == "event":
        ebm = tool.parse_ebm(path)
        return [Message(
            index=m.index,
            text=m.text,
            msg_id=m.msg_id,
            metadata=m.metadata(),
        ) for m in ebm.messages]
    table = tool.parse_xml_table(path)
    result = []
    for row in table.rows:
        key = tool.row_key(row)
        result.append(Message(
            index=row.index,
            text=row.text,
            msg_id=None,
            metadata={k: v for k, v in row.attrs.items() if k != "Text"},
            key=(str(key[0]), str(key[1])),
        ))
    return result


def metadata_signature(message: Message) -> tuple[Any, ...]:
    md = message.metadata
    return (
        message.msg_id,
        md.get("type"),
        md.get("voice_id"),
        md.get("name_id"),
        md.get("expr_id"),
        md.get("extra_id"),
    )


def exact_sequence_map(source: list[Message], target: list[Message]) -> tuple[dict[int, int], dict[int, str]]:
    """Create conservative monotonic exact-text mappings.

    SequenceMatcher provides context-sensitive blocks even for repeated strings.
    Remaining records are admitted only by unique exact text/key/msg_id evidence or
    by a unique nearest exact-text candidate inside surrounding mapped anchors.
    """
    src = [normalized_text(x.text) for x in source]
    dst = [normalized_text(x.text) for x in target]
    mapping: dict[int, int] = {}
    method: dict[int, str] = {}
    used: set[int] = set()

    matcher = difflib.SequenceMatcher(a=src, b=dst, autojunk=False)
    for block in matcher.get_matching_blocks():
        for offset in range(block.size):
            i = block.a + offset
            j = block.b + offset
            if src[i] == dst[j]:
                mapping[i] = j
                method[i] = "sequence_exact_text"
                used.add(j)

    target_by_key: dict[tuple[str, str], list[int]] = defaultdict(list)
    target_by_text: dict[str, list[int]] = defaultdict(list)
    target_by_msg: dict[int, list[int]] = defaultdict(list)
    target_by_sig: dict[tuple[Any, ...], list[int]] = defaultdict(list)
    for j, item in enumerate(target):
        if item.key is not None:
            target_by_key[item.key].append(j)
        target_by_text[dst[j]].append(j)
        if item.msg_id is not None:
            target_by_msg[item.msg_id].append(j)
        target_by_sig[metadata_signature(item)].append(j)

    for i, item in enumerate(source):
        if i in mapping:
            continue
        candidates: list[tuple[int, str]] = []
        if item.key is not None:
            candidates = [(j, "unique_key") for j in target_by_key.get(item.key, []) if j not in used]
        if not candidates and src[i]:
            candidates = [(j, "unique_exact_text") for j in target_by_text.get(src[i], []) if j not in used]
        if len(candidates) != 1 and item.msg_id is not None:
            by_msg = [j for j in target_by_msg.get(item.msg_id, []) if j not in used]
            exact_msg_text = [j for j in by_msg if src[i] == dst[j]]
            if len(exact_msg_text) == 1:
                candidates = [(exact_msg_text[0], "unique_msg_id_exact_text")]
        if len(candidates) != 1:
            by_sig = [j for j in target_by_sig.get(metadata_signature(item), []) if j not in used]
            exact_sig_text = [j for j in by_sig if src[i] == dst[j]]
            if len(exact_sig_text) == 1:
                candidates = [(exact_sig_text[0], "unique_metadata_exact_text")]
        if len(candidates) == 1:
            j, why = candidates[0]
            mapping[i] = j
            method[i] = why
            used.add(j)

    # Disambiguate repeated exact strings only when surrounding anchors impose a
    # single monotonic candidate. This remains conservative and never guesses by
    # approximate text.
    sorted_pairs = sorted(mapping.items())
    for i, item in enumerate(source):
        if i in mapping or not src[i]:
            continue
        candidates = [j for j in target_by_text.get(src[i], []) if j not in used]
        if not candidates:
            continue
        left = max((pair for pair in sorted_pairs if pair[0] < i), default=None)
        right = min((pair for pair in sorted_pairs if pair[0] > i), default=None)
        lo = left[1] + 1 if left else 0
        hi = right[1] - 1 if right else len(target) - 1
        bounded = [j for j in candidates if lo <= j <= hi]
        if len(bounded) == 1:
            j = bounded[0]
            mapping[i] = j
            method[i] = "bounded_repeated_exact_text"
            used.add(j)
            sorted_pairs = sorted(mapping.items())

    return mapping, method


def language_structure_map(source: list[Message], target: list[Message]) -> tuple[dict[int, int], dict[int, str]]:
    """Map JP structure to EN structure without comparing language text."""
    mapping: dict[int, int] = {}
    method: dict[int, str] = {}
    used: set[int] = set()

    if len(source) == len(target):
        if all(a.msg_id == b.msg_id for a, b in zip(source, target)):
            return ({i: i for i in range(len(source))}, {i: "exact_index_msg_id" for i in range(len(source))})
        if all(a.key == b.key for a, b in zip(source, target)):
            return ({i: i for i in range(len(source))}, {i: "exact_index_key" for i in range(len(source))})

    target_by_key: dict[tuple[str, str], list[int]] = defaultdict(list)
    target_by_msg: dict[int, list[int]] = defaultdict(list)
    target_by_sig: dict[tuple[Any, ...], list[int]] = defaultdict(list)
    for j, item in enumerate(target):
        if item.key is not None:
            target_by_key[item.key].append(j)
        if item.msg_id is not None:
            target_by_msg[item.msg_id].append(j)
        target_by_sig[metadata_signature(item)].append(j)

    for i, item in enumerate(source):
        candidates: list[tuple[int, str]] = []
        if item.key is not None:
            xs = [j for j in target_by_key.get(item.key, []) if j not in used]
            if len(xs) == 1:
                candidates = [(xs[0], "unique_key")]
        if not candidates and item.msg_id is not None:
            xs = [j for j in target_by_msg.get(item.msg_id, []) if j not in used]
            if len(xs) == 1:
                candidates = [(xs[0], "unique_msg_id")]
        if not candidates:
            xs = [j for j in target_by_sig.get(metadata_signature(item), []) if j not in used]
            if len(xs) == 1:
                candidates = [(xs[0], "unique_metadata")]
        if len(candidates) == 1:
            j, why = candidates[0]
            mapping[i] = j
            method[i] = why
            used.add(j)

    if len(source) == len(target):
        # Same-size language tables normally preserve record order. Only fill
        # holes that do not conflict with already established mappings.
        for i in range(len(source)):
            if i not in mapping and i not in used:
                mapping[i] = i
                method[i] = "same_count_index_review"
                used.add(i)

    return mapping, method


def invalid_auxiliary_copy(tool: Any, jp: str, en: str) -> Optional[str]:
    classifier = getattr(tool, "classify_auxiliary_japanese_copy", None)
    if classifier is None:
        return None
    return classifier(jp, en)


def unit_role(path: Path, unit: dict[str, Any]) -> str:
    role = unit.get("source_role")
    if isinstance(role, str):
        return role
    if "events_quartet_extensions" in path.parts or "system_quartet_extensions" in path.parts:
        return "quartet_extension"
    return "canonical"


def candidate_indices(messages: list[Message], source: Message) -> list[int]:
    norm = normalized_text(source.text)
    return [i for i, item in enumerate(messages) if normalized_text(item.text) == norm]


def audit(root: Path, output: Path) -> dict[str, Any]:
    tool = load_parser_module(root)
    output.mkdir(parents=True, exist_ok=True)
    detail_dir = output / "units"
    detail_dir.mkdir(parents=True, exist_ok=True)

    summary = Counter()
    class_counts = Counter()
    verification_counts = Counter()
    unit_rows: list[dict[str, Any]] = []
    null_rows: list[dict[str, Any]] = []
    verification_rows: list[dict[str, Any]] = []
    proposal: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    missing_referenced_sources = Counter()

    for path, unit in iter_units(root):
        category = str(unit.get("category") or "unknown")
        role = unit_role(path, unit)
        logical_path = str(unit.get("logical_path") or path.name.removesuffix(".json"))
        records = unit.get("records", [])
        if not isinstance(records, list):
            errors.append({"unit": rel(path, root), "error": "records_not_list"})
            continue
        summary["units"] += 1
        summary[f"{category}_units"] += 1
        summary[f"{role}_units"] += 1
        summary["records"] += len(records)

        canonical = canonical_messages(unit)
        source_meta = unit.get("source") if isinstance(unit.get("source"), dict) else {}
        aux_jp_path = resolve_source(root, source_meta.get("auxiliary_jp_path"))
        aux_en_path = resolve_source(root, source_meta.get("auxiliary_en_path"))
        unit_detail: dict[str, Any] = {
            "unit": rel(path, root),
            "category": category,
            "source_role": role,
            "logical_path": logical_path,
            "records": len(records),
            "auxiliary_jp_path": rel(aux_jp_path, root),
            "auxiliary_en_path": rel(aux_en_path, root),
            "auxiliary_jp_exists": bool(aux_jp_path and aux_jp_path.is_file()),
            "auxiliary_en_exists": bool(aux_en_path and aux_en_path.is_file()),
        }

        aux_jp: list[Message] = []
        aux_en: list[Message] = []
        source_to_aux: dict[int, int] = {}
        source_methods: dict[int, str] = {}
        aux_to_en: dict[int, int] = {}
        aux_en_methods: dict[int, str] = {}

        if role != "quartet_extension" and aux_jp_path and not aux_jp_path.is_file():
            missing_referenced_sources["auxiliary_jp"] += 1
        if role != "quartet_extension" and aux_en_path and not aux_en_path.is_file():
            missing_referenced_sources["auxiliary_en"] += 1

        if role != "quartet_extension" and aux_jp_path and aux_jp_path.is_file():
            try:
                aux_jp = parsed_messages(tool, aux_jp_path, category)
                source_to_aux, source_methods = exact_sequence_map(canonical, aux_jp)
            except Exception as exc:
                errors.append({"unit": rel(path, root), "error": "auxiliary_jp_parse_failed", "detail": str(exc)})
        if role != "quartet_extension" and aux_en_path and aux_en_path.is_file():
            try:
                aux_en = parsed_messages(tool, aux_en_path, category)
                if aux_jp:
                    aux_to_en, aux_en_methods = language_structure_map(aux_jp, aux_en)
            except Exception as exc:
                errors.append({"unit": rel(path, root), "error": "auxiliary_en_parse_failed", "detail": str(exc)})

        unit_class = Counter()
        unit_verify = Counter()
        unit_detail["auxiliary_jp_records"] = len(aux_jp)
        unit_detail["auxiliary_en_records"] = len(aux_en)
        unit_detail["source_to_aux_high_confidence"] = len(source_to_aux)
        unit_detail["auxiliary_jp_to_en_mapped"] = len(aux_to_en)

        detail_records: list[dict[str, Any]] = []
        for pos, record in enumerate(records):
            if not isinstance(record, dict):
                continue
            summary["records_scanned"] += 1
            logical_id = str(record.get("logical_id") or f"{logical_path}:{pos}")
            existing = record.get("en_auxiliary")
            source_msg = canonical[pos] if pos < len(canonical) else Message(pos, str(record.get("jp") or ""), None, {})
            mapped_aux = source_to_aux.get(pos)
            mapped_en = aux_to_en.get(mapped_aux) if mapped_aux is not None else None
            candidate_value: Optional[str] = None
            candidate_jp: Optional[str] = None
            invalid_class: Optional[str] = None
            if mapped_aux is not None and mapped_aux < len(aux_jp):
                candidate_jp = aux_jp[mapped_aux].text
            if mapped_en is not None and mapped_en < len(aux_en):
                candidate_value = aux_en[mapped_en].text
                invalid_class = invalid_auxiliary_copy(tool, candidate_jp or "", candidate_value)

            classification: str
            if role == "quartet_extension":
                classification = "not_applicable_quartet_extension"
            elif aux_jp_path is None:
                classification = "quartet_unit_absent"
            elif not aux_jp_path.is_file():
                classification = "referenced_auxiliary_jp_missing_on_disk"
            elif mapped_aux is None:
                exact_candidates = candidate_indices(aux_jp, source_msg) if aux_jp else []
                if len(exact_candidates) > 1:
                    classification = "ambiguous_repeated_exact_jp"
                elif len(exact_candidates) == 1:
                    classification = "exact_jp_candidate_not_admitted"
                else:
                    classification = "quartet_record_absent_or_jp_changed"
            elif aux_en_path is None:
                classification = "quartet_en_unit_absent"
            elif not aux_en_path.is_file():
                classification = "referenced_auxiliary_en_missing_on_disk"
            elif mapped_en is None:
                classification = "quartet_en_record_unresolved"
            elif candidate_value is None:
                classification = "quartet_en_record_unresolved"
            elif candidate_value == "":
                classification = "quartet_en_empty"
            elif is_redaction(candidate_value, source_msg.text):
                classification = "quartet_en_redacted"
            elif invalid_class:
                classification = f"quartet_en_invalid_copy:{invalid_class}"
            else:
                classification = "recoverable_high_confidence"

            if not nonempty(existing):
                summary["null_en_auxiliary"] += 1
                summary[f"null_{category}"] += 1
                summary[f"null_{role}"] += 1
                class_counts[classification] += 1
                unit_class[classification] += 1
                row = {
                    "unit": rel(path, root),
                    "logical_path": logical_path,
                    "category": category,
                    "source_role": role,
                    "logical_id": logical_id,
                    "record_index": pos,
                    "msg_id": record.get("msg_id"),
                    "string_no": record.get("string_no"),
                    "jp": record.get("jp"),
                    "en_original": record.get("en_original"),
                    "en": record.get("en"),
                    "alignment_status": (record.get("alignment") or {}).get("status") if isinstance(record.get("alignment"), dict) else None,
                    "current_auxiliary_mapping": (record.get("alignment") or {}).get("auxiliary_mapping") if isinstance(record.get("alignment"), dict) else None,
                    "classification": classification,
                    "source_to_aux_index": mapped_aux,
                    "source_to_aux_method": source_methods.get(pos),
                    "auxiliary_jp": candidate_jp,
                    "auxiliary_en_index": mapped_en,
                    "auxiliary_jp_to_en_method": aux_en_methods.get(mapped_aux) if mapped_aux is not None else None,
                    "recoverable_en_auxiliary": candidate_value if classification == "recoverable_high_confidence" else None,
                    "exact_jp_candidate_indices": candidate_indices(aux_jp, source_msg) if aux_jp and mapped_aux is None else [],
                }
                null_rows.append(row)
                detail_records.append(row)
                if classification == "recoverable_high_confidence":
                    proposal.append({
                        "unit": rel(path, root),
                        "logical_id": logical_id,
                        "record_index": pos,
                        "old_en_auxiliary": existing,
                        "new_en_auxiliary": candidate_value,
                        "auxiliary_en_index": mapped_en,
                        "source_to_aux_index": mapped_aux,
                        "source_to_aux_method": source_methods.get(pos),
                        "auxiliary_jp_to_en_method": aux_en_methods.get(mapped_aux) if mapped_aux is not None else None,
                    })
            else:
                summary["nonnull_en_auxiliary"] += 1
                if candidate_value is None:
                    verification = "existing_unverifiable_no_high_confidence_candidate"
                elif existing == candidate_value:
                    verification = "existing_matches_recomputed_candidate"
                else:
                    verification = "existing_mismatch_recomputed_candidate"
                verification_counts[verification] += 1
                unit_verify[verification] += 1
                if verification != "existing_matches_recomputed_candidate":
                    row = {
                        "unit": rel(path, root),
                        "logical_path": logical_path,
                        "category": category,
                        "logical_id": logical_id,
                        "record_index": pos,
                        "jp": record.get("jp"),
                        "existing_en_auxiliary": existing,
                        "recomputed_en_auxiliary": candidate_value,
                        "verification": verification,
                        "source_to_aux_index": mapped_aux,
                        "source_to_aux_method": source_methods.get(pos),
                        "auxiliary_en_index": mapped_en,
                        "auxiliary_jp_to_en_method": aux_en_methods.get(mapped_aux) if mapped_aux is not None else None,
                    }
                    verification_rows.append(row)
                    detail_records.append(row)

        unit_detail["null_classifications"] = dict(sorted(unit_class.items()))
        unit_detail["existing_verification"] = dict(sorted(unit_verify.items()))
        unit_detail["null_count"] = sum(unit_class.values())
        unit_detail["verification_exceptions"] = sum(v for k, v in unit_verify.items() if k != "existing_matches_recomputed_candidate")
        unit_rows.append(unit_detail)
        if detail_records:
            safe = hashlib.sha256(rel(path, root).encode("utf-8")).hexdigest()[:16]
            atomic_json(detail_dir / f"{safe}.json", {**unit_detail, "records_of_interest": detail_records})

    summary_data = {
        "type": "br_second_light_quartet_alignment_full_audit",
        "format_version": 1,
        "status": (
            "complete"
            if not errors and not missing_referenced_sources
            else "complete_with_source_errors"
            if errors
            else "complete_with_missing_referenced_sources"
        ),
        "generated_utc": now_utc(),
        "translation_version": (root / "workstreams/translation/VERSION").read_text(encoding="utf-8").strip(),
        "translation_tooling_version": (root / "workstreams/translation_tooling/VERSION").read_text(encoding="utf-8").strip(),
        "scope": "Second Light canonical and Quartet b4 extension records; read-only",
        "totals": dict(summary),
        "null_classifications": dict(sorted(class_counts.items())),
        "existing_auxiliary_verification": dict(sorted(verification_counts.items())),
        "proposed_high_confidence_recoveries": len(proposal),
        "source_errors": errors,
        "missing_referenced_sources": dict(sorted(missing_referenced_sources.items())),
        "acceptance_gates": {
            "source_errors_zero": len(errors) == 0,
            "referenced_source_files_present": not missing_referenced_sources,
            "existing_auxiliary_mismatches_zero": verification_counts["existing_mismatch_recomputed_candidate"] == 0,
            "existing_auxiliary_fully_verified": (
                verification_counts["existing_mismatch_recomputed_candidate"] == 0
                and verification_counts["existing_unverifiable_no_high_confidence_candidate"] == 0
            ),
            "every_null_classified": sum(class_counts.values()) == summary["null_en_auxiliary"],
            "generic_manual_required_used_as_final_classification": False,
            "automatic_changes_applied": False,
        },
        "files": {
            "null_records": "NULL_EN_AUXILIARY_RECORDS.json",
            "verification_exceptions": "EXISTING_AUXILIARY_VERIFICATION_EXCEPTIONS.json",
            "proposal": "HIGH_CONFIDENCE_RECOVERY_PROPOSAL.json",
            "unit_summary": "UNIT_SUMMARY.json",
        },
    }
    atomic_json(output / "SUMMARY.json", summary_data)
    atomic_json(output / "NULL_EN_AUXILIARY_RECORDS.json", null_rows)
    atomic_json(output / "EXISTING_AUXILIARY_VERIFICATION_EXCEPTIONS.json", verification_rows)
    atomic_json(output / "HIGH_CONFIDENCE_RECOVERY_PROPOSAL.json", {
        "type": "br_second_light_auxiliary_recovery_proposal",
        "format_version": 1,
        "status": "proposal_only_not_applied",
        "records": proposal,
    })
    atomic_json(output / "UNIT_SUMMARY.json", unit_rows)

    with (output / "NULL_EN_AUXILIARY_RECORDS.tsv").open("w", encoding="utf-8", newline="") as handle:
        columns = [
            "unit", "logical_path", "category", "source_role", "logical_id", "record_index",
            "msg_id", "string_no", "classification", "source_to_aux_index", "source_to_aux_method",
            "auxiliary_en_index", "auxiliary_jp_to_en_method", "jp", "en_original", "en",
            "recoverable_en_auxiliary",
        ]
        writer = csv.DictWriter(handle, fieldnames=columns, delimiter="\t", extrasaction="ignore")
        writer.writeheader()
        writer.writerows(null_rows)

    lines = [
        "Blue Reflection Second Light / Quartet b4 alignment full audit",
        "",
        f"Translation: {summary_data['translation_version']}",
        f"Translation tooling: {summary_data['translation_tooling_version']}",
        f"Status: {summary_data['status']}",
        "",
        "Totals:",
    ]
    for key, value in sorted(summary.items()):
        lines.append(f"  {key}: {value}")
    lines.append("")
    lines.append("Null en_auxiliary classifications:")
    for key, value in sorted(class_counts.items()):
        lines.append(f"  {key}: {value}")
    lines.append("")
    lines.append("Existing non-null auxiliary verification:")
    for key, value in sorted(verification_counts.items()):
        lines.append(f"  {key}: {value}")
    lines.append("")
    lines.append(f"High-confidence recovery proposal records: {len(proposal)}")
    lines.append(f"Source/parsing errors: {len(errors)}")
    lines.append(f"Missing referenced source files: {sum(missing_referenced_sources.values())}")
    lines.append("")
    lines.append("No canonical JSON or game file was modified.")
    (output / "SUMMARY.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")

    return summary_data


def main() -> int:
    parser = argparse.ArgumentParser(description="Read-only full alignment audit for Second Light vs Quartet b4")
    parser.add_argument("--project-root", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    root = Path(args.project_root).resolve()
    output = Path(args.output).resolve()
    try:
        result = audit(root, output)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except AuditError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
