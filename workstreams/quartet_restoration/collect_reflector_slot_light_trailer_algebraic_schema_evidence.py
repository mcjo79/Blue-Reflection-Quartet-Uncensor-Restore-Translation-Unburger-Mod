#!/usr/bin/env python3
"""Audit algebraic trailer schemas for the seven unresolved one-edit pairs.

Stage 113 found no exact cross-member trailer transition that can normalize any
of the 175 residual dwords.  The residuals nevertheless expose repeatable
mathematical relationships between trailer fields, including cube and
cube-difference identities and an angle/cosine identity.  This stage treats
those relationships only as format-level schema evidence.

The collector rehydrates the same two bounded parent containers used by stages
112-113, reconstructs the same 62 occurrence blocks, and classifies algebraic
relations at fixed trailer dwords.  A model may resolve occurrence identity only
when it is the sole model for its pair whose every matched source/target block
preserves the same non-empty algebraic relation signature.  Raw paired-float
leaf values, numeric closeness between occurrences, and guessed effect semantics
are excluded from the identity gate.

The stage-99/112/113 PC02 canary remains immutable.  The collector is read-only:
it never writes G1E/G1EM, Elixir, PAK, profiles, registries or installed-game
payloads and never labels the fields as brightness, intensity, radius, angle or
censorship controls.
"""
from __future__ import annotations

import argparse
import csv
import importlib.util
import json
import math
import os
import struct
import subprocess
import sys
import tempfile
from collections import defaultdict
from pathlib import Path, PurePosixPath
from typing import Any, Callable, Iterable, Mapping, Sequence

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT_DEFAULT = SCRIPT_DIR.parent.parent
TOOL_VERSION = "0.1.29"
REPORT_NAME = "BR_quartet_restoration_reflector_slot_light_trailer_algebraic_schema_evidence.tar.zst"
REPORT_DIR = "reflector_slot_light_trailer_algebraic_schema_evidence"

STAGE79_DIR = "reflector_character_slot_render_member_evidence"
STAGE79_ARCHIVE = "BR_quartet_restoration_reflector_character_slot_render_member_evidence.tar.zst"
STAGE108_DIR = "br1_official_source_retirement_closure_evidence"
STAGE108_ARCHIVE = "BR_quartet_restoration_br1_official_source_retirement_closure_evidence.tar.zst"
STAGE109_DIR = "reflector_slot_light_sibling_section_layout_evidence"
STAGE109_ARCHIVE = "BR_quartet_restoration_reflector_slot_light_sibling_section_layout_evidence.tar.zst"
STAGE111_DIR = "reflector_slot_light_edit_normalized_layout_alignment_evidence"
STAGE111_ARCHIVE = "BR_quartet_restoration_reflector_slot_light_edit_normalized_layout_alignment_evidence.tar.zst"
STAGE112_DIR = "reflector_slot_light_unresolved_edit_block_continuity_evidence"
STAGE112_ARCHIVE = "BR_quartet_restoration_reflector_slot_light_unresolved_edit_block_continuity_evidence.tar.zst"
STAGE113_DIR = "reflector_slot_light_trailer_residual_recurrence_evidence"
STAGE113_ARCHIVE = "BR_quartet_restoration_reflector_slot_light_trailer_residual_recurrence_evidence.tar.zst"

EXPECTED_STAGE109_OCCURRENCES = 1814
EXPECTED_UNRESOLVED_PAIRS = 7
EXPECTED_UNRESOLVED_MODELS = 19
EXPECTED_CANARY_MODELS = 4
EXPECTED_PARENT_CONTAINERS = 2
EXPECTED_SCOPED_MEMBER_PAIRS = 8
EXPECTED_BLOCK_ROWS = 62
EXPECTED_STAGE113_UNSUPPORTED_DWORDS = 175

CANARY_PATH = "data/x64/effect/1002_pc02.elixir.gz"
CANARY_MEMBER_KEY = "e_pc02_w5_ringlight_01.g1e#0"

