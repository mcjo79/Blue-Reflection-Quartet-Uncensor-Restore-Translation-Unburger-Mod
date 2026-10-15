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
import br_line_budget as budget  # noqa: E402
import br_quartet_french_patch as qp  # noqa: E402
import br_rewrite_batch as rewrite  # noqa: E402
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


WRAPPED_DOCUMENT = """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE translation SYSTEM "../translation_fr.dtd">
<translation game="blue_reflection" lang="fr">
    <names>
        <string string_no="1">Hinako</string>
    </names>
    <dialogue>
        <chapter id="aa01">
            <event file="aa01/x.ebm">
                <message msg_id="0" name_id="1">Non, je parlais de nous... Est-ce que nous
                    allons... ?</message>
                <message msg_id="1" name_id="1">Tu n'es pas encore morte, n'est-ce pas ?
                    &lt;CR&gt;Et tu ne veux pas mourir ICI, si ?</message>
            </event>
        </chapter>
    </dialogue>
</translation>
""".encode("utf-8")


class WrapArtifactTests(unittest.TestCase):
    """A re-formatted dataset must never leak stray spaces into the game text.

    Commit 08580c36 re-indented the BLUE REFLECTION French dataset with an XML
    formatter, which wrapped 9223 long text nodes across lines.  The reader used
    to hand those raw newlines and their 20-space indentation to the EBM writer,
    so the dialogs showed bogus line breaks and runs of useless spaces.
    """

    def _write_wrapped(self, tmp: str) -> Path:
        path = Path(tmp) / "dialogue.xml"
        path.write_bytes(WRAPPED_DOCUMENT)
        return path

    def test_reader_collapses_wrap_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            parsed = tx.parse_translation(self._write_wrapped(tmp))
        messages = parsed["dialogue"][0]["events"][0]["messages"]
        self.assertEqual(
            messages[0]["text"], "Non, je parlais de nous... Est-ce que nous allons... ?"
        )
        for message in messages:
            self.assertNotIn("\n", message["text"])
            self.assertNotIn("\t", message["text"])

    def test_reader_keeps_the_cr_token(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            parsed = tx.parse_translation(self._write_wrapped(tmp))
        text = parsed["dialogue"][0]["events"][0]["messages"][1]["text"]
        self.assertEqual(
            text,
            "Tu n'es pas encore morte, n'est-ce pas ? <CR>Et tu ne veux pas mourir ICI, si ?",
        )
        self.assertEqual(text.count("<CR>"), 1)

    def test_string_sections_are_normalised_too(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            parsed = tx.parse_translation(self._write_wrapped(tmp))
        self.assertEqual(parsed["names"], {"1": "Hinako"})

    def test_normalize_file_rewrites_and_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = self._write_wrapped(tmp)
            self.assertEqual(len(tx.find_wrap_artifacts(path)), 2)
            self.assertEqual(tx.normalize_file(path), 2)
            self.assertEqual(tx.find_wrap_artifacts(path), [])
            self.assertEqual(tx.normalize_file(path), 0)
            self.assertIn(
                b'<!DOCTYPE translation SYSTEM "../translation_fr.dtd">', path.read_bytes()
            )
            reparsed = tx.parse_translation(path)
        self.assertTrue(reparsed["dialogue"])

    def test_patched_ebm_text_has_no_control_characters(self) -> None:
        """The end-to-end guarantee: what reaches the game file is clean."""
        with tempfile.TemporaryDirectory() as tmp:
            parsed = tx.parse_translation(self._write_wrapped(tmp))
        messages = parsed["dialogue"][0]["events"][0]["messages"]
        data = make_ebm([m["text"] for m in messages])
        written = [m.text for m in bt.parse_ebm_bytes(data, Path("synthetic.ebm")).messages]
        self.assertEqual(written, [m["text"] for m in messages])
        for text in written:
            self.assertFalse(
                [ch for ch in text if ord(ch) < 32 and ch not in "\n\r\t"],
                f"control character in {text!r}",
            )
        self.assertNotIn("  ", written[0])


class LineBudgetTests(unittest.TestCase):
    """The message box breaks a line inside a word and clips the rest."""

    def test_wrap_breaks_mid_word(self) -> None:
        item = budget.BudgetItem("messages", "1", "a" * 130)
        self.assertEqual(item.wrap(128), ["a" * 128, "aa"])
        self.assertEqual(item.needed_lines(128), 2)

    def test_explicit_cr_starts_a_new_line(self) -> None:
        item = budget.BudgetItem("dialogue", "x#0", "court<CR>" + "b" * 5)
        self.assertEqual(item.wrap(128), ["court", "bbbbb"])

    def test_empty_segments_are_kept(self) -> None:
        item = budget.BudgetItem("dialogue", "x#1", "a<CR><CR>b")
        self.assertEqual(item.wrap(128), ["a", "", "b"])

    def test_chars_over_counts_only_the_clipped_tail(self) -> None:
        item = budget.BudgetItem("messages", "1", "a" * 260)
        # 128 + 128 visible on two lines, the 4 remaining characters are lost
        self.assertEqual(item.chars_over(128, 2), 4)
        self.assertTrue(item.fits(128, 3))
        self.assertFalse(item.fits(128, 2))

    def test_reference_line_is_over_the_observed_budget(self) -> None:
        text = (
            "Du soda et du pain. Compris ! Je reviens... Attends. Pourquoi c'est "
            "moi qui vais les chercher ? C'est devenu quoi le respect des ainés... ?"
        )
        item = budget.BudgetItem("messages", "33882113", text)
        self.assertEqual(len(text), 139)
        self.assertFalse(item.fits(128, 1))
        self.assertTrue(item.fits(139, 1))


class RewriteBatchTests(unittest.TestCase):
    def _dataset(self, tmp: str) -> Path:
        root = Path(tmp)
        tx.write_translation(
            {
                "game": "blue_reflection",
                "lang": "fr",
                "messages": {"33882113": "Du soda et du pain."},
            },
            root / "messages.xml",
        )
        tx.write_translation(
            {
                "game": "blue_reflection",
                "lang": "fr",
                "dialogue": [
                    {
                        "id": "aa01",
                        "events": [
                            {
                                "file": "aa01/x.ebm",
                                "messages": [{"msg_id": 0, "name_id": 1, "text": "Trop long ici"}],
                            }
                        ],
                    }
                ],
            },
            root / "dialogue.xml",
        )
        return root

    def test_applies_a_batch_to_both_categories(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = self._dataset(tmp)
            changed = rewrite.apply_batch(
                {
                    "messages:33882113": "Du soda et du pain. Compris !",
                    "dialogue:aa01/x.ebm#0": "Court",
                },
                root,
            )
            self.assertEqual(changed, {"messages": 1, "dialogue": 1})
            parsed = tx.parse_translation(root / "messages.xml")
            self.assertEqual(parsed["messages"]["33882113"], "Du soda et du pain. Compris !")
            dialogue = tx.parse_translation(root / "dialogue.xml")
            written = dialogue["dialogue"][0]["events"][0]["messages"][0]["text"]
            self.assertEqual(written, "Court")
            # the dataset stays free of wrap artifacts
            self.assertEqual(tx.find_wrap_artifacts(root / "messages.xml"), [])
            self.assertEqual(tx.find_wrap_artifacts(root / "dialogue.xml"), [])

    def test_unknown_key_is_refused_without_writing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = self._dataset(tmp)
            before = (root / "messages.xml").read_bytes()
            with self.assertRaises(rewrite.RewriteError):
                rewrite.apply_batch({"messages:1": "x"}, root)
            self.assertEqual((root / "messages.xml").read_bytes(), before)

    def test_expected_text_guard(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = self._dataset(tmp)
            with self.assertRaises(rewrite.RewriteError):
                rewrite.apply_batch(
                    {"messages:33882113": "nouveau"},
                    root,
                    expect={"messages:33882113": "un autre texte"},
                )

    def test_dry_run_writes_nothing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = self._dataset(tmp)
            before = (root / "messages.xml").read_bytes()
            changed = rewrite.apply_batch({"messages:33882113": "court"}, root, dry_run=True)
            self.assertEqual(changed, {"messages": 1})
            self.assertEqual((root / "messages.xml").read_bytes(), before)


class BudgetCheckTests(unittest.TestCase):
    """The release gate: `br_line_budget.py check` fails while texts overflow."""

    def _dataset(self, tmp: str) -> Path:
        root = Path(tmp)
        tx.write_translation(
            {
                "game": "blue_reflection",
                "lang": "fr",
                "messages": {"1": "a" * 40, "2": "court"},
            },
            root / "messages.xml",
        )
        return root

    def test_check_fails_then_passes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = self._dataset(tmp)
            strict = budget.main(
                [
                    "check",
                    "--dataset",
                    str(root),
                    "--baseline",
                    "none",
                    "--max-total",
                    "30",
                    "--category",
                    "messages",
                ]
            )
            self.assertEqual(strict, 1)
            relaxed = budget.main(
                [
                    "check",
                    "--dataset",
                    str(root),
                    "--baseline",
                    "none",
                    "--max-total",
                    "128",
                    "--category",
                    "messages",
                ]
            )
            self.assertEqual(relaxed, 0)


class BatchStyleTests(unittest.TestCase):
    """The charset rule: never introduce a character the original did not use."""

    def _dataset(self, tmp: str) -> Path:
        root = Path(tmp)
        tx.write_translation(
            {
                "game": "blue_reflection",
                "lang": "fr",
                "other": {
                    "1": "\u3010Degats\u3011 sur un ennemi",
                    "2": "Texte simple",
                },
            },
            root / "other.xml",
        )
        return root

    def test_keeps_brackets_the_original_uses(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = self._dataset(tmp)
            problems = rewrite.check_mapping(
                {"other:1": "\u3010Degats\u3011 sur l'ennemi"},
                root,
                max_total=128,
                cap_by_source=False,
            )
            self.assertEqual(problems, [])

    def test_rejects_new_accented_characters(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = self._dataset(tmp)
            problems = rewrite.check_mapping(
                {"other:2": "Une soiree agreable a Paris"},
                root,
                max_total=128,
                cap_by_source=False,
            )
            self.assertEqual(problems, [])
            problems = rewrite.check_mapping(
                {"other:2": "Une soir\u00e9e agr\u00e9able \u00e0 Paris"},
                root,
                max_total=128,
                cap_by_source=False,
            )
            self.assertEqual(len(problems), 1)
            self.assertIn("font cannot render", problems[0])

    def test_button_tokens_must_survive(self) -> None:
        """The Quartet patch keeps the English when a token disappears."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            tx.write_translation(
                {
                    "game": "blue_reflection",
                    "lang": "fr",
                    "other": {"3": "Ajoutez avec <IM10> puis <IM05>, et <IM05> pour retirer."},
                },
                root / "other.xml",
            )
            kept = rewrite.check_mapping(
                {"other:3": "Ajoutez avec <IM10>, puis <IM05> et <IM05> pour retirer."},
                root,
                max_total=128,
                cap_by_source=False,
            )
            self.assertEqual(kept, [])
            dropped = rewrite.check_mapping(
                {"other:3": "Ajoutez avec <IM10>, puis <IM05> pour retirer."},
                root,
                max_total=128,
                cap_by_source=False,
            )
            self.assertEqual(len(dropped), 1)
            self.assertIn("button tokens changed", dropped[0])


class PackagingBudgetGateTests(unittest.TestCase):
    """`build-bundle` refuses a dataset whose dialogue box would still clip."""

    def _dataset(self, tmp: str, text: str) -> Path:
        root = Path(tmp)
        tx.write_translation(
            {
                "game": "blue_reflection",
                "lang": "fr",
                "dialogue": [
                    {
                        "id": "aa01",
                        "events": [
                            {
                                "file": "aa01/x.ebm",
                                "messages": [{"msg_id": 0, "name_id": 1, "text": text}],
                            }
                        ],
                    }
                ],
            },
            root / "dialogue.xml",
        )
        return root

    def test_short_dataset_passes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = self._dataset(tmp, "Une replique courte.")
            patch.assert_line_budget(root, categories=("dialogue",))

    def test_long_dataset_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = self._dataset(tmp, "a" * 200)
            with self.assertRaises(patch.FrenchPatchError):
                patch.assert_line_budget(root, categories=("dialogue",))


class SourceLimitTests(unittest.TestCase):
    """A redacted English entry must not become a one-character target."""

    def test_placeholder_values_carry_no_target(self) -> None:
        for placeholder in ("-", "--", "", "   ", "\uff0d", "\u2014", "\u2013"):
            self.assertIsNone(budget.source_limit(placeholder), placeholder)

    def test_real_source_gives_its_length(self) -> None:
        self.assertEqual(budget.source_limit("  Hello there  "), 11)

    def test_item_with_placeholder_source_is_judged_on_the_budget(self) -> None:
        report = budget.BudgetReport(
            budget=128, max_lines=2, max_total=128, cap_by_source=True,
            items=[budget.BudgetItem("dialogue", "x#0", "a" * 100, "", "-")],
        )
        self.assertEqual([item.key for item in report.over()], [])
        long_item = budget.BudgetItem("dialogue", "x#1", "a" * 200, "", "-")
        report.items.append(long_item)
        self.assertEqual([item.key for item in report.over()], ["x#1"])


class RevertConflictTests(unittest.TestCase):
    """A revert must never undo a change we did not make (Steam update, other tool).

    Only an archive that is exactly the one the patch installed, or already the
    original, is handled silently.  Everything else goes through the conflict
    policy: adopt the current files, restore ours anyway, or abort.
    """

    PATCHED = b"patched by us"
    ORIGINAL = b"original"
    FOREIGN = b"steam update"

    @staticmethod
    def _ns(game: Path, **kwargs):
        import argparse

        base = dict(game_dir=str(game), force=False, on_conflict="ask", yes=True)
        base.update(kwargs)
        return argparse.Namespace(**base)

    def _second_light(self, tmp: str, current: bytes, *, corrupt_backup=False, hashes=True):
        game = Path(tmp)
        (game / "Data").mkdir()
        (game / "Data/PACK01_03.PAK").write_bytes(current)
        state_dir = game / slpatch.STATE_DIRNAME
        backup_dir = state_dir / slpatch.BACKUP_DIRNAME
        backup_dir.mkdir(parents=True)
        (backup_dir / "PACK01_03.PAK").write_bytes(
            b"tampered" if corrupt_backup else self.ORIGINAL
        )
        state: dict = {"archives": ["Data/PACK01_03.PAK"]}
        if hashes:
            state["original_sha256"] = {
                "Data/PACK01_03.PAK": hashlib.sha256(self.ORIGINAL).hexdigest()
            }
            state["sha256_after"] = {
                "Data/PACK01_03.PAK": hashlib.sha256(self.PATCHED).hexdigest()
            }
        (state_dir / slpatch.STATE_FILE).write_text(json.dumps(state), encoding="utf-8")
        return game, state_dir

    def _quartet(self, tmp: str, current: bytes, *, corrupt_backup=False, hashes=True):
        game = Path(tmp)
        (game / "Data").mkdir()
        target = game / "Data/PACK11.PAK"
        target.write_bytes(current)
        state_root = game / qp.STATE_DIR_NAME
        backup = state_root / "backup"
        backup.mkdir(parents=True)
        (backup / "PACK11.PAK").write_bytes(b"tampered" if corrupt_backup else self.ORIGINAL)
        archive = {
            "relative": "Data/PACK11.PAK",
            "name": "PACK11.PAK",
            "backup": f"{qp.STATE_DIR_NAME}/backup/PACK11.PAK",
        }
        if hashes:
            archive["original_sha256"] = hashlib.sha256(self.ORIGINAL).hexdigest()
            archive["patched_sha256"] = hashlib.sha256(self.PATCHED).hexdigest()
        (state_root / "state.json").write_text(
            json.dumps({"archives": [archive]}), encoding="utf-8"
        )
        return game, state_root

    def _data(self, game: Path) -> bytes:
        return (game / "Data/PACK11.PAK").read_bytes()

    # -- Second Light -------------------------------------------------------

    def test_second_light_restores_our_own_patched_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            game, state_dir = self._second_light(tmp, self.PATCHED)
            slpatch.cmd_revert(self._ns(game))
            self.assertEqual((game / "Data/PACK01_03.PAK").read_bytes(), self.ORIGINAL)
            self.assertFalse((state_dir / slpatch.STATE_FILE).is_file())

    def test_second_light_leaves_a_steam_update_alone_by_default(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            game, state_dir = self._second_light(tmp, self.FOREIGN)
            with self.assertRaises(slpatch.FrenchPatchError):
                slpatch.cmd_revert(self._ns(game))  # non-interactive "ask" => abort
            self.assertEqual((game / "Data/PACK01_03.PAK").read_bytes(), self.FOREIGN)
            self.assertTrue((state_dir / slpatch.STATE_FILE).is_file())

    def test_second_light_adopts_a_steam_update(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            game, state_dir = self._second_light(tmp, self.FOREIGN)
            slpatch.cmd_revert(self._ns(game, on_conflict="adopt"))
            self.assertEqual((game / "Data/PACK01_03.PAK").read_bytes(), self.FOREIGN)
            self.assertFalse((state_dir / slpatch.STATE_FILE).is_file())

    def test_second_light_can_force_the_restore(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            game, _state = self._second_light(tmp, self.FOREIGN)
            slpatch.cmd_revert(self._ns(game, on_conflict="restore"))
            self.assertEqual((game / "Data/PACK01_03.PAK").read_bytes(), self.ORIGINAL)

    def test_second_light_corrupt_backup_is_never_written(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            game, state_dir = self._second_light(tmp, self.PATCHED, corrupt_backup=True)
            with self.assertRaises(slpatch.FrenchPatchError):
                slpatch.cmd_revert(self._ns(game))
            self.assertEqual((game / "Data/PACK01_03.PAK").read_bytes(), self.PATCHED)
            self.assertTrue((state_dir / slpatch.STATE_FILE).is_file())

    def test_second_light_legacy_state_asks_before_restoring(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            game, _state = self._second_light(tmp, self.PATCHED, hashes=False)
            with self.assertRaises(slpatch.FrenchPatchError):
                slpatch.cmd_revert(self._ns(game))
            slpatch.cmd_revert(self._ns(game, force=True))
            self.assertEqual((game / "Data/PACK01_03.PAK").read_bytes(), self.ORIGINAL)

    def test_second_light_missing_state_points_at_forget(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            game = Path(tmp)
            (game / "Data").mkdir()
            with self.assertRaises(slpatch.FrenchPatchError) as ctx:
                slpatch.cmd_revert(self._ns(game))
            self.assertIn("forget", str(ctx.exception))

    # -- Quartet (b1) -------------------------------------------------------

    def test_quartet_restores_our_own_patched_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            game, state_root = self._quartet(tmp, self.PATCHED)
            qp.cmd_revert(self._ns(game))
            self.assertEqual(self._data(game), self.ORIGINAL)
            self.assertFalse((state_root / "state.json").is_file())

    def test_quartet_leaves_a_steam_update_alone_by_default(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            game, state_root = self._quartet(tmp, self.FOREIGN)
            with self.assertRaises(patch.FrenchPatchError):
                qp.cmd_revert(self._ns(game))
            self.assertEqual(self._data(game), self.FOREIGN)
            self.assertTrue((state_root / "state.json").is_file())

    def test_quartet_adopts_a_steam_update(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            game, state_root = self._quartet(tmp, self.FOREIGN)
            qp.cmd_revert(self._ns(game, on_conflict="adopt"))
            self.assertEqual(self._data(game), self.FOREIGN)
            self.assertFalse((state_root / "state.json").is_file())

    def test_quartet_corrupt_backup_is_never_written(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            game, _state = self._quartet(tmp, self.PATCHED, corrupt_backup=True)
            with self.assertRaises(patch.FrenchPatchError):
                qp.cmd_revert(self._ns(game))
            self.assertEqual(self._data(game), self.PATCHED)


class ForgetStateTests(unittest.TestCase):
    """`forget` drops the recorded state and never touches the game files."""

    def test_second_light_forget_keeps_backups_until_purge(self) -> None:
        import argparse

        with tempfile.TemporaryDirectory() as tmp:
            game = Path(tmp)
            (game / "Data").mkdir()
            (game / "Data/PACK01_03.PAK").write_bytes(b"installed")
            state_dir = game / slpatch.STATE_DIRNAME
            backup_dir = state_dir / slpatch.BACKUP_DIRNAME
            backup_dir.mkdir(parents=True)
            (backup_dir / "PACK01_03.PAK").write_bytes(b"original")
            (state_dir / slpatch.STATE_FILE).write_text("{}", encoding="utf-8")

            slpatch.cmd_forget(argparse.Namespace(game_dir=str(game), purge=False))
            self.assertFalse((state_dir / slpatch.STATE_FILE).is_file())
            self.assertTrue(backup_dir.is_dir())
            self.assertEqual((game / "Data/PACK01_03.PAK").read_bytes(), b"installed")

            slpatch.cmd_forget(argparse.Namespace(game_dir=str(game), purge=True))
            self.assertFalse(backup_dir.is_dir())
            self.assertEqual((game / "Data/PACK01_03.PAK").read_bytes(), b"installed")

    def test_quartet_forget_drops_the_state_only(self) -> None:
        import argparse

        with tempfile.TemporaryDirectory() as tmp:
            game = Path(tmp)
            (game / "Data").mkdir()
            (game / "Data/PACK11.PAK").write_bytes(b"installed")
            state_root = game / qp.STATE_DIR_NAME
            (state_root / "backup").mkdir(parents=True)
            (state_root / "backup/PACK11.PAK").write_bytes(b"original")
            (state_root / "state.json").write_text("{}", encoding="utf-8")

            qp.cmd_forget(argparse.Namespace(game_dir=str(game), purge=False))
            self.assertFalse((state_root / "state.json").is_file())
            self.assertTrue((state_root / "backup").is_dir())
            self.assertEqual((game / "Data/PACK11.PAK").read_bytes(), b"installed")


class CommittedDatasetHygieneTests(unittest.TestCase):
    """Guard the shipped datasets: no text node may wrap across lines."""
    DATASETS = (
        "titles/blue_reflection/translation_fr",
        "titles/second_light/translation_fr",
    )

    def test_datasets_contain_no_wrap_artifacts(self) -> None:
        repo_root = TOOL_DIR.parent
        checked = 0
        for relative in self.DATASETS:
            root = repo_root / relative
            if not root.is_dir():
                continue
            for path in sorted(root.rglob("*.xml")):
                checked += 1
                found = tx.find_wrap_artifacts(path)
                if found:
                    self.fail(
                        f"{path.relative_to(repo_root)}: {len(found)} text node(s) wrap "
                        f"across lines (first: {found[0][1][:80]!r}); run "
                        f"`python br_translation_xml.py normalize {relative}`"
                    )
        self.assertGreater(checked, 0, "no dataset files found to check")


if __name__ == "__main__":
    unittest.main(verbosity=2)
