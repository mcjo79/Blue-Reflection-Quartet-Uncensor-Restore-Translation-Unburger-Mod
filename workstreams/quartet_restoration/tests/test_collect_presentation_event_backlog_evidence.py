from __future__ import annotations

import csv
import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
TOOL_PATH = ROOT / "workstreams/quartet_restoration/collect_presentation_event_backlog_evidence.py"
SPEC = importlib.util.spec_from_file_location("collect_presentation_event_backlog_evidence", TOOL_PATH)
assert SPEC and SPEC.loader
TOOL = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = TOOL
SPEC.loader.exec_module(TOOL)


def write_tsv(path: Path, fieldnames: list[str], rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def write_summary(path: Path, type_name: str, tool_version: str = "fixture") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"type": type_name, "tool_version": tool_version}), encoding="utf-8")


class PresentationEventBacklogTests(unittest.TestCase):
    def test_registered_profile_is_parked(self):
        classification, priority, next_gate, safe = TOOL.classify_candidate({"existing_profile_ids": "profile-x"})
        self.assertEqual(classification, "registered_inactive_profile")
        self.assertEqual(priority, "parked")
        self.assertFalse(safe)
        self.assertIn("already_built", next_gate)

    def test_static_composite_candidate_is_buildable_without_runtime(self):
        classification, priority, _, safe = TOOL.classify_candidate({
            "composite_classification": "exact_original_payload_match_after_composite_inverse",
            "composite_next_gate": "eligible_for_separate_local_single_scene_prototype_review",
        })
        self.assertEqual(classification, "static_composite_candidate_ready_for_local_profile")
        self.assertEqual(priority, "critical")
        self.assertTrue(safe)

    def test_isolated_cue_splice_requires_no_shared_control_context(self):
        good = TOOL.classify_candidate({
            "isolated_cue_splice_count": 1,
            "shared_cue_noncue_context_count": 0,
            "context_priority": "high",
        })
        bad = TOOL.classify_candidate({
            "isolated_cue_splice_count": 1,
            "shared_cue_noncue_context_count": 1,
            "rare_residual_regions": 1,
        })
        self.assertEqual(good[0], "isolated_cue_inverse_splice_candidate")
        self.assertTrue(good[3])
        self.assertNotEqual(bad[0], "isolated_cue_inverse_splice_candidate")
        self.assertFalse(bad[3])

    def build_fixture(self, root: Path, *, activation_authorized: bool = False) -> tuple[Path, Path]:
        project_root = root / "project"
        report_root = project_root / ".local/reports/quartet_restoration"
        registry = project_root / ".local/build/quartet_restoration/core_profiles/generated"
        registry.mkdir(parents=True)
        report_root.mkdir(parents=True)

        registered_path = "event/event_jp/dd01/event_dd01_400.ebd"
        manifest = {
            "schema_version": 1,
            "profile_id": "registered_event_profile",
            "target_relative_path": "Data/PACK11.PAK",
            "changed_members": ["event/b1/event_jp/dd01/event_dd01_400.ebd"],
            "runtime_validated": False,
            "workstream_id": TOOL.WORKSTREAM_ID,
        }
        (registry / "registered_event_profile.json").write_text(json.dumps(manifest), encoding="utf-8")

        stage39 = report_root / "residual_shared_presentation_runtime_readiness"
        stage39.mkdir()
        (stage39 / "SUMMARY.json").write_text(json.dumps({
            "type": "br_quartet_restoration_residual_shared_presentation_runtime_readiness_summary",
            "tool_version": "0.0.45",
            "status": "profile_metadata_ready_activation_not_authorized_save_required",
            "open_transaction_rows": 0,
            "activation_authorized": activation_authorized,
            "runtime_validated": False,
        }), encoding="utf-8")

        cue = report_root / "event_scene_cue_evidence"
        write_tsv(cue / "FOCUSED_PRESENTATION_EVENT_REVIEW.tsv", [
            "normalized_path", "event_message_classification", "cue_rule_ids", "cue_domains",
            "rare_residual_regions", "compound_location_and_presentation_cue", "review_priority",
        ], [
            {"normalized_path": "event/event_jp/aa01/event_aa01_100.ebd", "event_message_classification": "identical", "cue_rule_ids": "shower", "cue_domains": "shower;steam_or_vapor", "rare_residual_regions": 1, "compound_location_and_presentation_cue": True, "review_priority": "high"},
            {"normalized_path": "event/event_jp/bb01/event_bb01_200.ebd", "event_message_classification": "identical", "cue_rule_ids": "bath", "cue_domains": "bath_or_hot_spring", "rare_residual_regions": 1, "compound_location_and_presentation_cue": True, "review_priority": "critical"},
            {"normalized_path": "event/event_jp/cc01/event_cc01_300.ebd", "event_message_classification": "identical", "cue_rule_ids": "wet", "cue_domains": "wet_fabric", "rare_residual_regions": 0, "compound_location_and_presentation_cue": False, "review_priority": "medium"},
            {"normalized_path": registered_path, "event_message_classification": "identical", "cue_rule_ids": "steam", "cue_domains": "steam_or_vapor", "rare_residual_regions": 1, "compound_location_and_presentation_cue": False, "review_priority": "high"},
        ])

        context = report_root / "event_delta_context_evidence"
        write_tsv(context / "EVENT_DELTA_CONTEXT_OCCURRENCES.tsv", [
            "normalized_path", "shape_id", "cue_positive_occurrence", "cue_domains",
        ], [
            {"normalized_path": "event/event_jp/aa01/event_aa01_100.ebd", "shape_id": "shape-a", "cue_positive_occurrence": True, "cue_domains": "shower;steam_or_vapor"},
        ])
        write_tsv(context / "IN_MEMORY_EVENT_DELTA_SPLICE_READINESS.tsv", [
            "normalized_path", "shape_id", "cue_positive_occurrence", "cue_domains", "in_memory_splice_status",
        ], [
            {"normalized_path": "event/event_jp/aa01/event_aa01_100.ebd", "shape_id": "shape-a", "cue_positive_occurrence": True, "cue_domains": "shower;steam_or_vapor", "in_memory_splice_status": "selected_shape_removed_without_other_coarse_delta_changes"},
        ])
        write_tsv(context / "EVENT_DELTA_CUE_NONCUE_COMPARISON.tsv", [
            "shape_id", "shared_cue_noncue_context_archetype_count",
        ], [{"shape_id": "shape-a", "shared_cue_noncue_context_archetype_count": 0}])
        write_tsv(context / "FOCUSED_EVENT_DELTA_CONTEXT_REVIEW.tsv", [
            "shape_id", "review_priority",
        ], [{"shape_id": "shape-a", "review_priority": "high"}])

        composite = report_root / "single_scene_composite_evidence"
        write_tsv(composite / "SINGLE_SCENE_COMPOSITE_EVENTS.tsv", [
            "normalized_path", "cue_domains", "classification", "candidate_sha256", "unknown_residual_rows", "review_priority",
        ], [{
            "normalized_path": "event/event_jp/bb01/event_bb01_200.ebd",
            "cue_domains": "bath_or_hot_spring",
            "classification": "exact_original_payload_match_after_composite_inverse",
            "candidate_sha256": "a" * 64,
            "unknown_residual_rows": 0,
            "review_priority": "critical",
        }])
        write_tsv(composite / "FOCUSED_SINGLE_SCENE_COMPOSITE_REVIEW.tsv", [
            "normalized_path", "cue_domains", "classification", "unknown_residual_rows", "review_priority", "next_gate",
        ], [{
            "normalized_path": "event/event_jp/bb01/event_bb01_200.ebd",
            "cue_domains": "bath_or_hot_spring",
            "classification": "exact_original_payload_match_after_composite_inverse",
            "unknown_residual_rows": 0,
            "review_priority": "critical",
            "next_gate": "eligible_for_separate_local_single_scene_prototype_review",
        }])

        residual = report_root / "residual_scene_context_evidence"
        write_tsv(residual / "FOCUSED_UNRESOLVED_SCENE_REVIEW.tsv", [
            "normalized_path", "cue_domains", "unknown_shape_count", "review_priority",
        ], [{"normalized_path": registered_path, "cue_domains": "steam_or_vapor", "unknown_shape_count": 1, "review_priority": "high"}])
        write_tsv(residual / "UNRESOLVED_SCENE_RESIDUAL_SHAPES.tsv", [
            "normalized_path", "shape_id", "cue_domains",
        ], [{"normalized_path": registered_path, "shape_id": "shape-d", "cue_domains": "steam_or_vapor"}])

        exact = report_root / "residual_exact_context_evidence"
        write_tsv(exact / "RESIDUAL_EXACT_CONTEXT_OCCURRENCES.tsv", [
            "normalized_path", "shape_id",
        ], [{"normalized_path": registered_path, "shape_id": "shape-d"}])
        write_tsv(exact / "RESIDUAL_SHAPE_PROMOTION_GATES.tsv", [
            "shape_id", "stage36_gate",
        ], [{"shape_id": "shape-d", "stage36_gate": "eligible_for_stage_36_local_prototype_review"}])

        event_proto = report_root / "event_prototype_evidence"
        write_tsv(event_proto / "EVENT_PROTOTYPE_PROFILES.tsv", ["profile_id", "shape_id"], [])
        single_proto = report_root / "single_scene_event_prototype_evidence"
        write_tsv(single_proto / "SINGLE_SCENE_EVENT_PROTOTYPE_PROFILES.tsv", ["profile_id", "shape_id"], [])

        # Direct report directories are preferred; summaries are not consumed by stage 40
        # except for stage 39, but adding them keeps fixtures representative.
        write_summary(cue / "SUMMARY.json", "br_quartet_restoration_event_scene_cue_evidence_summary")
        write_summary(context / "SUMMARY.json", "br_quartet_restoration_event_delta_context_evidence_summary")
        write_summary(composite / "SUMMARY.json", "br_quartet_restoration_single_scene_composite_evidence_summary")
        write_summary(residual / "SUMMARY.json", "br_quartet_restoration_residual_scene_context_evidence_summary")
        write_summary(exact / "SUMMARY.json", "br_quartet_restoration_residual_exact_context_evidence_summary")
        write_summary(event_proto / "SUMMARY.json", "br_quartet_restoration_event_prototype_evidence_summary")
        write_summary(single_proto / "SUMMARY.json", "br_quartet_restoration_single_scene_event_prototype_evidence_summary")
        return project_root, report_root

    def test_end_to_end_consolidates_and_groups_static_candidates(self):
        with tempfile.TemporaryDirectory() as temporary:
            project_root, report_root = self.build_fixture(Path(temporary))
            summary, tables = TOOL.build_backlog(project_root=project_root, report_root=report_root)
            self.assertEqual(summary["registry_profile_rows"], 1)
            self.assertEqual(summary["safe_static_build_event_rows"], 2)
            self.assertEqual(summary["registered_event_rows"], 1)
            self.assertEqual(summary["proposed_build_group_rows"], 2)
            classifications = {row["event_id"]: row["classification"] for row in tables["EVENT_CANDIDATE_BACKLOG.tsv"]}
            self.assertEqual(classifications["aa01_100"], "isolated_cue_inverse_splice_candidate")
            self.assertEqual(classifications["bb01_200"], "static_composite_candidate_ready_for_local_profile")
            self.assertEqual(classifications["dd01_400"], "registered_inactive_profile")

            report = TOOL.write_report(report_root=report_root, summary=summary, tables=tables, create_archive=True)
            assert report is not None
            listing = subprocess.run(["tar", "--zstd", "-tf", str(report)], text=True, capture_output=True, check=True).stdout
            self.assertIn("EVENT_CANDIDATE_BUILD_GROUPS.tsv", listing)
            self.assertNotIn(".PAK", listing)
            self.assertNotIn(".ebd", listing.casefold())

    def test_stage39_activation_authorization_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            project_root, report_root = self.build_fixture(Path(temporary), activation_authorized=True)
            with self.assertRaisesRegex(TOOL.BacklogError, "inactive and runtime-unvalidated"):
                TOOL.build_backlog(project_root=project_root, report_root=report_root)


if __name__ == "__main__":
    unittest.main()
