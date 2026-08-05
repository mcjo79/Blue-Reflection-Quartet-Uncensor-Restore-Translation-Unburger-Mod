#!/usr/bin/env python3
"""Audit bounded block/trailer continuity for the seven unresolved one-edit pairs.

Stage 111 aligned 193 mutually unique source/target section pairs.  It resolved
185 zero-edit pairs plus the independently proven PC02 ringlight canary, but
left seven one-insertion/deletion pairs ambiguous because multiple ordinal
models satisfy the section-offset geometry.  This stage rehydrates only the two
already-scoped parent effect containers that hold those seven members and the
PC02 canary.  It reconstructs the 108-byte pre-record envelope, 44-byte shared
record and post-record trailer for every involved occurrence.

Paired-float leaves and confirmed field-relative structural references are
masked before block comparison.  A non-canary model may resolve identity only
when it is the sole model whose every matched block has zero structural
residual and whose inserted/deleted block remains structurally distinct from
all matched blocks.  Distance, value equality and numeric closeness never select
an occurrence.  The stage-99 PC02 decision is an immutable canary: this stage
may confirm it or remain non-discriminating, but it must never contradict it.

The collector is read-only.  It never writes G1E/G1EM, Elixir, PAK, profile,
registry or installed-game payloads and never infers brightness, intensity or
censorship semantics.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
from collections import Counter, defaultdict
from pathlib import Path, PurePosixPath
from typing import Any, Callable, Iterable, Mapping, Sequence

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT_DEFAULT = SCRIPT_DIR.parent.parent
TOOL_VERSION = "0.1.27"
REPORT_NAME = "BR_quartet_restoration_reflector_slot_light_unresolved_edit_block_continuity_evidence.tar.zst"
REPORT_DIR = "reflector_slot_light_unresolved_edit_block_continuity_evidence"

STAGE79_DIR = "reflector_character_slot_render_member_evidence"
STAGE79_ARCHIVE = "BR_quartet_restoration_reflector_character_slot_render_member_evidence.tar.zst"
STAGE99_DIR = "reflector_slot_light_insertion_shift_continuity_evidence"
STAGE99_ARCHIVE = "BR_quartet_restoration_reflector_slot_light_insertion_shift_continuity_evidence.tar.zst"
STAGE108_DIR = "br1_official_source_retirement_closure_evidence"
STAGE108_ARCHIVE = "BR_quartet_restoration_br1_official_source_retirement_closure_evidence.tar.zst"
STAGE109_DIR = "reflector_slot_light_sibling_section_layout_evidence"
STAGE109_ARCHIVE = "BR_quartet_restoration_reflector_slot_light_sibling_section_layout_evidence.tar.zst"
STAGE111_DIR = "reflector_slot_light_edit_normalized_layout_alignment_evidence"
STAGE111_ARCHIVE = "BR_quartet_restoration_reflector_slot_light_edit_normalized_layout_alignment_evidence.tar.zst"

EXPECTED_STAGE109_OCCURRENCES = 1814
EXPECTED_STAGE111_UNRESOLVED_PAIRS = 7
EXPECTED_STAGE111_TOTAL_ONE_EDIT_MODELS = 23
EXPECTED_STAGE111_UNRESOLVED_MODELS = 19
EXPECTED_STAGE111_CANARY_MODELS = 4
EXPECTED_PARENT_CONTAINERS = 2
EXPECTED_SCOPED_MEMBER_PAIRS = 8
EXPECTED_BLOCK_ROWS = 62
EXPECTED_MODEL_COMPARISON_ROWS = 83
PRE_RECORD_BYTES = 108
RECORD_BYTES = 44
REFERENCE_DWORD = 10
MAX_BLOCK_SPAN = 1024 * 1024

CANARY_PATH = "data/x64/effect/1002_pc02.elixir.gz"
CANARY_MEMBER_KEY = "e_pc02_w5_ringlight_01.g1e#0"
CANARY_ENDPOINT = 20276
CANARY_STAGE99_MODEL_SUFFIX = "target_insertion_piecewise_offset_shift|1"

EXPECTED_UNRESOLVED_IDENTITIES = {
    ("data/x64/effect/1000_pc00.elixir.gz", "e_pc00_swordflash_02_bullet.g1e#0"),
    ("data/x64/effect/1000_pc00.elixir.gz", "e_pc00_swordflash_02_bullet_x.g1e#0"),
    ("data/x64/effect/1002_pc02.elixir.gz", "e_pc02_h3_shoot.g1e#0"),
    ("data/x64/effect/1002_pc02.elixir.gz", "e_pc02_h4_shoot.g1e#0"),
    ("data/x64/effect/1002_pc02.elixir.gz", "e_pc02_m4_beardivision.g1e#0"),
    ("data/x64/effect/1002_pc02.elixir.gz", "e_pc02_m4_charge_00.g1e#0"),
    ("data/x64/effect/1002_pc02.elixir.gz", "e_pc02_m4_charge_01.g1e#0"),
}


class Stage112Error(RuntimeError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise Stage112Error(message)


def progress(message: str) -> None:
    print(f"[stage112] {message}", file=sys.stderr, flush=True)


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
        raise Stage112Error(f"invalid JSON {path}: {exc}") from exc
    require(isinstance(value, dict), f"JSON root must be object: {path}")
    return value


def load_module(path: Path, name: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    require(spec is not None and spec.loader is not None, f"cannot load module: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


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
    path = report_root / direct
    return path if path.is_dir() else extract_archive(report_root / archive, temporary)


def make_archive(source: Path, output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(output.name + ".tmp")
    temporary.unlink(missing_ok=True)
    completed = subprocess.run(["tar", "--zstd", "-cf", str(temporary), "-C", str(source.parent), source.name], text=True, capture_output=True)
    require(completed.returncode == 0, completed.stderr.strip())
    os.replace(temporary, output)


def validate_stage108(root: Path) -> dict[str, Any]:
    summary = load_json(root / "SUMMARY.json")
    require(summary.get("type") == "br_quartet_restoration_br1_official_source_retirement_closure_evidence_summary", "stage108 type mismatch")
    require(summary.get("tool_version") == "0.1.22", "stage108 tool version mismatch")
    require(summary.get("status") == "underscore_archive_retirement_closed", "stage108 retirement status mismatch")
    require(parse_bool(summary.get("retirement_complete")), "stage108 retirement is incomplete")
    require(parse_int(summary.get("official_archives_verified"), -1) == 4, "stage108 official archive count mismatch")
    require(parse_int(summary.get("underscore_archives_absent"), -1) == 4, "stage108 underscore archive absence mismatch")
    require(not parse_bool(summary.get("underscore_archives_required_for_normal_workflow")), "stage108 still requires underscore archives")
    return summary


def validate_stage109(root: Path) -> dict[str, Any]:
    summary = load_json(root / "SUMMARY.json")
    require(summary.get("type") == "br_quartet_restoration_reflector_slot_light_sibling_section_layout_evidence_summary", "stage109 type mismatch")
    require(summary.get("tool_version") == "0.1.23", "stage109 tool version mismatch")
    require(parse_int(summary.get("revalidated_occurrence_rows"), -1) == EXPECTED_STAGE109_OCCURRENCES, "stage109 occurrence count mismatch")
    require(parse_int(summary.get("skipped_rows"), -1) == 0, "stage109 contains skipped rows")
    require(not parse_bool(summary.get("technical_leaf_domain_semantics_resolved")), "stage109 unexpectedly resolved leaf semantics")
    return summary


def validate_stage111(root: Path) -> dict[str, Any]:
    summary = load_json(root / "SUMMARY.json")
    require(summary.get("type") == "br_quartet_restoration_reflector_slot_light_edit_normalized_layout_alignment_evidence_summary", "stage111 type mismatch")
    require(summary.get("tool_version") == "0.1.25", "stage111 tool version mismatch")
    require(parse_int(summary.get("unresolved_one_edit_pair_rows"), -1) == EXPECTED_STAGE111_UNRESOLVED_PAIRS, "stage111 unresolved pair count mismatch")
    require(parse_int(summary.get("one_edit_alignment_model_rows"), -1) == EXPECTED_STAGE111_TOTAL_ONE_EDIT_MODELS, "stage111 one-edit model count mismatch")
    require(parse_int(summary.get("independently_resolved_canary_pair_rows"), -1) == 1, "stage111 canary count mismatch")
    require(parse_int(summary.get("prototype_candidate_rows"), -1) == 0, "stage111 unexpectedly authorized prototype")
    require(not parse_bool(summary.get("technical_leaf_domain_semantics_resolved")), "stage111 unexpectedly resolved leaf semantics")
    return summary


def validate_stage99(root: Path) -> dict[str, Any]:
    summary = load_json(root / "SUMMARY.json")
    require(summary.get("type") == "br_quartet_restoration_reflector_slot_light_insertion_shift_continuity_evidence_summary", "stage99 type mismatch")
    require(summary.get("tool_version") == "0.1.13", "stage99 tool version mismatch")
    require(parse_bool(summary.get("candidate_target_occurrence_identity_resolved")), "stage99 canary identity unresolved")
    require(summary.get("winning_model_id") == "insert_first_substitute_to_second", "stage99 canary winning model mismatch")
    require(summary.get("inserted_target_occurrence") == "first_target_75", "stage99 inserted canary mismatch")
    require(summary.get("candidate_target_occurrence_identity") == "second_target_75", "stage99 continuing canary mismatch")
    require(parse_int(summary.get("skipped_rows"), -1) == 0, "stage99 contains skipped rows")
    return summary


def split_pairs(text: str) -> list[tuple[int, int]]:
    result: list[tuple[int, int]] = []
    for item in str(text).split(";"):
        item = item.strip()
        if not item:
            continue
        left, separator, right = item.partition("->")
        require(separator == "->", f"invalid ordinal pair: {item}")
        result.append((parse_int(left, -1), parse_int(right, -1)))
    return result


def split_values(text: str) -> list[str]:
    return [] if not str(text).strip() else str(text).split(";")


def u32(payload: bytes, offset: int) -> int:
    require(0 <= offset <= len(payload) - 4, f"u32 offset out of bounds: {offset}")
    return int.from_bytes(payload[offset:offset + 4], "little")


def byte_differences(left: bytes, right: bytes) -> tuple[int, int]:
    common = min(len(left), len(right))
    byte_diff = sum(a != b for a, b in zip(left[:common], right[:common])) + abs(len(left) - len(right))
    common_dwords = common // 4
    dword_diff = sum(left[index * 4:(index + 1) * 4] != right[index * 4:(index + 1) * 4] for index in range(common_dwords))
    dword_diff += (abs(len(left) - len(right)) + 3) // 4
    if common % 4 and left[common_dwords * 4:common] != right[common_dwords * 4:common]:
        dword_diff += 1
    return byte_diff, dword_diff


def normalize_block(payload: bytes, anchor: int, span: int, targets: Mapping[int, set[str]]) -> tuple[bytes, list[dict[str, Any]]]:
    block = bytearray(payload[anchor:anchor + span])
    rows: list[dict[str, Any]] = []
    for relative in range(0, span - (span % 4), 4):
        field_offset = anchor + relative
        raw = int.from_bytes(block[relative:relative + 4], "little")
        displacement = signed_i32(raw)
        if displacement == 0:
            continue
        target = field_offset + displacement
        roles = targets.get(target)
        if not roles:
            continue
        rows.append({
            "relative_dword": relative // 4,
            "field_offset": field_offset,
            "u32_hex": f"0x{raw:08x}",
            "i32": displacement,
            "field_relative_target": target,
            "target_roles": " | ".join(sorted(roles)),
        })
        block[relative:relative + 4] = b"\0\0\0\0"
    for leaf_offset in (PRE_RECORD_BYTES, PRE_RECORD_BYTES + 4):
        require(leaf_offset + 4 <= len(block), "paired leaf outside block")
        block[leaf_offset:leaf_offset + 4] = b"\0\0\0\0"
    return bytes(block), rows


def build_side_blocks(payload: bytes, rows: list[dict[str, str]], endpoint: int) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    rows = sorted(rows, key=lambda row: parse_int(row.get("template_ordinal_within_section"), -1))
    require([parse_int(row.get("template_ordinal_within_section"), -1) for row in rows] == list(range(len(rows))), "non-contiguous occurrence ordinals")
    blocks: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    for row in rows:
        ordinal = parse_int(row.get("template_ordinal_within_section"), -1)
        record_start = parse_int(row.get("record_start"), -1)
        anchor = record_start - PRE_RECORD_BYTES
        try:
            require(anchor >= 0 and anchor % 4 == 0, f"invalid anchor {anchor}")
            span = u32(payload, anchor)
            require(RECORD_BYTES + PRE_RECORD_BYTES <= span <= MAX_BLOCK_SPAN and span % 4 == 0, f"invalid block span {span}")
            block_end = anchor + span
            require(block_end <= len(payload), f"block outside payload {anchor}:{block_end}/{len(payload)}")
            reference_offset = record_start + REFERENCE_DWORD * 4
            reference_i32 = signed_i32(u32(payload, reference_offset))
            reference_target = reference_offset + reference_i32
            require(reference_target == endpoint, f"reference endpoint mismatch {reference_target} != {endpoint}")
            require(str(row.get("paired_float_value", "")) == f"{__import__('struct').unpack('<f', payload[record_start:record_start + 4])[0]:.9g}", "paired-float value mismatch")
            require(payload[record_start:record_start + 4] == payload[record_start + 4:record_start + 8], "paired leaves not bitwise equal")
            blocks.append({
                "row": row,
                "ordinal": ordinal,
                "record_start": record_start,
                "anchor": anchor,
                "span": span,
                "block_end": block_end,
                "reference_offset": reference_offset,
                "reference_i32": reference_i32,
                "reference_target": reference_target,
            })
        except Stage112Error as exc:
            skipped.append({
                "side": row.get("side", ""),
                "ordinal": ordinal,
                "record_start": record_start,
                "reason": str(exc),
            })
    require(not skipped, f"bounded block reconstruction skipped {len(skipped)} rows")

    targets: dict[int, set[str]] = defaultdict(set)
    targets[endpoint].add("section_header")
    first = rows[0]
    for relative_name in ("section_table_boundary_1", "section_table_boundary_2", "section_table_boundary_3"):
        relative = parse_int(first.get(relative_name), -1)
        if relative >= 0:
            targets[endpoint + relative].add(relative_name)
    declared_span = parse_int(first.get("section_declared_span"), -1)
    if declared_span > 0:
        targets[endpoint + declared_span].add("section_declared_end")
    for block in blocks:
        targets[block["anchor"]].add("block_anchor")
        targets[block["record_start"]].add("record_start")
        targets[block["reference_offset"]].add("reference_field")
        targets[block["block_end"]].add("block_end")

    relocation_rows: list[dict[str, Any]] = []
    for index, block in enumerate(blocks):
        raw = payload[block["anchor"]:block["block_end"]]
        normalized, refs = normalize_block(payload, block["anchor"], block["span"], targets)
        next_anchor = blocks[index + 1]["anchor"] if index + 1 < len(blocks) else -1
        block.update({
            "raw": raw,
            "normalized": normalized,
            "normalized_prefix": normalized[:PRE_RECORD_BYTES],
            "normalized_record": normalized[PRE_RECORD_BYTES:PRE_RECORD_BYTES + RECORD_BYTES],
            "normalized_trailer": normalized[PRE_RECORD_BYTES + RECORD_BYTES:],
            "next_anchor": next_anchor,
            "chain_to_next_template_anchor_exact": "" if next_anchor < 0 else block["block_end"] == next_anchor,
            "recognized_reference_count": len(refs),
            "normalized_structural_sha256": sha256(normalized),
        })
        for ref in refs:
            relocation_rows.append({"ordinal": block["ordinal"], **ref})
    return blocks, relocation_rows


def model_edit_identity(model: Mapping[str, str]) -> tuple[str, int]:
    kind = str(model.get("edit_kind", ""))
    ordinal = parse_int(model.get("edit_ordinal"), -1)
    require(kind in {"target_insertion_piecewise_offset_shift", "target_deletion_piecewise_offset_shift"}, f"unexpected edit kind: {kind}")
    require(ordinal >= 0, "edit ordinal missing")
    return kind, ordinal


def compare_model(pair_id: str, model: Mapping[str, str], source_blocks: list[dict[str, Any]], target_blocks: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    pairs = split_pairs(str(model.get("matched_ordinal_pairs", "")))
    require(len(pairs) == parse_int(model.get("matched_occurrence_rows"), -1), f"model matched-row count mismatch: {model.get('model_id')}")
    kind, edit_ordinal = model_edit_identity(model)
    comparisons: list[dict[str, Any]] = []
    for source_ordinal, target_ordinal in pairs:
        require(0 <= source_ordinal < len(source_blocks) and 0 <= target_ordinal < len(target_blocks), "model ordinal out of bounds")
        source = source_blocks[source_ordinal]
        target = target_blocks[target_ordinal]
        anchor_shift = target["anchor"] - source["anchor"]
        reference_delta = target["reference_i32"] - source["reference_i32"]
        prefix_bytes, prefix_dwords = byte_differences(source["normalized_prefix"], target["normalized_prefix"])
        record_bytes, record_dwords = byte_differences(source["normalized_record"], target["normalized_record"])
        trailer_bytes, trailer_dwords = byte_differences(source["normalized_trailer"], target["normalized_trailer"])
        full_bytes, full_dwords = byte_differences(source["normalized"], target["normalized"])
        zero_residual = full_bytes == 0 and len(source["normalized"]) == len(target["normalized"])
        comparisons.append({
            "pair_id": pair_id,
            "model_id": model.get("model_id", ""),
            "source_ordinal": source_ordinal,
            "target_ordinal": target_ordinal,
            "source_paired_float_value": source["row"].get("paired_float_value", ""),
            "target_paired_float_value": target["row"].get("paired_float_value", ""),
            "source_anchor": source["anchor"],
            "target_anchor": target["anchor"],
            "anchor_shift": anchor_shift,
            "source_block_span": source["span"],
            "target_block_span": target["span"],
            "block_span_delta": target["span"] - source["span"],
            "source_reference_i32": source["reference_i32"],
            "target_reference_i32": target["reference_i32"],
            "reference_delta": reference_delta,
            "reference_compensates_anchor_shift": reference_delta == -anchor_shift,
            "normalized_prefix_byte_differences": prefix_bytes,
            "normalized_prefix_dword_differences": prefix_dwords,
            "masked_record_byte_differences": record_bytes,
            "masked_record_dword_differences": record_dwords,
            "normalized_trailer_byte_differences": trailer_bytes,
            "normalized_trailer_dword_differences": trailer_dwords,
            "normalized_full_block_byte_differences": full_bytes,
            "normalized_full_block_dword_differences": full_dwords,
            "normalized_full_block_exact": zero_residual,
            "source_chain_to_next_template_anchor_exact": source["chain_to_next_template_anchor_exact"],
            "target_chain_to_next_template_anchor_exact": target["chain_to_next_template_anchor_exact"],
            "classification": "zero_structural_residual_matched_block" if zero_residual else "nonzero_structural_residual_matched_block",
        })

    if kind == "target_insertion_piecewise_offset_shift":
        edit_block = target_blocks[edit_ordinal]
        matched_hashes = {target_blocks[target_ordinal]["normalized_structural_sha256"] for _, target_ordinal in pairs}
        edit_side = "target"
    else:
        edit_block = source_blocks[edit_ordinal]
        matched_hashes = {source_blocks[source_ordinal]["normalized_structural_sha256"] for source_ordinal, _ in pairs}
        edit_side = "source"
    edit_distinct = edit_block["normalized_structural_sha256"] not in matched_hashes
    all_zero = bool(comparisons) and all(parse_bool(row["normalized_full_block_exact"]) for row in comparisons)
    all_reference_exact = bool(comparisons) and all(parse_bool(row["reference_compensates_anchor_shift"]) for row in comparisons)
    identity_eligible = all_zero and all_reference_exact and edit_distinct
    aggregate = {
        "pair_id": pair_id,
        "model_id": model.get("model_id", ""),
        "edit_kind": kind,
        "edit_ordinal": edit_ordinal,
        "matched_occurrence_rows": len(comparisons),
        "zero_structural_residual_pair_rows": sum(parse_bool(row["normalized_full_block_exact"]) for row in comparisons),
        "reference_compensation_exact_rows": sum(parse_bool(row["reference_compensates_anchor_shift"]) for row in comparisons),
        "exact_prefix_rows": sum(parse_int(row["normalized_prefix_byte_differences"], -1) == 0 for row in comparisons),
        "exact_masked_record_rows": sum(parse_int(row["masked_record_byte_differences"], -1) == 0 for row in comparisons),
        "exact_trailer_rows": sum(parse_int(row["normalized_trailer_byte_differences"], -1) == 0 for row in comparisons),
        "total_structural_residual_bytes": sum(parse_int(row["normalized_full_block_byte_differences"], 0) for row in comparisons),
        "total_structural_residual_dwords": sum(parse_int(row["normalized_full_block_dword_differences"], 0) for row in comparisons),
        "maximum_structural_residual_dwords": max((parse_int(row["normalized_full_block_dword_differences"], 0) for row in comparisons), default=0),
        "edit_side": edit_side,
        "edit_block_ordinal": edit_ordinal,
        "edit_block_span": edit_block["span"],
        "edit_block_normalized_structural_sha256": edit_block["normalized_structural_sha256"],
        "edit_block_distinct_from_all_matched_blocks": edit_distinct,
        "all_matched_blocks_zero_structural_residual": all_zero,
        "all_reference_deltas_compensate_anchor_shift": all_reference_exact,
        "identity_eligible_exact_structural_model": identity_eligible,
        "classification": "identity_eligible_exact_structural_model" if identity_eligible else "non_authorizing_structural_model",
    }
    return comparisons, aggregate


def build_report(
    project_root: Path,
    *,
    create_archive: bool = True,
    report_root: Path | None = None,
    workspace_root: Path | None = None,
    rules_file: Path | None = None,
    maximum_earc_bytes: int = 512 * 1024 * 1024,
    container_loader: Callable[..., tuple[list[dict[str, Any]], list[dict[str, Any]]]] | None = None,
    scope_rows_override: Sequence[Mapping[str, Any]] | None = None,
) -> tuple[Path, Path | None, dict[str, Any]]:
    project_root = project_root.resolve()
    reports = (report_root or project_root / ".local/reports/quartet_restoration").resolve()
    workspace = (workspace_root or project_root / ".local/build/quartet_restoration").resolve()
    require(reports.is_dir(), f"missing report root: {reports}")

    stage81 = load_module(project_root / "workstreams/quartet_restoration/collect_reflector_ringlight_control_callsite_evidence.py", "stage81_for_stage112")
    stage86 = load_module(project_root / "workstreams/quartet_restoration/collect_reflector_slot_light_shared_record_template_evidence.py", "stage86_for_stage112")

    with tempfile.TemporaryDirectory(prefix="br-stage112-") as temporary_name:
        temporary = Path(temporary_name)
        stage108_root = locate(reports, STAGE108_DIR, STAGE108_ARCHIVE, temporary / "108")
        stage109_root = locate(reports, STAGE109_DIR, STAGE109_ARCHIVE, temporary / "109")
        stage111_root = locate(reports, STAGE111_DIR, STAGE111_ARCHIVE, temporary / "111")
        stage99_root = locate(reports, STAGE99_DIR, STAGE99_ARCHIVE, temporary / "99")
        validate_stage108(stage108_root)
        validate_stage109(stage109_root)
        validate_stage111(stage111_root)
        validate_stage99(stage99_root)

        occurrence_rows = read_tsv(stage109_root / "SLOT_LIGHT_SIBLING_SECTION_LAYOUT_OCCURRENCES.tsv")
        decision_rows = read_tsv(stage111_root / "SLOT_LIGHT_EDIT_NORMALIZED_SECTION_PAIR_DECISIONS.tsv")
        model_rows = read_tsv(stage111_root / "SLOT_LIGHT_EDIT_NORMALIZED_ALIGNMENT_MODELS.tsv")
        require(len(occurrence_rows) == EXPECTED_STAGE109_OCCURRENCES, "stage109 occurrence table length mismatch")

        unresolved = [row for row in decision_rows if row.get("classification") == "unresolved_multiple_one_edit_models"]
        require(len(unresolved) == EXPECTED_STAGE111_UNRESOLVED_PAIRS, "stage111 unresolved decision table mismatch")
        unresolved_identities = {(row.get("normalized_path", "").casefold(), row.get("member_key", "").casefold()) for row in unresolved}
        require(unresolved_identities == EXPECTED_UNRESOLVED_IDENTITIES, "stage111 unresolved member identity set drifted")
        unresolved_pair_ids = {row.get("pair_id", "") for row in unresolved}
        unresolved_models = [row for row in model_rows if row.get("pair_id", "") in unresolved_pair_ids]
        expected_unresolved_models = sum(parse_int(row.get("alignment_model_rows"), -1) for row in unresolved)
        require(expected_unresolved_models == EXPECTED_STAGE111_UNRESOLVED_MODELS, "stage111 unresolved decision model-count partition mismatch")
        require(len(unresolved_models) == expected_unresolved_models, "stage111 unresolved model table mismatch")

        canary_decisions = [row for row in decision_rows if row.get("member_key", "").casefold() == CANARY_MEMBER_KEY and row.get("normalized_path", "").casefold() == CANARY_PATH]
        require(len(canary_decisions) == 1, "stage111 canary decision missing")
        canary_pair_id = canary_decisions[0].get("pair_id", "")
        canary_models = [row for row in model_rows if row.get("pair_id", "") == canary_pair_id]
        expected_canary_models = parse_int(canary_decisions[0].get("alignment_model_rows"), -1)
        require(expected_canary_models == EXPECTED_STAGE111_CANARY_MODELS, "stage111 canary decision model-count partition mismatch")
        require(len(canary_models) == expected_canary_models, "stage111 canary model count mismatch")
        require(len(unresolved_models) + len(canary_models) == EXPECTED_STAGE111_TOTAL_ONE_EDIT_MODELS, "stage111 total one-edit model partition mismatch")
        stage99_selected_model = next((row.get("model_id", "") for row in canary_models if parse_bool(row.get("selected_for_resolved_transitions"))), "")
        require(stage99_selected_model.endswith(CANARY_STAGE99_MODEL_SUFFIX), "stage111 selected canary model mismatch")

        required_identities = set(unresolved_identities)
        required_identities.add((CANARY_PATH, CANARY_MEMBER_KEY))
        required_paths = {path for path, _ in required_identities}

        if scope_rows_override is None:
            stage79_root = locate(reports, STAGE79_DIR, STAGE79_ARCHIVE, temporary / "79")
            stage81.validate_stage79(stage79_root)
            parent_scope = [row for row in stage81.select_parent_scope(stage79_root) if str(row.get("normalized_path", "")).casefold() in required_paths]
        else:
            parent_scope = [dict(row) for row in scope_rows_override]
        require(parent_scope, "bounded parent scope is empty")
        actual_rules = rules_file or project_root / "titles/blue_reflection/modules/quartet_restoration/mappings/effect_material_rules.tsv"
        loader = container_loader or stage81.load_parent_containers
        progress("rehydrating the two bounded parent effect containers")
        containers, loader_skipped = loader(
            scope_rows=parent_scope,
            workspace_root=workspace,
            report_root=reports,
            rules_file=actual_rules,
            maximum_earc_bytes=maximum_earc_bytes,
        )
        require(not loader_skipped, f"parent container loader skipped {len(loader_skipped)} rows")
        require(len(containers) == EXPECTED_PARENT_CONTAINERS, f"expected {EXPECTED_PARENT_CONTAINERS} parent containers, found {len(containers)}")
        pair_by_key, _all_pairs = stage86.index_pairs(containers)
        scoped_pairs = {identity: pair_by_key.get(identity) for identity in required_identities}
        require(all(pair is not None for pair in scoped_pairs.values()), "one or more bounded member pairs are missing")
        require(len(scoped_pairs) == EXPECTED_SCOPED_MEMBER_PAIRS, "bounded member pair count mismatch")

        occurrences_by_section: dict[tuple[str, str, str, int], list[dict[str, str]]] = defaultdict(list)
        for row in occurrence_rows:
            identity = (row.get("normalized_path", "").casefold(), row.get("member_key", "").casefold())
            if identity not in required_identities:
                continue
            key = (identity[0], identity[1], row.get("side", "").casefold(), parse_int(row.get("normalized_endpoint"), -1))
            occurrences_by_section[key].append(row)

        block_inventory_rows: list[dict[str, Any]] = []
        structural_field_rows: list[dict[str, Any]] = []
        model_comparison_rows: list[dict[str, Any]] = []
        model_continuity_rows: list[dict[str, Any]] = []
        pair_decision_rows: list[dict[str, Any]] = []
        skipped_rows: list[dict[str, Any]] = []
        block_cache: dict[tuple[str, str, int], tuple[list[dict[str, Any]], list[dict[str, Any]]]] = {}

        all_decisions = unresolved + canary_decisions
        models_by_pair: dict[str, list[dict[str, str]]] = defaultdict(list)
        for row in unresolved_models + canary_models:
            models_by_pair[row.get("pair_id", "")].append(row)

        progress(f"auditing {len(all_decisions)} section pairs and {len(unresolved_models) + len(canary_models)} edit models")
        for decision in all_decisions:
            pair_id = decision.get("pair_id", "")
            path = decision.get("normalized_path", "").casefold()
            member_key = decision.get("member_key", "").casefold()
            source_endpoint = parse_int(decision.get("source_endpoint"), -1)
            target_endpoint = parse_int(decision.get("target_endpoint"), -1)
            require(source_endpoint >= 0 and target_endpoint >= 0, f"invalid pair endpoints: {pair_id}")
            pair = scoped_pairs[(path, member_key)]
            assert pair is not None
            source_rows = occurrences_by_section.get((path, member_key, "source", source_endpoint), [])
            target_rows = occurrences_by_section.get((path, member_key, "target", target_endpoint), [])
            require(split_values(decision.get("source_values", "")) == [row.get("paired_float_value", "") for row in sorted(source_rows, key=lambda item: parse_int(item.get("template_ordinal_within_section"), -1))], f"source sequence mismatch: {pair_id}")
            require(split_values(decision.get("target_values", "")) == [row.get("paired_float_value", "") for row in sorted(target_rows, key=lambda item: parse_int(item.get("template_ordinal_within_section"), -1))], f"target sequence mismatch: {pair_id}")

            source_blocks, source_refs = build_side_blocks(bytes(pair["source_payload"]), source_rows, source_endpoint)
            target_blocks, target_refs = build_side_blocks(bytes(pair["target_payload"]), target_rows, target_endpoint)
            block_cache[(pair_id, "source", source_endpoint)] = (source_blocks, source_refs)
            block_cache[(pair_id, "target", target_endpoint)] = (target_blocks, target_refs)

            for side, blocks, refs in (("source", source_blocks, source_refs), ("target", target_blocks, target_refs)):
                for block in blocks:
                    block_inventory_rows.append({
                        "pair_id": pair_id,
                        "normalized_path": path,
                        "member_key": member_key,
                        "member_name": decision.get("member_name", ""),
                        "side": side,
                        "endpoint": source_endpoint if side == "source" else target_endpoint,
                        "ordinal": block["ordinal"],
                        "paired_float_value": block["row"].get("paired_float_value", ""),
                        "record_start": block["record_start"],
                        "anchor": block["anchor"],
                        "declared_block_span": block["span"],
                        "block_end": block["block_end"],
                        "next_template_anchor": "" if block["next_anchor"] < 0 else block["next_anchor"],
                        "chain_to_next_template_anchor_exact": block["chain_to_next_template_anchor_exact"],
                        "reference_offset": block["reference_offset"],
                        "reference_i32": block["reference_i32"],
                        "reference_target": block["reference_target"],
                        "recognized_reference_count": block["recognized_reference_count"],
                        "raw_block_sha256": sha256(block["raw"]),
                        "normalized_structural_sha256": block["normalized_structural_sha256"],
                        "classification": "bounded_canary_occurrence_block" if member_key == CANARY_MEMBER_KEY else "bounded_unresolved_edit_occurrence_block",
                    })
                for ref in refs:
                    structural_field_rows.append({
                        "pair_id": pair_id,
                        "normalized_path": path,
                        "member_key": member_key,
                        "member_name": decision.get("member_name", ""),
                        "side": side,
                        **ref,
                    })

            continuity: list[dict[str, Any]] = []
            comparisons_for_pair: list[dict[str, Any]] = []
            for model in models_by_pair[pair_id]:
                comparisons, aggregate = compare_model(pair_id, model, source_blocks, target_blocks)
                comparisons_for_pair.extend(comparisons)
                continuity.append(aggregate)
            model_comparison_rows.extend(comparisons_for_pair)
            model_continuity_rows.extend(continuity)
            eligible = [row for row in continuity if parse_bool(row.get("identity_eligible_exact_structural_model"))]
            is_canary = member_key == CANARY_MEMBER_KEY and path == CANARY_PATH
            if is_canary:
                eligible_ids = {row.get("model_id", "") for row in eligible}
                require(not eligible_ids or stage99_selected_model in eligible_ids, "stage112 structural gate contradicts stage99 canary")
                selected_model = stage99_selected_model
                basis = "stage99_immutable_canary_decision"
                classification = "canary_identity_preserved"
            elif len(eligible) == 1:
                selected_model = eligible[0].get("model_id", "")
                basis = "unique_all_matched_blocks_zero_structural_residual_and_edit_block_distinct"
                classification = "occurrence_identity_resolved_by_exact_block_continuity"
            else:
                selected_model = ""
                basis = ""
                classification = "occurrence_identity_unresolved_no_unique_exact_block_model"
            pair_decision_rows.append({
                "pair_id": pair_id,
                "normalized_path": path,
                "member_key": member_key,
                "member_name": decision.get("member_name", ""),
                "source_values": decision.get("source_values", ""),
                "target_values": decision.get("target_values", ""),
                "model_rows": len(continuity),
                "identity_eligible_model_rows": len(eligible),
                "selected_model_id": selected_model,
                "selection_basis": basis,
                "classification": classification,
            })

        require(len(block_inventory_rows) == EXPECTED_BLOCK_ROWS, f"bounded block row count mismatch: {len(block_inventory_rows)}")
        require(len(model_comparison_rows) == EXPECTED_MODEL_COMPARISON_ROWS, f"model comparison row count mismatch: {len(model_comparison_rows)}")
        require(len(model_continuity_rows) == EXPECTED_STAGE111_TOTAL_ONE_EDIT_MODELS, "model continuity row count mismatch")
        require(not skipped_rows, "stage112 produced skipped rows")

        noncanary_decisions = [row for row in pair_decision_rows if row.get("member_key") != CANARY_MEMBER_KEY]
        resolved = [row for row in noncanary_decisions if row.get("classification") == "occurrence_identity_resolved_by_exact_block_continuity"]
        unresolved_after = [row for row in noncanary_decisions if row.get("classification") == "occurrence_identity_unresolved_no_unique_exact_block_model"]
        summary = {
            "type": "br_quartet_restoration_reflector_slot_light_unresolved_edit_block_continuity_evidence_summary",
            "format_version": 1,
            "tool_version": TOOL_VERSION,
            "status": "bounded_block_trailer_continuity_audited_semantics_unresolved_no_render_write",
            "input_unresolved_one_edit_pair_rows": len(unresolved),
            "input_unresolved_one_edit_model_rows": len(unresolved_models),
            "canary_model_rows": len(canary_models),
            "rehydrated_parent_container_rows": len(containers),
            "rehydrated_scoped_member_pair_rows": len(scoped_pairs),
            "bounded_occurrence_block_rows": len(block_inventory_rows),
            "recognized_structural_reference_rows": len(structural_field_rows),
            "model_pair_comparison_rows": len(model_comparison_rows),
            "model_continuity_rows": len(model_continuity_rows),
            "newly_resolved_noncanary_pair_rows": len(resolved),
            "still_unresolved_noncanary_pair_rows": len(unresolved_after),
            "canary_pair_rows": 1,
            "canary_identity_preserved": True,
            "prototype_candidate_rows": 0,
            "technical_leaf_domain_semantics_resolved": False,
            "brightness_semantics_confirmed": False,
            "intensity_semantics_confirmed": False,
            "censorship_semantics_confirmed": False,
            "skipped_rows": len(skipped_rows),
            "policy": {
                "official_nonunderscore_archives_are_canonical": True,
                "underscore_archives_required": False,
                "paired_float_values_masked_before_identity_decision": True,
                "distance_or_numeric_closeness_used_for_identity": False,
                "stage99_canary_is_immutable": True,
                "ambiguous_models_used_for_value_inference": False,
                "G1E_G1EM_write_authorized": False,
                "pak_repack_authorized": False,
                "profile_or_registry_write_authorized": False,
                "installed_game_modified": False,
            },
            "next_action": "Upload this report. Continue only from exact block/trailer continuity decisions: preserve any uniquely resolved occurrence identities, keep all remaining pairs unresolved, and do not infer brightness/intensity/censorship or write G1E/G1EM.",
        }

        output_dir = reports / REPORT_DIR
        if output_dir.exists():
            shutil = __import__("shutil")
            shutil.rmtree(output_dir)
        output_dir.mkdir(parents=True)
        write_tsv(output_dir / "SLOT_LIGHT_UNRESOLVED_EDIT_OCCURRENCE_BLOCKS.tsv", [
            "pair_id", "normalized_path", "member_key", "member_name", "side", "endpoint", "ordinal", "paired_float_value",
            "record_start", "anchor", "declared_block_span", "block_end", "next_template_anchor", "chain_to_next_template_anchor_exact",
            "reference_offset", "reference_i32", "reference_target", "recognized_reference_count", "raw_block_sha256", "normalized_structural_sha256", "classification",
        ], block_inventory_rows)
        write_tsv(output_dir / "SLOT_LIGHT_UNRESOLVED_EDIT_STRUCTURAL_FIELDS.tsv", [
            "pair_id", "normalized_path", "member_key", "member_name", "side", "ordinal", "relative_dword", "field_offset", "u32_hex", "i32", "field_relative_target", "target_roles",
        ], structural_field_rows)
        write_tsv(output_dir / "SLOT_LIGHT_UNRESOLVED_EDIT_MODEL_PAIR_COMPARISONS.tsv", [
            "pair_id", "model_id", "source_ordinal", "target_ordinal", "source_paired_float_value", "target_paired_float_value",
            "source_anchor", "target_anchor", "anchor_shift", "source_block_span", "target_block_span", "block_span_delta",
            "source_reference_i32", "target_reference_i32", "reference_delta", "reference_compensates_anchor_shift",
            "normalized_prefix_byte_differences", "normalized_prefix_dword_differences", "masked_record_byte_differences", "masked_record_dword_differences",
            "normalized_trailer_byte_differences", "normalized_trailer_dword_differences", "normalized_full_block_byte_differences", "normalized_full_block_dword_differences",
            "normalized_full_block_exact", "source_chain_to_next_template_anchor_exact", "target_chain_to_next_template_anchor_exact", "classification",
        ], model_comparison_rows)
        write_tsv(output_dir / "SLOT_LIGHT_UNRESOLVED_EDIT_MODEL_CONTINUITY.tsv", [
            "pair_id", "model_id", "edit_kind", "edit_ordinal", "matched_occurrence_rows", "zero_structural_residual_pair_rows",
            "reference_compensation_exact_rows", "exact_prefix_rows", "exact_masked_record_rows", "exact_trailer_rows",
            "total_structural_residual_bytes", "total_structural_residual_dwords", "maximum_structural_residual_dwords",
            "edit_side", "edit_block_ordinal", "edit_block_span", "edit_block_normalized_structural_sha256",
            "edit_block_distinct_from_all_matched_blocks", "all_matched_blocks_zero_structural_residual",
            "all_reference_deltas_compensate_anchor_shift", "identity_eligible_exact_structural_model", "classification",
        ], model_continuity_rows)
        write_tsv(output_dir / "SLOT_LIGHT_UNRESOLVED_EDIT_PAIR_DECISIONS.tsv", [
            "pair_id", "normalized_path", "member_key", "member_name", "source_values", "target_values", "model_rows",
            "identity_eligible_model_rows", "selected_model_id", "selection_basis", "classification",
        ], pair_decision_rows)
        write_tsv(output_dir / "SLOT_LIGHT_UNRESOLVED_EDIT_CANARY_CHECK.tsv", ["question", "answer", "classification"], [
            {"question": "stage99 canary selected model", "answer": stage99_selected_model, "classification": "immutable_canary_input"},
            {"question": "stage112 canary contradiction detected", "answer": False, "classification": "canary_preserved"},
            {"question": "paired-float values used to select identity", "answer": False, "classification": "value_independent_identity_gate"},
        ])
        write_tsv(output_dir / "SLOT_LIGHT_UNRESOLVED_EDIT_BLOCK_CONTINUITY_SKIPPED.tsv", ["scope", "identity", "reason"], skipped_rows)
        (output_dir / "SUMMARY.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

        archive_path: Path | None = None
        if create_archive:
            archive_path = reports / REPORT_NAME
            make_archive(output_dir, archive_path)
        return output_dir, archive_path, summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path, default=PROJECT_ROOT_DEFAULT)
    parser.add_argument("--report-root", type=Path)
    parser.add_argument("--workspace-root", type=Path)
    parser.add_argument("--rules-file", type=Path)
    parser.add_argument("--maximum-earc-bytes", type=int, default=512 * 1024 * 1024)
    parser.add_argument("--no-archive", action="store_true")
    args = parser.parse_args()
    try:
        output, archive, summary = build_report(
            args.project_root,
            create_archive=not args.no_archive,
            report_root=args.report_root,
            workspace_root=args.workspace_root,
            rules_file=args.rules_file,
            maximum_earc_bytes=args.maximum_earc_bytes,
        )
    except Stage112Error as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print(f"Report directory: {output}")
    if archive:
        print(f"Archive: {archive}")
    print(f"Input unresolved pairs: {summary['input_unresolved_one_edit_pair_rows']}")
    print(f"Newly resolved pairs: {summary['newly_resolved_noncanary_pair_rows']}")
    print(f"Still unresolved pairs: {summary['still_unresolved_noncanary_pair_rows']}")
    print("G1E/G1EM write: blocked")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
