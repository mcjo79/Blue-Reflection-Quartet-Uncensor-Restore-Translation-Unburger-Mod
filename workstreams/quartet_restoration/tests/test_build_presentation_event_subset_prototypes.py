from __future__ import annotations

import csv
import hashlib
import importlib.util
import json
import os
import struct
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
TOOL_PATH = ROOT / "workstreams/quartet_restoration/build_presentation_event_subset_prototypes.py"
SPEC = importlib.util.spec_from_file_location("build_presentation_event_subset_prototypes", TOOL_PATH)
assert SPEC and SPEC.loader
TOOL = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = TOOL
SPEC.loader.exec_module(TOOL)

STAGE44_PATH = ROOT / "workstreams/quartet_restoration/collect_presentation_event_subset_search_evidence.py"
STAGE44_SPEC = importlib.util.spec_from_file_location("stage44_fixture_helper", STAGE44_PATH)
assert STAGE44_SPEC and STAGE44_SPEC.loader
STAGE44 = importlib.util.module_from_spec(STAGE44_SPEC)
sys.modules[STAGE44_SPEC.name] = STAGE44
STAGE44_SPEC.loader.exec_module(STAGE44)

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


def read_rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return [dict(row) for row in csv.DictReader(handle, delimiter="\t")]


def lp(raw: bytes) -> bytes:
    return struct.pack("<I", len(raw)) + raw


def make_payload(words: list[int]) -> bytes:
    prefix = struct.pack("<II", 2, 0) + lp(b"name\0") + lp("説明".encode("cp932") + b"\0")
    return prefix + struct.pack(f"<{len(words)}I", *words)


