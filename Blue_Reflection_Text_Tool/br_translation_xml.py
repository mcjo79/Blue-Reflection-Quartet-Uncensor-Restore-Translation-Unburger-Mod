"""Read and write the French translation XML files (shared DTD schema).

The translation is stored as one XML file per category, each conforming to
``translation_fr.dtd``.  This module converts between those XML documents and a
plain Python mapping so the patch tools never deal with XML parsing details.

Data model
----------
A full translation mapping is::

    {
        "game": "blue_reflection",
        "lang": "fr",
        "meta": {"release": ..., "generated_utc": ...},
        "names":  {"327681": "Hinako", ...},      # character/creature names
        "places": {"...": "...", ...},            # location names
        "items":  {"...": "...", ...},            # object/crafting names
        "other":  {"...": "...", ...},            # everything else
        "dialogue": [                             # events grouped by chapter
            {
                "id": "aa01",
                "events": [
                    {
                        "file": "aa01/event_message_aa01_010.ebm",
                        "messages": [
                            {"msg_id": 0, "name_id": 124, "text": "..."},
                        ],
                    },
                ],
            },
        ],
    }

Each of ``names``/``places``/``items``/``other`` is a ``{String_No: text}``
mapping and may be absent.  ``dialogue`` is a list of chapter objects and may
be absent.  ``msg_id``/``name_id`` are integers or ``None``.
"""

from __future__ import annotations

import os
import re
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

TOOL_DIR = Path(__file__).resolve().parent
DTD_FILENAME = "translation_fr.dtd"
DTD_PATH = TOOL_DIR / DTD_FILENAME

ROOT_TAG = "translation"
STRING_SECTIONS = ("names", "places", "items", "messages", "other")


# XML 1.0 forbids most C0 control characters.  The game text normally uses the
# literal "<CR>" sequence for line breaks, but a stray raw control byte (for
# example the file separator 0x1C in a Second Light voice-continuation stub)
# must not make the document ill-formed.
_XML_ILLEGAL_CONTROL = set(range(0x20)) - {0x09, 0x0A, 0x0D}

# The games encode line breaks with the literal "<CR>" token and their source
# text contains no raw newline, so any newline (with its surrounding
# indentation) is a formatting artifact and collapses to a single space.
_NEWLINE_RUN = re.compile(r"\s*\n\s*")

# Text-bearing elements of the translation DTD.
_TEXT_TAGS = ("message", "string")

# Optional XML declaration + DOCTYPE prologue, preserved verbatim when a
# dataset file is rewritten so its DTD reference is not lost.
_XML_PROLOGUE = re.compile(rb"^\s*<\?xml[^>]*\?>\s*(?:<!DOCTYPE[^>]*>\s*)?")


def normalize_wrap_artifacts(text: str) -> str:
    """Collapse the line wrapping an indented dataset document introduces.

    The XML files are kept indented for manual proofreading, so a long message
    is stored across several lines::

        <message msg_id="1" name_id="3">Bonjour, je suis
                        revenue.</message>

    The line break and the indentation after it are pure formatting.  The games
    break lines with the literal ``<CR>`` token, so a raw newline must never
    reach the game text: written verbatim into an ``.ebm`` dialog, it shows up
    as a bogus line break followed by a run of stray spaces.
    """
    return _NEWLINE_RUN.sub(" ", text)


def _text(node: ET.Element) -> str:
    return normalize_wrap_artifacts(node.text or "")


def _sanitize_text(text: str) -> str:
    """Normalise formatting artifacts and XML-illegal control characters."""
    text = normalize_wrap_artifacts(text)
    if all(ord(ch) not in _XML_ILLEGAL_CONTROL for ch in text):
        return text
    return "".join(
        f"<0x{ord(ch):02X}>" if ord(ch) in _XML_ILLEGAL_CONTROL else ch
        for ch in text
    )


def _parse_optional_int(value: str | None) -> int | None:
    if value is None:
        return None
    return int(value, 0)


def _parse_string_section(root: ET.Element, section: str) -> dict[str, str]:
    strings: dict[str, str] = {}
    section_el = root.find(section)
    if section_el is not None:
        for str_el in section_el.findall("string"):
            strings[str_el.get("string_no", "")] = _text(str_el)
    return strings


