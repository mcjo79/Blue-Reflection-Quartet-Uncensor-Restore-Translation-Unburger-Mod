#!/usr/bin/env python3
"""Validate and build the Blue Reflection unified patch distribution skeleton."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import sys
import tempfile
import zipfile
from pathlib import Path
from typing import Any

TOOL_VERSION = "0.0.10"
ALLOWED_OPERATION_KINDS = {
    "merge_ebm_records",
    "merge_xml_records",
    "replace_entry",
    "copy_source_entry",
    "add_entry",
    "delete_entry",
    "edit_table_records",
}
ALLOWED_CONFLICT_POLICIES = {
    "structured_merge",
    "known_base_or_prompt",
    "backup_and_replace",
    "skip_unknown",
    "user_choice",
}
ALLOWED_MODULE_TYPES = {
    "translation",
    "restoration",
    "restoration_addon",
    "dlc_restoration",
    "dlc_adapter",  # historical/back-compat manifests only
}
PROPRIETARY_EXTENSIONS = {
    ".pak", ".ebm", ".ebd", ".g1m", ".g1t", ".ktid", ".kts",
    ".awb", ".acb", ".hca", ".ogg", ".wav", ".mp4", ".wmv",
    ".dds", ".png", ".jpg", ".jpeg",
}


class ValidationError(RuntimeError):
    pass


def load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ValidationError(f"missing JSON: {path}") from exc
    except json.JSONDecodeError as exc:
        raise ValidationError(f"invalid JSON in {path}: {exc}") from exc


def read_tsv(path: Path) -> list[dict[str, str]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as handle:
            return list(csv.DictReader(handle, delimiter="\t"))
    except FileNotFoundError as exc:
        raise ValidationError(f"missing TSV: {path}") from exc


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def atomic_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(data, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
        os.replace(temporary, path)
    except Exception:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise


def validate_manifest(manifest: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if manifest.get("type") != "br_patch_bundle" or manifest.get("format_version") != 1:
        return ["unsupported patch bundle type or format version"]
    compatibility = manifest.get("compatibility")
    if not isinstance(compatibility, dict):
        return ["compatibility must be an object"]
    if compatibility.get("mode") != "content_aware_rebuild":
        errors.append("compatibility mode must be content_aware_rebuild")
    if compatibility.get("require_whole_archive_hash") is not False:
        errors.append("whole-archive hash dependence must be disabled")
    if compatibility.get("preserve_unknown_entries") is not True:
        errors.append("unknown PAK entries must be preserved")
    if compatibility.get("allow_known_prior_outputs") is not True:
        errors.append("known prior patch outputs must be recognized")
    if compatibility.get("structured_merge_preferred") is not True:
        errors.append("structured merge must be preferred")

    targets = manifest.get("targets")
    modules = manifest.get("modules")
    operations = manifest.get("operations")
    if not isinstance(targets, list) or not isinstance(modules, list) or not isinstance(operations, list):
        return errors + ["targets, modules and operations must be arrays"]

    target_ids: set[str] = set()
    for target in targets:
        target_id = target.get("target_id") if isinstance(target, dict) else None
        if not target_id or target_id in target_ids:
            errors.append(f"invalid or duplicate bundle target: {target_id}")
        else:
            target_ids.add(target_id)
        if not isinstance(target, dict) or not target.get("required_paths"):
            errors.append(f"target {target_id} has no required_paths")

    module_ids: set[str] = set()
    module_map: dict[str, dict[str, Any]] = {}
    for module in modules:
        module_id = module.get("module_id") if isinstance(module, dict) else None
        if not module_id or module_id in module_ids:
            errors.append(f"invalid or duplicate module: {module_id}")
            continue
        module_ids.add(module_id)
        module_map[module_id] = module
        module_type = module.get("module_type")
        if module_type not in ALLOWED_MODULE_TYPES:
            errors.append(f"module {module_id} has unsupported module_type {module_type!r}")
        supported = set(module.get("supported_targets", []))
        if not supported or not supported <= target_ids:
            errors.append(f"module {module_id} has invalid supported targets")
        defaults = set(module.get("default_targets", []))
        if not defaults <= supported:
            errors.append(f"module {module_id} defaults outside supported targets")
        if module_type == "dlc_adapter" and defaults:
            errors.append(f"historical DLC adapter module {module_id} must remain opt-in")
        dependencies = module.get("dependencies", [])
        if not isinstance(dependencies, list):
            errors.append(f"module {module_id} dependencies must be an array")
        elif module_type == "restoration_addon" and not dependencies:
            errors.append(f"restoration add-on {module_id} must declare its parent dependency")
        source_targets = set(module.get("source_targets", []))
        if not source_targets <= target_ids:
            errors.append(f"module {module_id} has invalid source targets")

    operation_ids: set[str] = set()
    for operation in operations:
        if not isinstance(operation, dict):
            errors.append("operation is not an object")
            continue
        operation_id = operation.get("operation_id")
        if not operation_id or operation_id in operation_ids:
            errors.append(f"invalid or duplicate operation: {operation_id}")
        else:
            operation_ids.add(operation_id)
        if operation.get("module_id") not in module_ids:
            errors.append(f"operation {operation_id} references unknown module")
        if operation.get("target_id") not in target_ids:
            errors.append(f"operation {operation_id} references unknown target")
        if operation.get("kind") not in ALLOWED_OPERATION_KINDS:
            errors.append(f"operation {operation_id} has invalid kind")
        if operation.get("conflict_policy") not in ALLOWED_CONFLICT_POLICIES:
            errors.append(f"operation {operation_id} has invalid conflict policy")
        if not operation.get("archive_path") or not operation.get("entry_path"):
            errors.append(f"operation {operation_id} lacks archive or entry path")

    return errors


def cmd_validate(args: argparse.Namespace) -> int:
    project_root = Path(args.project_root).expanduser().resolve()
    manifest_path = Path(args.manifest).expanduser().resolve()
    output = Path(args.output).expanduser().resolve()
    errors: list[str] = []
    warnings: list[str] = []

    manifest = load_json(manifest_path)
    errors.extend(validate_manifest(manifest))

    project_modules = {row["module_id"]: row for row in read_tsv(project_root / "config/modules.tsv")}
    bundle_modules = {item["module_id"]: item for item in manifest.get("modules", []) if isinstance(item, dict)}
    if set(project_modules) != set(bundle_modules):
        errors.append("bundle module IDs do not match config/modules.tsv")

    target_rows = read_tsv(project_root / "config/series_targets.tsv")
    pc_targets = {
        row["target_id"] for row in target_rows
        if row["target_id"] in {
            "blue_reflection_original",
            "blue_reflection_quartet",
            "second_light_original",
        }
    }
    bundle_targets = {item["target_id"] for item in manifest.get("targets", []) if isinstance(item, dict)}
    if pc_targets != bundle_targets:
        errors.append("bundle target IDs do not match active PC targets")

    target_specs_path = project_root / "Blue_Reflection_Patcher/internal/targets/targets.json"
    target_specs = load_json(target_specs_path)
    ids = set()
    structural_fingerprints: dict[tuple[str, ...], str] = {}
    for item in target_specs:
        target_id = item.get("target_id")
        if target_id in ids or not target_id:
            errors.append(f"duplicate/invalid patcher target ID: {target_id}")
        ids.add(target_id)
        required_files = item.get("required_files")
        if not isinstance(required_files, list) or not required_files or not all(
            isinstance(path, str) and path for path in required_files
        ):
            errors.append(f"patcher target {target_id} has no valid structural required_files")
            continue
        fingerprint = tuple(sorted(path.replace("\\", "/").casefold() for path in required_files))
        if fingerprint in structural_fingerprints:
            errors.append(
                f"duplicate structural fingerprint for {target_id} and {structural_fingerprints[fingerprint]}"
            )
        structural_fingerprints[fingerprint] = target_id
        if any(key in item for key in ("steam_app_id", "executable_sha256", "install_dir_hints")):
            errors.append(f"patcher target {target_id} contains store/version-bound detection fields")
    if ids != pc_targets:
        errors.append("embedded patcher targets do not match active PC targets")

    required_go_files = [
        "Blue_Reflection_Patcher/go.mod",
        "Blue_Reflection_Patcher/cmd/brpatcher/main.go",
        "Blue_Reflection_Patcher/internal/detect/detect.go",
        "Blue_Reflection_Patcher/internal/bundle/bundle.go",
        "Blue_Reflection_Patcher/internal/plan/plan.go",
    ]
    missing_go = [rel for rel in required_go_files if not (project_root / rel).is_file()]
    if missing_go:
        errors.append("missing patcher source files: " + ", ".join(missing_go))

    go_mod_path = project_root / "Blue_Reflection_Patcher/go.mod"
    if go_mod_path.is_file():
        first_line = go_mod_path.read_text(encoding="utf-8").splitlines()[0].strip()
        if first_line != "module local/blue-reflection-patcher":
            errors.append("Go module path must use the neutral local namespace")

    proprietary: list[str] = []
    for root_rel in ("distribution", "Blue_Reflection_Patcher"):
        root = project_root / root_rel
        if not root.is_dir():
            continue
        for path in root.rglob("*"):
            if path.is_file() and path.suffix.lower() in PROPRIETARY_EXTENSIONS:
                proprietary.append(path.relative_to(project_root).as_posix())
    if proprietary:
        errors.append("proprietary game assets found in public distribution source")

    base_report_path = project_root / ".local/reports/BR_PROJECT_BASE_VALIDATION.json"
    base_status = "missing"
    if base_report_path.is_file():
        base_report = load_json(base_report_path)
        base_status = str(base_report.get("status", "unknown"))
        if base_status != "ok":
            errors.append("project base validation is not OK")
    else:
        warnings.append("BR_PROJECT_BASE_VALIDATION.json is not present")

    report = {
        "type": "br_pc_distribution_validation",
        "format_version": 1,
        "tool_version": TOOL_VERSION,
        "project_root": "<PROJECT_ROOT>",
        "status": "ok" if not errors else "failed",
        "bundle_manifest": {
            "bundle_id": manifest.get("bundle_id"),
            "bundle_version": manifest.get("bundle_version"),
            "modules": sorted(bundle_modules),
            "targets": sorted(bundle_targets),
            "operations": len(manifest.get("operations", [])),
        },
        "base_validation_status": base_status,
        "compatibility_policy": manifest.get("compatibility"),
        "detection_policy": {
            "primary_root": "current_working_directory",
            "fallback": "explicit_or_prompted_path",
            "identity": "structural_required_files",
            "store_metadata_required": False,
            "executable_hash_required": False,
        },
        "structural_targets": {
            item["target_id"]: item["required_files"] for item in target_specs
        },
        "public_proprietary_files": proprietary,
        "warnings": warnings,
        "errors": errors,
    }
    atomic_json(output, report)
    print(f"Distribution validation report: {output}")
    if errors:
        print(f"Validation failed with {len(errors)} error(s).", file=sys.stderr)
        return 1
    print("Unified PC patch distribution architecture is valid.")
    return 0


def cmd_build_bundle(args: argparse.Namespace) -> int:
    manifest_path = Path(args.manifest).expanduser().resolve()
    output = Path(args.output).expanduser().resolve()
    manifest = load_json(manifest_path)
    errors = validate_manifest(manifest)
    if errors:
        raise ValidationError("bundle manifest is invalid: " + "; ".join(errors))
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(output.suffix + ".tmp")
    if temporary.exists():
        temporary.unlink()
    with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(
            "manifest.json",
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        )
    with zipfile.ZipFile(temporary) as archive:
        bad = archive.testzip()
        if bad:
            raise ValidationError(f"corrupt generated bundle member: {bad}")
    os.replace(temporary, output)
    print(f"Development patch bundle: {output}")
    print(f"SHA-256: {sha256(output)}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    validate = sub.add_parser("validate")
    validate.add_argument("--project-root", required=True)
    validate.add_argument("--manifest", required=True)
    validate.add_argument("--output", required=True)
    validate.set_defaults(func=cmd_validate)

    bundle = sub.add_parser("build-bundle")
    bundle.add_argument("--manifest", required=True)
    bundle.add_argument("--output", required=True)
    bundle.set_defaults(func=cmd_build_bundle)
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    try:
        return int(args.func(args))
    except ValidationError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
