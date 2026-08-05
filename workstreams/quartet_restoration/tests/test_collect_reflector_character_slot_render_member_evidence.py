#!/usr/bin/env python3
from __future__ import annotations
import csv, importlib.util, json, tempfile, unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[3]
PATH=ROOT/'workstreams/quartet_restoration/collect_reflector_character_slot_render_member_evidence.py'
spec=importlib.util.spec_from_file_location('stage79',PATH);assert spec and spec.loader
TOOL=importlib.util.module_from_spec(spec);spec.loader.exec_module(TOOL)
def wj(p,d):p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(d)+'\n',encoding='utf-8')
def wt(p,fields,rows):
 p.parent.mkdir(parents=True,exist_ok=True)
 with p.open('w',encoding='utf-8',newline='') as f:
  w=csv.DictWriter(f,fieldnames=fields,delimiter='\t',lineterminator='\n');w.writeheader();w.writerows(rows)
class T(unittest.TestCase):
 def setUp(self):
  self.t=tempfile.TemporaryDirectory();self.p=Path(self.t.name);self.r=self.p/'.local/reports/quartet_restoration';self.r.mkdir(parents=True)
  r78=self.r/TOOL.STAGE78_DIR;wj(r78/'SUMMARY.json',{'type':'br_quartet_restoration_all_reflector_transformation_family_evidence_summary','tool_version':'0.0.91','changed_event_rows':1,'other_than_stage77_yuzuki_changed_event_rows':0})
  r76=self.r/TOOL.STAGE76_DIR;wj(r76/'SUMMARY.json',{'type':'br_quartet_restoration_transformation_brightness_evidence_summary','tool_version':'0.0.88'})
  fields=['evidence_source','candidate_id','domain','priority','normalized_path','member_name','member_key','change_classification','lead_classification']
  rows=[]
  for slot in range(3):
   for source in ('FOCUSED_SHADER_EFFECT_REVIEW.tsv','PAYLOAD_BINARY_DELTA.tsv'):
    rows.append({'evidence_source':source,'candidate_id':'c','domain':'d','priority':'high','normalized_path':'data/x64/effect/100_common.elixir.gz','member_name':f'e_cmn_ringlight_PC{slot:02d}.g1e','member_key':f'e_cmn_ringlight_pc{slot:02d}.g1e#0','change_classification':'changed','lead_classification':'transformation_body_brightness_lead'})
  rows.append({'evidence_source':'PAYLOAD_BINARY_DELTA.tsv','candidate_id':'c2','domain':'d','priority':'high','normalized_path':'data/x64/character/pc01/pc01_rfl_w.elixir.gz','member_name':'','member_key':'','change_classification':'added_in_target','lead_classification':'transformation_body_locator'})
  wt(r76/'TRANSFORMATION_BRIGHTNESS_EXISTING_EVIDENCE.tsv',fields,rows)
 def tearDown(self):self.t.cleanup()
 def test_build(self):
  out,arc,s=TOOL.build_report(self.p,False);self.assertIsNone(arc);self.assertEqual(s['character_slot_rows'],3);self.assertEqual(s['ringlight_family_rows'],1);self.assertEqual(s['uniform_changed_family_rows'],1)
  fam=TOOL.read_tsv(out/'REFLECTOR_RENDER_MEMBER_FAMILIES.tsv');ring=[x for x in fam if x['asset_role']=='ringlight'][0];self.assertEqual(ring['slot_count'],'3');self.assertEqual(ring['family_classification'],'uniform_changed_across_slots')
 def test_dedup_sources(self):
  out,_,_=TOOL.build_report(self.p,False);rows=TOOL.read_tsv(out/'REFLECTOR_SLOT_RENDER_MEMBERS.tsv');ring=[x for x in rows if x['asset_role']=='ringlight'];self.assertEqual(len(ring),3);self.assertTrue(all('FOCUSED_SHADER_EFFECT_REVIEW.tsv' in x['evidence_sources'] and 'PAYLOAD_BINARY_DELTA.tsv' in x['evidence_sources'] for x in ring))
 def test_slots_not_named(self):
  out,_,_=TOOL.build_report(self.p,False);rows=TOOL.read_tsv(out/'REFLECTOR_CHARACTER_SLOT_INVENTORY.tsv');self.assertTrue(all(x['heroine_name_binding']=='unresolved' for x in rows))
 def test_bad_stage78_rejected(self):
  p=self.r/TOOL.STAGE78_DIR/'SUMMARY.json';d=json.loads(p.read_text());d['other_than_stage77_yuzuki_changed_event_rows']=1;wj(p,d)
  with self.assertRaises(TOOL.Stage79Error):TOOL.build_report(self.p,False)
if __name__=='__main__':unittest.main()