def _parse_dialogue(root: ET.Element) -> list[dict[str, Any]]:
    dialogue_el = root.find("dialogue")
    if dialogue_el is None:
        return []
    chapters: list[dict[str, Any]] = []
    for chapter_el in dialogue_el.findall("chapter"):
        events: list[dict[str, Any]] = []
        for event_el in chapter_el.findall("event"):
            messages: list[dict[str, Any]] = []
            for msg_el in event_el.findall("message"):
                messages.append(
                    {
                        "msg_id": _parse_optional_int(msg_el.get("msg_id")),
                        "name_id": _parse_optional_int(msg_el.get("name_id")),
                        "text": _text(msg_el),
                    }
                )
            events.append({"file": event_el.get("file", ""), "messages": messages})
        chapters.append({"id": chapter_el.get("id", ""), "events": events})
    return chapters


def parse_translation(path: Path | str) -> dict[str, Any]:
    """Parse a translation XML document into the Python data model."""
    tree = ET.parse(str(path))
    root = tree.getroot()
    if root.tag != ROOT_TAG:
        raise ValueError(f"root element is <{root.tag}>, expected <{ROOT_TAG}>")

    data: dict[str, Any] = {
        "game": root.get("game", ""),
        "lang": root.get("lang", ""),
        "meta": {},
    }

    meta_el = root.find("meta")
    if meta_el is not None:
        data["meta"] = dict(meta_el.attrib)

    for section in STRING_SECTIONS:
        strings = _parse_string_section(root, section)
        if strings:
            data[section] = strings

    dialogue = _parse_dialogue(root)
    if dialogue:
        data["dialogue"] = dialogue

    return data


def _doctype(dtd_ref: str) -> str:
    return f'<!DOCTYPE {ROOT_TAG} SYSTEM "{dtd_ref}">'


def _default_dtd_ref(path: Path | str) -> str:
    try:
        ref = os.path.relpath(DTD_PATH, Path(path).resolve().parent)
    except ValueError:
        # Different drives (e.g. a temporary directory on another volume):
        # fall back to an absolute path so the document stays well-formed.
        ref = str(DTD_PATH)
    return ref.replace("\\", "/")


def _append_string_section(root: ET.Element, section: str, strings: dict[str, str]) -> None:
    if not strings:
        return
    section_el = ET.SubElement(root, section)
    for string_no, text in strings.items():
        str_el = ET.SubElement(section_el, "string", {"string_no": string_no})
        str_el.text = _sanitize_text(text)


def _append_dialogue(root: ET.Element, dialogue: list[dict[str, Any]]) -> None:
    if not dialogue:
        return
    dialogue_el = ET.SubElement(root, "dialogue")
    for chapter in dialogue:
        chapter_el = ET.SubElement(dialogue_el, "chapter", {"id": chapter["id"]})
        for event in chapter["events"]:
            event_el = ET.SubElement(chapter_el, "event", {"file": event["file"]})
            for message in event["messages"]:
                attrs: dict[str, str] = {}
                if message.get("msg_id") is not None:
                    attrs["msg_id"] = str(message["msg_id"])
                if message.get("name_id") is not None:
                    attrs["name_id"] = str(message["name_id"])
                msg_el = ET.SubElement(event_el, "message", attrs)
                msg_el.text = _sanitize_text(message["text"])


def write_translation(
    data: dict[str, Any],
    path: Path | str,
    dtd_ref: str | None = None,
) -> None:
    """Write the data model as a DTD-referencing XML document.

    Only the sections present in ``data`` are written, so this also serves to
    write one category file at a time.
    """
    root = ET.Element(ROOT_TAG, {"game": data["game"], "lang": data["lang"]})

    meta = data.get("meta")
    if meta:
        ET.SubElement(root, "meta", {k: str(v) for k, v in meta.items()})

    for section in STRING_SECTIONS:
        _append_string_section(root, section, data.get(section) or {})
    _append_dialogue(root, data.get("dialogue") or [])

    tree = ET.ElementTree(root)
    if dtd_ref is None:
        dtd_ref = _default_dtd_ref(path)
    body = ET.tostring(root, encoding="utf-8")
    xml_bytes = (
        b'<?xml version="1.0" encoding="UTF-8"?>\n'
        + _doctype(dtd_ref).encode("utf-8")
        + b"\n"
        + body
    )
    Path(path).write_bytes(xml_bytes)


