#!/usr/bin/env python3
"""Classify G1M/material deltas across all 120 universal character-state families.

Stage 126 consumes the exact stage-125 family ledger and the local read-only
extraction cache. It parses changed, added and removed G1M members with the
existing bounded G1M/G1MG parser, records structural and named-parameter deltas,
and groups recurrent schema shapes. The report is metadata-only and authorizes
no payload, profile, registry, PAK, core, game or Git write.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
from collections import Counter, defaultdict
from pathlib import Path, PurePosixPath
from typing import Any, Iterable, Mapping, Sequence

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT_DEFAULT = SCRIPT_DIR.parent.parent
TOOL_VERSION = "0.1.44"
REPORT_DIR = "character_state_g1m_material_classification_evidence"
REPORT_NAME = "BR_quartet_restoration_character_state_g1m_material_classification_evidence.tar.zst"
STAGE125_ARCHIVE = "BR_quartet_restoration_character_state_exact_rehydration_evidence.tar.zst"
STAGE125_ROOT = "character_state_exact_rehydration_evidence"
STAGE125_SHA256 = "a6b6ae0d0f1276b3393f5292dd65f264b003901142f1965c108f6ad58729fe54"
STAGE125_SUMMARY_SHA256 = "d9da19d479d599754d285d305820a17b48389c874916c68e45fe89ee17fc3002"
EXPECTED_FAMILIES = 120
EXPECTED_CHARACTERS = 15
EXPECTED_STATES = 8
MAX_EARC_BYTES = 256 * 1024 * 1024


class CollectorError(RuntimeError):
    pass


def version_tuple(value: str) -> tuple[int, ...]:
    try:
        return tuple(int(part) for part in value.strip().split("."))
    except ValueError as exc:
        raise CollectorError(f"invalid workstream version: {value}") from exc


def require(condition: bool, message: str) -> None:
    if not condition:
        raise CollectorError(message)


def progress(message: str) -> None:
    print(f"[character-state-g1m] {message}", file=sys.stderr, flush=True)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def safe_relative(raw: str, label: str) -> str:
    path = PurePosixPath(str(raw).replace("\\", "/"))
    require(bool(path.parts), f"empty {label}")
    require(not path.is_absolute() and ".." not in path.parts, f"unsafe {label}: {raw}")
    return path.as_posix()


def read_tsv(path: Path) -> list[dict[str, str]]:
    require(path.is_file(), f"missing required TSV: {path}")
    with path.open(encoding="utf-8", newline="") as handle:
        rows = [dict(row) for row in csv.DictReader(handle, delimiter="\t")]
    require(rows, f"empty required TSV: {path}")
    return rows


def write_tsv(path: Path, fields: Sequence[str], rows: Iterable[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(fields), delimiter="\t", lineterminator="\n", extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fields})


def atomic_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def make_archive(source: Path, output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(output.name + ".tmp")
    temporary.unlink(missing_ok=True)
    completed = subprocess.run(["tar", "--zstd", "-cf", str(temporary), "-C", str(source.parent), source.name], text=True, capture_output=True)
    require(completed.returncode == 0, completed.stderr.strip() or "report archive creation failed")
    os.replace(temporary, output)


def extract_report(archive: Path, destination: Path) -> Path:
    require(archive.is_file(), f"missing stage-125 report: {archive}")
    actual = sha256_file(archive)
    require(actual == STAGE125_SHA256, f"unexpected stage-125 report SHA-256: {actual}")
    listed = subprocess.run(["tar", "--zstd", "-tf", str(archive)], text=True, capture_output=True)
    require(listed.returncode == 0, listed.stderr.strip() or "cannot list stage-125 report")
    names = [safe_relative(line.strip(), "archive member") for line in listed.stdout.splitlines() if line.strip()]
    require(names and {PurePosixPath(name).parts[0] for name in names} == {STAGE125_ROOT}, "unexpected stage-125 archive root")
    destination.mkdir(parents=True, exist_ok=True)
    completed = subprocess.run(["tar", "--zstd", "-xf", str(archive), "-C", str(destination)], text=True, capture_output=True)
    require(completed.returncode == 0, completed.stderr.strip() or "cannot extract stage-125 report")
    root = destination / STAGE125_ROOT
    summary = root / "SUMMARY.json"
    require(summary.is_file(), "stage-125 SUMMARY.json missing")
    actual_summary = sha256_file(summary)
    require(actual_summary == STAGE125_SUMMARY_SHA256, f"unexpected stage-125 summary SHA-256: {actual_summary}")
    return root


def load_module(path: Path, name: str):
    require(path.is_file(), f"missing module: {path}")
    spec = importlib.util.spec_from_file_location(name, path)
    require(spec is not None and spec.loader is not None, f"cannot load module: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def parse_g1m(br: Any, payload: bytes | None, label: str) -> tuple[dict[str, Any] | None, str]:
    if payload is None:
        return None, "missing_side"
    try:
        return br.parse_g1m_material_parameters(payload, label=label), "parsed"
    except Exception as exc:  # bounded parser failure is reportable, not silently ignored
        error_type = type(exc).__name__
        return None, f"parse_error:{error_type}:{str(exc).replace(chr(9), ' ').replace(chr(10), ' ')[:240]}"


def chunk_schema(parsed: dict[str, Any] | None) -> str:
    if not parsed:
        return ""
    return ";".join(f"{row['chunk_magic']}@{row['chunk_version']}" for row in parsed.get("chunks", []))


def schema_signature(
    *, normalized_role: str, member_classification: str,
    source: dict[str, Any] | None, target: dict[str, Any] | None,
    semantic_rows: Sequence[Mapping[str, Any]],
) -> str:
    tokens = [
        f"role={normalized_role}",
        f"member={member_classification}",
        f"source_chunks={chunk_schema(source)}",
        f"target_chunks={chunk_schema(target)}",
    ]
    for row in semantic_rows:
        tokens.append("|".join([
            str(row.get("parameter_name", "")).casefold(),
            str(row.get("buffer_type", "")),
            str(row.get("buffer_count", "")),
            str(row.get("classification", "")),
            str(row.get("keyword_hits", "")),
        ]))
    return hashlib.sha256("\n".join(sorted(tokens)).encode("utf-8")).hexdigest()


def value_signature(
    *, schema_sha: str, semantic_rows: Sequence[Mapping[str, Any]],
) -> str:
    tokens = [schema_sha]
    for row in semantic_rows:
        tokens.append("|".join([
            str(row.get("parameter_name", "")).casefold(),
            str(row.get("classification", "")),
            str(row.get("source_value_hex", "")),
            str(row.get("target_value_hex", "")),
        ]))
    return hashlib.sha256("\n".join(sorted(tokens)).encode("utf-8")).hexdigest()


def build_report(
    project_root: Path,
    *, report_root: Path | None = None, output_report_root: Path | None = None,
    workspace_root: Path | None = None, original_root: Path | None = None,
    quartet_root: Path | None = None, gust_pak_path: Path | None = None,
    create_archive: bool = True, timeout_seconds: int = 1800,
    verify_payload_hashes: bool = True,
) -> tuple[Path | None, dict[str, Any]]:
    project_root = project_root.resolve()
    version = (project_root / "workstreams/quartet_restoration/VERSION").read_text(encoding="utf-8").strip()
    require(version_tuple(version) >= version_tuple(TOOL_VERSION), f"expected quartet_restoration {TOOL_VERSION} or newer, found {version}")
    report_root = (report_root or project_root / ".local/reports/quartet_restoration").resolve()
    output_report_root = (output_report_root or report_root).resolve()
    workspace_root = (workspace_root or project_root / ".local/build/quartet_restoration").resolve()
    output = output_report_root / REPORT_DIR
    archive = output_report_root / REPORT_NAME
    if output.exists():
        shutil.rmtree(output)
    output.mkdir(parents=True, exist_ok=True)

    br = load_module(project_root / "Blue_Reflection_Text_Tool/br_restoration_tool.py", "stage126_br_restoration_tool")
    stage125_tool = load_module(project_root / "workstreams/quartet_restoration/125_collect_character_state_exact_rehydration_evidence.py", "stage126_stage125_tool")

    with tempfile.TemporaryDirectory(prefix="stage126-prereq-") as td:
        stage125 = extract_report(report_root / STAGE125_ARCHIVE, Path(td))
        prerequisite_summary = json.loads((stage125 / "SUMMARY.json").read_text(encoding="utf-8"))
        require(prerequisite_summary.get("complete_universal_family_rows") == EXPECTED_FAMILIES, "stage-125 family count drift")
        require(prerequisite_summary.get("complete_universal_character_rows") == EXPECTED_CHARACTERS, "stage-125 character count drift")
        require(prerequisite_summary.get("complete_universal_state_token_rows") == EXPECTED_STATES, "stage-125 state count drift")
        require(prerequisite_summary.get("exact_universal_member_coverage_complete") is True, "stage-125 exact coverage is not complete")
        families = read_tsv(stage125 / "COMPLETE_UNIVERSAL_FAMILY_COVERAGE.tsv")
        require(len(families) == EXPECTED_FAMILIES, "stage-125 complete family ledger drift")
        require(len({row["character_id"] for row in families}) == EXPECTED_CHARACTERS, "character cardinality drift")
        require(len({row["state_token"] for row in families}) == EXPECTED_STATES, "state cardinality drift")

        inventories = stage125_tool.load_asset_inventories(project_root)
        required_paths = [row["archive_path"] for row in families]
        extraction_rows = stage125_tool.ensure_extraction_cache(
            project_root=project_root, workspace_root=workspace_root, inventories=inventories,
            required_paths=required_paths, original_root=original_root, quartet_root=quartet_root,
            gust_pak_path=gust_pak_path, br=br, timeout_seconds=timeout_seconds,
        )

        coverage_rows: list[dict[str, Any]] = []
        member_rows: list[dict[str, Any]] = []
        chunk_rows: list[dict[str, Any]] = []
        parameter_rows: list[dict[str, Any]] = []
        skipped_rows: list[dict[str, Any]] = []
        schema_groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
        value_groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
        payload_bytes_read = 0

        for family_index, family in enumerate(sorted(families, key=lambda r: (r["character_id"], r["state_token"])), 1):
            character_id = family["character_id"]
            state_token = family["state_token"]
            normalized = family["archive_path"]
            progress(f"family {family_index}/{len(families)} {character_id}:{state_token}")
            parsed_archives: dict[str, dict[str, Any]] = {}
            for side in ("source", "target"):
                key = (side, normalized.casefold())
                require(key in inventories, f"missing inventory entry: {key}")
                pair_id, entry = inventories[key]
                local = br.inventory_workspace_file(workspace_root, side, pair_id, str(entry["archive"]), str(entry["path"]))
                require(local.is_file(), f"missing extracted input: {side} {normalized}: {local}")
                actual_sha = sha256_file(local)
                if verify_payload_hashes:
                    require(actual_sha == str(entry["sha256"]), f"payload hash drift: {side} {normalized}: {actual_sha}")
                parsed_archives[side] = br.read_earc_archive(local, maximum_bytes=MAX_EARC_BYTES, include_member_payloads=True)
                payload_bytes_read += int(parsed_archives[side]["decoded_bytes"])

            source_by = {str(m["comparison_key"]): m for m in parsed_archives["source"]["members"]}
            target_by = {str(m["comparison_key"]): m for m in parsed_archives["target"]["members"]}
            family_g1m = 0
            family_parsed_pairs = 0
            family_parameter_diffs = 0
            family_keyword_diffs = 0
            family_parse_skips = 0

            for member_key in sorted(set(source_by) | set(target_by), key=str.casefold):
                left = source_by.get(member_key)
                right = target_by.get(member_key)
                member = right or left
                extension = str((member or {}).get("extension", "")).casefold()
                if extension != ".g1m":
                    continue
                if left and right:
                    classification = "identical" if left["sha256"] == right["sha256"] else "changed"
                elif left:
                    classification = "removed_in_target"
                else:
                    classification = "added_in_target"
                if classification == "identical":
                    continue
                family_g1m += 1
                member_name = str((right or left or {}).get("name", ""))
                normalized_role = stage125_tool.normalized_role(member_name, character_id, state_token)
                source_parsed, source_status = parse_g1m(br, (left or {}).get("payload"), f"{character_id}:{state_token}:source:{member_name}")
                target_parsed, target_status = parse_g1m(br, (right or {}).get("payload"), f"{character_id}:{state_token}:target:{member_name}")
                if source_status.startswith("parse_error"):
                    family_parse_skips += 1
                    skipped_rows.append({
                        "character_id": character_id, "state_token": state_token, "archive_path": normalized,
                        "member_key": member_key, "side": "source", "member_name": (left or {}).get("name", ""),
                        "reason": source_status, "write_authorized": False,
                    })
                if target_status.startswith("parse_error"):
                    family_parse_skips += 1
                    skipped_rows.append({
                        "character_id": character_id, "state_token": state_token, "archive_path": normalized,
                        "member_key": member_key, "side": "target", "member_name": (right or {}).get("name", ""),
                        "reason": target_status, "write_authorized": False,
                    })

                positional_rows, positional_counts = br.compare_g1m_material_parameters(source_parsed, target_parsed)
                semantic_rows, semantic_counts = br.compare_g1m_material_parameters_semantic(source_parsed, target_parsed)
                if source_parsed is not None or target_parsed is not None:
                    family_parsed_pairs += 1
                family_parameter_diffs += len(semantic_rows)
                keyword_count = sum(bool(str(row.get("keyword_hits", ""))) for row in semantic_rows)
                family_keyword_diffs += keyword_count
                schema_sha = schema_signature(
                    normalized_role=normalized_role, member_classification=classification,
                    source=source_parsed, target=target_parsed, semantic_rows=semantic_rows,
                )
                value_sha = value_signature(schema_sha=schema_sha, semantic_rows=semantic_rows)
                row = {
                    "character_id": character_id, "state_token": state_token, "archive_path": normalized,
                    "member_key": member_key, "normalized_member_role": normalized_role,
                    "source_member_name": (left or {}).get("name", ""), "target_member_name": (right or {}).get("name", ""),
                    "source_member_size": (left or {}).get("size", ""), "target_member_size": (right or {}).get("size", ""),
                    "source_member_sha256": (left or {}).get("sha256", ""), "target_member_sha256": (right or {}).get("sha256", ""),
                    "member_classification": classification, "source_parse_status": source_status, "target_parse_status": target_status,
                    "source_chunk_rows": len((source_parsed or {}).get("chunks", [])), "target_chunk_rows": len((target_parsed or {}).get("chunks", [])),
                    "source_parameter_rows": len((source_parsed or {}).get("parameters", [])), "target_parameter_rows": len((target_parsed or {}).get("parameters", [])),
                    "positional_parameter_diff_rows": len(positional_rows), "semantic_parameter_diff_rows": len(semantic_rows),
                    "semantic_keyword_diff_rows": keyword_count,
                    "semantic_identical_same_position_rows": semantic_counts.get("identical_same_position", 0),
                    "semantic_identical_relocated_rows": semantic_counts.get("identical_relocated", 0),
                    "semantic_changed_rows": semantic_counts.get("changed", 0),
                    "semantic_removed_rows": semantic_counts.get("removed_in_target", 0),
                    "semantic_added_rows": semantic_counts.get("added_in_target", 0),
                    "schema_delta_sha256": schema_sha, "value_delta_sha256": value_sha,
                    "runtime_confirmed": False, "semantics_confirmed": False, "write_authorized": False,
                }
                member_rows.append(row)
                schema_groups[schema_sha].append(row)
                value_groups[value_sha].append(row)

                for side, parsed in (("source", source_parsed), ("target", target_parsed)):
                    for chunk in (parsed or {}).get("chunks", []):
                        chunk_rows.append({
                            "character_id": character_id, "state_token": state_token, "archive_path": normalized,
                            "member_key": member_key, "normalized_member_role": normalized_role, "side": side,
                            **chunk, "semantics_confirmed": False, "write_authorized": False,
                        })
                for diff_index, diff in enumerate(semantic_rows):
                    parameter_rows.append({
                        "character_id": character_id, "state_token": state_token, "archive_path": normalized,
                        "member_key": member_key, "normalized_member_role": normalized_role,
                        "schema_delta_sha256": schema_sha, "parameter_diff_index": diff_index,
                        **diff, "semantics_confirmed": False, "write_authorized": False,
                    })

            coverage_rows.append({
                "character_id": character_id, "state_token": state_token, "logical_path": family["logical_path"],
                "archive_path": normalized, "nonidentical_g1m_member_rows": family_g1m,
                "parsed_g1m_member_pair_rows": family_parsed_pairs,
                "semantic_parameter_diff_rows": family_parameter_diffs,
                "semantic_keyword_diff_rows": family_keyword_diffs,
                "parse_skip_rows": family_parse_skips,
                "g1m_material_classification_complete": family_parse_skips == 0,
                "runtime_confirmed": False, "semantics_confirmed": False, "write_authorized": False,
            })

        require(len(coverage_rows) == EXPECTED_FAMILIES, "not all 120 families were audited")
        require(member_rows, "no nonidentical G1M members found")

        def group_rows(groups: Mapping[str, Sequence[Mapping[str, Any]]], signature_field: str) -> list[dict[str, Any]]:
            result = []
            for signature, rows in sorted(groups.items(), key=lambda item: (-len(item[1]), item[0])):
                result.append({
                    signature_field: signature,
                    "g1m_member_rows": len(rows),
                    "character_ids": ";".join(sorted({str(r["character_id"]) for r in rows})),
                    "state_tokens": ";".join(sorted({str(r["state_token"]) for r in rows})),
                    "normalized_member_roles": ";".join(sorted({str(r["normalized_member_role"]) for r in rows})),
                    "archive_paths": ";".join(sorted({str(r["archive_path"]) for r in rows})),
                    "semantic_parameter_diff_rows": sum(int(r["semantic_parameter_diff_rows"]) for r in rows),
                    "semantic_keyword_diff_rows": sum(int(r["semantic_keyword_diff_rows"]) for r in rows),
                    "recurrent_across_multiple_families": len(rows) > 1,
                    "semantics_confirmed": False, "write_authorized": False,
                })
            return result

        schema_group_rows = group_rows(schema_groups, "schema_delta_sha256")
        value_group_rows = group_rows(value_groups, "value_delta_sha256")

        write_tsv(output / "UNIVERSAL_STATE_G1M_COVERAGE.tsv", [
            "character_id", "state_token", "logical_path", "archive_path", "nonidentical_g1m_member_rows",
            "parsed_g1m_member_pair_rows", "semantic_parameter_diff_rows", "semantic_keyword_diff_rows",
            "parse_skip_rows", "g1m_material_classification_complete", "runtime_confirmed", "semantics_confirmed", "write_authorized",
        ], coverage_rows)
        write_tsv(output / "UNIVERSAL_G1M_MEMBER_AUDIT.tsv", [
            "character_id", "state_token", "archive_path", "member_key", "normalized_member_role",
            "source_member_name", "target_member_name", "source_member_size", "target_member_size",
            "source_member_sha256", "target_member_sha256", "member_classification", "source_parse_status", "target_parse_status",
            "source_chunk_rows", "target_chunk_rows", "source_parameter_rows", "target_parameter_rows",
            "positional_parameter_diff_rows", "semantic_parameter_diff_rows", "semantic_keyword_diff_rows",
            "semantic_identical_same_position_rows", "semantic_identical_relocated_rows", "semantic_changed_rows",
            "semantic_removed_rows", "semantic_added_rows", "schema_delta_sha256", "value_delta_sha256",
            "runtime_confirmed", "semantics_confirmed", "write_authorized",
        ], member_rows)
        write_tsv(output / "UNIVERSAL_G1M_CHUNK_ROWS.tsv", [
            "character_id", "state_token", "archive_path", "member_key", "normalized_member_role", "side",
            "chunk_index", "chunk_magic", "chunk_version", "chunk_offset", "chunk_size", "chunk_sha256",
            "semantics_confirmed", "write_authorized",
        ], chunk_rows)
        write_tsv(output / "UNIVERSAL_G1M_PARAMETER_DIFF.tsv", [
            "character_id", "state_token", "archive_path", "member_key", "normalized_member_role", "schema_delta_sha256",
            "parameter_diff_index", "parameter_name", "buffer_type", "buffer_count", "source_shader_block_index",
            "target_shader_block_index", "source_parameter_index", "target_parameter_index", "source_value_text",
            "target_value_text", "source_value_hex", "target_value_hex", "classification", "matching_basis",
            "normalized_distance", "keyword_hits", "review_status", "semantics_confirmed", "write_authorized",
        ], parameter_rows)
        write_tsv(output / "UNIVERSAL_G1M_SCHEMA_DELTA_GROUPS.tsv", [
            "schema_delta_sha256", "g1m_member_rows", "character_ids", "state_tokens", "normalized_member_roles",
            "archive_paths", "semantic_parameter_diff_rows", "semantic_keyword_diff_rows",
            "recurrent_across_multiple_families", "semantics_confirmed", "write_authorized",
        ], schema_group_rows)
        write_tsv(output / "UNIVERSAL_G1M_VALUE_DELTA_GROUPS.tsv", [
            "value_delta_sha256", "g1m_member_rows", "character_ids", "state_tokens", "normalized_member_roles",
            "archive_paths", "semantic_parameter_diff_rows", "semantic_keyword_diff_rows",
            "recurrent_across_multiple_families", "semantics_confirmed", "write_authorized",
        ], value_group_rows)
        write_tsv(output / "G1M_PARSE_SKIPPED.tsv", [
            "character_id", "state_token", "archive_path", "member_key", "side", "member_name", "reason", "write_authorized",
        ], skipped_rows)
        write_tsv(output / "EXTRACTION_INPUTS.tsv", [
            "side", "archive_relative", "archive_size", "archive_sha256", "gust_pak_sha256", "cache_action",
        ], extraction_rows)

        member_classifications = Counter(row["member_classification"] for row in member_rows)
        parse_statuses = Counter()
        for row in member_rows:
            parse_statuses[str(row["source_parse_status"]).split(":", 1)[0]] += 1
            parse_statuses[str(row["target_parse_status"]).split(":", 1)[0]] += 1
        parameter_classifications = Counter(row["classification"] for row in parameter_rows)
        keyword_hits = Counter()
        for row in parameter_rows:
            for hit in filter(None, str(row.get("keyword_hits", "")).split(",")):
                keyword_hits[hit] += 1
        recurrent_schema_groups = [rows for rows in schema_groups.values() if len(rows) > 1]
        recurrent_value_groups = [rows for rows in value_groups.values() if len(rows) > 1]
        complete_families = sum(row["g1m_material_classification_complete"] is True for row in coverage_rows)

        classification_complete = complete_families == EXPECTED_FAMILIES and not skipped_rows
        summary = {
            "type": "br_quartet_restoration_character_state_g1m_material_classification_evidence_summary",
            "format_version": 1,
            "tool_version": TOOL_VERSION,
            "status": (
                "all_120_universal_character_state_families_g1m_material_deltas_classified_metadata_only_no_write"
                if classification_complete
                else "universal_character_state_g1m_material_classification_partial_parse_skips_recorded_no_write"
            ),
            "stage125_report_sha256": STAGE125_SHA256,
            "stage125_summary_sha256": STAGE125_SUMMARY_SHA256,
            "audited_universal_family_rows": len(coverage_rows),
            "audited_character_rows": len({row["character_id"] for row in coverage_rows}),
            "audited_state_token_rows": len({row["state_token"] for row in coverage_rows}),
            "families_with_nonidentical_g1m_rows": sum(int(row["nonidentical_g1m_member_rows"]) > 0 for row in coverage_rows),
            "families_with_keyword_parameter_diffs": sum(int(row["semantic_keyword_diff_rows"]) > 0 for row in coverage_rows),
            "families_with_complete_g1m_classification": complete_families,
            "exact_g1m_material_classification_complete": classification_complete,
            "nonidentical_g1m_member_rows": len(member_rows),
            "g1m_member_classification_counts": dict(sorted(member_classifications.items())),
            "g1m_parse_status_counts": dict(sorted(parse_statuses.items())),
            "g1m_chunk_rows": len(chunk_rows),
            "semantic_parameter_diff_rows": len(parameter_rows),
            "semantic_parameter_classification_counts": dict(sorted(parameter_classifications.items())),
            "semantic_keyword_hit_counts": dict(sorted(keyword_hits.items())),
            "schema_delta_group_rows": len(schema_group_rows),
            "recurrent_schema_delta_group_rows": len(recurrent_schema_groups),
            "g1m_members_in_recurrent_schema_groups": sum(len(rows) for rows in recurrent_schema_groups),
            "value_delta_group_rows": len(value_group_rows),
            "recurrent_value_delta_group_rows": len(recurrent_value_groups),
            "g1m_members_in_recurrent_value_groups": sum(len(rows) for rows in recurrent_value_groups),
            "parse_skipped_rows": len(skipped_rows),
            "input_decoded_payload_bytes_read": payload_bytes_read,
            "runtime_confirmed_rows": 0,
            "visual_or_censorship_semantics_confirmed_rows": 0,
            "write_authorized_rows": 0,
            "global_discovery_saturation_achieved": False,
            "policy": {
                "local_proprietary_payloads_read_for_analysis": True,
                "proprietary_payloads_in_report": False,
                "metadata_and_numeric_parameter_values_only": True,
                "semantic_parameter_alignment_is_not_occurrence_binding": True,
                "numeric_parameter_distance_used_only_within_same_name_type_count_multiset": True,
                "save_or_runtime_required": False,
                "installed_game_read_only": True,
                "local_extraction_cache_may_be_reused_or_created": True,
                "pak_built_or_repacked": False,
                "g1m_or_earc_written": False,
                "profile_or_registry_modified": False,
                "core_modified": False,
                "translation_modified": False,
                "legacy_dlc_modified": False,
                "git_modified": False,
                "visual_or_censorship_semantics_assigned": False,
            },
            "next_action": (
                (
                    "Use recurrent schema groups and keyword-bearing parameter deltas to separate broad engine/remaster patterns from narrow state-specific candidates. "
                    "Then audit the 19 selector-bound towel/swimsuit/underwear families and the five standalone shader/caustics paths. Keep runtime composition deferred."
                )
                if classification_complete
                else (
                    "Extend only the bounded G1M parser for the explicitly recorded parse-skip shapes, rerun this read-only stage, and do not infer semantics or authorize writes from partial coverage."
                )
            ),
        }
        atomic_json(output / "SUMMARY.json", summary)

    result_archive: Path | None = None
    if create_archive:
        make_archive(output, archive)
        result_archive = archive
    return result_archive, summary


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", default=str(PROJECT_ROOT_DEFAULT))
    parser.add_argument("--report-root")
    parser.add_argument("--output-report-root")
    parser.add_argument("--workspace-root")
    parser.add_argument("--original-root", default=os.environ.get("BR1_ORIGINAL_ROOT"))
    parser.add_argument("--quartet-root", default=os.environ.get("BR1_QUARTET_ROOT"))
    parser.add_argument("--gust-pak")
    parser.add_argument("--timeout-seconds", type=int, default=1800)
    parser.add_argument("--no-archive", action="store_true")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    project_root = Path(args.project_root).expanduser().resolve()
    archive, summary = build_report(
        project_root,
        report_root=Path(args.report_root).expanduser() if args.report_root else None,
        output_report_root=Path(args.output_report_root).expanduser() if args.output_report_root else None,
        workspace_root=Path(args.workspace_root).expanduser() if args.workspace_root else None,
        original_root=Path(args.original_root).expanduser() if args.original_root else None,
        quartet_root=Path(args.quartet_root).expanduser() if args.quartet_root else None,
        gust_pak_path=Path(args.gust_pak).expanduser() if args.gust_pak else None,
        create_archive=not args.no_archive,
        timeout_seconds=args.timeout_seconds,
    )
    if archive:
        print(f"[character-state-g1m] report archive: {archive}")
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except CollectorError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(2)
