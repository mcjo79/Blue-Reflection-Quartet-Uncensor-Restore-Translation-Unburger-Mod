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
TOOL_PATH = ROOT / "workstreams/quartet_restoration/prepare_fe13_complete_residual_repack_test.py"
SPEC = importlib.util.spec_from_file_location("prepare_fe13_complete_residual_repack_test", TOOL_PATH)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)

BR_SPEC = importlib.util.spec_from_file_location(
    "br_restoration_tool_stage61", ROOT / "Blue_Reflection_Text_Tool/br_restoration_tool.py"
)
assert BR_SPEC and BR_SPEC.loader
BR = importlib.util.module_from_spec(BR_SPEC)
sys.modules[BR_SPEC.name] = BR
BR_SPEC.loader.exec_module(BR)

HELPER_SPEC = importlib.util.spec_from_file_location(
    "stage61_existing_repack_test_helpers",
    ROOT / "workstreams/quartet_restoration/tests/test_br_restoration_tool.py",
)
assert HELPER_SPEC and HELPER_SPEC.loader
HELPERS = importlib.util.module_from_spec(HELPER_SPEC)
sys.modules[HELPER_SPEC.name] = HELPERS
HELPER_SPEC.loader.exec_module(HELPERS)


class Fe13CompleteResidualRepackTests(unittest.TestCase):
    def _prepare(self, root: Path, *, bad_selected: bool = False):
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

        target_member = "event/b1/event_jp/fe13/event_fe13_090.ebd"
        target_payload = b"quartet-fe13-090"
        unrelated_member = "event/b1/event_en/fe13/event_fe13_090.ebd"
        archive_members = {
            target_member: target_payload,
            unrelated_member: b"current-translation-must-survive",
        }
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

        normalized = "event/event_jp/fe13/event_fe13_090.ebd"
        rel = normalized
        candidate = b"complete-residual-candidate-fe13-090"
        candidate_sha = hashlib.sha256(candidate).hexdigest()
        target_sha = hashlib.sha256(target_payload).hexdigest()
        original_expected_sha = MODULE.EXPECTED_CANDIDATE_SHA256
        MODULE.EXPECTED_CANDIDATE_SHA256 = candidate_sha
        self.addCleanup(setattr, MODULE, "EXPECTED_CANDIDATE_SHA256", original_expected_sha)

        evidence = reports / MODULE.STAGE60_EVIDENCE_DIR
        evidence.mkdir()
        BR.atomic_json(evidence / "SUMMARY.json", {
            "type": "br_quartet_restoration_fe13_remaining_residual_prototype_evidence_summary",
            "format_version": 1,
            "tool_version": MODULE.STAGE60_TOOL_VERSION,
            "proposed_profile_rows": 1,
            "promoted_profile_rows": 1,
            "prototype_file_rows": 1,
            "selected_occurrence_rows": 2,
            "remaining_residual_rows": 0,
            "validation_rows": 20,
            "validation_failures": 0,
            "skipped_rows": 0,
            "candidate_sha256": candidate_sha,
            "candidate_distance_to_original": MODULE.EXPECTED_CANDIDATE_DISTANCE,
            "runtime_testing_deferred": True,
        })
        BR.write_tsv(evidence / "FE13_REMAINING_RESIDUAL_PROTOTYPE_PROFILES.tsv", [
            "profile_id", "supersedes_profile_id", "validation_status", "runtime_validated",
            "remaining_residual_rows", "candidate_distance_to_original", "distance_improvement_over_stage51",
        ], [{
            "profile_id": MODULE.PROFILE_ID,
            "supersedes_profile_id": MODULE.SUPERSEDES_PROFILE_ID,
            "validation_status": "passed",
            "runtime_validated": False,
            "remaining_residual_rows": 0,
            "candidate_distance_to_original": MODULE.EXPECTED_CANDIDATE_DISTANCE,
            "distance_improvement_over_stage51": MODULE.EXPECTED_IMPROVEMENT_OVER_STAGE51,
        }])

        prototype_root = workspace / MODULE.STAGE60_PROTOTYPE_SUBDIR / MODULE.PROFILE_ID
        candidate_path = prototype_root / rel
        candidate_path.parent.mkdir(parents=True, exist_ok=True)
        candidate_path.write_bytes(candidate)
        file_item = {
            "normalized_path": normalized,
            "target_archive": "Data/PACK11.PAK",
            "target_member_path": target_member,
            "target_sha256": target_sha,
            "candidate_sha256": candidate_sha,
            "candidate_relative_path": rel,
            "candidate_byte_difference_to_source": MODULE.EXPECTED_CANDIDATE_DISTANCE,
            "remaining_residual_rows": 0,
            "selected_remaining_shape_ids": sorted(MODULE.SELECTED_SHAPE_IDS),
        }
        BR.atomic_json(prototype_root / "PROTOTYPE.json", {
            "type": "br_quartet_restoration_local_prototype",
            "format_version": 1,
            "tool_version": MODULE.STAGE60_TOOL_VERSION,
            "profile_id": MODULE.PROFILE_ID,
            "supersedes_profile_id": MODULE.SUPERSEDES_PROFILE_ID,
            "profile_classification": "experimental_single_scene_complete_residual_inverse_candidate",
            "prototype_confidence": "experimental_metadata_gated",
            "installable_package_generated": False,
            "runtime_validated": False,
            "installed_game_files_modified": False,
            "censorship_semantics_assigned": False,
            "files": [file_item],
        })
        BR.write_tsv(evidence / "FE13_REMAINING_RESIDUAL_PROTOTYPE_FILES.tsv", [
            "profile_id", "target_member_path", "target_sha256", "candidate_sha256",
            "candidate_distance_to_original", "stage51_distance_to_original", "distance_improvement_over_stage51",
        ], [{
            "profile_id": MODULE.PROFILE_ID,
            "target_member_path": target_member,
            "target_sha256": target_sha,
            "candidate_sha256": candidate_sha,
            "candidate_distance_to_original": MODULE.EXPECTED_CANDIDATE_DISTANCE,
            "stage51_distance_to_original": MODULE.EXPECTED_STAGE51_DISTANCE,
            "distance_improvement_over_stage51": MODULE.EXPECTED_IMPROVEMENT_OVER_STAGE51,
        }])
        BR.write_tsv(evidence / "FE13_REMAINING_RESIDUAL_PROTOTYPE_VALIDATIONS.tsv", [
            "profile_id", "check_name", "passed",
        ], [{
            "profile_id": MODULE.PROFILE_ID,
            "check_name": f"gate_{index:02d}",
            "passed": True,
        } for index in range(20)])
        selected = sorted(MODULE.SELECTED_SHAPE_IDS)
        if bad_selected:
            selected[1] = "0" * 64
        BR.write_tsv(evidence / "FE13_REMAINING_RESIDUAL_PROTOTYPE_SELECTED.tsv", [
            "profile_id", "shape_id", "semantic_status",
        ], [{
            "profile_id": MODULE.PROFILE_ID,
            "shape_id": shape,
            "semantic_status": "unassigned",
        } for shape in selected])
        BR.write_tsv(evidence / "FE13_REMAINING_RESIDUAL_PROTOTYPE_REMAINING.tsv", [
            "profile_id", "shape_id",
        ], [])
        BR.write_tsv(evidence / "FE13_REMAINING_RESIDUAL_PROTOTYPE_SKIPPED.tsv", [
            "profile_id", "reason",
        ], [])

        existing = workspace / BR.EVENT_REPACK_TEST_BUILD_DIR
        existing.mkdir(parents=True)
        (existing / "existing-profile-sentinel.txt").write_text("keep", encoding="utf-8")
        return (
            project, workspace, reports, quartet, gust_pak, archive, installed_sha,
            helper, candidate, target_member, unrelated_member,
        )

    def test_builds_one_member_checksum_gated_pack11_profile(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            prepared = self._prepare(Path(temporary))
            (
                project, workspace, reports, quartet, gust_pak, archive, installed_sha,
                helper, candidate, target_member, unrelated_member,
            ) = prepared
            output, summary = MODULE.prepare_fe13_complete_residual_repack_test(
                project_root=project,
                quartet_root=quartet,
                gust_pak=gust_pak,
                workspace_root=workspace,
                report_root=reports,
                timeout_seconds=30,
            )
            self.assertTrue(output.is_file())
            self.assertEqual(summary["profile_rows"], 1)
            self.assertEqual(summary["file_rows"], 1)
            self.assertEqual(summary["validation_failures"], 0)
            self.assertEqual(BR.sha256_file(archive), installed_sha)
            self.assertTrue((workspace / BR.EVENT_REPACK_TEST_BUILD_DIR / "existing-profile-sentinel.txt").is_file())

            final_root = workspace / MODULE.FINAL_BUILD_SUBDIR
            output_pak = final_root / "profiles" / MODULE.PROFILE_ID / "output/Data/PACK11.PAK"
            self.assertTrue(output_pak.is_file())
            self.assertEqual(helper._read_fake_pak_member(output_pak, target_member), candidate)
            self.assertEqual(
                helper._read_fake_pak_member(output_pak, unrelated_member),
                b"current-translation-must-survive",
            )
            profile = json.loads(
                (final_root / "profiles" / MODULE.PROFILE_ID / "PROFILE.json").read_text(encoding="utf-8")
            )
            self.assertEqual(profile["type"], "br_quartet_restoration_local_fe13_complete_residual_repack_test_profile")
            self.assertEqual(profile["supersedes_profile_id"], MODULE.SUPERSEDES_PROFILE_ID)
            self.assertEqual(profile["replaced_member_count"], 1)
            self.assertFalse(profile["runtime_validated"])
            self.assertFalse(any(path.suffix.casefold() == ".pak" for path in (reports / MODULE.EVIDENCE_DIR_NAME).rglob("*")))

    def test_rejects_changed_selected_residual_pair_before_repack(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            prepared = self._prepare(Path(temporary), bad_selected=True)
            project, workspace, reports, quartet, gust_pak, *_ = prepared
            with self.assertRaises(MODULE.Fe13CompleteResidualRepackError):
                MODULE.prepare_fe13_complete_residual_repack_test(
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
