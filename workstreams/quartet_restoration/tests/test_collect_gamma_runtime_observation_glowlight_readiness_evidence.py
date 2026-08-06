from __future__ import annotations

import hashlib
import importlib.util
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

WORKSTREAM = Path(__file__).resolve().parents[1]
PROJECT = WORKSTREAM.parent.parent
MODULE_PATH = WORKSTREAM / "145_collect_gamma_runtime_observation_glowlight_readiness_evidence.py"
SPEC = importlib.util.spec_from_file_location("stage145", MODULE_PATH)
assert SPEC and SPEC.loader
stage145 = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = stage145
SPEC.loader.exec_module(stage145)


class GammaRuntimeObservationGlowLightReadinessTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="stage145-tests-")
        self.root = Path(self.temp.name)
        self.project = self.root / "project"
        self.ws = self.project / "workstreams/quartet_restoration"
        self.reports = self.project / ".local/reports/quartet_restoration"
        self.output = self.root / "output"
        self.ws.mkdir(parents=True)
        self.reports.mkdir(parents=True)
        (self.ws / "VERSION").write_text("0.1.63\n", encoding="utf-8")
        for name in ["GAMMA_RUNTIME_OBSERVATION.json", "RUNTIME_VALIDATION_REGISTRY.json", "STATUS.json"]:
            shutil.copy2(WORKSTREAM / name, self.ws / name)
        for name in [stage145.STAGE143_REPORT, stage145.ACTIVATION_REPORT, stage145.ROLLBACK_REPORT]:
            shutil.copy2(PROJECT / ".local/reports/quartet_restoration" / name, self.reports / name)
        self.old_observation_sha = stage145.OBSERVATION_SHA256

    def tearDown(self) -> None:
        stage145.OBSERVATION_SHA256 = self.old_observation_sha
        self.temp.cleanup()

    def _update_observation(self, mutator) -> None:
        path = self.ws / "GAMMA_RUNTIME_OBSERVATION.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        mutator(data)
        path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
        stage145.OBSERVATION_SHA256 = hashlib.sha256(path.read_bytes()).hexdigest()

    def test_real_completed_tree_builds_metadata_only_report(self) -> None:
        archive, summary = stage145.build_report(PROJECT, output_report_root=self.output)
        self.assertIsNotNone(archive)
        assert archive is not None
        self.assertTrue(archive.is_file())
        self.assertEqual(summary["status"], "gamma_runtime_stable_visual_effect_unconfirmed_canonically_verified_glowlight_separate_test_technically_ready_but_not_authorized")
        self.assertTrue(summary["gamma_runtime_stable"])
        self.assertFalse(summary["gamma_visible_effect_confirmed"])
        self.assertFalse(summary["gamma_runtime_validated"])
        self.assertFalse(summary["gamma_production_eligible"])
        self.assertFalse(summary["glowlight_activation_authorized"])
        names = subprocess.check_output(["tar", "--zstd", "-tf", str(archive)], text=True).splitlines()
        self.assertFalse(any(name.casefold().endswith(stage145.FORBIDDEN_REPORT_EXTENSIONS) for name in names))

    def test_gamma_registry_is_stable_visual_unconfirmed_and_nonproduction(self) -> None:
        registry = json.loads((self.ws / "RUNTIME_VALIDATION_REGISTRY.json").read_text())
        row = registry["fast_test_results"][stage145.GAMMA_PROFILE_ID]
        self.assertEqual(row["runtime_status"], "runtime_stable_visual_effect_unconfirmed")
        self.assertTrue(row["runtime_stable"])
        self.assertFalse(row["visible_effect_confirmed"])
        self.assertFalse(row["runtime_validated"])
        self.assertFalse(row["production_eligible"])
        self.assertIsNone(row["confirmed_semantics"])
        self.assertFalse(row["gamma_retest_required"])

    def test_observation_preserves_bathroom_profile_context(self) -> None:
        observation = json.loads((self.ws / "GAMMA_RUNTIME_OBSERVATION.json").read_text())
        context = observation["test_context"]
        self.assertEqual(context["bathroom_water_profile_id"], stage145.BATHROOM_PROFILE_ID)
        self.assertEqual(context["bathroom_water_target_relative_path"], stage145.BATHROOM_TARGET_RELATIVE_PATH)
        self.assertTrue(context["bathroom_water_profile_was_active"])
        self.assertTrue(observation["exact_pack10_01_baseline_restored"])

    def test_glowlight_is_ready_only_as_separate_unauthorized_test(self) -> None:
        _, summary = stage145.build_report(self.project, output_report_root=self.output)
        self.assertTrue(summary["glowlight_stage143_profile_preparation_verified"])
        self.assertTrue(summary["glowlight_separate_test_technically_ready_after_exact_baseline_preflight"])
        self.assertFalse(summary["glowlight_runtime_tested"])
        self.assertFalse(summary["glowlight_runtime_validated"])
        self.assertFalse(summary["glowlight_production_eligible"])
        self.assertFalse(summary["glowlight_activation_authorized"])
        self.assertTrue(summary["glowlight_requires_separate_user_authorization"])
        self.assertTrue(summary["policy"]["glowlight_exact_rollback_required"])
        self.assertTrue(summary["policy"]["pack10_03_must_not_be_modified"])

    def test_visual_confirmation_cannot_be_invented(self) -> None:
        self._update_observation(lambda data: data.__setitem__("visible_effect_confirmed", True))
        with self.assertRaisesRegex(stage145.Stage145Error, "visual effect must remain unconfirmed"):
            stage145.build_report(self.project, output_report_root=self.output)

    def test_gamma_runtime_validation_promotion_fails_closed(self) -> None:
        path = self.ws / "RUNTIME_VALIDATION_REGISTRY.json"
        data = json.loads(path.read_text())
        data["fast_test_results"][stage145.GAMMA_PROFILE_ID]["runtime_validated"] = True
        path.write_text(json.dumps(data, indent=2) + "\n")
        with self.assertRaisesRegex(stage145.Stage145Error, "Gamma registry drift: runtime_validated"):
            stage145.build_report(self.project, output_report_root=self.output)

    def test_glowlight_activation_authorization_fails_closed(self) -> None:
        path = self.ws / "STATUS.json"
        data = json.loads(path.read_text())
        data["gamma_runtime_observation_glowlight_readiness_stage"]["glowlight_activation_authorized"] = True
        path.write_text(json.dumps(data, indent=2) + "\n")
        with self.assertRaisesRegex(stage145.Stage145Error, "GlowLight activation must remain unauthorized"):
            stage145.build_report(self.project, output_report_root=self.output)

    def test_rollback_report_hash_drift_fails_closed(self) -> None:
        path = self.reports / stage145.ROLLBACK_REPORT
        path.write_bytes(path.read_bytes() + b"drift")
        with self.assertRaisesRegex(stage145.Stage145Error, "gamma_rollback SHA-256 drift"):
            stage145.build_report(self.project, output_report_root=self.output)

    def test_gamma_retest_is_explicitly_not_required(self) -> None:
        _, summary = stage145.build_report(self.project, output_report_root=self.output)
        self.assertFalse(summary["gamma_retest_required"])
        self.assertFalse(summary["policy"]["gamma_repeat_test_required"])
        self.assertIn("do not repeat it", summary["next_action"].lower())

    def test_stage145_never_authorizes_a_write(self) -> None:
        _, summary = stage145.build_report(self.project, output_report_root=self.output)
        policy = summary["policy"]
        self.assertTrue(policy["metadata_only"])
        self.assertFalse(policy["installed_game_read"])
        self.assertFalse(policy["installed_game_modified"])
        self.assertFalse(policy["pak_built_or_repacked"])
        self.assertFalse(policy["profile_activated"])
        self.assertFalse(policy["core_modified"])
        self.assertFalse(policy["translation_modified"])
        self.assertFalse(policy["legacy_dlc_modified"])
        self.assertFalse(policy["git_modified"])


if __name__ == "__main__":
    unittest.main()
