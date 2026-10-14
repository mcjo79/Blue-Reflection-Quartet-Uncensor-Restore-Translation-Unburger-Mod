"""Unit tests for the French translation patch tooling.

Covers the BLUE REFLECTION text-envelope codec (including a cross-checked
golden vector produced by the native Go reference implementation) and the
event/system patching helpers.  These tests use only the Python standard
library and synthetic inputs; they do not require the proprietary French
release or ``gust_pak``.
"""

from __future__ import annotations

import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path

TOOL_DIR = Path(__file__).resolve().parents[1]
if str(TOOL_DIR) not in sys.path:
    sys.path.insert(0, str(TOOL_DIR))

import br_french_cleanup as cleanup  # noqa: E402
import br_french_patch as patch  # noqa: E402
import br_text_envelope as envelope  # noqa: E402
import br_text_tool as bt  # noqa: E402
import br_translation_categories as categories  # noqa: E402
import br_second_light_french_patch as slpatch  # noqa: E402
import br_translation_xml as tx  # noqa: E402

# Cross-implementation golden vector: the 132-byte plaintext below, encoded by
# the Go reference (Blue_Reflection_Patcher/internal/br1rebuild), must hash to
# this value.  It pins the Python port to the native implementation.
GOLDEN_PLAINTEXT = (
    '<?xml version="1.0" encoding="SHIFT-JIS"?>\r\n'
    '<Root>\r\n'
    '    <str Text="D\u00e9fi sportif ! \u2014 test \u00ab\u00e9\u00bb" String_No="1572865"/>\r\n'
    '</Root>\r\n'
)
GOLDEN_SHA256 = "f9ae9d05b2277e5856789af44b0df3486a0c0bb497a82cafe0e95c318bd40b2e"


def make_ebm(texts: list[str], msg_ids: list[int] | None = None, name_ids: list[int] | None = None) -> bytes:
    msg_ids = msg_ids if msg_ids is not None else list(range(len(texts)))
    name_ids = name_ids if name_ids is not None else [i + 1 for i in range(len(texts))]
    messages = [
        bt.EBMMessage(
            index=index,
            type=2,
            voice_id=10 + index,
            unknown1=0,
            name_id=name_ids[index],
            extra_id=0,
            expr_id=12,
            duration1=(),
            msg_id=msg_ids[index],
            unknown2=0,
            text=text,
            duration2=(),
        )
        for index, text in enumerate(texts)
    ]
    ebm = bt.EBMFile(
        path=Path("synthetic.ebm"),
        signed_count=len(messages),
        d1_len=0,
        d2_len=0,
        messages=tuple(messages),
        extra_data=b"",
        raw=b"",
    )
    return bt.serialize_ebm(ebm, [message.text for message in messages])


class TextEnvelopeTests(unittest.TestCase):
    def test_roundtrip(self) -> None:
        for size in (14, 15, 255, 256, 257, 511, 512, 513, 4096, 8192):
            data = bytes((byte * 7 + size) % 256 for byte in range(size))
            encoded = envelope.encode_br_text_envelope(data)
            self.assertEqual(envelope.decode_br_text_envelope(encoded), data)
            self.assertEqual(len(encoded) % 4, 0)

    def test_golden_vector(self) -> None:
        encoded = envelope.encode_br_text_envelope(GOLDEN_PLAINTEXT.encode("utf-8"))
        self.assertEqual(hashlib.sha256(encoded).hexdigest(), GOLDEN_SHA256)
        self.assertEqual(
            envelope.decode_br_text_envelope(encoded).decode("utf-8"),
            GOLDEN_PLAINTEXT,
        )

    def test_rejects_unknown_version(self) -> None:
        with self.assertRaises(envelope.TextEnvelopeError):
            envelope.decode_br_text_envelope(b"\x00" * 64)

    def test_rejects_short_payload(self) -> None:
        with self.assertRaises(envelope.TextEnvelopeError):
            envelope.encode_br_text_envelope(b"short")


