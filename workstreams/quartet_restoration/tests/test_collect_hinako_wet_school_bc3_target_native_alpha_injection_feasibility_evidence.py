import importlib.util
import unittest
from pathlib import Path

MODULE_PATH = Path(__file__).resolve().parents[1] / "160_collect_hinako_wet_school_bc3_target_native_alpha_injection_feasibility_evidence.py"
spec = importlib.util.spec_from_file_location("stage160", MODULE_PATH)
mod = importlib.util.module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(mod)


def block(alpha: bytes, color: bytes) -> bytes:
    assert len(alpha) == 8 and len(color) == 8
    return alpha + color


class Stage160Tests(unittest.TestCase):
    def test_version_and_prerequisite_are_frozen(self):
        self.assertEqual(mod.TOOL_VERSION, "0.1.81")
        self.assertEqual(mod.STAGE159_SHA256, "91c077ca408bed741d2cc297f4deec574bad361c16fc32b334f18666092e260d")

    def test_bc3_layout_matches_known_entry_sizes(self):
        src = mod.bc3_mip_layout(256, 256, 3)
        tgt = mod.bc3_mip_layout(2048, 2048, 3)
        self.assertEqual(sum(r["size"] for r in src), 86016)
        self.assertEqual(sum(r["size"] for r in tgt), 5505024)

    def test_alpha_injection_preserves_target_color(self):
        src_alpha = bytes(range(8))
        src = block(src_alpha, b"S" * 8)
        tgt_blocks = [block(b"T" * 8, bytes([i]) * 8) for i in range(64)]
        out, rows = mod.inject_scaled_bc3_alpha(src, 4, 4, 1, b"".join(tgt_blocks), 32, 32, 1)
        self.assertEqual(rows[0]["block_scale"], 8)
        for i in range(64):
            b = out[i * 16:(i + 1) * 16]
            self.assertEqual(b[:8], src_alpha)
            self.assertEqual(b[8:], bytes([i]) * 8)

    def test_alpha_injection_maps_multiple_source_blocks(self):
        a0 = b"A" * 8
        a1 = b"B" * 8
        a2 = b"C" * 8
        a3 = b"D" * 8
        src = b"".join([block(a0, b"x"*8), block(a1, b"x"*8), block(a2, b"x"*8), block(a3, b"x"*8)])
        # source 8x8 = 2x2 blocks; target 16x16 = 4x4 blocks => scale 2.
        tgt = b"".join(block(b"t"*8, bytes([i])*8) for i in range(16))
        out, rows = mod.inject_scaled_bc3_alpha(src, 8, 8, 1, tgt, 16, 16, 1)
        self.assertEqual(rows[0]["block_scale"], 2)
        expected = [a0,a0,a1,a1,a0,a0,a1,a1,a2,a2,a3,a3,a2,a2,a3,a3]
        self.assertEqual([out[i*16:i*16+8] for i in range(16)], expected)

    def test_histogram_validation_accounts_for_8x8_replication(self):
        source = [1, 2, 0, 4] + [0] * 12
        candidate = [64, 128, 0, 256] + [0] * 12
        self.assertTrue(mod.histogram_scaled_exactly(source, candidate, 64))
        self.assertFalse(mod.histogram_scaled_exactly(source, source, 64))
        self.assertFalse(mod.histogram_scaled_exactly(source, candidate, 0))

    def test_alpha_injection_rejects_mip_count_mismatch(self):
        with self.assertRaises(mod.Stage160Error):
            mod.inject_scaled_bc3_alpha(b"\0"*16, 4, 4, 1, b"\0"*32, 8, 4, 2)

    def test_alpha_injection_rejects_nonintegral_scale(self):
        with self.assertRaises(mod.Stage160Error):
            mod.inject_scaled_bc3_alpha(b"\0"*64, 8, 8, 1, b"\0"*144, 12, 12, 1)

    def test_candidate_contract_does_not_authorize_write(self):
        source = Path(MODULE_PATH).read_text(encoding="utf-8")
        self.assertIn('"write_authorized": False', source)
        self.assertIn('"candidate_profile_built": False', source)
        self.assertIn('"installed_game_modified": False', source)

    def test_forbidden_report_extensions_include_game_and_images(self):
        for ext in (".g1t", ".pak", ".dds", ".png", ".webp"):
            self.assertIn(ext, mod.FORBIDDEN_REPORT_EXTENSIONS)


if __name__ == "__main__":
    unittest.main()
