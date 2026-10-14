"""Measure how the French texts fit BLUE REFLECTION's message boxes.

In game, a line that is too long is not wrapped at a word boundary: the engine
breaks it in the middle of a word, and the last word of the example below
(``ainés... ?``) is cut in two.  The observed limit is 128 characters on a line,
measured on the NPC chat text

    "Du soda et du pain. Compris ! Je reviens... Attends. Pourquoi c'est moi
     qui vais les chercher ? C'est devenu quoi le respect des"

so a message box holds at most ``LINE_BUDGET`` characters per line, times the
number of lines it can display (``MAX_LINES``).  Everything longer than that is
clipped in game.

Two independent quantities therefore decide whether a text fits:

``budget``
    characters the box keeps on one line (128 as measured in game);
``max_lines``
    lines the box displays before it clips the rest (the value still to be
    confirmed in game; the tool reports every setting so the call can be made
    from the numbers).

The engine only breaks where the text says so (``<CR>``) or when the line
overflows, inside a word: the wrap here copies that behaviour.  The budget is a
character count, not a pixel width, because the game's bitmap font
(``mainfonthd720``/``subfont_hd720``) is a fixed grid, which is what makes a
character budget reproduce the observed cut.
"""

from __future__ import annotations

import argparse
import csv
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Optional

#: Characters the message box keeps on one line before it breaks the line.
LINE_BUDGET = 128

#: Lines a message box can display before the rest is clipped.  The in-game
#: value is still to be confirmed; 2 is the conservative default used in
#: reports so nothing optimistic slips through.
MAX_LINES = 2

#: Line-break token used by the game's text.
BREAK = "<CR>"

#: Values the canonical database uses where the official English is missing or
#: redacted: they carry no length information and must not become a target.
SOURCE_PLACEHOLDERS = {"-", "--", "\uff0d", "\u2014", "\u2013"}


def source_limit(en: str) -> Optional[int]:
    """Length of the official English, or ``None`` for a placeholder/empty value."""
    stripped = (en or "").strip()
    if not stripped or stripped in SOURCE_PLACEHOLDERS:
        return None
    return len(stripped)

#: Categories of the French dataset, in report order.
CATEGORIES = ("dialogue", "messages", "other", "items", "names", "places")

TOOL_DIR = Path(__file__).resolve().parent
DEFAULT_DATASET = TOOL_DIR.parent / "titles" / "blue_reflection" / "translation_fr"
DEFAULT_BASELINE = TOOL_DIR.parent / "titles" / "blue_reflection" / "translation"


@dataclass(frozen=True)
class BudgetItem:
    """One French text, with the source it was translated from."""

    source: str
    key: str
    text: str
    jp: str = ""
    en: str = ""

    @property
    def segmented(self) -> bool:
        return BREAK in self.text

    def wrap(self, budget: int = LINE_BUDGET) -> list[str]:
        """Display lines the engine produces: ``<CR>`` first, then mid-word."""
        out: list[str] = []
        for explicit in self.text.split(BREAK):
            if not explicit:
                out.append("")
                continue
            out.extend(
                explicit[start : start + budget] for start in range(0, len(explicit), budget)
            )
        return out

    def needed_lines(self, budget: int = LINE_BUDGET) -> int:
        return len(self.wrap(budget))

    def chars_over(self, budget: int = LINE_BUDGET, max_lines: int = MAX_LINES) -> int:
        """Characters the box cannot show (0 when the text fits)."""
        lines = self.wrap(budget)
        if len(lines) <= max_lines:
            return 0
        return sum(len(line) for line in lines[max_lines:])

    def fits(self, budget: int = LINE_BUDGET, max_lines: int = MAX_LINES) -> bool:
        return self.chars_over(budget, max_lines) == 0


