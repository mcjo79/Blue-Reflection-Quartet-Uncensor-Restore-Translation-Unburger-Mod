from __future__ import annotations

import csv
import hashlib
import importlib.util
import struct
import subprocess
import tempfile
import unittest
from pathlib import Path

WORKSTREAM = Path(__file__).resolve().parents[1]
PROJECT = WORKSTREAM.parent.parent
TOOL_PATH = WORKSTREAM / "129_collect_structured_selector_water_dependency_evidence.py"
SPEC = importlib.util.spec_from_file_location("stage129_tool", TOOL_PATH)
assert SPEC and SPEC.loader
TOOL = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(TOOL)

BR_SPEC = importlib.util.spec_from_file_location("stage129_test_br", PROJECT / "Blue_Reflection_Text_Tool/br_restoration_tool.py")
assert BR_SPEC and BR_SPEC.loader
BR = importlib.util.module_from_spec(BR_SPEC)
BR_SPEC.loader.exec_module(BR)


def read_tsv(path: Path):
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def earc_archive(files: list[tuple[str, bytes]]) -> bytes:
    max_name = max([0x30, *(len(name.encode("utf-8")) + 1 for name, _ in files)])
    filename_size = (max_name - 0x20 + 0x0F) // 0x10
    entry_size = 8 + 0x20 + filename_size * 0x10
    table_size = len(files) * entry_size
    payload_offset = BR.EARC_HEADER_SIZE + table_size
    table = bytearray(table_size)
    payload = bytearray()
    current = payload_offset
    for index, (name, data) in enumerate(files):
        offset = index * entry_size
        struct.pack_into("<2I", table, offset, current, len(data))
        encoded = name.encode("utf-8")
        table[offset + 8 : offset + 8 + len(encoded)] = encoded
        payload.extend(data)
        current += len(data)
    return struct.pack("<7I", BR.EARC_MAGIC, filename_size, len(payload), BR.EARC_HEADER_SIZE, table_size, len(files), 0) + bytes(table) + bytes(payload)


class StructuredSelectorWaterDependencyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.tmp = tempfile.TemporaryDirectory(prefix="stage129-tests-")
        cls.root = Path(cls.tmp.name)
        cls.fixture = cls.root / "fixture"
        cls.output = cls.root / "reports"
        stage128 = read_tsv(PROJECT / ".local/reports/quartet_restoration/coverage_selector_standalone_render_path_audit/COVERAGE_SELECTOR_CHANNEL_AUDIT.tsv")

        xml = "<root><costume model='item_bathtowel_00'/><entry>pc00_udw2</entry></root>".encode()
        for path in TOOL.STRUCTURED_PATHS:
            for side in ("source", "target"):
                if side == "source" and path == "saves/fieldmap/caustics_param.xml":
                    continue
                payload = b"<caustics><entry texture='caustics.g1t' value='1'/></caustics>" if path.endswith("caustics_param.xml") else xml
                local = cls.fixture / "br1_language" / side / path
                local.parent.mkdir(parents=True, exist_ok=True)
                local.write_bytes(payload)

        cls.seed_rows = []
        item_index = 0
        for row in stage128:
            token = row["token"]
            payload = bytearray(b"OID0" + bytes(range(1, 65)))
            if row["family"] != "underwear_coverage_variant":
                marker = (f"SEED{item_index:08d}").encode()[:12].ljust(12, b"X")
                payload[8:20] = marker
                cls.seed_rows.append({
                    "seed_id": f"fixture_seed_{item_index}",
                    "candidate_id": row["candidate_id"],
                    "seed_offset": "8",
                    "seed_length": "12",
                    "seed_sha256": hashlib.sha256(marker).hexdigest(),
                })
                item_index += 1
            candidate = cls.fixture / "br1_assets" / "target" / TOOL.candidate_asset_path(row)
            candidate.parent.mkdir(parents=True, exist_ok=True)
            candidate.write_bytes(earc_archive([(token + "Oid.bin", bytes(payload)), (token + ".g1m", b"G1M")]))
            sibling = TOOL.sibling_asset_path(row)
            if sibling:
                sibling_file = cls.fixture / "br1_assets" / "target" / sibling
                sibling_file.parent.mkdir(parents=True, exist_ok=True)
                sibling_payload = b"OID0" + bytes(range(1, 65))
                sibling_file.write_bytes(earc_archive([(row["character_id"] + "_udwOid.bin", sibling_payload)]))

        cls.archive, cls.summary = TOOL.build_report(
            PROJECT,
            report_root=PROJECT / ".local/reports/quartet_restoration",
            output_report_root=cls.output,
            fixture_root=cls.fixture,
            verify_payload_hashes=False,
            create_archive=True,
            seed_rows_override=cls.seed_rows,
        )
        cls.report = cls.output / TOOL.REPORT_DIR
        cls.structured = read_tsv(cls.report / "STRUCTURED_SELECTOR_TABLES.tsv")
        cls.hits = read_tsv(cls.report / "STRUCTURED_SELECTOR_EXACT_HITS.tsv")
        cls.oid = read_tsv(cls.report / "OID_MEMBER_MATRIX.tsv")
        cls.matrix = read_tsv(cls.report / "UNDERWEAR_SIBLING_OID_MATRIX.tsv")
        cls.seeds = read_tsv(cls.report / "EXACT_OID_SEED_SCAN.tsv")
        cls.water = read_tsv(cls.report / "WATER_SHADER_PAIR_CLASSIFICATION.tsv")
        cls.caustics = read_tsv(cls.report / "CAUSTICS_TARGET_ONLY_SUBSYSTEM.tsv")

    @classmethod
    def tearDownClass(cls) -> None:
        cls.tmp.cleanup()

    def test_all_nineteen_coverage_families_are_preserved(self):
        self.assertEqual(self.summary["coverage_family_rows"], 19)
        self.assertEqual(self.summary["item_family_rows"], 4)
        self.assertEqual(self.summary["underwear_family_rows"], 15)

    def test_structured_tables_cover_bounded_source_and_target_paths(self):
        self.assertEqual(self.summary["structured_table_payload_rows"], 17)
        self.assertTrue(all(row["payload_in_evidence"] == "False" for row in self.structured))
        self.assertTrue(all(row["parse_status"] == "ok" for row in self.structured))

    def test_exact_xml_hits_are_recorded_but_not_promoted(self):
        self.assertGreater(self.summary["structured_exact_candidate_token_hit_rows"], 0)
        self.assertTrue(any(row["token"] == "item_bathtowel_00" for row in self.hits))
        self.assertTrue(all(row["binding_confirmed"] == "False" for row in self.hits))

    def test_oid_rows_include_all_candidates_and_underwear_siblings(self):
        self.assertEqual(self.summary["oid_member_rows"], 34)
        self.assertEqual(len(self.oid), 34)
        self.assertEqual(sum(row["role"] == "candidate" for row in self.oid), 19)
        self.assertEqual(sum(row["role"] == "sibling_udw" for row in self.oid), 15)

    def test_all_underwear_variants_have_sibling_matrices(self):
        self.assertEqual(self.summary["underwear_sibling_matrix_rows"], 15)
        self.assertEqual(len(self.matrix), 15)
        self.assertTrue(all(row["selector_binding_confirmed"] == "False" for row in self.matrix))

    def test_seed_reconstruction_and_bounded_scan_are_exact(self):
        self.assertEqual(len(self.seed_rows), 4)
        self.assertGreaterEqual(len(self.seeds), 4)
        self.assertTrue(all(int(row["exact_hit_rows"]) > 0 for row in self.seeds))
        self.assertEqual(self.summary["independent_selector_binding_confirmed_rows"], 0)

    def test_cwater_pair_has_no_executable_code_delta(self):
        self.assertEqual(len(self.water), 2)
        self.assertEqual(self.summary["water_shader_paired_program_rows"], 10)
        self.assertEqual(self.summary["water_shader_executable_code_delta_rows"], 0)
        self.assertEqual(self.summary["water_shader_compiler_or_reflection_metadata_only_rows"], 10)
        self.assertTrue(all(row["profile_candidate_authorized"] == "False" for row in self.water))

    def test_caustics_target_only_pair_is_bounded_without_semantics(self):
        self.assertEqual(len(self.caustics), 1)
        row = self.caustics[0]
        self.assertEqual(row["texture_target_only"], "True")
        self.assertEqual(row["parameter_target_only"], "True")
        self.assertEqual(row["target_only_subsystem_pair_confirmed"], "True")
        self.assertEqual(row["direct_selector_binding_confirmed"], "False")
        self.assertEqual(row["write_authorized"], "False")

    def test_no_runtime_or_write_is_authorized(self):
        self.assertEqual(self.summary["runtime_confirmed_rows"], 0)
        self.assertEqual(self.summary["visual_or_censorship_semantics_confirmed_rows"], 0)
        self.assertEqual(self.summary["write_authorized_rows"], 0)
        self.assertFalse(self.summary["policy"]["installed_game_modified"])
        self.assertFalse(self.summary["policy"]["pak_built_or_repacked"])
        self.assertFalse(self.summary["policy"]["git_modified"])

    def test_fixture_mode_does_not_claim_local_payload_read(self):
        self.assertFalse(self.summary["policy"]["local_proprietary_payloads_read"])

    def test_archive_is_metadata_only(self):
        self.assertIsNotNone(self.archive)
        names = subprocess.run(["tar", "--zstd", "-tf", str(self.archive)], text=True, capture_output=True, check=True).stdout.splitlines()
        self.assertFalse(any(name.casefold().endswith(TOOL.FORBIDDEN_EXTENSIONS) for name in names))

    def test_stage128_and_dxbc_prerequisites_are_immutable(self):
        self.assertEqual(TOOL.sha256_file(PROJECT / ".local/reports/quartet_restoration" / TOOL.STAGE128_NAME), TOOL.STAGE128_SHA256)
        self.assertEqual(TOOL.sha256_file(PROJECT / ".local/reports/quartet_restoration" / TOOL.DXBC_REPORT_NAME), TOOL.DXBC_REPORT_SHA256)


if __name__ == "__main__":
    unittest.main()
