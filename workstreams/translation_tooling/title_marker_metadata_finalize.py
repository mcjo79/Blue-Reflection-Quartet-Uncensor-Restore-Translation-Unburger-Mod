#!/usr/bin/env python3
"""Finalize title-marker metadata from the actual local workstream state.

This intentionally updates STATUS.json and TITLE_MARKER_COMPOSITION.json at run
 time instead of relying on fragile old-value JSON merge assumptions.  It is
idempotent, preserves unrelated fields, and backs up both source files before
writing any change.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class FinalizeError(RuntimeError):
    pass


def load_object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise FinalizeError(f"cannot read JSON {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise FinalizeError(f"JSON root must be an object: {path}")
    return value


def atomic_write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    fd, raw_tmp = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    tmp = Path(raw_tmp)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
        dir_fd = os.open(path.parent, os.O_DIRECTORY)
        try:
            os.fsync(dir_fd)
        finally:
            os.close(dir_fd)
    finally:
        tmp.unlink(missing_ok=True)


def require_object(parent: dict[str, Any], key: str) -> dict[str, Any]:
    value = parent.get(key)
    if value is None:
        value = {}
        parent[key] = value
    if not isinstance(value, dict):
        raise FinalizeError(f"expected object at {key!r}")
    return value


def finalize_status(status: dict[str, Any]) -> None:
    status["current_stage"] = "title_markers_runtime_approved_all_targets"
    status["next_stage"] = "unified_installer_architecture_and_module_selection"
    status["next_script"] = "workstreams/translation_tooling/25_validate_title_marker_profiles.sh"
    status["orchestrator_next_action"] = (
        "Run the closed-profile validator, then begin unified installer architecture "
        "and module-selection integration."
    )

    safety = require_object(status, "safety")
    safety["title_marker_policy"] = (
        "All three runtime targets are confirmed. Original Blue Reflection uses the "
        "UNBURGER MOD translation label; Quartet supports UNBURGER, UNCENSOR, and "
        "combined variants. Second Light keeps its approved production marker."
    )

    marker = require_object(status, "title_marker")
    marker["implementation"] = (
        "Three runtime-confirmed production marker adapters: Second Light seed_title.g1t "
        "BC7 crop; Quartet b0_title.g1t texture 002.dds BC7 replacement; Original Blue "
        "Reflection 12_title.kscl embedded fnt_credit BC3/DXT5 replacement."
    )
    marker["runtime_confirmation"] = (
        "Second Light, Quartet, and Original Blue Reflection production markers are "
        "visible and approved."
    )
    marker["blue_reflection_original"] = {
        "resource_archive": "DATA/PACK00_04_1.PAK",
        "resource_path": "data/x64/res_en/layout/12_title.kscl",
        "embedded_texture": "fnt_credit",
        "texture_index": 7,
        "texture_dimensions": [480, 32],
        "texture_format": "BC3/DXT5",
        "runtime_status": "confirmed_visible_and_visual_design_approved",
        "allowed_labels": ["UNBURGER MOD"],
        "approved_label_template": "UNBURGER MOD (v<translation>)",
        "version_source": "workstreams/translation/VERSION",
        "build_script": "workstreams/translation_tooling/24_build_blue_reflection_title_marker.sh",
        "config": "workstreams/translation_tooling/config/title_markers/blue_reflection_title_marker.json",
        "approved_text_rgba": [45, 45, 45, 255],
    }

    diagnostic = require_object(status, "title_texture_diagnostic")
    diagnostic["remaining_games_strategy"] = (
        "completed: production runtime assets are identified for all three games; "
        "keep old probe scripts diagnostic-only"
    )

    milestones = require_object(status, "completed_milestones")
    milestones["blue_reflection_original_title_kscl_target"] = (
        "confirmed DATA/PACK00_04_1.PAK:data/x64/res_en/layout/12_title.kscl "
        "embedded texture fnt_credit"
    )
    milestones["blue_reflection_original_title_marker_runtime_test"] = (
        "visible_and_visual_design_approved_dark_gray_UNBURGER_MOD"
    )


def finalize_composition(composition: dict[str, Any]) -> None:
    implementation = require_object(composition, "implementation")
    targets = require_object(implementation, "targets")

    second_light = require_object(targets, "second_light_original")
    second_light["runtime_status"] = "confirmed_visible_and_visual_design_approved"

    quartet = require_object(targets, "blue_reflection_quartet")
    quartet["runtime_status"] = "confirmed_visible_and_visual_design_approved"

    targets["blue_reflection_original"] = {
        "method": "in-place replacement of the embedded fnt_credit BC3/DXT5 texture in 12_title.kscl",
        "resource_archive": "DATA/PACK00_04_1.PAK",
        "resource_path": "data/x64/res_en/layout/12_title.kscl",
        "embedded_texture": "fnt_credit",
        "texture_index": 7,
        "texture_dimensions": [480, 32],
        "build_script": "workstreams/translation_tooling/24_build_blue_reflection_title_marker.sh",
        "config": "workstreams/translation_tooling/config/title_markers/blue_reflection_title_marker.json",
        "runtime_status": "confirmed_visible_and_visual_design_approved",
        "allowed_variants": ["UNBURGER MOD"],
        "approved_label_template": "UNBURGER MOD (v<translation>)",
        "version_source": "workstreams/translation/VERSION",
        "approved_text_rgba": [45, 45, 45, 255],
    }
    implementation["validation_script"] = (
        "workstreams/translation_tooling/25_validate_title_marker_profiles.sh"
    )
    implementation["diagnostic_only_steps"] = [
        "11_collect_title_texture_evidence.sh",
        "12_carve_hidden_title_textures.sh",
        "13_scan_recursive_title_textures.sh",
        "14_build_second_light_title_marker_proof.sh",
        "15_build_second_light_seed_title_pixel_proof.sh",
        "17_build_blue_reflection_title_markers.sh",
        "18_build_blue_reflection_title_layout_probe.sh",
        "19_collect_quartet_title_candidates.sh",
        "20_build_title_resource_pixel_probe.sh",
        "21_build_quartet_b0_title_texture_probe.sh",
        "23_build_blue_reflection_title_kscl_probe.sh",
    ]


def main(project_root: Path) -> int:
    tooling = project_root / "workstreams/translation_tooling"
    version = (tooling / "VERSION").read_text(encoding="utf-8").strip()
    if version != "0.0.43":
        raise FinalizeError(f"metadata finalizer requires translation_tooling 0.0.43, found {version!r}")

    status_path = tooling / "STATUS.json"
    composition_path = tooling / "TITLE_MARKER_COMPOSITION.json"
    status_before = status_path.read_bytes()
    composition_before = composition_path.read_bytes()

    status = load_object(status_path)
    composition = load_object(composition_path)
    finalize_status(status)
    finalize_composition(composition)

    status_after = (json.dumps(status, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    composition_after = (json.dumps(composition, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    if status_before == status_after and composition_before == composition_after:
        print("Title-marker metadata already finalized.")
        return 0

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup = project_root / ".local/backups/translation_tooling/title_marker_metadata" / stamp
    backup.mkdir(parents=True, exist_ok=False)
    (backup / "STATUS.json").write_bytes(status_before)
    (backup / "TITLE_MARKER_COMPOSITION.json").write_bytes(composition_before)

    try:
        atomic_write_json(status_path, status)
        atomic_write_json(composition_path, composition)
    except Exception:
        shutil.copy2(backup / "STATUS.json", status_path)
        shutil.copy2(backup / "TITLE_MARKER_COMPOSITION.json", composition_path)
        raise

    print("Title-marker metadata finalized from the actual local state.")
    print(f"Backup: {backup}")
    return 0


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("--project-root", required=True)
    return result


if __name__ == "__main__":
    try:
        arguments = parser().parse_args()
        raise SystemExit(main(Path(arguments.project_root).expanduser().resolve()))
    except (FinalizeError, OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}", file=os.sys.stderr)
        raise SystemExit(1)
