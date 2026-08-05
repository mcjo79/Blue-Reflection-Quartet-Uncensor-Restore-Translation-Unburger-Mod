#!/usr/bin/env python3
"""Build one isolated checksum-gated PACK11 repack test for the stage-36 shared-presentation profile."""

from __future__ import annotations

import argparse
import csv
import hashlib
import importlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path, PurePosixPath
from typing import Any, Iterable, Mapping, Sequence

WORKSTREAM_ID = "quartet_restoration"
TOOL_VERSION = "0.0.43"
PROFILE_ID = "shared_presentation_d88c7c3a6f"
STAGE36_TOOL_VERSION = "0.0.42"
STAGE36_EVIDENCE_DIR = "residual_shared_presentation_prototype_evidence"
STAGE36_ARCHIVE = "BR_quartet_restoration_residual_shared_presentation_prototype_evidence.tar.zst"
STAGE36_PROTOTYPE_SUBDIR = "prototypes/residual_shared_presentation"
FINAL_BUILD_SUBDIR = "repack_tests/residual_shared_presentation"
REPORT_NAME = "BR_quartet_restoration_residual_shared_presentation_repack_test_evidence.tar.zst"
EVIDENCE_DIR_NAME = "residual_shared_presentation_repack_test_evidence"
EXPECTED_TARGET_MEMBERS = {
    "event/b1/event_jp/ce11/event_ce11_070.ebd",
    "event/b1/event_jp/em01/event_em01_090.ebd",
}


class SharedPresentationRepackError(RuntimeError):
    pass


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def parse_bool(value: object) -> bool:
    return str(value).strip().casefold() in {"1", "true", "yes", "y"}


def parse_int(value: object, default: int = 0) -> int:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return default


def read_tsv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return [dict(row) for row in csv.DictReader(handle, delimiter="\t")]


