#!/usr/bin/env python3
"""Calibrate section-table model selectivity before using it on swordflash.

Stage 117 established that both remaining PC00 swordflash pairs have no exact
same-stem G1EM companion.  Their G1E section tables nevertheless prefer one of
the two deletion models: deletion ordinal 2 has zero table conflicts, while
deletion ordinal 1 has one conflict.  That preference is not authoritative by
itself.

This read-only stage therefore rehydrates only the bounded PC00 and PC02
parent effect containers and evaluates the identical section-table rule on six
one-edit identities that were resolved independently by stages 99, 114, 115
and 116.  The table rule may be applied to swordflash only if it uniquely
recovers every independent reference, including the immutable PC02 canary,
across both parent containers.  A missing, ambiguous or incorrect calibration
result leaves both swordflash pairs unresolved.  No value semantics are
assigned and no game payload is written.
"""
from __future__ import annotations

import argparse
import csv
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
from collections import defaultdict
from pathlib import Path, PurePosixPath
from typing import Any, Callable, Iterable, Mapping, Sequence

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT_DEFAULT = SCRIPT_DIR.parent.parent
TOOL_VERSION = "0.1.35"
REPORT_NAME = "BR_quartet_restoration_reflector_slot_light_section_table_model_selectivity_calibration_evidence.tar.zst"
REPORT_DIR = "reflector_slot_light_section_table_model_selectivity_calibration_evidence"

STAGE108_DIR = "br1_official_source_retirement_closure_evidence"
STAGE108_ARCHIVE = "BR_quartet_restoration_br1_official_source_retirement_closure_evidence.tar.zst"
STAGE109_DIR = "reflector_slot_light_sibling_section_layout_evidence"
STAGE109_ARCHIVE = "BR_quartet_restoration_reflector_slot_light_sibling_section_layout_evidence.tar.zst"
STAGE111_DIR = "reflector_slot_light_edit_normalized_layout_alignment_evidence"
STAGE111_ARCHIVE = "BR_quartet_restoration_reflector_slot_light_edit_normalized_layout_alignment_evidence.tar.zst"
STAGE115_DIR = "reflector_slot_light_trailer_exact_field_continuity_evidence"
STAGE115_ARCHIVE = "BR_quartet_restoration_reflector_slot_light_trailer_exact_field_continuity_evidence.tar.zst"
STAGE116_DIR = "reflector_slot_light_companion_topology_binding_evidence"
STAGE116_ARCHIVE = "BR_quartet_restoration_reflector_slot_light_companion_topology_binding_evidence.tar.zst"
STAGE117_DIR = "reflector_slot_light_swordflash_g1em_section_table_binding_evidence"
STAGE117_ARCHIVE = "BR_quartet_restoration_reflector_slot_light_swordflash_g1em_section_table_binding_evidence.tar.zst"
STAGE79_DIR = "reflector_character_slot_render_member_evidence"
STAGE79_ARCHIVE = "BR_quartet_restoration_reflector_character_slot_render_member_evidence.tar.zst"

PC00_CONTAINER = "data/x64/effect/1000_pc00.elixir.gz"
PC02_CONTAINER = "data/x64/effect/1002_pc02.elixir.gz"
PARENT_CONTAINERS = (PC00_CONTAINER, PC02_CONTAINER)
CANARY_MEMBER = "e_pc02_w5_ringlight_01.g1e#0"
SWORDFLASH_MEMBERS = {
    "e_pc00_swordflash_02_bullet.g1e#0",
    "e_pc00_swordflash_02_bullet_x.g1e#0",
}
EXPECTED_STAGE109_OCCURRENCES = 1814
EXPECTED_STAGE111_MODELS = 23
EXPECTED_STAGE115_RESOLVED_NONCANARY = 4
EXPECTED_STAGE116_RESOLVED_NONCANARY = 5
EXPECTED_STAGE117_UNRESOLVED = 2
EXPECTED_REFERENCE_PAIRS = 6
EXPECTED_UNRESOLVED_PAIRS = 2
EXPECTED_TOTAL_ONE_EDIT_PAIRS = 8
EXPECTED_TOTAL_ONE_EDIT_MODELS = 23
MIN_TABLE_SUPPORT_ROWS = 2
MIN_DISTINCT_TABLES = 2


