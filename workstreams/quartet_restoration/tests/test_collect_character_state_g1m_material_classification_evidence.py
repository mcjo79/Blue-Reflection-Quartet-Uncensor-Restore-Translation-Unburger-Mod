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
TOOL_PATH = WORKSTREAM / "126_collect_character_state_g1m_material_classification_evidence.py"
SPEC = importlib.util.spec_from_file_location("stage126_tool", TOOL_PATH)
assert SPEC and SPEC.loader
TOOL = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = TOOL
SPEC.loader.exec_module(TOOL)


def read_tsv(path: Path):
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def parameter_record(name: str, buffer_type: int, values: list[object], *, endian: str = "<") -> bytes:
    name_bytes = name.encode("utf-8") + b"\0"
    raw = bytearray()
    for value in values:
        if buffer_type == 1:
            raw.extend(struct.pack(endian + "f", float(value)))
        elif buffer_type == 4:
            raw.extend(struct.pack(endian + "4f", *value))
        elif buffer_type == 5:
            raw.extend(struct.pack(endian + "i", int(value)))
        else:
            raise ValueError(buffer_type)
    size = 16 + len(name_bytes) + len(raw)
    return struct.pack(endian + "3I2H", size, len(name_bytes), 0, buffer_type, len(values)) + name_bytes + raw


def g1m(parameters: list[tuple[str, int, list[object]]], *, endian: str = "<") -> bytes:
    file_magic = b"_M1G" if endian == "<" else b"G1M_"
    block_payload = bytearray(struct.pack(endian + "I", len(parameters)))
    for name, buffer_type, values in parameters:
        block_payload.extend(parameter_record(name, buffer_type, values, endian=endian))
    section = struct.pack(endian + "3I", 0x00010003, 12 + len(block_payload), 1) + block_payload
    g1mg_size = 0x30 + len(section)
    g1mg = (
        b"G1MG"
        + struct.pack(endian + "2I", 0x30303430, g1mg_size)
        + b"DX11"
        + struct.pack(endian + "I6f", 0, 0.0, 0.0, 0.0, 1.0, 1.0, 1.0)
        + struct.pack(endian + "I", 1)
        + section
    )
    total = 0x18 + len(g1mg)
    return file_magic + struct.pack(endian + "5I", 0x30303430, total, 0x18, 0, 1) + g1mg


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


