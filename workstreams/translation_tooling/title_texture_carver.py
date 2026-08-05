#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import mmap
import os
import re
import shutil
import struct
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any


class CarveError(RuntimeError):
    pass


SIGNATURES = (b"GT1G", b"G1TG")
HEADER_SIZE = 28
MIN_BLOB_SIZE = 4 * 1024
MAX_BLOB_SIZE = 64 * 1024 * 1024
SUPPORTED_PLATFORMS = {0x00, 0x0A}
PROFILE_RULES: dict[str, dict[str, Any]] = {
    "a17_title": {
        "texture_count": 2,
        "minimum_dimensions": ((1452, 696), (428, 720)),
        "copyright_crop": (0, 411, 808, 45),
    },
    "a18_title": {
        "texture_count": 3,
        "minimum_dimensions": ((1520, 756), (572, 720), (572, 140)),
        "copyright_crop": (3, 568, 861, 44),
    },
}
LIST_TEXTURE_RE = re.compile(
    r"^0x[0-9a-fA-F]+\s+0x[0-9a-fA-F]+\s+0x[0-9a-fA-F]+\s+"
    r"(?P<name>\S+)\s+(?P<width>\d+)x(?P<height>\d+)\s+"
    r"(?P<mipmaps>\d+)\s+(?P<props>.*)$"
)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def safe_name(value: str) -> str:
    value = value.replace("\\", "/").strip("/")
    value = re.sub(r"[^A-Za-z0-9._-]+", "__", value)
    return value[:160] or "container"


