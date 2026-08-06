from __future__ import annotations
import hashlib, importlib.util, json, shutil, struct, sys, tempfile, unittest, zlib
from pathlib import Path
from unittest import mock

WORKSTREAM = Path(__file__).resolve().parents[1]
PROJECT = WORKSTREAM.parent.parent
TOOL_PATH = WORKSTREAM / "149_prepare_hinako_wet_default_g1mm_fast_test_profile.py"
SPEC = importlib.util.spec_from_file_location("stage149_tool", TOOL_PATH)
assert SPEC and SPEC.loader
TOOL = importlib.util.module_from_spec(SPEC); sys.modules[SPEC.name]=TOOL; SPEC.loader.exec_module(TOOL)
S120_PATH = WORKSTREAM / "120_collect_canary_all_synthetic_composer_contract_evidence.py"
S120_SPEC = importlib.util.spec_from_file_location("stage149_s120", S120_PATH)
assert S120_SPEC and S120_SPEC.loader
S120 = importlib.util.module_from_spec(S120_SPEC); sys.modules[S120_SPEC.name]=S120; S120_SPEC.loader.exec_module(S120)

def sha(b: bytes)->str: return hashlib.sha256(b).hexdigest()

def parameter_record(name: str, value: float) -> bytes:
    n=name.encode()+b"\0"; raw=struct.pack("<f",value); size=16+len(n)+len(raw)
    return struct.pack("<3I2H",size,len(n),0,1,1)+n+raw

def g1mg(value: float) -> bytes:
    record=parameter_record("sentinel",value); block=struct.pack("<I",1)+record
    section=struct.pack("<3I",0x00010003,12+len(block),1)+block
    size=0x30+len(section)
    return b"G1MG"+struct.pack("<2I",0x30303435,size)+b"DX11"+struct.pack("<I6f",0,0,0,0,1,1,1)+struct.pack("<I",1)+section

def g1m(mm_byte: int, value: float) -> bytes:
    mm=b"MM1G"+struct.pack("<2I",0x30303230,32)+bytes([mm_byte])*20
    geom=g1mg(value)
    total=0x18+len(mm)+len(geom)
    return b"_M1G"+struct.pack("<5I",0x30303435,total,0x18,0,2)+mm+geom

def make_earc(members):
    header=0x1C; filename_size=8; name_bytes=0x20+filename_size*0x10; entry=8+name_bytes; table=len(members)*entry
    payload_size=sum(len(x[1]) for x in members); out=bytearray(header+table+payload_size); struct.pack_into("<7I",out,0,0x45415243,filename_size,payload_size,header,table,len(members),0)
    off=header+table
    for i,(name,payload) in enumerate(members):
        t=header+i*entry; struct.pack_into("<2I",out,t,off,len(payload)); e=name.encode()+b"\0"; out[t+8:t+8+len(e)]=e; out[off:off+len(payload)]=payload; off+=len(payload)
    return bytes(out)

def gust_chunked(payload: bytes)->bytes:
    out=bytearray()
    for start in range(0,len(payload),0x4000):
        c=zlib.compress(payload[start:start+0x4000],9); out.extend(len(c).to_bytes(4,"little")); out.extend(c)
    out.extend((0).to_bytes(4,"little")); return bytes(out)

def write_parent(path: Path, selected: bytes, retained: bytes):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_bytes(gust_chunked(make_earc([
        ("dummy.bin",b"keep"),
        (TOOL.SELECTED_MEMBER_NAME,selected),
        (TOOL.RETAINED_MEMBER_NAME,retained),
    ])))

