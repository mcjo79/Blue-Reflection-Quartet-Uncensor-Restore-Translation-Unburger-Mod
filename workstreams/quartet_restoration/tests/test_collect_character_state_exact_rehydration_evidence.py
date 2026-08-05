from __future__ import annotations

import csv
import importlib.util
import json
import struct
import sys
import tempfile
import unittest
import zlib
from pathlib import Path

WORKSTREAM = Path(__file__).resolve().parents[1]
PROJECT = WORKSTREAM.parent.parent
TOOL_PATH = WORKSTREAM / "125_collect_character_state_exact_rehydration_evidence.py"
SPEC = importlib.util.spec_from_file_location("stage125_tool", TOOL_PATH)
assert SPEC and SPEC.loader
TOOL = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = TOOL
SPEC.loader.exec_module(TOOL)


def read_tsv(path: Path):
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def make_earc(members: list[tuple[str, bytes]]) -> bytes:
    magic = 0x45415243
    header_size = 0x1C
    filename_size = 8
    name_bytes = 0x20 + filename_size * 0x10
    entry_size = 8 + name_bytes
    table_size = len(members) * entry_size
    payload_size = sum(len(payload) for _, payload in members)
    result = bytearray(header_size + table_size + payload_size)
    struct.pack_into("<7I", result, 0, magic, filename_size, payload_size, header_size, table_size, len(members), 0)
    offset = header_size + table_size
    for index, (name, payload) in enumerate(members):
        table = header_size + index * entry_size
        struct.pack_into("<2I", result, table, offset, len(payload))
        encoded = name.encode("utf-8") + b"\x00"
        if len(encoded) > name_bytes:
            raise AssertionError(name)
        result[table + 8 : table + 8 + len(encoded)] = encoded
        result[offset : offset + len(payload)] = payload
        offset += len(payload)
    return bytes(result)


def write_gust_chunked(path: Path, payload: bytes) -> None:
    compressed = zlib.compress(payload, 9)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(len(compressed).to_bytes(4, "little") + compressed + (0).to_bytes(4, "little"))


class CharacterStateExactRehydrationEvidenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.tmp = tempfile.TemporaryDirectory(prefix="stage125-tests-")
        cls.root = Path(cls.tmp.name)
        cls.workspace = cls.root / "workspace"
        br = TOOL.load_br_tool(PROJECT)
        inventories = TOOL.load_asset_inventories(PROJECT)
        stage124 = PROJECT / ".local/reports/quartet_restoration/character_state_member_integration_audit"
        families = read_tsv(stage124 / "UNIVERSAL_CHARACTER_STATE_INTEGRATION.tsv")
        missing = [row for row in families if row["existing_member_integration_complete"] == "False"]
        faces = read_tsv(stage124 / "FACE_RIG_SUPPORT_INTEGRATION.tsv")
        for row in missing:
            character_id = row["character_id"]
            state_token = row["state_token"]
            normalized = row["archive_path"]
            source_members = [
                ("dummy", b"same"),
                (f"{character_id}_{state_token}.g1m", b"source-payload"),
            ]
            target_members = [
                ("dummy", b"same"),
                (f"{character_id}_{state_token}.g1m", b"target-payload"),
                (f"{character_id}_{state_token}_extra.g1m", b"target-extra"),
            ]
            for side, members in (("source", source_members), ("target", target_members)):
                pair_id, entry = inventories[(side, normalized.casefold())]
                local = br.inventory_workspace_file(cls.workspace, side, pair_id, str(entry["archive"]), str(entry["path"]))
                write_gust_chunked(local, make_earc(members))
        for row in faces:
            normalized = row["archive_path"]
            pair_id, entry = inventories[("target", normalized.casefold())]
            local = br.inventory_workspace_file(cls.workspace, "target", pair_id, str(entry["archive"]), str(entry["path"]))
            write_gust_chunked(local, make_earc([("dummy", b"same"), ("rig.g1m", b"rig")]))
        cls.archive, cls.summary = TOOL.build_report(
            PROJECT,
            report_root=PROJECT / ".local/reports/quartet_restoration",
            output_report_root=cls.root / "reports",
            workspace_root=cls.workspace,
            create_archive=True,
            verify_payload_hashes=False,
        )
        cls.report = cls.root / "reports" / TOOL.REPORT_DIR

    @classmethod
    def tearDownClass(cls) -> None:
        cls.tmp.cleanup()

    def test_stage124_prerequisite_is_exact(self):
        self.assertEqual(self.summary["stage124_report_sha256"], TOOL.STAGE124_SHA256)
        self.assertEqual(self.summary["stage124_summary_sha256"], TOOL.STAGE124_SUMMARY_SHA256)

    def test_all_81_missing_families_are_rehydrated(self):
        self.assertEqual(self.summary["new_exact_rehydrated_family_rows"], 81)
        rows = read_tsv(self.report / "REHYDRATED_UNIVERSAL_FAMILY_SUMMARY.tsv")
        self.assertEqual(len(rows), 81)
        self.assertTrue(all(row["exact_rehydration_complete"] == "True" for row in rows))

    def test_all_120_families_have_exact_coverage(self):
        self.assertEqual(self.summary["stage124_existing_family_rows_preserved"], 39)
        self.assertEqual(self.summary["complete_universal_family_rows"], 120)
        self.assertEqual(self.summary["complete_universal_state_token_rows"], 8)
        self.assertEqual(self.summary["complete_universal_character_rows"], 15)
        self.assertTrue(self.summary["exact_universal_member_coverage_complete"])
        rows = read_tsv(self.report / "COMPLETE_UNIVERSAL_FAMILY_COVERAGE.tsv")
        self.assertEqual(len(rows), 120)
        self.assertEqual(sum(row["coverage_source"] == "stage125_exact_local_rehydration" for row in rows), 81)

    def test_source_and_target_archive_tables_are_both_recorded(self):
        self.assertEqual(self.summary["rehydrated_archive_side_rows"], 162)
        rows = read_tsv(self.report / "REHYDRATED_UNIVERSAL_ARCHIVES.tsv")
        self.assertEqual(len(rows), 162)
        self.assertEqual({row["side"] for row in rows}, {"source", "target"})
        self.assertTrue(all(row["payload_in_evidence"] == "False" for row in rows))

    def test_member_ledger_is_complete_and_metadata_only(self):
        self.assertEqual(self.summary["rehydrated_member_ledger_rows"], 243)
        self.assertEqual(self.summary["rehydrated_member_classification_counts"], {"added_in_target": 81, "changed": 81, "identical": 81})
        rows = read_tsv(self.report / "REHYDRATED_UNIVERSAL_MEMBER_LEDGER.tsv")
        self.assertEqual(len(rows), 243)
        self.assertTrue(all(row["semantics_confirmed"] == "False" for row in rows))
        self.assertTrue(all(row["write_authorized"] == "False" for row in rows))

    def test_recurrent_delta_shapes_are_grouped_without_semantics(self):
        self.assertEqual(self.summary["delta_shape_group_rows"], 1)
        self.assertEqual(self.summary["repeated_delta_shape_group_rows"], 1)
        self.assertEqual(self.summary["families_in_repeated_delta_shapes"], 81)
        rows = read_tsv(self.report / "UNIVERSAL_DELTA_SHAPE_GROUPS.tsv")
        self.assertEqual(rows[0]["logical_family_rows"], "81")
        self.assertEqual(rows[0]["semantics_confirmed"], "False")

    def test_four_face_rig_member_tables_are_collected_separately(self):
        self.assertEqual(self.summary["target_only_face_rig_archive_rows"], 4)
        self.assertEqual(self.summary["target_only_face_rig_member_rows"], 8)
        self.assertEqual(self.summary["target_only_face_rig_shape_group_rows"], 1)
        rows = read_tsv(self.report / "FACE_RIG_ARCHIVES.tsv")
        self.assertEqual(len(rows), 4)
        self.assertTrue(all(row["expression_or_visual_semantics_confirmed"] == "False" for row in rows))

    def test_existing_workspace_is_reused_without_game_roots(self):
        rows = read_tsv(self.report / "EXTRACTION_INPUTS.tsv")
        self.assertEqual({row["cache_action"] for row in rows}, {"reused_existing_workspace"})

    def test_report_contains_no_proprietary_payload_extensions(self):
        self.assertTrue(self.archive and self.archive.is_file())
        forbidden = (".pak", ".g1e", ".g1em", ".g1m", ".g1s", ".g1t", ".elixir", ".elixir.gz", ".ebd", ".ebm")
        self.assertFalse(any(path.name.casefold().endswith(forbidden) for path in self.report.rglob("*") if path.is_file()))
        policy = self.summary["policy"]
        self.assertTrue(policy["local_proprietary_payloads_rehydrated_for_analysis"])
        self.assertFalse(policy["proprietary_payloads_in_report"])
        self.assertTrue(policy["installed_game_read_only"])
        for key in ("pak_built_or_repacked", "profile_or_registry_modified", "core_modified", "translation_modified", "legacy_dlc_modified", "git_modified", "visual_or_censorship_semantics_assigned"):
            self.assertFalse(policy[key])

    def test_no_runtime_or_write_is_inferred(self):
        self.assertEqual(self.summary["runtime_confirmed_rows"], 0)
        self.assertEqual(self.summary["visual_or_censorship_semantics_confirmed_rows"], 0)
        self.assertEqual(self.summary["write_authorized_rows"], 0)
        self.assertFalse(self.summary["global_discovery_saturation_achieved"])

    def test_delta_signature_ignores_character_and_state_names(self):
        a = [{"target_member_name": "PC00_nkd_body.g1m", "source_size": 10, "target_size": 12, "classification": "changed"}]
        b = [{"target_member_name": "PC14_swm_w_body.g1m", "source_size": 10, "target_size": 12, "classification": "changed"}]
        self.assertEqual(TOOL.delta_signature(a, "pc00", "nkd"), TOOL.delta_signature(b, "pc14", "swm_w"))

    def test_unsafe_paths_are_rejected(self):
        for value in ("../escape", "/absolute", "a/../../b"):
            with self.assertRaises(TOOL.CollectorError):
                TOOL.safe_relative(value, "test path")


if __name__ == "__main__":
    unittest.main()
