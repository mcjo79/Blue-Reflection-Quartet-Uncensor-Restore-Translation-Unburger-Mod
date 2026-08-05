#!/usr/bin/env python3
"""Audit recurrent trailer transitions for the seven unresolved one-edit pairs.

Stage 112 reconstructed full bounded occurrence blocks for seven ambiguous edit
pairs plus the immutable PC02 ringlight canary.  Paired-float leaves, recognized
field-relative references, prefixes and masked records were already controlled;
all seven non-canary pairs remained unresolved because nonzero structural
residuals persisted in their trailers.

This stage rehydrates the same two bounded parent effect containers and adds a
strict reference corpus: the 58 zero-edit section pairs already resolved by
stage 111 inside those containers.  Exact normalized dword transitions are
counted by relative dword and source/target block span.  A transition is eligible
for recurrence masking only when it occurs in at least two independent resolved
section pairs and at least two distinct members.  Ambiguous pairs never
contribute evidence to their own mask.

A non-canary model may resolve only when, after masking those independently
recurrent exact transitions, it is the sole model with no unsupported structural
residual, all reference deltas compensate anchor shifts, and the inserted or
deleted block remains structurally distinct.  Numeric closeness, paired-float
values and one-off transitions never choose identity.  The stage-99/112 canary
is immutable and any contradiction fails closed.

The collector is read-only.  It never writes G1E/G1EM, Elixir, PAK, profile,
registry or installed-game payloads and never infers brightness, intensity or
censorship semantics.
"""
from __future__ import annotations

import argparse
import csv
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
TOOL_VERSION = "0.1.28"
REPORT_NAME = "BR_quartet_restoration_reflector_slot_light_trailer_residual_recurrence_evidence.tar.zst"
REPORT_DIR = "reflector_slot_light_trailer_residual_recurrence_evidence"

STAGE79_DIR = "reflector_character_slot_render_member_evidence"
STAGE79_ARCHIVE = "BR_quartet_restoration_reflector_character_slot_render_member_evidence.tar.zst"
STAGE108_DIR = "br1_official_source_retirement_closure_evidence"
STAGE108_ARCHIVE = "BR_quartet_restoration_br1_official_source_retirement_closure_evidence.tar.zst"
STAGE109_DIR = "reflector_slot_light_sibling_section_layout_evidence"
STAGE109_ARCHIVE = "BR_quartet_restoration_reflector_slot_light_sibling_section_layout_evidence.tar.zst"
STAGE111_DIR = "reflector_slot_light_edit_normalized_layout_alignment_evidence"
STAGE111_ARCHIVE = "BR_quartet_restoration_reflector_slot_light_edit_normalized_layout_alignment_evidence.tar.zst"
STAGE112_DIR = "reflector_slot_light_unresolved_edit_block_continuity_evidence"
STAGE112_ARCHIVE = "BR_quartet_restoration_reflector_slot_light_unresolved_edit_block_continuity_evidence.tar.zst"

EXPECTED_STAGE109_OCCURRENCES = 1814
EXPECTED_STAGE111_ZERO_EDIT_PAIRS = 185
EXPECTED_REFERENCE_ZERO_EDIT_PAIRS = 58
EXPECTED_UNRESOLVED_PAIRS = 7
EXPECTED_UNRESOLVED_MODELS = 19
EXPECTED_CANARY_MODELS = 4
EXPECTED_PARENT_CONTAINERS = 2
EXPECTED_TOTAL_SCOPED_DECISIONS = 66
EXPECTED_TOTAL_SCOPED_MEMBER_PAIRS = 64
MIN_SUPPORT_PAIR_ROWS = 2
MIN_SUPPORT_MEMBER_ROWS = 2

SCOPED_PATHS = {
    "data/x64/effect/1000_pc00.elixir.gz",
    "data/x64/effect/1002_pc02.elixir.gz",
}
CANARY_PATH = "data/x64/effect/1002_pc02.elixir.gz"
CANARY_MEMBER_KEY = "e_pc02_w5_ringlight_01.g1e#0"


