#!/usr/bin/env python3
"""Collect path-level Quartet launcher/title candidates from all local PAK listings.

This is metadata-only discovery. It does not extract, carve, patch, or modify any
archive, and it intentionally does not repeat title-texture diagnostic steps
11-13.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import time
from pathlib import Path
from typing import Any

HEX = re.compile(r"^([0-9A-Fa-f]{9})\s+([0-9A-Fa-f]{8})\s+(.+?)\s*$")
KEYWORDS = {
    "launcher": 120,
    "game_select": 115,
    "gameselect": 115,
    "select_game": 115,
    "title": 100,
    "boot": 80,
    "top_menu": 75,
    "topmenu": 75,
    "main_menu": 70,
    "mainmenu": 70,
    "start_menu": 65,
    "startmenu": 65,
    "select": 45,
    "menu": 25,
}
EXTENSIONS = {".xml", ".g1t", ".kscl", ".ktsl2stbin", ".ebm", ".ebd", ".bin", ".dat"}


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def score_path(path: str) -> tuple[int, list[str]]:
    low = path.casefold().replace("\\", "/")
    score = 0
    reasons: list[str] = []
    for key, value in KEYWORDS.items():
        if key in low:
            score += value
            reasons.append(key)
    if "/ui/" in low or "/saves/" in low or "/layout/" in low:
        score += 20
        reasons.append("ui_or_layout")
    if "/b1/" in low:
        score -= 35
        reasons.append("embedded_b1_penalty")
    if Path(low).suffix in EXTENSIONS:
        score += 10
        reasons.append("relevant_extension")
    return score, reasons


def list_archive(gust_pak: Path, archive: Path, timeout: int) -> tuple[list[dict[str, Any]], list[str]]:
    proc = subprocess.run(
        [str(gust_pak), "-l", archive.name],
        cwd=archive.parent,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=timeout,
        check=False,
    )
    lines = proc.stdout.splitlines()
    if proc.returncode != 0:
        return [], lines[-20:]
    candidates: list[dict[str, Any]] = []
    for line in lines:
        match = HEX.match(line)
        if not match:
            continue
        path = match.group(3).rstrip("*").strip().replace("\\", "/")
        score, reasons = score_path(path)
        if score <= 0:
            continue
        candidates.append(
            {
                "offset_hex": match.group(1).lower(),
                "size_hex": match.group(2).lower(),
                "bytes": int(match.group(2), 16),
                "path": path,
                "score": score,
                "reasons": reasons,
            }
        )
    return candidates, lines[-20:]


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--project-root", required=True)
    p.add_argument("--quartet-root", required=True)
    p.add_argument("--gust-pak", required=True)
    p.add_argument("--timeout", type=int, default=1200)
    args = p.parse_args()

    project_root = Path(args.project_root).expanduser().resolve()
    quartet_root = Path(args.quartet_root).expanduser().resolve()
    gust_pak = Path(args.gust_pak).expanduser().resolve()
    if not quartet_root.is_dir():
        raise SystemExit(f"ERROR: Quartet root is missing: {quartet_root}")
    if not gust_pak.is_file() or not os.access(gust_pak, os.X_OK):
        raise SystemExit(f"ERROR: gust_pak is not executable: {gust_pak}")

    archives = sorted(
        (path for path in quartet_root.rglob("*") if path.is_file() and path.suffix.casefold() == ".pak"),
        key=lambda path: path.relative_to(quartet_root).as_posix().casefold(),
    )
    results: list[dict[str, Any]] = []
    all_candidates: list[dict[str, Any]] = []
    for archive in archives:
        relative = archive.relative_to(quartet_root).as_posix()
        candidates, tail = list_archive(gust_pak, archive, args.timeout)
        for item in candidates:
            item["archive"] = relative
            all_candidates.append(item)
        results.append(
            {
                "archive": relative,
                "sha256": sha256_file(archive),
                "bytes": archive.stat().st_size,
                "candidate_count": len(candidates),
                "listing_stdout_tail": tail,
            }
        )

    all_candidates.sort(key=lambda item: (-int(item["score"]), item["archive"], item["path"]))
    report_root = project_root / ".local/reports/translation/quartet_title_candidates"
    report_root.mkdir(parents=True, exist_ok=True)
    json_path = report_root / "BR_QUARTET_TITLE_CANDIDATE_REPORT.json"
    tsv_path = report_root / "candidates.tsv"
    report = {
        "type": "br_quartet_title_candidate_report",
        "format_version": 1,
        "status": "ok",
        "generated_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "project_root": "<PROJECT_ROOT>",
        "quartet_root": "<BR1_QUARTET_ROOT>",
        "strategy": "path_level_pak_listing_only_no_extraction_no_carving",
        "archives": results,
        "candidates": all_candidates,
        "summary": {
            "archives": len(archives),
            "candidates": len(all_candidates),
            "non_b1_candidates": sum("embedded_b1_penalty" not in item["reasons"] for item in all_candidates),
        },
        "safety": {
            "game_files_modified": False,
            "archives_opened_read_only": True,
            "repeats_steps_11_13": False,
        },
    }
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    with tsv_path.open("w", encoding="utf-8") as f:
        f.write("score\tarchive\toffset_hex\tsize_hex\tpath\treasons\n")
        for item in all_candidates:
            f.write(
                f"{item['score']}\t{item['archive']}\t{item['offset_hex']}\t{item['size_hex']}\t"
                f"{item['path']}\t{','.join(item['reasons'])}\n"
            )
    print(f"Quartet title candidate inventory completed: {len(all_candidates)} candidates")
    print(json_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
