from __future__ import annotations

import csv
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
WORKSTREAM = ROOT / "workstreams/quartet_legacy_dlc"
sys.path.insert(0, str(WORKSTREAM))
TOOL_PATH = WORKSTREAM / "br_dlc_technical_registry_tool.py"
spec = importlib.util.spec_from_file_location("br_dlc_technical_registry_tool", TOOL_PATH)
assert spec and spec.loader
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


class TechnicalRegistryHelpersTest(unittest.TestCase):
    def test_required_technical_types_are_registered(self):
        expected = {
            "costume_or_outfit", "accessory", "item_or_reward", "recipe_or_system_bonus",
            "theme_or_ui_content", "unlock_or_entitlement", "shared_asset_dependency",
            "unknown_legacy_dlc_candidate",
        }
        self.assertEqual(mod.TECHNICAL_TYPES, expected)

    def test_activation_map_ignores_content_basetag(self):
        record = {"attrs": {"BaseTag": "PC00_DLC_BKN", "st_ev_tag": "DLC_COSTUME_BKN"}}
        fields = mod.record_activation_fields(record)
        self.assertEqual(fields, [("st_ev_tag", "DLC_COSTUME_BKN")])

    def test_member_accessory_type_is_not_collapsed_into_shared(self):
        value = mod.member_technical_type(
            "data/x64/character/item_accessory_01/item_accessory_01.g1t",
            "shared_asset_dependency", "shared_member_candidate", shared=True,
        )
        self.assertEqual(value, "accessory")

    def test_costume_and_recipe_classification(self):
        self.assertEqual(mod.technical_type_for_signal("PC00_DLC_TWL costume"), "costume_or_outfit")
        self.assertEqual(mod.technical_type_for_signal("make_item recipe bonus"), "recipe_or_system_bonus")

    def test_discovery_does_not_require_or_use_text_table_seed(self):
        records = [
            {
                "record_sha256": "a", "table_path": "saves/chara/chara.xml", "index": 1,
                "attrs": {"BaseTag": "PC00_DLC_BKN"}, "identifiers": ["PC00_DLC_BKN"],
                "dlc_identifiers": ["PC00_DLC_BKN"], "element": "Chara", "record_key": "x",
            },
            {
                "record_sha256": "b", "table_path": "saves/text_jp/str_costume.xml", "index": 2,
                "attrs": {"String_No": "PC00_DLC_BKN"}, "identifiers": ["PC00_DLC_BKN"],
                "dlc_identifiers": ["PC00_DLC_BKN"], "element": "String", "record_key": "y",
            },
        ]
        selected, known = mod.discover_records(records)
        self.assertEqual([row["record_sha256"] for row in selected], ["a"])
        self.assertIn("PC00_DLC_BKN", known)

    def test_optional_text_seed_can_be_absent(self):
        with tempfile.TemporaryDirectory() as tmp:
            values, mode = mod.load_optional_text_seed(Path(tmp))
        self.assertEqual(values, set())
        self.assertEqual(mode, "not_available_discovery_still_complete")

    def test_text_seed_overlap_is_annotation_only(self):
        seeds = {"event/b1/event_en/fe01/event_message_fe01_200.ebm"}
        self.assertEqual(mod.text_seed_overlap(["data/x64/character/pc00/pc00_dlc_bkn.g1t"], seeds), "no")
        self.assertEqual(mod.text_seed_overlap(["event/b1/event_en/fe01/event_message_fe01_200.ebm"], seeds), "yes")

    def test_report_validation_rejects_raw_asset(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            registry_fields = [
                "registry_id", "content_id", "technical_type", "compatibility_status",
            ]
            with (root / "DLC_TECHNICAL_REGISTRY.tsv").open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=registry_fields, delimiter="\t", lineterminator="\n")
                writer.writeheader()
                writer.writerow({
                    "registry_id": "r", "content_id": "c", "technical_type": "costume_or_outfit",
                    "compatibility_status": "present_identical",
                })
            for name in (
                "DLC_TEXT_INDEPENDENT_INVENTORY.tsv", "DLC_TECHNICAL_MEMBER_BINDINGS.tsv",
                "DLC_TECHNICAL_SYSTEM_RECORDS.tsv", "DLC_UNLOCK_FLAG_MAP.tsv",
                "DLC_UNRESOLVED_TECHNICAL_CANDIDATES.tsv", "DLC_TECHNICAL_TABLE_PARSE_AUDIT.tsv",
            ):
                (root / name).write_text("x\n", encoding="utf-8")
            (root / "DLC_ASSET_DEPENDENCY_GRAPH.json").write_text("{}\n", encoding="utf-8")
            (root / "SUMMARY.json").write_text(json.dumps({
                "text_candidate_units_required": False,
                "technical_type_counts": {"costume_or_outfit": 1},
            }) + "\n", encoding="utf-8")
            (root / "bad.g1t").write_bytes(b"asset")
            with self.assertRaises(mod.TechnicalRegistryError):
                mod.validate_report_directory(root)


if __name__ == "__main__":
    unittest.main()
