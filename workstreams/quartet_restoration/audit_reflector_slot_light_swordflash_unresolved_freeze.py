#!/usr/bin/env python3
"""Formalize the fail-closed freeze of the two unresolved PC00 swordflash identities.

This post-stage-118 audit reads only completed evidence reports.  It does not
rehydrate proprietary payloads and does not introduce a numbered stage.  The
audit asks whether any already-established independent binding channel can
select deletion ordinal 1 or 2 for either remaining swordflash pair.

The following channels are checked exactly as they exist in the completed
project evidence:

* independently calibrated G1E section-table selectivity;
* exact same-stem G1EM occurrence bindings;
* independently resolved companion-family topology;
* exact parent-container name/callsite references;
* compatible cross-stem PC00 G1EM slot-light template occurrences; and
* parent-container scope rows that could otherwise be mistaken for an internal
  record-occurrence binding.

A channel is authorizing only when its own completed report already proves an
independent, selective occurrence mapping.  Absence of such a channel freezes
both identities as unresolved.  Paired-float values, numeric closeness, trailer
semantics and self-supporting companion topology are never promoted.  No G1E,
G1EM, Elixir, PAK, profile, registry, installed-game or Git payload is written.
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
from pathlib import Path, PurePosixPath
from typing import Any, Iterable, Mapping, Sequence

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT_DEFAULT = SCRIPT_DIR.parent.parent
TOOL_VERSION = "0.1.36"
REPORT_NAME = "BR_quartet_restoration_reflector_slot_light_swordflash_unresolved_freeze_evidence.tar.zst"
REPORT_DIR = "reflector_slot_light_swordflash_unresolved_freeze_evidence"

STAGE79_DIR = "reflector_character_slot_render_member_evidence"
STAGE79_ARCHIVE = "BR_quartet_restoration_reflector_character_slot_render_member_evidence.tar.zst"
STAGE81_DIR = "reflector_ringlight_control_callsite_evidence"
STAGE81_ARCHIVE = "BR_quartet_restoration_reflector_ringlight_control_callsite_evidence.tar.zst"
STAGE104_DIR = "reflector_slot_light_sibling_template_expansion_evidence"
STAGE104_ARCHIVE = "BR_quartet_restoration_reflector_slot_light_sibling_template_expansion_evidence.tar.zst"
STAGE116_DIR = "reflector_slot_light_companion_topology_binding_evidence"
STAGE116_ARCHIVE = "BR_quartet_restoration_reflector_slot_light_companion_topology_binding_evidence.tar.zst"
STAGE117_DIR = "reflector_slot_light_swordflash_g1em_section_table_binding_evidence"
STAGE117_ARCHIVE = "BR_quartet_restoration_reflector_slot_light_swordflash_g1em_section_table_binding_evidence.tar.zst"
STAGE118_DIR = "reflector_slot_light_section_table_model_selectivity_calibration_evidence"
STAGE118_ARCHIVE = "BR_quartet_restoration_reflector_slot_light_section_table_model_selectivity_calibration_evidence.tar.zst"
STAGE118_SHA256 = "12a6c42306d563b2130d98f58fe1517ce849f84c00eb24d9996130d7923abb0d"

PC00_CONTAINER = "data/x64/effect/1000_pc00.elixir.gz"
PC00_CROSS_STEM_G1EM = "e_pc00_model.g1em#0"
SWORDFLASH_MEMBERS = (
    "e_pc00_swordflash_02_bullet.g1e#0",
    "e_pc00_swordflash_02_bullet_x.g1e#0",
)
PC00_PARENT_SCOPE_MEMBERS = {
    "e_pc00_eyelight_00.g1e#0",
    "e_pc00_eyelight_01.g1e#0",
    "e_pc00_ringlight_a.g1e#0",
}
SWORDFLASH_FAMILY = "pc00_swordflash_02_bullet_companions"


class FreezeAuditError(RuntimeError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise FreezeAuditError(message)


def progress(message: str) -> None:
    print(f"[swordflash-freeze] {message}", file=sys.stderr, flush=True)


def parse_int(value: Any, default: int = 0) -> int:
    try:
        text = str(value).strip()
        return int(text, 16) if text.casefold().startswith("0x") else int(text)
    except (TypeError, ValueError):
        return default


def parse_bool(value: Any) -> bool:
    return str(value).strip().casefold() in {"1", "true", "yes", "y"}


def safe_name(raw: str) -> str:
    path = PurePosixPath(raw)
    require(not path.is_absolute() and path.parts and ".." not in path.parts, f"unsafe archive member: {raw}")
    return path.as_posix()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


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


def load_json(path: Path) -> dict[str, Any]:
    require(path.is_file(), f"missing required JSON: {path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise FreezeAuditError(f"invalid JSON {path}: {exc}") from exc
    require(isinstance(value, dict), f"JSON root must be object: {path}")
    return value


def extract_archive(archive: Path, destination: Path) -> Path:
    require(archive.is_file(), f"missing prerequisite report: {archive}")
    listed = subprocess.run(["tar", "--zstd", "-tf", str(archive)], text=True, capture_output=True)
    require(listed.returncode == 0, listed.stderr.strip())
    roots = {PurePosixPath(safe_name(line.strip())).parts[0] for line in listed.stdout.splitlines() if line.strip()}
    require(len(roots) == 1, f"expected one report root in {archive}")
    destination.mkdir(parents=True, exist_ok=True)
    completed = subprocess.run(["tar", "--zstd", "-xf", str(archive), "-C", str(destination)], text=True, capture_output=True)
    require(completed.returncode == 0, completed.stderr.strip())
    return destination / next(iter(roots))


def locate(report_root: Path, direct: str, archive: str, temporary: Path) -> Path:
    path = report_root / direct
    return path if path.is_dir() else extract_archive(report_root / archive, temporary)


def make_archive(source: Path, output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(output.name + ".tmp")
    temporary.unlink(missing_ok=True)
    completed = subprocess.run(["tar", "--zstd", "-cf", str(temporary), "-C", str(source.parent), source.name], text=True, capture_output=True)
    require(completed.returncode == 0, completed.stderr.strip())
    os.replace(temporary, output)


def validate_summary_contracts(
    stage79: Mapping[str, Any],
    stage81: Mapping[str, Any],
    stage104: Mapping[str, Any],
    stage116: Mapping[str, Any],
    stage117: Mapping[str, Any],
    stage118: Mapping[str, Any],
) -> None:
    require(stage79.get("tool_version") == "0.0.92", "stage79 tool-version drift")
    require(parse_int(stage79.get("character_slot_rows"), -1) == 15, "stage79 character-slot count drift")
    require(stage81.get("tool_version") == "0.0.95", "stage81 tool-version drift")
    require(parse_int(stage81.get("container_exact_reference_rows"), -1) == 0, "stage81 exact-container reference drift")
    require(parse_int(stage81.get("container_nonself_exact_reference_rows"), -1) == 0, "stage81 non-self reference drift")
    require(stage104.get("tool_version") == "0.1.18", "stage104 tool-version drift")
    require(parse_int(stage104.get("sibling_G1E_G1EM_pair_rows"), -1) == 540, "stage104 bounded corpus drift")
    require(parse_int(stage104.get("format_valid_sibling_occurrence_rows"), -1) == 1814, "stage104 occurrence count drift")
    require(stage116.get("tool_version") == "0.1.31", "stage116 tool-version drift")
    require(parse_int(stage116.get("still_unresolved_noncanary_pair_rows"), -1) == 2, "stage116 unresolved count drift")
    require(parse_int(stage116.get("total_resolved_noncanary_pair_rows_after_stage116"), -1) == 5, "stage116 resolved count drift")
    require(parse_bool(stage116.get("canary_identity_preserved")), "stage116 canary drift")
    require(stage117.get("tool_version") == "0.1.34", "stage117 tool-version drift")
    require(parse_int(stage117.get("same_stem_g1em_companion_rows"), -1) == 0, "stage117 same-stem G1EM drift")
    require(parse_int(stage117.get("g1em_occurrence_binding_candidate_rows"), -1) == 0, "stage117 G1EM binding drift")
    require(parse_int(stage117.get("still_unresolved_noncanary_pair_rows"), -1) == 2, "stage117 unresolved count drift")
    require(parse_bool(stage117.get("canary_identity_preserved")), "stage117 canary drift")
    require(stage118.get("tool_version") == "0.1.35", "stage118 tool-version drift")
    require(parse_int(stage118.get("independent_calibration_reference_rows"), -1) == 6, "stage118 reference count drift")
    require(parse_int(stage118.get("calibration_reference_pass_rows"), -1) == 0, "stage118 pass count drift")
    require(parse_int(stage118.get("calibration_reference_fail_rows"), -1) == 6, "stage118 fail count drift")
    require(not parse_bool(stage118.get("immutable_canary_recovered")), "stage118 canary recovery drift")
    require(not parse_bool(stage118.get("section_table_rule_authoritatively_calibrated")), "stage118 section-table authority drift")
    require(parse_int(stage118.get("still_unresolved_swordflash_pair_rows"), -1) == 2, "stage118 swordflash count drift")
    require(parse_int(stage118.get("total_resolved_noncanary_pair_rows_after_stage118"), -1) == 5, "stage118 total resolved drift")
    require(parse_bool(stage118.get("canary_identity_preserved")), "stage118 canary identity drift")
    for summary, name in ((stage116, "stage116"), (stage117, "stage117"), (stage118, "stage118")):
        policy = summary.get("policy")
        require(isinstance(policy, dict), f"{name} policy missing")
        require(not parse_bool(policy.get("G1E_G1EM_write_authorized")), f"{name} render-write gate drift")
        require(not parse_bool(policy.get("profile_or_registry_write_authorized")), f"{name} registry-write gate drift")
        require(not parse_bool(policy.get("installed_game_modified")), f"{name} installed-game gate drift")


def validate_parent_scope_rows(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    scoped = [dict(row) for row in rows if str(row.get("normalized_path", "")).casefold() == PC00_CONTAINER]
    selected = [row for row in scoped if str(row.get("member_key", "")).casefold() in PC00_PARENT_SCOPE_MEMBERS]
    require({str(row.get("member_key", "")).casefold() for row in selected} == PC00_PARENT_SCOPE_MEMBERS, "PC00 parent scope member set drift")
    require(len(selected) == 3, f"expected three PC00 parent scope rows, found {len(selected)}")
    require(len({str(row.get("candidate_id", "")) for row in selected}) == 1, "PC00 parent scope candidate identity drift")
    return sorted(selected, key=lambda row: str(row.get("member_key", "")))


def validate_cross_stem_g1em_rows(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    selected = [
        dict(row)
        for row in rows
        if str(row.get("normalized_path", "")).casefold() == PC00_CONTAINER
        and str(row.get("member_key", "")).casefold().endswith(".g1em#0")
    ]
    require(len(selected) == 2, f"expected source/target rows for one PC00 G1EM member, found {len(selected)}")
    require({str(row.get("side", "")).casefold() for row in selected} == {"source", "target"}, "PC00 G1EM side set drift")
    require({str(row.get("member_key", "")).casefold() for row in selected} == {PC00_CROSS_STEM_G1EM}, "unexpected PC00 cross-stem G1EM inventory")
    for row in selected:
        require(parse_int(row.get("raw_aligned_body_hits"), -1) == 0, "PC00 cross-stem G1EM body-hit drift")
        require(parse_int(row.get("format_valid_occurrence_rows"), -1) == 0, "PC00 cross-stem G1EM occurrence drift")
    return sorted(selected, key=lambda row: str(row.get("side", "")))


def validate_swordflash_family(
    inventory_rows: Sequence[Mapping[str, Any]],
    consensus_rows: Sequence[Mapping[str, Any]],
    resolved_rows: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    family = [dict(row) for row in inventory_rows if str(row.get("family_id", "")) == SWORDFLASH_FAMILY]
    require(len(family) == 2, f"expected two swordflash family rows, found {len(family)}")
    require({str(row.get("member_key", "")).casefold() for row in family} == set(SWORDFLASH_MEMBERS), "swordflash family member drift")
    require(not [row for row in consensus_rows if str(row.get("family_id", "")) == SWORDFLASH_FAMILY], "self-supporting swordflash consensus was promoted")
    require(not [row for row in resolved_rows if str(row.get("family_id", "")) == SWORDFLASH_FAMILY], "independent swordflash family reference unexpectedly exists")
    return sorted(family, key=lambda row: str(row.get("member_key", "")))


def validate_freeze_decisions(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    selected = [dict(row) for row in rows if str(row.get("member_key", "")).casefold() in SWORDFLASH_MEMBERS]
    require(len(selected) == 2, f"expected two stage118 swordflash decisions, found {len(selected)}")
    require({str(row.get("member_key", "")).casefold() for row in selected} == set(SWORDFLASH_MEMBERS), "stage118 swordflash member drift")
    result: list[dict[str, Any]] = []
    for row in sorted(selected, key=lambda item: str(item.get("member_key", ""))):
        require(parse_int(row.get("candidate_model_rows"), -1) == 2, "swordflash candidate-model count drift")
        require(parse_int(row.get("eligible_section_table_model_rows"), -1) == 1, "swordflash table-eligible count drift")
        require(not str(row.get("selected_model_id", "")).strip(), "stage118 improperly selected a swordflash model")
        require(str(row.get("classification", "")) == "occurrence_identity_unresolved_section_table_rule_not_authoritatively_calibrated", "stage118 swordflash classification drift")
        result.append({
            "pair_id": row.get("pair_id", ""),
            "normalized_path": row.get("normalized_path", ""),
            "member_key": row.get("member_key", ""),
            "member_name": row.get("member_name", ""),
            "candidate_model_rows": row.get("candidate_model_rows", ""),
            "table_eligible_model_rows": row.get("eligible_section_table_model_rows", ""),
            "selected_model_id": "",
            "freeze_basis": "no_existing_independent_authorizing_binding_channel",
            "classification": "formally_frozen_unresolved_existing_evidence_exhausted",
        })
    return result


def build_channel_rows(
    stage81_summary: Mapping[str, Any],
    stage116_summary: Mapping[str, Any],
    stage117_summary: Mapping[str, Any],
    stage118_summary: Mapping[str, Any],
    exact_reference_rows: Sequence[Mapping[str, Any]],
    cross_stem_rows: Sequence[Mapping[str, Any]],
    parent_scope_rows: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    rows = [
        {
            "channel_id": "calibrated_section_table_selectivity",
            "evidence_sources": "stage118",
            "observed_state": "0/6 references passed; immutable canary not recovered; rule non-authoritative",
            "independent_occurrence_binding_proven": False,
            "authorizing": False,
            "classification": "failed_calibration_non_authorizing",
        },
        {
            "channel_id": "same_stem_g1em_occurrence_binding",
            "evidence_sources": "stage117",
            "observed_state": f"companions={parse_int(stage117_summary.get('same_stem_g1em_companion_rows'), -1)}; bindings={parse_int(stage117_summary.get('g1em_occurrence_binding_candidate_rows'), -1)}",
            "independent_occurrence_binding_proven": False,
            "authorizing": False,
            "classification": "companion_absent_non_authorizing",
        },
        {
            "channel_id": "independent_swordflash_companion_topology",
            "evidence_sources": "stage116",
            "observed_state": f"unresolved_pairs={parse_int(stage116_summary.get('still_unresolved_noncanary_pair_rows'), -1)}; independent_family_references=0",
            "independent_occurrence_binding_proven": False,
            "authorizing": False,
            "classification": "family_contains_only_unresolved_members_self_support_forbidden",
        },
        {
            "channel_id": "exact_parent_container_name_or_callsite_reference",
            "evidence_sources": "stage81",
            "observed_state": f"summary_rows={parse_int(stage81_summary.get('container_exact_reference_rows'), -1)}; tsv_rows={len(exact_reference_rows)}",
            "independent_occurrence_binding_proven": False,
            "authorizing": False,
            "classification": "no_exact_container_reference_rows",
        },
        {
            "channel_id": "cross_stem_pc00_g1em_slot_light_template",
            "evidence_sources": "stage104",
            "observed_state": f"{PC00_CROSS_STEM_G1EM} source/target rows={len(cross_stem_rows)}; exact template occurrences=0",
            "independent_occurrence_binding_proven": False,
            "authorizing": False,
            "classification": "no_existing_compatible_occurrence_structure_evidence",
        },
        {
            "channel_id": "parent_container_scope_identity",
            "evidence_sources": "stage79/stage117 scope contract",
            "observed_state": f"one parent identity selected by {len(parent_scope_rows)} light-member rows",
            "independent_occurrence_binding_proven": False,
            "authorizing": False,
            "classification": "container_rehydration_scope_only_not_internal_record_binding",
        },
    ]
    require(not parse_bool(stage118_summary.get("section_table_rule_authoritatively_calibrated")), "section-table channel unexpectedly authorizing")
    require(parse_int(stage118_summary.get("calibration_reference_pass_rows"), -1) == 0, "stage118 calibration pass drift")
    require(not exact_reference_rows, "exact parent-container references unexpectedly exist")
    require(all(not parse_bool(row["authorizing"]) for row in rows), "authorizing channel unexpectedly present")
    return rows


def build_report(
    project_root: Path,
    *,
    source_report_root: Path | None = None,
    output_report_root: Path | None = None,
    create_archive: bool = True,
) -> tuple[Path, Path | None, dict[str, Any]]:
    project_root = project_root.resolve()
    source_reports = (source_report_root or project_root / ".local/reports/quartet_restoration").resolve()
    output_reports = (output_report_root or source_reports).resolve()
    require(source_reports.is_dir(), f"missing report root: {source_reports}")

    stage118_archive = source_reports / STAGE118_ARCHIVE
    require(stage118_archive.is_file(), f"missing stage118 archive: {stage118_archive}")
    actual_stage118_sha = sha256_file(stage118_archive)
    require(actual_stage118_sha == STAGE118_SHA256, f"stage118 archive SHA-256 drift: {actual_stage118_sha}")

    with tempfile.TemporaryDirectory(prefix="br-swordflash-freeze-") as temporary_name:
        temporary = Path(temporary_name)
        r79 = locate(source_reports, STAGE79_DIR, STAGE79_ARCHIVE, temporary / "79")
        r81 = locate(source_reports, STAGE81_DIR, STAGE81_ARCHIVE, temporary / "81")
        r104 = locate(source_reports, STAGE104_DIR, STAGE104_ARCHIVE, temporary / "104")
        r116 = locate(source_reports, STAGE116_DIR, STAGE116_ARCHIVE, temporary / "116")
        r117 = locate(source_reports, STAGE117_DIR, STAGE117_ARCHIVE, temporary / "117")
        r118 = locate(source_reports, STAGE118_DIR, STAGE118_ARCHIVE, temporary / "118")

        summaries = [load_json(root / "SUMMARY.json") for root in (r79, r81, r104, r116, r117, r118)]
        validate_summary_contracts(*summaries)
        s79, s81, s104, s116, s117, s118 = summaries

        parent_scope_rows = validate_parent_scope_rows(read_tsv(r79 / "REFLECTOR_SLOT_RENDER_MEMBERS.tsv"))
        exact_reference_rows = read_tsv(r81 / "RINGLIGHT_EFFECT_CONTAINER_EXACT_REFERENCES.tsv")
        require(not exact_reference_rows, "stage81 exact parent-container reference table is no longer empty")
        cross_stem_rows = validate_cross_stem_g1em_rows(read_tsv(r104 / "SLOT_LIGHT_SIBLING_TEMPLATE_MEMBER_SCAN.tsv"))
        validate_swordflash_family(
            read_tsv(r116 / "SLOT_LIGHT_COMPANION_FAMILY_INVENTORY.tsv"),
            read_tsv(r116 / "SLOT_LIGHT_COMPANION_TOPOLOGY_CONSENSUS_CLASSES.tsv"),
            read_tsv(r116 / "SLOT_LIGHT_RESOLVED_COMPANION_TOPOLOGY_REFERENCES.tsv"),
        )
        freeze_rows = validate_freeze_decisions(read_tsv(r118 / "SLOT_LIGHT_SWORDFLASH_CALIBRATED_SECTION_TABLE_PAIR_DECISIONS.tsv"))
        channel_rows = build_channel_rows(s81, s116, s117, s118, exact_reference_rows, cross_stem_rows, parent_scope_rows)

        canary_rows = [
            {"question": "stage118 archive SHA-256 matches reviewed handoff", "answer": actual_stage118_sha == STAGE118_SHA256, "classification": "immutable_report_identity_gate"},
            {"question": "stage116 canary identity preserved", "answer": s116.get("canary_identity_preserved", False), "classification": "prerequisite_canary_gate"},
            {"question": "stage117 canary identity preserved", "answer": s117.get("canary_identity_preserved", False), "classification": "prerequisite_canary_gate"},
            {"question": "stage118 canary identity preserved", "answer": s118.get("canary_identity_preserved", False), "classification": "prerequisite_canary_gate"},
            {"question": "stage118 immutable canary recovered by section-table rule", "answer": s118.get("immutable_canary_recovered", False), "classification": "failed_selectivity_calibration_recorded"},
            {"question": "any existing independent authorizing channel remains", "answer": False, "classification": "branch_freeze_gate"},
            {"question": "numbered stage 119 created", "answer": False, "classification": "no_stage_number_invented"},
            {"question": "paired-float or trailer semantics inferred", "answer": False, "classification": "semantic_non_inference_gate"},
        ]

        output = output_reports / REPORT_DIR
        if output.exists():
            shutil.rmtree(output)
        output.mkdir(parents=True)
        write_tsv(output / "SLOT_LIGHT_SWORDFLASH_EXISTING_BINDING_CHANNEL_AUDIT.tsv", [
            "channel_id", "evidence_sources", "observed_state", "independent_occurrence_binding_proven", "authorizing", "classification",
        ], channel_rows)
        write_tsv(output / "SLOT_LIGHT_SWORDFLASH_UNRESOLVED_FREEZE_DECISIONS.tsv", [
            "pair_id", "normalized_path", "member_key", "member_name", "candidate_model_rows", "table_eligible_model_rows", "selected_model_id", "freeze_basis", "classification",
        ], freeze_rows)
        write_tsv(output / "SLOT_LIGHT_SWORDFLASH_UNRESOLVED_FREEZE_CANARY_CHECK.tsv", ["question", "answer", "classification"], canary_rows)
        write_tsv(output / "SLOT_LIGHT_SWORDFLASH_UNRESOLVED_FREEZE_SKIPPED.tsv", ["scope", "identity", "reason"], [])

        summary = {
            "type": "br_quartet_restoration_reflector_slot_light_swordflash_unresolved_freeze_evidence_summary",
            "format_version": 1,
            "tool_version": TOOL_VERSION,
            "status": "existing_independent_binding_channels_exhausted_swordflash_branch_frozen_unresolved_no_write",
            "stage118_report_sha256": actual_stage118_sha,
            "existing_binding_channel_rows": len(channel_rows),
            "authorizing_binding_channel_rows": sum(parse_bool(row.get("authorizing")) for row in channel_rows),
            "frozen_unresolved_swordflash_pair_rows": len(freeze_rows),
            "total_resolved_noncanary_pair_rows_preserved": parse_int(s118.get("total_resolved_noncanary_pair_rows_after_stage118"), -1),
            "canary_identity_preserved": True,
            "numbered_stage_created": False,
            "prototype_candidate_rows": 0,
            "technical_leaf_domain_semantics_resolved": False,
            "brightness_semantics_confirmed": False,
            "intensity_semantics_confirmed": False,
            "censorship_semantics_confirmed": False,
            "skipped_rows": 0,
            "policy": {
                "existing_evidence_only": True,
                "proprietary_payload_rehydrated": False,
                "cross_stem_raw_offset_scan_invented_without_basis": False,
                "paired_float_leaf_values_used_for_identity": False,
                "numeric_closeness_used": False,
                "trailer_field_semantics_assigned": False,
                "deletion_ordinal_2_accepted_from_table_eligibility_alone": False,
                "G1E_G1EM_write_authorized": False,
                "pak_repack_authorized": False,
                "profile_or_registry_write_authorized": False,
                "installed_game_modified": False,
                "git_modified": False,
            },
            "next_action": "Upload this report. Keep both PC00 swordflash identities formally frozen as unresolved. Reopen only if a genuinely new independent occurrence-binding structure or externally grounded format evidence appears; otherwise move to another Restoration branch.",
        }
        (output / "SUMMARY.json").write_text(json.dumps(summary, indent=2, sort_keys=False) + "\n", encoding="utf-8")
        archive = output_reports / REPORT_NAME if create_archive else None
        if archive:
            make_archive(output, archive)
        return output, archive, summary


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path, default=PROJECT_ROOT_DEFAULT)
    parser.add_argument("--report-root", type=Path, help="source prerequisite report root")
    parser.add_argument("--output-report-root", type=Path, help="output report root; defaults to source report root")
    parser.add_argument("--no-report-archive", action="store_true")
    args = parser.parse_args(argv)
    try:
        output, archive, summary = build_report(
            args.project_root,
            source_report_root=args.report_root,
            output_report_root=args.output_report_root,
            create_archive=not args.no_report_archive,
        )
    except FreezeAuditError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    progress(f"report directory: {output}")
    if archive:
        progress(f"report archive: {archive}")
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
