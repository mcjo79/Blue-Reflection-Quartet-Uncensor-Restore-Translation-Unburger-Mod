#!/usr/bin/env python3
"""Stage 155: read-only Hinako wet texture-entry differential audit.

Stage 154 proved that all ten Original wet material texture fingerprints are
preserved and used in Quartet wet, but none of the actually used shader blocks
can be aligned safely by schema.  This stage moves one layer down to the G1T
texture packs themselves.  It parses texture-entry boundaries and metadata for
Hinako's dry/wet naked, school and swim texture packs plus the wet-associated
school sibling pack, hashes every raw texture entry and payload, and records:

* the three exact school wet texture-id transitions already established by the
  G1MG evidence (dry 24/26/30 -> wet 21/23/27);
* whether those source/target entries are structurally compatible enough even
  to consider a later per-entry experiment;
* payload families shared across multiple wet packs but absent from dry packs,
  which are useful static candidates for a common wet-skin/droplet layer.

No G1T, G1M, PAK or installed-game payload is modified or exported.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import importlib.util
import json
import os
import struct
import subprocess
import sys
import tempfile
from collections import defaultdict
from pathlib import Path, PurePosixPath
from typing import Any, Iterable, Mapping, Sequence

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT_DEFAULT = SCRIPT_DIR.parent.parent
TOOL_VERSION = "0.1.73"
REPORT_DIR = "hinako_wet_texture_entry_differential_evidence"
REPORT_NAME = "BR_quartet_restoration_hinako_wet_texture_entry_differential_evidence.tar.zst"
WORKSPACE_SUBDIR = Path("hinako_wet_texture_entry_differential")

STAGE154_REPORT = "BR_quartet_restoration_hinako_wet_school_shader_schema_material_usage_evidence.tar.zst"
STAGE154_SHA256 = "caf47bbe9d7485f9545e089a01c6a159bdea9ce715dc6ec5720329c2c99a63c8"
STAGE154_ROOT = "hinako_wet_school_shader_schema_material_usage_evidence"
STAGE153_SHA256 = "301bc4b6137dd9a6af756185ab4727ad6f09ef19eb97c6f5583f0ac60dd2e877"

PACKS: tuple[tuple[str, str], ...] = (
    ("nkd", "data/x64/character/pc00/pc00_nkd.g1t"),
    ("nkd_w", "data/x64/character/pc00/pc00_nkd_w.g1t"),
    ("scl", "data/x64/character/pc00/pc00_scl.g1t"),
    ("scl_w", "data/x64/character/pc00/pc00_scl_w.g1t"),
    ("scl_wh", "data/x64/character/pc00/pc00_scl_wh.g1t"),
    ("swm", "data/x64/character/pc00/pc00_swm.g1t"),
    ("swm_w", "data/x64/character/pc00/pc00_swm_w.g1t"),
)
DRY_TOKENS = {"nkd", "scl", "swm"}
WET_TOKENS = {"nkd_w", "scl_w", "scl_wh", "swm_w"}

# Exact texture-id changes from stage 151 / source wet material 3 and the
# stage-153-preserved target wet material 4.  These are identifiers only, not
# semantic labels.
FOCUS_TRANSITIONS = (
    {"texture_slot": 4, "dry_texture_id": 24, "wet_texture_id": 21},
    {"texture_slot": 5, "dry_texture_id": 26, "wet_texture_id": 23},
    {"texture_slot": 6, "dry_texture_id": 30, "wet_texture_id": 27},
)

FORBIDDEN_REPORT_EXTENSIONS = (
    ".pak", ".g1m", ".g1t", ".g1s", ".g1e", ".g1em", ".elixir", ".elixir.gz", ".ebd", ".ebm", ".kps", ".dds"
)

G1TG_MAGIC = 0x47315447
FLAG_EXTENDED_DATA = 0x1
FLAG_DOUBLE_HEIGHT = 0x001000000000


class WetTextureAuditError(RuntimeError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise WetTextureAuditError(message)


def progress(message: str) -> None:
    print(f"[stage155] {message}", flush=True)


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


def extract_report(archive: Path, expected_sha256: str, expected_root: str, destination: Path) -> Path:
    require(archive.is_file(), f"missing prerequisite report: {archive}")
    actual = sha256_file(archive)
    require(actual == expected_sha256, f"stage-154 evidence SHA-256 drift: {actual}")
    cp = subprocess.run(["tar", "--zstd", "-tf", str(archive)], text=True, capture_output=True)
    require(cp.returncode == 0, cp.stderr.strip() or "cannot list stage-154 evidence")
    names = [safe_relative(x.strip(), "stage-154 member") for x in cp.stdout.splitlines() if x.strip()]
    require(names and {PurePosixPath(x).parts[0] for x in names} == {expected_root}, "unexpected stage-154 archive root")
    require(not any(x.casefold().endswith(FORBIDDEN_REPORT_EXTENSIONS) for x in names), "proprietary payload in stage-154 evidence")
    destination.mkdir(parents=True, exist_ok=True)
    cp = subprocess.run(["tar", "--zstd", "-xf", str(archive), "-C", str(destination)], text=True, capture_output=True)
    require(cp.returncode == 0, cp.stderr.strip() or "cannot extract stage-154 evidence")
    return destination / expected_root


def validate_stage154(report_root: Path) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="stage155-prereq-") as td:
        root = extract_report(report_root / STAGE154_REPORT, STAGE154_SHA256, STAGE154_ROOT, Path(td))
        summary = json.loads((root / "SUMMARY.json").read_text(encoding="utf-8"))
        require(summary.get("tool_version") == "0.1.72", "stage-154 version drift")
        require(summary.get("stage153_evidence_sha256") == STAGE153_SHA256, "stage-153 chain drift")
        require(summary.get("material_usage_rows") == 10, "stage-154 material usage count drift")
        require(summary.get("used_source_material_rows") == 10 and summary.get("used_target_material_rows") == 10, "stage-154 material-use drift")
        require(summary.get("focus_source_material_index") == 3 and summary.get("focus_target_material_index") == 4, "stage-154 focus material drift")
        require(summary.get("focus_texture_triplet") == ["21:29:0", "23:3:0", "27:57:57"], "stage-154 focus texture triplet drift")
        require(summary.get("unique_target_material_scoped_schema_rows") == 0, "stage-154 shader-schema result drift")
        require(summary.get("parameter_comparison_rows") == 0, "stage-154 unexpectedly has parameter comparisons")
        require(summary.get("bounded_scalar_candidate_rows") == 0, "stage-154 unexpectedly has scalar candidates")
        require(summary.get("parse_skip_rows") == 0, "stage-154 parse skips drift")
        require(summary.get("runtime_validated") is False and summary.get("production_eligible") is False, "stage-154 promotion drift")
        policy = summary.get("policy", {})
        require(policy.get("scalar_write_authorized") is False, "stage-154 scalar write unexpectedly authorized")
        require(policy.get("whole_g1mm_transplant_reuse_forbidden") is True, "failed whole-G1MM guard missing")
        require(policy.get("installed_game_modified") is False and policy.get("pak_repacked") is False, "stage-154 write policy drift")
        return summary


def _u32(data: bytes, offset: int, endian: str) -> int:
    require(offset + 4 <= len(data), f"truncated u32 at 0x{offset:x}")
    return struct.unpack_from(endian + "I", data, offset)[0]


def _version_string(value: int) -> str:
    raw = value.to_bytes(4, "big", signed=False)
    return raw.decode("ascii", errors="replace").rstrip("\x00")


def parse_g1t(data: bytes, label: str) -> dict[str, Any]:
    require(len(data) >= 28, f"{label}: truncated G1T header")
    magic_le = struct.unpack_from("<I", data, 0)[0]
    magic_be = struct.unpack_from(">I", data, 0)[0]
    if magic_le == G1TG_MAGIC:
        endian = "<"
        byte_order = "little"
    elif magic_be == G1TG_MAGIC:
        endian = ">"
        byte_order = "big"
    else:
        raise WetTextureAuditError(f"{label}: bad G1T magic {data[:4]!r}")

    magic, version, total_size, header_size, nb_textures, platform, extra_size = struct.unpack_from(endian + "7I", data, 0)
    require(magic == G1TG_MAGIC, f"{label}: normalized magic drift")
    require(total_size == len(data), f"{label}: total_size mismatch header={total_size} actual={len(data)}")
    require(0 < nb_textures < 100000, f"{label}: unreasonable texture count {nb_textures}")
    require(28 + 4 * nb_textures <= len(data), f"{label}: global flag table truncated")
    require(header_size + 4 * nb_textures <= len(data), f"{label}: offset table truncated")
    require(extra_size <= len(data), f"{label}: unreasonable extra_size")

    global_flags = [_u32(data, 28 + 4 * i, endian) for i in range(nb_textures)]
    offsets = [_u32(data, header_size + 4 * i, endian) for i in range(nb_textures)]
    require(offsets == sorted(offsets), f"{label}: texture offsets are not monotonic")

    entries: list[dict[str, Any]] = []
    for i in range(nb_textures):
        start = header_size + offsets[i]
        end = header_size + (offsets[i + 1] if i + 1 < nb_textures else total_size - header_size)
        require(start + 8 <= end <= len(data), f"{label}: invalid entry bounds for texture {i}: 0x{start:x}-0x{end:x}")
        entry = data[start:end]
        b0, tex_type, b2 = entry[0], entry[1], entry[2]
        if endian == "<":
            z_mipmaps = b0 & 0x0F
            mipmaps = (b0 >> 4) & 0x0F
            dx = b2 & 0x0F
            dy = (b2 >> 4) & 0x0F
            flag_bytes = [((b >> 4) | ((b & 0x0F) << 4)) for b in entry[3:8]]
        else:
            z_mipmaps = (b0 >> 4) & 0x0F
            mipmaps = b0 & 0x0F
            dx = (b2 >> 4) & 0x0F
            dy = b2 & 0x0F
            flag_bytes = list(entry[3:8])
        require(mipmaps > 0, f"{label}: texture {i} has zero mipmaps")
        flags0 = int(global_flags[i])
        for b in flag_bytes:
            flags0 = (flags0 << 8) | b
        width = 1 << dx
        height = 1 << dy
        if flags0 & FLAG_DOUBLE_HEIGHT:
            height *= 2
        data_size = 0
        depth_bits = 0
        extra_flags = 0
        if flags0 & FLAG_EXTENDED_DATA:
            require(len(entry) >= 12, f"{label}: texture {i} extended-data header truncated")
            data_size = _u32(entry, 8, endian)
            require(data_size in (0x0C, 0x10, 0x14), f"{label}: texture {i} unsupported extra data size 0x{data_size:x}")
            require(8 + data_size <= len(entry), f"{label}: texture {i} extended data truncated")
            if data_size >= 0x0C:
                depth_bits = _u32(entry, 12, endian)
                extra_flags = int.from_bytes(entry[16:20], "big") if len(entry) >= 20 else 0
            if data_size >= 0x10:
                width = _u32(entry, 20, endian)
            if data_size >= 0x14:
                height = _u32(entry, 24, endian)
        payload_offset = 8 + data_size
        require(payload_offset <= len(entry), f"{label}: texture {i} payload offset beyond entry")
        payload = entry[payload_offset:]
        entries.append({
            "texture_index": i,
            "entry_offset": start,
            "entry_size": len(entry),
            "payload_offset_in_entry": payload_offset,
            "payload_size": len(payload),
            "texture_type": tex_type,
            "mipmaps": mipmaps,
            "z_mipmaps": z_mipmaps,
            "width": width,
            "height": height,
            "global_flag_word": global_flags[i],
            "flags_combined_hex": f"{flags0:026x}",
            "extra_data_size": data_size,
            "depth_bits_hex": f"{depth_bits:08x}",
            "extra_flags_hex": f"{extra_flags:08x}",
            "raw_entry_sha256": sha256_bytes(entry),
            "payload_sha256": sha256_bytes(payload),
        })

    return {
        "magic_ascii": data[:4].decode("ascii", errors="replace"),
        "byte_order": byte_order,
        "version_u32": version,
        "version_string": _version_string(version),
        "total_size": total_size,
        "header_size": header_size,
        "texture_count": nb_textures,
        "platform": platform,
        "extra_size": extra_size,
        "entries": entries,
    }


def entry_shape(row: Mapping[str, Any]) -> tuple[Any, ...]:
    return (
        int(row["texture_type"]), int(row["mipmaps"]), int(row["z_mipmaps"]),
        int(row["width"]), int(row["height"]), int(row["payload_size"]),
        str(row["flags_combined_hex"]), int(row["extra_data_size"]), str(row["depth_bits_hex"]), str(row["extra_flags_hex"]),
    )


def build_shared_wet_families(all_entries: Sequence[Mapping[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    by_side_hash: dict[tuple[str, str], list[Mapping[str, Any]]] = defaultdict(list)
    dry_hashes: dict[str, set[str]] = defaultdict(set)
    for row in all_entries:
        side = str(row["side"]); token = str(row["state_token"]); h = str(row["payload_sha256"])
        if token in DRY_TOKENS:
            dry_hashes[side].add(h)
        if token in WET_TOKENS:
            by_side_hash[(side, h)].append(row)

    families: list[dict[str, Any]] = []
    source_wet_only: list[dict[str, Any]] = []
    for (side, h), rows in sorted(by_side_hash.items()):
        tokens = sorted({str(r["state_token"]) for r in rows})
        if len(tokens) < 2:
            continue
        locations = sorted(f"{r['state_token']}:{r['texture_index']}" for r in rows)
        wet_only = h not in dry_hashes[side]
        row = {
            "side": side,
            "payload_sha256": h,
            "wet_pack_count": len(tokens),
            "wet_packs": ",".join(tokens),
            "entry_rows": len(rows),
            "locations": ",".join(locations),
            "present_in_same_side_dry_packs": not wet_only,
            "wet_only_shared_payload_family": wet_only,
            "semantics_confirmed": False,
            "write_authorized": False,
        }
        families.append(row)
        if side == "source" and wet_only:
            source_wet_only.append(row)
    return families, source_wet_only


def audit_source_wet_only_target_positions(source_families: Sequence[Mapping[str, Any]], entry_lookup: Mapping[tuple[str, str, int], Mapping[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for fam in source_families:
        locs: list[tuple[str, int]] = []
        for loc in str(fam["locations"]).split(","):
            token, idx_s = loc.rsplit(":", 1)
            locs.append((token, int(idx_s)))
        target_rows = [entry_lookup.get(("target", token, idx)) for token, idx in locs]
        target_present = all(r is not None for r in target_rows)
        target_hashes = [str(r["payload_sha256"]) for r in target_rows if r is not None]
        target_shared = target_present and len(set(target_hashes)) == 1 and len(target_hashes) >= 2
        shape_consistent = False
        if target_present and target_rows:
            shapes = [entry_shape(r) for r in target_rows if r is not None]
            shape_consistent = len(set(shapes)) == 1
        out.append({
            "source_payload_sha256": fam["payload_sha256"],
            "source_wet_packs": fam["wet_packs"],
            "source_locations": fam["locations"],
            "target_same_indices_all_present": target_present,
            "target_same_indices_payload_hashes": ",".join(target_hashes),
            "target_same_indices_still_exactly_shared": target_shared,
            "target_same_indices_structurally_uniform": shape_consistent,
            "candidate_common_wet_layer": bool(target_present and not target_shared),
            "wet_skin_or_droplet_semantics_confirmed": False,
            "write_authorized": False,
        })
    return out


def validate_with_gust_g1t(gust_g1t: Path, path: Path, timeout_seconds: int = 120) -> tuple[str, int]:
    if not gust_g1t.is_file():
        return "not_available", 0
    try:
        cp = subprocess.run([str(gust_g1t), "-l", str(path)], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=timeout_seconds)
    except subprocess.TimeoutExpired:
        return "timeout", 0
    if cp.returncode != 0:
        return f"error_{cp.returncode}", 0
    lines = [x for x in cp.stdout.splitlines() if x.startswith("0x")]
    return "ok", len(lines)


def build_report(
    project_root: Path,
    *,
    report_root: Path | None = None,
    output_report_root: Path | None = None,
    workspace_root: Path | None = None,
    original_root: Path | None = None,
    quartet_root: Path | None = None,
    gust_pak_path: Path | None = None,
    verify_payload_hashes: bool = True,
    create_archive: bool = True,
    timeout_seconds: int = 1800,
) -> tuple[Path | None, dict[str, Any]]:
    project_root = project_root.resolve()
    report_root = (report_root or (project_root / ".local/reports/quartet_restoration")).resolve()
    output_report_root = (output_report_root or report_root).resolve()
    workspace_root = (workspace_root or (project_root / ".local/workspaces/quartet_restoration" / WORKSPACE_SUBDIR)).resolve()
    output = output_report_root / REPORT_DIR
    archive = output_report_root / REPORT_NAME
    if output.exists():
        import shutil
        shutil.rmtree(output)
    output.mkdir(parents=True, exist_ok=True)

    validate_stage154(report_root)
    progress("stage-154 prerequisite verified; collecting seven Hinako G1T texture packs per side")

    br = load_module(project_root / "Blue_Reflection_Text_Tool/br_restoration_tool.py", "stage155_br")
    stage125 = load_module(project_root / "workstreams/quartet_restoration/125_collect_character_state_exact_rehydration_evidence.py", "stage155_stage125")
    inventories = stage125.load_asset_inventories(project_root)
    required = [path for _, path in PACKS]
    extraction_rows = stage125.ensure_extraction_cache(
        project_root=project_root, workspace_root=workspace_root, inventories=inventories,
        required_paths=required, original_root=original_root, quartet_root=quartet_root,
        gust_pak_path=gust_pak_path, br=br, timeout_seconds=timeout_seconds,
    )

    gust_g1t = project_root / ".local/vendor/gust_tools/gust_g1t"
    input_rows: list[dict[str, Any]] = []
    container_rows: list[dict[str, Any]] = []
    entry_rows: list[dict[str, Any]] = []
    parsed: dict[tuple[str, str], dict[str, Any]] = {}
    parse_skips: list[dict[str, Any]] = []

    for side in ("source", "target"):
        for token, normalized in PACKS:
            pair_id, entry = inventories[(side, normalized.casefold())]
            local = br.inventory_workspace_file(workspace_root, side, pair_id, str(entry["archive"]), str(entry["path"]))
            require(local.is_file(), f"missing extracted G1T input: {side} {normalized}: {local}")
            actual = sha256_file(local)
            if verify_payload_hashes:
                require(actual == str(entry["sha256"]), f"payload hash drift: {side} {normalized}: {actual}")
            progress(f"parsing {side} {token}: {normalized}")
            try:
                g = parse_g1t(local.read_bytes(), f"{side}:{token}")
                parsed[(side, token)] = g
                gust_status, gust_count = validate_with_gust_g1t(gust_g1t, local)
                require(gust_status in {"ok", "not_available"}, f"gust_g1t list validation failed: {side}:{token}:{gust_status}")
                if gust_status == "ok":
                    require(gust_count == g["texture_count"], f"gust_g1t texture-count mismatch: {side}:{token}: {gust_count}!={g['texture_count']}")
                container_rows.append({
                    "side": side, "state_token": token, "normalized_path": normalized,
                    "version_string": g["version_string"], "byte_order": g["byte_order"], "platform": g["platform"],
                    "container_size": g["total_size"], "header_size": g["header_size"], "extra_size": g["extra_size"],
                    "texture_count": g["texture_count"], "gust_g1t_list_status": gust_status, "gust_g1t_list_texture_rows": gust_count,
                    "payload_in_evidence": False,
                })
                for er in g["entries"]:
                    entry_rows.append({"side": side, "state_token": token, "normalized_path": normalized, **er, "payload_in_evidence": False})
            except Exception as exc:
                parse_skips.append({"side": side, "state_token": token, "normalized_path": normalized, "reason": f"{type(exc).__name__}:{exc}", "write_authorized": False})
            input_rows.append({
                "side": side, "state_token": token, "normalized_path": normalized,
                "archive": entry["archive"], "inventory_path": entry["path"], "input_sha256": actual,
                "input_size": local.stat().st_size, "payload_in_evidence": False,
            })

    require(not parse_skips, f"G1T parser skipped {len(parse_skips)} inputs")
    entry_lookup = {(str(r["side"]), str(r["state_token"]), int(r["texture_index"])): r for r in entry_rows}

    focus_rows: list[dict[str, Any]] = []
    for tr in FOCUS_TRANSITIONS:
        dry_id = int(tr["dry_texture_id"]); wet_id = int(tr["wet_texture_id"])
        sd = entry_lookup.get(("source", "scl", dry_id)); sw = entry_lookup.get(("source", "scl_w", wet_id))
        td = entry_lookup.get(("target", "scl", dry_id)); tw = entry_lookup.get(("target", "scl_w", wet_id))
        require(all(x is not None for x in (sd, sw, td, tw)), f"focus texture index out of range: slot {tr['texture_slot']}")
        assert sd is not None and sw is not None and td is not None and tw is not None
        source_transition_differs = sd["payload_sha256"] != sw["payload_sha256"]
        target_transition_differs = td["payload_sha256"] != tw["payload_sha256"]
        wet_shape_compatible = entry_shape(sw) == entry_shape(tw)
        dry_shape_compatible = entry_shape(sd) == entry_shape(td)
        direct_entry_candidate = bool(wet_shape_compatible and sw["payload_size"] == tw["payload_size"] and sw["texture_type"] == tw["texture_type"])
        focus_rows.append({
            "texture_slot": tr["texture_slot"], "dry_texture_id": dry_id, "wet_texture_id": wet_id,
            "source_dry_payload_sha256": sd["payload_sha256"], "source_wet_payload_sha256": sw["payload_sha256"],
            "target_dry_payload_sha256": td["payload_sha256"], "target_wet_payload_sha256": tw["payload_sha256"],
            "source_dry_shape": json.dumps(entry_shape(sd), separators=(",", ":")),
            "source_wet_shape": json.dumps(entry_shape(sw), separators=(",", ":")),
            "target_dry_shape": json.dumps(entry_shape(td), separators=(",", ":")),
            "target_wet_shape": json.dumps(entry_shape(tw), separators=(",", ":")),
            "source_dry_to_wet_payload_differs": source_transition_differs,
            "target_dry_to_wet_payload_differs": target_transition_differs,
            "source_target_dry_entry_shape_exact": dry_shape_compatible,
            "source_target_wet_entry_shape_exact": wet_shape_compatible,
            "source_target_wet_payload_exact": sw["payload_sha256"] == tw["payload_sha256"],
            "direct_raw_entry_transplant_structurally_bounded": direct_entry_candidate,
            "transparency_or_droplet_semantics_confirmed": False,
            "write_authorized": False,
        })

    shared_rows, source_wet_only = build_shared_wet_families(entry_rows)
    source_wet_only_target_rows = audit_source_wet_only_target_positions(source_wet_only, entry_lookup)

    fields_input = ["side","state_token","normalized_path","archive","inventory_path","input_sha256","input_size","payload_in_evidence"]
    fields_container = ["side","state_token","normalized_path","version_string","byte_order","platform","container_size","header_size","extra_size","texture_count","gust_g1t_list_status","gust_g1t_list_texture_rows","payload_in_evidence"]
    fields_entry = ["side","state_token","normalized_path","texture_index","entry_offset","entry_size","payload_offset_in_entry","payload_size","texture_type","mipmaps","z_mipmaps","width","height","global_flag_word","flags_combined_hex","extra_data_size","depth_bits_hex","extra_flags_hex","raw_entry_sha256","payload_sha256","payload_in_evidence"]
    fields_focus = ["texture_slot","dry_texture_id","wet_texture_id","source_dry_payload_sha256","source_wet_payload_sha256","target_dry_payload_sha256","target_wet_payload_sha256","source_dry_shape","source_wet_shape","target_dry_shape","target_wet_shape","source_dry_to_wet_payload_differs","target_dry_to_wet_payload_differs","source_target_dry_entry_shape_exact","source_target_wet_entry_shape_exact","source_target_wet_payload_exact","direct_raw_entry_transplant_structurally_bounded","transparency_or_droplet_semantics_confirmed","write_authorized"]
    fields_shared = ["side","payload_sha256","wet_pack_count","wet_packs","entry_rows","locations","present_in_same_side_dry_packs","wet_only_shared_payload_family","semantics_confirmed","write_authorized"]
    fields_cross = ["source_payload_sha256","source_wet_packs","source_locations","target_same_indices_all_present","target_same_indices_payload_hashes","target_same_indices_still_exactly_shared","target_same_indices_structurally_uniform","candidate_common_wet_layer","wet_skin_or_droplet_semantics_confirmed","write_authorized"]
    write_tsv(output / "INPUTS.tsv", fields_input, input_rows)
    write_tsv(output / "G1T_CONTAINERS.tsv", fields_container, container_rows)
    write_tsv(output / "G1T_ENTRIES.tsv", fields_entry, entry_rows)
    write_tsv(output / "SCHOOL_WET_FOCUS_TEXTURE_TRANSITIONS.tsv", fields_focus, focus_rows)
    write_tsv(output / "SHARED_WET_PAYLOAD_FAMILIES.tsv", fields_shared, shared_rows)
    write_tsv(output / "SOURCE_WET_ONLY_SHARED_TARGET_INDEX_AUDIT.tsv", fields_cross, source_wet_only_target_rows)
    write_tsv(output / "PARSE_SKIPPED.tsv", ["side","state_token","normalized_path","reason","write_authorized"], parse_skips)
    write_tsv(output / "EXTRACTION_INPUTS.tsv", sorted({k for r in extraction_rows for k in r.keys()}), extraction_rows)

    bounded_focus = [r for r in focus_rows if r["direct_raw_entry_transplant_structurally_bounded"]]
    common_wet = [r for r in source_wet_only_target_rows if r["candidate_common_wet_layer"]]
    summary = {
        "type": "br_quartet_restoration_hinako_wet_texture_entry_differential_evidence_summary",
        "format_version": 1,
        "tool_version": TOOL_VERSION,
        "status": "stage154_zero_shader_schema_matches_g1t_wet_texture_entry_differential_complete_no_write",
        "stage154_evidence_sha256": STAGE154_SHA256,
        "stage154_unique_target_material_scoped_schema_rows": 0,
        "stage154_parameter_comparison_rows": 0,
        "stage154_bounded_scalar_candidate_rows": 0,
        "input_texture_pack_rows": len(input_rows),
        "parsed_texture_pack_rows": len(container_rows),
        "g1t_entry_rows": len(entry_rows),
        "parse_skip_rows": len(parse_skips),
        "school_focus_transition_rows": len(focus_rows),
        "school_focus_source_wet_transition_rows": sum(bool(r["source_dry_to_wet_payload_differs"]) for r in focus_rows),
        "school_focus_target_wet_transition_rows": sum(bool(r["target_dry_to_wet_payload_differs"]) for r in focus_rows),
        "school_focus_cross_game_wet_shape_exact_rows": sum(bool(r["source_target_wet_entry_shape_exact"]) for r in focus_rows),
        "school_focus_cross_game_wet_payload_exact_rows": sum(bool(r["source_target_wet_payload_exact"]) for r in focus_rows),
        "school_focus_structurally_bounded_raw_entry_rows": len(bounded_focus),
        "shared_wet_payload_family_rows": len(shared_rows),
        "source_wet_only_shared_payload_family_rows": len(source_wet_only),
        "source_wet_only_target_index_audit_rows": len(source_wet_only_target_rows),
        "candidate_common_wet_layer_rows": len(common_wet),
        "runtime_validated": False,
        "production_eligible": False,
        "policy": {
            "g1t_entry_hashes_are_binding_clues_only": True,
            "texture_ids_are_used_only_where_already_grounded_by_g1mg": True,
            "same_texture_index_across_distinct_packs_is_not_semantic_identity": True,
            "raw_g1t_entry_transplant_authorized": False,
            "complete_g1t_transplant_authorized": False,
            "wet_skin_droplet_semantics_confirmed": False,
            "wet_transparency_semantics_confirmed": False,
            "installed_game_modified": False,
            "pak_repacked": False,
            "core_modified": False,
            "translation_modified": False,
            "legacy_dlc_modified": False,
            "git_modified": False,
            "proprietary_payloads_in_evidence": False,
            "whole_g1mm_transplant_reuse_forbidden": True,
        },
        "next_action": (
            "Review the three grounded school wet texture transitions and any source wet-only payload families shared across multiple wet packs. "
            "If a source/target wet entry is structurally identical, perform a separate per-entry content/alpha feasibility audit before any write. "
            "If a source wet-only shared family spans body/clothing wet packs but is not preserved at the same target positions, investigate it as a common wet-layer candidate without assigning droplet semantics. "
            "Do not transplant a whole G1T or authorize a runtime profile from hashes alone."
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
            print(f"[stage155] report archive: {archive}")
            print(f"[stage155] SHA-256: {sha256_file(archive)}")
        return 0
    except WetTextureAuditError as exc:
        print(f"[stage155] ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