class EventPatchTests(unittest.TestCase):
    def _write(self, data: bytes) -> str:
        path = Path(tempfile.mkdtemp()) / "event_message_test.ebm"
        path.write_bytes(data)
        return str(path)

    def test_aligned_apply(self) -> None:
        template = make_ebm(["Hello", "World", "Done"])
        unit = {
            "path": "test.ebm",
            "records": [[0, 0, 1, "Bonjour"], [1, 1, 2, "Monde"], [2, 2, 3, "Fini"]],
        }
        patched, report = patch.patch_event_unit(
            Path(self._write(template)), unit, allow_structural_mismatch=False
        )
        self.assertIsNotNone(patched)
        self.assertEqual(report["status"], "applied")
        self.assertEqual(report["applied"], 3)

        reparsed = bt.parse_ebm_bytes(patched, Path("x.ebm"))
        self.assertEqual([message.text for message in reparsed.messages], ["Bonjour", "Monde", "Fini"])
        # Metadata must be preserved exactly.
        self.assertEqual([message.msg_id for message in reparsed.messages], [0, 1, 2])
        self.assertEqual([message.name_id for message in reparsed.messages], [1, 2, 3])

    def test_structural_mismatch_skipped_by_default(self) -> None:
        template = make_ebm(["A", "B", "C"])
        unit = {"path": "test.ebm", "records": [[0, 0, 1, "X"], [1, 1, 2, "Y"]]}
        patched, report = patch.patch_event_unit(
            Path(self._write(template)), unit, allow_structural_mismatch=False
        )
        self.assertIsNone(patched)
        self.assertEqual(report["status"], "structural_mismatch")

    def test_slot_mismatch_skipped(self) -> None:
        template = make_ebm(["A", "B"])
        # Slot 1 claims msg_id 999 (wrong); only slot 0 should be applied.
        unit = {"path": "test.ebm", "records": [[0, 0, 1, "X"], [1, 999, 2, "Y"]]}
        patched, report = patch.patch_event_unit(
            Path(self._write(template)), unit, allow_structural_mismatch=True
        )
        self.assertIsNotNone(patched)
        self.assertEqual(report["applied"], 1)
        self.assertEqual(report["skipped"], 1)
        reparsed = bt.parse_ebm_bytes(patched, Path("x.ebm"))
        self.assertEqual([message.text for message in reparsed.messages], ["X", "B"])


class SystemPatchTests(unittest.TestCase):
    XML = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        "<Root>\n"
        '    <str Text="Hello" String_No="1"/>\n'
        '    <str Text="World" String_No="2"/>\n'
        '    <str String_No="3"/>\n'
        "</Root>\n"
    )

    def test_merge_and_envelope(self) -> None:
        path = Path(tempfile.mkdtemp()) / "strcombineall.xml"
        path.write_bytes(self.XML.encode("utf-8"))
        system = {
            "member": patch.SYSTEM_MEMBER,
            "strings": {"1": "Bonjour", "2": "Monde", "4": "Absent"},
        }
        patched, encoded, report = patch.patch_system_member(path, system)
        self.assertEqual(report["rows_changed"], 2)
        self.assertEqual(report["dataset_keys_absent_from_target"], 1)

        table = bt.parse_xml_table_bytes(patched, path)
        by_key = {row.string_no: row.text for row in table.rows}
        self.assertEqual(by_key["1"], "Bonjour")
        self.assertEqual(by_key["2"], "Monde")
        self.assertEqual(by_key["3"], "")
        # Rows without a Text attribute stay untouched.
        self.assertNotIn('String_No="3"/', "Bonjour")

        self.assertEqual(envelope.decode_br_text_envelope(encoded), patched)


