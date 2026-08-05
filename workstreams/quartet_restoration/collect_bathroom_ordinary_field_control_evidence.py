#!/usr/bin/env python3
"""Compare the Hinako bathroom descriptor with ordinary field controls.

Stage 67 showed that only three of the 61 changed Hinako-bathroom OPL2 words
share an exact Original->Quartet transition with the shower/pool controls.  The
remaining 58 are unique only inside that water-scene scope, which is not enough
to separate scene-specific restoration data from ordinary remaster/serializer
changes.  Stage 67 also proved a narrow, repeated-word exception for the final
river.bin word.

This stage remains read-only.  It discovers a bounded set of changed OPL2
members from ordinary non-water field containers, compares their exact word
transitions with the bathroom target, and produces cross-scope candidate
metadata.  Separately, it converts the already-proven river tail exception into
a static prototype-authorization row.  No member payload, Elixir archive, PAK,
registry, activation state or installed-game file is written.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from collections import Counter, defaultdict
from pathlib import Path, PurePosixPath
from typing import Any, Callable, Iterable, Mapping, Sequence

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT_DEFAULT = SCRIPT_DIR.parent.parent
TEXT_TOOL_DIR = PROJECT_ROOT_DEFAULT / "Blue_Reflection_Text_Tool"
for import_path in (SCRIPT_DIR, TEXT_TOOL_DIR):
    if str(import_path) not in sys.path:
        sys.path.insert(0, str(import_path))

import br_restoration_tool as BR  # noqa: E402
import collect_bathroom_scene_descriptor_word_evidence as STAGE66  # noqa: E402
import collect_bathroom_sibling_descriptor_comparison_evidence as STAGE67  # noqa: E402

TOOL_VERSION = "0.0.78"
REPORT_NAME = "BR_quartet_restoration_bathroom_ordinary_field_control_evidence.tar.zst"
EVIDENCE_DIR_NAME = "bathroom_ordinary_field_control_evidence"
EXPECTED_STAGE67_TOOL_VERSION = "0.0.77"

TARGET_OPL2_KEY = STAGE67.TARGET_OPL2_KEY
RIVER_KEY = STAGE67.RIVER_KEY
WATER_SCOPE_KEYS = (TARGET_OPL2_KEY, *STAGE67.SIBLING_OPL2_KEYS)

ORDINARY_FIELD_EXCLUDED_TOKENS = (
    "bath", "shower", "pool", "river", "water", "onsen", "hot_spring",
    "hotspring", "spa", "toilet", "steam", "mist", "sauna",
)


class OrdinaryFieldControlError(RuntimeError):
    pass


def parse_bool(value: object) -> bool:
    return str(value).strip().casefold() in {"1", "true", "yes", "y"}


def parse_int(value: object, default: int = 0) -> int:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return default


def safe_member_name(raw: str) -> str:
    path = PurePosixPath(raw)
    if path.is_absolute() or not path.parts or ".." in path.parts:
        raise OrdinaryFieldControlError(f"unsafe report archive member: {raw}")
    return path.as_posix()


def read_tsv(path: Path, *, required: bool = True) -> list[dict[str, str]]:
    if not path.is_file():
        if required:
            raise OrdinaryFieldControlError(f"missing prerequisite table: {path}")
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
        raise OrdinaryFieldControlError(f"missing prerequisite JSON: {path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise OrdinaryFieldControlError(f"invalid JSON {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise OrdinaryFieldControlError(f"expected JSON object: {path}")
    return value


def atomic_json(path: Path, value: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def extract_archive(archive: Path, destination: Path) -> Path:
    if not archive.is_file():
        raise OrdinaryFieldControlError(f"missing prerequisite report archive: {archive}")
    listed = subprocess.run(
        ["tar", "--zstd", "-tf", str(archive)], text=True,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False,
    )
    if listed.returncode != 0:
        raise OrdinaryFieldControlError(f"cannot list {archive}: {listed.stderr.strip()}")
    roots: set[str] = set()
    for raw in listed.stdout.splitlines():
        if raw.strip():
            roots.add(PurePosixPath(safe_member_name(raw.strip())).parts[0])
    if len(roots) != 1:
        raise OrdinaryFieldControlError(f"expected one report root in {archive}, found {sorted(roots)}")
    destination.mkdir(parents=True, exist_ok=True)
    completed = subprocess.run(
        ["tar", "--zstd", "-xf", str(archive), "-C", str(destination)], text=True,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False,
    )
    if completed.returncode != 0:
        raise OrdinaryFieldControlError(f"cannot extract {archive}: {completed.stderr.strip()}")
    return destination / next(iter(roots))


def locate_report_root(report_root: Path, directory_name: str, archive_name: str, temporary: Path) -> Path:
    direct = report_root / directory_name
    if direct.is_dir():
        return direct
    return extract_archive(report_root / archive_name, temporary)


def make_report_archive(source_dir: Path, output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(output.name + ".tmp")
    temporary.unlink(missing_ok=True)
    completed = subprocess.run(
        ["tar", "--zstd", "-cf", str(temporary), "-C", str(source_dir.parent), source_dir.name],
        text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False,
    )
    if completed.returncode != 0:
        raise OrdinaryFieldControlError(f"cannot create report archive: {completed.stderr.strip()}")
    os.replace(temporary, output)


def validate_stage67_report(root: Path) -> tuple[
    dict[str, Any], list[dict[str, str]], list[dict[str, str]],
    list[dict[str, str]], list[dict[str, str]],
]:
    summary = load_json(root / "SUMMARY.json")
    if summary.get("type") != "br_quartet_restoration_bathroom_sibling_descriptor_comparison_evidence_summary":
        raise OrdinaryFieldControlError("stage-67 report has an unexpected summary type")
    if summary.get("tool_version") != EXPECTED_STAGE67_TOOL_VERSION:
        raise OrdinaryFieldControlError("stage-67 report must use tool version 0.0.77")
    if summary.get("status") != "bathroom_sibling_descriptor_and_river_tail_audit_complete_no_payload_written_manual_decode_still_required":
        raise OrdinaryFieldControlError("stage-67 report is not complete")
    fixed_counts = {
        "scope_member_rows": 4,
        "opl2_scope_member_rows": 3,
        "target_opl2_cell_rows": 61,
        "opl2_exact_original_candidate_rows": 1,
        "river_word_cell_rows": 7,
        "river_repeated_tail_guard_exception_rows": 1,
        "river_candidate_rows": 2,
        "river_exact_original_candidate_rows": 1,
        "safe_local_prototype_rows": 0,
        "skipped_rows": 0,
    }
    for field, expected in fixed_counts.items():
        if parse_int(summary.get(field), -1) != expected:
            raise OrdinaryFieldControlError(f"stage-67 summary field {field} must equal {expected}")
    shared = parse_int(summary.get("target_opl2_cells_shared_by_exact_transition_with_sibling"), -1)
    unique = parse_int(summary.get("target_opl2_scope_unique_transition_cells"), -1)
    strict = parse_int(summary.get("target_opl2_strict_unique_word_pair_cells"), -1)
    if shared < 0 or unique < 0 or shared + unique != 61 or not (0 <= strict <= unique):
        raise OrdinaryFieldControlError("stage-67 target transition counts are inconsistent")
    policy = summary.get("policy") or {}
    if not isinstance(policy, dict):
        raise OrdinaryFieldControlError("stage-67 policy is malformed")
    for field in (
        "installed_games_modified", "candidate_member_payloads_written",
        "parent_archive_repack_performed", "pak_repack_performed",
        "core_registry_modified", "activation_or_rollback_invoked",
        "runtime_validation_inferred", "censorship_classification_inferred",
        "opaque_binary_field_semantics_inferred", "translation_or_dlc_workstreams_modified",
    ):
        if parse_bool(policy.get(field)):
            raise OrdinaryFieldControlError(f"stage-67 policy field {field} must be false")
    if not parse_bool(policy.get("ordinary_field_or_format_control_still_required_before_opl2_payload_build")):
        raise OrdinaryFieldControlError("stage-67 must retain the ordinary-field control requirement")

    opl2_candidate_count = parse_int(summary.get("opl2_candidate_rows"), -1)
    if opl2_candidate_count not in {3, 4}:
        raise OrdinaryFieldControlError("stage-67 OPL2 candidate count must be 3 or 4")
    target_rows = read_tsv(root / "BATHROOM_OPL2_TARGET_CELL_COMPARISONS.tsv")
    opl2_candidates = read_tsv(root / "BATHROOM_OPL2_CONTROLLED_CANDIDATES.tsv")
    river_review = read_tsv(root / "BATHROOM_RIVER_TAIL_REVIEW.tsv")
    river_candidates = read_tsv(root / "BATHROOM_RIVER_CANDIDATES.tsv")
    if len(target_rows) != 61 or len(opl2_candidates) != opl2_candidate_count or len(river_review) != 7 or len(river_candidates) != 2:
        raise OrdinaryFieldControlError("stage-67 table row counts do not match the summary")
    exact_opl2 = [row for row in opl2_candidates if parse_bool(row.get("exact_original"))]
    if len(exact_opl2) != 1 or exact_opl2[0].get("candidate_kind") != "complete_hinako_bathroom_word_set":
        raise OrdinaryFieldControlError("stage-67 exact OPL2 candidate is missing or ambiguous")
    exact_river = [row for row in river_candidates if parse_bool(row.get("exact_original"))]
    if len(exact_river) != 1 or exact_river[0].get("candidate_kind") != "complete_word_set_with_repeated_tail_guard_exception":
        raise OrdinaryFieldControlError("stage-67 exact river candidate is missing or ambiguous")
    return summary, target_rows, opl2_candidates, river_review, river_candidates


def _entry_normalized_path(entry: Mapping[str, Any]) -> str:
    source = entry.get("source") or {}
    target = entry.get("target") or {}
    return str(entry.get("normalized_path") or target.get("normalized_path") or source.get("normalized_path") or "")


def load_ordinary_field_opl2_pairs(
    *, workspace_root: Path, report_root: Path, maximum_earc_bytes: int,
    maximum_payload_bytes: int, maximum_control_archives: int,
    maximum_control_members: int, progress_callback: Callable[[str], None] | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Discover bounded non-water field OPL2 controls from the complete differences."""
    emit = progress_callback or (lambda _message: None)
    differences = BR.load_report_jsons(report_root, "differences")
    archive_rows: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    for report in differences:
        pair_id = str(report.get("source_archive_group", ""))
        for entry in report.get("entries", []):
            normalized = _entry_normalized_path(entry)
            folded = normalized.casefold()
            if entry.get("classification") != "changed" or entry.get("scope_status", "in_scope") != "in_scope":
                continue
            if not folded.startswith("data/x64/field/") or not folded.endswith((".elixir", ".elixir.gz")):
                continue
            if any(token in folded for token in ORDINARY_FIELD_EXCLUDED_TOKENS):
                skipped.append({"normalized_path": normalized, "member_key": "<archive>", "reason": "water_or_steam_scene_excluded"})
                continue
            source_ref = entry.get("source") or {}
            target_ref = entry.get("target") or {}
            if not source_ref or not target_ref:
                skipped.append({"normalized_path": normalized, "member_key": "<archive>", "reason": "source_or_target_archive_missing"})
                continue
            archive_rows.append({
                "pair_id": pair_id,
                "normalized_path": normalized,
                "source": source_ref,
                "target": target_ref,
            })
    archive_rows.sort(key=lambda row: str(row["normalized_path"]).casefold())
    archive_rows = archive_rows[:maximum_control_archives]

    controls: list[dict[str, Any]] = []
    for index, row in enumerate(archive_rows, start=1):
        if len(controls) >= maximum_control_members:
            break
        emit(f"ordinary control archive {index}/{len(archive_rows)}: {row['normalized_path']}")
        archives: dict[str, dict[str, Any] | None] = {"source": None, "target": None}
        failed = False
        for side in ("source", "target"):
            ref = row[side]
            local = BR.inventory_workspace_file(
                workspace_root, side, str(row["pair_id"]), str(ref.get("archive", "")), str(ref.get("path", ""))
            )
            if not local.is_file():
                skipped.append({"normalized_path": row["normalized_path"], "member_key": "<archive>", "reason": f"{side}_workspace_file_missing"})
                failed = True
                break
            try:
                archives[side] = BR.read_earc_archive(local, maximum_bytes=maximum_earc_bytes, include_member_payloads=True)
            except Exception as exc:  # normalized into metadata, never masks a selected payload
                skipped.append({"normalized_path": row["normalized_path"], "member_key": "<archive>", "reason": f"{side}_archive_parse_failed:{exc}"})
                failed = True
                break
        if failed:
            continue
        source_members = {str(item["comparison_key"]): item for item in (archives["source"] or {}).get("members", [])}
        target_members = {str(item["comparison_key"]): item for item in (archives["target"] or {}).get("members", [])}
        for member_key in sorted(set(source_members) & set(target_members), key=str.casefold):
            if len(controls) >= maximum_control_members:
                break
            left = source_members[member_key]
            right = target_members[member_key]
            if str(right.get("extension") or left.get("extension") or "").casefold() != ".opl2":
                continue
            source_payload = left.get("payload")
            target_payload = right.get("payload")
            if not isinstance(source_payload, (bytes, bytearray)) or not isinstance(target_payload, (bytes, bytearray)):
                skipped.append({"normalized_path": row["normalized_path"], "member_key": member_key, "reason": "member_payload_missing"})
                continue
            source_payload = bytes(source_payload)
            target_payload = bytes(target_payload)
            if source_payload == target_payload:
                continue
            if len(source_payload) != len(target_payload):
                skipped.append({"normalized_path": row["normalized_path"], "member_key": member_key, "reason": "source_target_member_size_mismatch"})
                continue
            if len(source_payload) > maximum_payload_bytes:
                skipped.append({"normalized_path": row["normalized_path"], "member_key": member_key, "reason": "member_payload_above_limit"})
                continue
            control_id = "ordinaryopl2_" + hashlib.sha256(
                (str(row["pair_id"]) + "|" + str(row["normalized_path"]).casefold() + "|" + member_key.casefold()).encode("utf-8")
            ).hexdigest()[:18]
            controls.append({
                "control_id": control_id,
                "pair_id": row["pair_id"],
                "normalized_path": row["normalized_path"],
                "member_key": member_key,
                "source_member_name": str(left.get("name", "")),
                "target_member_name": str(right.get("name", "")),
                "source_payload": source_payload,
                "target_payload": target_payload,
            })
    return controls, skipped


