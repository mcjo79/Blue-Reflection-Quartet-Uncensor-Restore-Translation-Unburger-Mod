import importlib.util
import struct
import unittest
from pathlib import Path

MODULE_PATH = Path(__file__).resolve().parents[1] / "159_collect_hinako_wet_school_bc3_alpha_transition_evidence.py"
spec = importlib.util.spec_from_file_location("stage159", MODULE_PATH)
mod = importlib.util.module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(mod)


def bc3_block(alpha_index=0, *, a0=255, a1=0, c0=0xFFFF, c1=0x0000, color_index=0):
    abits = 0
    cbits = 0
    for i in range(16):
        abits |= (alpha_index & 7) << (3 * i)
        cbits |= (color_index & 3) << (2 * i)
    return bytes([a0, a1]) + abits.to_bytes(6, "little") + struct.pack("<HHI", c0, c1, cbits)


class Stage159Tests(unittest.TestCase):
    def test_version_and_prerequisite_hashes_are_frozen(self):
        self.assertEqual(mod.TOOL_VERSION, "0.1.79")
        self.assertEqual(mod.STAGE155_SHA256, "91944b1da27e935695cb8c8c6781b276995cf9798b60262e810bfe385573da0d")
        self.assertEqual(mod.STAGE158_ACTIVATION_SHA256, "e792b19ebe128469db689b68059ddb4de5180dbc1c0765df1b4e1fb9a967084e")
        self.assertEqual(mod.STAGE158_ROLLBACK_SHA256, "7789949d0e99d1f530ea92d6f5d2f90c6c94b89049061319f1f8ce0703340c6b")

    def test_entry43_47_payload_contract_is_frozen(self):
        self.assertEqual(mod.SOURCE_WET_43_SHA, mod.SOURCE_WET_SIBLING_47_SHA)
        self.assertNotEqual(mod.TARGET_WET_43_SHA, mod.TARGET_WET_SIBLING_47_SHA)
        self.assertNotEqual(mod.SOURCE_DRY_43_SHA, mod.SOURCE_WET_43_SHA)
        self.assertNotEqual(mod.TARGET_DRY_43_SHA, mod.TARGET_WET_43_SHA)

    def test_decode_bc3_constant_opaque_alpha(self):
        alpha, luma = mod.decode_bc3_base_channels(bc3_block(alpha_index=0), 4, 4)
        self.assertEqual(alpha, bytes([255]) * 16)
        self.assertEqual(len(luma), 16)

    def test_decode_bc3_constant_zero_alpha(self):
        alpha, _ = mod.decode_bc3_base_channels(bc3_block(alpha_index=1), 4, 4)
        self.assertEqual(alpha, bytes([0]) * 16)

    def test_decode_bc3_rejects_short_payload(self):
        with self.assertRaises(mod.Stage159Error):
            mod.decode_bc3_base_channels(b"\x00" * 15, 4, 4)

    def test_transition_stats_detect_exact_equality(self):
        row = mod.transition_stats(bytes([1, 2, 3]), bytes([1, 2, 3]))
        self.assertTrue(row["exact_equal"])
        self.assertEqual(row["changed_pixels"], 0)
        self.assertEqual(row["mean_abs_delta"], 0.0)

    def test_transition_stats_detect_bounded_change(self):
        row = mod.transition_stats(bytes([0, 10, 255, 100]), bytes([0, 20, 255, 80]))
        self.assertFalse(row["exact_equal"])
        self.assertEqual(row["changed_pixels"], 2)
        self.assertEqual(row["changed_ratio"], 0.5)
        self.assertEqual(row["mean_abs_delta"], 7.5)
        self.assertEqual(row["mean_signed_delta"], -2.5)

    def test_channel_histogram_accounts_for_all_pixels(self):
        row = mod.channel_stats(bytes(range(256)))
        self.assertEqual(sum(row["histogram"]), 256)
        self.assertEqual(row["min"], 0)
        self.assertEqual(row["max"], 255)
        self.assertEqual(row["zero_ratio"], round(1 / 256, 8))

    def test_report_forbids_image_and_game_payloads(self):
        for ext in (".g1t", ".pak", ".dds", ".png", ".webp"):
            self.assertIn(ext, mod.FORBIDDEN_REPORT_EXTENSIONS)

    def test_stage158_profile_remains_nonproduction_candidate(self):
        self.assertEqual(mod.STAGE158_PROFILE_SHA256, "9b70d0cff0ef86666b223fdcfe105b54dff25d6db664a3c965d9e748d85fa9fc")
        self.assertEqual(mod.PACK10_02_BASELINE_SHA256, "e798f39c3bcdbb11381197bddf9bd3ad8de6ccf5d7c0c78b22613046d47f5302")


if __name__ == "__main__":
    unittest.main()
