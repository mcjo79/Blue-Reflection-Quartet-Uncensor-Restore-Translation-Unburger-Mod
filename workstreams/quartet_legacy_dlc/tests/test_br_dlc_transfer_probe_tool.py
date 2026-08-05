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
spec = importlib.util.spec_from_file_location("br_dlc_transfer_probe_tool", WS / "br_dlc_transfer_probe_tool.py")
assert spec and spec.loader
mod = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = mod
spec.loader.exec_module(mod)
N = mod.NESTED
BR = mod.BR


def write_tsv(path: Path, fields: list[str], rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def g1m(parameters: list[tuple[str, int, list[object]]]) -> bytes:
    parameter_payload = bytearray()
    for name, buffer_type, values in parameters:
        name_bytes = name.encode("utf-8") + b"\0"
        raw_values = bytearray()
        for value in values:
            if buffer_type == 1:
                raw_values.extend(struct.pack("<f", float(value)))
            elif buffer_type == 4:
                raw_values.extend(struct.pack("<4f", *value))
            elif buffer_type == 5:
                raw_values.extend(struct.pack("<i", int(value)))
            else:
                raise ValueError(buffer_type)
        size = 16 + len(name_bytes) + len(raw_values)
        parameter_payload.extend(struct.pack("<3I2H", size, len(name_bytes), 0, buffer_type, len(values)))
        parameter_payload.extend(name_bytes)
        parameter_payload.extend(raw_values)
    block = struct.pack("<I", len(parameters)) + parameter_payload
    section = struct.pack("<3I", BR.G1MG_SHADER_PARAMS_SECTION, 12 + len(block), 1) + block
    g1mg_size = BR.G1MG_HEADER_SIZE + len(section)
    g1mg = (
        b"G1MG" + struct.pack("<2I", 0x30303430, g1mg_size) + b"DX11"
        + struct.pack("<I6f", 0, 0.0, 0.0, 0.0, 1.0, 1.0, 1.0)
        + struct.pack("<I", 1) + section
    )
    total = BR.G1M_HEADER_SIZE + len(g1mg)
    return b"_M1G" + struct.pack("<5I", 0x30303430, total, BR.G1M_HEADER_SIZE, 0, 1) + g1mg


def earc(members: list[tuple[str, bytes]]) -> bytes:
    filename_size = 1
    header_size = 28
    entry_size = 8 + 0x20 + filename_size * 0x10
    table_size = entry_size * len(members)
    cursor = header_size + table_size
    table = bytearray()
    payload = bytearray()
    for name, data in members:
        encoded = name.encode("ascii")
        table.extend(struct.pack("<2I", cursor, len(data)))
        table.extend(encoded + b"\0" * (entry_size - 8 - len(encoded)))
        payload.extend(data)
        cursor += len(data)
    return struct.pack("<7I", BR.EARC_MAGIC, filename_size, len(payload), header_size, table_size, len(members), 10) + table + payload


def gust(data: bytes, chunk: int = 73) -> bytes:
    sizes = [min(chunk, len(data) - offset) for offset in range(0, len(data), chunk)]
    return mod.encode_gust_chunks(data, sizes)


def xor(data: bytes, key: bytes) -> bytes:
    return bytes(value ^ key[index % len(key)] for index, value in enumerate(data))


def make_pak(path: Path, entries: list[tuple[str, bytes]], *, fmt: str, master_key: bytes = b"") -> None:
    if fmt == "32":
        entry_struct = struct.Struct("<128sI20sII"); key_size = 20
    elif fmt == "64":
        entry_struct = struct.Struct("<128sI20sQQ"); key_size = 20
    else:
        raise ValueError(fmt)
    table = bytearray(); payload = bytearray()
    for index, (name, data) in enumerate(entries):
        key = bytes(((index + 5 + n) % 251) + 1 for n in range(key_size))
        effective = bytes(value ^ master_key[n] for n, value in enumerate(key)) if master_key else key
        raw_name = name.encode("ascii") + b"\0" * (128 - len(name))
        table.extend(entry_struct.pack(xor(raw_name, effective), len(data), key, len(payload), 0))
        payload.extend(xor(data, effective))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(struct.pack("<4I", 0x20000, len(entries), 16, 0) + table + payload)


class TransferProbeTest(unittest.TestCase):
    def test_gust_wrapper_roundtrip_preserves_decoded_bytes(self) -> None:
        payload = bytes(range(251)) * 7
        raw = gust(payload, 91)
        decoded, sizes, _ = mod.gust_chunk_layout(raw, "test")
        rebuilt = mod.encode_gust_chunks(decoded, sizes)
        decoded2, sizes2, _ = mod.gust_chunk_layout(rebuilt, "rebuilt")
        self.assertEqual(decoded2, payload)
        self.assertEqual(sizes2, sizes)

    def test_g1m_layout_locates_added_parameter_record(self) -> None:
        source = g1m([("fAlpha", 1, [0.5])])
        target = g1m([("fAlpha", 1, [0.5]), ("parameterForMeshBlend", 4, [(1.0, 1.0, 1.0, 1.0)])])
        left = mod.parse_g1m_layout(source, "source")
        right = mod.parse_g1m_layout(target, "target")
        source_keys = {row["parameter_key"] for row in left["parameters"]}
        added = [row for row in right["parameters"] if row["parameter_key"] not in source_keys]
        self.assertEqual(len(added), 1)
        self.assertEqual(added[0]["parameter_name"], "parameterForMeshBlend")
        self.assertGreater(added[0]["record_size"], 32)
        self.assertEqual(target[added[0]["record_offset"]:added[0]["record_offset"] + added[0]["record_size"]].__len__(), added[0]["record_size"])

    def test_diff_ranges_reconstruct_target(self) -> None:
        source = b"abcd" + b"1234" + b"wxyz"
        target = b"abcd" + b"XX" + b"1234" + b"wxyz"
        rows = mod.diff_ranges(source, target)
        self.assertEqual(sum(row["target_size"] - row["source_size"] for row in rows), 2)
        self.assertTrue(any(row["operation"] == "insert" for row in rows))

    def test_validate_rejects_profile_authorization(self) -> None:
        with tempfile.TemporaryDirectory() as temp_name:
            root = Path(temp_name)
            for name in (
                "DLC_BKN_DRY_TRANSFER_WORKSPACE.tsv", "DLC_BKN_DRY_PARENT_ROUNDTRIP.tsv",
                "DLC_TWL_WET_G1M_PARAMETER_INSERT_RANGES.tsv", "DLC_TWL_WET_G1M_CHUNK_ENVELOPES.tsv",
                "DLC_TWL_WET_SWG_DELTA_RANGES.tsv", "DLC_BKN_WET_CONVERSION_PLAN.tsv",
                "DLC_TRANSFER_PROBE_GAPS.tsv",
            ):
                write_tsv(root / name, ["x"], [])
            (root / "SUMMARY.json").write_text(json.dumps({
                "tool_version": mod.TOOL_VERSION,
                "dry_parent_decoded_roundtrip_identical": True,
                "policy": {
                    "raw_assets_exported_in_report": False, "target_pak_repacked": False,
                    "profile_built": False, "profile_build_allowed": True, "profiles_activated": False,
                    "game_modified": False, "git_modified": False,
                },
            }))
            (root / "REPORT_MANIFEST.json").write_text('{"files":[]}\n')
            with self.assertRaises(mod.TransferProbeError):
                mod.validate_report(root)

    def test_end_to_end_builds_local_workspace_and_metadata_only_report(self) -> None:
        with tempfile.TemporaryDirectory() as temp_name:
            base = Path(temp_name)
            project = base / "project"; original = base / "original"; quartet = base / "quartet"
            reports = project / ".local/reports/quartet_legacy_dlc"
            control = reports / "control_compatibility_evidence"
            bounded = reports / "bounded_family_evidence"
            nested = reports / "nested_container_evidence"
            external = reports / "external_dependency_closure_evidence"
            for directory in (control, bounded, nested, external):
                directory.mkdir(parents=True)
            (control / "SUMMARY.json").write_text(json.dumps({"tool_version": "0.0.11"}))
            (bounded / "SUMMARY.json").write_text(json.dumps({"tool_version": "0.0.10"}))
            (nested / "SUMMARY.json").write_text(json.dumps({"tool_version": "0.0.7"}))
            (external / "SUMMARY.json").write_text(json.dumps({"tool_version": "0.0.8"}))

            source_g1m = g1m([("fAlpha", 1, [0.5])])
            target_g1m = g1m([("fAlpha", 1, [0.5]), ("parameterForMeshBlend", 4, [(1.0, 1.0, 1.0, 1.0)])])
            bkn_parent_path = "data/x64/character/pc00/pc00_dlc_bkn.elixir.gz"
            twl_source_path = "data/x64/character/pc00/pc00_dlc_twl_w.elixir.gz"
            twl_target_path = "data/b1/x64/character/pc00/pc00_dlc_twl_w.elixir.gz"
            bkn_texture_path = "data/x64/character/pc00/pc00_dlc_bkn.g1t"
            bkn_parent = gust(earc([("PC00_DLC_Bkn_default.g1m", source_g1m), ("PC00_DLC_Bkn.swg", b"S" * 64)]))
            source_swg = b"A" * 64 + b"B" * 64
            target_swg = b"A" * 64 + b"0123456789ABCDEF" + b"B" * 64
            twl_source = gust(earc([("PC00_DLC_Twl_W_default.g1m", source_g1m), ("PC00_DLC_Twl_W.swg", source_swg)]))
            twl_target = gust(earc([("PC00_DLC_Twl_W_default.g1m", target_g1m), ("PC00_DLC_Twl_W.swg", target_swg), ("dummy", b"")]))
            bkn_texture = b"G1T" + bytes(range(128))
            make_pak(original / "DATA/PACK00_02.PAK", [
                (bkn_parent_path, bkn_parent), (bkn_texture_path, bkn_texture), (twl_source_path, twl_source),
                ("data/f1.bin", b"1"), ("data/f2.bin", b"2"),
            ], fmt="32")
            make_pak(quartet / "Data/PACK10_02.PAK", [
                (twl_target_path, twl_target), ("data/f1.bin", b"1"), ("data/f2.bin", b"2"),
            ], fmt="64", master_key=dict(N.PAK_MASTER_KEYS)["A24_A29"])

            write_tsv(nested / "DLC_NESTED_CONTAINER_INVENTORY.tsv", [
                "content_id", "parent_role", "source_archive", "source_path", "source_size", "source_sha256",
                "target_archive", "target_path", "target_decoded_sha256",
            ], [
                {"content_id": "costume_pc00_bkn", "parent_role": "dry_model_or_container", "source_archive": "DATA/PACK00_02.PAK", "source_path": bkn_parent_path, "source_size": len(bkn_parent), "source_sha256": mod.sha256_bytes(bkn_parent), "target_archive": "", "target_path": "", "target_decoded_sha256": ""},
                {"content_id": "costume_pc00_twl", "parent_role": "wet_model_or_container", "source_archive": "DATA/PACK00_02.PAK", "source_path": twl_source_path, "source_size": len(twl_source), "source_sha256": mod.sha256_bytes(twl_source), "target_archive": "Data/PACK10_02.PAK", "target_path": twl_target_path, "target_decoded_sha256": mod.sha256_bytes(N.decode_container_bytes(twl_target, "target")[0])},
            ])
            write_tsv(nested / "DLC_NESTED_MEMBER_BINDINGS.tsv", [
                "content_id", "parent_path", "member_name", "compatibility_status",
            ], [
                {"content_id": "costume_pc00_twl", "parent_path": twl_source_path, "member_name": "PC00_DLC_Twl_W_default.g1m", "compatibility_status": "present_modified"},
                {"content_id": "costume_pc00_twl", "parent_path": twl_source_path, "member_name": "PC00_DLC_Twl_W.swg", "compatibility_status": "present_modified"},
            ])
            write_tsv(external / "DLC_EXTERNAL_TEXTURE_BINDINGS.tsv", [
                "content_id", "texture_role", "source_archive", "source_path", "source_size", "source_sha256",
            ], [{"content_id": "costume_pc00_bkn", "texture_role": "dry_texture", "source_archive": "DATA/PACK00_02.PAK", "source_path": bkn_texture_path, "source_size": len(bkn_texture), "source_sha256": mod.sha256_bytes(bkn_texture)}])
            write_tsv(control / "DLC_CONTROL_MATERIAL_BLOCK_MAPPING.tsv", [
                "content_id", "parent_role", "member_part", "candidate_block_index", "transitive_mapping_status", "target_control_added_parameters",
            ], [
                {"content_id": "costume_pc00_bkn", "parent_role": "wet_model_or_container", "member_part": "default", "candidate_block_index": "0", "transitive_mapping_status": "unique_control_bridge", "target_control_added_parameters": '["parameterForMeshBlend"]'},
                {"content_id": "costume_pc00_bkn", "parent_role": "wet_model_or_container", "member_part": "default", "candidate_block_index": "1", "transitive_mapping_status": "ambiguous_control_bridge", "target_control_added_parameters": "[]"},
            ])
            write_tsv(control / "DLC_CANDIDATE_TRANSFER_CLASSIFICATION.tsv", ["x"], [])

            output = reports / mod.REPORT_DIR_NAME
            archive, summary = mod.audit(project, original, quartet, output)
            self.assertTrue(archive.is_file())
            self.assertEqual(summary["dry_workspace_payload_rows"], 3)
            self.assertEqual(summary["wet_added_parameter_records"], 1)
            self.assertEqual(summary["wet_swg_net_size_delta"], 16)
            self.assertTrue((project / mod.BUILD_RELATIVE / "TRANSFER_PROBE.json").is_file())
            self.assertFalse(any(path.suffix.casefold() in mod.FORBIDDEN_REPORT_SUFFIXES for path in output.iterdir() if path.is_file()))
            validated = mod.validate_report(output)
            self.assertFalse(validated["policy"]["target_pak_repacked"])


if __name__ == "__main__":
    unittest.main()
