#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import shutil
import subprocess
from collections import defaultdict
from pathlib import Path, PurePosixPath
from typing import Any, Iterable, Mapping, Sequence

TOOL_VERSION = "0.1.53"
STAGE134_ARCHIVE = "BR_quartet_restoration_effect_posteffect_namespace_member_saturation_evidence.tar.zst"
STAGE134_SHA256 = "597238b7b85606b07e50131428a028b37f2233a83fc2f0c063bd812a39738263"
STAGE134_DIR = "effect_posteffect_namespace_member_saturation_evidence"
STAGE134_SUMMARY_SHA256 = "4459b5a464015d7cabd09b44e7d60c26b31287765014f33a7ccc1221ff1530ce"
REPORT_DIR = "effect_posteffect_member_role_format_classification_evidence"
REPORT_ARCHIVE = "BR_quartet_restoration_effect_posteffect_member_role_format_classification_evidence.tar.zst"
FORBIDDEN_EXTENSIONS = (
    ".pak", ".g1e", ".g1em", ".g1m", ".g1s", ".g1t", ".g1pf",
    ".elixir", ".elixir.gz", ".ebd", ".ebm", ".kps",
)


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def safe_relative(value: str, label: str) -> str:
    path = PurePosixPath(str(value).replace("\\", "/"))
    require(bool(path.parts), f"empty {label}")
    require(not path.is_absolute() and ".." not in path.parts, f"unsafe {label}: {value}")
    return path.as_posix()


def read_tsv(path: Path) -> list[dict[str, str]]:
    require(path.is_file(), f"missing TSV: {path}")
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


