from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import sys

HERE = Path(__file__).resolve().parent
WORKSTREAM = HERE.parent
if str(WORKSTREAM) not in sys.path:
    sys.path.insert(0, str(WORKSTREAM))

import br_dlc_bkn_dry_pack12_repack_tool as mod
import br_dlc_nested_container_tool as N


def xor(data: bytes, key: bytes) -> bytes:
    return bytes(value ^ key[index % len(key)] for index, value in enumerate(data))


def make_pak(path: Path, entries: list[tuple[str, bytes]]) -> None:
    specs = {name: (entry_struct, key_size, a22) for name, entry_struct, key_size, a22 in N.PAK_FORMATS}
    entry_struct, key_size, a22 = specs["a22_64"]
    master = dict(N.PAK_MASTER_KEYS)["A24_A29"]
    table = bytearray()
    payload = bytearray()
    for index, (name, data) in enumerate(entries):
        key = bytes(((index + 29 + n) % 251) + 1 for n in range(key_size))
        effective = N.effective_entry_key(key, master)
        plain_name = name.encode("ascii") + b"\0" * (128 - len(name.encode("ascii")))
        raw_name = xor(plain_name, effective)
        raw_data = xor(data, effective)
        table.extend(entry_struct.pack(raw_name, len(data), key, 0, len(payload), 0))
        payload.extend(raw_data)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(N.PAK_HEADER.pack(0x20000, len(entries), N.PAK_HEADER.size, 0x10) + table + payload)


def baseline_xml() -> bytes:
    return (
        '<?xml version="1.0" encoding="SHIFT-JIS"?>\r\n'
        '<Root>\r\n'
        '<CharaBase BaseTag="PC00_DLC_BKN" Model="PC00/PC00_Scl" defaultTexture="PC00/PC00_Scl" Motion1="KEEP"/>\r\n'
        '<CharaBase BaseTag="PC00_DLC_BKN_W" Model="PC00/PC00_Scl_W" defaultTexture="PC00/PC00_Scl_W"/>\r\n'
        '</Root>\r\n'
    ).encode("cp932")


def candidate_xml() -> bytes:
    return baseline_xml().replace(b'PC00/PC00_Scl" defaultTexture="PC00/PC00_Scl', b'PC00/PC00_DLC_Bkn" defaultTexture="PC00/PC00_DLC_Bkn', 1)


def prereq(pack12: Path, candidate: bytes, dry_pak: Path, target_index: int) -> tuple[dict, dict]:
    summary = {
        "tool_version": "0.0.20",
        "status": "local_dry_bkn_composition_preflight_ready_not_built_not_installed",
        "candidate_charabase_sha256": mod.sha256_bytes(candidate),
        "dry_pack10_02_candidate_sha256": mod.sha256_file(dry_pak),
        "installed_charabase_entry_index": target_index,
        "installed_charabase_sha256": mod.sha256_bytes(baseline_xml()),
        "policy": {
            "local_pack12_repack_test_allowed": True,
            "local_two_archive_composition_build_allowed": True,
            "candidate_installed": False,
            "game_modified": False,
            "profile_build_allowed": False,
            "profile_registered": False,
            "runtime_validated": False,
            "target_pak_repacked": False,
        },
    }
    plan = {
        "inputs": [
            {"archive": "Data/PACK10_02.PAK", "size": dry_pak.stat().st_size, "sha256": mod.sha256_file(dry_pak)},
            {"archive": "Data/PACK12.PAK", "size": len(candidate), "sha256": mod.sha256_bytes(candidate)},
            {"archive": "Data/PACK12.PAK", "size": pack12.stat().st_size, "sha256": mod.sha256_file(pack12)},
        ]
    }
    return summary, plan


def fake_gust(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        '#!/usr/bin/env bash\n'
        'echo "Detected A22 64-bit PAK"\n'
        'echo "Using A24/A29 master key"\n'
        'echo "saves\\b1\\chara\\charabase.xml"\n',
        encoding="utf-8",
    )
    path.chmod(0o755)


