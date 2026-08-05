from __future__ import annotations
import importlib.util, json, struct, sys, tempfile, unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[3]
WS=ROOT/'workstreams/quartet_restoration'
sys.path.insert(0,str(WS))
path=WS/'build_unselected_cue_residual_prototype.py'
spec=importlib.util.spec_from_file_location('build_unselected_cue_residual_prototype',path); assert spec and spec.loader
TOOL=importlib.util.module_from_spec(spec); sys.modules[spec.name]=TOOL; spec.loader.exec_module(TOOL)
sys.path.insert(0,str(ROOT/'Blue_Reflection_Text_Tool'))
import br_restoration_tool as BR

def lp(raw:bytes)->bytes: return struct.pack('<I',len(raw))+raw
def payload(words:list[int], trailing:bytes=b'')->bytes:
    prefix=struct.pack('<II',2,0)+lp(b'name\0')+lp('説明'.encode('cp932')+b'\0')
    return prefix+struct.pack(f'<{len(words)}I',*words)+trailing

class Stage52Tests(unittest.TestCase):
    def fixture(self):
        source=payload([1,0x7B96EE8A,0x7F000000,0x75400009,0x7F000000],b'tail')
        target=payload([1,0x7B96EE8A,0x75834283,0x7F000000,0x75400009,0x74100014,0x7F000000],b'tail')
        sh=BR.parse_ebd_header_schema(source); th=BR.parse_ebd_header_schema(target)
        sp=BR.profile_ebd_post_header_words(source,int(sh['header_end'])); tp=BR.profile_ebd_post_header_words(target,int(th['header_end']))
        deltas=BR.compare_ebd_tag_atoms(sp['atoms'],tp['atoms'])
        shape=BR.event_residual_delta_shape_id(deltas[0])
        return source,target,shape
    def test_reconstruct_candidate_preserves_other_residual_and_roundtrips(self):
        source,target,shape=self.fixture()
        old=TOOL.TARGET_SHAPE_ID
        try:
            TOOL.TARGET_SHAPE_ID=shape
            candidate,reversed_payload,metadata,residuals=TOOL.reconstruct_candidate(BR,source,target)
        finally:
            TOOL.TARGET_SHAPE_ID=old
        self.assertEqual(reversed_payload,target)
        self.assertTrue(metadata['checks']['target_shape_count_reduced_exactly_once'])
        self.assertTrue(metadata['checks']['all_other_residual_counters_preserved'])
        self.assertTrue(metadata['checks']['strict_improvement'])
        self.assertEqual(len(residuals),1)
        self.assertNotEqual(candidate,target)
    def test_validate_stage51_accepts_canonical_ready_report(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            (root/'SUMMARY.json').write_text(json.dumps({
                'type':'br_quartet_restoration_unselected_cue_residual_splice_evidence_summary','tool_version':'0.0.59',
                'target_event_rows':1,'analyzed_event_rows':1,'promotable_event_rows':1,'validation_rows':9,
                'validation_failures':0,'remaining_residual_rows':2,'skipped_rows':0}),encoding='utf-8')
            BR.write_tsv(root/'UNSELECTED_CUE_RESIDUAL_EVENTS.tsv',['normalized_path','shape_id','classification','safe_to_build_separate_local_profile'],[{
                'normalized_path':TOOL.TARGET_EVENT_PATH,'shape_id':TOOL.TARGET_SHAPE_ID,
                'classification':'unselected_cue_residual_strict_improvement_ready_for_local_prototype','safe_to_build_separate_local_profile':True}])
            BR.write_tsv(root/'UNSELECTED_CUE_RESIDUAL_SPLICE_TESTS.tsv',['passed'],[{'passed':True} for _ in range(9)])
            BR.write_tsv(root/'UNSELECTED_CUE_RESIDUAL_REMAINING.tsv',['shape_id'],[{'shape_id':'a'},{'shape_id':'b'}])
            BR.write_tsv(root/'UNSELECTED_CUE_RESIDUAL_SKIPPED.tsv',['reason'],[])
            summary,event,tests,counter=TOOL.validate_stage51(root)
            self.assertEqual(summary['tool_version'],'0.0.59'); self.assertEqual(event['shape_id'],TOOL.TARGET_SHAPE_ID)
            self.assertEqual(len(tests),9); self.assertEqual(counter,{'a':1,'b':1})
    def test_validate_stage51_rejects_failed_validation(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            (root/'SUMMARY.json').write_text(json.dumps({
                'type':'br_quartet_restoration_unselected_cue_residual_splice_evidence_summary','tool_version':'0.0.59',
                'target_event_rows':1,'analyzed_event_rows':1,'promotable_event_rows':1,'validation_rows':9,
                'validation_failures':0,'remaining_residual_rows':2,'skipped_rows':0}),encoding='utf-8')
            BR.write_tsv(root/'UNSELECTED_CUE_RESIDUAL_EVENTS.tsv',['normalized_path','shape_id','classification','safe_to_build_separate_local_profile'],[{
                'normalized_path':TOOL.TARGET_EVENT_PATH,'shape_id':TOOL.TARGET_SHAPE_ID,
                'classification':'unselected_cue_residual_strict_improvement_ready_for_local_prototype','safe_to_build_separate_local_profile':True}])
            BR.write_tsv(root/'UNSELECTED_CUE_RESIDUAL_SPLICE_TESTS.tsv',['passed'],[{'passed':False}]+[{'passed':True} for _ in range(8)])
            BR.write_tsv(root/'UNSELECTED_CUE_RESIDUAL_REMAINING.tsv',['shape_id'],[{'shape_id':'a'},{'shape_id':'b'}])
            BR.write_tsv(root/'UNSELECTED_CUE_RESIDUAL_SKIPPED.tsv',['reason'],[])
            with self.assertRaises(TOOL.UnselectedCuePrototypeError): TOOL.validate_stage51(root)
if __name__=='__main__': unittest.main()
