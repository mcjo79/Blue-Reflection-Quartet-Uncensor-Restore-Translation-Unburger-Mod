"""Extract the French BLUE REFLECTION Second Light translation.

Reads the event .ebm members unpacked from the fan installer's ``PACK01.pak``
(BRSL_fr-FR_V1.02.beta.2_auto_install.exe), undoes the installer's accent
mojibake and applies the font-compatibility accent fallback, then writes a
clean French dataset alongside the official translation DB.

The beta only localises the ``aa01`` + ``cm01``-``cm03`` event groups (61
files).  The system tables are data (not translated text), so only events are
extracted here.
"""

from __future__ import annotations

import argparse
import json
import struct
import sys
from pathlib import Path

TOOL_DIR = Path(__file__).resolve().parent
if str(TOOL_DIR) not in sys.path:
    sys.path.insert(0, str(TOOL_DIR))

import br_french_cleanup as cleanup  # noqa: E402
import br_translation_categories as categories  # noqa: E402
import br_translation_xml as tx  # noqa: E402

EVENT_GROUPS = ("aa01", "cm01", "cm02", "cm03", "cm04")


def parse_ebm_messages(data: bytes) -> list[tuple[int, str]]:
    """Parse Second Light EBM messages, probing the duration2 word count.

    The record header is ``type, voice_id, unknown1, name_id, extra_id,
    expr_id, msg_id, unknown2, msg_length`` (9 words), followed by the UTF-8
    NUL-terminated string and then ``d2`` trailing duration words.
    """
    signed_count = struct.unpack_from("<i", data, 0)[0]
    count = abs(signed_count)
    for d2 in (0, 1, 2):
        messages: list[tuple[int, str]] = []
        offset = 4
        ok = True
        for _ in range(count):
            if offset + 36 > len(data):
                ok = False
                break
            vals = struct.unpack_from("<9I", data, offset)
            msg_length = vals[8]
            if msg_length == 0 or msg_length > 4096:
                ok = False
                break
            string_end = offset + 36 + msg_length
            duration_end = string_end + d2 * 4
            if duration_end > len(data):
                ok = False
                break
            raw = data[offset + 36:string_end]
            if not raw or raw[-1] != 0 or b"\0" in raw[:-1]:
                ok = False
                break
            try:
                text = raw[:-1].decode("utf-8")
            except UnicodeDecodeError:
                ok = False
                break
            messages.append((vals[6], text))
            offset = duration_end
        if ok and len(messages) == count:
            return messages
    raise ValueError("cannot determine EBM record layout")


def clean_text(text: str) -> tuple[str, int]:
    """Undo mojibake then reduce non-font-safe accents to ASCII."""
    text, n1 = cleanup.fix_brsl_mojibake(text)
    text, n2 = cleanup.apply_accent_fallback(text)
    return text, n1 + n2


def extract_events(event_root: Path) -> tuple[dict[str, int], list[dict[str, object]]]:
    events: list[dict[str, object]] = []
    files_seen = 0
    messages_seen = 0
    replaced_total = 0
    for group in EVENT_GROUPS:
        group_dir = event_root / group
        if not group_dir.is_dir():
            continue
        for ebm_path in sorted(group_dir.rglob("*.ebm")):
            rel = f"event_en/{group}/{ebm_path.name}"
            messages = parse_ebm_messages(ebm_path.read_bytes())
            files_seen += 1
            cleaned_messages: list[dict[str, object]] = []
            for msg_id, text in messages:
                clean, replaced = clean_text(text)
                replaced_total += replaced
                messages_seen += 1
                cleaned_messages.append({"msg_id": msg_id, "text": clean})
            events.append({"file": rel, "messages": cleaned_messages})
    return (
        {"files": files_seen, "messages": messages_seen, "replaced": replaced_total},
        events,
    )


def cmd_extract(args: argparse.Namespace) -> int:
    event_root = Path(args.events_dir)
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    stats, events = extract_events(event_root)

    dialogue = categories.group_events_by_chapter(events)
    tx.write_translation(
        {
            "game": "second_light",
            "lang": "fr",
            "meta": {
                "release": "BRSL_fr-FR_V1.02.beta.2_auto_install.exe",
                "scope": "events only (aa01 + cm01-cm03)",
            },
            "dialogue": dialogue,
        },
        out_dir / "dialogue.xml",
    )

    manifest = {
        "game": "second_light",
        "release": "BRSL_fr-FR_V1.02.beta.2_auto_install.exe",
        "scope": "events only (aa01 + cm01-cm03)",
        "event_files": stats["files"],
        "messages": stats["messages"],
        "accent_chars_replaced": stats["replaced"],
    }
    (out_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    print(
        f"extracted {stats['files']} events, {stats['messages']} messages, "
        f"{stats['replaced']} accent characters mapped"
    )
    print(f"wrote {out_dir / 'dialogue.xml'}")
    print(f"wrote {out_dir / 'manifest.json'}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Extract the French Second Light translation into a dataset."
    )
    sub = parser.add_subparsers(dest="command", required=True)
    extract = sub.add_parser("extract", help="extract events from an unpacked PACK01")
    extract.add_argument("--events-dir", required=True, help="event/event_en directory")
    extract.add_argument("--out", required=True, help="output dataset directory")
    extract.set_defaults(func=cmd_extract)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
