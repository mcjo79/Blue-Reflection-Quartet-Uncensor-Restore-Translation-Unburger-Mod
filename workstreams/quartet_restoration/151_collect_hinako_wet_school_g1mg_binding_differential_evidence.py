#!/usr/bin/env python3
"""Stage 151: read-only Hinako wet-school G1MG binding differential audit.

The stage-150 whole G1MM splice was runtime-failed because it severely
corrupted the rendered model without crashing.  This collector therefore does
not transplant G1MM or any other complete chunk.  It compares Original and
Quartet dry/wet school-uniform variants at the structured G1MG level:

* MATERIALS texture assignments;
* SHADER_PARAMS named values (with exact target byte locators for reporting);
* SUBMESH material/shader-parameter bindings;
* MESH_LOD shader-name/submesh bindings.

The four-way control is Original dry -> wet versus Quartet dry -> wet.  Exact
base-controlled rows are highlighted only when Original dry equals Quartet dry,
Original wet differs, and Quartet wet failed to change.  No semantic meaning or
write authorization is inferred from that pattern.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import importlib.util
import json
import os
import shutil
import struct
import subprocess
import sys
import tempfile
from collections import Counter, defaultdict
from pathlib import Path, PurePosixPath
from typing import Any, Iterable, Mapping, Sequence

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT_DEFAULT = SCRIPT_DIR.parent.parent
TOOL_VERSION = "0.1.69"
REPORT_DIR = "hinako_wet_school_g1mg_binding_differential_evidence"
REPORT_NAME = "BR_quartet_restoration_hinako_wet_school_g1mg_binding_differential_evidence.tar.zst"
WORKSPACE_SUBDIR = Path("wet_school_g1mg_binding_differential")

CHARACTER_ID = "pc00"
DRY_STATE = "scl"
WET_STATE = "scl_w"
DRY_ARCHIVE = "data/x64/character/pc00/pc00_scl.elixir.gz"
WET_ARCHIVE = "data/x64/character/pc00/pc00_scl_w.elixir.gz"
MAX_EARC_BYTES = 128 * 1024 * 1024

ACTIVATION_REPORT = "BR_quartet_restoration_hinako_wet_school_composite_g1mm_fast_test_lab_activation_evidence.tar.zst"
ACTIVATION_SHA256 = "3012b003ec1fa1892b215745e9abc3bb8b8f52bfcdb3a85b3c987eb9f9e05d3d"
ACTIVATION_ROOT = "hinako_wet_school_composite_g1mm_fast_test_lab_activation_evidence"
ROLLBACK_REPORT = "BR_quartet_restoration_hinako_wet_school_composite_g1mm_fast_test_lab_rollback_evidence.tar.zst"
ROLLBACK_SHA256 = "a3cd668e3bf5a3ade9d2d2d533be9164b17bc301cdc007bba347af1fe8876332"
ROLLBACK_ROOT = "hinako_wet_school_composite_g1mm_fast_test_lab_rollback_evidence"
OBSERVATION_PATH = SCRIPT_DIR / "WET_SCHOOL_COMPOSITE_G1MM_RUNTIME_OBSERVATION.json"
EXPECTED_BASELINE_SHA256 = "e798f39c3bcdbb11381197bddf9bd3ad8de6ccf5d7c0c78b22613046d47f5302"
FAILED_PROFILE_ID = "fast_test_pc00_scl_w_school_partial_plus_default_g1mm_c74bc813e41"
FAILED_PROFILE_SHA256 = "75eef97513a9c6d66372649bd2adc857c63d8c39f83aa53006dd5f6171e09684"

G1MG_MATERIALS = 0x00010002
G1MG_SHADER_PARAMS = 0x00010003
G1MG_SUBMESH = 0x00010008
G1MG_MESH_LOD = 0x00010009
G1M_HEADER_SIZE = 24
G1MG_HEADER_SIZE = 48

FORBIDDEN_REPORT_EXTENSIONS = (
    ".pak", ".g1m", ".g1t", ".g1s", ".g1e", ".g1em", ".elixir", ".elixir.gz", ".ebd", ".ebm", ".kps"
)


class WetSchoolG1MGError(RuntimeError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise WetSchoolG1MGError(message)


def progress(message: str) -> None:
    print(f"[stage151] {message}", flush=True)


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(8 * 1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


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


def extract_report(archive: Path, expected_sha256: str, expected_root: str, destination: Path, label: str) -> Path:
    require(archive.is_file(), f"missing {label}: {archive}")
    actual = sha256_file(archive)
    require(actual == expected_sha256, f"{label} SHA-256 drift: {actual}")
    cp = subprocess.run(["tar", "--zstd", "-tf", str(archive)], text=True, capture_output=True)
    require(cp.returncode == 0, cp.stderr.strip() or f"cannot list {label}")
    names = [safe_relative(x.strip(), f"{label} member") for x in cp.stdout.splitlines() if x.strip()]
    require(names and {PurePosixPath(x).parts[0] for x in names} == {expected_root}, f"unexpected {label} root")
    require(not any(x.casefold().endswith(FORBIDDEN_REPORT_EXTENSIONS) for x in names), f"proprietary payload in {label}")
    destination.mkdir(parents=True, exist_ok=True)
    cp = subprocess.run(["tar", "--zstd", "-xf", str(archive), "-C", str(destination)], text=True, capture_output=True)
    require(cp.returncode == 0, cp.stderr.strip() or f"cannot extract {label}")
    return destination / expected_root


def validate_runtime_failure(report_root: Path) -> dict[str, Any]:
    require(OBSERVATION_PATH.is_file(), "missing canonical stage-150 runtime observation")
    observation = json.loads(OBSERVATION_PATH.read_text(encoding="utf-8"))
    require(observation.get("profile_id") == FAILED_PROFILE_ID, "failed composite profile id drift")
    require(observation.get("profile_sha256") == FAILED_PROFILE_SHA256, "failed composite profile hash drift")
    require(observation.get("runtime_tested") is True, "stage-150 runtime observation not marked tested")
    require(observation.get("crash_observed") is False, "stage-150 crash observation drift")
    require(observation.get("severe_model_corruption_observed") is True, "stage-150 model-corruption observation missing")
    require(observation.get("runtime_validated") is False and observation.get("production_eligible") is False, "failed profile promoted")
    require(observation.get("whole_g1mm_transplant_reuse_forbidden") is True, "failed G1MM reuse guard missing")
    require(observation.get("exact_pack10_02_baseline_restored") is True, "stage-150 rollback not canonicalized")
    require(observation.get("pack10_02_baseline_sha256") == EXPECTED_BASELINE_SHA256, "stage-150 baseline hash drift")

    with tempfile.TemporaryDirectory(prefix="stage151-runtime-") as td:
        temp = Path(td)
        activation = extract_report(report_root / ACTIVATION_REPORT, ACTIVATION_SHA256, ACTIVATION_ROOT, temp / "a", "stage-150 activation evidence")
        rollback = extract_report(report_root / ROLLBACK_REPORT, ROLLBACK_SHA256, ROLLBACK_ROOT, temp / "r", "stage-150 rollback evidence")
        a = json.loads((activation / "SUMMARY.json").read_text(encoding="utf-8"))
        r = json.loads((rollback / "SUMMARY.json").read_text(encoding="utf-8"))
        require(a.get("profile_id") == FAILED_PROFILE_ID and a.get("observed_target_sha256") == FAILED_PROFILE_SHA256, "activation evidence profile drift")
        require(a.get("protected_archives_unchanged") is True, "activation protected-archive guard failed")
        require(r.get("exact_pack10_02_baseline_restored") is True and r.get("observed_target_sha256") == EXPECTED_BASELINE_SHA256, "rollback evidence baseline drift")
        require(r.get("protected_archives_unchanged") is True, "rollback protected-archive guard failed")
    return observation


def _endian(payload: bytes, label: str) -> str:
    require(len(payload) >= 4, f"truncated G1M: {label}")
    if payload[:4] == b"_M1G":
        return "<"
    if payload[:4] == b"G1M_":
        return ">"
    raise WetSchoolG1MGError(f"not a G1M payload: {label}")


def _name(raw: bytes) -> str:
    raw = raw.replace(b"\x00", b"")
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return raw.decode("cp932", errors="replace")


def _fmt_float(v: float) -> str:
    return format(v, ".9g")


def parse_g1mg_binding_metadata(payload: bytes, *, label: str = "<memory>") -> dict[str, Any]:
    """Parse bounded G1MG binding/material metadata without exporting buffers."""
    require(len(payload) >= G1M_HEADER_SIZE, f"G1M too small: {label}")
    e = _endian(payload, label)
    file_version, file_size, chunk_offset, reserved, chunk_count = struct.unpack_from(e + "5I", payload, 4)
    require(chunk_offset >= G1M_HEADER_SIZE and chunk_offset <= len(payload), f"unsafe chunk offset: {label}")
    require(chunk_count <= 0x1000, f"unsafe chunk count: {label}")
    require(not file_size or file_size <= len(payload), f"declared G1M size exceeds payload: {label}")

    g1mg_rows: list[tuple[int, int, bytes, int]] = []
    offset = chunk_offset
    for chunk_index in range(chunk_count):
        require(offset + 12 <= len(payload), f"truncated chunk header: {label}")
        magic = _name(payload[offset:offset+4])
        version, size = struct.unpack_from(e + "2I", payload, offset + 4)
        require(size >= 12 and offset + size <= len(payload), f"unsafe chunk size: {label}")
        if magic in {"GM1G", "G1MG"}:
            g1mg_rows.append((offset, size, payload[offset:offset+size], version))
        offset += size
    require(len(g1mg_rows) == 1, f"expected exactly one G1MG chunk: {label}")
    g1mg_abs, g1mg_size, chunk, g1mg_version = g1mg_rows[0]
    require(len(chunk) >= G1MG_HEADER_SIZE, f"G1MG too small: {label}")
    declared = struct.unpack_from(e + "I", chunk, 8)[0]
    require(declared == len(chunk), f"G1MG size mismatch: {label}")
    platform = _name(chunk[12:16])
    section_count = struct.unpack_from(e + "I", chunk, 44)[0]
    require(section_count <= 0x1000, f"unsafe G1MG section count: {label}")

    sections: list[dict[str, Any]] = []
    materials: list[dict[str, Any]] = []
    shader_params: list[dict[str, Any]] = []
    submeshes: list[dict[str, Any]] = []
    mesh_lod: list[dict[str, Any]] = []
    sec_off = G1MG_HEADER_SIZE
    for section_index in range(section_count):
        require(sec_off + 12 <= len(chunk), f"truncated G1MG section: {label}")
        stype, ssize, entries = struct.unpack_from(e + "3I", chunk, sec_off)
        require(ssize >= 12 and sec_off + ssize <= len(chunk), f"unsafe G1MG section size: {label}")
        send = sec_off + ssize
        cursor = sec_off + 12
        sections.append({
            "section_index": section_index, "section_type": f"0x{stype:08x}", "section_entries": entries,
            "section_offset": g1mg_abs + sec_off, "section_size": ssize,
            "section_sha256": sha256_bytes(chunk[sec_off:send]),
        })

        if stype == G1MG_MATERIALS:
            for material_index in range(entries):
                require(cursor + 16 <= send, f"truncated MATERIALS header: {label}")
                unknown1, texture_count, unknown2, unknown3 = struct.unpack_from(e + "4I", chunk, cursor)
                material_header_offset = g1mg_abs + cursor
                cursor += 16
                for texture_slot in range(texture_count):
                    require(cursor + 12 <= send, f"truncated MATERIALS texture: {label}")
                    vals = struct.unpack_from(e + "6H", chunk, cursor)
                    materials.append({
                        "material_index": material_index, "texture_slot": texture_slot,
                        "unknown1": unknown1, "texture_count": texture_count, "unknown2": unknown2, "unknown3": unknown3,
                        "texture_id": vals[0], "layer": vals[1], "texture_type": vals[2], "subtype": vals[3],
                        "tilemodex": vals[4], "tilemodey": vals[5],
                        "material_header_offset": material_header_offset, "texture_record_offset": g1mg_abs + cursor,
                    })
                    cursor += 12
        elif stype == G1MG_SHADER_PARAMS:
            for block_index in range(entries):
                require(cursor + 4 <= send, f"truncated SHADER_PARAMS block: {label}")
                parameter_count = struct.unpack_from(e + "I", chunk, cursor)[0]
                cursor += 4
                require(parameter_count <= 0x10000, f"unsafe SHADER_PARAMS count: {label}")
                duplicate_names: Counter[str] = Counter()
                for parameter_index in range(parameter_count):
                    pstart = cursor
                    require(cursor + 16 <= send, f"truncated SHADER_PARAMS record: {label}")
                    psize, name_size, unknown, buffer_type, buffer_count = struct.unpack_from(e + "3I2H", chunk, cursor)
                    cursor += 16
                    widths = {1: 4, 2: 8, 3: 12, 4: 16, 5: 4}
                    width = widths.get(buffer_type)
                    require(width is not None, f"unsupported shader buffer type {buffer_type}: {label}")
                    require(psize >= 16 + name_size + width * buffer_count, f"undersized shader param: {label}")
                    pend = pstart + psize
                    require(pend <= send, f"shader param exceeds section: {label}")
                    pname = _name(chunk[cursor:cursor+name_size])
                    cursor += name_size
                    value_off_local = cursor
                    raw = chunk[cursor:cursor + width * buffer_count]
                    vals: list[str] = []
                    for _ in range(buffer_count):
                        if buffer_type == 1:
                            vals.append(_fmt_float(struct.unpack_from(e + "f", chunk, cursor)[0]))
                        elif buffer_type == 2:
                            vals.append(",".join(_fmt_float(x) for x in struct.unpack_from(e + "2f", chunk, cursor)))
                        elif buffer_type == 3:
                            vals.append(",".join(_fmt_float(x) for x in struct.unpack_from(e + "3f", chunk, cursor)))
                        elif buffer_type == 4:
                            vals.append(",".join(_fmt_float(x) for x in struct.unpack_from(e + "4f", chunk, cursor)))
                        else:
                            vals.append(str(struct.unpack_from(e + "i", chunk, cursor)[0]))
                        cursor += width
                    folded = pname.casefold()
                    occurrence = duplicate_names[folded]
                    duplicate_names[folded] += 1
                    shader_params.append({
                        "shader_block_index": block_index, "parameter_index": parameter_index,
                        "parameter_name": pname, "parameter_name_folded": folded, "parameter_occurrence": occurrence,
                        "buffer_type": buffer_type, "buffer_count": buffer_count, "unknown": unknown,
                        "value_text": "|".join(vals), "value_hex": raw.hex(),
                        "parameter_record_offset": g1mg_abs + pstart, "value_offset": g1mg_abs + value_off_local,
                        "value_size": len(raw),
                    })
                    cursor = pend
        elif stype == G1MG_SUBMESH:
            fields = [
                "submeshFlags", "vertexBufferIndex", "bonePaletteIndex", "boneIndex", "unknown", "shaderParamIndex",
                "materialIndex", "indexBufferIndex", "unknown2", "indexBufferPrimType", "vertexBufferOffset", "vertexCount",
                "indexBufferOffset", "indexCount",
            ]
            for submesh_index in range(entries):
                require(cursor + 56 <= send, f"truncated SUBMESH: {label}")
                vals = struct.unpack_from(e + "14I", chunk, cursor)
                row = {"submesh_index": submesh_index, "record_offset": g1mg_abs + cursor}
                row.update(dict(zip(fields, vals)))
                submeshes.append(row)
                cursor += 56
        elif stype == G1MG_MESH_LOD:
            for block_index in range(entries):
                require(cursor + 4 <= send, f"truncated MESH_LOD block: {label}")
                lod = struct.unpack_from(e + "I", chunk, cursor)[0]; cursor += 4
                if g1mg_version > 0x30303330:
                    require(cursor + 8 <= send, f"truncated MESH_LOD group: {label}")
                    group, group_entry = struct.unpack_from(e + "2I", chunk, cursor); cursor += 8
                else:
                    group = group_entry = 0
                require(cursor + 8 <= send, f"truncated MESH_LOD counts: {label}")
                c1, c2 = struct.unpack_from(e + "2I", chunk, cursor); cursor += 8
                if g1mg_version > 0x30303340:
                    require(cursor + 16 <= send, f"truncated MESH_LOD range: {label}")
                    range_start, range_len, unknown1, unknown2 = struct.unpack_from(e + "4I", chunk, cursor); cursor += 16
                else:
                    range_start = range_len = unknown1 = unknown2 = 0
                total = c1 + c2
                require(total <= 0x10000, f"unsafe MESH_LOD entry count: {label}")
                for entry_index in range(total):
                    require(cursor + 28 <= send, f"truncated MESH_LOD entry: {label}")
                    entry_off = g1mg_abs + cursor
                    name = _name(chunk[cursor:cursor+16]); cursor += 16
                    cloth_id, unknown, nunid, index_count = struct.unpack_from(e + "2H2I", chunk, cursor); cursor += 12
                    require(index_count <= 0x10000, f"unsafe MESH_LOD index count: {label}")
                    if index_count:
                        require(cursor + 4 * index_count <= send, f"truncated MESH_LOD indices: {label}")
                        indices = list(struct.unpack_from(e + f"{index_count}I", chunk, cursor)); cursor += 4 * index_count
                    else:
                        require(cursor + 4 <= send, f"truncated MESH_LOD zero-count pad: {label}")
                        cursor += 4
                        indices = []
                    mesh_lod.append({
                        "block_index": block_index, "entry_index": entry_index, "record_offset": entry_off,
                        "lod": lod, "group": group, "group_entry_index": group_entry,
                        "submesh_count1": c1, "submesh_count2": c2, "lod_range_start": range_start,
                        "lod_range_length": range_len, "block_unknown1": unknown1, "block_unknown2": unknown2,
                        "name": name, "cloth_id": cloth_id, "unknown": unknown, "nunid": nunid,
                        "indices": indices,
                    })
        # Unknown / buffer-heavy sections are intentionally skipped by section size.
        sec_off = send

    return {
        "file_version": f"0x{file_version:08x}", "g1mg_version": f"0x{g1mg_version:08x}", "platform": platform,
        "g1mg_offset": g1mg_abs, "g1mg_size": g1mg_size,
        "sections": sections, "materials": materials, "shader_params": shader_params,
        "submeshes": submeshes, "mesh_lod": mesh_lod,
    }


def _canon(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def classify_four_way(sd: Any, sw: Any, td: Any, tw: Any) -> str:
    source_changed = sd != sw
    target_changed = td != tw
    if source_changed and not target_changed:
        return "original_wet_transition_missing_in_quartet_exact_base_control" if sd == td else "original_wet_transition_missing_in_quartet_base_differs"
    if source_changed and target_changed:
        if sd == td and sw == tw:
            return "matching_wet_transition"
        return "wet_transition_differs_between_games"
    if not source_changed and target_changed:
        return "quartet_only_wet_transition"
    return "dry_wet_identical_both_games"


def _unique_map(rows: Sequence[Mapping[str, Any]], key_fields: Sequence[str], label: str) -> dict[tuple[Any, ...], Mapping[str, Any]]:
    out: dict[tuple[Any, ...], Mapping[str, Any]] = {}
    for row in rows:
        key = tuple(row.get(f) for f in key_fields)
        require(key not in out, f"duplicate {label} key: {key}")
        out[key] = row
    return out


def analyze_role(role: str, variants: Mapping[str, dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    out: dict[str, list[dict[str, Any]]] = {"materials": [], "shader_params": [], "submeshes": [], "mesh_lod": []}
    names = ("source_dry", "source_wet", "target_dry", "target_wet")

    # MATERIALS texture assignments. Compare exact per material/texture slot.
    maps = {name: _unique_map(variants[name]["materials"], ("material_index", "texture_slot"), f"{role}:{name}:material") for name in names}
    for key in sorted(set().union(*(m.keys() for m in maps.values()))):
        rows = [maps[n].get(key) for n in names]
        if any(r is None for r in rows):
            values = [None if r is None else {k: r[k] for k in ("texture_id","layer","texture_type","subtype","tilemodex","tilemodey")} for r in rows]
        else:
            values = [{k: r[k] for k in ("texture_id","layer","texture_type","subtype","tilemodex","tilemodey")} for r in rows]  # type: ignore[index]
        cls = classify_four_way(*values)
        if cls != "dry_wet_identical_both_games":
            out["materials"].append({
                "normalized_member_role": role, "material_index": key[0], "texture_slot": key[1], "classification": cls,
                "source_dry": _canon(values[0]), "source_wet": _canon(values[1]), "target_dry": _canon(values[2]), "target_wet": _canon(values[3]),
                "exact_base_control": values[0] == values[2], "write_authorized": False,
            })

    # SHADER_PARAMS are compared by semantic signature. Direct scalar candidates
    # are only possible when the signature occurs exactly once in all four.
    grouped: dict[str, dict[tuple[str, int, int], list[Mapping[str, Any]]]] = {}
    for name in names:
        g: dict[tuple[str, int, int], list[Mapping[str, Any]]] = defaultdict(list)
        for row in variants[name]["shader_params"]:
            g[(str(row["parameter_name_folded"]), int(row["buffer_type"]), int(row["buffer_count"]))].append(row)
        grouped[name] = g
    signatures = set().union(*(g.keys() for g in grouped.values()))
    for sig in sorted(signatures):
        vals: list[list[str]] = []
        for name in names:
            vals.append(sorted(str(r["value_hex"]) for r in grouped[name].get(sig, [])))
        cls = classify_four_way(*vals)
        if cls == "dry_wet_identical_both_games":
            continue
        unique_all = all(len(grouped[name].get(sig, [])) == 1 for name in names)
        direct = bool(cls == "original_wet_transition_missing_in_quartet_exact_base_control" and unique_all)
        target_row = grouped["target_wet"].get(sig, [{}])[0] if grouped["target_wet"].get(sig) else {}
        source_wet_row = grouped["source_wet"].get(sig, [{}])[0] if grouped["source_wet"].get(sig) else {}
        out["shader_params"].append({
            "normalized_member_role": role, "parameter_name": sig[0], "buffer_type": sig[1], "buffer_count": sig[2],
            "classification": cls, "source_dry_values": ",".join(vals[0]), "source_wet_values": ",".join(vals[1]),
            "target_dry_values": ",".join(vals[2]), "target_wet_values": ",".join(vals[3]),
            "exact_base_control": vals[0] == vals[2], "unique_in_all_four": unique_all,
            "direct_scalar_probe_candidate": direct,
            "target_wet_shader_block_index": target_row.get("shader_block_index", ""),
            "target_wet_parameter_index": target_row.get("parameter_index", ""),
            "target_wet_value_offset": target_row.get("value_offset", ""),
            "target_before_hex": target_row.get("value_hex", ""),
            "original_wet_desired_hex": source_wet_row.get("value_hex", "") if direct else "",
            "semantics_confirmed": False, "write_authorized": False,
        })

    # SUBMESH: restrict transition value to material/shader-param binding only.
    maps = {name: _unique_map(variants[name]["submeshes"], ("submesh_index",), f"{role}:{name}:submesh") for name in names}
    for key in sorted(set().union(*(m.keys() for m in maps.values()))):
        values = []
        for n in names:
            row = maps[n].get(key)
            values.append(None if row is None else {"shaderParamIndex": row["shaderParamIndex"], "materialIndex": row["materialIndex"]})
        cls = classify_four_way(*values)
        if cls != "dry_wet_identical_both_games":
            out["submeshes"].append({
                "normalized_member_role": role, "submesh_index": key[0], "classification": cls,
                "source_dry": _canon(values[0]), "source_wet": _canon(values[1]), "target_dry": _canon(values[2]), "target_wet": _canon(values[3]),
                "exact_base_control": values[0] == values[2], "write_authorized": False,
            })

    # MESH_LOD: compare shader name and submesh index list per block/entry.
    maps = {name: _unique_map(variants[name]["mesh_lod"], ("block_index", "entry_index"), f"{role}:{name}:mesh_lod") for name in names}
    for key in sorted(set().union(*(m.keys() for m in maps.values()))):
        values = []
        for n in names:
            row = maps[n].get(key)
            values.append(None if row is None else {"name": row["name"], "indices": row["indices"], "cloth_id": row["cloth_id"], "nunid": row["nunid"]})
        cls = classify_four_way(*values)
        if cls != "dry_wet_identical_both_games":
            source_wet_name = (values[1] or {}).get("name", "") if isinstance(values[1], dict) else ""
            target_names = {str(r.get("name", "")) for r in variants["target_wet"]["mesh_lod"]}
            out["mesh_lod"].append({
                "normalized_member_role": role, "block_index": key[0], "entry_index": key[1], "classification": cls,
                "source_dry": _canon(values[0]), "source_wet": _canon(values[1]), "target_dry": _canon(values[2]), "target_wet": _canon(values[3]),
                "exact_base_control": values[0] == values[2],
                "source_wet_shader_name_present_in_target_wet": bool(source_wet_name and source_wet_name in target_names),
                "write_authorized": False,
            })
    return out


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

    observation = validate_runtime_failure(report_root)
    br = load_module(project_root / "Blue_Reflection_Text_Tool/br_restoration_tool.py", "stage151_br")
    stage125 = load_module(project_root / "workstreams/quartet_restoration/125_collect_character_state_exact_rehydration_evidence.py", "stage151_stage125")
    inventories = stage125.load_asset_inventories(project_root)
    extraction_rows = stage125.ensure_extraction_cache(
        project_root=project_root, workspace_root=workspace_root, inventories=inventories,
        required_paths=[DRY_ARCHIVE, WET_ARCHIVE], original_root=original_root, quartet_root=quartet_root,
        gust_pak_path=gust_pak_path, br=br, timeout_seconds=timeout_seconds,
    )

    archives: dict[tuple[str, str], dict[str, Any]] = {}
    input_rows: list[dict[str, Any]] = []
    for side in ("source", "target"):
        for state, normalized in ((DRY_STATE, DRY_ARCHIVE), (WET_STATE, WET_ARCHIVE)):
            pair_id, entry = inventories[(side, normalized.casefold())]
            local = br.inventory_workspace_file(workspace_root, side, pair_id, str(entry["archive"]), str(entry["path"]))
            require(local.is_file(), f"missing extracted input: {side} {normalized}: {local}")
            actual = sha256_file(local)
            if verify_payload_hashes:
                require(actual == str(entry["sha256"]), f"payload hash drift: {side} {normalized}: {actual}")
            progress(f"reading {side} {state}: {normalized}")
            parsed = br.read_earc_archive(local, maximum_bytes=MAX_EARC_BYTES, include_member_payloads=True)
            archives[(side, state)] = parsed
            input_rows.append({
                "side": side, "state_token": state, "archive_path": normalized, "input_sha256": actual,
                "input_size": local.stat().st_size, "decoded_bytes": parsed["decoded_bytes"], "member_count": parsed["file_count"],
                "payload_in_evidence": False,
            })

    role_members: dict[tuple[str, str], dict[str, Mapping[str, Any]]] = {}
    all_roles: set[str] = set()
    for side in ("source", "target"):
        for state in (DRY_STATE, WET_STATE):
            role_map: dict[str, Mapping[str, Any]] = {}
            for member in archives[(side, state)]["members"]:
                if str(member.get("extension", "")).casefold() != ".g1m": continue
                role = stage125.normalized_role(str(member["name"]), CHARACTER_ID, state)
                require(role not in role_map, f"duplicate normalized G1M role {side}:{state}:{role}")
                role_map[role] = member
                all_roles.add(role)
            role_members[(side, state)] = role_map

    role_rows: list[dict[str, Any]] = []
    section_rows: list[dict[str, Any]] = []
    material_rows: list[dict[str, Any]] = []
    shader_rows: list[dict[str, Any]] = []
    submesh_rows: list[dict[str, Any]] = []
    lod_rows: list[dict[str, Any]] = []
    parse_skips: list[dict[str, Any]] = []

    for role in sorted(all_roles):
        keys = [("source", DRY_STATE), ("source", WET_STATE), ("target", DRY_STATE), ("target", WET_STATE)]
        members = [role_members[k].get(role) for k in keys]
        complete = all(m is not None for m in members)
        role_rows.append({
            "normalized_member_role": role,
            "source_dry_present": members[0] is not None, "source_wet_present": members[1] is not None,
            "target_dry_present": members[2] is not None, "target_wet_present": members[3] is not None,
            "four_way_control_complete": complete,
            "disposition": "analyze_four_way" if complete else "incomplete_role_control_no_write",
        })
        if not complete: continue
        labels = ("source_dry", "source_wet", "target_dry", "target_wet")
        parsed_variants: dict[str, dict[str, Any]] = {}
        failed = False
        for label_name, member in zip(labels, members):
            assert member is not None
            try:
                parsed = parse_g1mg_binding_metadata(member["payload"], label=f"{role}:{label_name}:{member['name']}")
                parsed_variants[label_name] = parsed
                for row in parsed["sections"]:
                    section_rows.append({"normalized_member_role": role, "variant": label_name, **row})
            except Exception as exc:
                failed = True
                parse_skips.append({"normalized_member_role": role, "variant": label_name, "member_name": member["name"], "reason": f"{type(exc).__name__}:{exc}", "write_authorized": False})
        if failed: continue
        analysis = analyze_role(role, parsed_variants)
        material_rows.extend(analysis["materials"]); shader_rows.extend(analysis["shader_params"])
        submesh_rows.extend(analysis["submeshes"]); lod_rows.extend(analysis["mesh_lod"])

    exact_shader_candidates = [r for r in shader_rows if r["direct_scalar_probe_candidate"]]
    exact_material = [r for r in material_rows if r["classification"] == "original_wet_transition_missing_in_quartet_exact_base_control"]
    exact_submesh = [r for r in submesh_rows if r["classification"] == "original_wet_transition_missing_in_quartet_exact_base_control"]
    exact_lod = [r for r in lod_rows if r["classification"] == "original_wet_transition_missing_in_quartet_exact_base_control"]

    write_tsv(output / "INPUTS.tsv", ["side","state_token","archive_path","input_sha256","input_size","decoded_bytes","member_count","payload_in_evidence"], input_rows)
    write_tsv(output / "ROLE_COVERAGE.tsv", ["normalized_member_role","source_dry_present","source_wet_present","target_dry_present","target_wet_present","four_way_control_complete","disposition"], role_rows)
    write_tsv(output / "G1MG_SECTIONS.tsv", ["normalized_member_role","variant","section_index","section_type","section_entries","section_offset","section_size","section_sha256"], section_rows)
    write_tsv(output / "MATERIAL_TEXTURE_TRANSITIONS.tsv", ["normalized_member_role","material_index","texture_slot","classification","source_dry","source_wet","target_dry","target_wet","exact_base_control","write_authorized"], material_rows)
    write_tsv(output / "SHADER_PARAMETER_TRANSITIONS.tsv", ["normalized_member_role","parameter_name","buffer_type","buffer_count","classification","source_dry_values","source_wet_values","target_dry_values","target_wet_values","exact_base_control","unique_in_all_four","direct_scalar_probe_candidate","target_wet_shader_block_index","target_wet_parameter_index","target_wet_value_offset","target_before_hex","original_wet_desired_hex","semantics_confirmed","write_authorized"], shader_rows)
    write_tsv(output / "SUBMESH_BINDING_TRANSITIONS.tsv", ["normalized_member_role","submesh_index","classification","source_dry","source_wet","target_dry","target_wet","exact_base_control","write_authorized"], submesh_rows)
    write_tsv(output / "MESH_LOD_BINDING_TRANSITIONS.tsv", ["normalized_member_role","block_index","entry_index","classification","source_dry","source_wet","target_dry","target_wet","exact_base_control","source_wet_shader_name_present_in_target_wet","write_authorized"], lod_rows)
    write_tsv(output / "PARSE_SKIPPED.tsv", ["normalized_member_role","variant","member_name","reason","write_authorized"], parse_skips)
    write_tsv(output / "FAILED_G1MM_TRANSPLANT_GUARD.tsv", ["profile_id","profile_sha256","activation_evidence_sha256","rollback_evidence_sha256","runtime_result","whole_g1mm_reuse_forbidden","exact_baseline_restored"], [{
        "profile_id": FAILED_PROFILE_ID, "profile_sha256": FAILED_PROFILE_SHA256,
        "activation_evidence_sha256": ACTIVATION_SHA256, "rollback_evidence_sha256": ROLLBACK_SHA256,
        "runtime_result": "severe_model_corruption_without_crash", "whole_g1mm_reuse_forbidden": True,
        "exact_baseline_restored": True,
    }])

    summary = {
        "type": "br_quartet_restoration_hinako_wet_school_g1mg_binding_differential_evidence_summary",
        "format_version": 1, "tool_version": TOOL_VERSION,
        "status": "stage150_failed_g1mm_transplant_canonicalized_four_way_g1mg_binding_audit_complete_no_write",
        "stage150_activation_evidence_sha256": ACTIVATION_SHA256,
        "stage150_rollback_evidence_sha256": ROLLBACK_SHA256,
        "stage150_exact_pack10_02_baseline_restored": True,
        "stage150_severe_model_corruption_observed": True,
        "whole_g1mm_transplant_reuse_forbidden": True,
        "four_way_role_rows": len(role_rows),
        "complete_four_way_role_rows": sum(r["four_way_control_complete"] for r in role_rows),
        "parse_skip_rows": len(parse_skips),
        "material_transition_rows": len(material_rows),
        "shader_parameter_transition_rows": len(shader_rows),
        "submesh_binding_transition_rows": len(submesh_rows),
        "mesh_lod_binding_transition_rows": len(lod_rows),
        "exact_base_control_material_rows": len(exact_material),
        "exact_base_control_direct_scalar_probe_rows": len(exact_shader_candidates),
        "exact_base_control_submesh_rows": len(exact_submesh),
        "exact_base_control_mesh_lod_rows": len(exact_lod),
        "runtime_validated": False, "production_eligible": False,
        "policy": {
            "existing_runtime_failure_preserved": True,
            "whole_g1mm_transplant_authorized": False,
            "g1mg_complete_chunk_transplant_authorized": False,
            "direct_scalar_rows_are_candidates_only": True,
            "texture_binding_rows_require_dependency_validation": True,
            "submesh_binding_rows_require_index_compatibility_validation": True,
            "mesh_lod_rows_require_shader_dependency_validation": True,
            "wet_skin_droplet_binding_inferred": False,
            "blouse_transparency_semantics_inferred": False,
            "installed_game_modified": False,
            "pak_repacked": False,
            "core_modified": False, "translation_modified": False, "legacy_dlc_modified": False, "git_modified": False,
            "proprietary_payloads_in_evidence": False,
        },
        "next_action": "Review exact-base-control G1MG rows. Build at most one minimal target-native probe from an exact target locator after dependency/index checks; do not transplant G1MM or a complete G1MG chunk again.",
    }
    (output / "SUMMARY.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    write_tsv(output / "EXTRACTION_INPUTS.tsv", sorted({k for r in extraction_rows for k in r.keys()}), extraction_rows)

    # Fail closed if a proprietary payload was accidentally written to evidence.
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
            print(f"[stage151] report archive: {archive}")
            print(f"[stage151] SHA-256: {sha256_file(archive)}")
        return 0
    except WetSchoolG1MGError as exc:
        print(f"[stage151] ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
