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
spec = importlib.util.spec_from_file_location("br_dlc_bounded_family_tool", WS / "br_dlc_bounded_family_tool.py")
assert spec and spec.loader
mod = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = mod
spec.loader.exec_module(mod)
N = mod.NESTED
BR = mod.BR


def g1m(parameters: list[tuple[str, int, list[object]]]) -> bytes:
    endian = "<"
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


def make_earc(members: list[tuple[str, bytes]]) -> bytes:
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


def gust_chunks(data: bytes, chunk: int = 79) -> bytes:
    out = bytearray()
    for offset in range(0, len(data), chunk):
        compressed = zlib.compress(data[offset:offset + chunk])
        out.extend(len(compressed).to_bytes(4, "little"))
        out.extend(compressed)
    out.extend(b"\0\0\0\0")
    return bytes(out)


def encode(data: bytes, key: bytes) -> bytes:
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
        key = bytes(((index + 7 + n) % 251) + 1 for n in range(key_size))
        effective = bytes(value ^ master_key[n] for n, value in enumerate(key)) if master_key else key
        raw_name = name.encode("ascii") + b"\0" * (128 - len(name))
        stored_name = encode(raw_name, effective)
        stored_data = encode(data, effective)
        table.extend(entry_struct.pack(stored_name, len(data), key, len(payload), 0))
        payload.extend(stored_data)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(struct.pack("<4I", 0x20000, len(entries), 16, 0) + table + payload)


def write_tsv(path: Path, fields: list[str], rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, delimiter="\t", lineterminator="\n")
        writer.writeheader(); writer.writerows(rows)


