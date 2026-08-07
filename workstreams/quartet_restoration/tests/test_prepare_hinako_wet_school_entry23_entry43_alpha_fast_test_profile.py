from __future__ import annotations
import hashlib,importlib.util,shutil,struct,sys,tempfile,unittest
from pathlib import Path
from unittest import mock
W=Path(__file__).resolve().parents[1];P=W.parent.parent

def load(name,file):
 s=importlib.util.spec_from_file_location(name,W/file);m=importlib.util.module_from_spec(s);sys.modules[s.name]=m;s.loader.exec_module(m);return m
T=load('s161','161_prepare_hinako_wet_school_entry23_entry43_alpha_fast_test_profile.py')
S120=load('s161_s120','120_collect_canary_all_synthetic_composer_contract_evidence.py')
S155=load('s161_s155','155_collect_hinako_wet_texture_entry_differential_evidence.py')
S156=load('s161_s156','156_collect_hinako_wet_texture_content_alpha_rebuild_feasibility_evidence.py')
S160=load('s161_s160','160_collect_hinako_wet_school_bc3_target_native_alpha_injection_feasibility_evidence.py')
def sha(b):return hashlib.sha256(b).hexdigest()
def bc3_payload(w,h,mips,alpha8:bytes,color8:bytes):
 out=bytearray()
 for _ in range(mips):
  bw=max(1,(w+3)//4);bh=max(1,(h+3)//4);out.extend((alpha8+color8)*(bw*bh));w=max(1,w//2);h=max(1,h//2)
 return bytes(out)
def raw(tex_type,w,h,mips,payload):
 dx=w.bit_length()-1;dy=h.bit_length()-1
 return bytes([(mips<<4),tex_type,(dy<<4)|dx,0,0,0,0,0])+payload
def make_g1t(raws):
 n=len(raws);header=28+4*n;base=4*n;offs=[];cur=base
 for r in raws:offs.append(cur);cur+=len(r)
 total=header+cur;hdr=struct.pack('<7I',S155.G1TG_MAGIC,int.from_bytes(b'0060','big'),total,header,n,10,0);flags=b'\0'*(4*n);tab=b''.join(struct.pack('<I',x) for x in offs);return hdr+flags+tab+b''.join(raws)
class Tests(unittest.TestCase):
 def setUp(self):
  self.t=tempfile.TemporaryDirectory(prefix='s161-');self.r=Path(self.t.name);self.ws=P/'.local/build/quartet_restoration'/('s161test_'+self.r.name);self.man=self.ws/'manifests'
  small=raw(0x59,4,4,1,b'12345678');base=[small for _ in range(44)];prof=list(base);prof[23]=raw(0x59,4,4,1,b'ABCDEFGH')
  tgt43=bc3_payload(32,32,1,b'\x00'*8,b'\x11'*8);src43=bc3_payload(4,4,1,b'\x22'*8,b'\x00'*8)
  base[43]=raw(0x5B,32,32,1,tgt43);prof[43]=base[43];src=list(base);src[43]=raw(0x5B,4,4,1,src43)
  self.bg=make_g1t(base);self.pg=make_g1t(prof);self.sg=make_g1t(src)
  rootb=self.r/'b';rootp=self.r/'p';bm=S120.write_fixture_tree(rootb,'PACK10_02.PAK',{T.TARGET_PARENT_SUFFIX:b'BASEPARENT',T.TARGET_G1T_SUFFIX:self.bg,'sentinel.bin':b'keep'});pm=S120.write_fixture_tree(rootp,'PACK10_02.PAK',{T.TARGET_PARENT_SUFFIX:b'STAGE157PARENT',T.TARGET_G1T_SUFFIX:self.pg,'sentinel.bin':b'keep'})
  gust=P/'.local/vendor/gust_tools/gust_pak';S120.run_gust(gust,bm,rootb,self.r/'b.log');S120.run_gust(gust,pm,rootp,self.r/'p.log');self.baseline=rootb/'PACK10_02.PAK';self.stage157=rootp/'PACK10_02.PAK'
  sp=S155.parse_g1t(self.sg,'s');tp=S155.parse_g1t(self.pg,'t');source_payload=S160._payload(self.sg,sp,43);target_payload=S160._payload(self.pg,tp,43);cand,_=S160.inject_scaled_bc3_alpha(source_payload,4,4,1,target_payload,32,32,1)
  patches={'EXPECTED_BASELINE_SHA256':T.sha256_file(self.baseline),'EXPECTED_BASELINE_SIZE':self.baseline.stat().st_size,'EXPECTED_STAGE157_PROFILE_SHA256':T.sha256_file(self.stage157),'EXPECTED_ENTRY23_PROFILE_RAW_SHA256':sha(S156.raw_entry(self.pg,tp,23)),'EXPECTED_ENTRY43_SOURCE_PAYLOAD_SHA256':sha(source_payload),'EXPECTED_ENTRY43_TARGET_PAYLOAD_SHA256':sha(target_payload),'EXPECTED_ENTRY43_CANDIDATE_PAYLOAD_SHA256':sha(cand)}
  self.ps=[mock.patch.object(T,k,v) for k,v in patches.items()]
  for x in self.ps:x.start()
 def tearDown(self):
  for x in reversed(self.ps):x.stop()
  shutil.rmtree(self.ws,ignore_errors=True);self.t.cleanup()
 def build(self):return T.build_profile_from_inputs(P,baseline_archive=self.baseline,stage157_profile_archive=self.stage157,source_g1t=self.sg,gust_pak=P/'.local/vendor/gust_tools/gust_pak',workspace_root=self.ws,manifest_root=self.man,timeout_seconds=60)
 def test_entry43_candidate_preserves_target_colour(self):
  raw43,meta=T.make_entry43_candidate(S155,S156,S160,self.sg,self.pg);tp=S155.parse_g1t(self.pg,'t');old=S160._raw_entry(self.pg,tp,43);po=int(tp['entries'][43]['payload_offset_in_entry']);self.assertEqual(raw43[:po],old[:po]);self.assertEqual(meta['block_scale'],8)
 def test_profile_changes_two_pack_members_and_entries_23_43(self):
  p,g,pak,val,_=self.build();self.assertEqual(p['changed_member_count'],2);self.assertEqual([r['texture_index'] for r in g if r['changed']],[23,43]);self.assertEqual(sum(r['changed'] for r in pak),2);self.assertTrue(all(r['passed'] for r in val))
 def test_baseline_is_read_only(self):
  before=T.sha256_file(self.baseline);self.build();self.assertEqual(T.sha256_file(self.baseline),before)
 def test_profile_is_fast_test_only(self):
  p,*_=self.build();self.assertTrue(p['fast_test_only']);self.assertFalse(p['runtime_validated']);self.assertFalse(p['production_eligible'])
 def test_stage160_hash_is_frozen(self):self.assertEqual(T.STAGE160_SHA256,'d7d97892d61c3b598eb48f69425376a50b154655c52eecb6731c618aa42b98d6')
 def test_runtime_evidence_hashes_are_frozen(self):self.assertEqual(T.STAGE158_ACTIVATION_SHA256,'e792b19ebe128469db689b68059ddb4de5180dbc1c0765df1b4e1fb9a967084e');self.assertEqual(T.STAGE158_ROLLBACK_SHA256,'7789949d0e99d1f530ea92d6f5d2f90c6c94b89049061319f1f8ce0703340c6b')
 def test_report_forbids_payload_extensions(self):
  for e in ('.pak','.g1t','.g1m','.png','.dds'):self.assertIn(e,T.FORBIDDEN_REPORT_EXTENSIONS)
 def test_tool_version(self):self.assertEqual(T.TOOL_VERSION,'0.1.82')
if __name__=='__main__':unittest.main()
