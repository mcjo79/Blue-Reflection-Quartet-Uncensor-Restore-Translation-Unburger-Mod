#!/usr/bin/env python3
"""Audit stage-88 field-relative reference clusters and their target windows.

Stage 88 proved that both stage-87 residual dwords exactly compensate local
Original-to-Quartet relocation.  This read-only stage asks a narrower format
question: do those fields behave like members of repeated field-relative
reference clusters, and what structural metadata is present at the referenced
targets?  It validates the existing stage-88 report, rehydrates only the same
four bounded effect containers, verifies every relevant reference against the
actual G1E/G1EM payloads, scans inbound references to the two focal target
locations, hashes progressively larger target windows, and compares the two
44-byte islands after masking only their final relocation field.

The report exports offsets, counts, dword values, classifications and SHA-256
hashes only.  It never writes G1E/G1EM, Elixir, PAK, registry or installed-game
content and never infers brightness or censorship semantics.
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

TOOL_VERSION = "0.1.3"
REPORT_NAME = "BR_quartet_restoration_reflector_slot_light_reference_target_header_evidence.tar.zst"
REPORT_DIR = "reflector_slot_light_reference_target_header_evidence"
STAGE88_DIR = "reflector_slot_light_record_boundary_residual_evidence"
STAGE88_ARCHIVE = "BR_quartet_restoration_reflector_slot_light_record_boundary_residual_evidence.tar.zst"
STAGE87_DIR = "reflector_slot_light_local_change_island_evidence"
STAGE87_ARCHIVE = "BR_quartet_restoration_reflector_slot_light_local_change_island_evidence.tar.zst"
STAGE79_DIR = "reflector_character_slot_render_member_evidence"
STAGE79_ARCHIVE = "BR_quartet_restoration_reflector_character_slot_render_member_evidence.tar.zst"
EXPECTED_PARENT_CONTAINERS = 4
EXPECTED_SIBLING_PAIRS = 540
EXPECTED_RESIDUAL_ROWS = 2
EXPECTED_STAGE88_RECURRENCE_ROWS = 51
TARGET_WINDOW_RADII_DWORDS = (4, 8, 16, 32, 64)
TARGET_HEADER_DWORDS = 32
MASKED_RECORD_BYTES = 44


class Stage89Error(RuntimeError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise Stage89Error(message)


def progress(message: str) -> None:
    print(f"[stage89] {message}", file=sys.stderr, flush=True)


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
            raise Stage89Error(f"missing required TSV: {path}")
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
        raise Stage89Error(f"invalid JSON {path}: {exc}") from exc
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


def validate_stage88(root: Path) -> dict[str, Any]:
    summary = load_json(root / "SUMMARY.json")
    require(summary.get("type") == "br_quartet_restoration_reflector_slot_light_record_boundary_residual_evidence_summary", "stage88 type mismatch")
    require(summary.get("tool_version") == "0.1.2", "stage88 tool version mismatch")
    require(summary.get("status") == "stage87_residuals_tested_as_relocation_compensated_signed_fields_offset_origin_and_brightness_semantics_unresolved", "stage88 status mismatch")
    require(parse_int(summary.get("residual_rows"), -1) == EXPECTED_RESIDUAL_ROWS, "stage88 residual count mismatch")
    require(parse_int(summary.get("relocation_compensated_residual_rows"), -1) == EXPECTED_RESIDUAL_ROWS, "stage88 compensation count mismatch")
    require(parse_int(summary.get("stage84_relocation_compensation_recurrence_rows"), -1) == EXPECTED_STAGE88_RECURRENCE_ROWS, "stage88 recurrence count mismatch")
    require(parse_int(summary.get("stage84_recurrence_member_rows"), -1) == 5, "stage88 recurrence member count mismatch")
    require(not parse_bool(summary.get("offset_origin_resolved")), "stage88 unexpectedly resolved the offset origin")
    require(parse_int(summary.get("prototype_candidate_rows"), -1) == 0, "stage88 unexpectedly authorized a prototype")
    require(not parse_bool(summary.get("brightness_semantics_confirmed")), "stage88 unexpectedly confirmed brightness")
    require(not parse_bool(summary.get("censorship_semantics_confirmed")), "stage88 unexpectedly confirmed censorship")
    require(parse_int(summary.get("skipped_rows"), -1) == 0, "stage88 contains skipped rows")
    policy = summary.get("policy") or {}
    require(isinstance(policy, dict), "stage88 policy malformed")
    for field in ("installed_game_modified", "render_payload_written", "pak_repacked", "core_registry_modified", "profile_activated"):
        require(not parse_bool(policy.get(field)), f"stage88 performed forbidden action: {field}")
    return summary


def dword(payload: bytes, offset: int) -> int:
    require(offset >= 0 and offset + 4 <= len(payload) and offset % 4 == 0, f"invalid dword offset {offset}")
    return int.from_bytes(payload[offset:offset + 4], "little")


def finite_float(value: int) -> tuple[str, str]:
    decoded = struct.unpack("<f", int(value & 0xFFFFFFFF).to_bytes(4, "little"))[0]
    if not math.isfinite(decoded):
        return "", "nonfinite"
    if decoded == 0.0:
        return "0", "zero"
    if abs(decoded) < 1e-30:
        return f"{decoded:.9g}", "subnormal_or_tiny"
    return f"{decoded:.9g}", "finite"


def classify_dword(source_value: int, target_value: int, relative_dword: int, source_size: int, target_size: int) -> str:
    if source_value == target_value:
        return "unchanged"
    source_signed = signed_i32(source_value)
    target_signed = signed_i32(target_value)
    if relative_dword == 0 and 0 < source_value <= source_size * 2 and 0 < target_value <= target_size * 2:
        return "target_window_leading_size_or_offset_candidate"
    if source_value <= 0xFFFF and target_value <= 0xFFFF:
        return "small_integer_count_flag_or_offset"
    if source_signed < 0 and target_signed < 0:
        return "negative_relative_reference_or_rebase_candidate"
    sf, ss = finite_float(source_value)
    tf, ts = finite_float(target_value)
    if ss == "finite" and ts == "finite" and sf and tf:
        return "finite_float_transition_semantics_unresolved"
    return "opaque_dword_transition"


def inbound_reference_offsets(payload: bytes, endpoint: int) -> list[int]:
    offsets: list[int] = []
    for offset in range(0, len(payload) - 3, 4):
        value = int.from_bytes(payload[offset:offset + 4], "little")
        displacement = signed_i32(value)
        if displacement == 0:
            continue
        if offset + displacement == endpoint:
            offsets.append(offset)
    return offsets


def aligned_occurrences(payload: bytes, needle: bytes) -> list[int]:
    if not needle:
        return []
    rows: list[int] = []
    start = 0
    while True:
        found = payload.find(needle, start)
        if found < 0:
            return rows
        if found % 4 == 0:
            rows.append(found)
        start = found + 1


def centered_window(payload: bytes, endpoint: int, radius_dwords: int) -> bytes | None:
    radius = radius_dwords * 4
    start = endpoint - radius
    end = endpoint + 4 + radius
    if start < 0 or end > len(payload):
        return None
    return payload[start:end]


def masked_record(payload: bytes, start: int, end: int, residual_offset: int) -> bytes:
    require(end - start == MASKED_RECORD_BYTES, f"unexpected island length: {end - start}")
    require(start <= residual_offset <= end - 4 and residual_offset % 4 == 0, "residual outside island")
    data = bytearray(payload[start:end])
    relative = residual_offset - start
    data[relative:relative + 4] = b"\x00\x00\x00\x00"
    return bytes(data)


def model_support_rows(stage88_root: Path, cluster_rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    endpoint_contexts = read_tsv(stage88_root / "SLOT_LIGHT_RESIDUAL_ENDPOINT_CONTEXTS.tsv")
    model_rows = read_tsv(stage88_root / "SLOT_LIGHT_RESIDUAL_OFFSET_MODELS.tsv")
    exact_models = [row for row in model_rows if row.get("model_status") == "exact_in_bounds_aligned"]
    by_model = defaultdict(list)
    for row in exact_models:
        by_model[str(row.get("model", ""))].append(row)
    context_equal = Counter(
        row.get("model", "") for row in endpoint_contexts if parse_bool(row.get("source_target_context_equal"))
    )
    field_reference_rows = len(cluster_rows)
    rows: list[dict[str, Any]] = []
    for model in ("dword_start_relative", "dword_end_relative", "island_start_relative", "island_end_relative"):
        independent = field_reference_rows if model in {"dword_start_relative", "dword_end_relative"} else 0
        classification = "exact_model_without_independent_reference_cluster"
        if model in {"dword_start_relative", "dword_end_relative"} and independent:
            classification = "field_relative_model_supported_by_repeated_independent_reference_clusters"
        if context_equal[model] == EXPECTED_RESIDUAL_ROWS:
            classification += "_and_source_target_context_invariance"
        rows.append({
            "model": model,
            "exact_residual_rows": len(by_model.get(model, [])),
            "source_target_context_equal_rows": context_equal[model],
            "independent_reference_cluster_rows": independent,
            "base_family": "field_relative" if model in {"dword_start_relative", "dword_end_relative"} else "island_relative",
            "model_support_classification": classification,
            "exact_byte_origin_resolved": False,
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
    container_loader: Callable[..., tuple[list[dict[str, Any]], list[dict[str, Any]]]] | None = None,
) -> tuple[Path, Path | None, dict[str, Any]]:
    project_root = project_root.resolve()
    reports = (report_root or project_root / ".local/reports/quartet_restoration").resolve()
    workspace = (workspace_root or project_root / ".local/build/quartet_restoration").resolve()
    require(reports.is_dir(), f"missing report root: {reports}")

    stage81 = load_module(project_root / "workstreams/quartet_restoration/collect_reflector_ringlight_control_callsite_evidence.py", "stage81_for_stage89")
    stage86 = load_module(project_root / "workstreams/quartet_restoration/collect_reflector_slot_light_shared_record_template_evidence.py", "stage86_for_stage89")
    stage87 = load_module(project_root / "workstreams/quartet_restoration/collect_reflector_slot_light_local_change_island_evidence.py", "stage87_for_stage89")

    progress("validating stage 79, 87 and 88 reports")
    with tempfile.TemporaryDirectory(prefix="br-stage89-") as temporary_name:
        temporary = Path(temporary_name)
        stage88_root = locate(reports, STAGE88_DIR, STAGE88_ARCHIVE, temporary / "88")
        stage87_root = locate(reports, STAGE87_DIR, STAGE87_ARCHIVE, temporary / "87")
        stage79_root = locate(reports, STAGE79_DIR, STAGE79_ARCHIVE, temporary / "79")
        summary88 = validate_stage88(stage88_root)
        summary79 = stage81.validate_stage79(stage79_root)

        residual_rows = read_tsv(stage88_root / "SLOT_LIGHT_RESIDUAL_AUDIT.tsv")
        recurrence_rows = read_tsv(stage88_root / "SLOT_LIGHT_RELATIVE_OFFSET_RECURRENCE.tsv")
        require(len(residual_rows) == EXPECTED_RESIDUAL_ROWS, "stage88 residual table count mismatch")
        require(len(recurrence_rows) == EXPECTED_STAGE88_RECURRENCE_ROWS, "stage88 recurrence table count mismatch")
        require({row.get("island_role") for row in residual_rows} == {"candidate_ringlight", "neutral_control"}, "stage88 residual roles mismatch")

        island_rows = read_tsv(stage87_root / "SLOT_LIGHT_LOCAL_CHANGE_ISLANDS.tsv")
        transition_rows = read_tsv(stage87_root / "SLOT_LIGHT_LOCAL_CHANGE_ISLAND_TRANSITIONS.tsv")
        require(len(island_rows) == EXPECTED_RESIDUAL_ROWS, "stage87 island count mismatch")
        island_by_role = {row["island_role"]: row for row in island_rows}

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
        pair_by_key, all_pairs = stage86.index_pairs(containers)
        require(len(all_pairs) == EXPECTED_SIBLING_PAIRS, f"expected {EXPECTED_SIBLING_PAIRS} sibling pairs, found {len(all_pairs)}")
        progress(f"indexed {len(all_pairs)} sibling G1E/G1EM payload pairs")

        residual_by_role = {row["island_role"]: row for row in residual_rows}
        focal: dict[str, dict[str, Any]] = {}
        for role, residual in residual_by_role.items():
            key = stable_key(str(residual.get("normalized_path", "")), str(residual.get("member_key", "")))
            pair = pair_by_key.get(key)
            require(pair is not None, f"missing residual payload pair: {key}")
            source_offset = parse_int(residual.get("source_offset"), -1)
            target_offset = parse_int(residual.get("target_offset"), -1)
            source_value = parse_int(residual.get("source_u32_hex"), -1)
            target_value = parse_int(residual.get("target_u32_hex"), -1)
            require(dword(pair["source_payload"], source_offset) == source_value, f"source residual mismatch for {role}")
            require(dword(pair["target_payload"], target_offset) == target_value, f"target residual mismatch for {role}")
            source_endpoint = source_offset + signed_i32(source_value)
            target_endpoint = target_offset + signed_i32(target_value)
            require(source_endpoint == target_endpoint, f"dword-start endpoint mismatch for {role}")
            focal[role] = {
                "role": role,
                "pair": pair,
                "source_offset": source_offset,
                "target_offset": target_offset,
                "source_endpoint": source_endpoint,
                "target_endpoint": target_endpoint,
                "source_value": source_value,
                "target_value": target_value,
            }

        # Stage-88 changed-reference rows that independently support the two focal
        # endpoint values. Candidate 20276 is expected to recur within PC02; the
        # neutral endpoint 192 is expected in the PC00 eyelight controls.
        cluster_seed_rows: list[dict[str, Any]] = []
        for row in recurrence_rows:
            endpoint = parse_int(row.get("source_endpoint_dword_start_model"), -1)
            role = ""
            if endpoint == focal["candidate_ringlight"]["source_endpoint"]:
                role = "candidate_ringlight"
            elif endpoint == focal["neutral_control"]["source_endpoint"]:
                role = "neutral_control"
            if role:
                cluster_seed_rows.append({**row, "cluster_role": role, "origin": "stage88_recurrence"})
        # Add each stage-87 residual if it is not already represented.
        identities = {
            (row["cluster_role"], str(row.get("normalized_path", "")).casefold(), str(row.get("member_key", "")).casefold(), parse_int(row.get("source_offset"), -1))
            for row in cluster_seed_rows
        }
        for role, item in focal.items():
            pair = item["pair"]
            identity = (role, pair["normalized_path"].casefold(), pair["member_key"].casefold(), item["source_offset"])
            if identity not in identities:
                cluster_seed_rows.append({
                    "cluster_role": role,
                    "origin": "stage87_residual",
                    "normalized_path": pair["normalized_path"],
                    "member_key": pair["member_key"],
                    "member_name": pair["member_name"],
                    "source_offset": item["source_offset"],
                    "target_offset": item["target_offset"],
                    "source_u32_hex": f"0x{item['source_value']:08x}",
                    "target_u32_hex": f"0x{item['target_value']:08x}",
                    "source_endpoint_dword_start_model": item["source_endpoint"],
                    "target_endpoint_dword_start_model": item["target_endpoint"],
                })

        cluster_rows: list[dict[str, Any]] = []
        members_by_role: dict[str, set[tuple[str, str]]] = defaultdict(set)
        for seed in cluster_seed_rows:
            role = str(seed.get("cluster_role", ""))
            key = stable_key(str(seed.get("normalized_path", "")), str(seed.get("member_key", "")))
            pair = pair_by_key.get(key)
            require(pair is not None, f"missing cluster payload pair: {key}")
            source_offset = parse_int(seed.get("source_offset"), -1)
            target_offset = parse_int(seed.get("target_offset"), -1)
            source_value = parse_int(seed.get("source_u32_hex"), -1)
            target_value = parse_int(seed.get("target_u32_hex"), -1)
            require(dword(pair["source_payload"], source_offset) == source_value, f"cluster source value mismatch: {pair['member_name']}@{source_offset}")
            require(dword(pair["target_payload"], target_offset) == target_value, f"cluster target value mismatch: {pair['member_name']}@{target_offset}")
            source_endpoint = source_offset + signed_i32(source_value)
            target_endpoint = target_offset + signed_i32(target_value)
            require(source_endpoint == target_endpoint, f"cluster endpoint mismatch: {pair['member_name']}@{source_offset}")
            members_by_role[role].add(key)
            cluster_rows.append({
                "cluster_role": role,
                "origin": seed.get("origin", "stage88_recurrence"),
                "normalized_path": pair["normalized_path"],
                "member_key": pair["member_key"],
                "member_name": pair["member_name"],
                "source_offset": source_offset,
                "target_offset": target_offset,
                "source_u32_hex": f"0x{source_value:08x}",
                "target_u32_hex": f"0x{target_value:08x}",
                "source_i32": signed_i32(source_value),
                "target_i32": signed_i32(target_value),
                "endpoint": source_endpoint,
                "source_target_endpoint_equal": True,
            })

        reference_audit_rows: list[dict[str, Any]] = []
        target_window_rows: list[dict[str, Any]] = []
        target_hash_rows: list[dict[str, Any]] = []
        target_recurrence_rows: list[dict[str, Any]] = []

        for role in ("candidate_ringlight", "neutral_control"):
            item = focal[role]
            canonical_endpoint = item["source_endpoint"]
            relevant_members = sorted(members_by_role[role])
            progress(f"auditing {role} reference cluster across {len(relevant_members)} member(s)")
            for key in relevant_members:
                pair = pair_by_key[key]
                # Every seed in this member for the role has the same endpoint.
                member_seed_count = sum(
                    1 for row in cluster_rows
                    if row["cluster_role"] == role and stable_key(row["normalized_path"], row["member_key"]) == key
                )
                source_refs = inbound_reference_offsets(pair["source_payload"], canonical_endpoint)
                target_refs = inbound_reference_offsets(pair["target_payload"], canonical_endpoint)
                reference_audit_rows.append({
                    "cluster_role": role,
                    "normalized_path": pair["normalized_path"],
                    "member_key": pair["member_key"],
                    "member_name": pair["member_name"],
                    "endpoint": canonical_endpoint,
                    "stage87_or_88_seed_reference_rows": member_seed_count,
                    "source_all_inbound_reference_rows": len(source_refs),
                    "target_all_inbound_reference_rows": len(target_refs),
                    "source_inbound_offsets_sha256": sha256(b"".join(int(v).to_bytes(8, "little") for v in source_refs)),
                    "target_inbound_offsets_sha256": sha256(b"".join(int(v).to_bytes(8, "little") for v in target_refs)),
                    "source_target_inbound_count_equal": len(source_refs) == len(target_refs),
                    "field_relative_reference_fan_in_confirmed": len(source_refs) >= member_seed_count and len(target_refs) >= member_seed_count,
                })

            canonical_pair = item["pair"]
            for relative in range(TARGET_HEADER_DWORDS):
                source_offset = canonical_endpoint + relative * 4
                target_offset = canonical_endpoint + relative * 4
                if source_offset + 4 > len(canonical_pair["source_payload"]) or target_offset + 4 > len(canonical_pair["target_payload"]):
                    break
                source_value = dword(canonical_pair["source_payload"], source_offset)
                target_value = dword(canonical_pair["target_payload"], target_offset)
                source_float, source_float_status = finite_float(source_value)
                target_float, target_float_status = finite_float(target_value)
                target_window_rows.append({
                    "cluster_role": role,
                    "member_name": canonical_pair["member_name"],
                    "endpoint": canonical_endpoint,
                    "relative_dword": relative,
                    "source_offset": source_offset,
                    "target_offset": target_offset,
                    "source_u32_hex": f"0x{source_value:08x}",
                    "target_u32_hex": f"0x{target_value:08x}",
                    "source_i32": signed_i32(source_value),
                    "target_i32": signed_i32(target_value),
                    "source_float32": source_float,
                    "target_float32": target_float,
                    "source_float_status": source_float_status,
                    "target_float_status": target_float_status,
                    "source_target_equal": source_value == target_value,
                    "classification": classify_dword(source_value, target_value, relative, len(canonical_pair["source_payload"]), len(canonical_pair["target_payload"])),
                })

            for radius in TARGET_WINDOW_RADII_DWORDS:
                source_window = centered_window(canonical_pair["source_payload"], canonical_endpoint, radius)
                target_window = centered_window(canonical_pair["target_payload"], canonical_endpoint, radius)
                available = source_window is not None and target_window is not None
                source_hash = sha256(source_window) if source_window is not None else ""
                target_hash = sha256(target_window) if target_window is not None else ""
                target_hash_rows.append({
                    "cluster_role": role,
                    "member_name": canonical_pair["member_name"],
                    "endpoint": canonical_endpoint,
                    "radius_dwords": radius,
                    "window_available": available,
                    "source_window_sha256": source_hash,
                    "target_window_sha256": target_hash,
                    "source_target_window_equal": bool(available and source_window == target_window),
                })
                if not available:
                    continue
                for sibling in all_pairs:
                    source_occurrences = aligned_occurrences(sibling["source_payload"], source_window)
                    target_occurrences = aligned_occurrences(sibling["target_payload"], target_window)
                    if not source_occurrences and not target_occurrences:
                        continue
                    target_recurrence_rows.append({
                        "cluster_role": role,
                        "radius_dwords": radius,
                        "sibling_normalized_path": sibling["normalized_path"],
                        "sibling_member_key": sibling["member_key"],
                        "sibling_member_name": sibling["member_name"],
                        "source_window_occurrence_count": len(source_occurrences),
                        "target_window_occurrence_count": len(target_occurrences),
                        "source_occurrence_offsets_sha256": sha256(b"".join(int(v).to_bytes(8, "little") for v in source_occurrences)),
                        "target_occurrence_offsets_sha256": sha256(b"".join(int(v).to_bytes(8, "little") for v in target_occurrences)),
                    })

        normalized_record_rows: list[dict[str, Any]] = []
        masked_by_role: dict[str, tuple[bytes, bytes]] = {}
        for role in ("candidate_ringlight", "neutral_control"):
            island = island_by_role[role]
            item = focal[role]
            source_start = parse_int(island.get("source_start"), -1)
            source_end = parse_int(island.get("source_end_exclusive"), -1)
            target_start = parse_int(island.get("target_start"), -1)
            target_end = parse_int(island.get("target_end_exclusive"), -1)
            source_masked = masked_record(item["pair"]["source_payload"], source_start, source_end, item["source_offset"])
            target_masked = masked_record(item["pair"]["target_payload"], target_start, target_end, item["target_offset"])
            masked_by_role[role] = (source_masked, target_masked)
            normalized_record_rows.append({
                "island_role": role,
                "member_name": item["pair"]["member_name"],
                "record_length": len(source_masked),
                "masked_relative_dword": (item["source_offset"] - source_start) // 4,
                "source_masked_record_sha256": sha256(source_masked),
                "target_masked_record_sha256": sha256(target_masked),
                "source_target_masked_record_equal": source_masked == target_masked,
                "changed_dword_rows_after_mask": sum(
                    dword(source_masked, off) != dword(target_masked, off)
                    for off in range(0, len(source_masked), 4)
                ),
            })

        candidate_source, candidate_target = masked_by_role["candidate_ringlight"]
        neutral_source, neutral_target = masked_by_role["neutral_control"]
        normalized_comparison_rows = [{
            "record_length": MASKED_RECORD_BYTES,
            "masked_relative_dword": 10,
            "candidate_neutral_source_masked_equal": candidate_source == neutral_source,
            "candidate_neutral_target_masked_equal": candidate_target == neutral_target,
            "candidate_neutral_joint_masked_equal": candidate_source == neutral_source and candidate_target == neutral_target,
            "candidate_source_masked_sha256": sha256(candidate_source),
            "neutral_source_masked_sha256": sha256(neutral_source),
            "candidate_target_masked_sha256": sha256(candidate_target),
            "neutral_target_masked_sha256": sha256(neutral_target),
            "shared_non_residual_changed_dwords": 2,
            "brightness_semantics": "unresolved",
            "prototype_status": "evidence_only_no_G1E_write",
        }]

        support_rows = model_support_rows(stage88_root, cluster_rows)
        field_relative_supported = all(
            any(
                row["model"] == model and row["independent_reference_cluster_rows"] >= EXPECTED_RESIDUAL_ROWS
                for row in support_rows
            )
            for model in ("dword_start_relative", "dword_end_relative")
        )
        exact_origin_resolved = False
        normalized_records_equal = bool(normalized_comparison_rows[0]["candidate_neutral_joint_masked_equal"])
        source_inbound_total = sum(parse_int(row.get("source_all_inbound_reference_rows"), 0) for row in reference_audit_rows)
        target_inbound_total = sum(parse_int(row.get("target_all_inbound_reference_rows"), 0) for row in reference_audit_rows)
        candidate_seed_rows = sum(row["cluster_role"] == "candidate_ringlight" for row in cluster_rows)
        neutral_seed_rows = sum(row["cluster_role"] == "neutral_control" for row in cluster_rows)
        target_changed_rows = sum(not parse_bool(row["source_target_equal"]) for row in target_window_rows)

        if field_relative_supported:
            format_classification = "field_relative_reference_clusters_confirmed_start_vs_end_four_byte_origin_unresolved"
        else:
            format_classification = "reference_base_family_unresolved"
        if normalized_records_equal:
            record_template_classification = "candidate_and_neutral_11_dword_records_exact_after_masking_relocation_field"
        else:
            record_template_classification = "candidate_and_neutral_11_dword_records_still_diverge_after_masking_relocation_field"

        output_dir = reports / REPORT_DIR
        output_dir.mkdir(parents=True, exist_ok=True)
        write_tsv(output_dir / "SLOT_LIGHT_REFERENCE_CLUSTER_SEEDS.tsv", [
            "cluster_role", "origin", "normalized_path", "member_key", "member_name", "source_offset", "target_offset",
            "source_u32_hex", "target_u32_hex", "source_i32", "target_i32", "endpoint", "source_target_endpoint_equal",
        ], cluster_rows)
        write_tsv(output_dir / "SLOT_LIGHT_REFERENCE_CLUSTER_AUDIT.tsv", [
            "cluster_role", "normalized_path", "member_key", "member_name", "endpoint", "stage87_or_88_seed_reference_rows",
            "source_all_inbound_reference_rows", "target_all_inbound_reference_rows", "source_inbound_offsets_sha256",
            "target_inbound_offsets_sha256", "source_target_inbound_count_equal", "field_relative_reference_fan_in_confirmed",
        ], reference_audit_rows)
        write_tsv(output_dir / "SLOT_LIGHT_REFERENCE_TARGET_WINDOW_DWORDS.tsv", [
            "cluster_role", "member_name", "endpoint", "relative_dword", "source_offset", "target_offset", "source_u32_hex",
            "target_u32_hex", "source_i32", "target_i32", "source_float32", "target_float32", "source_float_status",
            "target_float_status", "source_target_equal", "classification",
        ], target_window_rows)
        write_tsv(output_dir / "SLOT_LIGHT_REFERENCE_TARGET_WINDOW_HASHES.tsv", [
            "cluster_role", "member_name", "endpoint", "radius_dwords", "window_available", "source_window_sha256",
            "target_window_sha256", "source_target_window_equal",
        ], target_hash_rows)
        write_tsv(output_dir / "SLOT_LIGHT_REFERENCE_TARGET_WINDOW_RECURRENCE.tsv", [
            "cluster_role", "radius_dwords", "sibling_normalized_path", "sibling_member_key", "sibling_member_name",
            "source_window_occurrence_count", "target_window_occurrence_count", "source_occurrence_offsets_sha256",
            "target_occurrence_offsets_sha256",
        ], target_recurrence_rows)
        write_tsv(output_dir / "SLOT_LIGHT_MASKED_RECORD_IMAGES.tsv", [
            "island_role", "member_name", "record_length", "masked_relative_dword", "source_masked_record_sha256",
            "target_masked_record_sha256", "source_target_masked_record_equal", "changed_dword_rows_after_mask",
        ], normalized_record_rows)
        write_tsv(output_dir / "SLOT_LIGHT_MASKED_RECORD_TEMPLATE_COMPARISON.tsv", [
            "record_length", "masked_relative_dword", "candidate_neutral_source_masked_equal", "candidate_neutral_target_masked_equal",
            "candidate_neutral_joint_masked_equal", "candidate_source_masked_sha256", "neutral_source_masked_sha256",
            "candidate_target_masked_sha256", "neutral_target_masked_sha256", "shared_non_residual_changed_dwords",
            "brightness_semantics", "prototype_status",
        ], normalized_comparison_rows)
        write_tsv(output_dir / "SLOT_LIGHT_OFFSET_ORIGIN_SUPPORT.tsv", [
            "model", "exact_residual_rows", "source_target_context_equal_rows", "independent_reference_cluster_rows",
            "base_family", "model_support_classification", "exact_byte_origin_resolved",
        ], support_rows)
        write_tsv(output_dir / "SLOT_LIGHT_REFERENCE_TARGET_SKIPPED.tsv", ["scope", "reason"], [])

        summary = {
            "type": "br_quartet_restoration_reflector_slot_light_reference_target_header_evidence_summary",
            "format_version": 1,
            "tool_version": TOOL_VERSION,
            "source_stage88_tool_version": summary88.get("tool_version"),
            "source_stage79_tool_version": summary79.get("tool_version"),
            "status": "stage88_relocation_fields_audited_as_repeated_field_relative_reference_clusters_exact_start_vs_end_origin_and_brightness_semantics_unresolved",
            "sibling_G1E_G1EM_member_rows": len(all_pairs),
            "residual_rows": len(residual_rows),
            "reference_cluster_seed_rows": len(cluster_rows),
            "candidate_reference_cluster_seed_rows": candidate_seed_rows,
            "neutral_reference_cluster_seed_rows": neutral_seed_rows,
            "reference_cluster_member_rows": len(reference_audit_rows),
            "source_all_inbound_reference_rows": source_inbound_total,
            "target_all_inbound_reference_rows": target_inbound_total,
            "field_relative_base_family_supported": field_relative_supported,
            "exact_field_start_vs_end_origin_resolved": exact_origin_resolved,
            "target_window_dword_rows": len(target_window_rows),
            "target_window_changed_dword_rows": target_changed_rows,
            "target_window_hash_rows": len(target_hash_rows),
            "target_window_recurrence_rows": len(target_recurrence_rows),
            "masked_record_rows": len(normalized_record_rows),
            "masked_record_template_exact_across_candidate_and_neutral": normalized_records_equal,
            "format_classification": format_classification,
            "record_template_classification": record_template_classification,
            "prototype_candidate_rows": 0,
            "brightness_semantics_confirmed": False,
            "censorship_semantics_confirmed": False,
            "skipped_rows": 0,
            "parameters": {
                "target_window_radii_dwords": list(TARGET_WINDOW_RADII_DWORDS),
                "target_header_dwords": TARGET_HEADER_DWORDS,
                "record_length_bytes": MASKED_RECORD_BYTES,
                "masked_relocation_relative_dword": 10,
                "field_relative_reference_equation": "field_offset + signed_i32(field_value) == endpoint",
                "exact_origin_ambiguity": "dword_start_relative versus dword_end_relative remains a four-byte ambiguity until target-header structure is parsed",
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
                "exact_offset_origin_inferred": False,
                "canary_track_modified": False,
                "full_proprietary_payloads_exported": False,
            },
            "next_action": "Upload this report. Use repeated inbound-reference fan-in and target-window structure to decide whether the 11-dword island is a shared record template. Do not write G1E or infer brightness/censorship; if the start-versus-end origin remains ambiguous, continue only with a read-only target-header/section parser audit.",
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
    except Stage89Error as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print(json.dumps({"output_dir": str(output), "archive": str(archive) if archive else None, "summary": summary}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
