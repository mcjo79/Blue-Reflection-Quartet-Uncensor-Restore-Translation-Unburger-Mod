#!/usr/bin/env python3
"""Audit the two residual shapes left in the registered fe13_090 candidate.

Stage 59 reconstructs the exact stage-51 candidate in memory, verifies its
registered-profile hash, and then evaluates each remaining residual separately
and as one bounded two-shape combination.  Promotion requires preservation of
all non-selected residual counters, no newly introduced shapes, exact reverse
round-trip to both the stage-51 candidate and the current Quartet EBD, and a
strict reduction in byte distance to Original.  No EBD or PAK payload is
written.
"""
from __future__ import annotations

import argparse
import hashlib
import itertools
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
import collect_unselected_cue_residual_splice_evidence as stage51

WORKSTREAM_ID = "quartet_restoration"
TOOL_VERSION = "0.0.68"
TARGET_EVENT_PATH = "event/event_jp/fe13/event_fe13_090.ebd"
REGISTERED_PROFILE_ID = "candidate_unselected_cue_residual_fe13_090_8330c2a15d46"
PRIMARY_SHAPE_ID = "8330c2a15d46ecd6f1a7ca60bd51696b69f69e9bc415c568e9610b1cc5ce8be7"
PRIMARY_CANDIDATE_SHA256 = "c1eb1458894ad5c5bc7375bce7bf3e8370f09b6974a5dcf49c69290fd64fcad5"
REMAINING_SHAPE_IDS = (
    "814385120ebc57505c10f3551bfcf26fd92ecaf1df7415f14410aa736c68d7d2",
    "5957105cd0163c27721a45d348ff58e3842d8c0b366e70186843f142ce0dd2cb",
)
REPORT_NAME = "BR_quartet_restoration_fe13_remaining_residual_evidence.tar.zst"
EVIDENCE_DIR_NAME = "fe13_remaining_residual_evidence"
REPORT_SPECS = {
    "stage51": (
        "unselected_cue_residual_splice_evidence",
        "BR_quartet_restoration_unselected_cue_residual_splice_evidence.tar.zst",
    ),
    "core": (
        "core_profile_manifest_evidence",
        "BR_quartet_restoration_core_profile_manifest_evidence.tar.zst",
    ),
}


class Fe13RemainingResidualError(RuntimeError):
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


def validate_core_summary(core_summary: Mapping[str, object]) -> None:
    """Validate the canonical stage-54 registry report.

    The actual 0.0.62 SUMMARY predates the optional ``rejected_manifests``
    counter.  Absence means the registrar emitted no rejection counter; it is
    not a failed value.  When the field is present, it must still be exactly
    zero.
    """
    if (
        core_summary.get("type")
        != "br_quartet_restoration_core_profile_manifest_evidence_summary"
        or core_summary.get("tool_version") != "0.0.62"
    ):
        raise Fe13RemainingResidualError("core report must be the canonical 0.0.62 report")

    rejected = core_summary.get("rejected_manifests")
    rejected_is_clean = rejected is None or parse_int(rejected, -1) == 0
    if (
        parse_int(core_summary.get("profile_rows"), -1) != 14
        or parse_int(core_summary.get("pack11_profile_rows"), -1) != 12
        or parse_int(core_summary.get("pack10_01_profile_rows"), -1) != 2
        or parse_int(core_summary.get("runtime_validated_profile_rows"), -1) != 0
        or not rejected_is_clean
    ):
        raise Fe13RemainingResidualError("core report must contain 14 clean runtime-unvalidated profiles")


def safe_member_name(raw: str) -> str:
    path = PurePosixPath(raw)
    if path.is_absolute() or not path.parts or ".." in path.parts:
        raise Fe13RemainingResidualError(f"unsafe report archive member: {raw}")
    return path.as_posix()


