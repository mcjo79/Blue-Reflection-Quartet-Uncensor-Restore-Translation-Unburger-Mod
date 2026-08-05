import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

MODULE_PATH = Path(__file__).resolve().parents[1] / "br_dlc_bkn_dry_shadow_core_rehearsal_tool.py"
spec = importlib.util.spec_from_file_location("shadow_tool", MODULE_PATH)
mod = importlib.util.module_from_spec(spec)
assert spec.loader
spec.loader.exec_module(mod)


def artifact(path, order):
    return {
        "artifact_order": order,
        "relative_path": path,
        "candidate_relative_path": f".local/build/{Path(path).name}",
        "baseline_size": 10 + order,
        "baseline_sha256": ("a" if order == 1 else "b") * 64,
        "candidate_size": 20 + order,
        "candidate_sha256": ("c" if order == 1 else "d") * 64,
        "independent_preview_ready_allowed": False,
        "transaction_prepare_allowed": False,
    }


def request():
    return {
        "type": "br_quartet_legacy_dlc_core_payload_preview_patch_request",
        "request_version": "0.0.31",
        "authorization": {
            "patch_request_ready": True,
            "core_modified": False,
            "core_patch_applied": False,
            "game_modified": False,
            "git_modified": False,
            "profile_build_allowed": False,
            "profile_registered": False,
            "real_transaction_commit_enabled": False,
            "real_transaction_prepare_enabled": False,
            "runtime_validated": False,
            "wet_variant_included": False,
            "candidate_installed": False,
        },
        "artifact_contract": [artifact("Data/PACK10_02.PAK", 1), artifact("Data/PACK12.PAK", 2)],
    }


class ShadowCoreToolTest(unittest.TestCase):
    def test_accepts_exact_two_artifact_contract(self):
        rows = mod.validate_patch_request(request())
        self.assertEqual([row["relative_path"] for row in rows], list(mod.EXPECTED_TARGETS))

    def test_rejects_single_artifact_contract(self):
        value = request(); value["artifact_contract"] = value["artifact_contract"][:1]
        with self.assertRaises(mod.ShadowCoreRehearsalError):
            mod.validate_patch_request(value)

    def test_rejects_prepare_authorization(self):
        value = request(); value["authorization"]["real_transaction_prepare_enabled"] = True
        with self.assertRaises(mod.ShadowCoreRehearsalError):
            mod.validate_patch_request(value)

    def test_catalog_patch_replaces_only_exact_row(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "catalog.json"
            doc = {"type": "br_local_payload_catalog", "format_version": 1, "module_targets": [
                {"module_id": "other", "target_id": "x", "source_kind": "x", "connection_status": "pending", "artifacts": []},
                {"module_id": "quartet_legacy_dlc", "target_id": "blue_reflection_quartet", "source_kind": "old", "connection_status": "pending_adapter", "artifacts": []},
            ]}
            path.write_text(json.dumps(doc), encoding="utf-8")
            candidate = {"module_id": "quartet_legacy_dlc", "target_id": "blue_reflection_quartet", "source_kind": "validated_quartet_legacy_dlc_handoff", "connection_status": "connected_preview_only", "artifacts": [{"relative_path": "Data/PACK10_02.PAK"}, {"relative_path": "Data/PACK12.PAK"}]}
            before = mod.patch_catalog(path, candidate)
            after = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(before["source_kind"], "old")
            self.assertEqual(after["module_targets"][0]["module_id"], "other")
            self.assertEqual(after["module_targets"][1], candidate)

    def test_generated_go_sources_contain_fail_closed_contract(self):
        source = mod.prototype_go_source()
        tests = mod.prototype_go_test_source()
        self.assertIn("expected exactly two artifacts", source)
        self.assertIn("candidate is not a regular non-symlink file", source)
        self.assertIn("all-or-none gate failed", tests)
        self.assertNotIn("transaction.Prepare", source)
        self.assertNotIn("transaction.Commit", source)


if __name__ == "__main__":
    unittest.main()
