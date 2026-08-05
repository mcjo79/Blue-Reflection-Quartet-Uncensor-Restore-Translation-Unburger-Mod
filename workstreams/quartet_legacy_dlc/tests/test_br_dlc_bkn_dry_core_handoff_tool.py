from __future__ import annotations

import csv
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parents[1]
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import br_dlc_bkn_dry_core_handoff_tool as mod


def write_json(path: Path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def write_tsv(path: Path, fields, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


class CoreHandoffTest(unittest.TestCase):
    def prepare(self, root: Path):
        tx = root / "tx"
        canon = root / "canon"
        out = root / "out"
        tx.mkdir(); canon.mkdir()
        request = {
            "type": "br_quartet_legacy_dlc_core_transaction_request",
            "target_id": "blue_reflection_quartet",
            "content_id": "costume_pc00_bkn",
            "core_contract": {
                "single_journal_required": True,
                "backup_every_existing_target": True,
                "hash_gate_prepare_and_commit": True,
                "reverse_order_guarded_rollback_required": True,
            },
            "authorization": {
                "core_integration_request_ready": True,
                "real_transaction_prepare_enabled": False,
                "commit_enabled": False,
                "candidate_installed": False,
                "profile_build_allowed": False,
                "profile_registered": False,
                "runtime_validated": False,
                "wet_variant_included": False,
            },
            "transaction_files": [
                {
                    "relative_path": "Data/PACK10_02.PAK",
                    "role": "dry_parent_and_external_texture",
                    "baseline_size": 100,
                    "baseline_sha256": "1" * 64,
                    "candidate_relative_path": ".local/build/PACK10_02.PAK",
                    "candidate_size": 120,
                    "candidate_sha256": "2" * 64,
                },
                {
                    "relative_path": "Data/PACK12.PAK",
                    "role": "dry_charabase_fallback_removal",
                    "baseline_size": 30,
                    "baseline_sha256": "3" * 64,
                    "candidate_relative_path": ".local/build/PACK12.PAK",
                    "candidate_size": 38,
                    "candidate_sha256": "4" * 64,
                },
            ],
        }
        write_json(tx / "DLC_BKN_DRY_CORE_TARGET_REQUEST.json", request)
        contract = {
            "resolver_id": "br1_official_source_overlay_v1",
            "canonical_archive": "DATA/PACK00_02.PAK",
            "canonical_archive_sha1": "f" * 40,
            "rules": {
                "underscore_archives_required": False,
                "old_modified_hash_may_be_selected": False,
                "future_payload_extraction_requires_registry_hash_gate": True,
            },
        }
        write_json(canon / "DLC_BR1_CANONICAL_SOURCE_CONSUMER_CONTRACT.json", contract)
        tx_summary = {
            "status": "two_archive_transaction_contract_ready_core_integration_required_not_prepared_not_installed",
            "policy": {
                "core_integration_request_ready": True,
                "real_transaction_prepared": False,
                "real_transaction_committed": False,
                "candidate_installed": False,
                "profile_build_allowed": False,
                "profile_registered": False,
                "runtime_validated": False,
                "wet_variant_included": False,
            },
        }
        canonical_summary = {
            "status": "canonical_official_source_registry_and_overlay_resolver_ready_underscore_inputs_not_required_dry_bkn_retained_no_game_writes",
            "official_overlay_rows_resolved": 39,
            "active_operational_underscore_dependencies": 0,
            "dry_bkn_transaction_contract_still_valid": True,
            "underscore_files_required_for_future_workflow": False,
            "policy": {"canonical_source_contract_ready": True},
        }
        return tx, canon, out, tx_summary, canonical_summary

    def build(self, root: Path):
        tx, canon, out, tx_summary, canonical_summary = self.prepare(root)
        with mock.patch.object(mod.TX, "validate_report", return_value=tx_summary), mock.patch.object(mod.CANON, "validate_report", return_value=canonical_summary):
            archive, summary = mod.build_handoff(tx, canon, out)
        return tx, canon, out, archive, summary

    def test_full_handoff_is_metadata_only_and_fail_closed(self):
        with tempfile.TemporaryDirectory() as name:
            _tx, _canon, out, archive, summary = self.build(Path(name))
            self.assertTrue(archive.is_file())
            self.assertEqual(summary["transaction_target_count"], 2)
            self.assertEqual(summary["canonical_overlay_rows_resolved"], 39)
            self.assertTrue(summary["policy"]["core_handoff_ready"])
            self.assertFalse(summary["policy"]["real_transaction_prepared"])
            validated = mod.validate_report(out)
            self.assertEqual(validated["status"], summary["status"])

    def test_prepared_transaction_input_is_rejected(self):
        with tempfile.TemporaryDirectory() as name:
            tx, canon, out, tx_summary, canonical_summary = self.prepare(Path(name))
            tx_summary["policy"]["real_transaction_prepared"] = True
            with mock.patch.object(mod.TX, "validate_report", return_value=tx_summary), mock.patch.object(mod.CANON, "validate_report", return_value=canonical_summary), self.assertRaises(mod.BknDryCoreHandoffError):
                mod.build_handoff(tx, canon, out)

    def test_canonical_underscore_dependency_is_rejected(self):
        with tempfile.TemporaryDirectory() as name:
            tx, canon, out, tx_summary, canonical_summary = self.prepare(Path(name))
            canonical_summary["active_operational_underscore_dependencies"] = 1
            with mock.patch.object(mod.TX, "validate_report", return_value=tx_summary), mock.patch.object(mod.CANON, "validate_report", return_value=canonical_summary), self.assertRaises(mod.BknDryCoreHandoffError):
                mod.build_handoff(tx, canon, out)

    def test_missing_second_transaction_target_is_rejected(self):
        with tempfile.TemporaryDirectory() as name:
            tx, canon, out, tx_summary, canonical_summary = self.prepare(Path(name))
            request_path = tx / "DLC_BKN_DRY_CORE_TARGET_REQUEST.json"
            request = json.loads(request_path.read_text(encoding="utf-8"))
            request["transaction_files"].pop()
            write_json(request_path, request)
            with mock.patch.object(mod.TX, "validate_report", return_value=tx_summary), mock.patch.object(mod.CANON, "validate_report", return_value=canonical_summary), self.assertRaises(mod.BknDryCoreHandoffError):
                mod.build_handoff(tx, canon, out)

    def test_validate_rejects_commit_authorization(self):
        with tempfile.TemporaryDirectory() as name:
            _tx, _canon, out, _archive, _summary = self.build(Path(name))
            summary_path = out / "SUMMARY.json"
            summary = json.loads(summary_path.read_text(encoding="utf-8"))
            summary["policy"]["real_transaction_committed"] = True
            write_json(summary_path, summary)
            with self.assertRaises(mod.BknDryCoreHandoffError):
                mod.validate_report(out)


if __name__ == "__main__":
    unittest.main()
