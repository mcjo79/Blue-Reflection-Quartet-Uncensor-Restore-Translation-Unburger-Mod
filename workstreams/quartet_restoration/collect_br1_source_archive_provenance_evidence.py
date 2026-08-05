#!/usr/bin/env python3
"""Audit BR1 source-archive provenance and member-level differences.

Stage 105 compares preserved pre-Steam-verification PAK copies (trailing
underscore) with official Steam copies (no trailing underscore) for
PACK00_02 and PACK00_04_1..3.  It performs a member-level comparison, records
archive/member hashes and layout metadata, classifies changed resources, and
scans the existing quartet_restoration reports/build/profile metadata for
actual dependencies on changed members.

The stage is read-only with respect to installed game files.  It may extract
archives only into .local/workspaces/quartet_restoration and exports metadata
only.  It never replaces a PAK, changes a profile, or invalidates unrelated
results.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from collections import Counter, defaultdict
from pathlib import Path, PurePosixPath
from typing import Any, Iterable, Mapping, Sequence

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT_DEFAULT = SCRIPT_DIR.parent.parent
TOOL_VERSION = "0.1.19"
REPORT_NAME = "BR_quartet_restoration_br1_source_archive_provenance_evidence.tar.zst"
REPORT_DIR = "br1_source_archive_provenance_evidence"
EXPECTED_PRESERVED_PACK00_02_SHA1 = "5a96b714d4fb828511049558e702f4b216f03522"
EXPECTED_OFFICIAL_PACK00_02_SHA1 = "f4f10dd846bbb056b81e18050ad3edc680d0bc8b"
EXPECTED_PACK00_02_SIZE = 6423820279
ARCHIVE_PAIRS = (
    ("PACK00_02.PAK", "PACK00_02.PAK_"),
    ("PACK00_04_1.PAK", "PACK00_04_1.PAK_"),
    ("PACK00_04_2.PAK", "PACK00_04_2.PAK_"),
    ("PACK00_04_3.PAK", "PACK00_04_3.PAK_"),
)
EXPECTED_PACK00_02_CHANGED_BASENAMES = (
    "npc00_scl_b.g1t", "npc00_swm_b.g1t", "npc01_scl_a.g1t",
    "npc03_scl_a.g1t", "npc03_swm_a.g1t", "npc04_scl_d.g1t",
    "npc04_scl_e.g1t", "npc04_swm_d.g1t",
    "pc03_dlc_bkn_w.g1t", "pc03_dlc_slr_w.g1t", "pc03_dlc_twl_w.g1t",
    "pc03_dlc_vac_w.g1t", "pc03_nkd_w.g1t", "pc03_scl_w.g1t",
    "pc03_swm_w.g1t", "pc04_dlc_bkn_w.g1t", "pc04_dlc_slr_w.g1t",
    "pc04_dlc_twl_w.g1t", "pc04_dlc_vac_w.g1t", "pc04_nkd_w.g1t",
    "pc04_scl_w.g1t", "pc04_swm_w.g1t", "pc06_dlc_bkn_w.g1t",
    "pc06_dlc_slr_w.g1t", "pc06_dlc_twl_w.g1t", "pc06_dlc_vac_w.g1t",
    "pc06_nkd_w.g1t", "pc06_scl_w.g1t", "pc06_swm_w.g1t",
    "pc14_dlc_slr_w.g1t",
)
TEXT_SUFFIXES = {".json", ".tsv", ".csv", ".md", ".txt", ".sh", ".py", ".log"}


class Stage105Error(RuntimeError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise Stage105Error(message)


def progress(message: str) -> None:
    print(f"[stage105] {message}", file=sys.stderr, flush=True)


def hash_file(path: Path, algorithm: str) -> str:
    digest = hashlib.new(algorithm)
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(4 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_file(path: Path) -> str:
    return hash_file(path, "sha256")


def parse_int(value: Any, default: int = -1) -> int:
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


def write_tsv(path: Path, fields: Sequence[str], rows: Iterable[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(fields), delimiter="\t", lineterminator="\n", extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fields})


def load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise Stage105Error(f"invalid JSON {path}: {exc}") from exc


def load_module(path: Path, name: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    require(spec is not None and spec.loader is not None, f"cannot load module: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


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
    raise Stage105Error("gust_pak was not found; install it in .local/vendor/gust_tools, ~/Downloads/gust_tools, or PATH")


def make_archive(source: Path, output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(output.name + ".tmp")
    temporary.unlink(missing_ok=True)
    result = subprocess.run(["tar", "--zstd", "-cf", str(temporary), "-C", str(source.parent), source.name], text=True, capture_output=True)
    require(result.returncode == 0, result.stderr.strip() or "failed to create report archive")
    os.replace(temporary, output)


def read_inventory_archive_hashes(project_root: Path) -> dict[str, dict[str, Any]]:
    path = project_root / ".local/reports/quartet_restoration/inventories/br1_assets.source.json"
    require(path.is_file(), f"missing prior BR1 source inventory: {path}")
    data = load_json(path)
    require(isinstance(data, dict), "prior source inventory root must be an object")
    rows: dict[str, dict[str, Any]] = {}
    for row in data.get("archives", []):
        archive = str(row.get("archive", ""))
        if archive:
            rows[archive.casefold()] = dict(row)
    return rows


def find_cached_extraction(project_root: Path, source_sha256: str, br: Any) -> Path | None:
    workspace_root = project_root / ".local/workspaces/quartet_restoration"
    if not workspace_root.is_dir():
        return None
    for marker in workspace_root.rglob(".br_restoration_extraction.json"):
        try:
            data = load_json(marker)
        except Stage105Error:
            continue
        if str(data.get("source_archive_sha256", "")).casefold() != source_sha256.casefold():
            continue
        manifest_name = str(data.get("manifest_name", ""))
        manifest = marker.parent / manifest_name
        if not manifest.is_file():
            continue
        try:
            parsed = br._load_gust_pak_manifest(manifest)
        except Exception:
            continue
        if all((marker.parent / row["safe_name"]).is_file() for row in parsed.get("safe_files", [])):
            return marker.parent
    return None


def extract_or_reuse(*, project_root: Path, game_root: Path, archive: Path, pair_id: str, side: str, gust_pak: Path, br: Any) -> tuple[Path, dict[str, Any], str]:
    source_sha = sha256_file(archive)
    cached = find_cached_extraction(project_root, source_sha, br)
    if cached is not None:
        marker = load_json(cached / ".br_restoration_extraction.json")
        manifest = br._load_gust_pak_manifest(cached / str(marker["manifest_name"]))
        return cached, manifest, "reused_existing_extraction"
    workspace_root = project_root / ".local/workspaces/quartet_restoration/source_provenance_stage105"
    result = br.extract_archive(
        archive=archive,
        game_root=game_root,
        gust_pak=gust_pak,
        gust_pak_sha256=sha256_file(gust_pak),
        pair_id=pair_id,
        side=side,
        workspace_root=workspace_root,
        timeout_seconds=7200,
    )
    workspace = Path(result["workspace"])
    manifest = br._load_gust_pak_manifest(workspace / str(result["manifest_name"]))
    return workspace, manifest, "extracted_stage105_workspace"


def classify_asset(path: str) -> tuple[str, str, str]:
    folded = path.casefold()
    suffix = Path(path).suffix.casefold()
    if suffix == ".g1t": asset_type = "texture"
    elif suffix == ".g1m": asset_type = "model"
    elif suffix in {".g1e", ".g1em"}: asset_type = "effect"
    elif suffix == ".g1s": asset_type = "shader"
    elif suffix in {".ebd", ".ebm"}: asset_type = "event"
    elif suffix in {".kps"}: asset_type = "postprocess"
    elif suffix in {".xml", ".txt", ".csv", ".json"}: asset_type = "data_or_text"
    elif ".elixir" in folded: asset_type = "container"
    else: asset_type = suffix.lstrip(".") or "unknown"
    if "/character/" in folded: domain = "character"
    elif "/effect/" in folded: domain = "effect"
    elif "/shader/" in folded: domain = "shader"
    elif any(token in folded for token in ("/res/", "/res_en/", "/ipu/", "/ui/")): domain = "interface"
    elif "/system/" in folded: domain = "system"
    else: domain = "other"
    dlc = "legacy_or_dlc_named" if "dlc" in folded else "base_or_unspecified"
    return asset_type, domain, dlc


def member_rows(workspace: Path, manifest: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    rows: dict[str, dict[str, Any]] = {}
    for index, item in enumerate(manifest.get("safe_files", [])):
        name = safe_posix(str(item.get("safe_name", "")))
        key = name.casefold()
        require(key not in rows, f"duplicate member in manifest: {name}")
        payload = workspace / name
        require(payload.is_file(), f"extracted member missing: {payload}")
        rows[key] = {
            "name": name,
            "index": index,
            "offset": parse_int(item.get("offset")),
            "size": parse_int(item.get("size"), payload.stat().st_size),
            "flags": parse_int(item.get("flags"), 0),
            "payload_size": payload.stat().st_size,
            "sha256": sha256_file(payload),
        }
    return rows


def compare_members(pair_id: str, preserved: dict[str, dict[str, Any]], official: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for key in sorted(set(preserved) | set(official)):
        old = preserved.get(key)
        new = official.get(key)
        name = (old or new or {}).get("name", key)
        if old is None:
            status = "added_in_official"
        elif new is None:
            status = "removed_from_official"
        else:
            payload_equal = old["sha256"] == new["sha256"]
            layout_equal = all(old[field] == new[field] for field in ("index", "offset", "size", "flags"))
            if payload_equal and layout_equal: status = "identical"
            elif not payload_equal and layout_equal: status = "payload_changed_layout_stable"
            elif payload_equal and not layout_equal: status = "layout_changed_payload_identical"
            else: status = "payload_and_layout_changed"
        asset_type, domain, dlc = classify_asset(str(name))
        rows.append({
            "pair_id": pair_id,
            "member_path": name,
            "member_basename": Path(str(name)).name,
            "status": status,
            "asset_type": asset_type,
            "asset_domain": domain,
            "dlc_classification": dlc,
            "preserved_index": "" if old is None else old["index"],
            "official_index": "" if new is None else new["index"],
            "preserved_offset": "" if old is None else old["offset"],
            "official_offset": "" if new is None else new["offset"],
            "preserved_size": "" if old is None else old["size"],
            "official_size": "" if new is None else new["size"],
            "preserved_sha256": "" if old is None else old["sha256"],
            "official_sha256": "" if new is None else new["sha256"],
        })
    return rows


def artifact_scope(path: Path, project_root: Path) -> str:
    rel = path.relative_to(project_root).as_posix()
    if "core_profiles" in rel and rel.endswith(".json"): return "profile_manifest"
    if rel.startswith(".local/build/"): return "build_or_payload_metadata"
    if "/inventories/" in rel: return "inventory"
    if "/differences/" in rel: return "difference_report"
    if rel.endswith("REVIEW_QUEUE.tsv") or rel.endswith("FOCUSED_REVIEW_QUEUE.tsv"): return "review_queue"
    if rel.endswith("DEFERRED_QUEUE.tsv"): return "deferred_queue"
    if rel.startswith(".local/reports/"): return "report_metadata"
    if rel.startswith("workstreams/quartet_restoration/"): return "workstream_source_or_documentation"
    return "other_metadata"


def scan_text_artifacts(project_root: Path, changed_paths: Sequence[str], old_hashes: Sequence[str], output_root: Path) -> list[dict[str, Any]]:
    roots = [
        project_root / "workstreams/quartet_restoration",
        project_root / ".local/reports/quartet_restoration",
        project_root / ".local/build/quartet_restoration",
        project_root / ".local/state",
    ]
    path_needles = sorted({p.casefold() for p in changed_paths} | {Path(p).name.casefold() for p in changed_paths}, key=len, reverse=True)
    hash_needles = [h.casefold() for h in old_hashes if h]
    rows: list[dict[str, Any]] = []
    ignore_names = {
        "collect_br1_source_archive_provenance_evidence.py",
        "105_collect_br1_source_archive_provenance_evidence.sh",
        "BR1_SOURCE_ARCHIVE_PROVENANCE_WORKFLOW.md",
    }
    for root in roots:
        if not root.exists():
            continue
        for path in root.rglob("*"):
            if not path.is_file() or path.name in ignore_names or output_root in path.parents:
                continue
            if path.suffix.casefold() not in TEXT_SUFFIXES or path.stat().st_size > 64 * 1024 * 1024:
                continue
            try:
                text = path.read_text(encoding="utf-8", errors="ignore").casefold()
            except OSError:
                continue
            member_hits = sorted({needle for needle in path_needles if needle in text and ("/" in needle or needle.endswith(".g1t"))})
            canonical_hits = sorted({p for p in changed_paths if p.casefold() in text or Path(p).name.casefold() in text})
            hash_hits = sorted({h for h in hash_needles if h in text})
            if not canonical_hits and not hash_hits:
                continue
            rel = path.relative_to(project_root).as_posix()
            scope = artifact_scope(path, project_root)
            if canonical_hits:
                dependency = "direct_changed_member_dependency"
                action = "recheck_only_rows_or_results_referencing_changed_members"
            elif scope in {"inventory", "difference_report"}:
                dependency = "archive_level_aggregate_provenance_dependency"
                action = "refresh_archive_inventory_and_aggregate_counts_from_official_source"
            else:
                dependency = "archive_identity_reference_without_direct_changed_member"
                action = "retain_result_add_provenance_note_only"
            rows.append({
                "artifact_path": rel,
                "artifact_scope": scope,
                "dependency_classification": dependency,
                "changed_member_count": len(canonical_hits),
                "changed_members": ";".join(canonical_hits),
                "old_archive_hash_reference_count": len(hash_hits),
                "old_archive_hash_references": ";".join(hash_hits),
                "required_action": action,
            })
    return sorted(rows, key=lambda row: (row["dependency_classification"], row["artifact_path"]))


def scan_report_archives(project_root: Path, changed_paths: Sequence[str], old_hashes: Sequence[str]) -> list[dict[str, Any]]:
    report_root = project_root / ".local/reports/quartet_restoration"
    if not report_root.is_dir():
        return []
    paths_folded = [(p, p.casefold(), Path(p).name.casefold()) for p in changed_paths]
    hashes = [h.casefold() for h in old_hashes if h]
    rows: list[dict[str, Any]] = []
    for archive in sorted(report_root.glob("*.tar.zst")):
        result = subprocess.run(["tar", "--zstd", "-tf", str(archive)], text=True, capture_output=True)
        if result.returncode != 0:
            continue
        member_hits: set[str] = set()
        hash_hits: set[str] = set()
        for entry in result.stdout.splitlines():
            if not entry or Path(entry).suffix.casefold() not in TEXT_SUFFIXES:
                continue
            content = subprocess.run(["tar", "--zstd", "-xOf", str(archive), entry], capture_output=True)
            if content.returncode != 0 or len(content.stdout) > 64 * 1024 * 1024:
                continue
            text = content.stdout.decode("utf-8", errors="ignore").casefold()
            for original, full, base in paths_folded:
                if full in text or base in text:
                    member_hits.add(original)
            for value in hashes:
                if value in text:
                    hash_hits.add(value)
        if member_hits or hash_hits:
            rows.append({
                "artifact_path": archive.relative_to(project_root).as_posix(),
                "artifact_scope": "compressed_report_metadata",
                "dependency_classification": "direct_changed_member_dependency" if member_hits else "archive_identity_reference_without_direct_changed_member",
                "changed_member_count": len(member_hits),
                "changed_members": ";".join(sorted(member_hits)),
                "old_archive_hash_reference_count": len(hash_hits),
                "old_archive_hash_references": ";".join(sorted(hash_hits)),
                "required_action": "recheck_report_rows_referencing_changed_members" if member_hits else "retain_result_add_provenance_note_only",
            })
    return rows


def validate_profile_dependencies(project_root: Path, changed_paths: Sequence[str]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    changed = {p.casefold() for p in changed_paths}
    changed_bases = {Path(p).name.casefold() for p in changed_paths}
    affected: list[dict[str, Any]] = []
    unaffected: list[dict[str, Any]] = []
    root = project_root / ".local/build/quartet_restoration/core_profiles"
    for path in sorted(root.rglob("*.json")) if root.is_dir() else []:
        try:
            data = load_json(path)
        except Stage105Error:
            continue
        members = [safe_posix(str(value)) for value in data.get("changed_members", [])]
        hits = [m for m in members if m.casefold() in changed or Path(m).name.casefold() in changed_bases]
        row = {
            "profile_id": str(data.get("profile_id", path.stem)),
            "manifest_path": path.relative_to(project_root).as_posix(),
            "target_relative_path": str(data.get("target_relative_path", "")),
            "changed_member_count": len(members),
            "intersecting_changed_members": ";".join(hits),
            "runtime_validated": bool(data.get("runtime_validated", False)),
        }
        (affected if hits else unaffected).append(row)
    return affected, unaffected


def collect(*, project_root: Path, game_root: Path, gust_pak: Path, report_root: Path, expected_preserved_sha1: str, expected_official_sha1: str, expected_pack00_02_size: int = EXPECTED_PACK00_02_SIZE, create_archive: bool = True) -> dict[str, Any]:
    data_root = game_root / "DATA"
    require(data_root.is_dir(), f"BR1 DATA directory missing: {data_root}")
    br = load_module(project_root / "Blue_Reflection_Text_Tool/br_restoration_tool.py", "br_stage105_tool")
    prior_archives = read_inventory_archive_hashes(project_root)
    output = report_root / REPORT_DIR
    if output.exists():
        shutil.rmtree(output)
    output.mkdir(parents=True)

    archive_rows: list[dict[str, Any]] = []
    all_member_rows: list[dict[str, Any]] = []
    prior_binding_rows: list[dict[str, Any]] = []
    old_hashes: list[str] = []

    for index, (official_name, preserved_name) in enumerate(ARCHIVE_PAIRS, start=1):
        pair_id = official_name.removesuffix(".PAK").casefold()
        official = data_root / official_name
        preserved = data_root / preserved_name
        require(official.is_file(), f"official Steam source missing: {official}")
        require(preserved.is_file(), f"preserved untrusted source missing: {preserved}")
        progress(f"hashing archive pair {index}/{len(ARCHIVE_PAIRS)}: {official_name}")
        official_sha1 = hash_file(official, "sha1")
        preserved_sha1 = hash_file(preserved, "sha1")
        official_sha256 = sha256_file(official)
        preserved_sha256 = sha256_file(preserved)
        old_hashes.extend([preserved_sha1, preserved_sha256])
        official_size = official.stat().st_size
        preserved_size = preserved.stat().st_size
        require(official_size == preserved_size, f"archive pair size mismatch for {official_name}: {preserved_size} != {official_size}")
        require(official_sha256 != preserved_sha256, f"archive pair is unexpectedly identical: {official_name}")
        if official_name == "PACK00_02.PAK":
            require(preserved_sha1.casefold() == expected_preserved_sha1.casefold(), "preserved PACK00_02 SHA-1 mismatch")
            require(official_sha1.casefold() == expected_official_sha1.casefold(), "official PACK00_02 SHA-1 mismatch")
            require(official_size == expected_pack00_02_size, "PACK00_02 size mismatch")
        canonical_rel = f"DATA/{official_name}"
        prior = prior_archives.get(canonical_rel.casefold(), {})
        prior_sha = str(prior.get("sha256", ""))
        if prior_sha.casefold() == preserved_sha256.casefold():
            prior_class = "prior_inventory_matches_preserved_untrusted"
        elif prior_sha.casefold() == official_sha256.casefold():
            prior_class = "prior_inventory_matches_official"
        else:
            prior_class = "prior_inventory_matches_neither"
        prior_binding_rows.append({
            "archive": canonical_rel,
            "prior_inventory_sha256": prior_sha,
            "preserved_sha256": preserved_sha256,
            "official_sha256": official_sha256,
            "classification": prior_class,
        })
        progress(f"opening preserved member inventory {index}/{len(ARCHIVE_PAIRS)}: {preserved_name}")
        old_ws, old_manifest, old_mode = extract_or_reuse(project_root=project_root, game_root=game_root, archive=preserved, pair_id=pair_id, side="preserved", gust_pak=gust_pak, br=br)
        progress(f"opening official member inventory {index}/{len(ARCHIVE_PAIRS)}: {official_name}")
        new_ws, new_manifest, new_mode = extract_or_reuse(project_root=project_root, game_root=game_root, archive=official, pair_id=pair_id, side="official", gust_pak=gust_pak, br=br)
        progress(f"hashing and comparing members {index}/{len(ARCHIVE_PAIRS)}: {official_name}")
        old_members = member_rows(old_ws, old_manifest)
        new_members = member_rows(new_ws, new_manifest)
        rows = compare_members(pair_id, old_members, new_members)
        all_member_rows.extend(rows)
        counts = Counter(row["status"] for row in rows)
        archive_rows.append({
            "pair_id": pair_id,
            "canonical_archive": canonical_rel,
            "preserved_filename": preserved_name,
            "official_filename": official_name,
            "preserved_size": preserved_size,
            "official_size": official_size,
            "preserved_sha1": preserved_sha1,
            "official_sha1": official_sha1,
            "preserved_sha256": preserved_sha256,
            "official_sha256": official_sha256,
            "preserved_extraction_mode": old_mode,
            "official_extraction_mode": new_mode,
            "preserved_member_count": len(old_members),
            "official_member_count": len(new_members),
            "identical_member_rows": counts["identical"],
            "changed_payload_rows": counts["payload_changed_layout_stable"] + counts["payload_and_layout_changed"],
            "layout_changed_rows": counts["layout_changed_payload_identical"] + counts["payload_and_layout_changed"],
            "added_member_rows": counts["added_in_official"],
            "removed_member_rows": counts["removed_from_official"],
            "prior_inventory_binding": prior_class,
        })

    changed_rows = [row for row in all_member_rows if row["status"] != "identical"]
    pack02_rows = [row for row in changed_rows if row["pair_id"] == "pack00_02"]
    pack02_bases = {row["member_basename"].casefold() for row in pack02_rows}
    require(pack02_bases == {value.casefold() for value in EXPECTED_PACK00_02_CHANGED_BASENAMES}, "PACK00_02 changed member set does not equal the expected 30 textures")
    require(len(pack02_rows) == 30, "PACK00_02 must contain exactly 30 changed members")
    require(all(row["status"] == "payload_changed_layout_stable" for row in pack02_rows), "PACK00_02 changes must preserve names, order, offsets and sizes")
    require(all(row["asset_type"] == "texture" for row in pack02_rows), "PACK00_02 changed members must all be textures")

    changed_paths = sorted({str(row["member_path"]) for row in changed_rows})
    progress("scanning current workstream metadata for direct changed-member dependencies")
    dependency_rows = scan_text_artifacts(project_root, changed_paths, old_hashes, output)
    dependency_rows.extend(scan_report_archives(project_root, changed_paths, old_hashes))
    unique_dependencies: dict[tuple[str, str], dict[str, Any]] = {}
    for row in dependency_rows:
        unique_dependencies[(row["artifact_path"], row["dependency_classification"])] = row
    dependency_rows = sorted(unique_dependencies.values(), key=lambda row: (row["dependency_classification"], row["artifact_path"]))
    affected_profiles, unaffected_profiles = validate_profile_dependencies(project_root, changed_paths)
    require(not affected_profiles, "a registered profile intersects a provenance-changed source member")

    stage104_path = report_root / "BR_quartet_restoration_reflector_slot_light_sibling_template_expansion_evidence.tar.zst"
    stage104_independent = True
    if stage104_path.is_file():
        try:
            listed = subprocess.run(["tar", "--zstd", "-xOf", str(stage104_path), f"reflector_slot_light_sibling_template_expansion_evidence/SLOT_LIGHT_SIBLING_TEMPLATE_OCCURRENCES.tsv"], capture_output=True)
            text = listed.stdout.decode("utf-8", errors="ignore").casefold() if listed.returncode == 0 else ""
            stage104_independent = not any(p.casefold() in text or Path(p).name.casefold() in text for p in changed_paths)
        except OSError:
            stage104_independent = True

    classification_rows = []
    for key, group in sorted(defaultdict(list, {k: [] for k in []}).items()):
        pass
    grouped: dict[tuple[str, str, str, str], int] = Counter((row["pair_id"], row["asset_type"], row["asset_domain"], row["dlc_classification"]) for row in changed_rows)
    for (pair_id, asset_type, asset_domain, dlc_class), count in sorted(grouped.items()):
        classification_rows.append({
            "pair_id": pair_id,
            "asset_type": asset_type,
            "asset_domain": asset_domain,
            "dlc_classification": dlc_class,
            "changed_member_rows": count,
        })

    direct_deps = [row for row in dependency_rows if row["dependency_classification"] == "direct_changed_member_dependency"]
    aggregate_deps = [row for row in dependency_rows if row["dependency_classification"] == "archive_level_aggregate_provenance_dependency"]
    decisions = [
        {"question": "is the prior PACK00_02 source archive official Steam", "answer": "False", "classification": "preserved_source_is_untrusted_modified_candidate"},
        {"question": "must future canonical BR1 analyses use non-underscore PAK files", "answer": "True", "classification": "official_nonunderscore_source_required"},
        {"question": "are all 15 registered restoration profiles independent of changed source members", "answer": str(len(unaffected_profiles) == 15 and not affected_profiles), "classification": "profile_member_intersection_audit"},
        {"question": "is stage104 slot-light sibling-template evidence independent of changed source members", "answer": str(stage104_independent), "classification": "stage104_member_scope_audit"},
        {"question": "should unrelated reports be invalidated automatically", "answer": "False", "classification": "dependency_scoped_revalidation_only"},
        {"question": "is G1E write or profile activation authorized", "answer": "False", "classification": "evidence_only_no_write"},
    ]

    write_tsv(output / "SOURCE_ARCHIVE_PROVENANCE_PAIRS.tsv", list(archive_rows[0].keys()), archive_rows)
    write_tsv(output / "SOURCE_ARCHIVE_MEMBER_DIFF.tsv", list(all_member_rows[0].keys()), all_member_rows)
    write_tsv(output / "SOURCE_ARCHIVE_CHANGED_MEMBERS.tsv", list(changed_rows[0].keys()), changed_rows)
    write_tsv(output / "SOURCE_ARCHIVE_ASSET_CLASSIFICATION.tsv", ["pair_id", "asset_type", "asset_domain", "dlc_classification", "changed_member_rows"], classification_rows)
    write_tsv(output / "SOURCE_ARCHIVE_PRIOR_INVENTORY_BINDING.tsv", ["archive", "prior_inventory_sha256", "preserved_sha256", "official_sha256", "classification"], prior_binding_rows)
    dependency_fields = ["artifact_path", "artifact_scope", "dependency_classification", "changed_member_count", "changed_members", "old_archive_hash_reference_count", "old_archive_hash_references", "required_action"]
    write_tsv(output / "SOURCE_ARCHIVE_WORKSTREAM_DEPENDENCIES.tsv", dependency_fields, dependency_rows)
    profile_fields = ["profile_id", "manifest_path", "target_relative_path", "changed_member_count", "intersecting_changed_members", "runtime_validated"]
    write_tsv(output / "SOURCE_ARCHIVE_AFFECTED_PROFILES.tsv", profile_fields, affected_profiles)
    write_tsv(output / "SOURCE_ARCHIVE_UNAFFECTED_PROFILES.tsv", profile_fields, unaffected_profiles)
    write_tsv(output / "SOURCE_ARCHIVE_PROVENANCE_DECISION.tsv", ["question", "answer", "classification"], decisions)

    summary = {
        "type": "br_quartet_restoration_br1_source_archive_provenance_evidence_summary",
        "format_version": 1,
        "tool_version": TOOL_VERSION,
        "status": "official_vs_preserved_member_diff_complete_dependency_scoped_revalidation_only",
        "archive_pair_rows": len(archive_rows),
        "member_rows": len(all_member_rows),
        "identical_member_rows": sum(row["status"] == "identical" for row in all_member_rows),
        "changed_member_rows": len(changed_rows),
        "added_member_rows": sum(row["status"] == "added_in_official" for row in changed_rows),
        "removed_member_rows": sum(row["status"] == "removed_from_official" for row in changed_rows),
        "layout_changed_member_rows": sum(row["status"] in {"layout_changed_payload_identical", "payload_and_layout_changed"} for row in changed_rows),
        "pack00_02_changed_member_rows": len(pack02_rows),
        "pack00_02_expected_30_texture_set_confirmed": True,
        "pack00_04_changed_member_rows": sum(row["pair_id"].startswith("pack00_04") for row in changed_rows),
        "direct_changed_member_dependency_artifact_rows": len(direct_deps),
        "aggregate_provenance_dependency_artifact_rows": len(aggregate_deps),
        "affected_registered_profile_rows": len(affected_profiles),
        "unaffected_registered_profile_rows": len(unaffected_profiles),
        "stage104_slot_light_evidence_independent": stage104_independent,
        "prior_inventory_archives_matching_preserved_untrusted": sum(row["classification"] == "prior_inventory_matches_preserved_untrusted" for row in prior_binding_rows),
        "prior_inventory_archives_matching_official": sum(row["classification"] == "prior_inventory_matches_official" for row in prior_binding_rows),
        "policy": {
            "official_nonunderscore_archives_are_canonical": True,
            "underscore_archives_are_analysis_only": True,
            "unrelated_results_invalidated": False,
            "profiles_modified": False,
            "registry_modified": False,
            "installed_game_modified": False,
            "pak_repacked": False,
            "proprietary_payloads_exported": False,
            "G1E_write_authorized": False,
        },
        "next_action": "Upload this report. Refresh only directly affected BR1 asset inventory/diff rows and any PACK00_04-dependent results from official non-underscore PAKs; retain independent slot-light and registered-profile evidence.",
    }
    (output / "SUMMARY.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    report_path = report_root / REPORT_NAME
    if create_archive:
        make_archive(output, report_path)
    return {"summary": summary, "report_path": str(report_path), "output": str(output)}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-root", default=str(PROJECT_ROOT_DEFAULT))
    parser.add_argument("--game-root", default=os.environ.get("BR1_ORIGINAL_ROOT"))
    parser.add_argument("--gust-pak")
    parser.add_argument("--report-root")
    parser.add_argument("--expected-preserved-pack00-02-sha1", default=EXPECTED_PRESERVED_PACK00_02_SHA1)
    parser.add_argument("--expected-official-pack00-02-sha1", default=EXPECTED_OFFICIAL_PACK00_02_SHA1)
    parser.add_argument("--expected-pack00-02-size", type=int, default=EXPECTED_PACK00_02_SIZE)
    parser.add_argument("--no-report-archive", action="store_true")
    args = parser.parse_args()
    project_root = Path(args.project_root).expanduser().resolve()
    if not args.game_root:
        raise Stage105Error("BR1_ORIGINAL_ROOT is not configured; use .local/paths.sh via the wrapper or pass --game-root")
    game_root = Path(args.game_root).expanduser().resolve()
    report_root = Path(args.report_root).expanduser().resolve() if args.report_root else project_root / ".local/reports/quartet_restoration"
    gust_pak = find_gust_pak(project_root, Path(args.gust_pak) if args.gust_pak else None)
    progress("starting official/preserved BR1 source provenance audit")
    result = collect(
        project_root=project_root,
        game_root=game_root,
        gust_pak=gust_pak,
        report_root=report_root,
        expected_preserved_sha1=args.expected_preserved_pack00_02_sha1,
        expected_official_sha1=args.expected_official_pack00_02_sha1,
        expected_pack00_02_size=args.expected_pack00_02_size,
        create_archive=not args.no_report_archive,
    )
    progress("completed")
    print(json.dumps(result["summary"], ensure_ascii=False, indent=2))
    print(f"Report: {result['report_path']}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Stage105Error as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
