#!/usr/bin/env python3
"""Build and fully verify a Second Light synthetic title-marker G1T proof.

This tool never modifies an installed game. It starts from the already rebuilt
PACK02.PAK so translation overlays are preserved, adds one synthetic G1T to a
copy of the installed PACK00_04_01.PAK, switches one English title-style image,
fully re-extracts both rebuilt archives, and only then updates local build output.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import struct
import subprocess
import tempfile
import time
import zlib
from pathlib import Path
from typing import Any, Iterable


TARGET_ID = "second_light_original"
RESOURCE_ARCHIVE = "Data/PACK00_04_01.PAK"
STYLE_ARCHIVE = "Data/PACK02.PAK"
RESOURCE_STEM = "PACK00_04_01"
STYLE_STEM = "PACK02"
RESOURCE_INTERNAL = "data/x64/res_en/ui/unburger_marker.g1t"
STYLE_INTERNAL = "saves/ui_en/gen_styles/uis_gen_seed_title.xml"
STYLE_NAME = "gen_seed_Title_copyrights_overseas"
TEXTURE_PATH = "ui/unburger_marker.g1t"
TEXTURE_WIDTH = 512
TEXTURE_HEIGHT = 32
TEXTURE_UVWH = "0,0,1024,64"
DEFAULT_MARKER = "UNBURGER / UNCENSOR"
G1T_TYPE_DXT5_WINDOWS = 0x5B
G1T_VERSION = 40
REPORT_TYPE = "br_second_light_title_marker_proof_report"


class ProofError(RuntimeError):
    pass


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def atomic_bytes(path: Path, data: bytes, mode: int | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, raw_tmp = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    tmp = Path(raw_tmp)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        if mode is not None:
            os.chmod(tmp, mode)
        os.replace(tmp, path)
        dir_fd = os.open(path.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            os.fsync(dir_fd)
        finally:
            os.close(dir_fd)
    finally:
        tmp.unlink(missing_ok=True)


def atomic_json(path: Path, data: dict[str, Any]) -> None:
    atomic_bytes(
        path,
        (json.dumps(data, ensure_ascii=False, indent=2) + "\n").encode("utf-8"),
    )


def run_checked(
    argv: list[str],
    *,
    cwd: Path,
    timeout: int,
    description: str,
) -> subprocess.CompletedProcess[str]:
    process = subprocess.run(
        argv,
        cwd=cwd,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    if process.returncode != 0:
        detail = (process.stderr or process.stdout).strip()
        raise ProofError(f"{description} failed ({process.returncode}): {detail}")
    return process


def safe_marker(value: str) -> str:
    marker = value.strip()
    if not marker:
        raise ProofError("Title marker must not be empty")
    if len(marker) > 40:
        raise ProofError("Title marker is longer than 40 characters")
    allowed = set("ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789 /+-_.")
    unsupported = sorted(set(marker) - allowed)
    if unsupported:
        rendered = " ".join(repr(char) for char in unsupported)
        raise ProofError(f"Unsupported title-marker character(s): {rendered}")
    return marker


# Compact 5x7 uppercase bitmap font. Each string is one glyph row.
FONT: dict[str, tuple[str, ...]] = {
    " ": ("00000",) * 7,
    "/": ("00001", "00010", "00100", "01000", "10000", "00000", "00000"),
    "+": ("00000", "00100", "00100", "11111", "00100", "00100", "00000"),
    "-": ("00000", "00000", "00000", "11111", "00000", "00000", "00000"),
    "_": ("00000", "00000", "00000", "00000", "00000", "00000", "11111"),
    ".": ("00000", "00000", "00000", "00000", "00000", "00110", "00110"),
    "0": ("01110", "10001", "10011", "10101", "11001", "10001", "01110"),
    "1": ("00100", "01100", "00100", "00100", "00100", "00100", "01110"),
    "2": ("01110", "10001", "00001", "00010", "00100", "01000", "11111"),
    "3": ("11110", "00001", "00001", "01110", "00001", "00001", "11110"),
    "4": ("00010", "00110", "01010", "10010", "11111", "00010", "00010"),
    "5": ("11111", "10000", "10000", "11110", "00001", "00001", "11110"),
    "6": ("01110", "10000", "10000", "11110", "10001", "10001", "01110"),
    "7": ("11111", "00001", "00010", "00100", "01000", "01000", "01000"),
    "8": ("01110", "10001", "10001", "01110", "10001", "10001", "01110"),
    "9": ("01110", "10001", "10001", "01111", "00001", "00001", "01110"),
    "A": ("01110", "10001", "10001", "11111", "10001", "10001", "10001"),
    "B": ("11110", "10001", "10001", "11110", "10001", "10001", "11110"),
    "C": ("01111", "10000", "10000", "10000", "10000", "10000", "01111"),
    "D": ("11110", "10001", "10001", "10001", "10001", "10001", "11110"),
    "E": ("11111", "10000", "10000", "11110", "10000", "10000", "11111"),
    "F": ("11111", "10000", "10000", "11110", "10000", "10000", "10000"),
    "G": ("01111", "10000", "10000", "10111", "10001", "10001", "01111"),
    "H": ("10001", "10001", "10001", "11111", "10001", "10001", "10001"),
    "I": ("11111", "00100", "00100", "00100", "00100", "00100", "11111"),
    "J": ("00111", "00010", "00010", "00010", "10010", "10010", "01100"),
    "K": ("10001", "10010", "10100", "11000", "10100", "10010", "10001"),
    "L": ("10000", "10000", "10000", "10000", "10000", "10000", "11111"),
    "M": ("10001", "11011", "10101", "10101", "10001", "10001", "10001"),
    "N": ("10001", "11001", "10101", "10011", "10001", "10001", "10001"),
    "O": ("01110", "10001", "10001", "10001", "10001", "10001", "01110"),
    "P": ("11110", "10001", "10001", "11110", "10000", "10000", "10000"),
    "Q": ("01110", "10001", "10001", "10001", "10101", "10010", "01101"),
    "R": ("11110", "10001", "10001", "11110", "10100", "10010", "10001"),
    "S": ("01111", "10000", "10000", "01110", "00001", "00001", "11110"),
    "T": ("11111", "00100", "00100", "00100", "00100", "00100", "00100"),
    "U": ("10001", "10001", "10001", "10001", "10001", "10001", "01110"),
    "V": ("10001", "10001", "10001", "10001", "10001", "01010", "00100"),
    "W": ("10001", "10001", "10001", "10101", "10101", "10101", "01010"),
    "X": ("10001", "10001", "01010", "00100", "01010", "10001", "10001"),
    "Y": ("10001", "10001", "01010", "00100", "00100", "00100", "00100"),
    "Z": ("11111", "00001", "00010", "00100", "01000", "10000", "11111"),
}


def set_pixel(pixels: bytearray, x: int, y: int, rgba: tuple[int, int, int, int]) -> None:
    if x < 0 or y < 0 or x >= TEXTURE_WIDTH or y >= TEXTURE_HEIGHT:
        return
    offset = (y * TEXTURE_WIDTH + x) * 4
    old_alpha = pixels[offset + 3]
    if rgba[3] < old_alpha:
        return
    pixels[offset:offset + 4] = bytes(rgba)


def draw_glyph(
    pixels: bytearray,
    glyph: tuple[str, ...],
    x: int,
    y: int,
    scale: int,
    rgba: tuple[int, int, int, int],
) -> None:
    for row, bits in enumerate(glyph):
        for column, bit in enumerate(bits):
            if bit != "1":
                continue
            for dy in range(scale):
                for dx in range(scale):
                    set_pixel(
                        pixels,
                        x + column * scale + dx,
                        y + row * scale + dy,
                        rgba,
                    )


def render_marker(marker: str) -> tuple[bytearray, int, int, int]:
    for char in marker:
        if char not in FONT:
            raise ProofError(f"No bitmap glyph for {char!r}")
    scale = min(4, (TEXTURE_WIDTH - 8) // max(1, (6 * len(marker) - 1)))
    if scale < 1:
        raise ProofError("Marker does not fit the synthetic texture")
    text_width = (6 * len(marker) - 1) * scale
    text_height = 7 * scale
    x = (TEXTURE_WIDTH - text_width) // 2
    y = (TEXTURE_HEIGHT - text_height) // 2
    pixels = bytearray(TEXTURE_WIDTH * TEXTURE_HEIGHT * 4)

    outline_offsets = (
        (-1, -1), (0, -1), (1, -1),
        (-1, 0),           (1, 0),
        (-1, 1),  (0, 1),  (1, 1),
    )
    cursor = x
    for char in marker:
        glyph = FONT[char]
        for dx, dy in outline_offsets:
            draw_glyph(pixels, glyph, cursor + dx, y + dy, scale, (0, 0, 0, 210))
        cursor += 6 * scale

    cursor = x
    for char in marker:
        draw_glyph(pixels, FONT[char], cursor, y, scale, (238, 238, 238, 255))
        cursor += 6 * scale
    return pixels, scale, text_width, text_height


def png_chunk(kind: bytes, payload: bytes) -> bytes:
    return (
        struct.pack(">I", len(payload))
        + kind
        + payload
        + struct.pack(">I", zlib.crc32(kind + payload) & 0xFFFFFFFF)
    )


def write_png(path: Path, pixels: bytes) -> None:
    rows = bytearray()
    stride = TEXTURE_WIDTH * 4
    for y in range(TEXTURE_HEIGHT):
        rows.append(0)
        rows.extend(pixels[y * stride:(y + 1) * stride])
    data = (
        b"\x89PNG\r\n\x1a\n"
        + png_chunk(
            b"IHDR",
            struct.pack(">IIBBBBB", TEXTURE_WIDTH, TEXTURE_HEIGHT, 8, 6, 0, 0, 0),
        )
        + png_chunk(b"IDAT", zlib.compress(bytes(rows), 9))
        + png_chunk(b"IEND", b"")
    )
    atomic_bytes(path, data)


def rgb888_to_565(rgb: tuple[int, int, int]) -> int:
    r, g, b = rgb
    return ((r * 31 + 127) // 255) << 11 | ((g * 63 + 127) // 255) << 5 | ((b * 31 + 127) // 255)


def rgb565_to_888(value: int) -> tuple[int, int, int]:
    r = (value >> 11) & 31
    g = (value >> 5) & 63
    b = value & 31
    return ((r * 255 + 15) // 31, (g * 255 + 31) // 63, (b * 255 + 15) // 31)


def color_distance(a: tuple[int, int, int], b: tuple[int, int, int]) -> int:
    return sum((x - y) * (x - y) for x, y in zip(a, b))


def encode_dxt5_block(block: list[tuple[int, int, int, int]]) -> bytes:
    alphas = [pixel[3] for pixel in block]
    alpha0 = max(alphas)
    alpha1 = min(alphas)
    if alpha0 == alpha1:
        alpha0 = 255 if alpha0 else 1
        alpha1 = 0
    if alpha0 <= alpha1:
        alpha0, alpha1 = alpha1, alpha0
    alpha_palette = [alpha0, alpha1]
    for index in range(1, 7):
        alpha_palette.append(((7 - index) * alpha0 + index * alpha1 + 3) // 7)
    alpha_bits = 0
    for index, alpha in enumerate(alphas):
        choice = min(range(8), key=lambda item: abs(alpha - alpha_palette[item]))
        alpha_bits |= choice << (3 * index)
    alpha_payload = bytes((alpha0, alpha1)) + alpha_bits.to_bytes(6, "little")

    visible = [pixel[:3] for pixel in block if pixel[3] >= 16]
    if not visible:
        color0 = 0
        color1 = 0
    else:
        darkest = min(visible, key=lambda rgb: (sum(rgb), rgb))
        lightest = max(visible, key=lambda rgb: (sum(rgb), rgb))
        color0 = rgb888_to_565(lightest)
        color1 = rgb888_to_565(darkest)
        if color0 == color1:
            color0 = min(0xFFFF, color0 + 1)
        if color0 < color1:
            color0, color1 = color1, color0
    c0 = rgb565_to_888(color0)
    c1 = rgb565_to_888(color1)
    palette = [
        c0,
        c1,
        tuple((2 * c0[i] + c1[i] + 1) // 3 for i in range(3)),
        tuple((c0[i] + 2 * c1[i] + 1) // 3 for i in range(3)),
    ]
    color_bits = 0
    for index, pixel in enumerate(block):
        choice = min(range(4), key=lambda item: color_distance(pixel[:3], palette[item]))
        color_bits |= choice << (2 * index)
    return alpha_payload + struct.pack("<HHI", color0, color1, color_bits)


def write_dxt5_dds(path: Path, pixels: bytes) -> None:
    if TEXTURE_WIDTH % 4 or TEXTURE_HEIGHT % 4:
        raise ProofError("DXT5 texture dimensions must be multiples of four")
    payload = bytearray()
    for block_y in range(0, TEXTURE_HEIGHT, 4):
        for block_x in range(0, TEXTURE_WIDTH, 4):
            block: list[tuple[int, int, int, int]] = []
            for dy in range(4):
                for dx in range(4):
                    offset = ((block_y + dy) * TEXTURE_WIDTH + block_x + dx) * 4
                    block.append(tuple(pixels[offset:offset + 4]))  # type: ignore[arg-type]
            payload.extend(encode_dxt5_block(block))
    linear_size = len(payload)
    dds_header = struct.pack(
        "<IIIIIII11I",
        124,
        0x00081007,  # CAPS | HEIGHT | WIDTH | PIXELFORMAT | LINEARSIZE
        TEXTURE_HEIGHT,
        TEXTURE_WIDTH,
        linear_size,
        0,
        1,
        *([0] * 11),
    )
    pixel_format = struct.pack(
        "<II4sIIIII",
        32,
        0x00000004,  # FOURCC
        b"DXT5",
        0,
        0,
        0,
        0,
        0,
    )
    caps = struct.pack("<IIIII", 0x00001000, 0, 0, 0, 0)
    output = b"DDS " + dds_header + pixel_format + caps + bytes(payload)
    if len(output) != 128 + linear_size:
        raise ProofError("Internal DDS size calculation failed")
    atomic_bytes(path, output)


def build_g1t_source(
    work_root: Path,
    marker: str,
    gust_g1t: Path,
    timeout: int,
) -> dict[str, Any]:
    source_dir = work_root / "g1t_source" / "unburger_marker"
    source_dir.mkdir(parents=True, exist_ok=True)
    dds_path = source_dir / "000.dds"
    preview_path = work_root / "UNBURGER_UNCENSOR_preview.png"
    pixels, scale, text_width, text_height = render_marker(marker)
    write_png(preview_path, pixels)
    write_dxt5_dds(dds_path, pixels)
    manifest = {
        "json_version": 2,
        "name": "unburger_marker.g1t",
        "version": G1T_VERSION,
        "platform": "Windows",
        "textures": [
            {
                "name": "000.dds",
                "type": G1T_TYPE_DXT5_WINDOWS,
                "flags": ["STANDARD_FLAGS"],
            }
        ],
    }
    atomic_json(source_dir / "g1t.json", manifest)
    output_path = source_dir.parent / "unburger_marker.g1t"
    output_path.unlink(missing_ok=True)
    create = run_checked(
        [str(gust_g1t), "-y", str(source_dir)],
        cwd=source_dir.parent,
        timeout=timeout,
        description="gust_g1t synthetic texture creation",
    )
    if not output_path.is_file():
        raise ProofError(f"gust_g1t did not create {output_path}")
    listing = run_checked(
        [str(gust_g1t), "-l", str(output_path)],
        cwd=source_dir.parent,
        timeout=timeout,
        description="gust_g1t synthetic texture listing",
    )
    listing_text = listing.stdout.lower()
    if "0x5b" not in listing_text or "512x32" not in listing_text:
        raise ProofError(
            "Synthetic G1T listing does not confirm Windows DXT5 512x32 texture"
        )
    return {
        "path": output_path,
        "sha256": sha256_file(output_path),
        "bytes": output_path.stat().st_size,
        "dds_path": dds_path,
        "dds_sha256": sha256_file(dds_path),
        "dds_bytes": dds_path.stat().st_size,
        "preview_path": preview_path,
        "preview_sha256": sha256_file(preview_path),
        "scale": scale,
        "text_width": text_width,
        "text_height": text_height,
        "create_stdout_tail": create.stdout.splitlines()[-10:],
        "listing_stdout_tail": listing.stdout.splitlines()[-10:],
    }


def normalize_archive_entry_path(name: str) -> str:
    normalized = name.replace("\\", "/").lstrip("/")
    if re.match(r"^[A-Za-z]:", normalized):
        raise ProofError(f"Unsafe PAK path reported by gust_pak: {name!r}")
    parts = normalized.split("/")
    if not normalized or any(part in {"", ".", ".."} for part in parts):
        raise ProofError(f"Unsafe PAK path reported by gust_pak: {name!r}")
    return "/".join(parts)


def list_pak_entries(
    gust_pak: Path,
    pak_path: Path,
    cwd: Path,
    timeout: int,
) -> tuple[list[str], list[str]]:
    process = run_checked(
        [str(gust_pak), "-l", str(pak_path)],
        cwd=cwd,
        timeout=timeout,
        description=f"gust_pak listing of {pak_path.name}",
    )
    entries: list[str] = []
    seen: set[str] = set()
    for line in process.stdout.splitlines():
        if len(line) < 20:
            continue
        offset = line[0:9]
        size = line[10:18]
        if (
            line[9:10] != " "
            or line[18:19] != " "
            or any(char not in "0123456789abcdefABCDEF" for char in offset)
            or any(char not in "0123456789abcdefABCDEF" for char in size)
        ):
            continue
        raw_name = line[19:]
        if raw_name.endswith("*") or raw_name.endswith(" "):
            raw_name = raw_name[:-1]
        name = normalize_archive_entry_path(raw_name)
        if name in seen:
            raise ProofError(f"Duplicate path in rebuilt PAK: {name}")
        seen.add(name)
        entries.append(name)
    if not entries:
        raise ProofError(f"gust_pak returned no entries for {pak_path}")
    return entries, process.stdout.splitlines()[-10:]


def extract_pak(
    gust_pak: Path,
    source_pak: Path,
    stage: Path,
    timeout: int,
) -> tuple[Path, list[str]]:
    if stage.exists():
        shutil.rmtree(stage)
    stage.mkdir(parents=True)
    local_pak = stage / source_pak.name
    shutil.copy2(source_pak, local_pak)
    process = run_checked(
        [str(gust_pak), str(local_pak)],
        cwd=stage,
        timeout=timeout,
        description=f"gust_pak extraction of {source_pak.name}",
    )
    local_pak.unlink(missing_ok=True)
    (stage / f"{source_pak.name}.bak").unlink(missing_ok=True)
    preferred = stage / f"{source_pak.stem}.json"
    if preferred.is_file():
        manifest = preferred
    else:
        manifests = sorted(stage.glob("*.json"))
        if len(manifests) != 1:
            raise ProofError(
                f"Expected one gust_pak manifest after extracting {source_pak.name}, "
                f"found {len(manifests)}"
            )
        manifest = manifests[0]
    return manifest, process.stdout.splitlines()[-10:]


def repack_stage(
    gust_pak: Path,
    stage: Path,
    manifest: Path,
    archive_stem: str,
    timeout: int,
) -> tuple[Path, list[str]]:
    before = {
        path.relative_to(stage)
        for path in stage.rglob("*")
        if path.is_file() and path.suffix.lower() == ".pak"
    }
    process = run_checked(
        [str(gust_pak), str(manifest)],
        cwd=stage,
        timeout=timeout,
        description=f"gust_pak repack of {archive_stem}",
    )
    after = {
        path.relative_to(stage)
        for path in stage.rglob("*")
        if path.is_file() and path.suffix.lower() == ".pak"
    }
    created = sorted(after - before)
    if len(created) != 1:
        rendered = ", ".join(path.as_posix() for path in created) or "(none)"
        raise ProofError(
            f"Expected one rebuilt PAK for {archive_stem}, found {len(created)}: {rendered}"
        )
    return stage / created[0], process.stdout.splitlines()[-10:]


def verify_repacked(
    gust_pak: Path,
    built_pak: Path,
    expected_stage: Path,
    verify_root: Path,
    timeout: int,
) -> tuple[int, list[dict[str, str]], list[str]]:
    entries, listing_tail = list_pak_entries(gust_pak, built_pak, expected_stage, timeout)
    if verify_root.exists():
        shutil.rmtree(verify_root)
    verify_root.mkdir(parents=True)
    verify_pak = verify_root / built_pak.name
    shutil.copy2(built_pak, verify_pak)
    run_checked(
        [str(gust_pak), str(verify_pak)],
        cwd=verify_root,
        timeout=timeout,
        description=f"gust_pak verification extraction of {built_pak.name}",
    )
    verify_pak.unlink(missing_ok=True)
    failures: list[dict[str, str]] = []
    checked = 0
    for name in entries:
        expected = expected_stage / Path(name)
        actual = verify_root / Path(name)
        if not expected.is_file():
            failures.append({"path": name, "error": "expected staged file missing"})
            continue
        if not actual.is_file():
            failures.append({"path": name, "error": "re-extracted file missing"})
            continue
        checked += 1
        if sha256_file(expected) != sha256_file(actual):
            failures.append({"path": name, "error": "content hash mismatch"})
    return checked, failures, listing_tail


def patch_style(style_path: Path) -> dict[str, Any]:
    original = style_path.read_bytes()
    bom = b"\xef\xbb\xbf" if original.startswith(b"\xef\xbb\xbf") else b""
    body = original[len(bom):]
    try:
        text = body.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ProofError(f"Title style is not UTF-8: {style_path}") from exc
    tag_pattern = re.compile(
        rf'<image\b(?=[^>]*\bname="{re.escape(STYLE_NAME)}")[^>]*/>'
    )
    matches = list(tag_pattern.finditer(text))
    if len(matches) != 1:
        raise ProofError(
            f"Expected one {STYLE_NAME!r} image in {style_path}, found {len(matches)}"
        )
    old_tag = matches[0].group(0)
    new_tag, texture_count = re.subn(
        r'\btexture="[^"]*"',
        f'texture="{TEXTURE_PATH}"',
        old_tag,
        count=1,
    )
    new_tag, uv_count = re.subn(
        r'\buvwh="[^"]*"',
        f'uvwh="{TEXTURE_UVWH}"',
        new_tag,
        count=1,
    )
    if texture_count != 1 or uv_count != 1:
        raise ProofError(f"Could not replace texture/uvwh attributes in {old_tag}")
    patched = text[:matches[0].start()] + new_tag + text[matches[0].end():]
    output = bom + patched.encode("utf-8")
    changed = output != original
    if changed:
        atomic_bytes(style_path, output)
    return {
        "path": STYLE_INTERNAL,
        "style_name": STYLE_NAME,
        "old_tag": old_tag,
        "new_tag": new_tag,
        "before_sha256": hashlib.sha256(original).hexdigest(),
        "after_sha256": hashlib.sha256(output).hexdigest(),
        "changed": changed,
    }


def existing_archive_entry(report: dict[str, Any], relative_path: str) -> dict[str, Any]:
    matches = [
        entry
        for entry in report.get("archives", [])
        if isinstance(entry, dict)
        and entry.get("target_id") == TARGET_ID
        and entry.get("archive_relative_path") == relative_path
    ]
    if len(matches) != 1:
        raise ProofError(
            f"Expected one clean repack entry for {TARGET_ID}/{relative_path}, "
            f"found {len(matches)}"
        )
    return matches[0]


def archive_report_entry(
    *,
    archive_stem: str,
    archive_relative_path: str,
    final_pak: Path,
    project_root: Path,
    changed_files: int,
    listed_entries: int,
    entries_checked: int,
    failures: list[dict[str, str]],
    repack_tail: list[str],
    listing_tail: list[str],
    source_policy: str,
    source_archive_sha256: str = "",
    source_archive_bytes: int = -1,
    changed_members: list[str] | None = None,
    full_reextract_verified: bool | None = None,
) -> dict[str, Any]:
    if full_reextract_verified is None:
        full_reextract_verified = not failures and entries_checked == listed_entries
    return {
        "target_id": TARGET_ID,
        "archive_stem": archive_stem,
        "archive_relative_path": archive_relative_path,
        "output_path": final_pak.relative_to(project_root).as_posix(),
        "output_sha256": sha256_file(final_pak),
        "output_bytes": final_pak.stat().st_size,
        "changed_files": changed_files,
        "listed_entries": listed_entries,
        "entries_checked": entries_checked,
        "failures": failures,
        "repack_stdout_tail": repack_tail,
        "listing_stdout_tail": listing_tail,
        "manifest_policy": "opaque_gust_pak_input",
        "source_policy": source_policy,
        "source_archive_sha256": source_archive_sha256,
        "source_archive_bytes": source_archive_bytes,
        "changed_members": sorted(changed_members or []),
        "full_reextract_verified": full_reextract_verified,
    }


def install_verified_output(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f".{destination.name}.marker-proof.tmp")
    temporary.unlink(missing_ok=True)
    try:
        shutil.copy2(source, temporary)
        if sha256_file(temporary) != sha256_file(source):
            raise ProofError(f"Temporary output checksum mismatch: {destination}")
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)


def recompute_main_summary(report: dict[str, Any]) -> None:
    archives = [entry for entry in report.get("archives", []) if isinstance(entry, dict)]
    failures = sum(len(entry.get("failures", [])) for entry in archives)
    report["summary"] = {
        "archives": len(archives),
        "entries_checked": sum(int(entry.get("entries_checked", 0)) for entry in archives),
        "changed_files": sum(int(entry.get("changed_files", 0)) for entry in archives),
        "failures": failures,
    }
    report["status"] = "failed" if failures else "ok"


def build(args: argparse.Namespace) -> int:
    project_root = Path(args.project_root).expanduser().resolve()
    game_root = Path(args.game_root).expanduser().resolve()
    gust_pak = Path(args.gust_pak).expanduser().resolve()
    gust_g1t = Path(args.gust_g1t).expanduser().resolve()
    marker = safe_marker(args.marker)
    for binary, name in ((gust_pak, "gust_pak"), (gust_g1t, "gust_g1t")):
        if not binary.is_file() or not os.access(binary, os.X_OK):
            raise ProofError(f"{name} is not executable: {binary}")
    if not project_root.is_dir():
        raise ProofError(f"Project root does not exist: {project_root}")
    if not game_root.is_dir():
        raise ProofError(f"Second Light root does not exist: {game_root}")

    build_root = project_root / ".local/build/translation"
    archive_output_root = build_root / "archives" / TARGET_ID
    main_report_path = project_root / ".local/reports/translation/BR_TRANSLATION_PAK_REPACK_REPORT.json"
    if not main_report_path.is_file():
        raise ProofError("Clean translation PAK report is missing; run step 08 first")
    main_report = json.loads(main_report_path.read_text(encoding="utf-8"))
    if (
        main_report.get("type") != "br_translation_pak_repack_report"
        or main_report.get("status") != "ok"
        or int(main_report.get("summary", {}).get("failures", -1)) != 0
    ):
        raise ProofError("Step 08 repack report is not clean")

    old_style_entry = existing_archive_entry(main_report, STYLE_ARCHIVE)
    style_source = project_root / str(old_style_entry.get("output_path", ""))
    if not style_source.is_file():
        raise ProofError(f"Already rebuilt PACK02 is missing: {style_source}")
    expected_style_hash = old_style_entry.get("output_sha256")
    if not isinstance(expected_style_hash, str) or sha256_file(style_source) != expected_style_hash:
        raise ProofError("Already rebuilt PACK02 changed after step 08 verification")

    resource_source = game_root / RESOURCE_ARCHIVE
    if not resource_source.is_file():
        raise ProofError(f"Installed source archive is missing: {resource_source}")

    work_root = build_root / "title_marker_proof"
    if work_root.exists():
        shutil.rmtree(work_root)
    work_root.mkdir(parents=True)
    generated = build_g1t_source(work_root, marker, gust_g1t, args.timeout)

    resource_stage = work_root / "staging" / RESOURCE_STEM
    style_stage = work_root / "staging" / STYLE_STEM
    resource_manifest, resource_extract_tail = extract_pak(
        gust_pak, resource_source, resource_stage, args.timeout
    )
    style_manifest, style_extract_tail = extract_pak(
        gust_pak, style_source, style_stage, args.timeout
    )

    resource_destination = resource_stage / RESOURCE_INTERNAL
    resource_destination.parent.mkdir(parents=True, exist_ok=True)
    if resource_destination.exists():
        raise ProofError(
            f"Refusing to overwrite an existing resource: {RESOURCE_INTERNAL}"
        )
    shutil.copy2(generated["path"], resource_destination)
    if sha256_file(resource_destination) != generated["sha256"]:
        raise ProofError("Staged G1T checksum mismatch")

    style_path = style_stage / STYLE_INTERNAL
    if not style_path.is_file():
        raise ProofError(f"English title style is missing from PACK02: {STYLE_INTERNAL}")
    style_patch = patch_style(style_path)

    built_resource, resource_repack_tail = repack_stage(
        gust_pak, resource_stage, resource_manifest, RESOURCE_STEM, args.timeout
    )
    built_style, style_repack_tail = repack_stage(
        gust_pak, style_stage, style_manifest, STYLE_STEM, args.timeout
    )

    resource_checked, resource_failures, resource_listing_tail = verify_repacked(
        gust_pak,
        built_resource,
        resource_stage,
        work_root / "verify" / RESOURCE_STEM,
        args.timeout,
    )
    style_checked, style_failures, style_listing_tail = verify_repacked(
        gust_pak,
        built_style,
        style_stage,
        work_root / "verify" / STYLE_STEM,
        args.timeout,
    )
    if resource_failures or style_failures:
        raise ProofError(
            f"Full PAK verification failed: resource={len(resource_failures)}, "
            f"style={len(style_failures)}"
        )

    final_resource = archive_output_root / RESOURCE_ARCHIVE
    final_style = archive_output_root / STYLE_ARCHIVE
    if final_style.resolve() != style_source.resolve():
        raise ProofError(
            f"PACK02 report/output mismatch: expected {final_style}, got {style_source}"
        )
    install_verified_output(built_resource, final_resource)
    install_verified_output(built_style, final_style)

    resource_entry = archive_report_entry(
        archive_stem=RESOURCE_STEM,
        archive_relative_path=RESOURCE_ARCHIVE,
        final_pak=final_resource,
        project_root=project_root,
        changed_files=1,
        listed_entries=resource_checked,
        entries_checked=resource_checked,
        failures=resource_failures,
        repack_tail=resource_repack_tail,
        listing_tail=resource_listing_tail,
        source_policy="installed_original_read_only_plus_synthetic_g1t",
    )
    style_entry = archive_report_entry(
        archive_stem=STYLE_STEM,
        archive_relative_path=STYLE_ARCHIVE,
        final_pak=final_style,
        project_root=project_root,
        changed_files=int(old_style_entry.get("changed_files", 0)) + (1 if style_patch["changed"] else 0),
        listed_entries=style_checked,
        entries_checked=style_checked,
        failures=style_failures,
        repack_tail=style_repack_tail,
        listing_tail=style_listing_tail,
        source_policy="verified_step_08_output_plus_one_style_binding",
    )

    retained = [
        entry
        for entry in main_report.get("archives", [])
        if not (
            isinstance(entry, dict)
            and entry.get("target_id") == TARGET_ID
            and entry.get("archive_relative_path") in {RESOURCE_ARCHIVE, STYLE_ARCHIVE}
        )
    ]
    main_report["archives"] = sorted(
        retained + [resource_entry, style_entry],
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
        "texture_path": TEXTURE_PATH,
        "resource_archive": RESOURCE_ARCHIVE,
        "style_archive": STYLE_ARCHIVE,
        "style_name": STYLE_NAME,
        "texture_dimensions": [TEXTURE_WIDTH, TEXTURE_HEIGHT],
        "texture_format": "DXT5 / G1T type 0x5B",
        "runtime_status": "awaiting_manual_title_screen_test",
    }
    recompute_main_summary(main_report)
    if main_report["status"] != "ok":
        raise ProofError("Refusing to publish a failed combined repack report")
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
        "method": "synthetic_g1t_plus_single_style_binding",
        "runtime_status": "awaiting_manual_title_screen_test",
        "texture": {
            "internal_path": RESOURCE_INTERNAL,
            "g1t_type": "0x5B",
            "dds_format": "DXT5",
            "width": TEXTURE_WIDTH,
            "height": TEXTURE_HEIGHT,
            "uvwh": TEXTURE_UVWH,
            "g1t_sha256": generated["sha256"],
            "g1t_bytes": generated["bytes"],
            "dds_sha256": generated["dds_sha256"],
            "dds_bytes": generated["dds_bytes"],
            "preview_path": generated["preview_path"].relative_to(project_root).as_posix(),
            "preview_sha256": generated["preview_sha256"],
            "font_scale": generated["scale"],
            "rendered_text_dimensions": [generated["text_width"], generated["text_height"]],
            "gust_g1t_create_stdout_tail": generated["create_stdout_tail"],
            "gust_g1t_listing_stdout_tail": generated["listing_stdout_tail"],
        },
        "style_patch": style_patch,
        "archives": [resource_entry, style_entry],
        "extraction_stdout_tail": {
            RESOURCE_STEM: resource_extract_tail,
            STYLE_STEM: style_extract_tail,
        },
        "safety": {
            "installed_game_files_modified": False,
            "translation_pack02_preserved": True,
            "full_reextract_hash_verification": True,
            "installation_requires_step_09": True,
        },
        "next_action": "run_step_09_install_then_check_second_light_title_screen",
    }
    proof_report_path = project_root / ".local/reports/translation/BR_SECOND_LIGHT_TITLE_MARKER_PROOF_REPORT.json"
    atomic_json(proof_report_path, proof_report)

    print("Second Light synthetic title-marker proof built and fully verified.")
    print(f"Marker: {marker}")
    print(f"Texture: {TEXTURE_WIDTH}x{TEXTURE_HEIGHT} DXT5 / G1T 0x5B")
    print(f"Output resource PAK: {final_resource}")
    print(f"Output style PAK: {final_style}")
    print(f"Preview: {generated['preview_path']}")
    print("No installed game file was modified.")
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
