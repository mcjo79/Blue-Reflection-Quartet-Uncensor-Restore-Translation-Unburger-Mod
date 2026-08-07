#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import re
import subprocess
from collections import Counter, defaultdict
from pathlib import Path, PurePosixPath
from typing import Any, Iterable, Mapping, Sequence

TOOL_VERSION = "0.1.46"
REPORT_DIR = "coverage_selector_standalone_render_path_audit"
REPORT_ARCHIVE = "BR_quartet_restoration_coverage_selector_standalone_render_path_audit_evidence.tar.zst"

INPUTS = {
    "stage122": (
        "BR_quartet_restoration_scene_effect_member_family_binding_audit_evidence.tar.zst",
        "5fba802fdc5407e5c12a708d612f91da087038bef1d48083cb30ae82da62bc92",
        "scene_effect_member_family_binding_audit/SUMMARY.json",
        "f892f3cd4afcb6daa21a3f3befc062b46b45c5e6adb3bcfe4cbae3b015004982",
    ),
    "reference": (
        "BR_quartet_restoration_reference_evidence.tar.zst",
        "13d99f356570cfb3c00118b42140cf5bcf6409f76a509fcb4ad18beec4156aeb",
        "reference_evidence/SUMMARY.json",
        "b5e7e16aed8432f7d0f26d71a25686ad0b685cd608f59aa1a1503cc1befabd30",
    ),
    "event_identifier": (
        "BR_quartet_restoration_event_identifier_evidence.tar.zst",
        "51746c1b890ca8471b47e8a5d97133d1b1ee9c6aa878d957ceeb7850704e7bf8",
        "event_identifier_evidence/SUMMARY.json",
        "16edd8925c48765761492c529911666bb61e1e1eb68e1fc6d7f197c20131b61b",
    ),
    "presentation_surface": (
        "BR_quartet_restoration_presentation_surface_evidence.tar.zst",
        "bddaebee407abdf200c54bd628ff3baa26bbaa511c1c5ef1bd1140ffc7de116c",
        "presentation_surface_evidence/SUMMARY.json",
        "116726b9ae96b3b62bad1f27ac9efe708017254f80acbc696fcce298573f8771",
    ),
    "shader_effect": (
        "BR_quartet_restoration_shader_effect_evidence.tar.zst",
        "d7cebd3faab63c4ad111551e711519127b0d79765c641a6c691ef8558fb47837",
        "shader_effect_evidence/SUMMARY.json",
        "a80c7ee79ef79877727ce982c2fe11f2e2aa2961f6f145a6c21f8d5c394f01f2",
    ),
    "g1s_prototype": (
        "BR_quartet_restoration_g1s_prototype_evidence.tar.zst",
        "94afca0f69afd0a3ca61d229bdd9803134dfc223196d2629c2f111aeecd5d956",
        "g1s_prototype_evidence/SUMMARY.json",
        "3678af77984c1223626db2674e0b22decae5865a0056d8a765ff6053e25d98d0",
    ),
    "stage127": (
        "BR_quartet_restoration_character_state_g1m_delta_scope_triage_evidence.tar.zst",
        "44fa2bc776a298a7ee7d21a382406fe8f8055fe3db6e627bc9a6b1b51544be63",
        "character_state_g1m_delta_scope_triage_evidence/SUMMARY.json",
        "e6aa80af52f351d9b8388a6530da0f419f2d9bac37867082afb81d0aaae37866",
    ),
}

STANDALONE_PATHS = {
    "data/x64/shader/cwater.g1s",
    "data/x64/shader/cwater2.g1s",
    "data/x64/shader/heightfog.g1s",
    "data/x64/shader/swater.g1s",
    "data/x64/shader/texture/caustics.g1t",
}

