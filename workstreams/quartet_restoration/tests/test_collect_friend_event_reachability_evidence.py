from __future__ import annotations
import hashlib, importlib.util, json, struct, sys, tempfile, unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[3]
WS=ROOT/'workstreams/quartet_restoration'
spec=importlib.util.spec_from_file_location('collect_friend_event_reachability_evidence',WS/'collect_friend_event_reachability_evidence.py'); assert spec and spec.loader
TOOL=importlib.util.module_from_spec(spec); sys.modules[spec.name]=TOOL; spec.loader.exec_module(TOOL)
sys.path.insert(0,str(ROOT/'Blue_Reflection_Text_Tool'))
import br_restoration_tool as BR

def sha(data:bytes)->str: return hashlib.sha256(data).hexdigest()
def ebm(count:int, marker:int=0)->bytes: return struct.pack('<IIII',count,2,marker,0)+bytes([marker & 0xff])*max(34,count)
def ebd(count:int, marker:int=0)->bytes: return struct.pack('<IIII',count,0,5,0x656d616e)+bytes([marker & 0xff])*64

def write_json(path:Path,data:dict): path.parent.mkdir(parents=True,exist_ok=True); path.write_text(json.dumps(data),encoding='utf-8')
def write_tsv(path:Path,fields:list[str],rows:list[dict]):
    import csv
    path.parent.mkdir(parents=True,exist_ok=True)
    with path.open('w',encoding='utf-8',newline='') as h:
        w=csv.DictWriter(h,fieldnames=fields,delimiter='\t',lineterminator='\n'); w.writeheader(); w.writerows(rows)

class Stage55Tests(unittest.TestCase):
    def test_classification_changed_message_and_control(self):
        row={'source_jp_message_state':'substantive','target_jp_message_state':'substantive','source_ebd_present':True,'target_ebd_present':True,'source_direct_control_reference_count':0,'target_direct_control_reference_count':0,'jp_message_hash_equal':False,'ebd_hash_equal':False}
        self.assertEqual(TOOL.classify_slot(row),('archive_present_message_and_control_changed_reachability_unresolved','high'))
    def test_message_stub_is_critical(self):
        row={'source_jp_message_state':'substantive','target_jp_message_state':'minimal_stub','source_ebd_present':True,'target_ebd_present':True,'source_direct_control_reference_count':0,'target_direct_control_reference_count':0,'jp_message_hash_equal':False,'ebd_hash_equal':False}
        self.assertEqual(TOOL.classify_slot(row)[0],'possible_message_payload_removed_or_stubbed')
    def test_full_collect_audits_420_core_slots(self):
        with tempfile.TemporaryDirectory() as td:
            base=Path(td); reports=base/'reports'; workspace=base/'workspace'
            (reports/'inventories').mkdir(parents=True); (reports/'differences').mkdir()
            src_files=[]; tgt_files=[]; family_rows=[]
            for family_num in range(1,15):
                family=f'fe{family_num:02d}'
                for slot_num in range(10,301,10):
                    eid=f'{family}_{slot_num:03d}'
                    count=50 if eid=='fe13_090' else 3
                    sm=ebm(count,1); tm=ebm(count,2 if eid=='fe13_090' else 1)
                    se=ebd(39 if eid=='fe13_090' else 2,1); te=ebd(39 if eid=='fe13_090' else 2,2 if eid=='fe13_090' else 1)
                    items=[('event_message_'+eid+'.ebm',sm,tm,'.ebm'),('event_'+eid+'.ebd',se,te,'.ebd')]
                    for name,sdata,tdata,ext in items:
                        norm=f'event/event_jp/{family}/{name}'
                        spath=norm; tpath=f'event/b1/event_jp/{family}/{name}'
                        sr={'archive':'DATA/PACK01.PAK','path':spath,'normalized_path':norm,'size':len(sdata),'sha256':sha(sdata),'extension':ext}
                        tr={'archive':'Data/PACK11.PAK','path':tpath,'normalized_path':norm,'size':len(tdata),'sha256':sha(tdata),'extension':ext}
                        src_files.append(sr); tgt_files.append(tr)
                        sp=BR.inventory_workspace_file(workspace,'source','br1_events',sr['archive'],sr['path']); sp.parent.mkdir(parents=True,exist_ok=True); sp.write_bytes(sdata)
                        tp=BR.inventory_workspace_file(workspace,'target','br1_events',tr['archive'],tr['path']); tp.parent.mkdir(parents=True,exist_ok=True); tp.write_bytes(tdata)
                    family_rows.append({'event_family_id':'x','event_message_path':f'event/event_jp/{family}/event_message_{eid}.ebm','event_data_path':f'event/event_jp/{family}/event_{eid}.ebd','event_message_classification':'changed' if eid=='fe13_090' else 'identical','event_data_classification':'changed' if eid=='fe13_090' else 'identical','exact_scene_rules':'','supporting_scene_rules':'','focused_technical_identifiers':'','target_only_technical_identifiers':'','source_only_technical_identifiers':'','rare_delta_regions':'1' if eid=='fe13_090' else '0','repeated_delta_regions':'0','widespread_delta_regions':'0','corrected_unresolved_changed_bytes':'179' if eid=='fe13_090' else '','classification':'event_family_without_direct_scene_binding','review_priority':'deferred','review_status':'x'})
            write_json(reports/'inventories/br1_events.source.json',{'archive_group':'br1_events','files':src_files})
            write_json(reports/'inventories/br1_events.target.json',{'archive_group':'br1_events','files':tgt_files})
            family=reports/'event_family_evidence'; write_json(family/'SUMMARY.json',{'type':'br_quartet_restoration_event_family_evidence_summary','tool_version':'0.0.20'})
            fields=list(family_rows[0]); write_tsv(family/'EVENT_FAMILY_PAIRS.tsv',fields,family_rows)
            record=reports/'event_record_evidence'; write_json(record/'SUMMARY.json',{'type':'br_quartet_restoration_event_record_evidence_summary','tool_version':'0.0.19'})
            write_tsv(record/'EVENT_PROCESS_LAYOUT.tsv',['normalized_path','source_size','target_size','source_leading_count','target_leading_count','in_scope_ebm_count','count_matches_in_scope_ebm','classification'],[{'normalized_path':'event/eventprocess/eventprocessdataall.epd','source_size':'1','target_size':'1','source_leading_count':'1758','target_leading_count':'1758','in_scope_ebm_count':'1758','count_matches_in_scope_ebm':'True','classification':'count'}])
            core=reports/'core_profile_manifest_evidence'; write_json(core/'SUMMARY.json',{'type':'br_quartet_restoration_core_profile_manifest_evidence_summary','tool_version':'0.0.62','profile_rows':14,'runtime_validated_profile_rows':0})
            out,summary=TOOL.collect(project_root=ROOT,workspace_root=workspace,report_root=reports)
            self.assertTrue(out.is_file()); self.assertEqual(summary['friend_event_slot_rows'],420)
            self.assertEqual(summary['friend_event_family_rows'],14)
            self.assertEqual(summary['source_to_target_message_removed_or_stubbed_rows'],0)
            self.assertEqual(summary['fe13_090']['source_jp_message_declared_records'],50)
            self.assertEqual(summary['fe13_090']['target_jp_message_declared_records'],50)
            self.assertTrue(summary['fe13_090']['message_changed']); self.assertTrue(summary['fe13_090']['control_changed'])
            self.assertEqual(summary['fe13_090']['classification'],'archive_present_message_and_control_changed_reachability_unresolved')

if __name__=='__main__': unittest.main()
