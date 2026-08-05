from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path

WORKSTREAM = Path(__file__).resolve().parents[1]
TOOL_PATH = WORKSTREAM / "collect_bathroom_ordinary_field_control_evidence.py"
SPEC = importlib.util.spec_from_file_location("stage68_tool", TOOL_PATH)
assert SPEC and SPEC.loader
TOOL = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = TOOL
SPEC.loader.exec_module(TOOL)

STAGE67_TEST_PATH = WORKSTREAM / "tests/test_collect_bathroom_sibling_descriptor_comparison_evidence.py"
TEST_SPEC = importlib.util.spec_from_file_location("stage67_test_fixture", STAGE67_TEST_PATH)
assert TEST_SPEC and TEST_SPEC.loader
STAGE67_TEST = importlib.util.module_from_spec(TEST_SPEC)
sys.modules[TEST_SPEC.name] = STAGE67_TEST
TEST_SPEC.loader.exec_module(STAGE67_TEST)


def make_control(control_id: str, source_word: bytes, target_word: bytes, *, offset: int = 64):
    source = bytearray((index * 19 + 7) & 0xFF for index in range(512))
    target = bytearray(source)
    source[offset:offset + 4] = source_word
    target[offset:offset + 4] = target_word
    return {
        "control_id": control_id,
        "pair_id": "ordinary_fields",
        "normalized_path": f"data/x64/field/s00_{control_id}/{control_id}.elixir.gz",
        "member_key": f"{control_id}.opl2#0",
        "source_member_name": f"{control_id}.opl2",
        "target_member_name": f"{control_id}.opl2",
        "source_payload": bytes(source),
        "target_payload": bytes(target),
    }


class Stage68Tests(unittest.TestCase):
    def prepare_stage67(self, root: Path):
        fixture = STAGE67_TEST.Stage67Tests()
        project, workspace, reports, pair_loader = fixture.build_fixture(root)
        TOOL.STAGE67.collect(
            project_root=project,
            workspace_root=workspace,
            report_root=reports,
            pair_loader=pair_loader,
            progress_callback=lambda _message: None,
        )
        pairs, _skipped = pair_loader()
        target_pair = next(row for row in pairs if row["member_key"] == TOOL.TARGET_OPL2_KEY)
        target_cells = TOOL.STAGE66.build_word_cells(
            source=bytes(target_pair["source_payload"]),
            target=bytes(target_pair["target_payload"]),
            extension=".opl2",
            header_guard_bytes=16,
            tail_guard_bytes=16,
        )
        return project, workspace, reports, pair_loader, target_cells

    def test_compares_ordinary_controls_and_authorizes_only_river(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project, workspace, reports, pair_loader, target_cells = self.prepare_stage67(Path(temporary))
            shared = target_cells[3]
            controls = [
                make_control("ordinary_a", bytes.fromhex(shared["source_hex"]), bytes.fromhex(shared["target_hex"])),
                make_control("ordinary_b", b"\x10\x20\x30\x40", b"\x11\x22\x33\x44"),
                make_control("ordinary_c", b"\x50\x60\x70\x80", b"\x55\x66\x77\x88"),
            ]

            def control_loader(**_kwargs):
                return controls, []

            output, summary = TOOL.collect(
                project_root=project,
                workspace_root=workspace,
                report_root=reports,
                pair_loader=pair_loader,
                control_loader=control_loader,
                progress_callback=lambda _message: None,
            )
            self.assertTrue(output.is_file())
            self.assertEqual(summary["ordinary_control_member_rows"], 3)
            self.assertTrue(summary["ordinary_control_scope_sufficient"])
            self.assertGreaterEqual(summary["target_opl2_cells_shared_by_exact_transition_with_ordinary_control"], 1)
            self.assertEqual(summary["opl2_safe_local_prototype_rows"], 0)
            self.assertEqual(summary["river_static_local_prototype_authorized_rows"], 1)
            self.assertEqual(summary["safe_local_prototype_rows"], 1)
            river_rows = TOOL.read_tsv(reports / TOOL.EVIDENCE_DIR_NAME / "BATHROOM_RIVER_STATIC_PROMOTION_REVIEW.tsv")
            self.assertEqual(len(river_rows), 1)
            self.assertTrue(TOOL.parse_bool(river_rows[0]["static_local_prototype_authorized"]))

    def test_insufficient_ordinary_scope_does_not_block_river_authorization(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project, workspace, reports, pair_loader, _target_cells = self.prepare_stage67(Path(temporary))

            def control_loader(**_kwargs):
                return [make_control("ordinary_only", b"\x01\x02\x03\x04", b"\x05\x06\x07\x08")], []

            _output, summary = TOOL.collect(
                project_root=project,
                workspace_root=workspace,
                report_root=reports,
                pair_loader=pair_loader,
                control_loader=control_loader,
                progress_callback=lambda _message: None,
            )
            self.assertFalse(summary["ordinary_control_scope_sufficient"])
            self.assertEqual(summary["opl2_safe_local_prototype_rows"], 0)
            self.assertEqual(summary["river_static_local_prototype_authorized_rows"], 1)


if __name__ == "__main__":
    unittest.main()
