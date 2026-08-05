#!/usr/bin/env python3
"""Build a reversible title-layout probe for Blue Reflection Original and Quartet.

The probe does not modify any texture. It changes only the translated/localized
style PAKs produced by step 08:

* a17 title logo: small, magenta, upper-left;
* a18 title logo: small, cyan, upper-right;
* a17 copyright: redirected to the existing a17_common help strip;
* a18 copyright: redirected to the existing a17_common A-button strip.

This distinguishes a17 versus a18 layout selection and separately verifies
whether an existing cross-atlas binding is honoured at runtime. Installed game
files are never modified by this builder; step 09 performs the transactional
install and restore.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from blue_reflection_title_markers import MarkerError, patch_named_image
from second_light_title_marker_proof import (
    archive_report_entry,
    atomic_json,
    extract_pak,
    install_verified_output,
    list_pak_entries,
    recompute_main_summary,
    repack_stage,
    sha256_file,
    verify_repacked,
)

REPORT_TYPE = "br_blue_reflection_title_layout_probe_report"


@dataclass(frozen=True)
class Target:
    target_id: str
    style_archive: str
    style_stem: str
    style_prefix: str


TARGETS = (
    Target(
        target_id="blue_reflection_original",
        style_archive="DATA/PACK02_1.PAK",
        style_stem="PACK02_1",
        style_prefix="saves_en",
    ),
    Target(
        target_id="blue_reflection_quartet",
        style_archive="Data/PACK12.PAK",
        style_stem="PACK12",
        style_prefix="saves/b1",
    ),
)

PROBES = (
    {
        "layout": "a17",
        "layout_file": "ui/a17_title/uil_title02.xml",
        "style_file": "ui/gen_styles/uis_gen_a17_title.xml",
        "style_name": "gen_a17_title01_copyright",
        "logo": {
            "pos": "20,20,0",
            "scale": "0.35,0.35,1",
            "color": "255,64,200,255",
        },
        "copyright": {
            "pos": "20,620,0",
            "scale": "1,1,1",
            "size_wh": "384,58",
            "color": "255,255,255,255",
        },
        "binding": {
            "texture": "ui/a17_common.g1t",
            "texture_index": "0",
            "uvwh": "0,0,384,58",
        },
        "expected_visual": "small magenta logo at upper-left and existing help strip at lower-left",
    },
    {
        "layout": "a18",
        "layout_file": "ui/a18_title/uil_a18_title02.xml",
        "style_file": "ui/gen_styles/uis_gen_a18_title.xml",
        "style_name": "gen_a18_title01_copyright",
        "logo": {
            "pos": "750,20,0",
            "scale": "0.35,0.35,1",
            "color": "64,220,255,255",
        },
        "copyright": {
            "pos": "750,620,0",
            "scale": "1,1,1",
            "size_wh": "384,58",
            "color": "255,255,255,255",
        },
        "binding": {
            "texture": "ui/a17_common.g1t",
            "texture_index": "0",
            "uvwh": "0,64,384,58",
        },
        "expected_visual": "small cyan logo at upper-right and existing A-button strip at lower-right",
    },
)


def load_clean_report(project_root: Path) -> tuple[Path, dict[str, Any]]:
    path = project_root / ".local/reports/translation/BR_TRANSLATION_PAK_REPACK_REPORT.json"
    if not path.is_file():
        raise MarkerError("Clean step-08 report is missing; run steps 07 and 08")
    report = json.loads(path.read_text(encoding="utf-8"))
    if report.get("type") != "br_translation_pak_repack_report" or report.get("status") != "ok":
        raise MarkerError("Step-08 report is not clean")
    if report.get("title_markers") or report.get("title_layout_probe") or report.get("title_marker_proof"):
        raise MarkerError(
            "The repack report already contains a title diagnostic. Rerun steps 07 and 08 "
            "with BR_TITLE_MARKER=none before step 18."
        )
    return path, report


def find_entry(report: dict[str, Any], target: Target) -> dict[str, Any]:
    matches = [
        item
        for item in report.get("archives", [])
        if isinstance(item, dict)
        and item.get("target_id") == target.target_id
        and item.get("archive_relative_path") == target.style_archive
    ]
    if len(matches) != 1:
        raise MarkerError(
            f"Expected one {target.style_archive} output for {target.target_id}, found {len(matches)}"
        )
    return matches[0]


def patch_stage(stage: Path, target: Target) -> list[dict[str, Any]]:
    changes: list[dict[str, Any]] = []
    for probe in PROBES:
        layout_path = stage / target.style_prefix / probe["layout_file"]
        style_path = stage / target.style_prefix / probe["style_file"]
        if not layout_path.is_file():
            raise MarkerError(f"Missing layout probe target: {layout_path}")
        if not style_path.is_file():
            raise MarkerError(f"Missing style probe target: {style_path}")
        changes.append(patch_named_image(layout_path, "logo", probe["logo"]))
        changes.append(patch_named_image(layout_path, "copyright", probe["copyright"]))
        changes.append(
            patch_named_image(style_path, str(probe["style_name"]), probe["binding"])
        )
    return changes


def build_target(
    project_root: Path,
    target: Target,
    report: dict[str, Any],
    temp_root: Path,
    gust_pak: Path,
    timeout: int,
) -> dict[str, Any]:
    entry = find_entry(report, target)
    source = project_root / str(entry.get("output_path", ""))
    expected = str(entry.get("output_sha256", ""))
    if not source.is_file() or sha256_file(source) != expected:
        raise MarkerError(f"Step-08 style output changed: {source}")

    target_root = temp_root / target.target_id
    stage = target_root / "staging" / target.style_stem
    manifest, extract_tail = extract_pak(gust_pak, source, stage, timeout)
    changes = patch_stage(stage, target)
    built, repack_tail = repack_stage(
        gust_pak, stage, manifest, target.style_stem, timeout
    )
    checked, failures, listing_tail = verify_repacked(
        gust_pak,
        built,
        stage,
        target_root / "verify" / target.style_stem,
        timeout,
    )
    if failures:
        raise MarkerError(
            f"Full verification of {target.style_archive} failed: {len(failures)}"
        )
    entries, _ = list_pak_entries(gust_pak, built, built.parent, timeout)
    archive = archive_report_entry(
        archive_stem=target.style_stem,
        archive_relative_path=target.style_archive,
        final_pak=built,
        project_root=project_root,
        changed_files=len(changes),
        listed_entries=len(entries),
        entries_checked=checked,
        failures=failures,
        repack_tail=repack_tail,
        listing_tail=listing_tail,
        source_policy="verified_step08_translation_output_plus_layout_and_existing_cross_atlas_probe",
    )
    archive["target_id"] = target.target_id
    return {
        "target": target,
        "built": built,
        "archive": archive,
        "changes": changes,
        "extract_tail": extract_tail,
    }


def build(args: argparse.Namespace) -> int:
    project_root = Path(args.project_root).expanduser().resolve()
    gust_pak = Path(args.gust_pak).expanduser().resolve()
    if not gust_pak.is_file() or not os.access(gust_pak, os.X_OK):
        raise MarkerError(f"gust_pak is not executable: {gust_pak}")
    report_path, main_report = load_clean_report(project_root)

    build_root = project_root / ".local/build/translation"
    final_probe_root = build_root / "blue_reflection_title_layout_probe"
    report_output = (
        project_root
        / ".local/reports/translation/BR_BLUE_REFLECTION_TITLE_LAYOUT_PROBE_REPORT.json"
    )
    build_root.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix=".br_title_layout_probe.", dir=build_root) as raw:
        temp_root = Path(raw)
        results = [
            build_target(project_root, target, main_report, temp_root, gust_pak, args.timeout)
            for target in TARGETS
        ]

        publish = build_root / ".blue_reflection_title_layout_probe.publish"
        if publish.exists():
            shutil.rmtree(publish)
        publish.mkdir(parents=True)
        new_entries: list[dict[str, Any]] = []
        target_reports: list[dict[str, Any]] = []

        for result in results:
            target: Target = result["target"]
            final_path = build_root / "archives" / target.target_id / target.style_archive
            install_verified_output(result["built"], final_path)
            archive = dict(result["archive"])
            archive["output_path"] = final_path.relative_to(project_root).as_posix()
            archive["output_sha256"] = sha256_file(final_path)
            archive["output_bytes"] = final_path.stat().st_size
            new_entries.append(archive)
            target_reports.append(
                {
                    "target_id": target.target_id,
                    "style_archive": target.style_archive,
                    "runtime_status": "awaiting_manual_layout_probe",
                    "probes": PROBES,
                    "xml_changes": [
                        {
                            **{k: v for k, v in item.items() if k != "path"},
                            "path": item["path"].relative_to(temp_root).as_posix(),
                        }
                        for item in result["changes"]
                    ],
                    "archive_report": archive,
                    "extract_stdout_tail": result["extract_tail"],
                }
            )

        if final_probe_root.exists():
            shutil.rmtree(final_probe_root)
        os.replace(publish, final_probe_root)

    keys = {(item["target_id"], item["archive_relative_path"]) for item in new_entries}
    kept = [
        item
        for item in main_report.get("archives", [])
        if isinstance(item, dict)
        and (item.get("target_id"), item.get("archive_relative_path")) not in keys
    ]
    main_report["archives"] = sorted(
        kept + new_entries,
        key=lambda item: (str(item.get("target_id", "")), str(item.get("archive_relative_path", ""))),
    )
    main_report["title_layout_probe"] = {
        "status": "ok",
        "method": "distinct_a17_a18_geometry_plus_existing_a17_common_regions",
        "targets": [item.target_id for item in TARGETS],
        "runtime_status": "awaiting_manual_layout_probe",
    }
    recompute_main_summary(main_report)
    atomic_json(report_path, main_report)
    atomic_json(
        report_output,
        {
            "type": REPORT_TYPE,
            "format_version": 1,
            "status": "ok",
            "generated_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "project_root": "<PROJECT_ROOT>",
            "method": "distinct_a17_a18_geometry_plus_existing_a17_common_regions",
            "targets": target_reports,
            "interpretation": {
                "a17": "magenta small logo upper-left; help strip lower-left",
                "a18": "cyan small logo upper-right; A-button strip lower-right",
                "moved_logo_without_strip": "layout is active but cross-atlas binding is not rendered",
                "unchanged": "neither patched localized layout is active for that screen",
            },
            "safety": {
                "installed_game_files_modified_during_build": False,
                "textures_modified": False,
                "proprietary_assets_in_update_package": False,
                "full_pak_reextract_hash_verification": True,
                "installation_requires_step_09": True,
            },
        },
    )
    print("Blue Reflection title-layout probe built and fully verified.")
    print("No texture or installed game file was modified during the build.")
    return 0


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser(description=__doc__)
    value.add_argument("--project-root", required=True)
    value.add_argument("--gust-pak", required=True)
    value.add_argument("--timeout", type=int, default=1800)
    return value


if __name__ == "__main__":
    try:
        raise SystemExit(build(parser().parse_args()))
    except MarkerError as exc:
        print(f"ERROR: {exc}", file=os.sys.stderr)
        raise SystemExit(1)
