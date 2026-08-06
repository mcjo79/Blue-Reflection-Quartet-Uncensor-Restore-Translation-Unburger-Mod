#!/usr/bin/env python3
"""Canonically integrate the verified Quartet Restoration runtime-validation return."""

from __future__ import annotations

import argparse
import csv
import hashlib
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

WORKSTREAM_ID = "quartet_restoration"
EXPECTED_VERSION = "0.1.56"
REGISTRY_REL = Path("workstreams/quartet_restoration/RUNTIME_VALIDATION_REGISTRY.json")
REPORT_NAME = "BR_quartet_restoration_runtime_validation_canonical_integration_evidence.tar.zst"
REPORT_DIR_NAME = "runtime_validation_canonical_integration_evidence"
B_PROFILE = "candidate_bathroom_river_containing_pak_static_inverse_062e39915e7d"
W_PROFILE = "water_shader_swater_original_code"
H_PROFILE = "height_fog_shader_original_code"
EXPECTED_CORE_RETURN_SHA256 = "93d106ac2ee390734725ca9d1c10b225d1af11294d4e355df90ef1e1b5cf0068"
EXPECTED_PROMOTION_EVIDENCE_SHA256 = "ccacd9234a60656a022bcb1155b8afc3e7fe6091b504882ad325083aeed83567"


