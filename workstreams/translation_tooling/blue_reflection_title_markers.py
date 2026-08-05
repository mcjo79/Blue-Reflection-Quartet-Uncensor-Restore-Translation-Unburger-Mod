#!/usr/bin/env python3
"""Build polished title markers for Blue Reflection Original and Quartet.

The title-specific a17/a18 atlases are not exposed as PAK members. Instead of
searching for them again, this tool uses the explicit, runtime-known
``a17_common.g1t`` resource shared by both releases. Static analysis of every
localized style reference proves that the block-aligned bottom 32 rows of
texture 0 are unused. The tool writes only a transparent marker into that
unused DXT5 region, redirects the two title copyright styles to it, rebuilds
both the resource and localized style PAKs, and fully re-extracts every entry.

No installed game file is modified during the build and no proprietary asset
is included in an update package. Installed PAKs are read-only inputs; rebuilt
copies exist only below ``.local/build/translation`` until step 09 performs a
transactional runtime test.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import shutil
import struct
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from second_light_title_marker import render_patch, write_png
from second_light_title_marker_proof import (
    ProofError,
    archive_report_entry,
    atomic_bytes,
    atomic_json,
    encode_dxt5_block,
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

REPORT_TYPE = "br_blue_reflection_title_markers_report"
DEFAULT_MARKER = "UNBURGER / UNCENSOR"
A17_COMMON_SHA256 = "e6f61809902841e2aa7d1d34ad697325f0d1148429412729e4a0513cd18d6619"
A17_COMMON_BYTES = 49236
QUARTET_PACK10_BASELINE_SHA256 = (
    "cc44e01cca2b1f68714dbe6a3c51b3e3894e612add1e440285e77fd4da5a00b1"
)

# a17_common texture 0 is 256x128 DXT5. Existing styles use a 1.5x UV grid and
# occupy physical rows 0..81. The bottom block-aligned 32 rows are unused.
EXPECTED_DDS_SIZE = (256, 128)
PATCH_RECT = (0, 96, 256, 32)
STYLE_UVWH = (0, 144, 384, 48)
DDS_DATA_OFFSET = 128
DDS_FOURCC = b"DXT5"
UV_SCALE_NUMERATOR = 3
UV_SCALE_DENOMINATOR = 2


class MarkerError(ProofError):
    pass


@dataclass(frozen=True)
class Target:
    target_id: str
    game_root_placeholder: str
    resource_archive: str
    resource_stem: str
    resource_internal: str
    style_archive: str
    style_stem: str
    style_prefix: str
    workspace_style_root: str
    quartet_baseline_required: bool = False

    @property
    def style_files(self) -> tuple[tuple[str, str], ...]:
        prefix = self.style_prefix
        return (
            (
                f"{prefix}/ui/gen_styles/uis_gen_a17_title.xml",
                "gen_a17_title01_copyright",
            ),
            (
                f"{prefix}/ui/gen_styles/uis_gen_a18_title.xml",
                "gen_a18_title01_copyright",
            ),
        )

    @property
    def layout_files(self) -> tuple[tuple[str, str], ...]:
        prefix = self.style_prefix
        return (
            (f"{prefix}/ui/a17_title/uil_title02.xml", "404, 24"),
            (f"{prefix}/ui/a18_title/uil_a18_title02.xml", "430, 24"),
        )


TARGETS = (
    Target(
        target_id="blue_reflection_original",
        game_root_placeholder="<BR1_ORIGINAL_ROOT>",
        resource_archive="DATA/PACK00_01.PAK",
        resource_stem="PACK00_01",
        resource_internal="data/x64/ui/a17_common.g1t",
        style_archive="DATA/PACK02_1.PAK",
        style_stem="PACK02_1",
        style_prefix="saves_en",
        workspace_style_root=(
            "titles/blue_reflection/workspace/original/archives/PACK02_1/saves_en"
        ),
    ),
    Target(
        target_id="blue_reflection_quartet",
        game_root_placeholder="<BR1_QUARTET_ROOT>",
        resource_archive="Data/PACK10_01.PAK",
        resource_stem="PACK10_01",
        resource_internal="data/b1/x64/ui/a17_common.g1t",
        style_archive="Data/PACK12.PAK",
        style_stem="PACK12",
        style_prefix="saves/b1",
        workspace_style_root=(
            "titles/blue_reflection/workspace/quartet/archives/PACK12/saves/b1"
        ),
        quartet_baseline_required=True,
    ),
)


def parse_dds_dxt5(data: bytes, expected_size: tuple[int, int]) -> dict[str, int]:
    if len(data) < DDS_DATA_OFFSET or data[:4] != b"DDS ":
        raise MarkerError("Extracted a17_common texture is not a DDS file")
    header_size = struct.unpack_from("<I", data, 4)[0]
    height = struct.unpack_from("<I", data, 12)[0]
    width = struct.unpack_from("<I", data, 16)[0]
    mipmaps = struct.unpack_from("<I", data, 28)[0]
    pixel_format_size = struct.unpack_from("<I", data, 76)[0]
    fourcc = data[84:88]
    if header_size != 124 or pixel_format_size != 32:
        raise MarkerError(
            f"Unexpected DDS header sizes: header={header_size}, pixel_format={pixel_format_size}"
        )
    if fourcc != DDS_FOURCC:
        raise MarkerError(f"Expected DXT5 DDS, found FourCC {fourcc!r}")
    if (width, height) != expected_size:
        raise MarkerError(
            f"Expected {expected_size[0]}x{expected_size[1]} DDS, found {width}x{height}"
        )
    if mipmaps not in {0, 1}:
        raise MarkerError(f"Expected one mip level, found {mipmaps}")
    blocks_x = math.ceil(width / 4)
    blocks_y = math.ceil(height / 4)
    expected_bytes = DDS_DATA_OFFSET + blocks_x * blocks_y * 16
    if len(data) != expected_bytes:
        raise MarkerError(f"Unexpected DXT5 DDS length: {len(data)} != {expected_bytes}")
    return {
        "width": width,
        "height": height,
        "mipmaps": mipmaps,
        "blocks_x": blocks_x,
        "blocks_y": blocks_y,
        "expected_bytes": expected_bytes,
    }


def rectangles_overlap(
    first: tuple[float, float, float, float],
    second: tuple[float, float, float, float],
) -> bool:
    ax, ay, aw, ah = first
    bx, by, bw, bh = second
    return ax < bx + bw and bx < ax + aw and ay < by + bh and by < ay + ah


def decode_xml_bytes(raw: bytes) -> tuple[str, str]:
    if raw.startswith(b"\xef\xbb\xbf"):
        try:
            return raw.decode("utf-8-sig"), "utf-8-sig"
        except UnicodeDecodeError:
            return raw.decode("latin1"), "latin1"
    head = raw[:160].upper()
    if b"UTF-8" in head:
        return raw.decode("utf-8"), "utf-8"
    if b"SHIFT_JIS" in head or b"SHIFT-JIS" in head or b"SJIS" in head:
        try:
            return raw.decode("shift_jis"), "shift_jis"
        except UnicodeDecodeError:
            try:
                return raw.decode("cp932"), "cp932"
            except UnicodeDecodeError:
                return raw.decode("latin1"), "latin1"
    try:
        return raw.decode("utf-8"), "utf-8"
    except UnicodeDecodeError:
        try:
            return raw.decode("cp932"), "cp932"
        except UnicodeDecodeError:
            return raw.decode("latin1"), "latin1"


def encode_xml_text(text: str, codec: str) -> bytes:
    if codec == "utf-8-sig":
        return text.encode("utf-8-sig")
    return text.encode(codec)


def parse_attributes(fragment: str) -> dict[str, str]:
    return {
        name: value
        for name, _quote, value in re.findall(
            r"([A-Za-z_][A-Za-z0-9_]*)\s*=\s*([\"'])(.*?)\2", fragment
        )
    }


def verify_unused_region(project_root: Path, target: Target) -> dict[str, Any]:
    style_root = project_root / target.workspace_style_root
    if not style_root.is_dir():
        raise MarkerError(f"Workspace style root is missing: {style_root}")
    patch = tuple(float(value) for value in PATCH_RECT)
    references: list[dict[str, Any]] = []
    conflicts: list[dict[str, Any]] = []
    image_pattern = re.compile(r"<image\b[^>]*>", re.IGNORECASE)
    for xml_path in sorted(style_root.rglob("*.xml")):
        raw = xml_path.read_bytes()
        text = raw.decode("latin1")
        for match in image_pattern.finditer(text):
            attrs = parse_attributes(match.group(0))
            if attrs.get("texture", "").replace("\\", "/").casefold() != "ui/a17_common.g1t":
                continue
            if attrs.get("texture_index", "0") != "0":
                continue
            uvwh_raw = attrs.get("uvwh")
            if uvwh_raw is None:
                raise MarkerError(
                    f"a17_common texture-0 reference lacks uvwh: {xml_path.relative_to(project_root)}"
                )
            try:
                ux, uy, uw, uh = (float(part.strip()) for part in uvwh_raw.split(","))
            except (ValueError, TypeError) as exc:
                raise MarkerError(
                    f"Invalid uvwh for a17_common reference in {xml_path}: {uvwh_raw!r}"
                ) from exc
            physical = (
                ux * UV_SCALE_DENOMINATOR / UV_SCALE_NUMERATOR,
                uy * UV_SCALE_DENOMINATOR / UV_SCALE_NUMERATOR,
                uw * UV_SCALE_DENOMINATOR / UV_SCALE_NUMERATOR,
                uh * UV_SCALE_DENOMINATOR / UV_SCALE_NUMERATOR,
            )
            item = {
                "path": xml_path.relative_to(project_root).as_posix(),
                "name": attrs.get("name"),
                "uvwh": [ux, uy, uw, uh],
                "physical_rect": list(physical),
            }
            references.append(item)
            if rectangles_overlap(physical, patch):
                conflicts.append(item)
    if not references:
        raise MarkerError(f"No a17_common texture-0 references found below {style_root}")
    if conflicts:
        rendered = ", ".join(f"{item['path']}:{item['name']}" for item in conflicts)
        raise MarkerError(f"Selected marker region overlaps existing UI styles: {rendered}")
    max_bottom = max(item["physical_rect"][1] + item["physical_rect"][3] for item in references)
    if max_bottom > PATCH_RECT[1]:
        raise MarkerError(
            f"Static style coverage reaches row {max_bottom:.3f}, marker begins at {PATCH_RECT[1]}"
        )
    return {
        "style_root": target.workspace_style_root,
        "reference_count": len(references),
        "maximum_used_physical_y": max_bottom,
        "patch_rect": list(PATCH_RECT),
        "uv_scale": "3:2",
        "references": references,
    }


def patch_dxt5_dds(dds_path: Path, marker: str, preview_path: Path) -> dict[str, Any]:
    original = dds_path.read_bytes()
    metadata = parse_dds_dxt5(original, EXPECTED_DDS_SIZE)
    before_sha256 = hashlib.sha256(original).hexdigest()
    x, y, width, height = PATCH_RECT
    if any(value % 4 for value in PATCH_RECT):
        raise MarkerError(f"Patch rectangle is not block aligned: {PATCH_RECT}")
    if x + width > metadata["width"] or y + height > metadata["height"]:
        raise MarkerError(f"Patch rectangle is outside the DDS: {PATCH_RECT}")

    pixels, render = render_patch(marker, width, height)
    write_png(preview_path, width, height, pixels)
    output = bytearray(original)
    first_block_x = x // 4
    first_block_y = y // 4
    local_blocks_x = width // 4
    local_blocks_y = height // 4
    for local_by in range(local_blocks_y):
        for local_bx in range(local_blocks_x):
            block: list[tuple[int, int, int, int]] = []
            for dy in range(4):
                for dx in range(4):
                    px = local_bx * 4 + dx
                    py = local_by * 4 + dy
                    offset = (py * width + px) * 4
                    block.append(tuple(pixels[offset : offset + 4]))  # type: ignore[arg-type]
            encoded = encode_dxt5_block(block)
            global_bx = first_block_x + local_bx
            global_by = first_block_y + local_by
            target_offset = (
                DDS_DATA_OFFSET
                + (global_by * metadata["blocks_x"] + global_bx) * 16
            )
            output[target_offset : target_offset + 16] = encoded
    if len(output) != len(original):
        raise MarkerError("DDS length changed during marker patch")
    after_sha256 = hashlib.sha256(output).hexdigest()
    if after_sha256 == before_sha256:
        raise MarkerError("Marker patch made no DDS change")
    atomic_bytes(dds_path, bytes(output))
    return {
        "before_sha256": before_sha256,
        "after_sha256": after_sha256,
        "bytes": len(output),
        "dds_dimensions": list(EXPECTED_DDS_SIZE),
        "patch_rect": list(PATCH_RECT),
        "style_uvwh": list(STYLE_UVWH),
        "patched_dxt5_blocks": local_blocks_x * local_blocks_y,
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
    target_id: str,
) -> dict[str, Any]:
    source_sha256 = sha256_file(source_g1t)
    source_bytes = source_g1t.stat().st_size
    if source_sha256 != A17_COMMON_SHA256 or source_bytes != A17_COMMON_BYTES:
        raise MarkerError(
            f"Unexpected a17_common.g1t for {target_id}: "
            f"sha256={source_sha256}, bytes={source_bytes}"
        )

    g1t_root = work_root / "g1t"
    g1t_root.mkdir(parents=True)
    local_g1t = g1t_root / "a17_common.g1t"
    shutil.copy2(source_g1t, local_g1t)

    before_listing = run_checked(
        [str(gust_g1t), "-l", local_g1t.name],
        cwd=g1t_root,
        timeout=timeout,
        description=f"gust_g1t listing of {target_id} a17_common.g1t",
    )
    # Do not infer the complete archive layout from gust_g1t's human-readable
    # listing. Different builds of gust_tools can label untouched secondary
    # entries differently even when the runtime-relevant texture 0 is the same.
    # The source G1T itself is already checksum-gated above; extraction plus a
    # byte-for-byte payload inventory is the authoritative structural check.
    extract = run_checked(
        [str(gust_g1t), "-y", local_g1t.name],
        cwd=g1t_root,
        timeout=timeout,
        description=f"gust_g1t extraction of {target_id} a17_common.g1t",
    )
    source_dir = g1t_root / "a17_common"
    dds0 = source_dir / "000.dds"
    manifest = source_dir / "g1t.json"
    if not dds0.is_file() or not manifest.is_file():
        raise MarkerError(
            "gust_g1t did not extract runtime texture 000.dds and g1t.json "
            f"for {target_id}; listing tail: {before_listing.stdout.splitlines()[-6:]}"
        )
    parse_dds_dxt5(dds0.read_bytes(), (256, 128))
    extracted_payloads = {
        path.relative_to(source_dir).as_posix(): sha256_file(path)
        for path in sorted(source_dir.rglob("*"))
        if path.is_file() and path.name != "g1t.json"
    }
    if "000.dds" not in extracted_payloads:
        raise MarkerError("Extracted a17_common payload inventory lacks 000.dds")
    untouched_payloads = {
        relative: digest
        for relative, digest in extracted_payloads.items()
        if relative != "000.dds"
    }

    preview_path = work_root / f"{target_id}_UNBURGER_UNCENSOR_a17_common.png"
    dds_patch = patch_dxt5_dds(dds0, marker, preview_path)
    patched_dds0_sha256 = sha256_file(dds0)

    original_copy = g1t_root / "a17_common.original.g1t"
    os.replace(local_g1t, original_copy)
    rebuilt = run_checked(
        [str(gust_g1t), "-y", str(source_dir)],
        cwd=g1t_root,
        timeout=timeout,
        description=f"gust_g1t rebuild of patched {target_id} a17_common.g1t",
    )
    if not local_g1t.is_file():
        raise MarkerError(f"gust_g1t did not rebuild {local_g1t}")
    rebuilt_sha256 = sha256_file(local_g1t)
    if rebuilt_sha256 == source_sha256:
        raise MarkerError("Rebuilt a17_common.g1t is byte-identical to the original")

    after_listing = run_checked(
        [str(gust_g1t), "-l", local_g1t.name],
        cwd=g1t_root,
        timeout=timeout,
        description=f"gust_g1t listing of rebuilt {target_id} a17_common.g1t",
    )

    verify_root = work_root / "g1t_verify"
    verify_root.mkdir(parents=True)
    verify_g1t = verify_root / "a17_common.g1t"
    shutil.copy2(local_g1t, verify_g1t)
    verify_extract = run_checked(
        [str(gust_g1t), "-y", verify_g1t.name],
        cwd=verify_root,
        timeout=timeout,
        description=f"gust_g1t verification extraction for {target_id}",
    )
    verified_dir = verify_root / "a17_common"
    verified_payloads = {
        path.relative_to(verified_dir).as_posix(): sha256_file(path)
        for path in sorted(verified_dir.rglob("*"))
        if path.is_file() and path.name != "g1t.json"
    }
    if set(verified_payloads) != set(extracted_payloads):
        missing = sorted(set(extracted_payloads) - set(verified_payloads))
        extra = sorted(set(verified_payloads) - set(extracted_payloads))
        raise MarkerError(
            "G1T rebuild changed the extracted payload inventory: "
            f"missing={missing}, extra={extra}"
        )
    if verified_payloads.get("000.dds") != patched_dds0_sha256:
        raise MarkerError("Patched DDS 000 changed after G1T rebuild")
    changed_untouched = [
        relative
        for relative, digest in untouched_payloads.items()
        if verified_payloads.get(relative) != digest
    ]
    if changed_untouched:
        raise MarkerError(
            "Untouched a17_common payloads changed after G1T rebuild: "
            + ", ".join(changed_untouched)
        )

    return {
        "path": local_g1t,
        "original_sha256": source_sha256,
        "original_bytes": source_bytes,
        "rebuilt_sha256": rebuilt_sha256,
        "rebuilt_bytes": local_g1t.stat().st_size,
        "dds_patch": dds_patch,
        "extracted_payload_count": len(extracted_payloads),
        "untouched_payload_sha256": untouched_payloads,
        "before_listing_stdout_tail": before_listing.stdout.splitlines()[-10:],
        "after_listing_stdout_tail": after_listing.stdout.splitlines()[-10:],
        "extract_stdout_tail": extract.stdout.splitlines()[-10:],
        "rebuild_stdout_tail": rebuilt.stdout.splitlines()[-10:],
        "verify_extract_stdout_tail": verify_extract.stdout.splitlines()[-10:],
    }


def replace_attribute(fragment: str, name: str, value: str) -> str:
    pattern = re.compile(rf"(\b{re.escape(name)}\s*=\s*)([\"']).*?\2")
    if pattern.search(fragment):
        return pattern.sub(lambda match: f'{match.group(1)}"{value}"', fragment, count=1)
    closing = "/>" if fragment.rstrip().endswith("/>") else ">"
    index = fragment.rfind(closing)
    if index < 0:
        raise MarkerError(f"Cannot append attribute {name!r} to XML fragment")
    return fragment[:index] + f' {name}="{value}"' + fragment[index:]


def patch_named_image(
    path: Path,
    image_name: str,
    attributes: dict[str, str],
) -> dict[str, Any]:
    original = path.read_bytes()
    text, codec = decode_xml_bytes(original)
    pattern = re.compile(
        rf"<image\b(?=[^>]*\bname\s*=\s*([\"']){re.escape(image_name)}\1)[^>]*?/?>",
        re.IGNORECASE,
    )
    matches = list(pattern.finditer(text))
    if len(matches) != 1:
        raise MarkerError(f"Expected one image {image_name!r} in {path}, found {len(matches)}")
    fragment = matches[0].group(0)
    patched = fragment
    old_attributes = parse_attributes(fragment)
    for name, value in attributes.items():
        patched = replace_attribute(patched, name, value)
    output_text = text[: matches[0].start()] + patched + text[matches[0].end() :]
    output = encode_xml_text(output_text, codec)
    if output == original:
        raise MarkerError(f"XML patch made no change: {path}")
    atomic_bytes(path, output)
    return {
        "path": path,
        "image_name": image_name,
        "old_attributes": {name: old_attributes.get(name) for name in attributes},
        "new_attributes": attributes,
        "before_sha256": hashlib.sha256(original).hexdigest(),
        "after_sha256": hashlib.sha256(output).hexdigest(),
    }


def patch_style_stage(stage: Path, target: Target) -> list[dict[str, Any]]:
    changes: list[dict[str, Any]] = []
    for relative, image_name in target.style_files:
        path = stage / relative
        if not path.is_file():
            raise MarkerError(f"Title style is missing from staged PAK: {relative}")
        changes.append(
            patch_named_image(
                path,
                image_name,
                {
                    "texture": "ui/a17_common.g1t",
                    "texture_index": "0",
                    "uvwh": ",".join(str(value) for value in STYLE_UVWH),
                },
            )
        )
    for relative, size_wh in target.layout_files:
        path = stage / relative
        if not path.is_file():
            raise MarkerError(f"Title layout is missing from staged PAK: {relative}")
        changes.append(patch_named_image(path, "copyright", {"size_wh": size_wh}))
    return changes


def load_clean_main_report(project_root: Path) -> tuple[Path, dict[str, Any]]:
    path = project_root / ".local/reports/translation/BR_TRANSLATION_PAK_REPACK_REPORT.json"
    if not path.is_file():
        raise MarkerError("Clean translation PAK report is missing; run steps 07 and 08")
    report = json.loads(path.read_text(encoding="utf-8"))
    if (
        report.get("type") != "br_translation_pak_repack_report"
        or report.get("status") != "ok"
        or int(report.get("summary", {}).get("failures", -1)) != 0
    ):
        raise MarkerError("Step-08 repack report is not clean")
    if isinstance(report.get("title_marker_proof"), dict) or report.get("title_markers"):
        raise MarkerError(
            "The repack report already contains a title-marker build. Rerun steps 07 and 08 "
            "with BR_TITLE_MARKER=none before step 17."
        )
    return path, report


def find_archive_entry(report: dict[str, Any], target: Target) -> dict[str, Any]:
    matches = [
        entry
        for entry in report.get("archives", [])
        if isinstance(entry, dict)
        and entry.get("target_id") == target.target_id
        and entry.get("archive_relative_path") == target.style_archive
    ]
    if len(matches) != 1:
        raise MarkerError(
            f"Expected one clean {target.style_archive} output for {target.target_id}, found {len(matches)}"
        )
    return matches[0]


def build_target(
    *,
    project_root: Path,
    target: Target,
    game_root: Path,
    main_report: dict[str, Any],
    temp_root: Path,
    gust_pak: Path,
    gust_g1t: Path,
    marker: str,
    timeout: int,
) -> dict[str, Any]:
    if not game_root.is_dir():
        raise MarkerError(f"Game root does not exist for {target.target_id}: {game_root}")
    coverage = verify_unused_region(project_root, target)
    target_root = temp_root / target.target_id
    target_root.mkdir(parents=True)

    installed_resource = game_root / target.resource_archive
    if not installed_resource.is_file():
        raise MarkerError(f"Installed resource archive is missing: {installed_resource}")
    installed_resource_sha256 = sha256_file(installed_resource)
    if target.quartet_baseline_required and installed_resource_sha256 != QUARTET_PACK10_BASELINE_SHA256:
        raise MarkerError(
            "Quartet PACK10_01.PAK is not the required baseline. Roll back any shader-profile "
            f"transaction before building the title marker. Current SHA-256: {installed_resource_sha256}"
        )

    resource_stage = target_root / "staging" / target.resource_stem
    resource_manifest, resource_extract_tail = extract_pak(
        gust_pak, installed_resource, resource_stage, timeout
    )
    staged_g1t = resource_stage / target.resource_internal
    if not staged_g1t.is_file():
        raise MarkerError(
            f"Expected runtime-known common atlas is absent: {target.resource_internal}"
        )
    g1t = build_repacked_g1t(
        staged_g1t, target_root / "common_marker", gust_g1t, marker, timeout, target.target_id
    )
    shutil.copy2(g1t["path"], staged_g1t)
    if sha256_file(staged_g1t) != g1t["rebuilt_sha256"]:
        raise MarkerError("Staged patched a17_common.g1t checksum mismatch")

    built_resource, resource_repack_tail = repack_stage(
        gust_pak, resource_stage, resource_manifest, target.resource_stem, timeout
    )
    resource_checked, resource_failures, resource_listing_tail = verify_repacked(
        gust_pak,
        built_resource,
        resource_stage,
        target_root / "verify_resource" / target.resource_stem,
        timeout,
    )
    if resource_failures:
        raise MarkerError(
            f"Full verification of {target.resource_archive} failed: {len(resource_failures)}"
        )

    style_entry = find_archive_entry(main_report, target)
    source_style = project_root / str(style_entry.get("output_path", ""))
    expected_style_sha256 = style_entry.get("output_sha256")
    if not source_style.is_file() or sha256_file(source_style) != expected_style_sha256:
        raise MarkerError(f"Clean style output changed after step 08: {source_style}")
    style_stage = target_root / "staging" / target.style_stem
    style_manifest, style_extract_tail = extract_pak(
        gust_pak, source_style, style_stage, timeout
    )
    xml_changes = patch_style_stage(style_stage, target)
    built_style, style_repack_tail = repack_stage(
        gust_pak, style_stage, style_manifest, target.style_stem, timeout
    )
    style_checked, style_failures, style_listing_tail = verify_repacked(
        gust_pak,
        built_style,
        style_stage,
        target_root / "verify_style" / target.style_stem,
        timeout,
    )
    if style_failures:
        raise MarkerError(
            f"Full verification of {target.style_archive} failed: {len(style_failures)}"
        )

    resource_entries, _ = list_pak_entries(gust_pak, built_resource, built_resource.parent, timeout)
    style_entries, _ = list_pak_entries(gust_pak, built_style, built_style.parent, timeout)
    resource_report = archive_report_entry(
        archive_stem=target.resource_stem,
        archive_relative_path=target.resource_archive,
        final_pak=built_resource,
        project_root=project_root,
        changed_files=1,
        listed_entries=len(resource_entries),
        entries_checked=resource_checked,
        failures=resource_failures,
        repack_tail=resource_repack_tail,
        listing_tail=resource_listing_tail,
        source_policy="installed_original_read_only_plus_unused_a17_common_dxt5_marker",
    )
    style_report = archive_report_entry(
        archive_stem=target.style_stem,
        archive_relative_path=target.style_archive,
        final_pak=built_style,
        project_root=project_root,
        changed_files=4,
        listed_entries=len(style_entries),
        entries_checked=style_checked,
        failures=style_failures,
        repack_tail=style_repack_tail,
        listing_tail=style_listing_tail,
        source_policy="verified_step08_translation_output_plus_title_binding_redirect",
    )
    # archive_report_entry is shared with the Second Light proof and therefore
    # carries that module's default target id. Override it explicitly here.
    resource_report["target_id"] = target.target_id
    style_report["target_id"] = target.target_id
    return {
        "target": target,
        "game_root": game_root,
        "built_resource": built_resource,
        "built_style": built_style,
        "resource_report": resource_report,
        "style_report": style_report,
        "installed_resource_sha256": installed_resource_sha256,
        "coverage": coverage,
        "g1t": g1t,
        "xml_changes": xml_changes,
        "resource_extract_tail": resource_extract_tail,
        "style_extract_tail": style_extract_tail,
    }


def build(args: argparse.Namespace) -> int:
    project_root = Path(args.project_root).expanduser().resolve()
    original_root = Path(args.original_root).expanduser().resolve()
    quartet_root = Path(args.quartet_root).expanduser().resolve()
    gust_pak = Path(args.gust_pak).expanduser().resolve()
    gust_g1t = Path(args.gust_g1t).expanduser().resolve()
    marker = safe_marker(args.marker)
    for binary, name in ((gust_pak, "gust_pak"), (gust_g1t, "gust_g1t")):
        if not binary.is_file() or not os.access(binary, os.X_OK):
            raise MarkerError(f"{name} is not executable: {binary}")
    main_report_path, main_report = load_clean_main_report(project_root)
    game_roots = {
        "blue_reflection_original": original_root,
        "blue_reflection_quartet": quartet_root,
    }

    build_root = project_root / ".local/build/translation"
    build_root.mkdir(parents=True, exist_ok=True)
    final_work_root = build_root / "blue_reflection_title_markers"
    report_path = (
        project_root
        / ".local/reports/translation/BR_BLUE_REFLECTION_TITLE_MARKERS_REPORT.json"
    )

    with tempfile.TemporaryDirectory(prefix=".br_title_markers.", dir=build_root) as raw_temp:
        temp_root = Path(raw_temp)
        results = [
            build_target(
                project_root=project_root,
                target=target,
                game_root=game_roots[target.target_id],
                main_report=main_report,
                temp_root=temp_root,
                gust_pak=gust_pak,
                gust_g1t=gust_g1t,
                marker=marker,
                timeout=args.timeout,
            )
            for target in TARGETS
        ]

        # All inputs, both targets, every G1T and every PAK have passed preflight
        # and verification. Only now publish local build outputs and the report.
        final_work_root_tmp = build_root / ".blue_reflection_title_markers.publish"
        if final_work_root_tmp.exists():
            shutil.rmtree(final_work_root_tmp)
        final_work_root_tmp.mkdir(parents=True)
        new_entries: list[dict[str, Any]] = []
        detailed_targets: list[dict[str, Any]] = []
        for result in results:
            target: Target = result["target"]
            archive_root = build_root / "archives" / target.target_id
            final_resource = archive_root / target.resource_archive
            final_style = archive_root / target.style_archive
            install_verified_output(result["built_resource"], final_resource)
            install_verified_output(result["built_style"], final_style)

            resource_report = dict(result["resource_report"])
            style_report = dict(result["style_report"])
            for entry, final_path in (
                (resource_report, final_resource),
                (style_report, final_style),
            ):
                entry["output_path"] = final_path.relative_to(project_root).as_posix()
                entry["output_sha256"] = sha256_file(final_path)
                entry["output_bytes"] = final_path.stat().st_size
            new_entries.extend((resource_report, style_report))

            preview: Path = result["g1t"]["dds_patch"]["preview_path"]
            published_preview = final_work_root_tmp / preview.name
            shutil.copy2(preview, published_preview)
            detailed_targets.append(
                {
                    "target_id": target.target_id,
                    "game_root": target.game_root_placeholder,
                    "marker": marker,
                    "method": "unused_region_of_existing_a17_common_g1t_plus_existing_title_style_redirect",
                    "runtime_status": "awaiting_manual_title_screen_test",
                    "resource_archive": target.resource_archive,
                    "resource_path": target.resource_internal,
                    "style_archive": target.style_archive,
                    "style_files": [path for path, _name in target.style_files],
                    "layout_files": [path for path, _size in target.layout_files],
                    "installed_resource_sha256": result["installed_resource_sha256"],
                    "static_unused_region_validation": result["coverage"],
                    "g1t": {
                        key: value
                        for key, value in result["g1t"].items()
                        if key
                        not in {
                            "path",
                            "dds_patch",
                        }
                    },
                    "dds_patch": {
                        key: (
                            published_preview.relative_to(project_root).as_posix()
                            if key == "preview_path"
                            else value
                        )
                        for key, value in result["g1t"]["dds_patch"].items()
                    },
                    "xml_changes": [
                        {
                            **{
                                key: value
                                for key, value in change.items()
                                if key != "path"
                            },
                            "path": change["path"].relative_to(temp_root).as_posix(),
                        }
                        for change in result["xml_changes"]
                    ],
                    "resource_archive_report": resource_report,
                    "style_archive_report": style_report,
                    "resource_extraction_stdout_tail": result["resource_extract_tail"],
                    "style_extraction_stdout_tail": result["style_extract_tail"],
                }
            )

        if final_work_root.exists():
            shutil.rmtree(final_work_root)
        os.replace(final_work_root_tmp, final_work_root)

    replacement_keys = {
        (entry["target_id"], entry["archive_relative_path"]) for entry in new_entries
    }
    kept = [
        entry
        for entry in main_report.get("archives", [])
        if isinstance(entry, dict)
        and (entry.get("target_id"), entry.get("archive_relative_path"))
        not in replacement_keys
    ]
    main_report["archives"] = sorted(
        kept + new_entries,
        key=lambda entry: (
            str(entry.get("target_id", "")),
            str(entry.get("archive_relative_path", "")),
        ),
    )
    main_report["gust_g1t_sha256"] = sha256_file(gust_g1t)
    main_report["title_markers"] = {
        "status": "ok",
        "marker": marker,
        "method": "existing_a17_common_unused_dxt5_region",
        "targets": [target.target_id for target in TARGETS],
        "runtime_status": "awaiting_manual_title_screen_tests",
    }
    recompute_main_summary(main_report)
    if main_report.get("status") != "ok":
        raise MarkerError("Refusing to publish a failed combined repack report")

    report = {
        "type": REPORT_TYPE,
        "format_version": 1,
        "status": "ok",
        "generated_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "project_root": "<PROJECT_ROOT>",
        "marker": marker,
        "method": "existing_a17_common_unused_dxt5_region",
        "runtime_status": "awaiting_manual_title_screen_tests",
        "targets": detailed_targets,
        "safety": {
            "installed_game_files_modified_during_build": False,
            "proprietary_asset_in_update_package": False,
            "proprietary_assets_read_only_sources": True,
            "patched_assets_created_only_under_local_build": True,
            "no_repeat_of_steps_11_13": True,
            "unused_region_proven_from_all_localized_style_references": True,
            "full_g1t_reextract_hash_verification": True,
            "full_pak_reextract_hash_verification": True,
            "quartet_shader_profile_must_be_rolled_back": True,
            "installation_requires_step_09": True,
        },
        "test_order": [
            "install blue_reflection_original; inspect marker; restore",
            "install blue_reflection_quartet; inspect marker; restore",
        ],
    }
    atomic_json(main_report_path, main_report)
    atomic_json(report_path, report)

    print("Blue Reflection Original and Quartet title markers built and fully verified.")
    print(f"Marker: {marker}")
    print(f"Shared DXT5 patch rectangle: {PATCH_RECT}")
    print(f"Shared style UV rectangle: {STYLE_UVWH}")
    print("No installed game file was modified during the build.")
    return 0


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("--project-root", required=True)
    result.add_argument("--original-root", required=True)
    result.add_argument("--quartet-root", required=True)
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
