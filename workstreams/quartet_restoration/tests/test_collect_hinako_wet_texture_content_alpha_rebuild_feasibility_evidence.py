import ast, importlib.util, inspect, struct, unittest
from types import SimpleNamespace
from unittest import mock
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('stage156', ROOT/'156_collect_hinako_wet_texture_content_alpha_rebuild_feasibility_evidence.py')
mod=importlib.util.module_from_spec(spec); assert spec and spec.loader; spec.loader.exec_module(mod)
spec2=importlib.util.spec_from_file_location('stage155_for_156', ROOT/'155_collect_hinako_wet_texture_entry_differential_evidence.py')
st155=importlib.util.module_from_spec(spec2); assert spec2 and spec2.loader; spec2.loader.exec_module(st155)

def make_g1t(entries, *, tex_type=0x59, width_exp=2, height_exp=2):
    n=len(entries); header_size=28+4*n; raws=[]
    for payload in entries:
        b0=(1<<4); b2=((height_exp&0xF)<<4)|(width_exp&0xF)
        raws.append(bytes([b0,tex_type,b2,0,0,0,0,0])+payload)
    base=4*n; offsets=[]; cur=base
    for r in raws: offsets.append(cur); cur+=len(r)
    total=header_size+cur; version=int.from_bytes(b'0060','big')
    hdr=struct.pack('<7I',st155.G1TG_MAGIC,version,total,header_size,n,10,0)
    flags=b''.join(struct.pack('<I',0) for _ in range(n)); tab=b''.join(struct.pack('<I',x) for x in offsets)
    return hdr+flags+tab+b''.join(raws)

def bc1_block(c0,c1,indices=0): return struct.pack('<HHI',c0,c1,indices)
def bc3_block(a0,a1,abits,c0=0xffff,c1=0,indices=0): return bytes([a0,a1])+int(abits).to_bytes(6,'little')+struct.pack('<HHI',c0,c1,indices)

class Stage156Tests(unittest.TestCase):
    def test_bc1_opaque_stats(self):
        s=mod.decode_base_stats(bc1_block(0xffff,0,0),0x59,4,4)
        self.assertEqual(s['decode_status'],'ok'); self.assertEqual(s['format_class'],'BC1')
        self.assertEqual(s['alpha_nonopaque_pixels'],0); self.assertEqual(s['alpha_min'],255)

    def test_bc1_alpha_mode_stats(self):
        # c0 <= c1 and all selectors 3 => transparent.
        s=mod.decode_base_stats(bc1_block(0,0xffff,0xffffffff),0x59,4,4)
        self.assertEqual(s['alpha_zero_pixels'],16); self.assertEqual(s['alpha_nonopaque_ratio'],1.0)
        self.assertEqual(s['bc1_alpha_mode_blocks'],1)

    def test_bc3_alpha_stats(self):
        # alpha index 0 for all pixels -> alpha0.
        s=mod.decode_base_stats(bc3_block(32,255,0),0x5B,4,4)
        self.assertEqual(s['alpha_min'],32); self.assertEqual(s['alpha_max'],32)
        self.assertEqual(s['alpha_nonopaque_pixels'],16)

    def test_unsupported_format_is_not_guessed(self):
        s=mod.decode_base_stats(b'\0'*16,0x5F,4,4)
        self.assertEqual(s['decode_status'],'unsupported')

    def test_rebuild_changes_one_entry_and_updates_size(self):
        base=make_g1t([bc1_block(0xffff,0),bc1_block(0,0xffff),bc1_block(0xffff,0)])
        repl=bytes([0x10,0x59,0x22,0,0,0,0,0])+bc1_block(0x1234,0x5678)+b'EXTRA123'
        out=mod.rebuild_one_entry(base,st155,1,repl)
        p0=st155.parse_g1t(base,'base'); p1=st155.parse_g1t(out,'out')
        self.assertEqual(p1['texture_count'],3); self.assertGreater(len(out),len(base))
        self.assertEqual(mod.raw_entry(out,p1,1),repl)
        self.assertEqual(mod.raw_entry(out,p1,0),mod.raw_entry(base,p0,0))
        self.assertEqual(mod.raw_entry(out,p1,2),mod.raw_entry(base,p0,2))

    def test_focus_constants_are_frozen(self):
        self.assertEqual((mod.FOCUS_DRY_ID,mod.FOCUS_WET_ID),(26,23))
        self.assertEqual(mod.FOCUS_SOURCE_WET_SHA,'3ac334051bbf5ee86947bdb2a6aecc15dbc0456ba9b41e232278143a9a7f6727')
        self.assertEqual(mod.FOCUS_DRY_SHA,'d7aea404adf36f9684696ac3ff6825481df126f04e639830254a09a3209cfc3a')

    def test_stage155_hash_is_user_report_hash(self):
        self.assertEqual(mod.STAGE155_SHA256,'91944b1da27e935695cb8c8c6781b276995cf9798b60262e810bfe385573da0d')

    def test_forbidden_evidence_includes_image_payloads(self):
        self.assertIn('.g1t',mod.FORBIDDEN_REPORT_EXTENSIONS); self.assertIn('.dds',mod.FORBIDDEN_REPORT_EXTENSIONS); self.assertIn('.png',mod.FORBIDDEN_REPORT_EXTENSIONS)

    def test_build_report_does_not_shadow_texture_records_with_context_manager_names(self):
        tree=ast.parse(inspect.getsource(mod.build_report))
        protected={'source_dry','target_dry','source_wet','target_wet'}
        shadowed=[]
        for node in ast.walk(tree):
            if isinstance(node, ast.withitem) and isinstance(node.optional_vars, ast.Name):
                if node.optional_vars.id in protected:
                    shadowed.append(node.optional_vars.id)
        self.assertEqual(shadowed,[])

    def test_gust_list_accepts_non_utf8_stdout_bytes(self):
        cp=SimpleNamespace(returncode=0,stdout=b'header\xfc\n0x00000000 first\nnoise\xff\n0x00000010 second\n',stderr=b'')
        with mock.patch.object(mod.subprocess,'run',return_value=cp) as run:
            status,count=mod.gust_list(Path(__file__),Path('dummy.g1t'),timeout=7)
        self.assertEqual((status,count),('ok',2))
        kwargs=run.call_args.kwargs
        self.assertIs(kwargs.get('text'),False)

    def test_hotfix_tool_version(self):
        self.assertEqual(mod.TOOL_VERSION,'0.1.75')

if __name__=='__main__': unittest.main()