class Stage118Error(RuntimeError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise Stage118Error(message)


def progress(message: str) -> None:
    print(f"[stage118] {message}", file=sys.stderr, flush=True)


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
        raise Stage118Error(f"invalid JSON {path}: {exc}") from exc
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


def load_module(path: Path, name: str) -> Any:
    require(path.is_file(), f"missing prerequisite collector: {path}")
    spec = importlib.util.spec_from_file_location(name, path)
    require(spec is not None and spec.loader is not None, f"cannot load module: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def parse_pairs(text: str) -> set[tuple[int, int]]:
    pairs: set[tuple[int, int]] = set()
    for item in str(text).split(";"):
        if not item:
            continue
        left, sep, right = item.partition("->")
        require(sep == "->", f"invalid ordinal mapping: {item}")
        pairs.add((parse_int(left, -1), parse_int(right, -1)))
    return pairs


def validate_parent_scopes(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []
    for normalized_path in PARENT_CONTAINERS:
        scoped = [dict(row) for row in rows if str(row.get("normalized_path", "")).casefold() == normalized_path]
        require(scoped, f"missing parent scope rows for {normalized_path}")
        parent_keys = {
            (str(row.get("candidate_id", "")), str(row.get("normalized_path", "")).casefold())
            for row in scoped
        }
        require(len(parent_keys) == 1, f"expected one parent identity for {normalized_path}, found {len(parent_keys)}")
        candidate_id, actual_path = next(iter(parent_keys))
        require(candidate_id and actual_path == normalized_path, f"invalid parent identity for {normalized_path}")
        selected.extend(scoped)
    return sorted(selected, key=lambda row: (str(row.get("normalized_path", "")), str(row.get("member_key", ""))))


def evaluate_section_table_model(
    model: Mapping[str, Any],
    source_table: Sequence[Mapping[str, Any]],
    target_table: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    mapping = parse_pairs(str(model.get("matched_ordinal_pairs", "")))
    support: set[tuple[int, int, int, int, int]] = set()
    conflicts: set[tuple[int, int, int, int, int]] = set()
    for left in source_table:
        for right in target_table:
            if parse_int(left.get("table_index"), -1) != parse_int(right.get("table_index"), -1):
                continue
            if parse_int(left.get("entry_index"), -1) != parse_int(right.get("entry_index"), -1):
                continue
            if parse_int(left.get("record_relative_dword"), 9999) != parse_int(right.get("record_relative_dword"), 9998):
                continue
            pair = (parse_int(left.get("occurrence_ordinal"), -1), parse_int(right.get("occurrence_ordinal"), -1))
            identity = (
                parse_int(left.get("table_index"), -1),
                parse_int(left.get("entry_index"), -1),
                parse_int(left.get("record_relative_dword"), 9999),
                pair[0], pair[1],
            )
            (support if pair in mapping else conflicts).add(identity)
    tables = {item[0] for item in support}
    eligible = len(support) >= MIN_TABLE_SUPPORT_ROWS and len(tables) >= MIN_DISTINCT_TABLES and not conflicts
    return {
        "pair_id": model.get("pair_id", ""),
        "model_id": model.get("model_id", ""),
        "normalized_path": model.get("normalized_path", ""),
        "member_key": model.get("member_key", ""),
        "member_name": model.get("member_name", ""),
        "edit_kind": model.get("edit_kind", ""),
        "edit_ordinal": model.get("edit_ordinal", ""),
        "section_table_support_rows": len(support),
        "section_table_support_distinct_tables": len(tables),
        "section_table_conflict_rows": len(conflicts),
        "section_table_model_eligible": eligible,
        "classification": "section_table_model_eligible" if eligible else "section_table_model_insufficient_or_conflicting",
    }


def calibrate_reference(pair: Mapping[str, Any], known_model_id: str, model_rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    eligible = [row for row in model_rows if parse_bool(row.get("section_table_model_eligible"))]
    selected = eligible[0] if len(eligible) == 1 else None
    passed = bool(selected and selected.get("model_id") == known_model_id)
    return {
        "pair_id": pair.get("pair_id", ""),
        "normalized_path": pair.get("normalized_path", ""),
        "member_key": pair.get("member_key", ""),
        "member_name": pair.get("member_name", ""),
        "known_model_id": known_model_id,
        "candidate_model_rows": len(model_rows),
        "eligible_section_table_model_rows": len(eligible),
        "selected_section_table_model_id": selected.get("model_id", "") if selected else "",
        "calibration_reference_passed": passed,
        "classification": "independent_identity_recovered_by_section_table_rule" if passed else "section_table_rule_failed_independent_reference",
    }


def decide_swordflash(
    pair: Mapping[str, Any], model_rows: Sequence[Mapping[str, Any]], calibration_authoritative: bool,
) -> dict[str, Any]:
    eligible = [row for row in model_rows if parse_bool(row.get("section_table_model_eligible"))]
    selected = eligible[0] if calibration_authoritative and len(eligible) == 1 else None
    if selected:
        classification = "occurrence_identity_resolved_by_calibrated_section_table_selectivity"
        basis = "all_independent_references_recovered_then_unique_zero_conflict_section_table_model"
    elif not calibration_authoritative:
        classification = "occurrence_identity_unresolved_section_table_rule_not_authoritatively_calibrated"
        basis = ""
    else:
        classification = "occurrence_identity_unresolved_after_calibrated_section_table_selectivity"
        basis = ""
    return {
        "pair_id": pair.get("pair_id", ""),
        "normalized_path": pair.get("normalized_path", ""),
        "member_key": pair.get("member_key", ""),
        "member_name": pair.get("member_name", ""),
        "source_values": pair.get("source_values", ""),
        "target_values": pair.get("target_values", ""),
        "candidate_model_rows": len(model_rows),
        "eligible_section_table_model_rows": len(eligible),
        "selected_model_id": selected.get("model_id", "") if selected else "",
        "selection_basis": basis,
        "classification": classification,
    }


def validate_summaries(
    stage108_root: Path, stage109_root: Path, stage111_root: Path,
    stage115_root: Path, stage116_root: Path, stage117_root: Path,
) -> tuple[dict[str, Any], ...]:
    summaries = tuple(load_json(root / "SUMMARY.json") for root in (
        stage108_root, stage109_root, stage111_root, stage115_root, stage116_root, stage117_root,
    ))
    s108, s109, s111, s115, s116, s117 = summaries
    require(s108.get("status") == "underscore_archive_retirement_closed" and parse_bool(s108.get("retirement_complete")), "stage108 retirement closure mismatch")
    require(s109.get("tool_version") == "0.1.23" and parse_int(s109.get("revalidated_occurrence_rows"), -1) == EXPECTED_STAGE109_OCCURRENCES, "stage109 summary mismatch")
    require(s111.get("tool_version") == "0.1.25" and parse_int(s111.get("one_edit_alignment_model_rows"), -1) == EXPECTED_STAGE111_MODELS, "stage111 summary mismatch")
    require(s115.get("tool_version") == "0.1.30" and parse_int(s115.get("total_resolved_noncanary_pair_rows_after_stage115"), -1) == EXPECTED_STAGE115_RESOLVED_NONCANARY, "stage115 summary mismatch")
    require(s116.get("tool_version") == "0.1.31" and parse_int(s116.get("total_resolved_noncanary_pair_rows_after_stage116"), -1) == EXPECTED_STAGE116_RESOLVED_NONCANARY, "stage116 summary mismatch")
    require(s117.get("tool_version") == "0.1.34" and parse_int(s117.get("still_unresolved_noncanary_pair_rows"), -1) == EXPECTED_STAGE117_UNRESOLVED, "stage117 summary mismatch")
    require(parse_int(s117.get("same_stem_g1em_companion_rows"), -1) == 0, "stage117 same-stem G1EM state drift")
    require(parse_bool(s115.get("canary_identity_preserved")) and parse_bool(s116.get("canary_identity_preserved")) and parse_bool(s117.get("canary_identity_preserved")), "immutable canary drift")
    require(all(parse_int(summary.get("prototype_candidate_rows"), -1) == 0 for summary in (s115, s116, s117)), "forbidden prototype output in prerequisites")
    return summaries


def build_known_identity_map(stage115_root: Path, stage116_root: Path) -> dict[str, str]:
    known: dict[str, str] = {}
    for path in (
        stage115_root / "SLOT_LIGHT_TRAILER_EXACT_FIELD_PAIR_DECISIONS.tsv",
        stage116_root / "SLOT_LIGHT_COMPANION_TOPOLOGY_PAIR_DECISIONS.tsv",
    ):
        for row in read_tsv(path):
            selected = str(row.get("selected_model_id", ""))
            if not selected:
                continue
            member = str(row.get("member_key", "")).casefold()
            if member in known:
                require(known[member] == selected, f"conflicting independent identity for {member}")
            known[member] = selected
    require(len(known) == EXPECTED_REFERENCE_PAIRS, f"expected {EXPECTED_REFERENCE_PAIRS} independent references, found {len(known)}")
    require(CANARY_MEMBER in known, "immutable PC02 canary missing from independent reference map")
    require(not (SWORDFLASH_MEMBERS & set(known)), "unresolved swordflash leaked into calibration references")
    return known


def crosscheck_stage117(stage117_root: Path, recalculated_rows: Sequence[Mapping[str, Any]]) -> None:
    old = read_tsv(stage117_root / "SLOT_LIGHT_SWORDFLASH_MODEL_TOPOLOGY_SUPPORT.tsv")
    old_map = {
        str(row.get("model_id", "")): (
            parse_int(row.get("section_table_support_rows"), -1),
            parse_int(row.get("section_table_support_distinct_tables"), -1),
            parse_int(row.get("section_table_conflict_rows"), -1),
        )
        for row in old
    }
    new_map = {
        str(row.get("model_id", "")): (
            parse_int(row.get("section_table_support_rows"), -1),
            parse_int(row.get("section_table_support_distinct_tables"), -1),
            parse_int(row.get("section_table_conflict_rows"), -1),
        )
        for row in recalculated_rows
        if str(row.get("member_key", "")).casefold() in SWORDFLASH_MEMBERS
    }
    require(old_map == new_map and len(new_map) == 4, "stage117 section-table support cross-check mismatch")


def build_report(
    project_root: Path,
    *,
    create_archive: bool = True,
    workspace_root: Path | None = None,
    report_root: Path | None = None,
    rules_file: Path | None = None,
    maximum_earc_bytes: int = 512 * 1024 * 1024,
    container_loader: Callable[..., tuple[list[dict[str, Any]], list[dict[str, Any]]]] | None = None,
) -> tuple[Path, Path | None, dict[str, Any]]:
    project_root = project_root.resolve()
    reports = (report_root or project_root / ".local/reports/quartet_restoration").resolve()
    workspace = (workspace_root or project_root / ".local/build/quartet_restoration").resolve()
    require(reports.is_dir(), f"missing report root: {reports}")

    stage81 = load_module(SCRIPT_DIR / "collect_reflector_ringlight_control_callsite_evidence.py", "stage81_for_stage118")
    stage86 = load_module(SCRIPT_DIR / "collect_reflector_slot_light_shared_record_template_evidence.py", "stage86_for_stage118")
    stage90 = load_module(SCRIPT_DIR / "collect_reflector_slot_light_target_section_layout_evidence.py", "stage90_for_stage118")
    stage117 = load_module(SCRIPT_DIR / "collect_reflector_slot_light_swordflash_g1em_section_table_binding_evidence.py", "stage117_for_stage118")

    with tempfile.TemporaryDirectory(prefix="br-stage118-") as temporary_name:
        temporary = Path(temporary_name)
        r108 = locate(reports, STAGE108_DIR, STAGE108_ARCHIVE, temporary / "108")
        r109 = locate(reports, STAGE109_DIR, STAGE109_ARCHIVE, temporary / "109")
        r111 = locate(reports, STAGE111_DIR, STAGE111_ARCHIVE, temporary / "111")
        r115 = locate(reports, STAGE115_DIR, STAGE115_ARCHIVE, temporary / "115")
        r116 = locate(reports, STAGE116_DIR, STAGE116_ARCHIVE, temporary / "116")
        r117 = locate(reports, STAGE117_DIR, STAGE117_ARCHIVE, temporary / "117")
        r79 = locate(reports, STAGE79_DIR, STAGE79_ARCHIVE, temporary / "79")
        s108, s109, s111, s115, s116, s117 = validate_summaries(r108, r109, r111, r115, r116, r117)
        stage81.validate_stage79(r79)

        known_map = build_known_identity_map(r115, r116)
        pair_rows_all = read_tsv(r111 / "SLOT_LIGHT_EDIT_NORMALIZED_SECTION_PAIR_CANDIDATES.tsv")
        model_rows_all = read_tsv(r111 / "SLOT_LIGHT_EDIT_NORMALIZED_ALIGNMENT_MODELS.tsv")
        occurrence_rows = read_tsv(r109 / "SLOT_LIGHT_SIBLING_SECTION_LAYOUT_OCCURRENCES.tsv")
        one_edit_pairs = [row for row in pair_rows_all if parse_int(row.get("alignment_model_rows"), 0) > 1]
        one_edit_models = [row for row in model_rows_all if str(row.get("edit_kind", "")) != "zero_edit_uniform_offset_shift"]
        require(len(one_edit_pairs) == EXPECTED_TOTAL_ONE_EDIT_PAIRS, f"one-edit pair count mismatch: {len(one_edit_pairs)}")
        require(len(one_edit_models) == EXPECTED_TOTAL_ONE_EDIT_MODELS, f"one-edit model count mismatch: {len(one_edit_models)}")
        pair_by_member = {str(row.get("member_key", "")).casefold(): row for row in one_edit_pairs}
        require(set(pair_by_member) == set(known_map) | SWORDFLASH_MEMBERS, "one-edit member partition mismatch")

        scope_rows = validate_parent_scopes(stage81.select_parent_scope(r79))
        actual_rules = rules_file or project_root / "titles/blue_reflection/modules/quartet_restoration/mappings/effect_material_rules.tsv"
        loader = container_loader or stage81.load_parent_containers
        progress("rehydrating bounded PC00 and PC02 parent effect containers")
        containers, loader_skipped = loader(scope_rows=scope_rows, workspace_root=workspace, report_root=reports, rules_file=actual_rules, maximum_earc_bytes=maximum_earc_bytes)
        require(not loader_skipped and len(containers) == 2, "bounded parent container rehydration mismatch")
        pair_payloads, _all_pairs = stage86.index_pairs(containers)

        occurrences: dict[tuple[str, str], list[dict[str, str]]] = defaultdict(list)
        for row in occurrence_rows:
            member = str(row.get("member_key", "")).casefold()
            if member in pair_by_member:
                occurrences[(member, str(row.get("side", "")).casefold())].append(row)
        for rows in occurrences.values():
            rows.sort(key=lambda row: parse_int(row.get("template_ordinal_within_section"), -1))

        binding_rows: list[dict[str, Any]] = []
        support_rows: list[dict[str, Any]] = []
        reference_inventory: list[dict[str, Any]] = []
        reference_decisions: list[dict[str, Any]] = []
        skipped_rows: list[dict[str, Any]] = []

        for member, pair in sorted(pair_by_member.items()):
            normalized_path = str(pair.get("normalized_path", "")).casefold()
            payload_pair = pair_payloads.get((normalized_path, member))
            require(payload_pair is not None, f"missing one-edit G1E pair: {member}")
            source_occ = occurrences[(member, "source")]
            target_occ = occurrences[(member, "target")]
            require(source_occ and target_occ, f"missing occurrence rows for {member}")
            source_endpoint = parse_int(pair.get("source_endpoint"), -1)
            target_endpoint = parse_int(pair.get("target_endpoint"), -1)
            source_payload = bytes(payload_pair.get("source_payload") or b"")
            target_payload = bytes(payload_pair.get("target_payload") or b"")
            source_header = stage90.parse_section_header(source_payload, source_endpoint)
            target_header = stage90.parse_section_header(target_payload, target_endpoint)
            require(parse_bool(source_header.get("exact_layout")) and parse_bool(target_header.get("exact_layout")), f"invalid section header for {member}")
            source_table = stage117.section_binding_candidates(stage117.extract_section_table_entries(source_payload, source_endpoint, source_header), source_occ, "source")
            target_table = stage117.section_binding_candidates(stage117.extract_section_table_entries(target_payload, target_endpoint, target_header), target_occ, "target")
            for row in source_table + target_table:
                binding_rows.append({"member_key": member, "member_name": pair.get("member_name", ""), **row})
            models = [row for row in one_edit_models if str(row.get("member_key", "")).casefold() == member]
            require(len(models) == parse_int(pair.get("alignment_model_rows"), -1), f"model count mismatch for {member}")
            evaluated = [evaluate_section_table_model(model, source_table, target_table) for model in models]
            support_rows.extend(evaluated)
            if member in known_map:
                decision = calibrate_reference(pair, known_map[member], evaluated)
                reference_decisions.append(decision)
                reference_inventory.append({
                    "pair_id": pair.get("pair_id", ""), "normalized_path": normalized_path,
                    "member_key": member, "member_name": pair.get("member_name", ""),
                    "known_model_id": known_map[member],
                    "identity_source": "immutable_pc02_canary" if member == CANARY_MEMBER else "independent_stage114_115_116_resolution",
                    "candidate_model_rows": len(models),
                })

        crosscheck_stage117(r117, support_rows)
        reference_containers = {str(row.get("normalized_path", "")) for row in reference_inventory}
        all_reference_passed = (
            len(reference_decisions) == EXPECTED_REFERENCE_PAIRS
            and all(parse_bool(row.get("calibration_reference_passed")) for row in reference_decisions)
            and len(reference_containers) == 2
        )
        canary_passed = any(
            str(row.get("member_key", "")).casefold() == CANARY_MEMBER and parse_bool(row.get("calibration_reference_passed"))
            for row in reference_decisions
        )
        calibration_authoritative = all_reference_passed and canary_passed

        swordflash_decisions: list[dict[str, Any]] = []
        for member in sorted(SWORDFLASH_MEMBERS):
            pair = pair_by_member[member]
            models = [row for row in support_rows if str(row.get("member_key", "")).casefold() == member]
            swordflash_decisions.append(decide_swordflash(pair, models, calibration_authoritative))

        newly_resolved = sum(bool(row.get("selected_model_id")) for row in swordflash_decisions)
        still_unresolved = len(swordflash_decisions) - newly_resolved
        if not calibration_authoritative:
            skipped_rows.append({
                "scope": "section_table_calibration", "identity": "all_independent_references",
                "reason": "section_table_rule_not_authoritative_all_swordflash_pairs_remain_unresolved",
            })

        canary_rows = [
            {"question": "were all six independent one-edit references recovered by the same section-table rule", "answer": all_reference_passed, "classification": "calibration_reference_gate"},
            {"question": "was the immutable PC02 canary recovered exactly", "answer": canary_passed, "classification": "immutable_canary_gate"},
            {"question": "did calibration cover both bounded parent containers", "answer": len(reference_containers) == 2, "classification": "cross_container_calibration_gate"},
            {"question": "is section-table-only selection authoritative for swordflash", "answer": calibration_authoritative, "classification": "all_gates_required"},
            {"question": "were paired-float values used for identity", "answer": False, "classification": "topology_only"},
            {"question": "was numeric closeness used", "answer": False, "classification": "exact_binding_only"},
        ]

        output = reports / REPORT_DIR
        if output.exists():
            import shutil
            shutil.rmtree(output)
        output.mkdir(parents=True)
        write_tsv(output / "SLOT_LIGHT_SECTION_TABLE_CALIBRATION_REFERENCE_INVENTORY.tsv", [
            "pair_id", "normalized_path", "member_key", "member_name", "known_model_id", "identity_source", "candidate_model_rows",
        ], reference_inventory)
        write_tsv(output / "SLOT_LIGHT_SECTION_TABLE_CALIBRATION_BINDINGS.tsv", [
            "member_key", "member_name", "side", "table_index", "entry_index", "entry_relative_offset", "entry_absolute_offset",
            "entry_u32_hex", "entry_i32", "signed_anchor", "occurrence_ordinal", "record_start", "record_relative_dword",
        ], binding_rows)
        write_tsv(output / "SLOT_LIGHT_SECTION_TABLE_CALIBRATION_MODEL_SUPPORT.tsv", [
            "pair_id", "model_id", "normalized_path", "member_key", "member_name", "edit_kind", "edit_ordinal",
            "section_table_support_rows", "section_table_support_distinct_tables", "section_table_conflict_rows",
            "section_table_model_eligible", "classification",
        ], support_rows)
        write_tsv(output / "SLOT_LIGHT_SECTION_TABLE_CALIBRATION_REFERENCE_DECISIONS.tsv", [
            "pair_id", "normalized_path", "member_key", "member_name", "known_model_id", "candidate_model_rows",
            "eligible_section_table_model_rows", "selected_section_table_model_id", "calibration_reference_passed", "classification",
        ], reference_decisions)
        write_tsv(output / "SLOT_LIGHT_SWORDFLASH_CALIBRATED_SECTION_TABLE_PAIR_DECISIONS.tsv", [
            "pair_id", "normalized_path", "member_key", "member_name", "source_values", "target_values", "candidate_model_rows",
            "eligible_section_table_model_rows", "selected_model_id", "selection_basis", "classification",
        ], swordflash_decisions)
        write_tsv(output / "SLOT_LIGHT_SECTION_TABLE_MODEL_SELECTIVITY_CANARY_CHECK.tsv", ["question", "answer", "classification"], canary_rows)
        write_tsv(output / "SLOT_LIGHT_SECTION_TABLE_MODEL_SELECTIVITY_SKIPPED.tsv", ["scope", "identity", "reason"], skipped_rows)

        summary = {
            "type": "br_quartet_restoration_reflector_slot_light_section_table_model_selectivity_calibration_evidence_summary",
            "format_version": 1,
            "tool_version": TOOL_VERSION,
            "status": "section_table_model_selectivity_calibrated_or_conservatively_rejected_semantics_unresolved_no_write",
            "stage109_occurrence_rows": parse_int(s109.get("revalidated_occurrence_rows"), -1),
            "stage111_one_edit_pair_rows": len(one_edit_pairs),
            "stage111_one_edit_model_rows": len(one_edit_models),
            "stage117_input_unresolved_noncanary_pair_rows": parse_int(s117.get("still_unresolved_noncanary_pair_rows"), -1),
            "rehydrated_parent_container_rows": len(containers),
            "independent_calibration_reference_rows": len(reference_inventory),
            "independent_calibration_reference_container_rows": len(reference_containers),
            "calibration_reference_pass_rows": sum(parse_bool(row.get("calibration_reference_passed")) for row in reference_decisions),
            "calibration_reference_fail_rows": sum(not parse_bool(row.get("calibration_reference_passed")) for row in reference_decisions),
            "immutable_canary_recovered": canary_passed,
            "section_table_rule_authoritatively_calibrated": calibration_authoritative,
            "section_table_binding_candidate_rows": len(binding_rows),
            "section_table_model_support_rows": len(support_rows),
            "newly_resolved_swordflash_pair_rows": newly_resolved,
            "still_unresolved_swordflash_pair_rows": still_unresolved,
            "total_resolved_noncanary_pair_rows_after_stage118": parse_int(s116.get("total_resolved_noncanary_pair_rows_after_stage116"), 0) + newly_resolved,
            "canary_identity_preserved": True,
            "prototype_candidate_rows": 0,
            "technical_leaf_domain_semantics_resolved": False,
            "brightness_semantics_confirmed": False,
            "intensity_semantics_confirmed": False,
            "censorship_semantics_confirmed": False,
            "skipped_rows": len(skipped_rows),
            "policy": {
                "official_nonunderscore_archives_are_canonical": True,
                "underscore_archives_required": False,
                "minimum_table_support_rows": MIN_TABLE_SUPPORT_ROWS,
                "minimum_distinct_tables": MIN_DISTINCT_TABLES,
                "zero_table_conflicts_required": True,
                "all_independent_references_must_be_recovered": True,
                "immutable_canary_must_be_recovered": True,
                "cross_container_calibration_required": True,
                "paired_float_leaf_values_used_for_identity": False,
                "numeric_closeness_used": False,
                "field_semantic_names_assigned": False,
                "G1E_G1EM_write_authorized": False,
                "pak_repack_authorized": False,
                "profile_or_registry_write_authorized": False,
                "installed_game_modified": False,
            },
            "next_action": "Upload this report. Accept swordflash identities only if all six independent references and the immutable canary calibrate the exact zero-conflict section-table rule and exactly one model remains per pair. Otherwise preserve unresolved status. Do not infer value semantics or write G1E/G1EM.",
        }
        (output / "SUMMARY.json").write_text(json.dumps(summary, indent=2, sort_keys=False) + "\n", encoding="utf-8")
        archive = reports / REPORT_NAME if create_archive else None
        if archive:
            make_archive(output, archive)
        return output, archive, summary


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path, default=PROJECT_ROOT_DEFAULT)
    parser.add_argument("--no-report-archive", action="store_true")
    args = parser.parse_args(argv)
    try:
        output, archive, summary = build_report(args.project_root, create_archive=not args.no_report_archive)
    except Stage118Error as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print(f"Output: {output}")
    if archive:
        print(f"Report: {archive}")
    print(f"Section-table rule calibrated: {summary['section_table_rule_authoritatively_calibrated']}")
    print(f"Newly resolved swordflash pairs: {summary['newly_resolved_swordflash_pair_rows']}")
    print(f"Still unresolved swordflash pairs: {summary['still_unresolved_swordflash_pair_rows']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
