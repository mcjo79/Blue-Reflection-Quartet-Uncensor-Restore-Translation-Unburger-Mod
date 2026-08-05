#!/usr/bin/env python3
"""Audit internal dword changes inside the focal anchored slot-light blocks.

Stage 95 confirmed the complete anchored-block geometry and showed that the
second target ``75`` block is closer to source ``150`` than the first, but
neither target block is an exact normalized peer.  This stage rehydrates only
the same four bounded effect containers, reconstructs the same 21 blocks and
localizes all remaining aligned dword differences without writing payloads.

Only exact structural references already justified by stage 95 are normalized.
Exact transition signatures observed in stable ``30`` and ``2`` controls are
reported separately.  They are not treated as semantic proof, and only a
transition observed identically in both stable controls at the same relative
dword may be used by the strict residual gate.
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
from collections import Counter, defaultdict
from pathlib import Path, PurePosixPath
from typing import Any, Callable, Iterable, Mapping, Sequence

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT_DEFAULT = SCRIPT_DIR.parent.parent

TOOL_VERSION = "0.1.10"
REPORT_NAME = "BR_quartet_restoration_reflector_slot_light_anchored_block_internal_change_evidence.tar.zst"
REPORT_DIR = "reflector_slot_light_anchored_block_internal_change_evidence"
STAGE79_DIR = "reflector_character_slot_render_member_evidence"
STAGE79_ARCHIVE = "BR_quartet_restoration_reflector_character_slot_render_member_evidence.tar.zst"
STAGE95_DIR = "reflector_slot_light_anchored_block_envelope_evidence"
STAGE95_ARCHIVE = "BR_quartet_restoration_reflector_slot_light_anchored_block_envelope_evidence.tar.zst"

EXPECTED_PARENT_CONTAINERS = 4
EXPECTED_SIBLING_PAIRS = 540
EXPECTED_FOCAL_OCCURRENCES = 21
EXPECTED_COMPARISONS = 5
PRE_RECORD_BYTES = 108
RECORD_BYTES = 44
REFERENCE_DWORD = 10
CONTEXT_DWORDS = 4


class Stage96Error(RuntimeError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise Stage96Error(message)


def progress(message: str) -> None:
    print(f"[stage96] {message}", file=sys.stderr, flush=True)


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
    result = struct.unpack("<f", int(value & 0xFFFFFFFF).to_bytes(4, "little"))[0]
    if not math.isfinite(result):
        return ""
    return format(result, ".9g")


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
        raise Stage96Error(f"invalid JSON {path}: {exc}") from exc
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
    require(path.is_file(), f"missing prerequisite collector: {path}")
    spec = importlib.util.spec_from_file_location(name, path)
    require(spec is not None and spec.loader is not None, f"cannot load module: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def u32(payload: bytes, offset: int) -> int:
    require(offset >= 0 and offset + 4 <= len(payload) and offset % 4 == 0, f"invalid dword offset {offset}")
    return int.from_bytes(payload[offset:offset + 4], "little")


def segment_for(relative_byte: int) -> str:
    if relative_byte < PRE_RECORD_BYTES:
        return "pre_record_prefix"
    if relative_byte < PRE_RECORD_BYTES + RECORD_BYTES:
        return "reference_record"
    return "post_record_trailer"


def validate_stage95(root: Path) -> dict[str, Any]:
    summary = load_json(root / "SUMMARY.json")
    require(summary.get("type") == "br_quartet_restoration_reflector_slot_light_anchored_block_envelope_evidence_summary", "stage95 type mismatch")
    require(summary.get("tool_version") == "0.1.9", "stage95 tool version mismatch")
    require(parse_int(summary.get("sibling_G1E_G1EM_member_rows"), -1) == EXPECTED_SIBLING_PAIRS, "stage95 sibling-pair count mismatch")
    require(parse_int(summary.get("focal_occurrence_rows"), -1) == EXPECTED_FOCAL_OCCURRENCES, "stage95 focal occurrence count mismatch")
    require(parse_int(summary.get("pairwise_comparison_rows"), -1) == EXPECTED_COMPARISONS, "stage95 comparison count mismatch")
    require(parse_bool(summary.get("anchored_block_span_field_confirmed")), "stage95 span field not confirmed")
    require(parse_bool(summary.get("block_prefix_geometry_confirmed")), "stage95 block-prefix geometry not confirmed")
    require(not parse_bool(summary.get("candidate_target_occurrence_identity_resolved")), "stage95 unexpectedly resolved target identity")
    require(parse_int(summary.get("prototype_candidate_rows"), -1) == 0, "stage95 unexpectedly authorized prototype")
    require(not parse_bool(summary.get("brightness_semantics_confirmed")), "stage95 unexpectedly confirmed brightness")
    require(not parse_bool(summary.get("censorship_semantics_confirmed")), "stage95 unexpectedly confirmed censorship")
    require(parse_int(summary.get("skipped_rows"), -1) == 0, "stage95 contains skipped rows")
    return summary


def contiguous_islands(indices: Sequence[int]) -> list[tuple[int, int]]:
    if not indices:
        return []
    ordered = sorted(set(indices))
    result: list[tuple[int, int]] = []
    start = previous = ordered[0]
    for index in ordered[1:]:
        if index == previous + 1:
            previous = index
            continue
        result.append((start, previous))
        start = previous = index
    result.append((start, previous))
    return result


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

    stage81 = load_module(project_root / "workstreams/quartet_restoration/collect_reflector_ringlight_control_callsite_evidence.py", "stage81_for_stage96")
    stage86 = load_module(project_root / "workstreams/quartet_restoration/collect_reflector_slot_light_shared_record_template_evidence.py", "stage86_for_stage96")
    stage95 = load_module(project_root / "workstreams/quartet_restoration/collect_reflector_slot_light_anchored_block_envelope_evidence.py", "stage95_for_stage96")

    progress("validating stage 79 and stage 95 reports")
    with tempfile.TemporaryDirectory(prefix="br-stage96-") as temporary_name:
        temporary = Path(temporary_name)
        stage79_root = locate(reports, STAGE79_DIR, STAGE79_ARCHIVE, temporary / "79")
        stage95_root = locate(reports, STAGE95_DIR, STAGE95_ARCHIVE, temporary / "95")
        stage81.validate_stage79(stage79_root)
        summary95 = validate_stage95(stage95_root)
        layout_rows = read_tsv(stage95_root / "SLOT_LIGHT_ANCHORED_BLOCK_LAYOUT.tsv")
        pairwise95 = read_tsv(stage95_root / "SLOT_LIGHT_ANCHORED_BLOCK_PAIRWISE_COMPARISON.tsv")
        require(len(layout_rows) == EXPECTED_FOCAL_OCCURRENCES, "stage95 layout count mismatch")
        require(len(pairwise95) == EXPECTED_COMPARISONS, "stage95 pairwise count mismatch")

        parent_scope = stage81.select_parent_scope(stage79_root)
        actual_rules = rules_file or project_root / "titles/blue_reflection/modules/quartet_restoration/mappings/effect_material_rules.tsv"
        loader = container_loader or stage81.load_parent_containers
        progress("rehydrating the same four bounded parent effect containers")
        containers, skipped = loader(
            scope_rows=parent_scope,
            workspace_root=workspace,
            report_root=reports,
            rules_file=actual_rules,
            maximum_earc_bytes=maximum_earc_bytes,
        )
        require(not skipped, f"parent container loader skipped {len(skipped)} rows")
        require(len(containers) == EXPECTED_PARENT_CONTAINERS, f"expected {EXPECTED_PARENT_CONTAINERS} parent containers, found {len(containers)}")
        pair_by_key, all_pairs = stage86.index_pairs(containers)
        require(len(all_pairs) == EXPECTED_SIBLING_PAIRS, f"expected {EXPECTED_SIBLING_PAIRS} sibling pairs, found {len(all_pairs)}")

        grouped: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
        for row in layout_rows:
            key = (row.get("normalized_path", "").casefold(), row.get("member_key", "").casefold(), row.get("side", "").casefold())
            grouped[key].append(dict(row))
        for rows in grouped.values():
            rows.sort(key=lambda row: parse_int(row.get("anchor"), -1))

        occurrences: dict[tuple[str, str, str, int], dict[str, Any]] = {}
        skipped_rows: list[dict[str, Any]] = []
        progress(f"reconstructing {len(layout_rows)} normalized anchored blocks")
        for (path_cf, member_cf, side), rows in grouped.items():
            pair = pair_by_key.get((path_cf, member_cf))
            require(pair is not None, f"missing focal pair: {(path_cf, member_cf, side)}")
            payload = pair[f"{side}_payload"]
            endpoint = parse_int(rows[0].get("endpoint"), -1)
            targets = stage95.structural_targets(rows, endpoint)
            for row in rows:
                anchor = parse_int(row.get("anchor"), -1)
                span = parse_int(row.get("declared_block_span"), -1)
                reference_index = parse_int(row.get("reference_index"), -1)
                if anchor < 0 or span <= 0 or span % 4 or anchor + span > len(payload):
                    skipped_rows.append({"scope": "occurrence", "side": side, "anchor": anchor, "reason": "invalid_block_geometry"})
                    continue
                raw = payload[anchor:anchor + span]
                normalized, relocations = stage95.normalize_block(payload, anchor, span, targets)
                occurrences[(path_cf, member_cf, side, reference_index)] = {
                    "row": row,
                    "raw": raw,
                    "normalized": normalized,
                    "relocation_count": len(relocations),
                }
        require(not skipped_rows, f"internal audit skipped {len(skipped_rows)} occurrences")
        require(len(occurrences) == EXPECTED_FOCAL_OCCURRENCES, "occurrence reconstruction count mismatch")

        def candidate(side: str, variant: str, ordinal: int = 0) -> dict[str, Any]:
            matches = [
                value for key, value in occurrences.items()
                if key[2] == side
                and value["row"].get("cluster_role") == "candidate_ringlight"
                and value["row"].get("variant_label") == variant
            ]
            matches.sort(key=lambda value: parse_int(value["row"].get("reference_index"), -1))
            require(ordinal < len(matches), f"missing candidate occurrence {side} {variant} #{ordinal}")
            return matches[ordinal]

        source30 = candidate("source", "equal_float_30")
        target30 = candidate("target", "equal_float_30")
        source150 = candidate("source", "equal_float_150")
        target75a = candidate("target", "equal_float_75", 0)
        target75b = candidate("target", "equal_float_75", 1)
        source2 = candidate("source", "equal_float_2")
        target2 = candidate("target", "equal_float_2")

        specs = [
            ("stable_30_source_target", source30, target30, "stable_control"),
            ("stable_2_source_target", source2, target2, "stable_control"),
            ("ambiguous_150_to_first_75", source150, target75a, "ambiguous_candidate"),
            ("ambiguous_150_to_second_75", source150, target75b, "ambiguous_candidate"),
            ("duplicate_target_75_pair", target75a, target75b, "duplicate_target"),
        ]

        diff_by_comparison: dict[str, list[dict[str, Any]]] = {}
        progress("localizing aligned dword differences")
        for name, left, right, role in specs:
            left_block = left["normalized"]
            right_block = right["normalized"]
            require(len(left_block) == len(right_block) and len(left_block) % 4 == 0, f"comparison geometry mismatch: {name}")
            rows: list[dict[str, Any]] = []
            for relative_byte in range(0, len(left_block), 4):
                left_u32 = u32(left_block, relative_byte)
                right_u32 = u32(right_block, relative_byte)
                if left_u32 == right_u32:
                    continue
                left_target = relative_byte + signed_i32(left_u32)
                right_target = relative_byte + signed_i32(right_u32)
                left_internal = 0 <= left_target < len(left_block) and left_target % 4 == 0
                right_internal = 0 <= right_target < len(right_block) and right_target % 4 == 0
                equivalent_internal_reference = left_internal and right_internal and left_target == right_target
                rows.append({
                    "comparison": name,
                    "comparison_role": role,
                    "relative_dword": relative_byte // 4,
                    "relative_byte": relative_byte,
                    "segment": segment_for(relative_byte),
                    "left_u32_hex": f"0x{left_u32:08x}",
                    "right_u32_hex": f"0x{right_u32:08x}",
                    "left_i32": signed_i32(left_u32),
                    "right_i32": signed_i32(right_u32),
                    "left_float32": float32_text(left_u32),
                    "right_float32": float32_text(right_u32),
                    "left_internal_target_relative": left_target if left_internal else "",
                    "right_internal_target_relative": right_target if right_internal else "",
                    "equivalent_intra_block_reference": equivalent_internal_reference,
                    "transition_signature": f"{relative_byte // 4}:0x{left_u32:08x}->0x{right_u32:08x}",
                })
            diff_by_comparison[name] = rows

        stable30_signatures = {row["transition_signature"] for row in diff_by_comparison["stable_30_source_target"]}
        stable2_signatures = {row["transition_signature"] for row in diff_by_comparison["stable_2_source_target"]}
        consensus_stable = stable30_signatures & stable2_signatures
        any_stable = stable30_signatures | stable2_signatures

        duplicate_offsets = {parse_int(row["relative_dword"], -1) for row in diff_by_comparison["duplicate_target_75_pair"]}
        all_diff_rows: list[dict[str, Any]] = []
        island_rows: list[dict[str, Any]] = []
        reference_candidate_rows: list[dict[str, Any]] = []
        stable_transition_rows: list[dict[str, Any]] = []

        for name, left, right, role in specs:
            rows = diff_by_comparison[name]
            left_block = left["normalized"]
            right_block = right["normalized"]
            for row in rows:
                signature = row["transition_signature"]
                relative_dword = parse_int(row["relative_dword"], -1)
                row["seen_in_any_stable_control_same_offset"] = signature in any_stable
                row["seen_in_both_stable_controls_same_offset"] = signature in consensus_stable
                row["same_offset_differs_between_target_75_blocks"] = relative_dword in duplicate_offsets
                all_diff_rows.append(row)
                if parse_bool(row["equivalent_intra_block_reference"]):
                    reference_candidate_rows.append(dict(row))
            indices = [parse_int(row["relative_dword"], -1) for row in rows]
            row_by_index = {parse_int(row["relative_dword"], -1): row for row in rows}
            for island_index, (start, end) in enumerate(contiguous_islands(indices)):
                start_byte = start * 4
                end_byte = (end + 1) * 4
                context_start = max(0, start_byte - CONTEXT_DWORDS * 4)
                context_end = min(len(left_block), end_byte + CONTEXT_DWORDS * 4)
                island_diff_rows = [row_by_index[index] for index in range(start, end + 1) if index in row_by_index]
                island_rows.append({
                    "comparison": name,
                    "comparison_role": role,
                    "island_index": island_index,
                    "start_relative_dword": start,
                    "end_relative_dword": end,
                    "start_relative_byte": start_byte,
                    "end_relative_byte_exclusive": end_byte,
                    "dword_count": end - start + 1,
                    "segment_start": segment_for(start_byte),
                    "segment_end": segment_for(end_byte - 4),
                    "consensus_stable_transition_dwords": sum(parse_bool(row["seen_in_both_stable_controls_same_offset"]) for row in island_diff_rows),
                    "equivalent_intra_block_reference_dwords": sum(parse_bool(row["equivalent_intra_block_reference"]) for row in island_diff_rows),
                    "left_context_sha256": sha256(left_block[context_start:context_end]),
                    "right_context_sha256": sha256(right_block[context_start:context_end]),
                    "context_start_relative_byte": context_start,
                    "context_end_relative_byte_exclusive": context_end,
                })

        for source_name in ("stable_30_source_target", "stable_2_source_target"):
            for row in diff_by_comparison[source_name]:
                stable_transition_rows.append({
                    "source_comparison": source_name,
                    "relative_dword": row["relative_dword"],
                    "relative_byte": row["relative_byte"],
                    "segment": row["segment"],
                    "left_u32_hex": row["left_u32_hex"],
                    "right_u32_hex": row["right_u32_hex"],
                    "transition_signature": row["transition_signature"],
                    "present_in_other_stable_control": row["transition_signature"] in consensus_stable,
                })

        residual_rows: list[dict[str, Any]] = []
        residual_counts: dict[str, int] = {}
        for name in ("ambiguous_150_to_first_75", "ambiguous_150_to_second_75"):
            rows = diff_by_comparison[name]
            residual = [row for row in rows if row["transition_signature"] not in consensus_stable]
            residual_counts[name] = len(residual)
            by_segment = Counter(row["segment"] for row in residual)
            residual_rows.append({
                "comparison": name,
                "normalized_dword_differences": len(rows),
                "consensus_stable_masked_dwords": len(rows) - len(residual),
                "residual_dword_differences": len(residual),
                "residual_record_dwords": by_segment.get("reference_record", 0),
                "residual_trailer_dwords": by_segment.get("post_record_trailer", 0),
                "residual_prefix_dwords": by_segment.get("pre_record_prefix", 0),
                "equivalent_intra_block_reference_residuals": sum(parse_bool(row["equivalent_intra_block_reference"]) for row in residual),
                "target_duplicate_divergence_residuals": sum(parse_int(row["relative_dword"], -1) in duplicate_offsets for row in residual),
            })

        first_residual = residual_counts["ambiguous_150_to_first_75"]
        second_residual = residual_counts["ambiguous_150_to_second_75"]
        exact_unique = (first_residual == 0) ^ (second_residual == 0)
        duplicate_distinct = bool(diff_by_comparison["duplicate_target_75_pair"])
        identity_resolved = exact_unique and duplicate_distinct
        closest = "first_target_75" if first_residual < second_residual else "second_target_75" if second_residual < first_residual else "tie"
        reason = (
            "exactly one target is an exact peer after masking only transitions proven identically by both stable controls"
            if identity_resolved
            else "one target may be closer, but neither has a unique exact peer after the conservative stable-control mask"
        )

        decision_rows = [
            {"question": "are both target 75 blocks distinct", "answer": duplicate_distinct, "classification": "duplicate_target_blocks_distinct"},
            {"question": "which target 75 has fewer conservative residual dword differences", "answer": closest, "classification": "distance_only_not_identity"},
            {"question": "does exactly one target 75 become an exact peer after the consensus stable-control mask", "answer": identity_resolved, "classification": "target_occurrence_identity_resolved" if identity_resolved else "target_occurrence_identity_unresolved"},
        ]

        output = reports / REPORT_DIR
        output.mkdir(parents=True, exist_ok=True)
        write_tsv(output / "SLOT_LIGHT_INTERNAL_DWORD_DIFFERENCES.tsv", [
            "comparison", "comparison_role", "relative_dword", "relative_byte", "segment",
            "left_u32_hex", "right_u32_hex", "left_i32", "right_i32", "left_float32", "right_float32",
            "left_internal_target_relative", "right_internal_target_relative", "equivalent_intra_block_reference",
            "seen_in_any_stable_control_same_offset", "seen_in_both_stable_controls_same_offset",
            "same_offset_differs_between_target_75_blocks", "transition_signature",
        ], all_diff_rows)
        write_tsv(output / "SLOT_LIGHT_INTERNAL_CHANGE_ISLANDS.tsv", [
            "comparison", "comparison_role", "island_index", "start_relative_dword", "end_relative_dword",
            "start_relative_byte", "end_relative_byte_exclusive", "dword_count", "segment_start", "segment_end",
            "consensus_stable_transition_dwords", "equivalent_intra_block_reference_dwords",
            "left_context_sha256", "right_context_sha256", "context_start_relative_byte", "context_end_relative_byte_exclusive",
        ], island_rows)
        write_tsv(output / "SLOT_LIGHT_STABLE_CONTROL_TRANSITIONS.tsv", [
            "source_comparison", "relative_dword", "relative_byte", "segment", "left_u32_hex", "right_u32_hex",
            "transition_signature", "present_in_other_stable_control",
        ], stable_transition_rows)
        write_tsv(output / "SLOT_LIGHT_AMBIGUOUS_PAIR_RESIDUALS.tsv", [
            "comparison", "normalized_dword_differences", "consensus_stable_masked_dwords", "residual_dword_differences",
            "residual_prefix_dwords", "residual_record_dwords", "residual_trailer_dwords",
            "equivalent_intra_block_reference_residuals", "target_duplicate_divergence_residuals",
        ], residual_rows)
        write_tsv(output / "SLOT_LIGHT_INTRA_BLOCK_REFERENCE_CANDIDATES.tsv", [
            "comparison", "comparison_role", "relative_dword", "relative_byte", "segment",
            "left_u32_hex", "right_u32_hex", "left_i32", "right_i32",
            "left_internal_target_relative", "right_internal_target_relative", "equivalent_intra_block_reference",
            "seen_in_any_stable_control_same_offset", "seen_in_both_stable_controls_same_offset",
        ], reference_candidate_rows)
        write_tsv(output / "SLOT_LIGHT_INTERNAL_IDENTITY_DECISION.tsv", ["question", "answer", "classification"], decision_rows)
        write_tsv(output / "SLOT_LIGHT_INTERNAL_CHANGE_SKIPPED.tsv", ["scope", "side", "anchor", "reason"], skipped_rows)

        segment_counter = Counter(row["segment"] for row in all_diff_rows)
        summary = {
            "type": "br_quartet_restoration_reflector_slot_light_anchored_block_internal_change_evidence_summary",
            "format_version": 1,
            "tool_version": TOOL_VERSION,
            "source_stage95_tool_version": summary95.get("tool_version"),
            "status": "anchored_block_internal_differences_localized_target_identity_requires_unique_exact_peer",
            "sibling_G1E_G1EM_member_rows": len(all_pairs),
            "focal_occurrence_rows": len(occurrences),
            "comparison_rows": len(specs),
            "internal_dword_difference_rows": len(all_diff_rows),
            "internal_change_island_rows": len(island_rows),
            "stable_control_transition_rows": len(stable_transition_rows),
            "consensus_stable_transition_signatures": len(consensus_stable),
            "intra_block_reference_candidate_rows": len(reference_candidate_rows),
            "prefix_difference_rows": segment_counter.get("pre_record_prefix", 0),
            "record_difference_rows": segment_counter.get("reference_record", 0),
            "trailer_difference_rows": segment_counter.get("post_record_trailer", 0),
            "candidate_source_150_to_first_target_75_residual_dword_differences": first_residual,
            "candidate_source_150_to_second_target_75_residual_dword_differences": second_residual,
            "candidate_closest_target_by_residual_distance": closest,
            "candidate_target_duplicate_75_blocks_distinct": duplicate_distinct,
            "candidate_target_occurrence_identity_resolved": identity_resolved,
            "candidate_target_occurrence_identity_reason": reason,
            "technical_leaf_semantics_resolved": False,
            "brightness_semantics_confirmed": False,
            "censorship_semantics_confirmed": False,
            "prototype_candidate_rows": 0,
            "skipped_rows": len(skipped_rows),
            "parameters": {
                "block_normalization": "stage95 exact bounded structural references only",
                "stable_control_mask": "same relative dword and exact u32 transition must occur in both stable 30 and stable 2 controls",
                "identity_gate": "exactly one target 75 must have zero residual dword differences and duplicate target blocks must be distinct",
                "context_dwords_each_side": CONTEXT_DWORDS,
            },
            "next_action": "Upload this report. If neither target is an exact conservative peer, continue only with a read-only recurrence audit of the remaining record/trailer dword shapes across the bounded sibling corpus; do not write G1E or infer brightness/censorship.",
            "policy": {
                "render_payload_written": False,
                "full_proprietary_payloads_exported": False,
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
        (output / "SUMMARY.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        archive = reports / REPORT_NAME if create_archive else None
        if archive is not None:
            progress("creating compressed report archive")
            make_archive(output, archive)
        progress("completed")
        return output, archive, summary


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path, default=PROJECT_ROOT_DEFAULT)
    parser.add_argument("--no-report-archive", action="store_true")
    parser.add_argument("--maximum-earc-bytes", type=int, default=512 * 1024 * 1024)
    args = parser.parse_args(argv)
    try:
        output, archive, summary = build_report(
            args.project_root,
            create_archive=not args.no_report_archive,
            maximum_earc_bytes=args.maximum_earc_bytes,
        )
    except Stage96Error as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print(f"Report directory: {output}")
    if archive is not None:
        print(f"Report: {archive}")
    print(f"Residual dword differences: {summary['candidate_source_150_to_first_target_75_residual_dword_differences']} / {summary['candidate_source_150_to_second_target_75_residual_dword_differences']}")
    print(f"Closest target: {summary['candidate_closest_target_by_residual_distance']}")
    print(f"Occurrence identity resolved: {summary['candidate_target_occurrence_identity_resolved']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
