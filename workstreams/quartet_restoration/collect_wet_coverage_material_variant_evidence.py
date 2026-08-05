#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import shutil
import subprocess
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable

TOOL_VERSION = "0.0.84"
REPORT_NAME = "BR_quartet_restoration_wet_coverage_material_variant_evidence.tar.zst"
REPORT_DIR = "wet_coverage_material_variant_evidence"
REGISTRY_DIR = "core_profile_manifest_evidence"
MATERIAL_DIR = "material_delta_evidence"

HIGH_VALUE_PARAMETERS = {
    "frpalphathres",
    "frrrefractiveindex",
    "frrtransparency",
    "ftranslucency",
}
FOCUSED_DOMAINS = {
    "water_visibility",
    "steam_and_water_visibility",
    "steam_and_wet_clothing",
    "steam_or_vapor_occlusion",
    "wet_fabric_material_response",
    "costume_or_coverage",
    "clothing_state",
    "underwear",
    "nudity_or_body_coverage",
    "wet_clothing",
}
FOCUS_KEYWORDS = {
    "alpha", "opacity", "transparent", "transparency", "translucency",
    "refract", "refraction", "water", "wet", "steam", "vapor", "mist",
    "fog", "blend", "coverage", "cloth", "fabric", "skin", "body",
}
DIRECT_CHANGED = {"changed"}
DIRECT_STRUCTURAL = {"added_in_target", "removed_in_target"}
VARIANT_SPECIFIC = {"variant_specific_change", "variant_only_parameter"}


class MaterialVariantEvidenceError(RuntimeError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise MaterialVariantEvidenceError(message)


def load_json(path: Path) -> dict[str, Any]:
    require(path.is_file(), f"missing required JSON: {path}")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise MaterialVariantEvidenceError(f"cannot read JSON {path}: {exc}") from exc
    require(isinstance(data, dict), f"JSON root must be an object: {path}")
    return data


def read_tsv(path: Path) -> list[dict[str, str]]:
    require(path.is_file(), f"missing required TSV: {path}")
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def write_tsv(path: Path, fields: list[str], rows: Iterable[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=fields,
            delimiter="\t",
            lineterminator="\n",
            extrasaction="ignore",
        )
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fields})


def atomic_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    temporary.replace(path)


def bool_value(value: Any) -> bool:
    return str(value).strip().casefold() in {"1", "true", "yes", "passed"}


def folded(value: Any) -> str:
    return str(value or "").strip().casefold()


def split_tokens(value: Any) -> set[str]:
    text = folded(value)
    for separator in (";", "|", " "):
        text = text.replace(separator, ",")
    return {item.strip() for item in text.split(",") if item.strip()}


def focus_hits(row: dict[str, str]) -> set[str]:
    hits = split_tokens(row.get("keyword_hits", ""))
    haystack = " ".join(
        folded(row.get(key, ""))
        for key in (
            "parameter_name", "domain", "source_archive_path", "target_archive_path",
            "original_base_archive_path", "quartet_base_archive_path",
            "quartet_variant_archive_path", "source_member_name", "target_member_name",
            "quartet_variant_member_name", "candidate_token", "counterpart_token",
        )
    )
    hits.update(keyword for keyword in FOCUS_KEYWORDS if keyword in haystack)
    return hits


def stable_id(prefix: str, parts: Iterable[Any], length: int = 16) -> str:
    payload = "\0".join(str(part or "") for part in parts).encode("utf-8")
    return f"{prefix}_{hashlib.sha256(payload).hexdigest()[:length]}"


def validate_registry(report_root: Path) -> dict[str, Any]:
    summary = load_json(report_root / REGISTRY_DIR / "SUMMARY.json")
    require(
        summary.get("type") == "br_quartet_restoration_core_profile_manifest_evidence_summary",
        "core report has unexpected type",
    )
    require(int(summary.get("profile_rows", -1)) == 15, "core report must contain 15 profiles")
    require(int(summary.get("pack11_profile_rows", -1)) == 12, "core report must contain 12 PACK11 profiles")
    require(int(summary.get("pack10_01_profile_rows", -1)) == 2, "core report must contain 2 PACK10_01 profiles")
    require(int(summary.get("pack10_03_profile_rows", -1)) == 1, "core report must contain 1 PACK10_03 profile")
    require(int(summary.get("runtime_validated_profile_rows", -1)) == 0, "registry profiles must remain runtime-unvalidated")
    return summary


