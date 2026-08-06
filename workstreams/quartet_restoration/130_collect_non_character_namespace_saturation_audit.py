#!/usr/bin/env python3
"""Metadata-only saturation audit for non-character technical namespaces.

Stage 130 inventories every BR1-vs-Quartet asset-difference row outside
``data/x64/character``. Localization resources remain visible but are separated
from Restoration scope. The bounded Restoration candidate space is the set of
non-identical field, shader, effect and posteffect paths.

No payload is rehydrated, no visual/censorship semantics are assigned and no
write is authorized.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import subprocess
import sys
import tempfile
from collections import Counter, defaultdict
from pathlib import Path, PurePosixPath
from typing import Any, Iterable, Mapping, Sequence

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT_DEFAULT = SCRIPT_DIR.parent.parent
TOOL_VERSION = "0.1.48"
REPORT_DIR = "non_character_namespace_saturation_audit"
REPORT_NAME = "BR_quartet_restoration_non_character_namespace_saturation_audit_evidence.tar.zst"

ASSET_DIFF_REL = "differences/br1_assets.json"
ASSET_DIFF_SHA256 = "a948bf404dc439234519611b98a96b781a5e4f6ed24cf00104fd41ee7dc07456"

STAGE121_NAME = "BR_quartet_restoration_master_discovery_inventory_gap_audit_evidence.tar.zst"
STAGE121_SHA256 = "a1f9e87ee273af0fece9b6722bc0e9b58fd6d818cefbdbf9113d75fef4216219"
STAGE121_DIR = "master_restoration_discovery_inventory_gap_audit"
STAGE121_SUMMARY_SHA256 = "b074a9334a5f76e364e2df0a5e467c294bdd4ac636e7e5765eb4be03079e0654"

STAGE122_NAME = "BR_quartet_restoration_scene_effect_member_family_binding_audit_evidence.tar.zst"
STAGE122_SHA256 = "5fba802fdc5407e5c12a708d612f91da087038bef1d48083cb30ae82da62bc92"
STAGE122_DIR = "scene_effect_member_family_binding_audit"
STAGE122_SUMMARY_SHA256 = "f892f3cd4afcb6daa21a3f3befc062b46b45c5e6adb3bcfe4cbae3b015004982"

STAGE129_NAME = "BR_quartet_restoration_structured_selector_water_dependency_evidence.tar.zst"
STAGE129_SHA256 = "d695940c5e326cb1f351dd87102a57002c48d604c212f96a3a708af053e6ff34"
STAGE129_DIR = "structured_selector_water_dependency_evidence"
STAGE129_SUMMARY_SHA256 = "286ba6607b1d87ea4807174a968b8267c2d49d1c3b80f6f91c5c65efa60731be"

TECHNICAL_NAMESPACES = {
    "field", "shader", "effect", "posteffect", "obj", "ui", "camera",
    "shaderoriginal", "sky", "font",
}
ACTIVE_RESTORATION_NAMESPACES = {"field", "shader", "effect", "posteffect"}
LOCALIZATION_NAMESPACES = {"res_en", "res_jp", "res_sc", "res_ch", "res_tc"}
GENERATED_SHADER_PREFIXES = ("pbb-", "pbs-", "sm-", "smc-", "rsm-", "std-", "ds-")
FIELD_LEXICAL_TOKENS = (
    "bath", "shower", "pool", "river", "lake", "pier", "marsh", "sea", "water", "beach", "spring",
)
FORBIDDEN_EXTENSIONS = (".pak", ".g1m", ".g1e", ".g1em", ".elixir", ".ebm", ".ebd")

EXPECTED = {
    "asset_difference_rows": 7566,
    "character_rows": 3525,
    "localization_rows": 3121,
    "non_character_technical_rows": 920,
    "technical_identical_rows": 381,
    "technical_changed_rows": 512,
    "technical_new_in_target_rows": 24,
    "technical_removed_in_target_rows": 3,
    "technical_nonidentical_rows": 539,
    "technical_namespace_rows": 10,
    "active_restoration_namespace_rows": 4,
    "field_nonidentical_path_rows": 318,
    "field_scene_root_rows": 105,
    "field_lexical_signal_root_rows": 23,
    "field_lexical_signal_path_rows": 69,
    "shader_nonidentical_path_rows": 214,
    "shader_generated_variant_rows": 150,
    "shader_named_or_texture_rows": 64,
    "effect_nonidentical_path_rows": 6,
    "posteffect_nonidentical_path_rows": 1,
    "known_focused_non_character_path_rows": 19,
    "unfocused_non_character_candidate_rows": 520,
}


class AuditError(RuntimeError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AuditError(message)


def progress(message: str) -> None:
    print(f"[non-character-namespace] {message}", file=sys.stderr, flush=True)


def version_tuple(value: str) -> tuple[int, ...]:
    try:
        return tuple(int(part) for part in value.strip().split("."))
    except ValueError as exc:
        raise AuditError(f"invalid workstream version: {value}") from exc


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def safe_relative(raw: str, label: str) -> str:
    path = PurePosixPath(str(raw).replace("\\", "/"))
    require(bool(path.parts), f"empty {label}")
    require(not path.is_absolute() and ".." not in path.parts, f"unsafe {label}: {raw}")
    return path.as_posix()


def load_json(path: Path) -> dict[str, Any]:
    require(path.is_file(), f"missing required JSON: {path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise AuditError(f"invalid JSON {path}: {exc}") from exc
    require(isinstance(value, dict), f"JSON root must be object: {path}")
    return value


def read_tsv(path: Path) -> list[dict[str, str]]:
    require(path.is_file(), f"missing required TSV: {path}")
    with path.open(encoding="utf-8", newline="") as handle:
        rows = [dict(row) for row in csv.DictReader(handle, delimiter="\t")]
    require(rows, f"empty required TSV: {path}")
    return rows


def write_tsv(path: Path, fields: Sequence[str], rows: Iterable[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(fields), delimiter="\t", lineterminator="\n", extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fields})


def make_archive(source: Path, output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(output.name + ".tmp")
    temporary.unlink(missing_ok=True)
    completed = subprocess.run(
        ["tar", "--zstd", "-cf", str(temporary), "-C", str(source.parent), source.name],
        text=True, capture_output=True,
    )
    require(completed.returncode == 0, completed.stderr.strip() or "report archive creation failed")
    os.replace(temporary, output)


def extract_archive(archive: Path, destination: Path, expected_root: str) -> Path:
    require(archive.is_file(), f"missing prerequisite report archive: {archive}")
    listed = subprocess.run(["tar", "--zstd", "-tf", str(archive)], text=True, capture_output=True)
    require(listed.returncode == 0, listed.stderr.strip() or f"cannot list {archive}")
    names = [line.strip() for line in listed.stdout.splitlines() if line.strip()]
    require(names, f"empty prerequisite report: {archive}")
    for name in names:
        safe_relative(name, "archive member")
    roots = {PurePosixPath(name).parts[0] for name in names}
    require(roots == {expected_root}, f"unexpected report root in {archive}: {sorted(roots)}")
    destination.mkdir(parents=True, exist_ok=True)
    completed = subprocess.run(["tar", "--zstd", "-xf", str(archive), "-C", str(destination)], text=True, capture_output=True)
    require(completed.returncode == 0, completed.stderr.strip() or f"cannot extract {archive}")
    root = destination / expected_root
    require(root.is_dir(), f"missing extracted report root: {root}")
    return root


def locate_report(report_root: Path, temporary: Path, archive_name: str, archive_sha: str, root_name: str, summary_sha: str) -> tuple[Path, str]:
    archive = report_root / archive_name
    actual_archive_sha = sha256_file(archive)
    require(actual_archive_sha == archive_sha, f"unexpected {archive_name} SHA-256: {actual_archive_sha}")
    direct = report_root / root_name
    root = direct if direct.is_dir() else extract_archive(archive, temporary / root_name, root_name)
    actual_summary_sha = sha256_file(root / "SUMMARY.json")
    require(actual_summary_sha == summary_sha, f"unexpected {root_name} SUMMARY SHA-256: {actual_summary_sha}")
    return root, actual_archive_sha


def namespace(path: str) -> str:
    parts = PurePosixPath(safe_relative(path, "asset path")).parts
    if len(parts) >= 3 and parts[:2] == ("data", "x64"):
        return parts[2].casefold()
    return parts[0].casefold()


def extension(path: str) -> str:
    if path.casefold().endswith(".elixir.gz"):
        return ".elixir.gz"
    return PurePosixPath(path).suffix.casefold() or "(none)"


def field_root(path: str) -> str:
    parts = PurePosixPath(path).parts
    return parts[3].casefold() if len(parts) >= 4 and parts[:3] == ("data", "x64", "field") else ""


def shader_family(path: str) -> str:
    if not path.startswith("data/x64/shader/"):
        return ""
    base = PurePosixPath(path).name.casefold()
    return "generated_variant" if base.startswith(GENERATED_SHADER_PREFIXES) else "named_shader_or_texture"


def lexical_tokens(value: str) -> list[str]:
    lower = value.casefold()
    return [token for token in FIELD_LEXICAL_TOKENS if token in lower]


def scope_for_namespace(ns: str) -> str:
    if ns == "character":
        return "character_namespace_already_audited"
    if ns in LOCALIZATION_NAMESPACES:
        return "translation_or_localization_boundary"
    if ns in ACTIVE_RESTORATION_NAMESPACES:
        return "restoration_static_discovery"
    if ns in TECHNICAL_NAMESPACES:
        return "technical_namespace_identical_support"
    return "outside_bounded_br1_asset_comparison"


def normalize_classification(value: str) -> str:
    require(value in {"identical", "changed", "new_in_target", "removed_in_target", "probably_moved"}, f"unexpected classification: {value}")
    return value


def build_report(project_root: Path, report_root: Path | None = None, output_report_root: Path | None = None, create_archive: bool = True) -> tuple[Path | None, dict[str, Any]]:
    project_root = project_root.resolve()
    version = (project_root / "workstreams/quartet_restoration/VERSION").read_text(encoding="utf-8").strip()
    require(version_tuple(version) >= version_tuple(TOOL_VERSION), f"expected quartet_restoration {TOOL_VERSION} or newer, found {version}")
    report_root = (report_root or project_root / ".local/reports/quartet_restoration").resolve()
    output_report_root = (output_report_root or report_root).resolve()

    asset_diff = report_root / ASSET_DIFF_REL
    require(sha256_file(asset_diff) == ASSET_DIFF_SHA256, f"unexpected asset-difference SHA-256: {sha256_file(asset_diff)}")
    data = load_json(asset_diff)
    entries = data.get("entries")
    require(isinstance(entries, list), "asset-difference entries must be a list")

    with tempfile.TemporaryDirectory(prefix="stage130-prereq-") as tmp_text:
        temporary = Path(tmp_text)
        stage121, stage121_sha = locate_report(report_root, temporary, STAGE121_NAME, STAGE121_SHA256, STAGE121_DIR, STAGE121_SUMMARY_SHA256)
        stage122, stage122_sha = locate_report(report_root, temporary, STAGE122_NAME, STAGE122_SHA256, STAGE122_DIR, STAGE122_SUMMARY_SHA256)
        stage129, stage129_sha = locate_report(report_root, temporary, STAGE129_NAME, STAGE129_SHA256, STAGE129_DIR, STAGE129_SUMMARY_SHA256)

        stage121_summary = load_json(stage121 / "SUMMARY.json")
        require(stage121_summary.get("discovery_exhaustive") is False, "stage121 must remain non-exhaustive")
        focused_rows = read_tsv(stage122 / "SCENE_EFFECT_PATH_BINDING_SUMMARY.tsv")
        stage129_summary = load_json(stage129 / "SUMMARY.json")
        require(stage129_summary.get("independent_selector_binding_confirmed_rows") == 0, "stage129 selector result changed")
        require(stage129_summary.get("water_shader_executable_code_delta_rows") == 0, "stage129 water shader result changed")

    normalized_entries: list[dict[str, Any]] = []
    namespace_counts: dict[str, Counter[str]] = defaultdict(Counter)
    character_rows = localization_rows = 0
    for raw in entries:
        require(isinstance(raw, dict), "asset-difference row must be object")
        path = safe_relative(str(raw.get("normalized_path", "")), "asset path")
        ns = namespace(path)
        classification = normalize_classification(str(raw.get("classification", "")))
        namespace_counts[ns][classification] += 1
        if ns == "character":
            character_rows += 1
        if ns in LOCALIZATION_NAMESPACES:
            localization_rows += 1
        normalized_entries.append({**raw, "normalized_path": path, "namespace": ns, "classification": classification})

    technical_rows = [row for row in normalized_entries if row["namespace"] in TECHNICAL_NAMESPACES]
    candidate_rows = [row for row in technical_rows if row["namespace"] in ACTIVE_RESTORATION_NAMESPACES and row["classification"] != "identical"]
    focused_paths = {safe_relative(row["focused_path"], "focused path") for row in focused_rows if not row["focused_path"].startswith("data/x64/character/")}
    require(len(focused_paths) == EXPECTED["known_focused_non_character_path_rows"], f"unexpected focused non-character path count: {len(focused_paths)}")

    candidate_output: list[dict[str, Any]] = []
    field_roots: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in sorted(candidate_rows, key=lambda item: item["normalized_path"]):
        path = row["normalized_path"]
        ns = row["namespace"]
        source = row.get("source") if isinstance(row.get("source"), dict) else {}
        target = row.get("target") if isinstance(row.get("target"), dict) else {}
        root = field_root(path)
        tokens = lexical_tokens(root)
        if root:
            field_roots[root].append(row)
        candidate_output.append({
            "difference_id": row.get("difference_id", ""),
            "namespace": ns,
            "classification": row["classification"],
            "normalized_path": path,
            "extension": extension(path),
            "field_scene_root": root,
            "field_lexical_signal_tokens": ";".join(tokens),
            "shader_family": shader_family(path),
            "source_size": source.get("size", ""),
            "source_sha256": source.get("sha256", ""),
            "target_size": target.get("size", ""),
            "target_sha256": target.get("sha256", ""),
            "known_focused_discovery_path": path in focused_paths,
            "runtime_confirmed": False,
            "visual_or_censorship_semantics_confirmed": False,
            "write_authorized": False,
        })

    field_summary: list[dict[str, Any]] = []
    for root, rows in sorted(field_roots.items()):
        tokens = lexical_tokens(root)
        paths = sorted(row["normalized_path"] for row in rows)
        field_summary.append({
            "field_scene_root": root,
            "path_rows": len(rows),
            "changed_rows": sum(row["classification"] == "changed" for row in rows),
            "removed_in_target_rows": sum(row["classification"] == "removed_in_target" for row in rows),
            "extensions": ";".join(sorted({extension(path) for path in paths})),
            "lexical_signal_tokens": ";".join(tokens),
            "lexical_signal_only_not_semantics": bool(tokens),
            "known_focused_path_rows": sum(path in focused_paths for path in paths),
            "remaining_unfocused_path_rows": sum(path not in focused_paths for path in paths),
        })

    namespace_summary: list[dict[str, Any]] = []
    for ns in sorted(namespace_counts):
        counts = namespace_counts[ns]
        total = sum(counts.values())
        namespace_summary.append({
            "namespace": ns,
            "total_rows": total,
            "identical_rows": counts["identical"],
            "changed_rows": counts["changed"],
            "new_in_target_rows": counts["new_in_target"],
            "removed_in_target_rows": counts["removed_in_target"],
            "probably_moved_rows": counts["probably_moved"],
            "nonidentical_rows": total - counts["identical"],
            "workstream_scope": scope_for_namespace(ns),
            "visual_or_censorship_semantics_confirmed": False,
        })

    focused_output: list[dict[str, Any]] = []
    for row in sorted((r for r in focused_rows if r["focused_path"] in focused_paths), key=lambda r: r["focused_path"]):
        path = row["focused_path"]
        disposition = "stage122_focused_semantics_unresolved"
        if path in {"data/x64/shader/cwater.g1s", "data/x64/shader/cwater2.g1s"}:
            disposition = "stage129_no_executable_shader_delta"
        elif path == "data/x64/shader/texture/caustics.g1t":
            disposition = "stage129_target_only_subsystem_pair_no_selector_or_semantics"
        focused_output.append({
            "normalized_path": path,
            "namespace": namespace(path),
            "stage122_domain": row.get("domain", ""),
            "stage122_member_difference_rows": row.get("member_difference_rows", ""),
            "current_static_disposition": disposition,
            "runtime_confirmed": False,
            "visual_or_censorship_semantics_confirmed": False,
            "write_authorized": False,
        })

    ns_candidate_counts = Counter(row["namespace"] for row in candidate_rows)
    ns_focused_counts = Counter(namespace(path) for path in focused_paths)
    queue_rows = []
    for priority, ns, unit, next_step in [
        (1, "field", "field_archive_path", "rehydrate all 105 field scene roots and classify exact member-level delta families"),
        (2, "shader", "shader_or_texture_path", "classify 214 shader paths into executable-code, signature, reflection and target-only dependency families"),
        (3, "effect", "effect_archive_path", "extend member-level sweep from four focused player/common archives to the two remaining mob archives"),
        (4, "posteffect", "posteffect_archive_path", "preserve the existing focused pe_pack result and bind its member deltas to exact callsites"),
    ]:
        queue_rows.append({
            "priority": priority,
            "namespace": ns,
            "candidate_path_rows": ns_candidate_counts[ns],
            "known_focused_path_rows": ns_focused_counts[ns],
            "remaining_unfocused_path_rows": ns_candidate_counts[ns] - ns_focused_counts[ns],
            "primary_unit": unit,
            "safe_next_discovery": next_step,
            "runtime_or_save_required": False,
            "write_authorized": False,
        })

    technical_counts = Counter(row["classification"] for row in technical_rows)
    shader_candidates = [row for row in candidate_output if row["namespace"] == "shader"]
    lexical_field_roots = [row for row in field_summary if row["lexical_signal_tokens"]]
    summary = {
        "type": "br_quartet_restoration_non_character_namespace_saturation_audit_evidence_summary",
        "format_version": 1,
        "tool_version": TOOL_VERSION,
        "status": "non_character_technical_namespace_saturation_complete_candidate_space_bounded_semantics_unresolved_no_write",
        "asset_difference_rows": len(normalized_entries),
        "character_namespace_rows": character_rows,
        "localization_boundary_rows": localization_rows,
        "non_character_technical_rows": len(technical_rows),
        "technical_namespace_rows": len({row["namespace"] for row in technical_rows}),
        "active_restoration_namespace_rows": len(ACTIVE_RESTORATION_NAMESPACES),
        "technical_identical_rows": technical_counts["identical"],
        "technical_changed_rows": technical_counts["changed"],
        "technical_new_in_target_rows": technical_counts["new_in_target"],
        "technical_removed_in_target_rows": technical_counts["removed_in_target"],
        "technical_nonidentical_candidate_rows": len(candidate_rows),
        "field_nonidentical_path_rows": ns_candidate_counts["field"],
        "field_scene_root_rows": len(field_summary),
        "field_lexical_signal_root_rows": len(lexical_field_roots),
        "field_lexical_signal_path_rows": sum(int(row["path_rows"]) for row in lexical_field_roots),
        "shader_nonidentical_path_rows": ns_candidate_counts["shader"],
        "shader_generated_variant_rows": sum(row["shader_family"] == "generated_variant" for row in shader_candidates),
        "shader_named_or_texture_rows": sum(row["shader_family"] == "named_shader_or_texture" for row in shader_candidates),
        "effect_nonidentical_path_rows": ns_candidate_counts["effect"],
        "posteffect_nonidentical_path_rows": ns_candidate_counts["posteffect"],
        "known_focused_non_character_path_rows": len(focused_paths),
        "unfocused_non_character_candidate_rows": len(candidate_rows) - len(focused_paths),
        "water_shader_executable_code_delta_rows": stage129_summary["water_shader_executable_code_delta_rows"],
        "caustics_target_only_subsystem_pair_rows": stage129_summary["caustics_target_only_subsystem_pair_rows"],
        "runtime_confirmed_rows": 0,
        "visual_or_censorship_semantics_confirmed_rows": 0,
        "write_authorized_rows": 0,
        "global_discovery_saturation_achieved": False,
        "input_archive_sha256": {
            "stage121": stage121_sha,
            "stage122": stage122_sha,
            "stage129": stage129_sha,
        },
        "policy": {
            "existing_metadata_only": True,
            "local_proprietary_payloads_read": False,
            "proprietary_payloads_in_report": False,
            "translation_or_localization_rows_reclassified_as_restoration": False,
            "lexical_tokens_treated_as_visual_semantics": False,
            "runtime_validation_inferred": False,
            "pak_built_or_repacked": False,
            "profile_or_registry_modified": False,
            "installed_game_modified": False,
            "translation_modified": False,
            "legacy_dlc_modified": False,
            "core_modified": False,
            "git_modified": False,
        },
        "next_action": "Run one read-only field namespace member saturation collector across all 105 field scene roots, then classify the 214 shader paths by executable-code versus metadata/signature differences. Do not require saves or build a Canary-all package.",
    }

    checks = {
        "asset_difference_rows": len(normalized_entries),
        "character_rows": character_rows,
        "localization_rows": localization_rows,
        "non_character_technical_rows": len(technical_rows),
        "technical_identical_rows": technical_counts["identical"],
        "technical_changed_rows": technical_counts["changed"],
        "technical_new_in_target_rows": technical_counts["new_in_target"],
        "technical_removed_in_target_rows": technical_counts["removed_in_target"],
        "technical_nonidentical_rows": len(candidate_rows),
        "technical_namespace_rows": len({row["namespace"] for row in technical_rows}),
        "active_restoration_namespace_rows": len(ACTIVE_RESTORATION_NAMESPACES),
        "field_nonidentical_path_rows": ns_candidate_counts["field"],
        "field_scene_root_rows": len(field_summary),
        "field_lexical_signal_root_rows": len(lexical_field_roots),
        "field_lexical_signal_path_rows": sum(int(row["path_rows"]) for row in lexical_field_roots),
        "shader_nonidentical_path_rows": ns_candidate_counts["shader"],
        "shader_generated_variant_rows": summary["shader_generated_variant_rows"],
        "shader_named_or_texture_rows": summary["shader_named_or_texture_rows"],
        "effect_nonidentical_path_rows": ns_candidate_counts["effect"],
        "posteffect_nonidentical_path_rows": ns_candidate_counts["posteffect"],
        "known_focused_non_character_path_rows": len(focused_paths),
        "unfocused_non_character_candidate_rows": len(candidate_rows) - len(focused_paths),
    }
    for key, expected in EXPECTED.items():
        require(checks[key] == expected, f"unexpected {key}: {checks[key]} != {expected}")

    report_dir = output_report_root / REPORT_DIR
    if report_dir.exists():
        import shutil
        shutil.rmtree(report_dir)
    report_dir.mkdir(parents=True)
    write_tsv(report_dir / "NON_CHARACTER_NAMESPACE_SUMMARY.tsv", [
        "namespace", "total_rows", "identical_rows", "changed_rows", "new_in_target_rows", "removed_in_target_rows", "probably_moved_rows", "nonidentical_rows", "workstream_scope", "visual_or_censorship_semantics_confirmed",
    ], namespace_summary)
    write_tsv(report_dir / "NON_CHARACTER_TECHNICAL_CANDIDATES.tsv", [
        "difference_id", "namespace", "classification", "normalized_path", "extension", "field_scene_root", "field_lexical_signal_tokens", "shader_family", "source_size", "source_sha256", "target_size", "target_sha256", "known_focused_discovery_path", "runtime_confirmed", "visual_or_censorship_semantics_confirmed", "write_authorized",
    ], candidate_output)
    write_tsv(report_dir / "FIELD_SCENE_ROOT_SUMMARY.tsv", [
        "field_scene_root", "path_rows", "changed_rows", "removed_in_target_rows", "extensions", "lexical_signal_tokens", "lexical_signal_only_not_semantics", "known_focused_path_rows", "remaining_unfocused_path_rows",
    ], field_summary)
    write_tsv(report_dir / "KNOWN_FOCUSED_PATH_COVERAGE.tsv", [
        "normalized_path", "namespace", "stage122_domain", "stage122_member_difference_rows", "current_static_disposition", "runtime_confirmed", "visual_or_censorship_semantics_confirmed", "write_authorized",
    ], focused_output)
    write_tsv(report_dir / "NON_CHARACTER_DISCOVERY_QUEUE.tsv", [
        "priority", "namespace", "candidate_path_rows", "known_focused_path_rows", "remaining_unfocused_path_rows", "primary_unit", "safe_next_discovery", "runtime_or_save_required", "write_authorized",
    ], queue_rows)
    write_tsv(report_dir / "INPUT_HASHES.tsv", ["input_id", "relative_path", "sha256", "verified"], [
        {"input_id": "br1_assets", "relative_path": ASSET_DIFF_REL, "sha256": ASSET_DIFF_SHA256, "verified": True},
        {"input_id": "stage121", "relative_path": STAGE121_NAME, "sha256": stage121_sha, "verified": True},
        {"input_id": "stage122", "relative_path": STAGE122_NAME, "sha256": stage122_sha, "verified": True},
        {"input_id": "stage129", "relative_path": STAGE129_NAME, "sha256": stage129_sha, "verified": True},
    ])
    (report_dir / "SUMMARY.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    archive: Path | None = None
    if create_archive:
        archive = output_report_root / REPORT_NAME
        make_archive(report_dir, archive)
        names = subprocess.run(["tar", "--zstd", "-tf", str(archive)], text=True, capture_output=True, check=True).stdout.splitlines()
        require(not any(name.casefold().endswith(FORBIDDEN_EXTENSIONS) for name in names), "proprietary payload extension in report")
    return archive, summary


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path, default=PROJECT_ROOT_DEFAULT)
    parser.add_argument("--report-root", type=Path)
    parser.add_argument("--output-report-root", type=Path)
    parser.add_argument("--no-archive", action="store_true")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    archive, summary = build_report(args.project_root, args.report_root, args.output_report_root, not args.no_archive)
    print(json.dumps(summary, indent=2, sort_keys=True))
    if archive:
        progress(f"report archive: {archive}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except AuditError as exc:
        print(f"[non-character-namespace] ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
