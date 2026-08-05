#!/usr/bin/env python3
"""Refresh and analyze the remaining cue-positive EBD restoration backlog.

This metadata-only stage starts from the current fourteen-profile registry after
stage 62.  It excludes already-owned event paths, literal-dash FE scenes moved
to the legacy_dlc_or_removed_content queue, and the two previously closed
non-improving leads (fo07_090 and fe13_050).  For every remaining cue-positive
backlog event with eligible stage-23 residual occurrences it performs the same
bounded in-memory inverse-subset validation used by stage 44, but broadens the
search to medium-priority residual evidence.  No EBD, PAK, manifest, activation
or installed-game write is produced.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import itertools
import json
import os
import shutil
import subprocess
import struct
import sys
import tempfile
from collections import Counter, defaultdict
from pathlib import Path, PurePosixPath
from typing import Any, Iterable, Mapping, Sequence

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import collect_presentation_event_subset_search_evidence as subset  # noqa: E402

WORKSTREAM_ID = "quartet_restoration"
TOOL_VERSION = "0.0.72"
REPORT_NAME = "BR_quartet_restoration_remaining_cue_positive_backlog_evidence.tar.zst"
EVIDENCE_DIR_NAME = "remaining_cue_positive_backlog_evidence"

NEW_FE13_PROFILE_ID = "candidate_fe13_090_complete_residual_inverse_9a57d11730c0"
OLD_FE13_PROFILE_ID = "candidate_unselected_cue_residual_fe13_090_8330c2a15d46"
EXPECTED_PROFILE_ROWS = 14
EXPECTED_PACK11_ROWS = 12
EXPECTED_PACK10_ROWS = 2

ALLOWED_BACKLOG_CLASSES = {
    "cue_linked_residual_needs_static_reconstruction",
    "isolated_cue_inverse_splice_candidate",
    "residual_event_evidence_only",
    "static_composite_candidate_ready_for_local_profile",
}
ALLOWED_PRIORITIES = {"critical", "high", "medium"}
BROAD_MIGRATION_CLASSES = {
    "broad_schema_migration_candidate",
    "recurrent_schema_delta_candidate",
}

REPORT_SPECS = {
    "core": (
        "core_profile_manifest_evidence",
        "BR_quartet_restoration_core_profile_manifest_evidence.tar.zst",
    ),
    "backlog": (
        "presentation_event_backlog_evidence",
        "BR_quartet_restoration_presentation_event_backlog_evidence.tar.zst",
    ),
    "context": (
        "event_delta_context_evidence",
        "BR_quartet_restoration_event_delta_context_evidence.tar.zst",
    ),
    "migration": (
        "event_tag_migration_evidence",
        "BR_quartet_restoration_event_tag_migration_evidence.tar.zst",
    ),
    "anchor": (
        "registered_profile_anchor_subset_evidence",
        "BR_quartet_restoration_registered_profile_anchor_subset_evidence.tar.zst",
    ),
    "complex": (
        "complex_repeated_shape_subset_evidence",
        "BR_quartet_restoration_complex_repeated_shape_subset_evidence.tar.zst",
    ),
    "placeholder": (
        "fe01_message_placeholder_evidence",
        "BR_quartet_restoration_fe01_message_placeholder_evidence.tar.zst",
    ),
}


class RemainingCueBacklogError(RuntimeError):
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
    return subset.normalize_event_member(path)


def event_id(path: str) -> str:
    return subset.event_id(path)


def safe_member_name(raw: str) -> str:
    path = PurePosixPath(raw)
    if path.is_absolute() or not path.parts or ".." in path.parts:
        raise RemainingCueBacklogError(f"unsafe report archive member: {raw}")
    return path.as_posix()


def read_tsv(path: Path, *, required: bool = True) -> list[dict[str, str]]:
    if not path.is_file():
        if required:
            raise RemainingCueBacklogError(f"missing prerequisite table: {path}")
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
        raise RemainingCueBacklogError(f"missing prerequisite JSON: {path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RemainingCueBacklogError(f"invalid JSON {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise RemainingCueBacklogError(f"expected JSON object: {path}")
    return value


def extract_archive(archive: Path, destination: Path) -> Path:
    if not archive.is_file():
        raise RemainingCueBacklogError(f"missing prerequisite report archive: {archive}")
    listed = subprocess.run(
        ["tar", "--zstd", "-tf", str(archive)],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if listed.returncode != 0:
        raise RemainingCueBacklogError(f"cannot list {archive}: {listed.stderr.strip()}")
    roots: set[str] = set()
    for raw in listed.stdout.splitlines():
        if raw.strip():
            roots.add(PurePosixPath(safe_member_name(raw.strip())).parts[0])
    if len(roots) != 1:
        raise RemainingCueBacklogError(f"expected one report root in {archive}, found {sorted(roots)}")
    destination.mkdir(parents=True, exist_ok=True)
    completed = subprocess.run(
        ["tar", "--zstd", "-xf", str(archive), "-C", str(destination)],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if completed.returncode != 0:
        raise RemainingCueBacklogError(f"cannot extract {archive}: {completed.stderr.strip()}")
    return destination / next(iter(roots))


def locate_report_root(report_root: Path, key: str, temporary: Path) -> Path:
    directory_name, archive_name = REPORT_SPECS[key]
    direct = report_root / directory_name
    if direct.is_dir():
        return direct
    return extract_archive(report_root / archive_name, temporary / key)


def make_report_archive(source_dir: Path, output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(output.name + ".tmp")
    if temporary.exists():
        temporary.unlink()
    completed = subprocess.run(
        ["tar", "--zstd", "-cf", str(temporary), "-C", str(source_dir.parent), source_dir.name],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if completed.returncode != 0:
        raise RemainingCueBacklogError(f"cannot create report archive: {completed.stderr.strip()}")
    os.replace(temporary, output)


def validate_core_report(root: Path) -> dict[str, Any]:
    summary = load_json(root / "SUMMARY.json")
    if summary.get("type") != "br_quartet_restoration_core_profile_manifest_evidence_summary":
        raise RemainingCueBacklogError("core report has an unexpected summary type")
    if summary.get("tool_version") != "0.0.71":
        raise RemainingCueBacklogError(
            f"core report tool version is {summary.get('tool_version')!r}, expected '0.0.71'"
        )
    if summary.get("status") != "all_current_local_profiles_registered_runtime_unvalidated":
        raise RemainingCueBacklogError("core report is not in the clean runtime-unvalidated state")
    if parse_int(summary.get("profile_rows"), -1) != EXPECTED_PROFILE_ROWS:
        raise RemainingCueBacklogError("core report must contain 14 profiles")
    if parse_int(summary.get("pack11_profile_rows"), -1) != EXPECTED_PACK11_ROWS:
        raise RemainingCueBacklogError("core report must contain 12 PACK11 profiles")
    if parse_int(summary.get("pack10_01_profile_rows"), -1) != EXPECTED_PACK10_ROWS:
        raise RemainingCueBacklogError("core report must contain 2 PACK10_01 profiles")
    if parse_int(summary.get("runtime_validated_profile_rows"), -1) != 0:
        raise RemainingCueBacklogError("core report contains a runtime-validated profile")
    if "rejected_manifests" in summary and parse_int(summary.get("rejected_manifests"), -1) != 0:
        raise RemainingCueBacklogError("core report contains rejected manifests")

    rows = read_tsv(root / "CORE_PROFILE_MANIFESTS.tsv")
    if len(rows) != EXPECTED_PROFILE_ROWS:
        raise RemainingCueBacklogError("core manifest table must contain exactly 14 rows")
    profile_ids = [str(row.get("profile_id", "")) for row in rows]
    if len(profile_ids) != len(set(profile_ids)):
        raise RemainingCueBacklogError("core manifest table contains duplicate profile IDs")
    if NEW_FE13_PROFILE_ID not in profile_ids:
        raise RemainingCueBacklogError("core manifest table is missing the complete fe13_090 profile")
    if OLD_FE13_PROFILE_ID in profile_ids:
        raise RemainingCueBacklogError("core manifest table still contains the superseded fe13_090 profile")
    for row in rows:
        if str(row.get("validation_status", "")) != "passed":
            raise RemainingCueBacklogError(f"core profile did not pass validation: {row.get('profile_id')}")
        if parse_bool(row.get("runtime_validated")):
            raise RemainingCueBacklogError(f"core profile is runtime-validated unexpectedly: {row.get('profile_id')}")
    return summary


def load_registry_event_owners(project_root: Path) -> tuple[dict[str, list[str]], list[dict[str, Any]]]:
    registry_root = project_root / ".local/build/quartet_restoration/core_profiles/generated"
    if not registry_root.is_dir():
        raise RemainingCueBacklogError(f"missing generated registry: {registry_root}")
    manifests: list[dict[str, Any]] = []
    owners: defaultdict[str, list[str]] = defaultdict(list)
    target_counts: Counter[str] = Counter()
    for path in sorted(registry_root.glob("*.json")):
        data = load_json(path)
        if data.get("workstream_id") != WORKSTREAM_ID:
            continue
        profile_id = str(data.get("profile_id", ""))
        if not profile_id:
            raise RemainingCueBacklogError(f"registry manifest missing profile_id: {path}")
        if parse_bool(data.get("runtime_validated")):
            raise RemainingCueBacklogError(f"registry contains runtime-validated profile: {profile_id}")
        manifests.append(data)
        target = str(data.get("target_relative_path", ""))
        target_counts[target] += 1
        for member in data.get("changed_members", []) or []:
            normalized = normalize_event_member(member)
            if normalized.casefold().endswith(".ebd"):
                owners[normalized].append(profile_id)
    if len(manifests) != EXPECTED_PROFILE_ROWS:
        raise RemainingCueBacklogError(f"generated registry contains {len(manifests)} profiles, expected 14")
    profile_ids = [str(row.get("profile_id", "")) for row in manifests]
    if NEW_FE13_PROFILE_ID not in profile_ids or OLD_FE13_PROFILE_ID in profile_ids:
        raise RemainingCueBacklogError("generated registry does not reflect the stage-62 fe13_090 replacement")
    if target_counts["Data/PACK11.PAK"] != EXPECTED_PACK11_ROWS or target_counts["Data/PACK10_01.PAK"] != EXPECTED_PACK10_ROWS:
        raise RemainingCueBacklogError("generated registry target split is not 12 PACK11 + 2 PACK10_01")
    return dict(owners), manifests


def validate_source_reports(roots: Mapping[str, Path]) -> dict[str, dict[str, Any]]:
    expected = {
        "backlog": ("br_quartet_restoration_presentation_event_backlog_evidence_summary", "0.0.46"),
        "context": ("br_quartet_restoration_event_delta_context_evidence_summary", "0.0.27"),
        "migration": ("br_quartet_restoration_event_tag_migration_evidence_summary", "0.0.24"),
        "anchor": ("br_quartet_restoration_registered_profile_anchor_subset_evidence_summary", "0.0.56"),
        "complex": ("br_quartet_restoration_complex_repeated_shape_subset_evidence_summary", "0.0.58"),
        "placeholder": ("br_quartet_restoration_fe01_message_placeholder_evidence_summary", "0.0.65"),
    }
    summaries: dict[str, dict[str, Any]] = {}
    for key, (summary_type, version) in expected.items():
        summary = load_json(roots[key] / "SUMMARY.json")
        if summary.get("type") != summary_type or summary.get("tool_version") != version:
            raise RemainingCueBacklogError(f"{key} report is not the expected {version} report")
        summaries[key] = summary
    if parse_int(summaries["anchor"].get("promotable_event_rows"), -1) != 0:
        raise RemainingCueBacklogError("stage-49 anchor report outcome changed")
    if parse_int(summaries["complex"].get("promotable_event_rows"), -1) != 0:
        raise RemainingCueBacklogError("stage-50 complex-shape report outcome changed")
    return summaries


def legacy_dash_event_paths(placeholder_root: Path) -> set[str]:
    paths: set[str] = set()
    for row in read_tsv(placeholder_root / "FE_EVENT_MESSAGE_PAYLOAD_AUDIT.tsv"):
        if not parse_bool(row.get("all_target_languages_exact_dash_placeholders")):
            continue
        identifier = str(row.get("event_id", ""))
        family = str(row.get("family", ""))
        if identifier and family:
            paths.add(f"event/event_jp/{family}/event_{identifier}.ebd")
    return paths


def closed_nonimproving_paths(anchor_root: Path, complex_root: Path) -> set[str]:
    closed: set[str] = set()
    for row in read_tsv(anchor_root / "REGISTERED_PROFILE_ANCHOR_SUBSET_EVENTS.tsv"):
        if not parse_bool(row.get("safe_to_build_separate_local_profile")):
            closed.add(normalize_event_member(row.get("normalized_path", "")))
    for row in read_tsv(complex_root / "COMPLEX_REPEATED_SHAPE_EVENTS.tsv"):
        if not parse_bool(row.get("safe_to_build_separate_local_profile")):
            closed.add(normalize_event_member(row.get("normalized_path", "")))
    closed.discard("")
    return closed


def collect(
    *,
    project_root: Path,
    workspace_root: Path,
    report_root: Path,
    maximum_event_bytes: int = 2 * 1024 * 1024,
    maximum_subset_occurrences: int = 12,
    maximum_combinations_per_event: int = 4095,
    top_combinations_per_event: int = 32,
) -> tuple[Path, dict[str, Any]]:
    project_root = project_root.expanduser().resolve()
    workspace_root = workspace_root.expanduser().resolve()
    report_root = report_root.expanduser().resolve()
    if not 1 <= maximum_subset_occurrences <= 16:
        raise RemainingCueBacklogError("maximum_subset_occurrences must be in the range 1..16")
    if maximum_combinations_per_event < 1 or top_combinations_per_event < 1:
        raise RemainingCueBacklogError("combination limits must be positive")

    br = subset.load_restoration_tool(project_root)
    with tempfile.TemporaryDirectory(prefix="br-remaining-cue-backlog-") as temporary_name:
        temporary = Path(temporary_name)
        roots = {key: locate_report_root(report_root, key, temporary) for key in REPORT_SPECS}
        core_summary = validate_core_report(roots["core"])
        summaries = validate_source_reports(roots)
        registry_owners, registry_manifests = load_registry_event_owners(project_root)
        legacy_paths = legacy_dash_event_paths(roots["placeholder"])
        closed_paths = closed_nonimproving_paths(roots["anchor"], roots["complex"])

        backlog_rows = read_tsv(roots["backlog"] / "EVENT_CANDIDATE_BACKLOG.tsv")
        candidate_backlog: dict[str, dict[str, str]] = {}
        exclusion_rows: list[dict[str, object]] = []
        for row in backlog_rows:
            path = normalize_event_member(row.get("normalized_path", ""))
            if not path:
                continue
            reason = ""
            if path in registry_owners:
                reason = "already_owned_by_current_registry"
            elif path in legacy_paths:
                reason = "legacy_dlc_or_removed_content_literal_dash_scene"
            elif path in closed_paths:
                reason = "previous_occurrence_aware_audit_closed_without_strict_improvement"
            elif row.get("classification") not in ALLOWED_BACKLOG_CLASSES:
                reason = "backlog_class_not_supported_for_binary_subset_search"
            elif row.get("review_priority") not in ALLOWED_PRIORITIES:
                reason = "priority_below_medium"
            elif not split_cell(row.get("cue_domains")):
                reason = "no_presentation_cue_domain"
            if reason:
                exclusion_rows.append({
                    "normalized_path": path,
                    "event_id": event_id(path),
                    "reason": reason,
                    "backlog_classification": row.get("classification", ""),
                    "review_priority": row.get("review_priority", ""),
                    "cue_domains": row.get("cue_domains", ""),
                    "owner_profile_ids": ";".join(sorted(registry_owners.get(path, []))),
                })
                continue
            candidate_backlog[path] = row

        occurrence_rows = read_tsv(roots["context"] / "EVENT_DELTA_CONTEXT_OCCURRENCES.tsv")
        control_by_shape = {
            str(row.get("shape_id", "")): row
            for row in read_tsv(roots["context"] / "EVENT_DELTA_CUE_NONCUE_COMPARISON.tsv")
        }
        broad_shape_ids = {
            br.event_residual_delta_shape_id(row)
            for row in read_tsv(roots["migration"] / "EVENT_TAG_SCHEMA_MIGRATION_CANDIDATES.tsv")
            if row.get("classification") in BROAD_MIGRATION_CLASSES
        }
        occurrences_by_path: defaultdict[str, list[dict[str, str]]] = defaultdict(list)
        occurrence_exclusions: list[dict[str, object]] = []
        for row in occurrence_rows:
            path = normalize_event_member(row.get("normalized_path", ""))
            if path not in candidate_backlog or not parse_bool(row.get("cue_positive_occurrence")):
                continue
            shape_id = str(row.get("shape_id", ""))
            reason = ""
            if shape_id in broad_shape_ids:
                reason = "broad_or_recurrent_schema_shape"
            elif parse_int(control_by_shape.get(shape_id, {}).get("shared_cue_noncue_context_archetype_count"), 0) > 0:
                reason = "shared_cue_noncue_exact_context"
            if reason:
                occurrence_exclusions.append({
                    "normalized_path": path,
                    "shape_id": shape_id,
                    "occurrence_index": row.get("occurrence_index", ""),
                    "reason": reason,
                })
            else:
                occurrences_by_path[path].append(row)
        for rows in occurrences_by_path.values():
            rows.sort(key=lambda row: (str(row.get("shape_id", "")), parse_int(row.get("occurrence_index"), -1)))

        differences = br.load_report_jsons(report_root, "differences")
        event_report = next(
            (row for row in differences if str(row.get("source_archive_group", "")) == "br1_events"),
            None,
        )
        if event_report is None:
            raise RemainingCueBacklogError("missing br1_events difference report")
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
            eligible = occurrences_by_path.get(path, [])
            if not eligible:
                skipped_rows.append({
                    "normalized_path": path,
                    "event_id": event_id(path),
                    "reason": "no_eligible_cue_positive_nonmigration_nonshared_occurrences",
                    "eligible_occurrence_count": 0,
                    "possible_combination_count": 0,
                })
                continue
            if len(eligible) > maximum_subset_occurrences:
                skipped_rows.append({
                    "normalized_path": path,
                    "event_id": event_id(path),
                    "reason": "maximum_subset_occurrences_exceeded",
                    "eligible_occurrence_count": len(eligible),
                    "possible_combination_count": (1 << len(eligible)) - 1,
                })
                continue
            possible = (1 << len(eligible)) - 1
            if possible > maximum_combinations_per_event:
                skipped_rows.append({
                    "normalized_path": path,
                    "event_id": event_id(path),
                    "reason": "maximum_combinations_per_event_exceeded",
                    "eligible_occurrence_count": len(eligible),
                    "possible_combination_count": possible,
                })
                continue
            entry = entry_by_path.get(path)
            if entry is None:
                skipped_rows.append({
                    "normalized_path": path,
                    "event_id": event_id(path),
                    "reason": "difference_entry_missing",
                    "eligible_occurrence_count": len(eligible),
                    "possible_combination_count": possible,
                })
                continue
            source_ref = entry.get("source") or {}
            target_ref = entry.get("target") or {}
            source_path = br.inventory_workspace_file(
                workspace_root,
                "source",
                "br1_events",
                str(source_ref.get("archive", "")),
                str(source_ref.get("path", "")),
            )
            target_path = br.inventory_workspace_file(
                workspace_root,
                "target",
                "br1_events",
                str(target_ref.get("archive", "")),
                str(target_ref.get("path", "")),
            )
            if not source_path.is_file() or not target_path.is_file():
                skipped_rows.append({
                    "normalized_path": path,
                    "event_id": event_id(path),
                    "reason": "workspace_event_payload_missing",
                    "eligible_occurrence_count": len(eligible),
                    "possible_combination_count": possible,
                })
                continue
            if source_path.stat().st_size > maximum_event_bytes or target_path.stat().st_size > maximum_event_bytes:
                skipped_rows.append({
                    "normalized_path": path,
                    "event_id": event_id(path),
                    "reason": "maximum_event_bytes_exceeded",
                    "eligible_occurrence_count": len(eligible),
                    "possible_combination_count": possible,
                })
                continue
            source_payload = source_path.read_bytes()
            target_payload = target_path.read_bytes()
            if source_ref.get("sha256") and hashlib.sha256(source_payload).hexdigest() != str(source_ref.get("sha256")):
                skipped_rows.append({
                    "normalized_path": path,
                    "event_id": event_id(path),
                    "reason": "source_payload_sha256_mismatch",
                    "eligible_occurrence_count": len(eligible),
                    "possible_combination_count": possible,
                })
                continue
            if target_ref.get("sha256") and hashlib.sha256(target_payload).hexdigest() != str(target_ref.get("sha256")):
                skipped_rows.append({
                    "normalized_path": path,
                    "event_id": event_id(path),
                    "reason": "target_payload_sha256_mismatch",
                    "eligible_occurrence_count": len(eligible),
                    "possible_combination_count": possible,
                })
                continue

            evaluated: list[tuple[dict[str, Any], tuple[int, ...], list[dict[str, Any]]]] = []
            construction_failures = 0
            for subset_size in range(1, len(eligible) + 1):
                for indices in itertools.combinations(range(len(eligible)), subset_size):
                    chosen = [eligible[index] for index in indices]
                    try:
                        result, residuals = subset.evaluate_combination(
                            br=br,
                            source_payload=source_payload,
                            target_payload=target_payload,
                            occurrences=chosen,
                            control_by_shape=control_by_shape,
                        )
                    except (subset.SubsetSearchError, br.RestorationError, OSError, ValueError, struct.error):
                        construction_failures += 1
                        continue
                    if result.get("status") == "candidate_failed":
                        construction_failures += 1
                        continue
                    evaluated.append((result, indices, residuals))

            ranked = sorted(
                evaluated,
                key=lambda item: (
                    not bool(item[0].get("passes")),
                    not bool(item[0].get("exact_original")),
                    not bool(item[0].get("strict_improvement")),
                    -parse_int(item[0].get("distance_improvement")),
                    -parse_int(item[0].get("selected_occurrence_count")),
                    parse_int(item[0].get("remaining_residual_rows")),
                    str(item[0].get("candidate_sha256", "")),
                ),
            )
            best = ranked[0] if ranked else None
            promotable = bool(best and best[0].get("passes") and best[0].get("strict_improvement"))
            best_id = ""
            if best:
                best_id = hashlib.sha256(
                    (
                        path
                        + "|"
                        + ";".join(str(index) for index in best[1])
                        + "|"
                        + str(best[0].get("candidate_sha256", ""))
                    ).encode("utf-8")
                ).hexdigest()[:16]
            classification = (
                "remaining_cue_subset_ready_for_local_prototype"
                if promotable
                else "remaining_cue_subset_structurally_valid_without_strict_improvement"
                if best and best[0].get("passes")
                else "remaining_cue_subset_no_structurally_valid_candidate"
            )
            event_rows.append({
                "normalized_path": path,
                "event_id": event_id(path),
                "cue_domains": backlog.get("cue_domains", ""),
                "backlog_classification": backlog.get("classification", ""),
                "review_priority": backlog.get("review_priority", ""),
                "eligible_occurrence_count": len(eligible),
                "combination_count_tested": len(evaluated),
                "candidate_construction_failures": construction_failures,
                "passing_combination_count": sum(bool(item[0].get("passes")) for item in evaluated),
                "strictly_improving_combination_count": sum(
                    bool(item[0].get("passes") and item[0].get("strict_improvement")) for item in evaluated
                ),
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
                    "build_one_separate_checksum_gated_local_profile"
                    if promotable
                    else "retain_as_static_context_evidence_and_continue_backlog"
                ),
            })

            for rank, (result, indices, _) in enumerate(ranked[:top_combinations_per_event], start=1):
                combination_id = hashlib.sha256(
                    (
                        path
                        + "|"
                        + ";".join(str(index) for index in indices)
                        + "|"
                        + str(result.get("candidate_sha256", ""))
                    ).encode("utf-8")
                ).hexdigest()[:16]
                combination_rows.append({
                    "normalized_path": path,
                    "subset_rank": rank,
                    "subset_id": combination_id,
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
                    "passes_structural_gates": result.get("passes_structural", False),
                    "strict_improvement": result.get("strict_improvement", False),
                    "exact_original": result.get("exact_original", False),
                    "passes_all_subset_gates": result.get("passes", False),
                    "review_status": "bounded_in_memory_evidence_not_runtime_or_censorship_validation",
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
                        "review_status": "best_subset_component_not_written_as_payload",
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
                        "review_status": "remaining_residual_semantics_unassigned",
                    })

        event_rows.sort(
            key=lambda row: (
                not parse_bool(row.get("safe_to_build_local_profile_without_runtime")),
                {"critical": 0, "high": 1, "medium": 2}.get(str(row.get("review_priority", "")), 3),
                -parse_int(row.get("best_distance_improvement"), 0),
                str(row.get("normalized_path", "")),
            )
        )
        combination_rows.sort(key=lambda row: (str(row.get("normalized_path", "")), parse_int(row.get("subset_rank"))))
        selected_rows.sort(key=lambda row: (str(row.get("normalized_path", "")), parse_int(row.get("selection_order"))))
        residual_rows.sort(key=lambda row: (str(row.get("normalized_path", "")), str(row.get("shape_id", ""))))
        exclusion_rows.sort(key=lambda row: (str(row.get("normalized_path", "")), str(row.get("reason", ""))))
        occurrence_exclusions.sort(
            key=lambda row: (
                str(row.get("normalized_path", "")),
                str(row.get("shape_id", "")),
                parse_int(row.get("occurrence_index"), -1),
            )
        )
        skipped_rows.sort(key=lambda row: (str(row.get("normalized_path", "")), str(row.get("reason", ""))))

        evidence_root = report_root / EVIDENCE_DIR_NAME
        if evidence_root.exists():
            shutil.rmtree(evidence_root)
        evidence_root.mkdir(parents=True, exist_ok=True)
        write_tsv(evidence_root / "REMAINING_CUE_POSITIVE_BACKLOG_EVENTS.tsv", [
            "normalized_path",
            "event_id",
            "cue_domains",
            "backlog_classification",
            "review_priority",
            "eligible_occurrence_count",
            "combination_count_tested",
            "candidate_construction_failures",
            "passing_combination_count",
            "strictly_improving_combination_count",
            "best_subset_id",
            "best_selected_occurrence_count",
            "best_selected_shape_ids",
            "target_distance_to_source",
            "best_candidate_distance_to_source",
            "best_distance_improvement",
            "best_candidate_sha256",
            "best_remaining_residual_rows",
            "classification",
            "safe_to_build_local_profile_without_runtime",
            "runtime_test_deferred",
            "next_gate",
        ], event_rows)
        write_tsv(evidence_root / "REMAINING_CUE_POSITIVE_BACKLOG_COMBINATIONS.tsv", [
            "normalized_path",
            "subset_rank",
            "subset_id",
            "selected_occurrence_indices",
            "selected_occurrence_count",
            "selected_shape_count",
            "selected_shape_ids",
            "candidate_sha256",
            "candidate_size",
            "target_distance_to_source",
            "candidate_distance_to_source",
            "distance_improvement",
            "remaining_residual_rows",
            "remaining_residual_shape_ids",
            "passes_structural_gates",
            "strict_improvement",
            "exact_original",
            "passes_all_subset_gates",
            "review_status",
        ], combination_rows)
        write_tsv(evidence_root / "REMAINING_CUE_POSITIVE_BACKLOG_SELECTED_OCCURRENCES.tsv", [
            "normalized_path",
            "best_subset_id",
            "selection_order",
            "eligible_occurrence_index",
            "shape_id",
            "occurrence_index",
            "cue_domains",
            "selection_reasons",
            "review_status",
        ], selected_rows)
        write_tsv(evidence_root / "REMAINING_CUE_POSITIVE_BACKLOG_RESIDUALS.tsv", [
            "normalized_path",
            "best_subset_id",
            "shape_id",
            "sequence_tag",
            "source_atom_count",
            "target_atom_count",
            "classification",
            "review_status",
        ], residual_rows)
        write_tsv(evidence_root / "REMAINING_CUE_POSITIVE_BACKLOG_EVENT_EXCLUSIONS.tsv", [
            "normalized_path",
            "event_id",
            "reason",
            "backlog_classification",
            "review_priority",
            "cue_domains",
            "owner_profile_ids",
        ], exclusion_rows)
        write_tsv(evidence_root / "REMAINING_CUE_POSITIVE_BACKLOG_OCCURRENCE_EXCLUSIONS.tsv", [
            "normalized_path",
            "shape_id",
            "occurrence_index",
            "reason",
        ], occurrence_exclusions)
        write_tsv(evidence_root / "REMAINING_CUE_POSITIVE_BACKLOG_SKIPPED.tsv", [
            "normalized_path",
            "event_id",
            "reason",
            "eligible_occurrence_count",
            "possible_combination_count",
        ], skipped_rows)

        promoted = [row for row in event_rows if parse_bool(row.get("safe_to_build_local_profile_without_runtime"))]
        summary: dict[str, Any] = {
            "type": "br_quartet_restoration_remaining_cue_positive_backlog_evidence_summary",
            "format_version": 1,
            "tool_version": TOOL_VERSION,
            "source_core_tool_version": core_summary.get("tool_version"),
            "source_stage40_tool_version": summaries["backlog"].get("tool_version"),
            "source_stage23_tool_version": summaries["context"].get("tool_version"),
            "source_stage24_tool_version": summaries["migration"].get("tool_version"),
            "source_stage49_tool_version": summaries["anchor"].get("tool_version"),
            "source_stage50_tool_version": summaries["complex"].get("tool_version"),
            "source_stage57_tool_version": summaries["placeholder"].get("tool_version"),
            "status": "remaining_cue_positive_backlog_subset_search_complete_no_payload_written_runtime_deferred",
            "registry_profile_rows": len(registry_manifests),
            "registry_owned_event_rows": len(registry_owners),
            "legacy_dash_event_rows_excluded": len(legacy_paths),
            "previous_nonimproving_event_rows_excluded": len(closed_paths),
            "candidate_backlog_rows": len(candidate_backlog),
            "analyzed_event_rows": len(event_rows),
            "promotable_event_rows": len(promoted),
            "reported_combination_rows": len(combination_rows),
            "selected_occurrence_rows": len(selected_rows),
            "remaining_residual_rows": len(residual_rows),
            "event_exclusion_rows": len(exclusion_rows),
            "occurrence_exclusion_rows": len(occurrence_exclusions),
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
                "pak_repack_performed": False,
                "core_registry_modified": False,
                "activation_or_rollback_invoked": False,
                "runtime_validation_inferred": False,
                "censorship_classification_inferred": False,
                "binary_field_semantics_inferred": False,
                "legacy_dlc_or_removed_content_excluded": True,
                "current_registry_event_paths_excluded": True,
                "previous_zero_improvement_event_paths_excluded": True,
                "broad_or_recurrent_schema_shapes_selected": False,
                "shared_cue_noncue_context_selected": False,
                "strict_original_distance_improvement_required_for_promotion": True,
                "exact_target_reverse_roundtrip_required_for_promotion": True,
                "translation_or_dlc_workstreams_modified": False,
            },
            "next_action": (
                "Upload this metadata report. Build separate local prototypes only for rows marked "
                "remaining_cue_subset_ready_for_local_prototype. If none promote, retain the report as "
                "evidence and continue with the next non-EBD censorship class or debug-event-checker research."
            ),
        }
        (evidence_root / "SUMMARY.json").write_text(
            json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
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
    workspace_root = (
        Path(args.workspace_root).expanduser().resolve()
        if args.workspace_root
        else project_root / ".local/build/quartet_restoration"
    )
    report_root = (
        Path(args.report_root).expanduser().resolve()
        if args.report_root
        else project_root / ".local/reports/quartet_restoration"
    )
    try:
        output, summary = collect(
            project_root=project_root,
            workspace_root=workspace_root,
            report_root=report_root,
            maximum_event_bytes=args.maximum_event_bytes,
            maximum_subset_occurrences=args.maximum_subset_occurrences,
            maximum_combinations_per_event=args.maximum_combinations_per_event,
            top_combinations_per_event=args.top_combinations_per_event,
        )
    except (RemainingCueBacklogError, subset.SubsetSearchError, OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print(f"Remaining cue-positive events analyzed: {summary['analyzed_event_rows']}")
    print(f"Promotable remaining events: {summary['promotable_event_rows']}")
    print(f"Legacy-dash events excluded: {summary['legacy_dash_event_rows_excluded']}")
    print(f"Report: {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
