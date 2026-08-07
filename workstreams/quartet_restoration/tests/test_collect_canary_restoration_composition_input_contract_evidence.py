#!/usr/bin/env python3
from __future__ import annotations

import csv
import hashlib
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

MODULE_PATH = Path(__file__).resolve().parents[1] / "119_collect_canary_restoration_composition_input_contract_evidence.py"
spec = importlib.util.spec_from_file_location("canary_input_contract", MODULE_PATH)
assert spec and spec.loader
C = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = C
spec.loader.exec_module(C)


class CanaryCompositionInputContractTests(unittest.TestCase):
    @staticmethod
    def digest(data: bytes) -> str:
        return hashlib.sha256(data).hexdigest()

    @staticmethod
    def write_tsv(path: Path, fields: list[str], rows: list[dict[str, object]]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields, delimiter="\t", lineterminator="\n")
            writer.writeheader()
            writer.writerows(rows)

    def make_fixture(self, root: Path) -> tuple[Path, Path]:
        project = root / "project"
        reports = root / "reports"
        manifest_root = project / C.MANIFEST_ROOT_REL
        manifest_root.mkdir(parents=True)

        source_texts = {
            "preview": "\n".join([
                "switch {",
                "case !profile.RuntimeValidated:",
                'profile.Status = "candidate_awaiting_runtime_validation"',
                'profile.Status = "eligible_runtime_validated"',
                'preview.Status = "awaiting_runtime_validated_profiles"',
                "}",
            ]) + "\n",
            "build": "\n".join([
                'if preflight.Status != "ready_for_composition_build" {',
                'if !profile.ProductionEligible {',
                'composition preflight selected no production-eligible restoration profiles',
            ]) + "\n",
            "main": 'case "quartet-composition-build":\n',
            "preview_doc": "A profile enters only when `runtime_validated` is true.\n",
            "build_doc": "Only profiles that are valid, locally hash-verified and marked\n",
        }
        for role, relative in C.PRODUCTION_CONTRACT_FILES.items():
            path = project / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(source_texts[role], encoding="utf-8")

        target_profiles = []
        for target, count in C.EXPECTED_TARGET_PROFILE_ROWS.items():
            target_profiles.extend((target, index) for index in range(count))

        baseline_by_target = {
            target: (self.digest(f"baseline:{target}".encode()), 1000 + index)
            for index, target in enumerate(C.EXPECTED_TARGET_PROFILE_ROWS)
        }
        remaining_extra = C.EXPECTED_CHANGED_MEMBER_ROWS - C.EXPECTED_PROFILE_ROWS
        report_rows: list[dict[str, object]] = []
        for ordinal, (target, index) in enumerate(target_profiles):
            profile_id = f"profile_{ordinal:02d}"
            member_count = 1 + (remaining_extra if ordinal == 0 else 0)
            members = [f"member/{ordinal:02d}_{member:02d}.bin" for member in range(member_count)]
            payload = (f"payload:{profile_id}:" * 3).encode()
            local_rel = f".local/build/quartet_restoration/test_profiles/{profile_id}.pak"
            local_path = project / local_rel
            local_path.parent.mkdir(parents=True, exist_ok=True)
            local_path.write_bytes(payload)
            baseline_sha256, baseline_size = baseline_by_target[target]
            manifest = {
                "schema_version": 1,
                "profile_id": profile_id,
                "target_relative_path": target,
                "baseline_sha256": baseline_sha256,
                "baseline_size": baseline_size,
                "profile_sha256": self.digest(payload),
                "profile_size": len(payload),
                "local_profile_path": local_rel,
                "changed_member_count": member_count,
                "changed_members": members,
                "runtime_validated": False,
                "workstream_id": "quartet_restoration",
                "workstream_version": "0.0.83",
            }
            (manifest_root / f"{profile_id}.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
            report_rows.append(
                {
                    "profile_id": profile_id,
                    "target_relative_path": target,
                    "baseline_sha256": baseline_sha256,
                    "baseline_size": baseline_size,
                    "profile_sha256": self.digest(payload),
                    "profile_size": len(payload),
                    "local_profile_path": local_rel,
                    "changed_member_count": member_count,
                    "manifest_relative_path": f"{C.MANIFEST_ROOT_REL.as_posix()}/{profile_id}.json",
                    "runtime_validated": "false",
                    "workstream_version": "0.0.83",
                    "validation_status": "passed",
                }
            )

        core_root = reports / C.CORE_REPORT_DIR
        core_root.mkdir(parents=True)
        core_summary = {
            "type": "br_quartet_restoration_core_profile_manifest_evidence_summary",
            "format_version": 1,
            "tool_version": "0.0.83",
            "status": "all_current_local_profiles_registered_runtime_unvalidated",
            "profile_rows": 15,
            "pack11_profile_rows": 12,
            "pack10_01_profile_rows": 2,
            "pack10_03_profile_rows": 1,
            "runtime_validated_profile_rows": 0,
            "policy": {
                "profile_paks_checksum_and_size_verified": True,
                "activation_or_rollback_scripts_generated": False,
                "runtime_validation_inferred": False,
            },
        }
        (core_root / "SUMMARY.json").write_text(json.dumps(core_summary, indent=2) + "\n", encoding="utf-8")
        self.write_tsv(
            core_root / "CORE_PROFILE_MANIFESTS.tsv",
            [
                "profile_id", "target_relative_path", "baseline_sha256", "baseline_size", "profile_sha256",
                "profile_size", "local_profile_path", "changed_member_count", "manifest_relative_path",
                "runtime_validated", "workstream_version", "validation_status",
            ],
            report_rows,
        )

        freeze_root = reports / C.FREEZE_REPORT_DIR
        freeze_root.mkdir(parents=True)
        freeze_summary = {
            "type": "br_quartet_restoration_reflector_slot_light_swordflash_unresolved_freeze_evidence_summary",
            "format_version": 1,
            "tool_version": "0.1.36",
            "status": "existing_independent_binding_channels_exhausted_swordflash_branch_frozen_unresolved_no_write",
            "stage118_report_sha256": C.STAGE118_SHA256,
            "existing_binding_channel_rows": 6,
            "authorizing_binding_channel_rows": 0,
            "frozen_unresolved_swordflash_pair_rows": 2,
            "numbered_stage_created": False,
            "policy": {
                "deletion_ordinal_2_accepted_from_table_eligibility_alone": False,
                "G1E_G1EM_write_authorized": False,
                "pak_repack_authorized": False,
                "profile_or_registry_write_authorized": False,
                "installed_game_modified": False,
                "git_modified": False,
            },
        }
        (freeze_root / "SUMMARY.json").write_text(json.dumps(freeze_summary, indent=2) + "\n", encoding="utf-8")
        return project, reports

    def test_immutable_core_profile_report_hash(self) -> None:
        fixture_root = Path(__file__).resolve().parent / "fixtures" / "stage119_historical_reports"
        archive = fixture_root / C.CORE_REPORT_ARCHIVE
        self.assertEqual(C.sha256_file(archive), C.CORE_REPORT_SHA256)

    def test_real_tree_metadata_contract_is_15_profiles_split_12_2_1(self) -> None:
        project_root = Path(__file__).resolve().parents[3]
        with tempfile.TemporaryDirectory(prefix="canary-real-metadata-") as tmp_name:
            fixture_root = Path(__file__).resolve().parent / "fixtures" / "stage119_historical_reports"
            frozen_manifest_root = Path(__file__).resolve().parent / "fixtures" / "stage119_historical_core_profile_manifests"
            _, archive, summary = C.build_report(
                project_root,
                core_source_report_root=fixture_root,
                output_report_root=Path(tmp_name),
                verify_payloads=False,
                enforce_core_archive_hash=True,
                create_archive=False,
                manifest_root=frozen_manifest_root,
            )
            self.assertIsNone(archive)
            self.assertEqual(summary["profile_rows"], 15)
            self.assertEqual(summary["pack11_profile_rows"], 12)
            self.assertEqual(summary["pack10_01_profile_rows"], 2)
            self.assertEqual(summary["pack10_03_profile_rows"], 1)
            self.assertEqual(summary["changed_member_reference_rows"], 30)
            self.assertEqual(summary["changed_member_conflict_rows"], 0)
            self.assertTrue(summary["production_composer_present"])
            self.assertTrue(summary["production_composer_runtime_validated_only"])
            self.assertFalse(summary["production_composer_accepts_current_profiles"])
            self.assertFalse(summary["separate_canary_all_entrypoint_present"])
            self.assertFalse(summary["canary_all_composer_implemented"])
            self.assertFalse(summary["canary_input_contract_ready"])

    def test_fixture_full_payload_audit_passes_without_composite(self) -> None:
        with tempfile.TemporaryDirectory(prefix="canary-fixture-") as tmp_name:
            root = Path(tmp_name)
            project, reports = self.make_fixture(root)
            output, archive, summary = C.build_report(
                project,
                source_report_root=reports,
                output_report_root=root / "output",
                verify_payloads=True,
                enforce_core_archive_hash=False,
                create_archive=False,
            )
            self.assertIsNone(archive)
            self.assertTrue((output / "SUMMARY.json").is_file())
            self.assertEqual(summary["profile_payload_check_pass_rows"], 15)
            self.assertEqual(summary["changed_member_reference_rows"], 30)
            self.assertEqual(summary["unique_changed_member_rows"], 30)
            self.assertTrue(summary["canary_input_contract_ready"])
            self.assertFalse(summary["canary_all_composer_implemented"])
            self.assertFalse(summary["composite_pak_written"])
            self.assertFalse(summary["activation_authorized"])

    def test_missing_profile_payload_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory(prefix="canary-missing-") as tmp_name:
            root = Path(tmp_name)
            project, reports = self.make_fixture(root)
            manifest_path = sorted((project / C.MANIFEST_ROOT_REL).glob("*.json"))[0]
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            (project / manifest["local_profile_path"]).unlink()
            with self.assertRaisesRegex(C.CanaryContractError, "missing local profile payload"):
                C.build_report(project, source_report_root=reports, output_report_root=root / "output", verify_payloads=True, enforce_core_archive_hash=False, create_archive=False)

    def test_profile_payload_hash_drift_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory(prefix="canary-hash-") as tmp_name:
            root = Path(tmp_name)
            project, reports = self.make_fixture(root)
            manifest_path = sorted((project / C.MANIFEST_ROOT_REL).glob("*.json"))[0]
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            payload = project / manifest["local_profile_path"]
            payload.write_bytes(b"X" * manifest["profile_size"])
            with self.assertRaisesRegex(C.CanaryContractError, "local profile SHA-256 drift"):
                C.build_report(project, source_report_root=reports, output_report_root=root / "output", verify_payloads=True, enforce_core_archive_hash=False, create_archive=False)

    def test_changed_member_overlap_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory(prefix="canary-overlap-") as tmp_name:
            root = Path(tmp_name)
            project, reports = self.make_fixture(root)
            manifests = sorted((project / C.MANIFEST_ROOT_REL).glob("*.json"))
            first = json.loads(manifests[0].read_text(encoding="utf-8"))
            second = json.loads(manifests[1].read_text(encoding="utf-8"))
            second["changed_members"][0] = first["changed_members"][0]
            manifests[1].write_text(json.dumps(second, indent=2) + "\n", encoding="utf-8")
            with self.assertRaisesRegex(C.CanaryContractError, "changed member overlap detected"):
                C.build_report(project, source_report_root=reports, output_report_root=root / "output", verify_payloads=True, enforce_core_archive_hash=False, create_archive=False)

    def test_unclosed_swordflash_branch_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory(prefix="canary-freeze-") as tmp_name:
            root = Path(tmp_name)
            project, reports = self.make_fixture(root)
            summary_path = reports / C.FREEZE_REPORT_DIR / "SUMMARY.json"
            summary = json.loads(summary_path.read_text(encoding="utf-8"))
            summary["authorizing_binding_channel_rows"] = 1
            summary_path.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
            with self.assertRaisesRegex(C.CanaryContractError, "authorizing-channel drift"):
                C.build_report(project, source_report_root=reports, output_report_root=root / "output", verify_payloads=True, enforce_core_archive_hash=False, create_archive=False)

    def test_runtime_validated_manifest_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory(prefix="canary-runtime-") as tmp_name:
            root = Path(tmp_name)
            project, reports = self.make_fixture(root)
            manifest_path = sorted((project / C.MANIFEST_ROOT_REL).glob("*.json"))[0]
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["runtime_validated"] = True
            manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
            with self.assertRaisesRegex(C.CanaryContractError, "runtime-validated profile entered Canary input snapshot"):
                C.build_report(project, source_report_root=reports, output_report_root=root / "output", verify_payloads=True, enforce_core_archive_hash=False, create_archive=False)

    def test_production_composer_contract_drift_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory(prefix="canary-core-drift-") as tmp_name:
            root = Path(tmp_name)
            project, reports = self.make_fixture(root)
            preview = project / C.PRODUCTION_CONTRACT_FILES["preview"]
            preview.write_text(preview.read_text(encoding="utf-8").replace("case !profile.RuntimeValidated:", "case false:"), encoding="utf-8")
            with self.assertRaisesRegex(C.CanaryContractError, "production composer contract drift"):
                C.build_report(project, source_report_root=reports, output_report_root=root / "output", verify_payloads=True, enforce_core_archive_hash=False, create_archive=False)

    def test_unexpected_explicit_canary_entrypoint_requires_review(self) -> None:
        with tempfile.TemporaryDirectory(prefix="canary-entrypoint-") as tmp_name:
            root = Path(tmp_name)
            project, reports = self.make_fixture(root)
            main = project / C.PRODUCTION_CONTRACT_FILES["main"]
            main.write_text(main.read_text(encoding="utf-8") + 'case "quartet-canary-composition-build":\n', encoding="utf-8")
            with self.assertRaisesRegex(C.CanaryContractError, "unexpected explicit Canary-all entrypoint"):
                C.build_report(project, source_report_root=reports, output_report_root=root / "output", verify_payloads=True, enforce_core_archive_hash=False, create_archive=False)


if __name__ == "__main__":
    unittest.main()
