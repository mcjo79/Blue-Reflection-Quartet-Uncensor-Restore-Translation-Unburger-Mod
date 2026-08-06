#!/usr/bin/env python3
"""Stage 154: read-only Hinako wet-school shader-schema/material-usage audit.

Stage 153 proved that all ten Original wet material texture fingerprints are
present in Quartet wet, including source material 3 relocated to target material
4, but it found no geometry-safe submesh remap and no exact whole shader-block
fingerprint match.  This stage therefore keeps the preserved material mapping
and compares *shader block schemas* independently of their values, scoped by
actual submesh use of each mapped wet material.  It then compares individual
parameter values and, when a unique dry schema control exists on both sides,
classifies exact dry->wet transitions.

No payload is modified.  Any scalar candidate is metadata-only and remains
write_authorized=false until a later explicit, separately reviewed probe.
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
from collections import defaultdict
from pathlib import Path, PurePosixPath
from typing import Any, Iterable, Mapping, Sequence

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT_DEFAULT = SCRIPT_DIR.parent.parent
TOOL_VERSION = "0.1.72"
REPORT_DIR = "hinako_wet_school_shader_schema_material_usage_evidence"
REPORT_NAME = "BR_quartet_restoration_hinako_wet_school_shader_schema_material_usage_evidence.tar.zst"
WORKSPACE_SUBDIR = Path("wet_school_shader_schema_material_usage")

CHARACTER_ID = "pc00"
DRY_STATE = "scl"
WET_STATE = "scl_w"
DRY_ARCHIVE = "data/x64/character/pc00/pc00_scl.elixir.gz"
WET_ARCHIVE = "data/x64/character/pc00/pc00_scl_w.elixir.gz"
TARGET_ROLE = "{pc}_{state}_default.g1m"
MAX_EARC_BYTES = 128 * 1024 * 1024

STAGE153_REPORT = "BR_quartet_restoration_hinako_wet_school_material_submesh_remap_evidence.tar.zst"
STAGE153_SHA256 = "301bc4b6137dd9a6af756185ab4727ad6f09ef19eb97c6f5583f0ac60dd2e877"
STAGE153_ROOT = "hinako_wet_school_material_submesh_remap_evidence"
STAGE152_SHA256 = "a96c875a5d47c0f3ecf2721c634723b245556438f8a0ad5597de212f426b3e6a"
STAGE151_SHA256 = "68bb8760691bb01833af87c7ff6ed5c05868e360b1a4a6363bb9a8c187c5f1b9"

FOCUS_SOURCE_MATERIAL_INDEX = 3
FOCUS_TARGET_MATERIAL_INDEX = 4
FOCUS_TEXTURE_TRIPLET = ("21:29:0", "23:3:0", "27:57:57")

FORBIDDEN_REPORT_EXTENSIONS = (
    ".pak", ".g1m", ".g1t", ".g1s", ".g1e", ".g1em", ".elixir", ".elixir.gz", ".ebd", ".ebm", ".kps"
)


class WetSchoolShaderSchemaError(RuntimeError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise WetSchoolShaderSchemaError(message)


def progress(message: str) -> None:
    print(f"[stage154] {message}", flush=True)


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(8 * 1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def safe_relative(value: str, label: str) -> str:
    p = PurePosixPath(str(value).replace("\\", "/"))
    require(p.parts and not p.is_absolute() and ".." not in p.parts, f"unsafe {label}: {value}")
    return p.as_posix()


def load_module(path: Path, name: str) -> Any:
    require(path.is_file(), f"missing module: {path}")
    spec = importlib.util.spec_from_file_location(name, path)
    require(spec is not None and spec.loader is not None, f"cannot load module: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def write_tsv(path: Path, fields: Sequence[str], rows: Iterable[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(fields), delimiter="\t", lineterminator="\n", extrasaction="ignore")
        w.writeheader()
        for row in rows:
            w.writerow({field: row.get(field, "") for field in fields})


def make_archive(source: Path, output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    tmp = output.with_name(output.name + ".tmp")
    tmp.unlink(missing_ok=True)
    cp = subprocess.run(["tar", "--zstd", "-cf", str(tmp), "-C", str(source.parent), source.name], text=True, capture_output=True)
    require(cp.returncode == 0, cp.stderr.strip() or "report archive creation failed")
    os.replace(tmp, output)


def extract_report(archive: Path, expected_sha256: str, expected_root: str, destination: Path) -> Path:
    require(archive.is_file(), f"missing prerequisite report: {archive}")
    actual = sha256_file(archive)
    require(actual == expected_sha256, f"stage-153 evidence SHA-256 drift: {actual}")
    cp = subprocess.run(["tar", "--zstd", "-tf", str(archive)], text=True, capture_output=True)
    require(cp.returncode == 0, cp.stderr.strip() or "cannot list stage-153 evidence")
    names = [safe_relative(x.strip(), "stage-153 member") for x in cp.stdout.splitlines() if x.strip()]
    require(names and {PurePosixPath(x).parts[0] for x in names} == {expected_root}, "unexpected stage-153 archive root")
    require(not any(x.casefold().endswith(FORBIDDEN_REPORT_EXTENSIONS) for x in names), "proprietary payload in stage-153 evidence")
    destination.mkdir(parents=True, exist_ok=True)
    cp = subprocess.run(["tar", "--zstd", "-xf", str(archive), "-C", str(destination)], text=True, capture_output=True)
    require(cp.returncode == 0, cp.stderr.strip() or "cannot extract stage-153 evidence")
    return destination / expected_root


def validate_stage153(report_root: Path) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="stage154-prereq-") as td:
        root = extract_report(report_root / STAGE153_REPORT, STAGE153_SHA256, STAGE153_ROOT, Path(td))
        summary = json.loads((root / "SUMMARY.json").read_text(encoding="utf-8"))
        require(summary.get("tool_version") == "0.1.71", "stage-153 version drift")
        require(summary.get("stage151_evidence_sha256") == STAGE151_SHA256, "stage-151 chain drift")
        require(summary.get("stage152_evidence_sha256") == STAGE152_SHA256, "stage-152 chain drift")
        require(summary.get("bounded_binding_candidate_rows") == 0, "stage-153 unexpectedly has binding candidates")
        require(summary.get("strong_geometry_mapped_submesh_rows") == 0, "stage-153 geometry mapping result drift")
        require(summary.get("unique_cross_game_material_fingerprint_rows") == 10, "stage-153 material preservation count drift")
        require(summary.get("unique_cross_game_shader_fingerprint_rows") == 0, "stage-153 whole shader fingerprint result drift")
        require(summary.get("source_wet_material3_preserved_in_target_wet_indices") == [4], "stage-153 focus material mapping drift")
        require(tuple(summary.get("source_wet_material3_texture_triplet", [])) == FOCUS_TEXTURE_TRIPLET, "stage-153 texture triplet drift")
        require(summary.get("runtime_validated") is False and summary.get("production_eligible") is False, "stage-153 promotion drift")
        policy = summary.get("policy", {})
        require(policy.get("binding_write_authorized") is False, "stage-153 binding write unexpectedly authorized")
        require(policy.get("whole_g1mm_transplant_reuse_forbidden") is True, "failed whole-G1MM guard missing")
        return summary


def _canon(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def group_materials(parsed: Mapping[str, Any]) -> dict[int, dict[str, Any]]:
    grouped: dict[int, list[Mapping[str, Any]]] = defaultdict(list)
    for row in parsed.get("materials", []):
        grouped[int(row["material_index"])].append(row)
    out: dict[int, dict[str, Any]] = {}
    for idx, rows in grouped.items():
        rows = sorted(rows, key=lambda r: int(r["texture_slot"]))
        textures = [
            {
                "slot": int(r["texture_slot"]), "texture_id": int(r["texture_id"]), "layer": int(r["layer"]),
                "texture_type": int(r["texture_type"]), "subtype": int(r["subtype"]),
                "tilemodex": int(r["tilemodex"]), "tilemodey": int(r["tilemodey"]),
            }
            for r in rows
        ]
        out[idx] = {
            "material_index": idx,
            "texture_count": len(textures),
            "texture_fingerprint": sha256_text(_canon(textures)),
            "textures": textures,
        }
    return out


def shader_blocks(parsed: Mapping[str, Any]) -> dict[int, dict[str, Any]]:
    grouped: dict[int, list[Mapping[str, Any]]] = defaultdict(list)
    for row in parsed.get("shader_params", []):
        grouped[int(row["shader_block_index"])].append(row)
    out: dict[int, dict[str, Any]] = {}
    for idx, rows in grouped.items():
        ordered = sorted(rows, key=lambda r: (int(r["parameter_index"]), str(r["parameter_name_folded"]), int(r["parameter_occurrence"])))
        schema_items = [
            {
                "name": str(r["parameter_name_folded"]),
                "occurrence": int(r["parameter_occurrence"]),
                "buffer_type": int(r["buffer_type"]),
                "buffer_count": int(r["buffer_count"]),
            }
            for r in ordered
        ]
        value_items = [dict(schema_items[i], value_hex=str(r["value_hex"])) for i, r in enumerate(ordered)]
        key_rows = {
            (str(r["parameter_name_folded"]), int(r["parameter_occurrence"]), int(r["buffer_type"]), int(r["buffer_count"])): r
            for r in ordered
        }
        require(len(key_rows) == len(ordered), f"duplicate parameter key in shader block {idx}")
        out[idx] = {
            "shader_block_index": idx,
            "parameter_count": len(ordered),
            "schema_fingerprint": sha256_text(_canon(schema_items)),
            "value_fingerprint": sha256_text(_canon(value_items)),
            "rows": key_rows,
        }
    return out


def usage_by_material(parsed: Mapping[str, Any]) -> dict[int, dict[str, Any]]:
    out: dict[int, dict[str, Any]] = defaultdict(lambda: {"submesh_indices": [], "shader_indices": [], "record_offsets": []})
    for row in parsed.get("submeshes", []):
        midx = int(row["materialIndex"])
        out[midx]["submesh_indices"].append(int(row["submesh_index"]))
        out[midx]["shader_indices"].append(int(row["shaderParamIndex"]))
        out[midx]["record_offsets"].append(int(row["record_offset"]))
    for midx in list(out):
        out[midx]["submesh_indices"] = sorted(out[midx]["submesh_indices"])
        out[midx]["shader_indices"] = sorted(set(out[midx]["shader_indices"]))
        out[midx]["record_offsets"] = sorted(out[midx]["record_offsets"])
    return dict(out)


def reverse_materials(materials: Mapping[int, Mapping[str, Any]]) -> dict[str, list[int]]:
    rev: dict[str, list[int]] = defaultdict(list)
    for idx, row in materials.items():
        rev[str(row["texture_fingerprint"])].append(int(idx))
    return {k: sorted(v) for k, v in rev.items()}


def reverse_schema(blocks: Mapping[int, Mapping[str, Any]], allowed: Sequence[int] | None = None) -> dict[str, list[int]]:
    rev: dict[str, list[int]] = defaultdict(list)
    ids = sorted(blocks) if allowed is None else sorted(set(int(x) for x in allowed if int(x) in blocks))
    for idx in ids:
        rev[str(blocks[idx]["schema_fingerprint"])].append(idx)
    return {k: sorted(v) for k, v in rev.items()}


def _csv_ints(values: Sequence[int]) -> str:
    return ",".join(str(x) for x in values)


def analyze_variants(variants: Mapping[str, Mapping[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    for name in ("source_dry", "source_wet", "target_dry", "target_wet"):
        require(name in variants, f"missing parsed variant: {name}")

    mats = {name: group_materials(variants[name]) for name in variants}
    blocks = {name: shader_blocks(variants[name]) for name in variants}
    usage = {name: usage_by_material(variants[name]) for name in variants}
    target_wet_by_material = reverse_materials(mats["target_wet"])
    source_dry_schema = reverse_schema(blocks["source_dry"])
    target_dry_schema = reverse_schema(blocks["target_dry"])

    material_usage_rows: list[dict[str, Any]] = []
    schema_rows: list[dict[str, Any]] = []
    parameter_rows: list[dict[str, Any]] = []
    candidate_rows: list[dict[str, Any]] = []

    for smidx, smat in sorted(mats["source_wet"].items()):
        tmatches = target_wet_by_material.get(str(smat["texture_fingerprint"]), [])
        sw_usage = usage["source_wet"].get(smidx, {"submesh_indices": [], "shader_indices": [], "record_offsets": []})
        tmidx = tmatches[0] if len(tmatches) == 1 else None
        tw_usage = usage["target_wet"].get(tmidx, {"submesh_indices": [], "shader_indices": [], "record_offsets": []}) if tmidx is not None else {"submesh_indices": [], "shader_indices": [], "record_offsets": []}
        material_usage_rows.append({
            "source_wet_material_index": smidx,
            "source_texture_fingerprint": smat["texture_fingerprint"],
            "target_wet_matching_material_indices": _csv_ints(tmatches),
            "unique_target_material_match": len(tmatches) == 1,
            "target_wet_material_index": "" if tmidx is None else tmidx,
            "source_wet_submesh_indices": _csv_ints(sw_usage["submesh_indices"]),
            "source_wet_shader_indices": _csv_ints(sw_usage["shader_indices"]),
            "target_wet_submesh_indices": _csv_ints(tw_usage["submesh_indices"]),
            "target_wet_shader_indices": _csv_ints(tw_usage["shader_indices"]),
            "source_material_is_used": bool(sw_usage["submesh_indices"]),
            "target_material_is_used": bool(tw_usage["submesh_indices"]),
            "focus_material": smidx == FOCUS_SOURCE_MATERIAL_INDEX and tmidx == FOCUS_TARGET_MATERIAL_INDEX,
            "semantics_confirmed": False,
            "write_authorized": False,
        })
        if tmidx is None:
            continue

        target_wet_usage_schema = reverse_schema(blocks["target_wet"], tw_usage["shader_indices"])
        source_wet_shader_ids = sw_usage["shader_indices"]
        for ssidx in source_wet_shader_ids:
            sblock = blocks["source_wet"].get(ssidx)
            if sblock is None:
                continue
            schema_fp = str(sblock["schema_fingerprint"])
            tw_schema_matches = target_wet_usage_schema.get(schema_fp, [])
            sd_matches = source_dry_schema.get(schema_fp, [])
            td_matches = target_dry_schema.get(schema_fp, [])
            tsidx = tw_schema_matches[0] if len(tw_schema_matches) == 1 else None
            sdidx = sd_matches[0] if len(sd_matches) == 1 else None
            tdidx = td_matches[0] if len(td_matches) == 1 else None
            schema_rows.append({
                "source_wet_material_index": smidx,
                "target_wet_material_index": tmidx,
                "source_wet_shader_block_index": ssidx,
                "source_parameter_count": sblock["parameter_count"],
                "shader_schema_fingerprint": schema_fp,
                "target_wet_material_scoped_schema_matches": _csv_ints(tw_schema_matches),
                "unique_target_wet_material_scoped_schema_match": len(tw_schema_matches) == 1,
                "target_wet_shader_block_index": "" if tsidx is None else tsidx,
                "source_dry_global_schema_matches": _csv_ints(sd_matches),
                "unique_source_dry_schema_control": len(sd_matches) == 1,
                "source_dry_shader_block_index": "" if sdidx is None else sdidx,
                "target_dry_global_schema_matches": _csv_ints(td_matches),
                "unique_target_dry_schema_control": len(td_matches) == 1,
                "target_dry_shader_block_index": "" if tdidx is None else tdidx,
                "focus_material": smidx == FOCUS_SOURCE_MATERIAL_INDEX and tmidx == FOCUS_TARGET_MATERIAL_INDEX,
                "semantics_confirmed": False,
                "write_authorized": False,
            })
            if tsidx is None:
                continue

            tblock = blocks["target_wet"][tsidx]
            sdblock = blocks["source_dry"].get(sdidx) if sdidx is not None else None
            tdblock = blocks["target_dry"].get(tdidx) if tdidx is not None else None
            require(set(sblock["rows"]) == set(tblock["rows"]), "schema fingerprint collision between source/target wet blocks")
            for key in sorted(sblock["rows"]):
                sr = sblock["rows"][key]
                tr = tblock["rows"][key]
                sw = str(sr["value_hex"]); tw = str(tr["value_hex"])
                sd = str(sdblock["rows"][key]["value_hex"]) if sdblock is not None and key in sdblock["rows"] else ""
                td = str(tdblock["rows"][key]["value_hex"]) if tdblock is not None and key in tdblock["rows"] else ""
                exact_base = bool(sd and td and sd == td and sw != sd and tw == td)
                matching_wet = bool(sd and td and sd == td and sw == tw and sw != sd)
                cross_game_wet_diff = sw != tw
                scalar4 = len(bytes.fromhex(sw)) == 4 and len(bytes.fromhex(tw)) == 4
                bounded = bool(
                    exact_base and scalar4 and len(tw_schema_matches) == 1 and len(sd_matches) == 1 and len(td_matches) == 1
                    and bool(sw_usage["submesh_indices"]) and bool(tw_usage["submesh_indices"])
                )
                row = {
                    "source_wet_material_index": smidx,
                    "target_wet_material_index": tmidx,
                    "source_wet_shader_block_index": ssidx,
                    "target_wet_shader_block_index": tsidx,
                    "shader_schema_fingerprint": schema_fp,
                    "parameter_name": key[0],
                    "parameter_occurrence": key[1],
                    "buffer_type": key[2],
                    "buffer_count": key[3],
                    "source_dry_hex": sd,
                    "source_wet_hex": sw,
                    "target_dry_hex": td,
                    "target_wet_hex": tw,
                    "cross_game_wet_value_differs": cross_game_wet_diff,
                    "exact_base_control_missing_wet_transition": exact_base,
                    "matching_wet_transition": matching_wet,
                    "four_byte_scalar": scalar4,
                    "target_wet_value_offset": int(tr["value_offset"]),
                    "target_before_hex": tw,
                    "source_wet_desired_hex": sw if cross_game_wet_diff else "",
                    "source_material_is_used": bool(sw_usage["submesh_indices"]),
                    "target_material_is_used": bool(tw_usage["submesh_indices"]),
                    "focus_material": smidx == FOCUS_SOURCE_MATERIAL_INDEX and tmidx == FOCUS_TARGET_MATERIAL_INDEX,
                    "bounded_scalar_candidate": bounded,
                    "semantics_confirmed": False,
                    "write_authorized": False,
                }
                parameter_rows.append(row)
                if bounded:
                    candidate_rows.append(row)

    return {
        "material_usage": material_usage_rows,
        "shader_schema": schema_rows,
        "parameters": parameter_rows,
        "candidates": candidate_rows,
    }


def build_report(
    project_root: Path, *, report_root: Path | None = None, output_report_root: Path | None = None,
    workspace_root: Path | None = None, original_root: Path | None = None, quartet_root: Path | None = None,
    gust_pak_path: Path | None = None, create_archive: bool = True, timeout_seconds: int = 1800,
    verify_payload_hashes: bool = True,
) -> tuple[Path | None, dict[str, Any]]:
    project_root = project_root.resolve()
    version = (project_root / "workstreams/quartet_restoration/VERSION").read_text(encoding="utf-8").strip()
    require(tuple(map(int, version.split("."))) >= tuple(map(int, TOOL_VERSION.split("."))), f"expected {TOOL_VERSION} or newer, found {version}")
    report_root = (report_root or project_root / ".local/reports/quartet_restoration").resolve()
    output_report_root = (output_report_root or report_root).resolve()
    workspace_root = (workspace_root or project_root / ".local/build/quartet_restoration" / WORKSPACE_SUBDIR).resolve()
    output = output_report_root / REPORT_DIR
    archive = output_report_root / REPORT_NAME
    if output.exists(): shutil.rmtree(output)
    output.mkdir(parents=True, exist_ok=True)

    stage153 = validate_stage153(report_root)
    br = load_module(project_root / "Blue_Reflection_Text_Tool/br_restoration_tool.py", "stage154_br")
    stage125 = load_module(project_root / "workstreams/quartet_restoration/125_collect_character_state_exact_rehydration_evidence.py", "stage154_stage125")
    stage151 = load_module(project_root / "workstreams/quartet_restoration/151_collect_hinako_wet_school_g1mg_binding_differential_evidence.py", "stage154_stage151")
    inventories = stage125.load_asset_inventories(project_root)
    extraction_rows = stage125.ensure_extraction_cache(
        project_root=project_root, workspace_root=workspace_root, inventories=inventories,
        required_paths=[DRY_ARCHIVE, WET_ARCHIVE], original_root=original_root, quartet_root=quartet_root,
        gust_pak_path=gust_pak_path, br=br, timeout_seconds=timeout_seconds,
    )

    variants: dict[str, dict[str, Any]] = {}
    input_rows: list[dict[str, Any]] = []
    parse_skips: list[dict[str, Any]] = []
    for side in ("source", "target"):
        for state, normalized in ((DRY_STATE, DRY_ARCHIVE), (WET_STATE, WET_ARCHIVE)):
            pair_id, entry = inventories[(side, normalized.casefold())]
            local = br.inventory_workspace_file(workspace_root, side, pair_id, str(entry["archive"]), str(entry["path"]))
            require(local.is_file(), f"missing extracted input: {side} {normalized}: {local}")
            actual = sha256_file(local)
            if verify_payload_hashes:
                require(actual == str(entry["sha256"]), f"payload hash drift: {side} {normalized}: {actual}")
            progress(f"reading {side} {state}: {normalized}")
            parsed_archive = br.read_earc_archive(local, maximum_bytes=MAX_EARC_BYTES, include_member_payloads=True)
            matches = []
            for candidate in parsed_archive["members"]:
                if str(candidate.get("extension", "")).casefold() != ".g1m":
                    continue
                role = stage125.normalized_role(str(candidate["name"]), CHARACTER_ID, state)
                if role == TARGET_ROLE:
                    matches.append(candidate)
            require(len(matches) == 1, f"expected one normalized role {TARGET_ROLE} in {side} {normalized}, found {len(matches)}")
            member = matches[0]
            member_name = str(member["name"])
            payload = member.get("payload")
            require(isinstance(payload, (bytes, bytearray)), f"missing payload for {side} {state} {member_name}")
            payload = bytes(payload)
            key = f"{side}_{'dry' if state == DRY_STATE else 'wet'}"
            try:
                variants[key] = stage151.parse_g1mg_binding_metadata(payload, label=f"{side}:{state}:{member_name}")
            except Exception as exc:
                parse_skips.append({"variant": key, "member_name": member_name, "reason": str(exc), "write_authorized": False})
                continue
            input_rows.append({
                "side": side, "state_token": state, "archive_path": normalized,
                "archive_input_sha256": actual, "member_name": member_name,
                "member_sha256": hashlib.sha256(payload).hexdigest(), "member_size": len(payload),
                "payload_in_evidence": False,
            })

    require(not parse_skips, f"stage154 parse skips: {len(parse_skips)}")
    analysis = analyze_variants(variants)

    write_tsv(output / "INPUTS.tsv", ["side","state_token","archive_path","archive_input_sha256","member_name","member_sha256","member_size","payload_in_evidence"], input_rows)
    write_tsv(output / "MATERIAL_USAGE.tsv", [
        "source_wet_material_index","source_texture_fingerprint","target_wet_matching_material_indices","unique_target_material_match","target_wet_material_index",
        "source_wet_submesh_indices","source_wet_shader_indices","target_wet_submesh_indices","target_wet_shader_indices","source_material_is_used","target_material_is_used","focus_material","semantics_confirmed","write_authorized"
    ], analysis["material_usage"])
    write_tsv(output / "SHADER_SCHEMA_MATCHES.tsv", [
        "source_wet_material_index","target_wet_material_index","source_wet_shader_block_index","source_parameter_count","shader_schema_fingerprint",
        "target_wet_material_scoped_schema_matches","unique_target_wet_material_scoped_schema_match","target_wet_shader_block_index",
        "source_dry_global_schema_matches","unique_source_dry_schema_control","source_dry_shader_block_index",
        "target_dry_global_schema_matches","unique_target_dry_schema_control","target_dry_shader_block_index","focus_material","semantics_confirmed","write_authorized"
    ], analysis["shader_schema"])
    write_tsv(output / "PARAMETER_VALUE_COMPARISON.tsv", [
        "source_wet_material_index","target_wet_material_index","source_wet_shader_block_index","target_wet_shader_block_index","shader_schema_fingerprint",
        "parameter_name","parameter_occurrence","buffer_type","buffer_count","source_dry_hex","source_wet_hex","target_dry_hex","target_wet_hex",
        "cross_game_wet_value_differs","exact_base_control_missing_wet_transition","matching_wet_transition","four_byte_scalar","target_wet_value_offset","target_before_hex","source_wet_desired_hex",
        "source_material_is_used","target_material_is_used","focus_material","bounded_scalar_candidate","semantics_confirmed","write_authorized"
    ], analysis["parameters"])
    write_tsv(output / "BOUNDED_SCALAR_CANDIDATES.tsv", [
        "source_wet_material_index","target_wet_material_index","source_wet_shader_block_index","target_wet_shader_block_index","shader_schema_fingerprint",
        "parameter_name","parameter_occurrence","buffer_type","buffer_count","source_dry_hex","source_wet_hex","target_dry_hex","target_wet_hex",
        "target_wet_value_offset","target_before_hex","source_wet_desired_hex","focus_material","bounded_scalar_candidate","semantics_confirmed","write_authorized"
    ], analysis["candidates"])
    write_tsv(output / "PARSE_SKIPPED.tsv", ["variant","member_name","reason","write_authorized"], parse_skips)
    write_tsv(output / "EXTRACTION_INPUTS.tsv", ["archive_relative","archive_sha256","archive_size","cache_action","gust_pak_sha256","side"], extraction_rows)

    focus_usage = [r for r in analysis["material_usage"] if r["focus_material"]]
    focus_schema = [r for r in analysis["shader_schema"] if r["focus_material"]]
    focus_params = [r for r in analysis["parameters"] if r["focus_material"]]
    focus_candidates = [r for r in analysis["candidates"] if r["focus_material"]]
    summary = {
        "type": "br_quartet_restoration_hinako_wet_school_shader_schema_material_usage_evidence_summary",
        "format_version": 1,
        "tool_version": TOOL_VERSION,
        "status": "stage153_zero_binding_candidates_preserved_wet_material_shader_schema_usage_audit_complete_no_write",
        "stage153_evidence_sha256": STAGE153_SHA256,
        "stage153_bounded_binding_candidate_rows": int(stage153["bounded_binding_candidate_rows"]),
        "stage153_unique_material_fingerprint_rows": int(stage153["unique_cross_game_material_fingerprint_rows"]),
        "stage153_unique_shader_fingerprint_rows": int(stage153["unique_cross_game_shader_fingerprint_rows"]),
        "material_usage_rows": len(analysis["material_usage"]),
        "used_source_material_rows": sum(bool(r["source_material_is_used"]) for r in analysis["material_usage"]),
        "used_target_material_rows": sum(bool(r["target_material_is_used"]) for r in analysis["material_usage"]),
        "shader_schema_match_rows": len(analysis["shader_schema"]),
        "unique_target_material_scoped_schema_rows": sum(bool(r["unique_target_wet_material_scoped_schema_match"]) for r in analysis["shader_schema"]),
        "parameter_comparison_rows": len(analysis["parameters"]),
        "cross_game_wet_parameter_difference_rows": sum(bool(r["cross_game_wet_value_differs"]) for r in analysis["parameters"]),
        "exact_base_control_missing_wet_transition_rows": sum(bool(r["exact_base_control_missing_wet_transition"]) for r in analysis["parameters"]),
        "bounded_scalar_candidate_rows": len(analysis["candidates"]),
        "focus_source_material_index": FOCUS_SOURCE_MATERIAL_INDEX,
        "focus_target_material_index": FOCUS_TARGET_MATERIAL_INDEX,
        "focus_texture_triplet": list(FOCUS_TEXTURE_TRIPLET),
        "focus_material_usage_rows": len(focus_usage),
        "focus_source_material_is_used": bool(focus_usage and focus_usage[0]["source_material_is_used"]),
        "focus_target_material_is_used": bool(focus_usage and focus_usage[0]["target_material_is_used"]),
        "focus_source_shader_indices": focus_usage[0]["source_wet_shader_indices"] if focus_usage else "",
        "focus_target_shader_indices": focus_usage[0]["target_wet_shader_indices"] if focus_usage else "",
        "focus_shader_schema_rows": len(focus_schema),
        "focus_unique_target_schema_rows": sum(bool(r["unique_target_wet_material_scoped_schema_match"]) for r in focus_schema),
        "focus_parameter_rows": len(focus_params),
        "focus_cross_game_wet_parameter_difference_rows": sum(bool(r["cross_game_wet_value_differs"]) for r in focus_params),
        "focus_exact_base_control_missing_wet_transition_rows": sum(bool(r["exact_base_control_missing_wet_transition"]) for r in focus_params),
        "focus_bounded_scalar_candidate_rows": len(focus_candidates),
        "parse_skip_rows": len(parse_skips),
        "runtime_validated": False,
        "production_eligible": False,
        "policy": {
            "material_fingerprint_is_identity_only_for_texture_assignment": True,
            "shader_schema_fingerprint_ignores_values": True,
            "material_or_shader_ordinals_treated_as_cross_game_identity": False,
            "parameter_names_or_values_are_semantic_proof": False,
            "wet_transparency_semantics_confirmed": False,
            "wet_skin_droplet_semantics_confirmed": False,
            "bounded_scalar_rows_are_candidates_only": True,
            "scalar_write_authorized": False,
            "whole_g1mm_transplant_reuse_forbidden": True,
            "complete_g1mg_transplant_authorized": False,
            "pak_repacked": False,
            "installed_game_modified": False,
            "core_modified": False,
            "translation_modified": False,
            "legacy_dlc_modified": False,
            "git_modified": False,
            "proprietary_payloads_in_evidence": False,
        },
        "next_action": "If a focus or other used-material shader schema maps uniquely and yields a bounded 4-byte exact-base-control missing wet transition, review that one target-native scalar as a possible minimal Fast Test probe. Otherwise do not patch shader parameters and move to another wet-only layer such as texture/material state or body wet-state binding.",
    }
    (output / "SUMMARY.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    if create_archive:
        make_archive(output, archive)
        return archive, summary
    return None, summary


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("--project-root", type=Path, default=PROJECT_ROOT_DEFAULT)
    p.add_argument("--report-root", type=Path)
    p.add_argument("--output-report-root", type=Path)
    p.add_argument("--workspace-root", type=Path)
    p.add_argument("--original-root", type=Path)
    p.add_argument("--quartet-root", type=Path)
    p.add_argument("--gust-pak-path", type=Path)
    p.add_argument("--timeout-seconds", type=int, default=1800)
    p.add_argument("--no-archive", action="store_true")
    p.add_argument("--no-payload-hash-verification", action="store_true")
    return p.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        archive, summary = build_report(
            args.project_root, report_root=args.report_root, output_report_root=args.output_report_root,
            workspace_root=args.workspace_root, original_root=args.original_root, quartet_root=args.quartet_root,
            gust_pak_path=args.gust_pak_path, create_archive=not args.no_archive,
            timeout_seconds=args.timeout_seconds, verify_payload_hashes=not args.no_payload_hash_verification,
        )
        print(json.dumps(summary, indent=2, sort_keys=True))
        if archive is not None:
            print(f"[stage154] report archive: {archive}", flush=True)
        return 0
    except WetSchoolShaderSchemaError as exc:
        print(f"[stage154] ERROR: {exc}", file=sys.stderr, flush=True)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
