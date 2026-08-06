import importlib.util
import struct
import tempfile
import unittest
from pathlib import Path
import sys

MODULE_PATH = Path(__file__).resolve().parents[1] / "br_dlc_quartet_native_dlc_id_owner_binding_tool.py"
spec = importlib.util.spec_from_file_location("owner_binding", MODULE_PATH)
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)


def synthetic_pe() -> bytes:
    data = bytearray(0xA00)
    data[:2] = b"MZ"
    struct.pack_into("<I", data, 0x3C, 0x80)
    data[0x80:0x84] = b"PE\0\0"
    coff = 0x84
    struct.pack_into("<H", data, coff, 0x8664)
    struct.pack_into("<H", data, coff + 2, 2)
    struct.pack_into("<H", data, coff + 16, 0xF0)
    optional = coff + 20
    struct.pack_into("<H", data, optional, 0x20B)
    struct.pack_into("<Q", data, optional + 24, 0x180000000)
    struct.pack_into("<I", data, optional + 56, 0x3000)
    struct.pack_into("<I", data, optional + 60, 0x400)
    struct.pack_into("<I", data, optional + 108, 16)
    table = optional + 0xF0

    data[table:table + 8] = b".text\0\0\0"
    struct.pack_into("<I", data, table + 8, 0x200)
    struct.pack_into("<I", data, table + 12, 0x1000)
    struct.pack_into("<I", data, table + 16, 0x200)
    struct.pack_into("<I", data, table + 20, 0x400)
    struct.pack_into("<I", data, table + 36, 0x60000020)

    table2 = table + 40
    data[table2:table2 + 8] = b".rdata\0\0"
    struct.pack_into("<I", data, table2 + 8, 0x400)
    struct.pack_into("<I", data, table2 + 12, 0x2000)
    struct.pack_into("<I", data, table2 + 16, 0x400)
    struct.pack_into("<I", data, table2 + 20, 0x600)
    struct.pack_into("<I", data, table2 + 36, 0x40000040)

    instruction_offset = 0x420
    instruction_rva = 0x1020
    tag_offset = 0x600
    tag_rva = 0x2000
    displacement = tag_rva - (instruction_rva + 7)
    data[instruction_offset:instruction_offset + 3] = b"\x48\x8d\x05"
    struct.pack_into("<i", data, instruction_offset + 3, displacement)
    struct.pack_into("<I", data, 0x430, 4313520)
    data[tag_offset:tag_offset + len(b"PC00_DLC_HMF")] = b"PC00_DLC_HMF"
    data[0x650:0x650 + len(b"4313520")] = b"4313520"
    return bytes(data)


class OwnerBindingTests(unittest.TestCase):
    def test_platform_catalog_stays_auxiliary(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "steam_emu.ini").write_text(
                "[Settings]\nAppId=3825390\n[DLC]\n4313520=BLUE REFLECTION Quartet: Uniform (Partner World Version)\n",
                encoding="utf-8",
            )
            app_id, rows = module.quartet_dlc_catalog(root)
            self.assertEqual(app_id, "3825390")
            self.assertTrue(rows[0]["costume_candidate"])
            self.assertFalse(rows[0]["semantic_authority"])

    def test_pe_and_exact_identifier_hits(self):
        payload = synthetic_pe()
        pe = module.parse_pe(payload)
        app_hits, tags = module.find_targets(
            payload,
            pe,
            "3825390",
            [{"dlc_id": "4313520", "name": "Uniform", "costume_candidate": True}],
        )
        self.assertTrue(any(row["identifier"] == "4313520" and row["representation"] == "uint32_le" for row in app_hits))
        self.assertEqual([row["token"] for row in tags], ["PC00_DLC_HMF"])

    def test_rip_relative_tag_reference_is_candidate_only(self):
        payload = synthetic_pe()
        pe = module.parse_pe(payload)
        app_hits, tags = module.find_targets(
            payload,
            pe,
            "3825390",
            [{"dlc_id": "4313520", "name": "Uniform", "costume_candidate": True}],
        )
        xrefs = module.rip_relative_xrefs(payload, pe, app_hits + tags, [])
        tag_rows = [row for row in xrefs if row["target_kind"] == "costume_tag"]
        self.assertEqual(len(tag_rows), 1)
        self.assertFalse(tag_rows[0]["binding_proven"])

    def test_same_function_correlation_never_auto_proves_owner(self):
        immediates = [{
            "identifier": "4313520",
            "id_kind": "dlc_id",
            "function_begin_rva": 0x1000,
            "function_end_rva": 0x1100,
            "reference_strength": "raw_uint32_in_executable_section",
        }]
        xrefs = [{
            "target_kind": "costume_tag",
            "target_value": "PC00_DLC_HMF",
            "function_begin_rva": 0x1000,
            "function_end_rva": 0x1100,
            "reference_strength": "executable_rip_relative_candidate",
        }]
        rows = module.function_correlations(immediates, xrefs)
        self.assertEqual(rows[0]["classification"], "same_function_static_candidate")
        self.assertFalse(rows[0]["exact_owner_binding_proven"])

    def test_state_scan_exports_metadata_only(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            save = root / "Savedata" / "slot01.dat"
            save.parent.mkdir()
            save.write_bytes(b"header PC00_DLC_HMF 4313520 tail")
            inventory, hits = module.scan_states([root], ["4313520"], ["PC00_DLC_HMF"])
            self.assertEqual(len(inventory), 1)
            self.assertTrue(hits)
            self.assertTrue(all(row["raw_content_exported"] is False for row in hits))


if __name__ == "__main__":
    unittest.main()
