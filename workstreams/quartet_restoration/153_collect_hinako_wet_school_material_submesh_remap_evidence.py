#!/usr/bin/env python3
"""Stage 153: read-only Hinako wet-school material/submesh remap audit.

Stages 151-152 ruled out a safe direct scalar/field write.  Stage 151 also
showed a stronger structural clue: the wet texture triplet used by Original in
PC00_Scl_W_default.g1m is still present in Quartet wet, but at a different
material index.  This collector therefore aligns source/target *wet* materials
by exact content fingerprints, aligns submeshes by binding-independent geometry
signatures, and checks whether a mapped target submesh is bound away from an
otherwise preserved wet material/shader configuration.

No payload is modified.  Exact target locators are reported only for unique
strong geometry mappings; all candidates remain write_authorized=false.
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
TOOL_VERSION = "0.1.71"
REPORT_DIR = "hinako_wet_school_material_submesh_remap_evidence"
REPORT_NAME = "BR_quartet_restoration_hinako_wet_school_material_submesh_remap_evidence.tar.zst"
WORKSPACE_SUBDIR = Path("wet_school_material_submesh_remap")

CHARACTER_ID = "pc00"
DRY_STATE = "scl"
WET_STATE = "scl_w"
DRY_ARCHIVE = "data/x64/character/pc00/pc00_scl.elixir.gz"
WET_ARCHIVE = "data/x64/character/pc00/pc00_scl_w.elixir.gz"
TARGET_ROLE = "{pc}_{state}_default.g1m"
MAX_EARC_BYTES = 128 * 1024 * 1024

STAGE152_REPORT = "BR_quartet_restoration_hinako_wet_accessory_g1mm_exact_field_evidence.tar.zst"
STAGE152_SHA256 = "a96c875a5d47c0f3ecf2721c634723b245556438f8a0ad5597de212f426b3e6a"
STAGE152_ROOT = "hinako_wet_accessory_g1mm_exact_field_evidence"
STAGE151_SHA256 = "68bb8760691bb01833af87c7ff6ed5c05868e360b1a4a6363bb9a8c187c5f1b9"

FORBIDDEN_REPORT_EXTENSIONS = (
    ".pak", ".g1m", ".g1t", ".g1s", ".g1e", ".g1em", ".elixir", ".elixir.gz", ".ebd", ".ebm", ".kps"
)


class WetSchoolRemapError(RuntimeError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise WetSchoolRemapError(message)


def progress(message: str) -> None:
    print(f"[stage153] {message}", flush=True)


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
    require(actual == expected_sha256, f"stage-152 evidence SHA-256 drift: {actual}")
    cp = subprocess.run(["tar", "--zstd", "-tf", str(archive)], text=True, capture_output=True)
    require(cp.returncode == 0, cp.stderr.strip() or "cannot list stage-152 evidence")
    names = [safe_relative(x.strip(), "stage-152 member") for x in cp.stdout.splitlines() if x.strip()]
    require(names and {PurePosixPath(x).parts[0] for x in names} == {expected_root}, "unexpected stage-152 archive root")
    require(not any(x.casefold().endswith(FORBIDDEN_REPORT_EXTENSIONS) for x in names), "proprietary payload in stage-152 evidence")
    destination.mkdir(parents=True, exist_ok=True)
    cp = subprocess.run(["tar", "--zstd", "-xf", str(archive), "-C", str(destination)], text=True, capture_output=True)
    require(cp.returncode == 0, cp.stderr.strip() or "cannot extract stage-152 evidence")
    return destination / expected_root


def validate_stage152(report_root: Path) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="stage153-prereq-") as td:
        root = extract_report(report_root / STAGE152_REPORT, STAGE152_SHA256, STAGE152_ROOT, Path(td))
        summary = json.loads((root / "SUMMARY.json").read_text(encoding="utf-8"))
        require(summary.get("tool_version") == "0.1.70", "stage-152 version drift")
        require(summary.get("stage151_evidence_sha256") == STAGE151_SHA256, "stage-151 chain drift")
        require(summary.get("exact_field_candidate_rows") == 0, "stage-152 unexpectedly has exact field candidates")
        require(summary.get("school_exact_field_candidate_rows") == 0, "stage-152 school candidate count drift")
        require(summary.get("school_source_dry_wet_changed") is True, "stage-152 Original school clue lost")
        require(summary.get("school_target_dry_wet_changed") is False, "stage-152 Quartet school clue lost")
        require(summary.get("runtime_validated") is False and summary.get("production_eligible") is False, "stage-152 promotion drift")
        policy = summary.get("policy", {})
        require(policy.get("field_write_authorized") is False, "stage-152 field write unexpectedly authorized")
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
        first = rows[0]
        textures = [
            {
                "slot": int(r["texture_slot"]),
                "texture_id": int(r["texture_id"]),
                "layer": int(r["layer"]),
                "texture_type": int(r["texture_type"]),
                "subtype": int(r["subtype"]),
                "tilemodex": int(r["tilemodex"]),
                "tilemodey": int(r["tilemodey"]),
            }
            for r in rows
        ]
        texture_payload = _canon(textures)
        full_payload = _canon({
            "unknown1": int(first["unknown1"]), "unknown2": int(first["unknown2"]), "unknown3": int(first["unknown3"]),
            "texture_count": int(first["texture_count"]), "textures": textures,
        })
        out[idx] = {
            "material_index": idx,
            "texture_count": len(textures),
            "texture_fingerprint": sha256_text(texture_payload),
            "full_fingerprint": sha256_text(full_payload),
            "textures": textures,
        }
    return out


def group_shader_blocks(parsed: Mapping[str, Any]) -> dict[int, dict[str, Any]]:
    grouped: dict[int, list[Mapping[str, Any]]] = defaultdict(list)
    for row in parsed.get("shader_params", []):
        grouped[int(row["shader_block_index"])].append(row)
    out: dict[int, dict[str, Any]] = {}
    for idx, rows in grouped.items():
        items = [
            {
                "name": str(r["parameter_name_folded"]),
                "occurrence": int(r["parameter_occurrence"]),
                "buffer_type": int(r["buffer_type"]),
                "buffer_count": int(r["buffer_count"]),
                "value_hex": str(r["value_hex"]),
            }
            for r in sorted(rows, key=lambda r: (str(r["parameter_name_folded"]), int(r["parameter_occurrence"]), int(r["parameter_index"])))
        ]
        payload = _canon(items)
        out[idx] = {"shader_block_index": idx, "parameter_count": len(items), "fingerprint": sha256_text(payload)}
    return out


STRONG_GEOMETRY_FIELDS = (
    "submeshFlags", "vertexBufferIndex", "bonePaletteIndex", "boneIndex", "unknown",
    "indexBufferIndex", "unknown2", "indexBufferPrimType", "vertexBufferOffset", "vertexCount",
    "indexBufferOffset", "indexCount",
)
TOPOLOGY_FIELDS = (
    "submeshFlags", "vertexBufferIndex", "bonePaletteIndex", "boneIndex", "unknown",
    "indexBufferIndex", "unknown2", "indexBufferPrimType", "vertexCount", "indexCount",
)


def submesh_signature(row: Mapping[str, Any], fields: Sequence[str]) -> str:
    return sha256_text(_canon({f: int(row[f]) for f in fields}))


def unique_signature_map(rows: Sequence[Mapping[str, Any]], fields: Sequence[str]) -> tuple[dict[str, Mapping[str, Any]], set[str]]:
    grouped: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[submesh_signature(row, fields)].append(row)
    unique = {sig: vals[0] for sig, vals in grouped.items() if len(vals) == 1}
    duplicate = {sig for sig, vals in grouped.items() if len(vals) != 1}
    return unique, duplicate


def reverse_fingerprints(rows: Mapping[int, Mapping[str, Any]], field: str) -> dict[str, list[int]]:
    out: dict[str, list[int]] = defaultdict(list)
    for idx, row in rows.items():
        out[str(row[field])].append(int(idx))
    return {k: sorted(v) for k, v in out.items()}


def lod_names_for_submesh(parsed: Mapping[str, Any], index: int) -> list[str]:
    return sorted({str(r.get("name", "")) for r in parsed.get("mesh_lod", []) if index in [int(x) for x in r.get("indices", [])]})


def analyze_wet_pair(source_wet: Mapping[str, Any], target_wet: Mapping[str, Any]) -> dict[str, list[dict[str, Any]]]:
    src_mats = group_materials(source_wet); tgt_mats = group_materials(target_wet)
    src_shaders = group_shader_blocks(source_wet); tgt_shaders = group_shader_blocks(target_wet)
    tgt_mat_by_tex = reverse_fingerprints(tgt_mats, "texture_fingerprint")
    tgt_shader_by_fp = reverse_fingerprints(tgt_shaders, "fingerprint")

    material_rows: list[dict[str, Any]] = []
    for sidx, sm in sorted(src_mats.items()):
        matches = tgt_mat_by_tex.get(str(sm["texture_fingerprint"]), [])
        material_rows.append({
            "source_wet_material_index": sidx,
            "source_texture_count": sm["texture_count"],
            "source_texture_fingerprint": sm["texture_fingerprint"],
            "target_wet_matching_material_indices": ",".join(map(str, matches)),
            "unique_target_texture_match": len(matches) == 1,
            "target_match_material_index": matches[0] if len(matches) == 1 else "",
            "same_ordinal": len(matches) == 1 and matches[0] == sidx,
            "semantics_confirmed": False,
            "write_authorized": False,
        })

    shader_rows: list[dict[str, Any]] = []
    for sidx, ss in sorted(src_shaders.items()):
        matches = tgt_shader_by_fp.get(str(ss["fingerprint"]), [])
        shader_rows.append({
            "source_wet_shader_block_index": sidx,
            "source_parameter_count": ss["parameter_count"],
            "source_shader_fingerprint": ss["fingerprint"],
            "target_wet_matching_shader_block_indices": ",".join(map(str, matches)),
            "unique_target_shader_match": len(matches) == 1,
            "target_match_shader_block_index": matches[0] if len(matches) == 1 else "",
            "same_ordinal": len(matches) == 1 and matches[0] == sidx,
            "semantics_confirmed": False,
            "write_authorized": False,
        })

    src_strong, src_strong_dups = unique_signature_map(source_wet.get("submeshes", []), STRONG_GEOMETRY_FIELDS)
    tgt_strong, tgt_strong_dups = unique_signature_map(target_wet.get("submeshes", []), STRONG_GEOMETRY_FIELDS)
    src_top, src_top_dups = unique_signature_map(source_wet.get("submeshes", []), TOPOLOGY_FIELDS)
    tgt_top, tgt_top_dups = unique_signature_map(target_wet.get("submeshes", []), TOPOLOGY_FIELDS)

    target_exemplar_pairs: dict[int, set[tuple[int, int]]] = defaultdict(set)
    for row in target_wet.get("submeshes", []):
        target_exemplar_pairs[int(row["materialIndex"])].add((int(row["materialIndex"]), int(row["shaderParamIndex"])))

    submesh_rows: list[dict[str, Any]] = []
    candidate_rows: list[dict[str, Any]] = []
    for srow in source_wet.get("submeshes", []):
        strong_sig = submesh_signature(srow, STRONG_GEOMETRY_FIELDS)
        top_sig = submesh_signature(srow, TOPOLOGY_FIELDS)
        trow = tgt_strong.get(strong_sig)
        mapping = "unique_strong_geometry" if trow is not None and strong_sig not in src_strong_dups and strong_sig not in tgt_strong_dups else ""
        if trow is None:
            trow = tgt_top.get(top_sig)
            if trow is not None and top_sig not in src_top_dups and top_sig not in tgt_top_dups:
                mapping = "unique_topology_geometry"
        if trow is None:
            continue

        smat_idx = int(srow["materialIndex"]); ssh_idx = int(srow["shaderParamIndex"])
        tmat_idx = int(trow["materialIndex"]); tsh_idx = int(trow["shaderParamIndex"])
        smat = src_mats.get(smat_idx); ssh = src_shaders.get(ssh_idx)
        mat_matches = [] if smat is None else tgt_mat_by_tex.get(str(smat["texture_fingerprint"]), [])
        sh_matches = [] if ssh is None else tgt_shader_by_fp.get(str(ssh["fingerprint"]), [])
        desired_mat = mat_matches[0] if len(mat_matches) == 1 else None
        desired_sh = sh_matches[0] if len(sh_matches) == 1 else None
        source_lod = lod_names_for_submesh(source_wet, int(srow["submesh_index"]))
        target_lod = lod_names_for_submesh(target_wet, int(trow["submesh_index"]))
        shared_lod = sorted(set(source_lod) & set(target_lod))
        exemplar_pairs = sorted(target_exemplar_pairs.get(desired_mat, set())) if desired_mat is not None else []
        exact_pair_exemplar = bool(desired_mat is not None and desired_sh is not None and (desired_mat, desired_sh) in exemplar_pairs)
        changed = bool((desired_mat is not None and desired_mat != tmat_idx) or (desired_sh is not None and desired_sh != tsh_idx))
        strong = mapping == "unique_strong_geometry"
        bounded = bool(strong and desired_mat is not None and desired_sh is not None and changed and shared_lod and exact_pair_exemplar)
        row = {
            "source_wet_submesh_index": int(srow["submesh_index"]),
            "target_wet_submesh_index": int(trow["submesh_index"]),
            "mapping_strength": mapping,
            "strong_geometry_signature": strong_sig,
            "topology_signature": top_sig,
            "source_current_material_index": smat_idx,
            "source_current_shader_param_index": ssh_idx,
            "target_current_material_index": tmat_idx,
            "target_current_shader_param_index": tsh_idx,
            "source_material_texture_fingerprint": "" if smat is None else smat["texture_fingerprint"],
            "target_preserved_material_indices": ",".join(map(str, mat_matches)),
            "unique_preserved_material": len(mat_matches) == 1,
            "desired_target_material_index": "" if desired_mat is None else desired_mat,
            "source_shader_fingerprint": "" if ssh is None else ssh["fingerprint"],
            "target_preserved_shader_indices": ",".join(map(str, sh_matches)),
            "unique_preserved_shader": len(sh_matches) == 1,
            "desired_target_shader_param_index": "" if desired_sh is None else desired_sh,
            "target_native_exact_pair_exemplar_exists": exact_pair_exemplar,
            "source_mesh_lod_names": ",".join(source_lod),
            "target_mesh_lod_names": ",".join(target_lod),
            "shared_mesh_lod_names": ",".join(shared_lod),
            "binding_differs_from_preserved_source_wet_pair": changed,
            "bounded_binding_candidate": bounded,
            "target_material_index_offset": int(trow["record_offset"]) + 24,
            "target_shader_param_index_offset": int(trow["record_offset"]) + 20,
            "target_current_material_precondition": tmat_idx,
            "target_current_shader_precondition": tsh_idx,
            "semantics_confirmed": False,
            "write_authorized": False,
        }
        submesh_rows.append(row)
        if bounded:
            candidate_rows.append(row)

    return {
        "materials": material_rows,
        "shader_blocks": shader_rows,
        "submeshes": submesh_rows,
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

    stage152 = validate_stage152(report_root)
    br = load_module(project_root / "Blue_Reflection_Text_Tool/br_restoration_tool.py", "stage153_br")
    stage125 = load_module(project_root / "workstreams/quartet_restoration/125_collect_character_state_exact_rehydration_evidence.py", "stage153_stage125")
    stage151 = load_module(project_root / "workstreams/quartet_restoration/151_collect_hinako_wet_school_g1mg_binding_differential_evidence.py", "stage153_stage151")
    inventories = stage125.load_asset_inventories(project_root)
    extraction_rows = stage125.ensure_extraction_cache(
        project_root=project_root, workspace_root=workspace_root, inventories=inventories,
        required_paths=[DRY_ARCHIVE, WET_ARCHIVE], original_root=original_root, quartet_root=quartet_root,
        gust_pak_path=gust_pak_path, br=br, timeout_seconds=timeout_seconds,
    )

    parsed_variants: dict[str, dict[str, Any]] = {}
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
            for member in parsed_archive["members"]:
                if str(member.get("extension", "")).casefold() != ".g1m":
                    continue
                role = stage125.normalized_role(str(member["name"]), CHARACTER_ID, state)
                if role == TARGET_ROLE:
                    matches.append(member)
            require(len(matches) == 1, f"expected exactly one {TARGET_ROLE} in {side}:{state}; found={len(matches)}")
            member = matches[0]
            label = f"{side}_{'dry' if state == DRY_STATE else 'wet'}"
            try:
                parsed_variants[label] = stage151.parse_g1mg_binding_metadata(member["payload"], label=f"{label}:{member['name']}")
            except Exception as exc:
                parse_skips.append({"variant": label, "member_name": member["name"], "reason": f"{type(exc).__name__}:{exc}", "write_authorized": False})
            input_rows.append({
                "side": side, "state_token": state, "archive_path": normalized, "archive_input_sha256": actual,
                "member_name": member["name"], "member_sha256": member["sha256"], "member_size": len(member["payload"]),
                "payload_in_evidence": False,
            })

    require(not parse_skips, "target role parsing failed; no binding audit allowed")
    require(set(parsed_variants) == {"source_dry", "source_wet", "target_dry", "target_wet"}, "incomplete four-way target role")
    analysis = analyze_wet_pair(parsed_variants["source_wet"], parsed_variants["target_wet"])

    # Preserve the exact stage-151 wet texture triplet clue as a regression gate.
    src_mats = group_materials(parsed_variants["source_wet"])
    tgt_mats = group_materials(parsed_variants["target_wet"])
    require(3 in src_mats, "source-wet material 3 missing")
    src3 = src_mats[3]
    wet_triplet = [(r["texture_id"], r["texture_type"], r["subtype"]) for r in src3["textures"] if r["slot"] in (4,5,6)]
    require(wet_triplet == [(21,29,0),(23,3,0),(27,57,57)], f"stage-151 wet triplet drift: {wet_triplet}")
    target_same_fp = [idx for idx, row in tgt_mats.items() if row["texture_fingerprint"] == src3["texture_fingerprint"]]
    require(target_same_fp, "Quartet wet no longer preserves the source-wet material-3 texture fingerprint")

    write_tsv(output / "INPUTS.tsv", ["side","state_token","archive_path","archive_input_sha256","member_name","member_sha256","member_size","payload_in_evidence"], input_rows)
    write_tsv(output / "MATERIAL_FINGERPRINT_MATCHES.tsv", [
        "source_wet_material_index","source_texture_count","source_texture_fingerprint","target_wet_matching_material_indices",
        "unique_target_texture_match","target_match_material_index","same_ordinal","semantics_confirmed","write_authorized"
    ], analysis["materials"])
    write_tsv(output / "SHADER_BLOCK_FINGERPRINT_MATCHES.tsv", [
        "source_wet_shader_block_index","source_parameter_count","source_shader_fingerprint","target_wet_matching_shader_block_indices",
        "unique_target_shader_match","target_match_shader_block_index","same_ordinal","semantics_confirmed","write_authorized"
    ], analysis["shader_blocks"])
    submesh_fields = [
        "source_wet_submesh_index","target_wet_submesh_index","mapping_strength","strong_geometry_signature","topology_signature",
        "source_current_material_index","source_current_shader_param_index","target_current_material_index","target_current_shader_param_index",
        "source_material_texture_fingerprint","target_preserved_material_indices","unique_preserved_material","desired_target_material_index",
        "source_shader_fingerprint","target_preserved_shader_indices","unique_preserved_shader","desired_target_shader_param_index",
        "target_native_exact_pair_exemplar_exists","source_mesh_lod_names","target_mesh_lod_names","shared_mesh_lod_names",
        "binding_differs_from_preserved_source_wet_pair","bounded_binding_candidate","target_material_index_offset","target_shader_param_index_offset",
        "target_current_material_precondition","target_current_shader_precondition","semantics_confirmed","write_authorized"
    ]
    write_tsv(output / "SUBMESH_SEMANTIC_REMAP_AUDIT.tsv", submesh_fields, analysis["submeshes"])
    write_tsv(output / "BOUNDED_BINDING_CANDIDATES.tsv", submesh_fields, analysis["candidates"])
    write_tsv(output / "PARSE_SKIPPED.tsv", ["variant","member_name","reason","write_authorized"], parse_skips)
    extraction_fields = sorted({k for r in extraction_rows for k in r.keys()}) if extraction_rows else ["side","archive_relative","cache_action"]
    write_tsv(output / "EXTRACTION_INPUTS.tsv", extraction_fields, extraction_rows)

    unique_material_relocations = [r for r in analysis["materials"] if r["unique_target_texture_match"] and not r["same_ordinal"]]
    unique_shader_relocations = [r for r in analysis["shader_blocks"] if r["unique_target_shader_match"] and not r["same_ordinal"]]
    strong_mapped = [r for r in analysis["submeshes"] if r["mapping_strength"] == "unique_strong_geometry"]
    topology_mapped = [r for r in analysis["submeshes"] if r["mapping_strength"] == "unique_topology_geometry"]
    summary = {
        "type": "br_quartet_restoration_hinako_wet_school_material_submesh_remap_evidence_summary",
        "format_version": 1,
        "tool_version": TOOL_VERSION,
        "status": "stage152_zero_exact_field_candidates_preserved_wet_material_fingerprint_submesh_remap_audit_complete_no_write",
        "stage152_evidence_sha256": STAGE152_SHA256,
        "stage152_exact_field_candidate_rows": 0,
        "stage151_evidence_sha256": STAGE151_SHA256,
        "target_role": TARGET_ROLE,
        "parse_skip_rows": len(parse_skips),
        "source_wet_material_rows": len(analysis["materials"]),
        "unique_cross_game_material_fingerprint_rows": sum(bool(r["unique_target_texture_match"]) for r in analysis["materials"]),
        "unique_relocated_material_fingerprint_rows": len(unique_material_relocations),
        "unique_cross_game_shader_fingerprint_rows": sum(bool(r["unique_target_shader_match"]) for r in analysis["shader_blocks"]),
        "unique_relocated_shader_fingerprint_rows": len(unique_shader_relocations),
        "strong_geometry_mapped_submesh_rows": len(strong_mapped),
        "topology_only_mapped_submesh_rows": len(topology_mapped),
        "bounded_binding_candidate_rows": len(analysis["candidates"]),
        "source_wet_material3_texture_triplet": ["21:29:0","23:3:0","27:57:57"],
        "source_wet_material3_preserved_in_target_wet_indices": target_same_fp,
        "runtime_validated": False,
        "production_eligible": False,
        "policy": {
            "whole_g1mm_transplant_reuse_forbidden": True,
            "complete_g1mg_transplant_authorized": False,
            "material_ordinals_treated_as_identity": False,
            "submesh_ordinals_treated_as_identity": False,
            "material_fingerprints_are_semantic_proof": False,
            "geometry_signatures_are_visual_semantic_proof": False,
            "binding_rows_are_candidates_only": True,
            "binding_write_authorized": False,
            "blouse_transparency_semantics_confirmed": False,
            "wet_skin_droplet_semantics_confirmed": False,
            "installed_game_modified": False,
            "pak_repacked": False,
            "core_modified": False,
            "translation_modified": False,
            "legacy_dlc_modified": False,
            "git_modified": False,
            "proprietary_payloads_in_evidence": False,
        },
        "next_action": (
            "If one bounded binding candidate is uniquely strong, preserves an exact source-wet material/shader pair already present natively in Quartet wet, "
            "and has shared MESH_LOD support, validate the exact target offsets and build at most one two-dword target-native binding probe. "
            "Otherwise do not patch material/submesh indices and move to another wet-only layer."
        ),
    }
    (output / "SUMMARY.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    for p in output.rglob("*"):
        if p.is_file():
            rel = p.relative_to(output).as_posix().casefold()
            require(not rel.endswith(FORBIDDEN_REPORT_EXTENSIONS), f"proprietary payload in report: {rel}")

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
    p.add_argument("--gust-pak", type=Path)
    p.add_argument("--timeout-seconds", type=int, default=1800)
    p.add_argument("--no-verify-payload-hashes", action="store_true")
    return p.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        archive, summary = build_report(
            args.project_root, report_root=args.report_root, output_report_root=args.output_report_root,
            workspace_root=args.workspace_root, original_root=args.original_root, quartet_root=args.quartet_root,
            gust_pak_path=args.gust_pak, timeout_seconds=args.timeout_seconds,
            verify_payload_hashes=not args.no_verify_payload_hashes,
        )
        print(json.dumps(summary, indent=2, sort_keys=True))
        if archive is not None:
            print(f"[stage153] report archive: {archive}")
            print(f"[stage153] SHA-256: {sha256_file(archive)}")
        return 0
    except WetSchoolRemapError as exc:
        print(f"[stage153] ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
