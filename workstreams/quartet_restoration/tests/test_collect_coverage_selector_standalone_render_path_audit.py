from __future__ import annotations

import csv
import importlib.util
import subprocess
import tempfile
import unittest
from pathlib import Path

WORKSTREAM = Path(__file__).resolve().parents[1]
PROJECT = WORKSTREAM.parent.parent
TOOL_PATH = WORKSTREAM / "128_collect_coverage_selector_standalone_render_path_audit.py"
SPEC = importlib.util.spec_from_file_location("stage128_tool", TOOL_PATH)
assert SPEC and SPEC.loader
TOOL = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(TOOL)


def read_tsv(path: Path):
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


class CoverageSelectorStandaloneRenderPathAuditTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.tmp = tempfile.TemporaryDirectory(prefix="stage128-tests-")
        cls.root = Path(cls.tmp.name)
        cls.archive, cls.summary = TOOL.build_report(
            PROJECT,
            report_root=PROJECT / ".local/reports/quartet_restoration",
            output_report_root=cls.root,
            create_archive=True,
        )
        cls.report = cls.root / TOOL.REPORT_DIR
        cls.coverage = read_tsv(cls.report / "COVERAGE_SELECTOR_CHANNEL_AUDIT.tsv")
        cls.render = read_tsv(cls.report / "STANDALONE_RENDER_PATH_AUDIT.tsv")

    @classmethod
    def tearDownClass(cls) -> None:
        cls.tmp.cleanup()

    def test_all_nineteen_unbound_coverage_families_are_preserved(self):
        self.assertEqual(self.summary["unbound_coverage_family_rows"], 19)
        self.assertEqual(len(self.coverage), 19)
        self.assertEqual(
            self.summary["unbound_coverage_family_counts"],
            {"bath_towel_addition": 3, "shower_swimsuit_addition": 1, "underwear_coverage_variant": 15},
        )

    def test_four_item_families_have_unique_oid_seeds_but_no_binding(self):
        seeded = [row for row in self.coverage if int(row["unique_oid_signature_rows"]) > 0]
        self.assertEqual(len(seeded), 4)
        self.assertEqual({row["token"] for row in seeded}, {
            "item_bathtowel_00", "item_bathtowel_01", "item_bathtowel_02", "item_swimsuit"
        })
        self.assertTrue(all(row["independent_selector_binding_confirmed"] == "False" for row in seeded))

    def test_fifteen_underwear_families_have_no_unique_oid_seed(self):
        unseeded = [row for row in self.coverage if int(row["unique_oid_signature_rows"]) == 0]
        self.assertEqual(len(unseeded), 15)
        self.assertTrue(all(row["family"] == "underwear_coverage_variant" for row in unseeded))
        self.assertTrue(all(row["selector_channel_classification"] == "self_structural_identifiers_only_no_unique_oid_or_external_binding" for row in unseeded))

    def test_no_existing_external_event_or_scene_binding_is_promoted(self):
        self.assertEqual(self.summary["coverage_external_direct_name_binding_rows"], 0)
        self.assertEqual(self.summary["coverage_event_direct_name_binding_rows"], 0)
        self.assertEqual(self.summary["coverage_exact_event_identifier_binding_rows"], 0)
        self.assertEqual(self.summary["coverage_exact_scene_costume_binding_rows"], 0)
        self.assertEqual(self.summary["independent_selector_binding_confirmed_rows"], 0)

    def test_five_standalone_render_paths_are_bounded(self):
        self.assertEqual(self.summary["standalone_render_path_rows"], 5)
        self.assertEqual(len(self.render), 5)
        self.assertEqual({row["focused_path"] for row in self.render}, TOOL.STANDALONE_PATHS)
        self.assertEqual(self.summary["standalone_changed_g1s_rows"], 4)
        self.assertEqual(self.summary["standalone_target_only_g1t_rows"], 1)

    def test_shader_program_and_token_counts_are_preserved(self):
        self.assertEqual(self.summary["standalone_dxbc_program_difference_rows"], 15)
        self.assertEqual(self.summary["standalone_technical_token_difference_rows"], 5)
        by_path = {row["focused_path"]: row for row in self.render}
        self.assertEqual(int(by_path["data/x64/shader/cwater.g1s"]["dxbc_program_difference_rows"]), 5)
        self.assertEqual(int(by_path["data/x64/shader/cwater2.g1s"]["dxbc_program_difference_rows"]), 5)
        self.assertEqual(int(by_path["data/x64/shader/heightfog.g1s"]["dxbc_program_difference_rows"]), 3)
        self.assertEqual(int(by_path["data/x64/shader/swater.g1s"]["dxbc_program_difference_rows"]), 2)

    def test_only_heightfog_and_swater_have_parked_profiles(self):
        profiled = [row for row in self.render if int(row["profile_manifest_rows"]) > 0]
        self.assertEqual({row["focused_path"] for row in profiled}, {
            "data/x64/shader/heightfog.g1s", "data/x64/shader/swater.g1s"
        })
        self.assertEqual(self.summary["standalone_profile_manifest_rows"], 2)
        self.assertEqual(self.summary["standalone_runtime_validated_profile_rows"], 0)
        self.assertEqual(self.summary["standalone_paths_with_local_reversible_profile_rows"], 2)

    def test_caustics_is_target_only_and_not_promoted(self):
        row = next(row for row in self.render if row["focused_path"].endswith("caustics.g1t"))
        self.assertEqual(row["classification"], "new_in_target")
        self.assertEqual(int(row["source_payload_size"]), 0)
        self.assertGreater(int(row["target_payload_size"]), 0)
        self.assertEqual(row["profile_manifest_rows"], "0")
        self.assertEqual(row["write_authorized"], "False")

    def test_safety_and_path_hygiene_contract_remains_closed(self):
        self.assertEqual(self.summary["forbidden_local_path_hit_rows"], 0)
        self.assertGreater(self.summary["path_hygiene_scanned_versioned_text_files"], 0)
        self.assertEqual(self.summary["runtime_confirmed_rows"], 0)
        self.assertEqual(self.summary["visual_or_censorship_semantics_confirmed_rows"], 0)
        self.assertEqual(self.summary["write_authorized_rows"], 0)
        self.assertTrue(self.summary["policy"]["existing_evidence_only"])
        self.assertFalse(self.summary["policy"]["local_proprietary_payloads_read"])
        self.assertFalse(self.summary["policy"]["installed_game_modified"])
        self.assertFalse(self.summary["policy"]["git_modified"])

    def test_archive_is_metadata_only(self):
        self.assertIsNotNone(self.archive)
        names = subprocess.run(
            ["tar", "--zstd", "-tf", str(self.archive)],
            text=True,
            capture_output=True,
            check=True,
        ).stdout.splitlines()
        self.assertFalse(any(name.casefold().endswith(TOOL.FORBIDDEN_EXTENSIONS) for name in names))


if __name__ == "__main__":
    unittest.main()
