#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import struct
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
TOOL_PATH = ROOT / "workstreams/quartet_restoration/collect_reflector_slot_light_local_change_island_evidence.py"
spec = importlib.util.spec_from_file_location("stage87", TOOL_PATH)
assert spec and spec.loader
TOOL = importlib.util.module_from_spec(spec)
spec.loader.exec_module(TOOL)


def make_pair(extra_relative: int | None = None, extra_source: float = 1.0, extra_target: float = 2.0):
    source = bytearray(2048)
    target = bytearray(source)
    center = 1024
    source[center:center + 4] = struct.pack("<f", 150.0)
    source[center + 4:center + 8] = struct.pack("<f", 150.0)
    target[center:center + 4] = struct.pack("<f", 75.0)
    target[center + 4:center + 8] = struct.pack("<f", 75.0)
    if extra_relative is not None:
        offset = center + extra_relative * 4
        source[offset:offset + 4] = struct.pack("<f", extra_source)
        target[offset:offset + 4] = struct.pack("<f", extra_target)
    return bytes(source), bytes(target), [center, center + 4], [center, center + 4]


class ChangeIslandTests(unittest.TestCase):
    def test_discovers_two_leaf_island_between_stable_runs(self):
        source, target, source_centers, target_centers = make_pair()
        island = TOOL.discover_change_island(source, target, source_centers, target_centers, stable_run_dwords=16)
        self.assertEqual(island["changed_dword_rows"], 2)
        self.assertEqual([row["relative_dword"] for row in island["transitions"]], [0, 1])
        self.assertEqual(island["shift_bytes"], 0)

    def test_preserves_candidate_only_residual(self):
        source_a, target_a, centers_a, targets_a = make_pair(extra_relative=12, extra_source=3.0, extra_target=4.0)
        source_b, target_b, centers_b, targets_b = make_pair(extra_relative=-12, extra_source=5.0, extra_target=6.0)
        island_a = TOOL.discover_change_island(source_a, target_a, centers_a, targets_a, stable_run_dwords=16)
        island_b = TOOL.discover_change_island(source_b, target_b, centers_b, targets_b, stable_run_dwords=16)
        map_a = {TOOL.transition_identity(row) for row in island_a["transitions"]}
        map_b = {TOOL.transition_identity(row) for row in island_b["transitions"]}
        self.assertEqual(len(map_a & map_b), 2)
        self.assertEqual(len(map_a - map_b), 1)
        self.assertEqual(len(map_b - map_a), 1)

    def test_supports_constant_nonzero_local_shift(self):
        source = bytearray(2048)
        target = bytearray(2080)
        source_center = 1000
        shift = 16
        target_center = source_center + shift
        source[source_center:source_center + 8] = struct.pack("<ff", 150.0, 150.0)
        target[target_center:target_center + 8] = struct.pack("<ff", 75.0, 75.0)
        island = TOOL.discover_change_island(bytes(source), bytes(target), [source_center, source_center + 4], [target_center, target_center + 4])
        self.assertEqual(island["shift_bytes"], shift)
        self.assertEqual(island["changed_dword_rows"], 2)

    def test_rejects_inconsistent_center_shifts(self):
        source, target, source_centers, target_centers = make_pair()
        with self.assertRaises(TOOL.Stage87Error):
            TOOL.discover_change_island(source, target, source_centers, [target_centers[0], target_centers[1] + 4])

    def test_resolves_sibling_offsets_from_radius_table(self):
        pairs = [{
            "candidate_id": "a", "sibling_normalized_path": "data/x.elixir.gz",
            "sibling_member_key": "control.g1e#0",
        }]
        radii = [{
            "candidate_id": "a", "sibling_normalized_path": "data/x.elixir.gz",
            "sibling_member_key": "control.g1e#0", "radius_dwords": "8",
            "transition_profile_equal": "True", "sibling_source_offset": "100",
            "sibling_target_offset": "120",
        }]
        rows = TOOL.resolve_stage86_pair_rows(pairs, radii)
        self.assertEqual(rows[0]["sibling_source_offset"], "100")
        self.assertEqual(rows[0]["sibling_target_offset"], "120")


if __name__ == "__main__":
    unittest.main()
