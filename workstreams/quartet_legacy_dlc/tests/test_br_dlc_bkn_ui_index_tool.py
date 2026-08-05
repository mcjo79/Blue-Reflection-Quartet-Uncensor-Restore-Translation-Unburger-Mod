#!/usr/bin/env python3
from __future__ import annotations

import csv
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

import br_dlc_bkn_ui_index_tool as mod  # noqa: E402
import br_dlc_bkn_activation_ui_tool as stage31  # noqa: E402
import br_dlc_bkn_index_runtime_tool as stage34  # noqa: E402
import br_dlc_bkn_pe_reference_tool as stage37  # noqa: E402
import test_br_dlc_bkn_activation_ui_tool as fixture31  # noqa: E402
import test_br_dlc_bkn_index_runtime_tool as fixture34  # noqa: E402
import test_br_dlc_bkn_pe_reference_tool as fixture37  # noqa: E402


def xml_bytes(rows: list[tuple[str, dict[str, str]]]) -> bytes:
    body = ["<Root>"]
    for tag, attrs in rows:
        values = " ".join(f'{key}="{value}"' for key, value in attrs.items())
        body.append(f"  <{tag} {values}/>")
    body.append("</Root>")
    return "\n".join(body).encode("utf-8")


def full_rows(table: str, *, target: bool) -> list[tuple[str, dict[str, str]]]:
    element = "CharaBase" if table == "chara/charabase.xml" else "Chara"
    filler_count = 200 if element == "CharaBase" else 100
    rows: list[tuple[str, dict[str, str]]] = [(element, {"BaseTag": f"FILLER_{index:04d}"}) for index in range(filler_count)]
    for family in ("BKN", "TWL", "SCL"):
        for pc in range(15):
            for wet in (False, True):
                suffix = "_W" if wet else ""
                tag = f"PC{pc:02d}_{'DLC_' if family != 'SCL' else ''}{family}{suffix}"
                if element == "CharaBase":
                    model_family = "Scl" if target and family == "BKN" else ("DLC_Bkn" if family == "BKN" else ("DLC_Twl" if family == "TWL" else "Scl"))
                    attrs = {
                        "BaseTag": tag,
                        "Directory": "Character",
                        "Model": f"PC{pc:02d}/PC{pc:02d}_{model_family}{suffix}",
                        "defaultTexture": f"PC{pc:02d}/PC{pc:02d}_{model_family}{suffix}",
                    }
                else:
                    attrs = {"BaseTag": tag, "Height": str(150 + pc)}
                rows.append((element, attrs))
    return rows


def prepare_full_tables(project: Path) -> None:
    for relative, _element, _key in stage34.TABLE_SPECS:
        for root, target in ((stage34.SOURCE_TABLE_ROOT, False), (stage34.TARGET_TABLE_ROOT, True)):
            path = project / root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(xml_bytes(full_rows(relative, target=target)))
    for relative in stage34.NON_ENUMERATION_TABLES:
        for root in (stage34.SOURCE_TABLE_ROOT, stage34.TARGET_TABLE_ROOT):
            path = project / root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(xml_bytes([("row", {"tag": "neutral"})]))
    source_text = [("str", {"String_No": str(393217 + index), "Text": f"source-{index}"}) for index in range(120)]
    target_text = [("str", {"String_No": str(393217 + index), "Text": "-" if index < 90 else f"target-{index}"}) for index in range(122)]
    (project / stage34.SOURCE_TEXT).parent.mkdir(parents=True, exist_ok=True)
    (project / stage34.TARGET_TEXT).parent.mkdir(parents=True, exist_ok=True)
    (project / stage34.SOURCE_TEXT).write_bytes(xml_bytes(source_text))
    (project / stage34.TARGET_TEXT).write_bytes(xml_bytes(target_text))


def packed_sequences(*, complete: bool) -> bytes:
    values: list[int] = []
    if complete:
        # chara_shared: BKN 100-129, TWL 130-159, SCL 160-189
        # charabase:    BKN 200-229, TWL 230-259, SCL 260-289
        for start in (100, 130, 160, 200, 230, 260):
            values.extend(range(start, start + 30))
    else:
        values.extend((100, 105, 200, 207, 130, 230))
    return b"IDX0" + b"".join(struct.pack("<I", value) for value in values) + b"END0"


def prepare_ui(project: Path, br1: Path, quartet: Path, *, complete: bool) -> None:
    source_files = []
    target_files = []
    source_entries = []
    target_entries = []
    for index, name in enumerate(stage31.UI_MEMBER_NAMES):
        source_path = f"data/x64/res_jp/layout/{name}"
        target_path = f"data/b1/x64/res_jp/layout/{name}"
        base = packed_sequences(complete=complete) if index == 0 else b"NEUTRAL" + bytes([index])
        source_payload = base
        target_payload = base + (b"TARGET_DELTA" if index == 1 else b"")
        source_entries.append(("\\" + source_path.replace("/", "\\"), source_payload))
        target_entries.append(("\\" + target_path.replace("/", "\\"), target_payload))
        source_files.append({"archive": "DATA/PACK00_04_3.PAK", "path": source_path, "normalized_path": source_path, "size": len(source_payload), "sha256": stage31.sha256_bytes(source_payload)})
        target_files.append({"archive": "Data/PACK10_04_03.PAK", "path": target_path, "normalized_path": source_path, "size": len(target_payload), "sha256": stage31.sha256_bytes(target_payload)})
    inventories = project / ".local/reports/quartet_restoration/inventories"
    inventories.mkdir(parents=True, exist_ok=True)
    (inventories / "br1_assets.source.json").write_text(json.dumps({"files": source_files}), encoding="utf-8")
    (inventories / "br1_assets.target.json").write_text(json.dumps({"files": target_files}), encoding="utf-8")
    fixture31.make_pak(br1 / "DATA/PACK00_04_3.PAK", source_entries)
    fixture31.make_pak(quartet / "Data/PACK10_04_03.PAK", target_entries)


