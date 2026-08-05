#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any

from title_texture_carver import (
    CarveError,
    create_previews,
    extract_candidate,
    find_candidate_offsets,
    parse_gust_listing,
    profile_scores,
    read_blob,
    run,
    safe_name,
    sha256_file,
)


class RecursiveScanError(RuntimeError):
    pass


FOCUSED_ARCHIVES: dict[str, tuple[str, ...]] = {
    "blue_reflection_original": (
        "DATA/PACK00_01.PAK",
        "DATA/PACK00_04_1.PAK",
    ),
    "blue_reflection_quartet": (
        "Data/PACK10_01.PAK",
        "Data/PACK10_04_01.PAK",
    ),
}


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def locate_casefold(root: Path, relative: str) -> Path | None:
    direct = root / relative
    if direct.is_file():
        return direct
    wanted = relative.replace("\\", "/").casefold()
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        try:
            candidate = path.relative_to(root).as_posix().casefold()
        except ValueError:
            continue
        if candidate == wanted:
            return path
    return None


def extract_pak(
    gust_pak: Path,
    archive: Path,
    destination: Path,
    timeout: int,
) -> tuple[str, str]:
    destination.mkdir(parents=True, exist_ok=False)
    link = destination / archive.name
    os.symlink(archive, link)
    try:
        process = run([str(gust_pak), archive.name], destination, timeout)
    finally:
        link.unlink(missing_ok=True)
    return process.stdout, process.stderr


def candidate_public(record: dict[str, Any]) -> dict[str, Any]:
    return {
        "container_chain": record["container_chain"],
        "source_file": record["source_file"],
        "source_file_bytes": record["source_file_bytes"],
        "offset_hex": record["offset_hex"],
        "blob_bytes": record["blob_bytes"],
        "blob_sha256": record["blob_sha256"],
        "textures": record["textures"],
        "profiles": record["profiles"],
        "evidence_directory": record.get("evidence_directory"),
        "previews": record.get("previews", []),
    }


