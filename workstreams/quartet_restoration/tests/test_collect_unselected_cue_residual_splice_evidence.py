from __future__ import annotations
import importlib.util, struct, sys, unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[3]
WS=ROOT/'workstreams/quartet_restoration'
sys.path.insert(0,str(WS))
path=WS/'collect_unselected_cue_residual_splice_evidence.py'
spec=importlib.util.spec_from_file_location('collect_unselected_cue_residual_splice_evidence',path); assert spec and spec.loader
TOOL=importlib.util.module_from_spec(spec); sys.modules[spec.name]=TOOL; spec.loader.exec_module(TOOL)
sys.path.insert(0,str(ROOT/'Blue_Reflection_Text_Tool'))
import br_restoration_tool as BR

def lp(raw:bytes)->bytes: return struct.pack('<I',len(raw))+raw
def payload(words:list[int])->bytes:
    prefix=struct.pack('<II',2,0)+lp(b'name\0')+lp('説明'.encode('cp932')+b'\0')
    return prefix+struct.pack(f'<{len(words)}I',*words)

class Stage51Tests(unittest.TestCase):
    def fixture(self):
        source=payload([1,0x7B96EE8A,0x7F000000])
        target=payload([1,0x7B96EE8A,0x75834283,0x7F000000])
        sh=BR.parse_ebd_header_schema(source); th=BR.parse_ebd_header_schema(target)
        sp=BR.profile_ebd_post_header_words(source,int(sh['header_end']))
        tp=BR.profile_ebd_post_header_words(target,int(th['header_end']))
        ds=BR.compare_ebd_tag_atoms(sp['atoms'],tp['atoms'])
        self.assertEqual(len(ds),1)
        return source,target,BR.event_residual_delta_shape_id(ds[0])
    def test_fixture_produces_one_shape(self):
        _,_,shape=self.fixture(); self.assertEqual(len(shape),64)
    def test_single_splice_reconstructs_original(self):
        source,target,shape=self.fixture(); result,residuals=TOOL.evaluate_single_unselected_splice(BR,source,target,shape)
        self.assertTrue(result['passes_structural_gates']); self.assertTrue(result['strict_improvement'])
        self.assertTrue(result['exact_original']); self.assertEqual(result['distance_improvement'],8); self.assertEqual(residuals,[])
    def test_unrelated_residual_is_preserved(self):
        source=payload([1,0x7B96EE8A,0x7F000000,0x75400009,0x7F000000])
        target=payload([1,0x7B96EE8A,0x75834283,0x7F000000,0x75400009,0x74100014,0x7F000000])
        sh=BR.parse_ebd_header_schema(source); th=BR.parse_ebd_header_schema(target)
        sp=BR.profile_ebd_post_header_words(source,int(sh['header_end'])); tp=BR.profile_ebd_post_header_words(target,int(th['header_end']))
        shape=BR.event_residual_delta_shape_id(BR.compare_ebd_tag_atoms(sp['atoms'],tp['atoms'])[0])
        result,residuals=TOOL.evaluate_single_unselected_splice(BR,source,target,shape)
        self.assertTrue(result['passes_structural_gates']); self.assertTrue(result['strict_improvement']); self.assertEqual(len(residuals),1)
if __name__=='__main__': unittest.main()
