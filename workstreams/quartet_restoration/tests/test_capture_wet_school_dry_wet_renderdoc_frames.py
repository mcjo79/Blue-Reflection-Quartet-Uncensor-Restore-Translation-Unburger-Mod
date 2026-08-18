from __future__ import annotations

import importlib.util
import json
import os
import tempfile
import threading
import time
import unittest
from pathlib import Path

MODULE_PATH = Path(__file__).resolve().parents[1] / "173_capture_wet_school_dry_wet_renderdoc_frames.py"
spec = importlib.util.spec_from_file_location("br_stage173_test", MODULE_PATH)
assert spec and spec.loader
M = importlib.util.module_from_spec(spec)
spec.loader.exec_module(M)


class Stage173Tests(unittest.TestCase):
    def test_stage172_hash_is_pinned(self):
        self.assertEqual(M.STAGE172_SHA256, "d3844aa471b168c9fe24c21a9a08883c44c2632da8ec458f59599cc5e3357093")

    def test_baseline_hash_is_pinned(self):
        self.assertEqual(M.PACK10_02_BASELINE_SHA256, "e798f39c3bcdbb11381197bddf9bd3ad8de6ccf5d7c0c78b22613046d47f5302")

    def test_local_paths_are_under_local_build(self):
        self.assertTrue(str(M.LOCAL_CONTEXT_REL).startswith(".local/build/"))
        self.assertTrue(str(M.LOCAL_STAGE173_REL).startswith(".local/build/"))
        self.assertTrue(str(M.LOCAL_CURRENT_REL).startswith(".local/build/"))

    def test_validate_rdc_accepts_magic(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "a.rdc"
            p.write_bytes(b"RDOC" + b"x" * 5000)
            row = M.validate_rdc(p)
            self.assertTrue(row["magic_ok"])
            self.assertEqual(row["size_bytes"], 5004)
            self.assertEqual(len(row["sha256"]), 64)

    def test_validate_rdc_rejects_wrong_magic(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "a.rdc"
            p.write_bytes(b"NOPE" + b"x" * 5000)
            with self.assertRaises(M.Stage173Error):
                M.validate_rdc(p)

    def test_validate_rdc_rejects_small_file(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "a.rdc"
            p.write_bytes(b"RDOC")
            with self.assertRaises(M.Stage173Error):
                M.validate_rdc(p)

    def test_snapshot_only_rdc(self):
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            (d / "a.rdc").write_bytes(b"x")
            (d / "b.txt").write_bytes(b"x")
            rows = M.snapshot_rdc(d)
            self.assertEqual({p.name for p in rows}, {"a.rdc"})

    def test_wait_for_one_new_capture(self):
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            before = M.snapshot_rdc(d)
            def writer():
                time.sleep(0.2)
                (d / "one.rdc").write_bytes(b"RDOC" + b"x" * 5000)
            t = threading.Thread(target=writer)
            t.start()
            p = M.wait_for_one_new_capture(d, before, timeout=3)
            t.join()
            self.assertEqual(p.name, "one.rdc")

    def test_wait_rejects_multiple_new_captures(self):
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            before = M.snapshot_rdc(d)
            (d / "one.rdc").write_bytes(b"RDOC" + b"x" * 5000)
            (d / "two.rdc").write_bytes(b"RDOC" + b"x" * 5000)
            with self.assertRaises(M.Stage173Error):
                M.wait_for_one_new_capture(d, before, timeout=1)

    def test_launch_context_must_match_selected_root(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            project = root / "project"
            game_a = root / "game_a"
            game_b = root / "game_b"
            cwd = root / "cwd"
            game_a.mkdir(); game_b.mkdir(); cwd.mkdir()
            p = project / M.LOCAL_CONTEXT_REL
            p.parent.mkdir(parents=True)
            p.write_text(json.dumps({
                "machine_specific_local_only": True,
                "must_not_be_packaged_or_exported": True,
                "pack10_02_sha256": M.PACK10_02_BASELINE_SHA256,
                "game_root": str(game_a),
                "cmdline": ["wine64", "Game.exe"],
                "cwd": str(cwd),
                "environment": {},
            }))
            with self.assertRaises(M.Stage173Error):
                M.load_launch_context(project, game_b)

    def test_launch_context_accepts_matching_root(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            project = root / "project"
            game = root / "game"
            cwd = root / "cwd"
            game.mkdir(); cwd.mkdir()
            p = project / M.LOCAL_CONTEXT_REL
            p.parent.mkdir(parents=True)
            p.write_text(json.dumps({
                "machine_specific_local_only": True,
                "must_not_be_packaged_or_exported": True,
                "pack10_02_sha256": M.PACK10_02_BASELINE_SHA256,
                "game_root": str(game),
                "cmdline": ["wine64", "Game.exe"],
                "cwd": str(cwd),
                "environment": {"WINEPREFIX": str(root / "prefix")},
            }))
            obj = M.load_launch_context(project, game)
            self.assertEqual(obj["cmdline"][0], "wine64")

    def test_report_name_is_small_metadata_evidence(self):
        self.assertTrue(M.REPORT_NAME.endswith(".tar.zst"))
        self.assertNotIn("rdc", M.REPORT_NAME.casefold())

    def test_source_separates_state_change_from_capture(self):
        text = MODULE_PATH.read_text(encoding="utf-8")
        self.assertIn("CAPTURE DRY FRAME NOW", text)
        self.assertIn("CHANGE STATE TO WET — DO NOT CAPTURE YET", text)
        self.assertIn("CAPTURE WET FRAME NOW", text)

    def test_source_does_not_export_raw_capture_or_machine_path(self):
        text = MODULE_PATH.read_text(encoding="utf-8")
        self.assertIn('"raw_rdc_exported": False', text)
        self.assertIn('"capture_paths_exported": False', text)
        self.assertIn('"selected_game_root_exported": False', text)

    def test_no_game_or_process_write_claims(self):
        text = MODULE_PATH.read_text(encoding="utf-8")
        self.assertIn("No game file or process memory is modified", text)
        self.assertIn('"installed_game_modified": False', text)
        self.assertIn('"process_memory_written": False', text)


if __name__ == "__main__":
    unittest.main()