def validate_material_report(report_root: Path) -> dict[str, Any]:
    summary = load_json(report_root / MATERIAL_DIR / "SUMMARY.json")
    require(
        summary.get("type") == "br_quartet_restoration_material_delta_evidence_summary",
        "material report has unexpected type",
    )
    require(int(summary.get("focused_review_rows", -1)) >= 0, "material report focused row count is invalid")
    require(int(summary.get("skipped_rows", -1)) >= 0, "material report skipped row count is invalid")
    return summary


def row_scope(row: dict[str, str]) -> tuple[bool, set[str]]:
    parameter = folded(row.get("parameter_name"))
    domain = folded(row.get("domain"))
    hits = focus_hits(row)
    high_value = parameter in HIGH_VALUE_PARAMETERS
    focused_domain = domain in FOCUSED_DOMAINS
    named_focus = bool(hits)
    explicit_hits = split_tokens(row.get("keyword_hits", ""))
    generic_mesh_blend = parameter == "parameterformeshblend" and not high_value and not explicit_hits
    return (not generic_mesh_blend and (high_value or named_focus or focused_domain)), hits


def direct_locator(row: dict[str, str]) -> str:
    return "|".join(
        str(row.get(key, ""))
        for key in (
            "target_archive_path", "target_member_name", "target_shader_block_index",
            "target_parameter_index", "parameter_name", "buffer_type", "buffer_count",
        )
    )


def normalize_row(row: dict[str, str], index: int) -> dict[str, Any]:
    evidence_kind = str(row.get("evidence_kind", ""))
    classification = str(row.get("classification", ""))
    parameter = str(row.get("parameter_name", ""))
    parameter_folded = parameter.casefold()
    relation = str(row.get("relation", ""))
    in_scope, hits = row_scope(row)
    source_hex = str(row.get("source_value_hex", ""))
    target_hex = str(row.get("target_value_hex", ""))
    direct_changed = (
        in_scope
        and evidence_kind == "semantic_pair"
        and relation == "original_scene_vs_quartet_scene"
        and classification in DIRECT_CHANGED
    )
    direct_structural = (
        in_scope
        and evidence_kind == "semantic_pair"
        and relation == "original_scene_vs_quartet_scene"
        and classification in DIRECT_STRUCTURAL
    )
    direct_value_ready = (
        direct_changed
        and bool(source_hex)
        and bool(target_hex)
        and len(source_hex) == len(target_hex)
        and bool(row.get("source_member_name"))
        and bool(row.get("target_member_name"))
        and bool(row.get("source_archive_path"))
        and bool(row.get("target_archive_path"))
        and bool(row.get("target_parameter_index"))
        and bool(row.get("target_shader_block_index"))
    )
    variant_specific = (
        in_scope
        and evidence_kind == "three_way_variant"
        and classification in VARIANT_SPECIFIC
    )

    if direct_value_ready:
        disposition = "direct_numeric_restore_candidate_ready_for_occurrence_validation"
    elif direct_structural:
        disposition = "direct_material_structure_change_requires_format_aware_rebuild"
    elif direct_changed:
        disposition = "direct_numeric_change_missing_stable_locator_or_equal_width_value"
    elif variant_specific:
        disposition = "quartet_variant_specific_material_review_candidate"
    elif in_scope:
        disposition = "focused_material_evidence_only"
    else:
        disposition = "out_of_scope_generic_material_change"

    group_parts = (
        evidence_kind,
        row.get("context_id", ""),
        relation,
        row.get("target_archive_path") or row.get("quartet_variant_archive_path", ""),
        row.get("target_member_name") or row.get("quartet_variant_member_name", ""),
    )
    group_id = stable_id("materialgroup", group_parts)
    row_id = stable_id(
        "materialrow",
        (*group_parts, parameter, row.get("target_shader_block_index", ""), row.get("target_parameter_index", ""), index),
    )
    return {
        "row_id": row_id,
        "group_id": group_id,
        "source_row_index": index,
        "evidence_kind": evidence_kind,
        "review_priority": row.get("review_priority", ""),
        "review_basis": row.get("review_basis", ""),
        "relation": relation,
        "context_id": row.get("context_id", ""),
        "domain": row.get("domain", ""),
        "priority": row.get("priority", ""),
        "pair_id": row.get("pair_id", ""),
        "candidate_token": row.get("candidate_token", ""),
        "counterpart_token": row.get("counterpart_token", ""),
        "source_archive_path": row.get("source_archive_path", ""),
        "target_archive_path": row.get("target_archive_path", ""),
        "quartet_variant_archive_path": row.get("quartet_variant_archive_path", ""),
        "source_member_name": row.get("source_member_name", ""),
        "target_member_name": row.get("target_member_name", ""),
        "quartet_variant_member_name": row.get("quartet_variant_member_name", ""),
        "parameter_name": parameter,
        "parameter_name_folded": parameter_folded,
        "buffer_type": row.get("buffer_type", ""),
        "buffer_count": row.get("buffer_count", ""),
        "source_shader_block_index": row.get("source_shader_block_index", ""),
        "target_shader_block_index": row.get("target_shader_block_index", ""),
        "source_parameter_index": row.get("source_parameter_index", ""),
        "target_parameter_index": row.get("target_parameter_index", ""),
        "source_value_text": row.get("source_value_text", ""),
        "target_value_text": row.get("target_value_text", ""),
        "source_value_hex": source_hex,
        "target_value_hex": target_hex,
        "original_base_values": row.get("original_base_values", ""),
        "quartet_base_values": row.get("quartet_base_values", ""),
        "quartet_variant_values": row.get("quartet_variant_values", ""),
        "original_base_value_hex": row.get("original_base_value_hex", ""),
        "quartet_base_value_hex": row.get("quartet_base_value_hex", ""),
        "quartet_variant_value_hex": row.get("quartet_variant_value_hex", ""),
        "classification": classification,
        "matching_basis": row.get("matching_basis", ""),
        "normalized_distance": row.get("normalized_distance", ""),
        "keyword_hits": ";".join(sorted(hits)),
        "high_value_parameter": parameter_folded in HIGH_VALUE_PARAMETERS,
        "focused_domain": folded(row.get("domain")) in FOCUSED_DOMAINS,
        "in_scope": in_scope,
        "direct_value_ready": direct_value_ready,
        "direct_locator": direct_locator(row) if direct_value_ready else "",
        "disposition": disposition,
        "runtime_validated": False,
        "semantics_inferred": False,
    }


