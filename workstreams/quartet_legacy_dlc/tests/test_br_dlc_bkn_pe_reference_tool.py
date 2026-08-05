#!/usr/bin/env python3
from __future__ import annotations

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

import br_dlc_bkn_pe_reference_tool as mod  # noqa: E402
import br_dlc_bkn_index_runtime_tool as stage34  # noqa: E402
import test_br_dlc_bkn_index_runtime_tool as fixture34  # noqa: E402


def align(value: int, amount: int) -> int:
    return (value + amount - 1) // amount * amount


def minimal_pe64(tokens: list[str], *, include_code_xrefs: bool = True, include_data_pointer: bool = True) -> bytes:
    image_base = 0x140000000
    file_alignment = 0x200
    section_alignment = 0x1000
    pe_offset = 0x80
    optional_size = 0xF0
    section_count = 2
    headers_size = 0x200
    text_raw = 0x200
    text_size = 0x200
    text_rva = 0x1000
    rdata_raw = 0x400
    rdata_size = 0x600
    rdata_rva = 0x2000
    total_size = rdata_raw + rdata_size
    data = bytearray(total_size)
    data[:2] = b"MZ"
    struct.pack_into("<I", data, 0x3C, pe_offset)
    data[pe_offset:pe_offset + 4] = b"PE\0\0"
    coff = pe_offset + 4
    struct.pack_into("<HHIIIHH", data, coff, 0x8664, section_count, 0, 0, 0, optional_size, 0x2022)
    optional = coff + 20
    struct.pack_into("<H", data, optional, 0x20B)
    struct.pack_into("<I", data, optional + 16, text_rva)
    struct.pack_into("<I", data, optional + 20, text_rva)
    struct.pack_into("<Q", data, optional + 24, image_base)
    struct.pack_into("<I", data, optional + 32, section_alignment)
    struct.pack_into("<I", data, optional + 36, file_alignment)
    struct.pack_into("<I", data, optional + 56, 0x3000)
    struct.pack_into("<I", data, optional + 60, headers_size)
    struct.pack_into("<H", data, optional + 68, 3)
    struct.pack_into("<I", data, optional + 108, 16)
    section_table = optional + optional_size
    # .text
    data[section_table:section_table + 8] = b".text\0\0\0"
    struct.pack_into("<IIIIIIHHI", data, section_table + 8, text_size, text_rva, text_size, text_raw, 0, 0, 0, 0, 0x60000020)
    # .rdata
    second = section_table + 40
    data[second:second + 8] = b".rdata\0\0"
    struct.pack_into("<IIIIIIHHI", data, second + 8, rdata_size, rdata_rva, rdata_size, rdata_raw, 0, 0, 0, 0, 0x40000040)

    token_offsets: dict[str, int] = {}
    cursor = rdata_raw + 0x20
    for token in tokens:
        token_offsets[token] = cursor
        encoded = token.encode("ascii") + b"\0"
        data[cursor:cursor + len(encoded)] = encoded
        cursor = align(cursor + len(encoded), 8)

    if include_code_xrefs:
        code_cursor = text_raw
        for token in tokens[:3]:
            token_rva = rdata_rva + (token_offsets[token] - rdata_raw)
            instruction_rva = text_rva + (code_cursor - text_raw)
            displacement = token_rva - (instruction_rva + 7)
            data[code_cursor:code_cursor + 3] = b"\x48\x8d\x0d"
            struct.pack_into("<i", data, code_cursor + 3, displacement)
            code_cursor += 8
    if include_data_pointer:
        pointer_offset = rdata_raw + 0x500
        token = tokens[0]
        token_rva = rdata_rva + (token_offsets[token] - rdata_raw)
        struct.pack_into("<Q", data, pointer_offset, image_base + token_rva)
        struct.pack_into("<I", data, pointer_offset + 16, token_rva)
    return bytes(data)