FORBIDDEN_EXTENSIONS = (
    ".pak", ".g1e", ".g1em", ".g1m", ".g1s", ".g1t", ".elixir", ".elixir.gz", ".ebd", ".ebm"
)


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def version_tuple(value: str) -> tuple[int, ...]:
    return tuple(int(part) for part in value.split("."))


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_tsv(path: Path) -> list[dict[str, str]]:
    require(path.is_file(), f"missing required TSV: {path}")
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def write_tsv(path: Path, fields: Sequence[str], rows: Iterable[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(fields), delimiter="\t", lineterminator="\n", extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fields})


def atomic_json(path: Path, value: Mapping[str, Any]) -> None:
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def make_archive(source: Path, output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(output.name + ".tmp")
    temporary.unlink(missing_ok=True)
    completed = subprocess.run(
        ["tar", "--zstd", "-cf", str(temporary), "-C", str(source.parent), source.name],
        text=True,
        capture_output=True,
    )
    require(completed.returncode == 0, completed.stderr.strip() or "report archive creation failed")
    os.replace(temporary, output)


def verify_input_reports(report_root: Path) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for key, (archive_name, archive_hash, summary_rel, summary_hash) in INPUTS.items():
        archive = report_root / archive_name
        summary = report_root / summary_rel
        require(archive.is_file(), f"missing prerequisite report: {archive}")
        require(summary.is_file(), f"missing prerequisite summary: {summary}")
        actual_archive = sha256_file(archive)
        actual_summary = sha256_file(summary)
        require(actual_archive == archive_hash, f"unexpected {key} report SHA-256: {actual_archive}")
        require(actual_summary == summary_hash, f"unexpected {key} summary SHA-256: {actual_summary}")
        rows.append({
            "input_id": key,
            "archive_name": archive_name,
            "archive_sha256": actual_archive,
            "summary_path": summary_rel,
            "summary_sha256": actual_summary,
        })
    return rows


def parse_asset_difference(path: Path, wanted_path: str) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    for row in data.get("entries", []):
        if row.get("normalized_path") == wanted_path:
            return row
    raise RuntimeError(f"asset difference row not found: {wanted_path}")


def path_hygiene_hits(workstream: Path) -> tuple[int, list[dict[str, Any]]]:
    patterns = [
        ("posix_home", re.compile(r"/(?:home|Users)/[^/\s\"']+/")),
        ("windows_user", re.compile(r"[A-Za-z]:[\\/]Users[\\/][^\\/\s\"']+[\\/]")),
        ("sandbox_mount", re.compile("/mnt" + "/data/")),
    ]
    hits: list[dict[str, Any]] = []
    scanned = 0
    text_suffixes = {".py", ".sh", ".md", ".json", ".tsv", ".txt", ".toml", ".yaml", ".yml"}
    for path in sorted(workstream.rglob("*")):
        if not path.is_file() or path.suffix.casefold() not in text_suffixes:
            continue
        scanned += 1
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except UnicodeDecodeError:
            continue
        for line_number, line in enumerate(lines, 1):
            for kind, pattern in patterns:
                if pattern.search(line):
                    hits.append({
                        "relative_path": path.relative_to(workstream).as_posix(),
                        "line_number": line_number,
                        "pattern_kind": kind,
                    })
    return scanned, hits


def build_coverage_rows(report_root: Path) -> list[dict[str, Any]]:
    stage122 = read_tsv(report_root / "scene_effect_member_family_binding_audit/COVERAGE_ASSET_SCENE_EFFECT_BINDINGS.tsv")
    candidates = read_tsv(report_root / "reference_evidence/CANDIDATE_ASSET_FAMILIES.tsv")
    reference_hits = read_tsv(report_root / "reference_evidence/REFERENCE_HITS.tsv")
    oid_signatures = read_tsv(report_root / "presentation_surface_evidence/COSTUME_OID_SIGNATURES.tsv")
    numeric_seeds = read_tsv(report_root / "event_identifier_evidence/OID_NUMERIC_IDENTIFIER_SEEDS.tsv")
    name_hashes = read_tsv(report_root / "event_identifier_evidence/NAME_HASH_HYPOTHESES.tsv")
    structural_seeds = read_tsv(report_root / "structural_evidence/DERIVED_IDENTIFIER_SEEDS.tsv")

    candidate_by_id = {row["candidate_id"]: row for row in candidates}
    counts = {
        "reference": Counter(row["candidate_id"] for row in reference_hits),
        "external_reference": Counter(row["candidate_id"] for row in reference_hits if row.get("self_reference") != "yes"),
        "event_reference": Counter(row["candidate_id"] for row in reference_hits if row.get("event_reference") == "yes"),
        "oid_signature": Counter(row["candidate_id"] for row in oid_signatures),
        "numeric_seed": Counter(row["candidate_id"] for row in numeric_seeds),
        "name_hash": Counter(row["candidate_id"] for row in name_hashes),
        "structural_seed": Counter(row["candidate_id"] for row in structural_seeds),
    }

    result: list[dict[str, Any]] = []
    for row in stage122:
        if row["binding_kind"] != "no_exact_focused_path_binding":
            continue
        candidate_id = row["candidate_id"]
        candidate = candidate_by_id[candidate_id]
        unique_oid = counts["oid_signature"][candidate_id]
        numeric = counts["numeric_seed"][candidate_id]
        if unique_oid:
            channel_class = "unique_oid_seed_available_but_no_external_or_event_binding"
            next_action = "scan_structured_selector_tables_and_binary_indices_for_exact_oid_seed_without_semantic_inference"
        else:
            channel_class = "self_structural_identifiers_only_no_unique_oid_or_external_binding"
            next_action = "audit_sibling_costume_state_selector_matrices_and_structured_indices_without_name_or_hash_guessing"
        result.append({
            "candidate_id": candidate_id,
            "token": row["token"],
            "family": row["family"],
            "character_id": row["character_id"],
            "asset_file_rows": int(row["asset_file_rows"]),
            "structural_basis": candidate["structural_basis"],
            "self_reference_rows": counts["reference"][candidate_id],
            "external_direct_name_reference_rows": counts["external_reference"][candidate_id],
            "event_direct_name_reference_rows": counts["event_reference"][candidate_id],
            "unique_oid_signature_rows": unique_oid,
            "numeric_oid_seed_rows": numeric,
            "name_hash_hypothesis_rows": counts["name_hash"][candidate_id],
            "derived_structural_identifier_seed_rows": counts["structural_seed"][candidate_id],
            "exact_event_identifier_hit_rows": 0,
            "exact_scene_costume_binding_rows": 0,
            "selector_channel_classification": channel_class,
            "independent_selector_binding_confirmed": False,
            "runtime_confirmed": False,
            "visual_or_censorship_semantics_confirmed": False,
            "write_authorized": False,
            "next_static_action": next_action,
        })
    return sorted(result, key=lambda item: (item["family"], item["token"]))


def build_render_rows(project_root: Path, report_root: Path, profile_manifest_root: Path | None = None) -> list[dict[str, Any]]:
    path_rows = read_tsv(report_root / "scene_effect_member_family_binding_audit/SCENE_EFFECT_PATH_BINDING_SUMMARY.tsv")
    payload_rows = read_tsv(report_root / "shader_effect_evidence/RENDER_PAYLOADS.tsv")
    dxbc_rows = read_tsv(report_root / "shader_effect_evidence/DXBC_PROGRAM_DIFF.tsv")
    token_rows = read_tsv(report_root / "shader_effect_evidence/RENDER_TECHNICAL_TOKEN_DIFF.tsv")
    prototypes = read_tsv(report_root / "g1s_prototype_evidence/G1S_PROTOTYPES.tsv")

    profiles_root = (profile_manifest_root or (project_root / ".local/build/quartet_restoration/core_profiles")).resolve()
    manifests: list[dict[str, Any]] = []
    if profiles_root.is_dir():
        for path in sorted(profiles_root.rglob("*.json")):
            try:
                value = json.loads(path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, UnicodeDecodeError):
                continue
            if isinstance(value, dict):
                value["_manifest_path"] = path.relative_to(project_root).as_posix()
                manifests.append(value)

    diff_path = report_root / "differences/br1_assets.json"
    result: list[dict[str, Any]] = []
    for base in path_rows:
        path = base["focused_path"]
        if path not in STANDALONE_PATHS:
            continue
        payload = [row for row in payload_rows if row["normalized_path"] == path]
        source_payload = next((row for row in payload if row["side"] == "source"), None)
        target_payload = next((row for row in payload if row["side"] == "target"), None)
        dxbc = [row for row in dxbc_rows if row["normalized_path"] == path]
        tokens = [row for row in token_rows if row["normalized_path"] == path]
        profile_rows = [m for m in manifests if path.replace("data/x64/", "data/b1/x64/") in [str(x).casefold() for x in m.get("changed_members", [])]]
        prototype_rows = [r for r in prototypes if r.get("normalized_path") == path or r.get("shader_path") == path]

        source_size = int(source_payload["payload_size"]) if source_payload else 0
        target_size = int(target_payload["payload_size"]) if target_payload else 0
        source_sha = source_payload["payload_sha256"] if source_payload else ""
        target_sha = target_payload["payload_sha256"] if target_payload else ""
        if path.endswith("caustics.g1t"):
            difference = parse_asset_difference(diff_path, path)
            target = difference.get("target") or {}
            target_size = int(target.get("size", 0))
            target_sha = str(target.get("sha256", ""))

        if profile_rows:
            disposition = "local_reversible_profile_exists_runtime_unvalidated_keep_parked"
        elif path.endswith(".g1s"):
            disposition = "changed_g1s_program_family_no_profile_bounded_format_specific_review_required"
        else:
            disposition = "target_only_caustics_texture_no_source_counterpart_or_selector_binding"

        result.append({
            "candidate_id": base["candidate_id"],
            "focused_path": path,
            "rule_id": base["rule_id"],
            "domain": base["domain"],
            "priority": base["priority"],
            "classification": base["classification"],
            "source_payload_size": source_size,
            "target_payload_size": target_size,
            "source_payload_sha256": source_sha,
            "target_payload_sha256": target_sha,
            "source_dxbc_program_rows": int(source_payload["dxbc_program_count"]) if source_payload else 0,
            "target_dxbc_program_rows": int(target_payload["dxbc_program_count"]) if target_payload else 0,
            "dxbc_program_difference_rows": len(dxbc),
            "vertex_program_difference_rows": sum(1 for row in dxbc if row.get("source_stage") == "vertex"),
            "pixel_program_difference_rows": sum(1 for row in dxbc if row.get("source_stage") == "pixel"),
            "technical_token_difference_rows": len(tokens),
            "profile_manifest_rows": len(profile_rows),
            "profile_ids": ";".join(sorted(str(row.get("profile_id", "")) for row in profile_rows if row.get("profile_id"))),
            "runtime_validated_profile_rows": sum(1 for row in profile_rows if row.get("runtime_validated") is True),
            "prototype_rows": len(prototype_rows),
            "static_disposition": disposition,
            "visual_or_censorship_semantics_confirmed": False,
            "write_authorized": False,
        })
    return sorted(result, key=lambda item: item["focused_path"])


def build_report(
    project_root: Path,
    *,
    report_root: Path | None = None,
    output_report_root: Path | None = None,
    create_archive: bool = True,
    profile_manifest_root: Path | None = None,
) -> tuple[Path | None, dict[str, Any]]:
    project_root = project_root.resolve()
    workstream = project_root / "workstreams/quartet_restoration"
    current_version = (workstream / "VERSION").read_text(encoding="utf-8").strip()
    require(version_tuple(current_version) >= version_tuple(TOOL_VERSION), f"expected quartet_restoration {TOOL_VERSION} or newer, found {current_version}")

    report_root = (report_root or project_root / ".local/reports/quartet_restoration").resolve()
    output_report_root = (output_report_root or report_root).resolve()
    input_rows = verify_input_reports(report_root)

    summary127 = json.loads((report_root / "character_state_g1m_delta_scope_triage_evidence/SUMMARY.json").read_text(encoding="utf-8"))
    require(summary127.get("forbidden_local_path_hit_rows") == 0, "stage-127 path-hygiene gate drift")
    require(summary127.get("visual_or_censorship_semantics_confirmed_rows") == 0, "stage-127 semantics gate drift")
    require(summary127.get("write_authorized_rows") == 0, "stage-127 write gate drift")

    coverage_rows = build_coverage_rows(report_root)
    require(len(coverage_rows) == 19, f"expected 19 unbound coverage families, found {len(coverage_rows)}")
    render_rows = build_render_rows(project_root, report_root, profile_manifest_root)
    require(len(render_rows) == 5, f"expected 5 standalone render paths, found {len(render_rows)}")

    scanned_files, path_hits = path_hygiene_hits(workstream)
    require(not path_hits, f"user-specific or sandbox paths remain in workstream: {len(path_hits)}")

    report_dir = output_report_root / REPORT_DIR
    if report_dir.exists():
        import shutil
        shutil.rmtree(report_dir)
    report_dir.mkdir(parents=True)

    write_tsv(report_dir / "INPUT_HASHES.tsv", ["input_id", "archive_name", "archive_sha256", "summary_path", "summary_sha256"], input_rows)
    write_tsv(
        report_dir / "COVERAGE_SELECTOR_CHANNEL_AUDIT.tsv",
        [
            "candidate_id", "token", "family", "character_id", "asset_file_rows", "structural_basis",
            "self_reference_rows", "external_direct_name_reference_rows", "event_direct_name_reference_rows",
            "unique_oid_signature_rows", "numeric_oid_seed_rows", "name_hash_hypothesis_rows",
            "derived_structural_identifier_seed_rows", "exact_event_identifier_hit_rows",
            "exact_scene_costume_binding_rows", "selector_channel_classification",
            "independent_selector_binding_confirmed", "runtime_confirmed",
            "visual_or_censorship_semantics_confirmed", "write_authorized", "next_static_action",
        ],
        coverage_rows,
    )
    write_tsv(
        report_dir / "STANDALONE_RENDER_PATH_AUDIT.tsv",
        [
            "candidate_id", "focused_path", "rule_id", "domain", "priority", "classification",
            "source_payload_size", "target_payload_size", "source_payload_sha256", "target_payload_sha256",
            "source_dxbc_program_rows", "target_dxbc_program_rows", "dxbc_program_difference_rows",
            "vertex_program_difference_rows", "pixel_program_difference_rows", "technical_token_difference_rows",
            "profile_manifest_rows", "profile_ids", "runtime_validated_profile_rows", "prototype_rows",
            "static_disposition", "visual_or_censorship_semantics_confirmed", "write_authorized",
        ],
        render_rows,
    )
    write_tsv(report_dir / "LOCAL_PATH_HYGIENE_AUDIT.tsv", ["relative_path", "line_number", "pattern_kind"], path_hits)

    family_counts = Counter(row["family"] for row in coverage_rows)
    channel_counts = Counter(row["selector_channel_classification"] for row in coverage_rows)
    summary: dict[str, Any] = {
        "type": "br_quartet_restoration_coverage_selector_standalone_render_path_audit_evidence_summary",
        "format_version": 1,
        "tool_version": TOOL_VERSION,
        "status": "coverage_selector_channels_and_standalone_render_paths_bounded_existing_channels_non_authorizing_no_semantics_no_write",
        "unbound_coverage_family_rows": len(coverage_rows),
        "unbound_coverage_family_counts": dict(sorted(family_counts.items())),
        "coverage_family_channel_classification_counts": dict(sorted(channel_counts.items())),
        "coverage_families_with_unique_oid_seed_rows": sum(1 for row in coverage_rows if row["unique_oid_signature_rows"] > 0),
        "coverage_families_without_unique_oid_seed_rows": sum(1 for row in coverage_rows if row["unique_oid_signature_rows"] == 0),
        "coverage_external_direct_name_binding_rows": sum(row["external_direct_name_reference_rows"] for row in coverage_rows),
        "coverage_event_direct_name_binding_rows": sum(row["event_direct_name_reference_rows"] for row in coverage_rows),
        "coverage_exact_event_identifier_binding_rows": sum(row["exact_event_identifier_hit_rows"] for row in coverage_rows),
        "coverage_exact_scene_costume_binding_rows": sum(row["exact_scene_costume_binding_rows"] for row in coverage_rows),
        "independent_selector_binding_confirmed_rows": sum(1 for row in coverage_rows if row["independent_selector_binding_confirmed"]),
        "standalone_render_path_rows": len(render_rows),
        "standalone_changed_g1s_rows": sum(1 for row in render_rows if row["focused_path"].endswith(".g1s")),
        "standalone_target_only_g1t_rows": sum(1 for row in render_rows if row["focused_path"].endswith(".g1t")),
        "standalone_dxbc_program_difference_rows": sum(row["dxbc_program_difference_rows"] for row in render_rows),
        "standalone_technical_token_difference_rows": sum(row["technical_token_difference_rows"] for row in render_rows),
        "standalone_profile_manifest_rows": sum(row["profile_manifest_rows"] for row in render_rows),
        "standalone_runtime_validated_profile_rows": sum(row["runtime_validated_profile_rows"] for row in render_rows),
        "standalone_paths_with_local_reversible_profile_rows": sum(1 for row in render_rows if row["profile_manifest_rows"] > 0),
        "path_hygiene_scanned_versioned_text_files": scanned_files,
        "forbidden_local_path_hit_rows": len(path_hits),
        "runtime_confirmed_rows": 0,
        "visual_or_censorship_semantics_confirmed_rows": 0,
        "write_authorized_rows": 0,
        "global_discovery_saturation_achieved": False,
        "policy": {
            "existing_evidence_only": True,
            "local_proprietary_payloads_read": False,
            "proprietary_payloads_in_report": False,
            "name_or_hash_hypotheses_treated_as_binding_proof": False,
            "parameter_or_shader_names_used_as_visual_semantics": False,
            "runtime_validation_inferred": False,
            "installed_game_modified": False,
            "pak_built_or_repacked": False,
            "profile_or_registry_modified": False,
            "core_modified": False,
            "translation_modified": False,
            "legacy_dlc_modified": False,
            "git_modified": False,
            "user_specific_paths_in_versioned_workstream_files": False,
        },
        "next_action": "Build one read-only structured-selector collector. For the four item families, scan exact OID seeds through structured binary index/table records. For the fifteen udw2/udw3 families, compare sibling costume-state selector matrices and table occurrences. Audit cwater/cwater2 as one paired shader family and caustics as a target-only texture dependency; keep heightfog and swater parked and runtime-unvalidated. Do not require saves or infer visual semantics.",
    }
    atomic_json(report_dir / "SUMMARY.json", summary)

    archive: Path | None = None
    if create_archive:
        archive = output_report_root / REPORT_ARCHIVE
        make_archive(report_dir, archive)
        listed = subprocess.run(["tar", "--zstd", "-tf", str(archive)], text=True, capture_output=True, check=True).stdout.splitlines()
        require(not any(name.casefold().endswith(FORBIDDEN_EXTENSIONS) for name in listed), "proprietary payload extension in report archive")
    return archive, summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Audit unresolved coverage selector channels and five standalone render paths using existing metadata-only evidence.")
    parser.add_argument("--project-root", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--report-root", type=Path)
    parser.add_argument("--output-report-root", type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    archive, summary = build_report(
        args.project_root,
        report_root=args.report_root,
        output_report_root=args.output_report_root,
        create_archive=True,
    )
    print(json.dumps(summary, indent=2, sort_keys=True))
    if archive:
        print(f"[stage128] report archive: {archive}")
        print(f"[stage128] report SHA-256: {sha256_file(archive)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
