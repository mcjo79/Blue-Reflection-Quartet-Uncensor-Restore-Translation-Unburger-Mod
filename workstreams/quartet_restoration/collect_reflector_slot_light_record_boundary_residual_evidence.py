#!/usr/bin/env python3
"""Audit stage-87 residual dwords as relocation-compensated G1E fields.

The two adaptive islands share two adjacent 150 -> 75 transitions but each has
one different residual dword.  This read-only stage tests signed/unsigned offset
models, validates endpoint bounds and local context, searches the stage-84
aligned corpus for the same relocation-compensation equation, and relates the
fields to known alignment segments and exact-match runs.  It exports metadata
and hashes only and never writes a G1E, Elixir, PAK, registry or installed game.
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
from collections import Counter
from pathlib import Path, PurePosixPath
from typing import Any, Callable, Iterable, Mapping, Sequence

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT_DEFAULT = SCRIPT_DIR.parent.parent

TOOL_VERSION = "0.1.2"
REPORT_NAME = "BR_quartet_restoration_reflector_slot_light_record_boundary_residual_evidence.tar.zst"
REPORT_DIR = "reflector_slot_light_record_boundary_residual_evidence"
STAGE87_DIR = "reflector_slot_light_local_change_island_evidence"
STAGE87_ARCHIVE = "BR_quartet_restoration_reflector_slot_light_local_change_island_evidence.tar.zst"
STAGE84_DIR = "reflector_slot_light_g1e_structure_evidence"
STAGE84_ARCHIVE = "BR_quartet_restoration_reflector_slot_light_g1e_structure_evidence.tar.zst"
STAGE79_DIR = "reflector_character_slot_render_member_evidence"
STAGE79_ARCHIVE = "BR_quartet_restoration_reflector_character_slot_render_member_evidence.tar.zst"
EXPECTED_ISLAND_ROWS = 2
EXPECTED_RESIDUAL_ROWS = 2
EXPECTED_SHARED_ROWS = 2
EXPECTED_PARENT_CONTAINERS = 4
ENDPOINT_CONTEXT_RADIUS = 16


class Stage88Error(RuntimeError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise Stage88Error(message)


def progress(message: str) -> None:
    print(f"[stage88] {message}", file=sys.stderr, flush=True)


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


def read_tsv(path: Path, required: bool = True) -> list[dict[str, str]]:
    if not path.is_file():
        if required:
            raise Stage88Error(f"missing required TSV: {path}")
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
        raise Stage88Error(f"invalid JSON {path}: {exc}") from exc
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


def stable_key(path: str, member_key: str) -> tuple[str, str]:
    return path.casefold(), member_key.casefold()


def validate_stage87(root: Path) -> dict[str, Any]:
    summary = load_json(root / "SUMMARY.json")
    require(summary.get("type") == "br_quartet_restoration_reflector_slot_light_local_change_island_evidence_summary", "stage87 type mismatch")
    require(summary.get("tool_version") == "0.1.1", "stage87 tool version mismatch")
    require(summary.get("status") == "PC02_ringlight_and_neutral_control_adaptive_change_islands_compared_brightness_semantics_unresolved", "stage87 status mismatch")
    require(parse_int(summary.get("adaptive_change_island_rows"), -1) == EXPECTED_ISLAND_ROWS, "stage87 island count mismatch")
    require(parse_int(summary.get("shared_exact_transition_rows"), -1) == EXPECTED_SHARED_ROWS, "stage87 shared transition count mismatch")
    require(parse_int(summary.get("candidate_only_transition_rows"), -1) == 1, "stage87 candidate residual count mismatch")
    require(parse_int(summary.get("neutral_only_transition_rows"), -1) == 1, "stage87 neutral residual count mismatch")
    require(parse_int(summary.get("exact_adaptive_island_profile_rows"), -1) == 0, "stage87 unexpectedly has an exact full-island match")
    require(parse_int(summary.get("prototype_candidate_rows"), -1) == 0, "stage87 unexpectedly authorized a prototype")
    require(not parse_bool(summary.get("brightness_semantics_confirmed")), "stage87 unexpectedly confirmed brightness")
    require(parse_int(summary.get("skipped_rows"), -1) == 0, "stage87 contains skipped rows")
    return summary


def validate_stage84(root: Path) -> dict[str, Any]:
    summary = load_json(root / "SUMMARY.json")
    require(summary.get("type") == "br_quartet_restoration_reflector_slot_light_g1e_structure_evidence_summary", "stage84 type mismatch")
    require(summary.get("tool_version") == "0.0.98", "stage84 tool version mismatch")
    require(parse_int(summary.get("scope_member_rows"), -1) == 6, "stage84 scope count mismatch")
    require(parse_int(summary.get("aligned_changed_dword_rows"), -1) == 634, "stage84 aligned dword count mismatch")
    require(parse_int(summary.get("skipped_rows"), -1) == 0, "stage84 contains skipped rows")
    return summary


def model_endpoints(
    *, source_offset: int, target_offset: int, source_value: int, target_value: int,
    island_source_start: int, island_target_start: int,
    island_source_end: int, island_target_end: int,
) -> list[dict[str, Any]]:
    source_signed = signed_i32(source_value)
    target_signed = signed_i32(target_value)
    models = [
        ("dword_start_relative", source_offset, target_offset),
        ("dword_end_relative", source_offset + 4, target_offset + 4),
        ("island_start_relative", island_source_start, island_target_start),
        ("island_end_relative", island_source_end, island_target_end),
        ("member_start_signed_absolute", 0, 0),
    ]
    rows: list[dict[str, Any]] = []
    for name, source_base, target_base in models:
        source_endpoint = source_base + source_signed
        target_endpoint = target_base + target_signed
        rows.append({
            "model": name,
            "source_base": source_base,
            "target_base": target_base,
            "source_endpoint": source_endpoint,
            "target_endpoint": target_endpoint,
            "endpoint_equal": source_endpoint == target_endpoint,
        })
    rows.append({
        "model": "member_start_unsigned_absolute",
        "source_base": 0,
        "target_base": 0,
        "source_endpoint": source_value & 0xFFFFFFFF,
        "target_endpoint": target_value & 0xFFFFFFFF,
        "endpoint_equal": (source_value & 0xFFFFFFFF) == (target_value & 0xFFFFFFFF),
    })
    return rows


def compensation_holds(source_offset: int, target_offset: int, source_value: int, target_value: int) -> bool:
    shift = target_offset - source_offset
    return signed_i32(target_value) - signed_i32(source_value) == -shift


def context_hash(payload: bytes, endpoint: int, radius: int = ENDPOINT_CONTEXT_RADIUS) -> tuple[int, int, str]:
    start = max(0, endpoint - radius)
    end = min(len(payload), endpoint + radius)
    return start, end, sha256(payload[start:end])


def nearest_run(rows: Sequence[Mapping[str, Any]], offset: int, *, before: bool) -> Mapping[str, Any] | None:
    candidates = []
    for row in rows:
        start = parse_int(row.get("source_start"), -1)
        length = parse_int(row.get("length"), 0)
        end = start + length
        if before and end <= offset:
            candidates.append((end, row))
        elif not before and start >= offset + 4:
            candidates.append((start, row))
    if not candidates:
        return None
    return (max(candidates, key=lambda pair: pair[0]) if before else min(candidates, key=lambda pair: pair[0]))[1]


def containing_segment(rows: Sequence[Mapping[str, Any]], offset: int) -> Mapping[str, Any] | None:
    matches = [row for row in rows if parse_int(row.get("source_start"), -1) <= offset < parse_int(row.get("source_end_exclusive"), -1)]
    return matches[0] if len(matches) == 1 else None


def build_report(
    project_root: Path,
    *,
    create_archive: bool = True,
    workspace_root: Path | None = None,
    report_root: Path | None = None,
    rules_file: Path | None = None,
    maximum_earc_bytes: int = 512 * 1024 * 1024,
    container_loader: Callable[..., tuple[list[dict[str, Any]], list[dict[str, Any]]]] | None = None,
) -> tuple[Path, Path | None, dict[str, Any]]:
    project_root = project_root.resolve()
    reports = (report_root or project_root / ".local/reports/quartet_restoration").resolve()
    workspace = (workspace_root or project_root / ".local/build/quartet_restoration").resolve()
    require(reports.is_dir(), f"missing report root: {reports}")

    stage81 = load_module(project_root / "workstreams/quartet_restoration/collect_reflector_ringlight_control_callsite_evidence.py", "stage81_for_stage88")
    stage87 = load_module(project_root / "workstreams/quartet_restoration/collect_reflector_slot_light_local_change_island_evidence.py", "stage87_for_stage88")

    progress("validating stage 79, 84 and 87 reports")
    with tempfile.TemporaryDirectory(prefix="br-stage88-") as temporary_name:
        temporary = Path(temporary_name)
        stage87_root = locate(reports, STAGE87_DIR, STAGE87_ARCHIVE, temporary / "87")
        stage84_root = locate(reports, STAGE84_DIR, STAGE84_ARCHIVE, temporary / "84")
        stage79_root = locate(reports, STAGE79_DIR, STAGE79_ARCHIVE, temporary / "79")
        summary87 = validate_stage87(stage87_root)
        summary84 = validate_stage84(stage84_root)
        summary79 = stage81.validate_stage79(stage79_root)

        island_rows = read_tsv(stage87_root / "SLOT_LIGHT_LOCAL_CHANGE_ISLANDS.tsv")
        transition_rows = read_tsv(stage87_root / "SLOT_LIGHT_LOCAL_CHANGE_ISLAND_TRANSITIONS.tsv")
        require(len(island_rows) == EXPECTED_ISLAND_ROWS, "stage87 island table count mismatch")
        shared_rows = [row for row in transition_rows if row.get("cross_island_relation") == "shared_exact_transition"]
        residual_rows = [row for row in transition_rows if row.get("cross_island_relation") in {"candidate_only_transition", "neutral_only_transition"}]
        require(len(shared_rows) == EXPECTED_SHARED_ROWS * 2, "stage87 transition table must contain two shared rows per island")
        require(len(residual_rows) == EXPECTED_RESIDUAL_ROWS, "stage87 residual table count mismatch")
        require({parse_int(row.get("relative_dword"), -1) for row in residual_rows} == {10}, "stage87 residuals are not at relative dword 10")

        parent_scope = stage81.select_parent_scope(stage79_root)
        actual_rules = rules_file or project_root / "titles/blue_reflection/modules/quartet_restoration/mappings/effect_material_rules.tsv"
        loader = container_loader or stage81.load_parent_containers
        progress("rehydrating the four bounded parent effect containers")
        containers, skipped = loader(
            scope_rows=parent_scope,
            workspace_root=workspace,
            report_root=reports,
            rules_file=actual_rules,
            maximum_earc_bytes=maximum_earc_bytes,
        )
        require(not skipped, f"parent container loader skipped {len(skipped)} rows")
        require(len(containers) == EXPECTED_PARENT_CONTAINERS, f"expected {EXPECTED_PARENT_CONTAINERS} parent containers, found {len(containers)}")
        pairs = stage87.index_pairs(containers)
        progress(f"indexed {len(pairs)} G1E/G1EM payload pairs")

        island_by_role = {row["island_role"]: row for row in island_rows}
        require(set(island_by_role) == {"candidate_ringlight", "neutral_control"}, "stage87 island roles mismatch")

        audit_rows: list[dict[str, Any]] = []
        model_rows: list[dict[str, Any]] = []
        endpoint_rows: list[dict[str, Any]] = []
        boundary_rows: list[dict[str, Any]] = []

        segments = read_tsv(stage84_root / "SLOT_LIGHT_ALIGNMENT_SEGMENTS.tsv")
        runs = read_tsv(stage84_root / "SLOT_LIGHT_EXACT_MATCH_RUNS.tsv")
        member_audit = read_tsv(stage84_root / "SLOT_LIGHT_MEMBER_STRUCTURE_AUDIT.tsv")
        dword_rows84 = read_tsv(stage84_root / "SLOT_LIGHT_ALIGNED_CHANGED_DWORDS.tsv")
        member_sizes = {
            stable_key(row.get("normalized_path", ""), row.get("member_key", "")): (parse_int(row.get("source_size"), -1), parse_int(row.get("target_size"), -1))
            for row in member_audit
        }

        for residual in residual_rows:
            role = str(residual.get("island_role", ""))
            island = island_by_role.get(role)
            require(island is not None, f"missing island row for {role}")
            key = stable_key(str(residual.get("normalized_path", "")), str(residual.get("member_key", "")))
            pair = pairs.get(key)
            require(pair is not None, f"missing rehydrated residual pair: {key}")
            source_payload = pair["source_payload"]
            target_payload = pair["target_payload"]
            source_offset = parse_int(residual.get("source_offset"), -1)
            target_offset = parse_int(residual.get("target_offset"), -1)
            source_value = parse_int(residual.get("source_u32_hex"), -1)
            target_value = parse_int(residual.get("target_u32_hex"), -1)
            require(stage87.dword(source_payload, source_offset) == source_value, f"stage87 source residual mismatch for {role}")
            require(stage87.dword(target_payload, target_offset) == target_value, f"stage87 target residual mismatch for {role}")
            shift = target_offset - source_offset
            source_signed = signed_i32(source_value)
            target_signed = signed_i32(target_value)
            compensated = compensation_holds(source_offset, target_offset, source_value, target_value)

            models = model_endpoints(
                source_offset=source_offset, target_offset=target_offset,
                source_value=source_value, target_value=target_value,
                island_source_start=parse_int(island.get("source_start"), -1),
                island_target_start=parse_int(island.get("target_start"), -1),
                island_source_end=parse_int(island.get("source_end_exclusive"), -1),
                island_target_end=parse_int(island.get("target_end_exclusive"), -1),
            )
            plausible = []
            for model in models:
                source_endpoint = int(model["source_endpoint"])
                target_endpoint = int(model["target_endpoint"])
                source_in_bounds = 0 <= source_endpoint < len(source_payload)
                target_in_bounds = 0 <= target_endpoint < len(target_payload)
                aligned = source_endpoint % 4 == 0 and target_endpoint % 4 == 0
                status = "exact_in_bounds_aligned" if model["endpoint_equal"] and source_in_bounds and target_in_bounds and aligned else "rejected_or_ambiguous"
                if status == "exact_in_bounds_aligned":
                    plausible.append(model["model"])
                model_rows.append({
                    "island_role": role,
                    "member_name": pair["member_name"],
                    "model": model["model"],
                    "source_base": model["source_base"],
                    "target_base": model["target_base"],
                    "source_signed_value": source_signed,
                    "target_signed_value": target_signed,
                    "source_endpoint": source_endpoint,
                    "target_endpoint": target_endpoint,
                    "endpoint_equal": model["endpoint_equal"],
                    "source_endpoint_in_bounds": source_in_bounds,
                    "target_endpoint_in_bounds": target_in_bounds,
                    "endpoint_dword_aligned": aligned,
                    "model_status": status,
                })
                if model["endpoint_equal"] and source_in_bounds and target_in_bounds:
                    ss, se, sh = context_hash(source_payload, source_endpoint)
                    ts, te, th = context_hash(target_payload, target_endpoint)
                    endpoint_rows.append({
                        "island_role": role,
                        "member_name": pair["member_name"],
                        "model": model["model"],
                        "endpoint": source_endpoint,
                        "source_context_start": ss,
                        "source_context_end_exclusive": se,
                        "target_context_start": ts,
                        "target_context_end_exclusive": te,
                        "source_context_sha256": sh,
                        "target_context_sha256": th,
                        "source_target_context_equal": sh == th and (se - ss) == (te - ts),
                    })

            relevant_segments = [row for row in segments if stable_key(row.get("normalized_path", ""), row.get("member_key", "")) == key]
            relevant_runs = [row for row in runs if stable_key(row.get("normalized_path", ""), row.get("member_key", "")) == key]
            segment = containing_segment(relevant_segments, source_offset)
            before = nearest_run(relevant_runs, source_offset, before=True)
            after = nearest_run(relevant_runs, source_offset, before=False)
            boundary_rows.append({
                "island_role": role,
                "member_name": pair["member_name"],
                "island_source_start": island.get("source_start", ""),
                "island_source_end_exclusive": island.get("source_end_exclusive", ""),
                "residual_source_offset": source_offset,
                "residual_relative_dword": residual.get("relative_dword", ""),
                "stage84_segment_id": segment.get("segment_id", "") if segment else "",
                "stage84_segment_type": segment.get("segment_type", "") if segment else "not_in_stage84_six_member_scope",
                "stage84_segment_source_start": segment.get("source_start", "") if segment else "",
                "stage84_segment_source_end_exclusive": segment.get("source_end_exclusive", "") if segment else "",
                "nearest_exact_run_before_source_start": before.get("source_start", "") if before else "",
                "nearest_exact_run_before_length": before.get("length", "") if before else "",
                "nearest_exact_run_after_source_start": after.get("source_start", "") if after else "",
                "nearest_exact_run_after_length": after.get("length", "") if after else "",
                "record_boundary_status": "bounded_11_dword_island_offset_origin_unresolved",
            })
            audit_rows.append({
                "island_role": role,
                "normalized_path": pair["normalized_path"],
                "member_key": pair["member_key"],
                "member_name": pair["member_name"],
                "source_offset": source_offset,
                "target_offset": target_offset,
                "local_shift_bytes": shift,
                "source_u32_hex": f"0x{source_value:08x}",
                "target_u32_hex": f"0x{target_value:08x}",
                "source_i32": source_signed,
                "target_i32": target_signed,
                "signed_delta": target_signed - source_signed,
                "expected_compensation_delta": -shift,
                "relocation_compensation_exact": compensated,
                "plausible_exact_model_count": len(plausible),
                "plausible_exact_models": ",".join(plausible),
                "classification": "relocation_compensated_signed_field_origin_unresolved" if compensated else "not_relocation_compensated",
            })

        progress("searching stage84 aligned dwords for relocation-compensation recurrence")
        recurrence_rows: list[dict[str, Any]] = []
        for row in dword_rows84:
            source_offset = parse_int(row.get("source_offset"), -1)
            target_offset = parse_int(row.get("target_offset"), -1)
            source_value = parse_int(row.get("source_u32_hex"), -1)
            target_value = parse_int(row.get("target_u32_hex"), -1)
            if min(source_offset, target_offset, source_value, target_value) < 0:
                continue
            if not compensation_holds(source_offset, target_offset, source_value, target_value):
                continue
            key = stable_key(row.get("normalized_path", ""), row.get("member_key", ""))
            source_size, target_size = member_sizes.get(key, (-1, -1))
            source_endpoint = source_offset + signed_i32(source_value)
            target_endpoint = target_offset + signed_i32(target_value)
            recurrence_rows.append({
                "character_slot": row.get("character_slot", ""),
                "asset_role": row.get("asset_role", ""),
                "normalized_path": row.get("normalized_path", ""),
                "member_key": row.get("member_key", ""),
                "member_name": row.get("member_name", ""),
                "segment_id": row.get("segment_id", ""),
                "source_offset": source_offset,
                "target_offset": target_offset,
                "shift_bytes": target_offset - source_offset,
                "source_u32_hex": row.get("source_u32_hex", ""),
                "target_u32_hex": row.get("target_u32_hex", ""),
                "source_i32": signed_i32(source_value),
                "target_i32": signed_i32(target_value),
                "source_endpoint_dword_start_model": source_endpoint,
                "target_endpoint_dword_start_model": target_endpoint,
                "endpoint_equal": source_endpoint == target_endpoint,
                "source_endpoint_in_bounds": 0 <= source_endpoint < source_size,
                "target_endpoint_in_bounds": 0 <= target_endpoint < target_size,
                "endpoint_dword_aligned": source_endpoint % 4 == 0 and target_endpoint % 4 == 0,
                "transition_classification_stage84": row.get("transition_classification", ""),
            })

        all_compensated = all(parse_bool(row["relocation_compensation_exact"]) for row in audit_rows)
        plausible_field_start = all("dword_start_relative" in row["plausible_exact_models"].split(",") for row in audit_rows)
        normalized_classification = (
            "shared_two_leaf_core_with_equivalent_relocation_compensated_residuals_offset_origin_unresolved"
            if all_compensated and plausible_field_start
            else "shared_two_leaf_core_with_unresolved_non_equivalent_residuals"
        )
        normalized_rows = [{
            "shared_exact_transition_rows": EXPECTED_SHARED_ROWS,
            "residual_rows": len(audit_rows),
            "relocation_compensated_residual_rows": sum(parse_bool(row["relocation_compensation_exact"]) for row in audit_rows),
            "stage84_relocation_compensation_recurrence_rows": len(recurrence_rows),
            "normalized_classification": normalized_classification,
            "offset_origin": "unresolved_multiple_exact_shifted_base_models",
            "brightness_semantics": "unresolved",
            "censorship_semantics": "unresolved",
            "prototype_status": "evidence_only_no_G1E_write",
        }]

        output_dir = reports / REPORT_DIR
        output_dir.mkdir(parents=True, exist_ok=True)
        write_tsv(output_dir / "SLOT_LIGHT_RESIDUAL_AUDIT.tsv", [
            "island_role", "normalized_path", "member_key", "member_name", "source_offset", "target_offset",
            "local_shift_bytes", "source_u32_hex", "target_u32_hex", "source_i32", "target_i32", "signed_delta",
            "expected_compensation_delta", "relocation_compensation_exact", "plausible_exact_model_count",
            "plausible_exact_models", "classification",
        ], audit_rows)
        write_tsv(output_dir / "SLOT_LIGHT_RESIDUAL_OFFSET_MODELS.tsv", [
            "island_role", "member_name", "model", "source_base", "target_base", "source_signed_value", "target_signed_value",
            "source_endpoint", "target_endpoint", "endpoint_equal", "source_endpoint_in_bounds", "target_endpoint_in_bounds",
            "endpoint_dword_aligned", "model_status",
        ], model_rows)
        write_tsv(output_dir / "SLOT_LIGHT_RESIDUAL_ENDPOINT_CONTEXTS.tsv", [
            "island_role", "member_name", "model", "endpoint", "source_context_start", "source_context_end_exclusive",
            "target_context_start", "target_context_end_exclusive", "source_context_sha256", "target_context_sha256",
            "source_target_context_equal",
        ], endpoint_rows)
        write_tsv(output_dir / "SLOT_LIGHT_RELATIVE_OFFSET_RECURRENCE.tsv", [
            "character_slot", "asset_role", "normalized_path", "member_key", "member_name", "segment_id", "source_offset",
            "target_offset", "shift_bytes", "source_u32_hex", "target_u32_hex", "source_i32", "target_i32",
            "source_endpoint_dword_start_model", "target_endpoint_dword_start_model", "endpoint_equal",
            "source_endpoint_in_bounds", "target_endpoint_in_bounds", "endpoint_dword_aligned", "transition_classification_stage84",
        ], recurrence_rows)
        write_tsv(output_dir / "SLOT_LIGHT_RECORD_BOUNDARY_CANDIDATES.tsv", [
            "island_role", "member_name", "island_source_start", "island_source_end_exclusive", "residual_source_offset",
            "residual_relative_dword", "stage84_segment_id", "stage84_segment_type", "stage84_segment_source_start",
            "stage84_segment_source_end_exclusive", "nearest_exact_run_before_source_start", "nearest_exact_run_before_length",
            "nearest_exact_run_after_source_start", "nearest_exact_run_after_length", "record_boundary_status",
        ], boundary_rows)
        write_tsv(output_dir / "SLOT_LIGHT_NORMALIZED_ISLAND_COMPARISON.tsv", [
            "shared_exact_transition_rows", "residual_rows", "relocation_compensated_residual_rows",
            "stage84_relocation_compensation_recurrence_rows", "normalized_classification", "offset_origin",
            "brightness_semantics", "censorship_semantics", "prototype_status",
        ], normalized_rows)
        write_tsv(output_dir / "SLOT_LIGHT_RECORD_BOUNDARY_SKIPPED.tsv", ["scope", "reason"], [])

        recurrence_by_member = Counter(row["member_name"] for row in recurrence_rows)
        summary = {
            "type": "br_quartet_restoration_reflector_slot_light_record_boundary_residual_evidence_summary",
            "format_version": 1,
            "tool_version": TOOL_VERSION,
            "source_stage87_tool_version": summary87.get("tool_version"),
            "source_stage84_tool_version": summary84.get("tool_version"),
            "source_stage79_tool_version": summary79.get("tool_version"),
            "status": "stage87_residuals_tested_as_relocation_compensated_signed_fields_offset_origin_and_brightness_semantics_unresolved",
            "adaptive_change_island_rows": len(island_rows),
            "shared_two_leaf_transition_rows": EXPECTED_SHARED_ROWS,
            "residual_rows": len(audit_rows),
            "relocation_compensated_residual_rows": sum(parse_bool(row["relocation_compensation_exact"]) for row in audit_rows),
            "residuals_with_exact_in_bounds_dword_start_model": sum("dword_start_relative" in row["plausible_exact_models"].split(",") for row in audit_rows),
            "plausible_model_rows": sum(row["model_status"] == "exact_in_bounds_aligned" for row in model_rows),
            "offset_origin_resolved": False,
            "stage84_aligned_changed_dword_rows_scanned": len(dword_rows84),
            "stage84_relocation_compensation_recurrence_rows": len(recurrence_rows),
            "stage84_recurrence_member_rows": len(recurrence_by_member),
            "normalized_classification": normalized_classification,
            "prototype_candidate_rows": 0,
            "brightness_semantics_confirmed": False,
            "censorship_semantics_confirmed": False,
            "skipped_rows": 0,
            "parameters": {
                "signed_integer_width_bits": 32,
                "endpoint_context_radius_bytes": ENDPOINT_CONTEXT_RADIUS,
                "tested_offset_origins": [
                    "dword_start_relative", "dword_end_relative", "island_start_relative",
                    "island_end_relative", "member_start_signed_absolute", "member_start_unsigned_absolute",
                ],
                "relocation_compensation_equation": "target_i32-source_i32 == -(target_offset-source_offset)",
            },
            "policy": {
                "installed_game_modified": False,
                "render_payload_written": False,
                "event_payload_written": False,
                "pak_repacked": False,
                "core_registry_modified": False,
                "profile_activated": False,
                "runtime_validation_inferred": False,
                "censorship_semantics_inferred": False,
                "brightness_semantics_inferred": False,
                "offset_origin_inferred": False,
                "canary_track_modified": False,
                "full_proprietary_payloads_exported": False,
            },
            "next_action": "Upload this report. Treat exact relocation compensation as structural evidence only. If multiple offset-origin models remain exact, continue with a narrower G1E section/record-origin audit; do not write G1E or infer brightness/censorship.",
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
    except Stage88Error as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print(json.dumps({"output_dir": str(output), "archive": str(archive) if archive else None, "summary": summary}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
