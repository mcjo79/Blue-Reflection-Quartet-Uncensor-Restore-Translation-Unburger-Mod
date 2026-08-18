from __future__ import annotations

import importlib.util
from pathlib import Path
import tempfile
import unittest

MODULE_PATH = Path(__file__).resolve().parents[1] / "validate_release_hygiene.py"
spec = importlib.util.spec_from_file_location("validate_release_hygiene", MODULE_PATH)
assert spec and spec.loader
M = importlib.util.module_from_spec(spec)
spec.loader.exec_module(M)


class ReleaseHygieneTests(unittest.TestCase):
    def test_clean_relative_and_variable_paths_pass(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "sample.py").write_text('root = "$HOME/game"\nrel = "Data/PACK10_02.PAK"\n')
            self.assertEqual(M.scan(root), [])

    def test_concrete_posix_user_home_is_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            private = chr(47) + "home" + chr(47) + "private_user" + chr(47) + "game"
            (root / "sample.txt").write_text(private)
            findings = M.scan(root)
            self.assertTrue(any("POSIX user-home" in row[2] for row in findings))

    def test_split_python_literal_cannot_hide_private_path(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            slash = chr(47)
            source = repr(slash + "home" + slash) + " + " + repr("private_user" + slash)
            (root / "sample.py").write_text("value = " + source + "\n")
            findings = M.scan(root)
            self.assertTrue(any("statically reconstructed" in row[2] for row in findings))

    def test_concrete_windows_user_profile_is_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            sep = chr(92)
            private = "C:" + sep + "Users" + sep + "private_user" + sep + "Game"
            (root / "sample.txt").write_text(private)
            findings = M.scan(root)
            self.assertTrue(any("Windows user-profile" in row[2] for row in findings))


if __name__ == "__main__":
    unittest.main()
