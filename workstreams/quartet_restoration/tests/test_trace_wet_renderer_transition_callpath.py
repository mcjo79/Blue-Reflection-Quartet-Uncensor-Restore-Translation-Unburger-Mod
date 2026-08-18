from __future__ import annotations

import importlib.util
import struct
import sys
import unittest
from collections import Counter
from pathlib import Path

MODULE_PATH = Path(__file__).resolve().parents[1] / "171_trace_wet_renderer_transition_callpath.py"
spec = importlib.util.spec_from_file_location("br_stage171_test", MODULE_PATH)
assert spec and spec.loader
M = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = M
spec.loader.exec_module(M)


def maprow(start, end, perms, path=""):
    return M.S164.MapRow(start, end, perms, 0, "00:00", 1, path)


class Stage171Tests(unittest.TestCase):
    def setUp(self):
        self.game_root = Path("/games/Quartet")

    def test_perf_attr_is_read_only_user_callchain_sampler(self):
        a = M.make_perf_attr()
        self.assertEqual(a.type, M.PERF_TYPE_SOFTWARE)
        self.assertEqual(a.config, M.PERF_COUNT_SW_CPU_CLOCK)
        self.assertTrue(a.flags & (1 << 0))  # disabled before explicit enable
        self.assertTrue(a.flags & (1 << 5))  # exclude kernel
        self.assertTrue(a.sample_type & M.PERF_SAMPLE_CALLCHAIN)
        self.assertEqual(a.sample_period, M.SAMPLE_PERIOD_NS)

    def test_parse_perf_sample_payload(self):
        payload = struct.pack("<QIIQQQQ", 0x1111, 10, 11, 12345, 2, 0x2222, 0x3333)
        row = M.parse_perf_sample_payload(payload)
        self.assertEqual(row["ip"], 0x1111)
        self.assertEqual(row["tid"], 11)
        self.assertEqual(row["callchain"], [0x2222, 0x3333])

    def test_parse_perf_sample_payload_rejects_truncated(self):
        with self.assertRaises(M.Stage171Error):
            M.parse_perf_sample_payload(b"short")

    def test_normalize_callchain_detects_renderer_family_without_addresses(self):
        maps = [
            maprow(0x1000, 0x2000, "r-xp", "/wine/d3d11.dll"),
            maprow(0x3000, 0x4000, "r-xp", "/games/Quartet/BLUE_REFLECTION.exe"),
        ]
        row = M.normalize_callchain({"ip": 0x1108, "callchain": [0x3110]}, maps, self.game_root)
        self.assertIsNotNone(row)
        self.assertTrue(row["renderer_associated"])
        self.assertIn("d3d11", row["renderer_families"])
        self.assertNotIn("1108", row["exact_signature_sha256"])

    def test_context_markers_are_filtered(self):
        maps = [maprow(0x1000, 0x2000, "r-xp", "/wine/dxgi.dll")]
        marker = (1 << 64) - 1
        row = M.normalize_callchain({"ip": marker, "callchain": [0x1100]}, maps, self.game_root)
        self.assertIsNotNone(row)
        self.assertEqual(row["module_families"], "dxgi")

    def test_recurrent_exact_wet_only_renderer_callpath_is_candidate(self):
        meta = {
            "abc": {
                "module_families": "d3d11;dxgi",
                "renderer_families": "d3d11;dxgi",
                "renderer_associated": True,
                "frame_count": 4,
            }
        }
        captures = {
            "wet1": (Counter({"abc": 3}), Counter(), meta),
            "dry2": (Counter(), Counter(), {}),
            "wet2": (Counter({"abc": 2}), Counter(), meta),
        }
        out = M.recurrent_candidates(captures)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["signature_kind"], "exact")
        self.assertTrue(out[0]["renderer_associated"])
        self.assertFalse(out[0]["transparency_semantics_confirmed"])

    def test_same_signature_in_dry_control_is_not_candidate(self):
        meta = {"abc": {"renderer_associated": True, "frame_count": 2}}
        captures = {
            "wet1": (Counter({"abc": 3}), Counter(), meta),
            "dry2": (Counter({"abc": 1}), Counter(), meta),
            "wet2": (Counter({"abc": 3}), Counter(), meta),
        }
        self.assertEqual(M.recurrent_candidates(captures), [])

    def test_single_sample_each_wet_round_is_too_weak(self):
        meta = {"abc": {"renderer_associated": True, "frame_count": 2}}
        captures = {
            "wet1": (Counter({"abc": 1}), Counter(), meta),
            "dry2": (Counter(), Counter(), {}),
            "wet2": (Counter({"abc": 1}), Counter(), meta),
        }
        self.assertEqual(M.recurrent_candidates(captures), [])

    def test_family_signature_can_be_candidate_independently(self):
        meta = {
            "fam": {
                "module_families": "dxvk;vulkan",
                "renderer_families": "dxvk;vulkan",
                "renderer_associated": True,
                "frame_count": 5,
            }
        }
        captures = {
            "wet1": (Counter(), Counter({"fam": 4}), meta),
            "dry2": (Counter(), Counter(), {}),
            "wet2": (Counter(), Counter({"fam": 5}), meta),
        }
        out = M.recurrent_candidates(captures)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["signature_kind"], "family")

    def test_bounds_are_conservative(self):
        self.assertLessEqual(M.CAPTURE_SECONDS, 10)
        self.assertLessEqual(M.MAX_THREADS, 128)
        self.assertLessEqual(M.MAX_CALLCHAIN_FRAMES, 32)
        self.assertGreaterEqual(M.SAMPLE_PERIOD_NS, 1_000_000)

    def test_stage170_hash_is_pinned(self):
        self.assertEqual(M.STAGE170_SHA256, "6f73ad48d129e1215f110219bc908d02e0e37c1e9f417652cbd86ea88eb088d7")

    def test_source_declares_privacy_and_no_write(self):
        text = MODULE_PATH.read_text(encoding="utf-8")
        self.assertIn("game file write is performed", text)
        self.assertIn('"absolute_process_addresses_exported": False', text)
        self.assertIn('"raw_perf_ring_exported": False', text)
        self.assertIn('"wet_transparency_mechanism_confirmed": False', text)


if __name__ == "__main__":
    unittest.main()
