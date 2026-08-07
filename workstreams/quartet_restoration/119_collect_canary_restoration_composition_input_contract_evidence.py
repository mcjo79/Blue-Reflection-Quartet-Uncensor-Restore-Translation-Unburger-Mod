#!/usr/bin/env python3
"""Audit the exact 15-profile Restoration input contract for a future Canary-all composer.

Stage 119 is read-only and fail-closed. It verifies the completed swordflash
freeze, the immutable 15-profile manifest report, current profile manifests,
optional local profile payload hashes, common baseline identity and disjoint
changed-member ownership. It also verifies the bounded source contract of the
existing production composer: only runtime-validated profiles are production
eligible, so the current 15 runtime-unvalidated profiles cannot enter it.

The stage does not compose, extract, repack, activate or install a PAK. It does
not modify core, profile manifests, registry, Translation, Legacy DLC, the game
installation or Git. A passing report authorizes only a separate synthetic
Canary-all composer design and fixture tests in a later stage.
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
from collections import defaultdict
from pathlib import Path, PurePosixPath
from typing import Any, Iterable, Mapping, Sequence

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT_DEFAULT = SCRIPT_DIR.parent.parent
TOOL_VERSION = "0.1.37"
REPORT_NAME = "BR_quartet_restoration_canary_composition_input_contract_evidence.tar.zst"
REPORT_DIR = "canary_composition_input_contract_evidence"

CORE_REPORT_DIR = "core_profile_manifest_evidence"
CORE_REPORT_ARCHIVE = "BR_quartet_restoration_core_profile_manifest_evidence.tar.zst"
CORE_REPORT_SHA256 = "9a89f376064b5cda1135b8d42572581dd47c0f90464f8bdc39fca597dced7789"
FREEZE_REPORT_DIR = "reflector_slot_light_swordflash_unresolved_freeze_evidence"
FREEZE_REPORT_ARCHIVE = "BR_quartet_restoration_reflector_slot_light_swordflash_unresolved_freeze_evidence.tar.zst"
STAGE118_SHA256 = "12a6c42306d563b2130d98f58fe1517ce849f84c00eb24d9996130d7923abb0d"

MANIFEST_ROOT_REL = Path(".local/build/quartet_restoration/core_profiles/generated")
EXPECTED_PROFILE_ROWS = 15
EXPECTED_CHANGED_MEMBER_ROWS = 30
EXPECTED_TARGET_PROFILE_ROWS = {
    "Data/PACK11.PAK": 12,
    "Data/PACK10_01.PAK": 2,
    "Data/PACK10_03.PAK": 1,
}

PRODUCTION_CONTRACT_FILES = {
    "preview": Path("Blue_Reflection_Patcher/cmd/brpatcher/composition_preview_cli.go"),
    "build": Path("Blue_Reflection_Patcher/cmd/brpatcher/composition_build_cli.go"),
    "main": Path("Blue_Reflection_Patcher/cmd/brpatcher/main.go"),
    "preview_doc": Path("workstreams/core/docs/QUARTET_COMPOSITION_PREFLIGHT.md"),
    "build_doc": Path("workstreams/core/docs/QUARTET_COMPOSITION_BUILD.md"),
}


class CanaryContractError(RuntimeError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise CanaryContractError(message)


def progress(message: str) -> None:
    print(f"[canary-contract] {message}", file=sys.stderr, flush=True)


def parse_int(value: Any, default: int = 0) -> int:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return default


def parse_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().casefold() in {"1", "true", "yes", "y"}


def is_sha256(value: Any) -> bool:
    text = str(value).strip().casefold()
    return len(text) == 64 and all(ch in "0123456789abcdef" for ch in text)


def safe_relative(raw: str, label: str) -> str:
    path = PurePosixPath(str(raw).replace("\\", "/"))
    require(bool(path.parts), f"empty {label}")
    require(not path.is_absolute() and ".." not in path.parts, f"unsafe {label}: {raw}")
    return path.as_posix()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_json(path: Path) -> dict[str, Any]:
    require(path.is_file(), f"missing required JSON: {path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CanaryContractError(f"invalid JSON {path}: {exc}") from exc
    require(isinstance(value, dict), f"JSON root must be object: {path}")
    return value


def read_tsv(path: Path) -> list[dict[str, str]]:
    require(path.is_file(), f"missing required TSV: {path}")
    with path.open(encoding="utf-8", newline="") as handle:
        return [dict(row) for row in csv.DictReader(handle, delimiter="\t")]


def write_tsv(path: Path, fields: Sequence[str], rows: Iterable[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=list(fields),
            delimiter="\t",
            lineterminator="\n",
            extrasaction="ignore",
        )
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fields})


def extract_archive(archive: Path, destination: Path) -> Path:
    require(archive.is_file(), f"missing prerequisite report: {archive}")
    listed = subprocess.run(["tar", "--zstd", "-tf", str(archive)], text=True, capture_output=True)
    require(listed.returncode == 0, listed.stderr.strip() or f"cannot list {archive}")
    names = [line.strip() for line in listed.stdout.splitlines() if line.strip()]
    require(names, f"empty prerequisite report: {archive}")
    roots = {PurePosixPath(safe_relative(name, "archive member")).parts[0] for name in names}
    require(len(roots) == 1, f"expected one report root in {archive}")
    destination.mkdir(parents=True, exist_ok=True)
    completed = subprocess.run(
        ["tar", "--zstd", "-xf", str(archive), "-C", str(destination)],
        text=True,
        capture_output=True,
    )
    require(completed.returncode == 0, completed.stderr.strip() or f"cannot extract {archive}")
    root = destination / next(iter(roots))
    require(root.is_dir(), f"missing extracted report root: {root}")
    return root


def locate_report(report_root: Path, direct: str, archive: str, temporary: Path) -> Path:
    direct_path = report_root / direct
    if direct_path.is_dir():
        return direct_path
    return extract_archive(report_root / archive, temporary)


def make_archive(source: Path, output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(output.name + ".tmp")
    temporary.unlink(missing_ok=True)
    completed = subprocess.run(
        ["tar", "--zstd", "-cf", str(temporary), "-C", str(source.parent), source.name],
        text=True,
        capture_output=True,
    )
    require(completed.returncode == 0, completed.stderr.strip() or "report archive creation failed")
    os.replace(temporary, output)


def validate_freeze_summary(summary: Mapping[str, Any]) -> None:
    require(summary.get("tool_version") == "0.1.36", "swordflash freeze tool-version drift")
    require(
        summary.get("status")
        == "existing_independent_binding_channels_exhausted_swordflash_branch_frozen_unresolved_no_write",
        "swordflash freeze status drift",
    )
    require(summary.get("stage118_report_sha256") == STAGE118_SHA256, "swordflash freeze stage-118 hash drift")
    require(parse_int(summary.get("existing_binding_channel_rows"), -1) == 6, "swordflash freeze channel-count drift")
    require(parse_int(summary.get("authorizing_binding_channel_rows"), -1) == 0, "swordflash freeze authorizing-channel drift")
    require(parse_int(summary.get("frozen_unresolved_swordflash_pair_rows"), -1) == 2, "swordflash freeze pair-count drift")
    require(not parse_bool(summary.get("numbered_stage_created")), "swordflash freeze unexpectedly created a numbered stage")
    policy = summary.get("policy")
    require(isinstance(policy, Mapping), "swordflash freeze policy missing")
    for field in (
        "deletion_ordinal_2_accepted_from_table_eligibility_alone",
        "G1E_G1EM_write_authorized",
        "pak_repack_authorized",
        "profile_or_registry_write_authorized",
        "installed_game_modified",
        "git_modified",
    ):
        require(not parse_bool(policy.get(field)), f"swordflash freeze policy drift: {field}")


def validate_core_report(summary: Mapping[str, Any], rows: Sequence[Mapping[str, Any]]) -> dict[str, Mapping[str, Any]]:
    require(summary.get("tool_version") == "0.0.83", "core profile report tool-version drift")
    require(summary.get("status") == "all_current_local_profiles_registered_runtime_unvalidated", "core profile report status drift")
    require(parse_int(summary.get("profile_rows"), -1) == EXPECTED_PROFILE_ROWS, "core profile count drift")
    for target, expected in EXPECTED_TARGET_PROFILE_ROWS.items():
        key = {
            "Data/PACK11.PAK": "pack11_profile_rows",
            "Data/PACK10_01.PAK": "pack10_01_profile_rows",
            "Data/PACK10_03.PAK": "pack10_03_profile_rows",
        }[target]
        require(parse_int(summary.get(key), -1) == expected, f"core profile target split drift: {target}")
    require(parse_int(summary.get("runtime_validated_profile_rows"), -1) == 0, "runtime-validation count drift")
    policy = summary.get("policy")
    require(isinstance(policy, Mapping), "core profile report policy missing")
    require(parse_bool(policy.get("profile_paks_checksum_and_size_verified")), "core report did not verify profile payloads")
    require(not parse_bool(policy.get("activation_or_rollback_scripts_generated")), "core report unexpectedly generated activation")
    require(not parse_bool(policy.get("runtime_validation_inferred")), "core report inferred runtime validation")
    require(len(rows) == EXPECTED_PROFILE_ROWS, "core profile TSV row-count drift")

    indexed: dict[str, Mapping[str, Any]] = {}
    for row in rows:
        profile_id = str(row.get("profile_id", "")).strip()
        require(profile_id and profile_id not in indexed, f"duplicate/empty core profile row: {profile_id}")
        require(str(row.get("validation_status", "")) == "passed", f"core profile validation failed: {profile_id}")
        require(not parse_bool(row.get("runtime_validated")), f"unexpected runtime-validated core row: {profile_id}")
        indexed[profile_id] = row
    return indexed


def validate_production_composer_contract(project_root: Path) -> list[dict[str, Any]]:
    texts: dict[str, str] = {}
    rows: list[dict[str, Any]] = []
    for role, relative in PRODUCTION_CONTRACT_FILES.items():
        path = project_root / relative
        require(path.is_file(), f"missing production composer contract file: {relative}")
        text = path.read_text(encoding="utf-8")
        texts[role] = text
        rows.append(
            {
                "check_id": f"source_file_{role}",
                "relative_path": relative.as_posix(),
                "passed": True,
                "observed": sha256_file(path),
                "meaning": "bounded production-composer contract source present",
            }
        )

    exact_checks = [
        (
            "preview_rejects_unvalidated_profiles",
            "preview",
            'case !profile.RuntimeValidated:',
            "current runtime-unvalidated profiles remain candidates",
        ),
        (
            "preview_marks_candidate_awaiting_runtime_validation",
            "preview",
            'profile.Status = "candidate_awaiting_runtime_validation"',
            "unvalidated profile status is explicit",
        ),
        (
            "preview_only_marks_eligible_after_runtime_gate",
            "preview",
            'profile.Status = "eligible_runtime_validated"',
            "production eligibility follows the runtime gate",
        ),
        (
            "preview_reports_awaiting_runtime_profiles",
            "preview",
            'preview.Status = "awaiting_runtime_validated_profiles"',
            "zero eligible profiles is a non-buildable state",
        ),
        (
            "build_requires_ready_preflight",
            "build",
            'preflight.Status != "ready_for_composition_build"',
            "production build cannot bypass preflight",
        ),
        (
            "build_selects_only_production_eligible_profiles",
            "build",
            'if !profile.ProductionEligible {',
            "production build skips every noneligible profile",
        ),
        (
            "build_rejects_empty_production_set",
            "build",
            'composition preflight selected no production-eligible restoration profiles',
            "production build rejects the current zero-eligible set",
        ),
        (
            "main_registers_production_build_command",
            "main",
            'case "quartet-composition-build":',
            "production composer entrypoint exists",
        ),
        (
            "preflight_doc_runtime_gate",
            "preview_doc",
            "`runtime_validated` is true",
            "documented production gate agrees with source",
        ),
        (
            "build_doc_runtime_gate",
            "build_doc",
            "Only profiles that are valid, locally hash-verified and marked",
            "documented build contract agrees with source",
        ),
    ]
    for check_id, role, needle, meaning in exact_checks:
        present = needle in texts[role]
        require(present, f"production composer contract drift: {check_id}")
        rows.append(
            {
                "check_id": check_id,
                "relative_path": PRODUCTION_CONTRACT_FILES[role].as_posix(),
                "passed": present,
                "observed": needle,
                "meaning": meaning,
            }
        )

    bounded_text = "\n".join(texts.values()).casefold()
    explicit_canary_tokens = [
        "quartet-canary-composition-build",
        "quartet-restoration-canary-build",
        "canary-all-composition-build",
    ]
    found = [token for token in explicit_canary_tokens if token in bounded_text]
    require(not found, f"unexpected explicit Canary-all entrypoint detected: {found}")
    rows.append(
        {
            "check_id": "explicit_canary_all_entrypoint_absent",
            "relative_path": ";".join(path.as_posix() for path in PRODUCTION_CONTRACT_FILES.values()),
            "passed": True,
            "observed": "0 bounded explicit Canary-all command tokens",
            "meaning": "a separate Canary-all composer still requires an explicit later implementation",
        }
    )
    return rows


def validate_manifest(
    manifest_path: Path,
    project_root: Path,
    report_row: Mapping[str, Any],
    verify_payload: bool,
) -> tuple[dict[str, Any], dict[str, Any]]:
    data = load_json(manifest_path)
    require(parse_int(data.get("schema_version"), -1) == 1, f"manifest schema drift: {manifest_path.name}")
    require(data.get("workstream_id") == "quartet_restoration", f"manifest workstream drift: {manifest_path.name}")
    profile_id = str(data.get("profile_id", "")).strip()
    require(profile_id == manifest_path.stem, f"manifest/profile filename mismatch: {manifest_path.name}")
    require(not parse_bool(data.get("runtime_validated")), f"runtime-validated profile entered Canary input snapshot: {profile_id}")

    target = safe_relative(str(data.get("target_relative_path", "")), "target path")
    require(target in EXPECTED_TARGET_PROFILE_ROWS, f"unexpected target archive: {target}")
    baseline_sha256 = str(data.get("baseline_sha256", "")).casefold()
    profile_sha256 = str(data.get("profile_sha256", "")).casefold()
    require(is_sha256(baseline_sha256), f"invalid baseline SHA-256: {profile_id}")
    require(is_sha256(profile_sha256), f"invalid profile SHA-256: {profile_id}")
    baseline_size = parse_int(data.get("baseline_size"), -1)
    profile_size = parse_int(data.get("profile_size"), -1)
    require(baseline_size > 0 and profile_size > 0, f"invalid manifest sizes: {profile_id}")
    local_profile_path = safe_relative(str(data.get("local_profile_path", "")), "local profile path")

    raw_members = data.get("changed_members")
    require(isinstance(raw_members, list) and raw_members, f"missing changed members: {profile_id}")
    changed_members = [safe_relative(str(member), "changed member") for member in raw_members]
    require(len(changed_members) == len(set(member.casefold() for member in changed_members)), f"duplicate changed member: {profile_id}")
    require(parse_int(data.get("changed_member_count"), -1) == len(changed_members), f"changed-member count drift: {profile_id}")

    comparisons: dict[str, Any] = {
        "target_relative_path": target,
        "baseline_sha256": baseline_sha256,
        "baseline_size": baseline_size,
        "profile_sha256": profile_sha256,
        "profile_size": profile_size,
        "local_profile_path": local_profile_path,
        "changed_member_count": len(changed_members),
    }
    for key, value in comparisons.items():
        observed = report_row.get(key, "")
        if isinstance(value, int):
            require(parse_int(observed, -1) == value, f"manifest/core-report {key} drift: {profile_id}")
        else:
            require(str(observed).casefold() == str(value).casefold(), f"manifest/core-report {key} drift: {profile_id}")

    payload_path = project_root / local_profile_path
    payload_exists = payload_path.is_file()
    observed_size = payload_path.stat().st_size if payload_exists else -1
    observed_sha256 = ""
    validation_status = "not_checked"
    if verify_payload:
        progress(f"hashing profile {profile_id}: {local_profile_path}")
        require(payload_exists, f"missing local profile payload: {local_profile_path}")
        require(observed_size == profile_size, f"local profile size drift: {profile_id}")
        observed_sha256 = sha256_file(payload_path)
        require(observed_sha256 == profile_sha256, f"local profile SHA-256 drift: {profile_id}")
        validation_status = "passed"

    profile_row = {
        "profile_id": profile_id,
        "target_relative_path": target,
        "baseline_sha256": baseline_sha256,
        "baseline_size": baseline_size,
        "profile_sha256": profile_sha256,
        "profile_size": profile_size,
        "local_profile_path": local_profile_path,
        "changed_member_count": len(changed_members),
        "changed_members": changed_members,
        "runtime_validated": False,
        "manifest_relative_path": manifest_path.relative_to(project_root).as_posix(),
        "workstream_version": str(data.get("workstream_version", "")),
    }
    payload_check = {
        "profile_id": profile_id,
        "target_relative_path": target,
        "local_profile_path": local_profile_path,
        "expected_size": profile_size,
        "observed_size": observed_size,
        "expected_sha256": profile_sha256,
        "observed_sha256": observed_sha256,
        "payload_exists": payload_exists,
        "validation_status": validation_status,
    }
    return profile_row, payload_check


def analyze_profile_rows(profile_rows: Sequence[Mapping[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    require(len(profile_rows) == EXPECTED_PROFILE_ROWS, f"expected {EXPECTED_PROFILE_ROWS} manifests, found {len(profile_rows)}")
    ids = [str(row["profile_id"]) for row in profile_rows]
    require(len(ids) == len(set(ids)), "duplicate profile ids")
    require({str(row["target_relative_path"]) for row in profile_rows} == set(EXPECTED_TARGET_PROFILE_ROWS), "target archive set drift")

    groups: list[dict[str, Any]] = []
    conflicts: list[dict[str, Any]] = []
    total_changed = 0
    for target, expected_rows in EXPECTED_TARGET_PROFILE_ROWS.items():
        rows = [row for row in profile_rows if row["target_relative_path"] == target]
        require(len(rows) == expected_rows, f"profile count drift for {target}")
        baselines = {(str(row["baseline_sha256"]), parse_int(row["baseline_size"], -1)) for row in rows}
        require(len(baselines) == 1, f"baseline identity disagreement for {target}")
        profile_hashes = [str(row["profile_sha256"]) for row in rows]
        require(len(profile_hashes) == len(set(profile_hashes)), f"duplicate profile payload identity for {target}")

        owners: dict[str, list[str]] = defaultdict(list)
        for row in rows:
            for member in row["changed_members"]:
                owners[str(member).casefold()].append(str(row["profile_id"]))
        target_changed = sum(len(row["changed_members"]) for row in rows)
        total_changed += target_changed
        for member_key, owner_ids in sorted(owners.items()):
            if len(owner_ids) > 1:
                conflicts.append(
                    {
                        "target_relative_path": target,
                        "changed_member": member_key,
                        "owner_profile_count": len(owner_ids),
                        "owner_profile_ids": ";".join(sorted(owner_ids)),
                        "classification": "blocked_same_target_member_overlap",
                    }
                )
        baseline_sha256, baseline_size = next(iter(baselines))
        target_conflicts = [row for row in conflicts if row["target_relative_path"] == target]
        groups.append(
            {
                "target_relative_path": target,
                "profile_rows": len(rows),
                "baseline_sha256": baseline_sha256,
                "baseline_size": baseline_size,
                "changed_member_reference_rows": target_changed,
                "unique_changed_member_rows": len(owners),
                "overlap_conflict_rows": len(target_conflicts),
                "runtime_validated_profile_rows": 0,
                "input_classification": "common_baseline_disjoint_member_sets" if not target_conflicts else "blocked_member_overlap",
            }
        )
    require(total_changed == EXPECTED_CHANGED_MEMBER_ROWS, f"changed member reference count drift: {total_changed}")
    require(not conflicts, f"changed member overlap detected: {len(conflicts)} conflict rows")
    return groups, conflicts


def load_profiles(
    project_root: Path,
    core_rows_by_id: Mapping[str, Mapping[str, Any]],
    verify_payloads: bool,
    *,
    manifest_root: Path | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    manifest_root = (manifest_root or (project_root / MANIFEST_ROOT_REL)).resolve()
    require(manifest_root.is_dir(), f"missing manifest root: {manifest_root}")
    manifest_paths = sorted(manifest_root.glob("*.json"))
    require(len(manifest_paths) == EXPECTED_PROFILE_ROWS, f"expected {EXPECTED_PROFILE_ROWS} manifest files, found {len(manifest_paths)}")

    profile_rows: list[dict[str, Any]] = []
    payload_checks: list[dict[str, Any]] = []
    for manifest_path in manifest_paths:
        profile_id = manifest_path.stem
        require(profile_id in core_rows_by_id, f"manifest absent from immutable core report: {profile_id}")
        profile, payload_check = validate_manifest(
            manifest_path,
            project_root,
            core_rows_by_id[profile_id],
            verify_payloads,
        )
        profile_rows.append(profile)
        payload_checks.append(payload_check)
    require(set(core_rows_by_id) == {row["profile_id"] for row in profile_rows}, "core report/manifest profile set drift")
    groups, conflicts = analyze_profile_rows(profile_rows)
    return profile_rows, payload_checks, groups, conflicts


def build_report(
    project_root: Path,
    *,
    source_report_root: Path | None = None,
    core_source_report_root: Path | None = None,
    output_report_root: Path | None = None,
    verify_payloads: bool = True,
    enforce_core_archive_hash: bool = True,
    create_archive: bool = True,
    manifest_root: Path | None = None,
) -> tuple[Path, Path | None, dict[str, Any]]:
    project_root = project_root.resolve()
    source_report_root = (source_report_root or project_root / ".local/reports/quartet_restoration").resolve()
    core_source_report_root = (core_source_report_root or source_report_root).resolve()
    output_report_root = (output_report_root or project_root / ".local/reports/quartet_restoration").resolve()

    with tempfile.TemporaryDirectory(prefix="br-canary-contract-") as temporary_name:
        temporary = Path(temporary_name)
        if enforce_core_archive_hash:
            core_archive = core_source_report_root / CORE_REPORT_ARCHIVE
            require(core_archive.is_file(), f"missing immutable core profile report: {core_archive}")
            require(sha256_file(core_archive) == CORE_REPORT_SHA256, "core profile report SHA-256 drift")

        core_root = locate_report(core_source_report_root, CORE_REPORT_DIR, CORE_REPORT_ARCHIVE, temporary / "core")
        freeze_root = locate_report(source_report_root, FREEZE_REPORT_DIR, FREEZE_REPORT_ARCHIVE, temporary / "freeze")
        core_summary = load_json(core_root / "SUMMARY.json")
        core_rows = read_tsv(core_root / "CORE_PROFILE_MANIFESTS.tsv")
        core_rows_by_id = validate_core_report(core_summary, core_rows)
        validate_freeze_summary(load_json(freeze_root / "SUMMARY.json"))
        composer_contract_rows = validate_production_composer_contract(project_root)

        profile_rows, payload_checks, group_rows, conflict_rows = load_profiles(
            project_root,
            core_rows_by_id,
            verify_payloads,
            manifest_root=manifest_root,
        )
        payload_pass_rows = sum(1 for row in payload_checks if row["validation_status"] == "passed")
        if verify_payloads:
            require(payload_pass_rows == EXPECTED_PROFILE_ROWS, "profile payload verification incomplete")

        input_rows = []
        for row in sorted(profile_rows, key=lambda item: (str(item["target_relative_path"]), str(item["profile_id"]))):
            input_rows.append(
                {
                    "profile_id": row["profile_id"],
                    "target_relative_path": row["target_relative_path"],
                    "baseline_sha256": row["baseline_sha256"],
                    "baseline_size": row["baseline_size"],
                    "profile_sha256": row["profile_sha256"],
                    "profile_size": row["profile_size"],
                    "local_profile_path": row["local_profile_path"],
                    "changed_member_count": row["changed_member_count"],
                    "changed_members": ";".join(row["changed_members"]),
                    "runtime_validated": False,
                    "production_composition_role": "excluded_candidate_awaiting_runtime_validation",
                    "future_canary_role": "member_source_candidate_only",
                }
            )

        contract_ready = bool(verify_payloads and payload_pass_rows == EXPECTED_PROFILE_ROWS and not conflict_rows)
        gates = [
            {"gate_id": "swordflash_branch_formally_frozen", "passed": True, "authorizing": True, "detail": "6 audited channels; 0 authorizing; 2 unresolved pairs frozen"},
            {"gate_id": "immutable_15_profile_report", "passed": True, "authorizing": True, "detail": CORE_REPORT_SHA256},
            {"gate_id": "exact_profile_split_12_2_1", "passed": True, "authorizing": True, "detail": "PACK11=12; PACK10_01=2; PACK10_03=1"},
            {"gate_id": "exact_changed_member_rows_30", "passed": True, "authorizing": True, "detail": "PACK11=27; PACK10_01=2; PACK10_03=1"},
            {"gate_id": "common_baseline_per_target", "passed": True, "authorizing": True, "detail": "one exact baseline identity per target"},
            {"gate_id": "disjoint_changed_members_within_target", "passed": not conflict_rows, "authorizing": True, "detail": f"conflicts={len(conflict_rows)}"},
            {"gate_id": "all_local_profile_payloads_checksum_valid", "passed": payload_pass_rows == EXPECTED_PROFILE_ROWS if verify_payloads else False, "authorizing": verify_payloads, "detail": f"passed={payload_pass_rows}; expected={EXPECTED_PROFILE_ROWS}"},
            {"gate_id": "production_composer_present", "passed": True, "authorizing": True, "detail": "quartet-composition-build and preflight source contract verified"},
            {"gate_id": "production_composer_accepts_current_profiles", "passed": False, "authorizing": False, "detail": "all 15 profiles remain runtime_validated=false"},
            {"gate_id": "separate_canary_all_entrypoint_present", "passed": False, "authorizing": False, "detail": "no bounded explicit Canary-all command exists"},
            {"gate_id": "canary_all_build_authorized", "passed": False, "authorizing": False, "detail": "stage 119 authorizes design and synthetic fixtures only"},
            {"gate_id": "activation_or_install_authorized", "passed": False, "authorizing": False, "detail": "no build, transaction or game write"},
        ]

        summary = {
            "type": "br_quartet_restoration_canary_composition_input_contract_evidence_summary",
            "format_version": 1,
            "tool_version": TOOL_VERSION,
            "status": "canary_input_contract_checksum_valid_production_composer_runtime_gate_confirmed_separate_canary_composer_not_implemented_no_write" if verify_payloads else "metadata_contract_valid_payload_hashing_not_run",
            "stage118_report_sha256": STAGE118_SHA256,
            "swordflash_branch_frozen": True,
            "core_profile_report_sha256": CORE_REPORT_SHA256,
            "profile_rows": len(profile_rows),
            "pack11_profile_rows": sum(1 for row in profile_rows if row["target_relative_path"] == "Data/PACK11.PAK"),
            "pack10_01_profile_rows": sum(1 for row in profile_rows if row["target_relative_path"] == "Data/PACK10_01.PAK"),
            "pack10_03_profile_rows": sum(1 for row in profile_rows if row["target_relative_path"] == "Data/PACK10_03.PAK"),
            "target_group_rows": len(group_rows),
            "changed_member_reference_rows": sum(parse_int(row["changed_member_count"]) for row in profile_rows),
            "unique_changed_member_rows": sum(parse_int(row["unique_changed_member_rows"]) for row in group_rows),
            "changed_member_conflict_rows": len(conflict_rows),
            "profile_payload_check_pass_rows": payload_pass_rows,
            "runtime_validated_profile_rows": 0,
            "production_composer_contract_check_rows": len(composer_contract_rows),
            "production_composer_present": True,
            "production_composer_runtime_validated_only": True,
            "production_composer_accepts_current_profiles": False,
            "expected_production_preflight_state_when_other_inputs_ready": "awaiting_runtime_validated_profiles",
            "canary_input_contract_ready": contract_ready,
            "separate_canary_all_entrypoint_present": False,
            "canary_all_composer_implemented": False,
            "composite_pak_written": False,
            "activation_authorized": False,
            "prototype_candidate_rows": 0,
            "skipped_rows": 0,
            "policy": {
                "profile_paks_read_for_size_and_sha256_only": bool(verify_payloads),
                "profile_paks_extracted": False,
                "baseline_paks_rehydrated": False,
                "production_composer_executed": False,
                "canary_composer_executed": False,
                "composite_pak_built": False,
                "runtime_validation_inferred": False,
                "runtime_validated_flags_modified": False,
                "core_modified": False,
                "registry_modified": False,
                "profiles_modified": False,
                "translation_modified": False,
                "legacy_dlc_modified": False,
                "installed_game_modified": False,
                "git_modified": False,
            },
            "next_action": "Implement only a separate synthetic Canary-all composer contract with tiny fixture archives first. It must explicitly select the 15 runtime-unvalidated inputs without mutating their manifests, build outside the production composition root, preserve one baseline per target, reject overlaps and produce no installation transaction.",
        }

        output_report_root.mkdir(parents=True, exist_ok=True)
        staging = Path(tempfile.mkdtemp(prefix=REPORT_DIR + ".", dir=output_report_root))
        output = staging / REPORT_DIR
        output.mkdir()
        write_tsv(
            output / "CANARY_RESTORATION_PROFILE_INPUTS.tsv",
            ["profile_id", "target_relative_path", "baseline_sha256", "baseline_size", "profile_sha256", "profile_size", "local_profile_path", "changed_member_count", "changed_members", "runtime_validated", "production_composition_role", "future_canary_role"],
            input_rows,
        )
        write_tsv(
            output / "CANARY_RESTORATION_PROFILE_PAYLOAD_CHECKS.tsv",
            ["profile_id", "target_relative_path", "local_profile_path", "expected_size", "observed_size", "expected_sha256", "observed_sha256", "payload_exists", "validation_status"],
            payload_checks,
        )
        write_tsv(
            output / "CANARY_RESTORATION_TARGET_GROUPS.tsv",
            ["target_relative_path", "profile_rows", "baseline_sha256", "baseline_size", "changed_member_reference_rows", "unique_changed_member_rows", "overlap_conflict_rows", "runtime_validated_profile_rows", "input_classification"],
            group_rows,
        )
        write_tsv(
            output / "CANARY_RESTORATION_CHANGED_MEMBER_CONFLICTS.tsv",
            ["target_relative_path", "changed_member", "owner_profile_count", "owner_profile_ids", "classification"],
            conflict_rows,
        )
        write_tsv(
            output / "PRODUCTION_COMPOSER_CONTRACT_CHECKS.tsv",
            ["check_id", "relative_path", "passed", "observed", "meaning"],
            composer_contract_rows,
        )
        write_tsv(
            output / "CANARY_RESTORATION_COMPOSITION_GATES.tsv",
            ["gate_id", "passed", "authorizing", "detail"],
            gates,
        )
        write_tsv(output / "CANARY_RESTORATION_SKIPPED.tsv", ["scope", "reason"], [])
        (output / "SUMMARY.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

        final_output = output_report_root / REPORT_DIR
        if final_output.exists():
            shutil.rmtree(final_output)
        os.replace(output, final_output)
        shutil.rmtree(staging, ignore_errors=True)

    archive: Path | None = None
    if create_archive:
        archive = output_report_root / REPORT_NAME
        make_archive(final_output, archive)
    return final_output, archive, summary


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path, default=PROJECT_ROOT_DEFAULT)
    parser.add_argument("--source-report-root", type=Path)
    parser.add_argument("--output-report-root", type=Path)
    parser.add_argument("--metadata-only", action="store_true", help="validate metadata without reading local profile PAK payloads")
    parser.add_argument("--no-archive", action="store_true")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        output, archive, summary = build_report(
            args.project_root,
            source_report_root=args.source_report_root,
            output_report_root=args.output_report_root,
            verify_payloads=not args.metadata_only,
            enforce_core_archive_hash=True,
            create_archive=not args.no_archive,
        )
    except CanaryContractError as exc:
        print(f"[canary-contract] ERROR: {exc}", file=sys.stderr)
        return 1
    progress(f"report directory: {output}")
    if archive is not None:
        progress(f"report archive: {archive}")
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
