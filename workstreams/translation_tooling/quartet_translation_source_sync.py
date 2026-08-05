#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import tempfile
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

PRESERVED_PROJECTS = ("blue_reflection", "second_light", "blue_reflection_sun")
ALL_PROJECTS = ("blue_reflection", "second_light", "blue_reflection_sun", "blue_reflection_ray")
UNIT_TYPES = {"br_event_translation_unit", "br_system_translation_unit"}


class SyncError(RuntimeError):
    pass


def atomic_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(data, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except Exception:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def iter_units(root: Path, project: str) -> Iterable[tuple[Path, dict[str, Any]]]:
    translation_root = root / "titles" / project / "translation"
    if not translation_root.is_dir():
        return
    for path in sorted(translation_root.rglob("*.json")):
        if path.name == "translation_manifest.json":
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if data.get("type") in UNIT_TYPES:
            yield path, data


def parse_version(text: str) -> tuple[int, int, int]:
    match = re.fullmatch(r"(\d+)\.(\d+)\.(\d+)", text.strip())
    if not match:
        raise SyncError(f"unsupported translation version: {text!r}")
    return tuple(map(int, match.groups()))


def initial_generated_en(record: dict[str, Any]) -> str:
    alignment = record.get("alignment")
    source = alignment.get("initial_en_source") if isinstance(alignment, dict) else None
    if source in {"official_en", "quartet_official_en"}:
        value = record.get("en_original")
        return value if isinstance(value, str) else ""
    if source == "quartet_en":
        value = record.get("en_auxiliary")
        return value if isinstance(value, str) else ""
    return ""


def record_was_authored(record: dict[str, Any]) -> bool:
    current = record.get("en")
    if not isinstance(current, str):
        return True
    if current != initial_generated_en(record):
        return True
    if "notes" in record and record.get("notes") not in (None, "", []):
        return True
    if "status" in record:
        return True
    return False


def content_state(record: dict[str, Any]) -> dict[str, Any]:
    return {
        "en": record.get("en"),
        "has_notes": "notes" in record,
        "notes": record.get("notes"),
        "has_status": "status" in record,
        "status": record.get("status"),
    }


def target_paths(root: Path, project: str, target_id: str) -> list[str]:
    paths: list[str] = []
    for _, unit in iter_units(root, project):
        target = unit.get("targets", {}).get(target_id)
        if isinstance(target, dict) and isinstance(target.get("template_path"), str):
            paths.append(target["template_path"])
    return paths


def branch_counts(paths: list[str]) -> Counter[str]:
    counts: Counter[str] = Counter()
    for path in paths:
        normalized = path.replace("\\", "/")
        if "/PACK01_01/" in normalized or "/PACK02_01/" in normalized or "/b2/" in normalized:
            counts["b2"] += 1
        if "/PACK01_02/" in normalized or "/PACK02_02/" in normalized or "/b3/" in normalized:
            counts["b3"] += 1
        if "/PACK01_03/" in normalized or "/PACK02_03/" in normalized or "/b4/" in normalized:
            counts["b4"] += 1
    return counts


def mapping_state(root: Path) -> dict[str, Any]:
    second_light_paths = target_paths(root, "second_light", "second_light_quartet")
    ray_paths = target_paths(root, "blue_reflection_ray", "blue_reflection_ray_quartet")
    second_light = branch_counts(second_light_paths)
    ray = branch_counts(ray_paths)
    if second_light["b2"] > 0 and second_light["b4"] == 0 and ray["b4"] > 0 and ray["b2"] == 0:
        state = "wrong_b2_second_light_b4_ray"
    elif second_light["b4"] > 0 and second_light["b2"] == 0 and ray["b2"] > 0 and ray["b4"] == 0:
        state = "correct_b4_second_light_b2_ray"
    else:
        state = "mixed_or_unknown"
    return {
        "state": state,
        "second_light": dict(second_light),
        "ray": dict(ray),
        "second_light_target_units": len(second_light_paths),
        "ray_target_units": len(ray_paths),
    }


def unsafe_generated_scope(root: Path) -> dict[str, Any]:
    scopes = {
        "wrong_second_light_quartet_extensions": [],
        "wrong_ray_database": [],
    }
    extension_units = extension_records = ray_units = ray_records = 0
    for path, unit in iter_units(root, "second_light"):
        if unit.get("source_role") != "quartet_extension":
            continue
        extension_units += 1
        for record in unit.get("records", []):
            extension_records += 1
            if record_was_authored(record):
                scopes["wrong_second_light_quartet_extensions"].append({
                    "path": path.relative_to(root).as_posix(),
                    "logical_id": record.get("logical_id"),
                    "en": record.get("en"),
                    "initial_generated_en": initial_generated_en(record),
                })
    for path, unit in iter_units(root, "blue_reflection_ray"):
        ray_units += 1
        for record in unit.get("records", []):
            ray_records += 1
            if record_was_authored(record):
                scopes["wrong_ray_database"].append({
                    "path": path.relative_to(root).as_posix(),
                    "logical_id": record.get("logical_id"),
                    "en": record.get("en"),
                    "initial_generated_en": initial_generated_en(record),
                })
    scopes["counts"] = {
        "wrong_second_light_extension_units": extension_units,
        "wrong_second_light_extension_records": extension_records,
        "wrong_ray_units": ray_units,
        "wrong_ray_records": ray_records,
        "authored_wrong_second_light_extension_records": len(scopes["wrong_second_light_quartet_extensions"]),
        "authored_wrong_ray_records": len(scopes["wrong_ray_database"]),
    }
    return scopes


def snapshot(root: Path, output: Path) -> dict[str, Any]:
    state = mapping_state(root)
    if state["state"] == "correct_b4_second_light_b2_ray":
        raise SyncError("Quartet game partition mapping is already corrected")
    if state["state"] != "wrong_b2_second_light_b4_ray":
        raise SyncError(f"cannot safely correct mixed/unknown mapping state: {state}")

    unsafe = unsafe_generated_scope(root)
    counts = unsafe["counts"]
    if counts["authored_wrong_second_light_extension_records"]:
        raise SyncError(
            "wrong Second Light b2 extension records contain authored content; "
            "manual salvage is required before correction"
        )
    if counts["authored_wrong_ray_records"]:
        raise SyncError(
            "the wrong b4-backed RAY database contains authored content; "
            "manual salvage is required before replacement"
        )

    records: dict[str, Any] = {}
    project_counts: Counter[str] = Counter()
    for project in PRESERVED_PROJECTS:
        for path, unit in iter_units(root, project):
            if project == "second_light" and unit.get("source_role") == "quartet_extension":
                continue
            for record in unit.get("records", []):
                logical_id = record.get("logical_id")
                if not isinstance(logical_id, str) or logical_id in records:
                    raise SyncError(f"invalid/duplicate preserved logical_id: {logical_id}")
                records[logical_id] = {
                    "project": project,
                    "path": path.relative_to(root).as_posix(),
                    "content": content_state(record),
                }
                project_counts[project] += 1

    version = (root / "workstreams/translation/VERSION").read_text(encoding="utf-8").strip()
    parse_version(version)
    data = {
        "type": "br_translation_pre_quartet_partition_correction",
        "format_version": 2,
        "translation_version": version,
        "mapping_state": state,
        "preserved_records": records,
        "preserved_counts": dict(project_counts),
        "generated_wrong_scope": unsafe,
    }
    atomic_json(output, data)
    return data


def unit_stats(root: Path, project: str) -> dict[str, Any]:
    stats: Counter[str] = Counter()
    status: Counter[str] = Counter()
    target_branches: Counter[str] = Counter()
    for _, unit in iter_units(root, project):
        stats["units"] += 1
        category = unit.get("category", "unknown")
        role = unit.get("source_role", "unknown")
        stats[f"{category}_units"] += 1
        stats[f"{role}_units"] += 1
        targets = unit.get("targets", {})
        for target in targets.values():
            if isinstance(target, dict) and isinstance(target.get("template_path"), str):
                target_branches.update(branch_counts([target["template_path"]]))
        for record in unit.get("records", []):
            stats["records"] += 1
            stats[f"{category}_records"] += 1
            stats[f"{role}_records"] += 1
            auxiliary = record.get("en_auxiliary")
            if isinstance(auxiliary, str) and auxiliary.strip():
                stats["nonnull_en_auxiliary"] += 1
                stats[f"{category}_nonnull_en_auxiliary"] += 1
                value_status = (record.get("alignment") or {}).get("auxiliary_value_status")
                if value_status in (None, "available") and auxiliary.strip() not in {"-", "－", "--"}:
                    stats["usable_en_auxiliary"] += 1
                    stats[f"{category}_usable_en_auxiliary"] += 1
            if isinstance(record.get("en"), str) and record.get("en") != "":
                stats["nonnull_en"] += 1
            status[str(record.get("alignment", {}).get("status", "missing"))] += 1
    return {
        **dict(stats),
        "alignment_statuses": dict(sorted(status.items())),
        "target_branch_counts": dict(target_branches),
    }


def current_content_records(root: Path) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for project in PRESERVED_PROJECTS:
        for path, unit in iter_units(root, project):
            if project == "second_light" and unit.get("source_role") == "quartet_extension":
                continue
            for record in unit.get("records", []):
                logical_id = record.get("logical_id")
                if isinstance(logical_id, str):
                    result[logical_id] = {
                        "project": project,
                        "path": path.relative_to(root).as_posix(),
                        "content": content_state(record),
                    }
    return result


def finalize(root: Path, before_path: Path, output_dir: Path) -> dict[str, Any]:
    before = json.loads(before_path.read_text(encoding="utf-8"))
    if before.get("type") != "br_translation_pre_quartet_partition_correction":
        raise SyncError("unsupported pre-correction snapshot")

    post_state = mapping_state(root)
    if post_state["state"] != "correct_b4_second_light_b2_ray":
        raise SyncError(f"mapping correction did not produce the expected state: {post_state}")

    previous = before.get("preserved_records", {})
    current = current_content_records(root)
    lost = sorted(set(previous) - set(current))
    changed: list[dict[str, Any]] = []
    for logical_id, row in previous.items():
        if logical_id in current and row.get("content") != current[logical_id].get("content"):
            changed.append({
                "logical_id": logical_id,
                "before": row.get("content"),
                "after": current[logical_id].get("content"),
            })
    if lost:
        raise SyncError(f"preserved logical IDs lost: {len(lost)}")
    if changed:
        raise SyncError(f"preserved authored content changed: {len(changed)}")

    old_extension_ids = set()
    for item in before.get("generated_wrong_scope", {}).get("wrong_second_light_quartet_extensions", []):
        if isinstance(item.get("logical_id"), str):
            old_extension_ids.add(item["logical_id"])
    # The list above contains authored records only and is expected to be empty. Verify
    # removal structurally instead through branch state and source roles.

    export_path = root / ".local/reports/BR_TRANSLATION_EXPORT_REPORT.json"
    export_report = json.loads(export_path.read_text(encoding="utf-8"))
    failures = export_report.get("ebm_validation", {}).get("failures", [])
    if failures:
        raise SyncError(f"EBM validation failures: {len(failures)}")
    selected = set(export_report.get("selected_projects", []))
    if selected != {"second_light", "blue_reflection_ray"}:
        raise SyncError(f"unexpected selected export projects: {sorted(selected)}")

    stats = {project: unit_stats(root, project) for project in ALL_PROJECTS}
    second_light = stats["second_light"]
    ray = stats["blue_reflection_ray"]
    old_second_light_units = int(before.get("mapping_state", {}).get("second_light_target_units", 0))
    old_wrong_ray_units = int(before.get("mapping_state", {}).get("ray_target_units", 0))
    minimum_second_light_units = max(1, (old_second_light_units * 3) // 4)
    if second_light.get("units", 0) < minimum_second_light_units:
        raise SyncError(
            f"Second Light corrected export is implausibly small: "
            f"{second_light.get('units', 0)} < {minimum_second_light_units}"
        )
    canonical_records = second_light.get("canonical_records", 0)
    auxiliary = second_light.get("nonnull_en_auxiliary", 0)
    if canonical_records <= 0 or auxiliary < max(1, canonical_records // 2):
        raise SyncError(
            f"Second Light b4 auxiliary coverage is implausibly low: {auxiliary}/{canonical_records}"
        )
    event_records = second_light.get("event_records", 0)
    event_auxiliary = second_light.get("event_nonnull_en_auxiliary", 0)
    if event_records > 0 and event_auxiliary < max(1, event_records // 2):
        raise SyncError(
            f"Second Light event dialogue auxiliary coverage is implausibly low: "
            f"{event_auxiliary}/{event_records}"
        )
    ray_units = ray.get("units", 0)
    if ray_units <= 0:
        raise SyncError("RAY b2 export is empty")
    if old_wrong_ray_units > 1 and ray_units >= max(2, (old_wrong_ray_units * 3) // 4):
        raise SyncError(
            f"RAY b2 export still resembles the larger wrong b4 database: "
            f"{ray_units} vs prior {old_wrong_ray_units}"
        )
    if ray_units >= second_light.get("units", 0):
        raise SyncError("RAY export still resembles the larger Second Light b4 database")
    if post_state["second_light"].get("b2", 0) or post_state["ray"].get("b4", 0):
        raise SyncError("wrong b2/b4 target references remain after correction")

    version_path = root / "workstreams/translation/VERSION"
    old_version = version_path.read_text(encoding="utf-8").strip()
    if old_version != before.get("translation_version"):
        raise SyncError(
            f"Translation version changed during migration: {before.get('translation_version')} -> {old_version}"
        )
    major, minor, patch = parse_version(old_version)
    new_version = f"{major}.{minor}.{patch + 1}"
    version_path.write_text(new_version + "\n", encoding="utf-8")

    now = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    status_path = root / "workstreams/translation/STATUS.json"
    status = json.loads(status_path.read_text(encoding="utf-8"))
    status["version"] = new_version
    status["canonical_databases"] = [f"titles/{project}/translation/" for project in ALL_PROJECTS]
    status["quartet_policy"] = (
        "Quartet b1 reuses canonical Blue Reflection records; RAY is Quartet b2; "
        "SUN is Quartet b3; Second Light uses its standalone JP/EN as canonical content "
        "and Quartet b4 as en_auxiliary and target data."
    )
    status["next_update"] = {
        "from_version": new_version,
        "to_version": f"{major}.{minor}.{patch + 2}",
        "workstream_id": "translation",
    }
    atomic_json(status_path, status)

    changelog_path = root / "workstreams/translation/CONTENT_CHANGELOG.json"
    previous_changelog_raw = changelog_path.read_bytes() if changelog_path.is_file() else b""
    previous_changelog = None
    if previous_changelog_raw:
        try:
            previous_changelog = json.loads(previous_changelog_raw.decode("utf-8"))
        except Exception:
            previous_changelog = None
    changelog = {
        "type": "br_translation_quartet_partition_correction",
        "format_version": 1,
        "workstream_id": "translation",
        "from_version": old_version,
        "to_version": new_version,
        "status": "ready",
        "generated_utc": now,
        "correction": {
            "second_light": "rebound from incorrect Quartet b2 to correct Quartet b4",
            "blue_reflection_ray": "rebuilt from correct Quartet b2 instead of incorrect b4",
            "blue_reflection_sun": "unchanged on Quartet b3",
            "blue_reflection": "unchanged on Quartet b1",
        },
        "results": stats,
        "removed_wrong_generated_scope": before.get("generated_wrong_scope", {}).get("counts", {}),
        "guarantees": {
            "preserved_logical_ids_lost": 0,
            "preserved_en_notes_status_changed": 0,
            "game_files_modified": False,
        },
        "previous_content_changelog_sha256": sha256_bytes(previous_changelog_raw),
        "previous_content_changelog": previous_changelog,
    }
    atomic_json(changelog_path, changelog)

    history = root / "workstreams/translation/docs/RELEASE_HISTORY.md"
    with history.open("a", encoding="utf-8") as handle:
        handle.write(
            f"\n| {new_version} | Correct Quartet partition mapping: Second Light b4 auxiliary/target and RAY b2 canonical export | "
            f"0 preserved content changes | Second Light auxiliary {auxiliary}; RAY units {ray.get('units', 0)} |\n"
        )

    report = {
        "type": "br_quartet_translation_partition_correction",
        "format_version": 2,
        "status": "ok",
        "generated_utc": now,
        "from_translation_version": old_version,
        "to_translation_version": new_version,
        "pre_mapping_state": before.get("mapping_state"),
        "post_mapping_state": post_state,
        "preserved_logical_ids_lost": 0,
        "preserved_content_values_changed": 0,
        "removed_wrong_generated_scope": before.get("generated_wrong_scope", {}).get("counts", {}),
        "projects": stats,
        "export_report": ".local/reports/BR_TRANSLATION_EXPORT_REPORT.json",
    }
    report_path = root / ".local/reports/translation/BR_QUARTET_TRANSLATION_PARTITION_CORRECTION.json"
    atomic_json(report_path, report)

    output_dir.mkdir(parents=True, exist_ok=True)
    addendum = output_dir / f"Blue_Reflection_translation_chat_QUARTET_PARTITION_CORRECTION_ADDENDUM_{new_version}.md"
    addendum.write_text(
        f"""# Blue Reflection — korekta źródeł Quartet

Aktualny stan treści po korekcie: **translation {new_version}**.

Poprzednia migracja błędnie zamieniła sekcje RAY i Second Light. Zostało to poprawione na aktualnej bazie `{old_version}` bez cofania pracy tłumaczeniowej.

## Prawidłowy podział Quartet

```text
b1 → BLUE REFLECTION
b2 → BLUE REFLECTION RAY
b3 → BLUE REFLECTION SUN
b4 → BLUE REFLECTION: Second Light
```

## Gwarancje migracji

```text
utracone dotychczasowe logical_id: 0
zmienione dotychczasowe en/notes/status: 0
```

Second Light zachowuje wszystkie poprawki wykonane do wersji `{old_version}`. `en_auxiliary` i target Quartet pochodzą teraz z właściwego `b4`. Błędne rozszerzenia pochodzące z RAY/b2 zostały usunięte, a prawidłowe rozszerzenia b4 wygenerowane ponownie.

Baza RAY została w całości odtworzona z właściwego `b2`. Poprzedniej bazy RAY z bundle 0.0.108–0.0.111 nie wolno używać, ponieważ zawierała Second Light/b4. SUN pozostaje bez zmian na `b3`.

## Wyniki

```text
Second Light: {second_light.get('units', 0)} units / {second_light.get('records', 0)} records
Second Light populated en_auxiliary: {auxiliary}
Second Light event en_auxiliary: {second_light.get('event_nonnull_en_auxiliary', 0)}
RAY: {ray.get('units', 0)} units / {ray.get('records', 0)} records
SUN: {stats['blue_reflection_sun'].get('units', 0)} units / {stats['blue_reflection_sun'].get('records', 0)} records
```

Kontynuuj bieżący zakres Second Light od wersji `{new_version}`. RAY należy rozpoczynać wyłącznie z nowej bazy zawartej w tym bundle.
""",
        encoding="utf-8",
    )
    result = {
        "report": str(report_path),
        "addendum": str(addendum),
        "version": new_version,
        "stats": stats,
    }
    atomic_json(output_dir / "QUARTET_PARTITION_CORRECTION_RESULT.json", result)
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    command = sub.add_parser("snapshot")
    command.add_argument("--project-root", required=True)
    command.add_argument("--output", required=True)
    command = sub.add_parser("finalize")
    command.add_argument("--project-root", required=True)
    command.add_argument("--before", required=True)
    command.add_argument("--output-dir", required=True)
    args = parser.parse_args()
    root = Path(args.project_root).resolve()
    try:
        if args.command == "snapshot":
            result = snapshot(root, Path(args.output).resolve())
            print(json.dumps({
                "status": "ready_for_correction",
                "translation_version": result["translation_version"],
                "mapping_state": result["mapping_state"],
                "generated_wrong_scope": result["generated_wrong_scope"]["counts"],
            }, ensure_ascii=False, indent=2))
            return 0
        result = finalize(root, Path(args.before).resolve(), Path(args.output_dir).resolve())
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except SyncError as exc:
        print(f"ERROR: {exc}", file=__import__("sys").stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
