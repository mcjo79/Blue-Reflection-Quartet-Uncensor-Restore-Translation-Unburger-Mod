from __future__ import annotations

import csv
import hashlib
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

import br_dlc_br1_official_source_refresh_tool as mod
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


def write_tsv(path: Path, fields: list[str], rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def read_tsv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


class OfficialSourceRefreshTest(unittest.TestCase):
    def prepare(self, root: Path) -> tuple[Path, Path, Path, Path, Path]:
        project = root / "project"
        reports = project / ".local/reports/quartet_legacy_dlc"
        provenance = reports / "br1_source_provenance_evidence"
        transaction = reports / "bkn_dry_transaction_contract_evidence"
        br1 = root / "br1"
        provenance.mkdir(parents=True)
        transaction.mkdir(parents=True)

        members: list[tuple[str, bytes]] = []
        changed_rows: list[dict[str, str]] = []
        plan_rows: list[dict[str, str]] = []
        for basename in sorted(mod.EXPECTED_REQUIRED_MEMBERS):
            pc = basename.split("_")[0]
            member = f"data/x64/character/{pc}/{basename}"
            payload = ("official:" + basename).encode("ascii")
            members.append((member, payload))
        make_pak(br1 / "DATA/PACK00_02.PAK", members)
        index = N.index_pak(br1 / "DATA/PACK00_02.PAK")

        dependencies = (
            ".local/reports/quartet_legacy_dlc/technical_registry_evidence/DLC_TECHNICAL_MEMBER_BINDINGS.tsv;"
            ".local/reports/quartet_legacy_dlc/nonscenario_inventory_evidence/DLC_NONSCRIPT_MEMBER_BINDINGS.tsv;"
            ".local/reports/quartet_legacy_dlc/external_dependency_closure_evidence/DLC_EXTERNAL_TEXTURE_BINDINGS.tsv;"
            ".local/reports/quartet_legacy_dlc/exact_closure_evidence/DLC_EXACT_ROLE_CLOSURE.tsv"
        )
        old_by_member: dict[str, str] = {}
        official_by_member: dict[str, str] = {}
        for member, payload in members:
            entry = index.by_name[member.casefold()][0]
            old_hash = hashlib.sha256(("modified:" + Path(member).name).encode("ascii")).hexdigest()
            official_hash = hashlib.sha256(payload).hexdigest()
            old_by_member[member] = old_hash
            official_by_member[member] = official_hash
            changed_rows.append({
                "pair_id": "PACK00_02",
                "member_name": member,
                "status": "changed",
                "official_size": str(entry.size),
                "official_data_offset": str(entry.data_offset),
                "official_payload_sha256": official_hash,
                "modified_payload_sha256": old_hash,
                "size_changed": "false",
                "data_offset_changed": "false",
            })
            plan_rows.append({
                "pair_id": "PACK00_02",
                "member_name": member,
                "priority": "required",
                "dependent_metadata_files": dependencies,
            })

        write_tsv(provenance / "DLC_BR1_SELECTIVE_REBUILD_PLAN.tsv", list(plan_rows[0]), plan_rows)
        write_tsv(provenance / "DLC_BR1_CHANGED_MEMBER_CLASSIFICATION.tsv", list(changed_rows[0]), changed_rows)
        write_tsv(provenance / "DLC_BR1_SOURCE_ARCHIVE_PROVENANCE.tsv", [
            "pair_id", "official_size", "official_format", "official_entry_count"
        ], [{
            "pair_id": "PACK00_02",
            "official_size": str((br1 / "DATA/PACK00_02.PAK").stat().st_size),
            "official_format": index.format_name,
            "official_entry_count": str(len(index.entries)),
        }])
        dry_rows = [
            {
                "member_name": "data/x64/character/pc00/pc00_dlc_bkn.elixir.gz",
                "current_payload_affected": "false",
                "comparison_status": "identical",
            },
            {
                "member_name": "data/x64/character/pc00/pc00_dlc_bkn.g1t",
                "current_payload_affected": "false",
                "comparison_status": "identical",
            },
        ]
        write_tsv(provenance / "DLC_BR1_CURRENT_DRY_BKN_IMPACT.tsv", list(dry_rows[0]), dry_rows)

        technical_rows = []
        nonscript_rows = []
        external_rows = []
        closure_rows = []
        for i, (member, _payload) in enumerate(members):
            old_hash = old_by_member[member]
            size = str(index.by_name[member.casefold()][0].size)
            technical_rows.append({
                "registry_id": f"registry_{i}", "normalized_path": member,
                "source_size": size, "source_sha256": old_hash, "source_archive": "DATA/PACK00_02.PAK",
            })
            nonscript_rows.append({
                "content_id": f"content_{i}", "normalized_path": member,
                "source_size": size, "source_sha256": old_hash, "source_archive": "DATA/PACK00_02.PAK",
            })
            external_rows.append({
                "closure_id": f"closure_{i}", "normalized_path": member,
                "source_size": size, "source_sha256": old_hash, "source_archive": "DATA/PACK00_02.PAK",
            })
            closure_rows.append({"content_id": f"content_{i}", "evidence": member})
        write_tsv(reports / mod.BINDING_SPECS[0][0], list(technical_rows[0]), technical_rows)
        write_tsv(reports / mod.BINDING_SPECS[1][0], list(nonscript_rows[0]), nonscript_rows)
        write_tsv(reports / mod.BINDING_SPECS[2][0], list(external_rows[0]), external_rows)
        write_tsv(reports / "exact_closure_evidence/DLC_EXACT_ROLE_CLOSURE.tsv", list(closure_rows[0]), closure_rows)
        return project, br1, reports, provenance, transaction

    def test_full_refresh_builds_39_official_binding_replacements(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            project, br1, reports, provenance, transaction = self.prepare(Path(name))
            output = reports / mod.REPORT_DIR_NAME
            tx_summary = {"policy": {"core_integration_request_ready": True}, "request_file": "DLC_BKN_DRY_CORE_TARGET_REQUEST.json"}
            with mock.patch.object(mod.PROV, "validate_report", return_value={}), \
                 mock.patch.object(mod.TX, "validate_report", return_value=tx_summary):
                archive, summary = mod.refresh(project, br1, reports, provenance, transaction, output)
            self.assertTrue(archive.is_file())
            self.assertEqual(summary["official_changed_members_verified"], 13)
            self.assertEqual(summary["binding_rows_superseded"], 39)
            self.assertTrue(summary["dry_bkn_transaction_contract_still_valid"])
            replacement = read_tsv(output / "DLC_BR1_OFFICIAL_TECHNICAL_MEMBER_BINDINGS.tsv")
            self.assertEqual(len(replacement), 13)
            verification = read_tsv(output / "DLC_BR1_OFFICIAL_CHANGED_MEMBER_VERIFICATION.tsv")
            official = {row["member_name"]: row["official_payload_sha256"] for row in verification}
            self.assertTrue(all(row["source_sha256"] == official[row["normalized_path"]] for row in replacement))
            validated = mod.validate_report(output)
            self.assertFalse(validated["policy"]["game_modified"])

    def test_binding_refresh_rejects_row_without_modified_hash(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            project, br1, reports, provenance, transaction = self.prepare(Path(name))
            path = reports / mod.BINDING_SPECS[0][0]
            rows = read_tsv(path)
            rows[0]["source_sha256"] = "0" * 64
            write_tsv(path, list(rows[0]), rows)
            required = mod._required_changed_rows(provenance)
            _verified, provenance_by_name = mod.verify_official_members(br1, provenance, required)
            with self.assertRaises(mod.OfficialSourceRefreshError):
                mod.build_binding_replacements(reports, reports / "out", provenance_by_name)

    def test_official_member_verification_rejects_changed_payload(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            _project, br1, _reports, provenance, _transaction = self.prepare(Path(name))
            archive = br1 / "DATA/PACK00_02.PAK"
            data = bytearray(archive.read_bytes())
            data[-1] ^= 0x01
            archive.write_bytes(data)
            required = mod._required_changed_rows(provenance)
            with self.assertRaises(mod.OfficialSourceRefreshError):
                mod.verify_official_members(br1, provenance, required)

    def test_validate_rejects_profile_authorization(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            project, br1, reports, provenance, transaction = self.prepare(Path(name))
            output = reports / mod.REPORT_DIR_NAME
            tx_summary = {"policy": {"core_integration_request_ready": True}, "request_file": "request.json"}
            with mock.patch.object(mod.PROV, "validate_report", return_value={}), \
                 mock.patch.object(mod.TX, "validate_report", return_value=tx_summary):
                mod.refresh(project, br1, reports, provenance, transaction, output)
            summary_path = output / "SUMMARY.json"
            summary = json.loads(summary_path.read_text(encoding="utf-8"))
            summary["policy"]["profile_build_allowed"] = True
            summary_path.write_text(json.dumps(summary), encoding="utf-8")
            with self.assertRaises(mod.OfficialSourceRefreshError):
                mod.validate_report(output)


if __name__ == "__main__":
    unittest.main()
