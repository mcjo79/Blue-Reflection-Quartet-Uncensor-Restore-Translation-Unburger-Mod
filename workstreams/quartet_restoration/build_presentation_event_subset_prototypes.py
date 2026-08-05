#!/usr/bin/env python3
"""Build separate local EBD prototypes from the stage-44 best subsets.

This stage consumes only events promoted by the bounded stage-44 subset search.
For every event it independently reconstructs the exact reported candidate from
current Original and Quartet EBD payloads, reproduces the stage-44 SHA-256 and
quality metrics, preserves every non-selected residual-shape counter, and proves
an exact reverse round-trip to the current Quartet target.  Each passing event
is written as a separate local, runtime-unvalidated profile below the restoration
workspace.  No PAK, core manifest, transaction, activation or game file is
created or modified.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
from collections import Counter, defaultdict
from pathlib import Path, PurePosixPath
from typing import Any, Iterable, Mapping, Sequence

WORKSTREAM_ID = "quartet_restoration"
TOOL_VERSION = "0.0.52"
REPORT_NAME = "BR_quartet_restoration_presentation_event_subset_prototype_evidence.tar.zst"
EVIDENCE_DIR_NAME = "presentation_event_subset_prototype_evidence"
PROTOTYPE_SUBDIR = Path("prototypes/presentation_event_subset")
SOURCE_REPORT_DIR = "presentation_event_subset_search_evidence"
SOURCE_REPORT_ARCHIVE = "BR_quartet_restoration_presentation_event_subset_search_evidence.tar.zst"


class SubsetPrototypeError(RuntimeError):
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


def read_tsv(path: Path, *, required: bool = True) -> list[dict[str, str]]:
    if not path.is_file():
        if required:
            raise SubsetPrototypeError(f"missing prerequisite table: {path}")
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
        raise SubsetPrototypeError(f"missing prerequisite JSON: {path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SubsetPrototypeError(f"invalid JSON {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise SubsetPrototypeError(f"expected JSON object: {path}")
    return value


def atomic_json(path: Path, data: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def atomic_bytes(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_bytes(data)
    os.replace(temporary, path)


def safe_member_name(raw: str) -> str:
    path = PurePosixPath(raw)
    if path.is_absolute() or not path.parts or ".." in path.parts:
        raise SubsetPrototypeError(f"unsafe report archive member: {raw}")
    return path.as_posix()


def extract_archive(archive: Path, destination: Path) -> Path:
    if not archive.is_file():
        raise SubsetPrototypeError(f"missing prerequisite report archive: {archive}")
    listed = subprocess.run(
        ["tar", "--zstd", "-tf", str(archive)], text=True,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False,
    )
    if listed.returncode != 0:
        raise SubsetPrototypeError(f"cannot list {archive}: {listed.stderr.strip()}")
    roots: set[str] = set()
    for raw in listed.stdout.splitlines():
        if raw.strip():
            roots.add(PurePosixPath(safe_member_name(raw.strip())).parts[0])
    if len(roots) != 1:
        raise SubsetPrototypeError(f"expected one report root in {archive}, found {sorted(roots)}")
    destination.mkdir(parents=True, exist_ok=True)
    completed = subprocess.run(
        ["tar", "--zstd", "-xf", str(archive), "-C", str(destination)], text=True,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False,
    )
    if completed.returncode != 0:
        raise SubsetPrototypeError(f"cannot extract {archive}: {completed.stderr.strip()}")
    return destination / next(iter(roots))


def locate_source_report(report_root: Path, temporary: Path) -> Path:
    direct = report_root / SOURCE_REPORT_DIR
    if direct.is_dir():
        return direct
    return extract_archive(report_root / SOURCE_REPORT_ARCHIVE, temporary / "subset-search")


def load_module(path: Path, name: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise SubsetPrototypeError(f"cannot load Python module: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def load_tools(project_root: Path) -> tuple[Any, Any]:
    restoration_path = project_root / "Blue_Reflection_Text_Tool/br_restoration_tool.py"
    subset_path = project_root / "workstreams/quartet_restoration/collect_presentation_event_subset_search_evidence.py"
    if not restoration_path.is_file():
        raise SubsetPrototypeError(f"missing restoration tool: {restoration_path}")
    if not subset_path.is_file():
        raise SubsetPrototypeError(f"missing stage-44 tool: {subset_path}")
    tool_root = restoration_path.parent
    sys.path.insert(0, str(tool_root))
    try:
        import br_restoration_tool as restoration  # type: ignore
    finally:
        try:
            sys.path.remove(str(tool_root))
        except ValueError:
            pass
    subset = load_module(subset_path, "br_stage44_subset_search_for_stage45")
    return restoration, subset


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
        raise SubsetPrototypeError(f"cannot create report archive: {result.stderr.strip()}")
    os.replace(temporary, output)


def byte_difference_count(left: bytes, right: bytes) -> int:
    overlap = min(len(left), len(right))
    return sum(a != b for a, b in zip(left[:overlap], right[:overlap])) + abs(len(left) - len(right))


def validate_stage44(root: Path) -> tuple[
    dict[str, Any], list[dict[str, str]], dict[tuple[str, str], dict[str, str]],
    dict[tuple[str, str], list[dict[str, str]]], dict[tuple[str, str], list[dict[str, str]]],
]:
    summary = load_json(root / "SUMMARY.json")
    if summary.get("type") != "br_quartet_restoration_presentation_event_subset_search_evidence_summary":
        raise SubsetPrototypeError("stage-44 report has an unexpected summary type")
    if summary.get("tool_version") != "0.0.51":
        raise SubsetPrototypeError(f"stage-44 report tool version is {summary.get('tool_version')!r}, expected '0.0.51'")
    if summary.get("status") != "bounded_cue_linked_residual_subset_search_complete_no_payload_written_runtime_deferred":
        raise SubsetPrototypeError(f"stage-44 report status is unexpected: {summary.get('status')!r}")
    if not parse_bool(summary.get("runtime_testing_deferred")):
        raise SubsetPrototypeError("stage-44 report must keep runtime testing deferred")
    policy = summary.get("policy")
    if not isinstance(policy, dict) or any(parse_bool(policy.get(key)) for key in (
        "installed_games_modified", "candidate_ebd_payloads_written", "pak_repacked",
        "core_profile_manifest_modified", "activation_or_rollback_invoked",
        "runtime_validation_inferred", "censorship_classification_inferred",
    )):
        raise SubsetPrototypeError("stage-44 report policy is not metadata-only")

    event_rows = read_tsv(root / "PRESENTATION_EVENT_SUBSET_SEARCH_EVENTS.tsv")
    promotable = [
        row for row in event_rows
        if row.get("classification") == "strictly_improving_subset_ready_for_local_prototype"
        and parse_bool(row.get("safe_to_build_local_profile_without_runtime"))
        and parse_bool(row.get("runtime_test_deferred"))
    ]
    if len(promotable) != parse_int(summary.get("promotable_event_rows"), -1):
        raise SubsetPrototypeError("stage-44 promotable event count changed")
    if not promotable:
        raise SubsetPrototypeError("stage-44 report contains no promotable events")

    combination_by_key: dict[tuple[str, str], dict[str, str]] = {}
    for row in read_tsv(root / "PRESENTATION_EVENT_SUBSET_SEARCH_COMBINATIONS.tsv"):
        key = (normalize_event_member(row.get("normalized_path", "")), str(row.get("subset_id", "")))
        if key not in combination_by_key or parse_int(row.get("subset_rank"), 999999) < parse_int(combination_by_key[key].get("subset_rank"), 999999):
            combination_by_key[key] = row

    selected_by_key: defaultdict[tuple[str, str], list[dict[str, str]]] = defaultdict(list)
    for row in read_tsv(root / "PRESENTATION_EVENT_SUBSET_SEARCH_SELECTED_OCCURRENCES.tsv"):
        key = (normalize_event_member(row.get("normalized_path", "")), str(row.get("best_subset_id", "")))
        selected_by_key[key].append(row)
    for rows in selected_by_key.values():
        rows.sort(key=lambda row: parse_int(row.get("selection_order"), 999999))

    residuals_by_key: defaultdict[tuple[str, str], list[dict[str, str]]] = defaultdict(list)
    for row in read_tsv(root / "PRESENTATION_EVENT_SUBSET_SEARCH_RESIDUALS.tsv"):
        key = (normalize_event_member(row.get("normalized_path", "")), str(row.get("best_subset_id", "")))
        residuals_by_key[key].append(row)

    for event in promotable:
        path = normalize_event_member(event.get("normalized_path", ""))
        subset_id = str(event.get("best_subset_id", ""))
        key = (path, subset_id)
        combination = combination_by_key.get(key)
        selected = selected_by_key.get(key, [])
        if combination is None:
            raise SubsetPrototypeError(f"stage-44 best combination row is missing: {path} {subset_id}")
        if not parse_bool(combination.get("passes_all_subset_gates")) or not parse_bool(combination.get("strict_improvement")):
            raise SubsetPrototypeError(f"stage-44 best combination is not strictly passing: {path}")
        if combination.get("candidate_sha256") != event.get("best_candidate_sha256"):
            raise SubsetPrototypeError(f"stage-44 event/combination hash disagreement: {path}")
        if parse_int(event.get("best_selected_occurrence_count"), -1) != len(selected):
            raise SubsetPrototypeError(f"stage-44 selected occurrence count changed: {path}")
        selected_shapes = sorted(str(row.get("shape_id", "")) for row in selected)
        if sorted(split_cell(event.get("best_selected_shape_ids"))) != sorted(set(selected_shapes)):
            raise SubsetPrototypeError(f"stage-44 selected shape set changed: {path}")
    return summary, promotable, combination_by_key, dict(selected_by_key), dict(residuals_by_key)


def build_subset_prototypes(
    *, project_root: Path, workspace_root: Path, report_root: Path,
    maximum_event_bytes: int = 2 * 1024 * 1024,
) -> tuple[Path, dict[str, object]]:
    project_root = project_root.expanduser().resolve()
    workspace_root = workspace_root.expanduser().resolve()
    report_root = report_root.expanduser().resolve()
    br, subset = load_tools(project_root)

    with tempfile.TemporaryDirectory(prefix="br-subset-prototypes-") as temporary_name:
        temporary = Path(temporary_name)
        source_root = locate_source_report(report_root, temporary)
        stage44_summary, event_rows, combination_by_key, selected_by_key, reported_residuals_by_key = validate_stage44(source_root)

        registry_owners = subset.load_registry_event_owners(project_root)
        differences = br.load_report_jsons(report_root, "differences")
        event_report = next(
            (row for row in differences if str(row.get("source_archive_group", "")) == "br1_events"),
            None,
        )
        if event_report is None:
            raise SubsetPrototypeError("missing br1_events difference report")
        entry_by_path = {
            normalize_event_member(row.get("normalized_path", "")): row
            for row in event_report.get("entries", [])
            if row.get("scope_status") == "in_scope" and row.get("source") and row.get("target")
        }

        prototype_root = workspace_root / PROTOTYPE_SUBDIR
        try:
            prototype_root.relative_to(workspace_root)
        except ValueError as exc:
            raise SubsetPrototypeError("prototype root escapes quartet_restoration workspace") from exc
        if prototype_root.exists():
            shutil.rmtree(prototype_root)
        prototype_root.mkdir(parents=True, exist_ok=True)

        profile_rows: list[dict[str, object]] = []
        file_rows: list[dict[str, object]] = []
        selection_rows: list[dict[str, object]] = []
        residual_rows: list[dict[str, object]] = []
        validation_rows: list[dict[str, object]] = []
        skipped_rows: list[dict[str, object]] = []

        for event in sorted(event_rows, key=lambda row: normalize_event_member(row.get("normalized_path", ""))):
            path = normalize_event_member(event.get("normalized_path", ""))
            subset_id = str(event.get("best_subset_id", ""))
            key = (path, subset_id)
            profile_id = f"candidate_subset_{event_id(path)}_{subset_id}"
            combination = combination_by_key[key]
            selected_report_rows = selected_by_key[key]
            reported_residual_rows = reported_residuals_by_key.get(key, [])

            if path in registry_owners:
                skipped_rows.append({"profile_id": profile_id, "normalized_path": path, "reason": "event_already_owned_by_registered_profile"})
                continue
            entry = entry_by_path.get(path)
            if entry is None:
                skipped_rows.append({"profile_id": profile_id, "normalized_path": path, "reason": "difference_entry_missing"})
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
                skipped_rows.append({"profile_id": profile_id, "normalized_path": path, "reason": "workspace_event_payload_missing"})
                continue
            if source_path.stat().st_size > maximum_event_bytes or target_path.stat().st_size > maximum_event_bytes:
                skipped_rows.append({"profile_id": profile_id, "normalized_path": path, "reason": "maximum_event_bytes_exceeded"})
                continue
            source_payload = source_path.read_bytes()
            target_payload = target_path.read_bytes()
            source_sha = hashlib.sha256(source_payload).hexdigest()
            target_sha = hashlib.sha256(target_payload).hexdigest()
            if source_ref.get("sha256") and source_sha != str(source_ref.get("sha256")):
                skipped_rows.append({"profile_id": profile_id, "normalized_path": path, "reason": "source_payload_sha256_mismatch"})
                continue
            if target_ref.get("sha256") and target_sha != str(target_ref.get("sha256")):
                skipped_rows.append({"profile_id": profile_id, "normalized_path": path, "reason": "target_payload_sha256_mismatch"})
                continue

            selected_occurrences = [
                {
                    "normalized_path": path,
                    "shape_id": row.get("shape_id", ""),
                    "occurrence_index": row.get("occurrence_index", ""),
                    "cue_positive_occurrence": True,
                    "cue_domains": row.get("cue_domains", event.get("cue_domains", "")),
                    "selection_reasons": row.get("selection_reasons", ""),
                }
                for row in selected_report_rows
            ]
            try:
                candidate, metadata, rebuilt_residuals = br.construct_composite_inverse_event_candidate(
                    source_payload=source_payload,
                    target_payload=target_payload,
                    selected_occurrences=selected_occurrences,
                )
                if candidate is None:
                    raise SubsetPrototypeError(f"candidate construction failed: {metadata.get('status')}")
                operations, source_profile, target_profile = subset.build_operations(
                    br=br,
                    source_payload=source_payload,
                    target_payload=target_payload,
                    selected_occurrences=selected_occurrences,
                )
                reverse_payload = subset.reverse_candidate(
                    candidate_payload=candidate,
                    target_payload=target_payload,
                    operations=operations,
                    br=br,
                )
            except Exception as exc:  # fail this profile without leaving a partial payload
                skipped_rows.append({"profile_id": profile_id, "normalized_path": path, "reason": f"candidate_reconstruction_failed:{exc}"})
                continue

            candidate_header = br.parse_ebd_header_schema(candidate)
            candidate_profile = br.profile_ebd_post_header_words(
                candidate,
                int(candidate_header.get("header_end", 0)),
                maximum_words=max(1, len(candidate) // 4 + 8),
            )
            before_counter = subset.shape_counter(br, source_profile, target_profile)
            after_counter = subset.shape_counter(br, source_profile, candidate_profile)
            selected_counter = Counter(str(row.get("shape_id", "")) for row in selected_occurrences)
            nonselected_before = before_counter.copy()
            nonselected_after = after_counter.copy()
            for shape_id in selected_counter:
                nonselected_before.pop(shape_id, None)
                nonselected_after.pop(shape_id, None)

            candidate_sha = hashlib.sha256(candidate).hexdigest()
            target_distance = byte_difference_count(target_payload, source_payload)
            candidate_distance = byte_difference_count(candidate, source_payload)
            improvement = target_distance - candidate_distance
            reported_residual_counter = Counter(str(row.get("shape_id", "")) for row in reported_residual_rows)
            rebuilt_residual_counter = Counter(str(row.get("shape_id", "")) for row in rebuilt_residuals)
            selected_shapes = sorted(selected_counter)

            checks = {
                "stage44_classification_promotable": event.get("classification") == "strictly_improving_subset_ready_for_local_prototype",
                "stage44_safe_without_runtime": parse_bool(event.get("safe_to_build_local_profile_without_runtime")),
                "stage44_runtime_deferred": parse_bool(event.get("runtime_test_deferred")),
                "stage44_subset_id_consistent": combination.get("subset_id") == subset_id,
                "stage44_combination_passes_all_gates": parse_bool(combination.get("passes_all_subset_gates")),
                "stage44_combination_strictly_improves": parse_bool(combination.get("strict_improvement")),
                "selected_occurrence_count_matches_stage44": len(selected_occurrences) == parse_int(event.get("best_selected_occurrence_count"), -1),
                "selected_shape_ids_match_stage44": selected_shapes == sorted(split_cell(event.get("best_selected_shape_ids"))),
                "all_selected_contexts_isolated": all(parse_int(row.get("shared_cue_noncue_context_archetype_count"), -1) == 0 for row in selected_report_rows),
                "candidate_sha256_matches_stage44_event": candidate_sha == event.get("best_candidate_sha256"),
                "candidate_sha256_matches_stage44_combination": candidate_sha == combination.get("candidate_sha256"),
                "candidate_size_matches_stage44": len(candidate) == parse_int(combination.get("candidate_size"), -1),
                "target_distance_matches_stage44": target_distance == parse_int(event.get("target_distance_to_source"), -1),
                "candidate_distance_matches_stage44": candidate_distance == parse_int(event.get("best_candidate_distance_to_source"), -1),
                "distance_improvement_matches_stage44": improvement == parse_int(event.get("best_distance_improvement"), -1),
                "strict_distance_improvement": improvement > 0,
                "all_selected_shapes_removed": parse_bool(metadata.get("all_selected_shapes_removed")),
                "selected_shape_count_after_zero": parse_int(metadata.get("selected_shape_count_after")) == 0,
                "no_introduced_coarse_shapes": parse_int(metadata.get("introduced_coarse_shape_count")) == 0,
                "no_nonselected_coarse_shapes_removed": parse_int(metadata.get("removed_nonselected_coarse_shape_count")) == 0,
                "all_nonselected_shape_counters_preserved": nonselected_before == nonselected_after,
                "reported_residual_multiset_reproduced": reported_residual_counter == rebuilt_residual_counter,
                "reported_remaining_residual_count_reproduced": len(rebuilt_residuals) == parse_int(event.get("best_remaining_residual_rows"), -1),
                "candidate_header_preserved_from_target": parse_bool(metadata.get("candidate_header_preserved_from_target")),
                "candidate_trailing_preserved_from_target": parse_bool(metadata.get("candidate_trailing_bytes_preserved_from_target")),
                "candidate_header_valid": metadata.get("candidate_header_classification") == "observed_ebd_name_description_header",
                "exact_target_reverse_roundtrip": reverse_payload == target_payload,
                "candidate_not_farther_from_original": candidate_distance <= target_distance,
            }
            for check_name, passed in checks.items():
                validation_rows.append({
                    "profile_id": profile_id,
                    "normalized_path": path,
                    "check_name": check_name,
                    "passed": passed,
                    "review_status": "static_metadata_gate_not_runtime_validation",
                })
            if not all(checks.values()):
                skipped_rows.append({"profile_id": profile_id, "normalized_path": path, "reason": "one_or_more_subset_prototype_validation_gates_failed"})
                continue

            profile_dir = prototype_root / profile_id
            local_relative = PurePosixPath("payload") / PurePosixPath(path)
            candidate_path = profile_dir / Path(local_relative.as_posix())
            atomic_bytes(candidate_path, candidate)
            manifest = {
                "type": "br_quartet_restoration_local_presentation_event_subset_prototype",
                "format_version": 1,
                "tool_version": TOOL_VERSION,
                "profile_id": profile_id,
                "profile_classification": "experimental_bounded_subset_static_candidate",
                "prototype_confidence": "experimental_metadata_gated",
                "runtime_validated": False,
                "censorship_semantics_assigned": False,
                "installed_game_files_modified": False,
                "installable_package_generated": False,
                "source_stage44_subset_id": subset_id,
                "cue_domains": event.get("cue_domains", ""),
                "files": [{
                    "normalized_path": path,
                    "candidate_relative_path": local_relative.as_posix(),
                    "source_archive": source_ref.get("archive", ""),
                    "source_member_path": source_ref.get("path", ""),
                    "target_archive": target_ref.get("archive", ""),
                    "target_member_path": target_ref.get("path", ""),
                    "source_sha256": source_sha,
                    "target_sha256": target_sha,
                    "candidate_sha256": candidate_sha,
                    "source_size": len(source_payload),
                    "target_size": len(target_payload),
                    "candidate_size": len(candidate),
                    "selected_occurrence_count": len(selected_occurrences),
                    "selected_shape_ids": selected_shapes,
                    "remaining_residual_rows": len(rebuilt_residuals),
                    "target_byte_difference_to_source": target_distance,
                    "candidate_byte_difference_to_source": candidate_distance,
                    "distance_improvement": improvement,
                }],
            }
            atomic_json(profile_dir / "PROTOTYPE.json", manifest)

            profile_rows.append({
                "profile_id": profile_id,
                "profile_classification": "experimental_bounded_subset_static_candidate",
                "prototype_confidence": "experimental_metadata_gated",
                "event_count": 1,
                "event_paths": path,
                "subset_id": subset_id,
                "selected_occurrence_count": len(selected_occurrences),
                "selected_shape_count": len(selected_shapes),
                "selected_shape_ids": ";".join(selected_shapes),
                "remaining_residual_rows": len(rebuilt_residuals),
                "cue_domains": event.get("cue_domains", ""),
                "distance_improvement": improvement,
                "local_profile_root": str(profile_dir.relative_to(project_root)) if profile_dir.is_relative_to(project_root) else str(profile_dir),
                "validation_status": "passed",
                "runtime_validated": False,
                "review_status": "separate_experimental_local_subset_profile_not_repacked_not_installed",
            })
            file_rows.append({
                "profile_id": profile_id,
                "normalized_path": path,
                "source_archive": source_ref.get("archive", ""),
                "source_member_path": source_ref.get("path", ""),
                "target_archive": target_ref.get("archive", ""),
                "target_member_path": target_ref.get("path", ""),
                "source_sha256": source_sha,
                "target_sha256": target_sha,
                "candidate_sha256": candidate_sha,
                "source_size": len(source_payload),
                "target_size": len(target_payload),
                "candidate_size": len(candidate),
                "target_byte_difference_to_source": target_distance,
                "candidate_byte_difference_to_source": candidate_distance,
                "distance_improvement": improvement,
                "selected_occurrence_count": len(selected_occurrences),
                "remaining_residual_rows": len(rebuilt_residuals),
                "local_relative_path": local_relative.as_posix(),
                "validation_status": "passed",
                "review_status": "candidate_payload_local_only_runtime_unvalidated",
            })
            for order, (reported, occurrence) in enumerate(zip(selected_report_rows, selected_occurrences)):
                selection_rows.append({
                    "profile_id": profile_id,
                    "normalized_path": path,
                    "subset_id": subset_id,
                    "selection_order": order,
                    "shape_id": occurrence.get("shape_id", ""),
                    "occurrence_index": occurrence.get("occurrence_index", ""),
                    "cue_domains": occurrence.get("cue_domains", ""),
                    "selection_reasons": occurrence.get("selection_reasons", ""),
                    "shared_cue_noncue_context_archetype_count": reported.get("shared_cue_noncue_context_archetype_count", ""),
                    "validation_status": "passed",
                    "review_status": "stage44_best_subset_component_reconstructed_from_current_ebd",
                })
            for residual in rebuilt_residuals:
                residual_rows.append({
                    "profile_id": profile_id,
                    "normalized_path": path,
                    "subset_id": subset_id,
                    "shape_id": residual.get("shape_id", ""),
                    "sequence_tag": residual.get("sequence_tag", ""),
                    "source_atom_count": residual.get("source_atom_count", ""),
                    "target_atom_count": residual.get("target_atom_count", ""),
                    "classification": residual.get("classification", ""),
                    "review_status": "remaining_measured_residual_not_assigned_semantics",
                })

        profile_rows.sort(key=lambda row: str(row.get("profile_id", "")))
        file_rows.sort(key=lambda row: str(row.get("normalized_path", "")))
        selection_rows.sort(key=lambda row: (str(row.get("normalized_path", "")), parse_int(row.get("selection_order"))))
        residual_rows.sort(key=lambda row: (str(row.get("normalized_path", "")), str(row.get("shape_id", ""))))
        validation_rows.sort(key=lambda row: (str(row.get("profile_id", "")), str(row.get("check_name", ""))))
        skipped_rows.sort(key=lambda row: (str(row.get("profile_id", "")), str(row.get("reason", ""))))

        evidence_root = report_root / EVIDENCE_DIR_NAME
        if evidence_root.exists():
            shutil.rmtree(evidence_root)
        evidence_root.mkdir(parents=True, exist_ok=True)
        write_tsv(evidence_root / "PRESENTATION_EVENT_SUBSET_PROFILES.tsv", [
            "profile_id", "profile_classification", "prototype_confidence", "event_count", "event_paths",
            "subset_id", "selected_occurrence_count", "selected_shape_count", "selected_shape_ids",
            "remaining_residual_rows", "cue_domains", "distance_improvement", "local_profile_root",
            "validation_status", "runtime_validated", "review_status",
        ], profile_rows)
        write_tsv(evidence_root / "PRESENTATION_EVENT_SUBSET_FILES.tsv", [
            "profile_id", "normalized_path", "source_archive", "source_member_path", "target_archive",
            "target_member_path", "source_sha256", "target_sha256", "candidate_sha256", "source_size",
            "target_size", "candidate_size", "target_byte_difference_to_source",
            "candidate_byte_difference_to_source", "distance_improvement", "selected_occurrence_count",
            "remaining_residual_rows", "local_relative_path", "validation_status", "review_status",
        ], file_rows)
        write_tsv(evidence_root / "PRESENTATION_EVENT_SUBSET_SELECTED_OCCURRENCES.tsv", [
            "profile_id", "normalized_path", "subset_id", "selection_order", "shape_id",
            "occurrence_index", "cue_domains", "selection_reasons",
            "shared_cue_noncue_context_archetype_count", "validation_status", "review_status",
        ], selection_rows)
        write_tsv(evidence_root / "PRESENTATION_EVENT_SUBSET_RESIDUALS.tsv", [
            "profile_id", "normalized_path", "subset_id", "shape_id", "sequence_tag",
            "source_atom_count", "target_atom_count", "classification", "review_status",
        ], residual_rows)
        write_tsv(evidence_root / "PRESENTATION_EVENT_SUBSET_VALIDATION.tsv", [
            "profile_id", "normalized_path", "check_name", "passed", "review_status",
        ], validation_rows)
        write_tsv(evidence_root / "PRESENTATION_EVENT_SUBSET_BUILD_SKIPPED.tsv", [
            "profile_id", "normalized_path", "reason",
        ], skipped_rows)

        validation_failures = sum(not parse_bool(row.get("passed")) for row in validation_rows)
        summary: dict[str, object] = {
            "type": "br_quartet_restoration_presentation_event_subset_prototype_evidence_summary",
            "format_version": 1,
            "tool_version": TOOL_VERSION,
            "source_stage44_tool_version": stage44_summary.get("tool_version"),
            "status": "separate_stage44_subset_prototypes_built_roundtrip_validated_not_repacked_or_installed",
            "proposed_profile_rows": len(event_rows),
            "promoted_profile_rows": len(profile_rows),
            "prototype_file_rows": len(file_rows),
            "selected_occurrence_rows": len(selection_rows),
            "remaining_residual_rows": len(residual_rows),
            "validation_rows": len(validation_rows),
            "validation_failures": validation_failures,
            "skipped_rows": len(skipped_rows),
            "runtime_testing_deferred": True,
            "local_prototype_root": str(prototype_root.relative_to(project_root)) if prototype_root.is_relative_to(project_root) else str(prototype_root),
            "parameters": {"maximum_event_bytes": maximum_event_bytes},
            "policy": {
                "installed_games_modified": False,
                "candidate_ebd_payloads_written_only_under_local_workspace": True,
                "candidate_ebd_payloads_exported_in_report": False,
                "pak_repacked": False,
                "core_profile_manifest_generated": False,
                "activation_or_rollback_invoked": False,
                "runtime_validation_inferred": False,
                "censorship_classification_inferred": False,
                "remaining_residuals_discarded": False,
                "dialogue_or_localized_text_exported": False,
                "legacy_dlc_in_scope": False,
                "translation_or_core_files_modified": False,
            },
            "next_action": (
                "Upload this metadata report. Prepare one separate checksum-gated PACK11 repack test only for each "
                "profile reported as passed. Keep every profile inactive and runtime-unvalidated; retain any skipped "
                "event in the static backlog without weakening its gates."
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
    workspace_root = Path(args.workspace_root).expanduser().resolve() if args.workspace_root else project_root / ".local/build/quartet_restoration"
    report_root = Path(args.report_root).expanduser().resolve() if args.report_root else project_root / ".local/reports/quartet_restoration"
    if not project_root.is_dir():
        raise SubsetPrototypeError(f"project root does not exist: {project_root}")
    output, summary = build_subset_prototypes(
        project_root=project_root,
        workspace_root=workspace_root,
        report_root=report_root,
        maximum_event_bytes=args.maximum_event_bytes,
    )
    print(f"Stage-44 promotable events: {summary['proposed_profile_rows']}")
    print(f"Separate local subset profiles built: {summary['promoted_profile_rows']}")
    print(f"Candidate EBD files: {summary['prototype_file_rows']}")
    print(f"Validation failures: {summary['validation_failures']}")
    print("Runtime testing deferred: true")
    print(f"Report: {output}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SubsetPrototypeError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