def run(command: list[str], cwd: Path, timeout: int) -> subprocess.CompletedProcess[str]:
    try:
        process = subprocess.run(
            command,
            cwd=cwd,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        raise CarveError(f"Command timed out: {command[0]}") from exc
    if process.returncode != 0:
        raise CarveError(
            f"Command failed ({process.returncode}): {' '.join(command)}\n"
            f"STDOUT:\n{process.stdout}\nSTDERR:\n{process.stderr}"
        )
    return process


def game_archives(game_root: Path) -> list[Path]:
    return sorted(
        (
            path for path in game_root.rglob("*")
            if path.is_file() and path.suffix.casefold() == ".pak" and "__" not in path.name
        ),
        key=lambda path: path.relative_to(game_root).as_posix().casefold(),
    )


def parse_candidate_header(mapped: mmap.mmap, offset: int) -> dict[str, int] | None:
    remaining = len(mapped) - offset
    if remaining < HEADER_SIZE:
        return None
    signature = bytes(mapped[offset:offset + 4])
    if signature not in SIGNATURES:
        return None
    version, total_size, header_size, texture_count, platform, extra_size = struct.unpack_from(
        "<6I", mapped, offset + 4
    )
    if not (MIN_BLOB_SIZE <= total_size <= MAX_BLOB_SIZE):
        return None
    if total_size > remaining:
        return None
    if not (HEADER_SIZE <= header_size <= min(total_size, 4 * 1024 * 1024)):
        return None
    if not (1 <= texture_count <= 64):
        return None
    if platform not in SUPPORTED_PLATFORMS:
        return None
    if extra_size > total_size:
        return None
    return {
        "version": version,
        "total_size": total_size,
        "header_size": header_size,
        "texture_count": texture_count,
        "platform": platform,
        "extra_size": extra_size,
    }


def find_candidate_offsets(path: Path) -> list[tuple[int, dict[str, int]]]:
    candidates: list[tuple[int, dict[str, int]]] = []
    with path.open("rb") as handle:
        if path.stat().st_size < HEADER_SIZE:
            return candidates
        with mmap.mmap(handle.fileno(), 0, access=mmap.ACCESS_READ) as mapped:
            seen: set[int] = set()
            for signature in SIGNATURES:
                cursor = 0
                while True:
                    offset = mapped.find(signature, cursor)
                    if offset < 0:
                        break
                    cursor = offset + 1
                    if offset in seen:
                        continue
                    seen.add(offset)
                    header = parse_candidate_header(mapped, offset)
                    if header is not None:
                        candidates.append((offset, header))
    return sorted(candidates, key=lambda item: item[0])


def read_blob(path: Path, offset: int, total_size: int) -> bytes:
    with path.open("rb") as handle:
        handle.seek(offset)
        data = handle.read(total_size)
    if len(data) != total_size:
        raise CarveError(f"Short read while carving {path} at 0x{offset:x}")
    return data


def parse_gust_listing(stdout: str) -> list[dict[str, Any]]:
    textures: list[dict[str, Any]] = []
    for line in stdout.splitlines():
        match = LIST_TEXTURE_RE.match(line.strip())
        if not match:
            continue
        textures.append({
            "name": match.group("name"),
            "width": int(match.group("width")),
            "height": int(match.group("height")),
            "mipmaps": int(match.group("mipmaps")),
            "properties": match.group("props").strip(),
        })
    return textures


def profile_scores(textures: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for profile, rule in PROFILE_RULES.items():
        expected_count = int(rule["texture_count"])
        minima = tuple(rule["minimum_dimensions"])
        count_match = len(textures) == expected_count
        checks: list[bool] = []
        dimensions: list[dict[str, Any]] = []
        for index, (min_width, min_height) in enumerate(minima):
            if index < len(textures):
                width = int(textures[index]["width"])
                height = int(textures[index]["height"])
                matched = width >= min_width and height >= min_height
                dimensions.append({
                    "index": index,
                    "actual": [width, height],
                    "minimum": [min_width, min_height],
                    "matched": matched,
                })
                checks.append(matched)
            else:
                dimensions.append({
                    "index": index,
                    "actual": None,
                    "minimum": [min_width, min_height],
                    "matched": False,
                })
                checks.append(False)
        score = (2.0 if count_match else 0.0) + sum(1.0 for matched in checks if matched)
        maximum = 2.0 + len(checks)
        exact = count_match and all(checks)
        result[profile] = {
            "score": score,
            "maximum_score": maximum,
            "normalized_score": score / maximum,
            "exact_profile_match": exact,
            "texture_count_match": count_match,
            "dimension_checks": dimensions,
            "copyright_crop": list(rule["copyright_crop"]),
        }
    return result


def extract_candidate(
    gust_g1t: Path,
    blob_path: Path,
    output_dir: Path,
    timeout: int,
) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=False)
    local_blob = output_dir / blob_path.name
    shutil.copy2(blob_path, local_blob)
    process = run([str(gust_g1t), "-y", local_blob.name], output_dir, timeout)
    (output_dir / "gust_g1t_extract.txt").write_text(
        process.stdout + ("\nSTDERR:\n" + process.stderr if process.stderr else ""),
        encoding="utf-8",
    )
    dds_files = sorted(output_dir.rglob("*.dds"))
    json_files = sorted(output_dir.rglob("g1t.json"))
    return {
        "dds_files": [path.relative_to(output_dir).as_posix() for path in dds_files],
        "g1t_json": (
            json_files[0].relative_to(output_dir).as_posix()
            if len(json_files) == 1 else None
        ),
    }


def create_previews(
    output_dir: Path,
    textures: list[dict[str, Any]],
    profile_data: dict[str, dict[str, Any]],
) -> list[str]:
    magick = shutil.which("magick") or shutil.which("convert")
    if magick is None:
        return []
    dds_files = sorted(output_dir.rglob("*.dds"))
    previews: list[str] = []
    for index, dds in enumerate(dds_files):
        png = output_dir / f"texture_{index:02d}.png"
        process = subprocess.run(
            [magick, str(dds), str(png)],
            capture_output=True,
            text=True,
        )
        if process.returncode == 0 and png.is_file():
            previews.append(png.relative_to(output_dir).as_posix())
    if not dds_files:
        return previews
    for profile, data in profile_data.items():
        if not data.get("exact_profile_match"):
            continue
        x, y, width, height = data["copyright_crop"]
        crop = output_dir / f"{profile}_copyright_crop.png"
        process = subprocess.run(
            [
                magick,
                str(dds_files[0]),
                "-crop",
                f"{width}x{height}+{x}+{y}",
                "+repage",
                str(crop),
            ],
            capture_output=True,
            text=True,
        )
        if process.returncode == 0 and crop.is_file():
            previews.append(crop.relative_to(output_dir).as_posix())
    return previews


def scan_target(
    target: str,
    game_root: Path,
    gust_g1t: Path,
    output_root: Path,
    timeout: int,
) -> dict[str, Any]:
    target_root = output_root / target
    target_root.mkdir(parents=True, exist_ok=False)
    scratch = Path(tempfile.mkdtemp(prefix=f"br-g1t-carve-{target}-", dir=output_root.parent))
    report: dict[str, Any] = {
        "game_root": "<GAME_ROOT>",
        "archives": [],
        "candidate_count": 0,
        "valid_g1t_count": 0,
        "exact_profile_matches": [],
        "top_candidates": {"a17_title": [], "a18_title": []},
    }
    candidates: list[dict[str, Any]] = []
    seen_hashes: set[str] = set()
    try:
        for archive in game_archives(game_root):
            archive_relative = archive.relative_to(game_root).as_posix()
            hits = find_candidate_offsets(archive)
            archive_record = {
                "path": archive_relative,
                "bytes": archive.stat().st_size,
                "header_candidates": len(hits),
            }
            report["archives"].append(archive_record)
            for offset, header in hits:
                # The known title bundles contain exactly 2 or 3 textures.
                if header["texture_count"] not in {2, 3}:
                    continue
                blob = read_blob(archive, offset, header["total_size"])
                digest = sha256_bytes(blob)
                if digest in seen_hashes:
                    continue
                seen_hashes.add(digest)
                candidate_name = (
                    f"{safe_name(archive_relative)}__0x{offset:012x}__"
                    f"{header['texture_count']}tex.g1t"
                )
                candidate_path = scratch / candidate_name
                candidate_path.write_bytes(blob)
                listing = subprocess.run(
                    [str(gust_g1t), "-l", candidate_path.name],
                    cwd=scratch,
                    stdin=subprocess.DEVNULL,
                    capture_output=True,
                    text=True,
                    timeout=timeout,
                )
                item: dict[str, Any] = {
                    "archive": archive_relative,
                    "offset": offset,
                    "offset_hex": f"0x{offset:x}",
                    "blob_bytes": len(blob),
                    "blob_sha256": digest,
                    "header": header,
                    "gust_g1t_returncode": listing.returncode,
                }
                if listing.returncode != 0:
                    item["gust_g1t_stderr_tail"] = listing.stderr.splitlines()[-10:]
                    candidates.append(item)
                    continue
                textures = parse_gust_listing(listing.stdout)
                if not textures:
                    item["gust_g1t_stdout_tail"] = listing.stdout.splitlines()[-10:]
                    candidates.append(item)
                    continue
                item["textures"] = textures
                item["profiles"] = profile_scores(textures)
                item["valid_g1t"] = True
                report["valid_g1t_count"] += 1
                candidates.append(item)

                exact_profiles = [
                    profile for profile, data in item["profiles"].items()
                    if data["exact_profile_match"]
                ]
                if exact_profiles:
                    candidate_out = target_root / (
                        f"candidate_{len(report['exact_profile_matches']) + 1:03d}_"
                        f"{safe_name(archive_relative)}_0x{offset:x}"
                    )
                    extraction = extract_candidate(
                        gust_g1t, candidate_path, candidate_out, timeout
                    )
                    previews = create_previews(
                        candidate_out, textures, item["profiles"]
                    )
                    shutil.copy2(candidate_path, candidate_out / "carved.g1t")
                    (candidate_out / "gust_g1t_list.txt").write_text(
                        listing.stdout + (
                            "\nSTDERR:\n" + listing.stderr if listing.stderr else ""
                        ),
                        encoding="utf-8",
                    )
                    evidence_relative = candidate_out.relative_to(output_root).as_posix()
                    exact_record = {
                        "archive": archive_relative,
                        "offset_hex": f"0x{offset:x}",
                        "blob_sha256": digest,
                        "profiles": exact_profiles,
                        "textures": textures,
                        "evidence_directory": evidence_relative,
                        "dds_files": extraction["dds_files"],
                        "g1t_json": extraction["g1t_json"],
                        "previews": previews,
                    }
                    report["exact_profile_matches"].append(exact_record)
                    item["evidence_directory"] = evidence_relative

        report["candidate_count"] = len(candidates)
        for profile in PROFILE_RULES:
            ranked = sorted(
                (
                    item for item in candidates
                    if item.get("valid_g1t") and profile in item.get("profiles", {})
                ),
                key=lambda item: (
                    item["profiles"][profile]["normalized_score"],
                    item["profiles"][profile]["exact_profile_match"],
                    item["blob_bytes"],
                ),
                reverse=True,
            )[:20]
            report["top_candidates"][profile] = [
                {
                    "archive": item["archive"],
                    "offset_hex": item["offset_hex"],
                    "blob_bytes": item["blob_bytes"],
                    "blob_sha256": item["blob_sha256"],
                    "textures": item["textures"],
                    "profile": item["profiles"][profile],
                    "evidence_directory": item.get("evidence_directory"),
                }
                for item in ranked
            ]
        report["status"] = (
            "exact_candidates_found"
            if report["exact_profile_matches"] else "no_exact_candidate"
        )
        return report
    finally:
        shutil.rmtree(scratch, ignore_errors=True)


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Carve hidden Windows G1T blobs from Blue Reflection PAK containers "
            "and identify title-atlas candidates by texture geometry."
        )
    )
    parser.add_argument("--project-root", required=True)
    parser.add_argument("--original-root", required=True)
    parser.add_argument("--quartet-root", required=True)
    parser.add_argument("--gust-g1t", required=True)
    parser.add_argument("--output-root", required=True)
    parser.add_argument("--timeout", type=int, default=300)
    args = parser.parse_args()

    project_root = Path(args.project_root).expanduser().resolve()
    output_root = Path(args.output_root).expanduser().resolve()
    gust_g1t = Path(args.gust_g1t).expanduser().resolve()
    roots = {
        "blue_reflection_original": Path(args.original_root).expanduser().resolve(),
        "blue_reflection_quartet": Path(args.quartet_root).expanduser().resolve(),
    }
    if not project_root.is_dir():
        raise CarveError(f"Project root is missing: {project_root}")
    if not gust_g1t.is_file():
        raise CarveError(f"gust_g1t is missing: {gust_g1t}")
    for target, root in roots.items():
        if not root.is_dir():
            raise CarveError(f"Game root is missing for {target}: {root}")
    if output_root.exists():
        shutil.rmtree(output_root)
    output_root.mkdir(parents=True)

    report: dict[str, Any] = {
        "type": "br_hidden_title_g1t_carve_report",
        "format_version": 1,
        "tool_version": "translation-0.0.16",
        "status": "ok",
        "generated_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "project_root": "<PROJECT_ROOT>",
        "gust_g1t_sha256": sha256_file(gust_g1t),
        "profiles": PROFILE_RULES,
        "targets": {},
        "safety": {
            "game_files_modified": False,
            "containers_opened_read_only": True,
            "carved_blobs_written_only_to_report_directory": True,
        },
    }
    exact_total = 0
    for target, root in roots.items():
        target_report = scan_target(
            target, root, gust_g1t, output_root, args.timeout
        )
        report["targets"][target] = target_report
        exact_total += len(target_report["exact_profile_matches"])
    report["summary"] = {
        "targets": len(roots),
        "header_candidates": sum(
            item["candidate_count"] for item in report["targets"].values()
        ),
        "valid_g1t": sum(
            item["valid_g1t_count"] for item in report["targets"].values()
        ),
        "exact_profile_matches": exact_total,
    }
    if exact_total == 0:
        report["status"] = "no_exact_candidate"
    report_path = output_root / "BR_HIDDEN_TITLE_G1T_CARVE_REPORT.json"
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"Hidden title G1T carve complete: {report_path}")
    for target, data in report["targets"].items():
        print(
            f"  {target}: {data['candidate_count']} plausible headers, "
            f"{data['valid_g1t_count']} valid G1T, "
            f"{len(data['exact_profile_matches'])} exact geometry matches"
        )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except CarveError as exc:
        print(f"ERROR: {exc}", file=os.sys.stderr)
        raise SystemExit(1)
