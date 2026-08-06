#!/usr/bin/env python3
"""Build a metadata-only master discovery inventory and gap audit.

Stage 121 consolidates completed quartet_restoration evidence into one bounded
snapshot of what has actually been found in the game. It deliberately separates
heterogeneous identity namespaces (asset families, scene/effect paths, event
paths and render-member families) and never claims that their row counts are one
number of independent censorship changes.

The stage reads only existing report metadata and stage-119 profile manifests.
It rehydrates no proprietary payload, builds no PAK, changes no profile/runtime
state and performs no installation or Git operation.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from collections import Counter
from pathlib import Path, PurePosixPath
from typing import Any, Iterable, Mapping, Sequence

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT_DEFAULT = SCRIPT_DIR.parent.parent
TOOL_VERSION = "0.1.39"
REPORT_DIR = "master_restoration_discovery_inventory_gap_audit"
REPORT_NAME = "BR_quartet_restoration_master_discovery_inventory_gap_audit_evidence.tar.zst"

STAGE119_ARCHIVE = "BR_quartet_restoration_canary_composition_input_contract_evidence.tar.zst"
STAGE120_ARCHIVE = "BR_quartet_restoration_canary_all_synthetic_composer_contract_evidence.tar.zst"
STAGE119_DIR = "canary_composition_input_contract_evidence"
STAGE120_DIR = "canary_all_synthetic_composer_contract_evidence"

REQUIRED_REPORTS = {
    "reference_evidence": "BR_quartet_restoration_reference_evidence.tar.zst",
    "scene_effect_evidence": "BR_quartet_restoration_scene_effect_evidence.tar.zst",
    "presentation_surface_evidence": "BR_quartet_restoration_presentation_surface_evidence.tar.zst",
    "structural_evidence": "BR_quartet_restoration_structural_evidence.tar.zst",
    "material_delta_evidence": "BR_quartet_restoration_material_delta_evidence.tar.zst",
    "wet_coverage_material_variant_evidence": "BR_quartet_restoration_wet_coverage_material_variant_evidence.tar.zst",
    "bathroom_ordinary_field_control_evidence": "BR_quartet_restoration_bathroom_ordinary_field_control_evidence.tar.zst",
    "presentation_event_backlog_evidence": "BR_quartet_restoration_presentation_event_backlog_evidence.tar.zst",
    "remaining_cue_positive_backlog_evidence": "BR_quartet_restoration_remaining_cue_positive_backlog_evidence.tar.zst",
    "all_reflector_transformation_family_evidence": "BR_quartet_restoration_all_reflector_transformation_family_evidence.tar.zst",
    "reflector_character_slot_render_member_evidence": "BR_quartet_restoration_reflector_character_slot_render_member_evidence.tar.zst",
    "reflector_light_family_binary_evidence": "BR_quartet_restoration_reflector_light_family_binary_evidence.tar.zst",
    "reflector_slot_light_swordflash_unresolved_freeze_evidence": "BR_quartet_restoration_reflector_slot_light_swordflash_unresolved_freeze_evidence.tar.zst",
    STAGE119_DIR: STAGE119_ARCHIVE,
    STAGE120_DIR: STAGE120_ARCHIVE,
}

POST_STAGE121_LOW_VERSION_REPORT_IDS = {
    "br1_official_source_inventory_refresh_preview_evidence",
    "br1_official_source_metadata_refresh_evidence",
    "br1_official_source_retirement_closure_evidence",
    "quartet_restoration",
}

EXPECTED = {
    "report_catalog_rows": 110,
    "asset_family_rows": 22,
    "asset_file_rows": 44,
    "scene_effect_rows": 22,
    "event_candidate_rows": 38,
    "render_family_rows": 167,
    "cross_namespace_candidate_rows": 249,
    "profile_rows": 15,
    "profile_changed_member_rows": 30,
    "profile_pack11_rows": 12,
    "profile_pack10_01_rows": 2,
    "profile_pack10_03_rows": 1,
}


class AuditError(RuntimeError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AuditError(message)


def progress(message: str) -> None:
    print(f"[master-discovery] {message}", file=sys.stderr, flush=True)


def parse_int(value: Any, default: int = 0) -> int:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return default


def version_tuple(value: str) -> tuple[int, ...]:
    try:
        return tuple(int(part) for part in value.strip().split("."))
    except ValueError as exc:
        raise AuditError(f"invalid workstream version: {value}") from exc


def parse_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().casefold() in {"1", "true", "yes", "y"}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def safe_relative(raw: str, label: str) -> str:
    path = PurePosixPath(str(raw).replace("\\", "/"))
    require(bool(path.parts), f"empty {label}")
    require(not path.is_absolute() and ".." not in path.parts, f"unsafe {label}: {raw}")
    return path.as_posix()


def load_json(path: Path) -> dict[str, Any]:
    require(path.is_file(), f"missing required JSON: {path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise AuditError(f"invalid JSON {path}: {exc}") from exc
    require(isinstance(value, dict), f"JSON root must be object: {path}")
    return value


def read_tsv(path: Path) -> list[dict[str, str]]:
    require(path.is_file(), f"missing required TSV: {path}")
    with path.open(encoding="utf-8", newline="") as handle:
        return [dict(row) for row in csv.DictReader(handle, delimiter="\t")]


def write_tsv(path: Path, fields: Sequence[str], rows: Iterable[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(fields), delimiter="\t", lineterminator="\n", extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fields})


def extract_archive(archive: Path, destination: Path) -> Path:
    require(archive.is_file(), f"missing prerequisite report archive: {archive}")
    listed = subprocess.run(["tar", "--zstd", "-tf", str(archive)], text=True, capture_output=True)
    require(listed.returncode == 0, listed.stderr.strip() or f"cannot list {archive}")
    names = [line.strip() for line in listed.stdout.splitlines() if line.strip()]
    require(names, f"empty prerequisite report: {archive}")
    roots = {PurePosixPath(safe_relative(name, "archive member")).parts[0] for name in names}
    require(len(roots) == 1, f"expected one report root in {archive}")
    destination.mkdir(parents=True, exist_ok=True)
    completed = subprocess.run(["tar", "--zstd", "-xf", str(archive), "-C", str(destination)], text=True, capture_output=True)
    require(completed.returncode == 0, completed.stderr.strip() or f"cannot extract {archive}")
    root = destination / next(iter(roots))
    require(root.is_dir(), f"missing extracted report root: {root}")
    return root


def locate_report(report_root: Path, report_id: str, archive_name: str, temporary: Path) -> Path:
    direct = report_root / report_id
    if direct.is_dir():
        return direct
    return extract_archive(report_root / archive_name, temporary / report_id)


def make_archive(source: Path, output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(output.name + ".tmp")
    temporary.unlink(missing_ok=True)
    completed = subprocess.run(["tar", "--zstd", "-cf", str(temporary), "-C", str(source.parent), source.name], text=True, capture_output=True)
    require(completed.returncode == 0, completed.stderr.strip() or "report archive creation failed")
    os.replace(temporary, output)


def report_domain(report_id: str) -> str:
    if report_id.startswith("reflector_") or "transformation" in report_id:
        return "reflector_and_transformation"
    if report_id.startswith("event_") or report_id.startswith("presentation_event") or report_id.startswith("friend_event") or report_id.startswith("fe") or report_id.startswith("single_scene") or report_id.startswith("residual_") or report_id.startswith("remaining_cue") or report_id.startswith("unselected_cue") or report_id.startswith("complex_repeated") or report_id.startswith("registered_profile"):
        return "event_and_scene_binding"
    if "bathroom" in report_id:
        return "bathroom_and_water"
    if "material" in report_id or "wet_coverage" in report_id:
        return "materials_and_coverage"
    if "shader" in report_id or "dxbc" in report_id or "binary_delta" in report_id or report_id.startswith("g1s_"):
        return "shader_and_render"
    if report_id.startswith("canary_") or "profile" in report_id or "activation" in report_id or "repack" in report_id:
        return "profile_and_composition"
    if report_id.startswith("br1_"):
        return "provenance"
    return "inventory_and_cross_domain"


def build_report(project_root: Path, report_root: Path | None = None, output_report_root: Path | None = None, create_archive: bool = True) -> tuple[Path, dict[str, Any]]:
    project_root = project_root.resolve()
    version = (project_root / "workstreams/quartet_restoration/VERSION").read_text(encoding="utf-8").strip()
    require(version_tuple(version) >= version_tuple(TOOL_VERSION), f"expected quartet_restoration {TOOL_VERSION} or newer, found {version}")
    report_root = (report_root or project_root / ".local/reports/quartet_restoration").resolve()
    output_report_root = (output_report_root or report_root).resolve()

    output_dir = output_report_root / REPORT_DIR
    if output_dir.exists():
        shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True)

    with tempfile.TemporaryDirectory(prefix="br-stage121-") as td:
        temp = Path(td)
        reports = {rid: locate_report(report_root, rid, archive, temp) for rid, archive in REQUIRED_REPORTS.items()}

        reference_summary = load_json(reports["reference_evidence"] / "SUMMARY.json")
        asset_families = read_tsv(reports["reference_evidence"] / "CANDIDATE_ASSET_FAMILIES.tsv")
        require(reference_summary.get("status") == "streaming_full_reference_scan_complete_manual_confirmation_required", "reference report status drift")
        require(parse_int(reference_summary.get("candidate_families"), -1) == EXPECTED["asset_family_rows"], "asset-family count drift")
        require(parse_int(reference_summary.get("candidate_asset_files"), -1) == EXPECTED["asset_file_rows"], "asset-file count drift")
        require(len(asset_families) == EXPECTED["asset_family_rows"], "candidate family TSV count drift")
        require(reference_summary.get("families") == {"bath_towel_addition": 3, "shower_swimsuit_addition": 1, "underwear_coverage_variant": 15, "wet_reflector_variant": 3}, "candidate family distribution drift")

        scene_summary = load_json(reports["scene_effect_evidence"] / "SUMMARY.json")
        scene_rows = read_tsv(reports["scene_effect_evidence"] / "SCENE_EFFECT_CANDIDATES.tsv")
        require(parse_int(scene_summary.get("candidate_files"), -1) == EXPECTED["scene_effect_rows"], "scene/effect candidate count drift")
        require(len(scene_rows) == EXPECTED["scene_effect_rows"], "scene/effect TSV count drift")
        require(scene_summary.get("domains") == {"steam_and_water_visibility": 3, "steam_and_wet_clothing": 4, "steam_or_vapor_occlusion": 2, "water_visibility": 7, "wet_fabric_material_response": 6}, "scene/effect domain split drift")

        presentation = load_json(reports["presentation_surface_evidence"] / "SUMMARY.json")
        require(parse_int(presentation.get("scene_costume_binding_candidates"), -1) == 0, "scene costume-binding status drift")
        require(parse_int(presentation.get("lightshaft_asset_candidates"), -1) == 5, "lightshaft asset count drift")
        require(parse_int(presentation.get("lightshaft_effect_member_candidates"), -1) == 12, "lightshaft member count drift")

        structural = load_json(reports["structural_evidence"] / "SUMMARY.json")
        require(parse_int(structural.get("parsed_earc_archives"), -1) == 92, "EARC count drift")
        require(parse_int(structural.get("scene_effect_member_differences"), -1) == 586, "scene/effect member-difference count drift")
        require(parse_int(structural.get("variant_member_rows"), -1) == 452, "variant-member count drift")

        material = load_json(reports["material_delta_evidence"] / "SUMMARY.json")
        wet = load_json(reports["wet_coverage_material_variant_evidence"] / "SUMMARY.json")
        require(parse_int(material.get("focused_review_rows"), -1) == 1508, "focused material count drift")
        require(parse_int(material.get("high_value_alpha_transparency_refraction_rows"), -1) == 73, "high-value material count drift")
        require(parse_int(wet.get("direct_numeric_restore_candidate_rows"), -1) == 0, "direct numeric material candidate drift")
        require(parse_int(wet.get("structural_material_change_rows"), -1) == 48, "structural material count drift")
        require(parse_int(wet.get("three_way_variant_review_rows"), -1) == 96, "three-way material review count drift")
        require(parse_int(wet.get("material_member_group_rows"), -1) == 357, "material group count drift")

        bathroom = load_json(reports["bathroom_ordinary_field_control_evidence"] / "SUMMARY.json")
        require(parse_int(bathroom.get("safe_local_prototype_rows"), -1) == 1, "bathroom promoted static candidate drift")
        require(parse_int(bathroom.get("opl2_safe_local_prototype_rows"), -1) == 0, "bathroom OPL2 readiness drift")

        event_summary = load_json(reports["presentation_event_backlog_evidence"] / "SUMMARY.json")
        event_rows = read_tsv(reports["presentation_event_backlog_evidence"] / "EVENT_CANDIDATE_BACKLOG.tsv")
        require(parse_int(event_summary.get("candidate_event_rows"), -1) == EXPECTED["event_candidate_rows"], "event candidate count drift")
        require(len(event_rows) == EXPECTED["event_candidate_rows"], "event backlog TSV count drift")
        require(parse_int(event_summary.get("registered_event_rows"), -1) == 19, "historical registered event count drift")
        require(parse_int(event_summary.get("safe_static_build_event_rows"), -1) == 2, "safe static event count drift")
        require(parse_int(event_summary.get("evidence_only_or_needs_decode_rows"), -1) == 17, "evidence-only event count drift")

        remaining = load_json(reports["remaining_cue_positive_backlog_evidence"] / "SUMMARY.json")
        require(parse_int(remaining.get("registry_owned_event_rows"), -1) == 27, "current registry-owned event count drift")
        require(parse_int(remaining.get("candidate_backlog_rows"), -1) == 0, "remaining cue-positive backlog drift")

        transformation = load_json(reports["all_reflector_transformation_family_evidence"] / "SUMMARY.json")
        require(parse_int(transformation.get("event_rows"), -1) == 68, "transformation event count drift")
        require(parse_int(transformation.get("changed_event_rows"), -1) == 1, "changed transformation event count drift")
        require(parse_int(transformation.get("effect_binding_candidate_rows"), -1) == 0, "transformation effect binding status drift")

        render_summary = load_json(reports["reflector_character_slot_render_member_evidence"] / "SUMMARY.json")
        render_rows = read_tsv(reports["reflector_character_slot_render_member_evidence"] / "REFLECTOR_RENDER_MEMBER_FAMILIES.tsv")
        require(parse_int(render_summary.get("character_slot_rows"), -1) == 15, "reflector slot count drift")
        require(parse_int(render_summary.get("render_member_family_rows"), -1) == EXPECTED["render_family_rows"], "render family count drift")
        require(parse_int(render_summary.get("uniform_changed_family_rows"), -1) == 8, "uniform changed render-family count drift")
        require(parse_int(render_summary.get("resolved_event_family_slot_binding_rows"), -1) == 0, "reflector slot binding status drift")
        require(len(render_rows) == EXPECTED["render_family_rows"], "render family TSV count drift")

        light = load_json(reports["reflector_light_family_binary_evidence"] / "SUMMARY.json")
        require(parse_int(light.get("family_rows"), -1) == 7, "reflector light family count drift")
        require(parse_int(light.get("candidate_family_rows"), -1) == 0, "reflector light promotion status drift")
        require(not parse_bool(light.get("brightness_semantics_confirmed")), "brightness semantics unexpectedly confirmed")

        freeze = load_json(reports["reflector_slot_light_swordflash_unresolved_freeze_evidence"] / "SUMMARY.json")
        require(parse_int(freeze.get("frozen_unresolved_swordflash_pair_rows"), -1) == 2, "swordflash unresolved count drift")
        require(parse_int(freeze.get("total_resolved_noncanary_pair_rows_preserved"), -1) == 5, "resolved slot-light count drift")

        stage119 = load_json(reports[STAGE119_DIR] / "SUMMARY.json")
        profile_rows = read_tsv(reports[STAGE119_DIR] / "CANARY_RESTORATION_PROFILE_INPUTS.tsv")
        require(parse_int(stage119.get("profile_rows"), -1) == EXPECTED["profile_rows"], "profile count drift")
        require(parse_int(stage119.get("changed_member_reference_rows"), -1) == EXPECTED["profile_changed_member_rows"], "profile changed-member count drift")
        require(parse_int(stage119.get("runtime_validated_profile_rows"), -1) == 0, "runtime validation count drift")
        require(len(profile_rows) == EXPECTED["profile_rows"], "profile input TSV count drift")
        split = Counter(row["target_relative_path"] for row in profile_rows)
        require(split == Counter({"Data/PACK11.PAK": 12, "Data/PACK10_01.PAK": 2, "Data/PACK10_03.PAK": 1}), f"profile target split drift: {dict(split)}")
        require(all(not parse_bool(row.get("runtime_validated")) for row in profile_rows), "profile runtime-validation drift")

        stage120 = load_json(reports[STAGE120_DIR] / "SUMMARY.json")
        require(stage120.get("status") == "synthetic_canary_all_composer_contract_passed_real_gust_pak_fixture_roundtrip_no_install_transaction", "stage-120 status drift")
        require(parse_int(stage120.get("overlay_member_verified_rows"), -1) == 30, "stage-120 overlay verification drift")
        require(parse_int(stage120.get("negative_gate_pass_rows"), -1) == 5, "stage-120 negative-gate drift")
        require(not parse_bool(stage120.get("real_canary_all_build_authorized")), "stage 120 unexpectedly authorized real build")

        ledger: list[dict[str, Any]] = []
        for row in asset_families:
            ledger.append({
                "identity_namespace": "coverage_asset_family",
                "identity": row["candidate_id"],
                "logical_name": row["token"],
                "domain": row["family"],
                "priority": row["priority"],
                "source_path_or_members": row["asset_files"],
                "profile_coverage": "none",
                "current_disposition": row["review_status"],
                "source_report": "reference_evidence",
            })
        for row in scene_rows:
            ledger.append({
                "identity_namespace": "scene_effect_path",
                "identity": row["candidate_id"],
                "logical_name": row["normalized_path"],
                "domain": row["domain"],
                "priority": row["priority"],
                "source_path_or_members": row["normalized_path"],
                "profile_coverage": "bathroom_or_shader_profile_possible_only_when_exact_path_matches_stage119",
                "current_disposition": row["review_status"],
                "source_report": "scene_effect_evidence",
            })
        for row in event_rows:
            ledger.append({
                "identity_namespace": "event_candidate_path",
                "identity": row["event_id"],
                "logical_name": row["normalized_path"],
                "domain": row["cue_domains"],
                "priority": row["review_priority"],
                "source_path_or_members": row["normalized_path"],
                "profile_coverage": "covered_historically" if row.get("existing_profile_ids") else "not_covered_in_stage40_snapshot",
                "current_disposition": row["classification"],
                "source_report": "presentation_event_backlog_evidence",
            })
        for row in render_rows:
            ledger.append({
                "identity_namespace": "reflector_render_member_family",
                "identity": row.get("family_key", ""),
                "logical_name": row.get("family_key", ""),
                "domain": row.get("asset_role", "reflector_render"),
                "priority": "high" if parse_bool(row.get("uniform_changed_family")) else "review",
                "source_path_or_members": row.get("members", row.get("member_names", "")),
                "profile_coverage": "none",
                "current_disposition": row.get("family_classification", row.get("review_status", "evidence_only")),
                "source_report": "reflector_character_slot_render_member_evidence",
            })
        require(len(ledger) == EXPECTED["cross_namespace_candidate_rows"], f"cross-namespace ledger count drift: {len(ledger)}")

        profile_ledger: list[dict[str, Any]] = []
        changed_member_total = 0
        for row in sorted(profile_rows, key=lambda r: r["profile_id"]):
            members = [safe_relative(m, "changed member") for m in row.get("changed_members", "").split(";") if m]
            require(len(members) == parse_int(row.get("changed_member_count"), -1), f"profile member-count drift: {row['profile_id']}")
            changed_member_total += len(members)
            profile_ledger.append({
                "profile_id": row["profile_id"],
                "target_relative_path": row["target_relative_path"],
                "changed_member_count": len(members),
                "changed_members": ";".join(members),
                "runtime_validated": False,
                "production_eligible": False,
                "discovery_meaning": "implementation_unit_not_independent_game_change_count",
            })
        require(changed_member_total == EXPECTED["profile_changed_member_rows"], "profile member total drift")

        domain_rows = [
            {"domain": "costume_and_coverage_assets", "primary_identity_rows": 22, "secondary_technical_rows": 44, "primary_unit": "asset_family", "profile_ready_rows": 0, "runtime_confirmed_rows": 0, "state": "families_found_scene_binding_unresolved", "source": "reference_evidence"},
            {"domain": "steam_water_wet_scene_effects", "primary_identity_rows": 22, "secondary_technical_rows": 586, "primary_unit": "focused_scene_or_effect_path", "profile_ready_rows": 3, "runtime_confirmed_rows": 0, "state": "focused_paths_found_member_semantics_incomplete", "source": "scene_effect_evidence;structural_evidence;stage119"},
            {"domain": "event_and_scene_presentation", "primary_identity_rows": 38, "secondary_technical_rows": 27, "primary_unit": "historical_candidate_event_path", "profile_ready_rows": 27, "runtime_confirmed_rows": 0, "state": "cue_positive_static_backlog_exhausted_under_existing_rules_other_binding_classes_open", "source": "presentation_event_backlog_evidence;remaining_cue_positive_backlog_evidence;stage119"},
            {"domain": "materials_alpha_transparency_refraction", "primary_identity_rows": 357, "secondary_technical_rows": 1508, "primary_unit": "material_member_group", "profile_ready_rows": 0, "runtime_confirmed_rows": 0, "state": "evidence_large_direct_numeric_restore_not_supported", "source": "material_delta_evidence;wet_coverage_material_variant_evidence"},
            {"domain": "bathroom_field_and_river", "primary_identity_rows": 1, "secondary_technical_rows": 5, "primary_unit": "static_promoted_field_member", "profile_ready_rows": 1, "runtime_confirmed_rows": 0, "state": "river_member_profile_ready_opl2_descriptor_unresolved", "source": "bathroom_ordinary_field_control_evidence;stage119"},
            {"domain": "reflector_transformation_and_character_render", "primary_identity_rows": 167, "secondary_technical_rows": 68, "primary_unit": "render_member_family", "profile_ready_rows": 0, "runtime_confirmed_rows": 0, "state": "families_inventoried_heroine_and_brightness_binding_unresolved", "source": "all_reflector_transformation_family_evidence;reflector_character_slot_render_member_evidence"},
            {"domain": "reflector_ringlight_eyelight", "primary_identity_rows": 7, "secondary_technical_rows": 21, "primary_unit": "light_member_family", "profile_ready_rows": 0, "runtime_confirmed_rows": 0, "state": "binary_families_audited_semantics_unresolved", "source": "reflector_light_family_binary_evidence"},
            {"domain": "reflector_slot_light_occurrence_identity", "primary_identity_rows": 7, "secondary_technical_rows": 0, "primary_unit": "one_edit_pair", "profile_ready_rows": 0, "runtime_confirmed_rows": 0, "state": "five_resolved_two_frozen_unresolved_no_write", "source": "reflector_slot_light_swordflash_unresolved_freeze_evidence"},
            {"domain": "restoration_profiles_and_composition", "primary_identity_rows": 15, "secondary_technical_rows": 30, "primary_unit": "inactive_profile", "profile_ready_rows": 15, "runtime_confirmed_rows": 0, "state": "structurally_verified_runtime_unvalidated_synthetic_composition_only", "source": "stage119;stage120"},
        ]

        gap_rows = [
            {"gap_id": "coverage_scene_binding", "priority": "critical", "affected_identity_rows": 22, "blocking_fact": "direct-name reference scan found zero event reference files and scene costume binding candidates remain zero", "safe_next_discovery": "structured index/hash/container binding audit for the 22 coverage families", "runtime_or_save_required": False, "write_authorized": False},
            {"gap_id": "scene_effect_semantic_partition", "priority": "critical", "affected_identity_rows": 22, "blocking_fact": "focused paths and 586 member differences are known but steam water wetness and remaster changes are not fully separated", "safe_next_discovery": "deduplicate the 586 member differences into member families and bind them to the 22 focused paths", "runtime_or_save_required": False, "write_authorized": False},
            {"gap_id": "material_format_mapping", "priority": "high", "affected_identity_rows": 357, "blocking_fact": "1508 focused rows yield zero direct numeric restore candidates and 48 structural changes remain format-aware rebuild only", "safe_next_discovery": "map structural parameter records to exact material member occurrences without assigning opacity semantics", "runtime_or_save_required": False, "write_authorized": False},
            {"gap_id": "event_noncue_binding_classes", "priority": "high", "affected_identity_rows": 38, "blocking_fact": "the cue-positive backlog is exhausted under existing rules but this does not cover non-EBD or index/hash-driven scene bindings", "safe_next_discovery": "continue with non-EBD asset-to-event binding and debug-event-checker research", "runtime_or_save_required": False, "write_authorized": False},
            {"gap_id": "bathroom_opl2_descriptor", "priority": "high", "affected_identity_rows": 1, "blocking_fact": "one river member is profile-ready but the OPL2 descriptor has zero safe local prototype rows", "safe_next_discovery": "format-aware OPL2 record boundary and reference audit", "runtime_or_save_required": False, "write_authorized": False},
            {"gap_id": "reflector_heroine_and_brightness_binding", "priority": "critical", "affected_identity_rows": 167, "blocking_fact": "15 character slots and 167 render families are inventoried but heroine bindings and brightness semantics remain unresolved", "safe_next_discovery": "strict technical slot-name binding and cross-slot family classification across all characters", "runtime_or_save_required": False, "write_authorized": False},
            {"gap_id": "slot_light_swordflash_identity", "priority": "frozen", "affected_identity_rows": 2, "blocking_fact": "all existing independent binding channels are non-authorizing", "safe_next_discovery": "reopen only on genuinely new independent format evidence", "runtime_or_save_required": False, "write_authorized": False},
            {"gap_id": "global_discovery_saturation", "priority": "critical", "affected_identity_rows": 249, "blocking_fact": "candidate namespaces are broad but heterogeneous and cannot establish exhaustive full-game coverage", "safe_next_discovery": "master deduplication plus systematic scan of remaining scene effect material transformation and costume-binding namespaces", "runtime_or_save_required": False, "write_authorized": False},
            {"gap_id": "runtime_validation_without_saves", "priority": "deferred", "affected_identity_rows": 15, "blocking_fact": "all profiles are runtime-unvalidated and individual scene saves are unavailable", "safe_next_discovery": "finish static discovery first; later use one opt-in broad Canary-all package during ordinary play rather than per-profile save tests", "runtime_or_save_required": True, "write_authorized": False},
        ]

        report_catalog: list[dict[str, Any]] = []
        catalog_sources = {
            path.parent.name: path
            for path in report_root.glob("*/SUMMARY.json")
            if path.parent.name != REPORT_DIR
        }
        # A reviewed handoff may retain a completed report only as its archive.
        # Include every required located report even when no direct extracted
        # report directory is present in the current workspace.
        for report_id, located in reports.items():
            catalog_sources.setdefault(report_id, located / "SUMMARY.json")
        for report_id in sorted(catalog_sources):
            summary_path = catalog_sources[report_id]
            data = load_json(summary_path)
            # These reports were completed after the reviewed stage-121 snapshot
            # but retain older tool-version values. Exclude them explicitly so
            # extraction of archived reports cannot expand the frozen catalog.
            if report_id not in reports and report_id in POST_STAGE121_LOW_VERSION_REPORT_IDS:
                continue
            # Stage 121 is a historical snapshot. On newer workstream versions,
            # do not let later reports expand its reviewed 110-report catalog.
            # Required stage-121 inputs remain included even when their tool
            # version is newer than an older report family.
            data_tool_version = str(data.get("tool_version", "")).strip()
            if report_id not in reports and data_tool_version:
                if version_tuple(data_tool_version) >= version_tuple(TOOL_VERSION):
                    continue
            report_catalog.append({
                "report_id": report_id,
                "domain": report_domain(report_id),
                "tool_version": data.get("tool_version", ""),
                "status": data.get("status", ""),
                "summary_sha256": sha256_file(summary_path),
                "next_action_present": bool(data.get("next_action")),
            })
        require(len(report_catalog) == EXPECTED["report_catalog_rows"], f"report catalog count drift: {len(report_catalog)}")

        count_warning_rows = [
            {"metric": "cross_namespace_candidate_rows", "value": 249, "interpretation": "sum of four disjoint metadata namespaces only", "may_be_read_as_independent_game_changes": False},
            {"metric": "profile_rows", "value": 15, "interpretation": "implementation profiles; one profile may cover multiple event members", "may_be_read_as_independent_game_changes": False},
            {"metric": "profile_changed_member_rows", "value": 30, "interpretation": "changed archive members; not 30 visually confirmed restorations", "may_be_read_as_independent_game_changes": False},
            {"metric": "material_focused_rows", "value": 1508, "interpretation": "technical parameter evidence rows with overlap and repeated contexts", "may_be_read_as_independent_game_changes": False},
            {"metric": "scene_effect_member_differences", "value": 586, "interpretation": "member-level binary differences across 92 EARC archives", "may_be_read_as_independent_game_changes": False},
        ]

        write_tsv(output_dir / "MASTER_DISCOVERY_IDENTITY_LEDGER.tsv", ["identity_namespace", "identity", "logical_name", "domain", "priority", "source_path_or_members", "profile_coverage", "current_disposition", "source_report"], ledger)
        write_tsv(output_dir / "MASTER_DISCOVERY_DOMAIN_SUMMARY.tsv", ["domain", "primary_identity_rows", "secondary_technical_rows", "primary_unit", "profile_ready_rows", "runtime_confirmed_rows", "state", "source"], domain_rows)
        write_tsv(output_dir / "MASTER_DISCOVERY_PROFILE_LEDGER.tsv", ["profile_id", "target_relative_path", "changed_member_count", "changed_members", "runtime_validated", "production_eligible", "discovery_meaning"], profile_ledger)
        write_tsv(output_dir / "MASTER_DISCOVERY_GAP_REGISTER.tsv", ["gap_id", "priority", "affected_identity_rows", "blocking_fact", "safe_next_discovery", "runtime_or_save_required", "write_authorized"], gap_rows)
        write_tsv(output_dir / "MASTER_DISCOVERY_REPORT_CATALOG.tsv", ["report_id", "domain", "tool_version", "status", "summary_sha256", "next_action_present"], report_catalog)
        write_tsv(output_dir / "MASTER_DISCOVERY_COUNT_INTERPRETATION.tsv", ["metric", "value", "interpretation", "may_be_read_as_independent_game_changes"], count_warning_rows)

        summary = {
            "type": "br_quartet_restoration_master_discovery_inventory_gap_audit_evidence_summary",
            "format_version": 1,
            "tool_version": TOOL_VERSION,
            "status": "master_static_discovery_inventory_consolidated_discovery_not_exhaustive_runtime_validation_deferred_no_write",
            "completed_report_summary_rows": len(report_catalog),
            "cross_namespace_candidate_rows": len(ledger),
            "cross_namespace_candidate_rows_are_additive_game_changes": False,
            "candidate_asset_family_rows": len(asset_families),
            "candidate_asset_file_rows": parse_int(reference_summary["candidate_asset_files"]),
            "focused_scene_effect_path_rows": len(scene_rows),
            "historical_event_candidate_path_rows": len(event_rows),
            "current_registry_owned_event_rows": parse_int(remaining["registry_owned_event_rows"]),
            "remaining_cue_positive_candidate_rows": parse_int(remaining["candidate_backlog_rows"]),
            "reflector_render_member_family_rows": len(render_rows),
            "reflector_character_slot_rows": parse_int(render_summary["character_slot_rows"]),
            "reflector_light_family_rows": parse_int(light["family_rows"]),
            "structural_earc_archive_rows": parse_int(structural["parsed_earc_archives"]),
            "scene_effect_member_difference_rows": parse_int(structural["scene_effect_member_differences"]),
            "variant_member_rows": parse_int(structural["variant_member_rows"]),
            "material_member_group_rows": parse_int(wet["material_member_group_rows"]),
            "focused_material_evidence_rows": parse_int(material["focused_review_rows"]),
            "direct_numeric_material_restore_candidate_rows": parse_int(wet["direct_numeric_restore_candidate_rows"]),
            "profile_rows": len(profile_rows),
            "profile_changed_member_rows": changed_member_total,
            "runtime_validated_profile_rows": 0,
            "runtime_confirmed_discovery_rows": 0,
            "resolved_noncanary_slot_light_pair_rows": parse_int(freeze["total_resolved_noncanary_pair_rows_preserved"]),
            "frozen_unresolved_swordflash_pair_rows": parse_int(freeze["frozen_unresolved_swordflash_pair_rows"]),
            "gap_rows": len(gap_rows),
            "discovery_exhaustive": False,
            "individual_save_based_runtime_testing_is_current_priority": False,
            "recommended_program_order": [
                "continue_static_master_discovery_and_binding",
                "deduplicate_scene_effect_and_render_member_families",
                "resolve_asset_to_scene_and_slot_bindings",
                "only_after_discovery_saturation_build_one_opt_in_broad_canary_all_runtime_package",
            ],
            "policy": {
                "existing_evidence_only": True,
                "proprietary_payload_rehydrated": False,
                "single_total_of_game_censorship_changes_claimed": False,
                "runtime_validation_inferred": False,
                "real_profile_paks_extracted": False,
                "real_baseline_paks_rehydrated": False,
                "pak_built_or_repacked": False,
                "profile_or_registry_modified": False,
                "core_modified": False,
                "installed_game_modified": False,
                "translation_modified": False,
                "legacy_dlc_modified": False,
                "git_modified": False,
            },
            "next_action": "Use the gap register to start a save-independent static discovery pass. First deduplicate the 586 scene/effect member differences into exact member families and bind them to the 22 focused scene/effect paths and 22 coverage families; do not proceed to real Canary-all composition yet.",
        }
        (output_dir / "SUMMARY.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")

    archive = output_report_root / REPORT_NAME
    if create_archive:
        make_archive(output_dir, archive)
    return archive, summary


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path, default=PROJECT_ROOT_DEFAULT)
    parser.add_argument("--report-root", type=Path)
    parser.add_argument("--output-report-root", type=Path)
    parser.add_argument("--no-archive", action="store_true")
    args = parser.parse_args(argv)
    try:
        archive, summary = build_report(args.project_root, args.report_root, args.output_report_root, not args.no_archive)
    except AuditError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    progress(f"report archive: {archive}")
    print(json.dumps(summary, indent=2, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
