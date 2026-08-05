#!/usr/bin/env python3
"""Correlate unresolved single-scene EBD residuals with corpus context and core registry discovery."""

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
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Iterable, Mapping, Sequence

WORKSTREAM_ID = "quartet_restoration"
TOOL_VERSION = "0.0.40"
REPORT_NAME = "BR_quartet_restoration_residual_scene_context_evidence.tar.zst"
EVIDENCE_DIR_NAME = "residual_scene_context_evidence"
EXPECTED_PROFILE_IDS = {
    "repeated_context_69adef108a_c90700a5a2",
    "route_sequence_te02_a570203aa6",
    "single_scene_event_te02_230_0143f9822b",
    "height_fog_shader_original_code",
    "water_shader_swater_original_code",
}
INPUT_REPORTS = {
    "single_scene": "BR_quartet_restoration_single_scene_composite_evidence.tar.zst",
    "context": "BR_quartet_restoration_event_delta_context_evidence.tar.zst",
    "migration": "BR_quartet_restoration_event_tag_migration_evidence.tar.zst",
    "event_prototypes": "BR_quartet_restoration_event_prototype_evidence.tar.zst",
}
ANSI_RE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
ROUTE_RE = re.compile(r"/event_([a-z0-9]+)_\d+\.ebd$")


class ResidualContextError(RuntimeError):
    pass


@dataclass(frozen=True)
class ResidualKey:
    sequence_tag: str
    source_atom_count: int
    target_atom_count: int
    source_tag_values: str
    target_tag_values: str


@dataclass
class CoreListResult:
    returncode: int
    stdout: str
    stderr: str


def parse_bool(value: object) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes", "y"}


def parse_int(value: object, default: int = 0) -> int:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return default


def atom_count(values: str) -> int:
    return 0 if not values else len([part for part in values.split(";") if part])


def route_family(path: str) -> str:
    match = ROUTE_RE.search(path)
    return match.group(1) if match else ""


def unique_join(values: Iterable[str], *, limit: int | None = None) -> str:
    ordered: list[str] = []
    seen: set[str] = set()
    for value in values:
        if not value or value in seen:
            continue
        seen.add(value)
        ordered.append(value)
        if limit is not None and len(ordered) >= limit:
            break
    return ";".join(ordered)


def safe_member_name(raw: str) -> str:
    path = PurePosixPath(raw)
    if path.is_absolute() or not path.parts or ".." in path.parts:
        raise ResidualContextError(f"unsafe report archive member: {raw}")
    return path.as_posix()


