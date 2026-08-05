#!/usr/bin/env python3
"""Test repeated cue-positive occurrences of complex residual shapes as bounded subsets.

Stage 50 follows unresolved high-priority shapes that stage 23 intentionally did
not classify as simple inverse splices.  It considers only cue-positive events
outside the current profile registry where the same complex shape occurs more
than once, enumerates every bounded non-empty occurrence subset, reconstructs
it in memory, and requires exact occurrence-count reduction, preservation of
all other residual counters, Quartet header/trailing bytes, exact reverse
round-trip and strict distance improvement before any later prototype.

No EBD, PAK, registry manifest or installed-game file is written.
"""

from __future__ import annotations

import argparse
import hashlib
import itertools
import json
import os
import shutil
import subprocess
import sys
import tempfile
from collections import Counter, defaultdict
from pathlib import Path, PurePosixPath
from typing import Any, Iterable, Mapping, Sequence

import collect_presentation_event_subset_search_evidence as subset

WORKSTREAM_ID = "quartet_restoration"
TOOL_VERSION = "0.0.58"
TARGET_COMPLEX_SHAPE_ID = "a92037cebf526c656d4b1e76c1871b17657f08ebd1bb73c6ca8ae15b78bef64d"
TARGET_EVENT_PATH = "event/event_jp/fe13/event_fe13_050.ebd"
REPORT_NAME = "BR_quartet_restoration_complex_repeated_shape_subset_evidence.tar.zst"
EVIDENCE_DIR_NAME = "complex_repeated_shape_subset_evidence"

REPORT_SPECS = {
    "context": (
        "event_delta_context_evidence",
        "BR_quartet_restoration_event_delta_context_evidence.tar.zst",
    ),
    "core": (
        "core_profile_manifest_evidence",
        "BR_quartet_restoration_core_profile_manifest_evidence.tar.zst",
    ),
    "anchor": (
        "registered_profile_anchor_subset_evidence",
        "BR_quartet_restoration_registered_profile_anchor_subset_evidence.tar.zst",
    ),
}


class ComplexRepeatedShapeError(RuntimeError):
    pass


def parse_bool(value: object) -> bool:
    return str(value).strip().casefold() in {"1", "true", "yes", "y"}


def parse_int(value: object, default: int = 0) -> int:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return default


def normalize_event_member(path: object) -> str:
    return subset.normalize_event_member(path)


def event_id(path: str) -> str:
    return subset.event_id(path)


def read_tsv(path: Path, *, required: bool = True) -> list[dict[str, str]]:
    return subset.read_tsv(path, required=required)


def write_tsv(path: Path, fieldnames: Sequence[str], rows: Iterable[Mapping[str, object]]) -> None:
    subset.write_tsv(path, fieldnames, rows)


def load_json(path: Path) -> dict[str, Any]:
    return subset.load_json(path)


def safe_member_name(raw: str) -> str:
    path = PurePosixPath(raw)
    if path.is_absolute() or not path.parts or ".." in path.parts:
        raise ComplexRepeatedShapeError(f"unsafe report archive member: {raw}")
    return path.as_posix()


def extract_archive(archive: Path, destination: Path) -> Path:
    if not archive.is_file():
        raise ComplexRepeatedShapeError(f"missing prerequisite report archive: {archive}")
    listed = subprocess.run(
        ["tar", "--zstd", "-tf", str(archive)], text=True,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False,
    )
    if listed.returncode != 0:
        raise ComplexRepeatedShapeError(f"cannot list {archive}: {listed.stderr.strip()}")
    roots: set[str] = set()
    for raw in listed.stdout.splitlines():
        if raw.strip():
            roots.add(PurePosixPath(safe_member_name(raw.strip())).parts[0])
    if len(roots) != 1:
        raise ComplexRepeatedShapeError(f"expected one report root in {archive}, found {sorted(roots)}")
    destination.mkdir(parents=True, exist_ok=True)
    completed = subprocess.run(
        ["tar", "--zstd", "-xf", str(archive), "-C", str(destination)], text=True,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False,
    )
    if completed.returncode != 0:
        raise ComplexRepeatedShapeError(f"cannot extract {archive}: {completed.stderr.strip()}")
    return destination / next(iter(roots))


def locate_report_root(report_root: Path, key: str, temporary: Path) -> Path:
    directory_name, archive_name = REPORT_SPECS[key]
    direct = report_root / directory_name
    return direct if direct.is_dir() else extract_archive(report_root / archive_name, temporary / key)


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
        raise ComplexRepeatedShapeError(f"cannot create report archive: {result.stderr.strip()}")
    os.replace(temporary, output)


