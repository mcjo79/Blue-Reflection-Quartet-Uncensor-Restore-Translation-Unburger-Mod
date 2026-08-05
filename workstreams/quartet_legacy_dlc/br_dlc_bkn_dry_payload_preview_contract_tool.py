#!/usr/bin/env python3
"""Build a metadata-only core payload-preview integration contract for dry BKN.

The stage consumes the validated stage-67 dry-BKN core handoff and audits the
current core module catalog plus payloadpreview implementation.  It emits an
immutable patch request describing how core can expose the two verified local
PAK candidates in preview-only mode without using the translation repack report.

It never edits core, prepares or commits a transaction, copies PAKs, installs
game files, authorizes a profile, includes wet BKN, or modifies Git state.
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

import br_dlc_bkn_dry_core_handoff_tool as HANDOFF

TOOL_VERSION = "0.0.31"
FORMAT_VERSION = 1
REPORT_DIR_NAME = "bkn_dry_payload_preview_contract_evidence"
REPORT_ARCHIVE_NAME = "BR_quartet_legacy_dlc_bkn_dry_payload_preview_contract_evidence.tar.zst"
FORBIDDEN_REPORT_SUFFIXES = HANDOFF.FORBIDDEN_REPORT_SUFFIXES
EXPECTED_TARGETS = ("Data/PACK10_02.PAK", "Data/PACK12.PAK")
EXPECTED_SOURCE_KIND = "validated_quartet_legacy_dlc_handoff"

CORE_FILES = (
    "Blue_Reflection_Patcher/internal/plan/catalog/catalog.json",
    "Blue_Reflection_Patcher/internal/plan/payloadpreview/catalog.json",
    "Blue_Reflection_Patcher/internal/plan/payloadpreview/catalog.go",
    "Blue_Reflection_Patcher/internal/plan/payloadpreview/preview.go",
    "Blue_Reflection_Patcher/internal/plan/payloadpreview/preview_test.go",
    "Blue_Reflection_Patcher/cmd/brpatcher/payload_preview_cli.go",
)


class BknDryPayloadPreviewContractError(RuntimeError):
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
            raise BknDryPayloadPreviewContractError(f"raw asset-like file in report: {path}")
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
        raise BknDryPayloadPreviewContractError(f"cannot create report archive: {result.stderr.strip()}")
    os.replace(temporary, output)


def _load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise BknDryPayloadPreviewContractError(f"cannot read JSON {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise BknDryPayloadPreviewContractError(f"JSON root is not an object: {path}")
    return value


def _one(rows: list[dict[str, Any]], *, field: str, value: str, label: str) -> dict[str, Any]:
    matches = [row for row in rows if row.get(field) == value]
    if len(matches) != 1:
        raise BknDryPayloadPreviewContractError(f"expected exactly one {label}, found {len(matches)}")
    return matches[0]


def _load_handoff(handoff_root: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    summary = HANDOFF.validate_report(handoff_root)
    handoff = _load_json(handoff_root / "DLC_BKN_DRY_CORE_INTEGRATION_HANDOFF.json")
    if summary.get("status") != "metadata_only_core_handoff_ready_not_wired_not_prepared_not_committed_not_installed":
        raise BknDryPayloadPreviewContractError("unexpected handoff status")
    policy = summary.get("policy", {})
    if policy.get("core_handoff_ready") is not True:
        raise BknDryPayloadPreviewContractError("core handoff is not ready")
    if any(policy.get(key) is not False for key in (
        "core_modified", "real_transaction_prepared", "real_transaction_committed",
        "candidate_installed", "profile_build_allowed", "profile_registered",
        "runtime_validated", "wet_variant_included", "game_modified", "git_modified",
    )):
        raise BknDryPayloadPreviewContractError("handoff policy is not fail-closed")
    files = handoff.get("transaction_files", [])
    if len(files) != 2 or {row.get("relative_path") for row in files} != set(EXPECTED_TARGETS):
        raise BknDryPayloadPreviewContractError("handoff must contain exactly PACK10_02 and PACK12")
    return summary, handoff


def _audit_core(project_root: Path) -> tuple[list[dict[str, Any]], dict[str, Any], dict[str, Any], dict[str, bool]]:
    for relative in CORE_FILES:
        path = project_root / relative
        if not path.is_file():
            raise BknDryPayloadPreviewContractError(f"missing core file: {relative}")

    plan_catalog_path = project_root / CORE_FILES[0]
    preview_catalog_path = project_root / CORE_FILES[1]
    plan_catalog = _load_json(plan_catalog_path)
    preview_catalog = _load_json(preview_catalog_path)

    module = _one(plan_catalog.get("modules", []), field="module_id", value="quartet_legacy_dlc", label="core module catalog row")
    if module.get("selectable") is not True:
        raise BknDryPayloadPreviewContractError("quartet_legacy_dlc is not selectable")
    if module.get("supported_targets") != ["blue_reflection_quartet"]:
        raise BknDryPayloadPreviewContractError("unexpected quartet_legacy_dlc target set")
    if module.get("default_targets") not in ([], None):
        raise BknDryPayloadPreviewContractError("quartet_legacy_dlc must remain opt-in")
    if "blue_reflection_original" not in module.get("source_targets", []):
        raise BknDryPayloadPreviewContractError("quartet_legacy_dlc source target is missing")

    module_targets = preview_catalog.get("module_targets", [])
    matches = [row for row in module_targets if row.get("module_id") == "quartet_legacy_dlc" and row.get("target_id") == "blue_reflection_quartet"]
    if len(matches) != 1:
        raise BknDryPayloadPreviewContractError(f"expected one payload-preview legacy DLC row, found {len(matches)}")
    preview_spec = matches[0]
    current_artifacts = [row.get("relative_path") for row in preview_spec.get("artifacts", [])]
    current_state = "unknown"
    if preview_spec.get("connection_status") == "pending_adapter" and current_artifacts == []:
        current_state = "pending_adapter_no_artifacts"
    elif preview_spec.get("connection_status") == "connected_preview_only" and set(current_artifacts) == set(EXPECTED_TARGETS):
        current_state = "catalog_declares_exact_artifacts_requires_resolver_audit"
    else:
        raise BknDryPayloadPreviewContractError("unexpected quartet_legacy_dlc payload-preview catalog state")

    preview_source = (project_root / CORE_FILES[3]).read_text(encoding="utf-8")
    catalog_source = (project_root / CORE_FILES[2]).read_text(encoding="utf-8")
    cli_source = (project_root / CORE_FILES[5]).read_text(encoding="utf-8")
    features = {
        "catalog_connected_requires_artifacts": "connected_preview_only" in catalog_source and "len(spec.Artifacts) == 0" in catalog_source,
        "preview_loads_translation_repack_report": "loadRepackReport(" in preview_source,
        "artifact_inspector_requires_repack_report": "report repackReport" in preview_source and "findReportEntry(report" in preview_source,
        "source_kind_specific_resolver_present": "switch spec.SourceKind" in preview_source or "switch module.SourceKind" in preview_source or "validated_quartet_legacy_dlc_handoff" in preview_source,
        "preview_commit_disabled": "CommitEnabled: false" in preview_source,
        "preview_policy_says_no_transaction": "no transaction is prepared or committed" in preview_source,
        "cli_says_preview_only": "Preview only:" in cli_source and "no transaction was prepared" in cli_source,
    }
    if not features["preview_commit_disabled"] or not features["preview_policy_says_no_transaction"]:
        raise BknDryPayloadPreviewContractError("payload preview is not visibly fail-closed")

    file_rows = []
    for relative in CORE_FILES:
        path = project_root / relative
        file_rows.append({
            "path": relative,
            "size": path.stat().st_size,
            "sha256": sha256_file(path),
            "role": {
                CORE_FILES[0]: "module_selection_catalog",
                CORE_FILES[1]: "payload_preview_catalog",
                CORE_FILES[2]: "payload_preview_catalog_validator",
                CORE_FILES[3]: "payload_preview_builder",
                CORE_FILES[4]: "payload_preview_unit_tests",
                CORE_FILES[5]: "payload_preview_cli",
            }[relative],
            "modified_by_stage": False,
        })
    return file_rows, module, {**preview_spec, "observed_state": current_state}, features


def build_contract(project_root: Path, handoff_root: Path, output_root: Path) -> tuple[Path, dict[str, Any]]:
    project_root = project_root.resolve()
    handoff_root = handoff_root.resolve()
    output_root = output_root.resolve()
    handoff_summary, handoff = _load_handoff(handoff_root)
    core_rows, module, preview_spec, features = _audit_core(project_root)

    if output_root.exists():
        import shutil
        shutil.rmtree(output_root)
    output_root.mkdir(parents=True, exist_ok=True)

    write_tsv(
        output_root / "DLC_BKN_DRY_CORE_PAYLOAD_PREVIEW_FILES.tsv",
        ("path", "role", "size", "sha256", "modified_by_stage"),
        core_rows,
    )

    catalog_rows = [
        {
            "catalog": "module_selection",
            "module_id": module.get("module_id"),
            "target_id": "blue_reflection_quartet",
            "source_kind": "selected_first_game_installation",
            "connection_status": "selectable_opt_in",
            "artifact_count": 0,
            "observed_state": "module_declared_and_opt_in",
            "required_change": "none",
        },
        {
            "catalog": "payload_preview",
            "module_id": preview_spec.get("module_id"),
            "target_id": preview_spec.get("target_id"),
            "source_kind": preview_spec.get("source_kind", ""),
            "connection_status": preview_spec.get("connection_status", ""),
            "artifact_count": len(preview_spec.get("artifacts", [])),
            "observed_state": preview_spec.get("observed_state"),
            "required_change": "declare the exact two handoff artifacts and use a dedicated handoff-backed resolver",
        },
    ]
    write_tsv(
        output_root / "DLC_BKN_DRY_CORE_CATALOG_AUDIT.tsv",
        ("catalog", "module_id", "target_id", "source_kind", "connection_status", "artifact_count", "observed_state", "required_change"),
        catalog_rows,
    )

    callsite_rows = [
        {
            "callsite": "payloadpreview.LoadCatalog",
            "path": CORE_FILES[2],
            "observed": features["catalog_connected_requires_artifacts"],
            "meaning": "connected preview mappings must declare at least one artifact",
            "required_core_action": "retain this invariant for the two exact DLC targets",
        },
        {
            "callsite": "payloadpreview.Build.loadRepackReport",
            "path": CORE_FILES[3],
            "observed": features["preview_loads_translation_repack_report"],
            "meaning": "the current builder loads the translation repack report before module-specific resolution",
            "required_core_action": "allow the DLC source-kind resolver to load the validated stage-67 handoff instead",
        },
        {
            "callsite": "payloadpreview.inspectArtifact",
            "path": CORE_FILES[3],
            "observed": features["artifact_inspector_requires_repack_report"],
            "meaning": "the current artifact verifier is coupled to translation repack entries",
            "required_core_action": "add a handoff-backed verifier using candidate and baseline size/SHA-256",
        },
        {
            "callsite": "payloadpreview.Build.source_kind_dispatch",
            "path": CORE_FILES[3],
            "observed": features["source_kind_specific_resolver_present"],
            "meaning": "no dedicated validated legacy-DLC handoff resolver is currently proven",
            "required_core_action": "dispatch validated_quartet_legacy_dlc_handoff without enabling transaction prepare",
        },
        {
            "callsite": "payloadpreview.Preview.CommitEnabled",
            "path": CORE_FILES[3],
            "observed": features["preview_commit_disabled"],
            "meaning": "preview output remains non-committing",
            "required_core_action": "preserve CommitEnabled=false",
        },
        {
            "callsite": "brpatcher payload-preview human output",
            "path": CORE_FILES[5],
            "observed": features["cli_says_preview_only"],
            "meaning": "CLI explicitly says no transaction was prepared and no game file was modified",
            "required_core_action": "preserve this statement after adding DLC preview support",
        },
    ]
    write_tsv(
        output_root / "DLC_BKN_DRY_PAYLOAD_PREVIEW_CALLSITE_AUDIT.tsv",
        ("callsite", "path", "observed", "meaning", "required_core_action"),
        callsite_rows,
    )

    transaction_files = sorted(handoff["transaction_files"], key=lambda row: row["relative_path"].casefold())
    artifact_rows = []
    for index, row in enumerate(transaction_files, start=1):
        artifact_rows.append({
            "artifact_order": index,
            "relative_path": row["relative_path"],
            "role": row["role"],
            "baseline_size": row["baseline_size"],
            "baseline_sha256": row["baseline_sha256"],
            "candidate_relative_path": row["candidate_relative_path"],
            "candidate_size": row["candidate_size"],
            "candidate_sha256": row["candidate_sha256"],
            "source_contract": "stage67_validated_handoff",
            "independent_preview_ready_allowed": False,
            "transaction_prepare_allowed": False,
        })
    write_tsv(
        output_root / "DLC_BKN_DRY_PAYLOAD_PREVIEW_ARTIFACT_CONTRACT.tsv",
        (
            "artifact_order", "relative_path", "role", "baseline_size", "baseline_sha256",
            "candidate_relative_path", "candidate_size", "candidate_sha256", "source_contract",
            "independent_preview_ready_allowed", "transaction_prepare_allowed",
        ),
        artifact_rows,
    )

    requirements = [
        (1, "catalog_exact_artifacts", "payloadpreview/catalog.json declares exactly PACK10_02 and PACK12 for quartet_legacy_dlc", True),
        (2, "dedicated_source_kind", f"use source_kind={EXPECTED_SOURCE_KIND}", True),
        (3, "validated_handoff_input", "load and validate stage-67 handoff; do not use the translation repack report for these artifacts", True),
        (4, "candidate_hash_gate", "candidate paths must be regular non-symlink files matching exact size and SHA-256", True),
        (5, "baseline_hash_gate", "installed target paths must be regular non-symlink files matching exact baseline size and SHA-256", True),
        (6, "all_or_none_module_readiness", "module is ready only when both artifacts pass; independent archive readiness is forbidden", True),
        (7, "preview_only_envelope", "CommitEnabled remains false and no Prepare/Commit/Rollback function is called", True),
        (8, "core_regression_tests", "add ready, missing artifact, tampered candidate, changed baseline and single-artifact rejection tests", True),
    ]
    requirement_rows = [
        {"requirement_order": order, "requirement": name, "detail": detail, "mandatory": mandatory, "implemented_by_stage": False}
        for order, name, detail, mandatory in requirements
    ]
    write_tsv(
        output_root / "DLC_BKN_DRY_PAYLOAD_PREVIEW_PATCH_REQUIREMENTS.tsv",
        ("requirement_order", "requirement", "detail", "mandatory", "implemented_by_stage"),
        requirement_rows,
    )

    candidate_entry = {
        "module_id": "quartet_legacy_dlc",
        "target_id": "blue_reflection_quartet",
        "source_kind": EXPECTED_SOURCE_KIND,
        "connection_status": "connected_preview_only",
        "reason": "Validated dry PC00 BKN handoff; preview-only, two artifacts required together, transaction prepare and commit remain disabled.",
        "artifacts": [{"relative_path": path} for path in EXPECTED_TARGETS],
    }
    write_json(output_root / "DLC_BKN_DRY_PAYLOAD_PREVIEW_CATALOG_CANDIDATE.json", candidate_entry)

    core_hashes = {row["path"]: row["sha256"] for row in core_rows}
    patch_request = {
        "type": "br_quartet_legacy_dlc_core_payload_preview_patch_request",
        "format_version": FORMAT_VERSION,
        "request_version": TOOL_VERSION,
        "request_id": "quartet_legacy_dlc_costume_pc00_bkn_dry_payload_preview",
        "workstream_id": "quartet_legacy_dlc",
        "next_owner": "core_orchestrator",
        "content_id": handoff["content_id"],
        "target_id": handoff["target_id"],
        "input_handoff_id": handoff["handoff_id"],
        "input_handoff_version": handoff["handoff_version"],
        "current_core_files": [
            {"path": row["path"], "sha256": row["sha256"], "size": row["size"], "role": row["role"]}
            for row in core_rows
        ],
        "catalog_candidate": candidate_entry,
        "artifact_contract": artifact_rows,
        "required_core_changes": [
            {
                "path": CORE_FILES[1],
                "expected_current_sha256": core_hashes[CORE_FILES[1]],
                "change": "replace only the quartet_legacy_dlc/blue_reflection_quartet row with catalog_candidate",
            },
            {
                "path": CORE_FILES[3],
                "expected_current_sha256": core_hashes[CORE_FILES[3]],
                "change": "add a dedicated handoff-backed artifact resolver selected by source_kind; preserve CommitEnabled=false",
            },
            {
                "path": CORE_FILES[4],
                "expected_current_sha256": core_hashes[CORE_FILES[4]],
                "change": "add exact two-artifact fail-closed preview tests",
            },
        ],
        "requirements": [
            {"requirement": name, "detail": detail, "mandatory": mandatory}
            for _, name, detail, mandatory in requirements
        ],
        "authorization": {
            "patch_request_ready": True,
            "core_patch_applied": False,
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
        "next_action": "core orchestrator applies the request in its own workstream, runs Go tests and returns payload-preview evidence; no prepare or commit is authorized",
    }
    write_json(output_root / "DLC_BKN_DRY_PAYLOAD_PREVIEW_PATCH_REQUEST.json", patch_request)

    gaps = [
        {
            "dependency": "dedicated_handoff_backed_payload_preview_resolver",
            "status": "patch_request_ready_not_implemented",
            "blocks_payload_preview_ready": True,
            "blocks_prepare": True,
            "required_action": "core must implement the requested source-kind resolver and tests",
        },
        {
            "dependency": "core_patch_application_and_go_regression",
            "status": "not_run",
            "blocks_payload_preview_ready": True,
            "blocks_prepare": True,
            "required_action": "apply only in core workstream and return evidence",
        },
        {
            "dependency": "explicit_operator_prepare_authorization",
            "status": "not_granted",
            "blocks_payload_preview_ready": False,
            "blocks_prepare": True,
            "required_action": "obtain separately after preview integration and review",
        },
        {
            "dependency": "runtime_validation_and_ui_availability",
            "status": "not_run",
            "blocks_payload_preview_ready": False,
            "blocks_prepare": False,
            "required_action": "perform only after a separately approved reversible commit",
        },
        {
            "dependency": "wet_bkn_conversion",
            "status": "excluded_conversion_blocked",
            "blocks_payload_preview_ready": False,
            "blocks_prepare": False,
            "required_action": "keep wet variant outside this dry-only contract",
        },
    ]
    write_tsv(
        output_root / "DLC_BKN_DRY_PAYLOAD_PREVIEW_CONTRACT_GAPS.tsv",
        ("dependency", "status", "blocks_payload_preview_ready", "blocks_prepare", "required_action"),
        gaps,
    )

    summary = {
        "type": "br_quartet_legacy_dlc_bkn_dry_payload_preview_contract_summary",
        "format_version": FORMAT_VERSION,
        "tool_version": TOOL_VERSION,
        "status": "metadata_only_payload_preview_patch_request_ready_core_unchanged_no_prepare_no_commit",
        "content_id": handoff["content_id"],
        "target_id": handoff["target_id"],
        "handoff_status": handoff_summary["status"],
        "transaction_target_count": len(artifact_rows),
        "core_file_audit_count": len(core_rows),
        "callsite_audit_count": len(callsite_rows),
        "patch_requirement_count": len(requirement_rows),
        "blocking_preview_gaps": sum(1 for row in gaps if row["blocks_payload_preview_ready"]),
        "current_payload_preview_state": preview_spec["observed_state"],
        "findings": [
            "the core module-selection catalog already declares quartet_legacy_dlc as an opt-in module for Quartet with BR1 as its source target",
            "the payload-preview catalog still marks the adapter pending and declares no artifacts",
            "the current payload-preview verifier is coupled to the translation repack report and has no proven stage-67 handoff resolver",
            "the exact PACK10_02 and PACK12 artifact contract and a fail-closed core patch request are ready without modifying core or the game",
        ],
        "next_action": patch_request["next_action"],
        "policy": {
            "patch_request_ready": True,
            "core_patch_applied": False,
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
        "DLC_BKN_DRY_CORE_PAYLOAD_PREVIEW_FILES.tsv",
        "DLC_BKN_DRY_CORE_CATALOG_AUDIT.tsv",
        "DLC_BKN_DRY_PAYLOAD_PREVIEW_CALLSITE_AUDIT.tsv",
        "DLC_BKN_DRY_PAYLOAD_PREVIEW_ARTIFACT_CONTRACT.tsv",
        "DLC_BKN_DRY_PAYLOAD_PREVIEW_PATCH_REQUIREMENTS.tsv",
        "DLC_BKN_DRY_PAYLOAD_PREVIEW_CATALOG_CANDIDATE.json",
        "DLC_BKN_DRY_PAYLOAD_PREVIEW_PATCH_REQUEST.json",
        "DLC_BKN_DRY_PAYLOAD_PREVIEW_CONTRACT_GAPS.tsv",
        "SUMMARY.json",
        "REPORT_MANIFEST.json",
    )
    for name in required:
        if not (report_root / name).is_file():
            raise BknDryPayloadPreviewContractError(f"missing report file: {name}")

    summary = _load_json(report_root / "SUMMARY.json")
    if summary.get("type") != "br_quartet_legacy_dlc_bkn_dry_payload_preview_contract_summary" or summary.get("tool_version") != TOOL_VERSION:
        raise BknDryPayloadPreviewContractError("invalid payload-preview contract summary")
    if summary.get("status") != "metadata_only_payload_preview_patch_request_ready_core_unchanged_no_prepare_no_commit":
        raise BknDryPayloadPreviewContractError("unexpected payload-preview contract status")
    if summary.get("transaction_target_count") != 2 or summary.get("patch_requirement_count") != 8:
        raise BknDryPayloadPreviewContractError("payload-preview contract counts invalid")
    policy = summary.get("policy", {})
    if policy.get("patch_request_ready") is not True:
        raise BknDryPayloadPreviewContractError("patch request not ready")
    if any(policy.get(key) is not False for key in (
        "core_patch_applied", "core_modified", "real_transaction_prepared", "real_transaction_committed",
        "candidate_installed", "profile_build_allowed", "profile_registered", "runtime_validated",
        "wet_variant_included", "game_modified", "git_modified", "translation_modified",
        "restoration_modified", "raw_assets_exported_in_report",
    )):
        raise BknDryPayloadPreviewContractError("payload-preview contract violates fail-closed policy")

    artifacts = read_tsv(report_root / "DLC_BKN_DRY_PAYLOAD_PREVIEW_ARTIFACT_CONTRACT.tsv")
    if len(artifacts) != 2 or {row.get("relative_path") for row in artifacts} != set(EXPECTED_TARGETS):
        raise BknDryPayloadPreviewContractError("artifact contract target set invalid")
    if any(row.get("independent_preview_ready_allowed") != "false" or row.get("transaction_prepare_allowed") != "false" for row in artifacts):
        raise BknDryPayloadPreviewContractError("artifact contract authorizes a forbidden operation")
    if any(not row.get("candidate_sha256") or not row.get("baseline_sha256") for row in artifacts):
        raise BknDryPayloadPreviewContractError("artifact contract hash missing")

    candidate = _load_json(report_root / "DLC_BKN_DRY_PAYLOAD_PREVIEW_CATALOG_CANDIDATE.json")
    if candidate.get("source_kind") != EXPECTED_SOURCE_KIND or candidate.get("connection_status") != "connected_preview_only":
        raise BknDryPayloadPreviewContractError("catalog candidate semantics invalid")
    if {row.get("relative_path") for row in candidate.get("artifacts", [])} != set(EXPECTED_TARGETS):
        raise BknDryPayloadPreviewContractError("catalog candidate artifact set invalid")

    requirements = read_tsv(report_root / "DLC_BKN_DRY_PAYLOAD_PREVIEW_PATCH_REQUIREMENTS.tsv")
    if len(requirements) != 8 or any(row.get("mandatory") != "true" or row.get("implemented_by_stage") != "false" for row in requirements):
        raise BknDryPayloadPreviewContractError("patch requirements invalid")

    request = _load_json(report_root / "DLC_BKN_DRY_PAYLOAD_PREVIEW_PATCH_REQUEST.json")
    if request.get("type") != "br_quartet_legacy_dlc_core_payload_preview_patch_request":
        raise BknDryPayloadPreviewContractError("patch request type invalid")
    if len(request.get("artifact_contract", [])) != 2 or len(request.get("required_core_changes", [])) != 3:
        raise BknDryPayloadPreviewContractError("patch request content incomplete")
    auth = request.get("authorization", {})
    if auth.get("patch_request_ready") is not True or any(auth.get(key) is not False for key in (
        "core_patch_applied", "core_modified", "real_transaction_prepare_enabled",
        "real_transaction_commit_enabled", "candidate_installed", "profile_build_allowed",
        "profile_registered", "runtime_validated", "wet_variant_included", "game_modified", "git_modified",
    )):
        raise BknDryPayloadPreviewContractError("patch request authorization invalid")

    gaps = read_tsv(report_root / "DLC_BKN_DRY_PAYLOAD_PREVIEW_CONTRACT_GAPS.tsv")
    if len(gaps) < 5 or sum(row.get("blocks_payload_preview_ready") == "true" for row in gaps) != 2:
        raise BknDryPayloadPreviewContractError("payload-preview gap set invalid")

    manifest = _load_json(report_root / "REPORT_MANIFEST.json")
    for row in manifest.get("files", []):
        path = report_root / row["path"]
        if not path.is_file() or path.stat().st_size != row["size"] or sha256_file(path) != row["sha256"]:
            raise BknDryPayloadPreviewContractError(f"report manifest mismatch: {row.get('path')}")
        if {suffix.casefold() for suffix in path.suffixes} & FORBIDDEN_REPORT_SUFFIXES:
            raise BknDryPayloadPreviewContractError(f"raw asset in report: {path}")
    return summary


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    build = sub.add_parser("build-contract")
    build.add_argument("--project-root", type=Path, required=True)
    build.add_argument("--reports-root", type=Path)
    build.add_argument("--handoff-root", type=Path)
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
        if args.command == "build-contract":
            project = args.project_root.resolve()
            reports = (args.reports_root or project / ".local/reports/quartet_legacy_dlc").resolve()
            handoff = (args.handoff_root or reports / HANDOFF.REPORT_DIR_NAME).resolve()
            output = (args.output_root or reports / REPORT_DIR_NAME).resolve()
            build_contract(project, handoff, output)
        elif args.command == "validate-report":
            validate_report(args.report_root)
        else:
            validate_report(args.report_root)
            make_archive(args.report_root.resolve(), args.output.resolve())
    except (BknDryPayloadPreviewContractError, HANDOFF.BknDryCoreHandoffError, OSError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
