#!/usr/bin/env python3
"""Triage stage-126 G1M/material deltas by structural scope.

Stage 127 consumes the exact locally reviewed stage-126 evidence archive. It
separates ubiquitous cross-character/cross-state patterns from narrower
state/character/member-role candidates, groups keyword-bearing parameter
signatures, and emits a bounded follow-up queue. It also enforces the
quartet_restoration path-hygiene contract: versioned workstream files may not
contain user-specific home paths or sandbox paths.

This stage is metadata-only. It assigns no visual, wetness, nudity, opacity,
remastering or censorship semantics and authorizes no payload or game write.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from collections import Counter, defaultdict
from pathlib import Path, PurePosixPath
from typing import Any, Iterable, Mapping, Sequence

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT_DEFAULT = SCRIPT_DIR.parent.parent
TOOL_VERSION = "0.1.45"
REPORT_DIR = "character_state_g1m_delta_scope_triage_evidence"
REPORT_NAME = "BR_quartet_restoration_character_state_g1m_delta_scope_triage_evidence.tar.zst"
STAGE126_ARCHIVE = "BR_quartet_restoration_character_state_g1m_material_classification_evidence.tar.zst"
STAGE126_ROOT = "character_state_g1m_material_classification_evidence"
STAGE126_SHA256 = "fd1a6992f9ef79264a33269fe1d12c94d34d7bb1e3c60dfec973ece0cb8c5371"
STAGE126_SUMMARY_SHA256 = "63a51dd2b7ad056d38da881fd640d4537ab7c1218bbc142eddbd0a009831e04a"
EXPECTED_SCHEMA_GROUPS = 108
EXPECTED_VALUE_GROUPS = 117
EXPECTED_PARAMETER_ROWS = 2678


class CollectorError(RuntimeError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise CollectorError(message)


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
        return [dict(row) for row in csv.DictReader(handle, delimiter="\t")]


def write_tsv(path: Path, fields: Sequence[str], rows: Iterable[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(fields), delimiter="\t", lineterminator="\n", extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fields})


def atomic_json(path: Path, value: Mapping[str, Any]) -> None:
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def make_archive(source: Path, output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(output.name + ".tmp")
    temporary.unlink(missing_ok=True)
    completed = subprocess.run(
        ["tar", "--zstd", "-cf", str(temporary), "-C", str(source.parent), source.name],
        text=True,
        capture_output=True,
    )
    require(completed.returncode == 0, completed.stderr.strip() or "report archive creation failed")
    os.replace(temporary, output)


def extract_stage126(archive: Path, destination: Path) -> Path:
    require(archive.is_file(), f"missing stage-126 report: {archive}")
    actual = sha256_file(archive)
    require(actual == STAGE126_SHA256, f"unexpected stage-126 report SHA-256: {actual}")
    listed = subprocess.run(["tar", "--zstd", "-tf", str(archive)], text=True, capture_output=True)
    require(listed.returncode == 0, listed.stderr.strip() or "cannot list stage-126 report")
    names = [safe_relative(line.strip(), "archive member") for line in listed.stdout.splitlines() if line.strip()]
    require(names and {PurePosixPath(name).parts[0] for name in names} == {STAGE126_ROOT}, "unexpected stage-126 archive root")
    forbidden = (".pak", ".g1e", ".g1em", ".g1m", ".g1s", ".g1t", ".elixir", ".elixir.gz", ".ebd", ".ebm")
    require(not any(name.casefold().endswith(forbidden) for name in names), "proprietary payload extension in stage-126 report")
    destination.mkdir(parents=True, exist_ok=True)
    completed = subprocess.run(["tar", "--zstd", "-xf", str(archive), "-C", str(destination)], text=True, capture_output=True)
    require(completed.returncode == 0, completed.stderr.strip() or "cannot extract stage-126 report")
    root = destination / STAGE126_ROOT
    summary = root / "SUMMARY.json"
    require(summary.is_file(), "stage-126 SUMMARY.json missing")
    actual_summary = sha256_file(summary)
    require(actual_summary == STAGE126_SUMMARY_SHA256, f"unexpected stage-126 summary SHA-256: {actual_summary}")
    return root


def split_set(raw: str) -> set[str]:
    return {item for item in str(raw).split(";") if item}


def split_keywords(raw: str) -> set[str]:
    result: set[str] = set()
    for semicolon_part in str(raw).split(";"):
        for comma_part in semicolon_part.split(","):
            token = comma_part.strip().casefold()
            if token:
                result.add(token)
    return result


def scope_class(character_count: int, state_count: int) -> str:
    if character_count == 15 and state_count == 8:
        return "universal_15_character_8_state_pattern"
    if character_count >= 12 and state_count >= 6:
        return "broad_cross_character_cross_state_pattern"
    if character_count >= 8 and state_count <= 3:
        return "state_concentrated_cross_character_pattern"
    if character_count <= 2 and state_count >= 4:
        return "character_concentrated_cross_state_pattern"
    if character_count <= 3 and state_count <= 3:
        return "narrow_character_state_pattern"
    return "mixed_scope_pattern"


def classify_group_rows(rows: list[dict[str, str]], group_kind: str, hash_field: str) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for row in rows:
        characters = split_set(row["character_ids"])
        states = split_set(row["state_tokens"])
        roles = split_set(row["normalized_member_roles"])
        member_rows = int(row["g1m_member_rows"])
        keyword_rows = int(row["semantic_keyword_diff_rows"])
        classification = scope_class(len(characters), len(states))
        broad = classification in {
            "universal_15_character_8_state_pattern",
            "broad_cross_character_cross_state_pattern",
        }
        narrow = classification in {
            "narrow_character_state_pattern",
            "character_concentrated_cross_state_pattern",
        }
        if broad:
            priority = "deprioritize_as_broad_engine_or_format_candidate_pending_external_proof"
        elif narrow and keyword_rows > 0:
            priority = "high_static_review_priority_keyword_bearing_narrow_scope"
        elif narrow:
            priority = "medium_static_review_priority_narrow_scope"
        elif keyword_rows > 0:
            priority = "medium_static_review_priority_keyword_bearing_mixed_scope"
        else:
            priority = "low_static_review_priority_structural_only"
        result.append({
            "group_kind": group_kind,
            "group_sha256": row[hash_field],
            "g1m_member_rows": member_rows,
            "character_count": len(characters),
            "state_count": len(states),
            "member_role_count": len(roles),
            "character_ids": ";".join(sorted(characters)),
            "state_tokens": ";".join(sorted(states)),
            "normalized_member_roles": ";".join(sorted(roles)),
            "semantic_parameter_diff_rows": int(row["semantic_parameter_diff_rows"]),
            "semantic_keyword_diff_rows": keyword_rows,
            "recurrent_across_multiple_families": row["recurrent_across_multiple_families"],
            "scope_classification": classification,
            "review_priority": priority,
            "broad_engine_or_format_candidate": broad,
            "narrow_state_specific_candidate": narrow,
            "visual_or_censorship_semantics_confirmed": False,
            "write_authorized": False,
        })
    return sorted(result, key=lambda row: (-int(row["g1m_member_rows"]), str(row["group_sha256"])))


def keyword_signature_rows(parameter_rows: list[dict[str, str]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    groups: dict[tuple[str, ...], list[dict[str, str]]] = defaultdict(list)
    detailed: list[dict[str, Any]] = []
    for row in parameter_rows:
        keywords = split_keywords(row.get("keyword_hits", ""))
        if not keywords:
            continue
        key = (
            row["parameter_name"], row["buffer_type"], row["buffer_count"], row["classification"],
            row["source_value_hex"], row["target_value_hex"], row["matching_basis"],
        )
        groups[key].append(row)
        if keywords != {"blend"}:
            detailed.append({
                "character_id": row["character_id"],
                "state_token": row["state_token"],
                "archive_path": row["archive_path"],
                "member_key": row["member_key"],
                "normalized_member_role": row["normalized_member_role"],
                "parameter_name": row["parameter_name"],
                "classification": row["classification"],
                "source_value_text": row["source_value_text"],
                "target_value_text": row["target_value_text"],
                "source_value_hex": row["source_value_hex"],
                "target_value_hex": row["target_value_hex"],
                "keyword_hits": ";".join(sorted(keywords)),
                "review_priority": "high_static_review_priority_nonblend_keyword",
                "semantics_confirmed": False,
                "write_authorized": False,
            })
    grouped: list[dict[str, Any]] = []
    for key, rows in groups.items():
        parameter_name, buffer_type, buffer_count, classification, source_hex, target_hex, matching_basis = key
        characters = {row["character_id"] for row in rows}
        states = {row["state_token"] for row in rows}
        roles = {row["normalized_member_role"] for row in rows}
        keywords: set[str] = set()
        for row in rows:
            keywords.update(split_keywords(row.get("keyword_hits", "")))
        if parameter_name == "parameterForMeshBlend" and len(rows) >= 1000 and len(characters) == 15 and len(states) == 8:
            structural_class = "ubiquitous_engine_or_format_candidate"
            priority = "deprioritize_pending_external_format_or_visual_evidence"
        elif keywords != {"blend"} and len(rows) <= 2:
            structural_class = "isolated_nonblend_keyword_candidate"
            priority = "highest_static_review_priority"
        elif keywords != {"blend"}:
            structural_class = "clustered_nonblend_keyword_candidate"
            priority = "high_static_review_priority"
        else:
            structural_class = "recurrent_blend_keyword_pattern"
            priority = "low_static_review_priority"
        grouped.append({
            "parameter_name": parameter_name,
            "buffer_type": buffer_type,
            "buffer_count": buffer_count,
            "classification": classification,
            "source_value_hex": source_hex,
            "target_value_hex": target_hex,
            "matching_basis": matching_basis,
            "row_count": len(rows),
            "character_count": len(characters),
            "state_count": len(states),
            "member_role_count": len(roles),
            "character_ids": ";".join(sorted(characters)),
            "state_tokens": ";".join(sorted(states)),
            "normalized_member_roles": ";".join(sorted(roles)),
            "keyword_hits": ";".join(sorted(keywords)),
            "structural_classification": structural_class,
            "review_priority": priority,
            "visual_or_censorship_semantics_confirmed": False,
            "write_authorized": False,
        })
    grouped.sort(key=lambda row: (-int(row["row_count"]), str(row["parameter_name"]), str(row["classification"])))
    detailed.sort(key=lambda row: (str(row["parameter_name"]), str(row["character_id"]), str(row["state_token"]), str(row["member_key"])))
    return grouped, detailed


def path_hygiene_hits(workstream: Path) -> tuple[int, list[dict[str, Any]]]:
    posix_home = re.compile(r"/(?:home|Users)/[^/\\\s\"'`]+/")
    windows_home = re.compile(r"[A-Za-z]:[\\/]+Users[\\/]+[^\\/\s\"'`]+[\\/]")
    sandbox = re.compile(re.escape("/mnt" + "/data") + r"(?:/|\b)")
    scanned = 0
    hits: list[dict[str, Any]] = []
    for path in sorted(workstream.rglob("*")):
        if not path.is_file() or "__pycache__" in path.parts or path.suffix == ".pyc":
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        scanned += 1
        for line_number, line in enumerate(text.splitlines(), 1):
            classifications: list[str] = []
            if posix_home.search(line):
                classifications.append("user_specific_posix_home")
            if windows_home.search(line):
                classifications.append("user_specific_windows_home")
            if sandbox.search(line):
                classifications.append("sandbox_mount_path")
            if classifications:
                hits.append({
                    "relative_path": path.relative_to(workstream.parent.parent).as_posix(),
                    "line_number": line_number,
                    "classification": ";".join(classifications),
                    "line_sha256": hashlib.sha256(line.encode("utf-8")).hexdigest(),
                })
    return scanned, hits


def build_report(project_root: Path, *, report_root: Path | None = None, output_report_root: Path | None = None, create_archive: bool = True) -> tuple[Path | None, dict[str, Any]]:
    project_root = project_root.resolve()
    workstream = project_root / "workstreams/quartet_restoration"
    version = (workstream / "VERSION").read_text(encoding="utf-8").strip()
    require(version == TOOL_VERSION, f"expected quartet_restoration {TOOL_VERSION}, found {version}")
    report_root = (report_root or project_root / ".local/reports/quartet_restoration").resolve()
    output_report_root = (output_report_root or report_root).resolve()
    output = output_report_root / REPORT_DIR
    archive = output_report_root / REPORT_NAME
    if output.exists():
        shutil.rmtree(output)
    output.mkdir(parents=True, exist_ok=True)

    scanned_files, path_hits = path_hygiene_hits(workstream)
    require(not path_hits, f"user-specific or sandbox paths remain in workstream: {len(path_hits)}")

    with tempfile.TemporaryDirectory(prefix="stage127-prereq-") as td:
        stage126 = extract_stage126(report_root / STAGE126_ARCHIVE, Path(td))
        summary126 = json.loads((stage126 / "SUMMARY.json").read_text(encoding="utf-8"))
        require(summary126.get("exact_g1m_material_classification_complete") is True, "stage-126 classification is not complete")
        require(summary126.get("audited_universal_family_rows") == 120, "stage-126 family count drift")
        require(summary126.get("visual_or_censorship_semantics_confirmed_rows") == 0, "stage-126 semantics gate drift")
        require(summary126.get("write_authorized_rows") == 0, "stage-126 write gate drift")
        schema_rows = read_tsv(stage126 / "UNIVERSAL_G1M_SCHEMA_DELTA_GROUPS.tsv")
        value_rows = read_tsv(stage126 / "UNIVERSAL_G1M_VALUE_DELTA_GROUPS.tsv")
        parameter_rows = read_tsv(stage126 / "UNIVERSAL_G1M_PARAMETER_DIFF.tsv")
        require(len(schema_rows) == EXPECTED_SCHEMA_GROUPS, f"schema group count drift: {len(schema_rows)}")
        require(len(value_rows) == EXPECTED_VALUE_GROUPS, f"value group count drift: {len(value_rows)}")
        require(len(parameter_rows) == EXPECTED_PARAMETER_ROWS, f"parameter row count drift: {len(parameter_rows)}")

        classified_schema = classify_group_rows(schema_rows, "schema_delta", "schema_delta_sha256")
        classified_value = classify_group_rows(value_rows, "value_delta", "value_delta_sha256")
        keyword_groups, nonblend_queue = keyword_signature_rows(parameter_rows)

    group_fields = [
        "group_kind", "group_sha256", "g1m_member_rows", "character_count", "state_count", "member_role_count",
        "character_ids", "state_tokens", "normalized_member_roles", "semantic_parameter_diff_rows",
        "semantic_keyword_diff_rows", "recurrent_across_multiple_families", "scope_classification", "review_priority",
        "broad_engine_or_format_candidate", "narrow_state_specific_candidate",
        "visual_or_censorship_semantics_confirmed", "write_authorized",
    ]
    write_tsv(output / "SCHEMA_DELTA_SCOPE_CLASSIFICATION.tsv", group_fields, classified_schema)
    write_tsv(output / "VALUE_DELTA_SCOPE_CLASSIFICATION.tsv", group_fields, classified_value)
    write_tsv(output / "KEYWORD_PARAMETER_SIGNATURE_GROUPS.tsv", [
        "parameter_name", "buffer_type", "buffer_count", "classification", "source_value_hex", "target_value_hex",
        "matching_basis", "row_count", "character_count", "state_count", "member_role_count", "character_ids",
        "state_tokens", "normalized_member_roles", "keyword_hits", "structural_classification", "review_priority",
        "visual_or_censorship_semantics_confirmed", "write_authorized",
    ], keyword_groups)
    write_tsv(output / "NON_BLEND_KEYWORD_CANDIDATE_QUEUE.tsv", [
        "character_id", "state_token", "archive_path", "member_key", "normalized_member_role", "parameter_name",
        "classification", "source_value_text", "target_value_text", "source_value_hex", "target_value_hex",
        "keyword_hits", "review_priority", "semantics_confirmed", "write_authorized",
    ], nonblend_queue)
    write_tsv(output / "LOCAL_PATH_HYGIENE_AUDIT.tsv", [
        "relative_path", "line_number", "classification", "line_sha256",
    ], path_hits)

    schema_scope_counts = Counter(row["scope_classification"] for row in classified_schema)
    value_scope_counts = Counter(row["scope_classification"] for row in classified_value)
    keyword_parameter_counts = Counter()
    for row in nonblend_queue:
        keyword_parameter_counts[str(row["parameter_name"])] += 1
    ubiquitous_blend = sum(int(row["row_count"]) for row in keyword_groups if row["structural_classification"] == "ubiquitous_engine_or_format_candidate")
    summary = {
        "type": "br_quartet_restoration_character_state_g1m_delta_scope_triage_evidence_summary",
        "format_version": 1,
        "tool_version": TOOL_VERSION,
        "status": "stage126_g1m_delta_scope_triage_complete_broad_patterns_separated_from_narrow_candidates_no_semantics_no_write",
        "stage126_report_sha256": STAGE126_SHA256,
        "stage126_summary_sha256": STAGE126_SUMMARY_SHA256,
        "schema_delta_group_rows": len(classified_schema),
        "value_delta_group_rows": len(classified_value),
        "schema_scope_classification_counts": dict(sorted(schema_scope_counts.items())),
        "value_scope_classification_counts": dict(sorted(value_scope_counts.items())),
        "recurrent_schema_delta_group_rows": sum(row["recurrent_across_multiple_families"] == "True" for row in classified_schema),
        "recurrent_value_delta_group_rows": sum(row["recurrent_across_multiple_families"] == "True" for row in classified_value),
        "keyword_parameter_signature_group_rows": len(keyword_groups),
        "ubiquitous_mesh_blend_addition_rows": ubiquitous_blend,
        "nonblend_keyword_candidate_rows": len(nonblend_queue),
        "nonblend_keyword_candidate_family_rows": len({(row["character_id"], row["state_token"]) for row in nonblend_queue}),
        "nonblend_keyword_parameter_counts": dict(sorted(keyword_parameter_counts.items())),
        "path_hygiene_scanned_versioned_text_files": scanned_files,
        "forbidden_local_path_hit_rows": len(path_hits),
        "runtime_confirmed_rows": 0,
        "visual_or_censorship_semantics_confirmed_rows": 0,
        "write_authorized_rows": 0,
        "global_discovery_saturation_achieved": False,
        "policy": {
            "stage126_evidence_only": True,
            "local_proprietary_payloads_read": False,
            "proprietary_payloads_in_report": False,
            "user_specific_paths_in_versioned_workstream_files": False,
            "project_root_resolved_relatively_or_by_argument": True,
            "game_roots_loaded_from_local_path_configuration_or_explicit_arguments": True,
            "parameter_names_used_as_semantics": False,
            "broad_pattern_classification_is_not_visual_proof": True,
            "save_or_runtime_required": False,
            "pak_built_or_repacked": False,
            "g1m_or_earc_written": False,
            "profile_or_registry_modified": False,
            "core_modified": False,
            "translation_modified": False,
            "legacy_dlc_modified": False,
            "installed_game_modified": False,
            "git_modified": False,
        },
        "next_action": (
            "Audit the 19 selector-bound towel/swimsuit/underwear families and the five standalone shader/caustics paths. "
            "Use the 36 non-blend keyword rows only as a bounded static review queue; do not infer opacity, wetness or censorship semantics without independent structural or visual evidence."
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
    parser.add_argument("--no-archive", action="store_true")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    archive, summary = build_report(
        Path(args.project_root).expanduser(),
        report_root=Path(args.report_root).expanduser() if args.report_root else None,
        output_report_root=Path(args.output_report_root).expanduser() if args.output_report_root else None,
        create_archive=not args.no_archive,
    )
    if archive:
        print(f"[character-state-g1m-triage] report archive: {archive}")
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except CollectorError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(2)
