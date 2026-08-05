import importlib.util
import json
import tempfile
import unittest
import sys
from pathlib import Path

SYNC_MODULE = Path(__file__).resolve().parents[1] / "quartet_translation_source_sync.py"
spec = importlib.util.spec_from_file_location("sync", SYNC_MODULE)
sync = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = sync
spec.loader.exec_module(sync)

TEXT_TOOL_MODULE = Path(__file__).resolve().parents[3] / "Blue_Reflection_Text_Tool" / "br_text_tool.py"
spec2 = importlib.util.spec_from_file_location("br_text_tool", TEXT_TOOL_MODULE)
text_tool = importlib.util.module_from_spec(spec2)
sys.modules[spec2.name] = text_tool
spec2.loader.exec_module(text_tool)


class QuartetPartitionCorrectionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        (self.root / "config").mkdir(parents=True)
        (self.root / "config/project_version").write_text("1\n")
        ws = self.root / "workstreams/translation"
        (ws / "docs").mkdir(parents=True)
        (ws / "VERSION").write_text("0.0.111\n")
        (ws / "STATUS.json").write_text(json.dumps({
            "type": "br_workstream_status",
            "workstream_id": "translation",
            "version": "0.0.111",
            "canonical_databases": [],
            "next_update": {},
        }))
        (ws / "CONTENT_CHANGELOG.json").write_text(json.dumps({"version": "0.0.111", "scope": "ds09"}))
        (ws / "docs/RELEASE_HISTORY.md").write_text("# History\n")
        (self.root / ".local/reports/translation").mkdir(parents=True)

    def write_unit(
        self,
        project,
        name,
        target_id,
        target_path,
        logical_id,
        *,
        en="English",
        en_original="English",
        en_auxiliary=None,
        source_role="canonical",
        initial_source="official_en",
        notes_marker=False,
    ):
        base = self.root / "titles" / project / "translation"
        folder = "events_quartet_extensions" if source_role == "quartet_extension" else "events"
        path = base / folder / f"{name}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        record = {
            "index": 0,
            "logical_id": logical_id,
            "jp": "日本語",
            "en_original": en_original,
            "en_auxiliary": en_auxiliary,
            "en": en,
            "alignment": {
                "status": "exact_index_msg_id",
                "initial_en_source": initial_source,
                "target_indices": {target_id: 0},
            },
        }
        if notes_marker:
            record["notes"] = "keep this"
            record["status"] = "reviewed"
        unit = {
            "type": "br_event_translation_unit",
            "format_version": 1,
            "project": project,
            "category": "event",
            "source_role": source_role,
            "targets": {target_id: {"template_path": target_path}},
            "records": [record],
        }
        path.write_text(json.dumps(unit, ensure_ascii=False))
        self.write_manifest(project)
        return path

    def write_manifest(self, project):
        base = self.root / "titles" / project / "translation"
        units = []
        for path in sorted(base.rglob("*.json")):
            if path.name == "translation_manifest.json":
                continue
            try:
                data = json.loads(path.read_text())
            except Exception:
                continue
            if data.get("type") in sync.UNIT_TYPES:
                units.append({
                    "path": path.relative_to(base).as_posix(),
                    "records": len(data.get("records", [])),
                    "category": data.get("category"),
                })
        (base / "translation_manifest.json").write_text(json.dumps({
            "type": "br_translation_project",
            "project": project,
            "units": units,
            "summary": {"units": len(units), "records": sum(x["records"] for x in units)},
        }))

    def make_wrong_state(self):
        self.write_unit(
            "blue_reflection", "br", "blue_reflection_quartet",
            "titles/blue_reflection/workspace/quartet/archives/PACK11/event/b1/event_en/br.ebm",
            "blue_reflection:event:br:0", en="BR edit", en_original="BR official", notes_marker=True,
        )
        self.write_unit(
            "second_light", "sl", "second_light_quartet",
            "titles/second_light/workspace/quartet/archives/PACK01_01/event/b2/event_en/sl.ebm",
            "second_light:event:sl:0", en="SL authored", en_original="SL official", notes_marker=True,
        )
        self.write_unit(
            "second_light", "false_ray_extension", "second_light_quartet",
            "titles/second_light/workspace/quartet/archives/PACK01_01/event/b2/event_en/false.ebm",
            "second_light:event_quartet_extension:false:0",
            en="Generated RAY EN", en_original="Generated RAY EN",
            source_role="quartet_extension", initial_source="quartet_official_en",
        )
        self.write_unit(
            "blue_reflection_sun", "sun", "blue_reflection_sun_quartet",
            "titles/blue_reflection_sun/workspace/quartet/archives/PACK01_02/event/b3/event_en/sun.ebm",
            "blue_reflection_sun:event:sun:0", en="SUN authored", en_original="SUN official", notes_marker=True,
        )
        for index in range(4):
            self.write_unit(
                "blue_reflection_ray", f"wrong_sl_{index}", "blue_reflection_ray_quartet",
                f"titles/blue_reflection_ray/workspace/quartet/archives/PACK01_03/event/b4/event_en/{index}.ebm",
                f"blue_reflection_ray:event:wrong_sl:{index}",
                en=f"Generated SL EN {index}", en_original=f"Generated SL EN {index}",
            )

    def test_initial_editable_recognizes_quartet_official_en(self):
        record = {
            "en_original": "Generated target EN",
            "en_auxiliary": None,
            "alignment": {"initial_en_source": "quartet_official_en"},
        }
        self.assertEqual(text_tool._initial_editable(record), "Generated target EN")

    def test_project_specs_use_correct_b2_b4_partitions(self):
        event_sets, system_sets = text_tool.project_specs(self.root)
        event = {item.project: item for item in event_sets}
        system = {item.project: item for item in system_sets}
        self.assertIn("PACK01_03/event/b4", event["second_light"].auxiliary_jp_root.as_posix())
        self.assertIn("PACK02_03/saves/b4", system["second_light"].auxiliary_jp_root.as_posix())
        self.assertIn("PACK01_01/event/b2", event["blue_reflection_ray"].source_jp_root.as_posix())
        self.assertIn("PACK02_01/saves/b2", system["blue_reflection_ray"].source_jp_root.as_posix())

    def test_snapshot_accepts_known_wrong_generated_state(self):
        self.make_wrong_state()
        output = self.root / "before.json"
        result = sync.snapshot(self.root, output)
        self.assertEqual(result["mapping_state"]["state"], "wrong_b2_second_light_b4_ray")
        counts = result["generated_wrong_scope"]["counts"]
        self.assertEqual(counts["authored_wrong_second_light_extension_records"], 0)
        self.assertEqual(counts["authored_wrong_ray_records"], 0)
        self.assertIn("second_light:event:sl:0", result["preserved_records"])
        self.assertNotIn("second_light:event_quartet_extension:false:0", result["preserved_records"])

    def test_snapshot_rejects_authored_wrong_ray_content(self):
        self.make_wrong_state()
        path = self.root / "titles/blue_reflection_ray/translation/events/wrong_sl_0.json"
        data = json.loads(path.read_text())
        data["records"][0]["en"] = "Authored change"
        path.write_text(json.dumps(data))
        with self.assertRaises(sync.SyncError):
            sync.snapshot(self.root, self.root / "before.json")

    def test_finalize_preserves_0111_content_and_rebuilds_ray(self):
        self.make_wrong_state()
        before = self.root / "before.json"
        sync.snapshot(self.root, before)

        # Remove false outputs and rewrite the preserved Second Light unit with b4.
        false_dir = self.root / "titles/second_light/translation/events_quartet_extensions"
        for path in false_dir.rglob("*.json"):
            path.unlink()
        for path in sorted(false_dir.rglob("*"), reverse=True):
            if path.is_dir():
                path.rmdir()
        false_dir.rmdir()
        sl_path = self.root / "titles/second_light/translation/events/sl.json"
        sl = json.loads(sl_path.read_text())
        sl["targets"]["second_light_quartet"]["template_path"] = (
            "titles/second_light/workspace/quartet/archives/PACK01_03/event/b4/event_en/sl.ebm"
        )
        sl["records"][0]["en_auxiliary"] = "Quartet b4 EN"
        sl_path.write_text(json.dumps(sl, ensure_ascii=False))
        self.write_unit(
            "second_light", "true_b4_extension", "second_light_quartet",
            "titles/second_light/workspace/quartet/archives/PACK01_03/event/b4/event_en/new.ebm",
            "second_light:event_quartet_extension:true_b4:0",
            en="New b4 EN", en_original="New b4 EN", en_auxiliary=None,
            source_role="quartet_extension", initial_source="quartet_official_en",
        )

        ray_root = self.root / "titles/blue_reflection_ray/translation"
        for path in sorted(ray_root.rglob("*"), reverse=True):
            if path.is_file():
                path.unlink()
            elif path.is_dir():
                path.rmdir()
        ray_root.rmdir()
        self.write_unit(
            "blue_reflection_ray", "true_ray", "blue_reflection_ray_quartet",
            "titles/blue_reflection_ray/workspace/quartet/archives/PACK01_01/event/b2/event_en/ray.ebm",
            "blue_reflection_ray:event:true_ray:0",
            en="RAY official", en_original="RAY official",
        )
        self.write_manifest("second_light")
        self.write_manifest("blue_reflection_ray")
        (self.root / ".local/reports/BR_TRANSLATION_EXPORT_REPORT.json").write_text(json.dumps({
            "ebm_validation": {"failures": []},
            "selected_projects": ["blue_reflection_ray", "second_light"],
        }))

        result = sync.finalize(self.root, before, self.root / "out")
        self.assertEqual(result["version"], "0.0.112")
        self.assertEqual((self.root / "workstreams/translation/VERSION").read_text().strip(), "0.0.112")
        sl_after = json.loads(sl_path.read_text())
        self.assertEqual(sl_after["records"][0]["en"], "SL authored")
        self.assertEqual(sl_after["records"][0]["notes"], "keep this")
        self.assertEqual(sl_after["records"][0]["status"], "reviewed")
        self.assertEqual(result["stats"]["second_light"]["event_nonnull_en_auxiliary"], 1)
        self.assertEqual(result["stats"]["blue_reflection_ray"]["target_branch_counts"]["b2"], 1)


if __name__ == "__main__":
    unittest.main()
