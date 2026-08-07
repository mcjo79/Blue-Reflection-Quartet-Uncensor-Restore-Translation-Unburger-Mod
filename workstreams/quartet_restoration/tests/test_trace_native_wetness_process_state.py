from __future__ import annotations

import ctypes
import importlib.util
import json
import os
import tempfile
import unittest
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[3]
TOOL_PATH = PROJECT / "workstreams/quartet_restoration/164_trace_native_wetness_process_state.py"
spec = importlib.util.spec_from_file_location("stage164", TOOL_PATH)
assert spec and spec.loader
TOOL = importlib.util.module_from_spec(spec)
spec.loader.exec_module(TOOL)


def m(start: int, size: int, perms: str = "rw-p", path: str = "[heap]"):
    return TOOL.MapRow(start, start + size, perms, 0, "00:00", 0, path)


def occurrence(token: str, state: str, addr: int, mapping, *, context="c", page="p"):
    return {
        "token_label": token,
        "token_text": "pc00_scl" if state == "dry" else "pc00_scl_w",
        "token_state": state,
        "primary_token": True,
        "encoding": "ascii",
        "address": addr,
        "address_hex": f"0x{addr:x}",
        "mapping_index": 0,
        "mapping_key": TOOL.mapping_key(mapping),
        "mapping_class": "anonymous",
        "mapping_permissions": mapping.perms,
        "mapping_path_basename": mapping.path,
        "mapping_path_sha256": "h",
        "mapping_relative_offset": addr - mapping.start,
        "context_sha256": context,
        "page_sha256": page,
    }


def pointer(site: int, target, mapping, *, context="ctx"):
    return {
        "site_address": site,
        "site_address_hex": f"0x{site:x}",
        "site_mapping_index": 0,
        "site_mapping_key": TOOL.mapping_key(mapping),
        "site_mapping_class": "anonymous",
        "site_mapping_permissions": mapping.perms,
        "site_mapping_path_basename": mapping.path,
        "site_mapping_path_sha256": "h",
        "site_mapping_relative_offset": site - mapping.start,
        "site_context_sha256": context,
        "target_token_label": target["token_label"],
        "target_token_state": target["token_state"],
        "target_encoding": target["encoding"],
        "target_address": target["address"],
        "target_address_hex": target["address_hex"],
        "classification": "exact_address_pointer_reference_candidate_not_object_semantics",
    }