class CleanupTests(unittest.TestCase):
    def test_terminology_normalisation(self) -> None:
        cases = [
            ("C'est un Sephiroth.", "C'est un Sephira."),
            ("la proximité du Sephiroth", "la proximité du Sephira"),
            ("Ce Sephiroth a battu en retraite.", "Ce Sephira a battu en retraite."),
            ("les Sephiroth et tout le reste", "les Sephirot et tout le reste"),
            ("tous les Sephira", "tous les Sephirot"),
            ("des Sephira", "des Sephirot"),
            ("Cette Sephira... On peut vraiment la vaincre... ?", "Ce Sephira... On peut vraiment le vaincre... ?"),
            ("Une Sephira... Est-ce possible de la vaincre ?", "Un Sephira... Est-ce possible de le vaincre ?"),
            ("La Sephira va bouger.", "Le Sephira va bouger."),
            ("un combat contre un Sephirot", "un combat contre un Sephira"),
            ("Le Sephirot va bouger.", "Le Sephira va bouger."),
        ]
        for source, expected in cases:
            result, _ = cleanup.apply_cleanup(source)
            self.assertEqual(result, expected, source)
            self.assertEqual(cleanup.validate_cleanup(result), [], result)

    def test_grammar_fixes(self) -> None:
        cases = [
            ("j'ai le droit à un vœu exaucé", "j'ai droit à un vœu exaucé"),
            ("Tu affroentes les Sephirot", "Tu affrontes les Sephirot"),
            ("à combattre Sephirot", "à combattre les Sephirot"),
        ]
        for source, expected in cases:
            result, _ = cleanup.apply_cleanup(source)
            self.assertEqual(result, expected, source)

    def test_no_false_positive_on_canonical_forms(self) -> None:
        # Already-canonical text must be untouched.
        canonical = (
            "Un Sephira... Le Sephira est apparu. "
            "Les Sephirot et le Common. Anti-Sephirot +1."
        )
        result, applied = cleanup.apply_cleanup(canonical)
        self.assertEqual(result, canonical)
        self.assertEqual(applied, [])


class AccentFallbackTests(unittest.TestCase):
    def test_replaces_unsupported_accents(self) -> None:
        source = "Où ça ? École, très chère sœur : « Bonjour » — cœur, île."
        result, replaced = cleanup.apply_accent_fallback(source)
        for forbidden in ("\u00f9", "\u00e7", "\u00e8", "\u00e0", "\u00c9",
                          "\u0153", "\u00ab", "\u00bb", "\u00ee", "\u2014"):
            self.assertNotIn(forbidden, result)
        self.assertIn("ou", result)
        self.assertIn("ca", result)
        self.assertIn("Ecole", result)
        self.assertGreater(replaced, 0)

    def test_keeps_characters_present_in_official_font(self) -> None:
        source = "l'\u00e9t\u00e9 \u2026 l'\u00e9t\u00e9"  # é, ', …
        result, replaced = cleanup.apply_accent_fallback(source)
        self.assertEqual(result, source)  # é, …, ' all kept
        self.assertEqual(replaced, 0)


class SecondLightMojibakeTests(unittest.TestCase):
    def test_undoes_mojibake(self) -> None:
        source = (
            "O\u00e1 \u00fda ? Peut-\u00dftre. S\u00f6r, gr\u00e4ce \u00e0 toi. "
            "Plut\u00f3t. M\u00dfme. \u00a4E\u00a4videmment, \u00a4A\u00a4 mon avis."
        )
        expected = (
            "O\u00f9 \u00e7a ? Peut-\u00eatre. S\u00fbr, gr\u00e2ce \u00e0 toi. "
            "Plut\u00f4t. M\u00eame. \u00c9videmment, \u00c0 mon avis."
        )
        result, replaced = cleanup.fix_brsl_mojibake(source)
        self.assertEqual(result, expected)
        self.assertEqual(replaced, 9)

    def test_mojibake_then_accent_fallback_is_ascii(self) -> None:
        source = "O\u00e1 \u00fda ? Peut-\u00dftre. \u00a4E\u00a4videmment."
        mojibake_fixed, _ = cleanup.fix_brsl_mojibake(source)
        result, _ = cleanup.apply_accent_fallback(mojibake_fixed)
        self.assertEqual(result, "Ou ca ? Peut-etre. Evidemment.")

    def test_keeps_legitimate_french(self) -> None:
        # é, à, è, ï are already correct in the source and must not be mangled.
        source = "l'\u00e9t\u00e9, d\u00e9j\u00e0, tr\u00e8s, ha\u00efr"
        result, replaced = cleanup.fix_brsl_mojibake(source)
        self.assertEqual(result, source)
        self.assertEqual(replaced, 0)


