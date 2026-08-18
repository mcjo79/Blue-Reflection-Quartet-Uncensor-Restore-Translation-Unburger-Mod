from __future__ import annotations

import csv
import json
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[3]


def load_json(rel: str):
    return json.loads((PROJECT_ROOT / rel).read_text(encoding="utf-8"))


def version(rel: str) -> str:
    return (PROJECT_ROOT / rel).read_text(encoding="utf-8").strip()


class CanonicalStateConsistencyTests(unittest.TestCase):
    def test_versions_match_canonical_state(self) -> None:
        state = load_json("config/canonical_state.json")
        self.assertEqual(state["core_version"], version("config/project_version"))
        self.assertEqual(state["core_version"], version("workstreams/core/VERSION"))
        self.assertEqual(
            state["modules"]["blue_reflection_translation"]["version"],
            version("workstreams/translation/VERSION"),
        )
        self.assertEqual(
            state["modules"]["quartet_restoration"]["version"],
            version("workstreams/quartet_restoration/VERSION"),
        )
        self.assertEqual(
            state["modules"]["quartet_legacy_dlc"]["version"],
            version("workstreams/quartet_legacy_dlc/VERSION"),
        )

    def test_runtime_catalog_matches_distribution_manifest(self) -> None:
        catalog = load_json("Blue_Reflection_Patcher/internal/plan/catalog/catalog.json")
        manifest = load_json("distribution/bundle/manifest.template.json")
        self.assertEqual(catalog["modules"], manifest["modules"])

    def test_source_module_rows_match_manifests(self) -> None:
        with (PROJECT_ROOT / "config/modules.tsv").open(encoding="utf-8", newline="") as f:
            rows = list(csv.DictReader(f, delimiter="\t"))
        by_id = {row["module_id"]: row for row in rows}
        self.assertEqual(len(by_id), len(rows))
        for module_id, row in by_id.items():
            manifest = load_json(row["manifest_path"])
            self.assertEqual(manifest["module_id"], module_id)
            self.assertEqual(manifest["project"], row["project"])
            self.assertEqual(manifest["module_type"], row["module_type"])
            self.assertEqual(manifest["status"], row["status"])
            self.assertEqual(bool(manifest["default_enabled"]), row["default_enabled"] == "true")
            self.assertEqual(manifest["targets"], row["target_ids"].split(","))
            deps = [] if row["dependencies"] == "-" else row["dependencies"].split(",")
            self.assertEqual(manifest["dependencies"], deps)

    def test_quartet_pc_module_defaults_are_current(self) -> None:
        catalog = load_json("Blue_Reflection_Patcher/internal/plan/catalog/catalog.json")
        by_id = {m["module_id"]: m for m in catalog["modules"]}
        for module_id in (
            "blue_reflection_translation",
            "quartet_restoration",
            "quartet_movie_restoration",
            "quartet_legacy_dlc",
        ):
            self.assertIn("blue_reflection_quartet", by_id[module_id]["default_targets"])
        self.assertIn(
            "quartet_restoration",
            by_id["quartet_movie_restoration"]["dependencies"],
        )

    def test_pc_composition_profiles_are_not_historical_placeholders(self) -> None:
        paths = {
            "quartet_translation_restoration": "titles/blue_reflection/profiles/quartet_translation_restoration.json",
            "quartet_complete": "titles/blue_reflection/profiles/quartet_complete.json",
            "quartet_translation_dlc": "titles/blue_reflection/profiles/quartet_translation_dlc.json",
        }
        for name, path in paths.items():
            profile = load_json(path)
            self.assertEqual(profile["status"], "active", name)
        self.assertIn(
            "quartet_movie_restoration",
            load_json(paths["quartet_translation_restoration"])["enabled_modules"],
        )
        self.assertIn(
            "quartet_movie_restoration",
            load_json(paths["quartet_complete"])["enabled_modules"],
        )

    def test_workstream_statuses_match_current_versions(self) -> None:
        translation = load_json("workstreams/translation/STATUS.json")
        dlc = load_json("workstreams/quartet_legacy_dlc/STATUS.json")
        self.assertEqual(translation["version"], version("workstreams/translation/VERSION"))
        self.assertEqual(dlc["version"], version("workstreams/quartet_legacy_dlc/VERSION"))
        summary = dlc["current_runtime_summary"]
        self.assertEqual(summary["blue_reflection_dlc"], "PASS")
        self.assertEqual(summary["second_light_dlc"], "PASS")
        self.assertEqual(summary["translation_composition"], "PASS")
        self.assertEqual(summary["combined_unburger_assets_build_and_read"], "PASS")


if __name__ == "__main__":
    unittest.main()