class CharacterStateG1MMaterialClassificationEvidenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.tmp = tempfile.TemporaryDirectory(prefix="stage126-tests-")
        cls.root = Path(cls.tmp.name)
        cls.workspace = cls.root / "workspace"
        br = TOOL.load_module(PROJECT / "Blue_Reflection_Text_Tool/br_restoration_tool.py", "stage126_test_br")
        stage125 = TOOL.load_module(WORKSTREAM / "125_collect_character_state_exact_rehydration_evidence.py", "stage126_test_stage125")
        inventories = stage125.load_asset_inventories(PROJECT)

        with tempfile.TemporaryDirectory(prefix="stage126-ledger-") as td:
            report = TOOL.extract_report(
                PROJECT / ".local/reports/quartet_restoration" / TOOL.STAGE125_ARCHIVE,
                Path(td),
            )
            families = read_tsv(report / "COMPLETE_UNIVERSAL_FAMILY_COVERAGE.tsv")

        for index, family in enumerate(families):
            character_id = family["character_id"]
            state_token = family["state_token"]
            normalized = family["archive_path"]
            source_body = g1m([
                ("baseColor", 4, [(1.0, 1.0, 1.0, 1.0)]),
                ("fTranslucency", 1, [1.0]),
            ])
            target_body = g1m([
                ("baseColor", 4, [(1.0, 1.0, 1.0, 1.0)]),
                ("fTranslucency", 1, [0.5]),
            ])
            unchanged = g1m([("baseColor", 4, [(0.25, 0.25, 0.25, 1.0)])])
            source_members = [
                ("dummy.bin", b"same"),
                (f"{character_id}_{state_token}_body.g1m", source_body),
                (f"{character_id}_{state_token}_unchanged.g1m", unchanged),
            ]
            target_members = [
                ("dummy.bin", b"same"),
                (f"{character_id}_{state_token}_body.g1m", target_body),
                (f"{character_id}_{state_token}_unchanged.g1m", unchanged),
            ]
            if index == 0:
                target_members.append((f"{character_id}_{state_token}_extra.g1m", g1m([("fAlpha", 1, [0.75])])))
            if index == 1:
                source_members.append((f"{character_id}_{state_token}_removed.g1m", g1m([("fWet", 1, [1.0])])))
            for side, members in (("source", source_members), ("target", target_members)):
                pair_id, entry = inventories[(side, normalized.casefold())]
                local = br.inventory_workspace_file(
                    cls.workspace, side, pair_id, str(entry["archive"]), str(entry["path"])
                )
                write_gust_chunked(local, make_earc(members))

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

    def test_stage125_prerequisite_is_exact(self):
        self.assertEqual(self.summary["stage125_report_sha256"], TOOL.STAGE125_SHA256)
        self.assertEqual(self.summary["stage125_summary_sha256"], TOOL.STAGE125_SUMMARY_SHA256)

    def test_all_120_families_are_audited(self):
        self.assertEqual(self.summary["audited_universal_family_rows"], 120)
        self.assertEqual(self.summary["audited_character_rows"], 15)
        self.assertEqual(self.summary["audited_state_token_rows"], 8)
        self.assertEqual(self.summary["families_with_nonidentical_g1m_rows"], 120)
        rows = read_tsv(self.report / "UNIVERSAL_STATE_G1M_COVERAGE.tsv")
        self.assertEqual(len(rows), 120)

    def test_changed_added_and_removed_g1m_members_are_recorded(self):
        self.assertEqual(self.summary["nonidentical_g1m_member_rows"], 122)
        self.assertEqual(
            self.summary["g1m_member_classification_counts"],
            {"added_in_target": 1, "changed": 120, "removed_in_target": 1},
        )
        rows = read_tsv(self.report / "UNIVERSAL_G1M_MEMBER_AUDIT.tsv")
        self.assertEqual(len(rows), 122)
        self.assertTrue(all(row["runtime_confirmed"] == "False" for row in rows))
        self.assertTrue(all(row["write_authorized"] == "False" for row in rows))

    def test_identical_and_non_g1m_members_are_not_misclassified(self):
        rows = read_tsv(self.report / "UNIVERSAL_G1M_MEMBER_AUDIT.tsv")
        self.assertFalse(any("unchanged" in row["member_key"] for row in rows))
        self.assertFalse(any(row["member_key"].endswith("dummy.bin#0") for row in rows))

    def test_named_parameter_deltas_are_semantically_aligned_without_meaning_assignment(self):
        self.assertEqual(self.summary["semantic_parameter_diff_rows"], 122)
        counts = self.summary["semantic_parameter_classification_counts"]
        self.assertEqual(counts, {"added_in_target": 1, "changed": 120, "removed_in_target": 1})
        rows = read_tsv(self.report / "UNIVERSAL_G1M_PARAMETER_DIFF.tsv")
        changed = [row for row in rows if row["classification"] == "changed"]
        self.assertEqual(len(changed), 120)
        self.assertTrue(all(row["parameter_name"] == "fTranslucency" for row in changed))
        self.assertTrue(all(row["semantics_confirmed"] == "False" for row in rows))

    def test_keyword_bearing_rows_are_counted_but_not_interpreted(self):
        hits = self.summary["semantic_keyword_hit_counts"]
        self.assertGreaterEqual(hits.get("trans", 0), 120)
        self.assertGreaterEqual(hits.get("translucency", 0), 120)
        self.assertEqual(self.summary["visual_or_censorship_semantics_confirmed_rows"], 0)

    def test_recurrent_schema_and_value_groups_are_exposed(self):
        self.assertGreaterEqual(self.summary["recurrent_schema_delta_group_rows"], 1)
        self.assertGreaterEqual(self.summary["g1m_members_in_recurrent_schema_groups"], 120)
        self.assertGreaterEqual(self.summary["recurrent_value_delta_group_rows"], 1)
        self.assertGreaterEqual(self.summary["g1m_members_in_recurrent_value_groups"], 120)
        groups = read_tsv(self.report / "UNIVERSAL_G1M_SCHEMA_DELTA_GROUPS.tsv")
        self.assertTrue(any(row["g1m_member_rows"] == "120" for row in groups))

    def test_all_synthetic_g1m_payloads_parse_without_skips(self):
        self.assertEqual(self.summary["parse_skipped_rows"], 0)
        self.assertEqual(self.summary["families_with_complete_g1m_classification"], 120)
        skipped = read_tsv(self.report / "G1M_PARSE_SKIPPED.tsv")
        self.assertEqual(skipped, [])

    def test_chunk_metadata_is_reported_without_payloads(self):
        self.assertEqual(self.summary["g1m_chunk_rows"], 242)
        rows = read_tsv(self.report / "UNIVERSAL_G1M_CHUNK_ROWS.tsv")
        self.assertEqual(len(rows), 242)
        self.assertEqual({row["chunk_magic"] for row in rows}, {"G1MG"})
        forbidden = (".pak", ".g1e", ".g1em", ".g1m", ".g1s", ".g1t", ".elixir", ".elixir.gz", ".ebd", ".ebm")
        self.assertFalse(any(path.name.casefold().endswith(forbidden) for path in self.report.rglob("*") if path.is_file()))

    def test_existing_workspace_is_reused(self):
        rows = read_tsv(self.report / "EXTRACTION_INPUTS.tsv")
        self.assertEqual({row["cache_action"] for row in rows}, {"reused_existing_workspace"})

    def test_report_is_fail_closed_and_metadata_only(self):
        self.assertTrue(self.archive and self.archive.is_file())
        policy = self.summary["policy"]
        self.assertTrue(policy["local_proprietary_payloads_read_for_analysis"])
        self.assertFalse(policy["proprietary_payloads_in_report"])
        self.assertTrue(policy["metadata_and_numeric_parameter_values_only"])
        self.assertFalse(policy["pak_built_or_repacked"])
        self.assertFalse(policy["g1m_or_earc_written"])
        self.assertFalse(policy["visual_or_censorship_semantics_assigned"])
        self.assertEqual(self.summary["runtime_confirmed_rows"], 0)
        self.assertEqual(self.summary["write_authorized_rows"], 0)
        self.assertFalse(self.summary["global_discovery_saturation_achieved"])

    def test_schema_signature_ignores_character_identity(self):
        semantic = [{
            "parameter_name": "fTranslucency", "buffer_type": 1, "buffer_count": 1,
            "classification": "changed", "keyword_hits": "trans,translucency",
        }]
        source = {"chunks": [{"chunk_magic": "G1MG", "chunk_version": "0x30303430"}]}
        target = {"chunks": [{"chunk_magic": "G1MG", "chunk_version": "0x30303430"}]}
        a = TOOL.schema_signature(normalized_role="pc_body", member_classification="changed", source=source, target=target, semantic_rows=semantic)
        b = TOOL.schema_signature(normalized_role="pc_body", member_classification="changed", source=source, target=target, semantic_rows=semantic)
        self.assertEqual(a, b)

    def test_invalid_g1m_is_reportable_not_silently_parsed(self):
        br = TOOL.load_module(PROJECT / "Blue_Reflection_Text_Tool/br_restoration_tool.py", "stage126_invalid_br")
        parsed, status = TOOL.parse_g1m(br, b"not-a-g1m", "invalid")
        self.assertIsNone(parsed)
        self.assertTrue(status.startswith("parse_error:"))

    def test_unsafe_archive_members_are_rejected(self):
        for value in ("../escape", "/absolute", "a/../../b"):
            with self.assertRaises(TOOL.CollectorError):
                TOOL.safe_relative(value, "test path")


if __name__ == "__main__":
    unittest.main()