class PresentationEventSubsetPrototypeTests(unittest.TestCase):
    def build_fixture(self, root: Path, *, register_candidate: bool = False) -> tuple[Path, Path, str, str]:
        project = root / "project"
        reports = project / ".local/reports/quartet_restoration"
        workspace = project / ".local/build/quartet_restoration"
        registry = workspace / "core_profiles/generated"
        registry.mkdir(parents=True)
        reports.mkdir(parents=True)
        os.symlink(ROOT / "Blue_Reflection_Text_Tool", project / "Blue_Reflection_Text_Tool", target_is_directory=True)
        (project / "workstreams").mkdir()
        os.symlink(ROOT / "workstreams/quartet_restoration", project / "workstreams/quartet_restoration", target_is_directory=True)

        event_path = "event/event_jp/aa01/event_aa01_100.ebd"
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
            changed = []
            if register_candidate and index == 0:
                changed = ["event/b1/event_jp/aa01/event_aa01_100.ebd"]
            write_json(registry / f"{profile_id}.json", {
                "workstream_id": TOOL.WORKSTREAM_ID,
                "profile_id": profile_id,
                "target_relative_path": "Data/PACK11.PAK" if index < 5 else "Data/PACK10_01.PAK",
                "changed_members": changed,
                "runtime_validated": False,
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
        occurrences = [
            {
                "shape_id": shape,
                "occurrence_index": 0,
                "cue_positive_occurrence": True,
                "cue_domains": "bath_or_hot_spring",
                "selection_reasons": "domain_single_scene_context_shape",
            }
            for shape in shapes
        ]
        result, residuals = STAGE44.evaluate_combination(
            br=BR,
            source_payload=source_payload,
            target_payload=target_payload,
            occurrences=occurrences,
            control_by_shape={shape: {"shared_cue_noncue_context_archetype_count": 0} for shape in shapes},
        )
        self.assertTrue(result["passes"])
        self.assertTrue(result["strict_improvement"])
        subset_id = "fixturebestsubset"

        subset = reports / TOOL.SOURCE_REPORT_DIR
        write_json(subset / "SUMMARY.json", {
            "type": "br_quartet_restoration_presentation_event_subset_search_evidence_summary",
            "tool_version": "0.0.51",
            "status": "bounded_cue_linked_residual_subset_search_complete_no_payload_written_runtime_deferred",
            "promotable_event_rows": 1,
            "runtime_testing_deferred": True,
            "policy": {
                "installed_games_modified": False,
                "candidate_ebd_payloads_written": False,
                "pak_repacked": False,
                "core_profile_manifest_modified": False,
                "activation_or_rollback_invoked": False,
                "runtime_validation_inferred": False,
                "censorship_classification_inferred": False,
            },
        })
        write_tsv(subset / "PRESENTATION_EVENT_SUBSET_SEARCH_EVENTS.tsv", [
            "normalized_path", "event_id", "cue_domains", "best_subset_id",
            "best_selected_occurrence_count", "best_selected_shape_ids", "target_distance_to_source",
            "best_candidate_distance_to_source", "best_distance_improvement", "best_candidate_sha256",
            "best_remaining_residual_rows", "classification", "safe_to_build_local_profile_without_runtime",
            "runtime_test_deferred",
        ], [{
            "normalized_path": event_path,
            "event_id": "aa01_100",
            "cue_domains": "bath_or_hot_spring",
            "best_subset_id": subset_id,
            "best_selected_occurrence_count": len(occurrences),
            "best_selected_shape_ids": ";".join(sorted(shapes)),
            "target_distance_to_source": result["target_distance_to_source"],
            "best_candidate_distance_to_source": result["candidate_distance_to_source"],
            "best_distance_improvement": result["distance_improvement"],
            "best_candidate_sha256": result["candidate_sha256"],
            "best_remaining_residual_rows": len(residuals),
            "classification": "strictly_improving_subset_ready_for_local_prototype",
            "safe_to_build_local_profile_without_runtime": True,
            "runtime_test_deferred": True,
        }])
        write_tsv(subset / "PRESENTATION_EVENT_SUBSET_SEARCH_COMBINATIONS.tsv", [
            "normalized_path", "subset_rank", "subset_id", "selected_occurrence_count",
            "selected_shape_ids", "candidate_sha256", "candidate_size", "passes_all_subset_gates",
            "strict_improvement",
        ], [{
            "normalized_path": event_path,
            "subset_rank": 1,
            "subset_id": subset_id,
            "selected_occurrence_count": len(occurrences),
            "selected_shape_ids": ";".join(sorted(shapes)),
            "candidate_sha256": result["candidate_sha256"],
            "candidate_size": result["candidate_size"],
            "passes_all_subset_gates": True,
            "strict_improvement": True,
        }])
        write_tsv(subset / "PRESENTATION_EVENT_SUBSET_SEARCH_SELECTED_OCCURRENCES.tsv", [
            "normalized_path", "best_subset_id", "selection_order", "shape_id", "occurrence_index",
            "cue_domains", "selection_reasons", "shared_cue_noncue_context_archetype_count",
        ], [
            {
                "normalized_path": event_path,
                "best_subset_id": subset_id,
                "selection_order": index,
                "shape_id": row["shape_id"],
                "occurrence_index": 0,
                "cue_domains": "bath_or_hot_spring",
                "selection_reasons": "domain_single_scene_context_shape",
                "shared_cue_noncue_context_archetype_count": 0,
            }
            for index, row in enumerate(occurrences)
        ])
        write_tsv(subset / "PRESENTATION_EVENT_SUBSET_SEARCH_RESIDUALS.tsv", [
            "normalized_path", "best_subset_id", "shape_id", "sequence_tag", "source_atom_count",
            "target_atom_count", "classification",
        ], [
            {
                "normalized_path": event_path,
                "best_subset_id": subset_id,
                "shape_id": row.get("shape_id", ""),
                "sequence_tag": row.get("sequence_tag", ""),
                "source_atom_count": row.get("source_atom_count", ""),
                "target_atom_count": row.get("target_atom_count", ""),
                "classification": row.get("classification", ""),
            }
            for row in residuals
        ])

        source_ref = {
            "archive": "DATA/PACK01.PAK", "path": event_path,
            "sha256": hashlib.sha256(source_payload).hexdigest(), "size": len(source_payload),
        }
        target_member = "event/b1/event_jp/aa01/event_aa01_100.ebd"
        target_ref = {
            "archive": "Data/PACK11.PAK", "path": target_member,
            "sha256": hashlib.sha256(target_payload).hexdigest(), "size": len(target_payload),
        }
        write_json(reports / "differences/br1_events.json", {
            "source_archive_group": "br1_events",
            "entries": [{
                "classification": "changed", "scope_status": "in_scope", "normalized_path": event_path,
                "source": source_ref, "target": target_ref,
            }],
        })
        for side, ref, payload in (("source", source_ref, source_payload), ("target", target_ref, target_payload)):
            payload_path = BR.inventory_workspace_file(workspace, side, "br1_events", ref["archive"], ref["path"])
            payload_path.parent.mkdir(parents=True, exist_ok=True)
            payload_path.write_bytes(payload)
        return project, reports, event_path, result["candidate_sha256"]

    def test_builds_separate_local_subset_profile_and_metadata_only_report(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project, reports, event_path, candidate_sha = self.build_fixture(Path(temporary))
            output, summary = TOOL.build_subset_prototypes(
                project_root=project,
                workspace_root=project / ".local/build/quartet_restoration",
                report_root=reports,
            )
            self.assertTrue(output.is_file())
            self.assertEqual(summary["proposed_profile_rows"], 1)
            self.assertEqual(summary["promoted_profile_rows"], 1)
            self.assertEqual(summary["prototype_file_rows"], 1)
            self.assertEqual(summary["validation_failures"], 0)
            self.assertEqual(summary["skipped_rows"], 0)
            files = read_rows(reports / TOOL.EVIDENCE_DIR_NAME / "PRESENTATION_EVENT_SUBSET_FILES.tsv")
            self.assertEqual(files[0]["normalized_path"], event_path)
            self.assertEqual(files[0]["candidate_sha256"], candidate_sha)
            payloads = list((project / ".local/build/quartet_restoration" / TOOL.PROTOTYPE_SUBDIR).rglob("*.ebd"))
            self.assertEqual(len(payloads), 1)
            listing = subprocess.run(
                ["tar", "--zstd", "-tf", str(output)], text=True, capture_output=True, check=True
            ).stdout.casefold()
            self.assertNotIn(".ebd", listing)
            self.assertNotIn(".pak", listing)
            self.assertNotIn(Path(event_path).name.casefold(), listing)

    def test_corrupted_reported_candidate_hash_keeps_profile_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project, reports, _, _ = self.build_fixture(Path(temporary))
            path = reports / TOOL.SOURCE_REPORT_DIR / "PRESENTATION_EVENT_SUBSET_SEARCH_EVENTS.tsv"
            rows = read_rows(path)
            rows[0]["best_candidate_sha256"] = "0" * 64
            write_tsv(path, list(rows[0]), rows)
            with self.assertRaisesRegex(TOOL.SubsetPrototypeError, "hash disagreement"):
                TOOL.build_subset_prototypes(
                    project_root=project,
                    workspace_root=project / ".local/build/quartet_restoration",
                    report_root=reports,
                )

    def test_registered_event_is_not_rebuilt(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project, reports, _, _ = self.build_fixture(Path(temporary), register_candidate=True)
            _, summary = TOOL.build_subset_prototypes(
                project_root=project,
                workspace_root=project / ".local/build/quartet_restoration",
                report_root=reports,
            )
            self.assertEqual(summary["promoted_profile_rows"], 0)
            self.assertEqual(summary["skipped_rows"], 1)
            self.assertEqual(len(list((project / ".local/build/quartet_restoration" / TOOL.PROTOTYPE_SUBDIR).rglob("*.ebd"))), 0)


if __name__ == "__main__":
    unittest.main()
