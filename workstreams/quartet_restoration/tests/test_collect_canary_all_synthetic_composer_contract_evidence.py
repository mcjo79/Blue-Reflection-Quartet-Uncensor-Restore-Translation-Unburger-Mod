from __future__ import annotations

import csv
import hashlib
import importlib.util
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

WORKSTREAM = Path(__file__).resolve().parents[1]
PROJECT = WORKSTREAM.parent.parent
TOOL_PATH = WORKSTREAM / "120_collect_canary_all_synthetic_composer_contract_evidence.py"
SPEC = importlib.util.spec_from_file_location("stage120_tool", TOOL_PATH)
assert SPEC and SPEC.loader
TOOL = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = TOOL
SPEC.loader.exec_module(TOOL)


def read_tsv(path: Path):
    with path.open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f, delimiter="\t"))


class CanaryAllSyntheticComposerContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.tmp = tempfile.TemporaryDirectory(prefix="stage120-tests-")
        cls.root = Path(cls.tmp.name)
        cls.fixture_report_root = Path(__file__).resolve().parent / "fixtures" / "stage119_historical_reports"
        cls.manifest_root = Path(__file__).resolve().parent / "fixtures" / "stage119_historical_core_profile_manifests"
        cls.before = TOOL.manifest_hashes(PROJECT, cls.manifest_root)
        cls.archive, cls.summary = TOOL.build_report(
            PROJECT,
            report_root=cls.fixture_report_root,
            output_report_root=cls.root / "reports",
            gust_pak=PROJECT / TOOL.GUST_PAK_REL,
            create_archive=True,
            manifest_root=cls.manifest_root,
        )
        cls.report = cls.root / "reports" / TOOL.REPORT_DIR

    @classmethod
    def tearDownClass(cls) -> None:
        cls.tmp.cleanup()

    def test_summary_matches_exact_stage119_contract(self):
        self.assertEqual(self.summary["tool_version"], "0.1.38")
        self.assertEqual(self.summary["stage119_report_sha256"], TOOL.STAGE119_SHA256)
        self.assertEqual(self.summary["explicit_selected_profile_rows"], 15)
        self.assertEqual((self.summary["pack11_profile_rows"], self.summary["pack10_01_profile_rows"], self.summary["pack10_03_profile_rows"]), (12, 2, 1))

    def test_all_three_real_gust_pak_fixture_composites_reextract(self):
        rows = read_tsv(self.report / "SYNTHETIC_COMPOSITE_TARGETS.tsv")
        self.assertEqual(len(rows), 3)
        self.assertTrue(all(r["full_reextraction_passed"] == "True" for r in rows))

    def test_each_synthetic_profile_differs_only_at_declared_members(self):
        rows = read_tsv(self.report / "SYNTHETIC_PROFILE_SOURCE_VALIDATIONS.tsv")
        self.assertEqual(len(rows), 15)
        self.assertTrue(all(r["declared_member_rows"] == r["observed_diff_rows"] for r in rows))

    def test_exact_30_overlay_members_are_verified(self):
        rows = read_tsv(self.report / "SYNTHETIC_COMPOSITE_OVERLAYS.tsv")
        self.assertEqual(len(rows), 30)
        self.assertTrue(all(r["validation_status"] == "passed" for r in rows))

    def test_unrelated_sentinel_is_preserved_for_each_target(self):
        rows = read_tsv(self.report / "SYNTHETIC_SENTINEL_VALIDATIONS.tsv")
        self.assertEqual(len(rows), 3)
        self.assertTrue(all(r["preserved"] == "True" for r in rows))

    def test_explicit_selection_is_exact_and_does_not_infer_runtime_validation(self):
        self.assertEqual(self.summary["runtime_unvalidated_selected_profile_rows"], 15)
        self.assertFalse(self.summary["policy"]["runtime_validation_inferred"])
        with self.assertRaises(TOOL.SyntheticComposerError):
            TOOL.validate_explicit_selection(["a"], ["a", "b"])

    def test_negative_gates_reject_missing_duplicate_overlap_baseline_and_runtime_drift(self):
        rows = read_tsv(self.report / "SYNTHETIC_NEGATIVE_GATES.tsv")
        self.assertEqual(len(rows), 5)
        self.assertTrue(all(r["passed"] == "True" for r in rows))

    def test_production_composition_root_and_transaction_are_not_used(self):
        self.assertFalse(self.summary["production_composition_root_touched"])
        self.assertEqual(self.summary["transaction_artifact_rows"], 0)
        self.assertFalse(self.summary["policy"]["production_composer_executed"])
        self.assertFalse(self.summary["policy"]["installation_transaction_created"])

    def test_real_and_fixture_manifests_remain_immutable(self):
        self.assertEqual(TOOL.manifest_hashes(PROJECT, self.manifest_root), self.before)
        self.assertEqual(self.summary["real_profile_manifest_unchanged_rows"], 15)
        self.assertFalse(self.summary["policy"]["real_profile_manifests_modified"])

    def test_stage119_report_hash_is_fail_closed(self):
        source = self.fixture_report_root / TOOL.STAGE119_ARCHIVE
        bad = self.root / "bad-stage119.tar.zst"
        shutil.copy2(source, bad)
        bad.write_bytes(bad.read_bytes() + b"drift")
        with self.assertRaisesRegex(TOOL.SyntheticComposerError, "SHA-256 drift"):
            TOOL.load_stage119(bad, self.root / "bad-extract")

    def test_evidence_archive_contains_metadata_only(self):
        self.assertTrue(self.archive.is_file())
        self.assertFalse(any(p.suffix.casefold() == ".pak" for p in self.report.rglob("*")))
        self.assertFalse(self.summary["policy"]["evidence_contains_pak_payloads"])

    def test_unsafe_member_paths_are_rejected(self):
        for value in ("../escape.bin", "/absolute.bin", "a/../../b"):
            with self.assertRaises(TOOL.SyntheticComposerError):
                TOOL.safe_member(value)

    def test_no_real_profile_or_baseline_payload_is_rehydrated(self):
        self.assertFalse(self.summary["real_profile_paks_extracted"])
        self.assertFalse(self.summary["real_baseline_paks_rehydrated"])
        self.assertFalse(self.summary["real_canary_all_build_authorized"])
        self.assertFalse(self.summary["activation_authorized"])


if __name__ == "__main__":
    unittest.main()
