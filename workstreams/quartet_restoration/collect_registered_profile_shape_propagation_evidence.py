#!/usr/bin/env python3
"""Find unregistered event occurrences of shapes already used by local profiles.

Stage 48 does not assume that a residual shape has one global meaning.  It uses
registered, checksum-gated event profiles only as discovery anchors, compares
exact context archetypes, rebuilds each unregistered occurrence independently
in memory, and requires the same structural/reverse-round-trip gates used by the
bounded subset search.  No candidate EBD, PAK, manifest or game file is written.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import subprocess
import sys
import tempfile
from collections import defaultdict
from pathlib import Path, PurePosixPath
from typing import Any, Iterable, Mapping, Sequence

WORKSTREAM_ID = "quartet_restoration"
TOOL_VERSION = "0.0.55"
REPORT_NAME = "BR_quartet_restoration_registered_profile_shape_propagation_evidence.tar.zst"
EVIDENCE_DIR_NAME = "registered_profile_shape_propagation_evidence"

REPORT_SPECS = {
    "core": ("core_profile_manifest_evidence", "BR_quartet_restoration_core_profile_manifest_evidence.tar.zst"),
    "context": ("event_delta_context_evidence", "BR_quartet_restoration_event_delta_context_evidence.tar.zst"),
    "scene_cues": ("event_scene_cue_evidence", "BR_quartet_restoration_event_scene_cue_evidence.tar.zst"),
    "event_prototypes": ("event_prototype_evidence", "BR_quartet_restoration_event_prototype_evidence.tar.zst"),
    "single_scene": ("single_scene_composite_evidence", "BR_quartet_restoration_single_scene_composite_evidence.tar.zst"),
    "residual_exact": ("residual_exact_context_evidence", "BR_quartet_restoration_residual_exact_context_evidence.tar.zst"),
    "backlog_prototype": ("presentation_event_backlog_prototype_evidence", "BR_quartet_restoration_presentation_event_backlog_prototype_evidence.tar.zst"),
    "subset_search": ("presentation_event_subset_search_evidence", "BR_quartet_restoration_presentation_event_subset_search_evidence.tar.zst"),
}


class PropagationError(RuntimeError):
    pass


def parse_bool(value: object) -> bool:
    return str(value).strip().casefold() in {"1", "true", "yes", "y"}


def parse_int(value: object, default: int = 0) -> int:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return default


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
        raise PropagationError(f"unsafe report archive member: {raw}")
    return path.as_posix()


def read_tsv(path: Path, *, required: bool = True) -> list[dict[str, str]]:
    if not path.is_file():
        if required:
            raise PropagationError(f"missing prerequisite table: {path}")
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
        raise PropagationError(f"missing prerequisite JSON: {path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PropagationError(f"invalid JSON {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise PropagationError(f"expected JSON object: {path}")
    return value


def extract_archive(archive: Path, destination: Path) -> Path:
    if not archive.is_file():
        raise PropagationError(f"missing prerequisite report archive: {archive}")
    listed = subprocess.run(
        ["tar", "--zstd", "-tf", str(archive)], text=True,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False,
    )
    if listed.returncode != 0:
        raise PropagationError(f"cannot list {archive}: {listed.stderr.strip()}")
    roots: set[str] = set()
    for raw in listed.stdout.splitlines():
        if raw.strip():
            roots.add(PurePosixPath(safe_member_name(raw.strip())).parts[0])
    if len(roots) != 1:
        raise PropagationError(f"expected one report root in {archive}, found {sorted(roots)}")
    destination.mkdir(parents=True, exist_ok=True)
    completed = subprocess.run(
        ["tar", "--zstd", "-xf", str(archive), "-C", str(destination)], text=True,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False,
    )
    if completed.returncode != 0:
        raise PropagationError(f"cannot extract {archive}: {completed.stderr.strip()}")
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
        raise PropagationError(f"cannot create report archive: {result.stderr.strip()}")
    os.replace(temporary, output)


def load_subset_module() -> Any:
    import collect_presentation_event_subset_search_evidence as subset
    return subset


def validate_summary(root: Path, expected_type: str, expected_version: str) -> dict[str, Any]:
    summary = load_json(root / "SUMMARY.json")
    if summary.get("type") != expected_type or summary.get("tool_version") != expected_version:
        raise PropagationError(
            f"unexpected prerequisite summary in {root}: {summary.get('type')!r} {summary.get('tool_version')!r}"
        )
    return summary


def load_registry(project_root: Path, core_root: Path) -> tuple[dict[str, dict[str, Any]], dict[str, list[str]]]:
    summary = validate_summary(
        core_root,
        "br_quartet_restoration_core_profile_manifest_evidence_summary",
        "0.0.54",
    )
    if summary.get("status") != "all_current_local_profiles_registered_runtime_unvalidated":
        raise PropagationError("core report is not in the expected all-registered runtime-unvalidated state")
    if parse_int(summary.get("profile_rows"), -1) != 13:
        raise PropagationError("stage-47 core report must contain 13 profiles")
    if parse_int(summary.get("pack11_profile_rows"), -1) != 11 or parse_int(summary.get("pack10_01_profile_rows"), -1) != 2:
        raise PropagationError("stage-47 core report target counts changed")
    if parse_int(summary.get("runtime_validated_profile_rows"), -1) != 0:
        raise PropagationError("runtime-validated profiles are outside stage-48 assumptions")
    rows = read_tsv(core_root / "CORE_PROFILE_MANIFESTS.tsv")
    if len(rows) != 13 or any(row.get("validation_status") != "passed" for row in rows):
        raise PropagationError("core manifest evidence does not contain 13 passed rows")

    registry_root = project_root / ".local/build/quartet_restoration/core_profiles/generated"
    if not registry_root.is_dir():
        raise PropagationError(f"missing generated registry: {registry_root}")
    manifests: dict[str, dict[str, Any]] = {}
    owners: defaultdict[str, list[str]] = defaultdict(list)
    for path in sorted(registry_root.glob("*.json")):
        data = load_json(path)
        if data.get("workstream_id") != WORKSTREAM_ID:
            continue
        profile_id = str(data.get("profile_id", ""))
        if not profile_id:
            raise PropagationError(f"manifest lacks profile_id: {path}")
        if parse_bool(data.get("runtime_validated")):
            raise PropagationError(f"profile unexpectedly runtime-validated: {profile_id}")
        manifests[profile_id] = data
        for member in data.get("changed_members", []) or []:
            normalized = normalize_event_member(member)
            if normalized.casefold().endswith(".ebd"):
                owners[normalized].append(profile_id)
    if len(manifests) != 13:
        raise PropagationError(f"generated registry contains {len(manifests)} restoration profiles, expected 13")
    return manifests, dict(owners)


def occurrence_key(row: Mapping[str, object]) -> tuple[str, str, int]:
    return (
        normalize_event_member(row.get("normalized_path", "")),
        str(row.get("shape_id", "")),
        parse_int(row.get("occurrence_index"), -1),
    )


def collect_support_rows(
    *, roots: Mapping[str, Path], manifests: Mapping[str, Mapping[str, Any]],
    owners: Mapping[str, list[str]], occurrence_index: Mapping[tuple[str, str, int], Mapping[str, str]],
) -> list[dict[str, object]]:
    support: list[dict[str, object]] = []

    def add(profile_id: str, path: object, shape_id: object, occurrence: object, source: str) -> None:
        normalized = normalize_event_member(path)
        shape = str(shape_id or "")
        index = parse_int(occurrence, -1)
        if not profile_id or profile_id not in manifests or not shape or index < 0:
            return
        if profile_id not in owners.get(normalized, []):
            return
        context = occurrence_index.get((normalized, shape, index))
        if context is None:
            raise PropagationError(f"support occurrence cannot be found in stage 23: {normalized} {shape}:{index}")
        support.append({
            "profile_id": profile_id,
            "normalized_path": normalized,
            "shape_id": shape,
            "occurrence_index": index,
            "pair_context_archetype_id": context.get("pair_context_archetype_id", ""),
            "cue_positive_occurrence": context.get("cue_positive_occurrence", ""),
            "cue_domains": context.get("cue_domains", ""),
            "support_source": source,
            "runtime_validated": False,
            "review_status": "registered_profile_shape_is_discovery_support_not_global_field_semantics",
        })

    for row in read_tsv(roots["event_prototypes"] / "EVENT_PROTOTYPE_FILES.tsv"):
        add(str(row.get("profile_id", "")), row.get("normalized_path"), row.get("shape_id"), row.get("occurrence_index"), "stage24_event_prototype")

    for row in read_tsv(roots["single_scene"] / "SINGLE_SCENE_COMPOSITE_SPLICES.tsv"):
        path = normalize_event_member(row.get("normalized_path", ""))
        for profile_id in owners.get(path, []):
            if profile_id.startswith("single_scene_event_"):
                add(profile_id, path, row.get("shape_id"), row.get("occurrence_index"), "stage29_single_scene_composite")

    promotion = {
        str(row.get("shape_id", ""))
        for row in read_tsv(roots["residual_exact"] / "RESIDUAL_SHAPE_PROMOTION_GATES.tsv")
        if row.get("stage36_gate") == "eligible_for_stage_36_local_prototype_review"
    }
    for row in read_tsv(roots["residual_exact"] / "RESIDUAL_EXACT_CONTEXT_OCCURRENCES.tsv"):
        if str(row.get("shape_id", "")) not in promotion:
            continue
        path = normalize_event_member(row.get("normalized_path", ""))
        for profile_id in owners.get(path, []):
            if profile_id.startswith("shared_presentation_"):
                add(profile_id, path, row.get("shape_id"), row.get("occurrence_index"), "stage35_residual_exact_context")

    passed_backlog_profiles = {
        str(row.get("profile_id", ""))
        for row in read_tsv(roots["backlog_prototype"] / "PRESENTATION_EVENT_BACKLOG_PROFILES.tsv")
        if row.get("validation_status") == "passed"
    }
    for row in read_tsv(roots["backlog_prototype"] / "PRESENTATION_EVENT_BACKLOG_SELECTED_SPLICES.tsv"):
        profile_id = str(row.get("profile_id", ""))
        if profile_id in passed_backlog_profiles and row.get("input_validation_status") == "passed":
            add(profile_id, row.get("normalized_path"), row.get("shape_id"), row.get("occurrence_index"), "stage41_backlog_prototype")

    for row in read_tsv(roots["subset_search"] / "PRESENTATION_EVENT_SUBSET_SEARCH_SELECTED_OCCURRENCES.tsv"):
        path = normalize_event_member(row.get("normalized_path", ""))
        profile_ids = [profile for profile in owners.get(path, []) if profile.startswith("candidate_subset_")]
        if len(profile_ids) != 1:
            raise PropagationError(f"expected one registered subset profile for {path}, found {profile_ids}")
        add(profile_ids[0], path, row.get("shape_id"), row.get("occurrence_index"), "stage44_subset_search")

    dedup: dict[tuple[str, str, str, int], dict[str, object]] = {}
    for row in support:
        key = (str(row["profile_id"]), str(row["normalized_path"]), str(row["shape_id"]), int(row["occurrence_index"]))
        dedup[key] = row
    result = sorted(dedup.values(), key=lambda row: (str(row["profile_id"]), str(row["normalized_path"]), str(row["shape_id"]), int(row["occurrence_index"])))
    if not result:
        raise PropagationError("no registered event-profile shape support rows were collected")
    return result


def classify_propagation_result(
    *, binary_structural_pass: bool, strict_improvement: bool, cue_positive: bool,
    no_shared_context: bool, exact_context_support_count: int,
) -> tuple[str, str, str, bool]:
    eligible = binary_structural_pass and strict_improvement and cue_positive and no_shared_context
    if eligible and exact_context_support_count > 0:
        return (
            "registered_profile_exact_context_strict_improvement_candidate",
            "critical",
            "build_separate_local_profile_with_exact_hash_and_reverse_roundtrip",
            True,
        )
    if eligible:
        return (
            "registered_profile_cross_context_strict_improvement_candidate",
            "high",
            "build_separate_experimental_local_profile_without_assuming_global_shape_semantics",
            True,
        )
    if binary_structural_pass and strict_improvement and not cue_positive:
        return (
            "registered_profile_shape_noncue_state_candidate",
            "medium",
            "retain_as_control_or_route_state_evidence_until_scene_support_exists",
            False,
        )
    if binary_structural_pass:
        return (
            "registered_profile_shape_structurally_safe_but_not_improving",
            "low",
            "retain_evidence_only",
            False,
        )
    return (
        "registered_profile_shape_static_gates_failed",
        "low",
        "do_not_build",
        False,
    )


def collect_propagation(
    *, project_root: Path, workspace_root: Path, report_root: Path,
    maximum_event_bytes: int = 2 * 1024 * 1024,
) -> tuple[Path, dict[str, object]]:
    project_root = project_root.expanduser().resolve()
    workspace_root = workspace_root.expanduser().resolve()
    report_root = report_root.expanduser().resolve()
    subset = load_subset_module()
    br = subset.load_restoration_tool(project_root)

    with tempfile.TemporaryDirectory(prefix="br-profile-shape-propagation-") as temporary_name:
        temporary = Path(temporary_name)
        roots = {key: locate_report_root(report_root, key, temporary) for key in REPORT_SPECS}
        manifests, owners = load_registry(project_root, roots["core"])
        validate_summary(roots["context"], "br_quartet_restoration_event_delta_context_evidence_summary", "0.0.27")
        validate_summary(roots["scene_cues"], "br_quartet_restoration_event_scene_cue_evidence_summary", "0.0.25")
        validate_summary(roots["event_prototypes"], "br_quartet_restoration_event_prototype_evidence_summary", "0.0.28")
        validate_summary(roots["single_scene"], "br_quartet_restoration_single_scene_composite_evidence_summary", "0.0.35")
        validate_summary(roots["residual_exact"], "br_quartet_restoration_residual_exact_context_evidence_summary", "0.0.41")
        backlog_summary = validate_summary(roots["backlog_prototype"], "br_quartet_restoration_presentation_event_backlog_prototype_evidence_summary", "0.0.48")
        if parse_int(backlog_summary.get("promoted_profile_rows"), -1) != 1:
            raise PropagationError("corrected stage-41 report no longer contains one promoted profile")
        subset_summary = validate_summary(roots["subset_search"], "br_quartet_restoration_presentation_event_subset_search_evidence_summary", "0.0.51")
        if parse_int(subset_summary.get("promotable_event_rows"), -1) != 6:
            raise PropagationError("stage-44 report no longer contains six promotable events")

        occurrence_rows = read_tsv(roots["context"] / "EVENT_DELTA_CONTEXT_OCCURRENCES.tsv")
        occurrence_index = {occurrence_key(row): row for row in occurrence_rows}
        support_rows = collect_support_rows(
            roots=roots, manifests=manifests, owners=owners, occurrence_index=occurrence_index,
        )
        support_by_shape: defaultdict[str, list[dict[str, object]]] = defaultdict(list)
        for row in support_rows:
            support_by_shape[str(row["shape_id"])].append(row)

        cue_by_path = {
            normalize_event_member(row.get("normalized_path", "")): row
            for row in read_tsv(roots["scene_cues"] / "EVENT_RESIDUAL_CUE_CORRELATION.tsv")
        }
        control_by_shape = {
            str(row.get("shape_id", "")): row
            for row in read_tsv(roots["context"] / "EVENT_DELTA_CUE_NONCUE_COMPARISON.tsv")
        }

        candidate_occurrences = [
            row for row in occurrence_rows
            if str(row.get("shape_id", "")) in support_by_shape
            and normalize_event_member(row.get("normalized_path", "")) not in owners
        ]
        candidate_occurrences.sort(key=lambda row: (normalize_event_member(row.get("normalized_path", "")), str(row.get("shape_id", "")), parse_int(row.get("occurrence_index"), -1)))

        differences = br.load_report_jsons(report_root, "differences")
        event_report = next((row for row in differences if str(row.get("source_archive_group", "")) == "br1_events"), None)
        if event_report is None:
            raise PropagationError("missing br1_events difference report")
        entry_by_path = {
            normalize_event_member(row.get("normalized_path", "")): row
            for row in event_report.get("entries", [])
            if row.get("scope_status") == "in_scope" and row.get("source") and row.get("target")
        }

        comparison_rows: list[dict[str, object]] = []
        test_rows: list[dict[str, object]] = []
        review_rows: list[dict[str, object]] = []
        skipped_rows: list[dict[str, object]] = []

        for occurrence in candidate_occurrences:
            path = normalize_event_member(occurrence.get("normalized_path", ""))
            shape_id = str(occurrence.get("shape_id", ""))
            candidate_archetype = str(occurrence.get("pair_context_archetype_id", ""))
            supports = support_by_shape[shape_id]
            for support in supports:
                comparison_rows.append({
                    "shape_id": shape_id,
                    "candidate_path": path,
                    "candidate_occurrence_index": parse_int(occurrence.get("occurrence_index"), -1),
                    "candidate_cue_positive": occurrence.get("cue_positive_occurrence", ""),
                    "candidate_cue_domains": occurrence.get("cue_domains", ""),
                    "candidate_context_archetype_id": candidate_archetype,
                    "support_profile_id": support["profile_id"],
                    "support_path": support["normalized_path"],
                    "support_context_archetype_id": support["pair_context_archetype_id"],
                    "same_exact_pair_context_archetype": candidate_archetype == str(support["pair_context_archetype_id"]),
                    "review_status": "same_shape_context_comparison_does_not_assign_global_shape_semantics",
                })

            entry = entry_by_path.get(path)
            if entry is None:
                skipped_rows.append({"normalized_path": path, "shape_id": shape_id, "occurrence_index": occurrence.get("occurrence_index", ""), "reason": "missing_inventory_entry"})
                continue
            source_ref = entry["source"]
            target_ref = entry["target"]
            source_file = br.inventory_workspace_file(workspace_root, "source", "br1_events", source_ref["archive"], source_ref["path"])
            target_file = br.inventory_workspace_file(workspace_root, "target", "br1_events", target_ref["archive"], target_ref["path"])
            if not source_file.is_file() or not target_file.is_file():
                skipped_rows.append({"normalized_path": path, "shape_id": shape_id, "occurrence_index": occurrence.get("occurrence_index", ""), "reason": "workspace_payload_missing"})
                continue
            if source_file.stat().st_size > maximum_event_bytes or target_file.stat().st_size > maximum_event_bytes:
                skipped_rows.append({"normalized_path": path, "shape_id": shape_id, "occurrence_index": occurrence.get("occurrence_index", ""), "reason": "maximum_event_bytes_exceeded"})
                continue
            source_payload = source_file.read_bytes()
            target_payload = target_file.read_bytes()
            if hashlib.sha256(source_payload).hexdigest() != source_ref["sha256"] or hashlib.sha256(target_payload).hexdigest() != target_ref["sha256"]:
                raise PropagationError(f"workspace hash mismatch for {path}")

            result, _ = subset.evaluate_combination(
                br=br, source_payload=source_payload, target_payload=target_payload,
                occurrences=[occurrence], control_by_shape=control_by_shape,
            )
            checks = result.get("checks", {}) if isinstance(result, dict) else {}
            binary_gate_names = {
                "all_selected_shapes_removed", "selected_shape_count_after_zero",
                "no_introduced_coarse_shapes", "no_nonselected_coarse_shapes_removed",
                "all_nonselected_shape_counters_preserved", "candidate_header_preserved_from_target",
                "candidate_trailing_preserved_from_target", "candidate_header_valid",
                "exact_target_reverse_roundtrip",
            }
            binary_structural_pass = bool(checks) and all(parse_bool(checks.get(name)) for name in binary_gate_names)
            cue_positive = parse_bool(occurrence.get("cue_positive_occurrence"))
            no_shared_context = parse_bool(checks.get("no_shared_cue_noncue_exact_context"))
            strict_improvement = parse_bool(result.get("strict_improvement"))
            exact_context_supports = [support for support in supports if candidate_archetype and candidate_archetype == str(support["pair_context_archetype_id"])]
            classification, priority, next_gate, eligible = classify_propagation_result(
                binary_structural_pass=binary_structural_pass,
                strict_improvement=strict_improvement,
                cue_positive=cue_positive,
                no_shared_context=no_shared_context,
                exact_context_support_count=len(exact_context_supports),
            )

            cue_row = cue_by_path.get(path, {})
            test_rows.append({
                "normalized_path": path,
                "event_id": event_id(path),
                "shape_id": shape_id,
                "occurrence_index": parse_int(occurrence.get("occurrence_index"), -1),
                "candidate_cue_positive": cue_positive,
                "candidate_cue_domains": occurrence.get("cue_domains", "") or cue_row.get("cue_domains", ""),
                "support_profile_count": len({str(row["profile_id"]) for row in supports}),
                "support_profile_ids": ";".join(sorted({str(row["profile_id"]) for row in supports})),
                "support_path_count": len({str(row["normalized_path"]) for row in supports}),
                "exact_context_support_count": len(exact_context_supports),
                "same_shape_different_context": len(exact_context_supports) == 0,
                "binary_structural_gates_passed": binary_structural_pass,
                "no_shared_cue_noncue_exact_context": no_shared_context,
                "candidate_sha256": result.get("candidate_sha256", ""),
                "candidate_size": result.get("candidate_size", ""),
                "target_distance_to_source": result.get("target_distance_to_source", ""),
                "candidate_distance_to_source": result.get("candidate_distance_to_source", ""),
                "distance_improvement": result.get("distance_improvement", ""),
                "strict_improvement": strict_improvement,
                "exact_original": result.get("exact_original", ""),
                "remaining_residual_rows": result.get("remaining_residual_rows", ""),
                "remaining_residual_shape_ids": result.get("remaining_residual_shape_ids", ""),
                "eligible_for_separate_local_profile": eligible,
                "classification": classification,
                "review_priority": priority,
                "next_gate": next_gate,
                "review_status": "in_memory_profile_shape_propagation_test_not_runtime_or_censorship_validation",
            })

        by_path: defaultdict[str, list[dict[str, object]]] = defaultdict(list)
        for row in test_rows:
            by_path[str(row["normalized_path"])].append(row)
        for path, rows in sorted(by_path.items()):
            eligible_rows = [row for row in rows if parse_bool(row.get("eligible_for_separate_local_profile"))]
            best = max(rows, key=lambda row: (parse_int(row.get("distance_improvement"), -10**9), str(row.get("shape_id", ""))))
            if eligible_rows:
                best = max(eligible_rows, key=lambda row: (parse_int(row.get("distance_improvement"), -10**9), str(row.get("shape_id", ""))))
                event_class = str(best["classification"])
                priority = str(best["review_priority"])
                next_gate = str(best["next_gate"])
            elif any(row.get("classification") == "registered_profile_shape_noncue_state_candidate" for row in rows):
                event_class = "registered_profile_shape_noncue_event_control"
                priority = "medium"
                next_gate = "retain_as_control_or_route_state_evidence_until_scene_support_exists"
            else:
                event_class = "registered_profile_shape_event_not_promoted"
                priority = "low"
                next_gate = "retain_evidence_only"
            review_rows.append({
                "normalized_path": path,
                "event_id": event_id(path),
                "candidate_occurrence_count": len(rows),
                "profile_supported_shape_ids": ";".join(sorted({str(row["shape_id"]) for row in rows})),
                "cue_domains": ";".join(sorted({domain for row in rows for domain in str(row.get("candidate_cue_domains", "")).split(";") if domain})),
                "eligible_occurrence_count": len(eligible_rows),
                "best_shape_id": best.get("shape_id", ""),
                "best_candidate_sha256": best.get("candidate_sha256", ""),
                "best_distance_improvement": best.get("distance_improvement", ""),
                "classification": event_class,
                "review_priority": priority,
                "safe_to_build_separate_local_profile": bool(eligible_rows),
                "runtime_test_deferred": True,
                "next_gate": next_gate,
                "review_status": "profile_support_is_discovery_evidence_not_global_shape_semantics",
            })

        support_rows.sort(key=lambda row: (str(row["profile_id"]), str(row["normalized_path"]), str(row["shape_id"]), int(row["occurrence_index"])))
        comparison_rows.sort(key=lambda row: (str(row["candidate_path"]), str(row["shape_id"]), str(row["support_profile_id"]), str(row["support_path"])))
        test_rows.sort(key=lambda row: (str(row["normalized_path"]), str(row["shape_id"]), parse_int(row["occurrence_index"], -1)))
        review_rows.sort(key=lambda row: ({"critical": 0, "high": 1, "medium": 2, "low": 3}.get(str(row["review_priority"]), 9), str(row["normalized_path"])))

        evidence_dir = report_root / EVIDENCE_DIR_NAME
        if evidence_dir.exists():
            import shutil
            shutil.rmtree(evidence_dir)
        evidence_dir.mkdir(parents=True)
        write_tsv(evidence_dir / "REGISTERED_EVENT_PROFILE_SHAPE_SUPPORT.tsv", [
            "profile_id", "normalized_path", "shape_id", "occurrence_index", "pair_context_archetype_id",
            "cue_positive_occurrence", "cue_domains", "support_source", "runtime_validated", "review_status",
        ], support_rows)
        write_tsv(evidence_dir / "PROFILE_SHAPE_CONTEXT_COMPARISONS.tsv", [
            "shape_id", "candidate_path", "candidate_occurrence_index", "candidate_cue_positive", "candidate_cue_domains",
            "candidate_context_archetype_id", "support_profile_id", "support_path", "support_context_archetype_id",
            "same_exact_pair_context_archetype", "review_status",
        ], comparison_rows)
        write_tsv(evidence_dir / "PROFILE_SHAPE_PROPAGATION_SPLICE_TESTS.tsv", [
            "normalized_path", "event_id", "shape_id", "occurrence_index", "candidate_cue_positive", "candidate_cue_domains",
            "support_profile_count", "support_profile_ids", "support_path_count", "exact_context_support_count",
            "same_shape_different_context", "binary_structural_gates_passed", "no_shared_cue_noncue_exact_context",
            "candidate_sha256", "candidate_size", "target_distance_to_source", "candidate_distance_to_source",
            "distance_improvement", "strict_improvement", "exact_original", "remaining_residual_rows",
            "remaining_residual_shape_ids", "eligible_for_separate_local_profile", "classification", "review_priority",
            "next_gate", "review_status",
        ], test_rows)
        write_tsv(evidence_dir / "FOCUSED_PROFILE_SHAPE_PROPAGATION_REVIEW.tsv", [
            "normalized_path", "event_id", "candidate_occurrence_count", "profile_supported_shape_ids", "cue_domains",
            "eligible_occurrence_count", "best_shape_id", "best_candidate_sha256", "best_distance_improvement",
            "classification", "review_priority", "safe_to_build_separate_local_profile", "runtime_test_deferred",
            "next_gate", "review_status",
        ], review_rows)
        write_tsv(evidence_dir / "PROFILE_SHAPE_PROPAGATION_SKIPPED.tsv", [
            "normalized_path", "shape_id", "occurrence_index", "reason",
        ], skipped_rows)

        summary: dict[str, object] = {
            "type": "br_quartet_restoration_registered_profile_shape_propagation_evidence_summary",
            "format_version": 1,
            "tool_version": TOOL_VERSION,
            "status": "registered_profile_shapes_checked_in_unregistered_event_contexts_runtime_deferred",
            "registry_profile_rows": len(manifests),
            "registered_event_rows": len(owners),
            "registered_shape_support_rows": len(support_rows),
            "registered_shape_count": len(support_by_shape),
            "unregistered_candidate_occurrence_rows": len(candidate_occurrences),
            "analyzed_splice_rows": len(test_rows),
            "candidate_event_rows": len(review_rows),
            "eligible_profile_event_rows": sum(parse_bool(row.get("safe_to_build_separate_local_profile")) for row in review_rows),
            "noncue_control_event_rows": sum(row.get("classification") == "registered_profile_shape_noncue_event_control" for row in review_rows),
            "skipped_rows": len(skipped_rows),
            "policy": {
                "installed_games_modified": False,
                "candidate_ebd_payloads_written": False,
                "pak_repack_performed": False,
                "profile_manifests_modified": False,
                "activation_or_rollback_invoked": False,
                "runtime_validation_inferred": False,
                "registered_shape_treated_as_global_field_semantics": False,
                "same_shape_different_context_auto_promoted": False,
                "exact_reverse_roundtrip_required_for_promotion": True,
                "strict_original_distance_improvement_required_for_promotion": True,
                "cue_positive_occurrence_required_for_promotion": True,
                "legacy_dlc_in_scope": False,
            },
            "next_action": "Upload this report. Build only cue-positive occurrences that pass every binary gate, avoid cue/non-cue-shared exact contexts, and strictly improve distance to Original; retain non-cue or non-improving occurrences as controls/evidence.",
        }
        (evidence_dir / "SUMMARY.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        output = report_root / REPORT_NAME
        make_report_archive(evidence_dir, output)
        return output, summary


def default_project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path, default=default_project_root())
    parser.add_argument("--workspace-root", type=Path)
    parser.add_argument("--report-root", type=Path)
    parser.add_argument("--maximum-event-bytes", type=int, default=2 * 1024 * 1024)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    project_root = args.project_root.expanduser().resolve()
    workspace_root = args.workspace_root or project_root / ".local/build/quartet_restoration"
    report_root = args.report_root or project_root / ".local/reports/quartet_restoration"
    try:
        output, summary = collect_propagation(
            project_root=project_root,
            workspace_root=workspace_root,
            report_root=report_root,
            maximum_event_bytes=args.maximum_event_bytes,
        )
    except (PropagationError, OSError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print(f"Registered profiles: {summary['registry_profile_rows']}")
    print(f"Registered profile shape support rows: {summary['registered_shape_support_rows']}")
    print(f"Unregistered candidate events: {summary['candidate_event_rows']}")
    print(f"Eligible next local profiles: {summary['eligible_profile_event_rows']}")
    print(f"Report: {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
