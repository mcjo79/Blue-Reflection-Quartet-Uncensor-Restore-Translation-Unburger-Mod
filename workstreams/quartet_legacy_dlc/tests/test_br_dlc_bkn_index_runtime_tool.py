#!/usr/bin/env python3
from __future__ import annotations

import csv
import importlib
import json
import struct
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parents[1]
TEST_DIR = Path(__file__).resolve().parent
for item in (SCRIPT_DIR, TEST_DIR):
    if str(item) not in sys.path:
        sys.path.insert(0, str(item))

import br_dlc_bkn_index_runtime_tool as mod  # noqa: E402
import br_dlc_bkn_activation_ui_tool as stage31  # noqa: E402
import test_br_dlc_bkn_activation_ui_tool as fixture31  # noqa: E402


def xml_bytes(rows: list[tuple[str, dict[str, str]]], *, encoding: str = "utf-8") -> bytes:
    body = ["<Root>"]
    for tag, attrs in rows:
        values = " ".join(f'{key}="{value}"' for key, value in attrs.items())
        body.append(f"  <{tag} {values}/>")
    body.append("</Root>")
    return "\n".join(body).encode(encoding)


def full_bkn_rows(table: str, *, target: bool) -> list[tuple[str, dict[str, str]]]:
    element = "CharaBase" if table == "chara/charabase.xml" else "Chara"
    rows: list[tuple[str, dict[str, str]]] = []
    filler_count = 200 if element == "CharaBase" else 100
    for index in range(filler_count):
        rows.append((element, {"BaseTag": f"FILLER_{index:04d}"}))
    for pc in range(15):
        for wet in (False, True):
            suffix = "_W" if wet else ""
            tag = f"PC{pc:02d}_DLC_BKN{suffix}"
            if element == "CharaBase":
                family = "Scl" if target else "DLC_Bkn"
                attrs = {
                    "BaseTag": tag,
                    "Directory": "Character",
                    "Model": f"PC{pc:02d}/PC{pc:02d}_{family}{suffix}",
                    "defaultTexture": f"PC{pc:02d}/PC{pc:02d}_{family}{suffix}",
                    "motset0": f"MOTION_{pc:02d}",
                }
                if target and not wet:
                    attrs["Motion1"] = f"PC{pc:02d}_SCL_BASE_MOTION1"
                    attrs["Facial"] = f"PC{pc:02d}_FACIAL"
            else:
                attrs = {"BaseTag": tag, "Height": str(150 + pc)}
            rows.append((element, attrs))
    return rows


def prepare_full_tables(project: Path) -> None:
    for relative, _element, _key in mod.TABLE_SPECS:
        for root, target in ((mod.SOURCE_TABLE_ROOT, False), (mod.TARGET_TABLE_ROOT, True)):
            path = project / root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(xml_bytes(full_bkn_rows(relative, target=target)))
    for relative in mod.NON_ENUMERATION_TABLES:
        for root in (mod.SOURCE_TABLE_ROOT, mod.TARGET_TABLE_ROOT):
            path = project / root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(xml_bytes([("row", {"tag": "neutral"})]))
    source_text = []
    target_text = []
    for index in range(120):
        string_no = str(393217 + index)
        source_text.append(("str", {"String_No": string_no, "Text": f"source-{index}"}))
        target_text.append(("str", {"String_No": string_no, "Text": "-" if index < 90 else f"target-{index}"}))
    for index in range(120, 122):
        target_text.append(("str", {"String_No": str(393217 + index), "Text": f"target-{index}"}))
    (project / mod.SOURCE_TEXT).parent.mkdir(parents=True, exist_ok=True)
    (project / mod.TARGET_TEXT).parent.mkdir(parents=True, exist_ok=True)
    (project / mod.SOURCE_TEXT).write_bytes(xml_bytes(source_text))
    (project / mod.TARGET_TEXT).write_bytes(xml_bytes(target_text))