class Stage164Tests(unittest.TestCase):
    def test_parse_maps_and_normalization(self):
        rows = TOOL.parse_maps_text("1000-3000 rw-p 00000000 00:00 0 [heap]\n4000-5000 r--p 00000000 08:01 12 /tmp/Game/Test.exe\n")
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0].size, 0x2000)
        self.assertEqual(TOOL.mapping_class(rows[0], Path("/tmp/Game")), "anonymous")
        self.assertEqual(TOOL.mapping_class(rows[1], Path("/tmp/Game")), "game")
        ev = TOOL.map_evidence_row(1, rows[1], Path("/tmp/Game"))
        self.assertEqual(ev["path_basename"], "Test.exe")
        self.assertNotIn("/tmp/Game", json.dumps(ev))

    def test_dry_token_does_not_alias_wet_substring(self):
        mapping = m(0x1000, 0x1000)
        data = b"xx pc00_scl_w yy pc00_scl zz"
        rows = TOOL.scan_buffer_for_tokens(data, mapping.start, mapping, 0, Path("/game"))
        dry = [r for r in rows if r["token_label"] == "pc00_school_dry" and r["encoding"] == "ascii"]
        wet = [r for r in rows if r["token_label"] == "pc00_school_wet" and r["encoding"] == "ascii"]
        self.assertEqual(len(dry), 1)
        self.assertEqual(len(wet), 1)

    def test_ascii_and_utf16_tokens_are_detected(self):
        mapping = m(0x2000, 0x2000)
        data = b"A pc00_scl_w B" + " pc00_scl_w ".encode("utf-16le")
        rows = TOOL.scan_buffer_for_tokens(data, mapping.start, mapping, 0, Path("/game"))
        enc = {r["encoding"] for r in rows if r["token_label"] == "pc00_school_wet"}
        self.assertEqual(enc, {"ascii", "utf16le"})

    def test_process_detection_requires_strong_game_identity_not_game_root_argument(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            game = root / "game"; game.mkdir()
            (game / "BLUE REFLECTION Quartet.exe").write_bytes(b"")
            proc = root / "proc"; proc.mkdir()
            # Unrelated helper contains the game-root argument but is not the game.
            helper = proc / "50001"; helper.mkdir()
            (helper / "cmdline").write_bytes(f"python3\0tool.py\0--game-root\0{game}\0".encode())
            (helper / "statm").write_text("1 1 0 0 0 0 0\n")
            os.symlink(root, helper / "cwd")
            os.symlink("/usr/bin/python3", helper / "exe")
            # Actual Wine game process advertises the concrete EXE basename.
            gp = proc / "50002"; gp.mkdir()
            (gp / "cmdline").write_bytes(b"wine64\0BLUE REFLECTION Quartet.exe\0")
            (gp / "statm").write_text("100000 50000 0 0 0 0 0\n")
            os.symlink(game, gp / "cwd")
            os.symlink("/usr/bin/wine64", gp / "exe")
            found = TOOL.discover_game_process(game, proc_root=proc)
            self.assertEqual(found["pid"], 50002)

    def test_process_vm_readv_can_read_own_memory(self):
        marker = ctypes.create_string_buffer(b"stage164-self-read-marker")
        with TOOL.ProcessMemoryReader(os.getpid()) as reader:
            got = reader.read(ctypes.addressof(marker), len(marker.raw))
        self.assertIn(b"stage164-self-read-marker", got)

    def test_pointer_target_selection_is_bounded_and_keeps_dry_and_wet(self):
        mapping = m(0x100000, 0x200000)
        rows = []
        for i in range(80):
            state = "dry" if i % 2 == 0 else "wet"
            tok = "pc00_school_dry" if state == "dry" else "pc00_school_wet"
            rows.append(occurrence(tok, state, 0x101000 + i * 0x100, mapping))
        selected, stats = TOOL.select_pointer_targets(rows, max_targets=16)
        self.assertEqual(len(selected), 16)
        self.assertTrue(stats["target_selection_bounded"])
        selected_states = {ref[0]["token_state"] for refs in selected.values() for ref in refs}
        self.assertEqual(selected_states, {"dry", "wet"})

    def test_pointer_scan_honors_exact_byte_cap(self):
        class Reader:
            def read(self, address, size):
                return b"\x00" * size
        mapping = m(0x100000, 4 * 1024 * 1024)
        tok = occurrence("pc00_school_dry", "dry", 0x101000, mapping)
        rows, stats = TOOL.scan_pointer_references(
            Reader(), [mapping], Path("/game"), [tok], label="fixture",
            max_bytes=256 * 1024, max_targets=8,
        )
        self.assertEqual(rows, [])
        self.assertEqual(stats["planned_scan_bytes"], 256 * 1024)
        self.assertEqual(stats["bytes_read"], 256 * 1024)
        self.assertTrue(stats["pointer_scan_bounded"])

    def test_same_address_dry_to_wet_pointer_switch_is_bounded_candidate(self):
        mapping = m(0x100000, 0x10000)
        dry_tok = occurrence("pc00_school_dry", "dry", 0x101000, mapping)
        wet_tok = occurrence("pc00_school_wet", "wet", 0x102000, mapping)
        dry = {"pointer_rows": [pointer(0x103000, dry_tok, mapping, context="a")]}
        wet = {"pointer_rows": [pointer(0x103000, wet_tok, mapping, context="b")]}
        rows = TOOL.pointer_switch_rows(dry, wet)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["dry_target_token_label"], "pc00_school_dry")
        self.assertEqual(rows[0]["wet_target_token_label"], "pc00_school_wet")
        self.assertIn("not_selector_or_transparency_semantics", rows[0]["classification"])

    def test_different_pointer_sites_do_not_form_switch(self):
        mapping = m(0x100000, 0x10000)
        dry_tok = occurrence("pc00_school_dry", "dry", 0x101000, mapping)
        wet_tok = occurrence("pc00_school_wet", "wet", 0x102000, mapping)
        dry = {"pointer_rows": [pointer(0x103000, dry_tok, mapping)]}
        wet = {"pointer_rows": [pointer(0x103008, wet_tok, mapping)]}
        self.assertEqual(TOOL.pointer_switch_rows(dry, wet), [])

    def test_wet_only_residency_is_not_semantic_proof(self):
        mapping = m(0x100000, 0x10000)
        wet_tok = occurrence("pc00_school_wet", "wet", 0x102000, mapping)
        rows = TOOL.wet_only_dynamic_rows({"token_rows": []}, {"token_rows": [wet_tok]})
        self.assertEqual(len(rows), 1)
        self.assertIn("not_resolution_semantics", rows[0]["classification"])

    def test_fixture_report_has_no_raw_memory_or_absolute_paths(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            mapping = m(0x100000, 0x10000)
            dry_tok = occurrence("pc00_school_dry", "dry", 0x101000, mapping, context="d", page="pd")
            wet_tok = occurrence("pc00_school_wet", "wet", 0x102000, mapping, context="w", page="pw")
            dry = {
                "pid": 4242, "label": "dry", "maps": [mapping], "token_rows": [dry_tok],
                "pointer_rows": [pointer(0x103000, dry_tok, mapping, context="a")],
                "token_scan_stats": {}, "pointer_scan_stats": {},
            }
            wet = {
                "pid": 4242, "label": "wet", "maps": [mapping], "token_rows": [wet_tok],
                "pointer_rows": [pointer(0x103000, wet_tok, mapping, context="b")],
                "token_scan_stats": {}, "pointer_scan_stats": {},
            }
            _, summary = TOOL.build_report(
                PROJECT, Path("/fake/game"), report_root=root, output_report_root=root,
                create_archive=False, interactive=False, fixture_snapshots=(dry, wet),
                skip_prerequisites_for_fixture=True,
            )
            self.assertEqual(summary["same_address_dry_to_wet_pointer_switch_rows"], 1)
            self.assertFalse(summary["pointer_scan_exhaustive"])
            self.assertEqual(summary["pointer_scan_max_bytes_per_snapshot"], TOOL.MAX_POINTER_SCAN_BYTES)
            self.assertEqual(summary["pointer_target_pattern_cap_per_snapshot"], TOOL.MAX_POINTER_TARGETS)
            self.assertFalse(summary["runtime_process_memory_written"])
            self.assertFalse(summary["installed_game_modified"])
            text = "\n".join(p.read_text(encoding="utf-8") for p in (root / TOOL.REPORT_DIR).iterdir())
            self.assertNotIn("/fake/game", text)
            self.assertNotIn("stage164-self-read-marker", text)
            self.assertIn("same_address_dry_to_wet_pointer_switch_candidate", text)

    def test_stage163_no_anchor_result_is_canonicalized(self):
        status = json.loads((PROJECT / "workstreams/quartet_restoration/STATUS.json").read_text())
        row = status["wetness_transition_structured_selector_binding_stage"]
        self.assertEqual(row["status"], "complete_no_bounded_runtime_trace_anchor")
        self.assertEqual(row["user_evidence_sha256"], TOOL.STAGE163_SHA256)
        self.assertEqual(row["pc00_target_bounded_trace_anchor_rows"], 0)
        self.assertFalse(row["selector_binding_confirmed"])
        nxt = status["native_wetness_process_state_trace_stage"]
        self.assertEqual(nxt["stage"], 164)
        self.assertFalse(nxt["writes_process_memory"])
        self.assertFalse(nxt["writes_installed_game"])

    def test_stage164_tool_version_remains_canonical_after_later_workstream_updates(self):
        current = tuple(int(x) for x in (PROJECT / "workstreams/quartet_restoration/VERSION").read_text().strip().split("."))
        self.assertGreaterEqual(current, (0, 1, 86))
        self.assertEqual(TOOL.TOOL_VERSION, "0.1.86")


if __name__ == "__main__":
    unittest.main()
