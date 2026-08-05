from __future__ import annotations

import csv
import importlib.util
import json
import os
import struct
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
WS = ROOT / "workstreams/quartet_legacy_dlc"
sys.path.insert(0, str(WS))
spec = importlib.util.spec_from_file_location(
    "br_dlc_dry_pak_insertion_tool", WS / "br_dlc_dry_pak_insertion_tool.py"
)
assert spec and spec.loader
mod = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = mod
spec.loader.exec_module(mod)
N = mod.NESTED


def write_tsv(path: Path, fields: list[str], rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def xor(data: bytes, key: bytes) -> bytes:
    return bytes(value ^ key[index % len(key)] for index, value in enumerate(data))


def make_pak(
    path: Path,
    entries: list[tuple[str, bytes]],
    *,
    fmt: str = "a18_64",
    master_key_label: str = "A24_A29",
    flags: int = 0,
) -> None:
    specs = {name: (entry_struct, key_size, a22) for name, entry_struct, key_size, a22 in N.PAK_FORMATS}
    entry_struct, key_size, a22 = specs[fmt]
    master_key = dict(N.PAK_MASTER_KEYS)[master_key_label]
    table = bytearray()
    payload = bytearray()
    for index, (name, data) in enumerate(entries):
        key = bytes(((index + 17 + n) % 251) + 1 for n in range(key_size))
        effective = N.effective_entry_key(key, master_key)
        encoded_name = name.encode("ascii")
        plain_name = encoded_name + b"\0" * (128 - len(encoded_name))
        raw_name = xor(plain_name, effective)
        raw_data = xor(data, effective)
        if a22:
            table.extend(entry_struct.pack(raw_name, len(data), key, 0, len(payload), 0))
        else:
            table.extend(entry_struct.pack(raw_name, len(data), key, len(payload), 0))
        payload.extend(raw_data)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(N.PAK_HEADER.pack(0x20000, len(entries), N.PAK_HEADER.size, flags) + table + payload)


def prepare_prerequisite(project: Path, parent: bytes, texture: bytes) -> None:
    report = project / ".local/reports/quartet_legacy_dlc/transfer_probe_evidence"
    report.mkdir(parents=True)
    (report / "SUMMARY.json").write_text(json.dumps({
        "tool_version": "0.0.12",
        "status": "dry_local_workspace_built_and_wet_control_schema_ranges_located",
        "dry_parent_decoded_roundtrip_identical": True,
        "policy": {
            "game_modified": False,
            "profile_build_allowed": False,
            "profile_built": False,
            "profiles_activated": False,
            "target_pak_repacked": False,
        },
    }), encoding="utf-8")
    workspace = project / mod.TRANSFER_BUILD_RELATIVE / "source_exact/data/x64/character/pc00"
    workspace.mkdir(parents=True)
    parent_path = workspace / "pc00_dlc_bkn.elixir.gz"
    texture_path = workspace / "pc00_dlc_bkn.g1t"
    parent_path.write_bytes(parent)
    texture_path.write_bytes(texture)
    write_tsv(report / "DLC_BKN_DRY_TRANSFER_WORKSPACE.tsv", [
        "payload_role", "size", "sha256",
    ], [
        {"payload_role": "dry_parent_source_exact", "size": len(parent), "sha256": mod.sha256_bytes(parent)},
        {"payload_role": "dry_external_texture_source_exact", "size": len(texture), "sha256": mod.sha256_bytes(texture)},
    ])


class DryPakInsertionTest(unittest.TestCase):
    def test_copy_through_extension_adds_two_members_and_preserves_baseline(self) -> None:
        with tempfile.TemporaryDirectory() as temp_name:
            base = Path(temp_name)
            project = base / "project"
            quartet = base / "quartet"
            project.mkdir()
            parent = b"GUST_PARENT" + bytes(range(255)) * 11
            texture = b"G1T" + bytes(range(251)) * 17
            prepare_prerequisite(project, parent, texture)
            baseline = quartet / mod.TARGET_ARCHIVE_RELATIVE
            make_pak(baseline, [
                (r"\data\b1\x64\character\pc00\pc00_dlc_twl.elixir.gz", b"A" * 101),
                (r"\data\b1\x64\character\pc00\pc00_dlc_twl.g1t", b"B" * 203),
                (r"\data\b1\x64\character\pc01\pc01_scl.g1t", b"C" * 307),
            ])
            before = mod.sha256_file(baseline)
            output = project / ".local/reports/quartet_legacy_dlc" / mod.REPORT_DIR_NAME
            gust_pak = ROOT / ".local/vendor/gust_tools/gust_pak"
            archive, summary = mod.audit(project, quartet, gust_pak, output, timeout=60)
            self.assertTrue(archive.is_file())
            self.assertEqual(mod.sha256_file(baseline), before)
            self.assertEqual(summary["added_member_count"], 2)
            self.assertTrue(summary["existing_encrypted_data_region_identical"])
            candidate = project / mod.BUILD_RELATIVE / "candidate/PACK10_02.PAK"
            self.assertTrue(candidate.is_file())
            index = N.index_pak(candidate)
            decoded_parent, _ = N.read_pak_member(index, mod.ADDED_MEMBERS[0]["target_path"])
            decoded_texture, _ = N.read_pak_member(index, mod.ADDED_MEMBERS[1]["target_path"])
            self.assertEqual(decoded_parent, parent)
            self.assertEqual(decoded_texture, texture)
            validated = mod.validate_report(output)
            self.assertFalse(validated["policy"]["candidate_installed"])
            self.assertTrue(validated["policy"]["target_pak_repacked_locally"])

    def test_existing_target_member_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp_name:
            base = Path(temp_name)
            project = base / "project"
            quartet = base / "quartet"
            project.mkdir()
            parent = b"P" * 123
            texture = b"T" * 234
            prepare_prerequisite(project, parent, texture)
            baseline = quartet / mod.TARGET_ARCHIVE_RELATIVE
            make_pak(baseline, [
                (r"\data\b1\x64\character\pc00\pc00_dlc_bkn.elixir.gz", b"already"),
                (r"\data\b1\x64\character\pc00\pc00_dlc_twl.g1t", b"control"),
            ])
            with self.assertRaises(mod.DryPakInsertionError):
                mod.audit(
                    project, quartet, ROOT / ".local/vendor/gust_tools/gust_pak",
                    project / ".local/reports/quartet_legacy_dlc" / mod.REPORT_DIR_NAME,
                    timeout=60,
                )

    def test_validate_rejects_install_or_profile_authorization(self) -> None:
        with tempfile.TemporaryDirectory() as temp_name:
            root = Path(temp_name)
            for name in (
                "DLC_DRY_PAK_INSERTION_ARCHIVE.tsv",
                "DLC_DRY_PAK_INSERTED_MEMBERS.tsv",
                "DLC_DRY_PAK_BASELINE_PRESERVATION.tsv",
                "DLC_DRY_PAK_LAYOUT_VALIDATION.tsv",
                "DLC_DRY_PAK_GUST_LIST_VALIDATION.tsv",
                "DLC_DRY_PAK_INSERTION_GAPS.tsv",
            ):
                write_tsv(root / name, ["x"], [])
            (root / "SUMMARY.json").write_text(json.dumps({
                "type": "br_quartet_legacy_dlc_dry_pak_insertion_summary",
                "tool_version": mod.TOOL_VERSION,
                "status": "local_asset_only_pack10_02_candidate_built_not_installed",
                "added_member_count": 2,
                "existing_table_prefix_identical": True,
                "existing_encrypted_data_region_identical": True,
                "gust_pak_list_passed": True,
                "policy": {
                    "game_modified": True,
                    "git_modified": False,
                    "candidate_installed": False,
                    "profile_registered": False,
                    "profile_build_allowed": False,
                    "profiles_activated": False,
                    "runtime_validated": False,
                    "existing_pak_payloads_reencoded": False,
                    "raw_assets_exported_in_report": False,
                    "raw_assets_in_update": False,
                    "wet_variant_included": False,
                    "target_pak_repacked_locally": True,
                    "raw_assets_in_local_build": True,
                },
            }), encoding="utf-8")
            (root / "REPORT_MANIFEST.json").write_text('{"files":[]}\n', encoding="utf-8")
            with self.assertRaises(mod.DryPakInsertionError):
                mod.validate_report(root)


if __name__ == "__main__":
    unittest.main()
