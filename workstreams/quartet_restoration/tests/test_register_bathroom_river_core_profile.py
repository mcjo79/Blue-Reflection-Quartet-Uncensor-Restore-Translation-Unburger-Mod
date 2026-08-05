from __future__ import annotations

import csv
import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

ROOT = Path(__file__).resolve().parents[3]
TOOL_PATH = ROOT / "workstreams/quartet_restoration/register_bathroom_river_core_profile.py"
SPEC = importlib.util.spec_from_file_location("register_bathroom_river_core_profile", TOOL_PATH)
assert SPEC and SPEC.loader
TOOL = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = TOOL
SPEC.loader.exec_module(TOOL)


def write_tsv(path: Path, fields: list[str], rows: list[dict[str, object]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def build_stage72_report(root: Path) -> Path:
    report_root = root / TOOL.STAGE72_ROOT
    report_root.mkdir(parents=True)
    summary = {
        "type": "br_quartet_restoration_core_target_interface_request",
        "format_version": 1,
        "tool_version": "0.0.82",
        "status": "core_target_extension_required_before_profile_registration",
        "requested_target_relative_path": TOOL.TARGET_ARCHIVE,
        "requested_target_kind": "field",
        "requested_state_path": ".local/state/core_unified_patcher/quartet_field_profile.json",
        "requested_report_latest": ".local/reports/core/BR_QUARTET_FIELD_PROFILE_TRANSACTION_REPORT.json",
        "requested_report_dir": ".local/reports/core/quartet_field_profiles",
        "requested_commands": [
            "quartet-field-profile-activate",
            "quartet-field-profile-status",
            "quartet-field-profile-rollback",
        ],
        "required_transaction_change": "generalize scalar OtherState to all other target states or an equivalent grouped mutual-exclusion check before activation",
        "profile_to_register_after_core_update": {
            "profile_id": TOOL.PROFILE_ID,
            "target_relative_path": TOOL.TARGET_ARCHIVE,
            "baseline_sha256": TOOL.BASELINE_SHA256,
            "baseline_size": TOOL.BASELINE_SIZE,
            "profile_sha256": TOOL.PROFILE_SHA256,
            "profile_size": TOOL.PROFILE_SIZE,
            "local_profile_path": TOOL.LOCAL_PROFILE_PATH,
            "changed_members": [TOOL.TARGET_MEMBER],
            "runtime_validated": False,
        },
        "current_core_support": {
            "target_registered": False,
            "activation_commands_present": False,
            "wrapper_support_present": False,
            "fully_supported": False,
            "current_target_count": 2,
            "current_other_state_is_scalar": True,
        },
        "restoration_registry_state": {
            "current_profiles": 14,
            "pending_profiles": 1,
            "expected_profiles_after_registration": 15,
            "pack11_profiles_after_registration": 12,
            "pack10_01_profiles_after_registration": 2,
            "pack10_03_profiles_after_registration": 1,
        },
        "policy": {
            "restoration_only_update": True,
            "core_sources_modified": False,
            "registry_modified": False,
            "profile_activated": False,
            "installed_game_modified": False,
            "runtime_validation_inferred": False,
            "opaque_binary_semantics_inferred": False,
            "canary_track_modified": False,
        },
        "next_action": "core update then stage 73",
        "source_stage71_report_sha256": "0" * 64,
        "source_stage71_output_archive_sha256": TOOL.PROFILE_SHA256,
    }
    for name in ("SUMMARY.json", "CORE_INTERFACE_REQUEST.json"):
        (report_root / name).write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    (report_root / "CORE_INTERFACE_REQUEST.md").write_text("request\n", encoding="utf-8")
    write_tsv(
        report_root / "PENDING_PROFILE.tsv",
        [
            "profile_id", "target_relative_path", "baseline_sha256", "baseline_size",
            "profile_sha256", "profile_size", "local_profile_path", "changed_member",
            "runtime_validated",
        ],
        [{
            "profile_id": TOOL.PROFILE_ID,
            "target_relative_path": TOOL.TARGET_ARCHIVE,
            "baseline_sha256": TOOL.BASELINE_SHA256,
            "baseline_size": TOOL.BASELINE_SIZE,
            "profile_sha256": TOOL.PROFILE_SHA256,
            "profile_size": TOOL.PROFILE_SIZE,
            "local_profile_path": TOOL.LOCAL_PROFILE_PATH,
            "changed_member": TOOL.TARGET_MEMBER,
            "runtime_validated": False,
        }],
    )
    write_tsv(
        report_root / "VALIDATIONS.tsv",
        ["check_name", "passed", "gate_effect", "details"],
        [
            {"check_name": "stage71_report_canonical", "passed": True, "gate_effect": "passed", "details": ""},
            {"check_name": "stage71_profile_local_only", "passed": True, "gate_effect": "passed", "details": ""},
            {"check_name": "pack10_03_target_support_complete", "passed": False, "gate_effect": "dependency_status", "details": ""},
            {"check_name": "core_partial_support_absent", "passed": True, "gate_effect": "passed", "details": ""},
            {"check_name": "restoration_registry_left_unchanged", "passed": True, "gate_effect": "passed", "details": ""},
        ],
    )
    archive = root / TOOL.STAGE72_REPORT
    completed = subprocess.run(
        ["tar", "--zstd", "-cf", str(archive), "-C", str(root), TOOL.STAGE72_ROOT],
        text=True,
        capture_output=True,
    )
    if completed.returncode != 0:
        raise RuntimeError(completed.stderr)
    return archive


def generator_specs() -> list[SimpleNamespace]:
    specs = [
        SimpleNamespace(profile_id=f"event_{index}", target_relative_path="Data/PACK11.PAK")
        for index in range(11)
    ]
    specs.append(SimpleNamespace(
        profile_id="candidate_fe13_090_complete_residual_inverse_9a57d11730c0",
        target_relative_path="Data/PACK11.PAK",
    ))
    specs.extend([
        SimpleNamespace(profile_id="height", target_relative_path="Data/PACK10_01.PAK"),
        SimpleNamespace(profile_id="water", target_relative_path="Data/PACK10_01.PAK"),
    ])
    specs.append(SimpleNamespace(
        profile_id=TOOL.PROFILE_ID,
        target_relative_path=TOOL.TARGET_ARCHIVE,
        baseline_sha256=TOOL.BASELINE_SHA256,
        baseline_size=TOOL.BASELINE_SIZE,
        profile_sha256=TOOL.PROFILE_SHA256,
        profile_size=TOOL.PROFILE_SIZE,
        local_profile_path=TOOL.LOCAL_PROFILE_PATH,
        changed_members=(TOOL.TARGET_MEMBER,),
    ))
    return specs


class BathroomRiverCoreProfileRegistrationTests(unittest.TestCase):
    def test_validates_stage72_request_report(self):
        with tempfile.TemporaryDirectory() as temporary:
            summary = TOOL.validate_stage72_report(build_stage72_report(Path(temporary)))
            self.assertEqual(summary["restoration_registry_state"]["expected_profiles_after_registration"], 15)

    def test_actual_core_extension_is_complete(self):
        request_path = ROOT / "workstreams/quartet_restoration/prepare_bathroom_river_core_target_request.py"
        spec = importlib.util.spec_from_file_location("stage72_actual_core_test", request_path)
        assert spec and spec.loader
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        support = module.inspect_core_support(ROOT)
        self.assertTrue(support["fully_supported"])
        self.assertEqual(support["current_target_count"], 3)
        self.assertFalse(support["current_other_state_is_scalar"])

    def test_generator_requires_exact_fifteen_and_one_field_profile(self):
        specs = generator_specs()
        TOOL.validate_generator_extension(SimpleNamespace(CURRENT_PROFILE_SPECS=specs))
        specs.append(SimpleNamespace(
            profile_id="duplicate_field",
            target_relative_path=TOOL.TARGET_ARCHIVE,
        ))
        with self.assertRaisesRegex(TOOL.RegistrationError, "exactly fifteen"):
            TOOL.validate_generator_extension(SimpleNamespace(CURRENT_PROFILE_SPECS=specs))

    def test_registration_generates_fifteen_runtime_unvalidated_profiles(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            reports = root / ".local/reports/quartet_restoration"
            reports.mkdir(parents=True)
            (reports / TOOL.STAGE71_REPORT).write_bytes(b"stage71")
            build_stage72_report(root).replace(reports / TOOL.STAGE72_REPORT)
            specs = generator_specs()
            manifests = [
                {
                    "profile_id": item.profile_id,
                    "target_relative_path": item.target_relative_path,
                    "runtime_validated": False,
                }
                for item in specs
            ]
            selected = next(item for item in manifests if item["profile_id"] == TOOL.PROFILE_ID)
            selected.update({
                "baseline_sha256": TOOL.BASELINE_SHA256,
                "baseline_size": TOOL.BASELINE_SIZE,
                "profile_sha256": TOOL.PROFILE_SHA256,
                "profile_size": TOOL.PROFILE_SIZE,
                "local_profile_path": TOOL.LOCAL_PROFILE_PATH,
                "changed_members": [TOOL.TARGET_MEMBER],
            })
            request_module = SimpleNamespace(
                validate_stage71_report=lambda path: {"status": "ok"},
            )
            generator = SimpleNamespace(
                CURRENT_PROFILE_SPECS=specs,
                generate_manifests=lambda **kwargs: (root / "generated", None, manifests),
            )
            with mock.patch.object(TOOL, "load_module", side_effect=[request_module, generator]), \
                 mock.patch.object(TOOL, "validate_stage72_report", return_value={}), \
                 mock.patch.object(TOOL, "validate_core_extension", return_value={"fully_supported": True}):
                _, _, result, _ = TOOL.register_profile(root, create_report_archive=False)
            self.assertEqual(len(result), 15)
            self.assertEqual(sum(item["target_relative_path"] == TOOL.TARGET_ARCHIVE for item in result), 1)
            self.assertTrue(all(item["runtime_validated"] is False for item in result))


if __name__ == "__main__":
    unittest.main()
