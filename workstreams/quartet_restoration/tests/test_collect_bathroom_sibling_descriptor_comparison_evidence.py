from __future__ import annotations

import csv
import hashlib
import importlib.util
import json
import sys
import tarfile
import tempfile
import unittest
from pathlib import Path

WORKSTREAM = Path(__file__).resolve().parents[1]
TOOL_PATH = WORKSTREAM / "collect_bathroom_sibling_descriptor_comparison_evidence.py"
SPEC = importlib.util.spec_from_file_location("stage67_tool", TOOL_PATH)
assert SPEC and SPEC.loader
TOOL = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = TOOL
SPEC.loader.exec_module(TOOL)


def write_tsv(path: Path, fieldnames: list[str], rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fieldnames})


def write_json(path: Path, value: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def changed_payload(size: int, changes: list[tuple[int, bytes, bytes]]) -> tuple[bytes, bytes]:
    source = bytearray((index * 37 + 11) & 0xFF for index in range(size))
    target = bytearray(source)
    for start, source_word, target_word in changes:
        source[start:start + len(source_word)] = source_word
        target[start:start + len(target_word)] = target_word
    return bytes(source), bytes(target)


class Stage67Tests(unittest.TestCase):
    def build_fixture(self, root: Path, *, repeat_tail: bool = True):
        project = root / "project"
        workspace = project / ".local/build/quartet_restoration"
        reports = project / ".local/reports/quartet_restoration"
        for side in ("source", "target"):
            (workspace / side).mkdir(parents=True, exist_ok=True)

        # Hinako OPL2: 61 changed words, 146 changed bytes. The first exact
        # transition is also present in the shower control; the rest are unique.
        target_changes: list[tuple[int, bytes, bytes]] = []
        for i in range(61):
            start = 20 + i * 8
            changed = 4 if i == 0 else (2 if i <= 38 else 3)
            source_word = bytes([(0x10 + i) & 0xFF, (0x20 + i) & 0xFF, (0x30 + i) & 0xFF, (0x40 + i) & 0xFF])
            target_word = bytearray(source_word)
            for j in range(changed):
                target_word[j] ^= 0x55
            target_changes.append((start, source_word, bytes(target_word)))
        bathroom_source, bathroom_target = changed_payload(2180, target_changes)

        shower_changes: list[tuple[int, bytes, bytes]] = [
            (20, target_changes[0][1], target_changes[0][2]),
        ]
        for i in range(1, 28):
            start = 24 + i * 8
            source_word = bytes([0x80 + i, 0x30 + i, 0x40 + i, 0x50 + i])
            target_word = bytes(value ^ 0x0F for value in source_word)
            shower_changes.append((start, source_word, target_word))
        shower_source, shower_target = changed_payload(1469, shower_changes)

        pool_changes: list[tuple[int, bytes, bytes]] = []
        for i in range(97):
            start = 20 + i * 8
            source_word = bytes([(0x90 + i) & 0xFF, (0x60 + i) & 0xFF, (0x20 + i) & 0xFF, (0x10 + i) & 0xFF])
            target_word = bytearray(source_word)
            changed = 2 if i == 96 else 4
            for j in range(changed):
                target_word[j] ^= 0x33
            pool_changes.append((start, source_word, bytes(target_word)))
        pool_source, pool_target = changed_payload(3125, pool_changes)

        river_changes = [
            (20, b"\x01\x02\x03\x04", b"\x11\x12\x13\x14"),
            (40, b"\x21\x22\x23\x24", b"\x31\x32\x33\x24"),
            (80, b"\x41\x42\x43\x44", b"\x51\x52\x53\x44"),
            (120, b"\x61\x62\x63\x64", b"\x71\x72\x73\x64"),
        ]
        repeated_source = b"\x00\x00\x88\x42"
        repeated_target = b"\x9f\x57\x94\x42"
        river_changes.extend([
            (208, repeated_source, repeated_target),
            (224, repeated_source, repeated_target),
            (240, repeated_source, repeated_target if repeat_tail else b"\x9f\x57\x95\x42"),
        ])
        river_source, river_target = changed_payload(252, river_changes)
        self.assertEqual(TOOL.STAGE66.hamming_distance(bathroom_source, bathroom_target), 146)
        self.assertEqual(TOOL.STAGE66.hamming_distance(shower_source, shower_target), 112)
        self.assertEqual(TOOL.STAGE66.hamming_distance(pool_source, pool_target), 386)
        self.assertEqual(TOOL.STAGE66.hamming_distance(river_source, river_target), 22)

        payloads = {
            TOOL.TARGET_OPL2_KEY: (bathroom_source, bathroom_target),
            TOOL.SIBLING_OPL2_KEYS[0]: (shower_source, shower_target),
            TOOL.SIBLING_OPL2_KEYS[1]: (pool_source, pool_target),
            TOOL.RIVER_KEY: (river_source, river_target),
        }

        stage65 = reports / "expanded_scene_effect_member_evidence"
        write_json(stage65 / "SUMMARY.json", {
            "type": "br_quartet_restoration_expanded_scene_effect_member_evidence_summary",
            "tool_version": "0.0.75",
            "status": "expanded_scene_effect_member_inverse_range_audit_complete_no_payload_written_runtime_deferred",
            "expanded_focused_binary_delta_rows_selected": 185,
            "rehydrated_member_rows": 185,
            "analyzed_member_rows": 185,
            "promotable_exact_original_member_rows": 0,
            "partial_inverse_evidence_member_rows": 13,
            "skipped_rows": 0,
        })
        stage65_rows: list[dict[str, object]] = []
        pairs: list[dict[str, object]] = []
        metadata: list[dict[str, object]] = []
        for member_key, expected in TOOL.EXPECTED_STAGE65_ROWS.items():
            source, target = payloads[member_key]
            source_name = member_key.split("#", 1)[0].upper()
            target_name = source_name
            row = {
                **expected,
                "member_key": member_key,
                "source_member_name": source_name,
                "target_member_name": target_name,
            }
            stage65_rows.append(row)
            pairs.append({**row, "source_payload": source, "target_payload": target})
            for side, payload in (("source", source), ("target", target)):
                metadata.append({
                    "candidate_id": expected["candidate_id"],
                    "normalized_path": expected["normalized_path"],
                    "member_key": member_key,
                    "side": side,
                    "payload_size": len(payload),
                    "payload_sha256": hashlib.sha256(payload).hexdigest(),
                })
        write_tsv(stage65 / "EXPANDED_SCENE_EFFECT_MEMBERS.tsv", list(stage65_rows[0]), stage65_rows)

        shader = reports / "shader_effect_evidence"
        write_json(shader / "SUMMARY.json", {
            "type": "br_quartet_restoration_shader_effect_evidence_summary",
            "tool_version": "0.0.11",
        })
        write_tsv(shader / "RENDER_PAYLOADS.tsv", list(metadata[0]), metadata)

        stage66 = reports / "bathroom_scene_descriptor_word_evidence"
        write_json(stage66 / "SUMMARY.json", {
            "type": "br_quartet_restoration_bathroom_scene_descriptor_word_evidence_summary",
            "tool_version": "0.0.76",
            "status": "bathroom_scene_descriptor_word_cell_audit_complete_no_payload_written_manual_decode_required",
            "target_member_rows": 2,
            "word_cell_rows": 68,
            "transition_group_rows": 54,
            "candidate_rows": 78,
            "passing_candidate_rows": 78,
            "exact_original_candidate_rows": 1,
            "exact_original_member_rows": 1,
            "full_word_reconstruction_member_rows": 1,
            "safe_local_prototype_rows": 0,
            "skipped_rows": 0,
            "policy": {},
        })
        bathroom_cells = TOOL.STAGE66.build_word_cells(
            source=bathroom_source, target=bathroom_target, extension=".opl2",
            header_guard_bytes=16, tail_guard_bytes=16,
        )
        river_cells = TOOL.STAGE66.build_word_cells(
            source=river_source, target=river_target, extension=".bin",
            header_guard_bytes=16, tail_guard_bytes=16,
        )
        self.assertEqual(len(bathroom_cells), 61)
        self.assertEqual(len(river_cells), 7)
        cell_rows = []
        for member_key, cells in ((TOOL.TARGET_OPL2_KEY, bathroom_cells), (TOOL.RIVER_KEY, river_cells)):
            for cell in cells:
                cell_rows.append({
                    "member_key": member_key,
                    "cell_index": cell["cell_index"],
                    "start": cell["start"],
                    "end": cell["end"],
                    "source_hex": cell["source_hex"],
                    "target_hex": cell["target_hex"],
                    "transition_id": cell["transition_id"],
                    "eligible": cell["eligible"],
                    "exclusion_reasons": cell["exclusion_reasons"],
                })
        write_tsv(stage66 / "BATHROOM_SCENE_DESCRIPTOR_WORD_CELLS.tsv", list(cell_rows[0]), cell_rows)
        write_tsv(stage66 / "BATHROOM_SCENE_DESCRIPTOR_MEMBERS.tsv", [
            "member_key", "target_distance_to_source", "word_cell_count", "eligible_word_cell_count",
            "excluded_word_cell_count", "best_candidate_distance_to_source", "best_distance_improvement",
            "best_exact_original", "all_word_cells_eligible", "classification",
            "safe_to_build_local_prototype_without_manual_decode",
        ], [
            {
                "member_key": TOOL.TARGET_OPL2_KEY,
                "target_distance_to_source": 146,
                "word_cell_count": 61,
                "eligible_word_cell_count": 61,
                "excluded_word_cell_count": 0,
                "best_candidate_distance_to_source": 0,
                "best_distance_improvement": 146,
                "best_exact_original": True,
                "all_word_cells_eligible": True,
                "classification": "exact_original_word_reconstruction_available_manual_decode_required",
                "safe_to_build_local_prototype_without_manual_decode": False,
            },
            {
                "member_key": TOOL.RIVER_KEY,
                "target_distance_to_source": 22,
                "word_cell_count": 7,
                "eligible_word_cell_count": 6,
                "excluded_word_cell_count": 1,
                "best_candidate_distance_to_source": 3,
                "best_distance_improvement": 19,
                "best_exact_original": False,
                "all_word_cells_eligible": False,
                "classification": "partial_word_reconstruction_evidence_only",
                "safe_to_build_local_prototype_without_manual_decode": False,
            },
        ])

        def pair_loader(**_kwargs):
            return pairs, []

        return project, workspace, reports, pair_loader

    def test_compares_siblings_and_supports_repeated_river_tail_exception(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project, workspace, reports, loader = self.build_fixture(Path(temporary))
            output, summary = TOOL.collect(
                project_root=project,
                workspace_root=workspace,
                report_root=reports,
                pair_loader=loader,
                progress_callback=lambda _message: None,
            )
            self.assertTrue(output.is_file())
            self.assertEqual(summary["scope_member_rows"], 4)
            self.assertEqual(summary["target_opl2_cells_shared_by_exact_transition_with_sibling"], 1)
            self.assertEqual(summary["target_opl2_scope_unique_transition_cells"], 60)
            self.assertEqual(summary["river_repeated_tail_guard_exception_rows"], 1)
            self.assertEqual(summary["river_exact_original_candidate_rows"], 1)
            self.assertEqual(summary["safe_local_prototype_rows"], 0)
            river_rows = TOOL.read_tsv(reports / TOOL.EVIDENCE_DIR_NAME / "BATHROOM_RIVER_CANDIDATES.tsv")
            exact = [row for row in river_rows if TOOL.parse_bool(row["exact_original"])]
            self.assertEqual(len(exact), 1)
            self.assertEqual(exact[0]["candidate_kind"], "complete_word_set_with_repeated_tail_guard_exception")

    def test_does_not_grant_tail_exception_without_identical_repetition(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project, workspace, reports, loader = self.build_fixture(Path(temporary), repeat_tail=False)
            _output, summary = TOOL.collect(
                project_root=project,
                workspace_root=workspace,
                report_root=reports,
                pair_loader=loader,
                progress_callback=lambda _message: None,
            )
            self.assertEqual(summary["river_repeated_tail_guard_exception_rows"], 0)
            self.assertEqual(summary["river_exact_original_candidate_rows"], 0)

    def test_rejects_stage66_report_that_authorizes_payload(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project, workspace, reports, loader = self.build_fixture(Path(temporary))
            path = reports / "bathroom_scene_descriptor_word_evidence" / "BATHROOM_SCENE_DESCRIPTOR_MEMBERS.tsv"
            rows = TOOL.read_tsv(path)
            rows[0]["safe_to_build_local_prototype_without_manual_decode"] = "True"
            write_tsv(path, list(rows[0]), rows)
            with self.assertRaises(TOOL.SiblingDescriptorError):
                TOOL.collect(
                    project_root=project,
                    workspace_root=workspace,
                    report_root=reports,
                    pair_loader=loader,
                    progress_callback=lambda _message: None,
                )


if __name__ == "__main__":
    unittest.main()
