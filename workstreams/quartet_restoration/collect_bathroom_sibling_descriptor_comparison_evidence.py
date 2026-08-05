#!/usr/bin/env python3
"""Compare the Hinako bathroom descriptor against sibling water-scene controls.

Stage 66 proved that replacing all changed 32-bit cells in the Hinako bathroom
OPL2 reconstructs Original exactly, but that fact alone cannot distinguish
scene-specific steam/water parameters from serializer or remaster-wide changes.
It also left one repeated river-BIN word blocked only by the generic tail guard.

This stage remains read-only.  It rehydrates the bathroom, shower and pool OPL2
members, compares exact source->Quartet word transitions across that bounded
scope, and tests target-specific versus sibling-shared inverse subsets.  It also
audits whether the guarded river word is supported by identical earlier
occurrences and unchanged bytes after the word.  No member payload, Elixir, PAK,
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

TOOL_VERSION = "0.0.77"
REPORT_NAME = "BR_quartet_restoration_bathroom_sibling_descriptor_comparison_evidence.tar.zst"
EVIDENCE_DIR_NAME = "bathroom_sibling_descriptor_comparison_evidence"

EXPECTED_STAGE65_TOOL_VERSION = "0.0.75"
EXPECTED_STAGE66_TOOL_VERSION = "0.0.76"

TARGET_OPL2_KEY = "s89_s_hinako_bath_room_01.opl2#0"
RIVER_KEY = "s89_s_hinako_bath_room_01_river.bin#0"
SIBLING_OPL2_KEYS = (
    "s86_s_shower_room_01.opl2#0",
    "s84_m_pool_01.opl2#0",
)
SCOPE_KEYS = (TARGET_OPL2_KEY, *SIBLING_OPL2_KEYS, RIVER_KEY)

EXPECTED_STAGE65_ROWS: dict[str, dict[str, object]] = {
    TARGET_OPL2_KEY: {
        "candidate_id": "effectcand_4d378854f72fd55bcf",
        "rule_id": "bathroom_scene",
        "domain": "steam_and_water_visibility",
        "priority": "critical",
        "normalized_path": "data/x64/field/s89_s_hinako_bath_room_01/s89_s_hinako_bath_room_01.elixir.gz",
        "extension": ".opl2",
        "source_size": 2180,
        "target_size": 2180,
        "target_distance_to_source": 146,
    },
    RIVER_KEY: {
        "candidate_id": "effectcand_4d378854f72fd55bcf",
        "rule_id": "bathroom_scene",
        "domain": "steam_and_water_visibility",
        "priority": "critical",
        "normalized_path": "data/x64/field/s89_s_hinako_bath_room_01/s89_s_hinako_bath_room_01.elixir.gz",
        "extension": ".bin",
        "source_size": 252,
        "target_size": 252,
        "target_distance_to_source": 22,
    },
    "s86_s_shower_room_01.opl2#0": {
        "candidate_id": "effectcand_6830d15599baa3b292",
        "rule_id": "shower_scene",
        "domain": "steam_and_wet_clothing",
        "priority": "critical",
        "normalized_path": "data/x64/field/s86_s_shower_room_01/s86_s_shower_room_01.elixir.gz",
        "extension": ".opl2",
        "source_size": 1469,
        "target_size": 1469,
        "target_distance_to_source": 112,
    },
    "s84_m_pool_01.opl2#0": {
        "candidate_id": "effectcand_c7c64d33c3b345c4c7",
        "rule_id": "pool_scene",
        "domain": "water_visibility",
        "priority": "critical",
        "normalized_path": "data/x64/field/s84_m_pool_01/s84_m_pool_01.elixir.gz",
        "extension": ".opl2",
        "source_size": 3125,
        "target_size": 3125,
        "target_distance_to_source": 386,
    },
}


class SiblingDescriptorError(RuntimeError):
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
        raise SiblingDescriptorError(f"unsafe report archive member: {raw}")
    return path.as_posix()


def read_tsv(path: Path, *, required: bool = True) -> list[dict[str, str]]:
    if not path.is_file():
        if required:
            raise SiblingDescriptorError(f"missing prerequisite table: {path}")
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
        raise SiblingDescriptorError(f"missing prerequisite JSON: {path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SiblingDescriptorError(f"invalid JSON {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise SiblingDescriptorError(f"expected JSON object: {path}")
    return value


def atomic_json(path: Path, value: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def extract_archive(archive: Path, destination: Path) -> Path:
    if not archive.is_file():
        raise SiblingDescriptorError(f"missing prerequisite report archive: {archive}")
    listed = subprocess.run(
        ["tar", "--zstd", "-tf", str(archive)],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if listed.returncode != 0:
        raise SiblingDescriptorError(f"cannot list {archive}: {listed.stderr.strip()}")
    roots: set[str] = set()
    for raw in listed.stdout.splitlines():
        if raw.strip():
            roots.add(PurePosixPath(safe_member_name(raw.strip())).parts[0])
    if len(roots) != 1:
        raise SiblingDescriptorError(f"expected one report root in {archive}, found {sorted(roots)}")
    destination.mkdir(parents=True, exist_ok=True)
    completed = subprocess.run(
        ["tar", "--zstd", "-xf", str(archive), "-C", str(destination)],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if completed.returncode != 0:
        raise SiblingDescriptorError(f"cannot extract {archive}: {completed.stderr.strip()}")
    return destination / next(iter(roots))


def locate_report_root(report_root: Path, directory_name: str, archive_name: str, temporary: Path) -> Path:
    direct = report_root / directory_name
    if direct.is_dir():
        return direct
    return extract_archive(report_root / archive_name, temporary)


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
        raise SiblingDescriptorError(f"cannot create report archive: {completed.stderr.strip()}")
    os.replace(temporary, output)


def validate_stage66_report(root: Path) -> tuple[dict[str, Any], dict[str, dict[str, str]], dict[str, list[dict[str, str]]]]:
    summary = load_json(root / "SUMMARY.json")
    if summary.get("type") != "br_quartet_restoration_bathroom_scene_descriptor_word_evidence_summary":
        raise SiblingDescriptorError("stage-66 report has an unexpected summary type")
    if summary.get("tool_version") != EXPECTED_STAGE66_TOOL_VERSION:
        raise SiblingDescriptorError("stage-66 report must use tool version 0.0.76")
    if summary.get("status") != "bathroom_scene_descriptor_word_cell_audit_complete_no_payload_written_manual_decode_required":
        raise SiblingDescriptorError("stage-66 report is not complete")
    expected_counts = {
        "target_member_rows": 2,
        "word_cell_rows": 68,
        "transition_group_rows": 54,
        "candidate_rows": 78,
        "passing_candidate_rows": 78,
        "exact_original_candidate_rows": 1,
        "exact_original_member_rows": 1,
        "full_word_reconstruction_member_rows": 1,
        "safe_local_prototype_rows": 0,
        "skipped_rows": 0,
    }
    for field, expected in expected_counts.items():
        if parse_int(summary.get(field), -1) != expected:
            raise SiblingDescriptorError(f"stage-66 summary field {field} must equal {expected}")
    policy = summary.get("policy") or {}
    if not isinstance(policy, dict):
        raise SiblingDescriptorError("stage-66 policy is malformed")
    forbidden = (
        "installed_games_modified",
        "candidate_member_payloads_written",
        "parent_archive_repack_performed",
        "pak_repack_performed",
        "core_registry_modified",
        "activation_or_rollback_invoked",
        "runtime_validation_inferred",
        "censorship_classification_inferred",
        "opaque_binary_field_semantics_inferred",
        "translation_or_dlc_workstreams_modified",
    )
    if any(parse_bool(policy.get(field)) for field in forbidden):
        raise SiblingDescriptorError("stage-66 report performed or inferred a forbidden action")

    member_rows = read_tsv(root / "BATHROOM_SCENE_DESCRIPTOR_MEMBERS.tsv")
    if len(member_rows) != 2:
        raise SiblingDescriptorError("stage-66 member table must contain exactly two rows")
    members = {str(row.get("member_key", "")): row for row in member_rows}
    if set(members) != {TARGET_OPL2_KEY, RIVER_KEY}:
        raise SiblingDescriptorError("stage-66 member table does not contain the expected bathroom members")
    expected_member_values = {
        TARGET_OPL2_KEY: {
            "target_distance_to_source": 146,
            "word_cell_count": 61,
            "eligible_word_cell_count": 61,
            "excluded_word_cell_count": 0,
            "best_candidate_distance_to_source": 0,
            "best_distance_improvement": 146,
            "best_exact_original": True,
            "all_word_cells_eligible": True,
            "classification": "exact_original_word_reconstruction_available_manual_decode_required",
        },
        RIVER_KEY: {
            "target_distance_to_source": 22,
            "word_cell_count": 7,
            "eligible_word_cell_count": 6,
            "excluded_word_cell_count": 1,
            "best_candidate_distance_to_source": 3,
            "best_distance_improvement": 19,
            "best_exact_original": False,
            "all_word_cells_eligible": False,
            "classification": "partial_word_reconstruction_evidence_only",
        },
    }
    for member_key, expected in expected_member_values.items():
        row = members[member_key]
        for field, value in expected.items():
            actual = row.get(field, "")
            if isinstance(value, bool):
                if parse_bool(actual) is not value:
                    raise SiblingDescriptorError(f"unexpected stage-66 {field} for {member_key}")
            elif isinstance(value, int):
                if parse_int(actual, -1) != value:
                    raise SiblingDescriptorError(f"unexpected stage-66 {field} for {member_key}")
            elif str(actual) != value:
                raise SiblingDescriptorError(f"unexpected stage-66 {field} for {member_key}")
        if parse_bool(row.get("safe_to_build_local_prototype_without_manual_decode")):
            raise SiblingDescriptorError("stage-66 member unexpectedly authorizes a local prototype")

    cell_rows = read_tsv(root / "BATHROOM_SCENE_DESCRIPTOR_WORD_CELLS.tsv")
    by_member: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in cell_rows:
        by_member[str(row.get("member_key", ""))].append(row)
    if len(by_member.get(TARGET_OPL2_KEY, [])) != 61 or len(by_member.get(RIVER_KEY, [])) != 7:
        raise SiblingDescriptorError("stage-66 word-cell table has unexpected member counts")
    return summary, members, dict(by_member)


def validate_stage65_report(root: Path) -> tuple[dict[str, Any], dict[str, dict[str, str]]]:
    summary = load_json(root / "SUMMARY.json")
    if summary.get("type") != "br_quartet_restoration_expanded_scene_effect_member_evidence_summary":
        raise SiblingDescriptorError("stage-65 report has an unexpected summary type")
    if summary.get("tool_version") != EXPECTED_STAGE65_TOOL_VERSION:
        raise SiblingDescriptorError("stage-65 report must use tool version 0.0.75")
    if summary.get("status") != "expanded_scene_effect_member_inverse_range_audit_complete_no_payload_written_runtime_deferred":
        raise SiblingDescriptorError("stage-65 report is not complete")
    expected_counts = {
        "expanded_focused_binary_delta_rows_selected": 185,
        "rehydrated_member_rows": 185,
        "analyzed_member_rows": 185,
        "promotable_exact_original_member_rows": 0,
        "partial_inverse_evidence_member_rows": 13,
        "skipped_rows": 0,
    }
    for field, expected in expected_counts.items():
        if parse_int(summary.get(field), -1) != expected:
            raise SiblingDescriptorError(f"stage-65 summary field {field} must equal {expected}")
    rows = read_tsv(root / "EXPANDED_SCENE_EFFECT_MEMBERS.tsv")
    selected: dict[str, dict[str, str]] = {}
    for row in rows:
        member_key = str(row.get("member_key", ""))
        if member_key in EXPECTED_STAGE65_ROWS:
            if member_key in selected:
                raise SiblingDescriptorError(f"duplicate stage-65 scope row: {member_key}")
            selected[member_key] = row
    if set(selected) != set(EXPECTED_STAGE65_ROWS):
        raise SiblingDescriptorError("stage-65 report does not contain the four expected descriptor rows")
    for member_key, expected in EXPECTED_STAGE65_ROWS.items():
        row = selected[member_key]
        for field, value in expected.items():
            actual = row.get(field, "")
            if isinstance(value, int):
                if parse_int(actual, -1) != value:
                    raise SiblingDescriptorError(f"unexpected stage-65 {field} for {member_key}")
            elif str(actual).casefold() != str(value).casefold():
                raise SiblingDescriptorError(f"unexpected stage-65 {field} for {member_key}")
    return summary, selected


def row_key(row: Mapping[str, object]) -> tuple[str, str, str, str, str]:
    return (
        str(row.get("candidate_id", "")),
        str(row.get("normalized_path", "")),
        str(row.get("member_key", "")),
        str(row.get("source_member_name", "")),
        str(row.get("target_member_name", "")),
    )


def load_scope_pairs(
    *, project_root: Path, workspace_root: Path, report_root: Path,
    stage65_rows: Mapping[str, Mapping[str, str]],
    maximum_earc_bytes: int,
    pair_loader: Callable[..., tuple[list[dict[str, Any]], list[dict[str, Any]]]] | None = None,
) -> dict[str, dict[str, Any]]:
    rules_file = project_root / "titles/blue_reflection/modules/quartet_restoration/mappings/effect_material_rules.tsv"
    loader = pair_loader or BR.load_focused_render_pairs
    pairs, skipped = loader(
        workspace_root=workspace_root,
        report_root=report_root,
        rules_file=rules_file,
        maximum_earc_bytes=maximum_earc_bytes,
    )
    if skipped:
        raise SiblingDescriptorError(f"focused render pair loader skipped {len(skipped)} rows")
    pair_map = {row_key(row): row for row in pairs}
    result: dict[str, dict[str, Any]] = {}
    for member_key, report_row in stage65_rows.items():
        key = row_key(report_row)
        pair = pair_map.get(key)
        if pair is None:
            raise SiblingDescriptorError(f"rehydrated pair missing for {member_key}")
        result[member_key] = pair
    return result


def verify_payload_metadata(
    *, stage65_rows: Mapping[str, Mapping[str, str]],
    pairs: Mapping[str, Mapping[str, Any]],
    metadata: Mapping[tuple[str, str, str, str], Mapping[str, str]],
    maximum_payload_bytes: int,
) -> dict[str, tuple[bytes, bytes]]:
    payloads: dict[str, tuple[bytes, bytes]] = {}
    for member_key, report_row in stage65_rows.items():
        pair = pairs[member_key]
        source = pair.get("source_payload")
        target = pair.get("target_payload")
        if not isinstance(source, (bytes, bytearray)) or not isinstance(target, (bytes, bytearray)):
            raise SiblingDescriptorError(f"source or target payload missing for {member_key}")
        source = bytes(source)
        target = bytes(target)
        if len(source) > maximum_payload_bytes or len(target) > maximum_payload_bytes:
            raise SiblingDescriptorError(f"payload exceeds stage-67 limit: {member_key}")
        if len(source) != len(target):
            raise SiblingDescriptorError(f"source/target size mismatch for {member_key}")
        expected_distance = parse_int(report_row.get("target_distance_to_source"), -1)
        if STAGE66.hamming_distance(source, target) != expected_distance:
            raise SiblingDescriptorError(f"stage-65 distance mismatch for {member_key}")
        for side, payload in (("source", source), ("target", target)):
            key = (
                str(report_row.get("candidate_id", "")),
                str(report_row.get("normalized_path", "")),
                member_key,
                side,
            )
            row = metadata.get(key)
            if row is None:
                raise SiblingDescriptorError(f"missing shader payload metadata for {member_key} side={side}")
            if parse_int(row.get("payload_size"), -1) != len(payload):
                raise SiblingDescriptorError(f"payload size mismatch for {member_key} side={side}")
            if str(row.get("payload_sha256", "")) != hashlib.sha256(payload).hexdigest():
                raise SiblingDescriptorError(f"payload hash mismatch for {member_key} side={side}")
        payloads[member_key] = (source, target)
    return payloads


def compare_recomputed_cells(
    recomputed: Sequence[Mapping[str, Any]],
    reported: Sequence[Mapping[str, str]],
    *, member_key: str,
) -> None:
    by_index = {parse_int(row.get("cell_index"), -1): row for row in reported}
    if len(by_index) != len(recomputed):
        raise SiblingDescriptorError(f"stage-66 cell count mismatch for {member_key}")
    for cell in recomputed:
        index = int(cell["cell_index"])
        row = by_index.get(index)
        if row is None:
            raise SiblingDescriptorError(f"stage-66 cell missing for {member_key} index={index}")
        for field in ("start", "end", "source_hex", "target_hex", "transition_id"):
            if str(row.get(field, "")) != str(cell.get(field, "")):
                raise SiblingDescriptorError(f"stage-66 cell field {field} mismatch for {member_key} index={index}")
        if parse_bool(row.get("eligible")) is not bool(cell.get("eligible")):
            raise SiblingDescriptorError(f"stage-66 eligibility mismatch for {member_key} index={index}")
        if str(row.get("exclusion_reasons", "")) != str(cell.get("exclusion_reasons", "")):
            raise SiblingDescriptorError(f"stage-66 exclusion mismatch for {member_key} index={index}")


def apply_and_measure(
    *, member_key: str, source: bytes, target: bytes, cells: Sequence[Mapping[str, Any]],
    candidate_kind: str, selected: Sequence[Mapping[str, Any]],
    header_guard_bytes: int, tail_guard_bytes: int,
    classification: str,
) -> dict[str, Any]:
    candidate = STAGE66.apply_cells(target, selected)
    reversed_target = STAGE66.reverse_cells(candidate, selected)
    target_distance = STAGE66.hamming_distance(source, target)
    candidate_distance = STAGE66.hamming_distance(source, candidate)
    header_preserved = candidate[:header_guard_bytes] == target[:header_guard_bytes]
    tail_preserved = (
        candidate[len(candidate) - tail_guard_bytes:] == target[len(target) - tail_guard_bytes:]
        if tail_guard_bytes else True
    )
    return {
        "member_key": member_key,
        "candidate_kind": candidate_kind,
        "selected_cell_indices": ";".join(str(cell["cell_index"]) for cell in selected),
        "selected_cell_count": len(selected),
        "selected_transition_ids": ";".join(sorted({str(cell["transition_id"]) for cell in selected})),
        "candidate_sha256": hashlib.sha256(candidate).hexdigest(),
        "candidate_size": len(candidate),
        "target_distance_to_source": target_distance,
        "candidate_distance_to_source": candidate_distance,
        "distance_improvement": target_distance - candidate_distance,
        "exact_original": candidate == source,
        "guarded_header_preserved": header_preserved,
        "guarded_tail_preserved": tail_preserved,
        "exact_target_reverse_roundtrip": reversed_target == target,
        "passes_static_reconstruction_gates": (
            len(candidate) == len(target)
            and header_preserved
            and reversed_target == target
            and candidate_distance < target_distance
        ),
        "classification": classification,
        "safe_to_build_local_prototype": False,
        "semantics_assigned": False,
        "review_status": "sibling_control_metadata_only_no_payload_authorization",
    }


def collect(
    *, project_root: Path, workspace_root: Path, report_root: Path,
    maximum_earc_bytes: int = 512 * 1024 * 1024,
    maximum_payload_bytes: int = 8 * 1024 * 1024,
    header_guard_bytes: int = 16,
    tail_guard_bytes: int = 16,
    pair_loader: Callable[..., tuple[list[dict[str, Any]], list[dict[str, Any]]]] | None = None,
    progress_callback: Callable[[str], None] | None = None,
) -> tuple[Path, dict[str, Any]]:
    if maximum_earc_bytes < 1 or maximum_payload_bytes < 1:
        raise SiblingDescriptorError("archive and payload limits must be positive")
    if header_guard_bytes < 0 or tail_guard_bytes < 0:
        raise SiblingDescriptorError("guard sizes cannot be negative")
    emit = progress_callback or (lambda message: print(f"[stage67] {message}", flush=True))

    with tempfile.TemporaryDirectory(prefix="br-stage67-") as temporary_name:
        temporary = Path(temporary_name)
        emit("validating stage-65, stage-66 and shader evidence")
        stage65_root = locate_report_root(
            report_root,
            "expanded_scene_effect_member_evidence",
            "BR_quartet_restoration_expanded_scene_effect_member_evidence.tar.zst",
            temporary / "stage65",
        )
        stage66_root = locate_report_root(
            report_root,
            "bathroom_scene_descriptor_word_evidence",
            "BR_quartet_restoration_bathroom_scene_descriptor_word_evidence.tar.zst",
            temporary / "stage66",
        )
        shader_root = locate_report_root(
            report_root,
            "shader_effect_evidence",
            "BR_quartet_restoration_shader_effect_evidence.tar.zst",
            temporary / "shader",
        )
        stage65_summary, stage65_rows = validate_stage65_report(stage65_root)
        stage66_summary, _stage66_members, stage66_cells = validate_stage66_report(stage66_root)
        shader_summary, payload_metadata = STAGE66.load_shader_metadata(shader_root)

        emit("rehydrating bathroom, shower and pool descriptor controls")
        pairs = load_scope_pairs(
            project_root=project_root,
            workspace_root=workspace_root,
            report_root=report_root,
            stage65_rows=stage65_rows,
            maximum_earc_bytes=maximum_earc_bytes,
            pair_loader=pair_loader,
        )
        payloads = verify_payload_metadata(
            stage65_rows=stage65_rows,
            pairs=pairs,
            metadata=payload_metadata,
            maximum_payload_bytes=maximum_payload_bytes,
        )

        cells_by_member: dict[str, list[dict[str, Any]]] = {}
        for index, member_key in enumerate(SCOPE_KEYS, start=1):
            emit(f"coalescing changed words {index}/{len(SCOPE_KEYS)}: {member_key}")
            source, target = payloads[member_key]
            cells = STAGE66.build_word_cells(
                source=source,
                target=target,
                extension=str(stage65_rows[member_key].get("extension", "")),
                header_guard_bytes=header_guard_bytes,
                tail_guard_bytes=tail_guard_bytes,
            )
            cells_by_member[member_key] = cells
            if member_key in stage66_cells:
                compare_recomputed_cells(cells, stage66_cells[member_key], member_key=member_key)

        opl2_keys = (TARGET_OPL2_KEY, *SIBLING_OPL2_KEYS)
        transition_members: dict[str, Counter[str]] = defaultdict(Counter)
        source_word_members: dict[str, Counter[str]] = defaultdict(Counter)
        target_word_members: dict[str, Counter[str]] = defaultdict(Counter)
        transition_offsets: dict[tuple[str, str], list[int]] = defaultdict(list)
        for member_key in opl2_keys:
            for cell in cells_by_member[member_key]:
                transition_id = str(cell["transition_id"])
                transition_members[transition_id][member_key] += 1
                source_word_members[str(cell["source_hex"])][member_key] += 1
                target_word_members[str(cell["target_hex"])][member_key] += 1
                transition_offsets[(transition_id, member_key)].append(int(cell["start"]))

        emit("classifying Hinako bathroom word transitions against sibling descriptors")
        comparison_rows: list[dict[str, Any]] = []
        target_cells = cells_by_member[TARGET_OPL2_KEY]
        sibling_keys = set(SIBLING_OPL2_KEYS)
        for cell in target_cells:
            transition_id = str(cell["transition_id"])
            exact_members = transition_members[transition_id]
            sibling_exact = sum(exact_members.get(key, 0) for key in SIBLING_OPL2_KEYS)
            sibling_source = sum(source_word_members[str(cell["source_hex"])].get(key, 0) for key in SIBLING_OPL2_KEYS)
            sibling_target = sum(target_word_members[str(cell["target_hex"])].get(key, 0) for key in SIBLING_OPL2_KEYS)
            exact_names = [key for key in SIBLING_OPL2_KEYS if exact_members.get(key, 0)]
            if exact_names:
                classification = "exact_transition_shared_with_sibling_water_descriptor"
            elif sibling_source and sibling_target:
                classification = "source_and_target_words_seen_in_siblings_but_not_as_same_transition"
            elif sibling_source:
                classification = "source_word_shared_with_sibling_target_differs"
            elif sibling_target:
                classification = "target_word_shared_with_sibling_source_differs"
            else:
                classification = "hinako_bathroom_scope_unique_transition"
            comparison_rows.append({
                "member_key": TARGET_OPL2_KEY,
                "cell_index": cell["cell_index"],
                "start": cell["start"],
                "end": cell["end"],
                "source_hex": cell["source_hex"],
                "target_hex": cell["target_hex"],
                "changed_byte_mask": cell["changed_byte_mask"],
                "source_f32_le": cell["source_f32_le"],
                "target_f32_le": cell["target_f32_le"],
                "transition_id": transition_id,
                "target_occurrence_count": exact_members.get(TARGET_OPL2_KEY, 0),
                "shower_exact_transition_count": exact_members.get(SIBLING_OPL2_KEYS[0], 0),
                "pool_exact_transition_count": exact_members.get(SIBLING_OPL2_KEYS[1], 0),
                "sibling_exact_transition_count": sibling_exact,
                "sibling_source_word_count": sibling_source,
                "sibling_target_word_count": sibling_target,
                "exact_transition_sibling_members": ";".join(exact_names),
                "classification": classification,
                "semantics_assigned": False,
                "review_status": "bounded_water_scene_control_comparison_only",
            })

        scope_transition_rows: list[dict[str, Any]] = []
        for transition_id, counts in sorted(transition_members.items()):
            scope_transition_rows.append({
                "transition_id": transition_id,
                "source_hex": next(
                    str(cell["source_hex"])
                    for key in opl2_keys
                    for cell in cells_by_member[key]
                    if str(cell["transition_id"]) == transition_id
                ),
                "target_hex": next(
                    str(cell["target_hex"])
                    for key in opl2_keys
                    for cell in cells_by_member[key]
                    if str(cell["transition_id"]) == transition_id
                ),
                "bathroom_occurrence_count": counts.get(TARGET_OPL2_KEY, 0),
                "shower_occurrence_count": counts.get(SIBLING_OPL2_KEYS[0], 0),
                "pool_occurrence_count": counts.get(SIBLING_OPL2_KEYS[1], 0),
                "scope_occurrence_count": sum(counts.values()),
                "scope_member_count": sum(1 for value in counts.values() if value),
                "bathroom_offsets": ";".join(str(value) for value in transition_offsets.get((transition_id, TARGET_OPL2_KEY), [])),
                "shower_offsets": ";".join(str(value) for value in transition_offsets.get((transition_id, SIBLING_OPL2_KEYS[0]), [])),
                "pool_offsets": ";".join(str(value) for value in transition_offsets.get((transition_id, SIBLING_OPL2_KEYS[1]), [])),
                "shared_with_bathroom": counts.get(TARGET_OPL2_KEY, 0) > 0 and sum(counts.get(key, 0) for key in SIBLING_OPL2_KEYS) > 0,
                "semantics_assigned": False,
                "review_status": "transition_frequency_metadata_only",
            })

        target_unique = [
            cell for cell in target_cells
            if not any(transition_members[str(cell["transition_id"])].get(key, 0) for key in SIBLING_OPL2_KEYS)
        ]
        strict_unique = [
            cell for cell in target_unique
            if not any(source_word_members[str(cell["source_hex"])].get(key, 0) for key in SIBLING_OPL2_KEYS)
            and not any(target_word_members[str(cell["target_hex"])].get(key, 0) for key in SIBLING_OPL2_KEYS)
        ]
        sibling_shared = [cell for cell in target_cells if cell not in target_unique]
        candidate_sets: list[tuple[str, list[dict[str, Any]], str]] = [
            (
                "hinako_bathroom_scope_unique_exact_transition_set",
                target_unique,
                "target_transition_not_seen_in_shower_or_pool_scope_semantics_unassigned",
            ),
            (
                "hinako_bathroom_strict_unique_word_pair_set",
                strict_unique,
                "source_and_target_words_absent_from_shower_and_pool_scope_semantics_unassigned",
            ),
            (
                "sibling_shared_exact_transition_set",
                sibling_shared,
                "shared_water_scene_transition_set_confounded_between_censorship_and_remaster",
            ),
            (
                "complete_hinako_bathroom_word_set",
                target_cells,
                "exact_original_available_but_mixes_scope_unique_and_sibling_shared_transitions",
            ),
        ]
        opl2_candidate_rows: list[dict[str, Any]] = []
        seen_sets: set[tuple[int, ...]] = set()
        source_opl2, target_opl2 = payloads[TARGET_OPL2_KEY]
        for kind, selected, classification in candidate_sets:
            indices = tuple(sorted(int(cell["cell_index"]) for cell in selected))
            if not selected or indices in seen_sets:
                continue
            seen_sets.add(indices)
            opl2_candidate_rows.append(apply_and_measure(
                member_key=TARGET_OPL2_KEY,
                source=source_opl2,
                target=target_opl2,
                cells=target_cells,
                candidate_kind=kind,
                selected=selected,
                header_guard_bytes=header_guard_bytes,
                tail_guard_bytes=tail_guard_bytes,
                classification=classification,
            ))

        emit("auditing the repeated river transition blocked only by the generic tail guard")
        river_source, river_target = payloads[RIVER_KEY]
        river_cells = cells_by_member[RIVER_KEY]
        river_transition_counts = Counter(str(cell["transition_id"]) for cell in river_cells)
        river_review_rows: list[dict[str, Any]] = []
        exception_cells: list[dict[str, Any]] = []
        for cell in river_cells:
            reasons = {reason for reason in str(cell.get("exclusion_reasons", "")).split(";") if reason}
            same_transition = [other for other in river_cells if other["transition_id"] == cell["transition_id"]]
            eligible_support = [other for other in same_transition if bool(other.get("eligible"))]
            bytes_after_unchanged = river_source[int(cell["end"]):] == river_target[int(cell["end"]):]
            repeated_tail_exception = (
                reasons == {"touches_guarded_tail"}
                and int(cell["end"]) - int(cell["start"]) == 4
                and len(same_transition) >= 3
                and len(eligible_support) >= 2
                and bytes_after_unchanged
                and int(cell["end"]) <= len(river_target) - 4
            )
            if repeated_tail_exception:
                exception_cells.append(cell)
            river_review_rows.append({
                "member_key": RIVER_KEY,
                "cell_index": cell["cell_index"],
                "start": cell["start"],
                "end": cell["end"],
                "source_hex": cell["source_hex"],
                "target_hex": cell["target_hex"],
                "source_f32_le": cell["source_f32_le"],
                "target_f32_le": cell["target_f32_le"],
                "transition_id": cell["transition_id"],
                "transition_occurrence_count": river_transition_counts[str(cell["transition_id"])],
                "eligible_support_occurrence_count": len(eligible_support),
                "base_eligible": bool(cell.get("eligible")),
                "base_exclusion_reasons": cell.get("exclusion_reasons", ""),
                "bytes_after_word_identical": bytes_after_unchanged,
                "repeated_tail_guard_exception_supported": repeated_tail_exception,
                "semantics_assigned": False,
                "review_status": (
                    "repeated_transition_supports_narrow_tail_guard_exception_metadata_only"
                    if repeated_tail_exception
                    else "base_word_gate_result_retained"
                ),
            })

        eligible_river = [cell for cell in river_cells if bool(cell.get("eligible"))]
        river_candidate_rows: list[dict[str, Any]] = []
        if eligible_river:
            river_candidate_rows.append(apply_and_measure(
                member_key=RIVER_KEY,
                source=river_source,
                target=river_target,
                cells=river_cells,
                candidate_kind="base_eligible_word_set",
                selected=eligible_river,
                header_guard_bytes=header_guard_bytes,
                tail_guard_bytes=tail_guard_bytes,
                classification="stage66_partial_word_reconstruction_retained",
            ))
        if exception_cells and len(eligible_river) + len(exception_cells) == len(river_cells):
            full_river = sorted([*eligible_river, *exception_cells], key=lambda row: int(row["cell_index"]))
            row = apply_and_measure(
                member_key=RIVER_KEY,
                source=river_source,
                target=river_target,
                cells=river_cells,
                candidate_kind="complete_word_set_with_repeated_tail_guard_exception",
                selected=full_river,
                header_guard_bytes=header_guard_bytes,
                tail_guard_bytes=0,
                classification="exact_original_reconstruction_supported_by_repeated_tail_transition_semantics_unassigned",
            )
            row["guarded_tail_preserved"] = river_source[-tail_guard_bytes:] == river_target[-tail_guard_bytes:]
            row["generic_tail_guard_intentionally_not_used_for_one_repeated_cell"] = True
            river_candidate_rows.append(row)

        scope_member_rows: list[dict[str, Any]] = []
        for member_key in SCOPE_KEYS:
            source, target = payloads[member_key]
            cells = cells_by_member[member_key]
            report_row = stage65_rows[member_key]
            scope_member_rows.append({
                "candidate_id": report_row.get("candidate_id", ""),
                "rule_id": report_row.get("rule_id", ""),
                "domain": report_row.get("domain", ""),
                "priority": report_row.get("priority", ""),
                "normalized_path": report_row.get("normalized_path", ""),
                "member_key": member_key,
                "extension": report_row.get("extension", ""),
                "source_size": len(source),
                "target_size": len(target),
                "target_distance_to_source": STAGE66.hamming_distance(source, target),
                "word_cell_count": len(cells),
                "eligible_word_cell_count": sum(bool(cell.get("eligible")) for cell in cells),
                "excluded_word_cell_count": sum(not bool(cell.get("eligible")) for cell in cells),
                "unique_transition_count": len({str(cell["transition_id"]) for cell in cells}),
                "scope_role": (
                    "hinako_bathroom_target"
                    if member_key == TARGET_OPL2_KEY
                    else "hinako_bathroom_river_companion"
                    if member_key == RIVER_KEY
                    else "water_scene_sibling_control"
                ),
                "semantics_assigned": False,
                "review_status": "read_only_sibling_descriptor_scope",
            })

        evidence_root = report_root / EVIDENCE_DIR_NAME
        if evidence_root.exists():
            shutil.rmtree(evidence_root)
        evidence_root.mkdir(parents=True, exist_ok=True)

        write_tsv(evidence_root / "BATHROOM_SIBLING_DESCRIPTOR_MEMBERS.tsv", [
            "candidate_id", "rule_id", "domain", "priority", "normalized_path", "member_key", "extension",
            "source_size", "target_size", "target_distance_to_source", "word_cell_count",
            "eligible_word_cell_count", "excluded_word_cell_count", "unique_transition_count",
            "scope_role", "semantics_assigned", "review_status",
        ], scope_member_rows)
        write_tsv(evidence_root / "BATHROOM_OPL2_TARGET_CELL_COMPARISONS.tsv", [
            "member_key", "cell_index", "start", "end", "source_hex", "target_hex", "changed_byte_mask",
            "source_f32_le", "target_f32_le", "transition_id", "target_occurrence_count",
            "shower_exact_transition_count", "pool_exact_transition_count", "sibling_exact_transition_count",
            "sibling_source_word_count", "sibling_target_word_count", "exact_transition_sibling_members",
            "classification", "semantics_assigned", "review_status",
        ], comparison_rows)
        write_tsv(evidence_root / "BATHROOM_OPL2_SCOPE_TRANSITIONS.tsv", [
            "transition_id", "source_hex", "target_hex", "bathroom_occurrence_count", "shower_occurrence_count",
            "pool_occurrence_count", "scope_occurrence_count", "scope_member_count", "bathroom_offsets",
            "shower_offsets", "pool_offsets", "shared_with_bathroom", "semantics_assigned", "review_status",
        ], scope_transition_rows)
        candidate_fields = [
            "member_key", "candidate_kind", "selected_cell_indices", "selected_cell_count",
            "selected_transition_ids", "candidate_sha256", "candidate_size", "target_distance_to_source",
            "candidate_distance_to_source", "distance_improvement", "exact_original", "guarded_header_preserved",
            "guarded_tail_preserved", "exact_target_reverse_roundtrip", "passes_static_reconstruction_gates",
            "classification", "generic_tail_guard_intentionally_not_used_for_one_repeated_cell",
            "safe_to_build_local_prototype", "semantics_assigned", "review_status",
        ]
        write_tsv(evidence_root / "BATHROOM_OPL2_CONTROLLED_CANDIDATES.tsv", candidate_fields, opl2_candidate_rows)
        write_tsv(evidence_root / "BATHROOM_RIVER_TAIL_REVIEW.tsv", [
            "member_key", "cell_index", "start", "end", "source_hex", "target_hex", "source_f32_le",
            "target_f32_le", "transition_id", "transition_occurrence_count", "eligible_support_occurrence_count",
            "base_eligible", "base_exclusion_reasons", "bytes_after_word_identical",
            "repeated_tail_guard_exception_supported", "semantics_assigned", "review_status",
        ], river_review_rows)
        write_tsv(evidence_root / "BATHROOM_RIVER_CANDIDATES.tsv", candidate_fields, river_candidate_rows)
        write_tsv(evidence_root / "BATHROOM_SIBLING_DESCRIPTOR_SKIPPED.tsv", ["member_key", "reason"], [])

        shared_target_cells = sum(parse_int(row["sibling_exact_transition_count"]) > 0 for row in comparison_rows)
        unique_target_cells = len(comparison_rows) - shared_target_cells
        strict_unique_target_cells = sum(
            row["classification"] == "hinako_bathroom_scope_unique_transition"
            and parse_int(row["sibling_source_word_count"]) == 0
            and parse_int(row["sibling_target_word_count"]) == 0
            for row in comparison_rows
        )
        exact_opl2_candidates = sum(parse_bool(row.get("exact_original")) for row in opl2_candidate_rows)
        exact_river_candidates = sum(parse_bool(row.get("exact_original")) for row in river_candidate_rows)
        river_exception_rows = sum(parse_bool(row.get("repeated_tail_guard_exception_supported")) for row in river_review_rows)

        summary = {
            "type": "br_quartet_restoration_bathroom_sibling_descriptor_comparison_evidence_summary",
            "format_version": 1,
            "tool_version": TOOL_VERSION,
            "source_stage65_tool_version": stage65_summary.get("tool_version"),
            "source_stage66_tool_version": stage66_summary.get("tool_version"),
            "source_shader_effect_tool_version": shader_summary.get("tool_version"),
            "status": "bathroom_sibling_descriptor_and_river_tail_audit_complete_no_payload_written_manual_decode_still_required",
            "scope_member_rows": len(scope_member_rows),
            "opl2_scope_member_rows": len(opl2_keys),
            "target_opl2_cell_rows": len(target_cells),
            "sibling_opl2_cell_rows": sum(len(cells_by_member[key]) for key in SIBLING_OPL2_KEYS),
            "target_opl2_cells_shared_by_exact_transition_with_sibling": shared_target_cells,
            "target_opl2_scope_unique_transition_cells": unique_target_cells,
            "target_opl2_strict_unique_word_pair_cells": strict_unique_target_cells,
            "opl2_candidate_rows": len(opl2_candidate_rows),
            "opl2_exact_original_candidate_rows": exact_opl2_candidates,
            "river_word_cell_rows": len(river_cells),
            "river_repeated_tail_guard_exception_rows": river_exception_rows,
            "river_candidate_rows": len(river_candidate_rows),
            "river_exact_original_candidate_rows": exact_river_candidates,
            "safe_local_prototype_rows": 0,
            "skipped_rows": 0,
            "parameters": {
                "maximum_earc_bytes": maximum_earc_bytes,
                "maximum_payload_bytes": maximum_payload_bytes,
                "word_size_bytes": 4,
                "header_guard_bytes": header_guard_bytes,
                "tail_guard_bytes": tail_guard_bytes,
                "sibling_scope": list(SIBLING_OPL2_KEYS),
                "river_tail_exception_requires_three_exact_transition_occurrences": True,
                "river_tail_exception_requires_two_base_eligible_support_occurrences": True,
                "river_tail_exception_requires_identical_remaining_suffix": True,
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
                "exact_original_reconstruction_is_not_automatic_prototype_authorization": True,
                "sibling_scope_contains_only_water_or_steam_scenes_and_is_not_a_neutral_remaster_control": True,
                "ordinary_field_or_format_control_still_required_before_opl2_payload_build": True,
                "river_tail_exception_is_metadata_only_until_report_review": True,
                "translation_or_dlc_workstreams_modified": False,
            },
            "next_action": (
                "Upload this report. Review whether the Hinako OPL2 exact reconstruction is dominated by transitions shared with the "
                "shower/pool descriptors or by target-unique cells. Separately review the repeated river tail exception. Build no payload "
                "until the report identifies a narrowly supported candidate and ordinary-field/remaster controls are considered where needed."
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
    parser.add_argument("--header-guard-bytes", type=int, default=16)
    parser.add_argument("--tail-guard-bytes", type=int, default=16)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    project_root = args.project_root.resolve()
    workspace_root = (args.workspace_root or project_root / ".local/build/quartet_restoration").resolve()
    report_root = (args.report_root or project_root / ".local/reports/quartet_restoration").resolve()
    try:
        output, summary = collect(
            project_root=project_root,
            workspace_root=workspace_root,
            report_root=report_root,
            maximum_earc_bytes=args.maximum_earc_bytes,
            maximum_payload_bytes=args.maximum_payload_bytes,
            header_guard_bytes=args.header_guard_bytes,
            tail_guard_bytes=args.tail_guard_bytes,
        )
    except (SiblingDescriptorError, STAGE66.BathroomWordAuditError, OSError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print(f"Report: {output}")
    print(f"Scope members: {summary['scope_member_rows']}")
    print(f"Target OPL2 cells shared with sibling exact transitions: {summary['target_opl2_cells_shared_by_exact_transition_with_sibling']}")
    print(f"Target OPL2 scope-unique transitions: {summary['target_opl2_scope_unique_transition_cells']}")
    print(f"River repeated-tail exceptions: {summary['river_repeated_tail_guard_exception_rows']}")
    print(f"Safe local prototypes: {summary['safe_local_prototype_rows']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
