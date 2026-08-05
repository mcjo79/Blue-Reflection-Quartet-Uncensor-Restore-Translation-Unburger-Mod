#!/usr/bin/env python3
"""Audit word-coalesced bathroom scene descriptor deltas without writing payloads.

Stage 65 found no exact-Original member under raw changed-run alignment, but its
strongest scene-specific partial result is the Hinako bathroom field container.
Most excluded runs are partial-byte changes inside 32-bit cells, so rejecting the
run boundaries as unaligned does not prove the enclosing words are unsafe.

This stage rehydrates only the two bathroom members, expands every changed byte
to its enclosing little-endian 32-bit cell, and records occurrence-aware word
transitions plus reversible singleton/group/full-member reconstructions.  It
never assigns field semantics and never writes a candidate member, archive, PAK,
registry entry, activation state, or installed-game file.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
import shutil
import struct
import subprocess
import sys
import tempfile
from collections import Counter, defaultdict
from math import gcd
from pathlib import Path, PurePosixPath
from typing import Any, Iterable, Mapping, Sequence

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT_DEFAULT = SCRIPT_DIR.parent.parent
TEXT_TOOL_DIR = PROJECT_ROOT_DEFAULT / "Blue_Reflection_Text_Tool"
if str(TEXT_TOOL_DIR) not in sys.path:
    sys.path.insert(0, str(TEXT_TOOL_DIR))

import br_restoration_tool as BR  # noqa: E402

TOOL_VERSION = "0.0.76"
REPORT_NAME = "BR_quartet_restoration_bathroom_scene_descriptor_word_evidence.tar.zst"
EVIDENCE_DIR_NAME = "bathroom_scene_descriptor_word_evidence"

EXPECTED_STAGE65_TOOL_VERSION = "0.0.75"
EXPECTED_PARENT_PATH = "data/x64/field/s89_s_hinako_bath_room_01/s89_s_hinako_bath_room_01.elixir.gz"
TARGET_MEMBERS = {
    "s89_s_hinako_bath_room_01.opl2#0": {
        "extension": ".opl2",
        "classification": "expanded_scene_effect_partial_inverse_evidence_only",
        "target_distance_to_source": 146,
        "operation_count": 54,
        "eligible_operation_count": 4,
        "excluded_operation_count": 50,
        "best_candidate_distance_to_source": 130,
        "best_distance_improvement": 16,
    },
    "s89_s_hinako_bath_room_01_river.bin#0": {
        "extension": ".bin",
        "classification": "expanded_scene_effect_member_not_promotable_by_conservative_inverse_ranges",
        "target_distance_to_source": 22,
        "operation_count": 5,
        "eligible_operation_count": 0,
        "excluded_operation_count": 5,
        "best_candidate_distance_to_source": None,
        "best_distance_improvement": None,
    },
}


class BathroomWordAuditError(RuntimeError):
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
        raise BathroomWordAuditError(f"unsafe report archive member: {raw}")
    return path.as_posix()


def read_tsv(path: Path, *, required: bool = True) -> list[dict[str, str]]:
    if not path.is_file():
        if required:
            raise BathroomWordAuditError(f"missing prerequisite table: {path}")
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
        raise BathroomWordAuditError(f"missing prerequisite JSON: {path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise BathroomWordAuditError(f"invalid JSON {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise BathroomWordAuditError(f"expected JSON object: {path}")
    return value


def atomic_json(path: Path, value: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def extract_archive(archive: Path, destination: Path) -> Path:
    if not archive.is_file():
        raise BathroomWordAuditError(f"missing prerequisite report archive: {archive}")
    listed = subprocess.run(
        ["tar", "--zstd", "-tf", str(archive)],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if listed.returncode != 0:
        raise BathroomWordAuditError(f"cannot list {archive}: {listed.stderr.strip()}")
    roots: set[str] = set()
    for raw in listed.stdout.splitlines():
        if raw.strip():
            roots.add(PurePosixPath(safe_member_name(raw.strip())).parts[0])
    if len(roots) != 1:
        raise BathroomWordAuditError(f"expected one report root in {archive}, found {sorted(roots)}")
    destination.mkdir(parents=True, exist_ok=True)
    completed = subprocess.run(
        ["tar", "--zstd", "-xf", str(archive), "-C", str(destination)],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if completed.returncode != 0:
        raise BathroomWordAuditError(f"cannot extract {archive}: {completed.stderr.strip()}")
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
        raise BathroomWordAuditError(f"cannot create report archive: {completed.stderr.strip()}")
    os.replace(temporary, output)


def validate_stage65_report(root: Path) -> tuple[dict[str, Any], dict[str, dict[str, str]]]:
    summary = load_json(root / "SUMMARY.json")
    if summary.get("type") != "br_quartet_restoration_expanded_scene_effect_member_evidence_summary":
        raise BathroomWordAuditError("stage-65 report has an unexpected summary type")
    if summary.get("tool_version") != EXPECTED_STAGE65_TOOL_VERSION:
        raise BathroomWordAuditError("stage-65 report must use tool version 0.0.75")
    if summary.get("status") != "expanded_scene_effect_member_inverse_range_audit_complete_no_payload_written_runtime_deferred":
        raise BathroomWordAuditError("stage-65 report is not complete")
    required_counts = {
        "registry_profile_rows": 14,
        "stage63_remaining_ebd_candidate_rows": 0,
        "stage64_historical_prefilter_selected_rows": 0,
        "expanded_focused_binary_delta_rows_selected": 185,
        "rehydrated_member_rows": 185,
        "analyzed_member_rows": 185,
        "promotable_exact_original_member_rows": 0,
        "partial_inverse_evidence_member_rows": 13,
        "skipped_rows": 0,
    }
    for field, expected in required_counts.items():
        if parse_int(summary.get(field), -1) != expected:
            raise BathroomWordAuditError(f"stage-65 summary field {field} must equal {expected}")
    policy = summary.get("policy") or {}
    if not isinstance(policy, dict):
        raise BathroomWordAuditError("stage-65 policy is malformed")
    forbidden = (
        "installed_games_modified",
        "candidate_effect_payloads_written",
        "parent_archive_repack_performed",
        "core_registry_modified",
        "activation_or_rollback_invoked",
        "runtime_validation_inferred",
        "censorship_classification_inferred",
    )
    if any(parse_bool(policy.get(field)) for field in forbidden):
        raise BathroomWordAuditError("stage-65 report performed or inferred a forbidden action")

    rows = read_tsv(root / "EXPANDED_SCENE_EFFECT_MEMBERS.tsv")
    target_rows: dict[str, dict[str, str]] = {}
    for row in rows:
        if str(row.get("normalized_path", "")).casefold() != EXPECTED_PARENT_PATH.casefold():
            continue
        member_key = str(row.get("member_key", "")).casefold()
        for expected_key in TARGET_MEMBERS:
            if member_key == expected_key.casefold():
                if expected_key in target_rows:
                    raise BathroomWordAuditError(f"duplicate stage-65 bathroom member row: {expected_key}")
                target_rows[expected_key] = row
    if set(target_rows) != set(TARGET_MEMBERS):
        raise BathroomWordAuditError(
            "stage-65 report must contain exactly the two expected bathroom descriptor members"
        )
    candidate_ids = {str(row.get("candidate_id", "")) for row in target_rows.values()}
    if len(candidate_ids) != 1 or not next(iter(candidate_ids)):
        raise BathroomWordAuditError("bathroom descriptor rows must share one nonempty candidate_id")
    for member_key, expected in TARGET_MEMBERS.items():
        row = target_rows[member_key]
        if str(row.get("rule_id", "")) != "bathroom_scene":
            raise BathroomWordAuditError(f"unexpected rule_id for {member_key}")
        if str(row.get("domain", "")) != "steam_and_water_visibility":
            raise BathroomWordAuditError(f"unexpected domain for {member_key}")
        if str(row.get("priority", "")) != "critical":
            raise BathroomWordAuditError(f"unexpected priority for {member_key}")
        for field in ("extension", "classification"):
            if str(row.get(field, "")) != str(expected[field]):
                raise BathroomWordAuditError(f"unexpected {field} for {member_key}")
        for field in (
            "target_distance_to_source", "operation_count", "eligible_operation_count",
            "excluded_operation_count",
        ):
            if parse_int(row.get(field), -1) != int(expected[field]):
                raise BathroomWordAuditError(f"unexpected {field} for {member_key}")
        for field in ("best_candidate_distance_to_source", "best_distance_improvement"):
            expected_value = expected[field]
            actual = str(row.get(field, "")).strip()
            if expected_value is None:
                if actual:
                    raise BathroomWordAuditError(f"unexpected populated {field} for {member_key}")
            elif parse_int(actual, -1) != int(expected_value):
                raise BathroomWordAuditError(f"unexpected {field} for {member_key}")
    return summary, target_rows


def load_shader_metadata(root: Path) -> tuple[dict[str, Any], dict[tuple[str, str, str, str], dict[str, str]]]:
    summary = load_json(root / "SUMMARY.json")
    if summary.get("type") != "br_quartet_restoration_shader_effect_evidence_summary":
        raise BathroomWordAuditError("shader-effect report has an unexpected summary type")
    rows = read_tsv(root / "RENDER_PAYLOADS.tsv")
    metadata: dict[tuple[str, str, str, str], dict[str, str]] = {}
    for row in rows:
        key = (
            str(row.get("candidate_id", "")),
            str(row.get("normalized_path", "")),
            str(row.get("member_key", "")),
            str(row.get("side", "")),
        )
        if key in metadata:
            raise BathroomWordAuditError(f"duplicate render payload metadata row: {key}")
        metadata[key] = row
    return summary, metadata


def load_target_pairs(
    *, project_root: Path, workspace_root: Path, report_root: Path,
    stage65_rows: Mapping[str, Mapping[str, str]],
    maximum_earc_bytes: int,
    pair_loader: Any | None = None,
) -> tuple[dict[str, dict[str, Any]], list[dict[str, Any]]]:
    if pair_loader is not None:
        pairs, skipped = pair_loader(
            workspace_root=workspace_root,
            report_root=report_root,
            rules_file=project_root / "titles/blue_reflection/modules/quartet_restoration/mappings/effect_material_rules.tsv",
            maximum_earc_bytes=maximum_earc_bytes,
        )
        by_key = {str(row.get("member_key", "")): row for row in pairs}
        return {key: by_key[key] for key in TARGET_MEMBERS if key in by_key}, skipped

    rules_file = project_root / "titles/blue_reflection/modules/quartet_restoration/mappings/effect_material_rules.tsv"
    differences = BR.load_report_jsons(report_root, "differences")
    effects = BR.build_effect_material_candidates(differences, BR.load_effect_material_rules(rules_file))
    candidate_id = str(next(iter(stage65_rows.values())).get("candidate_id", ""))
    matching = [
        row for row in effects
        if str(row.get("candidate_id", "")) == candidate_id
        and str(row.get("normalized_path", "")).casefold() == EXPECTED_PARENT_PATH.casefold()
    ]
    if len(matching) != 1:
        raise BathroomWordAuditError("cannot resolve the unique bathroom effect-material candidate")
    effect = matching[0]
    archives: dict[str, dict[str, Any]] = {}
    skipped: list[dict[str, Any]] = []
    for side in ("source", "target"):
        ref = effect.get(side)
        if not isinstance(ref, dict):
            raise BathroomWordAuditError(f"missing {side} archive reference for bathroom container")
        local_path = BR.inventory_workspace_file(
            workspace_root,
            side,
            str(effect.get("pair_id", "")),
            str(ref.get("archive", "")),
            str(ref.get("path", "")),
        )
        if not local_path.is_file():
            raise BathroomWordAuditError(f"missing {side} bathroom container in workspace: {local_path}")
        archives[side] = BR.read_earc_archive(
            local_path,
            maximum_bytes=maximum_earc_bytes,
            include_member_payloads=True,
        )
    source_members = {str(row["comparison_key"]): row for row in archives["source"].get("members", [])}
    target_members = {str(row["comparison_key"]): row for row in archives["target"].get("members", [])}
    result: dict[str, dict[str, Any]] = {}
    for member_key in TARGET_MEMBERS:
        left = source_members.get(member_key)
        right = target_members.get(member_key)
        if not left or not right:
            raise BathroomWordAuditError(f"missing bathroom member pair: {member_key}")
        result[member_key] = {
            **effect,
            "member_key": member_key,
            "source_member_name": str(left.get("name", "")),
            "target_member_name": str(right.get("name", "")),
            "extension": str(right.get("extension", left.get("extension", ""))),
            "source_payload": left.get("payload"),
            "target_payload": right.get("payload"),
        }
    return result, skipped


def hamming_distance(left: bytes, right: bytes) -> int:
    if len(left) != len(right):
        raise BathroomWordAuditError("hamming distance requires equal payload sizes")
    return sum(a != b for a, b in zip(left, right))


def float_text(raw: bytes) -> str:
    if len(raw) != 4:
        return ""
    value = struct.unpack("<f", raw)[0]
    if not math.isfinite(value):
        return ""
    return format(value, ".9g")


def build_word_cells(
    *, source: bytes, target: bytes, extension: str,
    header_guard_bytes: int, tail_guard_bytes: int,
) -> list[dict[str, Any]]:
    if len(source) != len(target):
        raise BathroomWordAuditError("word-cell audit requires equal payload sizes")
    offsets = sorted({(index // 4) * 4 for index, (a, b) in enumerate(zip(source, target)) if a != b})
    cells: list[dict[str, Any]] = []
    for ordinal, start in enumerate(offsets):
        end = min(start + 4, len(target))
        source_word = source[start:end]
        target_word = target[start:end]
        reasons: list[str] = []
        if len(source_word) != 4 or len(target_word) != 4:
            reasons.append("truncated_terminal_word")
        if start < header_guard_bytes:
            reasons.append("touches_guarded_header")
        if end > len(target) - tail_guard_bytes:
            reasons.append("touches_guarded_tail")
        mask = "".join("1" if a != b else "0" for a, b in zip(source_word, target_word))
        transition = hashlib.sha256(
            extension.encode("utf-8") + source_word + b"\0" + target_word
        ).hexdigest()
        cells.append({
            "cell_index": ordinal,
            "word_index": start // 4,
            "start": start,
            "end": end,
            "source_word": source_word,
            "target_word": target_word,
            "source_hex": source_word.hex(),
            "target_hex": target_word.hex(),
            "changed_byte_mask": mask,
            "changed_byte_count": sum(bit == "1" for bit in mask),
            "source_u32_le": int.from_bytes(source_word, "little") if len(source_word) == 4 else "",
            "target_u32_le": int.from_bytes(target_word, "little") if len(target_word) == 4 else "",
            "source_i32_le": int.from_bytes(source_word, "little", signed=True) if len(source_word) == 4 else "",
            "target_i32_le": int.from_bytes(target_word, "little", signed=True) if len(target_word) == 4 else "",
            "source_f32_le": float_text(source_word),
            "target_f32_le": float_text(target_word),
            "xor_hex": bytes(a ^ b for a, b in zip(source_word, target_word)).hex(),
            "transition_id": transition,
            "eligible": not reasons,
            "exclusion_reasons": ";".join(reasons),
        })
    return cells


def apply_cells(target: bytes, cells: Sequence[Mapping[str, Any]]) -> bytes:
    result = bytearray(target)
    for cell in cells:
        start = int(cell["start"])
        end = int(cell["end"])
        source_word = bytes(cell["source_word"])
        if end - start != len(source_word):
            raise BathroomWordAuditError("word replacement is not size-preserving")
        result[start:end] = source_word
    return bytes(result)


def reverse_cells(candidate: bytes, cells: Sequence[Mapping[str, Any]]) -> bytes:
    result = bytearray(candidate)
    for cell in cells:
        start = int(cell["start"])
        end = int(cell["end"])
        target_word = bytes(cell["target_word"])
        if end - start != len(target_word):
            raise BathroomWordAuditError("reverse word replacement is not size-preserving")
        result[start:end] = target_word
    return bytes(result)


def gap_gcd(offsets: Sequence[int]) -> int:
    if len(offsets) < 2:
        return 0
    value = 0
    for left, right in zip(offsets, offsets[1:]):
        value = gcd(value, right - left)
    return value


def collect(
    *, project_root: Path, workspace_root: Path, report_root: Path,
    maximum_earc_bytes: int = 512 * 1024 * 1024,
    maximum_payload_bytes: int = 8 * 1024 * 1024,
    header_guard_bytes: int = 16,
    tail_guard_bytes: int = 16,
    pair_loader: Any | None = None,
) -> tuple[Path, dict[str, Any]]:
    if maximum_earc_bytes < 1 or maximum_payload_bytes < 1:
        raise BathroomWordAuditError("size limits must be positive")
    if header_guard_bytes < 0 or tail_guard_bytes < 0:
        raise BathroomWordAuditError("guard sizes cannot be negative")

    print("[stage66] validating stage-65 and shader evidence", flush=True)
    with tempfile.TemporaryDirectory(prefix="br-stage66-") as temporary_name:
        temporary = Path(temporary_name)
        stage65_root = locate_report_root(
            report_root,
            "expanded_scene_effect_member_evidence",
            "BR_quartet_restoration_expanded_scene_effect_member_evidence.tar.zst",
            temporary / "stage65",
        )
        shader_root = locate_report_root(
            report_root,
            "shader_effect_evidence",
            "BR_quartet_restoration_shader_effect_evidence.tar.zst",
            temporary / "shader",
        )
        stage65_summary, stage65_rows = validate_stage65_report(stage65_root)
        shader_summary, payload_metadata = load_shader_metadata(shader_root)

        print("[stage66] rehydrating only the two bathroom descriptor members", flush=True)
        pairs, loader_skipped = load_target_pairs(
            project_root=project_root,
            workspace_root=workspace_root,
            report_root=report_root,
            stage65_rows=stage65_rows,
            maximum_earc_bytes=maximum_earc_bytes,
            pair_loader=pair_loader,
        )
        if loader_skipped:
            raise BathroomWordAuditError(f"targeted bathroom pair loader skipped {len(loader_skipped)} rows")
        if set(pairs) != set(TARGET_MEMBERS):
            raise BathroomWordAuditError("targeted pair loader did not return both bathroom members")

        member_rows: list[dict[str, Any]] = []
        cell_rows: list[dict[str, Any]] = []
        candidate_rows: list[dict[str, Any]] = []
        skipped_rows: list[dict[str, Any]] = []
        raw_cells_by_member: dict[str, list[dict[str, Any]]] = {}
        payloads_by_member: dict[str, tuple[bytes, bytes]] = {}

        for member_index, member_key in enumerate(TARGET_MEMBERS, start=1):
            print(f"[stage66] analyzing bathroom member {member_index}/2: {member_key}", flush=True)
            stage65_row = stage65_rows[member_key]
            pair = pairs[member_key]
            source = pair.get("source_payload")
            target = pair.get("target_payload")
            if not isinstance(source, (bytes, bytearray)) or not isinstance(target, (bytes, bytearray)):
                skipped_rows.append({"member_key": member_key, "reason": "source_or_target_payload_missing"})
                continue
            source = bytes(source)
            target = bytes(target)
            if len(source) > maximum_payload_bytes or len(target) > maximum_payload_bytes:
                skipped_rows.append({"member_key": member_key, "reason": "payload_exceeds_stage66_limit"})
                continue
            if len(source) != len(target):
                skipped_rows.append({"member_key": member_key, "reason": "source_target_payload_size_mismatch"})
                continue
            if source == target:
                skipped_rows.append({"member_key": member_key, "reason": "rehydrated_payloads_are_identical"})
                continue
            actual_target_distance = hamming_distance(source, target)
            if actual_target_distance != parse_int(stage65_row.get("target_distance_to_source"), -1):
                raise BathroomWordAuditError(
                    f"stage-65 target distance mismatch for {member_key}: "
                    f"report={stage65_row.get('target_distance_to_source')} actual={actual_target_distance}"
                )
            candidate_id = str(stage65_row.get("candidate_id", ""))
            normalized_path = str(stage65_row.get("normalized_path", ""))
            for side, payload in (("source", source), ("target", target)):
                metadata = payload_metadata.get((candidate_id, normalized_path, member_key, side))
                if metadata is None:
                    raise BathroomWordAuditError(f"missing payload metadata for {member_key} side={side}")
                if parse_int(metadata.get("payload_size"), -1) != len(payload):
                    raise BathroomWordAuditError(f"payload size mismatch for {member_key} side={side}")
                if str(metadata.get("payload_sha256", "")) != hashlib.sha256(payload).hexdigest():
                    raise BathroomWordAuditError(f"payload hash mismatch for {member_key} side={side}")
            cells = build_word_cells(
                source=source,
                target=target,
                extension=str(stage65_row.get("extension", "")),
                header_guard_bytes=header_guard_bytes,
                tail_guard_bytes=tail_guard_bytes,
            )
            if not cells:
                skipped_rows.append({"member_key": member_key, "reason": "no_changed_word_cells"})
                continue
            raw_cells_by_member[member_key] = cells
            payloads_by_member[member_key] = (source, target)

        transition_counts = Counter(
            str(cell["transition_id"])
            for cells in raw_cells_by_member.values()
            for cell in cells
        )
        transition_locations: dict[str, list[tuple[str, int]]] = defaultdict(list)
        for member_key, cells in raw_cells_by_member.items():
            for cell in cells:
                transition_locations[str(cell["transition_id"])].append((member_key, int(cell["start"])))

        transition_group_rows: list[dict[str, Any]] = []
        for transition_id, locations in sorted(transition_locations.items()):
            offsets_by_member: dict[str, list[int]] = defaultdict(list)
            for member_key, offset in locations:
                offsets_by_member[member_key].append(offset)
            for member_key, offsets in sorted(offsets_by_member.items()):
                offsets = sorted(offsets)
                example = next(
                    cell for cell in raw_cells_by_member[member_key]
                    if str(cell["transition_id"]) == transition_id
                )
                transition_group_rows.append({
                    "member_key": member_key,
                    "extension": TARGET_MEMBERS[member_key]["extension"],
                    "transition_id": transition_id,
                    "source_hex": example["source_hex"],
                    "target_hex": example["target_hex"],
                    "changed_byte_mask": example["changed_byte_mask"],
                    "occurrence_count_in_member": len(offsets),
                    "occurrence_count_in_target_scope": transition_counts[transition_id],
                    "offsets": ";".join(str(value) for value in offsets),
                    "offset_gap_gcd": gap_gcd(offsets),
                    "repeated_within_member": len(offsets) > 1,
                    "cross_member_transition": len({key for key, _ in locations}) > 1,
                    "semantics_assigned": False,
                    "review_status": "word_transition_group_metadata_only_manual_decode_required",
                })

        exact_original_members = 0
        full_word_reconstruction_members = 0
        for member_key in TARGET_MEMBERS:
            if member_key not in raw_cells_by_member:
                continue
            stage65_row = stage65_rows[member_key]
            source, target = payloads_by_member[member_key]
            cells = raw_cells_by_member[member_key]
            eligible = [cell for cell in cells if parse_bool(cell["eligible"])]
            for cell in cells:
                locations = transition_locations[str(cell["transition_id"])]
                cell_rows.append({
                    "candidate_id": stage65_row.get("candidate_id", ""),
                    "rule_id": stage65_row.get("rule_id", ""),
                    "domain": stage65_row.get("domain", ""),
                    "priority": stage65_row.get("priority", ""),
                    "normalized_path": stage65_row.get("normalized_path", ""),
                    "member_key": member_key,
                    "source_member_name": stage65_row.get("source_member_name", ""),
                    "target_member_name": stage65_row.get("target_member_name", ""),
                    "extension": stage65_row.get("extension", ""),
                    **{field: cell.get(field, "") for field in (
                        "cell_index", "word_index", "start", "end", "source_hex", "target_hex",
                        "changed_byte_mask", "changed_byte_count", "source_u32_le", "target_u32_le",
                        "source_i32_le", "target_i32_le", "source_f32_le", "target_f32_le",
                        "xor_hex", "transition_id", "eligible", "exclusion_reasons",
                    )},
                    "transition_occurrence_count_in_member": sum(
                        1 for key, _ in locations if key == member_key
                    ),
                    "transition_occurrence_count_in_target_scope": len(locations),
                    "semantics_assigned": False,
                    "review_status": "word_cell_metadata_only_no_field_semantics",
                })

            candidate_sets: list[tuple[str, list[dict[str, Any]]]] = []
            candidate_sets.extend((f"cell_{cell['cell_index']}", [cell]) for cell in eligible)
            groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
            for cell in eligible:
                groups[str(cell["transition_id"])].append(cell)
            for transition_id, group in sorted(groups.items()):
                if len(group) > 1:
                    candidate_sets.append((f"transition_{transition_id[:12]}", group))
            if eligible:
                candidate_sets.append(("complete_eligible_word_set", eligible))

            target_distance = hamming_distance(source, target)
            seen_sets: set[tuple[int, ...]] = set()
            best: dict[str, Any] | None = None
            for label, selected_cells in candidate_sets:
                key = tuple(sorted(int(cell["cell_index"]) for cell in selected_cells))
                if key in seen_sets:
                    continue
                seen_sets.add(key)
                candidate = apply_cells(target, selected_cells)
                reversed_target = reverse_cells(candidate, selected_cells)
                distance = hamming_distance(source, candidate)
                improvement = target_distance - distance
                header_preserved = candidate[:header_guard_bytes] == target[:header_guard_bytes]
                tail_preserved = (
                    candidate[len(candidate) - tail_guard_bytes:] == target[len(target) - tail_guard_bytes:]
                    if tail_guard_bytes else True
                )
                passes = (
                    len(candidate) == len(target)
                    and header_preserved
                    and tail_preserved
                    and reversed_target == target
                    and improvement > 0
                )
                row = {
                    "candidate_id": stage65_row.get("candidate_id", ""),
                    "rule_id": stage65_row.get("rule_id", ""),
                    "domain": stage65_row.get("domain", ""),
                    "priority": stage65_row.get("priority", ""),
                    "normalized_path": stage65_row.get("normalized_path", ""),
                    "member_key": member_key,
                    "extension": stage65_row.get("extension", ""),
                    "candidate_kind": label,
                    "selected_cell_indices": ";".join(str(value) for value in key),
                    "selected_cell_count": len(selected_cells),
                    "selected_transition_ids": ";".join(sorted({str(cell["transition_id"]) for cell in selected_cells})),
                    "candidate_sha256": hashlib.sha256(candidate).hexdigest(),
                    "candidate_size": len(candidate),
                    "target_distance_to_source": target_distance,
                    "candidate_distance_to_source": distance,
                    "distance_improvement": improvement,
                    "exact_original": candidate == source,
                    "guarded_header_preserved": header_preserved,
                    "guarded_tail_preserved": tail_preserved,
                    "exact_target_reverse_roundtrip": reversed_target == target,
                    "passes_all_static_word_gates": passes,
                    "safe_to_build_local_prototype_without_manual_decode": False,
                    "semantics_assigned": False,
                    "review_status": "word_coalesced_inverse_metadata_only_manual_decode_required",
                }
                candidate_rows.append(row)
                if passes and (
                    best is None
                    or parse_int(row["candidate_distance_to_source"], 1 << 60)
                    < parse_int(best["candidate_distance_to_source"], 1 << 60)
                ):
                    best = row

            complete_candidate = next(
                (row for row in candidate_rows if row["member_key"] == member_key and row["candidate_kind"] == "complete_eligible_word_set"),
                None,
            )
            all_cells_eligible = bool(cells) and len(eligible) == len(cells)
            exact_original_available = bool(
                complete_candidate
                and parse_bool(complete_candidate["passes_all_static_word_gates"])
                and parse_bool(complete_candidate["exact_original"])
                and all_cells_eligible
            )
            if exact_original_available:
                exact_original_members += 1
                full_word_reconstruction_members += 1
                classification = "exact_original_word_reconstruction_available_manual_decode_required"
                next_gate = "compare_word_transitions_against_sibling_bathroom_and_field_descriptors_before_any_payload_build"
            elif best:
                classification = "partial_word_reconstruction_evidence_only"
                next_gate = "decode_or_isolate_guarded_or_uncovered_word_cells_before_any_payload_build"
            else:
                classification = "word_reconstruction_not_promotable"
                next_gate = "retain_as_evidence_only"
            member_rows.append({
                "candidate_id": stage65_row.get("candidate_id", ""),
                "rule_id": stage65_row.get("rule_id", ""),
                "domain": stage65_row.get("domain", ""),
                "priority": stage65_row.get("priority", ""),
                "normalized_path": stage65_row.get("normalized_path", ""),
                "member_key": member_key,
                "source_member_name": stage65_row.get("source_member_name", ""),
                "target_member_name": stage65_row.get("target_member_name", ""),
                "extension": stage65_row.get("extension", ""),
                "source_size": len(source),
                "target_size": len(target),
                "target_distance_to_source": target_distance,
                "stage65_raw_changed_run_count": stage65_row.get("operation_count", ""),
                "stage65_eligible_raw_run_count": stage65_row.get("eligible_operation_count", ""),
                "word_cell_count": len(cells),
                "eligible_word_cell_count": len(eligible),
                "excluded_word_cell_count": len(cells) - len(eligible),
                "unique_transition_count": len({str(cell["transition_id"]) for cell in cells}),
                "repeated_transition_count": sum(1 for group in groups.values() if len(group) > 1),
                "best_candidate_kind": (best or {}).get("candidate_kind", ""),
                "best_candidate_sha256": (best or {}).get("candidate_sha256", ""),
                "best_candidate_distance_to_source": (best or {}).get("candidate_distance_to_source", ""),
                "best_distance_improvement": (best or {}).get("distance_improvement", ""),
                "best_exact_original": (best or {}).get("exact_original", False),
                "all_changed_bytes_covered_by_word_cells": sum(int(cell["changed_byte_count"]) for cell in cells) == target_distance,
                "all_word_cells_eligible": all_cells_eligible,
                "classification": classification,
                "safe_to_build_local_prototype_without_manual_decode": False,
                "runtime_test_deferred": True,
                "semantics_assigned": False,
                "next_gate": next_gate,
            })

        if skipped_rows:
            raise BathroomWordAuditError(f"bathroom word audit skipped {len(skipped_rows)} required members")

        evidence_root = report_root / EVIDENCE_DIR_NAME
        if evidence_root.exists():
            shutil.rmtree(evidence_root)
        evidence_root.mkdir(parents=True, exist_ok=True)

        member_fields = [
            "candidate_id", "rule_id", "domain", "priority", "normalized_path", "member_key",
            "source_member_name", "target_member_name", "extension", "source_size", "target_size",
            "target_distance_to_source", "stage65_raw_changed_run_count", "stage65_eligible_raw_run_count",
            "word_cell_count", "eligible_word_cell_count", "excluded_word_cell_count", "unique_transition_count",
            "repeated_transition_count", "best_candidate_kind", "best_candidate_sha256",
            "best_candidate_distance_to_source", "best_distance_improvement", "best_exact_original",
            "all_changed_bytes_covered_by_word_cells", "all_word_cells_eligible", "classification",
            "safe_to_build_local_prototype_without_manual_decode", "runtime_test_deferred", "semantics_assigned",
            "next_gate",
        ]
        cell_fields = [
            "candidate_id", "rule_id", "domain", "priority", "normalized_path", "member_key",
            "source_member_name", "target_member_name", "extension", "cell_index", "word_index", "start", "end",
            "source_hex", "target_hex", "changed_byte_mask", "changed_byte_count", "source_u32_le",
            "target_u32_le", "source_i32_le", "target_i32_le", "source_f32_le", "target_f32_le", "xor_hex",
            "transition_id", "transition_occurrence_count_in_member", "transition_occurrence_count_in_target_scope",
            "eligible", "exclusion_reasons", "semantics_assigned", "review_status",
        ]
        transition_fields = [
            "member_key", "extension", "transition_id", "source_hex", "target_hex", "changed_byte_mask",
            "occurrence_count_in_member", "occurrence_count_in_target_scope", "offsets", "offset_gap_gcd",
            "repeated_within_member", "cross_member_transition", "semantics_assigned", "review_status",
        ]
        candidate_fields = [
            "candidate_id", "rule_id", "domain", "priority", "normalized_path", "member_key", "extension",
            "candidate_kind", "selected_cell_indices", "selected_cell_count", "selected_transition_ids",
            "candidate_sha256", "candidate_size", "target_distance_to_source", "candidate_distance_to_source",
            "distance_improvement", "exact_original", "guarded_header_preserved", "guarded_tail_preserved",
            "exact_target_reverse_roundtrip", "passes_all_static_word_gates",
            "safe_to_build_local_prototype_without_manual_decode", "semantics_assigned", "review_status",
        ]
        skipped_fields = ["member_key", "reason"]
        write_tsv(evidence_root / "BATHROOM_SCENE_DESCRIPTOR_MEMBERS.tsv", member_fields, member_rows)
        write_tsv(evidence_root / "BATHROOM_SCENE_DESCRIPTOR_WORD_CELLS.tsv", cell_fields, cell_rows)
        write_tsv(evidence_root / "BATHROOM_SCENE_DESCRIPTOR_TRANSITION_GROUPS.tsv", transition_fields, transition_group_rows)
        write_tsv(evidence_root / "BATHROOM_SCENE_DESCRIPTOR_CANDIDATES.tsv", candidate_fields, candidate_rows)
        write_tsv(evidence_root / "BATHROOM_SCENE_DESCRIPTOR_SKIPPED.tsv", skipped_fields, skipped_rows)

        exact_candidates = [
            row for row in candidate_rows
            if parse_bool(row.get("exact_original")) and parse_bool(row.get("passes_all_static_word_gates"))
        ]
        summary = {
            "type": "br_quartet_restoration_bathroom_scene_descriptor_word_evidence_summary",
            "format_version": 1,
            "tool_version": TOOL_VERSION,
            "source_stage65_tool_version": stage65_summary.get("tool_version"),
            "source_shader_effect_tool_version": shader_summary.get("tool_version"),
            "status": "bathroom_scene_descriptor_word_cell_audit_complete_no_payload_written_manual_decode_required",
            "target_parent_container": EXPECTED_PARENT_PATH,
            "target_member_rows": len(member_rows),
            "word_cell_rows": len(cell_rows),
            "transition_group_rows": len(transition_group_rows),
            "candidate_rows": len(candidate_rows),
            "passing_candidate_rows": sum(parse_bool(row.get("passes_all_static_word_gates")) for row in candidate_rows),
            "exact_original_candidate_rows": len(exact_candidates),
            "exact_original_member_rows": exact_original_members,
            "full_word_reconstruction_member_rows": full_word_reconstruction_members,
            "safe_local_prototype_rows": 0,
            "skipped_rows": len(skipped_rows),
            "parameters": {
                "maximum_earc_bytes": maximum_earc_bytes,
                "maximum_payload_bytes": maximum_payload_bytes,
                "word_size_bytes": 4,
                "header_guard_bytes": header_guard_bytes,
                "tail_guard_bytes": tail_guard_bytes,
                "changed_byte_to_enclosing_word_coalescing": True,
                "candidate_strategy": "eligible_singletons_repeated_transition_groups_and_complete_eligible_word_set",
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
                "word_cell_float_or_integer_views_are_diagnostic_only": True,
                "exact_original_word_reconstruction_is_not_automatic_prototype_authorization": True,
                "manual_sibling_descriptor_comparison_required_before_payload_build": True,
                "translation_or_dlc_workstreams_modified": False,
            },
            "next_action": (
                "Upload this report. Compare the repeated word transitions against sibling bathroom/field descriptors "
                "and separate format/remaster-wide changes from scene-specific steam/water parameters before any local payload prototype."
            ),
        }
        atomic_json(evidence_root / "SUMMARY.json", summary)
        output = report_root / REPORT_NAME
        make_report_archive(evidence_root, output)
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
    args = build_parser().parse_args(argv)
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
    except (BathroomWordAuditError, BR.RestorationError, OSError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print(f"Bathroom descriptor members: {summary['target_member_rows']}")
    print(f"Word cells: {summary['word_cell_rows']}")
    print(f"Exact-Original word reconstructions: {summary['exact_original_member_rows']}")
    print(f"Safe local prototypes: {summary['safe_local_prototype_rows']}")
    print(f"Report: {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
