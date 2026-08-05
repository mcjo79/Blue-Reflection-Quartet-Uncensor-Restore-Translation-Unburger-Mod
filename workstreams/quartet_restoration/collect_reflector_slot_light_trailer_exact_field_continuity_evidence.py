#!/usr/bin/env python3
"""Audit exact continuity of algebraically validated trailer fields.

Stage 114 resolved two of seven ambiguous one-edit pairs using non-empty
algebraic relation signatures.  Five pairs remained ambiguous because more than
one model preserved the same relation class.  This stage compares only the five
fixed trailer fields already exported by stage 114 (dwords 128, 129, 132, 134
and 136), plus block span, using their round-trip-stable float32 text.

A model may resolve occurrence identity only when it is the sole algebraically
eligible model with a strictly dominant exact-continuity score.  Numeric
closeness, paired-float leaves, semantic labels and guessed units are excluded.
The stage is metadata-only: it does not rehydrate or write game payloads.
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import subprocess
import tempfile
from collections import defaultdict
from pathlib import Path, PurePosixPath
from typing import Any, Iterable, Mapping, Sequence

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT_DEFAULT = SCRIPT_DIR.parent.parent
TOOL_VERSION = "0.1.30"
REPORT_NAME = "BR_quartet_restoration_reflector_slot_light_trailer_exact_field_continuity_evidence.tar.zst"
REPORT_DIR = "reflector_slot_light_trailer_exact_field_continuity_evidence"

STAGE108_DIR = "br1_official_source_retirement_closure_evidence"
STAGE108_ARCHIVE = "BR_quartet_restoration_br1_official_source_retirement_closure_evidence.tar.zst"
STAGE111_DIR = "reflector_slot_light_edit_normalized_layout_alignment_evidence"
STAGE111_ARCHIVE = "BR_quartet_restoration_reflector_slot_light_edit_normalized_layout_alignment_evidence.tar.zst"
STAGE114_DIR = "reflector_slot_light_trailer_algebraic_schema_evidence"
STAGE114_ARCHIVE = "BR_quartet_restoration_reflector_slot_light_trailer_algebraic_schema_evidence.tar.zst"

FIELD_DWORDS = (128, 129, 132, 134, 136)
EXPECTED_STAGE114_PAIR_ROWS = 8
EXPECTED_STAGE114_MODEL_ROWS = 23
EXPECTED_STAGE114_BLOCK_ROWS = 62
EXPECTED_STAGE114_COMPARISON_ROWS = 83
EXPECTED_STAGE114_RESOLVED_NONCANARY = 2
EXPECTED_STAGE114_UNRESOLVED_NONCANARY = 5
EXPECTED_STAGE115_NEWLY_RESOLVED = 2
EXPECTED_STAGE115_STILL_UNRESOLVED = 3
CANARY_MEMBER_KEY = "e_pc02_w5_ringlight_01.g1e#0"


class Stage115Error(RuntimeError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise Stage115Error(message)


def progress(message: str) -> None:
    print(f"[stage115] {message}", file=__import__("sys").stderr, flush=True)


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
        raise Stage115Error(f"invalid JSON {path}: {exc}") from exc
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


def model_score(
    model_id: str,
    comparisons: Sequence[Mapping[str, str]],
    blocks: Mapping[tuple[str, str, int], Mapping[str, str]],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    rows = [row for row in comparisons if row.get("model_id", "") == model_id]
    require(rows, f"stage114 model comparison rows missing: {model_id}")
    detail: list[dict[str, Any]] = []
    exact_vector_rows = 0
    exact_field_rows = 0
    exact_span_rows = 0
    for row in rows:
        pair_id = row.get("pair_id", "")
        source_ordinal = parse_int(row.get("source_ordinal"), -1)
        target_ordinal = parse_int(row.get("target_ordinal"), -1)
        source = blocks.get((pair_id, "source", source_ordinal))
        target = blocks.get((pair_id, "target", target_ordinal))
        require(source is not None and target is not None, f"stage114 block relation missing for {model_id}")
        span_equal = source.get("block_span", "") == target.get("block_span", "")
        exact_span_rows += int(span_equal)
        field_equalities: list[bool] = []
        for dword in FIELD_DWORDS:
            field = f"dword_{dword}_float"
            equal = source.get(field, "") == target.get(field, "") and source.get(field, "") != ""
            field_equalities.append(equal)
            exact_field_rows += int(equal)
            detail.append({
                "pair_id": pair_id,
                "model_id": model_id,
                "source_ordinal": source_ordinal,
                "target_ordinal": target_ordinal,
                "relative_dword": dword,
                "source_canonical_f32": source.get(field, ""),
                "target_canonical_f32": target.get(field, ""),
                "canonical_f32_equal": equal,
                "source_relation_signature": source.get("relation_signature", ""),
                "target_relation_signature": target.get("relation_signature", ""),
                "block_span_equal": span_equal,
                "classification": "exact_roundtrip_f32_field_continuity" if equal else "changed_roundtrip_f32_field",
            })
        exact_vector = span_equal and all(field_equalities)
        exact_vector_rows += int(exact_vector)
    aggregate = {
        "model_id": model_id,
        "pair_id": rows[0].get("pair_id", ""),
        "matched_occurrence_rows": len(rows),
        "exact_block_span_rows": exact_span_rows,
        "exact_five_field_vector_rows": exact_vector_rows,
        "exact_individual_field_rows": exact_field_rows,
        "maximum_individual_field_rows": len(rows) * len(FIELD_DWORDS),
    }
    return detail, aggregate


def decide_pair(pair_id: str, model_rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    require(model_rows, f"no eligible models for pair: {pair_id}")
    ranked = sorted(
        model_rows,
        key=lambda row: (
            parse_int(row.get("exact_five_field_vector_rows"), -1),
            parse_int(row.get("exact_individual_field_rows"), -1),
            parse_int(row.get("exact_block_span_rows"), -1),
            str(row.get("model_id", "")),
        ),
        reverse=True,
    )
    best = ranked[0]
    best_score = (
        parse_int(best.get("exact_five_field_vector_rows"), -1),
        parse_int(best.get("exact_individual_field_rows"), -1),
        parse_int(best.get("exact_block_span_rows"), -1),
    )
    tied = [row for row in ranked if (
        parse_int(row.get("exact_five_field_vector_rows"), -1),
        parse_int(row.get("exact_individual_field_rows"), -1),
        parse_int(row.get("exact_block_span_rows"), -1),
    ) == best_score]
    eligible = len(tied) == 1 and best_score[0] > 0
    return {
        "pair_id": pair_id,
        "input_model_rows": len(model_rows),
        "best_exact_vector_rows": best_score[0],
        "best_exact_field_rows": best_score[1],
        "best_exact_span_rows": best_score[2],
        "top_score_model_rows": len(tied),
        "selected_model_id": best.get("model_id", "") if eligible else "",
        "selection_basis": "unique_strict_exact_trailer_field_continuity" if eligible else "",
        "classification": "occurrence_identity_resolved_by_exact_trailer_field_continuity" if eligible else "occurrence_identity_unresolved_after_exact_trailer_field_continuity",
    }


def validate_prerequisites(stage108_root: Path, stage111_root: Path, stage114_root: Path) -> dict[str, Any]:
    stage108 = load_json(stage108_root / "SUMMARY.json")
    require(stage108.get("status") == "underscore_archive_retirement_closed", "stage108 retirement status mismatch")
    require(parse_bool(stage108.get("retirement_complete")), "stage108 retirement incomplete")

    stage111 = load_json(stage111_root / "SUMMARY.json")
    require(stage111.get("tool_version") == "0.1.25", "stage111 tool version mismatch")
    require(parse_int(stage111.get("one_edit_alignment_model_rows"), -1) == 23, "stage111 model count mismatch")

    stage114 = load_json(stage114_root / "SUMMARY.json")
    require(stage114.get("tool_version") == "0.1.29", "stage114 tool version mismatch")
    require(parse_int(stage114.get("model_summary_rows"), -1) == EXPECTED_STAGE114_MODEL_ROWS, "stage114 model count mismatch")
    require(parse_int(stage114.get("bounded_occurrence_block_rows"), -1) == EXPECTED_STAGE114_BLOCK_ROWS, "stage114 block count mismatch")
    require(parse_int(stage114.get("model_relation_comparison_rows"), -1) == EXPECTED_STAGE114_COMPARISON_ROWS, "stage114 comparison count mismatch")
    require(parse_int(stage114.get("newly_resolved_noncanary_pair_rows"), -1) == EXPECTED_STAGE114_RESOLVED_NONCANARY, "stage114 resolved count mismatch")
    require(parse_int(stage114.get("still_unresolved_noncanary_pair_rows"), -1) == EXPECTED_STAGE114_UNRESOLVED_NONCANARY, "stage114 unresolved count mismatch")
    require(parse_bool(stage114.get("canary_identity_preserved")), "stage114 canary not preserved")
    require(parse_int(stage114.get("skipped_rows"), -1) == 0, "stage114 contains skipped rows")
    return stage114


def build_report(
    project_root: Path,
    *,
    create_archive: bool = True,
    report_root: Path | None = None,
) -> tuple[Path, Path | None, dict[str, Any]]:
    project_root = project_root.resolve()
    reports = (report_root or project_root / ".local/reports/quartet_restoration").resolve()
    require(reports.is_dir(), f"missing report root: {reports}")

    with tempfile.TemporaryDirectory(prefix="br-stage115-") as temporary_name:
        temporary = Path(temporary_name)
        stage108_root = locate(reports, STAGE108_DIR, STAGE108_ARCHIVE, temporary / "108")
        stage111_root = locate(reports, STAGE111_DIR, STAGE111_ARCHIVE, temporary / "111")
        stage114_root = locate(reports, STAGE114_DIR, STAGE114_ARCHIVE, temporary / "114")
        validate_prerequisites(stage108_root, stage111_root, stage114_root)

        stage111_models = read_tsv(stage111_root / "SLOT_LIGHT_EDIT_NORMALIZED_ALIGNMENT_MODELS.tsv")
        block_rows = read_tsv(stage114_root / "SLOT_LIGHT_TRAILER_ALGEBRAIC_BLOCK_RELATIONS.tsv")
        comparison_rows = read_tsv(stage114_root / "SLOT_LIGHT_TRAILER_ALGEBRAIC_MODEL_COMPARISONS.tsv")
        summary_rows = read_tsv(stage114_root / "SLOT_LIGHT_TRAILER_ALGEBRAIC_MODEL_SUMMARY.tsv")
        decision_rows = read_tsv(stage114_root / "SLOT_LIGHT_TRAILER_ALGEBRAIC_PAIR_DECISIONS.tsv")
        require(len(decision_rows) == EXPECTED_STAGE114_PAIR_ROWS, "stage114 decision table count mismatch")
        require(len(summary_rows) == EXPECTED_STAGE114_MODEL_ROWS, "stage114 model summary table count mismatch")
        require(len(block_rows) == EXPECTED_STAGE114_BLOCK_ROWS, "stage114 block table count mismatch")
        require(len(comparison_rows) == EXPECTED_STAGE114_COMPARISON_ROWS, "stage114 comparison table count mismatch")

        stage111_by_model = {row.get("model_id", ""): row for row in stage111_models}
        block_index = {(row.get("pair_id", ""), row.get("side", "").casefold(), parse_int(row.get("ordinal"), -1)): row for row in block_rows}
        stage114_summary_by_model = {row.get("model_id", ""): row for row in summary_rows}
        require(len(stage114_summary_by_model) == len(summary_rows), "duplicate stage114 model id")

        unresolved_decisions = [row for row in decision_rows if row.get("classification") == "occurrence_identity_unresolved_after_algebraic_schema_audit"]
        preserved_resolved = [row for row in decision_rows if row.get("classification") == "occurrence_identity_resolved_by_algebraic_trailer_schema"]
        canary_rows = [row for row in decision_rows if row.get("classification") == "canary_identity_preserved"]
        require(len(unresolved_decisions) == EXPECTED_STAGE114_UNRESOLVED_NONCANARY, "stage114 unresolved decision count drifted")
        require(len(preserved_resolved) == EXPECTED_STAGE114_RESOLVED_NONCANARY, "stage114 resolved decision count drifted")
        require(len(canary_rows) == 1 and canary_rows[0].get("member_key", "").casefold() == CANARY_MEMBER_KEY, "stage114 canary decision missing")

        field_comparison_rows: list[dict[str, Any]] = []
        model_score_rows: list[dict[str, Any]] = []
        pair_decision_rows: list[dict[str, Any]] = []
        distribution: dict[int, dict[str, int]] = {dword: {"equal": 0, "changed": 0} for dword in FIELD_DWORDS}

        progress(f"auditing exact trailer-field continuity for {len(unresolved_decisions)} unresolved pairs")
        for decision in unresolved_decisions:
            pair_id = decision.get("pair_id", "")
            eligible_models = [
                row for row in summary_rows
                if row.get("pair_id", "") == pair_id and parse_bool(row.get("identity_eligible_algebraic_schema_model"))
            ]
            require(eligible_models, f"stage114 eligible model set empty: {pair_id}")
            scores: list[dict[str, Any]] = []
            for eligible in eligible_models:
                model_id = eligible.get("model_id", "")
                require(model_id in stage111_by_model, f"stage111 model missing: {model_id}")
                detail, aggregate = model_score(model_id, comparison_rows, block_index)
                aggregate.update({
                    "edit_kind": stage111_by_model[model_id].get("edit_kind", ""),
                    "edit_ordinal": stage111_by_model[model_id].get("edit_ordinal", ""),
                    "stage114_relation_signature_equal_rows": eligible.get("relation_signature_equal_rows", ""),
                    "stage114_strong_relation_evidence_rows": eligible.get("strong_relation_evidence_rows", ""),
                    "classification": "exact_trailer_field_continuity_model_scored",
                })
                field_comparison_rows.extend(detail)
                model_score_rows.append(aggregate)
                scores.append(aggregate)
                for row in detail:
                    dword = parse_int(row.get("relative_dword"), -1)
                    distribution[dword]["equal" if parse_bool(row.get("canonical_f32_equal")) else "changed"] += 1
            result = decide_pair(pair_id, scores)
            pair_decision_rows.append({
                "normalized_path": decision.get("normalized_path", ""),
                "member_key": decision.get("member_key", ""),
                "member_name": decision.get("member_name", ""),
                "source_values": decision.get("source_values", ""),
                "target_values": decision.get("target_values", ""),
                **result,
            })

        for decision in preserved_resolved:
            pair_decision_rows.append({
                "pair_id": decision.get("pair_id", ""),
                "normalized_path": decision.get("normalized_path", ""),
                "member_key": decision.get("member_key", ""),
                "member_name": decision.get("member_name", ""),
                "source_values": decision.get("source_values", ""),
                "target_values": decision.get("target_values", ""),
                "input_model_rows": decision.get("model_rows", ""),
                "selected_model_id": decision.get("selected_model_id", ""),
                "selection_basis": "preserved_stage114_unique_algebraic_schema_resolution",
                "classification": "stage114_algebraic_identity_preserved",
            })
        canary = canary_rows[0]
        pair_decision_rows.append({
            "pair_id": canary.get("pair_id", ""),
            "normalized_path": canary.get("normalized_path", ""),
            "member_key": canary.get("member_key", ""),
            "member_name": canary.get("member_name", ""),
            "source_values": canary.get("source_values", ""),
            "target_values": canary.get("target_values", ""),
            "input_model_rows": canary.get("model_rows", ""),
            "selected_model_id": canary.get("selected_model_id", ""),
            "selection_basis": "stage99_stage112_stage113_stage114_immutable_canary_decision",
            "classification": "canary_identity_preserved",
        })

        newly_resolved = [row for row in pair_decision_rows if row.get("classification") == "occurrence_identity_resolved_by_exact_trailer_field_continuity"]
        still_unresolved = [row for row in pair_decision_rows if row.get("classification") == "occurrence_identity_unresolved_after_exact_trailer_field_continuity"]
        require(len(newly_resolved) == EXPECTED_STAGE115_NEWLY_RESOLVED, f"unexpected stage115 resolved count: {len(newly_resolved)}")
        require(len(still_unresolved) == EXPECTED_STAGE115_STILL_UNRESOLVED, f"unexpected stage115 unresolved count: {len(still_unresolved)}")

        distribution_rows = [
            {
                "relative_dword": dword,
                "canonical_f32_equal_rows": values["equal"],
                "changed_canonical_f32_rows": values["changed"],
                "classification": "exact_field_continuity_distribution_only",
            }
            for dword, values in sorted(distribution.items())
        ]
        skipped_rows: list[dict[str, Any]] = []
        summary = {
            "type": "br_quartet_restoration_reflector_slot_light_trailer_exact_field_continuity_evidence_summary",
            "format_version": 1,
            "tool_version": TOOL_VERSION,
            "status": "exact_trailer_field_continuity_audited_semantics_unresolved_no_render_write",
            "stage114_pair_rows": len(decision_rows),
            "stage114_preserved_resolved_noncanary_pair_rows": len(preserved_resolved),
            "stage114_input_unresolved_noncanary_pair_rows": len(unresolved_decisions),
            "stage114_canary_rows": len(canary_rows),
            "scored_model_rows": len(model_score_rows),
            "field_comparison_rows": len(field_comparison_rows),
            "newly_resolved_noncanary_pair_rows": len(newly_resolved),
            "still_unresolved_noncanary_pair_rows": len(still_unresolved),
            "total_resolved_noncanary_pair_rows_after_stage115": len(preserved_resolved) + len(newly_resolved),
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
                "stage114_algebraic_resolutions_are_immutable": True,
                "canonical_f32_equality_only_no_numeric_closeness": True,
                "paired_float_leaf_values_used_for_identity": False,
                "field_semantic_names_assigned": False,
                "G1E_G1EM_write_authorized": False,
                "pak_repack_authorized": False,
                "profile_or_registry_write_authorized": False,
                "installed_game_modified": False,
            },
            "next_action": "Upload this report. Preserve the two stage-114 identities and only the new uniquely dominant exact-field identities. Treat the remaining duplicate-block pairs as unresolved and move next to companion/topology binding rather than value or distance heuristics.",
        }

        output_dir = reports / REPORT_DIR
        if output_dir.exists():
            __import__("shutil").rmtree(output_dir)
        output_dir.mkdir(parents=True)
        write_tsv(output_dir / "SLOT_LIGHT_TRAILER_EXACT_FIELD_COMPARISONS.tsv", [
            "pair_id", "model_id", "source_ordinal", "target_ordinal", "relative_dword",
            "source_canonical_f32", "target_canonical_f32", "canonical_f32_equal",
            "source_relation_signature", "target_relation_signature", "block_span_equal", "classification",
        ], field_comparison_rows)
        write_tsv(output_dir / "SLOT_LIGHT_TRAILER_EXACT_FIELD_MODEL_SUMMARY.tsv", [
            "pair_id", "model_id", "edit_kind", "edit_ordinal", "matched_occurrence_rows",
            "exact_block_span_rows", "exact_five_field_vector_rows", "exact_individual_field_rows",
            "maximum_individual_field_rows", "stage114_relation_signature_equal_rows",
            "stage114_strong_relation_evidence_rows", "classification",
        ], model_score_rows)
        write_tsv(output_dir / "SLOT_LIGHT_TRAILER_EXACT_FIELD_PAIR_DECISIONS.tsv", [
            "pair_id", "normalized_path", "member_key", "member_name", "source_values", "target_values",
            "input_model_rows", "best_exact_vector_rows", "best_exact_field_rows", "best_exact_span_rows",
            "top_score_model_rows", "selected_model_id", "selection_basis", "classification",
        ], pair_decision_rows)
        write_tsv(output_dir / "SLOT_LIGHT_TRAILER_EXACT_FIELD_DISTRIBUTION.tsv", [
            "relative_dword", "canonical_f32_equal_rows", "changed_canonical_f32_rows", "classification",
        ], distribution_rows)
        write_tsv(output_dir / "SLOT_LIGHT_TRAILER_EXACT_FIELD_CANARY_CHECK.tsv", ["question", "answer", "classification"], [
            {"question": "stage114 resolved identities preserved", "answer": len(preserved_resolved) == EXPECTED_STAGE114_RESOLVED_NONCANARY, "classification": "immutable_input_preserved"},
            {"question": "immutable canary selected model", "answer": canary.get("selected_model_id", ""), "classification": "stage99_stage112_stage113_stage114_input"},
            {"question": "numeric closeness used", "answer": False, "classification": "exact_equality_only"},
            {"question": "paired-float leaves used", "answer": False, "classification": "trailer_fields_only"},
            {"question": "field semantic names assigned", "answer": False, "classification": "format_continuity_only"},
        ])
        write_tsv(output_dir / "SLOT_LIGHT_TRAILER_EXACT_FIELD_CONTINUITY_SKIPPED.tsv", ["scope", "identity", "reason"], skipped_rows)
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
