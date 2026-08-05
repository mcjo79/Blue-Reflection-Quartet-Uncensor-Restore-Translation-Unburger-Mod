#!/usr/bin/env python3
"""Audit the six non-common Reflector ringlight/eyelight G1E members.

Stage 83 closes the shared e_cmn_ringlight_PC00-PC14 family as a uniform
8-byte record-layout compaction with no semantic residual.  This stage keeps
that family excluded and rehydrates only the six structurally different light
members inventoried by stage 79/80.  It builds a conservative aligned-anchor
map, records insertion/deletion/replacement regions, classifies changed dwords
without assigning brightness semantics, and writes metadata only.
"""
from __future__ import annotations

import argparse
import bisect
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

TOOL_VERSION = "0.0.98"
REPORT_NAME = "BR_quartet_restoration_reflector_slot_light_g1e_structure_evidence.tar.zst"
REPORT_DIR = "reflector_slot_light_g1e_structure_evidence"
STAGE79_DIR = "reflector_character_slot_render_member_evidence"
STAGE79_ARCHIVE = "BR_quartet_restoration_reflector_character_slot_render_member_evidence.tar.zst"
STAGE80_DIR = "reflector_light_family_binary_evidence"
STAGE80_ARCHIVE = "BR_quartet_restoration_reflector_light_family_binary_evidence.tar.zst"
STAGE83_DIR = "reflector_ringlight_structural_shift_evidence"
STAGE83_ARCHIVE = "BR_quartet_restoration_reflector_ringlight_structural_shift_evidence.tar.zst"
COMMON_FAMILY_KEY = "ringlight:e_cmn_ringlight_PCXX.g1e"
EXPECTED_SCOPE_ROWS = 6
ANCHOR_BLOCK_BYTES = 16
ANCHOR_STEP_BYTES = 4
MIN_MATCH_RUN_BYTES = 16
HEADER_DWORD_BYTES = 96


