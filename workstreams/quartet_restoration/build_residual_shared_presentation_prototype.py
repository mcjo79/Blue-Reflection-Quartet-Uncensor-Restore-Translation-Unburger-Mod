#!/usr/bin/env python3
"""Build one local, metadata-gated prototype for the stage-35 shared-presentation shape."""

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
from collections import Counter
from pathlib import Path, PurePosixPath
from typing import Any, Iterable, Mapping, Sequence

WORKSTREAM_ID = "quartet_restoration"
TOOL_VERSION = "0.0.42"
REPORT_NAME = "BR_quartet_restoration_residual_shared_presentation_prototype_evidence.tar.zst"
EVIDENCE_DIR_NAME = "residual_shared_presentation_prototype_evidence"
STAGE35_DIR = "residual_exact_context_evidence"
STAGE35_ARCHIVE = "BR_quartet_restoration_residual_exact_context_evidence.tar.zst"
PROTOTYPE_SUBDIR = "prototypes/residual_shared_presentation"
EXPECTED_SHAPE_ID = "d88c7c3a6f484a28d9ff9662379152bdcdeb4e12fa46d286cc02e3b0bcaabc69"
EXPECTED_PROFILE_ID = "shared_presentation_d88c7c3a6f"
EXPECTED_PATHS = {
    "event/event_jp/ce11/event_ce11_070.ebd",
    "event/event_jp/em01/event_em01_090.ebd",
}


class SharedPresentationPrototypeError(RuntimeError):
    pass


def parse_bool(value: object) -> bool:
    return str(value).strip().casefold() in {"1", "true", "yes", "y"}


def parse_int(value: object, default: int = 0) -> int:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return default


def read_tsv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return [dict(row) for row in csv.DictReader(handle, delimiter="\t")]


