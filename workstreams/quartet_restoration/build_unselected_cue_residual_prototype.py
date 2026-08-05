#!/usr/bin/env python3
"""Build one local metadata-gated fe13_090 prototype from the stage-51 splice evidence."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import struct
import subprocess
import sys
import tempfile
from collections import Counter
from pathlib import Path, PurePosixPath
from typing import Any, Iterable, Mapping, Sequence

import collect_presentation_event_subset_search_evidence as subset
import collect_complex_repeated_shape_subset_evidence as complex_stage

TOOL_VERSION = "0.0.60"
TARGET_EVENT_PATH = "event/event_jp/fe13/event_fe13_090.ebd"
TARGET_SHAPE_ID = "8330c2a15d46ecd6f1a7ca60bd51696b69f69e9bc415c568e9610b1cc5ce8be7"
PROFILE_ID = "candidate_unselected_cue_residual_fe13_090_8330c2a15d46"
REPORT_NAME = "BR_quartet_restoration_unselected_cue_residual_prototype_evidence.tar.zst"
EVIDENCE_DIR_NAME = "unselected_cue_residual_prototype_evidence"
STAGE51_DIR = "unselected_cue_residual_splice_evidence"
STAGE51_ARCHIVE = "BR_quartet_restoration_unselected_cue_residual_splice_evidence.tar.zst"
PROTOTYPE_SUBDIR = Path("prototypes/unselected_cue_residual")


class UnselectedCuePrototypeError(RuntimeError):
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


def read_tsv(path: Path, *, required: bool = True) -> list[dict[str, str]]:
    return subset.read_tsv(path, required=required)


def write_tsv(path: Path, fields: Sequence[str], rows: Iterable[Mapping[str, object]]) -> None:
    subset.write_tsv(path, fields, rows)


def load_json(path: Path) -> dict[str, Any]:
    return subset.load_json(path)


def safe_member_name(raw: str) -> str:
    path = PurePosixPath(raw)
    if path.is_absolute() or not path.parts or ".." in path.parts:
        raise UnselectedCuePrototypeError(f"unsafe report archive member: {raw}")
    return path.as_posix()


def extract_report(archive: Path, destination: Path) -> Path:
    if not archive.is_file():
        raise UnselectedCuePrototypeError(f"missing prerequisite report: {archive}")
    listed = subprocess.run(
        ["tar", "--zstd", "-tf", str(archive)], text=True,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    if listed.returncode:
        raise UnselectedCuePrototypeError(f"cannot list {archive}: {listed.stderr.strip()}")
    roots = {PurePosixPath(safe_member_name(line.strip())).parts[0] for line in listed.stdout.splitlines() if line.strip()}
    if len(roots) != 1:
        raise UnselectedCuePrototypeError(f"expected one report root in {archive}, found {sorted(roots)}")
    destination.mkdir(parents=True, exist_ok=True)
    done = subprocess.run(
        ["tar", "--zstd", "-xf", str(archive), "-C", str(destination)], text=True,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    if done.returncode:
        raise UnselectedCuePrototypeError(f"cannot extract {archive}: {done.stderr.strip()}")
    return destination / next(iter(roots))


def locate_stage51(report_root: Path, temporary: Path) -> Path:
    direct = report_root / STAGE51_DIR
    return direct if direct.is_dir() else extract_report(report_root / STAGE51_ARCHIVE, temporary / "stage51")


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
        text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    if done.returncode:
        raise UnselectedCuePrototypeError(f"cannot create report archive: {done.stderr.strip()}")
    os.replace(temporary, output)


def byte_difference_count(left: bytes, right: bytes) -> int:
    return subset.byte_difference_count(left, right)


def shape_counter(br: Any, source_profile: Mapping[str, object], target_profile: Mapping[str, object]) -> Counter[str]:
    return Counter(br.event_residual_delta_shape_id(row) for row in br.compare_ebd_tag_atoms(source_profile["atoms"], target_profile["atoms"]))


def reconstruct_candidate(br: Any, source_payload: bytes, target_payload: bytes) -> tuple[bytes, bytes, dict[str, Any], list[dict[str, Any]]]:
    source_header = br.parse_ebd_header_schema(source_payload)
    target_header = br.parse_ebd_header_schema(target_payload)
    if source_header.get("classification") != "observed_ebd_name_description_header":
        raise UnselectedCuePrototypeError("source EBD header is not recognized")
    if target_header.get("classification") != "observed_ebd_name_description_header":
        raise UnselectedCuePrototypeError("target EBD header is not recognized")
    source_profile = br.profile_ebd_post_header_words(
        source_payload, int(source_header["header_end"]), maximum_words=max(1, len(source_payload) // 4 + 8)
    )
    target_profile = br.profile_ebd_post_header_words(
        target_payload, int(target_header["header_end"]), maximum_words=max(1, len(target_payload) // 4 + 8)
    )
    deltas = br.compare_ebd_tag_atoms(source_profile["atoms"], target_profile["atoms"])
    matches = [row for row in deltas if br.event_residual_delta_shape_id(row) == TARGET_SHAPE_ID]
    if len(matches) != 1:
        raise UnselectedCuePrototypeError(f"expected one reproducible target occurrence, found {len(matches)}")
    delta = matches[0]
    source_start, source_end = br.event_atom_word_span(
        source_profile["atoms"], int(delta["source_atom_start"]), int(delta["source_atom_end"]), int(source_profile["word_count"])
    )
    target_start, target_end = br.event_atom_word_span(
        target_profile["atoms"], int(delta["target_atom_start"]), int(delta["target_atom_end"]), int(target_profile["word_count"])
    )
    source_span = list(source_profile["words"])[source_start:source_end]
    target_span = list(target_profile["words"])[target_start:target_end]
    candidate_words = list(target_profile["words"])
    candidate_words[target_start:target_end] = source_span
    target_words_end = int(target_header["header_end"]) + int(target_profile["word_count"]) * 4
    candidate = (
        target_payload[:int(target_header["header_end"])]
        + (struct.pack(f"<{len(candidate_words)}I", *candidate_words) if candidate_words else b"")
        + target_payload[target_words_end:]
    )
    candidate_header = br.parse_ebd_header_schema(candidate)
    candidate_profile = br.profile_ebd_post_header_words(
        candidate, int(candidate_header.get("header_end", 0)), maximum_words=max(1, len(candidate) // 4 + 8)
    )
    reverse_words = list(candidate_profile["words"])
    reverse_words[target_start:target_start + len(source_span)] = target_span
    candidate_words_end = int(candidate_header["header_end"]) + int(candidate_profile["word_count"]) * 4
    reversed_payload = (
        target_payload[:int(target_header["header_end"])]
        + (struct.pack(f"<{len(reverse_words)}I", *reverse_words) if reverse_words else b"")
        + candidate[candidate_words_end:]
    )
    before = shape_counter(br, source_profile, target_profile)
    after = shape_counter(br, source_profile, candidate_profile)
    before_other = before.copy(); after_other = after.copy()
    before_other.pop(TARGET_SHAPE_ID, None); after_other.pop(TARGET_SHAPE_ID, None)
    target_distance = byte_difference_count(target_payload, source_payload)
    candidate_distance = byte_difference_count(candidate, source_payload)
    checks = {
        "target_shape_count_reduced_exactly_once": before.get(TARGET_SHAPE_ID, 0) == 1 and after.get(TARGET_SHAPE_ID, 0) == 0,
        "all_other_residual_counters_preserved": before_other == after_other,
        "no_new_residual_shapes": not (set(after) - set(before)),
        "quartet_header_preserved": candidate[:int(target_header["header_end"])] == target_payload[:int(target_header["header_end"])],
        "quartet_trailing_bytes_preserved": candidate[candidate_words_end:] == target_payload[target_words_end:],
        "exact_target_reverse_roundtrip": reversed_payload == target_payload,
        "candidate_not_farther_from_original": candidate_distance <= target_distance,
        "strict_improvement": candidate_distance < target_distance,
    }
    residuals = [
        {
            "shape_id": br.event_residual_delta_shape_id(row),
            "sequence_tag": row.get("sequence_tag", ""),
            "source_atom_count": row.get("source_atom_count", ""),
            "target_atom_count": row.get("target_atom_count", ""),
        }
        for row in br.compare_ebd_tag_atoms(source_profile["atoms"], candidate_profile["atoms"])
    ]
    metadata = {
        "candidate_sha256": hashlib.sha256(candidate).hexdigest(),
        "candidate_size": len(candidate),
        "target_distance_to_source": target_distance,
        "candidate_distance_to_source": candidate_distance,
        "distance_improvement": target_distance - candidate_distance,
        "source_span_start_word_index": source_start,
        "source_span_end_word_index": source_end,
        "target_span_start_word_index": target_start,
        "target_span_end_word_index": target_end,
        "source_span_word_count": len(source_span),
        "target_span_word_count": len(target_span),
        "remaining_residual_rows": len(residuals),
        "checks": checks,
    }
    return candidate, reversed_payload, metadata, residuals


def validate_stage51(source_root: Path) -> tuple[dict[str, Any], dict[str, str], list[dict[str, str]], Counter[str]]:
    summary = load_json(source_root / "SUMMARY.json")
    if summary.get("type") != "br_quartet_restoration_unselected_cue_residual_splice_evidence_summary":
        raise UnselectedCuePrototypeError("unexpected stage-51 report type")
    if summary.get("tool_version") != "0.0.59":
        raise UnselectedCuePrototypeError("stage-51 report must use tool version 0.0.59")
    expected_counts = {
        "target_event_rows": 1,
        "analyzed_event_rows": 1,
        "promotable_event_rows": 1,
        "validation_rows": 9,
        "validation_failures": 0,
        "remaining_residual_rows": 2,
        "skipped_rows": 0,
    }
    for key, expected in expected_counts.items():
        if parse_int(summary.get(key), -1) != expected:
            raise UnselectedCuePrototypeError(f"stage-51 {key} must be {expected}")
    events = read_tsv(source_root / "UNSELECTED_CUE_RESIDUAL_EVENTS.tsv")
    if len(events) != 1:
        raise UnselectedCuePrototypeError("expected exactly one stage-51 event row")
    event = events[0]
    if normalize_event_member(event.get("normalized_path")) != TARGET_EVENT_PATH or event.get("shape_id") != TARGET_SHAPE_ID:
        raise UnselectedCuePrototypeError("stage-51 target event or shape changed")
    if event.get("classification") != "unselected_cue_residual_strict_improvement_ready_for_local_prototype":
        raise UnselectedCuePrototypeError("stage-51 event is not marked ready for local prototype")
    if not parse_bool(event.get("safe_to_build_separate_local_profile")):
        raise UnselectedCuePrototypeError("stage-51 safe-to-build flag is false")
    tests = read_tsv(source_root / "UNSELECTED_CUE_RESIDUAL_SPLICE_TESTS.tsv")
    if len(tests) != 9 or any(not parse_bool(row.get("passed")) for row in tests):
        raise UnselectedCuePrototypeError("stage-51 splice validations are incomplete or failed")
    remaining = read_tsv(source_root / "UNSELECTED_CUE_RESIDUAL_REMAINING.tsv")
    remaining_counter = Counter(str(row.get("shape_id", "")) for row in remaining)
    if len(remaining) != 2 or not all(remaining_counter.values()):
        raise UnselectedCuePrototypeError("stage-51 remaining residual evidence is incomplete")
    skipped = read_tsv(source_root / "UNSELECTED_CUE_RESIDUAL_SKIPPED.tsv")
    if skipped:
        raise UnselectedCuePrototypeError("stage-51 report contains skipped rows")
    return summary, event, tests, remaining_counter


def build(*, project_root: Path, workspace_root: Path, report_root: Path, maximum_event_bytes: int) -> tuple[Path, dict[str, Any]]:
    sys.path.insert(0, str(project_root / "Blue_Reflection_Text_Tool"))
    try:
        import br_restoration_tool as br
    finally:
        sys.path.pop(0)
    with tempfile.TemporaryDirectory(prefix="br-stage52-") as temporary_raw:
        temporary = Path(temporary_raw)
        source_root = locate_stage51(report_root, temporary)
        stage51_summary, stage51_event, _stage51_tests, stage51_remaining = validate_stage51(source_root)
        owners = complex_stage.load_registry_event_owners(project_root)
        if TARGET_EVENT_PATH in owners:
            raise UnselectedCuePrototypeError(f"target event is already covered by profiles: {owners[TARGET_EVENT_PATH]}")
        differences = br.load_report_jsons(report_root, "differences")
        event_report = next((row for row in differences if str(row.get("source_archive_group", "")) == "br1_events"), None)
        if event_report is None:
            raise UnselectedCuePrototypeError("missing br1_events difference report")
        entry = next(
            (row for row in event_report.get("entries", [])
             if normalize_event_member(row.get("normalized_path")) == TARGET_EVENT_PATH
             and row.get("scope_status") == "in_scope" and row.get("source") and row.get("target")),
            None,
        )
        if entry is None:
            raise UnselectedCuePrototypeError("missing in-scope difference entry for fe13_090")
        source_ref = entry["source"]; target_ref = entry["target"]
        source_path = br.inventory_workspace_file(workspace_root, "source", "br1_events", str(source_ref.get("archive", "")), str(source_ref.get("path", "")))
        target_path = br.inventory_workspace_file(workspace_root, "target", "br1_events", str(target_ref.get("archive", "")), str(target_ref.get("path", "")))

        profile_rows: list[dict[str, object]] = []
        file_rows: list[dict[str, object]] = []
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
            source_payload = source_path.read_bytes(); target_payload = target_path.read_bytes()
            source_sha = hashlib.sha256(source_payload).hexdigest(); target_sha = hashlib.sha256(target_payload).hexdigest()
            if source_ref.get("sha256") and source_sha != str(source_ref.get("sha256")):
                skipped_rows.append({"profile_id": PROFILE_ID, "normalized_path": TARGET_EVENT_PATH, "reason": "source_payload_sha256_mismatch"})
            elif target_ref.get("sha256") and target_sha != str(target_ref.get("sha256")):
                skipped_rows.append({"profile_id": PROFILE_ID, "normalized_path": TARGET_EVENT_PATH, "reason": "target_payload_sha256_mismatch"})
            else:
                candidate, reversed_payload, metadata, rebuilt_residuals = reconstruct_candidate(br, source_payload, target_payload)
                rebuilt_counter = Counter(str(row.get("shape_id", "")) for row in rebuilt_residuals)
                checks = {
                    "stage51_report_ready_for_local_prototype": stage51_event.get("classification") == "unselected_cue_residual_strict_improvement_ready_for_local_prototype",
                    "candidate_sha256_matches_stage51": metadata["candidate_sha256"] == stage51_event.get("candidate_sha256"),
                    "target_distance_matches_stage51": metadata["target_distance_to_source"] == parse_int(stage51_event.get("target_distance_to_source"), -1),
                    "candidate_distance_matches_stage51": metadata["candidate_distance_to_source"] == parse_int(stage51_event.get("candidate_distance_to_source"), -1),
                    "distance_improvement_matches_stage51": metadata["distance_improvement"] == parse_int(stage51_event.get("distance_improvement"), -1),
                    "remaining_residual_count_matches_stage51": metadata["remaining_residual_rows"] == parse_int(stage51_event.get("remaining_residual_rows"), -1),
                    "remaining_residual_multiset_matches_stage51": rebuilt_counter == stage51_remaining,
                    "exact_target_reverse_roundtrip": reversed_payload == target_payload,
                    **metadata["checks"],
                }
                for name, passed in checks.items():
                    validation_rows.append({
                        "profile_id": PROFILE_ID, "normalized_path": TARGET_EVENT_PATH,
                        "check_name": name, "passed": passed,
                        "review_status": "static_metadata_gate_not_runtime_validation",
                    })
                if not all(checks.values()):
                    skipped_rows.append({"profile_id": PROFILE_ID, "normalized_path": TARGET_EVENT_PATH, "reason": "one_or_more_prototype_validation_gates_failed"})
                else:
                    profile_dir = prototype_root / PROFILE_ID
                    local_relative = PurePosixPath("payload") / PurePosixPath(TARGET_EVENT_PATH)
                    candidate_path = profile_dir / Path(local_relative.as_posix())
                    atomic_bytes(candidate_path, candidate)
                    manifest = {
                        "type": "br_quartet_restoration_local_unselected_cue_residual_prototype",
                        "format_version": 1,
                        "tool_version": TOOL_VERSION,
                        "profile_id": PROFILE_ID,
                        "profile_classification": "experimental_single_scene_unselected_cue_residual_candidate",
                        "prototype_confidence": "experimental_metadata_gated",
                        "runtime_validated": False,
                        "censorship_semantics_assigned": False,
                        "installed_game_files_modified": False,
                        "installable_package_generated": False,
                        "cue_domains": stage51_event.get("cue_domains", ""),
                        "files": [{
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
                            "target_size": len(target_payload),
                            "candidate_size": len(candidate),
                            "selected_shape_id": TARGET_SHAPE_ID,
                            "remaining_residual_rows": len(rebuilt_residuals),
                            "target_byte_difference_to_source": metadata["target_distance_to_source"],
                            "candidate_byte_difference_to_source": metadata["candidate_distance_to_source"],
                            "distance_improvement": metadata["distance_improvement"],
                        }],
                    }
                    atomic_json(profile_dir / "PROTOTYPE.json", manifest)
                    profile_rows.append({
                        "profile_id": PROFILE_ID,
                        "profile_classification": manifest["profile_classification"],
                        "prototype_confidence": manifest["prototype_confidence"],
                        "event_count": 1,
                        "event_paths": TARGET_EVENT_PATH,
                        "selected_shape_id": TARGET_SHAPE_ID,
                        "remaining_residual_rows": len(rebuilt_residuals),
                        "cue_domains": stage51_event.get("cue_domains", ""),
                        "distance_improvement": metadata["distance_improvement"],
                        "local_profile_root": str(profile_dir.relative_to(project_root)) if profile_dir.is_relative_to(project_root) else str(profile_dir),
                        "validation_status": "passed",
                        "runtime_validated": False,
                        "review_status": "separate_experimental_local_unselected_cue_profile_not_repacked_not_installed",
                    })
                    file_rows.append({
                        "profile_id": PROFILE_ID, "normalized_path": TARGET_EVENT_PATH,
                        "source_archive": source_ref.get("archive", ""), "source_member_path": source_ref.get("path", ""),
                        "target_archive": target_ref.get("archive", ""), "target_member_path": target_ref.get("path", ""),
                        "source_sha256": source_sha, "target_sha256": target_sha,
                        "candidate_sha256": metadata["candidate_sha256"],
                        "source_size": len(source_payload), "target_size": len(target_payload), "candidate_size": len(candidate),
                        "target_distance_to_source": metadata["target_distance_to_source"],
                        "candidate_distance_to_source": metadata["candidate_distance_to_source"],
                        "distance_improvement": metadata["distance_improvement"],
                        "candidate_relative_path": local_relative.as_posix(),
                    })
                    for row in rebuilt_residuals:
                        residual_rows.append({"profile_id": PROFILE_ID, "normalized_path": TARGET_EVENT_PATH, **row, "review_status": "remaining_residual_not_assigned_semantics"})

        outdir = report_root / EVIDENCE_DIR_NAME
        if outdir.exists():
            shutil.rmtree(outdir)
        outdir.mkdir(parents=True)
        write_tsv(outdir / "UNSELECTED_CUE_RESIDUAL_PROTOTYPE_PROFILES.tsv", [
            "profile_id", "profile_classification", "prototype_confidence", "event_count", "event_paths",
            "selected_shape_id", "remaining_residual_rows", "cue_domains", "distance_improvement",
            "local_profile_root", "validation_status", "runtime_validated", "review_status",
        ], profile_rows)
        write_tsv(outdir / "UNSELECTED_CUE_RESIDUAL_PROTOTYPE_FILES.tsv", [
            "profile_id", "normalized_path", "source_archive", "source_member_path", "target_archive", "target_member_path",
            "source_sha256", "target_sha256", "candidate_sha256", "source_size", "target_size", "candidate_size",
            "target_distance_to_source", "candidate_distance_to_source", "distance_improvement", "candidate_relative_path",
        ], file_rows)
        write_tsv(outdir / "UNSELECTED_CUE_RESIDUAL_PROTOTYPE_REMAINING.tsv", [
            "profile_id", "normalized_path", "shape_id", "sequence_tag", "source_atom_count", "target_atom_count", "review_status",
        ], residual_rows)
        write_tsv(outdir / "UNSELECTED_CUE_RESIDUAL_PROTOTYPE_VALIDATIONS.tsv", [
            "profile_id", "normalized_path", "check_name", "passed", "review_status",
        ], validation_rows)
        write_tsv(outdir / "UNSELECTED_CUE_RESIDUAL_PROTOTYPE_SKIPPED.tsv", [
            "profile_id", "normalized_path", "reason",
        ], skipped_rows)
        summary = {
            "type": "br_quartet_restoration_unselected_cue_residual_prototype_evidence_summary",
            "format_version": 1,
            "tool_version": TOOL_VERSION,
            "source_stage51_tool_version": stage51_summary.get("tool_version"),
            "status": "separate_unselected_cue_residual_prototype_built_roundtrip_validated_not_repacked_or_installed" if profile_rows else "unselected_cue_residual_prototype_not_built",
            "proposed_profile_rows": 1,
            "promoted_profile_rows": len(profile_rows),
            "prototype_file_rows": len(file_rows),
            "remaining_residual_rows": len(residual_rows),
            "validation_rows": len(validation_rows),
            "validation_failures": sum(not parse_bool(row.get("passed")) for row in validation_rows),
            "skipped_rows": len(skipped_rows),
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
                "legacy_dlc_in_scope": False,
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
        output, summary = build(project_root=project_root, workspace_root=workspace_root, report_root=report_root, maximum_event_bytes=args.maximum_event_bytes)
    except (UnselectedCuePrototypeError, subset.SubsetSearchError, OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print(f"Unselected cue profiles built: {summary['promoted_profile_rows']}")
    print(f"Prototype validation failures: {summary['validation_failures']}")
    print(f"Report: {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
