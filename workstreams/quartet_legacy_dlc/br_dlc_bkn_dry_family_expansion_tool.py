#!/usr/bin/env python3
"""Collect metadata-only evidence for expanding dry BKN beyond PC00.

The tool reads existing quartet_legacy_dlc reports and report archives only. It
never reads or writes game installations, never copies raw assets, and never
builds or installs PAK files.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import re
import subprocess
import sys
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Iterable, Iterator

REPORT_BASENAMES = {
    "DLC_TECHNICAL_REGISTRY.tsv",
    "DLC_CANONICAL_CONTENT_CLOSURE.tsv",
    "DLC_EXACT_ROLE_CLOSURE.tsv",
    "DLC_NESTED_CONTAINER_INVENTORY.tsv",
    "DLC_NESTED_MEMBER_BINDINGS.tsv",
    "DLC_NESTED_ROLE_CLOSURE.tsv",
    "DLC_OWNER_EXTERNAL_DEPENDENCY_CLOSURE.tsv",
    "DLC_EXTERNAL_TEXTURE_BINDINGS.tsv",
    "DLC_SYSTEM_TABLE_OWNER_BINDINGS.tsv",
    "DLC_BKN_INDEX_BLOCK_AUDIT.tsv",
    "DLC_BKN_FAMILY_FALLBACK_MAP.tsv",
    "DLC_BR1_CANONICAL_SOURCE_REGISTRY.tsv",
    "DLC_BR1_OFFICIAL_OVERLAY_RESOLUTION.tsv",
    "DLC_BR1_DRY_BKN_CONTINUITY.tsv",
    "SUMMARY.json",
}

RAW_ASSET_SUFFIXES = {
    ".pak",
    ".g1t",
    ".g1m",
    ".dds",
    ".gz",
    ".bin",
    ".exe",
    ".dll",
    ".ebm",
    ".ebd",
    ".g1s",
}

CHAR_IDS = tuple(f"PC{i:02d}" for i in range(15))
BKN_RE = re.compile(r"(?i)\b(?:costume_)?pc(?:0[0-9]|1[0-4])(?:_dlc)?_bkn(?:_w)?\b")
CHAR_RE = re.compile(r"(?i)pc(?:0[0-9]|1[0-4])")
IDENTIFIER_RE = re.compile(
    r"(?i)(?:costume_pc(?:0[0-9]|1[0-4])_bkn|pc(?:0[0-9]|1[0-4])_dlc_bkn(?:_w)?)"
)
PATH_RE = re.compile(r"(?i)(?:[A-Za-z0-9_./-]+\.(?:elixir\.gz|g1t))")
STATUS_TOKENS = (
    "present_identical",
    "present_modified",
    "present_but_disabled",
    "missing_portable_from_br1",
    "missing_requires_conversion",
    "missing_requires_reconstruction",
    "unknown_dependency",
    "assets_identified",
    "not_mapped",
    "target_only_nested_member",
)


class EvidenceError(RuntimeError):
    pass


@dataclass(frozen=True)
class SourceDocument:
    source_kind: str
    source_ref: str
    member_name: str
    basename: str
    content: bytes

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.content).hexdigest()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def normalize_rel(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return path.name


def safe_report_member(name: str) -> bool:
    p = PurePosixPath(name)
    if p.name not in REPORT_BASENAMES:
        return False
    lower = p.name.lower()
    return not any(lower.endswith(suffix) for suffix in RAW_ASSET_SUFFIXES)


def list_tar_members(archive: Path) -> list[str]:
    proc = subprocess.run(
        ["tar", "--zstd", "-tf", str(archive)],
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    if proc.returncode != 0:
        raise EvidenceError(
            f"cannot list report archive {archive.name}: {proc.stderr.strip()}"
        )
    return [line.strip() for line in proc.stdout.splitlines() if line.strip()]


def read_tar_member(archive: Path, member: str) -> bytes:
    proc = subprocess.run(
        ["tar", "--zstd", "-xOf", str(archive), member],
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if proc.returncode != 0:
        raise EvidenceError(
            f"cannot read {member} from {archive.name}: "
            f"{proc.stderr.decode('utf-8', 'replace').strip()}"
        )
    return proc.stdout


def discover_documents(reports_root: Path, output_dir: Path) -> list[SourceDocument]:
    documents: list[SourceDocument] = []
    output_resolved = output_dir.resolve()

    for path in sorted(reports_root.rglob("*")):
        if not path.is_file():
            continue
        try:
            path.resolve().relative_to(output_resolved)
            continue
        except ValueError:
            pass

        if path.name in REPORT_BASENAMES:
            if path.stat().st_size > 64 * 1024 * 1024:
                raise EvidenceError(f"metadata report unexpectedly large: {path}")
            documents.append(
                SourceDocument(
                    source_kind="loose_report",
                    source_ref=normalize_rel(path, reports_root),
                    member_name=path.name,
                    basename=path.name,
                    content=path.read_bytes(),
                )
            )
            continue

        if path.name.endswith(".tar.zst"):
            for member in list_tar_members(path):
                if not safe_report_member(member):
                    continue
                content = read_tar_member(path, member)
                if len(content) > 64 * 1024 * 1024:
                    raise EvidenceError(
                        f"metadata member unexpectedly large: {path.name}:{member}"
                    )
                documents.append(
                    SourceDocument(
                        source_kind="report_archive",
                        source_ref=normalize_rel(path, reports_root),
                        member_name=member,
                        basename=PurePosixPath(member).name,
                        content=content,
                    )
                )

    # Identical report copies commonly exist in a loose directory and in its
    # deterministic evidence archive. Keep one content instance while retaining
    # a source index for provenance.
    unique: dict[tuple[str, str], SourceDocument] = {}
    for doc in documents:
        key = (doc.basename, doc.sha256)
        current = unique.get(key)
        if current is None or (doc.source_kind, doc.source_ref, doc.member_name) < (
            current.source_kind,
            current.source_ref,
            current.member_name,
        ):
            unique[key] = doc
    return sorted(
        unique.values(),
        key=lambda d: (d.basename, d.sha256, d.source_kind, d.source_ref, d.member_name),
    )


def text_from_bytes(data: bytes, label: str) -> str:
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise EvidenceError(f"metadata report is not UTF-8: {label}: {exc}") from exc


def variant_for_text(text: str) -> str:
    low = text.lower()
    if re.search(r"pc(?:0[0-9]|1[0-4])_dlc_bkn_w\b", low):
        return "wet"
    if "costume_pc" in low and "_bkn" in low and re.search(r"(?:_wet\b|\bwet\b)", low):
        return "wet"
    return "dry_or_family"


def char_ids_for_text(text: str) -> list[str]:
    return sorted({m.group(0).upper() for m in CHAR_RE.finditer(text)})


def identifiers_for_text(text: str) -> list[str]:
    return sorted({m.group(0) for m in IDENTIFIER_RE.finditer(text)}, key=str.lower)


def paths_for_text(text: str) -> list[str]:
    return sorted({m.group(0) for m in PATH_RE.finditer(text)}, key=str.lower)


def statuses_for_text(text: str) -> list[str]:
    low = text.lower()
    return [token for token in STATUS_TOKENS if token in low]


def iter_json_matches(value: Any, pointer: str = "") -> Iterator[tuple[str, str]]:
    if isinstance(value, dict):
        for key in sorted(value):
            token = str(key).replace("~", "~0").replace("/", "~1")
            yield from iter_json_matches(value[key], f"{pointer}/{token}")
    elif isinstance(value, list):
        for index, item in enumerate(value):
            yield from iter_json_matches(item, f"{pointer}/{index}")
    elif isinstance(value, (str, int, float, bool)) or value is None:
        text = "null" if value is None else str(value)
        if BKN_RE.search(text) or "bkn" in text.lower():
            yield pointer or "/", text


def collect_matches(documents: Iterable[SourceDocument]) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    source_rows: list[dict[str, str]] = []
    match_rows: list[dict[str, str]] = []

    for doc in documents:
        text = text_from_bytes(doc.content, f"{doc.source_ref}:{doc.member_name}")
        row_count = 0
        if doc.basename.endswith(".tsv"):
            reader = csv.reader(text.splitlines(), delimiter="\t")
            rows = list(reader)
            header = rows[0] if rows else []
            for line_number, row in enumerate(rows[1:], start=2):
                raw = "\t".join(row)
                if not (BKN_RE.search(raw) or "bkn" in raw.lower()):
                    continue
                row_count += 1
                chars = char_ids_for_text(raw)
                match_rows.append(
                    {
                        "source_report": doc.basename,
                        "source_sha256": doc.sha256,
                        "source_ref": doc.source_ref,
                        "location": str(line_number),
                        "record_kind": "tsv_row",
                        "character_ids": ",".join(chars),
                        "variant": variant_for_text(raw),
                        "identifiers": ",".join(identifiers_for_text(raw)),
                        "asset_paths": ",".join(paths_for_text(raw)),
                        "statuses": ",".join(statuses_for_text(raw)),
                        "header": "\t".join(header),
                        "record": raw,
                    }
                )
        elif doc.basename.endswith(".json"):
            try:
                parsed = json.loads(text)
            except json.JSONDecodeError as exc:
                raise EvidenceError(
                    f"invalid JSON report {doc.source_ref}:{doc.member_name}: {exc}"
                ) from exc
            for pointer, raw in iter_json_matches(parsed):
                row_count += 1
                chars = char_ids_for_text(raw)
                match_rows.append(
                    {
                        "source_report": doc.basename,
                        "source_sha256": doc.sha256,
                        "source_ref": doc.source_ref,
                        "location": pointer,
                        "record_kind": "json_value",
                        "character_ids": ",".join(chars),
                        "variant": variant_for_text(raw),
                        "identifiers": ",".join(identifiers_for_text(raw)),
                        "asset_paths": ",".join(paths_for_text(raw)),
                        "statuses": ",".join(statuses_for_text(raw)),
                        "header": "",
                        "record": raw,
                    }
                )

        source_rows.append(
            {
                "report": doc.basename,
                "sha256": doc.sha256,
                "bytes": str(len(doc.content)),
                "source_kind": doc.source_kind,
                "source_ref": doc.source_ref,
                "member_name": doc.member_name,
                "bkn_match_count": str(row_count),
            }
        )

    match_rows.sort(
        key=lambda r: (
            r["source_report"],
            r["source_sha256"],
            r["source_ref"],
            r["location"],
            r["record"],
        )
    )
    source_rows.sort(key=lambda r: (r["report"], r["sha256"], r["source_ref"]))
    return source_rows, match_rows


def make_character_summary(match_rows: list[dict[str, str]]) -> list[dict[str, Any]]:
    facts: dict[str, dict[str, Any]] = {
        char: {
            "character_id": char,
            "dry_identifier_observed": False,
            "wet_identifier_observed": False,
            "source_parent_paths": set(),
            "source_texture_paths": set(),
            "fallback_reference_observed": False,
            "canonical_source_reference_observed": False,
            "statuses": set(),
            "source_reports": set(),
            "evidence_rows": 0,
        }
        for char in CHAR_IDS
    }

    for row in match_rows:
        chars = [value for value in row["character_ids"].split(",") if value]
        low = row["record"].lower()
        paths = [value for value in row["asset_paths"].split(",") if value]
        statuses = [value for value in row["statuses"].split(",") if value]
        ids = [value.lower() for value in row["identifiers"].split(",") if value]
        for char in chars:
            fact = facts[char]
            fact["evidence_rows"] += 1
            fact["source_reports"].add(row["source_report"])
            fact["statuses"].update(statuses)
            if any(value.endswith("_bkn_w") for value in ids):
                fact["wet_identifier_observed"] = True
            if any(value.endswith("_bkn") and not value.endswith("_bkn_w") for value in ids):
                fact["dry_identifier_observed"] = True
            if "scl" in low and "bkn" in low:
                fact["fallback_reference_observed"] = True
            if any(token in low for token in ("canonical", "official", "no-underscore")):
                fact["canonical_source_reference_observed"] = True
            for asset_path in paths:
                path_low = asset_path.lower()
                if char.lower() not in path_low:
                    continue
                if path_low.endswith(".elixir.gz"):
                    fact["source_parent_paths"].add(asset_path)
                elif path_low.endswith(".g1t"):
                    fact["source_texture_paths"].add(asset_path)

    results: list[dict[str, Any]] = []
    for char in CHAR_IDS:
        fact = facts[char]
        if char == "PC00":
            state = "already_handled_pc00_reference"
            gaps: list[str] = []
        else:
            gaps = []
            if not fact["dry_identifier_observed"]:
                gaps.append("dry_identifier_not_observed")
            if not fact["source_parent_paths"]:
                gaps.append("dry_parent_binding_not_observed")
            if not fact["source_texture_paths"]:
                gaps.append("dry_texture_binding_not_observed")
            if not fact["fallback_reference_observed"]:
                gaps.append("quartet_fallback_mapping_not_observed")
            if not fact["canonical_source_reference_observed"]:
                gaps.append("canonical_source_reference_not_observed")
            state = (
                "metadata_ready_for_bounded_dry_probe"
                if not gaps
                else "requires_metadata_closure"
            )

        results.append(
            {
                "character_id": char,
                "candidate_state": state,
                "dry_identifier_observed": fact["dry_identifier_observed"],
                "wet_identifier_observed": fact["wet_identifier_observed"],
                "source_parent_count": len(fact["source_parent_paths"]),
                "source_parent_paths": sorted(fact["source_parent_paths"], key=str.lower),
                "source_texture_count": len(fact["source_texture_paths"]),
                "source_texture_paths": sorted(fact["source_texture_paths"], key=str.lower),
                "fallback_reference_observed": fact["fallback_reference_observed"],
                "canonical_source_reference_observed": fact[
                    "canonical_source_reference_observed"
                ],
                "statuses": sorted(fact["statuses"]),
                "source_reports": sorted(fact["source_reports"]),
                "evidence_rows": fact["evidence_rows"],
                "gaps": gaps,
                "build_authorized": False,
                "install_authorized": False,
                "runtime_validated": False,
            }
        )
    return results


def write_tsv(path: Path, fieldnames: list[str], rows: Iterable[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        for row in rows:
            normalized = {
                key: (
                    json.dumps(value, ensure_ascii=False, separators=(",", ":"))
                    if isinstance(value, (list, dict))
                    else str(value).lower()
                    if isinstance(value, bool)
                    else value
                )
                for key, value in row.items()
            }
            writer.writerow(normalized)


def write_manifest(output_dir: Path) -> None:
    entries = []
    for path in sorted(output_dir.iterdir(), key=lambda p: p.name):
        if not path.is_file() or path.name == "REPORT_MANIFEST.json":
            continue
        content = path.read_bytes()
        entries.append(
            {
                "path": path.name,
                "bytes": len(content),
                "sha256": sha256_bytes(content),
            }
        )
    manifest = {"type": "br_report_manifest", "format_version": 1, "files": entries}
    (output_dir / "REPORT_MANIFEST.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )


def collect(reports_root: Path, output_dir: Path) -> dict[str, Any]:
    if not reports_root.is_dir():
        raise EvidenceError(f"reports root does not exist: {reports_root}")
    output_dir.mkdir(parents=True, exist_ok=False)

    documents = discover_documents(reports_root, output_dir)
    if not documents:
        raise EvidenceError(
            "no prerequisite quartet_legacy_dlc metadata reports were found; "
            "do not regenerate game assets—restore or supply the existing report bundles"
        )

    source_rows, match_rows = collect_matches(documents)
    matched_reports = sorted(
        {row["report"] for row in source_rows if int(row["bkn_match_count"]) > 0}
    )
    required_signal_reports = {
        "DLC_TECHNICAL_REGISTRY.tsv",
        "DLC_NESTED_MEMBER_BINDINGS.tsv",
        "DLC_EXTERNAL_TEXTURE_BINDINGS.tsv",
        "DLC_BKN_FAMILY_FALLBACK_MAP.tsv",
    }
    missing_signal_reports = sorted(required_signal_reports - set(matched_reports))

    character_summary = make_character_summary(match_rows)
    ready_chars = [
        item["character_id"]
        for item in character_summary
        if item["candidate_state"] == "metadata_ready_for_bounded_dry_probe"
    ]

    write_tsv(
        output_dir / "DLC_BKN_DRY_FAMILY_REPORT_SOURCES.tsv",
        [
            "report",
            "sha256",
            "bytes",
            "source_kind",
            "source_ref",
            "member_name",
            "bkn_match_count",
        ],
        source_rows,
    )
    write_tsv(
        output_dir / "DLC_BKN_DRY_FAMILY_EVIDENCE_ROWS.tsv",
        [
            "source_report",
            "source_sha256",
            "source_ref",
            "location",
            "record_kind",
            "character_ids",
            "variant",
            "identifiers",
            "asset_paths",
            "statuses",
            "header",
            "record",
        ],
        match_rows,
    )
    write_tsv(
        output_dir / "DLC_BKN_DRY_FAMILY_CANDIDATES.tsv",
        [
            "character_id",
            "candidate_state",
            "dry_identifier_observed",
            "wet_identifier_observed",
            "source_parent_count",
            "source_parent_paths",
            "source_texture_count",
            "source_texture_paths",
            "fallback_reference_observed",
            "canonical_source_reference_observed",
            "statuses",
            "source_reports",
            "evidence_rows",
            "gaps",
            "build_authorized",
            "install_authorized",
            "runtime_validated",
        ],
        character_summary,
    )

    gaps = []
    for name in missing_signal_reports:
        gaps.append(
            {
                "scope": "report_prerequisite",
                "character_id": "",
                "gap": f"missing_or_no_bkn_rows:{name}",
                "blocking": "true",
            }
        )
    for item in character_summary:
        if item["character_id"] == "PC00":
            continue
        for gap in item["gaps"]:
            gaps.append(
                {
                    "scope": "character_candidate",
                    "character_id": item["character_id"],
                    "gap": gap,
                    "blocking": "true",
                }
            )
    write_tsv(
        output_dir / "DLC_BKN_DRY_FAMILY_GAPS.tsv",
        ["scope", "character_id", "gap", "blocking"],
        gaps,
    )

    summary = {
        "type": "br_quartet_legacy_dlc_bkn_dry_family_expansion_preflight",
        "format_version": 1,
        "status": "metadata_collected",
        "scope": "PC01-PC14 dry BKN expansion using existing metadata evidence",
        "source_document_count": len(documents),
        "matched_report_count": len(matched_reports),
        "matched_reports": matched_reports,
        "bkn_evidence_row_count": len(match_rows),
        "character_count": len(character_summary),
        "already_handled": ["PC00"],
        "metadata_ready_for_bounded_dry_probe": ready_chars,
        "requires_metadata_closure": [
            item["character_id"]
            for item in character_summary
            if item["candidate_state"] == "requires_metadata_closure"
        ],
        "missing_signal_reports": missing_signal_reports,
        "build_authorized": False,
        "profile_build_allowed": False,
        "prepare_allowed": False,
        "commit_allowed": False,
        "installation_allowed": False,
        "runtime_validation_allowed": False,
        "wet_bkn_included": False,
        "game_files_read": False,
        "game_files_written": False,
        "raw_assets_exported": False,
        "next_action": (
            "review candidate rows and select the smallest complete PC01-PC14 dry subset"
            if ready_chars
            else "close missing metadata bindings before any asset or PAK build"
        ),
    }
    (output_dir / "SUMMARY.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    write_manifest(output_dir)
    return summary


def validate(output_dir: Path) -> dict[str, Any]:
    required = {
        "DLC_BKN_DRY_FAMILY_REPORT_SOURCES.tsv",
        "DLC_BKN_DRY_FAMILY_EVIDENCE_ROWS.tsv",
        "DLC_BKN_DRY_FAMILY_CANDIDATES.tsv",
        "DLC_BKN_DRY_FAMILY_GAPS.tsv",
        "SUMMARY.json",
        "REPORT_MANIFEST.json",
    }
    missing = sorted(name for name in required if not (output_dir / name).is_file())
    if missing:
        raise EvidenceError(f"missing output files: {', '.join(missing)}")

    manifest = json.loads((output_dir / "REPORT_MANIFEST.json").read_text(encoding="utf-8"))
    listed = {entry["path"]: entry for entry in manifest.get("files", [])}
    for name in sorted(required - {"REPORT_MANIFEST.json"}):
        if name not in listed:
            raise EvidenceError(f"manifest does not list {name}")
        data = (output_dir / name).read_bytes()
        entry = listed[name]
        if entry.get("bytes") != len(data):
            raise EvidenceError(f"manifest byte mismatch for {name}")
        if entry.get("sha256") != sha256_bytes(data):
            raise EvidenceError(f"manifest hash mismatch for {name}")

    summary = json.loads((output_dir / "SUMMARY.json").read_text(encoding="utf-8"))
    safety_false = (
        "build_authorized",
        "profile_build_allowed",
        "prepare_allowed",
        "commit_allowed",
        "installation_allowed",
        "runtime_validation_allowed",
        "wet_bkn_included",
        "game_files_read",
        "game_files_written",
        "raw_assets_exported",
    )
    for key in safety_false:
        if summary.get(key) is not False:
            raise EvidenceError(f"unsafe or invalid summary field {key}={summary.get(key)!r}")
    if summary.get("status") != "metadata_collected":
        raise EvidenceError(f"unexpected summary status: {summary.get('status')}")
    if summary.get("already_handled") != ["PC00"]:
        raise EvidenceError("PC00 reference state is missing or changed")

    with (output_dir / "DLC_BKN_DRY_FAMILY_CANDIDATES.tsv").open(
        encoding="utf-8", newline=""
    ) as handle:
        rows = list(csv.DictReader(handle, delimiter="\t"))
    if [row["character_id"] for row in rows] != list(CHAR_IDS):
        raise EvidenceError("candidate table must contain PC00-PC14 exactly once in order")
    for row in rows:
        if row["build_authorized"] != "false":
            raise EvidenceError(f"build authorization unexpectedly enabled for {row['character_id']}")
        if row["install_authorized"] != "false":
            raise EvidenceError(
                f"install authorization unexpectedly enabled for {row['character_id']}"
            )
        if row["runtime_validated"] != "false":
            raise EvidenceError(
                f"runtime validation unexpectedly enabled for {row['character_id']}"
            )

    for path in output_dir.iterdir():
        if path.is_file() and any(path.name.lower().endswith(s) for s in RAW_ASSET_SUFFIXES):
            raise EvidenceError(f"raw asset present in evidence output: {path.name}")

    result = {
        "type": "br_quartet_legacy_dlc_bkn_dry_family_expansion_validation",
        "format_version": 1,
        "status": "pass",
        "candidate_rows": len(rows),
        "prepare_allowed": False,
        "commit_allowed": False,
        "installation_allowed": False,
        "runtime_validation_allowed": False,
    }
    (output_dir / "VALIDATION.json").write_text(
        json.dumps(result, indent=2) + "\n", encoding="utf-8"
    )
    write_manifest(output_dir)
    return result


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)

    collect_parser = sub.add_parser("collect")
    collect_parser.add_argument("--reports-root", type=Path, required=True)
    collect_parser.add_argument("--output-dir", type=Path, required=True)

    validate_parser = sub.add_parser("validate")
    validate_parser.add_argument("--output-dir", type=Path, required=True)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    try:
        if args.command == "collect":
            summary = collect(args.reports_root.resolve(), args.output_dir.resolve())
            print(json.dumps(summary, indent=2, ensure_ascii=False))
        else:
            result = validate(args.output_dir.resolve())
            print(json.dumps(result, indent=2))
    except (EvidenceError, OSError, subprocess.SubprocessError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
