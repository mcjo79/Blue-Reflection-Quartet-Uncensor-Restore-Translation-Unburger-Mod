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

import br_dlc_bkn_ui_structure_tool as mod  # noqa: E402
import br_dlc_bkn_activation_ui_tool as stage31  # noqa: E402
import br_dlc_bkn_ui_index_tool as stage40  # noqa: E402
import test_br_dlc_bkn_activation_ui_tool as fixture31  # noqa: E402
import test_br_dlc_bkn_ui_index_tool as fixture40  # noqa: E402


def make_kslt(*, texture_name: str, raw_value: int | None, raw_fill: int = 0xA5) -> bytes:
    name = texture_name.encode("ascii") + b"\0"
    table_base = 0x40
    names_base = table_base + 0x14
    texture_header = 0x80
    raw_offset = texture_header + 0x48
    raw_size = 256
    out = bytearray(raw_offset + raw_size)
    struct.pack_into("<I", out, 0, mod.KSLT_MAGIC)
    struct.pack_into("<I", out, 8, 1)
    struct.pack_into("<I", out, 12, len(out) - 0x40)
    struct.pack_into("<I", out, 16, 0)
    struct.pack_into("<I", out, 20, len(name))
    struct.pack_into("<I", out, 24, 1)
    struct.pack_into("<I", out, table_base, texture_header)
    out[names_base:names_base + len(name)] = name
    struct.pack_into("<I", out, texture_header, 0)
    struct.pack_into("<H", out, texture_header + 4, 8)
    struct.pack_into("<H", out, texture_header + 6, 8)
    struct.pack_into("<I", out, texture_header + 0x1C, raw_size)
    out[raw_offset:raw_offset + raw_size] = bytes([raw_fill]) * raw_size
    if raw_value is not None:
        struct.pack_into("<I", out, raw_offset + 16, raw_value)
    return bytes(out)


def make_kscl(*, texture_name: str, control_value: int | None, raw_value: int | None, raw_fill: int = 0xA5) -> bytes:
    kslt = make_kslt(texture_name=texture_name, raw_value=raw_value, raw_fill=raw_fill)
    kscl_length = 0x200
    out = bytearray(kscl_length + len(kslt))
    struct.pack_into("<I", out, 0, mod.KSCL_MAGIC)
    struct.pack_into("<I", out, 8, kscl_length - mod.KSCL_HEADER_SIZE)
    if control_value is not None:
        struct.pack_into("<I", out, 0x100, control_value)
    out[kscl_length:] = kslt
    return bytes(out)


def prepare_valid_ui(project: Path, br1: Path, quartet: Path) -> None:
    source_files = []
    target_files = []
    source_entries = []
    target_entries = []
    for index, name in enumerate(stage31.UI_MEMBER_NAMES):
        normalized = f"data/x64/res_jp/layout/{name}"
        source_path = normalized
        target_path = f"data/b1/x64/res_jp/layout/{name}"
        if name.endswith(".kslt"):
            source_payload = make_kslt(texture_name="item_icon", raw_value=None, raw_fill=0x22)
            target_payload = make_kslt(texture_name="item_icon", raw_value=100, raw_fill=0x23)
        else:
            source_payload = make_kscl(texture_name=f"texture_{index}", control_value=None, raw_value=None, raw_fill=0x30 + index)
            target_payload = make_kscl(
                texture_name=f"texture_{index}",
                control_value=200 if index == 0 else None,
                raw_value=100 if index == 1 else None,
                raw_fill=0x40 + index,
            )
        source_entries.append(("\\" + source_path.replace("/", "\\"), source_payload))
        target_entries.append(("\\" + target_path.replace("/", "\\"), target_payload))
        source_files.append({
            "archive": "DATA/PACK00_04_3.PAK",
            "path": source_path,
            "normalized_path": normalized,
            "size": len(source_payload),
            "sha256": stage31.sha256_bytes(source_payload),
        })
        target_files.append({
            "archive": "Data/PACK10_04_03.PAK",
            "path": target_path,
            "normalized_path": normalized,
            "size": len(target_payload),
            "sha256": stage31.sha256_bytes(target_payload),
        })
    inventories = project / ".local/reports/quartet_restoration/inventories"
    inventories.mkdir(parents=True, exist_ok=True)
    (inventories / "br1_assets.source.json").write_text(json.dumps({"files": source_files}), encoding="utf-8")
    (inventories / "br1_assets.target.json").write_text(json.dumps({"files": target_files}), encoding="utf-8")
    fixture31.make_pak(br1 / "DATA/PACK00_04_3.PAK", source_entries)
    fixture31.make_pak(quartet / "Data/PACK10_04_03.PAK", target_entries)


