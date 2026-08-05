#!/usr/bin/env python3
"""Build the exact best stage-59 fe13_090 remaining-residual prototype locally.

The prototype starts from the canonical stage-51 candidate, removes both still
unassigned insert residuals selected by stage 59, and must reproduce the exact
stage-59 SHA-256, 39-byte distance to Original and full reverse chain back to
stage 51 and current Quartet.  It writes only under .local/build and emits a
metadata report; it does not repack PACK11, modify the registry or touch the
installed game.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from collections import Counter
from pathlib import Path, PurePosixPath
from typing import Any, Iterable, Mapping, Sequence

import collect_presentation_event_subset_search_evidence as subset
import collect_fe13_remaining_residual_evidence as stage59

TOOL_VERSION = "0.0.69"
TARGET_EVENT_PATH = stage59.TARGET_EVENT_PATH
PRIMARY_SHAPE_ID = stage59.PRIMARY_SHAPE_ID
SELECTED_SHAPE_IDS = stage59.REMAINING_SHAPE_IDS
SOURCE_PROFILE_ID = stage59.REGISTERED_PROFILE_ID
PROFILE_ID = "candidate_fe13_090_complete_residual_inverse_9a57d11730c0"
EXPECTED_COMBINATION_ID = "fe13_090_remaining_3"
EXPECTED_CANDIDATE_SHA256 = "9a57d11730c0f952ee0abcb6083efeaec243f87720279997e3dcae5a88bd88c7"
EXPECTED_CANDIDATE_SIZE = 5273
EXPECTED_STAGE51_DISTANCE = 2589
EXPECTED_CANDIDATE_DISTANCE = 39
EXPECTED_IMPROVEMENT_OVER_STAGE51 = 2550
EXPECTED_QUARTET_DISTANCE = 2899
REPORT_NAME = "BR_quartet_restoration_fe13_remaining_residual_prototype_evidence.tar.zst"
EVIDENCE_DIR_NAME = "fe13_remaining_residual_prototype_evidence"
STAGE59_DIR = "fe13_remaining_residual_evidence"
STAGE59_ARCHIVE = "BR_quartet_restoration_fe13_remaining_residual_evidence.tar.zst"
PROTOTYPE_SUBDIR = Path("prototypes/fe13_remaining_residual")


class Fe13RemainingPrototypeError(RuntimeError):
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


def load_json(path: Path) -> dict[str, Any]:
    return subset.load_json(path)


def read_tsv(path: Path, *, required: bool = True) -> list[dict[str, str]]:
    return subset.read_tsv(path, required=required)


def write_tsv(path: Path, fields: Sequence[str], rows: Iterable[Mapping[str, object]]) -> None:
    subset.write_tsv(path, fields, rows)


def safe_member_name(raw: str) -> str:
    path = PurePosixPath(raw)
    if path.is_absolute() or not path.parts or ".." in path.parts:
        raise Fe13RemainingPrototypeError(f"unsafe report archive member: {raw}")
    return path.as_posix()


def extract_report(archive: Path, destination: Path) -> Path:
    if not archive.is_file():
        raise Fe13RemainingPrototypeError(f"missing prerequisite report: {archive}")
    listed = subprocess.run(
        ["tar", "--zstd", "-tf", str(archive)],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if listed.returncode:
        raise Fe13RemainingPrototypeError(f"cannot list {archive}: {listed.stderr.strip()}")
    roots = {
        PurePosixPath(safe_member_name(line.strip())).parts[0]
        for line in listed.stdout.splitlines()
        if line.strip()
    }
    if len(roots) != 1:
        raise Fe13RemainingPrototypeError(
            f"expected one report root in {archive}, found {sorted(roots)}"
        )
    destination.mkdir(parents=True, exist_ok=True)
    done = subprocess.run(
        ["tar", "--zstd", "-xf", str(archive), "-C", str(destination)],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if done.returncode:
        raise Fe13RemainingPrototypeError(f"cannot extract {archive}: {done.stderr.strip()}")
    return destination / next(iter(roots))


def locate_stage59(report_root: Path, temporary: Path) -> Path:
    direct = report_root / STAGE59_DIR
    if direct.is_dir():
        return direct
    return extract_report(report_root / STAGE59_ARCHIVE, temporary / "stage59")


def atomic_bytes(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_bytes(data)
    os.replace(temporary, path)


def atomic_json(path: Path, data: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def make_report_archive(source_dir: Path, output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(output.name + ".tmp")
    temporary.unlink(missing_ok=True)
    done = subprocess.run(
        ["tar", "--zstd", "-cf", str(temporary), "-C", str(source_dir.parent), source_dir.name],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if done.returncode:
        raise Fe13RemainingPrototypeError(f"cannot create report archive: {done.stderr.strip()}")
    os.replace(temporary, output)


def validate_stage59(root: Path) -> tuple[dict[str, Any], dict[str, str], dict[str, str], list[dict[str, str]]]:
    summary = load_json(root / "SUMMARY.json")
    if (
        summary.get("type") != "br_quartet_restoration_fe13_remaining_residual_evidence_summary"
        or summary.get("tool_version") != "0.0.68"
    ):
        raise Fe13RemainingPrototypeError("stage-59 report must be the canonical 0.0.68 report")
    expected_counts = {
        "target_event_rows": 1,
        "analyzed_event_rows": 1,
        "tested_combination_rows": 3,
        "selected_occurrence_rows": 4,
        "promotable_combination_rows": 3,
        "validation_rows": 39,
        "validation_failures": 0,
        "strict_improvement_failures": 0,
        "skipped_rows": 0,
    }
    for key, expected in expected_counts.items():
        if parse_int(summary.get(key), -1) != expected:
            raise Fe13RemainingPrototypeError(f"stage-59 {key} must be {expected}")
    if list(summary.get("remaining_shape_ids", [])) != list(SELECTED_SHAPE_IDS):
        raise Fe13RemainingPrototypeError("stage-59 remaining shape order or set changed")

    events = read_tsv(root / "FE13_REMAINING_RESIDUAL_EVENTS.tsv")
    if len(events) != 1:
        raise Fe13RemainingPrototypeError("stage-59 report must contain exactly one event row")
    event = events[0]
    if (
        normalize_event_member(event.get("normalized_path")) != TARGET_EVENT_PATH
        or event.get("registered_profile_id") != SOURCE_PROFILE_ID
        or event.get("primary_removed_shape_id") != PRIMARY_SHAPE_ID
        or event.get("primary_candidate_sha256") != stage59.PRIMARY_CANDIDATE_SHA256
        or parse_int(event.get("quartet_distance_to_original"), -1) != EXPECTED_QUARTET_DISTANCE
        or parse_int(event.get("stage51_distance_to_original"), -1) != EXPECTED_STAGE51_DISTANCE
        or event.get("best_combination_id") != EXPECTED_COMBINATION_ID
        or event.get("best_selected_shape_ids") != ";".join(SELECTED_SHAPE_IDS)
        or parse_int(event.get("best_candidate_distance_to_original"), -1) != EXPECTED_CANDIDATE_DISTANCE
        or parse_int(event.get("best_distance_improvement_over_stage51"), -1) != EXPECTED_IMPROVEMENT_OVER_STAGE51
        or event.get("best_classification") != "strict_improvement_ready_for_separate_local_prototype"
    ):
        raise Fe13RemainingPrototypeError("stage-59 best fe13_090 result changed")

    combinations = read_tsv(root / "FE13_REMAINING_RESIDUAL_COMBINATIONS.tsv")
    if len(combinations) != 3:
        raise Fe13RemainingPrototypeError("stage-59 report must contain exactly three combinations")
    pair_rows = [row for row in combinations if row.get("combination_id") == EXPECTED_COMBINATION_ID]
    if len(pair_rows) != 1:
        raise Fe13RemainingPrototypeError("stage-59 best pair row is missing or duplicated")
    pair = pair_rows[0]
    if (
        pair.get("selected_shape_ids") != ";".join(SELECTED_SHAPE_IDS)
        or parse_int(pair.get("selected_shape_count"), -1) != 2
        or parse_int(pair.get("stage51_distance_to_original"), -1) != EXPECTED_STAGE51_DISTANCE
        or parse_int(pair.get("candidate_distance_to_original"), -1) != EXPECTED_CANDIDATE_DISTANCE
        or parse_int(pair.get("distance_improvement_over_stage51"), -1) != EXPECTED_IMPROVEMENT_OVER_STAGE51
        or pair.get("candidate_sha256") != EXPECTED_CANDIDATE_SHA256
        or parse_int(pair.get("candidate_size"), -1) != EXPECTED_CANDIDATE_SIZE
        or parse_int(pair.get("remaining_residual_rows"), -1) != 0
        or not parse_bool(pair.get("passes_structural_gates"))
        or not parse_bool(pair.get("strict_improvement"))
        or not parse_bool(pair.get("safe_to_build_separate_local_profile"))
        or pair.get("classification") != "strict_improvement_ready_for_separate_local_prototype"
    ):
        raise Fe13RemainingPrototypeError("stage-59 best pair no longer matches the canonical candidate")

    selected = read_tsv(root / "FE13_REMAINING_RESIDUAL_SELECTED_OCCURRENCES.tsv")
    selected_pair = [row for row in selected if row.get("combination_id") == EXPECTED_COMBINATION_ID]
    if len(selected_pair) != 2 or {row.get("shape_id") for row in selected_pair} != set(SELECTED_SHAPE_IDS):
        raise Fe13RemainingPrototypeError("stage-59 best pair selected occurrences changed")
    for row in selected_pair:
        if (
            parse_int(row.get("occurrence_index"), -1) != 0
            or row.get("sequence_tag") != "insert"
            or parse_int(row.get("source_atom_count"), -1) != 0
            or parse_int(row.get("target_atom_count"), -1) != 1
            or row.get("semantic_status") != "unassigned"
        ):
            raise Fe13RemainingPrototypeError("stage-59 selected occurrence metadata changed")

    tests = read_tsv(root / "FE13_REMAINING_RESIDUAL_TESTS.tsv")
    pair_tests = [row for row in tests if row.get("combination_id") == EXPECTED_COMBINATION_ID]
    if len(tests) != 39 or len(pair_tests) != 13 or any(not parse_bool(row.get("passed")) for row in tests):
        raise Fe13RemainingPrototypeError("stage-59 validations are incomplete or failed")
    if read_tsv(root / "FE13_REMAINING_RESIDUAL_SKIPPED.tsv"):
        raise Fe13RemainingPrototypeError("stage-59 report contains skipped rows")
    return summary, event, pair, pair_tests


def reconstruct_best_candidate(br: Any, source_payload: bytes, quartet_payload: bytes) -> tuple[bytes, dict[str, Any], list[dict[str, Any]]]:
    stage51_candidate, _, _, stage51_operations = stage59.inverse_candidate(
        br=br,
        source_payload=source_payload,
        target_payload=quartet_payload,
        shape_ids=[PRIMARY_SHAPE_ID],
    )
    stage51_sha = hashlib.sha256(stage51_candidate).hexdigest()
    if stage51_sha != stage59.PRIMARY_CANDIDATE_SHA256:
        raise Fe13RemainingPrototypeError(
            f"stage-51 candidate hash mismatch: expected {stage59.PRIMARY_CANDIDATE_SHA256}, got {stage51_sha}"
        )
    candidate, metadata, residuals, final_operations = stage59.inverse_candidate(
        br=br,
        source_payload=source_payload,
        target_payload=stage51_candidate,
        shape_ids=SELECTED_SHAPE_IDS,
    )
    reversed_stage51 = subset.reverse_candidate(
        candidate_payload=candidate,
        target_payload=stage51_candidate,
        operations=final_operations,
        br=br,
    )
    reversed_quartet = subset.reverse_candidate(
        candidate_payload=reversed_stage51,
        target_payload=quartet_payload,
        operations=stage51_operations,
        br=br,
    )
    candidate_sha = hashlib.sha256(candidate).hexdigest()
    candidate_distance = subset.byte_difference_count(candidate, source_payload)
    quartet_distance = subset.byte_difference_count(quartet_payload, source_payload)
    stage51_distance = subset.byte_difference_count(stage51_candidate, source_payload)
    counter = stage59.shape_counter(br, source_payload, candidate)
    checks = {
        "stage51_candidate_sha256_matches_registered_profile": stage51_sha == stage59.PRIMARY_CANDIDATE_SHA256,
        "selected_pair_removed": all(counter.get(shape, 0) == 0 for shape in SELECTED_SHAPE_IDS),
        "no_residual_shapes_remain": counter == Counter(),
        "candidate_sha256_matches_stage59": candidate_sha == EXPECTED_CANDIDATE_SHA256,
        "candidate_size_matches_stage59": len(candidate) == EXPECTED_CANDIDATE_SIZE,
        "quartet_distance_matches_stage59": quartet_distance == EXPECTED_QUARTET_DISTANCE,
        "stage51_distance_matches_stage59": stage51_distance == EXPECTED_STAGE51_DISTANCE,
        "candidate_distance_matches_stage59": candidate_distance == EXPECTED_CANDIDATE_DISTANCE,
        "improvement_over_stage51_matches_stage59": stage51_distance - candidate_distance == EXPECTED_IMPROVEMENT_OVER_STAGE51,
        "strict_improvement_over_stage51": candidate_distance < stage51_distance,
        "strict_improvement_over_quartet": candidate_distance < quartet_distance,
        "exact_stage51_reverse_roundtrip": reversed_stage51 == stage51_candidate,
        "exact_full_quartet_reverse_chain": reversed_quartet == quartet_payload,
        "candidate_header_preserved_from_stage51": parse_bool(metadata.get("candidate_header_preserved_from_target")),
        "candidate_trailing_preserved_from_stage51": parse_bool(metadata.get("candidate_trailing_bytes_preserved_from_target")),
        "candidate_header_valid": metadata.get("candidate_header_classification") == "observed_ebd_name_description_header",
        "no_nonselected_residual_shapes_removed": parse_int(metadata.get("removed_nonselected_coarse_shape_count"), -1) == 0,
    }
    return candidate, {
        "candidate_sha256": candidate_sha,
        "candidate_size": len(candidate),
        "quartet_distance_to_original": quartet_distance,
        "stage51_distance_to_original": stage51_distance,
        "candidate_distance_to_original": candidate_distance,
        "distance_improvement_over_stage51": stage51_distance - candidate_distance,
        "distance_improvement_over_quartet": quartet_distance - candidate_distance,
        "checks": checks,
    }, residuals


def build(*, project_root: Path, workspace_root: Path, report_root: Path, maximum_event_bytes: int) -> tuple[Path, dict[str, Any]]:
    sys.path.insert(0, str(project_root / "Blue_Reflection_Text_Tool"))
    try:
        import br_restoration_tool as br
    finally:
        sys.path.pop(0)

    with tempfile.TemporaryDirectory(prefix="br-stage60-") as temporary_raw:
        temporary = Path(temporary_raw)
        stage59_root = locate_stage59(report_root, temporary)
        stage59_summary, stage59_event, stage59_pair, _stage59_tests = validate_stage59(stage59_root)

        differences = br.load_report_jsons(report_root, "differences")
        event_report = next(
            (row for row in differences if str(row.get("source_archive_group", "")) == "br1_events"),
            None,
        )
        if event_report is None:
            raise Fe13RemainingPrototypeError("missing br1_events difference report")
        entry = next(
            (
                row
                for row in event_report.get("entries", [])
                if normalize_event_member(row.get("normalized_path")) == TARGET_EVENT_PATH
                and row.get("scope_status") == "in_scope"
                and row.get("source")
                and row.get("target")
            ),
            None,
        )
        if entry is None:
            raise Fe13RemainingPrototypeError("missing in-scope difference entry for fe13_090")
        source_ref = entry["source"]
        target_ref = entry["target"]
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

        profile_rows: list[dict[str, object]] = []
        file_rows: list[dict[str, object]] = []
        selected_rows: list[dict[str, object]] = []
        residual_rows: list[dict[str, object]] = []
        validation_rows: list[dict[str, object]] = []
        skipped_rows: list[dict[str, object]] = []
        prototype_root = workspace_root / PROTOTYPE_SUBDIR
        if prototype_root.exists():
            shutil.rmtree(prototype_root)
        prototype_root.mkdir(parents=True, exist_ok=True)

        if not source_path.is_file() or not target_path.is_file():
            skipped_rows.append({"profile_id": PROFILE_ID, "normalized_path": TARGET_EVENT_PATH, "reason": "workspace_event_payload_missing"})
        elif source_path.stat().st_size > maximum_event_bytes or target_path.stat().st_size > maximum_event_bytes:
            skipped_rows.append({"profile_id": PROFILE_ID, "normalized_path": TARGET_EVENT_PATH, "reason": "maximum_event_bytes_exceeded"})
        else:
            source_payload = source_path.read_bytes()
            quartet_payload = target_path.read_bytes()
            source_sha = hashlib.sha256(source_payload).hexdigest()
            target_sha = hashlib.sha256(quartet_payload).hexdigest()
            if source_ref.get("sha256") and source_sha != str(source_ref.get("sha256")):
                skipped_rows.append({"profile_id": PROFILE_ID, "normalized_path": TARGET_EVENT_PATH, "reason": "source_payload_sha256_mismatch"})
            elif target_ref.get("sha256") and target_sha != str(target_ref.get("sha256")):
                skipped_rows.append({"profile_id": PROFILE_ID, "normalized_path": TARGET_EVENT_PATH, "reason": "target_payload_sha256_mismatch"})
            else:
                candidate, metadata, rebuilt_residuals = reconstruct_best_candidate(br, source_payload, quartet_payload)
                checks = {
                    "stage59_report_canonical": stage59_summary.get("tool_version") == "0.0.68",
                    "stage59_best_combination_selected": stage59_event.get("best_combination_id") == EXPECTED_COMBINATION_ID,
                    "stage59_pair_sha256_expected": stage59_pair.get("candidate_sha256") == EXPECTED_CANDIDATE_SHA256,
                    **metadata["checks"],
                }
                for check_name, passed in checks.items():
                    validation_rows.append(
                        {
                            "profile_id": PROFILE_ID,
                            "normalized_path": TARGET_EVENT_PATH,
                            "check_name": check_name,
                            "passed": passed,
                            "review_status": "passed" if passed else "failed",
                        }
                    )
                if not all(checks.values()):
                    skipped_rows.append({"profile_id": PROFILE_ID, "normalized_path": TARGET_EVENT_PATH, "reason": "prototype_validation_failed"})
                else:
                    profile_dir = prototype_root / PROFILE_ID
                    local_relative = Path(TARGET_EVENT_PATH)
                    candidate_path = profile_dir / local_relative
                    atomic_bytes(candidate_path, candidate)
                    manifest = {
                        "type": "br_quartet_restoration_local_prototype",
                        "format_version": 1,
                        "tool_version": TOOL_VERSION,
                        "profile_id": PROFILE_ID,
                        "supersedes_profile_id": SOURCE_PROFILE_ID,
                        "profile_classification": "experimental_single_scene_complete_residual_inverse_candidate",
                        "prototype_confidence": "experimental_metadata_gated",
                        "runtime_validated": False,
                        "censorship_semantics_assigned": False,
                        "installed_game_files_modified": False,
                        "installable_package_generated": False,
                        "cue_domains": "clothing_state;costume_or_coverage",
                        "files": [
                            {
                                "normalized_path": TARGET_EVENT_PATH,
                                "candidate_relative_path": local_relative.as_posix(),
                                "source_archive": source_ref.get("archive", ""),
                                "source_member_path": source_ref.get("path", ""),
                                "target_archive": target_ref.get("archive", ""),
                                "target_member_path": target_ref.get("path", ""),
                                "source_sha256": source_sha,
                                "target_sha256": target_sha,
                                "candidate_sha256": metadata["candidate_sha256"],
                                "source_size": len(source_payload),
                                "target_size": len(quartet_payload),
                                "candidate_size": len(candidate),
                                "primary_shape_id": PRIMARY_SHAPE_ID,
                                "selected_remaining_shape_ids": list(SELECTED_SHAPE_IDS),
                                "remaining_residual_rows": len(rebuilt_residuals),
                                "quartet_byte_difference_to_source": metadata["quartet_distance_to_original"],
                                "stage51_byte_difference_to_source": metadata["stage51_distance_to_original"],
                                "candidate_byte_difference_to_source": metadata["candidate_distance_to_original"],
                                "distance_improvement_over_stage51": metadata["distance_improvement_over_stage51"],
                                "distance_improvement_over_quartet": metadata["distance_improvement_over_quartet"],
                            }
                        ],
                    }
                    atomic_json(profile_dir / "PROTOTYPE.json", manifest)
                    profile_rows.append(
                        {
                            "profile_id": PROFILE_ID,
                            "supersedes_profile_id": SOURCE_PROFILE_ID,
                            "profile_classification": manifest["profile_classification"],
                            "prototype_confidence": manifest["prototype_confidence"],
                            "event_count": 1,
                            "event_paths": TARGET_EVENT_PATH,
                            "selected_shape_ids": ";".join(SELECTED_SHAPE_IDS),
                            "remaining_residual_rows": len(rebuilt_residuals),
                            "candidate_distance_to_original": metadata["candidate_distance_to_original"],
                            "distance_improvement_over_stage51": metadata["distance_improvement_over_stage51"],
                            "local_profile_root": str(profile_dir.relative_to(project_root)) if profile_dir.is_relative_to(project_root) else str(profile_dir),
                            "validation_status": "passed",
                            "runtime_validated": False,
                            "review_status": "separate_experimental_local_prototype_not_repacked_not_registered_not_installed",
                        }
                    )
                    file_rows.append(
                        {
                            "profile_id": PROFILE_ID,
                            "normalized_path": TARGET_EVENT_PATH,
                            "source_archive": source_ref.get("archive", ""),
                            "source_member_path": source_ref.get("path", ""),
                            "target_archive": target_ref.get("archive", ""),
                            "target_member_path": target_ref.get("path", ""),
                            "source_sha256": source_sha,
                            "target_sha256": target_sha,
                            "candidate_sha256": metadata["candidate_sha256"],
                            "source_size": len(source_payload),
                            "target_size": len(quartet_payload),
                            "candidate_size": len(candidate),
                            "quartet_distance_to_original": metadata["quartet_distance_to_original"],
                            "stage51_distance_to_original": metadata["stage51_distance_to_original"],
                            "candidate_distance_to_original": metadata["candidate_distance_to_original"],
                            "distance_improvement_over_stage51": metadata["distance_improvement_over_stage51"],
                            "distance_improvement_over_quartet": metadata["distance_improvement_over_quartet"],
                            "candidate_relative_path": local_relative.as_posix(),
                        }
                    )
                    for shape_id in SELECTED_SHAPE_IDS:
                        selected_rows.append(
                            {
                                "profile_id": PROFILE_ID,
                                "normalized_path": TARGET_EVENT_PATH,
                                "shape_id": shape_id,
                                "occurrence_index": 0,
                                "sequence_tag": "insert",
                                "source_atom_count": 0,
                                "target_atom_count": 1,
                                "semantic_status": "unassigned",
                            }
                        )
                    for row in rebuilt_residuals:
                        residual_rows.append(
                            {
                                "profile_id": PROFILE_ID,
                                "normalized_path": TARGET_EVENT_PATH,
                                "shape_id": row.get("shape_id", ""),
                                "sequence_tag": row.get("sequence_tag", ""),
                                "source_atom_count": row.get("source_atom_count", ""),
                                "target_atom_count": row.get("target_atom_count", ""),
                                "review_status": "remaining_residual_not_assigned_semantics",
                            }
                        )

        outdir = report_root / EVIDENCE_DIR_NAME
        if outdir.exists():
            shutil.rmtree(outdir)
        outdir.mkdir(parents=True)
        write_tsv(
            outdir / "FE13_REMAINING_RESIDUAL_PROTOTYPE_PROFILES.tsv",
            [
                "profile_id", "supersedes_profile_id", "profile_classification", "prototype_confidence",
                "event_count", "event_paths", "selected_shape_ids", "remaining_residual_rows",
                "candidate_distance_to_original", "distance_improvement_over_stage51", "local_profile_root",
                "validation_status", "runtime_validated", "review_status",
            ],
            profile_rows,
        )
        write_tsv(
            outdir / "FE13_REMAINING_RESIDUAL_PROTOTYPE_FILES.tsv",
            [
                "profile_id", "normalized_path", "source_archive", "source_member_path", "target_archive",
                "target_member_path", "source_sha256", "target_sha256", "candidate_sha256", "source_size",
                "target_size", "candidate_size", "quartet_distance_to_original", "stage51_distance_to_original",
                "candidate_distance_to_original", "distance_improvement_over_stage51",
                "distance_improvement_over_quartet", "candidate_relative_path",
            ],
            file_rows,
        )
        write_tsv(
            outdir / "FE13_REMAINING_RESIDUAL_PROTOTYPE_SELECTED.tsv",
            [
                "profile_id", "normalized_path", "shape_id", "occurrence_index", "sequence_tag",
                "source_atom_count", "target_atom_count", "semantic_status",
            ],
            selected_rows,
        )
        write_tsv(
            outdir / "FE13_REMAINING_RESIDUAL_PROTOTYPE_REMAINING.tsv",
            [
                "profile_id", "normalized_path", "shape_id", "sequence_tag", "source_atom_count",
                "target_atom_count", "review_status",
            ],
            residual_rows,
        )
        write_tsv(
            outdir / "FE13_REMAINING_RESIDUAL_PROTOTYPE_VALIDATIONS.tsv",
            ["profile_id", "normalized_path", "check_name", "passed", "review_status"],
            validation_rows,
        )
        write_tsv(
            outdir / "FE13_REMAINING_RESIDUAL_PROTOTYPE_SKIPPED.tsv",
            ["profile_id", "normalized_path", "reason"],
            skipped_rows,
        )
        summary = {
            "type": "br_quartet_restoration_fe13_remaining_residual_prototype_evidence_summary",
            "format_version": 1,
            "tool_version": TOOL_VERSION,
            "source_stage59_tool_version": stage59_summary.get("tool_version"),
            "status": "exact_fe13_remaining_residual_prototype_built_not_repacked_or_installed" if profile_rows else "fe13_remaining_residual_prototype_not_built",
            "proposed_profile_rows": 1,
            "promoted_profile_rows": len(profile_rows),
            "prototype_file_rows": len(file_rows),
            "selected_occurrence_rows": len(selected_rows),
            "remaining_residual_rows": len(residual_rows),
            "validation_rows": len(validation_rows),
            "validation_failures": sum(not parse_bool(row.get("passed")) for row in validation_rows),
            "skipped_rows": len(skipped_rows),
            "candidate_sha256": EXPECTED_CANDIDATE_SHA256 if profile_rows else "",
            "candidate_distance_to_original": EXPECTED_CANDIDATE_DISTANCE if profile_rows else None,
            "runtime_testing_deferred": True,
            "policy": {
                "installed_games_modified": False,
                "candidate_ebd_payloads_written_only_under_local_workspace": True,
                "candidate_ebd_payloads_exported_in_report": False,
                "pak_repack_performed": False,
                "profile_manifests_modified": False,
                "activation_or_rollback_invoked": False,
                "runtime_validation_inferred": False,
                "censorship_classification_inferred": False,
                "binary_field_semantics_inferred": False,
                "legacy_dlc_or_removed_content_in_scope": False,
                "source_registered_profile_replaced_or_modified": False,
            },
            "next_action": "Upload this metadata report. Prepare one isolated checksum-gated PACK11 repack test only if promoted_profile_rows is 1 and validation_failures/skipped_rows are 0.",
        }
        atomic_json(outdir / "SUMMARY.json", summary)
        output = report_root / REPORT_NAME
        make_report_archive(outdir, output)
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
    try:
        output, summary = build(
            project_root=project_root,
            workspace_root=workspace_root,
            report_root=report_root,
            maximum_event_bytes=args.maximum_event_bytes,
        )
    except (Fe13RemainingPrototypeError, stage59.Fe13RemainingResidualError, subset.SubsetSearchError, OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print(f"fe13_090 complete-residual prototypes built: {summary['promoted_profile_rows']}")
    print(f"Prototype validation failures: {summary['validation_failures']}")
    print(f"Report: {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