def write_tsv(path: Path, fieldnames: Sequence[str], rows: Iterable[Mapping[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fieldnames})


def atomic_json(path: Path, data: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def atomic_bytes(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_bytes(data)
    os.replace(temporary, path)


def safe_member_name(raw: str) -> str:
    path = PurePosixPath(raw)
    if path.is_absolute() or not path.parts or ".." in path.parts:
        raise SharedPresentationPrototypeError(f"unsafe report archive member: {raw}")
    return path.as_posix()


def extract_report(archive: Path, destination: Path) -> None:
    if not archive.is_file():
        raise SharedPresentationPrototypeError(f"missing prerequisite report: {archive}")
    listing = subprocess.run(
        ["tar", "--zstd", "-tf", str(archive)], check=False, text=True,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    if listing.returncode != 0:
        raise SharedPresentationPrototypeError(f"cannot list report {archive}: {listing.stderr.strip()}")
    for line in listing.stdout.splitlines():
        if line.strip():
            safe_member_name(line.strip())
    destination.mkdir(parents=True, exist_ok=True)
    result = subprocess.run(
        ["tar", "--zstd", "-xf", str(archive), "-C", str(destination)],
        check=False, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    if result.returncode != 0:
        raise SharedPresentationPrototypeError(f"cannot extract report {archive}: {result.stderr.strip()}")


def evidence_dir(report_root: Path, temporary_root: Path) -> Path:
    direct = report_root / STAGE35_DIR
    if direct.is_dir():
        return direct
    extraction = temporary_root / STAGE35_DIR
    extract_report(report_root / STAGE35_ARCHIVE, extraction)
    matches = [path for path in extraction.rglob(STAGE35_DIR) if path.is_dir()]
    if len(matches) != 1:
        raise SharedPresentationPrototypeError(
            f"expected one {STAGE35_DIR} directory in {STAGE35_ARCHIVE}, found {len(matches)}"
        )
    return matches[0]


def load_restoration_tool(project_root: Path) -> Any:
    tool_root = project_root / "Blue_Reflection_Text_Tool"
    tool_path = tool_root / "br_restoration_tool.py"
    if not tool_path.is_file():
        raise SharedPresentationPrototypeError(f"missing restoration tool: {tool_path}")
    sys.path.insert(0, str(tool_root))
    try:
        return importlib.import_module("br_restoration_tool")
    finally:
        try:
            sys.path.remove(str(tool_root))
        except ValueError:
            pass


def make_report_archive(source_dir: Path, output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(output.name + ".tmp")
    if temporary.exists():
        temporary.unlink()
    result = subprocess.run(
        ["tar", "--zstd", "-cf", str(temporary), "-C", str(source_dir.parent), source_dir.name],
        check=False, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    if result.returncode != 0:
        raise SharedPresentationPrototypeError(f"cannot create report archive: {result.stderr.strip()}")
    temporary.replace(output)


def byte_difference_count(left: bytes, right: bytes) -> int:
    overlap = min(len(left), len(right))
    return sum(a != b for a, b in zip(left[:overlap], right[:overlap])) + abs(len(left) - len(right))


def shape_counter(br: Any, source_profile: Mapping[str, object], target_profile: Mapping[str, object]) -> Counter[str]:
    deltas = br.compare_ebd_tag_atoms(source_profile["atoms"], target_profile["atoms"])
    return Counter(br.event_residual_delta_shape_id(row) for row in deltas)


def construct_exact_inverse_candidate(
    *, br: Any, source_payload: bytes, target_payload: bytes, occurrence: Mapping[str, object],
) -> tuple[bytes, dict[str, object]]:
    source_header = br.parse_ebd_header_schema(source_payload)
    target_header = br.parse_ebd_header_schema(target_payload)
    if source_header.get("classification") != "observed_ebd_name_description_header":
        raise SharedPresentationPrototypeError("source EBD header is not recognized")
    if target_header.get("classification") != "observed_ebd_name_description_header":
        raise SharedPresentationPrototypeError("target EBD header is not recognized")

    source_profile = br.profile_ebd_post_header_words(source_payload, int(source_header["header_end"]))
    target_profile = br.profile_ebd_post_header_words(target_payload, int(target_header["header_end"]))
    source_words = list(source_profile["words"])
    target_words = list(target_profile["words"])
    source_start = parse_int(occurrence.get("source_span_start_word_index"), -1)
    source_end = parse_int(occurrence.get("source_span_end_word_index"), -1)
    target_start = parse_int(occurrence.get("target_span_start_word_index"), -1)
    target_end = parse_int(occurrence.get("target_span_end_word_index"), -1)
    if not (0 <= source_start <= source_end <= len(source_words)):
        raise SharedPresentationPrototypeError("source exact span escapes EBD post-header words")
    if not (0 <= target_start <= target_end <= len(target_words)):
        raise SharedPresentationPrototypeError("target exact span escapes EBD post-header words")

    source_span = source_words[source_start:source_end]
    target_span = target_words[target_start:target_end]
    candidate_words = target_words[:target_start] + source_span + target_words[target_end:]
    target_header_end = int(target_header["header_end"])
    target_word_bytes_end = target_header_end + int(target_profile["word_count"]) * 4
    target_trailing = target_payload[target_word_bytes_end:]
    candidate_payload = (
        target_payload[:target_header_end]
        + (struct.pack(f"<{len(candidate_words)}I", *candidate_words) if candidate_words else b"")
        + target_trailing
    )

    candidate_header = br.parse_ebd_header_schema(candidate_payload)
    candidate_profile = br.profile_ebd_post_header_words(
        candidate_payload, int(candidate_header.get("header_end", 0)),
        maximum_words=max(1, len(candidate_words) + 8),
    )
    before = shape_counter(br, source_profile, target_profile)
    after = shape_counter(br, source_profile, candidate_profile)
    shape_id = str(occurrence.get("shape_id", ""))
    other_before = before.copy()
    other_after = after.copy()
    selected_before = other_before.pop(shape_id, 0)
    selected_after = other_after.pop(shape_id, 0)

    candidate_insert_end = target_start + len(source_span)
    rebuilt_words = list(candidate_words)
    rebuilt_words[target_start:candidate_insert_end] = target_span
    rebuilt_target = (
        target_payload[:target_header_end]
        + (struct.pack(f"<{len(rebuilt_words)}I", *rebuilt_words) if rebuilt_words else b"")
        + target_trailing
    )
    candidate_word_bytes_end = target_header_end + len(candidate_words) * 4
    source_span_bytes = struct.pack(f"<{len(source_span)}I", *source_span) if source_span else b""
    target_span_bytes = struct.pack(f"<{len(target_span)}I", *target_span) if target_span else b""

    metadata: dict[str, object] = {
        "source_span_start_word_index": source_start,
        "source_span_end_word_index": source_end,
        "target_span_start_word_index": target_start,
        "target_span_end_word_index": target_end,
        "source_span_word_count": len(source_span),
        "target_span_word_count": len(target_span),
        "source_span_sha256": hashlib.sha256(source_span_bytes).hexdigest(),
        "target_span_sha256": hashlib.sha256(target_span_bytes).hexdigest(),
        "candidate_sha256": hashlib.sha256(candidate_payload).hexdigest(),
        "candidate_size": len(candidate_payload),
        "target_size": len(target_payload),
        "candidate_size_delta": len(candidate_payload) - len(target_payload),
        "selected_shape_count_before": selected_before,
        "selected_shape_count_after": selected_after,
        "selected_occurrence_removed": selected_before > 0 and selected_after == selected_before - 1,
        "other_residual_shape_counter_unchanged": other_before == other_after,
        "other_residual_shape_count_before": sum(other_before.values()),
        "other_residual_shape_count_after": sum(other_after.values()),
        "target_header_preserved": candidate_payload[:target_header_end] == target_payload[:target_header_end],
        "target_trailing_bytes_preserved": candidate_payload[candidate_word_bytes_end:] == target_trailing,
        "candidate_header_valid": candidate_header.get("classification") == "observed_ebd_name_description_header",
        "candidate_post_header_family": candidate_profile.get("family", ""),
        "target_roundtrip_exact": rebuilt_target == target_payload,
        "target_prefix_preserved": candidate_payload[:target_header_end + target_start * 4]
            == target_payload[:target_header_end + target_start * 4],
        "target_suffix_preserved": candidate_payload[target_header_end + candidate_insert_end * 4:candidate_word_bytes_end]
            == target_payload[target_header_end + target_end * 4:target_word_bytes_end],
        "target_byte_difference_to_source": byte_difference_count(target_payload, source_payload),
        "candidate_byte_difference_to_source": byte_difference_count(candidate_payload, source_payload),
    }
    return candidate_payload, metadata


def validate_stage35(stage35: Path) -> tuple[dict[str, str], list[dict[str, str]], dict[tuple[str, int], dict[str, str]], dict[str, object]]:
    summary = json.loads((stage35 / "SUMMARY.json").read_text(encoding="utf-8"))
    if summary.get("type") != "br_quartet_restoration_residual_exact_context_evidence_summary":
        raise SharedPresentationPrototypeError("invalid stage-35 residual exact-context summary")
    if str(summary.get("tool_version", "")) != "0.0.41":
        raise SharedPresentationPrototypeError(f"stage-35 tool version must be 0.0.41, got {summary.get('tool_version')}")
    eligible = list(summary.get("stage36_eligible_shape_ids", []))
    if eligible != [EXPECTED_SHAPE_ID]:
        raise SharedPresentationPrototypeError(
            "stage-35 eligible shape set changed; expected only " + EXPECTED_SHAPE_ID
        )

    gates = read_tsv(stage35 / "RESIDUAL_SHAPE_PROMOTION_GATES.tsv")
    gate_rows = [row for row in gates if row.get("stage36_gate") == "eligible_for_stage_36_local_prototype_review"]
    if len(gate_rows) != 1 or gate_rows[0].get("shape_id") != EXPECTED_SHAPE_ID:
        raise SharedPresentationPrototypeError("stage-35 promotion gate does not contain exactly the expected shared-presentation shape")
    gate = gate_rows[0]
    if gate.get("stage35_classification") != "shared_presentation_exact_span_prototype_candidate":
        raise SharedPresentationPrototypeError("stage-35 shared-presentation classification changed")
    if parse_int(gate.get("noncue_occurrence_count")) != 0 or parse_int(gate.get("route_family_count")) < 2:
        raise SharedPresentationPrototypeError("stage-35 shape no longer has cue-only cross-route support")
    if not parse_bool(gate.get("all_splices_isolated")):
        raise SharedPresentationPrototypeError("stage-35 shape no longer has all isolated inverse splices")

    occurrences = [
        row for row in read_tsv(stage35 / "RESIDUAL_EXACT_CONTEXT_OCCURRENCES.tsv")
        if row.get("shape_id") == EXPECTED_SHAPE_ID
    ]
    if {row.get("normalized_path", "") for row in occurrences} != EXPECTED_PATHS:
        raise SharedPresentationPrototypeError("stage-35 occurrence paths changed from the two reviewed cue-positive events")
    if len(occurrences) != 2 or not all(parse_bool(row.get("cue_positive_occurrence")) for row in occurrences):
        raise SharedPresentationPrototypeError("stage-35 shared-presentation occurrences must be exactly two cue-positive rows")

    splice_rows = {
        (row.get("normalized_path", ""), parse_int(row.get("occurrence_index"))): row
        for row in read_tsv(stage35 / "RESIDUAL_IN_MEMORY_SPLICE_VALIDATION.tsv")
        if row.get("shape_id") == EXPECTED_SHAPE_ID
    }
    if len(splice_rows) != 2:
        raise SharedPresentationPrototypeError("stage-35 splice validation must contain exactly two rows")
    for key, row in splice_rows.items():
        if row.get("splice_status") != "isolated_exact_inverse_splice_passed":
            raise SharedPresentationPrototypeError(f"stage-35 splice is not isolated for {key[0]}")
        if not parse_bool(row.get("selected_occurrence_removed")) or not parse_bool(row.get("other_residual_shape_counter_unchanged")):
            raise SharedPresentationPrototypeError(f"stage-35 splice isolation flags changed for {key[0]}")
        if not parse_bool(row.get("target_header_preserved")) or not parse_bool(row.get("target_trailing_bytes_preserved")):
            raise SharedPresentationPrototypeError(f"stage-35 container invariants changed for {key[0]}")
    return gate, occurrences, splice_rows, summary


def build_residual_shared_presentation_prototype(
    *, project_root: Path, workspace_root: Path, report_root: Path,
    maximum_event_bytes: int = 2 * 1024 * 1024,
) -> tuple[Path, dict[str, object]]:
    br = load_restoration_tool(project_root)
    with tempfile.TemporaryDirectory(prefix="br-shared-presentation-") as temporary:
        stage35 = evidence_dir(report_root, Path(temporary))
        gate, occurrences, stage35_splices, stage35_summary = validate_stage35(stage35)

        difference_reports = br.load_report_jsons(report_root, "differences")
        event_report = next(
            (row for row in difference_reports if str(row.get("source_archive_group", "")) == "br1_events"),
            None,
        )
        if event_report is None:
            raise SharedPresentationPrototypeError("missing br1_events difference report")
        entry_by_path = {
            str(row.get("normalized_path", "")): row
            for row in event_report.get("entries", [])
            if row.get("scope_status") == "in_scope" and row.get("source") and row.get("target")
        }

        prototype_root = workspace_root / PROTOTYPE_SUBDIR
        try:
            prototype_root.relative_to(workspace_root)
        except ValueError as exc:
            raise SharedPresentationPrototypeError("prototype root escapes quartet_restoration workspace") from exc
        if prototype_root.exists():
            shutil.rmtree(prototype_root)
        prototype_root.mkdir(parents=True, exist_ok=True)
        profile_dir = prototype_root / EXPECTED_PROFILE_ID
        payload_root = profile_dir / "payload"

        profile_rows: list[dict[str, object]] = []
        file_rows: list[dict[str, object]] = []
        validation_rows: list[dict[str, object]] = []
        skipped_rows: list[dict[str, object]] = []
        manifest_files: list[dict[str, object]] = []
        profile_failed = False

        for occurrence in sorted(occurrences, key=lambda row: row.get("normalized_path", "")):
            normalized_path = str(occurrence.get("normalized_path", ""))
            occurrence_index = parse_int(occurrence.get("occurrence_index"))
            stage35_row = stage35_splices.get((normalized_path, occurrence_index))
            if stage35_row is None:
                skipped_rows.append({
                    "profile_id": EXPECTED_PROFILE_ID, "normalized_path": normalized_path,
                    "shape_id": EXPECTED_SHAPE_ID, "reason": "stage35_splice_row_missing",
                })
                profile_failed = True
                continue
            entry = entry_by_path.get(normalized_path)
            if entry is None:
                skipped_rows.append({
                    "profile_id": EXPECTED_PROFILE_ID, "normalized_path": normalized_path,
                    "shape_id": EXPECTED_SHAPE_ID, "reason": "difference_entry_missing",
                })
                profile_failed = True
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
                skipped_rows.append({
                    "profile_id": EXPECTED_PROFILE_ID, "normalized_path": normalized_path,
                    "shape_id": EXPECTED_SHAPE_ID, "reason": "workspace_event_payload_missing",
                })
                profile_failed = True
                continue
            if source_path.stat().st_size > maximum_event_bytes or target_path.stat().st_size > maximum_event_bytes:
                skipped_rows.append({
                    "profile_id": EXPECTED_PROFILE_ID, "normalized_path": normalized_path,
                    "shape_id": EXPECTED_SHAPE_ID, "reason": "maximum_event_bytes_exceeded",
                })
                profile_failed = True
                continue

            source_payload = source_path.read_bytes()
            target_payload = target_path.read_bytes()
            source_sha = hashlib.sha256(source_payload).hexdigest()
            target_sha = hashlib.sha256(target_payload).hexdigest()
            if source_ref.get("sha256") and source_sha != str(source_ref.get("sha256")):
                skipped_rows.append({
                    "profile_id": EXPECTED_PROFILE_ID, "normalized_path": normalized_path,
                    "shape_id": EXPECTED_SHAPE_ID, "reason": "source_payload_sha256_mismatch",
                })
                profile_failed = True
                continue
            if target_ref.get("sha256") and target_sha != str(target_ref.get("sha256")):
                skipped_rows.append({
                    "profile_id": EXPECTED_PROFILE_ID, "normalized_path": normalized_path,
                    "shape_id": EXPECTED_SHAPE_ID, "reason": "target_payload_sha256_mismatch",
                })
                profile_failed = True
                continue

            try:
                candidate_payload, metadata = construct_exact_inverse_candidate(
                    br=br, source_payload=source_payload, target_payload=target_payload, occurrence=occurrence,
                )
            except (SharedPresentationPrototypeError, br.RestorationError, OSError, ValueError, struct.error) as exc:
                skipped_rows.append({
                    "profile_id": EXPECTED_PROFILE_ID, "normalized_path": normalized_path,
                    "shape_id": EXPECTED_SHAPE_ID, "reason": f"candidate_error:{type(exc).__name__}:{exc}",
                })
                profile_failed = True
                continue

            checks = {
                "stage35_candidate_sha256_reproduced": metadata["candidate_sha256"] == stage35_row.get("candidate_sha256"),
                "stage35_candidate_size_reproduced": parse_int(metadata["candidate_size"]) == parse_int(stage35_row.get("candidate_size")),
                "stage35_source_span_sha256_reproduced": metadata["source_span_sha256"] == stage35_row.get("source_span_sha256"),
                "stage35_target_span_sha256_reproduced": metadata["target_span_sha256"] == stage35_row.get("target_span_sha256"),
                "selected_occurrence_removed": bool(metadata["selected_occurrence_removed"]),
                "all_other_residual_shapes_unchanged": bool(metadata["other_residual_shape_counter_unchanged"]),
                "target_header_preserved": bool(metadata["target_header_preserved"]),
                "target_trailing_bytes_preserved": bool(metadata["target_trailing_bytes_preserved"]),
                "target_prefix_preserved": bool(metadata["target_prefix_preserved"]),
                "target_suffix_preserved": bool(metadata["target_suffix_preserved"]),
                "candidate_header_valid": bool(metadata["candidate_header_valid"]),
                "exact_target_reverse_roundtrip": bool(metadata["target_roundtrip_exact"]),
                "candidate_not_farther_from_original": parse_int(metadata["candidate_byte_difference_to_source"])
                    <= parse_int(metadata["target_byte_difference_to_source"]),
            }
            for check_name, passed in checks.items():
                validation_rows.append({
                    "profile_id": EXPECTED_PROFILE_ID,
                    "normalized_path": normalized_path,
                    "shape_id": EXPECTED_SHAPE_ID,
                    "check_name": check_name,
                    "passed": passed,
                    "review_status": "metadata_gate_only_not_runtime_validation",
                })
            if not all(checks.values()):
                skipped_rows.append({
                    "profile_id": EXPECTED_PROFILE_ID, "normalized_path": normalized_path,
                    "shape_id": EXPECTED_SHAPE_ID, "reason": "one_or_more_prototype_validation_gates_failed",
                })
                profile_failed = True
                continue

            local_relative_path = PurePosixPath("payload") / PurePosixPath(normalized_path)
            candidate_path = profile_dir / Path(local_relative_path.as_posix())
            atomic_bytes(candidate_path, candidate_payload)
            candidate_sha = str(metadata["candidate_sha256"])
            manifest_files.append({
                "normalized_path": normalized_path,
                "candidate_relative_path": local_relative_path.as_posix(),
                "source_archive": source_ref.get("archive", ""),
                "source_member_path": source_ref.get("path", ""),
                "target_archive": target_ref.get("archive", ""),
                "target_member_path": target_ref.get("path", ""),
                "source_sha256": source_sha,
                "target_sha256": target_sha,
                "candidate_sha256": candidate_sha,
                "source_size": len(source_payload),
                "target_size": len(target_payload),
                "candidate_size": len(candidate_payload),
                "occurrence_index": occurrence_index,
                "cue_domains": occurrence.get("cue_domains", ""),
                "pair_context_archetype_id": occurrence.get("pair_context_archetype_id", ""),
            })
            file_rows.append({
                "profile_id": EXPECTED_PROFILE_ID,
                "profile_classification": "shared_presentation_exact_span_local_prototype",
                "prototype_confidence": "metadata_gated",
                "normalized_path": normalized_path,
                "shape_id": EXPECTED_SHAPE_ID,
                "occurrence_index": occurrence_index,
                "cue_positive_occurrence": True,
                "cue_domains": occurrence.get("cue_domains", ""),
                "pair_context_archetype_id": occurrence.get("pair_context_archetype_id", ""),
                "source_archive": source_ref.get("archive", ""),
                "source_member_path": source_ref.get("path", ""),
                "target_archive": target_ref.get("archive", ""),
                "target_member_path": target_ref.get("path", ""),
                "source_sha256": source_sha,
                "target_sha256": target_sha,
                "candidate_sha256": candidate_sha,
                "source_size": len(source_payload),
                "target_size": len(target_payload),
                "candidate_size": len(candidate_payload),
                "candidate_size_delta": metadata["candidate_size_delta"],
                "source_span_start_word_index": metadata["source_span_start_word_index"],
                "source_span_end_word_index": metadata["source_span_end_word_index"],
                "target_span_start_word_index": metadata["target_span_start_word_index"],
                "target_span_end_word_index": metadata["target_span_end_word_index"],
                "source_span_word_count": metadata["source_span_word_count"],
                "target_span_word_count": metadata["target_span_word_count"],
                "source_span_sha256": metadata["source_span_sha256"],
                "target_span_sha256": metadata["target_span_sha256"],
                "target_byte_difference_to_source": metadata["target_byte_difference_to_source"],
                "candidate_byte_difference_to_source": metadata["candidate_byte_difference_to_source"],
                "local_relative_path": local_relative_path.as_posix(),
                "validation_status": "passed",
                "review_status": "local_candidate_not_installable_runtime_unvalidated",
            })

        if profile_failed or len(manifest_files) != 2:
            if profile_dir.exists():
                shutil.rmtree(profile_dir)
            skipped_rows.append({
                "profile_id": EXPECTED_PROFILE_ID,
                "normalized_path": "",
                "shape_id": EXPECTED_SHAPE_ID,
                "reason": "profile_removed_after_validation_failure",
            })
            manifest_files.clear()
            file_rows.clear()
        else:
            manifest = {
                "type": "br_quartet_restoration_local_residual_shared_presentation_prototype",
                "format_version": 1,
                "tool_version": TOOL_VERSION,
                "profile_id": EXPECTED_PROFILE_ID,
                "profile_classification": "shared_presentation_exact_span_local_prototype",
                "prototype_confidence": "metadata_gated",
                "shape_id": EXPECTED_SHAPE_ID,
                "source_stage35_classification": gate.get("stage35_classification", ""),
                "cue_only_cross_route_support": True,
                "runtime_validated": False,
                "censorship_semantics_assigned": False,
                "installed_game_files_modified": False,
                "installable_package_generated": False,
                "files": manifest_files,
            }
            atomic_json(profile_dir / "PROTOTYPE.json", manifest)
            profile_rows.append({
                "profile_id": EXPECTED_PROFILE_ID,
                "profile_classification": "shared_presentation_exact_span_local_prototype",
                "prototype_confidence": "metadata_gated",
                "shape_id": EXPECTED_SHAPE_ID,
                "source_stage35_classification": gate.get("stage35_classification", ""),
                "file_count": len(manifest_files),
                "cue_file_count": len(manifest_files),
                "noncue_file_count": 0,
                "route_family_count": 2,
                "route_families": "ce11;em01",
                "cue_domains": "pool_or_swimming;steam_or_vapor",
                "local_profile_root": str(profile_dir.relative_to(project_root)) if profile_dir.is_relative_to(project_root) else str(profile_dir),
                "validation_status": "passed",
                "review_status": "separate_local_profile_not_repacked_not_installed",
            })

        profile_rows.sort(key=lambda row: str(row.get("profile_id", "")))
        file_rows.sort(key=lambda row: str(row.get("normalized_path", "")))
        validation_rows.sort(key=lambda row: (str(row.get("normalized_path", "")), str(row.get("check_name", ""))))
        skipped_rows.sort(key=lambda row: (str(row.get("normalized_path", "")), str(row.get("reason", ""))))

        evidence_root = report_root / EVIDENCE_DIR_NAME
        if evidence_root.exists():
            shutil.rmtree(evidence_root)
        evidence_root.mkdir(parents=True, exist_ok=True)
        write_tsv(evidence_root / "RESIDUAL_SHARED_PRESENTATION_PROFILES.tsv", [
            "profile_id", "profile_classification", "prototype_confidence", "shape_id",
            "source_stage35_classification", "file_count", "cue_file_count", "noncue_file_count",
            "route_family_count", "route_families", "cue_domains", "local_profile_root",
            "validation_status", "review_status",
        ], profile_rows)
        write_tsv(evidence_root / "RESIDUAL_SHARED_PRESENTATION_FILES.tsv", [
            "profile_id", "profile_classification", "prototype_confidence", "normalized_path", "shape_id",
            "occurrence_index", "cue_positive_occurrence", "cue_domains", "pair_context_archetype_id",
            "source_archive", "source_member_path", "target_archive", "target_member_path",
            "source_sha256", "target_sha256", "candidate_sha256", "source_size", "target_size",
            "candidate_size", "candidate_size_delta", "source_span_start_word_index",
            "source_span_end_word_index", "target_span_start_word_index", "target_span_end_word_index",
            "source_span_word_count", "target_span_word_count", "source_span_sha256", "target_span_sha256",
            "target_byte_difference_to_source", "candidate_byte_difference_to_source",
            "local_relative_path", "validation_status", "review_status",
        ], file_rows)
        write_tsv(evidence_root / "RESIDUAL_SHARED_PRESENTATION_VALIDATION.tsv", [
            "profile_id", "normalized_path", "shape_id", "check_name", "passed", "review_status",
        ], validation_rows)
        write_tsv(evidence_root / "RESIDUAL_SHARED_PRESENTATION_BUILD_SKIPPED.tsv", [
            "profile_id", "normalized_path", "shape_id", "reason",
        ], skipped_rows)

        validation_failures = sum(not parse_bool(row.get("passed")) for row in validation_rows)
        summary: dict[str, object] = {
            "type": "br_quartet_restoration_residual_shared_presentation_prototype_evidence_summary",
            "format_version": 1,
            "tool_version": TOOL_VERSION,
            "source_residual_exact_context_tool_version": stage35_summary.get("tool_version"),
            "status": "one_separate_local_shared_presentation_event_profile_built_and_roundtrip_validated_not_repacked_not_installed",
            "eligible_shape_rows": 1,
            "eligible_shape_ids": [EXPECTED_SHAPE_ID],
            "promoted_profile_rows": len(profile_rows),
            "prototype_file_rows": len(file_rows),
            "prototype_validation_rows": len(validation_rows),
            "validation_failures": validation_failures,
            "skipped_rows": len(skipped_rows),
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
                "route_or_schema_shapes_promoted": False,
                "dialogue_or_localized_text_exported": False,
                "legacy_dlc_in_scope": False,
                "translation_or_core_files_modified": False,
            },
            "next_action": (
                "Upload this metadata report. If the single profile and all validation gates pass, prepare one separate "
                "checksum-gated local PACK11 repack test; do not copy candidate EBD files into the game manually."
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
    if not project_root.is_dir():
        raise SharedPresentationPrototypeError(f"project root does not exist: {project_root}")
    default_workspace = project_root / ".local/build/quartet_restoration"
    default_reports = project_root / ".local/reports/quartet_restoration"
    workspace_root = Path(args.workspace_root).expanduser().resolve() if args.workspace_root else default_workspace
    report_root = Path(args.report_root).expanduser().resolve() if args.report_root else default_reports
    try:
        workspace_root.relative_to(default_workspace)
        report_root.relative_to(default_reports)
    except ValueError as exc:
        raise SharedPresentationPrototypeError("workspace/report roots must remain inside quartet_restoration local roots") from exc
    output, summary = build_residual_shared_presentation_prototype(
        project_root=project_root,
        workspace_root=workspace_root,
        report_root=report_root,
        maximum_event_bytes=args.maximum_event_bytes,
    )
    print(f"Local shared-presentation profiles built: {summary['promoted_profile_rows']}")
    print(f"Local candidate EBD files: {summary['prototype_file_rows']}")
    print(f"Validation failures: {summary['validation_failures']}")
    print(f"Metadata-only report: {output}")
    print(f"Local prototypes: {summary['local_prototype_root']}")
    print("Installed game files were not modified.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SharedPresentationPrototypeError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
