import importlib.util, struct, sys, tempfile, unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
P = ROOT / "165_trace_wet_model_pointer_roundtrip.py"
spec = importlib.util.spec_from_file_location("stage165_testmod", P)
M = importlib.util.module_from_spec(spec); sys.modules[spec.name] = M; spec.loader.exec_module(M)
S = M.S164

class Reader:
    def __init__(self, segments): self.segments=segments
    def read(self, addr, size):
        for start,data in self.segments:
            if start <= addr < start+len(data):
                off=addr-start; return data[off:off+size]
        raise OSError("unmapped")

class Stage165Tests(unittest.TestCase):
    def map(self,start,size,path=""):
        return S.MapRow(start,start+size,"rw-p",0,"00:00",0,path)

    def test_dynamic_wet_residency_ignores_stale_dry_copy(self):
        d=[{"mapping_key":"a","mapping_relative_offset":10,"address":0x1010,"address_hex":"0x1010"}]
        w=[{"mapping_key":"a","mapping_relative_offset":10,"address":0x1010,"address_hex":"0x1010"}, {"mapping_key":"a","mapping_relative_offset":20,"address":0x1020,"address_hex":"0x1020"}]
        got=M.dynamic_wet_occurrences(d,w)
        self.assertEqual([x["address"] for x in got],[0x1020])

    def test_exact_token_scan_finds_wet_model(self):
        start=0x100000
        data=bytearray(8192); at=1234; data[at:at+len(M.WET_MODEL_TOKEN)]=M.WET_MODEL_TOKEN
        mp=self.map(start,len(data))
        rows,stats=M.scan_wet_model_token(Reader([(start,bytes(data))]),[mp],Path("/game"),"wet",max_bytes=len(data))
        self.assertEqual(len(rows),1); self.assertEqual(rows[0]["address"],start+at)
        self.assertEqual(stats["occurrence_rows"],1)

    def test_targeted_pointer_scan_finds_pointer(self):
        token_addr=0x200000+500
        mem_start=0x300000
        data=bytearray(4096); site_off=800; data[site_off:site_off+8]=struct.pack("<Q",token_addr)
        mp=self.map(mem_start,len(data))
        target={"address":token_addr,"address_hex":hex(token_addr),"mapping_key":"tok","mapping_relative_offset":500}
        rows,stats=M.scan_pointers_to_dynamic_wet(Reader([(mem_start,bytes(data))]),[mp],Path("/game"),[target],max_bytes=len(data))
        self.assertEqual(len(rows),1); self.assertEqual(rows[0]["site_address"],mem_start+site_off)
        self.assertEqual(stats["target_patterns"],1)

    def test_roundtrip_site_classifies_dry_school_target(self):
        site=0x400100; dry_obj=0x500000
        sdata=bytearray(4096); sdata[0x100:0x108]=struct.pack("<Q",dry_obj)
        odata=bytearray(4096); odata[:32]=b"prefix pc00_scl suffix\x00"
        maps=[self.map(0x400000,len(sdata)),self.map(dry_obj,len(odata))]
        wet=[{"site_address":site,"site_address_hex":hex(site),"wet_target_address":0x600000,"wet_target_address_hex":"0x600000"}]
        rows=M.read_roundtrip_sites(Reader([(0x400000,bytes(sdata)),(dry_obj,bytes(odata))]),maps,wet,Path("/game"))
        self.assertEqual(rows[0]["dry2_pointed_payload_class"],"points_to_dry_school_token")
        self.assertTrue(rows[0]["pointer_changed"])
        self.assertIn("high_value",rows[0]["classification"])

    def test_wet_token_is_not_misclassified_as_dry(self):
        start=0x700000; data=b"xx pc00_scl_w yy"+b"\x00"*100
        mp=self.map(start,len(data))
        cls,h=M.classify_pointed_payload(Reader([(start,data)]),[mp],start)
        self.assertEqual(cls,"points_to_wet_school_token"); self.assertTrue(h)

    def test_report_contract_constants(self):
        self.assertEqual(M.TOOL_VERSION,"0.1.87")
        self.assertEqual(M.STAGE164_SHA256,"b1763e27075d47287bb64e71c6d2f8454c3f49a058747422ed1ddcaf06fa70dc")
        self.assertEqual(M.PACK10_02_BASELINE_SHA256,"e798f39c3bcdbb11381197bddf9bd3ad8de6ccf5d7c0c78b22613046d47f5302")

    def test_script_has_no_process_write_api(self):
        text=P.read_text()
        self.assertNotIn("process_vm_writev",text)
        self.assertNotIn("/proc/{pid}/mem",text)
        self.assertNotIn("ptrace(PTRACE_POK",text)

    def test_workflow_documents_previous_wet_safe_baseline_rule(self):
        text=(ROOT/"WET_MODEL_POINTER_ROUNDTRIP_TRACE_WORKFLOW.md").read_text()
        self.assertIn("Earlier WET use before DRY1 does not invalidate",text)
        self.assertIn("mapping+relative-offset",text)

if __name__ == "__main__": unittest.main()