class Stage84Error(RuntimeError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise Stage84Error(message)


def progress(message: str) -> None:
    print(f"[stage84] {message}", file=sys.stderr, flush=True)


def parse_int(value: Any, default: int = 0) -> int:
    try:
        text = str(value).strip()
        if text.lower().startswith("0x"):
            return int(text, 16)
        return int(text)
    except (TypeError, ValueError):
        return default


def parse_bool(value: Any) -> bool:
    return str(value).strip().casefold() in {"1", "true", "yes", "y"}


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def safe_name(raw: str) -> str:
    path = PurePosixPath(raw)
    require(not path.is_absolute() and path.parts and ".." not in path.parts, f"unsafe archive member: {raw}")
    return path.as_posix()


def read_tsv(path: Path, required: bool = True) -> list[dict[str, str]]:
    if not path.is_file():
        if required:
            raise Stage84Error(f"missing required TSV: {path}")
        return []
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
        raise Stage84Error(f"invalid JSON {path}: {exc}") from exc
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
    spec = importlib.util.spec_from_file_location(name, path)
    require(spec is not None and spec.loader is not None, f"cannot load module: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def stable_export_key(row: Mapping[str, Any]) -> tuple[str, str]:
    return (str(row.get("normalized_path", "")).casefold(), str(row.get("member_key", "")).casefold())


def stable_scope_key(row: Mapping[str, Any]) -> tuple[str, str, str]:
    return (
        str(row.get("candidate_id", "")),
        str(row.get("normalized_path", "")).casefold(),
        str(row.get("member_key", "")).casefold(),
    )


def validate_stage83(root: Path) -> dict[str, Any]:
    summary = load_json(root / "SUMMARY.json")
    require(summary.get("type") == "br_quartet_restoration_reflector_ringlight_structural_shift_evidence_summary", "stage83 type mismatch")
    require(summary.get("tool_version") == "0.0.97", "stage83 tool version mismatch")
    require(summary.get("status") == "common_ringlight_delta_fully_explained_by_uniform_eight_byte_record_compaction_no_brightness_leaf_residual", "stage83 closure status mismatch")
    require(parse_int(summary.get("common_ringlight_member_rows"), -1) == 15, "stage83 common member count mismatch")
    require(parse_int(summary.get("common_ringlight_changed_dword_rows"), -1) == 36, "stage83 changed dword count mismatch")
    require(summary.get("model_shift_values") == [8], "stage83 shift model must be exactly 8 bytes")
    require(parse_bool(summary.get("uniform_shift_across_clusters")), "stage83 shift is not uniform")
    require(parse_int(summary.get("complete_cluster_model_rows"), -1) == 3, "stage83 cluster closure mismatch")
    require(parse_int(summary.get("explained_dword_rows"), -1) == 36, "stage83 did not explain all dwords")
    require(parse_int(summary.get("residual_dword_rows"), -1) == 0, "stage83 contains residual dwords")
    require(parse_int(summary.get("exact_slot_model_rows"), -1) == 15, "stage83 slot validation mismatch")
    require(parse_int(summary.get("brightness_leaf_residual_rows"), -1) == 0, "stage83 contains brightness-leaf residuals")
    require(parse_int(summary.get("prototype_candidate_rows"), -1) == 0, "stage83 unexpectedly produced a prototype candidate")
    require(parse_int(summary.get("skipped_rows"), -1) == 0, "stage83 contains skipped rows")
    return summary


def unique_block_positions(payload: bytes, block_size: int, step: int) -> dict[bytes, int]:
    counts: Counter[bytes] = Counter()
    positions: dict[bytes, int] = {}
    for offset in range(0, max(0, len(payload) - block_size + 1), step):
        block = payload[offset:offset + block_size]
        counts[block] += 1
        positions[block] = offset
    return {block: positions[block] for block, count in counts.items() if count == 1}


def longest_increasing_anchor_chain(pairs: Sequence[tuple[int, int]]) -> list[tuple[int, int]]:
    if not pairs:
        return []
    ordered = sorted(set(pairs))
    tails: list[int] = []
    tail_indices: list[int] = []
    predecessors = [-1] * len(ordered)
    for index, (_source, target) in enumerate(ordered):
        pos = bisect.bisect_left(tails, target)
        if pos == len(tails):
            tails.append(target)
            tail_indices.append(index)
        else:
            tails[pos] = target
            tail_indices[pos] = index
        if pos:
            predecessors[index] = tail_indices[pos - 1]
    chain: list[tuple[int, int]] = []
    cursor = tail_indices[-1]
    while cursor >= 0:
        chain.append(ordered[cursor])
        cursor = predecessors[cursor]
    return list(reversed(chain))


def discover_match_runs(source: bytes, target: bytes, block_size: int = ANCHOR_BLOCK_BYTES, step: int = ANCHOR_STEP_BYTES) -> list[dict[str, int]]:
    source_unique = unique_block_positions(source, block_size, step)
    target_unique = unique_block_positions(target, block_size, step)
    pairs = [(source_offset, target_unique[block]) for block, source_offset in source_unique.items() if block in target_unique]
    chain = longest_increasing_anchor_chain(pairs)
    if not chain:
        prefix = 0
        limit = min(len(source), len(target))
        while prefix < limit and source[prefix] == target[prefix]:
            prefix += 1
        suffix = 0
        while suffix < limit - prefix and source[len(source)-1-suffix] == target[len(target)-1-suffix]:
            suffix += 1
        runs = []
        if prefix >= MIN_MATCH_RUN_BYTES:
            runs.append({"source_start": 0, "target_start": 0, "length": prefix})
        if suffix >= MIN_MATCH_RUN_BYTES:
            runs.append({"source_start": len(source)-suffix, "target_start": len(target)-suffix, "length": suffix})
        return runs

    runs: list[dict[str, int]] = []
    start_s, start_t = chain[0]
    last_s, last_t = start_s, start_t
    for source_offset, target_offset in chain[1:]:
        if source_offset == last_s + step and target_offset == last_t + step:
            last_s, last_t = source_offset, target_offset
            continue
        length = last_s - start_s + block_size
        if length >= MIN_MATCH_RUN_BYTES:
            runs.append({"source_start": start_s, "target_start": start_t, "length": length})
        start_s, start_t = source_offset, target_offset
        last_s, last_t = source_offset, target_offset
    length = last_s - start_s + block_size
    if length >= MIN_MATCH_RUN_BYTES:
        runs.append({"source_start": start_s, "target_start": start_t, "length": length})

    filtered: list[dict[str, int]] = []
    for run in sorted(runs, key=lambda item: (item["source_start"], item["target_start"])):
        if filtered:
            previous = filtered[-1]
            if run["source_start"] < previous["source_start"] + previous["length"] or run["target_start"] < previous["target_start"] + previous["length"]:
                continue
        filtered.append(run)
    return filtered


def classify_gap(source_span: bytes, target_span: bytes) -> str:
    if not source_span and target_span:
        return "target_insertion"
    if source_span and not target_span:
        return "target_deletion"
    if len(source_span) == len(target_span):
        return "same_size_replacement"
    return "size_changing_replacement"


def zero_fraction(payload: bytes) -> float:
    if not payload:
        return 0.0
    return payload.count(0) / len(payload)


def build_alignment_segments(source: bytes, target: bytes) -> tuple[list[dict[str, Any]], list[dict[str, int]]]:
    runs = discover_match_runs(source, target)
    segments: list[dict[str, Any]] = []
    source_cursor = 0
    target_cursor = 0
    for run in runs:
        source_start = run["source_start"]
        target_start = run["target_start"]
        if source_start < source_cursor or target_start < target_cursor:
            continue
        if source_start != source_cursor or target_start != target_cursor:
            source_span = source[source_cursor:source_start]
            target_span = target[target_cursor:target_start]
            segments.append({
                "segment_type": classify_gap(source_span, target_span),
                "source_start": source_cursor,
                "source_end_exclusive": source_start,
                "target_start": target_cursor,
                "target_end_exclusive": target_start,
                "source_length": len(source_span),
                "target_length": len(target_span),
                "size_delta": len(target_span) - len(source_span),
                "shift_before": target_cursor - source_cursor,
                "shift_after": target_start - source_start,
                "source_sha256": sha256(source_span),
                "target_sha256": sha256(target_span),
                "source_zero_fraction": f"{zero_fraction(source_span):.9f}",
                "target_zero_fraction": f"{zero_fraction(target_span):.9f}",
                "dword_phase_compatible": source_cursor % 4 == target_cursor % 4,
            })
        source_cursor = source_start + run["length"]
        target_cursor = target_start + run["length"]
    if source_cursor != len(source) or target_cursor != len(target):
        source_span = source[source_cursor:]
        target_span = target[target_cursor:]
        if source_span or target_span:
            segments.append({
                "segment_type": classify_gap(source_span, target_span),
                "source_start": source_cursor,
                "source_end_exclusive": len(source),
                "target_start": target_cursor,
                "target_end_exclusive": len(target),
                "source_length": len(source_span),
                "target_length": len(target_span),
                "size_delta": len(target_span) - len(source_span),
                "shift_before": target_cursor - source_cursor,
                "shift_after": len(target) - len(source),
                "source_sha256": sha256(source_span),
                "target_sha256": sha256(target_span),
                "source_zero_fraction": f"{zero_fraction(source_span):.9f}",
                "target_zero_fraction": f"{zero_fraction(target_span):.9f}",
                "dword_phase_compatible": source_cursor % 4 == target_cursor % 4,
            })
    return segments, runs


def finite_float_text(raw: bytes) -> tuple[str, str]:
    if len(raw) != 4:
        return "", "not_dword"
    value = struct.unpack("<f", raw)[0]
    if not math.isfinite(value):
        return "", "nonfinite"
    if 0 < abs(value) < 1.0e-30:
        return f"{value:.9g}", "subnormal_or_tiny"
    return f"{value:.9g}", "finite"


def is_small_aligned_offset(value: int) -> bool:
    return 0 < value <= 0x1000000 and value % 4 == 0


def classify_word(source_value: int, target_value: int, total_size_delta: int, source_float_status: str, target_float_status: str) -> str:
    if source_value == target_value:
        return "identical"
    difference = target_value - source_value
    if total_size_delta and difference in {total_size_delta, -total_size_delta} and (is_small_aligned_offset(source_value) or is_small_aligned_offset(target_value)):
        return "possible_relative_offset_or_length_rebase"
    if source_value in {0, 1, 2, 4, 8, 12, 16, 24, 32} or target_value in {0, 1, 2, 4, 8, 12, 16, 24, 32}:
        return "small_integer_or_flag_transition"
    if source_float_status == "finite" and target_float_status == "finite":
        source_float = struct.unpack("<f", source_value.to_bytes(4, "little"))[0]
        target_float = struct.unpack("<f", target_value.to_bytes(4, "little"))[0]
        if abs(source_float) <= 1.0e6 and abs(target_float) <= 1.0e6:
            return "finite_float_transition_unresolved"
    return "opaque_dword_transition"


def changed_words_for_segment(source: bytes, target: bytes, segment: Mapping[str, Any], total_size_delta: int) -> list[dict[str, Any]]:
    source_start = parse_int(segment.get("source_start"), -1)
    target_start = parse_int(segment.get("target_start"), -1)
    source_length = parse_int(segment.get("source_length"), 0)
    target_length = parse_int(segment.get("target_length"), 0)
    if source_start < 0 or target_start < 0 or source_start % 4 != target_start % 4:
        return []
    comparable = min(source_length, target_length)
    comparable -= comparable % 4
    rows: list[dict[str, Any]] = []
    for relative in range(0, comparable, 4):
        source_offset = source_start + relative
        target_offset = target_start + relative
        left = source[source_offset:source_offset + 4]
        right = target[target_offset:target_offset + 4]
        if left == right:
            continue
        source_value = int.from_bytes(left, "little")
        target_value = int.from_bytes(right, "little")
        source_float, source_status = finite_float_text(left)
        target_float, target_status = finite_float_text(right)
        classification = classify_word(source_value, target_value, total_size_delta, source_status, target_status)
        rows.append({
            "source_offset": source_offset,
            "target_offset": target_offset,
            "relative_offset": relative,
            "source_u32_hex": f"0x{source_value:08x}",
            "target_u32_hex": f"0x{target_value:08x}",
            "source_float32": source_float,
            "target_float32": target_float,
            "source_float_status": source_status,
            "target_float_status": target_status,
            "transition_classification": classification,
            "transition_id": sha256(left + right),
        })
    return rows


def build_report(
    project_root: Path,
    *,
    create_archive: bool = True,
    workspace_root: Path | None = None,
    report_root: Path | None = None,
    rules_file: Path | None = None,
    maximum_earc_bytes: int = 512 * 1024 * 1024,
    pair_loader: Callable[..., tuple[list[dict[str, Any]], list[dict[str, Any]]]] | None = None,
) -> tuple[Path, Path | None, dict[str, Any]]:
    project_root = project_root.resolve()
    reports = (report_root or project_root / ".local/reports/quartet_restoration").resolve()
    workspace = (workspace_root or project_root / ".local/build/quartet_restoration").resolve()
    require(reports.is_dir(), f"missing report root: {reports}")

    stage80 = load_module(project_root / "workstreams/quartet_restoration/collect_reflector_light_family_binary_evidence.py", "stage80_for_stage84")
    progress("validating stage 79, 80 and 83 reports")
    with tempfile.TemporaryDirectory(prefix="br-stage84-") as temporary_name:
        temporary = Path(temporary_name)
        stage79_root = locate(reports, STAGE79_DIR, STAGE79_ARCHIVE, temporary / "79")
        stage80_root = locate(reports, STAGE80_DIR, STAGE80_ARCHIVE, temporary / "80")
        stage83_root = locate(reports, STAGE83_DIR, STAGE83_ARCHIVE, temporary / "83")
        summary79 = stage80.validate_stage79(stage79_root)
        summary80 = load_json(stage80_root / "SUMMARY.json")
        require(summary80.get("type") == "br_quartet_restoration_reflector_light_family_binary_evidence_summary", "stage80 type mismatch")
        require(summary80.get("tool_version") == "0.0.93", "stage80 tool version mismatch")
        require(parse_int(summary80.get("scope_member_rows"), -1) == 21, "stage80 member count mismatch")
        require(parse_int(summary80.get("skipped_rows"), -1) == 0, "stage80 contains skipped rows")
        summary83 = validate_stage83(stage83_root)

        full_scope = stage80.select_scope(stage79_root)
        scope = [row for row in full_scope if row.get("family_key") != COMMON_FAMILY_KEY]
        require(len(scope) == EXPECTED_SCOPE_ROWS, f"expected {EXPECTED_SCOPE_ROWS} non-common light members, found {len(scope)}")
        require(sum(row.get("asset_role") == "ringlight" for row in scope) == 4, "expected four non-common ringlight members")
        require(sum(row.get("asset_role") == "eyelight" for row in scope) == 2, "expected two non-common eyelight members")

        audit_rows = read_tsv(stage80_root / "REFLECTOR_LIGHT_MEMBER_BINARY_AUDIT.tsv")
        audit_map: dict[tuple[str, str], dict[str, str]] = {}
        for row in audit_rows:
            key = stable_export_key(row)
            require(all(key), "stage80 audit row missing stable identity")
            require(key not in audit_map, f"duplicate stage80 audit identity: {key}")
            audit_map[key] = row

        actual_rules = rules_file or project_root / "titles/blue_reflection/modules/quartet_restoration/mappings/effect_material_rules.tsv"
        loader = pair_loader or stage80.targeted_rehydrate
        pairs, skipped = loader(
            scope_rows=scope,
            workspace_root=workspace,
            report_root=reports,
            rules_file=actual_rules,
            maximum_earc_bytes=maximum_earc_bytes,
        )
        if skipped:
            raise Stage84Error(f"targeted loader skipped {len(skipped)} rows")
        pair_map: dict[tuple[str, str, str], dict[str, Any]] = {}
        for pair in pairs:
            key = stable_scope_key(pair)
            require(key not in pair_map, f"duplicate rehydrated pair: {key}")
            pair_map[key] = pair
        require(len(pair_map) == EXPECTED_SCOPE_ROWS, f"rehydrated {len(pair_map)} of {EXPECTED_SCOPE_ROWS} scoped members")

        member_rows: list[dict[str, Any]] = []
        segment_rows: list[dict[str, Any]] = []
        match_rows: list[dict[str, Any]] = []
        word_rows: list[dict[str, Any]] = []
        header_rows: list[dict[str, Any]] = []
        skipped_rows: list[dict[str, Any]] = []

        for index, row in enumerate(scope, start=1):
            progress(f"auditing member {index}/{len(scope)}: {row.get('character_slot')} {row.get('member_name')}")
            key = stable_scope_key(row)
            pair = pair_map.get(key)
            require(pair is not None, f"rehydrated pair missing: {key}")
            audit = audit_map.get(stable_export_key(row))
            require(audit is not None, f"stage80 audit row missing: {stable_export_key(row)}")
            source = pair.get("source_payload")
            target = pair.get("target_payload")
            require(isinstance(source, (bytes, bytearray)) and isinstance(target, (bytes, bytearray)), f"payload missing: {key}")
            source = bytes(source); target = bytes(target)
            require(sha256(source) == audit.get("source_sha256"), f"source hash mismatch: {key}")
            require(sha256(target) == audit.get("target_sha256"), f"target hash mismatch: {key}")
            require(len(source) == parse_int(audit.get("source_size"), -1), f"source size mismatch: {key}")
            require(len(target) == parse_int(audit.get("target_size"), -1), f"target size mismatch: {key}")

            segments, runs = build_alignment_segments(source, target)
            require(segments or source == target, f"no change segments generated for changed member: {key}")
            total_delta = len(target) - len(source)
            local_words: list[dict[str, Any]] = []
            for segment_index, segment in enumerate(segments, start=1):
                segment_id = f"{row.get('character_slot')}_{index:02d}_segment_{segment_index:03d}"
                enriched = {
                    "character_slot": row.get("character_slot", ""),
                    "asset_role": row.get("asset_role", ""),
                    "family_key": row.get("family_key", ""),
                    "normalized_path": row.get("normalized_path", ""),
                    "member_key": row.get("member_key", ""),
                    "member_name": row.get("member_name", ""),
                    "segment_id": segment_id,
                    **segment,
                }
                segment_rows.append(enriched)
                for word in changed_words_for_segment(source, target, segment, total_delta):
                    local_words.append({**enriched, **word})
            word_rows.extend(local_words)
            for run_index, run in enumerate(runs, start=1):
                match_rows.append({
                    "character_slot": row.get("character_slot", ""),
                    "asset_role": row.get("asset_role", ""),
                    "family_key": row.get("family_key", ""),
                    "normalized_path": row.get("normalized_path", ""),
                    "member_key": row.get("member_key", ""),
                    "member_name": row.get("member_name", ""),
                    "match_run_index": run_index,
                    **run,
                    "shift_bytes": run["target_start"] - run["source_start"],
                })

            header_limit = min(HEADER_DWORD_BYTES, len(source), len(target))
            header_limit -= header_limit % 4
            for offset in range(0, header_limit, 4):
                left = source[offset:offset + 4]
                right = target[offset:offset + 4]
                if left == right:
                    continue
                source_value = int.from_bytes(left, "little")
                target_value = int.from_bytes(right, "little")
                source_float, source_float_status = finite_float_text(left)
                target_float, target_float_status = finite_float_text(right)
                header_rows.append({
                    "character_slot": row.get("character_slot", ""),
                    "asset_role": row.get("asset_role", ""),
                    "family_key": row.get("family_key", ""),
                    "normalized_path": row.get("normalized_path", ""),
                    "member_key": row.get("member_key", ""),
                    "member_name": row.get("member_name", ""),
                    "word_offset": offset,
                    "source_u32_hex": f"0x{source_value:08x}",
                    "target_u32_hex": f"0x{target_value:08x}",
                    "source_float32": source_float,
                    "target_float32": target_float,
                    "source_float_status": source_float_status,
                    "target_float_status": target_float_status,
                    "transition_classification": classify_word(source_value, target_value, total_delta, source_float_status, target_float_status),
                })

            counts = Counter(segment["segment_type"] for segment in segments)
            word_counts = Counter(word["transition_classification"] for word in local_words)
            member_rows.append({
                "character_slot": row.get("character_slot", ""),
                "asset_role": row.get("asset_role", ""),
                "family_key": row.get("family_key", ""),
                "normalized_path": row.get("normalized_path", ""),
                "member_key": row.get("member_key", ""),
                "member_name": row.get("member_name", ""),
                "source_size": len(source),
                "target_size": len(target),
                "size_delta": total_delta,
                "source_sha256": sha256(source),
                "target_sha256": sha256(target),
                "stage80_audit_status": audit.get("audit_status", ""),
                "match_run_rows": len(runs),
                "change_segment_rows": len(segments),
                "target_insertion_rows": counts["target_insertion"],
                "target_deletion_rows": counts["target_deletion"],
                "same_size_replacement_rows": counts["same_size_replacement"],
                "size_changing_replacement_rows": counts["size_changing_replacement"],
                "changed_dword_rows": len(local_words),
                "finite_float_transition_rows": word_counts["finite_float_transition_unresolved"],
                "offset_or_length_rebase_rows": word_counts["possible_relative_offset_or_length_rebase"],
                "small_integer_or_flag_rows": word_counts["small_integer_or_flag_transition"],
                "opaque_dword_rows": word_counts["opaque_dword_transition"],
                "alignment_anchor_status": "anchored_metadata_complete" if runs else "prefix_suffix_only_metadata",
                "brightness_semantics": "unresolved",
                "prototype_status": "evidence_only_no_format_aware_write",
            })

        require(len(member_rows) == EXPECTED_SCOPE_ROWS, "member audit row count mismatch")
        require(not skipped_rows, "unexpected skipped rows")
        finite_rows = [row for row in word_rows if row.get("transition_classification") == "finite_float_transition_unresolved"]
        same_size_rows = [row for row in member_rows if parse_int(row.get("size_delta")) == 0]
        size_changed_rows = [row for row in member_rows if parse_int(row.get("size_delta")) != 0]

        output_dir = reports / REPORT_DIR
        if output_dir.exists():
            for child in output_dir.iterdir():
                if child.is_file() or child.is_symlink():
                    child.unlink()
                elif child.is_dir():
                    import shutil
                    shutil.rmtree(child)
        output_dir.mkdir(parents=True, exist_ok=True)

        write_tsv(output_dir / "SLOT_LIGHT_MEMBER_STRUCTURE_AUDIT.tsv", [
            "character_slot", "asset_role", "family_key", "normalized_path", "member_key", "member_name",
            "source_size", "target_size", "size_delta", "source_sha256", "target_sha256", "stage80_audit_status",
            "match_run_rows", "change_segment_rows", "target_insertion_rows", "target_deletion_rows",
            "same_size_replacement_rows", "size_changing_replacement_rows", "changed_dword_rows",
            "finite_float_transition_rows", "offset_or_length_rebase_rows", "small_integer_or_flag_rows",
            "opaque_dword_rows", "alignment_anchor_status", "brightness_semantics", "prototype_status",
        ], member_rows)
        write_tsv(output_dir / "SLOT_LIGHT_ALIGNMENT_SEGMENTS.tsv", [
            "character_slot", "asset_role", "family_key", "normalized_path", "member_key", "member_name", "segment_id",
            "segment_type", "source_start", "source_end_exclusive", "target_start", "target_end_exclusive",
            "source_length", "target_length", "size_delta", "shift_before", "shift_after", "source_sha256", "target_sha256",
            "source_zero_fraction", "target_zero_fraction", "dword_phase_compatible",
        ], segment_rows)
        write_tsv(output_dir / "SLOT_LIGHT_EXACT_MATCH_RUNS.tsv", [
            "character_slot", "asset_role", "family_key", "normalized_path", "member_key", "member_name",
            "match_run_index", "source_start", "target_start", "length", "shift_bytes",
        ], match_rows)
        write_tsv(output_dir / "SLOT_LIGHT_ALIGNED_CHANGED_DWORDS.tsv", [
            "character_slot", "asset_role", "family_key", "normalized_path", "member_key", "member_name", "segment_id",
            "source_offset", "target_offset", "relative_offset", "source_u32_hex", "target_u32_hex",
            "source_float32", "target_float32", "source_float_status", "target_float_status",
            "transition_classification", "transition_id",
        ], word_rows)
        write_tsv(output_dir / "SLOT_LIGHT_HEADER_DWORD_TRANSITIONS.tsv", [
            "character_slot", "asset_role", "family_key", "normalized_path", "member_key", "member_name", "word_offset",
            "source_u32_hex", "target_u32_hex", "source_float32", "target_float32", "source_float_status", "target_float_status",
            "transition_classification",
        ], header_rows)
        write_tsv(output_dir / "SLOT_LIGHT_FINITE_FLOAT_LEADS.tsv", [
            "character_slot", "asset_role", "family_key", "normalized_path", "member_key", "member_name", "segment_id",
            "source_offset", "target_offset", "relative_offset", "source_u32_hex", "target_u32_hex",
            "source_float32", "target_float32", "transition_id", "transition_classification",
        ], finite_rows)
        write_tsv(output_dir / "SLOT_LIGHT_STRUCTURE_SKIPPED.tsv", [
            "scope", "normalized_path", "member_key", "side", "reason",
        ], skipped_rows)

        summary = {
            "type": "br_quartet_restoration_reflector_slot_light_g1e_structure_evidence_summary",
            "format_version": 1,
            "tool_version": TOOL_VERSION,
            "source_stage83_tool_version": summary83.get("tool_version"),
            "source_stage80_tool_version": summary80.get("tool_version"),
            "source_stage79_tool_version": summary79.get("tool_version"),
            "status": "non_common_reflector_light_members_structurally_aligned_semantic_brightness_values_not_yet_resolved",
            "scope_member_rows": len(member_rows),
            "ringlight_member_rows": sum(row.get("asset_role") == "ringlight" for row in member_rows),
            "eyelight_member_rows": sum(row.get("asset_role") == "eyelight" for row in member_rows),
            "same_size_member_rows": len(same_size_rows),
            "size_changed_member_rows": len(size_changed_rows),
            "alignment_segment_rows": len(segment_rows),
            "exact_match_run_rows": len(match_rows),
            "aligned_changed_dword_rows": len(word_rows),
            "finite_float_lead_rows": len(finite_rows),
            "header_transition_rows": len(header_rows),
            "prototype_candidate_rows": 0,
            "brightness_semantics_confirmed": False,
            "heroine_name_bindings_resolved": 0,
            "common_ringlight_closed_as_structural_compaction": True,
            "common_ringlight_residual_dword_rows": 0,
            "skipped_rows": len(skipped_rows),
            "parameters": {
                "anchor_block_bytes": ANCHOR_BLOCK_BYTES,
                "anchor_step_bytes": ANCHOR_STEP_BYTES,
                "minimum_match_run_bytes": MIN_MATCH_RUN_BYTES,
                "header_dword_bytes": HEADER_DWORD_BYTES,
                "alignment_method": "unique_aligned_16_byte_blocks_plus_monotonic_LIS_chain",
            },
            "policy": {
                "installed_game_modified": False,
                "render_payload_written": False,
                "event_payload_written": False,
                "global_bloom_hdr_gamma_or_exposure_restore_attempted": False,
                "pak_repacked": False,
                "core_registry_modified": False,
                "profile_activated": False,
                "runtime_validation_inferred": False,
                "censorship_semantics_inferred": False,
                "heroine_names_inferred_from_slot_numbers": False,
                "canary_track_modified": False,
                "full_proprietary_payloads_exported": False,
            },
            "next_action": "Upload this report. Review structural insertion/replacement maps and finite-float leads for the six non-common slot light members. Do not promote any value until a full G1E record parser or neutral sibling record mapping proves that the value is a semantic leaf rather than an offset, length, flag or serializer change.",
        }
        (output_dir / "SUMMARY.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

        archive_path: Path | None = None
        if create_archive:
            archive_path = reports / REPORT_NAME
            make_archive(output_dir, archive_path)
        progress("completed")
        return output_dir, archive_path, summary


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path, default=PROJECT_ROOT_DEFAULT)
    parser.add_argument("--no-archive", action="store_true")
    args = parser.parse_args(argv)
    try:
        output, archive, summary = build_report(args.project_root, create_archive=not args.no_archive)
    except Stage84Error as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print(json.dumps({"output_dir": str(output), "archive": str(archive) if archive else None, "summary": summary}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
