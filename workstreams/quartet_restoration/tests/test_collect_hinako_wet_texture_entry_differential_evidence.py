import importlib.util
import io
import json
import struct
import tarfile
import tempfile
import unittest
from pathlib import Path

MODULE_PATH = Path(__file__).resolve().parents[1] / "155_collect_hinako_wet_texture_entry_differential_evidence.py"
spec = importlib.util.spec_from_file_location("stage155", MODULE_PATH)
mod = importlib.util.module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(mod)


def make_g1t(payloads, *, tex_type=0x08, width_exp=2, height_exp=2, platform=0x0A):
    n = len(payloads)
    header_size = 28 + 4 * n
    entries = []
    for payload in payloads:
        b0 = (1 << 4)  # 1 mipmap, 0 z-mipmaps
        b2 = ((height_exp & 0xF) << 4) | (width_exp & 0xF)
        entries.append(bytes([b0, tex_type, b2, 0, 0, 0, 0, 0]) + bytes(payload))
    offset_table_size = 4 * n
    offsets = []
    cursor = offset_table_size
    for e in entries:
        offsets.append(cursor)
        cursor += len(e)
    total_size = header_size + cursor
    version = int.from_bytes(b"0050", "big")
    header = struct.pack("<7I", mod.G1TG_MAGIC, version, total_size, header_size, n, platform, 0)
    flags = b"".join(struct.pack("<I", 0) for _ in range(n))
    offs = b"".join(struct.pack("<I", x) for x in offsets)
    return header + flags + offs + b"".join(entries)


class Stage155Tests(unittest.TestCase):
    def test_parse_g1t_little_endian_entries(self):
        data = make_g1t([b"abc", b"defgh"])
        g = mod.parse_g1t(data, "fixture")
        self.assertEqual(g["texture_count"], 2)
        self.assertEqual(g["byte_order"], "little")
        self.assertEqual(g["entries"][0]["payload_size"], 3)
        self.assertEqual(g["entries"][1]["payload_size"], 5)
        self.assertEqual(g["entries"][0]["width"], 4)
        self.assertEqual(g["entries"][0]["height"], 4)

    def test_parse_rejects_bad_magic(self):
        with self.assertRaises(mod.WetTextureAuditError):
            mod.parse_g1t(b"NOPE" + b"\0" * 40, "bad")

    def test_parse_rejects_zero_mipmap(self):
        data = bytearray(make_g1t([b"abc"]))
        # First entry starts at header_size + first offset = 32 + 4 = 36.
        data[36] = 0
        with self.assertRaises(mod.WetTextureAuditError):
            mod.parse_g1t(bytes(data), "bad-mips")

    def test_entry_shape_includes_dimensions_and_payload_size(self):
        a = mod.parse_g1t(make_g1t([b"a"]), "a")["entries"][0]
        b = mod.parse_g1t(make_g1t([b"aa"]), "b")["entries"][0]
        self.assertNotEqual(mod.entry_shape(a), mod.entry_shape(b))

    def test_shared_wet_payload_family_excludes_dry_reuse(self):
        common = mod.sha256_bytes(b"wet")
        rows = [
            {"side":"source","state_token":"nkd_w","texture_index":1,"payload_sha256":common, **self._shape()},
            {"side":"source","state_token":"scl_w","texture_index":2,"payload_sha256":common, **self._shape()},
            {"side":"source","state_token":"swm_w","texture_index":3,"payload_sha256":common, **self._shape()},
        ]
        fam, src = mod.build_shared_wet_families(rows)
        self.assertEqual(len(fam), 1)
        self.assertEqual(len(src), 1)
        self.assertTrue(src[0]["wet_only_shared_payload_family"])
        rows.append({"side":"source","state_token":"scl","texture_index":8,"payload_sha256":common, **self._shape()})
        fam, src = mod.build_shared_wet_families(rows)
        self.assertEqual(len(src), 0)
        self.assertFalse(fam[0]["wet_only_shared_payload_family"])

    def test_target_position_audit_flags_broken_shared_family(self):
        h = mod.sha256_bytes(b"src")
        fam = [{"payload_sha256":h,"wet_packs":"nkd_w,scl_w","locations":"nkd_w:1,scl_w:2"}]
        lookup = {
            ("target","nkd_w",1): {"payload_sha256":mod.sha256_bytes(b"a"), **self._shape()},
            ("target","scl_w",2): {"payload_sha256":mod.sha256_bytes(b"b"), **self._shape()},
        }
        rows = mod.audit_source_wet_only_target_positions(fam, lookup)
        self.assertEqual(len(rows), 1)
        self.assertTrue(rows[0]["candidate_common_wet_layer"])
        self.assertFalse(rows[0]["wet_skin_or_droplet_semantics_confirmed"])
        self.assertFalse(rows[0]["write_authorized"])

    def test_focus_transition_ids_are_frozen(self):
        self.assertEqual([(r["dry_texture_id"], r["wet_texture_id"]) for r in mod.FOCUS_TRANSITIONS], [(24,21),(26,23),(30,27)])

    def test_stage154_prerequisite_hash_is_user_report_hash(self):
        self.assertEqual(mod.STAGE154_SHA256, "caf47bbe9d7485f9545e089a01c6a159bdea9ce715dc6ec5720329c2c99a63c8")

    def test_forbidden_payload_extensions_include_dds_and_g1t(self):
        self.assertIn(".g1t", mod.FORBIDDEN_REPORT_EXTENSIONS)
        self.assertIn(".dds", mod.FORBIDDEN_REPORT_EXTENSIONS)

    @staticmethod
    def _shape():
        return {
            "texture_type":8,"mipmaps":1,"z_mipmaps":0,"width":4,"height":4,"payload_size":16,
            "flags_combined_hex":"0","extra_data_size":0,"depth_bits_hex":"00000000","extra_flags_hex":"00000000",
        }


if __name__ == "__main__":
    unittest.main()
