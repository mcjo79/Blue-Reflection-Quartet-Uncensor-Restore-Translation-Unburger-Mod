#!/usr/bin/env python3
"""Interactive installer for the BLUE REFLECTION French translation patch.

Detects the supported games (the 2017 standalone and the Quartet "b1"
partition), then lets the user choose an action per game:

* install the French translation, or
* restore the original English.

The two underlying patch tools keep their own state and backups, so switching
between French and English is always possible and reversible.

Usage
-----
``python br_french_installer.py``
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Optional

TOOL_DIR = Path(__file__).resolve().parent
if str(TOOL_DIR) not in sys.path:
    sys.path.insert(0, str(TOOL_DIR))

import br_french_patch as bp  # noqa: E402  (2017 standalone)
import br_quartet_french_patch as qp  # noqa: E402  (Quartet b1)
import br_second_light_french_patch as slp  # noqa: E402  (Second Light)


class Target:
    def __init__(self, key: str, label: str, markers: list[str], state_dir: str) -> None:
        self.key = key
        self.label = label
        self.markers = markers
        self.state_dir = state_dir


TARGETS: list[Target] = [
    Target(
        "2017",
        "BLUE REFLECTION (2017)",
        ["DATA/PACK01.PAK", "DATA/PACK02_1.PAK"],
        ".br_french_patch",
    ),
    Target(
        "quartet",
        "BLUE REFLECTION Quartet (partition b1)",
        ["Data/PACK11.PAK", "Data/PACK12.PAK"],
        ".br_french_quartet_patch",
    ),
    Target(
        "second_light",
        "BLUE REFLECTION Second Light",
        ["Data/PACK01.PAK", "Data/PACK02.PAK"],
        ".br_french_second_light",
    ),
    Target(
        "second_light_quartet",
        "BLUE REFLECTION Quartet (partition b4 : Second Light)",
        ["Data/PACK01_03.PAK", "Data/PACK02_03.PAK"],
        ".br_french_second_light",
    ),
]


def _marker_present(game_dir: Path, marker: str) -> bool:
    return bp.resolve_path_ci(game_dir, marker) is not None


def identify_games(game_dir: Path) -> list[Target]:
    """Return every target whose markers all exist under ``game_dir``.

    A Quartet folder matches both the b1 (first game) and b4 (Second Light)
    targets.
    """
    return [
        target
        for target in TARGETS
        if all(_marker_present(game_dir, marker) for marker in target.markers)
    ]


def steam_common_roots() -> list[Path]:
    roots: list[Path] = []
    home = Path.home()
    candidates = [
        home / ".steam" / "steam" / "steamapps" / "common",
        home / ".local" / "share" / "Steam" / "steamapps" / "common",
        home / "snap" / "steam" / "common" / ".local" / "share" / "Steam" / "steamapps" / "common",
        Path("C:/Program Files (x86)/Steam/steamapps/common"),
        Path("C:/Program Files/Steam/steamapps/common"),
    ]
    for drive in "ABCDEFGHIJKLMNOPQRSTUVWXYZ":
        candidates.extend(
            [
                Path(f"{drive}:/Steam/steamapps/common"),
                Path(f"{drive}:/SteamLibrary/steamapps/common"),
            ]
        )
    for candidate in candidates:
        try:
            if candidate.is_dir():
                roots.append(candidate)
        except OSError:
            continue
    return roots


def detect_games() -> dict[str, Path]:
    found: dict[str, Path] = {}
    remaining = list(TARGETS)
    for root in steam_common_roots():
        try:
            children = list(root.iterdir())
        except OSError:
            continue
        for child in children:
            if not child.is_dir():
                continue
            for target in remaining[:]:
                if all(_marker_present(child, marker) for marker in target.markers):
                    found[target.key] = child
                    remaining.remove(target)
        if not remaining:
            break
    return found


def is_patched(target: Target, game_dir: Path) -> bool:
    return (game_dir / target.state_dir / "state.json").is_file()


def run_apply(target: Target, game_dir: Path, force: bool) -> None:
    if target.key == "2017":
        args = argparse.Namespace(
            game_dir=str(game_dir), dataset=None, gust_pak=None, work_dir=None,
            timeout=1800, dry_run=False, force=force, keep_work=False,
            with_movies=False, movies_dir=None, allow_structural_mismatch=False,
        )
        bp.cmd_apply(args)
    elif target.key in ("second_light", "second_light_quartet"):
        args = argparse.Namespace(
            game_dir=str(game_dir), dataset=None, gust_pak=None,
            work_dir=None, timeout=3600,
        )
        slp.cmd_apply(args)
    else:
        args = argparse.Namespace(
            game_dir=str(game_dir), dataset=None, baseline_db=None, gust_pak=None,
            work_dir=None, timeout=1800, dry_run=False, force=force, keep_work=False,
        )
        qp.cmd_apply(args)


def run_revert(target: Target, game_dir: Path) -> None:
    args = argparse.Namespace(game_dir=str(game_dir), force=False)
    if target.key == "2017":
        bp.cmd_revert(args)
    elif target.key in ("second_light", "second_light_quartet"):
        slp.cmd_revert(args)
    else:
        qp.cmd_revert(args)


def prompt_choice(prompt: str, minimum: int, maximum: int) -> int:
    while True:
        try:
            value = input(prompt).strip()
            if value == "":
                continue
            number = int(value)
        except (EOFError, KeyboardInterrupt):
            raise
        except ValueError:
            print("  Entrez un numéro.")
            continue
        if minimum <= number <= maximum:
            return number
        print(f"  Entrez un numéro entre {minimum} et {maximum}.")


def yes_no(prompt: str) -> bool:
    while True:
        try:
            answer = input(prompt).strip().lower()
        except (EOFError, KeyboardInterrupt):
            raise
        if answer in {"o", "oui", "y", "yes", "1"}:
            return True
        if answer in {"n", "non", "no", "0", ""}:
            return False


def manual_entry() -> Optional[tuple[Target, Path]]:
    while True:
        try:
            raw = input("  Dossier du jeu (ou vide pour annuler) : ").strip()
        except (EOFError, KeyboardInterrupt):
            raise
        if raw == "":
            return None
        game_dir = Path(raw).expanduser().resolve()
        if not game_dir.is_dir():
            print("  Dossier introuvable.")
            continue
        targets = identify_games(game_dir)
        if not targets:
            print("  Ce dossier ne correspond à aucune version prise en charge.")
            continue
        if len(targets) == 1:
            return targets[0], game_dir
        print("  Ce dossier contient plusieurs jeux :")
        for index, candidate in enumerate(targets, 1):
            print(f"    [{index}] {candidate.label}")
        return targets[prompt_choice("  Votre choix : ", 1, len(targets)) - 1], game_dir


def action_menu(target: Target, game_dir: Path) -> None:
    patched = is_patched(target, game_dir)
    status = "français installé" if patched else "anglais (original)"
    print()
    print(f"--- {target.label} ---")
    print(f"  Dossier : {game_dir}")
    print(f"  État    : {status}")
    print()
    print("  1. Installer la traduction française")
    print("  2. Restaurer l'anglais (d'origine)")
    print("  0. Retour")

    choice = prompt_choice("  Votre choix : ", 0, 2)
    print()
    if choice == 0:
        return

    if choice == 1:
        force = False
        if patched:
            if not yes_no("  Le français est déjà installé. Réinstaller ? (o/N) : "):
                return
            force = True
        _dispatch(lambda: run_apply(target, game_dir, force))
    elif choice == 2:
        if not patched:
            print("  L'anglais est déjà en place (aucun patch enregistré).")
            return
        if not yes_no("  Restaurer l'anglais d'origine ? (o/N) : "):
            return
        _dispatch(lambda: run_revert(target, game_dir))


def _dispatch(action) -> None:
    try:
        action()
    except Exception as exc:  # noqa: BLE001 — report any tool error and return
        print(f"\nErreur : {exc}")
        print("Aucune modification n'a été appliquée en cas d'échec.")


QUARTET_KEYS = ("quartet", "second_light_quartet")


def install_all(entries: list[tuple[Target, Path]], assume_yes: bool = False) -> int:
    """Apply the French patch to Quartet only (b1 + b4). Older games are just sources."""
    entries = [e for e in entries if e[0].key in QUARTET_KEYS]
    if not entries:
        print("Quartet non détecté.")
        return 1
    print("Quartet à traduire :")
    for target, game_dir in entries:
        print(f"  - {target.label}  [{game_dir}]")
    if not assume_yes and not yes_no("Installer le français sur Quartet (b1 + b4) ? (o/N) : "):
        return 0
    failures = 0
    for target, game_dir in entries:
        print(f"\n=== {target.label} ===")
        force = is_patched(target, game_dir)
        try:
            run_apply(target, game_dir, force)
        except Exception as exc:  # noqa: BLE001
            failures += 1
            print(f"Erreur : {exc}")
    print(f"\nTerminé : {len(entries) - failures}/{len(entries)} jeu(x) traduit(s).")
    return 1 if failures else 0


def main() -> int:
    run_all = "--all" in sys.argv[1:]
    print()
    print("=" * 62)
    print("  Patch de traduction française — BLUE REFLECTION")
    print("=" * 62)

    found = detect_games()
    entries: list[tuple[Target, Path]] = []
    for target in TARGETS:
        game_dir = found.get(target.key)
        if game_dir is not None:
            entries.append((target, game_dir))

    if run_all:
        return install_all(entries, assume_yes="--yes" in sys.argv[1:])

    while True:
        print()
        print("Jeux détectés :")
        for index, (target, game_dir) in enumerate(entries, 1):
            status = "français" if is_patched(target, game_dir) else "anglais"
            print(f"  [{index}] {target.label}  ({status})")
        if not entries:
            print("  (aucun jeu détecté automatiquement)")
        manual_number = len(entries) + 1
        print(f"  [{manual_number}] Entrer un dossier de jeu manuellement")
        all_number = manual_number + 1
        print(f"  [{all_number}] Installer tout Quartet (b1 + b4)")
        print("  [0] Quitter")

        choice = prompt_choice("Votre choix : ", 0, all_number)
        print()
        if choice == 0:
            break
        if choice == all_number:
            install_all(entries)
            continue
        if choice == manual_number:
            manual = manual_entry()
            if manual is not None:
                action_menu(*manual)
            continue
        target, game_dir = entries[choice - 1]
        action_menu(target, game_dir)

    print("Au revoir.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("\ninterrompu")
        raise SystemExit(130)
