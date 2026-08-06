from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
TOOL_PATH = ROOT / "workstreams/quartet_restoration/153_collect_hinako_wet_school_material_submesh_remap_evidence.py"
SPEC = importlib.util.spec_from_file_location("stage153", TOOL_PATH)
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


def shader_block(idx: int, value: str):
    return [{
        "shader_block_index": idx, "parameter_index": 0, "parameter_name": "WetScalar",
        "parameter_name_folded": "wetscalar", "parameter_occurrence": 0,
        "buffer_type": 1, "buffer_count": 1, "value_hex": value,
    }]


def submesh(idx: int, *, material_index: int, shader_index: int, geom: int, record_offset: int):
    return {
        "submesh_index": idx, "record_offset": record_offset,
        "submeshFlags": 0, "vertexBufferIndex": 0, "bonePaletteIndex": 0, "boneIndex": 0,
        "unknown": 0, "shaderParamIndex": shader_index, "materialIndex": material_index,
        "indexBufferIndex": 0, "unknown2": 0, "indexBufferPrimType": 3,
        "vertexBufferOffset": geom * 100, "vertexCount": 12 + geom,
        "indexBufferOffset": geom * 200, "indexCount": 18 + geom,
    }


def lod(name: str, indices: list[int]):
    return {"name": name, "indices": indices}


def parsed(material_rows, shader_rows, submesh_rows, lod_rows):
    return {"materials": material_rows, "shader_params": shader_rows, "submeshes": submesh_rows, "mesh_lod": lod_rows}


