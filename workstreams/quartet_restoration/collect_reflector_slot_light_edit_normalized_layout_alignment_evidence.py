#!/usr/bin/env python3
"""Align non-identical source/target section layouts with bounded edit normalization.

Stage 110 proved that every paired-float value is stable inside 297 unique exact
source-target section-layout classes.  This metadata-only stage examines only the
200 source-only and 205 target-only classes that stage 110 excluded.  It pairs
sections conservatively inside the same member, mode/flag and coverage class,
then permits either a uniform-offset zero-edit alignment or one insertion/deletion
whose matched offset deltas form at most two constant runs.

The resolved PC02 ringlight occurrence identity from stage 99 is used only as an
independent structural canary.  Ambiguous edit models elsewhere remain unresolved.
No numeric-domain semantics are inferred and no G1E/G1EM payload is written.
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import shutil
import subprocess
import tempfile
from collections import Counter, defaultdict
from pathlib import Path, PurePosixPath
from typing import Any, Iterable, Mapping, Sequence

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT_DEFAULT = SCRIPT_DIR.parent.parent
TOOL_VERSION = "0.1.25"
REPORT_NAME = "BR_quartet_restoration_reflector_slot_light_edit_normalized_layout_alignment_evidence.tar.zst"
REPORT_DIR = "reflector_slot_light_edit_normalized_layout_alignment_evidence"

STAGE109_DIR = "reflector_slot_light_sibling_section_layout_evidence"
STAGE109_ARCHIVE = "BR_quartet_restoration_reflector_slot_light_sibling_section_layout_evidence.tar.zst"
STAGE110_DIR = "reflector_slot_light_identical_layout_value_transition_evidence"
STAGE110_ARCHIVE = "BR_quartet_restoration_reflector_slot_light_identical_layout_value_transition_evidence.tar.zst"
STAGE99_DIR = "reflector_slot_light_insertion_shift_continuity_evidence"
STAGE99_ARCHIVE = "BR_quartet_restoration_reflector_slot_light_insertion_shift_continuity_evidence.tar.zst"

EXPECTED_STAGE109_SECTIONS = 999
EXPECTED_STAGE109_OCCURRENCES = 1814
EXPECTED_STAGE110_CLASSES = 702
EXPECTED_SOURCE_ONLY_CLASSES = 200
EXPECTED_TARGET_ONLY_CLASSES = 205
EXPECTED_CANDIDATE_SECTION_PAIRS = 195
EXPECTED_ALIGNMENT_MODELS = 210
EXPECTED_MUTUAL_UNIQUE_PAIRS = 193
EXPECTED_ZERO_EDIT_PAIRS = 185
EXPECTED_ONE_EDIT_PAIRS = 8
EXPECTED_ONE_EDIT_MODELS = 23
EXPECTED_RESOLVED_PAIRS = 186
EXPECTED_UNRESOLVED_ONE_EDIT_PAIRS = 7
EXPECTED_RESOLVED_TRANSITIONS = 475
EXPECTED_STABLE_TRANSITIONS = 468
EXPECTED_CHANGED_TRANSITIONS = 7
EXPECTED_INSERTED_OCCURRENCES = 1
EXPECTED_DELETED_OCCURRENCES = 0

CANARY_PATH = "data/x64/effect/1002_pc02.elixir.gz"
CANARY_MEMBER_KEY = "e_pc02_w5_ringlight_01.g1e#0"
CANARY_ENDPOINT = 20276
CANARY_SOURCE_VALUES = ["30", "150", "2"]
CANARY_TARGET_VALUES = ["30", "75", "75", "2"]
CANARY_INSERTED_TARGET_ORDINAL = 1


class Stage111Error(RuntimeError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise Stage111Error(message)


def parse_int(value: Any, default: int = 0) -> int:
    try:
        text = str(value).strip()
        return int(text, 16) if text.casefold().startswith("0x") else int(text)
    except (TypeError, ValueError):
        return default


def parse_bool(value: Any) -> bool:
    return str(value).strip().casefold() in {"1", "true", "yes", "y"}


def split_ints(value: Any) -> list[int]:
    text = str(value).strip()
    return [] if not text else [parse_int(item, -1) for item in text.split(";")]


def split_values(value: Any) -> list[str]:
    text = str(value).strip()
    return [] if not text else text.split(";")


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
        raise Stage111Error(f"invalid JSON {path}: {exc}") from exc
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
    direct_path = report_root / direct
    return direct_path if direct_path.is_dir() else extract_archive(report_root / archive, temporary)


def make_archive(source: Path, output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(output.name + ".tmp")
    temporary.unlink(missing_ok=True)
    completed = subprocess.run(["tar", "--zstd", "-cf", str(temporary), "-C", str(source.parent), source.name], text=True, capture_output=True)
    require(completed.returncode == 0, completed.stderr.strip())
    os.replace(temporary, output)


def validate_stage109(root: Path) -> dict[str, Any]:
    summary = load_json(root / "SUMMARY.json")
    require(summary.get("type") == "br_quartet_restoration_reflector_slot_light_sibling_section_layout_evidence_summary", "stage109 type mismatch")
    require(summary.get("tool_version") == "0.1.23", "stage109 tool version mismatch")
    require(parse_int(summary.get("section_anchored_layout_rows"), -1) == EXPECTED_STAGE109_SECTIONS, "stage109 section count mismatch")
    require(parse_int(summary.get("revalidated_occurrence_rows"), -1) == EXPECTED_STAGE109_OCCURRENCES, "stage109 occurrence count mismatch")
    require(parse_int(summary.get("skipped_rows"), -1) == 0, "stage109 contains skipped rows")
    require(not parse_bool(summary.get("technical_leaf_domain_semantics_resolved")), "stage109 unexpectedly resolved value semantics")
    return summary


def validate_stage110(root: Path) -> dict[str, Any]:
    summary = load_json(root / "SUMMARY.json")
    require(summary.get("type") == "br_quartet_restoration_reflector_slot_light_identical_layout_value_transition_evidence_summary", "stage110 type mismatch")
    require(summary.get("tool_version") == "0.1.24", "stage110 tool version mismatch")
    require(parse_int(summary.get("layout_class_rows"), -1) == EXPECTED_STAGE110_CLASSES, "stage110 class count mismatch")
    require(parse_int(summary.get("source_only_layout_class_rows"), -1) == EXPECTED_SOURCE_ONLY_CLASSES, "stage110 source-only count mismatch")
    require(parse_int(summary.get("target_only_layout_class_rows"), -1) == EXPECTED_TARGET_ONLY_CLASSES, "stage110 target-only count mismatch")
    require(parse_int(summary.get("changed_value_transition_rows"), -1) == 0, "stage110 exact-layout changed values no longer zero")
    require(parse_int(summary.get("skipped_rows"), -1) == 0, "stage110 contains skipped rows")
    return summary


def validate_stage99(root: Path) -> dict[str, Any]:
    summary = load_json(root / "SUMMARY.json")
    require(summary.get("type") == "br_quartet_restoration_reflector_slot_light_insertion_shift_continuity_evidence_summary", "stage99 type mismatch")
    require(summary.get("tool_version") == "0.1.13", "stage99 tool version mismatch")
    require(parse_bool(summary.get("candidate_target_occurrence_identity_resolved")), "stage99 canary identity is unresolved")
    require(summary.get("winning_model_id") == "insert_first_substitute_to_second", "stage99 canary winning model mismatch")
    require(summary.get("inserted_target_occurrence") == "first_target_75", "stage99 inserted occurrence mismatch")
    require(summary.get("candidate_target_occurrence_identity") == "second_target_75", "stage99 continuing occurrence mismatch")
    parameters = summary.get("parameters")
    require(isinstance(parameters, dict), "stage99 parameters missing")
    require([str(value) for value in parameters.get("candidate_source_sequence", [])] == CANARY_SOURCE_VALUES, "stage99 source canary sequence mismatch")
    require([str(value) for value in parameters.get("candidate_target_sequence", [])] == CANARY_TARGET_VALUES, "stage99 target canary sequence mismatch")
    require(parse_int(summary.get("skipped_rows"), -1) == 0, "stage99 contains skipped rows")
    return summary


def class_key(row: Mapping[str, Any]) -> tuple[str, str, str]:
    return (
        str(row.get("normalized_path", "")).casefold(),
        str(row.get("member_key", "")).casefold(),
        str(row.get("exact_section_anchored_layout_sha256", "")),
    )


def section_key(row: Mapping[str, Any]) -> tuple[str, str, str, int]:
    return (
        str(row.get("normalized_path", "")).casefold(),
        str(row.get("member_key", "")).casefold(),
        str(row.get("side", "")),
        parse_int(row.get("normalized_endpoint"), -1),
    )


def section_pair_id(source: Mapping[str, Any], target: Mapping[str, Any]) -> str:
    return "|".join([
        str(source.get("normalized_path", "")).casefold(),
        str(source.get("member_key", "")).casefold(),
        str(parse_int(source.get("normalized_endpoint"), -1)),
        str(parse_int(target.get("normalized_endpoint"), -1)),
    ])


def offset_alignment_models(source: Mapping[str, Any], target: Mapping[str, Any]) -> list[dict[str, Any]]:
    source_offsets = split_ints(source.get("template_relative_offsets"))
    target_offsets = split_ints(target.get("template_relative_offsets"))
    models: list[dict[str, Any]] = []

    if len(source_offsets) == len(target_offsets):
        deltas = [target - source for source, target in zip(source_offsets, target_offsets)]
        if len(set(deltas)) <= 1:
            models.append({
                "edit_kind": "zero_edit_uniform_offset_shift",
                "edit_ordinal": "",
                "matched_pairs": list(zip(range(len(source_offsets)), range(len(target_offsets)))),
                "offset_deltas": deltas,
            })

    if len(target_offsets) == len(source_offsets) + 1:
        for inserted in range(len(target_offsets)):
            pairs = [(index, index if index < inserted else index + 1) for index in range(len(source_offsets))]
            deltas = [target_offsets[target_index] - source_offsets[source_index] for source_index, target_index in pairs]
            before = deltas[:inserted]
            after = deltas[inserted:]
            if (not before or len(set(before)) == 1) and (not after or len(set(after)) == 1):
                models.append({
                    "edit_kind": "target_insertion_piecewise_offset_shift",
                    "edit_ordinal": inserted,
                    "matched_pairs": pairs,
                    "offset_deltas": deltas,
                })

    if len(source_offsets) == len(target_offsets) + 1:
        for deleted in range(len(source_offsets)):
            pairs = [(index if index < deleted else index + 1, index) for index in range(len(target_offsets))]
            deltas = [target_offsets[target_index] - source_offsets[source_index] for source_index, target_index in pairs]
            before = deltas[:deleted]
            after = deltas[deleted:]
            if (not before or len(set(before)) == 1) and (not after or len(set(after)) == 1):
                models.append({
                    "edit_kind": "target_deletion_piecewise_offset_shift",
                    "edit_ordinal": deleted,
                    "matched_pairs": pairs,
                    "offset_deltas": deltas,
                })
    return models


def model_id(pair_id: str, model: Mapping[str, Any]) -> str:
    ordinal = model.get("edit_ordinal", "")
    return f"{pair_id}|{model.get('edit_kind')}|{ordinal}"


def constant_or_blank(values: list[int]) -> str:
    return "" if not values else str(values[0]) if len(set(values)) == 1 else "non_constant"


def build_report(project_root: Path, *, create_archive: bool = True, report_root: Path | None = None) -> tuple[Path, Path | None, dict[str, Any]]:
    project_root = project_root.resolve()
    reports = (report_root or project_root / ".local/reports/quartet_restoration").resolve()
    require(reports.is_dir(), f"missing report root: {reports}")

    with tempfile.TemporaryDirectory(prefix="br-stage111-") as temporary_name:
        temporary = Path(temporary_name)
        stage109_root = locate(reports, STAGE109_DIR, STAGE109_ARCHIVE, temporary / "109")
        stage110_root = locate(reports, STAGE110_DIR, STAGE110_ARCHIVE, temporary / "110")
        stage99_root = locate(reports, STAGE99_DIR, STAGE99_ARCHIVE, temporary / "99")
        summary109 = validate_stage109(stage109_root)
        summary110 = validate_stage110(stage110_root)
        summary99 = validate_stage99(stage99_root)

        section_rows = read_tsv(stage109_root / "SLOT_LIGHT_SIBLING_SECTION_ANCHORED_LAYOUTS.tsv")
        occurrence_rows = read_tsv(stage109_root / "SLOT_LIGHT_SIBLING_SECTION_LAYOUT_OCCURRENCES.tsv")
        class_rows = read_tsv(stage110_root / "SLOT_LIGHT_IDENTICAL_LAYOUT_CLASSES.tsv")
        require(len(section_rows) == EXPECTED_STAGE109_SECTIONS, "stage109 section table length mismatch")
        require(len(occurrence_rows) == EXPECTED_STAGE109_OCCURRENCES, "stage109 occurrence table length mismatch")
        require(len(class_rows) == EXPECTED_STAGE110_CLASSES, "stage110 class table length mismatch")

        sections_by_class: dict[tuple[str, str, str], list[dict[str, str]]] = defaultdict(list)
        sections_by_key: dict[tuple[str, str, str, int], dict[str, str]] = {}
        for row in section_rows:
            key = section_key(row)
            require(key not in sections_by_key, f"duplicate section key: {key}")
            sections_by_key[key] = row
            sections_by_class[class_key(row)].append(row)

        occurrences_by_section: dict[tuple[str, str, str, int], list[dict[str, str]]] = defaultdict(list)
        for row in occurrence_rows:
            key = section_key(row)
            require(key in sections_by_key, f"occurrence references unknown section: {key}")
            occurrences_by_section[key].append(row)
        for key, rows in occurrences_by_section.items():
            rows.sort(key=lambda item: parse_int(item.get("template_ordinal_within_section"), -1))
            require([parse_int(row.get("template_ordinal_within_section"), -1) for row in rows] == list(range(len(rows))), f"non-contiguous occurrence ordinals: {key}")

        source_only_sections: list[dict[str, str]] = []
        target_only_sections: list[dict[str, str]] = []
        for row in class_rows:
            classification = row.get("classification")
            members = sections_by_class.get(class_key(row), [])
            if classification == "source_only_layout_class":
                require(len(members) == 1 and members[0].get("side") == "source", f"stage110 source-only class mismatch: {class_key(row)}")
                source_only_sections.append(members[0])
            elif classification == "target_only_layout_class":
                require(len(members) == 1 and members[0].get("side") == "target", f"stage110 target-only class mismatch: {class_key(row)}")
                target_only_sections.append(members[0])
        require(len(source_only_sections) == EXPECTED_SOURCE_ONLY_CLASSES, "source-only section reconstruction mismatch")
        require(len(target_only_sections) == EXPECTED_TARGET_ONLY_CLASSES, "target-only section reconstruction mismatch")

        candidate_pairs: list[dict[str, Any]] = []
        source_candidates: dict[int, list[int]] = defaultdict(list)
        target_candidates: dict[int, list[int]] = defaultdict(list)
        pair_models: dict[tuple[int, int], list[dict[str, Any]]] = {}

        for source_index, source in enumerate(source_only_sections):
            for target_index, target in enumerate(target_only_sections):
                if (str(source.get("normalized_path", "")).casefold(), str(source.get("member_key", "")).casefold()) != (str(target.get("normalized_path", "")).casefold(), str(target.get("member_key", "")).casefold()):
                    continue
                if str(source.get("section_mode_or_flag_word", "")) != str(target.get("section_mode_or_flag_word", "")):
                    continue
                if str(source.get("template_coverage_of_section_count", "")) != str(target.get("template_coverage_of_section_count", "")):
                    continue
                if abs(parse_int(target.get("section_count")) - parse_int(source.get("section_count"))) > 1:
                    continue
                models = offset_alignment_models(source, target)
                if not models:
                    continue
                pair_index = len(candidate_pairs)
                source_candidates[source_index].append(pair_index)
                target_candidates[target_index].append(pair_index)
                pair_models[(source_index, target_index)] = models
                candidate_pairs.append({
                    "pair_index": pair_index,
                    "source_index": source_index,
                    "target_index": target_index,
                    "source": source,
                    "target": target,
                    "models": models,
                })

        require(len(candidate_pairs) == EXPECTED_CANDIDATE_SECTION_PAIRS, "normalized candidate pair count mismatch")
        require(sum(len(pair["models"]) for pair in candidate_pairs) == EXPECTED_ALIGNMENT_MODELS, "alignment model count mismatch")

        mutual_pairs: list[dict[str, Any]] = []
        for pair in candidate_pairs:
            source_index = pair["source_index"]
            target_index = pair["target_index"]
            if len(source_candidates[source_index]) == 1 and len(target_candidates[target_index]) == 1:
                mutual_pairs.append(pair)
        require(len(mutual_pairs) == EXPECTED_MUTUAL_UNIQUE_PAIRS, "mutual unique pair count mismatch")

        canary_pair: dict[str, Any] | None = None
        for pair in mutual_pairs:
            source = pair["source"]
            target = pair["target"]
            if (
                str(source.get("normalized_path", "")).casefold() == CANARY_PATH
                and str(source.get("member_key", "")).casefold() == CANARY_MEMBER_KEY
                and parse_int(source.get("normalized_endpoint"), -1) == CANARY_ENDPOINT
                and parse_int(target.get("normalized_endpoint"), -1) == CANARY_ENDPOINT
            ):
                require(canary_pair is None, "duplicate PC02 canary pair")
                canary_pair = pair
        require(canary_pair is not None, "missing PC02 insertion canary pair")
        require(split_values(canary_pair["source"].get("template_values_in_order")) == CANARY_SOURCE_VALUES, "stage109 canary source values mismatch")
        require(split_values(canary_pair["target"].get("template_values_in_order")) == CANARY_TARGET_VALUES, "stage109 canary target values mismatch")

        candidate_rows: list[dict[str, Any]] = []
        model_rows: list[dict[str, Any]] = []
        pair_decision_rows: list[dict[str, Any]] = []
        transition_rows: list[dict[str, Any]] = []
        edit_occurrence_rows: list[dict[str, Any]] = []
        skipped_rows: list[dict[str, Any]] = []

        selected_models: dict[str, dict[str, Any]] = {}
        zero_edit_pairs = 0
        one_edit_pairs = 0
        one_edit_models = 0
        unresolved_one_edit_pairs = 0
        independently_resolved_canary_pairs = 0

        for pair in candidate_pairs:
            source = pair["source"]
            target = pair["target"]
            pair_id = section_pair_id(source, target)
            mutual = len(source_candidates[pair["source_index"]]) == 1 and len(target_candidates[pair["target_index"]]) == 1
            candidate_rows.append({
                "pair_id": pair_id,
                "normalized_path": source.get("normalized_path", ""),
                "member_key": source.get("member_key", ""),
                "member_name": source.get("member_name", ""),
                "technical_member_role": source.get("technical_member_role", ""),
                "source_endpoint": source.get("normalized_endpoint", ""),
                "target_endpoint": target.get("normalized_endpoint", ""),
                "section_mode_or_flag_word": source.get("section_mode_or_flag_word", ""),
                "source_section_count": source.get("section_count", ""),
                "target_section_count": target.get("section_count", ""),
                "source_occurrence_count": source.get("template_occurrences_in_section", ""),
                "target_occurrence_count": target.get("template_occurrences_in_section", ""),
                "source_declared_span": source.get("section_declared_span", ""),
                "target_declared_span": target.get("section_declared_span", ""),
                "source_relative_offsets": source.get("template_relative_offsets", ""),
                "target_relative_offsets": target.get("template_relative_offsets", ""),
                "source_values": source.get("template_values_in_order", ""),
                "target_values": target.get("template_values_in_order", ""),
                "alignment_model_rows": len(pair["models"]),
                "source_candidate_pair_rows": len(source_candidates[pair["source_index"]]),
                "target_candidate_pair_rows": len(target_candidates[pair["target_index"]]),
                "mutual_unique_section_pair": mutual,
                "classification": "mutual_unique_normalized_section_pair" if mutual else "ambiguous_section_pair_candidate",
            })

            source_values = split_values(source.get("template_values_in_order"))
            target_values = split_values(target.get("template_values_in_order"))
            for model in pair["models"]:
                matched_pairs = list(model["matched_pairs"])
                stable = sum(source_values[source_ordinal] == target_values[target_ordinal] for source_ordinal, target_ordinal in matched_pairs)
                changed = len(matched_pairs) - stable
                deltas = list(model["offset_deltas"])
                edit_ordinal = model.get("edit_ordinal", "")
                before_count = parse_int(edit_ordinal, len(deltas)) if edit_ordinal != "" else len(deltas)
                before = deltas[:before_count]
                after = deltas[before_count:]
                model_rows.append({
                    "pair_id": pair_id,
                    "model_id": model_id(pair_id, model),
                    "normalized_path": source.get("normalized_path", ""),
                    "member_key": source.get("member_key", ""),
                    "member_name": source.get("member_name", ""),
                    "source_endpoint": source.get("normalized_endpoint", ""),
                    "target_endpoint": target.get("normalized_endpoint", ""),
                    "edit_kind": model.get("edit_kind", ""),
                    "edit_ordinal": edit_ordinal,
                    "matched_ordinal_pairs": ";".join(f"{source_ordinal}->{target_ordinal}" for source_ordinal, target_ordinal in matched_pairs),
                    "offset_delta_vector": ";".join(str(value) for value in deltas),
                    "pre_edit_offset_shift": constant_or_blank(before),
                    "post_edit_offset_shift": constant_or_blank(after),
                    "matched_occurrence_rows": len(matched_pairs),
                    "stable_value_rows_diagnostic": stable,
                    "changed_value_rows_diagnostic": changed,
                    "mutual_unique_section_pair": mutual,
                    "selected_for_resolved_transitions": False,
                    "selection_basis": "",
                    "classification": "bounded_alignment_model_candidate",
                })

        # Resolve mutual pairs. Zero-edit pairs with one model are self-contained;
        # the PC02 one-edit canary is selected only because stage 99 independently
        # established the inserted and continuing occurrences.
        for pair in mutual_pairs:
            source = pair["source"]
            target = pair["target"]
            pair_id = section_pair_id(source, target)
            models = pair["models"]
            selected: dict[str, Any] | None = None
            basis = ""
            if len(models) == 1 and models[0]["edit_kind"] == "zero_edit_uniform_offset_shift":
                selected = models[0]
                basis = "unique_zero_edit_uniform_offset_alignment"
                zero_edit_pairs += 1
            else:
                one_edit_pairs += 1
                one_edit_models += len(models)
                if pair is canary_pair:
                    matches = [
                        model for model in models
                        if model["edit_kind"] == "target_insertion_piecewise_offset_shift"
                        and parse_int(model.get("edit_ordinal"), -1) == CANARY_INSERTED_TARGET_ORDINAL
                        and list(model["matched_pairs"]) == [(0, 0), (1, 2), (2, 3)]
                    ]
                    require(len(matches) == 1, "stage99-selected PC02 canary model absent from stage111 candidates")
                    selected = matches[0]
                    basis = "stage99_independent_insertion_shift_continuity_canary"
                    independently_resolved_canary_pairs += 1
                elif len(models) == 1:
                    selected = models[0]
                    basis = "unique_one_edit_offset_geometry"
                else:
                    unresolved_one_edit_pairs += 1

            if selected is not None:
                selected_models[pair_id] = selected
                selected_id = model_id(pair_id, selected)
                for row in model_rows:
                    if row["model_id"] == selected_id:
                        row["selected_for_resolved_transitions"] = True
                        row["selection_basis"] = basis
                        row["classification"] = "selected_bounded_alignment_model"
                        break
                pair_classification = "resolved_zero_edit_normalized_pair" if selected["edit_kind"] == "zero_edit_uniform_offset_shift" else "resolved_one_edit_canary_pair"
            else:
                pair_classification = "unresolved_multiple_one_edit_models"
                skipped_rows.append({
                    "pair_id": pair_id,
                    "normalized_path": source.get("normalized_path", ""),
                    "member_key": source.get("member_key", ""),
                    "source_endpoint": source.get("normalized_endpoint", ""),
                    "target_endpoint": target.get("normalized_endpoint", ""),
                    "alignment_model_rows": len(models),
                    "reason": "multiple_bounded_edit_models_without_independent_occurrence_identity",
                })

            pair_decision_rows.append({
                "pair_id": pair_id,
                "normalized_path": source.get("normalized_path", ""),
                "member_key": source.get("member_key", ""),
                "member_name": source.get("member_name", ""),
                "technical_member_role": source.get("technical_member_role", ""),
                "source_endpoint": source.get("normalized_endpoint", ""),
                "target_endpoint": target.get("normalized_endpoint", ""),
                "source_values": source.get("template_values_in_order", ""),
                "target_values": target.get("template_values_in_order", ""),
                "alignment_model_rows": len(models),
                "selected_model_id": model_id(pair_id, selected) if selected is not None else "",
                "selection_basis": basis,
                "classification": pair_classification,
            })

            if selected is None:
                continue

            source_occurrences = occurrences_by_section[section_key(source)]
            target_occurrences = occurrences_by_section[section_key(target)]
            for source_ordinal, target_ordinal in selected["matched_pairs"]:
                source_occurrence = source_occurrences[source_ordinal]
                target_occurrence = target_occurrences[target_ordinal]
                source_value = str(source_occurrence.get("paired_float_value", ""))
                target_value = str(target_occurrence.get("paired_float_value", ""))
                transition_rows.append({
                    "pair_id": pair_id,
                    "model_id": model_id(pair_id, selected),
                    "selection_basis": basis,
                    "normalized_path": source.get("normalized_path", ""),
                    "member_key": source.get("member_key", ""),
                    "member_name": source.get("member_name", ""),
                    "technical_member_role": source.get("technical_member_role", ""),
                    "source_endpoint": source.get("normalized_endpoint", ""),
                    "target_endpoint": target.get("normalized_endpoint", ""),
                    "source_ordinal": source_ordinal,
                    "target_ordinal": target_ordinal,
                    "source_record_relative_offset": source_occurrence.get("record_relative_offset", ""),
                    "target_record_relative_offset": target_occurrence.get("record_relative_offset", ""),
                    "offset_delta": parse_int(target_occurrence.get("record_relative_offset")) - parse_int(source_occurrence.get("record_relative_offset")),
                    "source_paired_float_value": source_value,
                    "target_paired_float_value": target_value,
                    "classification": "stable_value_in_edit_normalized_layout" if source_value == target_value else "changed_value_in_edit_normalized_layout",
                })

            source_matched = {source_ordinal for source_ordinal, _ in selected["matched_pairs"]}
            target_matched = {target_ordinal for _, target_ordinal in selected["matched_pairs"]}
            for ordinal, occurrence in enumerate(source_occurrences):
                if ordinal not in source_matched:
                    edit_occurrence_rows.append({
                        "pair_id": pair_id,
                        "model_id": model_id(pair_id, selected),
                        "normalized_path": source.get("normalized_path", ""),
                        "member_key": source.get("member_key", ""),
                        "member_name": source.get("member_name", ""),
                        "side": "source",
                        "edit_kind": "deleted_from_target",
                        "ordinal": ordinal,
                        "record_relative_offset": occurrence.get("record_relative_offset", ""),
                        "paired_float_value": occurrence.get("paired_float_value", ""),
                        "selection_basis": basis,
                        "classification": "resolved_deleted_occurrence",
                    })
            for ordinal, occurrence in enumerate(target_occurrences):
                if ordinal not in target_matched:
                    edit_occurrence_rows.append({
                        "pair_id": pair_id,
                        "model_id": model_id(pair_id, selected),
                        "normalized_path": source.get("normalized_path", ""),
                        "member_key": source.get("member_key", ""),
                        "member_name": source.get("member_name", ""),
                        "side": "target",
                        "edit_kind": "inserted_in_target",
                        "ordinal": ordinal,
                        "record_relative_offset": occurrence.get("record_relative_offset", ""),
                        "paired_float_value": occurrence.get("paired_float_value", ""),
                        "selection_basis": basis,
                        "classification": "resolved_inserted_occurrence",
                    })

        require(zero_edit_pairs == EXPECTED_ZERO_EDIT_PAIRS, "zero-edit pair count mismatch")
        require(one_edit_pairs == EXPECTED_ONE_EDIT_PAIRS, "one-edit pair count mismatch")
        require(one_edit_models == EXPECTED_ONE_EDIT_MODELS, "one-edit model count mismatch")
        require(independently_resolved_canary_pairs == 1, "PC02 canary resolution count mismatch")
        require(unresolved_one_edit_pairs == EXPECTED_UNRESOLVED_ONE_EDIT_PAIRS, "unresolved one-edit pair count mismatch")
        require(len(selected_models) == EXPECTED_RESOLVED_PAIRS, "resolved section pair count mismatch")
        require(len(transition_rows) == EXPECTED_RESOLVED_TRANSITIONS, "resolved transition count mismatch")

        stable_rows = sum(row["classification"] == "stable_value_in_edit_normalized_layout" for row in transition_rows)
        changed_rows = len(transition_rows) - stable_rows
        inserted_rows = sum(row["edit_kind"] == "inserted_in_target" for row in edit_occurrence_rows)
        deleted_rows = sum(row["edit_kind"] == "deleted_from_target" for row in edit_occurrence_rows)
        require(stable_rows == EXPECTED_STABLE_TRANSITIONS, "stable transition count mismatch")
        require(changed_rows == EXPECTED_CHANGED_TRANSITIONS, "changed transition count mismatch")
        require(inserted_rows == EXPECTED_INSERTED_OCCURRENCES, "inserted occurrence count mismatch")
        require(deleted_rows == EXPECTED_DELETED_OCCURRENCES, "deleted occurrence count mismatch")

        distribution_counter = Counter((row["source_paired_float_value"], row["target_paired_float_value"]) for row in transition_rows)
        distribution_rows: list[dict[str, Any]] = []
        for (source_value, target_value), count in sorted(distribution_counter.items(), key=lambda item: (float(item[0][0]), float(item[0][1]))):
            rows = [row for row in transition_rows if row["source_paired_float_value"] == source_value and row["target_paired_float_value"] == target_value]
            distribution_rows.append({
                "source_paired_float_value": source_value,
                "target_paired_float_value": target_value,
                "transition_rows": count,
                "section_pair_rows": len({row["pair_id"] for row in rows}),
                "member_rows": len({(row["normalized_path"], row["member_key"]) for row in rows}),
                "selection_bases": ";".join(sorted({row["selection_basis"] for row in rows})),
                "classification": "stable_transition_shape" if source_value == target_value else "changed_transition_shape",
            })

        decision_rows = [
            {"question": "were all stage110 source-only and target-only classes reconstructed", "answer": True, "classification": "200_source_only_and_205_target_only_classes_cross_validated"},
            {"question": "were exact-layout classes reused", "answer": False, "classification": "stage111_operates_only_on_stage110_unmatched_classes"},
            {"question": "were normalized section pairs required to be mutually unique", "answer": True, "classification": "193_mutual_unique_pairs"},
            {"question": "were ambiguous one-edit models used for value inference", "answer": False, "classification": "7_pairs_excluded_until_independent_occurrence_identity"},
            {"question": "was the PC02 one-edit model selected from offset geometry alone", "answer": False, "classification": "selected_only_from_stage99_independent_continuity_evidence"},
            {"question": "did normalized zero-edit layouts expose value changes", "answer": True, "classification": "6_changes_across_2_sections"},
            {"question": "does structural correlation resolve brightness intensity or censorship semantics", "answer": False, "classification": "domain_semantics_unresolved"},
            {"question": "does this authorize G1E G1EM write prototype or profile activation", "answer": False, "classification": "evidence_only_no_write"},
        ]

        output_root = reports / REPORT_DIR
        if output_root.exists():
            shutil.rmtree(output_root)
        output_root.mkdir(parents=True)
        write_tsv(output_root / "SLOT_LIGHT_EDIT_NORMALIZED_SECTION_PAIR_CANDIDATES.tsv", [
            "pair_id", "normalized_path", "member_key", "member_name", "technical_member_role",
            "source_endpoint", "target_endpoint", "section_mode_or_flag_word", "source_section_count",
            "target_section_count", "source_occurrence_count", "target_occurrence_count",
            "source_declared_span", "target_declared_span", "source_relative_offsets",
            "target_relative_offsets", "source_values", "target_values", "alignment_model_rows",
            "source_candidate_pair_rows", "target_candidate_pair_rows", "mutual_unique_section_pair",
            "classification",
        ], candidate_rows)
        write_tsv(output_root / "SLOT_LIGHT_EDIT_NORMALIZED_ALIGNMENT_MODELS.tsv", [
            "pair_id", "model_id", "normalized_path", "member_key", "member_name", "source_endpoint",
            "target_endpoint", "edit_kind", "edit_ordinal", "matched_ordinal_pairs", "offset_delta_vector",
            "pre_edit_offset_shift", "post_edit_offset_shift", "matched_occurrence_rows",
            "stable_value_rows_diagnostic", "changed_value_rows_diagnostic", "mutual_unique_section_pair",
            "selected_for_resolved_transitions", "selection_basis", "classification",
        ], model_rows)
        write_tsv(output_root / "SLOT_LIGHT_EDIT_NORMALIZED_SECTION_PAIR_DECISIONS.tsv", [
            "pair_id", "normalized_path", "member_key", "member_name", "technical_member_role",
            "source_endpoint", "target_endpoint", "source_values", "target_values", "alignment_model_rows",
            "selected_model_id", "selection_basis", "classification",
        ], pair_decision_rows)
        write_tsv(output_root / "SLOT_LIGHT_EDIT_NORMALIZED_VALUE_TRANSITIONS.tsv", [
            "pair_id", "model_id", "selection_basis", "normalized_path", "member_key", "member_name",
            "technical_member_role", "source_endpoint", "target_endpoint", "source_ordinal", "target_ordinal",
            "source_record_relative_offset", "target_record_relative_offset", "offset_delta",
            "source_paired_float_value", "target_paired_float_value", "classification",
        ], transition_rows)
        write_tsv(output_root / "SLOT_LIGHT_EDIT_NORMALIZED_INSERTED_DELETED_OCCURRENCES.tsv", [
            "pair_id", "model_id", "normalized_path", "member_key", "member_name", "side", "edit_kind",
            "ordinal", "record_relative_offset", "paired_float_value", "selection_basis", "classification",
        ], edit_occurrence_rows)
        write_tsv(output_root / "SLOT_LIGHT_EDIT_NORMALIZED_TRANSITION_DISTRIBUTION.tsv", [
            "source_paired_float_value", "target_paired_float_value", "transition_rows", "section_pair_rows",
            "member_rows", "selection_bases", "classification",
        ], distribution_rows)
        write_tsv(output_root / "SLOT_LIGHT_EDIT_NORMALIZED_DECISION.tsv", ["question", "answer", "classification"], decision_rows)
        write_tsv(output_root / "SLOT_LIGHT_EDIT_NORMALIZED_SKIPPED.tsv", [
            "pair_id", "normalized_path", "member_key", "source_endpoint", "target_endpoint",
            "alignment_model_rows", "reason",
        ], skipped_rows)

        summary = {
            "type": "br_quartet_restoration_reflector_slot_light_edit_normalized_layout_alignment_evidence_summary",
            "format_version": 1,
            "tool_version": TOOL_VERSION,
            "source_stage109_tool_version": summary109.get("tool_version"),
            "source_stage110_tool_version": summary110.get("tool_version"),
            "source_stage99_tool_version": summary99.get("tool_version"),
            "stage110_layout_class_rows": len(class_rows),
            "source_only_layout_class_rows": len(source_only_sections),
            "target_only_layout_class_rows": len(target_only_sections),
            "candidate_section_pair_rows": len(candidate_pairs),
            "alignment_model_rows": len(model_rows),
            "mutual_unique_section_pair_rows": len(mutual_pairs),
            "zero_edit_resolved_pair_rows": zero_edit_pairs,
            "one_edit_section_pair_rows": one_edit_pairs,
            "one_edit_alignment_model_rows": one_edit_models,
            "independently_resolved_canary_pair_rows": independently_resolved_canary_pairs,
            "unresolved_one_edit_pair_rows": unresolved_one_edit_pairs,
            "resolved_section_pair_rows": len(selected_models),
            "resolved_occurrence_transition_rows": len(transition_rows),
            "stable_value_transition_rows": stable_rows,
            "changed_value_transition_rows": changed_rows,
            "unique_transition_shapes": len(distribution_rows),
            "unique_changed_transition_shapes": sum(row["classification"] == "changed_transition_shape" for row in distribution_rows),
            "inserted_occurrence_rows": inserted_rows,
            "deleted_occurrence_rows": deleted_rows,
            "unpaired_source_layout_class_rows": len(source_only_sections) - len(mutual_pairs),
            "unpaired_target_layout_class_rows": len(target_only_sections) - len(mutual_pairs),
            "prototype_candidate_rows": 0,
            "skipped_rows": len(skipped_rows),
            "technical_leaf_domain_semantics_resolved": False,
            "brightness_semantics_confirmed": False,
            "censorship_semantics_confirmed": False,
            "policy": {
                "official_nonunderscore_archives_are_canonical": True,
                "underscore_archives_required": False,
                "ambiguous_edit_models_used_for_value_inference": False,
                "pc02_canary_selected_from_stage99_independent_evidence": True,
                "technical_leaf_domain_semantics_inferred": False,
                "brightness_semantics_inferred": False,
                "censorship_semantics_inferred": False,
                "render_payload_written": False,
                "profile_activated": False,
                "pak_repacked": False,
                "installed_game_modified": False,
            },
            "status": "unmatched_layouts_edit_normalized_pc02_canary_resolved_seven_one_edit_pairs_unresolved_domain_semantics_unresolved",
            "next_action": "Upload this report. Continue only with a read-only bounded block/trailer continuity audit for the seven unresolved one-edit section pairs. Rehydrate only their already-scoped G1E/G1EM members, preserve the PC02 stage-99 canary rules, and do not infer brightness/intensity/censorship or write G1E/G1EM.",
        }
        (output_root / "SUMMARY.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")

        archive_path = reports / REPORT_NAME if create_archive else None
        if archive_path is not None:
            make_archive(output_root, archive_path)
        return output_root, archive_path, summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path, default=PROJECT_ROOT_DEFAULT)
    parser.add_argument("--report-root", type=Path)
    parser.add_argument("--no-archive", action="store_true")
    args = parser.parse_args()
    try:
        output_root, archive, summary = build_report(args.project_root, create_archive=not args.no_archive, report_root=args.report_root)
    except Stage111Error as exc:
        print(f"ERROR: {exc}", file=os.sys.stderr)
        return 1
    print(f"Report directory: {output_root}")
    if archive is not None:
        print(f"Report archive: {archive}")
    print(f"Mutual normalized section pairs: {summary['mutual_unique_section_pair_rows']}")
    print(f"Resolved section pairs: {summary['resolved_section_pair_rows']}")
    print(f"Unresolved one-edit pairs: {summary['unresolved_one_edit_pair_rows']}")
    print(f"Changed resolved transitions: {summary['changed_value_transition_rows']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