def evaluate_candidate(
    *, source: bytes, target: bytes, cells: Sequence[Mapping[str, Any]],
    candidate_kind: str, selected: Sequence[Mapping[str, Any]], classification: str,
    header_guard_bytes: int, tail_guard_bytes: int,
) -> dict[str, Any]:
    candidate = STAGE66.apply_cells(target, selected)
    reverse = STAGE66.reverse_cells(candidate, selected)
    target_distance = STAGE66.hamming_distance(source, target)
    candidate_distance = STAGE66.hamming_distance(source, candidate)
    return {
        "member_key": TARGET_OPL2_KEY,
        "candidate_kind": candidate_kind,
        "selected_cell_indices": ";".join(str(row["cell_index"]) for row in selected),
        "selected_cell_count": len(selected),
        "selected_transition_ids": ";".join(sorted({str(row["transition_id"]) for row in selected})),
        "candidate_sha256": hashlib.sha256(candidate).hexdigest(),
        "candidate_size": len(candidate),
        "target_distance_to_source": target_distance,
        "candidate_distance_to_source": candidate_distance,
        "distance_improvement": target_distance - candidate_distance,
        "exact_original": candidate == source,
        "guarded_header_preserved": candidate[:header_guard_bytes] == target[:header_guard_bytes],
        "guarded_tail_preserved": candidate[len(candidate) - tail_guard_bytes:] == target[len(target) - tail_guard_bytes:] if tail_guard_bytes else True,
        "exact_target_reverse_roundtrip": reverse == target,
        "passes_static_reconstruction_gates": (
            bool(selected) and candidate_distance < target_distance and reverse == target and len(candidate) == len(target)
        ),
        "classification": classification,
        "safe_to_build_local_prototype": False,
        "semantics_assigned": False,
        "review_status": "ordinary_field_control_metadata_only_no_opl2_payload_authorization",
    }