class IntegrationError(RuntimeError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise IntegrationError(message)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    require(spec is not None and spec.loader is not None, f"cannot load module: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def read_version(project_root: Path) -> str:
    path = project_root / "workstreams/quartet_restoration/VERSION"
    require(path.is_file(), f"missing VERSION: {path}")
    version = path.read_text(encoding="utf-8").strip()
    require(version == EXPECTED_VERSION, f"expected quartet_restoration {EXPECTED_VERSION}, got {version}")
    return version


def validate_registry(registry: dict[str, object], specs) -> dict[str, bool]:
    require(registry.get("type") == "br_quartet_restoration_runtime_validation_registry", "registry type mismatch")
    require(registry.get("format_version") == 1, "registry format mismatch")
    source = registry.get("source_evidence")
    require(isinstance(source, dict), "source evidence is missing")
    require(source.get("core_return_bundle_sha256") == EXPECTED_CORE_RETURN_SHA256, "core return hash mismatch")
    require(source.get("local_promotion_evidence_sha256") == EXPECTED_PROMOTION_EVIDENCE_SHA256, "promotion evidence hash mismatch")

    by_id = {item.profile_id: item for item in specs}
    require(len(by_id) == 15, "expected exactly fifteen current profile specs")
    direct = registry.get("profiles")
    require(isinstance(direct, dict), "direct runtime profile decisions are missing")
    require(set(direct) == {B_PROFILE, W_PROFILE, H_PROFILE}, "direct runtime profile decision set mismatch")
    decisions: dict[str, bool] = {}
    for profile_id, row in direct.items():
        require(profile_id in by_id, f"unknown runtime profile: {profile_id}")
        require(isinstance(row, dict), f"invalid runtime row: {profile_id}")
        spec = by_id[profile_id]
        require(row.get("target_relative_path") == spec.target_relative_path, f"target mismatch: {profile_id}")
        require(row.get("profile_sha256") == spec.profile_sha256, f"profile hash mismatch: {profile_id}")
        require(isinstance(row.get("runtime_validated"), bool), f"invalid runtime flag: {profile_id}")
        require(row.get("production_eligible") is row.get("runtime_validated"), f"production flag mismatch: {profile_id}")
        decisions[profile_id] = bool(row["runtime_validated"])

    b = direct[B_PROFILE]
    require(b.get("runtime_status") == "pass_visual_and_stability", "B runtime status mismatch")
    require(b.get("runtime_validated") is True, "B must be runtime-validated")
    semantics = b.get("confirmed_semantics")
    require(isinstance(semantics, dict), "B confirmed semantics are missing")
    require(semantics.get("classification") == "water_visibility_transparency_restoration", "B semantics mismatch")
    require(semantics.get("field") == "home_bathroom", "B field semantics mismatch")

    for profile_id in (W_PROFILE, H_PROFILE):
        row = direct[profile_id]
        require(row.get("runtime_status") == "runtime_failed", f"shader failure status mismatch: {profile_id}")
        require(row.get("runtime_validated") is False, f"failed shader must remain unvalidated: {profile_id}")
        require(row.get("production_eligible") is False, f"failed shader must remain excluded: {profile_id}")

    event = registry.get("event_group")
    require(isinstance(event, dict), "event-group runtime decision is missing")
    event_ids = event.get("profile_ids")
    require(isinstance(event_ids, list), "event-group profile IDs are invalid")
    expected_event_ids = {item.profile_id for item in specs if item.target_relative_path == "Data/PACK11.PAK"}
    require(set(event_ids) == expected_event_ids and len(event_ids) == 12, "event-group profile set mismatch")
    require(event.get("profile_count") == 12, "event-group count mismatch")
    require(event.get("group_runtime_status") == "runtime_safe_visual_inconclusive", "event-group status mismatch")
    require(event.get("individual_runtime_validated") is False, "event profiles must remain individually unvalidated")
    require(event.get("production_eligible") is False, "event profiles must remain production-ineligible")
    for profile_id in event_ids:
        decisions[profile_id] = False

    require(set(decisions) == set(by_id), "runtime decisions do not cover all current profiles")
    require([profile_id for profile_id, value in decisions.items() if value] == [B_PROFILE], "validated profile set mismatch")
    fix = registry.get("shader_failure_investigation")
    require(isinstance(fix, dict), "shader fix directions are missing")
    require(fix.get("status") == "hypothesis_supported_not_proven", "shader hypothesis status mismatch")
    steps = fix.get("required_next_steps")
    require(isinstance(steps, list) and len(steps) == 6, "shader fix direction count mismatch")
    return decisions


def validate_manifests(manifests: list[dict[str, object]], specs, decisions: dict[str, bool], version: str) -> None:
    require(len(manifests) == 15, "generated manifest count mismatch")
    by_id = {item["profile_id"]: item for item in manifests}
    require(len(by_id) == 15, "generated manifests contain duplicate IDs")
    spec_by_id = {item.profile_id: item for item in specs}
    require(set(by_id) == set(spec_by_id), "generated manifest profile set mismatch")
    for profile_id, manifest in by_id.items():
        spec = spec_by_id[profile_id]
        require(manifest.get("runtime_validated") is decisions[profile_id], f"runtime flag mismatch: {profile_id}")
        require(manifest.get("workstream_version") == version, f"workstream version mismatch: {profile_id}")
        require(manifest.get("profile_sha256") == spec.profile_sha256, f"generated profile hash mismatch: {profile_id}")
        require(manifest.get("target_relative_path") == spec.target_relative_path, f"generated target mismatch: {profile_id}")
    require(sum(row.get("runtime_validated") is True for row in manifests) == 1, "exactly one manifest must be production eligible")
    require(by_id[B_PROFILE].get("runtime_validated") is True, "B generated manifest is not runtime-validated")
    require(by_id[W_PROFILE].get("runtime_validated") is False, "W generated manifest became eligible")
    require(by_id[H_PROFILE].get("runtime_validated") is False, "H generated manifest became eligible")


def atomic_json(path: Path, data: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + f".tmp.{os.getpid()}")
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def write_tsv(path: Path, fieldnames: list[str], rows: list[dict[str, object]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def build_report(project_root: Path, generator, registry: dict[str, object], manifests: list[dict[str, object]], version: str) -> Path:
    report_root = project_root / ".local/reports/quartet_restoration"
    evidence_dir = report_root / REPORT_DIR_NAME
    if evidence_dir.exists():
        shutil.rmtree(evidence_dir)
    evidence_dir.mkdir(parents=True)

    specs = {item.profile_id: item for item in generator.CURRENT_PROFILE_SPECS}
    direct = registry["profiles"]
    event = registry["event_group"]
    rows: list[dict[str, object]] = []
    for manifest in sorted(manifests, key=lambda row: str(row["profile_id"])):
        profile_id = str(manifest["profile_id"])
        if profile_id in direct:
            row = direct[profile_id]
            runtime_status = row["runtime_status"]
            observation = row["observation"]
            semantics = (row.get("confirmed_semantics") or {}).get("classification", "")
        else:
            runtime_status = event["group_runtime_status"]
            observation = event["observation"]
            semantics = ""
        rows.append({
            "profile_id": profile_id,
            "target_relative_path": manifest["target_relative_path"],
            "profile_sha256": manifest["profile_sha256"],
            "runtime_status": runtime_status,
            "runtime_validated": str(manifest["runtime_validated"]).lower(),
            "production_eligible": str(manifest["runtime_validated"]).lower(),
            "confirmed_semantics": semantics,
            "observation": observation,
        })
    write_tsv(
        evidence_dir / "PROFILE_RUNTIME_DECISIONS.tsv",
        ["profile_id", "target_relative_path", "profile_sha256", "runtime_status", "runtime_validated", "production_eligible", "confirmed_semantics", "observation"],
        rows,
    )

    manifest_rows = [{
        "profile_id": row["profile_id"],
        "manifest_relative_path": f".local/build/quartet_restoration/core_profiles/generated/{row['profile_id']}.json",
        "workstream_version": row["workstream_version"],
        "runtime_validated": str(row["runtime_validated"]).lower(),
        "target_relative_path": row["target_relative_path"],
        "profile_sha256": row["profile_sha256"],
        "validation_status": "passed",
    } for row in sorted(manifests, key=lambda item: str(item["profile_id"]))]
    write_tsv(
        evidence_dir / "GENERATED_MANIFEST_CHECKS.tsv",
        ["profile_id", "manifest_relative_path", "workstream_version", "runtime_validated", "target_relative_path", "profile_sha256", "validation_status"],
        manifest_rows,
    )

    atomic_json(evidence_dir / "CONFIRMED_SEMANTICS.json", {
        "profile_id": B_PROFILE,
        "runtime_status": direct[B_PROFILE]["runtime_status"],
        "confirmed_semantics": direct[B_PROFILE]["confirmed_semantics"],
        "observation": direct[B_PROFILE]["observation"],
    })
    atomic_json(evidence_dir / "SHADER_FAILURE_FIX_DIRECTIONS.json", registry["shader_failure_investigation"])
    write_tsv(evidence_dir / "INPUT_HASHES.tsv", ["input", "sha256"], [
        {"input": "runtime_validation_core_return_bundle", "sha256": EXPECTED_CORE_RETURN_SHA256},
        {"input": "local_B_runtime_promotion_evidence", "sha256": EXPECTED_PROMOTION_EVIDENCE_SHA256},
        {"input": "runtime_validation_registry", "sha256": sha256_file(project_root / REGISTRY_REL)},
    ])

    summary = {
        "type": "br_quartet_restoration_runtime_validation_canonical_integration_evidence_summary",
        "format_version": 1,
        "tool_version": version,
        "status": "bathroom_water_visibility_transparency_profile_canonically_runtime_validated_shader_failures_and_event_deferrals_preserved_no_game_write",
        "profile_rows": 15,
        "runtime_validated_profile_rows": 1,
        "runtime_validated_profile_ids": [B_PROFILE],
        "production_eligible_profile_rows": 1,
        "confirmed_semantics_rows": 1,
        "confirmed_semantics": "water_visibility_transparency_restoration",
        "confirmed_field": "home_bathroom",
        "runtime_failed_shader_profile_rows": 2,
        "runtime_failed_shader_profile_ids": [W_PROFILE, H_PROFILE],
        "deferred_event_profile_rows": 12,
        "event_group_runtime_safe": True,
        "event_group_visual_effect_confirmed": False,
        "shader_fix_direction_rows": 6,
        "core_return_bundle_sha256": EXPECTED_CORE_RETURN_SHA256,
        "local_promotion_evidence_sha256": EXPECTED_PROMOTION_EVIDENCE_SHA256,
        "generated_manifest_root": ".local/build/quartet_restoration/core_profiles/generated",
        "policy": {
            "runtime_validation_inferred": False,
            "only_explicit_runtime_results_persisted": True,
            "failed_shaders_excluded_from_normal_composition": True,
            "event_profiles_individually_runtime_validated": False,
            "core_modified": False,
            "translation_modified": False,
            "legacy_dlc_modified": False,
            "installed_game_modified": False,
            "git_modified": False,
            "pak_built_or_repacked": False,
            "transaction_prepare_called": False,
            "transaction_commit_called": False,
            "proprietary_payloads_in_report": False,
        },
        "next_action": "Normal composition may include only the validated bathroom-water profile. Keep both shader profiles excluded and the twelve event profiles deferred. Investigate repaired swater and heightfog variants per program through the Fast Test Lab before any future runtime promotion.",
    }
    atomic_json(evidence_dir / "SUMMARY.json", summary)

    report_root.mkdir(parents=True, exist_ok=True)
    archive = report_root / REPORT_NAME
    temporary = archive.with_name(archive.name + f".tmp.{os.getpid()}")
    completed = subprocess.run(
        ["tar", "--zstd", "-cf", str(temporary), "-C", str(report_root), REPORT_DIR_NAME],
        text=True,
        capture_output=True,
    )
    require(completed.returncode == 0, "failed to create evidence archive: " + (completed.stderr.strip() or completed.stdout.strip()))
    os.replace(temporary, archive)
    return archive


def integrate(project_root: Path, *, generator=None, regenerate: bool = True) -> tuple[Path, list[dict[str, object]], dict[str, object]]:
    project_root = project_root.expanduser().resolve()
    require(project_root.is_dir(), f"project root does not exist: {project_root}")
    version = read_version(project_root)
    if generator is None:
        generator = load_module(
            project_root / "workstreams/quartet_restoration/generate_core_profile_manifests.py",
            "generate_core_profile_manifests_for_runtime_integration",
        )
    registry = json.loads((project_root / REGISTRY_REL).read_text(encoding="utf-8"))
    decisions = validate_registry(registry, generator.CURRENT_PROFILE_SPECS)
    if regenerate:
        _, _, manifests = generator.generate_manifests(project_root=project_root, create_report_archive=True)
    else:
        manifests = [generator.build_manifest(spec, version, decisions[spec.profile_id]) for spec in generator.CURRENT_PROFILE_SPECS]
    validate_manifests(manifests, generator.CURRENT_PROFILE_SPECS, decisions, version)
    archive = build_report(project_root, generator, registry, manifests, version)
    return archive, manifests, registry


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", required=True)
    parser.add_argument("--no-regenerate", action="store_true", help="Validate canonical metadata without reading local profile PAKs.")
    args = parser.parse_args()
    archive, manifests, _ = integrate(Path(args.project_root), regenerate=not args.no_regenerate)
    print(f"Runtime-validated profiles: {sum(row['runtime_validated'] is True for row in manifests)}")
    print(f"Validated profile: {B_PROFILE}")
    print(f"Evidence: {archive}")
    print(f"Evidence SHA-256: {sha256_file(archive)}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (IntegrationError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
