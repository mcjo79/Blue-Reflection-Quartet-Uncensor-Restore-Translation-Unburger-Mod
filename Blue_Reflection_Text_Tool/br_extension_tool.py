#!/usr/bin/env python3
"""Blue Reflection optional-module, inventory and project validation tool.

The tool uses only Python's standard library.  Optional restoration and DLC
research remain disabled by policy until the text import/repack workflow is
stable, but their data formats and reusable inventory/diff machinery are
defined now.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import re
import sys
import tempfile
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable

TOOL_VERSION = "0.0.8"
FORMAT_VERSION = 1
SAMPLE_BLOCK_SIZE = 65536
SAMPLE_BLOCKS = 32
BANNED_REPOSITORY_EXTENSIONS = {
    ".pak", ".ebm", ".ebd", ".g1m", ".g1t", ".ktid", ".kts", ".ogg",
    ".wav", ".awb", ".acb", ".hca", ".mp4", ".wmv", ".dds", ".png",
    ".jpg", ".jpeg", ".bin", ".dat",
}


class ToolError(RuntimeError):
    pass


def atomic_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(data, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
        os.replace(tmp_name, path)
    except Exception:
        try:
            os.unlink(tmp_name)
        except FileNotFoundError:
            pass
        raise


def load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ToolError(f"Missing JSON file: {path}") from exc
    except json.JSONDecodeError as exc:
        raise ToolError(f"Invalid JSON in {path}: {exc}") from exc


def read_tsv(path: Path) -> list[dict[str, str]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as handle:
            return list(csv.DictReader(handle, delimiter="\t"))
    except FileNotFoundError as exc:
        raise ToolError(f"Missing TSV file: {path}") from exc


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def normalized_relative(path: Path, root: Path) -> str:
    return path.relative_to(root).as_posix()


def sample_hashes(path: Path) -> list[str]:
    size = path.stat().st_size
    if size == 0:
        return []
    total_blocks = (size + SAMPLE_BLOCK_SIZE - 1) // SAMPLE_BLOCK_SIZE
    if total_blocks <= SAMPLE_BLOCKS:
        indices = list(range(total_blocks))
    else:
        indices = sorted({
            round(i * (total_blocks - 1) / (SAMPLE_BLOCKS - 1))
            for i in range(SAMPLE_BLOCKS)
        })
    hashes: list[str] = []
    with path.open("rb") as handle:
        for index in indices:
            handle.seek(index * SAMPLE_BLOCK_SIZE)
            block = handle.read(SAMPLE_BLOCK_SIZE)
            hashes.append(hashlib.sha256(block).hexdigest())
    return hashes


def sample_similarity(a: Iterable[str], b: Iterable[str]) -> float:
    left = set(a)
    right = set(b)
    if not left and not right:
        return 1.0
    union = left | right
    return round(len(left & right) / len(union), 6) if union else 0.0


def target_ids(project_root: Path) -> set[str]:
    rows = read_tsv(project_root / "config/series_targets.tsv")
    ids = {row.get("target_id", "") for row in rows}
    ids.discard("")
    if not ids:
        raise ToolError("No target IDs found in config/series_targets.tsv")
    return ids


def validate_module_manifest(
    manifest: dict[str, Any],
    row: dict[str, str],
    known_targets: set[str],
    known_modules: set[str],
) -> list[str]:
    errors: list[str] = []
    required = {
        "type", "format_version", "module_id", "project", "module_type",
        "status", "default_enabled", "targets", "dependencies",
        "distribution_policy", "build_namespace",
    }
    missing = sorted(required - set(manifest))
    if missing:
        errors.append(f"missing fields: {', '.join(missing)}")
        return errors
    if manifest["type"] != "br_module_manifest" or manifest["format_version"] != 1:
        errors.append("unsupported manifest type or version")
    if manifest["module_id"] != row["module_id"]:
        errors.append("module_id does not match config/modules.tsv")
    if manifest["project"] != row["project"]:
        errors.append("project does not match config/modules.tsv")
    if manifest["module_type"] != row["module_type"]:
        errors.append("module_type does not match config/modules.tsv")
    if bool(manifest["default_enabled"]) != (row["default_enabled"].lower() == "true"):
        errors.append("default_enabled does not match config/modules.tsv")
    unknown_targets = sorted(set(manifest["targets"]) - known_targets)
    if unknown_targets:
        errors.append(f"unknown targets: {', '.join(unknown_targets)}")
    unknown_dependencies = sorted(set(manifest["dependencies"]) - known_modules)
    if unknown_dependencies:
        errors.append(f"unknown dependencies: {', '.join(unknown_dependencies)}")
    if manifest["module_type"] in {"restoration", "dlc_adapter"}:
        if manifest["default_enabled"]:
            errors.append("optional module must not be enabled by default")
        policy = manifest.get("distribution_policy", {})
        if manifest["module_type"] == "restoration":
            if policy.get("contains_proprietary_assets") is not False:
                errors.append("restoration policy must forbid bundled proprietary assets")
        if manifest["module_type"] == "dlc_adapter":
            if policy.get("contains_paid_dlc_assets") is not False:
                errors.append("DLC policy must forbid bundled paid DLC assets")
    return errors


def validate_restoration_registry(data: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if data.get("type") != "br_restoration_registry" or data.get("format_version") != 1:
        return ["unsupported restoration registry type or version"]
    items = data.get("items")
    if not isinstance(items, list):
        return ["items must be an array"]
    seen: set[str] = set()
    allowed_statuses = {
        "not_mapped", "files_identified", "dependencies_mapped",
        "conversion_required", "integrated", "in_game_tested",
        "blocked", "unsupported",
    }
    for index, item in enumerate(items):
        if not isinstance(item, dict):
            errors.append(f"item {index} is not an object")
            continue
        item_id = item.get("restoration_id")
        if not item_id:
            errors.append(f"item {index} has no restoration_id")
        elif item_id in seen:
            errors.append(f"duplicate restoration_id: {item_id}")
        else:
            seen.add(item_id)
        if item.get("status") not in allowed_statuses:
            errors.append(f"{item_id or index}: unsupported status")
        if item.get("enabled_by_default") is not False:
            errors.append(f"{item_id or index}: restoration must default to disabled")
        for field in ("source_files", "target_files", "dependencies"):
            if not isinstance(item.get(field), list):
                errors.append(f"{item_id or index}: {field} must be an array")
    return errors


DLC_OPERATIONAL_STATUSES = {
    "not_mapped",
    "assets_identified",
    "conversion_required",
    "integrated",
    "in_game_tested",
    "blocked",
    "unsupported",
}

DLC_METADATA_STATUS_CONTENT_TYPES = {
    "metadata_inventory_only": {"generated_metadata_catalog"},
    "not_synthesized": {"generated_dependency_catalog"},
    "nested_inventory_metadata_only": {"generated_metadata_catalog"},
}

DLC_TECHNICAL_CATALOG_TYPES = {
    "costume_or_outfit",
    "accessory",
    "item_or_reward",
    "recipe_or_system_bonus",
    "theme_or_ui_content",
    "unlock_or_entitlement",
    "shared_asset_dependency",
    "unknown_legacy_dlc_candidate",
}


def validate_dlc_registry(data: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if data.get("type") != "br_dlc_content_registry" or data.get("format_version") != 1:
        return ["unsupported DLC registry type or version"]
    items = data.get("items")
    if not isinstance(items, list):
        return ["items must be an array"]

    generated_registry = data.get("generated_registry")
    declared_technical_types: set[str] = set()
    if generated_registry is not None:
        if not isinstance(generated_registry, dict):
            errors.append("generated_registry must be an object")
        else:
            raw_types = generated_registry.get("technical_types")
            if not isinstance(raw_types, list) or not raw_types:
                errors.append("generated_registry.technical_types must be a non-empty array")
            elif not all(isinstance(value, str) and value for value in raw_types):
                errors.append("generated_registry.technical_types must contain non-empty strings")
            else:
                declared_technical_types = set(raw_types)
                if len(declared_technical_types) != len(raw_types):
                    errors.append("generated_registry.technical_types contains duplicates")
                unsupported_types = declared_technical_types - DLC_TECHNICAL_CATALOG_TYPES
                if unsupported_types:
                    errors.append(
                        "generated_registry.technical_types contains unsupported values: "
                        + ", ".join(sorted(unsupported_types))
                    )
            if generated_registry.get("status") != "metadata_only_not_buildable":
                errors.append("generated_registry.status must be metadata_only_not_buildable")
            if generated_registry.get("default_enabled") is not False:
                errors.append("generated_registry.default_enabled must be false")
            if generated_registry.get("raw_assets_embedded") is not False:
                errors.append("generated_registry.raw_assets_embedded must be false")

    seen: set[str] = set()
    for index, item in enumerate(items):
        if not isinstance(item, dict):
            errors.append(f"item {index} is not an object")
            continue
        item_id = item.get("content_id")
        label = item_id or index
        if not item_id:
            errors.append(f"item {index} has no content_id")
        elif item_id in seen:
            errors.append(f"duplicate content_id: {item_id}")
        else:
            seen.add(item_id)

        content_type = item.get("content_type")
        status = item.get("quartet_status")
        ownership = item.get("source_ownership")

        if status in DLC_OPERATIONAL_STATUSES:
            if ownership != "requires_original_dlc":
                errors.append(f"{label}: operational content must require original DLC")
        elif status in DLC_METADATA_STATUS_CONTENT_TYPES:
            allowed_types = DLC_METADATA_STATUS_CONTENT_TYPES[status]
            if content_type not in allowed_types:
                errors.append(
                    f"{label}: quartet_status {status} is not allowed for content_type {content_type}"
                )
            if ownership != "requires_original_dlc":
                errors.append(f"{label}: metadata inventory must require original DLC")
        elif status == "generated_metadata_registry_only":
            if content_type not in DLC_TECHNICAL_CATALOG_TYPES:
                errors.append(
                    f"{label}: generated metadata registry has unsupported content_type {content_type}"
                )
            if declared_technical_types and content_type not in declared_technical_types:
                errors.append(
                    f"{label}: content_type is missing from generated_registry.technical_types"
                )
            if ownership != "requires_original_dlc_when_applicable":
                errors.append(
                    f"{label}: generated technical metadata must use "
                    "requires_original_dlc_when_applicable"
                )
        else:
            errors.append(f"{label}: unsupported quartet_status")

        if not isinstance(item.get("dependencies"), list):
            errors.append(f"{label}: dependencies must be an array")

    if declared_technical_types:
        represented_types = {
            item.get("content_type")
            for item in items
            if isinstance(item, dict)
            and item.get("quartet_status") == "generated_metadata_registry_only"
        }
        missing_items = declared_technical_types - represented_types
        if missing_items:
            errors.append(
                "generated_registry.technical_types has no registry item for: "
                + ", ".join(sorted(missing_items))
            )

    return errors


def validate_translation_project(
    project_root: Path,
    project: str,
    require_translation: bool,
) -> tuple[dict[str, Any], list[str]]:
    translation_root = project_root / "titles" / project / "translation"
    manifest_path = translation_root / "translation_manifest.json"
    if not manifest_path.is_file():
        if require_translation:
            return {}, [f"missing translation manifest: {manifest_path}"]
        return {"present": False}, []

    manifest = load_json(manifest_path)
    errors: list[str] = []
    if manifest.get("type") != "br_translation_project":
        errors.append(f"{project}: unsupported translation manifest type")
    units = manifest.get("units")
    if not isinstance(units, list):
        return {}, [f"{project}: manifest units must be an array"]

    logical_ids: set[str] = set()
    total_records = 0
    categories: Counter[str] = Counter()
    statuses: Counter[str] = Counter()
    for unit_summary in units:
        rel = unit_summary.get("path")
        if not isinstance(rel, str):
            errors.append(f"{project}: unit manifest entry has no path")
            continue
        unit_path = translation_root / rel
        if not unit_path.is_file():
            errors.append(f"{project}: missing unit file {rel}")
            continue
        unit = load_json(unit_path)
        records = unit.get("records")
        if not isinstance(records, list):
            errors.append(f"{project}: {rel} records must be an array")
            continue
        if unit_summary.get("records") != len(records):
            errors.append(f"{project}: {rel} record count differs from manifest")
        category = unit.get("category")
        categories[str(category)] += 1
        total_records += len(records)
        for index, record in enumerate(records):
            if not isinstance(record, dict):
                errors.append(f"{project}: {rel} record {index} is not an object")
                continue
            missing = [
                field for field in ("logical_id", "jp", "en_original", "en", "alignment")
                if field not in record
            ]
            if missing:
                errors.append(
                    f"{project}: {rel} record {index} missing {', '.join(missing)}"
                )
                continue
            logical_id = record["logical_id"]
            if logical_id in logical_ids:
                errors.append(f"{project}: duplicate logical_id {logical_id}")
            else:
                logical_ids.add(logical_id)
            if not isinstance(record["jp"], str) or not isinstance(record["en"], str):
                errors.append(f"{project}: {logical_id} jp/en must be strings")
            if record["en_original"] is not None and not isinstance(record["en_original"], str):
                errors.append(f"{project}: {logical_id} en_original has invalid type")
            alignment = record["alignment"]
            if isinstance(alignment, dict):
                statuses[str(alignment.get("status", "missing"))] += 1
            else:
                errors.append(f"{project}: {logical_id} alignment must be an object")

    summary = manifest.get("summary", {})
    if summary.get("units") != len(units):
        errors.append(f"{project}: manifest summary unit count mismatch")
    if summary.get("records") != total_records:
        errors.append(f"{project}: manifest summary record count mismatch")

    return {
        "present": True,
        "units": len(units),
        "records": total_records,
        "logical_ids": len(logical_ids),
        "categories": dict(sorted(categories.items())),
        "alignment_statuses": dict(sorted(statuses.items())),
    }, errors


def cmd_validate_project(args: argparse.Namespace) -> int:
    project_root = Path(args.project_root).expanduser().resolve()
    known_targets = target_ids(project_root)
    module_rows = read_tsv(project_root / "config/modules.tsv")
    known_modules = {row["module_id"] for row in module_rows}
    errors: list[str] = []
    warnings: list[str] = []
    modules_report: list[dict[str, Any]] = []

    if len(known_modules) != len(module_rows):
        errors.append("duplicate module_id in config/modules.tsv")

    for row in module_rows:
        manifest_path = project_root / row["manifest_path"]
        manifest = load_json(manifest_path)
        module_errors = validate_module_manifest(
            manifest, row, known_targets, known_modules
        )
        modules_report.append({
            "module_id": row["module_id"],
            "type": row["module_type"],
            "status": row["status"],
            "default_enabled": row["default_enabled"].lower() == "true",
            "targets": manifest.get("targets", []),
            "errors": module_errors,
        })
        errors.extend(f"{row['module_id']}: {message}" for message in module_errors)

        registries = manifest.get("registries", {})
        if row["module_type"] == "restoration":
            reg_path = project_root / registries.get("items", "")
            reg_errors = validate_restoration_registry(load_json(reg_path))
            errors.extend(f"quartet_restoration registry: {message}" for message in reg_errors)
        elif row["module_type"] == "dlc_adapter":
            reg_path = project_root / registries.get("content", "")
            reg_errors = validate_dlc_registry(load_json(reg_path))
            errors.extend(f"quartet_legacy_dlc registry: {message}" for message in reg_errors)

    # Validate independent composition profiles.
    profiles_report: list[dict[str, Any]] = []
    profile_ids: set[str] = set()
    for profile_path in sorted((project_root / "titles").glob("*/profiles/*.json")):
        profile = load_json(profile_path)
        rel = profile_path.relative_to(project_root).as_posix()
        profile_errors: list[str] = []
        if profile.get("type") != "br_composition_profile" or profile.get("format_version") != 1:
            profile_errors.append("unsupported profile type or version")
        profile_id = profile.get("profile_id")
        if not profile_id:
            profile_errors.append("missing profile_id")
        elif profile_id in profile_ids:
            profile_errors.append("duplicate profile_id")
        else:
            profile_ids.add(profile_id)
        if profile.get("target_id") not in known_targets:
            profile_errors.append("unknown target_id")
        enabled = profile.get("enabled_modules")
        if not isinstance(enabled, list) or not enabled:
            profile_errors.append("enabled_modules must be a non-empty array")
            enabled = []
        for module_id in enabled:
            if module_id not in known_modules:
                profile_errors.append(f"unknown module: {module_id}")
                continue
            manifest_row = next(row for row in module_rows if row["module_id"] == module_id)
            manifest = load_json(project_root / manifest_row["manifest_path"])
            if profile.get("target_id") not in manifest.get("targets", []):
                profile_errors.append(
                    f"module {module_id} does not support target {profile.get('target_id')}"
                )
        profiles_report.append({
            "path": rel,
            "profile_id": profile_id,
            "target_id": profile.get("target_id"),
            "status": profile.get("status"),
            "modules": enabled,
            "errors": profile_errors,
        })
        errors.extend(f"{rel}: {message}" for message in profile_errors)

    # Ensure no proprietary asset slipped into module source directories.
    proprietary_files: list[str] = []
    for module_root in sorted((project_root / "titles").glob("*/modules/*")):
        if not module_root.is_dir():
            continue
        for path in module_root.rglob("*"):
            if path.is_file() and path.suffix.lower() in BANNED_REPOSITORY_EXTENSIONS:
                proprietary_files.append(path.relative_to(project_root).as_posix())
    if proprietary_files:
        errors.append(
            "proprietary/binary assets found under module source directories"
        )

    translation_report: dict[str, Any] = {}
    for project in ("blue_reflection", "second_light", "blue_reflection_sun", "blue_reflection_ray"):
        required = args.require_translation and project in ("blue_reflection", "second_light")
        result, project_errors = validate_translation_project(
            project_root, project, required
        )
        translation_report[project] = result
        errors.extend(project_errors)

    # Explicitly verify the future modules remain independent.
    module_by_id = {
        row["module_id"]: load_json(project_root / row["manifest_path"])
        for row in module_rows
    }
    restoration_deps = set(module_by_id["quartet_restoration"].get("dependencies", []))
    dlc_deps = set(module_by_id["quartet_legacy_dlc"].get("dependencies", []))
    if "quartet_legacy_dlc" in restoration_deps or "quartet_restoration" in dlc_deps:
        errors.append("restoration and DLC adapter must remain independently selectable")

    report = {
        "type": "br_project_base_validation",
        "format_version": FORMAT_VERSION,
        "tool_version": TOOL_VERSION,
        "project_root": "<PROJECT_ROOT>",
        "status": "ok" if not errors else "failed",
        "targets": sorted(known_targets),
        "modules": modules_report,
        "profiles": profiles_report,
        "translation": translation_report,
        "policy": {
            "restoration_default_enabled": False,
            "dlc_default_enabled": False,
            "restoration_and_dlc_independent": True,
            "public_module_assets_forbidden": True,
            "switch_adapters_share_canonical_translation": True,
        },
        "proprietary_files_under_modules": proprietary_files,
        "warnings": warnings,
        "errors": errors,
    }
    output = Path(args.output).expanduser().resolve()
    atomic_json(output, report)
    print(f"Validation report: {output}")
    if errors:
        print(f"Validation failed with {len(errors)} error(s).", file=sys.stderr)
        return 1
    print("Project base and optional-module architecture are valid.")
    return 0


def load_path_rules(path: Path | None, side: str) -> list[tuple[str, str]]:
    if path is None:
        return []
    rows = read_tsv(path)
    rules: list[tuple[str, str]] = []
    for row in rows:
        if row.get("status") != "active" or row.get("side") != side:
            continue
        rules.append((row["path_prefix"], row["normalized_prefix"]))
    return sorted(rules, key=lambda item: len(item[0]), reverse=True)


def normalize_path(path: str, rules: list[tuple[str, str]]) -> str:
    normalized = path.replace("\\", "/")
    for prefix, replacement in rules:
        if normalized.startswith(prefix):
            return replacement + normalized[len(prefix):]
    return normalized


def cmd_inventory(args: argparse.Namespace) -> int:
    root = Path(args.root).expanduser().resolve()
    if not root.is_dir():
        raise ToolError(f"Inventory root does not exist: {root}")
    rules_path = (
        Path(args.path_rules).expanduser().resolve() if args.path_rules else None
    )
    rules = load_path_rules(rules_path, args.side)
    files: list[dict[str, Any]] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        rel = normalized_relative(path, root)
        files.append({
            "path": rel,
            "normalized_path": normalize_path(rel, rules),
            "size": path.stat().st_size,
            "sha256": sha256_file(path),
            "extension": path.suffix.lower(),
            "sample_block_size": SAMPLE_BLOCK_SIZE,
            "sample_hashes": sample_hashes(path),
        })
    report = {
        "type": "br_asset_inventory",
        "format_version": FORMAT_VERSION,
        "tool_version": TOOL_VERSION,
        "target_id": args.target_id,
        "archive_group": args.archive_group,
        "root": "<LOCAL_EXTRACTED_ROOT>",
        "normalization_side": args.side,
        "normalization_rules": str(rules_path) if rules_path else None,
        "files": files,
        "summary": {
            "files": len(files),
            "bytes": sum(entry["size"] for entry in files),
            "extensions": dict(sorted(Counter(
                entry["extension"] or "(none)" for entry in files
            ).items())),
        },
    }
    output = Path(args.output).expanduser().resolve()
    atomic_json(output, report)
    print(f"Inventory created: {output}")
    print(f"Files: {len(files)}")
    return 0


def file_ref(entry: dict[str, Any] | None) -> dict[str, Any] | None:
    if entry is None:
        return None
    return {
        "path": entry["path"],
        "size": entry["size"],
        "sha256": entry["sha256"],
        "extension": entry["extension"],
    }


def cmd_compare(args: argparse.Namespace) -> int:
    source = load_json(Path(args.source_inventory).expanduser().resolve())
    target = load_json(Path(args.target_inventory).expanduser().resolve())
    if source.get("type") != "br_asset_inventory":
        raise ToolError("Source is not a BR asset inventory")
    if target.get("type") != "br_asset_inventory":
        raise ToolError("Target is not a BR asset inventory")

    source_by_path = {entry["normalized_path"]: entry for entry in source["files"]}
    target_by_path = {entry["normalized_path"]: entry for entry in target["files"]}
    target_by_hash: dict[str, list[dict[str, Any]]] = defaultdict(list)
    target_by_basename_size: dict[tuple[str, int], list[dict[str, Any]]] = defaultdict(list)
    for entry in target["files"]:
        target_by_hash[entry["sha256"]].append(entry)
        target_by_basename_size[
            (Path(entry["normalized_path"]).name.lower(), entry["size"])
        ].append(entry)

    entries: list[dict[str, Any]] = []
    consumed_target_paths: set[str] = set()

    def add(
        classification: str,
        normalized_path: str,
        source_entry: dict[str, Any] | None,
        target_entry: dict[str, Any] | None,
        similarity: float,
        confidence: str,
    ) -> None:
        key = (
            f"{source.get('target_id')}|{target.get('target_id')}|"
            f"{classification}|{normalized_path}|"
            f"{source_entry['path'] if source_entry else ''}|"
            f"{target_entry['path'] if target_entry else ''}"
        )
        entries.append({
            "difference_id": "diff_" + hashlib.sha256(key.encode()).hexdigest()[:20],
            "classification": classification,
            "normalized_path": normalized_path,
            "source": file_ref(source_entry),
            "target": file_ref(target_entry),
            "binary_similarity": similarity,
            "confidence": confidence,
            "dependencies": [],
            "references": [],
            "review_classification": "not_assessed",
            "review_note": (
                "A structural difference is not automatically a censorship change."
            ),
        })

    for normalized_path, source_entry in sorted(source_by_path.items()):
        target_entry = target_by_path.get(normalized_path)
        if target_entry is not None:
            consumed_target_paths.add(target_entry["path"])
            if source_entry["sha256"] == target_entry["sha256"]:
                add("identical", normalized_path, source_entry, target_entry, 1.0, "exact")
            else:
                add(
                    "changed",
                    normalized_path,
                    source_entry,
                    target_entry,
                    sample_similarity(
                        source_entry.get("sample_hashes", []),
                        target_entry.get("sample_hashes", []),
                    ),
                    "exact_path",
                )
            continue

        moved = [
            candidate for candidate in target_by_hash.get(source_entry["sha256"], [])
            if candidate["path"] not in consumed_target_paths
        ]
        if len(moved) == 1:
            target_entry = moved[0]
            consumed_target_paths.add(target_entry["path"])
            add("probably_moved", normalized_path, source_entry, target_entry, 1.0, "exact_hash")
            continue

        basename_key = (
            Path(normalized_path).name.lower(),
            source_entry["size"],
        )
        candidates = [
            candidate for candidate in target_by_basename_size.get(basename_key, [])
            if candidate["path"] not in consumed_target_paths
        ]
        if len(candidates) == 1:
            target_entry = candidates[0]
            consumed_target_paths.add(target_entry["path"])
            add(
                "probably_moved",
                normalized_path,
                source_entry,
                target_entry,
                sample_similarity(
                    source_entry.get("sample_hashes", []),
                    target_entry.get("sample_hashes", []),
                ),
                "basename_and_size",
            )
        else:
            add("removed_in_target", normalized_path, source_entry, None, 0.0, "structural")

    for normalized_path, target_entry in sorted(target_by_path.items()):
        if target_entry["path"] in consumed_target_paths:
            continue
        add("new_in_target", normalized_path, None, target_entry, 0.0, "structural")

    summary = Counter(entry["classification"] for entry in entries)
    report = {
        "type": "br_asset_difference_report",
        "format_version": FORMAT_VERSION,
        "tool_version": TOOL_VERSION,
        "source_target": source.get("target_id"),
        "target_target": target.get("target_id"),
        "source_archive_group": source.get("archive_group"),
        "target_archive_group": target.get("archive_group"),
        "entries": entries,
        "summary": {
            "entries": len(entries),
            "classifications": dict(sorted(summary.items())),
            "censorship_candidates": 0,
            "note": (
                "Censorship classification is intentionally manual and remains "
                "separate from structural comparison."
            ),
        },
    }
    output = Path(args.output).expanduser().resolve()
    atomic_json(output, report)
    print(f"Difference report created: {output}")
    print(json.dumps(report["summary"]["classifications"], sort_keys=True))
    return 0


def append_registry_item(path: Path, registry_type: str, id_field: str, item: dict[str, Any]) -> None:
    data = load_json(path)
    if data.get("type") != registry_type or data.get("format_version") != 1:
        raise ToolError(f"Unsupported registry: {path}")
    items = data.get("items")
    if not isinstance(items, list):
        raise ToolError(f"Registry items are invalid: {path}")
    item_id = item[id_field]
    if any(existing.get(id_field) == item_id for existing in items):
        raise ToolError(f"Duplicate {id_field}: {item_id}")
    items.append(item)
    atomic_json(path, data)


def cmd_new_restoration_item(args: argparse.Namespace) -> int:
    registry = Path(args.registry).expanduser().resolve()
    item = {
        "restoration_id": args.restoration_id,
        "status": "not_mapped",
        "category": args.category,
        "source_files": [],
        "target_files": [],
        "mapping_reason": "",
        "dependencies": [],
        "changes": [],
        "platform_targets": [
            "blue_reflection_quartet",
            "blue_reflection_quartet_switch",
        ],
        "test_status": "not_tested",
        "test_evidence": [],
        "side_effects": [],
        "enabled_by_default": False,
        "notes": "",
    }
    append_registry_item(
        registry, "br_restoration_registry", "restoration_id", item
    )
    print(f"Added restoration skeleton: {args.restoration_id}")
    return 0


def cmd_new_dlc_item(args: argparse.Namespace) -> int:
    registry = Path(args.registry).expanduser().resolve()
    item = {
        "content_id": args.content_id,
        "content_type": args.content_type,
        "source": "blue_reflection_original_dlc",
        "source_ownership": "requires_original_dlc",
        "quartet_status": "not_mapped",
        "source_files": [],
        "target_bindings": [],
        "dependencies": [],
        "test_status": "not_tested",
        "platform_targets": [
            "blue_reflection_quartet",
            "blue_reflection_quartet_switch",
        ],
        "notes": "",
    }
    append_registry_item(
        registry, "br_dlc_content_registry", "content_id", item
    )
    print(f"Added DLC content skeleton: {args.content_id}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    validate = sub.add_parser(
        "validate-project",
        help="validate translation bases, module manifests, registries and profiles",
    )
    validate.add_argument("--project-root", required=True)
    validate.add_argument("--output", required=True)
    validate.add_argument("--require-translation", action="store_true")
    validate.set_defaults(func=cmd_validate_project)

    inventory = sub.add_parser(
        "inventory",
        help="create a normalized, hashed inventory of one extracted asset root",
    )
    inventory.add_argument("--root", required=True)
    inventory.add_argument("--target-id", required=True)
    inventory.add_argument("--archive-group", required=True)
    inventory.add_argument("--output", required=True)
    inventory.add_argument("--path-rules")
    inventory.add_argument("--side", choices=("source", "target"), default="source")
    inventory.set_defaults(func=cmd_inventory)

    compare = sub.add_parser(
        "compare",
        help="compare two asset inventories without claiming censorship",
    )
    compare.add_argument("--source-inventory", required=True)
    compare.add_argument("--target-inventory", required=True)
    compare.add_argument("--output", required=True)
    compare.set_defaults(func=cmd_compare)

    restoration = sub.add_parser(
        "new-restoration-item",
        help="append an empty restoration item to a local registry",
    )
    restoration.add_argument("--registry", required=True)
    restoration.add_argument("--restoration-id", required=True)
    restoration.add_argument("--category", required=True)
    restoration.set_defaults(func=cmd_new_restoration_item)

    dlc = sub.add_parser(
        "new-dlc-item",
        help="append an empty DLC content item to a local registry",
    )
    dlc.add_argument("--registry", required=True)
    dlc.add_argument("--content-id", required=True)
    dlc.add_argument(
        "--content-type",
        choices=("costume", "event", "system", "other"),
        required=True,
    )
    dlc.set_defaults(func=cmd_new_dlc_item)

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    try:
        return int(args.func(args))
    except ToolError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