def enumerate_nonempty_subsets(rows: Sequence[Mapping[str, object]]) -> Iterable[tuple[tuple[int, ...], list[Mapping[str, object]]]]:
    for count in range(1, len(rows) + 1):
        for indices in itertools.combinations(range(len(rows)), count):
            yield indices, [rows[index] for index in indices]


def validate_prerequisites(roots: Mapping[str, Path]) -> dict[str, Any]:
    context = load_json(roots["context"] / "SUMMARY.json")
    if context.get("type") != "br_quartet_restoration_event_delta_context_evidence_summary":
        raise ComplexRepeatedShapeError("stage-23 report has an unexpected type")
    if context.get("tool_version") != "0.0.27":
        raise ComplexRepeatedShapeError("stage-23 report must be the 0.0.27 report")

    core = load_json(roots["core"] / "SUMMARY.json")
    if core.get("type") != "br_quartet_restoration_core_profile_manifest_evidence_summary":
        raise ComplexRepeatedShapeError("current core-profile report has an unexpected type")
    if core.get("tool_version") != "0.0.54" or parse_int(core.get("profile_rows"), -1) != 13:
        raise ComplexRepeatedShapeError("current core-profile report must contain the 13 profiles registered by 0.0.54")
    if parse_int(core.get("runtime_validated_profile_rows"), -1) != 0:
        raise ComplexRepeatedShapeError("registered profiles must remain runtime-unvalidated")
    manifest_rows = read_tsv(roots["core"] / "CORE_PROFILE_MANIFESTS.tsv")
    if len(manifest_rows) != 13 or any(row.get("validation_status") != "passed" for row in manifest_rows):
        raise ComplexRepeatedShapeError("current core-profile rows are incomplete or invalid")

    anchor = load_json(roots["anchor"] / "SUMMARY.json")
    if anchor.get("type") != "br_quartet_restoration_registered_profile_anchor_subset_evidence_summary":
        raise ComplexRepeatedShapeError("stage-49 report has an unexpected type")
    if anchor.get("tool_version") != "0.0.56":
        raise ComplexRepeatedShapeError("stage-49 report must be the 0.0.56 report")
    if parse_int(anchor.get("promotable_event_rows"), -1) != 0 or parse_int(anchor.get("skipped_rows"), -1) != 0:
        raise ComplexRepeatedShapeError("stage-49 report must contain no promoted or skipped event")
    return {"context": context, "core": core, "anchor": anchor}


