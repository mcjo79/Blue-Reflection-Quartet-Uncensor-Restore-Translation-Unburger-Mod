#!/usr/bin/env python3
"""Build a self-contained, metadata-only core-workstream handoff for dry PC00 BKN.

The stage consumes the validated stage-76 canonical patch proposal, copies the
exact source patch plus its file/hash contract into a compact report, and emits
an acceptance/return contract for the core orchestrator.  It never modifies
canonical core, game files, transaction state, profiles, Translation,
Restoration, or Git.
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
from pathlib import Path
from typing import Any, Iterable

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import br_dlc_bkn_dry_canonical_patch_proposal_tool as PROPOSAL

TOOL_VERSION = "0.0.34"
FORMAT_VERSION = 1
REPORT_DIR_NAME = "bkn_dry_core_patch_handoff_evidence"
REPORT_ARCHIVE_NAME = "BR_quartet_legacy_dlc_bkn_dry_core_patch_handoff_evidence.tar.zst"
PATCH_NAME = "DLC_BKN_DRY_CANONICAL_CORE_PATCH.patch"
HANDOFF_PATCH_NAME = "DLC_BKN_DRY_CORE_WORKSTREAM_PATCH.patch"
EXPECTED_TARGETS = ("Data/PACK10_02.PAK", "Data/PACK12.PAK")
EXPECTED_CHANGED_CORE_FILES = (
    "Blue_Reflection_Patcher/internal/plan/payloadpreview/catalog.json",
    "Blue_Reflection_Patcher/internal/plan/payloadpreview/preview.go",
    "Blue_Reflection_Patcher/internal/plan/payloadpreview/legacy_dlc.go",
    "Blue_Reflection_Patcher/internal/plan/payloadpreview/legacy_dlc_integration_test.go",
)
FORBIDDEN_REPORT_SUFFIXES = PROPOSAL.FORBIDDEN_REPORT_SUFFIXES


class CorePatchHandoffError(RuntimeError):
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
    names = list(fields)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=names, delimiter="\t", lineterminator="\n", extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({name: bool_text(row.get(name, "")) for name in names})


def read_tsv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(4 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CorePatchHandoffError(f"cannot read JSON {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise CorePatchHandoffError(f"JSON root is not an object: {path}")
    return value


def report_manifest(root: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.name == "REPORT_MANIFEST.json":
            continue
        if {suffix.casefold() for suffix in path.suffixes} & FORBIDDEN_REPORT_SUFFIXES:
            raise CorePatchHandoffError(f"raw asset-like file in report: {path}")
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
        raise CorePatchHandoffError(f"cannot create report archive: {result.stderr.strip()}")
    os.replace(temporary, output)


def _acceptance_rows() -> list[dict[str, Any]]:
    return [
        {"order": 1, "requirement": "core_owned_application_only", "required": True, "blocks_prepare": True, "acceptance": "the patch is reviewed and applied only in the core workstream"},
        {"order": 2, "requirement": "old_hash_gate_for_replaced_files", "required": True, "blocks_prepare": True, "acceptance": "catalog.json and preview.go match the recorded old size and SHA-256 before application"},
        {"order": 3, "requirement": "new_files_absent_or_explicitly_reconciled", "required": True, "blocks_prepare": True, "acceptance": "legacy_dlc.go and its integration test do not silently overwrite unrelated existing files"},
        {"order": 4, "requirement": "exact_patch_result_hashes", "required": True, "blocks_prepare": True, "acceptance": "all four resulting files match the proposal new size and SHA-256"},
        {"order": 5, "requirement": "payloadpreview_go_tests", "required": True, "blocks_prepare": True, "acceptance": "go test ./internal/plan/payloadpreview -count=1 passes including every listed legacy-DLC test"},
        {"order": 6, "requirement": "canonical_preview_exact_two_artifacts", "required": True, "blocks_prepare": True, "acceptance": "canonical payload preview exposes exactly PACK10_02 and PACK12 for quartet_legacy_dlc"},
        {"order": 7, "requirement": "all_or_none_readiness", "required": True, "blocks_prepare": True, "acceptance": "both artifacts become ready together and either failure blocks the module"},
        {"order": 8, "requirement": "dedicated_handoff_provenance", "required": True, "blocks_prepare": True, "acceptance": "artifact provenance comes from the validated stage-67 DLC handoff, never the Translation repack report"},
        {"order": 9, "requirement": "preview_only_authorization", "required": True, "blocks_prepare": True, "acceptance": "CommitEnabled remains false and no transaction function is called"},
        {"order": 10, "requirement": "canonical_core_evidence_returned", "required": True, "blocks_prepare": True, "acceptance": "the core workstream returns hashes, Go-test output and canonical preview evidence for DLC review"},
        {"order": 11, "requirement": "separate_prepare_authorization", "required": True, "blocks_prepare": True, "acceptance": "real Prepare remains disabled until a later explicit operator decision"},
        {"order": 12, "requirement": "wet_variant_excluded", "required": True, "blocks_prepare": False, "acceptance": "the integration continues to describe dry PC00 BKN only"},
    ]


def _handoff_markdown(patch_sha: str, patch_size: int, changed_rows: list[dict[str, str]], test_count: int) -> str:
    file_lines = "\n".join(
        f"- `{row['path']}` — {row['action']}, old `{row.get('old_sha256') or 'absent'}`, new `{row['new_sha256']}`"
        for row in changed_rows
    )
    return f"""# Dry PC00 BKN — core payload-preview patch handoff

