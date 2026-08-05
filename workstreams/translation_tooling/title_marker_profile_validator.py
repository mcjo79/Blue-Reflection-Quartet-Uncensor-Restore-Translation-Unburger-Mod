#!/usr/bin/env python3
"""Validate the closed production title-marker profiles without game assets."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def fail(message: str) -> None:
    raise RuntimeError(message)


def load_json(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        fail(f"cannot read JSON {path}: {exc}")
    if not isinstance(data, dict):
        fail(f"JSON root must be an object: {path}")
    return data


def assert_text_fits(metrics: dict, width: int, height: int, label: str) -> None:
    x = int(metrics["text_x"])
    y = int(metrics["text_y"])
    text_width = int(metrics["text_width"])
    text_height = int(metrics["text_height"])
    if x < 0 or y < 0 or x + text_width > width or y + text_height > height:
        fail(f"rendered label is outside {width}x{height}: {label!r}, metrics={metrics}")


def validate(project_root: Path) -> int:
    tooling = project_root / "workstreams/translation_tooling"
    sys.path.insert(0, str(tooling))

    import blue_reflection_title_marker as br1
    import quartet_title_marker as quartet

    # Original Blue Reflection: exact approved label, colour and geometry.
    br1_label, br1_version = br1.build_label(project_root)
    expected_br1 = f"UNBURGER MOD (v{br1_version})"
    if br1_label != expected_br1:
        fail(f"BR1 label mismatch: {br1_label!r} != {expected_br1!r}")
    _, br1_config = br1.load_config(project_root, None)
    if br1_config["style"]["text_rgba"] != [45, 45, 45, 255]:
        fail("BR1 approved text_rgba must be [45, 45, 45, 255]")
    br1_pixels, br1_metrics = br1.render_label(br1_label, 480, 32, br1_config)
    assert_text_fits(br1_metrics, 480, 32, br1_label)
    if len(br1.encode_dxt5_image(br1_pixels, 480, 32)) != 15360:
        fail("BR1 DXT5 output size mismatch")

    # Quartet: all three installer-facing variants must fit the approved Y=55 layout.
    _, quartet_config = quartet.load_marker_config(project_root, None)
    if quartet_config["layout"]["text_rect"] != [320, 55, 1120, 24]:
        fail("Quartet approved text_rect must be [320, 55, 1120, 24]")
    quartet_labels: dict[str, str] = {}
    for variant in ("unburger", "uncensor", "combined"):
        label, _versions = quartet.build_label(project_root, variant)
        _pixels, metrics = quartet.render_label(label, 1760, 100, quartet_config)
        assert_text_fits(metrics, 1760, 100, label)
        quartet_labels[variant] = label

    # Closed-state metadata must agree with the production generators.
    status = load_json(tooling / "STATUS.json")
    if status.get("current_stage") != "title_markers_runtime_approved_all_targets":
        fail("STATUS.json does not mark all title targets approved")
    br1_status = status.get("title_marker", {}).get("blue_reflection_original", {})
    if br1_status.get("approved_label_template") != "UNBURGER MOD (v<translation>)":
        fail("STATUS.json BR1 label template mismatch")
    if br1_status.get("approved_text_rgba") != [45, 45, 45, 255]:
        fail("STATUS.json BR1 colour mismatch")

    composition = load_json(tooling / "TITLE_MARKER_COMPOSITION.json")
    targets = composition.get("implementation", {}).get("targets", {})
    for target in ("second_light_original", "blue_reflection_original", "blue_reflection_quartet"):
        runtime = targets.get(target, {}).get("runtime_status", "")
        if not str(runtime).startswith("confirmed"):
            fail(f"composition target is not confirmed: {target}: {runtime!r}")

    # Production generators must no longer emit stale awaiting/candidate statuses.
    production_sources = (
        tooling / "second_light_title_marker.py",
        tooling / "quartet_title_marker.py",
        tooling / "blue_reflection_title_marker.py",
    )
    for source in production_sources:
        text = source.read_text(encoding="utf-8")
        if '"runtime_status": "awaiting' in text:
            fail(f"stale awaiting runtime status remains in production generator: {source.name}")
        if "production-candidate" in text:
            fail(f"stale production-candidate wording remains: {source.name}")

    print("Title-marker production profiles validated.")
    print(f"Original Blue Reflection: {br1_label}")
    for variant, label in quartet_labels.items():
        print(f"Quartet {variant}: {label}")
    print("Second Light, Quartet, and Original runtime statuses: confirmed")
    return 0


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("--project-root", required=True)
    return result


if __name__ == "__main__":
    try:
        args = parser().parse_args()
        raise SystemExit(validate(Path(args.project_root).expanduser().resolve()))
    except (RuntimeError, OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
