from __future__ import annotations

import csv
import importlib.util
import tempfile
import unittest
from pathlib import Path

WORKSTREAM = Path(__file__).resolve().parents[1]
PROJECT = WORKSTREAM.parent.parent
TOOL_PATH = WORKSTREAM / "127_collect_character_state_g1m_delta_scope_triage_evidence.py"
SPEC = importlib.util.spec_from_file_location("stage127_tool", TOOL_PATH)
assert SPEC and SPEC.loader
TOOL = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(TOOL)


def read_tsv(path: Path):
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


class CharacterStateG1MDeltaScopeTriageEvidenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.tmp = tempfile.TemporaryDirectory(prefix="stage127-tests-")
        cls.root = Path(cls.tmp.name)
        cls.archive, cls.summary = TOOL.build_report(
            PROJECT,
            report_root=PROJECT / ".local/reports/quartet_restoration",
            output_report_root=cls.root,
            create_archive=True,
        )
        cls.report = cls.root / TOOL.REPORT_DIR

    @classmethod
    def tearDownClass(cls) -> None:
        cls.tmp.cleanup()

    def test_exact_stage126_prerequisite_is_preserved(self):
        self.assertEqual(self.summary["stage126_report_sha256"], TOOL.STAGE126_SHA256)
        self.assertEqual(self.summary["stage126_summary_sha256"], TOOL.STAGE126_SUMMARY_SHA256)

    def test_all_schema_and_value_groups_are_classified(self):
        self.assertEqual(self.summary["schema_delta_group_rows"], 108)
        self.assertEqual(self.summary["value_delta_group_rows"], 117)
        self.assertEqual(len(read_tsv(self.report / "SCHEMA_DELTA_SCOPE_CLASSIFICATION.tsv")), 108)
        self.assertEqual(len(read_tsv(self.report / "VALUE_DELTA_SCOPE_CLASSIFICATION.tsv")), 117)

    def test_recurrent_group_counts_are_preserved(self):
        self.assertEqual(self.summary["recurrent_schema_delta_group_rows"], 49)
        self.assertEqual(self.summary["recurrent_value_delta_group_rows"], 46)

    def test_ubiquitous_mesh_blend_pattern_is_deprioritized_not_semantically_named(self):
        self.assertEqual(self.summary["ubiquitous_mesh_blend_addition_rows"], 2047)
        rows = read_tsv(self.report / "KEYWORD_PARAMETER_SIGNATURE_GROUPS.tsv")
        blend = [row for row in rows if row["parameter_name"] == "parameterForMeshBlend"]
        self.assertEqual(len(blend), 1)
        self.assertEqual(blend[0]["structural_classification"], "ubiquitous_engine_or_format_candidate")
        self.assertEqual(blend[0]["visual_or_censorship_semantics_confirmed"], "False")

    def test_nonblend_keyword_queue_is_bounded_and_metadata_only(self):
        self.assertEqual(self.summary["nonblend_keyword_candidate_rows"], 36)
        self.assertEqual(self.summary["nonblend_keyword_candidate_family_rows"], 33)
        self.assertEqual(
            self.summary["nonblend_keyword_parameter_counts"],
            {"fRpAlphaThres": 34, "fTranslucency": 2},
        )
        rows = read_tsv(self.report / "NON_BLEND_KEYWORD_CANDIDATE_QUEUE.tsv")
        self.assertEqual(len(rows), 36)
        self.assertTrue(all(row["semantics_confirmed"] == "False" for row in rows))
        self.assertTrue(all(row["write_authorized"] == "False" for row in rows))

    def test_path_hygiene_is_clean_in_complete_workstream(self):
        self.assertGreater(self.summary["path_hygiene_scanned_versioned_text_files"], 0)
        self.assertEqual(self.summary["forbidden_local_path_hit_rows"], 0)
        rows = read_tsv(self.report / "LOCAL_PATH_HYGIENE_AUDIT.tsv")
        self.assertEqual(rows, [])

    def test_path_hygiene_detects_user_specific_and_sandbox_paths(self):
        with tempfile.TemporaryDirectory(prefix="stage127-paths-") as td:
            root = Path(td)
            bad_home = "/" + "home" + "/example/private/project"
            bad_sandbox = "/mnt" + "/data/private"
            (root / "bad.sh").write_text(f'X="{bad_home}"\nY="{bad_sandbox}"\n', encoding="utf-8")
            scanned, hits = TOOL.path_hygiene_hits(root)
            self.assertEqual(scanned, 1)
            self.assertEqual(len(hits), 2)

    def test_stage105_uses_canonical_local_path_configuration(self):
        wrapper = (WORKSTREAM / "105_collect_br1_source_archive_provenance_evidence.sh").read_text(encoding="utf-8")
        tool = (WORKSTREAM / "collect_br1_source_archive_provenance_evidence.py").read_text(encoding="utf-8")
        self.assertIn('.local/paths.sh', wrapper)
        self.assertIn('BR1_ORIGINAL_ROOT', wrapper)
        self.assertIn('os.environ.get("BR1_ORIGINAL_ROOT")', tool)
        forbidden = "/" + "home" + "/"
        self.assertNotIn(forbidden, wrapper)
        self.assertNotIn(forbidden, tool)

    def test_safety_contract_remains_closed(self):
        self.assertEqual(self.summary["runtime_confirmed_rows"], 0)
        self.assertEqual(self.summary["visual_or_censorship_semantics_confirmed_rows"], 0)
        self.assertEqual(self.summary["write_authorized_rows"], 0)
        policy = self.summary["policy"]
        self.assertTrue(policy["stage126_evidence_only"])
        self.assertFalse(policy["local_proprietary_payloads_read"])
        self.assertFalse(policy["installed_game_modified"])
        self.assertFalse(policy["git_modified"])

    def test_archive_is_metadata_only(self):
        self.assertIsNotNone(self.archive)
        self.assertTrue(self.archive.is_file())
        forbidden = (".pak", ".g1e", ".g1em", ".g1m", ".g1s", ".g1t", ".elixir", ".elixir.gz", ".ebd", ".ebm")
        import subprocess
        names = subprocess.run(["tar", "--zstd", "-tf", str(self.archive)], text=True, capture_output=True, check=True).stdout.splitlines()
        self.assertFalse(any(name.casefold().endswith(forbidden) for name in names))


if __name__ == "__main__":
    unittest.main()
