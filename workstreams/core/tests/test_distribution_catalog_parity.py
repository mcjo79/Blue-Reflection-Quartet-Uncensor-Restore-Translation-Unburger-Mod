from __future__ import annotations

import json
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[3]
MANIFEST_PATH = PROJECT_ROOT / "distribution/bundle/manifest.template.json"
CATALOG_PATH = (
    PROJECT_ROOT
    / "Blue_Reflection_Patcher/internal/plan/catalog/catalog.json"
)


class DistributionCatalogParityTests(unittest.TestCase):
    def test_embedded_catalog_matches_public_bundle_manifest(self) -> None:
        manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
        catalog = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))

        self.assertEqual(manifest.get("type"), "br_patch_bundle")
        self.assertEqual(catalog.get("type"), "br_module_catalog")
        self.assertEqual(catalog.get("format_version"), 1)

        manifest_modules = {
            module["module_id"]: module
            for module in manifest.get("modules", [])
        }
        catalog_modules = {
            module["module_id"]: module
            for module in catalog.get("modules", [])
        }

        self.assertEqual(
            manifest_modules,
            catalog_modules,
            "distribution bundle module definitions diverge from the "
            "catalog embedded in the patcher binary",
        )


if __name__ == "__main__":
    unittest.main()