def read_numbered(root: Path, stem: str) -> list[dict[str, Any]]:
    """Parse ``<stem>.xml``, ``<stem>_1.xml``, ``<stem>_2.xml`` ... in order.

    Returns the parsed data model for every numbered file that exists.  Used to
    load a category (or the dialogue) that has been split into several files.
    """
    parsed: list[dict[str, Any]] = []
    names = [f"{stem}.xml"] + [f"{stem}_{i}.xml" for i in range(1, 10_000)]
    for name in names:
        path = root / name
        if not path.is_file():
            break
        parsed.append(parse_translation(path))
    return parsed


# --------------------------------------------------------------------------- #
# Dataset hygiene
#
# Rewriting a dataset file with an XML formatter (or an editor's "format
# document") wraps long text nodes across lines.  The reader now collapses that
# wrapping, but the committed data must stay clean too: the raw newline and the
# indentation after it inflate the string, and both the file diff and the
# proofreading view then contain noise that is not in the translation.  These
# helpers normalise a file in place and let the test suite (or a release check)
# fail when the artifacts come back.
# --------------------------------------------------------------------------- #


def iter_text_nodes(root: ET.Element):
    """Yield the DTD's text-bearing elements (``<message>``/``<string>``)."""
    for element in root.iter():
        if element.tag in _TEXT_TAGS:
            yield element


def find_wrap_artifacts(path: Path | str) -> list[tuple[str, str]]:
    """Return ``(tag, text)`` for every text node that still wraps across lines."""
    root = ET.parse(str(path)).getroot()
    found: list[tuple[str, str]] = []
    for element in iter_text_nodes(root):
        text = element.text or ""
        if "\n" in text:
            found.append((element.tag, text))
    return found


def normalize_file(path: Path | str, write: bool = True) -> int:
    """Collapse wrap artifacts in ``path``; return the number of fixed nodes.

    The XML prologue (declaration + DOCTYPE reference) is preserved verbatim and
    the element tree is re-indented, so section order and every attribute stay
    untouched.  Nothing is written when the file is already clean.
    """
    path = Path(path)
    raw = path.read_bytes()
    match = _XML_PROLOGUE.match(raw)
    if match is None:
        raise ValueError(f"{path}: no XML declaration found")
    root = ET.fromstring(raw)
    changed = 0
    for element in iter_text_nodes(root):
        text = element.text or ""
        fixed = normalize_wrap_artifacts(text)
        if fixed != text:
            element.text = fixed
            changed += 1
    if write and changed:
        ET.indent(root, space="    ")
        path.write_bytes(match.group(0) + ET.tostring(root, encoding="utf-8") + b"\n")
    return changed


def _resolve_targets(paths: list[str]) -> list[Path]:
    targets: list[Path] = []
    for raw in paths:
        path = Path(raw)
        if path.is_dir():
            targets.extend(sorted(path.rglob("*.xml")))
        else:
            targets.append(path)
    return targets


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(
        description="Check or normalise translation dataset formatting"
    )
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("check", "normalize"):
        child = sub.add_parser(name)
        child.add_argument("paths", nargs="+", help="XML files or dataset folders")
        if name == "normalize":
            child.add_argument(
                "--dry-run",
                action="store_true",
                help="report what would change without writing",
            )
    args = parser.parse_args(argv)

    problems = 0
    for path in _resolve_targets(args.paths):
        if args.command == "check":
            found = find_wrap_artifacts(path)
            if found:
                problems += len(found)
                print(f"{path}: {len(found)} text node(s) with wrap artifacts")
                for tag, text in found[:3]:
                    print(f"    <{tag}> {text[:120]!r}")
            continue
        changed = normalize_file(path, write=not args.dry_run)
        problems += changed
        verb = "would normalise" if args.dry_run else "normalised"
        if changed:
            print(f"{path}: {verb} {changed} text node(s)")

    if args.command == "check":
        if problems:
            print(f"\n{problems} text node(s) still contain raw line breaks")
            return 1
        print("clean: no wrap artifacts in the checked files")
        return 0
    print(f"{problems} text node(s) {'to fix' if args.dry_run else 'fixed'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
