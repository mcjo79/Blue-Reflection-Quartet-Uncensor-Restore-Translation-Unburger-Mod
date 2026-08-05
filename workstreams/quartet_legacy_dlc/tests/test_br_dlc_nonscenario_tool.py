from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
TOOL_PATH = ROOT / "workstreams/quartet_legacy_dlc/br_dlc_nonscenario_tool.py"
spec = importlib.util.spec_from_file_location("br_dlc_nonscenario_tool", TOOL_PATH)
assert spec and spec.loader
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


class NonscenarioHelpersTest(unittest.TestCase):
    def test_costume_member_grouping(self):
        value = mod.content_from_member("data/x64/character/pc03/pc03_dlc_twl_w.g1t")
        self.assertEqual(value[0], "costume_pc03_twl")
        self.assertEqual(value[1], "costume_and_appearance")
        self.assertEqual(value[3], "wet")

    def test_item_identifier_grouping(self):
        value = mod.content_from_identifier("ITEM_DLC_ITEM_07")
        self.assertEqual(value[0], "dlc_item_07")
        self.assertEqual(value[1], "items_rewards_and_recipes")

    def test_removed_g1t_is_portable_fallback_candidate(self):
        status, _ = mod.member_status({
            "classification": "removed_in_target",
            "source": {"extension": ".g1t", "asset_type": "texture"},
        })
        self.assertEqual(status, "missing_portable_from_br1")

    def test_removed_xml_requires_reconstruction(self):
        status, _ = mod.member_status({
            "classification": "removed_in_target",
            "source": {"extension": ".xml", "asset_type": "event_or_script"},
        })
        self.assertEqual(status, "missing_requires_reconstruction")

    def test_translation_ownership(self):
        self.assertTrue(mod.translation_owned("saves_jp/text/str_costume.xml"))
        self.assertFalse(mod.translation_owned("data/x64/character/pc00/pc00_dlc_bkn.g1t"))

    def test_exact_dlc_record_is_not_claimed_runtime_active(self):
        source = {
            "record_key": "channel_skin:st_ev_tag=DLC_ADDSKIN000000000",
            "record_sha256": "abc",
            "attrs": {"st_ev_tag": "DLC_ADDSKIN000000000"},
        }
        target = [{"record_key": source["record_key"], "record_sha256": "abc"}]
        status, _ = mod.target_record_status(source, target)
        self.assertEqual(status, "present_but_disabled")

    def test_report_validation_rejects_raw_asset(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            required = {
                "DLC_FULL_CATALOG.tsv": "content_id\tfamily\tstatus\nitem\titems_rewards_and_recipes\tpresent_but_disabled\n",
                "DLC_NONSCRIPT_MEMBER_BINDINGS.tsv": "x\n",
                "DLC_SYSTEM_TABLE_RECORDS.tsv": "x\n",
                "DLC_IDENTIFIER_LINKS.tsv": "x\n",
                "DLC_ENTITLEMENT_AND_UNLOCK_AUDIT.tsv": "x\n",
                "DLC_NONSCRIPT_ASSET_COMPATIBILITY.tsv": "x\n",
                "DLC_NONSCRIPT_UNRESOLVED_DEPENDENCIES.tsv": "x\n",
                "DLC_TABLE_PARSE_AUDIT.tsv": "x\n",
                "DLC_SHARED_DEPENDENCY_CANDIDATES.tsv": "x\n",
                "DLC_NONSCRIPT_DEPENDENCY_GRAPH.json": "{}\n",
                "DLC_NONSCRIPT_PROFILE_CANDIDATES.json": "{}\n",
                "SUMMARY.json": "{}\n",
            }
            for name, data in required.items():
                (root / name).write_text(data, encoding="utf-8")
            (root / "bad.g1t").write_bytes(b"asset")
            with self.assertRaises(mod.NonscenarioAuditError):
                mod.validate_report_directory(root)


if __name__ == "__main__":
    unittest.main()
