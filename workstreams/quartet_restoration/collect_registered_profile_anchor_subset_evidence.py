#!/usr/bin/env python3
"""Search bounded residual subsets around a cue-positive registered-profile shape anchor.

Stage 49 handles the conservative follow-up to stage 48.  A shape that was
selected by an already registered profile may be structurally safe in a new
cue-positive event while its single inverse splice gives no strict improvement.
This stage keeps that propagated occurrence mandatory, enumerates bounded
combinations with other non-migration residual occurrences from the same EBD,
and accepts a later prototype candidate only if the complete anchored subset
passes exact reverse-round-trip and strictly approaches Original.

No EBD, PAK, registry manifest or installed-game file is written.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
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

import collect_presentation_event_subset_search_evidence as subset

WORKSTREAM_ID = "quartet_restoration"
TOOL_VERSION = "0.0.56"
REPORT_NAME = "BR_quartet_restoration_registered_profile_anchor_subset_evidence.tar.zst"
EVIDENCE_DIR_NAME = "registered_profile_anchor_subset_evidence"

REPORT_SPECS = {
    "propagation": (
        "registered_profile_shape_propagation_evidence",
        "BR_quartet_restoration_registered_profile_shape_propagation_evidence.tar.zst",
    ),
    "context": (
        "event_delta_context_evidence",
        "BR_quartet_restoration_event_delta_context_evidence.tar.zst",
    ),
    "migration": (
        "event_tag_migration_evidence",
        "BR_quartet_restoration_event_tag_migration_evidence.tar.zst",
    ),
}


class AnchorSubsetError(RuntimeError):
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
        raise AnchorSubsetError(f"unsafe report archive member: {raw}")
    return path.as_posix()


def extract_archive(archive: Path, destination: Path) -> Path:
    if not archive.is_file():
        raise AnchorSubsetError(f"missing prerequisite report archive: {archive}")
    listed = subprocess.run(
        ["tar", "--zstd", "-tf", str(archive)], text=True,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False,
    )
    if listed.returncode != 0:
        raise AnchorSubsetError(f"cannot list {archive}: {listed.stderr.strip()}")
    roots: set[str] = set()
    for raw in listed.stdout.splitlines():
        if raw.strip():
            roots.add(PurePosixPath(safe_member_name(raw.strip())).parts[0])
    if len(roots) != 1:
        raise AnchorSubsetError(f"expected one report root in {archive}, found {sorted(roots)}")
    destination.mkdir(parents=True, exist_ok=True)
    completed = subprocess.run(
        ["tar", "--zstd", "-xf", str(archive), "-C", str(destination)], text=True,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False,
    )
    if completed.returncode != 0:
        raise AnchorSubsetError(f"cannot extract {archive}: {completed.stderr.strip()}")
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
        raise AnchorSubsetError(f"cannot create report archive: {result.stderr.strip()}")
    os.replace(temporary, output)


def occurrence_key(row: Mapping[str, object]) -> tuple[str, int]:
    return str(row.get("shape_id", "")), parse_int(row.get("occurrence_index"), -1)


def enumerate_anchor_subsets(
    anchor: Mapping[str, object], optional_occurrences: Sequence[Mapping[str, object]],
) -> Iterable[tuple[tuple[int, ...], list[Mapping[str, object]]]]:
    """Yield every subset while keeping the anchor mandatory.

    The returned indices address optional_occurrences.  The empty tuple means
    the anchor-only candidate and is intentionally included as a baseline.
    """
    for count in range(0, len(optional_occurrences) + 1):
        for indices in itertools.combinations(range(len(optional_occurrences)), count):
            yield indices, [anchor, *(optional_occurrences[index] for index in indices)]


def filter_optional_occurrences(
    *, residual_occurrences: Sequence[Mapping[str, object]], anchor: Mapping[str, object],
    broad_shape_ids: set[str], control_by_shape: Mapping[str, Mapping[str, object]],
) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    anchor_key = occurrence_key(anchor)
    optional: list[dict[str, object]] = []
    excluded: list[dict[str, object]] = []
    for raw in residual_occurrences:
        row = dict(raw)
        key = occurrence_key(row)
        if key == anchor_key:
            continue
        shape_id = key[0]
        reason = ""
        if shape_id in broad_shape_ids:
            reason = "broad_or_recurrent_schema_shape"
        elif parse_int(control_by_shape.get(shape_id, {}).get("shared_cue_noncue_context_archetype_count")) > 0:
            reason = "known_cue_noncue_shared_context_shape"
        if reason:
            row["exclusion_reason"] = reason
            excluded.append(row)
        else:
            optional.append(row)
    optional.sort(key=lambda row: (str(row.get("shape_id", "")), parse_int(row.get("occurrence_index"), -1)))
    excluded.sort(key=lambda row: (str(row.get("shape_id", "")), parse_int(row.get("occurrence_index"), -1)))
    return optional, excluded


def classify_anchor_subset_result(
    *, passes_structural: bool, strict_improvement: bool, anchor_cue_positive: bool,
    anchor_no_shared_context: bool,
) -> tuple[str, str, bool]:
    if not passes_structural:
        return "anchored_subset_failed_structural_gates", "low", False
    if not anchor_cue_positive or not anchor_no_shared_context:
        return "anchored_subset_anchor_evidence_not_isolated", "low", False
    if not strict_improvement:
        return "anchored_subset_structurally_valid_without_strict_improvement", "medium", False
    return "anchored_subset_strict_improvement_ready_for_local_prototype", "high", True


def all_residual_occurrences(br: Any, source_payload: bytes, target_payload: bytes) -> tuple[list[dict[str, object]], Any, Any]:
    source_header = br.parse_ebd_header_schema(source_payload)
    target_header = br.parse_ebd_header_schema(target_payload)
    if source_header.get("classification") != "observed_ebd_name_description_header":
        raise AnchorSubsetError("source EBD header is not recognized")
    if target_header.get("classification") != "observed_ebd_name_description_header":
        raise AnchorSubsetError("target EBD header is not recognized")
    source_profile = br.profile_ebd_post_header_words(
        source_payload, int(source_header["header_end"]), maximum_words=max(1, len(source_payload) // 4 + 8),
    )
    target_profile = br.profile_ebd_post_header_words(
        target_payload, int(target_header["header_end"]), maximum_words=max(1, len(target_payload) // 4 + 8),
    )
    counters: defaultdict[str, int] = defaultdict(int)
    rows: list[dict[str, object]] = []
    for delta in br.compare_ebd_tag_atoms(source_profile["atoms"], target_profile["atoms"]):
        shape_id = br.event_residual_delta_shape_id(delta)
        occurrence_index = counters[shape_id]
        counters[shape_id] += 1
        rows.append({
            "shape_id": shape_id,
            "occurrence_index": occurrence_index,
            "sequence_tag": delta.get("sequence_tag", ""),
            "source_atom_count": delta.get("source_atom_count", ""),
            "target_atom_count": delta.get("target_atom_count", ""),
            "classification": delta.get("classification", ""),
        })
    return rows, source_profile, target_profile


def evaluate_anchored_combination(
    *, br: Any, source_payload: bytes, target_payload: bytes,
    occurrences: Sequence[Mapping[str, object]], anchor: Mapping[str, object],
    control_by_shape: Mapping[str, Mapping[str, object]],
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
    selected_shapes = {str(row.get("shape_id", "")) for row in occurrences}
    nonselected_before = before_counter.copy()
    nonselected_after = after_counter.copy()
    for shape_id in selected_shapes:
        nonselected_before.pop(shape_id, None)
        nonselected_after.pop(shape_id, None)
    anchor_shape, anchor_index = occurrence_key(anchor)
    anchor_included = any(occurrence_key(row) == (anchor_shape, anchor_index) for row in occurrences)
    optional_shared_context_count = sum(
        parse_int(control_by_shape.get(str(row.get("shape_id", "")), {}).get("shared_cue_noncue_context_archetype_count"))
        for row in occurrences if occurrence_key(row) != (anchor_shape, anchor_index)
    )
    target_distance = subset.byte_difference_count(target_payload, source_payload)
    candidate_distance = subset.byte_difference_count(candidate, source_payload)
    checks = {
        "mandatory_anchor_included": anchor_included,
        "anchor_cue_positive": parse_bool(anchor.get("candidate_cue_positive", anchor.get("cue_positive_occurrence"))),
        "anchor_no_shared_cue_noncue_exact_context": parse_bool(anchor.get("no_shared_cue_noncue_exact_context")),
        "optional_shapes_have_no_known_shared_context": optional_shared_context_count == 0,
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
        "selected_occurrence_count": len(occurrences),
        "selected_shape_count": len(selected_shapes),
        "selected_shape_ids": ";".join(sorted(selected_shapes)),
        "optional_shared_context_count": optional_shared_context_count,
        "remaining_residual_rows": len(residuals),
        "remaining_residual_shape_ids": ";".join(sorted({str(row.get("shape_id", "")) for row in residuals})),
        "checks": checks,
    }, residuals


def validate_prerequisites(roots: Mapping[str, Path]) -> dict[str, Any]:
    propagation = load_json(roots["propagation"] / "SUMMARY.json")
    if propagation.get("type") != "br_quartet_restoration_registered_profile_shape_propagation_evidence_summary":
        raise AnchorSubsetError("stage-48 report has an unexpected type")
    if propagation.get("tool_version") != "0.0.55":
        raise AnchorSubsetError("stage-48 report must be the 0.0.55 report")
    if propagation.get("status") != "registered_profile_shapes_checked_in_unregistered_event_contexts_runtime_deferred":
        raise AnchorSubsetError("stage-48 report status changed")
    if parse_int(propagation.get("registry_profile_rows"), -1) != 13:
        raise AnchorSubsetError("stage-48 report must validate 13 registry profiles")
    if parse_int(propagation.get("candidate_event_rows"), -1) != 4:
        raise AnchorSubsetError("stage-48 candidate-event count changed")
    if parse_int(propagation.get("eligible_profile_event_rows"), -1) != 0:
        raise AnchorSubsetError("stage-48 unexpectedly already promoted a profile")
    if parse_int(propagation.get("skipped_rows"), -1) != 0:
        raise AnchorSubsetError("stage-48 contains skipped rows")

    context = load_json(roots["context"] / "SUMMARY.json")
    if context.get("type") != "br_quartet_restoration_event_delta_context_evidence_summary" or context.get("tool_version") != "0.0.27":
        raise AnchorSubsetError("stage-23 context report is not the expected 0.0.27 report")
    migration = load_json(roots["migration"] / "SUMMARY.json")
    if migration.get("type") != "br_quartet_restoration_event_tag_migration_evidence_summary" or migration.get("tool_version") != "0.0.24":
        raise AnchorSubsetError("stage-24 migration report is not the expected 0.0.24 report")
    return propagation


def collect_anchor_subset_evidence(
    *, project_root: Path, workspace_root: Path, report_root: Path,
    maximum_event_bytes: int = 2 * 1024 * 1024,
    maximum_total_occurrences: int = 12,
    maximum_combinations_per_event: int = 4096,
    top_combinations_per_event: int = 32,
) -> tuple[Path, dict[str, object]]:
    project_root = project_root.expanduser().resolve()
    workspace_root = workspace_root.expanduser().resolve()
    report_root = report_root.expanduser().resolve()
    if maximum_total_occurrences < 1 or maximum_total_occurrences > 16:
        raise AnchorSubsetError("maximum_total_occurrences must be in the range 1..16")
    if maximum_combinations_per_event < 1 or top_combinations_per_event < 1:
        raise AnchorSubsetError("combination limits must be positive")
    br = subset.load_restoration_tool(project_root)

    with tempfile.TemporaryDirectory(prefix="br-profile-anchor-subset-") as temporary_name:
        temporary = Path(temporary_name)
        roots = {key: locate_report_root(report_root, key, temporary) for key in REPORT_SPECS}
        propagation_summary = validate_prerequisites(roots)

        splice_rows = read_tsv(roots["propagation"] / "PROFILE_SHAPE_PROPAGATION_SPLICE_TESTS.tsv")
        anchors = [
            row for row in splice_rows
            if parse_bool(row.get("candidate_cue_positive"))
            and parse_bool(row.get("binary_structural_gates_passed"))
            and parse_bool(row.get("no_shared_cue_noncue_exact_context"))
            and not parse_bool(row.get("strict_improvement"))
        ]
        if not anchors:
            raise AnchorSubsetError("stage-48 report contains no cue-positive structural non-improving anchor")

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
            raise AnchorSubsetError("missing br1_events difference report")
        entry_by_path = {
            normalize_event_member(row.get("normalized_path", "")): row
            for row in event_report.get("entries", [])
            if row.get("scope_status") == "in_scope" and row.get("source") and row.get("target")
        }

        event_rows: list[dict[str, object]] = []
        combination_rows: list[dict[str, object]] = []
        selected_rows: list[dict[str, object]] = []
        residual_rows: list[dict[str, object]] = []
        excluded_rows: list[dict[str, object]] = []
        skipped_rows: list[dict[str, object]] = []

        for anchor in sorted(anchors, key=lambda row: normalize_event_member(row.get("normalized_path", ""))):
            path = normalize_event_member(anchor.get("normalized_path", ""))
            entry = entry_by_path.get(path)
            if entry is None:
                skipped_rows.append({"normalized_path": path, "reason": "difference_entry_missing"})
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

            try:
                all_occurrences, _, _ = all_residual_occurrences(br, source_payload, target_payload)
            except (AnchorSubsetError, br.RestorationError, ValueError, struct.error) as exc:
                skipped_rows.append({"normalized_path": path, "reason": f"residual_enumeration_failed:{type(exc).__name__}"})
                continue
            anchor_shape = str(anchor.get("shape_id", ""))
            anchor_index = parse_int(anchor.get("occurrence_index"), -1)
            matching_anchor = next(
                (row for row in all_occurrences if occurrence_key(row) == (anchor_shape, anchor_index)), None,
            )
            if matching_anchor is None:
                skipped_rows.append({"normalized_path": path, "reason": "mandatory_anchor_occurrence_not_reproduced"})
                continue
            anchor_occurrence = dict(matching_anchor)
            anchor_occurrence.update({
                "candidate_cue_positive": anchor.get("candidate_cue_positive", ""),
                "candidate_cue_domains": anchor.get("candidate_cue_domains", ""),
                "no_shared_cue_noncue_exact_context": anchor.get("no_shared_cue_noncue_exact_context", ""),
                "role": "mandatory_registered_profile_shape_anchor",
            })
            optional, excluded = filter_optional_occurrences(
                residual_occurrences=all_occurrences, anchor=anchor_occurrence,
                broad_shape_ids=broad_shape_ids, control_by_shape=control_by_shape,
            )
            for row in excluded:
                excluded_rows.append({"normalized_path": path, **row})
            total_eligible = 1 + len(optional)
            if total_eligible > maximum_total_occurrences:
                skipped_rows.append({
                    "normalized_path": path, "reason": "maximum_total_occurrences_exceeded",
                    "eligible_occurrence_count": total_eligible,
                })
                continue
            possible = 1 << len(optional)
            if possible > maximum_combinations_per_event:
                skipped_rows.append({
                    "normalized_path": path, "reason": "maximum_combinations_per_event_exceeded",
                    "eligible_occurrence_count": total_eligible, "possible_combination_count": possible,
                })
                continue

            evaluated: list[tuple[dict[str, Any], tuple[int, ...], list[dict[str, Any]]]] = []
            failures = 0
            for indices, selected in enumerate_anchor_subsets(anchor_occurrence, optional):
                try:
                    result, residuals = evaluate_anchored_combination(
                        br=br, source_payload=source_payload, target_payload=target_payload,
                        occurrences=selected, anchor=anchor_occurrence, control_by_shape=control_by_shape,
                    )
                except (AnchorSubsetError, subset.SubsetSearchError, br.RestorationError, OSError, ValueError, struct.error):
                    failures += 1
                    continue
                if result.get("status") == "candidate_failed":
                    failures += 1
                    continue
                evaluated.append((result, indices, residuals))

            ranked = sorted(
                evaluated,
                key=lambda item: (
                    not bool(item[0].get("passes")),
                    not bool(item[0].get("strict_improvement")),
                    not bool(item[0].get("exact_original")),
                    -parse_int(item[0].get("distance_improvement")),
                    parse_int(item[0].get("remaining_residual_rows")),
                    parse_int(item[0].get("selected_occurrence_count")),
                    str(item[0].get("candidate_sha256", "")),
                ),
            )
            best = ranked[0] if ranked else None
            best_result = best[0] if best else {}
            classification, priority, promotable = classify_anchor_subset_result(
                passes_structural=bool(best_result.get("passes_structural")),
                strict_improvement=bool(best_result.get("passes") and best_result.get("strict_improvement")),
                anchor_cue_positive=parse_bool(anchor.get("candidate_cue_positive")),
                anchor_no_shared_context=parse_bool(anchor.get("no_shared_cue_noncue_exact_context")),
            )
            best_id = ""
            if best:
                best_id = hashlib.sha256(
                    (path + "|anchor:" + anchor_shape + ":" + str(anchor_index) + "|optional:" +
                     ";".join(str(index) for index in best[1]) + "|" + str(best_result.get("candidate_sha256", ""))).encode("utf-8")
                ).hexdigest()[:16]
            event_rows.append({
                "normalized_path": path,
                "event_id": event_id(path),
                "anchor_shape_id": anchor_shape,
                "anchor_occurrence_index": anchor_index,
                "anchor_cue_domains": anchor.get("candidate_cue_domains", ""),
                "all_residual_occurrence_count": len(all_occurrences),
                "excluded_broad_or_shared_occurrence_count": len(excluded),
                "optional_occurrence_count": len(optional),
                "combination_count_tested": len(evaluated),
                "candidate_construction_failures": failures,
                "passing_combination_count": sum(bool(item[0].get("passes")) for item in evaluated),
                "strictly_improving_combination_count": sum(bool(item[0].get("passes") and item[0].get("strict_improvement")) for item in evaluated),
                "best_subset_id": best_id,
                "best_selected_occurrence_count": best_result.get("selected_occurrence_count", ""),
                "best_selected_shape_ids": best_result.get("selected_shape_ids", ""),
                "target_distance_to_source": best_result.get("target_distance_to_source", ""),
                "best_candidate_distance_to_source": best_result.get("candidate_distance_to_source", ""),
                "best_distance_improvement": best_result.get("distance_improvement", ""),
                "best_candidate_sha256": best_result.get("candidate_sha256", ""),
                "best_remaining_residual_rows": best_result.get("remaining_residual_rows", ""),
                "classification": classification,
                "review_priority": priority,
                "safe_to_build_separate_local_profile": promotable,
                "runtime_test_deferred": True,
                "next_gate": "build_one_separate_anchor_subset_local_prototype" if promotable else "retain_as_static_context_evidence",
            })

            for rank, (result, indices, _) in enumerate(ranked[:top_combinations_per_event], start=1):
                subset_id = hashlib.sha256(
                    (path + "|anchor:" + anchor_shape + ":" + str(anchor_index) + "|optional:" +
                     ";".join(str(index) for index in indices) + "|" + str(result.get("candidate_sha256", ""))).encode("utf-8")
                ).hexdigest()[:16]
                combination_rows.append({
                    "normalized_path": path,
                    "subset_rank": rank,
                    "subset_id": subset_id,
                    "anchor_shape_id": anchor_shape,
                    "anchor_occurrence_index": anchor_index,
                    "selected_optional_occurrence_indices": ";".join(str(index) for index in indices),
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
                    "passes_structural_gates": result.get("passes_structural", False),
                    "candidate_not_farther_from_original": result.get("checks", {}).get("candidate_not_farther_from_original", False),
                    "strict_improvement": result.get("strict_improvement", False),
                    "exact_original": result.get("exact_original", False),
                    "passes_all_anchor_subset_gates": result.get("passes", False),
                    "review_status": "bounded_in_memory_anchor_subset_evidence_not_runtime_or_censorship_validation",
                })

            if best:
                _, best_indices, best_residuals = best
                selected_rows.append({
                    "normalized_path": path, "best_subset_id": best_id, "selection_order": 0,
                    "role": "mandatory_registered_profile_shape_anchor",
                    "optional_occurrence_index": "", "shape_id": anchor_shape,
                    "occurrence_index": anchor_index, "cue_domains": anchor.get("candidate_cue_domains", ""),
                    "review_status": "best_anchor_subset_component_not_yet_written_as_payload",
                })
                for ordinal, optional_index in enumerate(best_indices, start=1):
                    occurrence = optional[optional_index]
                    selected_rows.append({
                        "normalized_path": path, "best_subset_id": best_id, "selection_order": ordinal,
                        "role": "context_companion_residual", "optional_occurrence_index": optional_index,
                        "shape_id": occurrence.get("shape_id", ""), "occurrence_index": occurrence.get("occurrence_index", ""),
                        "cue_domains": "", "review_status": "best_anchor_subset_component_not_yet_written_as_payload",
                    })
                for residual in best_residuals:
                    residual_rows.append({
                        "normalized_path": path, "best_subset_id": best_id,
                        "shape_id": residual.get("shape_id", ""), "sequence_tag": residual.get("sequence_tag", ""),
                        "source_atom_count": residual.get("source_atom_count", ""),
                        "target_atom_count": residual.get("target_atom_count", ""),
                        "classification": residual.get("classification", ""),
                        "review_status": "best_anchor_subset_remaining_residual_not_assigned_semantics",
                    })

        event_rows.sort(key=lambda row: (not parse_bool(row.get("safe_to_build_separate_local_profile")), str(row.get("normalized_path", ""))))
        combination_rows.sort(key=lambda row: (str(row.get("normalized_path", "")), parse_int(row.get("subset_rank"))))
        selected_rows.sort(key=lambda row: (str(row.get("normalized_path", "")), parse_int(row.get("selection_order"))))
        residual_rows.sort(key=lambda row: (str(row.get("normalized_path", "")), str(row.get("shape_id", ""))))
        excluded_rows.sort(key=lambda row: (str(row.get("normalized_path", "")), str(row.get("shape_id", ""))))
        skipped_rows.sort(key=lambda row: (str(row.get("normalized_path", "")), str(row.get("reason", ""))))

        evidence_root = report_root / EVIDENCE_DIR_NAME
        if evidence_root.exists():
            shutil.rmtree(evidence_root)
        evidence_root.mkdir(parents=True, exist_ok=True)
        write_tsv(evidence_root / "REGISTERED_PROFILE_ANCHOR_SUBSET_EVENTS.tsv", [
            "normalized_path", "event_id", "anchor_shape_id", "anchor_occurrence_index", "anchor_cue_domains",
            "all_residual_occurrence_count", "excluded_broad_or_shared_occurrence_count", "optional_occurrence_count",
            "combination_count_tested", "candidate_construction_failures", "passing_combination_count",
            "strictly_improving_combination_count", "best_subset_id", "best_selected_occurrence_count",
            "best_selected_shape_ids", "target_distance_to_source", "best_candidate_distance_to_source",
            "best_distance_improvement", "best_candidate_sha256", "best_remaining_residual_rows", "classification",
            "review_priority", "safe_to_build_separate_local_profile", "runtime_test_deferred", "next_gate",
        ], event_rows)
        write_tsv(evidence_root / "REGISTERED_PROFILE_ANCHOR_SUBSET_COMBINATIONS.tsv", [
            "normalized_path", "subset_rank", "subset_id", "anchor_shape_id", "anchor_occurrence_index",
            "selected_optional_occurrence_indices", "selected_occurrence_count", "selected_shape_count",
            "selected_shape_ids", "candidate_sha256", "candidate_size", "target_distance_to_source",
            "candidate_distance_to_source", "distance_improvement", "remaining_residual_rows",
            "remaining_residual_shape_ids", "passes_structural_gates", "candidate_not_farther_from_original",
            "strict_improvement", "exact_original", "passes_all_anchor_subset_gates", "review_status",
        ], combination_rows)
        write_tsv(evidence_root / "REGISTERED_PROFILE_ANCHOR_SUBSET_SELECTED_OCCURRENCES.tsv", [
            "normalized_path", "best_subset_id", "selection_order", "role", "optional_occurrence_index",
            "shape_id", "occurrence_index", "cue_domains", "review_status",
        ], selected_rows)
        write_tsv(evidence_root / "REGISTERED_PROFILE_ANCHOR_SUBSET_RESIDUALS.tsv", [
            "normalized_path", "best_subset_id", "shape_id", "sequence_tag", "source_atom_count",
            "target_atom_count", "classification", "review_status",
        ], residual_rows)
        write_tsv(evidence_root / "REGISTERED_PROFILE_ANCHOR_SUBSET_EXCLUDED.tsv", [
            "normalized_path", "shape_id", "occurrence_index", "sequence_tag", "exclusion_reason",
        ], excluded_rows)
        write_tsv(evidence_root / "REGISTERED_PROFILE_ANCHOR_SUBSET_SKIPPED.tsv", [
            "normalized_path", "reason", "eligible_occurrence_count", "possible_combination_count",
        ], skipped_rows)

        promoted = [row for row in event_rows if parse_bool(row.get("safe_to_build_separate_local_profile"))]
        summary: dict[str, object] = {
            "type": "br_quartet_restoration_registered_profile_anchor_subset_evidence_summary",
            "format_version": 1,
            "tool_version": TOOL_VERSION,
            "source_stage48_tool_version": propagation_summary.get("tool_version"),
            "status": "mandatory_registered_shape_anchor_subset_search_complete_no_payload_written_runtime_deferred",
            "anchor_event_rows": len(anchors),
            "analyzed_event_rows": len(event_rows),
            "promotable_event_rows": len(promoted),
            "reported_combination_rows": len(combination_rows),
            "best_selected_occurrence_rows": len(selected_rows),
            "best_remaining_residual_rows": len(residual_rows),
            "excluded_occurrence_rows": len(excluded_rows),
            "skipped_rows": len(skipped_rows),
            "runtime_testing_deferred": True,
            "parameters": {
                "maximum_event_bytes": maximum_event_bytes,
                "maximum_total_occurrences": maximum_total_occurrences,
                "maximum_combinations_per_event": maximum_combinations_per_event,
                "top_combinations_per_event": top_combinations_per_event,
            },
            "policy": {
                "installed_games_modified": False,
                "candidate_ebd_payloads_written": False,
                "pak_repack_performed": False,
                "profile_manifests_modified": False,
                "activation_or_rollback_invoked": False,
                "runtime_validation_inferred": False,
                "censorship_classification_inferred": False,
                "registered_profile_shape_anchor_mandatory": True,
                "context_companion_residuals_assigned_semantics": False,
                "broad_or_recurrent_schema_shapes_selected": False,
                "known_cue_noncue_shared_context_companions_selected": False,
                "exact_reverse_roundtrip_required_for_promotion": True,
                "strict_original_distance_improvement_required_for_promotion": True,
                "legacy_dlc_in_scope": False,
            },
            "next_action": (
                "Upload this metadata report. Build a separate local prototype only for events marked "
                "anchored_subset_strict_improvement_ready_for_local_prototype, reproducing the exact reported "
                "candidate hash and reverse round-trip. Otherwise keep the propagated anchor and companions as "
                "static context evidence without global field semantics."
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
    parser.add_argument("--maximum-total-occurrences", type=int, default=12)
    parser.add_argument("--maximum-combinations-per-event", type=int, default=4096)
    parser.add_argument("--top-combinations-per-event", type=int, default=32)
    args = parser.parse_args()
    project_root = Path(args.project_root).expanduser().resolve()
    workspace_root = Path(args.workspace_root).expanduser().resolve() if args.workspace_root else project_root / ".local/build/quartet_restoration"
    report_root = Path(args.report_root).expanduser().resolve() if args.report_root else project_root / ".local/reports/quartet_restoration"
    try:
        output, summary = collect_anchor_subset_evidence(
            project_root=project_root, workspace_root=workspace_root, report_root=report_root,
            maximum_event_bytes=args.maximum_event_bytes,
            maximum_total_occurrences=args.maximum_total_occurrences,
            maximum_combinations_per_event=args.maximum_combinations_per_event,
            top_combinations_per_event=args.top_combinations_per_event,
        )
    except (AnchorSubsetError, subset.SubsetSearchError, OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print(f"Anchor events analyzed: {summary['analyzed_event_rows']}")
    print(f"Promotable anchored subsets: {summary['promotable_event_rows']}")
    print(f"Report: {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
