from __future__ import annotations

import csv
import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import sys

HERE = Path(__file__).resolve().parent
WORKSTREAM = HERE.parent
if str(WORKSTREAM) not in sys.path:
    sys.path.insert(0, str(WORKSTREAM))

import br_dlc_br1_source_provenance_tool as mod
import br_dlc_nested_container_tool as N


def make_pak(path: Path, entries: list[tuple[str, bytes]]) -> None:
    specs = {name: (entry_struct, key_size, a22) for name, entry_struct, key_size, a22 in N.PAK_FORMATS}
    entry_struct, key_size, a22 = specs["a17_32"]
    table = bytearray()
    payload = bytearray()
    for name, data in entries:
        raw_name = name.encode("ascii") + b"\0" * (128 - len(name.encode("ascii")))
        key = b"\0" * key_size
        if a22:
            table.extend(entry_struct.pack(raw_name, len(data), key, 0, len(payload), 0))
        else:
            table.extend(entry_struct.pack(raw_name, len(data), key, len(payload), 0))
        payload.extend(data)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(N.PAK_HEADER.pack(0x20000, len(entries), N.PAK_HEADER.size, 0) + table + payload)


def read_tsv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


class Br1SourceProvenanceTest(unittest.TestCase):
    def prepare(self, root: Path) -> tuple[Path, Path]:
        project = root / "project"
        br1 = root / "br1"
        data = br1 / "DATA"
        project.mkdir()
        common = [
            ("data/x64/character/pc00/pc00_dlc_bkn.elixir.gz", b"same-parent"),
            ("data/x64/character/pc00/pc00_dlc_bkn.g1t", b"same-dry-texture"),
        ]
        make_pak(data / "PACK00_02.PAK_", common + [
            ("data/x64/character/pc03/pc03_dlc_bkn_w.g1t", b"modified-wet"),
            ("data/x64/character/pc03/pc03_scl.g1t", b"modified-school"),
        ])
        make_pak(data / "PACK00_02.PAK", common + [
            ("data/x64/character/pc03/pc03_dlc_bkn_w.g1t", b"official-wet"),
            ("data/x64/character/pc03/pc03_scl.g1t", b"official-school"),
        ])
        make_pak(data / "PACK00_04_1.PAK_", [
            ("data/ui/22_costume_change.kscl", b"old-ui"),
            ("data/ui/removed.kslt", b"removed"),
        ])
        make_pak(data / "PACK00_04_1.PAK", [
            ("data/ui/22_costume_change.kscl", b"official-ui"),
            ("data/ui/added.kslt", b"added"),
        ])
        make_pak(data / "PACK00_04_2.PAK_", [("data/a.bin", b"same")])
        make_pak(data / "PACK00_04_2.PAK", [("data/a.bin", b"same")])
        make_pak(data / "PACK00_04_3.PAK_", [("data/system/unlock.xml", b"old")])
        make_pak(data / "PACK00_04_3.PAK", [("data/system/unlock.xml", b"new")])

        old_sha256 = mod.sha256_file(data / "PACK00_02.PAK_")
        report = project / ".local/reports/quartet_legacy_dlc/old_report"
        report.mkdir(parents=True)
        (report / "metadata.tsv").write_text(
            "archive\tmember\tsha\n"
            f"DATA/PACK00_02.PAK\tdata/x64/character/pc03/pc03_dlc_bkn_w.g1t\t{old_sha256}\n",
            encoding="utf-8",
        )
        payload = project / ".local/build/quartet_legacy_dlc/probe/pc03_dlc_bkn_w.g1t"
        payload.parent.mkdir(parents=True)
        payload.write_bytes(b"modified-wet")
        return project, br1

    @staticmethod
    def fake_digests(path: Path) -> tuple[str, str]:
        sha256 = mod.sha256_file(path)
        if path.name == "PACK00_02.PAK_":
            return mod.EXPECTED_PACK00_02_MODIFIED_SHA1, sha256
        if path.name == "PACK00_02.PAK":
            return mod.EXPECTED_PACK00_02_OFFICIAL_SHA1, sha256
        return mod.hash_file(path, "sha1"), sha256


    def test_member_level_audit_and_selective_rebuild(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            project, br1 = self.prepare(Path(name))
            output = project / ".local/reports/quartet_legacy_dlc" / mod.REPORT_DIR_NAME
            with mock.patch.object(mod, "hash_file_digests", side_effect=self.fake_digests):
                archive, summary = mod.audit(project, br1, output)
            self.assertTrue(archive.is_file())
            self.assertEqual(summary["archive_pair_count"], 4)
            self.assertFalse(summary["current_dry_bkn_payload_affected"])
            changed = read_tsv(output / "DLC_BR1_CHANGED_MEMBER_CLASSIFICATION.tsv")
            names = {row["member_name"] for row in changed}
            self.assertIn("data/x64/character/pc03/pc03_dlc_bkn_w.g1t", names)
            self.assertIn("data/ui/22_costume_change.kscl", names)
            self.assertIn("data/ui/removed.kslt", names)
            self.assertIn("data/ui/added.kslt", names)
            payloads = read_tsv(output / "DLC_BR1_EXTRACTED_PAYLOAD_PROVENANCE.tsv")
            self.assertTrue(any(row["provenance"] == "matches_untrusted_modified_member" for row in payloads))
            rebuild = read_tsv(output / "DLC_BR1_SELECTIVE_REBUILD_PLAN.tsv")
            wet = next(row for row in rebuild if row["member_name"].endswith("pc03_dlc_bkn_w.g1t"))
            self.assertEqual(wet["priority"], "required")
            validated = mod.validate_report(output)
            self.assertFalse(validated["policy"]["game_modified"])

    def test_compare_pair_reports_identical_offsets_and_changed_payload(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            modified = root / "old.pak"
            official = root / "new.pak"
            make_pak(modified, [("data/a.g1t", b"old")])
            make_pak(official, [("data/a.g1t", b"new")])
            result = mod.compare_pair("PACK00_04_1", modified, official)
            self.assertEqual(len(result.changed_rows), 1)
            row = result.changed_rows[0]
            self.assertEqual(row["status"], "changed")
            self.assertFalse(row["size_changed"])
            self.assertFalse(row["data_offset_changed"])
            self.assertNotEqual(row["modified_payload_sha256"], row["official_payload_sha256"])

    def test_validate_rejects_canonical_underscore_policy(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            project, br1 = self.prepare(Path(name))
            output = project / ".local/reports/quartet_legacy_dlc" / mod.REPORT_DIR_NAME
            with mock.patch.object(mod, "hash_file_digests", side_effect=self.fake_digests):
                mod.audit(project, br1, output)
            summary_path = output / "SUMMARY.json"
            summary = json.loads(summary_path.read_text(encoding="utf-8"))
            summary["policy"]["underscore_source_canonical_allowed"] = True
            summary_path.write_text(json.dumps(summary), encoding="utf-8")
            with self.assertRaises(mod.Br1SourceProvenanceError):
                mod.validate_report(output)


if __name__ == "__main__":
    unittest.main()
