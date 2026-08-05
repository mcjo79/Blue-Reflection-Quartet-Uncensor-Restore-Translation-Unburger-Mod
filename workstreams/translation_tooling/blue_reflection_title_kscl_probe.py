#!/usr/bin/env python3
"""Build a focused runtime probe for Original Blue Reflection's 12_title.kscl.

Only one installed source archive is read: DATA/PACK00_04_1.PAK. Only one
member is modified: data/x64/res_en/layout/12_title.kscl. The KSCL's embedded
KSLT texture payloads are replaced in-place with distinct checker patterns
without changing texture sizes, table offsets, or any non-texture bytes.
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
from pathlib import Path
from typing import Any

from second_light_title_marker_proof import (
    ProofError,
    atomic_json,
    install_verified_output,
    list_pak_entries,
    recompute_main_summary,
    repack_stage,
    run_checked,
    sha256_file,
    verify_repacked,
    encode_dxt5_block,
)

REPORT_TYPE = "br_blue_reflection_title_kscl_probe_report"
TARGET_ID = "blue_reflection_original"
ARCHIVE_RELATIVE = "DATA/PACK00_04_1.PAK"
ARCHIVE_STEM = "PACK00_04_1"
RESOURCE_PATH = "data/x64/res_en/layout/12_title.kscl"
EXPECTED_SOURCE_PAK_SHA256 = "1603d406ea0242adf83dde0293685d0569d20d37e8ed08cc321dc62b30441d5f"
KSCL_MAGIC = 0x4B53434C
KSLT_MAGIC = 0x4B534C54

PALETTES = (
    ("red", (255, 40, 40, 255), (35, 0, 0, 255)),
    ("green", (45, 255, 80, 255), (0, 35, 6, 255)),
    ("blue", (50, 110, 255, 255), (0, 6, 38, 255)),
    ("magenta", (255, 45, 235, 255), (38, 0, 32, 255)),
    ("cyan", (35, 245, 255, 255), (0, 32, 38, 255)),
    ("yellow", (255, 235, 40, 255), (38, 32, 0, 255)),
    ("orange", (255, 135, 35, 255), (38, 12, 0, 255)),
    ("violet", (155, 70, 255, 255), (16, 0, 38, 255)),
)


class KSCLProbeError(ProofError):
    pass


def u16(data: bytes | bytearray, offset: int) -> int:
    if offset < 0 or offset + 2 > len(data):
        raise KSCLProbeError(f"Out-of-range uint16 at 0x{offset:x}")
    return struct.unpack_from("<H", data, offset)[0]


def u32(data: bytes | bytearray, offset: int) -> int:
    if offset < 0 or offset + 4 > len(data):
        raise KSCLProbeError(f"Out-of-range uint32 at 0x{offset:x}")
    return struct.unpack_from("<I", data, offset)[0]


def read_c_string(data: bytes | bytearray, offset: int) -> tuple[str, int]:
    if offset < 0 or offset >= len(data):
        raise KSCLProbeError(f"Out-of-range string at 0x{offset:x}")
    end = data.find(b"\0", offset)
    if end < 0:
        raise KSCLProbeError(f"Unterminated KSCL texture name at 0x{offset:x}")
    try:
        value = bytes(data[offset:end]).decode("ascii")
    except UnicodeDecodeError as exc:
        raise KSCLProbeError(f"Non-ASCII KSCL texture name at 0x{offset:x}") from exc
    return value, end + 1


def parse_kscl(data: bytes | bytearray) -> dict[str, Any]:
    if len(data) < 0x8C or u32(data, 0) != KSCL_MAGIC:
        raise KSCLProbeError("12_title.kscl does not have the supported KSCL header")
    kscl_length = u32(data, 8) + 0x8C
    if kscl_length + 0x40 > len(data):
        raise KSCLProbeError("KSCL header length points outside the file")
    if u32(data, kscl_length) != KSLT_MAGIC:
        raise KSCLProbeError("KSCL does not contain the expected embedded KSLT block")

    texture_count = u32(data, kscl_length + 8)
    headerless_size = u32(data, kscl_length + 12)
    table_pointer = u32(data, kscl_length + 16)
    name_length = u32(data, kscl_length + 20)
    name_count = u32(data, kscl_length + 24)
    if texture_count <= 0 or texture_count > 4096:
        raise KSCLProbeError(f"Implausible embedded texture count: {texture_count}")

    table_base = kscl_length + table_pointer + 0x40
    names_base = table_base + 0x14 * texture_count
    if names_base > len(data):
        raise KSCLProbeError("KSLT table or name area points outside the file")

    names: list[str] = []
    cursor = names_base
    for index in range(texture_count):
        name, cursor = read_c_string(data, cursor)
        names.append(name or f"texture_{index:03d}")

    textures: list[dict[str, Any]] = []
    ranges: list[tuple[int, int, int]] = []
    for index in range(texture_count):
        entry = table_base + index * 0x14
        pointer = u32(data, entry)
        header = kscl_length + pointer
        if header + 0x48 > len(data):
            raise KSCLProbeError(f"Texture {index} header points outside the file")
        format_type = u32(data, header)
        width = u16(data, header + 4)
        height = u16(data, header + 6)
        raw_size = u32(data, header + 0x1C)
        raw_offset = header + 0x48
        raw_end = raw_offset + raw_size
        if width <= 0 or height <= 0:
            raise KSCLProbeError(f"Texture {index} has invalid dimensions {width}x{height}")
        if raw_size <= 0 or raw_end > len(data):
            raise KSCLProbeError(f"Texture {index} raw payload points outside the file")
        if format_type not in {0, 3}:
            raise KSCLProbeError(
                f"Texture {index} ({names[index]}) uses unsupported KSCL format {format_type}"
            )
        ranges.append((raw_offset, raw_end, index))
        textures.append(
            {
                "index": index,
                "name": names[index],
                "table_entry_offset": entry,
                "texture_header_offset": header,
                "raw_offset": raw_offset,
                "raw_size": raw_size,
                "format_type": format_type,
                "format": "RGBA8" if format_type == 0 else "BC3_DXT5",
                "width": width,
                "height": height,
            }
        )

    ranges.sort()
    for previous, current in zip(ranges, ranges[1:]):
        if previous[1] > current[0]:
            raise KSCLProbeError(
                f"Embedded texture payloads overlap: {previous[2]} and {current[2]}"
            )

    return {
        "kscl_length": kscl_length,
        "texture_count": texture_count,
        "headerless_size": headerless_size,
        "table_pointer": table_pointer,
        "name_length": name_length,
        "name_count": name_count,
        "table_base": table_base,
        "names_base": names_base,
        "textures": textures,
    }


def palette_for(index: int) -> tuple[str, tuple[int, int, int, int], tuple[int, int, int, int]]:
    return PALETTES[index % len(PALETTES)]


def checker_pixel(x: int, y: int, index: int, light: tuple[int, int, int, int], dark: tuple[int, int, int, int]) -> tuple[int, int, int, int]:
    large = ((x // 32) + (y // 32) + index) & 1
    diagonal = ((x + y) // 12) & 1
    return light if (large ^ diagonal) == 0 else dark


def patch_rgba8(out: bytearray, tex: dict[str, Any], index: int, light: tuple[int, int, int, int], dark: tuple[int, int, int, int]) -> int:
    width = int(tex["width"])
    height = int(tex["height"])
    required = width * height * 4
    if required > int(tex["raw_size"]):
        raise KSCLProbeError(
            f"RGBA8 texture {index} base mip exceeds raw payload: {required} > {tex['raw_size']}"
        )
    cursor = int(tex["raw_offset"])
    for y in range(height):
        for x in range(width):
            out[cursor : cursor + 4] = bytes(checker_pixel(x, y, index, light, dark))
            cursor += 4
    return required


def patch_dxt5(out: bytearray, tex: dict[str, Any], index: int, light: tuple[int, int, int, int], dark: tuple[int, int, int, int]) -> int:
    width = int(tex["width"])
    height = int(tex["height"])
    blocks_x = math.ceil(width / 4)
    blocks_y = math.ceil(height / 4)
    required = blocks_x * blocks_y * 16
    if required > int(tex["raw_size"]):
        raise KSCLProbeError(
            f"DXT5 texture {index} base mip exceeds raw payload: {required} > {tex['raw_size']}"
        )
    cursor = int(tex["raw_offset"])
    for block_y in range(blocks_y):
        for block_x in range(blocks_x):
            block: list[tuple[int, int, int, int]] = []
            for dy in range(4):
                for dx in range(4):
                    block.append(
                        checker_pixel(
                            block_x * 4 + dx,
                            block_y * 4 + dy,
                            index,
                            light,
                            dark,
                        )
                    )
            encoded = encode_dxt5_block(block)
            out[cursor : cursor + 16] = encoded
            cursor += 16
    return required


def patch_kscl(path: Path) -> dict[str, Any]:
    original = path.read_bytes()
    parsed = parse_kscl(original)
    out = bytearray(original)
    patch_details: list[dict[str, Any]] = []
    for tex in parsed["textures"]:
        index = int(tex["index"])
        colour_name, light, dark = palette_for(index)
        raw_offset = int(tex["raw_offset"])
        raw_size = int(tex["raw_size"])
        before = hashlib.sha256(original[raw_offset : raw_offset + raw_size]).hexdigest()
        if int(tex["format_type"]) == 0:
            base_bytes = patch_rgba8(out, tex, index, light, dark)
        else:
            base_bytes = patch_dxt5(out, tex, index, light, dark)
        after = hashlib.sha256(out[raw_offset : raw_offset + raw_size]).hexdigest()
        if before == after:
            raise KSCLProbeError(f"Texture {index} probe made no change")
        patch_details.append(
            {
                **tex,
                "probe_colour": colour_name,
                "palette_light": list(light),
                "palette_dark": list(dark),
                "base_mip_bytes_patched": base_bytes,
                "before_raw_sha256": before,
                "after_raw_sha256": after,
            }
        )

    before_file = hashlib.sha256(original).hexdigest()
    after_file = hashlib.sha256(out).hexdigest()
    if before_file == after_file:
        raise KSCLProbeError("KSCL probe produced an unchanged file")
    install_verified_output_bytes(bytes(out), path)
    reparsed = parse_kscl(path.read_bytes())
    if [
        (item["name"], item["format_type"], item["width"], item["height"], item["raw_size"])
        for item in reparsed["textures"]
    ] != [
        (item["name"], item["format_type"], item["width"], item["height"], item["raw_size"])
        for item in parsed["textures"]
    ]:
        raise KSCLProbeError("KSCL structure changed after in-place texture patching")
    return {
        "resource_path": RESOURCE_PATH,
        "before_sha256": before_file,
        "after_sha256": after_file,
        "bytes": len(original),
        "kscl": {key: value for key, value in parsed.items() if key != "textures"},
        "textures": patch_details,
    }


def install_verified_output_bytes(data: bytes, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    fd, raw_tmp = tempfile.mkstemp(prefix=f".{destination.name}.", dir=destination.parent)
    tmp = Path(raw_tmp)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, destination)
    finally:
        tmp.unlink(missing_ok=True)


def extract_pak_symlink(gust_pak: Path, source_pak: Path, stage: Path, timeout: int) -> tuple[Path, list[str]]:
    if stage.exists():
        shutil.rmtree(stage)
    stage.mkdir(parents=True)
    link = stage / source_pak.name
    os.symlink(source_pak, link)
    try:
        process = run_checked(
            [str(gust_pak), source_pak.name],
            cwd=stage,
            timeout=timeout,
            description=f"gust_pak extraction of {source_pak.name}",
        )
    finally:
        link.unlink(missing_ok=True)
    (stage / f"{source_pak.name}.bak").unlink(missing_ok=True)
    preferred = stage / f"{source_pak.stem}.json"
    if preferred.is_file():
        manifest = preferred
    else:
        manifests = sorted(stage.glob("*.json"))
        if len(manifests) != 1:
            raise KSCLProbeError(
                f"Expected one gust_pak manifest after extracting {source_pak.name}, found {len(manifests)}"
            )
        manifest = manifests[0]
    return manifest, process.stdout.splitlines()[-10:]


def build(args: argparse.Namespace) -> int:
    project_root = Path(args.project_root).expanduser().resolve()
    original_root = Path(args.original_root).expanduser().resolve()
    gust_pak = Path(args.gust_pak).expanduser().resolve()
    timeout = args.timeout

    source_pak = original_root / ARCHIVE_RELATIVE
    if not source_pak.is_file():
        raise KSCLProbeError(f"Missing Original source archive: {source_pak}")
    source_hash = sha256_file(source_pak)
    if source_hash != EXPECTED_SOURCE_PAK_SHA256:
        raise KSCLProbeError(
            "Original DATA/PACK00_04_1.PAK is not the known baseline; restore any previous test first "
            f"(current {source_hash})"
        )

    main_report_path = project_root / ".local/reports/translation/BR_TRANSLATION_PAK_REPACK_REPORT.json"
    if not main_report_path.is_file():
        raise KSCLProbeError("Translation repack report missing; run steps 07 and 08 first")
    main_report = json.loads(main_report_path.read_text(encoding="utf-8"))
    if main_report.get("status") != "ok":
        raise KSCLProbeError("Translation repack report is not ok")

    build_root = project_root / ".local/build/translation"
    build_root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".br1_12_title_kscl_probe.", dir=build_root) as raw_tmp:
        temp_root = Path(raw_tmp)
        stage = temp_root / "stage"
        manifest, extract_tail = extract_pak_symlink(gust_pak, source_pak, stage, timeout)
        entries, _ = list_pak_entries(gust_pak, source_pak, temp_root, timeout)
        normalized = {entry.casefold(): entry for entry in entries}
        key = RESOURCE_PATH.casefold()
        if key not in normalized:
            raise KSCLProbeError(f"Resource not present in source PAK: {RESOURCE_PATH}")
        staged_kscl = stage / Path(normalized[key])
        if not staged_kscl.is_file():
            raise KSCLProbeError(f"Extracted resource missing: {staged_kscl}")

        resource_details = patch_kscl(staged_kscl)
        built, repack_tail = repack_stage(gust_pak, stage, manifest, ARCHIVE_STEM, timeout)
        checked, failures, listing_tail = verify_repacked(
            gust_pak, built, stage, temp_root / "verify_pak", timeout
        )
        if failures:
            raise KSCLProbeError(f"PAK verification failed: {failures[:3]}")

        final = build_root / "archives" / TARGET_ID / ARCHIVE_RELATIVE
        install_verified_output(built, final)

    # Remove the obsolete broad G1T probe so the next runtime test has one candidate only.
    broad_probe = build_root / "archives" / TARGET_ID / "DATA/PACK00_01.PAK"
    broad_probe.unlink(missing_ok=True)
    main_report["archives"] = [
        entry
        for entry in main_report.get("archives", [])
        if not (
            entry.get("target_id") == TARGET_ID
            and entry.get("archive_relative_path") in {"DATA/PACK00_01.PAK", ARCHIVE_RELATIVE}
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
        "source_policy": "installed_original_read_only_plus_single_kscl_embedded_texture_probe",
    }
    main_report["archives"].append(archive_entry)
    main_report["archives"].sort(
        key=lambda entry: (str(entry.get("target_id")), str(entry.get("archive_relative_path")))
    )
    main_report.pop("title_resource_pixel_probe", None)
    main_report["blue_reflection_title_kscl_probe"] = {
        "status": "ok",
        "resource": RESOURCE_PATH,
        "runtime_status": "awaiting_manual_test",
        "embedded_texture_count": len(resource_details["textures"]),
    }
    recompute_main_summary(main_report)
    atomic_json(main_report_path, main_report)

    report = {
        "type": REPORT_TYPE,
        "format_version": 1,
        "status": "ok",
        "method": "single_kscl_embedded_kslt_texture_probe",
        "runtime_status": "awaiting_manual_test",
        "project_root": "<PROJECT_ROOT>",
        "target_id": TARGET_ID,
        "archive": ARCHIVE_RELATIVE,
        "source_archive_sha256": source_hash,
        "output_archive_sha256": sha256_file(final),
        "resource": resource_details,
        "interpretation": (
            "Any visible checker pattern confirms that the English 12_title.kscl is active. "
            "The probe_colour field maps each visible colour to its embedded texture index and name."
        ),
        "archive_report": archive_entry,
        "extract_tail": extract_tail,
        "safety": {
            "installed_files_modified_during_build": False,
            "proprietary_assets_in_update_package": False,
            "only_one_pak_modified": True,
            "only_one_kscl_modified": True,
            "texture_payload_sizes_preserved": True,
            "full_pak_reextract_verification": True,
            "installation_requires_step_09": True,
        },
    }
    atomic_json(
        project_root / ".local/reports/translation/BR_BLUE_REFLECTION_TITLE_KSCL_PROBE_REPORT.json",
        report,
    )
    print(f"Original Blue Reflection 12_title.kscl probe built: {len(resource_details['textures'])} embedded textures")
    return 0


def self_test() -> int:
    texture_names = ["probe_rgba", "probe_dxt5"]
    tex_count = len(texture_names)
    kscl_length = 0x8C
    table_pointer = 0
    table_base = kscl_length + 0x40
    names_base = table_base + 0x14 * tex_count
    names = b"".join(name.encode("ascii") + b"\0" for name in texture_names)
    first_header = names_base + len(names)
    first_header = (first_header + 0x0F) & ~0x0F
    first_pointer = first_header - kscl_length
    rgba_raw = 8 * 8 * 4
    second_header = first_header + 0x48 + rgba_raw
    second_header = (second_header + 0x0F) & ~0x0F
    second_pointer = second_header - kscl_length
    dxt_raw = math.ceil(8 / 4) * math.ceil(8 / 4) * 16
    total = second_header + 0x48 + dxt_raw
    blob = bytearray(total)
    struct.pack_into("<I", blob, 0, KSCL_MAGIC)
    struct.pack_into("<I", blob, 8, kscl_length - 0x8C)
    struct.pack_into("<I", blob, kscl_length, KSLT_MAGIC)
    struct.pack_into("<IIIII", blob, kscl_length + 8, tex_count, total - kscl_length, table_pointer, len(names), tex_count)
    blob[names_base : names_base + len(names)] = names
    struct.pack_into("<I", blob, table_base, first_pointer)
    struct.pack_into("<I", blob, table_base + 0x14, second_pointer)
    struct.pack_into("<IHH", blob, first_header, 0, 8, 8)
    struct.pack_into("<I", blob, first_header + 0x1C, rgba_raw)
    struct.pack_into("<IHH", blob, second_header, 3, 8, 8)
    struct.pack_into("<I", blob, second_header + 0x1C, dxt_raw)
    parsed = parse_kscl(blob)
    if parsed["texture_count"] != 2 or [item["format_type"] for item in parsed["textures"]] != [0, 3]:
        raise KSCLProbeError("Synthetic KSCL parser self-test failed")
    print("KSCL parser self-test passed")
    return 0


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser()
    p.add_argument("--project-root")
    p.add_argument("--original-root")
    p.add_argument("--gust-pak")
    p.add_argument("--timeout", type=int, default=1800)
    p.add_argument("--self-test", action="store_true")
    return p


if __name__ == "__main__":
    try:
        args = parser().parse_args()
        if args.self_test:
            raise SystemExit(self_test())
        if not all((args.project_root, args.original_root, args.gust_pak)):
            raise KSCLProbeError("--project-root, --original-root and --gust-pak are required")
        raise SystemExit(build(args))
    except (KSCLProbeError, OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}", file=os.sys.stderr)
        raise SystemExit(1)
