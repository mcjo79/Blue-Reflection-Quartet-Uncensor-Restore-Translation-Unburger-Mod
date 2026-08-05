from __future__ import annotations

import importlib.util
import json
import os
import tempfile
import unittest
import sys
from pathlib import Path

MODULE_PATH = Path(__file__).resolve().parents[1] / "local_translation_workflow.py"
SPEC = importlib.util.spec_from_file_location("local_translation_workflow", MODULE_PATH)
assert SPEC and SPEC.loader
workflow_module = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = workflow_module
SPEC.loader.exec_module(workflow_module)

LocalTranslationWorkflow = workflow_module.LocalTranslationWorkflow
WorkflowError = workflow_module.WorkflowError
normalize_modules = workflow_module.normalize_modules
sha256_file = workflow_module.sha256_file
resolve_case_insensitive = workflow_module.resolve_case_insensitive


def write_route_registry(project: Path) -> None:
    path = project / "config/translation_target_routes.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({
        "type": "br_translation_target_routes",
        "format_version": 1,
        "minimum_translation_version": "0.0.113",
        "installation_targets": {
            "blue_reflection_original": {"module_id": "blue_reflection_translation", "content_targets": ["blue_reflection_original"], "marker_archive": "DATA/PACK00_04_1.PAK"},
            "second_light_original": {"module_id": "second_light_translation", "content_targets": ["second_light_original"], "marker_archive": "Data/PACK00_04_01.PAK"},
            "blue_reflection_quartet": {"module_id": "blue_reflection_translation", "content_targets": ["blue_reflection_quartet", "blue_reflection_ray_quartet", "blue_reflection_sun_quartet", "second_light_quartet"], "marker_archive": "Data/PACK00_04_01.PAK"},
        },
        "content_targets": {
            "blue_reflection_original": {"installation_target_id": "blue_reflection_original", "project": "blue_reflection", "archives": [{"archive_stem": "PACK01", "relative_path": "DATA/PACK01.PAK", "production_text": True}, {"archive_stem": "PACK02_1", "relative_path": "DATA/PACK02_1.PAK", "production_text": True}]},
            "second_light_original": {"installation_target_id": "second_light_original", "project": "second_light", "archives": [{"archive_stem": "PACK01", "relative_path": "Data/PACK01.PAK", "production_text": True}, {"archive_stem": "PACK02", "relative_path": "Data/PACK02.PAK", "production_text": True}]},
            "blue_reflection_quartet": {"installation_target_id": "blue_reflection_quartet", "project": "blue_reflection", "archives": [{"archive_stem": "PACK11", "relative_path": "Data/PACK11.PAK", "production_text": True}, {"archive_stem": "PACK12", "relative_path": "Data/PACK12.PAK", "production_text": True}]},
            "blue_reflection_ray_quartet": {"installation_target_id": "blue_reflection_quartet", "project": "blue_reflection_ray", "archives": [{"archive_stem": "PACK01_01", "relative_path": "Data/PACK01_01.PAK", "production_text": True}, {"archive_stem": "PACK02_01", "relative_path": "Data/PACK02_01.PAK", "production_text": True}]},
            "blue_reflection_sun_quartet": {"installation_target_id": "blue_reflection_quartet", "project": "blue_reflection_sun", "archives": [{"archive_stem": "PACK01_02", "relative_path": "Data/PACK01_02.PAK", "production_text": True}, {"archive_stem": "PACK02_02", "relative_path": "Data/PACK02_02.PAK", "production_text": True}]},
            "second_light_quartet": {"installation_target_id": "blue_reflection_quartet", "project": "second_light", "archives": [{"archive_stem": "PACK01_03", "relative_path": "Data/PACK01_03.PAK", "production_text": True}, {"archive_stem": "PACK02_03", "relative_path": "Data/PACK02_03.PAK", "production_text": True}]},
        },
    }, indent=2) + "\n", encoding="utf-8")


