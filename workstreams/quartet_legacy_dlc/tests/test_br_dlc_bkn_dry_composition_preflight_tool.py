from __future__ import annotations

import json
import struct
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import sys

HERE = Path(__file__).resolve().parent
WORKSTREAM = HERE.parent
if str(WORKSTREAM) not in sys.path:
    sys.path.insert(0, str(WORKSTREAM))

import br_dlc_bkn_dry_composition_preflight_tool as mod
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
        key = bytes(((index + 17 + n) % 251) + 1 for n in range(key_size))
        effective = N.effective_entry_key(key, master)
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
    path.write_bytes(N.PAK_HEADER.pack(0x20000, len(entries), N.PAK_HEADER.size, 13) + table + payload)


def charabase_bytes() -> bytes:
    return (
        '<?xml version="1.0" encoding="SHIFT-JIS"?>\r\n'
        '<Root>\r\n'
        '\t<CharaBase BaseTag="PC00_DLC_BKN" Directory="Character" Model="PC00/PC00_Scl" FileHead="PC00" defaultTexture="PC00/PC00_Scl" Motion1="KEEP" Facial="KEEP2"/>\r\n'
        '\t<CharaBase BaseTag="PC00_DLC_BKN_W" Directory="Character" Model="PC00/PC00_Scl_W" FileHead="PC00" defaultTexture="PC00/PC00_Scl_W"/>\r\n'
        '\t<CharaBase BaseTag="PC00_SCL" Directory="Character" Model="PC00/PC00_Scl" defaultTexture="PC00/PC00_Scl"/>\r\n'
        '</Root>\r\n'
    ).encode("cp932")


def prereq(dry_sha: str) -> dict:
    return {
        "dry": {"status": "local_asset_only_pack10_02_candidate_built_not_installed", "candidate_sha256": dry_sha},
        "activation": {"status": "bkn_table_stub_proven_activation_and_ui_still_fail_closed"},
        "ui": {"status": "bkn_ui_numeric_index_route_not_supported_by_local_schema", "schema_supported_control_candidates": 0},
        "patch": {
            "record_key": "CharaBase:BaseTag=PC00_DLC_BKN",
            "expected_old_values": {"Model": "PC00/PC00_Scl", "defaultTexture": "PC00/PC00_Scl"},
            "new_values": {"Model": "PC00/PC00_DLC_Bkn", "defaultTexture": "PC00/PC00_DLC_Bkn"},
        },
    }