RELATION_DWORDS = (128, 129, 132, 134, 136)
CUBE_RELATION = "cube_d129_to_d134"
CUBE_DIFFERENCE_RELATION = "cube_difference_d128_d129_to_d134"
COSINE_RELATION = "cosine_d132_to_d136"

EXPECTED_UNRESOLVED_IDENTITIES = {
    ("data/x64/effect/1000_pc00.elixir.gz", "e_pc00_swordflash_02_bullet.g1e#0"),
    ("data/x64/effect/1000_pc00.elixir.gz", "e_pc00_swordflash_02_bullet_x.g1e#0"),
    ("data/x64/effect/1002_pc02.elixir.gz", "e_pc02_h3_shoot.g1e#0"),
    ("data/x64/effect/1002_pc02.elixir.gz", "e_pc02_h4_shoot.g1e#0"),
    ("data/x64/effect/1002_pc02.elixir.gz", "e_pc02_m4_beardivision.g1e#0"),
    ("data/x64/effect/1002_pc02.elixir.gz", "e_pc02_m4_charge_00.g1e#0"),
    ("data/x64/effect/1002_pc02.elixir.gz", "e_pc02_m4_charge_01.g1e#0"),
}


class Stage114Error(RuntimeError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise Stage114Error(message)


def progress(message: str) -> None:
    print(f"[stage114] {message}", file=sys.stderr, flush=True)


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
        raise Stage114Error(f"invalid JSON {path}: {exc}") from exc
    require(isinstance(value, dict), f"JSON root must be object: {path}")
    return value


def load_module(path: Path, name: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    require(spec is not None and spec.loader is not None, f"cannot load module: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


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


def f32_at(block: bytes, relative_dword: int) -> float | None:
    offset = relative_dword * 4
    if offset < 0 or offset + 4 > len(block):
        return None
    return struct.unpack("<f", block[offset:offset + 4])[0]


def finite(value: float | None) -> bool:
    return value is not None and math.isfinite(value)


def close_relation(actual: float, expected: float) -> bool:
    return math.isclose(actual, expected, rel_tol=2e-5, abs_tol=1e-4)


def classify_relation_values(values: Mapping[int, float | None]) -> tuple[list[str], dict[str, float | bool | str]]:
    d128 = values.get(128)
    d129 = values.get(129)
    d132 = values.get(132)
    d134 = values.get(134)
    d136 = values.get(136)
    relations: list[str] = []
    diagnostics: dict[str, float | bool | str] = {}

    cube_ok = False
    cube_difference_ok = False
    cosine_ok = False
    if finite(d129) and finite(d134) and abs(float(d129)) >= 1e-6:
        cube_expected = float(d129) ** 3
        cube_error = float(d134) - cube_expected
        cube_ok = close_relation(float(d134), cube_expected)
        diagnostics.update({"cube_expected": cube_expected, "cube_error": cube_error, "cube_ok": cube_ok})
    if finite(d128) and finite(d129) and finite(d134) and abs(float(d128)) >= 1e-6:
        difference_expected = float(d129) ** 3 - float(d128) ** 3
        difference_error = float(d134) - difference_expected
        cube_difference_ok = close_relation(float(d134), difference_expected)
        diagnostics.update({"cube_difference_expected": difference_expected, "cube_difference_error": difference_error, "cube_difference_ok": cube_difference_ok})
    if finite(d132) and finite(d136) and abs(float(d132)) <= math.tau * 2 and abs(float(d136)) <= 1.0001:
        cosine_expected = math.cos(float(d132))
        cosine_error = float(d136) - cosine_expected
        cosine_ok = close_relation(float(d136), cosine_expected)
        diagnostics.update({"cosine_expected": cosine_expected, "cosine_error": cosine_error, "cosine_ok": cosine_ok})

    if cube_difference_ok:
        relations.append(CUBE_DIFFERENCE_RELATION)
    elif cube_ok:
        relations.append(CUBE_RELATION)
    if cosine_ok:
        relations.append(COSINE_RELATION)
    return relations, diagnostics


def classify_block(block: Mapping[str, Any]) -> dict[str, Any]:
    raw = bytes(block["raw"])
    values = {dword: f32_at(raw, dword) for dword in RELATION_DWORDS}
    relations, diagnostics = classify_relation_values(values)
    signature = " | ".join(relations) if relations else "none"
    row: dict[str, Any] = {
        "ordinal": block["ordinal"],
        "block_span": block["span"],
        "trailer_dword_rows": max(0, block["span"] // 4 - 38),
        "relation_signature": signature,
        "strong_relation_count": len(relations),
        "classification": "nonempty_algebraic_trailer_schema" if relations else "no_supported_algebraic_trailer_schema",
    }
    for dword, value in values.items():
        row[f"dword_{dword}_float"] = "" if value is None else f"{value:.9g}"
    for key, value in diagnostics.items():
        row[key] = f"{value:.9g}" if isinstance(value, float) else value
    return row


def evaluate_model(model: Mapping[str, str], source_blocks: Sequence[Mapping[str, Any]], target_blocks: Sequence[Mapping[str, Any]], source_relations: Mapping[int, Mapping[str, Any]], target_relations: Mapping[int, Mapping[str, Any]], split_pairs: Callable[[str], list[tuple[int, int]]]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    pairs = split_pairs(str(model.get("matched_ordinal_pairs", "")))
    require(len(pairs) == parse_int(model.get("matched_occurrence_rows"), -1), f"model matched-row count mismatch: {model.get('model_id')}")
    comparisons: list[dict[str, Any]] = []
    for source_ordinal, target_ordinal in pairs:
        require(0 <= source_ordinal < len(source_blocks) and 0 <= target_ordinal < len(target_blocks), "model ordinal out of bounds")
        source = source_relations[source_ordinal]
        target = target_relations[target_ordinal]
        same_signature = source["relation_signature"] == target["relation_signature"]
        nonempty = source["relation_signature"] != "none" or target["relation_signature"] != "none"
        comparisons.append({
            "pair_id": model.get("pair_id", ""),
            "model_id": model.get("model_id", ""),
            "source_ordinal": source_ordinal,
            "target_ordinal": target_ordinal,
            "source_relation_signature": source["relation_signature"],
            "target_relation_signature": target["relation_signature"],
            "relation_signature_equal": same_signature,
            "nonempty_relation_evidence": nonempty,
            "classification": "algebraic_schema_compatible_matched_occurrence" if same_signature and nonempty else ("algebraic_schema_mismatch" if not same_signature else "non_discriminating_empty_schema_match"),
        })
    all_equal = bool(comparisons) and all(parse_bool(row["relation_signature_equal"]) for row in comparisons)
    strong_rows = sum(parse_bool(row["nonempty_relation_evidence"]) for row in comparisons)
    eligible = all_equal and strong_rows > 0
    aggregate = {
        "pair_id": model.get("pair_id", ""),
        "model_id": model.get("model_id", ""),
        "edit_kind": model.get("edit_kind", ""),
        "edit_ordinal": model.get("edit_ordinal", ""),
        "matched_occurrence_rows": len(comparisons),
        "relation_signature_equal_rows": sum(parse_bool(row["relation_signature_equal"]) for row in comparisons),
        "strong_relation_evidence_rows": strong_rows,
        "relation_signature_mismatch_rows": sum(not parse_bool(row["relation_signature_equal"]) for row in comparisons),
        "all_matched_relation_signatures_equal": all_equal,
        "identity_eligible_algebraic_schema_model": eligible,
        "classification": "identity_eligible_algebraic_schema_model" if eligible else "non_authorizing_algebraic_schema_model",
    }
    return comparisons, aggregate


def decide_pair(pair_id: str, member_key: str, models: Sequence[Mapping[str, Any]], immutable_canary_model: str = "") -> dict[str, Any]:
    eligible = [row for row in models if parse_bool(row.get("identity_eligible_algebraic_schema_model"))]
    if member_key.casefold() == CANARY_MEMBER_KEY:
        if len(eligible) == 1:
            require(eligible[0].get("model_id", "") == immutable_canary_model, "stage114 algebraic schema gate contradicts immutable canary")
        return {
            "pair_id": pair_id,
            "model_rows": len(models),
            "identity_eligible_model_rows": len(eligible),
            "selected_model_id": immutable_canary_model,
            "selection_basis": "stage99_stage112_stage113_immutable_canary_decision",
            "classification": "canary_identity_preserved",
        }
    if len(eligible) == 1:
        return {
            "pair_id": pair_id,
            "model_rows": len(models),
            "identity_eligible_model_rows": 1,
            "selected_model_id": eligible[0].get("model_id", ""),
            "selection_basis": "unique_nonempty_algebraic_trailer_schema_continuity",
            "classification": "occurrence_identity_resolved_by_algebraic_trailer_schema",
        }
    return {
        "pair_id": pair_id,
        "model_rows": len(models),
        "identity_eligible_model_rows": len(eligible),
        "selected_model_id": "",
        "selection_basis": "",
        "classification": "occurrence_identity_unresolved_after_algebraic_schema_audit",
    }


def validate_prerequisites(stage108_root: Path, stage109_root: Path, stage111_root: Path, stage112_root: Path, stage113_root: Path) -> None:
    stage108 = load_json(stage108_root / "SUMMARY.json")
    require(stage108.get("status") == "underscore_archive_retirement_closed", "stage108 retirement status mismatch")
    require(parse_bool(stage108.get("retirement_complete")), "stage108 retirement incomplete")
    require(not parse_bool(stage108.get("underscore_archives_required_for_normal_workflow")), "stage108 still requires underscore archives")

    stage109 = load_json(stage109_root / "SUMMARY.json")
    require(stage109.get("tool_version") == "0.1.23", "stage109 tool version mismatch")
    require(parse_int(stage109.get("revalidated_occurrence_rows"), -1) == EXPECTED_STAGE109_OCCURRENCES, "stage109 occurrence count mismatch")
    require(parse_int(stage109.get("skipped_rows"), -1) == 0, "stage109 contains skipped rows")

    stage111 = load_json(stage111_root / "SUMMARY.json")
    require(stage111.get("tool_version") == "0.1.25", "stage111 tool version mismatch")
    require(parse_int(stage111.get("unresolved_one_edit_pair_rows"), -1) == EXPECTED_UNRESOLVED_PAIRS, "stage111 unresolved pair count mismatch")
    require(parse_int(stage111.get("one_edit_alignment_model_rows"), -1) == EXPECTED_UNRESOLVED_MODELS + EXPECTED_CANARY_MODELS, "stage111 model count mismatch")

    stage112 = load_json(stage112_root / "SUMMARY.json")
    require(stage112.get("tool_version") == "0.1.27", "stage112 tool version mismatch")
    require(parse_int(stage112.get("still_unresolved_noncanary_pair_rows"), -1) == EXPECTED_UNRESOLVED_PAIRS, "stage112 unresolved pair count mismatch")
    require(parse_int(stage112.get("input_unresolved_one_edit_model_rows"), -1) == EXPECTED_UNRESOLVED_MODELS, "stage112 unresolved model count mismatch")
    require(parse_int(stage112.get("canary_model_rows"), -1) == EXPECTED_CANARY_MODELS, "stage112 canary model count mismatch")
    require(parse_bool(stage112.get("canary_identity_preserved")), "stage112 canary not preserved")

    stage113 = load_json(stage113_root / "SUMMARY.json")
    require(stage113.get("tool_version") == "0.1.28", "stage113 tool version mismatch")
    require(parse_int(stage113.get("still_unresolved_noncanary_pair_rows"), -1) == EXPECTED_UNRESOLVED_PAIRS, "stage113 unresolved pair count mismatch")
    require(parse_int(stage113.get("input_unresolved_model_rows"), -1) == EXPECTED_UNRESOLVED_MODELS, "stage113 unresolved model count mismatch")
    require(parse_int(stage113.get("canary_model_rows"), -1) == EXPECTED_CANARY_MODELS, "stage113 canary model count mismatch")
    require(parse_int(stage113.get("recurrent_masked_candidate_dword_rows"), -1) == 0, "stage113 unexpectedly masked candidate residuals")
    require(parse_int(stage113.get("unsupported_candidate_dword_rows"), -1) == EXPECTED_STAGE113_UNSUPPORTED_DWORDS, "stage113 unsupported residual count mismatch")
    require(parse_bool(stage113.get("canary_identity_preserved")), "stage113 canary not preserved")
    require(parse_int(stage113.get("skipped_rows"), -1) == 0, "stage113 contains skipped rows")


def build_report(
    project_root: Path,
    *,
    create_archive: bool = True,
    report_root: Path | None = None,
    workspace_root: Path | None = None,
    rules_file: Path | None = None,
    maximum_earc_bytes: int = 512 * 1024 * 1024,
    container_loader: Callable[..., tuple[list[dict[str, Any]], list[dict[str, Any]]]] | None = None,
    scope_rows_override: Sequence[Mapping[str, Any]] | None = None,
) -> tuple[Path, Path | None, dict[str, Any]]:
    project_root = project_root.resolve()
    reports = (report_root or project_root / ".local/reports/quartet_restoration").resolve()
    workspace = (workspace_root or project_root / ".local/build/quartet_restoration").resolve()
    require(reports.is_dir(), f"missing report root: {reports}")

    stage112 = load_module(project_root / "workstreams/quartet_restoration/collect_reflector_slot_light_unresolved_edit_block_continuity_evidence.py", "stage112_for_stage114")
    stage81 = load_module(project_root / "workstreams/quartet_restoration/collect_reflector_ringlight_control_callsite_evidence.py", "stage81_for_stage114")
    stage86 = load_module(project_root / "workstreams/quartet_restoration/collect_reflector_slot_light_shared_record_template_evidence.py", "stage86_for_stage114")

    with tempfile.TemporaryDirectory(prefix="br-stage114-") as temporary_name:
        temporary = Path(temporary_name)
        stage108_root = locate(reports, STAGE108_DIR, STAGE108_ARCHIVE, temporary / "108")
        stage109_root = locate(reports, STAGE109_DIR, STAGE109_ARCHIVE, temporary / "109")
        stage111_root = locate(reports, STAGE111_DIR, STAGE111_ARCHIVE, temporary / "111")
        stage112_root = locate(reports, STAGE112_DIR, STAGE112_ARCHIVE, temporary / "112")
        stage113_root = locate(reports, STAGE113_DIR, STAGE113_ARCHIVE, temporary / "113")
        validate_prerequisites(stage108_root, stage109_root, stage111_root, stage112_root, stage113_root)

        occurrence_rows = read_tsv(stage109_root / "SLOT_LIGHT_SIBLING_SECTION_LAYOUT_OCCURRENCES.tsv")
        decision_rows = read_tsv(stage111_root / "SLOT_LIGHT_EDIT_NORMALIZED_SECTION_PAIR_DECISIONS.tsv")
        model_rows = read_tsv(stage111_root / "SLOT_LIGHT_EDIT_NORMALIZED_ALIGNMENT_MODELS.tsv")
        stage113_decisions = read_tsv(stage113_root / "SLOT_LIGHT_UNRESOLVED_PAIR_RECURRENCE_DECISIONS.tsv")
        require(len(occurrence_rows) == EXPECTED_STAGE109_OCCURRENCES, "stage109 occurrence table length mismatch")

        unresolved = [row for row in decision_rows if row.get("classification") == "unresolved_multiple_one_edit_models"]
        unresolved_ids = {(row.get("normalized_path", "").casefold(), row.get("member_key", "").casefold()) for row in unresolved}
        require(unresolved_ids == EXPECTED_UNRESOLVED_IDENTITIES, "stage111 unresolved identity set drifted")
        canary = [row for row in decision_rows if row.get("normalized_path", "").casefold() == CANARY_PATH and row.get("member_key", "").casefold() == CANARY_MEMBER_KEY]
        require(len(canary) == 1, "stage111 canary decision missing")
        all_decisions = unresolved + canary
        pair_ids = {row.get("pair_id", "") for row in all_decisions}
        models = [row for row in model_rows if row.get("pair_id", "") in pair_ids]
        require(len(models) == EXPECTED_UNRESOLVED_MODELS + EXPECTED_CANARY_MODELS, "stage111 scoped model count mismatch")
        models_by_pair: dict[str, list[dict[str, str]]] = defaultdict(list)
        for row in models:
            models_by_pair[row.get("pair_id", "")].append(row)
        stage113_by_pair = {row.get("pair_id", ""): row for row in stage113_decisions}
        require(set(stage113_by_pair) == pair_ids, "stage113 decision identity set mismatch")
        canary_model = stage113_by_pair[canary[0].get("pair_id", "")].get("selected_model_id", "")
        require(canary_model, "stage113 canary selected model missing")

        required_identities = set(unresolved_ids)
        required_identities.add((CANARY_PATH, CANARY_MEMBER_KEY))
        required_paths = {path for path, _ in required_identities}
        if scope_rows_override is None:
            stage79_root = locate(reports, STAGE79_DIR, STAGE79_ARCHIVE, temporary / "79")
            stage81.validate_stage79(stage79_root)
            parent_scope = [row for row in stage81.select_parent_scope(stage79_root) if str(row.get("normalized_path", "")).casefold() in required_paths]
        else:
            parent_scope = [dict(row) for row in scope_rows_override]
        require(parent_scope, "bounded parent scope is empty")
        actual_rules = rules_file or project_root / "titles/blue_reflection/modules/quartet_restoration/mappings/effect_material_rules.tsv"
        loader = container_loader or stage81.load_parent_containers
        progress("rehydrating the same two bounded parent effect containers")
        containers, loader_skipped = loader(scope_rows=parent_scope, workspace_root=workspace, report_root=reports, rules_file=actual_rules, maximum_earc_bytes=maximum_earc_bytes)
        require(not loader_skipped, f"parent container loader skipped {len(loader_skipped)} rows")
        require(len(containers) == EXPECTED_PARENT_CONTAINERS, f"expected {EXPECTED_PARENT_CONTAINERS} parent containers, found {len(containers)}")
        pair_by_key, _ = stage86.index_pairs(containers)
        scoped_pairs = {identity: pair_by_key.get(identity) for identity in required_identities}
        require(all(pair is not None for pair in scoped_pairs.values()), "one or more bounded member pairs are missing")
        require(len(scoped_pairs) == EXPECTED_SCOPED_MEMBER_PAIRS, "bounded member pair count mismatch")

        occurrences_by_section: dict[tuple[str, str, str, int], list[dict[str, str]]] = defaultdict(list)
        for row in occurrence_rows:
            identity = (row.get("normalized_path", "").casefold(), row.get("member_key", "").casefold())
            if identity in required_identities:
                key = (identity[0], identity[1], row.get("side", "").casefold(), parse_int(row.get("normalized_endpoint"), -1))
                occurrences_by_section[key].append(row)

        block_relation_rows: list[dict[str, Any]] = []
        model_comparison_rows: list[dict[str, Any]] = []
        model_summary_rows: list[dict[str, Any]] = []
        pair_decision_rows: list[dict[str, Any]] = []
        skipped_rows: list[dict[str, Any]] = []

        progress(f"auditing algebraic trailer schemas for {len(all_decisions)} pairs")
        for decision in all_decisions:
            pair_id = decision.get("pair_id", "")
            path = decision.get("normalized_path", "").casefold()
            member_key = decision.get("member_key", "").casefold()
            source_endpoint = parse_int(decision.get("source_endpoint"), -1)
            target_endpoint = parse_int(decision.get("target_endpoint"), -1)
            pair = scoped_pairs[(path, member_key)]
            assert pair is not None
            source_rows = occurrences_by_section[(path, member_key, "source", source_endpoint)]
            target_rows = occurrences_by_section[(path, member_key, "target", target_endpoint)]
            source_blocks, _ = stage112.build_side_blocks(bytes(pair["source_payload"]), source_rows, source_endpoint)
            target_blocks, _ = stage112.build_side_blocks(bytes(pair["target_payload"]), target_rows, target_endpoint)
            source_rel = {block["ordinal"]: classify_block(block) for block in source_blocks}
            target_rel = {block["ordinal"]: classify_block(block) for block in target_blocks}
            for side, relation_map in (("source", source_rel), ("target", target_rel)):
                for ordinal, relation in sorted(relation_map.items()):
                    block_relation_rows.append({
                        "pair_id": pair_id,
                        "normalized_path": path,
                        "member_key": member_key,
                        "member_name": decision.get("member_name", ""),
                        "side": side,
                        **relation,
                    })
            aggregates: list[dict[str, Any]] = []
            for model in models_by_pair[pair_id]:
                comparisons, aggregate = evaluate_model(model, source_blocks, target_blocks, source_rel, target_rel, stage112.split_pairs)
                model_comparison_rows.extend(comparisons)
                model_summary_rows.append(aggregate)
                aggregates.append(aggregate)
            decision_result = decide_pair(pair_id, member_key, aggregates, canary_model)
            pair_decision_rows.append({
                "normalized_path": path,
                "member_key": member_key,
                "member_name": decision.get("member_name", ""),
                "source_values": decision.get("source_values", ""),
                "target_values": decision.get("target_values", ""),
                **decision_result,
            })

        require(len(block_relation_rows) == EXPECTED_BLOCK_ROWS, f"block relation row count mismatch: {len(block_relation_rows)}")
        require(len(model_summary_rows) == EXPECTED_UNRESOLVED_MODELS + EXPECTED_CANARY_MODELS, "model summary count mismatch")
        noncanary = [row for row in pair_decision_rows if row.get("member_key") != CANARY_MEMBER_KEY]
        resolved = [row for row in noncanary if row.get("classification") == "occurrence_identity_resolved_by_algebraic_trailer_schema"]
        unresolved_after = [row for row in noncanary if row.get("classification") == "occurrence_identity_unresolved_after_algebraic_schema_audit"]
        require(len(resolved) + len(unresolved_after) == EXPECTED_UNRESOLVED_PAIRS, "noncanary decision partition mismatch")
        require(not skipped_rows, "stage114 produced skipped rows")

        summary = {
            "type": "br_quartet_restoration_reflector_slot_light_trailer_algebraic_schema_evidence_summary",
            "format_version": 1,
            "tool_version": TOOL_VERSION,
            "status": "trailer_algebraic_schema_audited_semantics_unresolved_no_render_write",
            "input_unresolved_pair_rows": EXPECTED_UNRESOLVED_PAIRS,
            "input_unresolved_model_rows": EXPECTED_UNRESOLVED_MODELS,
            "canary_model_rows": EXPECTED_CANARY_MODELS,
            "rehydrated_parent_container_rows": len(containers),
            "rehydrated_scoped_member_pair_rows": len(scoped_pairs),
            "bounded_occurrence_block_rows": len(block_relation_rows),
            "nonempty_relation_block_rows": sum(row.get("relation_signature") != "none" for row in block_relation_rows),
            "cube_relation_block_rows": sum(CUBE_RELATION in str(row.get("relation_signature")) for row in block_relation_rows),
            "cube_difference_relation_block_rows": sum(CUBE_DIFFERENCE_RELATION in str(row.get("relation_signature")) for row in block_relation_rows),
            "cosine_relation_block_rows": sum(COSINE_RELATION in str(row.get("relation_signature")) for row in block_relation_rows),
            "model_relation_comparison_rows": len(model_comparison_rows),
            "model_summary_rows": len(model_summary_rows),
            "newly_resolved_noncanary_pair_rows": len(resolved),
            "still_unresolved_noncanary_pair_rows": len(unresolved_after),
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
                "algebraic_relations_are_format_signatures_only": True,
                "paired_float_values_used_for_identity": False,
                "numeric_closeness_between_occurrences_used_for_identity": False,
                "field_semantic_names_assigned": False,
                "stage99_stage112_stage113_canary_is_immutable": True,
                "G1E_G1EM_write_authorized": False,
                "pak_repack_authorized": False,
                "profile_or_registry_write_authorized": False,
                "installed_game_modified": False,
            },
            "next_action": "Upload this report. Preserve only identities selected by a unique non-empty algebraic trailer schema; keep every other pair unresolved. Do not name the fields as brightness/intensity/radius/angle/censorship controls or write G1E/G1EM.",
        }

        output_dir = reports / REPORT_DIR
        if output_dir.exists():
            __import__("shutil").rmtree(output_dir)
        output_dir.mkdir(parents=True)
        write_tsv(output_dir / "SLOT_LIGHT_TRAILER_ALGEBRAIC_BLOCK_RELATIONS.tsv", [
            "pair_id", "normalized_path", "member_key", "member_name", "side", "ordinal", "block_span", "trailer_dword_rows",
            "dword_128_float", "dword_129_float", "dword_132_float", "dword_134_float", "dword_136_float",
            "cube_expected", "cube_error", "cube_ok", "cube_difference_expected", "cube_difference_error", "cube_difference_ok",
            "cosine_expected", "cosine_error", "cosine_ok", "relation_signature", "strong_relation_count", "classification",
        ], block_relation_rows)
        write_tsv(output_dir / "SLOT_LIGHT_TRAILER_ALGEBRAIC_MODEL_COMPARISONS.tsv", [
            "pair_id", "model_id", "source_ordinal", "target_ordinal", "source_relation_signature", "target_relation_signature",
            "relation_signature_equal", "nonempty_relation_evidence", "classification",
        ], model_comparison_rows)
        write_tsv(output_dir / "SLOT_LIGHT_TRAILER_ALGEBRAIC_MODEL_SUMMARY.tsv", [
            "pair_id", "model_id", "edit_kind", "edit_ordinal", "matched_occurrence_rows", "relation_signature_equal_rows",
            "strong_relation_evidence_rows", "relation_signature_mismatch_rows", "all_matched_relation_signatures_equal",
            "identity_eligible_algebraic_schema_model", "classification",
        ], model_summary_rows)
        write_tsv(output_dir / "SLOT_LIGHT_TRAILER_ALGEBRAIC_PAIR_DECISIONS.tsv", [
            "pair_id", "normalized_path", "member_key", "member_name", "source_values", "target_values", "model_rows",
            "identity_eligible_model_rows", "selected_model_id", "selection_basis", "classification",
        ], pair_decision_rows)
        write_tsv(output_dir / "SLOT_LIGHT_TRAILER_ALGEBRAIC_CANARY_CHECK.tsv", ["question", "answer", "classification"], [
            {"question": "immutable canary selected model", "answer": canary_model, "classification": "stage99_stage112_stage113_input"},
            {"question": "stage114 canary contradiction detected", "answer": False, "classification": "canary_preserved"},
            {"question": "field semantic names assigned", "answer": False, "classification": "format_relation_only"},
            {"question": "paired-float leaf values used to select identity", "answer": False, "classification": "value_independent_identity_gate"},
        ])
        write_tsv(output_dir / "SLOT_LIGHT_TRAILER_ALGEBRAIC_SCHEMA_SKIPPED.tsv", ["scope", "identity", "reason"], skipped_rows)
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
    parser.add_argument("--workspace-root", type=Path)
    parser.add_argument("--rules-file", type=Path)
    parser.add_argument("--maximum-earc-bytes", type=int, default=512 * 1024 * 1024)
    parser.add_argument("--no-archive", action="store_true")
    args = parser.parse_args()
    try:
        output, archive, summary = build_report(
            args.project_root,
            create_archive=not args.no_archive,
            report_root=args.report_root,
            workspace_root=args.workspace_root,
            rules_file=args.rules_file,
            maximum_earc_bytes=args.maximum_earc_bytes,
        )
    except Stage114Error as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print(f"Report directory: {output}")
    if archive:
        print(f"Archive: {archive}")
    print(f"Input unresolved pairs: {summary['input_unresolved_pair_rows']}")
    print(f"Newly resolved pairs: {summary['newly_resolved_noncanary_pair_rows']}")
    print(f"Still unresolved pairs: {summary['still_unresolved_noncanary_pair_rows']}")
    print("G1E/G1EM write: blocked")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