class LocalTranslationWorkflowTests(unittest.TestCase):
    def test_normalize_modules_preserves_order_and_removes_duplicates(self) -> None:
        self.assertEqual(
            normalize_modules(" blue_reflection_translation,quartet_restoration,blue_reflection_translation "),
            ["blue_reflection_translation", "quartet_restoration"],
        )

    def make_source_project(self, root: Path, payload: bytes = b"baseline") -> tuple[Path, Path]:
        project = root / "project"
        game = root / "game"
        archive = game / "DATA/PACK01.PAK"
        archive.parent.mkdir(parents=True)
        archive.write_bytes(payload)
        workspace = project / "titles/blue_reflection/workspace/original/archives/PACK01"
        workspace.mkdir(parents=True)
        (project / "config").mkdir(parents=True)
        write_route_registry(project)
        (project / "config/text_source_archives.tsv").write_text(
            "target_id\tproject\tgame_relative_archive\tworkspace_slot\tpurpose\tstatus\n"
            "blue_reflection_original\tblue_reflection\tDATA/PACK01.PAK\toriginal/PACK01\tevents\tactive\n",
            encoding="utf-8",
        )
        (workspace / ".br_generated_source.tsv").write_text(
            "generated_by\ttest\n"
            f"source_bytes\t{len(payload)}\n"
            f"source_sha256\t{sha256_file(archive)}\n",
            encoding="utf-8",
        )
        return project, game

    def test_workspace_freshness_no_longer_rejects_different_game_version(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            project, game = self.make_source_project(Path(temp))
            (game / "DATA/PACK01.PAK").write_bytes(b"different-version")
            workflow = LocalTranslationWorkflow(project)
            workflow.verify_workspace_freshness(
                "blue_reflection_original",
                game,
                {"active_state": {"active": False}, "baseline": {}},
            )

    def test_case_insensitive_resolution_remains_available(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            _, game = self.make_source_project(root)
            original = game / "DATA/PACK01.PAK"
            payload = original.read_bytes()
            original.unlink()
            original.parent.rmdir()
            alternate = game / "Data/pack01.pak"
            alternate.parent.mkdir(parents=True)
            alternate.write_bytes(payload)
            self.assertEqual(resolve_case_insensitive(game, "DATA/PACK01.PAK"), alternate)

    def test_case_insensitive_resolution_does_not_select_analytical_pak_sibling(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            game = root / "game"
            analytical = game / "DATA/PACK01.PAK_"
            analytical.parent.mkdir(parents=True)
            analytical.write_bytes(b"old-analytical")
            self.assertIsNone(resolve_case_insensitive(game, "DATA/PACK01.PAK"))

    def test_prepare_target_workspace_extracts_different_archive_revision(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            project = root / "project"
            write_route_registry(project)
            game = root / "game"
            for relative, payload in {
                "DATA/PACK01.PAK": b"older-events-revision",
                "DATA/PACK02_1.PAK": b"older-system-revision",
            }.items():
                path = game / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(payload)
            gust = root / "gust_pak"
            gust.write_text(
                "#!/usr/bin/env python3\n"
                "import json, pathlib, sys\n"
                "stem = pathlib.Path(sys.argv[1]).stem.upper()\n"
                "pathlib.Path(stem + '.json').write_text('{}\\n', encoding='utf-8')\n",
                encoding="utf-8",
            )
            gust.chmod(0o755)
            workflow = LocalTranslationWorkflow(project)
            workspace_map = workflow.prepare_target_workspace(
                "blue_reflection_original",
                game,
                {"active_state": {"active": False}, "baseline": {}},
                gust,
            )
            data = json.loads(workspace_map.read_text(encoding="utf-8"))
            self.assertEqual(data["type"], "br_target_workspace_map")
            self.assertEqual(len(data["archives"]), 2)
            self.assertTrue(all(row["extraction_status"] == "extracted" for row in data["archives"]))
            self.assertTrue(workflow.report.workspace_source.startswith("current_baseline_structural_rebase:"))

    def test_marker_source_uses_persistent_baseline_for_active_mod(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            project = root / "project"
            write_route_registry(project)
            game = root / "game"
            installed = game / "DATA/PACK00_04_1.PAK"
            installed.parent.mkdir(parents=True)
            installed.write_bytes(b"installed-marker")

            baseline_root = root / "state/baselines/fingerprint"
            stored = baseline_root / "files/DATA/PACK00_04_1.PAK"
            stored.parent.mkdir(parents=True)
            stored.write_bytes(b"baseline-marker")
            manifest = baseline_root / "manifest.json"
            manifest.write_text(
                json.dumps(
                    {
                        "baseline_id": "baseline-marker",
                        "files": [
                            {
                                "relative_path": "DATA/PACK00_04_1.PAK",
                                "existed": True,
                                "stored_path": "files/DATA/PACK00_04_1.PAK",
                                "bytes": stored.stat().st_size,
                                "sha256": sha256_file(stored),
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            active_state = root / "state/active_state.json"
            active_state.parent.mkdir(parents=True, exist_ok=True)
            active_state.write_text(
                json.dumps({"baseline_manifest_path": str(manifest)}),
                encoding="utf-8",
            )

            workflow = LocalTranslationWorkflow(project)
            source_root = workflow.marker_source_root(
                "blue_reflection_original",
                game,
                {
                    "active_state": {"active": True, "state_path": str(active_state)},
                    "baseline": {},
                },
            )
            self.assertEqual(source_root, baseline_root / "files")
            self.assertEqual(workflow.report.marker_source, "persistent_baseline:baseline-marker")
            self.assertEqual((source_root / "DATA/PACK00_04_1.PAK").read_bytes(), b"baseline-marker")


    def test_marker_source_builds_canonical_view_for_case_insensitive_layout(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            project = root / "project"
            write_route_registry(project)
            game = root / "game"
            actual = game / "Data/pack00_04_1.pak"
            actual.parent.mkdir(parents=True)
            actual.write_bytes(b"marker-source")

            workflow = LocalTranslationWorkflow(project)
            source_root = workflow.marker_source_root(
                "blue_reflection_original",
                game,
                {"active_state": {"active": False}, "baseline": {}},
            )
            canonical = source_root / "DATA/PACK00_04_1.PAK"
            self.assertTrue(canonical.is_symlink())
            self.assertEqual(canonical.resolve(), actual.resolve())
            self.assertEqual(canonical.read_bytes(), b"marker-source")
            self.assertEqual(
                workflow.report.marker_source,
                "current_installation_case_insensitive:canonical_path_view",
            )

    def test_marker_source_rejects_corrupt_persistent_baseline(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            project = root / "project"
            write_route_registry(project)
            game = root / "game"
            baseline_root = root / "state/baselines/fingerprint"
            stored = baseline_root / "files/DATA/PACK00_04_1.PAK"
            stored.parent.mkdir(parents=True)
            stored.write_bytes(b"corrupt")
            manifest = baseline_root / "manifest.json"
            manifest.write_text(
                json.dumps(
                    {
                        "baseline_id": "baseline-marker",
                        "files": [
                            {
                                "relative_path": "DATA/PACK00_04_1.PAK",
                                "existed": True,
                                "stored_path": "files/DATA/PACK00_04_1.PAK",
                                "bytes": 8,
                                "sha256": "0" * 64,
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            active_state = root / "state/active_state.json"
            active_state.parent.mkdir(parents=True, exist_ok=True)
            active_state.write_text(
                json.dumps({"baseline_manifest_path": str(manifest)}),
                encoding="utf-8",
            )
            workflow = LocalTranslationWorkflow(project)
            with self.assertRaises(WorkflowError) as raised:
                workflow.marker_source_root(
                    "blue_reflection_original",
                    game,
                    {
                        "active_state": {"active": True, "state_path": str(active_state)},
                        "baseline": {},
                    },
                )
            self.assertEqual(raised.exception.code, "baseline_source_invalid")

    def test_br1_rejects_restoration_module(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            write_route_registry(Path(temp))
            workflow = LocalTranslationWorkflow(Path(temp))
            with self.assertRaises(WorkflowError) as raised:
                workflow.validate_modules(
                    "blue_reflection_original",
                    ["blue_reflection_translation", "quartet_restoration"],
                )
            self.assertEqual(raised.exception.code, "unsupported_modules")


class SyntheticWorkflow(LocalTranslationWorkflow):
    def __init__(self, project_root: Path, target_id: str):
        write_route_registry(project_root)
        super().__init__(project_root)
        self.target_id_for_test = target_id
        self.calls: list[str] = []

    def ensure_project(self) -> None:
        self.calls.append("ensure_project")

    def ensure_patcher(self, force: bool = False) -> Path:
        self.calls.append("ensure_patcher")
        self.patcher = self.project_root / "fake-patcher"
        return self.patcher

    def detect_target(self, game_root: Path):
        self.calls.append("detect_target")
        self.report.game_root = str(game_root)
        self.report.target_id = self.target_id_for_test
        self.report.display_name = self.target_id_for_test
        return {"root": str(game_root), "target_id": self.target_id_for_test, "display_name": self.target_id_for_test}

    def installation_status(self, game_root: Path):
        self.calls.append("installation_status")
        return {"automatic_prepare_allowed": True, "active_state": {"active": False}, "baseline": {}}

    def prepare_target_workspace(self, target_id: str, game_root: Path, status, gust_pak: Path) -> Path:
        self.calls.append("prepare_target_workspace")
        path = self.project_root / "workspace-map.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{}", encoding="utf-8")
        return path

    def validate_translation_prerequisites(self) -> None:
        self.calls.append("validate_translation_prerequisites")

    def find_tool(self, variable: str, executable: str) -> Path:
        self.calls.append(f"find_tool:{executable}")
        return self.project_root / executable

    def build_loose(self, target_id: str, workspace_map: Path) -> None:
        self.calls.append("build_loose")

    def repack(self, gust_pak: Path) -> None:
        self.calls.append("repack")

    def marker_source_root(self, target_id: str, game_root: Path, status) -> Path:
        self.calls.append("marker_source_root")
        return game_root

    def build_marker(self, target_id: str, source_root: Path, modules, gust_pak: Path) -> None:
        self.calls.append("build_marker")

    def maybe_build_composition(self, target_id: str, game_root: Path, modules, gust_pak: Path) -> None:
        self.calls.append("composition" if "quartet_restoration" in modules else "composition_skipped")

    def payload_preview(self, game_root: Path, modules):
        self.calls.append("payload_preview")
        return {"status": "ready"}

    def prepare(self, game_root: Path, modules):
        self.calls.append("prepare")
        return {
            "status": "prepared",
            "journal_path": "/state/journal.json",
            "baseline_manifest_path": "/state/baseline.json",
            "commit_enabled": True,
        }

    def commit(self, journal_path: str):
        self.calls.append("commit")
        return {"status": "installed", "journal_path": journal_path}


class SyntheticWorkflowSequenceTests(unittest.TestCase):
    def test_translation_workflow_prepares_in_one_run(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            workflow = SyntheticWorkflow(Path(temp), "blue_reflection_original")
            report = workflow.run(
                game_root=Path(temp) / "game",
                modules=["blue_reflection_translation"],
                preview_only=False,
            )
            self.assertEqual(report.status, "prepared")
            self.assertTrue(report.commit_enabled)
            self.assertEqual(
                workflow.calls[-6:],
                ["repack", "marker_source_root", "build_marker", "composition_skipped", "payload_preview", "prepare"],
            )


    def test_translation_workflow_installs_only_when_requested(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            workflow = SyntheticWorkflow(Path(temp), "blue_reflection_original")
            report = workflow.run(
                game_root=Path(temp) / "game",
                modules=["blue_reflection_translation"],
                preview_only=False,
                install=True,
            )
            self.assertEqual(report.status, "installed")
            self.assertTrue(report.game_files_modified)
            self.assertFalse(report.commit_enabled)
            self.assertEqual(workflow.calls[-2:], ["prepare", "commit"])

    def test_preview_only_rejects_install(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            workflow = SyntheticWorkflow(Path(temp), "blue_reflection_original")
            with self.assertRaises(WorkflowError) as raised:
                workflow.run(
                    game_root=Path(temp) / "game",
                    modules=["blue_reflection_translation"],
                    preview_only=True,
                    install=True,
                )
            self.assertEqual(raised.exception.code, "conflicting_mode")

    def test_quartet_combined_workflow_requests_composition(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            workflow = SyntheticWorkflow(Path(temp), "blue_reflection_quartet")
            report = workflow.run(
                game_root=Path(temp) / "game",
                modules=["blue_reflection_translation", "quartet_restoration"],
                preview_only=True,
            )
            self.assertEqual(report.status, "ready_preview_only")
            self.assertFalse(report.commit_enabled)
            self.assertIn("composition", workflow.calls)
            self.assertNotIn("prepare", workflow.calls)

    def test_translation_plus_legacy_dlc_composition_path_has_defined_translation_module(self) -> None:
        class CompositionProbe(LocalTranslationWorkflow):
            def __init__(self, project_root: Path):
                write_route_registry(project_root)
                super().__init__(project_root)
                self.patcher = project_root / "fake-patcher"
                self.calls: list[str] = []

            def record_step(self, name, command, *, cwd=None, env=None, note="") -> None:
                self.calls.append(name)
                command = [str(value) for value in command]
                if "--json" in command:
                    path = Path(command[command.index("--json") + 1])
                    path.parent.mkdir(parents=True, exist_ok=True)
                    if name == "quartet_composition_preview":
                        path.write_text(json.dumps({"status": "ready_for_composition_build", "archives": []}), encoding="utf-8")
                    else:
                        path.write_text(json.dumps({"status": "ok"}), encoding="utf-8")

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            workflow = CompositionProbe(root)
            workflow.maybe_build_composition(
                "blue_reflection_quartet",
                root / "game",
                ["blue_reflection_translation", "quartet_legacy_dlc"],
                root / "gust_pak",
            )
            self.assertEqual(
                workflow.calls,
                ["quartet_composition_preview", "quartet_composition_build"],
            )



    def test_ensure_project_captures_workstream_versions(self):
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary)
            for relative in [
                "Blue_Reflection_Patcher/go.mod",
                "Blue_Reflection_Text_Tool/br_text_tool.py",
                "config/text_source_archives.tsv",
            ]:
                path = project / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("fixture\n", encoding="utf-8")
            routing = project / "config/translation_target_routes.json"
            routing.write_text(json.dumps({
                "type": "br_translation_target_routes",
                "format_version": 1,
                "installation_targets": {
                    "blue_reflection_original": {
                        "module_id": "blue_reflection_translation",
                        "content_targets": ["blue_reflection"],
                    }
                },
                "content_targets": {
                    "blue_reflection": {
                        "installation_target_id": "blue_reflection_original"
                    }
                },
            }), encoding="utf-8")
            versions = {
                "core": "0.0.46",
                "translation_tooling": "0.0.54",
                "translation": "0.0.123",
                "quartet_restoration": "0.1.37",
                "quartet_legacy_dlc": "0.0.39",
            }
            for workstream_id, version in versions.items():
                path = project / "workstreams" / workstream_id / "VERSION"
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(version + "\n", encoding="utf-8")
            workflow = LocalTranslationWorkflow(project)
            workflow.ensure_project()
            self.assertEqual(workflow.report.core_version, "0.0.46")
            self.assertEqual(workflow.report.translation_tooling_version, "0.0.54")
            self.assertEqual(workflow.report.translation_version, "0.0.123")
            self.assertEqual(workflow.report.quartet_restoration_version, "0.1.37")
            self.assertEqual(workflow.report.quartet_legacy_dlc_version, "0.0.39")

if __name__ == "__main__":
    unittest.main()