def extract_archive(archive: Path, destination: Path) -> Path:
    if not archive.is_file():
        raise Fe13RemainingResidualError(f"missing prerequisite report archive: {archive}")
    listed = subprocess.run(
        ["tar", "--zstd", "-tf", str(archive)],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if listed.returncode:
        raise Fe13RemainingResidualError(f"cannot list {archive}: {listed.stderr.strip()}")
    roots = {
        PurePosixPath(safe_member_name(line.strip())).parts[0]
        for line in listed.stdout.splitlines()
        if line.strip()
    }
    if len(roots) != 1:
        raise Fe13RemainingResidualError(
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
        raise Fe13RemainingResidualError(f"cannot extract {archive}: {done.stderr.strip()}")
    return destination / next(iter(roots))


def locate_report_root(report_root: Path, key: str, temporary: Path) -> Path:
    dirname, archive = REPORT_SPECS[key]
    direct = report_root / dirname
    if direct.is_dir():
        return direct
    return extract_archive(report_root / archive, temporary / key)


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
        raise Fe13RemainingResidualError(f"cannot create report archive: {done.stderr.strip()}")
    os.replace(temporary, output)


def shape_counter(br: Any, source_payload: bytes, target_payload: bytes) -> Counter[str]:
    source_header = br.parse_ebd_header_schema(source_payload)
    target_header = br.parse_ebd_header_schema(target_payload)
    source_profile = br.profile_ebd_post_header_words(
        source_payload,
        int(source_header["header_end"]),
        maximum_words=max(1, len(source_payload) // 4 + 8),
    )
    target_profile = br.profile_ebd_post_header_words(
        target_payload,
        int(target_header["header_end"]),
        maximum_words=max(1, len(target_payload) // 4 + 8),
    )
    return Counter(
        br.event_residual_delta_shape_id(row)
        for row in br.compare_ebd_tag_atoms(source_profile["atoms"], target_profile["atoms"])
    )


def occurrence_rows(shape_ids: Sequence[str]) -> list[dict[str, object]]:
    return [
        {
            "shape_id": shape_id,
            "occurrence_index": 0,
            "cue_domains": "clothing_state;costume_or_coverage",
            "selection_reasons": "fe13_090_remaining_residual_audit",
        }
        for shape_id in shape_ids
    ]


def inverse_candidate(
    *, br: Any, source_payload: bytes, target_payload: bytes, shape_ids: Sequence[str]
) -> tuple[bytes, dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]:
    selected = occurrence_rows(shape_ids)
    candidate, metadata, residuals = br.construct_composite_inverse_event_candidate(
        source_payload=source_payload,
        target_payload=target_payload,
        selected_occurrences=selected,
    )
    if candidate is None:
        raise Fe13RemainingResidualError(
            f"cannot reconstruct inverse candidate for {','.join(shape_ids)}: {metadata.get('status')}"
        )
    operations, _, _ = subset.build_operations(
        br=br,
        source_payload=source_payload,
        target_payload=target_payload,
        selected_occurrences=selected,
    )
    return candidate, metadata, residuals, operations


def evaluate_remaining_combinations(
    br: Any,
    source_payload: bytes,
    quartet_payload: bytes,
    *,
    primary_shape_id: str = PRIMARY_SHAPE_ID,
    remaining_shape_ids: Sequence[str] = REMAINING_SHAPE_IDS,
    expected_primary_sha256: str = PRIMARY_CANDIDATE_SHA256,
) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    if len(remaining_shape_ids) != 2 or len(set(remaining_shape_ids)) != 2:
        raise Fe13RemainingResidualError("stage 59 requires exactly two distinct remaining shapes")

    base_candidate, base_metadata, _, base_operations = inverse_candidate(
        br=br,
        source_payload=source_payload,
        target_payload=quartet_payload,
        shape_ids=[primary_shape_id],
    )
    base_sha256 = hashlib.sha256(base_candidate).hexdigest()
    if expected_primary_sha256 and base_sha256 != expected_primary_sha256:
        raise Fe13RemainingResidualError(
            f"stage-51 candidate hash mismatch: expected {expected_primary_sha256}, got {base_sha256}"
        )
    reversed_quartet = subset.reverse_candidate(
        candidate_payload=base_candidate,
        target_payload=quartet_payload,
        operations=base_operations,
        br=br,
    )
    if reversed_quartet != quartet_payload:
        raise Fe13RemainingResidualError("stage-51 candidate no longer reverses exactly to Quartet")

    base_counter = shape_counter(br, source_payload, base_candidate)
    actual_remaining = Counter({shape: base_counter.get(shape, 0) for shape in remaining_shape_ids})
    if actual_remaining != Counter({shape: 1 for shape in remaining_shape_ids}):
        raise Fe13RemainingResidualError(
            f"remaining shape occurrences changed: {dict(actual_remaining)}"
        )
    unexpected = set(base_counter) - set(remaining_shape_ids)
    if unexpected:
        raise Fe13RemainingResidualError(
            f"stage-51 candidate has unexpected residual shapes: {sorted(unexpected)}"
        )

    base_distance = subset.byte_difference_count(base_candidate, source_payload)
    combination_rows: list[dict[str, Any]] = []
    test_rows: list[dict[str, Any]] = []
    selected_rows: list[dict[str, Any]] = []

    combinations = [
        combo
        for size in (1, 2)
        for combo in itertools.combinations(tuple(remaining_shape_ids), size)
    ]
    for index, combo in enumerate(combinations, start=1):
        candidate, metadata, residuals, operations = inverse_candidate(
            br=br,
            source_payload=source_payload,
            target_payload=base_candidate,
            shape_ids=combo,
        )
        reversed_base = subset.reverse_candidate(
            candidate_payload=candidate,
            target_payload=base_candidate,
            operations=operations,
            br=br,
        )
        after_counter = shape_counter(br, source_payload, candidate)
        selected_before = Counter({shape: base_counter.get(shape, 0) for shape in combo})
        selected_after = Counter({shape: after_counter.get(shape, 0) for shape in combo})
        nonselected_before = base_counter.copy()
        nonselected_after = after_counter.copy()
        for shape in combo:
            nonselected_before.pop(shape, None)
            nonselected_after.pop(shape, None)
        candidate_distance = subset.byte_difference_count(candidate, source_payload)
        improvement = base_distance - candidate_distance
        checks = {
            "selected_occurrences_present_once": all(value == 1 for value in selected_before.values()),
            "selected_occurrences_removed": all(value == 0 for value in selected_after.values()),
            "all_nonselected_residual_counters_preserved": nonselected_before == nonselected_after,
            "no_new_residual_shapes": not (set(after_counter) - set(base_counter)),
            "no_nonselected_residual_shapes_removed": parse_int(
                metadata.get("removed_nonselected_coarse_shape_count"), -1
            ) == 0,
            "candidate_header_preserved_from_stage51": parse_bool(
                metadata.get("candidate_header_preserved_from_target")
            ),
            "candidate_trailing_preserved_from_stage51": parse_bool(
                metadata.get("candidate_trailing_bytes_preserved_from_target")
            ),
            "candidate_header_valid": metadata.get("candidate_header_classification")
            == "observed_ebd_name_description_header",
            "exact_stage51_reverse_roundtrip": reversed_base == base_candidate,
            "exact_full_quartet_reverse_chain": reversed_base == base_candidate
            and reversed_quartet == quartet_payload,
            "candidate_not_farther_from_original_than_stage51": candidate_distance <= base_distance,
        }
        structural_names = [
            name
            for name in checks
            if name != "candidate_not_farther_from_original_than_stage51"
        ]
        passes_structural = all(checks[name] for name in structural_names)
        strict_improvement = passes_structural and candidate_distance < base_distance
        if strict_improvement:
            classification = "strict_improvement_ready_for_separate_local_prototype"
            next_gate = "build_exact_fe13_remaining_residual_candidate"
        elif passes_structural and candidate_distance == base_distance:
            classification = "structurally_safe_but_flat_evidence_only"
            next_gate = "retain_as_evidence_only"
        elif passes_structural:
            classification = "structurally_safe_but_farther_evidence_only"
            next_gate = "retain_as_evidence_only"
        else:
            classification = "structural_gate_failure"
            next_gate = "do_not_build"

        combination_id = f"fe13_090_remaining_{index}"
        combination_rows.append(
            {
                "combination_id": combination_id,
                "normalized_path": TARGET_EVENT_PATH,
                "selected_shape_ids": ";".join(combo),
                "selected_shape_count": len(combo),
                "stage51_distance_to_original": base_distance,
                "candidate_distance_to_original": candidate_distance,
                "distance_improvement_over_stage51": improvement,
                "candidate_sha256": hashlib.sha256(candidate).hexdigest(),
                "candidate_size": len(candidate),
                "remaining_residual_rows": len(residuals),
                "passes_structural_gates": passes_structural,
                "strict_improvement": strict_improvement,
                "classification": classification,
                "safe_to_build_separate_local_profile": strict_improvement,
                "runtime_test_deferred": True,
                "next_gate": next_gate,
            }
        )
        for shape in combo:
            selected_rows.append(
                {
                    "combination_id": combination_id,
                    "normalized_path": TARGET_EVENT_PATH,
                    "shape_id": shape,
                    "occurrence_index": 0,
                    "sequence_tag": "insert",
                    "source_atom_count": 0,
                    "target_atom_count": 1,
                    "semantic_status": "unassigned",
                }
            )
        for name, passed in checks.items():
            test_rows.append(
                {
                    "combination_id": combination_id,
                    "normalized_path": TARGET_EVENT_PATH,
                    "selected_shape_ids": ";".join(combo),
                    "validation": name,
                    "passed": passed,
                    "details": "",
                }
            )
        test_rows.extend(
            [
                {
                    "combination_id": combination_id,
                    "normalized_path": TARGET_EVENT_PATH,
                    "selected_shape_ids": ";".join(combo),
                    "validation": "passes_structural_gates",
                    "passed": passes_structural,
                    "details": "",
                },
                {
                    "combination_id": combination_id,
                    "normalized_path": TARGET_EVENT_PATH,
                    "selected_shape_ids": ";".join(combo),
                    "validation": "strict_improvement_over_stage51",
                    "passed": strict_improvement,
                    "details": str(improvement),
                },
            ]
        )

    best = min(
        combination_rows,
        key=lambda row: (
            parse_int(row["candidate_distance_to_original"], 1 << 60),
            parse_int(row["selected_shape_count"], 99),
            str(row["selected_shape_ids"]),
        ),
    )
    event_summary = {
        "normalized_path": TARGET_EVENT_PATH,
        "event_id": "fe13_090",
        "registered_profile_id": REGISTERED_PROFILE_ID,
        "primary_removed_shape_id": primary_shape_id,
        "primary_candidate_sha256": base_sha256,
        "quartet_distance_to_original": subset.byte_difference_count(quartet_payload, source_payload),
        "stage51_distance_to_original": base_distance,
        "remaining_shape_ids": ";".join(remaining_shape_ids),
        "tested_combination_rows": len(combination_rows),
        "promotable_combination_rows": sum(
            parse_bool(row["safe_to_build_separate_local_profile"])
            for row in combination_rows
        ),
        "best_combination_id": best["combination_id"],
        "best_selected_shape_ids": best["selected_shape_ids"],
        "best_candidate_distance_to_original": best["candidate_distance_to_original"],
        "best_distance_improvement_over_stage51": best["distance_improvement_over_stage51"],
        "best_classification": best["classification"],
        "runtime_test_deferred": True,
    }
    return event_summary, combination_rows, selected_rows, test_rows


def validate_prerequisites(
    *, project_root: Path, stage51_root: Path, core_root: Path
) -> dict[str, Any]:
    stage51_summary = load_json(stage51_root / "SUMMARY.json")
    if (
        stage51_summary.get("type")
        != "br_quartet_restoration_unselected_cue_residual_splice_evidence_summary"
        or stage51_summary.get("tool_version") != "0.0.59"
    ):
        raise Fe13RemainingResidualError("stage-51 report must be the canonical 0.0.59 report")
    if (
        parse_int(stage51_summary.get("promotable_event_rows"), -1) != 1
        or parse_int(stage51_summary.get("remaining_residual_rows"), -1) != 2
        or parse_int(stage51_summary.get("validation_failures"), -1) != 0
    ):
        raise Fe13RemainingResidualError("stage-51 report no longer has the expected clean result")

    event_rows = read_tsv(stage51_root / "UNSELECTED_CUE_RESIDUAL_EVENTS.tsv")
    if len(event_rows) != 1:
        raise Fe13RemainingResidualError("stage-51 report must contain exactly one event row")
    event_row = event_rows[0]
    if (
        normalize_event_member(event_row.get("normalized_path")) != TARGET_EVENT_PATH
        or event_row.get("shape_id") != PRIMARY_SHAPE_ID
        or event_row.get("candidate_sha256") != PRIMARY_CANDIDATE_SHA256
        or parse_int(event_row.get("candidate_distance_to_source"), -1) != 2589
        or parse_int(event_row.get("distance_improvement"), -1) != 310
        or not parse_bool(event_row.get("safe_to_build_separate_local_profile"))
    ):
        raise Fe13RemainingResidualError("stage-51 fe13_090 result changed")

    remaining_rows = read_tsv(stage51_root / "UNSELECTED_CUE_RESIDUAL_REMAINING.tsv")
    remaining_by_shape = {row.get("shape_id", ""): row for row in remaining_rows}
    if set(remaining_by_shape) != set(REMAINING_SHAPE_IDS):
        raise Fe13RemainingResidualError("stage-51 remaining residual set changed")
    for shape_id in REMAINING_SHAPE_IDS:
        row = remaining_by_shape[shape_id]
        if (
            row.get("sequence_tag") != "insert"
            or parse_int(row.get("source_atom_count"), -1) != 0
            or parse_int(row.get("target_atom_count"), -1) != 1
        ):
            raise Fe13RemainingResidualError(
                f"remaining residual no longer has expected insert 0->1 form: {shape_id}"
            )

    core_summary = load_json(core_root / "SUMMARY.json")
    validate_core_summary(core_summary)

    registry_root = project_root / ".local/build/quartet_restoration/core_profiles/generated"
    manifests = sorted(registry_root.glob("*.json")) if registry_root.is_dir() else []
    if len(manifests) != 14:
        raise Fe13RemainingResidualError(f"expected 14 generated profile manifests, found {len(manifests)}")
    target_manifests: list[dict[str, Any]] = []
    for path in manifests:
        data = load_json(path)
        if data.get("workstream_id") != WORKSTREAM_ID:
            raise Fe13RemainingResidualError(f"foreign manifest in restoration registry: {path}")
        if parse_bool(data.get("runtime_validated")):
            raise Fe13RemainingResidualError(f"runtime-validated manifest is not allowed here: {path}")
        if data.get("profile_id") == REGISTERED_PROFILE_ID:
            target_manifests.append(data)
    if len(target_manifests) != 1:
        raise Fe13RemainingResidualError(
            f"expected one registered fe13_090 profile, found {len(target_manifests)}"
        )
    manifest = target_manifests[0]
    if str(manifest.get("target_relative_path", "")).casefold() != "data/pack11.pak":
        raise Fe13RemainingResidualError("registered fe13_090 profile no longer targets PACK11")
    changed = [normalize_event_member(path) for path in manifest.get("changed_members", [])]
    if changed != [TARGET_EVENT_PATH]:
        raise Fe13RemainingResidualError("registered fe13_090 profile changed member set changed")
    if parse_bool(manifest.get("active")):
        raise Fe13RemainingResidualError("registered fe13_090 profile unexpectedly marked active")

    return {
        "stage51": stage51_summary,
        "core": core_summary,
        "stage51_event": event_row,
        "stage51_remaining": remaining_rows,
        "manifest": manifest,
    }


def collect(
    *, project_root: Path, workspace_root: Path, report_root: Path, maximum_event_bytes: int
) -> tuple[Path, dict[str, Any]]:
    sys.path.insert(0, str(project_root / "Blue_Reflection_Text_Tool"))
    try:
        import br_restoration_tool as br
    finally:
        sys.path.pop(0)

    with tempfile.TemporaryDirectory(prefix="br-stage59-") as temporary_raw:
        temporary = Path(temporary_raw)
        stage51_root = locate_report_root(report_root, "stage51", temporary)
        core_root = locate_report_root(report_root, "core", temporary)
        prerequisites = validate_prerequisites(
            project_root=project_root,
            stage51_root=stage51_root,
            core_root=core_root,
        )

        reports = br.load_report_jsons(report_root, "differences")
        event_report = next(
            (row for row in reports if str(row.get("source_archive_group", "")) == "br1_events"),
            None,
        )
        if event_report is None:
            raise Fe13RemainingResidualError("missing br1_events difference report")
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
            raise Fe13RemainingResidualError("missing in-scope difference entry for fe13_090")
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

        skipped_rows: list[dict[str, Any]] = []
        event_rows: list[dict[str, Any]] = []
        combination_rows: list[dict[str, Any]] = []
        selected_rows: list[dict[str, Any]] = []
        test_rows: list[dict[str, Any]] = []
        if not source_path.is_file() or not target_path.is_file():
            skipped_rows.append(
                {"normalized_path": TARGET_EVENT_PATH, "reason": "workspace_event_payload_missing"}
            )
        else:
            source_payload = source_path.read_bytes()
            target_payload = target_path.read_bytes()
            if len(source_payload) > maximum_event_bytes or len(target_payload) > maximum_event_bytes:
                skipped_rows.append(
                    {"normalized_path": TARGET_EVENT_PATH, "reason": "maximum_event_bytes_exceeded"}
                )
            elif source_ref.get("sha256") and hashlib.sha256(source_payload).hexdigest() != str(
                source_ref.get("sha256")
            ):
                skipped_rows.append(
                    {"normalized_path": TARGET_EVENT_PATH, "reason": "source_payload_sha256_mismatch"}
                )
            elif target_ref.get("sha256") and hashlib.sha256(target_payload).hexdigest() != str(
                target_ref.get("sha256")
            ):
                skipped_rows.append(
                    {"normalized_path": TARGET_EVENT_PATH, "reason": "target_payload_sha256_mismatch"}
                )
            else:
                event, combinations, selected, tests = evaluate_remaining_combinations(
                    br,
                    source_payload,
                    target_payload,
                )
                event_rows.append(event)
                combination_rows.extend(combinations)
                selected_rows.extend(selected)
                test_rows.extend(tests)

        output_dir = report_root / EVIDENCE_DIR_NAME
        if output_dir.exists():
            shutil.rmtree(output_dir)
        output_dir.mkdir(parents=True)
        write_tsv(
            output_dir / "FE13_REMAINING_RESIDUAL_EVENTS.tsv",
            [
                "normalized_path",
                "event_id",
                "registered_profile_id",
                "primary_removed_shape_id",
                "primary_candidate_sha256",
                "quartet_distance_to_original",
                "stage51_distance_to_original",
                "remaining_shape_ids",
                "tested_combination_rows",
                "promotable_combination_rows",
                "best_combination_id",
                "best_selected_shape_ids",
                "best_candidate_distance_to_original",
                "best_distance_improvement_over_stage51",
                "best_classification",
                "runtime_test_deferred",
            ],
            event_rows,
        )
        write_tsv(
            output_dir / "FE13_REMAINING_RESIDUAL_COMBINATIONS.tsv",
            [
                "combination_id",
                "normalized_path",
                "selected_shape_ids",
                "selected_shape_count",
                "stage51_distance_to_original",
                "candidate_distance_to_original",
                "distance_improvement_over_stage51",
                "candidate_sha256",
                "candidate_size",
                "remaining_residual_rows",
                "passes_structural_gates",
                "strict_improvement",
                "classification",
                "safe_to_build_separate_local_profile",
                "runtime_test_deferred",
                "next_gate",
            ],
            combination_rows,
        )
        write_tsv(
            output_dir / "FE13_REMAINING_RESIDUAL_SELECTED_OCCURRENCES.tsv",
            [
                "combination_id",
                "normalized_path",
                "shape_id",
                "occurrence_index",
                "sequence_tag",
                "source_atom_count",
                "target_atom_count",
                "semantic_status",
            ],
            selected_rows,
        )
        write_tsv(
            output_dir / "FE13_REMAINING_RESIDUAL_TESTS.tsv",
            [
                "combination_id",
                "normalized_path",
                "selected_shape_ids",
                "validation",
                "passed",
                "details",
            ],
            test_rows,
        )
        write_tsv(
            output_dir / "FE13_REMAINING_RESIDUAL_SKIPPED.tsv",
            ["normalized_path", "reason"],
            skipped_rows,
        )

        promotable = sum(
            parse_bool(row.get("safe_to_build_separate_local_profile"))
            for row in combination_rows
        )
        summary = {
            "type": "br_quartet_restoration_fe13_remaining_residual_evidence_summary",
            "format_version": 1,
            "tool_version": TOOL_VERSION,
            "source_stage51_tool_version": prerequisites["stage51"].get("tool_version"),
            "source_core_profile_tool_version": prerequisites["core"].get("tool_version"),
            "status": "fe13_remaining_residuals_audited_in_memory_no_payload_written_runtime_deferred",
            "target_event_rows": 1,
            "analyzed_event_rows": len(event_rows),
            "tested_combination_rows": len(combination_rows),
            "selected_occurrence_rows": len(selected_rows),
            "promotable_combination_rows": promotable,
            "validation_rows": len(test_rows),
            "validation_failures": sum(
                not parse_bool(row.get("passed"))
                for row in test_rows
                if row.get("validation") != "strict_improvement_over_stage51"
            ),
            "strict_improvement_failures": sum(
                not parse_bool(row.get("passed"))
                for row in test_rows
                if row.get("validation") == "strict_improvement_over_stage51"
            ),
            "skipped_rows": len(skipped_rows),
            "remaining_shape_ids": list(REMAINING_SHAPE_IDS),
            "runtime_testing_deferred": True,
            "policy": {
                "installed_games_modified": False,
                "candidate_ebd_payloads_written": False,
                "pak_repack_performed": False,
                "profile_manifests_modified": False,
                "activation_or_rollback_invoked": False,
                "runtime_validation_inferred": False,
                "censorship_classification_inferred": False,
                "binary_field_semantics_inferred": False,
                "legacy_dlc_or_removed_content_in_scope": False,
                "stage58_message_payload_rebuild_invoked": False,
                "each_remaining_shape_tested_separately": True,
                "bounded_pair_combination_tested": True,
                "all_nonselected_residual_counters_must_remain_unchanged": True,
                "exact_stage51_and_quartet_reverse_roundtrip_required": True,
                "strict_improvement_over_registered_candidate_required": True,
            },
            "next_action": (
                "Upload this metadata report. Build a separate local prototype only for a combination marked "
                "strict_improvement_ready_for_separate_local_prototype; otherwise close both residuals as "
                "evidence-only and continue to the next cue-positive EBD backlog event."
            ),
        }
        (output_dir / "SUMMARY.json").write_text(
            json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        output = report_root / REPORT_NAME
        make_report_archive(output_dir, output)
        return output, summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", required=True)
    parser.add_argument("--workspace-root")
    parser.add_argument("--report-root")
    parser.add_argument("--maximum-event-bytes", type=int, default=2 * 1024 * 1024)
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
        )
    except (
        Fe13RemainingResidualError,
        stage51.UnselectedCueResidualError,
        subset.SubsetSearchError,
        OSError,
        ValueError,
        json.JSONDecodeError,
    ) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print(f"fe13_090 events analyzed: {summary['analyzed_event_rows']}")
    print(f"Combinations tested: {summary['tested_combination_rows']}")
    print(f"Promotable combinations: {summary['promotable_combination_rows']}")
    print(f"Report: {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
