#!/usr/bin/env python3
"""Publish the validated PC00+PC01+PC02+PC03+PC04+PC05 dry-BKN generation manifest.

This tool is owned by quartet_legacy_dlc. It validates the generation-5 parent
manifest, the stage-91 PC05 candidate report, candidate and baseline hashes, and
core-owned generic adapter contracts. It then writes provenance evidence and
atomically replaces ACTIVE.json with generation 6. It never calls transaction
Prepare or Commit and never writes to the game installation.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import importlib.util
import json
import os
import re
import sys
import tempfile
from pathlib import Path
from typing import Any, Mapping, Sequence

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT_DEFAULT = SCRIPT_DIR.parent.parent
TOOL_VERSION = "0.0.50"
ACCEPTANCE_RELATIVE = Path("workstreams/quartet_legacy_dlc/DLC_BKN_DRY_PC05_GENERATION_ACCEPTANCE.json")
PC05_TOOL_RELATIVE = Path("workstreams/quartet_legacy_dlc/br_dlc_bkn_dry_pc05_generation_tool.py")
ACTIVE_RELATIVE = Path(".local/reports/quartet_legacy_dlc/validated_payloads/ACTIVE.json")
EVIDENCE_RELATIVE = Path(".local/reports/quartet_legacy_dlc/generations/bkn_dry_generation_6/EVIDENCE.json")
PUBLICATION_REPORT_RELATIVE = Path(".local/reports/quartet_legacy_dlc/validated_payloads/GENERATION_6_PUBLICATION.json")
GENERATION5_SHA256 = "61aa6eb253d806f9b780d417910fdd6cda787d00bc318d87fc53b0e2f7004e9f"
MEMBERS = ["costume_pc00_bkn", "costume_pc01_bkn", "costume_pc02_bkn", "costume_pc03_bkn", "costume_pc04_bkn", "costume_pc05_bkn"]
EXPECTED_CANDIDATES = {
    "Data/PACK10_02.PAK": ".local/build/quartet_legacy_dlc/family_expansion/costume_pc00_pc01_pc02_pc03_pc04_pc05_bkn_dry/candidate/PACK10_02.PAK",
    "Data/PACK12.PAK": ".local/build/quartet_legacy_dlc/family_expansion/costume_pc00_pc01_pc02_pc03_pc04_pc05_bkn_dry/candidate/PACK12.PAK",
}
ADDED_MEMBERS = [
    "data/b1/x64/character/pc00/pc00_dlc_bkn.elixir.gz",
    "data/b1/x64/character/pc00/pc00_dlc_bkn.g1t",
    "data/b1/x64/character/pc01/pc01_dlc_bkn.elixir.gz",
    "data/b1/x64/character/pc01/pc01_dlc_bkn.g1t",
    "data/b1/x64/character/pc02/pc02_dlc_bkn.elixir.gz",
    "data/b1/x64/character/pc02/pc02_dlc_bkn.g1t",
    "data/b1/x64/character/pc03/pc03_dlc_bkn.elixir.gz",
    "data/b1/x64/character/pc03/pc03_dlc_bkn.g1t",
    "data/b1/x64/character/pc04/pc04_dlc_bkn.elixir.gz",
    "data/b1/x64/character/pc04/pc04_dlc_bkn.g1t",
    "data/b1/x64/character/pc05/pc05_dlc_bkn.elixir.gz",
    "data/b1/x64/character/pc05/pc05_dlc_bkn.g1t",
]
COPY_BLOCK_SIZE = 8 * 1024 * 1024


class GenerationPublishError(RuntimeError):
    pass


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(COPY_BLOCK_SIZE), b""):
            digest.update(block)
    return digest.hexdigest()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise GenerationPublishError(f"could not read JSON {path}: {exc}") from exc


def canonical_json_bytes(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def regular_file(path: Path, label: str) -> None:
    if not path.is_file() or path.is_symlink():
        raise GenerationPublishError(f"{label} is missing or is not a regular non-symlink file: {path}")


def resolve_relative_under(root: Path, relative: str | Path, label: str) -> Path:
    raw = Path(relative)
    if raw.is_absolute() or ".." in raw.parts:
        raise GenerationPublishError(f"{label} must be a canonical relative path: {relative}")
    root_real = root.resolve(strict=True)
    path = root / raw
    regular_file(path, label)
    parent_real = path.parent.resolve(strict=True)
    try:
        parent_real.relative_to(root_real)
    except ValueError as exc:
        raise GenerationPublishError(f"{label} escapes its allowed root: {relative}") from exc
    return path


def require_identity(path: Path, *, size: int, sha256: str, label: str) -> dict[str, Any]:
    regular_file(path, label)
    actual_size = path.stat().st_size
    actual_sha = sha256_file(path)
    if actual_size != int(size) or actual_sha != sha256:
        raise GenerationPublishError(
            f"{label} identity mismatch: size {actual_size}/{size}, SHA-256 {actual_sha}/{sha256}"
        )
    return {"path": str(path), "size": actual_size, "sha256": actual_sha}


def version_tuple(raw: str) -> tuple[int, int, int]:
    match = re.fullmatch(r"(\d+)\.(\d+)\.(\d+)", raw.strip())
    if not match:
        raise GenerationPublishError(f"invalid semantic version: {raw!r}")
    return tuple(int(item) for item in match.groups())


def load_pc05_tool(project_root: Path):
    path = project_root / PC05_TOOL_RELATIVE
    regular_file(path, "PC05 generation tool")
    spec = importlib.util.spec_from_file_location("br_dlc_bkn_dry_pc05_generation_tool_runtime", path)
    if spec is None or spec.loader is None:
        raise GenerationPublishError(f"could not load PC05 generation tool: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def load_acceptance(project_root: Path) -> dict[str, Any]:
    acceptance = read_json(project_root / ACCEPTANCE_RELATIVE)
    if acceptance.get("type") != "br_quartet_legacy_dlc_bkn_dry_pc05_generation_acceptance":
        raise GenerationPublishError("unexpected PC05 generation acceptance type")
    if acceptance.get("status") != "accepted_for_checksum_gated_local_pc00_pc01_pc02_pc03_pc04_pc05_generation":
        raise GenerationPublishError("PC05 generation is not accepted")
    auth = acceptance.get("authorization", {})
    for key in ("local_candidate_build", "active_manifest_generation_6_publication", "read_only_canonical_preview"):
        if auth.get(key) is not True:
            raise GenerationPublishError(f"required authorization is missing: {key}")
    for key in (
        "prepare", "commit", "installation", "profile_registration", "runtime_validation", "wet_bkn",
        "translation_modification", "restoration_modification", "core_modification", "git_modification",
    ):
        if auth.get(key) is not False:
            raise GenerationPublishError(f"acceptance does not fail closed for {key}")
    return acceptance


def verify_versions_and_core(project_root: Path, acceptance: Mapping[str, Any]) -> tuple[str, list[dict[str, Any]]]:
    dlc_version = (project_root / "workstreams/quartet_legacy_dlc/VERSION").read_text(encoding="utf-8").strip()
    if dlc_version != TOOL_VERSION:
        raise GenerationPublishError(f"quartet_legacy_dlc {TOOL_VERSION} is required, got {dlc_version}")
    core_version = (project_root / "workstreams/core/VERSION").read_text(encoding="utf-8").strip()
    if version_tuple(core_version) < (0, 0, 47):
        raise GenerationPublishError(f"core 0.0.47 or newer is required, got {core_version}")
    rows: list[dict[str, Any]] = []
    for relative, expected in sorted(acceptance.get("core_contract_gates", {}).items()):
        path = resolve_relative_under(project_root, relative, f"core contract {relative}")
        actual = sha256_file(path)
        if actual != expected:
            raise GenerationPublishError(f"core generic adapter contract changed: {relative}: {actual} != {expected}")
        rows.append({"relative_path": relative, "sha256": actual})
    return core_version, rows


def load_composition(report_root: Path) -> dict[str, dict[str, Any]]:
    path = report_root / "DLC_BKN_DRY_PC05_TWO_ARCHIVE_COMPOSITION.tsv"
    regular_file(path, "PC05 composition report")
    with path.open("r", encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle, delimiter="\t"))
    by_target = {str(row["archive"]): row for row in rows}
    if set(by_target) != set(EXPECTED_CANDIDATES) or len(rows) != 2:
        raise GenerationPublishError("PC05 composition must contain exactly PACK10_02 and PACK12")
    for target, expected_path in EXPECTED_CANDIDATES.items():
        row = by_target[target]
        if row.get("candidate_relative_path") != expected_path:
            raise GenerationPublishError(f"unexpected candidate path for {target}: {row.get('candidate_relative_path')}")
        for key in ("candidate_installed", "profile_registered", "runtime_validated"):
            if row.get(key) != "false":
                raise GenerationPublishError(f"PC05 composition does not fail closed for {key}")
    return by_target


def build_evidence(
    project_root: Path,
    report_root: Path,
    acceptance: Mapping[str, Any],
    composition: Mapping[str, Mapping[str, Any]],
    core_version: str,
) -> dict[str, Any]:
    report_manifest = report_root / "REPORT_MANIFEST.json"
    summary = report_root / "SUMMARY.json"
    regular_file(report_manifest, "PC05 report manifest")
    regular_file(summary, "PC05 summary")
    return {
        "type": "br_quartet_legacy_dlc_bkn_dry_generation_evidence",
        "format_version": 1,
        "status": "generation_6_pc00_pc01_pc02_pc03_pc04_pc05_built_validated_not_installed",
        "workstream_id": "quartet_legacy_dlc",
        "workstream_version": TOOL_VERSION,
        "core_version": core_version,
        "family_id": "bkn_dry",
        "generation": 6,
        "members": MEMBERS,
        "source_evidence": acceptance["source_evidence"],
        "parent_generation": acceptance["active_generation5"],
        "candidate_report": {
            "relative_path": report_root.relative_to(project_root).as_posix(),
            "report_manifest_sha256": sha256_file(report_manifest),
            "summary_sha256": sha256_file(summary),
        },
        "artifacts": [
            {
                "target_path": target,
                "candidate_relative_path": row["candidate_relative_path"],
                "candidate_size": int(row["candidate_size"]),
                "candidate_sha256": row["candidate_sha256"],
            }
            for target, row in sorted(composition.items())
        ],
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


def build_manifest(
    composition: Mapping[str, Mapping[str, Any]],
    acceptance: Mapping[str, Any],
    evidence_sha256: str,
) -> dict[str, Any]:
    baselines = {row["relative_path"]: row for row in acceptance["installed_baselines"]}
    artifacts: list[dict[str, Any]] = []
    for target in ("Data/PACK10_02.PAK", "Data/PACK12.PAK"):
        row = composition[target]
        baseline = baselines[target]
        if target == "Data/PACK10_02.PAK":
            delta = {"added": ADDED_MEMBERS, "changed": [], "removed": []}
        else:
            delta = {"added": [], "changed": ["saves/b1/chara/charabase.xml"], "removed": []}
        artifacts.append({
            "target_path": target,
            "operation": "replace",
            "candidate_relative_path": row["candidate_relative_path"],
            "candidate_size": int(row["candidate_size"]),
            "candidate_sha256": row["candidate_sha256"],
            "baseline_size": int(baseline["size"]),
            "baseline_sha256": baseline["sha256"],
            "member_delta": delta,
        })
    return {
        "type": "validated_quartet_legacy_dlc_payload",
        "format_version": 1,
        "family_id": "bkn_dry",
        "generation": 6,
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
        raise GenerationPublishError("manifest type/version mismatch")
    if manifest.get("family_id") != "bkn_dry" or manifest.get("generation") != 6:
        raise GenerationPublishError("manifest family/generation mismatch")
    if manifest.get("members") != MEMBERS:
        raise GenerationPublishError("manifest members mismatch")
    if manifest.get("source_kind") != "validated_quartet_legacy_dlc_handoff":
        raise GenerationPublishError("manifest source kind mismatch")
    if manifest.get("target_id") != "blue_reflection_quartet":
        raise GenerationPublishError("manifest target mismatch")
    artifacts = manifest.get("artifacts")
    if not isinstance(artifacts, list) or [row.get("target_path") for row in artifacts] != ["Data/PACK10_02.PAK", "Data/PACK12.PAK"]:
        raise GenerationPublishError("manifest target set/order mismatch")
    if artifacts[0].get("member_delta") != {"added": ADDED_MEMBERS, "changed": [], "removed": []}:
        raise GenerationPublishError("PACK10_02 member delta mismatch")
    if artifacts[1].get("member_delta") != {"added": [], "changed": ["saves/b1/chara/charabase.xml"], "removed": []}:
        raise GenerationPublishError("PACK12 member delta mismatch")
    if manifest.get("transaction") != {"group": "quartet_legacy_dlc_bkn_dry", "all_or_none": True, "commit_enabled": False}:
        raise GenerationPublishError("manifest transaction policy mismatch")
    authorization = manifest.get("authorization", {})
    if authorization.get("core_handoff_ready") is not True or any(
        authorization.get(key) is not False
        for key in (
            "real_transaction_prepare_enabled", "real_transaction_commit_enabled", "candidate_installed",
            "profile_registered", "runtime_validated", "wet_variant_included", "game_modified",
        )
    ):
        raise GenerationPublishError("manifest authorization is not fail-closed")


def ensure_safe_parent(project_root: Path, target: Path) -> None:
    project_real = project_root.resolve(strict=True)
    try:
        relative = target.relative_to(project_root)
    except ValueError as exc:
        raise GenerationPublishError(f"publication target is outside project root: {target}") from exc
    current = project_root
    for part in relative.parts[:-1]:
        current /= part
        if current.exists() and current.is_symlink():
            raise GenerationPublishError(f"publication parent is a symlink: {current}")
    target.parent.mkdir(parents=True, exist_ok=True)
    parent_real = target.parent.resolve(strict=True)
    try:
        parent_real.relative_to(project_real)
    except ValueError as exc:
        raise GenerationPublishError("publication parent escapes project root") from exc
    if target.exists() and target.is_symlink():
        raise GenerationPublishError(f"publication target is a symlink: {target}")


def atomic_write_guarded(project_root: Path, target: Path, data: bytes, allowed_existing_hashes: Sequence[str]) -> str:
    ensure_safe_parent(project_root, target)
    new_hash = sha256_bytes(data)
    if target.exists():
        regular_file(target, "existing publication target")
        current_hash = sha256_file(target)
        if current_hash == new_hash:
            return "already_identical"
        if current_hash not in set(allowed_existing_hashes):
            raise GenerationPublishError(f"unexpected existing publication target hash: {target}: {current_hash}")
    fd, temp_name = tempfile.mkstemp(prefix=f".{target.name}.", dir=target.parent)
    temp = Path(temp_name)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temp, 0o644)
        os.replace(temp, target)
        directory_fd = os.open(target.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        if temp.exists():
            temp.unlink()
    return "published"


def publish(project_root: Path, game_dir: Path, report_root: Path) -> dict[str, Any]:
    project_root = project_root.resolve(strict=True)
    game_dir = game_dir.resolve(strict=True)
    report_root = report_root.resolve(strict=True)
    acceptance = load_acceptance(project_root)
    core_version, core_guards = verify_versions_and_core(project_root, acceptance)

    pc05_tool = load_pc05_tool(project_root)
    pc05_tool.validate_report(report_root)
    composition = load_composition(report_root)

    candidates: list[dict[str, Any]] = []
    for target, row in sorted(composition.items()):
        candidate = resolve_relative_under(project_root, row["candidate_relative_path"], f"candidate {target}")
        candidates.append(require_identity(
            candidate,
            size=int(row["candidate_size"]),
            sha256=row["candidate_sha256"],
            label=f"candidate {target}",
        ))

    baselines: list[dict[str, Any]] = []
    for row in acceptance["installed_baselines"]:
        baseline = resolve_relative_under(game_dir, row["relative_path"], f"installed baseline {row['relative_path']}")
        baselines.append(require_identity(
            baseline,
            size=int(row["size"]),
            sha256=row["sha256"],
            label=f"installed baseline {row['relative_path']}",
        ))

    active_path = project_root / ACTIVE_RELATIVE
    regular_file(active_path, "generation-5 ACTIVE manifest")
    active_hash_before = sha256_file(active_path)
    if active_hash_before != GENERATION5_SHA256:
        existing = read_json(active_path)
        if existing.get("generation") != 6 or existing.get("members") != MEMBERS:
            raise GenerationPublishError(
                f"ACTIVE manifest is not the accepted generation 5 and is not this generation 6: {active_hash_before}"
            )

    evidence = build_evidence(project_root, report_root, acceptance, composition, core_version)
    evidence_bytes = canonical_json_bytes(evidence)
    evidence_path = project_root / EVIDENCE_RELATIVE
    evidence_result = atomic_write_guarded(project_root, evidence_path, evidence_bytes, [sha256_bytes(evidence_bytes)])
    evidence_sha = sha256_file(evidence_path)

    manifest = build_manifest(composition, acceptance, evidence_sha)
    validate_manifest_semantics(manifest)
    manifest_bytes = canonical_json_bytes(manifest)
    manifest_sha = sha256_bytes(manifest_bytes)
    active_result = atomic_write_guarded(project_root, active_path, manifest_bytes, [GENERATION5_SHA256, manifest_sha])
    if sha256_file(active_path) != manifest_sha:
        raise GenerationPublishError("published ACTIVE manifest hash mismatch")

    report = {
        "type": "br_quartet_legacy_dlc_bkn_dry_generation_publication",
        "format_version": 1,
        "status": "pass",
        "tool_version": TOOL_VERSION,
        "core_version": core_version,
        "family_id": "bkn_dry",
        "generation": 6,
        "members": MEMBERS,
        "evidence_ready": True,
        "evidence_relative_path": EVIDENCE_RELATIVE.as_posix(),
        "evidence_sha256": evidence_sha,
        "active_manifest_ready": True,
        "active_manifest_relative_path": ACTIVE_RELATIVE.as_posix(),
        "active_manifest_sha256": manifest_sha,
        "parent_generation_manifest_sha256": GENERATION5_SHA256,
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
    }
    report_bytes = canonical_json_bytes(report)
    atomic_write_guarded(project_root, project_root / PUBLICATION_REPORT_RELATIVE, report_bytes, [sha256_bytes(report_bytes)])
    return report


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-root", type=Path, default=PROJECT_ROOT_DEFAULT)
    parser.add_argument("--game-dir", type=Path, required=True)
    parser.add_argument("--report-root", type=Path, required=True)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        result = publish(args.project_root, args.game_dir, args.report_root)
    except (GenerationPublishError, OSError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
