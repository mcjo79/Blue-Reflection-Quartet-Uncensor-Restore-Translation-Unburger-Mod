from __future__ import annotations

import csv
import hashlib
import importlib.util
import json
import os
import struct
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
TOOL_PATH = ROOT / "workstreams/quartet_restoration/collect_presentation_event_subset_search_evidence.py"
SPEC = importlib.util.spec_from_file_location("collect_presentation_event_subset_search_evidence", TOOL_PATH)
assert SPEC and SPEC.loader
TOOL = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = TOOL
SPEC.loader.exec_module(TOOL)

sys.path.insert(0, str(ROOT / "Blue_Reflection_Text_Tool"))
import br_restoration_tool as BR  # noqa: E402


def write_tsv(path: Path, fieldnames: list[str], rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def write_json(path: Path, data: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")


def lp(raw: bytes) -> bytes:
    return struct.pack("<I", len(raw)) + raw


def make_payload(words: list[int]) -> bytes:
    prefix = struct.pack("<II", 2, 0) + lp(b"name\0") + lp("説明".encode("cp932") + b"\0")
    return prefix + struct.pack(f"<{len(words)}I", *words)


class PresentationEventSubsetSearchTests(unittest.TestCase):
    def build_fixture(self, root: Path) -> tuple[Path, Path, str, list[str]]:
        project = root / "project"
        reports = project / ".local/reports/quartet_restoration"
        workspace = project / ".local/build/quartet_restoration"
        registry = workspace / "core_profiles/generated"
        registry.mkdir(parents=True)
        reports.mkdir(parents=True)
        os.symlink(ROOT / "Blue_Reflection_Text_Tool", project / "Blue_Reflection_Text_Tool", target_is_directory=True)

        candidate_path = "event/event_jp/aa01/event_aa01_100.ebd"
        registered_path = "event/event_jp/bb01/event_bb01_200.ebd"
        profile_ids = [
            "repeated_context_69adef108a_c90700a5a2",
            "route_sequence_te02_a570203aa6",
            "single_scene_event_te02_230_0143f9822b",
            "shared_presentation_d88c7c3a6f",
            "candidate_single_scene_multishape_em01_050_954fadd61cac",
            "height_fog_shader_original_code",
            "water_shader_swater_original_code",
        ]
        for index, profile_id in enumerate(profile_ids):
            pack11 = index < 5
            changed = ["event/b1/event_jp/bb01/event_bb01_200.ebd"] if index == 0 else []
            write_json(registry / f"{profile_id}.json", {
                "workstream_id": TOOL.WORKSTREAM_ID,
                "profile_id": profile_id,
                "target_relative_path": "Data/PACK11.PAK" if pack11 else "Data/PACK10_01.PAK",
                "changed_members": changed,
                "runtime_validated": False,
            })

        core = reports / "core_profile_manifest_evidence"
        write_json(core / "SUMMARY.json", {
            "type": "br_quartet_restoration_core_profile_manifest_evidence_summary",
            "tool_version": "0.0.50",
            "status": "all_current_local_profiles_registered_runtime_unvalidated",
            "profile_rows": 7,
            "pack11_profile_rows": 5,
            "pack10_01_profile_rows": 2,
            "runtime_validated_profile_rows": 0,
        })
        write_tsv(core / "CORE_PROFILE_MANIFESTS.tsv", ["profile_id", "validation_status"], [
            {"profile_id": profile_id, "validation_status": "passed"} for profile_id in profile_ids
        ])

        backlog = reports / "presentation_event_backlog_evidence"
        write_json(backlog / "SUMMARY.json", {
            "type": "br_quartet_restoration_presentation_event_backlog_evidence_summary",
            "tool_version": "0.0.46",
        })
        write_tsv(backlog / "EVENT_CANDIDATE_BACKLOG.tsv", [
            "normalized_path", "classification", "review_priority", "cue_domains",
        ], [
            {"normalized_path": candidate_path, "classification": "cue_linked_residual_needs_static_reconstruction", "review_priority": "high", "cue_domains": "bath_or_hot_spring"},
            {"normalized_path": registered_path, "classification": "cue_linked_residual_needs_static_reconstruction", "review_priority": "high", "cue_domains": "steam_or_vapor"},
        ])

        prototype = reports / "presentation_event_backlog_prototype_evidence"
        write_json(prototype / "SUMMARY.json", {
            "type": "br_quartet_restoration_presentation_event_backlog_prototype_evidence_summary",
            "tool_version": "0.0.48",
            "promoted_profile_rows": 1,
            "validation_failures": 1,
        })
        write_tsv(prototype / "PRESENTATION_EVENT_BACKLOG_VALIDATION.tsv", [
            "normalized_path", "check_name", "passed",
        ], [{
            "normalized_path": "event/event_jp/ce07/event_ce07_060.ebd",
            "check_name": "candidate_not_farther_from_original",
            "passed": False,
        }])

        source_words = [1, 0x75400009, 0x74100011, 0x7F000000, 0x7540000A, 0x74100012, 0x7F000000]
        target_words = [1, 0x75400009, 0x74100011, 0x74100014, 0x7F000000, 0x7540000A, 0x74100012, 0x74100015, 0x7F000000]
        source_payload = make_payload(source_words)
        target_payload = make_payload(target_words)
        source_header = BR.parse_ebd_header_schema(source_payload)
        target_header = BR.parse_ebd_header_schema(target_payload)
        source_profile = BR.profile_ebd_post_header_words(source_payload, int(source_header["header_end"]))
        target_profile = BR.profile_ebd_post_header_words(target_payload, int(target_header["header_end"]))
        deltas = BR.compare_ebd_tag_atoms(source_profile["atoms"], target_profile["atoms"])
        shapes = [BR.event_residual_delta_shape_id(delta) for delta in deltas]

        context = reports / "event_delta_context_evidence"
        write_json(context / "SUMMARY.json", {
            "type": "br_quartet_restoration_event_delta_context_evidence_summary",
            "tool_version": "0.0.27",
        })
        write_tsv(context / "EVENT_DELTA_CONTEXT_OCCURRENCES.tsv", [
            "normalized_path", "shape_id", "occurrence_index", "cue_positive_occurrence",
            "cue_domains", "selection_reasons",
        ], [
            {"normalized_path": candidate_path, "shape_id": shape, "occurrence_index": 0,
             "cue_positive_occurrence": True, "cue_domains": "bath_or_hot_spring",
             "selection_reasons": "domain_single_scene_context_shape"}
            for shape in shapes
        ])
        write_tsv(context / "EVENT_DELTA_CUE_NONCUE_COMPARISON.tsv", [
            "shape_id", "shared_cue_noncue_context_archetype_count",
        ], [{"shape_id": shape, "shared_cue_noncue_context_archetype_count": 0} for shape in shapes])

        migration = reports / "event_tag_migration_evidence"
        write_json(migration / "SUMMARY.json", {
            "type": "br_quartet_restoration_event_tag_migration_evidence_summary",
            "tool_version": "0.0.24",
        })
        write_tsv(migration / "EVENT_TAG_SCHEMA_MIGRATION_CANDIDATES.tsv", [
            "classification", "sequence_tag", "source_atom_count", "target_atom_count",
            "source_atom_sequence_sha256", "target_atom_sequence_sha256",
        ], [])

        differences = reports / "differences"
        source_ref = {"archive": "DATA/PACK01.PAK", "path": candidate_path, "sha256": hashlib.sha256(source_payload).hexdigest(), "size": len(source_payload)}
        target_member = "event/b1/event_jp/aa01/event_aa01_100.ebd"
        target_ref = {"archive": "Data/PACK11.PAK", "path": target_member, "sha256": hashlib.sha256(target_payload).hexdigest(), "size": len(target_payload)}
        write_json(differences / "br1_events.json", {
            "source_archive_group": "br1_events",
            "entries": [{
                "classification": "changed", "scope_status": "in_scope", "normalized_path": candidate_path,
                "source": source_ref, "target": target_ref,
            }],
        })
        for side, ref, payload in (("source", source_ref, source_payload), ("target", target_ref, target_payload)):
            path = BR.inventory_workspace_file(workspace, side, "br1_events", ref["archive"], ref["path"])
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(payload)
        return project, reports, candidate_path, shapes

    def test_end_to_end_promotes_best_strictly_improving_subset(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project, reports, path, shapes = self.build_fixture(Path(temporary))
            output, summary = TOOL.collect_subset_search(
                project_root=project,
                workspace_root=project / ".local/build/quartet_restoration",
                report_root=reports,
                top_combinations_per_event=8,
            )
            self.assertTrue(output.is_file())
            self.assertEqual(summary["registry_profile_rows"], 7)
            self.assertEqual(summary["analyzed_event_rows"], 1)
            self.assertEqual(summary["promotable_event_rows"], 1)
            rows = TOOL.read_tsv(reports / TOOL.EVIDENCE_DIR_NAME / "PRESENTATION_EVENT_SUBSET_SEARCH_EVENTS.tsv")
            self.assertEqual(rows[0]["normalized_path"], path)
            self.assertEqual(rows[0]["classification"], "strictly_improving_subset_ready_for_local_prototype")
            self.assertEqual(int(rows[0]["best_selected_occurrence_count"]), 2)
            self.assertEqual(set(rows[0]["best_selected_shape_ids"].split(";")), set(shapes))
            combinations = TOOL.read_tsv(reports / TOOL.EVIDENCE_DIR_NAME / "PRESENTATION_EVENT_SUBSET_SEARCH_COMBINATIONS.tsv")
            self.assertEqual(combinations[0]["exact_original"], "True")
            self.assertEqual(combinations[0]["passes_all_subset_gates"], "True")

    def test_shared_cue_noncue_context_blocks_promotion(self) -> None:
        source_words = [1, 0x75400009, 0x74100011, 0x7F000000]
        target_words = [1, 0x75400009, 0x74100011, 0x74100014, 0x7F000000]
        source = make_payload(source_words)
        target = make_payload(target_words)
        sh = BR.parse_ebd_header_schema(source)
        th = BR.parse_ebd_header_schema(target)
        sp = BR.profile_ebd_post_header_words(source, int(sh["header_end"]))
        tp = BR.profile_ebd_post_header_words(target, int(th["header_end"]))
        delta = BR.compare_ebd_tag_atoms(sp["atoms"], tp["atoms"])[0]
        shape = BR.event_residual_delta_shape_id(delta)
        result, _ = TOOL.evaluate_combination(
            br=BR,
            source_payload=source,
            target_payload=target,
            occurrences=[{"shape_id": shape, "occurrence_index": 0, "cue_positive_occurrence": True}],
            control_by_shape={shape: {"shared_cue_noncue_context_archetype_count": 1}},
        )
        self.assertFalse(result["passes"])
        self.assertTrue(result["strict_improvement"])
        self.assertFalse(result["checks"]["no_shared_cue_noncue_exact_context"])

    def test_core_report_requires_registered_em01_profile(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            write_json(root / "SUMMARY.json", {
                "type": "br_quartet_restoration_core_profile_manifest_evidence_summary",
                "tool_version": "0.0.50",
                "status": "all_current_local_profiles_registered_runtime_unvalidated",
                "profile_rows": 7, "pack11_profile_rows": 5, "pack10_01_profile_rows": 2,
                "runtime_validated_profile_rows": 0,
            })
            write_tsv(root / "CORE_PROFILE_MANIFESTS.tsv", ["profile_id", "validation_status"], [
                {"profile_id": f"profile-{index}", "validation_status": "passed"} for index in range(7)
            ])
            with self.assertRaises(TOOL.SubsetSearchError):
                TOOL.validate_core_report(root)


if __name__ == "__main__":
    unittest.main()
