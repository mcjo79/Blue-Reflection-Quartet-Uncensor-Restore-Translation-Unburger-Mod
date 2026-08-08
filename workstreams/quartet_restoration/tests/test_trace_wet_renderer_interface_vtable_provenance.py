from __future__ import annotations

import importlib.util
import struct
import sys
import tempfile
import unittest
from unittest import mock
from pathlib import Path

MODULE_PATH = Path(__file__).resolve().parents[1] / "170_trace_wet_renderer_interface_vtable_provenance.py"
spec = importlib.util.spec_from_file_location("br_stage170_test", MODULE_PATH)
assert spec and spec.loader
M = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = M
spec.loader.exec_module(M)


class FakeReader:
    def __init__(self, chunks):
        self.chunks = list(chunks)
    def read(self, address, size):
        for start, data in self.chunks:
            if start <= address and address + size <= start + len(data):
                off = address - start
                return data[off:off+size]
        return b""


def maprow(start, end, perms, path=""):
    return M.S164.MapRow(start, end, perms, 0, "00:00", 1, path)


class Stage170Tests(unittest.TestCase):
    def setUp(self):
        self.game_root = Path("/games/Quartet")

    def renderer_fixture(self, family_path="/wine/d3d11.dll", exec_count=4):
        child = 0x1100
        vtable = 0x2100
        funcs = [0x3100 + 0x20*i for i in range(M.VTABLE_ENTRY_COUNT)]
        child_mem = bytearray(0x400)
        struct.pack_into("<Q", child_mem, child-0x1000, vtable)
        vt_mem = bytearray(0x400)
        for i, fn in enumerate(funcs):
            struct.pack_into("<Q", vt_mem, vtable-0x2000+i*8, fn if i < exec_count else 0)
        fn_mem = bytes(0x800)
        maps = [
            maprow(0x1000, 0x1400, "rw-p", "[heap]"),
            maprow(0x2000, 0x2400, "r--p", family_path),
            maprow(0x3000, 0x3800, "r-xp", family_path),
        ]
        reader = FakeReader([(0x1000, bytes(child_mem)), (0x2000, bytes(vt_mem)), (0x3000, fn_mem)])
        return reader, maps, child

    def test_module_family_d3d11(self):
        m = maprow(0x2000, 0x3000, "r--p", "/wine/d3d11.dll")
        self.assertEqual(M.module_family(m, self.game_root), "d3d11")

    def test_probable_d3d11_vtable_is_renderer_supported(self):
        reader, maps, child = self.renderer_fixture()
        row = M.classify_vtable_candidate(reader, maps, self.game_root, child)
        self.assertIsNotNone(row)
        self.assertTrue(row["renderer_interface_supported"])
        self.assertIn("d3d11", row["function_module_families"])
        self.assertGreaterEqual(row["executable_entry_count"], M.MIN_EXEC_VTABLE_ENTRIES)

    def test_vtable_with_too_few_executable_entries_is_rejected(self):
        reader, maps, child = self.renderer_fixture(exec_count=1)
        self.assertIsNone(M.classify_vtable_candidate(reader, maps, self.game_root, child))

    def test_game_vtable_is_object_provenance_but_not_renderer(self):
        reader, maps, child = self.renderer_fixture(family_path="/games/Quartet/BLUE_REFLECTION.exe")
        row = M.classify_vtable_candidate(reader, maps, self.game_root, child)
        self.assertIsNotNone(row)
        self.assertFalse(row["renderer_interface_supported"])
        self.assertIn("game_executable", row["function_module_families"])

    def test_recurrent_wet_only_renderer_interface_candidate(self):
        base = {
            "root_id": "iface_root_01",
            "root_field_relative_offset": 24,
            "vtable_module_family": "d3d11",
            "vtable_mapping_relative_offset": 0x120,
            "vtable_signature_sha256": "abc",
            "function_module_families": "d3d11",
            "executable_entry_count": 6,
            "renderer_interface_supported": True,
        }
        out = M.recurrent_interface_candidates([base], [], [base])
        self.assertEqual(len(out), 1)
        self.assertTrue(out[0]["renderer_interface_supported"])
        self.assertFalse(out[0]["transparency_semantics_confirmed"])

    def test_same_interface_present_in_dry_is_not_candidate(self):
        base = {
            "root_id": "iface_root_01",
            "root_field_relative_offset": 24,
            "vtable_module_family": "dxgi",
            "vtable_mapping_relative_offset": 0x120,
            "vtable_signature_sha256": "abc",
            "function_module_families": "dxgi",
            "executable_entry_count": 4,
            "renderer_interface_supported": True,
        }
        self.assertEqual(M.recurrent_interface_candidates([base], [base], [base]), [])

    def test_changed_vtable_signature_between_wet_rounds_is_not_candidate(self):
        a = {
            "root_id": "iface_root_01", "root_field_relative_offset": 8,
            "vtable_module_family": "d3d11", "vtable_mapping_relative_offset": 0x10,
            "vtable_signature_sha256": "a", "renderer_interface_supported": True,
        }
        b = dict(a); b["vtable_signature_sha256"] = "b"
        self.assertEqual(M.recurrent_interface_candidates([a], [], [b]), [])


    def test_explicit_game_root_has_priority_over_environment(self):
        with tempfile.TemporaryDirectory() as td:
            explicit = Path(td) / "explicit"
            explicit.mkdir()
            with mock.patch.dict(M.os.environ, {"BR1_QUARTET_ROOT": "/env/quartet"}, clear=False):
                root, source = M.resolve_game_root(Path(td), explicit)
            self.assertEqual(root, explicit.resolve())
            self.assertEqual(source, "explicit_cli")

    def test_environment_has_priority_over_local_paths(self):
        with tempfile.TemporaryDirectory() as td:
            project = Path(td)
            env_root = project / "env-root"
            env_root.mkdir()
            local = project / ".local"
            local.mkdir()
            (local / "paths.sh").write_text('BR1_QUARTET_ROOT="/local/quartet"\n', encoding="utf-8")
            with mock.patch.dict(M.os.environ, {"BR1_QUARTET_ROOT": str(env_root)}, clear=False):
                root, source = M.resolve_game_root(project, None)
            self.assertEqual(root, env_root.resolve())
            self.assertEqual(source, "environment")

    def test_root_preflight_error_includes_selected_root_and_hash(self):
        with tempfile.TemporaryDirectory() as td:
            project = Path(td) / "project"
            game = Path(td) / "game"
            (game / "Data").mkdir(parents=True)
            (game / "Data/PACK10_02.PAK").write_bytes(b"not-baseline")
            with mock.patch.object(M, "verify_stage169_contract", return_value={}):
                with self.assertRaises(M.Stage170Error) as cm:
                    M.root_preflight(project, game, "explicit_cli")
            msg = str(cm.exception)
            self.assertIn(str(game), msg)
            self.assertIn(M.sha256_file(game / "Data/PACK10_02.PAK"), msg)

    def test_process_selector_prefers_unique_selected_root_game_exe_mapping(self):
        rows = [
            {"pid": 10, "mapped_game_exe_count": 0, "mapped_game_root_exec_count": 0, "mapped_game_root_count": 0, "thread_count": 4, "rss": 200},
            {"pid": 11, "mapped_game_exe_count": 1, "mapped_game_root_exec_count": 2, "mapped_game_root_count": 3, "thread_count": 3, "rss": 100},
        ]
        row, mode = M.choose_game_process_candidate(rows)
        self.assertEqual(row["pid"], 11)
        self.assertEqual(mode, "selected_root_game_exe_mapping")

    def test_process_selector_uses_dominant_rss_for_equivalent_wine_helpers(self):
        mib = 1024 * 1024
        rows = [
            {"pid": 109875, "mapped_game_exe_count": 0, "mapped_game_root_exec_count": 0, "mapped_game_root_count": 0, "thread_count": 6, "rss": 80*mib},
            {"pid": 109767, "mapped_game_exe_count": 0, "mapped_game_root_exec_count": 0, "mapped_game_root_count": 0, "thread_count": 5, "rss": 44*mib},
            {"pid": 109883, "mapped_game_exe_count": 0, "mapped_game_root_exec_count": 0, "mapped_game_root_count": 0, "thread_count": 4, "rss": 38*mib},
        ]
        row, mode = M.choose_game_process_candidate(rows)
        self.assertEqual(row["pid"], 109875)
        self.assertEqual(mode, "dominant_rss")

    def test_process_selector_true_tie_fails_closed_noninteractive(self):
        mib = 1024 * 1024
        rows = [
            {"pid": 20, "mapped_game_exe_count": 0, "mapped_game_root_exec_count": 0, "mapped_game_root_count": 0, "thread_count": 4, "rss": 40*mib},
            {"pid": 21, "mapped_game_exe_count": 0, "mapped_game_root_exec_count": 0, "mapped_game_root_count": 0, "thread_count": 4, "rss": 38*mib},
        ]
        with self.assertRaises(M.Stage170Error):
            M.choose_game_process_candidate(rows, interactive=False)

    def test_process_selector_true_tie_allows_interactive_pid_selection(self):
        mib = 1024 * 1024
        rows = [
            {"pid": 20, "mapped_game_exe_count": 0, "mapped_game_root_exec_count": 0, "mapped_game_root_count": 0, "thread_count": 4, "rss": 40*mib},
            {"pid": 21, "mapped_game_exe_count": 0, "mapped_game_root_exec_count": 0, "mapped_game_root_count": 0, "thread_count": 4, "rss": 38*mib},
        ]
        row, mode = M.choose_game_process_candidate(rows, interactive=True, input_fn=lambda _prompt: "21")
        self.assertEqual(row["pid"], 21)
        self.assertEqual(mode, "interactive_pid_selection")

    def test_trace_bounds_are_small(self):
        self.assertLessEqual(M.ROOT_SCAN_RADIUS, 1024)
        self.assertLessEqual(M.MAX_INTERFACE_ROWS_PER_ROOT, 64)
        self.assertLessEqual(M.VTABLE_ENTRY_COUNT, 8)

    def test_stage169_negative_contract_is_pinned(self):
        self.assertEqual(M.STAGE169_SHA256, "a4d4976e7449fe41d46133e6a81f790cb66489551ee0985eafe59e33088fdf2d")

    def test_source_declares_independent_signal_and_read_only(self):
        text = MODULE_PATH.read_text(encoding="utf-8")
        self.assertIn("object-interface provenance", text)
        self.assertIn("No process memory or game file is written", text)
        self.assertIn('"token_semantics_used_for_interface_classification": False', text)
        self.assertIn('"absolute_process_addresses_exported": False', text)
        self.assertIn('"wet_transparency_mechanism_confirmed": False', text)


if __name__ == "__main__":
    unittest.main()