class DryCompositionPreflightTest(unittest.TestCase):
    def test_patch_changes_only_dry_model_and_texture(self) -> None:
        raw = charabase_bytes()
        candidate, detail = mod.patch_dry_record(
            raw,
            {"Model": "PC00/PC00_Scl", "defaultTexture": "PC00/PC00_Scl"},
            {"Model": "PC00/PC00_DLC_Bkn", "defaultTexture": "PC00/PC00_DLC_Bkn"},
        )
        self.assertEqual(set(detail["changed"]), {"Model", "defaultTexture"})
        self.assertEqual(mod.record_attrs(candidate, "PC00_DLC_BKN")["Motion1"], "KEEP")
        self.assertEqual(mod.record_attrs(candidate, "PC00_DLC_BKN")["Facial"], "KEEP2")
        self.assertEqual(mod.record_attrs(candidate, "PC00_DLC_BKN_W")["Model"], "PC00/PC00_Scl_W")

    def test_audit_builds_local_preflight_without_repacking(self) -> None:
        with tempfile.TemporaryDirectory() as temp_name:
            base = Path(temp_name)
            project = base / "project"
            quartet = base / "quartet"
            project.mkdir()
            raw = charabase_bytes()
            workspace = project / mod.WORKSPACE_TABLE_RELATIVE
            workspace.parent.mkdir(parents=True, exist_ok=True)
            workspace.write_bytes(raw)
            dry_pak = project / mod.DRY_PAK_RELATIVE
            dry_pak.parent.mkdir(parents=True, exist_ok=True)
            dry_pak.write_bytes(b"dry-pack-candidate")
            pack12 = quartet / mod.TARGET_ARCHIVE_RELATIVE
            make_pak(pack12, [("\\saves\\b1\\chara\\charabase.xml", raw), ("\\other.bin", b"other")])
            output = project / ".local/reports/quartet_legacy_dlc" / mod.REPORT_DIR_NAME
            with mock.patch.object(mod, "validate_prerequisites", return_value=prereq(mod.sha256_file(dry_pak))):
                archive, summary = mod.audit(project, quartet, output)
            self.assertTrue(archive.is_file())
            self.assertFalse(summary["policy"]["profile_build_allowed"])
            self.assertFalse(summary["policy"]["target_pak_repacked"])
            self.assertTrue(summary["policy"]["local_pack12_repack_test_allowed"])
            candidate = project / mod.BUILD_RELATIVE / "candidate" / mod.TARGET_MEMBER
            self.assertTrue(candidate.is_file())
            self.assertEqual(mod.record_attrs(candidate.read_bytes(), mod.DRY_TAG)["Model"], "PC00/PC00_DLC_Bkn")
            validated = mod.validate_report(output)
            self.assertEqual(validated["schema_supported_ui_candidates"], 0)

    def test_audit_rejects_installed_member_drift(self) -> None:
        with tempfile.TemporaryDirectory() as temp_name:
            base = Path(temp_name)
            project = base / "project"
            quartet = base / "quartet"
            project.mkdir()
            raw = charabase_bytes()
            workspace = project / mod.WORKSPACE_TABLE_RELATIVE
            workspace.parent.mkdir(parents=True, exist_ok=True)
            workspace.write_bytes(raw)
            dry_pak = project / mod.DRY_PAK_RELATIVE
            dry_pak.parent.mkdir(parents=True, exist_ok=True)
            dry_pak.write_bytes(b"dry-pack-candidate")
            changed = raw.replace(b'Facial="KEEP2"', b'Facial="DRIFT"')
            make_pak(quartet / mod.TARGET_ARCHIVE_RELATIVE, [("\\saves\\b1\\chara\\charabase.xml", changed)])
            with mock.patch.object(mod, "validate_prerequisites", return_value=prereq(mod.sha256_file(dry_pak))):
                with self.assertRaises(mod.BknDryCompositionPreflightError):
                    mod.audit(project, quartet, project / "report")

    def test_validate_rejects_profile_authorization(self) -> None:
        with tempfile.TemporaryDirectory() as temp_name:
            base = Path(temp_name)
            project = base / "project"
            quartet = base / "quartet"
            project.mkdir()
            raw = charabase_bytes()
            workspace = project / mod.WORKSPACE_TABLE_RELATIVE
            workspace.parent.mkdir(parents=True, exist_ok=True)
            workspace.write_bytes(raw)
            dry_pak = project / mod.DRY_PAK_RELATIVE
            dry_pak.parent.mkdir(parents=True, exist_ok=True)
            dry_pak.write_bytes(b"dry-pack-candidate")
            make_pak(quartet / mod.TARGET_ARCHIVE_RELATIVE, [("\\saves\\b1\\chara\\charabase.xml", raw)])
            output = project / ".local/reports/quartet_legacy_dlc" / mod.REPORT_DIR_NAME
            with mock.patch.object(mod, "validate_prerequisites", return_value=prereq(mod.sha256_file(dry_pak))):
                mod.audit(project, quartet, output)
            summary_path = output / "SUMMARY.json"
            summary = json.loads(summary_path.read_text(encoding="utf-8"))
            summary["policy"]["profile_build_allowed"] = True
            summary_path.write_text(json.dumps(summary), encoding="utf-8")
            with self.assertRaises(mod.BknDryCompositionPreflightError):
                mod.validate_report(output)


if __name__ == "__main__":
    unittest.main()
