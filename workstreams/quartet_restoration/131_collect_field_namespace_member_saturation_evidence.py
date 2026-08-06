#!/usr/bin/env python3
"""Read-only member saturation sweep for all 105 BR1 field scene roots.

Stage 131 consumes the exact stage-130 metadata report and the local Original /
Quartet field asset archives.  It records metadata for every paired field EARC
member and the three source-only G1PF files.  Payload bytes are never copied to
evidence, no visual/censorship semantics are inferred and no write is authorized.
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
TOOL_VERSION = "0.1.49"
REPORT_DIR = "field_namespace_member_saturation_evidence"
REPORT_NAME = "BR_quartet_restoration_field_namespace_member_saturation_evidence.tar.zst"
STAGE130_ARCHIVE = "BR_quartet_restoration_non_character_namespace_saturation_audit_evidence.tar.zst"
STAGE130_ROOT = "non_character_namespace_saturation_audit"
STAGE130_SHA256 = "de8b339921387dfa8858415110166120f49ceddcf63ea148883fcf41d214d69c"
STAGE130_SUMMARY_SHA256 = "3b1293b422d19a9ab87a22d00b46755ca7e23d48b6d46ea1795ac0435080decd"
ASSET_DIFF_REL = ".local/reports/quartet_restoration/differences/br1_assets.json"
ASSET_DIFF_SHA256 = "a948bf404dc439234519611b98a96b781a5e4f6ed24cf00104fd41ee7dc07456"
EXPECTED_FIELD_PATHS = 318
EXPECTED_FIELD_ROOTS = 105
EXPECTED_PAIRED_EARC = 312
EXPECTED_SOURCE_ONLY_EARC = 3
EXPECTED_PAIRED_G1PF = 3
MAX_EARC_BYTES = 1024 * 1024 * 1024
FORBIDDEN_EXTENSIONS = (".pak", ".g1m", ".g1e", ".g1em", ".elixir", ".ebm", ".ebd", ".g1pf")


class CollectorError(RuntimeError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise CollectorError(message)


def progress(message: str) -> None:
    print(f"[field-member-saturation] {message}", file=sys.stderr, flush=True)


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
        return [dict(row) for row in csv.DictReader(handle, delimiter="\t")]


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


def extract_stage130(archive: Path, destination: Path) -> Path:
    require(archive.is_file(), f"missing stage-130 report: {archive}")
    actual = sha256_file(archive)
    require(actual == STAGE130_SHA256, f"unexpected stage-130 report SHA-256: {actual}")
    listed = subprocess.run(["tar", "--zstd", "-tf", str(archive)], text=True, capture_output=True)
    require(listed.returncode == 0, listed.stderr.strip() or "cannot list stage-130 report")
    names = [safe_relative(line.strip(), "archive member") for line in listed.stdout.splitlines() if line.strip()]
    require(names and {PurePosixPath(name).parts[0] for name in names} == {STAGE130_ROOT}, "unexpected stage-130 archive root")
    destination.mkdir(parents=True, exist_ok=True)
    completed = subprocess.run(["tar", "--zstd", "-xf", str(archive), "-C", str(destination)], text=True, capture_output=True)
    require(completed.returncode == 0, completed.stderr.strip() or "cannot extract stage-130 report")
    root = destination / STAGE130_ROOT
    summary = root / "SUMMARY.json"
    require(summary.is_file(), "stage-130 SUMMARY.json missing")
    actual_summary = sha256_file(summary)
    require(actual_summary == STAGE130_SUMMARY_SHA256, f"unexpected stage-130 SUMMARY SHA-256: {actual_summary}")
    return root


def load_br_tool(project_root: Path):
    path = project_root / "Blue_Reflection_Text_Tool/br_restoration_tool.py"
    require(path.is_file(), f"missing restoration tool: {path}")
    spec = importlib.util.spec_from_file_location("stage131_br_restoration_tool", path)
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
    candidates.append(project_root / ".local/vendor/gust_tools/gust_pak")
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


def field_root(path: str) -> str:
    parts = PurePosixPath(path).parts
    require(len(parts) >= 5 and parts[:3] == ("data", "x64", "field"), f"not a field path: {path}")
    return parts[3]


def archive_role(path: str) -> str:
    name = PurePosixPath(path).name.casefold()
    if name.endswith("_env.elixir.gz"):
        return "environment"
    if name.endswith("_obj.elixir.gz"):
        return "objects"
    if name.endswith(".elixir.gz"):
        return "primary"
    if name.endswith(".g1pf"):
        return "removed_g1pf"
    return "other"


def normalized_member_role(name: str, root: str) -> str:
    value = name.casefold().replace("\\", "/")
    value = value.replace(root.casefold(), "{field_root}")
    value = re.sub(r"s\d{2}_[a-z]_[a-z0-9_]+", "{field_root}", value)
    return value


def ensure_field_cache(*, project_root: Path, workspace_root: Path, inventories: Mapping[tuple[str, str], tuple[str, dict[str, Any]]], candidates: Sequence[Mapping[str, str]], original_root: Path | None, quartet_root: Path | None, gust_pak_path: Path | None, br: Any, timeout_seconds: int) -> list[dict[str, Any]]:
    required: dict[str, list[str]] = {"source": [], "target": []}
    for row in candidates:
        normalized = row["normalized_path"].casefold()
        required["source"].append(normalized)
        if row["classification"] == "changed":
            required["target"].append(normalized)
    missing: dict[str, list[str]] = defaultdict(list)
    for side, paths in required.items():
        for normalized in paths:
            key = (side, normalized)
            require(key in inventories, f"missing inventory entry: {key}")
            pair_id, entry = inventories[key]
            local = br.inventory_workspace_file(workspace_root, side, pair_id, str(entry["archive"]), str(entry["path"]))
            if not local.is_file():
                missing[side].append(normalized)
    if not missing:
        return [
            {"side": "source", "archive_relative": "DATA/PACK00_03.PAK", "cache_action": "reused_existing_workspace"},
            {"side": "target", "archive_relative": "Data/PACK10_03.PAK", "cache_action": "reused_existing_workspace"},
        ]
    require(original_root is not None and quartet_root is not None, "required field workspace files are missing; provide --original-root and --quartet-root")
    gust = find_gust_pak(project_root, gust_pak_path)
    gust_sha = sha256_file(gust)
    side_specs = {"source": (original_root, "DATA/PACK00_03.PAK"), "target": (quartet_root, "Data/PACK10_03.PAK")}
    rows: list[dict[str, Any]] = []
    for side in sorted(missing):
        game_root, relative = side_specs[side]
        archive = resolve_game_archive(game_root, relative)
        progress(f"extracting read-only input {relative} for {len(missing[side])} field paths")
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


def build_report(project_root: Path, *, report_root: Path | None = None, output_report_root: Path | None = None, workspace_root: Path | None = None, original_root: Path | None = None, quartet_root: Path | None = None, gust_pak_path: Path | None = None, create_archive: bool = True, timeout_seconds: int = 3600, verify_payload_hashes: bool = True) -> tuple[Path | None, dict[str, Any]]:
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

    asset_diff = project_root / ASSET_DIFF_REL
    require(asset_diff.is_file(), f"missing asset difference report: {asset_diff}")
    require(sha256_file(asset_diff) == ASSET_DIFF_SHA256, "asset difference report SHA-256 drift")
    br = load_br_tool(project_root)
    inventories = load_asset_inventories(project_root)

    with tempfile.TemporaryDirectory(prefix="stage131-prereq-") as td:
        stage130 = extract_stage130(report_root / STAGE130_ARCHIVE, Path(td))
        stage130_summary = json.loads((stage130 / "SUMMARY.json").read_text(encoding="utf-8"))
        require(stage130_summary.get("field_nonidentical_path_rows") == EXPECTED_FIELD_PATHS, "stage-130 field path count drift")
        require(stage130_summary.get("field_scene_root_rows") == EXPECTED_FIELD_ROOTS, "stage-130 field root count drift")
        all_candidates = read_tsv(stage130 / "NON_CHARACTER_TECHNICAL_CANDIDATES.tsv")
        candidates = sorted((row for row in all_candidates if row["namespace"] == "field"), key=lambda row: row["normalized_path"])
        roots130 = read_tsv(stage130 / "FIELD_SCENE_ROOT_SUMMARY.tsv")
        require(len(candidates) == EXPECTED_FIELD_PATHS, f"expected {EXPECTED_FIELD_PATHS} field candidates, found {len(candidates)}")
        require(len(roots130) == EXPECTED_FIELD_ROOTS, f"expected {EXPECTED_FIELD_ROOTS} field roots, found {len(roots130)}")
        require(sum(row["classification"] == "changed" and row["extension"] == ".elixir.gz" for row in candidates) == EXPECTED_PAIRED_EARC, "paired EARC count drift")
        require(sum(row["classification"] == "removed_in_target" and row["extension"] == ".elixir.gz" for row in candidates) == EXPECTED_SOURCE_ONLY_EARC, "source-only EARC count drift")
        require(sum(row["classification"] == "changed" and row["extension"] == ".g1pf" for row in candidates) == EXPECTED_PAIRED_G1PF, "paired G1PF count drift")

        extraction_rows = ensure_field_cache(
            project_root=project_root, workspace_root=workspace_root, inventories=inventories, candidates=candidates,
            original_root=original_root, quartet_root=quartet_root, gust_pak_path=gust_pak_path,
            br=br, timeout_seconds=timeout_seconds,
        )

        input_rows: list[dict[str, Any]] = []
        archive_summaries: list[dict[str, Any]] = []
        member_rows: list[dict[str, Any]] = []
        root_acc: dict[str, Counter[str]] = defaultdict(Counter)
        shape_groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
        role_groups: dict[tuple[str, str, str, int], list[dict[str, Any]]] = defaultdict(list)
        decoded_bytes_total = 0

        for index, candidate in enumerate(candidates, 1):
            normalized = candidate["normalized_path"]
            root = field_root(normalized)
            role = archive_role(normalized)
            classification = candidate["classification"]
            is_earc = normalized.casefold().endswith(".elixir.gz")
            progress(f"field path {index}/{len(candidates)} {normalized}")
            parsed: dict[str, dict[str, Any]] = {}
            input_files: dict[str, tuple[Path, dict[str, Any], str]] = {}
            for side in ("source", "target"):
                if side == "target" and classification == "removed_in_target":
                    continue
                pair_id, entry = inventories[(side, normalized.casefold())]
                local = br.inventory_workspace_file(workspace_root, side, pair_id, str(entry["archive"]), str(entry["path"]))
                require(local.is_file(), f"missing extracted input: {side} {normalized}: {local}")
                actual_sha = sha256_file(local)
                if verify_payload_hashes:
                    require(actual_sha == str(entry["sha256"]), f"payload hash drift: {side} {normalized}: {actual_sha}")
                input_files[side] = (local, entry, actual_sha)
                row = {
                    "field_scene_root": root, "archive_role": role, "normalized_path": normalized,
                    "classification": classification, "side": side, "container_archive": entry["archive"],
                    "input_size": local.stat().st_size, "input_sha256": actual_sha,
                    "payload_in_evidence": False, "write_authorized": False,
                }
                if is_earc:
                    item = br.read_earc_archive(local, maximum_bytes=MAX_EARC_BYTES, include_member_payloads=False)
                    parsed[side] = item
                    decoded_bytes_total += int(item["decoded_bytes"])
                    row.update({
                        "container": item["container"], "decoded_bytes": item["decoded_bytes"],
                        "decoded_sha256": item["decoded_sha256"], "member_count": item["file_count"],
                    })
                else:
                    row.update({"container": "paired_g1pf_file_level", "decoded_bytes": "", "decoded_sha256": "", "member_count": ""})
                input_rows.append(row)

            if not is_earc:
                source_local, _, source_sha = input_files["source"]
                target_local, _, target_sha = input_files["target"]
                root_acc[root].update({"archive_path_rows": 1, "paired_g1pf_rows": 1, "file_level_only_rows": 1})
                archive_summaries.append({
                    "field_scene_root": root, "archive_role": role, "normalized_path": normalized,
                    "classification": classification, "source_member_rows": "", "target_member_rows": "",
                    "identical_member_rows": 0, "changed_member_rows": 0, "added_member_rows": 0,
                    "removed_member_rows": 0, "nonidentical_member_rows": 0,
                    "delta_shape_id": hashlib.sha256(f"g1pf|{source_local.stat().st_size}|{target_local.stat().st_size}|{source_sha}|{target_sha}".encode()).hexdigest(),
                    "exact_member_audit_complete": False, "file_level_audit_complete": True,
                    "visual_or_censorship_semantics_confirmed": False, "write_authorized": False,
                })
                continue

            source_by = {str(m["comparison_key"]): m for m in parsed["source"]["members"]}
            target_by = {str(m["comparison_key"]): m for m in parsed.get("target", {}).get("members", [])}
            current_rows: list[dict[str, Any]] = []
            counts = Counter()
            for key in sorted(set(source_by) | set(target_by), key=str.casefold):
                left, right = source_by.get(key), target_by.get(key)
                if left and right:
                    member_class = "identical" if left["sha256"] == right["sha256"] else "changed"
                elif left:
                    member_class = "removed_in_target"
                else:
                    member_class = "added_in_target"
                counts[member_class] += 1
                chosen = right or left
                source_size = int((left or {}).get("size", 0))
                target_size = int((right or {}).get("size", 0))
                member_name = str(chosen.get("name", key))
                row = {
                    "field_scene_root": root, "archive_role": role, "normalized_path": normalized,
                    "member_key": key, "normalized_member_role": normalized_member_role(member_name, root),
                    "classification": member_class,
                    "source_member_name": (left or {}).get("name", ""), "target_member_name": (right or {}).get("name", ""),
                    "source_member_index": (left or {}).get("index", ""), "target_member_index": (right or {}).get("index", ""),
                    "source_size": source_size if left else "", "target_size": target_size if right else "",
                    "size_delta": target_size - source_size,
                    "source_sha256": (left or {}).get("sha256", ""), "target_sha256": (right or {}).get("sha256", ""),
                    "member_extension": PurePosixPath(member_name).suffix.casefold() or "(none)",
                    "payload_in_evidence": False, "visual_or_censorship_semantics_confirmed": False,
                    "runtime_confirmed": False, "write_authorized": False,
                }
                member_rows.append(row)
                current_rows.append(row)
                if member_class != "identical":
                    role_groups[(row["normalized_member_role"], row["member_extension"], member_class, row["size_delta"])].append(row)
            nonidentical = len(current_rows) - counts["identical"]
            signature_lines = [
                "|".join([r["normalized_member_role"], r["classification"], str(r["size_delta"]), r["member_extension"]])
                for r in current_rows if r["classification"] != "identical"
            ]
            shape_id = hashlib.sha256("\n".join(sorted(signature_lines)).encode("utf-8")).hexdigest()
            summary_row = {
                "field_scene_root": root, "archive_role": role, "normalized_path": normalized,
                "classification": classification,
                "source_member_rows": len(source_by), "target_member_rows": len(target_by),
                "identical_member_rows": counts["identical"], "changed_member_rows": counts["changed"],
                "added_member_rows": counts["added_in_target"], "removed_member_rows": counts["removed_in_target"],
                "nonidentical_member_rows": nonidentical, "delta_shape_id": shape_id,
                "exact_member_audit_complete": True, "file_level_audit_complete": True,
                "visual_or_censorship_semantics_confirmed": False, "write_authorized": False,
            }
            archive_summaries.append(summary_row)
            shape_groups[shape_id].append(summary_row)
            root_acc[root].update({
                "archive_path_rows": 1,
                "paired_earc_rows": 1 if classification == "changed" else 0,
                "source_only_earc_rows": 1 if classification == "removed_in_target" else 0,
                "member_rows": len(current_rows),
                "identical_member_rows": counts["identical"], "changed_member_rows": counts["changed"],
                "added_member_rows": counts["added_in_target"], "removed_member_rows": counts["removed_in_target"],
                "nonidentical_member_rows": nonidentical,
            })

        root_meta = {row["field_scene_root"]: row for row in roots130}
        root_rows = []
        for root in sorted(root_meta):
            count = root_acc[root]
            root_rows.append({
                "field_scene_root": root, "archive_path_rows": count["archive_path_rows"],
                "paired_earc_rows": count["paired_earc_rows"], "source_only_earc_rows": count["source_only_earc_rows"],
                "paired_g1pf_rows": count["paired_g1pf_rows"], "file_level_only_rows": count["file_level_only_rows"],
                "member_rows": count["member_rows"], "identical_member_rows": count["identical_member_rows"],
                "changed_member_rows": count["changed_member_rows"], "added_member_rows": count["added_member_rows"],
                "removed_member_rows": count["removed_member_rows"], "nonidentical_member_rows": count["nonidentical_member_rows"],
                "lexical_signal_tokens": root_meta[root]["lexical_signal_tokens"],
                "lexical_signal_only_not_semantics": True,
                "field_path_saturation_complete": count["archive_path_rows"] == int(root_meta[root]["path_rows"]),
                "earc_member_saturation_complete": count["paired_earc_rows"] + count["source_only_earc_rows"] == sum(1 for row in candidates if field_root(row["normalized_path"]) == root and row["extension"] == ".elixir.gz"),
                "visual_or_censorship_semantics_confirmed": False, "runtime_confirmed": False, "write_authorized": False,
            })

        shape_rows = []
        for shape_id, rows in sorted(shape_groups.items(), key=lambda item: (-len(item[1]), item[0])):
            shape_rows.append({
                "delta_shape_id": shape_id, "archive_rows": len(rows),
                "field_scene_root_rows": len({row["field_scene_root"] for row in rows}),
                "archive_roles": ",".join(sorted({row["archive_role"] for row in rows})),
                "normalized_paths": ",".join(sorted(row["normalized_path"] for row in rows)),
                "recurrent_shape": len(rows) > 1, "semantic_classification": "unassigned", "write_authorized": False,
            })

        role_rows = []
        for (normalized_role, ext, classification, size_delta), rows in sorted(role_groups.items(), key=lambda item: (-len(item[1]), item[0])):
            role_rows.append({
                "normalized_member_role": normalized_role, "member_extension": ext,
                "classification": classification, "size_delta": size_delta,
                "member_rows": len(rows), "field_scene_root_rows": len({row["field_scene_root"] for row in rows}),
                "archive_rows": len({row["normalized_path"] for row in rows}),
                "recurrent_role_family": len(rows) > 1, "semantic_classification": "unassigned", "write_authorized": False,
            })

        queue_rows = sorted(root_rows, key=lambda row: (-int(row["nonidentical_member_rows"]), row["field_scene_root"]))
        for priority, row in enumerate(queue_rows, 1):
            row["priority"] = priority
            row["safe_next_discovery"] = "classify recurrent member roles and format-specific deltas; do not infer visual meaning from root names"

        write_tsv(output / "FIELD_ARCHIVE_INPUTS.tsv", [
            "field_scene_root", "archive_role", "normalized_path", "classification", "side", "container_archive",
            "input_size", "input_sha256", "container", "decoded_bytes", "decoded_sha256", "member_count",
            "payload_in_evidence", "write_authorized",
        ], input_rows)
        write_tsv(output / "FIELD_ARCHIVE_SUMMARY.tsv", [
            "field_scene_root", "archive_role", "normalized_path", "classification", "source_member_rows", "target_member_rows",
            "identical_member_rows", "changed_member_rows", "added_member_rows", "removed_member_rows", "nonidentical_member_rows",
            "delta_shape_id", "exact_member_audit_complete", "file_level_audit_complete", "visual_or_censorship_semantics_confirmed", "write_authorized",
        ], archive_summaries)
        write_tsv(output / "FIELD_ARCHIVE_MEMBER_DELTAS.tsv", [
            "field_scene_root", "archive_role", "normalized_path", "member_key", "normalized_member_role", "classification",
            "source_member_name", "target_member_name", "source_member_index", "target_member_index", "source_size", "target_size",
            "size_delta", "source_sha256", "target_sha256", "member_extension", "payload_in_evidence",
            "visual_or_censorship_semantics_confirmed", "runtime_confirmed", "write_authorized",
        ], member_rows)
        write_tsv(output / "FIELD_SCENE_ROOT_MEMBER_SUMMARY.tsv", [
            "priority", "field_scene_root", "archive_path_rows", "paired_earc_rows", "source_only_earc_rows", "paired_g1pf_rows", "file_level_only_rows", "member_rows",
            "identical_member_rows", "changed_member_rows", "added_member_rows", "removed_member_rows", "nonidentical_member_rows",
            "lexical_signal_tokens", "lexical_signal_only_not_semantics", "field_path_saturation_complete", "earc_member_saturation_complete",
            "visual_or_censorship_semantics_confirmed", "runtime_confirmed", "write_authorized", "safe_next_discovery",
        ], queue_rows)
        write_tsv(output / "FIELD_ARCHIVE_DELTA_SHAPE_GROUPS.tsv", [
            "delta_shape_id", "archive_rows", "field_scene_root_rows", "archive_roles", "normalized_paths",
            "recurrent_shape", "semantic_classification", "write_authorized",
        ], shape_rows)
        write_tsv(output / "FIELD_MEMBER_ROLE_FAMILIES.tsv", [
            "normalized_member_role", "member_extension", "classification", "size_delta", "member_rows",
            "field_scene_root_rows", "archive_rows", "recurrent_role_family", "semantic_classification", "write_authorized",
        ], role_rows)
        write_tsv(output / "EXTRACTION_INPUTS.tsv", [
            "side", "archive_relative", "archive_size", "archive_sha256", "gust_pak_sha256", "cache_action",
        ], extraction_rows)
        write_tsv(output / "INPUT_HASHES.tsv", ["input_id", "relative_path", "sha256", "verified"], [
            {"input_id": "stage130", "relative_path": STAGE130_ARCHIVE, "sha256": STAGE130_SHA256, "verified": True},
            {"input_id": "stage130_summary", "relative_path": f"{STAGE130_ROOT}/SUMMARY.json", "sha256": STAGE130_SUMMARY_SHA256, "verified": True},
            {"input_id": "br1_assets", "relative_path": ASSET_DIFF_REL, "sha256": ASSET_DIFF_SHA256, "verified": True},
        ])

        summary = {
            "type": "br_quartet_restoration_field_namespace_member_saturation_evidence_summary",
            "format_version": 1,
            "tool_version": version,
            "status": "all_105_field_scene_roots_member_saturated_metadata_only_semantics_unresolved_no_write",
            "stage130_report_sha256": STAGE130_SHA256,
            "stage130_summary_sha256": STAGE130_SUMMARY_SHA256,
            "field_candidate_path_rows": len(candidates),
            "field_scene_root_rows": len(root_rows),
            "paired_earc_path_rows": sum(row["classification"] == "changed" and row["extension"] == ".elixir.gz" for row in candidates),
            "source_only_earc_path_rows": sum(row["classification"] == "removed_in_target" and row["extension"] == ".elixir.gz" for row in candidates),
            "paired_g1pf_path_rows": sum(row["classification"] == "changed" and row["extension"] == ".g1pf" for row in candidates),
            "archive_input_side_rows": len(input_rows),
            "exact_member_audited_earc_rows": sum(bool(row["exact_member_audit_complete"]) for row in archive_summaries),
            "file_level_only_path_rows": sum(not bool(row["exact_member_audit_complete"]) for row in archive_summaries),
            "exact_member_ledger_rows": len(member_rows),
            "identical_member_rows": sum(row["classification"] == "identical" for row in member_rows),
            "changed_member_rows": sum(row["classification"] == "changed" for row in member_rows),
            "added_member_rows": sum(row["classification"] == "added_in_target" for row in member_rows),
            "removed_member_rows": sum(row["classification"] == "removed_in_target" for row in member_rows),
            "nonidentical_member_rows": sum(row["classification"] != "identical" for row in member_rows),
            "archive_delta_shape_rows": len(shape_rows),
            "recurrent_archive_delta_shape_rows": sum(bool(row["recurrent_shape"]) for row in shape_rows),
            "member_role_family_rows": len(role_rows),
            "recurrent_member_role_family_rows": sum(bool(row["recurrent_role_family"]) for row in role_rows),
            "decoded_bytes_read": decoded_bytes_total,
            "all_field_paths_saturated": all(bool(row["field_path_saturation_complete"]) for row in root_rows),
            "all_field_earc_members_saturated": all(bool(row["earc_member_saturation_complete"]) for row in root_rows),
            "runtime_confirmed_rows": 0,
            "visual_or_censorship_semantics_confirmed_rows": 0,
            "write_authorized_rows": 0,
            "policy": {
                "local_proprietary_payloads_read": True,
                "proprietary_payloads_in_report": False,
                "installed_game_modified": False,
                "pak_built_or_repacked": False,
                "profile_or_registry_modified": False,
                "core_modified": False,
                "translation_modified": False,
                "legacy_dlc_modified": False,
                "git_modified": False,
                "runtime_or_save_required": False,
                "field_root_names_treated_as_visual_semantics": False,
            },
            "next_action": "Classify recurrent field member-role and format families, then run the separate 214-path shader executable/signature/reflection sweep. Do not require saves or build Canary-all.",
        }
        atomic_json(output / "SUMMARY.json", summary)

    report_archive: Path | None = None
    if create_archive:
        make_archive(output, archive)
        report_archive = archive
    return report_archive, summary


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path, default=PROJECT_ROOT_DEFAULT)
    parser.add_argument("--report-root", type=Path)
    parser.add_argument("--output-report-root", type=Path)
    parser.add_argument("--workspace-root", type=Path)
    parser.add_argument("--original-root", type=Path)
    parser.add_argument("--quartet-root", type=Path)
    parser.add_argument("--gust-pak", type=Path)
    parser.add_argument("--timeout-seconds", type=int, default=3600)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        archive, summary = build_report(
            args.project_root, report_root=args.report_root, output_report_root=args.output_report_root,
            workspace_root=args.workspace_root, original_root=args.original_root, quartet_root=args.quartet_root,
            gust_pak_path=args.gust_pak, timeout_seconds=args.timeout_seconds,
        )
    except CollectorError as exc:
        print(f"[field-member-saturation] ERROR: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(summary, indent=2, sort_keys=True))
    if archive:
        print(f"[field-member-saturation] report archive: {archive}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
