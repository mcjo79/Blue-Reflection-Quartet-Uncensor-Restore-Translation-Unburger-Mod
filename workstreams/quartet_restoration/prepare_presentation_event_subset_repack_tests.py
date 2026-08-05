#!/usr/bin/env python3
"""Build six separate checksum-gated PACK11 repack tests from the passing stage-45 subset prototypes."""

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
TOOL_VERSION = "0.0.53"
STAGE45_TOOL_VERSION = "0.0.52"
STAGE45_EVIDENCE_DIR = "presentation_event_subset_prototype_evidence"
STAGE45_ARCHIVE = "BR_quartet_restoration_presentation_event_subset_prototype_evidence.tar.zst"
STAGE45_PROTOTYPE_SUBDIR = "prototypes/presentation_event_subset"
FINAL_BUILD_SUBDIR = "repack_tests/presentation_event_subset"
REPORT_NAME = "BR_quartet_restoration_presentation_event_subset_repack_test_evidence.tar.zst"
EVIDENCE_DIR_NAME = "presentation_event_subset_repack_test_evidence"
EXPECTED_PROFILE_MEMBERS = {
    "candidate_subset_ce07_060_1cddf6cac60969c4": "event/b1/event_jp/ce07/event_ce07_060.ebd",
    "candidate_subset_ce11_010_abc7939e4ff69ead": "event/b1/event_jp/ce11/event_ce11_010.ebd",
    "candidate_subset_em01_060_43f9052741640b35": "event/b1/event_jp/em01/event_em01_060.ebd",
    "candidate_subset_em02_030_552c84999f656afb": "event/b1/event_jp/em02/event_em02_030.ebd",
    "candidate_subset_te01_270_f6e3b892ac7ba1b9": "event/b1/event_jp/te01/event_te01_270.ebd",
    "candidate_subset_xf07_030_d85e6afc33b5802b": "event/b1/event_jp/xf07/event_xf07_030.ebd",
}


class PresentationSubsetRepackError(RuntimeError):
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


