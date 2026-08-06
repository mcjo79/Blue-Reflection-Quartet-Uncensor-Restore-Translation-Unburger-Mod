from __future__ import annotations

import csv
import hashlib
import importlib.util
import json
import subprocess
import tempfile
import unittest
from pathlib import Path

WORKSTREAM = Path(__file__).resolve().parents[1]
MODULE_PATH = WORKSTREAM / "146_glowlight_fast_test_lab.py"
spec = importlib.util.spec_from_file_location("stage146", MODULE_PATH)
assert spec and spec.loader
stage146 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(stage146)


def write_tsv(path: Path, fields: list[str], rows: list[dict]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, delimiter="\t", lineterminator="\n")
        writer.writeheader(); writer.writerows(rows)


class GlowLightFastTestLabTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.project = self.root / "project"; self.project.mkdir()
        self.game = self.root / "game"; (self.game / "Data").mkdir(parents=True)
        self.reports = self.project / ".local/reports/quartet_restoration"; self.reports.mkdir(parents=True)
        self.workstream = self.project / "workstreams/quartet_restoration"; self.workstream.mkdir(parents=True)
        (self.workstream / "VERSION").write_text(stage146.TOOL_VERSION + "\n")
        core = self.project / "Blue_Reflection_Patcher/cmd"; core.mkdir(parents=True)
        route = core / "br_quartet_shader_profile.sh"; route.write_text("#!/bin/sh\nexit 0\n"); route.chmod(0o755)

        self.old = {k: getattr(stage146, k) for k in (
            "BASELINE_SHA256", "BASELINE_SIZE", "GLOWLIGHT_PROFILE_SHA256", "GLOWLIGHT_PROFILE_SIZE",
            "STAGE143_SHA256", "STAGE145_SHA256",
        )}
        self.baseline = b"baseline-pack10-01"
        self.profile = b"glowlight-pack10-01"
        self.pack10_03 = b"validated-water-pack10-03"
        stage146.BASELINE_SHA256 = hashlib.sha256(self.baseline).hexdigest(); stage146.BASELINE_SIZE = len(self.baseline)
        stage146.GLOWLIGHT_PROFILE_SHA256 = hashlib.sha256(self.profile).hexdigest(); stage146.GLOWLIGHT_PROFILE_SIZE = len(self.profile)
        (self.game / stage146.TARGET_RELATIVE_PATH).write_bytes(self.baseline)
        (self.game / stage146.PROTECTED_PACK10_03_RELATIVE_PATH).write_bytes(self.pack10_03)

        self.local_profile_rel = ".local/build/quartet_restoration/fast_test_lab/test_glow/output/Data/PACK10_01.PAK"
        pp = self.project / self.local_profile_rel; pp.parent.mkdir(parents=True); pp.write_bytes(self.profile)
        manifest = {
            "schema_version": 1, "profile_id": stage146.GLOWLIGHT_PROFILE_ID,
            "target_relative_path": stage146.TARGET_RELATIVE_PATH,
            "baseline_sha256": stage146.BASELINE_SHA256, "baseline_size": stage146.BASELINE_SIZE,
            "profile_sha256": stage146.GLOWLIGHT_PROFILE_SHA256, "profile_size": stage146.GLOWLIGHT_PROFILE_SIZE,
            "changed_member_count": 1, "runtime_validated": False, "workstream_id": "quartet_restoration",
            "changed_members": ["data/b1/x64/posteffect/pe_pack.elixir.gz"], "local_profile_path": self.local_profile_rel,
        }
        mp = self.project / stage146.MANIFEST_RELATIVE_PATH; mp.parent.mkdir(parents=True); mp.write_text(json.dumps(manifest))
        self.manifest_path = mp
        self._make_registry()
        self._make_stage143()
        self._make_stage145()

    def tearDown(self) -> None:
        for k,v in self.old.items(): setattr(stage146,k,v)
        self.temp.cleanup()

    def _archive(self, source: Path, output: Path) -> str:
        cp=subprocess.run(["tar","--zstd","-cf",str(output),"-C",str(source.parent),source.name],text=True,capture_output=True)
        self.assertEqual(cp.returncode,0,cp.stderr)
        return hashlib.sha256(output.read_bytes()).hexdigest()

    def _make_registry(self) -> None:
        registry = {
            "fast_test_results": {stage146.GAMMA_PROFILE_ID: {
                "runtime_status":"runtime_stable_visual_effect_unconfirmed", "runtime_tested":True, "runtime_stable":True,
                "visible_effect_confirmed":False, "runtime_validated":False, "production_eligible":False,
                "exact_pack10_01_baseline_restored":True, "pack10_01_baseline_sha256":stage146.BASELINE_SHA256,
            }},
            "policy": {"glowlight_requires_separate_runtime_evidence":True, "glowlight_activation_requires_separate_user_authorization":True},
        }
        (self.workstream / "RUNTIME_VALIDATION_REGISTRY.json").write_text(json.dumps(registry))

    def _make_stage143(self) -> None:
        source=self.root/stage146.STAGE143_ROOT; source.mkdir(parents=True)
        fields=["profile_id","test_order","member_name","profile_pak_sha256","profile_pak_size","local_profile_path","runtime_validated","normal_composer_eligible","installed"]
        write_tsv(source/"FAST_TEST_LAB_PROFILES.tsv",fields,[
            {"profile_id":stage146.GAMMA_PROFILE_ID,"test_order":1,"member_name":"PostEffectGamma.kps","profile_pak_sha256":"a"*64,"profile_pak_size":1,"local_profile_path":"x","runtime_validated":False,"normal_composer_eligible":False,"installed":False},
            {"profile_id":stage146.GLOWLIGHT_PROFILE_ID,"test_order":2,"member_name":"PostEffectGlowLight.kps","profile_pak_sha256":stage146.GLOWLIGHT_PROFILE_SHA256,"profile_pak_size":stage146.GLOWLIGHT_PROFILE_SIZE,"local_profile_path":self.local_profile_rel,"runtime_validated":False,"normal_composer_eligible":False,"installed":False},
        ])
        write_tsv(source/"FAST_TEST_ORDER.tsv",["test_order","profile_id","must_be_tested_alone","rollback_required_before_next_variant","automatic_activation_authorized"],[
            {"test_order":1,"profile_id":stage146.GAMMA_PROFILE_ID,"must_be_tested_alone":True,"rollback_required_before_next_variant":True,"automatic_activation_authorized":False},
            {"test_order":2,"profile_id":stage146.GLOWLIGHT_PROFILE_ID,"must_be_tested_alone":True,"rollback_required_before_next_variant":True,"automatic_activation_authorized":False},
        ])
        archive=self.reports/stage146.STAGE143_REPORT
        stage146.STAGE143_SHA256=self._archive(source,archive)

    def _make_stage145(self) -> None:
        source=self.root/stage146.STAGE145_ROOT; source.mkdir(parents=True)
        summary={
            "tool_version":"0.1.63","status":"gamma_runtime_stable_visual_effect_unconfirmed_canonically_verified_glowlight_separate_test_technically_ready_but_not_authorized",
            "gamma_runtime_tested":True,"gamma_runtime_stable":True,"gamma_visible_effect_confirmed":False,"gamma_runtime_validated":False,"gamma_production_eligible":False,"gamma_retest_required":False,
            "exact_pack10_01_baseline_restored":True,"glowlight_runtime_tested":False,"glowlight_runtime_validated":False,"glowlight_production_eligible":False,
            "glowlight_separate_test_technically_ready_after_exact_baseline_preflight":True,"glowlight_activation_authorized":False,"glowlight_requires_separate_user_authorization":True,
            "glowlight_profile_id":stage146.GLOWLIGHT_PROFILE_ID,"glowlight_profile_sha256":stage146.GLOWLIGHT_PROFILE_SHA256,"pack10_01_baseline_sha256":stage146.BASELINE_SHA256,"skipped_rows":0,
            "policy":{"glowlight_must_be_tested_separately":True,"glowlight_exact_pack10_01_baseline_preflight_required":True,"glowlight_exact_rollback_required":True,"pack10_03_must_not_be_modified":True},
        }
        (source/"SUMMARY.json").write_text(json.dumps(summary))
        archive=self.reports/stage146.STAGE145_REPORT
        stage146.STAGE145_SHA256=self._archive(source,archive)

    def _write_state_report(self, status: str) -> None:
        state_path=self.project/stage146.STATE_RELATIVE_PATH; state_path.parent.mkdir(parents=True,exist_ok=True)
        state={"status":status,"profile_id":stage146.GLOWLIGHT_PROFILE_ID,"target_relative_path":stage146.TARGET_RELATIVE_PATH,
               "baseline_sha256":stage146.BASELINE_SHA256,"active_profile_sha256":stage146.GLOWLIGHT_PROFILE_SHA256,"runtime_validated":False,"transaction_id":"t1"}
        state_path.write_text(json.dumps(state))
        report_path=self.project/stage146.CORE_REPORT_RELATIVE_PATH; report_path.parent.mkdir(parents=True,exist_ok=True)
        report={"status":"ok","operation":"activate" if status=="active" else "rollback","profile_id":stage146.GLOWLIGHT_PROFILE_ID,"state_status":status,"runtime_validated":False}
        report_path.write_text(json.dumps(report))

    def test_preflight_accepts_exact_baseline_and_records_pack10_03_hash(self):
        result=stage146.preflight(self.project,self.game,self.reports)
        self.assertEqual(result["mode"],"activate")
        self.assertEqual(result["pack10_03_sha256"],hashlib.sha256(self.pack10_03).hexdigest())

    def test_stage145_hash_drift_fails_closed(self):
        stage146.STAGE145_SHA256="0"*64
        with self.assertRaisesRegex(stage146.GlowLightFastTestError,"stage-145 evidence SHA-256 drift"):
            stage146.preflight(self.project,self.game,self.reports)

    def test_gamma_canonical_record_required(self):
        p=self.workstream/"RUNTIME_VALIDATION_REGISTRY.json"; d=json.loads(p.read_text()); d["fast_test_results"]={}; p.write_text(json.dumps(d))
        with self.assertRaisesRegex(stage146.GlowLightFastTestError,"Gamma Fast Test result missing"):
            stage146.preflight(self.project,self.game,self.reports)

    def test_existing_glowlight_runtime_result_blocks_retest(self):
        p=self.workstream/"RUNTIME_VALIDATION_REGISTRY.json"; d=json.loads(p.read_text()); d["fast_test_results"][stage146.GLOWLIGHT_PROFILE_ID]={}; p.write_text(json.dumps(d))
        with self.assertRaisesRegex(stage146.GlowLightFastTestError,"already exists"):
            stage146.preflight(self.project,self.game,self.reports)

    def test_baseline_drift_fails_closed(self):
        (self.game/stage146.TARGET_RELATIVE_PATH).write_bytes(b"drift")
        with self.assertRaisesRegex(stage146.GlowLightFastTestError,"baseline drift"):
            stage146.preflight(self.project,self.game,self.reports)

    def test_manifest_runtime_promotion_fails_closed(self):
        d=json.loads(self.manifest_path.read_text()); d["runtime_validated"]=True; self.manifest_path.write_text(json.dumps(d))
        with self.assertRaisesRegex(stage146.GlowLightFastTestError,"runtime_validated"):
            stage146.preflight(self.project,self.game,self.reports)

    def test_other_shader_profile_blocks_glowlight(self):
        state=self.project/stage146.STATE_RELATIVE_PATH; state.parent.mkdir(parents=True,exist_ok=True)
        state.write_text(json.dumps({"status":"active","profile_id":stage146.GAMMA_PROFILE_ID}))
        with self.assertRaisesRegex(stage146.GlowLightFastTestError,"another PACK10_01 profile"):
            stage146.preflight(self.project,self.game,self.reports)

    def test_prepare_guard_and_pack10_03_drift_detection(self):
        guard=stage146.prepare_guard(self.project,self.game,self.reports)
        self.assertTrue(guard.is_file())
        stage146.validate_pack10_03_guard(self.project,self.game)
        (self.game/stage146.PROTECTED_PACK10_03_RELATIVE_PATH).write_bytes(b"changed")
        with self.assertRaisesRegex(stage146.GlowLightFastTestError,"PACK10_03 changed"):
            stage146.validate_pack10_03_guard(self.project,self.game)

    def test_active_validation_and_evidence_keep_runtime_unvalidated(self):
        stage146.prepare_guard(self.project,self.game,self.reports)
        (self.game/stage146.TARGET_RELATIVE_PATH).write_bytes(self.profile)
        self._write_state_report("active")
        state,report,guard=stage146.validate_active(self.project,self.game)
        self.assertFalse(state["runtime_validated"]); self.assertEqual(report["profile_id"],stage146.GLOWLIGHT_PROFILE_ID)
        archive=stage146.write_report(self.project,self.game,self.reports,operation="activation")
        self.assertTrue(archive.is_file())
        names=subprocess.check_output(["tar","--zstd","-tf",str(archive)],text=True).splitlines()
        self.assertFalse(any(name.casefold().endswith(stage146.FORBIDDEN_REPORT_EXTENSIONS) for name in names))

    def test_rollback_requires_exact_baseline_and_unchanged_pack10_03(self):
        stage146.prepare_guard(self.project,self.game,self.reports)
        self._write_state_report("rolled_back")
        stage146.validate_rolled_back(self.project,self.game)
        archive=stage146.write_report(self.project,self.game,self.reports,operation="rollback")
        self.assertTrue(archive.is_file())

    def test_shell_wrapper_requires_explicit_authorization_token_and_only_glowlight(self):
        text=(WORKSTREAM/"146_glowlight_fast_test_lab.sh").read_text()
        self.assertIn(stage146.GLOWLIGHT_PROFILE_ID,text)
        self.assertNotIn(stage146.GAMMA_PROFILE_ID,text)
        self.assertIn("--user-authorized-glowlight-test",text)
        self.assertIn('activate "$PROFILE_ID"',text)

    def test_update_documents_activation_as_unauthorized(self):
        status=json.loads((WORKSTREAM/"STATUS.json").read_text())['glowlight_fast_test_lab_runtime_stage']
        self.assertFalse(status['activation_authorized_by_update'])
        self.assertFalse(status['installed_game_modified_by_update'])
        self.assertTrue(status['pack10_03_guard_required'])


if __name__ == "__main__":
    unittest.main()