def collect(
    *, project_root: Path, workspace_root: Path, report_root: Path,
    maximum_earc_bytes: int = 512 * 1024 * 1024,
    maximum_payload_bytes: int = 8 * 1024 * 1024,
    maximum_control_archives: int = 48,
    maximum_control_members: int = 24,
    minimum_control_members: int = 3,
    header_guard_bytes: int = 16,
    tail_guard_bytes: int = 16,
    pair_loader: Callable[..., tuple[list[dict[str, Any]], list[dict[str, Any]]]] | None = None,
    control_loader: Callable[..., tuple[list[dict[str, Any]], list[dict[str, Any]]]] | None = None,
    progress_callback: Callable[[str], None] | None = None,
) -> tuple[Path, dict[str, Any]]:
    if minimum_control_members < 1 or maximum_control_members < minimum_control_members:
        raise OrdinaryFieldControlError("ordinary-control member limits are inconsistent")
    if maximum_control_archives < 1 or maximum_earc_bytes < 1 or maximum_payload_bytes < 1:
        raise OrdinaryFieldControlError("archive and payload limits must be positive")
    emit = progress_callback or (lambda message: print(f"[stage68] {message}", flush=True))

    with tempfile.TemporaryDirectory(prefix="br-stage68-") as temporary_name:
        temporary = Path(temporary_name)
        emit("validating stage-65 through stage-67 descriptor evidence")
        stage65_root = locate_report_root(report_root, "expanded_scene_effect_member_evidence", "BR_quartet_restoration_expanded_scene_effect_member_evidence.tar.zst", temporary / "stage65")
        stage66_root = locate_report_root(report_root, "bathroom_scene_descriptor_word_evidence", "BR_quartet_restoration_bathroom_scene_descriptor_word_evidence.tar.zst", temporary / "stage66")
        stage67_root = locate_report_root(report_root, "bathroom_sibling_descriptor_comparison_evidence", "BR_quartet_restoration_bathroom_sibling_descriptor_comparison_evidence.tar.zst", temporary / "stage67")
        shader_root = locate_report_root(report_root, "shader_effect_evidence", "BR_quartet_restoration_shader_effect_evidence.tar.zst", temporary / "shader")

        _stage67_summary, stage67_targets, _stage67_opl2, stage67_river_review, stage67_river_candidates = validate_stage67_report(stage67_root)
        _stage65_summary, stage65_rows = STAGE67.validate_stage65_report(stage65_root)
        _stage66_summary, _stage66_members, stage66_cells = STAGE67.validate_stage66_report(stage66_root)
        _shader_summary, payload_metadata = STAGE66.load_shader_metadata(shader_root)
        scope_pairs = STAGE67.load_scope_pairs(
            project_root=project_root, workspace_root=workspace_root, report_root=report_root,
            stage65_rows=stage65_rows, maximum_earc_bytes=maximum_earc_bytes, pair_loader=pair_loader,
        )
        payloads = STAGE67.verify_payload_metadata(
            stage65_rows=stage65_rows, pairs=scope_pairs, metadata=payload_metadata,
            maximum_payload_bytes=maximum_payload_bytes,
        )
        source_target, target_target = payloads[TARGET_OPL2_KEY]
        target_cells = STAGE66.build_word_cells(
            source=source_target, target=target_target, extension=".opl2",
            header_guard_bytes=header_guard_bytes, tail_guard_bytes=tail_guard_bytes,
        )
        STAGE67.compare_recomputed_cells(target_cells, stage66_cells[TARGET_OPL2_KEY], member_key=TARGET_OPL2_KEY)
        stage67_by_index = {parse_int(row.get("cell_index"), -1): row for row in stage67_targets}
        if set(stage67_by_index) != {int(row["cell_index"]) for row in target_cells}:
            raise OrdinaryFieldControlError("stage-67 target cell inventory does not match rehydrated payload")

        emit("discovering bounded ordinary non-water field OPL2 controls")
        loader = control_loader or load_ordinary_field_opl2_pairs
        controls, control_skipped = loader(
            workspace_root=workspace_root, report_root=report_root,
            maximum_earc_bytes=maximum_earc_bytes, maximum_payload_bytes=maximum_payload_bytes,
            maximum_control_archives=maximum_control_archives, maximum_control_members=maximum_control_members,
            progress_callback=emit,
        )
        if len(controls) > maximum_control_members:
            raise OrdinaryFieldControlError("ordinary control loader exceeded the member limit")

        control_member_rows: list[dict[str, Any]] = []
        control_cell_rows: list[dict[str, Any]] = []
        transition_counts: Counter[str] = Counter()
        transition_members: dict[str, set[str]] = defaultdict(set)
        source_word_counts: Counter[str] = Counter()
        target_word_counts: Counter[str] = Counter()
        source_word_members: dict[str, set[str]] = defaultdict(set)
        target_word_members: dict[str, set[str]] = defaultdict(set)

        emit(f"coalescing changed words in {len(controls)} ordinary controls")
        for index, control in enumerate(controls, start=1):
            emit(f"ordinary control member {index}/{len(controls)}: {control['member_key']}")
            source = control.get("source_payload")
            target = control.get("target_payload")
            if not isinstance(source, (bytes, bytearray)) or not isinstance(target, (bytes, bytearray)):
                raise OrdinaryFieldControlError("ordinary control loader returned a missing payload")
            source = bytes(source)
            target = bytes(target)
            if source == target or len(source) != len(target) or len(source) > maximum_payload_bytes:
                raise OrdinaryFieldControlError("ordinary control loader returned an invalid payload pair")
            cells = STAGE66.build_word_cells(
                source=source, target=target, extension=".opl2",
                header_guard_bytes=header_guard_bytes, tail_guard_bytes=tail_guard_bytes,
            )
            eligible = [row for row in cells if bool(row.get("eligible"))]
            member_key = str(control["member_key"])
            control_member_rows.append({
                "control_id": control["control_id"],
                "pair_id": control.get("pair_id", ""),
                "normalized_path": control.get("normalized_path", ""),
                "member_key": member_key,
                "source_member_name": control.get("source_member_name", ""),
                "target_member_name": control.get("target_member_name", ""),
                "source_size": len(source),
                "target_size": len(target),
                "target_distance_to_source": STAGE66.hamming_distance(source, target),
                "word_cell_count": len(cells),
                "eligible_word_cell_count": len(eligible),
                "excluded_word_cell_count": len(cells) - len(eligible),
                "source_sha256": hashlib.sha256(source).hexdigest(),
                "target_sha256": hashlib.sha256(target).hexdigest(),
                "scope_role": "ordinary_non_water_field_control",
                "semantics_assigned": False,
                "review_status": "bounded_ordinary_field_control_metadata_only",
            })
            for cell in cells:
                row = {
                    "control_id": control["control_id"],
                    "normalized_path": control.get("normalized_path", ""),
                    "member_key": member_key,
                    "cell_index": cell["cell_index"],
                    "start": cell["start"],
                    "end": cell["end"],
                    "source_hex": cell["source_hex"],
                    "target_hex": cell["target_hex"],
                    "changed_byte_mask": cell["changed_byte_mask"],
                    "transition_id": cell["transition_id"],
                    "eligible": cell["eligible"],
                    "exclusion_reasons": cell["exclusion_reasons"],
                    "semantics_assigned": False,
                    "review_status": "ordinary_field_word_transition_frequency_metadata_only",
                }
                control_cell_rows.append(row)
                if not bool(cell.get("eligible")):
                    continue
                transition = str(cell["transition_id"])
                source_hex = str(cell["source_hex"])
                target_hex = str(cell["target_hex"])
                transition_counts[transition] += 1
                transition_members[transition].add(member_key)
                source_word_counts[source_hex] += 1
                target_word_counts[target_hex] += 1
                source_word_members[source_hex].add(member_key)
                target_word_members[target_hex].add(member_key)

        control_scope_sufficient = len(control_member_rows) >= minimum_control_members
        emit("classifying bathroom transitions against ordinary controls")
        comparison_rows: list[dict[str, Any]] = []
        cross_scope_exact_unique: list[dict[str, Any]] = []
        strict_cross_scope_unique: list[dict[str, Any]] = []
        ordinary_exact_shared: list[dict[str, Any]] = []
        water_exact_shared: list[dict[str, Any]] = []
        for cell in target_cells:
            index = int(cell["cell_index"])
            prior = stage67_by_index[index]
            transition_id = str(cell["transition_id"])
            ordinary_exact = transition_counts[transition_id]
            ordinary_exact_members = sorted(transition_members[transition_id], key=str.casefold)
            ordinary_source = source_word_counts[str(cell["source_hex"])]
            ordinary_target = target_word_counts[str(cell["target_hex"])]
            sibling_exact = parse_int(prior.get("sibling_exact_transition_count"), 0)
            sibling_source = parse_int(prior.get("sibling_source_word_count"), 0)
            sibling_target = parse_int(prior.get("sibling_target_word_count"), 0)
            if ordinary_exact:
                classification = "exact_transition_seen_in_ordinary_field_control"
                ordinary_exact_shared.append(cell)
            elif sibling_exact:
                classification = "exact_transition_shared_only_with_water_scene_control"
                water_exact_shared.append(cell)
            elif ordinary_source and ordinary_target:
                classification = "source_and_target_words_seen_in_ordinary_controls_without_exact_transition"
            elif ordinary_source:
                classification = "source_word_seen_in_ordinary_controls_target_differs"
            elif ordinary_target:
                classification = "target_word_seen_in_ordinary_controls_source_differs"
            else:
                classification = "transition_absent_from_water_and_ordinary_control_exact_scopes"
            if not sibling_exact and not ordinary_exact:
                cross_scope_exact_unique.append(cell)
            if (
                not sibling_exact and not ordinary_exact
                and not sibling_source and not sibling_target
                and not ordinary_source and not ordinary_target
            ):
                strict_cross_scope_unique.append(cell)
            comparison_rows.append({
                **{field: prior.get(field, "") for field in prior},
                "ordinary_exact_transition_count": ordinary_exact,
                "ordinary_exact_transition_member_count": len(ordinary_exact_members),
                "ordinary_exact_transition_members": ";".join(ordinary_exact_members),
                "ordinary_source_word_count": ordinary_source,
                "ordinary_source_word_member_count": len(source_word_members[str(cell["source_hex"])]),
                "ordinary_target_word_count": ordinary_target,
                "ordinary_target_word_member_count": len(target_word_members[str(cell["target_hex"])]),
                "cross_scope_classification": classification,
                "control_scope_sufficient": control_scope_sufficient,
                "semantics_assigned": False,
                "review_status": "water_and_ordinary_field_control_comparison_only",
            })

        candidate_sets = [
            (
                "cross_scope_exact_transition_unique_set", cross_scope_exact_unique,
                "exact_transition_absent_from_water_and_ordinary_controls_semantics_unassigned",
            ),
            (
                "strict_cross_scope_unique_word_pair_set", strict_cross_scope_unique,
                "source_target_word_pair_absent_from_water_and_ordinary_controls_semantics_unassigned",
            ),
            (
                "ordinary_field_shared_exact_transition_set", ordinary_exact_shared,
                "ordinary_field_shared_transition_set_remaster_confounded",
            ),
            (
                "water_scene_shared_exact_transition_set", water_exact_shared,
                "water_scene_shared_transition_set_censorship_or_remaster_confounded",
            ),
            (
                "complete_hinako_bathroom_word_set", target_cells,
                "exact_original_available_but_cross_scope_shared_and_opaque_fields_remain",
            ),
        ]
        candidate_rows: list[dict[str, Any]] = []
        seen_sets: set[tuple[int, ...]] = set()
        for kind, selected, classification in candidate_sets:
            indices = tuple(sorted(int(row["cell_index"]) for row in selected))
            if not indices or indices in seen_sets:
                continue
            seen_sets.add(indices)
            candidate_rows.append(evaluate_candidate(
                source=source_target, target=target_target, cells=target_cells,
                candidate_kind=kind, selected=selected, classification=classification,
                header_guard_bytes=header_guard_bytes, tail_guard_bytes=tail_guard_bytes,
            ))

        emit("reviewing the proven repeated river-tail exception")
        exact_river = next(row for row in stage67_river_candidates if parse_bool(row.get("exact_original")))
        supported_tail = [
            row for row in stage67_river_review
            if parse_bool(row.get("repeated_tail_guard_exception_supported"))
        ]
        river_authorized = (
            len(supported_tail) == 1
            and parse_bool(supported_tail[0].get("bytes_after_word_identical"))
            and parse_int(supported_tail[0].get("transition_occurrence_count"), 0) >= 3
            and parse_int(supported_tail[0].get("eligible_support_occurrence_count"), 0) >= 2
            and parse_bool(exact_river.get("exact_original"))
            and parse_bool(exact_river.get("passes_static_reconstruction_gates"))
            and parse_bool(exact_river.get("exact_target_reverse_roundtrip"))
            and parse_bool(exact_river.get("generic_tail_guard_intentionally_not_used_for_one_repeated_cell"))
            and parse_int(exact_river.get("candidate_distance_to_source"), -1) == 0
            and parse_int(exact_river.get("selected_cell_count"), -1) == 7
        )
        river_review_rows = [{
            "member_key": RIVER_KEY,
            "candidate_kind": exact_river.get("candidate_kind", ""),
            "selected_cell_indices": exact_river.get("selected_cell_indices", ""),
            "selected_cell_count": exact_river.get("selected_cell_count", ""),
            "candidate_sha256": exact_river.get("candidate_sha256", ""),
            "candidate_size": exact_river.get("candidate_size", ""),
            "target_distance_to_source": exact_river.get("target_distance_to_source", ""),
            "candidate_distance_to_source": exact_river.get("candidate_distance_to_source", ""),
            "distance_improvement": exact_river.get("distance_improvement", ""),
            "exact_original": exact_river.get("exact_original", ""),
            "exact_target_reverse_roundtrip": exact_river.get("exact_target_reverse_roundtrip", ""),
            "repeated_tail_guard_exception_rows": len(supported_tail),
            "tail_transition_occurrence_count": supported_tail[0].get("transition_occurrence_count", "") if supported_tail else "",
            "tail_eligible_support_occurrence_count": supported_tail[0].get("eligible_support_occurrence_count", "") if supported_tail else "",
            "bytes_after_tail_word_identical": supported_tail[0].get("bytes_after_word_identical", "") if supported_tail else "",
            "static_local_prototype_authorized": river_authorized,
            "semantics_assigned": False,
            "classification": "exact_original_small_river_descriptor_supported_by_repeated_tail_transition" if river_authorized else "river_descriptor_static_promotion_blocked",
            "review_status": "static_member_prototype_authorization_only_no_parent_archive_or_game_write" if river_authorized else "metadata_only",
        }]

        evidence_root = report_root / EVIDENCE_DIR_NAME
        if evidence_root.exists():
            shutil.rmtree(evidence_root)
        evidence_root.mkdir(parents=True, exist_ok=True)
        member_fields = [
            "control_id", "pair_id", "normalized_path", "member_key", "source_member_name", "target_member_name",
            "source_size", "target_size", "target_distance_to_source", "word_cell_count", "eligible_word_cell_count",
            "excluded_word_cell_count", "source_sha256", "target_sha256", "scope_role", "semantics_assigned", "review_status",
        ]
        cell_fields = [
            "control_id", "normalized_path", "member_key", "cell_index", "start", "end", "source_hex", "target_hex",
            "changed_byte_mask", "transition_id", "eligible", "exclusion_reasons", "semantics_assigned", "review_status",
        ]
        comparison_fields = list(dict.fromkeys(list(stage67_targets[0]) + [
            "ordinary_exact_transition_count", "ordinary_exact_transition_member_count", "ordinary_exact_transition_members",
            "ordinary_source_word_count", "ordinary_source_word_member_count", "ordinary_target_word_count",
            "ordinary_target_word_member_count", "cross_scope_classification", "control_scope_sufficient",
            "semantics_assigned", "review_status",
        ]))
        candidate_fields = [
            "member_key", "candidate_kind", "selected_cell_indices", "selected_cell_count", "selected_transition_ids",
            "candidate_sha256", "candidate_size", "target_distance_to_source", "candidate_distance_to_source",
            "distance_improvement", "exact_original", "guarded_header_preserved", "guarded_tail_preserved",
            "exact_target_reverse_roundtrip", "passes_static_reconstruction_gates", "classification",
            "safe_to_build_local_prototype", "semantics_assigned", "review_status",
        ]
        river_fields = list(river_review_rows[0])
        skipped_fields = ["normalized_path", "member_key", "reason"]
        write_tsv(evidence_root / "BATHROOM_ORDINARY_FIELD_CONTROL_MEMBERS.tsv", member_fields, control_member_rows)
        write_tsv(evidence_root / "BATHROOM_ORDINARY_FIELD_CONTROL_WORD_CELLS.tsv", cell_fields, control_cell_rows)
        write_tsv(evidence_root / "BATHROOM_TARGET_ORDINARY_CONTROL_COMPARISONS.tsv", comparison_fields, comparison_rows)
        write_tsv(evidence_root / "BATHROOM_OPL2_CROSS_SCOPE_CANDIDATES.tsv", candidate_fields, candidate_rows)
        write_tsv(evidence_root / "BATHROOM_RIVER_STATIC_PROMOTION_REVIEW.tsv", river_fields, river_review_rows)
        write_tsv(evidence_root / "BATHROOM_ORDINARY_FIELD_CONTROL_SKIPPED.tsv", skipped_fields, control_skipped)

        exact_ordinary_shared = sum(1 for row in comparison_rows if parse_int(row.get("ordinary_exact_transition_count"), 0) > 0)
        summary = {
            "type": "br_quartet_restoration_bathroom_ordinary_field_control_evidence_summary",
            "format_version": 1,
            "tool_version": TOOL_VERSION,
            "source_stage67_tool_version": EXPECTED_STAGE67_TOOL_VERSION,
            "status": "bathroom_ordinary_field_control_and_river_static_promotion_audit_complete_no_payload_written",
            "ordinary_control_member_rows": len(control_member_rows),
            "ordinary_control_word_cell_rows": len(control_cell_rows),
            "ordinary_control_eligible_word_cell_rows": sum(1 for row in control_cell_rows if parse_bool(row.get("eligible"))),
            "ordinary_control_scope_sufficient": control_scope_sufficient,
            "target_opl2_cell_rows": len(comparison_rows),
            "target_opl2_cells_shared_by_exact_transition_with_ordinary_control": exact_ordinary_shared,
            "target_opl2_cross_scope_exact_unique_cells": len(cross_scope_exact_unique),
            "target_opl2_strict_cross_scope_unique_word_pair_cells": len(strict_cross_scope_unique),
            "opl2_candidate_rows": len(candidate_rows),
            "opl2_exact_original_candidate_rows": sum(1 for row in candidate_rows if parse_bool(row.get("exact_original"))),
            "opl2_safe_local_prototype_rows": 0,
            "river_static_promotion_review_rows": 1,
            "river_static_local_prototype_authorized_rows": 1 if river_authorized else 0,
            "safe_local_prototype_rows": 1 if river_authorized else 0,
            "skipped_rows": len(control_skipped),
            "parameters": {
                "maximum_earc_bytes": maximum_earc_bytes,
                "maximum_payload_bytes": maximum_payload_bytes,
                "maximum_control_archives": maximum_control_archives,
                "maximum_control_members": maximum_control_members,
                "minimum_control_members": minimum_control_members,
                "header_guard_bytes": header_guard_bytes,
                "tail_guard_bytes": tail_guard_bytes,
                "ordinary_field_excluded_tokens": list(ORDINARY_FIELD_EXCLUDED_TOKENS),
            },
            "policy": {
                "installed_games_modified": False,
                "candidate_member_payloads_written": False,
                "parent_archive_repack_performed": False,
                "pak_repack_performed": False,
                "core_registry_modified": False,
                "activation_or_rollback_invoked": False,
                "runtime_validation_inferred": False,
                "censorship_classification_inferred": False,
                "opaque_binary_field_semantics_inferred": False,
                "ordinary_controls_are_bounded_non_water_field_descriptors_not_format_proof": True,
                "opl2_exact_original_reconstruction_is_not_automatic_prototype_authorization": True,
                "river_authorization_is_limited_to_a_local_member_prototype": True,
                "translation_or_dlc_workstreams_modified": False,
            },
            "next_action": (
                "Upload this report. If the river static authorization row is present, build only the small local river.bin member prototype next. "
                "Keep the Hinako OPL2 metadata-only unless ordinary controls produce a narrowly isolated exact-Original subset; do not rebuild Elixir, "
                "repack a PAK, modify registry, activate profiles or write to the game from this stage."
            ),
        }
        atomic_json(evidence_root / "SUMMARY.json", summary)
        output = report_root / REPORT_NAME
        make_report_archive(evidence_root, output)
        emit(f"report written: {output}")
        return output, summary


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path, default=PROJECT_ROOT_DEFAULT)
    parser.add_argument("--workspace-root", type=Path)
    parser.add_argument("--report-root", type=Path)
    parser.add_argument("--maximum-earc-bytes", type=int, default=512 * 1024 * 1024)
    parser.add_argument("--maximum-payload-bytes", type=int, default=8 * 1024 * 1024)
    parser.add_argument("--maximum-control-archives", type=int, default=48)
    parser.add_argument("--maximum-control-members", type=int, default=24)
    parser.add_argument("--minimum-control-members", type=int, default=3)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    project_root = args.project_root.resolve()
    workspace_root = (args.workspace_root or project_root / ".local/build/quartet_restoration").resolve()
    report_root = (args.report_root or project_root / ".local/reports/quartet_restoration").resolve()
    try:
        output, summary = collect(
            project_root=project_root, workspace_root=workspace_root, report_root=report_root,
            maximum_earc_bytes=args.maximum_earc_bytes, maximum_payload_bytes=args.maximum_payload_bytes,
            maximum_control_archives=args.maximum_control_archives,
            maximum_control_members=args.maximum_control_members,
            minimum_control_members=args.minimum_control_members,
        )
    except (OrdinaryFieldControlError, STAGE67.SiblingDescriptorError, STAGE66.BathroomWordAuditError, BR.RestorationError, OSError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print(f"Report: {output}")
    print(f"Ordinary control members: {summary['ordinary_control_member_rows']}")
    print(f"Control scope sufficient: {summary['ordinary_control_scope_sufficient']}")
    print(f"Bathroom cells shared exactly with ordinary controls: {summary['target_opl2_cells_shared_by_exact_transition_with_ordinary_control']}")
    print(f"River static prototype authorizations: {summary['river_static_local_prototype_authorized_rows']}")
    print(f"Safe local prototypes: {summary['safe_local_prototype_rows']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