def build_groups(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        if row["in_scope"]:
            grouped[str(row["group_id"])].append(row)

    output: list[dict[str, Any]] = []
    for group_id, members in sorted(grouped.items()):
        direct = [row for row in members if row["direct_value_ready"]]
        structural = [row for row in members if row["disposition"] == "direct_material_structure_change_requires_format_aware_rebuild"]
        variant = [row for row in members if row["disposition"] == "quartet_variant_specific_material_review_candidate"]
        locators = Counter(str(row["direct_locator"]) for row in direct)
        duplicate_locator_rows = sum(count - 1 for count in locators.values() if count > 1)
        source_values_by_locator: dict[str, set[str]] = defaultdict(set)
        for row in direct:
            source_values_by_locator[str(row["direct_locator"])].add(str(row["source_value_hex"]))
        conflicting_locator_count = sum(1 for values in source_values_by_locator.values() if len(values) > 1)
        if direct and not structural and not duplicate_locator_rows and not conflicting_locator_count:
            status = "direct_numeric_member_candidate_ready_for_binary_occurrence_audit"
        elif direct:
            status = "direct_numeric_member_candidate_blocked_by_group_conflict_or_structure"
        elif variant:
            status = "variant_specific_material_member_review_only"
        else:
            status = "focused_material_member_evidence_only"
        first = members[0]
        archive = first.get("target_archive_path") or first.get("quartet_variant_archive_path", "")
        member = first.get("target_member_name") or first.get("quartet_variant_member_name", "")
        output.append({
            "group_id": group_id,
            "context_id": first.get("context_id", ""),
            "domain": first.get("domain", ""),
            "relation": first.get("relation", ""),
            "archive_path": archive,
            "member_name": member,
            "focused_row_count": len(members),
            "high_value_row_count": sum(bool(row["high_value_parameter"]) for row in members),
            "direct_value_candidate_rows": len(direct),
            "structural_change_rows": len(structural),
            "variant_specific_rows": len(variant),
            "duplicate_locator_rows": duplicate_locator_rows,
            "conflicting_locator_count": conflicting_locator_count,
            "candidate_parameter_names": ";".join(sorted({str(row["parameter_name"]) for row in direct})),
            "candidate_row_ids": ";".join(str(row["row_id"]) for row in direct),
            "classification": status,
            "safe_to_build_payload_now": False,
            "next_gate": (
                "rehydrate_exact_g1m_member_and_validate_parameter_occurrences_then_exact_reverse_roundtrip"
                if status == "direct_numeric_member_candidate_ready_for_binary_occurrence_audit"
                else "retain_metadata_and_resolve_group_conflicts_or_variant_binding"
            ),
        })
    return output


def build_report(project_root: Path, *, create_archive: bool = True) -> tuple[Path, Path | None, dict[str, Any]]:
    report_root = project_root / ".local/reports/quartet_restoration"
    registry_summary = validate_registry(report_root)
    material_summary = validate_material_report(report_root)
    focused_path = report_root / MATERIAL_DIR / "FOCUSED_MATERIAL_REVIEW.tsv"
    source_rows = read_tsv(focused_path)
    require(
        len(source_rows) == int(material_summary.get("focused_review_rows", len(source_rows))),
        "material focused TSV row count does not match SUMMARY.json",
    )

    normalized = [normalize_row(row, index) for index, row in enumerate(source_rows)]
    in_scope = [row for row in normalized if row["in_scope"]]
    direct = [row for row in in_scope if row["direct_value_ready"]]
    structural = [row for row in in_scope if row["disposition"] == "direct_material_structure_change_requires_format_aware_rebuild"]
    variants = [row for row in in_scope if row["disposition"] == "quartet_variant_specific_material_review_candidate"]
    groups = build_groups(normalized)
    ready_groups = [row for row in groups if row["classification"] == "direct_numeric_member_candidate_ready_for_binary_occurrence_audit"]

    output = report_root / REPORT_DIR
    if output.exists():
        shutil.rmtree(output)
    output.mkdir(parents=True)

    row_fields = [
        "row_id", "group_id", "source_row_index", "evidence_kind", "review_priority", "review_basis",
        "relation", "context_id", "domain", "priority", "pair_id", "candidate_token", "counterpart_token",
        "source_archive_path", "target_archive_path", "quartet_variant_archive_path",
        "source_member_name", "target_member_name", "quartet_variant_member_name",
        "parameter_name", "parameter_name_folded", "buffer_type", "buffer_count",
        "source_shader_block_index", "target_shader_block_index", "source_parameter_index", "target_parameter_index",
        "source_value_text", "target_value_text", "source_value_hex", "target_value_hex",
        "original_base_values", "quartet_base_values", "quartet_variant_values",
        "original_base_value_hex", "quartet_base_value_hex", "quartet_variant_value_hex",
        "classification", "matching_basis", "normalized_distance", "keyword_hits",
        "high_value_parameter", "focused_domain", "in_scope", "direct_value_ready", "direct_locator",
        "disposition", "runtime_validated", "semantics_inferred",
    ]
    write_tsv(output / "WET_COVERAGE_MATERIAL_ROWS.tsv", row_fields, in_scope)
    write_tsv(output / "DIRECT_NUMERIC_RESTORE_CANDIDATES.tsv", row_fields, direct)
    write_tsv(output / "STRUCTURAL_MATERIAL_CHANGES.tsv", row_fields, structural)
    write_tsv(output / "THREE_WAY_VARIANT_REVIEW.tsv", row_fields, variants)
    group_fields = [
        "group_id", "context_id", "domain", "relation", "archive_path", "member_name",
        "focused_row_count", "high_value_row_count", "direct_value_candidate_rows",
        "structural_change_rows", "variant_specific_rows", "duplicate_locator_rows",
        "conflicting_locator_count", "candidate_parameter_names", "candidate_row_ids",
        "classification", "safe_to_build_payload_now", "next_gate",
    ]
    write_tsv(output / "MATERIAL_MEMBER_GROUPS.tsv", group_fields, groups)
    write_tsv(
        output / "MATERIAL_VARIANT_SKIPPED.tsv",
        ["source_row_index", "reason", "parameter_name", "domain", "classification"],
        [
            {
                "source_row_index": row["source_row_index"],
                "reason": row["disposition"],
                "parameter_name": row["parameter_name"],
                "domain": row["domain"],
                "classification": row["classification"],
            }
            for row in normalized
            if not row["in_scope"]
        ],
    )

    counts = Counter(str(row["disposition"]) for row in normalized)
    summary = {
        "type": "br_quartet_restoration_wet_coverage_material_variant_evidence_summary",
        "format_version": 1,
        "tool_version": TOOL_VERSION,
        "source_registry_tool_version": registry_summary.get("tool_version"),
        "source_material_delta_tool_version": material_summary.get("tool_version"),
        "status": "wet_coverage_material_variant_queue_classified_no_payload_written_runtime_deferred",
        "registry_profile_rows": 15,
        "source_focused_material_rows": len(source_rows),
        "in_scope_material_rows": len(in_scope),
        "direct_numeric_restore_candidate_rows": len(direct),
        "structural_material_change_rows": len(structural),
        "three_way_variant_review_rows": len(variants),
        "material_member_group_rows": len(groups),
        "direct_numeric_member_groups_ready_for_occurrence_audit": len(ready_groups),
        "disposition_counts": dict(sorted(counts.items())),
        "high_value_parameters": sorted(HIGH_VALUE_PARAMETERS),
        "focused_domains": sorted(FOCUSED_DOMAINS),
        "policy": {
            "installed_game_modified": False,
            "g1m_payload_written": False,
            "parent_elixir_rebuilt": False,
            "pak_repacked": False,
            "core_registry_modified": False,
            "profile_activated": False,
            "runtime_validation_inferred": False,
            "censorship_semantics_inferred": False,
            "legacy_dlc_in_scope": False,
            "canary_track_modified": False,
            "direct_numeric_candidates_require_exact_member_rehydration_before_payload_build": True,
            "three_way_variant_rows_not_treated_as_direct_original_restore_candidates": True,
        },
        "next_action": (
            "Upload this report. If direct numeric member groups are ready, build a read-only occurrence-aware "
            "G1M parameter audit for the strongest groups. Do not write material payloads until exact parameter "
            "locations, byte widths, unchanged surrounding data and exact reverse round-trip are verified."
        ),
    }
    atomic_json(output / "SUMMARY.json", summary)

    archive: Path | None = None
    if create_archive:
        archive = report_root / REPORT_NAME
        if archive.exists():
            archive.unlink()
        completed = subprocess.run(
            ["tar", "--zstd", "-cf", str(archive), "-C", str(report_root), REPORT_DIR],
            text=True,
            capture_output=True,
        )
        if completed.returncode != 0:
            raise MaterialVariantEvidenceError(completed.stderr.strip() or "tar failed")
    return output, archive, summary


def main() -> int:
    parser = argparse.ArgumentParser(description="Classify direct and three-way wet/coverage G1M material evidence")
    parser.add_argument("--project-root", type=Path, required=True)
    parser.add_argument("--no-report-archive", action="store_true")
    args = parser.parse_args()
    project_root = args.project_root.expanduser().resolve()
    output, archive, summary = build_report(project_root, create_archive=not args.no_report_archive)
    print(f"Validated registry profiles: {summary['registry_profile_rows']}")
    print(f"Focused material rows: {summary['source_focused_material_rows']}")
    print(f"In-scope wet/coverage rows: {summary['in_scope_material_rows']}")
    print(f"Direct numeric candidate rows: {summary['direct_numeric_restore_candidate_rows']}")
    print(f"Ready member groups: {summary['direct_numeric_member_groups_ready_for_occurrence_audit']}")
    print(f"Report directory: {output}")
    if archive:
        print(f"Report: {archive}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except MaterialVariantEvidenceError as exc:
        print(f"ERROR: {exc}", file=__import__("sys").stderr)
        raise SystemExit(1)
