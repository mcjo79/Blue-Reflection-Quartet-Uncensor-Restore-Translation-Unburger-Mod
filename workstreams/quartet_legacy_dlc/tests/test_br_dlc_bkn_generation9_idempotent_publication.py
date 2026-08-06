from __future__ import annotations

import copy
import importlib.util
import unittest
from pathlib import Path

MODULE_PATH = (
    Path(__file__).resolve().parents[1]
    / "br_dlc_bkn_generation9_publish_tool.py"
)
SPEC = importlib.util.spec_from_file_location(
    "generation9_idempotent_publication_test",
    MODULE_PATH,
)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def safe_flags() -> dict:
    return {
        "commit_enabled": False,
        "transaction_function_called": False,
        "transaction_prepare_called": False,
        "transaction_commit_called": False,
        "candidate_installed": False,
        "profile_registered": False,
        "runtime_validated": False,
        "wet_variant_included": False,
        "game_modified": False,
        "save_modified": False,
        "existing_costume_replaced": False,
        "global_show_all_enabled": False,
    }


def artifacts() -> list[dict]:
    return [
        {
            "target_path": "Data/PACK10_02.PAK",
            "candidate_relative_path": ".local/build/PACK10_02.PAK",
            "candidate_size": 10,
            "candidate_sha256": "1" * 64,
        },
        {
            "target_path": "Data/PACK12.PAK",
            "candidate_relative_path": ".local/build/PACK12.PAK",
            "candidate_size": 20,
            "candidate_sha256": "2" * 64,
        },
    ]


