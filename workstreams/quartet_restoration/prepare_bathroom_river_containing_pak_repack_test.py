#!/usr/bin/env python3
"""Build and verify one local containing-PAK repack for the bathroom river parent.

Stage 70 produced a verified local candidate for one Quartet Elixir container.
This stage resolves the exact containing PAK from the canonical target inventory,
uses the currently installed archive as a read-only base, replaces exactly that
one Elixir member, repacks and re-extracts the result, and verifies every other
PAK member. It writes only a local candidate archive and rollback copy. It does
not modify registry state, activate a profile, or write to an installed game.
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
TEXT_TOOL_DIR = PROJECT_ROOT_DEFAULT / "Blue_Reflection_Text_Tool"
for import_path in (SCRIPT_DIR, TEXT_TOOL_DIR):
    if str(import_path) not in sys.path:
        sys.path.insert(0, str(import_path))

import br_restoration_tool as BR  # noqa: E402
import prepare_bathroom_river_parent_elixir_repack_test as STAGE70  # noqa: E402

TOOL_VERSION = "0.0.81"
EXPECTED_STAGE70_TOOL_VERSION = "0.0.80"
REPORT_NAME = "BR_quartet_restoration_bathroom_river_containing_pak_repack_test_evidence.tar.zst"
EVIDENCE_DIR_NAME = "bathroom_river_containing_pak_repack_test_evidence"
STAGE70_DIR = STAGE70.EVIDENCE_DIR_NAME
STAGE70_ARCHIVE = STAGE70.REPORT_NAME
INVENTORY_ARCHIVE = "BR_quartet_restoration_inventory_and_diff.tar.zst"
PROFILE_ID = "candidate_bathroom_river_containing_pak_static_inverse_062e39915e7d"
SOURCE_PROFILE_ID = STAGE70.PROFILE_ID
PARENT_PATH = STAGE70.PARENT_PATH
EXPECTED_TARGET_PARENT_SHA256 = "6d9aaf32b7eebd9e927b1b4e6e5521b9696d75738ba55499f3c64fcee0d76af8"
EXPECTED_SELECTED_MEMBER_SHA256 = STAGE70.EXPECTED_CANDIDATE_SHA256
REPACK_SUBDIR = Path("repack_tests/bathroom_river_containing_pak")


class BathroomRiverContainingPakError(RuntimeError):
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


def read_tsv(path: Path, *, required: bool = True) -> list[dict[str, str]]:
    if not path.is_file():
        if required:
            raise BathroomRiverContainingPakError(f"missing prerequisite table: {path}")
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
        raise BathroomRiverContainingPakError(f"missing JSON: {path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise BathroomRiverContainingPakError(f"invalid JSON {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise BathroomRiverContainingPakError(f"expected JSON object: {path}")
    return value


def atomic_json(path: Path, value: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + f".tmp.{os.getpid()}")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def safe_posix(raw: str, *, label: str) -> str:
    normalized = raw.replace("\\", "/")
    path = PurePosixPath(normalized)
    if path.is_absolute() or not path.parts or ".." in path.parts or "." in path.parts:
        raise BathroomRiverContainingPakError(f"unsafe {label}: {raw}")
    return path.as_posix()


def require_within(path: Path, root: Path, *, label: str) -> None:
    try:
        path.resolve().relative_to(root.resolve())
    except ValueError as exc:
        raise BathroomRiverContainingPakError(f"{label} escapes allowed root: {path}") from exc


def safe_archive_member(raw: str) -> str:
    path = PurePosixPath(raw)
    if path.is_absolute() or not path.parts or ".." in path.parts:
        raise BathroomRiverContainingPakError(f"unsafe report archive member: {raw}")
    return path.as_posix()


def extract_archive(archive: Path, destination: Path) -> Path:
    if not archive.is_file():
        raise BathroomRiverContainingPakError(f"missing prerequisite archive: {archive}")
    listed = subprocess.run(
        ["tar", "--zstd", "-tf", str(archive)], text=True,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False,
    )
    if listed.returncode:
        raise BathroomRiverContainingPakError(f"cannot list {archive}: {listed.stderr.strip()}")
    roots = {
        PurePosixPath(safe_archive_member(line.strip())).parts[0]
        for line in listed.stdout.splitlines() if line.strip()
    }
    if len(roots) != 1:
        raise BathroomRiverContainingPakError(
            f"expected one report root in {archive}, found {sorted(roots)}"
        )
    destination.mkdir(parents=True, exist_ok=True)
    done = subprocess.run(
        ["tar", "--zstd", "-xf", str(archive), "-C", str(destination)], text=True,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False,
    )
    if done.returncode:
        raise BathroomRiverContainingPakError(f"cannot extract {archive}: {done.stderr.strip()}")
    return destination / next(iter(roots))


def locate_report_root(
    report_root: Path, directory_name: str, archive_name: str, temporary: Path
) -> Path:
    direct = report_root / directory_name
    if direct.is_dir():
        return direct
    return extract_archive(report_root / archive_name, temporary)


def make_report_archive(source_dir: Path, output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(output.name + ".tmp")
    temporary.unlink(missing_ok=True)
    done = subprocess.run(
        ["tar", "--zstd", "-cf", str(temporary), "-C", str(source_dir.parent), source_dir.name],
        text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False,
    )
    if done.returncode:
        raise BathroomRiverContainingPakError(f"cannot create report archive: {done.stderr.strip()}")
    os.replace(temporary, output)


def validate_stage70(root: Path) -> tuple[dict[str, Any], dict[str, str], dict[str, str]]:
    summary = load_json(root / "SUMMARY.json")
    if summary.get("type") != "br_quartet_restoration_bathroom_river_parent_elixir_repack_test_evidence_summary":
        raise BathroomRiverContainingPakError("stage-70 report has an unexpected summary type")
    if summary.get("tool_version") != EXPECTED_STAGE70_TOOL_VERSION:
        raise BathroomRiverContainingPakError("stage-70 report must use tool version 0.0.80")
    if summary.get("status") != "bathroom_river_parent_elixir_local_repack_verified_not_pak_repacked_or_installed":
        raise BathroomRiverContainingPakError("stage-70 report is not complete")
    expected = {
        "proposed_profile_rows": 1,
        "repacked_profile_rows": 1,
        "parent_file_rows": 1,
        "member_rows": 15,
        "changed_member_rows": 1,
        "unchanged_member_rows": 14,
        "validation_rows": 25,
        "validation_failures": 0,
        "skipped_rows": 0,
        "decoded_parent_distance": 22,
    }
    for field, expected_value in expected.items():
        if parse_int(summary.get(field), -1) != expected_value:
            raise BathroomRiverContainingPakError(
                f"stage-70 {field} must be {expected_value}, got {summary.get(field)}"
            )
    if summary.get("container_kind") not in {"gzip", "gust_chunked_zlib"}:
        raise BathroomRiverContainingPakError("stage-70 container kind is unsupported")
    if summary.get("selected_member_key") != STAGE70.MEMBER_KEY:
        raise BathroomRiverContainingPakError("stage-70 selected member changed")
    if summary.get("selected_member_candidate_sha256") != EXPECTED_SELECTED_MEMBER_SHA256:
        raise BathroomRiverContainingPakError("stage-70 selected-member hash changed")
    if summary.get("target_parent_sha256") != EXPECTED_TARGET_PARENT_SHA256:
        raise BathroomRiverContainingPakError("stage-70 target-parent hash changed")
    candidate_parent_sha = str(summary.get("candidate_parent_sha256", ""))
    if len(candidate_parent_sha) != 64:
        raise BathroomRiverContainingPakError("stage-70 candidate-parent hash is missing")
    policy = summary.get("policy") or {}
    if not isinstance(policy, dict):
        raise BathroomRiverContainingPakError("stage-70 policy is malformed")
    forbidden_true = (
        "installed_games_modified", "candidate_parent_payload_exported_in_report",
        "selected_member_payload_exported_in_report", "pak_repack_performed",
        "core_registry_modified", "activation_or_rollback_invoked",
        "runtime_validation_inferred", "censorship_classification_inferred",
        "opaque_binary_field_semantics_inferred", "opl2_payload_modified",
        "translation_or_dlc_workstreams_modified",
    )
    for field in forbidden_true:
        if parse_bool(policy.get(field)):
            raise BathroomRiverContainingPakError(f"stage-70 policy field {field} must be false")
    for field in (
        "candidate_parent_written_only_under_local_workspace",
        "rollback_parent_written_only_under_local_workspace",
    ):
        if not parse_bool(policy.get(field)):
            raise BathroomRiverContainingPakError(f"stage-70 policy field {field} must be true")

    profiles = read_tsv(root / "BATHROOM_RIVER_PARENT_ELIXIR_REPACK_PROFILES.tsv")
    files = read_tsv(root / "BATHROOM_RIVER_PARENT_ELIXIR_REPACK_FILES.tsv")
    validations = read_tsv(root / "BATHROOM_RIVER_PARENT_ELIXIR_REPACK_VALIDATIONS.tsv")
    skipped = read_tsv(root / "BATHROOM_RIVER_PARENT_ELIXIR_REPACK_SKIPPED.tsv")
    if len(profiles) != 1 or len(files) != 1 or len(validations) != 25 or skipped:
        raise BathroomRiverContainingPakError("stage-70 report row counts changed")
    if any(not parse_bool(row.get("passed")) for row in validations):
        raise BathroomRiverContainingPakError("stage-70 contains a failed validation")
    profile = profiles[0]
    file_row = files[0]
    checks = {
        "profile_id": profile.get("profile_id") == SOURCE_PROFILE_ID,
        "source_profile_id": profile.get("source_profile_id") == STAGE70.SOURCE_PROFILE_ID,
        "parent_container": profile.get("parent_container") == PARENT_PATH,
        "selected_member_key": profile.get("selected_member_key") == STAGE70.MEMBER_KEY,
        "changed_member_count": parse_int(profile.get("changed_member_count"), -1) == 1,
        "unchanged_member_count": parse_int(profile.get("unchanged_member_count"), -1) == 14,
        "target_parent_sha256": profile.get("target_parent_sha256") == EXPECTED_TARGET_PARENT_SHA256,
        "candidate_parent_sha256": profile.get("candidate_parent_sha256") == candidate_parent_sha,
        "rollback_parent_sha256": profile.get("rollback_parent_sha256") == EXPECTED_TARGET_PARENT_SHA256,
        "validation_status": profile.get("validation_status") == "passed",
        "runtime_unvalidated": not parse_bool(profile.get("runtime_validated")),
        "file_target_hash": file_row.get("target_parent_sha256") == EXPECTED_TARGET_PARENT_SHA256,
        "file_candidate_hash": file_row.get("candidate_parent_sha256") == candidate_parent_sha,
        "file_decoded_distance": parse_int(file_row.get("decoded_distance"), -1) == 22,
    }
    failed = [name for name, passed in checks.items() if not passed]
    if failed:
        raise BathroomRiverContainingPakError("stage-70 canonical rows changed: " + ", ".join(failed))
    return summary, profile, file_row


def resolve_stage70_candidate(
    project_root: Path, workspace_root: Path, profile_row: Mapping[str, str]
) -> tuple[Path, dict[str, Any]]:
    root_path = Path(str(profile_row.get("local_profile_root", "")))
    if not root_path.is_absolute():
        root_path = project_root / root_path
    root_path = root_path.resolve()
    require_within(root_path, workspace_root, label="stage-70 local profile")
    manifest = load_json(root_path / "REPACK_TEST.json")
    if manifest.get("type") != "br_quartet_restoration_local_parent_elixir_repack_test":
        raise BathroomRiverContainingPakError("stage-70 local manifest type changed")
    if manifest.get("tool_version") != EXPECTED_STAGE70_TOOL_VERSION:
        raise BathroomRiverContainingPakError("stage-70 local manifest version changed")
    checks = {
        "profile_id": manifest.get("profile_id") == SOURCE_PROFILE_ID,
        "parent_container": manifest.get("parent_container") == PARENT_PATH,
        "changed_member_count": parse_int(manifest.get("changed_member_count"), -1) == 1,
        "target_parent_sha256": manifest.get("target_parent_sha256") == EXPECTED_TARGET_PARENT_SHA256,
        "candidate_parent_sha256": manifest.get("candidate_parent_sha256") == profile_row.get("candidate_parent_sha256"),
        "pak_not_repacked": not parse_bool(manifest.get("pak_repacked")),
        "registry_unmodified": not parse_bool(manifest.get("core_registry_modified")),
        "game_unmodified": not parse_bool(manifest.get("installed_game_modified")),
        "runtime_unvalidated": not parse_bool(manifest.get("runtime_validated")),
        "semantics_unassigned": not parse_bool(manifest.get("semantics_assigned")),
    }
    failed = [name for name, passed in checks.items() if not passed]
    if failed:
        raise BathroomRiverContainingPakError("stage-70 local manifest changed: " + ", ".join(failed))
    relative = safe_posix(str(manifest.get("candidate_relative_path", "")), label="candidate parent path")
    candidate = (root_path / Path(relative)).resolve()
    require_within(candidate, root_path, label="stage-70 candidate parent")
    if not candidate.is_file():
        raise BathroomRiverContainingPakError("stage-70 candidate parent is missing")
    if sha256_file(candidate) != str(manifest.get("candidate_parent_sha256", "")):
        raise BathroomRiverContainingPakError("stage-70 candidate parent hash mismatch")
    return candidate, manifest


def locate_inventory_root(report_root: Path, temporary: Path) -> Path:
    direct = report_root / "inventories"
    if direct.is_dir():
        return report_root
    extracted = extract_archive(report_root / INVENTORY_ARCHIVE, temporary)
    if not (extracted / "inventories").is_dir():
        raise BathroomRiverContainingPakError("inventory report has no inventories directory")
    return extracted


def normalize_path(value: object) -> str:
    return str(value or "").replace("\\", "/").strip("/").casefold()


def resolve_target_inventory_member(inventory_root: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    matches: list[tuple[dict[str, Any], dict[str, Any]]] = []
    for path in sorted((inventory_root / "inventories").glob("*.target.json")):
        inventory = load_json(path)
        for raw in inventory.get("files", []):
            if not isinstance(raw, dict):
                continue
            if normalize_path(raw.get("normalized_path")) == normalize_path(PARENT_PATH):
                matches.append((inventory, dict(raw)))
    if len(matches) != 1:
        raise BathroomRiverContainingPakError(
            f"expected one target inventory row for {PARENT_PATH}, found {len(matches)}"
        )
    inventory, row = matches[0]
    if str(inventory.get("normalization_side", "target")) not in {"", "target"}:
        raise BathroomRiverContainingPakError("resolved inventory is not target-side")
    archive = safe_posix(str(row.get("archive", "")), label="target archive")
    member = safe_posix(str(row.get("path", "")), label="target member")
    row["archive"] = archive
    row["path"] = member
    return inventory, row


def archive_inventory_sha(report_root: Path, inventory_root: Path, archive_rel: str) -> str:
    candidates = [report_root / "ARCHIVE_INVENTORY.tsv", inventory_root / "ARCHIVE_INVENTORY.tsv"]
    for candidate in candidates:
        if not candidate.is_file():
            continue
        rows = read_tsv(candidate)
        matches = [
            row for row in rows
            if str(row.get("side", "")) == "target"
            and normalize_path(row.get("archive")) == normalize_path(archive_rel)
        ]
        if len(matches) == 1:
            value = str(matches[0].get("sha256", ""))
            return value if len(value) == 64 else ""
    return ""


def remove_previous_root(path: Path) -> None:
    if not path.exists():
        return
    marker = path / "HARNESS.json"
    if not marker.is_file():
        raise BathroomRiverContainingPakError(f"refusing to replace unmarked directory: {path}")
    data = load_json(marker)
    if data.get("type") != "br_quartet_restoration_local_bathroom_river_containing_pak_repack_test_harness":
        raise BathroomRiverContainingPakError(f"unexpected existing harness marker: {marker}")
    shutil.rmtree(path)


def build(
    *, project_root: Path, quartet_root: Path, gust_pak: Path,
    workspace_root: Path, report_root: Path, timeout_seconds: int = 600,
) -> tuple[Path, dict[str, Any]]:
    project_root = project_root.resolve()
    quartet_root = quartet_root.resolve()
    workspace_root = workspace_root.resolve()
    report_root = report_root.resolve()
    require_within(workspace_root, project_root / ".local/build/quartet_restoration", label="workspace")
    require_within(report_root, project_root / ".local/reports/quartet_restoration", label="report root")
    if not quartet_root.is_dir():
        raise BathroomRiverContainingPakError(f"Quartet game root does not exist: {quartet_root}")
    if not gust_pak.is_file() or not os.access(gust_pak, os.X_OK):
        raise BathroomRiverContainingPakError(f"gust_pak is missing or not executable: {gust_pak}")

    print("[stage71] validating stage-70 parent-Elixir report", flush=True)
    with tempfile.TemporaryDirectory(prefix="br-stage71-") as temp_name:
        temp = Path(temp_name)
        stage70_root = locate_report_root(report_root, STAGE70_DIR, STAGE70_ARCHIVE, temp / "stage70")
        stage70_summary, stage70_profile, _stage70_file = validate_stage70(stage70_root)
        candidate_parent, stage70_manifest = resolve_stage70_candidate(
            project_root, workspace_root, stage70_profile
        )
        inventory_root = locate_inventory_root(report_root, temp / "inventory")
        inventory, inventory_row = resolve_target_inventory_member(inventory_root)
        archive_rel = str(inventory_row["archive"])
        target_member = str(inventory_row["path"])
        installed_archive = (quartet_root / Path(archive_rel)).resolve()
        require_within(installed_archive, quartet_root, label="installed containing PAK")
        if not installed_archive.is_file():
            raise BathroomRiverContainingPakError(f"containing PAK is missing: {installed_archive}")

        print(f"[stage71] containing archive: {archive_rel}", flush=True)
        current_archive_sha = sha256_file(installed_archive)
        current_archive_size = installed_archive.stat().st_size
        pristine_archive_sha = archive_inventory_sha(report_root, inventory_root, archive_rel)
        pristine_archive_match = bool(pristine_archive_sha) and current_archive_sha == pristine_archive_sha
        gust_pak_sha = sha256_file(gust_pak)

        final_root = workspace_root / REPACK_SUBDIR
        final_root.parent.mkdir(parents=True, exist_ok=True)
        temporary_root = Path(tempfile.mkdtemp(prefix=".bathroom_river_pak.", dir=final_root.parent))
        try:
            baseline_root = temporary_root / "baseline"
            rollback_path = baseline_root / Path(archive_rel)
            rollback_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(installed_archive, rollback_path)
            rollback_sha = sha256_file(rollback_path)
            if rollback_sha != current_archive_sha:
                raise BathroomRiverContainingPakError("local rollback PAK checksum mismatch")

            baseline_extract = baseline_root / "extracted"
            print("[stage71] extracting current containing PAK", flush=True)
            baseline_manifest_path, baseline_manifest = BR._extract_pak_for_repack_test(
                archive=installed_archive,
                destination=baseline_extract,
                gust_pak=gust_pak,
                timeout_seconds=timeout_seconds,
                log_name="baseline_extract.log",
            )
            baseline_members = BR._manifest_member_hashes(baseline_extract, baseline_manifest)
            baseline_signature = BR._gust_manifest_semantic_signature(baseline_manifest)
            target_key = target_member.casefold()
            current_member = baseline_members.get(target_key)
            if current_member is None:
                raise BathroomRiverContainingPakError(
                    f"inventory member is absent from current PAK: {target_member}"
                )
            if current_member["sha256"] != EXPECTED_TARGET_PARENT_SHA256:
                raise BathroomRiverContainingPakError(
                    "current containing-PAK member does not match the stage-70 target parent"
                )
            if sha256_file(candidate_parent) != str(stage70_profile.get("candidate_parent_sha256", "")):
                raise BathroomRiverContainingPakError("stage-70 candidate parent changed before PAK repack")

            profile_root = temporary_root / "profiles" / PROFILE_ID
            stage_dir = profile_root / "staging"
            verify_dir = profile_root / "verify"
            output_path = profile_root / "output" / Path(archive_rel)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            BR._copy_repack_input_tree(baseline_extract, stage_dir)
            stage_manifest_path = stage_dir / baseline_manifest_path.name
            stage_manifest = BR._load_gust_pak_manifest(stage_manifest_path)
            stage_target = stage_dir / Path(current_member["name"])
            require_within(stage_target, stage_dir, label="staged PAK member")
            shutil.copy2(candidate_parent, stage_target)

            print("[stage71] repacking local containing PAK", flush=True)
            stage_output = stage_dir / str(stage_manifest["safe_output_name"])
            stage_output.unlink(missing_ok=True)
            BR._run_gust_pak(
                gust_pak=gust_pak,
                argument_name=stage_manifest_path.name,
                cwd=stage_dir,
                log_path=profile_root / "repack.log",
                timeout_seconds=timeout_seconds,
            )
            if not stage_output.is_file():
                raise BathroomRiverContainingPakError("gust_pak did not produce the local containing PAK")
            shutil.move(stage_output, output_path)
            output_sha = sha256_file(output_path)
            output_size = output_path.stat().st_size

            print("[stage71] re-extracting and verifying local PAK", flush=True)
            verify_manifest_path, verify_manifest = BR._extract_pak_for_repack_test(
                archive=output_path,
                destination=verify_dir,
                gust_pak=gust_pak,
                timeout_seconds=timeout_seconds,
                log_name="verify_extract.log",
            )
            verify_members = BR._manifest_member_hashes(verify_dir, verify_manifest)
            verify_signature = BR._gust_manifest_semantic_signature(verify_manifest)
            manifest_differences = BR._gust_manifest_metadata_differences(
                baseline_manifest,
                verify_manifest,
                profile_id=PROFILE_ID,
                modified_member_keys={target_key},
            )
            stable_manifest_differences = sum(
                row.get("gate_effect") == "validation_gate" for row in manifest_differences
            )
            derived_manifest_differences = sum(
                row.get("gate_effect") == "diagnostic_only" for row in manifest_differences
            )
            set_delta = set(baseline_members) ^ set(verify_members)
            unchanged_keys = set(baseline_members) - {target_key}
            unchanged_mismatches = [
                key for key in sorted(unchanged_keys)
                if verify_members.get(key, {}).get("sha256") != baseline_members[key]["sha256"]
            ]
            repacked_member_sha = verify_members.get(target_key, {}).get("sha256", "")
            candidate_parent_sha = sha256_file(candidate_parent)

            checks: dict[str, bool] = {
                "stage70_report_canonical": True,
                "stage70_local_parent_manifest_canonical": True,
                "stage70_candidate_parent_hash_matches": candidate_parent_sha == str(stage70_profile.get("candidate_parent_sha256", "")),
                "target_inventory_member_resolved_once": True,
                "installed_containing_pak_present": installed_archive.is_file(),
                "rollback_copy_exact_input_pak": rollback_sha == current_archive_sha,
                "baseline_manifest_valid": bool(baseline_members),
                "target_member_present_once": target_key in baseline_members,
                "current_target_member_hash_expected": current_member["sha256"] == EXPECTED_TARGET_PARENT_SHA256,
                "candidate_parent_replaces_exact_target_member": repacked_member_sha == candidate_parent_sha,
                "pak_member_name_set_preserved": not set_delta,
                "pak_manifest_semantics_preserved": verify_signature == baseline_signature,
                "stable_manifest_differences_absent": stable_manifest_differences == 0,
                "all_unchanged_members_preserved": not unchanged_mismatches,
                "exactly_one_member_changed": sum(
                    verify_members.get(key, {}).get("sha256") != baseline_members.get(key, {}).get("sha256")
                    for key in set(baseline_members) | set(verify_members)
                ) == 1,
                "output_pak_differs_from_input": output_sha != current_archive_sha,
                "verification_manifest_created": verify_manifest_path.is_file(),
                "installed_pak_still_matches_initial_sha256": sha256_file(installed_archive) == current_archive_sha,
                "candidate_and_rollback_local_only": output_path.is_relative_to(workspace_root) and rollback_path.is_relative_to(workspace_root),
                "source_parent_elixir_local_profile_unchanged": sha256_file(candidate_parent) == candidate_parent_sha,
            }
            validation_rows = [
                {
                    "profile_id": PROFILE_ID,
                    "target_archive": archive_rel,
                    "check_name": name,
                    "passed": passed,
                    "details": (
                        f"checked={len(unchanged_keys)};mismatches={len(unchanged_mismatches)}"
                        if name == "all_unchanged_members_preserved"
                        else f"stable={stable_manifest_differences};derived={derived_manifest_differences}"
                        if name == "stable_manifest_differences_absent"
                        else ""
                    ),
                }
                for name, passed in checks.items()
            ]
            failures = [name for name, passed in checks.items() if not passed]
            skipped_rows: list[dict[str, object]] = []
            profile_rows: list[dict[str, object]] = []
            file_rows: list[dict[str, object]] = []
            if failures:
                output_path.unlink(missing_ok=True)
                skipped_rows.append({
                    "profile_id": PROFILE_ID,
                    "target_archive": archive_rel,
                    "target_member_path": target_member,
                    "reason": "containing_pak_repack_validation_failed:" + ";".join(failures),
                })
            else:
                profile_manifest = {
                    "type": "br_quartet_restoration_local_bathroom_river_containing_pak_repack_test_profile",
                    "format_version": 1,
                    "tool_version": TOOL_VERSION,
                    "profile_id": PROFILE_ID,
                    "source_profile_id": SOURCE_PROFILE_ID,
                    "classification": "single_parent_elixir_member_containing_pak_repack_test",
                    "input_archive_relative_path": archive_rel,
                    "input_archive_sha256": current_archive_sha,
                    "input_archive_size": current_archive_size,
                    "output_archive_relative_path": output_path.relative_to(temporary_root).as_posix(),
                    "output_archive_sha256": output_sha,
                    "output_archive_size": output_size,
                    "rollback_archive_relative_path": rollback_path.relative_to(temporary_root).as_posix(),
                    "rollback_archive_sha256": rollback_sha,
                    "target_member_path": target_member,
                    "target_member_sha256": EXPECTED_TARGET_PARENT_SHA256,
                    "candidate_member_sha256": candidate_parent_sha,
                    "repacked_member_sha256": repacked_member_sha,
                    "replaced_member_count": 1,
                    "unchanged_member_count_verified": len(unchanged_keys),
                    "gust_pak_sha256": gust_pak_sha,
                    "inventory_pair_id": inventory.get("archive_group", inventory.get("pair_id", "")),
                    "runtime_validated": False,
                    "activation_supported": False,
                    "core_registry_modified": False,
                    "installed_game_modified": False,
                    "semantics_assigned": False,
                    "opl2_modified": False,
                }
                atomic_json(profile_root / "PROFILE.json", profile_manifest)
                profile_rows.append({
                    "profile_id": PROFILE_ID,
                    "source_profile_id": SOURCE_PROFILE_ID,
                    "classification": profile_manifest["classification"],
                    "target_archive": archive_rel,
                    "target_member_path": target_member,
                    "input_archive_sha256": current_archive_sha,
                    "output_archive_sha256": output_sha,
                    "rollback_archive_sha256": rollback_sha,
                    "input_archive_size": current_archive_size,
                    "output_archive_size": output_size,
                    "replaced_member_count": 1,
                    "unchanged_member_count_verified": len(unchanged_keys),
                    "inventory_pristine_archive_match": pristine_archive_match,
                    "baseline_manifest_parse_mode": baseline_manifest.get("safe_parse_mode", "unknown"),
                    "verification_manifest_parse_mode": verify_manifest.get("safe_parse_mode", "unknown"),
                    "local_output_archive": str((final_root / "profiles" / PROFILE_ID / "output" / Path(archive_rel)).relative_to(project_root)),
                    "local_rollback_archive": str((final_root / "baseline" / Path(archive_rel)).relative_to(project_root)),
                    "validation_status": "passed",
                    "runtime_validated": False,
                    "review_status": "local_containing_pak_only_not_registered_not_installed",
                })
                file_rows.append({
                    "profile_id": PROFILE_ID,
                    "normalized_path": PARENT_PATH,
                    "target_archive": archive_rel,
                    "target_member_path": target_member,
                    "target_member_sha256": EXPECTED_TARGET_PARENT_SHA256,
                    "candidate_member_sha256": candidate_parent_sha,
                    "repacked_member_sha256": repacked_member_sha,
                    "validation_status": "passed",
                    "review_status": "single_parent_elixir_member_repacked_all_other_pak_members_preserved",
                })

            harness = {
                "type": "br_quartet_restoration_local_bathroom_river_containing_pak_repack_test_harness",
                "format_version": 1,
                "tool_version": TOOL_VERSION,
                "source_stage70_tool_version": stage70_summary.get("tool_version"),
                "successful_profile_ids": [PROFILE_ID] if profile_rows else [],
                "input_archive_relative_path": archive_rel,
                "input_archive_sha256": current_archive_sha,
                "inventory_pristine_archive_sha256": pristine_archive_sha,
                "inventory_pristine_archive_match": pristine_archive_match,
                "gust_pak_sha256": gust_pak_sha,
                "baseline_member_count": len(baseline_members),
                "installed_game_modified": False,
                "activation_supported": False,
            }
            atomic_json(temporary_root / "HARNESS.json", harness)
            shutil.rmtree(baseline_extract, ignore_errors=True)
            shutil.rmtree(stage_dir, ignore_errors=True)
            shutil.rmtree(verify_dir, ignore_errors=True)
            remove_previous_root(final_root)
            os.replace(temporary_root, final_root)
            temporary_root = None
        finally:
            if temporary_root is not None and temporary_root.exists():
                shutil.rmtree(temporary_root, ignore_errors=True)

        outdir = report_root / EVIDENCE_DIR_NAME
        if outdir.exists():
            shutil.rmtree(outdir)
        outdir.mkdir(parents=True, exist_ok=True)
        write_tsv(outdir / "BATHROOM_RIVER_CONTAINING_PAK_REPACK_PROFILES.tsv", [
            "profile_id", "source_profile_id", "classification", "target_archive",
            "target_member_path", "input_archive_sha256", "output_archive_sha256",
            "rollback_archive_sha256", "input_archive_size", "output_archive_size",
            "replaced_member_count", "unchanged_member_count_verified",
            "inventory_pristine_archive_match", "baseline_manifest_parse_mode",
            "verification_manifest_parse_mode", "local_output_archive",
            "local_rollback_archive", "validation_status", "runtime_validated", "review_status",
        ], profile_rows)
        write_tsv(outdir / "BATHROOM_RIVER_CONTAINING_PAK_REPACK_FILES.tsv", [
            "profile_id", "normalized_path", "target_archive", "target_member_path",
            "target_member_sha256", "candidate_member_sha256", "repacked_member_sha256",
            "validation_status", "review_status",
        ], file_rows)
        write_tsv(outdir / "BATHROOM_RIVER_CONTAINING_PAK_REPACK_VALIDATIONS.tsv", [
            "profile_id", "target_archive", "check_name", "passed", "details",
        ], validation_rows)
        write_tsv(outdir / "BATHROOM_RIVER_CONTAINING_PAK_REPACK_MANIFEST_DIFFERENCES.tsv", [
            "profile_id", "scope", "field", "member_path", "classification",
            "baseline_value", "verification_value", "baseline_value_sha256",
            "verification_value_sha256", "gate_effect",
        ], manifest_differences)
        write_tsv(outdir / "BATHROOM_RIVER_CONTAINING_PAK_REPACK_SKIPPED.tsv", [
            "profile_id", "target_archive", "target_member_path", "reason",
        ], skipped_rows)
        validation_failures = sum(not parse_bool(row.get("passed")) for row in validation_rows)
        summary = {
            "type": "br_quartet_restoration_bathroom_river_containing_pak_repack_test_evidence_summary",
            "format_version": 1,
            "tool_version": TOOL_VERSION,
            "source_stage70_tool_version": EXPECTED_STAGE70_TOOL_VERSION,
            "status": (
                "bathroom_river_containing_pak_local_repack_verified_not_registered_or_installed"
                if profile_rows else "bathroom_river_containing_pak_local_repack_not_built"
            ),
            "proposed_profile_rows": 1,
            "repacked_profile_rows": len(profile_rows),
            "file_rows": len(file_rows),
            "validation_rows": len(validation_rows),
            "validation_failures": validation_failures,
            "manifest_difference_rows": len(manifest_differences),
            "stable_manifest_difference_rows": stable_manifest_differences,
            "derived_manifest_difference_rows": derived_manifest_differences,
            "skipped_rows": len(skipped_rows),
            "target_archive": archive_rel,
            "target_member_path": target_member,
            "input_archive_sha256": current_archive_sha,
            "output_archive_sha256": output_sha if profile_rows else "",
            "input_archive_size": current_archive_size,
            "output_archive_size": output_size if profile_rows else 0,
            "unchanged_member_count_verified": len(unchanged_keys),
            "candidate_parent_sha256": candidate_parent_sha,
            "inventory_pristine_archive_sha256": pristine_archive_sha,
            "inventory_pristine_archive_match": pristine_archive_match,
            "policy": {
                "installed_game_read_only": True,
                "installed_game_modified": False,
                "current_archive_used_as_repack_base": True,
                "unrelated_translation_or_other_member_changes_preserved": True,
                "all_unchanged_members_verified_by_reextraction_hash": True,
                "stable_manifest_fields_used_as_validation_gate": True,
                "derived_gust_manifest_keys_used_as_validation_gate": False,
                "local_rollback_baseline_copied": True,
                "candidate_pak_written_only_under_local_workspace": True,
                "proprietary_pak_exported_in_report": False,
                "candidate_parent_payload_exported_in_report": False,
                "core_registry_modified": False,
                "activation_or_rollback_invoked": False,
                "runtime_validation_inferred": False,
                "censorship_classification_inferred": False,
                "opaque_binary_field_semantics_inferred": False,
                "opl2_payload_modified": False,
                "translation_or_dlc_workstreams_modified": False,
                "canary_track_modified": False,
            },
            "next_action": (
                "Upload this metadata report. If one profile passes with zero failures/skips, "
                "register one new inactive checksum-gated local profile for the containing PAK; "
                "do not activate or install it yet."
            ),
        }
        atomic_json(outdir / "SUMMARY.json", summary)
        output = report_root / REPORT_NAME
        make_report_archive(outdir, output)
        print(f"[stage71] local containing-PAK profiles: {summary['repacked_profile_rows']}", flush=True)
        print(f"[stage71] validation failures: {validation_failures}", flush=True)
        print(f"[stage71] installed game modified: false", flush=True)
        print(f"[stage71] report: {output}", flush=True)
        return output, summary


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", default=str(PROJECT_ROOT_DEFAULT))
    parser.add_argument("--quartet-root", required=True)
    parser.add_argument("--gust-pak", required=True)
    parser.add_argument("--workspace-root")
    parser.add_argument("--report-root")
    parser.add_argument("--timeout-seconds", type=int, default=600)
    args = parser.parse_args(argv)
    project_root = Path(args.project_root).expanduser().resolve()
    workspace_root = (
        Path(args.workspace_root).expanduser().resolve()
        if args.workspace_root else project_root / ".local/build/quartet_restoration"
    )
    report_root = (
        Path(args.report_root).expanduser().resolve()
        if args.report_root else project_root / ".local/reports/quartet_restoration"
    )
    build(
        project_root=project_root,
        quartet_root=Path(args.quartet_root).expanduser().resolve(),
        gust_pak=Path(args.gust_pak).expanduser().resolve(),
        workspace_root=workspace_root,
        report_root=report_root,
        timeout_seconds=args.timeout_seconds,
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (BathroomRiverContainingPakError, BR.RestorationError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