class BoundedFamilyToolTest(unittest.TestCase):
    def test_safe_tokens_are_bounded_and_technical(self) -> None:
        payload = b"noise hello texture_pc00.g1t PC00_DLC_Bkn materialAlpha other"
        tokens = mod.safe_tokens(payload)
        self.assertIn("texture_pc00.g1t", tokens)
        self.assertIn("PC00_DLC_Bkn", tokens)
        self.assertNotIn("hello", tokens)

    def test_structural_signature_is_metadata_only(self) -> None:
        payload = b"PC00_DLC_Bkn.swg\0" + struct.pack("<8I", *range(8))
        row = mod.structural_signature(payload)
        self.assertEqual(row["sha256"], mod.sha256_bytes(payload))
        self.assertGreaterEqual(row["technical_token_count"], 1)
        self.assertNotIn("payload", row)

    def test_audit_parses_selected_control_and_portable_family(self) -> None:
        with tempfile.TemporaryDirectory() as temp_name:
            base = Path(temp_name)
            project = base / "project"; original = base / "original"; quartet = base / "quartet"
            reports = project / ".local/reports/quartet_legacy_dlc"
            external = reports / "external_dependency_closure_evidence"
            nested = reports / "nested_container_evidence"
            external.mkdir(parents=True); nested.mkdir(parents=True)

            source_twl_g1m = g1m([("fTranslucency", 1, [0.5]), ("texture_pc00_twl.g1t", 5, [1])])
            target_twl_g1m = g1m([("fTranslucency", 1, [0.75]), ("texture_pc00_twl.g1t", 5, [1])])
            source_bkn_g1m = g1m([("fTranslucency", 1, [0.4]), ("texture_pc00_bkn.g1t", 5, [1])])
            swg_shared = b"PC00_DLC_shared.swg\0" + struct.pack("<20I", *range(20))
            oid = b"PC00_DLC_Oid material cloth\0" + struct.pack("<12I", *range(12))

            parents: dict[str, bytes] = {}
            parents["data/x64/character/pc00/pc00_dlc_twl.elixir.gz"] = gust_chunks(make_earc([
                ("PC00_DLC_Twl.g1m", source_twl_g1m), ("PC00_DLC_Twl.swg", swg_shared), ("PC00_DLC_TwlOid.bin", oid),
            ]))
            parents["data/x64/character/pc00/pc00_dlc_twl_w.elixir.gz"] = gust_chunks(make_earc([
                ("PC00_DLC_Twl_W.g1m", source_twl_g1m), ("PC00_DLC_Twl_W.swg", swg_shared), ("PC00_DLC_Twl_WOid.bin", oid),
            ]))
            parents["data/x64/character/pc00/pc00_dlc_bkn.elixir.gz"] = gust_chunks(make_earc([
                ("PC00_DLC_Bkn.g1m", source_bkn_g1m), ("PC00_DLC_Bkn.swg", swg_shared), ("PC00_DLC_BknOid.bin", oid),
            ]))
            parents["data/x64/character/pc00/pc00_dlc_bkn_w.elixir.gz"] = gust_chunks(make_earc([
                ("PC00_DLC_Bkn_W.g1m", source_bkn_g1m), ("PC00_DLC_Bkn_W.swg", swg_shared), ("PC00_DLC_Bkn_WOid.bin", oid),
            ]))
            target_parents = {
                "data/b1/x64/character/pc00/pc00_dlc_twl.elixir.gz": gust_chunks(make_earc([
                    ("PC00_DLC_Twl.g1m", source_twl_g1m), ("PC00_DLC_Twl.swg", swg_shared), ("PC00_DLC_TwlOid.bin", oid),
                ])),
                "data/b1/x64/character/pc00/pc00_dlc_twl_w.elixir.gz": gust_chunks(make_earc([
                    ("PC00_DLC_Twl_W.g1m", target_twl_g1m), ("PC00_DLC_Twl_W.swg", swg_shared + b"X"), ("PC00_DLC_Twl_WOid.bin", oid),
                    ("dummy", b""),
                ])),
            }
            make_pak(original / "DATA/PACK00_02.PAK", list(parents.items()) + [("data/f1.bin", b"1"), ("data/f2.bin", b"2")], fmt="32")
            make_pak(quartet / "Data/PACK10_02.PAK", list(target_parents.items()) + [("data/f1.bin", b"1"), ("data/f2.bin", b"2")], fmt="64", master_key=dict(N.PAK_MASTER_KEYS)["A24_A29"])

            write_tsv(external / "DLC_BOUNDED_FAMILY_CANDIDATES.tsv", [
                "content_id", "candidate_kind", "selected_for_next_audit",
            ], [
                {"content_id": "costume_pc00_twl", "candidate_kind": "positive_control", "selected_for_next_audit": "true"},
                {"content_id": "costume_pc00_bkn", "candidate_kind": "portable_transfer_candidate", "selected_for_next_audit": "true"},
            ])

            container_fields = [
                "content_id", "parent_role", "normalized_path", "source_archive", "source_path", "source_sha256",
                "target_archive", "target_path", "target_decoded_sha256",
            ]
            container_rows = []
            for content, token in (("costume_pc00_twl", "twl"), ("costume_pc00_bkn", "bkn")):
                for role, wet in (("dry_model_or_container", ""), ("wet_model_or_container", "_w")):
                    source_path = f"data/x64/character/pc00/pc00_dlc_{token}{wet}.elixir.gz"
                    target_path = f"data/b1/x64/character/pc00/pc00_dlc_{token}{wet}.elixir.gz" if content.endswith("twl") else ""
                    container_rows.append({
                        "content_id": content, "parent_role": role, "normalized_path": source_path,
                        "source_archive": "DATA/PACK00_02.PAK", "source_path": source_path,
                        "source_sha256": mod.sha256_bytes(parents[source_path]),
                        "target_archive": "Data/PACK10_02.PAK" if target_path else "", "target_path": target_path,
                        "target_decoded_sha256": "",
                    })
            write_tsv(nested / "DLC_NESTED_CONTAINER_INVENTORY.tsv", container_fields, container_rows)

            binding_fields = [
                "content_id", "parent_path", "member_key", "member_name", "nested_role", "source_sha256",
                "target_sha256", "compatibility_status",
            ]
            binding_rows = []
            for row in container_rows:
                content = row["content_id"]; source_path = row["source_path"]
                token = "Twl" if content.endswith("twl") else "Bkn"
                wet = "_W" if "_w.elixir" in source_path else ""
                members = [
                    (f"PC00_DLC_{token}{wet}.g1m", "model_and_material"),
                    (f"PC00_DLC_{token}{wet}.swg", "other_nested_member"),
                    (f"PC00_DLC_{token}{wet}Oid.bin", "auxiliary_descriptor"),
                ]
                source_decoded, _, _ = N.decode_container_bytes(parents[source_path], source_path)
                source_archive = BR.parse_earc_payload(source_decoded, include_member_payloads=True)
                smap = {m["name"].casefold(): m for m in source_archive["members"]}
                target_map = {}
                if row["target_path"]:
                    target_decoded, _, _ = N.decode_container_bytes(target_parents[row["target_path"]], row["target_path"])
                    target_archive = BR.parse_earc_payload(target_decoded, include_member_payloads=True)
                    target_map = {m["name"].casefold(): m for m in target_archive["members"]}
                for name, role in members:
                    s = smap[name.casefold()]; t = target_map.get(name.casefold())
                    binding_rows.append({
                        "content_id": content, "parent_path": source_path,
                        "member_key": s["comparison_key"], "member_name": name, "nested_role": role,
                        "source_sha256": s["sha256"], "target_sha256": "" if t is None else t["sha256"],
                        "compatibility_status": "missing_portable_from_br1" if t is None else ("present_identical" if s["sha256"] == t["sha256"] else "present_modified"),
                    })
                if row["target_path"] and "_w.elixir" in source_path:
                    target_dummy = target_map["dummy"]
                    binding_rows.append({
                        "content_id": content, "parent_path": source_path,
                        "member_key": target_dummy["comparison_key"], "member_name": "dummy", "nested_role": "other_nested_member",
                        "source_sha256": "", "target_sha256": target_dummy["sha256"],
                        "compatibility_status": "target_only_nested_member",
                    })
            write_tsv(nested / "DLC_NESTED_MEMBER_BINDINGS.tsv", binding_fields, binding_rows)

            report_root = reports / mod.REPORT_DIR_NAME
            archive, summary = mod.audit(project, original, quartet, report_root)
            self.assertTrue(archive.is_file())
            self.assertEqual(len(summary["selected_families"]), 2)
            self.assertEqual(summary["g1m_member_count"], 4)
            self.assertGreater(summary["material_parameter_rows"], 0)
            self.assertGreater(summary["material_difference_rows"], 0)
            self.assertFalse(summary["policy"]["raw_assets_exported"])
            self.assertEqual(summary["target_only_member_rows"], 1)
            with (report_root / "DLC_BOUNDED_FAMILY_MEMBER_AUDIT.tsv").open(encoding="utf-8", newline="") as handle:
                member_audit = list(csv.DictReader(handle, delimiter="\t"))
            dummy_row = next(row for row in member_audit if row["member_key"] == "dummy#0")
            self.assertEqual(dummy_row["compatibility_status"], "target_only_nested_member")
            self.assertEqual(dummy_row["source_sha256"], "")
            self.assertEqual(dummy_row["target_sha256"], mod.sha256_bytes(b""))
            self.assertEqual(dummy_row["source_parse_status"], "source_missing_expected_target_only")
            validated = mod.validate_report(report_root)
            self.assertEqual(validated["tool_version"], "0.0.10")
            with (report_root / "DLC_BOUNDED_PROFILE_READINESS.tsv").open(encoding="utf-8", newline="") as handle:
                readiness = list(csv.DictReader(handle, delimiter="\t"))
            self.assertTrue(all(row["profile_build_allowed"] == "false" for row in readiness))
            forbidden = {p.suffix.casefold() for p in report_root.iterdir() if p.is_file()} & mod.FORBIDDEN_SUFFIXES
            self.assertFalse(forbidden)

    def test_validate_rejects_build_authorization(self) -> None:
        with tempfile.TemporaryDirectory() as temp_name:
            root = Path(temp_name)
            for name in (
                "DLC_BOUNDED_FAMILY_MEMBER_AUDIT.tsv", "DLC_BOUNDED_G1M_MATERIAL_PARAMETERS.tsv",
                "DLC_BOUNDED_G1M_MATERIAL_DIFFS.tsv", "DLC_BOUNDED_TECHNICAL_REFERENCE_TOKENS.tsv",
                "DLC_BOUNDED_CLOTH_STRUCTURE_AUDIT.tsv", "DLC_BOUNDED_SHARED_MEMBER_BINDINGS.tsv",
                "DLC_BOUNDED_FAMILY_GAPS.tsv",
            ):
                write_tsv(root / name, ["x"], [])
            write_tsv(root / "DLC_BOUNDED_PROFILE_READINESS.tsv", ["candidate_kind", "profile_build_allowed"], [
                {"candidate_kind": "positive_control", "profile_build_allowed": "true"},
                {"candidate_kind": "portable_transfer_candidate", "profile_build_allowed": "false"},
            ])
            (root / "DLC_BOUNDED_FAMILY_GRAPH.json").write_text("{}\n")
            (root / "SUMMARY.json").write_text(json.dumps({"policy": {"raw_assets_exported": False, "profiles_built": False}}))
            with self.assertRaises(mod.BoundedFamilyError):
                mod.validate_report(root)


if __name__ == "__main__":
    unittest.main()
