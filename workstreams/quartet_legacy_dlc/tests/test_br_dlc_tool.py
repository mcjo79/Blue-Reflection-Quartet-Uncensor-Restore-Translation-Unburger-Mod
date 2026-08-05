from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
TOOL_PATH = PROJECT_ROOT / "Blue_Reflection_Text_Tool/br_dlc_tool.py"
SPEC = importlib.util.spec_from_file_location("br_dlc_tool", TOOL_PATH)
assert SPEC and SPEC.loader
TOOL = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(TOOL)


def member(path: str, size: int, digest: str, archive: str) -> dict[str, object]:
    return {
        "archive": archive,
        "path": path,
        "normalized_path": TOOL.canonical_member_path(path),
        "size": size,
        "sha256": digest,
    }


class DlcToolSyntheticTests(unittest.TestCase):
    def test_candidate_seed_totals_and_families(self) -> None:
        path = PROJECT_ROOT / "titles/blue_reflection/modules/quartet_legacy_dlc/mappings/text_candidate_units.tsv"
        rows = TOOL.read_tsv(path)
        self.assertEqual(len(rows), 135)
        self.assertEqual(sum(TOOL.parse_int(row["record_count"]) for row in rows), 1247)
        counts: dict[str, int] = {}
        for row in rows:
            family = TOOL.FAMILY_BY_SUBCATEGORY[row["subcategory"]]
            counts[family] = counts.get(family, 0) + 1
        self.assertEqual(counts, {"south_island": 94, "ffxv": 4, "yy": 35, "system_registry": 2})

    def test_binding_statuses_are_conservative(self) -> None:
        source = member("event/event_jp/fe01/event_fe01_200.ebd", 100, "a" * 64, "DATA/PACK01.PAK")
        target = member("event/b1/event_jp/fe01/event_fe01_200.ebd", 100, "b" * 64, "Data/PACK11.PAK")
        status, _ = TOOL.classify_binding(
            difference={"classification": "changed", "source": source, "target": target},
            role="event_control",
            event_id="fe01_200",
            placeholder_events=set(),
        )
        self.assertEqual(status, "present_modified")
        status, _ = TOOL.classify_binding(
            difference={"classification": "changed", "source": source, "target": target},
            role="event_message",
            event_id="fe01_200",
            placeholder_events={"fe01_200"},
        )
        self.assertEqual(status, "present_but_disabled")
        status, _ = TOOL.classify_binding(
            difference={"classification": "removed_in_target", "source": source, "target": None},
            role="event_control",
            event_id="fe01_200",
            placeholder_events=set(),
        )
        self.assertEqual(status, "missing_portable_from_br1")

    def test_member_mapping_keeps_translation_separate(self) -> None:
        unit = {
            "unit_path": "titles/blue_reflection/translation/events/fe01/event_message_fe01_200.ebm.json",
            "logical_path": "fe01/event_message_fe01_200.ebm",
            "internal_path": "event/b1/event_en/fe01/event_message_fe01_200.ebm",
            "record_count": "27",
            "category": "legacy_dlc_event",
            "subcategory": "south_island",
        }
        message_diff = {
            "difference_id": "diff_message",
            "classification": "changed",
            "normalized_path": "event/event_en/fe01/event_message_fe01_200.ebm",
            "mapping_basis": "normalized_path",
            "binary_similarity": 0.0,
            "source": member("event/event_en/fe01/event_message_fe01_200.ebm", 200, "1" * 64, "DATA/PACK01.PAK"),
            "target": member("event/b1/event_en/fe01/event_message_fe01_200.ebm", 40, "2" * 64, "Data/PACK11.PAK"),
        }
        control_diff = {
            "difference_id": "diff_control",
            "classification": "identical",
            "normalized_path": "event/event_jp/fe01/event_fe01_200.ebd",
            "mapping_basis": "normalized_path_and_sha256",
            "binary_similarity": 1.0,
            "source": member("event/event_jp/fe01/event_fe01_200.ebd", 100, "3" * 64, "DATA/PACK01.PAK"),
            "target": member("event/b1/event_jp/fe01/event_fe01_200.ebd", 100, "3" * 64, "Data/PACK11.PAK"),
        }
        rows = TOOL.build_member_bindings(
            units=[unit],
            event_differences=[message_diff, control_diff],
            language_differences=[],
            placeholder_events={"fe01_200"},
            restoration_changed=set(),
        )
        self.assertEqual(len(rows), 2)
        message = next(row for row in rows if row["member_role"] == "event_message")
        control = next(row for row in rows if row["member_role"] == "event_control")
        self.assertTrue(message["text_managed_by_translation"])
        self.assertEqual(message["binding_status"], "present_but_disabled")
        self.assertFalse(control["text_managed_by_translation"])
        self.assertEqual(control["binding_status"], "present_identical")

    def test_profile_candidates_never_embed_text_or_raw_assets(self) -> None:
        content = [{"content_id": "legacy_dlc_event_fe01_200", "family_id": "south_island"}]
        bindings = [
            {
                "content_id": "legacy_dlc_event_fe01_200",
                "family_id": "south_island",
                "normalized_path": "event/event_en/fe01/event_message_fe01_200.ebm",
                "binding_status": "present_but_disabled",
                "text_managed_by_translation": True,
            },
            {
                "content_id": "legacy_dlc_event_fe01_200",
                "family_id": "south_island",
                "normalized_path": "event/event_jp/fe01/event_fe01_200.ebd",
                "binding_status": "missing_portable_from_br1",
                "text_managed_by_translation": False,
            },
        ]
        unresolved = [
            {
                "family_id": "south_island",
                "dependency_kind": "routing",
            }
        ]
        result = TOOL.build_profile_candidates(content_rows=content, bindings=bindings, unresolved=unresolved)
        south = next(row for row in result["profiles"] if row["family_id"] == "south_island")
        self.assertFalse(south["raw_assets_included"])
        self.assertFalse(south["buildable"])
        self.assertEqual(len(south["transfer_member_candidates"]), 1)
        self.assertTrue(south["transfer_member_candidates"][0]["normalized_path"].endswith(".ebd"))

    def test_report_validation_rejects_raw_asset_suffix(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            required = {
                "DLC_CONTENT_INVENTORY.tsv": "x\n",
                "DLC_MEMBER_BINDINGS.tsv": "x\n",
                "DLC_DEPENDENCY_GRAPH.json": "{}\n",
                "DLC_TRIGGER_AND_FLAG_AUDIT.tsv": "x\n",
                "DLC_ASSET_COMPATIBILITY.tsv": "x\n",
                "DLC_UNRESOLVED_DEPENDENCIES.tsv": "x\n",
                "DLC_PROFILE_CANDIDATES.json": "{}\n",
                "DLC_SOURCE_INSTALLATION_AUDIT.tsv": "x\n",
                "SUMMARY.json": "{}\n",
            }
            for name, content in required.items():
                (root / name).write_text(content, encoding="utf-8")
            (root / "forbidden.ebd").write_bytes(b"asset")
            with self.assertRaises(TOOL.DlcAuditError):
                TOOL.validate_report_directory(root)

    def test_deterministic_metadata_bundle(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            parent = Path(temp)
            report = parent / "inventory_evidence"
            report.mkdir()
            required = {
                "DLC_CONTENT_INVENTORY.tsv": "x\n",
                "DLC_MEMBER_BINDINGS.tsv": "x\n",
                "DLC_DEPENDENCY_GRAPH.json": "{}\n",
                "DLC_TRIGGER_AND_FLAG_AUDIT.tsv": "x\n",
                "DLC_ASSET_COMPATIBILITY.tsv": "x\n",
                "DLC_UNRESOLVED_DEPENDENCIES.tsv": "x\n",
                "DLC_PROFILE_CANDIDATES.json": "{}\n",
                "DLC_SOURCE_INSTALLATION_AUDIT.tsv": "x\n",
                "SUMMARY.json": json.dumps({"policy": {"game_modified": False}}) + "\n",
            }
            for name, content in required.items():
                (report / name).write_text(content, encoding="utf-8")
            rows = TOOL.validate_report_directory(report)
            TOOL.write_json(report / "REPORT_MANIFEST.json", {
                "type": "test",
                "files": rows,
            })
            one = parent / "one.tar.zst"
            two = parent / "two.tar.zst"
            TOOL.make_report_archive(report, one)
            TOOL.make_report_archive(report, two)
            self.assertEqual(TOOL.sha256_file(one), TOOL.sha256_file(two))


if __name__ == "__main__":
    unittest.main()