def prepare_stage34(project: Path, br1: Path, quartet: Path, *, pe: bool = True) -> None:
    fixture34.prepare_prerequisite(project, br1, quartet)
    source_tokens = ["PC00_DLC_BKN", "PC00_DLC_BKN_W", "PC00_DLC_TWL", "PC00_DLC_TWL_W", "PC00_SCL", "PC00_SCL_W", "costume_change"]
    target_tokens = ["PC00_DLC_BKN", "PC00_DLC_BKN_W", "PC00_DLC_TWL", "PC00_DLC_TWL_W", "PC00_SCL", "PC00_SCL_W", "costume_change"]
    br1.mkdir(parents=True, exist_ok=True)
    quartet.mkdir(parents=True, exist_ok=True)
    if pe:
        (br1 / "BLUE_REFLECTION.exe").write_bytes(minimal_pe64(source_tokens))
        (quartet / "B1.dll").write_bytes(minimal_pe64(target_tokens))
    else:
        (br1 / "BLUE_REFLECTION.exe").write_bytes(b"MZ" + b"PC00_DLC_BKN" + b"\0" * 100)
        (quartet / "B1.dll").write_bytes(minimal_pe64(target_tokens))
    output = project / ".local/reports/quartet_legacy_dlc" / stage34.REPORT_DIR_NAME
    stage34.audit(project, br1, quartet, output, create_report_archive=False)


class BknPeReferenceTest(unittest.TestCase):
    def test_pe_reference_audit_classifies_code_and_data_candidates(self) -> None:
        with tempfile.TemporaryDirectory() as temp_name:
            base = Path(temp_name)
            project = base / "project"
            br1 = base / "br1"
            quartet = base / "quartet"
            project.mkdir()
            prepare_stage34(project, br1, quartet)
            output = project / ".local/reports/quartet_legacy_dlc" / mod.REPORT_DIR_NAME
            archive, summary = mod.audit(project, br1, quartet, output, create_report_archive=False)
            self.assertIsNone(archive)
            self.assertEqual(summary["exact_token_modules"], 2)
            self.assertGreater(summary["deduplicated_exact_token_locations"], 0)
            self.assertGreater(summary["bkn_code_xref_candidates"], 0)
            self.assertGreater(summary["xref_candidates"], summary["bkn_code_xref_candidates"])
            self.assertEqual(summary["status"], "bkn_pe_code_reference_candidates_found_semantics_unproven")
            validated = mod.validate_report(output)
            self.assertFalse(validated["policy"]["profile_build_allowed"])

    def test_audit_rejects_changed_module_after_stage34(self) -> None:
        with tempfile.TemporaryDirectory() as temp_name:
            base = Path(temp_name)
            project = base / "project"
            br1 = base / "br1"
            quartet = base / "quartet"
            project.mkdir()
            prepare_stage34(project, br1, quartet)
            with (br1 / "BLUE_REFLECTION.exe").open("ab") as handle:
                handle.write(b"changed")
            output = project / ".local/reports/quartet_legacy_dlc" / mod.REPORT_DIR_NAME
            with self.assertRaises(mod.BknPeReferenceError):
                mod.audit(project, br1, quartet, output, create_report_archive=False)

    def test_exact_token_module_must_be_supported_pe(self) -> None:
        with tempfile.TemporaryDirectory() as temp_name:
            base = Path(temp_name)
            project = base / "project"
            br1 = base / "br1"
            quartet = base / "quartet"
            project.mkdir()
            prepare_stage34(project, br1, quartet, pe=False)
            output = project / ".local/reports/quartet_legacy_dlc" / mod.REPORT_DIR_NAME
            with self.assertRaises(mod.BknPeReferenceError):
                mod.audit(project, br1, quartet, output, create_report_archive=False)

    def test_validate_rejects_profile_authorization(self) -> None:
        with tempfile.TemporaryDirectory() as temp_name:
            base = Path(temp_name)
            project = base / "project"
            br1 = base / "br1"
            quartet = base / "quartet"
            project.mkdir()
            prepare_stage34(project, br1, quartet)
            output = project / ".local/reports/quartet_legacy_dlc" / mod.REPORT_DIR_NAME
            mod.audit(project, br1, quartet, output, create_report_archive=False)
            summary_path = output / "SUMMARY.json"
            summary = json.loads(summary_path.read_text(encoding="utf-8"))
            summary["policy"]["profile_build_allowed"] = True
            summary_path.write_text(json.dumps(summary), encoding="utf-8")
            with self.assertRaises(mod.BknPeReferenceError):
                mod.validate_report(output)


if __name__ == "__main__":
    unittest.main()
