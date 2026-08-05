from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
TOOL_PATH = ROOT / "workstreams/quartet_restoration/collect_residual_scene_context_evidence.py"
SPEC = importlib.util.spec_from_file_location("collect_residual_scene_context_evidence", TOOL_PATH)
assert SPEC and SPEC.loader
TOOL = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = TOOL
SPEC.loader.exec_module(TOOL)


class ResidualSceneContextTests(unittest.TestCase):
    def test_existing_profile_wins_over_other_classifications(self):
        classification, priority, _ = TOOL.classify_shape(
            promoted_profiles=["route_sequence"],
            support_file_count=8,
            same_route_file_count=8,
            other_route_file_count=0,
            route_family_count=1,
            cue_file_count=4,
        )
        self.assertEqual(classification, "already_covered_by_existing_local_profile")
        self.assertEqual(priority, "parked")

    def test_route_local_shape_is_high_priority(self):
        classification, priority, _ = TOOL.classify_shape(
            promoted_profiles=[],
            support_file_count=5,
            same_route_file_count=5,
            other_route_file_count=0,
            route_family_count=1,
            cue_file_count=2,
        )
        self.assertEqual(classification, "route_sequence_state_candidate")
        self.assertEqual(priority, "high")

    def test_corpus_common_shape_is_not_promoted(self):
        classification, priority, _ = TOOL.classify_shape(
            promoted_profiles=[],
            support_file_count=12,
            same_route_file_count=1,
            other_route_file_count=11,
            route_family_count=9,
            cue_file_count=2,
        )
        self.assertEqual(classification, "corpus_common_or_schema_candidate")
        self.assertEqual(priority, "low")

    def _write_tsv(self, path: Path, header: str, rows: list[str]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(header + "\n" + "\n".join(rows) + ("\n" if rows else ""), encoding="utf-8")

    def _pack(self, root: Path, directory_name: str, output: Path) -> None:
        subprocess.run(
            ["tar", "--zstd", "-cf", str(output), "-C", str(root), directory_name],
            check=True,
        )

    def _fixture(self, root: Path) -> tuple[Path, Path]:
        report_root = root / ".local/reports/quartet_restoration"
        report_root.mkdir(parents=True)
        registry = root / ".local/build/quartet_restoration/core_profiles/generated"
        registry.mkdir(parents=True)
        pak_root = root / ".local/build/quartet_restoration/test_profiles"
        pak_root.mkdir(parents=True)
        for index, profile_id in enumerate(sorted(TOOL.EXPECTED_PROFILE_IDS)):
            pak = pak_root / f"{profile_id}.PAK"
            pak.write_bytes(f"pak-{index}".encode())
            manifest = {
                "schema_version": 1,
                "profile_id": profile_id,
                "target_relative_path": "Data/PACK11.PAK",
                "baseline_sha256": "0" * 64,
                "baseline_size": 1,
                "profile_sha256": "1" * 64,
                "profile_size": pak.stat().st_size,
                "local_profile_path": pak.relative_to(root).as_posix(),
                "changed_member_count": 1,
                "changed_members": ["event/test.ebd"],
                "runtime_validated": False,
                "workstream_id": "quartet_restoration",
                "workstream_version": "0.0.40",
            }
            (registry / f"{profile_id}.json").write_text(json.dumps(manifest), encoding="utf-8")

        command = root / "core-list.sh"
        command.write_text(
            "#!/usr/bin/env bash\nprintf '%s\\n' "
            + " ".join(repr(profile_id) for profile_id in sorted(TOOL.EXPECTED_PROFILE_IDS))
            + "\n",
            encoding="utf-8",
        )

        # Single-scene report.
        base = root / "build_reports"
        single = base / "single_scene_composite_evidence"
        self._write_tsv(
            single / "FOCUSED_SINGLE_SCENE_COMPOSITE_REVIEW.tsv",
            "normalized_path\tcue_domains\tclassification",
            ["event/event_jp/te02/event_te02_180.ebd\tshower\tselected_single_scene_shapes_removed_unknown_residuals_remain"],
        )
        self._write_tsv(
            single / "SINGLE_SCENE_COMPOSITE_EVENTS.tsv",
            "normalized_path\tcue_domains",
            ["event/event_jp/te02/event_te02_180.ebd\tshower"],
        )
        self._write_tsv(
            single / "SINGLE_SCENE_COMPOSITE_RESIDUALS.tsv",
            "normalized_path\tshape_id\tsequence_tag\tsource_tag_values\ttarget_tag_values\tknown_schema_migration_shape",
            ["event/event_jp/te02/event_te02_180.ebd\tshape-route\tdelete\t0x1;0x2\t\tFalse"],
        )
        self._pack(base, "single_scene_composite_evidence", report_root / TOOL.INPUT_REPORTS["single_scene"])

        context = base / "event_delta_context_evidence"
        header = (
            "normalized_path\tshape_id\toccurrence_index\tsequence_tag\t"
            "cue_positive_occurrence\tpair_context_archetype_id"
        )
        rows = [
            f"event/event_jp/te02/event_te02_{number}.ebd\tshape-route\t0\tdelete\t{str(number in (180, 220))}\tctx-a"
            for number in (150, 180, 220, 250)
        ]
        self._write_tsv(context / "EVENT_DELTA_CONTEXT_OCCURRENCES.tsv", header, rows)
        self._pack(base, "event_delta_context_evidence", report_root / TOOL.INPUT_REPORTS["context"])

        migration = base / "event_tag_migration_evidence"
        self._write_tsv(
            migration / "EVENT_TAG_DELTA_SIGNATURE_FREQUENCY.tsv",
            "sequence_tag\tsource_atom_count\ttarget_atom_count\tsource_tag_values\ttarget_tag_values\toccurrence_count\tfile_count\troute_family_count",
            ["delete\t2\t0\t0x1;0x2\t\t4\t4\t1"],
        )
        self._pack(base, "event_tag_migration_evidence", report_root / TOOL.INPUT_REPORTS["migration"])

        prototypes = base / "event_prototype_evidence"
        self._write_tsv(
            prototypes / "EVENT_PROTOTYPE_PROFILES.tsv",
            "profile_id\tshape_id",
            [],
        )
        self._pack(base, "event_prototype_evidence", report_root / TOOL.INPUT_REPORTS["event_prototypes"])
        return report_root, command

    def test_end_to_end_classifies_route_shape_and_core_profiles(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            report_root, command = self._fixture(root)
            archive, summary = TOOL.collect(
                project_root=root,
                report_root=report_root,
                core_list_command=command,
                create_archive=False,
            )
            self.assertIsNone(archive)
            self.assertEqual(summary["core_profile_rows_passed"], 5)
            self.assertEqual(summary["unique_unresolved_shape_rows"], 1)
            self.assertEqual(
                summary["classification_counts"],
                {"route_sequence_state_candidate": 1},
            )

    def test_core_list_missing_profile_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            report_root, command = self._fixture(root)
            command.write_text("#!/usr/bin/env bash\necho incomplete\n", encoding="utf-8")
            with self.assertRaisesRegex(TOOL.ResidualContextError, "did not contain current profile IDs"):
                TOOL.collect(
                    project_root=root,
                    report_root=report_root,
                    core_list_command=command,
                    create_archive=False,
                )


if __name__ == "__main__":
    unittest.main()
