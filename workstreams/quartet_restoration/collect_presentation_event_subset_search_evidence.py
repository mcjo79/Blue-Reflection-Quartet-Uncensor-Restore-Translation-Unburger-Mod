#!/usr/bin/env python3
"""Search bounded cue-linked residual subsets for additional static event candidates.

This metadata-only stage continues the stage-40 backlog after the seventh local
profile has been registered.  It examines only high-priority, unregistered
presentation-event leads.  For every event it reconstructs bounded non-empty
subsets of cue-positive stage-23 residual occurrences in memory, excludes
broad/recurrent schema candidates and cue/non-cue shared exact contexts, and
requires exact target reverse round-trip plus preservation of every non-selected
residual-shape counter.  No EBD, PAK, manifest, activation or game write is
produced.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import importlib
import itertools
import json
import os
import shutil
import struct
import subprocess
import sys
import tempfile
from collections import Counter, defaultdict
from pathlib import Path, PurePosixPath
from typing import Any, Iterable, Mapping, Sequence

WORKSTREAM_ID = "quartet_restoration"
TOOL_VERSION = "0.0.51"
REPORT_NAME = "BR_quartet_restoration_presentation_event_subset_search_evidence.tar.zst"
EVIDENCE_DIR_NAME = "presentation_event_subset_search_evidence"

REPORT_SPECS = {
    "core": ("core_profile_manifest_evidence", "BR_quartet_restoration_core_profile_manifest_evidence.tar.zst"),
    "backlog": ("presentation_event_backlog_evidence", "BR_quartet_restoration_presentation_event_backlog_evidence.tar.zst"),
    "prototype": ("presentation_event_backlog_prototype_evidence", "BR_quartet_restoration_presentation_event_backlog_prototype_evidence.tar.zst"),
    "context": ("event_delta_context_evidence", "BR_quartet_restoration_event_delta_context_evidence.tar.zst"),
    "migration": ("event_tag_migration_evidence", "BR_quartet_restoration_event_tag_migration_evidence.tar.zst"),
}


class SubsetSearchError(RuntimeError):
    pass


def parse_bool(value: object) -> bool:
    return str(value).strip().casefold() in {"1", "true", "yes", "y"}


def parse_int(value: object, default: int = 0) -> int:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return default


def split_cell(value: object) -> list[str]:
    return [part for part in str(value or "").split(";") if part]


def normalize_event_member(path: object) -> str:
    value = str(path or "").replace("\\", "/").lstrip("./")
    for prefix in ("event/b1/event_jp/", "data/b1/event/event_jp/", "event/event_jp/"):
        if value.casefold().startswith(prefix.casefold()):
            return "event/event_jp/" + value[len(prefix):]
    return value


def event_id(path: str) -> str:
    stem = PurePosixPath(path).stem
    return stem[len("event_"):] if stem.casefold().startswith("event_") else stem


def safe_member_name(raw: str) -> str:
    path = PurePosixPath(raw)
    if path.is_absolute() or not path.parts or ".." in path.parts:
        raise SubsetSearchError(f"unsafe report archive member: {raw}")
    return path.as_posix()


def read_tsv(path: Path, *, required: bool = True) -> list[dict[str, str]]:
    if not path.is_file():
        if required:
            raise SubsetSearchError(f"missing prerequisite table: {path}")
        return []
    with path.open("r", encoding="utf-8", newline="") as handle:
        return [dict(row) for row in csv.DictReader(handle, delimiter="\t")]


def write_tsv(path: Path, fieldnames: Sequence[str], rows: Iterable[Mapping[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fieldnames})


def load_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise SubsetSearchError(f"missing prerequisite JSON: {path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SubsetSearchError(f"invalid JSON {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise SubsetSearchError(f"expected JSON object: {path}")
    return value


def extract_archive(archive: Path, destination: Path) -> Path:
    if not archive.is_file():
        raise SubsetSearchError(f"missing prerequisite report archive: {archive}")
    listed = subprocess.run(
        ["tar", "--zstd", "-tf", str(archive)], text=True,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False,
    )
    if listed.returncode != 0:
        raise SubsetSearchError(f"cannot list {archive}: {listed.stderr.strip()}")
    roots: set[str] = set()
    for raw in listed.stdout.splitlines():
        if raw.strip():
            roots.add(PurePosixPath(safe_member_name(raw.strip())).parts[0])
    if len(roots) != 1:
        raise SubsetSearchError(f"expected one report root in {archive}, found {sorted(roots)}")
    destination.mkdir(parents=True, exist_ok=True)
    completed = subprocess.run(
        ["tar", "--zstd", "-xf", str(archive), "-C", str(destination)], text=True,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False,
    )
    if completed.returncode != 0:
        raise SubsetSearchError(f"cannot extract {archive}: {completed.stderr.strip()}")
    return destination / next(iter(roots))


def locate_report_root(report_root: Path, key: str, temporary: Path) -> Path:
    directory_name, archive_name = REPORT_SPECS[key]
    direct = report_root / directory_name
    return direct if direct.is_dir() else extract_archive(report_root / archive_name, temporary / key)


def load_restoration_tool(project_root: Path) -> Any:
    tool_root = project_root / "Blue_Reflection_Text_Tool"
    tool_path = tool_root / "br_restoration_tool.py"
    if not tool_path.is_file():
        raise SubsetSearchError(f"missing restoration tool: {tool_path}")
    sys.path.insert(0, str(tool_root))
    try:
        return importlib.import_module("br_restoration_tool")
    finally:
        try:
            sys.path.remove(str(tool_root))
        except ValueError:
            pass


def make_report_archive(source_dir: Path, output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(output.name + ".tmp")
    if temporary.exists():
        temporary.unlink()
    result = subprocess.run(
        ["tar", "--zstd", "-cf", str(temporary), "-C", str(source_dir.parent), source_dir.name],
        text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False,
    )
    if result.returncode != 0:
        raise SubsetSearchError(f"cannot create report archive: {result.stderr.strip()}")
    os.replace(temporary, output)


def byte_difference_count(left: bytes, right: bytes) -> int:
    overlap = min(len(left), len(right))
    return sum(a != b for a, b in zip(left[:overlap], right[:overlap])) + abs(len(left) - len(right))


def occurrence_key(row: Mapping[str, object]) -> tuple[str, str, int]:
    return (
        normalize_event_member(row.get("normalized_path", "")),
        str(row.get("shape_id", "")),
        parse_int(row.get("occurrence_index"), -1),
    )


def shape_counter(br: Any, source_profile: Mapping[str, object], target_profile: Mapping[str, object]) -> Counter[str]:
    rows = br.compare_ebd_tag_atoms(source_profile["atoms"], target_profile["atoms"])
    return Counter(br.event_residual_delta_shape_id(row) for row in rows)


def build_operations(
    *, br: Any, source_payload: bytes, target_payload: bytes,
    selected_occurrences: Sequence[Mapping[str, object]],
) -> tuple[list[dict[str, Any]], Mapping[str, object], Mapping[str, object]]:
    source_header = br.parse_ebd_header_schema(source_payload)
    target_header = br.parse_ebd_header_schema(target_payload)
    if source_header.get("classification") != "observed_ebd_name_description_header":
        raise SubsetSearchError("source EBD header is not recognized")
    if target_header.get("classification") != "observed_ebd_name_description_header":
        raise SubsetSearchError("target EBD header is not recognized")
    source_profile = br.profile_ebd_post_header_words(
        source_payload, int(source_header["header_end"]), maximum_words=max(1, len(source_payload) // 4 + 8)
    )
    target_profile = br.profile_ebd_post_header_words(
        target_payload, int(target_header["header_end"]), maximum_words=max(1, len(target_payload) // 4 + 8)
    )
    matches: defaultdict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in br.compare_ebd_tag_atoms(source_profile["atoms"], target_profile["atoms"]):
        matches[br.event_residual_delta_shape_id(row)].append(row)
    operations: list[dict[str, Any]] = []
    for occurrence in selected_occurrences:
        shape_id = str(occurrence.get("shape_id", ""))
        index = parse_int(occurrence.get("occurrence_index"), -1)
        candidates = matches.get(shape_id, [])
        if index < 0 or index >= len(candidates):
            raise SubsetSearchError(f"reported occurrence cannot be reproduced: {shape_id}:{index}")
        delta = candidates[index]
        source_start, source_end = br.event_atom_word_span(
            source_profile["atoms"], int(delta["source_atom_start"]), int(delta["source_atom_end"]),
            int(source_profile["word_count"]),
        )
        target_start, target_end = br.event_atom_word_span(
            target_profile["atoms"], int(delta["target_atom_start"]), int(delta["target_atom_end"]),
            int(target_profile["word_count"]),
        )
        operations.append({
            "shape_id": shape_id,
            "occurrence_index": index,
            "source_start": source_start,
            "source_end": source_end,
            "target_start": target_start,
            "target_end": target_end,
            "source_words": list(source_profile["words"])[source_start:source_end],
            "target_words": list(target_profile["words"])[target_start:target_end],
        })
    return operations, source_profile, target_profile


def reverse_candidate(
    *, candidate_payload: bytes, target_payload: bytes, operations: Sequence[Mapping[str, object]], br: Any,
) -> bytes:
    candidate_header = br.parse_ebd_header_schema(candidate_payload)
    target_header = br.parse_ebd_header_schema(target_payload)
    if candidate_header.get("classification") != "observed_ebd_name_description_header":
        return b""
    if target_header.get("classification") != "observed_ebd_name_description_header":
        return b""
    if int(candidate_header["header_end"]) != int(target_header["header_end"]):
        return b""
    candidate_profile = br.profile_ebd_post_header_words(
        candidate_payload, int(candidate_header["header_end"]), maximum_words=max(1, len(candidate_payload) // 4 + 8)
    )
    target_profile = br.profile_ebd_post_header_words(
        target_payload, int(target_header["header_end"]), maximum_words=max(1, len(target_payload) // 4 + 8)
    )
    candidate_end = int(candidate_header["header_end"]) + int(candidate_profile["word_count"]) * 4
    target_end = int(target_header["header_end"]) + int(target_profile["word_count"]) * 4
    if candidate_payload[candidate_end:] != target_payload[target_end:]:
        return b""
    cumulative_shift = 0
    mapped: list[tuple[int, int, list[int]]] = []
    for operation in sorted(operations, key=lambda row: (int(row["target_start"]), int(row["target_end"]))):
        target_start = int(operation["target_start"])
        target_finish = int(operation["target_end"])
        source_words = list(operation["source_words"])
        candidate_start = target_start + cumulative_shift
        candidate_finish = candidate_start + len(source_words)
        mapped.append((candidate_start, candidate_finish, list(operation["target_words"])))
        cumulative_shift += len(source_words) - (target_finish - target_start)
    rebuilt = list(candidate_profile["words"])
    for start, finish, target_words in sorted(mapped, reverse=True):
        rebuilt[start:finish] = target_words
    packed = struct.pack(f"<{len(rebuilt)}I", *rebuilt) if rebuilt else b""
    return target_payload[:int(target_header["header_end"])] + packed + target_payload[target_end:]


def validate_core_report(root: Path) -> dict[str, Any]:
    summary = load_json(root / "SUMMARY.json")
    if summary.get("type") != "br_quartet_restoration_core_profile_manifest_evidence_summary":
        raise SubsetSearchError("stage-43 report has an unexpected summary type")
    if summary.get("tool_version") != "0.0.50":
        raise SubsetSearchError(f"stage-43 report tool version is {summary.get('tool_version')!r}, expected '0.0.50'")
    if summary.get("status") != "all_current_local_profiles_registered_runtime_unvalidated":
        raise SubsetSearchError(f"stage-43 report status is unexpected: {summary.get('status')!r}")
    if parse_int(summary.get("profile_rows"), -1) != 7:
        raise SubsetSearchError("stage-43 report must contain seven profiles")
    if parse_int(summary.get("pack11_profile_rows"), -1) != 5 or parse_int(summary.get("pack10_01_profile_rows"), -1) != 2:
        raise SubsetSearchError("stage-43 target split changed")
    if parse_int(summary.get("runtime_validated_profile_rows"), -1) != 0:
        raise SubsetSearchError("stage-43 profiles must remain runtime-unvalidated")
    rows = read_tsv(root / "CORE_PROFILE_MANIFESTS.tsv")
    if len(rows) != 7 or any(row.get("validation_status") != "passed" for row in rows):
        raise SubsetSearchError("stage-43 manifest rows are incomplete or invalid")
    required = "candidate_single_scene_multishape_em01_050_954fadd61cac"
    if required not in {row.get("profile_id") for row in rows}:
        raise SubsetSearchError("stage-43 report does not contain the registered em01_050 profile")
    return summary


def load_registry_event_owners(project_root: Path) -> dict[str, list[str]]:
    root = project_root / ".local/build/quartet_restoration/core_profiles/generated"
    if not root.is_dir():
        raise SubsetSearchError(f"missing generated core registry: {root}")
    manifests = sorted(root.glob("*.json"))
    if len(manifests) != 7:
        raise SubsetSearchError(f"expected seven generated profile manifests, found {len(manifests)}")
    owners: defaultdict[str, list[str]] = defaultdict(list)
    for manifest_path in manifests:
        data = load_json(manifest_path)
        if data.get("workstream_id") != WORKSTREAM_ID:
            raise SubsetSearchError(f"foreign manifest in restoration registry: {manifest_path}")
        if parse_bool(data.get("runtime_validated")):
            raise SubsetSearchError(f"runtime-validated manifest is not allowed here: {manifest_path}")
        if str(data.get("target_relative_path", "")).casefold() != "data/pack11.pak".casefold():
            continue
        profile_id = str(data.get("profile_id", manifest_path.stem))
        changed = data.get("changed_members", [])
        if not isinstance(changed, list):
            raise SubsetSearchError(f"changed_members is not a list: {manifest_path}")
        for member in changed:
            owners[normalize_event_member(member)].append(profile_id)
    return dict(owners)


def evaluate_combination(
    *, br: Any, source_payload: bytes, target_payload: bytes,
    occurrences: Sequence[Mapping[str, object]], control_by_shape: Mapping[str, Mapping[str, object]],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    candidate, metadata, residuals = br.construct_composite_inverse_event_candidate(
        source_payload=source_payload, target_payload=target_payload, selected_occurrences=occurrences,
    )
    if candidate is None:
        return {"status": str(metadata.get("status", "candidate_failed")), "passes": False}, []
    operations, source_profile, target_profile = build_operations(
        br=br, source_payload=source_payload, target_payload=target_payload, selected_occurrences=occurrences,
    )
    reversed_payload = reverse_candidate(candidate_payload=candidate, target_payload=target_payload, operations=operations, br=br)
    candidate_header = br.parse_ebd_header_schema(candidate)
    candidate_profile = br.profile_ebd_post_header_words(
        candidate, int(candidate_header.get("header_end", 0)), maximum_words=max(1, len(candidate) // 4 + 8),
    )
    before_counter = shape_counter(br, source_profile, target_profile)
    after_counter = shape_counter(br, source_profile, candidate_profile)
    selected_shapes = {str(row.get("shape_id", "")) for row in occurrences}
    nonselected_before = before_counter.copy()
    nonselected_after = after_counter.copy()
    for shape_id in selected_shapes:
        nonselected_before.pop(shape_id, None)
        nonselected_after.pop(shape_id, None)
    shared_context_count = sum(
        parse_int(control_by_shape.get(shape_id, {}).get("shared_cue_noncue_context_archetype_count"))
        for shape_id in selected_shapes
    )
    target_distance = byte_difference_count(target_payload, source_payload)
    candidate_distance = byte_difference_count(candidate, source_payload)
    checks = {
        "all_occurrences_cue_positive": all(parse_bool(row.get("cue_positive_occurrence")) for row in occurrences),
        "no_shared_cue_noncue_exact_context": shared_context_count == 0,
        "all_selected_shapes_removed": parse_bool(metadata.get("all_selected_shapes_removed")),
        "selected_shape_count_after_zero": parse_int(metadata.get("selected_shape_count_after")) == 0,
        "no_introduced_coarse_shapes": parse_int(metadata.get("introduced_coarse_shape_count")) == 0,
        "no_nonselected_coarse_shapes_removed": parse_int(metadata.get("removed_nonselected_coarse_shape_count")) == 0,
        "all_nonselected_shape_counters_preserved": nonselected_before == nonselected_after,
        "candidate_header_preserved_from_target": parse_bool(metadata.get("candidate_header_preserved_from_target")),
        "candidate_trailing_preserved_from_target": parse_bool(metadata.get("candidate_trailing_bytes_preserved_from_target")),
        "candidate_header_valid": metadata.get("candidate_header_classification") == "observed_ebd_name_description_header",
        "exact_target_reverse_roundtrip": reversed_payload == target_payload,
        "candidate_not_farther_from_original": candidate_distance <= target_distance,
    }
    passes_structural = all(value for key, value in checks.items() if key != "candidate_not_farther_from_original")
    strict_improvement = candidate_distance < target_distance
    exact_original = candidate == source_payload
    passes = passes_structural and candidate_distance <= target_distance
    return {
        "status": "passed" if passes else "failed",
        "passes": passes,
        "passes_structural": passes_structural,
        "strict_improvement": strict_improvement,
        "exact_original": exact_original,
        "candidate_sha256": hashlib.sha256(candidate).hexdigest(),
        "candidate_size": len(candidate),
        "target_distance_to_source": target_distance,
        "candidate_distance_to_source": candidate_distance,
        "distance_improvement": target_distance - candidate_distance,
        "selected_occurrence_count": len(occurrences),
        "selected_shape_count": len(selected_shapes),
        "selected_shape_ids": ";".join(sorted(selected_shapes)),
        "shared_cue_noncue_context_count": shared_context_count,
        "remaining_residual_rows": len(residuals),
        "remaining_residual_shape_ids": ";".join(sorted({str(row.get("shape_id", "")) for row in residuals})),
        "checks": checks,
    }, residuals


def collect_subset_search(
    *, project_root: Path, workspace_root: Path, report_root: Path,
    maximum_event_bytes: int = 2 * 1024 * 1024,
    maximum_subset_occurrences: int = 12,
    maximum_combinations_per_event: int = 4095,
    top_combinations_per_event: int = 32,
) -> tuple[Path, dict[str, object]]:
    project_root = project_root.expanduser().resolve()
    workspace_root = workspace_root.expanduser().resolve()
    report_root = report_root.expanduser().resolve()
    if maximum_subset_occurrences < 1 or maximum_subset_occurrences > 16:
        raise SubsetSearchError("maximum_subset_occurrences must be in the range 1..16")
    if maximum_combinations_per_event < 1:
        raise SubsetSearchError("maximum_combinations_per_event must be positive")
    if top_combinations_per_event < 1:
        raise SubsetSearchError("top_combinations_per_event must be positive")
    br = load_restoration_tool(project_root)

    with tempfile.TemporaryDirectory(prefix="br-event-subset-search-") as temporary_name:
        temporary = Path(temporary_name)
        roots = {key: locate_report_root(report_root, key, temporary) for key in REPORT_SPECS}
        core_summary = validate_core_report(roots["core"])
        registry_owners = load_registry_event_owners(project_root)

        backlog_summary = load_json(roots["backlog"] / "SUMMARY.json")
        if backlog_summary.get("type") != "br_quartet_restoration_presentation_event_backlog_evidence_summary" or backlog_summary.get("tool_version") != "0.0.46":
            raise SubsetSearchError("stage-40 backlog report is not the expected 0.0.46 report")
        prototype_summary = load_json(roots["prototype"] / "SUMMARY.json")
        if prototype_summary.get("type") != "br_quartet_restoration_presentation_event_backlog_prototype_evidence_summary" or prototype_summary.get("tool_version") != "0.0.48":
            raise SubsetSearchError("stage-41 prototype report is not the corrected 0.0.48 report")
        if parse_int(prototype_summary.get("promoted_profile_rows"), -1) != 1 or parse_int(prototype_summary.get("validation_failures"), -1) != 1:
            raise SubsetSearchError("stage-41 corrected outcome changed")
        context_summary = load_json(roots["context"] / "SUMMARY.json")
        if context_summary.get("type") != "br_quartet_restoration_event_delta_context_evidence_summary" or context_summary.get("tool_version") != "0.0.27":
            raise SubsetSearchError("stage-23 context report is not the expected 0.0.27 report")
        migration_summary = load_json(roots["migration"] / "SUMMARY.json")
        if migration_summary.get("type") != "br_quartet_restoration_event_tag_migration_evidence_summary" or migration_summary.get("tool_version") != "0.0.24":
            raise SubsetSearchError("stage-24 migration report is not the expected 0.0.24 report")

        validation_rows = read_tsv(roots["prototype"] / "PRESENTATION_EVENT_BACKLOG_VALIDATION.tsv")
        ce07_failures = [
            row for row in validation_rows
            if normalize_event_member(row.get("normalized_path", "")) == "event/event_jp/ce07/event_ce07_060.ebd"
            and not parse_bool(row.get("passed"))
        ]
        if len(ce07_failures) != 1 or ce07_failures[0].get("check_name") != "candidate_not_farther_from_original":
            raise SubsetSearchError("ce07_060 must have exactly the known distance-quality failure")

        backlog_rows = read_tsv(roots["backlog"] / "EVENT_CANDIDATE_BACKLOG.tsv")
        candidate_backlog: dict[str, dict[str, str]] = {}
        allowed_classes = {"cue_linked_residual_needs_static_reconstruction", "isolated_cue_inverse_splice_candidate"}
        for row in backlog_rows:
            path = normalize_event_member(row.get("normalized_path", ""))
            if path in registry_owners:
                continue
            if row.get("classification") not in allowed_classes:
                continue
            if row.get("review_priority") not in {"critical", "high"}:
                continue
            candidate_backlog[path] = row

        occurrence_rows = read_tsv(roots["context"] / "EVENT_DELTA_CONTEXT_OCCURRENCES.tsv")
        occurrences_by_path: defaultdict[str, list[dict[str, str]]] = defaultdict(list)
        for row in occurrence_rows:
            path = normalize_event_member(row.get("normalized_path", ""))
            if path in candidate_backlog and parse_bool(row.get("cue_positive_occurrence")):
                occurrences_by_path[path].append(row)
        for rows in occurrences_by_path.values():
            rows.sort(key=lambda row: (str(row.get("shape_id", "")), parse_int(row.get("occurrence_index"), -1)))

        control_by_shape = {
            str(row.get("shape_id", "")): row
            for row in read_tsv(roots["context"] / "EVENT_DELTA_CUE_NONCUE_COMPARISON.tsv")
        }
        broad_shape_ids = {
            br.event_residual_delta_shape_id(row)
            for row in read_tsv(roots["migration"] / "EVENT_TAG_SCHEMA_MIGRATION_CANDIDATES.tsv")
            if row.get("classification") in {"broad_schema_migration_candidate", "recurrent_schema_delta_candidate"}
        }

        differences = br.load_report_jsons(report_root, "differences")
        event_report = next((row for row in differences if str(row.get("source_archive_group", "")) == "br1_events"), None)
        if event_report is None:
            raise SubsetSearchError("missing br1_events difference report")
        entry_by_path = {
            normalize_event_member(row.get("normalized_path", "")): row
            for row in event_report.get("entries", [])
            if row.get("scope_status") == "in_scope" and row.get("source") and row.get("target")
        }

        event_rows: list[dict[str, object]] = []
        combination_rows: list[dict[str, object]] = []
        selected_rows: list[dict[str, object]] = []
        residual_rows: list[dict[str, object]] = []
        skipped_rows: list[dict[str, object]] = []

        for path in sorted(candidate_backlog):
            backlog = candidate_backlog[path]
            raw_occurrences = occurrences_by_path.get(path, [])
            excluded_broad = [row for row in raw_occurrences if str(row.get("shape_id", "")) in broad_shape_ids]
            eligible = [row for row in raw_occurrences if str(row.get("shape_id", "")) not in broad_shape_ids]
            if not eligible:
                skipped_rows.append({"normalized_path": path, "reason": "no_eligible_cue_positive_nonmigration_occurrences"})
                continue
            if len(eligible) > maximum_subset_occurrences:
                skipped_rows.append({
                    "normalized_path": path,
                    "reason": "maximum_subset_occurrences_exceeded",
                    "eligible_occurrence_count": len(eligible),
                })
                continue
            possible = (1 << len(eligible)) - 1
            if possible > maximum_combinations_per_event:
                skipped_rows.append({
                    "normalized_path": path,
                    "reason": "maximum_combinations_per_event_exceeded",
                    "eligible_occurrence_count": len(eligible),
                    "possible_combination_count": possible,
                })
                continue
            entry = entry_by_path.get(path)
            if entry is None:
                skipped_rows.append({"normalized_path": path, "reason": "difference_entry_missing"})
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
                skipped_rows.append({"normalized_path": path, "reason": "workspace_event_payload_missing"})
                continue
            if source_path.stat().st_size > maximum_event_bytes or target_path.stat().st_size > maximum_event_bytes:
                skipped_rows.append({"normalized_path": path, "reason": "maximum_event_bytes_exceeded"})
                continue
            source_payload = source_path.read_bytes()
            target_payload = target_path.read_bytes()
            if source_ref.get("sha256") and hashlib.sha256(source_payload).hexdigest() != str(source_ref.get("sha256")):
                skipped_rows.append({"normalized_path": path, "reason": "source_payload_sha256_mismatch"})
                continue
            if target_ref.get("sha256") and hashlib.sha256(target_payload).hexdigest() != str(target_ref.get("sha256")):
                skipped_rows.append({"normalized_path": path, "reason": "target_payload_sha256_mismatch"})
                continue

            evaluated: list[tuple[dict[str, Any], tuple[int, ...], list[dict[str, Any]]]] = []
            failed_candidate_count = 0
            for subset_size in range(1, len(eligible) + 1):
                for indices in itertools.combinations(range(len(eligible)), subset_size):
                    subset = [eligible[index] for index in indices]
                    try:
                        result, residuals = evaluate_combination(
                            br=br, source_payload=source_payload, target_payload=target_payload,
                            occurrences=subset, control_by_shape=control_by_shape,
                        )
                    except (SubsetSearchError, br.RestorationError, OSError, ValueError, struct.error):
                        failed_candidate_count += 1
                        continue
                    if result.get("status") == "candidate_failed":
                        failed_candidate_count += 1
                        continue
                    evaluated.append((result, indices, residuals))

            ranked = sorted(
                evaluated,
                key=lambda item: (
                    not bool(item[0].get("passes")),
                    not bool(item[0].get("exact_original")),
                    not bool(item[0].get("strict_improvement")),
                    -parse_int(item[0].get("selected_occurrence_count")),
                    -parse_int(item[0].get("distance_improvement")),
                    parse_int(item[0].get("remaining_residual_rows")),
                    str(item[0].get("candidate_sha256", "")),
                ),
            )
            best = ranked[0] if ranked else None
            promotable = bool(best and best[0].get("passes") and best[0].get("strict_improvement"))
            best_id = ""
            if best:
                best_id = hashlib.sha256(
                    (path + "|" + ";".join(str(index) for index in best[1]) + "|" + str(best[0].get("candidate_sha256", ""))).encode("utf-8")
                ).hexdigest()[:16]
            classification = (
                "strictly_improving_subset_ready_for_local_prototype"
                if promotable else
                "structurally_valid_subset_without_strict_original_improvement"
                if best and best[0].get("passes") else
                "no_structurally_valid_subset"
            )
            event_rows.append({
                "normalized_path": path,
                "event_id": event_id(path),
                "cue_domains": backlog.get("cue_domains", ""),
                "backlog_classification": backlog.get("classification", ""),
                "review_priority": backlog.get("review_priority", ""),
                "raw_cue_positive_occurrence_count": len(raw_occurrences),
                "excluded_broad_or_recurrent_occurrence_count": len(excluded_broad),
                "eligible_occurrence_count": len(eligible),
                "combination_count_tested": len(evaluated),
                "candidate_construction_failures": failed_candidate_count,
                "passing_combination_count": sum(bool(item[0].get("passes")) for item in evaluated),
                "strictly_improving_combination_count": sum(bool(item[0].get("passes") and item[0].get("strict_improvement")) for item in evaluated),
                "best_subset_id": best_id,
                "best_selected_occurrence_count": best[0].get("selected_occurrence_count", "") if best else "",
                "best_selected_shape_ids": best[0].get("selected_shape_ids", "") if best else "",
                "target_distance_to_source": best[0].get("target_distance_to_source", "") if best else "",
                "best_candidate_distance_to_source": best[0].get("candidate_distance_to_source", "") if best else "",
                "best_distance_improvement": best[0].get("distance_improvement", "") if best else "",
                "best_candidate_sha256": best[0].get("candidate_sha256", "") if best else "",
                "best_remaining_residual_rows": best[0].get("remaining_residual_rows", "") if best else "",
                "classification": classification,
                "safe_to_build_local_profile_without_runtime": promotable,
                "runtime_test_deferred": True,
                "next_gate": (
                    "build_one_separate_checksum_gated_local_subset_profile"
                    if promotable else "retain_in_static_backlog_for_further_decoding"
                ),
            })

            for rank, (result, indices, _) in enumerate(ranked[:top_combinations_per_event], start=1):
                subset_id = hashlib.sha256(
                    (path + "|" + ";".join(str(index) for index in indices) + "|" + str(result.get("candidate_sha256", ""))).encode("utf-8")
                ).hexdigest()[:16]
                combination_rows.append({
                    "normalized_path": path,
                    "subset_rank": rank,
                    "subset_id": subset_id,
                    "selected_occurrence_indices": ";".join(str(index) for index in indices),
                    "selected_occurrence_count": result.get("selected_occurrence_count", ""),
                    "selected_shape_count": result.get("selected_shape_count", ""),
                    "selected_shape_ids": result.get("selected_shape_ids", ""),
                    "candidate_sha256": result.get("candidate_sha256", ""),
                    "candidate_size": result.get("candidate_size", ""),
                    "target_distance_to_source": result.get("target_distance_to_source", ""),
                    "candidate_distance_to_source": result.get("candidate_distance_to_source", ""),
                    "distance_improvement": result.get("distance_improvement", ""),
                    "remaining_residual_rows": result.get("remaining_residual_rows", ""),
                    "remaining_residual_shape_ids": result.get("remaining_residual_shape_ids", ""),
                    "shared_cue_noncue_context_count": result.get("shared_cue_noncue_context_count", ""),
                    "passes_structural_gates": result.get("passes_structural", False),
                    "candidate_not_farther_from_original": result.get("checks", {}).get("candidate_not_farther_from_original", False),
                    "strict_improvement": result.get("strict_improvement", False),
                    "exact_original": result.get("exact_original", False),
                    "passes_all_subset_gates": result.get("passes", False),
                    "review_status": "bounded_in_memory_subset_evidence_not_runtime_or_censorship_validation",
                })

            if best:
                best_result, best_indices, best_residuals = best
                for ordinal, index in enumerate(best_indices):
                    occurrence = eligible[index]
                    selected_rows.append({
                        "normalized_path": path,
                        "best_subset_id": best_id,
                        "selection_order": ordinal,
                        "eligible_occurrence_index": index,
                        "shape_id": occurrence.get("shape_id", ""),
                        "occurrence_index": occurrence.get("occurrence_index", ""),
                        "cue_domains": occurrence.get("cue_domains", ""),
                        "selection_reasons": occurrence.get("selection_reasons", ""),
                        "shared_cue_noncue_context_archetype_count": control_by_shape.get(str(occurrence.get("shape_id", "")), {}).get("shared_cue_noncue_context_archetype_count", ""),
                        "review_status": "best_subset_component_not_yet_written_as_payload",
                    })
                for residual in best_residuals:
                    residual_rows.append({
                        "normalized_path": path,
                        "best_subset_id": best_id,
                        "shape_id": residual.get("shape_id", ""),
                        "sequence_tag": residual.get("sequence_tag", ""),
                        "source_atom_count": residual.get("source_atom_count", ""),
                        "target_atom_count": residual.get("target_atom_count", ""),
                        "classification": residual.get("classification", ""),
                        "review_status": "best_subset_remaining_residual_not_assigned_semantics",
                    })

        event_rows.sort(key=lambda row: (not parse_bool(row.get("safe_to_build_local_profile_without_runtime")), str(row.get("normalized_path", ""))))
        combination_rows.sort(key=lambda row: (str(row.get("normalized_path", "")), parse_int(row.get("subset_rank"))))
        selected_rows.sort(key=lambda row: (str(row.get("normalized_path", "")), parse_int(row.get("selection_order"))))
        residual_rows.sort(key=lambda row: (str(row.get("normalized_path", "")), str(row.get("shape_id", ""))))
        skipped_rows.sort(key=lambda row: (str(row.get("normalized_path", "")), str(row.get("reason", ""))))

        evidence_root = report_root / EVIDENCE_DIR_NAME
        if evidence_root.exists():
            shutil.rmtree(evidence_root)
        evidence_root.mkdir(parents=True, exist_ok=True)
        write_tsv(evidence_root / "PRESENTATION_EVENT_SUBSET_SEARCH_EVENTS.tsv", [
            "normalized_path", "event_id", "cue_domains", "backlog_classification", "review_priority",
            "raw_cue_positive_occurrence_count", "excluded_broad_or_recurrent_occurrence_count",
            "eligible_occurrence_count", "combination_count_tested", "candidate_construction_failures",
            "passing_combination_count", "strictly_improving_combination_count", "best_subset_id",
            "best_selected_occurrence_count", "best_selected_shape_ids", "target_distance_to_source",
            "best_candidate_distance_to_source", "best_distance_improvement", "best_candidate_sha256",
            "best_remaining_residual_rows", "classification", "safe_to_build_local_profile_without_runtime",
            "runtime_test_deferred", "next_gate",
        ], event_rows)
        write_tsv(evidence_root / "PRESENTATION_EVENT_SUBSET_SEARCH_COMBINATIONS.tsv", [
            "normalized_path", "subset_rank", "subset_id", "selected_occurrence_indices",
            "selected_occurrence_count", "selected_shape_count", "selected_shape_ids", "candidate_sha256",
            "candidate_size", "target_distance_to_source", "candidate_distance_to_source",
            "distance_improvement", "remaining_residual_rows", "remaining_residual_shape_ids",
            "shared_cue_noncue_context_count", "passes_structural_gates",
            "candidate_not_farther_from_original", "strict_improvement", "exact_original",
            "passes_all_subset_gates", "review_status",
        ], combination_rows)
        write_tsv(evidence_root / "PRESENTATION_EVENT_SUBSET_SEARCH_SELECTED_OCCURRENCES.tsv", [
            "normalized_path", "best_subset_id", "selection_order", "eligible_occurrence_index", "shape_id",
            "occurrence_index", "cue_domains", "selection_reasons",
            "shared_cue_noncue_context_archetype_count", "review_status",
        ], selected_rows)
        write_tsv(evidence_root / "PRESENTATION_EVENT_SUBSET_SEARCH_RESIDUALS.tsv", [
            "normalized_path", "best_subset_id", "shape_id", "sequence_tag", "source_atom_count",
            "target_atom_count", "classification", "review_status",
        ], residual_rows)
        write_tsv(evidence_root / "PRESENTATION_EVENT_SUBSET_SEARCH_SKIPPED.tsv", [
            "normalized_path", "reason", "eligible_occurrence_count", "possible_combination_count",
        ], skipped_rows)

        promoted = [row for row in event_rows if parse_bool(row.get("safe_to_build_local_profile_without_runtime"))]
        summary: dict[str, object] = {
            "type": "br_quartet_restoration_presentation_event_subset_search_evidence_summary",
            "format_version": 1,
            "tool_version": TOOL_VERSION,
            "source_stage43_tool_version": core_summary.get("tool_version"),
            "source_stage40_tool_version": backlog_summary.get("tool_version"),
            "source_stage41_tool_version": prototype_summary.get("tool_version"),
            "source_stage23_tool_version": context_summary.get("tool_version"),
            "source_stage24_tool_version": migration_summary.get("tool_version"),
            "status": "bounded_cue_linked_residual_subset_search_complete_no_payload_written_runtime_deferred",
            "registry_profile_rows": 7,
            "candidate_event_rows": len(candidate_backlog),
            "analyzed_event_rows": len(event_rows),
            "promotable_event_rows": len(promoted),
            "reported_combination_rows": len(combination_rows),
            "best_selected_occurrence_rows": len(selected_rows),
            "best_remaining_residual_rows": len(residual_rows),
            "skipped_rows": len(skipped_rows),
            "runtime_testing_deferred": True,
            "parameters": {
                "maximum_event_bytes": maximum_event_bytes,
                "maximum_subset_occurrences": maximum_subset_occurrences,
                "maximum_combinations_per_event": maximum_combinations_per_event,
                "top_combinations_per_event": top_combinations_per_event,
            },
            "policy": {
                "installed_games_modified": False,
                "candidate_ebd_payloads_written": False,
                "pak_repacked": False,
                "core_profile_manifest_modified": False,
                "activation_or_rollback_invoked": False,
                "runtime_validation_inferred": False,
                "censorship_classification_inferred": False,
                "broad_or_recurrent_schema_shapes_selected": False,
                "shared_cue_noncue_context_selected": False,
                "dialogue_or_localized_text_exported": False,
                "legacy_dlc_in_scope": False,
                "translation_or_core_files_modified": False,
            },
            "next_action": (
                "Upload this metadata report. Build one separate local EBD profile only for each event marked "
                "strictly_improving_subset_ready_for_local_prototype, reproducing the exact reported subset hash and "
                "target reverse round-trip. Keep all other events in the static backlog and all runtime testing deferred."
            ),
        }
        (evidence_root / "SUMMARY.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        output = report_root / REPORT_NAME
        make_report_archive(evidence_root, output)
        return output, summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", required=True)
    parser.add_argument("--workspace-root")
    parser.add_argument("--report-root")
    parser.add_argument("--maximum-event-bytes", type=int, default=2 * 1024 * 1024)
    parser.add_argument("--maximum-subset-occurrences", type=int, default=12)
    parser.add_argument("--maximum-combinations-per-event", type=int, default=4095)
    parser.add_argument("--top-combinations-per-event", type=int, default=32)
    args = parser.parse_args()
    project_root = Path(args.project_root).expanduser().resolve()
    workspace_root = Path(args.workspace_root).expanduser().resolve() if args.workspace_root else project_root / ".local/build/quartet_restoration"
    report_root = Path(args.report_root).expanduser().resolve() if args.report_root else project_root / ".local/reports/quartet_restoration"
    if not project_root.is_dir():
        raise SubsetSearchError(f"project root does not exist: {project_root}")
    output, summary = collect_subset_search(
        project_root=project_root,
        workspace_root=workspace_root,
        report_root=report_root,
        maximum_event_bytes=args.maximum_event_bytes,
        maximum_subset_occurrences=args.maximum_subset_occurrences,
        maximum_combinations_per_event=args.maximum_combinations_per_event,
        top_combinations_per_event=args.top_combinations_per_event,
    )
    print(f"Current registry profiles: {summary['registry_profile_rows']}")
    print(f"High-priority unregistered events analyzed: {summary['analyzed_event_rows']}")
    print(f"Strictly improving static subset candidates: {summary['promotable_event_rows']}")
    print("Candidate EBD payloads written: false")
    print("Runtime testing deferred: true")
    print(f"Report: {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
