#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import struct
import sys
import tempfile
import unittest
from pathlib import Path

MODULE_PATH = Path(__file__).resolve().parents[1] / "167_trace_wet_render_resource_material_binding.py"
spec = importlib.util.spec_from_file_location("wet_resource_stage167", MODULE_PATH)
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
                return data[off:off + size]
        raise OSError("outside fake region")


class Stage167Tests(unittest.TestCase):
    def test_stage166_contract_is_exact_canonical_report(self) -> None:
        project_root = Path(__file__).resolve().parents[3]
        summary = M.verify_stage166_contract(project_root)
        self.assertEqual(summary["stage"], 166)
        self.assertFalse(summary["historical_stage165_absolute_addresses_reused"])
        self.assertEqual(summary["recurrent_wet_pointer_candidate_rows"], 229)

    def test_extract_allowlisted_ascii_asset_and_term(self) -> None:
        assets, terms = M.extract_allowlisted_tokens(b"xx C:/fake/path/PC00_Scl_W_default.g1m material shader yy")
        self.assertIn("PC00_Scl_W_default.g1m", assets)
        self.assertIn("material", terms)
        self.assertIn("shader", terms)
        self.assertFalse(any("C:/" in x for x in assets))

    def test_extract_allowlisted_utf16_asset(self) -> None:
        raw = "PC00_Scl_W_P_School_Wet.g1m texture".encode("utf-16le")
        assets, terms = M.extract_allowlisted_tokens(raw)
        self.assertIn("PC00_Scl_W_P_School_Wet.g1m", assets)
        self.assertIn("texture", terms)

    def test_safe_site_id_never_contains_absolute_address(self) -> None:
        site = {"site_mapping_key": "abc123", "site_mapping_relative_offset": 456, "site_address": 0x7FFF12345678}
        sid = M.safe_site_id(site)
        self.assertTrue(sid.startswith("anchor_"))
        self.assertNotIn("7fff", sid.casefold())
        self.assertEqual(len(sid), len("anchor_") + 12)

    def test_changed_pointer_fields_uses_relative_anchor_descriptor(self) -> None:
        MapRow = M.S164.MapRow
        site_addr = 0x1800
        wet_target = 0x2800
        dry_target = 0x3800
        maps = [
            MapRow(0x1000, 0x2200, "rw-p", 0, "00:00", 0, "[heap]"),
            MapRow(0x2400, 0x3200, "rw-p", 0, "00:00", 0, "[heap]"),
            MapRow(0x3400, 0x4200, "rw-p", 0, "00:00", 0, "[heap]"),
        ]
        size = M.S166.LOCAL_FIELD_RADIUS * 2 + 8
        wet = bytearray(size)
        dry = bytearray(size)
        struct.pack_into("<Q", wet, M.S166.LOCAL_FIELD_RADIUS, wet_target)
        struct.pack_into("<Q", dry, M.S166.LOCAL_FIELD_RADIUS, dry_target)
        sites = [{"site_address": site_addr, "site_mapping_key": M.S164.mapping_key(maps[0]), "site_mapping_relative_offset": site_addr - maps[0].start}]
        rows = M.changed_pointer_fields(sites, {site_addr: bytes(wet)}, {site_addr: bytes(dry)}, maps, maps, Path("/tmp/game"))
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["relative_offset"], 0)
        self.assertIn("anchor_id", rows[0])

    def test_observe_pointer_target_finds_direct_and_one_hop_asset(self) -> None:
        MapRow = M.S164.MapRow
        primary_base = 0x1000
        secondary_base = 0x3000
        primary = bytearray(0x1000)
        secondary = bytearray(0x1000)
        pointer = primary_base + 0x500
        secondary_pointer = secondary_base + 0x500
        # The bounded primary window contains one mapped secondary qword.
        struct.pack_into("<Q", primary, 0x500, secondary_pointer)
        secondary[0x480:0x480 + len(b"pc00_scl_w.g1t texture")] = b"pc00_scl_w.g1t texture"
        maps = [
            MapRow(primary_base, primary_base + len(primary), "rw-p", 0, "00:00", 0, "[heap]"),
            MapRow(secondary_base, secondary_base + len(secondary), "rw-p", 0, "00:00", 0, "[heap]"),
        ]
        obs = M.observe_pointer_target(FakeReader({primary_base: bytes(primary), secondary_base: bytes(secondary)}), maps, Path("/tmp/game"), pointer)
        self.assertTrue(obs["mapped"])
        self.assertIn("pc00_scl_w.g1t", obs["one_hop_asset_tokens"])
        self.assertIn("texture", obs["one_hop_technical_terms"])
        self.assertGreaterEqual(obs["one_hop_token_pointer_rows"], 1)

    def test_classification_prefers_wet_only_asset_token(self) -> None:
        dry = {"mapping_key": "a", "context_sha256": "1", "direct_asset_tokens": [], "one_hop_asset_tokens": [], "direct_technical_terms": [], "one_hop_technical_terms": []}
        wet = {"mapping_key": "b", "context_sha256": "2", "direct_asset_tokens": ["pc00_scl_w.g1t"], "one_hop_asset_tokens": [], "direct_technical_terms": ["texture"], "one_hop_technical_terms": []}
        row = M.classify_binding_candidate("anchor_x", 8, dry, wet)
        self.assertIn("wet_only_asset_token", row["classification"])
        self.assertEqual(row["wet_only_asset_tokens"], "pc00_scl_w.g1t")
        self.assertFalse(row["material_binding_confirmed"])
        self.assertFalse(row["transparency_semantics_confirmed"])

    def test_public_observation_exports_no_absolute_pointer(self) -> None:
        obs = {
            "mapped": True, "mapping_key": "k", "mapping_class": "anonymous", "mapping_permissions": "rw-p",
            "mapping_path_basename": "[heap]", "mapping_path_sha256": "h", "mapping_relative_offset": 123,
            "context_sha256": "c", "direct_asset_tokens": ["x.g1t"], "direct_technical_terms": ["texture"],
            "one_hop_asset_tokens": [], "one_hop_technical_terms": [], "one_hop_token_pointer_rows": 0,
        }
        row = M.observation_public("anchor_a", 4, "wet2", obs)
        self.assertFalse(row["absolute_pointer_exported"])
        self.assertNotIn("pointer_value", row)
        self.assertNotIn("address", row)

    def test_stage167_source_declares_read_only_safety(self) -> None:
        text = MODULE_PATH.read_text(encoding="utf-8")
        self.assertIn("No process memory or game file is written", text)
        self.assertIn("stage166_historical_absolute_addresses_reused", text)
        self.assertIn('"generation10_v2_dependency_used": False', text)


if __name__ == "__main__":
    unittest.main()
