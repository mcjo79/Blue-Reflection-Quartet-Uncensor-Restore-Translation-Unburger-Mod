#!/usr/bin/env python3
"""BLUE REFLECTION (2017) French translation patch tool.

Two jobs:

``import-release``
    Read a French fan release (the extracted ``DATA/PACK01.pak`` and
    ``DATA/PACK02_1.pak`` of the ``Blue Reflection French Translation`` package)
    and write a compact, versioned French translation dataset under
    ``titles/blue_reflection/translation_fr``.  Only the French *text* is kept:
    the release's Japanese members were verified byte-identical to this
    project's canonical baseline, so nothing else has to be redistributed.

``apply``
    Patch a user's own BLUE REFLECTION (2017) PC installation.  The tool
    extracts the affected archives from the user's own files, rewrites only the
    text members that carry French content, repacks, verifies the result
    member-by-member and commits with a backup that ``revert`` can restore.

Only the Python standard library is used.  Archive extract/repack is performed
by ``gust_pak`` from gust_tools, exactly like the rest of this repository.

Usage
-----
``python br_french_patch.py import-release --release-dir DIR``
``python br_french_patch.py apply --game-dir DIR``
``python br_french_patch.py status --game-dir DIR``
``python br_french_patch.py revert --game-dir DIR``
``python br_french_patch.py self-check``

See ``--help`` on each subcommand for the complete option list.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Optional

TOOL_DIR = Path(__file__).resolve().parent
if str(TOOL_DIR) not in sys.path:
    sys.path.insert(0, str(TOOL_DIR))

import br_french_cleanup as cleanup  # noqa: E402
import br_french_names as names  # noqa: E402
import br_text_envelope as envelope  # noqa: E402
import br_text_tool as bt  # noqa: E402
import br_translation_categories as categories  # noqa: E402
import br_translation_xml as tx  # noqa: E402

FR_PATCH_TOOL_VERSION = "fr-patch-0.1.0"
FR_DATASET_FORMAT_VERSION = 1

TARGET_ID = "blue_reflection_original"
RELEASE_ARCHIVES = {
    "PACK01": "DATA/PACK01.PAK",
    "PACK02_1": "DATA/PACK02_1.PAK",
}
GAME_ARCHIVES = {
    "PACK01": "DATA/PACK01.PAK",
    "PACK02_1": "DATA/PACK02_1.PAK",
}
GAME_MARKER_ARCHIVE = "DATA/PACK00_04_1.PAK"

# The four re-encoded movies shipped by the French release, mapped from their
# basename to their game-relative location.
MOVIES = {
    "ending_EN.wmv": "DATA/x64/Movie/ending_EN.wmv",
    "EVT_MOB14A_00_EN.wmv": "DATA/x64/Movie/EVT_MOB14A_00_EN.wmv",
    "RFC_MOB14A_00_EN.wmv": "DATA/x64/Movie/RFC_MOB14A_00_EN.wmv",
    "RFC_MOB14A_10_EN.wmv": "DATA/x64/Movie/RFC_MOB14A_10_EN.wmv",
}

EVENT_MEMBER_ROOT = "event/event_en"
SYSTEM_MEMBER = "saves_en/text/strcombineall.xml"
SYSTEM_ENVELOPE_MEMBER = "saves_en/text/strcombineall.xml.e"

STATE_DIR_NAME = ".br_french_patch"
STATE_FILE_NAME = "state.json"

RELEASE_EVENT_ROOT = "event/event_en"
RELEASE_SYSTEM_MEMBER = "saves_en/text/strcombineall.xml"
RELEASE_SYSTEM_ENVELOPE = "saves_en/text/strcombineall.xml.e"


class FrenchPatchError(RuntimeError):
    """Raised on any unrecoverable patch problem."""


# --------------------------------------------------------------------------- #
# Small filesystem and process helpers
# --------------------------------------------------------------------------- #


def sha256_file(path: Path) -> str:
    return bt.sha256_file(path)


def sha256_bytes(data: bytes) -> str:
    import hashlib

    return hashlib.sha256(data).hexdigest()


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def atomic_write_bytes(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
        os.replace(tmp_name, path)
    except BaseException:
        try:
            os.unlink(tmp_name)
        except FileNotFoundError:
            pass
        raise


def atomic_replace_file(source: Path, destination: Path) -> None:
    """Replace ``destination`` with ``source`` as atomically as the OS allows."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    os.replace(source, destination)


def resolve_path_ci(root: Path, relative: str) -> Optional[Path]:
    """Resolve ``relative`` under ``root`` using case-insensitive matching."""
    current = root
    for part in Path(relative).parts:
        if not current.is_dir():
            return None
        match = None
        for candidate in current.iterdir():
            if candidate.name.lower() == part.lower():
                match = candidate
                break
        if match is None:
            return None
        current = match
    return current


def require_path_ci(root: Path, relative: str, description: str) -> Path:
    found = resolve_path_ci(root, relative)
    if found is None:
        raise FrenchPatchError(
            f"{description} not found: {root / relative}\n"
            f"The selected directory does not look like a supported "
            f"BLUE REFLECTION (2017) installation."
        )
    return found


def human_bytes(value: int) -> str:
    units = ["B", "KiB", "MiB", "GiB"]
    size = float(value)
    for unit in units:
        if size < 1024 or unit == units[-1]:
            return f"{size:.1f} {unit}" if unit != "B" else f"{int(size)} B"
        size /= 1024
    return f"{value} B"


# --------------------------------------------------------------------------- #
# gust_pak plumbing (same tool and calls the repository uses)
# --------------------------------------------------------------------------- #


def find_gust_pak(explicit: Optional[str]) -> Path:
    candidates: list[Path] = []
    if explicit:
        candidates.append(Path(explicit).expanduser())
    env = os.environ.get("GUST_PAK")
    if env:
        candidates.append(Path(env).expanduser())

    bundle_root = TOOL_DIR
    project_root = TOOL_DIR.parent
    names = ["gust_pak.exe", "gust_pak"]
    for name in names:
        candidates.append(bundle_root / name)
        candidates.append(bundle_root / "vendor" / name)
    for name in names:
        candidates.append(project_root / ".local" / "vendor" / "gust_tools" / name)
        candidates.append(project_root / "vendor" / name)

    for name in names:
        found = shutil.which(name)
        if found:
            candidates.append(Path(found))

    for candidate in candidates:
        if candidate.is_file():
            return candidate.resolve()
    raise FrenchPatchError(
        "gust_pak was not found.\n"
        "Pass --gust-pak PATH, set the GUST_PAK environment variable, place "
        "gust_pak.exe next to this tool, or install gust_tools from\n"
        "  https://github.com/VitaSmith/gust_tools/releases\n"
        "The repository also accepts .local/vendor/gust_tools/gust_pak[.exe]."
    )


