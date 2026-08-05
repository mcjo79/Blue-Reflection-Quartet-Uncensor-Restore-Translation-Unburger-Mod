#!/usr/bin/env python3
from __future__ import annotations
import csv, importlib.util, json, tempfile, unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[3]
PATH=ROOT/'workstreams/quartet_restoration/collect_reflector_light_family_binary_evidence.py'
spec=importlib.util.spec_from_file_location('stage80',PATH);assert spec and spec.loader
TOOL=importlib.util.module_from_spec(spec);spec.loader.exec_module(TOOL)
def wj(p,d):p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(d)+'\n',encoding='utf-8')
def wt(p,fields,rows):
 p.parent.mkdir(parents=True,exist_ok=True)
 with p.open('w',encoding='utf-8',newline='') as f:
  w=csv.DictWriter(f,fieldnames=fields,delimiter='\t',lineterminator='\n');w.writeheader();w.writerows(rows)
class T(unittest.TestCase):
 def setUp(self):
  self.t=tempfile.TemporaryDirectory();self.p=Path(self.t.name);self.r=self.p/'.local/reports/quartet_restoration';self.r.mkdir(parents=True)
  r79=self.r/TOOL.STAGE79_DIR
  wj(r79/'SUMMARY.json',{'type':'br_quartet_restoration_reflector_character_slot_render_member_evidence_summary','tool_version':'0.0.92','character_slot_rows':15,'slot_member_rows':220,'ringlight_family_rows':5,'eyelight_family_rows':2,'policy':{}})
  self.scope=[]
  for i in range(15):
   self.scope.append({'character_slot':f'PC{i:02d}','asset_role':'ringlight','family_key':'ringlight:e_cmn_ringlight_PCXX.g1e','normalized_path':'data/x64/effect/100_common.elixir.gz','member_name':f'e_cmn_ringlight_PC{i:02d}.g1e','member_key':f'e_cmn_ringlight_pc{i:02d}.g1e#0','candidate_id':'common','domain':'d','priority':'high','change_classification':'changed','evidence_sources':'x','lead_classification':'x','review_status':'x'})
  extras=[('PC00','ringlight','ringlight:e_PCXX_ringlight_a.g1e','a'),('PC01','ringlight','ringlight:e_PCXX_h2_ringlight_00.g1e','b'),('PC01','ringlight','ringlight:e_PCXX_ringlight_00.g1e','c'),('PC02','ringlight','ringlight:e_PCXX_w5_ringlight_01.g1e','d'),('PC00','eyelight','eyelight:e_PCXX_eyelight_00.g1e','e'),('PC00','eyelight','eyelight:e_PCXX_eyelight_01.g1e','f')]
  for slot,role,family,suffix in extras:
   self.scope.append({'character_slot':slot,'asset_role':role,'family_key':family,'normalized_path':f'data/x64/effect/{suffix}.elixir.gz','member_name':f'{suffix}.g1e','member_key':f'{suffix}.g1e#0','candidate_id':suffix,'domain':'d','priority':'high','change_classification':'changed','evidence_sources':'x','lead_classification':'x','review_status':'x'})
  fields=list(self.scope[0])
  wt(r79/'REFLECTOR_SLOT_RENDER_MEMBERS.tsv',fields,self.scope)
  shader=self.r/TOOL.SHADER_DIR
  wj(shader/'SUMMARY.json',{'type':'br_quartet_restoration_shader_effect_evidence_summary','status':'focused_shader_effect_posteffect_evidence_complete_manual_confirmation_required','skipped_rows':0,'tool_version':'x'})
  binary=self.r/TOOL.BINARY_DIR
  wj(binary/'SUMMARY.json',{'type':'br_quartet_restoration_binary_delta_evidence_summary','status':'focused_binary_and_DXBC_chunk_delta_complete_controlled_prototypes_not_generated','skipped_rows':0,'tool_version':'y'})
  self.pairs=[]; render=[]; deltas=[]
  for row in self.scope:
   source=bytearray(64);target=bytearray(source);source[16:20]=b'ABCD';target[16:20]=b'WXYZ'
   if row['family_key']!='ringlight:e_cmn_ringlight_PCXX.g1e':
    source[24:28]=b'1234';target[24:28]=b'5678'
   source=bytes(source);target=bytes(target)
   pair={**row,'source_member_name':row['member_name'],'target_member_name':row['member_name'],'source_payload':source,'target_payload':target}
   self.pairs.append(pair)
   for side,payload in [('source',source),('target',target)]:
    render.append({'candidate_id':row['candidate_id'],'normalized_path':row['normalized_path'],'member_key':row['member_key'],'side':side,'payload_size':len(payload),'payload_sha256':TOOL.sha256(payload)})
   deltas.append({'candidate_id':row['candidate_id'],'normalized_path':row['normalized_path'],'member_key':row['member_key'],'classification':'changed'})
  wt(shader/'RENDER_PAYLOADS.tsv',['candidate_id','normalized_path','member_key','side','payload_size','payload_sha256'],render)
  wt(binary/'PAYLOAD_BINARY_DELTA.tsv',['candidate_id','normalized_path','member_key','classification'],deltas)
 def tearDown(self):self.t.cleanup()
 def loader(self,**kwargs):return list(self.pairs),[]
 def test_build_uniform_common_family(self):
  out,arc,s=TOOL.build_report(self.p,create_archive=False,pair_loader=self.loader)
  self.assertIsNone(arc);self.assertEqual(s['scope_member_rows'],21);self.assertEqual(s['family_rows'],7)
  fam=TOOL.read_tsv(out/'REFLECTOR_LIGHT_FAMILY_BINARY_COMPARISON.tsv')
  common=[x for x in fam if x['family_key']=='ringlight:e_cmn_ringlight_PCXX.g1e'][0]
  self.assertEqual(common['member_rows'],'15');self.assertEqual(common['family_classification'],'uniform_exact_delta_across_slots')
  self.assertEqual(common['promotion_status'],'uniform_cross_slot_candidate_requires_semantic_control')
 def test_all_payloads_verified(self):
  out,_,s=TOOL.build_report(self.p,create_archive=False,pair_loader=self.loader)
  rows=TOOL.read_tsv(out/'REFLECTOR_LIGHT_MEMBER_BINARY_AUDIT.tsv')
  self.assertEqual(len(rows),21);self.assertTrue(all(x['exact_source_inverse']=='True' for x in rows));self.assertEqual(s['skipped_rows'],0)
 def test_hash_mismatch_rejected(self):
  p=self.r/TOOL.SHADER_DIR/'RENDER_PAYLOADS.tsv';rows=TOOL.read_tsv(p);rows[0]['payload_sha256']='0'*64
  wt(p,['candidate_id','normalized_path','member_key','side','payload_size','payload_sha256'],rows)
  with self.assertRaises(TOOL.Stage80Error):TOOL.build_report(self.p,create_archive=False,pair_loader=self.loader)
 def test_missing_common_slot_rejected(self):
  p=self.r/TOOL.STAGE79_DIR/'REFLECTOR_SLOT_RENDER_MEMBERS.tsv';rows=TOOL.read_tsv(p);rows=rows[1:]
  wt(p,list(rows[0]),rows)
  with self.assertRaises(TOOL.Stage80Error):TOOL.build_report(self.p,create_archive=False,pair_loader=self.loader)
if __name__=='__main__':unittest.main()
