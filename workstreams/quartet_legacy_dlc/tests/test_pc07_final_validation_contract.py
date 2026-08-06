from __future__ import annotations

import pathlib
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
RUNNER = ROOT / "93_run_bkn_dry_pc07_generation_preview_evidence.sh"
FINALIZER = ROOT / "94_finalize_bkn_dry_pc07_generation_preview_evidence.sh"
PUBLISHER = ROOT / "br_dlc_bkn_dry_generation_publish_tool.py"


class Pc07FinalValidationContractTests(unittest.TestCase):
    def test_stage93_validates_and_records_generation_8(self):
        text = RUNNER.read_text(encoding="utf-8")
        self.assertIn("manifest.get('generation') != 8", text)
        self.assertIn("'generation':8", text)
        self.assertIn("ACTIVE generation is not 8", text)
        self.assertNotIn("ACTIVE generation is not 7", text)

    def test_version_gates_are_synchronized(self):
        runner = RUNNER.read_text(encoding="utf-8")
        publisher = PUBLISHER.read_text(encoding="utf-8")
        finalizer = FINALIZER.read_text(encoding="utf-8")
        self.assertIn('== "0.0.53"', runner)
        self.assertIn('quartet_legacy_dlc 0.0.53 is required', runner)
        self.assertIn('TOOL_VERSION = "0.0.53"', publisher)
        self.assertIn('== "0.0.53"', finalizer)

    def test_finalizer_is_packaging_only_and_fail_closed(self):
        text = FINALIZER.read_text(encoding="utf-8")
        self.assertIn('old_validation.get("errors") != ["ACTIVE generation is not 7"]', text)
        self.assertIn('"candidate_rebuilt": False', text)
        self.assertIn('"active_manifest_republished": False', text)
        self.assertIn('"canonical_preview_rerun": False', text)
        self.assertNotIn("transaction-prepare", text)
        self.assertNotIn("transaction-commit", text)

    def test_no_machine_specific_paths(self):
        for path in (RUNNER, FINALIZER, PUBLISHER):
            text = path.read_text(encoding="utf-8")
            self.assertNotIn("/home/", text)
            self.assertNotIn("C:\\Users\\", text)


if __name__ == "__main__":
    unittest.main()
