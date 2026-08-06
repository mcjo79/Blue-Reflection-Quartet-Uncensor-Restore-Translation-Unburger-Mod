import importlib.util
import tempfile
import unittest
from pathlib import Path

MODULE_PATH = Path(__file__).resolve().parents[1] / "br_dlc_bkn_dry_save_entitlement_surface_tool.py"
spec = importlib.util.spec_from_file_location("surface", MODULE_PATH)
module = importlib.util.module_from_spec(spec)
import sys
sys.modules[spec.name] = module
spec.loader.exec_module(module)


class SurfaceTests(unittest.TestCase):
    def test_classifies_save_and_configs(self):
        self.assertEqual(module.classify(Path("slot01.sav")), "save_or_state")
        self.assertEqual(module.classify(Path("steam_settings/DLC.txt")), "text_config")
        self.assertEqual(module.classify(Path("game.exe")), "binary")

    def test_text_hit_extracts_api_and_ids(self):
        enc, hits = module.bounded_text_hits(b"BIsDlcInstalled appid=123456 unlock costume BKN\n")
        self.assertTrue(hits)
        self.assertIn("123456", hits[0]["numeric_ids"])
        self.assertIn("bkn", hits[0]["keywords"])

    def test_binary_hit_finds_ascii_and_utf16(self):
        raw = b"xxBIsDlcInstalledyy" + "SteamApps".encode("utf-16-le")
        hits = module.binary_hits(raw)
        needles = {x["needle"] for x in hits}
        self.assertIn("BIsDlcInstalled", needles)
        self.assertIn("SteamApps", needles)

    def test_state_root_prefers_user_surface(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "drive_c/users/test/AppData/Roaming").mkdir(parents=True)
            scan = module.ScanRoot("state", root, "state")
            subroots = module.candidate_subroots(scan)
            self.assertIn(root / "drive_c/users", subroots)


if __name__ == "__main__":
    unittest.main()