def atomic_json(path: Path, value: Mapping[str, Any]) -> None:
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def make_archive(source: Path, output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(output.name + ".tmp")
    temporary.unlink(missing_ok=True)
    completed = subprocess.run(
        ["tar", "--zstd", "-cf", str(temporary), "-C", str(source.parent), source.name],
        text=True,
        capture_output=True,
    )
    require(completed.returncode == 0, completed.stderr.strip() or "archive creation failed")
    os.replace(temporary, output)


def extract_report(archive: Path, destination: Path, expected_root: str) -> Path:
    listed = subprocess.run(["tar", "--zstd", "-tf", str(archive)], text=True, capture_output=True)
    require(listed.returncode == 0, listed.stderr.strip() or f"cannot list {archive}")
    names = [safe_relative(line, "report member") for line in listed.stdout.splitlines() if line.strip()]
    require(names, f"empty report archive: {archive}")
    require({PurePosixPath(name).parts[0] for name in names} == {expected_root}, f"unexpected report root: {archive}")
    destination.mkdir(parents=True, exist_ok=True)
    completed = subprocess.run(["tar", "--zstd", "-xf", str(archive), "-C", str(destination)], text=True, capture_output=True)
    require(completed.returncode == 0, completed.stderr.strip() or f"cannot extract {archive}")
    root = destination / expected_root
    require(root.is_dir(), f"missing extracted report root: {root}")
    return root


def locate_stage134(report_root: Path, temporary: Path) -> tuple[Path, dict[str, Any], list[dict[str, Any]]]:
    archive = report_root / STAGE134_ARCHIVE
    require(archive.is_file(), f"missing stage-134 report: {archive}")
    archive_hash = sha256_file(archive)
    require(archive_hash == STAGE134_SHA256, f"unexpected stage-134 report SHA-256: {archive_hash}")
    root = report_root / STAGE134_DIR
    if not root.is_dir():
        root = extract_report(archive, temporary, STAGE134_DIR)
    summary_path = root / "SUMMARY.json"
    require(summary_path.is_file(), f"missing stage-134 summary: {summary_path}")
    summary_hash = sha256_file(summary_path)
    require(summary_hash == STAGE134_SUMMARY_SHA256, f"unexpected stage-134 summary SHA-256: {summary_hash}")
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    return root, summary, [
        {"input_id": "stage134", "relative_path": STAGE134_ARCHIVE, "sha256": archive_hash, "verified": True},
        {"input_id": "stage134_summary", "relative_path": f"{STAGE134_DIR}/SUMMARY.json", "sha256": summary_hash, "verified": True},
    ]


def format_family(extension: str) -> str:
    return {
        ".g1e": "effect_graph_g1e",
        ".g1em": "effect_model_binding_g1em",
        ".g1t": "effect_texture_g1t",
        ".kps": "posteffect_program_kps",
    }.get(extension, "other_format")


def size_delta_class(row: Mapping[str, str]) -> tuple[int, str]:
    classification = row["classification"]
    if classification == "added_in_target":
        return int(row["target_size"]), "target_added"
    if classification == "removed_in_target":
        return -int(row["source_size"]), "target_removed"
    delta = int(row["target_size"]) - int(row["source_size"])
    if delta == 0:
        return delta, "changed_same_size"
    if delta > 0:
        return delta, "changed_grew"
    return delta, "changed_shrank"


def recurrence_scope(row: Mapping[str, str]) -> str:
    if row["recurrent_role_family"] != "True":
        return "singleton_or_unique_role"
    paths = int(row["container_path_rows"])
    if paths >= 3:
        return "three_container_recurrence"
    if paths == 2:
        return "two_container_recurrence"
    return "repeated_within_single_container"


def role_triage(extension: str, scope: str) -> str:
    if extension == ".kps":
        return "posteffect_program_family"
    if extension == ".g1em":
        return "effect_model_binding_family"
    if extension == ".g1t":
        return "effect_texture_family"
    if scope == "three_container_recurrence":
        return "cross_character_recurrent_effect_graph_family"
    if scope == "two_container_recurrence":
        return "bounded_cross_container_effect_graph_family"
    return "unique_or_singleton_effect_graph_family"


def build_report(
    project_root: Path,
    report_root: Path | None = None,
    output_report_root: Path | None = None,
    create_archive: bool = True,
):
    project_root = project_root.resolve()
    report_root = (report_root or project_root / ".local/reports/quartet_restoration").resolve()
    output_report_root = (output_report_root or report_root).resolve()
    temporary = output_report_root / ".stage135_prerequisite_extract"
    if temporary.exists():
        shutil.rmtree(temporary)
    stage_root, stage_summary, input_hashes = locate_stage134(report_root, temporary)

    require(stage_summary.get("tool_version") == "0.1.52", "stage-134 tool version mismatch")
    require(stage_summary.get("container_path_rows") == 7, "stage-134 container count mismatch")
    require(stage_summary.get("member_rows") == 694, "stage-134 member count mismatch")
    require(stage_summary.get("nonidentical_member_rows") == 658, "stage-134 non-identical member count mismatch")
    require(stage_summary.get("member_role_family_rows") == 602, "stage-134 role-family count mismatch")
    require(stage_summary.get("recurrent_member_role_family_rows") == 32, "stage-134 recurrent role count mismatch")
    require(stage_summary.get("bounded_shader_candidate_rows") == 15, "stage-134 shader candidate count mismatch")
    require(stage_summary.get("resolved_shader_dependency_binding_rows") == 0, "stage-134 unexpectedly resolved a shader binding")
    require(stage_summary.get("skipped_rows") == 0, "stage-134 has skipped rows")

    raw_ledger = read_tsv(stage_root / "EFFECT_POSTEFFECT_MEMBER_LEDGER.tsv")
    raw_roles = read_tsv(stage_root / "EFFECT_POSTEFFECT_MEMBER_ROLE_FAMILIES.tsv")
    raw_paths = read_tsv(stage_root / "EFFECT_POSTEFFECT_PATH_SUMMARY.tsv")
    raw_shaders = read_tsv(stage_root / "BOUNDED_SHADER_STATIC_DEPENDENCY_AUDIT.tsv")

    role_by_key: dict[tuple[str, str, str], dict[str, str]] = {}
    role_rows: list[dict[str, Any]] = []
    for row in raw_roles:
        scope = recurrence_scope(row)
        enriched = {
            **row,
            "format_family": format_family(row["member_extension"]),
            "recurrence_scope": scope,
            "format_triage_classification": role_triage(row["member_extension"], scope),
            "visual_or_censorship_semantics_confirmed": False,
            "runtime_confirmed": False,
            "write_authorized": False,
        }
        role_rows.append(enriched)
        key = (row["normalized_member_role"], row["member_extension"], row["classification"])
        require(key not in role_by_key, f"duplicate role family key: {key}")
        role_by_key[key] = row

    member_rows: list[dict[str, Any]] = []
    for row in raw_ledger:
        if row["classification"] == "identical":
            continue
        delta, delta_class = size_delta_class(row)
        key = (row["normalized_member_role"], row["member_extension"], row["classification"])
        role = role_by_key.get(key)
        require(role is not None, f"missing role family for member: {key}")
        scope = recurrence_scope(role)
        member_rows.append({
            **row,
            "size_delta": delta,
            "delta_size_class": delta_class,
            "format_family": format_family(row["member_extension"]),
            "recurrence_scope": scope,
            "format_triage_classification": role_triage(row["member_extension"], scope),
            "visual_or_censorship_semantics_confirmed": False,
            "runtime_confirmed": False,
            "write_authorized": False,
        })

    aggregate: dict[tuple[str, str, str, str, str], dict[str, Any]] = {}
    for row in member_rows:
        key = (
            row["namespace"], row["format_family"], row["member_extension"],
            row["classification"], row["delta_size_class"],
        )
        entry = aggregate.setdefault(key, {
            "namespace": key[0],
            "format_family": key[1],
            "member_extension": key[2],
            "classification": key[3],
            "delta_size_class": key[4],
            "member_rows": 0,
            "container_path_rows": set(),
            "role_family_rows": set(),
            "recurrent_member_rows": 0,
            "total_absolute_size_delta": 0,
            "visual_or_censorship_semantics_confirmed": False,
            "write_authorized": False,
        })
        entry["member_rows"] += 1
        entry["container_path_rows"].add(row["normalized_path"])
        entry["role_family_rows"].add((row["normalized_member_role"], row["classification"]))
        if row["recurrence_scope"] != "singleton_or_unique_role":
            entry["recurrent_member_rows"] += 1
        entry["total_absolute_size_delta"] += abs(int(row["size_delta"]))
    format_rows: list[dict[str, Any]] = []
    for entry in aggregate.values():
        format_rows.append({
            **entry,
            "container_path_rows": len(entry["container_path_rows"]),
            "role_family_rows": len(entry["role_family_rows"]),
        })
    format_rows.sort(key=lambda row: (row["namespace"], row["format_family"], row["classification"], row["delta_size_class"]))

    burden: dict[str, dict[str, Any]] = {}
    for base in raw_paths:
        burden[base["normalized_path"]] = {
            "namespace": base["namespace"],
            "normalized_path": base["normalized_path"],
            "nonidentical_member_rows": 0,
            "g1e_member_rows": 0,
            "g1em_member_rows": 0,
            "g1t_member_rows": 0,
            "kps_member_rows": 0,
            "recurrent_member_rows": 0,
            "unique_or_singleton_member_rows": 0,
            "changed_same_size_rows": 0,
            "changed_grew_rows": 0,
            "changed_shrank_rows": 0,
            "target_added_rows": 0,
            "visual_or_censorship_semantics_confirmed": False,
            "write_authorized": False,
        }
    for row in member_rows:
        entry = burden[row["normalized_path"]]
        entry["nonidentical_member_rows"] += 1
        ext_key = {".g1e": "g1e_member_rows", ".g1em": "g1em_member_rows", ".g1t": "g1t_member_rows", ".kps": "kps_member_rows"}[row["member_extension"]]
        entry[ext_key] += 1
        if row["recurrence_scope"] == "singleton_or_unique_role":
            entry["unique_or_singleton_member_rows"] += 1
        else:
            entry["recurrent_member_rows"] += 1
        entry[f"{row['delta_size_class']}_rows"] += 1
    burden_rows = [burden[key] for key in sorted(burden)]

    shader_rows: list[dict[str, Any]] = []
    for row in raw_shaders:
        require(row["dependency_binding_resolved"] == "False", f"unexpected resolved shader binding: {row['normalized_path']}")
        shader_rows.append({
            **row,
            "stage135_disposition": "carry_forward_unresolved_no_independent_binding_channel",
            "visual_or_censorship_semantics_confirmed": False,
            "runtime_confirmed": False,
            "write_authorized": False,
        })

    output = output_report_root / REPORT_DIR
    if output.exists():
        shutil.rmtree(output)
    output.mkdir(parents=True)
    write_tsv(output / "INPUT_HASHES.tsv", ["input_id", "relative_path", "sha256", "verified"], input_hashes)
    write_tsv(output / "EFFECT_POSTEFFECT_MEMBER_FORMAT_CLASSIFICATION.tsv", list(member_rows[0].keys()), member_rows)
    write_tsv(output / "EFFECT_POSTEFFECT_MEMBER_ROLE_FORMAT_CLASSIFICATION.tsv", list(role_rows[0].keys()), role_rows)
    write_tsv(output / "EFFECT_POSTEFFECT_FORMAT_FAMILY_SUMMARY.tsv", list(format_rows[0].keys()), format_rows)
    write_tsv(output / "EFFECT_POSTEFFECT_CONTAINER_FORMAT_BURDEN.tsv", list(burden_rows[0].keys()), burden_rows)
    write_tsv(output / "BOUNDED_SHADER_UNRESOLVED_CARRY_FORWARD.tsv", list(shader_rows[0].keys()), shader_rows)

    recurrent_roles = [row for row in role_rows if row["recurrence_scope"] != "singleton_or_unique_role"]
    summary = {
        "type": "br_quartet_restoration_effect_posteffect_member_role_format_classification_evidence_summary",
        "format_version": 1,
        "tool_version": TOOL_VERSION,
        "status": "effect_posteffect_member_roles_and_format_families_classified_metadata_only_semantics_unresolved_no_write",
        "stage134_report_sha256": STAGE134_SHA256,
        "stage134_summary_sha256": STAGE134_SUMMARY_SHA256,
        "container_path_rows": len(burden_rows),
        "effect_container_path_rows": sum(row["namespace"] == "effect" for row in burden_rows),
        "posteffect_container_path_rows": sum(row["namespace"] == "posteffect" for row in burden_rows),
        "nonidentical_member_rows": len(member_rows),
        "member_role_family_rows": len(role_rows),
        "recurrent_member_role_family_rows": len(recurrent_roles),
        "three_container_recurrent_role_family_rows": sum(row["recurrence_scope"] == "three_container_recurrence" for row in role_rows),
        "two_container_recurrent_role_family_rows": sum(row["recurrence_scope"] == "two_container_recurrence" for row in role_rows),
        "unique_or_singleton_member_role_family_rows": sum(row["recurrence_scope"] == "singleton_or_unique_role" for row in role_rows),
        "recurrent_role_member_rows": sum(int(row["member_rows"]) for row in recurrent_roles),
        "unique_or_singleton_role_member_rows": sum(int(row["member_rows"]) for row in role_rows if row["recurrence_scope"] == "singleton_or_unique_role"),
        "g1e_member_rows": sum(row["member_extension"] == ".g1e" for row in member_rows),
        "g1em_member_rows": sum(row["member_extension"] == ".g1em" for row in member_rows),
        "g1t_member_rows": sum(row["member_extension"] == ".g1t" for row in member_rows),
        "kps_member_rows": sum(row["member_extension"] == ".kps" for row in member_rows),
        "g1e_role_family_rows": sum(row["member_extension"] == ".g1e" for row in role_rows),
        "g1em_role_family_rows": sum(row["member_extension"] == ".g1em" for row in role_rows),
        "g1t_role_family_rows": sum(row["member_extension"] == ".g1t" for row in role_rows),
        "kps_role_family_rows": sum(row["member_extension"] == ".kps" for row in role_rows),
        "changed_same_size_member_rows": sum(row["delta_size_class"] == "changed_same_size" for row in member_rows),
        "changed_grew_member_rows": sum(row["delta_size_class"] == "changed_grew" for row in member_rows),
        "changed_shrank_member_rows": sum(row["delta_size_class"] == "changed_shrank" for row in member_rows),
        "target_added_member_rows": sum(row["delta_size_class"] == "target_added" for row in member_rows),
        "format_summary_rows": len(format_rows),
        "bounded_shader_candidate_rows": len(shader_rows),
        "resolved_shader_dependency_binding_rows": 0,
        "visual_or_censorship_semantics_confirmed_rows": 0,
        "runtime_confirmed_rows": 0,
        "write_authorized_rows": 0,
        "skipped_rows": 0,
        "policy": {
            "existing_evidence_only": True,
            "local_proprietary_payloads_read": False,
            "proprietary_payloads_in_report": False,
            "member_names_extensions_sizes_or_recurrence_treated_as_visual_semantics": False,
            "shader_binding_inferred_from_name_or_inactive_profile": False,
            "runtime_or_save_required": False,
            "pak_built_or_repacked": False,
            "installed_game_modified": False,
            "profile_or_registry_modified": False,
            "core_modified": False,
            "translation_modified": False,
            "legacy_dlc_modified": False,
            "git_modified": False,
        },
        "next_action": "Use the classified effect/posteffect format families to run format-specific static analysis of the 621 changed G1E members and 27 changed/added KPS members. Keep G1EM/G1T and all fifteen shaders unresolved unless an independent binding or semantic channel appears. Do not require saves or build Canary-all.",
    }
    atomic_json(output / "SUMMARY.json", summary)
    archive = output_report_root / REPORT_ARCHIVE
    if create_archive:
        make_archive(output, archive)
    if temporary.exists():
        shutil.rmtree(temporary)
    return (archive if create_archive else None), summary


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-root", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--report-root", type=Path)
    parser.add_argument("--output-report-root", type=Path)
    parser.add_argument("--no-archive", action="store_true")
    args = parser.parse_args()
    archive, summary = build_report(
        args.project_root,
        report_root=args.report_root,
        output_report_root=args.output_report_root,
        create_archive=not args.no_archive,
    )
    print(json.dumps(summary, indent=2, sort_keys=True))
    if archive:
        print(f"[effect-posteffect-format] report archive: {archive}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
