import csv, importlib.util, json, tempfile, unittest
from pathlib import Path
MODULE=Path(__file__).resolve().parents[1]/'br_dlc_control_compatibility_tool.py'
spec=importlib.util.spec_from_file_location('control_tool',MODULE); mod=importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)

def write_tsv(p,fields,rows):
    p.parent.mkdir(parents=True,exist_ok=True)
    with p.open('w',encoding='utf-8',newline='') as f:
        w=csv.DictWriter(f,fieldnames=fields,delimiter='\t',lineterminator='\n'); w.writeheader(); w.writerows(rows)

class TestControlCompatibility(unittest.TestCase):
    def test_metadata_audit(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); reports=root/'.local/reports/quartet_legacy_dlc'; b=reports/'bounded_family_evidence'; e=reports/'external_dependency_closure_evidence'; b.mkdir(parents=True); e.mkdir()
            (b/'SUMMARY.json').write_text(json.dumps({'tool_version':'0.0.10'}))
            pf=['content_id','parent_role','member_name','side','parameter_key','parameter_name','shader_block_index','parameter_occurrence','buffer_type','buffer_count','value_text','value_hex_sha256','keyword_hits','raw_payload_exported']
            rows=[]
            def add(c,role,m,side,bi,name,v): rows.append(dict(zip(pf,[c,role,m,side,f'{bi}|{name.lower()}|0',name,str(bi),'0','1','1',v,v,'','false'])))
            for c in ('costume_pc00_bkn','costume_pc00_twl'):
                add(c,'dry_model_or_container',f'{c}.g1m','source',0,'fTranslucency','a')
                add(c,'wet_model_or_container',f'{c}_W.g1m','source',0,'fTranslucency','a')
            add('costume_pc00_twl','dry_model_or_container','twl.g1m','target',0,'fTranslucency','a')
            add('costume_pc00_twl','wet_model_or_container','twl_W.g1m','target',0,'fTranslucency','a')
            add('costume_pc00_twl','wet_model_or_container','twl_W.g1m','target',0,'parameterForMeshBlend','b')
            write_tsv(b/'DLC_BOUNDED_G1M_MATERIAL_PARAMETERS.tsv',pf,rows)
            df=['content_id','parent_role','member_name','classification','parameter_name']
            write_tsv(b/'DLC_BOUNDED_G1M_MATERIAL_DIFFS.tsv',df,[{'content_id':'costume_pc00_twl','parent_role':'wet_model_or_container','member_name':'twl_W.g1m','classification':'added_in_target','parameter_name':'parameterForMeshBlend'}])
            mf=['content_id','parent_role','member_name','nested_role','source_size','source_sha256','target_size','target_sha256','compatibility_status']
            write_tsv(b/'DLC_BOUNDED_FAMILY_MEMBER_AUDIT.tsv',mf,[
                {'content_id':'costume_pc00_bkn','parent_role':'dry_model_or_container','member_name':'bkn.g1m','nested_role':'model_and_material','source_size':'10','source_sha256':'x','compatibility_status':'missing_portable_from_br1'},
                {'content_id':'costume_pc00_bkn','parent_role':'wet_model_or_container','member_name':'bkn_W.g1m','nested_role':'model_and_material','source_size':'10','source_sha256':'y','compatibility_status':'missing_portable_from_br1'},
                {'content_id':'costume_pc00_twl','parent_role':'dry_model_or_container','member_name':'twl.g1m','nested_role':'model_and_material','source_size':'10','source_sha256':'a','target_size':'10','target_sha256':'a','compatibility_status':'present_identical'},
                {'content_id':'costume_pc00_twl','parent_role':'wet_model_or_container','member_name':'twl_W.g1m','nested_role':'model_and_material','source_size':'10','source_sha256':'b','target_size':'12','target_sha256':'c','compatibility_status':'present_modified'},
            ])
            write_tsv(b/'DLC_BOUNDED_CLOTH_STRUCTURE_AUDIT.tsv',['x'],[]); write_tsv(b/'DLC_BOUNDED_SHARED_MEMBER_BINDINGS.tsv',['payload_sha256','content_ids'],[])
            tf=['content_id','texture_role','source_path','source_size','source_sha256','compatibility_status']
            write_tsv(e/'DLC_EXTERNAL_TEXTURE_BINDINGS.tsv',tf,[{'content_id':'costume_pc00_bkn','texture_role':'dry_texture','source_path':'a.g1t','source_size':'1','source_sha256':'z','compatibility_status':'missing_portable_from_br1'}])
            out=reports/mod.REPORT_DIR_NAME; archive,summary=mod.audit(root,out)
            self.assertTrue(archive.is_file()); self.assertEqual(summary['classification_counts']['missing_requires_conversion'],1)
            self.assertFalse(summary['policy']['profile_build_allowed']); self.assertEqual(mod.validate(out)['tool_version'],'0.0.11')
    def test_validation_rejects_build(self):
        with tempfile.TemporaryDirectory() as td:
            r=Path(td)
            for n in ['DLC_CONTROL_MATERIAL_BLOCK_MAPPING.tsv','DLC_POSITIVE_CONTROL_STRUCTURAL_DELTA.tsv','DLC_CONTROL_DERIVED_NEXT_PROBES.tsv','DLC_CONTROL_DERIVED_GAPS.tsv']:
                write_tsv(r/n,['x'],[])
            write_tsv(r/'DLC_CANDIDATE_TRANSFER_CLASSIFICATION.tsv',['control_derived_classification','profile_build_allowed'],[{'control_derived_classification':'missing_requires_conversion','profile_build_allowed':'true'}])
            (r/'SUMMARY.json').write_text(json.dumps({'tool_version':'0.0.11','policy':{'profile_build_allowed':False}})); (r/'REPORT_MANIFEST.json').write_text('{}')
            with self.assertRaises(mod.ControlCompatibilityError): mod.validate(r)
if __name__=='__main__': unittest.main()
