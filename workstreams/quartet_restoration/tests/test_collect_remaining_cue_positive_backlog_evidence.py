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
TOOL_PATH = ROOT / "workstreams/quartet_restoration/collect_remaining_cue_positive_backlog_evidence.py"
SPEC = importlib.util.spec_from_file_location("collect_remaining_cue_positive_backlog_evidence", TOOL_PATH)
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


class RemainingCuePositiveBacklogTests(unittest.TestCase):
    def build_fixture(self, root: Path) -> tuple[Path, Path, str, set[str]]:
        project = root / "project"
        reports = project / ".local/reports/quartet_restoration"
        workspace = project / ".local/build/quartet_restoration"
        registry = workspace / "core_profiles/generated"
        registry.mkdir(parents=True)
        reports.mkdir(parents=True)
        os.symlink(ROOT / "Blue_Reflection_Text_Tool", project / "Blue_Reflection_Text_Tool", target_is_directory=True)

        candidate_path = "event/event_jp/aa01/event_aa01_100.ebd"
        registered_path = "event/event_jp/bb01/event_bb01_200.ebd"
        legacy_path = "event/event_jp/fe01/event_fe01_220.ebd"
        closed_path = "event/event_jp/fo07/event_fo07_090.ebd"

        profile_ids = [
            "repeated_context_69adef108a_c90700a5a2",
            "route_sequence_te02_a570203aa6",
            "single_scene_event_te02_230_0143f9822b",
            "shared_presentation_d88c7c3a6f",
            "candidate_single_scene_multishape_em01_050_954fadd61cac",
            "candidate_subset_ce07_060_1cddf6cac60969c4",
            "candidate_subset_ce11_010_abc7939e4ff69ead",
            "candidate_subset_em01_060_43f9052741640b35",
            "candidate_subset_em02_030_552c84999f656afb",
            "candidate_subset_te01_270_f6e3b892ac7ba1b9",
            "candidate_subset_xf07_030_d85e6afc33b5802b",
            TOOL.NEW_FE13_PROFILE_ID,
            "height_fog_shader_original_code",
            "water_shader_swater_original_code",
        ]
        for index, profile_id in enumerate(profile_ids):
            pack11 = index < 12
            changed = ["event/b1/event_jp/bb01/event_bb01_200.ebd"] if profile_id == profile_ids[0] else []
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
            "tool_version": "0.0.71",
            "status": "all_current_local_profiles_registered_runtime_unvalidated",
            "profile_rows": 14,
            "pack11_profile_rows": 12,
            "pack10_01_profile_rows": 2,
            "runtime_validated_profile_rows": 0,
        })
        write_tsv(core / "CORE_PROFILE_MANIFESTS.tsv", [
            "profile_id", "runtime_validated", "validation_status",
        ], [
            {"profile_id": profile_id, "runtime_validated": False, "validation_status": "passed"}
            for profile_id in profile_ids
        ])

        backlog = reports / "presentation_event_backlog_evidence"
        write_json(backlog / "SUMMARY.json", {
            "type": "br_quartet_restoration_presentation_event_backlog_evidence_summary",
            "tool_version": "0.0.46",
        })
        write_tsv(backlog / "EVENT_CANDIDATE_BACKLOG.tsv", [
            "normalized_path", "classification", "review_priority", "cue_domains",
        ], [
            {"normalized_path": candidate_path, "classification": "residual_event_evidence_only", "review_priority": "medium", "cue_domains": "bath_or_hot_spring"},
            {"normalized_path": registered_path, "classification": "cue_linked_residual_needs_static_reconstruction", "review_priority": "high", "cue_domains": "steam_or_vapor"},
            {"normalized_path": legacy_path, "classification": "residual_event_evidence_only", "review_priority": "critical", "cue_domains": "costume_or_coverage"},
            {"normalized_path": closed_path, "classification": "residual_event_evidence_only", "review_priority": "high", "cue_domains": "bath_or_hot_spring"},
            {"normalized_path": "event/event_jp/cc01/event_cc01_100.ebd", "classification": "residual_event_evidence_only", "review_priority": "medium", "cue_domains": ""},
            {"normalized_path": "event/event_jp/dd01/event_dd01_100.ebd", "classification": "residual_event_evidence_only", "review_priority": "low", "cue_domains": "pool_or_swimming"},
        ])

        context = reports / "event_delta_context_evidence"
        write_json(context / "SUMMARY.json", {
            "type": "br_quartet_restoration_event_delta_context_evidence_summary",
            "tool_version": "0.0.27",
        })

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
        write_tsv(context / "EVENT_DELTA_CONTEXT_OCCURRENCES.tsv", [
            "normalized_path", "shape_id", "occurrence_index", "cue_positive_occurrence", "cue_domains", "selection_reasons",
        ], [
            {
                "normalized_path": candidate_path,
                "shape_id": shape,
                "occurrence_index": 0,
                "cue_positive_occurrence": True,
                "cue_domains": "bath_or_hot_spring",
                "selection_reasons": "medium_priority_scene_unique_shape",
            }
            for shape in shapes
        ])
        write_tsv(context / "EVENT_DELTA_CUE_NONCUE_COMPARISON.tsv", [
            "shape_id", "shared_cue_noncue_context_archetype_count",
        ], [
            {"shape_id": shape, "shared_cue_noncue_context_archetype_count": 0} for shape in shapes
        ])

        migration = reports / "event_tag_migration_evidence"
        write_json(migration / "SUMMARY.json", {
            "type": "br_quartet_restoration_event_tag_migration_evidence_summary",
            "tool_version": "0.0.24",
        })
        write_tsv(migration / "EVENT_TAG_SCHEMA_MIGRATION_CANDIDATES.tsv", [
            "classification", "sequence_tag", "source_atom_count", "target_atom_count", "source_atom_sequence_sha256", "target_atom_sequence_sha256",
        ], [])

        anchor = reports / "registered_profile_anchor_subset_evidence"
        write_json(anchor / "SUMMARY.json", {
            "type": "br_quartet_restoration_registered_profile_anchor_subset_evidence_summary",
            "tool_version": "0.0.56",
            "promotable_event_rows": 0,
        })
        write_tsv(anchor / "REGISTERED_PROFILE_ANCHOR_SUBSET_EVENTS.tsv", [
            "normalized_path", "safe_to_build_separate_local_profile",
        ], [{"normalized_path": closed_path, "safe_to_build_separate_local_profile": False}])

        complex_root = reports / "complex_repeated_shape_subset_evidence"
        write_json(complex_root / "SUMMARY.json", {
            "type": "br_quartet_restoration_complex_repeated_shape_subset_evidence_summary",
            "tool_version": "0.0.58",
            "promotable_event_rows": 0,
        })
        write_tsv(complex_root / "COMPLEX_REPEATED_SHAPE_EVENTS.tsv", [
            "normalized_path", "safe_to_build_separate_local_profile",
        ], [{"normalized_path": "event/event_jp/fe13/event_fe13_050.ebd", "safe_to_build_separate_local_profile": False}])

        placeholder = reports / "fe01_message_placeholder_evidence"
        write_json(placeholder / "SUMMARY.json", {
            "type": "br_quartet_restoration_fe01_message_placeholder_evidence_summary",
            "tool_version": "0.0.65",
        })
        write_tsv(placeholder / "FE_EVENT_MESSAGE_PAYLOAD_AUDIT.tsv", [
            "event_id", "family", "all_target_languages_exact_dash_placeholders",
        ], [{"event_id": "fe01_220", "family": "fe01", "all_target_languages_exact_dash_placeholders": True}])

        differences = reports / "differences"
        source_ref = {
            "archive": "DATA/PACK01.PAK",
            "path": candidate_path,
            "sha256": hashlib.sha256(source_payload).hexdigest(),
            "size": len(source_payload),
        }
        target_member = "event/b1/event_jp/aa01/event_aa01_100.ebd"
        target_ref = {
            "archive": "Data/PACK11.PAK",
            "path": target_member,
            "sha256": hashlib.sha256(target_payload).hexdigest(),
            "size": len(target_payload),
        }
        write_json(differences / "br1_events.json", {
            "source_archive_group": "br1_events",
            "entries": [{
                "classification": "changed",
                "scope_status": "in_scope",
                "normalized_path": candidate_path,
                "source": source_ref,
                "target": target_ref,
            }],
        })
        for side, ref, payload in (("source", source_ref, source_payload), ("target", target_ref, target_payload)):
            path = BR.inventory_workspace_file(workspace, side, "br1_events", ref["archive"], ref["path"])
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(payload)
        return project, reports, candidate_path, {registered_path, legacy_path, closed_path}

    def test_end_to_end_expands_to_medium_priority_and_excludes_owned_legacy_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project, reports, candidate_path, excluded_paths = self.build_fixture(Path(temporary))
            output, summary = TOOL.collect(
                project_root=project,
                workspace_root=project / ".local/build/quartet_restoration",
                report_root=reports,
                top_combinations_per_event=8,
            )
            self.assertTrue(output.is_file())
            self.assertEqual(summary["registry_profile_rows"], 14)
            self.assertEqual(summary["analyzed_event_rows"], 1)
            self.assertEqual(summary["promotable_event_rows"], 1)
            rows = TOOL.read_tsv(reports / TOOL.EVIDENCE_DIR_NAME / "REMAINING_CUE_POSITIVE_BACKLOG_EVENTS.tsv")
            self.assertEqual(rows[0]["normalized_path"], candidate_path)
            self.assertEqual(rows[0]["review_priority"], "medium")
            self.assertEqual(rows[0]["classification"], "remaining_cue_subset_ready_for_local_prototype")
            exclusions = TOOL.read_tsv(reports / TOOL.EVIDENCE_DIR_NAME / "REMAINING_CUE_POSITIVE_BACKLOG_EVENT_EXCLUSIONS.tsv")
            exclusion_by_path = {row["normalized_path"]: row["reason"] for row in exclusions}
            for path in excluded_paths:
                self.assertIn(path, exclusion_by_path)
            self.assertEqual(exclusion_by_path["event/event_jp/fe01/event_fe01_220.ebd"], "legacy_dlc_or_removed_content_literal_dash_scene")

    def test_core_report_rejects_superseded_profile(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            ids = [f"profile-{index}" for index in range(12)] + ["height", "water"]
            ids[0] = TOOL.OLD_FE13_PROFILE_ID
            write_json(root / "SUMMARY.json", {
                "type": "br_quartet_restoration_core_profile_manifest_evidence_summary",
                "tool_version": "0.0.71",
                "status": "all_current_local_profiles_registered_runtime_unvalidated",
                "profile_rows": 14,
                "pack11_profile_rows": 12,
                "pack10_01_profile_rows": 2,
                "runtime_validated_profile_rows": 0,
            })
            write_tsv(root / "CORE_PROFILE_MANIFESTS.tsv", [
                "profile_id", "runtime_validated", "validation_status",
            ], [
                {"profile_id": profile_id, "runtime_validated": False, "validation_status": "passed"}
                for profile_id in ids
            ])
            with self.assertRaises(TOOL.RemainingCueBacklogError):
                TOOL.validate_core_report(root)

    def test_literal_dash_path_mapping(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            write_tsv(root / "FE_EVENT_MESSAGE_PAYLOAD_AUDIT.tsv", [
                "event_id", "family", "all_target_languages_exact_dash_placeholders",
            ], [
                {"event_id": "fe01_220", "family": "fe01", "all_target_languages_exact_dash_placeholders": True},
                {"event_id": "fe01_010", "family": "fe01", "all_target_languages_exact_dash_placeholders": False},
            ])
            self.assertEqual(
                TOOL.legacy_dash_event_paths(root),
                {"event/event_jp/fe01/event_fe01_220.ebd"},
            )


if __name__ == "__main__":
    unittest.main()
