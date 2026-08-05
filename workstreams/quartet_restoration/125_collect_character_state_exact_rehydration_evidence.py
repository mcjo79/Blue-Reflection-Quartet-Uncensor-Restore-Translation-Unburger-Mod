#!/usr/bin/env python3
"""Rehydrate exact member tables for the 81 missing universal character states.

Stage 125 reads local proprietary Original/Quartet asset archives or an existing
extraction cache, but emits metadata only. It also audits the four target-only
face-rig support archives. No payload is copied into evidence and no game,
profile, registry, PAK, core, Translation, Legacy DLC or Git state is modified.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import importlib.util
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
TOOL_VERSION = "0.1.43"
REPORT_DIR = "character_state_exact_rehydration_evidence"
REPORT_NAME = "BR_quartet_restoration_character_state_exact_rehydration_evidence.tar.zst"
STAGE124_ARCHIVE = "BR_quartet_restoration_character_state_member_integration_audit_evidence.tar.zst"
STAGE124_ROOT = "character_state_member_integration_audit"
STAGE124_SHA256 = "fdefcede53e433d82731d0070e8264c2861c1cf6c14c82ce3706b20a16a4ce3a"
STAGE124_SUMMARY_SHA256 = "7686958157e730427bf81ffab32a9af383ec80c48e166d832b6d566be1b2dc69"
UNIVERSAL_TOKENS = {"nkd", "nkd_w", "scl", "scl_w", "swm", "swm_w", "tng", "udw"}
EXPECTED_MISSING_FAMILIES = 81
EXPECTED_EXISTING_FAMILIES = 39
EXPECTED_TOTAL_FAMILIES = 120
EXPECTED_FACE_RIGS = 4
MAX_EARC_BYTES = 256 * 1024 * 1024


class CollectorError(RuntimeError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise CollectorError(message)


def progress(message: str) -> None:
    print(f"[character-state-rehydration] {message}", file=sys.stderr, flush=True)


def version_tuple(value: str) -> tuple[int, ...]:
    try:
        return tuple(int(part) for part in value.strip().split("."))
    except ValueError as exc:
        raise CollectorError(f"invalid workstream version: {value}") from exc


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
    require(archive.is_file(), f"missing stage-124 report: {archive}")
    actual = sha256_file(archive)
    require(actual == STAGE124_SHA256, f"unexpected stage-124 report SHA-256: {actual}")
    listed = subprocess.run(["tar", "--zstd", "-tf", str(archive)], text=True, capture_output=True)
    require(listed.returncode == 0, listed.stderr.strip() or "cannot list stage-124 report")
    names = [safe_relative(line.strip(), "archive member") for line in listed.stdout.splitlines() if line.strip()]
    require(names and {PurePosixPath(name).parts[0] for name in names} == {STAGE124_ROOT}, "unexpected stage-124 archive root")
    destination.mkdir(parents=True, exist_ok=True)
    completed = subprocess.run(["tar", "--zstd", "-xf", str(archive), "-C", str(destination)], text=True, capture_output=True)
    require(completed.returncode == 0, completed.stderr.strip() or "cannot extract stage-124 report")
    root = destination / STAGE124_ROOT
    summary = root / "SUMMARY.json"
    require(summary.is_file(), "stage-124 SUMMARY.json missing")
    actual_summary = sha256_file(summary)
    require(actual_summary == STAGE124_SUMMARY_SHA256, f"unexpected stage-124 summary SHA-256: {actual_summary}")
    return root


def load_br_tool(project_root: Path):
    path = project_root / "Blue_Reflection_Text_Tool/br_restoration_tool.py"
    require(path.is_file(), f"missing restoration tool: {path}")
    spec = importlib.util.spec_from_file_location("stage125_br_restoration_tool", path)
    require(spec is not None and spec.loader is not None, "cannot load restoration tool")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def load_asset_inventories(project_root: Path) -> dict[tuple[str, str], tuple[str, dict[str, Any]]]:
    root = project_root / ".local/reports/quartet_restoration/inventories"
    require(root.is_dir(), f"missing inventory directory: {root}")
    result: dict[tuple[str, str], tuple[str, dict[str, Any]]] = {}
    for path in sorted(root.glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        if data.get("archive_group") != "br1_assets" or data.get("normalization_side") not in {"source", "target"}:
            continue
        side = str(data["normalization_side"])
        pair_id = str(data["archive_group"])
        for entry in data.get("files", []):
            normalized = str(entry.get("normalized_path", "")).casefold()
            if normalized:
                key = (side, normalized)
                require(key not in result, f"duplicate inventory normalized path: {key}")
                result[key] = (pair_id, dict(entry))
    require(result, "no br1_assets inventory entries loaded")
    return result


def find_gust_pak(project_root: Path, explicit: Path | None) -> Path:
    candidates: list[Path] = []
    if explicit:
        candidates.append(explicit.expanduser())
    candidates += [
        project_root / ".local/vendor/gust_tools/gust_pak",
        Path.home() / "Downloads/gust_tools/gust_pak",
    ]
    found = shutil.which("gust_pak")
    if found:
        candidates.append(Path(found))
    for candidate in candidates:
        path = candidate.resolve()
        if path.is_file() and os.access(path, os.X_OK):
            return path
    raise CollectorError("gust_pak was not found; provide --gust-pak or install it in .local/vendor/gust_tools")


def resolve_game_archive(game_root: Path, relative: str) -> Path:
    game_root = game_root.expanduser().resolve()
    require(game_root.is_dir(), f"game root does not exist: {game_root}")
    direct = game_root / PurePosixPath(relative)
    if direct.is_file():
        return direct.resolve()
    wanted = PurePosixPath(relative).as_posix().casefold()
    matches = [p.resolve() for p in game_root.rglob("*.PAK") if p.relative_to(game_root).as_posix().casefold() == wanted]
    require(len(matches) == 1, f"cannot uniquely resolve {relative} below {game_root}; matches={len(matches)}")
    return matches[0]


def normalized_role(name: str, character_id: str, state_token: str) -> str:
    value = name.casefold()
    value = re.sub(re.escape(character_id.casefold()), "{pc}", value)
    value = re.sub(re.escape(state_token.casefold()), "{state}", value)
    value = re.sub(r"pc\d{2}", "{pc}", value)
    return value


def delta_signature(rows: Sequence[Mapping[str, Any]], character_id: str, state_token: str) -> str:
    tokens = []
    for row in rows:
        name = str(row.get("target_member_name") or row.get("source_member_name") or "")
        source_size = int(row.get("source_size") or 0)
        target_size = int(row.get("target_size") or 0)
        tokens.append("|".join([
            normalized_role(name, character_id, state_token),
            str(row.get("classification", "")),
            str(target_size - source_size),
            Path(name).suffix.casefold(),
        ]))
    return hashlib.sha256("\n".join(sorted(tokens)).encode("utf-8")).hexdigest()


def ensure_extraction_cache(
    *, project_root: Path, workspace_root: Path, inventories: Mapping[tuple[str, str], tuple[str, dict[str, Any]]],
    required_paths: Sequence[str], original_root: Path | None, quartet_root: Path | None, gust_pak_path: Path | None,
    br: Any, timeout_seconds: int,
) -> list[dict[str, Any]]:
    missing_by_side: dict[str, list[str]] = defaultdict(list)
    for normalized in required_paths:
        for side in ("source", "target"):
            if side == "source" and normalized.startswith("data/x64/character/pc00/face/pc00_") and (side, normalized.casefold()) not in inventories:
                continue
            key = (side, normalized.casefold())
            if key not in inventories:
                if side == "source":
                    continue
                raise CollectorError(f"missing inventory entry: {key}")
            pair_id, entry = inventories[key]
            local = br.inventory_workspace_file(workspace_root, side, pair_id, str(entry["archive"]), str(entry["path"]))
            if not local.is_file():
                missing_by_side[side].append(normalized)
    if not missing_by_side:
        return [{"side": "source", "archive_relative": "DATA/PACK00_02.PAK", "cache_action": "reused_existing_workspace"},
                {"side": "target", "archive_relative": "Data/PACK10_02.PAK", "cache_action": "reused_existing_workspace"}]

    require(original_root is not None and quartet_root is not None, "required workspace files are missing; provide --original-root and --quartet-root")
    gust = find_gust_pak(project_root, gust_pak_path)
    gust_sha = sha256_file(gust)
    rows: list[dict[str, Any]] = []
    side_specs = {
        "source": (original_root, "DATA/PACK00_02.PAK"),
        "target": (quartet_root, "Data/PACK10_02.PAK"),
    }
    for side in sorted(missing_by_side):
        game_root, relative = side_specs[side]
        archive = resolve_game_archive(game_root, relative)
        progress(f"extracting read-only input {relative} for {len(missing_by_side[side])} required paths")
        result = br.extract_archive(
            archive=archive,
            game_root=game_root.expanduser().resolve(),
            gust_pak=gust,
            gust_pak_sha256=gust_sha,
            pair_id="br1_assets",
            side=side,
            workspace_root=workspace_root,
            timeout_seconds=timeout_seconds,
        )
        rows.append({
            "side": side,
            "archive_relative": relative,
            "archive_size": result["source_archive_size"],
            "archive_sha256": result["source_archive_sha256"],
            "gust_pak_sha256": gust_sha,
            "cache_action": result["status"],
        })
    return rows


def build_report(
    project_root: Path,
    *, report_root: Path | None = None, output_report_root: Path | None = None,
    workspace_root: Path | None = None, original_root: Path | None = None, quartet_root: Path | None = None,
    gust_pak_path: Path | None = None, create_archive: bool = True, timeout_seconds: int = 1800,
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

    br = load_br_tool(project_root)
    with tempfile.TemporaryDirectory(prefix="stage125-prereq-") as td:
        stage124 = extract_report(report_root / STAGE124_ARCHIVE, Path(td))
        summary124 = json.loads((stage124 / "SUMMARY.json").read_text(encoding="utf-8"))
        require(summary124.get("missing_existing_member_coverage_family_rows") == EXPECTED_MISSING_FAMILIES, "stage-124 missing-family count drift")
        require(summary124.get("existing_member_coverage_family_rows") == EXPECTED_EXISTING_FAMILIES, "stage-124 existing-family count drift")
        family_rows = read_tsv(stage124 / "UNIVERSAL_CHARACTER_STATE_INTEGRATION.tsv")
        missing = [row for row in family_rows if row["existing_member_integration_complete"] == "False"]
        existing = [row for row in family_rows if row["existing_member_integration_complete"] == "True"]
        require(len(missing) == EXPECTED_MISSING_FAMILIES and len(existing) == EXPECTED_EXISTING_FAMILIES, "stage-124 family partition drift")
        require({row["state_token"] for row in family_rows} == UNIVERSAL_TOKENS, "universal token set drift")
        face_rows = read_tsv(stage124 / "FACE_RIG_SUPPORT_INTEGRATION.tsv")
        require(len(face_rows) == EXPECTED_FACE_RIGS, "face-rig count drift")

        inventories = load_asset_inventories(project_root)
        missing_paths = [row["archive_path"] for row in missing]
        face_paths = [row["archive_path"] for row in face_rows]
        extraction_rows = ensure_extraction_cache(
            project_root=project_root, workspace_root=workspace_root, inventories=inventories,
            required_paths=missing_paths + face_paths, original_root=original_root, quartet_root=quartet_root,
            gust_pak_path=gust_pak_path, br=br, timeout_seconds=timeout_seconds,
        )

        archive_rows: list[dict[str, Any]] = []
        member_rows: list[dict[str, Any]] = []
        family_summaries: list[dict[str, Any]] = []
        shape_groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
        payload_bytes_read = 0

        for index, family in enumerate(sorted(missing, key=lambda r: (r["character_id"], r["state_token"])), 1):
            character_id = family["character_id"]
            state_token = family["state_token"]
            normalized = family["archive_path"]
            progress(f"universal family {index}/{len(missing)} {character_id}:{state_token}")
            parsed: dict[str, dict[str, Any]] = {}
            input_sha: dict[str, str] = {}
            for side in ("source", "target"):
                pair_id, entry = inventories[(side, normalized.casefold())]
                local = br.inventory_workspace_file(workspace_root, side, pair_id, str(entry["archive"]), str(entry["path"]))
                require(local.is_file(), f"missing extracted input: {side} {normalized}: {local}")
                actual_sha = sha256_file(local)
                if verify_payload_hashes:
                    require(actual_sha == str(entry["sha256"]), f"payload hash drift: {side} {normalized}: {actual_sha}")
                input_sha[side] = actual_sha
                item = br.read_earc_archive(local, maximum_bytes=MAX_EARC_BYTES, include_member_payloads=False)
                parsed[side] = item
                payload_bytes_read += int(item["decoded_bytes"])
                archive_rows.append({
                    "character_id": character_id, "state_token": state_token, "side": side,
                    "archive_path": normalized, "container": item["container"],
                    "input_file_size": local.stat().st_size, "input_file_sha256": actual_sha,
                    "decoded_bytes": item["decoded_bytes"], "decoded_sha256": item["decoded_sha256"],
                    "member_count": item["file_count"], "filename_size_units": item["filename_size"], "flags": item["flags"],
                    "payload_in_evidence": False, "write_authorized": False,
                })
            diffs, counts = br.compare_earc_members(parsed["source"], parsed["target"])
            source_by = {str(m["comparison_key"]): m for m in parsed["source"]["members"]}
            target_by = {str(m["comparison_key"]): m for m in parsed["target"]["members"]}
            complete_rows: list[dict[str, Any]] = []
            for key in sorted(set(source_by) | set(target_by), key=str.casefold):
                left, right = source_by.get(key), target_by.get(key)
                if left and right:
                    classification = "identical" if left["sha256"] == right["sha256"] else "changed"
                elif left:
                    classification = "removed_in_target"
                else:
                    classification = "added_in_target"
                row = {
                    "character_id": character_id, "state_token": state_token, "archive_path": normalized,
                    "member_key": key, "normalized_member_role": normalized_role(str((right or left)["name"]), character_id, state_token),
                    "source_member_name": (left or {}).get("name", ""), "target_member_name": (right or {}).get("name", ""),
                    "source_member_index": (left or {}).get("index", ""), "target_member_index": (right or {}).get("index", ""),
                    "source_size": (left or {}).get("size", ""), "target_size": (right or {}).get("size", ""),
                    "source_sha256": (left or {}).get("sha256", ""), "target_sha256": (right or {}).get("sha256", ""),
                    "classification": classification, "member_extension": (right or left).get("extension", ""),
                    "semantics_confirmed": False, "write_authorized": False,
                }
                complete_rows.append(row)
                member_rows.append(row)
            changed_rows = [row for row in complete_rows if row["classification"] != "identical"]
            signature = delta_signature(changed_rows, character_id, state_token)
            family_summary = {
                "character_id": character_id, "state_token": state_token, "logical_path": family["logical_path"], "archive_path": normalized,
                "source_input_sha256": input_sha["source"], "target_input_sha256": input_sha["target"],
                "source_member_rows": len(source_by), "target_member_rows": len(target_by),
                "identical_member_rows": counts.get("identical", 0), "changed_member_rows": counts.get("changed", 0),
                "removed_in_target_member_rows": counts.get("removed_in_target", 0), "added_in_target_member_rows": counts.get("added_in_target", 0),
                "nonidentical_member_rows": len(changed_rows), "delta_shape_sha256": signature,
                "exact_rehydration_complete": True, "runtime_confirmed": False, "semantics_confirmed": False, "write_authorized": False,
            }
            family_summaries.append(family_summary)
            shape_groups[signature].append(family_summary)

        require(len(family_summaries) == EXPECTED_MISSING_FAMILIES, "not all 81 families were rehydrated")
        complete_coverage = []
        for row in family_rows:
            is_existing = row["existing_member_integration_complete"] == "True"
            complete_coverage.append({
                "character_id": row["character_id"], "state_token": row["state_token"], "logical_path": row["logical_path"], "archive_path": row["archive_path"],
                "coverage_source": "stage124_existing_exact_member_ledger" if is_existing else "stage125_exact_local_rehydration",
                "exact_member_coverage_complete": True, "runtime_confirmed": False, "semantics_confirmed": False, "write_authorized": False,
            })
        require(len(complete_coverage) == EXPECTED_TOTAL_FAMILIES, "complete universal family count drift")

        shape_rows = []
        for signature, rows in sorted(shape_groups.items(), key=lambda item: (-len(item[1]), item[0])):
            shape_rows.append({
                "delta_shape_sha256": signature, "logical_family_rows": len(rows),
                "character_ids": ";".join(sorted({r["character_id"] for r in rows})),
                "state_tokens": ";".join(sorted({r["state_token"] for r in rows})),
                "archive_paths": ";".join(sorted(r["archive_path"] for r in rows)),
                "total_changed_member_rows": sum(int(r["changed_member_rows"]) for r in rows),
                "total_removed_member_rows": sum(int(r["removed_in_target_member_rows"]) for r in rows),
                "total_added_member_rows": sum(int(r["added_in_target_member_rows"]) for r in rows),
                "semantics_confirmed": False, "write_authorized": False,
            })

        face_archive_rows: list[dict[str, Any]] = []
        face_member_rows: list[dict[str, Any]] = []
        face_groups: dict[str, list[str]] = defaultdict(list)
        for row in sorted(face_rows, key=lambda r: r["archive_path"]):
            normalized = row["archive_path"]
            pair_id, entry = inventories[("target", normalized.casefold())]
            local = br.inventory_workspace_file(workspace_root, "target", pair_id, str(entry["archive"]), str(entry["path"]))
            require(local.is_file(), f"missing target face-rig input: {normalized}: {local}")
            actual_sha = sha256_file(local)
            if verify_payload_hashes:
                require(actual_sha == str(entry["sha256"]), f"face-rig payload hash drift: {normalized}: {actual_sha}")
            parsed = br.read_earc_archive(local, maximum_bytes=MAX_EARC_BYTES, include_member_payloads=False)
            payload_bytes_read += int(parsed["decoded_bytes"])
            shape_source = "\n".join(f"{m['name'].casefold()}|{m['size']}|{m['sha256']}" for m in parsed["members"])
            shape_sha = hashlib.sha256(shape_source.encode("utf-8")).hexdigest()
            face_groups[shape_sha].append(normalized)
            face_archive_rows.append({
                "archive_path": normalized, "input_file_size": local.stat().st_size, "input_file_sha256": actual_sha,
                "container": parsed["container"], "decoded_bytes": parsed["decoded_bytes"], "decoded_sha256": parsed["decoded_sha256"],
                "member_count": parsed["file_count"], "member_table_shape_sha256": shape_sha,
                "expression_or_visual_semantics_confirmed": False, "write_authorized": False,
            })
            for member in parsed["members"]:
                face_member_rows.append({
                    "archive_path": normalized, "member_key": member["comparison_key"], "member_name": member["name"],
                    "member_index": member["index"], "member_size": member["size"], "member_sha256": member["sha256"],
                    "member_extension": member["extension"], "expression_or_visual_semantics_confirmed": False, "write_authorized": False,
                })
        face_group_rows = [{
            "member_table_shape_sha256": sha, "archive_rows": len(paths), "archive_paths": ";".join(sorted(paths)),
            "duplicate_shape": len(paths) > 1, "semantics_confirmed": False, "write_authorized": False,
        } for sha, paths in sorted(face_groups.items(), key=lambda item: (-len(item[1]), item[0]))]

        write_tsv(output / "REHYDRATED_UNIVERSAL_ARCHIVES.tsv", [
            "character_id", "state_token", "side", "archive_path", "container", "input_file_size", "input_file_sha256",
            "decoded_bytes", "decoded_sha256", "member_count", "filename_size_units", "flags", "payload_in_evidence", "write_authorized",
        ], archive_rows)
        write_tsv(output / "REHYDRATED_UNIVERSAL_MEMBER_LEDGER.tsv", [
            "character_id", "state_token", "archive_path", "member_key", "normalized_member_role",
            "source_member_name", "target_member_name", "source_member_index", "target_member_index", "source_size", "target_size",
            "source_sha256", "target_sha256", "classification", "member_extension", "semantics_confirmed", "write_authorized",
        ], member_rows)
        write_tsv(output / "REHYDRATED_UNIVERSAL_FAMILY_SUMMARY.tsv", [
            "character_id", "state_token", "logical_path", "archive_path", "source_input_sha256", "target_input_sha256",
            "source_member_rows", "target_member_rows", "identical_member_rows", "changed_member_rows", "removed_in_target_member_rows",
            "added_in_target_member_rows", "nonidentical_member_rows", "delta_shape_sha256", "exact_rehydration_complete",
            "runtime_confirmed", "semantics_confirmed", "write_authorized",
        ], family_summaries)
        write_tsv(output / "COMPLETE_UNIVERSAL_FAMILY_COVERAGE.tsv", [
            "character_id", "state_token", "logical_path", "archive_path", "coverage_source", "exact_member_coverage_complete",
            "runtime_confirmed", "semantics_confirmed", "write_authorized",
        ], complete_coverage)
        write_tsv(output / "UNIVERSAL_DELTA_SHAPE_GROUPS.tsv", [
            "delta_shape_sha256", "logical_family_rows", "character_ids", "state_tokens", "archive_paths",
            "total_changed_member_rows", "total_removed_member_rows", "total_added_member_rows", "semantics_confirmed", "write_authorized",
        ], shape_rows)
        write_tsv(output / "FACE_RIG_ARCHIVES.tsv", [
            "archive_path", "input_file_size", "input_file_sha256", "container", "decoded_bytes", "decoded_sha256",
            "member_count", "member_table_shape_sha256", "expression_or_visual_semantics_confirmed", "write_authorized",
        ], face_archive_rows)
        write_tsv(output / "FACE_RIG_MEMBER_TABLES.tsv", [
            "archive_path", "member_key", "member_name", "member_index", "member_size", "member_sha256", "member_extension",
            "expression_or_visual_semantics_confirmed", "write_authorized",
        ], face_member_rows)
        write_tsv(output / "FACE_RIG_SHAPE_GROUPS.tsv", [
            "member_table_shape_sha256", "archive_rows", "archive_paths", "duplicate_shape", "semantics_confirmed", "write_authorized",
        ], face_group_rows)
        write_tsv(output / "EXTRACTION_INPUTS.tsv", [
            "side", "archive_relative", "archive_size", "archive_sha256", "gust_pak_sha256", "cache_action",
        ], extraction_rows)

        classification_counts = Counter(row["classification"] for row in member_rows)
        extension_counts = Counter(row["member_extension"] or "<none>" for row in member_rows)
        repeated_shapes = sum(1 for rows in shape_groups.values() if len(rows) > 1)
        repeated_shape_families = sum(len(rows) for rows in shape_groups.values() if len(rows) > 1)
        summary = {
            "type": "br_quartet_restoration_character_state_exact_rehydration_evidence_summary",
            "format_version": 1,
            "tool_version": TOOL_VERSION,
            "status": "all_120_universal_character_state_families_now_share_exact_member_coverage_metadata_only_no_write",
            "stage124_report_sha256": STAGE124_SHA256,
            "stage124_summary_sha256": STAGE124_SUMMARY_SHA256,
            "stage124_existing_family_rows_preserved": EXPECTED_EXISTING_FAMILIES,
            "new_exact_rehydrated_family_rows": len(family_summaries),
            "complete_universal_family_rows": len(complete_coverage),
            "complete_universal_state_token_rows": len({r["state_token"] for r in complete_coverage}),
            "complete_universal_character_rows": len({r["character_id"] for r in complete_coverage}),
            "exact_universal_member_coverage_complete": len(complete_coverage) == EXPECTED_TOTAL_FAMILIES,
            "rehydrated_archive_side_rows": len(archive_rows),
            "rehydrated_member_ledger_rows": len(member_rows),
            "rehydrated_member_classification_counts": dict(sorted(classification_counts.items())),
            "rehydrated_member_extension_counts": dict(sorted(extension_counts.items())),
            "delta_shape_group_rows": len(shape_groups),
            "repeated_delta_shape_group_rows": repeated_shapes,
            "families_in_repeated_delta_shapes": repeated_shape_families,
            "target_only_face_rig_archive_rows": len(face_archive_rows),
            "target_only_face_rig_member_rows": len(face_member_rows),
            "target_only_face_rig_shape_group_rows": len(face_groups),
            "input_decoded_payload_bytes_read": payload_bytes_read,
            "runtime_confirmed_rows": 0,
            "visual_or_censorship_semantics_confirmed_rows": 0,
            "write_authorized_rows": 0,
            "global_discovery_saturation_achieved": False,
            "policy": {
                "local_proprietary_payloads_rehydrated_for_analysis": True,
                "proprietary_payloads_in_report": False,
                "member_names_hashes_sizes_and_numeric_metadata_only": True,
                "save_or_runtime_required": False,
                "installed_game_read_only": True,
                "local_extraction_cache_may_be_created": True,
                "pak_built_or_repacked": False,
                "profile_or_registry_modified": False,
                "core_modified": False,
                "translation_modified": False,
                "legacy_dlc_modified": False,
                "git_modified": False,
                "visual_or_censorship_semantics_assigned": False,
            },
            "next_action": (
                "Classify recurrent member-delta shapes across the now-complete 120-family exact ledger, then parse the changed G1M/material members "
                "for systematic Original-to-Quartet delta families. Keep the 19 selector-bound towel/swimsuit/underwear families and runtime composition deferred."
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
        print(f"[character-state-rehydration] report archive: {archive}")
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except CollectorError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(2)