class Stage113Error(RuntimeError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise Stage113Error(message)


def progress(message: str) -> None:
    print(f"[stage113] {message}", file=sys.stderr, flush=True)


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
        raise Stage113Error(f"invalid JSON {path}: {exc}") from exc
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


def validate_inputs(stage108_root: Path, stage109_root: Path, stage111_root: Path, stage112_root: Path) -> None:
    stage108 = load_json(stage108_root / "SUMMARY.json")
    require(stage108.get("type") == "br_quartet_restoration_br1_official_source_retirement_closure_evidence_summary", "stage108 type mismatch")
    require(stage108.get("tool_version") == "0.1.22", "stage108 tool version mismatch")
    require(stage108.get("status") == "underscore_archive_retirement_closed", "stage108 retirement status mismatch")
    require(parse_bool(stage108.get("retirement_complete")), "stage108 retirement incomplete")
    require(not parse_bool(stage108.get("underscore_archives_required_for_normal_workflow")), "stage108 still requires underscore archives")

    stage109 = load_json(stage109_root / "SUMMARY.json")
    require(stage109.get("type") == "br_quartet_restoration_reflector_slot_light_sibling_section_layout_evidence_summary", "stage109 type mismatch")
    require(stage109.get("tool_version") == "0.1.23", "stage109 tool version mismatch")
    require(parse_int(stage109.get("revalidated_occurrence_rows"), -1) == EXPECTED_STAGE109_OCCURRENCES, "stage109 occurrence count mismatch")
    require(parse_int(stage109.get("skipped_rows"), -1) == 0, "stage109 contains skipped rows")

    stage111 = load_json(stage111_root / "SUMMARY.json")
    require(stage111.get("type") == "br_quartet_restoration_reflector_slot_light_edit_normalized_layout_alignment_evidence_summary", "stage111 type mismatch")
    require(stage111.get("tool_version") == "0.1.25", "stage111 tool version mismatch")
    require(parse_int(stage111.get("zero_edit_resolved_pair_rows"), -1) == EXPECTED_STAGE111_ZERO_EDIT_PAIRS, "stage111 zero-edit pair count mismatch")
    require(parse_int(stage111.get("unresolved_one_edit_pair_rows"), -1) == EXPECTED_UNRESOLVED_PAIRS, "stage111 unresolved pair count mismatch")
    require(parse_int(stage111.get("one_edit_alignment_model_rows"), -1) == EXPECTED_UNRESOLVED_MODELS + EXPECTED_CANARY_MODELS, "stage111 one-edit model count mismatch")
    require(parse_int(stage111.get("independently_resolved_canary_pair_rows"), -1) == 1, "stage111 canary count mismatch")
    require(parse_int(stage111.get("prototype_candidate_rows"), -1) == 0, "stage111 unexpectedly contains prototypes")

    stage112 = load_json(stage112_root / "SUMMARY.json")
    require(stage112.get("type") == "br_quartet_restoration_reflector_slot_light_unresolved_edit_block_continuity_evidence_summary", "stage112 type mismatch")
    require(stage112.get("tool_version") == "0.1.27", "stage112 tool version mismatch")
    require(parse_int(stage112.get("input_unresolved_one_edit_pair_rows"), -1) == EXPECTED_UNRESOLVED_PAIRS, "stage112 unresolved pair count mismatch")
    require(parse_int(stage112.get("input_unresolved_one_edit_model_rows"), -1) == EXPECTED_UNRESOLVED_MODELS, "stage112 unresolved model count mismatch")
    require(parse_int(stage112.get("canary_model_rows"), -1) == EXPECTED_CANARY_MODELS, "stage112 canary model count mismatch")
    require(parse_int(stage112.get("newly_resolved_noncanary_pair_rows"), -1) == 0, "stage112 unexpectedly resolved a non-canary pair")
    require(parse_int(stage112.get("still_unresolved_noncanary_pair_rows"), -1) == EXPECTED_UNRESOLVED_PAIRS, "stage112 unresolved result count mismatch")
    require(parse_bool(stage112.get("canary_identity_preserved")), "stage112 did not preserve canary identity")
    require(parse_int(stage112.get("skipped_rows"), -1) == 0, "stage112 contains skipped rows")


def segment_for(relative_dword: int, pre_record_bytes: int, record_bytes: int) -> str:
    offset = relative_dword * 4
    if offset < pre_record_bytes:
        return "prefix"
    if offset < pre_record_bytes + record_bytes:
        return "record"
    return "trailer"


def residual_dword_rows(
    *,
    pair_id: str,
    model_id: str,
    member_key: str,
    source_ordinal: int,
    target_ordinal: int,
    source_block: Mapping[str, Any],
    target_block: Mapping[str, Any],
    pre_record_bytes: int,
    record_bytes: int,
    corpus_role: str,
) -> list[dict[str, Any]]:
    source = bytes(source_block["normalized"])
    target = bytes(target_block["normalized"])
    common_dwords = min(len(source), len(target)) // 4
    rows: list[dict[str, Any]] = []
    for relative_dword in range(common_dwords):
        start = relative_dword * 4
        left = source[start:start + 4]
        right = target[start:start + 4]
        if left == right:
            continue
        source_u32 = int.from_bytes(left, "little")
        target_u32 = int.from_bytes(right, "little")
        rows.append({
            "pair_id": pair_id,
            "model_id": model_id,
            "member_key": member_key,
            "source_ordinal": source_ordinal,
            "target_ordinal": target_ordinal,
            "source_block_span": len(source),
            "target_block_span": len(target),
            "relative_dword": relative_dword,
            "segment": segment_for(relative_dword, pre_record_bytes, record_bytes),
            "source_u32_hex": f"0x{source_u32:08x}",
            "target_u32_hex": f"0x{target_u32:08x}",
            "source_i32": signed_i32(source_u32),
            "target_i32": signed_i32(target_u32),
            "signed_delta": signed_i32(target_u32) - signed_i32(source_u32),
            "byte_differences": sum(a != b for a, b in zip(left, right)),
            "length_mismatch": False,
            "corpus_role": corpus_role,
        })
    if len(source) != len(target):
        rows.append({
            "pair_id": pair_id,
            "model_id": model_id,
            "member_key": member_key,
            "source_ordinal": source_ordinal,
            "target_ordinal": target_ordinal,
            "source_block_span": len(source),
            "target_block_span": len(target),
            "relative_dword": common_dwords,
            "segment": "length_mismatch",
            "source_u32_hex": "",
            "target_u32_hex": "",
            "source_i32": "",
            "target_i32": "",
            "signed_delta": "",
            "byte_differences": abs(len(source) - len(target)),
            "length_mismatch": True,
            "corpus_role": corpus_role,
        })
    return rows


def recurrence_key(row: Mapping[str, Any]) -> tuple[Any, ...] | None:
    if parse_bool(row.get("length_mismatch")):
        return None
    return (
        parse_int(row.get("source_block_span"), -1),
        parse_int(row.get("target_block_span"), -1),
        parse_int(row.get("relative_dword"), -1),
        str(row.get("source_u32_hex", "")),
        str(row.get("target_u32_hex", "")),
    )


def build_recurrence_classes(reference_rows: Sequence[Mapping[str, Any]]) -> tuple[list[dict[str, Any]], dict[tuple[Any, ...], dict[str, Any]]]:
    grouped: dict[tuple[Any, ...], list[Mapping[str, Any]]] = defaultdict(list)
    for row in reference_rows:
        key = recurrence_key(row)
        if key is not None:
            grouped[key].append(row)
    classes: list[dict[str, Any]] = []
    lookup: dict[tuple[Any, ...], dict[str, Any]] = {}
    for key, rows in sorted(grouped.items(), key=lambda item: item[0]):
        pairs = {str(row.get("pair_id", "")) for row in rows}
        members = {str(row.get("member_key", "")) for row in rows}
        segment = str(rows[0].get("segment", ""))
        eligible = segment == "trailer" and len(pairs) >= MIN_SUPPORT_PAIR_ROWS and len(members) >= MIN_SUPPORT_MEMBER_ROWS
        out = {
            "source_block_span": key[0],
            "target_block_span": key[1],
            "relative_dword": key[2],
            "segment": segment,
            "source_u32_hex": key[3],
            "target_u32_hex": key[4],
            "signed_delta": rows[0].get("signed_delta", ""),
            "occurrence_rows": len(rows),
            "section_pair_rows": len(pairs),
            "member_rows": len(members),
            "recurrence_mask_eligible": eligible,
            "classification": "independent_cross_member_exact_trailer_transition" if eligible else "insufficient_or_nontrailer_reference_transition",
        }
        classes.append(out)
        lookup[key] = out
    return classes, lookup


def annotate_candidate_rows(candidate_rows: Sequence[Mapping[str, Any]], lookup: Mapping[tuple[Any, ...], Mapping[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for source in candidate_rows:
        row = dict(source)
        key = recurrence_key(row)
        support = lookup.get(key) if key is not None else None
        eligible = bool(support and parse_bool(support.get("recurrence_mask_eligible")))
        row.update({
            "reference_occurrence_rows": 0 if support is None else support.get("occurrence_rows", 0),
            "reference_section_pair_rows": 0 if support is None else support.get("section_pair_rows", 0),
            "reference_member_rows": 0 if support is None else support.get("member_rows", 0),
            "recurrence_mask_applied": eligible,
            "classification": "masked_by_independent_exact_trailer_recurrence" if eligible else "unsupported_structural_residual",
        })
        result.append(row)
    return result


def aggregate_model(
    model: Mapping[str, Any],
    rows: Sequence[Mapping[str, Any]],
    stage112_continuity: Mapping[str, Any],
) -> dict[str, Any]:
    supported = [row for row in rows if parse_bool(row.get("recurrence_mask_applied"))]
    unsupported = [row for row in rows if not parse_bool(row.get("recurrence_mask_applied"))]
    exact_after_mask = len(unsupported) == 0
    references_exact = parse_bool(stage112_continuity.get("all_reference_deltas_compensate_anchor_shift"))
    edit_distinct = parse_bool(stage112_continuity.get("edit_block_distinct_from_all_matched_blocks"))
    eligible = exact_after_mask and references_exact and edit_distinct
    return {
        "pair_id": model.get("pair_id", ""),
        "model_id": model.get("model_id", ""),
        "edit_kind": model.get("edit_kind", ""),
        "edit_ordinal": model.get("edit_ordinal", ""),
        "matched_occurrence_rows": model.get("matched_occurrence_rows", ""),
        "raw_residual_dword_rows": len(rows),
        "recurrent_masked_dword_rows": len(supported),
        "unsupported_residual_dword_rows": len(unsupported),
        "raw_residual_byte_differences": sum(parse_int(row.get("byte_differences"), 0) for row in rows),
        "recurrent_masked_byte_differences": sum(parse_int(row.get("byte_differences"), 0) for row in supported),
        "unsupported_residual_byte_differences": sum(parse_int(row.get("byte_differences"), 0) for row in unsupported),
        "all_reference_deltas_compensate_anchor_shift": references_exact,
        "edit_block_distinct_from_all_matched_blocks": edit_distinct,
        "all_unsupported_residuals_removed": exact_after_mask,
        "identity_eligible_after_recurrence_mask": eligible,
        "classification": "identity_eligible_after_independent_recurrence_mask" if eligible else "non_authorizing_recurrence_normalized_model",
    }


def decide_pair(pair_id: str, member_key: str, models: Sequence[Mapping[str, Any]], immutable_canary_model: str = "") -> dict[str, Any]:
    eligible = [row for row in models if parse_bool(row.get("identity_eligible_after_recurrence_mask"))]
    if member_key == CANARY_MEMBER_KEY:
        eligible_ids = {str(row.get("model_id", "")) for row in eligible}
        require(not eligible_ids or immutable_canary_model in eligible_ids, "stage113 recurrence mask contradicts immutable canary")
        return {
            "pair_id": pair_id,
            "member_key": member_key,
            "model_rows": len(models),
            "identity_eligible_model_rows": len(eligible),
            "selected_model_id": immutable_canary_model,
            "selection_basis": "stage99_and_stage112_immutable_canary_decision",
            "classification": "canary_identity_preserved",
        }
    if len(eligible) == 1:
        return {
            "pair_id": pair_id,
            "member_key": member_key,
            "model_rows": len(models),
            "identity_eligible_model_rows": 1,
            "selected_model_id": eligible[0].get("model_id", ""),
            "selection_basis": "unique_zero_unsupported_residual_after_independent_cross_member_exact_trailer_mask",
            "classification": "occurrence_identity_resolved_by_recurrent_trailer_transition_mask",
        }
    return {
        "pair_id": pair_id,
        "member_key": member_key,
        "model_rows": len(models),
        "identity_eligible_model_rows": len(eligible),
        "selected_model_id": "",
        "selection_basis": "",
        "classification": "occurrence_identity_unresolved_after_recurrence_mask",
    }


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

    stage81 = load_module(project_root / "workstreams/quartet_restoration/collect_reflector_ringlight_control_callsite_evidence.py", "stage81_for_stage113")
    stage86 = load_module(project_root / "workstreams/quartet_restoration/collect_reflector_slot_light_shared_record_template_evidence.py", "stage86_for_stage113")
    stage112_module = load_module(project_root / "workstreams/quartet_restoration/collect_reflector_slot_light_unresolved_edit_block_continuity_evidence.py", "stage112_for_stage113")

    with tempfile.TemporaryDirectory(prefix="br-stage113-") as temporary_name:
        temporary = Path(temporary_name)
        stage108_root = locate(reports, STAGE108_DIR, STAGE108_ARCHIVE, temporary / "108")
        stage109_root = locate(reports, STAGE109_DIR, STAGE109_ARCHIVE, temporary / "109")
        stage111_root = locate(reports, STAGE111_DIR, STAGE111_ARCHIVE, temporary / "111")
        stage112_root = locate(reports, STAGE112_DIR, STAGE112_ARCHIVE, temporary / "112")
        validate_inputs(stage108_root, stage109_root, stage111_root, stage112_root)

        occurrence_rows = read_tsv(stage109_root / "SLOT_LIGHT_SIBLING_SECTION_LAYOUT_OCCURRENCES.tsv")
        decision_rows = read_tsv(stage111_root / "SLOT_LIGHT_EDIT_NORMALIZED_SECTION_PAIR_DECISIONS.tsv")
        model_rows = read_tsv(stage111_root / "SLOT_LIGHT_EDIT_NORMALIZED_ALIGNMENT_MODELS.tsv")
        stage112_continuity_rows = read_tsv(stage112_root / "SLOT_LIGHT_UNRESOLVED_EDIT_MODEL_CONTINUITY.tsv")
        stage112_decisions = read_tsv(stage112_root / "SLOT_LIGHT_UNRESOLVED_EDIT_PAIR_DECISIONS.tsv")
        require(len(occurrence_rows) == EXPECTED_STAGE109_OCCURRENCES, "stage109 occurrence table length mismatch")

        scoped_decisions = [row for row in decision_rows if row.get("normalized_path", "").casefold() in SCOPED_PATHS]
        reference_decisions = [row for row in scoped_decisions if row.get("classification") == "resolved_zero_edit_normalized_pair"]
        unresolved_decisions = [row for row in scoped_decisions if row.get("classification") == "unresolved_multiple_one_edit_models"]
        canary_decisions = [row for row in scoped_decisions if row.get("classification") == "resolved_one_edit_canary_pair"]
        require(len(reference_decisions) == EXPECTED_REFERENCE_ZERO_EDIT_PAIRS, f"resolved reference pair count mismatch: {len(reference_decisions)}")
        require(len(unresolved_decisions) == EXPECTED_UNRESOLVED_PAIRS, "unresolved pair count mismatch")
        require(len(canary_decisions) == 1, "canary pair count mismatch")
        require(len(scoped_decisions) == EXPECTED_TOTAL_SCOPED_DECISIONS, f"scoped decision count mismatch: {len(scoped_decisions)}")

        selected_models = [row for row in model_rows if parse_bool(row.get("selected_for_resolved_transitions"))]
        selected_by_pair = {row.get("pair_id", ""): row for row in selected_models}
        require(all(row.get("pair_id", "") in selected_by_pair for row in reference_decisions + canary_decisions), "one or more resolved decisions lack a selected model")

        unresolved_pair_ids = {row.get("pair_id", "") for row in unresolved_decisions}
        canary_pair_id = canary_decisions[0].get("pair_id", "")
        ambiguous_models = [row for row in model_rows if row.get("pair_id", "") in unresolved_pair_ids]
        canary_models = [row for row in model_rows if row.get("pair_id", "") == canary_pair_id]
        require(len(ambiguous_models) == EXPECTED_UNRESOLVED_MODELS, "unresolved model table mismatch")
        require(len(canary_models) == EXPECTED_CANARY_MODELS, "canary model table mismatch")
        immutable_canary_model = selected_by_pair[canary_pair_id].get("model_id", "")
        require(bool(immutable_canary_model), "selected canary model missing")

        stage112_by_model = {row.get("model_id", ""): row for row in stage112_continuity_rows}
        require(set(stage112_by_model) == {row.get("model_id", "") for row in ambiguous_models + canary_models}, "stage112 model continuity identity mismatch")
        stage112_decision_by_pair = {row.get("pair_id", ""): row for row in stage112_decisions}
        require(all(stage112_decision_by_pair.get(row.get("pair_id", ""), {}).get("classification") == "occurrence_identity_unresolved_no_unique_exact_block_model" for row in unresolved_decisions), "stage112 unresolved decision drift")
        require(stage112_decision_by_pair.get(canary_pair_id, {}).get("classification") == "canary_identity_preserved", "stage112 canary decision drift")

        required_identities = {(row.get("normalized_path", "").casefold(), row.get("member_key", "").casefold()) for row in scoped_decisions}
        if scope_rows_override is None:
            stage79_root = locate(reports, STAGE79_DIR, STAGE79_ARCHIVE, temporary / "79")
            stage81.validate_stage79(stage79_root)
            parent_scope = [row for row in stage81.select_parent_scope(stage79_root) if str(row.get("normalized_path", "")).casefold() in SCOPED_PATHS]
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
        require(all(pair is not None for pair in scoped_pairs.values()), "one or more scoped member pairs are missing")
        require(len(scoped_pairs) == EXPECTED_TOTAL_SCOPED_MEMBER_PAIRS, f"scoped member pair count mismatch: {len(scoped_pairs)}")

        occurrences_by_section: dict[tuple[str, str, str, int], list[dict[str, str]]] = defaultdict(list)
        for row in occurrence_rows:
            identity = (row.get("normalized_path", "").casefold(), row.get("member_key", "").casefold())
            if identity not in required_identities:
                continue
            key = (identity[0], identity[1], row.get("side", "").casefold(), parse_int(row.get("normalized_endpoint"), -1))
            occurrences_by_section[key].append(row)

        decision_by_pair = {row.get("pair_id", ""): row for row in scoped_decisions}
        models_by_pair: dict[str, list[dict[str, str]]] = defaultdict(list)
        for row in model_rows:
            if row.get("pair_id", "") in decision_by_pair:
                models_by_pair[row.get("pair_id", "")].append(row)

        block_cache: dict[tuple[str, str], list[dict[str, Any]]] = {}
        progress(f"reconstructing blocks for {len(scoped_decisions)} scoped section pairs")
        for decision in scoped_decisions:
            pair_id = decision.get("pair_id", "")
            path = decision.get("normalized_path", "").casefold()
            member_key = decision.get("member_key", "").casefold()
            pair = scoped_pairs[(path, member_key)]
            assert pair is not None
            source_endpoint = parse_int(decision.get("source_endpoint"), -1)
            target_endpoint = parse_int(decision.get("target_endpoint"), -1)
            source_rows = occurrences_by_section.get((path, member_key, "source", source_endpoint), [])
            target_rows = occurrences_by_section.get((path, member_key, "target", target_endpoint), [])
            require(source_rows and target_rows, f"missing occurrence rows: {pair_id}")
            try:
                source_blocks, _source_refs = stage112_module.build_side_blocks(bytes(pair["source_payload"]), source_rows, source_endpoint)
                target_blocks, _target_refs = stage112_module.build_side_blocks(bytes(pair["target_payload"]), target_rows, target_endpoint)
            except Exception as exc:  # imported collector raises its own class
                raise Stage113Error(f"block reconstruction failed for {pair_id}: {exc}") from exc
            block_cache[(pair_id, "source")] = source_blocks
            block_cache[(pair_id, "target")] = target_blocks

        reference_rows: list[dict[str, Any]] = []
        progress(f"building exact transition reference corpus from {len(reference_decisions)} resolved zero-edit pairs")
        for decision in reference_decisions:
            pair_id = decision.get("pair_id", "")
            model = selected_by_pair[pair_id]
            require(model.get("edit_kind") == "zero_edit_uniform_offset_shift", f"reference pair is not zero-edit: {pair_id}")
            source_blocks = block_cache[(pair_id, "source")]
            target_blocks = block_cache[(pair_id, "target")]
            for source_ordinal, target_ordinal in stage112_module.split_pairs(model.get("matched_ordinal_pairs", "")):
                reference_rows.extend(residual_dword_rows(
                    pair_id=pair_id,
                    model_id=model.get("model_id", ""),
                    member_key=decision.get("member_key", ""),
                    source_ordinal=source_ordinal,
                    target_ordinal=target_ordinal,
                    source_block=source_blocks[source_ordinal],
                    target_block=target_blocks[target_ordinal],
                    pre_record_bytes=stage112_module.PRE_RECORD_BYTES,
                    record_bytes=stage112_module.RECORD_BYTES,
                    corpus_role="resolved_zero_edit_reference",
                ))
        recurrence_classes, recurrence_lookup = build_recurrence_classes(reference_rows)
        eligible_classes = [row for row in recurrence_classes if parse_bool(row.get("recurrence_mask_eligible"))]

        candidate_residual_rows: list[dict[str, Any]] = []
        normalized_model_rows: list[dict[str, Any]] = []
        pair_decision_rows: list[dict[str, Any]] = []
        all_candidate_models = ambiguous_models + canary_models
        progress(f"auditing {len(all_candidate_models)} unresolved/canary models against {len(eligible_classes)} recurrent classes")
        for model in all_candidate_models:
            pair_id = model.get("pair_id", "")
            decision = decision_by_pair[pair_id]
            source_blocks = block_cache[(pair_id, "source")]
            target_blocks = block_cache[(pair_id, "target")]
            model_rows: list[dict[str, Any]] = []
            for source_ordinal, target_ordinal in stage112_module.split_pairs(model.get("matched_ordinal_pairs", "")):
                model_rows.extend(residual_dword_rows(
                    pair_id=pair_id,
                    model_id=model.get("model_id", ""),
                    member_key=decision.get("member_key", ""),
                    source_ordinal=source_ordinal,
                    target_ordinal=target_ordinal,
                    source_block=source_blocks[source_ordinal],
                    target_block=target_blocks[target_ordinal],
                    pre_record_bytes=stage112_module.PRE_RECORD_BYTES,
                    record_bytes=stage112_module.RECORD_BYTES,
                    corpus_role="ambiguous_or_canary_model",
                ))
            annotated = annotate_candidate_rows(model_rows, recurrence_lookup)
            candidate_residual_rows.extend(annotated)
            normalized_model_rows.append(aggregate_model(model, annotated, stage112_by_model[model.get("model_id", "")]))

        normalized_by_pair: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for row in normalized_model_rows:
            normalized_by_pair[row.get("pair_id", "")].append(row)
        for decision in unresolved_decisions + canary_decisions:
            pair_id = decision.get("pair_id", "")
            pair_decision_rows.append({
                **decide_pair(pair_id, decision.get("member_key", "").casefold(), normalized_by_pair[pair_id], immutable_canary_model),
                "normalized_path": decision.get("normalized_path", ""),
                "member_name": decision.get("member_name", ""),
                "source_values": decision.get("source_values", ""),
                "target_values": decision.get("target_values", ""),
            })

        noncanary_decisions = [row for row in pair_decision_rows if row.get("member_key") != CANARY_MEMBER_KEY]
        resolved = [row for row in noncanary_decisions if row.get("classification") == "occurrence_identity_resolved_by_recurrent_trailer_transition_mask"]
        unresolved = [row for row in noncanary_decisions if row.get("classification") == "occurrence_identity_unresolved_after_recurrence_mask"]
        require(len(resolved) + len(unresolved) == EXPECTED_UNRESOLVED_PAIRS, "stage113 pair decision partition mismatch")

        summary = {
            "type": "br_quartet_restoration_reflector_slot_light_trailer_residual_recurrence_evidence_summary",
            "format_version": 1,
            "tool_version": TOOL_VERSION,
            "status": "cross_member_exact_trailer_recurrence_audited_semantics_unresolved_no_render_write",
            "resolved_zero_edit_reference_pair_rows": len(reference_decisions),
            "resolved_reference_residual_dword_rows": len(reference_rows),
            "resolved_reference_transition_class_rows": len(recurrence_classes),
            "recurrence_mask_eligible_transition_class_rows": len(eligible_classes),
            "input_unresolved_pair_rows": len(unresolved_decisions),
            "input_unresolved_model_rows": len(ambiguous_models),
            "canary_model_rows": len(canary_models),
            "candidate_model_residual_dword_rows": len(candidate_residual_rows),
            "recurrent_masked_candidate_dword_rows": sum(parse_bool(row.get("recurrence_mask_applied")) for row in candidate_residual_rows),
            "unsupported_candidate_dword_rows": sum(not parse_bool(row.get("recurrence_mask_applied")) for row in candidate_residual_rows),
            "newly_resolved_noncanary_pair_rows": len(resolved),
            "still_unresolved_noncanary_pair_rows": len(unresolved),
            "canary_identity_preserved": True,
            "prototype_candidate_rows": 0,
            "technical_leaf_domain_semantics_resolved": False,
            "brightness_semantics_confirmed": False,
            "intensity_semantics_confirmed": False,
            "censorship_semantics_confirmed": False,
            "skipped_rows": 0,
            "policy": {
                "official_nonunderscore_archives_are_canonical": True,
                "underscore_archives_required": False,
                "ambiguous_pairs_contribute_to_reference_mask": False,
                "minimum_independent_reference_pairs": MIN_SUPPORT_PAIR_ROWS,
                "minimum_independent_reference_members": MIN_SUPPORT_MEMBER_ROWS,
                "only_exact_trailer_transitions_are_maskable": True,
                "paired_float_values_used_for_identity": False,
                "distance_or_numeric_closeness_used_for_identity": False,
                "stage99_and_stage112_canary_is_immutable": True,
                "G1E_G1EM_write_authorized": False,
                "pak_repack_authorized": False,
                "profile_or_registry_write_authorized": False,
                "installed_game_modified": False,
            },
            "next_action": "Upload this report. Preserve only uniquely recurrence-normalized identities; every remaining pair stays unresolved and excluded from value inference. Do not infer brightness/intensity/censorship or write G1E/G1EM.",
        }

        output_dir = reports / REPORT_DIR
        if output_dir.exists():
            __import__("shutil").rmtree(output_dir)
        output_dir.mkdir(parents=True)
        write_tsv(output_dir / "SLOT_LIGHT_RESOLVED_TRAILER_TRANSITION_REFERENCE.tsv", [
            "pair_id", "model_id", "member_key", "source_ordinal", "target_ordinal", "source_block_span", "target_block_span",
            "relative_dword", "segment", "source_u32_hex", "target_u32_hex", "source_i32", "target_i32", "signed_delta",
            "byte_differences", "length_mismatch", "corpus_role",
        ], reference_rows)
        write_tsv(output_dir / "SLOT_LIGHT_RECURRENT_TRAILER_TRANSITION_CLASSES.tsv", [
            "source_block_span", "target_block_span", "relative_dword", "segment", "source_u32_hex", "target_u32_hex", "signed_delta",
            "occurrence_rows", "section_pair_rows", "member_rows", "recurrence_mask_eligible", "classification",
        ], recurrence_classes)
        write_tsv(output_dir / "SLOT_LIGHT_UNRESOLVED_MODEL_RESIDUAL_TRANSITIONS.tsv", [
            "pair_id", "model_id", "member_key", "source_ordinal", "target_ordinal", "source_block_span", "target_block_span",
            "relative_dword", "segment", "source_u32_hex", "target_u32_hex", "source_i32", "target_i32", "signed_delta",
            "byte_differences", "length_mismatch", "reference_occurrence_rows", "reference_section_pair_rows", "reference_member_rows",
            "recurrence_mask_applied", "classification",
        ], candidate_residual_rows)
        write_tsv(output_dir / "SLOT_LIGHT_UNRESOLVED_MODEL_RECURRENCE_NORMALIZATION.tsv", [
            "pair_id", "model_id", "edit_kind", "edit_ordinal", "matched_occurrence_rows", "raw_residual_dword_rows",
            "recurrent_masked_dword_rows", "unsupported_residual_dword_rows", "raw_residual_byte_differences",
            "recurrent_masked_byte_differences", "unsupported_residual_byte_differences",
            "all_reference_deltas_compensate_anchor_shift", "edit_block_distinct_from_all_matched_blocks",
            "all_unsupported_residuals_removed", "identity_eligible_after_recurrence_mask", "classification",
        ], normalized_model_rows)
        write_tsv(output_dir / "SLOT_LIGHT_UNRESOLVED_PAIR_RECURRENCE_DECISIONS.tsv", [
            "pair_id", "normalized_path", "member_key", "member_name", "source_values", "target_values", "model_rows",
            "identity_eligible_model_rows", "selected_model_id", "selection_basis", "classification",
        ], pair_decision_rows)
        write_tsv(output_dir / "SLOT_LIGHT_TRAILER_RESIDUAL_RECURRENCE_CANARY_CHECK.tsv", ["question", "answer", "classification"], [
            {"question": "immutable canary selected model", "answer": immutable_canary_model, "classification": "stage99_and_stage112_input"},
            {"question": "stage113 canary contradiction detected", "answer": False, "classification": "canary_preserved"},
            {"question": "ambiguous pairs contributed to recurrence reference", "answer": False, "classification": "independent_reference_only"},
            {"question": "paired-float values used to select identity", "answer": False, "classification": "value_independent_identity_gate"},
        ])
        write_tsv(output_dir / "SLOT_LIGHT_TRAILER_RESIDUAL_RECURRENCE_SKIPPED.tsv", ["scope", "identity", "reason"], [])
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
    except Stage113Error as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print(f"Report directory: {output}")
    if archive:
        print(f"Archive: {archive}")
    print(f"Reference pairs: {summary['resolved_zero_edit_reference_pair_rows']}")
    print(f"Recurrent transition classes: {summary['recurrence_mask_eligible_transition_class_rows']}")
    print(f"Newly resolved pairs: {summary['newly_resolved_noncanary_pair_rows']}")
    print(f"Still unresolved pairs: {summary['still_unresolved_noncanary_pair_rows']}")
    print("G1E/G1EM write: blocked")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