This archive is the core-owned integration handoff from `quartet_legacy_dlc 0.0.34`.
It contains a source-only patch. It contains no PAK, G1T, XML, KSCL/KSLT, EXE or DLL payload.

## Scope

The patch connects the already validated dry-PC00-BKN two-archive handoff to
canonical `payloadpreview.Build` for preview only:

- `Data/PACK10_02.PAK`
- `Data/PACK12.PAK`

The two artifacts are all-or-none. Candidate and installed baseline files are
validated by exact size and SHA-256. Symlinks are rejected. Provenance comes
from the stage-67 DLC handoff, not from Translation.

## Patch

- file: `{HANDOFF_PATCH_NAME}`
- size: `{patch_size}` bytes
- SHA-256: `{patch_sha}`

Changed source files:

{file_lines}

## Required core-owned review

1. Verify the recorded old hashes before applying the patch.
2. Apply or reproduce the source change inside the core workstream.
3. Verify all four resulting file hashes.
4. Run `go test ./internal/plan/payloadpreview -count=1 -v`.
5. Return canonical preview evidence showing exactly the two DLC artifacts,
   all-or-none readiness, dedicated handoff provenance and `CommitEnabled=false`.

The supplied test matrix contains {test_count} required package tests.

## Explicitly not authorized

This handoff does not authorize transaction `Prepare`, `Commit`, `Rollback`,
game installation, profile registration, runtime validation, wet BKN, changes
to Translation or Restoration, or Git operations by the DLC workstream.
"""


def build_report(project_root: Path, proposal_report_root: Path | None = None) -> Path:
    proposal_root = proposal_report_root or (
        project_root / ".local/reports/quartet_legacy_dlc/bkn_dry_canonical_patch_proposal_evidence"
    )
    proposal_summary = PROPOSAL.validate_report(proposal_root)
    proposal_handoff = _load_json(proposal_root / "DLC_BKN_DRY_CANONICAL_PATCH_HANDOFF.json")
    patch_source = proposal_root / PATCH_NAME
    changed_rows = read_tsv(proposal_root / "DLC_BKN_DRY_CANONICAL_PATCH_FILES.tsv")
    test_rows = [row for row in read_tsv(proposal_root / "DLC_BKN_DRY_CANONICAL_PATCH_GO_TESTS.tsv") if row["phase"] == "patch_apply_check"]
    core_guard_rows = read_tsv(proposal_root / "DLC_BKN_DRY_CANONICAL_PATCH_CORE_GUARD.tsv")

    if tuple(row["path"] for row in changed_rows) != EXPECTED_CHANGED_CORE_FILES:
        raise CorePatchHandoffError("proposal changed-file order does not match the expected four-file core patch")
    if len(test_rows) != int(proposal_summary.get("go_test_count_patch_apply_check", -1)):
        raise CorePatchHandoffError("proposal patch-apply test count is inconsistent")
    if len(core_guard_rows) != 6:
        raise CorePatchHandoffError("proposal canonical core guard must contain six files")
    artifacts = proposal_handoff.get("artifact_contract", [])
    if tuple(row.get("relative_path") for row in artifacts) != EXPECTED_TARGETS:
        raise CorePatchHandoffError("proposal artifact contract is not exact PACK10_02 + PACK12")

    report_root = project_root / ".local/reports/quartet_legacy_dlc" / REPORT_DIR_NAME
    if report_root.exists():
        shutil.rmtree(report_root)
    report_root.mkdir(parents=True)

    patch_target = report_root / HANDOFF_PATCH_NAME
    shutil.copyfile(patch_source, patch_target)
    patch_sha = sha256_file(patch_target)
    patch_size = patch_target.stat().st_size
    if patch_sha != proposal_summary.get("patch_sha256") or patch_size != int(proposal_summary.get("patch_size", -1)):
        raise CorePatchHandoffError("copied patch no longer matches the proposal summary")

    input_rows: list[dict[str, Any]] = []
    for order, row in enumerate(changed_rows, start=1):
        input_rows.append({
            "order": order,
            "path": row["path"],
            "action": row["action"],
            "old_size": row["old_size"],
            "old_sha256": row["old_sha256"],
            "new_size": row["new_size"],
            "new_sha256": row["new_sha256"],
            "canonical_core_modified_by_dlc_workstream": False,
        })
    write_tsv(
        report_root / "DLC_BKN_DRY_CORE_PATCH_INPUTS.tsv",
        ("order", "path", "action", "old_size", "old_sha256", "new_size", "new_sha256", "canonical_core_modified_by_dlc_workstream"),
        input_rows,
    )

    acceptance_rows = _acceptance_rows()
    write_tsv(
        report_root / "DLC_BKN_DRY_CORE_PATCH_ACCEPTANCE.tsv",
        ("order", "requirement", "required", "blocks_prepare", "acceptance"),
        acceptance_rows,
    )

    matrix_rows = [
        {
            "order": index,
            "package": row["package"],
            "test": row["test"],
            "proposal_status": row["status"],
            "required_canonical_status": "pass",
        }
        for index, row in enumerate(test_rows, start=1)
    ]
    write_tsv(
        report_root / "DLC_BKN_DRY_CORE_PATCH_TEST_MATRIX.tsv",
        ("order", "package", "test", "proposal_status", "required_canonical_status"),
        matrix_rows,
    )

    guard_rows: list[dict[str, Any]] = []
    for row in changed_rows:
        guard_rows.append({
            "scope": "patch_target",
            "path": row["path"],
            "expected_preapply_size": row["old_size"],
            "expected_preapply_sha256": row["old_sha256"],
            "expected_postapply_size": row["new_size"],
            "expected_postapply_sha256": row["new_sha256"],
        })
    for row in core_guard_rows:
        if row["path"] in EXPECTED_CHANGED_CORE_FILES:
            continue
        guard_rows.append({
            "scope": "unchanged_canonical_guard",
            "path": row["path"],
            "expected_preapply_size": row["expected_size"],
            "expected_preapply_sha256": row["expected_sha256"],
            "expected_postapply_size": row["expected_size"],
            "expected_postapply_sha256": row["expected_sha256"],
        })
    write_tsv(
        report_root / "DLC_BKN_DRY_CORE_PATCH_FILE_GUARDS.tsv",
        ("scope", "path", "expected_preapply_size", "expected_preapply_sha256", "expected_postapply_size", "expected_postapply_sha256"),
        guard_rows,
    )

    return_contract = {
        "type": "br_quartet_legacy_dlc_core_patch_return_contract",
        "format_version": FORMAT_VERSION,
        "content_id": "costume_pc00_bkn",
        "target_id": "blue_reflection_quartet",
        "required_core_evidence": {
            "patch_or_equivalent_applied": True,
            "result_file_hashes_match": True,
            "payloadpreview_go_tests_pass": True,
            "artifact_paths": list(EXPECTED_TARGETS),
            "artifact_count": 2,
            "all_or_none_ready": True,
            "source_kind": "validated_quartet_legacy_dlc_handoff",
            "commit_enabled": False,
            "transaction_function_called": False,
        },
        "not_authorized": {
            "real_transaction_prepare": True,
            "real_transaction_commit": True,
            "candidate_installation": True,
            "profile_registration": True,
            "runtime_validation": True,
            "wet_variant": True,
        },
    }
    write_json(report_root / "DLC_BKN_DRY_CORE_PATCH_RETURN_CONTRACT.json", return_contract)

    handoff = {
        "type": "br_quartet_legacy_dlc_core_patch_handoff",
        "format_version": FORMAT_VERSION,
        "handoff_version": TOOL_VERSION,
        "content_id": "costume_pc00_bkn",
        "target_id": "blue_reflection_quartet",
        "next_owner": "core_orchestrator",
        "patch_file": HANDOFF_PATCH_NAME,
        "patch_size": patch_size,
        "patch_sha256": patch_sha,
        "changed_files": input_rows,
        "artifact_contract": artifacts,
        "test_count": len(matrix_rows),
        "acceptance_requirement_count": len(acceptance_rows),
        "return_contract_file": "DLC_BKN_DRY_CORE_PATCH_RETURN_CONTRACT.json",
        "authorization": {
            "core_workstream_review_allowed": True,
            "core_workstream_application_allowed_after_review": True,
            "dlc_workstream_core_application_allowed": False,
            "canonical_core_modified": False,
            "real_transaction_prepare_enabled": False,
            "real_transaction_commit_enabled": False,
            "candidate_installed": False,
            "profile_build_allowed": False,
            "profile_registered": False,
            "runtime_validated": False,
            "wet_variant_included": False,
            "game_modified": False,
            "translation_modified": False,
            "restoration_modified": False,
            "git_modified": False,
        },
        "next_action": "upload this report archive to the core orchestrator; apply or reproduce the source-only patch there, return canonical payload-preview evidence, and keep transaction prepare/commit disabled",
    }
    write_json(report_root / "DLC_BKN_DRY_CORE_PATCH_HANDOFF.json", handoff)

    (report_root / "CORE_WORKSTREAM_HANDOFF.md").write_text(
        _handoff_markdown(patch_sha, patch_size, changed_rows, len(matrix_rows)),
        encoding="utf-8",
    )

    gap_rows = [
        {"dependency": "canonical_core_patch_application", "status": "owned_by_core_not_applied", "blocks_preview_acceptance": True, "blocks_prepare": True, "required_action": "core workstream reviews and applies this exact patch or a hash-equivalent implementation"},
        {"dependency": "canonical_payload_preview_evidence", "status": "not_returned", "blocks_preview_acceptance": True, "blocks_prepare": True, "required_action": "return canonical file hashes, Go tests and exact two-artifact preview output"},
        {"dependency": "explicit_operator_prepare_authorization", "status": "not_granted", "blocks_preview_acceptance": False, "blocks_prepare": True, "required_action": "obtain separately only after canonical preview review"},
        {"dependency": "runtime_validation_and_ui_availability", "status": "not_run", "blocks_preview_acceptance": False, "blocks_prepare": False, "required_action": "perform only after a separately authorized reversible commit"},
        {"dependency": "wet_bkn_conversion", "status": "excluded_conversion_blocked", "blocks_preview_acceptance": False, "blocks_prepare": False, "required_action": "keep wet BKN outside this dry-only handoff"},
    ]
    write_tsv(
        report_root / "DLC_BKN_DRY_CORE_PATCH_GAPS.tsv",
        ("dependency", "status", "blocks_preview_acceptance", "blocks_prepare", "required_action"),
        gap_rows,
    )

    summary = {
        "type": "br_quartet_legacy_dlc_bkn_dry_core_patch_handoff_summary",
        "format_version": FORMAT_VERSION,
        "tool_version": TOOL_VERSION,
        "content_id": "costume_pc00_bkn",
        "status": "core_owned_source_patch_handoff_ready_not_applied_no_prepare_no_commit",
        "patch_size": patch_size,
        "patch_sha256": patch_sha,
        "changed_source_file_count": len(input_rows),
        "artifact_count": len(artifacts),
        "test_count": len(matrix_rows),
        "acceptance_requirement_count": len(acceptance_rows),
        "blocking_preview_gaps": 2,
        "findings": [
            "the exact apply-checked source patch is packaged with old/new file hashes and no game payloads",
            "the core workstream receives a complete acceptance matrix and return contract for canonical payload-preview evidence",
            "the DLC workstream does not apply the patch and does not authorize transaction prepare or commit",
        ],
        "policy": {
            "source_patch_exported": True,
            "core_workstream_review_allowed": True,
            "dlc_workstream_core_application_allowed": False,
            "canonical_core_modified": False,
            "real_transaction_prepared": False,
            "real_transaction_committed": False,
            "candidate_installed": False,
            "profile_build_allowed": False,
            "profile_registered": False,
            "runtime_validated": False,
            "wet_variant_included": False,
            "raw_assets_exported_in_report": False,
            "game_modified": False,
            "translation_modified": False,
            "restoration_modified": False,
            "git_modified": False,
        },
        "next_action": handoff["next_action"],
    }
    write_json(report_root / "SUMMARY.json", summary)
    write_json(report_root / "REPORT_MANIFEST.json", {
        "type": "br_report_manifest",
        "format_version": FORMAT_VERSION,
        "files": report_manifest(report_root),
    })
    return report_root


def validate_report(report_root: Path) -> dict[str, Any]:
    summary = _load_json(report_root / "SUMMARY.json")
    if summary.get("tool_version") != TOOL_VERSION or summary.get("status") != "core_owned_source_patch_handoff_ready_not_applied_no_prepare_no_commit":
        raise CorePatchHandoffError("unexpected summary version/status")
    policy = summary.get("policy", {})
    if policy.get("source_patch_exported") is not True or policy.get("core_workstream_review_allowed") is not True:
        raise CorePatchHandoffError("handoff/export flags are missing")
    for key in (
        "dlc_workstream_core_application_allowed", "canonical_core_modified",
        "real_transaction_prepared", "real_transaction_committed", "candidate_installed",
        "profile_build_allowed", "profile_registered", "runtime_validated",
        "wet_variant_included", "raw_assets_exported_in_report", "game_modified",
        "translation_modified", "restoration_modified", "git_modified",
    ):
        if policy.get(key) is not False:
            raise CorePatchHandoffError(f"unsafe policy flag: {key}")

    patch = report_root / HANDOFF_PATCH_NAME
    if not patch.is_file() or patch.stat().st_size != int(summary.get("patch_size", -1)) or sha256_file(patch) != summary.get("patch_sha256"):
        raise CorePatchHandoffError("handoff patch is missing or mismatched")
    inputs = read_tsv(report_root / "DLC_BKN_DRY_CORE_PATCH_INPUTS.tsv")
    if len(inputs) != 4 or tuple(row["path"] for row in inputs) != EXPECTED_CHANGED_CORE_FILES:
        raise CorePatchHandoffError("handoff changed-file contract is invalid")
    if any(row["canonical_core_modified_by_dlc_workstream"] != "false" for row in inputs):
        raise CorePatchHandoffError("handoff claims canonical core modification")
    acceptance = read_tsv(report_root / "DLC_BKN_DRY_CORE_PATCH_ACCEPTANCE.tsv")
    if len(acceptance) != 12 or any(row["required"] != "true" for row in acceptance):
        raise CorePatchHandoffError("acceptance matrix is incomplete")
    tests = read_tsv(report_root / "DLC_BKN_DRY_CORE_PATCH_TEST_MATRIX.tsv")
    if len(tests) != int(summary.get("test_count", -1)) or any(row["proposal_status"] != "pass" or row["required_canonical_status"] != "pass" for row in tests):
        raise CorePatchHandoffError("test matrix is incomplete")
    guards = read_tsv(report_root / "DLC_BKN_DRY_CORE_PATCH_FILE_GUARDS.tsv")
    if len(guards) < 6 or len({row["path"] for row in guards}) != len(guards):
        raise CorePatchHandoffError("file guard matrix is incomplete or duplicated")
    handoff = _load_json(report_root / "DLC_BKN_DRY_CORE_PATCH_HANDOFF.json")
    authorization = handoff.get("authorization", {})
    if authorization.get("core_workstream_review_allowed") is not True or authorization.get("core_workstream_application_allowed_after_review") is not True:
        raise CorePatchHandoffError("core review/application handoff flags are missing")
    for key in (
        "dlc_workstream_core_application_allowed", "canonical_core_modified",
        "real_transaction_prepare_enabled", "real_transaction_commit_enabled",
        "candidate_installed", "profile_build_allowed", "profile_registered",
        "runtime_validated", "wet_variant_included", "game_modified",
        "translation_modified", "restoration_modified", "git_modified",
    ):
        if authorization.get(key) is not False:
            raise CorePatchHandoffError(f"unsafe handoff authorization: {key}")
    if tuple(row.get("relative_path") for row in handoff.get("artifact_contract", [])) != EXPECTED_TARGETS:
        raise CorePatchHandoffError("handoff artifact contract is not exact PACK10_02 + PACK12")
    return_contract = _load_json(report_root / "DLC_BKN_DRY_CORE_PATCH_RETURN_CONTRACT.json")
    evidence = return_contract.get("required_core_evidence", {})
    if evidence.get("artifact_paths") != list(EXPECTED_TARGETS) or evidence.get("commit_enabled") is not False or evidence.get("transaction_function_called") is not False:
        raise CorePatchHandoffError("return contract is not fail-closed")
    manifest = _load_json(report_root / "REPORT_MANIFEST.json")
    expected = {row["path"]: (int(row["size"]), row["sha256"]) for row in manifest.get("files", [])}
    actual = {row["path"]: (int(row["size"]), row["sha256"]) for row in report_manifest(report_root)}
    if expected != actual:
        raise CorePatchHandoffError("report manifest mismatch")
    return summary


def main() -> None:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    build = sub.add_parser("build-handoff")
    build.add_argument("--project-root", required=True)
    build.add_argument("--proposal-report-root")
    validate = sub.add_parser("validate-report")
    validate.add_argument("--report-root", required=True)
    bundle = sub.add_parser("bundle-report")
    bundle.add_argument("--report-root", required=True)
    bundle.add_argument("--output", required=True)
    args = parser.parse_args()
    try:
        if args.command == "build-handoff":
            root = build_report(
                Path(args.project_root).resolve(),
                Path(args.proposal_report_root).resolve() if args.proposal_report_root else None,
            )
            print(root)
        elif args.command == "validate-report":
            print(json.dumps(validate_report(Path(args.report_root).resolve()), indent=2, sort_keys=True))
        else:
            root = Path(args.report_root).resolve()
            validate_report(root)
            output = Path(args.output).resolve()
            make_archive(root, output)
            print(output)
    except (CorePatchHandoffError, PROPOSAL.CanonicalPatchProposalError, OSError, subprocess.SubprocessError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
