#!/usr/bin/env python3
"""Build a metadata-only dry-BKN integration handoff for the core workstream.

The handoff consumes the validated two-archive transaction contract and the
validated canonical BR1 source contract.  It binds the exact target paths,
baseline hashes, candidate hashes, transaction requirements, operator gates,
runtime observations and rollback expectations into one immutable report.

This stage does not prepare or commit a real transaction, copy candidate PAKs,
modify core, install game files, authorize a profile or claim runtime success.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Iterable

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import br_dlc_bkn_dry_transaction_contract_tool as TX
import br_dlc_br1_canonical_source_tool as CANON

TOOL_VERSION = "0.0.30"
FORMAT_VERSION = 1
REPORT_DIR_NAME = "bkn_dry_core_integration_handoff_evidence"
REPORT_ARCHIVE_NAME = "BR_quartet_legacy_dlc_bkn_dry_core_integration_handoff_evidence.tar.zst"
FORBIDDEN_REPORT_SUFFIXES = TX.FORBIDDEN_REPORT_SUFFIXES
EXPECTED_TARGETS = ("Data/PACK10_02.PAK", "Data/PACK12.PAK")


class BknDryCoreHandoffError(RuntimeError):
    pass


def bool_text(value: Any) -> Any:
    if isinstance(value, bool):
        return "true" if value else "false"
    if value is None:
        return ""
    if isinstance(value, (dict, list, tuple, set)):
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return value


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def write_tsv(path: Path, fields: Iterable[str], rows: Iterable[dict[str, Any]]) -> None:
    fieldnames = list(fields)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, delimiter="\t", lineterminator="\n", extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({field: bool_text(row.get(field, "")) for field in fieldnames})


def read_tsv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(4 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def report_manifest(root: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.name == "REPORT_MANIFEST.json":
            continue
        if {suffix.casefold() for suffix in path.suffixes} & FORBIDDEN_REPORT_SUFFIXES:
            raise BknDryCoreHandoffError(f"raw asset-like file in report: {path}")
        rows.append({
            "path": path.relative_to(root).as_posix(),
            "size": path.stat().st_size,
            "sha256": sha256_file(path),
        })
    return rows


def make_archive(root: Path, output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(output.name + ".tmp")
    temporary.unlink(missing_ok=True)
    result = subprocess.run(
        ["tar", "--zstd", "-cf", str(temporary), "-C", str(root.parent), root.name],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    if result.returncode != 0:
        temporary.unlink(missing_ok=True)
        raise BknDryCoreHandoffError(f"cannot create report archive: {result.stderr.strip()}")
    os.replace(temporary, output)


def _load_and_validate_inputs(transaction_root: Path, canonical_root: Path) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
    tx_summary = TX.validate_report(transaction_root)
    canonical_summary = CANON.validate_report(canonical_root)
    request = json.loads((transaction_root / "DLC_BKN_DRY_CORE_TARGET_REQUEST.json").read_text(encoding="utf-8"))
    canonical_contract = json.loads((canonical_root / "DLC_BR1_CANONICAL_SOURCE_CONSUMER_CONTRACT.json").read_text(encoding="utf-8"))

    tx_policy = tx_summary.get("policy", {})
    if tx_policy.get("core_integration_request_ready") is not True:
        raise BknDryCoreHandoffError("transaction request is not ready for core integration")
    if any(tx_policy.get(key) is not False for key in (
        "real_transaction_prepared", "real_transaction_committed", "candidate_installed",
        "profile_build_allowed", "profile_registered", "runtime_validated", "wet_variant_included",
    )):
        raise BknDryCoreHandoffError("transaction report is not fail-closed")

    canonical_policy = canonical_summary.get("policy", {})
    if canonical_policy.get("canonical_source_contract_ready") is not True:
        raise BknDryCoreHandoffError("canonical source contract is not ready")
    if canonical_summary.get("official_overlay_rows_resolved") != 39:
        raise BknDryCoreHandoffError("canonical overlay resolution is incomplete")
    if canonical_summary.get("active_operational_underscore_dependencies") != 0:
        raise BknDryCoreHandoffError("active underscore dependency remains")
    if canonical_summary.get("dry_bkn_transaction_contract_still_valid") is not True:
        raise BknDryCoreHandoffError("canonical provenance invalidated the dry-BKN transaction")
    if canonical_summary.get("underscore_files_required_for_future_workflow") is not False:
        raise BknDryCoreHandoffError("future workflow still requires underscore archives")

    auth = request.get("authorization", {})
    if auth.get("core_integration_request_ready") is not True or any(auth.get(key) is not False for key in (
        "real_transaction_prepare_enabled", "commit_enabled", "candidate_installed",
        "profile_build_allowed", "profile_registered", "runtime_validated", "wet_variant_included",
    )):
        raise BknDryCoreHandoffError("transaction request authorization is not fail-closed")

    files = request.get("transaction_files", [])
    if len(files) != 2 or tuple(sorted(row.get("relative_path", "") for row in files)) != tuple(sorted(EXPECTED_TARGETS)):
        raise BknDryCoreHandoffError("transaction request must contain exactly PACK10_02 and PACK12")
    if len({row.get("relative_path") for row in files}) != 2:
        raise BknDryCoreHandoffError("duplicate transaction target")
    for row in files:
        if not row.get("baseline_sha256") or not row.get("candidate_sha256"):
            raise BknDryCoreHandoffError(f"missing transaction hash: {row.get('relative_path')}")
        if int(row.get("baseline_size", 0)) <= 0 or int(row.get("candidate_size", 0)) <= 0:
            raise BknDryCoreHandoffError(f"invalid transaction size: {row.get('relative_path')}")

    rules = canonical_contract.get("rules", {})
    if rules.get("underscore_archives_required") is not False or rules.get("old_modified_hash_may_be_selected") is not False:
        raise BknDryCoreHandoffError("canonical contract permits an untrusted source")
    if rules.get("future_payload_extraction_requires_registry_hash_gate") is not True:
        raise BknDryCoreHandoffError("canonical registry hash gate is missing")
    return tx_summary, canonical_summary, request, canonical_contract


def build_handoff(transaction_root: Path, canonical_root: Path, output_root: Path) -> tuple[Path, dict[str, Any]]:
    transaction_root = transaction_root.resolve()
    canonical_root = canonical_root.resolve()
    output_root = output_root.resolve()
    tx_summary, canonical_summary, request, canonical_contract = _load_and_validate_inputs(transaction_root, canonical_root)

    if output_root.exists():
        for child in output_root.iterdir():
            if child.is_dir():
                import shutil
                shutil.rmtree(child)
            else:
                child.unlink()
    output_root.mkdir(parents=True, exist_ok=True)

    transaction_files = sorted(request["transaction_files"], key=lambda row: row["relative_path"].casefold())
    target_rows = []
    for index, row in enumerate(transaction_files, start=1):
        target_rows.append({
            "transaction_order": index,
            "relative_path": row["relative_path"],
            "role": row["role"],
            "baseline_size": row["baseline_size"],
            "baseline_sha256": row["baseline_sha256"],
            "candidate_relative_path": row["candidate_relative_path"],
            "candidate_size": row["candidate_size"],
            "candidate_sha256": row["candidate_sha256"],
            "independent_install_allowed": False,
            "real_prepare_enabled": False,
            "real_commit_enabled": False,
        })
    write_tsv(
        output_root / "DLC_BKN_DRY_CORE_INTEGRATION_TARGETS.tsv",
        (
            "transaction_order", "relative_path", "role", "baseline_size", "baseline_sha256",
            "candidate_relative_path", "candidate_size", "candidate_sha256",
            "independent_install_allowed", "real_prepare_enabled", "real_commit_enabled",
        ),
        target_rows,
    )

    prerequisite_rows = [
        {
            "prerequisite": "two_archive_transaction_contract",
            "source": "bkn_dry_transaction_contract_evidence/SUMMARY.json",
            "expected_state": "ready_core_integration_not_prepared_not_installed",
            "observed_state": tx_summary["status"],
            "validation_status": "passed",
        },
        {
            "prerequisite": "canonical_br1_source_contract",
            "source": "br1_canonical_source_contract_evidence/SUMMARY.json",
            "expected_state": "canonical_official_source_ready_no_underscore_dependency",
            "observed_state": canonical_summary["status"],
            "validation_status": "passed",
        },
        {
            "prerequisite": "official_overlay_resolution",
            "source": "DLC_BR1_OFFICIAL_OVERLAY_RESOLUTION.tsv",
            "expected_state": "39_rows_resolved",
            "observed_state": canonical_summary["official_overlay_rows_resolved"],
            "validation_status": "passed",
        },
        {
            "prerequisite": "dry_bkn_provenance_continuity",
            "source": "DLC_BR1_DRY_BKN_CONTINUITY.tsv",
            "expected_state": "transaction_contract_still_valid",
            "observed_state": canonical_summary["dry_bkn_transaction_contract_still_valid"],
            "validation_status": "passed",
        },
        {
            "prerequisite": "runtime_and_profile_authorization",
            "source": "combined_fail_closed_policy",
            "expected_state": "not_granted",
            "observed_state": "not_granted",
            "validation_status": "passed",
        },
    ]
    write_tsv(
        output_root / "DLC_BKN_DRY_CORE_INTEGRATION_PREREQUISITES.tsv",
        ("prerequisite", "source", "expected_state", "observed_state", "validation_status"),
        prerequisite_rows,
    )

    operator_gates = [
        {
            "gate_order": 1,
            "gate": "core_request_wiring",
            "required_state": "one transaction journal consumes both targets",
            "current_state": "handoff_ready_not_wired",
            "authorization_required": False,
            "blocks_prepare": True,
            "blocks_commit": True,
        },
        {
            "gate_order": 2,
            "gate": "explicit_real_prepare_authorization",
            "required_state": "operator explicitly authorizes prepare against installed Quartet",
            "current_state": "not_authorized",
            "authorization_required": True,
            "blocks_prepare": True,
            "blocks_commit": True,
        },
        {
            "gate_order": 3,
            "gate": "prepared_journal_review",
            "required_state": "both baseline, staged and backup hashes reviewed before commit",
            "current_state": "not_prepared",
            "authorization_required": True,
            "blocks_prepare": False,
            "blocks_commit": True,
        },
        {
            "gate_order": 4,
            "gate": "explicit_commit_authorization",
            "required_state": "operator explicitly authorizes one two-file commit",
            "current_state": "not_authorized",
            "authorization_required": True,
            "blocks_prepare": False,
            "blocks_commit": True,
        },
        {
            "gate_order": 5,
            "gate": "controlled_runtime_observation",
            "required_state": "runtime result recorded after reversible commit",
            "current_state": "not_run",
            "authorization_required": True,
            "blocks_prepare": False,
            "blocks_commit": False,
        },
    ]
    write_tsv(
        output_root / "DLC_BKN_DRY_OPERATOR_GATES.tsv",
        ("gate_order", "gate", "required_state", "current_state", "authorization_required", "blocks_prepare", "blocks_commit"),
        operator_gates,
    )

    runtime_rows = [
        {
            "observation_order": 1,
            "observation": "game_boot",
            "expected_for_success": "Quartet reaches title and load flow without archive error",
            "failure_action": "stop test and execute guarded rollback",
            "claims_owner_ui_binding": False,
        },
        {
            "observation_order": 2,
            "observation": "save_load",
            "expected_for_success": "existing save loads without crash",
            "failure_action": "stop test and execute guarded rollback",
            "claims_owner_ui_binding": False,
        },
        {
            "observation_order": 3,
            "observation": "dry_bkn_availability",
            "expected_for_success": "PC00 dry BKN can be selected or otherwise reached through the existing costume system",
            "failure_action": "record unavailable path; do not infer missing asset failure",
            "claims_owner_ui_binding": True,
        },
        {
            "observation_order": 4,
            "observation": "dry_bkn_render",
            "expected_for_success": "model and external texture render without SCL fallback, corruption or missing-resource substitution",
            "failure_action": "capture symptom and execute guarded rollback",
            "claims_owner_ui_binding": False,
        },
        {
            "observation_order": 5,
            "observation": "wet_record_unchanged",
            "expected_for_success": "wet BKN remains outside scope and no wet conversion is claimed",
            "failure_action": "treat any wet behavior as incidental and unsupported",
            "claims_owner_ui_binding": False,
        },
        {
            "observation_order": 6,
            "observation": "icon_or_thumbnail",
            "expected_for_success": "record actual UI presentation without assuming a dedicated owner slot",
            "failure_action": "keep UI ownership unresolved; do not patch isolated numeric candidates",
            "claims_owner_ui_binding": True,
        },
    ]
    write_tsv(
        output_root / "DLC_BKN_DRY_RUNTIME_OBSERVATION_PLAN.tsv",
        ("observation_order", "observation", "expected_for_success", "failure_action", "claims_owner_ui_binding"),
        runtime_rows,
    )

    rollback_rows = [
        {
            "rollback_order": 1,
            "target": "Data/PACK12.PAK",
            "precondition": "installed target still matches desired candidate hash",
            "restore_to_sha256": next(row["baseline_sha256"] for row in transaction_files if row["relative_path"] == "Data/PACK12.PAK"),
            "conflict_behavior": "refuse overwrite and preserve external change",
        },
        {
            "rollback_order": 2,
            "target": "Data/PACK10_02.PAK",
            "precondition": "installed target still matches desired candidate hash",
            "restore_to_sha256": next(row["baseline_sha256"] for row in transaction_files if row["relative_path"] == "Data/PACK10_02.PAK"),
            "conflict_behavior": "refuse overwrite and preserve external change",
        },
    ]
    write_tsv(
        output_root / "DLC_BKN_DRY_ROLLBACK_CONTRACT.tsv",
        ("rollback_order", "target", "precondition", "restore_to_sha256", "conflict_behavior"),
        rollback_rows,
    )

    gaps = [
        {
            "dependency": "core_two_archive_request_wiring",
            "status": "handoff_ready_not_integrated",
            "blocks_prepare": True,
            "blocks_commit": True,
            "required_action": "core must consume both targets in one journal; this workstream does not modify core",
        },
        {
            "dependency": "explicit_operator_authorization",
            "status": "not_granted",
            "blocks_prepare": True,
            "blocks_commit": True,
            "required_action": "obtain separate explicit approval before real prepare or commit",
        },
        {
            "dependency": "runtime_availability_and_render_validation",
            "status": "not_run",
            "blocks_prepare": False,
            "blocks_commit": False,
            "required_action": "perform only after reversible core integration and explicit approval",
        },
        {
            "dependency": "owner_ui_icon_or_thumbnail",
            "status": "unresolved",
            "blocks_prepare": False,
            "blocks_commit": False,
            "required_action": "observe runtime presentation; do not infer ownership from prior isolated UI integers",
        },
        {
            "dependency": "wet_bkn_conversion",
            "status": "out_of_scope_conversion_blocked",
            "blocks_prepare": False,
            "blocks_commit": False,
            "required_action": "keep wet variant excluded from the dry-only transaction",
        },
    ]
    write_tsv(
        output_root / "DLC_BKN_DRY_CORE_INTEGRATION_GAPS.tsv",
        ("dependency", "status", "blocks_prepare", "blocks_commit", "required_action"),
        gaps,
    )

    handoff = {
        "type": "br_quartet_legacy_dlc_dry_bkn_core_integration_handoff",
        "format_version": FORMAT_VERSION,
        "handoff_version": TOOL_VERSION,
        "handoff_id": "quartet_legacy_dlc_costume_pc00_bkn_dry",
        "workstream_id": "quartet_legacy_dlc",
        "target_id": request["target_id"],
        "content_id": request["content_id"],
        "transaction_request_type": request["type"],
        "transaction_files": transaction_files,
        "core_contract": request["core_contract"],
        "canonical_source_contract": {
            "resolver_id": canonical_contract["resolver_id"],
            "canonical_archive": canonical_contract["canonical_archive"],
            "canonical_archive_sha1": canonical_contract["canonical_archive_sha1"],
            "official_overlay_rows_resolved": canonical_summary["official_overlay_rows_resolved"],
            "underscore_archives_required": False,
            "dry_bkn_transaction_contract_still_valid": True,
        },
        "required_core_integration": {
            "single_journal_for_both_files": True,
            "prepare_both_or_prepare_neither": True,
            "commit_both_through_one_transaction": True,
            "reverse_order_hash_guarded_rollback": True,
            "independent_archive_install_forbidden": True,
            "explicit_prepare_authorization_required": True,
            "explicit_commit_authorization_required": True,
        },
        "authorization": {
            "core_handoff_ready": True,
            "core_modified": False,
            "real_transaction_prepare_enabled": False,
            "real_transaction_commit_enabled": False,
            "candidate_installed": False,
            "profile_build_allowed": False,
            "profile_registered": False,
            "runtime_validated": False,
            "wet_variant_included": False,
            "game_modified": False,
            "git_modified": False,
        },
        "next_owner": "core_orchestrator",
        "next_action": "wire this immutable two-file request into the core transaction planner while leaving prepare and commit disabled until explicit operator approval",
    }
    write_json(output_root / "DLC_BKN_DRY_CORE_INTEGRATION_HANDOFF.json", handoff)

    summary = {
        "type": "br_quartet_legacy_dlc_bkn_dry_core_integration_handoff_summary",
        "format_version": FORMAT_VERSION,
        "tool_version": TOOL_VERSION,
        "status": "metadata_only_core_handoff_ready_not_wired_not_prepared_not_committed_not_installed",
        "content_id": request["content_id"],
        "target_id": request["target_id"],
        "transaction_target_count": len(transaction_files),
        "canonical_overlay_rows_resolved": canonical_summary["official_overlay_rows_resolved"],
        "active_operational_underscore_dependencies": canonical_summary["active_operational_underscore_dependencies"],
        "operator_gate_count": len(operator_gates),
        "runtime_observation_count": len(runtime_rows),
        "rollback_target_count": len(rollback_rows),
        "blocking_integration_gaps": sum(1 for row in gaps if row["blocks_prepare"] or row["blocks_commit"]),
        "findings": [
            "the canonical BR1 source contract resolves all thirty-nine wet-DLC overlays and no longer requires underscore archives",
            "the dry PC00 BKN PACK10_02 and PACK12 candidates remain checksum-bound to one two-file transaction request",
            "the core integration handoff defines exact targets, operator gates, runtime observations and reverse rollback expectations",
            "no real transaction was prepared or committed and no game or core file was modified",
        ],
        "next_action": handoff["next_action"],
        "policy": {
            "core_handoff_ready": True,
            "core_modified": False,
            "real_transaction_prepared": False,
            "real_transaction_committed": False,
            "candidate_installed": False,
            "profile_build_allowed": False,
            "profile_registered": False,
            "runtime_validated": False,
            "wet_variant_included": False,
            "game_modified": False,
            "git_modified": False,
            "translation_modified": False,
            "restoration_modified": False,
            "raw_assets_exported_in_report": False,
            "underscore_archives_required": False,
        },
    }
    write_json(output_root / "SUMMARY.json", summary)
    write_json(output_root / "REPORT_MANIFEST.json", {"type": "br_report_manifest", "format_version": 1, "files": report_manifest(output_root)})
    validate_report(output_root)
    archive = output_root.parent / REPORT_ARCHIVE_NAME
    make_archive(output_root, archive)
    return archive, summary


def validate_report(report_root: Path) -> dict[str, Any]:
    report_root = report_root.resolve()
    required = (
        "DLC_BKN_DRY_CORE_INTEGRATION_TARGETS.tsv",
        "DLC_BKN_DRY_CORE_INTEGRATION_PREREQUISITES.tsv",
        "DLC_BKN_DRY_OPERATOR_GATES.tsv",
        "DLC_BKN_DRY_RUNTIME_OBSERVATION_PLAN.tsv",
        "DLC_BKN_DRY_ROLLBACK_CONTRACT.tsv",
        "DLC_BKN_DRY_CORE_INTEGRATION_GAPS.tsv",
        "DLC_BKN_DRY_CORE_INTEGRATION_HANDOFF.json",
        "SUMMARY.json",
        "REPORT_MANIFEST.json",
    )
    for name in required:
        if not (report_root / name).is_file():
            raise BknDryCoreHandoffError(f"missing report file: {name}")

    summary = json.loads((report_root / "SUMMARY.json").read_text(encoding="utf-8"))
    if summary.get("type") != "br_quartet_legacy_dlc_bkn_dry_core_integration_handoff_summary" or summary.get("tool_version") != TOOL_VERSION:
        raise BknDryCoreHandoffError("invalid core handoff summary")
    if summary.get("status") != "metadata_only_core_handoff_ready_not_wired_not_prepared_not_committed_not_installed":
        raise BknDryCoreHandoffError("unexpected core handoff status")
    if summary.get("transaction_target_count") != 2 or summary.get("rollback_target_count") != 2:
        raise BknDryCoreHandoffError("core handoff target count invalid")
    if summary.get("canonical_overlay_rows_resolved") != 39 or summary.get("active_operational_underscore_dependencies") != 0:
        raise BknDryCoreHandoffError("canonical provenance state invalid")

    policy = summary.get("policy", {})
    if policy.get("core_handoff_ready") is not True or policy.get("underscore_archives_required") is not False:
        raise BknDryCoreHandoffError("core handoff readiness flags invalid")
    false_keys = (
        "core_modified", "real_transaction_prepared", "real_transaction_committed", "candidate_installed",
        "profile_build_allowed", "profile_registered", "runtime_validated", "wet_variant_included",
        "game_modified", "git_modified", "translation_modified", "restoration_modified", "raw_assets_exported_in_report",
    )
    if any(policy.get(key) is not False for key in false_keys):
        raise BknDryCoreHandoffError("core handoff report violates fail-closed policy")

    targets = read_tsv(report_root / "DLC_BKN_DRY_CORE_INTEGRATION_TARGETS.tsv")
    if len(targets) != 2 or {row.get("relative_path") for row in targets} != set(EXPECTED_TARGETS):
        raise BknDryCoreHandoffError("core handoff target set invalid")
    if any(row.get("independent_install_allowed") != "false" or row.get("real_prepare_enabled") != "false" or row.get("real_commit_enabled") != "false" for row in targets):
        raise BknDryCoreHandoffError("target row authorizes a forbidden operation")

    prerequisites = read_tsv(report_root / "DLC_BKN_DRY_CORE_INTEGRATION_PREREQUISITES.tsv")
    if len(prerequisites) < 5 or any(row.get("validation_status") != "passed" for row in prerequisites):
        raise BknDryCoreHandoffError("integration prerequisites incomplete")
    gates = read_tsv(report_root / "DLC_BKN_DRY_OPERATOR_GATES.tsv")
    if len(gates) < 5 or not any(row.get("blocks_prepare") == "true" for row in gates) or not any(row.get("blocks_commit") == "true" for row in gates):
        raise BknDryCoreHandoffError("operator gates incomplete")
    runtime = read_tsv(report_root / "DLC_BKN_DRY_RUNTIME_OBSERVATION_PLAN.tsv")
    if len(runtime) < 6:
        raise BknDryCoreHandoffError("runtime observation plan incomplete")
    rollback = read_tsv(report_root / "DLC_BKN_DRY_ROLLBACK_CONTRACT.tsv")
    if len(rollback) != 2 or [row.get("target") for row in rollback] != ["Data/PACK12.PAK", "Data/PACK10_02.PAK"]:
        raise BknDryCoreHandoffError("rollback order is not reverse transaction order")
    gaps = read_tsv(report_root / "DLC_BKN_DRY_CORE_INTEGRATION_GAPS.tsv")
    if len(gaps) < 5 or not any(row.get("blocks_prepare") == "true" for row in gaps):
        raise BknDryCoreHandoffError("blocking integration gaps missing")

    handoff = json.loads((report_root / "DLC_BKN_DRY_CORE_INTEGRATION_HANDOFF.json").read_text(encoding="utf-8"))
    if handoff.get("type") != "br_quartet_legacy_dlc_dry_bkn_core_integration_handoff":
        raise BknDryCoreHandoffError("invalid handoff type")
    if {row.get("relative_path") for row in handoff.get("transaction_files", [])} != set(EXPECTED_TARGETS):
        raise BknDryCoreHandoffError("handoff transaction file set invalid")
    auth = handoff.get("authorization", {})
    if auth.get("core_handoff_ready") is not True or any(auth.get(key) is not False for key in (
        "core_modified", "real_transaction_prepare_enabled", "real_transaction_commit_enabled",
        "candidate_installed", "profile_build_allowed", "profile_registered", "runtime_validated",
        "wet_variant_included", "game_modified", "git_modified",
    )):
        raise BknDryCoreHandoffError("handoff authorization is not fail-closed")

    manifest = json.loads((report_root / "REPORT_MANIFEST.json").read_text(encoding="utf-8"))
    for row in manifest.get("files", []):
        path = report_root / row["path"]
        if not path.is_file() or path.stat().st_size != row["size"] or sha256_file(path) != row["sha256"]:
            raise BknDryCoreHandoffError(f"report manifest mismatch: {row.get('path')}")
        if {suffix.casefold() for suffix in path.suffixes} & FORBIDDEN_REPORT_SUFFIXES:
            raise BknDryCoreHandoffError(f"raw asset in report: {path}")
    return summary


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    build = sub.add_parser("build-handoff")
    build.add_argument("--project-root", type=Path, required=True)
    build.add_argument("--reports-root", type=Path)
    build.add_argument("--transaction-root", type=Path)
    build.add_argument("--canonical-root", type=Path)
    build.add_argument("--output-root", type=Path)
    validate = sub.add_parser("validate-report")
    validate.add_argument("--report-root", type=Path, required=True)
    bundle = sub.add_parser("bundle-report")
    bundle.add_argument("--report-root", type=Path, required=True)
    bundle.add_argument("--output", type=Path, required=True)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        if args.command == "build-handoff":
            project = args.project_root.resolve()
            reports = (args.reports_root or project / ".local/reports/quartet_legacy_dlc").resolve()
            transaction = (args.transaction_root or reports / TX.REPORT_DIR_NAME).resolve()
            canonical = (args.canonical_root or reports / CANON.REPORT_DIR_NAME).resolve()
            output = (args.output_root or reports / REPORT_DIR_NAME).resolve()
            build_handoff(transaction, canonical, output)
        elif args.command == "validate-report":
            print(json.dumps(validate_report(args.report_root), ensure_ascii=False, sort_keys=True))
        elif args.command == "bundle-report":
            validate_report(args.report_root)
            make_archive(args.report_root.resolve(), args.output.resolve())
        else:
            raise BknDryCoreHandoffError("unsupported command")
    except (BknDryCoreHandoffError, TX.BknDryTransactionContractError, CANON.CanonicalSourceContractError, OSError, subprocess.TimeoutExpired) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