def prepare_prerequisites(project: Path, br1: Path, quartet: Path, *, complete: bool) -> None:
    fixture31.prepare_dry_report(project)
    fixture31.prepare_tables(project)
    prepare_ui(project, br1, quartet, complete=complete)
    stage31_output = project / ".local/reports/quartet_legacy_dlc" / stage31.REPORT_DIR_NAME
    stage31.audit(project, br1, quartet, stage31_output)
    prepare_full_tables(project)
    tokens = ["PC00_DLC_BKN", "PC00_DLC_BKN_W", "PC00_DLC_TWL", "PC00_DLC_TWL_W", "PC00_SCL", "PC00_SCL_W", "costume_change"]
    (br1 / "BLUE_REFLECTION.exe").write_bytes(fixture37.minimal_pe64(tokens, include_code_xrefs=False, include_data_pointer=False))
    (quartet / "B1.dll").write_bytes(fixture37.minimal_pe64(tokens, include_code_xrefs=False, include_data_pointer=False))
    stage34_output = project / ".local/reports/quartet_legacy_dlc" / stage34.REPORT_DIR_NAME
    stage34.audit(project, br1, quartet, stage34_output, create_report_archive=False)
    stage37_output = project / ".local/reports/quartet_legacy_dlc" / stage37.REPORT_DIR_NAME
    stage37.audit(project, br1, quartet, stage37_output, create_report_archive=False)


class BknUiIndexTest(unittest.TestCase):
    def test_audit_finds_bounded_bkn_sequences_and_remains_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temp_name:
            base = Path(temp_name)
            project, br1, quartet = base / "project", base / "br1", base / "quartet"
            project.mkdir()
            prepare_prerequisites(project, br1, quartet, complete=True)
            output = project / ".local/reports/quartet_legacy_dlc" / mod.REPORT_DIR_NAME
            archive, summary = mod.audit(project, br1, quartet, output, create_report_archive=False)
            self.assertIsNone(archive)
            self.assertGreater(summary["bkn_target_sequence_candidates"], 0)
            self.assertGreater(summary["complete_bkn_target_sequence_candidates"], 0)
            self.assertEqual(summary["status"], "bkn_ui_index_sequence_candidates_found_semantics_unproven")
            validated = mod.validate_report(output)
            self.assertFalse(validated["policy"]["profile_build_allowed"])
            with (output / "DLC_BKN_UI_INDEX_SEQUENCE_CANDIDATES.tsv").open(encoding="utf-8") as handle:
                rows = list(csv.DictReader(handle, delimiter="\t"))
            self.assertTrue(any(row["family"] == "bkn" and row["side"] == "target" for row in rows))

    def test_isolated_values_do_not_become_ui_binding(self) -> None:
        with tempfile.TemporaryDirectory() as temp_name:
            base = Path(temp_name)
            project, br1, quartet = base / "project", base / "br1", base / "quartet"
            project.mkdir()
            prepare_prerequisites(project, br1, quartet, complete=False)
            output = project / ".local/reports/quartet_legacy_dlc" / mod.REPORT_DIR_NAME
            _, summary = mod.audit(project, br1, quartet, output, create_report_archive=False)
            self.assertGreater(summary["bkn_target_value_hits"], 0)
            self.assertEqual(summary["bkn_target_sequence_candidates"], 0)
            self.assertEqual(summary["status"], "bkn_ui_index_value_hits_found_without_sequence")
            self.assertFalse(summary["policy"]["numeric_index_hit_is_ui_binding_proof"])

    def test_changed_ui_member_after_stage31_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp_name:
            base = Path(temp_name)
            project, br1, quartet = base / "project", base / "br1", base / "quartet"
            project.mkdir()
            prepare_prerequisites(project, br1, quartet, complete=True)
            pak_path = quartet / "Data/PACK10_04_03.PAK"
            index = stage31.NESTED.index_pak(pak_path)
            entry = index.entries[0]
            data = bytearray(pak_path.read_bytes())
            data[entry.absolute_offset] ^= 0x01
            pak_path.write_bytes(data)
            output = project / ".local/reports/quartet_legacy_dlc" / mod.REPORT_DIR_NAME
            with self.assertRaises((mod.BknUiIndexError, stage31.NESTED.NestedContainerError)):
                mod.audit(project, br1, quartet, output, create_report_archive=False)

    def test_validate_rejects_profile_authorization(self) -> None:
        with tempfile.TemporaryDirectory() as temp_name:
            base = Path(temp_name)
            project, br1, quartet = base / "project", base / "br1", base / "quartet"
            project.mkdir()
            prepare_prerequisites(project, br1, quartet, complete=True)
            output = project / ".local/reports/quartet_legacy_dlc" / mod.REPORT_DIR_NAME
            mod.audit(project, br1, quartet, output, create_report_archive=False)
            summary_path = output / "SUMMARY.json"
            summary = json.loads(summary_path.read_text(encoding="utf-8"))
            summary["policy"]["profile_build_allowed"] = True
            summary_path.write_text(json.dumps(summary), encoding="utf-8")
            with self.assertRaises(mod.BknUiIndexError):
                mod.validate_report(output)


if __name__ == "__main__":
    unittest.main()
