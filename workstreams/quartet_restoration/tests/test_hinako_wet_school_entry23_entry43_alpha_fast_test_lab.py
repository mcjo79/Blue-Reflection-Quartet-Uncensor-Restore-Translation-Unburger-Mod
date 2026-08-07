from __future__ import annotations

import hashlib
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

WORKSTREAM = Path(__file__).resolve().parents[1]
TOOL_PATH = WORKSTREAM / "162_hinako_wet_school_entry23_entry43_alpha_fast_test_lab.py"
SPEC = importlib.util.spec_from_file_location("stage162_wet_school_entry23_entry43_alpha", TOOL_PATH)
assert SPEC and SPEC.loader
mod = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(mod)


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class WetSchoolEntry23Entry43AlphaFastTestLabTests(unittest.TestCase):
    def setUp(self) -> None:
        self.td = tempfile.TemporaryDirectory()
        root = Path(self.td.name)
        self.project = root / "project"
        self.game = root / "game"
        (self.project / "workstreams/quartet_restoration").mkdir(parents=True)
        (self.project / "workstreams/quartet_restoration/VERSION").write_text("0.1.83\n", encoding="utf-8")
        (self.project / ".local/reports/quartet_restoration").mkdir(parents=True)
        (self.game / "Data").mkdir(parents=True)
        self.baseline = b"BASELINE-PACK10-02\n" * 64
        self.profile = b"PROFILE-PACK10-02\n" * 63
        self.guard_payloads = {
            "Data/PACK10_01.PAK": b"guard-10-01\n",
            "Data/PACK10_03.PAK": b"guard-10-03\n",
            "Data/PACK11.PAK": b"guard-11\n",
        }
        (self.game / mod.TARGET_RELATIVE_PATH).write_bytes(self.baseline)
        for rel, payload in self.guard_payloads.items():
            (self.game / rel).write_bytes(payload)
        self.originals = {
            "BASELINE_SHA256": mod.BASELINE_SHA256,
            "BASELINE_SIZE": mod.BASELINE_SIZE,
            "PROFILE_SHA256": mod.PROFILE_SHA256,
            "PROFILE_SIZE": mod.PROFILE_SIZE,
            "PROFILE_RELATIVE_PATH": mod.PROFILE_RELATIVE_PATH,
            "validate_stage161_report": mod.validate_stage161_report,
            "validate_manifest": mod.validate_manifest,
        }
        mod.BASELINE_SHA256 = digest(self.baseline)
        mod.BASELINE_SIZE = len(self.baseline)
        mod.PROFILE_SHA256 = digest(self.profile)
        mod.PROFILE_SIZE = len(self.profile)
        mod.PROFILE_RELATIVE_PATH = ".local/build/test/profile/PACK10_02.PAK"
        profile_path = self.project / mod.PROFILE_RELATIVE_PATH
        profile_path.parent.mkdir(parents=True)
        profile_path.write_bytes(self.profile)
        mod.validate_stage161_report = lambda report_root: {"status": "fixture"}
        mod.validate_manifest = lambda project_root: {"profile_id": mod.PROFILE_ID}

    def tearDown(self) -> None:
        for key, value in self.originals.items():
            setattr(mod, key, value)
        self.td.cleanup()

    def target(self) -> Path:
        return self.game / mod.TARGET_RELATIVE_PATH

    def test_preflight_accepts_exact_baseline_and_profile(self) -> None:
        result = mod.preflight(self.project, self.game, show_progress=False)
        self.assertEqual(result["mode"], "activate")
        self.assertEqual(result["installed_sha256"], digest(self.baseline))
        self.assertEqual(len(result["guard_rows"]), 3)
        self.assertFalse(result["runtime_validated"])

    def test_preflight_rejects_baseline_drift(self) -> None:
        self.target().write_bytes(b"drift")
        with self.assertRaises(mod.WetSchoolEntry23Entry43AlphaFastTestError):
            mod.preflight(self.project, self.game, show_progress=False)

    def test_preflight_rejects_profile_drift(self) -> None:
        (self.project / mod.PROFILE_RELATIVE_PATH).write_bytes(b"wrong-profile")
        with self.assertRaises(mod.WetSchoolEntry23Entry43AlphaFastTestError):
            mod.preflight(self.project, self.game, show_progress=False)

    def test_activate_targets_only_pack10_02_and_creates_hardlink_backup(self) -> None:
        before_guards = {rel: digest((self.game / rel).read_bytes()) for rel in self.guard_payloads}
        state = mod.activate(self.project, self.game, show_progress=False)
        self.assertEqual(state["status"], "active")
        self.assertEqual(self.target().read_bytes(), self.profile)
        backup = self.game / state["backup_relative_path"]
        self.assertTrue(backup.is_file())
        self.assertEqual(backup.read_bytes(), self.baseline)
        for rel, before in before_guards.items():
            self.assertEqual(digest((self.game / rel).read_bytes()), before)

    def test_activate_is_recoverably_idempotent_when_already_active(self) -> None:
        first = mod.activate(self.project, self.game, show_progress=False)
        second = mod.activate(self.project, self.game, show_progress=False)
        self.assertEqual(first["transaction_id"], second["transaction_id"])
        self.assertEqual(second["status"], "active")
        self.assertEqual(self.target().read_bytes(), self.profile)

    def test_rollback_restores_exact_baseline_and_removes_backup(self) -> None:
        active = mod.activate(self.project, self.game, show_progress=False)
        backup = self.game / active["backup_relative_path"]
        rolled = mod.rollback(self.project, self.game, show_progress=False)
        self.assertEqual(rolled["status"], "rolled_back")
        self.assertTrue(rolled["exact_baseline_restored"])
        self.assertEqual(self.target().read_bytes(), self.baseline)
        self.assertFalse(backup.exists())

    def test_rollback_does_not_require_local_profile_after_activation(self) -> None:
        mod.activate(self.project, self.game, show_progress=False)
        (self.project / mod.PROFILE_RELATIVE_PATH).unlink()
        state = mod.rollback(self.project, self.game, show_progress=False)
        self.assertEqual(state["status"], "rolled_back")
        self.assertEqual(self.target().read_bytes(), self.baseline)

    def test_post_activation_guard_failure_auto_restores_baseline(self) -> None:
        original_compare = mod.compare_guards
        calls = {"n": 0}
        def fail_after_activation(root, expected, *, show_progress):
            calls["n"] += 1
            if calls["n"] >= 1:
                raise mod.WetSchoolEntry23Entry43AlphaFastTestError("synthetic guard failure")
            return original_compare(root, expected, show_progress=show_progress)
        mod.compare_guards = fail_after_activation
        try:
            with self.assertRaises(mod.WetSchoolEntry23Entry43AlphaFastTestError):
                mod.activate(self.project, self.game, show_progress=False)
        finally:
            mod.compare_guards = original_compare
        self.assertEqual(self.target().read_bytes(), self.baseline)
        state = mod.load_state(self.project)
        self.assertEqual(state["status"], "rolled_back")
        self.assertTrue(state["exact_baseline_restored"])

    def test_rollback_refuses_active_target_drift(self) -> None:
        mod.activate(self.project, self.game, show_progress=False)
        self.target().write_bytes(b"external-drift")
        with self.assertRaises(mod.WetSchoolEntry23Entry43AlphaFastTestError):
            mod.rollback(self.project, self.game, show_progress=False)

    def test_rollback_refuses_protected_guard_drift(self) -> None:
        mod.activate(self.project, self.game, show_progress=False)
        (self.game / "Data/PACK10_03.PAK").write_bytes(b"changed-guard")
        with self.assertRaises(mod.WetSchoolEntry23Entry43AlphaFastTestError):
            mod.rollback(self.project, self.game, show_progress=False)

    def test_activation_report_is_metadata_only(self) -> None:
        state = mod.activate(self.project, self.game, show_progress=False)
        archive = mod.build_report(self.project, self.game, state, operation="activation", show_progress=False)
        self.assertTrue(archive.is_file())
        listing = __import__("subprocess").run(["tar", "--zstd", "-tf", str(archive)], text=True, capture_output=True, check=True).stdout.splitlines()
        self.assertTrue(listing)
        self.assertFalse(any(name.casefold().endswith(mod.FORBIDDEN_REPORT_EXTENSIONS) for name in listing))
        summary = json.loads((self.project / ".local/reports/quartet_restoration" / mod.ACTIVATION_REPORT_DIR / "SUMMARY.json").read_text())
        self.assertEqual(summary["observed_target_sha256"], digest(self.profile))
        self.assertFalse(summary["runtime_validated"])
        self.assertTrue(summary["glowlight_deferred"])

    def test_rollback_report_confirms_exact_baseline(self) -> None:
        mod.activate(self.project, self.game, show_progress=False)
        state = mod.rollback(self.project, self.game, show_progress=False)
        mod.build_report(self.project, self.game, state, operation="rollback", show_progress=False)
        summary = json.loads((self.project / ".local/reports/quartet_restoration" / mod.ROLLBACK_REPORT_DIR / "SUMMARY.json").read_text())
        self.assertTrue(summary["exact_pack10_02_baseline_restored"])
        self.assertEqual(summary["observed_target_sha256"], digest(self.baseline))
        self.assertTrue(summary["protected_archives_unchanged"])

    def test_shell_wrapper_requires_explicit_authorization_token(self) -> None:
        text = (WORKSTREAM / "158_hinako_wet_school_entry23_fast_test_lab.sh").read_text(encoding="utf-8")
        self.assertIn("--user-authorized-wet-school-entry23-test", text)
        self.assertIn("PACK10_01, PACK10_03 and PACK11", text)
        self.assertIn("rollback", text)


if __name__ == "__main__":
    unittest.main()
