#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path

MODULE_PATH = Path(__file__).resolve().parents[1] / "audit_reflector_slot_light_swordflash_unresolved_freeze.py"
spec = importlib.util.spec_from_file_location("swordflash_freeze", MODULE_PATH)
assert spec and spec.loader
S = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = S
spec.loader.exec_module(S)


class SwordflashFreezeAuditTests(unittest.TestCase):
    def test_parent_scope_is_container_selection_only(self) -> None:
        rows = [
            {"normalized_path": S.PC00_CONTAINER, "member_key": key, "candidate_id": "pc00"}
            for key in sorted(S.PC00_PARENT_SCOPE_MEMBERS)
        ]
        selected = S.validate_parent_scope_rows(rows)
        self.assertEqual(len(selected), 3)
        bad = rows[:-1]
        with self.assertRaisesRegex(S.FreezeAuditError, "parent scope member set drift"):
            S.validate_parent_scope_rows(bad)

    def test_cross_stem_g1em_requires_zero_existing_template_occurrences(self) -> None:
        rows = [
            {
                "normalized_path": S.PC00_CONTAINER,
                "member_key": S.PC00_CROSS_STEM_G1EM,
                "side": side,
                "raw_aligned_body_hits": "0",
                "format_valid_occurrence_rows": "0",
            }
            for side in ("source", "target")
        ]
        self.assertEqual(len(S.validate_cross_stem_g1em_rows(rows)), 2)
        rows[0]["format_valid_occurrence_rows"] = "1"
        with self.assertRaisesRegex(S.FreezeAuditError, "occurrence drift"):
            S.validate_cross_stem_g1em_rows(rows)

    def test_swordflash_family_cannot_support_itself(self) -> None:
        inventory = [
            {"family_id": S.SWORDFLASH_FAMILY, "member_key": key}
            for key in S.SWORDFLASH_MEMBERS
        ]
        selected = S.validate_swordflash_family(inventory, [], [])
        self.assertEqual(len(selected), 2)
        consensus = [{"family_id": S.SWORDFLASH_FAMILY}]
        with self.assertRaisesRegex(S.FreezeAuditError, "self-supporting"):
            S.validate_swordflash_family(inventory, consensus, [])

    def test_freeze_decision_preserves_unique_table_eligible_model_as_unselected(self) -> None:
        rows = [
            {
                "pair_id": f"pair-{index}",
                "normalized_path": S.PC00_CONTAINER,
                "member_key": key,
                "member_name": key.split("#", 1)[0],
                "candidate_model_rows": "2",
                "eligible_section_table_model_rows": "1",
                "selected_model_id": "",
                "classification": "occurrence_identity_unresolved_section_table_rule_not_authoritatively_calibrated",
            }
            for index, key in enumerate(S.SWORDFLASH_MEMBERS)
        ]
        frozen = S.validate_freeze_decisions(rows)
        self.assertEqual(len(frozen), 2)
        self.assertTrue(all(row["selected_model_id"] == "" for row in frozen))
        rows[0]["selected_model_id"] = "ordinal-2"
        with self.assertRaisesRegex(S.FreezeAuditError, "improperly selected"):
            S.validate_freeze_decisions(rows)

    def test_channel_rows_are_all_non_authorizing(self) -> None:
        stage81 = {"container_exact_reference_rows": 0}
        stage116 = {"still_unresolved_noncanary_pair_rows": 2}
        stage117 = {"same_stem_g1em_companion_rows": 0, "g1em_occurrence_binding_candidate_rows": 0}
        stage118 = {"section_table_rule_authoritatively_calibrated": False, "calibration_reference_pass_rows": 0}
        cross_stem = [{}, {}]
        parent_scope = [{}, {}, {}]
        channels = S.build_channel_rows(stage81, stage116, stage117, stage118, [], cross_stem, parent_scope)
        self.assertEqual(len(channels), 6)
        self.assertFalse(any(S.parse_bool(row["authorizing"]) for row in channels))

    def test_reviewed_stage118_archive_hash_is_immutable(self) -> None:
        project_root = Path(__file__).resolve().parents[3]
        archive = project_root / ".local/reports/quartet_restoration" / S.STAGE118_ARCHIVE
        self.assertEqual(S.sha256_file(archive), S.STAGE118_SHA256)

    def test_real_completed_tree_builds_freeze_report_without_payload_rehydration(self) -> None:
        project_root = Path(__file__).resolve().parents[3]
        source_reports = project_root / ".local/reports/quartet_restoration"
        with tempfile.TemporaryDirectory(prefix="swordflash-freeze-test-") as tmp_name:
            output, archive, summary = S.build_report(
                project_root,
                source_report_root=source_reports,
                output_report_root=Path(tmp_name),
                create_archive=False,
            )
            self.assertIsNone(archive)
            self.assertTrue((output / "SUMMARY.json").is_file())
            self.assertEqual(summary["authorizing_binding_channel_rows"], 0)
            self.assertEqual(summary["frozen_unresolved_swordflash_pair_rows"], 2)
            self.assertFalse(summary["numbered_stage_created"])
            self.assertFalse(summary["policy"]["proprietary_payload_rehydrated"])


if __name__ == "__main__":
    unittest.main()
