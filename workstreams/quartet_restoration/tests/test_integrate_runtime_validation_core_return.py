from __future__ import annotations

import importlib.util
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
TOOL_PATH = ROOT / "workstreams/quartet_restoration/138_integrate_runtime_validation_core_return.py"
GENERATOR_PATH = ROOT / "workstreams/quartet_restoration/generate_core_profile_manifests.py"


def load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


TOOL = load(TOOL_PATH, "integrate_runtime_validation_core_return")
GENERATOR = load(GENERATOR_PATH, "runtime_validation_generator_for_tests")


class RuntimeValidationCanonicalIntegrationTests(unittest.TestCase):
    def fixture(self, root: Path) -> None:
        ws = root / "workstreams/quartet_restoration"
        ws.mkdir(parents=True)
        (ws / "VERSION").write_text(TOOL.EXPECTED_VERSION + "\n", encoding="utf-8")
        shutil.copy2(ROOT / TOOL.REGISTRY_REL, root / TOOL.REGISTRY_REL)

    def test_real_registry_selects_only_bathroom_profile(self):
        registry = json.loads((ROOT / TOOL.REGISTRY_REL).read_text(encoding="utf-8"))
        decisions = TOOL.validate_registry(registry, GENERATOR.CURRENT_PROFILE_SPECS)
        self.assertEqual([key for key, value in decisions.items() if value], [TOOL.B_PROFILE])
        self.assertFalse(decisions[TOOL.W_PROFILE])
        self.assertFalse(decisions[TOOL.H_PROFILE])
        self.assertEqual(sum(value is False for value in decisions.values()), 14)

    def test_metadata_only_integration_builds_canonical_evidence(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.fixture(root)
            archive, manifests, registry = TOOL.integrate(root, generator=GENERATOR, regenerate=False)
            self.assertTrue(archive.is_file())
            self.assertEqual(sum(row["runtime_validated"] is True for row in manifests), 1)
            self.assertTrue(next(row for row in manifests if row["profile_id"] == TOOL.B_PROFILE)["runtime_validated"])
            self.assertEqual(
                registry["profiles"][TOOL.B_PROFILE]["confirmed_semantics"]["classification"],
                "water_visibility_transparency_restoration",
            )
            report_dir = root / ".local/reports/quartet_restoration" / TOOL.REPORT_DIR_NAME
            summary = json.loads((report_dir / "SUMMARY.json").read_text(encoding="utf-8"))
            self.assertEqual(summary["runtime_validated_profile_rows"], 1)
            self.assertEqual(summary["runtime_failed_shader_profile_rows"], 2)
            self.assertEqual(summary["deferred_event_profile_rows"], 12)
            self.assertFalse(summary["policy"]["installed_game_modified"])
            self.assertFalse(summary["policy"]["core_modified"])

    def test_rejects_second_runtime_validated_profile(self):
        registry = json.loads((ROOT / TOOL.REGISTRY_REL).read_text(encoding="utf-8"))
        registry["profiles"][TOOL.W_PROFILE]["runtime_validated"] = True
        registry["profiles"][TOOL.W_PROFILE]["production_eligible"] = True
        with self.assertRaisesRegex(TOOL.IntegrationError, "failed shader must remain unvalidated|validated profile set"):
            TOOL.validate_registry(registry, GENERATOR.CURRENT_PROFILE_SPECS)

    def test_rejects_profile_hash_drift(self):
        registry = json.loads((ROOT / TOOL.REGISTRY_REL).read_text(encoding="utf-8"))
        registry["profiles"][TOOL.B_PROFILE]["profile_sha256"] = "0" * 64
        with self.assertRaisesRegex(TOOL.IntegrationError, "profile hash mismatch"):
            TOOL.validate_registry(registry, GENERATOR.CURRENT_PROFILE_SPECS)

    def test_rejects_event_group_promotion(self):
        registry = json.loads((ROOT / TOOL.REGISTRY_REL).read_text(encoding="utf-8"))
        registry["event_group"]["individual_runtime_validated"] = True
        with self.assertRaisesRegex(TOOL.IntegrationError, "event profiles must remain individually unvalidated"):
            TOOL.validate_registry(registry, GENERATOR.CURRENT_PROFILE_SPECS)

    def test_rejects_unproven_b_semantics(self):
        registry = json.loads((ROOT / TOOL.REGISTRY_REL).read_text(encoding="utf-8"))
        registry["profiles"][TOOL.B_PROFILE]["confirmed_semantics"]["classification"] = "unknown"
        with self.assertRaisesRegex(TOOL.IntegrationError, "B semantics mismatch"):
            TOOL.validate_registry(registry, GENERATOR.CURRENT_PROFILE_SPECS)

    def test_report_contains_no_payload_extensions(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.fixture(root)
            TOOL.integrate(root, generator=GENERATOR, regenerate=False)
            report_dir = root / ".local/reports/quartet_restoration" / TOOL.REPORT_DIR_NAME
            forbidden = {".pak", ".g1e", ".g1em", ".g1m", ".g1t", ".elixir", ".ebm", ".ebd"}
            self.assertFalse([p for p in report_dir.rglob("*") if p.is_file() and p.suffix.lower() in forbidden])


if __name__ == "__main__":
    unittest.main()
