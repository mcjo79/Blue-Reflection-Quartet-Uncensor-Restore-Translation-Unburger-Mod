from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import sys

HERE = Path(__file__).resolve().parent
WORKSTREAM = HERE.parent
PROJECT_ROOT = WORKSTREAM.parents[1]
if str(WORKSTREAM) not in sys.path:
    sys.path.insert(0, str(WORKSTREAM))

import br_dlc_bkn_dry_transaction_contract_tool as mod


class TransactionContractTest(unittest.TestCase):
    def make_fixture(self, root: Path) -> tuple[Path, Path, dict, dict, list[dict[str, str]]]:
        project = root / "project"
        quartet = root / "quartet"
        project.mkdir()
        (quartet / "Data").mkdir(parents=True)
        baseline10 = b"baseline-pack10"
        baseline12 = b"baseline12xx"
        candidate10 = b"candidate-pack10"
        candidate12 = b"candidate-pack12-xxxx"
        (quartet / "Data/PACK10_02.PAK").write_bytes(baseline10)
        (quartet / "Data/PACK12.PAK").write_bytes(baseline12)
        path10 = project / ".local/build/p10/PACK10_02.PAK"
        path12 = project / ".local/build/p12/PACK12.PAK"
        path10.parent.mkdir(parents=True)
        path12.parent.mkdir(parents=True)
        path10.write_bytes(candidate10)
        path12.write_bytes(candidate12)
        pack10 = {
            "tool_version": "0.0.13",
            "baseline_size": len(baseline10),
            "baseline_sha256": mod.sha256_bytes(baseline10),
        }
        pack12 = {
            "tool_version": "0.0.21",
            "candidate_pack12_size": len(baseline12) + 8,
            "baseline_pack12_sha256": mod.sha256_bytes(baseline12),
        }
        composition = [
            {
                "archive": "Data/PACK10_02.PAK",
                "role": "dry_parent_and_external_texture",
                "candidate_relative_path": path10.relative_to(project).as_posix(),
                "candidate_size": str(len(candidate10)),
                "candidate_sha256": mod.sha256_bytes(candidate10),
            },
            {
                "archive": "Data/PACK12.PAK",
                "role": "dry_charabase_fallback_removal",
                "candidate_relative_path": path12.relative_to(project).as_posix(),
                "candidate_size": str(len(candidate12)),
                "candidate_sha256": mod.sha256_bytes(candidate12),
            },
        ]
        return project, quartet, pack10, pack12, composition

    @staticmethod
    def probe() -> dict:
        return {
            "status": "passed",
            "prepare_preserved_both_originals": True,
            "staged_payloads_hash_verified": True,
            "backup_files_hash_verified": True,
            "journal_hashes_verified": True,
            "journal_file_count": 2,
            "journal_paths": ["Data/PACK10_02.PAK", "Data/PACK12.PAK"],
            "commit_replaced_both": True,
            "rollback_restored_both": True,
            "final_journal_status": "rolled_back",
            "conflict_after_prepare_rejected": True,
            "conflict_target_preserved": True,
            "selected_modules": ["quartet_legacy_dlc"],
            "metadata": {},
        }

    @staticmethod
    def capabilities() -> list[dict]:
        return [
            {"capability": f"capability_{index}", "present": True, "validation_status": "passed"}
            for index in range(11)
        ]

    def test_real_core_probe_handles_two_existing_files(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            work = Path(name)
            value = mod.run_core_probe(
                PROJECT_ROOT / "Blue_Reflection_Patcher",
                work,
                {"target_id": "blue_reflection_quartet", "content_id": "costume_pc00_bkn"},
                120,
            )
            self.assertEqual(value["journal_file_count"], 2)
            self.assertTrue(value["staged_payloads_hash_verified"])
            self.assertTrue(value["backup_files_hash_verified"])
            self.assertTrue(value["journal_hashes_verified"])
            self.assertTrue(value["commit_replaced_both"])
            self.assertTrue(value["rollback_restored_both"])
            self.assertTrue(value["conflict_after_prepare_rejected"])

    def test_real_core_probe_accepts_resolved_core_path_with_spaces(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            spaced_core = root / "Blue Reflection Patcher"
            shutil.copytree(PROJECT_ROOT / "Blue_Reflection_Patcher", spaced_core)
            value = mod.run_core_probe(
                spaced_core,
                root / "probe work",
                {"target_id": "blue_reflection_quartet", "content_id": "costume_pc00_bkn"},
                120,
            )
            self.assertEqual(value["journal_file_count"], 2)
            self.assertTrue(value["commit_replaced_both"])


    def test_behavioral_probe_resolves_format_sensitive_backup_scan(self) -> None:
        rows = [
            {
                "capability": "prepare_backs_up_and_hashes_existing_targets",
                "present": False,
                "validation_method": "static_source_or_test_scan",
                "validation_status": "pending_behavioral_probe",
            }
        ]
        resolved = mod.finalize_core_capabilities(rows, self.probe())
        self.assertTrue(resolved[0]["present"])
        self.assertEqual(resolved[0]["validation_method"], "isolated_behavioral_probe")
        self.assertEqual(resolved[0]["validation_status"], "passed")

    def test_static_backup_scan_miss_does_not_fail_behavioral_capability(self) -> None:
        rows = [{
            "capability": "prepare_backs_up_and_hashes_existing_targets",
            "present": False,
            "validation_method": "static_source_or_test_scan",
            "validation_status": "pending_behavioral_probe",
        }]
        resolved = mod.finalize_core_capabilities(rows, self.probe())
        self.assertTrue(resolved[0]["present"])
        self.assertEqual(resolved[0]["validation_method"], "isolated_behavioral_probe")

    def test_core_source_scan_accepts_line_wrapped_backup_call(self) -> None:
        source = """
func prepare() error {
    if err := copyRegularFile(
        target,
        backupPath,
        info.Mode().Perm(),
    ); err != nil {
        return err
    }
    return fmt.Errorf("backup hash mismatch")
}
"""
        self.assertTrue(mod.has_backup_copy_call(source))

    def test_current_core_backup_capability_is_resolved_behaviorally(self) -> None:
        rows, _, _ = mod.inspect_core_contract(PROJECT_ROOT / "Blue_Reflection_Patcher")
        indexed = {row["capability"]: row for row in rows}
        self.assertIn("prepare_backs_up_and_hashes_existing_targets", indexed)
        resolved = mod.finalize_core_capabilities(
            [indexed["prepare_backs_up_and_hashes_existing_targets"]],
            self.probe(),
        )
        self.assertTrue(resolved[0]["present"])
        self.assertEqual(resolved[0]["validation_status"], "passed")
        self.assertIn(
            resolved[0]["validation_method"],
            {"static_source_or_test_scan", "isolated_behavioral_probe"},
        )

    def test_core_source_scan_rejects_non_backup_destination(self) -> None:
        source = "copyRegularFile(target, unrelatedPath, info.Mode().Perm())"
        self.assertFalse(mod.has_backup_copy_call(source))

    def test_build_request_is_fail_closed(self) -> None:
        request = mod.build_request([], "a" * 64, "b" * 64)
        auth = request["authorization"]
        self.assertTrue(auth["core_integration_request_ready"])
        self.assertFalse(auth["real_transaction_prepare_enabled"])
        self.assertFalse(auth["commit_enabled"])
        self.assertFalse(auth["profile_build_allowed"])

    def test_audit_builds_metadata_only_contract(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            project, quartet, pack10, pack12, composition = self.make_fixture(Path(name))
            output = project / ".local/reports/quartet_legacy_dlc" / mod.REPORT_DIR_NAME
            with (
                mock.patch.object(mod, "validate_prerequisites", return_value=(pack10, pack12, composition)),
                mock.patch.object(mod, "inspect_core_contract", return_value=(self.capabilities(), "a" * 64, "b" * 64)),
                mock.patch.object(mod, "run_core_probe", return_value=self.probe()),
            ):
                archive, summary = mod.audit(project, quartet, output)
            self.assertTrue(archive.is_file())
            self.assertEqual(summary["transaction_target_count"], 2)
            self.assertFalse(summary["policy"]["real_transaction_prepared"])
            validated = mod.validate_report(output)
            self.assertTrue(validated["policy"]["core_integration_request_ready"])
            forbidden = {".pak", ".xml", ".exe", ".dll"}
            self.assertFalse(any({s.lower() for s in path.suffixes} & forbidden for path in output.rglob("*") if path.is_file()))

    def test_audit_rejects_candidate_drift(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            project, quartet, pack10, pack12, composition = self.make_fixture(Path(name))
            candidate = project / composition[0]["candidate_relative_path"]
            candidate.write_bytes(candidate.read_bytes() + b"drift")
            with mock.patch.object(mod, "validate_prerequisites", return_value=(pack10, pack12, composition)):
                with self.assertRaises(mod.BknDryTransactionContractError):
                    mod.audit(project, quartet, project / "report")

    def test_validate_rejects_real_commit_authorization(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            project, quartet, pack10, pack12, composition = self.make_fixture(Path(name))
            output = project / ".local/reports/quartet_legacy_dlc" / mod.REPORT_DIR_NAME
            with (
                mock.patch.object(mod, "validate_prerequisites", return_value=(pack10, pack12, composition)),
                mock.patch.object(mod, "inspect_core_contract", return_value=(self.capabilities(), "a" * 64, "b" * 64)),
                mock.patch.object(mod, "run_core_probe", return_value=self.probe()),
            ):
                mod.audit(project, quartet, output)
            request_path = output / "DLC_BKN_DRY_CORE_TARGET_REQUEST.json"
            request = json.loads(request_path.read_text(encoding="utf-8"))
            request["authorization"]["commit_enabled"] = True
            request_path.write_text(json.dumps(request), encoding="utf-8")
            with self.assertRaises(mod.BknDryTransactionContractError):
                mod.validate_report(output)


if __name__ == "__main__":
    unittest.main()
