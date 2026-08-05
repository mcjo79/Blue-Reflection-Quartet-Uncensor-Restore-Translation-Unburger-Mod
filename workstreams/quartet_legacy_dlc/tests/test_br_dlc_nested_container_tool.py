from __future__ import annotations

import csv
import importlib.util
import json
import struct
import sys
import tempfile
import unittest
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
WS = ROOT / "workstreams/quartet_legacy_dlc"
sys.path.insert(0, str(WS))
spec = importlib.util.spec_from_file_location("br_dlc_nested_container_tool", WS / "br_dlc_nested_container_tool.py")
assert spec and spec.loader
mod = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = mod
spec.loader.exec_module(mod)


def make_earc(members: list[tuple[str, bytes]]) -> bytes:
    filename_size = 1
    header_size = 28
    entry_size = 8 + 0x20 + filename_size * 0x10
    table_size = entry_size * len(members)
    payload_offset = header_size + table_size
    table = bytearray()
    payloads = bytearray()
    cursor = payload_offset
    for name, data in members:
        encoded = name.encode("ascii")
        if len(encoded) >= entry_size - 8:
            raise ValueError(name)
        table.extend(struct.pack("<2I", cursor, len(data)))
        table.extend(encoded + b"\0" * (entry_size - 8 - len(encoded)))
        payloads.extend(data)
        cursor += len(data)
    return struct.pack("<7I", mod.BR.EARC_MAGIC, filename_size, len(payloads), header_size, table_size, len(members), 10) + table + payloads


def gust_chunks(data: bytes, chunk: int = 37) -> bytes:
    output = bytearray()
    for offset in range(0, len(data), chunk):
        compressed = zlib.compress(data[offset:offset + chunk])
        output.extend(len(compressed).to_bytes(4, "little"))
        output.extend(compressed)
    output.extend(b"\0\0\0\0")
    return bytes(output)


def encode(data: bytes, key: bytes) -> bytes:
    return bytes(value ^ key[index % len(key)] for index, value in enumerate(data))


def make_pak(
    path: Path, entries: list[tuple[str, bytes]], *, fmt: str = "32",
    encrypted: bool = True, master_key: bytes = b"",
) -> None:
    if fmt == "32":
        entry_struct = struct.Struct("<128sI20sII")
        key_size = 20
    elif fmt == "64":
        entry_struct = struct.Struct("<128sI20sQQ")
        key_size = 20
    elif fmt == "a22":
        entry_struct = struct.Struct("<128sI32sIQQ")
        key_size = 32
    else:
        raise ValueError(fmt)
    header = struct.pack("<4I", 0x20000, len(entries), 16, 0)
    table = bytearray()
    payload = bytearray()
    for index, (name, data) in enumerate(entries):
        key = bytes(((index + 3 + n) % 251) + 1 for n in range(key_size)) if encrypted else bytes(key_size)
        raw_name = name.encode("ascii") + b"\0" * (128 - len(name))
        decode_key = bytes(
            value ^ master_key[n] for n, value in enumerate(key)
        ) if master_key else key
        stored_name = encode(raw_name, decode_key) if encrypted else raw_name
        stored_data = encode(data, decode_key) if encrypted else data
        if fmt == "32":
            table.extend(entry_struct.pack(stored_name, len(data), key, len(payload), 0))
        elif fmt == "64":
            table.extend(entry_struct.pack(stored_name, len(data), key, len(payload), 0))
        else:
            table.extend(entry_struct.pack(stored_name, len(data), key, 0, len(payload), 0))
        payload.extend(stored_data)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(header + table + payload)


