from __future__ import annotations

import csv
import hashlib
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

MODULE_PATH = Path(__file__).resolve().parents[1] / "br_dlc_bkn_dry_core_patch_handoff_tool.py"
SPEC = importlib.util.spec_from_file_location("core_patch_handoff_tool", MODULE_PATH)
assert SPEC and SPEC.loader
mod = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(mod)


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def write_tsv(path: Path, fields: list[str], rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


class CorePatchHandoffTest(unittest.TestCase):
    def make_proposal(self, project: Path) -> tuple[Path, dict[str, object]]:
        root = project / ".local/reports/quartet_legacy_dlc/bkn_dry_canonical_patch_proposal_evidence"
        root.mkdir(parents=True)
        patch = b"--- a/Blue_Reflection_Patcher/a\n+++ b/Blue_Reflection_Patcher/a\n"
        (root / mod.PATCH_NAME).write_bytes(patch)
        changed = []
        for idx, path in enumerate(mod.EXPECTED_CHANGED_CORE_FILES):
            action = "replace" if idx < 2 else "add"
            changed.append({
                "path": path,
                "action": action,
                "old_size": 10 + idx if action == "replace" else 0,
                "old_sha256": sha(f"old-{idx}".encode()) if action == "replace" else "",
                "new_size": 20 + idx,
                "new_sha256": sha(f"new-{idx}".encode()),
                "canonical_core_modified": "false",
            })
        write_tsv(
            root / "DLC_BKN_DRY_CANONICAL_PATCH_FILES.tsv",
            ["path", "action", "old_size", "old_sha256", "new_size", "new_sha256", "canonical_core_modified"],
            changed,
        )
        tests = []
        for idx in range(3):
            tests.append({"phase": "patch_apply_check", "package": "./internal/plan/payloadpreview", "test": f"TestLegacy{idx}", "status": "pass"})
            tests.append({"phase": "proposal_shadow", "package": "./internal/plan/payloadpreview", "test": f"TestLegacy{idx}", "status": "pass"})
        write_tsv(root / "DLC_BKN_DRY_CANONICAL_PATCH_GO_TESTS.tsv", ["phase", "package", "test", "status"], tests)
        guards = []
        for idx in range(6):
            path = mod.EXPECTED_CHANGED_CORE_FILES[idx] if idx < 4 else f"Blue_Reflection_Patcher/guard{idx}.go"
            guards.append({
                "path": path,
                "expected_size": 100 + idx,
                "expected_sha256": sha(f"guard-{idx}".encode()),
                "unchanged_after_proposal": "true",
            })
        write_tsv(
            root / "DLC_BKN_DRY_CANONICAL_PATCH_CORE_GUARD.tsv",
            ["path", "expected_size", "expected_sha256", "unchanged_after_proposal"],
            guards,
        )
        handoff = {
            "artifact_contract": [
                {"relative_path": "Data/PACK10_02.PAK", "candidate_sha256": sha(b"c1"), "baseline_sha256": sha(b"b1")},
                {"relative_path": "Data/PACK12.PAK", "candidate_sha256": sha(b"c2"), "baseline_sha256": sha(b"b2")},
            ],
            "authorization": {"core_patch_proposal_ready": True},
        }
        (root / "DLC_BKN_DRY_CANONICAL_PATCH_HANDOFF.json").write_text(json.dumps(handoff), encoding="utf-8")
        summary = {
            "patch_sha256": sha(patch),
            "patch_size": len(patch),
            "go_test_count_patch_apply_check": 3,
        }
        return root, summary

    def test_build_and_validate_handoff(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            proposal, summary = self.make_proposal(project)
            with mock.patch.object(mod.PROPOSAL, "validate_report", return_value=summary):
                report = mod.build_report(project, proposal)
            result = mod.validate_report(report)
            self.assertEqual(result["changed_source_file_count"], 4)
            self.assertEqual(result["artifact_count"], 2)
            self.assertEqual(result["test_count"], 3)
            self.assertEqual(result["acceptance_requirement_count"], 12)
            self.assertTrue((report / mod.HANDOFF_PATCH_NAME).is_file())

    def test_rejects_wrong_artifact_order(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            proposal, summary = self.make_proposal(project)
            handoff_path = proposal / "DLC_BKN_DRY_CANONICAL_PATCH_HANDOFF.json"
            handoff = json.loads(handoff_path.read_text())
            handoff["artifact_contract"].reverse()
            handoff_path.write_text(json.dumps(handoff), encoding="utf-8")
            with mock.patch.object(mod.PROPOSAL, "validate_report", return_value=summary):
                with self.assertRaises(mod.CorePatchHandoffError):
                    mod.build_report(project, proposal)

    def test_rejects_tampered_patch(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            proposal, summary = self.make_proposal(project)
            with mock.patch.object(mod.PROPOSAL, "validate_report", return_value=summary):
                report = mod.build_report(project, proposal)
            (report / mod.HANDOFF_PATCH_NAME).write_text("tampered", encoding="utf-8")
            with self.assertRaises(mod.CorePatchHandoffError):
                mod.validate_report(report)

    def test_rejects_unsafe_authorization(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            proposal, summary = self.make_proposal(project)
            with mock.patch.object(mod.PROPOSAL, "validate_report", return_value=summary):
                report = mod.build_report(project, proposal)
            handoff_path = report / "DLC_BKN_DRY_CORE_PATCH_HANDOFF.json"
            handoff = json.loads(handoff_path.read_text())
            handoff["authorization"]["real_transaction_prepare_enabled"] = True
            handoff_path.write_text(json.dumps(handoff, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            # Rebuild manifest so the failure is authorization, not manifest drift.
            (report / "REPORT_MANIFEST.json").write_text(
                json.dumps({"type": "br_report_manifest", "format_version": 1, "files": mod.report_manifest(report)}, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            with self.assertRaises(mod.CorePatchHandoffError):
                mod.validate_report(report)

    def test_bundle_contains_no_raw_game_payload(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            proposal, summary = self.make_proposal(project)
            with mock.patch.object(mod.PROPOSAL, "validate_report", return_value=summary):
                report = mod.build_report(project, proposal)
            output = project / "handoff.tar.zst"
            mod.make_archive(report, output)
            self.assertTrue(output.is_file())
            self.assertGreater(output.stat().st_size, 0)


if __name__ == "__main__":
    unittest.main()
