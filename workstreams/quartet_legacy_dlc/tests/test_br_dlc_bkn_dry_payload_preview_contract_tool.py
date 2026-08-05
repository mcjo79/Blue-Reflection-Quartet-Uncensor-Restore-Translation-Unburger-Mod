from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

MODULE_PATH = Path(__file__).resolve().parents[1] / "br_dlc_bkn_dry_payload_preview_contract_tool.py"
SPEC = importlib.util.spec_from_file_location("br_dlc_bkn_dry_payload_preview_contract_tool", MODULE_PATH)
assert SPEC and SPEC.loader
mod = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(mod)


class PayloadPreviewContractTest(unittest.TestCase):
    def write(self, root: Path, relative: str, value: str) -> None:
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(value, encoding="utf-8")

    def synthetic_project(self, root: Path, *, duplicate_module: bool = False, preview_artifacts: list[str] | None = None) -> None:
        module = {
            "module_id": "quartet_legacy_dlc",
            "display_name": "Quartet legacy DLC adapter",
            "description": "test",
            "module_type": "dlc_adapter",
            "supported_targets": ["blue_reflection_quartet"],
            "default_targets": [],
            "dependencies": [],
            "conflicts": [],
            "selectable": True,
            "source_targets": ["blue_reflection_original"],
        }
        modules = [module, dict(module)] if duplicate_module else [module]
        self.write(root, mod.CORE_FILES[0], json.dumps({"type": "br_module_catalog", "format_version": 1, "modules": modules}))
        if preview_artifacts is None:
            spec = {
                "module_id": "quartet_legacy_dlc",
                "target_id": "blue_reflection_quartet",
                "source_kind": "future_selected_game_transfer",
                "connection_status": "pending_adapter",
                "reason": "pending",
                "artifacts": [],
            }
        else:
            spec = {
                "module_id": "quartet_legacy_dlc",
                "target_id": "blue_reflection_quartet",
                "source_kind": mod.EXPECTED_SOURCE_KIND,
                "connection_status": "connected_preview_only",
                "reason": "test",
                "artifacts": [{"relative_path": value} for value in preview_artifacts],
            }
        self.write(root, mod.CORE_FILES[1], json.dumps({"type": "br_local_payload_catalog", "format_version": 1, "module_targets": [spec]}))
        self.write(root, mod.CORE_FILES[2], 'if spec.ConnectionStatus == "connected_preview_only" && len(spec.Artifacts) == 0 {}\n')
        self.write(
            root,
            mod.CORE_FILES[3],
            'report, err := loadRepackReport(reportPath)\n'
            'func inspectArtifact(projectRoot string, report repackReport) { findReportEntry(report, "x", "y") }\n'
            'CommitEnabled: false\n'
            'TransactionPolicy: "preview verified local artifacts only; no transaction is prepared or committed"\n',
        )
        self.write(root, mod.CORE_FILES[4], "package payloadpreview\n")
        self.write(root, mod.CORE_FILES[5], 'fmt.Fprintf(out, "Preview only: no transaction was prepared and no game file was modified.")\n')

    def synthetic_handoff(self, root: Path) -> dict:
        handoff = {
            "type": "br_quartet_legacy_dlc_dry_bkn_core_integration_handoff",
            "format_version": 1,
            "handoff_id": "quartet_legacy_dlc_costume_pc00_bkn_dry",
            "handoff_version": "0.0.30",
            "content_id": "costume_pc00_bkn",
            "target_id": "blue_reflection_quartet",
            "transaction_files": [
                {
                    "relative_path": "Data/PACK10_02.PAK",
                    "role": "dry_parent_and_external_texture",
                    "baseline_size": 100,
                    "baseline_sha256": "1" * 64,
                    "candidate_relative_path": ".local/build/a/PACK10_02.PAK",
                    "candidate_size": 110,
                    "candidate_sha256": "2" * 64,
                },
                {
                    "relative_path": "Data/PACK12.PAK",
                    "role": "dry_charabase_fallback_removal",
                    "baseline_size": 200,
                    "baseline_sha256": "3" * 64,
                    "candidate_relative_path": ".local/build/b/PACK12.PAK",
                    "candidate_size": 208,
                    "candidate_sha256": "4" * 64,
                },
            ],
        }
        root.mkdir(parents=True, exist_ok=True)
        (root / "DLC_BKN_DRY_CORE_INTEGRATION_HANDOFF.json").write_text(json.dumps(handoff), encoding="utf-8")
        return {
            "status": "metadata_only_core_handoff_ready_not_wired_not_prepared_not_committed_not_installed",
            "policy": {
                "core_handoff_ready": True,
                "core_modified": False,
                "real_transaction_prepared": False,
                "real_transaction_committed": False,
                "candidate_installed": False,
                "profile_build_allowed": False,
                "profile_registered": False,
                "runtime_validated": False,
                "wet_variant_included": False,
                "game_modified": False,
                "git_modified": False,
            },
        }

    def test_builds_exact_two_artifact_patch_request(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            project = root / "project"
            handoff = root / "handoff"
            output = root / "report"
            self.synthetic_project(project)
            summary = self.synthetic_handoff(handoff)
            with mock.patch.object(mod.HANDOFF, "validate_report", return_value=summary):
                archive, built = mod.build_contract(project, handoff, output)
            self.assertTrue(archive.is_file())
            self.assertEqual(2, built["transaction_target_count"])
            request = json.loads((output / "DLC_BKN_DRY_PAYLOAD_PREVIEW_PATCH_REQUEST.json").read_text())
            self.assertEqual(set(mod.EXPECTED_TARGETS), {row["relative_path"] for row in request["artifact_contract"]})
            self.assertFalse(request["authorization"]["core_patch_applied"])
            mod.validate_report(output)

    def test_duplicate_module_catalog_row_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            project = root / "project"
            handoff = root / "handoff"
            self.synthetic_project(project, duplicate_module=True)
            summary = self.synthetic_handoff(handoff)
            with mock.patch.object(mod.HANDOFF, "validate_report", return_value=summary):
                with self.assertRaises(mod.BknDryPayloadPreviewContractError):
                    mod.build_contract(project, handoff, root / "report")

    def test_connected_catalog_requires_exact_two_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            project = root / "project"
            handoff = root / "handoff"
            self.synthetic_project(project, preview_artifacts=["Data/PACK10_02.PAK"])
            summary = self.synthetic_handoff(handoff)
            with mock.patch.object(mod.HANDOFF, "validate_report", return_value=summary):
                with self.assertRaises(mod.BknDryPayloadPreviewContractError):
                    mod.build_contract(project, handoff, root / "report")

    def test_catalog_candidate_is_preview_only_and_all_or_none(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            project = root / "project"
            handoff = root / "handoff"
            output = root / "report"
            self.synthetic_project(project)
            summary = self.synthetic_handoff(handoff)
            with mock.patch.object(mod.HANDOFF, "validate_report", return_value=summary):
                mod.build_contract(project, handoff, output)
            candidate = json.loads((output / "DLC_BKN_DRY_PAYLOAD_PREVIEW_CATALOG_CANDIDATE.json").read_text())
            self.assertEqual("connected_preview_only", candidate["connection_status"])
            self.assertEqual(mod.EXPECTED_SOURCE_KIND, candidate["source_kind"])
            self.assertEqual(set(mod.EXPECTED_TARGETS), {row["relative_path"] for row in candidate["artifacts"]})
            rows = mod.read_tsv(output / "DLC_BKN_DRY_PAYLOAD_PREVIEW_ARTIFACT_CONTRACT.tsv")
            self.assertTrue(all(row["independent_preview_ready_allowed"] == "false" for row in rows))

    def test_validator_rejects_applied_core_patch_claim(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            project = root / "project"
            handoff = root / "handoff"
            output = root / "report"
            self.synthetic_project(project)
            summary = self.synthetic_handoff(handoff)
            with mock.patch.object(mod.HANDOFF, "validate_report", return_value=summary):
                mod.build_contract(project, handoff, output)
            value = json.loads((output / "SUMMARY.json").read_text())
            value["policy"]["core_patch_applied"] = True
            (output / "SUMMARY.json").write_text(json.dumps(value), encoding="utf-8")
            with self.assertRaises(mod.BknDryPayloadPreviewContractError):
                mod.validate_report(output)


if __name__ == "__main__":
    unittest.main()