def write_tsv(path: Path, fields: list[str], rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


class NestedContainerToolTest(unittest.TestCase):
    def test_selective_reader_supports_encrypted_a17_32(self) -> None:
        with tempfile.TemporaryDirectory() as temp_name:
            path = Path(temp_name) / "test.pak"
            entries = [("data/a.bin", b"A" * 31), ("data/b.bin", b"B" * 47), ("data/c.bin", b"C" * 13)]
            make_pak(path, entries, fmt="32", encrypted=True)
            index = mod.index_pak(path)
            self.assertEqual(index.format_name, "a17_32")
            data, entry = mod.read_pak_member(index, "data/b.bin")
            self.assertEqual(data, b"B" * 47)
            self.assertEqual(entry.size, 47)

    def test_selective_reader_supports_encrypted_a18_64(self) -> None:
        with tempfile.TemporaryDirectory() as temp_name:
            path = Path(temp_name) / "test.pak"
            entries = [("Data/x.bin", b"x" * 17), ("Data/y.bin", b"y" * 29), ("Data/z.bin", b"z" * 41)]
            make_pak(path, entries, fmt="64", encrypted=True)
            index = mod.index_pak(path)
            self.assertEqual(index.format_name, "a18_64")
            data, _ = mod.read_pak_member(index, "data/Y.bin")
            self.assertEqual(data, b"y" * 29)


    def test_selective_reader_detects_a24_a29_master_key_on_a18(self) -> None:
        with tempfile.TemporaryDirectory() as temp_name:
            path = Path(temp_name) / "quartet.pak"
            master = dict(mod.PAK_MASTER_KEYS)["A24_A29"]
            entries = [
                ("Data/B1/x64/character/pc00/a.bin", b"A" * 19),
                ("Data/B1/x64/character/pc00/b.bin", b"B" * 31),
                ("Data/B1/x64/character/pc00/c.bin", b"C" * 43),
            ]
            make_pak(path, entries, fmt="64", encrypted=True, master_key=master)
            index = mod.index_pak(path)
            self.assertEqual(index.format_name, "a18_64")
            self.assertEqual(index.master_key_label, "A24_A29")
            data, _ = mod.read_pak_member(index, "data/b1/x64/character/pc00/b.bin")
            self.assertEqual(data, b"B" * 31)

    def test_selective_reader_detects_master_key_on_a22(self) -> None:
        with tempfile.TemporaryDirectory() as temp_name:
            path = Path(temp_name) / "a22.pak"
            master = dict(mod.PAK_MASTER_KEYS)["A28"]
            entries = [
                ("data/a.bin", b"a" * 17),
                ("data/b.bin", b"b" * 29),
                ("data/c.bin", b"c" * 41),
            ]
            make_pak(path, entries, fmt="a22", encrypted=True, master_key=master)
            index = mod.index_pak(path)
            self.assertEqual(index.format_name, "a22_64")
            self.assertEqual(index.master_key_label, "A28")
            data, _ = mod.read_pak_member(index, "data/c.bin")
            self.assertEqual(data, b"c" * 41)

    def test_archive_root_notation_is_normalized_for_a17(self) -> None:
        with tempfile.TemporaryDirectory() as temp_name:
            path = Path(temp_name) / "test.pak"
            entries = [(r"\\data\\a.bin", b"A" * 7), (r"\\data\\b.bin", b"B" * 11), (r"\\data\\c.bin", b"C" * 13)]
            make_pak(path, entries, fmt="32", encrypted=True)
            index = mod.index_pak(path)
            self.assertEqual(index.format_name, "a17_32")
            self.assertEqual([entry.name for entry in index.entries], ["data/a.bin", "data/b.bin", "data/c.bin"])
            data, _ = mod.read_pak_member(index, "data/b.bin")
            self.assertEqual(data, b"B" * 11)

    def test_archive_root_notation_is_normalized_for_a18(self) -> None:
        with tempfile.TemporaryDirectory() as temp_name:
            path = Path(temp_name) / "test.pak"
            entries = [(r"\Data\x.bin", b"x" * 17), (r"\Data\y.bin", b"y" * 29), (r"\Data\z.bin", b"z" * 41)]
            make_pak(path, entries, fmt="64", encrypted=True)
            index = mod.index_pak(path)
            self.assertEqual(index.format_name, "a18_64")
            data, _ = mod.read_pak_member(index, "data/Y.bin")
            self.assertEqual(data, b"y" * 29)

    def test_gust_chunk_decode_and_earc_parse(self) -> None:
        earc = make_earc([("body_hi.g1m", b"G1M" * 20), ("cloth.bin", b"P" * 12)])
        decoded, kind, chunks = mod.decode_container_bytes(gust_chunks(earc), "synthetic")
        self.assertEqual(decoded, earc)
        self.assertEqual(kind, "gust_chunked_zlib")
        self.assertGreater(chunks, 1)
        parsed = mod.BR.parse_earc_payload(decoded)
        self.assertEqual(parsed["file_count"], 2)

    def test_nested_role_classification(self) -> None:
        self.assertEqual(mod.nested_role("body_hi.g1m"), "model_and_material")
        self.assertEqual(mod.nested_role("body.g1t"), "embedded_texture")
        self.assertEqual(mod.nested_role("skirt_physics.bin"), "cloth_or_physics")
        self.assertEqual(mod.nested_role("motion.g1a"), "animation")

    def test_audit_is_metadata_only_and_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temp_name:
            project = Path(temp_name) / "project"
            original = Path(temp_name) / "original"
            quartet = Path(temp_name) / "quartet"
            reports = project / ".local/reports/quartet_legacy_dlc"
            exact = reports / "exact_closure_evidence"
            technical = reports / "technical_registry_evidence"
            exact.mkdir(parents=True)
            technical.mkdir(parents=True)

            source_earc = make_earc([("pc00_bkn_hi.g1m", b"MODEL-SOURCE"), ("skirt_physics.bin", b"PHYSICS")])
            target_earc = make_earc([("pc00_bkn_hi.g1m", b"MODEL-TARGET"), ("skirt_physics.bin", b"PHYSICS")])
            source_container = gust_chunks(source_earc)
            target_container = gust_chunks(target_earc)
            source_path = "data/x64/character/pc00/pc00_dlc_bkn.elixir.gz"
            target_path = "data/b1/x64/character/pc00/pc00_dlc_bkn.elixir.gz"
            make_pak(original / "DATA/PACK00_02.PAK", [(source_path, source_container), ("data/filler1.bin", b"1"), ("data/filler2.bin", b"2")], fmt="32")
            make_pak(
                quartet / "Data/PACK10_02.PAK",
                [(target_path, target_container), ("data/filler1.bin", b"1"), ("data/filler2.bin", b"2")],
                fmt="64", master_key=dict(mod.PAK_MASTER_KEYS)["A24_A29"],
            )

            write_tsv(exact / "DLC_CANONICAL_CONTENT_CLOSURE.tsv", [
                "closure_id", "content_id", "technical_types", "scope_classification", "compatibility_status"
            ], [{
                "closure_id": "closure_test", "content_id": "costume_pc00_bkn", "technical_types": "costume_or_outfit",
                "scope_classification": "canonical_owner", "compatibility_status": "present_modified",
            }])
            write_tsv(exact / "DLC_EXACT_ROLE_CLOSURE.tsv", [
                "closure_id", "content_id", "role", "resolution_status", "evidence"
            ], [{
                "closure_id": "closure_test", "content_id": "costume_pc00_bkn", "role": "dry_model_or_container",
                "resolution_status": "resolved", "evidence": source_path,
            }])
            write_tsv(technical / "DLC_TECHNICAL_MEMBER_BINDINGS.tsv", [
                "content_id", "normalized_path", "source_archive", "source_path", "source_size", "source_sha256",
                "target_archive", "target_path", "target_size", "target_sha256"
            ], [{
                "content_id": "costume_pc00_bkn", "normalized_path": source_path,
                "source_archive": "DATA/PACK00_02.PAK", "source_path": source_path, "source_size": len(source_container),
                "source_sha256": mod.sha256_bytes(source_container), "target_archive": "Data/PACK10_02.PAK",
                "target_path": target_path, "target_size": len(target_container), "target_sha256": mod.sha256_bytes(target_container),
            }])

            report_root = reports / mod.REPORT_DIR_NAME
            archive, summary = mod.audit(project, original, quartet, report_root)
            self.assertTrue(archive.is_file())
            self.assertEqual(summary["canonical_owner_count"], 1)
            self.assertEqual(summary["parent_container_count"], 1)
            self.assertEqual(summary["nested_compatibility_counts"]["present_identical"], 1)
            self.assertEqual(summary["nested_compatibility_counts"]["present_modified"], 1)
            self.assertFalse(summary["policy"]["raw_assets_exported"])
            self.assertIn("A24_A29", summary["selective_pak_reader"]["master_keys"])
            with (report_root / "DLC_NESTED_PROFILE_READINESS.tsv").open(encoding="utf-8", newline="") as handle:
                readiness = list(csv.DictReader(handle, delimiter="\t"))
            self.assertEqual(readiness[0]["profile_build_allowed"], "False")
            mod.validate_report(report_root)
            forbidden = {path.suffix.casefold() for path in report_root.iterdir() if path.is_file()} & mod.FORBIDDEN_REPORT_SUFFIXES
            self.assertFalse(forbidden)


if __name__ == "__main__":
    unittest.main()
