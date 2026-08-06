from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path

MODULE_PATH = Path(__file__).resolve().parents[1] / "br_dlc_bkn_generation9_publish_tool.py"
SPEC = importlib.util.spec_from_file_location("br_dlc_bkn_generation9_publish_tool_test", MODULE_PATH)
assert SPEC and SPEC.loader
MOD = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MOD)


class Generation9PublishTests(unittest.TestCase):
    def test_manifest_semantics_accept_append_only_generation9(self) -> None:
        composition = {
            "Data/PACK10_02.PAK": {
                "candidate_relative_path": ".local/build/a/PACK10_02.PAK",
                "candidate_size": "10",
                "candidate_sha256": "a" * 64,
            },
            "Data/PACK12.PAK": {
                "candidate_relative_path": ".local/build/b/PACK12.PAK",
                "candidate_size": "20",
                "candidate_sha256": "b" * 64,
            },
        }
        acceptance = {
            "installed_baselines": [
                {"target_path": "Data/PACK10_02.PAK", "size": 1, "sha256": "c" * 64},
                {"target_path": "Data/PACK12.PAK", "size": 2, "sha256": "d" * 64},
            ]
        }
        manifest = MOD.build_manifest(composition, acceptance, "e" * 64)
        MOD.validate_manifest_semantics(manifest)
        self.assertEqual(manifest["generation"], 9)
        self.assertEqual(manifest["artifacts"][1]["member_delta"]["changed"], MOD.PACK12_CHANGED_MEMBERS)
        self.assertFalse(manifest["transaction"]["commit_enabled"])

    def test_manifest_rejects_existing_costume_replacement_shape(self) -> None:
        manifest = {
            "type": "validated_quartet_legacy_dlc_payload",
            "format_version": 1,
            "family_id": "bkn_dry",
            "generation": 9,
            "members": MOD.MEMBERS,
            "artifacts": [
                {"target_path": "Data/PACK10_02.PAK", "member_delta": {"added": MOD.ADDED_MEMBERS, "changed": [], "removed": []}},
                {"target_path": "Data/PACK12.PAK", "member_delta": {"added": [], "changed": ["wrong"], "removed": []}},
            ],
            "transaction": {"group": "quartet_legacy_dlc_bkn_dry", "all_or_none": True, "commit_enabled": False},
        }
        with self.assertRaises(MOD.Generation9PublishError):
            MOD.validate_manifest_semantics(manifest)


if __name__ == "__main__":
    unittest.main()
