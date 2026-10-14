"""Apply the French translation to BLUE REFLECTION Second Light.

Standalone Second Light: patches ``Data/PACK01.PAK`` (the event dialogue under
``event/event_en``).  Its system text already ships in French inside the fan
beta's ``PACK02``, so the tool leaves it alone.

BLUE REFLECTION Quartet (partition b4): patches the dialogue in
``Data/PACK01_03.PAK`` (``event/b4/event_en``) and merges the French system text
into ``saves/b4/text_en/strcombineall.xml`` of ``Data/PACK02_03.PAK``,
regenerating its ``.e`` envelope with the Second Light (A21) key.

The event ``.ebm`` files are plain (no text envelope), so the dialogue can be
rewritten directly.

``python br_second_light_french_patch.py apply --game-dir DIR``
``python br_second_light_french_patch.py revert --game-dir DIR``
``python br_second_light_french_patch.py status --game-dir DIR``
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any, Optional

TOOL_DIR = Path(__file__).resolve().parent
if str(TOOL_DIR) not in sys.path:
    sys.path.insert(0, str(TOOL_DIR))

import br_french_patch as bp  # noqa: E402
import br_text_envelope as envelope  # noqa: E402
import br_text_tool as bt  # noqa: E402
import br_translation_xml as tx  # noqa: E402

FR_PATCH_TOOL_VERSION = "fr-sl-patch-0.2.0"
TARGET_ID = "second_light_original"

# The Quartet's b4 system text is English; the standalone game gets French
# system text from the fan beta, so only the Quartet needs it patched.
SYSTEM_ARCHIVE = "Data/PACK02_03.PAK"
SYSTEM_MEMBER = "saves/b4/text_en/strcombineall.xml"
SYSTEM_ENVELOPE_MEMBER = "saves/b4/text_en/strcombineall.xml.e"
SYSTEM_CATEGORIES = ("names", "places", "items", "messages", "other")

# Standalone Second Light keeps its events in PACK01; the Quartet ships the same
# game as partition "b4" inside PACK01_03.
LAYOUTS = (
    ("quartet", "Data/PACK01_03.PAK", "event/b4/event_en"),
    ("standalone", "Data/PACK01.PAK", "event/event_en"),
)

STATE_DIRNAME = ".br_french_second_light"
STATE_FILE = "state.json"
BACKUP_DIRNAME = "backup"

FrenchPatchError = bp.FrenchPatchError


def detect_layout(game_dir: Path) -> tuple[str, str, str]:
    """Return (name, archive, event member root) for the install in ``game_dir``."""
    for layout in LAYOUTS:
        if (game_dir / layout[1]).is_file():
            return layout
    raise FrenchPatchError(
        "Neither Data/PACK01_03.PAK (Quartet) nor Data/PACK01.PAK (Second Light) "
        f"found in {game_dir}"
    )


def default_dataset_dir() -> Path:
    bundled = TOOL_DIR / "dataset_second_light"
    if bundled.is_dir():
        return bundled
    return TOOL_DIR.parent / "titles" / "second_light" / "translation_fr"


def load_dataset(root: Path) -> dict[str, Any]:
    if not (root / "manifest.json").is_file():
        raise FrenchPatchError(
            f"French translation dataset not found: {root / 'manifest.json'}"
        )
    units: dict[str, dict[str, Any]] = {}
    for parsed in tx.read_numbered(root, "dialogue"):
        for chapter in parsed.get("dialogue") or []:
            for event in chapter["events"]:
                # dataset files look like "event_en/aa01/x.ebm"
                logical = event["file"].split("/", 1)[1] if "/" in event["file"] else event["file"]
                units[logical] = {
                    "path": logical,
                    "records": [
                        [i, m.get("msg_id"), m.get("name_id"), m["text"]]
                        for i, m in enumerate(event["messages"])
                    ],
                }
    if not units:
        raise FrenchPatchError(f"No dialogue found in the dataset at {root}")
    return {"root": root, "units": units}


def load_system(root: Path) -> dict[str, str]:
    """Map String_No -> French text for every system category."""
    strings: dict[str, str] = {}
    for category in SYSTEM_CATEGORIES:
        path = root / f"{category}.xml"
        if path.is_file():
            strings.update(tx.parse_translation(path).get(category) or {})
    return strings


# Tokens the game substitutes at run time: a translation that loses or adds one
# would break the string, so such entries keep the original text.
_RUNTIME_TOKEN_RE = re.compile(r"%[sd]|<(?:NUM|STR|IM|KEY_ASSIGN_)[A-Z0-9_]*>")


def _runtime_tokens(text: str) -> list[str]:
    return sorted(_RUNTIME_TOKEN_RE.findall(text))


def patch_system_table(
    plain: bytes, path: Path, system: dict[str, str]
) -> tuple[bytes, bytes, dict[str, int]]:
    """Merge the French strings into strcombineall.xml and rebuild its envelope."""
    table = bt.parse_xml_table_bytes(plain, path)
    replacements: dict[int, str] = {}
    stats = {"rows": len(table.rows), "written": 0, "kept_empty": 0, "kept_tokens": 0, "kept_marker": 0}
    for row in table.rows:
        key = row.string_no or row.string_id
        text = system.get(key) if key is not None else None
        if text is None or text == row.text:
            continue
        if text == "":
            stats["kept_empty"] += 1
        elif text.startswith("[[") and not row.text.startswith("[["):
            stats["kept_marker"] += 1
        elif _runtime_tokens(text) != _runtime_tokens(row.text):
            stats["kept_tokens"] += 1
        else:
            replacements[row.index] = text
            stats["written"] += 1
    patched = bt.serialize_xml_table(table, replacements)
    seeds = envelope.SECOND_LIGHT_A21_SEEDS
    encoded = envelope.encode_text_envelope(patched, seeds)
    if envelope.decode_text_envelope(encoded, seeds) != patched:
        raise FrenchPatchError("system envelope round-trip self-check failed")
    return patched, encoded, stats


# --------------------------------------------------------------------------- #
# event patching
# --------------------------------------------------------------------------- #


def patch_event_file(path: Path, records: list[list[Any]]) -> tuple[int, bool]:
    """Rewrite the messages of one .ebm.  Returns (changed, skipped).

    When the dataset's whole (msg_id, name_id) sequence equals the game file's,
    every record is written by position, which also covers ``4294967295`` ("no
    identifier", shared by voice continuations) and msg_ids repeated within a
    script.  Otherwise records are matched by msg_id when it is unique, and the
    rest are left alone rather than risk a translation landing on the wrong
    line.
    """
    ebm = bt.parse_ebm(path)
    index_by_msg: dict[int, list[int]] = {}
    for i, message in enumerate(ebm.messages):
        index_by_msg.setdefault(message.msg_id, []).append(i)
    files = [m.text for m in ebm.messages]
    same_layout = len(records) == len(ebm.messages) and all(
        msg_id == m.msg_id and name_id == m.name_id
        for (_i, msg_id, name_id, _t), m in zip(records, ebm.messages)
    )
    changed = 0
    for index, msg_id, _name_id, text in records:
        if same_layout:
            i = index
        elif msg_id == 0xFFFFFFFF:
            continue
        else:
            targets = index_by_msg.get(msg_id, [])
            if len(targets) != 1:
                # ambiguous or absent: do not guess
                continue
            i = targets[0]
        if files[i] != text:
            files[i] = text
            changed += 1
    if not changed:
        return 0, False
    data = bt.serialize_ebm(ebm, files)
    try:
        bt.parse_ebm_bytes(data, path)
    except Exception:  # pragma: no cover - defensive
        return 0, True
    path.write_bytes(data)
    return changed, False


def load_state(game_dir: Path) -> dict[str, Any]:
    state_file = game_dir / STATE_DIRNAME / STATE_FILE
    if not state_file.is_file():
        return {}
    try:
        return json.loads(state_file.read_text(encoding="utf-8"))
    except ValueError:
        return {}


def pristine_source(game_dir: Path, relative: str, state: dict[str, Any]) -> tuple[Path, bool]:
    """Return (original archive to patch from, whether the backup must be refreshed).

    * no backup yet                          -> the installed archive is the original;
    * installed archive is the one we wrote  -> patch again from our backup;
    * anything else (Steam update/verify)    -> the installed archive is the new
      original and replaces the stale backup.
    """
    target = game_dir / relative
    backup = game_dir / STATE_DIRNAME / BACKUP_DIRNAME / target.name
    if not backup.is_file():
        return target, False
    current = bp.sha256_file(target)
    if current == bp.sha256_file(backup):
        return target, False
    written = (state.get("sha256_after") or {}).get(relative)
    if written is None and relative == state.get("archive"):
        written = state.get("archive_sha256_after")
    if written is None and state:
        # installed by an older version that did not record this archive's hash
        return backup, False
    if written is not None and current == written:
        return backup, False
    return target, True


def cmd_apply(args: argparse.Namespace) -> int:
    game_dir = Path(args.game_dir).expanduser().resolve()
    if not game_dir.is_dir():
        raise FrenchPatchError(f"--game-dir is not a directory: {game_dir}")
    dataset_root = (
        Path(args.dataset).expanduser().resolve() if args.dataset else default_dataset_dir()
    )
    gust_pak = bp.find_gust_pak(args.gust_pak)
    dataset = load_dataset(dataset_root)
    units = dataset["units"]

    # The archives hold long member paths: keep the default work directory short
    # (Windows refuses to create files past ~260 characters) and remove it after.
    temporary = not args.work_dir
    work_root = (
        Path(tempfile.gettempdir()) / "br_sl_work"
        if temporary
        else Path(args.work_dir).expanduser().resolve()
    )
    work_root.mkdir(parents=True, exist_ok=True)
    try:
        return _apply(args, game_dir, dataset_root, gust_pak, dataset, units, work_root)
    finally:
        if temporary:
            shutil.rmtree(work_root, ignore_errors=True)


def _apply(
    args: argparse.Namespace,
    game_dir: Path,
    dataset_root: Path,
    gust_pak: Path,
    dataset: dict[str, Any],
    units: dict[str, dict[str, Any]],
    work_root: Path,
) -> int:

    layout, game_archive, event_member_root = detect_layout(game_dir)
    archive = game_dir / game_archive
    state = load_state(game_dir)
    sources = {
        relative: pristine_source(game_dir, relative, state)
        for relative in ([game_archive] + ([SYSTEM_ARCHIVE] if layout == "quartet" else []))
    }
    for relative, (_src, refresh) in sources.items():
        if refresh:
            print(f"note        : {relative} changed outside this tool (Steam update?); using it as the new original")

    print(f"game        : {game_dir} ({layout})")
    print(f"dataset     : {dataset_root} ({len(units)} scripts)")
    print(f"gust_pak    : {gust_pak}")

    manifest, _ = bp.extract_archive(gust_pak, sources[game_archive][0], work_root / "PACK01", args.timeout)
    event_root = work_root / "PACK01" / event_member_root
    if not event_root.is_dir():
        raise FrenchPatchError(f"{event_member_root} not found in the extracted archive")

    patched = 0
    changed_total = 0
    skipped: list[str] = []
    missing: list[str] = []
    for logical, unit in units.items():
        target = event_root / logical
        if not target.is_file():
            missing.append(logical)
            continue
        try:
            changed, failed = patch_event_file(target, unit["records"])
        except Exception:
            skipped.append(logical)
            continue
        if failed:
            skipped.append(logical)
            continue
        if changed:
            patched += 1
            changed_total += changed

    print(f"events      : {patched} scripts patched, {changed_total} messages written")
    if missing:
        print(f"              {len(missing)} dataset scripts absent from this install")
    if skipped:
        print(f"              {len(skipped)} scripts skipped (unsupported EBM layout)")

    installs: list[tuple[str, Path]] = [
        (game_archive, bp.repack_archive(gust_pak, manifest, work_root / "PACK01", args.timeout))
    ]

    system_stats: dict[str, int] = {}
    if layout == "quartet":
        system_archive = game_dir / SYSTEM_ARCHIVE
        if not system_archive.is_file():
            raise FrenchPatchError(f"{SYSTEM_ARCHIVE} not found in {game_dir}")
        system = load_system(dataset_root)
        sys_manifest, _ = bp.extract_archive(gust_pak, sources[SYSTEM_ARCHIVE][0], work_root / "PACK02", args.timeout)
        plain_path = work_root / "PACK02" / SYSTEM_MEMBER
        if not plain_path.is_file():
            raise FrenchPatchError(f"{SYSTEM_MEMBER} not found in the extracted archive")
        patched_xml, encoded, system_stats = patch_system_table(plain_path.read_bytes(), plain_path, system)
        plain_path.write_bytes(patched_xml)
        (work_root / "PACK02" / SYSTEM_ENVELOPE_MEMBER).write_bytes(encoded)
        print(
            f"system      : {system_stats['written']} strings written "
            f"({system_stats['kept_tokens']} kept for runtime tokens, "
            f"{system_stats['kept_empty']} untranslated, {system_stats['kept_marker']} markers)"
        )
        installs.append(
            (SYSTEM_ARCHIVE, bp.repack_archive(gust_pak, sys_manifest, work_root / "PACK02", args.timeout))
        )

    state_dir = game_dir / STATE_DIRNAME
    backup_dir = state_dir / BACKUP_DIRNAME
    backup_dir.mkdir(parents=True, exist_ok=True)
    for relative, new_pak in installs:
        target = game_dir / relative
        backup = backup_dir / target.name
        if not backup.is_file() or sources[relative][1]:
            shutil.copy2(target, backup)
        shutil.copy2(new_pak, target)

    state = {
        "type": "br_sl_french_patch_state",
        "version": FR_PATCH_TOOL_VERSION,
        "target": TARGET_ID,
        "installed_utc": bp.utc_now(),
        "scripts_patched": patched,
        "messages_written": changed_total,
        "scripts_skipped": skipped,
        "archive": game_archive,
        "archives": [relative for relative, _new in installs],
        "layout": layout,
        "system": system_stats,
        "archive_sha256_after": bp.sha256_file(archive),
        "sha256_after": {relative: bp.sha256_file(game_dir / relative) for relative, _new in installs},
    }
    bp.atomic_write_bytes(
        state_dir / STATE_FILE,
        json.dumps(state, ensure_ascii=False, indent=1).encode("utf-8"),
    )
    print(f"installed   : {', '.join(relative for relative, _new in installs)}")
    return 0


def cmd_revert(args: argparse.Namespace) -> int:
    game_dir = Path(args.game_dir).expanduser().resolve()
    state_dir = game_dir / STATE_DIRNAME
    backups = sorted((state_dir / BACKUP_DIRNAME).glob("*.PAK"))
    if not backups:
        raise FrenchPatchError(f"No backup found in {state_dir / BACKUP_DIRNAME}")
    for backup in backups:
        shutil.copy2(backup, game_dir / "Data" / backup.name)
        print(f"restored Data/{backup.name}")
    shutil.rmtree(state_dir, ignore_errors=True)
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    game_dir = Path(args.game_dir).expanduser().resolve()
    state_file = game_dir / STATE_DIRNAME / STATE_FILE
    if not state_file.is_file():
        print("not installed")
        return 1
    state = json.loads(state_file.read_text(encoding="utf-8"))
    print(f"installed : {state.get('installed_utc')}")
    print(f"scripts   : {state.get('scripts_patched')} ({state.get('messages_written')} messages)")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="French patch for BLUE REFLECTION Second Light")
    sub = parser.add_subparsers(dest="command", required=True)
    for name, func in (("apply", cmd_apply), ("revert", cmd_revert), ("status", cmd_status)):
        p = sub.add_parser(name)
        p.add_argument("--game-dir", required=True)
        if name == "apply":
            p.add_argument("--dataset")
            p.add_argument("--gust-pak")
            p.add_argument("--work-dir")
            p.add_argument("--timeout", type=int, default=3600)
        p.set_defaults(func=func)
    return parser


def main(argv: Optional[list[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return int(args.func(args))
    except FrenchPatchError as exc:
        print(f"\nERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