def prepare_prerequisite(project: Path, br1: Path, quartet: Path) -> None:
    fixture31.prepare_dry_report(project)
    fixture31.prepare_tables(project)
    fixture31.prepare_ui(project, br1, quartet)
    output = project / ".local/reports/quartet_legacy_dlc" / stage31.REPORT_DIR_NAME
    stage31.audit(project, br1, quartet, output)
    prepare_full_tables(project)


def write_runtime_module(root: Path, *, with_token: bool, with_sequence: bool) -> None:
    root.mkdir(parents=True, exist_ok=True)
    data = bytearray(b"MZ" + b"\0" * 126)
    if with_token:
        data.extend(b"PC00_DLC_BKN\0BIsDlcInstalled\0str_costume\0")
    if with_sequence:
        values = [200 + pc * 2 for pc in range(15)]
        data.extend(b"\0" * 17)
        data.extend(b"".join(struct.pack("<I", value) for value in values))
    (root / "B1.dll").write_bytes(bytes(data))


class BknIndexRuntimeTest(unittest.TestCase):
    def test_audit_preserves_full_family_and_finds_bounded_runtime_candidates(self) -> None:
        with tempfile.TemporaryDirectory() as temp_name:
            base = Path(temp_name)
            project = base / "project"
            br1 = base / "br1"
            quartet = base / "quartet"
            project.mkdir()
            prepare_prerequisite(project, br1, quartet)
            write_runtime_module(br1, with_token=True, with_sequence=True)
            write_runtime_module(quartet, with_token=False, with_sequence=True)
            output = project / ".local/reports/quartet_legacy_dlc" / mod.REPORT_DIR_NAME
            archive, summary = mod.audit(project, br1, quartet, output, create_report_archive=False)
            self.assertIsNone(archive)
            self.assertEqual(summary["bkn_index_rows"], 90)
            self.assertEqual(summary["bkn_indices_preserved"], 90)
            self.assertEqual(summary["expected_scl_fallback_rows"], 30)
            self.assertGreater(summary["runtime_binding_candidates"], 0)
            self.assertEqual(summary["status"], "bkn_static_runtime_binding_candidates_found_but_not_proven")
            validated = mod.validate_report(output)
            self.assertFalse(validated["policy"]["profile_build_allowed"])
            with (output / "DLC_BKN_FAMILY_FALLBACK_MAP.tsv").open(encoding="utf-8") as handle:
                rows = list(csv.DictReader(handle, delimiter="\t"))
            self.assertEqual(len(rows), 30)
            self.assertTrue(all(row["redirects_to_expected_scl_fallback"] == "true" for row in rows))

    def test_audit_without_modules_remains_complete_and_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temp_name:
            base = Path(temp_name)
            project = base / "project"
            br1 = base / "br1"
            quartet = base / "quartet"
            project.mkdir()
            prepare_prerequisite(project, br1, quartet)
            output = project / ".local/reports/quartet_legacy_dlc" / mod.REPORT_DIR_NAME
            _, summary = mod.audit(project, br1, quartet, output, create_report_archive=False)
            self.assertEqual(summary["runtime_modules_scanned"], 0)
            self.assertEqual(summary["status"], "bkn_index_blocks_preserved_runtime_modules_not_found")
            mod.validate_report(output)

    def test_validate_rejects_profile_authorization(self) -> None:
        with tempfile.TemporaryDirectory() as temp_name:
            base = Path(temp_name)
            project = base / "project"
            br1 = base / "br1"
            quartet = base / "quartet"
            project.mkdir()
            prepare_prerequisite(project, br1, quartet)
            output = project / ".local/reports/quartet_legacy_dlc" / mod.REPORT_DIR_NAME
            mod.audit(project, br1, quartet, output, create_report_archive=False)
            summary_path = output / "SUMMARY.json"
            summary = json.loads(summary_path.read_text(encoding="utf-8"))
            summary["policy"]["profile_build_allowed"] = True
            summary_path.write_text(json.dumps(summary), encoding="utf-8")
            with self.assertRaises(mod.BknIndexRuntimeError):
                mod.validate_report(output)


if __name__ == "__main__":
    unittest.main()
