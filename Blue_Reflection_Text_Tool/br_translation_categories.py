"""Categorize the BLUE REFLECTION French system strings into named groups.

The game combines every ``str_*.xml`` table into a single ``strcombineall.xml``
keyed by ``String_No``.  This module maps each ``String_No`` back to its source
table (using the official translation database under ``titles/.../translation``)
and groups the French strings into the user-facing categories:

* ``names``  - character / creature names;
* ``places`` - location names;
* ``items``  - object / crafting names;
* ``other``  - everything else (UI, battle, tutorial, NPC messages, ...).

The event dialogue is grouped by chapter (the event folder: ``aa01`` prologue,
``ce01`` chapter 1, ...).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

# category -> source table names (without the trailing ".json").
SYSTEM_CATEGORY_TABLES: dict[str, tuple[str, ...]] = {
    "names": (
        "str_chara_name.xml",
        "str_monster_name.xml",
        "str_event_chara_name.xml",
        "str_race_name.xml",
    ),
    "places": (
        "str_school_map_name.xml",
        "str_school_map_comment.xml",
        "str_fm_info_area.xml",
        "str_library_map.xml",
    ),
    "items": (
        "str_item_name.xml",
        "str_craft_text.xml",
        "str_treasure_name.xml",
        "str_fragment_name.xml",
        "str_costume.xml",
        "str_item_category.xml",
        "str_item_kind.xml",
    ),
}

STRING_CATEGORIES = ("names", "places", "items", "messages", "other")

# category -> output file name.
CATEGORY_FILES = {
    "names": "names.xml",
    "places": "places.xml",
    "items": "items.xml",
    "messages": "messages.xml",
    "other": "other.xml",
    "dialogue": "dialogue.xml",
}

# Spoken dialogue tables (NPC messages, chat, conversation topics) are grouped
# into "messages" by table-name pattern rather than listed exhaustively.
MESSAGE_TABLE_PREFIXES = ("str_npc_",)
MESSAGE_TABLE_NAMES = {
    "str_chat_msg.xml",
    "str_chat_group.xml",
    "str_chat_group_info.xml",
    "str_talk_matter.xml",
}


def table_for_string_no(repo_db_dir: Path) -> dict[str, str]:
    """Map every ``String_No`` to its source table name (``str_*.xml``)."""
    mapping: dict[str, str] = {}
    system_dir = repo_db_dir / "system"
    if not system_dir.is_dir():
        return mapping
    for table_file in system_dir.glob("*.json"):
        table = table_file.stem  # e.g. "str_chara_name.xml"
        try:
            data = json.loads(table_file.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        for record in data.get("records", []):
            string_no = record.get("string_no")
            if string_no is not None:
                mapping[str(string_no)] = table
    return mapping


def categorize_strings(
    strings: dict[str, str],
    repo_db_dir: Path,
) -> dict[str, dict[str, str]]:
    """Split ``{String_No: text}`` into names/places/items/messages/other."""
    table_of = table_for_string_no(repo_db_dir)
    categories: dict[str, dict[str, str]] = {cat: {} for cat in STRING_CATEGORIES}
    for string_no, text in strings.items():
        table = table_of.get(str(string_no))
        categories[category_for_table(table)][string_no] = text
    return categories


def category_for_table(table: str | None) -> str:
    """Map a source table name to its user-facing category."""
    if table is None:
        return "other"
    for candidate, tables in SYSTEM_CATEGORY_TABLES.items():
        if table in tables:
            return candidate
    if table.startswith(MESSAGE_TABLE_PREFIXES) or table in MESSAGE_TABLE_NAMES:
        return "messages"
    return "other"


def group_events_by_chapter(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Group event units by the folder that contains them (``aa01``, ``ce01``, ...)."""
    chapters: dict[str, list[dict[str, Any]]] = {}
    for event in events:
        chapter = Path(event["file"]).parent.name
        chapters.setdefault(chapter, []).append(event)
    return [
        {"id": chapter_id, "events": chapter_events}
        for chapter_id, chapter_events in sorted(chapters.items())
    ]
