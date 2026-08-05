from __future__ import annotations

import csv
import hashlib
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

MODULE_PATH = Path(__file__).resolve().parents[1] / "collect_bathroom_scene_descriptor_word_evidence.py"
SPEC = importlib.util.spec_from_file_location("collect_bathroom_scene_descriptor_word_evidence", MODULE_PATH)
assert SPEC and SPEC.loader
TOOL = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(TOOL)


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def write_tsv(path: Path, fields: list[str], rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fields})


class BathroomDescriptorWordEvidenceTests(unittest.TestCase):
    def build_fixture(self, root: Path):
        project = root / "project"
        reports = project / ".local/reports/quartet_restoration"
        workspace = project / ".local/build/quartet_restoration"
        workspace.mkdir(parents=True)

        stage65 = reports / "expanded_scene_effect_member_evidence"
        write_json(stage65 / "SUMMARY.json", {
            "type": "br_quartet_restoration_expanded_scene_effect_member_evidence_summary",
            "tool_version": "0.0.75",
            "status": "expanded_scene_effect_member_inverse_range_audit_complete_no_payload_written_runtime_deferred",
            "registry_profile_rows": 14,
            "stage63_remaining_ebd_candidate_rows": 0,
            "stage64_historical_prefilter_selected_rows": 0,
            "expanded_focused_binary_delta_rows_selected": 185,
            "rehydrated_member_rows": 185,
            "analyzed_member_rows": 185,
            "promotable_exact_original_member_rows": 0,
            "partial_inverse_evidence_member_rows": 13,
            "skipped_rows": 0,
            "policy": {
                "installed_games_modified": False,
                "candidate_effect_payloads_written": False,
                "parent_archive_repack_performed": False,
                "core_registry_modified": False,
                "activation_or_rollback_invoked": False,
                "runtime_validation_inferred": False,
                "censorship_classification_inferred": False,
            },
        })
        member_fields = [
            "candidate_id", "rule_id", "domain", "priority", "normalized_path", "member_key",
            "source_member_name", "target_member_name", "extension", "target_distance_to_source",
            "operation_count", "eligible_operation_count", "excluded_operation_count",
            "best_candidate_distance_to_source", "best_distance_improvement", "classification",
        ]
        base = {
            "candidate_id": "effectcand_bathroom",
            "rule_id": "bathroom_scene",
            "domain": "steam_and_water_visibility",
            "priority": "critical",
            "normalized_path": TOOL.EXPECTED_PARENT_PATH,
        }
        stage65_rows = [
            {
                **base,
                "member_key": "s89_s_hinako_bath_room_01.opl2#0",
                "source_member_name": "S89_S_HINAKO_BATH_ROOM_01.opl2",
                "target_member_name": "S89_S_HINAKO_BATH_ROOM_01.opl2",
                "extension": ".opl2",
                "target_distance_to_source": 146,
                "operation_count": 54,
                "eligible_operation_count": 4,
                "excluded_operation_count": 50,
                "best_candidate_distance_to_source": 130,
                "best_distance_improvement": 16,
                "classification": "expanded_scene_effect_partial_inverse_evidence_only",
            },
            {
                **base,
                "member_key": "s89_s_hinako_bath_room_01_river.bin#0",
                "source_member_name": "S89_S_HINAKO_BATH_ROOM_01_river.bin",
                "target_member_name": "S89_S_HINAKO_BATH_ROOM_01_river.bin",
                "extension": ".bin",
                "target_distance_to_source": 22,
                "operation_count": 5,
                "eligible_operation_count": 0,
                "excluded_operation_count": 5,
                "best_candidate_distance_to_source": "",
                "best_distance_improvement": "",
                "classification": "expanded_scene_effect_member_not_promotable_by_conservative_inverse_ranges",
            },
        ]
        write_tsv(stage65 / "EXPANDED_SCENE_EFFECT_MEMBERS.tsv", member_fields, stage65_rows)

        source_opl2 = bytes((index % 251 for index in range(256)))
        target_opl2 = bytearray(source_opl2)
        for index in range(20, 166):
            target_opl2[index] ^= 0x5A
        target_opl2 = bytes(target_opl2)
        self.assertEqual(TOOL.hamming_distance(source_opl2, target_opl2), 146)

        source_river = bytes((index * 3 % 251 for index in range(128)))
        target_river = bytearray(source_river)
        for index in range(24, 46):
            target_river[index] ^= 0x33
        target_river = bytes(target_river)
        self.assertEqual(TOOL.hamming_distance(source_river, target_river), 22)

        pairs = []
        shader_rows = []
        for row, source, target in (
            (stage65_rows[0], source_opl2, target_opl2),
            (stage65_rows[1], source_river, target_river),
        ):
            pairs.append({
                **row,
                "source_payload": source,
                "target_payload": target,
            })
            for side, payload in (("source", source), ("target", target)):
                shader_rows.append({
                    "candidate_id": row["candidate_id"],
                    "normalized_path": row["normalized_path"],
                    "member_key": row["member_key"],
                    "side": side,
                    "payload_size": len(payload),
                    "payload_sha256": hashlib.sha256(payload).hexdigest(),
                })

        shader = reports / "shader_effect_evidence"
        write_json(shader / "SUMMARY.json", {
            "type": "br_quartet_restoration_shader_effect_evidence_summary",
            "tool_version": "0.0.12",
        })
        write_tsv(shader / "RENDER_PAYLOADS.tsv", [
            "candidate_id", "normalized_path", "member_key", "side", "payload_size", "payload_sha256",
        ], shader_rows)

        def pair_loader(**_kwargs):
            return pairs, []

        return project, workspace, reports, pair_loader

    def test_changed_bytes_are_coalesced_to_enclosing_words(self) -> None:
        source = bytes(range(64))
        target = bytearray(source)
        target[21] ^= 0x55
        target[22] ^= 0x22
        cells = TOOL.build_word_cells(
            source=source,
            target=bytes(target),
            extension=".opl2",
            header_guard_bytes=16,
            tail_guard_bytes=16,
        )
        self.assertEqual(len(cells), 1)
        self.assertEqual(cells[0]["start"], 20)
        self.assertEqual(cells[0]["end"], 24)
        self.assertEqual(cells[0]["changed_byte_mask"], "0110")
        self.assertTrue(cells[0]["eligible"])
        candidate = TOOL.apply_cells(bytes(target), cells)
        self.assertEqual(candidate, source)
        self.assertEqual(TOOL.reverse_cells(candidate, cells), bytes(target))

    def test_guarded_word_is_not_eligible(self) -> None:
        source = bytes(range(64))
        target = bytearray(source)
        target[2] ^= 0x11
        cells = TOOL.build_word_cells(
            source=source,
            target=bytes(target),
            extension=".bin",
            header_guard_bytes=16,
            tail_guard_bytes=16,
        )
        self.assertFalse(cells[0]["eligible"])
        self.assertIn("touches_guarded_header", cells[0]["exclusion_reasons"])

    def test_collect_reports_exact_word_reconstruction_but_no_prototype_authorization(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project, workspace, reports, loader = self.build_fixture(Path(temporary))
            output, summary = TOOL.collect(
                project_root=project,
                workspace_root=workspace,
                report_root=reports,
                pair_loader=loader,
            )
            self.assertTrue(output.is_file())
            self.assertEqual(summary["target_member_rows"], 2)
            self.assertEqual(summary["exact_original_member_rows"], 2)
            self.assertEqual(summary["safe_local_prototype_rows"], 0)
            members = TOOL.read_tsv(
                reports / TOOL.EVIDENCE_DIR_NAME / "BATHROOM_SCENE_DESCRIPTOR_MEMBERS.tsv"
            )
            self.assertEqual(len(members), 2)
            self.assertTrue(all(row["best_exact_original"] == "True" for row in members))
            self.assertTrue(all(row["safe_to_build_local_prototype_without_manual_decode"] == "False" for row in members))
            self.assertTrue(all("manual_decode_required" in row["classification"] for row in members))

    def test_stage65_validation_rejects_wrong_analyzed_count(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            _project, _workspace, reports, _loader = self.build_fixture(Path(temporary))
            summary_path = reports / "expanded_scene_effect_member_evidence" / "SUMMARY.json"
            summary = json.loads(summary_path.read_text(encoding="utf-8"))
            summary["analyzed_member_rows"] = 184
            write_json(summary_path, summary)
            with self.assertRaises(TOOL.BathroomWordAuditError):
                TOOL.validate_stage65_report(reports / "expanded_scene_effect_member_evidence")


if __name__ == "__main__":
    unittest.main()
