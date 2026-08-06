from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

MODULE_PATH = Path(__file__).resolve().parents[1] / "br_dlc_bkn_generation9_label_candidate_tool.py"
SPEC = importlib.util.spec_from_file_location("br_dlc_bkn_generation9_label_candidate_tool_test", MODULE_PATH)
assert SPEC and SPEC.loader
MOD = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MOD)


class Generation9LabelCandidateTests(unittest.TestCase):
    def sample_xml(self, bom: bool = True) -> bytes:
        rows = "".join(
            f'\t<str Text="{text}" String_No="{number}"/>\r\n'
            for number, text in [
                (393335, "-"),
                (393336, "-"),
                (393337, "Gym Uniform"),
                (393338, "Cami"),
            ]
        )
        raw = ('<?xml version="1.0" encoding="utf-8"?>\r\n<Root>\r\n' + rows + '</Root>\r\n').encode("utf-8")
        return (b"\xef\xbb\xbf" + raw) if bom else raw

    def test_append_is_collision_free_and_preserves_existing_rows(self) -> None:
        source = self.sample_xml()
        candidate, rows = MOD.patch_str_costume(source, label="Bikini", start=393339, end=393346)
        before = MOD.parse_string_rows(source)
        after = MOD.parse_string_rows(candidate)
        self.assertEqual(after[: len(before)], before)
        self.assertEqual(after[-8:], [(number, "Bikini") for number in range(393339, 393347)])
        self.assertEqual(len(rows), 8)
        self.assertTrue(candidate.startswith(b"\xef\xbb\xbf"))

    def test_collision_is_rejected(self) -> None:
        source = self.sample_xml()
        with self.assertRaises(MOD.Generation9CandidateError):
            MOD.patch_str_costume(source, label="Bikini", start=393338, end=393345)

    def test_protected_rows_are_required(self) -> None:
        source = self.sample_xml().replace(b' String_No="393335"', b' String_No="393334"')
        with self.assertRaises(MOD.Generation9CandidateError):
            MOD.patch_str_costume(source, label="Bikini", start=393339, end=393346)


if __name__ == "__main__":
    unittest.main()
