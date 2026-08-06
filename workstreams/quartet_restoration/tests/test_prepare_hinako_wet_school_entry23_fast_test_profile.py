from __future__ import annotations

import hashlib
import importlib.util
import json
import shutil
import struct
import sys
import tempfile
import unittest
import zlib
from pathlib import Path
from unittest import mock

WORKSTREAM = Path(__file__).resolve().parents[1]
PROJECT = WORKSTREAM.parent.parent
TOOL_PATH = WORKSTREAM / "157_prepare_hinako_wet_school_entry23_fast_test_profile.py"
spec = importlib.util.spec_from_file_location("stage157_tool", TOOL_PATH)
assert spec and spec.loader
TOOL = importlib.util.module_from_spec(spec); sys.modules[spec.name] = TOOL; spec.loader.exec_module(TOOL)

S120_PATH = WORKSTREAM / "120_collect_canary_all_synthetic_composer_contract_evidence.py"
spec120 = importlib.util.spec_from_file_location("stage157_s120", S120_PATH)
assert spec120 and spec120.loader
S120 = importlib.util.module_from_spec(spec120); sys.modules[spec120.name] = S120; spec120.loader.exec_module(S120)

S147_PATH = WORKSTREAM / "147_prepare_hinako_wet_school_uniform_fast_test_profile.py"
spec147 = importlib.util.spec_from_file_location("stage157_s147", S147_PATH)
assert spec147 and spec147.loader
S147 = importlib.util.module_from_spec(spec147); sys.modules[spec147.name] = S147; spec147.loader.exec_module(S147)

S155_PATH = WORKSTREAM / "155_collect_hinako_wet_texture_entry_differential_evidence.py"
spec155 = importlib.util.spec_from_file_location("stage157_s155", S155_PATH)
assert spec155 and spec155.loader
S155 = importlib.util.module_from_spec(spec155); sys.modules[spec155.name] = S155; spec155.loader.exec_module(S155)

S156_PATH = WORKSTREAM / "156_collect_hinako_wet_texture_content_alpha_rebuild_feasibility_evidence.py"
spec156 = importlib.util.spec_from_file_location("stage157_s156", S156_PATH)
assert spec156 and spec156.loader
S156 = importlib.util.module_from_spec(spec156); sys.modules[spec156.name] = S156; spec156.loader.exec_module(S156)

def sha(b: bytes) -> str: return hashlib.sha256(b).hexdigest()

def parameter_record(name: str, value: float) -> bytes:
    n = name.encode() + b"\0"; raw = struct.pack("<f", value); size = 16 + len(n) + len(raw)
    return struct.pack("<3I2H", size, len(n), 0, 1, 1) + n + raw

def g1m(name: str, value: float, extra: int = 0) -> bytes:
    rec = parameter_record(name, value); payload = struct.pack("<I", 1) + rec + b"\0" * extra
    sec = struct.pack("<3I", 0x00010003, 12 + len(payload), 1) + payload
    g1mg_size = 0x30 + len(sec)
    g1mg = b"G1MG" + struct.pack("<2I", 0x30303430, g1mg_size) + b"DX11" + struct.pack("<I6f", 0,0,0,0,1,1,1) + struct.pack("<I",1) + sec
    total = 0x18 + len(g1mg)
    return b"_M1G" + struct.pack("<5I", 0x30303430, total, 0x18, 0, 1) + g1mg

def make_earc(members):
    header=0x1C; filename_size=8; name_bytes=0x20+filename_size*0x10; es=8+name_bytes; table=len(members)*es; payload=sum(len(x[1]) for x in members)
    out=bytearray(header+table+payload); struct.pack_into("<7I",out,0,0x45415243,filename_size,payload,header,table,len(members),0); off=header+table
    for i,(name,data) in enumerate(members):
        t=header+i*es; struct.pack_into("<2I",out,t,off,len(data)); enc=name.encode()+b"\0"; out[t+8:t+8+len(enc)]=enc; out[off:off+len(data)]=data; off+=len(data)
    return bytes(out)

