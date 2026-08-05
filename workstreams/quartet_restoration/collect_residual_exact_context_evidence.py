#!/usr/bin/env python3
"""Validate exact contexts and in-memory inverse splices for stage-34 residual shapes."""

from __future__ import annotations

import argparse
import csv
import hashlib
import importlib
import json
import shutil
import struct
import subprocess
import sys
import tarfile
import tempfile
from collections import Counter, defaultdict
from pathlib import Path, PurePosixPath
from typing import Any, Iterable, Mapping, Sequence

WORKSTREAM_ID = "quartet_restoration"
TOOL_VERSION = "0.0.41"
REPORT_NAME = "BR_quartet_restoration_residual_exact_context_evidence.tar.zst"
EVIDENCE_DIR_NAME = "residual_exact_context_evidence"

STAGE34_DIR = "residual_scene_context_evidence"
STAGE34_ARCHIVE = "BR_quartet_restoration_residual_scene_context_evidence.tar.zst"
CONTEXT_DIR = "event_delta_context_evidence"
CONTEXT_ARCHIVE = "BR_quartet_restoration_event_delta_context_evidence.tar.zst"
MIGRATION_DIR = "event_tag_migration_evidence"
MIGRATION_ARCHIVE = "BR_quartet_restoration_event_tag_migration_evidence.tar.zst"

TARGET_SHAPES: dict[str, dict[str, str]] = {
    "5d4f142d73a7cc2cec78daabba6733ba1f71ac4c430031534b2407cb06e6ba72": {
        "stage34_classification": "route_sequence_state_candidate",
        "expected_events": "event/event_jp/te02/event_te02_180.ebd;event/event_jp/te02/event_te02_220.ebd",
        "expected_domains": "pool_or_swimming;shower",
    },
    "e684210e170e285eb0b3bf04dd11b819482b73bba3489c94a61e570da75f4e1d": {
        "stage34_classification": "route_sequence_state_candidate",
        "expected_events": "event/event_jp/te02/event_te02_180.ebd",
        "expected_domains": "pool_or_swimming;shower",
    },
    "d88c7c3a6f484a28d9ff9662379152bdcdeb4e12fa46d286cc02e3b0bcaabc69": {
        "stage34_classification": "shared_presentation_candidate",
        "expected_events": "event/event_jp/ce11/event_ce11_070.ebd",
        "expected_domains": "steam_or_vapor",
    },
}
PARKED_SHAPE = "a570203aa66f99f15cfbdaa84653f0cb55f515cd59e5372bd1d6d69852c58d7d"
PARKED_PROFILE = "route_sequence_te02_a570203aa6"


class ExactContextError(RuntimeError):
    pass


def parse_bool(value: object) -> bool:
    return str(value).strip().casefold() in {"1", "true", "yes", "y"}


def parse_int(value: object, default: int = 0) -> int:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return default


def split_semicolon(value: object) -> list[str]:
    return [part for part in str(value or "").split(";") if part]


def unique_join(values: Iterable[str]) -> str:
    output: list[str] = []
    seen: set[str] = set()
    for value in values:
        if value and value not in seen:
            seen.add(value)
            output.append(value)
    return ";".join(output)


def read_tsv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return [dict(row) for row in csv.DictReader(handle, delimiter="\t")]


