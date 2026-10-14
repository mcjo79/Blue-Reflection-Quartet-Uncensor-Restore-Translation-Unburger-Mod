"""Apply a batch of rewritten French lines to a translation dataset.

The line-budget work rewrites long texts in batches: this tool takes the batch as
a mapping and writes it into the dataset, so every change is reviewable in git
and the batch can be replayed.

Mapping format (JSON object, UTF-8)::

    {
      "messages:33882113": "Du soda et du pain. Compris ! ...",
      "dialogue:aa01/event_message_aa01_010.ebm#3": "..."
    }

The key is ``<category>:<key>`` where ``<key>`` is the ``String_No`` for the
system categories and ``<file>#<index>`` for dialogue, exactly what
``br_line_budget.py report`` prints.

Guards
------
* every key must exist, and the batch is refused as a whole when one does not;
* ``--expect`` can pin the current text (``old == expected``) so a stale batch
  never overwrites a newer revision;
* the file is only rewritten for the categories that actually change, and the
  resulting texts are re-measured automatically with the line budget.
"""

from __future__ import annotations

import argparse
import json
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Optional

TOOL_DIR = Path(__file__).resolve().parent
if str(TOOL_DIR) not in sys.path:
    sys.path.insert(0, str(TOOL_DIR))

import br_line_budget as lb  # noqa: E402
import br_translation_xml as tx  # noqa: E402


class RewriteError(RuntimeError):
    """Raised when a batch cannot be applied safely."""


def parse_key(key: str) -> tuple[str, str]:
    if ":" not in key:
        raise RewriteError(f"malformed key (expected 'category:key'): {key}")
    category, rest = key.split(":", 1)
    if category not in lb.CATEGORIES:
        raise RewriteError(f"unknown category in key: {key}")
    return category, rest


def _dialogue_targets(tree: ET.ElementTree) -> dict[str, ET.Element]:
    out: dict[str, ET.Element] = {}
    dialogue = tree.getroot().find("dialogue")
    if dialogue is None:
        return out
    for chapter in dialogue.findall("chapter"):
        for event in chapter.findall("event"):
            file_name = event.get("file", "")
            for index, message in enumerate(event.findall("message")):
                out[f"{file_name}#{index}"] = message
    return out


def _write(tree: ET.ElementTree, path: Path, prologue: bytes) -> None:
    ET.indent(tree, space="    ")
    path.write_bytes(prologue + ET.tostring(tree.getroot(), encoding="utf-8") + b"\n")


def _prologue(path: Path) -> bytes:
    raw = path.read_bytes()
    match = tx._XML_PROLOGUE.match(raw)
    if match is None:
        raise RewriteError(f"{path}: no XML declaration found")
    return match.group(0)


def apply_batch(
    mapping: dict[str, str],
    dataset: Path = lb.DEFAULT_DATASET,
    expect: Optional[dict[str, str]] = None,
    dry_run: bool = False,
) -> dict[str, int]:
    """Write ``mapping`` into ``dataset``; return a per-category change count."""
    expect = expect or {}
    grouped: dict[str, dict[str, str]] = {}
    for key, text in mapping.items():
        category, rest = parse_key(key)
        grouped.setdefault(category, {})[rest] = text

    changed: dict[str, int] = {}
    for category, updates in grouped.items():
        paths = _category_paths(dataset, category)
        remaining = dict(updates)
        for path in paths:
            if not remaining:
                break
            tree = ET.parse(str(path))
            targets = _targets(tree, category)
            touched = 0
            for key in list(remaining):
                element = targets.get(key)
                if element is None:
                    continue
                new_text = remaining.pop(key)
                old_text = element.text or ""
                pinned = expect.get(f"{category}:{key}")
                if pinned is not None and old_text != pinned:
                    raise RewriteError(
                        f"{category}:{key}: expected {pinned[:60]!r}, found {old_text[:60]!r}"
                    )
                if old_text == new_text:
                    continue
                element.text = new_text
                touched += 1
            if touched and not dry_run:
                _write(tree, path, _prologue(path))
            if touched:
                changed[category] = changed.get(category, 0) + touched
        if remaining:
            raise RewriteError(
                f"{len(remaining)} key(s) not found in the {category} files: "
                f"{sorted(remaining)[:5]}"
            )
    return changed


def _category_paths(dataset: Path, category: str) -> list[Path]:
    if category == "dialogue":
        return [dataset / name for name in _numbered_names(dataset, "dialogue")]
    return [dataset / name for name in _numbered_names(dataset, category)]


def _numbered_names(root: Path, stem: str) -> list[str]:
    names = [f"{stem}.xml"] + [f"{stem}_{i}.xml" for i in range(1, 10_000)]
    return [name for name in names if (root / name).is_file()]


def _targets(tree: ET.ElementTree, category: str) -> dict[str, ET.Element]:
    if category == "dialogue":
        return _dialogue_targets(tree)
    section = tree.getroot().find(category)
    if section is None:
        return {}
    return {element.get("string_no", ""): element for element in section.findall("string")}


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Apply a rewritten-lines batch")
    parser.add_argument("mapping", help="JSON mapping file")
    parser.add_argument("--dataset", default=str(lb.DEFAULT_DATASET))
    parser.add_argument("--budget", type=int, default=lb.LINE_BUDGET)
    parser.add_argument("--max-lines", type=int, default=lb.MAX_LINES)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--strict", action="store_true", help="fail when a text still overflows")
    args = parser.parse_args(argv)

    # utf-8-sig: a batch edited in Notepad may carry a BOM.
    mapping = json.loads(Path(args.mapping).read_text(encoding="utf-8-sig"))
    dataset = Path(args.dataset)
    try:
        changed = apply_batch(mapping, dataset, dry_run=args.dry_run)
    except RewriteError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print(f"lots appliqués: {changed}")
    if args.dry_run:
        print("dry run: rien n'a été écrit")
        return 0

    report = lb.build_report(dataset, budget=args.budget, max_lines=args.max_lines)
    lb.print_summary(report)
    offending = {f"{item.source}:{item.key}" for item in report.over()}
    touched = set(mapping)
    still = sorted(touched & offending)
    print(f"\ntextes du lot encore hors budget: {len(still)}")
    for key in still[:10]:
        print(f"  {key}")
    if args.strict and still:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
