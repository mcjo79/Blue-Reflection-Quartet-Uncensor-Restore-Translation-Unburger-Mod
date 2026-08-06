from __future__ import annotations

import importlib.util
import json
import struct
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
TOOL_PATH = ROOT / "workstreams/quartet_restoration/151_collect_hinako_wet_school_g1mg_binding_differential_evidence.py"
SPEC = importlib.util.spec_from_file_location("stage151", TOOL_PATH)
assert SPEC and SPEC.loader
TOOL = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = TOOL
SPEC.loader.exec_module(TOOL)


def shader_param(name: str, value: float) -> bytes:
    nb = name.encode() + b"\0"
    raw = struct.pack("<f", value)
    size = 16 + len(nb) + len(raw)
    return struct.pack("<3I2H", size, len(nb), 0, 1, 1) + nb + raw


def make_g1m(*, shader_value: float = 1.0, texture_id: int = 10,
             material_index: int = 2, shader_param_index: int = 3,
             shader_name: str = "PBS", lod_indices=(0,)) -> bytes:
    sections = []
    # MATERIALS: one material, one texture assignment.
    body = struct.pack("<4I", 0, 1, 0, 0) + struct.pack("<6H", texture_id, 0, 1, 0, 1, 1)
    sections.append(struct.pack("<3I", TOOL.G1MG_MATERIALS, 12 + len(body), 1) + body)
    # SHADER_PARAMS: one block, one scalar.
    body = struct.pack("<I", 1) + shader_param("WetScalar", shader_value)
    sections.append(struct.pack("<3I", TOOL.G1MG_SHADER_PARAMS, 12 + len(body), 1) + body)
    # SUBMESH: one fixed 14-dword record.
    vals = [0, 0, 0, 0, 0, shader_param_index, material_index, 0, 0, 0, 0, 1, 0, 3]
    body = struct.pack("<14I", *vals)
    sections.append(struct.pack("<3I", TOOL.G1MG_SUBMESH, 12 + len(body), 1) + body)
    # MESH_LOD for version 0x30303430: block/group/count/range + one entry.
    name = shader_name.encode()[:15].ljust(16, b"\0")
    body = struct.pack("<I2I2I4I", 0, 0, 0, 1, 0, 0, 0, 0, 0)
    body += name + struct.pack("<2H2I", 0, 0, 0, len(lod_indices))
    if lod_indices:
        body += struct.pack("<%dI" % len(lod_indices), *lod_indices)
    else:
        body += struct.pack("<I", 0)
    sections.append(struct.pack("<3I", TOOL.G1MG_MESH_LOD, 12 + len(body), 1) + body)

    sec = b"".join(sections)
    g1mg_size = TOOL.G1MG_HEADER_SIZE + len(sec)
    g1mg = (b"G1MG" + struct.pack("<2I", 0x30303430, g1mg_size) + b"DX11" +
            struct.pack("<I6f", 0, 0, 0, 0, 1, 1, 1) + struct.pack("<I", len(sections)) + sec)
    total = TOOL.G1M_HEADER_SIZE + len(g1mg)
    return b"_M1G" + struct.pack("<5I", 0x30303430, total, TOOL.G1M_HEADER_SIZE, 0, 1) + g1mg


