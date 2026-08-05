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


class EvidenceError(RuntimeError):
    pass


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


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
        raise EvidenceError(f"Command timed out: {command[0]}") from exc
    if process.returncode != 0:
        raise EvidenceError(
            f"Command failed ({process.returncode}): {' '.join(command)}\n"
            f"STDOUT:\n{process.stdout}\nSTDERR:\n{process.stderr}"
        )
    return process


def safe_name(value: str) -> str:
    value = value.replace("\\", "/").strip("/")
    value = re.sub(r"[^A-Za-z0-9._-]+", "__", value)
    return value[:180] or "asset"


def normalized_path(value: str) -> str:
    return re.sub(r"/+", "/", value.replace("\\", "/")).strip("/").casefold()


def dds_metadata(path: Path) -> dict[str, Any]:
    data = path.read_bytes()[:160]
    result: dict[str, Any] = {
        "name": path.name,
        "bytes": path.stat().st_size,
        "sha256": sha256_file(path),
    }
    if len(data) < 128 or data[:4] != b"DDS ":
        result["valid_dds_header"] = False
        return result
    result.update({
        "valid_dds_header": struct.unpack_from("<I", data, 4)[0] == 124,
        "height": struct.unpack_from("<I", data, 12)[0],
        "width": struct.unpack_from("<I", data, 16)[0],
        "mipmaps": struct.unpack_from("<I", data, 28)[0],
        "fourcc": data[84:88].decode("ascii", errors="replace").rstrip("\\x00"),
    })
    return result


def copy_layout_evidence(project_root: Path, destination: Path) -> list[str]:
    patterns = (
        "titles/blue_reflection/workspace/original/archives/PACK02_1/saves_en/ui/gen_styles/uis_gen_a17_title.xml",
        "titles/blue_reflection/workspace/original/archives/PACK02_1/saves_en/ui/gen_styles/uis_gen_a18_title.xml",
        "titles/blue_reflection/workspace/original/archives/PACK02_1/saves_en/ui/a17_title/uil_title02.xml",
        "titles/blue_reflection/workspace/original/archives/PACK02_1/saves_en/ui/a18_title/uil_a18_title02.xml",
        "titles/blue_reflection/workspace/quartet/archives/PACK12/saves/b1/ui/gen_styles/uis_gen_a17_title.xml",
        "titles/blue_reflection/workspace/quartet/archives/PACK12/saves/b1/ui/gen_styles/uis_gen_a18_title.xml",
        "titles/blue_reflection/workspace/quartet/archives/PACK12/saves/b1/ui/a17_title/uil_title02.xml",
        "titles/blue_reflection/workspace/quartet/archives/PACK12/saves/b1/ui/a18_title/uil_a18_title02.xml",
        "titles/second_light/workspace/original/archives/PACK02/saves/ui_en/gen_styles/uis_gen_seed_title.xml",
        "titles/second_light/workspace/original/archives/PACK02/saves/ui_en/seed_title/uil_seed_title.xml",
    )
    copied: list[str] = []
    for relative in patterns:
        source = project_root / relative
        if not source.is_file():
            continue
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        copied.append(relative)
    return copied


TITLE_TEXTURE_RELATIVES: dict[str, tuple[str, ...]] = {
    "blue_reflection_original": (
        "data/x64/ui/a17_title.g1t",
        "data/x64/ui/a18_title.g1t",
    ),
    "blue_reflection_quartet": (
        "data/b1/x64/ui/a17_title.g1t",
        "data/b1/x64/ui/a18_title.g1t",
    ),
    "second_light_original": (
        "data/x64/res_en/ui/seed_title.g1t",
    ),
}


def expected_textures(target: str) -> tuple[str, ...]:
    try:
        return TITLE_TEXTURE_RELATIVES[target]
    except KeyError as exc:
        raise EvidenceError(f"Unsupported target: {target}") from exc


def expected_basenames(target: str) -> set[str]:
    return {Path(item).name.casefold() for item in expected_textures(target)}


def game_archives_for_scan(game_root: Path) -> list[Path]:
    archives = [
        path for path in game_root.rglob("*")
        if path.is_file() and path.suffix.casefold() == ".pak" and "__" not in path.name
    ]
    return sorted(archives, key=lambda p: p.relative_to(game_root).as_posix().casefold())


def loose_title_candidates(target: str, game_root: Path) -> list[Path]:
    basenames = expected_basenames(target)
    results: list[Path] = []
    for path in game_root.rglob("*"):
        if path.is_file() and path.name.casefold() in basenames:
            results.append(path)
    return sorted(results, key=lambda p: p.relative_to(game_root).as_posix().casefold())