def prepare_prerequisites(project: Path, br1: Path, quartet: Path) -> None:
    fixture40.prepare_prerequisites(project, br1, quartet, complete=False)
    prepare_valid_ui(project, br1, quartet)
    stage31_output = project / ".local/reports/quartet_legacy_dlc" / stage31.REPORT_DIR_NAME
    stage31.audit(project, br1, quartet, stage31_output)
    stage40_output = project / ".local/reports/quartet_legacy_dlc" / stage40.REPORT_DIR_NAME
    stage40.audit(project, br1, quartet, stage40_output, create_report_archive=False)


class BknUiStructureTest(unittest.TestCase):
    def test_parser_classifies_control_and_texture_payload(self) -> None:
        payload = make_kscl(texture_name="atlas", control_value=200, raw_value=100)
        parsed = mod.parse_ui_member(payload)
        self.assertEqual(parsed.file_kind, "kscl_with_embedded_kslt")
        role, _region = mod.region_for(parsed, 0x100, 4)
        self.assertEqual(role, "kscl_control_body")
        raw_offset = parsed.textures[0]["raw_offset"]
        role, _region = mod.region_for(parsed, raw_offset + 16, 4)
        self.assertEqual(role, "texture_payload")

    def test_standalone_kslt_parser(self) -> None:
        parsed = mod.parse_ui_member(make_kslt(texture_name="icons", raw_value=100))
        self.assertEqual(parsed.file_kind, "standalone_kslt")
        self.assertEqual(parsed.texture_count, 1)
        self.assertTrue(any(region.role == "kslt_texture_table" for region in parsed.regions))

    def test_full_audit_classifies_prior_hits_and_remains_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temp_name:
            base = Path(temp_name)
            project, br1, quartet = base / "project", base / "br1", base / "quartet"
            project.mkdir()
            prepare_prerequisites(project, br1, quartet)
            output = project / ".local/reports/quartet_legacy_dlc" / mod.REPORT_DIR_NAME
            archive, summary = mod.audit(project, br1, quartet, output, create_report_archive=False)
            self.assertIsNone(archive)
            self.assertEqual(summary["ui_members_scanned"], 10)
            self.assertEqual(summary["kscl_members"], 8)
            self.assertEqual(summary["standalone_kslt_members"], 2)
            self.assertGreater(summary["target_bkn_texture_payload_hits"], 0)
            self.assertGreater(summary["target_bkn_structural_candidate_hits"], 0)
            self.assertFalse(summary["policy"]["profile_build_allowed"])
            validated = mod.validate_report(output)
            self.assertEqual(validated["tool_version"], "0.0.18")
            with (output / "DLC_BKN_UI_INDEX_REGION_CLASSIFICATION.tsv").open(encoding="utf-8") as handle:
                rows = list(csv.DictReader(handle, delimiter="\t"))
            self.assertTrue(any(row["family"] == "bkn" and row["region_role"] == "texture_payload" for row in rows))
            self.assertTrue(any(row["family"] == "bkn" and row["region_role"] == "kscl_control_body" for row in rows))

    def test_unsupported_magic_is_rejected(self) -> None:
        with self.assertRaises(mod.BknUiStructureError):
            mod.parse_ui_member(b"NOT_A_UI_MEMBER")

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
            with self.assertRaises(mod.BknUiStructureError):
                mod.validate_report(output)


if __name__ == "__main__":
    unittest.main()
