from __future__ import annotations

import importlib.util
import json
import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
MODULE_PATH = PROJECT_ROOT / "Blue_Reflection_Text_Tool/br_extension_tool.py"
SPEC = importlib.util.spec_from_file_location("br_extension_tool", MODULE_PATH)
assert SPEC and SPEC.loader
extension_tool = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = extension_tool
SPEC.loader.exec_module(extension_tool)

validate_dlc_registry = extension_tool.validate_dlc_registry
REGISTRY_PATH = (
    PROJECT_ROOT
    / "titles/blue_reflection/modules/quartet_legacy_dlc/registry/content_registry.json"
)


class DLCRegistryValidationTests(unittest.TestCase):
    def load_registry(self) -> dict:
        return json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))

    def synthetic_registry(self) -> dict:
        return {
            "type": "br_dlc_content_registry",
            "format_version": 1,
            "generated_registry": {
                "status": "metadata_only_not_buildable",
                "default_enabled": False,
                "raw_assets_embedded": False,
                "technical_types": sorted(extension_tool.DLC_TECHNICAL_CATALOG_TYPES),
            },
            "items": [
                {
                    "content_id": "operational_fixture",
                    "content_type": "event_family",
                    "quartet_status": "not_mapped",
                    "source_ownership": "requires_original_dlc",
                    "dependencies": [],
                },
                {
                    "content_id": "metadata_fixture",
                    "content_type": "generated_metadata_catalog",
                    "quartet_status": "metadata_inventory_only",
                    "source_ownership": "requires_original_dlc",
                    "dependencies": [],
                },
                {
                    "content_id": "generated_technical_fixture",
                    "content_type": "accessory",
                    "quartet_status": "generated_metadata_registry_only",
                    "source_ownership": "requires_original_dlc_when_applicable",
                    "dependencies": [],
                },
            ],
        }

    def test_current_registry_passes(self) -> None:
        self.assertEqual(validate_dlc_registry(self.load_registry()), [])

    def test_declared_technical_type_does_not_require_materialized_item(self) -> None:
        data = self.synthetic_registry()
        data["items"] = [
            item
            for item in data["items"]
            if item["quartet_status"] != "generated_metadata_registry_only"
        ]
        self.assertEqual(validate_dlc_registry(data), [])

    def test_unknown_status_is_rejected(self) -> None:
        data = self.synthetic_registry()
        data["items"][0]["quartet_status"] = "anything_goes"
        self.assertTrue(
            any("unsupported quartet_status" in error for error in validate_dlc_registry(data))
        )

    def test_when_applicable_ownership_is_limited_to_generated_technical_metadata(self) -> None:
        data = self.synthetic_registry()
        data["items"][0]["source_ownership"] = "requires_original_dlc_when_applicable"
        self.assertTrue(
            any(
                "operational content must require original DLC" in error
                for error in validate_dlc_registry(data)
            )
        )

    def test_generated_technical_metadata_requires_conditional_ownership(self) -> None:
        data = self.synthetic_registry()
        data["items"][2]["source_ownership"] = "requires_original_dlc"
        self.assertTrue(
            any(
                "generated technical metadata must use" in error
                for error in validate_dlc_registry(data)
            )
        )

    def test_metadata_status_cannot_be_reused_for_arbitrary_content_type(self) -> None:
        data = self.synthetic_registry()
        data["items"][1]["content_type"] = "event_family"
        self.assertTrue(
            any(
                "is not allowed for content_type" in error
                for error in validate_dlc_registry(data)
            )
        )

    def test_emitted_technical_type_must_be_declared(self) -> None:
        data = self.synthetic_registry()
        data["generated_registry"]["technical_types"].remove("accessory")
        self.assertTrue(
            any(
                "missing from generated_registry.technical_types" in error
                for error in validate_dlc_registry(data)
            )
        )

    def test_arbitrary_declared_technical_type_is_rejected(self) -> None:
        data = self.synthetic_registry()
        data["generated_registry"]["technical_types"].append("arbitrary_payload")
        self.assertTrue(
            any(
                "contains unsupported values" in error
                for error in validate_dlc_registry(data)
            )
        )

    def test_generated_registry_remains_non_buildable_and_disabled(self) -> None:
        data = self.synthetic_registry()
        data["generated_registry"]["status"] = "integrated"
        data["generated_registry"]["default_enabled"] = True
        errors = validate_dlc_registry(data)
        self.assertTrue(any("status must be metadata_only_not_buildable" in error for error in errors))
        self.assertTrue(any("default_enabled must be false" in error for error in errors))


if __name__ == "__main__":
    unittest.main()