PAK_LINE_RE = re.compile(
    r"^[0-9A-Fa-f]{9}\s+[0-9A-Fa-f]{8}\s+(?P<name>.*?)(?:[* ]?)$"
)


def list_pak_entries(
    gust_pak: Path,
    archive: Path,
    work_root: Path,
    timeout: int,
) -> tuple[list[str], str, str]:
    listing_dir = work_root / safe_name(archive.as_posix())
    listing_dir.mkdir(parents=True, exist_ok=False)
    link = listing_dir / archive.name
    os.symlink(archive, link)
    try:
        process = run([str(gust_pak), "-l", archive.name], listing_dir, timeout)
    finally:
        link.unlink(missing_ok=True)
    entries: list[str] = []
    for line in process.stdout.splitlines():
        match = PAK_LINE_RE.match(line)
        if not match:
            continue
        name = match.group("name")
        if name.endswith("*") or name.endswith(" "):
            name = name[:-1]
        name = name.strip()
        if name:
            entries.append(name)
    return entries, process.stdout, process.stderr


def classify_entries(target: str, entries: list[str]) -> dict[str, list[str]]:
    exact_paths = {normalized_path(item) for item in expected_textures(target)}
    basenames = expected_basenames(target)
    exact: list[str] = []
    basename: list[str] = []
    near: list[str] = []
    for entry in entries:
        normalized = normalized_path(entry)
        name = Path(normalized).name
        if normalized in exact_paths:
            exact.append(entry)
        elif name in basenames:
            basename.append(entry)
        elif normalized.endswith(".g1t") and (
            "title" in name
            or "a17" in name
            or "a18" in name
            or "seed" in name
        ):
            near.append(entry)
    return {
        "exact": sorted(set(exact), key=str.casefold),
        "basename": sorted(set(basename), key=str.casefold),
        "near": sorted(set(near), key=str.casefold),
    }


def extract_pak(
    gust_pak: Path,
    archive: Path,
    work_root: Path,
    timeout: int,
) -> tuple[Path, str, str]:
    archive_dir = work_root / (safe_name(archive.as_posix()) + "__extract")
    archive_dir.mkdir(parents=True, exist_ok=False)
    link = archive_dir / archive.name
    os.symlink(archive, link)
    try:
        process = run([str(gust_pak), archive.name], archive_dir, timeout)
    finally:
        link.unlink(missing_ok=True)
    return archive_dir, process.stdout, process.stderr


def locate_extracted_candidates(
    target: str,
    extracted_root: Path,
    selected_entries: list[str],
) -> list[tuple[Path, str]]:
    selected_normalized = {normalized_path(item) for item in selected_entries}
    basenames = expected_basenames(target)
    found: list[tuple[Path, str]] = []
    for path in extracted_root.rglob("*"):
        if not path.is_file() or path.suffix.casefold() != ".g1t":
            continue
        relative = path.relative_to(extracted_root).as_posix()
        normalized = normalized_path(relative)
        if normalized in selected_normalized or path.name.casefold() in basenames:
            found.append((path, relative))
    return sorted(found, key=lambda item: item[1].casefold())


def extract_g1t(
    gust_g1t: Path,
    source: Path,
    target_dir: Path,
    timeout: int,
) -> dict[str, Any]:
    target_dir.mkdir(parents=True, exist_ok=False)
    source_copy = target_dir / source.name
    shutil.copy2(source, source_copy)
    listing = run([str(gust_g1t), "-l", source_copy.name], target_dir, timeout)
    (target_dir / "gust_g1t_list.txt").write_text(
        listing.stdout + ("\nSTDERR:\n" + listing.stderr if listing.stderr else ""),
        encoding="utf-8",
    )
    extracted = run([str(gust_g1t), "-y", source_copy.name], target_dir, timeout)
    (target_dir / "gust_g1t_extract.txt").write_text(
        extracted.stdout + ("\nSTDERR:\n" + extracted.stderr if extracted.stderr else ""),
        encoding="utf-8",
    )
    json_files = sorted(target_dir.rglob("g1t.json"))
    if len(json_files) != 1:
        raise EvidenceError(
            f"Expected one g1t.json after extracting {source}, found {len(json_files)}"
        )
    extraction_root = json_files[0].parent
    dds_files = sorted(extraction_root.rglob("*.dds"))
    if not dds_files:
        raise EvidenceError(f"No DDS textures extracted from {source}")
    return {
        "source_name": source.name,
        "source_bytes": source.stat().st_size,
        "source_sha256": sha256_file(source),
        "list_output": "gust_g1t_list.txt",
        "extract_output": "gust_g1t_extract.txt",
        "g1t_json": json_files[0].relative_to(target_dir).as_posix(),
        "textures": [
            {**dds_metadata(path), "relative_path": path.relative_to(target_dir).as_posix()}
            for path in dds_files
        ],
    }


