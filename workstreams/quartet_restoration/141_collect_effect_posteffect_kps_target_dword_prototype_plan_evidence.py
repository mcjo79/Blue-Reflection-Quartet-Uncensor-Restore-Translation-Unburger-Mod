#!/usr/bin/env python3
"""Stage 141: metadata-only target-side KPS dword prototype planner.

Consumes the verified stage-140 report. It admits only whole programs classified
as ``bounded_target_dword_edit_candidate`` and converts their exact changed-word
coordinates into a deterministic no-write plan. The plan records target-side
preconditions and the corresponding Original word proposed for a future local
prototype, but emits no KPS/DXBC payload, builds no patch, and authorizes no
write or runtime promotion.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import shutil
import subprocess
import tempfile
from collections import Counter, defaultdict
from pathlib import Path, PurePosixPath
from typing import Any, Iterable, Mapping, Sequence

TOOL_VERSION = "0.1.59"
REPORT_DIR = "effect_posteffect_kps_target_dword_prototype_plan_evidence"
REPORT_NAME = "BR_quartet_restoration_effect_posteffect_kps_target_dword_prototype_plan_evidence.tar.zst"
STAGE140_NAME = "BR_quartet_restoration_effect_posteffect_exact_section_content_kps_minimal_patch_feasibility_evidence.tar.zst"
STAGE140_SHA256 = "dbb672ecf2821c5e84e2eb9d1027a060395b8136871ff677705fa65b624b2566"
STAGE140_DIR = "effect_posteffect_exact_section_content_kps_minimal_patch_feasibility_evidence"
STAGE140_SUMMARY_SHA256 = "d841145d03e692e7039a3b45be79044226c04c5adcbd4e7294001d9223f40335"
EXPECTED_FEASIBILITY_ROWS = 16
EXPECTED_ADMITTED_PROGRAMS = 15
EXPECTED_EXCLUDED_STABLE_PROGRAMS = 1
EXPECTED_ALL_DWORD_ROWS = 232
EXPECTED_PLANNED_DWORD_ROWS = 227
EXPECTED_CHANGED_INSTRUCTION_ROWS = 58
FORBIDDEN_EXTENSIONS = (
    ".pak", ".g1e", ".g1em", ".g1m", ".g1s", ".g1t", ".kps", ".dxbc",
    ".elixir", ".elixir.gz", ".ebd", ".ebm",
)


class CollectorError(RuntimeError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise CollectorError(message)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def stable_id(*parts: object) -> str:
    value = "\0".join(str(part) for part in parts).encode("utf-8")
    return hashlib.sha256(value).hexdigest()[:24]


def safe_relative(value: str, label: str) -> str:
    path = PurePosixPath(str(value).replace("\\", "/"))
    require(bool(path.parts) and not path.is_absolute() and ".." not in path.parts, f"unsafe {label}: {value}")
    return path.as_posix()


def parse_bool(value: object) -> bool:
    return str(value).strip().casefold() in {"1", "true", "yes", "y"}


def read_tsv(path: Path) -> list[dict[str, str]]:
    require(path.is_file(), f"missing TSV: {path}")
    with path.open(encoding="utf-8", newline="") as handle:
        return [dict(row) for row in csv.DictReader(handle, delimiter="\t")]


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


def extract_report(archive: Path, destination: Path) -> Path:
    listed = subprocess.run(["tar", "--zstd", "-tf", str(archive)], text=True, capture_output=True)
    require(listed.returncode == 0, listed.stderr.strip() or "cannot list stage-140 report")
    names = [safe_relative(line, "report member") for line in listed.stdout.splitlines() if line.strip()]
    require(names and {PurePosixPath(name).parts[0] for name in names} == {STAGE140_DIR}, "unexpected stage-140 report root")
    destination.mkdir(parents=True, exist_ok=True)
    completed = subprocess.run(["tar", "--zstd", "-xf", str(archive), "-C", str(destination)], text=True, capture_output=True)
    require(completed.returncode == 0, completed.stderr.strip() or "cannot extract stage-140 report")
    root = destination / STAGE140_DIR
    require(root.is_dir(), f"missing extracted report root: {root}")
    return root


def make_archive(source: Path, output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(output.name + ".tmp")
    temporary.unlink(missing_ok=True)
    completed = subprocess.run(["tar", "--zstd", "-cf", str(temporary), "-C", str(source.parent), source.name], text=True, capture_output=True)
    require(completed.returncode == 0, completed.stderr.strip() or "archive creation failed")
    os.replace(temporary, output)


def topology(edit_rows: int, instruction_rows: int) -> str:
    if instruction_rows == 1 and edit_rows == 1:
        return "single_instruction_single_word"
    if instruction_rows == 1:
        return "single_instruction_multiword"
    if edit_rows <= 4:
        return "few_instruction_few_word"
    return "multi_instruction_multiword"


def build_report(
    project_root: Path,
    *,
    report_root: Path | None = None,
    output_report_root: Path | None = None,
    create_archive: bool = True,
) -> tuple[Path | None, dict[str, Any]]:
    project_root = project_root.resolve()
    version_path = project_root / "workstreams/quartet_restoration/VERSION"
    require(version_path.is_file(), f"missing VERSION: {version_path}")
    version = tuple(int(part) for part in version_path.read_text(encoding="utf-8").strip().split("."))
    require(version >= (0, 1, 59), f"stage 141 requires quartet_restoration 0.1.59 or newer, found {version_path.read_text().strip()}")

    report_root = (report_root or project_root / ".local/reports/quartet_restoration").resolve()
    output_report_root = (output_report_root or report_root).resolve()
    archive = report_root / STAGE140_NAME
    require(archive.is_file(), f"missing prerequisite report: {archive}")
    archive_hash = sha256_file(archive)
    require(archive_hash == STAGE140_SHA256, f"unexpected stage-140 SHA-256: {archive_hash}")

    with tempfile.TemporaryDirectory(prefix="stage141-prereq-") as temporary_text:
        temporary = Path(temporary_text)
        root = report_root / STAGE140_DIR
        if not root.is_dir():
            root = extract_report(archive, temporary)
        summary_path = root / "SUMMARY.json"
        require(summary_path.is_file(), f"missing stage-140 summary: {summary_path}")
        summary_hash = sha256_file(summary_path)
        require(summary_hash == STAGE140_SUMMARY_SHA256, f"unexpected stage-140 summary SHA-256: {summary_hash}")
        summary140 = json.loads(summary_path.read_text(encoding="utf-8"))
        require(summary140.get("kps_exact_interface_opcode_stable_program_rows") == EXPECTED_FEASIBILITY_ROWS, "stage-140 feasibility count drift")
        require(summary140.get("kps_minimal_patch_feasibility") == {
            "bounded_target_dword_edit_candidate": EXPECTED_ADMITTED_PROGRAMS,
            "opcode_inventory_equal_but_instruction_envelope_delta": EXPECTED_EXCLUDED_STABLE_PROGRAMS,
        }, "stage-140 feasibility partition drift")
        require(summary140.get("kps_bounded_dword_edit_candidate_rows") == EXPECTED_ALL_DWORD_ROWS, "stage-140 dword row count drift")
        require(summary140.get("runtime_validated_profile_rows_preserved") == 1, "runtime profile cardinality drift")
        require(summary140.get("runtime_validated_profile_id_preserved") == "candidate_bathroom_river_containing_pak_static_inverse_062e39915e7d", "runtime profile identity drift")
        require(summary140.get("runtime_failed_shader_rows_preserved") == 2, "runtime-failed shader count drift")
        require(summary140.get("skipped_rows") == 0, "stage-140 contains skipped rows")

        feasibility = read_tsv(root / "KPS_MINIMAL_PATCH_FEASIBILITY.tsv")
        dword_rows = read_tsv(root / "KPS_BOUNDED_DWORD_EDIT_CANDIDATES.tsv")
        nonminimal = read_tsv(root / "KPS_NONMINIMAL_PROGRAM_CARRY_FORWARD.tsv")
        g1e_families = read_tsv(root / "G1E_FAMILY_EXACT_SECTION_RESIDUAL_SUMMARY.tsv")
        unresolved = read_tsv(root / "UNRESOLVED_G1EM_G1T_SHADER_CARRY_FORWARD.tsv")
        require(len(feasibility) == EXPECTED_FEASIBILITY_ROWS, "stage-140 feasibility table drift")
        require(len(dword_rows) == EXPECTED_ALL_DWORD_ROWS, "stage-140 dword table drift")
        require(len(g1e_families) == 7, "stage-140 G1E family count drift")
        require(len(unresolved) == 25, "stage-140 unresolved carry-forward drift")

        admitted = {
            (row["normalized_path"], row["member_key"], row["program_pair_index"]): row
            for row in feasibility
            if row["minimal_patch_feasibility"] == "bounded_target_dword_edit_candidate"
        }
        excluded_stable = [row for row in feasibility if row["minimal_patch_feasibility"] != "bounded_target_dword_edit_candidate"]
        require(len(admitted) == EXPECTED_ADMITTED_PROGRAMS, "expected fifteen admitted KPS programs")
        require(len(excluded_stable) == EXPECTED_EXCLUDED_STABLE_PROGRAMS, "expected one excluded stable-interface KPS program")

        edits_by_program: dict[tuple[str, str, str], list[dict[str, str]]] = defaultdict(list)
        rejected_word_rows: list[dict[str, Any]] = []
        for row in dword_rows:
            key = (row["normalized_path"], row["member_key"], row["program_pair_index"])
            if key in admitted:
                require(parse_bool(row["minimal_patch_word_candidate"]), f"admitted program contains noncandidate word: {key}")
                require(row["source_u32_hex"] != row["target_u32_hex"], f"no-op edit row: {key}")
                edits_by_program[key].append(row)
            else:
                rejected_word_rows.append({**row, "rejection_reason": "program_not_admitted_as_bounded_target_dword_edit_candidate"})
        require(len(edits_by_program) == EXPECTED_ADMITTED_PROGRAMS, "admitted program lost edit rows")
        require(sum(len(rows) for rows in edits_by_program.values()) == EXPECTED_PLANNED_DWORD_ROWS, "planned dword count drift")

        plan_rows: list[dict[str, Any]] = []
        program_rows: list[dict[str, Any]] = []
        member_acc: dict[tuple[str, str, str], dict[str, Any]] = {}
        coordinate_values: dict[tuple[str, str, str, str, str, str], set[tuple[str, str]]] = defaultdict(set)
        changed_instruction_total = 0

        for key in sorted(admitted):
            base = admitted[key]
            edits = sorted(edits_by_program[key], key=lambda row: (
                row["code_chunk_key"], int(row["instruction_index"]), int(row["instruction_dword_index"])
            ))
            program_plan_id = stable_id("kps-program-plan", *key)
            instruction_count = len({(row["code_chunk_key"], row["instruction_index"]) for row in edits})
            changed_instruction_total += instruction_count
            code_chunks = sorted({row["code_chunk_key"] for row in edits})
            require(len(code_chunks) == 1, f"bounded planner requires one code chunk per program: {key}")
            for ordinal, row in enumerate(edits, start=1):
                coordinate = (
                    row["normalized_path"], row["member_key"], row["program_pair_index"], row["code_chunk_key"],
                    row["instruction_index"], row["instruction_dword_index"],
                )
                coordinate_values[coordinate].add((row["target_u32_hex"], row["source_u32_hex"]))
                plan_rows.append({
                    "program_plan_id": program_plan_id,
                    "edit_plan_id": stable_id("kps-dword-edit", *coordinate),
                    "edit_ordinal": ordinal,
                    "normalized_path": row["normalized_path"],
                    "member_key": row["member_key"],
                    "member_name": row["member_name"],
                    "program_pair_index": row["program_pair_index"],
                    "code_chunk_key": row["code_chunk_key"],
                    "instruction_index": row["instruction_index"],
                    "instruction_dword_index": row["instruction_dword_index"],
                    "word_role": row["word_role"],
                    "expected_target_u32_hex": row["target_u32_hex"],
                    "proposed_original_u32_hex": row["source_u32_hex"],
                    "precondition_required": True,
                    "edit_applied": False,
                    "prototype_built": False,
                    "runtime_confirmed": False,
                    "write_authorized": False,
                })
            program_rows.append({
                "program_plan_id": program_plan_id,
                "normalized_path": base["normalized_path"],
                "member_key": base["member_key"],
                "member_name": base["member_name"],
                "program_pair_index": base["program_pair_index"],
                "code_chunk_key": code_chunks[0],
                "planned_edit_rows": len(edits),
                "changed_instruction_rows": instruction_count,
                "edit_topology": topology(len(edits), instruction_count),
                "exact_interface_equal": base["exact_interface_equal"],
                "exact_opcode_inventory_equal": base["exact_opcode_inventory_equal"],
                "opcode_sequence_equal": base["opcode_sequence_equal"],
                "instruction_length_sequence_equal": base["instruction_length_sequence_equal"],
                "all_target_preconditions_required": True,
                "prototype_built": False,
                "patch_built": False,
                "runtime_confirmed": False,
                "write_authorized": False,
            })
            member_key = (base["normalized_path"], base["member_key"], base["member_name"])
            acc = member_acc.setdefault(member_key, {"programs": 0, "edits": 0, "instructions": 0, "plans": []})
            acc["programs"] += 1
            acc["edits"] += len(edits)
            acc["instructions"] += instruction_count
            acc["plans"].append(program_plan_id)

        conflict_rows: list[dict[str, Any]] = []
        for coordinate, values in sorted(coordinate_values.items()):
            if len(values) <= 1:
                continue
            conflict_rows.append({
                "normalized_path": coordinate[0], "member_key": coordinate[1], "program_pair_index": coordinate[2],
                "code_chunk_key": coordinate[3], "instruction_index": coordinate[4], "instruction_dword_index": coordinate[5],
                "conflicting_value_pairs": " || ".join(f"{before}->{after}" for before, after in sorted(values)),
                "write_authorized": False,
            })
        require(not conflict_rows, "conflicting target coordinates in KPS prototype plan")
        require(len(coordinate_values) == EXPECTED_PLANNED_DWORD_ROWS, "duplicate edit coordinate drift")
        require(changed_instruction_total == EXPECTED_CHANGED_INSTRUCTION_ROWS, "changed instruction count drift")

        member_rows = []
        for (normalized_path, member_key, member_name), acc in sorted(member_acc.items()):
            member_rows.append({
                "normalized_path": normalized_path,
                "member_key": member_key,
                "member_name": member_name,
                "planned_program_rows": acc["programs"],
                "planned_edit_rows": acc["edits"],
                "changed_instruction_rows": acc["instructions"],
                "program_plan_ids": " || ".join(sorted(acc["plans"])),
                "prototype_built": False,
                "runtime_confirmed": False,
                "write_authorized": False,
            })
        require(len(member_rows) == 2, "expected two KPS members in prototype plan")

        excluded_rows: list[dict[str, Any]] = []
        for row in excluded_stable:
            excluded_rows.append({
                "normalized_path": row["normalized_path"], "member_key": row["member_key"], "member_name": row["member_name"],
                "program_pair_index": row["program_pair_index"], "classification": row["classification"],
                "exclusion_reason": row["minimal_patch_feasibility"], "prototype_built": False, "write_authorized": False,
            })
        for row in nonminimal:
            excluded_rows.append({
                "normalized_path": row.get("normalized_path", ""), "member_key": row.get("member_key", ""),
                "member_name": row.get("member_name", ""), "program_pair_index": row.get("program_pair_index", ""),
                "classification": row.get("classification", ""), "exclusion_reason": row.get("minimal_patch_feasibility", "nonminimal_program"),
                "prototype_built": False, "write_authorized": False,
            })
        require(len(excluded_rows) == 28, "excluded program count drift")

        output = output_report_root / REPORT_DIR
        shutil.rmtree(output, ignore_errors=True)
        output.mkdir(parents=True, exist_ok=True)
        write_tsv(output / "INPUT_HASHES.tsv", ["input_id", "relative_path", "sha256", "verified"], [
            {"input_id": STAGE140_DIR, "relative_path": STAGE140_NAME, "sha256": archive_hash, "verified": True},
            {"input_id": f"{STAGE140_DIR}_summary", "relative_path": f"{STAGE140_DIR}/SUMMARY.json", "sha256": summary_hash, "verified": True},
        ])
        write_tsv(output / "KPS_PROGRAM_TARGET_DWORD_PROTOTYPE_PLAN.tsv", list(program_rows[0]), program_rows)
        write_tsv(output / "KPS_TARGET_DWORD_EDIT_PLAN.tsv", list(plan_rows[0]), plan_rows)
        write_tsv(output / "KPS_MEMBER_PROTOTYPE_PLAN.tsv", list(member_rows[0]), member_rows)
        write_tsv(output / "KPS_EXCLUDED_PROGRAMS.tsv", list(excluded_rows[0]), excluded_rows)
        write_tsv(output / "KPS_EDIT_COORDINATE_CONFLICTS.tsv", [
            "normalized_path", "member_key", "program_pair_index", "code_chunk_key", "instruction_index",
            "instruction_dword_index", "conflicting_value_pairs", "write_authorized",
        ], conflict_rows)
        write_tsv(output / "G1E_UNRESOLVED_CALIBRATION_CARRY_FORWARD.tsv", list(g1e_families[0]), g1e_families)
        write_tsv(output / "UNRESOLVED_G1EM_G1T_SHADER_CARRY_FORWARD.tsv", list(unresolved[0]), unresolved)
        write_tsv(output / "PARSER_SKIPPED.tsv", ["scope", "identity", "reason"], [])

        topology_counts = Counter(row["edit_topology"] for row in program_rows)
        summary = {
            "type": "br_quartet_restoration_effect_posteffect_kps_target_dword_prototype_plan_evidence_summary",
            "format_version": 1,
            "tool_version": TOOL_VERSION,
            "status": "kps_target_dword_prototype_plan_bounded_preconditioned_metadata_only_no_patch_no_write",
            "stage140_report_sha256": archive_hash,
            "stage140_summary_sha256": summary_hash,
            "runtime_validated_profile_rows_preserved": 1,
            "runtime_validated_profile_id_preserved": summary140["runtime_validated_profile_id_preserved"],
            "runtime_failed_shader_rows_preserved": 2,
            "kps_admitted_program_rows": len(program_rows),
            "kps_admitted_member_rows": len(member_rows),
            "kps_planned_target_dword_edit_rows": len(plan_rows),
            "kps_unique_target_coordinate_rows": len(coordinate_values),
            "kps_changed_instruction_rows": changed_instruction_total,
            "kps_program_edit_topologies": dict(sorted(topology_counts.items())),
            "kps_target_precondition_rows": len(plan_rows),
            "kps_excluded_program_rows": len(excluded_rows),
            "kps_rejected_word_rows": len(rejected_word_rows),
            "kps_edit_coordinate_conflict_rows": len(conflict_rows),
            "g1e_unresolved_calibration_family_rows": len(g1e_families),
            "unresolved_g1em_g1t_shader_rows": len(unresolved),
            "prototype_artifact_rows": 0,
            "patch_built_rows": 0,
            "new_runtime_confirmed_rows": 0,
            "field_semantics_confirmed_rows": 0,
            "visual_or_censorship_semantics_confirmed_rows": 0,
            "write_authorized_rows": 0,
            "skipped_rows": 0,
            "policy": {
                "existing_evidence_only": True,
                "local_proprietary_payloads_read": False,
                "proprietary_payloads_in_report": False,
                "target_dword_precondition_required_for_every_planned_edit": True,
                "original_word_treated_as_semantic_or_runtime_proof": False,
                "prototype_or_patch_built": False,
                "runtime_failed_shader_promoted": False,
                "event_profiles_promoted": False,
                "runtime_or_save_required": False,
                "pak_built_or_repacked": False,
                "installed_game_modified": False,
                "profile_or_registry_modified": False,
                "core_modified": False,
                "translation_modified": False,
                "legacy_dlc_modified": False,
                "git_modified": False,
            },
            "next_action": (
                "Use the fifteen admitted program plans only in a separate local no-install prototype builder that rehydrates the exact target KPS, "
                "verifies every target dword precondition, applies proposed Original words to a temporary copy, reparses DXBC, and proves that interface, "
                "opcode sequence, instruction lengths and all untouched dwords remain unchanged. Do not install or runtime-promote any prototype without a later explicit test-lab step."
            ),
        }
        atomic_json(output / "SUMMARY.json", summary)
        report_archive = output_report_root / REPORT_NAME
        if create_archive:
            make_archive(output, report_archive)
        return (report_archive if create_archive else None), summary


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-root", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--report-root", type=Path)
    parser.add_argument("--output-report-root", type=Path)
    parser.add_argument("--no-archive", action="store_true")
    args = parser.parse_args()
    archive, summary = build_report(
        args.project_root,
        report_root=args.report_root,
        output_report_root=args.output_report_root,
        create_archive=not args.no_archive,
    )
    print(json.dumps(summary, indent=2, sort_keys=True))
    if archive:
        print(f"[kps-target-dword-plan] report archive: {archive}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
