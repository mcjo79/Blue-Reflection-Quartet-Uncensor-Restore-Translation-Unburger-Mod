from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
TOOL_PATH = ROOT / "workstreams/quartet_restoration/154_collect_hinako_wet_school_shader_schema_material_usage_evidence.py"
SPEC = importlib.util.spec_from_file_location("stage154", TOOL_PATH)
assert SPEC and SPEC.loader
TOOL = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = TOOL
SPEC.loader.exec_module(TOOL)


def material(idx: int, texture_ids: tuple[int, ...]):
    out = []
    for slot, tid in enumerate(texture_ids):
        out.append({
            "material_index": idx, "texture_slot": slot, "unknown1": 0, "texture_count": len(texture_ids),
            "unknown2": 0, "unknown3": 0, "texture_id": tid, "layer": 0, "texture_type": 1,
            "subtype": 0, "tilemodex": 4, "tilemodey": 4,
        })
    return out


def shader_block(idx: int, value: str, *, name: str = "WetScalar", offset: int = 100):
    return [{
        "shader_block_index": idx, "parameter_index": 0, "parameter_name": name,
        "parameter_name_folded": name.casefold(), "parameter_occurrence": 0,
        "buffer_type": 1, "buffer_count": 1, "value_hex": value,
        "value_offset": offset,
    }]


def submesh(idx: int, material_index: int, shader_index: int, record_offset: int = 1000):
    return {
        "submesh_index": idx, "record_offset": record_offset,
        "materialIndex": material_index, "shaderParamIndex": shader_index,
    }


def parsed(material_rows, shader_rows, submesh_rows):
    return {"materials": material_rows, "shader_params": shader_rows, "submeshes": submesh_rows, "mesh_lod": []}


def variants(*, sw="0000803f", tw="00000000", sd="00000000", td="00000000"):
    return {
        "source_dry": parsed(material(0, (90,)), shader_block(2, sd, offset=200), [submesh(0, 0, 2)]),
        "source_wet": parsed(material(3, (21, 23, 27)), shader_block(3, sw, offset=300), [submesh(1, 3, 3)]),
        "target_dry": parsed(material(1, (91,)), shader_block(5, td, offset=500), [submesh(2, 1, 5)]),
        "target_wet": parsed(material(4, (21, 23, 27)), shader_block(7, tw, offset=700), [submesh(3, 4, 7)]),
    }


class Stage154Tests(unittest.TestCase):
    def test_shader_schema_fingerprint_ignores_value(self):
        a = TOOL.shader_blocks(parsed([], shader_block(1, "00000000"), []))[1]
        b = TOOL.shader_blocks(parsed([], shader_block(9, "0000803f"), []))[9]
        self.assertEqual(a["schema_fingerprint"], b["schema_fingerprint"])
        self.assertNotEqual(a["value_fingerprint"], b["value_fingerprint"])

    def test_material_scoped_schema_alignment_finds_relocated_block(self):
        out = TOOL.analyze_variants(variants())
        focus = [r for r in out["shader_schema"] if r["focus_material"]]
        self.assertEqual(len(focus), 1)
        self.assertTrue(focus[0]["unique_target_wet_material_scoped_schema_match"])
        self.assertEqual(focus[0]["target_wet_shader_block_index"], 7)

    def test_exact_base_control_missing_wet_transition_is_bounded_scalar_candidate(self):
        out = TOOL.analyze_variants(variants(sw="0000803f", tw="00000000", sd="00000000", td="00000000"))
        self.assertEqual(len(out["candidates"]), 1)
        row = out["candidates"][0]
        self.assertTrue(row["exact_base_control_missing_wet_transition"])
        self.assertTrue(row["four_byte_scalar"])
        self.assertEqual(row["target_wet_value_offset"], 700)
        self.assertEqual(row["target_before_hex"], "00000000")
        self.assertEqual(row["source_wet_desired_hex"], "0000803f")
        self.assertFalse(row["write_authorized"])

    def test_matching_wet_transition_is_not_candidate(self):
        out = TOOL.analyze_variants(variants(sw="0000803f", tw="0000803f", sd="00000000", td="00000000"))
        self.assertEqual(len(out["candidates"]), 0)
        row = out["parameters"][0]
        self.assertTrue(row["matching_wet_transition"])
        self.assertFalse(row["cross_game_wet_value_differs"])

    def test_ambiguous_target_material_scoped_schema_blocks_parameter_probe(self):
        v = variants()
        v["target_wet"]["shader_params"] += shader_block(8, "00000000", offset=800)
        v["target_wet"]["submeshes"].append(submesh(4, 4, 8))
        out = TOOL.analyze_variants(v)
        focus = [r for r in out["shader_schema"] if r["focus_material"]]
        self.assertEqual(focus[0]["target_wet_material_scoped_schema_matches"], "7,8")
        self.assertFalse(focus[0]["unique_target_wet_material_scoped_schema_match"])
        self.assertEqual(len(out["parameters"]), 0)
        self.assertEqual(len(out["candidates"]), 0)

    def test_unused_material_cannot_create_bounded_candidate(self):
        v = variants()
        v["target_wet"]["submeshes"] = []
        out = TOOL.analyze_variants(v)
        self.assertEqual(len(out["candidates"]), 0)
        focus_usage = [r for r in out["material_usage"] if r["focus_material"]][0]
        self.assertFalse(focus_usage["target_material_is_used"])

    def test_stage153_prerequisite_hash_is_immutable(self):
        self.assertEqual(TOOL.STAGE153_SHA256, "301bc4b6137dd9a6af756185ab4727ad6f09ef19eb97c6f5583f0ac60dd2e877")
        self.assertEqual(TOOL.STAGE152_SHA256, "a96c875a5d47c0f3ecf2721c634723b245556438f8a0ad5597de212f426b3e6a")
        self.assertEqual(TOOL.STAGE151_SHA256, "68bb8760691bb01833af87c7ff6ed5c05868e360b1a4a6363bb9a8c187c5f1b9")

    def test_report_policy_forbids_payloads(self):
        joined = " ".join(TOOL.FORBIDDEN_REPORT_EXTENSIONS)
        for ext in (".pak", ".g1m", ".elixir", ".kps"):
            self.assertIn(ext, joined)


if __name__ == "__main__":
    unittest.main()
