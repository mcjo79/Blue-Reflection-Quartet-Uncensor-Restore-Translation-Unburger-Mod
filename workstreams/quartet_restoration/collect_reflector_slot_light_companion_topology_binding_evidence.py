#!/usr/bin/env python3
"""Audit bounded companion-family topology consensus for remaining slot-light identities.

Stage 115 leaves exactly three one-edit pairs unresolved because their bounded
blocks and trailer fields are structural duplicates.  This stage does not use
paired-float values, numeric closeness or semantic labels.  It reads only
completed metadata from stages 108, 109, 111, 114 and 115 and asks whether an
unresolved model is the sole model matching a topology consensus established by
at least two independently resolved companion members in one explicitly bounded
family.

The bounded families are evidence scopes, not semantic claims.  A consensus
requires the same edit kind and edit ordinal, the same occurrence-count delta,
and the same leading/post-edit ordinal mapping shape in two distinct resolved
members.  Unresolved members never support their own consensus.  The immutable
PC02 ringlight canary cannot be overridden.  No game payload is rehydrated or
written.
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import shutil
import subprocess
import tempfile
from collections import defaultdict
from pathlib import Path, PurePosixPath
from typing import Any, Iterable, Mapping, Sequence

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT_DEFAULT = SCRIPT_DIR.parent.parent
TOOL_VERSION = "0.1.31"
REPORT_NAME = "BR_quartet_restoration_reflector_slot_light_companion_topology_binding_evidence.tar.zst"
REPORT_DIR = "reflector_slot_light_companion_topology_binding_evidence"

STAGE108_DIR = "br1_official_source_retirement_closure_evidence"
STAGE108_ARCHIVE = "BR_quartet_restoration_br1_official_source_retirement_closure_evidence.tar.zst"
STAGE109_DIR = "reflector_slot_light_sibling_section_layout_evidence"
STAGE109_ARCHIVE = "BR_quartet_restoration_reflector_slot_light_sibling_section_layout_evidence.tar.zst"
STAGE111_DIR = "reflector_slot_light_edit_normalized_layout_alignment_evidence"
STAGE111_ARCHIVE = "BR_quartet_restoration_reflector_slot_light_edit_normalized_layout_alignment_evidence.tar.zst"
STAGE114_DIR = "reflector_slot_light_trailer_algebraic_schema_evidence"
STAGE114_ARCHIVE = "BR_quartet_restoration_reflector_slot_light_trailer_algebraic_schema_evidence.tar.zst"
STAGE115_DIR = "reflector_slot_light_trailer_exact_field_continuity_evidence"
STAGE115_ARCHIVE = "BR_quartet_restoration_reflector_slot_light_trailer_exact_field_continuity_evidence.tar.zst"

EXPECTED_STAGE115_PAIR_ROWS = 8
EXPECTED_STAGE115_RESOLVED_NONCANARY = 4
EXPECTED_STAGE115_UNRESOLVED_NONCANARY = 3
EXPECTED_STAGE115_CANARY_ROWS = 1
EXPECTED_NEWLY_RESOLVED = 1
EXPECTED_STILL_UNRESOLVED = 2
CANARY_MEMBER_KEY = "e_pc02_w5_ringlight_01.g1e#0"

# Explicitly bounded evidence families.  Membership itself carries no semantic
# meaning; it only scopes exact topology-consensus tests.
FAMILY_MEMBERS: dict[str, tuple[str, ...]] = {
    "pc00_swordflash_02_bullet_companions": (
        "e_pc00_swordflash_02_bullet.g1e#0",
        "e_pc00_swordflash_02_bullet_x.g1e#0",
    ),
    "pc02_m4_companions": (
        "e_pc02_m4_beardivision.g1e#0",
        "e_pc02_m4_charge_00.g1e#0",
        "e_pc02_m4_charge_01.g1e#0",
    ),
}


class Stage116Error(RuntimeError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise Stage116Error(message)


def progress(message: str) -> None:
    print(f"[stage116] {message}", file=__import__("sys").stderr, flush=True)


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
        raise Stage116Error(f"invalid JSON {path}: {exc}") from exc
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


def split_values(text: str) -> list[str]:
    return [part for part in str(text).split(";") if part != ""]


def parse_pairs(text: str) -> list[tuple[int, int]]:
    result: list[tuple[int, int]] = []
    if not text:
        return result
    for item in str(text).split(";"):
        left, sep, right = item.partition("->")
        require(sep == "->", f"invalid ordinal pair: {item}")
        result.append((parse_int(left, -1), parse_int(right, -1)))
    return result


def family_for_member(member_key: str) -> str:
    matches = [family for family, members in FAMILY_MEMBERS.items() if member_key.casefold() in members]
    require(len(matches) <= 1, f"member belongs to multiple bounded families: {member_key}")
    return matches[0] if matches else ""


def model_topology_signature(model: Mapping[str, Any], pair: Mapping[str, Any]) -> tuple[Any, ...]:
    pairs = parse_pairs(str(model.get("matched_ordinal_pairs", "")))
    edit_kind = str(model.get("edit_kind", ""))
    edit_ordinal = parse_int(model.get("edit_ordinal"), -1)
    source_count = len(split_values(str(pair.get("source_values", ""))))
    target_count = len(split_values(str(pair.get("target_values", ""))))
    count_delta = target_count - source_count
    expected_delta = 1 if edit_kind == "target_insertion_piecewise_offset_shift" else -1 if edit_kind == "target_deletion_piecewise_offset_shift" else 0
    require(count_delta == expected_delta, f"model count delta mismatch: {model.get('model_id')}")
    before = [(s, t) for s, t in pairs if (t if count_delta > 0 else s) < edit_ordinal]
    after = [(s, t) for s, t in pairs if (t if count_delta > 0 else s) > edit_ordinal]
    leading_identity = all(s == t for s, t in before)
    post_shift = all((t - s) == count_delta for s, t in after)
    return (
        edit_kind,
        edit_ordinal,
        count_delta,
        leading_identity,
        post_shift,
    )


def build_consensus_classes(
    resolved_rows: Sequence[Mapping[str, Any]],
    models_by_id: Mapping[str, Mapping[str, Any]],
    pair_by_id: Mapping[str, Mapping[str, Any]],
    minimum_members: int = 2,
) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, tuple[Any, ...]], list[dict[str, Any]]] = defaultdict(list)
    for row in resolved_rows:
        member_key = str(row.get("member_key", "")).casefold()
        family = family_for_member(member_key)
        if not family:
            continue
        model_id = str(row.get("selected_model_id", ""))
        require(model_id in models_by_id, f"resolved model missing from stage111: {model_id}")
        pair_id = str(row.get("pair_id", ""))
        require(pair_id in pair_by_id, f"resolved pair missing from stage111: {pair_id}")
        signature = model_topology_signature(models_by_id[model_id], pair_by_id[pair_id])
        grouped[(family, signature)].append({
            "family_id": family,
            "pair_id": pair_id,
            "member_key": member_key,
            "member_name": row.get("member_name", ""),
            "selected_model_id": model_id,
            "selection_basis": row.get("selection_basis", ""),
            "topology_signature": signature,
        })
    rows: list[dict[str, Any]] = []
    for (family, signature), refs in sorted(grouped.items(), key=lambda item: (item[0][0], str(item[0][1]))):
        members = sorted({str(ref["member_key"]) for ref in refs})
        independent = len(members) >= minimum_members
        rows.append({
            "family_id": family,
            "edit_kind": signature[0],
            "edit_ordinal": signature[1],
            "count_delta": signature[2],
            "leading_identity": signature[3],
            "post_edit_uniform_shift": signature[4],
            "resolved_reference_rows": len(refs),
            "distinct_resolved_members": len(members),
            "resolved_member_keys": ";".join(members),
            "consensus_eligible": independent and bool(signature[3]) and bool(signature[4]),
            "classification": "independent_companion_topology_consensus" if independent and bool(signature[3]) and bool(signature[4]) else "insufficient_independent_companion_support",
        })
    return rows


def decide_unresolved_pair(
    pair: Mapping[str, Any],
    candidate_models: Sequence[Mapping[str, Any]],
    consensus_rows: Sequence[Mapping[str, Any]],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    pair_id = str(pair.get("pair_id", ""))
    member_key = str(pair.get("member_key", "")).casefold()
    family = family_for_member(member_key)
    bindings: list[dict[str, Any]] = []
    eligible_models: list[str] = []
    for model in candidate_models:
        signature = model_topology_signature(model, pair)
        matching = [row for row in consensus_rows if row.get("family_id") == family and parse_bool(row.get("consensus_eligible")) and (
            row.get("edit_kind") == signature[0]
            and parse_int(row.get("edit_ordinal"), -1) == signature[1]
            and parse_int(row.get("count_delta"), 0) == signature[2]
            and parse_bool(row.get("leading_identity")) == signature[3]
            and parse_bool(row.get("post_edit_uniform_shift")) == signature[4]
        )]
        supported = len(matching) == 1
        if supported:
            eligible_models.append(str(model.get("model_id", "")))
        bindings.append({
            "pair_id": pair_id,
            "family_id": family,
            "member_key": member_key,
            "member_name": pair.get("member_name", ""),
            "model_id": model.get("model_id", ""),
            "edit_kind": signature[0],
            "edit_ordinal": signature[1],
            "count_delta": signature[2],
            "leading_identity": signature[3],
            "post_edit_uniform_shift": signature[4],
            "matching_consensus_rows": len(matching),
            "consensus_reference_members": matching[0].get("resolved_member_keys", "") if supported else "",
            "companion_consensus_supported": supported,
            "classification": "model_supported_by_independent_companion_topology" if supported else "model_not_supported_by_independent_companion_topology",
        })
    selected = eligible_models[0] if len(eligible_models) == 1 else ""
    decision = {
        "pair_id": pair_id,
        "normalized_path": pair.get("normalized_path", ""),
        "family_id": family,
        "member_key": member_key,
        "member_name": pair.get("member_name", ""),
        "source_values": pair.get("source_values", ""),
        "target_values": pair.get("target_values", ""),
        "candidate_model_rows": len(candidate_models),
        "consensus_supported_model_rows": len(eligible_models),
        "selected_model_id": selected,
        "selection_basis": "unique_independent_companion_topology_consensus" if selected else "",
        "classification": "occurrence_identity_resolved_by_companion_topology_consensus" if selected else "occurrence_identity_unresolved_after_companion_topology_binding",
    }
    return decision, bindings


def validate_prerequisites(stage108_root: Path, stage109_root: Path, stage111_root: Path, stage114_root: Path, stage115_root: Path) -> None:
    s108 = load_json(stage108_root / "SUMMARY.json")
    require(s108.get("status") == "underscore_archive_retirement_closed", "stage108 retirement closure missing")
    require(parse_bool(s108.get("retirement_complete")), "stage108 retirement not complete")
    s109 = load_json(stage109_root / "SUMMARY.json")
    require(parse_int(s109.get("revalidated_occurrence_rows"), -1) == 1814, "stage109 occurrence count mismatch")
    s111 = load_json(stage111_root / "SUMMARY.json")
    require(parse_int(s111.get("unresolved_one_edit_pair_rows"), 7) == 7, "stage111 unresolved pair count drifted")
    s114 = load_json(stage114_root / "SUMMARY.json")
    require(parse_int(s114.get("newly_resolved_noncanary_pair_rows"), -1) == 2, "stage114 resolved count drifted")
    s115 = load_json(stage115_root / "SUMMARY.json")
    require(s115.get("tool_version") == "0.1.30", "stage115 tool version mismatch")
    require(parse_int(s115.get("stage114_pair_rows"), -1) == EXPECTED_STAGE115_PAIR_ROWS, "stage115 pair count mismatch")
    require(parse_int(s115.get("total_resolved_noncanary_pair_rows_after_stage115"), -1) == EXPECTED_STAGE115_RESOLVED_NONCANARY, "stage115 resolved count mismatch")
    require(parse_int(s115.get("still_unresolved_noncanary_pair_rows"), -1) == EXPECTED_STAGE115_UNRESOLVED_NONCANARY, "stage115 unresolved count mismatch")
    require(parse_bool(s115.get("canary_identity_preserved")), "stage115 canary not preserved")


def build_report(project_root: Path, *, create_archive: bool = True, report_root: Path | None = None) -> tuple[Path, Path | None, dict[str, Any]]:
    project_root = project_root.resolve()
    reports = (report_root or project_root / ".local/reports/quartet_restoration").resolve()
    reports.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="br_stage116_") as temp_name:
        temporary = Path(temp_name)
        stage108_root = locate(reports, STAGE108_DIR, STAGE108_ARCHIVE, temporary / "108")
        stage109_root = locate(reports, STAGE109_DIR, STAGE109_ARCHIVE, temporary / "109")
        stage111_root = locate(reports, STAGE111_DIR, STAGE111_ARCHIVE, temporary / "111")
        stage114_root = locate(reports, STAGE114_DIR, STAGE114_ARCHIVE, temporary / "114")
        stage115_root = locate(reports, STAGE115_DIR, STAGE115_ARCHIVE, temporary / "115")
        validate_prerequisites(stage108_root, stage109_root, stage111_root, stage114_root, stage115_root)

        pair_rows = read_tsv(stage111_root / "SLOT_LIGHT_EDIT_NORMALIZED_SECTION_PAIR_DECISIONS.tsv")
        model_rows = read_tsv(stage111_root / "SLOT_LIGHT_EDIT_NORMALIZED_ALIGNMENT_MODELS.tsv")
        stage115_decisions = read_tsv(stage115_root / "SLOT_LIGHT_TRAILER_EXACT_FIELD_PAIR_DECISIONS.tsv")
        require(len(stage115_decisions) == EXPECTED_STAGE115_PAIR_ROWS, "stage115 decision table count mismatch")
        pair_by_id = {row.get("pair_id", ""): row for row in pair_rows}
        model_by_id = {row.get("model_id", ""): row for row in model_rows}
        models_by_pair: dict[str, list[dict[str, str]]] = defaultdict(list)
        for row in model_rows:
            models_by_pair[row.get("pair_id", "")].append(row)

        resolved_noncanary = [row for row in stage115_decisions if row.get("classification") in {
            "stage114_algebraic_identity_preserved",
            "occurrence_identity_resolved_by_exact_trailer_field_continuity",
        }]
        unresolved = [row for row in stage115_decisions if row.get("classification") == "occurrence_identity_unresolved_after_exact_trailer_field_continuity"]
        canary_rows = [row for row in stage115_decisions if row.get("classification") == "canary_identity_preserved"]
        require(len(resolved_noncanary) == EXPECTED_STAGE115_RESOLVED_NONCANARY, "resolved non-canary decision count mismatch")
        require(len(unresolved) == EXPECTED_STAGE115_UNRESOLVED_NONCANARY, "unresolved decision count mismatch")
        require(len(canary_rows) == EXPECTED_STAGE115_CANARY_ROWS and canary_rows[0].get("member_key", "").casefold() == CANARY_MEMBER_KEY, "canary row mismatch")

        consensus_rows = build_consensus_classes(resolved_noncanary, model_by_id, pair_by_id)
        reference_rows: list[dict[str, Any]] = []
        for row in resolved_noncanary:
            member_key = row.get("member_key", "").casefold()
            family = family_for_member(member_key)
            if not family:
                continue
            model_id = row.get("selected_model_id", "")
            model = model_by_id[model_id]
            signature = model_topology_signature(model, pair_by_id[row.get("pair_id", "")])
            reference_rows.append({
                "family_id": family,
                "pair_id": row.get("pair_id", ""),
                "member_key": member_key,
                "member_name": row.get("member_name", ""),
                "selected_model_id": model_id,
                "selection_basis": row.get("selection_basis", ""),
                "edit_kind": signature[0],
                "edit_ordinal": signature[1],
                "count_delta": signature[2],
                "leading_identity": signature[3],
                "post_edit_uniform_shift": signature[4],
                "classification": "independently_resolved_companion_topology_reference",
            })

        binding_rows: list[dict[str, Any]] = []
        new_decisions: list[dict[str, Any]] = []
        for row in unresolved:
            pair_id = row.get("pair_id", "")
            require(pair_id in pair_by_id, f"unresolved pair missing from stage111: {pair_id}")
            candidates = [model for model in models_by_pair[pair_id] if model.get("edit_kind", "") in {"target_insertion_piecewise_offset_shift", "target_deletion_piecewise_offset_shift"}]
            decision, bindings = decide_unresolved_pair(pair_by_id[pair_id], candidates, consensus_rows)
            new_decisions.append(decision)
            binding_rows.extend(bindings)

        newly_resolved = [row for row in new_decisions if row.get("classification") == "occurrence_identity_resolved_by_companion_topology_consensus"]
        still_unresolved = [row for row in new_decisions if row.get("classification") == "occurrence_identity_unresolved_after_companion_topology_binding"]
        require(len(newly_resolved) == EXPECTED_NEWLY_RESOLVED, f"unexpected stage116 resolved count: {len(newly_resolved)}")
        require(len(still_unresolved) == EXPECTED_STILL_UNRESOLVED, f"unexpected stage116 unresolved count: {len(still_unresolved)}")
        require(newly_resolved[0].get("member_key") == "e_pc02_m4_beardivision.g1e#0", "unexpected stage116 resolved member")
        require(str(newly_resolved[0].get("selected_model_id", "")).endswith("|target_insertion_piecewise_offset_shift|1"), "unexpected beardivision model")

        family_inventory_rows: list[dict[str, Any]] = []
        decision_by_member = {row.get("member_key", "").casefold(): row for row in stage115_decisions}
        for family, members in FAMILY_MEMBERS.items():
            for member in members:
                row = decision_by_member.get(member)
                require(row is not None, f"bounded family member missing from stage115: {member}")
                family_inventory_rows.append({
                    "family_id": family,
                    "member_key": member,
                    "member_name": row.get("member_name", ""),
                    "stage115_classification": row.get("classification", ""),
                    "stage115_selected_model_id": row.get("selected_model_id", ""),
                    "source_values": row.get("source_values", ""),
                    "target_values": row.get("target_values", ""),
                    "classification": "bounded_companion_family_member",
                })

        canary = canary_rows[0]
        skipped_rows: list[dict[str, Any]] = []
        summary = {
            "type": "br_quartet_restoration_reflector_slot_light_companion_topology_binding_evidence_summary",
            "format_version": 1,
            "tool_version": TOOL_VERSION,
            "status": "bounded_companion_topology_binding_audited_semantics_unresolved_no_render_write",
            "stage115_pair_rows": len(stage115_decisions),
            "stage115_preserved_resolved_noncanary_pair_rows": len(resolved_noncanary),
            "stage115_input_unresolved_noncanary_pair_rows": len(unresolved),
            "bounded_companion_family_rows": len(FAMILY_MEMBERS),
            "bounded_companion_member_rows": len(family_inventory_rows),
            "independently_resolved_companion_reference_rows": len(reference_rows),
            "companion_consensus_class_rows": len(consensus_rows),
            "eligible_companion_consensus_class_rows": sum(parse_bool(row.get("consensus_eligible")) for row in consensus_rows),
            "candidate_model_binding_rows": len(binding_rows),
            "newly_resolved_noncanary_pair_rows": len(newly_resolved),
            "still_unresolved_noncanary_pair_rows": len(still_unresolved),
            "total_resolved_noncanary_pair_rows_after_stage116": len(resolved_noncanary) + len(newly_resolved),
            "canary_identity_preserved": True,
            "prototype_candidate_rows": 0,
            "technical_leaf_domain_semantics_resolved": False,
            "brightness_semantics_confirmed": False,
            "intensity_semantics_confirmed": False,
            "censorship_semantics_confirmed": False,
            "skipped_rows": 0,
            "policy": {
                "official_nonunderscore_archives_are_canonical": True,
                "underscore_archives_required": False,
                "bounded_family_membership_is_semantic_evidence": False,
                "minimum_independent_resolved_companion_members": 2,
                "unresolved_pairs_contribute_to_consensus": False,
                "paired_float_leaf_values_used_for_identity": False,
                "numeric_closeness_used": False,
                "field_semantic_names_assigned": False,
                "G1E_G1EM_write_authorized": False,
                "pak_repack_authorized": False,
                "profile_or_registry_write_authorized": False,
                "installed_game_modified": False,
            },
            "next_action": "Upload this report. Preserve the stage-114, stage-115 and new companion-topology identities. Keep the two swordflash companion pairs unresolved; their two deletion ordinals remain topology-symmetric. Move next to read-only G1EM/section-table topology binding for only those two members, without value or distance heuristics.",
        }

        output_dir = reports / REPORT_DIR
        if output_dir.exists():
            shutil.rmtree(output_dir)
        output_dir.mkdir(parents=True)
        write_tsv(output_dir / "SLOT_LIGHT_COMPANION_FAMILY_INVENTORY.tsv", [
            "family_id", "member_key", "member_name", "stage115_classification", "stage115_selected_model_id", "source_values", "target_values", "classification",
        ], family_inventory_rows)
        write_tsv(output_dir / "SLOT_LIGHT_RESOLVED_COMPANION_TOPOLOGY_REFERENCES.tsv", [
            "family_id", "pair_id", "member_key", "member_name", "selected_model_id", "selection_basis", "edit_kind", "edit_ordinal", "count_delta", "leading_identity", "post_edit_uniform_shift", "classification",
        ], reference_rows)
        write_tsv(output_dir / "SLOT_LIGHT_COMPANION_TOPOLOGY_CONSENSUS_CLASSES.tsv", [
            "family_id", "edit_kind", "edit_ordinal", "count_delta", "leading_identity", "post_edit_uniform_shift", "resolved_reference_rows", "distinct_resolved_members", "resolved_member_keys", "consensus_eligible", "classification",
        ], consensus_rows)
        write_tsv(output_dir / "SLOT_LIGHT_UNRESOLVED_COMPANION_MODEL_BINDING.tsv", [
            "pair_id", "family_id", "member_key", "member_name", "model_id", "edit_kind", "edit_ordinal", "count_delta", "leading_identity", "post_edit_uniform_shift", "matching_consensus_rows", "consensus_reference_members", "companion_consensus_supported", "classification",
        ], binding_rows)
        write_tsv(output_dir / "SLOT_LIGHT_COMPANION_TOPOLOGY_PAIR_DECISIONS.tsv", [
            "pair_id", "normalized_path", "family_id", "member_key", "member_name", "source_values", "target_values", "candidate_model_rows", "consensus_supported_model_rows", "selected_model_id", "selection_basis", "classification",
        ], new_decisions)
        write_tsv(output_dir / "SLOT_LIGHT_COMPANION_TOPOLOGY_CANARY_CHECK.tsv", ["question", "answer", "classification"], [
            {"question": "immutable canary selected model", "answer": canary.get("selected_model_id", ""), "classification": "stage99_stage112_stage113_stage114_stage115_input"},
            {"question": "canary used as companion consensus reference", "answer": False, "classification": "excluded_from_family_consensus"},
            {"question": "unresolved pairs used as consensus support", "answer": False, "classification": "independent_support_only"},
            {"question": "paired-float leaf values used", "answer": False, "classification": "topology_only"},
            {"question": "numeric closeness used", "answer": False, "classification": "exact_topology_only"},
        ])
        write_tsv(output_dir / "SLOT_LIGHT_COMPANION_TOPOLOGY_BINDING_SKIPPED.tsv", ["scope", "identity", "reason"], skipped_rows)
        (output_dir / "SUMMARY.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

        archive_path: Path | None = None
        if create_archive:
            archive_path = reports / REPORT_NAME
            make_archive(output_dir, archive_path)
        return output_dir, archive_path, summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path, default=PROJECT_ROOT_DEFAULT)
    parser.add_argument("--report-root", type=Path)
    parser.add_argument("--no-archive", action="store_true")
    args = parser.parse_args()
    output, archive, summary = build_report(args.project_root, create_archive=not args.no_archive, report_root=args.report_root)
    print(json.dumps({"output_dir": str(output), "archive": str(archive) if archive else "", "summary": summary}, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
