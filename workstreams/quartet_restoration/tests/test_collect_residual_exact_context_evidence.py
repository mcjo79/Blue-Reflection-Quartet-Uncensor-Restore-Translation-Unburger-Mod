#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import hashlib
import json
import shutil
import struct
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
TOOL_PATH = ROOT / "workstreams/quartet_restoration/collect_residual_exact_context_evidence.py"
SPEC = importlib.util.spec_from_file_location("collect_residual_exact_context_evidence", TOOL_PATH)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)

BR_SPEC = importlib.util.spec_from_file_location(
    "br_restoration_tool", ROOT / "Blue_Reflection_Text_Tool/br_restoration_tool.py"
)
assert BR_SPEC and BR_SPEC.loader
BR = importlib.util.module_from_spec(BR_SPEC)
sys.modules[BR_SPEC.name] = BR
BR_SPEC.loader.exec_module(BR)


def payload(words: list[int]) -> bytes:
    def lp(raw: bytes) -> bytes:
        return struct.pack("<I", len(raw)) + raw

    prefix = struct.pack("<II", 3, 0) + lp(b"name\0") + lp("説明".encode("cp932") + b"\0")
    return prefix + struct.pack(f"<{len(words)}I", *words)


class ResidualExactContextTests(unittest.TestCase):
    def test_route_controls_block_promotion(self) -> None:
        classification, gate, reason = MODULE.classify_promotion_gate(
            cue_occurrences=2,
            noncue_occurrences=3,
            route_family_count=1,
            shared_cue_noncue_archetypes=1,
            splice_rows=5,
            isolated_splice_rows=5,
        )
        self.assertEqual(classification, "route_state_or_schema_behavior_more_likely")
        self.assertEqual(gate, "not_eligible_for_stage_36")
        self.assertIn("non-cue", reason)

    def test_cue_only_cross_route_isolated_shape_can_reach_stage36_review(self) -> None:
        classification, gate, _ = MODULE.classify_promotion_gate(
            cue_occurrences=2,
            noncue_occurrences=0,
            route_family_count=2,
            shared_cue_noncue_archetypes=0,
            splice_rows=2,
            isolated_splice_rows=2,
        )
        self.assertEqual(classification, "shared_presentation_exact_span_prototype_candidate")
        self.assertEqual(gate, "eligible_for_stage_36_local_prototype_review")

    def test_context_comparison_detects_shared_cue_noncue_archetype(self) -> None:
        rows = MODULE.build_context_comparisons([
            {
                "shape_id": "shape",
                "normalized_path": "event/event_jp/te02/event_te02_180.ebd",
                "occurrence_index": "0",
                "cue_positive_occurrence": "True",
                "cue_domains": "shower",
                "pair_context_archetype_id": "same",
                "source_context_signature_sha256": "src",
                "target_context_signature_sha256": "dst",
            },
            {
                "shape_id": "shape",
                "normalized_path": "event/event_jp/te02/event_te02_170.ebd",
                "occurrence_index": "0",
                "cue_positive_occurrence": "False",
                "cue_domains": "",
                "pair_context_archetype_id": "same",
                "source_context_signature_sha256": "src",
                "target_context_signature_sha256": "dst",
            },
        ])
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["comparison_kind"], "cue_vs_noncue_control")
        self.assertTrue(rows[0]["same_exact_pair_context_archetype"])
        self.assertTrue(rows[0]["same_route_family"])

    def test_exact_inverse_splice_removes_only_selected_shape(self) -> None:
        source = payload([
            1, 0x75400009, 0x70000001, 0x77000001, 0x74200012, 0x7F000000,
        ])
        target = payload([
            1, 0x75400009, 0x70000001, 0x750000A3, 0x77000001, 0x74200012, 0x7F000000,
        ])
        source_header = BR.parse_ebd_header_schema(source)
        target_header = BR.parse_ebd_header_schema(target)
        source_profile = BR.profile_ebd_post_header_words(source, int(source_header["header_end"]))
        target_profile = BR.profile_ebd_post_header_words(target, int(target_header["header_end"]))
        delta = BR.compare_ebd_tag_atoms(source_profile["atoms"], target_profile["atoms"])[0]
        shape_id = BR.event_residual_delta_shape_id(delta)
        source_start, source_end = BR.event_atom_word_span(
            source_profile["atoms"], int(delta["source_atom_start"]), int(delta["source_atom_end"]),
            int(source_profile["word_count"]),
        )
        target_start, target_end = BR.event_atom_word_span(
            target_profile["atoms"], int(delta["target_atom_start"]), int(delta["target_atom_end"]),
            int(target_profile["word_count"]),
        )
        result = MODULE.simulate_exact_inverse_splice(
            br=BR,
            source_payload=source,
            target_payload=target,
            occurrence={
                "shape_id": shape_id,
                "source_span_start_word_index": source_start,
                "source_span_end_word_index": source_end,
                "target_span_start_word_index": target_start,
                "target_span_end_word_index": target_end,
            },
        )
        self.assertEqual(result["splice_status"], "isolated_exact_inverse_splice_passed")
        self.assertTrue(result["selected_occurrence_removed"])
        self.assertTrue(result["other_residual_shape_counter_unchanged"])
        self.assertEqual(result["candidate_byte_difference_to_source"], 0)
        self.assertTrue(result["target_header_preserved"])
        self.assertTrue(result["target_trailing_bytes_preserved"])


    def test_collect_stage_writes_metadata_only_report(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary)
            tool_dir = project / "Blue_Reflection_Text_Tool"
            tool_dir.mkdir(parents=True)
            shutil.copy2(ROOT / "Blue_Reflection_Text_Tool/br_restoration_tool.py", tool_dir / "br_restoration_tool.py")
            reports = project / ".local/reports/quartet_restoration"
            workspace = project / ".local/build/quartet_restoration"
            stage34 = reports / MODULE.STAGE34_DIR
            context = reports / MODULE.CONTEXT_DIR
            migration = reports / MODULE.MIGRATION_DIR
            differences = reports / "differences"
            for directory in (stage34, context, migration, differences):
                directory.mkdir(parents=True, exist_ok=True)

            source = payload([1, 0x75400009, 0x77000001, 0x7F000000])
            target = payload([1, 0x75400009, 0x750000A3, 0x77000001, 0x7F000000])
            sh = BR.parse_ebd_header_schema(source)
            th = BR.parse_ebd_header_schema(target)
            sp = BR.profile_ebd_post_header_words(source, int(sh["header_end"]))
            tp = BR.profile_ebd_post_header_words(target, int(th["header_end"]))
            delta = BR.compare_ebd_tag_atoms(sp["atoms"], tp["atoms"])[0]
            shape_id = BR.event_residual_delta_shape_id(delta)
            source_start, source_end = BR.event_atom_word_span(
                sp["atoms"], int(delta["source_atom_start"]), int(delta["source_atom_end"]), int(sp["word_count"])
            )
            target_start, target_end = BR.event_atom_word_span(
                tp["atoms"], int(delta["target_atom_start"]), int(delta["target_atom_end"]), int(tp["word_count"])
            )
            path = "event/event_jp/ce11/event_ce11_070.ebd"
            source_item = {
                "archive": "DATA/PACK01.PAK", "path": path, "normalized_path": path,
                "size": len(source), "sha256": hashlib.sha256(source).hexdigest(),
                "extension": ".ebd", "asset_type": "event_data", "magic_hex": source[:8].hex(),
            }
            target_internal = "event/b1/event_jp/ce11/event_ce11_070.ebd"
            target_item = {
                "archive": "Data/PACK11.PAK", "path": target_internal, "normalized_path": path,
                "size": len(target), "sha256": hashlib.sha256(target).hexdigest(),
                "extension": ".ebd", "asset_type": "event_data", "magic_hex": target[:8].hex(),
            }
            BR.atomic_json(differences / "br1_events.json", {
                "source_archive_group": "br1_events",
                "entries": [{
                    "classification": "changed", "scope_status": "in_scope", "normalized_path": path,
                    "source": BR.file_ref(source_item), "target": BR.file_ref(target_item),
                }],
            })
            for side, item, raw in (("source", source_item, source), ("target", target_item, target)):
                out = BR.inventory_workspace_file(workspace, side, "br1_events", item["archive"], item["path"])
                out.parent.mkdir(parents=True, exist_ok=True)
                out.write_bytes(raw)

            (stage34 / "SUMMARY.json").write_text(json.dumps({
                "type": "br_quartet_restoration_residual_scene_context_evidence_summary",
                "tool_version": "0.0.40",
            }), encoding="utf-8")
            BR.write_tsv(stage34 / "RESIDUAL_ROUTE_AND_SHARED_COHORTS.tsv", [
                "shape_id", "classification", "review_priority", "sequence_tag", "source_tag_values",
                "target_tag_values", "unresolved_events", "cue_domains", "support_file_count",
                "same_route_file_count", "other_route_file_count", "route_family_count", "cue_file_count",
                "context_archetype_count", "promoted_profile_ids",
            ], [
                {
                    "shape_id": shape_id, "classification": "shared_presentation_candidate", "review_priority": "high",
                    "sequence_tag": "insert", "source_tag_values": "", "target_tag_values": "0x750000a3",
                    "unresolved_events": path, "cue_domains": "steam_or_vapor", "support_file_count": 1,
                    "same_route_file_count": 1, "other_route_file_count": 0, "route_family_count": 1,
                    "cue_file_count": 1, "context_archetype_count": 1, "promoted_profile_ids": "",
                },
                {
                    "shape_id": "parked", "classification": "already_covered_by_existing_local_profile",
                    "review_priority": "parked", "sequence_tag": "delete", "source_tag_values": "x",
                    "target_tag_values": "", "unresolved_events": path, "cue_domains": "shower",
                    "support_file_count": 1, "same_route_file_count": 1, "other_route_file_count": 0,
                    "route_family_count": 1, "cue_file_count": 1, "context_archetype_count": 1,
                    "promoted_profile_ids": "profile",
                },
            ])
            (context / "SUMMARY.json").write_text(json.dumps({
                "type": "br_quartet_restoration_event_delta_context_evidence_summary",
                "tool_version": "0.0.27",
            }), encoding="utf-8")
            BR.write_tsv(context / "EVENT_DELTA_CONTEXT_OCCURRENCES.tsv", [
                "normalized_path", "shape_id", "occurrence_index", "cue_positive_occurrence", "cue_domains",
                "pair_context_archetype_id", "source_span_start_word_index", "source_span_end_word_index",
                "target_span_start_word_index", "target_span_end_word_index", "source_before_structural_tokens",
                "source_delta_structural_tokens", "source_after_structural_tokens", "target_before_structural_tokens",
                "target_delta_structural_tokens", "target_after_structural_tokens", "source_context_signature_sha256",
                "target_context_signature_sha256",
            ], [{
                "normalized_path": path, "shape_id": shape_id, "occurrence_index": 0,
                "cue_positive_occurrence": True, "cue_domains": "steam_or_vapor",
                "pair_context_archetype_id": "arch", "source_span_start_word_index": source_start,
                "source_span_end_word_index": source_end, "target_span_start_word_index": target_start,
                "target_span_end_word_index": target_end, "source_before_structural_tokens": "T7540:0009",
                "source_delta_structural_tokens": "", "source_after_structural_tokens": "T7700:0001",
                "target_before_structural_tokens": "T7540:0009", "target_delta_structural_tokens": "T7500:00a3",
                "target_after_structural_tokens": "T7700:0001", "source_context_signature_sha256": "s",
                "target_context_signature_sha256": "t",
            }])
            (migration / "SUMMARY.json").write_text(json.dumps({
                "type": "br_quartet_restoration_event_tag_migration_evidence_summary",
                "tool_version": "0.0.24",
            }), encoding="utf-8")
            BR.write_tsv(migration / "EVENT_TAG_SCHEMA_MIGRATION_CANDIDATES.tsv", [
                "sequence_tag", "source_atom_count", "target_atom_count", "source_tag_values",
                "target_tag_values", "classification",
            ], [])

            old_targets, old_parked, old_profile = MODULE.TARGET_SHAPES, MODULE.PARKED_SHAPE, MODULE.PARKED_PROFILE
            try:
                MODULE.TARGET_SHAPES = {shape_id: {
                    "stage34_classification": "shared_presentation_candidate",
                    "expected_events": path,
                    "expected_domains": "steam_or_vapor",
                }}
                MODULE.PARKED_SHAPE = "parked"
                MODULE.PARKED_PROFILE = "profile"
                output, summary = MODULE.collect_residual_exact_context_evidence(
                    project_root=project, workspace_root=workspace, report_root=reports,
                )
            finally:
                MODULE.TARGET_SHAPES = old_targets
                MODULE.PARKED_SHAPE = old_parked
                MODULE.PARKED_PROFILE = old_profile
            self.assertTrue(output.is_file())
            self.assertEqual(summary["target_shape_rows"], 1)
            self.assertEqual(summary["isolated_in_memory_splice_rows"], 1)
            self.assertEqual(summary["stage36_eligible_shape_rows"], 0)
            self.assertFalse((workspace / "prototypes").exists())
            evidence = reports / MODULE.EVIDENCE_DIR_NAME
            self.assertTrue((evidence / "RESIDUAL_IN_MEMORY_SPLICE_VALIDATION.tsv").is_file())
            self.assertNotIn("説明", (evidence / "SUMMARY.json").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
