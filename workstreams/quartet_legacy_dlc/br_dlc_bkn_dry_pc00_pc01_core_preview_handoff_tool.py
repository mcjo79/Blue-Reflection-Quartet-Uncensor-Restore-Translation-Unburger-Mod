#!/usr/bin/env python3
"""Build a metadata-only core handoff for the combined dry BKN PC00+PC01 candidates."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import stat as statmod
from pathlib import Path, PurePosixPath
from typing import Any, Iterable

TOOL_VERSION = "0.0.43"
FORMAT_VERSION = 1
ACCEPTANCE_NAME = "DLC_BKN_DRY_PC01_FAMILY_CANDIDATE_ACCEPTANCE.json"
REPORT_DIR_NAME = "bkn_dry_pc00_pc01_core_preview_handoff_evidence"
ARCHIVE_NAME = "BR_quartet_legacy_dlc_bkn_dry_pc00_pc01_core_preview_handoff_evidence.tar.zst"
HANDOFF_NAME = "DLC_BKN_DRY_PC00_PC01_CORE_PREVIEW_HANDOFF.json"
RETURN_NAME = "DLC_BKN_DRY_PC00_PC01_CORE_PREVIEW_RETURN_CONTRACT.json"
EXPECTED_ARTIFACTS = ("Data/PACK10_02.PAK", "Data/PACK12.PAK")
CORE_FILES = (
    "Blue_Reflection_Patcher/internal/plan/payloadpreview/catalog.json",
    "Blue_Reflection_Patcher/internal/plan/payloadpreview/preview.go",
    "Blue_Reflection_Patcher/internal/plan/payloadpreview/legacy_dlc.go",
    "Blue_Reflection_Patcher/internal/plan/payloadpreview/legacy_dlc_integration_test.go",
)
CURRENT_TYPE = "br_quartet_legacy_dlc_dry_bkn_core_integration_handoff"
CURRENT_HANDOFF_VERSION = "0.0.30"
CURRENT_HANDOFF_PATH = ".local/reports/quartet_legacy_dlc/bkn_dry_core_integration_handoff_evidence/DLC_BKN_DRY_CORE_INTEGRATION_HANDOFF.json"
REQUESTED_TYPE = "br_quartet_legacy_dlc_dry_bkn_family_core_integration_handoff"
REQUESTED_HANDOFF_VERSION = "0.0.43"
SOURCE_KIND = "validated_quartet_legacy_dlc_handoff"
MINIMUM_CORE_VERSION = "0.0.42"
FORBIDDEN_SUFFIXES = {".pak", ".g1t", ".g1m", ".gz", ".elixir", ".xml", ".exe", ".dll", ".bin", ".swg"}

class HandoffError(RuntimeError):
    pass

def parse_numeric_version(value: str, label: str) -> tuple[int, ...]:
    if not re.fullmatch(r"[0-9]+(?:\.[0-9]+)*", value):
        raise HandoffError(f"invalid {label}: {value!r}")
    return tuple(int(part) for part in value.split("."))

def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()

def load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise HandoffError(f"cannot read JSON {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise HandoffError(f"JSON root is not an object: {path}")
    return value

def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")

def bool_text(value: Any) -> Any:
    if isinstance(value, bool):
        return "true" if value else "false"
    if value is None:
        return ""
    if isinstance(value, (dict, list, tuple, set)):
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return value

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

def safe_relative(value: str) -> PurePosixPath:
    rel = PurePosixPath(value)
    if rel.is_absolute() or not rel.parts or any(part in ("", ".", "..") for part in rel.parts):
        raise HandoffError(f"unsafe relative path: {value}")
    return rel

def regular_file_under(root: Path, relative: str, label: str) -> Path:
    rel = safe_relative(relative)
    current = root
    for part in rel.parts:
        current = current / part
        try:
            info = current.lstat()
        except OSError as exc:
            raise HandoffError(f"cannot inspect {label} {relative}: {exc}") from exc
        if statmod.S_ISLNK(info.st_mode):
            raise HandoffError(f"{label} contains a symlink component: {relative}")
    if not current.is_file():
        raise HandoffError(f"{label} is not a regular file: {relative}")
    return current

def verify_file(path: Path, size: int, digest: str, label: str) -> None:
    actual_size = path.stat().st_size
    if actual_size != size:
        raise HandoffError(f"{label} size mismatch: {actual_size} != {size}")
    actual_hash = sha256_file(path)
    if actual_hash.lower() != digest.lower():
        raise HandoffError(f"{label} SHA-256 mismatch: {actual_hash} != {digest}")

def report_manifest(root: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.name == "REPORT_MANIFEST.json":
            continue
        if any(suffix.casefold() in FORBIDDEN_SUFFIXES for suffix in path.suffixes):
            raise HandoffError(f"raw asset-like file in metadata report: {path.name}")
        rows.append({"path": path.relative_to(root).as_posix(), "size": path.stat().st_size, "sha256": sha256_file(path)})
    return rows

def parse_current_binding(text: str) -> dict[str, str]:
    def one(pattern: str, label: str) -> str:
        match = re.search(pattern, text, flags=re.MULTILINE)
        if not match:
            raise HandoffError(f"cannot identify current core {label}")
        return match.group(1)
    result = {
        "source_kind": one(r'legacyDLCSourceKind\s*=\s*"([^"]+)"', "source kind"),
        "handoff_relative_path": one(r'legacyDLCHandoffRelative\s*=\s*"([^"]+)"', "handoff path"),
        "accepted_type": one(r'handoff\.Type\s*!=\s*"([^"]+)"', "handoff type"),
        "accepted_handoff_version": one(r'handoff\.HandoffVersion\s*!=\s*"([^"]+)"', "handoff version"),
    }
    reason_matches = re.findall(r'return artifacts, true, "([^"]+)"', text)
    result["ready_reason"] = reason_matches[-1] if reason_matches else ""
    return result

def make_archive(root: Path, output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(output.name + ".tmp")
    temporary.unlink(missing_ok=True)
    result = subprocess.run(["tar", "--zstd", "-cf", str(temporary), "-C", str(root.parent), root.name], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if result.returncode != 0:
        temporary.unlink(missing_ok=True)
        raise HandoffError(f"cannot create archive: {result.stderr.strip()}")
    os.replace(temporary, output)

def build_report(project_root: Path, game_root: Path) -> Path:
    workstream = project_root / "workstreams/quartet_legacy_dlc"
    acceptance = load_json(workstream / ACCEPTANCE_NAME)
    if acceptance.get("accepted_at_version") != TOOL_VERSION or acceptance.get("status") != "accepted_for_metadata_only_core_pc00_pc01_payload_preview_handoff":
        raise HandoffError("unexpected stage-85 acceptance version/status")
    if (workstream / "VERSION").read_text(encoding="utf-8").strip() != TOOL_VERSION:
        raise HandoffError(f"quartet_legacy_dlc VERSION is not {TOOL_VERSION}")
    minimum_core = str(acceptance.get("minimum_core_version", ""))
    if minimum_core != MINIMUM_CORE_VERSION:
        raise HandoffError(f"unexpected minimum core version contract: {minimum_core!r}")
    core_version = (project_root / "workstreams/core/VERSION").read_text(encoding="utf-8").strip()
    if parse_numeric_version(core_version, "core version") < parse_numeric_version(minimum_core, "minimum core version"):
        raise HandoffError(f"core version too old: minimum {minimum_core}, got {core_version}")

    files = acceptance.get("transaction_files")
    if not isinstance(files, list) or len(files) != 2 or tuple(row.get("relative_path") for row in files) != EXPECTED_ARTIFACTS:
        raise HandoffError("stage-85 acceptance does not contain exact PACK10_02 + PACK12 contract")

    artifact_rows: list[dict[str, Any]] = []
    for order, row in enumerate(files, start=1):
        candidate = regular_file_under(project_root, str(row["candidate_relative_path"]), "candidate")
        baseline = regular_file_under(game_root, str(row["relative_path"]), "installed baseline")
        verify_file(candidate, int(row["candidate_size"]), str(row["candidate_sha256"]), f"candidate {row['relative_path']}")
        verify_file(baseline, int(row["baseline_size"]), str(row["baseline_sha256"]), f"baseline {row['relative_path']}")
        artifact_rows.append({
            "order": order,
            "relative_path": row["relative_path"],
            "candidate_relative_path": row["candidate_relative_path"],
            "candidate_size": row["candidate_size"],
            "candidate_sha256": row["candidate_sha256"],
            "baseline_size": row["baseline_size"],
            "baseline_sha256": row["baseline_sha256"],
            "candidate_verified": True,
            "baseline_verified": True,
            "candidate_installed": False,
        })

    source_rows: list[dict[str, Any]] = []
    for relative in CORE_FILES:
        path = regular_file_under(project_root, relative, "canonical core source")
        source_rows.append({"path": relative, "size": path.stat().st_size, "sha256": sha256_file(path), "modified_by_dlc_workstream": False})
    legacy_path = project_root / CORE_FILES[2]
    binding = parse_current_binding(legacy_path.read_text(encoding="utf-8"))
    expected_binding = {
        "source_kind": SOURCE_KIND,
        "handoff_relative_path": CURRENT_HANDOFF_PATH,
        "accepted_type": CURRENT_TYPE,
        "accepted_handoff_version": CURRENT_HANDOFF_VERSION,
    }
    for key, expected in expected_binding.items():
        if binding.get(key) != expected:
            raise HandoffError(f"current core binding changed for {key}: expected {expected!r}, got {binding.get(key)!r}")

    report_root = project_root / ".local/reports/quartet_legacy_dlc" / REPORT_DIR_NAME
    if report_root.exists():
        shutil.rmtree(report_root)
    report_root.mkdir(parents=True)

    write_tsv(report_root / "DLC_BKN_DRY_PC00_PC01_ARTIFACT_CONTRACT.tsv",
              ("order", "relative_path", "candidate_relative_path", "candidate_size", "candidate_sha256", "baseline_size", "baseline_sha256", "candidate_verified", "baseline_verified", "candidate_installed"), artifact_rows)
    write_tsv(report_root / "DLC_BKN_DRY_PC00_PC01_CORE_SOURCE_GUARDS.tsv",
              ("path", "size", "sha256", "modified_by_dlc_workstream"), source_rows)
    binding_rows = [{"field": key, "current_value": value, "requested_value": {
        "source_kind": SOURCE_KIND,
        "handoff_relative_path": f".local/reports/quartet_legacy_dlc/{REPORT_DIR_NAME}/{HANDOFF_NAME}",
        "accepted_type": REQUESTED_TYPE,
        "accepted_handoff_version": REQUESTED_HANDOFF_VERSION,
        "ready_reason": "validated dry BKN PC00+PC01 family handoff; preview-only two-artifact contract",
    }.get(key, value), "semantic_merge_required": key != "source_kind"} for key, value in binding.items()]
    write_tsv(report_root / "DLC_BKN_DRY_PC00_PC01_CORE_CURRENT_BINDING.tsv",
              ("field", "current_value", "requested_value", "semantic_merge_required"), binding_rows)

    acceptance_rows = [
        {"order": 1, "requirement": "core_owned_semantic_merge_only", "required": True, "acceptance": "all canonical source changes are reviewed and applied only by the core workstream"},
        {"order": 2, "requirement": "preserve_six_target_routing", "required": True, "acceptance": "the existing target routing and module ownership gates remain unchanged"},
        {"order": 3, "requirement": "preserve_handoff_provenance", "required": True, "acceptance": "source_kind remains validated_quartet_legacy_dlc_handoff and Translation reports are not accepted as DLC provenance"},
        {"order": 4, "requirement": "versioned_family_handoff", "required": True, "acceptance": "canonical preview consumes the new PC00+PC01 family handoff type/version/path or a documented equivalent"},
        {"order": 5, "requirement": "exact_two_artifacts", "required": True, "acceptance": "the module exposes exactly Data/PACK10_02.PAK and Data/PACK12.PAK"},
        {"order": 6, "requirement": "exact_candidate_and_baseline_gates", "required": True, "acceptance": "both artifact size/SHA-256 pairs match this handoff and symlinks are rejected"},
        {"order": 7, "requirement": "all_or_none_readiness", "required": True, "acceptance": "either both artifacts are ready or the module is blocked"},
        {"order": 8, "requirement": "payloadpreview_tests", "required": True, "acceptance": "the payloadpreview package test matrix passes, including missing/tampered/symlink/all-or-none cases"},
        {"order": 9, "requirement": "full_core_tests_and_vet", "required": True, "acceptance": "go test ./... and go vet ./... pass in Blue_Reflection_Patcher"},
        {"order": 10, "requirement": "canonical_local_preview", "required": True, "acceptance": "a real local payloadpreview.Build returns ready with exactly the two combined-family candidates"},
        {"order": 11, "requirement": "preview_only", "required": True, "acceptance": "CommitEnabled remains false and no transaction function is called"},
        {"order": 12, "requirement": "return_evidence", "required": True, "acceptance": "core returns source hashes, tests, raw preview fixture and canonical local preview evidence"},
    ]
    write_tsv(report_root / "DLC_BKN_DRY_PC00_PC01_CORE_ACCEPTANCE.tsv", ("order", "requirement", "required", "acceptance"), acceptance_rows)

    handoff_path = f".local/reports/quartet_legacy_dlc/{REPORT_DIR_NAME}/{HANDOFF_NAME}"
    handoff = {
        "type": REQUESTED_TYPE,
        "format_version": FORMAT_VERSION,
        "handoff_version": REQUESTED_HANDOFF_VERSION,
        "workstream_version": TOOL_VERSION,
        "target_id": "blue_reflection_quartet",
        "content_ids": acceptance["content_ids"],
        "source_kind": SOURCE_KIND,
        "current_core_version": core_version,
        "minimum_core_version": minimum_core,
        "current_core_binding": binding,
        "requested_handoff_relative_path": handoff_path,
        "transaction_files": [{key: row[key] for key in ("relative_path", "candidate_relative_path", "baseline_size", "baseline_sha256", "candidate_size", "candidate_sha256")} for row in files],
        "authorization": {
            "core_handoff_ready": True,
            "core_semantic_merge_allowed": True,
            "dlc_workstream_core_modification_allowed": False,
            "real_transaction_prepare_enabled": False,
            "real_transaction_commit_enabled": False,
            "candidate_installed": False,
            "profile_registered": False,
            "runtime_validated": False,
            "wet_variant_included": False,
            "game_modified": False,
            "translation_modified": False,
            "restoration_modified": False,
            "git_modified": False,
        },
        "required_semantic_merge": {
            "generalize_pc00_only_binding_to_pc00_pc01_family": True,
            "preserve_source_kind": SOURCE_KIND,
            "preserve_target_routing": True,
            "preserve_all_or_none": True,
            "preserve_symlink_rejection": True,
            "preserve_preview_only_policy": True,
            "ready_reason": "validated dry BKN PC00+PC01 family handoff; preview-only two-artifact contract",
        },
        "next_action": "core reviews current source guards, performs a semantic merge for the versioned family handoff, runs canonical tests and returns evidence matching the return contract; no Prepare, Commit or installation",
    }
    write_json(report_root / HANDOFF_NAME, handoff)

    return_contract = {
        "type": "br_quartet_legacy_dlc_bkn_dry_pc00_pc01_core_preview_return_contract",
        "format_version": FORMAT_VERSION,
        "target_id": "blue_reflection_quartet",
        "content_ids": acceptance["content_ids"],
        "input_handoff_sha256": "__FILLED_AFTER_HANDOFF_WRITE__",
        "required_core_evidence": {
            "semantic_merge_applied_by_core": True,
            "six_target_routing_preserved": True,
            "provenance_gates_preserved": True,
            "source_kind": SOURCE_KIND,
            "payloadpreview_go_tests_pass": True,
            "all_go_tests_pass": True,
            "go_vet_pass": True,
            "artifact_paths": list(EXPECTED_ARTIFACTS),
            "artifact_count": 2,
            "candidate_sha256": {row["relative_path"]: row["candidate_sha256"] for row in files},
            "baseline_sha256": {row["relative_path"]: row["baseline_sha256"] for row in files},
            "all_or_none_ready": True,
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
            "translation_modification": True,
            "restoration_modification": True,
            "git_modification_by_dlc_workstream": True,
        },
    }
    return_contract["input_handoff_sha256"] = sha256_file(report_root / HANDOFF_NAME)
    write_json(report_root / RETURN_NAME, return_contract)

    gap_rows = [
        {"dependency": "core_family_handoff_semantic_merge", "status": "not_applied_owned_by_core", "blocks_canonical_preview": True, "blocks_prepare": True, "required_action": "core generalizes the PC00-only binding without regressing routing or provenance"},
        {"dependency": "canonical_pc00_pc01_payload_preview_return", "status": "not_returned", "blocks_canonical_preview": True, "blocks_prepare": True, "required_action": "core returns exact combined-family preview evidence"},
        {"dependency": "explicit_prepare_authorization", "status": "not_granted", "blocks_canonical_preview": False, "blocks_prepare": True, "required_action": "obtain separately after preview review"},
        {"dependency": "runtime_validation", "status": "not_run", "blocks_canonical_preview": False, "blocks_prepare": False, "required_action": "perform only after a separately authorized reversible installation"},
        {"dependency": "wet_bkn", "status": "excluded_conversion_blocked", "blocks_canonical_preview": False, "blocks_prepare": False, "required_action": "keep outside this dry-only family handoff"},
    ]
    write_tsv(report_root / "DLC_BKN_DRY_PC00_PC01_CORE_GAPS.tsv", ("dependency", "status", "blocks_canonical_preview", "blocks_prepare", "required_action"), gap_rows)

    md = f"""# Dry BKN PC00+PC01 — canonical core preview handoff