def gust_chunked(payload: bytes) -> bytes:
    out=bytearray()
    for start in range(0,len(payload),0x4000):
        c=zlib.compress(payload[start:start+0x4000],9); out.extend(len(c).to_bytes(4,"little")); out.extend(c)
    out.extend((0).to_bytes(4,"little")); return bytes(out)

def write_parent(path: Path, selected: bytes):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_bytes(gust_chunked(make_earc([("dummy.bin",b"sentinel"),(S147.SELECTED_MEMBER_NAME,selected)])))

def bc1(c0: int, c1: int) -> bytes: return struct.pack("<HHI", c0, c1, 0)

def make_g1t(entries: list[bytes]) -> bytes:
    n=len(entries); raws=[]
    for payload in entries:
        raws.append(bytes([0x10,0x59,0x22,0,0,0,0,0])+payload)
    header_size=28+4*n; base=4*n; offsets=[]; cur=base
    for r in raws: offsets.append(cur); cur += len(r)
    total=header_size+cur; version=int.from_bytes(b"0060","big")
    hdr=struct.pack("<7I",S155.G1TG_MAGIC,version,total,header_size,n,10,0)
    flags=b"".join(struct.pack("<I",0) for _ in range(n)); tab=b"".join(struct.pack("<I",x) for x in offsets)
    return hdr+flags+tab+b"".join(raws)