class Stage153Tests(unittest.TestCase):
    def test_material_fingerprint_matches_across_relocated_ordinal(self):
        src = parsed(material(3, (21, 23, 27)), [], [], [])
        tgt = parsed(material(4, (21, 23, 27)), [], [], [])
        rows = TOOL.analyze_wet_pair(src, tgt)["materials"]
        self.assertEqual(len(rows), 1)
        self.assertTrue(rows[0]["unique_target_texture_match"])
        self.assertEqual(rows[0]["target_match_material_index"], 4)
        self.assertFalse(rows[0]["same_ordinal"])
        self.assertFalse(rows[0]["write_authorized"])

    def test_shader_block_fingerprint_matches_across_relocated_ordinal(self):
        src = parsed([], shader_block(3, "0000803f"), [], [])
        tgt = parsed([], shader_block(7, "0000803f"), [], [])
        row = TOOL.analyze_wet_pair(src, tgt)["shader_blocks"][0]
        self.assertTrue(row["unique_target_shader_match"])
        self.assertEqual(row["target_match_shader_block_index"], 7)
        self.assertFalse(row["same_ordinal"])

    def test_unique_strong_geometry_plus_native_pair_exemplar_is_bounded_candidate(self):
        src = parsed(
            material(3, (21, 23, 27)), shader_block(3, "0000803f"),
            [submesh(0, material_index=3, shader_index=3, geom=1, record_offset=1000)],
            [lod("PBS_WET", [0])],
        )
        tgt = parsed(
            material(2, (99,)) + material(4, (21, 23, 27)),
            shader_block(2, "0000003f") + shader_block(4, "0000803f"),
            [
                submesh(5, material_index=2, shader_index=2, geom=1, record_offset=2000),
                submesh(6, material_index=4, shader_index=4, geom=2, record_offset=3000),
            ],
            [lod("PBS_WET", [5, 6])],
        )
        out = TOOL.analyze_wet_pair(src, tgt)
        self.assertEqual(len(out["candidates"]), 1)
        row = out["candidates"][0]
        self.assertEqual(row["mapping_strength"], "unique_strong_geometry")
        self.assertEqual(row["target_wet_submesh_index"], 5)
        self.assertEqual(row["desired_target_material_index"], 4)
        self.assertEqual(row["desired_target_shader_param_index"], 4)
        self.assertTrue(row["target_native_exact_pair_exemplar_exists"])
        self.assertEqual(row["target_material_index_offset"], 2024)
        self.assertEqual(row["target_shader_param_index_offset"], 2020)
        self.assertFalse(row["write_authorized"])

    def test_missing_native_pair_exemplar_blocks_candidate(self):
        src = parsed(
            material(3, (21, 23, 27)), shader_block(3, "0000803f"),
            [submesh(0, material_index=3, shader_index=3, geom=1, record_offset=1000)],
            [lod("PBS_WET", [0])],
        )
        tgt = parsed(
            material(2, (99,)) + material(4, (21, 23, 27)),
            shader_block(2, "0000003f") + shader_block(4, "0000803f"),
            [submesh(5, material_index=2, shader_index=2, geom=1, record_offset=2000)],
            [lod("PBS_WET", [5])],
        )
        out = TOOL.analyze_wet_pair(src, tgt)
        self.assertEqual(len(out["candidates"]), 0)
        self.assertFalse(out["submeshes"][0]["target_native_exact_pair_exemplar_exists"])

    def test_topology_only_mapping_is_not_write_candidate(self):
        src = parsed(
            material(3, (21,)), shader_block(3, "0000803f"),
            [submesh(0, material_index=3, shader_index=3, geom=1, record_offset=1000)],
            [lod("PBS_WET", [0])],
        )
        trow = submesh(5, material_index=4, shader_index=4, geom=1, record_offset=2000)
        trow["vertexBufferOffset"] += 16
        trow["indexBufferOffset"] += 24
        exemplar = submesh(6, material_index=4, shader_index=4, geom=2, record_offset=3000)
        tgt = parsed(
            material(4, (21,)), shader_block(4, "0000803f"), [trow, exemplar],
            [lod("PBS_WET", [5, 6])],
        )
        out = TOOL.analyze_wet_pair(src, tgt)
        self.assertEqual(out["submeshes"][0]["mapping_strength"], "unique_topology_geometry")
        self.assertFalse(out["submeshes"][0]["bounded_binding_candidate"])
        self.assertEqual(len(out["candidates"]), 0)

    def test_duplicate_target_material_fingerprint_blocks_unique_mapping(self):
        src = parsed(material(3, (21,)), [], [], [])
        tgt = parsed(material(4, (21,)) + material(5, (21,)), [], [], [])
        row = TOOL.analyze_wet_pair(src, tgt)["materials"][0]
        self.assertFalse(row["unique_target_texture_match"])
        self.assertEqual(row["target_wet_matching_material_indices"], "4,5")

    def test_shared_lod_name_is_required_for_bounded_candidate(self):
        src = parsed(
            material(3, (21,)), shader_block(3, "0000803f"),
            [submesh(0, material_index=3, shader_index=3, geom=1, record_offset=1000)], [lod("SRC", [0])],
        )
        tgt = parsed(
            material(2, (99,)) + material(4, (21,)), shader_block(2, "0000003f") + shader_block(4, "0000803f"),
            [submesh(5, material_index=2, shader_index=2, geom=1, record_offset=2000), submesh(6, material_index=4, shader_index=4, geom=2, record_offset=3000)],
            [lod("TGT", [5, 6])],
        )
        out = TOOL.analyze_wet_pair(src, tgt)
        self.assertEqual(out["submeshes"][0]["shared_mesh_lod_names"], "")
        self.assertFalse(out["submeshes"][0]["bounded_binding_candidate"])

    def test_stage152_prerequisite_hash_is_immutable(self):
        self.assertEqual(TOOL.STAGE152_SHA256, "a96c875a5d47c0f3ecf2721c634723b245556438f8a0ad5597de212f426b3e6a")
        self.assertEqual(TOOL.STAGE151_SHA256, "68bb8760691bb01833af87c7ff6ed5c05868e360b1a4a6363bb9a8c187c5f1b9")

    def test_report_policy_forbids_payloads(self):
        joined = " ".join(TOOL.FORBIDDEN_REPORT_EXTENSIONS)
        for ext in (".pak", ".g1m", ".elixir", ".kps"):
            self.assertIn(ext, joined)


if __name__ == "__main__":
    unittest.main()
