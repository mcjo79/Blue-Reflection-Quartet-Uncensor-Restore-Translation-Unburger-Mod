#!/usr/bin/env python3
"""Build the runtime-approved polished Second Light title marker.

The update package contains no game asset. This tool extracts the user's local
English ``seed_title.g1t`` from the installed ``PACK00_04_01.PAK``, replaces
only the block-aligned overseas-copyright rectangle with a transparent label
using BC7 mode 5, rebuilds the same G1T under the same internal path, and fully
verifies the rebuilt PAK.
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
import time
import zlib
from pathlib import Path
from typing import Any

from second_light_title_marker_proof import (
    FONT,
    ProofError,
    archive_report_entry,
    atomic_bytes,
    atomic_json,
    extract_pak,
    install_verified_output,
    list_pak_entries,
    recompute_main_summary,
    repack_stage,
    run_checked,
    safe_marker,
    sha256_file,
    verify_repacked,
)


TARGET_ID = "second_light_original"
RESOURCE_ARCHIVE = "Data/PACK00_04_01.PAK"
RESOURCE_STEM = "PACK00_04_01"
RESOURCE_INTERNAL = "data/x64/res_en/ui/seed_title.g1t"
DEFAULT_MARKER = "UNBURGER / UNCENSOR"
REPORT_TYPE = "br_second_light_title_marker_report"

# uis_gen_seed_title.xml uses resolution_hd=2160 coordinates while the DDS is
# 1024 pixels wide. The known overseas copyright region is:
#   uvwh="514,844,1356,41"
# Therefore the DDS crop is approximately (257, 422, 678, 21). We patch the
# smallest surrounding BC7 block rectangle so no partial 4x4 block is edited.
STYLE_UVWH = (514, 844, 1356, 41)
DDS_CROP = (257, 422, 678, 21)
PATCH_RECT = (256, 420, 680, 24)
EXPECTED_DDS_SIZE = (1024, 1428)
DDS_DATA_OFFSET = 148
DDS_FOURCC = b"DX10"
DXGI_FORMAT_BC7_UNORM = 98


class TitleMarkerError(ProofError):
    pass


def png_chunk(kind: bytes, payload: bytes) -> bytes:
    return (
        struct.pack(">I", len(payload))
        + kind
        + payload
        + struct.pack(">I", zlib.crc32(kind + payload) & 0xFFFFFFFF)
    )


def write_png(path: Path, width: int, height: int, pixels: bytes) -> None:
    rows = bytearray()
    stride = width * 4
    for y in range(height):
        rows.append(0)
        rows.extend(pixels[y * stride : (y + 1) * stride])
    data = (
        b"\x89PNG\r\n\x1a\n"
        + png_chunk(
            b"IHDR",
            struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0),
        )
        + png_chunk(b"IDAT", zlib.compress(bytes(rows), 9))
        + png_chunk(b"IEND", b"")
    )
    atomic_bytes(path, data)


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
        pixels[offset : offset + 4] = b"\0\0\0\0"
        return
    denom = out_a * 255
    out_r = (sr * sa * 255 + dr * da * (255 - sa) + denom // 2) // denom
    out_g = (sg * sa * 255 + dg * da * (255 - sa) + denom // 2) // denom
    out_b = (sb * sa * 255 + db * da * (255 - sa) + denom // 2) // denom
    pixels[offset : offset + 4] = bytes((out_r, out_g, out_b, out_a))


def build_text_mask(marker: str, width: int, height: int) -> tuple[list[int], dict[str, int]]:
    for char in marker:
        if char not in FONT:
            raise TitleMarkerError(f"No bitmap glyph for {char!r}")
    # A smaller two-pixel cell height leaves breathing room around the label
    # and reads closer to the original copyright treatment than the proof bar.
    scale = min(
        2,
        max(1, (height - 6) // 7),
        max(1, (width - 24) // max(1, 6 * len(marker) - 1)),
    )
    text_width = (6 * len(marker) - 1) * scale
    text_height = 7 * scale
    x = (width - text_width) // 2
    y = (height - text_height) // 2 - 1
    mask = [0] * (width * height)
    cursor = x
    for char in marker:
        glyph = FONT[char]
        for row, bits in enumerate(glyph):
            for column, bit in enumerate(bits):
                if bit != "1":
                    continue
                for dy in range(scale):
                    for dx in range(scale):
                        px = cursor + column * scale + dx
                        py = y + row * scale + dy
                        if 0 <= px < width and 0 <= py < height:
                            mask[py * width + px] = 255
        cursor += 6 * scale
    return mask, {
        "font_scale": scale,
        "text_width": text_width,
        "text_height": text_height,
        "text_x": x,
        "text_y": y,
    }


def dilate_mask(mask: list[int], width: int, height: int, radius: int) -> list[int]:
    output = [0] * len(mask)
    for y in range(height):
        for x in range(width):
            best = 0
            for dy in range(-radius, radius + 1):
                py = y + dy
                if py < 0 or py >= height:
                    continue
                for dx in range(-radius, radius + 1):
                    px = x + dx
                    if px < 0 or px >= width:
                        continue
                    best = max(best, mask[py * width + px])
            output[y * width + x] = best
    return output


def blur_mask(mask: list[int], width: int, height: int) -> list[int]:
    # Compact 3x3 Gaussian-like kernel. It is intentionally deterministic and
    # keeps the build independent of Pillow, ImageMagick and system fonts.
    weights = ((1, 2, 1), (2, 4, 2), (1, 2, 1))
    output = [0] * len(mask)
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
            output[y * width + x] = (total + weight_sum // 2) // weight_sum
    return output


def render_patch(marker: str, width: int, height: int) -> tuple[bytearray, dict[str, Any]]:
    mask, metrics = build_text_mask(marker, width, height)
    outline = dilate_mask(mask, width, height, 1)

    shifted = [0] * len(mask)
    for y in range(height):
        for x in range(width):
            src_x = x - 1
            src_y = y - 2
            if 0 <= src_x < width and 0 <= src_y < height:
                shifted[y * width + x] = mask[src_y * width + src_x]
    shadow = blur_mask(blur_mask(shifted, width, height), width, height)

    pixels = bytearray(width * height * 4)
    for y in range(height):
        for x in range(width):
            index = y * width + x
            shadow_alpha = (shadow[index] * 145 + 127) // 255
            if shadow_alpha:
                blend_pixel(pixels, width, height, x, y, (5, 10, 20, shadow_alpha))

            if outline[index] and not mask[index]:
                outline_alpha = (outline[index] * 205 + 127) // 255
                blend_pixel(pixels, width, height, x, y, (20, 31, 52, outline_alpha))

            if mask[index]:
                # Slightly cool white matches the title-screen palette while
                # retaining enough contrast over both light and dark scenes.
                blend_pixel(pixels, width, height, x, y, (239, 247, 255, 250))

    return pixels, {
        **metrics,
        "background": "transparent",
        "text_rgba": [239, 247, 255, 250],
        "outline_rgba": [20, 31, 52, 205],
        "shadow_rgba_max": [5, 10, 20, 145],
        "shadow_offset": [1, 2],
        "encoder": "BC7 mode 5 with independent colour and alpha selectors",
    }


BC7_WEIGHTS_2BIT = (0, 21, 43, 64)


def quantize_7bit(value: int) -> int:
    return max(0, min(127, (value * 127 + 127) // 255))


def expand_7bit(value: int) -> int:
    return (value << 1) | (value >> 6)


def interpolate(endpoint0: int, endpoint1: int, weight: int) -> int:
    return ((64 - weight) * endpoint0 + weight * endpoint1 + 32) >> 6


def farthest_rgb_pair(pixels: list[tuple[int, int, int, int]]) -> tuple[tuple[int, int, int], tuple[int, int, int]]:
    colours = list(dict.fromkeys(pixel[:3] for pixel in pixels))
    if len(colours) == 1:
        return colours[0], colours[0]
    best = (colours[0], colours[1])
    best_distance = -1
    for index, first in enumerate(colours):
        for second in colours[index + 1 :]:
            distance = sum((first[channel] - second[channel]) ** 2 for channel in range(3))
            if distance > best_distance:
                best = (first, second)
                best_distance = distance
    return best


def encode_bc7_mode5_block(pixels: list[tuple[int, int, int, int]]) -> bytes:
    """Encode one RGBA block with BC7 mode 5.

    Mode 5 gives colour and alpha independent two-bit selector sets. That is
    the smallest self-contained BC7 mode suitable for transparent background,
    dark shadow/outline and light text in the same 4x4 block.
    """
    if len(pixels) != 16:
        raise TitleMarkerError(f"BC7 block requires 16 pixels, found {len(pixels)}")

    rgb0, rgb1 = farthest_rgb_pair(pixels)
    endpoint0 = tuple(quantize_7bit(value) for value in rgb0)
    endpoint1 = tuple(quantize_7bit(value) for value in rgb1)
    expanded0 = tuple(expand_7bit(value) for value in endpoint0)
    expanded1 = tuple(expand_7bit(value) for value in endpoint1)
    palette = [
        tuple(interpolate(expanded0[channel], expanded1[channel], weight) for channel in range(3))
        for weight in BC7_WEIGHTS_2BIT
    ]
    colour_indices = [
        min(
            range(4),
            key=lambda choice: sum(
                (pixel[channel] - palette[choice][channel]) ** 2 for channel in range(3)
            ),
        )
        for pixel in pixels
    ]
    if colour_indices[0] >= 2:
        endpoint0, endpoint1 = endpoint1, endpoint0
        colour_indices = [3 - value for value in colour_indices]

    alpha0 = min(pixel[3] for pixel in pixels)
    alpha1 = max(pixel[3] for pixel in pixels)
    alpha_palette = [interpolate(alpha0, alpha1, weight) for weight in BC7_WEIGHTS_2BIT]
    alpha_indices = [
        min(range(4), key=lambda choice: abs(pixel[3] - alpha_palette[choice]))
        for pixel in pixels
    ]
    if alpha_indices[0] >= 2:
        alpha0, alpha1 = alpha1, alpha0
        alpha_indices = [3 - value for value in alpha_indices]

    packed = 0
    bit_offset = 0

    def put(value: int, bits: int) -> None:
        nonlocal packed, bit_offset
        if value < 0 or value >= (1 << bits):
            raise TitleMarkerError(f"BC7 value {value} does not fit in {bits} bits")
        packed |= value << bit_offset
        bit_offset += bits

    # Unary mode prefix: five zero bits followed by one bit for mode 5.
    put(1 << 5, 6)
    put(0, 2)  # no component rotation
    for channel in range(3):
        put(endpoint0[channel], 7)
        put(endpoint1[channel], 7)
    put(alpha0, 8)
    put(alpha1, 8)
    for index, selector in enumerate(colour_indices):
        put(selector, 1 if index == 0 else 2)
    for index, selector in enumerate(alpha_indices):
        put(selector, 1 if index == 0 else 2)
    if bit_offset != 128:
        raise TitleMarkerError(f"BC7 mode-5 block used {bit_offset} bits instead of 128")
    return packed.to_bytes(16, "little")


def parse_dds_bc7(data: bytes) -> dict[str, int]:
    if len(data) < DDS_DATA_OFFSET or data[:4] != b"DDS ":
        raise TitleMarkerError("Extracted title texture is not a DDS file")
    header_size = struct.unpack_from("<I", data, 4)[0]
    height = struct.unpack_from("<I", data, 12)[0]
    width = struct.unpack_from("<I", data, 16)[0]
    mipmaps = struct.unpack_from("<I", data, 28)[0]
    pixel_format_size = struct.unpack_from("<I", data, 76)[0]
    fourcc = data[84:88]
    if header_size != 124 or pixel_format_size != 32:
        raise TitleMarkerError(
            f"Unexpected DDS header sizes: header={header_size}, pixel_format={pixel_format_size}"
        )
    if fourcc != DDS_FOURCC:
        raise TitleMarkerError(f"Expected DX10 DDS, found FourCC {fourcc!r}")
    dxgi_format, resource_dimension, misc_flag, array_size, misc_flags2 = struct.unpack_from("<IIIII", data, 128)
    if dxgi_format != DXGI_FORMAT_BC7_UNORM:
        raise TitleMarkerError(
            f"Expected DXGI_FORMAT_BC7_UNORM ({DXGI_FORMAT_BC7_UNORM}), found {dxgi_format}"
        )
    if resource_dimension != 3 or array_size != 1:
        raise TitleMarkerError(
            f"Unexpected DDS DX10 resource metadata: dimension={resource_dimension}, array={array_size}"
        )
    if (width, height) != EXPECTED_DDS_SIZE:
        raise TitleMarkerError(
            f"Expected {EXPECTED_DDS_SIZE[0]}x{EXPECTED_DDS_SIZE[1]} DDS, found {width}x{height}"
        )
    if mipmaps not in {0, 1}:
        raise TitleMarkerError(f"Expected one title-atlas mip level, found {mipmaps}")
    blocks_x = math.ceil(width / 4)
    blocks_y = math.ceil(height / 4)
    expected_bytes = DDS_DATA_OFFSET + blocks_x * blocks_y * 16
    if len(data) != expected_bytes:
        raise TitleMarkerError(
            f"Unexpected BC7 payload size: {len(data)} != {expected_bytes}"
        )
    return {
        "width": width,
        "height": height,
        "mipmaps": mipmaps,
        "blocks_x": blocks_x,
        "blocks_y": blocks_y,
        "expected_bytes": expected_bytes,
        "dxgi_format": dxgi_format,
        "resource_dimension": resource_dimension,
        "array_size": array_size,
    }


def patch_dds(dds_path: Path, marker: str, preview_path: Path) -> dict[str, Any]:
    original = dds_path.read_bytes()
    metadata = parse_dds_bc7(original)
    before_sha256 = hashlib.sha256(original).hexdigest()
    x, y, width, height = PATCH_RECT
    if x % 4 or y % 4 or width % 4 or height % 4:
        raise TitleMarkerError(f"PATCH_RECT is not BC7 block aligned: {PATCH_RECT}")
    if x + width > metadata["width"] or y + height > metadata["height"]:
        raise TitleMarkerError(f"PATCH_RECT is outside the DDS: {PATCH_RECT}")

    pixels, render = render_patch(marker, width, height)
    write_png(preview_path, width, height, pixels)
    output = bytearray(original)
    blocks_x = metadata["blocks_x"]
    local_blocks_x = width // 4
    local_blocks_y = height // 4
    first_block_x = x // 4
    first_block_y = y // 4

    for local_by in range(local_blocks_y):
        for local_bx in range(local_blocks_x):
            block: list[tuple[int, int, int, int]] = []
            for dy in range(4):
                for dx in range(4):
                    px = local_bx * 4 + dx
                    py = local_by * 4 + dy
                    offset = (py * width + px) * 4
                    block.append(tuple(pixels[offset : offset + 4]))  # type: ignore[arg-type]
            encoded = encode_bc7_mode5_block(block)
            global_bx = first_block_x + local_bx
            global_by = first_block_y + local_by
            target = DDS_DATA_OFFSET + (global_by * blocks_x + global_bx) * 16
            output[target : target + 16] = encoded

    if len(output) != len(original):
        raise TitleMarkerError("DDS size changed during block replacement")
    after_sha256 = hashlib.sha256(output).hexdigest()
    if after_sha256 == before_sha256:
        raise TitleMarkerError("DDS block replacement made no change")
    atomic_bytes(dds_path, bytes(output))
    return {
        "before_sha256": before_sha256,
        "after_sha256": after_sha256,
        "bytes": len(output),
        "dds_dimensions": [metadata["width"], metadata["height"]],
        "style_uvwh": list(STYLE_UVWH),
        "dds_crop": list(DDS_CROP),
        "patch_rect": list(PATCH_RECT),
        "patched_bc7_blocks": local_blocks_x * local_blocks_y,
        "preview_path": preview_path,
        "preview_sha256": sha256_file(preview_path),
        **render,
    }


def build_repacked_g1t(
    source_g1t: Path,
    work_root: Path,
    gust_g1t: Path,
    marker: str,
    timeout: int,
) -> dict[str, Any]:
    g1t_root = work_root / "g1t"
    if g1t_root.exists():
        shutil.rmtree(g1t_root)
    g1t_root.mkdir(parents=True)
    local_g1t = g1t_root / "seed_title.g1t"
    shutil.copy2(source_g1t, local_g1t)
    original_sha256 = sha256_file(local_g1t)

    before_listing = run_checked(
        [str(gust_g1t), "-l", local_g1t.name],
        cwd=g1t_root,
        timeout=timeout,
        description="gust_g1t listing of original English seed_title.g1t",
    )
    before_text = before_listing.stdout.lower()
    if "0x5f" not in before_text or "1024x1428" not in before_text:
        raise TitleMarkerError(
            "Original English seed_title.g1t is not the expected 0x5F 1024x1428 atlas"
        )

    extract = run_checked(
        [str(gust_g1t), "-y", local_g1t.name],
        cwd=g1t_root,
        timeout=timeout,
        description="gust_g1t extraction of English seed_title.g1t",
    )
    source_dir = g1t_root / "seed_title"
    dds_path = source_dir / "000.dds"
    manifest_path = source_dir / "g1t.json"
    if not dds_path.is_file() or not manifest_path.is_file():
        raise TitleMarkerError("gust_g1t did not extract seed_title/000.dds and g1t.json")

    preview_path = work_root / "UNBURGER_UNCENSOR_existing_seed_title_marker.png"
    dds_patch = patch_dds(dds_path, marker, preview_path)
    patched_dds_sha256 = sha256_file(dds_path)

    original_copy = g1t_root / "seed_title.original.g1t"
    os.replace(local_g1t, original_copy)
    rebuilt = run_checked(
        [str(gust_g1t), "-y", str(source_dir)],
        cwd=g1t_root,
        timeout=timeout,
        description="gust_g1t rebuild of patched English seed_title.g1t",
    )
    if not local_g1t.is_file():
        raise TitleMarkerError(f"gust_g1t did not rebuild {local_g1t}")
    rebuilt_sha256 = sha256_file(local_g1t)
    if rebuilt_sha256 == original_sha256:
        raise TitleMarkerError("Rebuilt seed_title.g1t is byte-identical to the original")

    after_listing = run_checked(
        [str(gust_g1t), "-l", local_g1t.name],
        cwd=g1t_root,
        timeout=timeout,
        description="gust_g1t listing of patched English seed_title.g1t",
    )
    after_text = after_listing.stdout.lower()
    if "0x5f" not in after_text or "1024x1428" not in after_text:
        raise TitleMarkerError(
            "Patched English seed_title.g1t lost its 0x5F 1024x1428 geometry"
        )

    verify_root = work_root / "g1t_verify"
    verify_root.mkdir(parents=True, exist_ok=True)
    verify_g1t = verify_root / "seed_title.g1t"
    shutil.copy2(local_g1t, verify_g1t)
    verify_extract = run_checked(
        [str(gust_g1t), "-y", verify_g1t.name],
        cwd=verify_root,
        timeout=timeout,
        description="gust_g1t verification extraction of patched seed_title.g1t",
    )
    verified_dds = verify_root / "seed_title" / "000.dds"
    if not verified_dds.is_file():
        raise TitleMarkerError("Patched G1T verification did not produce 000.dds")
    if sha256_file(verified_dds) != patched_dds_sha256:
        raise TitleMarkerError("Patched DDS changed after G1T rebuild and re-extraction")

    return {
        "path": local_g1t,
        "original_sha256": original_sha256,
        "rebuilt_sha256": rebuilt_sha256,
        "rebuilt_bytes": local_g1t.stat().st_size,
        "dds_patch": dds_patch,
        "extract_stdout_tail": extract.stdout.splitlines()[-10:],
        "rebuild_stdout_tail": rebuilt.stdout.splitlines()[-10:],
        "verify_extract_stdout_tail": verify_extract.stdout.splitlines()[-10:],
        "before_listing_stdout_tail": before_listing.stdout.splitlines()[-10:],
        "after_listing_stdout_tail": after_listing.stdout.splitlines()[-10:],
    }


def build(args: argparse.Namespace) -> int:
    project_root = Path(args.project_root).expanduser().resolve()
    game_root = Path(args.game_root).expanduser().resolve()
    gust_pak = Path(args.gust_pak).expanduser().resolve()
    gust_g1t = Path(args.gust_g1t).expanduser().resolve()
    marker = safe_marker(args.marker)

    for binary, name in ((gust_pak, "gust_pak"), (gust_g1t, "gust_g1t")):
        if not binary.is_file() or not os.access(binary, os.X_OK):
            raise TitleMarkerError(f"{name} is not executable: {binary}")
    if not project_root.is_dir():
        raise TitleMarkerError(f"Project root does not exist: {project_root}")
    if not game_root.is_dir():
        raise TitleMarkerError(f"Second Light root does not exist: {game_root}")

    main_report_path = (
        project_root / ".local/reports/translation/BR_TRANSLATION_PAK_REPACK_REPORT.json"
    )
    if not main_report_path.is_file():
        raise TitleMarkerError("Clean translation PAK report is missing; run steps 07 and 08")
    main_report = json.loads(main_report_path.read_text(encoding="utf-8"))
    if (
        main_report.get("type") != "br_translation_pak_repack_report"
        or main_report.get("status") != "ok"
        or int(main_report.get("summary", {}).get("failures", -1)) != 0
    ):
        raise TitleMarkerError("Step-08 repack report is not clean")
    if isinstance(main_report.get("title_marker_proof"), dict):
        raise TitleMarkerError(
            "The repack report still contains an earlier title-marker proof. "
            "Rerun steps 07 and 08 with BR_TITLE_MARKER=none before step 16."
        )
    existing_resource = [
        entry
        for entry in main_report.get("archives", [])
        if isinstance(entry, dict)
        and entry.get("target_id") == TARGET_ID
        and entry.get("archive_relative_path") == RESOURCE_ARCHIVE
    ]
    if existing_resource:
        raise TitleMarkerError(
            "The clean step-08 report unexpectedly already contains PACK00_04_01.PAK"
        )

    installed_resource = game_root / RESOURCE_ARCHIVE
    if not installed_resource.is_file():
        raise TitleMarkerError(f"Installed source archive is missing: {installed_resource}")

    build_root = project_root / ".local/build/translation"
    archive_output_root = build_root / "archives" / TARGET_ID
    work_root = build_root / "seed_title_marker"
    if work_root.exists():
        shutil.rmtree(work_root)
    work_root.mkdir(parents=True)

    resource_stage = work_root / "staging" / RESOURCE_STEM
    resource_manifest, resource_extract_tail = extract_pak(
        gust_pak, installed_resource, resource_stage, args.timeout
    )
    staged_g1t = resource_stage / RESOURCE_INTERNAL
    if not staged_g1t.is_file():
        raise TitleMarkerError(
            f"English title atlas is missing from installed resource PAK: {RESOURCE_INTERNAL}"
        )

    patched_g1t = build_repacked_g1t(
        staged_g1t,
        work_root,
        gust_g1t,
        marker,
        args.timeout,
    )
    shutil.copy2(patched_g1t["path"], staged_g1t)
    if sha256_file(staged_g1t) != patched_g1t["rebuilt_sha256"]:
        raise TitleMarkerError("Staged patched G1T checksum mismatch")

    built_resource, resource_repack_tail = repack_stage(
        gust_pak,
        resource_stage,
        resource_manifest,
        RESOURCE_STEM,
        args.timeout,
    )
    resource_checked, resource_failures, resource_listing_tail = verify_repacked(
        gust_pak,
        built_resource,
        resource_stage,
        work_root / "pak_verify" / RESOURCE_STEM,
        args.timeout,
    )
    if resource_failures:
        raise TitleMarkerError(
            f"Full PACK00_04_01 verification failed: {len(resource_failures)}"
        )

    final_resource = archive_output_root / RESOURCE_ARCHIVE
    install_verified_output(built_resource, final_resource)
    entries, _ = list_pak_entries(
        gust_pak, final_resource, final_resource.parent, args.timeout
    )
    resource_entry = archive_report_entry(
        archive_stem=RESOURCE_STEM,
        archive_relative_path=RESOURCE_ARCHIVE,
        final_pak=final_resource,
        project_root=project_root,
        changed_files=1,
        listed_entries=len(entries),
        entries_checked=resource_checked,
        failures=resource_failures,
        repack_tail=resource_repack_tail,
        listing_tail=resource_listing_tail,
        source_policy="current_installation_baseline_extraction_plus_verified_marker_overlay",
        source_archive_sha256=sha256_file(installed_resource),
        source_archive_bytes=installed_resource.stat().st_size,
        changed_members=[RESOURCE_INTERNAL],
        full_reextract_verified=(
            not resource_failures and resource_checked == len(entries)
        ),
    )

    main_report["archives"] = sorted(
        [entry for entry in main_report.get("archives", []) if isinstance(entry, dict)]
        + [resource_entry],
        key=lambda entry: (
            str(entry.get("target_id", "")),
            str(entry.get("archive_relative_path", "")),
        ),
    )
    main_report["gust_g1t_sha256"] = sha256_file(gust_g1t)
    main_report["title_marker_proof"] = {
        "status": "ok",
        "target_id": TARGET_ID,
        "marker": marker,
        "method": "existing_seed_title_g1t_transparent_marker",
        "resource_archive": RESOURCE_ARCHIVE,
        "resource_path": RESOURCE_INTERNAL,
        "style_name": "gen_seed_Title_copyrights_overseas",
        "style_uvwh": list(STYLE_UVWH),
        "dds_crop": list(DDS_CROP),
        "patch_rect": list(PATCH_RECT),
        "design": "transparent cool-white label with navy outline and soft drop shadow",
        "runtime_status": "confirmed_visible_and_visual_design_approved",
    }
    recompute_main_summary(main_report)
    if main_report["status"] != "ok":
        raise TitleMarkerError("Refusing to publish a failed combined repack report")
    atomic_json(main_report_path, main_report)

    proof_report = {
        "type": REPORT_TYPE,
        "format_version": 1,
        "status": "ok",
        "generated_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "project_root": "<PROJECT_ROOT>",
        "game_root": "<SECOND_LIGHT_ROOT>",
        "target_id": TARGET_ID,
        "marker": marker,
        "method": "existing_seed_title_g1t_transparent_marker",
        "runtime_status": "confirmed_visible_and_visual_design_approved",
        "resource_archive": RESOURCE_ARCHIVE,
        "resource_path": RESOURCE_INTERNAL,
        "style_binding_unchanged": {
            "style_path": "saves/ui_en/gen_styles/uis_gen_seed_title.xml",
            "style_name": "gen_seed_Title_copyrights_overseas",
            "texture": "ui/seed_title.g1t",
            "texture_index": 0,
            "uvwh": list(STYLE_UVWH),
        },
        "g1t": {
            "original_sha256": patched_g1t["original_sha256"],
            "rebuilt_sha256": patched_g1t["rebuilt_sha256"],
            "rebuilt_bytes": patched_g1t["rebuilt_bytes"],
            "before_listing_stdout_tail": patched_g1t[
                "before_listing_stdout_tail"
            ],
            "after_listing_stdout_tail": patched_g1t[
                "after_listing_stdout_tail"
            ],
            "extract_stdout_tail": patched_g1t["extract_stdout_tail"],
            "rebuild_stdout_tail": patched_g1t["rebuild_stdout_tail"],
            "verify_extract_stdout_tail": patched_g1t[
                "verify_extract_stdout_tail"
            ],
        },
        "dds_patch": {
            key: (
                value.relative_to(project_root).as_posix()
                if key == "preview_path" and isinstance(value, Path)
                else value
            )
            for key, value in patched_g1t["dds_patch"].items()
        },
        "archive": resource_entry,
        "resource_extraction_stdout_tail": resource_extract_tail,
        "safety": {
            "installed_game_files_modified_during_build": False,
            "proprietary_asset_in_update_package": False,
            "proprietary_asset_read_only_source": True,
            "patched_asset_created_only_under_local_build": True,
            "style_xml_modified": False,
            "full_g1t_reextract_hash_verification": True,
            "full_pak_reextract_hash_verification": True,
            "installation_requires_step_09": True,
        },
        "next_action": "production marker is approved; use step 09 only for an explicit regression test",
    }
    proof_report_path = (
        project_root
        / ".local/reports/translation/BR_SECOND_LIGHT_TITLE_MARKER_REPORT.json"
    )
    atomic_json(proof_report_path, proof_report)

    print("Second Light polished seed_title.g1t marker built and fully verified.")
    print(f"Marker: {marker}")
    print(f"Transparent marker DDS block rectangle: {PATCH_RECT}")
    print(f"Output resource PAK: {final_resource}")
    print(f"Preview: {patched_g1t['dds_patch']['preview_path']}")
    print("No installed game file was modified during the build.")
    return 0


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("--project-root", required=True)
    result.add_argument("--game-root", required=True)
    result.add_argument("--gust-pak", required=True)
    result.add_argument("--gust-g1t", required=True)
    result.add_argument("--marker", default=DEFAULT_MARKER)
    result.add_argument("--timeout", type=int, default=1800)
    return result


def main() -> int:
    return build(parser().parse_args())


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except ProofError as exc:
        print(f"ERROR: {exc}", file=os.sys.stderr)
        raise SystemExit(1)
