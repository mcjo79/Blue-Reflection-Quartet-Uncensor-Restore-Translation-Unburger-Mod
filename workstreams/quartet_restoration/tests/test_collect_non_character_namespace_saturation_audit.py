from __future__ import annotations

import csv
import importlib.util
import subprocess
import tempfile
import unittest
from pathlib import Path

WORKSTREAM = Path(__file__).resolve().parents[1]
PROJECT = WORKSTREAM.parent.parent
TOOL_PATH = WORKSTREAM / "130_collect_non_character_namespace_saturation_audit.py"
SPEC = importlib.util.spec_from_file_location("stage130_tool", TOOL_PATH)
assert SPEC and SPEC.loader
TOOL = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(TOOL)


def read_tsv(path: Path):
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


class NonCharacterNamespaceSaturationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.tmp = tempfile.TemporaryDirectory(prefix="stage130-tests-")
        cls.output = Path(cls.tmp.name) / "reports"
        cls.archive, cls.summary = TOOL.build_report(PROJECT, output_report_root=cls.output)
        cls.report = cls.output / TOOL.REPORT_DIR
        cls.namespaces = read_tsv(cls.report / "NON_CHARACTER_NAMESPACE_SUMMARY.tsv")
        cls.candidates = read_tsv(cls.report / "NON_CHARACTER_TECHNICAL_CANDIDATES.tsv")
        cls.fields = read_tsv(cls.report / "FIELD_SCENE_ROOT_SUMMARY.tsv")
        cls.focused = read_tsv(cls.report / "KNOWN_FOCUSED_PATH_COVERAGE.tsv")
        cls.queue = read_tsv(cls.report / "NON_CHARACTER_DISCOVERY_QUEUE.tsv")

    @classmethod
    def tearDownClass(cls) -> None:
        cls.tmp.cleanup()

    def test_complete_asset_space_is_partitioned(self):
        self.assertEqual(self.summary["asset_difference_rows"], 7566)
        self.assertEqual(self.summary["character_namespace_rows"], 3525)
        self.assertEqual(self.summary["localization_boundary_rows"], 3121)
        self.assertEqual(self.summary["non_character_technical_rows"], 920)
        self.assertEqual(3525 + 3121 + 920, 7566)

    def test_technical_candidate_counts_are_exact(self):
        self.assertEqual(self.summary["technical_nonidentical_candidate_rows"], 539)
        self.assertEqual(self.summary["technical_changed_rows"], 512)
        self.assertEqual(self.summary["technical_new_in_target_rows"], 24)
        self.assertEqual(self.summary["technical_removed_in_target_rows"], 3)
        self.assertEqual(len(self.candidates), 539)

    def test_namespace_breakdown_is_complete(self):
        by_name = {row["namespace"]: row for row in self.namespaces}
        self.assertEqual(int(by_name["field"]["nonidentical_rows"]), 318)
        self.assertEqual(int(by_name["shader"]["nonidentical_rows"]), 214)
        self.assertEqual(int(by_name["effect"]["nonidentical_rows"]), 6)
        self.assertEqual(int(by_name["posteffect"]["nonidentical_rows"]), 1)
        self.assertEqual(self.summary["technical_namespace_rows"], 10)

    def test_field_scene_roots_are_bounded_without_semantics(self):
        self.assertEqual(len(self.fields), 105)
        self.assertEqual(self.summary["field_lexical_signal_root_rows"], 23)
        self.assertEqual(self.summary["field_lexical_signal_path_rows"], 69)
        self.assertTrue(all(row["lexical_signal_only_not_semantics"] in {"True", "False"} for row in self.fields))

    def test_shader_family_partition_is_exact(self):
        shader_rows = [row for row in self.candidates if row["namespace"] == "shader"]
        self.assertEqual(len(shader_rows), 214)
        self.assertEqual(sum(row["shader_family"] == "generated_variant" for row in shader_rows), 150)
        self.assertEqual(sum(row["shader_family"] == "named_shader_or_texture" for row in shader_rows), 64)

    def test_known_focused_paths_are_only_a_small_subset(self):
        self.assertEqual(len(self.focused), 19)
        self.assertEqual(self.summary["known_focused_non_character_path_rows"], 19)
        self.assertEqual(self.summary["unfocused_non_character_candidate_rows"], 520)
        self.assertEqual(sum(row["known_focused_discovery_path"] == "True" for row in self.candidates), 19)

    def test_cwater_pair_is_closed_only_at_executable_code_level(self):
        water = {row["normalized_path"]: row for row in self.focused}
        for path in ("data/x64/shader/cwater.g1s", "data/x64/shader/cwater2.g1s"):
            self.assertEqual(water[path]["current_static_disposition"], "stage129_no_executable_shader_delta")
        self.assertEqual(self.summary["water_shader_executable_code_delta_rows"], 0)

    def test_caustics_remains_bounded_without_visual_semantics(self):
        caustics = next(row for row in self.focused if row["normalized_path"].endswith("caustics.g1t"))
        self.assertIn("no_selector_or_semantics", caustics["current_static_disposition"])
        self.assertEqual(self.summary["caustics_target_only_subsystem_pair_rows"], 1)

    def test_queue_covers_every_active_namespace(self):
        self.assertEqual([row["namespace"] for row in self.queue], ["field", "shader", "effect", "posteffect"])
        self.assertEqual(sum(int(row["candidate_path_rows"]) for row in self.queue), 539)
        self.assertEqual(sum(int(row["remaining_unfocused_path_rows"]) for row in self.queue), 520)
        self.assertTrue(all(row["runtime_or_save_required"] == "False" for row in self.queue))

    def test_no_semantics_runtime_or_write_is_authorized(self):
        self.assertEqual(self.summary["runtime_confirmed_rows"], 0)
        self.assertEqual(self.summary["visual_or_censorship_semantics_confirmed_rows"], 0)
        self.assertEqual(self.summary["write_authorized_rows"], 0)
        self.assertFalse(self.summary["policy"]["installed_game_modified"])
        self.assertFalse(self.summary["policy"]["pak_built_or_repacked"])

    def test_report_is_metadata_only(self):
        self.assertIsNotNone(self.archive)
        names = subprocess.run(["tar", "--zstd", "-tf", str(self.archive)], text=True, capture_output=True, check=True).stdout.splitlines()
        self.assertFalse(any(name.casefold().endswith(TOOL.FORBIDDEN_EXTENSIONS) for name in names))

    def test_unsafe_relative_paths_are_rejected(self):
        for value in ("../escape", "/absolute", "a/../../b"):
            with self.assertRaises(TOOL.AuditError):
                TOOL.safe_relative(value, "test")


if __name__ == "__main__":
    unittest.main()
