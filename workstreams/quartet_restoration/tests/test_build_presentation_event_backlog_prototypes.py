from __future__ import annotations

import csv
import hashlib
import importlib.util
import json
import struct
import subprocess
import sys
import tempfile
import unittest
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
TOOL_PATH = ROOT / "workstreams/quartet_restoration/build_presentation_event_backlog_prototypes.py"
SPEC = importlib.util.spec_from_file_location("build_presentation_event_backlog_prototypes", TOOL_PATH)
assert SPEC and SPEC.loader
TOOL = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = TOOL
SPEC.loader.exec_module(TOOL)

BR_SPEC = importlib.util.spec_from_file_location(
    "br_restoration_tool_fixture", ROOT / "Blue_Reflection_Text_Tool/br_restoration_tool.py"
)
assert BR_SPEC and BR_SPEC.loader
BR = importlib.util.module_from_spec(BR_SPEC)
sys.modules[BR_SPEC.name] = BR
BR_SPEC.loader.exec_module(BR)


def write_tsv(path: Path, fieldnames: list[str], rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def payload(words: list[int]) -> bytes:
    def lp(raw: bytes) -> bytes:
        return struct.pack("<I", len(raw)) + raw
    prefix = struct.pack("<II", 3, 0) + lp(b"name\0") + lp("説明".encode("cp932") + b"\0")
    return prefix + struct.pack(f"<{len(words)}I", *words)


def file_ref(path: str, archive: str, data: bytes) -> dict[str, object]:
    return {
        "archive": archive,
        "path": path,
        "normalized_path": path,
        "size": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
    }


class PresentationBacklogPrototypeTests(unittest.TestCase):
    def build_fixture(self, root: Path) -> tuple[Path, Path, Path, list[str]]:
        project = root / "project"
        workspace = project / ".local/build/quartet_restoration"
        reports = project / ".local/reports/quartet_restoration"
        (project / "Blue_Reflection_Text_Tool").mkdir(parents=True)
        # The stage imports the real project restoration tool.  A symlink keeps the
        # fixture small while preserving normal import behavior.
        (project / "Blue_Reflection_Text_Tool/br_restoration_tool.py").symlink_to(
            ROOT / "Blue_Reflection_Text_Tool/br_restoration_tool.py"
        )
        reports.mkdir(parents=True)
        (reports / "differences").mkdir()

        context = reports / "event_delta_context_evidence"
        composite = reports / "single_scene_composite_evidence"
        backlog = reports / "presentation_event_backlog_evidence"
        for directory in (context, composite, backlog):
            directory.mkdir()

        (context / "SUMMARY.json").write_text(json.dumps({
            "type": "br_quartet_restoration_event_delta_context_evidence_summary",
            "tool_version": "0.0.28",
        }), encoding="utf-8")
        (composite / "SUMMARY.json").write_text(json.dumps({
            "type": "br_quartet_restoration_single_scene_composite_evidence_summary",
            "tool_version": "0.0.35",
        }), encoding="utf-8")

        event_paths = [
            "event/event_jp/ce07/event_ce07_060.ebd",
            "event/event_jp/em01/event_em01_050.ebd",
        ]
        fixture_rows: list[dict[str, object]] = []
        occurrence_rows: list[dict[str, object]] = []
        stage23_splice_rows: list[dict[str, object]] = []
        control_rows: list[dict[str, object]] = []
        composite_event_rows: list[dict[str, object]] = []
        composite_splice_rows: list[dict[str, object]] = []
        composite_residual_rows: list[dict[str, object]] = []
        backlog_rows: list[dict[str, object]] = []
        group_rows: list[dict[str, object]] = []
        difference_entries: list[dict[str, object]] = []

        cases = [
            (
                event_paths[0],
                [1, 0x75400009, 0x74100013, 0x7F000000,
                 1, 0x7540000A, 0x75100001, 0x7F000000,
                 1, 0x7540000B, 0x75200001, 0x7F000000],
                [1, 0x75400009, 0x74100013, 0x74100014, 0x7F000000,
                 1, 0x7540000A, 0x75100001, 0x7500002C, 0x7F000000,
                 1, 0x7540000B, 0x75200001, 0x75300077, 0x7F000000],
                2,
                "costume_or_coverage",
                "profile_ce07_fixture",
            ),
            (
                event_paths[1],
                [1, 0x75400009, 0x74100013, 0x7F000000,
                 1, 0x7540000A, 0x75100001, 0x7F000000,
                 1, 0x7540000B, 0x75200001, 0x7F000000,
                 1, 0x7540000C, 0x75300001, 0x7F000000],
                [1, 0x75400009, 0x74100013, 0x74100014, 0x7F000000,
                 1, 0x7540000A, 0x75100001, 0x7500002C, 0x7F000000,
                 1, 0x7540000B, 0x75200001, 0x75200044, 0x7F000000,
                 1, 0x7540000C, 0x75300001, 0x75400088, 0x7F000000],
                3,
                "pool_or_swimming;water_visibility",
                "profile_em01_fixture",
            ),
        ]

        for order, (normalized, source_words, target_words, selected_count, domains, profile_id) in enumerate(cases, 1):
            source = payload(source_words)
            target = payload(target_words)
            sh = BR.parse_ebd_header_schema(source)
            th = BR.parse_ebd_header_schema(target)
            sp = BR.profile_ebd_post_header_words(source, int(sh["header_end"]))
            tp = BR.profile_ebd_post_header_words(target, int(th["header_end"]))
            deltas = BR.compare_ebd_tag_atoms(sp["atoms"], tp["atoms"])
            self.assertGreaterEqual(len(deltas), selected_count + 1)
            selected = []
            per_shape: Counter[str] = Counter()
            for delta in deltas[:selected_count]:
                shape_id = BR.event_residual_delta_shape_id(delta)
                occurrence_index = per_shape[shape_id]
                per_shape[shape_id] += 1
                row = {
                    "normalized_path": normalized,
                    "shape_id": shape_id,
                    "occurrence_index": occurrence_index,
                    "cue_positive_occurrence": True,
                    "cue_domains": domains,
                    "selection_reasons": "domain_single_scene_context_shape",
                }
                selected.append(row)
                occurrence_rows.append(row)
                individual = BR.simulate_inverse_event_delta_splice(
                    source_payload=source,
                    target_payload=target,
                    source_header=sh,
                    target_header=th,
                    source_profile=sp,
                    target_profile=tp,
                    delta=delta,
                    shape_id=shape_id,
                )
                stage23_splice_rows.append({
                    **row,
                    "candidate_sha256": individual["candidate_sha256"],
                    "in_memory_splice_status": "selected_shape_removed_without_other_coarse_delta_changes",
                })
                control_rows.append({
                    "shape_id": shape_id,
                    "shared_cue_noncue_context_archetype_count": 0,
                })

            candidate, metadata, residuals = BR.construct_composite_inverse_event_candidate(
                source_payload=source, target_payload=target, selected_occurrences=selected
            )
            assert candidate is not None
            self.assertTrue(metadata["all_selected_shapes_removed"])
            self.assertGreater(len(residuals), 0)

            source_member = normalized
            target_member = "event/b1/" + normalized[len("event/"):]
            source_ref = file_ref(source_member, "DATA/PACK01.PAK", source)
            target_ref = file_ref(target_member, "Data/PACK11.PAK", target)
            target_ref["normalized_path"] = normalized
            difference_entries.append({
                "classification": "changed",
                "scope_status": "in_scope",
                "normalized_path": normalized,
                "source": source_ref,
                "target": target_ref,
            })
            for side, ref, data in (("source", source_ref, source), ("target", target_ref, target)):
                out = BR.inventory_workspace_file(workspace, side, "br1_events", str(ref["archive"]), str(ref["path"]))
                out.parent.mkdir(parents=True, exist_ok=True)
                out.write_bytes(data)

            composite_event_rows.append({
                "normalized_path": normalized,
                "candidate_sha256": metadata["candidate_sha256"],
                "candidate_size": metadata["candidate_size"],
                "operation_count": metadata["operation_count"],
                "unknown_residual_rows": len(residuals),
                "classification": "selected_single_scene_shapes_removed_unknown_residuals_remain",
            })
            for row, stage23 in zip(selected, stage23_splice_rows[-selected_count:]):
                composite_splice_rows.append({
                    "normalized_path": normalized,
                    "shape_id": row["shape_id"],
                    "occurrence_index": row["occurrence_index"],
                    "stage23_candidate_sha256": stage23["candidate_sha256"],
                    "composite_candidate_sha256": metadata["candidate_sha256"],
                })
            for residual in residuals:
                composite_residual_rows.append({"normalized_path": normalized, **residual})

            all_shape_ids = sorted({BR.event_residual_delta_shape_id(delta) for delta in deltas})
            backlog_rows.append({
                "normalized_path": normalized,
                "event_id": Path(normalized).stem.removeprefix("event_"),
                "route_family": Path(normalized).parent.name,
                "cue_domains": domains,
                "shape_ids": ";".join(all_shape_ids),
                "composite_candidate_sha256": metadata["candidate_sha256"],
                "unknown_residual_shapes": len(residuals),
                "existing_profile_ids": "",
                "classification": "isolated_cue_inverse_splice_candidate",
                "safe_to_build_local_profile_without_runtime": True,
            })
            group_rows.append({
                "group_order": order,
                "proposed_profile_id": profile_id,
                "group_type": "single_scene_multi_shape",
                "route_family": Path(normalized).parent.name,
                "event_count": 1,
                "event_paths": normalized,
                "shape_count": len(all_shape_ids),
                "shape_ids": ";".join(all_shape_ids),
                "cue_domains": domains,
                "build_mode": "reconstruct_exact_selected_spans_as_one_scene_profile",
                "requires_exact_hash_roundtrip": True,
                "requires_other_shape_counter_preservation": True,
                "repack_separately": True,
                "register_inactive": True,
                "runtime_test_deferred": True,
            })

        BR.atomic_json(reports / "differences/br1_events.json", {
            "source_archive_group": "br1_events",
            "entries": difference_entries,
        })
        write_tsv(context / "EVENT_DELTA_CONTEXT_OCCURRENCES.tsv", [
            "normalized_path", "shape_id", "occurrence_index", "cue_positive_occurrence",
            "cue_domains", "selection_reasons",
        ], occurrence_rows)
        write_tsv(context / "IN_MEMORY_EVENT_DELTA_SPLICE_READINESS.tsv", [
            "normalized_path", "shape_id", "occurrence_index", "cue_positive_occurrence",
            "cue_domains", "selection_reasons", "candidate_sha256", "in_memory_splice_status",
        ], stage23_splice_rows)
        write_tsv(context / "EVENT_DELTA_CUE_NONCUE_COMPARISON.tsv", [
            "shape_id", "shared_cue_noncue_context_archetype_count",
        ], control_rows)
        write_tsv(composite / "SINGLE_SCENE_COMPOSITE_EVENTS.tsv", [
            "normalized_path", "candidate_sha256", "candidate_size", "operation_count",
            "unknown_residual_rows", "classification",
        ], composite_event_rows)
        write_tsv(composite / "SINGLE_SCENE_COMPOSITE_SPLICES.tsv", [
            "normalized_path", "shape_id", "occurrence_index", "stage23_candidate_sha256",
            "composite_candidate_sha256",
        ], composite_splice_rows)
        write_tsv(composite / "SINGLE_SCENE_COMPOSITE_RESIDUALS.tsv", [
            "normalized_path", "shape_id", "sequence_tag", "source_atom_count",
            "target_atom_count", "source_tag_values", "target_tag_values", "classification",
        ], composite_residual_rows)
        write_tsv(backlog / "EVENT_CANDIDATE_BACKLOG.tsv", [
            "normalized_path", "event_id", "route_family", "cue_domains", "shape_ids",
            "composite_candidate_sha256", "unknown_residual_shapes", "existing_profile_ids",
            "classification", "safe_to_build_local_profile_without_runtime",
        ], backlog_rows)
        write_tsv(backlog / "EVENT_CANDIDATE_BUILD_GROUPS.tsv", [
            "group_order", "proposed_profile_id", "group_type", "route_family", "event_count",
            "event_paths", "shape_count", "shape_ids", "cue_domains", "build_mode",
            "requires_exact_hash_roundtrip", "requires_other_shape_counter_preservation",
            "repack_separately", "register_inactive", "runtime_test_deferred",
        ], group_rows)
        (backlog / "SUMMARY.json").write_text(json.dumps({
            "type": "br_quartet_restoration_presentation_event_backlog_evidence_summary",
            "tool_version": "0.0.46",
            "status": "possible_presentation_events_consolidated_runtime_testing_deferred",
            "runtime_testing_deferred": True,
            "proposed_build_group_rows": 2,
            "safe_static_build_event_rows": 2,
        }), encoding="utf-8")
        return project, workspace, reports, event_paths

    def test_builds_two_separate_profiles_and_metadata_only_report(self):
        with tempfile.TemporaryDirectory() as temporary:
            project, workspace, reports, event_paths = self.build_fixture(Path(temporary))
            output, summary = TOOL.build_prototypes(
                project_root=project,
                workspace_root=workspace,
                report_root=reports,
                maximum_event_bytes=1024 * 1024,
            )
            self.assertTrue(output.is_file())
            self.assertEqual(summary["proposed_group_rows"], 2)
            self.assertEqual(summary["promoted_profile_rows"], 2)
            self.assertEqual(summary["prototype_file_rows"], 2)
            self.assertEqual(summary["validation_failures"], 0)
            self.assertEqual(summary["skipped_rows"], 0)
            profiles = read_rows(reports / TOOL.EVIDENCE_DIR_NAME / "PRESENTATION_EVENT_BACKLOG_PROFILES.tsv")
            self.assertEqual({row["profile_id"] for row in profiles}, {"profile_ce07_fixture", "profile_em01_fixture"})
            self.assertEqual(len(list((workspace / TOOL.PROTOTYPE_SUBDIR).rglob("*.ebd"))), 2)
            listing = subprocess.run(
                ["tar", "--zstd", "-tf", str(output)], text=True, capture_output=True, check=True
            ).stdout.casefold()
            self.assertNotIn(".ebd", listing)
            self.assertNotIn(".pak", listing)
            for path in event_paths:
                self.assertNotIn(Path(path).name.casefold(), listing)

    def test_accepts_legacy_blank_stage29_component_hashes_after_payload_revalidation(self):
        with tempfile.TemporaryDirectory() as temporary:
            project, workspace, reports, _ = self.build_fixture(Path(temporary))
            splice_path = reports / "single_scene_composite_evidence/SINGLE_SCENE_COMPOSITE_SPLICES.tsv"
            rows = read_rows(splice_path)
            for row in rows:
                row["stage23_candidate_sha256"] = ""
            write_tsv(splice_path, list(rows[0]), rows)

            _, summary = TOOL.build_prototypes(
                project_root=project,
                workspace_root=workspace,
                report_root=reports,
                maximum_event_bytes=1024 * 1024,
            )
            self.assertEqual(summary["promoted_profile_rows"], 2)
            self.assertEqual(summary["validation_failures"], 0)
            self.assertEqual(summary["legacy_blank_stage29_component_hash_rows"], 5)
            self.assertEqual(summary["single_splice_payload_revalidation_rows"], 5)
            selected = read_rows(
                reports / TOOL.EVIDENCE_DIR_NAME / "PRESENTATION_EVENT_BACKLOG_SELECTED_SPLICES.tsv"
            )
            self.assertEqual(len(selected), 5)
            self.assertTrue(all(
                row["component_hash_validation_status"] == "legacy_stage29_blank_revalidated_from_ebd"
                for row in selected
            ))

    def test_rejects_nonblank_stage29_component_hash_mismatch(self):
        with tempfile.TemporaryDirectory() as temporary:
            project, workspace, reports, _ = self.build_fixture(Path(temporary))
            splice_path = reports / "single_scene_composite_evidence/SINGLE_SCENE_COMPOSITE_SPLICES.tsv"
            rows = read_rows(splice_path)
            rows[0]["stage23_candidate_sha256"] = "0" * 64
            write_tsv(splice_path, list(rows[0]), rows)

            _, summary = TOOL.build_prototypes(
                project_root=project,
                workspace_root=workspace,
                report_root=reports,
                maximum_event_bytes=1024 * 1024,
            )
            self.assertEqual(summary["promoted_profile_rows"], 1)
            self.assertGreaterEqual(summary["validation_failures"], 1)
            skipped = read_rows(
                reports / TOOL.EVIDENCE_DIR_NAME / "PRESENTATION_EVENT_BACKLOG_BUILD_SKIPPED.tsv"
            )
            self.assertTrue(any(
                row["reason"] == "one_or_more_selected_splice_inputs_failed"
                for row in skipped
            ))

    def test_rejects_corrupted_stage23_hash_when_stage29_field_is_blank(self):
        with tempfile.TemporaryDirectory() as temporary:
            project, workspace, reports, _ = self.build_fixture(Path(temporary))
            stage29_path = reports / "single_scene_composite_evidence/SINGLE_SCENE_COMPOSITE_SPLICES.tsv"
            stage29_rows = read_rows(stage29_path)
            for row in stage29_rows:
                row["stage23_candidate_sha256"] = ""
            write_tsv(stage29_path, list(stage29_rows[0]), stage29_rows)

            stage23_path = reports / "event_delta_context_evidence/IN_MEMORY_EVENT_DELTA_SPLICE_READINESS.tsv"
            stage23_rows = read_rows(stage23_path)
            stage23_rows[0]["candidate_sha256"] = "f" * 64
            write_tsv(stage23_path, list(stage23_rows[0]), stage23_rows)

            _, summary = TOOL.build_prototypes(
                project_root=project,
                workspace_root=workspace,
                report_root=reports,
                maximum_event_bytes=1024 * 1024,
            )
            self.assertEqual(summary["promoted_profile_rows"], 1)
            self.assertGreaterEqual(summary["validation_failures"], 1)
            skipped = read_rows(
                reports / TOOL.EVIDENCE_DIR_NAME / "PRESENTATION_EVENT_BACKLOG_BUILD_SKIPPED.tsv"
            )
            self.assertTrue(any(
                row["reason"] == "one_or_more_stage23_splices_failed_payload_reconstruction"
                for row in skipped
            ))

    def test_rejects_group_already_covered_by_profile(self):
        with tempfile.TemporaryDirectory() as temporary:
            project, workspace, reports, _ = self.build_fixture(Path(temporary))
            backlog_path = reports / "presentation_event_backlog_evidence/EVENT_CANDIDATE_BACKLOG.tsv"
            rows = read_rows(backlog_path)
            rows[0]["existing_profile_ids"] = "already_registered"
            write_tsv(backlog_path, list(rows[0]), rows)
            with self.assertRaisesRegex(TOOL.BacklogPrototypeError, "already covered"):
                TOOL.build_prototypes(project_root=project, workspace_root=workspace, report_root=reports)


def read_rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return [dict(row) for row in csv.DictReader(handle, delimiter="\t")]


if __name__ == "__main__":
    unittest.main()