class Stage151Tests(unittest.TestCase):
    def test_parser_extracts_all_bounded_binding_sections(self):
        parsed = TOOL.parse_g1mg_binding_metadata(make_g1m(), label="fixture")
        self.assertEqual(len(parsed["materials"]), 1)
        self.assertEqual(len(parsed["shader_params"]), 1)
        self.assertEqual(len(parsed["submeshes"]), 1)
        self.assertEqual(len(parsed["mesh_lod"]), 1)
        self.assertEqual(parsed["materials"][0]["texture_id"], 10)
        self.assertEqual(parsed["submeshes"][0]["materialIndex"], 2)
        self.assertEqual(parsed["mesh_lod"][0]["name"], "PBS")

    def test_shader_parameter_has_exact_target_value_locator(self):
        payload = make_g1m(shader_value=1.25)
        parsed = TOOL.parse_g1mg_binding_metadata(payload, label="fixture")
        row = parsed["shader_params"][0]
        off = row["value_offset"]
        self.assertEqual(payload[off:off + row["value_size"]].hex(), row["value_hex"])
        self.assertEqual(struct.unpack("<f", payload[off:off+4])[0], 1.25)

    def test_four_way_exact_base_scalar_becomes_candidate_not_authorized(self):
        variants = {
            "source_dry": TOOL.parse_g1mg_binding_metadata(make_g1m(shader_value=1.0)),
            "source_wet": TOOL.parse_g1mg_binding_metadata(make_g1m(shader_value=0.25)),
            "target_dry": TOOL.parse_g1mg_binding_metadata(make_g1m(shader_value=1.0)),
            "target_wet": TOOL.parse_g1mg_binding_metadata(make_g1m(shader_value=1.0)),
        }
        rows = TOOL.analyze_role("default.g1m", variants)["shader_params"]
        row = next(r for r in rows if r["parameter_name"] == "wetscalar")
        self.assertEqual(row["classification"], "original_wet_transition_missing_in_quartet_exact_base_control")
        self.assertTrue(row["direct_scalar_probe_candidate"])
        self.assertFalse(row["write_authorized"])
        self.assertEqual(row["original_wet_desired_hex"], struct.pack("<f", .25).hex())

    def test_base_difference_prevents_direct_scalar_candidate(self):
        variants = {
            "source_dry": TOOL.parse_g1mg_binding_metadata(make_g1m(shader_value=1.0)),
            "source_wet": TOOL.parse_g1mg_binding_metadata(make_g1m(shader_value=0.25)),
            "target_dry": TOOL.parse_g1mg_binding_metadata(make_g1m(shader_value=2.0)),
            "target_wet": TOOL.parse_g1mg_binding_metadata(make_g1m(shader_value=2.0)),
        }
        row = TOOL.analyze_role("default.g1m", variants)["shader_params"][0]
        self.assertEqual(row["classification"], "original_wet_transition_missing_in_quartet_base_differs")
        self.assertFalse(row["direct_scalar_probe_candidate"])

    def test_material_submesh_and_lod_missing_wet_transitions_are_reported(self):
        dry = make_g1m(texture_id=10, material_index=2, shader_param_index=3, shader_name="PBS", lod_indices=(0,))
        wet = make_g1m(texture_id=11, material_index=4, shader_param_index=5, shader_name="PBS_WET", lod_indices=(1,))
        variants = {
            "source_dry": TOOL.parse_g1mg_binding_metadata(dry),
            "source_wet": TOOL.parse_g1mg_binding_metadata(wet),
            "target_dry": TOOL.parse_g1mg_binding_metadata(dry),
            "target_wet": TOOL.parse_g1mg_binding_metadata(dry),
        }
        out = TOOL.analyze_role("default.g1m", variants)
        for key in ("materials", "submeshes", "mesh_lod"):
            self.assertEqual(len(out[key]), 1)
            self.assertEqual(out[key][0]["classification"], "original_wet_transition_missing_in_quartet_exact_base_control")
            self.assertFalse(out[key][0]["write_authorized"])

    def test_canonical_runtime_failure_guard_is_present(self):
        obs = json.loads(TOOL.OBSERVATION_PATH.read_text())
        self.assertTrue(obs["runtime_tested"])
        self.assertTrue(obs["severe_model_corruption_observed"])
        self.assertFalse(obs["runtime_stable"])
        self.assertFalse(obs["runtime_validated"])
        self.assertTrue(obs["whole_g1mm_transplant_reuse_forbidden"])
        self.assertTrue(obs["exact_pack10_02_baseline_restored"])

    def test_registry_preserves_stable_partial_and_records_failed_composite(self):
        reg = json.loads((TOOL.SCRIPT_DIR / "RUNTIME_VALIDATION_REGISTRY.json").read_text())
        stable = reg["fast_test_results"]["fast_test_pc00_scl_w_school_wet_original_member_b98a68625fe3"]
        failed = reg["fast_test_results"][TOOL.FAILED_PROFILE_ID]
        self.assertTrue(stable["runtime_stable"])
        self.assertTrue(stable["partial_visual_restoration_confirmed"])
        self.assertFalse(stable["target_transparency_restored"])
        self.assertFalse(failed["runtime_stable"])
        self.assertTrue(failed["severe_model_corruption_observed"])
        self.assertTrue(failed["whole_g1mm_transplant_reuse_forbidden"])

    def test_report_extension_policy_forbids_payloads(self):
        joined = " ".join(TOOL.FORBIDDEN_REPORT_EXTENSIONS)
        for ext in (".pak", ".g1m", ".elixir", ".kps"):
            self.assertIn(ext, joined)


if __name__ == "__main__":
    unittest.main()
