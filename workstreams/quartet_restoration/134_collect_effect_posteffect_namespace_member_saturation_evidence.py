#!/usr/bin/env python3
"""Stage 134: saturate effect/posteffect members and audit bounded shader dependencies.

This read-only collector consumes the complete seven-path effect/posteffect queue
from stage 130 and the fifteen interface-stable executable-code candidates from
stage 133. It records every member in the six effect Elixirs and one posteffect
Elixir, groups non-identical member roles, and searches only exact shader-basename
references in effect/posteffect and field member names. Existing inactive shader
profiles are recorded as provenance, never as runtime validation or semantic proof.

Installed archives are read only. Evidence contains metadata, names, sizes,
hashes and counts only; no proprietary payload is copied and no write is authorized.
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

TOOL_VERSION = "0.1.52"
REPORT_DIR = "effect_posteffect_namespace_member_saturation_evidence"
REPORT_NAME = "BR_quartet_restoration_effect_posteffect_namespace_member_saturation_evidence.tar.zst"

STAGE130_NAME = "BR_quartet_restoration_non_character_namespace_saturation_audit_evidence.tar.zst"
STAGE130_SHA256 = "de8b339921387dfa8858415110166120f49ceddcf63ea148883fcf41d214d69c"
STAGE130_DIR = "non_character_namespace_saturation_audit"
STAGE130_SUMMARY_SHA256 = "3b1293b422d19a9ab87a22d00b46755ca7e23d48b6d46ea1795ac0435080decd"

STAGE131_NAME = "BR_quartet_restoration_field_namespace_member_saturation_evidence.tar.zst"
STAGE131_SHA256 = "b3c7273404ad6d80206f59497e338f85169026fbf22df9b3eefb689f7e5ca32b"
STAGE131_DIR = "field_namespace_member_saturation_evidence"
STAGE131_SUMMARY_SHA256 = "a3e07a7d73cbf76152e5d82727ab219679c6f3059336ba1e694b717d4c0ee75f"

STAGE133_NAME = "BR_quartet_restoration_shader_namespace_executable_signature_reflection_sweep_evidence.tar.zst"
STAGE133_SHA256 = "8d3d9488400e13aa40accbb35e2a9ce13956de6fd0ad2030fb825d3ccd20a76b"
STAGE133_DIR = "shader_namespace_executable_signature_reflection_sweep_evidence"
STAGE133_SUMMARY_SHA256 = "6013ea240e48ea97fe4b1e128c2bd872eaa4dc768fc6cbd40a25438e059303c7"

EXPECTED_CONTAINER_PATHS = 7
EXPECTED_EFFECT_PATHS = 6
EXPECTED_POSTEFFECT_PATHS = 1
EXPECTED_SHADER_CANDIDATES = 15
MAX_EARC_BYTES = 1024 * 1024 * 1024
FORBIDDEN_EXTENSIONS = (
    ".pak", ".g1m", ".g1e", ".g1em", ".g1s", ".g1t", ".dxbc",
    ".elixir", ".elixir.gz", ".ebd", ".ebm", ".bin",
)


class CollectorError(RuntimeError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise CollectorError(message)


def progress(message: str) -> None:
    print(f"[effect-posteffect-saturation] {message}", file=sys.stderr, flush=True)


def version_tuple(value: str) -> tuple[int, ...]:
    try:
        return tuple(int(part) for part in value.strip().split("."))
    except ValueError as exc:
        raise CollectorError(f"invalid version: {value}") from exc


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def safe_relative(value: str, label: str) -> str:
    path = PurePosixPath(str(value).replace("\\", "/"))
    require(bool(path.parts), f"empty {label}")
    require(not path.is_absolute() and ".." not in path.parts, f"unsafe {label}: {value}")
    return path.as_posix()


def parse_bool(value: object) -> bool:
    return str(value).strip().casefold() in {"1", "true", "yes", "y"}


def read_tsv(path: Path) -> list[dict[str, str]]:
    require(path.is_file(), f"missing TSV: {path}")
    with path.open(encoding="utf-8", newline="") as handle:
        return [dict(row) for row in csv.DictReader(handle, delimiter="\t")]


def write_tsv(path: Path, fields: Sequence[str], rows: Iterable[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle, fieldnames=list(fields), delimiter="\t", lineterminator="\n",
            extrasaction="ignore",
        )
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
        text=True, capture_output=True,
    )
    require(completed.returncode == 0, completed.stderr.strip() or "archive creation failed")
    os.replace(temporary, output)


def extract_report(archive: Path, destination: Path, expected_root: str) -> Path:
    listed = subprocess.run(["tar", "--zstd", "-tf", str(archive)], text=True, capture_output=True)
    require(listed.returncode == 0, listed.stderr.strip() or f"cannot list {archive}")
    names = [safe_relative(line, "report member") for line in listed.stdout.splitlines() if line.strip()]
    require(names, f"empty report archive: {archive}")
    require({PurePosixPath(name).parts[0] for name in names} == {expected_root}, f"unexpected report root: {archive}")
    destination.mkdir(parents=True, exist_ok=True)
    completed = subprocess.run(["tar", "--zstd", "-xf", str(archive), "-C", str(destination)], text=True, capture_output=True)
    require(completed.returncode == 0, completed.stderr.strip() or f"cannot extract {archive}")
    root = destination / expected_root
    require(root.is_dir(), f"missing extracted report root: {root}")
    return root


def locate_report(
    report_root: Path,
    temporary: Path,
    archive_name: str,
    archive_hash: str,
    root_name: str,
    summary_hash: str,
) -> tuple[Path, dict[str, Any], list[dict[str, Any]]]:
    archive = report_root / archive_name
    require(archive.is_file(), f"missing prerequisite report: {archive}")
    actual_archive_hash = sha256_file(archive)
    require(actual_archive_hash == archive_hash, f"unexpected {archive_name} SHA-256: {actual_archive_hash}")
    root = report_root / root_name
    if not root.is_dir():
        root = extract_report(archive, temporary / root_name, root_name)
    summary_path = root / "SUMMARY.json"
    require(summary_path.is_file(), f"missing prerequisite summary: {summary_path}")
    actual_summary_hash = sha256_file(summary_path)
    require(actual_summary_hash == summary_hash, f"unexpected {root_name} summary SHA-256: {actual_summary_hash}")
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    hashes = [
        {"input_id": root_name, "relative_path": archive_name, "sha256": actual_archive_hash, "verified": True},
        {"input_id": f"{root_name}_summary", "relative_path": f"{root_name}/SUMMARY.json", "sha256": actual_summary_hash, "verified": True},
    ]
    return root, summary, hashes


def load_br_tool(project_root: Path):
    path = project_root / "Blue_Reflection_Text_Tool/br_restoration_tool.py"
    require(path.is_file(), f"missing restoration tool: {path}")
    spec = importlib.util.spec_from_file_location("stage134_br_restoration_tool", path)
    require(spec is not None and spec.loader is not None, "cannot load restoration tool")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def load_inventory(project_root: Path, side: str) -> dict[str, dict[str, Any]]:
    path = project_root / f".local/reports/quartet_restoration/inventories/br1_assets.{side}.json"
    require(path.is_file(), f"missing asset inventory: {path}")
    data = json.loads(path.read_text(encoding="utf-8"))
    require(data.get("archive_group") == "br1_assets", f"inventory group drift: {path}")
    rows: dict[str, dict[str, Any]] = {}
    for raw in data.get("files", []):
        normalized = safe_relative(str(raw.get("normalized_path", "")), "inventory path").casefold()
        require(normalized not in rows, f"duplicate inventory path: {side}:{normalized}")
        rows[normalized] = dict(raw)
    return rows


def find_gust_pak(project_root: Path, explicit: Path | None) -> Path:
    candidates: list[Path] = []
    if explicit is not None:
        candidates.append(explicit.expanduser())
    candidates.append(project_root / ".local/vendor/gust_tools/gust_pak")
    found = shutil.which("gust_pak")
    if found:
        candidates.append(Path(found))
    for candidate in candidates:
        resolved = candidate.resolve()
        if resolved.is_file() and os.access(resolved, os.X_OK):
            return resolved
    raise CollectorError("gust_pak not found; provide --gust-pak or install it under .local/vendor/gust_tools")


def resolve_game_archive(game_root: Path, relative: str) -> Path:
    root = game_root.expanduser().resolve()
    require(root.is_dir(), f"game root does not exist: {root}")
    direct = root / PurePosixPath(relative)
    if direct.is_file():
        return direct.resolve()
    wanted = PurePosixPath(relative).as_posix().casefold()
    matches = [path.resolve() for path in root.rglob("*.PAK") if path.relative_to(root).as_posix().casefold() == wanted]
    require(len(matches) == 1, f"cannot uniquely resolve {relative} below {root}; matches={len(matches)}")
    return matches[0]


def ensure_extraction_cache(
    *,
    project_root: Path,
    workspace_root: Path,
    candidates: Sequence[Mapping[str, str]],
    inventories: Mapping[str, Mapping[str, dict[str, Any]]],
    original_root: Path | None,
    quartet_root: Path | None,
    gust_pak_path: Path | None,
    br: Any,
    timeout_seconds: int,
) -> list[dict[str, Any]]:
    missing_by_side: dict[str, int] = defaultdict(int)
    for row in candidates:
        normalized = row["normalized_path"].casefold()
        for side in ("source", "target"):
            entry = inventories[side].get(normalized)
            require(entry is not None, f"missing inventory entry: {side}:{normalized}")
            local = br.inventory_workspace_file(workspace_root, side, "br1_assets", str(entry["archive"]), str(entry["path"]))
            if not local.is_file():
                missing_by_side[side] += 1
    if not missing_by_side:
        return [
            {"side": "source", "archive_relative": "DATA/PACK00_01.PAK", "cache_action": "reused_existing_workspace"},
            {"side": "target", "archive_relative": "Data/PACK10_01.PAK", "cache_action": "reused_existing_workspace"},
        ]

    require(original_root is not None and quartet_root is not None, "effect workspace is incomplete; provide --original-root and --quartet-root")
    gust = find_gust_pak(project_root, gust_pak_path)
    gust_hash = sha256_file(gust)
    specs = {
        "source": (original_root, "DATA/PACK00_01.PAK"),
        "target": (quartet_root, "Data/PACK10_01.PAK"),
    }
    rows: list[dict[str, Any]] = []
    for side in sorted(missing_by_side):
        root, relative = specs[side]
        archive = resolve_game_archive(root, relative)
        progress(f"extracting read-only {relative} for {missing_by_side[side]} missing effect/posteffect inputs")
        result = br.extract_archive(
            archive=archive,
            game_root=root.expanduser().resolve(),
            gust_pak=gust,
            gust_pak_sha256=gust_hash,
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
            "gust_pak_sha256": gust_hash,
            "cache_action": result["status"],
        })
    return rows


def normalize_member_role(name: str) -> str:
    value = name.casefold().replace("\\", "/")
    value = re.sub(r"pc\d{2}", "{pc}", value)
    value = re.sub(r"mob\d{2}", "{mob}", value)
    value = re.sub(r"(?<!\d)(?:1000|1001|1002|2012|2014)(?!\d)", "{effect_id}", value)
    return value


def normalize_profile_member(value: str) -> str:
    path = safe_relative(value, "profile member").casefold()
    if path.startswith("data/b1/x64/"):
        path = "data/x64/" + path[len("data/b1/x64/"):]
    return path


def load_profile_bindings(project_root: Path, profile_manifest_root: Path | None = None) -> dict[str, list[str]]:
    root = (profile_manifest_root or (project_root / ".local/build/quartet_restoration/core_profiles/generated")).resolve()
    result: dict[str, list[str]] = defaultdict(list)
    if not root.is_dir():
        return result
    for path in sorted(root.glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        profile_id = str(data.get("profile_id", path.stem))
        for member in data.get("changed_members", []):
            result[normalize_profile_member(str(member))].append(profile_id)
    return result


def member_row(
    *,
    container_path: str,
    namespace: str,
    key: str,
    left: Mapping[str, Any] | None,
    right: Mapping[str, Any] | None,
    shader_tokens: Sequence[str],
) -> dict[str, Any]:
    if left and right:
        classification = "identical" if left["sha256"] == right["sha256"] else "changed"
    elif left:
        classification = "removed_in_target"
    else:
        classification = "added_in_target"
    display = str((right or left or {}).get("name", ""))
    folded = display.casefold()
    hits = [token for token in shader_tokens if token in folded]
    return {
        "namespace": namespace,
        "normalized_path": container_path,
        "member_key": key,
        "normalized_member_role": normalize_member_role(display),
        "classification": classification,
        "source_member_name": (left or {}).get("name", ""),
        "target_member_name": (right or {}).get("name", ""),
        "source_member_index": (left or {}).get("index", ""),
        "target_member_index": (right or {}).get("index", ""),
        "source_size": (left or {}).get("size", ""),
        "target_size": (right or {}).get("size", ""),
        "source_sha256": (left or {}).get("sha256", ""),
        "target_sha256": (right or {}).get("sha256", ""),
        "member_extension": str((right or left or {}).get("extension", "")),
        "bounded_shader_token_hits": ",".join(hits),
        "payload_in_evidence": False,
        "visual_or_censorship_semantics_confirmed": False,
        "runtime_confirmed": False,
        "write_authorized": False,
    }


def build_report(
    project_root: Path,
    *,
    report_root: Path | None = None,
    output_report_root: Path | None = None,
    workspace_root: Path | None = None,
    original_root: Path | None = None,
    quartet_root: Path | None = None,
    gust_pak_path: Path | None = None,
    create_archive: bool = True,
    timeout_seconds: int = 1800,
    verify_payload_hashes: bool = True,
    profile_manifest_root: Path | None = None,
) -> tuple[Path | None, dict[str, Any]]:
    project_root = project_root.resolve()
    version_path = project_root / "workstreams/quartet_restoration/VERSION"
    require(version_path.is_file(), f"missing VERSION: {version_path}")
    version = version_path.read_text(encoding="utf-8").strip()
    require(version_tuple(version) >= version_tuple(TOOL_VERSION), f"expected quartet_restoration {TOOL_VERSION} or newer, found {version}")
    report_root = (report_root or project_root / ".local/reports/quartet_restoration").resolve()
    output_report_root = (output_report_root or report_root).resolve()
    workspace_root = (workspace_root or project_root / ".local/build/quartet_restoration").resolve()
    output = output_report_root / REPORT_DIR
    archive = output_report_root / REPORT_NAME
    if output.exists():
        shutil.rmtree(output)
    output.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="stage134-prereq-") as temp_text:
        temporary = Path(temp_text)
        stage130, summary130, input130 = locate_report(
            report_root, temporary, STAGE130_NAME, STAGE130_SHA256,
            STAGE130_DIR, STAGE130_SUMMARY_SHA256,
        )
        stage131, summary131, input131 = locate_report(
            report_root, temporary, STAGE131_NAME, STAGE131_SHA256,
            STAGE131_DIR, STAGE131_SUMMARY_SHA256,
        )
        stage133, summary133, input133 = locate_report(
            report_root, temporary, STAGE133_NAME, STAGE133_SHA256,
            STAGE133_DIR, STAGE133_SUMMARY_SHA256,
        )
        require(summary130.get("effect_nonidentical_path_rows") == EXPECTED_EFFECT_PATHS, "stage-130 effect count drift")
        require(summary130.get("posteffect_nonidentical_path_rows") == EXPECTED_POSTEFFECT_PATHS, "stage-130 posteffect count drift")
        require(summary131.get("field_candidate_path_rows") == 318, "stage-131 prerequisite drift")
        require(summary133.get("interface_stable_executable_candidate_path_rows") == EXPECTED_SHADER_CANDIDATES, "stage-133 candidate count drift")

        container_candidates = [
            row for row in read_tsv(stage130 / "NON_CHARACTER_TECHNICAL_CANDIDATES.tsv")
            if row["namespace"] in {"effect", "posteffect"}
        ]
        require(len(container_candidates) == EXPECTED_CONTAINER_PATHS, f"expected {EXPECTED_CONTAINER_PATHS} effect/posteffect paths, found {len(container_candidates)}")
        require(sum(row["namespace"] == "effect" for row in container_candidates) == EXPECTED_EFFECT_PATHS, "effect path count drift")
        require(sum(row["namespace"] == "posteffect" for row in container_candidates) == EXPECTED_POSTEFFECT_PATHS, "posteffect path count drift")

        shader_rows = [
            row for row in read_tsv(stage133 / "SHADER_PATH_CLASSIFICATION.tsv")
            if row["path_disposition"] == "executable_code_delta_interface_stable"
        ]
        require(len(shader_rows) == EXPECTED_SHADER_CANDIDATES, f"expected {EXPECTED_SHADER_CANDIDATES} bounded shader candidates, found {len(shader_rows)}")
        shader_tokens = [PurePosixPath(row["normalized_path"]).stem.casefold() for row in shader_rows]
        require(len(set(shader_tokens)) == EXPECTED_SHADER_CANDIDATES, "bounded shader basename collision")

        inventories = {side: load_inventory(project_root, side) for side in ("source", "target")}
        br = load_br_tool(project_root)
        extraction_rows = ensure_extraction_cache(
            project_root=project_root,
            workspace_root=workspace_root,
            candidates=container_candidates,
            inventories=inventories,
            original_root=original_root,
            quartet_root=quartet_root,
            gust_pak_path=gust_pak_path,
            br=br,
            timeout_seconds=timeout_seconds,
        )

        path_rows: list[dict[str, Any]] = []
        ledger_rows: list[dict[str, Any]] = []
        input_rows: list[dict[str, Any]] = []
        payload_bytes_read = 0
        for index, candidate in enumerate(sorted(container_candidates, key=lambda row: row["normalized_path"]), start=1):
            normalized = candidate["normalized_path"].casefold()
            progress(f"reading {index}/{EXPECTED_CONTAINER_PATHS}: {normalized}")
            parsed: dict[str, dict[str, Any]] = {}
            for side in ("source", "target"):
                entry = inventories[side].get(normalized)
                require(entry is not None, f"missing inventory: {side}:{normalized}")
                local = br.inventory_workspace_file(workspace_root, side, "br1_assets", str(entry["archive"]), str(entry["path"]))
                require(local.is_file(), f"missing cached input: {local}")
                if verify_payload_hashes:
                    actual = sha256_file(local)
                    require(actual == str(entry["sha256"]), f"payload hash drift: {side}:{normalized}: {actual}")
                    require(local.stat().st_size == int(entry["size"]), f"payload size drift: {side}:{normalized}")
                archive_data = br.read_earc_archive(local, maximum_bytes=MAX_EARC_BYTES, include_member_payloads=False)
                parsed[side] = archive_data
                payload_bytes_read += int(archive_data["decoded_bytes"])
                input_rows.append({
                    "side": side,
                    "namespace": candidate["namespace"],
                    "normalized_path": normalized,
                    "container_archive": entry["archive"],
                    "input_size": local.stat().st_size,
                    "input_sha256": sha256_file(local),
                    "container": archive_data["container"],
                    "decoded_bytes": archive_data["decoded_bytes"],
                    "decoded_sha256": archive_data["decoded_sha256"],
                    "member_count": archive_data["file_count"],
                    "payload_in_evidence": False,
                    "write_authorized": False,
                })
            source_members = {str(row["comparison_key"]): row for row in parsed["source"]["members"]}
            target_members = {str(row["comparison_key"]): row for row in parsed["target"]["members"]}
            counts: Counter[str] = Counter()
            for key in sorted(set(source_members) | set(target_members), key=str.casefold):
                row = member_row(
                    container_path=normalized,
                    namespace=candidate["namespace"],
                    key=key,
                    left=source_members.get(key),
                    right=target_members.get(key),
                    shader_tokens=shader_tokens,
                )
                counts[row["classification"]] += 1
                ledger_rows.append(row)
            path_rows.append({
                "namespace": candidate["namespace"],
                "normalized_path": normalized,
                "source_member_rows": parsed["source"]["file_count"],
                "target_member_rows": parsed["target"]["file_count"],
                "identical_member_rows": counts["identical"],
                "changed_member_rows": counts["changed"],
                "added_member_rows": counts["added_in_target"],
                "removed_member_rows": counts["removed_in_target"],
                "nonidentical_member_rows": counts["changed"] + counts["added_in_target"] + counts["removed_in_target"],
                "exact_member_saturation_complete": True,
                "visual_or_censorship_semantics_confirmed": False,
                "runtime_confirmed": False,
                "write_authorized": False,
            })

        nonidentical = [row for row in ledger_rows if row["classification"] != "identical"]
        role_groups: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
        for row in nonidentical:
            role_groups[(row["normalized_member_role"], row["member_extension"], row["classification"])].append(row)
        role_rows: list[dict[str, Any]] = []
        for (role, extension, classification), rows in sorted(role_groups.items()):
            role_rows.append({
                "normalized_member_role": role,
                "member_extension": extension,
                "classification": classification,
                "member_rows": len(rows),
                "container_path_rows": len({row["normalized_path"] for row in rows}),
                "namespaces": ",".join(sorted({row["namespace"] for row in rows})),
                "bounded_shader_token_hits": ",".join(sorted({token for row in rows for token in row["bounded_shader_token_hits"].split(",") if token})),
                "recurrent_role_family": len({row["normalized_path"] for row in rows}) >= 2,
                "semantic_classification": "unresolved_metadata_only",
                "write_authorized": False,
            })

        field_rows = read_tsv(stage131 / "FIELD_ARCHIVE_MEMBER_DELTAS.tsv")
        profile_bindings = load_profile_bindings(project_root, profile_manifest_root)
        program_rows = read_tsv(stage133 / "DXBC_PROGRAM_CLASSIFICATION.tsv")
        shader_dependency_rows: list[dict[str, Any]] = []
        for shader in sorted(shader_rows, key=lambda row: row["normalized_path"]):
            path = shader["normalized_path"].casefold()
            token = PurePosixPath(path).stem.casefold()
            effect_hits = [row for row in ledger_rows if token in (str(row["source_member_name"]) + " " + str(row["target_member_name"])).casefold()]
            field_hits = [row for row in field_rows if token in (str(row.get("source_member_name", "")) + " " + str(row.get("target_member_name", ""))).casefold()]
            profiles = sorted(profile_bindings.get(path, []))
            programs = [row for row in program_rows if row["normalized_path"].casefold() == path]
            executable = [row for row in programs if row["classification"] == "executable_code_delta_interface_stable"]
            reflection_pairs = {
                f"{row.get('source_reflection_semantic_sha256', '')}->{row.get('target_reflection_semantic_sha256', '')}"
                for row in programs
                if row.get("source_reflection_semantic_sha256") or row.get("target_reflection_semantic_sha256")
            }
            if profiles and (effect_hits or field_hits):
                disposition = "inactive_profile_plus_member_name_reference_only"
            elif profiles:
                disposition = "inactive_profile_only_no_member_name_reference"
            elif effect_hits or field_hits:
                disposition = "member_name_reference_only_no_profile"
            else:
                disposition = "no_static_dependency_binding_found"
            shader_dependency_rows.append({
                "normalized_path": path,
                "shader_basename_token": token,
                "executable_code_delta_program_rows": len(executable),
                "dxbc_program_rows": len(programs),
                "reflection_signature_pair_rows": len(reflection_pairs),
                "effect_posteffect_member_name_hit_rows": len(effect_hits),
                "field_member_name_hit_rows": len(field_hits),
                "inactive_profile_rows": len(profiles),
                "inactive_profile_ids": ",".join(profiles),
                "static_dependency_disposition": disposition,
                "dependency_binding_resolved": False,
                "visual_or_censorship_semantics_confirmed": False,
                "runtime_confirmed": False,
                "write_authorized": False,
            })

        input_hashes = input130 + input131 + input133
        write_tsv(output / "INPUT_HASHES.tsv", ["input_id", "relative_path", "sha256", "verified"], input_hashes)
        write_tsv(output / "EXTRACTION_INPUTS.tsv", ["side", "archive_relative", "archive_size", "archive_sha256", "gust_pak_sha256", "cache_action"], extraction_rows)
        write_tsv(output / "EFFECT_POSTEFFECT_ARCHIVE_INPUTS.tsv", [
            "side", "namespace", "normalized_path", "container_archive", "input_size", "input_sha256",
            "container", "decoded_bytes", "decoded_sha256", "member_count", "payload_in_evidence", "write_authorized",
        ], input_rows)
        write_tsv(output / "EFFECT_POSTEFFECT_PATH_SUMMARY.tsv", [
            "namespace", "normalized_path", "source_member_rows", "target_member_rows", "identical_member_rows",
            "changed_member_rows", "added_member_rows", "removed_member_rows", "nonidentical_member_rows",
            "exact_member_saturation_complete", "visual_or_censorship_semantics_confirmed", "runtime_confirmed", "write_authorized",
        ], path_rows)
        write_tsv(output / "EFFECT_POSTEFFECT_MEMBER_LEDGER.tsv", [
            "namespace", "normalized_path", "member_key", "normalized_member_role", "classification",
            "source_member_name", "target_member_name", "source_member_index", "target_member_index",
            "source_size", "target_size", "source_sha256", "target_sha256", "member_extension",
            "bounded_shader_token_hits", "payload_in_evidence", "visual_or_censorship_semantics_confirmed",
            "runtime_confirmed", "write_authorized",
        ], ledger_rows)
        write_tsv(output / "EFFECT_POSTEFFECT_MEMBER_ROLE_FAMILIES.tsv", [
            "normalized_member_role", "member_extension", "classification", "member_rows", "container_path_rows",
            "namespaces", "bounded_shader_token_hits", "recurrent_role_family", "semantic_classification", "write_authorized",
        ], role_rows)
        write_tsv(output / "BOUNDED_SHADER_STATIC_DEPENDENCY_AUDIT.tsv", [
            "normalized_path", "shader_basename_token", "executable_code_delta_program_rows", "dxbc_program_rows",
            "reflection_signature_pair_rows", "effect_posteffect_member_name_hit_rows", "field_member_name_hit_rows",
            "inactive_profile_rows", "inactive_profile_ids", "static_dependency_disposition", "dependency_binding_resolved",
            "visual_or_censorship_semantics_confirmed", "runtime_confirmed", "write_authorized",
        ], shader_dependency_rows)
        write_tsv(output / "EFFECT_POSTEFFECT_SCAN_SKIPPED.tsv", ["scope", "reason", "detail"], [])

        member_counts = Counter(row["classification"] for row in ledger_rows)
        disposition_counts = Counter(row["static_dependency_disposition"] for row in shader_dependency_rows)
        summary = {
            "type": "br_quartet_restoration_effect_posteffect_namespace_member_saturation_evidence_summary",
            "format_version": 1,
            "tool_version": TOOL_VERSION,
            "status": "complete_effect_posteffect_member_saturation_and_bounded_shader_static_dependency_audit_metadata_only_semantics_unresolved_no_write",
            "stage130_report_sha256": STAGE130_SHA256,
            "stage131_report_sha256": STAGE131_SHA256,
            "stage133_report_sha256": STAGE133_SHA256,
            "container_path_rows": len(path_rows),
            "effect_path_rows": sum(row["namespace"] == "effect" for row in path_rows),
            "posteffect_path_rows": sum(row["namespace"] == "posteffect" for row in path_rows),
            "member_rows": len(ledger_rows),
            "identical_member_rows": member_counts["identical"],
            "changed_member_rows": member_counts["changed"],
            "added_member_rows": member_counts["added_in_target"],
            "removed_member_rows": member_counts["removed_in_target"],
            "nonidentical_member_rows": len(nonidentical),
            "member_role_family_rows": len(role_rows),
            "recurrent_member_role_family_rows": sum(parse_bool(row["recurrent_role_family"]) for row in role_rows),
            "bounded_shader_candidate_rows": len(shader_dependency_rows),
            "bounded_shader_candidate_with_member_name_reference_rows": sum(
                int(row["effect_posteffect_member_name_hit_rows"]) + int(row["field_member_name_hit_rows"]) > 0
                for row in shader_dependency_rows
            ),
            "bounded_shader_candidate_with_inactive_profile_rows": sum(int(row["inactive_profile_rows"]) > 0 for row in shader_dependency_rows),
            "resolved_shader_dependency_binding_rows": 0,
            "shader_dependency_dispositions": dict(sorted(disposition_counts.items())),
            "payload_bytes_read": payload_bytes_read,
            "skipped_rows": 0,
            "runtime_confirmed_rows": 0,
            "visual_or_censorship_semantics_confirmed_rows": 0,
            "write_authorized_rows": 0,
            "policy": {
                "local_proprietary_payloads_read": True,
                "proprietary_payloads_in_report": False,
                "installed_game_modified": False,
                "pak_built_or_repacked": False,
                "effect_or_posteffect_payload_written": False,
                "shader_payload_written": False,
                "profile_or_registry_modified": False,
                "core_modified": False,
                "translation_modified": False,
                "legacy_dlc_modified": False,
                "git_modified": False,
                "save_or_runtime_required": False,
                "shader_basename_or_member_name_treated_as_dependency_proof": False,
                "shader_or_member_name_treated_as_visual_semantics": False,
                "restoration_prototype_authorized": False,
            },
            "next_action": (
                "Use the saturated seven-container member ledger to classify recurring effect/posteffect roles and exact format families. "
                "Keep all fifteen interface-stable shader candidates unresolved unless a genuinely independent selector or resource-binding channel appears. "
                "Then continue broad discovery with the remaining effect/posteffect format-specific classification; do not require saves or build Canary-all."
            ),
        }
        atomic_json(output / "SUMMARY.json", summary)

    forbidden = [
        path for path in output.rglob("*") if path.is_file()
        and any(path.name.casefold().endswith(ext) for ext in FORBIDDEN_EXTENSIONS)
    ]
    require(not forbidden, f"forbidden payload files in report: {[path.name for path in forbidden]}")
    if create_archive:
        make_archive(output, archive)
        return archive, summary
    return None, summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", default=str(Path(__file__).resolve().parents[2]))
    parser.add_argument("--report-root")
    parser.add_argument("--output-report-root")
    parser.add_argument("--workspace-root")
    parser.add_argument("--original-root")
    parser.add_argument("--quartet-root")
    parser.add_argument("--gust-pak")
    parser.add_argument("--timeout-seconds", type=int, default=1800)
    parser.add_argument("--no-archive", action="store_true")
    parser.add_argument("--no-verify-payload-hashes", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        archive, summary = build_report(
            Path(args.project_root),
            report_root=Path(args.report_root) if args.report_root else None,
            output_report_root=Path(args.output_report_root) if args.output_report_root else None,
            workspace_root=Path(args.workspace_root) if args.workspace_root else None,
            original_root=Path(args.original_root) if args.original_root else None,
            quartet_root=Path(args.quartet_root) if args.quartet_root else None,
            gust_pak_path=Path(args.gust_pak) if args.gust_pak else None,
            create_archive=not args.no_archive,
            timeout_seconds=args.timeout_seconds,
            verify_payload_hashes=not args.no_verify_payload_hashes,
        )
    except (CollectorError, OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"[effect-posteffect-saturation] ERROR: {exc}", file=sys.stderr)
        return 1
    if archive is not None:
        print(f"[effect-posteffect-saturation] report archive: {archive}")
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
