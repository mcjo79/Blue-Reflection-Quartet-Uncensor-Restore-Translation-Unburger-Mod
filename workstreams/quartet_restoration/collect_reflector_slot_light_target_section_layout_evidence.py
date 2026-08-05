#!/usr/bin/env python3
"""Resolve the focal G1E reference origin against a format-aware section header.

Stage 89 established repeated field-relative reference fan-in to two endpoints
and showed that the candidate and neutral 44-byte records become exact shared
templates after masking only the relocation field.  This read-only stage tests
whether the dword-start or dword-end interpretation lands on a reproducible
section-header layout.  It validates the stage-89 report, rehydrates only the
same four bounded effect containers, evaluates every inbound reference under
both origins, audits the target count/table-offset formula, and binds the two
shared 11-dword records to the validated header start.

Only technical metadata, integer values, offsets and SHA-256 hashes are
exported.  No G1E/G1EM, Elixir, PAK, registry or installed-game content is
written, and no brightness or censorship semantics are inferred.
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
from collections import defaultdict
from pathlib import Path, PurePosixPath
from typing import Any, Callable, Iterable, Mapping, Sequence

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT_DEFAULT = SCRIPT_DIR.parent.parent

TOOL_VERSION = "0.1.4"
REPORT_NAME = "BR_quartet_restoration_reflector_slot_light_target_section_layout_evidence.tar.zst"
REPORT_DIR = "reflector_slot_light_target_section_layout_evidence"
STAGE89_DIR = "reflector_slot_light_reference_target_header_evidence"
STAGE89_ARCHIVE = "BR_quartet_restoration_reflector_slot_light_reference_target_header_evidence.tar.zst"
STAGE88_DIR = "reflector_slot_light_record_boundary_residual_evidence"
STAGE88_ARCHIVE = "BR_quartet_restoration_reflector_slot_light_record_boundary_residual_evidence.tar.zst"
STAGE87_DIR = "reflector_slot_light_local_change_island_evidence"
STAGE87_ARCHIVE = "BR_quartet_restoration_reflector_slot_light_local_change_island_evidence.tar.zst"
STAGE79_DIR = "reflector_character_slot_render_member_evidence"
STAGE79_ARCHIVE = "BR_quartet_restoration_reflector_character_slot_render_member_evidence.tar.zst"
EXPECTED_PARENT_CONTAINERS = 4
EXPECTED_SIBLING_PAIRS = 540
EXPECTED_CLUSTER_MEMBERS = 4
EXPECTED_RESIDUAL_ROWS = 2
HEADER_DWORDS = 14
HEADER_BYTES = HEADER_DWORDS * 4
HEADER_FIXED_SIZE = 56
HEADER_VERSION = 0x00010000
RECORD_BYTES = 44
RELOCATION_DWORD = 10


class Stage90Error(RuntimeError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise Stage90Error(message)


def progress(message: str) -> None:
    print(f"[stage90] {message}", file=sys.stderr, flush=True)


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
            raise Stage90Error(f"missing required TSV: {path}")
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
        raise Stage90Error(f"invalid JSON {path}: {exc}") from exc
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


def dword(payload: bytes, offset: int) -> int:
    require(offset >= 0 and offset + 4 <= len(payload) and offset % 4 == 0, f"invalid dword offset {offset}")
    return int.from_bytes(payload[offset:offset + 4], "little")


def inbound_reference_offsets(payload: bytes, endpoint: int) -> list[int]:
    rows: list[int] = []
    for offset in range(0, len(payload) - 3, 4):
        value = int.from_bytes(payload[offset:offset + 4], "little")
        displacement = signed_i32(value)
        if displacement and offset + displacement == endpoint:
            rows.append(offset)
    return rows


def masked_record(payload: bytes, start: int, end: int, residual_offset: int) -> bytes:
    require(end - start == RECORD_BYTES, f"record length mismatch: {end - start}")
    require(start <= residual_offset <= end - 4 and residual_offset % 4 == 0, "residual outside record")
    value = bytearray(payload[start:end])
    relative = residual_offset - start
    value[relative:relative + 4] = b"\0\0\0\0"
    return bytes(value)


def validate_stage89(root: Path) -> dict[str, Any]:
    summary = load_json(root / "SUMMARY.json")
    require(summary.get("type") == "br_quartet_restoration_reflector_slot_light_reference_target_header_evidence_summary", "stage89 type mismatch")
    require(summary.get("tool_version") == "0.1.3", "stage89 tool version mismatch")
    require(parse_int(summary.get("sibling_G1E_G1EM_member_rows"), -1) == EXPECTED_SIBLING_PAIRS, "stage89 sibling count mismatch")
    require(parse_int(summary.get("residual_rows"), -1) == EXPECTED_RESIDUAL_ROWS, "stage89 residual count mismatch")
    require(parse_int(summary.get("reference_cluster_member_rows"), -1) == EXPECTED_CLUSTER_MEMBERS, "stage89 cluster-member count mismatch")
    require(parse_bool(summary.get("field_relative_base_family_supported")), "stage89 did not support field-relative base family")
    require(not parse_bool(summary.get("exact_field_start_vs_end_origin_resolved")), "stage89 unexpectedly resolved exact origin")
    require(parse_bool(summary.get("masked_record_template_exact_across_candidate_and_neutral")), "stage89 masked record template mismatch")
    require(parse_int(summary.get("prototype_candidate_rows"), -1) == 0, "stage89 unexpectedly authorized prototype")
    require(not parse_bool(summary.get("brightness_semantics_confirmed")), "stage89 unexpectedly confirmed brightness")
    require(not parse_bool(summary.get("censorship_semantics_confirmed")), "stage89 unexpectedly confirmed censorship")
    require(parse_int(summary.get("skipped_rows"), -1) == 0, "stage89 contains skipped rows")
    policy = summary.get("policy") or {}
    require(isinstance(policy, dict), "stage89 policy malformed")
    for field in ("installed_game_modified", "render_payload_written", "pak_repacked", "core_registry_modified", "profile_activated"):
        require(not parse_bool(policy.get(field)), f"stage89 performed forbidden action: {field}")
    return summary


def parse_section_header(payload: bytes, endpoint: int) -> dict[str, Any]:
    row: dict[str, Any] = {
        "endpoint": endpoint,
        "endpoint_aligned": endpoint % 4 == 0,
        "header_in_bounds": endpoint >= 0 and endpoint + HEADER_BYTES <= len(payload),
    }
    if not row["endpoint_aligned"] or not row["header_in_bounds"]:
        row.update({
            "layout_score": 0,
            "layout_check_count": 11,
            "exact_layout": False,
            "header_sha256": "",
            "count": -1,
            "declared_span": -1,
        })
        return row

    words = [int.from_bytes(payload[endpoint + i * 4:endpoint + i * 4 + 4], "little") for i in range(HEADER_DWORDS)]
    count = words[2]
    count_reasonable = 1 <= count <= 4096
    expected7 = HEADER_FIXED_SIZE + 4 * max(count - 1, 0)
    expected8 = HEADER_FIXED_SIZE + 8 * max(count - 1, 0)
    expected9 = HEADER_FIXED_SIZE + 12 * max(count - 1, 0)
    checks = {
        "reserved_zero": words[1] == 0,
        "triplet_count_equal": words[2] == words[3] == words[4],
        "count_reasonable": count_reasonable,
        "fixed_header_size_56": words[6] == HEADER_FIXED_SIZE,
        "table_boundary_1_formula": count_reasonable and words[7] == expected7,
        "table_boundary_2_formula": count_reasonable and words[8] == expected8,
        "table_boundary_3_formula": count_reasonable and words[9] == expected9,
        "table_boundaries_monotonic": words[6] <= words[7] <= words[8] <= words[9],
        "version_00010000": words[10] == HEADER_VERSION,
        "declared_span_contains_header": words[0] >= words[9] >= HEADER_FIXED_SIZE,
        "declared_span_in_bounds": endpoint + words[0] <= len(payload),
    }
    score = sum(bool(value) for value in checks.values())
    row.update({
        "layout_score": score,
        "layout_check_count": len(checks),
        "exact_layout": score == len(checks),
        "header_sha256": sha256(payload[endpoint:endpoint + HEADER_BYTES]),
        "declared_span": words[0],
        "declared_end": endpoint + words[0],
        "reserved_word": words[1],
        "count": count,
        "count_word_2": words[2],
        "count_word_3": words[3],
        "count_word_4": words[4],
        "mode_or_flag_word": words[5],
        "fixed_header_size": words[6],
        "table_boundary_1": words[7],
        "table_boundary_2": words[8],
        "table_boundary_3": words[9],
        "expected_table_boundary_1": expected7,
        "expected_table_boundary_2": expected8,
        "expected_table_boundary_3": expected9,
        "version_word_hex": f"0x{words[10]:08x}",
        **checks,
    })
    return row


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

    stage81 = load_module(project_root / "workstreams/quartet_restoration/collect_reflector_ringlight_control_callsite_evidence.py", "stage81_for_stage90")
    stage86 = load_module(project_root / "workstreams/quartet_restoration/collect_reflector_slot_light_shared_record_template_evidence.py", "stage86_for_stage90")

    progress("validating stage 79, 87, 88 and 89 reports")
    with tempfile.TemporaryDirectory(prefix="br-stage90-") as temporary_name:
        temporary = Path(temporary_name)
        stage89_root = locate(reports, STAGE89_DIR, STAGE89_ARCHIVE, temporary / "89")
        stage88_root = locate(reports, STAGE88_DIR, STAGE88_ARCHIVE, temporary / "88")
        stage87_root = locate(reports, STAGE87_DIR, STAGE87_ARCHIVE, temporary / "87")
        stage79_root = locate(reports, STAGE79_DIR, STAGE79_ARCHIVE, temporary / "79")
        summary89 = validate_stage89(stage89_root)
        summary79 = stage81.validate_stage79(stage79_root)

        cluster_seed_rows = read_tsv(stage89_root / "SLOT_LIGHT_REFERENCE_CLUSTER_SEEDS.tsv")
        cluster_audit_rows = read_tsv(stage89_root / "SLOT_LIGHT_REFERENCE_CLUSTER_AUDIT.tsv")
        masked_comparison_rows = read_tsv(stage89_root / "SLOT_LIGHT_MASKED_RECORD_TEMPLATE_COMPARISON.tsv")
        residual_rows = read_tsv(stage88_root / "SLOT_LIGHT_RESIDUAL_AUDIT.tsv")
        island_rows = read_tsv(stage87_root / "SLOT_LIGHT_LOCAL_CHANGE_ISLANDS.tsv")
        require(len(cluster_audit_rows) == EXPECTED_CLUSTER_MEMBERS, "stage89 cluster audit count mismatch")
        require(len(masked_comparison_rows) == 1 and parse_bool(masked_comparison_rows[0].get("candidate_neutral_joint_masked_equal")), "stage89 masked comparison gate failed")
        require(len(residual_rows) == EXPECTED_RESIDUAL_ROWS and len(island_rows) == EXPECTED_RESIDUAL_ROWS, "residual/island prerequisite count mismatch")

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

        seeds_by_member: dict[tuple[str, str], list[dict[str, str]]] = defaultdict(list)
        for row in cluster_seed_rows:
            seeds_by_member[stable_key(row.get("normalized_path", ""), row.get("member_key", ""))].append(row)
        require(len(seeds_by_member) == EXPECTED_CLUSTER_MEMBERS, "cluster seed member count mismatch")

        header_layout_rows: list[dict[str, Any]] = []
        formula_rows: list[dict[str, Any]] = []
        origin_rows: list[dict[str, Any]] = []
        member_header_by_side: dict[tuple[tuple[str, str], str], dict[str, Any]] = {}

        for member_index, (key, seeds) in enumerate(sorted(seeds_by_member.items()), 1):
            pair = pair_by_key.get(key)
            require(pair is not None, f"missing cluster payload pair: {key}")
            endpoint = parse_int(seeds[0].get("endpoint"), -1)
            require(endpoint >= 0 and all(parse_int(row.get("endpoint"), -2) == endpoint for row in seeds), f"cluster endpoint disagreement: {pair['member_name']}")
            progress(f"auditing section header {member_index}/{len(seeds_by_member)}: {pair['member_name']}")
            for side in ("source", "target"):
                payload = pair[f"{side}_payload"]
                offsets = inbound_reference_offsets(payload, endpoint)
                start_header = parse_section_header(payload, endpoint)
                end_header = parse_section_header(payload, endpoint + 4)
                member_header_by_side[(key, side)] = start_header
                header_layout_rows.append({
                    "cluster_role": seeds[0].get("cluster_role", ""),
                    "normalized_path": pair["normalized_path"],
                    "member_key": pair["member_key"],
                    "member_name": pair["member_name"],
                    "side": side,
                    **start_header,
                    "dword_end_shifted_layout_score": end_header["layout_score"],
                    "dword_end_shifted_exact_layout": end_header["exact_layout"],
                    "inbound_reference_rows": len(offsets),
                })
                formula_rows.append({
                    "cluster_role": seeds[0].get("cluster_role", ""),
                    "member_name": pair["member_name"],
                    "side": side,
                    "endpoint": endpoint,
                    "count": start_header.get("count", -1),
                    "fixed_header_size": start_header.get("fixed_header_size", -1),
                    "table_boundary_1": start_header.get("table_boundary_1", -1),
                    "expected_table_boundary_1": start_header.get("expected_table_boundary_1", -1),
                    "table_boundary_1_formula": start_header.get("table_boundary_1_formula", False),
                    "table_boundary_2": start_header.get("table_boundary_2", -1),
                    "expected_table_boundary_2": start_header.get("expected_table_boundary_2", -1),
                    "table_boundary_2_formula": start_header.get("table_boundary_2_formula", False),
                    "table_boundary_3": start_header.get("table_boundary_3", -1),
                    "expected_table_boundary_3": start_header.get("expected_table_boundary_3", -1),
                    "table_boundary_3_formula": start_header.get("table_boundary_3_formula", False),
                    "formula_exact": all(parse_bool(start_header.get(field)) for field in ("table_boundary_1_formula", "table_boundary_2_formula", "table_boundary_3_formula")),
                })
                for reference_offset in offsets:
                    value = dword(payload, reference_offset)
                    start_endpoint = reference_offset + signed_i32(value)
                    end_endpoint = reference_offset + 4 + signed_i32(value)
                    start_candidate = parse_section_header(payload, start_endpoint)
                    end_candidate = parse_section_header(payload, end_endpoint)
                    origin_rows.append({
                        "cluster_role": seeds[0].get("cluster_role", ""),
                        "normalized_path": pair["normalized_path"],
                        "member_key": pair["member_key"],
                        "member_name": pair["member_name"],
                        "side": side,
                        "reference_offset": reference_offset,
                        "reference_u32_hex": f"0x{value:08x}",
                        "reference_i32": signed_i32(value),
                        "dword_start_endpoint": start_endpoint,
                        "dword_end_endpoint": end_endpoint,
                        "dword_start_layout_score": start_candidate["layout_score"],
                        "dword_start_exact_layout": start_candidate["exact_layout"],
                        "dword_end_layout_score": end_candidate["layout_score"],
                        "dword_end_exact_layout": end_candidate["exact_layout"],
                        "origin_discrimination": "dword_start_only" if start_candidate["exact_layout"] and not end_candidate["exact_layout"] else "ambiguous_or_failed",
                    })

        start_exact_rows = sum(parse_bool(row.get("dword_start_exact_layout")) for row in origin_rows)
        end_exact_rows = sum(parse_bool(row.get("dword_end_exact_layout")) for row in origin_rows)
        all_headers_exact = all(parse_bool(row.get("exact_layout")) for row in header_layout_rows)
        all_formulas_exact = all(parse_bool(row.get("formula_exact")) for row in formula_rows)
        exact_origin_resolved = bool(origin_rows) and start_exact_rows == len(origin_rows) and end_exact_rows == 0 and all_headers_exact

        island_by_role = {row["island_role"]: row for row in island_rows}
        residual_by_role = {row["island_role"]: row for row in residual_rows}
        binding_rows: list[dict[str, Any]] = []
        masked_by_role: dict[str, tuple[bytes, bytes]] = {}
        for role in ("candidate_ringlight", "neutral_control"):
            residual = residual_by_role[role]
            island = island_by_role[role]
            key = stable_key(residual.get("normalized_path", ""), residual.get("member_key", ""))
            pair = pair_by_key.get(key)
            require(pair is not None, f"missing focal residual pair: {key}")
            source_start = parse_int(island.get("source_start"), -1)
            source_end = parse_int(island.get("source_end_exclusive"), -1)
            target_start = parse_int(island.get("target_start"), -1)
            target_end = parse_int(island.get("target_end_exclusive"), -1)
            source_offset = parse_int(residual.get("source_offset"), -1)
            target_offset = parse_int(residual.get("target_offset"), -1)
            source_value = dword(pair["source_payload"], source_offset)
            target_value = dword(pair["target_payload"], target_offset)
            source_endpoint = source_offset + signed_i32(source_value)
            target_endpoint = target_offset + signed_i32(target_value)
            source_header = parse_section_header(pair["source_payload"], source_endpoint)
            target_header = parse_section_header(pair["target_payload"], target_endpoint)
            source_masked = masked_record(pair["source_payload"], source_start, source_end, source_offset)
            target_masked = masked_record(pair["target_payload"], target_start, target_end, target_offset)
            masked_by_role[role] = (source_masked, target_masked)
            binding_rows.append({
                "island_role": role,
                "member_name": pair["member_name"],
                "record_length": source_end - source_start,
                "relocation_relative_dword": (source_offset - source_start) // 4,
                "source_header_endpoint": source_endpoint,
                "target_header_endpoint": target_endpoint,
                "source_header_exact_layout": source_header["exact_layout"],
                "target_header_exact_layout": target_header["exact_layout"],
                "source_record_masked_sha256": sha256(source_masked),
                "target_record_masked_sha256": sha256(target_masked),
                "source_target_masked_equal": source_masked == target_masked,
                "shared_non_relocation_transition_count": 2,
                "binding_classification": "shared_11_dword_record_with_dword_start_relative_section_header_reference",
            })

        candidate_source, candidate_target = masked_by_role["candidate_ringlight"]
        neutral_source, neutral_target = masked_by_role["neutral_control"]
        shared_template_exact = candidate_source == neutral_source and candidate_target == neutral_target
        require(shared_template_exact, "shared masked record template no longer exact")

        origin_summary_rows = [{
            "model": "dword_start_relative",
            "reference_rows": len(origin_rows),
            "exact_header_rows": start_exact_rows,
            "exact_header_rate": f"{start_exact_rows}/{len(origin_rows)}",
            "header_formula_member_side_rows": sum(parse_bool(row.get("formula_exact")) for row in formula_rows),
            "model_classification": "resolved_section_header_start" if exact_origin_resolved else "not_resolved",
        }, {
            "model": "dword_end_relative",
            "reference_rows": len(origin_rows),
            "exact_header_rows": end_exact_rows,
            "exact_header_rate": f"{end_exact_rows}/{len(origin_rows)}",
            "header_formula_member_side_rows": 0,
            "model_classification": "rejected_shifted_non_header" if exact_origin_resolved else "not_resolved",
        }]

        source_counts = {row["cluster_role"]: parse_int(row.get("count"), -1) for row in header_layout_rows if row["side"] == "source" and row["cluster_role"] == "candidate_ringlight"}
        target_counts = {row["cluster_role"]: parse_int(row.get("count"), -1) for row in header_layout_rows if row["side"] == "target" and row["cluster_role"] == "candidate_ringlight"}
        candidate_count_delta = target_counts.get("candidate_ringlight", -1) - source_counts.get("candidate_ringlight", -1)

        output_dir = reports / REPORT_DIR
        output_dir.mkdir(parents=True, exist_ok=True)
        write_tsv(output_dir / "SLOT_LIGHT_SECTION_HEADER_LAYOUT.tsv", [
            "cluster_role", "normalized_path", "member_key", "member_name", "side", "endpoint", "endpoint_aligned", "header_in_bounds",
            "header_sha256", "declared_span", "declared_end", "reserved_word", "count", "count_word_2", "count_word_3", "count_word_4",
            "mode_or_flag_word", "fixed_header_size", "table_boundary_1", "table_boundary_2", "table_boundary_3", "version_word_hex",
            "layout_score", "layout_check_count", "exact_layout", "dword_end_shifted_layout_score", "dword_end_shifted_exact_layout",
            "inbound_reference_rows",
        ], header_layout_rows)
        write_tsv(output_dir / "SLOT_LIGHT_SECTION_HEADER_TABLE_FORMULA.tsv", [
            "cluster_role", "member_name", "side", "endpoint", "count", "fixed_header_size", "table_boundary_1", "expected_table_boundary_1",
            "table_boundary_1_formula", "table_boundary_2", "expected_table_boundary_2", "table_boundary_2_formula", "table_boundary_3",
            "expected_table_boundary_3", "table_boundary_3_formula", "formula_exact",
        ], formula_rows)
        write_tsv(output_dir / "SLOT_LIGHT_REFERENCE_ORIGIN_DISCRIMINATION.tsv", [
            "cluster_role", "normalized_path", "member_key", "member_name", "side", "reference_offset", "reference_u32_hex", "reference_i32",
            "dword_start_endpoint", "dword_end_endpoint", "dword_start_layout_score", "dword_start_exact_layout", "dword_end_layout_score",
            "dword_end_exact_layout", "origin_discrimination",
        ], origin_rows)
        write_tsv(output_dir / "SLOT_LIGHT_REFERENCE_ORIGIN_SUMMARY.tsv", [
            "model", "reference_rows", "exact_header_rows", "exact_header_rate", "header_formula_member_side_rows", "model_classification",
        ], origin_summary_rows)
        write_tsv(output_dir / "SLOT_LIGHT_SHARED_RECORD_HEADER_BINDING.tsv", [
            "island_role", "member_name", "record_length", "relocation_relative_dword", "source_header_endpoint", "target_header_endpoint",
            "source_header_exact_layout", "target_header_exact_layout", "source_record_masked_sha256", "target_record_masked_sha256",
            "source_target_masked_equal", "shared_non_relocation_transition_count", "binding_classification",
        ], binding_rows)
        write_tsv(output_dir / "SLOT_LIGHT_TARGET_SECTION_LAYOUT_SKIPPED.tsv", ["scope", "reason"], [])

        if exact_origin_resolved:
            format_classification = "dword_start_relative_section_header_reference_confirmed"
        else:
            format_classification = "field_relative_reference_supported_exact_origin_still_unresolved"
        if shared_template_exact:
            transition_scope = "cross_context_shared_record_template_transition_not_candidate_specific"
        else:
            transition_scope = "record_template_scope_unresolved"

        summary = {
            "type": "br_quartet_restoration_reflector_slot_light_target_section_layout_evidence_summary",
            "format_version": 1,
            "tool_version": TOOL_VERSION,
            "source_stage89_tool_version": summary89.get("tool_version"),
            "source_stage79_tool_version": summary79.get("tool_version"),
            "status": "stage89_shared_record_template_bound_to_format_aware_section_headers_exact_reference_origin_audited_without_semantic_write_authorization",
            "sibling_G1E_G1EM_member_rows": len(all_pairs),
            "reference_cluster_member_rows": len(seeds_by_member),
            "reference_origin_rows": len(origin_rows),
            "dword_start_exact_header_rows": start_exact_rows,
            "dword_end_exact_header_rows": end_exact_rows,
            "section_header_member_side_rows": len(header_layout_rows),
            "section_header_exact_layout_rows": sum(parse_bool(row.get("exact_layout")) for row in header_layout_rows),
            "section_header_formula_rows": len(formula_rows),
            "section_header_formula_exact_rows": sum(parse_bool(row.get("formula_exact")) for row in formula_rows),
            "exact_field_origin_resolved": exact_origin_resolved,
            "resolved_field_origin": "dword_start_relative" if exact_origin_resolved else "unresolved",
            "shared_record_header_binding_rows": len(binding_rows),
            "masked_record_template_exact_across_candidate_and_neutral": shared_template_exact,
            "shared_transition_candidate_specific": False if shared_template_exact else None,
            "candidate_header_count_delta": candidate_count_delta,
            "format_classification": format_classification,
            "transition_scope_classification": transition_scope,
            "prototype_candidate_rows": 0,
            "brightness_semantics_confirmed": False,
            "censorship_semantics_confirmed": False,
            "skipped_rows": 0,
            "parameters": {
                "header_dwords": HEADER_DWORDS,
                "header_fixed_size": HEADER_FIXED_SIZE,
                "header_version": f"0x{HEADER_VERSION:08x}",
                "record_length_bytes": RECORD_BYTES,
                "relocation_relative_dword": RELOCATION_DWORD,
                "table_boundary_formula": "boundary_k = 56 + (4*k)*(count-1), k in 1..3",
                "dword_start_equation": "field_offset + signed_i32(field_value) == section_header_start",
                "dword_end_equation": "field_offset + 4 + signed_i32(field_value) == shifted_non_header_candidate",
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
                "record_numeric_leaf_semantics_inferred": False,
                "canary_track_modified": False,
                "full_proprietary_payloads_exported": False,
            },
            "next_action": "Upload this report. If the dword-start header layout is confirmed, treat the two 150 -> 75 leaves as a shared cross-context record-template transition rather than a PC02-specific candidate. Continue only with a read-only table-cardinality/record-role audit if technical semantics are still needed; do not write G1E or infer brightness/censorship.",
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
    parser.add_argument("--workspace-root", type=Path)
    parser.add_argument("--report-root", type=Path)
    parser.add_argument("--rules-file", type=Path)
    parser.add_argument("--maximum-earc-bytes", type=int, default=512 * 1024 * 1024)
    parser.add_argument("--no-report-archive", action="store_true")
    args = parser.parse_args(argv)
    try:
        output, archive, summary = build_report(
            args.project_root,
            create_archive=not args.no_report_archive,
            workspace_root=args.workspace_root,
            report_root=args.report_root,
            rules_file=args.rules_file,
            maximum_earc_bytes=args.maximum_earc_bytes,
        )
    except Stage90Error as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print(f"Report directory: {output}")
    if archive:
        print(f"Report: {archive}")
    print(f"Exact field origin resolved: {summary['exact_field_origin_resolved']}")
    print(f"Transition candidate-specific: {summary['shared_transition_candidate_specific']}")
    print(f"Prototype candidates: {summary['prototype_candidate_rows']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
