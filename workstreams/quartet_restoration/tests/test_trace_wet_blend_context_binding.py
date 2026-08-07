#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import struct
import sys
import unittest
from pathlib import Path

MODULE_PATH = Path(__file__).resolve().parents[1] / "169_trace_wet_blend_context_binding.py"
spec = importlib.util.spec_from_file_location("wet_blend_context_stage169", MODULE_PATH)
assert spec and spec.loader
M = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = M
spec.loader.exec_module(M)


class FakeReader:
    def __init__(self, regions: dict[int, bytes]):
        self.regions = regions
    def read(self, address: int, size: int) -> bytes:
        for base, data in self.regions.items():
            if base <= address and address + size <= base + len(data):
                off = address - base
                return data[off:off+size]
        raise OSError("outside fake region")


class Stage169Tests(unittest.TestCase):
    def test_stage168_contract_is_exact_user_report_and_contains_blend_clue(self) -> None:
        project_root = Path(__file__).resolve().parents[3]
        summary = M.verify_stage168_contract(project_root)
        self.assertEqual(summary["stage"], 168)
        self.assertEqual(summary["wet2_recurrent_wet_school_root_rows"], 17)
        self.assertEqual(summary["recurrent_wet_renderer_adjacent_path_rows"], 68)
        self.assertFalse(summary["material_binding_confirmed"])

    def test_rich_allowlist_detects_renderer_terms_without_exporting_arbitrary_string(self) -> None:
        assets, terms = M.extract_rich_allowlisted_tokens(
            b"random private prose pc00_scl_w.g1t AlphaBlend BlendState material texture opacity"
        )
        self.assertIn("pc00_scl_w.g1t", assets)
        self.assertIn("alpha", terms)
        self.assertIn("blend", terms)
        self.assertIn("blendstate", terms)
        self.assertIn("material", terms)
        self.assertIn("opacity", terms)
        self.assertNotIn("random private prose", terms)

    def test_strong_wet_root_requires_main_and_default_markers(self) -> None:
        self.assertTrue(M.is_strong_wet_root_assets(["PC00_Scl_W.g1m", "PC00_Scl_W_default.g1m"]))
        self.assertFalse(M.is_strong_wet_root_assets(["PC00_Scl_W.g1m"]))

    def test_wet_root_rank_degrades_to_single_main_marker_with_wet_term(self) -> None:
        self.assertEqual(M.wet_root_rank(["PC00_Scl_W.g1m"], ["pc00_scl_w"]), 1)
        self.assertEqual(M.wet_root_rank(["PC00_Scl_W_default.g1m"], ["scl_w"]), 1)
        self.assertEqual(M.wet_root_rank(["PC00_Scl_W_P_School_Wet.g1m"], ["pc00_scl_w"]), 2)
        self.assertIsNone(M.wet_root_rank(["PC04_Scl_W.g1m"], ["scl_w"]))

    def test_select_best_wet_roots_uses_only_best_available_rank(self) -> None:
        roots = [
            {"pointer": 1, "direct_asset_tokens": ["PC00_Scl_W_P_School_Wet.g1m"], "direct_technical_terms": ["pc00_scl_w"]},
            {"pointer": 2, "direct_asset_tokens": ["PC00_Scl_W_default.g1m"], "direct_technical_terms": ["pc00_scl_w"]},
            {"pointer": 3, "direct_asset_tokens": ["PC00_Scl_W_P_Tear.g1m"], "direct_technical_terms": ["pc00_scl_w"]},
        ]
        selected, rank = M.select_best_wet_roots(roots)
        self.assertEqual(rank, 1)
        self.assertEqual([r["pointer"] for r in selected], [2])

    def test_select_best_wet_roots_prefers_exact_both_marker_class(self) -> None:
        roots = [
            {"pointer": 1, "direct_asset_tokens": ["PC00_Scl_W_default.g1m"], "direct_technical_terms": ["pc00_scl_w"]},
            {"pointer": 2, "direct_asset_tokens": ["PC00_Scl_W.g1m", "PC00_Scl_W_default.g1m"], "direct_technical_terms": ["pc00_scl_w"]},
        ]
        selected, rank = M.select_best_wet_roots(roots)
        self.assertEqual(rank, 0)
        self.assertEqual([r["pointer"] for r in selected], [2])

    def test_recurrent_blend_context_requires_wet1_wet2_same_hash_and_absent_dry_blend(self) -> None:
        base = {
            "root_id": "r", "depth": 2, "edge_relative_path": "-56;-488",
            "technical_terms": "blend", "context_sha256": "abc", "_address": 0x1000,
        }
        rows = M.recurrent_blend_contexts([base], [], [dict(base, _address=0x2000)])
        self.assertEqual(len(rows), 1)
        self.assertTrue(rows[0]["same_context_hash_wet1_wet2"])

    def test_recurrent_blend_context_rejects_same_dry_blend_path(self) -> None:
        base = {
            "root_id": "r", "depth": 2, "edge_relative_path": "8;16",
            "technical_terms": "blend", "context_sha256": "abc", "_address": 0x1000,
        }
        self.assertEqual(M.recurrent_blend_contexts([base], [base], [base]), [])

    def test_pointer_neighborhood_records_only_renderer_like_children(self) -> None:
        MapRow = M.S164.MapRow
        root_base = 0x1000
        root_data = bytearray(0x4000)
        root_addr = 0x2800
        child_base = 0x8000
        child_data = bytearray(0x2000)
        child_addr = 0x8800
        # qword 64 bytes after the blend context center
        struct.pack_into("<Q", root_data, (root_addr-root_base)+64, child_addr)
        root_payload = b"BlendState blend"
        roff = root_addr-root_base
        root_data[roff:roff+len(root_payload)] = root_payload
        child_payload = b"material alpha texture pc00_scl_w.g1t"
        coff = child_addr-child_base
        child_data[coff:coff+len(child_payload)] = child_payload
        maps = [
            MapRow(root_base, root_base+len(root_data), "rw-p", 0, "00:00", 0, ""),
            MapRow(child_base, child_base+len(child_data), "rw-p", 0, "00:00", 0, ""),
        ]
        ctx, rows = M.pointer_neighborhood(
            FakeReader({root_base: bytes(root_data), child_base: bytes(child_data)}),
            maps, Path("/tmp/game"), root_addr, state="wet1", candidate_id="c1"
        )
        self.assertTrue(ctx["context_readable"])
        self.assertIn("blend", ctx["direct_render_terms"])
        self.assertTrue(rows)
        row = rows[0]
        self.assertTrue(row["renderer_asset_supported"])
        self.assertTrue(row["strong_binding_term_supported"])
        self.assertIn("alpha", row["child_render_terms"])
        self.assertFalse(row["absolute_pointer_exported"])

    def test_recurrent_binding_rows_require_wet_recurrence_and_absent_dry(self) -> None:
        base = {
            "candidate_id": "c", "field_relative_offset": 64,
            "child_asset_tokens": "pc00_scl_w.g1t", "child_render_terms": "alpha;material;texture",
            "child_context_sha256": "same",
        }
        rows = M.recurrent_binding_rows([base], [], [base])
        self.assertEqual(len(rows), 1)
        self.assertTrue(rows[0]["alpha_or_transparency_term_supported"])
        self.assertTrue(rows[0]["renderer_asset_supported"])
        self.assertFalse(rows[0]["render_resource_binding_confirmed"])
        self.assertFalse(rows[0]["transparency_semantics_confirmed"])

    def test_recurrent_binding_rows_reject_same_dry_child(self) -> None:
        base = {
            "candidate_id": "c", "field_relative_offset": 8,
            "child_asset_tokens": "x.g1t", "child_render_terms": "texture",
            "child_context_sha256": "same",
        }
        self.assertEqual(M.recurrent_binding_rows([base], [base], [base]), [])

    def test_source_declares_read_only_and_no_historical_address_reuse(self) -> None:
        text = MODULE_PATH.read_text(encoding="utf-8")
        self.assertIn("No process memory or game file is written", text)
        self.assertIn('"stage168_historical_pid_reused": False', text)
        self.assertIn('"absolute_process_addresses_exported": False', text)
        self.assertIn('"numeric_or_pointer_field_semantics_inferred": False', text)

    def test_trace_is_more_bounded_than_stage168_graph(self) -> None:
        self.assertLessEqual(M.ROOT_GRAPH_MAX_DEPTH, 2)
        self.assertLessEqual(M.ROOT_GRAPH_MAX_NODES, 72)
        self.assertLessEqual(M.MAX_NEIGHBOR_POINTERS, 64)


if __name__ == "__main__":
    unittest.main()