def extract_report(archive: Path, destination: Path) -> Path:
    if not archive.is_file():
        raise ResidualContextError(f"missing prerequisite report: {archive}")
    listed = subprocess.run(
        ["tar", "--zstd", "-tf", str(archive)],
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if listed.returncode != 0:
        raise ResidualContextError(
            f"cannot list report archive {archive}: {listed.stderr.strip()}"
        )
    for line in listed.stdout.splitlines():
        if line.strip():
            safe_member_name(line.strip())
    destination.mkdir(parents=True, exist_ok=True)
    extracted = subprocess.run(
        ["tar", "--zstd", "-xf", str(archive), "-C", str(destination)],
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if extracted.returncode != 0:
        raise ResidualContextError(
            f"cannot extract report archive {archive}: {extracted.stderr.strip()}"
        )
    return destination


def find_unique(root: Path, name: str) -> Path:
    matches = [path for path in root.rglob(name) if path.is_file()]
    if len(matches) != 1:
        raise ResidualContextError(
            f"expected exactly one {name} below {root}, found {len(matches)}"
        )
    return matches[0]


def read_tsv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return [dict(row) for row in csv.DictReader(handle, delimiter="\t")]


def write_tsv(path: Path, fieldnames: Sequence[str], rows: Iterable[Mapping[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow({name: row.get(name, "") for name in fieldnames})


def sanitize_output(text: str, project_root: Path) -> str:
    text = ANSI_RE.sub("", text)
    root = str(project_root)
    return text.replace(root, "<PROJECT_ROOT>")


def run_core_list(project_root: Path, command: Path | None = None) -> CoreListResult:
    command = command or (project_root / "Blue_Reflection_Patcher/cmd/br_quartet_profiles.sh")
    if not command.is_file():
        raise ResidualContextError(f"missing core profile registry command: {command}")
    result = subprocess.run(
        ["bash", str(command), "list"],
        cwd=project_root,
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    return CoreListResult(
        returncode=result.returncode,
        stdout=sanitize_output(result.stdout, project_root),
        stderr=sanitize_output(result.stderr, project_root),
    )


def load_manifests(project_root: Path) -> list[dict[str, object]]:
    root = project_root / ".local/build/quartet_restoration/core_profiles"
    if not root.is_dir():
        raise ResidualContextError(f"missing core profile manifest root: {root}")
    manifests: list[dict[str, object]] = []
    for path in sorted(root.rglob("*.json")):
        if path.is_symlink():
            raise ResidualContextError(f"profile manifest must not be a symlink: {path}")
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ResidualContextError(f"invalid profile manifest {path}: {exc}") from exc
        if data.get("workstream_id") != WORKSTREAM_ID:
            continue
        data = dict(data)
        data["_path"] = path.relative_to(project_root).as_posix()
        manifests.append(data)
    return manifests


def validate_core_discovery(
    project_root: Path,
    result: CoreListResult,
    manifests: Sequence[Mapping[str, object]],
) -> list[dict[str, object]]:
    if result.returncode != 0:
        raise ResidualContextError(
            f"core profile list failed with exit {result.returncode}: {result.stderr.strip()}"
        )
    ids = [str(item.get("profile_id", "")) for item in manifests]
    duplicates = sorted(profile_id for profile_id, count in Counter(ids).items() if count > 1)
    if duplicates:
        raise ResidualContextError(f"duplicate profile IDs in local manifests: {', '.join(duplicates)}")
    missing_manifest = sorted(EXPECTED_PROFILE_IDS - set(ids))
    if missing_manifest:
        raise ResidualContextError(
            "current profile manifests are missing: " + ", ".join(missing_manifest)
        )
    combined = result.stdout + "\n" + result.stderr
    rows: list[dict[str, object]] = []
    missing_output: list[str] = []
    for manifest in sorted(manifests, key=lambda item: str(item.get("profile_id", ""))):
        profile_id = str(manifest.get("profile_id", ""))
        mentioned = profile_id in combined
        if profile_id in EXPECTED_PROFILE_IDS and not mentioned:
            missing_output.append(profile_id)
        local_path = project_root / str(manifest.get("local_profile_path", ""))
        rows.append(
            {
                "profile_id": profile_id,
                "target_relative_path": manifest.get("target_relative_path", ""),
                "manifest_relative_path": manifest.get("_path", ""),
                "local_profile_path": manifest.get("local_profile_path", ""),
                "local_profile_exists": local_path.is_file(),
                "runtime_validated": bool(manifest.get("runtime_validated", False)),
                "core_list_mentions_profile": mentioned,
                "validation_status": "passed" if mentioned and local_path.is_file() else "failed",
            }
        )
    if missing_output:
        raise ResidualContextError(
            "core list output did not contain current profile IDs: " + ", ".join(missing_output)
        )
    return rows


def residual_key(row: Mapping[str, str]) -> ResidualKey:
    source = row.get("source_tag_values", "")
    target = row.get("target_tag_values", "")
    return ResidualKey(
        sequence_tag=row.get("sequence_tag", ""),
        source_atom_count=parse_int(row.get("source_atom_count"), atom_count(source)),
        target_atom_count=parse_int(row.get("target_atom_count"), atom_count(target)),
        source_tag_values=source,
        target_tag_values=target,
    )


def classify_shape(
    *,
    promoted_profiles: Sequence[str],
    support_file_count: int,
    same_route_file_count: int,
    other_route_file_count: int,
    route_family_count: int,
    cue_file_count: int,
) -> tuple[str, str, str]:
    if promoted_profiles:
        return (
            "already_covered_by_existing_local_profile",
            "parked",
            "do_not_generate_duplicate_profile; await runtime validation of the existing profile",
        )
    if support_file_count >= 4 and same_route_file_count >= 4 and other_route_file_count == 0:
        return (
            "route_sequence_state_candidate",
            "high",
            "compare route-local context archetypes and isolate a separate route-state splice only if it is not already covered",
        )
    if support_file_count >= 8 and route_family_count >= 4:
        return (
            "corpus_common_or_schema_candidate",
            "low",
            "treat as likely format/schema behavior until a scene-specific context or runtime correlation exists",
        )
    if support_file_count >= 2 and cue_file_count >= 2 and route_family_count <= 2:
        return (
            "shared_presentation_candidate",
            "high",
            "compare the exact context in the paired cue-positive scenes before any splice promotion",
        )
    if support_file_count == 1:
        return (
            "scene_unique_residual_candidate",
            "medium",
            "retain evidence-only; require additional binary context or runtime scene confirmation",
        )
    if support_file_count >= 2:
        return (
            "cross_scene_residual_candidate",
            "medium",
            "inspect cross-scene context archetypes and cue enrichment before interpreting the residual",
        )
    return (
        "insufficient_context_support",
        "low",
        "retain evidence-only because the shape was not selected for detailed context analysis",
    )


def analyze_residuals(
    *,
    single_scene_root: Path,
    context_root: Path,
    migration_root: Path,
    prototype_root: Path,
) -> tuple[list[dict[str, object]], list[dict[str, object]], list[dict[str, object]], list[dict[str, object]]]:
    focused = read_tsv(find_unique(single_scene_root, "FOCUSED_SINGLE_SCENE_COMPOSITE_REVIEW.tsv"))
    events = read_tsv(find_unique(single_scene_root, "SINGLE_SCENE_COMPOSITE_EVENTS.tsv"))
    residuals = read_tsv(find_unique(single_scene_root, "SINGLE_SCENE_COMPOSITE_RESIDUALS.tsv"))
    occurrences = read_tsv(find_unique(context_root, "EVENT_DELTA_CONTEXT_OCCURRENCES.tsv"))
    frequency = read_tsv(find_unique(migration_root, "EVENT_TAG_DELTA_SIGNATURE_FREQUENCY.tsv"))
    prototype_profiles = read_tsv(find_unique(prototype_root, "EVENT_PROTOTYPE_PROFILES.tsv"))

    unresolved_paths = {
        row["normalized_path"]
        for row in focused
        if row.get("classification") == "selected_single_scene_shapes_removed_unknown_residuals_remain"
    }
    if not unresolved_paths:
        raise ResidualContextError("single-scene report contains no unresolved event paths")
    cue_by_path = {row["normalized_path"]: row.get("cue_domains", "") for row in events}

    promoted_by_shape: dict[str, list[str]] = defaultdict(list)
    for row in prototype_profiles:
        promoted_by_shape[row.get("shape_id", "")].append(row.get("profile_id", ""))

    occurrence_by_shape: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in occurrences:
        occurrence_by_shape[row.get("shape_id", "")].append(row)

    frequency_by_key: dict[ResidualKey, dict[str, str]] = {}
    for row in frequency:
        frequency_by_key[residual_key(row)] = row

    deduped: dict[tuple[str, str], dict[str, str]] = {}
    counts_in_event: Counter[tuple[str, str]] = Counter()
    for row in residuals:
        path = row.get("normalized_path", "")
        if path not in unresolved_paths or parse_bool(row.get("known_schema_migration_shape")):
            continue
        key = (path, row.get("shape_id", ""))
        counts_in_event[key] += 1
        deduped.setdefault(key, row)

    detail_rows: list[dict[str, object]] = []
    for (path, shape_id), row in sorted(deduped.items()):
        route = route_family(path)
        shape_occurrences = occurrence_by_shape.get(shape_id, [])
        freq_row = frequency_by_key.get(residual_key(row), {})
        occurrence_paths = sorted({item.get("normalized_path", "") for item in shape_occurrences if item.get("normalized_path")})
        if shape_occurrences:
            support_file_count = len(occurrence_paths)
            support_occurrence_count = len(shape_occurrences)
            route_families = sorted({route_family(item) for item in occurrence_paths if route_family(item)})
            cue_paths = {
                item.get("normalized_path", "")
                for item in shape_occurrences
                if parse_bool(item.get("cue_positive_occurrence"))
            }
            archetypes = {item.get("pair_context_archetype_id", "") for item in shape_occurrences if item.get("pair_context_archetype_id")}
            current_archetypes = {
                item.get("pair_context_archetype_id", "")
                for item in shape_occurrences
                if item.get("normalized_path") == path and item.get("pair_context_archetype_id")
            }
            current_context_files = {
                item.get("normalized_path", "")
                for item in shape_occurrences
                if item.get("pair_context_archetype_id") in current_archetypes
            }
            current_context_support = len(current_context_files)
        else:
            support_file_count = parse_int(freq_row.get("file_count"))
            support_occurrence_count = parse_int(freq_row.get("occurrence_count"))
            route_families = []
            cue_paths = set()
            archetypes = set()
            current_context_support = 0
        same_route_paths = {item for item in occurrence_paths if route_family(item) == route}
        same_route_file_count = len(same_route_paths)
        other_route_file_count = max(0, support_file_count - same_route_file_count)
        route_family_count = len(route_families) or parse_int(freq_row.get("route_family_count"))
        cue_file_count = len(cue_paths)
        promoted = sorted(set(promoted_by_shape.get(shape_id, [])))
        classification, priority, next_gate = classify_shape(
            promoted_profiles=promoted,
            support_file_count=support_file_count,
            same_route_file_count=same_route_file_count,
            other_route_file_count=other_route_file_count,
            route_family_count=route_family_count,
            cue_file_count=cue_file_count,
        )
        detail_rows.append(
            {
                "normalized_path": path,
                "route_family": route,
                "cue_domains": cue_by_path.get(path, ""),
                "shape_id": shape_id,
                "event_residual_occurrence_count": counts_in_event[(path, shape_id)],
                "sequence_tag": row.get("sequence_tag", ""),
                "source_tag_values": row.get("source_tag_values", ""),
                "target_tag_values": row.get("target_tag_values", ""),
                "support_occurrence_count": support_occurrence_count,
                "support_file_count": support_file_count,
                "same_route_file_count": same_route_file_count,
                "other_route_file_count": other_route_file_count,
                "route_family_count": route_family_count,
                "cue_file_count": cue_file_count,
                "context_archetype_count": len(archetypes),
                "current_context_file_support": current_context_support,
                "support_paths": unique_join(occurrence_paths, limit=12),
                "promoted_profile_ids": ";".join(promoted),
                "classification": classification,
                "review_priority": priority,
                "next_gate": next_gate,
            }
        )

    support_rows: list[dict[str, object]] = []
    by_shape: dict[str, list[dict[str, object]]] = defaultdict(list)
    for row in detail_rows:
        by_shape[str(row["shape_id"])].append(row)
    for shape_id, rows in sorted(by_shape.items()):
        representative = rows[0]
        support_rows.append(
            {
                "shape_id": shape_id,
                "classification": representative["classification"],
                "review_priority": representative["review_priority"],
                "sequence_tag": representative["sequence_tag"],
                "source_tag_values": representative["source_tag_values"],
                "target_tag_values": representative["target_tag_values"],
                "unresolved_event_count": len({str(item["normalized_path"]) for item in rows}),
                "unresolved_events": unique_join(str(item["normalized_path"]) for item in rows),
                "cue_domains": unique_join(str(item["cue_domains"]) for item in rows),
                "support_occurrence_count": representative["support_occurrence_count"],
                "support_file_count": representative["support_file_count"],
                "same_route_file_count": max(parse_int(item["same_route_file_count"]) for item in rows),
                "other_route_file_count": representative["other_route_file_count"],
                "route_family_count": representative["route_family_count"],
                "cue_file_count": representative["cue_file_count"],
                "context_archetype_count": representative["context_archetype_count"],
                "promoted_profile_ids": representative["promoted_profile_ids"],
                "next_gate": representative["next_gate"],
            }
        )

    cohort_rows = [
        row for row in support_rows
        if row["classification"] in {
            "route_sequence_state_candidate",
            "shared_presentation_candidate",
            "already_covered_by_existing_local_profile",
        }
    ]

    focused_rows: list[dict[str, object]] = []
    by_path: dict[str, list[dict[str, object]]] = defaultdict(list)
    for row in detail_rows:
        by_path[str(row["normalized_path"])].append(row)
    rank = {"high": 0, "medium": 1, "low": 2, "parked": 3}
    for path, rows in sorted(by_path.items()):
        classes = Counter(str(item["classification"]) for item in rows)
        priority = min((str(item["review_priority"]) for item in rows), key=lambda value: rank.get(value, 9))
        uncovered_high = [
            item for item in rows
            if item["classification"] in {"route_sequence_state_candidate", "shared_presentation_candidate"}
        ]
        if uncovered_high:
            next_action = "analyze exact contexts of the uncovered repeated/shared shapes before considering any additional local prototype"
        elif all(item["classification"] == "already_covered_by_existing_local_profile" for item in rows):
            next_action = "no duplicate work; await runtime validation of the existing profile"
        else:
            next_action = "retain scene as evidence-only; scene-unique and corpus-common residuals are not sufficient for a prototype"
        focused_rows.append(
            {
                "normalized_path": path,
                "cue_domains": cue_by_path.get(path, ""),
                "unknown_shape_count": len(rows),
                "already_covered_shape_count": classes["already_covered_by_existing_local_profile"],
                "route_sequence_shape_count": classes["route_sequence_state_candidate"],
                "shared_presentation_shape_count": classes["shared_presentation_candidate"],
                "scene_unique_shape_count": classes["scene_unique_residual_candidate"],
                "corpus_common_shape_count": classes["corpus_common_or_schema_candidate"],
                "other_shape_count": len(rows) - sum(
                    classes[name]
                    for name in (
                        "already_covered_by_existing_local_profile",
                        "route_sequence_state_candidate",
                        "shared_presentation_candidate",
                        "scene_unique_residual_candidate",
                        "corpus_common_or_schema_candidate",
                    )
                ),
                "review_priority": priority,
                "next_action": next_action,
            }
        )

    return detail_rows, support_rows, cohort_rows, focused_rows


def make_archive(report_dir: Path, archive: Path) -> None:
    archive.parent.mkdir(parents=True, exist_ok=True)
    temporary = archive.with_name(archive.name + f".tmp.{os.getpid()}")
    if temporary.exists():
        temporary.unlink()
    result = subprocess.run(
        ["tar", "--zstd", "-cf", str(temporary), "-C", str(report_dir.parent), report_dir.name],
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if result.returncode != 0:
        raise ResidualContextError(f"cannot create report archive: {result.stderr.strip()}")
    os.replace(temporary, archive)


def collect(
    *,
    project_root: Path,
    report_root: Path | None = None,
    core_list_command: Path | None = None,
    create_archive: bool = True,
) -> tuple[Path | None, dict[str, object]]:
    project_root = project_root.expanduser().resolve()
    report_root = (report_root or project_root / ".local/reports/quartet_restoration").resolve()
    report_root.mkdir(parents=True, exist_ok=True)

    core_result = run_core_list(project_root, core_list_command)
    manifests = load_manifests(project_root)
    discovery_rows = validate_core_discovery(project_root, core_result, manifests)

    with tempfile.TemporaryDirectory(prefix="br-residual-scene-context-") as temporary:
        temp = Path(temporary)
        extracted: dict[str, Path] = {}
        for key, filename in INPUT_REPORTS.items():
            extracted[key] = extract_report(report_root / filename, temp / key)
        detail_rows, support_rows, cohort_rows, focused_rows = analyze_residuals(
            single_scene_root=extracted["single_scene"],
            context_root=extracted["context"],
            migration_root=extracted["migration"],
            prototype_root=extracted["event_prototypes"],
        )

    evidence_dir = report_root / EVIDENCE_DIR_NAME
    if evidence_dir.exists():
        shutil.rmtree(evidence_dir)
    evidence_dir.mkdir(parents=True)

    write_tsv(
        evidence_dir / "CORE_PROFILE_DISCOVERY.tsv",
        [
            "profile_id", "target_relative_path", "manifest_relative_path",
            "local_profile_path", "local_profile_exists", "runtime_validated",
            "core_list_mentions_profile", "validation_status",
        ],
        discovery_rows,
    )
    output_rows: list[dict[str, object]] = []
    for stream, text in (("stdout", core_result.stdout), ("stderr", core_result.stderr)):
        for index, line in enumerate(text.splitlines(), 1):
            output_rows.append({"stream": stream, "line_index": index, "text": line})
    write_tsv(
        evidence_dir / "CORE_PROFILE_LIST_OUTPUT.tsv",
        ["stream", "line_index", "text"],
        output_rows,
    )
    detail_fields = [
        "normalized_path", "route_family", "cue_domains", "shape_id",
        "event_residual_occurrence_count", "sequence_tag", "source_tag_values",
        "target_tag_values", "support_occurrence_count", "support_file_count",
        "same_route_file_count", "other_route_file_count", "route_family_count",
        "cue_file_count", "context_archetype_count", "current_context_file_support",
        "support_paths", "promoted_profile_ids", "classification", "review_priority",
        "next_gate",
    ]
    write_tsv(evidence_dir / "UNRESOLVED_SCENE_RESIDUAL_SHAPES.tsv", detail_fields, detail_rows)
    support_fields = [
        "shape_id", "classification", "review_priority", "sequence_tag",
        "source_tag_values", "target_tag_values", "unresolved_event_count",
        "unresolved_events", "cue_domains", "support_occurrence_count",
        "support_file_count", "same_route_file_count", "other_route_file_count",
        "route_family_count", "cue_file_count", "context_archetype_count",
        "promoted_profile_ids", "next_gate",
    ]
    write_tsv(evidence_dir / "RESIDUAL_SHAPE_CORPUS_SUPPORT.tsv", support_fields, support_rows)
    write_tsv(evidence_dir / "RESIDUAL_ROUTE_AND_SHARED_COHORTS.tsv", support_fields, cohort_rows)
    focused_fields = [
        "normalized_path", "cue_domains", "unknown_shape_count",
        "already_covered_shape_count", "route_sequence_shape_count",
        "shared_presentation_shape_count", "scene_unique_shape_count",
        "corpus_common_shape_count", "other_shape_count", "review_priority",
        "next_action",
    ]
    write_tsv(evidence_dir / "FOCUSED_UNRESOLVED_SCENE_REVIEW.tsv", focused_fields, focused_rows)

    class_counts = Counter(str(row["classification"]) for row in support_rows)
    summary: dict[str, object] = {
        "type": "br_quartet_restoration_residual_scene_context_evidence_summary",
        "format_version": 1,
        "tool_version": TOOL_VERSION,
        "status": "core_registry_confirmed_and_unresolved_scene_residuals_classified_without_new_payloads",
        "core_profile_manifest_rows": len(discovery_rows),
        "core_profile_list_exit_code": core_result.returncode,
        "core_profile_rows_passed": sum(row["validation_status"] == "passed" for row in discovery_rows),
        "runtime_validated_profile_rows": sum(parse_bool(row["runtime_validated"]) for row in discovery_rows),
        "unresolved_event_rows": len(focused_rows),
        "unresolved_shape_occurrence_rows": len(detail_rows),
        "unique_unresolved_shape_rows": len(support_rows),
        "classification_counts": dict(sorted(class_counts.items())),
        "route_or_shared_cohort_rows": len(cohort_rows),
        "policy": {
            "installed_games_modified": False,
            "profile_manifests_modified": False,
            "local_profile_paks_modified": False,
            "activation_or_rollback_invoked": False,
            "new_event_or_shader_payload_generated": False,
            "runtime_validation_inferred": False,
            "dialogue_or_localized_text_exported": False,
            "event_tag_semantics_assigned": False,
            "legacy_dlc_in_scope": False,
        },
        "next_action": "Upload this report. Only uncovered route-local or shared cue-positive residual shapes should receive deeper exact-context analysis; existing-profile, corpus-common and scene-unique shapes remain parked or evidence-only.",
    }
    (evidence_dir / "SUMMARY.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    archive = report_root / REPORT_NAME if create_archive else None
    if archive is not None:
        make_archive(evidence_dir, archive)
    return archive, summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", required=True)
    parser.add_argument("--report-root")
    parser.add_argument("--core-list-command")
    parser.add_argument("--no-archive", action="store_true")
    args = parser.parse_args()
    archive, summary = collect(
        project_root=Path(args.project_root),
        report_root=Path(args.report_root).expanduser() if args.report_root else None,
        core_list_command=Path(args.core_list_command).expanduser() if args.core_list_command else None,
        create_archive=not args.no_archive,
    )
    print(f"Core profiles discovered: {summary['core_profile_rows_passed']}")
    print(f"Runtime-validated profiles: {summary['runtime_validated_profile_rows']}")
    print(f"Unresolved events: {summary['unresolved_event_rows']}")
    print(f"Unique unresolved shapes: {summary['unique_unresolved_shape_rows']}")
    print(f"Route/shared cohorts: {summary['route_or_shared_cohort_rows']}")
    if archive is not None:
        print(f"Report: {archive}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except ResidualContextError as exc:
        print(f"ERROR: {exc}", file=os.sys.stderr)
        raise SystemExit(1)
