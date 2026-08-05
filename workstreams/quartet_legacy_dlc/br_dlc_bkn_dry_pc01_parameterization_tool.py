#!/usr/bin/env python3
"""Select PC01 and audit PC00-specific code before a bounded dry probe.

Inputs are restricted to validated stage-83 metadata and repository source text
under workstreams/quartet_legacy_dlc. The tool never reads a game installation,
raw assets, candidate PAKs, or any path outside the project workstream and local
report directory.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import shutil
import subprocess
from pathlib import Path, PurePosixPath
from typing import Any

EXPECTED_STAGE_FILES = {
    "DLC_BKN_DRY_FAMILY_CANDIDATES.tsv",
    "DLC_BKN_DRY_FAMILY_EVIDENCE_ROWS.tsv",
    "DLC_BKN_DRY_FAMILY_GAPS.tsv",
    "DLC_BKN_DRY_FAMILY_REPORT_SOURCES.tsv",
    "SUMMARY.json",
    "VALIDATION.json",
    "REPORT_MANIFEST.json",
}

SOURCE_SUFFIXES = {".py", ".sh"}
SOURCE_EXCLUDES = {
    "DLC_BKN_DRY_FAMILY_EXPANSION_ACCEPTANCE.json",
    "DLC_BKN_DRY_PC01_PARAMETERIZATION_SCOPE.json",
    "br_dlc_bkn_dry_pc01_parameterization_tool.py",
    "84_run_bkn_dry_pc01_parameterization_evidence.sh",
}
TOKENS = (
    "costume_pc00_bkn",
    "PC00_DLC_BKN",
    "pc00_dlc_bkn",
    "PC00/PC00_DLC_Bkn",
    "costume_pc00_twl",
    "PC00_DLC_TWL",
    "pc00_dlc_twl",
)
MACHINE_PATH_PATTERNS = (
    re.compile(r"/home/[^/\s]+/"),
    re.compile(r"(?i)[A-Z]:[\\/]Users[\\/][^\\/\s]+[\\/]"),
)


class AuditError(RuntimeError):
    pass


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def json_dump(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def write_tsv(path: Path, fields: list[str], rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, delimiter="\t", lineterminator="\n", fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fields})


def ensure_safe_relative(path: str) -> str:
    p = PurePosixPath(path)
    if p.is_absolute() or ".." in p.parts or not p.parts:
        raise AuditError(f"unsafe report path: {path!r}")
    return p.as_posix()


def read_archive_member(archive: Path, member: str) -> bytes:
    proc = subprocess.run(
        ["tar", "--zstd", "-xOf", str(archive), member],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if proc.returncode != 0:
        raise AuditError(
            f"cannot read {member} from {archive.name}: "
            f"{proc.stderr.decode('utf-8', 'replace').strip()}"
        )
    return proc.stdout


def list_archive(archive: Path) -> list[str]:
    proc = subprocess.run(
        ["tar", "--zstd", "-tf", str(archive)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        raise AuditError(f"cannot list {archive.name}: {proc.stderr.strip()}")
    return [line.strip().rstrip("/") for line in proc.stdout.splitlines() if line.strip()]


def load_stage83_archive(archive: Path) -> dict[str, bytes]:
    names = list_archive(archive)
    roots = {PurePosixPath(name).parts[0] for name in names if PurePosixPath(name).parts}
    if len(roots) != 1:
        raise AuditError("stage-83 archive must contain exactly one root directory")
    root = next(iter(roots))
    members = {
        PurePosixPath(name).name: name
        for name in names
        if len(PurePosixPath(name).parts) == 2 and PurePosixPath(name).parts[0] == root
    }
    missing = EXPECTED_STAGE_FILES - members.keys()
    if missing:
        raise AuditError(f"stage-83 archive is missing: {', '.join(sorted(missing))}")
    data = {name: read_archive_member(archive, members[name]) for name in EXPECTED_STAGE_FILES}
    validate_stage83_data(data)
    return data


def load_stage83_directory(directory: Path) -> dict[str, bytes]:
    data: dict[str, bytes] = {}
    for name in EXPECTED_STAGE_FILES:
        path = directory / name
        if not path.is_file():
            raise AuditError(f"stage-83 directory is missing: {name}")
        data[name] = path.read_bytes()
    validate_stage83_data(data)
    return data


def validate_stage83_data(data: dict[str, bytes]) -> None:
    try:
        manifest = json.loads(data["REPORT_MANIFEST.json"])
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise AuditError(f"invalid stage-83 report manifest: {exc}") from exc
    listed: dict[str, dict[str, Any]] = {}
    for entry in manifest.get("files", []):
        rel = ensure_safe_relative(str(entry.get("path", "")))
        if "/" in rel:
            raise AuditError(f"nested stage-83 report path is not allowed: {rel}")
        listed[rel] = entry
    expected_manifest_files = EXPECTED_STAGE_FILES - {"REPORT_MANIFEST.json"}
    if set(listed) != expected_manifest_files:
        raise AuditError("stage-83 report manifest file set is not exact")
    for name, entry in listed.items():
        content = data[name]
        if int(entry.get("bytes", -1)) != len(content):
            raise AuditError(f"stage-83 byte count mismatch: {name}")
        if str(entry.get("sha256", "")) != sha256_bytes(content):
            raise AuditError(f"stage-83 hash mismatch: {name}")
    summary = json.loads(data["SUMMARY.json"])
    validation = json.loads(data["VALIDATION.json"])
    if summary.get("status") != "metadata_collected":
        raise AuditError("stage-83 summary status is not metadata_collected")
    if validation.get("status") != "pass":
        raise AuditError("stage-83 validation did not pass")
    for key in ("build_authorized", "prepare_allowed", "commit_allowed", "installation_allowed", "runtime_validation_allowed", "wet_bkn_included"):
        if bool(summary.get(key)):
            raise AuditError(f"unsafe stage-83 authorization: {key}")


def parse_tsv(data: bytes, label: str) -> list[dict[str, str]]:
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise AuditError(f"{label} is not UTF-8: {exc}") from exc
    return list(csv.DictReader(text.splitlines(), delimiter="\t"))


def parse_json_array(text: str, label: str) -> list[Any]:
    try:
        value = json.loads(text)
    except json.JSONDecodeError as exc:
        raise AuditError(f"invalid JSON array in {label}: {exc}") from exc
    if not isinstance(value, list):
        raise AuditError(f"expected JSON array in {label}")
    return value


def candidate_rank(row: dict[str, str]) -> tuple[int, int, int]:
    char_id = row["character_id"].upper()
    return (
        int(row["source_parent_count"]) + int(row["source_texture_count"]),
        int(row["evidence_rows"]),
        int(char_id[2:]),
    )


def select_candidate(rows: list[dict[str, str]]) -> tuple[dict[str, str], list[dict[str, str]]]:
    ready = [
        row for row in rows
        if row.get("character_id", "").upper() != "PC00"
        and row.get("candidate_state") == "metadata_ready_for_bounded_dry_probe"
        and parse_json_array(row.get("gaps", "[]"), f"{row.get('character_id')}.gaps") == []
        and row.get("build_authorized") == "false"
        and row.get("install_authorized") == "false"
        and row.get("runtime_validated") == "false"
    ]
    if not ready:
        raise AuditError("no fail-closed dry BKN candidate is ready")
    ranked = sorted(ready, key=candidate_rank)
    selected = ranked[0]
    if selected.get("character_id") != "PC01":
        raise AuditError(f"deterministic selection changed unexpectedly: {selected.get('character_id')}")
    return selected, ranked


def machine_path_hits(text: str) -> list[str]:
    hits: list[str] = []
    for pattern in MACHINE_PATH_PATTERNS:
        hits.extend(match.group(0) for match in pattern.finditer(text))
    return sorted(set(hits))


def scan_workstream(workstream_root: Path, output_dir: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    points: list[dict[str, Any]] = []
    snapshots: list[dict[str, Any]] = []
    snapshot_root = output_dir / "SOURCE_SNAPSHOTS"
    output_resolved = output_dir.resolve()

    for path in sorted(workstream_root.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in SOURCE_SUFFIXES:
            continue
        if path.name in SOURCE_EXCLUDES or "tests" in path.relative_to(workstream_root).parts:
            continue
        try:
            path.resolve().relative_to(output_resolved)
            continue
        except ValueError:
            pass
        if path.stat().st_size > 4 * 1024 * 1024:
            raise AuditError(f"repository source file unexpectedly large: {path.name}")
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError as exc:
            raise AuditError(f"repository source is not UTF-8: {path}: {exc}") from exc
        local_hits = machine_path_hits(text)
        if local_hits:
            raise AuditError(f"machine-specific path found in production source: {path.name}")
        rel = path.relative_to(workstream_root).as_posix()
        file_points: list[dict[str, Any]] = []
        for number, line in enumerate(text.splitlines(), 1):
            for token in TOKENS:
                if token.lower() in line.lower():
                    snippet = line.strip()
                    if len(snippet) > 320:
                        snippet = snippet[:317] + "..."
                    file_points.append({
                        "path": rel,
                        "line": number,
                        "token": token,
                        "line_sha256": sha256_bytes(line.encode("utf-8")),
                        "snippet": snippet,
                    })
        if not file_points:
            continue
        points.extend(file_points)
        content = path.read_bytes()
        destination = snapshot_root / rel
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(content)
        snapshots.append({
            "path": rel,
            "snapshot_path": f"SOURCE_SNAPSHOTS/{rel}",
            "bytes": len(content),
            "sha256": sha256_bytes(content),
            "parameterization_points": len(file_points),
        })
    if not points:
        raise AuditError("no PC00 BKN parameterization points were found in repository source")
    return points, snapshots


def build_manifest(output_dir: Path) -> None:
    files: list[dict[str, Any]] = []
    for path in sorted(output_dir.rglob("*")):
        if not path.is_file() or path.name == "REPORT_MANIFEST.json":
            continue
        rel = path.relative_to(output_dir).as_posix()
        ensure_safe_relative(rel)
        content = path.read_bytes()
        files.append({"path": rel, "bytes": len(content), "sha256": sha256_bytes(content)})
    json_dump(output_dir / "REPORT_MANIFEST.json", {
        "type": "br_report_manifest",
        "format_version": 1,
        "files": files,
    })


def collect(workstream_root: Path, output_dir: Path, *, stage83_archive: Path | None = None, stage83_dir: Path | None = None) -> dict[str, Any]:
    if (stage83_archive is None) == (stage83_dir is None):
        raise AuditError("provide exactly one of stage83_archive or stage83_dir")
    output_dir.mkdir(parents=True, exist_ok=False)
    data = load_stage83_archive(stage83_archive) if stage83_archive else load_stage83_directory(stage83_dir)  # type: ignore[arg-type]
    candidates = parse_tsv(data["DLC_BKN_DRY_FAMILY_CANDIDATES.tsv"], "candidate table")
    evidence_rows = parse_tsv(data["DLC_BKN_DRY_FAMILY_EVIDENCE_ROWS.tsv"], "evidence rows")
    selected, ranked = select_candidate(candidates)

    selection_rows: list[dict[str, Any]] = []
    for index, row in enumerate(ranked, 1):
        selection_rows.append({
            "rank": index,
            "character_id": row["character_id"],
            "selected": str(row is selected).lower(),
            "source_parent_count": row["source_parent_count"],
            "source_texture_count": row["source_texture_count"],
            "evidence_rows": row["evidence_rows"],
            "rank_key": json.dumps(candidate_rank(row), separators=(",", ":")),
            "candidate_state": row["candidate_state"],
        })
    write_tsv(output_dir / "DLC_BKN_DRY_PROBE_SELECTION.tsv", list(selection_rows[0]), selection_rows)

    parent_paths = parse_json_array(selected["source_parent_paths"], "PC01 source_parent_paths")
    texture_paths = parse_json_array(selected["source_texture_paths"], "PC01 source_texture_paths")
    identifier_rows: list[dict[str, Any]] = []
    for path in parent_paths + texture_paths:
        low = str(path).lower()
        variant = "wet_excluded" if "_bkn_w" in low else "dry_selected"
        role = "parent_elixir" if low.endswith(".elixir.gz") else "external_texture"
        identifier_rows.append({
            "character_id": "PC01",
            "variant": variant,
            "role": role,
            "source_path": path,
            "target_member_path": str(path).replace("data/x64/", "data/b1/x64/"),
            "included_in_next_build": "false",
        })
    write_tsv(output_dir / "DLC_BKN_DRY_PC01_IDENTIFIERS.tsv", list(identifier_rows[0]), identifier_rows)

    pc01_rows = [
        row for row in evidence_rows
        if "PC01" in {token.strip().upper() for token in row.get("character_ids", "").split(",") if token.strip()}
    ]
    write_tsv(
        output_dir / "DLC_BKN_DRY_PC01_EVIDENCE_ROWS.tsv",
        list(pc01_rows[0]) if pc01_rows else ["character_id"],
        pc01_rows,
    )

    points, snapshots = scan_workstream(workstream_root, output_dir)
    write_tsv(
        output_dir / "DLC_BKN_DRY_PC01_PARAMETERIZATION_POINTS.tsv",
        ["path", "line", "token", "line_sha256", "snippet"],
        points,
    )
    write_tsv(
        output_dir / "DLC_BKN_DRY_PC01_SOURCE_SNAPSHOTS.tsv",
        ["path", "snapshot_path", "bytes", "sha256", "parameterization_points"],
        snapshots,
    )
    write_tsv(
        output_dir / "DLC_BKN_DRY_PC01_PROBE_GAPS.tsv",
        ["scope", "gap", "blocking"],
        [],
    )

    plan = {
        "type": "br_quartet_legacy_dlc_bkn_dry_pc01_parameterization_plan",
        "format_version": 1,
        "selected_character_id": "PC01",
        "reference_character_id": "PC00",
        "selection_rank_key": list(candidate_rank(selected)),
        "dry_source_members": [row["source_path"] for row in identifier_rows if row["variant"] == "dry_selected"],
        "dry_target_members": [row["target_member_path"] for row in identifier_rows if row["variant"] == "dry_selected"],
        "wet_members_observed_but_excluded": [row["source_path"] for row in identifier_rows if row["variant"] == "wet_excluded"],
        "source_snapshot_count": len(snapshots),
        "parameterization_point_count": len(points),
        "next_action": "generalize the exact PC00 dry transfer, PAK insertion, charabase patch and PACK12 repack code paths for a checksum-gated PC01 local probe",
        "build_authorized": False,
        "prepare_allowed": False,
        "commit_allowed": False,
        "installation_allowed": False,
        "profile_registration_allowed": False,
        "runtime_validation_allowed": False,
        "wet_bkn_included": False,
    }
    json_dump(output_dir / "DLC_BKN_DRY_PC01_PARAMETERIZATION_PLAN.json", plan)
    summary = {
        "type": "br_quartet_legacy_dlc_bkn_dry_pc01_parameterization_summary",
        "format_version": 1,
        "status": "pc01_selected_parameterization_points_collected",
        "selected_character_id": "PC01",
        "ready_candidate_count": len(ranked),
        "pc01_evidence_row_count": len(pc01_rows),
        "source_snapshot_count": len(snapshots),
        "parameterization_point_count": len(points),
        "build_authorized": False,
        "prepare_allowed": False,
        "commit_allowed": False,
        "installation_allowed": False,
        "runtime_validation_allowed": False,
        "wet_bkn_included": False,
        "game_files_read": False,
        "game_files_written": False,
        "raw_assets_exported": False,
        "next_action": plan["next_action"],
    }
    json_dump(output_dir / "SUMMARY.json", summary)
    json_dump(output_dir / "VALIDATION.json", {
        "type": "br_quartet_legacy_dlc_bkn_dry_pc01_parameterization_validation",
        "format_version": 1,
        "status": "pass",
        "selected_character_id": "PC01",
        "source_snapshots": len(snapshots),
        "parameterization_points": len(points),
        "prepare_allowed": False,
        "commit_allowed": False,
        "installation_allowed": False,
        "runtime_validation_allowed": False,
    })
    build_manifest(output_dir)
    return summary


def validate(output_dir: Path) -> None:
    manifest_path = output_dir / "REPORT_MANIFEST.json"
    if not manifest_path.is_file():
        raise AuditError("missing report manifest")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    listed = {entry["path"]: entry for entry in manifest.get("files", [])}
    actual = {
        path.relative_to(output_dir).as_posix(): path
        for path in output_dir.rglob("*")
        if path.is_file() and path.name != "REPORT_MANIFEST.json"
    }
    if set(listed) != set(actual):
        raise AuditError("output report manifest file set mismatch")
    for rel, path in actual.items():
        entry = listed[rel]
        content = path.read_bytes()
        if entry["bytes"] != len(content) or entry["sha256"] != sha256_bytes(content):
            raise AuditError(f"output report manifest mismatch: {rel}")
        if machine_path_hits(content.decode("utf-8", "replace")):
            raise AuditError(f"machine-specific path leaked into evidence: {rel}")
    summary = json.loads((output_dir / "SUMMARY.json").read_text(encoding="utf-8"))
    validation = json.loads((output_dir / "VALIDATION.json").read_text(encoding="utf-8"))
    if summary.get("status") != "pc01_selected_parameterization_points_collected":
        raise AuditError("unexpected summary status")
    if validation.get("status") != "pass" or validation.get("selected_character_id") != "PC01":
        raise AuditError("parameterization validation did not pass")
    if validation.get("source_snapshots", 0) < 1 or validation.get("parameterization_points", 0) < 1:
        raise AuditError("parameterization evidence is empty")
    for key in ("prepare_allowed", "commit_allowed", "installation_allowed", "runtime_validation_allowed"):
        if bool(validation.get(key)):
            raise AuditError(f"unsafe output authorization: {key}")


def main() -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    collect_parser = sub.add_parser("collect")
    collect_parser.add_argument("--workstream-root", type=Path, required=True)
    source_group = collect_parser.add_mutually_exclusive_group(required=True)
    source_group.add_argument("--stage83-archive", type=Path)
    source_group.add_argument("--stage83-dir", type=Path)
    collect_parser.add_argument("--output-dir", type=Path, required=True)
    validate_parser = sub.add_parser("validate")
    validate_parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    try:
        if args.command == "collect":
            collect(
                args.workstream_root,
                args.output_dir,
                stage83_archive=args.stage83_archive,
                stage83_dir=args.stage83_dir,
            )
        else:
            validate(args.output_dir)
    except (AuditError, OSError, ValueError, KeyError) as exc:
        print(f"ERROR: {exc}", file=__import__("sys").stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
