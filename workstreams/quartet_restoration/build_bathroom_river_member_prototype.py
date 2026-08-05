#!/usr/bin/env python3
"""Build the statically authorized Hinako bathroom river.bin member prototype.

Stage 68 authorized only the small river companion member.  This stage
independently validates the stage-68 report, rehydrates the Original and
Quartet member payloads, reapplies all seven recorded 32-bit inverse cells,
and requires an exact Original reconstruction plus an exact reverse roundtrip.
It writes the candidate only under .local/build and never rebuilds the parent
Elixir archive, repacks a PAK, modifies registry state, activates a profile or
writes to an installed game.
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
from typing import Any, Callable, Iterable, Mapping, Sequence

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT_DEFAULT = SCRIPT_DIR.parent.parent
TEXT_TOOL_DIR = PROJECT_ROOT_DEFAULT / "Blue_Reflection_Text_Tool"
for import_path in (SCRIPT_DIR, TEXT_TOOL_DIR):
    if str(import_path) not in sys.path:
        sys.path.insert(0, str(import_path))

import br_restoration_tool as BR  # noqa: E402
import collect_bathroom_scene_descriptor_word_evidence as STAGE66  # noqa: E402
import collect_bathroom_sibling_descriptor_comparison_evidence as STAGE67  # noqa: E402
import collect_bathroom_ordinary_field_control_evidence as STAGE68  # noqa: E402

TOOL_VERSION = "0.0.79"
EXPECTED_STAGE68_TOOL_VERSION = "0.0.78"
REPORT_NAME = "BR_quartet_restoration_bathroom_river_member_prototype_evidence.tar.zst"
EVIDENCE_DIR_NAME = "bathroom_river_member_prototype_evidence"
STAGE68_DIR = "bathroom_ordinary_field_control_evidence"
STAGE68_ARCHIVE = "BR_quartet_restoration_bathroom_ordinary_field_control_evidence.tar.zst"
PROFILE_ID = "candidate_bathroom_river_static_inverse_062e39915e7d"
PARENT_PATH = STAGE66.EXPECTED_PARENT_PATH
MEMBER_KEY = STAGE67.RIVER_KEY
EXPECTED_CANDIDATE_SHA256 = "062e39915e7df9e632c5bcaba592f9598572135efad8fa8aea24175f9bf06d7a"
EXPECTED_CANDIDATE_SIZE = 252
EXPECTED_TARGET_DISTANCE = 22
EXPECTED_CELL_COUNT = 7
EXPECTED_ELIGIBLE_CELL_COUNT = 6
EXPECTED_TAIL_EXCEPTION_COUNT = 1
EXPECTED_TAIL_TRANSITION_OCCURRENCES = 3
EXPECTED_TAIL_ELIGIBLE_SUPPORT = 2
PROTOTYPE_SUBDIR = Path("prototypes/bathroom_river_member")


class BathroomRiverPrototypeError(RuntimeError):
    pass


def parse_bool(value: object) -> bool:
    return str(value).strip().casefold() in {"1", "true", "yes", "y"}


def parse_int(value: object, default: int = 0) -> int:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return default


def read_tsv(path: Path, *, required: bool = True) -> list[dict[str, str]]:
    if not path.is_file():
        if required:
            raise BathroomRiverPrototypeError(f"missing prerequisite table: {path}")
        return []
    with path.open("r", encoding="utf-8", newline="") as handle:
        return [dict(row) for row in csv.DictReader(handle, delimiter="\t")]


def write_tsv(path: Path, fields: Sequence[str], rows: Iterable[Mapping[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fields})


def load_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise BathroomRiverPrototypeError(f"missing prerequisite JSON: {path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise BathroomRiverPrototypeError(f"invalid JSON {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise BathroomRiverPrototypeError(f"expected JSON object: {path}")
    return value


def safe_member_name(raw: str) -> str:
    path = PurePosixPath(raw)
    if path.is_absolute() or not path.parts or ".." in path.parts:
        raise BathroomRiverPrototypeError(f"unsafe report archive member: {raw}")
    return path.as_posix()


def extract_archive(archive: Path, destination: Path) -> Path:
    if not archive.is_file():
        raise BathroomRiverPrototypeError(f"missing prerequisite report: {archive}")
    listed = subprocess.run(
        ["tar", "--zstd", "-tf", str(archive)], text=True,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False,
    )
    if listed.returncode:
        raise BathroomRiverPrototypeError(f"cannot list {archive}: {listed.stderr.strip()}")
    roots = {
        PurePosixPath(safe_member_name(line.strip())).parts[0]
        for line in listed.stdout.splitlines() if line.strip()
    }
    if len(roots) != 1:
        raise BathroomRiverPrototypeError(f"expected one report root in {archive}, found {sorted(roots)}")
    destination.mkdir(parents=True, exist_ok=True)
    done = subprocess.run(
        ["tar", "--zstd", "-xf", str(archive), "-C", str(destination)], text=True,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False,
    )
    if done.returncode:
        raise BathroomRiverPrototypeError(f"cannot extract {archive}: {done.stderr.strip()}")
    return destination / next(iter(roots))


def locate_report_root(report_root: Path, directory_name: str, archive_name: str, temporary: Path) -> Path:
    direct = report_root / directory_name
    if direct.is_dir():
        return direct
    return extract_archive(report_root / archive_name, temporary)


def atomic_bytes(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_bytes(data)
    os.replace(temporary, path)


def atomic_json(path: Path, value: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def make_report_archive(source_dir: Path, output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(output.name + ".tmp")
    temporary.unlink(missing_ok=True)
    done = subprocess.run(
        ["tar", "--zstd", "-cf", str(temporary), "-C", str(source_dir.parent), source_dir.name],
        text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False,
    )
    if done.returncode:
        raise BathroomRiverPrototypeError(f"cannot create report archive: {done.stderr.strip()}")
    os.replace(temporary, output)


def validate_stage68(root: Path) -> tuple[dict[str, Any], dict[str, str]]:
    summary = load_json(root / "SUMMARY.json")
    if summary.get("type") != "br_quartet_restoration_bathroom_ordinary_field_control_evidence_summary":
        raise BathroomRiverPrototypeError("stage-68 report has an unexpected summary type")
    if summary.get("tool_version") != EXPECTED_STAGE68_TOOL_VERSION:
        raise BathroomRiverPrototypeError("stage-68 report must use tool version 0.0.78")
    if summary.get("status") != "bathroom_ordinary_field_control_and_river_static_promotion_audit_complete_no_payload_written":
        raise BathroomRiverPrototypeError("stage-68 report is not complete")
    expected = {
        "target_opl2_cell_rows": 61,
        "opl2_safe_local_prototype_rows": 0,
        "river_static_promotion_review_rows": 1,
        "river_static_local_prototype_authorized_rows": 1,
        "safe_local_prototype_rows": 1,
    }
    for field, value in expected.items():
        if parse_int(summary.get(field), -1) != value:
            raise BathroomRiverPrototypeError(f"stage-68 {field} must be {value}")
    if not parse_bool(summary.get("ordinary_control_scope_sufficient")):
        raise BathroomRiverPrototypeError("stage-68 ordinary control scope must be sufficient")
    if parse_int(summary.get("ordinary_control_member_rows"), 0) < 3:
        raise BathroomRiverPrototypeError("stage-68 must contain at least three ordinary controls")
    policy = summary.get("policy") or {}
    if not isinstance(policy, dict):
        raise BathroomRiverPrototypeError("stage-68 policy is malformed")
    for field in (
        "installed_games_modified", "candidate_member_payloads_written", "parent_archive_repack_performed",
        "pak_repack_performed", "core_registry_modified", "activation_or_rollback_invoked",
        "runtime_validation_inferred", "censorship_classification_inferred",
        "opaque_binary_field_semantics_inferred", "translation_or_dlc_workstreams_modified",
    ):
        if parse_bool(policy.get(field)):
            raise BathroomRiverPrototypeError(f"stage-68 policy field {field} must be false")
    if not parse_bool(policy.get("river_authorization_is_limited_to_a_local_member_prototype")):
        raise BathroomRiverPrototypeError("stage-68 must limit river authorization to a local member prototype")

    rows = read_tsv(root / "BATHROOM_RIVER_STATIC_PROMOTION_REVIEW.tsv")
    if len(rows) != 1:
        raise BathroomRiverPrototypeError("stage-68 must contain exactly one river review row")
    row = rows[0]
    checks = {
        "member_key": row.get("member_key") == MEMBER_KEY,
        "candidate_kind": row.get("candidate_kind") == "complete_word_set_with_repeated_tail_guard_exception",
        "selected_cell_indices": row.get("selected_cell_indices") == "0;1;2;3;4;5;6",
        "selected_cell_count": parse_int(row.get("selected_cell_count"), -1) == EXPECTED_CELL_COUNT,
        "candidate_sha256": row.get("candidate_sha256") == EXPECTED_CANDIDATE_SHA256,
        "candidate_size": parse_int(row.get("candidate_size"), -1) == EXPECTED_CANDIDATE_SIZE,
        "target_distance": parse_int(row.get("target_distance_to_source"), -1) == EXPECTED_TARGET_DISTANCE,
        "candidate_distance": parse_int(row.get("candidate_distance_to_source"), -1) == 0,
        "distance_improvement": parse_int(row.get("distance_improvement"), -1) == EXPECTED_TARGET_DISTANCE,
        "exact_original": parse_bool(row.get("exact_original")),
        "exact_reverse": parse_bool(row.get("exact_target_reverse_roundtrip")),
        "tail_exception_rows": parse_int(row.get("repeated_tail_guard_exception_rows"), -1) == EXPECTED_TAIL_EXCEPTION_COUNT,
        "tail_occurrences": parse_int(row.get("tail_transition_occurrence_count"), -1) == EXPECTED_TAIL_TRANSITION_OCCURRENCES,
        "tail_support": parse_int(row.get("tail_eligible_support_occurrence_count"), -1) == EXPECTED_TAIL_ELIGIBLE_SUPPORT,
        "suffix_identical": parse_bool(row.get("bytes_after_tail_word_identical")),
        "authorized": parse_bool(row.get("static_local_prototype_authorized")),
        "semantics_unassigned": not parse_bool(row.get("semantics_assigned")),
        "classification": row.get("classification") == "exact_original_small_river_descriptor_supported_by_repeated_tail_transition",
    }
    failed = [name for name, passed in checks.items() if not passed]
    if failed:
        raise BathroomRiverPrototypeError("stage-68 river authorization changed: " + ", ".join(failed))
    return summary, row


def reconstruct_river_candidate(source: bytes, target: bytes) -> tuple[bytes, list[dict[str, Any]], dict[str, bool]]:
    if len(source) != EXPECTED_CANDIDATE_SIZE or len(target) != EXPECTED_CANDIDATE_SIZE:
        raise BathroomRiverPrototypeError("river member size changed")
    cells = STAGE66.build_word_cells(
        source=source, target=target, extension=".bin", header_guard_bytes=16, tail_guard_bytes=16,
    )
    eligible = [cell for cell in cells if bool(cell.get("eligible"))]
    excluded = [cell for cell in cells if not bool(cell.get("eligible"))]
    tail = [cell for cell in excluded if str(cell.get("exclusion_reasons")) == "touches_guarded_tail"]
    if len(cells) != EXPECTED_CELL_COUNT or len(eligible) != EXPECTED_ELIGIBLE_CELL_COUNT or len(tail) != EXPECTED_TAIL_EXCEPTION_COUNT:
        raise BathroomRiverPrototypeError("river word-cell inventory changed")
    tail_cell = tail[0]
    transition = str(tail_cell["transition_id"])
    matching = [cell for cell in cells if str(cell["transition_id"]) == transition]
    matching_eligible = [cell for cell in matching if bool(cell.get("eligible"))]
    candidate = STAGE66.apply_cells(target, cells)
    reverse = STAGE66.reverse_cells(candidate, cells)
    end = int(tail_cell["end"])
    checks = {
        "source_target_equal_size": len(source) == len(target),
        "target_distance_expected": STAGE66.hamming_distance(source, target) == EXPECTED_TARGET_DISTANCE,
        "seven_changed_word_cells": len(cells) == EXPECTED_CELL_COUNT,
        "six_normal_eligible_cells": len(eligible) == EXPECTED_ELIGIBLE_CELL_COUNT,
        "one_tail_guard_exception": len(tail) == EXPECTED_TAIL_EXCEPTION_COUNT,
        "tail_transition_occurs_three_times": len(matching) == EXPECTED_TAIL_TRANSITION_OCCURRENCES,
        "tail_transition_has_two_normal_supports": len(matching_eligible) == EXPECTED_TAIL_ELIGIBLE_SUPPORT,
        "bytes_after_tail_word_identical": source[end:] == target[end:],
        "candidate_exact_original": candidate == source,
        "candidate_sha256_expected": hashlib.sha256(candidate).hexdigest() == EXPECTED_CANDIDATE_SHA256,
        "exact_target_reverse_roundtrip": reverse == target,
        "header_preserved_from_target": candidate[:16] == target[:16],
        "no_size_change": len(candidate) == len(target),
    }
    return candidate, cells, checks


def build(
    *, project_root: Path, workspace_root: Path, report_root: Path,
    maximum_earc_bytes: int, maximum_payload_bytes: int,
    pair_loader: Callable[..., tuple[list[dict[str, Any]], list[dict[str, Any]]]] | None = None,
) -> tuple[Path, dict[str, Any]]:
    with tempfile.TemporaryDirectory(prefix="br-stage69-") as temporary_name:
        temporary = Path(temporary_name)
        stage68_root = locate_report_root(report_root, STAGE68_DIR, STAGE68_ARCHIVE, temporary / "stage68")
        stage68_summary, stage68_row = validate_stage68(stage68_root)
        stage65_root = STAGE68.locate_report_root(report_root, "expanded_scene_effect_member_evidence", "BR_quartet_restoration_expanded_scene_effect_member_evidence.tar.zst", temporary / "stage65")
        stage66_root = STAGE68.locate_report_root(report_root, "bathroom_scene_descriptor_word_evidence", "BR_quartet_restoration_bathroom_scene_descriptor_word_evidence.tar.zst", temporary / "stage66")
        shader_root = STAGE68.locate_report_root(report_root, "shader_effect_evidence", "BR_quartet_restoration_shader_effect_evidence.tar.zst", temporary / "shader")

        _stage65_summary, stage65_rows = STAGE67.validate_stage65_report(stage65_root)
        _stage66_summary, _stage66_members, stage66_cells = STAGE67.validate_stage66_report(stage66_root)
        _shader_summary, payload_metadata = STAGE66.load_shader_metadata(shader_root)
        scope_pairs = STAGE67.load_scope_pairs(
            project_root=project_root, workspace_root=workspace_root, report_root=report_root,
            stage65_rows=stage65_rows, maximum_earc_bytes=maximum_earc_bytes, pair_loader=pair_loader,
        )
        payloads = STAGE67.verify_payload_metadata(
            stage65_rows=stage65_rows, pairs=scope_pairs, metadata=payload_metadata,
            maximum_payload_bytes=maximum_payload_bytes,
        )
        source, target = payloads[MEMBER_KEY]
        recomputed_cells = STAGE66.build_word_cells(
            source=source, target=target, extension=".bin", header_guard_bytes=16, tail_guard_bytes=16,
        )
        STAGE67.compare_recomputed_cells(recomputed_cells, stage66_cells[MEMBER_KEY], member_key=MEMBER_KEY)
        candidate, cells, reconstruction_checks = reconstruct_river_candidate(source, target)

        checks = {
            "stage68_report_canonical": stage68_summary.get("tool_version") == EXPECTED_STAGE68_TOOL_VERSION,
            "stage68_authorization_present": parse_bool(stage68_row.get("static_local_prototype_authorized")),
            "stage68_candidate_hash_matches": stage68_row.get("candidate_sha256") == hashlib.sha256(candidate).hexdigest(),
            "stage66_cells_recomputed_exactly": len(cells) == len(stage66_cells[MEMBER_KEY]),
            **reconstruction_checks,
        }
        validation_rows = [
            {
                "profile_id": PROFILE_ID,
                "member_key": MEMBER_KEY,
                "check_name": name,
                "passed": passed,
                "review_status": "static_member_prototype_validation",
            }
            for name, passed in checks.items()
        ]
        failures = [name for name, passed in checks.items() if not passed]

        prototype_root = workspace_root / PROTOTYPE_SUBDIR
        if prototype_root.exists():
            shutil.rmtree(prototype_root)
        prototype_root.mkdir(parents=True, exist_ok=True)
        profile_rows: list[dict[str, object]] = []
        file_rows: list[dict[str, object]] = []
        selected_rows: list[dict[str, object]] = []
        skipped_rows: list[dict[str, object]] = []

        if failures:
            skipped_rows.append({"profile_id": PROFILE_ID, "member_key": MEMBER_KEY, "reason": "prototype_validation_failed:" + ";".join(failures)})
        else:
            profile_dir = prototype_root / PROFILE_ID
            member_dir = profile_dir / "members"
            member_name = MEMBER_KEY.rsplit("#", 1)[0]
            candidate_path = member_dir / member_name
            atomic_bytes(candidate_path, candidate)
            candidate_relative = candidate_path.relative_to(profile_dir)
            manifest = {
                "type": "br_quartet_restoration_local_member_prototype",
                "format_version": 1,
                "tool_version": TOOL_VERSION,
                "profile_id": PROFILE_ID,
                "classification": "exact_original_small_river_descriptor_member_prototype",
                "parent_container": PARENT_PATH,
                "member_key": MEMBER_KEY,
                "candidate_relative_path": candidate_relative.as_posix(),
                "source_sha256": hashlib.sha256(source).hexdigest(),
                "target_sha256": hashlib.sha256(target).hexdigest(),
                "candidate_sha256": hashlib.sha256(candidate).hexdigest(),
                "source_size": len(source),
                "target_size": len(target),
                "candidate_size": len(candidate),
                "selected_cell_indices": [int(cell["cell_index"]) for cell in cells],
                "tail_guard_exception_used": True,
                "semantics_assigned": False,
                "runtime_validated": False,
                "parent_archive_rebuilt": False,
                "pak_repacked": False,
                "installed_game_modified": False,
            }
            atomic_json(profile_dir / "PROTOTYPE.json", manifest)
            profile_rows.append({
                "profile_id": PROFILE_ID,
                "classification": manifest["classification"],
                "parent_container": PARENT_PATH,
                "member_key": MEMBER_KEY,
                "candidate_sha256": manifest["candidate_sha256"],
                "candidate_size": len(candidate),
                "selected_cell_count": len(cells),
                "tail_guard_exception_used": True,
                "local_profile_root": str(profile_dir.relative_to(project_root)) if profile_dir.is_relative_to(project_root) else str(profile_dir),
                "validation_status": "passed",
                "semantics_assigned": False,
                "runtime_validated": False,
                "review_status": "local_member_only_not_repacked_not_registered_not_installed",
            })
            file_rows.append({
                "profile_id": PROFILE_ID,
                "parent_container": PARENT_PATH,
                "member_key": MEMBER_KEY,
                "source_sha256": manifest["source_sha256"],
                "target_sha256": manifest["target_sha256"],
                "candidate_sha256": manifest["candidate_sha256"],
                "source_size": len(source),
                "target_size": len(target),
                "candidate_size": len(candidate),
                "target_distance_to_source": STAGE66.hamming_distance(source, target),
                "candidate_distance_to_source": STAGE66.hamming_distance(source, candidate),
                "distance_improvement": STAGE66.hamming_distance(source, target),
                "candidate_relative_path": candidate_relative.as_posix(),
            })
            for cell in cells:
                selected_rows.append({
                    "profile_id": PROFILE_ID,
                    "member_key": MEMBER_KEY,
                    "cell_index": cell["cell_index"],
                    "start": cell["start"],
                    "end": cell["end"],
                    "source_hex": cell["source_hex"],
                    "target_hex": cell["target_hex"],
                    "transition_id": cell["transition_id"],
                    "normal_eligibility": cell["eligible"],
                    "exception_reason": cell["exclusion_reasons"],
                    "semantics_assigned": False,
                })

        outdir = report_root / EVIDENCE_DIR_NAME
        if outdir.exists():
            shutil.rmtree(outdir)
        outdir.mkdir(parents=True, exist_ok=True)
        write_tsv(outdir / "BATHROOM_RIVER_MEMBER_PROTOTYPE_PROFILES.tsv", [
            "profile_id", "classification", "parent_container", "member_key", "candidate_sha256", "candidate_size",
            "selected_cell_count", "tail_guard_exception_used", "local_profile_root", "validation_status",
            "semantics_assigned", "runtime_validated", "review_status",
        ], profile_rows)
        write_tsv(outdir / "BATHROOM_RIVER_MEMBER_PROTOTYPE_FILES.tsv", [
            "profile_id", "parent_container", "member_key", "source_sha256", "target_sha256", "candidate_sha256",
            "source_size", "target_size", "candidate_size", "target_distance_to_source", "candidate_distance_to_source",
            "distance_improvement", "candidate_relative_path",
        ], file_rows)
        write_tsv(outdir / "BATHROOM_RIVER_MEMBER_PROTOTYPE_SELECTED_WORDS.tsv", [
            "profile_id", "member_key", "cell_index", "start", "end", "source_hex", "target_hex", "transition_id",
            "normal_eligibility", "exception_reason", "semantics_assigned",
        ], selected_rows)
        write_tsv(outdir / "BATHROOM_RIVER_MEMBER_PROTOTYPE_VALIDATIONS.tsv", [
            "profile_id", "member_key", "check_name", "passed", "review_status",
        ], validation_rows)
        write_tsv(outdir / "BATHROOM_RIVER_MEMBER_PROTOTYPE_SKIPPED.tsv", ["profile_id", "member_key", "reason"], skipped_rows)
        summary = {
            "type": "br_quartet_restoration_bathroom_river_member_prototype_evidence_summary",
            "format_version": 1,
            "tool_version": TOOL_VERSION,
            "source_stage68_tool_version": EXPECTED_STAGE68_TOOL_VERSION,
            "status": "exact_bathroom_river_member_prototype_built_not_repacked_or_installed" if profile_rows else "bathroom_river_member_prototype_not_built",
            "proposed_profile_rows": 1,
            "promoted_profile_rows": len(profile_rows),
            "prototype_file_rows": len(file_rows),
            "selected_word_rows": len(selected_rows),
            "validation_rows": len(validation_rows),
            "validation_failures": sum(not parse_bool(row.get("passed")) for row in validation_rows),
            "skipped_rows": len(skipped_rows),
            "candidate_sha256": EXPECTED_CANDIDATE_SHA256 if profile_rows else "",
            "candidate_size": EXPECTED_CANDIDATE_SIZE if profile_rows else None,
            "candidate_distance_to_original": 0 if profile_rows else None,
            "policy": {
                "installed_games_modified": False,
                "candidate_member_payload_written_only_under_local_workspace": True,
                "candidate_member_payload_exported_in_report": False,
                "parent_archive_repack_performed": False,
                "pak_repack_performed": False,
                "core_registry_modified": False,
                "activation_or_rollback_invoked": False,
                "runtime_validation_inferred": False,
                "censorship_classification_inferred": False,
                "opaque_binary_field_semantics_inferred": False,
                "opl2_payload_built": False,
                "translation_or_dlc_workstreams_modified": False,
            },
            "next_action": "Upload this metadata report. If promoted_profile_rows is 1 with zero failures/skips, prepare a separate local parent-Elixir rebuild test next; do not repack a PAK, modify registry, activate or write to the game yet.",
        }
        atomic_json(outdir / "SUMMARY.json", summary)
        output = report_root / REPORT_NAME
        make_report_archive(outdir, output)
        return output, summary


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path, default=PROJECT_ROOT_DEFAULT)
    parser.add_argument("--workspace-root", type=Path)
    parser.add_argument("--report-root", type=Path)
    parser.add_argument("--maximum-earc-bytes", type=int, default=512 * 1024 * 1024)
    parser.add_argument("--maximum-payload-bytes", type=int, default=8 * 1024 * 1024)
    args = parser.parse_args(argv)
    project_root = args.project_root.resolve()
    workspace_root = (args.workspace_root or project_root / ".local/build/quartet_restoration").resolve()
    report_root = (args.report_root or project_root / ".local/reports/quartet_restoration").resolve()
    try:
        output, summary = build(
            project_root=project_root, workspace_root=workspace_root, report_root=report_root,
            maximum_earc_bytes=args.maximum_earc_bytes, maximum_payload_bytes=args.maximum_payload_bytes,
        )
    except (BathroomRiverPrototypeError, STAGE68.OrdinaryFieldControlError, STAGE67.SiblingDescriptorError, STAGE66.BathroomWordAuditError, BR.RestorationError, OSError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print(f"Bathroom river member prototypes built: {summary['promoted_profile_rows']}")
    print(f"Prototype validation failures: {summary['validation_failures']}")
    print(f"Report: {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
