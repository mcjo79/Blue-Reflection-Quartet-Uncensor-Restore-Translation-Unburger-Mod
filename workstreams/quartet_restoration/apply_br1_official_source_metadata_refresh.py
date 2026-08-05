#!/usr/bin/env python3
"""Transactionally refresh BR1 source metadata from official Steam PAKs.

Stage 107 consumes the completed stage-106 preview.  It verifies only the four
canonical non-underscore PAKs, reuses or creates official extraction workspaces,
rebuilds complete inventory metadata for the 33 payload-changed members, and
updates only dependency-scoped report metadata.  Preserved underscore PAK files
are never read and are not required.

The transaction updates the canonical BR1 source inventory, affected difference
rows, affected review-queue rows, archive inventory, research summary, provenance
ledger, and the compact inventory/diff report archive.  It never writes a game
PAK, G1E/G1EM payload, profile, registry, installed game, or Git repository.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import importlib.util
import io
import json
import math
import os
import shutil
import subprocess
import sys
import tempfile
from collections import Counter, defaultdict
from pathlib import Path, PurePosixPath
from typing import Any, Iterable, Mapping, Sequence

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT_DEFAULT = SCRIPT_DIR.parent.parent
TOOL_VERSION = "0.1.21"
REPORT_NAME = "BR_quartet_restoration_br1_official_source_metadata_refresh_evidence.tar.zst"
REPORT_DIR = "br1_official_source_metadata_refresh_evidence"
STAGE106_REPORT_NAME = "BR_quartet_restoration_br1_official_source_inventory_refresh_preview_evidence.tar.zst"
LEDGER_REL = Path("provenance/br1_source_archive_provenance_ledger.json")
STATE_REL = Path(".local/state/quartet_restoration/BR1_OFFICIAL_SOURCE_METADATA_REFRESH_STATE.json")
QUEUE_FILES = ("REVIEW_QUEUE.tsv", "FOCUSED_REVIEW_QUEUE.tsv", "DEFERRED_QUEUE.tsv")
EXPECTED_ARCHIVES = {
    "pack00_02": "DATA/PACK00_02.PAK",
    "pack00_04_1": "DATA/PACK00_04_1.PAK",
    "pack00_04_2": "DATA/PACK00_04_2.PAK",
    "pack00_04_3": "DATA/PACK00_04_3.PAK",
}
REPORT_ARCHIVE_MEMBERS = (
    "inventories/br1_assets.source.json",
    "inventories/br1_assets.target.json",
    "inventories/br1_events.source.json",
    "inventories/br1_events.target.json",
    "inventories/br1_language.source.json",
    "inventories/br1_language.target.json",
    "differences/br1_assets.json",
    "differences/br1_events.json",
    "differences/br1_language.json",
    "REVIEW_QUEUE.tsv",
    "ARCHIVE_INVENTORY.tsv",
    "FOCUSED_REVIEW_QUEUE.tsv",
    "DEFERRED_QUEUE.tsv",
    "SUMMARY.json",
    LEDGER_REL.as_posix(),
)


class Stage107Error(RuntimeError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise Stage107Error(message)


def progress(message: str) -> None:
    print(f"[stage107] {message}", file=sys.stderr, flush=True)


def hash_file(path: Path, algorithm: str = "sha256") -> str:
    digest = hashlib.new(algorithm)
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(4 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def hash_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def json_bytes(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise Stage107Error(f"invalid JSON {path}: {exc}") from exc


def safe_int(value: Any, default: int = -1) -> int:
    try:
        text = str(value).strip()
        return int(text, 16) if text.casefold().startswith("0x") else int(text)
    except (TypeError, ValueError):
        return default


def safe_posix(raw: str) -> str:
    value = raw.replace("\\", "/").lstrip("/")
    pure = PurePosixPath(value)
    require(pure.parts and ".." not in pure.parts, f"unsafe member path: {raw!r}")
    return pure.as_posix()


def load_module(path: Path, name: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    require(spec is not None and spec.loader is not None, f"cannot load module: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def read_tsv(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    require(path.is_file(), f"missing TSV: {path}")
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        require(reader.fieldnames is not None, f"TSV has no header: {path}")
        return list(reader.fieldnames), list(reader)


def tsv_bytes(fields: Sequence[str], rows: Iterable[Mapping[str, Any]], *, crlf: bool = False) -> bytes:
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(
        buffer,
        fieldnames=list(fields),
        delimiter="\t",
        lineterminator="\r\n" if crlf else "\n",
        extrasaction="ignore",
    )
    writer.writeheader()
    for row in rows:
        writer.writerow({field: row.get(field, "") for field in fields})
    return buffer.getvalue().encode("utf-8")


def extract_report(report: Path, destination: Path) -> Path:
    result = subprocess.run(
        ["tar", "--zstd", "-xf", str(report), "-C", str(destination)],
        text=True,
        capture_output=True,
    )
    require(result.returncode == 0, result.stderr.strip() or f"failed to extract {report}")
    root = destination / "br1_official_source_inventory_refresh_preview_evidence"
    require(root.is_dir(), f"stage-106 report directory missing: {root}")
    return root


def make_archive(source: Path, output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(output.name + ".tmp")
    temporary.unlink(missing_ok=True)
    result = subprocess.run(
        [
            "tar", "--sort=name", "--mtime=@0", "--owner=0", "--group=0",
            "--numeric-owner", "--zstd", "-cf", str(temporary),
            "-C", str(source.parent), source.name,
        ],
        text=True,
        capture_output=True,
    )
    require(result.returncode == 0, result.stderr.strip() or "failed to create report archive")
    os.replace(temporary, output)


def find_gust_pak(project_root: Path, explicit: Path | None) -> Path:
    candidates: list[Path] = []
    if explicit is not None:
        candidates.append(explicit.expanduser())
    candidates.extend([
        project_root / ".local/vendor/gust_tools/gust_pak",
        Path.home() / "Downloads/gust_tools/gust_pak",
    ])
    found = shutil.which("gust_pak")
    if found:
        candidates.append(Path(found))
    for candidate in candidates:
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return candidate.resolve()
    raise Stage107Error("gust_pak was not found and no official extraction cache is available")


def find_cached_extraction(project_root: Path, source_sha256: str, br: Any) -> Path | None:
    workspace_root = project_root / ".local/workspaces/quartet_restoration"
    if not workspace_root.is_dir():
        return None
    for marker in workspace_root.rglob(".br_restoration_extraction.json"):
        try:
            data = load_json(marker)
        except Stage107Error:
            continue
        if str(data.get("source_archive_sha256", "")).casefold() != source_sha256.casefold():
            continue
        manifest_name = str(data.get("manifest_name", ""))
        manifest_path = marker.parent / manifest_name
        if not manifest_path.is_file():
            continue
        try:
            br._load_gust_pak_manifest(manifest_path)
        except Exception:
            continue
        return marker.parent
    return None


def extract_or_reuse_official(
    *,
    project_root: Path,
    game_root: Path,
    archive: Path,
    pair_id: str,
    official_sha256: str,
    br: Any,
    gust_pak_explicit: Path | None,
) -> tuple[Path, Mapping[str, Any], str]:
    cached = find_cached_extraction(project_root, official_sha256, br)
    if cached is not None:
        marker = load_json(cached / ".br_restoration_extraction.json")
        manifest = br._load_gust_pak_manifest(cached / str(marker["manifest_name"]))
        return cached, manifest, "reused_official_sha256_cache"
    gust_pak = find_gust_pak(project_root, gust_pak_explicit)
    workspace_root = project_root / ".local/workspaces/quartet_restoration/source_provenance_stage107"
    result = br.extract_archive(
        archive=archive,
        game_root=game_root,
        gust_pak=gust_pak,
        gust_pak_sha256=hash_file(gust_pak),
        pair_id=pair_id,
        side="official_refresh",
        workspace_root=workspace_root,
        timeout_seconds=7200,
    )
    workspace = Path(result["workspace"])
    manifest = br._load_gust_pak_manifest(workspace / str(result["manifest_name"]))
    return workspace, manifest, "extracted_official_stage107_workspace"


def manifest_member_map(workspace: Path, manifest: Mapping[str, Any]) -> dict[str, Path]:
    rows: dict[str, Path] = {}
    for item in manifest.get("safe_files", []):
        name = safe_posix(str(item.get("safe_name", "")))
        key = name.casefold()
        require(key not in rows, f"duplicate extracted member: {name}")
        payload = workspace / name
        require(payload.is_file(), f"official extracted member missing: {payload}")
        rows[key] = payload
    return rows


def index_inventory_files(inventory: Mapping[str, Any]) -> tuple[dict[tuple[str, str], dict[str, Any]], dict[str, list[dict[str, Any]]]]:
    by_archive_path: dict[tuple[str, str], dict[str, Any]] = {}
    by_comparison: dict[str, list[dict[str, Any]]] = defaultdict(list)
    files = inventory.get("files", [])
    require(isinstance(files, list), "inventory files must be a list")
    for row in files:
        require(isinstance(row, dict), "inventory row must be an object")
        archive = str(row.get("archive", "")).casefold()
        path = safe_posix(str(row.get("path", ""))).casefold()
        key = (archive, path)
        require(key not in by_archive_path, f"duplicate inventory row: {key}")
        by_archive_path[key] = row
        comparison = str(row.get("comparison_key") or row.get("normalized_path") or row.get("path") or "").casefold()
        require(comparison, f"inventory row missing comparison key: {key}")
        by_comparison[comparison].append(row)
    return by_archive_path, by_comparison


def index_difference_rows(report: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    rows: dict[str, dict[str, Any]] = {}
    for row in report.get("entries", []):
        key = str(row.get("normalized_path", "")).casefold()
        require(key, "difference row missing normalized_path")
        require(key not in rows, f"duplicate difference path: {key}")
        rows[key] = row
    return rows


def determine_classification(new_source: Mapping[str, Any], target_inventory: Mapping[str, Any], br: Any) -> tuple[str, dict[str, Any] | None, str]:
    comparison_key = str(new_source["comparison_key"]).casefold()
    _, target_by_comparison = index_inventory_files(target_inventory)
    same_key = list(target_by_comparison.get(comparison_key, []))
    exact_same = [row for row in same_key if str(row.get("sha256", "")).casefold() == str(new_source["sha256"]).casefold()]
    if exact_same:
        require(len(exact_same) == 1, f"multiple exact target rows for {comparison_key}")
        return "identical", exact_same[0], "normalized_path_and_sha256"
    if same_key:
        require(len(same_key) == 1, f"multiple nonidentical target rows for {comparison_key}")
        return "changed", same_key[0], "normalized_path"

    target_files = list(target_inventory.get("files", []))
    exact_outside = [row for row in target_files if str(row.get("sha256", "")).casefold() == str(new_source["sha256"]).casefold()]
    if exact_outside:
        require(len(exact_outside) == 1, f"multiple exact moved targets for {comparison_key}")
        return "probably_moved", exact_outside[0], "sha256_outside_normalized_path"

    basename = Path(str(new_source["normalized_path"])).name.casefold()
    extension = str(new_source.get("extension", ""))
    source_size = safe_int(new_source.get("size"), 0)
    candidates: list[tuple[float, float, dict[str, Any]]] = []
    for target in target_files:
        same_basename = Path(str(target.get("normalized_path", ""))).name.casefold() == basename
        same_extension = str(target.get("extension", "")) == extension
        ratio = br.size_ratio(dict(new_source), target)
        if not same_basename and not (same_extension and ratio >= 0.95):
            continue
        similarity = br.bounded_similarity(dict(new_source), target)
        score = (similarity * 0.75) + (ratio * 0.2) + (0.05 if same_basename else 0.0)
        candidates.append((score, similarity, target))
    candidates.sort(key=lambda item: item[0], reverse=True)
    if candidates:
        best_score = candidates[0][0]
        runner_up = candidates[1][0] if len(candidates) > 1 else 0.0
        require(
            not (best_score >= 0.78 and best_score - runner_up >= 0.12),
            f"official payload creates a potential fuzzy moved classification for {comparison_key}; run a full canonical inventory rebuild",
        )
    return "removed_in_target", None, "no_target_match"


def update_queue_rows(
    *,
    report_root: Path,
    changed_paths: set[str],
    new_diff_by_path: Mapping[str, Mapping[str, Any]],
    br: Any,
) -> tuple[dict[Path, bytes], list[dict[str, Any]]]:
    outputs: dict[Path, bytes] = {}
    evidence: list[dict[str, Any]] = []
    expected_membership: dict[str, set[str]] = defaultdict(set)
    for filename in QUEUE_FILES:
        path = report_root / filename
        fields, rows = read_tsv(path)
        changed_count = 0
        for row in rows:
            if str(row.get("pair_id", "")) != "br1_assets":
                continue
            key = str(row.get("normalized_path", "")).replace("\\", "/").casefold()
            if key not in changed_paths:
                continue
            expected_membership[key].add(filename)
            diff = dict(new_diff_by_path[key])
            replacement = br.review_row("br1_assets", diff)
            replacement["review_classification"] = row.get("review_classification", "not_assessed")
            replacement["review_note"] = row.get("review_note", "")
            for field in fields:
                row[field] = str(replacement.get(field, row.get(field, "")))
            changed_count += 1
        outputs[path] = tsv_bytes(fields, rows, crlf=True)
        evidence.append({
            "queue_file": filename,
            "total_rows": len(rows),
            "refreshed_rows": changed_count,
            "classification_changes": 0,
            "membership_changes": 0,
        })

    for member in sorted(changed_paths):
        diff = new_diff_by_path[member]
        scope = str(diff.get("scope_status", "in_scope"))
        review = br.review_row("br1_assets", dict(diff))
        desired = {"REVIEW_QUEUE.tsv"} if scope == "in_scope" else {"DEFERRED_QUEUE.tsv"}
        if scope == "in_scope" and int(review["focus_score"]) >= 60:
            desired.add("FOCUSED_REVIEW_QUEUE.tsv")
        require(expected_membership.get(member, set()) == desired, f"queue membership would change for {member}: {expected_membership.get(member, set())} -> {desired}")
    return outputs, evidence


def update_archive_inventory(path: Path, archive_replacements: Sequence[Mapping[str, str]]) -> tuple[bytes, list[dict[str, Any]]]:
    fields, rows = read_tsv(path)
    replacements = {str(row["archive"]).casefold(): row for row in archive_replacements}
    seen: set[str] = set()
    evidence: list[dict[str, Any]] = []
    for row in rows:
        if str(row.get("pair_id", "")) != "br1_assets" or str(row.get("side", "")) != "source":
            continue
        key = str(row.get("archive", "")).casefold()
        replacement = replacements.get(key)
        if replacement is None:
            continue
        old_sha = str(row.get("sha256", ""))
        require(old_sha.casefold() in {str(replacement["old_sha256"]).casefold(), str(replacement["new_sha256"]).casefold()}, f"archive inventory drift for {row.get('archive')}")
        row["size"] = str(replacement["new_size"])
        row["sha256"] = str(replacement["new_sha256"])
        row["extraction_status"] = "official_steam_canonical"
        seen.add(key)
        evidence.append({
            "archive": row["archive"],
            "old_sha256": replacement["old_sha256"],
            "new_sha256": replacement["new_sha256"],
            "result": "refreshed_official_steam_canonical",
        })
    require(seen == set(replacements), f"ARCHIVE_INVENTORY missing source rows: {sorted(set(replacements) - seen)}")
    return tsv_bytes(fields, rows, crlf=True), evidence


def make_inventory_report_archive(report_root: Path, staged_bytes: Mapping[Path, bytes], output: Path) -> None:
    with tempfile.TemporaryDirectory(prefix="br_stage107_report_archive_") as td:
        root = Path(td) / "quartet_restoration"
        for rel_text in REPORT_ARCHIVE_MEMBERS:
            rel = Path(rel_text)
            source = report_root / rel
            target = root / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            if source in staged_bytes:
                target.write_bytes(staged_bytes[source])
            else:
                require(source.is_file(), f"inventory report member missing: {source}")
                shutil.copy2(source, target)
        make_archive(root, output)


def fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def atomic_write(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.stage107.tmp")
    temporary.unlink(missing_ok=True)
    with temporary.open("wb") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)
    fsync_directory(path.parent)


def apply_transaction(project_root: Path, staged: Mapping[Path, bytes], transaction_id: str) -> tuple[str, list[dict[str, Any]]]:
    before_hashes = {path: hash_file(path) if path.is_file() else "" for path in staged}
    after_hashes = {path: hash_bytes(payload) for path, payload in staged.items()}
    equal = {path: before_hashes[path] == after_hashes[path] for path in staged}
    if all(equal.values()):
        return "already_applied_verified", [
            {"path": path.relative_to(project_root).as_posix(), "before_sha256": before_hashes[path], "after_sha256": after_hashes[path], "action": "verified_already_applied"}
            for path in sorted(staged, key=lambda item: item.as_posix())
        ]
    source_anchor = next(
        (path for path in staged if path.as_posix().endswith("/inventories/br1_assets.source.json")),
        None,
    )
    require(source_anchor is not None, "transaction source-inventory anchor is missing")
    require(
        not equal[source_anchor],
        "mixed metadata state detected: canonical source inventory is already refreshed but another transaction target differs",
    )
    changed_targets = {path: payload for path, payload in staged.items() if not equal[path]}

    state_path = project_root / STATE_REL
    transaction_root = project_root / ".local/state/quartet_restoration/source_metadata_refresh_stage107" / transaction_id
    backup_root = transaction_root / "backup"
    backup_root.mkdir(parents=True, exist_ok=True)
    state = {
        "type": "br1_official_source_metadata_refresh_state",
        "format_version": 1,
        "tool_version": TOOL_VERSION,
        "transaction_id": transaction_id,
        "status": "prepared",
        "targets": [],
        "underscore_archives_required": False,
    }
    for path in sorted(changed_targets, key=lambda item: item.as_posix()):
        rel = path.relative_to(project_root)
        backup = backup_root / rel
        backup.parent.mkdir(parents=True, exist_ok=True)
        if path.is_file():
            shutil.copy2(path, backup)
        state["targets"].append({
            "path": rel.as_posix(),
            "before_sha256": before_hashes[path],
            "after_sha256": after_hashes[path],
            "backup": backup.relative_to(project_root).as_posix() if path.is_file() else "",
        })
    atomic_write(state_path, json_bytes(state))

    replaced: list[Path] = []
    try:
        state["status"] = "committing"
        atomic_write(state_path, json_bytes(state))
        for path in sorted(changed_targets, key=lambda item: item.as_posix()):
            atomic_write(path, changed_targets[path])
            require(hash_file(path) == after_hashes[path], f"post-write hash mismatch: {path}")
            replaced.append(path)
        state["status"] = "committed"
        atomic_write(state_path, json_bytes(state))
    except Exception:
        for path in reversed(replaced):
            rel = path.relative_to(project_root)
            backup = backup_root / rel
            if backup.is_file():
                atomic_write(path, backup.read_bytes())
            else:
                path.unlink(missing_ok=True)
        state["status"] = "rolled_back_after_failure"
        atomic_write(state_path, json_bytes(state))
        raise

    evidence = [
        {
            "path": path.relative_to(project_root).as_posix(),
            "before_sha256": before_hashes[path],
            "after_sha256": after_hashes[path],
            "action": "verified_unchanged" if equal[path] else "atomic_replace_with_backup",
        }
        for path in sorted(staged, key=lambda item: item.as_posix())
    ]
    return "applied_transactionally", evidence


def collect(
    *,
    project_root: Path,
    game_root: Path,
    stage106_report: Path,
    output: Path,
    gust_pak: Path | None,
    apply: bool,
) -> dict[str, Any]:
    project_root = project_root.resolve()
    game_root = game_root.resolve()
    report_root = project_root / ".local/reports/quartet_restoration"
    br_path = project_root / "Blue_Reflection_Text_Tool/br_restoration_tool.py"
    require(br_path.is_file(), f"missing restoration tool: {br_path}")
    br = load_module(br_path, "br_stage107_tool")

    source_path = report_root / "inventories/br1_assets.source.json"
    target_path = report_root / "inventories/br1_assets.target.json"
    diff_path = report_root / "differences/br1_assets.json"
    archive_inventory_path = report_root / "ARCHIVE_INVENTORY.tsv"
    summary_path = report_root / "SUMMARY.json"
    report_archive_path = report_root / "BR_quartet_restoration_inventory_and_diff.tar.zst"
    for path in (source_path, target_path, diff_path, archive_inventory_path, summary_path):
        require(path.is_file(), f"missing canonical metadata target: {path}")
    require(stage106_report.is_file(), f"missing stage-106 report: {stage106_report}")

    source_inventory = load_json(source_path)
    target_inventory = load_json(target_path)
    difference_report = load_json(diff_path)
    research_summary = load_json(summary_path)
    source_by_archive_path, _ = index_inventory_files(source_inventory)
    target_by_archive_path, _ = index_inventory_files(target_inventory)
    diff_by_path = index_difference_rows(difference_report)

    stage106_sha256 = hash_file(stage106_report)
    with tempfile.TemporaryDirectory(prefix="br_stage107_") as td:
        temp = Path(td)
        stage106_root = extract_report(stage106_report, temp)
        summary106 = load_json(stage106_root / "SUMMARY.json")
        require(summary106.get("tool_version") == "0.1.20", "stage-106 report tool version must be 0.1.20")
        require(safe_int(summary106.get("archive_replacement_rows")) == 4, "stage-106 report must contain four archive replacements")
        require(safe_int(summary106.get("member_replacement_rows")) == 33, "stage-106 report must contain 33 member replacements")
        require(safe_int(summary106.get("classification_changed_rows")) == 0, "stage-106 preview contains classification changes")
        require(safe_int(summary106.get("affected_registered_profile_rows")) == 0, "stage-106 preview contains affected profiles")
        require(bool(summary106.get("stage104_slot_light_evidence_independent")), "stage-104 independence not confirmed")

        _, archive_replacements = read_tsv(stage106_root / "OFFICIAL_SOURCE_ARCHIVE_REPLACEMENTS.tsv")
        _, member_replacements = read_tsv(stage106_root / "OFFICIAL_SOURCE_MEMBER_REPLACEMENTS.tsv")
        _, diff_preview = read_tsv(stage106_root / "OFFICIAL_SOURCE_DIFF_RECLASSIFICATION.tsv")
        _, queue_preview = read_tsv(stage106_root / "OFFICIAL_SOURCE_QUEUE_REVALIDATION.tsv")
        require(len(archive_replacements) == 4 and len(member_replacements) == 33 and len(diff_preview) == 33 and len(queue_preview) == 33, "stage-106 row counts are inconsistent")
        archive_by_pair = {row["pair_id"]: row for row in archive_replacements}
        require(set(archive_by_pair) == set(EXPECTED_ARCHIVES), "unexpected stage-106 archive set")
        preview_diff_by_path = {row["member_path"].casefold(): row for row in diff_preview}
        member_by_pair: dict[str, list[dict[str, str]]] = defaultdict(list)
        for row in member_replacements:
            member_by_pair[row["pair_id"]].append(row)

        official_payloads: dict[str, Path] = {}
        archive_evidence: list[dict[str, Any]] = []
        for pair_id in sorted(EXPECTED_ARCHIVES):
            replacement = archive_by_pair[pair_id]
            archive_rel = EXPECTED_ARCHIVES[pair_id]
            require(str(replacement["archive"]).casefold() == archive_rel.casefold(), f"archive mismatch for {pair_id}")
            archive = game_root / archive_rel
            require(archive.is_file(), f"official non-underscore archive missing: {archive}")
            require(archive.stat().st_size == safe_int(replacement["new_size"]), f"official archive size mismatch: {archive}")
            actual_sha = hash_file(archive)
            require(actual_sha.casefold() == replacement["new_sha256"].casefold(), f"official archive SHA-256 mismatch: {archive}")
            progress(f"official archive verified: {archive_rel}")
            workspace, manifest, extraction_mode = extract_or_reuse_official(
                project_root=project_root,
                game_root=game_root,
                archive=archive,
                pair_id=pair_id,
                official_sha256=actual_sha,
                br=br,
                gust_pak_explicit=gust_pak,
            )
            member_map = manifest_member_map(workspace, manifest)
            for member in member_by_pair[pair_id]:
                key = member["member_path"].casefold()
                require(key in member_map, f"official extraction missing changed member: {member['member_path']}")
                official_payloads[key] = member_map[key]
            archive_evidence.append({
                "pair_id": pair_id,
                "archive": archive_rel,
                "official_size": archive.stat().st_size,
                "official_sha256": actual_sha,
                "extraction_mode": extraction_mode,
                "underscore_archive_read": False,
            })

        new_source_inventory = json.loads(json.dumps(source_inventory))
        new_source_by_archive_path, _ = index_inventory_files(new_source_inventory)
        archive_rows = {str(row.get("archive", "")).casefold(): row for row in new_source_inventory.get("archives", [])}
        archive_refresh_rows: list[dict[str, Any]] = []
        for replacement in archive_replacements:
            key = replacement["archive"].casefold()
            row = archive_rows.get(key)
            require(row is not None, f"source inventory missing archive row: {replacement['archive']}")
            current_sha = str(row.get("sha256", "")).casefold()
            require(current_sha in {replacement["old_sha256"].casefold(), replacement["new_sha256"].casefold()}, f"source archive inventory drift: {replacement['archive']}")
            row["size"] = safe_int(replacement["new_size"])
            row["sha256"] = replacement["new_sha256"]
            row["extraction_status"] = "official_steam_canonical"
            row["provenance"] = "official_steam_canonical"
            row["sha1"] = replacement["new_sha1"]
            row["preserved_untrusted_candidate"] = {
                "sha1": replacement["old_sha1"],
                "sha256": replacement["old_sha256"],
                "size": safe_int(replacement["old_size"]),
                "archive_filename": Path(replacement["archive"]).name + "_",
                "retained_as_file": False,
            }
            archive_refresh_rows.append({
                "archive": replacement["archive"],
                "old_sha256": replacement["old_sha256"],
                "new_sha256": replacement["new_sha256"],
                "result": "official_identity_installed_in_source_inventory",
            })

        member_refresh_rows: list[dict[str, Any]] = []
        new_rows_by_path: dict[str, dict[str, Any]] = {}
        for replacement in sorted(member_replacements, key=lambda row: row["member_path"].casefold()):
            archive_key = replacement["archive"].casefold()
            member_key = replacement["member_path"].casefold()
            row = new_source_by_archive_path.get((archive_key, member_key))
            require(row is not None, f"source inventory missing changed member: {replacement['member_path']}")
            current_sha = str(row.get("sha256", "")).casefold()
            require(current_sha in {replacement["old_sha256"].casefold(), replacement["new_sha256"].casefold()}, f"source member inventory drift: {replacement['member_path']}")
            payload = official_payloads[member_key]
            actual_sha = hash_file(payload)
            actual_size = payload.stat().st_size
            require(actual_sha.casefold() == replacement["new_sha256"].casefold(), f"official member SHA-256 mismatch: {replacement['member_path']}")
            require(actual_size == safe_int(replacement["new_size"]), f"official member size mismatch: {replacement['member_path']}")
            row["size"] = actual_size
            row["sha256"] = actual_sha
            row["magic_hex"] = br.read_magic(payload)
            row["sample_block_size"] = br.SAMPLE_BLOCK_SIZE
            row["sample_hashes"] = br.sample_hashes(payload)
            row["provenance"] = "official_steam_canonical"
            row["preserved_untrusted_candidate_sha256"] = replacement["old_sha256"]
            row["canonical_refresh_stage"] = 107
            new_rows_by_path[member_key] = row
            member_refresh_rows.append({
                "archive": replacement["archive"],
                "member_path": replacement["member_path"],
                "old_sha256": replacement["old_sha256"],
                "new_sha256": replacement["new_sha256"],
                "sample_hash_count": len(row["sample_hashes"]),
                "result": "official_payload_metadata_rebuilt",
            })
        require(len(new_rows_by_path) == 33, "did not rebuild exactly 33 source member rows")

        provenance_ledger = {
            "type": "br1_source_archive_provenance_ledger",
            "format_version": 1,
            "tool_version": TOOL_VERSION,
            "canonical_policy": {
                "official_nonunderscore_archives_are_canonical": True,
                "underscore_archives_are_historical_analysis_only": True,
                "underscore_archives_required_for_normal_workflow": False,
                "underscore_archives_safe_to_delete_after_committed_stage107": True,
            },
            "source_evidence": {
                "stage106_report": STAGE106_REPORT_NAME,
                "stage106_report_sha256": stage106_sha256,
                "archive_pairs": 4,
                "changed_members": 33,
                "classification_changes": 0,
                "affected_registered_profiles": 0,
            },
            "archives": archive_replacements,
            "members": member_replacements,
            "retirement": {
                "preserved_files": [Path(row["archive"]).name + "_" for row in archive_replacements],
                "file_payloads_retained_by_project": False,
                "hashes_and_member_level_diff_retained": True,
                "normal_workflow_dependency_after_refresh": False,
            },
        }
        new_source_inventory["canonical_source_provenance"] = {
            "tool_version": TOOL_VERSION,
            "stage": 107,
            "ledger": LEDGER_REL.as_posix(),
            "stage106_report_sha256": stage106_sha256,
            "official_archives": 4,
            "refreshed_members": 33,
            "underscore_archives_required": False,
        }

        old_member_sha_by_path = {row["member_path"].casefold(): row["old_sha256"] for row in member_replacements}
        new_difference_report = json.loads(json.dumps(difference_report))
        new_diff_by_path = index_difference_rows(new_difference_report)
        diff_refresh_rows: list[dict[str, Any]] = []
        for member_key, source_row in sorted(new_rows_by_path.items()):
            preview = preview_diff_by_path.get(member_key)
            require(preview is not None, f"stage-106 preview missing difference row: {member_key}")
            diff = new_diff_by_path.get(member_key)
            require(diff is not None, f"difference report missing row: {member_key}")
            new_class, target_row, mapping_basis = determine_classification(source_row, target_inventory, br)
            require(new_class == preview["new_classification"], f"classification differs from approved preview for {member_key}: {preview['new_classification']} -> {new_class}")
            require(str(diff.get("classification", "")) == preview["old_classification"], f"current difference classification drift: {member_key}")
            if target_row is None:
                new_similarity = 0.0
                new_size_ratio = 0.0
            else:
                new_similarity = 1.0 if new_class in {"identical", "probably_moved"} and str(source_row["sha256"]) == str(target_row["sha256"]) else br.bounded_similarity(source_row, target_row)
                new_size_ratio = br.size_ratio(source_row, target_row)
            diff["classification"] = new_class
            diff["source"] = br.file_ref(source_row)
            diff["target"] = br.file_ref(target_row)
            diff["binary_similarity"] = new_similarity
            diff["binary_similarity_method"] = "bounded_sample_hash_alignment_and_jaccard"
            diff["size_ratio"] = new_size_ratio
            diff["confidence"] = "exact" if new_class == "identical" else ("exact_hash" if new_class == "probably_moved" else ("exact_path" if new_class == "changed" else "structural"))
            diff["mapping_basis"] = mapping_basis
            scope, reason = br.scope_status(new_class, str(diff["normalized_path"]), source_row, target_row)
            diff["scope_status"] = scope
            diff["scope_reason"] = reason
            diff["manual_review_priority"] = br.manual_review_priority(new_class, source_row, scope)
            diff["source_provenance"] = "official_steam_canonical"
            diff["preserved_untrusted_source_sha256"] = old_member_sha_by_path[member_key]
            diff["canonical_refresh_stage"] = 107
            diff_refresh_rows.append({
                "member_path": member_key,
                "difference_id": diff.get("difference_id", ""),
                "classification": new_class,
                "old_source_sha256": old_member_sha_by_path[member_key],
                "new_source_sha256": source_row["sha256"],
                "old_binary_similarity": diff_by_path[member_key].get("binary_similarity", ""),
                "new_binary_similarity": new_similarity,
                "classification_changed": False,
            })

        classification_counts = Counter(str(row.get("classification", "")) for row in new_difference_report.get("entries", []))
        priority_counts = Counter(str(row.get("manual_review_priority", "")) for row in new_difference_report.get("entries", []))
        scope_counts = Counter(str(row.get("scope_status", "")) for row in new_difference_report.get("entries", []))
        if isinstance(new_difference_report.get("summary"), dict):
            new_difference_report["summary"]["classifications"] = dict(sorted(classification_counts.items()))
            new_difference_report["summary"]["manual_review_priorities"] = dict(sorted(priority_counts.items()))
            new_difference_report["summary"]["scope_statuses"] = dict(sorted(scope_counts.items()))
        new_difference_report["canonical_source_provenance"] = {
            "tool_version": TOOL_VERSION,
            "stage": 107,
            "ledger": LEDGER_REL.as_posix(),
            "refreshed_source_rows": 33,
            "classification_changes": 0,
        }

        changed_paths = set(new_rows_by_path)
        queue_outputs, queue_refresh_rows = update_queue_rows(
            report_root=report_root,
            changed_paths=changed_paths,
            new_diff_by_path=new_diff_by_path,
            br=br,
        )
        archive_inventory_bytes, archive_inventory_evidence = update_archive_inventory(archive_inventory_path, archive_replacements)

        new_research_summary = json.loads(json.dumps(research_summary))
        new_research_summary["canonical_source_provenance"] = {
            "tool_version": TOOL_VERSION,
            "stage": 107,
            "official_archives": 4,
            "refreshed_members": 33,
            "classification_changes": 0,
            "affected_registered_profiles": 0,
            "underscore_archives_required": False,
            "ledger": LEDGER_REL.as_posix(),
        }

        staged: dict[Path, bytes] = {
            source_path: json_bytes(new_source_inventory),
            diff_path: json_bytes(new_difference_report),
            archive_inventory_path: archive_inventory_bytes,
            summary_path: json_bytes(new_research_summary),
            report_root / LEDGER_REL: json_bytes(provenance_ledger),
            **queue_outputs,
        }
        temporary_report_archive = temp / "BR_quartet_restoration_inventory_and_diff.tar.zst"
        make_inventory_report_archive(report_root, staged, temporary_report_archive)
        staged[report_archive_path] = temporary_report_archive.read_bytes()

        transaction_id = "stage107_" + stage106_sha256[:16]
        if apply:
            transaction_mode, transaction_rows = apply_transaction(project_root, staged, transaction_id)
        else:
            transaction_mode = "validated_preview_only"
            transaction_rows = [
                {
                    "path": path.relative_to(project_root).as_posix(),
                    "before_sha256": hash_file(path) if path.is_file() else "",
                    "after_sha256": hash_bytes(payload),
                    "action": "would_atomic_replace_with_backup",
                }
                for path, payload in sorted(staged.items(), key=lambda item: item[0].as_posix())
            ]

        report_dir = temp / REPORT_DIR
        report_dir.mkdir()
        write_specs = [
            ("OFFICIAL_SOURCE_ARCHIVE_VERIFICATION.tsv", ["pair_id", "archive", "official_size", "official_sha256", "extraction_mode", "underscore_archive_read"], archive_evidence),
            ("OFFICIAL_SOURCE_ARCHIVE_REFRESH_RESULT.tsv", ["archive", "old_sha256", "new_sha256", "result"], archive_refresh_rows),
            ("OFFICIAL_SOURCE_MEMBER_REFRESH_RESULT.tsv", ["archive", "member_path", "old_sha256", "new_sha256", "sample_hash_count", "result"], member_refresh_rows),
            ("OFFICIAL_SOURCE_DIFF_REFRESH_RESULT.tsv", ["member_path", "difference_id", "classification", "old_source_sha256", "new_source_sha256", "old_binary_similarity", "new_binary_similarity", "classification_changed"], diff_refresh_rows),
            ("OFFICIAL_SOURCE_QUEUE_REFRESH_RESULT.tsv", ["queue_file", "total_rows", "refreshed_rows", "classification_changes", "membership_changes"], queue_refresh_rows),
            ("OFFICIAL_SOURCE_ARCHIVE_INVENTORY_REFRESH_RESULT.tsv", ["archive", "old_sha256", "new_sha256", "result"], archive_inventory_evidence),
            ("OFFICIAL_SOURCE_TRANSACTION_TARGETS.tsv", ["path", "before_sha256", "after_sha256", "action"], transaction_rows),
        ]
        for filename, fields, rows in write_specs:
            (report_dir / filename).write_bytes(tsv_bytes(fields, rows))
        retirement_rows = [
            {"question": "are underscore archives required by stage 107", "answer": False, "classification": "official_and_report_only_inputs"},
            {"question": "does normal workflow require underscore archives after committed refresh", "answer": False, "classification": "retired_historical_files"},
            {"question": "are preserved hashes and member-level differences retained", "answer": True, "classification": "provenance_ledger_and_stage105_106_reports"},
            {"question": "may underscore archives be deleted after committed or already-applied verification", "answer": transaction_mode in {"applied_transactionally", "already_applied_verified"}, "classification": "retirement_readiness"},
            {"question": "does stage 107 delete underscore archives", "answer": False, "classification": "user_managed_cleanup_only"},
        ]
        (report_dir / "UNDERSCORE_ARCHIVE_RETIREMENT_READINESS.tsv").write_bytes(tsv_bytes(["question", "answer", "classification"], retirement_rows))
        summary = {
            "type": "br_quartet_restoration_br1_official_source_metadata_refresh_evidence_summary",
            "format_version": 1,
            "tool_version": TOOL_VERSION,
            "status": "official_source_metadata_refresh_committed" if transaction_mode == "applied_transactionally" else ("official_source_metadata_refresh_already_applied_verified" if transaction_mode == "already_applied_verified" else "official_source_metadata_refresh_preview_validated"),
            "transaction_mode": transaction_mode,
            "official_archive_rows": 4,
            "refreshed_member_rows": 33,
            "refreshed_difference_rows": 33,
            "classification_changed_rows": 0,
            "refreshed_review_queue_rows": sum(safe_int(row["refreshed_rows"], 0) for row in queue_refresh_rows),
            "registered_profiles_affected": 0,
            "stage104_slot_light_evidence_independent": True,
            "transaction_target_rows": len(transaction_rows),
            "underscore_archives_read": False,
            "underscore_archives_required_after_refresh": False,
            "underscore_archives_safe_to_delete": transaction_mode in {"applied_transactionally", "already_applied_verified"},
            "preserved_hashes_and_member_diff_retained": True,
            "policy": {
                "official_nonunderscore_archives_are_canonical": True,
                "pak_write_authorized": False,
                "G1E_G1EM_write_authorized": False,
                "profile_or_registry_write_authorized": False,
                "installed_game_write": False,
                "unrelated_results_invalidated": False,
            },
            "next_action": "Upload this report. If transaction_mode is applied_transactionally or already_applied_verified and underscore_archives_safe_to_delete is true, preserved underscore PAK files may be removed; continue normal analyses from official non-underscore PAKs and retained provenance reports.",
        }
        (report_dir / "SUMMARY.json").write_bytes(json_bytes(summary))
        make_archive(report_dir, output)
        return {"summary": summary, "report_path": str(output), "transaction_rows": transaction_rows}


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path, default=PROJECT_ROOT_DEFAULT)
    parser.add_argument("--game-root", type=Path, required=True)
    parser.add_argument("--stage106-report", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--gust-pak", type=Path)
    parser.add_argument("--validate-only", action="store_true", help="Build and validate the transaction without modifying metadata")
    args = parser.parse_args(argv)

    project_root = args.project_root.resolve()
    report_root = project_root / ".local/reports/quartet_restoration"
    stage106 = (args.stage106_report or (report_root / STAGE106_REPORT_NAME)).resolve()
    output = (args.output or (report_root / REPORT_NAME)).resolve()
    try:
        result = collect(
            project_root=project_root,
            game_root=args.game_root,
            stage106_report=stage106,
            output=output,
            gust_pak=args.gust_pak,
            apply=not args.validate_only,
        )
    except Stage107Error as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    progress(f"report: {result['report_path']}")
    print(json.dumps(result["summary"], ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
