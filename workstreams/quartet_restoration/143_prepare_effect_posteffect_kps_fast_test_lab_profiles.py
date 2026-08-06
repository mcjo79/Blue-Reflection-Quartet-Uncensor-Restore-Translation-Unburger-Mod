#!/usr/bin/env python3
"""Stage 143: prepare two isolated, reversible KPS Fast Test Lab profiles.

Consumes the immutable stage-142 metadata report and the two local KPS
prototypes that stage 142 wrote under .local/build. It verifies the exact
Quartet PACK10_01 baseline, replaces exactly one KPS member inside the target
pe_pack Elixir per profile, repacks and fully re-extracts two local PAKs, and
writes two runtime-unvalidated core profile manifests. Nothing is installed and
normal composition remains unable to select these profiles.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import importlib.util
import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path, PurePosixPath
from typing import Any, Iterable, Mapping, Sequence

TOOL_VERSION = "0.1.61"
REPORT_DIR = "effect_posteffect_kps_fast_test_lab_profile_preparation_evidence"
REPORT_NAME = "BR_quartet_restoration_effect_posteffect_kps_fast_test_lab_profile_preparation_evidence.tar.zst"
STAGE142_NAME = "BR_quartet_restoration_effect_posteffect_kps_local_no_install_prototype_evidence.tar.zst"
STAGE142_SHA256 = "35b5000b88dff089371087e82ec9f4bbcd87d30fdb059762133cef8b2d244134"
STAGE142_DIR = "effect_posteffect_kps_local_no_install_prototype_evidence"
STAGE142_SUMMARY_SHA256 = "09d497cc75a7196291b084ee140fc8c95c6bafb321c829baa1d92e7169acb8ad"
TARGET_RELATIVE_PATH = "Data/PACK10_01.PAK"
EXPECTED_BASELINE_SHA256 = "cc44e01cca2b1f68714dbe6a3c51b3e3894e612add1e440285e77fd4da5a00b1"
EXPECTED_BASELINE_SIZE = 194151990
PARENT_SUFFIX = "data/b1/x64/posteffect/pe_pack.elixir.gz"
PROFILE_ROOT_REL = Path(".local/build/quartet_restoration/fast_test_lab/kps_profiles_0.1.61")
MANIFEST_ROOT_REL = Path(".local/build/quartet_restoration/core_profiles/fast_test_lab")
EXPECTED_MEMBER_NAMES = {"PostEffectGamma.kps", "PostEffectGlowLight.kps"}
FORBIDDEN_REPORT_EXTENSIONS = (
    ".pak", ".kps", ".dxbc", ".elixir", ".elixir.gz", ".g1e", ".g1em",
    ".g1m", ".g1s", ".g1t", ".ebd", ".ebm",
)


class FastTestProfileError(RuntimeError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise FastTestProfileError(message)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def parse_bool(value: object) -> bool:
    return str(value).strip().casefold() in {"1", "true", "yes", "y"}


def read_tsv(path: Path) -> list[dict[str, str]]:
    require(path.is_file(), f"missing TSV: {path}")
    with path.open(encoding="utf-8", newline="") as handle:
        return [dict(row) for row in csv.DictReader(handle, delimiter="\t")]


def write_tsv(path: Path, fields: Sequence[str], rows: Iterable[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(fields), delimiter="\t", lineterminator="\n", extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fields})


def atomic_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def safe_relative(value: str, label: str) -> str:
    path = PurePosixPath(str(value).replace("\\", "/"))
    require(bool(path.parts) and not path.is_absolute() and ".." not in path.parts, f"unsafe {label}: {value}")
    return path.as_posix()


def require_within(path: Path, root: Path, label: str) -> None:
    try:
        path.resolve().relative_to(root.resolve())
    except ValueError as exc:
        raise FastTestProfileError(f"{label} leaves approved root: {path}") from exc


def load_module(path: Path, name: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    require(spec is not None and spec.loader is not None, f"cannot load module: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def extract_report(archive: Path, destination: Path, *, expected_sha256: str = STAGE142_SHA256) -> Path:
    require(archive.is_file(), f"missing stage-142 report: {archive}")
    actual = sha256_file(archive)
    require(actual == expected_sha256, f"stage-142 report SHA-256 drift: {actual}")
    listed = subprocess.run(["tar", "--zstd", "-tf", str(archive)], text=True, capture_output=True)
    require(listed.returncode == 0, listed.stderr.strip() or "cannot list stage-142 report")
    names = [safe_relative(line.strip(), "stage-142 archive member") for line in listed.stdout.splitlines() if line.strip()]
    require(names and {PurePosixPath(name).parts[0] for name in names} == {STAGE142_DIR}, "unexpected stage-142 report root")
    destination.mkdir(parents=True, exist_ok=True)
    extracted = subprocess.run(["tar", "--zstd", "-xf", str(archive), "-C", str(destination)], text=True, capture_output=True)
    require(extracted.returncode == 0, extracted.stderr.strip() or "cannot extract stage-142 report")
    root = destination / STAGE142_DIR
    require(root.is_dir(), f"missing extracted stage-142 root: {root}")
    return root


def make_archive(source: Path, output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(output.name + ".tmp")
    temporary.unlink(missing_ok=True)
    completed = subprocess.run(["tar", "--zstd", "-cf", str(temporary), "-C", str(source.parent), source.name], text=True, capture_output=True)
    require(completed.returncode == 0, completed.stderr.strip() or "evidence archive creation failed")
    os.replace(temporary, output)


def profile_id_for(member_name: str, prototype_sha256: str) -> str:
    stem = Path(member_name).stem.casefold()
    require(stem in {"posteffectgamma", "posteffectglowlight"}, f"unexpected KPS prototype: {member_name}")
    return f"fast_test_kps_{stem}_target_dword_{prototype_sha256[:12]}"


def load_stage142(
    project_root: Path,
    report_root: Path,
    temporary: Path,
    *,
    expected_archive_sha256: str = STAGE142_SHA256,
    expected_summary_sha256: str = STAGE142_SUMMARY_SHA256,
    prototype_root: Path | None = None,
) -> tuple[dict[str, Any], list[dict[str, Any]], Path]:
    archive = report_root / STAGE142_NAME
    root = report_root / STAGE142_DIR
    if not root.is_dir():
        root = extract_report(archive, temporary, expected_sha256=expected_archive_sha256)
    else:
        require(archive.is_file(), f"missing stage-142 archive beside extracted report: {archive}")
        require(sha256_file(archive) == expected_archive_sha256, "stage-142 archive hash drift")
    summary_path = root / "SUMMARY.json"
    require(summary_path.is_file(), "missing stage-142 SUMMARY.json")
    summary_hash = sha256_file(summary_path)
    require(summary_hash == expected_summary_sha256, f"stage-142 summary SHA-256 drift: {summary_hash}")
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    require(summary.get("tool_version") == "0.1.60", "stage-142 tool version drift")
    require(summary.get("status") == "kps_local_no_install_prototypes_built_all_preconditions_verified_dxbc_reparsed_no_pak_no_install_no_runtime_promotion", "stage-142 status drift")
    require(int(summary.get("kps_prototype_artifact_rows", -1)) == 2, "stage-142 prototype count drift")
    require(int(summary.get("kps_prototype_program_rows", -1)) == 15, "stage-142 program count drift")
    require(int(summary.get("kps_applied_target_dword_edit_rows", -1)) == 227, "stage-142 edit count drift")
    require(int(summary.get("kps_target_precondition_rows_verified", -1)) == 227, "stage-142 precondition count drift")
    require(int(summary.get("skipped_rows", -1)) == 0, "stage-142 contains skipped rows")
    policy = summary.get("policy") or {}
    require(policy.get("every_target_dword_precondition_verified") is True, "stage-142 precondition policy drift")
    require(policy.get("only_planned_dwords_and_dxbc_checksums_changed") is True, "stage-142 byte-scope policy drift")
    require(policy.get("installed_game_modified") is False and policy.get("pak_built_or_repacked") is False, "stage-142 write policy drift")

    rows = read_tsv(root / "KPS_LOCAL_PROTOTYPE_ARTIFACTS.tsv")
    require(len(rows) == 2, "stage-142 artifact table count drift")
    require({row["member_name"] for row in rows} == EXPECTED_MEMBER_NAMES, "stage-142 member set drift")
    prototype_root = (prototype_root or project_root / ".local/build/quartet_restoration/kps_target_dword_prototypes_0.1.60").resolve()
    require_within(prototype_root, project_root / ".local/build/quartet_restoration", "prototype root")
    parsed: list[dict[str, Any]] = []
    for row in rows:
        require(parse_bool(row["prototype_built"]), f"prototype not built: {row['member_name']}")
        require(parse_bool(row["all_target_preconditions_verified"]), f"prototype preconditions not verified: {row['member_name']}")
        require(parse_bool(row["all_programs_reparsed"]), f"prototype programs not reparsed: {row['member_name']}")
        require(parse_bool(row["all_dxbc_checksums_valid"]), f"prototype checksum invalid: {row['member_name']}")
        require(parse_bool(row["all_unplanned_bytes_preserved"]), f"prototype has unplanned changes: {row['member_name']}")
        member_name = Path(row["member_name"]).name
        path = prototype_root / member_name
        require(path.is_file(), f"missing local KPS prototype: {path}")
        require(path.stat().st_size == int(row["prototype_size"]), f"prototype size drift: {member_name}")
        require(sha256_file(path) == row["prototype_sha256"], f"prototype hash drift: {member_name}")
        parsed.append({**row, "prototype_path": path, "profile_id": profile_id_for(member_name, row["prototype_sha256"])})
    return summary, sorted(parsed, key=lambda row: row["member_name"].casefold()), root


def find_parent_member(members: Mapping[str, Mapping[str, Any]]) -> tuple[str, Mapping[str, Any]]:
    matches = [(key, row) for key, row in members.items() if str(row.get("name", "")).replace("\\", "/").casefold().endswith(PARENT_SUFFIX)]
    require(len(matches) == 1, f"expected exactly one pe_pack member in PACK10_01, found {len(matches)}")
    return matches[0]


def patch_same_size_earc_member(br: Any, stage70: Any, encoded_parent: Path, *, member_key: str, prototype: bytes, expected_target_sha256: str, label: str) -> tuple[bytes, dict[str, Any], list[dict[str, Any]]]:
    decoded, container, metadata = stage70.decode_parent(encoded_parent, 2 * 1024 * 1024 * 1024)
    before = br.parse_earc_payload(decoded, label=label, include_member_payloads=True)
    before_rows = {str(row["comparison_key"]): row for row in before.get("members", [])}
    selected = before_rows.get(member_key)
    require(selected is not None, f"pe_pack lacks selected member: {member_key}")
    target_payload = selected.get("payload")
    require(isinstance(target_payload, (bytes, bytearray)), f"selected KPS payload unavailable: {member_key}")
    target_payload = bytes(target_payload)
    require(sha256_bytes(target_payload) == expected_target_sha256, f"target KPS hash drift: {member_key}")
    require(len(target_payload) == len(prototype), f"prototype size differs from target KPS: {member_key}")
    start = int(selected["offset"])
    end = start + len(prototype)
    require(0 <= start <= end <= len(decoded), f"invalid KPS bounds: {member_key}")
    mutable = bytearray(decoded)
    mutable[start:end] = prototype
    patched_decoded = bytes(mutable)
    after = br.parse_earc_payload(patched_decoded, label=label + "#candidate", include_member_payloads=True)
    after_rows = {str(row["comparison_key"]): row for row in after.get("members", [])}
    require(set(before_rows) == set(after_rows), "pe_pack member set changed")
    verification: list[dict[str, Any]] = []
    for key in sorted(before_rows, key=str.casefold):
        left = before_rows[key]
        right = after_rows[key]
        changed = left["sha256"] != right["sha256"]
        expected_changed = key == member_key
        verified = (
            left["index"] == right["index"]
            and left["offset"] == right["offset"]
            and left["size"] == right["size"]
            and changed == expected_changed
            and (right["sha256"] == sha256_bytes(prototype) if expected_changed else right["sha256"] == left["sha256"])
        )
        verification.append({
            "member_key": key,
            "member_name": left.get("name", ""),
            "selected_for_profile": expected_changed,
            "target_sha256": left.get("sha256", ""),
            "candidate_sha256": right.get("sha256", ""),
            "target_size": left.get("size", ""),
            "candidate_size": right.get("size", ""),
            "target_offset": left.get("offset", ""),
            "candidate_offset": right.get("offset", ""),
            "verified": verified,
        })
    require(all(row["verified"] for row in verification), "pe_pack member verification failed")
    require(sum(bool(row["selected_for_profile"]) for row in verification) == 1, "pe_pack changed-member count drift")
    encoded = stage70.encode_parent(patched_decoded, container, metadata)
    return encoded, {"container": container, "decoded_size": len(decoded), "member_count": len(before_rows)}, verification


def build_report(
    project_root: Path,
    *,
    quartet_root: Path,
    gust_pak: Path,
    report_root: Path | None = None,
    output_report_root: Path | None = None,
    workspace_root: Path | None = None,
    prototype_root: Path | None = None,
    manifest_root: Path | None = None,
    baseline_archive: Path | None = None,
    create_archive: bool = True,
    timeout_seconds: int = 1800,
    expected_stage142_sha256: str = STAGE142_SHA256,
    expected_stage142_summary_sha256: str = STAGE142_SUMMARY_SHA256,
    expected_baseline_sha256: str = EXPECTED_BASELINE_SHA256,
    expected_baseline_size: int = EXPECTED_BASELINE_SIZE,
) -> tuple[Path | None, dict[str, Any]]:
    project_root = project_root.resolve()
    version_path = project_root / "workstreams/quartet_restoration/VERSION"
    require(version_path.is_file(), f"missing VERSION: {version_path}")
    version_text = version_path.read_text(encoding="utf-8").strip()
    version = tuple(int(part) for part in version_text.split("."))
    require(version >= (0, 1, 61), f"stage 143 requires quartet_restoration 0.1.61 or newer, found {version_text}")

    quartet_root = quartet_root.resolve()
    gust_pak = gust_pak.resolve()
    report_root = (report_root or project_root / ".local/reports/quartet_restoration").resolve()
    output_report_root = (output_report_root or report_root).resolve()
    workspace_root = (workspace_root or project_root / PROFILE_ROOT_REL).resolve()
    manifest_root = (manifest_root or project_root / MANIFEST_ROOT_REL).resolve()
    require_within(workspace_root, project_root / ".local/build/quartet_restoration", "profile workspace")
    require_within(manifest_root, project_root / ".local/build/quartet_restoration/core_profiles", "manifest root")
    require(gust_pak.is_file() and os.access(gust_pak, os.X_OK), f"gust_pak missing or not executable: {gust_pak}")

    installed_archive = (baseline_archive or quartet_root / TARGET_RELATIVE_PATH).resolve()
    if baseline_archive is None:
        require_within(installed_archive, quartet_root, "installed PACK10_01")
    require(installed_archive.is_file(), f"missing PACK10_01 baseline: {installed_archive}")
    baseline_sha = sha256_file(installed_archive)
    baseline_size = installed_archive.stat().st_size
    require(baseline_sha == expected_baseline_sha256, f"PACK10_01 baseline SHA-256 drift: {baseline_sha}")
    require(baseline_size == expected_baseline_size, f"PACK10_01 baseline size drift: {baseline_size}")

    output = output_report_root / REPORT_DIR
    archive_output = output_report_root / REPORT_NAME
    shutil.rmtree(output, ignore_errors=True)
    output.mkdir(parents=True, exist_ok=True)

    stage70 = load_module(project_root / "workstreams/quartet_restoration/prepare_bathroom_river_parent_elixir_repack_test.py", "stage143_stage70")
    stage134 = load_module(project_root / "workstreams/quartet_restoration/134_collect_effect_posteffect_namespace_member_saturation_evidence.py", "stage143_stage134")
    br = stage134.load_br_tool(project_root)

    with tempfile.TemporaryDirectory(prefix="br-stage143-") as temporary_text:
        temporary = Path(temporary_text)
        summary142, prototypes, _root142 = load_stage142(
            project_root,
            report_root,
            temporary / "stage142",
            expected_archive_sha256=expected_stage142_sha256,
            expected_summary_sha256=expected_stage142_summary_sha256,
            prototype_root=prototype_root,
        )
        baseline_extract = temporary / "baseline_extract"
        baseline_manifest_path, baseline_manifest = br._extract_pak_for_repack_test(
            archive=installed_archive,
            destination=baseline_extract,
            gust_pak=gust_pak,
            timeout_seconds=timeout_seconds,
            log_name="baseline_extract.log",
        )
        baseline_members = br._manifest_member_hashes(baseline_extract, baseline_manifest)
        baseline_signature = br._gust_manifest_semantic_signature(baseline_manifest)
        parent_key, parent_row = find_parent_member(baseline_members)
        parent_path = baseline_extract / Path(str(parent_row["name"]))
        require(parent_path.is_file(), f"extracted pe_pack missing: {parent_path}")
        parent_target_sha = sha256_file(parent_path)

        staging_workspace = workspace_root.with_name(workspace_root.name + ".tmp")
        staging_manifests = manifest_root.with_name(manifest_root.name + ".tmp")
        shutil.rmtree(staging_workspace, ignore_errors=True)
        shutil.rmtree(staging_manifests, ignore_errors=True)
        staging_workspace.mkdir(parents=True)
        staging_manifests.mkdir(parents=True)

        profile_rows: list[dict[str, Any]] = []
        parent_rows: list[dict[str, Any]] = []
        pak_rows: list[dict[str, Any]] = []
        validation_rows: list[dict[str, Any]] = []
        test_order_rows: list[dict[str, Any]] = []
        skipped_rows: list[dict[str, Any]] = []

        try:
            for test_order, artifact in enumerate(prototypes, start=1):
                profile_id = artifact["profile_id"]
                member_name = artifact["member_name"]
                member_key = artifact["member_key"]
                prototype_path = Path(artifact["prototype_path"])
                prototype = prototype_path.read_bytes()
                candidate_parent_bytes, parent_meta, member_verification = patch_same_size_earc_member(
                    br,
                    stage70,
                    parent_path,
                    member_key=member_key,
                    prototype=prototype,
                    expected_target_sha256=artifact["target_sha256"],
                    label=f"{PARENT_SUFFIX}:{profile_id}",
                )
                candidate_parent = staging_workspace / profile_id / "candidate_parent" / PARENT_SUFFIX
                candidate_parent.parent.mkdir(parents=True, exist_ok=True)
                candidate_parent.write_bytes(candidate_parent_bytes)
                candidate_parent_sha = sha256_file(candidate_parent)

                profile_root = staging_workspace / profile_id
                stage_dir = profile_root / "staging"
                verify_dir = profile_root / "verify"
                output_pak = profile_root / "output" / TARGET_RELATIVE_PATH
                output_pak.parent.mkdir(parents=True, exist_ok=True)
                br._copy_repack_input_tree(baseline_extract, stage_dir)
                stage_manifest_path = stage_dir / baseline_manifest_path.name
                stage_manifest = br._load_gust_pak_manifest(stage_manifest_path)
                staged_parent = stage_dir / Path(str(parent_row["name"]))
                require_within(staged_parent, stage_dir, "staged pe_pack")
                shutil.copy2(candidate_parent, staged_parent)
                stage_output = stage_dir / str(stage_manifest["safe_output_name"])
                stage_output.unlink(missing_ok=True)
                br._run_gust_pak(
                    gust_pak=gust_pak,
                    argument_name=stage_manifest_path.name,
                    cwd=stage_dir,
                    log_path=profile_root / "repack.log",
                    timeout_seconds=timeout_seconds,
                )
                require(stage_output.is_file(), f"gust_pak did not produce profile PAK: {profile_id}")
                shutil.move(stage_output, output_pak)
                output_sha = sha256_file(output_pak)
                output_size = output_pak.stat().st_size

                verify_manifest_path, verify_manifest = br._extract_pak_for_repack_test(
                    archive=output_pak,
                    destination=verify_dir,
                    gust_pak=gust_pak,
                    timeout_seconds=timeout_seconds,
                    log_name="verify_extract.log",
                )
                verify_members = br._manifest_member_hashes(verify_dir, verify_manifest)
                verify_signature = br._gust_manifest_semantic_signature(verify_manifest)
                manifest_differences = br._gust_manifest_metadata_differences(
                    baseline_manifest,
                    verify_manifest,
                    profile_id=profile_id,
                    modified_member_keys={parent_key},
                )
                stable_manifest_differences = sum(row.get("gate_effect") == "validation_gate" for row in manifest_differences)
                set_delta = set(baseline_members) ^ set(verify_members)
                changed_keys = sorted(
                    key for key in set(baseline_members) | set(verify_members)
                    if baseline_members.get(key, {}).get("sha256") != verify_members.get(key, {}).get("sha256")
                )
                require(not set_delta, f"PAK member set changed: {profile_id}")
                require(changed_keys == [parent_key], f"profile PAK changed unexpected members: {profile_id}:{changed_keys}")
                require(verify_signature == baseline_signature, f"PAK manifest semantic drift: {profile_id}")
                require(stable_manifest_differences == 0, f"stable PAK manifest drift: {profile_id}")
                verified_parent = verify_dir / Path(str(verify_members[parent_key]["name"]))
                require(sha256_file(verified_parent) == candidate_parent_sha, f"repacked pe_pack hash mismatch: {profile_id}")
                decoded_verified, _container, _metadata = stage70.decode_parent(verified_parent, 2 * 1024 * 1024 * 1024)
                parsed_verified = br.parse_earc_payload(decoded_verified, label=f"verify:{profile_id}", include_member_payloads=True)
                verified_kps = {str(row["comparison_key"]): row for row in parsed_verified.get("members", [])}.get(member_key)
                require(verified_kps is not None and verified_kps.get("sha256") == artifact["prototype_sha256"], f"repacked KPS mismatch: {profile_id}")
                require(sha256_file(installed_archive) == baseline_sha and installed_archive.stat().st_size == baseline_size, "installed PACK10_01 changed during build")

                workspace_rel = workspace_root.relative_to(project_root)
                manifest_root_rel = manifest_root.relative_to(project_root)
                final_output_rel = workspace_rel / profile_id / "output" / TARGET_RELATIVE_PATH
                manifest = {
                    "schema_version": 1,
                    "profile_id": profile_id,
                    "target_relative_path": TARGET_RELATIVE_PATH,
                    "baseline_sha256": baseline_sha,
                    "baseline_size": baseline_size,
                    "profile_sha256": output_sha,
                    "profile_size": output_size,
                    "local_profile_path": final_output_rel.as_posix(),
                    "changed_member_count": 1,
                    "changed_members": [str(parent_row["name"]).replace("\\", "/")],
                    "runtime_validated": False,
                    "workstream_id": "quartet_restoration",
                    "workstream_version": TOOL_VERSION,
                }
                atomic_json(staging_manifests / f"{profile_id}.json", manifest)

                for row in member_verification:
                    parent_rows.append({"profile_id": profile_id, **row})
                for key in sorted(baseline_members, key=str.casefold):
                    left = baseline_members[key]
                    right = verify_members[key]
                    pak_rows.append({
                        "profile_id": profile_id,
                        "member_key": key,
                        "member_name": left.get("name", ""),
                        "selected_parent_member": key == parent_key,
                        "baseline_sha256": left.get("sha256", ""),
                        "profile_sha256": right.get("sha256", ""),
                        "verified": (right.get("sha256") == candidate_parent_sha if key == parent_key else right.get("sha256") == left.get("sha256")),
                    })
                checks = {
                    "stage142_report_immutable": True,
                    "prototype_hash_and_size_verified": True,
                    "installed_baseline_exact": baseline_sha == expected_baseline_sha256 and baseline_size == expected_baseline_size,
                    "pe_pack_member_resolved_once": True,
                    "exactly_one_kps_changed_inside_pe_pack": sum(bool(row["selected_for_profile"]) for row in member_verification) == 1,
                    "all_other_pe_pack_members_preserved": all(bool(row["verified"]) for row in member_verification),
                    "exactly_one_pak_member_changed": changed_keys == [parent_key],
                    "all_other_pak_members_preserved": all(bool(row["verified"]) for row in pak_rows if row["profile_id"] == profile_id),
                    "pak_manifest_semantics_preserved": verify_signature == baseline_signature,
                    "repacked_kps_matches_prototype": verified_kps.get("sha256") == artifact["prototype_sha256"],
                    "profile_manifest_runtime_unvalidated": manifest["runtime_validated"] is False,
                    "installed_game_unchanged": sha256_file(installed_archive) == baseline_sha,
                }
                for name, passed in checks.items():
                    validation_rows.append({"profile_id": profile_id, "check_name": name, "passed": passed})
                require(all(checks.values()), f"profile validation failed: {profile_id}")

                profile_rows.append({
                    "profile_id": profile_id,
                    "test_order": test_order,
                    "member_name": member_name,
                    "member_key": member_key,
                    "prototype_sha256": artifact["prototype_sha256"],
                    "prototype_size": artifact["prototype_size"],
                    "candidate_parent_sha256": candidate_parent_sha,
                    "profile_pak_sha256": output_sha,
                    "profile_pak_size": output_size,
                    "target_relative_path": TARGET_RELATIVE_PATH,
                    "changed_parent_member": str(parent_row["name"]).replace("\\", "/"),
                    "manifest_relative_path": (manifest_root_rel / f"{profile_id}.json").as_posix(),
                    "local_profile_path": final_output_rel.as_posix(),
                    "runtime_validated": False,
                    "normal_composer_eligible": False,
                    "installed": False,
                })
                test_order_rows.append({
                    "test_order": test_order,
                    "profile_id": profile_id,
                    "variant": "gamma" if member_name == "PostEffectGamma.kps" else "glowlight",
                    "must_be_tested_alone": True,
                    "rollback_required_before_next_variant": True,
                    "runtime_validated_before_test": False,
                    "automatic_activation_authorized": False,
                })

            require(len(profile_rows) == 2, "Fast Test Lab profile count drift")
            require(sum(int(row["test_order"]) == 1 and row["member_name"] == "PostEffectGamma.kps" for row in profile_rows) == 1, "Gamma must be first")
            require(sum(int(row["test_order"]) == 2 and row["member_name"] == "PostEffectGlowLight.kps" for row in profile_rows) == 1, "GlowLight must be second")
            shutil.rmtree(workspace_root, ignore_errors=True)
            workspace_root.parent.mkdir(parents=True, exist_ok=True)
            os.replace(staging_workspace, workspace_root)
            shutil.rmtree(manifest_root, ignore_errors=True)
            manifest_root.parent.mkdir(parents=True, exist_ok=True)
            os.replace(staging_manifests, manifest_root)
        except Exception:
            shutil.rmtree(staging_workspace, ignore_errors=True)
            shutil.rmtree(staging_manifests, ignore_errors=True)
            raise

    write_tsv(output / "INPUT_HASHES.tsv", ["input_id", "relative_path", "sha256", "verified"], [
        {"input_id": "stage142_report", "relative_path": f".local/reports/quartet_restoration/{STAGE142_NAME}", "sha256": expected_stage142_sha256, "verified": True},
        {"input_id": "stage142_summary", "relative_path": f"{STAGE142_DIR}/SUMMARY.json", "sha256": expected_stage142_summary_sha256, "verified": True},
        {"input_id": "quartet_pack10_01_baseline", "relative_path": TARGET_RELATIVE_PATH, "sha256": baseline_sha, "verified": True},
        {"input_id": "target_pe_pack", "relative_path": str(parent_row["name"]).replace("\\", "/"), "sha256": parent_target_sha, "verified": True},
    ])
    write_tsv(output / "FAST_TEST_LAB_PROFILES.tsv", list(profile_rows[0]), profile_rows)
    write_tsv(output / "PE_PACK_MEMBER_VERIFICATION.tsv", list(parent_rows[0]), parent_rows)
    write_tsv(output / "PACK10_01_MEMBER_VERIFICATION.tsv", list(pak_rows[0]), pak_rows)
    write_tsv(output / "PROFILE_VALIDATIONS.tsv", ["profile_id", "check_name", "passed"], validation_rows)
    write_tsv(output / "FAST_TEST_ORDER.tsv", list(test_order_rows[0]), test_order_rows)
    write_tsv(output / "PARSER_SKIPPED.tsv", ["scope", "identity", "reason"], skipped_rows)

    summary = {
        "type": "br_quartet_restoration_effect_posteffect_kps_fast_test_lab_profile_preparation_evidence_summary",
        "format_version": 1,
        "tool_version": TOOL_VERSION,
        "status": "two_isolated_runtime_unvalidated_kps_fast_test_lab_profiles_built_and_reextracted_no_install",
        "stage142_report_sha256": expected_stage142_sha256,
        "stage142_summary_sha256": expected_stage142_summary_sha256,
        "target_relative_path": TARGET_RELATIVE_PATH,
        "baseline_sha256": baseline_sha,
        "baseline_size": baseline_size,
        "target_parent_member": str(parent_row["name"]).replace("\\", "/"),
        "target_parent_sha256": parent_target_sha,
        "fast_test_profile_rows": len(profile_rows),
        "gamma_profile_rows": sum(row["member_name"] == "PostEffectGamma.kps" for row in profile_rows),
        "glowlight_profile_rows": sum(row["member_name"] == "PostEffectGlowLight.kps" for row in profile_rows),
        "runtime_validated_profile_rows_created": 0,
        "normal_composer_eligible_profile_rows_created": 0,
        "profile_pak_rows_built": len(profile_rows),
        "profile_pak_full_reextraction_pass_rows": len(profile_rows),
        "profile_manifest_rows_written": len(profile_rows),
        "automatic_activation_rows": 0,
        "installed_artifact_rows": 0,
        "runtime_confirmed_rows": 0,
        "runtime_validated_bathroom_profile_rows_preserved": 1,
        "runtime_failed_shader_rows_preserved": 2,
        "skipped_rows": len(skipped_rows),
        "policy": {
            "local_proprietary_payloads_read": True,
            "local_profile_paks_built_outside_report": True,
            "proprietary_payloads_in_report": False,
            "one_kps_prototype_per_profile": True,
            "one_parent_elixir_member_changed_per_profile": True,
            "one_pack10_01_member_changed_per_profile": True,
            "profile_paks_fully_reextracted": True,
            "profiles_runtime_validated": False,
            "profiles_normal_composer_eligible": False,
            "test_order_gamma_before_glowlight": True,
            "rollback_required_between_variants": True,
            "automatic_activation_authorized": False,
            "installed_game_modified": False,
            "core_modified": False,
            "translation_modified": False,
            "legacy_dlc_modified": False,
            "git_modified": False,
        },
        "next_action": (
            "Upload this metadata-only report. Then run only the Gamma profile through the existing isolated shader-profile Fast Test Lab route, exit the game and rollback. "
            "Do not activate GlowLight until Gamma has a recorded result and the PACK10_01 baseline has been restored. Never set runtime_validated=true from profile construction alone."
        ),
    }
    atomic_json(output / "SUMMARY.json", summary)
    bad = [path for path in output.rglob("*") if path.is_file() and path.name.casefold().endswith(FORBIDDEN_REPORT_EXTENSIONS)]
    require(not bad, "proprietary payload extension in evidence report: " + ", ".join(str(path) for path in bad))
    archive = archive_output if create_archive else None
    if create_archive:
        make_archive(output, archive_output)
    return archive, summary


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path, required=True)
    parser.add_argument("--quartet-root", type=Path, required=True)
    parser.add_argument("--gust-pak", type=Path, required=True)
    parser.add_argument("--report-root", type=Path)
    parser.add_argument("--output-report-root", type=Path)
    parser.add_argument("--workspace-root", type=Path)
    parser.add_argument("--prototype-root", type=Path)
    parser.add_argument("--manifest-root", type=Path)
    parser.add_argument("--baseline-archive", type=Path)
    parser.add_argument("--timeout-seconds", type=int, default=1800)
    args = parser.parse_args(argv)
    archive, summary = build_report(
        args.project_root,
        quartet_root=args.quartet_root,
        gust_pak=args.gust_pak,
        report_root=args.report_root,
        output_report_root=args.output_report_root,
        workspace_root=args.workspace_root,
        prototype_root=args.prototype_root,
        manifest_root=args.manifest_root,
        baseline_archive=args.baseline_archive,
        timeout_seconds=args.timeout_seconds,
    )
    print(json.dumps(summary, indent=2, sort_keys=True))
    if archive is not None:
        print(f"[stage143] report archive: {archive}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
