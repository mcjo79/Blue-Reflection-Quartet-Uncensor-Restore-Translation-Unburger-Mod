#!/usr/bin/env python3
"""Audit the local record/trailer layout around the ambiguous target-75 blocks.

Stage 97 found no exact residual transition outside the focal PC02 member.  This
stage therefore stays local and format-aware: it rehydrates only the same four
bounded effect containers, reconstructs the 21 normalized anchored blocks from
stage 95, and compares the source-150 block and both target-75 blocks with the
stable same-variant 150/75 blocks in ``e_cmn_pup_reflect_s.g1e``.

The report exports only selected dword values, offsets, counts and bounded
hashes.  Same-variant similarity cannot establish occurrence identity and no
G1E/G1EM write, prototype or brightness/censorship claim is authorized.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import importlib.util
import json
import math
import os
import struct
import subprocess
import sys
import tempfile
from pathlib import Path, PurePosixPath
from typing import Any, Callable, Iterable, Mapping, Sequence

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT_DEFAULT = SCRIPT_DIR.parent.parent

TOOL_VERSION = "0.1.12"
REPORT_NAME = "BR_quartet_restoration_reflector_slot_light_trailer_record_layout_evidence.tar.zst"
REPORT_DIR = "reflector_slot_light_trailer_record_layout_evidence"
STAGE79_DIR = "reflector_character_slot_render_member_evidence"
STAGE79_ARCHIVE = "BR_quartet_restoration_reflector_character_slot_render_member_evidence.tar.zst"
STAGE95_DIR = "reflector_slot_light_anchored_block_envelope_evidence"
STAGE95_ARCHIVE = "BR_quartet_restoration_reflector_slot_light_anchored_block_envelope_evidence.tar.zst"
STAGE96_DIR = "reflector_slot_light_anchored_block_internal_change_evidence"
STAGE96_ARCHIVE = "BR_quartet_restoration_reflector_slot_light_anchored_block_internal_change_evidence.tar.zst"
STAGE97_DIR = "reflector_slot_light_residual_shape_recurrence_evidence"
STAGE97_ARCHIVE = "BR_quartet_restoration_reflector_slot_light_residual_shape_recurrence_evidence.tar.zst"

EXPECTED_PARENT_CONTAINERS = 4
EXPECTED_SIBLING_PAIRS = 540
EXPECTED_FOCAL_OCCURRENCES = 21
EXPECTED_STAGE96_INTERNAL_DIFFS = 23
EXPECTED_STAGE97_UNIQUE_SHAPES = 10
EXPECTED_STAGE97_SEEDS = 13
CANDIDATE_MEMBER = "e_pc02_w5_ringlight_01.g1e"
NEUTRAL_MEMBER = "e_cmn_pup_reflect_s.g1e"
RESIDUAL_DWORDS = (27, 28, 37, 104, 126, 128, 129, 132, 133)


class Stage98Error(RuntimeError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise Stage98Error(message)


def progress(message: str) -> None:
    print(f"[stage98] {message}", file=sys.stderr, flush=True)


def parse_int(value: Any, default: int = 0) -> int:
    try:
        text = str(value).strip()
        return int(text, 16) if text.casefold().startswith("0x") else int(text)
    except (TypeError, ValueError):
        return default


def parse_bool(value: Any) -> bool:
    return str(value).strip().casefold() in {"1", "true", "yes", "y"}


def signed_i32(value: int) -> int:
    value &= 0xFFFFFFFF
    return value - 0x100000000 if value & 0x80000000 else value


def float32_text(value: int) -> str:
    number = struct.unpack("<f", int(value & 0xFFFFFFFF).to_bytes(4, "little"))[0]
    if not math.isfinite(number):
        return ""
    return format(number, ".9g")


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def safe_name(raw: str) -> str:
    path = PurePosixPath(raw)
    require(not path.is_absolute() and path.parts and ".." not in path.parts, f"unsafe archive member: {raw}")
    return path.as_posix()


def read_tsv(path: Path) -> list[dict[str, str]]:
    require(path.is_file(), f"missing required TSV: {path}")
    with path.open(encoding="utf-8", newline="") as handle:
        return [dict(row) for row in csv.DictReader(handle, delimiter="\t")]


def write_tsv(path: Path, fields: Sequence[str], rows: Iterable[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(fields), delimiter="\t", lineterminator="\n", extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fields})


def load_json(path: Path) -> dict[str, Any]:
    require(path.is_file(), f"missing required JSON: {path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise Stage98Error(f"invalid JSON {path}: {exc}") from exc
    require(isinstance(value, dict), f"JSON root must be object: {path}")
    return value


def extract_archive(archive: Path, destination: Path) -> Path:
    require(archive.is_file(), f"missing prerequisite report: {archive}")
    listed = subprocess.run(["tar", "--zstd", "-tf", str(archive)], text=True, capture_output=True)
    require(listed.returncode == 0, listed.stderr.strip())
    roots = {PurePosixPath(safe_name(line.strip())).parts[0] for line in listed.stdout.splitlines() if line.strip()}
    require(len(roots) == 1, f"expected one report root in {archive}")
    destination.mkdir(parents=True, exist_ok=True)
    completed = subprocess.run(["tar", "--zstd", "-xf", str(archive), "-C", str(destination)], text=True, capture_output=True)
    require(completed.returncode == 0, completed.stderr.strip())
    return destination / next(iter(roots))


def locate(report_root: Path, direct: str, archive: str, temporary: Path) -> Path:
    direct_path = report_root / direct
    return direct_path if direct_path.is_dir() else extract_archive(report_root / archive, temporary)


def make_archive(source: Path, output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(output.name + ".tmp")
    temporary.unlink(missing_ok=True)
    completed = subprocess.run(["tar", "--zstd", "-cf", str(temporary), "-C", str(source.parent), source.name], text=True, capture_output=True)
    require(completed.returncode == 0, completed.stderr.strip())
    os.replace(temporary, output)


def load_module(path: Path, name: str):
    require(path.is_file(), f"missing helper module: {path}")
    spec = importlib.util.spec_from_file_location(name, path)
    require(spec is not None and spec.loader is not None, f"cannot load helper module: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def u32(payload: bytes, offset: int) -> int:
    require(0 <= offset <= len(payload) - 4, f"u32 offset out of bounds: {offset}")
    return int.from_bytes(payload[offset:offset + 4], "little")


def segment_for(relative_dword: int) -> str:
    if 27 <= relative_dword <= 37:
        return "reference_record"
    if relative_dword >= 38:
        return "post_record_trailer"
    return "pre_record_prefix"


def validate_stage95(root: Path) -> dict[str, Any]:
    summary = load_json(root / "SUMMARY.json")
    require(summary.get("type") == "br_quartet_restoration_reflector_slot_light_anchored_block_envelope_evidence_summary", "stage95 type mismatch")
    require(summary.get("tool_version") == "0.1.9", "stage95 tool version mismatch")
    require(parse_int(summary.get("focal_occurrence_rows"), -1) == EXPECTED_FOCAL_OCCURRENCES, "stage95 focal count mismatch")
    require(parse_bool(summary.get("anchored_block_span_field_confirmed")), "stage95 block span not confirmed")
    require(not parse_bool(summary.get("candidate_target_occurrence_identity_resolved")), "stage95 unexpectedly resolved identity")
    require(parse_int(summary.get("skipped_rows"), -1) == 0, "stage95 contains skipped rows")
    return summary


def validate_stage96(root: Path) -> dict[str, Any]:
    summary = load_json(root / "SUMMARY.json")
    require(summary.get("type") == "br_quartet_restoration_reflector_slot_light_anchored_block_internal_change_evidence_summary", "stage96 type mismatch")
    require(summary.get("tool_version") == "0.1.10", "stage96 tool version mismatch")
    require(parse_int(summary.get("internal_dword_difference_rows"), -1) == EXPECTED_STAGE96_INTERNAL_DIFFS, "stage96 difference count mismatch")
    require(parse_int(summary.get("candidate_source_150_to_second_target_75_residual_dword_differences"), -1) == 4, "stage96 second-target residual mismatch")
    require(not parse_bool(summary.get("candidate_target_occurrence_identity_resolved")), "stage96 unexpectedly resolved identity")
    require(parse_int(summary.get("skipped_rows"), -1) == 0, "stage96 contains skipped rows")
    return summary


def validate_stage97(root: Path) -> dict[str, Any]:
    summary = load_json(root / "SUMMARY.json")
    require(summary.get("type") == "br_quartet_restoration_reflector_slot_light_residual_shape_recurrence_evidence_summary", "stage97 type mismatch")
    require(summary.get("tool_version") == "0.1.11", "stage97 tool version mismatch")
    require(parse_int(summary.get("ambiguous_residual_seed_rows"), -1) == EXPECTED_STAGE97_SEEDS, "stage97 seed count mismatch")
    require(parse_int(summary.get("unique_residual_transition_shapes"), -1) == EXPECTED_STAGE97_UNIQUE_SHAPES, "stage97 shape count mismatch")
    require(parse_int(summary.get("transition_shapes_with_exact_hits_outside_focal_member"), -1) == 0, "stage97 unexpectedly found cross-member exact support")
    require(not parse_bool(summary.get("candidate_target_occurrence_identity_resolved")), "stage97 unexpectedly resolved identity")
    require(parse_int(summary.get("prototype_candidate_rows"), -1) == 0, "stage97 unexpectedly authorized prototype")
    require(parse_int(summary.get("skipped_rows"), -1) == 0, "stage97 contains skipped rows")
    return summary


def diff_count(left: bytes, right: bytes, start_dw: int, end_dw_exclusive: int) -> int:
    limit = min(len(left), len(right)) // 4
    start = max(0, start_dw)
    end = min(limit, end_dw_exclusive)
    return sum(u32(left, index * 4) != u32(right, index * 4) for index in range(start, end))


def local_window(payload: bytes, relative_dword: int, radius: int = 2) -> bytes:
    start = max(0, relative_dword - radius) * 4
    end = min(len(payload), (relative_dword + radius + 1) * 4)
    return payload[start:end]


def build_report(
    project_root: Path,
    *,
    create_archive: bool = True,
    report_root: Path | None = None,
    workspace_root: Path | None = None,
    rules_file: Path | None = None,
    maximum_earc_bytes: int = 512 * 1024 * 1024,
    container_loader: Callable[..., tuple[list[dict[str, Any]], list[dict[str, Any]]]] | None = None,
) -> tuple[Path, Path | None, dict[str, Any]]:
    project_root = project_root.resolve()
    reports = (report_root or project_root / ".local/reports/quartet_restoration").resolve()
    workspace = (workspace_root or project_root / ".local/build/quartet_restoration").resolve()
    require(reports.is_dir(), f"missing report root: {reports}")

    stage81 = load_module(project_root / "workstreams/quartet_restoration/collect_reflector_ringlight_control_callsite_evidence.py", "stage81_for_stage98")
    stage86 = load_module(project_root / "workstreams/quartet_restoration/collect_reflector_slot_light_shared_record_template_evidence.py", "stage86_for_stage98")
    stage95 = load_module(project_root / "workstreams/quartet_restoration/collect_reflector_slot_light_anchored_block_envelope_evidence.py", "stage95_for_stage98")

    progress("validating stages 79, 95, 96 and 97")
    with tempfile.TemporaryDirectory(prefix="br-stage98-") as temporary_name:
        temporary = Path(temporary_name)
        stage79_root = locate(reports, STAGE79_DIR, STAGE79_ARCHIVE, temporary / "79")
        stage95_root = locate(reports, STAGE95_DIR, STAGE95_ARCHIVE, temporary / "95")
        stage96_root = locate(reports, STAGE96_DIR, STAGE96_ARCHIVE, temporary / "96")
        stage97_root = locate(reports, STAGE97_DIR, STAGE97_ARCHIVE, temporary / "97")
        stage81.validate_stage79(stage79_root)
        summary95 = validate_stage95(stage95_root)
        summary96 = validate_stage96(stage96_root)
        summary97 = validate_stage97(stage97_root)
        layout_rows = read_tsv(stage95_root / "SLOT_LIGHT_ANCHORED_BLOCK_LAYOUT.tsv")
        seeds97 = read_tsv(stage97_root / "SLOT_LIGHT_RESIDUAL_SHAPE_SEEDS.tsv")
        require(len(layout_rows) == EXPECTED_FOCAL_OCCURRENCES, "stage95 layout row count mismatch")
        require(len(seeds97) == EXPECTED_STAGE97_SEEDS, "stage97 seed table count mismatch")
        observed_positions = {parse_int(row.get("relative_dword"), -1) for row in seeds97}
        require(observed_positions == set(RESIDUAL_DWORDS), "stage97 residual position set mismatch")

        parent_scope = stage81.select_parent_scope(stage79_root)
        actual_rules = rules_file or project_root / "titles/blue_reflection/modules/quartet_restoration/mappings/effect_material_rules.tsv"
        loader = container_loader or stage81.load_parent_containers
        progress("rehydrating the same four bounded parent effect containers")
        containers, skipped = loader(scope_rows=parent_scope, workspace_root=workspace, report_root=reports, rules_file=actual_rules, maximum_earc_bytes=maximum_earc_bytes)
        require(not skipped, f"parent container loader skipped {len(skipped)} rows")
        require(len(containers) == EXPECTED_PARENT_CONTAINERS, f"expected {EXPECTED_PARENT_CONTAINERS} parent containers, found {len(containers)}")
        pair_by_key, all_pairs = stage86.index_pairs(containers)
        require(len(all_pairs) == EXPECTED_SIBLING_PAIRS, f"expected {EXPECTED_SIBLING_PAIRS} sibling pairs, found {len(all_pairs)}")

        occurrences: list[dict[str, Any]] = []
        skipped_rows: list[dict[str, Any]] = []
        grouped: dict[tuple[str, str, str], list[dict[str, str]]] = {}
        for row in layout_rows:
            key = (row.get("normalized_path", "").casefold(), row.get("member_key", "").casefold(), row.get("side", "").casefold())
            grouped.setdefault(key, []).append(row)
        for rows in grouped.values():
            rows.sort(key=lambda row: parse_int(row.get("anchor"), -1))

        progress(f"reconstructing {len(layout_rows)} normalized anchored blocks")
        for (path_cf, member_cf, side), rows in grouped.items():
            pair = pair_by_key.get((path_cf, member_cf))
            require(pair is not None, f"missing focal pair: {(path_cf, member_cf)}")
            payload = pair[f"{side}_payload"]
            endpoint = parse_int(rows[0].get("endpoint"), -1)
            targets = stage95.structural_targets(rows, endpoint)
            for row in rows:
                anchor = parse_int(row.get("anchor"), -1)
                span = parse_int(row.get("declared_block_span"), -1)
                if anchor < 0 or span <= 0 or span % 4 or anchor + span > len(payload):
                    skipped_rows.append({"scope": "occurrence", "side": side, "anchor": anchor, "reason": "invalid_block_geometry"})
                    continue
                raw = payload[anchor:anchor + span]
                normalized, relocations = stage95.normalize_block(payload, anchor, span, targets)
                occurrences.append({"row": dict(row), "raw": raw, "normalized": normalized, "relocation_count": len(relocations)})
        require(not skipped_rows, f"stage98 skipped {len(skipped_rows)} occurrences")
        require(len(occurrences) == EXPECTED_FOCAL_OCCURRENCES, "occurrence reconstruction count mismatch")

        def select(member_name: str, side: str, variant: str) -> list[dict[str, Any]]:
            result = [value for value in occurrences if value["row"].get("member_name", "").casefold() == member_name.casefold() and value["row"].get("side") == side and value["row"].get("variant_label") == variant]
            result.sort(key=lambda value: parse_int(value["row"].get("reference_index"), -1))
            return result

        source150 = select(CANDIDATE_MEMBER, "source", "equal_float_150")
        target75 = select(CANDIDATE_MEMBER, "target", "equal_float_75")
        neutral_source150 = select(NEUTRAL_MEMBER, "source", "equal_float_150")
        neutral_target150 = select(NEUTRAL_MEMBER, "target", "equal_float_150")
        neutral_source75 = select(NEUTRAL_MEMBER, "source", "equal_float_75")
        neutral_target75 = select(NEUTRAL_MEMBER, "target", "equal_float_75")
        require(len(source150) == 1 and len(target75) == 2, "candidate 150/75 occurrence count mismatch")
        require(all(len(group) == 1 for group in (neutral_source150, neutral_target150, neutral_source75, neutral_target75)), "neutral same-variant occurrence count mismatch")

        labels: dict[str, dict[str, Any]] = {
            "candidate_source_150": source150[0],
            "candidate_target_75_first": target75[0],
            "candidate_target_75_second": target75[1],
            "neutral_source_150": neutral_source150[0],
            "neutral_target_150": neutral_target150[0],
            "neutral_source_75": neutral_source75[0],
            "neutral_target_75": neutral_target75[0],
        }

        inventory_rows: list[dict[str, Any]] = []
        dword_rows: list[dict[str, Any]] = []
        field_role_rows: list[dict[str, Any]] = []
        for label, occurrence in labels.items():
            row = occurrence["row"]
            normalized = occurrence["normalized"]
            inventory_rows.append({
                "occurrence_label": label,
                "cluster_role": row.get("cluster_role", ""),
                "member_name": row.get("member_name", ""),
                "side": row.get("side", ""),
                "reference_index": row.get("reference_index", ""),
                "variant_label": row.get("variant_label", ""),
                "anchor": row.get("anchor", ""),
                "record_start": row.get("record_start", ""),
                "declared_block_span": row.get("declared_block_span", ""),
                "normalized_block_sha256": sha256(normalized),
                "relocation_fields_normalized": occurrence["relocation_count"],
            })
            anchor = parse_int(row.get("anchor"), -1)
            record_start = parse_int(row.get("record_start"), -1)
            reference_offset = parse_int(row.get("reference_offset"), -1)
            span = len(normalized)
            landmarks = {"anchor": anchor, "record_start": record_start, "reference_offset": reference_offset, "block_end": anchor + span}
            for relative_dword in RESIDUAL_DWORDS:
                if (relative_dword + 1) * 4 > len(normalized):
                    continue
                value = u32(normalized, relative_dword * 4)
                window = local_window(normalized, relative_dword)
                dword_rows.append({
                    "occurrence_label": label,
                    "variant_label": row.get("variant_label", ""),
                    "relative_dword": relative_dword,
                    "relative_byte": relative_dword * 4,
                    "segment": segment_for(relative_dword),
                    "u32_hex": f"0x{value:08x}",
                    "i32": signed_i32(value),
                    "float32": float32_text(value),
                    "window_radius_dwords": 2,
                    "window_sha256": sha256(window),
                })
                field_abs = anchor + relative_dword * 4
                candidates = {
                    "field_start_relative": field_abs + signed_i32(value),
                    "anchor_relative": anchor + signed_i32(value),
                    "record_start_relative": record_start + signed_i32(value),
                }
                matched = [f"{model}:{name}" for model, endpoint in candidates.items() for name, landmark in landmarks.items() if endpoint == landmark]
                field_role_rows.append({
                    "occurrence_label": label,
                    "relative_dword": relative_dword,
                    "segment": segment_for(relative_dword),
                    "u32_hex": f"0x{value:08x}",
                    "i32": signed_i32(value),
                    "equals_declared_block_span": value == span,
                    "equals_trailer_bytes": value == max(0, span - 152),
                    "field_start_relative_endpoint": candidates["field_start_relative"],
                    "anchor_relative_endpoint": candidates["anchor_relative"],
                    "record_start_relative_endpoint": candidates["record_start_relative"],
                    "exact_known_landmark_matches": ",".join(matched),
                    "role_classification": "exact_bounded_landmark_reference" if matched else "unresolved_local_field",
                })

        comparison_specs = [
            ("neutral_150_source_target", "neutral_source_150", "neutral_target_150"),
            ("neutral_75_source_target", "neutral_source_75", "neutral_target_75"),
            ("candidate_source150_to_neutral_source150", "candidate_source_150", "neutral_source_150"),
            ("candidate_source150_to_neutral_target150", "candidate_source_150", "neutral_target_150"),
            ("candidate_first75_to_neutral_source75", "candidate_target_75_first", "neutral_source_75"),
            ("candidate_first75_to_neutral_target75", "candidate_target_75_first", "neutral_target_75"),
            ("candidate_second75_to_neutral_source75", "candidate_target_75_second", "neutral_source_75"),
            ("candidate_second75_to_neutral_target75", "candidate_target_75_second", "neutral_target_75"),
            ("candidate_target75_duplicate_pair", "candidate_target_75_first", "candidate_target_75_second"),
        ]
        comparison_rows: list[dict[str, Any]] = []
        window_rows: list[dict[str, Any]] = []
        for comparison, left_label, right_label in comparison_specs:
            left = labels[left_label]["normalized"]
            right = labels[right_label]["normalized"]
            limit = min(len(left), len(right)) // 4
            selected_differences = sum(u32(left, pos * 4) != u32(right, pos * 4) for pos in RESIDUAL_DWORDS if pos < limit)
            comparison_rows.append({
                "comparison": comparison,
                "left_occurrence": left_label,
                "right_occurrence": right_label,
                "left_block_dwords": len(left) // 4,
                "right_block_dwords": len(right) // 4,
                "shared_dword_span": limit,
                "full_shared_span_dword_differences": diff_count(left, right, 0, limit),
                "reference_record_dword_differences": diff_count(left, right, 27, 38),
                "early_trailer_dword_differences": diff_count(left, right, 38, min(limit, 112)),
                "late_trailer_dword_differences": diff_count(left, right, 112, limit),
                "selected_residual_position_differences": selected_differences,
                "selected_residual_positions_exact": selected_differences == 0,
            })
            for position in RESIDUAL_DWORDS:
                if position >= limit:
                    continue
                left_window = local_window(left, position)
                right_window = local_window(right, position)
                window_rows.append({
                    "comparison": comparison,
                    "relative_dword": position,
                    "segment": segment_for(position),
                    "left_u32_hex": f"0x{u32(left, position * 4):08x}",
                    "right_u32_hex": f"0x{u32(right, position * 4):08x}",
                    "center_exact": u32(left, position * 4) == u32(right, position * 4),
                    "window_exact": left_window == right_window,
                    "left_window_sha256": sha256(left_window),
                    "right_window_sha256": sha256(right_window),
                })

        by_comparison = {row["comparison"]: row for row in comparison_rows}
        second_source_support = by_comparison["candidate_second75_to_neutral_source75"]
        second_target_support = by_comparison["candidate_second75_to_neutral_target75"]
        first_source_support = by_comparison["candidate_first75_to_neutral_source75"]
        first_target_support = by_comparison["candidate_first75_to_neutral_target75"]
        second_same_variant_record_exact = min(second_source_support["reference_record_dword_differences"], second_target_support["reference_record_dword_differences"]) == 0
        first_same_variant_record_exact = min(first_source_support["reference_record_dword_differences"], first_target_support["reference_record_dword_differences"]) == 0
        second_same_variant_selected_exact = min(second_source_support["selected_residual_position_differences"], second_target_support["selected_residual_position_differences"]) == 0
        first_same_variant_selected_exact = min(first_source_support["selected_residual_position_differences"], first_target_support["selected_residual_position_differences"]) == 0

        decision_rows = [
            {"question": "does stage97 provide any exact cross-member transition support", "answer": False, "classification": "no_cross_member_exact_recurrence"},
            {"question": "does the second target 75 have an exact same-variant reference-record peer", "answer": second_same_variant_record_exact, "classification": "same_variant_record_layout_support_only" if second_same_variant_record_exact else "no_exact_same_variant_record_peer"},
            {"question": "does the first target 75 have an exact same-variant reference-record peer", "answer": first_same_variant_record_exact, "classification": "same_variant_record_layout_support_only" if first_same_variant_record_exact else "no_exact_same_variant_record_peer"},
            {"question": "does exactly one target 75 match all selected same-variant record/trailer positions", "answer": second_same_variant_selected_exact != first_same_variant_selected_exact, "classification": "variant_consistency_not_occurrence_identity"},
            {"question": "can same-variant trailer/record layout select the continuation occurrence", "answer": False, "classification": "target_occurrence_identity_unresolved"},
        ]

        output_dir = reports / REPORT_DIR
        if output_dir.exists():
            import shutil
            shutil.rmtree(output_dir)
        output_dir.mkdir(parents=True)
        write_tsv(output_dir / "SLOT_LIGHT_SAME_VARIANT_OCCURRENCE_INVENTORY.tsv", ["occurrence_label", "cluster_role", "member_name", "side", "reference_index", "variant_label", "anchor", "record_start", "declared_block_span", "normalized_block_sha256", "relocation_fields_normalized"], inventory_rows)
        write_tsv(output_dir / "SLOT_LIGHT_TRAILER_RECORD_DWORD_VALUES.tsv", ["occurrence_label", "variant_label", "relative_dword", "relative_byte", "segment", "u32_hex", "i32", "float32", "window_radius_dwords", "window_sha256"], dword_rows)
        write_tsv(output_dir / "SLOT_LIGHT_SAME_VARIANT_BLOCK_COMPARISON.tsv", ["comparison", "left_occurrence", "right_occurrence", "left_block_dwords", "right_block_dwords", "shared_dword_span", "full_shared_span_dword_differences", "reference_record_dword_differences", "early_trailer_dword_differences", "late_trailer_dword_differences", "selected_residual_position_differences", "selected_residual_positions_exact"], comparison_rows)
        write_tsv(output_dir / "SLOT_LIGHT_RESIDUAL_LOCAL_WINDOW_COMPARISON.tsv", ["comparison", "relative_dword", "segment", "left_u32_hex", "right_u32_hex", "center_exact", "window_exact", "left_window_sha256", "right_window_sha256"], window_rows)
        write_tsv(output_dir / "SLOT_LIGHT_TRAILER_FIELD_ROLE_CANDIDATES.tsv", ["occurrence_label", "relative_dword", "segment", "u32_hex", "i32", "equals_declared_block_span", "equals_trailer_bytes", "field_start_relative_endpoint", "anchor_relative_endpoint", "record_start_relative_endpoint", "exact_known_landmark_matches", "role_classification"], field_role_rows)
        write_tsv(output_dir / "SLOT_LIGHT_TARGET_75_TRAILER_RECORD_DECISION.tsv", ["question", "answer", "classification"], decision_rows)
        write_tsv(output_dir / "SLOT_LIGHT_TRAILER_RECORD_LAYOUT_SKIPPED.tsv", ["scope", "side", "anchor", "reason"], skipped_rows)

        summary = {
            "type": "br_quartet_restoration_reflector_slot_light_trailer_record_layout_evidence_summary",
            "format_version": 1,
            "tool_version": TOOL_VERSION,
            "source_stage95_tool_version": summary95.get("tool_version"),
            "source_stage96_tool_version": summary96.get("tool_version"),
            "source_stage97_tool_version": summary97.get("tool_version"),
            "sibling_G1E_G1EM_member_rows": len(all_pairs),
            "focal_occurrence_rows": len(occurrences),
            "same_variant_occurrence_rows": len(labels),
            "residual_seed_rows": len(seeds97),
            "residual_relative_dword_positions": len(RESIDUAL_DWORDS),
            "trailer_record_dword_value_rows": len(dword_rows),
            "same_variant_block_comparison_rows": len(comparison_rows),
            "local_window_comparison_rows": len(window_rows),
            "field_role_candidate_rows": len(field_role_rows),
            "candidate_first_target_75_same_variant_record_exact": first_same_variant_record_exact,
            "candidate_second_target_75_same_variant_record_exact": second_same_variant_record_exact,
            "candidate_first_target_75_selected_positions_exact": first_same_variant_selected_exact,
            "candidate_second_target_75_selected_positions_exact": second_same_variant_selected_exact,
            "candidate_target_occurrence_identity_resolved": False,
            "candidate_target_occurrence_identity_reason": "same-variant record or trailer similarity classifies layout but cannot align one of two target occurrences to the single source occurrence",
            "technical_leaf_semantics_resolved": False,
            "prototype_candidate_rows": 0,
            "brightness_semantics_confirmed": False,
            "censorship_semantics_confirmed": False,
            "skipped_rows": 0,
            "status": "local_trailer_record_layout_audited_same_variant_support_does_not_resolve_occurrence_identity",
            "next_action": "Upload this report. Continue only with a read-only bounded trailer-subrecord boundary audit if repeated local windows reveal a stable field grouping; otherwise close this occurrence-identity branch without G1E write or brightness/censorship inference.",
            "parameters": {
                "residual_relative_dwords": list(RESIDUAL_DWORDS),
                "local_window_radius_dwords": 2,
                "same_variant_controls": "stable source/target 150 and 75 occurrences in e_cmn_pup_reflect_s.g1e",
                "identity_gate": "same-variant similarity is never sufficient to select one of two target occurrences",
            },
            "policy": {
                "full_proprietary_payloads_exported": False,
                "render_payload_written": False,
                "pak_repacked": False,
                "core_registry_modified": False,
                "profile_activated": False,
                "installed_game_modified": False,
                "runtime_validation_inferred": False,
                "technical_leaf_semantics_inferred": False,
                "brightness_semantics_inferred": False,
                "censorship_semantics_inferred": False,
                "canary_track_modified": False,
            },
        }
        (output_dir / "SUMMARY.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        archive = reports / REPORT_NAME if create_archive else None
        if archive is not None:
            progress("creating compressed report archive")
            make_archive(output_dir, archive)
        progress("completed")
        return output_dir, archive, summary


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path, default=PROJECT_ROOT_DEFAULT)
    parser.add_argument("--no-report-archive", action="store_true")
    args = parser.parse_args(argv)
    try:
        output, archive, summary = build_report(args.project_root, create_archive=not args.no_report_archive)
    except Stage98Error as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print(f"Report directory: {output}")
    if archive is not None:
        print(f"Report: {archive}")
    print(f"Same-variant occurrence rows: {summary['same_variant_occurrence_rows']}")
    print(f"Target occurrence identity resolved: {summary['candidate_target_occurrence_identity_resolved']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