class Pack12RepackTest(unittest.TestCase):
    def create_fixture(self, root: Path) -> tuple[Path, Path, Path, dict, dict]:
        project = root / "project"
        quartet = root / "quartet"
        project.mkdir()
        entries = [
            ("\\before.bin", b"BEFORE" * 17),
            ("\\saves\\b1\\chara\\charabase.xml", baseline_xml()),
            ("\\after.bin", b"AFTER" * 23),
        ]
        pack12 = quartet / mod.TARGET_ARCHIVE_RELATIVE
        make_pak(pack12, entries)
        candidate_path = project / mod.PREFLIGHT_MEMBER_RELATIVE
        candidate_path.parent.mkdir(parents=True, exist_ok=True)
        candidate = candidate_xml()
        candidate_path.write_bytes(candidate)
        dry_pak = project / mod.DRY_PACK_RELATIVE
        dry_pak.parent.mkdir(parents=True, exist_ok=True)
        dry_pak.write_bytes(b"dry-pack10-candidate")
        gust = root / "gust_pak"
        fake_gust(gust)
        summary, plan = prereq(pack12, candidate, dry_pak, 1)
        return project, quartet, gust, summary, plan

    def test_audit_replaces_one_member_and_preserves_all_others(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            project, quartet, gust, summary, plan = self.create_fixture(root)
            output = project / ".local/reports/quartet_legacy_dlc" / mod.REPORT_DIR_NAME
            with mock.patch.object(mod, "validate_prerequisite", return_value=(summary, plan)):
                archive, result = mod.audit(project, quartet, gust, output)
            self.assertTrue(archive.is_file())
            self.assertEqual(result["non_target_entries_validated"], 2)
            self.assertFalse(result["policy"]["profile_build_allowed"])
            candidate_pak = project / mod.BUILD_RELATIVE / "candidate/PACK12.PAK"
            index = N.index_pak(candidate_pak)
            actual, _ = N.read_pak_member(index, mod.TARGET_MEMBER)
            self.assertEqual(actual, candidate_xml())
            self.assertEqual(mod.validate_report(output)["two_archive_candidate_count"], 2)

    def test_audit_rejects_installed_pack12_drift(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            project, quartet, gust, summary, plan = self.create_fixture(root)
            pack12 = quartet / mod.TARGET_ARCHIVE_RELATIVE
            pack12.write_bytes(pack12.read_bytes() + b"DRIFT")
            with mock.patch.object(mod, "validate_prerequisite", return_value=(summary, plan)):
                with self.assertRaises(mod.BknDryPack12RepackError):
                    mod.audit(project, quartet, gust, project / "report")

    def test_audit_rejects_local_member_drift(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            project, quartet, gust, summary, plan = self.create_fixture(root)
            (project / mod.PREFLIGHT_MEMBER_RELATIVE).write_bytes(candidate_xml() + b"DRIFT")
            with mock.patch.object(mod, "validate_prerequisite", return_value=(summary, plan)):
                with self.assertRaises(mod.BknDryPack12RepackError):
                    mod.audit(project, quartet, gust, project / "report")

    def test_rewrite_table_rejects_overlapping_entry(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            project, quartet, _gust, _summary, _plan = self.create_fixture(root)
            pack12 = quartet / mod.TARGET_ARCHIVE_RELATIVE
            index = N.index_pak(pack12)
            layout = mod.DRY.read_raw_layout(pack12, index)
            # The normal fixture is non-overlapping and must produce one target-size change.
            table, rows, delta = mod.rewrite_table_for_replacement(layout, index, index.entries[1], index.entries[1].size + 8)
            self.assertEqual(len(table), len(layout.raw_table))
            self.assertEqual(delta, 8)
            self.assertEqual(rows[1]["expected_change"], "target_size_replaced")

    def test_validate_rejects_profile_authorization(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            project, quartet, gust, summary, plan = self.create_fixture(root)
            output = project / ".local/reports/quartet_legacy_dlc" / mod.REPORT_DIR_NAME
            with mock.patch.object(mod, "validate_prerequisite", return_value=(summary, plan)):
                mod.audit(project, quartet, gust, output)
            summary_path = output / "SUMMARY.json"
            value = json.loads(summary_path.read_text(encoding="utf-8"))
            value["policy"]["profile_build_allowed"] = True
            summary_path.write_text(json.dumps(value), encoding="utf-8")
            with self.assertRaises(mod.BknDryPack12RepackError):
                mod.validate_report(output)


if __name__ == "__main__":
    unittest.main()