def load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise PresentationSubsetRepackError(f"missing JSON: {path}") from exc
    except json.JSONDecodeError as exc:
        raise PresentationSubsetRepackError(f"invalid JSON {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise PresentationSubsetRepackError(f"JSON root is not an object: {path}")
    return value


def safe_relative(raw: str, *, label: str) -> str:
    path = PurePosixPath(raw)
    if path.is_absolute() or not path.parts or ".." in path.parts or "." in path.parts:
        raise PresentationSubsetRepackError(f"unsafe {label}: {raw}")
    canonical = path.as_posix()
    if canonical != raw:
        raise PresentationSubsetRepackError(f"non-canonical {label}: {raw}")
    return canonical


def require_within(path: Path, root: Path, *, label: str) -> None:
    try:
        path.resolve().relative_to(root.resolve())
    except ValueError as exc:
        raise PresentationSubsetRepackError(f"{label} escapes allowed root: {path}") from exc


def safe_archive_member(raw: str) -> str:
    path = PurePosixPath(raw)
    if path.is_absolute() or not path.parts or ".." in path.parts:
        raise PresentationSubsetRepackError(f"unsafe report archive member: {raw}")
    return path.as_posix()


def extract_report(archive: Path, destination: Path) -> None:
    if not archive.is_file():
        raise PresentationSubsetRepackError(f"missing prerequisite report: {archive}")
    listing = subprocess.run(
        ["tar", "--zstd", "-tf", str(archive)], check=False, text=True,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    if listing.returncode != 0:
        raise PresentationSubsetRepackError(f"cannot list report {archive}: {listing.stderr.strip()}")
    for line in listing.stdout.splitlines():
        if line.strip():
            safe_archive_member(line.strip())
    destination.mkdir(parents=True, exist_ok=True)
    result = subprocess.run(
        ["tar", "--zstd", "-xf", str(archive), "-C", str(destination)], check=False,
        text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    if result.returncode != 0:
        raise PresentationSubsetRepackError(f"cannot extract report {archive}: {result.stderr.strip()}")


def find_stage45_evidence(report_root: Path, temporary_root: Path) -> Path:
    direct = report_root / STAGE45_EVIDENCE_DIR
    if direct.is_dir():
        return direct
    extraction = temporary_root / "stage45_report"
    extract_report(report_root / STAGE45_ARCHIVE, extraction)
    matches = [path for path in extraction.rglob(STAGE45_EVIDENCE_DIR) if path.is_dir()]
    if len(matches) != 1:
        raise PresentationSubsetRepackError(
            f"expected one {STAGE45_EVIDENCE_DIR} directory, found {len(matches)}"
        )
    return matches[0]


def load_restoration_tool(project_root: Path) -> Any:
    tool_root = project_root / "Blue_Reflection_Text_Tool"
    tool_path = tool_root / "br_restoration_tool.py"
    if not tool_path.is_file():
        raise PresentationSubsetRepackError(f"missing restoration tool: {tool_path}")
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
        raise PresentationSubsetRepackError(f"cannot create report archive: {result.stderr.strip()}")
    os.replace(temporary, output)


def validate_stage45(
    evidence: Path, prototype_base: Path,
) -> tuple[dict[str, Any], dict[str, dict[str, Any]], list[dict[str, str]], dict[str, int]]:
    summary = load_json(evidence / "SUMMARY.json")
    if summary.get("type") != "br_quartet_restoration_presentation_event_subset_prototype_evidence_summary":
        raise PresentationSubsetRepackError("stage-45 evidence has an unexpected summary type")
    if summary.get("tool_version") != STAGE45_TOOL_VERSION:
        raise PresentationSubsetRepackError(
            f"stage-45 evidence version mismatch: expected {STAGE45_TOOL_VERSION}, got {summary.get('tool_version')}"
        )
    required_counts = {
        "proposed_profile_rows": 6,
        "promoted_profile_rows": 6,
        "prototype_file_rows": 6,
        "selected_occurrence_rows": 21,
        "remaining_residual_rows": 115,
        "validation_rows": 168,
        "validation_failures": 0,
        "skipped_rows": 0,
    }
    for key, expected in required_counts.items():
        if parse_int(summary.get(key), -1) != expected:
            raise PresentationSubsetRepackError(
                f"stage-45 {key} mismatch: expected {expected}, got {summary.get(key)}"
            )
    if not parse_bool(summary.get("runtime_testing_deferred")):
        raise PresentationSubsetRepackError("stage-45 report no longer defers runtime testing")

    profile_rows = read_tsv(evidence / "PRESENTATION_EVENT_SUBSET_PROFILES.tsv")
    file_rows = read_tsv(evidence / "PRESENTATION_EVENT_SUBSET_FILES.tsv")
    validation_rows = read_tsv(evidence / "PRESENTATION_EVENT_SUBSET_VALIDATION.tsv")
    skipped_rows = read_tsv(evidence / "PRESENTATION_EVENT_SUBSET_BUILD_SKIPPED.tsv")
    expected_ids = set(EXPECTED_PROFILE_MEMBERS)
    if {row.get("profile_id", "") for row in profile_rows} != expected_ids or len(profile_rows) != 6:
        raise PresentationSubsetRepackError("stage-45 profile set changed")
    if any(row.get("validation_status") != "passed" for row in profile_rows):
        raise PresentationSubsetRepackError("one or more stage-45 profiles did not pass")
    if any(parse_bool(row.get("runtime_validated")) for row in profile_rows):
        raise PresentationSubsetRepackError("stage-45 unexpectedly claims runtime validation")
    if len(file_rows) != 6 or {row.get("profile_id", "") for row in file_rows} != expected_ids:
        raise PresentationSubsetRepackError("stage-45 file table changed")
    by_profile = {row["profile_id"]: row for row in file_rows}
    for profile_id, member in EXPECTED_PROFILE_MEMBERS.items():
        row = by_profile[profile_id]
        if row.get("target_member_path") != member or row.get("validation_status") != "passed":
            raise PresentationSubsetRepackError(f"stage-45 file row changed: {profile_id}")
    if len(validation_rows) != 168 or any(not parse_bool(row.get("passed")) for row in validation_rows):
        raise PresentationSubsetRepackError("stage-45 validation table must contain 168 successful gates")
    validation_counts: dict[str, int] = {}
    for profile_id in expected_ids:
        count = sum(row.get("profile_id") == profile_id for row in validation_rows)
        if count != 28:
            raise PresentationSubsetRepackError(
                f"stage-45 profile must have exactly 28 successful gates: {profile_id} has {count}"
            )
        validation_counts[profile_id] = count
    if skipped_rows:
        raise PresentationSubsetRepackError("stage-45 contains unexpected skipped profiles")

    manifests: dict[str, dict[str, Any]] = {}
    for profile_id, expected_member in EXPECTED_PROFILE_MEMBERS.items():
        profile_root = prototype_base / profile_id
        if profile_root.is_symlink() or not profile_root.is_dir():
            raise PresentationSubsetRepackError(f"missing or unsafe stage-45 prototype root: {profile_id}")
        manifest = load_json(profile_root / "PROTOTYPE.json")
        if manifest.get("type") != "br_quartet_restoration_local_presentation_event_subset_prototype":
            raise PresentationSubsetRepackError(f"stage-45 prototype type mismatch: {profile_id}")
        if manifest.get("profile_id") != profile_id or manifest.get("tool_version") != STAGE45_TOOL_VERSION:
            raise PresentationSubsetRepackError(f"stage-45 prototype identity mismatch: {profile_id}")
        if manifest.get("installable_package_generated") is not False or manifest.get("runtime_validated") is not False:
            raise PresentationSubsetRepackError(f"stage-45 prototype safety flags changed: {profile_id}")
        files = manifest.get("files")
        if not isinstance(files, list) or len(files) != 1:
            raise PresentationSubsetRepackError(f"stage-45 prototype must contain one file: {profile_id}")
        item = files[0]
        if str(item.get("target_member_path", "")) != expected_member:
            raise PresentationSubsetRepackError(f"stage-45 prototype member changed: {profile_id}")
        candidate_rel = safe_relative(str(item.get("candidate_relative_path", "")), label="candidate path")
        candidate = profile_root / Path(candidate_rel)
        require_within(candidate, profile_root, label="stage-45 candidate")
        if candidate.is_symlink() or not candidate.is_file():
            raise PresentationSubsetRepackError(f"stage-45 candidate is missing or unsafe: {profile_id}")
        report_row = by_profile[profile_id]
        actual_sha = sha256_file(candidate)
        if actual_sha != str(item.get("candidate_sha256", "")) or actual_sha != str(report_row.get("candidate_sha256", "")):
            raise PresentationSubsetRepackError(f"stage-45 candidate checksum mismatch: {profile_id}")
        if str(item.get("target_sha256", "")) != str(report_row.get("target_sha256", "")):
            raise PresentationSubsetRepackError(f"stage-45 target checksum mismatch: {profile_id}")
        manifests[profile_id] = manifest
    return summary, manifests, file_rows, validation_counts


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
    successful_ids = sorted(EXPECTED_PROFILE_MEMBERS, key=str.casefold)
    marker_path = final_root / "HARNESS.json"
    marker = load_json(marker_path)
    marker.update({
        "type": "br_quartet_restoration_local_presentation_event_subset_repack_test_harness",
        "tool_version": TOOL_VERSION,
        "source_presentation_event_subset_prototype_tool_version": source_tool_version,
        "successful_profile_ids": successful_ids,
        "activation_supported": False,
        "installed_game_modified": False,
    })
    marker.pop("source_single_scene_event_prototype_tool_version", None)
    atomic_json(marker_path, marker)

    baseline_path = final_root / "baseline" / "BASELINE.json"
    baseline = load_json(baseline_path)
    baseline.update({
        "type": "br_quartet_restoration_local_presentation_event_subset_repack_test_baseline",
        "tool_version": TOOL_VERSION,
        "installed_game_modified": False,
    })
    atomic_json(baseline_path, baseline)

    for profile_id, expected_member in EXPECTED_PROFILE_MEMBERS.items():
        profile_path = final_root / "profiles" / profile_id / "PROFILE.json"
        profile = load_json(profile_path)
        if parse_int(profile.get("replaced_member_count"), -1) != 1:
            raise PresentationSubsetRepackError(f"local repack profile did not replace exactly one member: {profile_id}")
        files = profile.get("files")
        if not isinstance(files, list) or {str(row.get("target_member_path", "")) for row in files} != {expected_member}:
            raise PresentationSubsetRepackError(f"local repack profile target-member set changed: {profile_id}")
        profile.update({
            "type": "br_quartet_restoration_local_presentation_event_subset_repack_test_profile",
            "tool_version": TOOL_VERSION,
            "source_presentation_event_subset_prototype_tool_version": source_tool_version,
            "runtime_validated": False,
            "activation_supported": False,
            "installed_game_modified": False,
        })
        atomic_json(profile_path, profile)


def prepare_presentation_event_subset_repack_tests(
    *, project_root: Path, quartet_root: Path, gust_pak: Path,
    workspace_root: Path, report_root: Path, timeout_seconds: int = 300,
) -> tuple[Path, dict[str, Any]]:
    br = load_restoration_tool(project_root)
    if not quartet_root.is_dir():
        raise PresentationSubsetRepackError(f"Quartet game root does not exist: {quartet_root}")
    if not gust_pak.is_file() or not os.access(gust_pak, os.X_OK):
        raise PresentationSubsetRepackError(f"gust_pak is missing or not executable: {gust_pak}")

    with tempfile.TemporaryDirectory(prefix="br-presentation-subset-repack-") as temp_name:
        temp_root = Path(temp_name)
        evidence = find_stage45_evidence(report_root, temp_root)
        prototype_base = workspace_root / STAGE45_PROTOTYPE_SUBDIR
        stage45_summary, prototype_manifests, stage45_files, validation_counts = validate_stage45(
            evidence, prototype_base,
        )

        adapter_workspace = workspace_root / f".stage46_adapter.{os.getpid()}"
        adapter_reports = report_root / f".stage46_adapter.{os.getpid()}"
        for adapter in (adapter_workspace, adapter_reports):
            if adapter.exists():
                shutil.rmtree(adapter)
            adapter.mkdir(parents=True)
        try:
            inventory = report_root / "ARCHIVE_INVENTORY.tsv"
            if not inventory.is_file():
                raise PresentationSubsetRepackError(f"missing archive inventory: {inventory}")
            shutil.copy2(inventory, adapter_reports / "ARCHIVE_INVENTORY.tsv")

            adapted_evidence = adapter_reports / br.SINGLE_SCENE_EVENT_PROTOTYPE_EVIDENCE_DIR
            adapted_evidence.mkdir(parents=True)
            br.atomic_json(adapted_evidence / "SUMMARY.json", {
                "type": "br_quartet_restoration_single_scene_event_prototype_evidence_summary",
                "format_version": 1,
                "tool_version": STAGE45_TOOL_VERSION,
                "validation_failures": 0,
            })
            br.write_tsv(adapted_evidence / "SINGLE_SCENE_EVENT_PROTOTYPE_FILES.tsv", ["profile_id"], [])

            for profile_id, manifest in prototype_manifests.items():
                source_root = prototype_base / profile_id
                adapted_profile = adapter_workspace / br.SINGLE_SCENE_EVENT_PROTOTYPE_BUILD_DIR / profile_id
                shutil.copytree(source_root, adapted_profile, symlinks=False)
                adapted_manifest = dict(manifest)
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
            for key, expected in {"profile_rows": 6, "file_rows": 6, "validation_failures": 0, "skipped_rows": 0}.items():
                if parse_int(adapter_summary.get(key), -1) != expected:
                    raise PresentationSubsetRepackError(
                        f"repack adapter {key} mismatch: expected {expected}, got {adapter_summary.get(key)}"
                    )

            adapter_harness = adapter_workspace / br.SINGLE_SCENE_EVENT_REPACK_TEST_BUILD_DIR
            if not adapter_harness.is_dir():
                raise PresentationSubsetRepackError("repack adapter did not create its local harness")
            final_root = workspace_root / FINAL_BUILD_SUBDIR
            require_within(final_root, workspace_root, label="stage-46 final harness")
            rewrite_local_harness(adapter_harness, stage45_summary.get("tool_version"))
            replace_tree(adapter_harness, final_root)

            adapter_evidence = adapter_reports / br.SINGLE_SCENE_EVENT_REPACK_TEST_EVIDENCE_DIR
            profile_rows = br.read_tsv(adapter_evidence / "SINGLE_SCENE_EVENT_REPACK_TEST_PROFILES.tsv")
            file_rows = br.read_tsv(adapter_evidence / "SINGLE_SCENE_EVENT_REPACK_TEST_FILES.tsv")
            validation_rows = br.read_tsv(adapter_evidence / "SINGLE_SCENE_EVENT_REPACK_TEST_VALIDATION.tsv")
            manifest_diff_rows = br.read_tsv(adapter_evidence / "SINGLE_SCENE_EVENT_REPACK_TEST_MANIFEST_DIFFERENCES.tsv")
            skipped_rows = br.read_tsv(adapter_evidence / "SINGLE_SCENE_EVENT_REPACK_TEST_BUILD_SKIPPED.tsv")
            if {row.get("profile_id", "") for row in profile_rows} != set(EXPECTED_PROFILE_MEMBERS) or len(profile_rows) != 6:
                raise PresentationSubsetRepackError("adapter profile report is inconsistent")
            if {row.get("profile_id", "") for row in file_rows} != set(EXPECTED_PROFILE_MEMBERS) or len(file_rows) != 6:
                raise PresentationSubsetRepackError("adapter file report is inconsistent")
            if skipped_rows:
                raise PresentationSubsetRepackError("adapter emitted unexpected skipped rows")

            stage45_by_profile = {row["profile_id"]: row for row in stage45_files}
            for profile in profile_rows:
                profile_id = str(profile.get("profile_id", ""))
                local_output = final_root / "profiles" / profile_id / "output" / "Data" / "PACK11.PAK"
                local_rollback = final_root / "baseline" / "Data" / "PACK11.PAK"
                if not local_output.is_file() or not local_rollback.is_file():
                    raise PresentationSubsetRepackError(f"local PACK11 output or rollback baseline is missing: {profile_id}")
                profile["local_output_archive"] = local_output.relative_to(project_root).as_posix()
                profile["local_rollback_archive"] = local_rollback.relative_to(project_root).as_posix()
                profile["activation_status"] = "not_generated_generic_core_manifest_required"
                profile["source_stage45_profile_id"] = profile_id
                profile["distance_improvement"] = stage45_by_profile[profile_id].get("distance_improvement", "")

                validation_rows.extend([
                    {"profile_id": profile_id, "check_name": "stage45_profile_set_exactly_six", "passed": True, "details": "count=6"},
                    {"profile_id": profile_id, "check_name": "stage45_candidate_file_count_exactly_one_for_profile", "passed": True, "details": "count=1"},
                    {"profile_id": profile_id, "check_name": "stage45_profile_all_metadata_gates_passed", "passed": True, "details": f"passed={validation_counts[profile_id]};failed=0"},
                    {"profile_id": profile_id, "check_name": "local_profile_and_rollback_archives_present", "passed": True, "details": "profile=present;rollback=present"},
                    {"profile_id": profile_id, "check_name": "installed_pack11_still_matches_repack_input", "passed": sha256_file(quartet_root / "Data" / "PACK11.PAK") == str(adapter_summary.get("input_archive_sha256", "")), "details": "installed_game_read_only=true"},
                ])
            validation_rows.sort(key=lambda row: (str(row.get("profile_id", "")), str(row.get("check_name", ""))))

            evidence_root = report_root / EVIDENCE_DIR_NAME
            if evidence_root.exists():
                shutil.rmtree(evidence_root)
            evidence_root.mkdir(parents=True)
            write_tsv(evidence_root / "PRESENTATION_EVENT_SUBSET_REPACK_PROFILES.tsv", [
                "profile_id", "profile_classification", "prototype_confidence", "source_stage45_profile_id",
                "distance_improvement", "input_archive_relative_path", "input_archive_sha256", "input_archive_size",
                "inventory_pristine_archive_match", "baseline_manifest_parse_mode", "verification_manifest_parse_mode",
                "output_archive_sha256", "output_archive_size", "replaced_member_count", "unchanged_member_count_verified",
                "local_output_archive", "local_rollback_archive", "validation_status", "activation_status",
            ], profile_rows)
            write_tsv(evidence_root / "PRESENTATION_EVENT_SUBSET_REPACK_FILES.tsv", [
                "profile_id", "profile_classification", "prototype_confidence", "normalized_path", "target_archive",
                "target_member_path", "expected_target_sha256", "current_member_sha256", "candidate_sha256",
                "repacked_member_sha256", "validation_status", "review_status",
            ], file_rows)
            write_tsv(evidence_root / "PRESENTATION_EVENT_SUBSET_REPACK_VALIDATION.tsv", [
                "profile_id", "check_name", "passed", "details",
            ], validation_rows)
            write_tsv(evidence_root / "PRESENTATION_EVENT_SUBSET_REPACK_MANIFEST_DIFFERENCES.tsv", [
                "profile_id", "scope", "field", "member_path", "classification", "baseline_value",
                "verification_value", "baseline_value_sha256", "verification_value_sha256", "gate_effect",
            ], manifest_diff_rows)
            write_tsv(evidence_root / "PRESENTATION_EVENT_SUBSET_REPACK_BUILD_SKIPPED.tsv", [
                "profile_id", "target_member_path", "reason",
            ], skipped_rows)

            validation_failures = sum(not parse_bool(row.get("passed")) for row in validation_rows)
            local_archives = {
                row["profile_id"]: row.get("local_output_archive", "") for row in profile_rows
            }
            summary: dict[str, Any] = {
                "type": "br_quartet_restoration_presentation_event_subset_repack_test_evidence_summary",
                "format_version": 1,
                "tool_version": TOOL_VERSION,
                "source_presentation_event_subset_prototype_tool_version": stage45_summary.get("tool_version"),
                "repack_engine_tool_version": adapter_summary.get("tool_version"),
                "status": "six_separate_checksum_gated_local_presentation_event_subset_pack11_profiles_built_reextracted_and_validated_not_installed",
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
                "local_profile_archives": local_archives,
                "policy": {
                    "installed_game_read_only": True,
                    "installed_game_modified": False,
                    "current_pack11_used_as_repack_base": True,
                    "candidate_members_replaced_per_profile": 1,
                    "profile_archives_kept_separate": True,
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
                    "Upload this metadata report. If all six separate profiles and every gate pass, register six additional "
                    "inactive generic core profile manifests bound to their local PACK11 archives. Do not combine, copy or activate them manually."
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
        raise PresentationSubsetRepackError(f"project root does not exist: {project_root}")
    default_workspace = project_root / ".local/build/quartet_restoration"
    default_reports = project_root / ".local/reports/quartet_restoration"
    workspace_root = Path(args.workspace_root).expanduser().resolve() if args.workspace_root else default_workspace
    report_root = Path(args.report_root).expanduser().resolve() if args.report_root else default_reports
    require_within(workspace_root, default_workspace, label="workspace root")
    require_within(report_root, default_reports, label="report root")
    output, summary = prepare_presentation_event_subset_repack_tests(
        project_root=project_root,
        quartet_root=quartet_root,
        gust_pak=gust_pak,
        workspace_root=workspace_root,
        report_root=report_root,
        timeout_seconds=args.timeout_seconds,
    )
    print(f"Local presentation-subset PACK11 profiles built: {summary['profile_rows']}")
    print(f"Repacked presentation-subset EBD files: {summary['file_rows']}")
    print(f"Validation failures: {summary['validation_failures']}")
    print(f"Installed game modified: {summary['policy']['installed_game_modified']}")
    print(f"Metadata-only report: {output}")
    print(f"Local harness: {summary['local_harness_root']}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except PresentationSubsetRepackError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
