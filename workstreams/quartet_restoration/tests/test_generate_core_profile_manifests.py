from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
TOOL_PATH = ROOT / "workstreams" / "quartet_restoration" / "generate_core_profile_manifests.py"
SPEC = importlib.util.spec_from_file_location("generate_core_profile_manifests", TOOL_PATH)
assert SPEC and SPEC.loader
TOOL = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = TOOL
SPEC.loader.exec_module(TOOL)


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class CoreProfileManifestTests(unittest.TestCase):
    def _fixture(self, root: Path, *, profile_id: str = "test_profile"):
        (root / "workstreams/quartet_restoration").mkdir(parents=True)
        (root / "workstreams/quartet_restoration/VERSION").write_text("0.0.39\n", encoding="utf-8")
        rel = f".local/build/quartet_restoration/repack_tests/test/{profile_id}/Data/PACK11.PAK"
        path = root / rel
        path.parent.mkdir(parents=True)
        payload = b"local-profile-pak"
        path.write_bytes(payload)
        spec = TOOL.ProfileSpec(
            profile_id=profile_id,
            target_relative_path="Data/PACK11.PAK",
            baseline_sha256=sha(b"baseline"),
            baseline_size=len(b"baseline"),
            profile_sha256=sha(payload),
            profile_size=len(payload),
            local_profile_path=rel,
            changed_members=("event/b1/event_jp/test.ebd",),
        )
        registry = {
            "type": "br_quartet_restoration_runtime_validation_registry",
            "format_version": 1,
            "profiles": {},
            "event_group": {
                "profile_ids": [profile_id],
                "profile_count": 1,
                "individual_runtime_validated": False,
                "production_eligible": False,
            },
        }
        registry_path = root / TOOL.RUNTIME_VALIDATION_REGISTRY
        registry_path.parent.mkdir(parents=True, exist_ok=True)
        registry_path.write_text(json.dumps(registry, indent=2) + "\n", encoding="utf-8")
        return spec, path

    def test_generates_exact_schema_and_current_version(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            spec, _ = self._fixture(root)
            generated, report, manifests = TOOL.generate_manifests(
                project_root=root, specs=(spec,), create_report_archive=False
            )
            self.assertIsNone(report)
            self.assertEqual(len(manifests), 1)
            data = json.loads((generated / "test_profile.json").read_text(encoding="utf-8"))
            self.assertEqual(data["schema_version"], 1)
            self.assertEqual(data["workstream_version"], "0.0.39")
            self.assertEqual(data["changed_member_count"], len(data["changed_members"]))
            self.assertFalse(data["runtime_validated"])
            self.assertEqual(set(data), {
                "schema_version", "profile_id", "target_relative_path",
                "baseline_sha256", "baseline_size", "profile_sha256",
                "profile_size", "local_profile_path", "changed_member_count",
                "changed_members", "runtime_validated", "workstream_id",
                "workstream_version",
            })

    def test_canonical_registry_marks_only_bathroom_profile_runtime_validated(self):
        decisions, registry = TOOL.load_runtime_validation_registry(ROOT, TOOL.CURRENT_PROFILE_SPECS)
        self.assertEqual(
            [profile_id for profile_id, value in decisions.items() if value],
            ["candidate_bathroom_river_containing_pak_static_inverse_062e39915e7d"],
        )
        self.assertEqual(
            registry["profiles"]["candidate_bathroom_river_containing_pak_static_inverse_062e39915e7d"]
            ["confirmed_semantics"]["classification"],
            "water_visibility_transparency_restoration",
        )
        self.assertFalse(decisions["water_shader_swater_original_code"])
        self.assertFalse(decisions["height_fog_shader_original_code"])

    def test_missing_runtime_registry_is_fail_closed(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            spec, _ = self._fixture(root)
            (root / TOOL.RUNTIME_VALIDATION_REGISTRY).unlink()
            with self.assertRaisesRegex(TOOL.ManifestGenerationError, "missing runtime-validation registry"):
                TOOL.generate_manifests(project_root=root, specs=(spec,), create_report_archive=False)

    def test_checksum_mismatch_keeps_existing_registry_untouched(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            spec, path = self._fixture(root)
            generated = root / ".local/build/quartet_restoration/core_profiles/generated"
            generated.mkdir(parents=True)
            sentinel = generated / "old.json"
            sentinel.write_text('{"old": true}\n', encoding="utf-8")
            path.write_bytes(b"X" * spec.profile_size)
            with self.assertRaisesRegex(TOOL.ManifestGenerationError, "checksum mismatch"):
                TOOL.generate_manifests(
                    project_root=root, specs=(spec,), create_report_archive=False
                )
            self.assertTrue(sentinel.is_file())

    def test_rejects_path_traversal(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            spec, _ = self._fixture(root)
            bad = TOOL.ProfileSpec(
                **{**spec.__dict__, "local_profile_path": ".local/build/quartet_restoration/../escape.PAK"}
            )
            with self.assertRaisesRegex(TOOL.ManifestGenerationError, "unsafe local_profile_path"):
                TOOL.generate_manifests(
                    project_root=root, specs=(bad,), create_report_archive=False
                )

    def test_rejects_duplicate_profile_ids(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            spec, _ = self._fixture(root)
            with self.assertRaisesRegex(TOOL.ManifestGenerationError, "duplicate profile_id"):
                TOOL.generate_manifests(
                    project_root=root, specs=(spec, spec), create_report_archive=False
                )

    def test_rejects_symlink_profile(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            spec, path = self._fixture(root)
            actual = path.with_name("actual.PAK")
            path.replace(actual)
            path.symlink_to(actual.name)
            with self.assertRaisesRegex(TOOL.ManifestGenerationError, "must not be a symlink"):
                TOOL.generate_manifests(
                    project_root=root, specs=(spec,), create_report_archive=False
                )

    def test_success_replaces_stale_generated_manifests_only(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            spec, _ = self._fixture(root)
            registry = root / ".local/build/quartet_restoration/core_profiles"
            generated = registry / "generated"
            generated.mkdir(parents=True)
            (generated / "stale.json").write_text("{}\n", encoding="utf-8")
            manual = registry / "manual/keep.json"
            manual.parent.mkdir(parents=True)
            manual.write_text("{}\n", encoding="utf-8")
            result, _, _ = TOOL.generate_manifests(
                project_root=root, specs=(spec,), create_report_archive=False
            )
            self.assertFalse((result / "stale.json").exists())
            self.assertTrue((result / "test_profile.json").exists())
            self.assertTrue(manual.exists())


if __name__ == "__main__":
    unittest.main()
