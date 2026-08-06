#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import subprocess
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

TOOL_VERSION = "0.1.50"
STAGE131_ARCHIVE = "BR_quartet_restoration_field_namespace_member_saturation_evidence.tar.zst"
STAGE131_SHA256 = "b3c7273404ad6d80206f59497e338f85169026fbf22df9b3eefb689f7e5ca32b"
STAGE131_DIR = "field_namespace_member_saturation_evidence"
STAGE131_SUMMARY_SHA256 = "a3e07a7d73cbf76152e5d82727ab219679c6f3059336ba1e694b717d4c0ee75f"
REPORT_DIR = "field_member_role_format_classification_evidence"
REPORT_ARCHIVE = "BR_quartet_restoration_field_member_role_format_classification_evidence.tar.zst"
FORBIDDEN_EXTENSIONS = (".pak", ".g1e", ".g1em", ".g1m", ".g1s", ".g1t", ".g1pf", ".elixir", ".elixir.gz", ".ebd", ".ebm")


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def read_tsv(path: Path) -> list[dict[str, str]]:
    require(path.is_file(), f"missing required TSV: {path}")
    with path.open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f, delimiter="\t"))


def write_tsv(path: Path, fields: Sequence[str], rows: Iterable[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(fields), delimiter="\t", lineterminator="\n", extrasaction="ignore")
        w.writeheader()
        for row in rows:
            w.writerow({key: row.get(key, "") for key in fields})


def atomic_json(path: Path, value: Mapping[str, Any]) -> None:
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def make_archive(source: Path, output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    tmp = output.with_name(output.name + ".tmp")
    tmp.unlink(missing_ok=True)
    cp = subprocess.run(["tar", "--zstd", "-cf", str(tmp), "-C", str(source.parent), source.name], text=True, capture_output=True)
    require(cp.returncode == 0, cp.stderr.strip() or "report archive creation failed")
    os.replace(tmp, output)


def format_family(extension: str) -> str:
    return {
        ".g1m": "model_geometry_g1m",
        ".g1co": "collision_g1co",
        ".g1t": "texture_g1t",
        ".g1s": "shader_g1s",
        ".opl2": "field_layout_opl2",
        ".ktf": "keyframe_table_ktf",
        ".khm": "khm_metadata",
        ".bin": "binary_table_bin",
        ".g1": "generic_g1_container",
        ".g": "generic_g_payload",
        ".": "dot_suffix_payload",
        "(none)": "extensionless_payload",
    }.get(extension, "other_format")


def delta_size_class(classification: str, size_delta: int) -> str:
    if classification == "added_in_target":
        return "target_added"
    if classification == "removed_in_target":
        return "target_removed"
    if size_delta == 0:
        return "changed_same_size"
    if size_delta > 0:
        return "changed_grew"
    return "changed_shrank"


def recurrence_scope(recurrent: bool, root_rows: int) -> str:
    if not recurrent:
        return "singleton_or_unique_role"
    if root_rows >= 10:
        return "broad_cross_scene_recurrence"
    if root_rows >= 2:
        return "bounded_cross_scene_recurrence"
    return "repeated_within_single_scene"


def role_classification(row: Mapping[str, str]) -> dict[str, Any]:
    roots = int(row["field_scene_root_rows"])
    recurrent = row["recurrent_role_family"] == "True"
    size_delta = int(row["size_delta"])
    scope = recurrence_scope(recurrent, roots)
    if scope == "broad_cross_scene_recurrence":
        triage = "broad_engine_or_format_candidate"
    elif scope == "bounded_cross_scene_recurrence":
        triage = "bounded_recurrent_format_candidate"
    elif scope == "repeated_within_single_scene":
        triage = "scene_local_repeated_candidate"
    else:
        triage = "unique_or_singleton_candidate"
    return {
        **row,
        "format_family": format_family(row["member_extension"]),
        "delta_size_class": delta_size_class(row["classification"], size_delta),
        "recurrence_scope": scope,
        "format_triage_classification": triage,
        "visual_or_censorship_semantics_confirmed": False,
        "runtime_confirmed": False,
        "write_authorized": False,
    }


def shape_classification(row: Mapping[str, str]) -> dict[str, Any]:
    archives = int(row["archive_rows"])
    roots = int(row["field_scene_root_rows"])
    recurrent = row["recurrent_shape"] == "True"
    if recurrent and roots >= 10:
        scope = "broad_cross_scene_archive_shape"
    elif recurrent:
        scope = "bounded_cross_scene_archive_shape"
    else:
        scope = "unique_archive_shape"
    return {
        **row,
        "archive_shape_scope": scope,
        "structural_recurrence_confirmed": recurrent and archives >= 2 and roots >= 2,
        "visual_or_censorship_semantics_confirmed": False,
        "runtime_confirmed": False,
        "write_authorized": False,
    }


def verify_prerequisite(report_root: Path) -> list[dict[str, Any]]:
    archive = report_root / STAGE131_ARCHIVE
    summary = report_root / STAGE131_DIR / "SUMMARY.json"
    require(archive.is_file(), f"missing stage-131 report: {archive}")
    require(summary.is_file(), f"missing stage-131 summary: {summary}")
    ah = sha256_file(archive)
    sh = sha256_file(summary)
    require(ah == STAGE131_SHA256, f"unexpected stage-131 report SHA-256: {ah}")
    require(sh == STAGE131_SUMMARY_SHA256, f"unexpected stage-131 summary SHA-256: {sh}")
    return [
        {"input_id": "stage131", "relative_path": STAGE131_ARCHIVE, "sha256": ah, "verified": True},
        {"input_id": "stage131_summary", "relative_path": f"{STAGE131_DIR}/SUMMARY.json", "sha256": sh, "verified": True},
    ]


def build_report(project_root: Path, report_root: Path | None = None, output_report_root: Path | None = None, create_archive: bool = True):
    project_root = project_root.resolve()
    report_root = (report_root or project_root / ".local/reports/quartet_restoration").resolve()
    output_report_root = (output_report_root or report_root).resolve()
    input_hashes = verify_prerequisite(report_root)
    source = report_root / STAGE131_DIR
    stage_summary = json.loads((source / "SUMMARY.json").read_text(encoding="utf-8"))
    require(stage_summary["tool_version"] == "0.1.49", "stage-131 tool version mismatch")
    require(stage_summary["archive_delta_shape_rows"] == 143, "stage-131 archive shape count mismatch")
    require(stage_summary["member_role_family_rows"] == 2796, "stage-131 member-role family count mismatch")

    raw_shapes = read_tsv(source / "FIELD_ARCHIVE_DELTA_SHAPE_GROUPS.tsv")
    raw_roles = read_tsv(source / "FIELD_MEMBER_ROLE_FAMILIES.tsv")
    raw_members = read_tsv(source / "FIELD_ARCHIVE_MEMBER_DELTAS.tsv")
    raw_roots = read_tsv(source / "FIELD_SCENE_ROOT_MEMBER_SUMMARY.tsv")

    shapes = [shape_classification(row) for row in raw_shapes]
    roles = [role_classification(row) for row in raw_roles]

    format_groups: dict[tuple[str, str, str, str], dict[str, Any]] = {}
    for row in roles:
        key = (row["format_family"], row["member_extension"], row["classification"], row["delta_size_class"])
        g = format_groups.setdefault(key, {
            "format_family": key[0], "member_extension": key[1], "classification": key[2], "delta_size_class": key[3],
            "role_family_rows": 0, "member_rows": 0, "field_scene_root_associations": 0,
            "recurrent_role_family_rows": 0, "broad_recurrent_role_family_rows": 0,
            "visual_or_censorship_semantics_confirmed": False, "write_authorized": False,
        })
        g["role_family_rows"] += 1
        g["member_rows"] += int(row["member_rows"])
        g["field_scene_root_associations"] += int(row["field_scene_root_rows"])
        if row["recurrent_role_family"] == "True":
            g["recurrent_role_family_rows"] += 1
        if row["recurrence_scope"] == "broad_cross_scene_recurrence":
            g["broad_recurrent_role_family_rows"] += 1
    format_rows = sorted(format_groups.values(), key=lambda r: (-r["member_rows"], r["format_family"], r["classification"], r["delta_size_class"]))

    role_lookup = {
        (r["normalized_member_role"], r["member_extension"], r["classification"], r["size_delta"]): r
        for r in roles
    }
    root_stats: dict[str, Counter[str]] = defaultdict(Counter)
    for row in raw_members:
        if row["classification"] == "identical":
            continue
        root = row["field_scene_root"]
        key = (row["normalized_member_role"], row["member_extension"], row["classification"], row["size_delta"])
        role = role_lookup.get(key)
        root_stats[root]["nonidentical_member_rows"] += 1
        root_stats[root][format_family(row["member_extension"])] += 1
        if role:
            root_stats[root][role["recurrence_scope"]] += 1
    root_rows = []
    for base in raw_roots:
        root = base["field_scene_root"]
        c = root_stats[root]
        root_rows.append({
            "priority": int(base["priority"]),
            "field_scene_root": root,
            "nonidentical_member_rows": c["nonidentical_member_rows"],
            "broad_recurrent_member_rows": c["broad_cross_scene_recurrence"],
            "bounded_recurrent_member_rows": c["bounded_cross_scene_recurrence"],
            "scene_local_repeated_member_rows": c["repeated_within_single_scene"],
            "unique_or_singleton_member_rows": c["singleton_or_unique_role"],
            "model_geometry_member_rows": c["model_geometry_g1m"],
            "collision_member_rows": c["collision_g1co"],
            "texture_member_rows": c["texture_g1t"],
            "shader_member_rows": c["shader_g1s"],
            "layout_member_rows": c["field_layout_opl2"],
            "semantic_classification": "unassigned",
            "runtime_confirmed": False,
            "write_authorized": False,
            "safe_next_discovery": "separate broad recurrent format churn from bounded scene-local format deltas; do not infer visual meaning",
        })
    root_rows.sort(key=lambda r: (-r["unique_or_singleton_member_rows"], -r["nonidentical_member_rows"], r["field_scene_root"]))
    for i, row in enumerate(root_rows, 1): row["priority"] = i

    recurrent_roles = [r for r in roles if r["recurrent_role_family"] == "True"]
    broad_roles = [r for r in roles if r["recurrence_scope"] == "broad_cross_scene_recurrence"]
    bounded_roles = [r for r in roles if r["recurrence_scope"] == "bounded_cross_scene_recurrence"]
    local_roles = [r for r in roles if r["recurrence_scope"] == "repeated_within_single_scene"]
    recurrent_shapes = [r for r in shapes if r["structural_recurrence_confirmed"]]

    out = output_report_root / REPORT_DIR
    if out.exists():
        import shutil
        shutil.rmtree(out)
    out.mkdir(parents=True)
    write_tsv(out / "INPUT_HASHES.tsv", ["input_id", "relative_path", "sha256", "verified"], input_hashes)
    write_tsv(out / "FIELD_ARCHIVE_DELTA_SHAPE_CLASSIFICATION.tsv", list(shapes[0].keys()), shapes)
    write_tsv(out / "FIELD_MEMBER_ROLE_FORMAT_CLASSIFICATION.tsv", list(roles[0].keys()), roles)
    write_tsv(out / "FIELD_FORMAT_FAMILY_SUMMARY.tsv", list(format_rows[0].keys()), format_rows)
    write_tsv(out / "FIELD_SCENE_ROOT_FORMAT_BURDEN.tsv", list(root_rows[0].keys()), root_rows)

    summary = {
        "type": "br_quartet_restoration_field_member_role_format_classification_evidence_summary",
        "format_version": 1,
        "tool_version": TOOL_VERSION,
        "status": "field_recurrent_member_roles_and_format_families_classified_metadata_only_semantics_unresolved_no_write",
        "stage131_report_sha256": STAGE131_SHA256,
        "stage131_summary_sha256": STAGE131_SUMMARY_SHA256,
        "archive_delta_shape_rows": len(shapes),
        "recurrent_archive_delta_shape_rows": len(recurrent_shapes),
        "broad_recurrent_archive_delta_shape_rows": sum(r["archive_shape_scope"] == "broad_cross_scene_archive_shape" for r in shapes),
        "member_role_family_rows": len(roles),
        "recurrent_member_role_family_rows": len(recurrent_roles),
        "broad_recurrent_member_role_family_rows": len(broad_roles),
        "bounded_recurrent_member_role_family_rows": len(bounded_roles),
        "scene_local_repeated_member_role_family_rows": len(local_roles),
        "unique_or_singleton_member_role_family_rows": sum(r["recurrence_scope"] == "singleton_or_unique_role" for r in roles),
        "recurrent_role_member_rows": sum(int(r["member_rows"]) for r in recurrent_roles),
        "broad_recurrent_role_member_rows": sum(int(r["member_rows"]) for r in broad_roles),
        "unique_or_singleton_role_member_rows": sum(int(r["member_rows"]) for r in roles if r["recurrence_scope"] == "singleton_or_unique_role"),
        "format_summary_rows": len(format_rows),
        "field_scene_root_rows": len(root_rows),
        "g1m_role_family_rows": sum(r["member_extension"] == ".g1m" for r in roles),
        "g1co_role_family_rows": sum(r["member_extension"] == ".g1co" for r in roles),
        "g1t_role_family_rows": sum(r["member_extension"] == ".g1t" for r in roles),
        "g1s_role_family_rows": sum(r["member_extension"] == ".g1s" for r in roles),
        "visual_or_censorship_semantics_confirmed_rows": 0,
        "runtime_confirmed_rows": 0,
        "write_authorized_rows": 0,
        "policy": {
            "existing_evidence_only": True,
            "local_proprietary_payloads_read": False,
            "proprietary_payloads_in_report": False,
            "field_root_or_member_names_treated_as_visual_semantics": False,
            "runtime_or_save_required": False,
            "pak_built_or_repacked": False,
            "installed_game_modified": False,
            "profile_or_registry_modified": False,
            "core_modified": False,
            "translation_modified": False,
            "legacy_dlc_modified": False,
            "git_modified": False,
        },
        "next_action": "Run the separate 214-path shader executable/signature/reflection sweep, then use this field classification to prioritize bounded non-systemic field deltas. Do not require saves or build Canary-all.",
    }
    atomic_json(out / "SUMMARY.json", summary)
    archive = output_report_root / REPORT_ARCHIVE
    if create_archive:
        make_archive(out, archive)
    return archive if create_archive else None, summary


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--project-root", type=Path, default=Path(__file__).resolve().parents[2])
    p.add_argument("--report-root", type=Path)
    p.add_argument("--output-report-root", type=Path)
    p.add_argument("--no-archive", action="store_true")
    a = p.parse_args()
    archive, summary = build_report(a.project_root, a.report_root, a.output_report_root, not a.no_archive)
    print(json.dumps(summary, indent=2, sort_keys=True))
    if archive: print(f"[field-format] report archive: {archive}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
