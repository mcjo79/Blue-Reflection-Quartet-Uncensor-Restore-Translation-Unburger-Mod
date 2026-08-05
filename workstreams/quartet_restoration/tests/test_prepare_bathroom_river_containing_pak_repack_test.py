from __future__ import annotations

import csv
import hashlib
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

WORKSTREAM = Path(__file__).resolve().parents[1]
TOOL_PATH = WORKSTREAM / "prepare_bathroom_river_containing_pak_repack_test.py"
SPEC = importlib.util.spec_from_file_location("stage71_tool", TOOL_PATH)
assert SPEC and SPEC.loader
TOOL = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = TOOL
SPEC.loader.exec_module(TOOL)

HELPER_PATH = WORKSTREAM / "tests/test_br_restoration_tool.py"
HELPER_SPEC = importlib.util.spec_from_file_location("stage71_helper", HELPER_PATH)
assert HELPER_SPEC and HELPER_SPEC.loader
HELPER = importlib.util.module_from_spec(HELPER_SPEC)
sys.modules[HELPER_SPEC.name] = HELPER
HELPER_SPEC.loader.exec_module(HELPER)


def write_tsv(path: Path, fields: list[str], rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


class Stage71Tests(unittest.TestCase):
    def prepare(self, root: Path, *, corrupt_current: bool = False, duplicate_inventory: bool = False):
        project = root / "project"
        workspace = project / ".local/build/quartet_restoration"
        reports = project / ".local/reports/quartet_restoration"
        quartet = root / "quartet"
        gust_pak = root / "gust_pak"
        helper = HELPER.EventRepackTestHarnessTests()
        helper._write_fake_gust_pak(gust_pak)

        target_parent = b"quartet-parent-elixir" * 17
        candidate_parent = b"candidate-parent-elixir" * 17
        target_hash = hashlib.sha256(target_parent).hexdigest()
        candidate_hash = hashlib.sha256(candidate_parent).hexdigest()
        old_target = TOOL.EXPECTED_TARGET_PARENT_SHA256
        self.addCleanup(setattr, TOOL, "EXPECTED_TARGET_PARENT_SHA256", old_target)
        TOOL.EXPECTED_TARGET_PARENT_SHA256 = target_hash

        stage70 = reports / TOOL.STAGE70_DIR
        stage70.mkdir(parents=True)
        summary = {
            "type": "br_quartet_restoration_bathroom_river_parent_elixir_repack_test_evidence_summary",
            "tool_version": "0.0.80",
            "status": "bathroom_river_parent_elixir_local_repack_verified_not_pak_repacked_or_installed",
            "proposed_profile_rows": 1,
            "repacked_profile_rows": 1,
            "parent_file_rows": 1,
            "member_rows": 15,
            "changed_member_rows": 1,
            "unchanged_member_rows": 14,
            "validation_rows": 25,
            "validation_failures": 0,
            "skipped_rows": 0,
            "container_kind": "gust_chunked_zlib",
            "selected_member_key": TOOL.STAGE70.MEMBER_KEY,
            "selected_member_candidate_sha256": TOOL.EXPECTED_SELECTED_MEMBER_SHA256,
            "target_parent_sha256": target_hash,
            "candidate_parent_sha256": candidate_hash,
            "decoded_parent_distance": 22,
            "policy": {
                "installed_games_modified": False,
                "candidate_parent_written_only_under_local_workspace": True,
                "rollback_parent_written_only_under_local_workspace": True,
                "candidate_parent_payload_exported_in_report": False,
                "selected_member_payload_exported_in_report": False,
                "pak_repack_performed": False,
                "core_registry_modified": False,
                "activation_or_rollback_invoked": False,
                "runtime_validation_inferred": False,
                "censorship_classification_inferred": False,
                "opaque_binary_field_semantics_inferred": False,
                "opl2_payload_modified": False,
                "translation_or_dlc_workstreams_modified": False,
            },
        }
        (stage70 / "SUMMARY.json").write_text(json.dumps(summary), encoding="utf-8")
        local_profile = workspace / "repack_tests/bathroom_river_parent_elixir" / TOOL.SOURCE_PROFILE_ID
        candidate_rel = "candidate/parent.elixir.gz"
        candidate_file = local_profile / candidate_rel
        candidate_file.parent.mkdir(parents=True, exist_ok=True)
        candidate_file.write_bytes(candidate_parent)
        (local_profile / "REPACK_TEST.json").write_text(json.dumps({
            "type": "br_quartet_restoration_local_parent_elixir_repack_test",
            "tool_version": "0.0.80",
            "profile_id": TOOL.SOURCE_PROFILE_ID,
            "parent_container": TOOL.PARENT_PATH,
            "changed_member_count": 1,
            "target_parent_sha256": target_hash,
            "candidate_parent_sha256": candidate_hash,
            "candidate_relative_path": candidate_rel,
            "pak_repacked": False,
            "core_registry_modified": False,
            "installed_game_modified": False,
            "runtime_validated": False,
            "semantics_assigned": False,
        }), encoding="utf-8")
        profile_row = {
            "profile_id": TOOL.SOURCE_PROFILE_ID,
            "source_profile_id": TOOL.STAGE70.SOURCE_PROFILE_ID,
            "parent_container": TOOL.PARENT_PATH,
            "selected_member_key": TOOL.STAGE70.MEMBER_KEY,
            "changed_member_count": 1,
            "unchanged_member_count": 14,
            "target_parent_sha256": target_hash,
            "candidate_parent_sha256": candidate_hash,
            "rollback_parent_sha256": target_hash,
            "local_profile_root": str(local_profile.relative_to(project)),
            "validation_status": "passed",
            "runtime_validated": False,
        }
        write_tsv(stage70 / "BATHROOM_RIVER_PARENT_ELIXIR_REPACK_PROFILES.tsv", list(profile_row), [profile_row])
        file_row = {
            "target_parent_sha256": target_hash,
            "candidate_parent_sha256": candidate_hash,
            "decoded_distance": 22,
        }
        write_tsv(stage70 / "BATHROOM_RIVER_PARENT_ELIXIR_REPACK_FILES.tsv", list(file_row), [file_row])
        write_tsv(
            stage70 / "BATHROOM_RIVER_PARENT_ELIXIR_REPACK_VALIDATIONS.tsv",
            ["check_name", "passed"],
            [{"check_name": f"check_{index}", "passed": True} for index in range(25)],
        )
        write_tsv(stage70 / "BATHROOM_RIVER_PARENT_ELIXIR_REPACK_SKIPPED.tsv", ["reason"], [])

        archive_rel = "Data/PACK00.PAK"
        member_path = TOOL.PARENT_PATH
        archive = quartet / archive_rel
        installed_parent = b"corrupt-current-parent" if corrupt_current else target_parent
        unrelated = b"translated-or-remastered-unrelated-member"
        helper._write_fake_pak(archive, {
            member_path: installed_parent,
            "data/x64/field/other/other.elixir.gz": unrelated,
        })
        installed_sha = hashlib.sha256(archive.read_bytes()).hexdigest()

        inventories = reports / "inventories"
        inventories.mkdir(parents=True)
        rows = [{
            "normalized_path": TOOL.PARENT_PATH,
            "archive": archive_rel,
            "path": member_path,
            "sha256": hashlib.sha256(installed_parent).hexdigest(),
        }]
        if duplicate_inventory:
            rows.append(dict(rows[0]))
        (inventories / "br1_fields.target.json").write_text(json.dumps({
            "normalization_side": "target",
            "archive_group": "br1_fields",
            "files": rows,
        }), encoding="utf-8")
        write_tsv(reports / "ARCHIVE_INVENTORY.tsv", [
            "pair_id", "category", "side", "target_id", "archive", "size", "sha256", "extraction_status",
        ], [{
            "pair_id": "br1_fields", "category": "fields", "side": "target",
            "target_id": "blue_reflection_quartet", "archive": archive_rel,
            "size": archive.stat().st_size, "sha256": installed_sha, "extraction_status": "unchanged",
        }])
        return project, workspace, reports, quartet, gust_pak, archive, installed_sha, helper, candidate_parent, unrelated

    def test_builds_one_local_pak_and_preserves_unrelated_member(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            project, workspace, reports, quartet, gust_pak, archive, installed_sha, helper, candidate, unrelated = self.prepare(root)
            report, summary = TOOL.build(
                project_root=project,
                quartet_root=quartet,
                gust_pak=gust_pak,
                workspace_root=workspace,
                report_root=reports,
                timeout_seconds=30,
            )
            self.assertTrue(report.is_file())
            self.assertEqual(summary["repacked_profile_rows"], 1)
            self.assertEqual(summary["validation_failures"], 0)
            self.assertEqual(summary["skipped_rows"], 0)
            self.assertEqual(hashlib.sha256(archive.read_bytes()).hexdigest(), installed_sha)
            output = workspace / TOOL.REPACK_SUBDIR / "profiles" / TOOL.PROFILE_ID / "output/Data/PACK00.PAK"
            self.assertEqual(helper._read_fake_pak_member(output, TOOL.PARENT_PATH), candidate)
            self.assertEqual(
                helper._read_fake_pak_member(output, "data/x64/field/other/other.elixir.gz"),
                unrelated,
            )
            profile = json.loads((workspace / TOOL.REPACK_SUBDIR / "profiles" / TOOL.PROFILE_ID / "PROFILE.json").read_text())
            self.assertEqual(profile["replaced_member_count"], 1)
            self.assertFalse(profile["installed_game_modified"])

    def test_rejects_current_member_hash_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            project, workspace, reports, quartet, gust_pak, *_ = self.prepare(root, corrupt_current=True)
            with self.assertRaisesRegex(TOOL.BathroomRiverContainingPakError, "does not match"):
                TOOL.build(
                    project_root=project, quartet_root=quartet, gust_pak=gust_pak,
                    workspace_root=workspace, report_root=reports, timeout_seconds=30,
                )

    def test_rejects_duplicate_inventory_mapping(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            project, workspace, reports, quartet, gust_pak, *_ = self.prepare(root, duplicate_inventory=True)
            with self.assertRaisesRegex(TOOL.BathroomRiverContainingPakError, "found 2"):
                TOOL.build(
                    project_root=project, quartet_root=quartet, gust_pak=gust_pak,
                    workspace_root=workspace, report_root=reports, timeout_seconds=30,
                )


if __name__ == "__main__":
    unittest.main()