def select_target_complex_shape(
    *,
    selected_shapes: Sequence[Mapping[str, object]],
    comparison_rows: Sequence[Mapping[str, object]],
    occurrence_rows: Sequence[Mapping[str, object]],
) -> tuple[set[str], dict[str, object]]:
    """Select the fixed stage-50 target without silently depending on one TSV row.

    The original 0.0.57 implementation derived eligibility only from
    SELECTED_EVENT_DELTA_SHAPES.tsv.  A stale or regenerated direct report
    directory could therefore produce a formally successful but empty report
    even though the canonical occurrence evidence still contained the intended
    a92037ce... target.  Stage 50 is deliberately scoped to that one shape, so
    validate it from all available stage-23 evidence and fail closed when the
    expected fe13_050 triplet is absent.
    """
    target_selected = [
        row for row in selected_shapes
        if str(row.get("shape_id", "")) == TARGET_COMPLEX_SHAPE_ID
    ]
    target_comparison = next((
        row for row in comparison_rows
        if str(row.get("shape_id", "")) == TARGET_COMPLEX_SHAPE_ID
    ), None)
    target_occurrences = [
        row for row in occurrence_rows
        if str(row.get("shape_id", "")) == TARGET_COMPLEX_SHAPE_ID
    ]
    cue_occurrences = [row for row in target_occurrences if parse_bool(row.get("cue_positive_occurrence"))]
    fe13_occurrences = [
        row for row in cue_occurrences
        if normalize_event_member(row.get("normalized_path", "")) == TARGET_EVENT_PATH
    ]

    if target_comparison is None:
        raise ComplexRepeatedShapeError(
            "stage-23 comparison evidence is missing the fixed a92037ce target"
        )
    if parse_int(target_comparison.get("shared_cue_noncue_context_archetype_count"), -1) != 0:
        raise ComplexRepeatedShapeError(
            "fixed a92037ce target no longer has zero shared cue/non-cue exact contexts"
        )
    if parse_int(target_comparison.get("cue_occurrence_count"), -1) != 4:
        raise ComplexRepeatedShapeError(
            "fixed a92037ce target must retain four cue-positive occurrences in stage-23 evidence"
        )
    if parse_int(target_comparison.get("noncue_occurrence_count"), -1) != 14:
        raise ComplexRepeatedShapeError(
            "fixed a92037ce target must retain fourteen non-cue occurrences in stage-23 evidence"
        )
    if len(target_occurrences) != 18 or len(cue_occurrences) != 4:
        raise ComplexRepeatedShapeError(
            "stage-23 occurrence evidence for a92037ce is incomplete or inconsistent"
        )
    if len(fe13_occurrences) != 3:
        raise ComplexRepeatedShapeError(
            "stage-23 evidence must contain exactly three cue-positive a92037ce occurrences in fe13_050"
        )
    if sorted(parse_int(row.get("occurrence_index"), -1) for row in fe13_occurrences) != [0, 1, 2]:
        raise ComplexRepeatedShapeError(
            "fe13_050 a92037ce occurrence indices must be exactly 0, 1 and 2"
        )
    if any(str(row.get("sequence_tag", "")).casefold() != "replace" for row in fe13_occurrences):
        raise ComplexRepeatedShapeError(
            "fe13_050 a92037ce occurrences must remain multi-atom replace rows"
        )

    selection_mode = "validated_occurrence_evidence_fallback"
    if target_selected:
        if len(target_selected) != 1:
            raise ComplexRepeatedShapeError(
                "stage-23 selected-shape evidence contains duplicate a92037ce rows"
            )
        selected = target_selected[0]
        if parse_bool(selected.get("simple_inverse_splice_eligible")):
            raise ComplexRepeatedShapeError(
                "fixed a92037ce target unexpectedly became simple-splice eligible"
            )
        if str(selected.get("selection_priority", "")).casefold() not in {"critical", "high"}:
            raise ComplexRepeatedShapeError(
                "fixed a92037ce target is no longer high-priority in stage-23 evidence"
            )
        if str(selected.get("sequence_tag", "")).casefold() != "replace":
            raise ComplexRepeatedShapeError(
                "fixed a92037ce selected row is no longer a replace shape"
            )
        if max(
            parse_int(selected.get("source_atom_count")),
            parse_int(selected.get("target_atom_count")),
        ) < 2:
            raise ComplexRepeatedShapeError(
                "fixed a92037ce selected row is no longer multi-atom"
            )
        selection_mode = "selected_shape_and_occurrence_evidence"

    return {TARGET_COMPLEX_SHAPE_ID}, {
        "selection_mode": selection_mode,
        "target_selected_shape_rows": len(target_selected),
        "target_context_occurrence_rows": len(target_occurrences),
        "target_cue_occurrence_rows": len(cue_occurrences),
        "target_noncue_occurrence_rows": len(target_occurrences) - len(cue_occurrences),
        "target_fe13_cue_occurrence_rows": len(fe13_occurrences),
    }


def load_registry_event_owners(project_root: Path) -> dict[str, list[str]]:
    root = project_root / ".local/build/quartet_restoration/core_profiles/generated"
    if not root.is_dir():
        raise ComplexRepeatedShapeError(f"missing generated core registry: {root}")
    manifests = sorted(root.glob("*.json"))
    if len(manifests) != 13:
        raise ComplexRepeatedShapeError(f"expected 13 generated profile manifests, found {len(manifests)}")
    owners: defaultdict[str, list[str]] = defaultdict(list)
    for manifest_path in manifests:
        data = load_json(manifest_path)
        if data.get("workstream_id") != WORKSTREAM_ID:
            raise ComplexRepeatedShapeError(f"foreign manifest in restoration registry: {manifest_path}")
        if parse_bool(data.get("runtime_validated")):
            raise ComplexRepeatedShapeError(f"runtime-validated manifest is not allowed here: {manifest_path}")
        if str(data.get("target_relative_path", "")).casefold() != "data/pack11.pak":
            continue
        changed = data.get("changed_members", [])
        if not isinstance(changed, list):
            raise ComplexRepeatedShapeError(f"changed_members is not a list: {manifest_path}")
        profile_id = str(data.get("profile_id", manifest_path.stem))
        for member in changed:
            owners[normalize_event_member(member)].append(profile_id)
    return dict(owners)


