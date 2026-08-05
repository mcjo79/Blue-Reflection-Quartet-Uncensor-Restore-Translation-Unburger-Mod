#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import importlib.util
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
TOOL_PATH = ROOT / "workstreams/quartet_restoration/prepare_residual_shared_presentation_repack_test.py"
SPEC = importlib.util.spec_from_file_location("prepare_residual_shared_presentation_repack_test", TOOL_PATH)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)

BR_SPEC = importlib.util.spec_from_file_location(
    "br_restoration_tool_stage37", ROOT / "Blue_Reflection_Text_Tool/br_restoration_tool.py"
)
assert BR_SPEC and BR_SPEC.loader
BR = importlib.util.module_from_spec(BR_SPEC)
sys.modules[BR_SPEC.name] = BR
BR_SPEC.loader.exec_module(BR)

HELPER_SPEC = importlib.util.spec_from_file_location(
    "stage37_existing_repack_test_helpers",
    ROOT / "workstreams/quartet_restoration/tests/test_br_restoration_tool.py",
)
assert HELPER_SPEC and HELPER_SPEC.loader
HELPERS = importlib.util.module_from_spec(HELPER_SPEC)
sys.modules[HELPER_SPEC.name] = HELPERS
HELPER_SPEC.loader.exec_module(HELPERS)


