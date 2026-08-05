#!/usr/bin/env python3
from __future__ import annotations

import argparse
import importlib.util
import json
import pathlib
import tempfile
import unittest
import sys
from unittest import mock


ROOT = pathlib.Path(__file__).resolve().parents[3]
TOOL_PATH = ROOT / "Blue_Reflection_Text_Tool" / "br_text_tool.py"
SPEC = importlib.util.spec_from_file_location("br_text_tool_partial_export_test", TOOL_PATH)
assert SPEC and SPEC.loader
TOOL = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = TOOL
SPEC.loader.exec_module(TOOL)


class PartialProjectExportReportTests(unittest.TestCase):
    def test_selected_project_subset_does_not_require_omitted_report_sections(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = pathlib.Path(td)
            (root / "config").mkdir(parents=True)
            (root / "config/project_version").write_text("test\n", encoding="utf-8")
            for project in ("blue_reflection", "second_light", "blue_reflection_sun", "blue_reflection_ray"):
                tr = root / "titles" / project / "translation"
                tr.mkdir(parents=True)
                (tr / "translation_manifest.json").write_text(
                    json.dumps({"summary": {"units": 0, "records": 0}}),
                    encoding="utf-8",
                )

            args = argparse.Namespace(
                project_root=str(root),
                project=["second_light", "blue_reflection_ray"],
                repair_layouts=False,
            )
            validation = {
                "failures": [],
                "files": 0,
                "byte_exact_roundtrip": True,
                "record_structures": {},
                "layout_disambiguations": {},
                "layout_disambiguation_files": [],
            }
            with mock.patch.object(TOOL, "validate_all_ebm", return_value=validation), mock.patch.object(
                TOOL, "project_specs", return_value=([], [])
            ):
                self.assertEqual(TOOL.cmd_export(args), 0)

            report = json.loads((root / ".local/reports/BR_TRANSLATION_EXPORT_REPORT.json").read_text())
            self.assertEqual(report["selected_projects"], ["blue_reflection_ray", "second_light"])
            exceptions = json.loads((root / ".local/reports/BR_ALIGNMENT_EXCEPTIONS.json").read_text())
            for project in ("blue_reflection", "second_light", "blue_reflection_sun", "blue_reflection_ray"):
                self.assertEqual(exceptions[project]["events"], [])
                self.assertEqual(exceptions[project]["system"], [])


if __name__ == "__main__":
    unittest.main()
