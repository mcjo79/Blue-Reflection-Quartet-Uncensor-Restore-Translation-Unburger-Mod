#!/usr/bin/env python3
"""Build a one-resource, per-texture probe for Quartet's active launcher atlas.

The earlier full-resource probe established that the English b4 b0_title.g1t is
loaded by the Quartet launcher. This step keeps the scope to that single G1T
and gives each of its three BC7 payloads a distinct colour so the on-screen
roles of texture indices 0, 1, and 2 can be identified without touching any
other launcher texture.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import tempfile
from pathlib import Path
from typing import Any

from second_light_title_marker_proof import (
    ProofError,
    atomic_json,
    extract_pak,
    install_verified_output,
    list_pak_entries,
    recompute_main_summary,
    repack_stage,
    run_checked,
    sha256_file,
    verify_repacked,
)
from title_resource_pixel_probe import parse_dds, patch_dds

REPORT_TYPE = "br_quartet_b0_title_texture_probe_report"
TARGET_ID = "blue_reflection_quartet"
ARCHIVE_RELATIVE = "Data/PACK00_04_01.PAK"
ARCHIVE_STEM = "PACK00_04_01"
RESOURCE_PATH = "data/b4/x64/res_en/ui/b0_title.g1t"
EXPECTED_SOURCE_PAK_SHA256 = "7b3f00055f315956b3177d61cd9dd0c8f5943b7d0e442b63b99d404355b1a747"
EXPECTED_G1T_SHA256 = "1204ddeca637a68dbd694379a32becb4eda020d69aeb455c0cb99a7ae3ee5108"
EXPECTED_TEXTURES = {
    "000.dds": {
        "sha256": "4354e1642e5cd38644bb6ba43b515bad5642d886dac3dc6c3aac90a05b5b1d13",
        "width": 1152,
        "height": 1600,
    },
    "001.dds": {
        "sha256": "9a94d2c038681a55e113ed6be0985d05ac6419e637f0c43898e15d16c8f7e8b1",
        "width": 672,
        "height": 152,
    },
    "002.dds": {
        "sha256": "dc9afd954fd290f5c5adbe78739e5cc131a8d63cf2d6354071d8c3cafff9972b",
        "width": 1760,
        "height": 100,
    },
}
PALETTES = {
    "000.dds": ((255, 35, 35, 255), (32, 0, 0, 255)),   # red
    "001.dds": ((40, 255, 70, 255), (0, 32, 5, 255)),   # green
    "002.dds": ((45, 105, 255, 255), (0, 5, 36, 255)),  # blue
}


class ProbeError(ProofError):
    pass


def validate_original_dds(path: Path, expected: dict[str, Any]) -> dict[str, Any]:
    if sha256_file(path) != expected["sha256"]:
        raise ProbeError(f"Unexpected original payload SHA-256: {path.name}")
    meta = parse_dds(path.read_bytes())
    if meta.get("format") != "BC7" or meta.get("dxgi") not in {98, 99}:
        raise ProbeError(f"Expected BC7 payload: {path.name}")
    if meta.get("width") != expected["width"] or meta.get("height") != expected["height"]:
        raise ProbeError(f"Unexpected dimensions for {path.name}: {meta.get('width')}x{meta.get('height')}")
    if meta.get("mipmaps") != 1:
        raise ProbeError(f"Expected one mipmap for {path.name}")
    return meta


def patch_g1t(source: Path, work: Path, gust_g1t: Path, timeout: int) -> tuple[Path, dict[str, Any]]:
    work.mkdir(parents=True, exist_ok=True)
    local = work / source.name
    shutil.copy2(source, local)
    if sha256_file(local) != EXPECTED_G1T_SHA256:
        raise ProbeError("Installed English b4 b0_title.g1t does not match the known baseline")

    listing_before = run_checked(
        [str(gust_g1t), "-l", local.name], cwd=work, timeout=timeout,
        description="list Quartet b0_title.g1t",
    )
    extract_result = run_checked(
        [str(gust_g1t), "-y", local.name], cwd=work, timeout=timeout,
        description="extract Quartet b0_title.g1t",
    )
    source_dir = work / source.stem
    manifest = source_dir / "g1t.json"
    if not manifest.is_file():
        raise ProbeError("Missing g1t.json after extracting b0_title.g1t")
    dds_files = sorted(source_dir.glob("*.dds"))
    if [p.name for p in dds_files] != list(EXPECTED_TEXTURES):
        raise ProbeError(f"Unexpected b0_title DDS inventory: {[p.name for p in dds_files]}")

    patches: list[dict[str, Any]] = []
    for index, dds in enumerate(dds_files):
        before_meta = validate_original_dds(dds, EXPECTED_TEXTURES[dds.name])
        patch = patch_dds(dds, index, PALETTES[dds.name])
        patches.append({
            "texture": dds.name,
            "probe_colour": {"000.dds": "red", "001.dds": "green", "002.dds": "blue"}[dds.name],
            "original_meta": before_meta,
            **patch,
        })

    original = work / f"{source.stem}.original.g1t"
    os.replace(local, original)
    rebuild_result = run_checked(
        [str(gust_g1t), "-y", str(source_dir)], cwd=work, timeout=timeout,
        description="rebuild Quartet b0_title.g1t",
    )
    if not local.is_file():
        raise ProbeError("gust_g1t did not rebuild b0_title.g1t")
    if sha256_file(local) == EXPECTED_G1T_SHA256:
        raise ProbeError("Rebuilt b0_title.g1t is unchanged")

    verify = work / "verify"
    verify.mkdir()
    verify_g1t = verify / local.name
    shutil.copy2(local, verify_g1t)
    verify_result = run_checked(
        [str(gust_g1t), "-y", verify_g1t.name], cwd=verify, timeout=timeout,
        description="verify rebuilt Quartet b0_title.g1t",
    )
    verified_dds = sorted((verify / source.stem).glob("*.dds"))
    if [p.name for p in verified_dds] != [p.name for p in dds_files]:
        raise ProbeError("DDS inventory changed after rebuilding b0_title.g1t")
    expected_after = {p.name: sha256_file(p) for p in dds_files}
    actual_after = {p.name: sha256_file(p) for p in verified_dds}
    if expected_after != actual_after:
        raise ProbeError("Re-extracted b0_title payload hashes do not match")

    details = {
        "resource_path": RESOURCE_PATH,
        "original_sha256": EXPECTED_G1T_SHA256,
        "rebuilt_sha256": sha256_file(local),
        "textures": patches,
        "listing_before_tail": listing_before.stdout.splitlines()[-10:],
        "extract_tail": extract_result.stdout.splitlines()[-10:],
        "rebuild_tail": rebuild_result.stdout.splitlines()[-10:],
        "verify_extract_tail": verify_result.stdout.splitlines()[-10:],
    }
    return local, details


def build(args: argparse.Namespace) -> int:
    project_root = Path(args.project_root).expanduser().resolve()
    quartet_root = Path(args.quartet_root).expanduser().resolve()
    gust_pak = Path(args.gust_pak).expanduser().resolve()
    gust_g1t = Path(args.gust_g1t).expanduser().resolve()
    timeout = args.timeout

    source_pak = quartet_root / ARCHIVE_RELATIVE
    if not source_pak.is_file():
        raise ProbeError(f"Missing Quartet source archive: {source_pak}")
    source_pak_hash = sha256_file(source_pak)
    if source_pak_hash != EXPECTED_SOURCE_PAK_SHA256:
        raise ProbeError(
            "Quartet PACK00_04_01.PAK is not the known baseline; restore the previous test first "
            f"(current {source_pak_hash})"
        )

    main_report_path = project_root / ".local/reports/translation/BR_TRANSLATION_PAK_REPACK_REPORT.json"
    if not main_report_path.is_file():
        raise ProbeError("Translation repack report missing; run steps 07 and 08")
    main_report = json.loads(main_report_path.read_text(encoding="utf-8"))
    if main_report.get("status") != "ok":
        raise ProbeError("Translation repack report is not ok")

    build_root = project_root / ".local/build/translation"
    with tempfile.TemporaryDirectory(prefix=".br_quartet_b0_index_probe.", dir=build_root) as raw_tmp:
        temp_root = Path(raw_tmp)
        stage = temp_root / "stage"
        manifest, extract_tail = extract_pak(gust_pak, source_pak, stage, timeout)
        entries, _ = list_pak_entries(gust_pak, source_pak, temp_root, timeout)
        normalized = {entry.casefold(): entry for entry in entries}
        key = RESOURCE_PATH.casefold()
        if key not in normalized:
            raise ProbeError(f"Resource not present in source PAK: {RESOURCE_PATH}")
        staged_g1t = stage / Path(normalized[key])
        if not staged_g1t.is_file():
            raise ProbeError(f"Extracted resource missing: {staged_g1t}")

        rebuilt_g1t, resource_details = patch_g1t(staged_g1t, temp_root / "g1t", gust_g1t, timeout)
        install_verified_output(rebuilt_g1t, staged_g1t)
        built, repack_tail = repack_stage(gust_pak, stage, manifest, ARCHIVE_STEM, timeout)
        checked, failures, listing_tail = verify_repacked(
            gust_pak, built, stage, temp_root / "verify_pak", timeout
        )
        if failures:
            raise ProbeError(f"PAK verification failed: {failures[:3]}")

        final = build_root / "archives" / TARGET_ID / ARCHIVE_RELATIVE
        install_verified_output(built, final)

    # Remove the now-obsolete broad PACK00_01 probe from both the report and build output.
    broad_probe = build_root / "archives" / TARGET_ID / "Data/PACK00_01.PAK"
    broad_probe.unlink(missing_ok=True)
    main_report["archives"] = [
        entry for entry in main_report.get("archives", [])
        if not (
            entry.get("target_id") == TARGET_ID
            and entry.get("archive_relative_path") in {"Data/PACK00_01.PAK", ARCHIVE_RELATIVE}
        )
    ]
    archive_entry = {
        "target_id": TARGET_ID,
        "archive_stem": ARCHIVE_STEM,
        "archive_relative_path": ARCHIVE_RELATIVE,
        "output_path": final.relative_to(project_root).as_posix(),
        "output_sha256": sha256_file(final),
        "output_bytes": final.stat().st_size,
        "changed_files": 1,
        "listed_entries": len(entries),
        "entries_checked": checked,
        "failures": failures,
        "repack_stdout_tail": repack_tail,
        "listing_stdout_tail": listing_tail,
        "manifest_policy": "opaque_gust_pak_input",
        "source_policy": "installed_original_read_only_plus_single_g1t_per_texture_probe",
    }
    main_report["archives"].append(archive_entry)
    main_report["archives"].sort(key=lambda entry: (str(entry.get("target_id")), str(entry.get("archive_relative_path"))))
    main_report.pop("title_resource_pixel_probe", None)
    main_report["quartet_b0_title_texture_probe"] = {
        "status": "ok",
        "resource": RESOURCE_PATH,
        "texture_colours": {"000.dds": "red", "001.dds": "green", "002.dds": "blue"},
        "runtime_status": "awaiting_manual_test",
    }
    recompute_main_summary(main_report)
    atomic_json(main_report_path, main_report)

    report = {
        "type": REPORT_TYPE,
        "format_version": 1,
        "status": "ok",
        "method": "single_active_g1t_per_texture_full_base_mip_probe",
        "runtime_status": "awaiting_manual_test",
        "project_root": "<PROJECT_ROOT>",
        "target_id": TARGET_ID,
        "archive": ARCHIVE_RELATIVE,
        "source_archive_sha256": source_pak_hash,
        "output_archive_sha256": sha256_file(final),
        "resource": resource_details,
        "texture_colours": {
            "000.dds": "red",
            "001.dds": "green",
            "002.dds": "blue",
        },
        "interpretation": (
            "Red screen elements use texture 000; green elements use texture 001; "
            "blue elements use texture 002. Only the already-proven English b4 b0_title.g1t is modified."
        ),
        "archive_report": archive_entry,
        "extract_tail": extract_tail,
        "safety": {
            "installed_files_modified_during_build": False,
            "proprietary_assets_in_update_package": False,
            "only_one_g1t_modified": True,
            "full_g1t_reextract_verification": True,
            "full_pak_reextract_verification": True,
            "installation_requires_step_09": True,
        },
    }
    atomic_json(
        project_root / ".local/reports/translation/BR_QUARTET_B0_TITLE_TEXTURE_PROBE_REPORT.json",
        report,
    )
    return 0


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser()
    p.add_argument("--project-root", required=True)
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
