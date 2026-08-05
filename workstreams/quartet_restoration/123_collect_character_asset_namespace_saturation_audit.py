#!/usr/bin/env python3
"""Build a metadata-only character-asset namespace saturation audit.

Stage 123 performs a systematic sweep of every `data/x64/character` entry in
BR1-vs-Quartet asset-difference metadata. It answers two bounded questions:

* whether the previous 22 target-only coverage families account for every
  target-only character asset; and
* which changed player-character state namespaces remain outside that narrow
  target-only inventory.

The stage reads only report metadata. It does not rehydrate character payloads,
assign visual/censorship semantics, build archives, modify profiles, or touch an
installed game.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
from collections import Counter, defaultdict
from pathlib import Path, PurePosixPath
from typing import Any, Iterable, Mapping, Sequence

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT_DEFAULT = SCRIPT_DIR.parent.parent
TOOL_VERSION = "0.1.41"
REPORT_DIR = "character_asset_namespace_saturation_audit"
REPORT_NAME = "BR_quartet_restoration_character_asset_namespace_saturation_audit_evidence.tar.zst"

STAGE122_ARCHIVE = "BR_quartet_restoration_scene_effect_member_family_binding_audit_evidence.tar.zst"
STAGE122_DIR = "scene_effect_member_family_binding_audit"
EXPECTED_STAGE122_ARCHIVE_SHA256 = "5fba802fdc5407e5c12a708d612f91da087038bef1d48083cb30ae82da62bc92"
EXPECTED_STAGE122_SUMMARY_SHA256 = "f892f3cd4afcb6daa21a3f3befc062b46b45c5e6adb3bcfe4cbae3b015004982"

INPUTS = {
    "br1_asset_differences": (
        "differences/br1_assets.json",
        "a948bf404dc439234519611b98a96b781a5e4f6ed24cf00104fd41ee7dc07456",
    ),
    "coverage_asset_families": (
        "reference_evidence/CANDIDATE_ASSET_FAMILIES.tsv",
        "86f6c9895189262be31c7293d6ab3a89a88d7ff7531b09bcd1080e384357f00d",
    ),
}

EXPECTED = {
    "character_file_rows": 3525,
    "identical_file_rows": 2906,
    "changed_file_rows": 327,
    "removed_file_rows": 244,
    "target_only_file_rows": 48,
    "character_logical_family_rows": 3056,
    "identical_logical_family_rows": 2743,
    "changed_logical_family_rows": 165,
    "removed_logical_family_rows": 122,
    "target_only_logical_family_rows": 26,
    "known_candidate_family_rows": 22,
    "known_candidate_file_rows": 44,
    "new_face_rig_file_rows": 4,
    "new_face_rig_logical_rows": 4,
    "new_face_rig_unique_payload_rows": 3,
    "changed_player_file_rows": 271,
    "changed_player_logical_rows": 137,
    "changed_npc_file_rows": 50,
    "changed_npc_logical_rows": 25,
    "changed_mob_file_rows": 6,
    "changed_mob_logical_rows": 3,
    "universal_changed_state_token_rows": 8,
    "universal_changed_state_logical_rows": 120,
    "universal_changed_state_file_rows": 240,
    "selective_changed_state_token_rows": 8,
    "selective_changed_state_logical_rows": 17,
    "selective_changed_state_file_rows": 31,
    "removed_legacy_dlc_file_rows": 244,
    "removed_legacy_dlc_logical_rows": 122,
}

UNIVERSAL_CHANGED_STATE_TOKENS = {
    "nkd", "nkd_w", "scl", "scl_w", "swm", "swm_w", "tng", "udw",
}
EXPECTED_PLAYER_IDS = {f"pc{i:02d}" for i in range(15)}
FACE_RIG_PATH_FRAGMENT = "/face/"


class AuditError(RuntimeError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AuditError(message)


def progress(message: str) -> None:
    print(f"[character-namespace] {message}", file=sys.stderr, flush=True)


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


def locate_stage122(report_root: Path, temporary: Path) -> tuple[Path, str]:
    archive = report_root / STAGE122_ARCHIVE
    archive_sha = sha256_file(archive)
    require(
        archive_sha == EXPECTED_STAGE122_ARCHIVE_SHA256,
        f"unexpected stage-122 archive SHA-256: {archive_sha}",
    )
    direct = report_root / STAGE122_DIR
    root = direct if direct.is_dir() else extract_archive(archive, temporary / STAGE122_DIR)
    summary_path = root / "SUMMARY.json"
    summary_sha = sha256_file(summary_path)
    require(
        summary_sha == EXPECTED_STAGE122_SUMMARY_SHA256,
        f"unexpected stage-122 summary SHA-256: {summary_sha}",
    )
    return root, archive_sha


def locate_input(report_root: Path, relative: str) -> Path:
    path = report_root / PurePosixPath(relative)
    require(path.is_file(), f"missing required metadata input: {path}")
    return path


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


def logical_path(path: str) -> str:
    normalized = safe_relative(path, "character asset path")
    if normalized.endswith(".elixir.gz"):
        return normalized[:-10]
    pure = PurePosixPath(normalized)
    return pure.with_suffix("").as_posix()


def asset_extension(path: str) -> str:
    if path.endswith(".elixir.gz"):
        return ".elixir.gz"
    return PurePosixPath(path).suffix.casefold() or "(none)"


def namespace(path: str) -> str:
    parts = PurePosixPath(path).parts
    require(len(parts) >= 4 and parts[:3] == ("data", "x64", "character"), f"not a character path: {path}")
    token = parts[3].casefold()
    if token.startswith("pc"):
        return "player_character"
    if token.startswith("npc"):
        return "npc"
    if token.startswith("mob"):
        return "mob"
    if token.startswith("cc"):
        return "cutscene_character"
    if token.startswith("item"):
        return "item"
    if token.startswith("fm"):
        return "field_model"
    if token.startswith("wep"):
        return "weapon"
    return token


def character_id(path: str) -> str:
    token = PurePosixPath(path).parts[3].casefold()
    match = re.match(r"^(pc\d{2})", token)
    return match.group(1) if match else ""


def state_token(path: str) -> str:
    lp = logical_path(path)
    name = PurePosixPath(lp).name.casefold()
    for pattern in (r"^pc\d{2}_(.+)$", r"^pc\d{2}scl_(.+)$"):
        match = re.match(pattern, name)
        if match:
            return match.group(1)
    return name


def joined(values: Iterable[str]) -> str:
    return ";".join(sorted({str(value) for value in values if str(value)}))


def source_or_target(row: Mapping[str, Any], side: str) -> Mapping[str, Any]:
    value = row.get(side)
    return value if isinstance(value, Mapping) else {}


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
        for child in output_dir.iterdir():
            if child.is_dir():
                import shutil
                shutil.rmtree(child)
            else:
                child.unlink()
    output_dir.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="br-stage123-") as td:
        temporary = Path(td)
        stage122_root, stage122_archive_sha = locate_stage122(report_root, temporary)
        stage122_summary = load_json(stage122_root / "SUMMARY.json")
        require(stage122_summary.get("tool_version") == "0.1.40", "stage-122 tool version drift")
        require(stage122_summary.get("unbound_coverage_asset_family_rows") == 19, "stage-122 unbound coverage count drift")

        input_hash_rows: list[dict[str, Any]] = []
        input_paths: dict[str, Path] = {}
        for input_id, (relative, expected_sha) in INPUTS.items():
            path = locate_input(report_root, relative)
            actual = sha256_file(path)
            require(actual == expected_sha, f"input SHA-256 drift for {relative}: {actual}")
            input_paths[input_id] = path
            input_hash_rows.append({
                "input_id": input_id,
                "relative_path": relative,
                "sha256": actual,
                "expected_sha256": expected_sha,
                "verified": True,
            })

        diff_report = load_json(input_paths["br1_asset_differences"])
        all_entries = diff_report.get("entries")
        require(isinstance(all_entries, list), "asset difference entries must be a list")
        character_rows = [
            row for row in all_entries
            if isinstance(row, dict) and str(row.get("normalized_path", "")).startswith("data/x64/character/")
        ]
        require(len(character_rows) == EXPECTED["character_file_rows"], "character file row count drift")

        class_counts = Counter(str(row.get("classification", "")) for row in character_rows)
        require(class_counts == Counter({
            "identical": EXPECTED["identical_file_rows"],
            "changed": EXPECTED["changed_file_rows"],
            "removed_in_target": EXPECTED["removed_file_rows"],
            "new_in_target": EXPECTED["target_only_file_rows"],
        }), f"character classification split drift: {class_counts}")

        candidate_rows = read_tsv(input_paths["coverage_asset_families"])
        require(len(candidate_rows) == EXPECTED["known_candidate_family_rows"], "coverage candidate count drift")
        candidate_by_path: dict[str, dict[str, str]] = {}
        for row in candidate_rows:
            for raw_path in row.get("asset_files", "").split(";"):
                path = raw_path.strip()
                if path:
                    require(path not in candidate_by_path, f"duplicate candidate asset path: {path}")
                    candidate_by_path[path] = row
        require(len(candidate_by_path) == EXPECTED["known_candidate_file_rows"], "candidate file count drift")

        logical_groups: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
        for row in character_rows:
            path = safe_relative(str(row["normalized_path"]), "normalized path")
            logical_groups[(str(row["classification"]), logical_path(path))].append(row)
        require(len(logical_groups) == EXPECTED["character_logical_family_rows"], "logical character family count drift")

        file_ledger_rows: list[dict[str, Any]] = []
        for row in sorted(character_rows, key=lambda item: (str(item.get("classification", "")), str(item.get("normalized_path", "")))):
            path = safe_relative(str(row["normalized_path"]), "normalized path")
            source = source_or_target(row, "source")
            target = source_or_target(row, "target")
            candidate = candidate_by_path.get(path)
            file_ledger_rows.append({
                "difference_id": row.get("difference_id", ""),
                "classification": row.get("classification", ""),
                "namespace": namespace(path),
                "character_id": character_id(path),
                "state_token": state_token(path) if namespace(path) == "player_character" else "",
                "logical_path": logical_path(path),
                "normalized_path": path,
                "asset_extension": asset_extension(path),
                "source_archive": source.get("archive", ""),
                "source_size": source.get("size", ""),
                "source_sha256": source.get("sha256", ""),
                "target_archive": target.get("archive", ""),
                "target_size": target.get("size", ""),
                "target_sha256": target.get("sha256", ""),
                "known_candidate_id": candidate.get("candidate_id", "") if candidate else "",
                "known_candidate_family": candidate.get("family", "") if candidate else "",
                "runtime_confirmed": False,
                "visual_semantics_confirmed": False,
            })

        logical_rows: list[dict[str, Any]] = []
        for (classification, lp), group in sorted(logical_groups.items()):
            paths = [safe_relative(str(row["normalized_path"]), "normalized path") for row in group]
            ns = namespace(paths[0])
            candidates = {candidate_by_path[path]["candidate_id"] for path in paths if path in candidate_by_path}
            families = {candidate_by_path[path]["family"] for path in paths if path in candidate_by_path}
            if classification == "new_in_target" and candidates:
                disposition = "known_target_only_candidate_family"
            elif classification == "new_in_target" and FACE_RIG_PATH_FRAGMENT in lp and lp.endswith("face_rig"):
                disposition = "new_target_only_face_rig_support_asset"
            elif classification == "changed" and ns == "player_character":
                disposition = "changed_player_state_requires_static_member_classification"
            elif classification == "removed_in_target" and ns == "player_character" and "_dlc_" in PurePosixPath(lp).name.casefold():
                disposition = "legacy_dlc_boundary_not_restoration"
            elif classification == "changed":
                disposition = "changed_nonplayer_character_asset_requires_remaster_triage"
            else:
                disposition = "accounted_character_namespace_row"
            source_hashes = [source_or_target(row, "source").get("sha256", "") for row in group]
            target_hashes = [source_or_target(row, "target").get("sha256", "") for row in group]
            logical_rows.append({
                "classification": classification,
                "namespace": ns,
                "character_id": character_id(paths[0]),
                "state_token": state_token(paths[0]) if ns == "player_character" else PurePosixPath(lp).name,
                "logical_path": lp,
                "asset_file_rows": len(group),
                "asset_files": joined(paths),
                "asset_extensions": joined(asset_extension(path) for path in paths),
                "source_archives": joined(source_or_target(row, "source").get("archive", "") for row in group),
                "target_archives": joined(source_or_target(row, "target").get("archive", "") for row in group),
                "source_sha256s": joined(source_hashes),
                "target_sha256s": joined(target_hashes),
                "known_candidate_ids": joined(candidates),
                "known_candidate_families": joined(families),
                "static_disposition": disposition,
                "runtime_confirmed": False,
                "visual_semantics_confirmed": False,
            })

        logical_class_counts = Counter(row["classification"] for row in logical_rows)
        require(logical_class_counts == Counter({
            "identical": EXPECTED["identical_logical_family_rows"],
            "changed": EXPECTED["changed_logical_family_rows"],
            "removed_in_target": EXPECTED["removed_logical_family_rows"],
            "new_in_target": EXPECTED["target_only_logical_family_rows"],
        }), f"logical classification split drift: {logical_class_counts}")

        target_only_file_rows = [row for row in file_ledger_rows if row["classification"] == "new_in_target"]
        known_target_files = [row for row in target_only_file_rows if row["known_candidate_id"]]
        unknown_target_files = [row for row in target_only_file_rows if not row["known_candidate_id"]]
        require(len(known_target_files) == EXPECTED["known_candidate_file_rows"], "known target-only coverage drift")
        require(len(unknown_target_files) == EXPECTED["new_face_rig_file_rows"], "untracked target-only row count drift")
        require(all(FACE_RIG_PATH_FRAGMENT in row["normalized_path"] and row["logical_path"].endswith("face_rig") for row in unknown_target_files), "unexpected untracked target-only character asset")
        require(len({row["target_sha256"] for row in unknown_target_files}) == EXPECTED["new_face_rig_unique_payload_rows"], "face-rig payload identity drift")

        target_only_logical = [row for row in logical_rows if row["classification"] == "new_in_target"]
        known_target_logical = [row for row in target_only_logical if row["known_candidate_ids"]]
        new_rig_logical = [row for row in target_only_logical if row["static_disposition"] == "new_target_only_face_rig_support_asset"]
        require(len(known_target_logical) == EXPECTED["known_candidate_family_rows"], "known target-only logical family drift")
        require(len(new_rig_logical) == EXPECTED["new_face_rig_logical_rows"], "face-rig logical family drift")

        changed_player = [row for row in logical_rows if row["classification"] == "changed" and row["namespace"] == "player_character"]
        require(len(changed_player) == EXPECTED["changed_player_logical_rows"], "changed player logical count drift")
        require(sum(int(row["asset_file_rows"]) for row in changed_player) == EXPECTED["changed_player_file_rows"], "changed player file count drift")

        state_groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for row in changed_player:
            state_groups[row["state_token"]].append(row)
        state_matrix_rows: list[dict[str, Any]] = []
        for token, group in sorted(state_groups.items()):
            ids = {row["character_id"] for row in group if row["character_id"]}
            file_count = sum(int(row["asset_file_rows"]) for row in group)
            universal = token in UNIVERSAL_CHANGED_STATE_TOKENS and ids == EXPECTED_PLAYER_IDS and len(group) == 15
            state_matrix_rows.append({
                "state_token": token,
                "changed_logical_family_rows": len(group),
                "changed_asset_file_rows": file_count,
                "character_id_rows": len(ids),
                "character_ids": joined(ids),
                "universal_across_pc00_pc14": universal,
                "restoration_scope_disposition": "core_player_state_static_classification_priority" if universal else ("legacy_dlc_overlap_deferred" if token.startswith("dlc_") else "selective_player_state_static_triage"),
                "runtime_confirmed": False,
                "visual_semantics_confirmed": False,
            })

        universal_rows = [row for row in state_matrix_rows if row["universal_across_pc00_pc14"]]
        selective_rows = [row for row in state_matrix_rows if not row["universal_across_pc00_pc14"]]
        require({row["state_token"] for row in universal_rows} == UNIVERSAL_CHANGED_STATE_TOKENS, "universal player state token drift")
        require(len(universal_rows) == EXPECTED["universal_changed_state_token_rows"], "universal state token count drift")
        require(sum(int(row["changed_logical_family_rows"]) for row in universal_rows) == EXPECTED["universal_changed_state_logical_rows"], "universal state logical count drift")
        require(sum(int(row["changed_asset_file_rows"]) for row in universal_rows) == EXPECTED["universal_changed_state_file_rows"], "universal state file count drift")
        require(len(selective_rows) == EXPECTED["selective_changed_state_token_rows"], "selective state token count drift")
        require(sum(int(row["changed_logical_family_rows"]) for row in selective_rows) == EXPECTED["selective_changed_state_logical_rows"], "selective state logical count drift")
        require(sum(int(row["changed_asset_file_rows"]) for row in selective_rows) == EXPECTED["selective_changed_state_file_rows"], "selective state file count drift")

        namespace_rows: list[dict[str, Any]] = []
        for (classification, ns), group in sorted(defaultdict(list, {
            key: [row for row in file_ledger_rows if row["classification"] == key[0] and row["namespace"] == key[1]]
            for key in {(row["classification"], row["namespace"]) for row in file_ledger_rows}
        }).items()):
            logical_count = len({row["logical_path"] for row in group})
            namespace_rows.append({
                "classification": classification,
                "namespace": ns,
                "asset_file_rows": len(group),
                "logical_family_rows": logical_count,
                "runtime_confirmed_rows": 0,
                "semantic_classification_authoritative": False,
            })

        removed_rows = [row for row in logical_rows if row["classification"] == "removed_in_target"]
        require(len(removed_rows) == EXPECTED["removed_legacy_dlc_logical_rows"], "removed logical row drift")
        require(sum(int(row["asset_file_rows"]) for row in removed_rows) == EXPECTED["removed_legacy_dlc_file_rows"], "removed file row drift")
        require(all(row["namespace"] == "player_character" and "_dlc_" in PurePosixPath(row["logical_path"]).name.casefold() for row in removed_rows), "removed character namespace contains non-DLC rows")

        changed_npc = [row for row in logical_rows if row["classification"] == "changed" and row["namespace"] == "npc"]
        changed_mob = [row for row in logical_rows if row["classification"] == "changed" and row["namespace"] == "mob"]
        require(len(changed_npc) == EXPECTED["changed_npc_logical_rows"] and sum(int(row["asset_file_rows"]) for row in changed_npc) == EXPECTED["changed_npc_file_rows"], "changed NPC split drift")
        require(len(changed_mob) == EXPECTED["changed_mob_logical_rows"] and sum(int(row["asset_file_rows"]) for row in changed_mob) == EXPECTED["changed_mob_file_rows"], "changed mob split drift")

        gap_rows = [
            {
                "gap_id": "universal_player_state_member_semantics",
                "priority": "critical",
                "affected_logical_family_rows": EXPECTED["universal_changed_state_logical_rows"],
                "affected_asset_file_rows": EXPECTED["universal_changed_state_file_rows"],
                "bounded_result": "eight state tokens differ for every player character pc00 through pc14",
                "blocking_fact": "path-level differences do not identify which internal members are remaster-only or restoration-relevant",
                "safe_next_discovery": "bind the universal state matrix to existing EARC member and material-parameter ledgers by exact logical path and member identity",
                "runtime_or_save_required": False,
                "write_authorized": False,
            },
            {
                "gap_id": "target_only_face_rig_support_assets",
                "priority": "medium",
                "affected_logical_family_rows": EXPECTED["new_face_rig_logical_rows"],
                "affected_asset_file_rows": EXPECTED["new_face_rig_file_rows"],
                "bounded_result": "four target-only face-rig paths were outside the previous 22-family inventory; two paths share one exact payload hash",
                "blocking_fact": "support-rig presence does not establish a visual restoration change or selector relationship",
                "safe_next_discovery": "compare exact internal member tables and route relationships against retained face rigs without assigning expression semantics",
                "runtime_or_save_required": False,
                "write_authorized": False,
            },
            {
                "gap_id": "coverage_selector_binding",
                "priority": "critical",
                "affected_logical_family_rows": 19,
                "affected_asset_file_rows": 38,
                "bounded_result": "all nineteen previously unbound coverage families remain fully represented in the target-only namespace",
                "blocking_fact": "namespace saturation accounts for their files but still does not identify event or table selectors",
                "safe_next_discovery": "continue structured selector binding only after universal state member families are integrated into the same character-state ledger",
                "runtime_or_save_required": False,
                "write_authorized": False,
            },
            {
                "gap_id": "legacy_dlc_character_boundary",
                "priority": "boundary",
                "affected_logical_family_rows": EXPECTED["removed_legacy_dlc_logical_rows"],
                "affected_asset_file_rows": EXPECTED["removed_legacy_dlc_file_rows"],
                "bounded_result": "every character asset removed from Quartet is DLC-prefixed and belongs to the Legacy DLC inventory boundary",
                "blocking_fact": "quartet_restoration must not absorb Legacy DLC restoration work",
                "safe_next_discovery": "record the boundary only; do not modify quartet_legacy_dlc from this workstream",
                "runtime_or_save_required": False,
                "write_authorized": False,
            },
            {
                "gap_id": "global_discovery_saturation",
                "priority": "critical",
                "affected_logical_family_rows": EXPECTED["character_logical_family_rows"],
                "affected_asset_file_rows": EXPECTED["character_file_rows"],
                "bounded_result": "the current BR1 asset-difference report is saturated for data/x64/character and every row is classified",
                "blocking_fact": "character namespace saturation does not prove that field, effect, shader, event, UI or table namespaces are exhausted",
                "safe_next_discovery": "continue namespace-by-namespace static sweeps and merge their bounded ledgers into the master inventory",
                "runtime_or_save_required": False,
                "write_authorized": False,
            },
        ]

        write_tsv(output_dir / "CHARACTER_ASSET_FILE_LEDGER.tsv", [
            "difference_id", "classification", "namespace", "character_id", "state_token", "logical_path",
            "normalized_path", "asset_extension", "source_archive", "source_size", "source_sha256",
            "target_archive", "target_size", "target_sha256", "known_candidate_id", "known_candidate_family",
            "runtime_confirmed", "visual_semantics_confirmed",
        ], file_ledger_rows)
        write_tsv(output_dir / "CHARACTER_LOGICAL_ASSET_FAMILIES.tsv", [
            "classification", "namespace", "character_id", "state_token", "logical_path", "asset_file_rows",
            "asset_files", "asset_extensions", "source_archives", "target_archives", "source_sha256s",
            "target_sha256s", "known_candidate_ids", "known_candidate_families", "static_disposition",
            "runtime_confirmed", "visual_semantics_confirmed",
        ], logical_rows)
        write_tsv(output_dir / "TARGET_ONLY_CHARACTER_ASSETS.tsv", [
            "difference_id", "classification", "namespace", "character_id", "state_token", "logical_path",
            "normalized_path", "asset_extension", "target_archive", "target_size", "target_sha256",
            "known_candidate_id", "known_candidate_family", "runtime_confirmed", "visual_semantics_confirmed",
        ], target_only_file_rows)
        write_tsv(output_dir / "TARGET_ONLY_CHARACTER_FAMILY_COVERAGE.tsv", [
            "classification", "namespace", "character_id", "state_token", "logical_path", "asset_file_rows",
            "asset_files", "asset_extensions", "target_archives", "target_sha256s", "known_candidate_ids",
            "known_candidate_families", "static_disposition", "runtime_confirmed", "visual_semantics_confirmed",
        ], target_only_logical)
        write_tsv(output_dir / "PLAYER_CHARACTER_CHANGED_STATE_FAMILIES.tsv", [
            "classification", "namespace", "character_id", "state_token", "logical_path", "asset_file_rows",
            "asset_files", "asset_extensions", "source_archives", "target_archives", "source_sha256s",
            "target_sha256s", "static_disposition", "runtime_confirmed", "visual_semantics_confirmed",
        ], changed_player)
        write_tsv(output_dir / "PLAYER_CHARACTER_STATE_MATRIX.tsv", [
            "state_token", "changed_logical_family_rows", "changed_asset_file_rows", "character_id_rows",
            "character_ids", "universal_across_pc00_pc14", "restoration_scope_disposition",
            "runtime_confirmed", "visual_semantics_confirmed",
        ], state_matrix_rows)
        write_tsv(output_dir / "CHARACTER_NAMESPACE_CLASSIFICATION.tsv", [
            "classification", "namespace", "asset_file_rows", "logical_family_rows",
            "runtime_confirmed_rows", "semantic_classification_authoritative",
        ], namespace_rows)
        write_tsv(output_dir / "CHARACTER_DISCOVERY_GAPS.tsv", [
            "gap_id", "priority", "affected_logical_family_rows", "affected_asset_file_rows", "bounded_result",
            "blocking_fact", "safe_next_discovery", "runtime_or_save_required", "write_authorized",
        ], gap_rows)
        write_tsv(output_dir / "INPUT_HASHES.tsv", [
            "input_id", "relative_path", "sha256", "expected_sha256", "verified",
        ], input_hash_rows)

        summary: dict[str, Any] = {
            "type": "br_quartet_restoration_character_asset_namespace_saturation_audit_evidence_summary",
            "format_version": 1,
            "tool_version": TOOL_VERSION,
            "status": "character_namespace_fully_enumerated_target_only_inventory_expanded_universal_player_state_differences_exposed_semantics_unresolved_no_write",
            "stage122_report_sha256": stage122_archive_sha,
            "stage122_summary_sha256": EXPECTED_STAGE122_SUMMARY_SHA256,
            "character_asset_file_rows": len(file_ledger_rows),
            "character_logical_family_rows": len(logical_rows),
            "classification_file_rows": dict(sorted(class_counts.items())),
            "classification_logical_family_rows": dict(sorted(logical_class_counts.items())),
            "target_only_character_asset_file_rows": len(target_only_file_rows),
            "target_only_character_logical_family_rows": len(target_only_logical),
            "previously_known_target_only_candidate_family_rows": len(known_target_logical),
            "previously_known_target_only_candidate_file_rows": len(known_target_files),
            "new_target_only_face_rig_logical_family_rows": len(new_rig_logical),
            "new_target_only_face_rig_file_rows": len(unknown_target_files),
            "new_target_only_face_rig_unique_payload_rows": len({row["target_sha256"] for row in unknown_target_files}),
            "target_only_character_namespace_saturation_achieved": True,
            "unclassified_target_only_character_file_rows": 0,
            "changed_player_character_logical_family_rows": len(changed_player),
            "changed_player_character_file_rows": sum(int(row["asset_file_rows"]) for row in changed_player),
            "universal_changed_player_state_tokens": sorted(UNIVERSAL_CHANGED_STATE_TOKENS),
            "universal_changed_player_state_token_rows": len(universal_rows),
            "universal_changed_player_state_logical_family_rows": sum(int(row["changed_logical_family_rows"]) for row in universal_rows),
            "universal_changed_player_state_file_rows": sum(int(row["changed_asset_file_rows"]) for row in universal_rows),
            "selective_changed_player_state_token_rows": len(selective_rows),
            "selective_changed_player_state_logical_family_rows": sum(int(row["changed_logical_family_rows"]) for row in selective_rows),
            "selective_changed_player_state_file_rows": sum(int(row["changed_asset_file_rows"]) for row in selective_rows),
            "changed_npc_logical_family_rows": len(changed_npc),
            "changed_npc_file_rows": sum(int(row["asset_file_rows"]) for row in changed_npc),
            "changed_mob_logical_family_rows": len(changed_mob),
            "changed_mob_file_rows": sum(int(row["asset_file_rows"]) for row in changed_mob),
            "removed_legacy_dlc_character_logical_family_rows": len(removed_rows),
            "removed_legacy_dlc_character_file_rows": sum(int(row["asset_file_rows"]) for row in removed_rows),
            "coverage_selector_binding_complete": False,
            "universal_player_state_member_semantics_resolved": False,
            "global_discovery_saturation_achieved": False,
            "runtime_confirmed_rows": 0,
            "write_authorized_rows": 0,
            "policy": {
                "existing_evidence_only": True,
                "proprietary_payload_rehydrated": False,
                "path_and_hash_metadata_only": True,
                "visual_or_censorship_semantics_assigned": False,
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
                "Continue save-independent discovery with an exact character-state member integration audit. Bind the 120 "
                "universal changed logical families for nkd, nkd_w, scl, scl_w, swm, swm_w, tng and udw to existing "
                "EARC member, structural variant and material-parameter ledgers. Audit the four new face-rig support paths "
                "separately. Keep the nineteen selector-unbound target-only coverage families unresolved and do not proceed "
                "to broad runtime composition."
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
        print(f"[character-namespace] ERROR: {exc}", file=sys.stderr)
        return 1
    root = args.output_report_root or args.report_root or args.project_root / ".local/reports/quartet_restoration"
    progress(f"report directory: {Path(root) / REPORT_DIR}")
    if not args.no_archive:
        progress(f"report archive: {archive}")
    print(json.dumps(summary, indent=2, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
