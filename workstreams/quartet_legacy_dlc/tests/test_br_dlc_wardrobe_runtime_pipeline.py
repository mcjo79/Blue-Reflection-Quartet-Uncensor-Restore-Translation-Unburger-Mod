import importlib.util, json, pathlib, tempfile, unittest

ROOT=pathlib.Path(__file__).resolve().parents[1]
SPEC=importlib.util.spec_from_file_location("pipeline",ROOT/"br_dlc_wardrobe_runtime_pipeline.py")
M=importlib.util.module_from_spec(SPEC); SPEC.loader.exec_module(M)

class PipelineTests(unittest.TestCase):
    def test_generation10_records_exact(self):
        p=ROOT/"runtime_payloads/bkn_dry_generation10/wardrobe_records.json"
        d=M.validate_record_manifest(p)
        self.assertEqual(len(d["records"]),8)
        self.assertEqual([r["character"] for r in d["records"]],list(range(8)))
        self.assertEqual([r["label_id"] for r in d["records"]],list(range(393339,393347)))
        self.assertEqual([r["field08"] for r in d["records"]],[723,725,727,729,731,733,735,737])
        for r in d["records"]:
            self.assertEqual(r["field08"],r["field0c"])
            self.assertEqual(r["field08"],r["field10"])
            self.assertEqual(r["field18"],0)
            self.assertEqual(r["field1c"],0)
            self.assertTrue(r["visible"])
    def test_manifest_scope(self):
        with open(ROOT/"runtime_payloads/bkn_dry_generation10/manifest.json") as f:\n            d=json.load(f)
        self.assertEqual(d["runtime_semantics"]["logical_indices"],list(range(56,64)))
        self.assertFalse(d["runtime_semantics"]["global_show_all"])
        self.assertFalse(d["scope"]["pc08"])
        self.assertFalse(d["scope"]["wet_bkn"])
    def test_reject_visible_nonzero_field18(self):
        d={"type":"br_runtime_wardrobe_records","format_version":1,"capability":M.CAPABILITY,
           "records":[{"label_id":1,"character":0,"field08":1,"field0c":1,"field10":1,"field14":1,
           "field18":1,"field1c":0,"field20":7,"field24":0,"field28":0,"field2c":0,"visible":True}]}
        with tempfile.TemporaryDirectory() as td:
            p=pathlib.Path(td)/"r.json"; p.write_text(json.dumps(d))
            with self.assertRaises(M.PipelineError): M.validate_record_manifest(p)
    def test_project_root_from_script(self):
        self.assertEqual(M.project_root_from_script(),ROOT.parents[1])

if __name__=="__main__": unittest.main()
