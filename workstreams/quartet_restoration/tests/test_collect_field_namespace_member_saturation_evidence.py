from __future__ import annotations

import csv
import importlib.util
import struct
import subprocess
import sys
import tempfile
import unittest
import zlib
from pathlib import Path

WORKSTREAM = Path(__file__).resolve().parents[1]
PROJECT = WORKSTREAM.parent.parent
TOOL_PATH = WORKSTREAM / "131_collect_field_namespace_member_saturation_evidence.py"
SPEC = importlib.util.spec_from_file_location("stage131_tool", TOOL_PATH)
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


class FieldNamespaceMemberSaturationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.tmp = tempfile.TemporaryDirectory(prefix="stage131-tests-")
        cls.root = Path(cls.tmp.name)
        cls.workspace = cls.root / "workspace"
        br = TOOL.load_br_tool(PROJECT)
        inventories = TOOL.load_asset_inventories(PROJECT)
        report_root = PROJECT / ".local/reports/quartet_restoration"
        with tempfile.TemporaryDirectory(prefix="stage131-stage130-") as td:
            stage130 = TOOL.extract_stage130(report_root / TOOL.STAGE130_ARCHIVE, Path(td))
            candidates = [row for row in read_tsv(stage130 / "NON_CHARACTER_TECHNICAL_CANDIDATES.tsv") if row["namespace"] == "field"]
        for index, row in enumerate(sorted(candidates, key=lambda item: item["normalized_path"])):
            normalized = row["normalized_path"]
            root = TOOL.field_root(normalized)
            pair_id, source_entry = inventories[("source", normalized.casefold())]
            source_local = br.inventory_workspace_file(cls.workspace, "source", pair_id, str(source_entry["archive"]), str(source_entry["path"]))
            is_earc = normalized.casefold().endswith(".elixir.gz")
            source_members = [("common.bin", b"same"), (f"{root}_terrain.g1m", b"source-terrain")]
            if row["classification"] == "removed_in_target":
                write_gust_chunked(source_local, make_earc(source_members))
                continue
            pair_id, target_entry = inventories[("target", normalized.casefold())]
            target_local = br.inventory_workspace_file(cls.workspace, "target", pair_id, str(target_entry["archive"]), str(target_entry["path"]))
            if not is_earc:
                source_local.parent.mkdir(parents=True, exist_ok=True)
                target_local.parent.mkdir(parents=True, exist_ok=True)
                source_local.write_bytes(b"synthetic-source-g1pf")
                target_local.write_bytes(b"synthetic-target-g1pf")
                continue
            target_members = [("common.bin", b"same"), (f"{root}_terrain.g1m", b"target-terrain")]
            if index % 10 == 0:
                target_members.append((f"{root}_extra.g1t", b"target-extra"))
            write_gust_chunked(source_local, make_earc(source_members))
            write_gust_chunked(target_local, make_earc(target_members))
        cls.archive, cls.summary = TOOL.build_report(
            PROJECT,
            report_root=report_root,
            output_report_root=cls.root / "reports",
            workspace_root=cls.workspace,
            create_archive=True,
            verify_payload_hashes=False,
        )
        cls.report = cls.root / "reports" / TOOL.REPORT_DIR
        cls.inputs = read_tsv(cls.report / "FIELD_ARCHIVE_INPUTS.tsv")
        cls.archives = read_tsv(cls.report / "FIELD_ARCHIVE_SUMMARY.tsv")
        cls.members = read_tsv(cls.report / "FIELD_ARCHIVE_MEMBER_DELTAS.tsv")
        cls.roots = read_tsv(cls.report / "FIELD_SCENE_ROOT_MEMBER_SUMMARY.tsv")
        cls.shapes = read_tsv(cls.report / "FIELD_ARCHIVE_DELTA_SHAPE_GROUPS.tsv")
        cls.roles = read_tsv(cls.report / "FIELD_MEMBER_ROLE_FAMILIES.tsv")

    @classmethod
    def tearDownClass(cls) -> None:
        cls.tmp.cleanup()

    def test_exact_stage130_prerequisite_is_preserved(self):
        self.assertEqual(self.summary["stage130_report_sha256"], TOOL.STAGE130_SHA256)
        self.assertEqual(self.summary["stage130_summary_sha256"], TOOL.STAGE130_SUMMARY_SHA256)

    def test_all_318_field_paths_are_covered(self):
        self.assertEqual(self.summary["field_candidate_path_rows"], 318)
        self.assertEqual(len(self.archives), 318)
        self.assertEqual(self.summary["paired_earc_path_rows"], 312)
        self.assertEqual(self.summary["source_only_earc_path_rows"], 3)
        self.assertEqual(self.summary["paired_g1pf_path_rows"], 3)

    def test_all_105_scene_roots_are_saturated(self):
        self.assertEqual(self.summary["field_scene_root_rows"], 105)
        self.assertEqual(len(self.roots), 105)
        self.assertTrue(self.summary["all_field_paths_saturated"])
        self.assertTrue(self.summary["all_field_earc_members_saturated"])
        self.assertTrue(all(row["field_path_saturation_complete"] == "True" for row in self.roots))
        self.assertTrue(all(row["earc_member_saturation_complete"] == "True" for row in self.roots))

    def test_input_side_count_is_exact(self):
        self.assertEqual(self.summary["archive_input_side_rows"], 633)
        self.assertEqual(len(self.inputs), 633)
        self.assertEqual(sum(row["side"] == "source" for row in self.inputs), 318)
        self.assertEqual(sum(row["side"] == "target" for row in self.inputs), 315)

    def test_member_ledger_includes_identical_changed_and_added_rows(self):
        classes = {row["classification"] for row in self.members}
        self.assertIn("identical", classes)
        self.assertIn("changed", classes)
        self.assertIn("added_in_target", classes)
        self.assertGreater(self.summary["exact_member_ledger_rows"], 630)
        self.assertGreater(self.summary["removed_member_rows"], 0)

    def test_source_only_earc_and_paired_g1pf_are_distinguished(self):
        removed = [row for row in self.archives if row["classification"] == "removed_in_target"]
        g1pf = [row for row in self.archives if row["archive_role"] == "removed_g1pf"]
        self.assertEqual(len(removed), 3)
        self.assertTrue(all(row["exact_member_audit_complete"] == "True" for row in removed))
        self.assertEqual(len(g1pf), 3)
        self.assertTrue(all(row["exact_member_audit_complete"] == "False" for row in g1pf))
        self.assertTrue(all(row["file_level_audit_complete"] == "True" for row in g1pf))

    def test_delta_shape_and_role_groups_are_emitted(self):
        self.assertGreater(len(self.shapes), 0)
        self.assertGreater(len(self.roles), 0)
        self.assertEqual(self.summary["archive_delta_shape_rows"], len(self.shapes))
        self.assertEqual(self.summary["member_role_family_rows"], len(self.roles))
        self.assertGreater(self.summary["recurrent_archive_delta_shape_rows"], 0)

    def test_field_names_remain_non_semantic(self):
        self.assertTrue(all(row["lexical_signal_only_not_semantics"] == "True" for row in self.roots))
        self.assertEqual(self.summary["visual_or_censorship_semantics_confirmed_rows"], 0)

    def test_no_runtime_or_write_is_authorized(self):
        self.assertEqual(self.summary["runtime_confirmed_rows"], 0)
        self.assertEqual(self.summary["write_authorized_rows"], 0)
        self.assertFalse(self.summary["policy"]["installed_game_modified"])
        self.assertFalse(self.summary["policy"]["pak_built_or_repacked"])
        self.assertFalse(self.summary["policy"]["runtime_or_save_required"])

    def test_report_is_metadata_only(self):
        self.assertIsNotNone(self.archive)
        names = subprocess.run(["tar", "--zstd", "-tf", str(self.archive)], text=True, capture_output=True, check=True).stdout.splitlines()
        self.assertFalse(any(name.casefold().endswith(TOOL.FORBIDDEN_EXTENSIONS) for name in names))
        self.assertTrue(all(row["payload_in_evidence"] == "False" for row in self.inputs))
        self.assertTrue(all(row["payload_in_evidence"] == "False" for row in self.members))

    def test_cache_is_reused_when_all_inputs_exist(self):
        extraction = read_tsv(self.report / "EXTRACTION_INPUTS.tsv")
        self.assertEqual(len(extraction), 2)
        self.assertTrue(all(row["cache_action"] == "reused_existing_workspace" for row in extraction))

    def test_unsafe_paths_are_rejected(self):
        for value in ("../escape", "/absolute", "a/../../b"):
            with self.assertRaises(TOOL.CollectorError):
                TOOL.safe_relative(value, "test")


if __name__ == "__main__":
    unittest.main()