@dataclass
class BudgetReport:
    budget: int = LINE_BUDGET
    max_lines: int = MAX_LINES
    items: list[BudgetItem] = field(default_factory=list)
    #: When set, a text is judged on its total length instead of the simulated
    #: line breaks (``--max-total 128`` is the rule used for the rework).
    max_total: Optional[int] = None
    #: Skip the texts that are not longer than their official English source:
    #: the source fits the widget, so the translation fits it too.
    cap_by_source: bool = False

    def is_over(self, item: BudgetItem) -> bool:
        limit_by_source = source_limit(item.en)
        if self.cap_by_source and limit_by_source is not None:
            if len(item.text) <= limit_by_source:
                return False
        if self.max_total is not None:
            return len(item.text) > self.max_total
        return not item.fits(self.budget, self.max_lines)

    def over(self) -> list[BudgetItem]:
        return [item for item in self.items if self.is_over(item)]

    def by_source(self) -> dict[str, dict[str, int]]:
        counts: dict[str, dict[str, int]] = {}
        for item in self.items:
            bucket = counts.setdefault(item.source, {"total": 0, "over": 0, "lines": 0})
            bucket["total"] += 1
            bucket["lines"] += item.needed_lines(self.budget)
            if self.is_over(item):
                bucket["over"] += 1
        return counts

    def line_histogram(self) -> dict[int, int]:
        histogram: dict[int, int] = {}
        for item in self.items:
            count = item.needed_lines(self.budget)
            histogram[count] = histogram.get(count, 0) + 1
        return histogram

    def worst(self, limit: int = 10) -> list[BudgetItem]:
        return sorted(
            self.items, key=lambda item: -item.chars_over(self.budget, self.max_lines)
        )[:limit]


# --------------------------------------------------------------------------- #
# dataset loading
# --------------------------------------------------------------------------- #


def _string_sources(baseline: Optional[Path]) -> dict[str, tuple[str, str]]:
    """Map ``String_No`` -> (japanese, official english) from the baseline DB."""
    out: dict[str, tuple[str, str]] = {}
    if baseline is None or not baseline.is_dir():
        return out
    for folder in ("system", "system_quartet_extensions", "system_quartet"):
        base = baseline / folder
        if not base.is_dir():
            continue
        for path in sorted(base.glob("*.json")):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except ValueError:
                continue
            for record in data.get("records") or []:
                key = record.get("string_no")
                if key is None:
                    continue
                out[str(key)] = (
                    record.get("jp") or "",
                    record.get("en_auxiliary") or record.get("en_original") or "",
                )
    return out


