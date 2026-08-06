from __future__ import annotations
import importlib.util,json,os,tempfile,unittest
from pathlib import Path
MODULE_PATH=Path(__file__).resolve().parents[1]/"br_dlc_bkn_generation9_publish_tool.py"
SPEC=importlib.util.spec_from_file_location("gen9_sem_gate_test",MODULE_PATH); assert SPEC and SPEC.loader
MOD=importlib.util.module_from_spec(SPEC); SPEC.loader.exec_module(MOD)
class Tests(unittest.TestCase):
    def make(self,with_g9=True):
        t=tempfile.TemporaryDirectory(); self.addCleanup(t.cleanup); r=Path(t.name)
        (r/"workstreams/core").mkdir(parents=True); (r/"workstreams/core/VERSION").write_text("9.9.9\n")
        p=r/"Blue_Reflection_Patcher/internal/plan/payloadpreview/legacy_dlc_policy.json"; p.parent.mkdir(parents=True)
        pol={"type":"br_quartet_legacy_dlc_manifest_policy","format_version":1,"source_kind":"validated_quartet_legacy_dlc_handoff","target_id":"blue_reflection_quartet","families":[{"family_id":"bkn_dry","transaction_group":"quartet_legacy_dlc_bkn_dry","member_id_pattern":"^costume_(pc[0-9]{2})_bkn$","minimum_members":1,"maximum_members":32,"artifacts":[{"target_path":"Data/PACK10_02.PAK","operation":"replace","added_member_templates":["data/b1/x64/character/{member_key}/{member_key}_dlc_bkn.elixir.gz","data/b1/x64/character/{member_key}/{member_key}_dlc_bkn.g1t"],"changed_members":[],"removed_members":[]},{"target_path":"Data/PACK12.PAK","operation":"replace","added_member_templates":[],"changed_members":["saves/b1/chara/charabase.xml"],"removed_members":[],"additional_changed_member_sets":[list(MOD.PACK12_CHANGED_MEMBERS)] if with_g9 else []}]}]}
        p.write_text(json.dumps(pol))
        files={"workstreams/core/contracts/quartet_legacy_dlc/VALIDATED_QUARTET_LEGACY_DLC_PAYLOAD.schema.json":"{}","workstreams/core/contracts/quartet_legacy_dlc/GENERIC_ADAPTER_RETURN_CONTRACT.json":"{}","workstreams/core/tools/validate_quartet_legacy_dlc_active_manifest.sh":"validate_quartet_legacy_dlc_preview_result.py\n","workstreams/core/tools/validate_quartet_legacy_dlc_preview_result.py":"structured_rejection_reason artifacts\n"}
        for rel,c in files.items(): q=r/rel; q.parent.mkdir(parents=True,exist_ok=True); q.write_text(c)
        os.chmod(r/"workstreams/core/tools/validate_quartet_legacy_dlc_active_manifest.sh",0o755); return r
    def test_unrelated_source_change_allowed(self):
        r=self.make(); s=r/"Blue_Reflection_Patcher/internal/plan/payloadpreview/legacy_dlc.go"; s.write_text("// progress bar\n")
        v,o=MOD.verify_core_contract(r,{"core_contract_gates":{str(s):"0"*64}}); self.assertEqual(v,"9.9.9"); self.assertNotIn(str(s),o)
    def test_missing_g9_rejected(self):
        with self.assertRaises(MOD.Generation9PublishError): MOD.verify_core_contract(self.make(False),{})
if __name__=="__main__": unittest.main()