def likely_binary_containers(game_root: Path) -> list[Path]:
    suffixes = {
        ".pak", ".bin", ".dat", ".rdb", ".arc", ".cpk", ".pkg",
        ".exe", ".dll", ".idx", ".res", ".data",
    }
    results: list[Path] = []
    for path in game_root.rglob("*"):
        try:
            if not path.is_file() or path.stat().st_size == 0:
                continue
        except OSError:
            continue
        if path.suffix.casefold() in suffixes or (not path.suffix and path.stat().st_size >= 1024 * 1024):
            results.append(path)
    return sorted(results, key=lambda p: p.relative_to(game_root).as_posix().casefold())


def file_contains_patterns(path: Path, patterns: list[bytes]) -> list[str]:
    hits: list[str] = []
    try:
        with path.open("rb") as handle:
            if path.stat().st_size == 0:
                return hits
            with mmap.mmap(handle.fileno(), 0, access=mmap.ACCESS_READ) as mapped:
                for pattern in patterns:
                    if mapped.find(pattern) >= 0:
                        hits.append(pattern.decode("ascii", errors="replace"))
    except (OSError, ValueError):
        return []
    return hits


def binary_reference_scan(target: str, game_root: Path) -> dict[str, Any]:
    raw_patterns: set[str] = set()
    for expected in expected_textures(target):
        raw_patterns.add(expected)
        raw_patterns.add(expected.replace("/", "\\"))
        raw_patterns.add(Path(expected).name)
    variants: set[bytes] = set()
    for pattern in raw_patterns:
        variants.add(pattern.encode("ascii"))
        variants.add(pattern.upper().encode("ascii"))
    patterns = sorted(variants)

    scanned_files = 0
    scanned_bytes = 0
    hits: list[dict[str, Any]] = []
    for path in likely_binary_containers(game_root):
        try:
            size = path.stat().st_size
        except OSError:
            continue
        scanned_files += 1
        scanned_bytes += size
        found = file_contains_patterns(path, patterns)
        if found:
            hits.append({
                "path": path.relative_to(game_root).as_posix(),
                "bytes": size,
                "patterns": found,
            })
    return {
        "scanned_files": scanned_files,
        "scanned_bytes": scanned_bytes,
        "hits": hits,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Collect read-only title texture evidence for Blue Reflection targets."
    )
    parser.add_argument("--project-root", required=True)
    parser.add_argument("--original-root", required=True)
    parser.add_argument("--quartet-root", required=True)
    parser.add_argument("--second-light-root", required=True)
    parser.add_argument("--gust-pak", required=True)
    parser.add_argument("--gust-g1t", required=True)
    parser.add_argument("--output-root", required=True)
    parser.add_argument("--timeout", type=int, default=1800)
    args = parser.parse_args()

    project_root = Path(args.project_root).expanduser().resolve()
    output_root = Path(args.output_root).expanduser().resolve()
    gust_pak = Path(args.gust_pak).expanduser().resolve()
    gust_g1t = Path(args.gust_g1t).expanduser().resolve()
    game_roots = {
        "blue_reflection_original": Path(args.original_root).expanduser().resolve(),
        "blue_reflection_quartet": Path(args.quartet_root).expanduser().resolve(),
        "second_light_original": Path(args.second_light_root).expanduser().resolve(),
    }

    if output_root.exists():
        shutil.rmtree(output_root)
    output_root.mkdir(parents=True)
    assets_root = output_root / "assets"
    layouts_root = output_root / "layouts"
    work_root = Path(tempfile.mkdtemp(prefix="br-title-evidence-", dir=output_root.parent))

    report: dict[str, Any] = {
        "type": "br_title_texture_evidence",
        "format_version": 2,
        "tool_version": "translation-0.0.15",
        "status": "ok",
        "generated_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "project_root": "<PROJECT_ROOT>",
        "tools": {
            "gust_pak_sha256": sha256_file(gust_pak),
            "gust_g1t_sha256": sha256_file(gust_g1t),
        },
        "layouts": copy_layout_evidence(project_root, layouts_root),
        "targets": {},
        "safety": {
            "game_files_modified": False,
            "archives_opened_read_only": True,
            "work_done_in_temporary_directories": True,
        },
    }

    incomplete = False
    try:
        for target, game_root in game_roots.items():
            if not game_root.is_dir():
                raise EvidenceError(f"Game root is missing for {target}: {game_root}")
            target_out = assets_root / target
            target_out.mkdir(parents=True)
            target_report: dict[str, Any] = {
                "game_root": "<GAME_ROOT>",
                "expected_textures": list(expected_textures(target)),
                "loose_candidates": [],
                "archives_scanned": [],
                "archive_matches": [],
                "near_title_entries": [],
                "binary_reference_scan": {},
                "extracted_g1t": [],
            }

            sources: list[tuple[str, Path, str]] = []
            seen_hashes: set[str] = set()
            for loose in loose_title_candidates(target, game_root):
                digest = sha256_file(loose)
                relative = loose.relative_to(game_root).as_posix()
                target_report["loose_candidates"].append(relative)
                if digest not in seen_hashes:
                    seen_hashes.add(digest)
                    sources.append(("loose", loose, relative))

            archives = game_archives_for_scan(game_root)
            for archive in archives:
                archive_relative = archive.relative_to(game_root).as_posix()
                entries, stdout, stderr = list_pak_entries(
                    gust_pak,
                    archive,
                    work_root / target / "listings",
                    args.timeout,
                )
                classification = classify_entries(target, entries)
                target_report["archives_scanned"].append({
                    "path": archive_relative,
                    "entries": len(entries),
                    "exact": classification["exact"],
                    "basename": classification["basename"],
                    "near_count": len(classification["near"]),
                })
                if classification["near"]:
                    for entry in classification["near"]:
                        target_report["near_title_entries"].append(
                            {"archive": archive_relative, "entry": entry}
                        )
                selected = classification["exact"] + classification["basename"]
                if not selected:
                    continue

                target_report["archive_matches"].append({
                    "archive": archive_relative,
                    "selected_entries": selected,
                })
                extract_root, extract_stdout, extract_stderr = extract_pak(
                    gust_pak,
                    archive,
                    work_root / target / "extractions",
                    args.timeout,
                )
                log_name = safe_name(archive_relative)
                (target_out / f"{log_name}__gust_pak_list.txt").write_text(
                    stdout + ("\nSTDERR:\n" + stderr if stderr else ""),
                    encoding="utf-8",
                )
                (target_out / f"{log_name}__gust_pak_extract.txt").write_text(
                    extract_stdout + ("\nSTDERR:\n" + extract_stderr if extract_stderr else ""),
                    encoding="utf-8",
                )
                for path, actual_relative in locate_extracted_candidates(
                    target, extract_root, selected
                ):
                    digest = sha256_file(path)
                    if digest in seen_hashes:
                        continue
                    seen_hashes.add(digest)
                    sources.append((
                        "archive",
                        path,
                        f"{archive_relative}:{actual_relative}",
                    ))

            if not sources:
                target_report["binary_reference_scan"] = binary_reference_scan(
                    target, game_root
                )
                target_report["status"] = "not_located"
                incomplete = True
            else:
                target_report["status"] = "located"

            for index, (source_kind, source, logical_path) in enumerate(sources, start=1):
                evidence_dir = target_out / f"{index:02d}_{safe_name(logical_path)}"
                item = extract_g1t(gust_g1t, source, evidence_dir, args.timeout)
                item.update({
                    "source_kind": source_kind,
                    "logical_path": logical_path,
                    "evidence_directory": evidence_dir.relative_to(output_root).as_posix(),
                })
                target_report["extracted_g1t"].append(item)

            target_report["candidate_count"] = len(target_report["extracted_g1t"])
            target_report["dds_count"] = sum(
                len(item["textures"]) for item in target_report["extracted_g1t"]
            )
            report["targets"][target] = target_report
    finally:
        shutil.rmtree(work_root, ignore_errors=True)

    if incomplete:
        report["status"] = "partial"
    (output_root / "BR_TITLE_TEXTURE_EVIDENCE_REPORT.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"Collected title texture evidence: {output_root}")
    for target, data in report["targets"].items():
        print(
            f"  {target}: {data['status']}, "
            f"{data['candidate_count']} G1T, {data['dds_count']} DDS, "
            f"{len(data['near_title_entries'])} near title entries"
        )
    if incomplete:
        print("Some exact title textures were not located; diagnostic evidence was still packaged.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except EvidenceError as exc:
        print(f"ERROR: {exc}", file=os.sys.stderr)
        raise SystemExit(1)
