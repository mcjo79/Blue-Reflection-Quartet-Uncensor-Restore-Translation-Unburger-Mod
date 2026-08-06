#!/usr/bin/env python3
"""Stage 133: full shader namespace executable/signature/reflection sweep.

This collector consumes the bounded 214-path shader queue from stage 130 and
classifies every G1S pair at embedded-DXBC level.  It records executable code,
RDEF reflection semantics, IO signature semantics, compiler/stat metadata and
outer-envelope-only differences separately.  The one target-only G1T path is
kept as a texture dependency row only.

Installed games are read only.  The report contains metadata, hashes and counts
only; it never exports G1S/G1T/DXBC payload bytes or authorizes a write.
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

TOOL_VERSION = "0.1.51"
REPORT_DIR = "shader_namespace_executable_signature_reflection_sweep_evidence"
REPORT_NAME = "BR_quartet_restoration_shader_namespace_executable_signature_reflection_sweep_evidence.tar.zst"

STAGE130_NAME = "BR_quartet_restoration_non_character_namespace_saturation_audit_evidence.tar.zst"
STAGE130_SHA256 = "de8b339921387dfa8858415110166120f49ceddcf63ea148883fcf41d214d69c"
STAGE130_DIR = "non_character_namespace_saturation_audit"
STAGE130_SUMMARY_SHA256 = "3b1293b422d19a9ab87a22d00b46755ca7e23d48b6d46ea1795ac0435080decd"

STAGE132_NAME = "BR_quartet_restoration_field_member_role_format_classification_evidence.tar.zst"
STAGE132_SHA256 = "34073f28482f064a28908d6b0b429d636d203f14362808f606b36864bd0cab7f"
STAGE132_DIR = "field_member_role_format_classification_evidence"
STAGE132_SUMMARY_SHA256 = "6199256293f0da4da6cc1cd6eb2b002c7a4d5da5998c03c9aa8a2532bb8697a1"

EXPECTED_PATHS = 214
EXPECTED_G1S = 213
EXPECTED_G1T = 1
EXPECTED_CHANGED = 190
EXPECTED_TARGET_ONLY = 24
EXPECTED_GENERATED = 150
EXPECTED_NAMED = 64
MAX_SHADER_BYTES = 64 * 1024 * 1024
FORBIDDEN_EXTENSIONS = (
    ".pak", ".g1s", ".g1t", ".dxbc", ".g1m", ".g1e", ".g1em",
    ".elixir", ".elixir.gz", ".ebd", ".ebm",
)


class CollectorError(RuntimeError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise CollectorError(message)


def progress(message: str) -> None:
    print(f"[shader-namespace-sweep] {message}", file=sys.stderr, flush=True)


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
    spec = importlib.util.spec_from_file_location("stage133_br_restoration_tool", path)
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
            if entry is None:
                require(side == "source" and row["classification"] == "new_in_target", f"missing inventory entry: {side}:{normalized}")
                continue
            local = br.inventory_workspace_file(workspace_root, side, "br1_assets", str(entry["archive"]), str(entry["path"]))
            if not local.is_file():
                missing_by_side[side] += 1
    if not missing_by_side:
        return [
            {"side": "source", "archive_relative": "DATA/PACK00_01.PAK", "cache_action": "reused_existing_workspace"},
            {"side": "target", "archive_relative": "Data/PACK10_01.PAK", "cache_action": "reused_existing_workspace"},
        ]

    require(original_root is not None and quartet_root is not None, "shader workspace is incomplete; provide --original-root and --quartet-root")
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
        progress(f"extracting read-only {relative} for {missing_by_side[side]} missing shader inputs")
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


def pair_programs(source: Sequence[dict[str, Any]], target: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    """Pair all programs deterministically, preserving exact matches as rows."""
    pairs: list[dict[str, Any]] = []
    used_source: set[int] = set()
    used_target: set[int] = set()
    target_by_hash: dict[str, list[int]] = defaultdict(list)
    for index, row in enumerate(target):
        target_by_hash[str(row.get("sha256", ""))].append(index)
    for source_index, source_row in enumerate(source):
        match = next((idx for idx in target_by_hash.get(str(source_row.get("sha256", "")), []) if idx not in used_target), None)
        if match is None:
            continue
        used_source.add(source_index)
        used_target.add(match)
        pairs.append({"source": source_row, "target": target[match], "matching_basis": "exact_program_sha256"})

    source_groups: dict[tuple[str, str], list[int]] = defaultdict(list)
    target_groups: dict[tuple[str, str], list[int]] = defaultdict(list)
    for index, row in enumerate(source):
        if index not in used_source:
            source_groups[(str(row.get("stage", "")), str(row.get("chunk_fourccs", "")))].append(index)
    for index, row in enumerate(target):
        if index not in used_target:
            target_groups[(str(row.get("stage", "")), str(row.get("chunk_fourccs", "")))].append(index)
    for signature in sorted(set(source_groups) | set(target_groups)):
        left = sorted(source_groups.get(signature, []), key=lambda idx: int(source[idx].get("size", 0)))
        right = sorted(target_groups.get(signature, []), key=lambda idx: int(target[idx].get("size", 0)))
        while left and right:
            source_index = left.pop(0)
            source_size = int(source[source_index].get("size", 0))
            position = min(range(len(right)), key=lambda pos: abs(int(target[right[pos]].get("size", 0)) - source_size))
            target_index = right.pop(position)
            used_source.add(source_index)
            used_target.add(target_index)
            pairs.append({"source": source[source_index], "target": target[target_index], "matching_basis": "stage_chunk_layout_nearest_size"})
    for index, row in enumerate(source):
        if index not in used_source:
            pairs.append({"source": row, "target": None, "matching_basis": "unmatched_source_program"})
    for index, row in enumerate(target):
        if index not in used_target:
            pairs.append({"source": None, "target": row, "matching_basis": "unmatched_target_program"})
    return sorted(
        pairs,
        key=lambda pair: (
            int((pair.get("target") or pair.get("source") or {}).get("program_index", 0)),
            str(pair.get("matching_basis", "")),
        ),
    )


def chunk_map(br: Any, payload: bytes | None, program: Mapping[str, Any] | None) -> dict[str, dict[str, Any]]:
    if payload is None or program is None:
        return {}
    return {row["comparison_key"]: row for row in br.parse_dxbc_chunk_payloads(payload, dict(program))}


def rdef_semantics(br: Any, chunks: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    row = chunks.get("RDEF#0")
    if row is None:
        return {"status": "missing", "reflection_semantic_sha256": "", "creator": ""}
    return br.parse_dxbc_rdef(row["payload"])


def signature_semantics(br: Any, chunks: Mapping[str, Mapping[str, Any]]) -> tuple[str, str]:
    rows: list[tuple[str, str, str]] = []
    unresolved = False
    signature_fourccs = set(br.DXBC_SIGNATURE_FOURCCS) | {"ISG1", "OSG1"}
    for key, row in sorted(chunks.items()):
        if row["fourcc"] not in signature_fourccs:
            continue
        parsed = br.parse_dxbc_signature(row["payload"], str(row["fourcc"]))
        status = str(parsed.get("status", ""))
        semantic_hash = str(parsed.get("semantic_sha256", ""))
        rows.append((key, status, semantic_hash))
        if status not in {"ok", "missing"}:
            unresolved = True
    digest = hashlib.sha256(json.dumps(rows, separators=(",", ":")).encode("utf-8")).hexdigest()
    return ("parse_unresolved" if unresolved else "ok"), digest


def program_analysis(
    br: Any,
    source_payload: bytes | None,
    target_payload: bytes | None,
    source_program: Mapping[str, Any] | None,
    target_program: Mapping[str, Any] | None,
    matching_basis: str,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    if source_program is None:
        return ({
            "classification": "program_added_in_target",
            "matching_basis": matching_basis,
            "reflection_semantics": "not_comparable",
            "signature_semantics": "not_comparable",
            "code_chunks_identical": False,
        }, [])
    if target_program is None:
        return ({
            "classification": "program_removed_in_target",
            "matching_basis": matching_basis,
            "reflection_semantics": "not_comparable",
            "signature_semantics": "not_comparable",
            "code_chunks_identical": False,
        }, [])

    source_chunks = chunk_map(br, source_payload, source_program)
    target_chunks = chunk_map(br, target_payload, target_program)
    chunk_rows: list[dict[str, Any]] = []
    for key in sorted(set(source_chunks) | set(target_chunks), key=str.casefold):
        left = source_chunks.get(key)
        right = target_chunks.get(key)
        if left and right:
            classification = "identical" if left["sha256"] == right["sha256"] else "changed"
        elif left:
            classification = "removed_in_target"
        else:
            classification = "added_in_target"
        chunk_rows.append({
            "chunk_key": key,
            "fourcc": str((right or left or {}).get("fourcc", "")),
            "source_size": (left or {}).get("size", ""),
            "target_size": (right or {}).get("size", ""),
            "source_sha256": (left or {}).get("sha256", ""),
            "target_sha256": (right or {}).get("sha256", ""),
            "classification": classification,
        })

    code_keys = sorted(
        key for key, row in {**source_chunks, **target_chunks}.items()
        if str(row.get("fourcc", "")) in br.DXBC_CODE_FOURCCS
    )
    code_equal = bool(code_keys) and all(
        key in source_chunks and key in target_chunks and source_chunks[key]["sha256"] == target_chunks[key]["sha256"]
        for key in code_keys
    )

    source_rdef = rdef_semantics(br, source_chunks)
    target_rdef = rdef_semantics(br, target_chunks)
    source_rdef_status = str(source_rdef.get("status", ""))
    target_rdef_status = str(target_rdef.get("status", ""))
    if source_rdef_status == target_rdef_status == "missing":
        reflection_state = "compatible_absent"
    elif source_rdef_status == target_rdef_status == "ok":
        reflection_state = (
            "compatible" if source_rdef.get("reflection_semantic_sha256") == target_rdef.get("reflection_semantic_sha256")
            else "different"
        )
    else:
        reflection_state = "parse_unresolved"

    source_signature_status, source_signature_hash = signature_semantics(br, source_chunks)
    target_signature_status, target_signature_hash = signature_semantics(br, target_chunks)
    if source_signature_status == target_signature_status == "ok":
        signature_state = "compatible" if source_signature_hash == target_signature_hash else "different"
    else:
        signature_state = "parse_unresolved"

    exact = str(source_program.get("sha256", "")) == str(target_program.get("sha256", ""))
    interface_stable = reflection_state.startswith("compatible") and signature_state == "compatible"
    interface_different = reflection_state == "different" or signature_state == "different"
    if exact:
        classification = "identical_program"
    elif not code_equal:
        if interface_stable:
            classification = "executable_code_delta_interface_stable"
        elif interface_different:
            classification = "executable_code_delta_with_interface_delta"
        else:
            classification = "executable_code_delta_interface_unresolved"
    elif interface_different:
        classification = "interface_delta_without_executable_code_delta"
    elif reflection_state == "parse_unresolved" or signature_state == "parse_unresolved":
        classification = "noncode_delta_interface_parse_unresolved"
    else:
        classification = "nonexecutive_metadata_or_compiler_delta"

    return ({
        "classification": classification,
        "matching_basis": matching_basis,
        "reflection_semantics": reflection_state,
        "signature_semantics": signature_state,
        "code_chunks_identical": code_equal,
        "source_rdef_status": source_rdef_status,
        "target_rdef_status": target_rdef_status,
        "source_reflection_semantic_sha256": source_rdef.get("reflection_semantic_sha256", ""),
        "target_reflection_semantic_sha256": target_rdef.get("reflection_semantic_sha256", ""),
        "source_creator_sha256": hashlib.sha256(str(source_rdef.get("creator", "")).encode()).hexdigest() if source_rdef.get("creator") else "",
        "target_creator_sha256": hashlib.sha256(str(target_rdef.get("creator", "")).encode()).hexdigest() if target_rdef.get("creator") else "",
        "source_signature_semantic_sha256": source_signature_hash,
        "target_signature_semantic_sha256": target_signature_hash,
    }, chunk_rows)


def path_disposition(program_rows: Sequence[Mapping[str, Any]], file_hash_equal: bool) -> str:
    classes = Counter(str(row.get("classification", "")) for row in program_rows)
    if classes["program_added_in_target"] or classes["program_removed_in_target"]:
        return "dxbc_program_inventory_delta"
    if classes["executable_code_delta_with_interface_delta"]:
        return "executable_code_delta_with_interface_delta"
    if classes["executable_code_delta_interface_unresolved"]:
        return "executable_code_delta_interface_unresolved"
    if classes["executable_code_delta_interface_stable"]:
        return "executable_code_delta_interface_stable"
    if classes["interface_delta_without_executable_code_delta"]:
        return "interface_delta_without_executable_code_delta"
    if classes["noncode_delta_interface_parse_unresolved"]:
        return "noncode_delta_interface_parse_unresolved"
    if classes["nonexecutive_metadata_or_compiler_delta"]:
        return "nonexecutive_metadata_or_compiler_delta"
    if file_hash_equal:
        return "identical_file"
    return "outer_g1s_envelope_only"


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

    with tempfile.TemporaryDirectory(prefix="stage133-prereq-") as temp_text:
        temporary = Path(temp_text)
        stage130, summary130, input130 = locate_report(
            report_root, temporary, STAGE130_NAME, STAGE130_SHA256,
            STAGE130_DIR, STAGE130_SUMMARY_SHA256,
        )
        _stage132, summary132, input132 = locate_report(
            report_root, temporary, STAGE132_NAME, STAGE132_SHA256,
            STAGE132_DIR, STAGE132_SUMMARY_SHA256,
        )
        require(summary130.get("shader_nonidentical_path_rows") == EXPECTED_PATHS, "stage-130 shader path count drift")
        require(summary132.get("member_role_family_rows") == 2796, "stage-132 prerequisite drift")
        candidates = [row for row in read_tsv(stage130 / "NON_CHARACTER_TECHNICAL_CANDIDATES.tsv") if row["namespace"] == "shader"]
        require(len(candidates) == EXPECTED_PATHS, f"expected {EXPECTED_PATHS} shader paths, found {len(candidates)}")
        require(sum(row["extension"] == ".g1s" for row in candidates) == EXPECTED_G1S, "G1S count drift")
        require(sum(row["extension"] == ".g1t" for row in candidates) == EXPECTED_G1T, "G1T count drift")
        require(sum(row["classification"] == "changed" for row in candidates) == EXPECTED_CHANGED, "changed shader count drift")
        require(sum(row["classification"] == "new_in_target" for row in candidates) == EXPECTED_TARGET_ONLY, "target-only shader count drift")
        require(sum(row["shader_family"] == "generated_variant" for row in candidates) == EXPECTED_GENERATED, "generated shader count drift")
        require(sum(row["shader_family"] == "named_shader_or_texture" for row in candidates) == EXPECTED_NAMED, "named shader count drift")
        input_hashes = input130 + input132

    br = load_br_tool(project_root)
    inventories = {"source": load_inventory(project_root, "source"), "target": load_inventory(project_root, "target")}
    extraction_rows = ensure_extraction_cache(
        project_root=project_root,
        workspace_root=workspace_root,
        candidates=candidates,
        inventories=inventories,
        original_root=original_root,
        quartet_root=quartet_root,
        gust_pak_path=gust_pak_path,
        br=br,
        timeout_seconds=timeout_seconds,
    )

    path_rows: list[dict[str, Any]] = []
    program_rows: list[dict[str, Any]] = []
    chunk_rows: list[dict[str, Any]] = []
    target_only_rows: list[dict[str, Any]] = []
    skipped_rows: list[dict[str, Any]] = []
    payload_bytes_read = 0

    for index, candidate in enumerate(sorted(candidates, key=lambda row: row["normalized_path"]), 1):
        normalized = safe_relative(candidate["normalized_path"], "shader path")
        progress(f"path {index}/{len(candidates)} {normalized}")
        payloads: dict[str, bytes | None] = {"source": None, "target": None}
        file_hashes: dict[str, str] = {"source": "", "target": ""}
        file_sizes: dict[str, int | str] = {"source": "", "target": ""}
        try:
            for side in ("source", "target"):
                entry = inventories[side].get(normalized.casefold())
                if entry is None:
                    require(side == "source" and candidate["classification"] == "new_in_target", f"missing {side} inventory row: {normalized}")
                    continue
                local = br.inventory_workspace_file(workspace_root, side, "br1_assets", str(entry["archive"]), str(entry["path"]))
                require(local.is_file(), f"missing extracted shader input: {side}:{normalized}: {local}")
                require(local.stat().st_size <= MAX_SHADER_BYTES, f"shader input exceeds safety limit: {side}:{normalized}")
                actual_hash = sha256_file(local)
                if verify_payload_hashes:
                    require(actual_hash == str(entry["sha256"]), f"payload hash drift: {side}:{normalized}: {actual_hash}")
                payload = local.read_bytes()
                payload_bytes_read += len(payload)
                payloads[side] = payload
                file_hashes[side] = actual_hash
                file_sizes[side] = len(payload)

            if candidate["extension"] == ".g1t":
                require(payloads["source"] is None and payloads["target"] is not None, "expected target-only shader texture")
                disposition = "target_only_shader_texture_dependency"
                target_only_rows.append({
                    "normalized_path": normalized,
                    "extension": ".g1t",
                    "target_size": file_sizes["target"],
                    "target_sha256": file_hashes["target"],
                    "dependency_semantics_confirmed": False,
                    "runtime_confirmed": False,
                    "write_authorized": False,
                })
                path_rows.append({
                    **candidate,
                    "source_program_rows": 0,
                    "target_program_rows": 0,
                    "paired_program_rows": 0,
                    "executable_code_delta_program_rows": 0,
                    "interface_delta_program_rows": 0,
                    "metadata_only_program_rows": 0,
                    "path_disposition": disposition,
                    "restoration_code_candidate": False,
                    "runtime_confirmed": False,
                    "visual_or_censorship_semantics_confirmed": False,
                    "write_authorized": False,
                })
                continue

            source_programs = br.find_dxbc_programs(payloads["source"] or b"", label=f"source:{normalized}")
            target_programs = br.find_dxbc_programs(payloads["target"] or b"", label=f"target:{normalized}")
            local_program_rows: list[dict[str, Any]] = []
            if payloads["source"] is None:
                for target_program in target_programs:
                    analysis, local_chunks = program_analysis(br, None, payloads["target"], None, target_program, "target_only_program")
                    base = {
                        "normalized_path": normalized,
                        "shader_family": candidate["shader_family"],
                        "source_program_index": "",
                        "target_program_index": target_program.get("program_index", ""),
                        "source_stage": "",
                        "target_stage": target_program.get("stage", ""),
                        "source_shader_model": "",
                        "target_shader_model": target_program.get("shader_model", ""),
                        "source_program_size": "",
                        "target_program_size": target_program.get("size", ""),
                        "source_program_sha256": "",
                        "target_program_sha256": target_program.get("sha256", ""),
                        **analysis,
                        "runtime_confirmed": False,
                        "visual_or_censorship_semantics_confirmed": False,
                        "write_authorized": False,
                    }
                    local_program_rows.append(base)
                    program_rows.append(base)
                    for chunk in local_chunks:
                        chunk_rows.append({**base, **chunk})
                disposition = "target_only_shader_program_inventory"
                target_only_rows.append({
                    "normalized_path": normalized,
                    "extension": ".g1s",
                    "target_size": file_sizes["target"],
                    "target_sha256": file_hashes["target"],
                    "target_program_rows": len(target_programs),
                    "dependency_semantics_confirmed": False,
                    "runtime_confirmed": False,
                    "write_authorized": False,
                })
            else:
                for pair in pair_programs(source_programs, target_programs):
                    source_program = pair.get("source")
                    target_program = pair.get("target")
                    analysis, local_chunks = program_analysis(
                        br,
                        payloads["source"], payloads["target"],
                        source_program, target_program,
                        str(pair["matching_basis"]),
                    )
                    base = {
                        "normalized_path": normalized,
                        "shader_family": candidate["shader_family"],
                        "source_program_index": (source_program or {}).get("program_index", ""),
                        "target_program_index": (target_program or {}).get("program_index", ""),
                        "source_stage": (source_program or {}).get("stage", ""),
                        "target_stage": (target_program or {}).get("stage", ""),
                        "source_shader_model": (source_program or {}).get("shader_model", ""),
                        "target_shader_model": (target_program or {}).get("shader_model", ""),
                        "source_program_size": (source_program or {}).get("size", ""),
                        "target_program_size": (target_program or {}).get("size", ""),
                        "source_program_sha256": (source_program or {}).get("sha256", ""),
                        "target_program_sha256": (target_program or {}).get("sha256", ""),
                        **analysis,
                        "runtime_confirmed": False,
                        "visual_or_censorship_semantics_confirmed": False,
                        "write_authorized": False,
                    }
                    local_program_rows.append(base)
                    program_rows.append(base)
                    for chunk in local_chunks:
                        chunk_rows.append({**base, **chunk})
                disposition = path_disposition(local_program_rows, file_hashes["source"] == file_hashes["target"])

            classes = Counter(str(row["classification"]) for row in local_program_rows)
            executable_rows = sum(count for key, count in classes.items() if key.startswith("executable_code_delta"))
            interface_rows = sum(count for key, count in classes.items() if "interface_delta" in key)
            metadata_rows = classes["nonexecutive_metadata_or_compiler_delta"]
            path_rows.append({
                **candidate,
                "source_input_size": file_sizes["source"],
                "source_input_sha256": file_hashes["source"],
                "target_input_size": file_sizes["target"],
                "target_input_sha256": file_hashes["target"],
                "source_program_rows": len(source_programs),
                "target_program_rows": len(target_programs),
                "paired_program_rows": len(local_program_rows),
                "executable_code_delta_program_rows": executable_rows,
                "interface_delta_program_rows": interface_rows,
                "metadata_only_program_rows": metadata_rows,
                "program_classifications": ";".join(f"{key}:{value}" for key, value in sorted(classes.items())),
                "path_disposition": disposition,
                "restoration_code_candidate": disposition == "executable_code_delta_interface_stable",
                "runtime_confirmed": False,
                "visual_or_censorship_semantics_confirmed": False,
                "write_authorized": False,
            })
        except (CollectorError, OSError, ValueError, RuntimeError) as exc:
            skipped_rows.append({
                "normalized_path": normalized,
                "classification": candidate.get("classification", ""),
                "extension": candidate.get("extension", ""),
                "reason": str(exc),
            })

    require(len(path_rows) + len(skipped_rows) == EXPECTED_PATHS, "shader queue accounting drift")
    require(not skipped_rows, f"shader sweep has skipped rows: {len(skipped_rows)}")
    require(len(path_rows) == EXPECTED_PATHS, "shader path output count drift")
    by_path = {row["normalized_path"]: row for row in path_rows}
    for water in ("data/x64/shader/cwater.g1s", "data/x64/shader/cwater2.g1s"):
        require(water in by_path, f"missing bounded water shader: {water}")
        require(int(by_path[water]["executable_code_delta_program_rows"]) == 0, f"reviewed cwater executable result drift: {water}")

    family_groups: dict[tuple[str, str], dict[str, Any]] = {}
    for row in path_rows:
        key = (str(row["shader_family"]), str(row["path_disposition"]))
        group = family_groups.setdefault(key, {
            "shader_family": key[0],
            "path_disposition": key[1],
            "path_rows": 0,
            "program_rows": 0,
            "executable_code_delta_program_rows": 0,
            "interface_delta_program_rows": 0,
            "restoration_code_candidate_path_rows": 0,
            "runtime_confirmed_rows": 0,
            "write_authorized_rows": 0,
        })
        group["path_rows"] += 1
        group["program_rows"] += int(row.get("paired_program_rows") or 0)
        group["executable_code_delta_program_rows"] += int(row.get("executable_code_delta_program_rows") or 0)
        group["interface_delta_program_rows"] += int(row.get("interface_delta_program_rows") or 0)
        group["restoration_code_candidate_path_rows"] += bool(row.get("restoration_code_candidate"))

    report_files = {
        "INPUT_HASHES.tsv": (["input_id", "relative_path", "sha256", "verified"], input_hashes),
        "EXTRACTION_INPUTS.tsv": (["side", "archive_relative", "archive_size", "archive_sha256", "gust_pak_sha256", "cache_action"], extraction_rows),
        "SHADER_PATH_CLASSIFICATION.tsv": ([
            "difference_id", "shader_family", "classification", "normalized_path", "extension",
            "source_input_size", "source_input_sha256", "target_input_size", "target_input_sha256",
            "source_program_rows", "target_program_rows", "paired_program_rows",
            "executable_code_delta_program_rows", "interface_delta_program_rows", "metadata_only_program_rows",
            "program_classifications", "path_disposition", "restoration_code_candidate",
            "runtime_confirmed", "visual_or_censorship_semantics_confirmed", "write_authorized",
        ], sorted(path_rows, key=lambda row: row["normalized_path"])),
        "DXBC_PROGRAM_CLASSIFICATION.tsv": ([
            "normalized_path", "shader_family", "source_program_index", "target_program_index",
            "source_stage", "target_stage", "source_shader_model", "target_shader_model",
            "source_program_size", "target_program_size", "source_program_sha256", "target_program_sha256",
            "matching_basis", "classification", "reflection_semantics", "signature_semantics",
            "code_chunks_identical", "source_rdef_status", "target_rdef_status",
            "source_reflection_semantic_sha256", "target_reflection_semantic_sha256",
            "source_signature_semantic_sha256", "target_signature_semantic_sha256",
            "source_creator_sha256", "target_creator_sha256", "runtime_confirmed",
            "visual_or_censorship_semantics_confirmed", "write_authorized",
        ], sorted(program_rows, key=lambda row: (row["normalized_path"], str(row["target_program_index"]), str(row["source_program_index"])))),
        "DXBC_CHUNK_CLASSIFICATION.tsv": ([
            "normalized_path", "source_program_index", "target_program_index", "classification",
            "chunk_key", "fourcc", "source_size", "target_size", "source_sha256", "target_sha256",
            "runtime_confirmed", "visual_or_censorship_semantics_confirmed", "write_authorized",
        ], sorted(chunk_rows, key=lambda row: (row["normalized_path"], str(row["target_program_index"]), row["chunk_key"]))),
        "TARGET_ONLY_SHADER_DEPENDENCIES.tsv": ([
            "normalized_path", "extension", "target_size", "target_sha256", "target_program_rows",
            "dependency_semantics_confirmed", "runtime_confirmed", "write_authorized",
        ], sorted(target_only_rows, key=lambda row: row["normalized_path"])),
        "SHADER_FAMILY_SUMMARY.tsv": ([
            "shader_family", "path_disposition", "path_rows", "program_rows",
            "executable_code_delta_program_rows", "interface_delta_program_rows",
            "restoration_code_candidate_path_rows", "runtime_confirmed_rows", "write_authorized_rows",
        ], sorted(family_groups.values(), key=lambda row: (row["shader_family"], row["path_disposition"]))),
        "SHADER_SCAN_SKIPPED.tsv": (["normalized_path", "classification", "extension", "reason"], skipped_rows),
    }
    for name, (fields, rows) in report_files.items():
        write_tsv(output / name, fields, rows)

    path_dispositions = Counter(str(row["path_disposition"]) for row in path_rows)
    program_classifications = Counter(str(row["classification"]) for row in program_rows)
    executable_candidate_paths = sum(bool(row["restoration_code_candidate"]) for row in path_rows)
    summary = {
        "type": "br_quartet_restoration_shader_namespace_executable_signature_reflection_sweep_evidence_summary",
        "format_version": 1,
        "tool_version": TOOL_VERSION,
        "status": "complete_shader_namespace_dxbc_executable_signature_reflection_sweep_metadata_only_semantics_unresolved_no_write",
        "stage130_report_sha256": STAGE130_SHA256,
        "stage132_report_sha256": STAGE132_SHA256,
        "shader_path_rows": len(path_rows),
        "g1s_path_rows": sum(row["extension"] == ".g1s" for row in path_rows),
        "g1t_path_rows": sum(row["extension"] == ".g1t" for row in path_rows),
        "changed_shader_path_rows": sum(row["classification"] == "changed" for row in path_rows),
        "target_only_shader_path_rows": sum(row["classification"] == "new_in_target" for row in path_rows),
        "generated_variant_path_rows": sum(row["shader_family"] == "generated_variant" for row in path_rows),
        "named_shader_or_texture_path_rows": sum(row["shader_family"] == "named_shader_or_texture" for row in path_rows),
        "dxbc_program_rows": len(program_rows),
        "dxbc_chunk_rows": len(chunk_rows),
        "path_dispositions": dict(sorted(path_dispositions.items())),
        "program_classifications": dict(sorted(program_classifications.items())),
        "executable_code_delta_program_rows": sum(key.startswith("executable_code_delta") and count or 0 for key, count in program_classifications.items()),
        "interface_stable_executable_candidate_path_rows": executable_candidate_paths,
        "target_only_dependency_rows": len(target_only_rows),
        "water_shader_executable_code_delta_rows": sum(
            int(by_path[path]["executable_code_delta_program_rows"])
            for path in ("data/x64/shader/cwater.g1s", "data/x64/shader/cwater2.g1s")
        ),
        "payload_bytes_read": payload_bytes_read,
        "skipped_rows": len(skipped_rows),
        "runtime_confirmed_rows": 0,
        "visual_or_censorship_semantics_confirmed_rows": 0,
        "write_authorized_rows": 0,
        "policy": {
            "local_proprietary_payloads_read": True,
            "proprietary_payloads_in_report": False,
            "installed_game_modified": False,
            "pak_built_or_repacked": False,
            "shader_or_texture_payload_written": False,
            "profile_or_registry_modified": False,
            "core_modified": False,
            "translation_modified": False,
            "legacy_dlc_modified": False,
            "git_modified": False,
            "save_or_runtime_required": False,
            "compiler_or_reflection_metadata_treated_as_executable_code": False,
            "shader_name_or_keyword_treated_as_visual_semantics": False,
            "restoration_prototype_authorized": False,
        },
        "next_action": (
            "Use the complete 214-path classification to separate broad compiler/envelope churn from bounded "
            "interface-stable executable-code deltas. Audit those bounded paths by family and scene dependency "
            "before any prototype. Then perform the six-effect-archive and one-posteffect-archive namespace sweeps. "
            "Do not require saves or build Canary-all."
        ),
    }
    atomic_json(output / "SUMMARY.json", summary)

    for path in output.rglob("*"):
        if path.is_file():
            lower = path.name.casefold()
            require(not any(lower.endswith(ext) for ext in FORBIDDEN_EXTENSIONS), f"forbidden payload in report: {path}")
    output_archive: Path | None = None
    if create_archive:
        make_archive(output, archive)
        output_archive = archive
    return output_archive, summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", required=True)
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
    print(json.dumps(summary, indent=2, sort_keys=True))
    if archive is not None:
        print(f"[shader-namespace-sweep] report archive: {archive}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except CollectorError as exc:
        print(f"[shader-namespace-sweep] ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