class IdempotentPublicationTests(unittest.TestCase):
    def evidence(self) -> dict:
        return {
            "type": "br_quartet_legacy_dlc_bkn_dry_generation_evidence",
            "format_version": 1,
            "status": (
                "generation_9_pc00_pc07_append_only_labels_"
                "built_validated_not_installed"
            ),
            "tool_version": "0.0.65",
            "core_version": "9.9.9",
            "family_id": "bkn_dry",
            "generation": 9,
            "parent_generation": 8,
            "members": list(MODULE.MEMBERS),
            "candidate_report": {
                "relative_path": (
                    ".local/reports/quartet_legacy_dlc/"
                    "bkn_dry_generation9_append_only_label_candidate_evidence"
                ),
                "summary_sha256": "3" * 64,
                "manifest_sha256": "4" * 64,
            },
            "artifacts": artifacts(),
            "append_plan": {
                "string_no_start": 393339,
                "string_no_end": 393346,
            },
            "authorization": safe_flags(),
        }

    def manifest(self) -> dict:
        manifest_artifacts = [
            {
                **artifacts()[0],
                "operation": "replace",
                "baseline_size": 5,
                "baseline_sha256": "5" * 64,
                "member_delta": {
                    "added": list(MODULE.ADDED_MEMBERS),
                    "changed": [],
                    "removed": [],
                },
            },
            {
                **artifacts()[1],
                "operation": "replace",
                "baseline_size": 6,
                "baseline_sha256": "6" * 64,
                "member_delta": {
                    "added": [],
                    "changed": list(MODULE.PACK12_CHANGED_MEMBERS),
                    "removed": [],
                },
            },
        ]
        return {
            "type": "validated_quartet_legacy_dlc_payload",
            "format_version": 1,
            "family_id": "bkn_dry",
            "generation": 9,
            "members": list(MODULE.MEMBERS),
            "source_kind": "validated_quartet_legacy_dlc_handoff",
            "target_id": "blue_reflection_quartet",
            "artifacts": manifest_artifacts,
            "transaction": {
                "group": "quartet_legacy_dlc_bkn_dry",
                "all_or_none": True,
                "commit_enabled": False,
            },
            "provenance": {
                "workstream_id": "quartet_legacy_dlc",
                "workstream_version": "0.0.65",
                "evidence_relative_path": MODULE.EVIDENCE_RELATIVE.as_posix(),
                "evidence_sha256": "7" * 64,
            },
            "authorization": {
                "core_handoff_ready": True,
                "real_transaction_prepare_enabled": False,
                "real_transaction_commit_enabled": False,
                "candidate_installed": False,
                "profile_registered": False,
                "runtime_validated": False,
                "wet_variant_included": False,
                "game_modified": False,
            },
        }

    def publication(self) -> dict:
        return {
            "type": "br_quartet_legacy_dlc_bkn_dry_generation_publication",
            "format_version": 1,
            "status": "pass",
            "tool_version": "0.0.65",
            "core_version": "9.9.9",
            "family_id": "bkn_dry",
            "generation": 9,
            "parent_generation": 8,
            "members": list(MODULE.MEMBERS),
            "evidence_ready": True,
            "evidence_relative_path": MODULE.EVIDENCE_RELATIVE.as_posix(),
            "evidence_sha256": "8" * 64,
            "active_manifest_ready": True,
            "active_manifest_relative_path": MODULE.ACTIVE_RELATIVE.as_posix(),
            "active_manifest_sha256": "9" * 64,
            "parent_generation_manifest_sha256": MODULE.GENERATION8_SHA256,
            "active_write_result": "published",
            "artifact_paths": [
                "Data/PACK10_02.PAK",
                "Data/PACK12.PAK",
            ],
            "candidates": artifacts(),
            "baselines": [
                {
                    "relative_path": "Data/PACK10_02.PAK",
                    "size": 5,
                    "sha256": "5" * 64,
                    "target_path": "Data/PACK10_02.PAK",
                },
                {
                    "relative_path": "Data/PACK12.PAK",
                    "size": 6,
                    "sha256": "6" * 64,
                    "target_path": "Data/PACK12.PAK",
                },
            ],
            "core_contract_guards": {},
            **safe_flags(),
        }

    def test_stale_metadata_for_same_evidence_is_allowed(self):
        desired = self.evidence()
        existing = copy.deepcopy(desired)
        existing["tool_version"] = "0.0.63"
        existing["core_version"] = "0.0.58"
        existing["candidate_report"]["summary_sha256"] = "a" * 64
        existing["candidate_report"]["manifest_sha256"] = "b" * 64
        MODULE.validate_replaceable_generation9_evidence(
            existing,
            desired,
        )

    def test_different_candidate_is_rejected(self):
        desired = self.evidence()
        existing = copy.deepcopy(desired)
        existing["artifacts"][1]["candidate_sha256"] = "f" * 64
        with self.assertRaises(MODULE.Generation9PublishError):
            MODULE.validate_replaceable_generation9_evidence(
                existing,
                desired,
            )

    def test_stale_manifest_provenance_is_allowed(self):
        desired = self.manifest()
        existing = copy.deepcopy(desired)
        existing["provenance"]["workstream_version"] = "0.0.63"
        existing["provenance"]["evidence_sha256"] = "c" * 64
        MODULE.validate_replaceable_generation9_manifest(
            existing,
            desired,
        )

    def test_manifest_candidate_change_is_rejected(self):
        desired = self.manifest()
        existing = copy.deepcopy(desired)
        existing["artifacts"][0]["candidate_sha256"] = "d" * 64
        with self.assertRaises(MODULE.Generation9PublishError):
            MODULE.validate_replaceable_generation9_manifest(
                existing,
                desired,
            )

    def test_stale_safe_publication_is_allowed(self):
        desired = self.publication()
        existing = copy.deepcopy(desired)
        existing["tool_version"] = "0.0.63"
        existing["core_version"] = "0.0.58"
        existing["evidence_sha256"] = "e" * 64
        existing["active_manifest_sha256"] = "f" * 64
        existing["active_write_result"] = "already_identical"
        MODULE.validate_replaceable_generation9_publication(
            existing,
            desired,
        )

    def test_unsafe_publication_is_rejected(self):
        desired = self.publication()
        existing = copy.deepcopy(desired)
        existing["candidate_installed"] = True
        with self.assertRaises(MODULE.Generation9PublishError):
            MODULE.validate_replaceable_generation9_publication(
                existing,
                desired,
            )


if __name__ == "__main__":
    unittest.main()
