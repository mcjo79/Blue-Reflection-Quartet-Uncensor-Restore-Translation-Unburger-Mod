#!/usr/bin/env python3
"""Build destructive-but-reversible pixel probes for title resources.

This diagnostic intentionally ignores localized title XML. It rewrites only the
base mip of existing G1T textures in local rebuilt PAKs so runtime usage is
visually undeniable. Installed files remain untouched until step 09 performs a
transactional test and can be restored immediately afterward.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import shutil
import struct
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from second_light_title_marker import encode_bc7_mode5_block
from second_light_title_marker_proof import (
    ProofError,
    atomic_bytes,
    atomic_json,
    encode_dxt5_block,
    extract_pak,
    install_verified_output,
    list_pak_entries,
    recompute_main_summary,
    repack_stage,
    run_checked,
    sha256_file,
    verify_repacked,
)

REPORT_TYPE = "br_title_resource_pixel_probe_report"


class ProbeError(ProofError):
    pass


@dataclass(frozen=True)
class Resource:
    internal_path: str
    code: str
    palette: tuple[tuple[int, int, int, int], tuple[int, int, int, int]]


@dataclass(frozen=True)
class Target:
    target_id: str
    archive_relative_path: str
    archive_stem: str
    resources: tuple[Resource, ...]


TARGETS = (
    Target(
        target_id="blue_reflection_original",
        archive_relative_path="DATA/PACK00_01.PAK",
        archive_stem="PACK00_01",
        resources=(
            Resource("data/x64/ui/a17_common.g1t", "A17C", ((255, 0, 180, 255), (20, 0, 20, 255))),
            Resource("data/x64/ui/a17_system.g1t", "A17S", ((0, 255, 255, 255), (0, 20, 25, 255))),
            Resource("data/x64/ui/a17_window.g1t", "A17W", ((255, 230, 0, 255), (30, 25, 0, 255))),
            Resource("data/x64/ui/a18_common.g1t", "A18C", ((0, 255, 70, 255), (0, 25, 8, 255))),
            Resource("data/x64/ui/a18_system.g1t", "A18S", ((255, 80, 0, 255), (30, 5, 0, 255))),
            Resource("data/x64/ui/a18_window.g1t", "A18W", ((120, 90, 255, 255), (10, 5, 30, 255))),
        ),
    ),
    Target(
        target_id="blue_reflection_quartet",
        archive_relative_path="Data/PACK00_01.PAK",
        archive_stem="PACK00_01",
        resources=(
            Resource("data/b4/x64/res_cmn/ui/seed_select_game.g1t", "CMN_SELECT", ((255, 35, 35, 255), (30, 0, 0, 255))),
            Resource("data/b4/x64/res_cmn/ui/b0_title.g1t", "CMN_B0TITLE", ((45, 90, 255, 255), (0, 5, 30, 255))),
            Resource("data/b4/x64/res_cmn/ui/seed_title.g1t", "CMN_B4TITLE", ((100, 255, 35, 255), (5, 30, 0, 255))),
        ),
    ),
    Target(
        target_id="blue_reflection_quartet",
        archive_relative_path="Data/PACK00_04_01.PAK",
        archive_stem="PACK00_04_01",
        resources=(
            Resource("data/b4/x64/res_en/ui/seed_select_game.g1t", "EN_SELECT", ((255, 0, 180, 255), (20, 0, 20, 255))),
            Resource("data/b4/x64/res_en/ui/b0_title.g1t", "EN_B0TITLE", ((0, 255, 255, 255), (0, 20, 25, 255))),
            Resource("data/b4/x64/res_en/ui/seed_title.g1t", "EN_B4TITLE", ((255, 230, 0, 255), (30, 25, 0, 255))),
        ),
    ),
)


def rgb565(rgb: tuple[int, int, int]) -> int:
    r, g, b = rgb
    return ((r * 31 + 127) // 255) << 11 | ((g * 63 + 127) // 255) << 5 | ((b * 31 + 127) // 255)


def encode_dxt1_block(pixels: list[tuple[int, int, int, int]]) -> bytes:
    # The probe uses a two-colour checker. DXT1 endpoint interpolation is enough.
    colours = [p[:3] for p in pixels]
    c0_rgb = max(colours, key=lambda c: sum(c))
    c1_rgb = min(colours, key=lambda c: sum(c))
    c0 = rgb565(c0_rgb)
    c1 = rgb565(c1_rgb)
    if c0 <= c1:
        c0, c1 = c1, c0
        c0_rgb, c1_rgb = c1_rgb, c0_rgb
    def expand(v: int) -> tuple[int, int, int]:
        return (((v >> 11) & 31) * 255 // 31, ((v >> 5) & 63) * 255 // 63, (v & 31) * 255 // 31)
    p0, p1 = expand(c0), expand(c1)
    palette = [p0, p1,
               tuple((2*p0[i] + p1[i] + 1)//3 for i in range(3)),
               tuple((p0[i] + 2*p1[i] + 1)//3 for i in range(3))]
    indices = 0
    for i, rgb in enumerate(colours):
        idx = min(range(4), key=lambda j: sum((rgb[k]-palette[j][k])**2 for k in range(3)))
        indices |= idx << (2*i)
    return struct.pack("<HHI", c0, c1, indices)


def parse_dds(data: bytes) -> dict[str, Any]:
    if len(data) < 128 or data[:4] != b"DDS ":
        raise ProbeError("G1T payload is not DDS")
    width = struct.unpack_from("<I", data, 16)[0]
    height = struct.unpack_from("<I", data, 12)[0]
    mipmaps = struct.unpack_from("<I", data, 28)[0] or 1
    fourcc = data[84:88]
    if fourcc == b"DXT1":
        return {"format": "DXT1", "offset": 128, "block_bytes": 8, "width": width, "height": height, "mipmaps": mipmaps}
    if fourcc == b"DXT5":
        return {"format": "DXT5", "offset": 128, "block_bytes": 16, "width": width, "height": height, "mipmaps": mipmaps}
    if fourcc == b"DX10" and len(data) >= 148:
        dxgi = struct.unpack_from("<I", data, 128)[0]
        if dxgi in {98, 99}:
            return {"format": "BC7", "offset": 148, "block_bytes": 16, "width": width, "height": height, "mipmaps": mipmaps, "dxgi": dxgi}
        raise ProbeError(f"Unsupported DX10 format {dxgi}")
    raise ProbeError(f"Unsupported DDS FourCC {fourcc!r}")


def pattern_block(block_x: int, block_y: int, texture_index: int, palette: tuple[tuple[int,int,int,int], tuple[int,int,int,int]]) -> list[tuple[int,int,int,int]]:
    a, b = palette
    # Large 32x32-pixel checker plus a fine diagonal. Each texture index shifts it.
    base = ((block_x // 8) + (block_y // 8) + texture_index) & 1
    pixels: list[tuple[int,int,int,int]] = []
    for y in range(4):
        for x in range(4):
            diagonal = ((block_x * 4 + x + block_y * 4 + y) // 12) & 1
            pixels.append(a if (base ^ diagonal) == 0 else b)
    return pixels


def patch_dds(path: Path, texture_index: int, palette: tuple[tuple[int,int,int,int], tuple[int,int,int,int]]) -> dict[str, Any]:
    raw = path.read_bytes()
    meta = parse_dds(raw)
    blocks_x = math.ceil(meta["width"] / 4)
    blocks_y = math.ceil(meta["height"] / 4)
    base_bytes = blocks_x * blocks_y * meta["block_bytes"]
    if meta["offset"] + base_bytes > len(raw):
        raise ProbeError(f"Truncated DDS base mip: {path}")
    out = bytearray(raw)
    cursor = meta["offset"]
    for by in range(blocks_y):
        for bx in range(blocks_x):
            pixels = pattern_block(bx, by, texture_index, palette)
            if meta["format"] == "DXT1":
                encoded = encode_dxt1_block(pixels)
            elif meta["format"] == "DXT5":
                encoded = encode_dxt5_block(pixels)
            else:
                encoded = encode_bc7_mode5_block(pixels)
            out[cursor:cursor+len(encoded)] = encoded
            cursor += len(encoded)
    before = hashlib.sha256(raw).hexdigest()
    after = hashlib.sha256(out).hexdigest()
    if before == after:
        raise ProbeError(f"DDS probe made no change: {path}")
    atomic_bytes(path, bytes(out))
    return {**meta, "before_sha256": before, "after_sha256": after, "base_blocks": blocks_x * blocks_y}


def patch_g1t(source: Path, work: Path, gust_g1t: Path, resource: Resource, timeout: int) -> dict[str, Any]:
    work.mkdir(parents=True, exist_ok=True)
    local = work / source.name
    shutil.copy2(source, local)
    before_sha = sha256_file(local)
    listing_before = run_checked([str(gust_g1t), "-l", local.name], cwd=work, timeout=timeout, description=f"list {resource.internal_path}")
    extracted = run_checked([str(gust_g1t), "-y", local.name], cwd=work, timeout=timeout, description=f"extract {resource.internal_path}")
    source_dir = work / source.stem
    manifest = source_dir / "g1t.json"
    if not manifest.is_file():
        raise ProbeError(f"Missing g1t.json after extracting {resource.internal_path}")
    dds_files = sorted(source_dir.glob("*.dds"))
    if not dds_files:
        raise ProbeError(f"No DDS payloads in {resource.internal_path}")
    before_payloads = {p.name: sha256_file(p) for p in dds_files}
    patches = []
    for index, dds in enumerate(dds_files):
        patches.append({"texture": dds.name, **patch_dds(dds, index, resource.palette)})
    original = work / f"{source.stem}.original.g1t"
    os.replace(local, original)
    rebuilt = run_checked([str(gust_g1t), "-y", str(source_dir)], cwd=work, timeout=timeout, description=f"rebuild {resource.internal_path}")
    if not local.is_file():
        raise ProbeError(f"gust_g1t did not rebuild {resource.internal_path}")
    after_sha = sha256_file(local)
    if after_sha == before_sha:
        raise ProbeError(f"Rebuilt G1T unchanged: {resource.internal_path}")
    verify = work / "verify"
    verify.mkdir()
    verify_g1t = verify / local.name
    shutil.copy2(local, verify_g1t)
    verify_extract = run_checked([str(gust_g1t), "-y", verify_g1t.name], cwd=verify, timeout=timeout, description=f"verify {resource.internal_path}")
    verified_dir = verify / source.stem
    verified_dds = sorted(verified_dir.glob("*.dds"))
    if [p.name for p in verified_dds] != [p.name for p in dds_files]:
        raise ProbeError(f"DDS inventory changed for {resource.internal_path}")
    expected_after = {p.name: sha256_file(p) for p in dds_files}
    actual_after = {p.name: sha256_file(p) for p in verified_dds}
    if expected_after != actual_after:
        raise ProbeError(f"DDS verification mismatch for {resource.internal_path}")
    return {
        "resource_path": resource.internal_path,
        "code": resource.code,
        "original_sha256": before_sha,
        "rebuilt_sha256": after_sha,
        "original_payload_sha256": before_payloads,
        "patches": patches,
        "listing_before_tail": listing_before.stdout.splitlines()[-10:],
        "extract_tail": extracted.stdout.splitlines()[-10:],
        "rebuild_tail": rebuilt.stdout.splitlines()[-10:],
        "verify_extract_tail": verify_extract.stdout.splitlines()[-10:],
        "rebuilt_path": local,
    }


def game_root_for(args: argparse.Namespace, target_id: str) -> Path:
    return Path(args.original_root if target_id == "blue_reflection_original" else args.quartet_root).expanduser().resolve()


def report_entry(target: Target, output: Path, project_root: Path, changed_files: int, listed: int, checked: int, failures: list[dict[str,str]], repack_tail: list[str], listing_tail: list[str]) -> dict[str, Any]:
    return {
        "target_id": target.target_id,
        "archive_stem": target.archive_stem,
        "archive_relative_path": target.archive_relative_path,
        "output_path": output.relative_to(project_root).as_posix(),
        "output_sha256": sha256_file(output),
        "output_bytes": output.stat().st_size,
        "changed_files": changed_files,
        "listed_entries": listed,
        "entries_checked": checked,
        "failures": failures,
        "repack_stdout_tail": repack_tail,
        "listing_stdout_tail": listing_tail,
        "manifest_policy": "opaque_gust_pak_input",
        "source_policy": "installed_original_read_only_plus_full_base_mip_resource_probe",
    }


def build(args: argparse.Namespace) -> int:
    project_root = Path(args.project_root).expanduser().resolve()
    gust_pak = Path(args.gust_pak).expanduser().resolve()
    gust_g1t = Path(args.gust_g1t).expanduser().resolve()
    timeout = args.timeout
    report_path = project_root / ".local/reports/translation/BR_TRANSLATION_PAK_REPACK_REPORT.json"
    if not report_path.is_file():
        raise ProbeError("Clean repack report missing; run steps 07 and 08")
    main_report = json.loads(report_path.read_text(encoding="utf-8"))
    if main_report.get("status") != "ok":
        raise ProbeError("Clean repack report is not ok")
    build_root = project_root / ".local/build/translation"
    results: list[dict[str, Any]] = []
    new_entries: list[dict[str, Any]] = []
    with tempfile.TemporaryDirectory(prefix=".br_title_resource_probe.", dir=build_root) as raw_tmp:
        temp_root = Path(raw_tmp)
        for target in TARGETS:
            game_root = game_root_for(args, target.target_id)
            source_pak = game_root / target.archive_relative_path
            if not source_pak.is_file():
                raise ProbeError(f"Missing source archive: {source_pak}")
            target_root = temp_root / target.target_id
            stage = target_root / "stage"
            manifest, extract_tail = extract_pak(gust_pak, source_pak, stage, timeout)
            entries, _ = list_pak_entries(gust_pak, source_pak, target_root, timeout)
            normalized = {e.casefold(): e for e in entries}
            resource_results = []
            for idx, resource in enumerate(target.resources):
                key = resource.internal_path.casefold()
                if key not in normalized:
                    raise ProbeError(f"Resource not found in {target.archive_relative_path}: {resource.internal_path}")
                actual = stage / Path(normalized[key])
                if not actual.is_file():
                    raise ProbeError(f"Extracted resource missing: {actual}")
                result = patch_g1t(actual, target_root / f"g1t_{idx}_{resource.code}", gust_g1t, resource, timeout)
                install_verified_output(result["rebuilt_path"], actual)
                result["rebuilt_path"] = actual.relative_to(stage).as_posix()
                resource_results.append(result)
            built, repack_tail = repack_stage(gust_pak, stage, manifest, target.archive_stem, timeout)
            checked, failures, listing_tail = verify_repacked(gust_pak, built, stage, target_root / "verify_pak", timeout)
            if failures:
                raise ProbeError(f"PAK verification failed for {target.target_id}: {failures[:3]}")
            final = build_root / "archives" / target.target_id / target.archive_relative_path
            install_verified_output(built, final)
            entry = report_entry(target, final, project_root, len(resource_results), len(entries), checked, failures, repack_tail, listing_tail)
            new_entries.append(entry)
            results.append({
                "target_id": target.target_id,
                "archive": target.archive_relative_path,
                "source_sha256": sha256_file(source_pak),
                "output_sha256": sha256_file(final),
                "resources": resource_results,
                "extract_tail": extract_tail,
                "archive_report": entry,
            })
    replace_keys = {(e["target_id"], e["archive_relative_path"]) for e in new_entries}
    main_report["archives"] = [e for e in main_report.get("archives", []) if (e.get("target_id"), e.get("archive_relative_path")) not in replace_keys] + new_entries
    main_report["archives"].sort(key=lambda e: (str(e.get("target_id")), str(e.get("archive_relative_path"))))
    recompute_main_summary(main_report)
    main_report["title_resource_pixel_probe"] = {
        "status": "ok",
        "method": "existing_g1t_full_base_mip_probe",
        "runtime_status": "awaiting_manual_test",
        "targets": [t.target_id for t in TARGETS],
    }
    atomic_json(report_path, main_report)
    report = {
        "type": REPORT_TYPE,
        "format_version": 1,
        "status": "ok",
        "method": "existing_g1t_full_base_mip_probe",
        "runtime_status": "awaiting_manual_test",
        "project_root": "<PROJECT_ROOT>",
        "targets": results,
        "interpretation": {
            "blue_reflection_original": "Any violent checkerboard change identifies the active explicit UI resource; no change excludes all six listed UI G1Ts.",
            "blue_reflection_quartet": "Common layer: red=seed_select_game, blue=b0_title, green=seed_title. English layer: magenta=seed_select_game, cyan=b0_title, yellow=seed_title.",
        },
        "safety": {
            "installed_files_modified_during_build": False,
            "proprietary_assets_in_update_package": False,
            "full_g1t_reextract_verification": True,
            "full_pak_reextract_verification": True,
            "installation_requires_step_09": True,
        },
    }
    atomic_json(project_root / ".local/reports/translation/BR_TITLE_RESOURCE_PIXEL_PROBE_REPORT.json", report)
    return 0


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser()
    p.add_argument("--project-root", required=True)
    p.add_argument("--original-root", required=True)
    p.add_argument("--quartet-root", required=True)
    p.add_argument("--gust-pak", required=True)
    p.add_argument("--gust-g1t", required=True)
    p.add_argument("--timeout", type=int, default=900)
    return p


if __name__ == "__main__":
    try:
        raise SystemExit(build(parser().parse_args()))
    except (ProbeError, OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}", file=os.sys.stderr)
        raise SystemExit(1)
