#!/usr/bin/env python3
from __future__ import annotations

import csv
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
TOOL_PATH = ROOT / "workstreams/quartet_restoration/collect_reflector_slot_light_reference_target_header_evidence.py"
spec = importlib.util.spec_from_file_location("stage89", TOOL_PATH)
assert spec and spec.loader
TOOL = importlib.util.module_from_spec(spec)
spec.loader.exec_module(TOOL)


def write_tsv(path: Path, fields: list[str], rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def set_u32(data: bytearray, offset: int, value: int) -> None:
    data[offset:offset + 4] = int(value & 0xFFFFFFFF).to_bytes(4, "little")


def make_pair(name: str, size: int = 512, marker: int = 1) -> tuple[dict[str, object], dict[str, object]]:
    source = bytearray(size)
    target = bytearray(size)
    for off in range(0, size, 4):
        value = ((marker * 0x101) + off) & 0xFFFFFFFF
        set_u32(source, off, value)
        set_u32(target, off, value)
    key = name.casefold() + "#0"
    return (
        {"comparison_key": key, "name": name, "payload": bytes(source)},
        {"comparison_key": key, "name": name, "payload": bytes(target)},
    )


class ReferenceTargetHelpers(unittest.TestCase):
    def test_inbound_reference_offsets(self):
        payload = bytearray(64)
        set_u32(payload, 16, (8 - 16) & 0xFFFFFFFF)
        set_u32(payload, 24, (8 - 24) & 0xFFFFFFFF)
        set_u32(payload, 8, 0)  # zero displacement is intentionally excluded
        self.assertEqual(TOOL.inbound_reference_offsets(bytes(payload), 8), [16, 24])

    def test_masked_record_only_zeros_residual(self):
        payload = bytes(range(64))
        masked = TOOL.masked_record(payload, 4, 48, 44)
        self.assertEqual(len(masked), 44)
        self.assertEqual(masked[:-4], payload[4:44])
        self.assertEqual(masked[-4:], b"\0\0\0\0")

    def test_aligned_occurrences_filters_unaligned_hits(self):
        self.assertEqual(TOOL.aligned_occurrences(b"xxABxxAB", b"AB"), [])
        self.assertEqual(TOOL.aligned_occurrences(b"ABxxABxx", b"AB"), [0, 4])

    def test_leading_target_word_classification(self):
        self.assertEqual(
            TOOL.classify_dword(0x100, 0x180, 0, 1024, 1024),
            "target_window_leading_size_or_offset_candidate",
        )


class SyntheticStage89Report(unittest.TestCase):
    def test_build_report_confirms_field_relative_clusters_without_write_authorization(self):
        with tempfile.TemporaryDirectory(prefix="stage89-test-") as temp_name:
            temp = Path(temp_name)
            reports = temp / "reports"
            workspace = temp / "workspace"
            reports.mkdir()
            workspace.mkdir()

            stage79 = reports / TOOL.STAGE79_DIR
            stage79.mkdir()
            (stage79 / "SUMMARY.json").write_text(json.dumps({
                "type": "br_quartet_restoration_reflector_character_slot_render_member_evidence_summary",
                "tool_version": "0.0.92",
                "character_slot_rows": 15,
            }), encoding="utf-8")
            scope_rows = []
            for index in range(21):
                scope_rows.append({
                    "candidate_id": f"c{index}",
                    "normalized_path": f"data/x64/effect/fake{index % 4}.elixir.gz",
                    "member_key": f"scope_{index}.g1e#0",
                    "member_name": f"scope_{index}.g1e",
                    "asset_role": "ringlight" if index < 19 else "eyelight",
                })
            write_tsv(stage79 / "REFLECTOR_SLOT_RENDER_MEMBERS.tsv", list(scope_rows[0]), scope_rows)

            candidate_path = "data/x64/effect/1002_pc02.elixir.gz"
            candidate_key = "candidate.g1e#0"
            neutral_path = "data/x64/effect/100_common.elixir.gz"
            neutral_key = "neutral.g1e#0"
            eye1_path = "data/x64/effect/1000_pc00.elixir.gz"
            eye1_key = "eye1.g1e#0"
            eye2_key = "eye2.g1e#0"

            # Candidate: endpoint 128, source island 256..300, target 272..316.
            candidate_source = bytearray(512)
            candidate_target = bytearray(512)
            for off in range(0, 512, 4):
                set_u32(candidate_source, off, 0x10000000 + off)
                set_u32(candidate_target, off, 0x10000000 + off)
            set_u32(candidate_source, 128, 0x100)
            set_u32(candidate_target, 128, 0x180)
            source_record = [0x43160000, 0x43160000, 1, 2, 3, 4, 5, 6, 7, 8, (128 - 296) & 0xFFFFFFFF]
            target_record = [0x42960000, 0x42960000, 1, 2, 3, 4, 5, 6, 7, 8, (128 - 312) & 0xFFFFFFFF]
            for index, value in enumerate(source_record):
                set_u32(candidate_source, 256 + index * 4, value)
            for index, value in enumerate(target_record):
                set_u32(candidate_target, 272 + index * 4, value)
            for source_offset, target_offset in ((296, 312), (320, 336), (340, 356)):
                set_u32(candidate_source, source_offset, (128 - source_offset) & 0xFFFFFFFF)
                set_u32(candidate_target, target_offset, (128 - target_offset) & 0xFFFFFFFF)

            # Neutral and two eyelights: endpoint 64.
            neutral_source = bytearray(384)
            neutral_target = bytearray(384)
            for off in range(0, 384, 4):
                set_u32(neutral_source, off, 0x20000000 + off)
                set_u32(neutral_target, off, 0x20000000 + off)
            set_u32(neutral_source, 64, 0x80)
            set_u32(neutral_target, 64, 0xC0)
            neutral_source_record = source_record[:-1] + [((64 - 232) & 0xFFFFFFFF)]
            neutral_target_record = target_record[:-1] + [((64 - 248) & 0xFFFFFFFF)]
            for index, value in enumerate(neutral_source_record):
                set_u32(neutral_source, 192 + index * 4, value)
            for index, value in enumerate(neutral_target_record):
                set_u32(neutral_target, 208 + index * 4, value)

            eye_payloads = []
            for marker, name in ((3, "eye1.g1e"), (4, "eye2.g1e")):
                source = bytearray(256)
                target = bytearray(256)
                for off in range(0, 256, 4):
                    set_u32(source, off, marker * 0x100000 + off)
                    set_u32(target, off, marker * 0x100000 + off)
                set_u32(source, 160, (64 - 160) & 0xFFFFFFFF)
                set_u32(target, 176, (64 - 176) & 0xFFFFFFFF)
                eye_payloads.append((name, source, target))

            stage87 = reports / TOOL.STAGE87_DIR
            stage87.mkdir()
            island_rows = [
                {"island_role": "candidate_ringlight", "normalized_path": candidate_path, "member_key": candidate_key, "member_name": "candidate.g1e", "source_start": 256, "source_end_exclusive": 300, "target_start": 272, "target_end_exclusive": 316},
                {"island_role": "neutral_control", "normalized_path": neutral_path, "member_key": neutral_key, "member_name": "neutral.g1e", "source_start": 192, "source_end_exclusive": 236, "target_start": 208, "target_end_exclusive": 252},
            ]
            write_tsv(stage87 / "SLOT_LIGHT_LOCAL_CHANGE_ISLANDS.tsv", list(island_rows[0]), island_rows)
            write_tsv(stage87 / "SLOT_LIGHT_LOCAL_CHANGE_ISLAND_TRANSITIONS.tsv", ["island_role"], [])

            stage88 = reports / TOOL.STAGE88_DIR
            stage88.mkdir()
            (stage88 / "SUMMARY.json").write_text(json.dumps({
                "type": "br_quartet_restoration_reflector_slot_light_record_boundary_residual_evidence_summary",
                "tool_version": "0.1.2",
                "status": "stage87_residuals_tested_as_relocation_compensated_signed_fields_offset_origin_and_brightness_semantics_unresolved",
                "residual_rows": 2,
                "relocation_compensated_residual_rows": 2,
                "stage84_relocation_compensation_recurrence_rows": 51,
                "stage84_recurrence_member_rows": 5,
                "offset_origin_resolved": False,
                "prototype_candidate_rows": 0,
                "brightness_semantics_confirmed": False,
                "censorship_semantics_confirmed": False,
                "skipped_rows": 0,
                "policy": {"installed_game_modified": False, "render_payload_written": False, "pak_repacked": False, "core_registry_modified": False, "profile_activated": False},
            }), encoding="utf-8")
            residuals = [
                {"island_role": "candidate_ringlight", "normalized_path": candidate_path, "member_key": candidate_key, "member_name": "candidate.g1e", "source_offset": 296, "target_offset": 312, "source_u32_hex": f"0x{(128-296)&0xffffffff:08x}", "target_u32_hex": f"0x{(128-312)&0xffffffff:08x}"},
                {"island_role": "neutral_control", "normalized_path": neutral_path, "member_key": neutral_key, "member_name": "neutral.g1e", "source_offset": 232, "target_offset": 248, "source_u32_hex": f"0x{(64-232)&0xffffffff:08x}", "target_u32_hex": f"0x{(64-248)&0xffffffff:08x}"},
            ]
            write_tsv(stage88 / "SLOT_LIGHT_RESIDUAL_AUDIT.tsv", list(residuals[0]), residuals)

            recurrence = [
                {"normalized_path": candidate_path, "member_key": candidate_key, "member_name": "candidate.g1e", "source_offset": 296, "target_offset": 312, "source_u32_hex": residuals[0]["source_u32_hex"], "target_u32_hex": residuals[0]["target_u32_hex"], "source_endpoint_dword_start_model": 128, "target_endpoint_dword_start_model": 128},
                {"normalized_path": candidate_path, "member_key": candidate_key, "member_name": "candidate.g1e", "source_offset": 320, "target_offset": 336, "source_u32_hex": f"0x{(128-320)&0xffffffff:08x}", "target_u32_hex": f"0x{(128-336)&0xffffffff:08x}", "source_endpoint_dword_start_model": 128, "target_endpoint_dword_start_model": 128},
                {"normalized_path": candidate_path, "member_key": candidate_key, "member_name": "candidate.g1e", "source_offset": 340, "target_offset": 356, "source_u32_hex": f"0x{(128-340)&0xffffffff:08x}", "target_u32_hex": f"0x{(128-356)&0xffffffff:08x}", "source_endpoint_dword_start_model": 128, "target_endpoint_dword_start_model": 128},
                {"normalized_path": eye1_path, "member_key": eye1_key, "member_name": "eye1.g1e", "source_offset": 160, "target_offset": 176, "source_u32_hex": f"0x{(64-160)&0xffffffff:08x}", "target_u32_hex": f"0x{(64-176)&0xffffffff:08x}", "source_endpoint_dword_start_model": 64, "target_endpoint_dword_start_model": 64},
                {"normalized_path": eye1_path, "member_key": eye2_key, "member_name": "eye2.g1e", "source_offset": 160, "target_offset": 176, "source_u32_hex": f"0x{(64-160)&0xffffffff:08x}", "target_u32_hex": f"0x{(64-176)&0xffffffff:08x}", "source_endpoint_dword_start_model": 64, "target_endpoint_dword_start_model": 64},
            ]
            while len(recurrence) < 51:
                recurrence.append({"normalized_path": "dummy", "member_key": "dummy", "member_name": "dummy.g1e", "source_offset": 0, "target_offset": 0, "source_u32_hex": "0x00000001", "target_u32_hex": "0x00000001", "source_endpoint_dword_start_model": 9999 + len(recurrence), "target_endpoint_dword_start_model": 9999 + len(recurrence)})
            write_tsv(stage88 / "SLOT_LIGHT_RELATIVE_OFFSET_RECURRENCE.tsv", list(recurrence[0]), recurrence)
            endpoint_context_rows = []
            model_rows = []
            for role in ("candidate_ringlight", "neutral_control"):
                for model in ("dword_start_relative", "dword_end_relative", "island_start_relative", "island_end_relative"):
                    endpoint_context_rows.append({"island_role": role, "model": model, "source_target_context_equal": model == "island_start_relative"})
                    model_rows.append({"island_role": role, "model": model, "model_status": "exact_in_bounds_aligned"})
            write_tsv(stage88 / "SLOT_LIGHT_RESIDUAL_ENDPOINT_CONTEXTS.tsv", list(endpoint_context_rows[0]), endpoint_context_rows)
            write_tsv(stage88 / "SLOT_LIGHT_RESIDUAL_OFFSET_MODELS.tsv", list(model_rows[0]), model_rows)

            containers = [
                {"normalized_path": candidate_path, "source_members": [{"comparison_key": candidate_key, "name": "candidate.g1e", "payload": bytes(candidate_source)}], "target_members": [{"comparison_key": candidate_key, "name": "candidate.g1e", "payload": bytes(candidate_target)}]},
                {"normalized_path": neutral_path, "source_members": [{"comparison_key": neutral_key, "name": "neutral.g1e", "payload": bytes(neutral_source)}], "target_members": [{"comparison_key": neutral_key, "name": "neutral.g1e", "payload": bytes(neutral_target)}]},
                {"normalized_path": eye1_path, "source_members": [], "target_members": []},
                {"normalized_path": "data/x64/effect/dummies.elixir.gz", "source_members": [], "target_members": []},
            ]
            for name, source, target in eye_payloads:
                key = name.casefold() + "#0"
                containers[2]["source_members"].append({"comparison_key": key, "name": name, "payload": bytes(source)})
                containers[2]["target_members"].append({"comparison_key": key, "name": name, "payload": bytes(target)})
            current_pairs = 4
            for index in range(536):
                name = f"dummy_{index:03d}.g1e"
                left, right = make_pair(name, marker=10 + index)
                containers[3]["source_members"].append(left)
                containers[3]["target_members"].append(right)
                current_pairs += 1
            self.assertEqual(current_pairs, 540)

            def fake_loader(**_kwargs):
                return containers, []

            output, archive, summary = TOOL.build_report(
                ROOT,
                create_archive=False,
                workspace_root=workspace,
                report_root=reports,
                container_loader=fake_loader,
            )
            self.assertIsNone(archive)
            self.assertEqual(summary["sibling_G1E_G1EM_member_rows"], 540)
            self.assertTrue(summary["field_relative_base_family_supported"])
            self.assertFalse(summary["exact_field_start_vs_end_origin_resolved"])
            self.assertTrue(summary["masked_record_template_exact_across_candidate_and_neutral"])
            self.assertEqual(summary["prototype_candidate_rows"], 0)
            self.assertFalse(summary["brightness_semantics_confirmed"])
            self.assertTrue((output / "SLOT_LIGHT_REFERENCE_CLUSTER_AUDIT.tsv").is_file())


if __name__ == "__main__":
    unittest.main()