class WetDefaultG1MMTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(prefix="stage149-"); self.root=Path(self.tmp.name)
        self.target=g1m(0x22,0.4); self.source=g1m(0x11,0.8)
        self.target_retained=b"quartet-school-wet-target"
        self.source_retained=b"original-school-wet-retained"
        self.target_parent=self.root/"target.elixir.gz"; self.source_parent=self.root/"source.elixir.gz"
        write_parent(self.target_parent,self.target,self.target_retained)
        write_parent(self.source_parent,self.source,self.source_retained)
        br=TOOL.load_module(PROJECT/"Blue_Reflection_Text_Tool/br_restoration_tool.py","stage149_test_br_init")
        sp=br.parse_g1m_material_parameters(self.source); tp=br.parse_g1m_material_parameters(self.target)
        sm=[r for r in sp["chunks"] if r["chunk_magic"]=="MM1G"][0]; tm=[r for r in tp["chunks"] if r["chunk_magic"]=="MM1G"][0]
        self.patch={
            "EXPECTED_SOURCE_MEMBER_SHA256":sha(self.source),"EXPECTED_TARGET_MEMBER_SHA256":sha(self.target),"EXPECTED_SOURCE_MEMBER_SIZE":len(self.source),"EXPECTED_TARGET_MEMBER_SIZE":len(self.target),
            "EXPECTED_SOURCE_PARENT_SHA256":TOOL.sha256_file(self.source_parent),"EXPECTED_TARGET_PARENT_SHA256":TOOL.sha256_file(self.target_parent),
            "EXPECTED_RETAINED_SOURCE_MEMBER_SHA256":sha(self.source_retained),"EXPECTED_RETAINED_TARGET_MEMBER_SHA256":sha(self.target_retained),
            "EXPECTED_RETAINED_SOURCE_MEMBER_SIZE":len(self.source_retained),"EXPECTED_RETAINED_TARGET_MEMBER_SIZE":len(self.target_retained),
            "EXPECTED_G1MM_SIZE":int(sm["chunk_size"]),"EXPECTED_SOURCE_G1MM_SHA256":sm["chunk_sha256"],"EXPECTED_TARGET_G1MM_SHA256":tm["chunk_sha256"],"EXPECTED_G1MM_VERSION":sm["chunk_version"],
        }
        self.patchers=[mock.patch.object(TOOL,k,v) for k,v in self.patch.items()]
        for p in self.patchers: p.start()
        packroot=self.root/"pack"; manifest=S120.write_fixture_tree(packroot,"PACK10_02.PAK",{TOOL.TARGET_PARENT_SUFFIX:self.target_parent.read_bytes(),"data/b1/x64/character/sentinel.bin":b"sentinel"})
        S120.run_gust(PROJECT/".local/vendor/gust_tools/gust_pak",manifest,packroot,self.root/"gust.log")
        self.baseline=packroot/"PACK10_02.PAK"; self.baseline_sha=TOOL.sha256_file(self.baseline)
        self.workspace=PROJECT/".local/build/quartet_restoration"/("stage149_test_"+self.root.name); self.manifests=self.workspace/"manifests"
    def tearDown(self):
        for p in reversed(self.patchers): p.stop()
        shutil.rmtree(self.workspace,ignore_errors=True); self.tmp.cleanup()
    def test_splice_changes_only_g1mm_and_preserves_target_g1mg(self):
        br=TOOL.load_module(PROJECT/"Blue_Reflection_Text_Tool/br_restoration_tool.py","stage149_test_br_splice")
        cand,meta=TOOL.splice_g1mm_chunk(br,self.target,self.source)
        cp=br.parse_g1m_material_parameters(cand); tp=br.parse_g1m_material_parameters(self.target); sp=br.parse_g1m_material_parameters(self.source)
        def h(parsed,magic): return [r["chunk_sha256"] for r in parsed["chunks"] if r["chunk_magic"]==magic][0]
        self.assertEqual(h(cp,"MM1G"),h(sp,"MM1G")); self.assertEqual(h(cp,"G1MG"),h(tp,"G1MG")); self.assertTrue(meta["other_top_level_chunks_preserved"])
    def test_different_g1mm_sizes_fail_closed(self):
        with mock.patch.object(TOOL,"EXPECTED_G1MM_SIZE",31):
            br=TOOL.load_module(PROJECT/"Blue_Reflection_Text_Tool/br_restoration_tool.py","stage149_test_br_bad")
            with self.assertRaises(TOOL.WetDefaultG1MMProfileError): TOOL.splice_g1mm_chunk(br,self.target,self.source)
    def test_parent_retains_school_wet_and_changes_only_default_g1mm_plus_school_wet(self):
        br=TOOL.load_module(PROJECT/"Blue_Reflection_Text_Tool/br_restoration_tool.py","stage149_test_br_parent")
        _candidate,rows,meta=TOOL.rebuild_earc_with_members(br,self.target_parent,self.source,self.source_retained)
        selected=[r for r in rows if r["selected_for_profile"]]
        self.assertEqual(len(selected),2)
        default=next(r for r in selected if r["member_key"]==TOOL.SELECTED_MEMBER_KEY)
        retained=next(r for r in selected if r["member_key"]==TOOL.RETAINED_MEMBER_KEY)
        self.assertNotEqual(default["candidate_sha256"],sha(self.source))
        self.assertNotEqual(default["candidate_sha256"],sha(self.target))
        self.assertEqual(retained["candidate_sha256"],sha(self.source_retained))
        self.assertEqual(sum(r["target_sha256"]!=r["candidate_sha256"] for r in rows),2)
        self.assertTrue(meta["other_top_level_chunks_preserved"])
    def test_profile_changes_one_pack_member_and_keeps_game_baseline(self):
        profile,parent,pak,vals=TOOL.build_profile_from_inputs(PROJECT,baseline_archive=self.baseline,source_default_member=self.source,source_retained_member=self.source_retained,gust_pak=PROJECT/".local/vendor/gust_tools/gust_pak",workspace_root=self.workspace,manifest_root=self.manifests,timeout_seconds=60)
        self.assertEqual(sum(r["baseline_sha256"]!=r["profile_sha256"] for r in pak),1); self.assertEqual(sum(r["target_sha256"]!=r["candidate_sha256"] for r in parent),2); self.assertTrue(all(r["passed"] for r in vals)); self.assertEqual(TOOL.sha256_file(self.baseline),self.baseline_sha); self.assertFalse(profile["runtime_validated"])
    def test_runtime_observation_is_canonical_and_nonproduction(self):
        obs=json.loads((WORKSTREAM/"WET_SCHOOL_RUNTIME_OBSERVATION.json").read_text())
        self.assertTrue(obs["runtime_stable"]); self.assertFalse(obs["target_transparency_restored"]); self.assertFalse(obs["runtime_validated"]); self.assertTrue(obs["exact_pack10_02_baseline_restored"])
        self.assertTrue(obs["partial_visual_restoration_confirmed"])
        self.assertTrue(obs["partial_visual_restoration"]["must_be_retained_in_future_candidate"])
        reg=json.loads((WORKSTREAM/"RUNTIME_VALIDATION_REGISTRY.json").read_text()); row=reg["fast_test_results"][obs["profile_id"]]
        self.assertEqual(row["runtime_status"],"runtime_stable_partial_visual_restoration_transparency_not_restored"); self.assertTrue(row["partial_visual_restoration_confirmed"]); self.assertFalse(row["production_eligible"])
    def test_profile_is_fast_test_only(self):
        profile,*_=TOOL.build_profile_from_inputs(PROJECT,baseline_archive=self.baseline,source_default_member=self.source,source_retained_member=self.source_retained,gust_pak=PROJECT/".local/vendor/gust_tools/gust_pak",workspace_root=self.workspace,manifest_root=self.manifests,timeout_seconds=60)
        self.assertTrue(profile["fast_test_only"]); self.assertFalse(profile["normal_composer_eligible"]); self.assertEqual(profile["g1mm_source_sha256"],self.patch["EXPECTED_SOURCE_G1MM_SHA256"])
    def test_report_is_metadata_only_and_records_previous_negative_probe(self):
        out=self.root/"reports"
        archive,summary=TOOL.build_report(
            PROJECT, quartet_root=self.root, original_root=None, gust_pak=PROJECT/".local/vendor/gust_tools/gust_pak",
            output_report_root=out, workspace_root=self.workspace, manifest_root=self.manifests, baseline_archive=self.baseline,
            source_parent_override=self.source_parent, timeout_seconds=60, validate_evidence=False, create_archive=True,
        )
        self.assertIsNotNone(archive); self.assertTrue(archive.is_file())
        self.assertEqual(summary["pak_changed_member_rows"],1); self.assertEqual(summary["parent_changed_member_rows"],2)
        self.assertTrue(summary["previous_probe_insufficient_for_transparency_restoration"])
        self.assertTrue(summary["previous_probe_partial_visual_restoration_must_be_retained"])
        self.assertTrue(summary["retained_partial_visual_restoration_confirmed"])
        self.assertFalse(summary["runtime_validated"]); self.assertFalse(summary["production_eligible"])
        report_dir=out/TOOL.REPORT_DIR
        forbidden=[p for p in report_dir.rglob("*") if p.is_file() and p.suffix.casefold() in {".pak",".g1m",".g1e",".g1t",".ebm",".ebd",".kps"}]
        self.assertEqual(forbidden,[])

if __name__ == "__main__": unittest.main()
