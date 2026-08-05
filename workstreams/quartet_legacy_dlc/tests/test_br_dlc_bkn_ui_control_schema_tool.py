#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parents[1]
TEST_DIR = Path(__file__).resolve().parent
for item in (SCRIPT_DIR, TEST_DIR):
    if str(item) not in sys.path:
        sys.path.insert(0, str(item))

import br_dlc_bkn_ui_control_schema_tool as mod  # noqa: E402
import br_dlc_bkn_ui_structure_tool as stage43  # noqa: E402
import test_br_dlc_bkn_ui_structure_tool as fixture43  # noqa: E402


def prepare_prerequisites(project: Path, br1: Path, quartet: Path) -> None:
    fixture43.prepare_prerequisites(project, br1, quartet)
    output = project / ".local/reports/quartet_legacy_dlc" / stage43.REPORT_DIR_NAME
    stage43.audit(project, br1, quartet, output, create_report_archive=False)


class BknUiControlSchemaTest(unittest.TestCase):
    def test_header_field_crossing_is_detected(self) -> None:
        self.assertEqual(
            mod.intersecting_header_fields(7, 2),
            ["unknown_04", "texture_count"],
        )
        self.assertEqual(mod.intersecting_header_fields(8, 4), ["texture_count"])

    def test_candidate_classification_is_conservative(self) -> None:
        classification, supported = mod.candidate_classification(
            "replace",
            {"bkn": [100], "twl": [], "scl": []},
            1,
            0,
            0,
        )
        self.assertEqual(classification, "isolated_changed_control_numeric_candidate")
        self.assertFalse(supported)
        classification, supported = mod.candidate_classification(
            "replace",
            {"bkn": [100, 102], "twl": [], "scl": []},
            1,
            0,
            0,
        )
        self.assertEqual(classification, "local_multi_bkn_control_pattern_candidate")
        self.assertTrue(supported)

    def test_full_audit_remains_metadata_only_and_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temp_name:
            base = Path(temp_name)
            project, br1, quartet = base / "project", base / "br1", base / "quartet"
            project.mkdir()
            prepare_prerequisites(project, br1, quartet)
            output = project / ".local/reports/quartet_legacy_dlc" / mod.REPORT_DIR_NAME
            archive, summary = mod.audit(project, br1, quartet, output, create_report_archive=False)
            self.assertIsNone(archive)
            self.assertGreater(summary["stage43_structural_candidates"], 0)
            self.assertGreater(summary["selected_ui_member_pairs"], 0)
            self.assertFalse(summary["policy"]["profile_build_allowed"])
            self.assertFalse(summary["policy"]["raw_ui_payload_exported"])
            validated = mod.validate_report(output)
            self.assertEqual(validated["tool_version"], "0.0.19")

    def test_find_opcode_maps_equal_and_replace_ranges(self) -> None:
        opcodes = [("equal", 0, 4, 0, 4), ("replace", 4, 6, 4, 8)]
        self.assertEqual(mod.find_opcode(opcodes, 2)[0], "equal")
        self.assertEqual(mod.find_opcode(opcodes, 6)[0], "replace")
        with self.assertRaises(mod.BknUiControlSchemaError):
            mod.find_opcode(opcodes, 9)

    def test_validate_rejects_profile_authorization(self) -> None:
        with tempfile.TemporaryDirectory() as temp_name:
            base = Path(temp_name)
            project, br1, quartet = base / "project", base / "br1", base / "quartet"
            project.mkdir()
            prepare_prerequisites(project, br1, quartet)
            output = project / ".local/reports/quartet_legacy_dlc" / mod.REPORT_DIR_NAME
            mod.audit(project, br1, quartet, output, create_report_archive=False)
            summary_path = output / "SUMMARY.json"
            summary = json.loads(summary_path.read_text(encoding="utf-8"))
            summary["policy"]["profile_build_allowed"] = True
            summary_path.write_text(json.dumps(summary), encoding="utf-8")
            with self.assertRaises(mod.BknUiControlSchemaError):
                mod.validate_report(output)


if __name__ == "__main__":
    unittest.main()