def run_gust_pak(
    gust_pak: Path,
    arguments: list[str],
    cwd: Path,
    timeout: int,
    description: str,
) -> subprocess.CompletedProcess[str]:
    try:
        process = subprocess.run(
            [str(gust_pak), *arguments],
            cwd=cwd,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        raise FrenchPatchError(f"gust_pak timed out for {description}") from exc
    if process.returncode != 0:
        tail = (process.stderr or process.stdout or "").strip().splitlines()[-6:]
        raise FrenchPatchError(
            f"gust_pak failed for {description} (exit {process.returncode}):\n"
            + "\n".join(tail)
        )
    return process


def list_members(gust_pak: Path, pak_path: Path, cwd: Path, timeout: int) -> list[str]:
    entries, _ = bt.list_pak_entries(gust_pak, pak_path, cwd, timeout)
    return entries


def extract_archive(
    gust_pak: Path,
    pak_path: Path,
    destination: Path,
    timeout: int,
) -> tuple[Path, list[str]]:
    """Extract ``pak_path`` into ``destination`` and return its manifest."""
    if destination.exists():
        shutil.rmtree(destination)
    destination.mkdir(parents=True)

    local_copy = destination / pak_path.name
    try:
        os.link(pak_path, local_copy)
    except OSError:
        shutil.copy2(pak_path, local_copy)

    manifest = destination / f"{pak_path.stem}.json"
    try:
        run_gust_pak(
            gust_pak,
            [local_copy.name],
            destination,
            timeout,
            f"extract {pak_path.name}",
        )
    finally:
        try:
            local_copy.unlink()
        except FileNotFoundError:
            pass

    if not manifest.is_file():
        raise FrenchPatchError(
            f"gust_pak did not create the expected manifest for {pak_path.name}: "
            f"{manifest}"
        )
    return manifest, [member for member in destination.rglob("*") if member.is_file()]


def repack_archive(
    gust_pak: Path,
    manifest: Path,
    directory: Path,
    timeout: int,
) -> Path:
    before = {
        path.relative_to(directory)
        for path in directory.rglob("*")
        if path.is_file() and path.suffix.lower() == ".pak"
    }
    run_gust_pak(
        gust_pak,
        [manifest.name],
        directory,
        timeout,
        f"repack {manifest.name}",
    )
    after = {
        path.relative_to(directory)
        for path in directory.rglob("*")
        if path.is_file() and path.suffix.lower() == ".pak"
    }
    created = sorted(after - before)
    if len(created) != 1:
        rendered = ", ".join(path.as_posix() for path in created) or "(none)"
        raise FrenchPatchError(
            f"Expected exactly one PAK from gust_pak for {manifest.name}, "
            f"found {len(created)}: {rendered}"
        )
    return directory / created[0]


def tree_hashes(root: Path) -> dict[str, str]:
    result: dict[str, str] = {}
    for path in root.rglob("*"):
        if path.is_file() and path.suffix.lower() != ".json":
            result[path.relative_to(root).as_posix()] = sha256_file(path)
    return result


# --------------------------------------------------------------------------- #
# Dataset layout
# --------------------------------------------------------------------------- #


def default_dataset_dir() -> Path:
    candidates = [
        TOOL_DIR.parent / "titles" / "blue_reflection" / "translation_fr",
        TOOL_DIR / "dataset",
    ]
    for candidate in candidates:
        if (candidate / "manifest.json").is_file():
            return candidate
    return candidates[0]


def default_baseline_db_dir() -> Optional[Path]:
    candidate = TOOL_DIR.parent / "titles" / "blue_reflection" / "translation"
    return candidate if candidate.is_dir() else None


def dataset_paths(root: Path) -> dict[str, Path]:
    return {
        "manifest": root / "manifest.json",
        "names": root / "names.xml",
        "places": root / "places.xml",
        "items": root / "items.xml",
        "messages": root / "messages.xml",
        "other": root / "other.xml",
        "dialogue": root / "dialogue.xml",
        "system_envelope": root / "system" / "strcombineall.xml.e",
    }


def load_dataset(root: Path) -> dict[str, Any]:
    paths = dataset_paths(root)
    if not paths["manifest"].is_file():
        raise FrenchPatchError(
            f"French translation dataset not found: {paths['manifest']}\n"
            f"Build it first with: python {Path(__file__).name} import-release "
            f"--release-dir <folder containing DATA/PACK01.pak>"
        )
    manifest = json.loads(paths["manifest"].read_text(encoding="utf-8"))
    if manifest.get("type") != "br_french_translation_dataset":
        raise FrenchPatchError(f"Unexpected dataset type: {paths['manifest']}")
    if manifest.get("format_version") != FR_DATASET_FORMAT_VERSION:
        raise FrenchPatchError(
            f"Unsupported dataset format version: {manifest.get('format_version')}"
        )

    strings: dict[str, str] = {}
    for section in categories.STRING_CATEGORIES:
        for parsed in tx.read_numbered(root, section):
            strings.update(parsed.get(section) or {})

    units: dict[str, dict[str, Any]] = {}
    for parsed in tx.read_numbered(root, "dialogue"):
        for chapter in parsed.get("dialogue") or []:
            for event in chapter["events"]:
                records = [
                    [index, msg.get("msg_id"), msg.get("name_id"), msg["text"]]
                    for index, msg in enumerate(event["messages"])
                ]
                units[event["file"]] = {
                    "path": event["file"],
                    "message_count": len(records),
                    "records": records,
                }

    system = {
        "member": SYSTEM_MEMBER,
        "envelope_member": SYSTEM_ENVELOPE_MEMBER,
        "encoding": None,
        "strings": strings,
    }

    return {
        "root": root,
        "manifest": manifest,
        "units": units,
        "system": system,
        "system_envelope": (
            paths["system_envelope"].read_bytes()
            if paths["system_envelope"].is_file()
            else None
        ),
    }


# --------------------------------------------------------------------------- #
# import-release
# --------------------------------------------------------------------------- #


def find_release_archive(release_data_dir: Path, stem: str) -> Path:
    for name in (f"{stem}.pak", f"{stem}.PAK"):
        candidate = release_data_dir / name
        if candidate.is_file():
            return candidate
    raise FrenchPatchError(
        f"{stem} archive not found in {release_data_dir} "
        f"(expected {stem}.pak). Point --release-dir at the folder that "
        f"contains DATA/PACK01.pak."
    )


def import_events(
    pack01_root: Path,
    baseline_db: Optional[Path],
    cleanup_stats: Optional[dict[str, Any]] = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    event_root = pack01_root / RELEASE_EVENT_ROOT
    if not event_root.is_dir():
        raise FrenchPatchError(f"No event folder in the extracted archive: {event_root}")

    baseline: dict[str, dict[str, Any]] = {}
    if baseline_db is not None:
        for path in (baseline_db / "events").rglob("*.ebm.json"):
            baseline[path.relative_to(baseline_db / "events").as_posix()[: -len(".json")]] = path

    units: list[dict[str, Any]] = []
    stats = {
        "units": 0,
        "records": 0,
        "records_changed_from_official_english": 0,
        "records_identical_to_official_english": 0,
        "units_with_baseline": 0,
        "units_with_structural_difference": 0,
        "units_baseline_metadata_mismatch": 0,
        "structural_differences": [],
    }

    for ebm_path in sorted(event_root.rglob("*.ebm")):
        logical = ebm_path.relative_to(event_root).as_posix()
        ebm = bt.parse_ebm(ebm_path)
        records = []
        for message in ebm.messages:
            text = message.text
            text, applied = cleanup.apply_cleanup(text)
            text, accent_replaced = cleanup.apply_accent_fallback(text)
            if cleanup_stats is not None:
                if applied:
                    cleanup_stats["records_changed"] += 1
                if accent_replaced:
                    cleanup_stats["accent_chars_replaced"] += accent_replaced
                for reason in applied:
                    cleanup_stats["rules"][reason] += 1
                for forbidden in cleanup.validate_cleanup(text):
                    cleanup_stats["forbidden_remaining"].append((logical, forbidden))
            records.append([message.index, message.msg_id, message.name_id, text])
        unit: dict[str, Any] = {
            "path": logical,
            "message_count": len(records),
            "records": records,
        }
        stats["units"] += 1
        stats["records"] += len(records)

        baseline_path = baseline.get(logical)
        if baseline_path is not None:
            reference = json.loads(baseline_path.read_text(encoding="utf-8"))
            stats["units_with_baseline"] += 1
            reference_records = reference["records"]
            if len(reference_records) != len(records):
                stats["units_with_structural_difference"] += 1
                if len(stats["structural_differences"]) < 32:
                    stats["structural_differences"].append(
                        {
                            "unit": logical,
                            "dataset_messages": len(records),
                            "baseline_messages": len(reference_records),
                        }
                    )
                unit["baseline_message_count"] = len(reference_records)
            else:
                mismatched = 0
                for message, reference_record in zip(ebm.messages, reference_records):
                    if (
                        message.msg_id != reference_record.get("msg_id")
                        or message.name_id != reference_record["metadata"].get("name_id")
                    ):
                        mismatched += 1
                    official = reference_record.get("en_original")
                    if official is None:
                        continue
                    if bt.text_sha256(message.text) == bt.text_sha256(official):
                        stats["records_identical_to_official_english"] += 1
                    else:
                        stats["records_changed_from_official_english"] += 1
                if mismatched:
                    stats["units_baseline_metadata_mismatch"] += 1
                    unit["baseline_metadata_mismatch"] = mismatched
        units.append(unit)

    return units, stats


def import_system(
    pack02_root: Path,
    cleanup_stats: Optional[dict[str, Any]] = None,
) -> tuple[dict[str, Any], bytes, dict[str, Any]]:
    member = pack02_root / RELEASE_SYSTEM_MEMBER
    if not member.is_file():
        raise FrenchPatchError(
            f"strcombineall.xml not found in the extracted archive: {member}"
        )
    table = bt.parse_xml_table(member)
    strings: dict[str, str] = {}
    duplicates: list[str] = []
    without_key = 0
    for row in table.rows:
        key = row.string_no or row.string_id
        if key is None:
            without_key += 1
            continue
        text, applied = cleanup.apply_cleanup(row.text)
        text, accent_replaced = cleanup.apply_accent_fallback(text)
        override = names.override_for(key)
        if override is not None:
            text = override
        if cleanup_stats is not None:
            if applied:
                cleanup_stats["system_changed"] += 1
            if accent_replaced:
                cleanup_stats["accent_chars_replaced"] += accent_replaced
            for reason in applied:
                cleanup_stats["rules"][reason] += 1
            for forbidden in cleanup.validate_cleanup(text):
                cleanup_stats["forbidden_remaining"].append((f"system:{key}", forbidden))
        if key in strings and strings[key] != text:
            duplicates.append(key)
        strings[key] = text

    envelope_path = pack02_root / RELEASE_SYSTEM_ENVELOPE
    envelope_bytes = b""
    envelope_sha = None
    if envelope_path.is_file():
        envelope_bytes = envelope_path.read_bytes()
        envelope_sha = sha256_bytes(envelope_bytes)

    system = {
        "member": SYSTEM_MEMBER,
        "envelope_member": SYSTEM_ENVELOPE_MEMBER,
        "encoding": table.encoding,
        "source_envelope_sha256": envelope_sha,
        "source_envelope_bytes": len(envelope_bytes),
        "strings": strings,
    }
    stats = {
        "rows": len(table.rows),
        "strings": len(strings),
        "rows_without_key": without_key,
        "conflicting_duplicate_keys": len(duplicates),
        "envelope_present": bool(envelope_bytes),
    }
    return system, envelope_bytes, stats


def cmd_import_release(args: argparse.Namespace) -> int:
    release_dir = Path(args.release_dir).expanduser().resolve()
    if not release_dir.is_dir():
        raise FrenchPatchError(f"--release-dir is not a directory: {release_dir}")

    data_dir = release_dir / "DATA"
    if not data_dir.is_dir():
        data_dir = release_dir
    pack01 = find_release_archive(data_dir, "PACK01")
    pack02 = find_release_archive(data_dir, "PACK02_1")

    gust_pak = find_gust_pak(args.gust_pak)
    work_root = (
        Path(args.work_dir).expanduser().resolve()
        if args.work_dir
        else TOOL_DIR.parent / ".local" / "fr" / "import"
    )
    work_root.mkdir(parents=True, exist_ok=True)

    print(f"gust_pak    : {gust_pak}")
    print(f"release     : {release_dir}")
    print(f"workspace   : {work_root}")

    if args.reuse_extract and (work_root / "PACK01").is_dir():
        print("reusing existing extraction of PACK01")
        pack01_manifest = work_root / "PACK01" / "PACK01.json"
    else:
        print(f"extracting  : {pack01.name}")
        pack01_manifest, _ = extract_archive(gust_pak, pack01, work_root / "PACK01", args.timeout)

    if args.reuse_extract and (work_root / "PACK02_1").is_dir():
        print("reusing existing extraction of PACK02_1")
    else:
        print(f"extracting  : {pack02.name}")
        extract_archive(gust_pak, pack02, work_root / "PACK02_1", args.timeout)

    baseline_db = (
        Path(args.baseline_db).expanduser().resolve()
        if args.baseline_db
        else default_baseline_db_dir()
    )
    if baseline_db is not None and not baseline_db.is_dir():
        baseline_db = None
    if baseline_db is not None:
        print(f"baseline db : {baseline_db}")
    else:
        print("baseline db : (not available; alignment verification limited)")

    print("reading French events ...")
    cleanup_stats: dict[str, Any] = {
        "rules": Counter(),
        "records_changed": 0,
        "system_changed": 0,
        "accent_chars_replaced": 0,
        "forbidden_remaining": [],
    }
    units, event_stats = import_events(work_root / "PACK01", baseline_db, cleanup_stats)
    print("reading French system text ...")
    system, envelope_bytes, system_stats = import_system(work_root / "PACK02_1", cleanup_stats)

    out_root = (
        Path(args.out).expanduser().resolve()
        if args.out
        else default_dataset_dir()
    )
    out_root.mkdir(parents=True, exist_ok=True)
    (out_root / "system").mkdir(parents=True, exist_ok=True)

    string_categories = categories.categorize_strings(
        system["strings"],
        baseline_db if baseline_db is not None else default_baseline_db_dir(),
    )
    dialogue = categories.group_events_by_chapter(
        [
            {
                "file": unit["path"],
                "messages": [
                    {"msg_id": record[1], "name_id": record[2], "text": record[3]}
                    for record in unit["records"]
                ],
            }
            for unit in units
        ]
    )

    meta = {"release": release_dir.name, "generated_utc": utc_now()}
    for section in categories.STRING_CATEGORIES:
        tx.write_translation(
            {
                "game": "blue_reflection",
                "lang": "fr",
                "meta": meta,
                section: string_categories[section],
            },
            out_root / categories.CATEGORY_FILES[section],
        )
    tx.write_translation(
        {
            "game": "blue_reflection",
            "lang": "fr",
            "meta": meta,
            "dialogue": dialogue,
        },
        out_root / categories.CATEGORY_FILES["dialogue"],
    )
    if envelope_bytes:
        atomic_write_bytes(out_root / "system" / "strcombineall.xml.e", envelope_bytes)

    manifest = {
        "type": "br_french_translation_dataset",
        "format_version": FR_DATASET_FORMAT_VERSION,
        "tool_version": FR_PATCH_TOOL_VERSION,
        "generated_utc": utc_now(),
        "target": TARGET_ID,
        "language": "fr",
        "source": {
            "release_directory": release_dir.name,
            "pack01_name": pack01.name,
            "pack01_bytes": pack01.stat().st_size,
            "pack01_sha256": sha256_file(pack01),
            "pack02_1_name": pack02.name,
            "pack02_1_bytes": pack02.stat().st_size,
            "pack02_1_sha256": sha256_file(pack02),
            "gust_pak_sha256": sha256_file(gust_pak),
        },
        "content": {
            "event_member_root": EVENT_MEMBER_ROOT,
            "system_member": SYSTEM_MEMBER,
            "system_envelope_member": SYSTEM_ENVELOPE_MEMBER,
        },
        "counts": {"events": event_stats, "system": system_stats},
        "cleanup": {
            "description": (
                "Normalise la terminologie '原種' (Sephira singulier / Sephirot "
                "pluriel, masculin) et corrige trois fautes ; voir "
                "Blue_Reflection_Text_Tool/br_french_cleanup.py."
            ),
            "rules": cleanup.describe(),
            "records_changed": cleanup_stats["records_changed"],
            "system_strings_changed": cleanup_stats["system_changed"],
            "rules_applied": dict(cleanup_stats["rules"]),
            "accent_chars_replaced": cleanup_stats["accent_chars_replaced"],
            "accent_fallback_map": cleanup.ACCENT_FALLBACK_MAP,
            "forbidden_remaining": cleanup_stats["forbidden_remaining"],
        },
        "field_notes": {
            "names.xml": (
                "Character / creature names (chara, monster, event_chara, race)."
            ),
            "places.xml": (
                "Location names (school map, field map area, library map)."
            ),
            "items.xml": (
                "Object / crafting names (items, treasure, fragments, costumes)."
            ),
            "messages.xml": (
                "Spoken dialogue tables (NPC messages, chat, conversation topics)."
            ),
            "dialogue.xml": (
                "Event dialogue, grouped by <chapter> (one per event folder)."
            ),
            "other.xml": (
                "Every remaining string (UI, battle, tutorial, NPC messages, "
                "missions, ...)."
            ),
            "system/strcombineall.xml.e": (
                "Original French release envelope, kept for provenance. The "
                "patch regenerates the envelope from the merged plain XML so "
                "that rows added by the user's own game version survive."
            ),
        },
    }
    atomic_write_bytes(
        out_root / "manifest.json",
        json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=1).encode("utf-8"),
    )

    print()
    print(f"dataset written to {out_root}")
    print(
        f"  events : {event_stats['units']} scripts, "
        f"{event_stats['records']} records "
        f"({event_stats['records_changed_from_official_english']} differ from "
        f"the official English)"
    )
    print(
        f"  system : {system_stats['strings']} strings "
        f"({system_stats['rows']} rows, envelope "
        f"{'kept' if system_stats['envelope_present'] else 'absent'})"
    )
    print(
        f"  cleanup: {cleanup_stats['records_changed']} event records + "
        f"{cleanup_stats['system_changed']} system strings corrected"
    )
    print(
        f"  accent fallback: {cleanup_stats['accent_chars_replaced']} unsupported "
        f"accented characters mapped to ASCII (font compatibility)"
    )
    if cleanup_stats["forbidden_remaining"]:
        print(
            f"  WARNING: {len(cleanup_stats['forbidden_remaining'])} forbidden "
            f"patterns remain after cleanup; review them"
        )
        for location, forbidden in cleanup_stats["forbidden_remaining"][:10]:
            print(f"    - {location}: {forbidden}")
    if event_stats["units_with_structural_difference"]:
        print(
            f"  warning: {event_stats['units_with_structural_difference']} scripts "
            f"have a different message count than the official script; they are "
            f"reported and left untouched by default"
        )
    return 0


# --------------------------------------------------------------------------- #
# apply
# --------------------------------------------------------------------------- #


def state_paths(game_dir: Path) -> dict[str, Path]:
    root = game_dir / STATE_DIR_NAME
    return {
        "root": root,
        "state": root / STATE_FILE_NAME,
        "backup": root / "backup",
        "work": root / "work",
    }


def load_state(game_dir: Path) -> Optional[dict[str, Any]]:
    state_file = state_paths(game_dir)["state"]
    if not state_file.is_file():
        return None
    return json.loads(state_file.read_text(encoding="utf-8"))


def detect_install(game_dir: Path) -> dict[str, Path]:
    found: dict[str, Path] = {}
    for stem, relative in GAME_ARCHIVES.items():
        found[stem] = require_path_ci(
            game_dir, relative, f"{stem} archive ({relative})"
        )
    marker = resolve_path_ci(game_dir, GAME_MARKER_ARCHIVE)
    if marker is not None:
        found["marker"] = marker
    return found


def patch_event_unit(
    template_path: Path,
    unit: dict[str, Any],
    allow_structural_mismatch: bool,
) -> tuple[Optional[bytes], dict[str, Any]]:
    """Return the patched EBM bytes for one unit (or ``None`` when skipped)."""
    logical = unit["path"]
    dataset_records = unit["records"]
    if not template_path.is_file():
        return None, {
            "unit": logical,
            "status": "template_missing",
            "applied": 0,
            "skipped": len(dataset_records),
        }

    template = bt.parse_ebm(template_path)
    if len(template.messages) != len(dataset_records):
        if not allow_structural_mismatch:
            return None, {
                "unit": logical,
                "status": "structural_mismatch",
                "template_messages": len(template.messages),
                "dataset_messages": len(dataset_records),
                "applied": 0,
                "skipped": len(dataset_records),
            }

    texts: list[str] = [message.text for message in template.messages]
    applied = 0
    skipped = 0
    mismatched_slots: list[int] = []
    for index, msg_id, name_id, text in dataset_records:
        if index < 0 or index >= len(template.messages):
            skipped += 1
            continue
        message = template.messages[index]
        if message.msg_id != msg_id or message.name_id != name_id:
            skipped += 1
            if len(mismatched_slots) < 8:
                mismatched_slots.append(index)
            continue
        texts[index] = text
        applied += 1

    status = "applied"
    if len(template.messages) != len(dataset_records):
        status = "applied_structural_mismatch"
    elif skipped:
        status = "applied_with_slot_mismatches"
    report = {
        "unit": logical,
        "status": status,
        "applied": applied,
        "skipped": skipped,
    }
    if mismatched_slots:
        report["mismatched_slots"] = mismatched_slots
    if applied == 0 and skipped == 0:
        return None, {"unit": logical, "status": "empty", "applied": 0, "skipped": 0}
    return bt.serialize_ebm(template, [str(value) for value in texts]), report


def patch_system_member(template_path: Path, system: dict[str, Any]) -> tuple[bytes, bytes, dict[str, Any]]:
    table = bt.parse_xml_table(template_path)
    index_by_key: dict[str, int] = {}
    for row in table.rows:
        key = row.string_no or row.string_id
        if key is None:
            continue
        index_by_key.setdefault(key, row.index)

    replacements: dict[int, str] = {}
    applied = 0
    missing_in_target: list[str] = []
    for key, text in system["strings"].items():
        index = index_by_key.get(key)
        if index is None:
            if len(missing_in_target) < 64:
                missing_in_target.append(key)
            continue
        if table.rows[index].text == text:
            continue
        replacements[index] = text
        applied += 1

    patched = bt.serialize_xml_table(table, replacements)
    encoded = envelope.encode_br_text_envelope(patched)
    if envelope.decode_br_text_envelope(encoded) != patched:
        raise FrenchPatchError(
            "text envelope round-trip self-check failed while patching "
            f"{SYSTEM_MEMBER}; refusing to continue"
        )

    report = {
        "member": SYSTEM_MEMBER,
        "rows": len(table.rows),
        "dataset_strings": len(system["strings"]),
        "rows_changed": applied,
        "already_equal": len(system["strings"]) - applied - len(missing_in_target),
        "dataset_keys_absent_from_target": len(missing_in_target),
        "sample_absent_keys": missing_in_target[:16],
        "target_rows_left_untouched": len(table.rows) - applied,
        "envelope_bytes": len(encoded),
        "envelope_sha256": sha256_bytes(encoded),
    }
    return patched, encoded, report


def archive_inventory(directory: Path, manifest: Path) -> dict[str, str]:
    return {
        path.relative_to(directory).as_posix(): sha256_file(path)
        for path in directory.rglob("*")
        if path.is_file() and path.suffix.lower() != ".json"
    }


def apply_archive(
    gust_pak: Path,
    game_archive: Path,
    work_dir: Path,
    timeout: int,
    mutate,
    verify_dir: Path,
) -> dict[str, Any]:
    """Extract, mutate, repack and verify a single archive."""
    stem = work_dir.name
    print(f"  extracting {game_archive.name} ...")
    manifest, _ = extract_archive(gust_pak, game_archive, work_dir, timeout)

    before_hashes = archive_inventory(work_dir, manifest)
    before_members = sorted(before_hashes)

    result = mutate(work_dir)

    print(f"  repacking  {game_archive.name} ...")
    rebuilt = repack_archive(gust_pak, manifest, work_dir, timeout)

    print(f"  verifying  {game_archive.name} ...")
    if verify_dir.exists():
        shutil.rmtree(verify_dir)
    verify_dir.mkdir(parents=True)
    verify_manifest, _ = extract_archive(gust_pak, rebuilt, verify_dir, timeout)
    after_hashes = archive_inventory(verify_dir, verify_manifest)
    after_members = sorted(after_hashes)

    missing = [name for name in before_members if name not in after_hashes]
    added = [name for name in after_members if name not in before_hashes]
    if missing or added:
        raise FrenchPatchError(
            f"{stem}: rebuilt archive membership changed "
            f"(missing={missing[:5]}, added={added[:5]})"
        )

    unexpected: list[str] = []
    for name, digest in before_hashes.items():
        if after_hashes[name] != digest and name not in result.get("changed_members", {}):
            unexpected.append(name)
    if unexpected:
        raise FrenchPatchError(
            f"{stem}: rebuilt archive changed unexpected members: {unexpected[:5]}"
        )

    for name, expected in result.get("changed_members", {}).items():
        actual = after_hashes.get(name)
        if actual != expected:
            raise FrenchPatchError(
                f"{stem}: rebuilt member {name} does not match the staged content"
            )

    return {
        "stem": stem,
        "game_archive": game_archive,
        "rebuilt": rebuilt,
        "members": len(after_hashes),
        "changed_members": sorted(result.get("changed_members", {})),
        "details": result.get("report", {}),
    }


# --------------------------------------------------------------------------- #
# movies
# --------------------------------------------------------------------------- #


def resolve_movies_dir(explicit: Optional[str], dataset_root: Path) -> Optional[Path]:
    if explicit:
        path = Path(explicit).expanduser().resolve()
        if not path.is_dir():
            raise FrenchPatchError(f"--movies-dir is not a directory: {path}")
        return path
    for candidate in (dataset_root.parent / "movies", dataset_root / "movies"):
        if candidate.is_dir():
            return candidate
    return None


def load_movies(movies_dir: Path) -> dict[str, Path]:
    result: dict[str, Path] = {}
    for basename, relative in MOVIES.items():
        source = resolve_path_ci(movies_dir, basename)
        if source is None:
            raise FrenchPatchError(
                f"movie not found in {movies_dir}: {basename}\n"
                f"Expected: {relative}"
            )
        result[basename] = source
    return result


def install_movies(
    game_dir: Path,
    movies_dir: Path,
    backup_dir: Path,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Back up and install the four French movies, returning state entries."""
    sources = load_movies(movies_dir)
    movie_backup_dir = backup_dir / "movies"
    movie_backup_dir.mkdir(parents=True, exist_ok=True)

    entries: list[dict[str, Any]] = []
    installed = 0
    for basename, relative in MOVIES.items():
        target = resolve_path_ci(game_dir, relative)
        if target is None:
            print(f"  skip      {relative} (not present in this installation)")
            continue
        source = sources[basename]
        source_sha = sha256_file(source)
        original_sha = sha256_file(target)

        if source_sha == original_sha:
            print(f"  already   {basename} (identical to the French movie)")
            entries.append(
                {
                    "relative": target.relative_to(game_dir).as_posix(),
                    "name": basename,
                    "backup": "",
                    "original_bytes": target.stat().st_size,
                    "original_sha256": original_sha,
                    "patched_bytes": target.stat().st_size,
                    "patched_sha256": source_sha,
                }
            )
            installed += 1
            continue

        backup_path = movie_backup_dir / basename
        if backup_path.is_file():
            if sha256_file(backup_path) != original_sha:
                raise FrenchPatchError(
                    f"A different backup already exists for movie {basename}: "
                    f"{backup_path}. Refusing to overwrite it."
                )
        else:
            shutil.copy2(target, backup_path)
            print(f"  backup    {basename} -> "
                  f"{backup_path.relative_to(game_dir).as_posix()}")

        staged = target.with_name(target.name + ".br_french_patch_stage")
        shutil.copy2(source, staged)
        atomic_replace_file(staged, target)
        if sha256_file(target) != source_sha:
            raise FrenchPatchError(f"movie install verification failed for {basename}")
        print(f"  installed {basename} ({human_bytes(target.stat().st_size)})")
        installed += 1
        entries.append(
            {
                "relative": target.relative_to(game_dir).as_posix(),
                "name": basename,
                "backup": backup_path.relative_to(game_dir).as_posix(),
                "original_bytes": backup_path.stat().st_size,
                "original_sha256": original_sha,
                "patched_bytes": target.stat().st_size,
                "patched_sha256": source_sha,
            }
        )

    summary = {"expected": len(MOVIES), "installed": installed}
    return entries, summary


def cmd_apply(args: argparse.Namespace) -> int:
    started = time.time()
    game_dir = Path(args.game_dir).expanduser().resolve()
    if not game_dir.is_dir():
        raise FrenchPatchError(f"--game-dir is not a directory: {game_dir}")

    dataset_root = (
        Path(args.dataset).expanduser().resolve()
        if args.dataset
        else default_dataset_dir()
    )
    dataset = load_dataset(dataset_root)
    print(f"game        : {game_dir}")
    print(f"dataset     : {dataset_root}")
    print(f"language    : French (fr)")

    state = load_state(game_dir)
    if state is not None and not args.force:
        raise FrenchPatchError(
            "The French patch is already recorded as installed in this game "
            f"directory ({state_paths(game_dir)['state']}).\n"
            "Run 'revert' first, or pass --force to reinstall over the current "
            "state (the existing backup is never overwritten)."
        )

    gust_pak = find_gust_pak(args.gust_pak)
    print(f"gust_pak    : {gust_pak}")

    install = detect_install(game_dir)
    for stem, path in sorted(install.items()):
        print(f"archive     : {path.relative_to(game_dir).as_posix()} "
              f"({human_bytes(path.stat().st_size)})")

    paths = state_paths(game_dir)
    backup_dir = paths["backup"]
    work_root = (
        Path(args.work_dir).expanduser().resolve()
        if args.work_dir
        else paths["work"]
    )
    if work_root.exists():
        shutil.rmtree(work_root)
    work_root.mkdir(parents=True, exist_ok=True)

    print()
    print("== Preflight ==")
    member_lists: dict[str, set[str]] = {}
    for stem, game_archive in GAME_ARCHIVES.items():
        # The repository's gust_pak wrapper normalises backslashes to slashes.
        resolved = install[stem]
        members = list_members(gust_pak, resolved, work_root, args.timeout)
        member_lists[stem] = {member.replace("\\", "/") for member in members}
        print(f"  {resolved.name}: {len(members)} members")

    if SYSTEM_MEMBER not in member_lists["PACK02_1"]:
        raise FrenchPatchError(
            f"{SYSTEM_MEMBER} is not present in the target PACK02_1 archive"
        )
    envelope_expected = SYSTEM_ENVELOPE_MEMBER in member_lists["PACK02_1"]
    if not envelope_expected:
        print(
            f"  note: {SYSTEM_ENVELOPE_MEMBER} is absent from this installation; "
            f"only the plain XML member will be written"
        )

    missing_units = [
        logical
        for logical in dataset["units"]
        if f"{EVENT_MEMBER_ROOT}/{logical}" not in member_lists["PACK01"]
    ]
    if missing_units:
        print(
            f"  note: {len(missing_units)} dataset scripts are absent from this "
            f"installation and will be skipped"
        )

    # ---------------------------------------------------------------- patch --
    print()
    print("== Patching ==")

    def mutate_pack01(work_dir: Path) -> dict[str, Any]:
        event_root = work_dir / EVENT_MEMBER_ROOT
        changed: dict[str, str] = {}
        reports: list[dict[str, Any]] = []
        counters = {
            "applied": 0,
            "skipped_units": 0,
            "records_applied": 0,
            "records_unmapped": 0,
        }
        for index, (logical, unit) in enumerate(sorted(dataset["units"].items()), 1):
            template_path = event_root / logical
            patched, report = patch_event_unit(
                template_path, unit, args.allow_structural_mismatch
            )
            reports.append(report)
            if patched is None:
                counters["skipped_units"] += 1
                continue
            template_path.write_bytes(patched)
            changed[f"{EVENT_MEMBER_ROOT}/{logical}"] = sha256_bytes(patched)
            counters["applied"] += 1
            counters["records_applied"] += report["applied"]
            counters["records_unmapped"] += report["skipped"]
            if index % 400 == 0:
                print(f"  events: {index}/{len(dataset['units'])} scripts")

        skipped = [row for row in reports if row["status"] != "applied"]
        return {
            "changed_members": changed,
            "report": {
                **counters,
                "units_total": len(dataset["units"]),
                "skipped_detail": skipped[:64],
                "skipped_detail_truncated": max(0, len(skipped) - 64),
            },
        }

    def mutate_pack02(work_dir: Path) -> dict[str, Any]:
        template_path = work_dir / SYSTEM_MEMBER
        if not template_path.is_file():
            raise FrenchPatchError(f"Missing system template: {template_path}")
        patched, encoded, report = patch_system_member(template_path, dataset["system"])
        template_path.write_bytes(patched)
        changed = {SYSTEM_MEMBER: sha256_bytes(patched)}
        if envelope_expected:
            envelope_path = work_dir / SYSTEM_ENVELOPE_MEMBER
            envelope_path.write_bytes(encoded)
            changed[SYSTEM_ENVELOPE_MEMBER] = sha256_bytes(encoded)
        return {"changed_members": changed, "report": report}

    results: list[dict[str, Any]] = []
    results.append(
        apply_archive(
            gust_pak,
            install["PACK01"],
            work_root / "PACK01",
            args.timeout,
            mutate_pack01,
            work_root / "verify" / "PACK01",
        )
    )
    results.append(
        apply_archive(
            gust_pak,
            install["PACK02_1"],
            work_root / "PACK02_1",
            args.timeout,
            mutate_pack02,
            work_root / "verify" / "PACK02_1",
        )
    )

    event_report = results[0]["details"]
    system_report = results[1]["details"]
    print()
    print(
        f"  events: {event_report['applied']}/{event_report['units_total']} scripts "
        f"patched, {event_report['records_applied']} records written, "
        f"{event_report['records_unmapped']} records unmapped"
    )
    print(
        f"  system: {system_report['rows_changed']}/{system_report['rows']} rows "
        f"changed, {system_report['dataset_keys_absent_from_target']} dataset keys "
        f"absent from this installation"
    )
    if event_report["skipped_detail"]:
        print("  scripts left untouched:")
        for row in event_report["skipped_detail"][:16]:
            print(f"    - {row['unit']} ({row['status']})")
        remaining = len(event_report["skipped_detail"]) + event_report["skipped_detail_truncated"] - 16
        if remaining > 0:
            print(f"    ... and {remaining} more")

    if args.dry_run:
        print()
        print("dry run: nothing was written to the game directory")
        print(f"staged output kept in {work_root}")
        return 0

    # --------------------------------------------------------------- commit --
    print()
    print("== Committing ==")
    backup_dir.mkdir(parents=True, exist_ok=True)
    state_archives: list[dict[str, Any]] = []
    for result in results:
        stem = result["stem"]
        game_archive = result["game_archive"]
        originals = [
            entry
            for entry in (state or {}).get("archives", [])
            if entry.get("relative", "").lower() == game_archive.name.lower()
        ]
        backup_path = backup_dir / game_archive.name
        original_sha = sha256_file(game_archive)
        if backup_path.is_file():
            if sha256_file(backup_path) != original_sha:
                raise FrenchPatchError(
                    f"A different backup already exists for {game_archive.name}: "
                    f"{backup_path}. Refusing to overwrite it.\n"
                    f"Move it away if the current game file is the correct "
                    f"baseline for a new patch."
                )
        else:
            shutil.copy2(game_archive, backup_path)
            print(f"  backup    {game_archive.name} -> "
                  f"{backup_path.relative_to(game_dir).as_posix()}")

        staged = work_root / f"{stem}.staged{game_archive.suffix.lower()}"
        shutil.copy2(result["rebuilt"], staged)
        atomic_replace_file(staged, game_archive)
        print(f"  installed {game_archive.name} "
              f"({human_bytes(game_archive.stat().st_size)})")

        state_archives.append(
            {
                "relative": game_archive.relative_to(game_dir).as_posix(),
                "name": game_archive.name,
                "backup": backup_path.relative_to(game_dir).as_posix(),
                "original_bytes": backup_path.stat().st_size,
                "original_sha256": original_sha,
                "patched_bytes": game_archive.stat().st_size,
                "patched_sha256": sha256_file(game_archive),
            }
        )

    state_movies: list[dict[str, Any]] = []
    movie_summary: dict[str, Any] = {}
    if args.with_movies:
        print()
        print("== Movies ==")
        movies_dir = resolve_movies_dir(args.movies_dir, dataset_root)
        if movies_dir is None:
            raise FrenchPatchError(
                "--with-movies was requested but no movies were found. "
                "Provide --movies-dir PATH or place a movies/ folder beside "
                "the dataset containing the four .wmv files."
            )
        print(f"  source     : {movies_dir}")
        state_movies, movie_summary = install_movies(
            game_dir, movies_dir, backup_dir
        )

    state_document = {
        "type": "br_french_patch_state",
        "format_version": FR_DATASET_FORMAT_VERSION,
        "tool_version": FR_PATCH_TOOL_VERSION,
        "installed_utc": utc_now(),
        "game_dir": str(game_dir),
        "dataset_root": str(dataset_root),
        "dataset_manifest_sha256": sha256_file(dataset_paths(dataset_root)["manifest"]),
        "language": "fr",
        "archives": state_archives,
        "movies": state_movies,
        "movie_summary": movie_summary,
        "counts": {
            "event_units_patched": event_report["applied"],
            "event_units_total": event_report["units_total"],
            "event_records_written": event_report["records_applied"],
            "event_records_unmapped": event_report["records_unmapped"],
            "system_rows_changed": system_report["rows_changed"],
            "system_rows_total": system_report["rows"],
        },
    }
    atomic_write_bytes(
        paths["state"],
        json.dumps(state_document, ensure_ascii=False, sort_keys=True, indent=1).encode("utf-8"),
    )

    if not args.keep_work:
        shutil.rmtree(work_root, ignore_errors=True)

    print()
    print(f"French patch installed in {game_dir}")
    print(f"  state file : {paths['state'].relative_to(game_dir).as_posix()}")
    print(f"  backups    : {backup_dir.relative_to(game_dir).as_posix()}")
    if movie_summary:
        print(f"  movies     : {movie_summary['installed']}/{movie_summary['expected']} installed")
    print(f"  elapsed    : {time.time() - started:.1f}s")
    print()
    print("Start the game from its normal English configuration; the French "
          "text is written into the English text members.")
    print("Run 'revert' to restore the original archives.")
    return 0


# --------------------------------------------------------------------------- #
# status / revert
# --------------------------------------------------------------------------- #


def cmd_status(args: argparse.Namespace) -> int:
    game_dir = Path(args.game_dir).expanduser().resolve()
    state = load_state(game_dir)
    if state is None:
        print(f"No French patch state recorded in {game_dir}")
        return 1

    print(f"game dir      : {game_dir}")
    print(f"installed utc : {state.get('installed_utc')}")
    print(f"tool version  : {state.get('tool_version')}")
    print(f"dataset       : {state.get('dataset_root')}")
    counts = state.get("counts", {})
    print(
        f"coverage      : {counts.get('event_units_patched')}/"
        f"{counts.get('event_units_total')} scripts, "
        f"{counts.get('event_records_written')} records, "
        f"{counts.get('system_rows_changed')} system rows"
    )
    problems = 0
    for archive in state.get("archives", []):
        path = game_dir / archive["relative"]
        if not path.is_file():
            print(f"  MISSING   {archive['relative']}")
            problems += 1
            continue
        digest = sha256_file(path)
        if digest == archive["patched_sha256"]:
            print(f"  patched   {archive['relative']}")
        elif digest == archive["original_sha256"]:
            print(f"  original  {archive['relative']} (patch no longer applied)")
            problems += 1
        else:
            print(f"  modified  {archive['relative']} (unknown content)")
            problems += 1
        backup = game_dir / archive["backup"]
        if not backup.is_file() or sha256_file(backup) != archive["original_sha256"]:
            print(f"  WARNING   backup for {archive['name']} is missing or changed")
            problems += 1
    for movie in state.get("movies", []):
        path = game_dir / movie["relative"]
        if not path.is_file():
            print(f"  MISSING   movie {movie['relative']}")
            problems += 1
            continue
        digest = sha256_file(path)
        if digest == movie["patched_sha256"]:
            print(f"  patched   movie {movie['name']}")
        elif digest == movie["original_sha256"]:
            print(f"  original  movie {movie['name']} (patch no longer applied)")
            problems += 1
        else:
            print(f"  modified  movie {movie['name']} (unknown content)")
            problems += 1
        backup_rel = movie.get("backup")
        if backup_rel:
            backup = game_dir / backup_rel
            if not backup.is_file() or sha256_file(backup) != movie["original_sha256"]:
                print(f"  WARNING   backup for movie {movie['name']} is missing or changed")
                problems += 1
    return 0 if problems == 0 else 1


def cmd_revert(args: argparse.Namespace) -> int:
    game_dir = Path(args.game_dir).expanduser().resolve()
    state = load_state(game_dir)
    if state is None:
        raise FrenchPatchError(f"No French patch state recorded in {game_dir}")

    restored = 0
    skipped = 0
    for archive in state.get("archives", []):
        target = game_dir / archive["relative"]
        backup = game_dir / archive["backup"]
        if not backup.is_file():
            if args.force:
                print(f"  skipping  {archive['name']}: backup missing")
                skipped += 1
                continue
            raise FrenchPatchError(f"Backup is missing: {backup}")
        if sha256_file(backup) != archive["original_sha256"]:
            raise FrenchPatchError(
                f"Backup {backup} does not match the recorded original hash"
            )
        if target.is_file() and sha256_file(target) == archive["original_sha256"]:
            print(f"  already   {archive['name']} is the original")
            restored += 1
            continue
        staged = target.with_name(target.name + ".br_french_patch_restore")
        shutil.copy2(backup, staged)
        atomic_replace_file(staged, target)
        print(f"  restored  {archive['name']}")
        restored += 1

    for movie in state.get("movies", []):
        target = game_dir / movie["relative"]
        backup_rel = movie.get("backup")
        if not backup_rel:
            continue
        backup = game_dir / backup_rel
        if not backup.is_file():
            if args.force:
                print(f"  skipping  movie {movie['name']}: backup missing")
                skipped += 1
                continue
            raise FrenchPatchError(f"Backup is missing: {backup}")
        if sha256_file(backup) != movie["original_sha256"]:
            raise FrenchPatchError(
                f"Backup {backup} does not match the recorded original hash"
            )
        if target.is_file() and sha256_file(target) == movie["original_sha256"]:
            print(f"  already   movie {movie['name']} is the original")
            restored += 1
            continue
        staged = target.with_name(target.name + ".br_french_patch_restore")
        shutil.copy2(backup, staged)
        atomic_replace_file(staged, target)
        print(f"  restored  movie {movie['name']}")
        restored += 1

    state_file = state_paths(game_dir)["state"]
    state_file.unlink(missing_ok=True)
    print()
    print(f"Reverted {restored} item(s) in {game_dir} ({skipped} skipped)")
    print("Backups were kept; delete the .br_french_patch folder to remove them.")
    return 0


# --------------------------------------------------------------------------- #
# self-check
# --------------------------------------------------------------------------- #


def cmd_self_check(args: argparse.Namespace) -> int:
    """Validate the text envelope codec and, optionally, gust_pak."""
    import random

    print("text envelope codec")
    rng = random.Random(20260821)
    samples = [b"", b"<Root/>", bytes(rng.randrange(256) for _ in range(37))]
    samples.append(b"<Root>\r\n  <str Text=\"D\xc3\xa9fi sportif !\" String_No=\"1572865\"/>\r\n</Root>")
    samples.append(bytes(rng.randrange(256) for _ in range(4096)))
    samples.append(bytes(rng.randrange(256) for _ in range(8192)))
    for index, sample in enumerate(samples):
        if len(sample) < 14:
            try:
                envelope.encode_br_text_envelope(sample)
            except envelope.TextEnvelopeError:
                print(f"  sample {index}: correctly rejected ({len(sample)} bytes < 14)")
                continue
            raise FrenchPatchError(f"sample {index} should have been rejected")
        encoded = envelope.encode_br_text_envelope(sample)
        decoded = envelope.decode_br_text_envelope(encoded)
        if decoded != sample:
            raise FrenchPatchError(f"sample {index} envelope round-trip failed")
        print(f"  sample {index}: {len(sample)} -> {len(encoded)} bytes round-trip OK")

    if args.release_envelope:
        source = Path(args.release_envelope).expanduser().resolve()
        data = source.read_bytes()
        decoded = envelope.decode_br_text_envelope(data)
        print(f"  reference envelope decoded: {source.name} ({len(data)} bytes)")
        if args.expect_plain:
            expected = Path(args.expect_plain).expanduser().resolve().read_bytes()
            matches = decoded == expected
            print(f"  reference envelope matches {expected.name}: {matches}")
            if not matches:
                return 1
    return 0


# --------------------------------------------------------------------------- #
# build-bundle
# --------------------------------------------------------------------------- #


def cmd_build_bundle(args: argparse.Namespace) -> int:
    """Assemble a self-contained end-user package (distribution/french_patch)."""
    dataset_root = (
        Path(args.dataset).expanduser().resolve()
        if args.dataset
        else default_dataset_dir()
    )
    load_dataset(dataset_root)

    out_root = (
        Path(args.out).expanduser().resolve()
        if args.out
        else TOOL_DIR.parent / "distribution" / "french_patch"
    )
    if out_root.exists():
        shutil.rmtree(out_root)
    out_root.mkdir(parents=True)

    for name in (
        "br_french_patch.py",
        "br_quartet_french_patch.py",
        "br_second_light_french_patch.py",
        "br_french_installer.py",
        "br_french_cleanup.py",
        "br_french_names.py",
        "br_second_light_extract.py",
        "br_text_tool.py",
        "br_text_envelope.py",
        "br_translation_categories.py",
        "br_translation_xml.py",
        "translation_fr.dtd",
    ):
        shutil.copy2(TOOL_DIR / name, out_root / name)

    template_dir = TOOL_DIR / "french_patch_bundle"
    for name in ("RUN.cmd", "RUN.sh", "README.md"):
        source = template_dir / name
        if not source.is_file():
            raise FrenchPatchError(f"Bundle template is missing: {source}")
        shutil.copy2(source, out_root / name)

    shutil.copytree(dataset_root, out_root / "dataset")

    second_light_dataset = TOOL_DIR.parent / "titles" / "second_light" / "translation_fr"
    if (second_light_dataset / "manifest.json").is_file():
        shutil.copytree(second_light_dataset, out_root / "dataset_second_light")

    if args.with_movies:
        movies_dir = resolve_movies_dir(args.movies_dir, dataset_root)
        if movies_dir is None:
            raise FrenchPatchError(
                "--with-movies was requested but no movies were found. "
                "Provide --movies-dir PATH."
            )
        sources = load_movies(movies_dir)
        movie_out = out_root / "movies"
        movie_out.mkdir(parents=True)
        for basename, source in sources.items():
            shutil.copy2(source, movie_out / basename)
        print(f"  movies copied from {movies_dir}")

    if args.with_gust_pak:
        gust = find_gust_pak(args.gust_pak)
        shutil.copy2(gust, out_root / "gust_pak.exe")
        license_candidates = [
            gust.parent / "LICENSE.txt",
            TOOL_DIR.parent / ".local" / "vendor" / "gust_tools" / "LICENSE.txt",
        ]
        for candidate in license_candidates:
            if candidate.is_file():
                shutil.copy2(candidate, out_root / "LICENSE.gust_tools.txt")
                break

    print(f"bundle written to {out_root}")
    print(f"  contents: {sorted(path.name for path in out_root.iterdir())}")
    print(
        "  note: gust_pak.exe is bundled for Windows; Linux users must provide "
        "gust_pak via GUST_PAK or PATH"
        if not args.with_gust_pak
        else "  gust_pak.exe bundled for Windows (see LICENSE.gust_tools.txt)"
    )
    return 0


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="br_french_patch.py",
        description=(
            "BLUE REFLECTION (2017) French translation patch tool. "
            "Builds a compact French dataset from a French fan release and "
            "applies it to a user's own game installation."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--version", action="version", version=FR_PATCH_TOOL_VERSION)
    subparsers = parser.add_subparsers(dest="command", required=True)

    import_parser = subparsers.add_parser(
        "import-release",
        help="extract French text from a French fan release into a dataset",
    )
    import_parser.add_argument("--release-dir", required=True)
    import_parser.add_argument("--out", default=None)
    import_parser.add_argument("--work-dir", default=None)
    import_parser.add_argument("--baseline-db", default=None)
    import_parser.add_argument("--gust-pak", default=None)
    import_parser.add_argument("--reuse-extract", action="store_true")
    import_parser.add_argument("--timeout", type=int, default=1800)
    import_parser.set_defaults(func=cmd_import_release)

    apply_parser = subparsers.add_parser("apply", help="patch a game installation")
    apply_parser.add_argument("--game-dir", required=True)
    apply_parser.add_argument("--dataset", default=None)
    apply_parser.add_argument("--gust-pak", default=None)
    apply_parser.add_argument("--work-dir", default=None)
    apply_parser.add_argument("--timeout", type=int, default=1800)
    apply_parser.add_argument("--dry-run", action="store_true")
    apply_parser.add_argument("--force", action="store_true")
    apply_parser.add_argument("--keep-work", action="store_true")
    apply_parser.add_argument(
        "--with-movies",
        action="store_true",
        help="also install the four French .wmv movies",
    )
    apply_parser.add_argument(
        "--movies-dir",
        default=None,
        help="folder containing the four French .wmv movies (default: movies/ beside the dataset)",
    )
    apply_parser.add_argument(
        "--allow-structural-mismatch",
        action="store_true",
        help=(
            "also patch scripts whose message count differs from the dataset "
            "(slots are still matched by msg_id/name_id)"
        ),
    )
    apply_parser.set_defaults(func=cmd_apply)

    status_parser = subparsers.add_parser("status", help="report installation state")
    status_parser.add_argument("--game-dir", required=True)
    status_parser.set_defaults(func=cmd_status)

    revert_parser = subparsers.add_parser("revert", help="restore original archives")
    revert_parser.add_argument("--game-dir", required=True)
    revert_parser.add_argument("--force", action="store_true")
    revert_parser.set_defaults(func=cmd_revert)

    check_parser = subparsers.add_parser(
        "self-check", help="validate the text envelope codec"
    )
    check_parser.add_argument("--release-envelope", default=None)
    check_parser.add_argument("--expect-plain", default=None)
    check_parser.set_defaults(func=cmd_self_check)

    bundle_parser = subparsers.add_parser(
        "build-bundle", help="assemble a self-contained end-user package"
    )
    bundle_parser.add_argument("--out", default=None)
    bundle_parser.add_argument("--dataset", default=None)
    bundle_parser.add_argument("--gust-pak", default=None)
    bundle_parser.add_argument(
        "--with-gust-pak",
        action="store_true",
        help="bundle gust_pak.exe (Windows) into the package",
    )
    bundle_parser.add_argument(
        "--with-movies",
        action="store_true",
        help="copy the four French .wmv movies into the bundle's movies/ folder",
    )
    bundle_parser.add_argument(
        "--movies-dir",
        default=None,
        help="folder containing the four French .wmv movies",
    )
    bundle_parser.set_defaults(func=cmd_build_bundle)

    return parser


def main(argv: Optional[Iterable[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)
    try:
        return int(args.func(args))
    except (FrenchPatchError, bt.ToolError, envelope.TextEnvelopeError) as exc:
        print(f"\nERROR: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\ninterrupted", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
