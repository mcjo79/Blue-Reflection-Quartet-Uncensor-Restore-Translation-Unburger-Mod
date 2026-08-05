#!/usr/bin/env python3
"""Build the runtime-approved production UNBURGER MOD marker for Original Blue Reflection.

The runtime-confirmed English title layout is stored in
``DATA/PACK00_04_1.PAK:data/x64/res_en/layout/12_title.kscl``.  Only the
embedded BC3 texture named ``fnt_credit`` is replaced in place.  Its dimensions,
raw payload size, the KSCL/KSLT table, every other embedded texture, and every
other PAK member must remain unchanged.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import shutil
import tempfile
from pathlib import Path
from typing import Any

from blue_reflection_title_kscl_probe import (
    ARCHIVE_RELATIVE,
    ARCHIVE_STEM,
    RESOURCE_PATH,
    KSCLProbeError,
    extract_pak_symlink,
    install_verified_output_bytes,
    parse_kscl,
)
from quartet_title_marker import FONT, render_label
from second_light_title_marker_proof import (
    atomic_json,
    encode_dxt5_block,
    install_verified_output,
    list_pak_entries,
    recompute_main_summary,
    repack_stage,
    sha256_file,
    verify_repacked,
)

REPORT_TYPE = "br_blue_reflection_title_marker_report"
TARGET_ID = "blue_reflection_original"
TARGET_TEXTURE_NAME = "fnt_credit"
EXPECTED_RESOURCE_SHA256 = "437e44f51de8e1313b4f848b1ba183dca309ab139acb43e97c9dbe53e4a82374"
EXPECTED_TEXTURE_INDEX = 7
EXPECTED_TEXTURE_RAW_SHA256 = "e03b2ea13b34270107bc2d0a93643c71db1b0f9a826c73ed20c51cd1dcd89ab8"
EXPECTED_TEXTURE_WIDTH = 480
EXPECTED_TEXTURE_HEIGHT = 32
EXPECTED_TEXTURE_RAW_SIZE = 15360
CONFIG_RELATIVE = "workstreams/translation_tooling/config/title_markers/blue_reflection_title_marker.json"


class BR1MarkerError(KSCLProbeError):
    pass


def read_translation_version(project_root: Path) -> str:
    path = project_root / "workstreams/translation/VERSION"
    if not path.is_file():
        raise BR1MarkerError(f"Missing translation version source: {path}")
    value = path.read_text(encoding="utf-8").strip()
    if not value:
        raise BR1MarkerError("Translation VERSION is empty")
    unsupported = sorted({char for char in value if char not in FONT})
    if unsupported:
        raise BR1MarkerError(f"Translation VERSION contains unsupported characters: {unsupported}")
    return value


def build_label(project_root: Path) -> tuple[str, str]:
    version = read_translation_version(project_root)
    label = f"UNBURGER MOD (v{version})"
    unsupported = sorted({char for char in label if char not in FONT})
    if unsupported:
        raise BR1MarkerError(f"Marker label contains unsupported characters: {unsupported}")
    return label, version


def load_config(project_root: Path, raw_path: str | None) -> tuple[Path, dict[str, Any]]:
    if raw_path:
        candidate = Path(raw_path).expanduser()
        path = candidate if candidate.is_absolute() else project_root / candidate
    else:
        path = project_root / CONFIG_RELATIVE
    path = path.resolve()
    if not path.is_file():
        raise BR1MarkerError(f"Missing Original Blue Reflection marker config: {path}")
    try:
        config = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise BR1MarkerError(f"Invalid marker JSON: {exc}") from exc
    if not isinstance(config, dict):
        raise BR1MarkerError("Marker config root must be an object")
    if config.get("type") != "br_blue_reflection_title_marker_config":
        raise BR1MarkerError("Unexpected Original Blue Reflection marker config type")
    if config.get("format_version") != 1:
        raise BR1MarkerError("Unsupported marker config format_version")
    # render_label performs the layout calculation. Validate the required shape
    # here so malformed user-edited configs fail before any PAK work starts.
    for key in ("clear", "layout", "font", "style"):
        if not isinstance(config.get(key), dict):
            raise BR1MarkerError(f"Marker config requires object: {key}")
    rect = config["layout"].get("text_rect")
    if not isinstance(rect, list) or len(rect) != 4 or not all(isinstance(v, int) for v in rect):
        raise BR1MarkerError("layout.text_rect must contain four integers")
    return path, config


def rgba_preview_png(path: Path, width: int, height: int, pixels: bytearray) -> None:
    # Reuse the small dependency-free PNG writer already used by title markers.
    from second_light_title_marker import write_png

    write_png(path, width, height, pixels)


def encode_dxt5_image(pixels: bytearray, width: int, height: int) -> bytes:
    if width % 4 or height % 4:
        raise BR1MarkerError(f"Target texture is not DXT5 block aligned: {width}x{height}")
    out = bytearray()
    for block_y in range(height // 4):
        for block_x in range(width // 4):
            block: list[tuple[int, int, int, int]] = []
            for dy in range(4):
                for dx in range(4):
                    x = block_x * 4 + dx
                    y = block_y * 4 + dy
                    offset = (y * width + x) * 4
                    block.append(tuple(pixels[offset : offset + 4]))  # type: ignore[arg-type]
            out.extend(encode_dxt5_block(block))
    return bytes(out)


def patch_kscl_credit(
    path: Path,
    label: str,
    config: dict[str, Any],
    preview_path: Path,
) -> dict[str, Any]:
    original = path.read_bytes()
    before_file = hashlib.sha256(original).hexdigest()
    parsed = parse_kscl(original)
    matches = [item for item in parsed["textures"] if item["name"] == TARGET_TEXTURE_NAME]
    if len(matches) != 1:
        raise BR1MarkerError(f"Expected exactly one {TARGET_TEXTURE_NAME!r} texture, found {len(matches)}")
    target = matches[0]
    if int(target["format_type"]) != 3:
        raise BR1MarkerError("fnt_credit is not BC3/DXT5")
    width = int(target["width"])
    height = int(target["height"])
    raw_size = int(target["raw_size"])
    if width <= 0 or height <= 0 or width % 4 or height % 4:
        raise BR1MarkerError(f"fnt_credit has incompatible BC3 geometry: {width}x{height}")
    expected_bc3_size = width * height
    if raw_size != expected_bc3_size:
        raise BR1MarkerError(
            f"fnt_credit BC3 payload size is incompatible: {raw_size} != {expected_bc3_size}"
        )

    raw_offset = int(target["raw_offset"])
    before_raw = original[raw_offset : raw_offset + raw_size]
    before_raw_hash = hashlib.sha256(before_raw).hexdigest()

    effective_config = json.loads(json.dumps(config))
    if (width, height) != (EXPECTED_TEXTURE_WIDTH, EXPECTED_TEXTURE_HEIGHT):
        rect = effective_config["layout"]["text_rect"]
        scale_x = width / EXPECTED_TEXTURE_WIDTH
        scale_y = height / EXPECTED_TEXTURE_HEIGHT
        effective_config["layout"]["text_rect"] = [
            round(rect[0] * scale_x), round(rect[1] * scale_y),
            round(rect[2] * scale_x), round(rect[3] * scale_y),
        ]
        effective_config["layout"]["padding_x"] = max(0, round(effective_config["layout"].get("padding_x", 0) * scale_x))
        effective_config["layout"]["padding_y"] = max(0, round(effective_config["layout"].get("padding_y", 0) * scale_y))
    pixels, metrics = render_label(label, width, height, effective_config)
    metrics["encoder"] = "BC3/DXT5 with explicit alpha"
    metrics["source_compatibility"] = (
        "known_runtime_profile"
        if before_file == EXPECTED_RESOURCE_SHA256 and before_raw_hash == EXPECTED_TEXTURE_RAW_SHA256
        else "structurally_compatible_current_baseline"
    )
    encoded = encode_dxt5_image(pixels, width, height)
    if len(encoded) != raw_size:
        raise BR1MarkerError(f"Encoded fnt_credit size mismatch: {len(encoded)} != {raw_size}")
    if encoded == before_raw:
        raise BR1MarkerError("Marker encoding made no texture change")

    out = bytearray(original)
    out[raw_offset : raw_offset + raw_size] = encoded
    install_verified_output_bytes(bytes(out), path)
    after = path.read_bytes()
    reparsed = parse_kscl(after)

    # Every texture except fnt_credit must retain exact raw bytes.  The structural
    # table and all non-texture bytes are protected by comparing a masked copy.
    for old_tex, new_tex in zip(parsed["textures"], reparsed["textures"], strict=True):
        signature_old = (
            old_tex["index"], old_tex["name"], old_tex["format_type"], old_tex["width"],
            old_tex["height"], old_tex["raw_offset"], old_tex["raw_size"],
        )
        signature_new = (
            new_tex["index"], new_tex["name"], new_tex["format_type"], new_tex["width"],
            new_tex["height"], new_tex["raw_offset"], new_tex["raw_size"],
        )
        if signature_old != signature_new:
            raise BR1MarkerError(f"KSCL texture structure changed at index {old_tex['index']}")
        if old_tex["name"] == TARGET_TEXTURE_NAME:
            continue
        start = int(old_tex["raw_offset"])
        end = start + int(old_tex["raw_size"])
        if original[start:end] != after[start:end]:
            raise BR1MarkerError(f"Unexpected modification of embedded texture {old_tex['name']}")

    masked_original = bytearray(original)
    masked_after = bytearray(after)
    masked_original[raw_offset : raw_offset + raw_size] = b"\0" * raw_size
    masked_after[raw_offset : raw_offset + raw_size] = b"\0" * raw_size
    if masked_original != masked_after:
        raise BR1MarkerError("Bytes outside fnt_credit changed in 12_title.kscl")

    preview_path.parent.mkdir(parents=True, exist_ok=True)
    rgba_preview_png(preview_path, EXPECTED_TEXTURE_WIDTH, EXPECTED_TEXTURE_HEIGHT, pixels)
    return {
        "resource_path": RESOURCE_PATH,
        "before_sha256": before_file,
        "after_sha256": hashlib.sha256(after).hexdigest(),
        "bytes": len(original),
        "target_texture": {
            **target,
            "before_raw_sha256": before_raw_hash,
            "after_raw_sha256": hashlib.sha256(encoded).hexdigest(),
            "preview_path": ".local/reports/translation/BR_blue_reflection_title_marker_preview.png",
            "preview_sha256": sha256_file(preview_path),
            **metrics,
        },
        "embedded_texture_count": len(parsed["textures"]),
        "unchanged_embedded_textures_verified": len(parsed["textures"]) - 1,
    }


def build(args: argparse.Namespace) -> int:
    project_root = Path(args.project_root).expanduser().resolve()
    original_root = Path(args.original_root).expanduser().resolve()
    gust_pak = Path(args.gust_pak).expanduser().resolve()
    timeout = args.timeout
    label, version = build_label(project_root)
    config_path, config = load_config(project_root, args.config)

    source_pak = original_root / ARCHIVE_RELATIVE
    if not source_pak.is_file():
        raise BR1MarkerError(f"Missing Original source archive: {source_pak}")
    source_hash = sha256_file(source_pak)

    main_report_path = project_root / ".local/reports/translation/BR_TRANSLATION_PAK_REPACK_REPORT.json"
    if not main_report_path.is_file():
        raise BR1MarkerError("Translation repack report missing; run clean steps 07 and 08 first")
    main_report = json.loads(main_report_path.read_text(encoding="utf-8"))
    if main_report.get("status") != "ok":
        raise BR1MarkerError("Translation repack report is not ok")

    build_root = project_root / ".local/build/translation"
    build_root.mkdir(parents=True, exist_ok=True)
    preview = project_root / ".local/reports/translation/BR_blue_reflection_title_marker_preview.png"
    with tempfile.TemporaryDirectory(prefix=".br1_title_marker.", dir=build_root) as raw_tmp:
        temp_root = Path(raw_tmp)
        stage = temp_root / "stage"
        manifest, extract_tail = extract_pak_symlink(gust_pak, source_pak, stage, timeout)
        entries, _ = list_pak_entries(gust_pak, source_pak, temp_root, timeout)
        normalized = {entry.casefold(): entry for entry in entries}
        key = RESOURCE_PATH.casefold()
        if key not in normalized:
            raise BR1MarkerError(f"Resource not present in source PAK: {RESOURCE_PATH}")
        staged_kscl = stage / Path(normalized[key])
        if not staged_kscl.is_file():
            raise BR1MarkerError(f"Extracted resource missing: {staged_kscl}")

        resource_details = patch_kscl_credit(staged_kscl, label, config, preview)
        # Fail immediately if a future report field accidentally contains Path or another
        # non-JSON type, before publishing the rebuilt archive.
        json.dumps(resource_details, ensure_ascii=False)
        built, repack_tail = repack_stage(gust_pak, stage, manifest, ARCHIVE_STEM, timeout)
        checked, failures, listing_tail = verify_repacked(
            gust_pak, built, stage, temp_root / "verify_pak", timeout
        )
        if failures:
            raise BR1MarkerError(f"PAK verification failed: {failures[:3]}")
        final = build_root / "archives" / TARGET_ID / ARCHIVE_RELATIVE
        install_verified_output(built, final)

    main_report["archives"] = [
        entry for entry in main_report.get("archives", [])
        if not (entry.get("target_id") == TARGET_ID and entry.get("archive_relative_path") == ARCHIVE_RELATIVE)
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
        "source_policy": "current_installation_baseline_extraction_plus_verified_marker_overlay",
        "source_archive_sha256": source_hash,
        "source_archive_bytes": source_pak.stat().st_size,
        "changed_members": [RESOURCE_PATH],
        "full_reextract_verified": not failures and checked == len(entries),
    }
    main_report["archives"].append(archive_entry)
    main_report["archives"].sort(key=lambda e: (str(e.get("target_id")), str(e.get("archive_relative_path"))))
    main_report.pop("blue_reflection_title_kscl_probe", None)
    main_report["blue_reflection_title_marker"] = {
        "status": "ok",
        "resource": RESOURCE_PATH,
        "texture": TARGET_TEXTURE_NAME,
        "runtime_status": "confirmed_visible_and_visual_design_approved",
        "label": label,
        "translation_version": version,
    }
    recompute_main_summary(main_report)
    atomic_json(main_report_path, main_report)

    report = {
        "type": REPORT_TYPE,
        "format_version": 1,
        "status": "ok",
        "method": "structural_single_kscl_fnt_credit_replacement",
        "runtime_status": "confirmed_visible_and_visual_design_approved",
        "project_root": "<PROJECT_ROOT>",
        "target_id": TARGET_ID,
        "archive": ARCHIVE_RELATIVE,
        "source_archive_sha256": source_hash,
        "output_archive_sha256": sha256_file(final),
        "resource": resource_details,
        "label": label,
        "translation_version": version,
        "version_source": "workstreams/translation/VERSION",
        "config_path": config_path.relative_to(project_root).as_posix(),
        "config_sha256": sha256_file(config_path),
        "archive_report": archive_entry,
        "extract_tail": extract_tail,
        "safety": {
            "installed_files_modified_during_build": False,
            "proprietary_assets_in_update_package": False,
            "only_one_pak_modified": True,
            "only_one_kscl_modified": True,
            "only_fnt_credit_modified": True,
            "other_embedded_textures_byte_verified": True,
            "texture_payload_size_preserved": True,
            "specific_game_archive_hash_required": False,
            "specific_resource_hash_required": False,
            "full_pak_reextract_verification": True,
            "installation_requires_step_09": True,
        },
    }
    atomic_json(
        project_root / ".local/reports/translation/BR_BLUE_REFLECTION_TITLE_MARKER_REPORT.json",
        report,
    )
    print(f"Original Blue Reflection title marker built: {label}")
    texture = resource_details["target_texture"]
    print(f"Modified embedded texture only: {TARGET_TEXTURE_NAME} ({texture['width']}x{texture['height']})")
    return 0


def self_test() -> int:
    # Validate that the production config can render a representative version
    # and encode to the exact fnt_credit payload size.
    config = {
        "clear": {"rgba": [0, 0, 0, 0]},
        "layout": {
            "text_rect": [0, 0, 480, 32], "align": "center", "max_font_scale": 4,
            "letter_spacing": 1, "padding_x": 4, "padding_y": 2,
        },
        "font": {"thickness": 0, "scale_x": 3, "scale_y": 3},
        "style": {
            "text_rgba": [45, 45, 45, 255], "outline_rgba": [0, 0, 0, 0],
            "outline_radius": 0, "glow_rgba": [0, 0, 0, 0], "glow_radius": 0,
            "glow_blur_passes": 0, "shadow_rgba": [20, 50, 90, 90],
            "shadow_offset": [1, 0], "shadow_blur_passes": 0,
        },
    }
    pixels, metrics = render_label("UNBURGER MOD (v0.0.18)", 480, 32, config)
    encoded = encode_dxt5_image(pixels, 480, 32)
    if len(encoded) != EXPECTED_TEXTURE_RAW_SIZE or metrics["text_height"] != 21:
        raise BR1MarkerError("Synthetic marker self-test failed")
    print("Original Blue Reflection title-marker self-test passed")
    return 0


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser()
    p.add_argument("--project-root")
    p.add_argument("--original-root")
    p.add_argument("--gust-pak")
    p.add_argument("--config")
    p.add_argument("--timeout", type=int, default=1800)
    p.add_argument("--self-test", action="store_true")
    return p


if __name__ == "__main__":
    try:
        args = parser().parse_args()
        if args.self_test:
            raise SystemExit(self_test())
        if not all((args.project_root, args.original_root, args.gust_pak)):
            raise BR1MarkerError("--project-root, --original-root and --gust-pak are required")
        raise SystemExit(build(args))
    except (BR1MarkerError, OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}", file=os.sys.stderr)
        raise SystemExit(1)
