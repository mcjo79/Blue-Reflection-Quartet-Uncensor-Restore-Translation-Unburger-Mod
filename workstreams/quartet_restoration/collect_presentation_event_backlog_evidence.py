#!/usr/bin/env python3
"""Build a metadata-only backlog of possible presentation-restoration events.

This stage deliberately defers runtime validation.  It consolidates the earlier
scene-cue, delta-context, composite, residual and generic-registry evidence into
one candidate queue so additional local profiles can be built before suitable
scene saves become available.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import re
import shutil
import subprocess
import tarfile
import tempfile
from collections import Counter, defaultdict
from pathlib import Path, PurePosixPath
from typing import Any, Iterable, Mapping, Sequence

WORKSTREAM_ID = "quartet_restoration"
TOOL_VERSION = "0.0.46"
REPORT_NAME = "BR_quartet_restoration_presentation_event_backlog_evidence.tar.zst"
EVIDENCE_DIR_NAME = "presentation_event_backlog_evidence"
STAGE39_REPORT_NAME = "BR_quartet_restoration_residual_shared_presentation_runtime_readiness.tar.zst"

REPORT_SPECS = {
    "scene_cues": (
        "event_scene_cue_evidence",
        "BR_quartet_restoration_event_scene_cue_evidence.tar.zst",
    ),
    "delta_context": (
        "event_delta_context_evidence",
        "BR_quartet_restoration_event_delta_context_evidence.tar.zst",
    ),
    "event_prototypes": (
        "event_prototype_evidence",
        "BR_quartet_restoration_event_prototype_evidence.tar.zst",
    ),
    "single_scene": (
        "single_scene_composite_evidence",
        "BR_quartet_restoration_single_scene_composite_evidence.tar.zst",
    ),
    "single_scene_prototypes": (
        "single_scene_event_prototype_evidence",
        "BR_quartet_restoration_single_scene_event_prototype_evidence.tar.zst",
    ),
    "residual_scene": (
        "residual_scene_context_evidence",
        "BR_quartet_restoration_residual_scene_context_evidence.tar.zst",
    ),
    "residual_exact": (
        "residual_exact_context_evidence",
        "BR_quartet_restoration_residual_exact_context_evidence.tar.zst",
    ),
}

EVENT_NAME_RE = re.compile(r"event_([a-z0-9]+)_([0-9]+)(?:_([0-9]+))?\.ebd$", re.I)
PRIORITY_RANK = {"critical": 0, "high": 1, "medium": 2, "low": 3, "parked": 4, "": 5}


class BacklogError(RuntimeError):
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


def unique_join(values: Iterable[str]) -> str:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        if value and value not in seen:
            seen.add(value)
            result.append(value)
    return ";".join(result)


def event_id(path: str) -> str:
    match = EVENT_NAME_RE.search(PurePosixPath(path).name)
    if not match:
        return PurePosixPath(path).stem
    parts = [match.group(1).lower(), match.group(2)]
    if match.group(3) is not None:
        parts.append(match.group(3))
    return "_".join(parts)


def route_family(path: str) -> str:
    match = EVENT_NAME_RE.search(PurePosixPath(path).name)
    return match.group(1).lower() if match else ""


def normalize_event_member(path: str) -> str:
    value = str(path or "").replace("\\", "/").lstrip("./")
    prefixes = (
        "event/b1/event_jp/",
        "data/b1/event/event_jp/",
        "event/event_jp/",
    )
    remainder = value
    for prefix in prefixes:
        if value.casefold().startswith(prefix.casefold()):
            remainder = value[len(prefix):]
            break
    if "/event_jp/" in remainder.casefold():
        # Preserve the actual suffix after the event_jp component.
        parts = remainder.split("/")
        index = next((i for i, part in enumerate(parts) if part.casefold() == "event_jp"), None)
        if index is not None:
            remainder = "/".join(parts[index + 1:])
    return f"event/event_jp/{remainder}" if remainder else value


def safe_member_name(raw: str) -> str:
    path = PurePosixPath(raw)
    if path.is_absolute() or not path.parts or ".." in path.parts:
        raise BacklogError(f"unsafe report archive member: {raw}")
    return path.as_posix()


def read_tsv(path: Path, *, required: bool = True) -> list[dict[str, str]]:
    if not path.is_file():
        if required:
            raise BacklogError(f"missing prerequisite table: {path}")
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
        raise BacklogError(f"missing prerequisite JSON: {path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise BacklogError(f"invalid JSON {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise BacklogError(f"expected JSON object: {path}")
    return value


def extract_archive(archive: Path, destination: Path) -> Path:
    if not archive.is_file():
        raise BacklogError(f"missing prerequisite report archive: {archive}")
    listed = subprocess.run(
        ["tar", "--zstd", "-tf", str(archive)],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if listed.returncode != 0:
        raise BacklogError(f"cannot list {archive}: {listed.stderr.strip()}")
    roots: set[str] = set()
    for raw in listed.stdout.splitlines():
        if not raw.strip():
            continue
        safe = safe_member_name(raw.strip())
        roots.add(PurePosixPath(safe).parts[0])
    if len(roots) != 1:
        raise BacklogError(f"expected one report root in {archive}, found {sorted(roots)}")
    destination.mkdir(parents=True, exist_ok=True)
    completed = subprocess.run(
        ["tar", "--zstd", "-xf", str(archive), "-C", str(destination)],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if completed.returncode != 0:
        raise BacklogError(f"cannot extract {archive}: {completed.stderr.strip()}")
    return destination / next(iter(roots))


def locate_report_root(report_root: Path, key: str, temporary: Path) -> Path:
    directory_name, archive_name = REPORT_SPECS[key]
    direct = report_root / directory_name
    if direct.is_dir():
        return direct
    return extract_archive(report_root / archive_name, temporary / key)


def validate_stage39(report_root: Path, temporary: Path) -> dict[str, Any]:
    direct = report_root / "residual_shared_presentation_runtime_readiness"
    root = direct if direct.is_dir() else extract_archive(report_root / STAGE39_REPORT_NAME, temporary / "stage39")
    summary = load_json(root / "SUMMARY.json")
    if summary.get("type") != "br_quartet_restoration_residual_shared_presentation_runtime_readiness_summary":
        raise BacklogError("stage-39 report has an unexpected summary type")
    if summary.get("tool_version") != "0.0.45":
        raise BacklogError(f"stage-39 report tool version is {summary.get('tool_version')!r}, expected '0.0.45'")
    if summary.get("status") != "profile_metadata_ready_activation_not_authorized_save_required":
        raise BacklogError(f"stage-39 report status is not the parked readiness state: {summary.get('status')!r}")
    if parse_int(summary.get("open_transaction_rows")) != 0:
        raise BacklogError("stage-39 report contains an open transaction")
    if parse_bool(summary.get("activation_authorized")) or parse_bool(summary.get("runtime_validated")):
        raise BacklogError("stage-39 profile must remain inactive and runtime-unvalidated")
    return summary


def load_registry(project_root: Path) -> tuple[list[dict[str, Any]], dict[str, list[str]]]:
    root = project_root / ".local/build/quartet_restoration/core_profiles/generated"
    if not root.is_dir():
        raise BacklogError(f"missing generic core profile registry: {root}")
    manifests: list[dict[str, Any]] = []
    event_owners: defaultdict[str, list[str]] = defaultdict(list)
    for path in sorted(root.glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise BacklogError(f"invalid profile manifest {path}: {exc}") from exc
        if not isinstance(data, dict) or data.get("workstream_id") != WORKSTREAM_ID:
            continue
        if parse_bool(data.get("runtime_validated")):
            raise BacklogError(f"unexpected runtime-validated profile in backlog stage: {data.get('profile_id')}")
        profile_id = str(data.get("profile_id", ""))
        if not profile_id:
            raise BacklogError(f"manifest missing profile_id: {path}")
        data = dict(data)
        data["_manifest_relative_path"] = path.relative_to(project_root).as_posix()
        manifests.append(data)
        for member in data.get("changed_members", []) or []:
            normalized = normalize_event_member(str(member))
            if normalized.casefold().endswith(".ebd"):
                event_owners[normalized].append(profile_id)
    if not manifests:
        raise BacklogError("generic core registry contains no quartet_restoration manifests")
    duplicates = [profile_id for profile_id, count in Counter(str(row.get("profile_id")) for row in manifests).items() if count > 1]
    if duplicates:
        raise BacklogError("duplicate registry profile IDs: " + ", ".join(sorted(duplicates)))
    return manifests, dict(event_owners)


def minimum_priority(*values: str) -> str:
    present = [value for value in values if value]
    return min(present, key=lambda value: PRIORITY_RANK.get(value, 9)) if present else ""


def classify_candidate(row: Mapping[str, Any]) -> tuple[str, str, str, bool]:
    if row.get("existing_profile_ids"):
        return (
            "registered_inactive_profile",
            "parked",
            "already_built_keep_inactive_until_scene_save_exists",
            False,
        )
    composite_class = str(row.get("composite_classification", ""))
    composite_gate = str(row.get("composite_next_gate", ""))
    if composite_gate == "eligible_for_separate_local_single_scene_prototype_review" and composite_class in {
        "exact_original_payload_match_after_composite_inverse",
        "residual_only_known_schema_migrations_after_composite_inverse",
    }:
        return (
            "static_composite_candidate_ready_for_local_profile",
            "critical",
            "build_separate_local_composite_profile_then_checksum_gated_repack",
            True,
        )
    if parse_int(row.get("isolated_cue_splice_count")) > 0 and parse_int(row.get("shared_cue_noncue_context_count")) == 0:
        return (
            "isolated_cue_inverse_splice_candidate",
            minimum_priority(str(row.get("context_priority", "")), str(row.get("cue_priority", ""))) or "high",
            "reconstruct_local_candidate_from_exact_stage23_spans_and_validate_other_shape_counters",
            True,
        )
    cue_priority = str(row.get("cue_priority", ""))
    if cue_priority in {"critical", "high"} and parse_int(row.get("rare_residual_regions")) > 0:
        return (
            "cue_linked_residual_needs_static_reconstruction",
            cue_priority,
            "decode_or_combine_residual_spans_before_any_profile_build",
            False,
        )
    if parse_int(row.get("rare_residual_regions")) > 0 or parse_int(row.get("unknown_residual_shapes")) > 0:
        return (
            "residual_event_evidence_only",
            minimum_priority(cue_priority, str(row.get("residual_priority", ""))) or "medium",
            "retain_in_backlog_until_more exact-context_or_cross-scene_support_exists".replace(" ", "_"),
            False,
        )
    return (
        "cue_only_or_background_event_not_static_candidate",
        cue_priority or "low",
        "do_not_build_from_dialogue_cue_without_binary_residual_support",
        False,
    )


def build_backlog(
    *,
    project_root: Path,
    report_root: Path,
) -> tuple[dict[str, Any], dict[str, list[dict[str, Any]]]]:
    project_root = project_root.expanduser().resolve()
    report_root = report_root.expanduser().resolve()
    with tempfile.TemporaryDirectory(prefix="br-presentation-event-backlog-") as temporary_name:
        temporary = Path(temporary_name)
        stage39 = validate_stage39(report_root, temporary)
        roots = {key: locate_report_root(report_root, key, temporary) for key in REPORT_SPECS}

        manifests, event_owners = load_registry(project_root)

        cue_rows = read_tsv(roots["scene_cues"] / "FOCUSED_PRESENTATION_EVENT_REVIEW.tsv")
        occurrence_rows = read_tsv(roots["delta_context"] / "EVENT_DELTA_CONTEXT_OCCURRENCES.tsv")
        splice_rows = read_tsv(roots["delta_context"] / "IN_MEMORY_EVENT_DELTA_SPLICE_READINESS.tsv")
        control_rows = read_tsv(roots["delta_context"] / "EVENT_DELTA_CUE_NONCUE_COMPARISON.tsv")
        focused_context_rows = read_tsv(roots["delta_context"] / "FOCUSED_EVENT_DELTA_CONTEXT_REVIEW.tsv")
        composite_rows = read_tsv(roots["single_scene"] / "SINGLE_SCENE_COMPOSITE_EVENTS.tsv")
        composite_focus_rows = read_tsv(roots["single_scene"] / "FOCUSED_SINGLE_SCENE_COMPOSITE_REVIEW.tsv")
        residual_focus_rows = read_tsv(roots["residual_scene"] / "FOCUSED_UNRESOLVED_SCENE_REVIEW.tsv")
        residual_detail_rows = read_tsv(roots["residual_scene"] / "UNRESOLVED_SCENE_RESIDUAL_SHAPES.tsv")
        exact_occurrence_rows = read_tsv(roots["residual_exact"] / "RESIDUAL_EXACT_CONTEXT_OCCURRENCES.tsv")
        exact_gate_rows = read_tsv(roots["residual_exact"] / "RESIDUAL_SHAPE_PROMOTION_GATES.tsv")

        # Optional historical prototype tables are useful for coverage accounting,
        # but the current generic registry remains the authoritative coverage source.
        historical_profile_rows: list[dict[str, str]] = []
        for root, candidates in (
            (roots["event_prototypes"], ["EVENT_PROTOTYPE_PROFILES.tsv"]),
            (roots["single_scene_prototypes"], ["SINGLE_SCENE_EVENT_PROTOTYPE_PROFILES.tsv", "SINGLE_SCENE_EVENT_PROFILES.tsv"]),
        ):
            for name in candidates:
                table = read_tsv(root / name, required=False)
                if table:
                    historical_profile_rows.extend(table)
                    break

    events: defaultdict[str, dict[str, Any]] = defaultdict(dict)

    def ensure(path: str) -> dict[str, Any]:
        normalized = normalize_event_member(path)
        item = events[normalized]
        item.setdefault("normalized_path", normalized)
        item.setdefault("event_id", event_id(normalized))
        item.setdefault("route_family", route_family(normalized))
        item.setdefault("cue_domains", set())
        item.setdefault("cue_rule_ids", set())
        item.setdefault("shape_ids", set())
        item.setdefault("evidence_sources", set())
        return item

    for row in cue_rows:
        item = ensure(str(row.get("normalized_path", "")))
        item["evidence_sources"].add("stage21_scene_cue")
        item["cue_domains"].update(split_cell(row.get("cue_domains")))
        item["cue_rule_ids"].update(split_cell(row.get("cue_rule_ids")))
        item["cue_priority"] = minimum_priority(str(item.get("cue_priority", "")), str(row.get("review_priority", "")))
        item["event_message_classification"] = row.get("event_message_classification", "")
        item["rare_residual_regions"] = max(parse_int(item.get("rare_residual_regions")), parse_int(row.get("rare_residual_regions")))
        item["compound_location_and_presentation_cue"] = parse_bool(row.get("compound_location_and_presentation_cue"))

    control_by_shape = {str(row.get("shape_id", "")): row for row in control_rows}
    focus_by_shape = {str(row.get("shape_id", "")): row for row in focused_context_rows}
    for row in occurrence_rows:
        path = str(row.get("normalized_path", ""))
        if not path:
            continue
        item = ensure(path)
        shape_id = str(row.get("shape_id", ""))
        item["evidence_sources"].add("stage23_delta_context")
        item["shape_ids"].add(shape_id)
        item["context_occurrence_count"] = parse_int(item.get("context_occurrence_count")) + 1
        if parse_bool(row.get("cue_positive_occurrence")):
            item["cue_context_occurrence_count"] = parse_int(item.get("cue_context_occurrence_count")) + 1
            item["cue_domains"].update(split_cell(row.get("cue_domains")))
        control = control_by_shape.get(shape_id, {})
        item["shared_cue_noncue_context_count"] = max(
            parse_int(item.get("shared_cue_noncue_context_count")),
            parse_int(control.get("shared_cue_noncue_context_archetype_count")),
        )
        focus = focus_by_shape.get(shape_id, {})
        item["context_priority"] = minimum_priority(str(item.get("context_priority", "")), str(focus.get("review_priority", "")))

    for row in splice_rows:
        path = str(row.get("normalized_path", ""))
        if not path:
            continue
        item = ensure(path)
        item["evidence_sources"].add("stage23_inverse_splice")
        if parse_bool(row.get("cue_positive_occurrence")):
            item["cue_domains"].update(split_cell(row.get("cue_domains")))
            if row.get("in_memory_splice_status") == "selected_shape_removed_without_other_coarse_delta_changes":
                item["isolated_cue_splice_count"] = parse_int(item.get("isolated_cue_splice_count")) + 1
        item["shape_ids"].add(str(row.get("shape_id", "")))

    composite_by_path = {normalize_event_member(str(row.get("normalized_path", ""))): row for row in composite_rows}
    composite_focus_by_path = {normalize_event_member(str(row.get("normalized_path", ""))): row for row in composite_focus_rows}
    for path in set(composite_by_path) | set(composite_focus_by_path):
        item = ensure(path)
        row = composite_by_path.get(path, {})
        focus = composite_focus_by_path.get(path, {})
        item["evidence_sources"].add("stage29_single_scene_composite")
        item["cue_domains"].update(split_cell(row.get("cue_domains", focus.get("cue_domains", ""))))
        item["composite_classification"] = row.get("classification", focus.get("classification", ""))
        item["composite_next_gate"] = focus.get("next_gate", "")
        item["composite_candidate_sha256"] = row.get("candidate_sha256", "")
        item["unknown_residual_shapes"] = parse_int(row.get("unknown_residual_rows", focus.get("unknown_residual_rows", 0)))
        item["residual_priority"] = focus.get("review_priority", row.get("review_priority", ""))

    for row in residual_focus_rows:
        path = str(row.get("normalized_path", ""))
        if not path:
            continue
        item = ensure(path)
        item["evidence_sources"].add("stage34_residual_scene_context")
        item["cue_domains"].update(split_cell(row.get("cue_domains")))
        item["unknown_residual_shapes"] = max(parse_int(item.get("unknown_residual_shapes")), parse_int(row.get("unknown_shape_count")))
        item["residual_priority"] = minimum_priority(str(item.get("residual_priority", "")), str(row.get("review_priority", "")))

    for row in residual_detail_rows:
        path = str(row.get("normalized_path", ""))
        if not path:
            continue
        item = ensure(path)
        item["shape_ids"].add(str(row.get("shape_id", "")))
        item["cue_domains"].update(split_cell(row.get("cue_domains")))

    eligible_exact_shapes = {
        str(row.get("shape_id", ""))
        for row in exact_gate_rows
        if str(row.get("stage36_gate", row.get("stage36_eligibility", row.get("next_gate", "")))) in {
            "eligible_for_stage_36_local_prototype_review",
            "eligible_for_stage36_shared_presentation_prototype",
            "eligible_for_shared_presentation_prototype",
        }
        or parse_bool(row.get("eligible_for_stage36"))
    }
    for row in exact_occurrence_rows:
        path = str(row.get("normalized_path", ""))
        if not path:
            continue
        item = ensure(path)
        shape_id = str(row.get("shape_id", ""))
        item["evidence_sources"].add("stage35_residual_exact_context")
        item["shape_ids"].add(shape_id)
        if shape_id in eligible_exact_shapes:
            item["stage35_eligible_shape_count"] = parse_int(item.get("stage35_eligible_shape_count")) + 1

    backlog_rows: list[dict[str, Any]] = []
    exclusion_rows: list[dict[str, Any]] = []
    for path, item in events.items():
        owners = sorted(set(event_owners.get(path, [])))
        item["existing_profile_ids"] = ";".join(owners)
        classification, priority, next_gate, safe_to_build = classify_candidate(item)
        row = {
            "normalized_path": path,
            "event_id": item["event_id"],
            "route_family": item["route_family"],
            "event_message_classification": item.get("event_message_classification", ""),
            "cue_domains": unique_join(sorted(item["cue_domains"])),
            "cue_rule_ids": unique_join(sorted(item["cue_rule_ids"])),
            "compound_location_and_presentation_cue": bool(item.get("compound_location_and_presentation_cue", False)),
            "rare_residual_regions": parse_int(item.get("rare_residual_regions")),
            "shape_ids": unique_join(sorted(value for value in item["shape_ids"] if value)),
            "shape_count": len({value for value in item["shape_ids"] if value}),
            "context_occurrence_count": parse_int(item.get("context_occurrence_count")),
            "cue_context_occurrence_count": parse_int(item.get("cue_context_occurrence_count")),
            "isolated_cue_splice_count": parse_int(item.get("isolated_cue_splice_count")),
            "shared_cue_noncue_context_count": parse_int(item.get("shared_cue_noncue_context_count")),
            "composite_classification": item.get("composite_classification", ""),
            "composite_candidate_sha256": item.get("composite_candidate_sha256", ""),
            "unknown_residual_shapes": parse_int(item.get("unknown_residual_shapes")),
            "stage35_eligible_shape_count": parse_int(item.get("stage35_eligible_shape_count")),
            "existing_profile_ids": item["existing_profile_ids"],
            "classification": classification,
            "review_priority": priority,
            "safe_to_build_local_profile_without_runtime": safe_to_build,
            "runtime_test_deferred": True,
            "next_gate": next_gate,
            "evidence_sources": unique_join(sorted(item["evidence_sources"])),
        }
        backlog_rows.append(row)
        if not safe_to_build and classification != "registered_inactive_profile":
            exclusion_rows.append({
                "normalized_path": path,
                "event_id": row["event_id"],
                "classification": classification,
                "reason": next_gate,
                "cue_domains": row["cue_domains"],
                "shape_ids": row["shape_ids"],
                "review_priority": priority,
                "review_status": "not_discarded_permanently_but_not_safe_for_automatic_local_profile_build",
            })

    backlog_rows.sort(key=lambda row: (
        0 if row["safe_to_build_local_profile_without_runtime"] else 1,
        PRIORITY_RANK.get(str(row["review_priority"]), 9),
        str(row["route_family"]),
        str(row["event_id"]),
    ))
    exclusion_rows.sort(key=lambda row: (PRIORITY_RANK.get(str(row["review_priority"]), 9), str(row["normalized_path"])))

    buildable = [row for row in backlog_rows if row["safe_to_build_local_profile_without_runtime"]]
    groups: defaultdict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in buildable:
        shape_ids = split_cell(row["shape_ids"])
        if row["classification"] == "static_composite_candidate_ready_for_local_profile":
            groups[("single_scene_composite", str(row["normalized_path"]))].append(row)
        elif len(shape_ids) == 1:
            shape_id = shape_ids[0]
            key_type = "route_shape" if row["route_family"] else "shared_shape"
            groups[(key_type, f"{row['route_family']}:{shape_id}" if row["route_family"] else shape_id)].append(row)
        else:
            groups[("single_scene_multi_shape", str(row["normalized_path"]))].append(row)

    group_rows: list[dict[str, Any]] = []
    for index, ((group_type, group_key), rows) in enumerate(sorted(groups.items()), 1):
        paths = sorted(str(row["normalized_path"]) for row in rows)
        shape_ids = sorted({shape for row in rows for shape in split_cell(row["shape_ids"])})
        digest = hashlib.sha256((group_type + "|" + group_key + "|" + "|".join(paths)).encode()).hexdigest()[:12]
        if group_type == "single_scene_composite":
            proposed_profile = f"candidate_single_scene_{rows[0]['event_id']}_{digest}"
            build_mode = "reproduce_stage29_composite_candidate"
        elif group_type == "route_shape":
            proposed_profile = f"candidate_route_{rows[0]['route_family']}_{digest}"
            build_mode = "reconstruct_all_isolated_cue_occurrences_of_one_route_shape"
        elif group_type == "shared_shape":
            proposed_profile = f"candidate_shared_presentation_{digest}"
            build_mode = "reconstruct_all_cue_only_exact_context_occurrences_of_shared_shape"
        else:
            proposed_profile = f"candidate_single_scene_multishape_{rows[0]['event_id']}_{digest}"
            build_mode = "reconstruct_exact_selected_spans_as_one_scene_profile"
        group_rows.append({
            "group_order": index,
            "proposed_profile_id": proposed_profile,
            "group_type": group_type,
            "route_family": unique_join(sorted({str(row["route_family"]) for row in rows if row["route_family"]})),
            "event_count": len(rows),
            "event_paths": ";".join(paths),
            "shape_count": len(shape_ids),
            "shape_ids": ";".join(shape_ids),
            "cue_domains": unique_join(sorted({domain for row in rows for domain in split_cell(row["cue_domains"])})),
            "build_mode": build_mode,
            "requires_exact_hash_roundtrip": True,
            "requires_other_shape_counter_preservation": True,
            "repack_separately": True,
            "register_inactive": True,
            "runtime_test_deferred": True,
            "review_status": "proposed_static_build_group_not_yet_a_profile_or_censorship_confirmation",
        })

    coverage_rows: list[dict[str, Any]] = []
    for manifest in sorted(manifests, key=lambda row: str(row.get("profile_id", ""))):
        members = [normalize_event_member(str(member)) for member in manifest.get("changed_members", []) or [] if str(member).casefold().endswith(".ebd")]
        coverage_rows.append({
            "profile_id": manifest.get("profile_id", ""),
            "target_relative_path": manifest.get("target_relative_path", ""),
            "changed_event_count": len(members),
            "changed_event_paths": ";".join(members),
            "runtime_validated": bool(manifest.get("runtime_validated", False)),
            "manifest_relative_path": manifest.get("_manifest_relative_path", ""),
            "coverage_status": "registered_inactive" if members else "non_event_profile",
        })

    historical_rows = [{
        "profile_id": row.get("profile_id", ""),
        "shape_id": row.get("shape_id", ""),
        "historical_status": "historical_local_prototype_report_row",
    } for row in historical_profile_rows]

    counts = Counter(str(row["classification"]) for row in backlog_rows)
    summary = {
        "type": "br_quartet_restoration_presentation_event_backlog_evidence_summary",
        "format_version": 1,
        "tool_version": TOOL_VERSION,
        "status": "possible_presentation_events_consolidated_runtime_testing_deferred",
        "source_stage39_tool_version": stage39.get("tool_version"),
        "registry_profile_rows": len(manifests),
        "registered_event_rows": sum(bool(row["existing_profile_ids"]) for row in backlog_rows),
        "candidate_event_rows": len(backlog_rows),
        "safe_static_build_event_rows": len(buildable),
        "proposed_build_group_rows": len(group_rows),
        "evidence_only_or_needs_decode_rows": len(exclusion_rows),
        "classification_counts": dict(sorted(counts.items())),
        "runtime_testing_deferred": True,
        "parameters": {
            "registry_is_authoritative_for_existing_profile_coverage": True,
            "stage29_composite_static_gate_required": True,
            "stage23_isolated_cue_splice_and_no_shared_cue_noncue_context_required": True,
        },
        "policy": {
            "installed_games_modified": False,
            "candidate_ebd_payloads_written": False,
            "pak_repack_performed": False,
            "profile_manifests_modified": False,
            "activation_or_rollback_invoked": False,
            "runtime_validation_inferred": False,
            "dialogue_or_localized_text_exported": False,
            "cue_hit_treated_as_censorship_proof": False,
            "event_tag_semantics_assigned": False,
            "legacy_dlc_in_scope": False,
        },
        "next_action": (
            "Upload this report. Build only the proposed safe static groups as separate local inactive profiles, "
            "with exact reverse round-trip, residual-shape counter and checksum-gated repack validation. Runtime "
            "testing remains deferred until suitable scene saves are obtained."
        ),
    }
    return summary, {
        "EVENT_CANDIDATE_BACKLOG.tsv": backlog_rows,
        "EVENT_CANDIDATE_BUILD_GROUPS.tsv": group_rows,
        "EXISTING_EVENT_PROFILE_COVERAGE.tsv": coverage_rows,
        "EVENT_CANDIDATE_EXCLUSIONS.tsv": exclusion_rows,
        "HISTORICAL_EVENT_PROTOTYPE_ROWS.tsv": historical_rows,
    }


def make_archive(report_dir: Path, archive: Path) -> None:
    archive.parent.mkdir(parents=True, exist_ok=True)
    temporary = archive.with_name(archive.name + f".tmp.{os.getpid()}")
    if temporary.exists():
        temporary.unlink()
    completed = subprocess.run(
        ["tar", "--zstd", "-cf", str(temporary), "-C", str(report_dir.parent), report_dir.name],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if completed.returncode != 0:
        raise BacklogError(f"cannot create report archive: {completed.stderr.strip()}")
    os.replace(temporary, archive)


def write_report(
    *,
    report_root: Path,
    summary: Mapping[str, Any],
    tables: Mapping[str, Sequence[Mapping[str, object]]],
    create_archive: bool = True,
) -> Path | None:
    evidence_root = report_root / EVIDENCE_DIR_NAME
    if evidence_root.exists():
        shutil.rmtree(evidence_root)
    evidence_root.mkdir(parents=True, exist_ok=True)
    field_order = {
        "EVENT_CANDIDATE_BACKLOG.tsv": [
            "normalized_path","event_id","route_family","event_message_classification","cue_domains","cue_rule_ids",
            "compound_location_and_presentation_cue","rare_residual_regions","shape_ids","shape_count",
            "context_occurrence_count","cue_context_occurrence_count","isolated_cue_splice_count",
            "shared_cue_noncue_context_count","composite_classification","composite_candidate_sha256",
            "unknown_residual_shapes","stage35_eligible_shape_count","existing_profile_ids","classification",
            "review_priority","safe_to_build_local_profile_without_runtime","runtime_test_deferred","next_gate",
            "evidence_sources",
        ],
        "EVENT_CANDIDATE_BUILD_GROUPS.tsv": [
            "group_order","proposed_profile_id","group_type","route_family","event_count","event_paths","shape_count",
            "shape_ids","cue_domains","build_mode","requires_exact_hash_roundtrip",
            "requires_other_shape_counter_preservation","repack_separately","register_inactive","runtime_test_deferred",
            "review_status",
        ],
        "EXISTING_EVENT_PROFILE_COVERAGE.tsv": [
            "profile_id","target_relative_path","changed_event_count","changed_event_paths","runtime_validated",
            "manifest_relative_path","coverage_status",
        ],
        "EVENT_CANDIDATE_EXCLUSIONS.tsv": [
            "normalized_path","event_id","classification","reason","cue_domains","shape_ids","review_priority",
            "review_status",
        ],
        "HISTORICAL_EVENT_PROTOTYPE_ROWS.tsv": ["profile_id","shape_id","historical_status"],
    }
    for name, rows in tables.items():
        write_tsv(evidence_root / name, field_order[name], rows)
    (evidence_root / "SUMMARY.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if not create_archive:
        return None
    archive = report_root / REPORT_NAME
    make_archive(evidence_root, archive)
    return archive


def collect(
    *,
    project_root: Path,
    report_root: Path | None = None,
    create_archive: bool = True,
) -> tuple[Path | None, dict[str, Any]]:
    project_root = project_root.expanduser().resolve()
    report_root = (report_root or project_root / ".local/reports/quartet_restoration").expanduser().resolve()
    report_root.mkdir(parents=True, exist_ok=True)
    summary, tables = build_backlog(project_root=project_root, report_root=report_root)
    archive = write_report(report_root=report_root, summary=summary, tables=tables, create_archive=create_archive)
    return archive, summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", required=True)
    parser.add_argument("--report-root")
    parser.add_argument("--no-archive", action="store_true")
    args = parser.parse_args()
    archive, summary = collect(
        project_root=Path(args.project_root),
        report_root=Path(args.report_root) if args.report_root else None,
        create_archive=not args.no_archive,
    )
    print(f"Candidate event rows: {summary['candidate_event_rows']}")
    print(f"Already registered event rows: {summary['registered_event_rows']}")
    print(f"Safe static-build event rows: {summary['safe_static_build_event_rows']}")
    print(f"Proposed build groups: {summary['proposed_build_group_rows']}")
    print("Runtime testing deferred: true")
    if archive is not None:
        print(f"Report: {archive}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except BacklogError as exc:
        print(f"ERROR: {exc}", file=os.sys.stderr)
        raise SystemExit(1)
