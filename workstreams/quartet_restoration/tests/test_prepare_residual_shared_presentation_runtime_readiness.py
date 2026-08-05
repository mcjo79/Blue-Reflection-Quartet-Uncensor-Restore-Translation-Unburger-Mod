from __future__ import annotations

import csv
import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[3]
TOOL_PATH = ROOT / "workstreams" / "quartet_restoration" / "prepare_residual_shared_presentation_runtime_readiness.py"
SPEC = importlib.util.spec_from_file_location("prepare_residual_shared_presentation_runtime_readiness", TOOL_PATH)
assert SPEC and SPEC.loader
TOOL = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = TOOL
SPEC.loader.exec_module(TOOL)


def write_tsv(path: Path, fieldnames: list[str], rows: list[dict[str, object]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def profile_specs() -> list[dict[str, object]]:
    rows = []
    for index, profile_id in enumerate(sorted(TOOL.EXPECTED_PROFILE_IDS)):
        if profile_id == TOOL.PROFILE_ID:
            rows.append({
                "schema_version": 1,
                "profile_id": profile_id,
                "target_relative_path": TOOL.TARGET_ARCHIVE,
                "baseline_sha256": TOOL.BASELINE_SHA256,
                "baseline_size": TOOL.BASELINE_SIZE,
                "profile_sha256": TOOL.PROFILE_SHA256,
                "profile_size": TOOL.PROFILE_SIZE,
                "local_profile_path": TOOL.LOCAL_PROFILE_PATH,
                "changed_member_count": 2,
                "changed_members": list(TOOL.EXPECTED_MEMBERS),
                "runtime_validated": False,
                "workstream_id": TOOL.WORKSTREAM_ID,
                "workstream_version": "0.0.50",
            })
            continue
        target = TOOL.TARGET_ARCHIVE if "shader" not in profile_id and "water_" not in profile_id else "Data/PACK10_01.PAK"
        rows.append({
            "schema_version": 1,
            "profile_id": profile_id,
            "target_relative_path": target,
            "baseline_sha256": f"{index + 1:064x}",
            "baseline_size": 1000 + index,
            "profile_sha256": f"{index + 11:064x}",
            "profile_size": 2000 + index,
            "local_profile_path": f".local/build/quartet_restoration/test/{profile_id}.pak",
            "changed_member_count": 1,
            "changed_members": [f"member/{profile_id}"],
            "runtime_validated": False,
            "workstream_id": TOOL.WORKSTREAM_ID,
            "workstream_version": "0.0.50",
        })
    return rows


def build_stage38_report(root: Path, *, runtime_validated: bool = False) -> Path:
    report_dir = root / TOOL.SOURCE_REPORT_DIR
    report_dir.mkdir(parents=True)
    summary = {
        "tool_version": "0.0.50",
        "status": "all_current_local_profiles_registered_runtime_unvalidated",
        "profile_rows": 7,
        "pack11_profile_rows": 5,
        "pack10_01_profile_rows": 2,
        "runtime_validated_profile_rows": 1 if runtime_validated else 0,
        "policy": {
            "local_paks_copied": False,
            "activation_or_rollback_scripts_generated": False,
            "core_transaction_state_modified": False,
            "core_backups_modified": False,
            "profile_paks_checksum_and_size_verified": True,
            "runtime_validation_inferred": False,
            "legacy_dlc_in_scope": False,
        },
    }
    (report_dir / "SUMMARY.json").write_text(json.dumps(summary), encoding="utf-8")
    rows = []
    for spec in profile_specs():
        rows.append({
            "profile_id": spec["profile_id"],
            "target_relative_path": spec["target_relative_path"],
            "baseline_sha256": spec["baseline_sha256"],
            "baseline_size": spec["baseline_size"],
            "profile_sha256": spec["profile_sha256"],
            "profile_size": spec["profile_size"],
            "local_profile_path": spec["local_profile_path"],
            "changed_member_count": spec["changed_member_count"],
            "manifest_relative_path": f".local/build/quartet_restoration/core_profiles/generated/{spec['profile_id']}.json",
            "runtime_validated": "true" if runtime_validated and spec["profile_id"] == TOOL.PROFILE_ID else "false",
            "workstream_version": "0.0.50",
            "validation_status": "passed",
        })
    write_tsv(report_dir / "CORE_PROFILE_MANIFESTS.tsv", list(rows[0]), rows)
    archive = root / TOOL.SOURCE_REPORT_NAME
    completed = subprocess.run(
        ["tar", "--zstd", "-cf", str(archive), "-C", str(root), TOOL.SOURCE_REPORT_DIR],
        text=True,
        capture_output=True,
    )
    if completed.returncode != 0:
        raise RuntimeError(completed.stderr)
    return archive


def build_project(root: Path) -> tuple[Path, Path, Path]:
    generated = root / ".local/build/quartet_restoration/core_profiles/generated"
    generated.mkdir(parents=True)
    specs = profile_specs()
    for item in specs:
        (generated / f"{item['profile_id']}.json").write_text(json.dumps(item), encoding="utf-8")
        path = root / str(item["local_profile_path"])
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"payload")
    report = build_stage38_report(root / "report_source")
    report_target = root / ".local/reports/quartet_restoration" / TOOL.SOURCE_REPORT_NAME
    report_target.parent.mkdir(parents=True)
    report_target.write_bytes(report.read_bytes())
    quartet_root = root / "quartet"
    installed = quartet_root / TOOL.TARGET_ARCHIVE
    installed.parent.mkdir(parents=True)
    installed.write_bytes(b"baseline")
    return report_target, quartet_root, installed


class RuntimeReadinessTests(unittest.TestCase):
    def test_validates_real_shape_of_stage38_report(self):
        with tempfile.TemporaryDirectory() as temporary:
            report = build_stage38_report(Path(temporary))
            summary, rows = TOOL.validate_stage38_report(report)
            self.assertEqual(summary["profile_rows"], 7)
            self.assertEqual(len(rows), 7)

    def test_rejects_runtime_validated_stage38_report(self):
        with tempfile.TemporaryDirectory() as temporary:
            report = build_stage38_report(Path(temporary), runtime_validated=True)
            with self.assertRaisesRegex(TOOL.ReadinessError, "runtime-validated"):
                TOOL.validate_stage38_report(report)

    def test_builds_metadata_only_readiness_with_closed_transactions(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            report, quartet_root, installed = build_project(root)
            by_path = {}
            for item in profile_specs():
                by_path[str((root / str(item["local_profile_path"])).resolve())] = (
                    str(item["profile_sha256"]), int(item["profile_size"])
                )
            by_path[str(installed.resolve())] = (TOOL.BASELINE_SHA256, TOOL.BASELINE_SIZE)

            def fake_checked(path: Path, *, label: str):
                return by_path[str(path.resolve())]

            with mock.patch.object(TOOL, "checked_regular_file", side_effect=fake_checked):
                summary, tables = TOOL.build_readiness(
                    project_root=root,
                    quartet_root=quartet_root,
                    source_report_path=report,
                )
            self.assertEqual(summary["status"], "profile_metadata_ready_activation_not_authorized_save_required")
            self.assertFalse(summary["activation_authorized"])
            self.assertEqual(len(tables["RUNTIME_TEST_MATRIX.tsv"]), 2)
            self.assertTrue(all(not row["executed_by_stage39"] for row in tables["COMMAND_PREVIEW.tsv"]))

    def test_open_shader_transaction_blocks_readiness(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            report, quartet_root, installed = build_project(root)
            state = root / TOOL.SHADER_STATE_PATH
            state.parent.mkdir(parents=True, exist_ok=True)
            state.write_text(json.dumps({"status": "active", "profile_id": "height_fog_shader_original_code"}), encoding="utf-8")
            by_path = {}
            for item in profile_specs():
                by_path[str((root / str(item["local_profile_path"])).resolve())] = (
                    str(item["profile_sha256"]), int(item["profile_size"])
                )
            by_path[str(installed.resolve())] = (TOOL.BASELINE_SHA256, TOOL.BASELINE_SIZE)

            def fake_checked(path: Path, *, label: str):
                return by_path[str(path.resolve())]

            with mock.patch.object(TOOL, "checked_regular_file", side_effect=fake_checked):
                with self.assertRaisesRegex(TOOL.ReadinessError, "transaction is already open"):
                    TOOL.build_readiness(project_root=root, quartet_root=quartet_root, source_report_path=report)

    def test_report_contains_only_metadata_and_no_activation(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            summary = {
                "tool_version": "0.0.45",
                "status": "profile_metadata_ready_activation_not_authorized_save_required",
                "policy": {"installed_game_modified": False, "activation_invoked": False},
            }
            tables = {
                "CORE_PROFILE_REGISTRY_RECHECK.tsv": [{
                    "profile_id": "x", "target_relative_path": "Data/PACK11.PAK", "local_profile_path": "x",
                    "profile_sha256": "0" * 64, "profile_size": 1, "runtime_validated": False,
                    "manifest_status": "passed", "local_payload_status": "passed", "active": False,
                    "baseline_status": "match",
                }],
                "TARGET_PROFILE_RUNTIME_READINESS.tsv": [{
                    "profile_id": "x", "target_relative_path": "Data/PACK11.PAK", "baseline_sha256": "0" * 64,
                    "baseline_size": 1, "profile_sha256": "1" * 64, "profile_size": 1, "changed_member_count": 1,
                    "registry_manifest_valid": True, "local_profile_checksum_valid": True,
                    "installed_baseline_match": True, "event_transaction_closed": True,
                    "shader_transaction_closed": True, "runtime_validated": False,
                    "explicit_user_authorization_present": False, "scene_save_or_reachable_state_confirmed": False,
                    "activation_performed": False, "readiness_status": "metadata_only",
                }],
                "TRANSACTION_STATE_CHECKS.tsv": [{
                    "kind": "event", "state_relative_path": "x", "state_present": False, "state_status": "absent",
                    "open_transaction": False, "profile_id": "", "target_relative_path": "",
                    "runtime_validated": False, "check_status": "passed_no_state",
                }],
                "RUNTIME_TEST_MATRIX.tsv": [{
                    "test_order": 1, "profile_id": "x", "event_member": "x", "event_id": "x",
                    "cue_domains": "x", "test_goal": "x", "isolation_requirement": "x",
                    "save_requirement": "x", "result_required": "x",
                }],
                "ROLLBACK_INVARIANTS.tsv": [{
                    "invariant": "x", "expected_value": "x", "verified_now": True, "required_after_test": True,
                }],
                "COMMAND_PREVIEW.tsv": [{
                    "step": 1, "purpose": "x", "command": "x", "executed_by_stage39": False,
                    "requires_explicit_user_authorization": True,
                }],
            }
            report = TOOL.write_report(project_root=root, summary=summary, tables=tables, create_archive=True)
            self.assertIsNotNone(report)
            listed = subprocess.run(["tar", "--zstd", "-tf", str(report)], text=True, capture_output=True, check=True).stdout
            self.assertNotIn(".PAK", listed)
            self.assertNotIn(".ebd", listed.lower())
            self.assertIn("COMMAND_PREVIEW.tsv", listed)


if __name__ == "__main__":
    unittest.main()