class TranslationXmlTests(unittest.TestCase):
    def _sample(self) -> dict:
        return {
            "game": "blue_reflection",
            "lang": "fr",
            "meta": {"release": "test"},
            "names": {"327681": "Hinako"},
            "places": {"100": "Toit"},
            "items": {"200": "Potion"},
            "dialogue": [
                {
                    "id": "aa01",
                    "events": [
                        {
                            "file": "aa01/x.ebm",
                            "messages": [
                                {"msg_id": 4294967295, "name_id": 125, "text": ""},
                                {"msg_id": 0, "name_id": 124, "text": "Elle est <CR>la. <&>"},
                            ],
                        }
                    ],
                }
            ],
        }

    def test_round_trip(self) -> None:
        data = self._sample()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "translation.xml"
            tx.write_translation(data, path)
            parsed = tx.parse_translation(path)
        self.assertEqual(parsed["game"], "blue_reflection")
        self.assertEqual(parsed["lang"], "fr")
        self.assertEqual(parsed["meta"], {"release": "test"})
        self.assertEqual(parsed["names"], {"327681": "Hinako"})
        self.assertEqual(parsed["places"], {"100": "Toit"})
        self.assertEqual(parsed["items"], {"200": "Potion"})
        chapter = parsed["dialogue"][0]
        self.assertEqual(chapter["id"], "aa01")
        messages = chapter["events"][0]["messages"]
        self.assertEqual(messages[0]["msg_id"], 4294967295)
        self.assertEqual(messages[0]["name_id"], 125)
        self.assertEqual(messages[0]["text"], "")
        self.assertEqual(messages[1]["text"], "Elle est <CR>la. <&>")

    def test_writes_one_category_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "names.xml"
            tx.write_translation(
                {"game": "br", "lang": "fr", "names": {"1": "Hinako"}}, path
            )
            parsed = tx.parse_translation(path)
        self.assertEqual(parsed["names"], {"1": "Hinako"})
        self.assertNotIn("dialogue", parsed)

    def test_sanitizes_illegal_control_chars(self) -> None:
        data = self._sample()
        data["dialogue"][0]["events"][0]["messages"].append(
            {"msg_id": 4294967295, "text": "a\x1cb"}
        )
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "translation.xml"
            tx.write_translation(data, path)
            parsed = tx.parse_translation(path)
        text = parsed["dialogue"][0]["events"][0]["messages"][2]["text"]
        self.assertEqual(text, "a<0x1C>b")

    def test_read_numbered_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            tx.write_translation(
                {"game": "br", "lang": "fr", "names": {"1": "A"}}, root / "names.xml"
            )
            tx.write_translation(
                {"game": "br", "lang": "fr", "names": {"2": "B"}}, root / "names_1.xml"
            )
            tx.write_translation(
                {"game": "br", "lang": "fr", "names": {"3": "C"}}, root / "names_2.xml"
            )
            parsed = tx.read_numbered(root, "names")
            merged = {}
            for p in parsed:
                merged.update(p.get("names", {}))
        self.assertEqual(merged, {"1": "A", "2": "B", "3": "C"})
        self.assertEqual(len(parsed), 3)


class TranslationCategoriesTests(unittest.TestCase):
    def test_group_events_by_chapter(self) -> None:
        events = [
            {"file": "ce01/a.ebm", "messages": []},
            {"file": "event_en/aa01/b.ebm", "messages": []},
            {"file": "ce01/c.ebm", "messages": []},
        ]
        chapters = categories.group_events_by_chapter(events)
        self.assertEqual([c["id"] for c in chapters], ["aa01", "ce01"])
        by_id = {c["id"]: len(c["events"]) for c in chapters}
        self.assertEqual(by_id, {"aa01": 1, "ce01": 2})

    def test_categorize_strings(self) -> None:
        # Synthetic repo DB with one table per category.
        with tempfile.TemporaryDirectory() as tmp:
            repo_db = Path(tmp)
            (repo_db / "system").mkdir()
            for table, string_nos in (
                ("str_chara_name.xml", ["1", "2"]),
                ("str_school_map_name.xml", ["3"]),
                ("str_item_name.xml", ["4"]),
                ("str_ui.xml", ["5"]),
            ):
                (repo_db / "system" / f"{table}.json").write_text(
                    json.dumps(
                        {
                            "records": [
                                {"string_no": sn} for sn in string_nos
                            ]
                        }
                    ),
                    encoding="utf-8",
                )
            strings = {"1": "A", "2": "B", "3": "C", "4": "D", "5": "E", "6": "F"}
            result = categories.categorize_strings(strings, repo_db)
        self.assertEqual(result["names"], {"1": "A", "2": "B"})
        self.assertEqual(result["places"], {"3": "C"})
        self.assertEqual(result["items"], {"4": "D"})
        # "5" (str_ui) and "6" (unmapped) both fall into "other".
        self.assertEqual(result["other"], {"5": "E", "6": "F"})

    def test_category_for_table_messages(self) -> None:
        self.assertEqual(categories.category_for_table("str_npc_s62_mess.xml"), "messages")
        self.assertEqual(categories.category_for_table("str_chat_msg.xml"), "messages")
        self.assertEqual(categories.category_for_table("str_talk_matter.xml"), "messages")
        self.assertEqual(categories.category_for_table("str_item_name.xml"), "items")
        self.assertEqual(categories.category_for_table("str_ui.xml"), "other")
        self.assertEqual(categories.category_for_table(None), "other")


