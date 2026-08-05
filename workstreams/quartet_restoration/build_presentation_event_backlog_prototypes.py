#!/usr/bin/env python3
"""Build separate local EBD prototypes for stage-40 safe backlog groups.

The stage accepts only groups already classified by stage 40 as safe for static
construction.  It reproduces the exact stage-29 composite candidate, verifies
all stage-23 splice inputs, preserves every non-selected residual-shape counter,
and proves an exact reverse round-trip to the current Quartet target.  Candidate
EBD payloads are written only below the local quartet_restoration workspace.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import importlib
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
TOOL_VERSION = "0.0.48"
REPORT_NAME = "BR_quartet_restoration_presentation_event_backlog_prototype_evidence.tar.zst"
EVIDENCE_DIR_NAME = "presentation_event_backlog_prototype_evidence"
PROTOTYPE_SUBDIR = "prototypes/presentation_event_backlog"

REPORT_SPECS = {
    "backlog": (
        "presentation_event_backlog_evidence",
        "BR_quartet_restoration_presentation_event_backlog_evidence.tar.zst",
    ),
    "context": (
        "event_delta_context_evidence",
        "BR_quartet_restoration_event_delta_context_evidence.tar.zst",
    ),
    "composite": (
        "single_scene_composite_evidence",
        "BR_quartet_restoration_single_scene_composite_evidence.tar.zst",
    ),
}


class BacklogPrototypeError(RuntimeError):
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


def read_tsv(path: Path, *, required: bool = True) -> list[dict[str, str]]:
    if not path.is_file():
        if required:
            raise BacklogPrototypeError(f"missing prerequisite table: {path}")
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
        raise BacklogPrototypeError(f"missing prerequisite JSON: {path}")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise BacklogPrototypeError(f"invalid JSON {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise BacklogPrototypeError(f"expected JSON object: {path}")
    return data


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
        raise BacklogPrototypeError(f"unsafe report archive member: {raw}")
    return path.as_posix()


def extract_archive(archive: Path, destination: Path) -> Path:
    if not archive.is_file():
        raise BacklogPrototypeError(f"missing prerequisite report archive: {archive}")
    listed = subprocess.run(
        ["tar", "--zstd", "-tf", str(archive)], text=True,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False,
    )
    if listed.returncode != 0:
        raise BacklogPrototypeError(f"cannot list {archive}: {listed.stderr.strip()}")
    roots: set[str] = set()
    for raw in listed.stdout.splitlines():
        if not raw.strip():
            continue
        safe = safe_member_name(raw.strip())
        roots.add(PurePosixPath(safe).parts[0])
    if len(roots) != 1:
        raise BacklogPrototypeError(f"expected one report root in {archive}, found {sorted(roots)}")
    destination.mkdir(parents=True, exist_ok=True)
    completed = subprocess.run(
        ["tar", "--zstd", "-xf", str(archive), "-C", str(destination)], text=True,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False,
    )
    if completed.returncode != 0:
        raise BacklogPrototypeError(f"cannot extract {archive}: {completed.stderr.strip()}")
    return destination / next(iter(roots))


def locate_report_root(report_root: Path, key: str, temporary: Path) -> Path:
    directory_name, archive_name = REPORT_SPECS[key]
    direct = report_root / directory_name
    if direct.is_dir():
        return direct
    return extract_archive(report_root / archive_name, temporary / key)


def load_restoration_tool(project_root: Path) -> Any:
    tool_root = project_root / "Blue_Reflection_Text_Tool"
    tool_path = tool_root / "br_restoration_tool.py"
    if not tool_path.is_file():
        raise BacklogPrototypeError(f"missing restoration tool: {tool_path}")
    sys.path.insert(0, str(tool_root))
    try:
        return importlib.import_module("br_restoration_tool")
    finally:
        try:
            sys.path.remove(str(tool_root))
        except ValueError:
            pass


def normalize_event_member(path: str) -> str:
    value = str(path or "").replace("\\", "/").lstrip("./")
    for prefix in ("event/b1/event_jp/", "data/b1/event/event_jp/", "event/event_jp/"):
        if value.casefold().startswith(prefix.casefold()):
            return "event/event_jp/" + value[len(prefix):]
    return value


def event_key(row: Mapping[str, object]) -> tuple[str, str, int]:
    return (
        normalize_event_member(str(row.get("normalized_path", ""))),
        str(row.get("shape_id", "")),
        parse_int(row.get("occurrence_index"), -1),
    )


def byte_difference_count(left: bytes, right: bytes) -> int:
    overlap = min(len(left), len(right))
    return sum(a != b for a, b in zip(left[:overlap], right[:overlap])) + abs(len(left) - len(right))


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
        raise BacklogPrototypeError("source EBD header is not recognized")
    if target_header.get("classification") != "observed_ebd_name_description_header":
        raise BacklogPrototypeError("target EBD header is not recognized")
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
        occurrence_index = parse_int(occurrence.get("occurrence_index"), -1)
        candidates = matches.get(shape_id, [])
        if occurrence_index < 0 or occurrence_index >= len(candidates):
            raise BacklogPrototypeError(
                f"reported occurrence cannot be reproduced: {shape_id}:{occurrence_index}"
            )
        delta = candidates[occurrence_index]
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
            "occurrence_index": occurrence_index,
            "source_start": source_start,
            "source_end": source_end,
            "target_start": target_start,
            "target_end": target_end,
            "source_words": list(source_profile["words"])[source_start:source_end],
            "target_words": list(target_profile["words"])[target_start:target_end],
        })
    return operations, source_profile, target_profile


def reverse_composite_candidate(
    *, candidate_payload: bytes, target_payload: bytes, target_header_end: int,
    operations: Sequence[Mapping[str, object]], br: Any,
) -> bytes:
    candidate_header = br.parse_ebd_header_schema(candidate_payload)
    target_header = br.parse_ebd_header_schema(target_payload)
    if candidate_header.get("classification") != "observed_ebd_name_description_header":
        return b""
    if target_header.get("classification") != "observed_ebd_name_description_header":
        return b""
    candidate_profile = br.profile_ebd_post_header_words(
        candidate_payload, int(candidate_header["header_end"]), maximum_words=max(1, len(candidate_payload) // 4 + 8)
    )
    target_profile = br.profile_ebd_post_header_words(
        target_payload, int(target_header["header_end"]), maximum_words=max(1, len(target_payload) // 4 + 8)
    )
    candidate_words = list(candidate_profile["words"])
    target_words = list(target_profile["words"])
    candidate_end = int(candidate_header["header_end"]) + int(candidate_profile["word_count"]) * 4
    target_end = int(target_header["header_end"]) + int(target_profile["word_count"]) * 4
    candidate_trailing = candidate_payload[candidate_end:]
    target_trailing = target_payload[target_end:]
    if candidate_trailing != target_trailing or int(candidate_header["header_end"]) != target_header_end:
        return b""

    cumulative_shift = 0
    mapped: list[tuple[int, int, list[int]]] = []
    for operation in sorted(operations, key=lambda row: (int(row["target_start"]), int(row["target_end"]))):
        target_start = int(operation["target_start"])
        target_finish = int(operation["target_end"])
        source_words = list(operation["source_words"])
        target_span_words = list(operation["target_words"])
        candidate_start = target_start + cumulative_shift
        candidate_finish = candidate_start + len(source_words)
        mapped.append((candidate_start, candidate_finish, target_span_words))
        cumulative_shift += len(source_words) - (target_finish - target_start)
    rebuilt = list(candidate_words)
    for start, finish, target_span_words in sorted(mapped, reverse=True):
        rebuilt[start:finish] = target_span_words
    return (
        target_payload[:target_header_end]
        + (struct.pack(f"<{len(rebuilt)}I", *rebuilt) if rebuilt else b"")
        + target_trailing
    )


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
        raise BacklogPrototypeError(f"cannot create report archive: {result.stderr.strip()}")
    os.replace(temporary, output)


def validate_stage40(backlog_root: Path) -> tuple[dict[str, Any], list[dict[str, str]], dict[str, dict[str, str]]]:
    summary = load_json(backlog_root / "SUMMARY.json")
    if summary.get("type") != "br_quartet_restoration_presentation_event_backlog_evidence_summary":
        raise BacklogPrototypeError("stage-40 report has an unexpected summary type")
    if summary.get("tool_version") != "0.0.46":
        raise BacklogPrototypeError(f"stage-40 report tool version is {summary.get('tool_version')!r}, expected '0.0.46'")
    if summary.get("status") != "possible_presentation_events_consolidated_runtime_testing_deferred":
        raise BacklogPrototypeError(f"stage-40 report status is unexpected: {summary.get('status')!r}")
    if not parse_bool(summary.get("runtime_testing_deferred")):
        raise BacklogPrototypeError("stage-40 report must keep runtime testing deferred")
    groups = read_tsv(backlog_root / "EVENT_CANDIDATE_BUILD_GROUPS.tsv")
    backlog_rows = read_tsv(backlog_root / "EVENT_CANDIDATE_BACKLOG.tsv")
    if len(groups) != parse_int(summary.get("proposed_build_group_rows"), -1):
        raise BacklogPrototypeError("stage-40 proposed build-group count changed")
    safe_rows = [row for row in backlog_rows if parse_bool(row.get("safe_to_build_local_profile_without_runtime"))]
    if len(safe_rows) != parse_int(summary.get("safe_static_build_event_rows"), -1):
        raise BacklogPrototypeError("stage-40 safe event count changed")
    backlog_by_path = {normalize_event_member(row.get("normalized_path", "")): row for row in backlog_rows}
    for group in groups:
        if group.get("group_type") != "single_scene_multi_shape":
            raise BacklogPrototypeError(f"unsupported stage-40 group type: {group.get('group_type')!r}")
        if group.get("build_mode") != "reconstruct_exact_selected_spans_as_one_scene_profile":
            raise BacklogPrototypeError(f"unsupported stage-40 build mode: {group.get('build_mode')!r}")
        if parse_int(group.get("event_count")) != 1 or len(split_cell(group.get("event_paths"))) != 1:
            raise BacklogPrototypeError("stage-40 multi-shape group must contain exactly one event")
        if not all(parse_bool(group.get(field)) for field in (
            "requires_exact_hash_roundtrip", "requires_other_shape_counter_preservation",
            "repack_separately", "register_inactive", "runtime_test_deferred",
        )):
            raise BacklogPrototypeError(f"stage-40 group safety flags changed: {group.get('proposed_profile_id')}")
        path = normalize_event_member(split_cell(group.get("event_paths"))[0])
        backlog = backlog_by_path.get(path)
        if backlog is None:
            raise BacklogPrototypeError(f"stage-40 group path is absent from backlog: {path}")
        if backlog.get("classification") != "isolated_cue_inverse_splice_candidate":
            raise BacklogPrototypeError(f"stage-40 group is not an isolated cue-splice candidate: {path}")
        if backlog.get("existing_profile_ids"):
            raise BacklogPrototypeError(f"stage-40 group is already covered by a profile: {path}")
    return summary, groups, backlog_by_path


def build_prototypes(
    *, project_root: Path, workspace_root: Path, report_root: Path,
    maximum_event_bytes: int = 2 * 1024 * 1024,
) -> tuple[Path, dict[str, object]]:
    project_root = project_root.expanduser().resolve()
    workspace_root = workspace_root.expanduser().resolve()
    report_root = report_root.expanduser().resolve()
    br = load_restoration_tool(project_root)

    with tempfile.TemporaryDirectory(prefix="br-backlog-prototypes-") as temporary_name:
        temporary = Path(temporary_name)
        roots = {key: locate_report_root(report_root, key, temporary) for key in REPORT_SPECS}
        stage40_summary, group_rows, backlog_by_path = validate_stage40(roots["backlog"])

        context_summary = load_json(roots["context"] / "SUMMARY.json")
        if context_summary.get("type") != "br_quartet_restoration_event_delta_context_evidence_summary":
            raise BacklogPrototypeError("stage-23 report has an unexpected summary type")
        composite_summary = load_json(roots["composite"] / "SUMMARY.json")
        if composite_summary.get("type") != "br_quartet_restoration_single_scene_composite_evidence_summary":
            raise BacklogPrototypeError("stage-29 report has an unexpected summary type")

        occurrences = {event_key(row): row for row in read_tsv(roots["context"] / "EVENT_DELTA_CONTEXT_OCCURRENCES.tsv")}
        stage23_splices = {event_key(row): row for row in read_tsv(roots["context"] / "IN_MEMORY_EVENT_DELTA_SPLICE_READINESS.tsv")}
        controls = {str(row.get("shape_id", "")): row for row in read_tsv(roots["context"] / "EVENT_DELTA_CUE_NONCUE_COMPARISON.tsv")}
        composite_events = {
            normalize_event_member(row.get("normalized_path", "")): row
            for row in read_tsv(roots["composite"] / "SINGLE_SCENE_COMPOSITE_EVENTS.tsv")
        }
        composite_splices_by_path: defaultdict[str, list[dict[str, str]]] = defaultdict(list)
        for row in read_tsv(roots["composite"] / "SINGLE_SCENE_COMPOSITE_SPLICES.tsv"):
            composite_splices_by_path[normalize_event_member(row.get("normalized_path", ""))].append(row)
        composite_residuals_by_path: defaultdict[str, list[dict[str, str]]] = defaultdict(list)
        for row in read_tsv(roots["composite"] / "SINGLE_SCENE_COMPOSITE_RESIDUALS.tsv"):
            composite_residuals_by_path[normalize_event_member(row.get("normalized_path", ""))].append(row)

        difference_reports = br.load_report_jsons(report_root, "differences")
        event_report = next(
            (row for row in difference_reports if str(row.get("source_archive_group", "")) == "br1_events"),
            None,
        )
        if event_report is None:
            raise BacklogPrototypeError("missing br1_events difference report")
        entry_by_path = {
            normalize_event_member(str(row.get("normalized_path", ""))): row
            for row in event_report.get("entries", [])
            if row.get("scope_status") == "in_scope" and row.get("source") and row.get("target")
        }

        prototype_root = workspace_root / PROTOTYPE_SUBDIR
        try:
            prototype_root.relative_to(workspace_root)
        except ValueError as exc:
            raise BacklogPrototypeError("prototype root escapes quartet_restoration workspace") from exc
        if prototype_root.exists():
            shutil.rmtree(prototype_root)
        prototype_root.mkdir(parents=True, exist_ok=True)

        profile_output_rows: list[dict[str, object]] = []
        file_output_rows: list[dict[str, object]] = []
        splice_output_rows: list[dict[str, object]] = []
        residual_output_rows: list[dict[str, object]] = []
        validation_rows: list[dict[str, object]] = []
        skipped_rows: list[dict[str, object]] = []

        for group in sorted(group_rows, key=lambda row: parse_int(row.get("group_order"))):
            profile_id = str(group.get("proposed_profile_id", ""))
            path = normalize_event_member(split_cell(group.get("event_paths"))[0])
            backlog = backlog_by_path[path]
            composite = composite_events.get(path)
            stage29_splices = sorted(
                composite_splices_by_path.get(path, []), key=lambda row: (str(row.get("shape_id", "")), parse_int(row.get("occurrence_index")))
            )
            if not profile_id or composite is None or not stage29_splices:
                skipped_rows.append({
                    "profile_id": profile_id, "normalized_path": path,
                    "reason": "stage29_event_or_splice_rows_missing",
                })
                continue
            if composite.get("classification") != "selected_single_scene_shapes_removed_unknown_residuals_remain":
                skipped_rows.append({
                    "profile_id": profile_id, "normalized_path": path,
                    "reason": f"unsupported_stage29_classification:{composite.get('classification', '')}",
                })
                continue
            if composite.get("candidate_sha256") != backlog.get("composite_candidate_sha256"):
                skipped_rows.append({
                    "profile_id": profile_id, "normalized_path": path,
                    "reason": "stage29_and_stage40_candidate_sha256_disagree",
                })
                continue

            selected_occurrences: list[dict[str, str]] = []
            selected_inputs: list[tuple[tuple[str, str, int], dict[str, str], dict[str, str], dict[str, str]]] = []
            input_failed = False
            for splice in stage29_splices:
                key = event_key(splice)
                occurrence = occurrences.get(key)
                stage23 = stage23_splices.get(key)
                control = controls.get(key[1], {})
                stage29_component_sha = str(splice.get("stage23_candidate_sha256", "")).strip()
                checks = {
                    "stage23_occurrence_present": occurrence is not None,
                    "stage23_splice_present": stage23 is not None,
                    "cue_positive_occurrence": bool(occurrence) and parse_bool(occurrence.get("cue_positive_occurrence")),
                    "isolated_stage23_splice": bool(stage23) and stage23.get("in_memory_splice_status") == "selected_shape_removed_without_other_coarse_delta_changes",
                    # Stage 29 tool version 0.0.35 accidentally copied this hash from
                    # the occurrence table, where the field did not exist, so the real
                    # report contains an empty value.  A non-empty value must still
                    # match stage 23.  Empty legacy values are accepted only provisionally
                    # and are revalidated from the actual EBD payload below.
                    "stage29_component_hash_legacy_blank_or_matches_stage23": bool(stage23) and (
                        not stage29_component_sha
                        or stage23.get("candidate_sha256") == stage29_component_sha
                    ),
                    "no_shared_cue_noncue_exact_context": parse_int(control.get("shared_cue_noncue_context_archetype_count")) == 0,
                    "stage29_composite_sha256_consistent": splice.get("composite_candidate_sha256") == composite.get("candidate_sha256"),
                }
                for check_name, passed in checks.items():
                    validation_rows.append({
                        "profile_id": profile_id, "normalized_path": path,
                        "check_name": f"input_{key[1][:12]}_{key[2]}_{check_name}",
                        "passed": passed,
                        "review_status": "static_metadata_gate_not_runtime_validation",
                    })
                if not all(checks.values()):
                    input_failed = True
                    continue
                assert occurrence is not None and stage23 is not None
                selected_occurrences.append(occurrence)
                selected_inputs.append((key, occurrence, stage23, splice))
            if input_failed or len(selected_occurrences) != len(stage29_splices):
                skipped_rows.append({
                    "profile_id": profile_id, "normalized_path": path,
                    "reason": "one_or_more_selected_splice_inputs_failed",
                })
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

            # Rebuild every individual stage-23 splice from the actual source/target
            # EBD payload.  This closes the historical blank-field gap in stage 29
            # without weakening the checksum gate.
            single_splice_failed = False
            staged_splice_rows: list[dict[str, object]] = []
            for key, occurrence, stage23, splice in selected_inputs:
                try:
                    single_candidate, single_metadata, _ = br.construct_composite_inverse_event_candidate(
                        source_payload=source_payload,
                        target_payload=target_payload,
                        selected_occurrences=[occurrence],
                    )
                except (br.RestorationError, OSError, ValueError, struct.error):
                    single_candidate = None
                    single_metadata = {}
                expected_stage23_sha = str(stage23.get("candidate_sha256", "")).strip()
                stage29_component_sha = str(splice.get("stage23_candidate_sha256", "")).strip()
                single_checks = {
                    "stage23_candidate_sha256_present": len(expected_stage23_sha) == 64,
                    "single_splice_reconstruction_succeeded": single_candidate is not None,
                    "single_splice_candidate_sha256_matches_stage23": (
                        single_candidate is not None
                        and single_metadata.get("candidate_sha256") == expected_stage23_sha
                    ),
                    "single_splice_selected_shape_removed": (
                        single_candidate is not None
                        and parse_bool(single_metadata.get("all_selected_shapes_removed"))
                        and parse_int(single_metadata.get("selected_shape_count_after")) == 0
                    ),
                    "single_splice_no_coarse_shape_side_effects": (
                        single_candidate is not None
                        and parse_int(single_metadata.get("introduced_coarse_shape_count")) == 0
                        and parse_int(single_metadata.get("removed_nonselected_coarse_shape_count")) == 0
                    ),
                }
                for check_name, passed in single_checks.items():
                    validation_rows.append({
                        "profile_id": profile_id, "normalized_path": path,
                        "check_name": f"rebuild_{key[1][:12]}_{key[2]}_{check_name}",
                        "passed": passed,
                        "review_status": "static_metadata_gate_not_runtime_validation",
                    })
                if not all(single_checks.values()):
                    single_splice_failed = True
                    continue
                staged_splice_rows.append({
                    "profile_id": profile_id,
                    "normalized_path": path,
                    "shape_id": key[1],
                    "occurrence_index": key[2],
                    "cue_domains": occurrence.get("cue_domains", ""),
                    "selection_reasons": occurrence.get("selection_reasons", ""),
                    "stage23_candidate_sha256": expected_stage23_sha,
                    "stage29_component_sha256": stage29_component_sha,
                    "composite_candidate_sha256": composite.get("candidate_sha256", ""),
                    "component_hash_validation_status": (
                        "legacy_stage29_blank_revalidated_from_ebd"
                        if not stage29_component_sha
                        else "stage29_component_hash_matched_and_revalidated"
                    ),
                    "input_validation_status": "passed",
                })
            if single_splice_failed or len(staged_splice_rows) != len(selected_inputs):
                skipped_rows.append({
                    "profile_id": profile_id, "normalized_path": path,
                    "reason": "one_or_more_stage23_splices_failed_payload_reconstruction",
                })
                continue
            splice_output_rows.extend(staged_splice_rows)

            try:
                candidate_payload, metadata, residuals = br.construct_composite_inverse_event_candidate(
                    source_payload=source_payload,
                    target_payload=target_payload,
                    selected_occurrences=selected_occurrences,
                )
                if candidate_payload is None:
                    raise BacklogPrototypeError(f"candidate construction failed: {metadata.get('status')}")
                operations, source_profile, target_profile = build_operations(
                    br=br, source_payload=source_payload, target_payload=target_payload,
                    selected_occurrences=selected_occurrences,
                )
                reverse_payload = reverse_composite_candidate(
                    candidate_payload=candidate_payload, target_payload=target_payload,
                    target_header_end=int(br.parse_ebd_header_schema(target_payload)["header_end"]),
                    operations=operations, br=br,
                )
            except (BacklogPrototypeError, br.RestorationError, OSError, ValueError, struct.error) as exc:
                skipped_rows.append({
                    "profile_id": profile_id, "normalized_path": path,
                    "reason": f"candidate_error:{type(exc).__name__}:{exc}",
                })
                continue

            candidate_header = br.parse_ebd_header_schema(candidate_payload)
            candidate_profile = br.profile_ebd_post_header_words(
                candidate_payload, int(candidate_header.get("header_end", 0)),
                maximum_words=max(1, len(candidate_payload) // 4 + 8),
            )
            before_counter = shape_counter(br, source_profile, target_profile)
            after_counter = shape_counter(br, source_profile, candidate_profile)
            selected_counter = Counter(str(row.get("shape_id", "")) for row in selected_occurrences)
            nonselected_before = before_counter.copy()
            nonselected_after = after_counter.copy()
            for shape_id in selected_counter:
                nonselected_before.pop(shape_id, None)
                nonselected_after.pop(shape_id, None)

            stage29_residual_counter = Counter(row.get("shape_id", "") for row in composite_residuals_by_path.get(path, []))
            rebuilt_residual_counter = Counter(row.get("shape_id", "") for row in residuals)
            checks = {
                "candidate_sha256_matches_stage29": metadata.get("candidate_sha256") == composite.get("candidate_sha256"),
                "candidate_sha256_matches_stage40": metadata.get("candidate_sha256") == backlog.get("composite_candidate_sha256"),
                "candidate_size_matches_stage29": parse_int(metadata.get("candidate_size")) == parse_int(composite.get("candidate_size")),
                "operation_count_matches_stage29": parse_int(metadata.get("operation_count")) == parse_int(composite.get("operation_count")),
                "all_selected_shapes_removed": parse_bool(metadata.get("all_selected_shapes_removed")),
                "selected_shape_count_after_zero": parse_int(metadata.get("selected_shape_count_after")) == 0,
                "no_introduced_coarse_shapes": parse_int(metadata.get("introduced_coarse_shape_count")) == 0,
                "no_nonselected_coarse_shapes_removed": parse_int(metadata.get("removed_nonselected_coarse_shape_count")) == 0,
                "all_nonselected_shape_counters_preserved": nonselected_before == nonselected_after,
                "stage29_residual_shape_multiset_reproduced": stage29_residual_counter == rebuilt_residual_counter,
                "stage29_unknown_residual_count_reproduced": parse_int(composite.get("unknown_residual_rows")) == parse_int(backlog.get("unknown_residual_shapes")),
                "candidate_header_preserved_from_target": parse_bool(metadata.get("candidate_header_preserved_from_target")),
                "candidate_trailing_preserved_from_target": parse_bool(metadata.get("candidate_trailing_bytes_preserved_from_target")),
                "candidate_header_valid": metadata.get("candidate_header_classification") == "observed_ebd_name_description_header",
                "exact_target_reverse_roundtrip": reverse_payload == target_payload,
                "candidate_not_farther_from_original": byte_difference_count(candidate_payload, source_payload)
                    <= byte_difference_count(target_payload, source_payload),
            }
            for check_name, passed in checks.items():
                validation_rows.append({
                    "profile_id": profile_id, "normalized_path": path,
                    "check_name": check_name, "passed": passed,
                    "review_status": "static_metadata_gate_not_runtime_validation",
                })
            if not all(checks.values()):
                skipped_rows.append({
                    "profile_id": profile_id, "normalized_path": path,
                    "reason": "one_or_more_prototype_validation_gates_failed",
                })
                continue

            profile_dir = prototype_root / profile_id
            local_relative = PurePosixPath("payload") / PurePosixPath(path)
            candidate_path = profile_dir / Path(local_relative.as_posix())
            atomic_bytes(candidate_path, candidate_payload)
            manifest = {
                "type": "br_quartet_restoration_local_presentation_event_backlog_prototype",
                "format_version": 1,
                "tool_version": TOOL_VERSION,
                "profile_id": profile_id,
                "profile_classification": "experimental_single_scene_multishape_static_candidate",
                "prototype_confidence": "experimental_metadata_gated",
                "runtime_validated": False,
                "censorship_semantics_assigned": False,
                "installed_game_files_modified": False,
                "installable_package_generated": False,
                "source_stage40_group_type": group.get("group_type", ""),
                "source_stage29_classification": composite.get("classification", ""),
                "cue_domains": group.get("cue_domains", ""),
                "files": [{
                    "normalized_path": path,
                    "candidate_relative_path": local_relative.as_posix(),
                    "source_archive": source_ref.get("archive", ""),
                    "source_member_path": source_ref.get("path", ""),
                    "target_archive": target_ref.get("archive", ""),
                    "target_member_path": target_ref.get("path", ""),
                    "source_sha256": source_sha,
                    "target_sha256": target_sha,
                    "candidate_sha256": metadata.get("candidate_sha256", ""),
                    "source_size": len(source_payload),
                    "target_size": len(target_payload),
                    "candidate_size": len(candidate_payload),
                    "selected_splice_count": len(selected_occurrences),
                    "selected_shape_ids": sorted(selected_counter),
                    "remaining_residual_shape_count": sum(rebuilt_residual_counter.values()),
                    "remaining_unknown_residual_rows": parse_int(composite.get("unknown_residual_rows")),
                }],
            }
            atomic_json(profile_dir / "PROTOTYPE.json", manifest)

            profile_output_rows.append({
                "profile_id": profile_id,
                "profile_classification": "experimental_single_scene_multishape_static_candidate",
                "prototype_confidence": "experimental_metadata_gated",
                "event_count": 1,
                "event_paths": path,
                "selected_splice_count": len(selected_occurrences),
                "selected_shape_count": len(selected_counter),
                "selected_shape_ids": ";".join(sorted(selected_counter)),
                "remaining_residual_rows": len(residuals),
                "remaining_unknown_residual_rows": composite.get("unknown_residual_rows", ""),
                "cue_domains": group.get("cue_domains", ""),
                "local_profile_root": str(profile_dir.relative_to(project_root)) if profile_dir.is_relative_to(project_root) else str(profile_dir),
                "validation_status": "passed",
                "runtime_validated": False,
                "review_status": "separate_experimental_local_profile_not_repacked_not_installed",
            })
            file_output_rows.append({
                "profile_id": profile_id,
                "normalized_path": path,
                "source_archive": source_ref.get("archive", ""),
                "source_member_path": source_ref.get("path", ""),
                "target_archive": target_ref.get("archive", ""),
                "target_member_path": target_ref.get("path", ""),
                "source_sha256": source_sha,
                "target_sha256": target_sha,
                "candidate_sha256": metadata.get("candidate_sha256", ""),
                "source_size": len(source_payload),
                "target_size": len(target_payload),
                "candidate_size": len(candidate_payload),
                "candidate_size_delta": parse_int(metadata.get("candidate_size_delta_from_target")),
                "target_byte_difference_to_source": metadata.get("target_byte_difference_to_source", ""),
                "candidate_byte_difference_to_source": metadata.get("candidate_byte_difference_to_source", ""),
                "selected_splice_count": len(selected_occurrences),
                "remaining_residual_rows": len(residuals),
                "remaining_unknown_residual_rows": composite.get("unknown_residual_rows", ""),
                "local_relative_path": local_relative.as_posix(),
                "validation_status": "passed",
                "review_status": "candidate_payload_local_only_runtime_unvalidated",
            })
            for residual in residuals:
                residual_output_rows.append({
                    "profile_id": profile_id,
                    "normalized_path": path,
                    "shape_id": residual.get("shape_id", ""),
                    "sequence_tag": residual.get("sequence_tag", ""),
                    "source_atom_count": residual.get("source_atom_count", ""),
                    "target_atom_count": residual.get("target_atom_count", ""),
                    "classification": residual.get("classification", ""),
                    "review_status": "remaining_measured_residual_not_assigned_semantics",
                })

        profile_output_rows.sort(key=lambda row: str(row.get("profile_id", "")))
        file_output_rows.sort(key=lambda row: str(row.get("normalized_path", "")))
        splice_output_rows.sort(key=lambda row: (str(row.get("normalized_path", "")), str(row.get("shape_id", "")), parse_int(row.get("occurrence_index"))))
        residual_output_rows.sort(key=lambda row: (str(row.get("normalized_path", "")), str(row.get("shape_id", ""))))
        validation_rows.sort(key=lambda row: (str(row.get("profile_id", "")), str(row.get("check_name", ""))))
        skipped_rows.sort(key=lambda row: (str(row.get("profile_id", "")), str(row.get("reason", ""))))

        evidence_root = report_root / EVIDENCE_DIR_NAME
        if evidence_root.exists():
            shutil.rmtree(evidence_root)
        evidence_root.mkdir(parents=True, exist_ok=True)
        write_tsv(evidence_root / "PRESENTATION_EVENT_BACKLOG_PROFILES.tsv", [
            "profile_id", "profile_classification", "prototype_confidence", "event_count", "event_paths",
            "selected_splice_count", "selected_shape_count", "selected_shape_ids", "remaining_residual_rows",
            "remaining_unknown_residual_rows", "cue_domains", "local_profile_root", "validation_status",
            "runtime_validated", "review_status",
        ], profile_output_rows)
        write_tsv(evidence_root / "PRESENTATION_EVENT_BACKLOG_FILES.tsv", [
            "profile_id", "normalized_path", "source_archive", "source_member_path", "target_archive",
            "target_member_path", "source_sha256", "target_sha256", "candidate_sha256", "source_size",
            "target_size", "candidate_size", "candidate_size_delta", "target_byte_difference_to_source",
            "candidate_byte_difference_to_source", "selected_splice_count", "remaining_residual_rows",
            "remaining_unknown_residual_rows", "local_relative_path", "validation_status", "review_status",
        ], file_output_rows)
        write_tsv(evidence_root / "PRESENTATION_EVENT_BACKLOG_SELECTED_SPLICES.tsv", [
            "profile_id", "normalized_path", "shape_id", "occurrence_index", "cue_domains",
            "selection_reasons", "stage23_candidate_sha256", "stage29_component_sha256",
            "composite_candidate_sha256", "component_hash_validation_status", "input_validation_status",
        ], splice_output_rows)
        write_tsv(evidence_root / "PRESENTATION_EVENT_BACKLOG_RESIDUALS.tsv", [
            "profile_id", "normalized_path", "shape_id", "sequence_tag", "source_atom_count",
            "target_atom_count", "classification", "review_status",
        ], residual_output_rows)
        write_tsv(evidence_root / "PRESENTATION_EVENT_BACKLOG_VALIDATION.tsv", [
            "profile_id", "normalized_path", "check_name", "passed", "review_status",
        ], validation_rows)
        write_tsv(evidence_root / "PRESENTATION_EVENT_BACKLOG_BUILD_SKIPPED.tsv", [
            "profile_id", "normalized_path", "reason",
        ], skipped_rows)

        validation_failures = sum(not parse_bool(row.get("passed")) for row in validation_rows)
        summary: dict[str, object] = {
            "type": "br_quartet_restoration_presentation_event_backlog_prototype_evidence_summary",
            "format_version": 1,
            "tool_version": TOOL_VERSION,
            "source_stage40_tool_version": stage40_summary.get("tool_version"),
            "source_stage23_tool_version": context_summary.get("tool_version"),
            "source_stage29_tool_version": composite_summary.get("tool_version"),
            "status": "separate_experimental_local_backlog_event_prototypes_built_roundtrip_validated_not_repacked_or_installed",
            "proposed_group_rows": len(group_rows),
            "promoted_profile_rows": len(profile_output_rows),
            "prototype_file_rows": len(file_output_rows),
            "selected_splice_rows": len(splice_output_rows),
            "remaining_residual_rows": len(residual_output_rows),
            "prototype_validation_rows": len(validation_rows),
            "validation_failures": validation_failures,
            "skipped_rows": len(skipped_rows),
            "legacy_blank_stage29_component_hash_rows": sum(
                row.get("component_hash_validation_status") == "legacy_stage29_blank_revalidated_from_ebd"
                for row in splice_output_rows
            ),
            "single_splice_payload_revalidation_rows": len(splice_output_rows),
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
                "remaining_unknown_residuals_discarded": False,
                "dialogue_or_localized_text_exported": False,
                "legacy_dlc_in_scope": False,
                "translation_or_core_files_modified": False,
            },
            "next_action": (
                "Upload this metadata report. If every proposed profile reproduces its stage-29 hash, preserves all "
                "non-selected residual-shape counters and reverse-roundtrips exactly, prepare one separate checksum-gated "
                "PACK11 repack test per profile. Keep all profiles inactive and runtime-unvalidated."
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
        raise BacklogPrototypeError(f"project root does not exist: {project_root}")
    output, summary = build_prototypes(
        project_root=project_root,
        workspace_root=workspace_root,
        report_root=report_root,
        maximum_event_bytes=args.maximum_event_bytes,
    )
    print(f"Proposed stage-40 groups: {summary['proposed_group_rows']}")
    print(f"Local experimental profiles built: {summary['promoted_profile_rows']}")
    print(f"Candidate EBD files: {summary['prototype_file_rows']}")
    print(f"Validation failures: {summary['validation_failures']}")
    print("Runtime testing deferred: true")
    print(f"Report: {output}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except BacklogPrototypeError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