This metadata-only handoff comes from `quartet_legacy_dlc {TOOL_VERSION}` and
contains no game payloads. The local candidates and installed baselines were
revalidated by exact size and SHA-256 before this report was created.

## Combined dry family

- `costume_pc00_bkn`
- `costume_pc01_bkn`
- `Data/PACK10_02.PAK`: `{files[0]['candidate_sha256']}`
- `Data/PACK12.PAK`: `{files[1]['candidate_sha256']}`

## Why core review is required

Core `{core_version}` passed the minimum-version gate and still accepts the earlier PC00-only handoff type
`{binding['accepted_type']}`, version `{binding['accepted_handoff_version']}`
and path `{binding['handoff_relative_path']}`. Do not silently overwrite that
contract. Perform a semantic merge in the core workstream so the canonical
preview consumes the versioned PC00+PC01 family handoff while preserving the
existing six-target routing, provenance, symlink rejection and all-or-none
readiness.

## Return requirement

Return evidence matching `{RETURN_NAME}`. The canonical local preview must show
exactly two ready artifacts and must keep `CommitEnabled=false` with no
transaction function called.

## Not authorized

No transaction Prepare, Commit, installation, profile registration, runtime
validation, wet BKN, Translation, Restoration or DLC-owned core modification.
"""
    (report_root / "CORE_WORKSTREAM_HANDOFF.md").write_text(md, encoding="utf-8")

    summary = {
        "type": "br_quartet_legacy_dlc_bkn_dry_pc00_pc01_core_preview_handoff_summary",
        "format_version": FORMAT_VERSION,
        "tool_version": TOOL_VERSION,
        "status": "metadata_only_core_family_preview_handoff_ready_waiting_for_core",
        "target_id": "blue_reflection_quartet",
        "content_ids": acceptance["content_ids"],
        "core_version": core_version,
        "artifact_count": 2,
        "core_source_guard_count": len(source_rows),
        "acceptance_requirement_count": len(acceptance_rows),
        "blocking_preview_gaps": 2,
        "handoff_file": HANDOFF_NAME,
        "handoff_sha256": sha256_file(report_root / HANDOFF_NAME),
        "return_contract_file": RETURN_NAME,
        "policy": {
            "candidate_files_verified": True,
            "installed_baselines_verified": True,
            "raw_assets_exported_in_report": False,
            "core_modified": False,
            "game_modified": False,
            "prepare_called": False,
            "commit_called": False,
            "candidate_installed": False,
            "profile_registered": False,
            "runtime_validated": False,
            "wet_variant_included": False,
            "translation_modified": False,
            "restoration_modified": False,
            "git_modified": False,
        },
        "next_action": handoff["next_action"],
    }
    write_json(report_root / "SUMMARY.json", summary)
    write_json(report_root / "REPORT_MANIFEST.json", {"type": "br_report_manifest", "format_version": FORMAT_VERSION, "files": report_manifest(report_root)})
    return report_root

def validate_report(report_root: Path) -> dict[str, Any]:
    summary = load_json(report_root / "SUMMARY.json")
    if summary.get("tool_version") != TOOL_VERSION or summary.get("status") != "metadata_only_core_family_preview_handoff_ready_waiting_for_core":
        raise HandoffError("unexpected report version/status")
    policy = summary.get("policy", {})
    if policy.get("candidate_files_verified") is not True or policy.get("installed_baselines_verified") is not True or policy.get("raw_assets_exported_in_report") is not False:
        raise HandoffError("report verification/export policy is invalid")
    for key in ("core_modified", "game_modified", "prepare_called", "commit_called", "candidate_installed", "profile_registered", "runtime_validated", "wet_variant_included", "translation_modified", "restoration_modified", "git_modified"):
        if policy.get(key) is not False:
            raise HandoffError(f"unsafe report policy: {key}")
    artifacts = read_tsv(report_root / "DLC_BKN_DRY_PC00_PC01_ARTIFACT_CONTRACT.tsv")
    if len(artifacts) != 2 or tuple(row["relative_path"] for row in artifacts) != EXPECTED_ARTIFACTS:
        raise HandoffError("artifact contract is not exact two-file order")
    if any(row["candidate_verified"] != "true" or row["baseline_verified"] != "true" or row["candidate_installed"] != "false" for row in artifacts):
        raise HandoffError("artifact verification flags are invalid")
    handoff = load_json(report_root / HANDOFF_NAME)
    if handoff.get("type") != REQUESTED_TYPE or handoff.get("handoff_version") != REQUESTED_HANDOFF_VERSION or handoff.get("source_kind") != SOURCE_KIND:
        raise HandoffError("family handoff identity is invalid")
    auth = handoff.get("authorization", {})
    if auth.get("core_handoff_ready") is not True or auth.get("core_semantic_merge_allowed") is not True:
        raise HandoffError("core handoff authorization is missing")
    for key in ("dlc_workstream_core_modification_allowed", "real_transaction_prepare_enabled", "real_transaction_commit_enabled", "candidate_installed", "profile_registered", "runtime_validated", "wet_variant_included", "game_modified", "translation_modified", "restoration_modified", "git_modified"):
        if auth.get(key) is not False:
            raise HandoffError(f"unsafe handoff authorization: {key}")
    contract = load_json(report_root / RETURN_NAME)
    evidence = contract.get("required_core_evidence", {})
    if evidence.get("artifact_paths") != list(EXPECTED_ARTIFACTS) or evidence.get("artifact_count") != 2 or evidence.get("commit_enabled") is not False or evidence.get("transaction_function_called") is not False:
        raise HandoffError("return contract is not exact and fail-closed")
    if contract.get("input_handoff_sha256") != sha256_file(report_root / HANDOFF_NAME):
        raise HandoffError("return contract does not bind the handoff hash")
    manifest = load_json(report_root / "REPORT_MANIFEST.json")
    expected = {row["path"]: (int(row["size"]), row["sha256"]) for row in manifest.get("files", [])}
    actual = {row["path"]: (int(row["size"]), row["sha256"]) for row in report_manifest(report_root)}
    if expected != actual:
        raise HandoffError("report manifest mismatch")
    return summary

def main() -> None:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    build = sub.add_parser("build-handoff")
    build.add_argument("--project-root", required=True)
    build.add_argument("--game-dir", required=True)
    validate = sub.add_parser("validate-report")
    validate.add_argument("--report-root", required=True)
    bundle = sub.add_parser("bundle-report")
    bundle.add_argument("--report-root", required=True)
    bundle.add_argument("--output", required=True)
    args = parser.parse_args()
    try:
        if args.command == "build-handoff":
            print(build_report(Path(args.project_root).resolve(), Path(args.game_dir).resolve()))
        elif args.command == "validate-report":
            print(json.dumps(validate_report(Path(args.report_root).resolve()), indent=2, sort_keys=True))
        else:
            root = Path(args.report_root).resolve()
            validate_report(root)
            output = Path(args.output).resolve()
            make_archive(root, output)
            print(output)
    except (HandoffError, OSError, subprocess.SubprocessError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)

if __name__ == "__main__":
    main()
