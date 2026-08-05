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

import br_dlc_br1_canonical_source_tool as mod
import br_dlc_nested_container_tool as N


def make_pak(path: Path, entries: list[tuple[str, bytes]]) -> None:
    specs = {name: (entry_struct, key_size, a22) for name, entry_struct, key_size, a22 in N.PAK_FORMATS}
    entry_struct, key_size, a22 = specs["a17_32"]
    table = bytearray()
    payload = bytearray()
    for name, data in entries:
        encoded = name.encode("ascii")
        raw_name = encoded + b"\0" * (128 - len(encoded))
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


class CanonicalSourceContractTest(unittest.TestCase):
    def prepare(self, root: Path) -> tuple[Path, Path, Path, Path, dict[str, bytes], dict[str, str]]:
        project = root / "project"
        workstream = project / "workstreams/quartet_legacy_dlc"
        reports = project / ".local/reports/quartet_legacy_dlc"
        refresh = reports / "br1_official_source_refresh_evidence"
        br1 = root / "br1"
        workstream.mkdir(parents=True)
        refresh.mkdir(parents=True)
        (workstream / "61_collect_br1_official_source_refresh_evidence.sh").write_text(
            "python3 tool.py --archive DATA/PACK00_02.PAK\n", encoding="utf-8"
        )
        (workstream / "64_collect_br1_canonical_source_contract_evidence.sh").write_text(
            "python3 canonical.py --archive DATA/PACK00_02.PAK\n", encoding="utf-8"
        )

        payloads: dict[str, bytes] = {}
        old_hashes: dict[str, str] = {}
        entries: list[tuple[str, bytes]] = []
        for basename in sorted(mod.PROV.KNOWN_PACK00_02_DLC_CHANGED_BASENAMES):
            pc = basename.split("_")[0]
            member = f"data/x64/character/{pc}/{basename}"
            payload = ("official:" + basename).encode("ascii")
            payloads[member] = payload
            old_hashes[member] = hashlib.sha256(("modified:" + basename).encode("ascii")).hexdigest()
            entries.append((member, payload))
        make_pak(br1 / mod.OFFICIAL_ARCHIVE, entries)
        index = N.index_pak(br1 / mod.OFFICIAL_ARCHIVE)

        verification: list[dict[str, str]] = []
        for member, payload in entries:
            entry = index.by_name[member.casefold()][0]
            verification.append({
                "member_name": member,
                "content_basename": Path(member).name,
                "official_archive": mod.OFFICIAL_ARCHIVE,
                "official_archive_designation": "canonical_official_no_trailing_underscore",
                "official_entry_index": str(entry.index),
                "official_size": str(entry.size),
                "official_data_offset": str(entry.data_offset),
                "modified_payload_sha256": old_hashes[member],
                "official_payload_sha256": hashlib.sha256(payload).hexdigest(),
                "payload_hash_changed": "true",
                "size_unchanged": "true",
                "data_offset_unchanged": "true",
                "verification_status": "official_member_hash_and_layout_verified",
                "raw_payload_exported": "false",
            })
        write_tsv(refresh / "DLC_BR1_OFFICIAL_CHANGED_MEMBER_VERIFICATION.tsv", list(verification[0]), verification)

        supersession: list[dict[str, str]] = []
        for spec in mod.BINDING_SPECS:
            old_rows: list[dict[str, str]] = []
            overlay_rows: list[dict[str, str]] = []
            for i, (member, payload) in enumerate(entries):
                identity = f"{spec['family']}_{i}"
                old = {
                    spec["identity_field"]: identity,
                    spec["path_field"]: member,
                    "source_archive": mod.OFFICIAL_ARCHIVE,
                    "source_size": str(len(payload)),
                    "source_sha256": old_hashes[member],
                    "compatibility_status": "missing_portable_from_br1",
                }
                overlay = dict(old)
                overlay["source_sha256"] = hashlib.sha256(payload).hexdigest()
                old_rows.append(old)
                # Real source reports group multiple dry/wet members under one
                # registry/content/closure identity.  The canonical resolver
                # must therefore join by identity plus normalized member path.
                companion = dict(old)
                companion[spec["path_field"]] = member.replace("_w.g1t", ".g1t")
                companion["source_sha256"] = hashlib.sha256(
                    ("unchanged-companion:" + companion[spec["path_field"]]).encode("ascii")
                ).hexdigest()
                old_rows.append(companion)
                overlay_rows.append(overlay)
                supersession.append({
                    "source_report": spec["source_report"],
                    "source_row_identity": identity,
                    "member_name": member,
                    "old_modified_source_sha256": old["source_sha256"],
                    "replacement_official_source_sha256": overlay["source_sha256"],
                    "replacement_report": spec["overlay_report"],
                    "supersession_status": "old_hash_row_superseded_by_official_overlay",
                })
            write_tsv(reports / spec["source_report"], list(old_rows[0]), old_rows)
            write_tsv(refresh / spec["overlay_report"], list(overlay_rows[0]), overlay_rows)
        write_tsv(refresh / "DLC_BR1_OFFICIAL_BINDING_SUPERSESSION.tsv", list(supersession[0]), supersession)

        dry = [
            {
                "item_type": "dry_bkn_source_payload",
                "item_id": "data/x64/character/pc00/pc00_dlc_bkn.elixir.gz",
                "provenance_status": "identical_between_modified_and_official_source",
                "current_candidate_valid": "true",
                "required_action": "retain_current_dry_candidate_payload",
            },
            {
                "item_type": "dry_bkn_source_payload",
                "item_id": "data/x64/character/pc00/pc00_dlc_bkn.g1t",
                "provenance_status": "identical_between_modified_and_official_source",
                "current_candidate_valid": "true",
                "required_action": "retain_current_dry_candidate_payload",
            },
            {
                "item_type": "two_archive_transaction_contract",
                "item_id": "DLC_BKN_DRY_CORE_TARGET_REQUEST.json",
                "provenance_status": "candidate_inputs_unaffected_and_contract_report_validated",
                "current_candidate_valid": "true",
                "required_action": "retain_request_for_later_explicit_core_integration",
            },
        ]
        write_tsv(refresh / "DLC_BR1_DRY_BKN_TRANSACTION_VALIDITY.tsv", list(dry[0]), dry)
        return project, br1, reports, refresh, payloads, old_hashes

    def patched_hash(self):
        original = mod.hash_file

        def helper(path: Path, algorithm: str = "sha256") -> str:
            if algorithm == "sha1":
                return mod.OFFICIAL_ARCHIVE_SHA1
            return original(path, algorithm)

        return mock.patch.object(mod, "hash_file", side_effect=helper)

    def test_full_contract_resolves_13_members_and_39_rows_without_underscore_input(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            project, br1, reports, refresh, _payloads, _old = self.prepare(Path(name))
            output = reports / mod.REPORT_DIR_NAME
            refresh_summary = {"policy": {"official_binding_overlay_required_for_future_consumers": True}}
            with mock.patch.object(mod.REFRESH, "validate_report", return_value=refresh_summary), self.patched_hash():
                archive, summary = mod.build_contract(project, br1, reports, refresh, output)
            self.assertTrue(archive.is_file())
            self.assertEqual(summary["canonical_registry_members"], 13)
            self.assertEqual(summary["official_overlay_rows_resolved"], 39)
            self.assertFalse(summary["underscore_files_required_for_future_workflow"])
            self.assertEqual(len(read_tsv(output / "DLC_BR1_CANONICAL_SOURCE_REGISTRY.tsv")), 13)
            self.assertEqual(len(read_tsv(output / "DLC_BR1_OFFICIAL_OVERLAY_RESOLUTION.tsv")), 39)
            validated = mod.validate_report(output)
            self.assertTrue(validated["policy"]["canonical_source_contract_ready"])


    def test_duplicate_exact_composite_source_identity_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            _project, _br1, reports, refresh, _payloads, _old = self.prepare(Path(name))
            spec = mod.BINDING_SPECS[0]
            path = reports / spec["source_report"]
            rows = read_tsv(path)
            rows.append(dict(rows[0]))
            write_tsv(path, list(rows[0]), rows)
            with self.assertRaises(mod.CanonicalSourceContractError):
                mod.build_overlay_resolution(reports, refresh)

    def test_same_group_identity_with_distinct_member_paths_is_valid(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            _project, _br1, reports, refresh, _payloads, _old = self.prepare(Path(name))
            rows = mod.build_overlay_resolution(reports, refresh)
            self.assertEqual(len(rows), 39)
            self.assertEqual(len({row["composite_resolver_key"] for row in rows}), 39)

    def test_matching_old_local_payload_is_quarantined_and_never_selected(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            project, br1, reports, refresh, _payloads, old_hashes = self.prepare(Path(name))
            member = sorted(old_hashes)[0]
            local = project / ".local/build/quartet_legacy_dlc/cache" / Path(member).name
            local.parent.mkdir(parents=True)
            local.write_bytes(("modified:" + Path(member).name).encode("ascii"))
            output = reports / mod.REPORT_DIR_NAME
            refresh_summary = {"policy": {"official_binding_overlay_required_for_future_consumers": True}}
            with mock.patch.object(mod.REFRESH, "validate_report", return_value=refresh_summary), self.patched_hash():
                mod.build_contract(project, br1, reports, refresh, output)
            rows = read_tsv(output / "DLC_BR1_LOCAL_WET_DLC_PAYLOAD_PROVENANCE.tsv")
            self.assertEqual(rows[0]["classification"], "matches_untrusted_modified_candidate")
            self.assertEqual(rows[0]["selected_for_future_use"], "false")

    def test_active_stage_with_underscore_dependency_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            project, _br1, _reports, _refresh, _payloads, _old = self.prepare(Path(name))
            bad = project / "workstreams/quartet_legacy_dlc/64_bad.sh"
            bad.write_text("read DATA/PACK00_02.PAK_\n", encoding="utf-8")
            with self.assertRaises(mod.CanonicalSourceContractError):
                mod.audit_operational_underscore_dependencies(project)

    def test_official_payload_drift_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            _project, br1, _reports, refresh, _payloads, _old = self.prepare(Path(name))
            archive = br1 / mod.OFFICIAL_ARCHIVE
            data = bytearray(archive.read_bytes())
            data[-1] ^= 1
            archive.write_bytes(data)
            with self.patched_hash(), self.assertRaises(mod.CanonicalSourceContractError):
                mod.verify_canonical_archive(br1, refresh)

    def test_validate_rejects_profile_authorization(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            project, br1, reports, refresh, _payloads, _old = self.prepare(Path(name))
            output = reports / mod.REPORT_DIR_NAME
            refresh_summary = {"policy": {"official_binding_overlay_required_for_future_consumers": True}}
            with mock.patch.object(mod.REFRESH, "validate_report", return_value=refresh_summary), self.patched_hash():
                mod.build_contract(project, br1, reports, refresh, output)
            summary_path = output / "SUMMARY.json"
            summary = json.loads(summary_path.read_text(encoding="utf-8"))
            summary["policy"]["profile_build_allowed"] = True
            summary_path.write_text(json.dumps(summary), encoding="utf-8")
            with self.assertRaises(mod.CanonicalSourceContractError):
                mod.validate_report(output)


if __name__ == "__main__":
    unittest.main()
