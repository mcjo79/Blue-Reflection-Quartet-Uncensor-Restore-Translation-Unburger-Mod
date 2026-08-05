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
TOOL_PATH = (
    ROOT / "workstreams" / "quartet_restoration"
    / "register_fe13_complete_residual_core_profile.py"
)
SPEC = importlib.util.spec_from_file_location(
    "register_fe13_complete_residual_core_profile", TOOL_PATH
)
assert SPEC and SPEC.loader
TOOL = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = TOOL
SPEC.loader.exec_module(TOOL)


def write_tsv(path: Path, fields: list[str], rows: list[dict[str, object]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def build_report(root: Path, *, supersedes: str = TOOL.SUPERSEDES_PROFILE_ID) -> Path:
    report_root = root / TOOL.REPORT_DIR
    report_root.mkdir(parents=True)
    summary = {
        "type": "br_quartet_restoration_fe13_complete_residual_repack_test_evidence_summary",
        "format_version": 1,
        "tool_version": "0.0.70",
        "source_fe13_complete_residual_prototype_tool_version": "0.0.69",
        "repack_engine_tool_version": "0.0.38",
        "status": "one_checksum_gated_local_fe13_complete_residual_pack11_profile_built_reextracted_and_validated_not_installed",
        "profile_rows": 1,
        "file_rows": 1,
        "validation_rows": 17,
        "validation_failures": 0,
        "manifest_difference_rows": 9397,
        "stable_manifest_difference_rows": 0,
        "derived_manifest_difference_rows": 9397,
        "skipped_rows": 0,
        "input_archive_relative_path": TOOL.TARGET_ARCHIVE,
        "input_archive_sha256": TOOL.BASELINE_SHA256,
        "input_archive_size": TOOL.BASELINE_SIZE,
        "inventory_pristine_archive_sha256": TOOL.BASELINE_SHA256,
        "inventory_pristine_archive_match": True,
        "local_profile_archive": TOOL.LOCAL_PROFILE_PATH,
        "policy": {
            "installed_game_read_only": True,
            "installed_game_modified": False,
            "current_pack11_used_as_repack_base": True,
            "candidate_members_replaced": 1,
            "all_unchanged_members_verified_by_reextraction_hash": True,
            "unrelated_translation_and_other_mod_members_preserved": True,
            "existing_pack11_profiles_left_untouched": True,
            "local_rollback_baseline_copied": True,
            "core_profile_manifest_generated": False,
            "activation_or_installer_generated": False,
            "runtime_validation_inferred": False,
            "censorship_semantics_inferred": False,
            "proprietary_pak_exported_in_report": False,
            "legacy_dlc_in_scope": False,
            "translation_or_core_files_modified": False,
        },
    }
    (report_root / "SUMMARY.json").write_text(
        json.dumps(summary, indent=2) + "\n", encoding="utf-8"
    )
    write_tsv(
        report_root / "FE13_COMPLETE_RESIDUAL_REPACK_TEST_BUILD_SKIPPED.tsv",
        ["profile_id", "reason"],
        [],
    )
    write_tsv(
        report_root / "FE13_COMPLETE_RESIDUAL_REPACK_TEST_PROFILES.tsv",
        [
            "profile_id", "profile_classification", "prototype_confidence",
            "source_stage60_profile_id", "supersedes_profile_id",
            "input_archive_relative_path", "input_archive_sha256", "input_archive_size",
            "inventory_pristine_archive_match", "output_archive_sha256",
            "output_archive_size", "replaced_member_count",
            "unchanged_member_count_verified", "local_output_archive",
            "validation_status", "activation_status",
        ],
        [{
            "profile_id": TOOL.PROFILE_ID,
            "profile_classification": "experimental_single_scene_complete_residual_inverse_candidate",
            "prototype_confidence": "experimental_metadata_gated",
            "source_stage60_profile_id": TOOL.PROFILE_ID,
            "supersedes_profile_id": supersedes,
            "input_archive_relative_path": TOOL.TARGET_ARCHIVE,
            "input_archive_sha256": TOOL.BASELINE_SHA256,
            "input_archive_size": TOOL.BASELINE_SIZE,
            "inventory_pristine_archive_match": True,
            "output_archive_sha256": TOOL.PROFILE_SHA256,
            "output_archive_size": TOOL.PROFILE_SIZE,
            "replaced_member_count": 1,
            "unchanged_member_count_verified": 9396,
            "local_output_archive": TOOL.LOCAL_PROFILE_PATH,
            "validation_status": "passed",
            "activation_status": "not_generated_generic_core_manifest_required",
        }],
    )
    member, digest = next(iter(TOOL.EXPECTED_MEMBERS.items()))
    write_tsv(
        report_root / "FE13_COMPLETE_RESIDUAL_REPACK_TEST_FILES.tsv",
        [
            "profile_id", "target_archive", "target_member_path",
            "candidate_sha256", "repacked_member_sha256", "validation_status",
        ],
        [{
            "profile_id": TOOL.PROFILE_ID,
            "target_archive": TOOL.TARGET_ARCHIVE,
            "target_member_path": member,
            "candidate_sha256": digest,
            "repacked_member_sha256": digest,
            "validation_status": "passed",
        }],
    )
    write_tsv(
        report_root / "FE13_COMPLETE_RESIDUAL_REPACK_TEST_VALIDATION.tsv",
        ["profile_id", "check_name", "passed", "details"],
        [{
            "profile_id": TOOL.PROFILE_ID,
            "check_name": f"check_{index:02d}",
            "passed": True,
            "details": "",
        } for index in range(17)],
    )
    differences = [
        {"classification": "derived_unchanged_member_metadata", "gate_effect": "diagnostic_only"}
        for _ in range(9396)
    ]
    differences.append({
        "classification": "derived_modified_member_metadata",
        "gate_effect": "diagnostic_only",
    })
    write_tsv(
        report_root / "FE13_COMPLETE_RESIDUAL_REPACK_TEST_MANIFEST_DIFFERENCES.tsv",
        ["classification", "gate_effect"],
        differences,
    )
    archive = root / TOOL.REPORT_NAME
    completed = subprocess.run(
        ["tar", "--zstd", "-cf", str(archive), "-C", str(root), TOOL.REPORT_DIR],
        text=True,
        capture_output=True,
    )
    if completed.returncode != 0:
        raise RuntimeError(completed.stderr)
    return archive


class Fe13CompleteResidualRegistrationTests(unittest.TestCase):
    def test_validates_clean_stage61_report(self):
        with tempfile.TemporaryDirectory() as temporary:
            summary = TOOL.validate_stage61_report(build_report(Path(temporary)))
            self.assertEqual(summary["validation_rows"], 17)
            self.assertEqual(summary["stable_manifest_difference_rows"], 0)

    def test_rejects_wrong_supersession_relation(self):
        with tempfile.TemporaryDirectory() as temporary:
            with self.assertRaisesRegex(TOOL.RegistrationError, "supersedes_profile_id"):
                TOOL.validate_stage61_report(
                    build_report(Path(temporary), supersedes="wrong_profile")
                )

    def test_generator_replacement_preserves_later_field_profile(self):
        specs = [
            SimpleNamespace(profile_id=f"p{index}", target_relative_path="Data/PACK11.PAK")
            for index in range(11)
        ]
        specs.append(SimpleNamespace(
            profile_id=TOOL.PROFILE_ID, target_relative_path="Data/PACK11.PAK"
        ))
        specs.extend([
            SimpleNamespace(profile_id="shader_a", target_relative_path="Data/PACK10_01.PAK"),
            SimpleNamespace(profile_id="shader_b", target_relative_path="Data/PACK10_01.PAK"),
        ])
        TOOL.validate_generator_replacement(SimpleNamespace(CURRENT_PROFILE_SPECS=specs))
        specs.append(SimpleNamespace(
            profile_id="field_profile",
            target_relative_path="Data/PACK10_03.PAK",
        ))
        TOOL.validate_generator_replacement(SimpleNamespace(CURRENT_PROFILE_SPECS=specs))
        specs.append(SimpleNamespace(
            profile_id=TOOL.SUPERSEDES_PROFILE_ID,
            target_relative_path="Data/PACK11.PAK",
        ))
        with self.assertRaisesRegex(TOOL.RegistrationError, "superseded"):
            TOOL.validate_generator_replacement(SimpleNamespace(CURRENT_PROFILE_SPECS=specs))

    def test_registration_preserves_fifteenth_field_profile_and_removes_old_profile(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            report = build_report(root)
            specs = [
                SimpleNamespace(profile_id=f"p{index}", target_relative_path="Data/PACK11.PAK")
                for index in range(11)
            ]
            specs.append(SimpleNamespace(
                profile_id=TOOL.PROFILE_ID, target_relative_path="Data/PACK11.PAK"
            ))
            specs.extend([
                SimpleNamespace(profile_id="shader_a", target_relative_path="Data/PACK10_01.PAK"),
                SimpleNamespace(profile_id="shader_b", target_relative_path="Data/PACK10_01.PAK"),
            ])
            specs.append(SimpleNamespace(
                profile_id="field_profile", target_relative_path="Data/PACK10_03.PAK"
            ))
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
                "changed_members": list(TOOL.EXPECTED_MEMBERS),
            })
            fake = SimpleNamespace(
                CURRENT_PROFILE_SPECS=specs,
                generate_manifests=lambda **kwargs: (root / "generated", None, manifests),
            )
            with mock.patch.object(TOOL, "load_generator", return_value=fake):
                _, _, result = TOOL.register_profile(
                    root, report, create_report_archive=False
                )
            self.assertEqual(len(result), 15)
            self.assertNotIn(
                TOOL.SUPERSEDES_PROFILE_ID,
                {item["profile_id"] for item in result},
            )

    def test_generic_generator_contains_only_replacement_fe13_profile(self):
        path = (
            ROOT / "workstreams" / "quartet_restoration"
            / "generate_core_profile_manifests.py"
        )
        spec = importlib.util.spec_from_file_location("generator_stage62_test", path)
        assert spec and spec.loader
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        matches = [item for item in module.CURRENT_PROFILE_SPECS if item.profile_id == TOOL.PROFILE_ID]
        ids = {item.profile_id for item in module.CURRENT_PROFILE_SPECS}
        self.assertEqual(len(module.CURRENT_PROFILE_SPECS), 15)
        self.assertEqual(len(matches), 1)
        self.assertNotIn(TOOL.SUPERSEDES_PROFILE_ID, ids)
        self.assertEqual(matches[0].profile_sha256, TOOL.PROFILE_SHA256)
        self.assertEqual(matches[0].profile_size, TOOL.PROFILE_SIZE)
        self.assertEqual(matches[0].local_profile_path, TOOL.LOCAL_PROFILE_PATH)
        self.assertEqual(matches[0].changed_members, tuple(TOOL.EXPECTED_MEMBERS))


if __name__ == "__main__":
    unittest.main()