def _event_sources(baseline: Optional[Path]) -> dict[str, tuple[str, str]]:
    """Map ``file#message_index`` -> (japanese, english) for event dialogue."""
    out: dict[str, tuple[str, str]] = {}
    base = baseline / "events" if baseline else None
    if base is None or not base.is_dir():
        return out
    for path in sorted(base.rglob("*.ebm.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except ValueError:
            continue
        logical = path.relative_to(base).as_posix()[: -len(".json")]
        records = data.get("records") or data.get("messages") or []
        for index, record in enumerate(records):
            out[f"{logical}#{index}"] = (
                record.get("jp") or "",
                record.get("en_auxiliary") or record.get("en_original") or "",
            )
    return out


def collect_items(
    dataset: Path = DEFAULT_DATASET,
    baseline: Optional[Path] = DEFAULT_BASELINE,
    categories: Iterable[str] = CATEGORIES,
) -> list[BudgetItem]:
    """Every French text of the dataset, tagged with its category and key."""
    import br_translation_xml as tx

    string_sources = _string_sources(baseline)
    event_sources = _event_sources(baseline)
    items: list[BudgetItem] = []
    for category in categories:
        if category == "dialogue":
            for parsed in tx.read_numbered(dataset, "dialogue"):
                for chapter in parsed.get("dialogue") or []:
                    for event in chapter["events"]:
                        for index, message in enumerate(event["messages"]):
                            key = f"{event['file']}#{index}"
                            jp, en = event_sources.get(key, ("", ""))
                            items.append(BudgetItem("dialogue", key, message["text"], jp, en))
            continue
        for parsed in tx.read_numbered(dataset, category):
            for string_no, text in (parsed.get(category) or {}).items():
                jp, en = string_sources.get(str(string_no), ("", ""))
                items.append(BudgetItem(category, str(string_no), text, jp, en))
    return items


# --------------------------------------------------------------------------- #
# reporting
# --------------------------------------------------------------------------- #


def build_report(
    dataset: Path = DEFAULT_DATASET,
    baseline: Optional[Path] = DEFAULT_BASELINE,
    budget: int = LINE_BUDGET,
    max_lines: int = MAX_LINES,
    categories: Iterable[str] = CATEGORIES,
    max_total: Optional[int] = None,
    cap_by_source: bool = False,
) -> BudgetReport:
    return BudgetReport(
        budget=budget,
        max_lines=max_lines,
        items=collect_items(dataset, baseline, categories),
        max_total=max_total,
        cap_by_source=cap_by_source,
    )


def print_summary(report: BudgetReport) -> None:
    if report.max_total is not None:
        print(f"règle: texte de plus de {report.max_total} caractères au total")
    else:
        print(
            f"capacité supposée: {report.budget} caractères x {report.max_lines} ligne(s) "
            f"= {report.budget * report.max_lines} caractères"
        )
    if report.cap_by_source:
        print("filtre: les textes déjà plus courts que l'anglais officiel sont ignorés")
    print(f"textes analysés: {len(report.items)}")
    print("\npar catégorie:")
    print(f"  {'catégorie':<10} {'textes':>7} {'à retoucher':>12} {'lignes':>8}")
    for source, counts in sorted(report.by_source().items()):
        print(f"  {source:<10} {counts['total']:>7} {counts['over']:>12} {counts['lines']:>8}")
    total_over = len(report.over())
    print(f"\ntextes à retoucher: {total_over}")
    if report.max_total is None:
        print("\nlignes nécessaires (découpe automatique en plein mot):")
        for count, total in sorted(report.line_histogram().items()):
            print(f"  {count} ligne(s) : {total}")


def compare_max_lines(report: BudgetReport, values: Iterable[int]) -> None:
    print(f"\ntextes hors budget selon le nombre de lignes affichables (budget {report.budget}):")
    for value in values:
        over = sum(1 for item in report.items if not item.fits(report.budget, value))
        print(f"  {value} ligne(s) : {over} textes à raccourcir")


def write_csv(report: BudgetReport, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            [
                "categorie",
                "cle",
                "longueur",
                "lignes_necessaires",
                "ligne_la_plus_longue",
                "caracteres_en_trop",
                "segments_cr",
                "jp",
                "en",
                "fr",
            ]
        )
        ordered = sorted(
            report.items,
            key=lambda item: (-item.chars_over(report.budget, report.max_lines), item.source),
        )
        for item in ordered:
            lines = item.wrap(report.budget)
            writer.writerow(
                [
                    item.source,
                    item.key,
                    len(item.text),
                    len(lines),
                    max((len(line) for line in lines), default=0),
                    item.chars_over(report.budget, report.max_lines),
                    item.text.count(BREAK) + 1,
                    item.jp,
                    item.en,
                    item.text,
                ]
            )


def write_listing(report: BudgetReport, path: Path, only_over: bool = True) -> int:
    """Human-readable listing of the texts to rewrite, with their sources."""
    path.parent.mkdir(parents=True, exist_ok=True)
    items = report.over() if only_over else report.items
    items = sorted(items, key=lambda item: (-len(item.text), item.source, item.key))
    target = report.max_total if report.max_total is not None else report.budget * report.max_lines
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(
            f"# {len(items)} textes | cible {target} caractères | "
            f"budget {report.budget} x {report.max_lines} ligne(s)\n"
        )
        for item in items:
            goal = target
            limit_by_source = source_limit(item.en)
            if limit_by_source is not None:
                goal = min(goal, limit_by_source)
            handle.write(
                f"\n=== {item.source}:{item.key} | FR {len(item.text)} | "
                f"EN {len(item.en)} | JP {len(item.jp)} | "
                f"cible {goal} | à retirer {max(0, len(item.text) - goal)} car.\n"
            )
            handle.write(f"FR: {item.text}\n")
            if item.en:
                handle.write(f"EN: {item.en}\n")
            if item.jp:
                handle.write(f"JP: {item.jp}\n")
    return len(items)


def write_mapping(report: BudgetReport, path: Path) -> int:
    """JSON skeleton (key -> current text) for a rewrite batch."""
    path.parent.mkdir(parents=True, exist_ok=True)
    mapping = {f"{item.source}:{item.key}": item.text for item in report.over()}
    path.write_text(
        json.dumps(mapping, ensure_ascii=False, indent=1) + "\n", encoding="utf-8"
    )
    return len(mapping)


def _add_budget_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--dataset", default=str(DEFAULT_DATASET))
    parser.add_argument("--baseline", default=str(DEFAULT_BASELINE))
    parser.add_argument("--budget", type=int, default=LINE_BUDGET)
    parser.add_argument("--max-lines", type=int, default=MAX_LINES)
    parser.add_argument("--category", action="append", choices=list(CATEGORIES))
    parser.add_argument(
        "--max-total",
        type=int,
        help="judge on the total length instead of the simulated line breaks",
    )
    parser.add_argument(
        "--cap-by-source",
        action="store_true",
        help="ignore the texts that are not longer than their English source",
    )


def _report_from_args(args: argparse.Namespace) -> BudgetReport:
    return build_report(
        Path(args.dataset),
        None if args.baseline in ("", "none") else Path(args.baseline),
        args.budget,
        args.max_lines,
        tuple(args.category) if args.category else CATEGORIES,
        max_total=args.max_total,
        cap_by_source=args.cap_by_source,
    )


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="BLUE REFLECTION line-budget report")
    sub = parser.add_subparsers(dest="command", required=True)
    report = sub.add_parser("report", help="summarise and optionally export the overflows")
    _add_budget_arguments(report)
    report.add_argument("--csv")
    report.add_argument("--listing", help="write the texts to rewrite, with their sources")
    report.add_argument("--mapping", help="write a JSON batch skeleton to fill in")
    report.add_argument("--top", type=int, default=8)
    check = sub.add_parser(
        "check", help="exit 1 while texts still do not fit (release gate)"
    )
    _add_budget_arguments(check)
    check.add_argument("--top", type=int, default=5)
    args = parser.parse_args(argv)

    if args.command == "check":
        data = _report_from_args(args)
        over = data.over()
        if not over:
            print(f"budget respecte: {len(data.items)} textes")
            return 0
        print_summary(data)
        print("\npremiers textes hors budget:")
        for item in data.worst(args.top):
            print(f"  [{item.source}:{item.key}] FR {len(item.text)} car.")
            print(f"    FR: {item.text[:120]}")
        return 1

    if args.command == "report":
        data = _report_from_args(args)
        print_summary(data)
        if args.max_total is None:
            compare_max_lines(data, (1, 2, 3, 4))
        print("\nplus longs textes:")
        for item in data.worst(args.top):
            lines = item.wrap(data.budget)
            print(
                f"  [{item.source}:{item.key}] {len(item.text)} car. -> {len(lines)} ligne(s), "
                f"{item.chars_over(data.budget, data.max_lines)} car. hors boîte"
            )
            print(f"    FR: {item.text[:150]}")
            if item.en:
                print(f"    EN: {item.en[:150]}")
        if args.csv:
            write_csv(data, Path(args.csv))
            print(f"\nrapport écrit: {args.csv}")
        if args.listing:
            count = write_listing(data, Path(args.listing))
            print(f"liste écrite: {args.listing} ({count} textes)")
        if args.mapping:
            count = write_mapping(data, Path(args.mapping))
            print(f"lot vierge écrit: {args.mapping} ({count} textes)")
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