class Stage157Tests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(prefix="stage157-tests-"); self.root=Path(self.tmp.name)
        self.target_g1m=g1m("targetWet",0.4); self.source_g1m=g1m("sourceWet",0.8,8)
        self.target_parent=self.root/"target_parent.elixir.gz"; write_parent(self.target_parent,self.target_g1m)
        base_entries=[bc1(0xffff,0) for _ in range(24)]; base_entries[23]=bc1(0,0xffff)
        source_entries=list(base_entries); source_entries[5]=bc1(0x1111,0x2222); source_entries[23]=bc1(0x1234,0x5678)+b"EXTRA-WET-ENTRY"
        self.target_g1t=make_g1t(base_entries); self.source_g1t=make_g1t(source_entries)
        tp=S155.parse_g1t(self.target_g1t,"target"); sp=S155.parse_g1t(self.source_g1t,"source")
        self.target_raw23=S156.raw_entry(self.target_g1t,tp,23); self.source_raw23=S156.raw_entry(self.source_g1t,sp,23)
        pack_root=self.root/"pack"
        manifest=S120.write_fixture_tree(pack_root,"PACK10_02.PAK",{
            TOOL.TARGET_PARENT_SUFFIX:self.target_parent.read_bytes(),
            TOOL.TARGET_G1T_SUFFIX:self.target_g1t,
            "data/b1/x64/character/sentinel.bin":b"keep",
        })
        S120.run_gust(PROJECT/".local/vendor/gust_tools/gust_pak",manifest,pack_root,self.root/"gust.log")
        self.baseline=pack_root/"PACK10_02.PAK"; self.baseline_sha=TOOL.sha256_file(self.baseline)
        self.workspace=PROJECT/".local/build/quartet_restoration"/("stage157_test_"+self.root.name); self.manifests=self.workspace/"manifests"

        self.orig_load=TOOL.load_module
        def loader(path: Path, name: str):
            if path.name.startswith("147_"): return S147
            if path.name.startswith("155_"): return S155
            if path.name.startswith("156_"): return S156
            return self.orig_load(path,name)
        self.load_patch=mock.patch.object(TOOL,"load_module",side_effect=loader); self.load_patch.start()
        patches={
            "EXPECTED_BASELINE_SHA256":self.baseline_sha,
            "EXPECTED_BASELINE_SIZE":self.baseline.stat().st_size,
            "EXPECTED_TARGET_PARENT_SHA256":TOOL.sha256_file(self.target_parent),
            "EXPECTED_TARGET_G1T_SHA256":sha(self.target_g1t),
            "EXPECTED_SOURCE_ENTRY23_RAW_SHA256":sha(self.source_raw23),
            "EXPECTED_TARGET_ENTRY23_RAW_SHA256":sha(self.target_raw23),
            "EXPECTED_SOURCE_ENTRY23_PAYLOAD_SHA256":sha(S156.payload_entry(self.source_g1t,S155.parse_g1t(self.source_g1t,"s"),23)),
            "EXPECTED_TARGET_ENTRY23_PAYLOAD_SHA256":sha(S156.payload_entry(self.target_g1t,S155.parse_g1t(self.target_g1t,"t"),23)),
        }
        self.patchers=[mock.patch.object(TOOL,k,v) for k,v in patches.items()]
        for p in self.patchers: p.start()
        self.s147_patchers=[
            mock.patch.object(S147,"EXPECTED_TARGET_MEMBER_SHA256",sha(self.target_g1m)),
            mock.patch.object(S147,"EXPECTED_SOURCE_MEMBER_SHA256",sha(self.source_g1m)),
            mock.patch.object(S147,"EXPECTED_TARGET_MEMBER_SIZE",len(self.target_g1m)),
            mock.patch.object(S147,"EXPECTED_SOURCE_MEMBER_SIZE",len(self.source_g1m)),
        ]
        for p in self.s147_patchers: p.start()

    def tearDown(self):
        for p in reversed(self.s147_patchers): p.stop()
        for p in reversed(self.patchers): p.stop()
        self.load_patch.stop(); shutil.rmtree(self.workspace,ignore_errors=True); self.tmp.cleanup()

    def build(self):
        return TOOL.build_profile_from_inputs(PROJECT,baseline_archive=self.baseline,source_school_wet_member=self.source_g1m,source_entry23_raw=self.source_raw23,gust_pak=PROJECT/".local/vendor/gust_tools/gust_pak",workspace_root=self.workspace,manifest_root=self.manifests,timeout_seconds=60)

    def test_g1t_rebuild_changes_exactly_entry23(self):
        candidate=S156.rebuild_one_entry(self.target_g1t,S155,23,self.source_raw23)
        rows=TOOL.verify_g1t_one_entry_change(S155,S156,self.target_g1t,candidate,23)
        self.assertEqual(sum(bool(r["changed"]) for r in rows),1); self.assertTrue(rows[23]["changed"]); self.assertTrue(all(r["verified"] for r in rows))

    def test_profile_changes_exactly_two_pack_members(self):
        profile,parent,g1t,pak,vals=self.build()
        self.assertEqual(profile["changed_member_count"],2)
        self.assertEqual(sum(r["baseline_sha256"]!=r["profile_sha256"] for r in pak),2)
        self.assertEqual(sum(r["target_sha256"]!=r["candidate_sha256"] for r in parent),1)
        self.assertEqual(sum(bool(r["changed"]) for r in g1t),1)
        self.assertTrue(all(r["passed"] for r in vals))

    def test_baseline_is_read_only(self):
        self.build(); self.assertEqual(TOOL.sha256_file(self.baseline),self.baseline_sha)

    def test_profile_is_fast_test_only(self):
        p,*_=self.build(); self.assertTrue(p["fast_test_only"]); self.assertFalse(p["runtime_validated"]); self.assertFalse(p["production_eligible"])

    def test_whole_g1t_is_not_source_transplant(self):
        p,*_=self.build(); self.assertNotEqual(p["candidate_g1t_sha256"],sha(self.source_g1t)); self.assertGreater(p["candidate_g1t_size"],len(self.target_g1t))

    def test_exact_real_stage156_hash_is_frozen(self):
        self.assertEqual(TOOL.STAGE156_SHA256,"78e975823454ca5416528d6e7f05b522d9b9b7599aab73c99d05b5a25f80367a")

    def test_runtime_stable_school_component_provenance_is_frozen(self):
        self.assertEqual(TOOL.STAGE148_ACTIVATION_SHA256,"9c6e9431e23a6fd0e96aa5ff08dc897ac003584bfaf4fdd4e20babd08f4f3e49")
        self.assertEqual(TOOL.STAGE148_ROLLBACK_SHA256,"113d6527cda4c787013d9af070927a52f1bf89735835600a76ae22644677aaed")

    def test_report_extension_policy_excludes_payloads(self):
        for ext in (".pak",".g1m",".g1t",".dds",".png"): self.assertIn(ext,TOOL.FORBIDDEN_REPORT_EXTENSIONS)

if __name__=="__main__": unittest.main()
