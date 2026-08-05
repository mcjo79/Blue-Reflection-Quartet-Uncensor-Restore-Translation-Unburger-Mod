#!/usr/bin/env python3
"""Build a metadata-only scene/effect member-family and coverage binding audit.

Stage 122 follows the stage-121 master inventory. It does not inspect game
payloads. It deterministically groups the 586 recorded member differences by
exact binary delta identity, binds every occurrence to the existing 22 focused
scene/effect paths, and performs an exact path-only binding against the 22
coverage asset families.

An exact delta family is intentionally narrow: classification, source/target
size and source/target SHA-256 must all match. This is deduplication, not a
claim that the rows have the same visual or censorship semantics.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
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
TOOL_VERSION = "0.1.40"
REPORT_DIR = "scene_effect_member_family_binding_audit"
REPORT_NAME = "BR_quartet_restoration_scene_effect_member_family_binding_audit_evidence.tar.zst"

STAGE121_ARCHIVE = "BR_quartet_restoration_master_discovery_inventory_gap_audit_evidence.tar.zst"
STAGE121_DIR = "master_restoration_discovery_inventory_gap_audit"

INPUTS = {
    "scene_effect_candidates": (
        "scene_effect_evidence/SCENE_EFFECT_CANDIDATES.tsv",
        "070aac5582aaf469aa288b94e2dbcb8b19797cd2e10ac2393c2988a75f0b743c",
    ),
    "scene_effect_member_diff": (
        "structural_evidence/SCENE_EFFECT_MEMBER_DIFF.tsv",
        "67a2403bc61ad9d15bc578122f8eeecc30553be4c152df7a47f083e2a0343f96",
    ),
    "coverage_asset_families": (
        "reference_evidence/CANDIDATE_ASSET_FAMILIES.tsv",
        "86f6c9895189262be31c7293d6ab3a89a88d7ff7531b09bcd1080e384357f00d",
    ),
}

EXPECTED = {
    "focused_path_rows": 22,
    "paths_with_member_differences": 17,
    "paths_without_member_differences": 5,
    "member_difference_rows": 586,
    "exact_delta_family_rows": 579,
    "singleton_delta_family_rows": 573,
    "repeated_delta_family_rows": 6,
    "repeated_delta_occurrence_rows": 13,
    "deduplicated_occurrence_reduction": 7,
    "extension_rows": 9,
    "coverage_asset_family_rows": 22,
    "exact_bound_coverage_asset_rows": 3,
    "unbound_coverage_asset_rows": 19,
    "exact_coverage_path_binding_rows": 3,
    "exact_bound_member_occurrence_rows": 22,
}

EXPECTED_PATH_DOMAIN_SPLIT = Counter({
    "water_visibility": 7,
    "wet_fabric_material_response": 6,
    "steam_and_wet_clothing": 4,
    "steam_and_water_visibility": 3,
    "steam_or_vapor_occlusion": 2,
})

EXPECTED_OCCURRENCE_EXTENSION_SPLIT = Counter({
    ".g1e": 504,
    ".g1m": 29,
    ".kps": 27,
    ".g1t": 9,
    ".bin": 4,
    ".g1em": 4,
    ".opl2": 3,
    ".swg": 3,
    "(none)": 3,
})

EXPECTED_FAMILY_EXTENSION_SPLIT = Counter({
    ".g1e": 501,
    ".g1m": 29,
    ".kps": 26,
    ".g1t": 8,
    ".bin": 4,
    ".g1em": 4,
    ".opl2": 3,
    ".swg": 3,
    "(none)": 1,
})

EXPECTED_EXACT_BOUND_TOKENS = {"pc00_rfl_w", "pc01_rfl_w", "pc02_rfl_w"}
EXPECTED_NO_MEMBER_PATHS = {
    "data/x64/shader/cwater.g1s",
    "data/x64/shader/cwater2.g1s",
    "data/x64/shader/heightfog.g1s",
    "data/x64/shader/swater.g1s",
    "data/x64/shader/texture/caustics.g1t",
}


class AuditError(RuntimeError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AuditError(message)


def progress(message: str) -> None:
    print(f"[scene-effect-family-binding] {message}", file=sys.stderr, flush=True)


def parse_int(value: Any, default: int = 0) -> int:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return default


def version_tuple(value: str) -> tuple[int, ...]:
    try:
        return tuple(int(part) for part in value.strip().split("."))
    except ValueError as exc:
        raise AuditError(f"invalid workstream version: {value}") from exc


def parse_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().casefold() in {"1", "true", "yes", "y"}


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


def load_json(path: Path) -> dict[str, Any]:
    require(path.is_file(), f"missing required JSON: {path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise AuditError(f"invalid JSON {path}: {exc}") from exc
    require(isinstance(value, dict), f"JSON root must be object: {path}")
    return value


def read_tsv(path: Path) -> list[dict[str, str]]:
    require(path.is_file(), f"missing required TSV: {path}")
    with path.open(encoding="utf-8", newline="") as handle:
        rows = [dict(row) for row in csv.DictReader(handle, delimiter="\t")]
    require(rows, f"empty required TSV: {path}")
    return rows


def write_tsv(path: Path, fields: Sequence[str], rows: Iterable[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=list(fields),
            delimiter="\t",
            lineterminator="\n",
            extrasaction="ignore",
        )
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fields})


def extract_archive(archive: Path, destination: Path) -> Path:
    require(archive.is_file(), f"missing prerequisite report archive: {archive}")
    listed = subprocess.run(["tar", "--zstd", "-tf", str(archive)], text=True, capture_output=True)
    require(listed.returncode == 0, listed.stderr.strip() or f"cannot list {archive}")
    names = [line.strip() for line in listed.stdout.splitlines() if line.strip()]
    require(names, f"empty prerequisite report: {archive}")
    roots = {PurePosixPath(safe_relative(name, "archive member")).parts[0] for name in names}
    require(len(roots) == 1, f"expected one report root in {archive}")
    destination.mkdir(parents=True, exist_ok=True)
    completed = subprocess.run(
        ["tar", "--zstd", "-xf", str(archive), "-C", str(destination)],
        text=True,
        capture_output=True,
    )
    require(completed.returncode == 0, completed.stderr.strip() or f"cannot extract {archive}")
    root = destination / next(iter(roots))
    require(root.is_dir(), f"missing extracted report root: {root}")
    return root


def locate_stage121(report_root: Path, temporary: Path) -> tuple[Path, str]:
    direct = report_root / STAGE121_DIR
    archive = report_root / STAGE121_ARCHIVE
    if direct.is_dir():
        archive_sha = sha256_file(archive) if archive.is_file() else ""
        return direct, archive_sha
    return extract_archive(archive, temporary / STAGE121_DIR), sha256_file(archive)


def locate_input_file(report_root: Path, relative: str, temporary: Path) -> Path:
    direct = report_root / relative
    if direct.is_file():
        return direct
    report_id = PurePosixPath(relative).parts[0]
    archive = report_root / f"BR_quartet_restoration_{report_id}.tar.zst"
    extracted = extract_archive(archive, temporary / f"input-{report_id}")
    candidate = extracted / PurePosixPath(relative).name
    require(candidate.is_file(), f"missing extracted input: {candidate}")
    return candidate


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


def member_extension(member_key: str) -> str:
    base = member_key.rsplit("#", 1)[0]
    suffix = PurePosixPath(base).suffix.casefold()
    return suffix or "(none)"


def delta_signature(row: Mapping[str, str]) -> tuple[str, str, str, str, str]:
    return (
        row.get("classification", ""),
        row.get("source_size", ""),
        row.get("target_size", ""),
        row.get("source_sha256", ""),
        row.get("target_sha256", ""),
    )


def delta_family_id(signature: tuple[str, str, str, str, str]) -> str:
    encoded = json.dumps(signature, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return "deltafam_" + hashlib.sha256(encoded).hexdigest()[:20]


def joined(values: Iterable[str]) -> str:
    return ";".join(sorted({value for value in values if value}))


def build_report(
    project_root: Path,
    report_root: Path | None = None,
    output_report_root: Path | None = None,
    create_archive: bool = True,
) -> tuple[Path, dict[str, Any]]:
    project_root = project_root.resolve()
    version_file = project_root / "workstreams/quartet_restoration/VERSION"
    require(version_file.is_file(), f"missing VERSION: {version_file}")
    version = version_file.read_text(encoding="utf-8").strip()
    require(version_tuple(version) >= version_tuple(TOOL_VERSION), f"expected quartet_restoration {TOOL_VERSION} or newer, found {version}")

    report_root = (report_root or project_root / ".local/reports/quartet_restoration").resolve()
    output_report_root = (output_report_root or report_root).resolve()
    output_dir = output_report_root / REPORT_DIR
    if output_dir.exists():
        shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True)

    with tempfile.TemporaryDirectory(prefix="br-stage122-") as td:
        temporary = Path(td)
        stage121_root, stage121_archive_sha = locate_stage121(report_root, temporary)
        stage121_summary_path = stage121_root / "SUMMARY.json"
        stage121_summary = load_json(stage121_summary_path)
        require(stage121_summary.get("tool_version") == "0.1.39", "stage-121 tool version drift")
        require(
            stage121_summary.get("status")
            == "master_static_discovery_inventory_consolidated_discovery_not_exhaustive_runtime_validation_deferred_no_write",
            "stage-121 status drift",
        )
        require(parse_int(stage121_summary.get("focused_scene_effect_path_rows"), -1) == 22, "stage-121 path count drift")
        require(parse_int(stage121_summary.get("scene_effect_member_difference_rows"), -1) == 586, "stage-121 member count drift")
        require(parse_int(stage121_summary.get("candidate_asset_family_rows"), -1) == 22, "stage-121 coverage count drift")
        require(not parse_bool(stage121_summary.get("discovery_exhaustive")), "stage 121 unexpectedly exhaustive")
        stage121_summary_sha = sha256_file(stage121_summary_path)
        require(
            stage121_summary_sha == "b074a9334a5f76e364e2df0a5e467c294bdd4ac636e7e5765eb4be03079e0654",
            f"stage-121 summary hash drift: {stage121_summary_sha}",
        )

        input_paths: dict[str, Path] = {}
        input_hash_rows: list[dict[str, Any]] = []
        for input_id, (relative, expected_sha) in INPUTS.items():
            path = locate_input_file(report_root, relative, temporary)
            actual_sha = sha256_file(path)
            require(actual_sha == expected_sha, f"{input_id} hash drift: {actual_sha}")
            input_paths[input_id] = path
            input_hash_rows.append({
                "input_id": input_id,
                "relative_path": relative,
                "sha256": actual_sha,
                "expected_sha256": expected_sha,
                "verified": True,
            })

        scene_rows = read_tsv(input_paths["scene_effect_candidates"])
        diff_rows = read_tsv(input_paths["scene_effect_member_diff"])
        asset_rows = read_tsv(input_paths["coverage_asset_families"])

        require(len(scene_rows) == EXPECTED["focused_path_rows"], "focused scene/effect count drift")
        require(len(diff_rows) == EXPECTED["member_difference_rows"], "member-difference count drift")
        require(len(asset_rows) == EXPECTED["coverage_asset_family_rows"], "coverage-family count drift")

        scene_by_path: dict[str, dict[str, str]] = {}
        for row in scene_rows:
            path = safe_relative(row["normalized_path"], "focused path")
            require(path not in scene_by_path, f"duplicate focused path: {path}")
            scene_by_path[path] = row
        require(Counter(row["domain"] for row in scene_rows) == EXPECTED_PATH_DOMAIN_SPLIT, "focused path domain split drift")

        occurrences_by_path: dict[str, list[dict[str, str]]] = defaultdict(list)
        family_occurrences: dict[tuple[str, str, str, str, str], list[dict[str, str]]] = defaultdict(list)
        occurrence_extension_split: Counter[str] = Counter()

        for row in diff_rows:
            path = safe_relative(row["normalized_path"], "member parent path")
            require(path in scene_by_path, f"member difference outside focused path set: {path}")
            scene = scene_by_path[path]
            require(row["candidate_id"] == scene["candidate_id"], f"candidate mismatch for {path}")
            require(row["domain"] == scene["domain"], f"domain mismatch for {path}")
            require(row["priority"] == scene["priority"], f"priority mismatch for {path}")
            safe_relative(row["member_key"], "member key")
            occurrences_by_path[path].append(row)
            family_occurrences[delta_signature(row)].append(row)
            occurrence_extension_split[member_extension(row["member_key"])] += 1

        require(occurrence_extension_split == EXPECTED_OCCURRENCE_EXTENSION_SPLIT, f"occurrence extension split drift: {dict(occurrence_extension_split)}")
        require(len(family_occurrences) == EXPECTED["exact_delta_family_rows"], "exact delta-family count drift")
        family_frequency = Counter(len(rows) for rows in family_occurrences.values())
        require(family_frequency == Counter({1: 573, 2: 5, 3: 1}), f"family-frequency drift: {dict(family_frequency)}")

        path_set = set(scene_by_path)
        path_with_rows = {path for path, rows in occurrences_by_path.items() if rows}
        path_without_rows = path_set - path_with_rows
        require(len(path_with_rows) == EXPECTED["paths_with_member_differences"], "path-with-members count drift")
        require(path_without_rows == EXPECTED_NO_MEMBER_PATHS, f"non-EARC focused path drift: {sorted(path_without_rows)}")

        asset_binding_rows: list[dict[str, Any]] = []
        coverage_tokens_by_path: dict[str, list[str]] = defaultdict(list)
        exact_path_binding_count = 0
        exact_bound_occurrences = 0
        for asset in asset_rows:
            asset_files = {safe_relative(value, "asset file") for value in asset.get("asset_files", "").split(";") if value}
            exact_paths = sorted(asset_files & path_set)
            exact_path_binding_count += len(exact_paths)
            member_rows = sum(len(occurrences_by_path[path]) for path in exact_paths)
            exact_bound_occurrences += member_rows
            for path in exact_paths:
                coverage_tokens_by_path[path].append(asset["token"])
            binding_kind = "exact_asset_file_to_focused_path" if exact_paths else "no_exact_focused_path_binding"
            disposition = (
                "exact_wet_reflector_asset_path_bound_member_semantics_and_scene_use_unresolved"
                if exact_paths
                else "structured_index_hash_or_container_binding_still_required"
            )
            asset_binding_rows.append({
                "candidate_id": asset["candidate_id"],
                "token": asset["token"],
                "family": asset["family"],
                "character_id": asset.get("character_id", ""),
                "asset_file_rows": asset.get("asset_file_count", ""),
                "exact_focused_path_binding_rows": len(exact_paths),
                "exact_focused_paths": ";".join(exact_paths),
                "bound_member_difference_rows": member_rows,
                "binding_kind": binding_kind,
                "runtime_confirmed": False,
                "semantic_binding_confirmed": False,
                "static_disposition": disposition,
            })

        exact_bound_assets = [row for row in asset_binding_rows if row["exact_focused_path_binding_rows"]]
        require({row["token"] for row in exact_bound_assets} == EXPECTED_EXACT_BOUND_TOKENS, "exact bound coverage token drift")
        require(len(exact_bound_assets) == EXPECTED["exact_bound_coverage_asset_rows"], "exact bound coverage count drift")
        require(len(asset_binding_rows) - len(exact_bound_assets) == EXPECTED["unbound_coverage_asset_rows"], "unbound coverage count drift")
        require(exact_path_binding_count == EXPECTED["exact_coverage_path_binding_rows"], "coverage path-binding count drift")
        require(exact_bound_occurrences == EXPECTED["exact_bound_member_occurrence_rows"], "bound member-occurrence count drift")

        occurrence_rows: list[dict[str, Any]] = []
        family_rows: list[dict[str, Any]] = []
        family_extension_split: Counter[str] = Counter()
        family_id_by_signature: dict[tuple[str, str, str, str, str], str] = {}

        for signature in sorted(family_occurrences):
            rows = family_occurrences[signature]
            family_id = delta_family_id(signature)
            require(family_id not in family_id_by_signature.values(), f"delta-family ID collision: {family_id}")
            family_id_by_signature[signature] = family_id
            extensions = {member_extension(row["member_key"]) for row in rows}
            require(len(extensions) == 1, f"mixed extensions in exact delta family {family_id}: {extensions}")
            extension = next(iter(extensions))
            family_extension_split[extension] += 1
            paths = sorted({safe_relative(row["normalized_path"], "family path") for row in rows})
            domains = sorted({row["domain"] for row in rows})
            tokens = sorted({token for path in paths for token in coverage_tokens_by_path.get(path, [])})
            family_rows.append({
                "delta_family_id": family_id,
                "classification": signature[0],
                "source_size": signature[1],
                "target_size": signature[2],
                "source_sha256": signature[3],
                "target_sha256": signature[4],
                "member_extension": extension,
                "occurrence_rows": len(rows),
                "focused_path_rows": len(paths),
                "focused_paths": ";".join(paths),
                "domains": ";".join(domains),
                "member_keys": joined(row["member_key"] for row in rows),
                "exact_coverage_asset_tokens": ";".join(tokens),
                "exact_coverage_binding_present": bool(tokens),
                "visual_semantics_confirmed": False,
                "deduplication_basis": "exact_classification_size_and_source_target_sha256",
            })

            for row in sorted(rows, key=lambda item: (item["normalized_path"], item["member_key"], item.get("source_member_index", ""))):
                path = safe_relative(row["normalized_path"], "occurrence path")
                tokens_for_path = sorted(coverage_tokens_by_path.get(path, []))
                occurrence_rows.append({
                    "delta_family_id": family_id,
                    "candidate_id": row["candidate_id"],
                    "focused_path": path,
                    "domain": row["domain"],
                    "priority": row["priority"],
                    "member_key": row["member_key"],
                    "member_extension": member_extension(row["member_key"]),
                    "source_member_name": row.get("source_member_name", ""),
                    "target_member_name": row.get("target_member_name", ""),
                    "source_member_index": row.get("source_member_index", ""),
                    "target_member_index": row.get("target_member_index", ""),
                    "classification": row["classification"],
                    "exact_coverage_asset_tokens": ";".join(tokens_for_path),
                    "runtime_confirmed": False,
                    "semantic_partition_confirmed": False,
                })

        require(family_extension_split == EXPECTED_FAMILY_EXTENSION_SPLIT, f"family extension split drift: {dict(family_extension_split)}")
        require(len(occurrence_rows) == EXPECTED["member_difference_rows"], "occurrence ledger count drift")
        require(len(family_rows) == EXPECTED["exact_delta_family_rows"], "family ledger count drift")
        require(len({row["delta_family_id"] for row in family_rows}) == len(family_rows), "duplicate family IDs")

        path_summary_rows: list[dict[str, Any]] = []
        for path, scene in sorted(scene_by_path.items()):
            rows = occurrences_by_path.get(path, [])
            signatures = {delta_signature(row) for row in rows}
            tokens = sorted(coverage_tokens_by_path.get(path, []))
            extensions = sorted({member_extension(row["member_key"]) for row in rows})
            if rows:
                disposition = (
                    "exact_coverage_asset_path_bound_semantics_unresolved"
                    if tokens
                    else "member_families_bounded_semantic_partition_still_required"
                )
            else:
                disposition = "focused_non_earc_path_requires_format_specific_static_audit"
            path_summary_rows.append({
                "candidate_id": scene["candidate_id"],
                "focused_path": path,
                "rule_id": scene["rule_id"],
                "domain": scene["domain"],
                "priority": scene["priority"],
                "classification": scene["classification"],
                "member_difference_rows": len(rows),
                "exact_delta_family_rows": len(signatures),
                "member_extensions": ";".join(extensions),
                "exact_coverage_asset_binding_rows": len(tokens),
                "exact_coverage_asset_tokens": ";".join(tokens),
                "runtime_confirmed": False,
                "semantic_partition_confirmed": False,
                "static_disposition": disposition,
            })

        extension_rows = []
        for extension in sorted(occurrence_extension_split):
            ext_occurrences = [row for row in occurrence_rows if row["member_extension"] == extension]
            extension_rows.append({
                "member_extension": extension,
                "occurrence_rows": occurrence_extension_split[extension],
                "exact_delta_family_rows": family_extension_split[extension],
                "focused_path_rows": len({row["focused_path"] for row in ext_occurrences}),
                "domains": joined(row["domain"] for row in ext_occurrences),
                "semantic_meaning_assigned": False,
            })

        frequency_rows = []
        for occurrence_count in sorted(family_frequency):
            family_count = family_frequency[occurrence_count]
            frequency_rows.append({
                "occurrences_per_exact_delta_family": occurrence_count,
                "exact_delta_family_rows": family_count,
                "member_occurrence_rows": occurrence_count * family_count,
                "interpretation": (
                    "singleton_exact_binary_delta"
                    if occurrence_count == 1
                    else "repeated_exact_binary_delta_not_visual_semantics_proof"
                ),
            })

        repeated_families = sum(1 for rows in family_occurrences.values() if len(rows) > 1)
        repeated_occurrences = sum(len(rows) for rows in family_occurrences.values() if len(rows) > 1)
        singleton_families = sum(1 for rows in family_occurrences.values() if len(rows) == 1)
        reduction = len(diff_rows) - len(family_occurrences)
        require(singleton_families == EXPECTED["singleton_delta_family_rows"], "singleton family count drift")
        require(repeated_families == EXPECTED["repeated_delta_family_rows"], "repeated family count drift")
        require(repeated_occurrences == EXPECTED["repeated_delta_occurrence_rows"], "repeated occurrence count drift")
        require(reduction == EXPECTED["deduplicated_occurrence_reduction"], "deduplication reduction drift")

        gap_rows = [
            {
                "gap_id": "scene_effect_binary_delta_semantics",
                "priority": "critical",
                "affected_rows": len(family_rows),
                "bounded_result": "exact delta families established without visual labels",
                "blocking_fact": "exact binary equality deduplicates only seven occurrences and cannot separate censorship from remaster changes",
                "safe_next_discovery": "cross-container and sibling-control classification by exact format structure per extension",
                "runtime_or_save_required": False,
                "write_authorized": False,
            },
            {
                "gap_id": "focused_non_earc_paths",
                "priority": "critical",
                "affected_rows": len(path_without_rows),
                "bounded_result": "five focused shader or texture paths have no EARC member rows by design",
                "blocking_fact": "the EARC member ledger cannot represent standalone G1S or G1T paths",
                "safe_next_discovery": "reuse existing shader and texture evidence in format-specific static audits",
                "runtime_or_save_required": False,
                "write_authorized": False,
            },
            {
                "gap_id": "coverage_asset_exact_binding",
                "priority": "critical",
                "affected_rows": EXPECTED["unbound_coverage_asset_rows"],
                "bounded_result": "three wet Reflector asset families bind by exact file path; nineteen coverage families do not",
                "blocking_fact": "exact path equality does not locate bath-towel underwear or shower-swimsuit use sites",
                "safe_next_discovery": "structured index hash container and table binding audit for the nineteen unbound families",
                "runtime_or_save_required": False,
                "write_authorized": False,
            },
            {
                "gap_id": "wet_reflector_scene_use",
                "priority": "high",
                "affected_rows": EXPECTED["exact_bound_coverage_asset_rows"],
                "bounded_result": "pc00 pc01 and pc02 rfl_w families bind to focused paths and 22 changed members",
                "blocking_fact": "asset-path identity does not prove which events select the wet variants or what each changed member renders",
                "safe_next_discovery": "bind exact rfl_w containers to event character-state and slot selectors using non-payload metadata",
                "runtime_or_save_required": False,
                "write_authorized": False,
            },
            {
                "gap_id": "discovery_saturation",
                "priority": "critical",
                "affected_rows": len(diff_rows) + len(asset_rows),
                "bounded_result": "all current scene/effect member differences and coverage families are represented",
                "blocking_fact": "current reports remain candidate-driven and do not prove all game namespaces were exhausted",
                "safe_next_discovery": "continue systematic format-specific and index-driven scans before broad runtime composition",
                "runtime_or_save_required": False,
                "write_authorized": False,
            },
        ]

        write_tsv(
            output_dir / "SCENE_EFFECT_PATH_BINDING_SUMMARY.tsv",
            [
                "candidate_id", "focused_path", "rule_id", "domain", "priority", "classification",
                "member_difference_rows", "exact_delta_family_rows", "member_extensions",
                "exact_coverage_asset_binding_rows", "exact_coverage_asset_tokens", "runtime_confirmed",
                "semantic_partition_confirmed", "static_disposition",
            ],
            path_summary_rows,
        )
        write_tsv(
            output_dir / "SCENE_EFFECT_MEMBER_DELTA_FAMILIES.tsv",
            [
                "delta_family_id", "classification", "source_size", "target_size", "source_sha256",
                "target_sha256", "member_extension", "occurrence_rows", "focused_path_rows",
                "focused_paths", "domains", "member_keys", "exact_coverage_asset_tokens",
                "exact_coverage_binding_present", "visual_semantics_confirmed", "deduplication_basis",
            ],
            family_rows,
        )
        write_tsv(
            output_dir / "SCENE_EFFECT_MEMBER_OCCURRENCES.tsv",
            [
                "delta_family_id", "candidate_id", "focused_path", "domain", "priority", "member_key",
                "member_extension", "source_member_name", "target_member_name", "source_member_index",
                "target_member_index", "classification", "exact_coverage_asset_tokens", "runtime_confirmed",
                "semantic_partition_confirmed",
            ],
            occurrence_rows,
        )
        write_tsv(
            output_dir / "COVERAGE_ASSET_SCENE_EFFECT_BINDINGS.tsv",
            [
                "candidate_id", "token", "family", "character_id", "asset_file_rows",
                "exact_focused_path_binding_rows", "exact_focused_paths", "bound_member_difference_rows",
                "binding_kind", "runtime_confirmed", "semantic_binding_confirmed", "static_disposition",
            ],
            asset_binding_rows,
        )
        write_tsv(
            output_dir / "SCENE_EFFECT_MEMBER_EXTENSION_SUMMARY.tsv",
            [
                "member_extension", "occurrence_rows", "exact_delta_family_rows", "focused_path_rows",
                "domains", "semantic_meaning_assigned",
            ],
            extension_rows,
        )
        write_tsv(
            output_dir / "SCENE_EFFECT_DELTA_FAMILY_FREQUENCY.tsv",
            [
                "occurrences_per_exact_delta_family", "exact_delta_family_rows", "member_occurrence_rows",
                "interpretation",
            ],
            frequency_rows,
        )
        write_tsv(
            output_dir / "SCENE_EFFECT_MEMBER_FAMILY_GAPS.tsv",
            [
                "gap_id", "priority", "affected_rows", "bounded_result", "blocking_fact",
                "safe_next_discovery", "runtime_or_save_required", "write_authorized",
            ],
            gap_rows,
        )
        write_tsv(
            output_dir / "INPUT_HASHES.tsv",
            ["input_id", "relative_path", "sha256", "expected_sha256", "verified"],
            input_hash_rows,
        )

        summary: dict[str, Any] = {
            "type": "br_quartet_restoration_scene_effect_member_family_binding_audit_evidence_summary",
            "format_version": 1,
            "tool_version": TOOL_VERSION,
            "status": "scene_effect_member_differences_exactly_deduplicated_and_path_bound_coverage_binding_partial_semantics_unresolved_no_write",
            "stage121_report_sha256": stage121_archive_sha,
            "stage121_summary_sha256": stage121_summary_sha,
            "focused_scene_effect_path_rows": len(scene_rows),
            "focused_paths_with_member_difference_rows": len(path_with_rows),
            "focused_paths_without_member_difference_rows": len(path_without_rows),
            "scene_effect_member_difference_rows": len(diff_rows),
            "exact_binary_delta_family_rows": len(family_rows),
            "singleton_exact_binary_delta_family_rows": singleton_families,
            "repeated_exact_binary_delta_family_rows": repeated_families,
            "repeated_exact_binary_delta_occurrence_rows": repeated_occurrences,
            "deduplicated_occurrence_reduction_rows": reduction,
            "member_extension_rows": len(extension_rows),
            "coverage_asset_family_rows": len(asset_rows),
            "exact_bound_coverage_asset_family_rows": len(exact_bound_assets),
            "unbound_coverage_asset_family_rows": len(asset_rows) - len(exact_bound_assets),
            "exact_coverage_to_focused_path_binding_rows": exact_path_binding_count,
            "exact_bound_member_difference_rows": exact_bound_occurrences,
            "exact_bound_coverage_tokens": sorted(EXPECTED_EXACT_BOUND_TOKENS),
            "semantic_scene_effect_partition_authoritative": False,
            "coverage_scene_use_binding_complete": False,
            "discovery_saturation_achieved": False,
            "runtime_confirmed_rows": 0,
            "write_authorized_rows": 0,
            "policy": {
                "existing_evidence_only": True,
                "proprietary_payload_rehydrated": False,
                "exact_binary_delta_identity_only": True,
                "numeric_similarity_used": False,
                "opacity_brightness_or_censorship_semantics_assigned": False,
                "runtime_validation_inferred": False,
                "pak_built_or_repacked": False,
                "profile_or_registry_modified": False,
                "core_modified": False,
                "translation_modified": False,
                "legacy_dlc_modified": False,
                "installed_game_modified": False,
                "git_modified": False,
            },
            "next_action": (
                "Continue save-independent discovery. Use the exact path and delta-family ledgers to run format-specific "
                "static classification, beginning with the five standalone shader/texture paths and structured index/hash/" 
                "container binding for the nineteen coverage families that still have no exact focused-path match. Do not "
                "proceed to real Canary-all composition or infer visual semantics from binary family identity."
            ),
        }
        (output_dir / "SUMMARY.json").write_text(
            json.dumps(summary, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
            encoding="utf-8",
        )

    archive = output_report_root / REPORT_NAME
    if create_archive:
        make_archive(output_dir, archive)
    return archive, summary


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path, default=PROJECT_ROOT_DEFAULT)
    parser.add_argument("--report-root", type=Path)
    parser.add_argument("--output-report-root", type=Path)
    parser.add_argument("--no-archive", action="store_true")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        archive, summary = build_report(
            args.project_root,
            report_root=args.report_root,
            output_report_root=args.output_report_root,
            create_archive=not args.no_archive,
        )
    except AuditError as exc:
        print(f"[scene-effect-family-binding] ERROR: {exc}", file=sys.stderr)
        return 1
    progress(f"report directory: {(args.output_report_root or args.report_root or args.project_root / '.local/reports/quartet_restoration') / REPORT_DIR}")
    if not args.no_archive:
        progress(f"report archive: {archive}")
    print(json.dumps(summary, indent=2, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