def write_tsv(path: Path, fields: Sequence[str], rows: Iterable[Mapping[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fields})


def atomic_json(path: Path, data: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + f".tmp.{os.getpid()}")
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def safe_relative(raw: str, *, label: str) -> str:
    path = PurePosixPath(raw)
    if path.is_absolute() or not path.parts or ".." in path.parts or "." in path.parts:
        raise SharedPresentationRepackError(f"unsafe {label}: {raw}")
    canonical = path.as_posix()
    if canonical != raw:
        raise SharedPresentationRepackError(f"non-canonical {label}: {raw}")
    return canonical


def require_within(path: Path, root: Path, *, label: str) -> None:
    try:
        path.resolve().relative_to(root.resolve())
    except ValueError as exc:
        raise SharedPresentationRepackError(f"{label} escapes allowed root: {path}") from exc


def load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise SharedPresentationRepackError(f"missing JSON: {path}") from exc
    except json.JSONDecodeError as exc:
        raise SharedPresentationRepackError(f"invalid JSON {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise SharedPresentationRepackError(f"JSON root is not an object: {path}")
    return value


def safe_archive_member(raw: str) -> str:
    path = PurePosixPath(raw)
    if path.is_absolute() or not path.parts or ".." in path.parts:
        raise SharedPresentationRepackError(f"unsafe report archive member: {raw}")
    return path.as_posix()


def extract_report(archive: Path, destination: Path) -> None:
    if not archive.is_file():
        raise SharedPresentationRepackError(f"missing prerequisite report: {archive}")
    listing = subprocess.run(
        ["tar", "--zstd", "-tf", str(archive)], check=False, text=True,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    if listing.returncode != 0:
        raise SharedPresentationRepackError(f"cannot list report {archive}: {listing.stderr.strip()}")
    for line in listing.stdout.splitlines():
        if line.strip():
            safe_archive_member(line.strip())
    destination.mkdir(parents=True, exist_ok=True)
    result = subprocess.run(
        ["tar", "--zstd", "-xf", str(archive), "-C", str(destination)], check=False,
        text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    if result.returncode != 0:
        raise SharedPresentationRepackError(f"cannot extract report {archive}: {result.stderr.strip()}")


def find_stage36_evidence(report_root: Path, temporary_root: Path) -> Path:
    direct = report_root / STAGE36_EVIDENCE_DIR
    if direct.is_dir():
        return direct
    extraction = temporary_root / "stage36_report"
    extract_report(report_root / STAGE36_ARCHIVE, extraction)
    matches = [path for path in extraction.rglob(STAGE36_EVIDENCE_DIR) if path.is_dir()]
    if len(matches) != 1:
        raise SharedPresentationRepackError(
            f"expected one {STAGE36_EVIDENCE_DIR} directory, found {len(matches)}"
        )
    return matches[0]


def load_restoration_tool(project_root: Path) -> Any:
    tool_root = project_root / "Blue_Reflection_Text_Tool"
    tool_path = tool_root / "br_restoration_tool.py"
    if not tool_path.is_file():
        raise SharedPresentationRepackError(f"missing restoration tool: {tool_path}")
    sys.path.insert(0, str(tool_root))
    try:
        return importlib.import_module("br_restoration_tool")
    finally:
        try:
            sys.path.remove(str(tool_root))
        except ValueError:
            pass


def make_report_archive(source_dir: Path, output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(output.name + ".tmp")
    temporary.unlink(missing_ok=True)
    result = subprocess.run(
        ["tar", "--zstd", "-cf", str(temporary), "-C", str(source_dir.parent), source_dir.name],
        check=False, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    if result.returncode != 0:
        raise SharedPresentationRepackError(f"cannot create report archive: {result.stderr.strip()}")
    os.replace(temporary, output)


def validate_stage36(evidence: Path, prototype_root: Path) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, str]]]:
    summary = load_json(evidence / "SUMMARY.json")
    if summary.get("type") != "br_quartet_restoration_residual_shared_presentation_prototype_evidence_summary":
        raise SharedPresentationRepackError("stage-36 evidence has an unexpected summary type")
    if summary.get("tool_version") != STAGE36_TOOL_VERSION:
        raise SharedPresentationRepackError(
            f"stage-36 evidence version mismatch: expected {STAGE36_TOOL_VERSION}, got {summary.get('tool_version')}"
        )
    required_counts = {
        "promoted_profile_rows": 1,
        "prototype_file_rows": 2,
        "prototype_validation_rows": 26,
        "validation_failures": 0,
        "skipped_rows": 0,
    }
    for key, expected in required_counts.items():
        if parse_int(summary.get(key), -1) != expected:
            raise SharedPresentationRepackError(
                f"stage-36 {key} mismatch: expected {expected}, got {summary.get(key)}"
            )

    profile_rows = read_tsv(evidence / "RESIDUAL_SHARED_PRESENTATION_PROFILES.tsv")
    file_rows = read_tsv(evidence / "RESIDUAL_SHARED_PRESENTATION_FILES.tsv")
    validation_rows = read_tsv(evidence / "RESIDUAL_SHARED_PRESENTATION_VALIDATION.tsv")
    skipped_rows = read_tsv(evidence / "RESIDUAL_SHARED_PRESENTATION_BUILD_SKIPPED.tsv")
    if len(profile_rows) != 1 or profile_rows[0].get("profile_id") != PROFILE_ID:
        raise SharedPresentationRepackError("stage-36 profile table does not contain the expected single profile")
    if profile_rows[0].get("validation_status") != "passed":
        raise SharedPresentationRepackError("stage-36 profile did not pass metadata validation")
    if len(file_rows) != 2 or {row.get("target_member_path") for row in file_rows} != EXPECTED_TARGET_MEMBERS:
        raise SharedPresentationRepackError("stage-36 file table does not contain the expected two target EBD members")
    if any(row.get("validation_status") != "passed" for row in file_rows):
        raise SharedPresentationRepackError("one or more stage-36 candidate files failed validation")
    if len(validation_rows) != 26 or any(not parse_bool(row.get("passed")) for row in validation_rows):
        raise SharedPresentationRepackError("stage-36 validation table is incomplete or contains a failure")
    if skipped_rows:
        raise SharedPresentationRepackError("stage-36 evidence contains skipped rows")

    if prototype_root.is_symlink() or not prototype_root.is_dir():
        raise SharedPresentationRepackError(f"missing or unsafe stage-36 prototype root: {prototype_root}")
    manifest = load_json(prototype_root / "PROTOTYPE.json")
    if manifest.get("type") != "br_quartet_restoration_local_residual_shared_presentation_prototype":
        raise SharedPresentationRepackError("stage-36 local prototype manifest type mismatch")
    if manifest.get("profile_id") != PROFILE_ID:
        raise SharedPresentationRepackError("stage-36 local prototype profile ID mismatch")
    if manifest.get("tool_version") != STAGE36_TOOL_VERSION:
        raise SharedPresentationRepackError("stage-36 local prototype tool version mismatch")
    if manifest.get("installable_package_generated") is not False or manifest.get("runtime_validated") is not False:
        raise SharedPresentationRepackError("stage-36 local prototype safety flags changed")
    manifest_files = manifest.get("files")
    if not isinstance(manifest_files, list) or len(manifest_files) != 2:
        raise SharedPresentationRepackError("stage-36 local prototype must contain exactly two files")
    by_member = {str(row.get("target_member_path", "")): row for row in file_rows}
    if {str(item.get("target_member_path", "")) for item in manifest_files} != EXPECTED_TARGET_MEMBERS:
        raise SharedPresentationRepackError("stage-36 manifest target-member set changed")
    for item in manifest_files:
        member = str(item.get("target_member_path", ""))
        candidate_rel = safe_relative(str(item.get("candidate_relative_path", "")), label="candidate path")
        candidate = prototype_root / Path(candidate_rel)
        require_within(candidate, prototype_root, label="stage-36 candidate")
        if candidate.is_symlink() or not candidate.is_file():
            raise SharedPresentationRepackError(f"stage-36 candidate is missing or unsafe: {candidate_rel}")
        actual_sha = sha256_file(candidate)
        expected_sha = str(item.get("candidate_sha256", ""))
        report_sha = str(by_member[member].get("candidate_sha256", ""))
        if actual_sha != expected_sha or actual_sha != report_sha:
            raise SharedPresentationRepackError(f"stage-36 candidate checksum mismatch: {member}")
        if str(item.get("target_sha256", "")) != str(by_member[member].get("target_sha256", "")):
            raise SharedPresentationRepackError(f"stage-36 target checksum mismatch: {member}")
    return summary, manifest, file_rows


def replace_tree(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary_old: Path | None = None
    if destination.exists():
        temporary_old = destination.with_name(destination.name + f".old.{os.getpid()}")
        if temporary_old.exists():
            shutil.rmtree(temporary_old)
        os.replace(destination, temporary_old)
    try:
        os.replace(source, destination)
    except Exception:
        if temporary_old is not None and temporary_old.exists() and not destination.exists():
            os.replace(temporary_old, destination)
        raise
    if temporary_old is not None and temporary_old.exists():
        shutil.rmtree(temporary_old)


def rewrite_local_harness(final_root: Path, source_tool_version: object) -> None:
    marker_path = final_root / "HARNESS.json"
    marker = load_json(marker_path)
    marker.update({
        "type": "br_quartet_restoration_local_residual_shared_presentation_repack_test_harness",
        "tool_version": TOOL_VERSION,
        "source_residual_shared_presentation_prototype_tool_version": source_tool_version,
        "successful_profile_ids": [PROFILE_ID],
        "activation_supported": False,
        "installed_game_modified": False,
    })
    marker.pop("source_single_scene_event_prototype_tool_version", None)
    atomic_json(marker_path, marker)

    baseline_path = final_root / "baseline" / "BASELINE.json"
    baseline = load_json(baseline_path)
    baseline.update({
        "type": "br_quartet_restoration_local_residual_shared_presentation_repack_test_baseline",
        "tool_version": TOOL_VERSION,
        "installed_game_modified": False,
    })
    atomic_json(baseline_path, baseline)

    profile_path = final_root / "profiles" / PROFILE_ID / "PROFILE.json"
    profile = load_json(profile_path)
    if parse_int(profile.get("replaced_member_count"), -1) != 2:
        raise SharedPresentationRepackError("local repack profile did not replace exactly two members")
    if {str(row.get("target_member_path", "")) for row in profile.get("files", [])} != EXPECTED_TARGET_MEMBERS:
        raise SharedPresentationRepackError("local repack profile target-member set changed")
    profile.update({
        "type": "br_quartet_restoration_local_residual_shared_presentation_repack_test_profile",
        "tool_version": TOOL_VERSION,
        "source_residual_shared_presentation_prototype_tool_version": source_tool_version,
        "runtime_validated": False,
        "activation_supported": False,
        "installed_game_modified": False,
    })
    atomic_json(profile_path, profile)


def prepare_residual_shared_presentation_repack_test(
    *, project_root: Path, quartet_root: Path, gust_pak: Path,
    workspace_root: Path, report_root: Path, timeout_seconds: int = 300,
) -> tuple[Path, dict[str, Any]]:
    br = load_restoration_tool(project_root)
    if not quartet_root.is_dir():
        raise SharedPresentationRepackError(f"Quartet game root does not exist: {quartet_root}")
    if not gust_pak.is_file() or not os.access(gust_pak, os.X_OK):
        raise SharedPresentationRepackError(f"gust_pak is missing or not executable: {gust_pak}")

    with tempfile.TemporaryDirectory(prefix="br-shared-presentation-repack-") as temp_name:
        temp_root = Path(temp_name)
        evidence = find_stage36_evidence(report_root, temp_root)
        prototype_root = workspace_root / STAGE36_PROTOTYPE_SUBDIR / PROFILE_ID
        stage36_summary, prototype_manifest, stage36_files = validate_stage36(evidence, prototype_root)

        adapter_workspace = workspace_root / f".stage37_adapter.{os.getpid()}"
        adapter_reports = report_root / f".stage37_adapter.{os.getpid()}"
        for adapter in (adapter_workspace, adapter_reports):
            if adapter.exists():
                shutil.rmtree(adapter)
            adapter.mkdir(parents=True)
        try:
            inventory = report_root / "ARCHIVE_INVENTORY.tsv"
            if not inventory.is_file():
                raise SharedPresentationRepackError(f"missing archive inventory: {inventory}")
            shutil.copy2(inventory, adapter_reports / "ARCHIVE_INVENTORY.tsv")

            adapted_evidence = adapter_reports / br.SINGLE_SCENE_EVENT_PROTOTYPE_EVIDENCE_DIR
            adapted_evidence.mkdir(parents=True)
            br.atomic_json(adapted_evidence / "SUMMARY.json", {
                "type": "br_quartet_restoration_single_scene_event_prototype_evidence_summary",
                "format_version": 1,
                "tool_version": STAGE36_TOOL_VERSION,
                "validation_failures": 0,
            })
            br.write_tsv(
                adapted_evidence / "SINGLE_SCENE_EVENT_PROTOTYPE_FILES.tsv",
                ["profile_id"], [],
            )

            adapted_profile = adapter_workspace / br.SINGLE_SCENE_EVENT_PROTOTYPE_BUILD_DIR / PROFILE_ID
            shutil.copytree(prototype_root, adapted_profile, symlinks=False)
            adapted_manifest = dict(prototype_manifest)
            adapted_manifest["type"] = "br_quartet_restoration_local_single_scene_event_prototype"
            adapted_manifest["installable_package_generated"] = False
            adapted_manifest["runtime_validated"] = False
            br.atomic_json(adapted_profile / "PROTOTYPE.json", adapted_manifest)

            _adapter_output, adapter_summary = br.prepare_single_scene_event_repack_tests(
                project_root=project_root,
                quartet_root=quartet_root,
                gust_pak=gust_pak,
                workspace_root=adapter_workspace,
                report_root=adapter_reports,
                timeout_seconds=timeout_seconds,
            )
            if parse_int(adapter_summary.get("profile_rows"), -1) != 1:
                raise SharedPresentationRepackError("repack adapter did not build exactly one profile")
            if parse_int(adapter_summary.get("file_rows"), -1) != 2:
                raise SharedPresentationRepackError("repack adapter did not validate exactly two files")
            if parse_int(adapter_summary.get("validation_failures"), -1) != 0:
                raise SharedPresentationRepackError("repack adapter reported validation failures")
            if parse_int(adapter_summary.get("skipped_rows"), -1) != 0:
                raise SharedPresentationRepackError("repack adapter reported skipped rows")

            adapter_harness = adapter_workspace / br.SINGLE_SCENE_EVENT_REPACK_TEST_BUILD_DIR
            if not adapter_harness.is_dir():
                raise SharedPresentationRepackError("repack adapter did not create its local harness")
            final_root = workspace_root / FINAL_BUILD_SUBDIR
            require_within(final_root, workspace_root, label="stage-37 final harness")
            rewrite_local_harness(adapter_harness, stage36_summary.get("tool_version"))
            replace_tree(adapter_harness, final_root)

            adapter_evidence = adapter_reports / br.SINGLE_SCENE_EVENT_REPACK_TEST_EVIDENCE_DIR
            profile_rows = br.read_tsv(adapter_evidence / "SINGLE_SCENE_EVENT_REPACK_TEST_PROFILES.tsv")
            file_rows = br.read_tsv(adapter_evidence / "SINGLE_SCENE_EVENT_REPACK_TEST_FILES.tsv")
            validation_rows = br.read_tsv(adapter_evidence / "SINGLE_SCENE_EVENT_REPACK_TEST_VALIDATION.tsv")
            manifest_diff_rows = br.read_tsv(adapter_evidence / "SINGLE_SCENE_EVENT_REPACK_TEST_MANIFEST_DIFFERENCES.tsv")
            skipped_rows = br.read_tsv(adapter_evidence / "SINGLE_SCENE_EVENT_REPACK_TEST_BUILD_SKIPPED.tsv")

            if len(profile_rows) != 1 or profile_rows[0].get("profile_id") != PROFILE_ID:
                raise SharedPresentationRepackError("adapter profile report is inconsistent")
            if len(file_rows) != 2 or {row.get("target_member_path") for row in file_rows} != EXPECTED_TARGET_MEMBERS:
                raise SharedPresentationRepackError("adapter file report is inconsistent")
            if skipped_rows:
                raise SharedPresentationRepackError("adapter emitted unexpected skipped rows")

            local_output = final_root / "profiles" / PROFILE_ID / "output" / "Data" / "PACK11.PAK"
            local_rollback = final_root / "baseline" / "Data" / "PACK11.PAK"
            if not local_output.is_file() or not local_rollback.is_file():
                raise SharedPresentationRepackError("local PACK11 output or rollback baseline is missing")
            profile_rows[0]["local_output_archive"] = local_output.relative_to(project_root).as_posix()
            profile_rows[0]["local_rollback_archive"] = local_rollback.relative_to(project_root).as_posix()
            profile_rows[0]["activation_status"] = "not_generated_generic_core_manifest_required"
            profile_rows[0]["source_stage36_profile_id"] = PROFILE_ID

            validation_rows.extend([
                {
                    "profile_id": PROFILE_ID,
                    "check_name": "stage36_profile_count_exactly_one",
                    "passed": True,
                    "details": "count=1",
                },
                {
                    "profile_id": PROFILE_ID,
                    "check_name": "stage36_candidate_file_count_exactly_two",
                    "passed": True,
                    "details": "count=2",
                },
                {
                    "profile_id": PROFILE_ID,
                    "check_name": "stage36_all_26_metadata_gates_passed",
                    "passed": True,
                    "details": "passed=26;failed=0",
                },
                {
                    "profile_id": PROFILE_ID,
                    "check_name": "local_profile_and_rollback_archives_present",
                    "passed": local_output.is_file() and local_rollback.is_file(),
                    "details": "profile=present;rollback=present",
                },
                {
                    "profile_id": PROFILE_ID,
                    "check_name": "installed_pack11_still_matches_repack_input",
                    "passed": sha256_file(quartet_root / "Data" / "PACK11.PAK") == str(adapter_summary.get("input_archive_sha256", "")),
                    "details": "installed_game_read_only=true",
                },
            ])
            validation_rows.sort(key=lambda row: (str(row.get("profile_id", "")), str(row.get("check_name", ""))))

            evidence_root = report_root / EVIDENCE_DIR_NAME
            if evidence_root.exists():
                shutil.rmtree(evidence_root)
            evidence_root.mkdir(parents=True)
            write_tsv(evidence_root / "RESIDUAL_SHARED_PRESENTATION_REPACK_PROFILES.tsv", [
                "profile_id", "profile_classification", "prototype_confidence",
                "source_stage36_profile_id", "input_archive_relative_path", "input_archive_sha256",
                "input_archive_size", "inventory_pristine_archive_match", "baseline_manifest_parse_mode",
                "verification_manifest_parse_mode", "output_archive_sha256", "output_archive_size",
                "replaced_member_count", "unchanged_member_count_verified", "local_output_archive",
                "local_rollback_archive", "validation_status", "activation_status",
            ], profile_rows)
            write_tsv(evidence_root / "RESIDUAL_SHARED_PRESENTATION_REPACK_FILES.tsv", [
                "profile_id", "profile_classification", "prototype_confidence", "normalized_path",
                "target_archive", "target_member_path", "expected_target_sha256", "current_member_sha256",
                "candidate_sha256", "repacked_member_sha256", "validation_status", "review_status",
            ], file_rows)
            write_tsv(evidence_root / "RESIDUAL_SHARED_PRESENTATION_REPACK_VALIDATION.tsv", [
                "profile_id", "check_name", "passed", "details",
            ], validation_rows)
            write_tsv(evidence_root / "RESIDUAL_SHARED_PRESENTATION_REPACK_MANIFEST_DIFFERENCES.tsv", [
                "profile_id", "scope", "field", "member_path", "classification",
                "baseline_value", "verification_value", "baseline_value_sha256",
                "verification_value_sha256", "gate_effect",
            ], manifest_diff_rows)
            write_tsv(evidence_root / "RESIDUAL_SHARED_PRESENTATION_REPACK_BUILD_SKIPPED.tsv", [
                "profile_id", "target_member_path", "reason",
            ], skipped_rows)

            validation_failures = sum(not parse_bool(row.get("passed")) for row in validation_rows)
            summary: dict[str, Any] = {
                "type": "br_quartet_restoration_residual_shared_presentation_repack_test_evidence_summary",
                "format_version": 1,
                "tool_version": TOOL_VERSION,
                "source_residual_shared_presentation_prototype_tool_version": stage36_summary.get("tool_version"),
                "repack_engine_tool_version": adapter_summary.get("tool_version"),
                "status": "one_checksum_gated_local_shared_presentation_pack11_profile_built_reextracted_and_validated_not_installed",
                "profile_rows": len(profile_rows),
                "file_rows": len(file_rows),
                "validation_rows": len(validation_rows),
                "validation_failures": validation_failures,
                "manifest_difference_rows": len(manifest_diff_rows),
                "stable_manifest_difference_rows": parse_int(adapter_summary.get("stable_manifest_difference_rows")),
                "derived_manifest_difference_rows": parse_int(adapter_summary.get("derived_manifest_difference_rows")),
                "skipped_rows": len(skipped_rows),
                "input_archive_relative_path": adapter_summary.get("input_archive_relative_path"),
                "input_archive_sha256": adapter_summary.get("input_archive_sha256"),
                "input_archive_size": adapter_summary.get("input_archive_size"),
                "inventory_pristine_archive_sha256": adapter_summary.get("inventory_pristine_archive_sha256"),
                "inventory_pristine_archive_match": adapter_summary.get("inventory_pristine_archive_match"),
                "gust_pak_sha256": adapter_summary.get("gust_pak_sha256"),
                "baseline_manifest_parse_mode": adapter_summary.get("baseline_manifest_parse_mode"),
                "local_harness_root": final_root.relative_to(project_root).as_posix(),
                "local_profile_archive": local_output.relative_to(project_root).as_posix(),
                "local_rollback_archive": local_rollback.relative_to(project_root).as_posix(),
                "policy": {
                    "installed_game_read_only": True,
                    "installed_game_modified": False,
                    "current_pack11_used_as_repack_base": True,
                    "candidate_members_replaced": 2,
                    "all_unchanged_members_verified_by_reextraction_hash": True,
                    "unrelated_translation_and_other_mod_members_preserved": True,
                    "existing_pack11_profiles_left_untouched": True,
                    "local_rollback_baseline_copied": True,
                    "core_profile_manifest_generated": False,
                    "activation_or_installer_generated": False,
                    "runtime_validation_inferred": False,
                    "censorship_semantics_inferred": False,
                    "proprietary_pak_exported_in_report": False,
                    "legacy_dlc_in_scope": False,
                    "translation_or_core_files_modified": False,
                },
                "next_action": (
                    "Upload this metadata report. If the one profile and every gate pass, generate one generic core "
                    "profile manifest for the local PACK11 archive; do not copy or activate PACK11 manually."
                ),
            }
            atomic_json(evidence_root / "SUMMARY.json", summary)
            output = report_root / REPORT_NAME
            make_report_archive(evidence_root, output)
            return output, summary
        finally:
            shutil.rmtree(adapter_workspace, ignore_errors=True)
            shutil.rmtree(adapter_reports, ignore_errors=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", required=True)
    parser.add_argument("--quartet-root", required=True)
    parser.add_argument("--gust-pak", required=True)
    parser.add_argument("--workspace-root")
    parser.add_argument("--report-root")
    parser.add_argument("--timeout-seconds", type=int, default=300)
    args = parser.parse_args()
    project_root = Path(args.project_root).expanduser().resolve()
    quartet_root = Path(args.quartet_root).expanduser().resolve()
    gust_pak = Path(args.gust_pak).expanduser().resolve()
    if not project_root.is_dir():
        raise SharedPresentationRepackError(f"project root does not exist: {project_root}")
    default_workspace = project_root / ".local/build/quartet_restoration"
    default_reports = project_root / ".local/reports/quartet_restoration"
    workspace_root = Path(args.workspace_root).expanduser().resolve() if args.workspace_root else default_workspace
    report_root = Path(args.report_root).expanduser().resolve() if args.report_root else default_reports
    require_within(workspace_root, default_workspace, label="workspace root")
    require_within(report_root, default_reports, label="report root")
    output, summary = prepare_residual_shared_presentation_repack_test(
        project_root=project_root,
        quartet_root=quartet_root,
        gust_pak=gust_pak,
        workspace_root=workspace_root,
        report_root=report_root,
        timeout_seconds=args.timeout_seconds,
    )
    print(f"Local shared-presentation PACK11 profiles built: {summary['profile_rows']}")
    print(f"Repacked candidate EBD files: {summary['file_rows']}")
    print(f"Validation failures: {summary['validation_failures']}")
    print(f"Installed game modified: {summary['policy']['installed_game_modified']}")
    print(f"Metadata-only report: {output}")
    print(f"Local harness: {summary['local_harness_root']}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SharedPresentationRepackError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
