from __future__ import annotations

import csv
import importlib.util
import subprocess
import tempfile
import unittest
from pathlib import Path

WORKSTREAM = Path(__file__).resolve().parents[1]
PROJECT = WORKSTREAM.parent.parent
TOOL_PATH = WORKSTREAM / "132_collect_field_member_role_format_classification_evidence.py"
SPEC = importlib.util.spec_from_file_location("stage132_tool", TOOL_PATH)
assert SPEC and SPEC.loader
TOOL = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(TOOL)


def read_tsv(path: Path):
    with path.open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f, delimiter="\t"))


class FieldMemberRoleFormatClassificationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory(prefix="stage132-tests-")
        cls.root = Path(cls.tmp.name)
        cls.archive, cls.summary = TOOL.build_report(PROJECT, output_report_root=cls.root, create_archive=True)
        cls.report = cls.root / TOOL.REPORT_DIR
        cls.shapes = read_tsv(cls.report / "FIELD_ARCHIVE_DELTA_SHAPE_CLASSIFICATION.tsv")
        cls.roles = read_tsv(cls.report / "FIELD_MEMBER_ROLE_FORMAT_CLASSIFICATION.tsv")
        cls.formats = read_tsv(cls.report / "FIELD_FORMAT_FAMILY_SUMMARY.tsv")
        cls.roots = read_tsv(cls.report / "FIELD_SCENE_ROOT_FORMAT_BURDEN.tsv")

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_exact_stage131_prerequisite_is_preserved(self):
        self.assertEqual(self.summary["stage131_report_sha256"], TOOL.STAGE131_SHA256)
        self.assertEqual(self.summary["stage131_summary_sha256"], TOOL.STAGE131_SUMMARY_SHA256)

    def test_all_archive_shapes_are_classified(self):
        self.assertEqual(len(self.shapes), 143)
        self.assertEqual(self.summary["archive_delta_shape_rows"], 143)
        self.assertEqual(self.summary["recurrent_archive_delta_shape_rows"], 6)
        self.assertEqual(self.summary["broad_recurrent_archive_delta_shape_rows"], 3)

    def test_all_member_role_families_are_classified(self):
        self.assertEqual(len(self.roles), 2796)
        self.assertEqual(self.summary["member_role_family_rows"], 2796)
        self.assertEqual(self.summary["recurrent_member_role_family_rows"], 801)
        self.assertEqual(self.summary["unique_or_singleton_member_role_family_rows"], 1995)

    def test_recurrent_scope_partition_is_exact(self):
        self.assertEqual(self.summary["broad_recurrent_member_role_family_rows"], 93)
        self.assertEqual(self.summary["bounded_recurrent_member_role_family_rows"], 706)
        self.assertEqual(self.summary["scene_local_repeated_member_role_family_rows"], 2)
        self.assertEqual(93 + 706 + 2, 801)

    def test_member_row_partition_is_preserved(self):
        self.assertEqual(self.summary["recurrent_role_member_rows"], 5000)
        self.assertEqual(self.summary["broad_recurrent_role_member_rows"], 1762)
        self.assertEqual(self.summary["unique_or_singleton_role_member_rows"], 1995)

    def test_format_families_cover_major_formats(self):
        self.assertEqual(self.summary["g1m_role_family_rows"], 2363)
        self.assertEqual(self.summary["g1co_role_family_rows"], 308)
        self.assertEqual(self.summary["g1t_role_family_rows"], 26)
        self.assertEqual(self.summary["g1s_role_family_rows"], 17)
        self.assertEqual(len(self.formats), 32)

    def test_widespread_texture_and_layout_roles_are_broad_not_semantic(self):
        by_role = {(r["normalized_member_role"], r["classification"], r["size_delta"]): r for r in self.roles}
        for key in (("{field_root}_as.g1t", "changed", "0"), ("{field_root}.opl2", "changed", "0")):
            row = by_role[key]
            self.assertEqual(row["recurrence_scope"], "broad_cross_scene_recurrence")
            self.assertEqual(row["visual_or_censorship_semantics_confirmed"], "False")

    def test_all_105_scene_roots_receive_format_burden_rows(self):
        self.assertEqual(len(self.roots), 105)
        self.assertEqual(self.summary["field_scene_root_rows"], 105)
        self.assertTrue(all(int(r["nonidentical_member_rows"]) > 0 for r in self.roots))

    def test_no_visual_runtime_or_write_authorization(self):
        self.assertEqual(self.summary["visual_or_censorship_semantics_confirmed_rows"], 0)
        self.assertEqual(self.summary["runtime_confirmed_rows"], 0)
        self.assertEqual(self.summary["write_authorized_rows"], 0)
        self.assertTrue(all(r["write_authorized"] == "False" for r in self.roles))

    def test_existing_evidence_only_policy_is_closed(self):
        p = self.summary["policy"]
        self.assertTrue(p["existing_evidence_only"])
        self.assertFalse(p["local_proprietary_payloads_read"])
        self.assertFalse(p["runtime_or_save_required"])
        self.assertFalse(p["installed_game_modified"])
        self.assertFalse(p["git_modified"])

    def test_report_archive_contains_no_payload_extensions(self):
        names = subprocess.run(["tar", "--zstd", "-tf", str(self.archive)], text=True, capture_output=True, check=True).stdout.splitlines()
        self.assertFalse(any(name.casefold().endswith(TOOL.FORBIDDEN_EXTENSIONS) for name in names))

    def test_next_action_is_shader_sweep_not_runtime(self):
        self.assertIn("214-path shader", self.summary["next_action"])
        self.assertIn("Do not require saves", self.summary["next_action"])


if __name__ == "__main__":
    unittest.main()
