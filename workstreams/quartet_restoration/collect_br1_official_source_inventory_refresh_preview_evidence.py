#!/usr/bin/env python3
"""Build a dependency-scoped preview for refreshing BR1 source metadata.

Stage 106 consumes the completed stage-105 provenance report and the existing
Original/Quartet inventories, difference report, and review queues. It does not
rewrite any existing report. Instead it emits metadata-only replacement rows for
the four official non-underscore PAK archives and the 33 members whose payloads
differ from the preserved underscore copies.

The stage is deliberately fail-closed: it requires the exact stage-105 scope,
verifies that current source inventory rows still match the preserved hashes,
and refuses to authorize PAK writes, profile changes, registry changes, or
automatic semantic conclusions.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import subprocess
import sys
import tempfile
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT_DEFAULT = SCRIPT_DIR.parent.parent
TOOL_VERSION = "0.1.20"
REPORT_NAME = "BR_quartet_restoration_br1_official_source_inventory_refresh_preview_evidence.tar.zst"
REPORT_DIR = "br1_official_source_inventory_refresh_preview_evidence"
STAGE105_REPORT_NAME = "BR_quartet_restoration_br1_source_archive_provenance_evidence.tar.zst"
EXPECTED_ARCHIVES = {
    "pack00_02": "DATA/PACK00_02.PAK",
    "pack00_04_1": "DATA/PACK00_04_1.PAK",
    "pack00_04_2": "DATA/PACK00_04_2.PAK",
    "pack00_04_3": "DATA/PACK00_04_3.PAK",
}
QUEUE_FILES = (
    "REVIEW_QUEUE.tsv",
    "FOCUSED_REVIEW_QUEUE.tsv",
    "DEFERRED_QUEUE.tsv",
)


class Stage106Error(RuntimeError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise Stage106Error(message)


def progress(message: str) -> None:
    print(f"[stage106] {message}", file=sys.stderr, flush=True)


def load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise Stage106Error(f"invalid JSON {path}: {exc}") from exc


def read_tsv(path: Path) -> list[dict[str, str]]:
    require(path.is_file(), f"missing TSV: {path}")
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def write_tsv(path: Path, fields: Sequence[str], rows: Iterable[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=list(fields),
            delimiter="\t",
            lineterminator="\n",
            extrasaction="ignore",
        )
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fields})


def safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return default


def make_archive(source: Path, output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(output.name + ".tmp")
    temporary.unlink(missing_ok=True)
    result = subprocess.run(
        ["tar", "--zstd", "-cf", str(temporary), "-C", str(source.parent), source.name],
        text=True,
        capture_output=True,
    )
    require(result.returncode == 0, result.stderr.strip() or "failed to create report archive")
    os.replace(temporary, output)


def extract_report(report: Path, destination: Path) -> Path:
    result = subprocess.run(
        ["tar", "--zstd", "-xf", str(report), "-C", str(destination)],
        text=True,
        capture_output=True,
    )
    require(result.returncode == 0, result.stderr.strip() or f"failed to extract {report}")
    root = destination / "br1_source_archive_provenance_evidence"
    require(root.is_dir(), f"stage-105 report directory missing: {root}")
    return root


def index_inventory_files(inventory: Mapping[str, Any]) -> tuple[dict[tuple[str, str], dict[str, Any]], dict[str, list[dict[str, Any]]]]:
    by_archive_path: dict[tuple[str, str], dict[str, Any]] = {}
    by_comparison: dict[str, list[dict[str, Any]]] = defaultdict(list)
    files = inventory.get("files", [])
    require(isinstance(files, list), "inventory files must be a list")
    for row in files:
        require(isinstance(row, dict), "inventory file row must be an object")
        archive = str(row.get("archive", "")).casefold()
        path = str(row.get("path", "")).replace("\\", "/").casefold()
        require(archive and path, "inventory file row missing archive/path")
        key = (archive, path)
        require(key not in by_archive_path, f"duplicate inventory archive/path row: {key}")
        by_archive_path[key] = dict(row)
        comparison = str(row.get("comparison_key") or row.get("normalized_path") or row.get("path") or "").casefold()
        require(comparison, f"inventory file row missing comparison key: {key}")
        by_comparison[comparison].append(dict(row))
    return by_archive_path, by_comparison


def index_archives(inventory: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    rows: dict[str, dict[str, Any]] = {}
    for row in inventory.get("archives", []):
        archive = str(row.get("archive", "")).casefold()
        require(archive, "inventory archive row missing archive")
        require(archive not in rows, f"duplicate archive row: {archive}")
        rows[archive] = dict(row)
    return rows


def index_differences(report: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    rows: dict[str, dict[str, Any]] = {}
    for row in report.get("entries", []):
        key = str(row.get("normalized_path", "")).casefold()
        require(key, "difference row missing normalized_path")
        require(key not in rows, f"duplicate difference normalized_path: {key}")
        rows[key] = dict(row)
    return rows


def queue_memberships(report_root: Path, changed_paths: set[str]) -> tuple[dict[str, set[str]], list[dict[str, Any]]]:
    memberships: dict[str, set[str]] = defaultdict(set)
    inventory_rows: list[dict[str, Any]] = []
    for filename in QUEUE_FILES:
        path = report_root / filename
        require(path.is_file(), f"missing queue: {path}")
        rows = read_tsv(path)
        hit_count = 0
        for ordinal, row in enumerate(rows):
            blob = "\n".join(str(value) for value in row.values()).replace("\\", "/").casefold()
            for member in changed_paths:
                if member in blob:
                    memberships[member].add(filename)
                    hit_count += 1
        inventory_rows.append({"queue_file": filename, "row_count": len(rows), "changed_member_reference_hits": hit_count})
    return memberships, inventory_rows


def expected_new_classification(official_sha: str, official_size: int, targets: list[dict[str, Any]]) -> tuple[str, int, str, str]:
    if not targets:
        return "removed_in_target", 0, "", ""
    exact = [
        row for row in targets
        if str(row.get("sha256", "")).casefold() == official_sha.casefold()
        and safe_int(row.get("size"), -1) == official_size
    ]
    if exact:
        chosen = exact[0]
        return "identical", len(targets), str(chosen.get("archive", "")), str(chosen.get("sha256", ""))
    chosen = targets[0]
    return "changed", len(targets), str(chosen.get("archive", "")), str(chosen.get("sha256", ""))


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path, default=PROJECT_ROOT_DEFAULT)
    parser.add_argument("--stage105-report", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)

    project_root = args.project_root.resolve()
    report_root = project_root / ".local/reports/quartet_restoration"
    stage105_report = (args.stage105_report or (report_root / STAGE105_REPORT_NAME)).resolve()
    output = (args.output or (report_root / REPORT_NAME)).resolve()
    require(stage105_report.is_file(), f"missing stage-105 report: {stage105_report}")

    source_inventory_path = report_root / "inventories/br1_assets.source.json"
    target_inventory_path = report_root / "inventories/br1_assets.target.json"
    difference_report_path = report_root / "differences/br1_assets.json"
    for path in (source_inventory_path, target_inventory_path, difference_report_path):
        require(path.is_file(), f"missing prior metadata: {path}")

    source_inventory = load_json(source_inventory_path)
    target_inventory = load_json(target_inventory_path)
    difference_report = load_json(difference_report_path)
    source_files, _ = index_inventory_files(source_inventory)
    _, target_by_comparison = index_inventory_files(target_inventory)
    source_archives = index_archives(source_inventory)
    difference_by_path = index_differences(difference_report)

    with tempfile.TemporaryDirectory(prefix="br_stage106_") as temporary:
        temporary_root = Path(temporary)
        stage105_root = extract_report(stage105_report, temporary_root)
        summary105 = load_json(stage105_root / "SUMMARY.json")
        require(summary105.get("tool_version") == "0.1.19", "stage-105 report tool version must be 0.1.19")
        require(safe_int(summary105.get("changed_member_rows")) == 33, "stage-105 report must contain exactly 33 changed members")
        require(safe_int(summary105.get("layout_changed_member_rows")) == 0, "layout-changing members are not supported")
        require(safe_int(summary105.get("affected_registered_profile_rows")) == 0, "stage-105 report contains affected registered profiles")
        require(safe_int(summary105.get("unaffected_registered_profile_rows")) == 15, "stage-105 report must preserve all 15 profiles")
        require(bool(summary105.get("stage104_slot_light_evidence_independent")), "stage-104 independence was not confirmed")

        pairs = read_tsv(stage105_root / "SOURCE_ARCHIVE_PROVENANCE_PAIRS.tsv")
        changed = read_tsv(stage105_root / "SOURCE_ARCHIVE_CHANGED_MEMBERS.tsv")
        dependencies = read_tsv(stage105_root / "SOURCE_ARCHIVE_WORKSTREAM_DEPENDENCIES.tsv")
        require(len(pairs) == 4, "expected four provenance archive pairs")
        require(len(changed) == 33, "expected 33 changed member rows")
        pair_by_id = {row["pair_id"]: row for row in pairs}
        require(set(pair_by_id) == set(EXPECTED_ARCHIVES), "unexpected stage-105 archive pair set")

        changed_paths = {row["member_path"].replace("\\", "/").casefold() for row in changed}
        require(len(changed_paths) == 33, "changed member paths must be unique")
        memberships, queue_inventory = queue_memberships(report_root, changed_paths)

        archive_replacements: list[dict[str, Any]] = []
        for pair_id in sorted(EXPECTED_ARCHIVES):
            row = pair_by_id[pair_id]
            canonical = EXPECTED_ARCHIVES[pair_id]
            require(row.get("canonical_archive", "").casefold() == canonical.casefold(), f"canonical archive mismatch for {pair_id}")
            old = source_archives.get(canonical.casefold())
            require(old is not None, f"source inventory missing archive: {canonical}")
            require(str(old.get("sha256", "")).casefold() == row["preserved_sha256"].casefold(), f"source inventory no longer matches preserved archive: {canonical}")
            require(safe_int(old.get("size"), -1) == safe_int(row["preserved_size"], -2), f"source inventory size mismatch: {canonical}")
            archive_replacements.append({
                "pair_id": pair_id,
                "archive": canonical,
                "old_provenance": "preserved_untrusted_candidate",
                "new_provenance": "official_steam_canonical",
                "old_sha1": row["preserved_sha1"],
                "new_sha1": row["official_sha1"],
                "old_sha256": row["preserved_sha256"],
                "new_sha256": row["official_sha256"],
                "old_size": row["preserved_size"],
                "new_size": row["official_size"],
                "member_count": row["official_member_count"],
                "changed_member_count": row["changed_payload_rows"],
                "layout_changed_member_count": row["layout_changed_rows"],
                "required_action": "replace_archive_identity_in_canonical_source_inventory",
            })

        member_replacements: list[dict[str, Any]] = []
        diff_rows: list[dict[str, Any]] = []
        queue_rows: list[dict[str, Any]] = []
        classification_counts: Counter[str] = Counter()
        old_classification_counts: Counter[str] = Counter()
        changed_classification_count = 0

        for row in sorted(changed, key=lambda item: (item["pair_id"], item["member_path"].casefold())):
            pair_id = row["pair_id"]
            canonical = EXPECTED_ARCHIVES[pair_id]
            member_path = row["member_path"].replace("\\", "/")
            member_key = member_path.casefold()
            source_row = source_files.get((canonical.casefold(), member_key))
            require(source_row is not None, f"source inventory missing changed member: {canonical}:{member_path}")
            require(str(source_row.get("sha256", "")).casefold() == row["preserved_sha256"].casefold(), f"source member hash does not match preserved candidate: {member_path}")
            require(safe_int(source_row.get("size"), -1) == safe_int(row["preserved_size"], -2), f"source member size mismatch: {member_path}")
            comparison_key = str(source_row.get("comparison_key") or source_row.get("normalized_path") or member_path).casefold()
            targets = target_by_comparison.get(comparison_key, [])
            new_classification, target_count, target_archive, target_sha = expected_new_classification(
                row["official_sha256"], safe_int(row["official_size"]), targets
            )
            previous = difference_by_path.get(comparison_key)
            old_classification = str(previous.get("classification", "identical")) if previous else "identical"
            classification_counts[new_classification] += 1
            old_classification_counts[old_classification] += 1
            classification_changed = old_classification != new_classification
            if classification_changed:
                changed_classification_count += 1

            queues = sorted(memberships.get(member_key, set()))
            if new_classification == "identical":
                queue_action = "remove_dependent_rows_from_review_and_deferred_queues"
            elif new_classification == "removed_in_target" and row.get("dlc_classification") == "legacy_or_dlc_named":
                queue_action = "refresh_source_provenance_and_retain_deferred_classification"
            elif new_classification == "removed_in_target":
                queue_action = "refresh_source_provenance_and_retain_manual_review"
            else:
                queue_action = "refresh_hashes_and_recompute_priority_without_semantic_inference"

            member_replacements.append({
                "pair_id": pair_id,
                "archive": canonical,
                "member_path": member_path,
                "asset_type": row["asset_type"],
                "asset_domain": row["asset_domain"],
                "dlc_classification": row["dlc_classification"],
                "old_provenance": "preserved_untrusted_candidate",
                "new_provenance": "official_steam_canonical",
                "old_sha256": row["preserved_sha256"],
                "new_sha256": row["official_sha256"],
                "old_size": row["preserved_size"],
                "new_size": row["official_size"],
                "layout_stable": str(row.get("status") == "payload_changed_layout_stable"),
                "comparison_key": comparison_key,
                "required_action": "replace_source_inventory_hash_and_provenance_only",
            })
            diff_rows.append({
                "pair_id": pair_id,
                "member_path": member_path,
                "comparison_key": comparison_key,
                "old_difference_id": str(previous.get("difference_id", "")) if previous else "",
                "canonical_difference_id": str(previous.get("difference_id", "")) if previous else "",
                "old_classification": old_classification,
                "new_classification": new_classification,
                "classification_changed": str(classification_changed),
                "official_source_sha256": row["official_sha256"],
                "target_match_count": target_count,
                "target_archive": target_archive,
                "target_sha256": target_sha,
                "semantic_conclusion": "none_provenance_only",
            })
            queue_rows.append({
                "member_path": member_path,
                "old_queue_memberships": ";".join(queues),
                "old_queue_membership_count": len(queues),
                "new_classification": new_classification,
                "recommended_queue_action": queue_action,
                "automatic_row_write_authorized": "False",
            })

        direct_dependencies = [row for row in dependencies if row.get("dependency_classification") == "direct_changed_member_dependency"]
        archive_identity_dependencies = [row for row in dependencies if row.get("dependency_classification") == "archive_identity_reference_without_direct_changed_member"]
        require(len(direct_dependencies) == safe_int(summary105.get("direct_changed_member_dependency_artifact_rows")), "direct dependency count drifted from stage 105")

        dependency_rows = []
        for row in dependencies:
            dependency_rows.append({
                "artifact_path": row.get("artifact_path", ""),
                "artifact_scope": row.get("artifact_scope", ""),
                "dependency_classification": row.get("dependency_classification", ""),
                "changed_member_count": row.get("changed_member_count", ""),
                "required_action": row.get("required_action", ""),
                "stage106_disposition": (
                    "regenerate_only_dependent_rows_from_official_source"
                    if row.get("dependency_classification") == "direct_changed_member_dependency"
                    else "retain_with_explicit_preserved_archive_provenance_note"
                ),
            })

        preview_patch = {
            "type": "br_quartet_restoration_official_source_inventory_refresh_preview",
            "format_version": 1,
            "tool_version": TOOL_VERSION,
            "source_inventory": str(source_inventory_path.relative_to(project_root)),
            "target_inventory": str(target_inventory_path.relative_to(project_root)),
            "difference_report": str(difference_report_path.relative_to(project_root)),
            "archive_replacements": archive_replacements,
            "member_replacements": member_replacements,
            "difference_reclassifications": diff_rows,
            "queue_revalidation": queue_rows,
            "policy": {
                "preview_only": True,
                "existing_reports_modified": False,
                "official_nonunderscore_archives_are_canonical": True,
                "underscore_archives_are_analysis_only": True,
                "unrelated_results_invalidated": False,
                "registered_profiles_affected": False,
                "stage104_slot_light_evidence_independent": True,
                "pak_write_authorized": False,
                "G1E_write_authorized": False,
            },
        }

        summary = {
            "type": "br_quartet_restoration_br1_official_source_inventory_refresh_preview_evidence_summary",
            "format_version": 1,
            "tool_version": TOOL_VERSION,
            "status": "official_source_metadata_refresh_preview_complete_no_existing_report_write",
            "archive_replacement_rows": len(archive_replacements),
            "member_replacement_rows": len(member_replacements),
            "difference_reclassification_rows": len(diff_rows),
            "classification_changed_rows": changed_classification_count,
            "new_classification_counts": dict(sorted(classification_counts.items())),
            "old_classification_counts": dict(sorted(old_classification_counts.items())),
            "queue_revalidation_rows": len(queue_rows),
            "queue_inventory_rows": len(queue_inventory),
            "direct_dependency_artifact_rows": len(direct_dependencies),
            "archive_identity_note_artifact_rows": len(archive_identity_dependencies),
            "affected_registered_profile_rows": 0,
            "unaffected_registered_profile_rows": 15,
            "stage104_slot_light_evidence_independent": True,
            "policy": preview_patch["policy"],
            "next_action": "Upload this report. Review exact classification/queue changes, then create a separate transactional stage that refreshes only approved metadata rows while retaining preserved underscore provenance records.",
        }

        report_dir = temporary_root / REPORT_DIR
        report_dir.mkdir(parents=True)
        write_tsv(report_dir / "OFFICIAL_SOURCE_ARCHIVE_REPLACEMENTS.tsv", [
            "pair_id", "archive", "old_provenance", "new_provenance", "old_sha1", "new_sha1",
            "old_sha256", "new_sha256", "old_size", "new_size", "member_count",
            "changed_member_count", "layout_changed_member_count", "required_action",
        ], archive_replacements)
        write_tsv(report_dir / "OFFICIAL_SOURCE_MEMBER_REPLACEMENTS.tsv", [
            "pair_id", "archive", "member_path", "asset_type", "asset_domain", "dlc_classification",
            "old_provenance", "new_provenance", "old_sha256", "new_sha256", "old_size", "new_size",
            "layout_stable", "comparison_key", "required_action",
        ], member_replacements)
        write_tsv(report_dir / "OFFICIAL_SOURCE_DIFF_RECLASSIFICATION.tsv", [
            "pair_id", "member_path", "comparison_key", "old_difference_id", "canonical_difference_id",
            "old_classification", "new_classification", "classification_changed", "official_source_sha256",
            "target_match_count", "target_archive", "target_sha256", "semantic_conclusion",
        ], diff_rows)
        write_tsv(report_dir / "OFFICIAL_SOURCE_QUEUE_REVALIDATION.tsv", [
            "member_path", "old_queue_memberships", "old_queue_membership_count", "new_classification",
            "recommended_queue_action", "automatic_row_write_authorized",
        ], queue_rows)
        write_tsv(report_dir / "OFFICIAL_SOURCE_QUEUE_INVENTORY.tsv", [
            "queue_file", "row_count", "changed_member_reference_hits",
        ], queue_inventory)
        write_tsv(report_dir / "OFFICIAL_SOURCE_DEPENDENCY_DISPOSITION.tsv", [
            "artifact_path", "artifact_scope", "dependency_classification", "changed_member_count",
            "required_action", "stage106_disposition",
        ], dependency_rows)
        write_tsv(report_dir / "OFFICIAL_SOURCE_REFRESH_DECISION.tsv", ["question", "answer", "classification"], [
            {"question": "should existing inventory/diff/queue reports be overwritten by this stage", "answer": False, "classification": "preview_only_no_write"},
            {"question": "are official non-underscore archives the canonical BR1 source", "answer": True, "classification": "official_source_required"},
            {"question": "are preserved underscore archives retained for provenance analysis", "answer": True, "classification": "preserved_untrusted_candidate_history"},
            {"question": "are unrelated restoration results invalidated", "answer": False, "classification": "dependency_scoped_refresh_only"},
            {"question": "are any registered profiles affected", "answer": False, "classification": "profile_scope_independent"},
            {"question": "is G1E or PAK write authorized", "answer": False, "classification": "evidence_only_no_write"},
        ])
        (report_dir / "OFFICIAL_SOURCE_CANONICAL_REFRESH_PREVIEW.json").write_text(
            json.dumps(preview_patch, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        (report_dir / "SUMMARY.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")

        make_archive(report_dir, output)

    progress(f"wrote {output}")
    progress(
        f"archives={len(archive_replacements)} members={len(member_replacements)} "
        f"classification_changes={changed_classification_count} profiles_affected=0"
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Stage106Error as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
