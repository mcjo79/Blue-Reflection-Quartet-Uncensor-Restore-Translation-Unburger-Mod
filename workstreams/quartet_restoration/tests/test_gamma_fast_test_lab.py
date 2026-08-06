from __future__ import annotations

import csv
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
MODULE_PATH = WORKSTREAM / "144_gamma_fast_test_lab.py"
SPEC = importlib.util.spec_from_file_location("stage144", MODULE_PATH)
assert SPEC and SPEC.loader
stage144 = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = stage144
SPEC.loader.exec_module(stage144)
CORE_ROOT = PROJECT / "Blue_Reflection_Patcher"


def write_tsv(path: Path, fields: list[str], rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


class GammaFastTestLabTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="stage144-tests-")
        self.root = Path(self.temp.name)
        self.project = self.root / "project"
        self.game = self.root / "game"
        self.reports = self.project / ".local/reports/quartet_restoration"
        self.project.mkdir()
        self.game.joinpath("Data").mkdir(parents=True)
        self.project.joinpath("workstreams/quartet_restoration").mkdir(parents=True)
        self.project.joinpath("workstreams/quartet_restoration/VERSION").write_text(stage144.TOOL_VERSION + "\n")
        core_wrapper = self.project / "Blue_Reflection_Patcher/cmd/br_quartet_shader_profile.sh"
        core_wrapper.parent.mkdir(parents=True)
        core_wrapper.write_text("#!/usr/bin/env bash\nexit 0\n")
        core_wrapper.chmod(0o755)
        self.baseline = b"synthetic PACK10_01 baseline\n"
        self.profile = b"synthetic Gamma PACK10_01 profile\n"
        self.old = {
            "BASELINE_SHA256": stage144.BASELINE_SHA256,
            "BASELINE_SIZE": stage144.BASELINE_SIZE,
            "GAMMA_PROFILE_SHA256": stage144.GAMMA_PROFILE_SHA256,
            "GAMMA_PROFILE_SIZE": stage144.GAMMA_PROFILE_SIZE,
            "STAGE143_SHA256": stage144.STAGE143_SHA256,
        }
        stage144.BASELINE_SHA256 = hashlib.sha256(self.baseline).hexdigest()
        stage144.BASELINE_SIZE = len(self.baseline)
        stage144.GAMMA_PROFILE_SHA256 = hashlib.sha256(self.profile).hexdigest()
        stage144.GAMMA_PROFILE_SIZE = len(self.profile)
        self.installed = self.game / stage144.TARGET_RELATIVE_PATH
        self.installed.parent.mkdir(parents=True, exist_ok=True)
        self.installed.write_bytes(self.baseline)
        self.local_profile_rel = ".local/build/quartet_restoration/fast_test_lab/tests/gamma/Data/PACK10_01.PAK"
        local_profile = self.project / self.local_profile_rel
        local_profile.parent.mkdir(parents=True)
        local_profile.write_bytes(self.profile)
        manifest = {
            "schema_version": 1,
            "profile_id": stage144.GAMMA_PROFILE_ID,
            "target_relative_path": stage144.TARGET_RELATIVE_PATH,
            "baseline_sha256": stage144.BASELINE_SHA256,
            "baseline_size": stage144.BASELINE_SIZE,
            "profile_sha256": stage144.GAMMA_PROFILE_SHA256,
            "profile_size": stage144.GAMMA_PROFILE_SIZE,
            "local_profile_path": self.local_profile_rel,
            "changed_member_count": 1,
            "changed_members": ["data/b1/x64/posteffect/pe_pack.elixir.gz"],
            "runtime_validated": False,
            "workstream_id": "quartet_restoration",
            "workstream_version": stage144.TOOL_VERSION,
        }
        self.manifest_path = self.project / stage144.MANIFEST_RELATIVE_PATH
        self.manifest_path.parent.mkdir(parents=True)
        self.manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
        self._make_stage143()

    def tearDown(self) -> None:
        for key, value in self.old.items():
            setattr(stage144, key, value)
        self.temp.cleanup()

    def _make_stage143(self) -> None:
        source = self.root / stage144.STAGE143_ROOT
        source.mkdir(parents=True)
        summary = {
            "tool_version": "0.1.61",
            "status": "two_isolated_runtime_unvalidated_kps_fast_test_lab_profiles_built_and_reextracted_no_install",
            "target_relative_path": stage144.TARGET_RELATIVE_PATH,
            "baseline_sha256": stage144.BASELINE_SHA256,
            "baseline_size": stage144.BASELINE_SIZE,
            "fast_test_profile_rows": 2,
            "gamma_profile_rows": 1,
            "glowlight_profile_rows": 1,
            "runtime_validated_profile_rows_created": 0,
            "normal_composer_eligible_profile_rows_created": 0,
            "profile_pak_rows_built": 2,
            "profile_pak_full_reextraction_pass_rows": 2,
            "automatic_activation_rows": 0,
            "installed_artifact_rows": 0,
            "skipped_rows": 0,
            "policy": {
                "profile_paks_fully_reextracted": True,
                "test_order_gamma_before_glowlight": True,
                "rollback_required_between_variants": True,
                "profiles_runtime_validated": False,
                "profiles_normal_composer_eligible": False,
                "automatic_activation_authorized": False,
                "installed_game_modified": False,
            },
        }
        (source / "SUMMARY.json").write_text(json.dumps(summary, indent=2) + "\n")
        fields = ["profile_id", "test_order", "member_name", "profile_pak_sha256", "profile_pak_size", "local_profile_path", "runtime_validated", "normal_composer_eligible", "installed"]
        write_tsv(source / "FAST_TEST_LAB_PROFILES.tsv", fields, [
            {"profile_id": stage144.GAMMA_PROFILE_ID, "test_order": 1, "member_name": "PostEffectGamma.kps", "profile_pak_sha256": stage144.GAMMA_PROFILE_SHA256, "profile_pak_size": stage144.GAMMA_PROFILE_SIZE, "local_profile_path": self.local_profile_rel, "runtime_validated": False, "normal_composer_eligible": False, "installed": False},
            {"profile_id": stage144.GLOWLIGHT_PROFILE_ID, "test_order": 2, "member_name": "PostEffectGlowLight.kps", "profile_pak_sha256": "f" * 64, "profile_pak_size": 1, "local_profile_path": ".local/build/quartet_restoration/fast_test_lab/tests/glow/Data/PACK10_01.PAK", "runtime_validated": False, "normal_composer_eligible": False, "installed": False},
        ])
        write_tsv(source / "FAST_TEST_ORDER.tsv", ["test_order", "profile_id", "variant", "rollback_required_before_next_variant"], [
            {"test_order": 1, "profile_id": stage144.GAMMA_PROFILE_ID, "variant": "gamma", "rollback_required_before_next_variant": True},
            {"test_order": 2, "profile_id": stage144.GLOWLIGHT_PROFILE_ID, "variant": "glowlight", "rollback_required_before_next_variant": True},
        ])
        self.reports.mkdir(parents=True)
        archive = self.reports / stage144.STAGE143_REPORT
        cp = subprocess.run(["tar", "--zstd", "-cf", str(archive), "-C", str(source.parent), source.name], text=True, capture_output=True)
        self.assertEqual(cp.returncode, 0, cp.stderr)
        stage144.STAGE143_SHA256 = hashlib.sha256(archive.read_bytes()).hexdigest()

    def _core(self, command: str) -> None:
        cp = subprocess.run([
            "go", "run", "./cmd/brpatcher", command,
            "--project-root", str(self.project), "--game-root", str(self.game),
            *([stage144.GAMMA_PROFILE_ID] if command.endswith("activate") else []),
        ], cwd=CORE_ROOT, text=True, capture_output=True, timeout=120)
        self.assertEqual(cp.returncode, 0, cp.stderr + cp.stdout)

    def test_preflight_accepts_exact_baseline(self) -> None:
        result = stage144.preflight(self.project, self.game, self.reports)
        self.assertEqual(result["mode"], "activate")

    def test_stage143_hash_drift_fails_closed(self) -> None:
        stage144.STAGE143_SHA256 = "0" * 64
        with self.assertRaisesRegex(stage144.GammaFastTestError, "stage-143 SHA-256 drift"):
            stage144.preflight(self.project, self.game, self.reports)

    def test_baseline_drift_fails_closed(self) -> None:
        self.installed.write_bytes(b"drift")
        with self.assertRaisesRegex(stage144.GammaFastTestError, "baseline drift"):
            stage144.preflight(self.project, self.game, self.reports)

    def test_manifest_runtime_promotion_fails_closed(self) -> None:
        manifest = json.loads(self.manifest_path.read_text())
        manifest["runtime_validated"] = True
        self.manifest_path.write_text(json.dumps(manifest))
        with self.assertRaisesRegex(stage144.GammaFastTestError, "runtime_validated"):
            stage144.preflight(self.project, self.game, self.reports)

    def test_profile_payload_drift_fails_closed(self) -> None:
        manifest = json.loads(self.manifest_path.read_text())
        path = self.project / manifest["local_profile_path"]
        path.write_bytes(self.profile + b"drift")
        with self.assertRaisesRegex(stage144.GammaFastTestError, "size drift"):
            stage144.preflight(self.project, self.game, self.reports)

    def test_open_event_transaction_blocks_gamma(self) -> None:
        state = self.project / ".local/state/core_unified_patcher/quartet_event_profile.json"
        state.parent.mkdir(parents=True)
        state.write_text(json.dumps({"status": "active", "profile_id": "event_profile"}))
        with self.assertRaisesRegex(stage144.GammaFastTestError, "open event"):
            stage144.preflight(self.project, self.game, self.reports)

    def test_core_activation_and_metadata_evidence(self) -> None:
        self._core("quartet-shader-profile-activate")
        state, report = stage144.validate_active(self.project, self.game)
        self.assertFalse(state["runtime_validated"])
        self.assertEqual(report["profile_id"], stage144.GAMMA_PROFILE_ID)
        archive = stage144.write_report(self.project, self.game, self.reports, operation="activation")
        self.assertTrue(archive.is_file())
        self.assertEqual(self.installed.read_bytes(), self.profile)
        with tempfile.TemporaryDirectory() as td:
            subprocess.run(["tar", "--zstd", "-xf", str(archive), "-C", td], check=True)
            root = Path(td) / stage144.ACTIVATION_REPORT_DIR
            summary = json.loads((root / "SUMMARY.json").read_text())
            self.assertEqual(summary["core_state_status"], "active")
            self.assertFalse(summary["runtime_validated"])
            self.assertFalse(summary["glowlight_activated"])
            names = subprocess.check_output(["tar", "--zstd", "-tf", str(archive)], text=True).splitlines()
            self.assertFalse(any(name.casefold().endswith(stage144.FORBIDDEN_REPORT_EXTENSIONS) for name in names))

    def test_active_gamma_preflight_is_idempotent(self) -> None:
        self._core("quartet-shader-profile-activate")
        result = stage144.preflight(self.project, self.game, self.reports)
        self.assertEqual(result["mode"], "already_active")

    def test_other_shader_profile_state_blocks_gamma(self) -> None:
        state = self.project / stage144.STATE_RELATIVE_PATH
        state.parent.mkdir(parents=True, exist_ok=True)
        state.write_text(json.dumps({"status": "active", "profile_id": stage144.GLOWLIGHT_PROFILE_ID}))
        self.installed.write_bytes(self.profile)
        with self.assertRaisesRegex(stage144.GammaFastTestError, "another PACK10_01 profile"):
            stage144.preflight(self.project, self.game, self.reports)

    def test_core_rollback_restores_exact_baseline_and_evidence(self) -> None:
        self._core("quartet-shader-profile-activate")
        self._core("quartet-shader-profile-rollback")
        state, report = stage144.validate_rolled_back(self.project, self.game)
        self.assertEqual(state["status"], "rolled_back")
        self.assertEqual(report["state_status"], "rolled_back")
        self.assertEqual(self.installed.read_bytes(), self.baseline)
        archive = stage144.write_report(self.project, self.game, self.reports, operation="rollback")
        self.assertTrue(archive.is_file())
        with tempfile.TemporaryDirectory() as td:
            subprocess.run(["tar", "--zstd", "-xf", str(archive), "-C", td], check=True)
            summary = json.loads((Path(td) / stage144.ROLLBACK_REPORT_DIR / "SUMMARY.json").read_text())
            self.assertTrue(summary["exact_baseline_restored"])
            self.assertFalse(summary["glowlight_activated"])

    def test_shell_wrapper_hardcodes_only_gamma_activation(self) -> None:
        text = (WORKSTREAM / "144_gamma_fast_test_lab.sh").read_text()
        self.assertIn(stage144.GAMMA_PROFILE_ID, text)
        self.assertNotIn(stage144.GLOWLIGHT_PROFILE_ID, text)
        self.assertIn('activate "$PROFILE_ID"', text)

    def test_report_matrix_keeps_glowlight_blocked(self) -> None:
        self._core("quartet-shader-profile-activate")
        archive = stage144.write_report(self.project, self.game, self.reports, operation="activation")
        with tempfile.TemporaryDirectory() as td:
            subprocess.run(["tar", "--zstd", "-xf", str(archive), "-C", td], check=True)
            with (Path(td) / stage144.ACTIVATION_REPORT_DIR / "RUNTIME_TEST_MATRIX.tsv").open(encoding="utf-8", newline="") as handle:
                rows = list(csv.DictReader(handle, delimiter="\t"))
            glow = next(row for row in rows if row["variant"] == "glowlight")
            self.assertEqual(glow["result_status"], "blocked")


if __name__ == "__main__":
    unittest.main()