class ResidualSharedPresentationRepackTests(unittest.TestCase):
    def _prepare(self, root: Path, *, failed_gate: bool = False):
        project = root / "project"
        workspace = project / ".local/build/quartet_restoration"
        reports = project / ".local/reports/quartet_restoration"
        quartet = root / "quartet"
        gust_pak = root / "gust_pak"
        helper = HELPERS.EventRepackTestHarnessTests(methodName="runTest")
        helper._write_fake_gust_pak(gust_pak)

        tool_dir = project / "Blue_Reflection_Text_Tool"
        tool_dir.mkdir(parents=True)
        shutil.copy2(ROOT / "Blue_Reflection_Text_Tool/br_restoration_tool.py", tool_dir / "br_restoration_tool.py")

        target_members = {
            "event/b1/event_jp/ce11/event_ce11_070.ebd": b"quartet-ce11",
            "event/b1/event_jp/em01/event_em01_090.ebd": b"quartet-em01",
        }
        unrelated_member = "event/b1/event_en/ce11/event_ce11_070.ebd"
        archive_members = {**target_members, unrelated_member: b"current-translation-must-survive"}
        archive = quartet / "Data/PACK11.PAK"
        helper._write_fake_pak(archive, archive_members)
        installed_sha = BR.sha256_file(archive)

        reports.mkdir(parents=True)
        BR.write_tsv(reports / "ARCHIVE_INVENTORY.tsv", [
            "pair_id", "side", "archive", "sha256",
        ], [{
            "pair_id": "br1_events", "side": "target", "archive": "Data/PACK11.PAK",
            "sha256": installed_sha,
        }])

        evidence = reports / MODULE.STAGE36_EVIDENCE_DIR
        evidence.mkdir()
        validation_failure_count = 1 if failed_gate else 0
        BR.atomic_json(evidence / "SUMMARY.json", {
            "type": "br_quartet_restoration_residual_shared_presentation_prototype_evidence_summary",
            "format_version": 1,
            "tool_version": MODULE.STAGE36_TOOL_VERSION,
            "promoted_profile_rows": 1,
            "prototype_file_rows": 2,
            "prototype_validation_rows": 26,
            "validation_failures": validation_failure_count,
            "skipped_rows": 0,
        })
        BR.write_tsv(evidence / "RESIDUAL_SHARED_PRESENTATION_PROFILES.tsv", [
            "profile_id", "validation_status",
        ], [{"profile_id": MODULE.PROFILE_ID, "validation_status": "passed"}])

        prototype_root = workspace / MODULE.STAGE36_PROTOTYPE_SUBDIR / MODULE.PROFILE_ID
        files = []
        file_rows = []
        candidates = {
            "event/b1/event_jp/ce11/event_ce11_070.ebd": b"candidate-ce11",
            "event/b1/event_jp/em01/event_em01_090.ebd": b"candidate-em01",
        }
        normalized = {
            "event/b1/event_jp/ce11/event_ce11_070.ebd": "event/event_jp/ce11/event_ce11_070.ebd",
            "event/b1/event_jp/em01/event_em01_090.ebd": "event/event_jp/em01/event_em01_090.ebd",
        }
        for member, candidate in candidates.items():
            rel = "payload/" + normalized[member]
            path = prototype_root / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(candidate)
            candidate_sha = hashlib.sha256(candidate).hexdigest()
            target_sha = hashlib.sha256(target_members[member]).hexdigest()
            files.append({
                "normalized_path": normalized[member],
                "target_archive": "Data/PACK11.PAK",
                "target_member_path": member,
                "target_sha256": target_sha,
                "candidate_sha256": candidate_sha,
                "candidate_relative_path": rel,
            })
            file_rows.append({
                "profile_id": MODULE.PROFILE_ID,
                "target_member_path": member,
                "target_sha256": target_sha,
                "candidate_sha256": candidate_sha,
                "validation_status": "passed",
            })
        BR.atomic_json(prototype_root / "PROTOTYPE.json", {
            "type": "br_quartet_restoration_local_residual_shared_presentation_prototype",
            "format_version": 1,
            "tool_version": MODULE.STAGE36_TOOL_VERSION,
            "profile_id": MODULE.PROFILE_ID,
            "profile_classification": "shared_presentation_exact_span_local_prototype",
            "prototype_confidence": "metadata_gated",
            "installable_package_generated": False,
            "runtime_validated": False,
            "files": files,
        })
        BR.write_tsv(evidence / "RESIDUAL_SHARED_PRESENTATION_FILES.tsv", [
            "profile_id", "target_member_path", "target_sha256", "candidate_sha256", "validation_status",
        ], file_rows)
        validation_rows = []
        for index in range(26):
            validation_rows.append({
                "profile_id": MODULE.PROFILE_ID,
                "check_name": f"gate_{index:02d}",
                "passed": not (failed_gate and index == 0),
            })
        BR.write_tsv(evidence / "RESIDUAL_SHARED_PRESENTATION_VALIDATION.tsv", [
            "profile_id", "check_name", "passed",
        ], validation_rows)
        BR.write_tsv(evidence / "RESIDUAL_SHARED_PRESENTATION_BUILD_SKIPPED.tsv", [
            "profile_id", "reason",
        ], [])

        existing = workspace / BR.EVENT_REPACK_TEST_BUILD_DIR
        existing.mkdir(parents=True)
        (existing / "existing-profile-sentinel.txt").write_text("keep", encoding="utf-8")
        return project, workspace, reports, quartet, gust_pak, archive, installed_sha, helper, candidates, unrelated_member

    def test_builds_two_member_checksum_gated_pack11_profile(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            (
                project, workspace, reports, quartet, gust_pak, archive, installed_sha,
                helper, candidates, unrelated_member,
            ) = self._prepare(Path(temporary))
            output, summary = MODULE.prepare_residual_shared_presentation_repack_test(
                project_root=project,
                quartet_root=quartet,
                gust_pak=gust_pak,
                workspace_root=workspace,
                report_root=reports,
                timeout_seconds=30,
            )
            self.assertTrue(output.is_file())
            self.assertEqual(summary["profile_rows"], 1)
            self.assertEqual(summary["file_rows"], 2)
            self.assertEqual(summary["validation_failures"], 0)
            self.assertEqual(BR.sha256_file(archive), installed_sha)
            self.assertTrue((workspace / BR.EVENT_REPACK_TEST_BUILD_DIR / "existing-profile-sentinel.txt").is_file())

            final_root = workspace / MODULE.FINAL_BUILD_SUBDIR
            output_pak = final_root / "profiles" / MODULE.PROFILE_ID / "output/Data/PACK11.PAK"
            self.assertTrue(output_pak.is_file())
            for member, candidate in candidates.items():
                self.assertEqual(helper._read_fake_pak_member(output_pak, member), candidate)
            self.assertEqual(
                helper._read_fake_pak_member(output_pak, unrelated_member),
                b"current-translation-must-survive",
            )
            profile = json.loads((final_root / "profiles" / MODULE.PROFILE_ID / "PROFILE.json").read_text(encoding="utf-8"))
            self.assertEqual(profile["type"], "br_quartet_restoration_local_residual_shared_presentation_repack_test_profile")
            self.assertEqual(profile["replaced_member_count"], 2)
            self.assertFalse(profile["runtime_validated"])
            self.assertFalse(any(path.suffix.casefold() == ".pak" for path in (reports / MODULE.EVIDENCE_DIR_NAME).rglob("*")))

    def test_rejects_stage36_validation_failure_before_repack(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project, workspace, reports, quartet, gust_pak, *_ = self._prepare(
                Path(temporary), failed_gate=True,
            )
            with self.assertRaises(MODULE.SharedPresentationRepackError):
                MODULE.prepare_residual_shared_presentation_repack_test(
                    project_root=project,
                    quartet_root=quartet,
                    gust_pak=gust_pak,
                    workspace_root=workspace,
                    report_root=reports,
                    timeout_seconds=30,
                )
            self.assertFalse((workspace / MODULE.FINAL_BUILD_SUBDIR).exists())


if __name__ == "__main__":
    unittest.main()
