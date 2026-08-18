#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import importlib.util
import sys
import unittest
from pathlib import Path


SCRIPT = Path(__file__).with_name("174_build_uncensor_followup.py")
SPEC = importlib.util.spec_from_file_location("stage174", SCRIPT)
assert SPEC and SPEC.loader
MOD = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MOD
SPEC.loader.exec_module(MOD)


class Stage174Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.project = SCRIPT.resolve().parents[2]
        cls.member = cls.project / "titles/blue_reflection/workspace/quartet/archives/PACK11" / MOD.TARGET_MEMBER
        cls.data = cls.member.read_bytes()

    def test_source_contract(self) -> None:
        self.assertEqual(len(self.data), MOD.BASELINE_MEMBER_SIZE)
        self.assertEqual(hashlib.sha256(self.data).hexdigest(), MOD.BASELINE_MEMBER_SHA256)

    def test_exact_patch(self) -> None:
        patched = MOD.patch_member(self.data)
        self.assertEqual(len(patched), len(self.data))
        changed = [i for i, (a, b) in enumerate(zip(self.data, patched)) if a != b]
        self.assertEqual(changed, [0xE32, 0xE33, 0xEA6, 0xEA7])
        self.assertEqual(patched[0xE32:0xE36], bytes.fromhex("0b020000"))
        self.assertEqual(patched[0xEA6:0xEAA], bytes.fromhex("0b020000"))

    def test_refuses_hash_drift(self) -> None:
        drifted = bytearray(self.data)
        drifted[100] ^= 1
        with self.assertRaises(MOD.BuildError):
            MOD.patch_member(bytes(drifted))

    def test_refuses_offset_drift(self) -> None:
        drifted = bytearray(self.data)
        drifted[0xE32:0xE36] = bytes.fromhex("0b020000")
        with self.assertRaises(MOD.BuildError):
            MOD.patch_member(bytes(drifted))

    def test_only_selected_candidate_is_ready(self) -> None:
        ready = [row["event_id"] for row in MOD.locker_candidates() if row["ready"]]
        self.assertEqual(ready, ["te01_290"])


if __name__ == "__main__":
    unittest.main()
