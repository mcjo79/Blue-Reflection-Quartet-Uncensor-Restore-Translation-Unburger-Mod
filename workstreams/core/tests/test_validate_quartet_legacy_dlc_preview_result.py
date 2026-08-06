import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / "tools" / "validate_quartet_legacy_dlc_preview_result.py"
spec = importlib.util.spec_from_file_location("legacy_preview_validator", SCRIPT)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class LegacyPreviewValidatorTests(unittest.TestCase):
    def write_fixture(self, root: Path, preview: dict):
        tx = {"type": "status", "generated_utc": "one", "transactions": []}
        (root / "PAYLOAD_PREVIEW.json").write_text(json.dumps(preview))
        (root / "TRANSACTION_STATUS_BEFORE.json").write_text(json.dumps(tx))
        tx["generated_utc"] = "two"
        (root / "TRANSACTION_STATUS_AFTER.json").write_text(json.dumps(tx))
        stat = "Data/PACK10_02.PAK\t1\nData/PACK12.PAK\t1\n"
        (root / "GAME_TARGET_STAT_BEFORE.tsv").write_text(stat)
        (root / "GAME_TARGET_STAT_AFTER.tsv").write_text(stat)

    def test_null_artifacts_returns_structured_rejection(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            reason = "legacy DLC member delta does not match bounded family policy: Data/PACK12.PAK"
            preview = {
                "status": "not_ready", "commit_enabled": False,
                "targets": [{"selected_modules": ["quartet_legacy_dlc"], "modules": [{
                    "module_id": "quartet_legacy_dlc",
                    "source_kind": module.EXPECTED_SOURCE_KIND,
                    "connection_status": "connected_preview_only",
                    "ready": False, "reason": reason, "artifacts": None,
                }]}],
            }
            self.write_fixture(root, preview)
            result = module.validate_preview_root(root)
            self.assertEqual(result["status"], "fail")
            self.assertEqual(result["structured_rejection_reason"], reason)
            self.assertEqual(result["artifact_paths"], [])
            self.assertEqual(result["policy_rejections"][0]["reason"], reason)

    def test_ready_two_artifact_preview_passes(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            preview = {
                "status": "ready", "commit_enabled": False,
                "targets": [{"selected_modules": ["quartet_legacy_dlc"], "modules": [{
                    "module_id": "quartet_legacy_dlc",
                    "source_kind": module.EXPECTED_SOURCE_KIND,
                    "connection_status": "connected_preview_only",
                    "ready": True, "reason": "ready", "artifacts": [
                        {"relative_path": "Data/PACK10_02.PAK"},
                        {"relative_path": "Data/PACK12.PAK"},
                    ],
                }]}],
            }
            self.write_fixture(root, preview)
            result = module.validate_preview_root(root)
            self.assertEqual(result["status"], "pass")
            self.assertIsNone(result["structured_rejection_reason"])
            self.assertEqual(result["artifact_paths"], module.EXPECTED_ARTIFACTS)


if __name__ == "__main__":
    unittest.main()