def write_tsv(path: Path, fieldnames: Sequence[str], rows: Iterable[Mapping[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fieldnames})


def atomic_json(path: Path, data: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def safe_member_name(raw: str) -> str:
    path = PurePosixPath(raw)
    if path.is_absolute() or not path.parts or ".." in path.parts:
        raise ExactContextError(f"unsafe report archive member: {raw}")
    return path.as_posix()


def extract_report(archive: Path, destination: Path) -> None:
    if not archive.is_file():
        raise ExactContextError(f"missing prerequisite report: {archive}")
    listing = subprocess.run(
        ["tar", "--zstd", "-tf", str(archive)], check=False, text=True,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    if listing.returncode != 0:
        raise ExactContextError(f"cannot list report {archive}: {listing.stderr.strip()}")
    for line in listing.stdout.splitlines():
        if line.strip():
            safe_member_name(line.strip())
    destination.mkdir(parents=True, exist_ok=True)
    result = subprocess.run(
        ["tar", "--zstd", "-xf", str(archive), "-C", str(destination)],
        check=False, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    if result.returncode != 0:
        raise ExactContextError(f"cannot extract report {archive}: {result.stderr.strip()}")


def evidence_dir(
    report_root: Path, directory_name: str, archive_name: str, temporary_root: Path,
) -> Path:
    direct = report_root / directory_name
    if direct.is_dir():
        return direct
    extraction = temporary_root / directory_name
    extract_report(report_root / archive_name, extraction)
    matches = [path for path in extraction.rglob(directory_name) if path.is_dir()]
    if len(matches) != 1:
        raise ExactContextError(
            f"expected one {directory_name} directory in {archive_name}, found {len(matches)}"
        )
    return matches[0]


def load_restoration_tool(project_root: Path) -> Any:
    tool_root = project_root / "Blue_Reflection_Text_Tool"
    if not (tool_root / "br_restoration_tool.py").is_file():
        raise ExactContextError(f"missing restoration tool: {tool_root / 'br_restoration_tool.py'}")
    sys.path.insert(0, str(tool_root))
    try:
        return importlib.import_module("br_restoration_tool")
    finally:
        try:
            sys.path.remove(str(tool_root))
        except ValueError:
            pass


def route_family(path: str) -> str:
    name = Path(path).name
    if not name.startswith("event_") or not name.endswith(".ebd"):
        return ""
    stem = name[len("event_") : -len(".ebd")]
    return stem.rsplit("_", 1)[0] if "_" in stem else stem


def byte_difference_count(left: bytes, right: bytes) -> int:
    overlap = min(len(left), len(right))
    return sum(a != b for a, b in zip(left[:overlap], right[:overlap])) + abs(len(left) - len(right))


def make_report_archive(source_dir: Path, output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(output.name + ".tmp")
    if temporary.exists():
        temporary.unlink()
    result = subprocess.run(
        ["tar", "--zstd", "-cf", str(temporary), "-C", str(source_dir.parent), source_dir.name],
        check=False, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    if result.returncode != 0:
        raise ExactContextError(f"cannot create report archive: {result.stderr.strip()}")
    temporary.replace(output)


def counter_shape_ids(br: Any, deltas: Sequence[dict[str, Any]]) -> Counter[str]:
    return Counter(br.event_residual_delta_shape_id(row) for row in deltas)


def simulate_exact_inverse_splice(
    *, br: Any, source_payload: bytes, target_payload: bytes, occurrence: Mapping[str, object],
) -> dict[str, object]:
    source_header = br.parse_ebd_header_schema(source_payload)
    target_header = br.parse_ebd_header_schema(target_payload)
    if source_header.get("classification") != "observed_ebd_name_description_header":
        raise ExactContextError("source EBD header is not recognized")
    if target_header.get("classification") != "observed_ebd_name_description_header":
        raise ExactContextError("target EBD header is not recognized")
    source_profile = br.profile_ebd_post_header_words(source_payload, int(source_header["header_end"]))
    target_profile = br.profile_ebd_post_header_words(target_payload, int(target_header["header_end"]))
    source_words = list(source_profile["words"])
    target_words = list(target_profile["words"])
    source_start = parse_int(occurrence.get("source_span_start_word_index"), -1)
    source_end = parse_int(occurrence.get("source_span_end_word_index"), -1)
    target_start = parse_int(occurrence.get("target_span_start_word_index"), -1)
    target_end = parse_int(occurrence.get("target_span_end_word_index"), -1)
    if not (0 <= source_start <= source_end <= len(source_words)):
        raise ExactContextError("source exact span escapes EBD post-header words")
    if not (0 <= target_start <= target_end <= len(target_words)):
        raise ExactContextError("target exact span escapes EBD post-header words")

    candidate_words = target_words[:target_start] + source_words[source_start:source_end] + target_words[target_end:]
    target_header_end = int(target_header["header_end"])
    target_word_bytes_end = target_header_end + int(target_profile["word_count"]) * 4
    trailing = target_payload[target_word_bytes_end:]
    candidate_payload = (
        target_payload[:target_header_end]
        + (struct.pack(f"<{len(candidate_words)}I", *candidate_words) if candidate_words else b"")
        + trailing
    )
    candidate_header = br.parse_ebd_header_schema(candidate_payload)
    candidate_profile = br.profile_ebd_post_header_words(
        candidate_payload, int(candidate_header.get("header_end", 0)),
        maximum_words=max(1, len(candidate_words) + 8),
    )
    before_deltas = br.compare_ebd_tag_atoms(source_profile["atoms"], target_profile["atoms"])
    after_deltas = br.compare_ebd_tag_atoms(source_profile["atoms"], candidate_profile["atoms"])
    before = counter_shape_ids(br, before_deltas)
    after = counter_shape_ids(br, after_deltas)
    shape_id = str(occurrence.get("shape_id", ""))
    selected_before = before[shape_id]
    selected_after = after[shape_id]
    other_before = before.copy()
    other_after = after.copy()
    other_before.pop(shape_id, None)
    other_after.pop(shape_id, None)
    selected_occurrence_removed = selected_before > 0 and selected_after == selected_before - 1
    other_shapes_unchanged = other_before == other_after
    header_preserved = candidate_payload[:target_header_end] == target_payload[:target_header_end]
    trailing_preserved = candidate_payload[-len(trailing):] == trailing if trailing else True
    candidate_header_valid = candidate_header.get("classification") == "observed_ebd_name_description_header"
    if selected_occurrence_removed and other_shapes_unchanged and header_preserved and trailing_preserved and candidate_header_valid:
        status = "isolated_exact_inverse_splice_passed"
    elif selected_after < selected_before and not other_shapes_unchanged:
        status = "selected_shape_reduced_but_other_residual_shapes_changed"
    elif selected_after < selected_before:
        status = "selected_shape_reduced_but_container_invariants_failed"
    else:
        status = "selected_shape_not_removed_by_exact_inverse_splice"
    source_span = source_words[source_start:source_end]
    target_span = target_words[target_start:target_end]
    return {
        "source_span_start_word_index": source_start,
        "source_span_end_word_index": source_end,
        "target_span_start_word_index": target_start,
        "target_span_end_word_index": target_end,
        "source_span_word_count": source_end - source_start,
        "target_span_word_count": target_end - target_start,
        "source_span_sha256": hashlib.sha256(struct.pack(f"<{len(source_span)}I", *source_span) if source_span else b"").hexdigest(),
        "target_span_sha256": hashlib.sha256(struct.pack(f"<{len(target_span)}I", *target_span) if target_span else b"").hexdigest(),
        "candidate_size": len(candidate_payload),
        "target_size": len(target_payload),
        "candidate_size_delta": len(candidate_payload) - len(target_payload),
        "candidate_sha256": hashlib.sha256(candidate_payload).hexdigest(),
        "target_byte_difference_to_source": byte_difference_count(target_payload, source_payload),
        "candidate_byte_difference_to_source": byte_difference_count(candidate_payload, source_payload),
        "selected_shape_count_before": selected_before,
        "selected_shape_count_after": selected_after,
        "selected_occurrence_removed": selected_occurrence_removed,
        "other_residual_shape_counter_unchanged": other_shapes_unchanged,
        "other_residual_shape_count_before": sum(other_before.values()),
        "other_residual_shape_count_after": sum(other_after.values()),
        "target_header_preserved": header_preserved,
        "target_trailing_bytes_preserved": trailing_preserved,
        "candidate_header_valid": candidate_header_valid,
        "candidate_post_header_family": candidate_profile.get("family", ""),
        "splice_status": status,
        "review_status": "in_memory_metadata_only_candidate_payload_not_written",
    }


def build_context_comparisons(occurrences: Sequence[Mapping[str, object]]) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    by_shape: defaultdict[str, list[Mapping[str, object]]] = defaultdict(list)
    for row in occurrences:
        by_shape[str(row.get("shape_id", ""))].append(row)
    for shape_id, items in sorted(by_shape.items()):
        ordered = sorted(items, key=lambda row: (str(row.get("normalized_path", "")), parse_int(row.get("occurrence_index"))))
        for index, left in enumerate(ordered):
            for right in ordered[index + 1 :]:
                left_cue = parse_bool(left.get("cue_positive_occurrence"))
                right_cue = parse_bool(right.get("cue_positive_occurrence"))
                if left_cue != right_cue:
                    comparison_kind = "cue_vs_noncue_control"
                elif left_cue:
                    comparison_kind = "cue_vs_cue_cross_scene"
                else:
                    comparison_kind = "noncue_vs_noncue_control"
                same_archetype = bool(left.get("pair_context_archetype_id")) and left.get("pair_context_archetype_id") == right.get("pair_context_archetype_id")
                rows.append({
                    "shape_id": shape_id,
                    "comparison_kind": comparison_kind,
                    "left_path": left.get("normalized_path", ""),
                    "left_cue_positive": left_cue,
                    "left_cue_domains": left.get("cue_domains", ""),
                    "left_context_archetype_id": left.get("pair_context_archetype_id", ""),
                    "right_path": right.get("normalized_path", ""),
                    "right_cue_positive": right_cue,
                    "right_cue_domains": right.get("cue_domains", ""),
                    "right_context_archetype_id": right.get("pair_context_archetype_id", ""),
                    "same_route_family": route_family(str(left.get("normalized_path", ""))) == route_family(str(right.get("normalized_path", ""))),
                    "same_exact_pair_context_archetype": same_archetype,
                    "same_source_context_signature": left.get("source_context_signature_sha256", "") == right.get("source_context_signature_sha256", ""),
                    "same_target_context_signature": left.get("target_context_signature_sha256", "") == right.get("target_context_signature_sha256", ""),
                    "review_status": (
                        "exact_context_is_shared_by_cue_and_noncue_occurrences"
                        if comparison_kind == "cue_vs_noncue_control" and same_archetype
                        else "context_comparison_does_not_assign_binary_field_semantics"
                    ),
                })
    return rows


def classify_promotion_gate(
    *, cue_occurrences: int, noncue_occurrences: int, route_family_count: int,
    shared_cue_noncue_archetypes: int, splice_rows: int, isolated_splice_rows: int,
) -> tuple[str, str, str]:
    if noncue_occurrences > 0:
        if shared_cue_noncue_archetypes > 0:
            return (
                "route_state_or_schema_behavior_more_likely",
                "not_eligible_for_stage_36",
                "cue-positive exact context is also present in non-cue route controls",
            )
        return (
            "route_sequence_state_or_schema_behavior_more_likely",
            "not_eligible_for_stage_36",
            "shape is distributed across cue and non-cue events in the route without presentation-specific exact-context support",
        )
    if cue_occurrences >= 2 and route_family_count >= 2:
        if splice_rows > 0 and isolated_splice_rows == splice_rows:
            return (
                "shared_presentation_exact_span_prototype_candidate",
                "eligible_for_stage_36_local_prototype_review",
                "cue-only cross-route support and every exact inverse splice preserves all other residual shapes",
            )
        return (
            "shared_presentation_candidate_not_splice_isolated",
            "not_eligible_for_stage_36",
            "cue-only support remains interesting but one or more exact inverse splices failed isolation",
        )
    return (
        "insufficient_exact_context_support",
        "not_eligible_for_stage_36",
        "exact context does not separate presentation behavior from route or schema behavior",
    )


def validate_stage34_targets(rows: Sequence[Mapping[str, str]]) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    by_shape = {str(row.get("shape_id", "")): row for row in rows}
    missing = sorted(set(TARGET_SHAPES) - set(by_shape))
    if missing:
        raise ExactContextError("stage-34 cohort report is missing target shapes: " + ", ".join(missing))
    target_rows: list[dict[str, object]] = []
    for shape_id, expected in TARGET_SHAPES.items():
        row = by_shape[shape_id]
        if row.get("classification") != expected["stage34_classification"]:
            raise ExactContextError(
                f"stage-34 classification changed for {shape_id}: {row.get('classification')}"
            )
        target_rows.append({
            "shape_id": shape_id,
            "stage34_classification": row.get("classification", ""),
            "stage34_review_priority": row.get("review_priority", ""),
            "sequence_tag": row.get("sequence_tag", ""),
            "source_tag_values": row.get("source_tag_values", ""),
            "target_tag_values": row.get("target_tag_values", ""),
            "unresolved_events": row.get("unresolved_events", ""),
            "cue_domains": row.get("cue_domains", ""),
            "support_file_count": row.get("support_file_count", ""),
            "same_route_file_count": row.get("same_route_file_count", ""),
            "other_route_file_count": row.get("other_route_file_count", ""),
            "route_family_count": row.get("route_family_count", ""),
            "cue_file_count": row.get("cue_file_count", ""),
            "context_archetype_count": row.get("context_archetype_count", ""),
            "stage35_scope": "exact_context_and_in_memory_inverse_splice_only",
        })
    parked = by_shape.get(PARKED_SHAPE)
    if not parked or PARKED_PROFILE not in split_semicolon(parked.get("promoted_profile_ids", "")):
        raise ExactContextError("stage-34 report does not preserve the parked a570 existing-profile shape")
    parked_rows = [{
        "shape_id": PARKED_SHAPE,
        "profile_id": PARKED_PROFILE,
        "stage34_classification": parked.get("classification", ""),
        "stage35_status": "parked_existing_profile_not_reanalyzed",
        "next_gate": "await_isolated_runtime_validation_of_existing_profile",
    }]
    return target_rows, parked_rows


def collect_residual_exact_context_evidence(
    *, project_root: Path, workspace_root: Path, report_root: Path,
    maximum_event_bytes: int = 2 * 1024 * 1024,
) -> tuple[Path, dict[str, object]]:
    br = load_restoration_tool(project_root)
    with tempfile.TemporaryDirectory(prefix="br-residual-exact-") as temporary:
        temporary_root = Path(temporary)
        stage34 = evidence_dir(report_root, STAGE34_DIR, STAGE34_ARCHIVE, temporary_root)
        context = evidence_dir(report_root, CONTEXT_DIR, CONTEXT_ARCHIVE, temporary_root)
        migration = evidence_dir(report_root, MIGRATION_DIR, MIGRATION_ARCHIVE, temporary_root)

        stage34_summary = json.loads((stage34 / "SUMMARY.json").read_text(encoding="utf-8"))
        context_summary = json.loads((context / "SUMMARY.json").read_text(encoding="utf-8"))
        migration_summary = json.loads((migration / "SUMMARY.json").read_text(encoding="utf-8"))
        if stage34_summary.get("type") != "br_quartet_restoration_residual_scene_context_evidence_summary":
            raise ExactContextError("invalid stage-34 residual scene context summary")
        if context_summary.get("type") != "br_quartet_restoration_event_delta_context_evidence_summary":
            raise ExactContextError("invalid event delta context summary")
        if migration_summary.get("type") != "br_quartet_restoration_event_tag_migration_evidence_summary":
            raise ExactContextError("invalid event tag migration summary")

        target_rows, parked_rows = validate_stage34_targets(
            read_tsv(stage34 / "RESIDUAL_ROUTE_AND_SHARED_COHORTS.tsv")
        )
        occurrence_rows = [
            row for row in read_tsv(context / "EVENT_DELTA_CONTEXT_OCCURRENCES.tsv")
            if row.get("shape_id") in TARGET_SHAPES
        ]
        if not occurrence_rows:
            raise ExactContextError("event delta context report has no occurrences for stage-35 target shapes")
        occurrence_rows.sort(key=lambda row: (row.get("shape_id", ""), row.get("normalized_path", ""), parse_int(row.get("occurrence_index"))))
        comparisons = build_context_comparisons(occurrence_rows)

        known_schema_shape_ids = {
            br.event_residual_delta_shape_id(row)
            for row in read_tsv(migration / "EVENT_TAG_SCHEMA_MIGRATION_CANDIDATES.tsv")
            if row.get("classification") in {"broad_schema_migration_candidate", "recurrent_schema_delta_candidate"}
        }
        difference_reports = br.load_report_jsons(report_root, "differences")
        event_report = next(
            (row for row in difference_reports if str(row.get("source_archive_group", "")) == "br1_events"),
            None,
        )
        if event_report is None:
            raise ExactContextError("missing br1_events difference report")
        entry_by_path = {
            str(row.get("normalized_path", "")): row
            for row in event_report.get("entries", [])
            if row.get("scope_status") == "in_scope" and row.get("source") and row.get("target")
        }

        exact_rows: list[dict[str, object]] = []
        splice_rows: list[dict[str, object]] = []
        skipped_rows: list[dict[str, object]] = []
        for row in occurrence_rows:
            normalized_path = row.get("normalized_path", "")
            exact_rows.append({
                "shape_id": row.get("shape_id", ""),
                "normalized_path": normalized_path,
                "route_family": route_family(normalized_path),
                "occurrence_index": row.get("occurrence_index", ""),
                "cue_positive_occurrence": row.get("cue_positive_occurrence", ""),
                "cue_domains": row.get("cue_domains", ""),
                "pair_context_archetype_id": row.get("pair_context_archetype_id", ""),
                "source_span_start_word_index": row.get("source_span_start_word_index", ""),
                "source_span_end_word_index": row.get("source_span_end_word_index", ""),
                "target_span_start_word_index": row.get("target_span_start_word_index", ""),
                "target_span_end_word_index": row.get("target_span_end_word_index", ""),
                "source_before_structural_tokens": row.get("source_before_structural_tokens", ""),
                "source_delta_structural_tokens": row.get("source_delta_structural_tokens", ""),
                "source_after_structural_tokens": row.get("source_after_structural_tokens", ""),
                "target_before_structural_tokens": row.get("target_before_structural_tokens", ""),
                "target_delta_structural_tokens": row.get("target_delta_structural_tokens", ""),
                "target_after_structural_tokens": row.get("target_after_structural_tokens", ""),
                "source_context_signature_sha256": row.get("source_context_signature_sha256", ""),
                "target_context_signature_sha256": row.get("target_context_signature_sha256", ""),
                "known_schema_migration_shape": row.get("shape_id", "") in known_schema_shape_ids,
                "review_status": "exact_structural_context_metadata_only_no_tag_semantics_assigned",
            })
            entry = entry_by_path.get(normalized_path)
            if not entry:
                skipped_rows.append({
                    "shape_id": row.get("shape_id", ""), "normalized_path": normalized_path,
                    "occurrence_index": row.get("occurrence_index", ""), "reason": "difference_entry_missing",
                })
                continue
            source_ref = entry.get("source") or {}
            target_ref = entry.get("target") or {}
            source_path = br.inventory_workspace_file(
                workspace_root, "source", "br1_events", str(source_ref.get("archive", "")), str(source_ref.get("path", ""))
            )
            target_path = br.inventory_workspace_file(
                workspace_root, "target", "br1_events", str(target_ref.get("archive", "")), str(target_ref.get("path", ""))
            )
            if not source_path.is_file() or not target_path.is_file():
                skipped_rows.append({
                    "shape_id": row.get("shape_id", ""), "normalized_path": normalized_path,
                    "occurrence_index": row.get("occurrence_index", ""), "reason": "workspace_event_payload_missing",
                })
                continue
            if source_path.stat().st_size > maximum_event_bytes or target_path.stat().st_size > maximum_event_bytes:
                skipped_rows.append({
                    "shape_id": row.get("shape_id", ""), "normalized_path": normalized_path,
                    "occurrence_index": row.get("occurrence_index", ""), "reason": "maximum_event_bytes_exceeded",
                })
                continue
            try:
                metadata = simulate_exact_inverse_splice(
                    br=br, source_payload=source_path.read_bytes(), target_payload=target_path.read_bytes(), occurrence=row,
                )
            except (ExactContextError, br.RestorationError, OSError, ValueError, struct.error) as exc:
                skipped_rows.append({
                    "shape_id": row.get("shape_id", ""), "normalized_path": normalized_path,
                    "occurrence_index": row.get("occurrence_index", ""), "reason": f"splice_error:{type(exc).__name__}:{exc}",
                })
                continue
            splice_rows.append({
                "shape_id": row.get("shape_id", ""),
                "normalized_path": normalized_path,
                "route_family": route_family(normalized_path),
                "occurrence_index": row.get("occurrence_index", ""),
                "cue_positive_occurrence": row.get("cue_positive_occurrence", ""),
                "cue_domains": row.get("cue_domains", ""),
                "pair_context_archetype_id": row.get("pair_context_archetype_id", ""),
                **metadata,
            })

        gate_rows: list[dict[str, object]] = []
        for target in target_rows:
            shape_id = str(target["shape_id"])
            occurrences = [row for row in occurrence_rows if row.get("shape_id") == shape_id]
            splices = [row for row in splice_rows if row.get("shape_id") == shape_id]
            cue_occurrences = sum(parse_bool(row.get("cue_positive_occurrence")) for row in occurrences)
            noncue_occurrences = len(occurrences) - cue_occurrences
            route_count = len({route_family(row.get("normalized_path", "")) for row in occurrences if route_family(row.get("normalized_path", ""))})
            shared_cue_noncue = {
                row.get("left_context_archetype_id", "")
                for row in comparisons
                if row.get("shape_id") == shape_id
                and row.get("comparison_kind") == "cue_vs_noncue_control"
                and parse_bool(row.get("same_exact_pair_context_archetype"))
            }
            isolated = sum(row.get("splice_status") == "isolated_exact_inverse_splice_passed" for row in splices)
            classification, gate, reason = classify_promotion_gate(
                cue_occurrences=cue_occurrences,
                noncue_occurrences=noncue_occurrences,
                route_family_count=route_count,
                shared_cue_noncue_archetypes=len(shared_cue_noncue),
                splice_rows=len(splices),
                isolated_splice_rows=isolated,
            )
            gate_rows.append({
                "shape_id": shape_id,
                "stage34_classification": target.get("stage34_classification", ""),
                "occurrence_count": len(occurrences),
                "cue_occurrence_count": cue_occurrences,
                "noncue_occurrence_count": noncue_occurrences,
                "route_family_count": route_count,
                "exact_context_archetype_count": len({row.get("pair_context_archetype_id", "") for row in occurrences if row.get("pair_context_archetype_id")}),
                "shared_cue_noncue_archetype_count": len(shared_cue_noncue),
                "splice_validation_rows": len(splices),
                "isolated_splice_pass_rows": isolated,
                "all_splices_isolated": bool(splices) and isolated == len(splices),
                "stage35_classification": classification,
                "stage36_gate": gate,
                "gate_reason": reason,
                "runtime_validation_inferred": False,
                "censorship_semantics_inferred": False,
            })

        evidence_root = report_root / EVIDENCE_DIR_NAME
        if evidence_root.exists():
            shutil.rmtree(evidence_root)
        evidence_root.mkdir(parents=True, exist_ok=True)
        write_tsv(evidence_root / "TARGET_RESIDUAL_SHAPES.tsv", [
            "shape_id", "stage34_classification", "stage34_review_priority", "sequence_tag",
            "source_tag_values", "target_tag_values", "unresolved_events", "cue_domains",
            "support_file_count", "same_route_file_count", "other_route_file_count",
            "route_family_count", "cue_file_count", "context_archetype_count", "stage35_scope",
        ], target_rows)
        write_tsv(evidence_root / "PARKED_EXISTING_PROFILE_SHAPES.tsv", [
            "shape_id", "profile_id", "stage34_classification", "stage35_status", "next_gate",
        ], parked_rows)
        write_tsv(evidence_root / "RESIDUAL_EXACT_CONTEXT_OCCURRENCES.tsv", [
            "shape_id", "normalized_path", "route_family", "occurrence_index", "cue_positive_occurrence",
            "cue_domains", "pair_context_archetype_id", "source_span_start_word_index",
            "source_span_end_word_index", "target_span_start_word_index", "target_span_end_word_index",
            "source_before_structural_tokens", "source_delta_structural_tokens", "source_after_structural_tokens",
            "target_before_structural_tokens", "target_delta_structural_tokens", "target_after_structural_tokens",
            "source_context_signature_sha256", "target_context_signature_sha256",
            "known_schema_migration_shape", "review_status",
        ], exact_rows)
        write_tsv(evidence_root / "RESIDUAL_EXACT_CONTEXT_COMPARISONS.tsv", [
            "shape_id", "comparison_kind", "left_path", "left_cue_positive", "left_cue_domains",
            "left_context_archetype_id", "right_path", "right_cue_positive", "right_cue_domains",
            "right_context_archetype_id", "same_route_family", "same_exact_pair_context_archetype",
            "same_source_context_signature", "same_target_context_signature", "review_status",
        ], comparisons)
        write_tsv(evidence_root / "RESIDUAL_IN_MEMORY_SPLICE_VALIDATION.tsv", [
            "shape_id", "normalized_path", "route_family", "occurrence_index", "cue_positive_occurrence",
            "cue_domains", "pair_context_archetype_id", "source_span_start_word_index",
            "source_span_end_word_index", "target_span_start_word_index", "target_span_end_word_index",
            "source_span_word_count", "target_span_word_count", "source_span_sha256", "target_span_sha256",
            "candidate_size", "target_size", "candidate_size_delta", "candidate_sha256",
            "target_byte_difference_to_source", "candidate_byte_difference_to_source",
            "selected_shape_count_before", "selected_shape_count_after", "selected_occurrence_removed",
            "other_residual_shape_counter_unchanged", "other_residual_shape_count_before",
            "other_residual_shape_count_after", "target_header_preserved", "target_trailing_bytes_preserved",
            "candidate_header_valid", "candidate_post_header_family", "splice_status", "review_status",
        ], splice_rows)
        write_tsv(evidence_root / "RESIDUAL_SHAPE_PROMOTION_GATES.tsv", [
            "shape_id", "stage34_classification", "occurrence_count", "cue_occurrence_count",
            "noncue_occurrence_count", "route_family_count", "exact_context_archetype_count",
            "shared_cue_noncue_archetype_count", "splice_validation_rows", "isolated_splice_pass_rows",
            "all_splices_isolated", "stage35_classification", "stage36_gate", "gate_reason",
            "runtime_validation_inferred", "censorship_semantics_inferred",
        ], gate_rows)
        write_tsv(evidence_root / "RESIDUAL_EXACT_CONTEXT_SCAN_SKIPPED.tsv", [
            "shape_id", "normalized_path", "occurrence_index", "reason",
        ], skipped_rows)

        eligible = [row for row in gate_rows if row["stage36_gate"] == "eligible_for_stage_36_local_prototype_review"]
        summary: dict[str, object] = {
            "type": "br_quartet_restoration_residual_exact_context_evidence_summary",
            "format_version": 1,
            "tool_version": TOOL_VERSION,
            "source_residual_scene_context_tool_version": stage34_summary.get("tool_version"),
            "source_event_delta_context_tool_version": context_summary.get("tool_version"),
            "source_event_tag_migration_tool_version": migration_summary.get("tool_version"),
            "status": "three_uncovered_high_priority_shapes_exact_context_and_inverse_splice_validated_in_memory",
            "target_shape_rows": len(target_rows),
            "parked_existing_profile_shape_rows": len(parked_rows),
            "exact_context_occurrence_rows": len(exact_rows),
            "exact_context_comparison_rows": len(comparisons),
            "in_memory_splice_validation_rows": len(splice_rows),
            "isolated_in_memory_splice_rows": sum(row["splice_status"] == "isolated_exact_inverse_splice_passed" for row in splice_rows),
            "promotion_gate_rows": len(gate_rows),
            "stage36_eligible_shape_rows": len(eligible),
            "stage36_eligible_shape_ids": [row["shape_id"] for row in eligible],
            "skipped_rows": len(skipped_rows),
            "parameters": {"maximum_event_bytes": maximum_event_bytes},
            "policy": {
                "installed_games_modified": False,
                "candidate_ebd_payloads_written": False,
                "candidate_ebd_payloads_exported": False,
                "profile_manifests_modified": False,
                "activation_or_rollback_invoked": False,
                "dialogue_or_localized_text_exported": False,
                "opaque_context_values_exported": False,
                "safe_structural_tokens_and_hashes_only": True,
                "event_tag_semantics_assigned": False,
                "runtime_validation_inferred": False,
                "censorship_classification_inferred": False,
                "parked_existing_profile_duplicated": False,
                "legacy_dlc_in_scope": False,
                "translation_or_core_files_modified": False,
            },
            "next_action": (
                "Upload this report. Only shapes explicitly marked eligible_for_stage_36_local_prototype_review "
                "may be considered for a separate local metadata-gated prototype; route/schema shapes remain evidence-only."
            ),
        }
        atomic_json(evidence_root / "SUMMARY.json", summary)
        output = report_root / REPORT_NAME
        make_report_archive(evidence_root, output)
        return output, summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", required=True)
    parser.add_argument("--workspace-root")
    parser.add_argument("--report-root")
    parser.add_argument("--maximum-event-bytes", type=int, default=2 * 1024 * 1024)
    args = parser.parse_args()
    project_root = Path(args.project_root).expanduser().resolve()
    if not project_root.is_dir():
        raise ExactContextError(f"project root does not exist: {project_root}")
    default_workspace = project_root / ".local/build/quartet_restoration"
    default_reports = project_root / ".local/reports/quartet_restoration"
    workspace_root = Path(args.workspace_root).expanduser().resolve() if args.workspace_root else default_workspace
    report_root = Path(args.report_root).expanduser().resolve() if args.report_root else default_reports
    try:
        workspace_root.relative_to(default_workspace)
        report_root.relative_to(default_reports)
    except ValueError as exc:
        raise ExactContextError("workspace/report roots must remain inside quartet_restoration local roots") from exc
    output, summary = collect_residual_exact_context_evidence(
        project_root=project_root,
        workspace_root=workspace_root,
        report_root=report_root,
        maximum_event_bytes=args.maximum_event_bytes,
    )
    print(f"Target shapes: {summary['target_shape_rows']}")
    print(f"Exact-context occurrences: {summary['exact_context_occurrence_rows']}")
    print(f"Isolated inverse splices: {summary['isolated_in_memory_splice_rows']}")
    print(f"Stage-36 eligible shapes: {summary['stage36_eligible_shape_rows']}")
    print(f"Report: {output}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except ExactContextError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
