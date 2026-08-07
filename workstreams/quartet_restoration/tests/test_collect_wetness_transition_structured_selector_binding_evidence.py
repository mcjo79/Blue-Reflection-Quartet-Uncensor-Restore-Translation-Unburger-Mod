from __future__ import annotations

import csv
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[3]
TOOL_PATH = PROJECT / "workstreams/quartet_restoration/163_collect_wetness_transition_structured_selector_binding_evidence.py"
spec = importlib.util.spec_from_file_location("stage163", TOOL_PATH)
assert spec and spec.loader
TOOL = importlib.util.module_from_spec(spec)
spec.loader.exec_module(TOOL)


def read_tsv(path: Path):
    with path.open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f, delimiter="\t"))


class Stage163Tests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.fixture = self.root / "fixture"
        self.reports = self.root / "reports"
        self.workspace = self.root / "workspace"
        self._make_fixture()

    def tearDown(self):
        self.temp.cleanup()

    def _write(self, side: str, rel: str, text: str):
        p = self.fixture / "br1_language" / side / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")

    def _make_fixture(self):
        generic = "<Root><Node Id='900' Name='fixture_secret_value'/></Root>"
        for rel in TOOL.STRUCTURED_PATHS:
            for side in ("source", "target"):
                self._write(side, rel, generic)

        source_charabase = """<Root>
          <CharaBase Id='100' Model='pc00_scl' defaultTexture='pc00_scl'/>
          <CharaBase Id='101' Model='pc00_scl_w' defaultTexture='pc00_scl_w'/>
          <CharaBase Id='200' Model='pc01_scl' defaultTexture='pc01_scl'/>
          <CharaBase Id='201' Model='pc01_scl_w' defaultTexture='pc01_scl_w'/>
        </Root>"""
        target_charabase = """<Root>
          <CharaBase Id='1100' Model='pc00_scl' defaultTexture='pc00_scl'/>
          <CharaBase Id='1101' Model='pc00_scl_w' defaultTexture='pc00_scl_w'/>
          <CharaBase Id='1200' Model='pc01_scl' defaultTexture='pc01_scl'/>
          <CharaBase Id='1201' Model='pc01_scl_w' defaultTexture='pc01_scl_w'/>
        </Root>"""
        source_costume = "<Root><Route Dry='100' Wet='101'/><Route Dry='200' Wet='201'/></Root>"
        target_costume = "<Root><Route Dry='1100' Wet='1101'/><Route Dry='1200' Wet='1201'/></Root>"
        self._write("source", "saves/chara/charabase.xml", source_charabase)
        self._write("target", "saves/chara/charabase.xml", target_charabase)
        self._write("source", "saves/costume/costume.xml", source_costume)
        self._write("target", "saves/costume/costume.xml", target_costume)

    def build(self):
        return TOOL.build_report(
            PROJECT,
            report_root=self.reports,
            output_report_root=self.reports,
            workspace_root=self.workspace,
            fixture_root=self.fixture,
            verify_payload_hashes=False,
            create_archive=False,
            skip_prerequisite_hashes_for_fixture=True,
        )

    def test_exact_pc00_dry_and_wet_tokens_are_found(self):
        _, summary = self.build()
        rows = read_tsv(self.reports / TOOL.REPORT_DIR / "SCHOOL_DRY_WET_TOKEN_HITS.tsv")
        target = {(r["exact_token"], r["normalized_path"]) for r in rows if r["side"] == "target"}
        self.assertIn(("pc00_scl", "saves/chara/charabase.xml"), target)
        self.assertIn(("pc00_scl_w", "saves/chara/charabase.xml"), target)
        self.assertGreater(summary["exact_school_dry_wet_token_hit_rows"], 0)

    def test_numeric_ids_get_independent_cross_references(self):
        self.build()
        rows = read_tsv(self.reports / TOOL.REPORT_DIR / "NUMERIC_CROSS_REFERENCES.tsv")
        hits = [r for r in rows if r["seed_side"] == "target" and "pc00_" in r["seed_tokens"] and r["hit_path"] == "saves/costume/costume.xml"]
        self.assertTrue(hits)
        self.assertTrue(all(r["independent_table_hit"] == "True" for r in hits))

    def test_pc00_becomes_bounded_runtime_trace_anchor_not_semantic_proof(self):
        _, summary = self.build()
        rows = read_tsv(self.reports / TOOL.REPORT_DIR / "BOUNDED_RUNTIME_TRACE_ANCHORS.tsv")
        pc00 = [r for r in rows if r["character_id"] == "pc00"]
        self.assertEqual(len(pc00), 1)
        self.assertEqual(pc00[0]["classification"], "bounded_structured_runtime_trace_anchor_not_selector_semantics")
        self.assertEqual(pc00[0]["runtime_trace_priority"], "highest")
        self.assertEqual(pc00[0]["selector_binding_confirmed"], "False")
        self.assertEqual(pc00[0]["transparency_semantics_confirmed"], "False")
        self.assertEqual(summary["pc00_target_bounded_trace_anchor_rows"], 1)

    def test_pair_matrix_has_all_15_characters_per_side(self):
        _, summary = self.build()
        rows = read_tsv(self.reports / TOOL.REPORT_DIR / "DRY_WET_PAIR_MATRIX.tsv")
        self.assertEqual(len(rows), 30)
        self.assertEqual(summary["pair_matrix_rows"], 30)

    def test_raw_xml_values_are_not_exported(self):
        self.build()
        out = self.reports / TOOL.REPORT_DIR
        text = "\n".join(p.read_text(encoding="utf-8") for p in out.iterdir() if p.suffix in {".tsv", ".json"})
        self.assertNotIn("fixture_secret_value", text)
        self.assertIn("pc00_scl_w", text)

    def test_policy_remains_read_only_and_generation10_v2_forbidden(self):
        _, summary = self.build()
        self.assertFalse(summary["installed_game_modified"])
        self.assertFalse(summary["pak_built_or_repacked"])
        self.assertFalse(summary["runtime_trace_performed"])
        self.assertFalse(summary["selector_binding_confirmed"])
        self.assertFalse(summary["wet_transparency_mechanism_confirmed"])
        self.assertTrue(summary["generation10_v2_dependency_forbidden"])
        self.assertEqual(summary["write_authorized_rows"], 0)

    def test_stage162_runtime_result_is_canonicalized(self):
        ws = PROJECT / "workstreams/quartet_restoration"
        status = json.loads((ws / "STATUS.json").read_text())
        row = status["wet_school_entry23_entry43_alpha_fast_test_lab_stage"]
        self.assertTrue(row["runtime_tested"])
        self.assertTrue(row["runtime_stable"])
        self.assertFalse(row["entry43_visible_effect_observed"])
        self.assertFalse(row["wet_shirt_transparency_restored"])
        self.assertTrue(row["exact_pack10_02_baseline_restored"])
        registry = json.loads((ws / "RUNTIME_VALIDATION_REGISTRY.json").read_text())
        fast = registry["fast_test_results"][TOOL.STAGE162_PROFILE_ID]
        self.assertEqual(fast["activation_evidence_sha256"], TOOL.STAGE162_ACTIVATION_SHA256)
        self.assertEqual(fast["rollback_evidence_sha256"], TOOL.STAGE162_ROLLBACK_SHA256)
        self.assertFalse(fast["entry43_interpretation"]["runtime_supported_as_visible_transparency_component"])

    def test_tool_version_matches_workstream(self):
        current = tuple(int(x) for x in (PROJECT / "workstreams/quartet_restoration/VERSION").read_text().strip().split("."))
        self.assertGreaterEqual(current, (0, 1, 84))
        self.assertEqual(TOOL.TOOL_VERSION, "0.1.84")


if __name__ == "__main__":
    unittest.main()
