#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import struct
import sys
import unittest
from pathlib import Path

MODULE_PATH = Path(__file__).resolve().parents[1] / "168_trace_wet_renderer_adjacent_pointer_graph.py"
spec = importlib.util.spec_from_file_location("wet_renderer_graph_stage168", MODULE_PATH)
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


class Stage168Tests(unittest.TestCase):
    def test_stage167_contract_is_exact_user_report(self) -> None:
        project_root = Path(__file__).resolve().parents[3]
        summary = M.verify_stage167_contract(project_root)
        self.assertEqual(summary["stage"], 167)
        self.assertEqual(summary["wet_only_asset_token_candidate_rows"], 2)
        self.assertFalse(summary["material_binding_confirmed"])

    def test_graph_terminal_key_contains_no_address(self) -> None:
        row = {"depth": 2, "edge_relative_path": "-8;24", "asset_tokens": "x.g1t", "technical_terms": "material", "mapping_class": "anonymous"}
        key = M.graph_terminal_key(row)
        self.assertEqual(len(key), 24)
        self.assertNotIn("0x", key)

    def test_trace_graph_finds_renderer_adjacent_child(self) -> None:
        MapRow = M.S164.MapRow
        root_base = 0x1000
        child_base = 0x4000
        root = bytearray(0x1000)
        child = bytearray(0x1000)
        root_ptr = root_base + 0x800
        child_ptr = child_base + 0x800
        struct.pack_into("<Q", root, 0x800, child_ptr)
        payload = b"pc00_scl_w.g1t material texture"
        child[0x780:0x780+len(payload)] = payload
        maps = [
            MapRow(root_base, root_base+len(root), "rw-p", 0, "00:00", 0, ""),
            MapRow(child_base, child_base+len(child), "rw-p", 0, "00:00", 0, ""),
        ]
        rows = M.trace_pointer_graph(FakeReader({root_base:bytes(root), child_base:bytes(child)}), maps, Path("/tmp/game"), root_ptr, state="wet1", root_id="r")
        renderer = [r for r in rows if r["renderer_adjacent"]]
        self.assertTrue(renderer)
        self.assertTrue(any("pc00_scl_w.g1t" in r["render_asset_tokens"] for r in renderer))
        self.assertTrue(any("material" in r["render_technical_terms"] for r in renderer))

    def test_recurrent_renderer_rows_requires_wet1_and_wet2_and_absent_dry(self) -> None:
        base = {"root_id":"r", "depth":1, "edge_relative_path":"8", "render_asset_tokens":"x.g1t", "render_technical_terms":"texture", "renderer_adjacent":True, "context_sha256":"a"}
        wet1 = [dict(base)]
        wet2 = [dict(base, context_sha256="b")]
        dry = []
        rows = M.recurrent_renderer_rows(wet1, dry, wet2)
        self.assertEqual(len(rows), 1)
        self.assertTrue(rows[0]["g1t_or_g1s_supported"])
        self.assertFalse(rows[0]["render_resource_binding_confirmed"])
        self.assertFalse(rows[0]["transparency_semantics_confirmed"])

    def test_recurrent_renderer_rows_rejects_same_dry_path(self) -> None:
        base = {"root_id":"r", "depth":1, "edge_relative_path":"8", "render_asset_tokens":"x.g1s", "render_technical_terms":"shader", "renderer_adjacent":True, "context_sha256":"a"}
        self.assertEqual(M.recurrent_renderer_rows([base], [base], [base]), [])

    def test_wet2_root_classifier_accepts_recurrent_wet_school_target(self) -> None:
        MapRow = M.S164.MapRow
        base = 0x1000
        data = bytearray(0x5000)
        pointer = base + 0x2800
        payload = b"PC00_Scl_W.g1m material texture"
        off = pointer - base
        data[off:off+len(payload)] = payload
        maps = [MapRow(base, base+len(data), "rw-p", 0, "00:00", 0, "")]
        status, assets, terms = M.classify_wet2_root_target(FakeReader({base:bytes(data)}), maps, Path("/tmp/game"), pointer)
        self.assertEqual(status, "recurrent_wet_school")
        self.assertIn("PC00_Scl_W.g1m", assets)

    def test_wet2_root_classifier_rejects_transient_candidate_without_exception(self) -> None:
        MapRow = M.S164.MapRow
        base = 0x1000
        data = bytearray(0x5000)
        pointer = base + 0x2800
        payload = b"PC00_Scl_default.g1m material texture"
        off = pointer - base
        data[off:off+len(payload)] = payload
        maps = [MapRow(base, base+len(data), "rw-p", 0, "00:00", 0, "")]
        status, assets, terms = M.classify_wet2_root_target(FakeReader({base:bytes(data)}), maps, Path("/tmp/game"), pointer)
        self.assertEqual(status, "non_wet_school_target")
        self.assertIn("PC00_Scl_default.g1m", assets)

    def test_wet2_root_classifier_handles_missing_field_as_nonfatal(self) -> None:
        status, assets, terms = M.classify_wet2_root_target(FakeReader({}), [], Path("/tmp/game"), None)
        self.assertEqual(status, "missing_field")
        self.assertEqual(assets, [])
        self.assertEqual(terms, [])

    def test_pointer_at_field_uses_relative_offset(self) -> None:
        site = 0x5000
        size = M.S166.LOCAL_FIELD_RADIUS * 2 + 8
        blob = bytearray(size)
        value = 0x123456789
        struct.pack_into("<Q", blob, M.S166.LOCAL_FIELD_RADIUS + 16, value)
        self.assertEqual(M.pointer_at_field(bytes(blob), site, 16), value)

    def test_source_declares_read_only_and_no_historical_address_reuse(self) -> None:
        text = MODULE_PATH.read_text(encoding="utf-8")
        self.assertIn("No process memory or game file is written", text)
        self.assertIn('"stage167_historical_pid_reused": False', text)
        self.assertIn('"absolute_process_addresses_exported": False', text)
        self.assertIn('"numeric_or_pointer_field_semantics_inferred": False', text)

    def test_constants_keep_graph_bounded(self) -> None:
        self.assertLessEqual(M.MAX_DEPTH, 3)
        self.assertLessEqual(M.MAX_GRAPH_NODES, 96)
        self.assertLessEqual(M.MAX_FANOUT, 24)


if __name__ == "__main__":
    unittest.main()
