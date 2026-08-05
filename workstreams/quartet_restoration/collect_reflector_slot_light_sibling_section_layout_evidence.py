#!/usr/bin/env python3
"""Audit section-header modes and section-anchored layout of stage-104 sibling records.

Stage 104 expanded one exact paired-float record body to 1,814 format-valid
occurrences in a bounded 540-pair G1E/G1EM corpus.  This read-only stage
rehydrates the same four parent effect containers, revalidates every exported
occurrence, and records the exact section-header mode/flag, declared span,
table boundaries, occurrence ordinal, and section-anchored record geometry.

The stage is structural only.  It cannot assign brightness/intensity or any
other value-domain meaning and must not write G1E/G1EM, create a prototype,
modify profiles or registry, repack a PAK, or modify the installed game.
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
from collections import defaultdict
from pathlib import Path, PurePosixPath
from typing import Any, Callable, Iterable, Mapping, Sequence

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT_DEFAULT = SCRIPT_DIR.parent.parent
TOOL_VERSION = "0.1.23"
REPORT_NAME = "BR_quartet_restoration_reflector_slot_light_sibling_section_layout_evidence.tar.zst"
REPORT_DIR = "reflector_slot_light_sibling_section_layout_evidence"
STAGE104_DIR = "reflector_slot_light_sibling_template_expansion_evidence"
STAGE104_ARCHIVE = "BR_quartet_restoration_reflector_slot_light_sibling_template_expansion_evidence.tar.zst"
STAGE108_DIR = "br1_official_source_retirement_closure_evidence"
STAGE108_ARCHIVE = "BR_quartet_restoration_br1_official_source_retirement_closure_evidence.tar.zst"
STAGE79_DIR = "reflector_character_slot_render_member_evidence"
STAGE79_ARCHIVE = "BR_quartet_restoration_reflector_character_slot_render_member_evidence.tar.zst"
EXPECTED_OCCURRENCES = 1814
EXPECTED_KNOWN = 21
EXPECTED_ADDITIONAL = 1793
EXPECTED_PAIRS = 540
EXPECTED_CONTAINERS = 4
RECORD_BYTES = 44
BODY_START = 8
BODY_END = 40


class Stage109Error(RuntimeError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise Stage109Error(message)


def progress(message: str) -> None:
    print(f"[stage109] {message}", file=sys.stderr, flush=True)


def parse_int(value: Any, default: int = 0) -> int:
    try:
        text = str(value).strip()
        return int(text, 16) if text.casefold().startswith("0x") else int(text)
    except (TypeError, ValueError):
        return default


def parse_bool(value: Any) -> bool:
    return str(value).strip().casefold() in {"1", "true", "yes", "y"}


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def stable_key(path: str, member_key: str) -> tuple[str, str]:
    return path.casefold(), member_key.casefold()


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
        raise Stage109Error(f"invalid JSON {path}: {exc}") from exc
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


def load_module(path: Path, name: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    require(spec is not None and spec.loader is not None, f"cannot load module: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def validate_stage104(root: Path) -> dict[str, Any]:
    summary = load_json(root / "SUMMARY.json")
    require(summary.get("type") == "br_quartet_restoration_reflector_slot_light_sibling_template_expansion_evidence_summary", "stage104 type mismatch")
    require(summary.get("tool_version") == "0.1.18", "stage104 tool version mismatch")
    require(parse_int(summary.get("sibling_G1E_G1EM_pair_rows"), -1) == EXPECTED_PAIRS, "stage104 pair count mismatch")
    require(parse_int(summary.get("format_valid_sibling_occurrence_rows"), -1) == EXPECTED_OCCURRENCES, "stage104 occurrence count mismatch")
    require(parse_int(summary.get("known_stage101_occurrence_rows"), -1) == EXPECTED_KNOWN, "stage104 known occurrence count mismatch")
    require(parse_int(summary.get("additional_sibling_occurrence_rows"), -1) == EXPECTED_ADDITIONAL, "stage104 additional occurrence count mismatch")
    require(not parse_bool(summary.get("technical_leaf_domain_semantics_resolved")), "stage104 unexpectedly resolved domain semantics")
    require(parse_int(summary.get("prototype_candidate_rows"), -1) == 0, "stage104 unexpectedly authorized prototype")
    require(parse_int(summary.get("skipped_rows"), -1) == 0, "stage104 contains skipped rows")
    return summary


def validate_stage108(root: Path) -> dict[str, Any]:
    summary = load_json(root / "SUMMARY.json")
    require(summary.get("type") == "br_quartet_restoration_br1_official_source_retirement_closure_evidence_summary", "stage108 type mismatch")
    require(summary.get("tool_version") == "0.1.22", "stage108 tool version mismatch")
    require(summary.get("status") == "underscore_archive_retirement_closed", "stage108 retirement is not closed")
    require(parse_bool(summary.get("retirement_complete")), "stage108 retirement incomplete")
    require(parse_int(summary.get("official_archives_verified"), -1) == 4, "stage108 official archive verification mismatch")
    require(parse_int(summary.get("underscore_archives_absent"), -1) == 4, "stage108 underscore archive absence mismatch")
    require(parse_int(summary.get("registered_profiles_affected"), -1) == 0, "stage108 unexpectedly affects registered profiles")
    require(parse_bool(summary.get("stage104_slot_light_evidence_independent")), "stage108 did not preserve stage104 independence")
    require(not parse_bool(summary.get("underscore_archives_required_for_normal_workflow")), "stage108 still requires underscore archives")
    return summary


def finite_equal_leaf(payload: bytes, start: int) -> tuple[int, float]:
    require(start >= 0 and start + RECORD_BYTES <= len(payload), f"record out of bounds at {start}")
    u0, u1 = struct.unpack_from("<II", payload, start)
    require(u0 == u1, f"paired leaf mismatch at {start}")
    value = struct.unpack("<f", struct.pack("<I", u0))[0]
    require(math.isfinite(value), f"non-finite paired leaf at {start}")
    return u0, value


def format_float(value: float) -> str:
    return f"{value:.9g}"


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

    stage81 = load_module(project_root / "workstreams/quartet_restoration/collect_reflector_ringlight_control_callsite_evidence.py", "stage81_for_stage109")
    stage86 = load_module(project_root / "workstreams/quartet_restoration/collect_reflector_slot_light_shared_record_template_evidence.py", "stage86_for_stage109")
    stage90 = load_module(project_root / "workstreams/quartet_restoration/collect_reflector_slot_light_target_section_layout_evidence.py", "stage90_for_stage109")

    progress("validating stage 79, 104 and 108 reports")
    with tempfile.TemporaryDirectory(prefix="br-stage109-") as temporary_name:
        temporary = Path(temporary_name)
        stage104_root = locate(reports, STAGE104_DIR, STAGE104_ARCHIVE, temporary / "104")
        stage108_root = locate(reports, STAGE108_DIR, STAGE108_ARCHIVE, temporary / "108")
        stage79_root = locate(reports, STAGE79_DIR, STAGE79_ARCHIVE, temporary / "79")
        summary104 = validate_stage104(stage104_root)
        summary108 = validate_stage108(stage108_root)
        stage81.validate_stage79(stage79_root)

        source_rows = read_tsv(stage104_root / "SLOT_LIGHT_SIBLING_TEMPLATE_OCCURRENCES.tsv")
        require(len(source_rows) == EXPECTED_OCCURRENCES, "stage104 occurrence table length mismatch")
        identities = {
            (str(row.get("normalized_path", "")).casefold(), str(row.get("member_key", "")).casefold(), str(row.get("side", "")), parse_int(row.get("record_start"), -1))
            for row in source_rows
        }
        require(len(identities) == EXPECTED_OCCURRENCES, "stage104 occurrence identities are not unique")

        parent_scope = stage81.select_parent_scope(stage79_root)
        actual_rules = rules_file or project_root / "titles/blue_reflection/modules/quartet_restoration/mappings/effect_material_rules.tsv"
        loader = container_loader or stage81.load_parent_containers
        progress("rehydrating four bounded parent effect containers")
        containers, loader_skipped = loader(
            scope_rows=parent_scope,
            workspace_root=workspace,
            report_root=reports,
            rules_file=actual_rules,
            maximum_earc_bytes=maximum_earc_bytes,
        )
        require(not loader_skipped, f"parent container loader skipped {len(loader_skipped)} rows")
        require(len(containers) == EXPECTED_CONTAINERS, f"expected {EXPECTED_CONTAINERS} parent containers, found {len(containers)}")
        pair_by_key, all_pairs = stage86.index_pairs(containers)
        require(len(all_pairs) == EXPECTED_PAIRS, f"expected {EXPECTED_PAIRS} sibling pairs, found {len(all_pairs)}")

        occurrence_rows: list[dict[str, Any]] = []
        grouped: dict[tuple[str, str, str, int], list[dict[str, Any]]] = defaultdict(list)
        skipped_rows: list[dict[str, Any]] = []
        for index, row in enumerate(source_rows, start=1):
            if index == 1 or index % 200 == 0 or index == len(source_rows):
                progress(f"revalidating occurrence {index}/{len(source_rows)}")
            path = str(row.get("normalized_path", "")).casefold()
            member_key = str(row.get("member_key", "")).casefold()
            side = str(row.get("side", ""))
            pair = pair_by_key.get(stable_key(path, member_key))
            require(pair is not None, f"stage104 member missing from bounded corpus: {path} {member_key}")
            payload = bytes(pair.get(f"{side}_payload") or b"")
            start = parse_int(row.get("record_start"), -1)
            endpoint = parse_int(row.get("normalized_endpoint"), -1)
            leaf_u32, leaf_value = finite_equal_leaf(payload, start)
            require(f"0x{leaf_u32:08x}" == str(row.get("leaf_u32_hex", "")).casefold(), f"leaf bits changed at {path} {member_key} {side} {start}")
            require(format_float(leaf_value) == str(row.get("paired_float_value", "")), f"leaf value changed at {path} {member_key} {side} {start}")
            require(sha256(payload[start:start + RECORD_BYTES]) == str(row.get("record_sha256", "")), f"record hash changed at {path} {member_key} {side} {start}")
            require(sha256(payload[start + BODY_START:start + BODY_END]) == str(row.get("non_leaf_body_sha256", "")), f"body hash changed at {path} {member_key} {side} {start}")
            header = dict(stage90.parse_section_header(payload, endpoint))
            require(parse_bool(header.get("exact_layout")), f"section header no longer exact at {path} {member_key} {side} {endpoint}")
            require(str(header.get("header_sha256", "")) == str(row.get("section_header_sha256", "")), f"section header hash changed at {path} {member_key} {side} {endpoint}")
            require(parse_int(header.get("count"), -1) == parse_int(row.get("section_count"), -2), "section count changed")
            require(parse_int(header.get("declared_span"), -1) == parse_int(row.get("section_declared_span"), -2), "declared span changed")

            rel = start - endpoint
            record_end_rel = rel + RECORD_BYTES
            declared_span = parse_int(header.get("declared_span"), -1)
            boundary3 = parse_int(header.get("table_boundary_3"), -1)
            require(rel >= 0 and record_end_rel <= declared_span, f"record outside declared section span at {path} {member_key} {side} {start}")
            enriched = {
                **row,
                "section_mode_or_flag_word": parse_int(header.get("mode_or_flag_word"), -1),
                "section_mode_or_flag_hex": f"0x{parse_int(header.get('mode_or_flag_word'), 0):08x}",
                "section_declared_end": parse_int(header.get("declared_end"), -1),
                "section_table_boundary_1": parse_int(header.get("table_boundary_1"), -1),
                "section_table_boundary_2": parse_int(header.get("table_boundary_2"), -1),
                "section_table_boundary_3": boundary3,
                "record_relative_offset": rel,
                "record_end_relative_offset": record_end_rel,
                "distance_after_table_boundary_3": rel - boundary3,
                "declared_tail_bytes_after_record": declared_span - record_end_rel,
                "record_inside_declared_span": True,
            }
            occurrence_rows.append(enriched)
            grouped[(path, member_key, side, endpoint)].append(enriched)

        section_rows: list[dict[str, Any]] = []
        for key, rows in sorted(grouped.items()):
            rows.sort(key=lambda item: parse_int(item.get("record_start"), -1))
            starts = [parse_int(item.get("record_start"), -1) for item in rows]
            relative_offsets = [parse_int(item.get("record_relative_offset"), -1) for item in rows]
            values = [str(item.get("paired_float_value", "")) for item in rows]
            first = rows[0]
            count = parse_int(first.get("section_count"), -1)
            for ordinal, item in enumerate(rows):
                previous_gap = "" if ordinal == 0 else starts[ordinal] - starts[ordinal - 1]
                next_gap = "" if ordinal + 1 == len(rows) else starts[ordinal + 1] - starts[ordinal]
                item.update({
                    "template_ordinal_within_section": ordinal,
                    "template_occurrences_in_section": len(rows),
                    "template_coverage_of_section_count": "full" if len(rows) == count else "partial",
                    "previous_template_gap_bytes": previous_gap,
                    "next_template_gap_bytes": next_gap,
                })
            vector_text = ";".join(str(value) for value in relative_offsets)
            exact_signature_material = "|".join([
                str(first.get("section_mode_or_flag_word")), str(count), str(first.get("section_declared_span")), vector_text,
            ]).encode("utf-8")
            section_rows.append({
                "normalized_path": key[0],
                "member_key": key[1],
                "member_name": first.get("member_name", ""),
                "side": key[2],
                "technical_member_role": first.get("technical_member_role", ""),
                "character_slot": first.get("character_slot", ""),
                "normalized_endpoint": key[3],
                "section_mode_or_flag_word": first.get("section_mode_or_flag_word", ""),
                "section_mode_or_flag_hex": first.get("section_mode_or_flag_hex", ""),
                "section_count": count,
                "section_declared_span": first.get("section_declared_span", ""),
                "section_table_boundary_1": first.get("section_table_boundary_1", ""),
                "section_table_boundary_2": first.get("section_table_boundary_2", ""),
                "section_table_boundary_3": first.get("section_table_boundary_3", ""),
                "template_occurrences_in_section": len(rows),
                "template_coverage_of_section_count": "full" if len(rows) == count else "partial",
                "template_relative_offsets": vector_text,
                "template_values_in_order": ";".join(values),
                "first_template_relative_offset": relative_offsets[0],
                "last_template_end_relative_offset": relative_offsets[-1] + RECORD_BYTES,
                "declared_tail_after_last_template": parse_int(first.get("section_declared_span"), -1) - (relative_offsets[-1] + RECORD_BYTES),
                "exact_section_anchored_layout_sha256": sha256(exact_signature_material),
                "classification": "full_template_coverage_section" if len(rows) == count else "partial_template_coverage_section",
            })

        occurrence_rows.sort(key=lambda item: (str(item["normalized_path"]), str(item["member_key"]), str(item["side"]), parse_int(item["record_start"], -1)))
        section_rows.sort(key=lambda item: (str(item["normalized_path"]), str(item["member_key"]), str(item["side"]), parse_int(item["normalized_endpoint"], -1)))

        mode_groups: dict[int, list[dict[str, Any]]] = defaultdict(list)
        value_groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for row in occurrence_rows:
            mode_groups[parse_int(row.get("section_mode_or_flag_word"), -1)].append(row)
            value_groups[str(row.get("paired_float_value", ""))].append(row)

        mode_rows = []
        for mode, rows in sorted(mode_groups.items()):
            mode_rows.append({
                "section_mode_or_flag_word": mode,
                "section_mode_or_flag_hex": f"0x{mode & 0xffffffff:08x}",
                "occurrence_rows": len(rows),
                "section_rows": len({(r["normalized_path"], r["member_key"], r["side"], r["normalized_endpoint"]) for r in rows}),
                "member_rows": len({(r["normalized_path"], r["member_key"]) for r in rows}),
                "paired_values": ";".join(sorted({str(r["paired_float_value"]) for r in rows}, key=float)),
                "paired_value_rows": len({str(r["paired_float_value"]) for r in rows}),
                "section_counts": ";".join(str(v) for v in sorted({parse_int(r["section_count"], -1) for r in rows})),
                "declared_span_min": min(parse_int(r["section_declared_span"], -1) for r in rows),
                "declared_span_max": max(parse_int(r["section_declared_span"], -1) for r in rows),
                "technical_member_roles": ";".join(sorted({str(r["technical_member_role"]) for r in rows})),
                "classification": "mode_flag_shared_by_multiple_values" if len({str(r["paired_float_value"]) for r in rows}) > 1 else "single_observed_value_in_bounded_corpus",
            })

        value_rows = []
        for value, rows in sorted(value_groups.items(), key=lambda item: float(item[0])):
            modes = {parse_int(r.get("section_mode_or_flag_word"), -1) for r in rows}
            layout_sigs = {
                next(s["exact_section_anchored_layout_sha256"] for s in section_rows if s["normalized_path"] == r["normalized_path"] and s["member_key"] == r["member_key"] and s["side"] == r["side"] and parse_int(s["normalized_endpoint"], -1) == parse_int(r["normalized_endpoint"], -2))
                for r in rows
            }
            value_rows.append({
                "paired_float_value": value,
                "occurrence_rows": len(rows),
                "member_rows": len({(r["normalized_path"], r["member_key"]) for r in rows}),
                "mode_flag_rows": len(modes),
                "mode_flags": ";".join(f"0x{mode & 0xffffffff:08x}" for mode in sorted(modes)),
                "section_count_rows": len({parse_int(r["section_count"], -1) for r in rows}),
                "section_counts": ";".join(str(v) for v in sorted({parse_int(r["section_count"], -1) for r in rows})),
                "declared_span_rows": len({parse_int(r["section_declared_span"], -1) for r in rows}),
                "declared_span_min": min(parse_int(r["section_declared_span"], -1) for r in rows),
                "declared_span_max": max(parse_int(r["section_declared_span"], -1) for r in rows),
                "section_anchored_layout_rows": len(layout_sigs),
                "technical_member_roles": ";".join(sorted({str(r["technical_member_role"]) for r in rows})),
                "classification": "value_crosses_multiple_section_modes" if len(modes) > 1 else "single_observed_section_mode",
            })

        member_side_groups: dict[tuple[str, str], dict[str, list[dict[str, Any]]]] = defaultdict(lambda: {"source": [], "target": []})
        for row in section_rows:
            member_side_groups[(str(row["normalized_path"]), str(row["member_key"]))][str(row["side"])].append(row)
        comparison_rows = []
        for (path, member_key), sides in sorted(member_side_groups.items()):
            source_signatures = {str(row["exact_section_anchored_layout_sha256"]) for row in sides["source"]}
            target_signatures = {str(row["exact_section_anchored_layout_sha256"]) for row in sides["target"]}
            comparison_rows.append({
                "normalized_path": path,
                "member_key": member_key,
                "source_section_rows": len(sides["source"]),
                "target_section_rows": len(sides["target"]),
                "exact_layout_signatures_shared": len(source_signatures & target_signatures),
                "source_only_layout_signatures": len(source_signatures - target_signatures),
                "target_only_layout_signatures": len(target_signatures - source_signatures),
                "classification": "exact_section_layout_multiset_stable" if source_signatures == target_signatures else "section_layout_signature_changed_or_reordered",
            })

        values_crossing_modes = sum(parse_int(row.get("mode_flag_rows"), 0) > 1 for row in value_rows)
        modes_covering_multiple_values = sum(parse_int(row.get("paired_value_rows"), 0) > 1 for row in mode_rows)
        full_sections = sum(str(row.get("template_coverage_of_section_count")) == "full" for row in section_rows)
        decision_rows = [
            {"question": "were all stage104 occurrences revalidated against rehydrated payloads", "answer": True, "classification": "1814_of_1814_exactly_revalidated"},
            {"question": "is stage104 independent of retired underscore archives", "answer": True, "classification": "stage108_retirement_closed_official_sources_only"},
            {"question": "do paired values map one-to-one to section mode flags", "answer": values_crossing_modes == 0 and modes_covering_multiple_values == 0, "classification": "one_to_one_not_established" if values_crossing_modes or modes_covering_multiple_values else "one_to_one_within_bounded_corpus_only"},
            {"question": "does section layout resolve brightness intensity or censorship semantics", "answer": False, "classification": "format_and_anchored_geometry_only"},
            {"question": "does this authorize G1E write or prototype", "answer": False, "classification": "evidence_only_no_write"},
        ]

        output = reports / REPORT_DIR
        if output.exists():
            import shutil
            shutil.rmtree(output)
        output.mkdir(parents=True)
        write_tsv(output / "SLOT_LIGHT_SIBLING_SECTION_LAYOUT_OCCURRENCES.tsv", [
            "normalized_path", "member_key", "member_name", "side", "technical_member_role", "bounded_name_scope", "character_slot",
            "record_start", "normalized_endpoint", "paired_float_value", "known_stage101_occurrence", "additional_sibling_occurrence",
            "section_mode_or_flag_word", "section_mode_or_flag_hex", "section_count", "section_declared_span", "section_declared_end",
            "section_table_boundary_1", "section_table_boundary_2", "section_table_boundary_3", "record_relative_offset",
            "record_end_relative_offset", "distance_after_table_boundary_3", "declared_tail_bytes_after_record",
            "template_ordinal_within_section", "template_occurrences_in_section", "template_coverage_of_section_count",
            "previous_template_gap_bytes", "next_template_gap_bytes", "record_inside_declared_span", "classification",
        ], occurrence_rows)
        write_tsv(output / "SLOT_LIGHT_SIBLING_SECTION_ANCHORED_LAYOUTS.tsv", [
            "normalized_path", "member_key", "member_name", "side", "technical_member_role", "character_slot", "normalized_endpoint",
            "section_mode_or_flag_word", "section_mode_or_flag_hex", "section_count", "section_declared_span",
            "section_table_boundary_1", "section_table_boundary_2", "section_table_boundary_3", "template_occurrences_in_section",
            "template_coverage_of_section_count", "template_relative_offsets", "template_values_in_order", "first_template_relative_offset",
            "last_template_end_relative_offset", "declared_tail_after_last_template", "exact_section_anchored_layout_sha256", "classification",
        ], section_rows)
        write_tsv(output / "SLOT_LIGHT_SIBLING_HEADER_MODE_FLAG_DISTRIBUTION.tsv", [
            "section_mode_or_flag_word", "section_mode_or_flag_hex", "occurrence_rows", "section_rows", "member_rows", "paired_values",
            "paired_value_rows", "section_counts", "declared_span_min", "declared_span_max", "technical_member_roles", "classification",
        ], mode_rows)
        write_tsv(output / "SLOT_LIGHT_SIBLING_VALUE_SECTION_LAYOUT_DISTRIBUTION.tsv", [
            "paired_float_value", "occurrence_rows", "member_rows", "mode_flag_rows", "mode_flags", "section_count_rows", "section_counts",
            "declared_span_rows", "declared_span_min", "declared_span_max", "section_anchored_layout_rows", "technical_member_roles", "classification",
        ], value_rows)
        write_tsv(output / "SLOT_LIGHT_SIBLING_SOURCE_TARGET_SECTION_LAYOUT_COMPARISON.tsv", [
            "normalized_path", "member_key", "source_section_rows", "target_section_rows", "exact_layout_signatures_shared",
            "source_only_layout_signatures", "target_only_layout_signatures", "classification",
        ], comparison_rows)
        write_tsv(output / "SLOT_LIGHT_SIBLING_SECTION_LAYOUT_DECISION.tsv", ["question", "answer", "classification"], decision_rows)
        write_tsv(output / "SLOT_LIGHT_SIBLING_SECTION_LAYOUT_SKIPPED.tsv", ["scope", "normalized_path", "member_key", "side", "record_start", "reason"], skipped_rows)

        summary = {
            "type": "br_quartet_restoration_reflector_slot_light_sibling_section_layout_evidence_summary",
            "format_version": 1,
            "tool_version": TOOL_VERSION,
            "source_stage104_tool_version": summary104.get("tool_version"),
            "source_stage108_tool_version": summary108.get("tool_version"),
            "sibling_G1E_G1EM_pair_rows": len(all_pairs),
            "revalidated_occurrence_rows": len(occurrence_rows),
            "section_anchored_layout_rows": len(section_rows),
            "header_mode_flag_rows": len(mode_rows),
            "paired_value_rows": len(value_rows),
            "values_crossing_multiple_mode_flags": values_crossing_modes,
            "mode_flags_covering_multiple_values": modes_covering_multiple_values,
            "full_template_coverage_section_rows": full_sections,
            "partial_template_coverage_section_rows": len(section_rows) - full_sections,
            "source_target_member_comparison_rows": len(comparison_rows),
            "source_target_layout_stable_member_rows": sum(row["classification"] == "exact_section_layout_multiset_stable" for row in comparison_rows),
            "technical_leaf_domain_semantics_resolved": False,
            "brightness_semantics_confirmed": False,
            "censorship_semantics_confirmed": False,
            "prototype_candidate_rows": 0,
            "skipped_rows": len(skipped_rows),
            "status": "sibling_section_mode_flag_and_anchored_layout_audited_domain_semantics_unresolved",
            "next_action": "Upload this report. Continue only with a read-only comparison of source-target value transitions within identical section-mode and anchored-layout classes. Do not infer brightness/intensity and do not write G1E.",
            "policy": {
                "official_nonunderscore_archives_are_canonical": True,
                "underscore_archives_required": False,
                "installed_game_modified": False,
                "render_payload_written": False,
                "pak_repacked": False,
                "core_registry_modified": False,
                "profile_activated": False,
                "runtime_validation_inferred": False,
                "technical_leaf_domain_semantics_inferred": False,
                "brightness_semantics_inferred": False,
                "censorship_semantics_inferred": False,
                "full_proprietary_payloads_exported": False,
            },
        }
        (output / "SUMMARY.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        archive = reports / REPORT_NAME if create_archive else None
        if archive is not None:
            progress("creating compressed report archive")
            make_archive(output, archive)
        return output, archive, summary


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path, default=PROJECT_ROOT_DEFAULT)
    parser.add_argument("--no-report-archive", action="store_true")
    args = parser.parse_args(argv)
    try:
        output, archive, summary = build_report(args.project_root, create_archive=not args.no_report_archive)
    except Stage109Error as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print(f"Revalidated occurrences: {summary['revalidated_occurrence_rows']}")
    print(f"Section-anchored layouts: {summary['section_anchored_layout_rows']}")
    print(f"Header mode/flag rows: {summary['header_mode_flag_rows']}")
    print(f"Domain semantics resolved: {summary['technical_leaf_domain_semantics_resolved']}")
    print(f"Report directory: {output}")
    if archive is not None:
        print(f"Report: {archive}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