class TargetScanner:
    def __init__(
        self,
        target: str,
        game_root: Path,
        gust_pak: Path,
        gust_g1t: Path,
        output_root: Path,
        scratch_root: Path,
        timeout: int,
        max_depth: int,
    ) -> None:
        self.target = target
        self.game_root = game_root
        self.gust_pak = gust_pak
        self.gust_g1t = gust_g1t
        self.output_root = output_root
        self.scratch_root = scratch_root
        self.timeout = timeout
        self.max_depth = max_depth
        self.seen_blob_hashes: set[str] = set()
        self.seen_container_hashes: set[str] = set()
        self.candidates: list[dict[str, Any]] = []
        self.errors: list[dict[str, str]] = []
        self.files_scanned = 0
        self.bytes_scanned = 0
        self.header_candidates = 0
        self.valid_g1t = 0
        self.nested_containers = 0

    def inspect_file(self, path: Path, logical_path: str, chain: list[str]) -> None:
        try:
            size = path.stat().st_size
        except OSError as exc:
            self.errors.append({"path": logical_path, "error": str(exc)})
            return
        if size < 28:
            return
        self.files_scanned += 1
        self.bytes_scanned += size
        try:
            hits = find_candidate_offsets(path)
        except (OSError, ValueError) as exc:
            self.errors.append({"path": logical_path, "error": str(exc)})
            return
        self.header_candidates += len(hits)
        for offset, header in hits:
            if header["texture_count"] not in {2, 3}:
                continue
            try:
                blob = read_blob(path, offset, header["total_size"])
            except CarveError as exc:
                self.errors.append({"path": logical_path, "error": str(exc)})
                continue
            blob_hash = sha256_bytes(blob)
            if blob_hash in self.seen_blob_hashes:
                continue
            self.seen_blob_hashes.add(blob_hash)

            blob_dir = self.scratch_root / "blobs"
            blob_dir.mkdir(parents=True, exist_ok=True)
            blob_path = blob_dir / f"{blob_hash}.g1t"
            blob_path.write_bytes(blob)
            try:
                listing = run(
                    [str(self.gust_g1t), "-l", blob_path.name],
                    blob_dir,
                    self.timeout,
                )
            except CarveError:
                blob_path.unlink(missing_ok=True)
                continue
            textures = parse_gust_listing(listing.stdout)
            if not textures:
                blob_path.unlink(missing_ok=True)
                continue
            self.valid_g1t += 1
            profiles = profile_scores(textures)
            record: dict[str, Any] = {
                "container_chain": list(chain),
                "source_file": logical_path,
                "source_file_bytes": size,
                "offset_hex": f"0x{offset:x}",
                "blob_bytes": len(blob),
                "blob_sha256": blob_hash,
                "textures": textures,
                "profiles": profiles,
            }

            exact_profiles = [
                name
                for name, data in profiles.items()
                if data.get("exact_profile_match")
            ]
            if exact_profiles:
                evidence_name = (
                    f"{len(self.candidates) + 1:03d}_"
                    f"{safe_name(Path(logical_path).name)}_"
                    f"{blob_hash[:12]}"
                )
                evidence_dir = self.output_root / "exact_candidates" / evidence_name
                try:
                    extraction = extract_candidate(
                        self.gust_g1t,
                        blob_path,
                        evidence_dir,
                        self.timeout,
                    )
                    previews = create_previews(evidence_dir, textures, profiles)
                    record["evidence_directory"] = evidence_dir.relative_to(
                        self.output_root
                    ).as_posix()
                    record["extraction"] = extraction
                    record["previews"] = previews
                except (CarveError, OSError) as exc:
                    self.errors.append({
                        "path": logical_path,
                        "error": f"exact candidate extraction failed: {exc}",
                    })
            self.candidates.append(record)
            blob_path.unlink(missing_ok=True)

    def process_container(
        self,
        archive: Path,
        chain: list[str],
        depth: int,
    ) -> dict[str, Any]:
        try:
            archive_hash = sha256_file(archive)
        except OSError as exc:
            return {"chain": chain, "status": "error", "error": str(exc)}
        if archive_hash in self.seen_container_hashes:
            return {"chain": chain, "status": "duplicate", "sha256": archive_hash}
        self.seen_container_hashes.add(archive_hash)

        container_dir = self.scratch_root / (
            f"container_{len(self.seen_container_hashes):04d}_"
            f"{safe_name(archive.name)}"
        )
        before_files = self.files_scanned
        before_bytes = self.bytes_scanned
        before_headers = self.header_candidates
        before_valid = self.valid_g1t
        record: dict[str, Any] = {
            "chain": list(chain),
            "depth": depth,
            "bytes": archive.stat().st_size,
            "sha256": archive_hash,
            "status": "ok",
            "nested": [],
        }
        try:
            stdout, stderr = extract_pak(
                self.gust_pak, archive, container_dir, self.timeout
            )
            record["extract_stdout_tail"] = stdout.splitlines()[-10:]
            record["extract_stderr_tail"] = stderr.splitlines()[-10:]
            files = sorted(
                (path for path in container_dir.rglob("*") if path.is_file()),
                key=lambda path: path.relative_to(container_dir).as_posix().casefold(),
            )
            nested: list[tuple[Path, str]] = []
            for path in files:
                relative = path.relative_to(container_dir).as_posix()
                logical = "!".join(chain + [relative])
                self.inspect_file(path, logical, chain)
                if path.suffix.casefold() == ".pak" and depth < self.max_depth:
                    nested.append((path, relative))
            for nested_path, relative in nested:
                self.nested_containers += 1
                nested_record = self.process_container(
                    nested_path,
                    chain + [relative],
                    depth + 1,
                )
                record["nested"].append(nested_record)
        except (CarveError, OSError, RecursiveScanError) as exc:
            record["status"] = "error"
            record["error"] = str(exc)
            self.errors.append({"path": "!".join(chain), "error": str(exc)})
        finally:
            shutil.rmtree(container_dir, ignore_errors=True)

        record.update({
            "files_scanned": self.files_scanned - before_files,
            "bytes_scanned": self.bytes_scanned - before_bytes,
            "header_candidates": self.header_candidates - before_headers,
            "valid_g1t": self.valid_g1t - before_valid,
        })
        return record

    def run(self) -> dict[str, Any]:
        archives: list[dict[str, Any]] = []
        for relative in FOCUSED_ARCHIVES[self.target]:
            archive = locate_casefold(self.game_root, relative)
            if archive is None:
                archives.append({
                    "path": relative,
                    "status": "missing",
                })
                self.errors.append({"path": relative, "error": "archive missing"})
                continue
            actual_relative = archive.relative_to(self.game_root).as_posix()
            archives.append(
                self.process_container(archive, [actual_relative], 0)
            )

        exact_matches: list[dict[str, Any]] = []
        for record in self.candidates:
            for profile, data in record["profiles"].items():
                if data.get("exact_profile_match"):
                    exact_matches.append({
                        "profile": profile,
                        **candidate_public(record),
                    })

        top_candidates: dict[str, list[dict[str, Any]]] = {}
        for profile in ("a17_title", "a18_title"):
            ranked = sorted(
                self.candidates,
                key=lambda item: (
                    float(item["profiles"][profile]["normalized_score"]),
                    item["blob_bytes"],
                ),
                reverse=True,
            )[:10]
            top_candidates[profile] = [candidate_public(item) for item in ranked]

        found_profiles = {item["profile"] for item in exact_matches}
        if found_profiles == {"a17_title", "a18_title"}:
            status = "all_profiles_located"
        elif found_profiles:
            status = "partial_profiles_located"
        else:
            status = "no_exact_candidate"

        return {
            "game_root": "<GAME_ROOT>",
            "focused_archives": list(FOCUSED_ARCHIVES[self.target]),
            "archives": archives,
            "files_scanned": self.files_scanned,
            "bytes_scanned": self.bytes_scanned,
            "nested_containers": self.nested_containers,
            "header_candidates": self.header_candidates,
            "valid_g1t": self.valid_g1t,
            "candidate_count": len(self.candidates),
            "exact_profile_matches": exact_matches,
            "top_candidates": top_candidates,
            "errors": self.errors,
            "status": status,
        }


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Extract focused BR1/Quartet UI archives read-only, recursively "
            "open nested PAKs, and scan every decompressed file for hidden G1T blobs."
        )
    )
    parser.add_argument("--project-root", required=True)
    parser.add_argument("--original-root", required=True)
    parser.add_argument("--quartet-root", required=True)
    parser.add_argument("--gust-pak", required=True)
    parser.add_argument("--gust-g1t", required=True)
    parser.add_argument("--output-root", required=True)
    parser.add_argument("--timeout", type=int, default=1800)
    parser.add_argument("--max-depth", type=int, default=2)
    args = parser.parse_args()

    project_root = Path(args.project_root).expanduser().resolve()
    output_root = Path(args.output_root).expanduser().resolve()
    gust_pak = Path(args.gust_pak).expanduser().resolve()
    gust_g1t = Path(args.gust_g1t).expanduser().resolve()
    roots = {
        "blue_reflection_original": Path(args.original_root).expanduser().resolve(),
        "blue_reflection_quartet": Path(args.quartet_root).expanduser().resolve(),
    }

    for path in (gust_pak, gust_g1t):
        if not path.is_file():
            raise RecursiveScanError(f"Required tool is missing: {path}")
    for target, root in roots.items():
        if not root.is_dir():
            raise RecursiveScanError(f"Game root is missing for {target}: {root}")
    if args.max_depth < 0 or args.max_depth > 4:
        raise RecursiveScanError("max-depth must be between 0 and 4")

    if output_root.exists():
        shutil.rmtree(output_root)
    output_root.mkdir(parents=True)
    scratch_parent = Path(
        tempfile.mkdtemp(prefix="br-recursive-title-scan-", dir=output_root.parent)
    )

    report: dict[str, Any] = {
        "type": "br_recursive_title_g1t_scan_report",
        "format_version": 1,
        "tool_version": "translation-0.0.17",
        "status": "ok",
        "generated_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "project_root": "<PROJECT_ROOT>",
        "tools": {
            "gust_pak_sha256": sha256_file(gust_pak),
            "gust_g1t_sha256": sha256_file(gust_g1t),
        },
        "strategy": {
            "focused_top_level_archives": FOCUSED_ARCHIVES,
            "pak_extraction": "temporary full extraction, one container at a time",
            "nested_pak_depth": args.max_depth,
            "file_scan": "every decompressed file, mmap GT1G/G1TG search",
            "candidate_boundary": "G1T total_size header field",
        },
        "targets": {},
        "safety": {
            "game_files_modified": False,
            "source_archives_opened_read_only": True,
            "temporary_extractions_removed": True,
            "outputs_limited_to_report_directory": True,
        },
    }

    try:
        for target, root in roots.items():
            target_output = output_root / "assets" / target
            target_output.mkdir(parents=True, exist_ok=True)
            target_scratch = scratch_parent / target
            target_scratch.mkdir(parents=True, exist_ok=True)
            scanner = TargetScanner(
                target,
                root,
                gust_pak,
                gust_g1t,
                target_output,
                target_scratch,
                args.timeout,
                args.max_depth,
            )
            report["targets"][target] = scanner.run()

        statuses = {
            value["status"] for value in report["targets"].values()
        }
        if statuses == {"all_profiles_located"}:
            report["status"] = "all_profiles_located"
        elif any(status != "no_exact_candidate" for status in statuses):
            report["status"] = "partial"
        else:
            report["status"] = "no_exact_candidate"
        report["summary"] = {
            "targets": len(report["targets"]),
            "files_scanned": sum(
                item["files_scanned"] for item in report["targets"].values()
            ),
            "bytes_scanned": sum(
                item["bytes_scanned"] for item in report["targets"].values()
            ),
            "nested_containers": sum(
                item["nested_containers"] for item in report["targets"].values()
            ),
            "header_candidates": sum(
                item["header_candidates"] for item in report["targets"].values()
            ),
            "valid_g1t": sum(
                item["valid_g1t"] for item in report["targets"].values()
            ),
            "exact_profile_matches": sum(
                len(item["exact_profile_matches"])
                for item in report["targets"].values()
            ),
        }
    finally:
        shutil.rmtree(scratch_parent, ignore_errors=True)
        report_path = output_root / "BR_RECURSIVE_TITLE_G1T_SCAN_REPORT.json"
        report_path.write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    print(f"Recursive title scan status: {report['status']}")
    print(f"Files scanned: {report['summary']['files_scanned']}")
    print(f"Valid G1T candidates: {report['summary']['valid_g1t']}")
    print(f"Exact profile matches: {report['summary']['exact_profile_matches']}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (RecursiveScanError, CarveError, KeyboardInterrupt) as exc:
        if isinstance(exc, KeyboardInterrupt):
            print("ERROR: scan interrupted", file=os.sys.stderr)
        else:
            print(f"ERROR: {exc}", file=os.sys.stderr)
        raise SystemExit(1)
