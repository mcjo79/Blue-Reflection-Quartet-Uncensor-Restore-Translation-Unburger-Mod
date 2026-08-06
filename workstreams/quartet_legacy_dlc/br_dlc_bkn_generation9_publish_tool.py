#!/usr/bin/env python3
"""Publish the validated generation-9 append-only BKN label manifest.

The tool writes only DLC-owned local evidence and ACTIVE.json. It never calls
transaction Prepare or Commit and never writes to the game installation.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import importlib.util
import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Any, Mapping, Sequence

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT_DEFAULT = SCRIPT_DIR.parent.parent
TOOL_VERSION = "0.0.64"
ACCEPTANCE_RELATIVE = Path("workstreams/quartet_legacy_dlc/DLC_BKN_SYNTHETIC_LABEL_SLOT_RETURN_ACCEPTANCE.json")
CANDIDATE_TOOL_RELATIVE = Path("workstreams/quartet_legacy_dlc/br_dlc_bkn_generation9_label_candidate_tool.py")
ACTIVE_RELATIVE = Path(".local/reports/quartet_legacy_dlc/validated_payloads/ACTIVE.json")
EVIDENCE_RELATIVE = Path(".local/reports/quartet_legacy_dlc/generations/bkn_dry_generation_9/EVIDENCE.json")
PUBLICATION_REPORT_RELATIVE = Path(".local/reports/quartet_legacy_dlc/validated_payloads/GENERATION_9_PUBLICATION.json")
GENERATION8_SHA256 = "237bca51efb207edfa61b3c4fc8d1ba64f21fc07f8fc211b2a54a69e1dc4929e"
MEMBERS = [
    "costume_pc00_bkn", "costume_pc01_bkn", "costume_pc02_bkn", "costume_pc03_bkn",
    "costume_pc04_bkn", "costume_pc05_bkn", "costume_pc06_bkn", "costume_pc07_bkn",
]
ADDED_MEMBERS = [
    f"data/b1/x64/character/pc{index:02d}/pc{index:02d}_dlc_bkn{suffix}"
    for index in range(8)
    for suffix in (".elixir.gz", ".g1t")
]
PACK12_CHANGED_MEMBERS = [
    "saves/b1/chara/charabase.xml",
    "saves/b1/text_en/str_costume.xml",
    "saves/b1/text_jp/str_costume.xml",
    "saves/b1/text_sc/str_costume.xml",
    "saves/b1/text_tc/str_costume.xml",
]
COPY_BLOCK_SIZE = 8 * 1024 * 1024


class Generation9PublishError(RuntimeError):
    pass


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(COPY_BLOCK_SIZE), b""):
            digest.update(block)
    return digest.hexdigest()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canonical_json_bytes(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise Generation9PublishError(f"could not read JSON {path}: {exc}") from exc


def read_tsv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def regular_file(path: Path, label: str) -> None:
    if not path.is_file() or path.is_symlink():
        raise Generation9PublishError(f"{label} is missing or unsafe: {path}")


def resolve_under(root: Path, relative: str, label: str) -> Path:
    rel = Path(relative)
    if rel.is_absolute() or ".." in rel.parts:
        raise Generation9PublishError(f"unsafe {label} path: {relative}")
    root_real = root.resolve(strict=True)
    candidate = (root_real / rel).resolve(strict=False)
    try:
        candidate.relative_to(root_real)
    except ValueError as exc:
        raise Generation9PublishError(f"{label} escapes root: {relative}") from exc
    return candidate


def require_identity(path: Path, *, size: int, sha256: str, label: str) -> dict[str, Any]:
    regular_file(path, label)
    actual_size = path.stat().st_size
    actual_sha = sha256_file(path)
    if actual_size != size or actual_sha != sha256:
        raise Generation9PublishError(f"{label} identity mismatch")
    return {"relative_path": "", "size": actual_size, "sha256": actual_sha}


def load_acceptance(project_root: Path) -> dict[str, Any]:
    path = project_root / ACCEPTANCE_RELATIVE
    regular_file(path, "generation9 acceptance")
    data = read_json(path)
    if data.get("type") != "br_quartet_legacy_dlc_bkn_synthetic_label_slot_return_acceptance":
        raise Generation9PublishError("unexpected acceptance type")
    if data.get("status") != "accepted_for_generation9_append_only_synthetic_label_candidate_build":
        raise Generation9PublishError("generation9 publication is not accepted")
    authorization = data.get("authorization", {})
    if authorization.get("generation9_active_manifest_publication") is not True or authorization.get("read_only_canonical_preview") is not True:
        raise Generation9PublishError("generation9 publication/preview authorization missing")
    forbidden = (
        "prepare", "commit", "installation", "profile_registration", "runtime_validation",
        "existing_costume_replacement", "global_show_all", "pc08", "wet_bkn",
        "translation_workstream_modification", "restoration_modification", "core_modification", "git_modification",
    )
    if any(authorization.get(key) is not False for key in forbidden):
        raise Generation9PublishError("acceptance does not fail closed")
    return data


def load_candidate_tool(project_root: Path):
    path = project_root / CANDIDATE_TOOL_RELATIVE
    regular_file(path, "generation9 candidate tool")
    spec = importlib.util.spec_from_file_location("br_dlc_bkn_generation9_label_candidate_tool_runtime", path)
    if spec is None or spec.loader is None:
        raise Generation9PublishError("could not load generation9 candidate tool")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def verify_core_contract(project_root: Path, acceptance: Mapping[str, Any]) -> tuple[str, dict[str, str]]:
    """Verify semantic capabilities of the parallel core workstream."""
    version_path = project_root / "workstreams/core/VERSION"
    regular_file(version_path, "core VERSION")
    core_version = version_path.read_text(encoding="utf-8").strip()
    try:
        tuple(int(part) for part in core_version.split("."))
    except ValueError as exc:
        raise Generation9PublishError(f"invalid core version: {core_version}") from exc

    required = {
        "policy": "Blue_Reflection_Patcher/internal/plan/payloadpreview/legacy_dlc_policy.json",
        "schema": "workstreams/core/contracts/quartet_legacy_dlc/VALIDATED_QUARTET_LEGACY_DLC_PAYLOAD.schema.json",
        "contract": "workstreams/core/contracts/quartet_legacy_dlc/GENERIC_ADAPTER_RETURN_CONTRACT.json",
        "runner": "workstreams/core/tools/validate_quartet_legacy_dlc_active_manifest.sh",
        "result_validator": "workstreams/core/tools/validate_quartet_legacy_dlc_preview_result.py",
    }
    paths = {}
    observed = {}
    for label, relative in required.items():
        path = resolve_under(project_root, relative, f"core capability {label}")
        regular_file(path, f"core capability {label}")
        paths[label] = path
        observed[relative] = sha256_file(path)

    policy = read_json(paths["policy"])
    if policy.get("type") != "br_quartet_legacy_dlc_manifest_policy" or policy.get("format_version") != 1:
        raise Generation9PublishError("unexpected core legacy-DLC policy type/version")
    if policy.get("source_kind") != "validated_quartet_legacy_dlc_handoff":
        raise Generation9PublishError("core legacy-DLC source_kind capability changed")
    if policy.get("target_id") != "blue_reflection_quartet":
        raise Generation9PublishError("core legacy-DLC target capability changed")

    families = [item for item in policy.get("families", []) if item.get("family_id") == "bkn_dry"]
    if len(families) != 1:
        raise Generation9PublishError("core must expose exactly one bkn_dry family policy")
    family = families[0]
    if family.get("transaction_group") != "quartet_legacy_dlc_bkn_dry":
        raise Generation9PublishError("core bkn_dry transaction group changed")
    if family.get("member_id_pattern") != r"^costume_(pc[0-9]{2})_bkn$":
        raise Generation9PublishError("core bkn_dry member pattern changed")
    if int(family.get("minimum_members", 999)) > 1 or int(family.get("maximum_members", 0)) < len(MEMBERS):
        raise Generation9PublishError("core bkn_dry member bounds reject generation 9")

    artifacts = {item.get("target_path"): item for item in family.get("artifacts", [])}
    if set(artifacts) != {"Data/PACK10_02.PAK", "Data/PACK12.PAK"}:
        raise Generation9PublishError("core bkn_dry artifact target set changed")
    pack10 = artifacts["Data/PACK10_02.PAK"]
    expected_templates = {
        "data/b1/x64/character/{member_key}/{member_key}_dlc_bkn.elixir.gz",
        "data/b1/x64/character/{member_key}/{member_key}_dlc_bkn.g1t",
    }
    if pack10.get("operation") != "replace" or set(pack10.get("added_member_templates", [])) != expected_templates:
        raise Generation9PublishError("core PACK10_02 capability changed")
    if pack10.get("changed_members", []) or pack10.get("removed_members", []):
        raise Generation9PublishError("core PACK10_02 delta is no longer add-only")
    pack12 = artifacts["Data/PACK12.PAK"]
    if pack12.get("operation") != "replace" or pack12.get("added_member_templates", []) or pack12.get("removed_members", []):
        raise Generation9PublishError("core PACK12 operation/add/remove capability changed")
    allowed_sets = {tuple(pack12.get("changed_members", []))}
    allowed_sets.update(tuple(item) for item in pack12.get("additional_changed_member_sets", []))
    if ("saves/b1/chara/charabase.xml",) not in allowed_sets:
        raise Generation9PublishError("core no longer accepts generation-8 PACK12")
    if tuple(PACK12_CHANGED_MEMBERS) not in allowed_sets:
        raise Generation9PublishError("core lacks the exact generation-9 PACK12 capability")
    runner_text = paths["runner"].read_text(encoding="utf-8", errors="replace")
    validator_text = paths["result_validator"].read_text(encoding="utf-8", errors="replace")
    if "validate_quartet_legacy_dlc_preview_result.py" not in runner_text:
        raise Generation9PublishError("core runner lacks structured result validation")
    for token in ("structured_rejection_reason", "artifacts"):
        if token not in validator_text:
            raise Generation9PublishError(f"core result validator lacks {token}")
    return core_version, observed


def ensure_safe_parent(project_root: Path, target: Path) -> None:
    project_real = project_root.resolve(strict=True)
    try:
        relative = target.relative_to(project_root)
    except ValueError as exc:
        raise Generation9PublishError(f"publication target is outside project root: {target}") from exc
    current = project_root
    for part in relative.parts[:-1]:
        current /= part
        if current.exists() and current.is_symlink():
            raise Generation9PublishError(f"publication parent is a symlink: {current}")
    target.parent.mkdir(parents=True, exist_ok=True)
    parent_real = target.parent.resolve(strict=True)
    try:
        parent_real.relative_to(project_real)
    except ValueError as exc:
        raise Generation9PublishError("publication parent escapes project root") from exc
    if target.exists() and target.is_symlink():
        raise Generation9PublishError(f"publication target is a symlink: {target}")


def atomic_write_guarded(project_root: Path, target: Path, data: bytes, allowed_existing_hashes: Sequence[str]) -> str:
    ensure_safe_parent(project_root, target)
    new_hash = sha256_bytes(data)
    if target.exists():
        regular_file(target, "existing publication target")
        current_hash = sha256_file(target)
        if current_hash == new_hash:
            return "already_identical"
        if current_hash not in set(allowed_existing_hashes):
            raise Generation9PublishError(f"unexpected existing publication target hash: {target}: {current_hash}")
    fd, temporary_name = tempfile.mkstemp(prefix=f".{target.name}.", dir=target.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, 0o644)
        os.replace(temporary, target)
        directory_fd = os.open(target.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        if temporary.exists():
            temporary.unlink()
    return "published"


def load_composition(report_root: Path) -> dict[str, dict[str, str]]:
    path = report_root / "GENERATION9_TWO_ARCHIVE_COMPOSITION.tsv"
    regular_file(path, "generation9 composition")
    rows = read_tsv(path)
    if [row.get("target_path") for row in rows] != ["Data/PACK10_02.PAK", "Data/PACK12.PAK"]:
        raise Generation9PublishError("generation9 composition target set/order mismatch")
    for row in rows:
        for key in ("candidate_installed", "profile_registered", "runtime_validated"):
            if row.get(key) != "false":
                raise Generation9PublishError(f"composition does not fail closed for {key}")
    return {row["target_path"]: row for row in rows}


def build_evidence(
    project_root: Path,
    report_root: Path,
    acceptance: Mapping[str, Any],
    composition: Mapping[str, Mapping[str, str]],
    core_version: str,
) -> dict[str, Any]:
    report_manifest = report_root / "REPORT_MANIFEST.json"
    summary = report_root / "SUMMARY.json"
    regular_file(report_manifest, "candidate report manifest")
    regular_file(summary, "candidate summary")
    return {
        "type": "br_quartet_legacy_dlc_bkn_dry_generation_evidence",
        "format_version": 1,
        "status": "generation_9_pc00_pc07_append_only_labels_built_validated_not_installed",
        "tool_version": TOOL_VERSION,
        "core_version": core_version,
        "family_id": "bkn_dry",
        "generation": 9,
        "parent_generation": 8,
        "members": MEMBERS,
        "candidate_report": {
            "relative_path": report_root.relative_to(project_root).as_posix(),
            "summary_sha256": sha256_file(summary),
            "manifest_sha256": sha256_file(report_manifest),
        },
        "artifacts": [
            {
                "target_path": target,
                "candidate_relative_path": row["candidate_relative_path"],
                "candidate_size": int(row["candidate_size"]),
                "candidate_sha256": row["candidate_sha256"],
            }
            for target, row in composition.items()
        ],
        "append_plan": acceptance["append_plan"],
        "authorization": {
            "commit_enabled": False,
            "transaction_function_called": False,
            "transaction_prepare_called": False,
            "transaction_commit_called": False,
            "candidate_installed": False,
            "profile_registered": False,
            "runtime_validated": False,
            "wet_variant_included": False,
            "game_modified": False,
            "save_modified": False,
            "existing_costume_replaced": False,
            "global_show_all_enabled": False,
        },
    }


def build_manifest(
    composition: Mapping[str, Mapping[str, str]],
    acceptance: Mapping[str, Any],
    evidence_sha256: str,
) -> dict[str, Any]:
    baselines = {row["target_path"]: row for row in acceptance["installed_baselines"]}
    artifacts = []
    for target in ("Data/PACK10_02.PAK", "Data/PACK12.PAK"):
        row = composition[target]
        baseline = baselines[target]
        changed = [] if target.endswith("PACK10_02.PAK") else PACK12_CHANGED_MEMBERS
        artifacts.append({
            "target_path": target,
            "operation": "replace",
            "candidate_relative_path": row["candidate_relative_path"],
            "candidate_size": int(row["candidate_size"]),
            "candidate_sha256": row["candidate_sha256"],
            "baseline_size": int(baseline["size"]),
            "baseline_sha256": baseline["sha256"],
            "member_delta": {
                "added": ADDED_MEMBERS if target.endswith("PACK10_02.PAK") else [],
                "changed": changed,
                "removed": [],
            },
        })
    return {
        "type": "validated_quartet_legacy_dlc_payload",
        "format_version": 1,
        "family_id": "bkn_dry",
        "generation": 9,
        "members": MEMBERS,
        "source_kind": "validated_quartet_legacy_dlc_handoff",
        "target_id": "blue_reflection_quartet",
        "artifacts": artifacts,
        "transaction": {
            "group": "quartet_legacy_dlc_bkn_dry",
            "all_or_none": True,
            "commit_enabled": False,
        },
        "provenance": {
            "workstream_id": "quartet_legacy_dlc",
            "workstream_version": TOOL_VERSION,
            "evidence_relative_path": EVIDENCE_RELATIVE.as_posix(),
            "evidence_sha256": evidence_sha256,
        },
        "authorization": {
            "core_handoff_ready": True,
            "real_transaction_prepare_enabled": False,
            "real_transaction_commit_enabled": False,
            "candidate_installed": False,
            "profile_registered": False,
            "runtime_validated": False,
            "wet_variant_included": False,
            "game_modified": False,
        },
    }


def validate_manifest_semantics(manifest: Mapping[str, Any]) -> None:
    if manifest.get("type") != "validated_quartet_legacy_dlc_payload" or manifest.get("format_version") != 1:
        raise Generation9PublishError("manifest type/version mismatch")
    if manifest.get("family_id") != "bkn_dry" or manifest.get("generation") != 9:
        raise Generation9PublishError("manifest family/generation mismatch")
    if manifest.get("members") != MEMBERS:
        raise Generation9PublishError("manifest members mismatch")
    artifacts = manifest.get("artifacts")
    if not isinstance(artifacts, list) or [row.get("target_path") for row in artifacts] != ["Data/PACK10_02.PAK", "Data/PACK12.PAK"]:
        raise Generation9PublishError("manifest target set/order mismatch")
    if artifacts[0].get("member_delta") != {"added": ADDED_MEMBERS, "changed": [], "removed": []}:
        raise Generation9PublishError("PACK10 member delta mismatch")
    if artifacts[1].get("member_delta") != {"added": [], "changed": PACK12_CHANGED_MEMBERS, "removed": []}:
        raise Generation9PublishError("PACK12 member delta mismatch")
    if manifest.get("transaction") != {"group": "quartet_legacy_dlc_bkn_dry", "all_or_none": True, "commit_enabled": False}:
        raise Generation9PublishError("manifest transaction policy mismatch")


def publish(project_root: Path, game_dir: Path, report_root: Path) -> dict[str, Any]:
    project_root = project_root.resolve(strict=True)
    game_dir = game_dir.resolve(strict=True)
    report_root = report_root.resolve(strict=True)
    acceptance = load_acceptance(project_root)
    core_version, core_guards = verify_core_contract(project_root, acceptance)
    candidate_tool = load_candidate_tool(project_root)
    candidate_tool.validate_report(report_root)
    composition = load_composition(report_root)

    candidates: list[dict[str, Any]] = []
    for target in ("Data/PACK10_02.PAK", "Data/PACK12.PAK"):
        row = composition[target]
        candidate = resolve_under(project_root, row["candidate_relative_path"], f"candidate {target}")
        identity = require_identity(candidate, size=int(row["candidate_size"]), sha256=row["candidate_sha256"], label=f"candidate {target}")
        identity["relative_path"] = candidate.relative_to(project_root).as_posix()
        identity["target_path"] = target
        candidates.append(identity)

    baselines: list[dict[str, Any]] = []
    for row in acceptance["installed_baselines"]:
        baseline = resolve_under(game_dir, row["relative_path"], f"installed baseline {row['target_path']}")
        identity = require_identity(baseline, size=int(row["size"]), sha256=row["sha256"], label=f"installed baseline {row['target_path']}")
        identity["relative_path"] = row["relative_path"]
        identity["target_path"] = row["target_path"]
        baselines.append(identity)

    active_path = project_root / ACTIVE_RELATIVE
    regular_file(active_path, "ACTIVE manifest")
    active_hash_before = sha256_file(active_path)
    active_before = read_json(active_path)
    if active_hash_before != GENERATION8_SHA256:
        if active_before.get("generation") != 9 or active_before.get("members") != MEMBERS:
            raise Generation9PublishError(f"ACTIVE manifest is neither accepted generation 8 nor generation 9: {active_hash_before}")

    evidence = build_evidence(project_root, report_root, acceptance, composition, core_version)
    evidence_bytes = canonical_json_bytes(evidence)
    evidence_path = project_root / EVIDENCE_RELATIVE
    atomic_write_guarded(project_root, evidence_path, evidence_bytes, [sha256_bytes(evidence_bytes)])
    evidence_sha = sha256_file(evidence_path)

    manifest = build_manifest(composition, acceptance, evidence_sha)
    validate_manifest_semantics(manifest)
    manifest_bytes = canonical_json_bytes(manifest)
    manifest_sha = sha256_bytes(manifest_bytes)
    active_result = atomic_write_guarded(project_root, active_path, manifest_bytes, [GENERATION8_SHA256, manifest_sha])
    if sha256_file(active_path) != manifest_sha:
        raise Generation9PublishError("published ACTIVE manifest hash mismatch")

    report = {
        "type": "br_quartet_legacy_dlc_bkn_dry_generation_publication",
        "format_version": 1,
        "status": "pass",
        "tool_version": TOOL_VERSION,
        "core_version": core_version,
        "family_id": "bkn_dry",
        "generation": 9,
        "parent_generation": 8,
        "members": MEMBERS,
        "evidence_ready": True,
        "evidence_relative_path": EVIDENCE_RELATIVE.as_posix(),
        "evidence_sha256": evidence_sha,
        "active_manifest_ready": True,
        "active_manifest_relative_path": ACTIVE_RELATIVE.as_posix(),
        "active_manifest_sha256": manifest_sha,
        "parent_generation_manifest_sha256": GENERATION8_SHA256,
        "active_write_result": active_result,
        "artifact_paths": ["Data/PACK10_02.PAK", "Data/PACK12.PAK"],
        "candidates": candidates,
        "baselines": baselines,
        "core_contract_guards": core_guards,
        "commit_enabled": False,
        "transaction_function_called": False,
        "transaction_prepare_called": False,
        "transaction_commit_called": False,
        "candidate_installed": False,
        "profile_registered": False,
        "runtime_validated": False,
        "wet_variant_included": False,
        "game_modified": False,
        "save_modified": False,
        "existing_costume_replaced": False,
        "global_show_all_enabled": False,
    }
    report_bytes = canonical_json_bytes(report)
    atomic_write_guarded(project_root, project_root / PUBLICATION_REPORT_RELATIVE, report_bytes, [sha256_bytes(report_bytes)])
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-root", type=Path, default=PROJECT_ROOT_DEFAULT)
    parser.add_argument("--game-dir", type=Path, required=True)
    parser.add_argument("--report-root", type=Path, required=True)
    args = parser.parse_args()
    try:
        result = publish(args.project_root, args.game_dir, args.report_root)
    except (Generation9PublishError, OSError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
