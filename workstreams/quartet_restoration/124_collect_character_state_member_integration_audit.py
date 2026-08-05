#!/usr/bin/env python3
"""Integrate universal character-state families with existing member ledgers.

Stage 124 is a metadata-only bridge between the complete character namespace
sweep from stage 123 and the earlier EARC/material reports. It determines which
of the 120 universal changed player-state families already have exact internal
member and material-parameter evidence, and which still require a dedicated
static rehydration collector.

No proprietary payload is rehydrated, no visual/censorship semantics are
assigned, and no profile, PAK, registry, game installation or Git state is
modified.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import subprocess
import sys
import tempfile
from collections import Counter, defaultdict
from pathlib import Path, PurePosixPath
from typing import Any, Iterable, Mapping, Sequence

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT_DEFAULT = SCRIPT_DIR.parent.parent
TOOL_VERSION = "0.1.42"
REPORT_DIR = "character_state_member_integration_audit"
REPORT_NAME = "BR_quartet_restoration_character_state_member_integration_audit_evidence.tar.zst"

STAGE123 = (
    "BR_quartet_restoration_character_asset_namespace_saturation_audit_evidence.tar.zst",
    "character_asset_namespace_saturation_audit",
    "96e1ecd852356ba10879647d056e6429604080bbe347a58e35b57d5ac27a70e4",
    "faad80893fdb47313c13483f57d36ba2bcda92319cd6e17e47bba044440b36e3",
)
INPUT_REPORTS = {
    "structural": (
        "BR_quartet_restoration_structural_evidence.tar.zst",
        "structural_evidence",
        "caf8968d7fba9476ddcf49af23166cdf865268ecc0eb353b47d9ae55b51394aa",
        "932a6364627e5d673c1e03e2092138198785fc11e0ba4a990ac7044645d14b0e",
    ),
    "material_parameter": (
        "BR_quartet_restoration_material_parameter_evidence.tar.zst",
        "material_parameter_evidence",
        "ffe6bf48ffc256ba67c3c59f920164e41781cb8f6bec242733ac7be1577488f8",
        "5f3a643783dc070992774cb2abf3c32763f79a0b2a4a15ba183e5e16ebdff182",
    ),
    "material_delta": (
        "BR_quartet_restoration_material_delta_evidence.tar.zst",
        "material_delta_evidence",
        "33feef5601bd914d9956a9ecc82e2af780af5a12cac6cc1586274046f80f7e5e",
        "fa667dc83507b7aa970fed50e30c423cff2854881253af0c23ca4a5a064c30a2",
    ),
    "wet_coverage": (
        "BR_quartet_restoration_wet_coverage_material_variant_evidence.tar.zst",
        "wet_coverage_material_variant_evidence",
        "ffd3d0a2a8fa0292dfea0e62760b531cbbec07755311c19864cc62b3eb6a50cf",
        "99c37f1a61e097579eefb7e5f475e1516043c395c26f9d00db332c1eb6d193d4",
    ),
    "structural_material": (
        "BR_quartet_restoration_structural_material_parameter_evidence.tar.zst",
        "structural_material_parameter_evidence",
        "840f42981f6c0aee0e9c264933f4771b46d337904d6db46f5f8590801041d94d",
        "292c532c5e1200eee9ce3d4cabba2869b4c298f74d017773e0efede031f263b8",
    ),
}

UNIVERSAL_TOKENS = {"nkd", "nkd_w", "scl", "scl_w", "swm", "swm_w", "tng", "udw"}
PLAYER_IDS = {f"pc{i:02d}" for i in range(15)}
HIGH_VALUE_PARAMETERS = {"frpalphathres", "frrrefractiveindex", "frrtransparency", "ftranslucency"}
EXPECTED = {
    "universal_family_rows": 120,
    "universal_asset_file_rows": 240,
    "covered_family_rows": 39,
    "uncovered_family_rows": 81,
    "covered_token_rows": 3,
    "covered_character_rows": 13,
    "earc_context_rows": 45,
    "earc_member_count_sum": 351,
    "variant_comparison_rows": 427,
    "variant_member_identity_rows": 339,
    "material_group_rows": 171,
    "material_group_identity_rows": 149,
    "chunk_rows": 824,
    "parameter_rows": 4242,
    "parameter_member_identity_rows": 146,
    "high_value_parameter_rows": 254,
    "semantic_rows": 3534,
    "base_semantic_rows": 943,
    "variant_semantic_rows": 2591,
    "base_high_value_rows": 18,
    "base_high_value_family_rows": 15,
    "focused_rows": 1347,
    "wet_rows": 1072,
    "wet_high_value_rows": 32,
    "wet_direct_ready_rows": 0,
    "three_way_rows": 1391,
    "structural_material_overlap_rows": 0,
    "face_rig_rows": 4,
}


class AuditError(RuntimeError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AuditError(message)


def progress(message: str) -> None:
    print(f"[character-state-integration] {message}", file=sys.stderr, flush=True)


def version_tuple(value: str) -> tuple[int, ...]:
    try:
        return tuple(int(part) for part in value.strip().split("."))
    except ValueError as exc:
        raise AuditError(f"invalid workstream version: {value}") from exc


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


def joined(values: Iterable[str]) -> str:
    return ";".join(sorted({str(value) for value in values if str(value)}))


def extract_report(archive: Path, expected_root: str, expected_archive_sha: str, expected_summary_sha: str, destination: Path) -> tuple[Path, str, str]:
    require(archive.is_file(), f"missing prerequisite report: {archive}")
    archive_sha = sha256_file(archive)
    require(archive_sha == expected_archive_sha, f"unexpected report SHA-256 for {archive.name}: {archive_sha}")
    listed = subprocess.run(["tar", "--zstd", "-tf", str(archive)], text=True, capture_output=True)
    require(listed.returncode == 0, listed.stderr.strip() or f"cannot list {archive}")
    names = [safe_relative(line.strip(), "archive member") for line in listed.stdout.splitlines() if line.strip()]
    require(names, f"empty report archive: {archive}")
    require({PurePosixPath(name).parts[0] for name in names} == {expected_root}, f"unexpected report root in {archive}")
    destination.mkdir(parents=True, exist_ok=True)
    completed = subprocess.run(["tar", "--zstd", "-xf", str(archive), "-C", str(destination)], text=True, capture_output=True)
    require(completed.returncode == 0, completed.stderr.strip() or f"cannot extract {archive}")
    root = destination / expected_root
    summary = root / "SUMMARY.json"
    require(summary.is_file(), f"missing SUMMARY.json in {archive}")
    summary_sha = sha256_file(summary)
    require(summary_sha == expected_summary_sha, f"unexpected summary SHA-256 for {archive.name}: {summary_sha}")
    return root, archive_sha, summary_sha


def make_archive(source: Path, output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(output.name + ".tmp")
    temporary.unlink(missing_ok=True)
    completed = subprocess.run(["tar", "--zstd", "-cf", str(temporary), "-C", str(source.parent), source.name], text=True, capture_output=True)
    require(completed.returncode == 0, completed.stderr.strip() or "report archive creation failed")
    os.replace(temporary, output)


def is_true(value: str) -> bool:
    return str(value).casefold() == "true"


def build_report(
    project_root: Path,
    *,
    report_root: Path | None = None,
    output_report_root: Path | None = None,
    create_archive: bool = True,
) -> tuple[Path | None, dict[str, Any]]:
    project_root = project_root.resolve()
    version_path = project_root / "workstreams/quartet_restoration/VERSION"
    require(version_path.is_file(), f"missing VERSION: {version_path}")
    actual_version = version_path.read_text(encoding="utf-8").strip()
    require(version_tuple(actual_version) >= version_tuple(TOOL_VERSION), f"expected quartet_restoration {TOOL_VERSION} or newer, found {actual_version}")

    report_root = (report_root or project_root / ".local/reports/quartet_restoration").resolve()
    output_report_root = (output_report_root or report_root).resolve()
    output = output_report_root / REPORT_DIR
    archive = output_report_root / REPORT_NAME
    if output.exists():
        import shutil
        shutil.rmtree(output)
    output.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="stage124-inputs-") as temp_name:
        temp = Path(temp_name)
        stage123_name, stage123_dir, stage123_archive_sha, stage123_summary_sha = STAGE123
        stage123_root, _, _ = extract_report(report_root / stage123_name, stage123_dir, stage123_archive_sha, stage123_summary_sha, temp / "stage123")
        roots: dict[str, Path] = {}
        input_hash_rows: list[dict[str, Any]] = [{
            "input_id": "stage123",
            "archive_name": stage123_name,
            "archive_sha256": stage123_archive_sha,
            "expected_archive_sha256": stage123_archive_sha,
            "summary_sha256": stage123_summary_sha,
            "expected_summary_sha256": stage123_summary_sha,
            "verified": True,
        }]
        for input_id, (name, root_name, archive_sha, summary_sha) in INPUT_REPORTS.items():
            root, _, _ = extract_report(report_root / name, root_name, archive_sha, summary_sha, temp / input_id)
            roots[input_id] = root
            input_hash_rows.append({
                "input_id": input_id,
                "archive_name": name,
                "archive_sha256": archive_sha,
                "expected_archive_sha256": archive_sha,
                "summary_sha256": summary_sha,
                "expected_summary_sha256": summary_sha,
                "verified": True,
            })

        changed_rows = read_tsv(stage123_root / "PLAYER_CHARACTER_CHANGED_STATE_FAMILIES.tsv")
        universal = [row for row in changed_rows if row["state_token"] in UNIVERSAL_TOKENS]
        require(len(universal) == EXPECTED["universal_family_rows"], f"universal family count drift: {len(universal)}")
        require({row["character_id"] for row in universal} == PLAYER_IDS, "player ID set drift")
        require({row["state_token"] for row in universal} == UNIVERSAL_TOKENS, "universal state token drift")
        require(sum(int(row["asset_file_rows"]) for row in universal) == EXPECTED["universal_asset_file_rows"], "universal asset count drift")
        by_archive = {row["logical_path"] + ".elixir.gz": row for row in universal}
        require(len(by_archive) == EXPECTED["universal_family_rows"], "duplicate universal archive paths")

        target_rows = read_tsv(stage123_root / "TARGET_ONLY_CHARACTER_FAMILY_COVERAGE.tsv")
        face_rigs = [row for row in target_rows if row["static_disposition"] == "new_target_only_face_rig_support_asset"]
        require(len(face_rigs) == EXPECTED["face_rig_rows"], "face-rig row drift")

        earc_rows = read_tsv(roots["structural"] / "ELIXIR_ARCHIVES.tsv")
        variant_rows = read_tsv(roots["structural"] / "VARIANT_MEMBER_COMPARISON.tsv")
        chunk_rows = read_tsv(roots["material_parameter"] / "G1M_CHUNKS.tsv")
        parameter_rows = read_tsv(roots["material_parameter"] / "G1M_SHADER_PARAMETERS.tsv")
        semantic_rows = read_tsv(roots["material_delta"] / "SEMANTIC_PARAMETER_DIFF.tsv")
        three_way_rows = read_tsv(roots["material_delta"] / "THREE_WAY_VARIANT_PARAMETERS.tsv")
        focused_rows = read_tsv(roots["material_delta"] / "FOCUSED_MATERIAL_REVIEW.tsv")
        wet_rows = read_tsv(roots["wet_coverage"] / "WET_COVERAGE_MATERIAL_ROWS.tsv")
        group_rows = read_tsv(roots["wet_coverage"] / "MATERIAL_MEMBER_GROUPS.tsv")
        structural_material_rows = read_tsv(roots["structural_material"] / "STRUCTURAL_MATERIAL_MEMBERS.tsv")

        earc_by_path: dict[str, list[dict[str, str]]] = defaultdict(list)
        for row in earc_rows:
            if row["normalized_path"] in by_archive:
                earc_by_path[row["normalized_path"]].append(row)

        chunks_by_path: dict[str, list[dict[str, str]]] = defaultdict(list)
        for row in chunk_rows:
            if row["archive_path"] in by_archive:
                chunks_by_path[row["archive_path"]].append(row)

        params_by_path: dict[str, list[dict[str, str]]] = defaultdict(list)
        for row in parameter_rows:
            if row["archive_path"] in by_archive:
                params_by_path[row["archive_path"]].append(row)

        groups_by_path: dict[str, list[dict[str, str]]] = defaultdict(list)
        for row in group_rows:
            if row["archive_path"] in by_archive:
                groups_by_path[row["archive_path"]].append(row)

        variant_by_path: dict[str, list[tuple[str, dict[str, str]]]] = defaultdict(list)
        member_ledger: dict[tuple[str, str], dict[str, Any]] = {}
        for row in variant_rows:
            for side, path_field, member_field in (
                ("candidate", "candidate_path", "candidate_member_name"),
                ("counterpart", "counterpart_path", "counterpart_member_name"),
            ):
                path = row[path_field]
                if path not in by_archive:
                    continue
                variant_by_path[path].append((side, row))
                key = (path, row[member_field].casefold())
                entry = member_ledger.setdefault(key, {
                    "archive_path": path,
                    "member_name": row[member_field],
                    "variant_comparison_rows": 0,
                    "variant_classifications": set(),
                    "material_group_rows": 0,
                    "material_parameter_rows": 0,
                    "g1m_chunk_rows": 0,
                })
                entry["variant_comparison_rows"] += 1
                entry["variant_classifications"].add(row["classification"])

        for row in group_rows:
            path = row["archive_path"]
            if path not in by_archive:
                continue
            key = (path, row["member_name"].casefold())
            entry = member_ledger.setdefault(key, {
                "archive_path": path,
                "member_name": row["member_name"],
                "variant_comparison_rows": 0,
                "variant_classifications": set(),
                "material_group_rows": 0,
                "material_parameter_rows": 0,
                "g1m_chunk_rows": 0,
            })
            entry["material_group_rows"] += 1

        for row in parameter_rows:
            path = row["archive_path"]
            if path not in by_archive:
                continue
            key = (path, row["member_name"].casefold())
            entry = member_ledger.setdefault(key, {
                "archive_path": path,
                "member_name": row["member_name"],
                "variant_comparison_rows": 0,
                "variant_classifications": set(),
                "material_group_rows": 0,
                "material_parameter_rows": 0,
                "g1m_chunk_rows": 0,
            })
            entry["material_parameter_rows"] += 1

        for row in chunk_rows:
            path = row["archive_path"]
            if path not in by_archive:
                continue
            key = (path, row["member_name"].casefold())
            entry = member_ledger.setdefault(key, {
                "archive_path": path,
                "member_name": row["member_name"],
                "variant_comparison_rows": 0,
                "variant_classifications": set(),
                "material_group_rows": 0,
                "material_parameter_rows": 0,
                "g1m_chunk_rows": 0,
            })
            entry["g1m_chunk_rows"] += 1

        semantic_by_path: dict[str, list[dict[str, str]]] = defaultdict(list)
        for row in semantic_rows:
            paths = {row.get("source_archive_path", ""), row.get("target_archive_path", "")}
            for path in paths & by_archive.keys():
                semantic_by_path[path].append(row)

        three_by_path: dict[str, list[dict[str, str]]] = defaultdict(list)
        for row in three_way_rows:
            paths = {row.get("original_base_archive_path", ""), row.get("quartet_base_archive_path", "")}
            for path in paths & by_archive.keys():
                three_by_path[path].append(row)

        focused_by_path: dict[str, list[dict[str, str]]] = defaultdict(list)
        for row in focused_rows:
            paths = {row.get(field, "") for field in (
                "source_archive_path", "target_archive_path", "original_base_archive_path", "quartet_base_archive_path", "quartet_variant_archive_path"
            )}
            for path in paths & by_archive.keys():
                focused_by_path[path].append(row)

        wet_by_path: dict[str, list[dict[str, str]]] = defaultdict(list)
        for row in wet_rows:
            paths = {row.get(field, "") for field in ("source_archive_path", "target_archive_path", "quartet_variant_archive_path")}
            for path in paths & by_archive.keys():
                wet_by_path[path].append(row)

        structural_material_by_path: dict[str, list[dict[str, str]]] = defaultdict(list)
        for row in structural_material_rows:
            if row["archive_path"] in by_archive:
                structural_material_by_path[row["archive_path"]].append(row)

        covered_paths = set(groups_by_path)
        require(len(covered_paths) == EXPECTED["covered_family_rows"], f"covered family count drift: {len(covered_paths)}")
        require(len(by_archive) - len(covered_paths) == EXPECTED["uncovered_family_rows"], "uncovered family count drift")
        require({by_archive[path]["state_token"] for path in covered_paths} == {"nkd", "tng", "udw"}, "covered state token set drift")
        require({by_archive[path]["character_id"] for path in covered_paths} == PLAYER_IDS - {"pc08", "pc12"}, "covered character set drift")

        family_ledger: list[dict[str, Any]] = []
        for path, source in sorted(by_archive.items()):
            family_params = params_by_path.get(path, [])
            family_semantic = semantic_by_path.get(path, [])
            base_semantic = [row for row in family_semantic if row.get("relation") == "original_base_vs_quartet_base" and row.get("source_archive_path") == path and row.get("target_archive_path") == path]
            high_value = [row for row in family_params if row["parameter_name"].casefold() in HIGH_VALUE_PARAMETERS]
            base_high_value = [row for row in base_semantic if row["parameter_name"].casefold() in HIGH_VALUE_PARAMETERS]
            covered = path in covered_paths
            family_ledger.append({
                "character_id": source["character_id"],
                "state_token": source["state_token"],
                "logical_path": source["logical_path"],
                "archive_path": path,
                "asset_file_rows": source["asset_file_rows"],
                "source_sha256s": source["source_sha256s"],
                "target_sha256s": source["target_sha256s"],
                "earc_context_rows": len(earc_by_path.get(path, [])),
                "earc_declared_member_rows": sum(int(row["member_count"]) for row in earc_by_path.get(path, [])),
                "variant_comparison_rows": len(variant_by_path.get(path, [])),
                "material_member_group_rows": len(groups_by_path.get(path, [])),
                "g1m_chunk_rows": len(chunks_by_path.get(path, [])),
                "g1m_parameter_rows": len(family_params),
                "high_value_parameter_rows": len(high_value),
                "high_value_parameter_names": joined(row["parameter_name"] for row in high_value),
                "semantic_material_rows": len(family_semantic),
                "base_semantic_material_rows": len(base_semantic),
                "base_high_value_parameter_rows": len(base_high_value),
                "three_way_variant_rows": len(three_by_path.get(path, [])),
                "focused_material_rows": len(focused_by_path.get(path, [])),
                "wet_coverage_material_rows": len(wet_by_path.get(path, [])),
                "structural_material_member_rows": len(structural_material_by_path.get(path, [])),
                "existing_member_integration_complete": covered,
                "coverage_classification": "exact_existing_earc_and_material_member_coverage" if covered else "not_present_in_existing_member_rehydration_scope",
                "runtime_confirmed": False,
                "visual_or_censorship_semantics_confirmed": False,
                "write_authorized": False,
                "next_gate": "cross_state_and_cross_character_static_delta_classification" if covered else "dedicated_exact_member_rehydration_collector_required",
            })

        token_rows: list[dict[str, Any]] = []
        for token in sorted(UNIVERSAL_TOKENS):
            rows = [row for row in family_ledger if row["state_token"] == token]
            covered = [row for row in rows if row["existing_member_integration_complete"]]
            token_rows.append({
                "state_token": token,
                "logical_family_rows": len(rows),
                "asset_file_rows": sum(int(row["asset_file_rows"]) for row in rows),
                "covered_family_rows": len(covered),
                "uncovered_family_rows": len(rows) - len(covered),
                "covered_character_ids": joined(row["character_id"] for row in covered),
                "coverage_complete": len(covered) == len(rows),
                "runtime_confirmed_rows": 0,
                "write_authorized_rows": 0,
            })

        character_rows: list[dict[str, Any]] = []
        for pc in sorted(PLAYER_IDS):
            rows = [row for row in family_ledger if row["character_id"] == pc]
            covered = [row for row in rows if row["existing_member_integration_complete"]]
            character_rows.append({
                "character_id": pc,
                "logical_family_rows": len(rows),
                "covered_family_rows": len(covered),
                "uncovered_family_rows": len(rows) - len(covered),
                "covered_state_tokens": joined(row["state_token"] for row in covered),
                "uncovered_state_tokens": joined(row["state_token"] for row in rows if not row["existing_member_integration_complete"]),
                "coverage_complete": len(covered) == len(rows),
                "runtime_confirmed_rows": 0,
                "write_authorized_rows": 0,
            })

        member_rows: list[dict[str, Any]] = []
        for entry in sorted(member_ledger.values(), key=lambda row: (row["archive_path"], row["member_name"].casefold())):
            source = by_archive[entry["archive_path"]]
            member_rows.append({
                "character_id": source["character_id"],
                "state_token": source["state_token"],
                "archive_path": entry["archive_path"],
                "member_name": entry["member_name"],
                "variant_comparison_rows": entry["variant_comparison_rows"],
                "variant_classifications": joined(entry["variant_classifications"]),
                "material_member_group_rows": entry["material_group_rows"],
                "material_parameter_rows": entry["material_parameter_rows"],
                "g1m_chunk_rows": entry["g1m_chunk_rows"],
                "exact_identity_from_existing_evidence": True,
                "semantics_confirmed": False,
                "write_authorized": False,
            })

        face_rig_rows: list[dict[str, Any]] = []
        all_known_paths = set(earc_by_path) | set(params_by_path) | set(groups_by_path)
        for row in sorted(face_rigs, key=lambda value: value["logical_path"]):
            archive_path = row["logical_path"] + ".elixir.gz"
            face_rig_rows.append({
                "logical_path": row["logical_path"],
                "archive_path": archive_path,
                "target_sha256s": row["target_sha256s"],
                "existing_earc_context_rows": len(earc_by_path.get(archive_path, [])),
                "existing_material_parameter_rows": len(params_by_path.get(archive_path, [])),
                "existing_member_integration_present": archive_path in all_known_paths,
                "static_disposition": "separate_exact_face_rig_member_table_audit_required",
                "expression_or_visual_semantics_confirmed": False,
                "write_authorized": False,
            })
        require(not any(is_true(row["existing_member_integration_present"]) for row in face_rig_rows), "face-rig unexpectedly present in existing ledgers")

        semantic_hits = [row for row in semantic_rows if row.get("source_archive_path") in by_archive or row.get("target_archive_path") in by_archive]
        base_semantic_hits = [row for row in semantic_hits if row.get("relation") == "original_base_vs_quartet_base" and row.get("source_archive_path") in by_archive and row.get("target_archive_path") in by_archive]
        variant_semantic_hits = [row for row in semantic_hits if row.get("relation") == "quartet_base_vs_quartet_variant"]
        parameter_hits = [row for row in parameter_rows if row["archive_path"] in by_archive]
        group_hits = [row for row in group_rows if row["archive_path"] in by_archive]
        chunk_hits = [row for row in chunk_rows if row["archive_path"] in by_archive]
        earc_hits = [row for row in earc_rows if row["normalized_path"] in by_archive]
        focused_hits = [row for row in focused_rows if any(row.get(field) in by_archive for field in (
            "source_archive_path", "target_archive_path", "original_base_archive_path", "quartet_base_archive_path", "quartet_variant_archive_path"
        ))]
        wet_hits = [row for row in wet_rows if any(row.get(field) in by_archive for field in ("source_archive_path", "target_archive_path", "quartet_variant_archive_path"))]
        three_hits = [row for row in three_way_rows if row.get("original_base_archive_path") in by_archive or row.get("quartet_base_archive_path") in by_archive]
        structural_overlap = [row for row in structural_material_rows if row["archive_path"] in by_archive]

        require(len(earc_hits) == EXPECTED["earc_context_rows"], "EARC context row drift")
        require(sum(int(row["member_count"]) for row in earc_hits) == EXPECTED["earc_member_count_sum"], "EARC member count drift")
        require(sum(len(rows) for rows in variant_by_path.values()) == EXPECTED["variant_comparison_rows"], "variant comparison count drift")
        require(len({(row["archive_path"], row["member_name"].casefold()) for row in member_rows if int(row["variant_comparison_rows"])}) == EXPECTED["variant_member_identity_rows"], "variant member identity drift")
        require(len(group_hits) == EXPECTED["material_group_rows"], "material group row drift")
        require(len({(row["archive_path"], row["member_name"].casefold()) for row in group_hits}) == EXPECTED["material_group_identity_rows"], "material group identity drift")
        require(len(chunk_hits) == EXPECTED["chunk_rows"], "chunk row drift")
        require(len(parameter_hits) == EXPECTED["parameter_rows"], "parameter row drift")
        require(len({(row["archive_path"], row["member_name"].casefold()) for row in parameter_hits}) == EXPECTED["parameter_member_identity_rows"], "parameter member identity drift")
        require(sum(row["parameter_name"].casefold() in HIGH_VALUE_PARAMETERS for row in parameter_hits) == EXPECTED["high_value_parameter_rows"], "high-value parameter row drift")
        require(len(semantic_hits) == EXPECTED["semantic_rows"], "semantic row drift")
        require(len(base_semantic_hits) == EXPECTED["base_semantic_rows"], "base semantic row drift")
        require(len(variant_semantic_hits) == EXPECTED["variant_semantic_rows"], "variant semantic row drift")
        require(sum(row["parameter_name"].casefold() in HIGH_VALUE_PARAMETERS for row in base_semantic_hits) == EXPECTED["base_high_value_rows"], "base high-value row drift")
        require(len({row["source_archive_path"] for row in base_semantic_hits if row["parameter_name"].casefold() in HIGH_VALUE_PARAMETERS}) == EXPECTED["base_high_value_family_rows"], "base high-value family drift")
        require(len(focused_hits) == EXPECTED["focused_rows"], "focused material row drift")
        require(len(wet_hits) == EXPECTED["wet_rows"], "wet row drift")
        require(sum(is_true(row["high_value_parameter"]) for row in wet_hits) == EXPECTED["wet_high_value_rows"], "wet high-value row drift")
        require(sum(is_true(row["direct_value_ready"]) for row in wet_hits) == EXPECTED["wet_direct_ready_rows"], "direct-ready row drift")
        require(len(three_hits) == EXPECTED["three_way_rows"], "three-way row drift")
        require(len(structural_overlap) == EXPECTED["structural_material_overlap_rows"], "structural material overlap drift")

        gap_rows = [
            {
                "gap_id": "uncovered_wet_school_swim_state_families",
                "priority": "critical",
                "affected_logical_family_rows": 75,
                "affected_asset_file_rows": 150,
                "bounded_result": "nkd_w, scl, scl_w, swm and swm_w have zero exact archive coverage in the existing member/material reports for every pc00-pc14 slot",
                "blocking_fact": "the historical focused material scope did not rehydrate these universal states",
                "safe_next_discovery": "run one exact read-only EARC/member/material collector over all 75 paths using local proprietary inputs",
                "runtime_or_save_required": False,
                "proprietary_static_inputs_required": True,
                "write_authorized": False,
            },
            {
                "gap_id": "pc08_pc12_base_state_member_coverage",
                "priority": "critical",
                "affected_logical_family_rows": 6,
                "affected_asset_file_rows": 12,
                "bounded_result": "pc08 and pc12 nkd, tng and udw are changed in the namespace ledger but absent from historical exact member rehydration",
                "blocking_fact": "existing candidate-pair material reports covered the other thirteen character slots only",
                "safe_next_discovery": "include these six paths in the same exact static rehydration collector",
                "runtime_or_save_required": False,
                "proprietary_static_inputs_required": True,
                "write_authorized": False,
            },
            {
                "gap_id": "covered_base_state_semantic_classification",
                "priority": "critical",
                "affected_logical_family_rows": 39,
                "affected_asset_file_rows": 78,
                "bounded_result": "exact EARC and material evidence exists for nkd, tng and udw in thirteen character slots, including 943 base-to-base semantic parameter rows",
                "blocking_fact": "parameter and member differences are not yet separated into systematic remaster changes versus restoration-relevant changes",
                "safe_next_discovery": "classify exact cross-character and cross-state recurrent delta shapes after the missing 81 paths are brought into the same ledger",
                "runtime_or_save_required": False,
                "proprietary_static_inputs_required": False,
                "write_authorized": False,
            },
            {
                "gap_id": "target_only_face_rig_member_tables",
                "priority": "medium",
                "affected_logical_family_rows": 4,
                "affected_asset_file_rows": 4,
                "bounded_result": "none of the four target-only face-rig support paths appears in the existing EARC or material ledgers",
                "blocking_fact": "path/hash presence alone does not identify route relationships or expression behavior",
                "safe_next_discovery": "rehydrate exact face-rig member tables separately and compare retained siblings without assigning expression semantics",
                "runtime_or_save_required": False,
                "proprietary_static_inputs_required": True,
                "write_authorized": False,
            },
            {
                "gap_id": "coverage_selector_binding_deferred",
                "priority": "critical",
                "affected_logical_family_rows": 19,
                "affected_asset_file_rows": 38,
                "bounded_result": "selector binding for towel, swimsuit and underwear coverage variants remains unresolved",
                "blocking_fact": "the universal state ledger is still incomplete at member level",
                "safe_next_discovery": "complete exact member coverage first, then resume index/hash/table selector binding",
                "runtime_or_save_required": False,
                "proprietary_static_inputs_required": False,
                "write_authorized": False,
            },
        ]

        summary = {
            "type": "br_quartet_restoration_character_state_member_integration_audit_evidence_summary",
            "format_version": 1,
            "tool_version": TOOL_VERSION,
            "status": "universal_character_state_existing_member_ledgers_integrated_39_of_120_covered_81_static_rehydration_gaps_no_write",
            "stage123_report_sha256": STAGE123[2],
            "stage123_summary_sha256": STAGE123[3],
            "universal_state_token_rows": len(UNIVERSAL_TOKENS),
            "universal_character_rows": len(PLAYER_IDS),
            "universal_logical_family_rows": len(family_ledger),
            "universal_asset_file_rows": sum(int(row["asset_file_rows"]) for row in family_ledger),
            "existing_member_coverage_family_rows": len(covered_paths),
            "missing_existing_member_coverage_family_rows": len(family_ledger) - len(covered_paths),
            "existing_member_coverage_percent": round(100.0 * len(covered_paths) / len(family_ledger), 2),
            "covered_state_token_rows": len({by_archive[path]["state_token"] for path in covered_paths}),
            "covered_character_rows": len({by_archive[path]["character_id"] for path in covered_paths}),
            "fully_uncovered_state_token_rows": 5,
            "partially_uncovered_base_state_character_rows": 2,
            "earc_context_rows": len(earc_hits),
            "earc_declared_member_rows": sum(int(row["member_count"]) for row in earc_hits),
            "variant_member_comparison_rows": sum(len(rows) for rows in variant_by_path.values()),
            "variant_member_identity_rows": len({(row["archive_path"], row["member_name"].casefold()) for row in member_rows if int(row["variant_comparison_rows"])}),
            "variant_member_classification_counts": dict(sorted(Counter(row["classification"] for row in variant_rows if row.get("candidate_path") in by_archive or row.get("counterpart_path") in by_archive).items())),
            "material_member_group_rows": len(group_hits),
            "material_member_identity_rows": len({(row["archive_path"], row["member_name"].casefold()) for row in group_hits}),
            "g1m_chunk_rows": len(chunk_hits),
            "g1m_parameter_rows": len(parameter_hits),
            "g1m_parameter_member_identity_rows": len({(row["archive_path"], row["member_name"].casefold()) for row in parameter_hits}),
            "high_value_parameter_rows": sum(row["parameter_name"].casefold() in HIGH_VALUE_PARAMETERS for row in parameter_hits),
            "high_value_parameter_name_counts": dict(sorted(Counter(row["parameter_name"] for row in parameter_hits if row["parameter_name"].casefold() in HIGH_VALUE_PARAMETERS).items())),
            "semantic_material_rows": len(semantic_hits),
            "base_to_base_semantic_material_rows": len(base_semantic_hits),
            "quartet_base_to_variant_semantic_rows": len(variant_semantic_hits),
            "base_to_base_semantic_classification_counts": dict(sorted(Counter(row["classification"] for row in base_semantic_hits).items())),
            "base_high_value_parameter_rows": sum(row["parameter_name"].casefold() in HIGH_VALUE_PARAMETERS for row in base_semantic_hits),
            "base_high_value_family_rows": len({row["source_archive_path"] for row in base_semantic_hits if row["parameter_name"].casefold() in HIGH_VALUE_PARAMETERS}),
            "focused_material_rows": len(focused_hits),
            "wet_coverage_material_rows": len(wet_hits),
            "wet_coverage_high_value_rows": sum(is_true(row["high_value_parameter"]) for row in wet_hits),
            "direct_numeric_restore_candidate_rows": sum(is_true(row["direct_value_ready"]) for row in wet_hits),
            "three_way_variant_rows": len(three_hits),
            "structural_material_overlap_rows": len(structural_overlap),
            "target_only_face_rig_rows": len(face_rig_rows),
            "target_only_face_rig_existing_member_coverage_rows": sum(is_true(row["existing_member_integration_present"]) for row in face_rig_rows),
            "runtime_confirmed_rows": 0,
            "write_authorized_rows": 0,
            "universal_member_integration_complete": False,
            "coverage_selector_binding_complete": False,
            "global_discovery_saturation_achieved": False,
            "policy": {
                "existing_evidence_only": True,
                "proprietary_payload_rehydrated": False,
                "member_names_hashes_and_numeric_metadata_only": True,
                "visual_or_censorship_semantics_assigned": False,
                "runtime_validation_inferred": False,
                "save_or_runtime_required_for_next_step": False,
                "pak_built_or_repacked": False,
                "profile_or_registry_modified": False,
                "core_modified": False,
                "translation_modified": False,
                "legacy_dlc_modified": False,
                "installed_game_modified": False,
                "git_modified": False,
            },
            "next_action": "Build one fail-closed read-only exact character-state rehydration collector for the 81 missing universal paths (all nkd_w/scl/scl_w/swm/swm_w plus pc08/pc12 nkd/tng/udw) and a separate four-path face-rig member-table audit. Use local proprietary inputs, emit metadata only, require no saves, and do not resume broad runtime composition or selector binding until all 120 universal families share one exact member ledger.",
        }

        write_tsv(output / "UNIVERSAL_CHARACTER_STATE_INTEGRATION.tsv", list(family_ledger[0]), family_ledger)
        write_tsv(output / "UNIVERSAL_STATE_TOKEN_COVERAGE.tsv", list(token_rows[0]), token_rows)
        write_tsv(output / "UNIVERSAL_STATE_CHARACTER_COVERAGE.tsv", list(character_rows[0]), character_rows)
        write_tsv(output / "UNIVERSAL_STATE_MEMBER_IDENTITIES.tsv", list(member_rows[0]), member_rows)
        write_tsv(output / "FACE_RIG_SUPPORT_INTEGRATION.tsv", list(face_rig_rows[0]), face_rig_rows)
        write_tsv(output / "CHARACTER_STATE_INTEGRATION_GAPS.tsv", list(gap_rows[0]), gap_rows)
        write_tsv(output / "INPUT_HASHES.tsv", list(input_hash_rows[0]), input_hash_rows)
        (output / "SUMMARY.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    if create_archive:
        make_archive(output, archive)
        return archive, summary
    return None, summary


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path, default=PROJECT_ROOT_DEFAULT)
    parser.add_argument("--report-root", type=Path)
    parser.add_argument("--output-report-root", type=Path)
    parser.add_argument("--no-archive", action="store_true")
    args = parser.parse_args(argv)
    try:
        archive, summary = build_report(
            args.project_root,
            report_root=args.report_root,
            output_report_root=args.output_report_root,
            create_archive=not args.no_archive,
        )
    except AuditError as exc:
        print(f"[character-state-integration] ERROR: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(summary, indent=2, sort_keys=True))
    if archive is not None:
        progress(f"report archive: {archive}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