class SecondLightEventPatchTests(unittest.TestCase):
    NO_ID = 0xFFFFFFFF

    def _patch(self, data: bytes, records: list[list]) -> tuple[int, list[str]]:
        path = Path(tempfile.mkdtemp()) / "event_message_test.ebm"
        path.write_bytes(data)
        changed, _skipped = slpatch.patch_event_file(path, records)
        return changed, [m.text for m in bt.parse_ebm(path).messages]

    def test_identifier_less_written_when_layout_matches(self) -> None:
        data = make_ebm(["A", "B", "C"], [5, self.NO_ID, self.NO_ID], [1, 2, 2])
        records = [[0, 5, 1, "a"], [1, self.NO_ID, 2, "b"], [2, self.NO_ID, 2, "c"]]
        self.assertEqual(self._patch(data, records), (3, ["a", "b", "c"]))

    def test_repeated_msg_id_written_when_layout_matches(self) -> None:
        data = make_ebm(["A", "B"], [7, 7], [1, 2])
        records = [[0, 7, 1, "a"], [1, 7, 2, "b"]]
        self.assertEqual(self._patch(data, records), (2, ["a", "b"]))

    def test_repeated_msg_id_left_alone_when_layout_differs(self) -> None:
        data = make_ebm(["A", "B"], [7, 7], [1, 2])
        records = [[0, 7, 1, "a"], [1, 7, 3, "b"]]
        self.assertEqual(self._patch(data, records), (0, ["A", "B"]))

    def test_identifier_less_left_alone_when_layout_differs(self) -> None:
        data = make_ebm(["A", "B", "C"], [5, self.NO_ID, self.NO_ID], [1, 2, 2])
        # the database order differs from the game file: never guess
        records = [[0, 5, 1, "a"], [1, self.NO_ID, 3, "x"], [2, self.NO_ID, 2, "c"]]
        self.assertEqual(self._patch(data, records), (1, ["a", "B", "C"]))


class SecondLightSourceTests(unittest.TestCase):
    REL = "Data/PACK01_03.PAK"

    def _setup(self, installed: bytes, backup: bytes | None, written: bytes | None):
        game = Path(tempfile.mkdtemp())
        (game / "Data").mkdir()
        (game / self.REL).write_bytes(installed)
        state: dict = {}
        if backup is not None:
            backup_dir = game / slpatch.STATE_DIRNAME / slpatch.BACKUP_DIRNAME
            backup_dir.mkdir(parents=True)
            (backup_dir / "PACK01_03.PAK").write_bytes(backup)
            state = {"sha256_after": {self.REL: hashlib.sha256(written or b"").hexdigest()}}
        return game, state

    def test_first_install_uses_installed_archive(self) -> None:
        game, state = self._setup(b"orig", None, None)
        self.assertEqual(slpatch.pristine_source(game, self.REL, state), (game / self.REL, False))

    def test_our_patched_archive_is_repatched_from_backup(self) -> None:
        game, state = self._setup(b"patched", b"orig", b"patched")
        source, refresh = slpatch.pristine_source(game, self.REL, state)
        self.assertEqual((source.read_bytes(), refresh), (b"orig", False))

    def test_steam_replaced_archive_becomes_new_original(self) -> None:
        game, state = self._setup(b"steam update", b"orig", b"patched")
        source, refresh = slpatch.pristine_source(game, self.REL, state)
        self.assertEqual((source, refresh), (game / self.REL, True))

    def test_verified_archive_matching_backup_needs_no_refresh(self) -> None:
        game, state = self._setup(b"orig", b"orig", b"patched")
        self.assertEqual(slpatch.pristine_source(game, self.REL, state), (game / self.REL, False))


if __name__ == "__main__":
    unittest.main(verbosity=2)
