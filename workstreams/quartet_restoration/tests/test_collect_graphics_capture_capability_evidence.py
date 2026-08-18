from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

MODULE_PATH = Path(__file__).resolve().parents[1] / "172_collect_graphics_capture_capability_evidence.py"
spec = importlib.util.spec_from_file_location("br_stage172_test", MODULE_PATH)
assert spec and spec.loader
M = importlib.util.module_from_spec(spec)
spec.loader.exec_module(M)


def maprow(start, end, perms, path=""):
    return M.S164.MapRow(start, end, perms, 0, "00:00", 1, path)


class Stage172Tests(unittest.TestCase):
    def test_stage171_hash_is_pinned(self):
        self.assertEqual(M.STAGE171_SHA256, "9fcc90452eed4bdd641da45aacdd280af4e8775c05cda2dba0589a0e5b1aebb5")

    def test_renderer_family_classification(self):
        self.assertEqual(M.renderer_family_from_basename("d3d11.dll"), "d3d11")
        self.assertEqual(M.renderer_family_from_basename("dxgi.dll"), "dxgi")
        self.assertEqual(M.renderer_family_from_basename("winevulkan.so"), "winevulkan")
        self.assertEqual(M.renderer_family_from_basename("libvulkan.so.1.3.0"), "vulkan_loader_or_icd")
        self.assertEqual(M.renderer_family_from_basename("wined3d.dll.so"), "wined3d")

    def test_process_renderer_stack_deduplicates_segments(self):
        maps = [
            maprow(0x1000, 0x2000, "r--p", "/sys/libvulkan.so.1"),
            maprow(0x2000, 0x3000, "r-xp", "/sys/libvulkan.so.1"),
            maprow(0x4000, 0x5000, "r-xp", "/wine/winevulkan.so"),
            maprow(0x6000, 0x7000, "r-xp", "/wine/d3d11.dll"),
        ]
        rows, flags, _ = M.process_renderer_stack_rows(maps)
        vulkan = [r for r in rows if r["module_family"] == "vulkan_loader_or_icd"]
        self.assertEqual(len(vulkan), 1)
        self.assertEqual(vulkan[0]["mapping_rows"], 2)
        self.assertEqual(vulkan[0]["executable_mapping_rows"], 1)
        self.assertTrue(flags["winevulkan_mapped"])
        self.assertTrue(flags["d3d11_mapped"])

    def test_launch_mode_detects_proton(self):
        self.assertEqual(M.launch_mode(["wine64", "Game.exe"], {"STEAM_COMPAT_DATA_PATH": "/x"}), "steam_or_proton_managed")

    def test_launch_mode_detects_wine(self):
        self.assertEqual(M.launch_mode(["wine64", "Game.exe"], {"WINEPREFIX": "/prefix"}), "wine_managed")

    def test_backend_prefers_renderdoc_when_fully_available(self):
        backend, _ = M.choose_capture_backend(
            {"vulkan_loader_mapped": True, "winevulkan_mapped": True},
            [{"category": "renderdoc_capture"}],
            {"renderdoccmd_available": True},
            True,
            True,
        )
        self.assertEqual(backend, "existing_renderdoc_capture")

    def test_backend_prefers_existing_api_dump_before_custom_layer(self):
        backend, _ = M.choose_capture_backend(
            {"vulkan_loader_mapped": True, "winevulkan_mapped": True},
            [{"category": "api_dump"}],
            {"renderdoccmd_available": False},
            True,
            True,
        )
        self.assertEqual(backend, "existing_vulkan_api_dump")

    def test_backend_falls_back_to_project_local_layer(self):
        backend, _ = M.choose_capture_backend(
            {"vulkan_loader_mapped": True, "winevulkan_mapped": False},
            [],
            {"renderdoccmd_available": False},
            True,
            True,
        )
        self.assertEqual(backend, "project_local_vulkan_layer")

    def test_backend_blocks_without_active_vulkan_stack(self):
        backend, _ = M.choose_capture_backend(
            {"vulkan_loader_mapped": False, "winevulkan_mapped": False},
            [{"category": "api_dump"}],
            {"renderdoccmd_available": False},
            True,
            True,
        )
        self.assertEqual(backend, "blocked_no_active_vulkan_stack")

    def test_local_launch_context_is_explicitly_local_only(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            original_env = M.parse_proc_environ
            original_cmd = M.parse_proc_cmdline
            original_cwd = M.parse_proc_cwd
            try:
                M.parse_proc_environ = lambda pid: {"WINEPREFIX": "/local/prefix", "DISPLAY": ":0"}
                M.parse_proc_cmdline = lambda pid: ["wine64", "Game.exe"]
                M.parse_proc_cwd = lambda pid: "/local/game"
                path = M.local_launch_context(root, root / "game", {"pid": 123}, "test")
                obj = json.loads(path.read_text())
                self.assertTrue(obj["machine_specific_local_only"])
                self.assertTrue(obj["must_not_be_packaged_or_exported"])
                self.assertEqual(path.relative_to(root), M.LOCAL_LAUNCH_CONTEXT_REL)
            finally:
                M.parse_proc_environ = original_env
                M.parse_proc_cmdline = original_cmd
                M.parse_proc_cwd = original_cwd

    def test_compiler_probe_is_non_game_mutating(self):
        ok, reason = M.compile_shared_library_probe()
        self.assertIsInstance(ok, bool)
        self.assertTrue(reason)

    def test_source_declares_privacy_and_no_capture(self):
        text = MODULE_PATH.read_text(encoding="utf-8")
        self.assertIn("No game file or process memory is modified", text)
        self.assertIn('"external_graphics_capture_started": False', text)
        self.assertIn('"selected_game_root_exported": False', text)
        self.assertIn('"wet_transparency_mechanism_confirmed": False', text)


if __name__ == "__main__":
    unittest.main()
