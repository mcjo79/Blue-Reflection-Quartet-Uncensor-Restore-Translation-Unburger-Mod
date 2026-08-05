import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

MODULE_PATH = Path(__file__).resolve().parents[1] / "br_dlc_bkn_dry_canonical_patch_proposal_tool.py"
spec = importlib.util.spec_from_file_location("canonical_patch_tool", MODULE_PATH)
mod = importlib.util.module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(mod)


class CanonicalPatchProposalTest(unittest.TestCase):
    def handoff(self):
        return {
            "type": "br_quartet_legacy_dlc_shadow_core_rehearsal_handoff",
            "handoff_version": "0.0.32",
            "shadow_rehearsal_passed": True,
            "canonical_core_modified": False,
            "production_wiring_applied": False,
            "authorization": {
                "core_patch_applied": False,
                "canonical_core_modified": False,
                "candidate_installed": False,
                "real_transaction_prepare_enabled": False,
                "real_transaction_commit_enabled": False,
                "profile_build_allowed": False,
                "profile_registered": False,
                "runtime_validated": False,
                "wet_variant_included": False,
                "game_modified": False,
                "git_modified": False,
            },
            "artifact_contract": [
                {"relative_path": "Data/PACK10_02.PAK"},
                {"relative_path": "Data/PACK12.PAK"},
            ],
        }

    def test_validate_shadow_handoff_accepts_exact_two_artifacts(self):
        rows = mod.validate_shadow_handoff(self.handoff())
        self.assertEqual([r["relative_path"] for r in rows], list(mod.EXPECTED_TARGETS))

    def test_validate_shadow_handoff_rejects_prepare_authorization(self):
        value = self.handoff()
        value["authorization"]["real_transaction_prepare_enabled"] = True
        with self.assertRaises(mod.CanonicalPatchProposalError):
            mod.validate_shadow_handoff(value)

    def test_patch_catalog_preserves_other_rows_and_declares_exact_artifacts(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "catalog.json"
            doc = {
                "type": "br_local_payload_catalog",
                "format_version": 1,
                "module_targets": [
                    {"module_id": "other", "target_id": "target", "source_kind": "x", "connection_status": "pending", "artifacts": []},
                    {"module_id": "quartet_legacy_dlc", "target_id": "blue_reflection_quartet", "source_kind": "old", "connection_status": "pending_adapter", "reason": "old", "artifacts": []},
                ],
            }
            path.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
            candidate = {
                "module_id": "quartet_legacy_dlc",
                "target_id": "blue_reflection_quartet",
                "source_kind": "validated_quartet_legacy_dlc_handoff",
                "connection_status": "connected_preview_only",
                "reason": "preview only",
                "artifacts": [{"relative_path": "Data/PACK10_02.PAK"}, {"relative_path": "Data/PACK12.PAK"}],
            }
            before = mod.patch_catalog(path, candidate)
            self.assertEqual(before["source_kind"], "old")
            result = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(result["module_targets"][0], doc["module_targets"][0])
            self.assertEqual(result["module_targets"][1]["artifacts"], candidate["artifacts"])

    def test_patch_preview_source_inserts_dedicated_dispatch_once(self):
        source = '''package payloadpreview\nfunc Build() {\n\t\t\tif !module.Ready {\n\t\t\t\ttarget.PendingModuleCount++\n\t\t\t\ttarget.Warnings = append(target.Warnings, fmt.Sprintf("%s: %s", moduleID, spec.Reason))\n\t\t\t} else {\n\t\t\t}\n}\n'''
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "preview.go"
            path.write_text(source, encoding="utf-8")
            mod.patch_preview_source(path)
            result = path.read_text(encoding="utf-8")
            self.assertEqual(result.count("inspectLegacyDLCModule"), 1)
            self.assertIn("continue", result)

    def test_unified_patch_uses_dev_null_for_added_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            old = root / "old"
            new = root / "new"
            old.mkdir()
            new.mkdir()
            (old / "existing.txt").write_text("old\n", encoding="utf-8")
            (new / "existing.txt").write_text("new\n", encoding="utf-8")
            (new / "added.txt").write_text("added\n", encoding="utf-8")
            patch = mod.unified_patch(old, new, [Path("existing.txt"), Path("added.txt")])
            self.assertIn("--- /dev/null", patch)
            self.assertIn("+++ b/Blue_Reflection_Patcher/added.txt", patch)
            self.assertIn("-old", patch)
            self.assertIn("+new", patch)


if __name__ == "__main__":
    unittest.main()
