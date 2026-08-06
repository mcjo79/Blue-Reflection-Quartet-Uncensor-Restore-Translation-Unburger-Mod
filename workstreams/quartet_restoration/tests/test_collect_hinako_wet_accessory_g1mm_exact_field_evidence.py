from __future__ import annotations

import importlib.util
import struct
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
TOOL_PATH = ROOT / "workstreams/quartet_restoration/152_collect_hinako_wet_accessory_g1mm_exact_field_evidence.py"
SPEC = importlib.util.spec_from_file_location("stage152", TOOL_PATH)
assert SPEC and SPEC.loader
TOOL = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = TOOL
SPEC.loader.exec_module(TOOL)


def make_g1m(words: list[int], *, version: int = 0x30303230) -> bytes:
    assert len(words) == 17  # 12-byte chunk header + 68-byte body = 80 bytes
    body = struct.pack("<17I", *words)
    chunk = b"MM1G" + struct.pack("<2I", version, 80) + body
    total = 24 + len(chunk)
    return b"_M1G" + struct.pack("<5I", 0x30303434, total, 24, 0, 1) + chunk


def parsed(words: list[int]):
    return TOOL.extract_g1mm_chunk(make_g1m(words), label="fixture")


class Stage152Tests(unittest.TestCase):
    def test_extracts_single_80_byte_g1mm_with_exact_locator(self):
        row = parsed(list(range(17)))
        self.assertEqual(row["chunk_magic"], "MM1G")
        self.assertEqual(row["chunk_size"], 80)
        self.assertEqual(row["chunk_offset"], 24)
        self.assertEqual(row["chunk_version"], "0x30303230")

    def test_exact_base_control_field_is_candidate_only(self):
        base = list(range(17))
        sw = base.copy(); sw[5] = 0x12345678
        td = base.copy(); tw = base.copy()
        control, fields, runs = TOOL.analyze_chunks("scl->scl_w", {
            "source_dry": parsed(base), "source_wet": parsed(sw),
            "target_dry": parsed(td), "target_wet": parsed(tw),
        })
        hits = [r for r in fields if r["classification"] == "original_wet_transition_missing_in_quartet_exact_base_control"]
        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0]["chunk_relative_offset"], 12 + 5 * 4)
        self.assertEqual(hits[0]["target_wet_g1m_absolute_offset"], 24 + 12 + 5 * 4)
        self.assertEqual(hits[0]["target_precondition_hex"], struct.pack("<I", 5).hex())
        self.assertEqual(hits[0]["source_wet_desired_hex"], struct.pack("<I", 0x12345678).hex())
        self.assertFalse(hits[0]["write_authorized"])
        self.assertTrue(control["exact_aligned_layout"])
        self.assertGreaterEqual(len(runs), 1)

    def test_base_difference_blocks_exact_field_candidate(self):
        sd = list(range(17)); sw = sd.copy(); sw[4] = 0x99999999
        td = sd.copy(); td[4] = 0x22222222; tw = td.copy()
        _, fields, _ = TOOL.analyze_chunks("scl->scl_w", {
            "source_dry": parsed(sd), "source_wet": parsed(sw),
            "target_dry": parsed(td), "target_wet": parsed(tw),
        })
        row = next(r for r in fields if r["chunk_relative_offset"] == 12 + 4 * 4)
        self.assertEqual(row["classification"], "original_wet_transition_missing_in_quartet_base_differs")
        self.assertFalse(row["exact_base_control"])
        self.assertEqual(row["source_wet_desired_hex"], "")

    def test_target_wet_transition_is_not_misclassified_as_missing(self):
        sd = list(range(17)); sw = sd.copy(); sw[3] = 10
        td = sd.copy(); tw = td.copy(); tw[3] = 11
        _, fields, _ = TOOL.analyze_chunks("swm->swm_w", {
            "source_dry": parsed(sd), "source_wet": parsed(sw),
            "target_dry": parsed(td), "target_wet": parsed(tw),
        })
        row = next(r for r in fields if r["chunk_relative_offset"] == 12 + 3 * 4)
        self.assertEqual(row["classification"], "wet_transition_differs_between_games")

    def test_changed_runs_record_metadata_only(self):
        before = b"abcdefgh"
        after = b"abXXefYh"
        self.assertEqual(TOOL.changed_runs(before, after), [(2, 2), (6, 1)])

    def test_stage151_uploaded_prerequisite_contract_is_exact(self):
        root = ROOT / ".local/reports/quartet_restoration"
        summary = TOOL.validate_stage151(root)
        self.assertEqual(summary["exact_base_control_material_rows"], 0)
        self.assertEqual(summary["exact_base_control_direct_scalar_probe_rows"], 0)
        self.assertTrue(summary["whole_g1mm_transplant_reuse_forbidden"])

    def test_failed_composite_guard_remains_canonical(self):
        registry = __import__("json").loads((ROOT / "workstreams/quartet_restoration/RUNTIME_VALIDATION_REGISTRY.json").read_text())
        failed = registry["fast_test_results"][TOOL.FAILED_PROFILE_ID]
        self.assertTrue(failed["severe_model_corruption_observed"])
        self.assertFalse(failed["runtime_stable"])
        self.assertFalse(failed["runtime_validated"])
        self.assertTrue(failed["whole_g1mm_transplant_reuse_forbidden"])

    def test_report_policy_forbids_proprietary_payloads(self):
        joined = " ".join(TOOL.FORBIDDEN_REPORT_EXTENSIONS)
        for ext in (".pak", ".g1m", ".elixir", ".kps"):
            self.assertIn(ext, joined)


if __name__ == "__main__":
    unittest.main()
