#!/usr/bin/env python3
"""Build the runtime-approved production Quartet launcher label.

Only the runtime-confirmed English b4 ``b0_title.g1t`` is modified, and only
texture ``002.dds`` inside that G1T.  Translation and restoration versions are
read directly from their workstream VERSION files at build time; no version is
duplicated in title-marker configuration.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import shutil
import tempfile
import time
from pathlib import Path
from typing import Any

from second_light_title_marker import (
    FONT as BASE_FONT,
    TitleMarkerError,
    atomic_bytes,
    encode_bc7_mode5_block,
    render_patch as _unused_render_patch,
    write_png,
)
from second_light_title_marker_proof import (
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
from title_resource_pixel_probe import parse_dds

REPORT_TYPE = "br_quartet_title_marker_report"
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
# 002.dds is the runtime-confirmed long bottom strip.  The production marker
# deliberately replaces the complete texture so the original legal/copyright
# line is removed rather than competing with the project label.  Position,
# weight, outline and glow are controlled by the editable JSON config.
CONFIG_RELATIVE = "workstreams/translation_tooling/config/title_markers/quartet_title_marker.json"
LAYOUT_PROFILE = "configurable_anisotropic_visible_band_v9"
DDS_DATA_OFFSET = 148

FONT = dict(BASE_FONT)
FONT.update(
    {
        "(": ("00010", "00100", "01000", "01000", "01000", "00100", "00010"),
        ")": ("01000", "00100", "00010", "00010", "00010", "00100", "01000"),
        "v": ("00000", "00000", "10001", "10001", "10001", "01010", "00100"),
    }
)


class QuartetMarkerError(TitleMarkerError):
    pass


def read_version(project_root: Path, relative: str) -> str:
    path = project_root / relative
    if not path.is_file():
        raise QuartetMarkerError(f"Missing version source: {relative}")
    value = path.read_text(encoding="utf-8").strip()
    if not value:
        raise QuartetMarkerError(f"Empty version source: {relative}")
    unsupported = sorted({char for char in value if char not in FONT})
    if unsupported:
        raise QuartetMarkerError(
            f"Version {relative} contains unsupported label characters: {unsupported}"
        )
    return value


def build_label(project_root: Path, variant: str) -> tuple[str, dict[str, str]]:
    versions: dict[str, str] = {}
    if variant in {"unburger", "combined"}:
        versions["translation"] = read_version(
            project_root, "workstreams/translation/VERSION"
        )
    if variant in {"uncensor", "combined"}:
        versions["uncensor"] = read_version(
            project_root, "workstreams/quartet_restoration/VERSION"
        )

    if variant == "unburger":
        label = f"UNBURGER (v{versions['translation']})"
    elif variant == "uncensor":
        label = f"UNCENSOR (v{versions['uncensor']})"
    elif variant == "combined":
        label = (
            f"UNBURGER (v{versions['translation']}) / "
            f"UNCENSOR (v{versions['uncensor']})"
        )
    else:
        raise QuartetMarkerError(
            f"Unknown variant {variant!r}; expected unburger, uncensor, or combined"
        )

    unsupported = sorted({char for char in label if char not in FONT})
    if unsupported:
        raise QuartetMarkerError(f"Label contains unsupported characters: {unsupported}")
    return label, versions


def blend_pixel(
    pixels: bytearray,
    width: int,
    height: int,
    x: int,
    y: int,
    rgba: tuple[int, int, int, int],
) -> None:
    if x < 0 or y < 0 or x >= width or y >= height:
        return
    offset = (y * width + x) * 4
    sr, sg, sb, sa = rgba
    dr, dg, db, da = pixels[offset : offset + 4]
    if sa == 0:
        return
    out_a = sa + ((da * (255 - sa) + 127) // 255)
    if out_a == 0:
        return
    denom = out_a * 255
    out_r = (sr * sa * 255 + dr * da * (255 - sa) + denom // 2) // denom
    out_g = (sg * sa * 255 + dg * da * (255 - sa) + denom // 2) // denom
    out_b = (sb * sa * 255 + db * da * (255 - sa) + denom // 2) // denom
    pixels[offset : offset + 4] = bytes((out_r, out_g, out_b, out_a))


def _rgba(value: Any, name: str) -> tuple[int, int, int, int]:
    if not isinstance(value, list) or len(value) != 4:
        raise QuartetMarkerError(f"{name} must be an RGBA list with four integers")
    out: list[int] = []
    for item in value:
        if not isinstance(item, int) or isinstance(item, bool) or not 0 <= item <= 255:
            raise QuartetMarkerError(f"{name} values must be integers in 0..255")
        out.append(item)
    return tuple(out)  # type: ignore[return-value]


def _integer(value: Any, name: str, minimum: int, maximum: int) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise QuartetMarkerError(f"{name} must be an integer")
    if not minimum <= value <= maximum:
        raise QuartetMarkerError(f"{name} must be in {minimum}..{maximum}")
    return value


def load_marker_config(project_root: Path, raw_path: str | None) -> tuple[Path, dict[str, Any]]:
    if raw_path:
        candidate = Path(raw_path).expanduser()
        path = candidate if candidate.is_absolute() else project_root / candidate
    else:
        path = project_root / CONFIG_RELATIVE
    path = path.resolve()
    if not path.is_file():
        raise QuartetMarkerError(f"Missing Quartet title-marker config: {path}")
    try:
        config = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise QuartetMarkerError(f"Invalid title-marker JSON: {exc}") from exc
    if not isinstance(config, dict):
        raise QuartetMarkerError("Quartet title-marker config root must be an object")
    if config.get("type") != "br_quartet_title_marker_config":
        raise QuartetMarkerError("Unexpected Quartet title-marker config type")
    if config.get("format_version") != 1:
        raise QuartetMarkerError("Unsupported Quartet title-marker config format_version")

    clear = config.get("clear")
    layout = config.get("layout")
    font = config.get("font")
    style = config.get("style")
    if not all(isinstance(item, dict) for item in (clear, layout, font, style)):
        raise QuartetMarkerError("Config requires clear, layout, font and style objects")

    _rgba(clear.get("rgba"), "clear.rgba")
    rect = layout.get("text_rect")
    if not isinstance(rect, list) or len(rect) != 4:
        raise QuartetMarkerError("layout.text_rect must contain x, y, width and height")
    for index, item in enumerate(rect):
        _integer(item, f"layout.text_rect[{index}]", 0, 4096)
    if layout.get("align") not in {"left", "center", "right"}:
        raise QuartetMarkerError("layout.align must be left, center or right")
    _integer(layout.get("max_font_scale"), "layout.max_font_scale", 1, 16)
    _integer(layout.get("letter_spacing"), "layout.letter_spacing", 0, 8)
    _integer(layout.get("padding_x"), "layout.padding_x", 0, 256)
    _integer(layout.get("padding_y"), "layout.padding_y", 0, 64)
    _integer(font.get("thickness"), "font.thickness", 0, 4)
    scale_x = font.get("scale_x")
    scale_y = font.get("scale_y")
    if (scale_x is None) != (scale_y is None):
        raise QuartetMarkerError("font.scale_x and font.scale_y must be provided together")
    if scale_x is not None:
        _integer(scale_x, "font.scale_x", 1, 16)
        _integer(scale_y, "font.scale_y", 1, 16)
    row_groups = font.get("row_groups")
    if row_groups is not None:
        if not isinstance(row_groups, list) or not row_groups:
            raise QuartetMarkerError("font.row_groups must be a non-empty list when provided")
        seen = []
        for group_index, group in enumerate(row_groups):
            if not isinstance(group, list) or not group:
                raise QuartetMarkerError(f"font.row_groups[{group_index}] must be a non-empty list of row indices")
            for row_index, row in enumerate(group):
                _integer(row, f"font.row_groups[{group_index}][{row_index}]", 0, 6)
                seen.append(row)
        if sorted(set(seen)) != list(range(7)):
            raise QuartetMarkerError("font.row_groups must cover source rows 0..6 at least once")
    _rgba(style.get("text_rgba"), "style.text_rgba")
    _rgba(style.get("outline_rgba"), "style.outline_rgba")
    _integer(style.get("outline_radius"), "style.outline_radius", 0, 6)
    _rgba(style.get("glow_rgba"), "style.glow_rgba")
    _integer(style.get("glow_radius"), "style.glow_radius", 0, 12)
    _integer(style.get("glow_blur_passes"), "style.glow_blur_passes", 0, 8)
    _rgba(style.get("shadow_rgba"), "style.shadow_rgba")
    offset = style.get("shadow_offset")
    if not isinstance(offset, list) or len(offset) != 2:
        raise QuartetMarkerError("style.shadow_offset must contain x and y")
    for index, item in enumerate(offset):
        _integer(item, f"style.shadow_offset[{index}]", -32, 32)
    _integer(style.get("shadow_blur_passes"), "style.shadow_blur_passes", 0, 8)
    return path, config


def text_mask(
    label: str,
    width: int,
    height: int,
    config: dict[str, Any],
) -> tuple[list[int], dict[str, Any]]:
    layout = config["layout"]
    x, y, rect_width, rect_height = layout["text_rect"]
    if x + rect_width > width or y + rect_height > height:
        raise QuartetMarkerError(
            f"layout.text_rect {layout['text_rect']} is outside {width}x{height}"
        )
    padding_x = layout["padding_x"]
    padding_y = layout["padding_y"]
    letter_spacing = layout["letter_spacing"]
    font = config["font"]
    row_groups = font.get("row_groups") or [[0], [1], [2], [3], [4], [5], [6]]
    glyph_rows = len(row_groups)
    glyph_columns = 5 * len(label) + letter_spacing * max(0, len(label) - 1)
    available_width = rect_width - 2 * padding_x
    available_height = rect_height - 2 * padding_y
    scale_x = font.get("scale_x")
    scale_y = font.get("scale_y")
    if scale_x is None:
        max_scale_width = available_width // max(1, glyph_columns)
        max_scale_height = available_height // glyph_rows
        scale_x = scale_y = min(layout["max_font_scale"], max_scale_width, max_scale_height)
        if scale_x < 1 or scale_y < 1:
            raise QuartetMarkerError(
                f"Label does not fit layout.text_rect {layout['text_rect']}: {label}"
            )
    else:
        if glyph_columns * scale_x > available_width or glyph_rows * scale_y > available_height:
            raise QuartetMarkerError(
                f"Configured font.scale_x/font.scale_y do not fit layout.text_rect {layout['text_rect']}: {label}"
            )
    text_width = glyph_columns * scale_x
    text_height = glyph_rows * scale_y
    if layout["align"] == "left":
        start_x = x + padding_x
    elif layout["align"] == "right":
        start_x = x + rect_width - padding_x - text_width
    else:
        start_x = x + (rect_width - text_width) // 2
    start_y = y + (rect_height - text_height) // 2
    mask = [0] * (width * height)
    cursor = start_x
    advance = (5 + letter_spacing) * scale_x
    for char in label:
        glyph = FONT[char]
        grouped_rows = []
        for group in row_groups:
            row_bits = []
            for column in range(5):
                bit = '1' if any(glyph[source_row][column] == '1' for source_row in group) else '0'
                row_bits.append(bit)
            grouped_rows.append(''.join(row_bits))
        for row, bits in enumerate(grouped_rows):
            for column, bit in enumerate(bits):
                if bit != "1":
                    continue
                for dy in range(scale_y):
                    for dx in range(scale_x):
                        px = cursor + column * scale_x + dx
                        py = start_y + row * scale_y + dy
                        if 0 <= px < width and 0 <= py < height:
                            mask[py * width + px] = 255
        cursor += advance
    return mask, {
        "layout_profile": LAYOUT_PROFILE,
        "text_rect": list(layout["text_rect"]),
        "align": layout["align"],
        "font_scale_x": scale_x,
        "font_scale_y": scale_y,
        "letter_spacing": letter_spacing,
        "text_width": text_width,
        "text_height": text_height,
        "text_x": start_x,
        "text_y": start_y,
    }


def dilate(mask: list[int], width: int, height: int, radius: int) -> list[int]:
    if radius <= 0:
        return list(mask)
    out = [0] * len(mask)
    for y in range(height):
        for x in range(width):
            best = 0
            for dy in range(-radius, radius + 1):
                py = y + dy
                if py < 0 or py >= height:
                    continue
                for dx in range(-radius, radius + 1):
                    px = x + dx
                    if 0 <= px < width:
                        best = max(best, mask[py * width + px])
            out[y * width + x] = best
    return out


def blur(mask: list[int], width: int, height: int) -> list[int]:
    weights = ((1, 2, 1), (2, 4, 2), (1, 2, 1))
    out = [0] * len(mask)
    for y in range(height):
        for x in range(width):
            total = 0
            weight_sum = 0
            for ky, row in enumerate(weights):
                py = y + ky - 1
                if py < 0 or py >= height:
                    continue
                for kx, weight in enumerate(row):
                    px = x + kx - 1
                    if px < 0 or px >= width:
                        continue
                    total += mask[py * width + px] * weight
                    weight_sum += weight
            out[y * width + x] = (total + weight_sum // 2) // weight_sum
    return out


def repeated_blur(mask: list[int], width: int, height: int, passes: int) -> list[int]:
    out = list(mask)
    for _ in range(passes):
        out = blur(out, width, height)
    return out


def shifted_mask(
    mask: list[int], width: int, height: int, offset_x: int, offset_y: int
) -> list[int]:
    out = [0] * len(mask)
    for y in range(height):
        for x in range(width):
            source_x = x - offset_x
            source_y = y - offset_y
            if 0 <= source_x < width and 0 <= source_y < height:
                out[y * width + x] = mask[source_y * width + source_x]
    return out


def render_label(
    label: str,
    width: int,
    height: int,
    config: dict[str, Any],
) -> tuple[bytearray, dict[str, Any]]:
    base_mask, metrics = text_mask(label, width, height, config)
    font = config["font"]
    style = config["style"]
    fill_mask = dilate(base_mask, width, height, font["thickness"])
    outline_mask = dilate(fill_mask, width, height, style["outline_radius"])
    glow_mask = repeated_blur(
        dilate(fill_mask, width, height, style["glow_radius"]),
        width,
        height,
        style["glow_blur_passes"],
    )
    shadow_mask = repeated_blur(
        shifted_mask(
            fill_mask,
            width,
            height,
            style["shadow_offset"][0],
            style["shadow_offset"][1],
        ),
        width,
        height,
        style["shadow_blur_passes"],
    )

    clear_rgba = _rgba(config["clear"]["rgba"], "clear.rgba")
    pixels = bytearray(bytes(clear_rgba) * (width * height))
    text_rgba = _rgba(style["text_rgba"], "style.text_rgba")
    outline_rgba = _rgba(style["outline_rgba"], "style.outline_rgba")
    glow_rgba = _rgba(style["glow_rgba"], "style.glow_rgba")
    shadow_rgba = _rgba(style["shadow_rgba"], "style.shadow_rgba")

    def paint(mask: list[int], rgba: tuple[int, int, int, int], exclude: list[int] | None = None) -> None:
        for py in range(height):
            for px in range(width):
                index = py * width + px
                if mask[index] == 0 or (exclude is not None and exclude[index] != 0):
                    continue
                alpha = (mask[index] * rgba[3] + 127) // 255
                blend_pixel(pixels, width, height, px, py, (rgba[0], rgba[1], rgba[2], alpha))

    paint(glow_mask, glow_rgba)
    paint(shadow_mask, shadow_rgba)
    paint(outline_mask, outline_rgba, fill_mask)
    paint(fill_mask, text_rgba)

    return pixels, {
        **metrics,
        "replacement_mode": "replace_entire_002_dds",
        "clear_rgba": list(clear_rgba),
        "font_thickness": font["thickness"],
        "text_rgba": list(text_rgba),
        "outline_rgba": list(outline_rgba),
        "outline_radius": style["outline_radius"],
        "glow_rgba": list(glow_rgba),
        "glow_radius": style["glow_radius"],
        "glow_blur_passes": style["glow_blur_passes"],
        "shadow_rgba": list(shadow_rgba),
        "shadow_offset": list(style["shadow_offset"]),
        "shadow_blur_passes": style["shadow_blur_passes"],
        "encoder": "BC7 mode 5 with independent colour and alpha selectors",
    }

def validate_dds(path: Path, expected: dict[str, Any]) -> dict[str, Any]:
    payload_sha256 = sha256_file(path)
    meta = parse_dds(path.read_bytes())
    if meta.get("format") != "BC7" or meta.get("dxgi") not in {98, 99}:
        raise QuartetMarkerError(f"Expected BC7 payload: {path.name}")
    if (meta.get("width"), meta.get("height")) != (
        expected["width"],
        expected["height"],
    ):
        raise QuartetMarkerError(f"Unexpected dimensions for {path.name}")
    if meta.get("mipmaps") != 1:
        raise QuartetMarkerError(f"Expected one mipmap for {path.name}")
    meta["payload_sha256"] = payload_sha256
    meta["source_compatibility"] = (
        "known_runtime_profile"
        if payload_sha256 == expected["sha256"]
        else "structurally_compatible_current_baseline"
    )
    return meta


def patch_target_dds(
    dds: Path,
    label: str,
    preview: Path,
    config: dict[str, Any],
) -> dict[str, Any]:
    original = dds.read_bytes()
    meta = validate_dds(dds, EXPECTED_TEXTURES[dds.name])
    width = meta["width"]
    height = meta["height"]
    if width % 4 or height % 4:
        raise QuartetMarkerError(f"002.dds is not BC7 block aligned: {width}x{height}")

    pixels, render = render_label(label, width, height, config)
    write_png(preview, width, height, pixels)
    output = bytearray(original)
    blocks_x = width // 4
    blocks_y = height // 4
    for block_y in range(blocks_y):
        for block_x in range(blocks_x):
            block: list[tuple[int, int, int, int]] = []
            for dy in range(4):
                for dx in range(4):
                    px = block_x * 4 + dx
                    py = block_y * 4 + dy
                    offset = (py * width + px) * 4
                    block.append(tuple(pixels[offset : offset + 4]))  # type: ignore[arg-type]
            encoded = encode_bc7_mode5_block(block)
            target = DDS_DATA_OFFSET + (block_y * blocks_x + block_x) * 16
            output[target : target + 16] = encoded

    before = hashlib.sha256(original).hexdigest()
    after = hashlib.sha256(output).hexdigest()
    if before == after:
        raise QuartetMarkerError("Marker replacement made no DDS change")
    atomic_bytes(dds, bytes(output))
    return {
        "texture": dds.name,
        "before_sha256": before,
        "after_sha256": after,
        "dds_dimensions": [width, height],
        "patch_rect": [0, 0, width, height],
        "patched_bc7_blocks": blocks_x * blocks_y,
        "preview_path": preview,
        "preview_sha256": sha256_file(preview),
        **render,
    }


def patch_g1t(
    source: Path,
    work: Path,
    gust_g1t: Path,
    label: str,
    config: dict[str, Any],
    timeout: int,
) -> tuple[Path, dict[str, Any]]:
    work.mkdir(parents=True, exist_ok=True)
    local = work / source.name
    shutil.copy2(source, local)
    original_g1t_sha256 = sha256_file(local)

    listing = run_checked(
        [str(gust_g1t), "-l", local.name],
        cwd=work,
        timeout=timeout,
        description="list original Quartet b0_title.g1t",
    )
    extract_result = run_checked(
        [str(gust_g1t), "-y", local.name],
        cwd=work,
        timeout=timeout,
        description="extract original Quartet b0_title.g1t",
    )
    source_dir = work / source.stem
    dds_files = sorted(source_dir.glob("*.dds"))
    if [path.name for path in dds_files] != list(EXPECTED_TEXTURES):
        raise QuartetMarkerError(f"Unexpected b0_title DDS inventory: {[p.name for p in dds_files]}")
    before_hashes = {}
    for dds in dds_files:
        validate_dds(dds, EXPECTED_TEXTURES[dds.name])
        before_hashes[dds.name] = sha256_file(dds)

    preview = work.parent / "QUARTET_TITLE_MARKER_preview.png"
    patch_details = patch_target_dds(source_dir / "002.dds", label, preview, config)
    after_hashes = {path.name: sha256_file(path) for path in dds_files}
    if before_hashes["000.dds"] != after_hashes["000.dds"]:
        raise QuartetMarkerError("000.dds changed unexpectedly")
    if before_hashes["001.dds"] != after_hashes["001.dds"]:
        raise QuartetMarkerError("001.dds changed unexpectedly")
    if before_hashes["002.dds"] == after_hashes["002.dds"]:
        raise QuartetMarkerError("002.dds did not change")

    original_copy = work / f"{source.stem}.original.g1t"
    os.replace(local, original_copy)
    rebuilt = run_checked(
        [str(gust_g1t), "-y", str(source_dir)],
        cwd=work,
        timeout=timeout,
        description="rebuild Quartet b0_title.g1t marker",
    )
    if not local.is_file():
        raise QuartetMarkerError("gust_g1t did not rebuild b0_title.g1t")

    verify = work / "verify"
    verify.mkdir()
    verify_g1t = verify / local.name
    shutil.copy2(local, verify_g1t)
    verify_result = run_checked(
        [str(gust_g1t), "-y", verify_g1t.name],
        cwd=verify,
        timeout=timeout,
        description="verify rebuilt Quartet b0_title.g1t marker",
    )
    verified = sorted((verify / source.stem).glob("*.dds"))
    verified_hashes = {path.name: sha256_file(path) for path in verified}
    if verified_hashes != after_hashes:
        raise QuartetMarkerError("Re-extracted b0_title payload hashes do not match")

    return local, {
        "resource_path": RESOURCE_PATH,
        "original_sha256": original_g1t_sha256,
        "source_compatibility": (
            "known_runtime_profile"
            if original_g1t_sha256 == EXPECTED_G1T_SHA256
            else "structurally_compatible_current_baseline"
        ),
        "rebuilt_sha256": sha256_file(local),
        "texture_hashes_before": before_hashes,
        "texture_hashes_after": after_hashes,
        "modified_texture": "002.dds",
        "patch": patch_details,
        "listing_tail": listing.stdout.splitlines()[-10:],
        "extract_tail": extract_result.stdout.splitlines()[-10:],
        "rebuild_tail": rebuilt.stdout.splitlines()[-10:],
        "verify_tail": verify_result.stdout.splitlines()[-10:],
    }


def build(args: argparse.Namespace) -> int:
    project_root = Path(args.project_root).expanduser().resolve()
    quartet_root = Path(args.quartet_root).expanduser().resolve()
    gust_pak = Path(args.gust_pak).expanduser().resolve()
    gust_g1t = Path(args.gust_g1t).expanduser().resolve()
    variant = args.variant.strip().lower()
    label, versions = build_label(project_root, variant)
    config_path, marker_config = load_marker_config(project_root, args.config)
    config_hash = sha256_file(config_path)

    source_pak = quartet_root / ARCHIVE_RELATIVE
    if not source_pak.is_file():
        raise QuartetMarkerError(f"Missing Quartet source archive: {source_pak}")
    source_hash = sha256_file(source_pak)

    main_report_path = project_root / ".local/reports/translation/BR_TRANSLATION_PAK_REPACK_REPORT.json"
    if not main_report_path.is_file():
        raise QuartetMarkerError("Translation repack report missing; run clean steps 07 and 08")
    main_report = json.loads(main_report_path.read_text(encoding="utf-8"))
    if main_report.get("status") != "ok":
        raise QuartetMarkerError("Translation repack report is not ok")
    replaced_previous_local_output = any(
        entry.get("target_id") == TARGET_ID
        and entry.get("archive_relative_path") == ARCHIVE_RELATIVE
        for entry in main_report.get("archives", [])
        if isinstance(entry, dict)
    )
    # A previous Quartet marker/probe may still be present only in the local
    # build output. The source for this build is always the hash-verified
    # installed baseline PAK, and the archive/report entry is replaced below.

    build_root = project_root / ".local/build/translation"
    with tempfile.TemporaryDirectory(prefix=".br_quartet_title_marker.", dir=build_root) as raw_tmp:
        temp_root = Path(raw_tmp)
        stage = temp_root / "stage"
        manifest, extract_tail = extract_pak(gust_pak, source_pak, stage, args.timeout)
        entries, _ = list_pak_entries(gust_pak, source_pak, temp_root, args.timeout)
        normalized = {entry.casefold(): entry for entry in entries}
        key = RESOURCE_PATH.casefold()
        if key not in normalized:
            raise QuartetMarkerError(f"Resource not present in source PAK: {RESOURCE_PATH}")
        staged_g1t = stage / Path(normalized[key])
        if not staged_g1t.is_file():
            raise QuartetMarkerError(f"Extracted resource missing: {staged_g1t}")

        rebuilt_g1t, details = patch_g1t(
            staged_g1t, temp_root / "g1t", gust_g1t, label, marker_config, args.timeout
        )
        install_verified_output(rebuilt_g1t, staged_g1t)
        built, repack_tail = repack_stage(
            gust_pak, stage, manifest, ARCHIVE_STEM, args.timeout
        )
        checked, failures, listing_tail = verify_repacked(
            gust_pak, built, stage, temp_root / "verify_pak", args.timeout
        )
        if failures:
            raise QuartetMarkerError(f"PAK verification failed: {failures[:3]}")

        final = build_root / "archives" / TARGET_ID / ARCHIVE_RELATIVE
        install_verified_output(built, final)
        preview_source = Path(details["patch"]["preview_path"])
        preview_final = build_root / "quartet_title_marker" / "QUARTET_TITLE_MARKER_preview.png"
        preview_final.parent.mkdir(parents=True, exist_ok=True)
        install_verified_output(preview_source, preview_final)
        details["patch"]["preview_path"] = preview_final

    main_report["archives"] = [
        entry
        for entry in main_report.get("archives", [])
        if not (
            isinstance(entry, dict)
            and entry.get("target_id") == TARGET_ID
            and entry.get("archive_relative_path") == ARCHIVE_RELATIVE
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
        "source_policy": "current_installation_baseline_extraction_plus_verified_marker_overlay",
        "source_archive_sha256": source_hash,
        "source_archive_bytes": source_pak.stat().st_size,
        "changed_members": [RESOURCE_PATH],
        "full_reextract_verified": not failures and checked == len(entries),
    }
    main_report["archives"].append(archive_entry)
    main_report["archives"].sort(
        key=lambda entry: (str(entry.get("target_id")), str(entry.get("archive_relative_path")))
    )
    for old_key in (
        "title_resource_pixel_probe",
        "quartet_b0_title_texture_probe",
        "quartet_title_marker",
    ):
        main_report.pop(old_key, None)
    main_report["quartet_title_marker"] = {
        "status": "ok",
        "variant": variant,
        "label": label,
        "versions": versions,
        "resource": RESOURCE_PATH,
        "modified_texture": "002.dds",
        "patch_rect": [0, 0, 1760, 100],
        "runtime_status": "confirmed_visible_and_visual_design_approved",
        "layout_profile": LAYOUT_PROFILE,
        "config_path": config_path.relative_to(project_root).as_posix() if config_path.is_relative_to(project_root) else str(config_path),
        "config_sha256": config_hash,
        "replaced_previous_local_output": replaced_previous_local_output,
    }
    recompute_main_summary(main_report)
    atomic_json(main_report_path, main_report)

    report = {
        "type": REPORT_TYPE,
        "format_version": 1,
        "status": "ok",
        "generated_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "runtime_status": "confirmed_visible_and_visual_design_approved",
        "project_root": "<PROJECT_ROOT>",
        "target_id": TARGET_ID,
        "archive": ARCHIVE_RELATIVE,
        "source_archive_sha256": source_hash,
        "output_archive_sha256": sha256_file(final),
        "variant": variant,
        "label": label,
        "versions": versions,
        "layout_profile": LAYOUT_PROFILE,
        "config_path": config_path.relative_to(project_root).as_posix() if config_path.is_relative_to(project_root) else str(config_path),
        "config_sha256": config_hash,
        "config": marker_config,
        "replaced_previous_local_output": replaced_previous_local_output,
        "version_sources": {
            "translation": "workstreams/translation/VERSION",
            "uncensor": "workstreams/quartet_restoration/VERSION",
        },
        "resource": details,
        "archive_report": archive_entry,
        "extract_tail": extract_tail,
        "safety": {
            "installed_files_modified_during_build": False,
            "proprietary_assets_in_update_package": False,
            "only_one_g1t_modified": True,
            "only_002_dds_modified": True,
            "full_g1t_reextract_verification": True,
            "full_pak_reextract_verification": True,
            "specific_game_archive_hash_required": False,
            "specific_g1t_hash_required": False,
            "installation_requires_step_09": True,
        },
    }
    report["resource"]["patch"]["preview_path"] = (
        Path(report["resource"]["patch"]["preview_path"])
        .relative_to(project_root)
        .as_posix()
    )
    atomic_json(
        project_root / ".local/reports/translation/BR_QUARTET_TITLE_MARKER_REPORT.json",
        report,
    )

    print("Quartet production title marker built and fully verified.")
    print(f"Variant: {variant}")
    print(f"Label: {label}")
    print(f"Modified resource: {RESOURCE_PATH} -> 002.dds")
    print(f"Layout profile: {LAYOUT_PROFILE}")
    print("Replacement rectangle: (0, 0, 1760, 100)")
    print(f"Editable config: {config_path}")
    print(f"Output PAK: {final}")
    print(f"Preview: {preview_final}")
    print("No installed game file was modified during the build.")
    return 0


def parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-root", required=True)
    parser.add_argument("--quartet-root", required=True)
    parser.add_argument("--gust-pak", required=True)
    parser.add_argument("--gust-g1t", required=True)
    parser.add_argument(
        "--variant",
        choices=("unburger", "uncensor", "combined"),
        default="combined",
    )
    parser.add_argument(
        "--config",
        help=(
            "Optional Quartet marker JSON path. Relative paths are resolved from "
            "--project-root; default: " + CONFIG_RELATIVE
        ),
    )
    parser.add_argument("--timeout", type=int, default=900)
    return parser


if __name__ == "__main__":
    try:
        raise SystemExit(build(parser().parse_args()))
    except (QuartetMarkerError, OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}", file=os.sys.stderr)
        raise SystemExit(1)
