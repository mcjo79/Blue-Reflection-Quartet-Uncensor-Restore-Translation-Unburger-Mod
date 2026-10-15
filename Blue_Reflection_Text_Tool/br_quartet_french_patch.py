#!/usr/bin/env python3
"""Apply the French translation to the BLUE REFLECTION Quartet "b1" partition.

The fan release targets the 2017 standalone; Quartet stores the first game in
its own archives (``Data/PACK11.PAK`` events, ``Data/PACK12.PAK`` system text,
A22/A24 format).  This tool reuses the repository's own Quartet target-adaptation
policy (``adapt_quartet_text``) to translate the ``<IM..>`` button tokens into
Quartet's ``<KEY_ASSIGN_..>`` tokens, merges the French composite strings into
Quartet's ``saves/b1/text_en/strcombineall.xml`` and regenerates its envelope.

Usage
-----
``python br_quartet_french_patch.py apply --game-dir "D:\\...\\BLUE REFLECTION Quartet"``
``python br_quartet_french_patch.py status  --game-dir "..."``
``python br_quartet_french_patch.py revert --game-dir "..."``
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Optional

TOOL_DIR = Path(__file__).resolve().parent
if str(TOOL_DIR) not in sys.path:
    sys.path.insert(0, str(TOOL_DIR))

import br_french_patch as bp  # noqa: E402
import br_text_envelope as envelope  # noqa: E402
import br_text_tool as bt  # noqa: E402

QUARTET_TOOL_VERSION = "fr-quartet-patch-0.1.0"

GAME_ARCHIVES = {
    "PACK11": "Data/PACK11.PAK",
    "PACK12": "Data/PACK12.PAK",
}
EVENT_EN_ROOT = "event/b1/event_en"
EVENT_JP_ROOT = "event/b1/event_jp"
SYSTEM_MEMBER = "saves/b1/text_en/strcombineall.xml"
SYSTEM_ENVELOPE_MEMBER = "saves/b1/text_en/strcombineall.xml.e"

STATE_DIR_NAME = ".br_french_quartet_patch"


def default_baseline_db() -> Path:
    return TOOL_DIR.parent / "titles" / "blue_reflection" / "translation"


def load_baseline_events(root: Path) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    events = root / "events"
    if not events.is_dir():
        return result
    for path in events.rglob("*.ebm.json"):
        logical = path.relative_to(events).as_posix()[: -len(".json")]
        result[logical] = json.loads(path.read_text(encoding="utf-8"))
    return result


def load_baseline_system(root: Path) -> dict[str, dict[str, Any]]:
    """Map String_No -> canonical record, across all system tables."""
    result: dict[str, dict[str, Any]] = {}
    for folder in ("system", "system_quartet_extensions"):
        base = root / folder
        if not base.is_dir():
            continue
        for path in base.glob("*.xml.json"):
            unit = json.loads(path.read_text(encoding="utf-8"))
            for record in unit.get("records", []):
                key = record.get("string_no") or record.get("string_id")
                if key is not None:
                    result[str(key)] = record
    return result


def msg_id_index_map(messages) -> dict[int, list[int]]:
    grouped: dict[int, list[int]] = defaultdict(list)
    for message in messages:
        grouped[message.msg_id].append(message.index)
    return grouped


def adapt_event_unit(
    quartet_en_path: Path,
    quartet_jp_path: Path,
    fr_unit: dict[str, Any],
    baseline_unit: Optional[dict[str, Any]],
    policy: dict[str, Any],
) -> tuple[Optional[bytes], dict[str, Any]]:
    logical = fr_unit["path"]
    if not quartet_en_path.is_file() or not quartet_jp_path.is_file():
        return None, {"unit": logical, "status": "template_missing"}

    en_ebm = bt.parse_ebm(quartet_en_path)
    jp_ebm = bt.parse_ebm(quartet_jp_path)
    en_by_id = msg_id_index_map(en_ebm.messages)
    jp_by_id = msg_id_index_map(jp_ebm.messages)

    baseline_records = baseline_unit["records"] if baseline_unit else []

    # Alignment: when the source and Quartet message-id sequences are identical
    # (the common case, including 0xFFFFFFFF sentinels), map by index.  Otherwise
    # fall back to unique msg_id matching (skipping the 0xFFFFFFFF sentinel).
    fr_msg_ids = [rec[1] for rec in fr_unit["records"]]
    q_msg_ids = [m.msg_id for m in en_ebm.messages]
    if len(fr_msg_ids) == len(q_msg_ids) and fr_msg_ids == q_msg_ids:
        index_of = {i: i for i in range(len(fr_msg_ids))}
    else:
        unique_q = bt.unique_msg_id_map(en_ebm.messages)
        index_of = {}
        for record in fr_unit["records"]:
            if record[1] != 0xFFFFFFFF:
                target = unique_q.get(record[1])
                if target is not None:
                    index_of[record[0]] = target

    texts = [m.text for m in en_ebm.messages]
    assignments: dict[int, str] = {}
    applied = 0
    skipped = 0
    preserved = 0
    adaptation_counts: Counter = Counter()
    problems: list[str] = []

    for record in fr_unit["records"]:
        index, msg_id, _name_id, fr_text = record
        en_index = index_of.get(index)
        if en_index is None:
            skipped += 1
            continue

        baseline_record = (
            baseline_records[index]
            if index < len(baseline_records) and baseline_records[index].get("msg_id") == msg_id
            else None
        )
        if baseline_record is None:
            # Without a canonical record we cannot run the policy; apply text as-is.
            if fr_text != "":
                assignments[en_index] = fr_text
                applied += 1
            else:
                skipped += 1
            continue

        jp_candidates = jp_by_id.get(msg_id, [])
        jp_index = jp_candidates[0] if len(jp_candidates) == 1 else en_index

        # The adaptation policy fingerprints were built against the *official*
        # Quartet English.  Use the canonical "en_auxiliary" as the EN reference
        # so the policy validates even when the Unburger translation is present.
        target_en_text = baseline_record.get("en_auxiliary")
        if not isinstance(target_en_text, str) or target_en_text == "":
            target_en_text = en_ebm.messages[en_index].text

        try:
            editable, adaptation = bt.adapt_quartet_text(
                record=baseline_record,
                editable=fr_text,
                target_jp=jp_ebm.messages[jp_index].text,
                target_en=target_en_text,
                quartet_policy=policy,
            )
        except bt.ToolError as exc:
            # English-specific literal replacements (e.g. "installed costumes")
            # legitimately do not occur in the French text; apply French as-is.
            if "expected" in str(exc) and "found 0" in str(exc):
                if fr_text != "":
                    assignments[en_index] = fr_text
                    applied += 1
                else:
                    skipped += 1
                continue
            skipped += 1
            if len(problems) < 8:
                problems.append(f"{logical}[{index}]: {exc}")
            continue
        adaptation_counts[adaptation] += 1
        if editable is None:
            preserved += 1
            continue
        if editable == "":
            skipped += 1
            continue
        assignments[en_index] = editable
        applied += 1

    for en_index, value in assignments.items():
        texts[en_index] = value

    output = bt.serialize_ebm(en_ebm, texts)
    report = {
        "unit": logical,
        "status": "applied" if applied else "skipped",
        "applied": applied,
        "skipped": skipped,
        "preserved_target_template": preserved,
        "adaptations": dict(sorted(adaptation_counts.items())),
        "problems": problems,
    }
    return output, report


def adapt_system(
    quartet_strcombineall: Path,
    fr_system: dict[str, Any],
    baseline_system: dict[str, dict[str, Any]],
    quartet_jp_tables: dict[str, str],
    quartet_en_tables: dict[str, str],
    policy: dict[str, Any],
) -> tuple[bytes, bytes, dict[str, Any]]:
    table = bt.parse_xml_table(quartet_strcombineall)
    index_by_key: dict[str, int] = {}
    for row in table.rows:
        key = row.string_no or row.string_id
        if key is not None:
            index_by_key.setdefault(key, row.index)

    replacements: dict[int, str] = {}
    applied = 0
    skipped = 0
    preserved = 0
    adaptation_counts: Counter = Counter()
    problems: list[str] = []

    for key, fr_text in fr_system["strings"].items():
        index = index_by_key.get(key)
        if index is None:
            skipped += 1
            continue
        baseline_record = baseline_system.get(key)
        target_jp = quartet_jp_tables.get(key, "")
        target_en = quartet_en_tables.get(key, "")
        # Use the official Quartet EN reference when available (see event path).
        official_en = baseline_record.get("en_auxiliary") if baseline_record else None
        if isinstance(official_en, str) and official_en != "":
            target_en = official_en
        if baseline_record is None or target_jp == "" or target_en == "":
            if fr_text != "":
                replacements[index] = fr_text
                applied += 1
            else:
                skipped += 1
            continue
        try:
            editable, adaptation = bt.adapt_quartet_text(
                record=baseline_record,
                editable=fr_text,
                target_jp=target_jp,
                target_en=target_en,
                quartet_policy=policy,
            )
        except bt.ToolError as exc:
            if "expected" in str(exc) and "found 0" in str(exc):
                if fr_text != "":
                    replacements[index] = fr_text
                    applied += 1
                else:
                    skipped += 1
                continue
            skipped += 1
            if len(problems) < 8:
                problems.append(f"{key}: {exc}")
            continue
        adaptation_counts[adaptation] += 1
        if editable is None:
            preserved += 1
            continue
        if editable == "":
            skipped += 1
            continue
        replacements[index] = editable
        applied += 1

    patched = bt.serialize_xml_table(table, replacements)
    encoded = envelope.encode_br_text_envelope(patched)
    if envelope.decode_br_text_envelope(encoded) != patched:
        raise bp.FrenchPatchError("system envelope round-trip self-check failed")

    report = {
        "rows": len(table.rows),
        "rows_changed": applied,
        "skipped": skipped,
        "preserved_target_template": preserved,
        "adaptations": dict(sorted(adaptation_counts.items())),
        "problems": problems,
    }
    return patched, encoded, report


def load_quartet_xml_tables(root: Path) -> dict[str, str]:
    """Map String_No -> text for every individual table in ``root``."""
    result: dict[str, str] = {}
    if not root.is_dir():
        return result
    for path in root.glob("str*.xml"):
        if path.name == "strcombineall.xml":
            continue
        table = bt.parse_xml_table(path)
        for row in table.rows:
            key = row.string_no or row.string_id
            if key is not None:
                result.setdefault(key, row.text)
    return result


def cmd_apply(args: argparse.Namespace) -> int:
    started = time.time()
    game_dir = Path(args.game_dir).expanduser().resolve()
    if not game_dir.is_dir():
        raise bp.FrenchPatchError(f"--game-dir is not a directory: {game_dir}")

    dataset_root = (
        Path(args.dataset).expanduser().resolve()
        if args.dataset
        else bp.default_dataset_dir()
    )
    dataset = bp.load_dataset(dataset_root)
    baseline_db = Path(args.baseline_db).expanduser().resolve() if args.baseline_db else default_baseline_db()
    policy = bt.load_quartet_target_policy(TOOL_DIR.parent)

    print(f"game        : {game_dir}")
    print(f"dataset     : {dataset_root}")
    print(f"baseline db : {baseline_db}")

    gust_pak = bp.find_gust_pak(args.gust_pak)
    print(f"gust_pak    : {gust_pak}")

    install: dict[str, Path] = {}
    for stem, relative in GAME_ARCHIVES.items():
        found = bp.resolve_path_ci(game_dir, relative)
        if found is None:
            raise bp.FrenchPatchError(
                f"{relative} not found — the directory does not look like a "
                f"BLUE REFLECTION Quartet installation."
            )
        install[stem] = found
        print(f"archive     : {found.relative_to(game_dir).as_posix()} "
              f"({bp.human_bytes(found.stat().st_size)})")

    # State / backup locations (separate folder from the 2017 patch).
    state_root = game_dir / STATE_DIR_NAME
    state_file = state_root / "state.json"
    backup_dir = state_root / "backup"
    work_root = Path(args.work_dir).expanduser().resolve() if args.work_dir else state_root / "work"
    if state_file.is_file() and not args.force:
        raise bp.FrenchPatchError(
            f"Quartet French patch already recorded ({state_file}). "
            f"Run 'revert' first, or pass --force."
        )
    if work_root.exists():
        shutil.rmtree(work_root)
    work_root.mkdir(parents=True, exist_ok=True)

    print()
    print("== Extracting ==")
    bp.extract_archive(gust_pak, install["PACK11"], work_root / "PACK11", args.timeout)
    bp.extract_archive(gust_pak, install["PACK12"], work_root / "PACK12", args.timeout)

    print("== Loading baseline ==")
    baseline_events = load_baseline_events(baseline_db)
    baseline_system = load_baseline_system(baseline_db)

    print("== Patching events (PACK11) ==")
    en_root = work_root / "PACK11" / EVENT_EN_ROOT
    jp_root = work_root / "PACK11" / EVENT_JP_ROOT
    event_reports: list[dict[str, Any]] = []
    event_applied = 0
    event_skipped = 0
    event_preserved = 0
    adaptation_totals: Counter = Counter()
    problems: list[str] = []
    for index, (logical, fr_unit) in enumerate(sorted(dataset["units"].items()), 1):
        output, report = adapt_event_unit(
            en_root / logical,
            jp_root / logical,
            fr_unit,
            baseline_events.get(logical),
            policy,
        )
        event_reports.append(report)
        if output is not None:
            (en_root / logical).write_bytes(output)
        event_applied += report["applied"]
        event_skipped += report["skipped"]
        event_preserved += report["preserved_target_template"]
        adaptation_totals.update(report["adaptations"])
        problems.extend(report["problems"])
        if index % 400 == 0:
            print(f"  events: {index}/{len(dataset['units'])} scripts")

    print("== Patching system (PACK12) ==")
    quartet_jp_tables = load_quartet_xml_tables(work_root / "PACK12" / "saves" / "b1" / "text_jp")
    quartet_en_tables = load_quartet_xml_tables(work_root / "PACK12" / "saves" / "b1" / "text_en")
    system_xml, system_envelope, system_report = adapt_system(
        work_root / "PACK12" / SYSTEM_MEMBER,
        dataset["system"],
        baseline_system,
        quartet_jp_tables,
        quartet_en_tables,
        policy,
    )
    (work_root / "PACK12" / SYSTEM_MEMBER).write_bytes(system_xml)
    (work_root / "PACK12" / SYSTEM_ENVELOPE_MEMBER).write_bytes(system_envelope)
    adaptation_totals.update(system_report["adaptations"])
    problems.extend(system_report["problems"])

    print()
    print(f"  events: {event_applied} records applied, {event_skipped} skipped, "
          f"{event_preserved} target-template preserved")
    print(f"  system: {system_report['rows_changed']}/{system_report['rows']} rows changed")
    print(f"  adaptations: {dict(adaptation_totals)}")
    if problems:
        print(f"  problems ({len(problems)}):")
        for problem in problems[:12]:
            print(f"    - {problem}")

    if args.dry_run:
        print()
        print("dry run: nothing was written")
        return 0

    # Repack + verify + commit.
    print()
    print("== Repacking ==")
    results: list[dict[str, Any]] = []
    for stem, mutate_root in (("PACK11", work_root / "PACK11"), ("PACK12", work_root / "PACK12")):
        print(f"  repacking {stem}.PAK ...")
        manifest = next(mutate_root.glob("*.json"))
        rebuilt = bp.repack_archive(gust_pak, manifest, mutate_root, args.timeout)
        verify_dir = work_root / "verify" / stem
        if verify_dir.exists():
            shutil.rmtree(verify_dir)
        verify_dir.mkdir(parents=True)
        verify_manifest, _ = bp.extract_archive(gust_pak, rebuilt, verify_dir, args.timeout)
        # member-by-member verification against the staged tree (the repacked
        # .pak file itself is not an archive member and must be excluded)
        before = {
            name: digest
            for name, digest in bp.archive_inventory(mutate_root, manifest).items()
            if not name.lower().endswith(".pak")
        }
        after = bp.archive_inventory(verify_dir, verify_manifest)
        missing = [n for n in before if n not in after]
        added = [n for n in after if n not in before]
        if missing or added:
            raise bp.FrenchPatchError(f"{stem}: membership changed (missing={missing[:5]}, added={added[:5]})")
        diffs = [n for n in before if before[n] != after[n]]
        # changed members are exactly those we expect to differ (event_en + strcombineall)
        unexpected = [n for n in diffs if not (n.startswith("event/b1/event_en/") or n in (SYSTEM_MEMBER, SYSTEM_ENVELOPE_MEMBER))]
        if unexpected:
            raise bp.FrenchPatchError(f"{stem}: unexpected member changes: {unexpected[:5]}")
        print(f"    {stem}: {len(before)} members verified, {len(diffs)} changed")
        results.append({"stem": stem, "game_archive": install[stem], "rebuilt": rebuilt, "changed": diffs})

    print()
    print("== Committing ==")
    backup_dir.mkdir(parents=True, exist_ok=True)
    state_archives: list[dict[str, Any]] = []
    for result in results:
        game_archive = result["game_archive"]
        original_sha = bp.sha256_file(game_archive)
        backup_path = backup_dir / game_archive.name
        if backup_path.is_file():
            if bp.sha256_file(backup_path) != original_sha:
                raise bp.FrenchPatchError(
                    f"A different backup exists for {game_archive.name}; refusing to overwrite."
                )
        else:
            shutil.copy2(game_archive, backup_path)
            print(f"  backup    {game_archive.name}")
        staged = work_root / f"{result['stem']}.staged.PAK"
        shutil.copy2(result["rebuilt"], staged)
        bp.atomic_replace_file(staged, game_archive)
        print(f"  installed {game_archive.name} ({bp.human_bytes(game_archive.stat().st_size)})")
        state_archives.append(
            {
                "relative": game_archive.relative_to(game_dir).as_posix(),
                "name": game_archive.name,
                "backup": backup_path.relative_to(game_dir).as_posix(),
                "original_bytes": backup_path.stat().st_size,
                "original_sha256": original_sha,
                "patched_bytes": game_archive.stat().st_size,
                "patched_sha256": bp.sha256_file(game_archive),
            }
        )

    state_document = {
        "type": "br_french_quartet_patch_state",
        "format_version": 1,
        "tool_version": QUARTET_TOOL_VERSION,
        "installed_utc": bp.utc_now(),
        "game_dir": str(game_dir),
        "dataset_root": str(dataset_root),
        "dataset_manifest_sha256": bp.sha256_file(bp.dataset_paths(dataset_root)["manifest"]),
        "archives": state_archives,
        "counts": {
            "event_records_applied": event_applied,
            "event_records_skipped": event_skipped,
            "event_target_template_preserved": event_preserved,
            "system_rows_changed": system_report["rows_changed"],
        },
    }
    bp.atomic_write_bytes(state_file, json.dumps(state_document, ensure_ascii=False, sort_keys=True, indent=1).encode("utf-8"))

    if not args.keep_work:
        shutil.rmtree(work_root, ignore_errors=True)

    print()
    print(f"Quartet French patch installed in {game_dir}")
    print(f"  state file : {state_file.relative_to(game_dir).as_posix()}")
    print(f"  backups    : {backup_dir.relative_to(game_dir).as_posix()}")
    print(f"  elapsed    : {time.time() - started:.1f}s")
    print("The b1 partition text is now French; the other partitions are untouched.")
    print("Run 'revert' to restore the original archives.")
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    game_dir = Path(args.game_dir).expanduser().resolve()
    state_file = game_dir / STATE_DIR_NAME / "state.json"
    if not state_file.is_file():
        print(f"No Quartet French patch state recorded in {game_dir}")
        return 1
    state = json.loads(state_file.read_text(encoding="utf-8"))
    print(f"game dir      : {game_dir}")
    print(f"installed utc : {state.get('installed_utc')}")
    print(f"coverage      : {state.get('counts', {}).get('event_records_applied')} event records, "
          f"{state.get('counts', {}).get('system_rows_changed')} system rows")
    problems = 0
    for archive in state.get("archives", []):
        path = game_dir / archive["relative"]
        if not path.is_file():
            print(f"  MISSING   {archive['relative']}")
            problems += 1
            continue
        digest = bp.sha256_file(path)
        if digest == archive["patched_sha256"]:
            print(f"  patched   {archive['relative']}")
        elif digest == archive["original_sha256"]:
            print(f"  original  {archive['relative']} (patch no longer applied)")
            problems += 1
        else:
            print(f"  modified  {archive['relative']} (unknown content)")
            problems += 1
        backup = game_dir / archive["backup"]
        if not backup.is_file() or bp.sha256_file(backup) != archive["original_sha256"]:
            print(f"  WARNING   backup for {archive['name']} missing or changed")
            problems += 1
    return 0 if problems == 0 else 1


def cmd_revert(args: argparse.Namespace) -> int:
    """Take the patch off, without ever undoing a change we did not make.

    Only two situations are handled silently: the archive is exactly the one we
    installed (safe to restore from the backup) or it is already the original one
    (nothing to do).  Anything else - typically a Steam update - is a conflict and
    goes through ``bp.resolve_conflict``: adopt the current files, restore ours
    anyway, or stop without writing.
    """
    game_dir = Path(args.game_dir).expanduser().resolve()
    state_file = game_dir / STATE_DIR_NAME / "state.json"
    if not state_file.is_file():
        raise bp.FrenchPatchError(f"No Quartet French patch state recorded in {game_dir}")
    state = json.loads(state_file.read_text(encoding="utf-8"))
    force = bool(getattr(args, "force", False))
    policy = "restore" if force else getattr(args, "on_conflict", "ask")
    interactive = sys.stdin.isatty() and not getattr(args, "yes", False)
    restored = 0
    adopted: list[str] = []
    for archive in state.get("archives", []):
        relative = archive["relative"]
        name = archive.get("name", relative)
        target = game_dir / relative
        backup = game_dir / archive["backup"]
        original = archive.get("original_sha256")
        current = bp.sha256_file(target) if target.is_file() else None
        if current is not None and original and current == original:
            print(f"  already   {name} (original)")
            continue
        patched = archive.get("patched_sha256")
        if patched is not None and current == patched:
            decision = "restore"
        else:
            decision = bp.resolve_conflict(
                name,
                policy,
                interactive,
                "le fichier du jeu n'est ni la version patchée, ni l'originale sauvegardée",
            )
        if decision == "abort":
            raise bp.FrenchPatchError(
                f"{relative}: arrêt demandé, rien de plus n'a été écrit (l'état est conservé). "
                f"Relancez avec --on-conflict adopt pour garder les fichiers actuels."
            )
        if decision == "adopt":
            print(f"  adopté    {name} (fichier actuel conservé)")
            adopted.append(name)
            continue
        if not backup.is_file():
            if force:
                print(f"  absente   {name} (ignorée)")
                continue
            raise bp.FrenchPatchError(f"Backup missing: {backup}")
        if original and bp.sha256_file(backup) != original:
            if force:
                print(f"  incohérente {name} (ignorée)")
                continue
            raise bp.FrenchPatchError(
                f"Sauvegarde incohérente pour {relative} : elle ne correspond pas à l'original "
                f"enregistré. Rien n'a été écrit ; utilisez --on-conflict adopt pour garder les "
                f"fichiers actuels."
            )
        staged = target.with_name(target.name + ".br_restore")
        shutil.copy2(backup, staged)
        bp.atomic_replace_file(staged, target)
        print(f"  restored  {name}")
        restored += 1
    state_file.unlink(missing_ok=True)
    print(f"Reverted {restored} archive(s) in {game_dir}")
    if adopted:
        print(f"conservé(s) tel quel : {', '.join(adopted)}")
        print("ces fichiers sont la nouvelle référence : réappliquez le patch français par-dessus.")
    return 0


def cmd_forget(args: argparse.Namespace) -> int:
    """Drop the recorded state without touching the game files ("clear the cache").

    The archives currently in the game become the new reference: the patch can no
    longer be reverted, but a re-install and the UNBURGER composition then start
    from what is really on disk.  ``--purge`` also deletes the stored backups.
    """
    game_dir = Path(args.game_dir).expanduser().resolve()
    state_root = game_dir / STATE_DIR_NAME
    state_file = state_root / "state.json"
    backup_dir = state_root / "backup"
    if state_file.is_file():
        state_file.unlink()
        print(f"état supprimé     : {state_file}")
    else:
        print(f"aucun état        : {state_file}")
    if getattr(args, "purge", False) and backup_dir.is_dir():
        count = sum(1 for _ in backup_dir.iterdir())
        shutil.rmtree(backup_dir, ignore_errors=True)
        print(f"sauvegardes       : {count} fichier(s) supprimé(s) ({backup_dir})")
    elif backup_dir.is_dir():
        print(f"sauvegardes       : conservées dans {backup_dir} (--purge pour les supprimer)")
    print("fichiers du jeu   : inchangés")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="br_quartet_french_patch.py",
        description="BLUE REFLECTION Quartet b1-partition French patch",
    )
    parser.add_argument("--version", action="version", version=QUARTET_TOOL_VERSION)
    sub = parser.add_subparsers(dest="command", required=True)

    apply = sub.add_parser("apply", help="patch the Quartet b1 partition")
    apply.add_argument("--game-dir", required=True)
    apply.add_argument("--dataset", default=None)
    apply.add_argument("--baseline-db", default=None)
    apply.add_argument("--gust-pak", default=None)
    apply.add_argument("--work-dir", default=None)
    apply.add_argument("--timeout", type=int, default=1800)
    apply.add_argument("--dry-run", action="store_true")
    apply.add_argument("--force", action="store_true")
    apply.add_argument("--keep-work", action="store_true")
    apply.set_defaults(func=cmd_apply)

    status = sub.add_parser("status", help="report installation state")
    status.add_argument("--game-dir", required=True)
    status.set_defaults(func=cmd_status)

    revert = sub.add_parser("revert", help="restore original archives")
    revert.add_argument("--game-dir", required=True)
    revert.add_argument("--force", action="store_true",
                        help="restore anyway, skipping the backups that cannot be verified")
    revert.add_argument("--on-conflict", choices=bp.CONFLICT_POLICIES, default="ask",
                        help="what to do when an archive changed outside the patch "
                             "(default: ask; adopt keeps the current files)")
    revert.add_argument("--yes", action="store_true",
                        help="never prompt: an unanswered conflict aborts")
    revert.set_defaults(func=cmd_revert)

    forget = sub.add_parser("forget", help="drop the recorded state (game files untouched)")
    forget.add_argument("--game-dir", required=True)
    forget.add_argument("--purge", action="store_true", help="also delete the stored backups")
    forget.set_defaults(func=cmd_forget)

    return parser


def main(argv: Optional[list[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.func(args))
    except (bp.FrenchPatchError, bt.ToolError, envelope.TextEnvelopeError) as exc:
        print(f"\nERROR: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\ninterrupted", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
