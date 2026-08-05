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
TOOL_PATH = ROOT / "workstreams/quartet_restoration/prepare_presentation_event_subset_repack_tests.py"
SPEC = importlib.util.spec_from_file_location("prepare_presentation_event_subset_repack_tests", TOOL_PATH)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)

BR_SPEC = importlib.util.spec_from_file_location(
    "br_restoration_tool_stage46", ROOT / "Blue_Reflection_Text_Tool/br_restoration_tool.py"
)
assert BR_SPEC and BR_SPEC.loader
BR = importlib.util.module_from_spec(BR_SPEC)
sys.modules[BR_SPEC.name] = BR
BR_SPEC.loader.exec_module(BR)

HELPER_SPEC = importlib.util.spec_from_file_location(
    "stage46_existing_repack_test_helpers",
    ROOT / "workstreams/quartet_restoration/tests/test_br_restoration_tool.py",
)
assert HELPER_SPEC and HELPER_SPEC.loader
HELPERS = importlib.util.module_from_spec(HELPER_SPEC)
sys.modules[HELPER_SPEC.name] = HELPERS
HELPER_SPEC.loader.exec_module(HELPERS)


class PresentationEventSubsetRepackTests(unittest.TestCase):
    def _prepare(self, root: Path, *, corrupt_validation: bool = False):
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

        archive_members: dict[str, bytes] = {
            member: f"quartet-{profile_id}".encode("ascii")
            for profile_id, member in MODULE.EXPECTED_PROFILE_MEMBERS.items()
        }
        unrelated_member = "event/b1/event_en/shared/unrelated.ebd"
        archive_members[unrelated_member] = b"current-translation-must-survive"
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

        evidence = reports / MODULE.STAGE45_EVIDENCE_DIR
        evidence.mkdir()
        BR.atomic_json(evidence / "SUMMARY.json", {
            "type": "br_quartet_restoration_presentation_event_subset_prototype_evidence_summary",
            "format_version": 1,
            "tool_version": MODULE.STAGE45_TOOL_VERSION,
            "proposed_profile_rows": 6,
            "promoted_profile_rows": 6,
            "prototype_file_rows": 6,
            "selected_occurrence_rows": 21,
            "remaining_residual_rows": 115,
            "validation_rows": 168,
            "validation_failures": 0,
            "skipped_rows": 0,
            "runtime_testing_deferred": True,
        })

        profile_rows = []
        file_rows = []
        validation_rows = []
        candidates: dict[str, bytes] = {}
        for profile_index, (profile_id, member) in enumerate(MODULE.EXPECTED_PROFILE_MEMBERS.items()):
            normalized = member.removeprefix("event/b1/")
            candidate = f"candidate-{profile_id}".encode("ascii")
            candidates[profile_id] = candidate
            target_payload = archive_members[member]
            target_sha = hashlib.sha256(target_payload).hexdigest()
            candidate_sha = hashlib.sha256(candidate).hexdigest()
            profile_root = workspace / MODULE.STAGE45_PROTOTYPE_SUBDIR / profile_id
            rel = "payload/" + normalized
            candidate_path = profile_root / rel
            candidate_path.parent.mkdir(parents=True, exist_ok=True)
            candidate_path.write_bytes(candidate)
            BR.atomic_json(profile_root / "PROTOTYPE.json", {
                "type": "br_quartet_restoration_local_presentation_event_subset_prototype",
                "format_version": 1,
                "tool_version": MODULE.STAGE45_TOOL_VERSION,
                "profile_id": profile_id,
                "profile_classification": "experimental_bounded_subset_static_candidate",
                "prototype_confidence": "experimental_metadata_gated",
                "installable_package_generated": False,
                "runtime_validated": False,
                "files": [{
                    "normalized_path": normalized,
                    "target_archive": "Data/PACK11.PAK",
                    "target_member_path": member,
                    "target_sha256": target_sha,
                    "candidate_sha256": candidate_sha,
                    "candidate_relative_path": rel,
                }],
            })
            profile_rows.append({
                "profile_id": profile_id,
                "validation_status": "passed",
                "runtime_validated": False,
            })
            file_rows.append({
                "profile_id": profile_id,
                "target_member_path": member,
                "target_sha256": target_sha,
                "candidate_sha256": candidate_sha,
                "validation_status": "passed",
                "distance_improvement": 10 + profile_index,
            })
            for gate in range(28):
                validation_rows.append({
                    "profile_id": profile_id,
                    "check_name": f"gate_{gate:02d}",
                    "passed": not (corrupt_validation and profile_index == 0 and gate == 0),
                })

        BR.write_tsv(evidence / "PRESENTATION_EVENT_SUBSET_PROFILES.tsv", [
            "profile_id", "validation_status", "runtime_validated",
        ], profile_rows)
        BR.write_tsv(evidence / "PRESENTATION_EVENT_SUBSET_FILES.tsv", [
            "profile_id", "target_member_path", "target_sha256", "candidate_sha256",
            "validation_status", "distance_improvement",
        ], file_rows)
        BR.write_tsv(evidence / "PRESENTATION_EVENT_SUBSET_VALIDATION.tsv", [
            "profile_id", "check_name", "passed",
        ], validation_rows)
        BR.write_tsv(evidence / "PRESENTATION_EVENT_SUBSET_BUILD_SKIPPED.tsv", [
            "profile_id", "normalized_path", "reason",
        ], [])
        return project, workspace, reports, quartet, gust_pak, archive, installed_sha, helper, candidates, archive_members, unrelated_member

    def test_builds_six_separate_checksum_gated_pack11_profiles(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            (
                project, workspace, reports, quartet, gust_pak, archive, installed_sha,
                helper, candidates, archive_members, unrelated_member,
            ) = self._prepare(Path(temporary))
            output, summary = MODULE.prepare_presentation_event_subset_repack_tests(
                project_root=project,
                quartet_root=quartet,
                gust_pak=gust_pak,
                workspace_root=workspace,
                report_root=reports,
                timeout_seconds=30,
            )
            self.assertTrue(output.is_file())
            self.assertEqual(summary["profile_rows"], 6)
            self.assertEqual(summary["file_rows"], 6)
            self.assertEqual(summary["validation_failures"], 0)
            self.assertEqual(BR.sha256_file(archive), installed_sha)
            self.assertFalse(any(path.suffix.casefold() == ".pak" for path in (reports / MODULE.EVIDENCE_DIR_NAME).rglob("*")))

            final_root = workspace / MODULE.FINAL_BUILD_SUBDIR
            for profile_id, member in MODULE.EXPECTED_PROFILE_MEMBERS.items():
                output_pak = final_root / "profiles" / profile_id / "output/Data/PACK11.PAK"
                self.assertTrue(output_pak.is_file())
                self.assertEqual(helper._read_fake_pak_member(output_pak, member), candidates[profile_id])
                self.assertEqual(
                    helper._read_fake_pak_member(output_pak, unrelated_member),
                    b"current-translation-must-survive",
                )
                for other_profile, other_member in MODULE.EXPECTED_PROFILE_MEMBERS.items():
                    if other_profile != profile_id:
                        self.assertEqual(
                            helper._read_fake_pak_member(output_pak, other_member),
                            archive_members[other_member],
                        )
                profile = json.loads((final_root / "profiles" / profile_id / "PROFILE.json").read_text(encoding="utf-8"))
                self.assertEqual(profile["type"], "br_quartet_restoration_local_presentation_event_subset_repack_test_profile")
                self.assertEqual(profile["replaced_member_count"], 1)
                self.assertFalse(profile["runtime_validated"])

    def test_rejects_failed_stage45_gate_before_repack(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project, workspace, reports, quartet, gust_pak, *_ = self._prepare(
                Path(temporary), corrupt_validation=True,
            )
            with self.assertRaises(MODULE.PresentationSubsetRepackError):
                MODULE.prepare_presentation_event_subset_repack_tests(
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
