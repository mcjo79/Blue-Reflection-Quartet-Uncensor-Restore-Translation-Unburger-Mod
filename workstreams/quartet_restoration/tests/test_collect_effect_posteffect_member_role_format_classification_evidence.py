from __future__ import annotations

import csv
import importlib.util
import subprocess
import tempfile
import unittest
from pathlib import Path

WORKSTREAM = Path(__file__).resolve().parents[1]
PROJECT = WORKSTREAM.parent.parent
TOOL_PATH = WORKSTREAM / "135_collect_effect_posteffect_member_role_format_classification_evidence.py"
SPEC = importlib.util.spec_from_file_location("stage135_tool", TOOL_PATH)
assert SPEC and SPEC.loader
TOOL = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(TOOL)


def read_tsv(path: Path):
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


class EffectPosteffectMemberRoleFormatClassificationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory(prefix="stage135-tests-")
        cls.root = Path(cls.tmp.name)
        cls.archive, cls.summary = TOOL.build_report(PROJECT, output_report_root=cls.root, create_archive=True)
        cls.report = cls.root / TOOL.REPORT_DIR
        cls.members = read_tsv(cls.report / "EFFECT_POSTEFFECT_MEMBER_FORMAT_CLASSIFICATION.tsv")
        cls.roles = read_tsv(cls.report / "EFFECT_POSTEFFECT_MEMBER_ROLE_FORMAT_CLASSIFICATION.tsv")
        cls.formats = read_tsv(cls.report / "EFFECT_POSTEFFECT_FORMAT_FAMILY_SUMMARY.tsv")
        cls.burden = read_tsv(cls.report / "EFFECT_POSTEFFECT_CONTAINER_FORMAT_BURDEN.tsv")
        cls.shaders = read_tsv(cls.report / "BOUNDED_SHADER_UNRESOLVED_CARRY_FORWARD.tsv")

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_exact_stage134_prerequisite_is_preserved(self):
        self.assertEqual(self.summary["stage134_report_sha256"], TOOL.STAGE134_SHA256)
        self.assertEqual(self.summary["stage134_summary_sha256"], TOOL.STAGE134_SUMMARY_SHA256)

    def test_all_nonidentical_members_are_classified(self):
        self.assertEqual(len(self.members), 658)
        self.assertEqual(self.summary["nonidentical_member_rows"], 658)
        self.assertEqual(self.summary["changed_same_size_member_rows"], 270)
        self.assertEqual(self.summary["changed_grew_member_rows"], 367)
        self.assertEqual(self.summary["changed_shrank_member_rows"], 20)
        self.assertEqual(self.summary["target_added_member_rows"], 1)

    def test_all_role_families_are_classified(self):
        self.assertEqual(len(self.roles), 602)
        self.assertEqual(self.summary["member_role_family_rows"], 602)
        self.assertEqual(self.summary["recurrent_member_role_family_rows"], 32)
        self.assertEqual(self.summary["unique_or_singleton_member_role_family_rows"], 570)

    def test_recurrence_partition_is_exact(self):
        self.assertEqual(self.summary["three_container_recurrent_role_family_rows"], 8)
        self.assertEqual(self.summary["two_container_recurrent_role_family_rows"], 24)
        self.assertEqual(self.summary["recurrent_role_member_rows"], 72)
        self.assertEqual(self.summary["unique_or_singleton_role_member_rows"], 586)

    def test_format_partitions_are_exact(self):
        self.assertEqual(self.summary["g1e_member_rows"], 621)
        self.assertEqual(self.summary["g1em_member_rows"], 6)
        self.assertEqual(self.summary["g1t_member_rows"], 4)
        self.assertEqual(self.summary["kps_member_rows"], 27)
        self.assertEqual(self.summary["g1e_role_family_rows"], 570)
        self.assertEqual(self.summary["g1em_role_family_rows"], 3)
        self.assertEqual(self.summary["g1t_role_family_rows"], 2)
        self.assertEqual(self.summary["kps_role_family_rows"], 27)

    def test_all_seven_containers_have_burden_rows(self):
        self.assertEqual(len(self.burden), 7)
        self.assertEqual(self.summary["container_path_rows"], 7)
        self.assertEqual(self.summary["effect_container_path_rows"], 6)
        self.assertEqual(self.summary["posteffect_container_path_rows"], 1)
        self.assertTrue(all(int(row["nonidentical_member_rows"]) > 0 for row in self.burden))

    def test_posteffect_is_isolated_as_kps(self):
        row = next(row for row in self.burden if row["namespace"] == "posteffect")
        self.assertEqual(int(row["kps_member_rows"]), 27)
        self.assertEqual(int(row["g1e_member_rows"]), 0)
        self.assertEqual(int(row["target_added_rows"]), 1)

    def test_recurrent_model_and_texture_controls_remain_nonsemantic(self):
        by_role = {row["normalized_member_role"]: row for row in self.roles}
        self.assertEqual(by_role["e_{pc}_model.g1em"]["recurrence_scope"], "three_container_recurrence")
        self.assertEqual(by_role["e_{pc}_texture.g1t"]["recurrence_scope"], "three_container_recurrence")
        self.assertEqual(by_role["e_{pc}_model.g1em"]["visual_or_censorship_semantics_confirmed"], "False")

    def test_all_bounded_shaders_remain_unresolved(self):
        self.assertEqual(len(self.shaders), 15)
        self.assertEqual(self.summary["resolved_shader_dependency_binding_rows"], 0)
        self.assertTrue(all(row["dependency_binding_resolved"] == "False" for row in self.shaders))
        self.assertTrue(all(row["stage135_disposition"] == "carry_forward_unresolved_no_independent_binding_channel" for row in self.shaders))

    def test_no_visual_runtime_or_write_authorization(self):
        self.assertEqual(self.summary["visual_or_censorship_semantics_confirmed_rows"], 0)
        self.assertEqual(self.summary["runtime_confirmed_rows"], 0)
        self.assertEqual(self.summary["write_authorized_rows"], 0)
        self.assertTrue(all(row["write_authorized"] == "False" for row in self.members))

    def test_existing_evidence_only_policy_is_closed(self):
        policy = self.summary["policy"]
        self.assertTrue(policy["existing_evidence_only"])
        self.assertFalse(policy["local_proprietary_payloads_read"])
        self.assertFalse(policy["runtime_or_save_required"])
        self.assertFalse(policy["installed_game_modified"])
        self.assertFalse(policy["git_modified"])

    def test_report_archive_contains_no_payload_extensions(self):
        names = subprocess.run(
            ["tar", "--zstd", "-tf", str(self.archive)],
            text=True,
            capture_output=True,
            check=True,
        ).stdout.splitlines()
        self.assertFalse(any(name.casefold().endswith(TOOL.FORBIDDEN_EXTENSIONS) for name in names))

    def test_next_action_is_format_specific_static_analysis(self):
        self.assertIn("621 changed G1E", self.summary["next_action"])
        self.assertIn("27 changed/added KPS", self.summary["next_action"])
        self.assertIn("Do not require saves", self.summary["next_action"])


if __name__ == "__main__":
    unittest.main()
