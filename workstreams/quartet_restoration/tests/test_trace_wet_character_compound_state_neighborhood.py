import importlib.util, inspect, struct, sys, unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
P=ROOT/'166_trace_wet_character_compound_state_neighborhood.py'
spec=importlib.util.spec_from_file_location('stage166_testmod',P)
M=importlib.util.module_from_spec(spec); sys.modules[spec.name]=M; spec.loader.exec_module(M)
S=M.S164

class Stage166Tests(unittest.TestCase):
    def mp(self,start,size,path=''):
        return S.MapRow(start,start+size,'rw-p',0,'00:00',0,path)

    def test_report_contract_constants(self):
        self.assertEqual(M.TOOL_VERSION,'0.1.89')
        self.assertEqual(M.STAGE,166)
        self.assertEqual(M.STAGE165_SHA256,'19938c006845ea7decba0a1db4e88ecd5bd704f43861b79bf8f5207c6bbf4d33')

    def test_fresh_site_contracts_deduplicate_current_pointer_rows(self):
        rows=[{'site_address':0x5000,'wet_target_address':0x9000,'site_mapping_key':'m','site_mapping_relative_offset':4},
              {'site_address':0x5000,'wet_target_address':0x9000,'site_mapping_key':'m','site_mapping_relative_offset':4}]
        out=M.fresh_site_contracts(rows)
        self.assertEqual(len(out),1); self.assertEqual(out[0]['site_address'],0x5000)

    def test_current_run_does_not_reuse_historical_pid(self):
        src=inspect.getsource(M.run_trace)
        self.assertIn('discover_game_process(game_root)',src)
        self.assertNotIn('explicit_pid=',src)
        self.assertIn('historical_stage165_pid',src)

    def test_component_dry_boundary_does_not_count_wet_as_dry(self):
        spec=next(x for x in M.COMPONENT_TOKENS if x.label=='school_dry')
        data=b'xx pc00_scl_w yy'; at=data.find(b'pc00_scl')
        self.assertFalse(M._token_boundary_ok(data,at,b'pc00_scl',spec,'ascii'))

    def test_component_wet_roundtrip_marks_recurrent_wet(self):
        row={'token_label':'body_wet','token_text':'pc00_nkd_w','component':'body_skin','encoding':'ascii','mapping_key':'m','mapping_relative_offset':10}
        out=M.component_wet_roundtrip_rows([row],[],[row])
        self.assertEqual(out[0]['classification'],'wet_recurrent_residency_candidate_not_component_semantics')

    def test_recurrent_wet_pointer_candidate_requires_wet1_equals_wet2(self):
        site=0x500000; maps=[self.mp(0x400000,0x400000)]
        size=2*M.LOCAL_FIELD_RADIUS+8
        w1=bytearray(size); d=bytearray(size); w2=bytearray(size)
        off=M.LOCAL_FIELD_RADIUS+16
        w1[off:off+8]=struct.pack('<Q',0x610000); d[off:off+8]=struct.pack('<Q',0x600000); w2[off:off+8]=struct.pack('<Q',0x610000)
        rows=M.derive_wet_roundtrip_fields([{'site_address':site}],{site:bytes(w1)},{site:bytes(d)},{site:bytes(w2)},maps,maps,maps,Path('/game'))
        hit=[r for r in rows if r['field_kind']=='recurrent_wet_qword_pointer_candidate' and r['relative_offset']==16]
        self.assertEqual(len(hit),1); self.assertTrue(hit[0]['wet_roundtrip_recurrent'])

    def test_nonrecurrent_wet_pointer_is_rejected(self):
        site=0x500000; maps=[self.mp(0x400000,0x400000)]
        size=2*M.LOCAL_FIELD_RADIUS+8
        w1=bytearray(size); d=bytearray(size); w2=bytearray(size)
        off=M.LOCAL_FIELD_RADIUS
        w1[off:off+8]=struct.pack('<Q',0x610000); d[off:off+8]=struct.pack('<Q',0x600000); w2[off:off+8]=struct.pack('<Q',0x620000)
        rows=M.derive_wet_roundtrip_fields([{'site_address':site}],{site:bytes(w1)},{site:bytes(d)},{site:bytes(w2)},maps,maps,maps,Path('/game'))
        self.assertFalse(any(r['field_kind']=='recurrent_wet_qword_pointer_candidate' and r['relative_offset']==0 for r in rows))

    def test_script_has_no_process_write_api(self):
        text=P.read_text()
        self.assertNotIn('process_vm_writev',text); self.assertNotIn('PTRACE_POK',text); self.assertNotIn('/proc/{pid}/mem',text)

    def test_workflow_is_self_contained_and_preserves_compound_scope(self):
        text=(ROOT/'WET_CHARACTER_COMPOUND_STATE_NEIGHBORHOOD_TRACE_WORKFLOW.md').read_text()
        self.assertIn('does **not** require the game process from stage 165',text)
        self.assertIn('WET1 == WET2 != DRY2',text)
        self.assertIn('body/skin and hair become wet',text)
        self.assertIn('may or may not be a separate asset/state',text)

if __name__=='__main__': unittest.main()
