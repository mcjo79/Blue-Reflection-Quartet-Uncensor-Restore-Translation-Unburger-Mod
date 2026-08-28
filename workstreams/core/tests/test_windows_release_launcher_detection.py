#!/usr/bin/env python3
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[3]
BUILD_RELEASE = ROOT / "BUILD_RELEASE.sh"

class WindowsReleaseLauncherDetectionTests(unittest.TestCase):
    def test_run_cmd_switches_to_release_root_before_patcher(self):
        text = BUILD_RELEASE.read_text(encoding="utf-8")
        start = text.index("cat > \"$RELEASE_STAGE/RUN.cmd\"")
        end = text.index("cat > \"$RELEASE_STAGE/SAVE_ACCESS.sh\"", start)
        block = text[start:end]
        self.assertIn('pushd "%ROOT%"', block)
        self.assertIn('popd', block)
        self.assertLess(block.index('pushd "%ROOT%"'), block.index('brpatcher.exe" start'))

if __name__ == "__main__":
    unittest.main()
