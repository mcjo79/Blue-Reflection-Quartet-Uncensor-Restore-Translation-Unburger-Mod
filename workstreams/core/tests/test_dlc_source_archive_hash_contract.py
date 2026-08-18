from __future__ import annotations

import hashlib
import json
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[3]
CONTRACT = PROJECT_ROOT / "workstreams/core/contracts/release/DLC_SOURCE_ARCHIVE_HASHES_V1.json"
ANCHORS = PROJECT_ROOT / "workstreams/core/contracts/release/BR1_LEGACY_SOURCE_MEMBER_ANCHORS_V1.json"

EXPECTED_CONTRACT_SHA256 = "c9ad059961a0e14abe752540abef9d0bb53ee9ee3618a8e1b1a561da9936a6d6"
EXPECTED_BR1_FILES = [
    "BLUE_REFLECTION.exe",
    "DATA/PACK00_02.PAK",
    "DATA/PACK00_03.PAK",
    "DATA/PACK01.PAK",
    "DATA/PACK02_1.PAK",
    "DATA/PACK02_2.PAK",
    "DATA/PACK02_3.PAK",
]
EXPECTED_SL_FILES = [
    "Data/PACK00_02.PAK",
    "Data/PACK00_03.PAK",
    "Data/PACK01.PAK",
    "Data/PACK02.PAK",
    "Data/x64/Sound/Le0000_BGM.ktsl2asbin",
    "Data/x64/Sound/Le0000_BGM.ktsl2stbin",
]


class DLCSourceArchiveHashContractTests(unittest.TestCase):
    def load(self, path: Path) -> dict:
        return json.loads(path.read_text(encoding="utf-8"))

    def test_promoted_contract_is_exact_reviewed_capture(self) -> None:
        self.assertEqual(hashlib.sha256(CONTRACT.read_bytes()).hexdigest(), EXPECTED_CONTRACT_SHA256)

    def test_contract_shape_and_file_scope_are_frozen(self) -> None:
        data = self.load(CONTRACT)
        self.assertEqual(data["type"], "unburger_dlc_source_archive_hashes")
        self.assertEqual(data["format_version"], 1)
        by_id = {game["id"]: game for game in data["games"]}
        self.assertEqual(set(by_id), {"blue_reflection_2017", "blue_reflection_second_light"})
        self.assertEqual([f["path"] for f in by_id["blue_reflection_2017"]["files"]], EXPECTED_BR1_FILES)
        self.assertEqual([f["path"] for f in by_id["blue_reflection_second_light"]["files"]], EXPECTED_SL_FILES)
        for game in by_id.values():
            for item in game["files"]:
                self.assertGreater(item["size"], 0)
                self.assertRegex(item["sha256"], r"^[0-9a-f]{64}$")

    def test_provenance_is_bound_to_current_member_contracts(self) -> None:
        data = self.load(CONTRACT)
        anchors = self.load(ANCHORS)
        provenance = data["provenance"]
        self.assertEqual(
            provenance["blue_reflection_2017_member_anchor_fingerprint"],
            anchors["source_fingerprint"],
        )
        self.assertEqual(
            provenance["blue_reflection_2017_pack00_02_official_sha1"],
            "f4f10dd846bbb056b81e18050ad3edc680d0bc8b",
        )
        self.assertEqual(provenance["second_light_verified_logical_members"], 2942)
        self.assertEqual(
            provenance["second_light_member_fingerprint"],
            "90731009bb5291014e3b81ddc35237fead3c8aca8c866d0aee8f1aa80f3d61df",
        )


if __name__ == "__main__":
    unittest.main()