def evaluate_repeated_subset(
    *, br: Any, source_payload: bytes, target_payload: bytes,
    occurrences: Sequence[Mapping[str, object]], shape_id: str,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    candidate, metadata, residuals = br.construct_composite_inverse_event_candidate(
        source_payload=source_payload, target_payload=target_payload, selected_occurrences=occurrences,
    )
    if candidate is None:
        return {"status": str(metadata.get("status", "candidate_failed")), "passes": False}, []
    operations, source_profile, target_profile = subset.build_operations(
        br=br, source_payload=source_payload, target_payload=target_payload, selected_occurrences=occurrences,
    )
    reversed_payload = subset.reverse_candidate(
        candidate_payload=candidate, target_payload=target_payload, operations=operations, br=br,
    )
    candidate_header = br.parse_ebd_header_schema(candidate)
    candidate_profile = br.profile_ebd_post_header_words(
        candidate, int(candidate_header.get("header_end", 0)), maximum_words=max(1, len(candidate) // 4 + 8),
    )
    before_counter = subset.shape_counter(br, source_profile, target_profile)
    after_counter = subset.shape_counter(br, source_profile, candidate_profile)
    selected_count = len(occurrences)
    before_shape_count = int(before_counter.get(shape_id, 0))
    after_shape_count = int(after_counter.get(shape_id, 0))
    expected_after = before_shape_count - selected_count
    nonselected_before = before_counter.copy()
    nonselected_after = after_counter.copy()
    nonselected_before.pop(shape_id, None)
    nonselected_after.pop(shape_id, None)
    target_distance = subset.byte_difference_count(target_payload, source_payload)
    candidate_distance = subset.byte_difference_count(candidate, source_payload)
    checks = {
        "all_occurrences_same_shape": all(str(row.get("shape_id", "")) == shape_id for row in occurrences),
        "all_occurrences_cue_positive": all(parse_bool(row.get("cue_positive_occurrence")) for row in occurrences),
        "selected_occurrence_count_reduced_exactly": after_shape_count == expected_after,
        "selected_occurrence_count_nonnegative": expected_after >= 0,
        "all_other_shape_counters_preserved": nonselected_before == nonselected_after,
        "no_introduced_coarse_shapes": parse_int(metadata.get("introduced_coarse_shape_count")) == 0,
        "candidate_header_preserved_from_target": parse_bool(metadata.get("candidate_header_preserved_from_target")),
        "candidate_trailing_preserved_from_target": parse_bool(metadata.get("candidate_trailing_bytes_preserved_from_target")),
        "candidate_header_valid": metadata.get("candidate_header_classification") == "observed_ebd_name_description_header",
        "exact_target_reverse_roundtrip": reversed_payload == target_payload,
        "candidate_not_farther_from_original": candidate_distance <= target_distance,
    }
    structural_names = [name for name in checks if name != "candidate_not_farther_from_original"]
    passes_structural = all(checks[name] for name in structural_names)
    strict_improvement = candidate_distance < target_distance
    passes = passes_structural and checks["candidate_not_farther_from_original"]
    return {
        "status": "passed" if passes else "failed",
        "passes": passes,
        "passes_structural": passes_structural,
        "strict_improvement": strict_improvement,
        "exact_original": candidate == source_payload,
        "candidate_sha256": hashlib.sha256(candidate).hexdigest(),
        "candidate_size": len(candidate),
        "target_distance_to_source": target_distance,
        "candidate_distance_to_source": candidate_distance,
        "distance_improvement": target_distance - candidate_distance,
        "selected_occurrence_count": selected_count,
        "shape_occurrence_count_before": before_shape_count,
        "shape_occurrence_count_after": after_shape_count,
        "expected_shape_occurrence_count_after": expected_after,
        "remaining_residual_rows": len(residuals),
        "remaining_residual_shape_ids": ";".join(sorted({str(row.get("shape_id", "")) for row in residuals})),
        "checks": checks,
    }, residuals


def collect_complex_repeated_shape_subset_evidence(
    *, project_root: Path, workspace_root: Path, report_root: Path,
    maximum_event_bytes: int = 2 * 1024 * 1024,
    maximum_occurrences_per_event: int = 12,
    maximum_combinations_per_event: int = 4096,
    top_combinations_per_event: int = 32,
) -> tuple[Path, dict[str, object]]:
    project_root = project_root.expanduser().resolve()
    workspace_root = workspace_root.expanduser().resolve()
    report_root = report_root.expanduser().resolve()
    if maximum_occurrences_per_event < 2 or maximum_occurrences_per_event > 16:
        raise ComplexRepeatedShapeError("maximum_occurrences_per_event must be in the range 2..16")
    if maximum_combinations_per_event < 1 or top_combinations_per_event < 1:
        raise ComplexRepeatedShapeError("combination limits must be positive")
    br = subset.load_restoration_tool(project_root)

    with tempfile.TemporaryDirectory(prefix="br-complex-repeated-shape-") as temporary_name:
        temporary = Path(temporary_name)
        roots = {key: locate_report_root(report_root, key, temporary) for key in REPORT_SPECS}
        summaries = validate_prerequisites(roots)
        owners = load_registry_event_owners(project_root)

        selected_shapes = read_tsv(roots["context"] / "SELECTED_EVENT_DELTA_SHAPES.tsv")
        comparison_rows = read_tsv(roots["context"] / "EVENT_DELTA_CUE_NONCUE_COMPARISON.tsv")
        occurrence_rows = read_tsv(roots["context"] / "EVENT_DELTA_CONTEXT_OCCURRENCES.tsv")
        eligible_shapes, selection_diagnostics = select_target_complex_shape(
            selected_shapes=selected_shapes,
            comparison_rows=comparison_rows,
            occurrence_rows=occurrence_rows,
        )
        grouped: defaultdict[tuple[str, str], list[dict[str, str]]] = defaultdict(list)
        excluded_rows: list[dict[str, object]] = []
        for row in occurrence_rows:
            shape_id = str(row.get("shape_id", ""))
            path = normalize_event_member(row.get("normalized_path", ""))
            if shape_id not in eligible_shapes or not parse_bool(row.get("cue_positive_occurrence")):
                continue
            if path in owners:
                excluded_rows.append({
                    "normalized_path": path, "shape_id": shape_id,
                    "occurrence_index": row.get("occurrence_index", ""),
                    "reason": "event_already_covered_by_registered_profile",
                    "owner_profile_ids": ";".join(sorted(owners[path])),
                })
                continue
            grouped[(path, shape_id)].append(row)

        target_group = grouped.get((TARGET_EVENT_PATH, TARGET_COMPLEX_SHAPE_ID), [])
        if len(target_group) != 3:
            raise ComplexRepeatedShapeError(
                "stage-50 selection produced no exact fe13_050 triplet; refusing to emit an empty success report"
            )

        differences = br.load_report_jsons(report_root, "differences")
        event_report = next((row for row in differences if str(row.get("source_archive_group", "")) == "br1_events"), None)
        if event_report is None:
            raise ComplexRepeatedShapeError("missing br1_events difference report")
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

        for (path, shape_id), occurrences in sorted(grouped.items()):
            occurrences = sorted(occurrences, key=lambda row: parse_int(row.get("occurrence_index"), -1))
            if len(occurrences) < 2:
                excluded_rows.append({
                    "normalized_path": path, "shape_id": shape_id, "occurrence_index": "",
                    "reason": "complex_shape_has_fewer_than_two_cue_occurrences_in_event", "owner_profile_ids": "",
                })
                continue
            if len(occurrences) > maximum_occurrences_per_event:
                skipped_rows.append({
                    "normalized_path": path, "shape_id": shape_id,
                    "reason": "maximum_occurrences_per_event_exceeded", "eligible_occurrence_count": len(occurrences),
                    "possible_combination_count": (1 << len(occurrences)) - 1,
                })
                continue
            possible = (1 << len(occurrences)) - 1
            if possible > maximum_combinations_per_event:
                skipped_rows.append({
                    "normalized_path": path, "shape_id": shape_id,
                    "reason": "maximum_combinations_per_event_exceeded", "eligible_occurrence_count": len(occurrences),
                    "possible_combination_count": possible,
                })
                continue
            entry = entry_by_path.get(path)
            if entry is None:
                skipped_rows.append({"normalized_path": path, "shape_id": shape_id, "reason": "difference_entry_missing"})
                continue
            source_ref = entry.get("source") or {}
            target_ref = entry.get("target") or {}
            source_path = br.inventory_workspace_file(
                workspace_root, "source", "br1_events", str(source_ref.get("archive", "")), str(source_ref.get("path", "")),
            )
            target_path = br.inventory_workspace_file(
                workspace_root, "target", "br1_events", str(target_ref.get("archive", "")), str(target_ref.get("path", "")),
            )
            if not source_path.is_file() or not target_path.is_file():
                skipped_rows.append({"normalized_path": path, "shape_id": shape_id, "reason": "workspace_event_payload_missing"})
                continue
            if source_path.stat().st_size > maximum_event_bytes or target_path.stat().st_size > maximum_event_bytes:
                skipped_rows.append({"normalized_path": path, "shape_id": shape_id, "reason": "maximum_event_bytes_exceeded"})
                continue
            source_payload = source_path.read_bytes()
            target_payload = target_path.read_bytes()
            if source_ref.get("sha256") and hashlib.sha256(source_payload).hexdigest() != str(source_ref.get("sha256")):
                skipped_rows.append({"normalized_path": path, "shape_id": shape_id, "reason": "source_payload_sha256_mismatch"})
                continue
            if target_ref.get("sha256") and hashlib.sha256(target_payload).hexdigest() != str(target_ref.get("sha256")):
                skipped_rows.append({"normalized_path": path, "shape_id": shape_id, "reason": "target_payload_sha256_mismatch"})
                continue

            evaluated: list[tuple[tuple[int, ...], dict[str, Any], list[dict[str, Any]]]] = []
            construction_failures = 0
            for indices, selected in enumerate_nonempty_subsets(occurrences):
                result, residuals = evaluate_repeated_subset(
                    br=br, source_payload=source_payload, target_payload=target_payload,
                    occurrences=selected, shape_id=shape_id,
                )
                if not result.get("candidate_sha256"):
                    construction_failures += 1
                    continue
                evaluated.append((indices, result, residuals))
            evaluated.sort(key=lambda item: (
                not bool(item[1].get("strict_improvement")),
                not bool(item[1].get("passes_structural")),
                parse_int(item[1].get("candidate_distance_to_source"), 1 << 60),
                parse_int(item[1].get("selected_occurrence_count"), 1 << 30),
                item[0],
            ))
            reported = evaluated[:top_combinations_per_event]
            for rank, (indices, result, residuals) in enumerate(reported, start=1):
                subset_id = hashlib.sha256(f"{path}|{shape_id}|{','.join(map(str, indices))}|{result['candidate_sha256']}".encode()).hexdigest()[:16]
                combination_rows.append({
                    "normalized_path": path, "shape_id": shape_id, "subset_rank": rank, "subset_id": subset_id,
                    "selected_occurrence_indices": ";".join(str(occurrences[index].get("occurrence_index", "")) for index in indices),
                    "selected_occurrence_count": result.get("selected_occurrence_count", ""),
                    "candidate_sha256": result.get("candidate_sha256", ""), "candidate_size": result.get("candidate_size", ""),
                    "target_distance_to_source": result.get("target_distance_to_source", ""),
                    "candidate_distance_to_source": result.get("candidate_distance_to_source", ""),
                    "distance_improvement": result.get("distance_improvement", ""),
                    "shape_occurrence_count_before": result.get("shape_occurrence_count_before", ""),
                    "shape_occurrence_count_after": result.get("shape_occurrence_count_after", ""),
                    "expected_shape_occurrence_count_after": result.get("expected_shape_occurrence_count_after", ""),
                    "remaining_residual_rows": result.get("remaining_residual_rows", ""),
                    "remaining_residual_shape_ids": result.get("remaining_residual_shape_ids", ""),
                    "passes_structural_gates": result.get("passes_structural", False),
                    "candidate_not_farther_from_original": result.get("checks", {}).get("candidate_not_farther_from_original", False),
                    "strict_improvement": result.get("strict_improvement", False), "exact_original": result.get("exact_original", False),
                    "review_status": "bounded_complex_shape_occurrence_subset_evidence_not_runtime_or_censorship_validation",
                })
            best = evaluated[0] if evaluated else None
            ready = bool(best and best[1].get("passes_structural") and best[1].get("strict_improvement"))
            classification = (
                "complex_repeated_shape_subset_strict_improvement_ready_for_local_prototype"
                if ready else "complex_repeated_shape_subsets_not_strictly_improving"
            )
            best_id = ""
            if best:
                indices, result, best_residuals = best
                best_id = hashlib.sha256(f"{path}|{shape_id}|{','.join(map(str, indices))}|{result['candidate_sha256']}".encode()).hexdigest()[:16]
                for order, index in enumerate(indices):
                    occurrence = occurrences[index]
                    selected_rows.append({
                        "normalized_path": path, "shape_id": shape_id, "best_subset_id": best_id,
                        "selection_order": order, "occurrence_index": occurrence.get("occurrence_index", ""),
                        "pair_context_archetype_id": occurrence.get("pair_context_archetype_id", ""),
                        "cue_domains": occurrence.get("cue_domains", ""),
                        "review_status": "best_complex_shape_subset_component_not_yet_written_as_payload",
                    })
                for residual in best_residuals:
                    residual_rows.append({
                        "normalized_path": path, "shape_id": residual.get("shape_id", ""), "best_subset_id": best_id,
                        "sequence_tag": residual.get("sequence_tag", ""), "source_atom_count": residual.get("source_atom_count", ""),
                        "target_atom_count": residual.get("target_atom_count", ""), "classification": residual.get("classification", ""),
                        "review_status": "best_complex_shape_subset_remaining_residual_not_assigned_semantics",
                    })
            event_rows.append({
                "normalized_path": path, "event_id": event_id(path), "shape_id": shape_id,
                "cue_domains": ";".join(sorted({domain for row in occurrences for domain in str(row.get("cue_domains", "")).split(";") if domain})),
                "cue_occurrence_count": len(occurrences), "combination_count_tested": len(evaluated),
                "candidate_construction_failures": construction_failures,
                "passing_structural_combination_count": sum(bool(row[1].get("passes_structural")) for row in evaluated),
                "strictly_improving_combination_count": sum(bool(row[1].get("strict_improvement")) and bool(row[1].get("passes_structural")) for row in evaluated),
                "best_subset_id": best_id,
                "best_selected_occurrence_count": best[1].get("selected_occurrence_count", "") if best else "",
                "best_selected_occurrence_indices": ";".join(str(occurrences[index].get("occurrence_index", "")) for index in best[0]) if best else "",
                "target_distance_to_source": best[1].get("target_distance_to_source", "") if best else "",
                "best_candidate_distance_to_source": best[1].get("candidate_distance_to_source", "") if best else "",
                "best_distance_improvement": best[1].get("distance_improvement", "") if best else "",
                "best_candidate_sha256": best[1].get("candidate_sha256", "") if best else "",
                "best_remaining_residual_rows": best[1].get("remaining_residual_rows", "") if best else "",
                "classification": classification, "review_priority": "high" if ready else "medium",
                "safe_to_build_separate_local_profile": ready, "runtime_test_deferred": True,
                "next_gate": "build_exact_reported_subset_as_separate_local_profile" if ready else "retain_as_complex_context_evidence",
            })

        event_rows.sort(key=lambda row: (not parse_bool(row.get("safe_to_build_separate_local_profile")), str(row.get("normalized_path", ""))))
        combination_rows.sort(key=lambda row: (str(row.get("normalized_path", "")), parse_int(row.get("subset_rank"))))
        selected_rows.sort(key=lambda row: (str(row.get("normalized_path", "")), parse_int(row.get("selection_order"))))
        residual_rows.sort(key=lambda row: (str(row.get("normalized_path", "")), str(row.get("shape_id", ""))))
        excluded_rows.sort(key=lambda row: (str(row.get("normalized_path", "")), str(row.get("shape_id", "")), parse_int(row.get("occurrence_index"), -1)))
        skipped_rows.sort(key=lambda row: (str(row.get("normalized_path", "")), str(row.get("reason", ""))))

        evidence_root = report_root / EVIDENCE_DIR_NAME
        if evidence_root.exists():
            shutil.rmtree(evidence_root)
        evidence_root.mkdir(parents=True, exist_ok=True)
        write_tsv(evidence_root / "COMPLEX_REPEATED_SHAPE_EVENTS.tsv", [
            "normalized_path", "event_id", "shape_id", "cue_domains", "cue_occurrence_count",
            "combination_count_tested", "candidate_construction_failures", "passing_structural_combination_count",
            "strictly_improving_combination_count", "best_subset_id", "best_selected_occurrence_count",
            "best_selected_occurrence_indices", "target_distance_to_source", "best_candidate_distance_to_source",
            "best_distance_improvement", "best_candidate_sha256", "best_remaining_residual_rows", "classification",
            "review_priority", "safe_to_build_separate_local_profile", "runtime_test_deferred", "next_gate",
        ], event_rows)
        write_tsv(evidence_root / "COMPLEX_REPEATED_SHAPE_COMBINATIONS.tsv", [
            "normalized_path", "shape_id", "subset_rank", "subset_id", "selected_occurrence_indices",
            "selected_occurrence_count", "candidate_sha256", "candidate_size", "target_distance_to_source",
            "candidate_distance_to_source", "distance_improvement", "shape_occurrence_count_before",
            "shape_occurrence_count_after", "expected_shape_occurrence_count_after", "remaining_residual_rows",
            "remaining_residual_shape_ids", "passes_structural_gates", "candidate_not_farther_from_original",
            "strict_improvement", "exact_original", "review_status",
        ], combination_rows)
        write_tsv(evidence_root / "COMPLEX_REPEATED_SHAPE_SELECTED_OCCURRENCES.tsv", [
            "normalized_path", "shape_id", "best_subset_id", "selection_order", "occurrence_index",
            "pair_context_archetype_id", "cue_domains", "review_status",
        ], selected_rows)
        write_tsv(evidence_root / "COMPLEX_REPEATED_SHAPE_RESIDUALS.tsv", [
            "normalized_path", "shape_id", "best_subset_id", "sequence_tag", "source_atom_count",
            "target_atom_count", "classification", "review_status",
        ], residual_rows)
        write_tsv(evidence_root / "COMPLEX_REPEATED_SHAPE_EXCLUDED.tsv", [
            "normalized_path", "shape_id", "occurrence_index", "reason", "owner_profile_ids",
        ], excluded_rows)
        write_tsv(evidence_root / "COMPLEX_REPEATED_SHAPE_SKIPPED.tsv", [
            "normalized_path", "shape_id", "reason", "eligible_occurrence_count", "possible_combination_count",
        ], skipped_rows)

        promoted = [row for row in event_rows if parse_bool(row.get("safe_to_build_separate_local_profile"))]
        summary: dict[str, object] = {
            "type": "br_quartet_restoration_complex_repeated_shape_subset_evidence_summary",
            "format_version": 1, "tool_version": TOOL_VERSION,
            "source_stage23_tool_version": summaries["context"].get("tool_version"),
            "source_core_profile_tool_version": summaries["core"].get("tool_version"),
            "source_stage49_tool_version": summaries["anchor"].get("tool_version"),
            "status": "complex_repeated_shape_occurrence_subset_search_complete_no_payload_written_runtime_deferred",
            "eligible_complex_shape_ids": len(eligible_shapes), "candidate_event_shape_rows": len(grouped),
            "selection_diagnostics": selection_diagnostics,
            "analyzed_event_rows": len(event_rows), "promotable_event_rows": len(promoted),
            "reported_combination_rows": len(combination_rows), "best_selected_occurrence_rows": len(selected_rows),
            "best_remaining_residual_rows": len(residual_rows), "excluded_occurrence_rows": len(excluded_rows),
            "skipped_rows": len(skipped_rows), "runtime_testing_deferred": True,
            "parameters": {
                "maximum_event_bytes": maximum_event_bytes,
                "maximum_occurrences_per_event": maximum_occurrences_per_event,
                "maximum_combinations_per_event": maximum_combinations_per_event,
                "top_combinations_per_event": top_combinations_per_event,
            },
            "policy": {
                "installed_games_modified": False, "candidate_ebd_payloads_written": False,
                "pak_repack_performed": False, "profile_manifests_modified": False,
                "activation_or_rollback_invoked": False, "runtime_validation_inferred": False,
                "censorship_classification_inferred": False, "complex_multi_atom_shape_semantics_inferred": False,
                "registered_event_paths_excluded": True, "all_other_residual_counters_must_remain_unchanged": True,
                "exact_reverse_roundtrip_required_for_promotion": True,
                "strict_original_distance_improvement_required_for_promotion": True,
                "legacy_dlc_in_scope": False,
            },
            "next_action": (
                "Upload this metadata report. Build a separate local prototype only for rows marked "
                "complex_repeated_shape_subset_strict_improvement_ready_for_local_prototype, reproducing the exact "
                "reported occurrence subset, candidate hash and reverse round-trip. Otherwise retain the repeated "
                "complex shape as context evidence without global field semantics."
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
    parser.add_argument("--maximum-occurrences-per-event", type=int, default=12)
    parser.add_argument("--maximum-combinations-per-event", type=int, default=4096)
    parser.add_argument("--top-combinations-per-event", type=int, default=32)
    args = parser.parse_args()
    project_root = Path(args.project_root).expanduser().resolve()
    workspace_root = Path(args.workspace_root).expanduser().resolve() if args.workspace_root else project_root / ".local/build/quartet_restoration"
    report_root = Path(args.report_root).expanduser().resolve() if args.report_root else project_root / ".local/reports/quartet_restoration"
    try:
        output, summary = collect_complex_repeated_shape_subset_evidence(
            project_root=project_root, workspace_root=workspace_root, report_root=report_root,
            maximum_event_bytes=args.maximum_event_bytes,
            maximum_occurrences_per_event=args.maximum_occurrences_per_event,
            maximum_combinations_per_event=args.maximum_combinations_per_event,
            top_combinations_per_event=args.top_combinations_per_event,
        )
    except (ComplexRepeatedShapeError, subset.SubsetSearchError, OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print(f"Complex repeated-shape events analyzed: {summary['analyzed_event_rows']}")
    print(f"Promotable repeated-shape subsets: {summary['promotable_event_rows']}")
    print(f"Report: {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
