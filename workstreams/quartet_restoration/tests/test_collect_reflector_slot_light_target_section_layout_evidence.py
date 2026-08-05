#!/usr/bin/env python3
from __future__ import annotations

import csv
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
TOOL_PATH = ROOT / "workstreams/quartet_restoration/collect_reflector_slot_light_target_section_layout_evidence.py"
spec = importlib.util.spec_from_file_location("stage90", TOOL_PATH)
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


def set_header(data: bytearray, endpoint: int, count: int, span: int) -> None:
    words = [
        span, 0, count, count, count, 2, 56,
        56 + 4 * (count - 1),
        56 + 8 * (count - 1),
        56 + 12 * (count - 1),
        0x00010000, 0x3DCCCCCD, 0, 0x3F800000,
    ]
    for index, value in enumerate(words):
        set_u32(data, endpoint + index * 4, value)


def make_dummy_pair(name: str, size: int = 256) -> tuple[dict[str, object], dict[str, object]]:
    payload = bytes(size)
    key = name.casefold() + "#0"
    return (
        {"comparison_key": key, "name": name, "payload": payload},
        {"comparison_key": key, "name": name, "payload": payload},
    )


class HeaderHelpers(unittest.TestCase):
    def test_parse_section_header_accepts_count_boundary_formula(self):
        payload = bytearray(512)
        set_header(payload, 64, 5, 256)
        row = TOOL.parse_section_header(bytes(payload), 64)
        self.assertTrue(row["exact_layout"])
        self.assertEqual(row["table_boundary_1"], 72)
        self.assertEqual(row["table_boundary_2"], 88)
        self.assertEqual(row["table_boundary_3"], 104)

    def test_shifted_dword_end_does_not_parse_as_header(self):
        payload = bytearray(512)
        set_header(payload, 64, 5, 256)
        self.assertFalse(TOOL.parse_section_header(bytes(payload), 68)["exact_layout"])

    def test_masked_record_zeros_only_relocation_word(self):
        payload = bytearray(range(64))
        result = TOOL.masked_record(bytes(payload), 4, 48, 44)
        self.assertEqual(result[:40], bytes(payload[4:44]))
        self.assertEqual(result[40:], b"\0\0\0\0")


class SyntheticStage90Report(unittest.TestCase):
    def test_build_report_resolves_start_origin_but_keeps_semantics_blocked(self):
        with tempfile.TemporaryDirectory(prefix="stage90-test-") as temp_name:
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
            scope_rows = [{
                "candidate_id": f"c{index}",
                "normalized_path": f"data/x64/effect/fake{index % 4}.elixir.gz",
                "member_key": f"scope_{index}.g1e#0",
                "member_name": f"scope_{index}.g1e",
                "asset_role": "ringlight" if index < 19 else "eyelight",
            } for index in range(21)]
            write_tsv(stage79 / "REFLECTOR_SLOT_RENDER_MEMBERS.tsv", list(scope_rows[0]), scope_rows)

            candidate_path = "data/x64/effect/1002_pc02.elixir.gz"
            candidate_key = "candidate.g1e#0"
            neutral_path = "data/x64/effect/100_common.elixir.gz"
            neutral_key = "neutral.g1e#0"
            eye_path = "data/x64/effect/1000_pc00.elixir.gz"
            eye1_key = "eye1.g1e#0"
            eye2_key = "eye2.g1e#0"

            candidate_source = bytearray(768)
            candidate_target = bytearray(896)
            set_header(candidate_source, 128, 3, 512)
            set_header(candidate_target, 128, 4, 640)
            source_record = [150, 150, 1, 2, 3, 4, 5, 6, 7, 8, (128 - 296) & 0xFFFFFFFF]
            target_record = [75, 75, 1, 2, 3, 4, 5, 6, 7, 8, (128 - 312) & 0xFFFFFFFF]
            for i, value in enumerate(source_record):
                set_u32(candidate_source, 256 + i * 4, value)
            for i, value in enumerate(target_record):
                set_u32(candidate_target, 272 + i * 4, value)
            for source_offset, target_offset in ((296, 312), (340, 356), (400, 416)):
                set_u32(candidate_source, source_offset, (128 - source_offset) & 0xFFFFFFFF)
                set_u32(candidate_target, target_offset, (128 - target_offset) & 0xFFFFFFFF)

            neutral_source = bytearray(640)
            neutral_target = bytearray(640)
            set_header(neutral_source, 64, 5, 448)
            set_header(neutral_target, 64, 5, 448)
            neutral_source_record = source_record[:-1] + [((64 - 232) & 0xFFFFFFFF)]
            neutral_target_record = target_record[:-1] + [((64 - 248) & 0xFFFFFFFF)]
            for i, value in enumerate(neutral_source_record):
                set_u32(neutral_source, 192 + i * 4, value)
            for i, value in enumerate(neutral_target_record):
                set_u32(neutral_target, 208 + i * 4, value)
            set_u32(neutral_source, 232, (64 - 232) & 0xFFFFFFFF)
            set_u32(neutral_target, 248, (64 - 248) & 0xFFFFFFFF)

            eye_members = []
            for index, name in enumerate(("eye1.g1e", "eye2.g1e"), 1):
                source = bytearray(512)
                target = bytearray(512)
                set_header(source, 64, 5, 384)
                set_header(target, 64, 5, 384)
                set_u32(source, 320 + index * 4, (64 - (320 + index * 4)) & 0xFFFFFFFF)
                set_u32(target, 336 + index * 4, (64 - (336 + index * 4)) & 0xFFFFFFFF)
                eye_members.append((name, source, target))

            stage87 = reports / TOOL.STAGE87_DIR
            stage87.mkdir()
            islands = [
                {"island_role": "candidate_ringlight", "normalized_path": candidate_path, "member_key": candidate_key, "member_name": "candidate.g1e", "source_start": 256, "source_end_exclusive": 300, "target_start": 272, "target_end_exclusive": 316},
                {"island_role": "neutral_control", "normalized_path": neutral_path, "member_key": neutral_key, "member_name": "neutral.g1e", "source_start": 192, "source_end_exclusive": 236, "target_start": 208, "target_end_exclusive": 252},
            ]
            write_tsv(stage87 / "SLOT_LIGHT_LOCAL_CHANGE_ISLANDS.tsv", list(islands[0]), islands)

            stage88 = reports / TOOL.STAGE88_DIR
            stage88.mkdir()
            residuals = [
                {"island_role": "candidate_ringlight", "normalized_path": candidate_path, "member_key": candidate_key, "member_name": "candidate.g1e", "source_offset": 296, "target_offset": 312},
                {"island_role": "neutral_control", "normalized_path": neutral_path, "member_key": neutral_key, "member_name": "neutral.g1e", "source_offset": 232, "target_offset": 248},
            ]
            write_tsv(stage88 / "SLOT_LIGHT_RESIDUAL_AUDIT.tsv", list(residuals[0]), residuals)

            stage89 = reports / TOOL.STAGE89_DIR
            stage89.mkdir()
            (stage89 / "SUMMARY.json").write_text(json.dumps({
                "type": "br_quartet_restoration_reflector_slot_light_reference_target_header_evidence_summary",
                "tool_version": "0.1.3",
                "sibling_G1E_G1EM_member_rows": 540,
                "residual_rows": 2,
                "reference_cluster_member_rows": 4,
                "field_relative_base_family_supported": True,
                "exact_field_start_vs_end_origin_resolved": False,
                "masked_record_template_exact_across_candidate_and_neutral": True,
                "prototype_candidate_rows": 0,
                "brightness_semantics_confirmed": False,
                "censorship_semantics_confirmed": False,
                "skipped_rows": 0,
                "policy": {"installed_game_modified": False, "render_payload_written": False, "pak_repacked": False, "core_registry_modified": False, "profile_activated": False},
            }), encoding="utf-8")
            seeds = [
                {"cluster_role": "candidate_ringlight", "normalized_path": candidate_path, "member_key": candidate_key, "member_name": "candidate.g1e", "endpoint": 128},
                {"cluster_role": "neutral_control", "normalized_path": neutral_path, "member_key": neutral_key, "member_name": "neutral.g1e", "endpoint": 64},
                {"cluster_role": "neutral_control", "normalized_path": eye_path, "member_key": eye1_key, "member_name": "eye1.g1e", "endpoint": 64},
                {"cluster_role": "neutral_control", "normalized_path": eye_path, "member_key": eye2_key, "member_name": "eye2.g1e", "endpoint": 64},
            ]
            write_tsv(stage89 / "SLOT_LIGHT_REFERENCE_CLUSTER_SEEDS.tsv", list(seeds[0]), seeds)
            audits = [{"cluster_role": row["cluster_role"], "normalized_path": row["normalized_path"], "member_key": row["member_key"], "member_name": row["member_name"]} for row in seeds]
            write_tsv(stage89 / "SLOT_LIGHT_REFERENCE_CLUSTER_AUDIT.tsv", list(audits[0]), audits)
            write_tsv(stage89 / "SLOT_LIGHT_MASKED_RECORD_TEMPLATE_COMPARISON.tsv", ["candidate_neutral_joint_masked_equal"], [{"candidate_neutral_joint_masked_equal": True}])

            containers = [
                {"normalized_path": candidate_path, "source_members": [{"comparison_key": candidate_key, "name": "candidate.g1e", "payload": bytes(candidate_source)}], "target_members": [{"comparison_key": candidate_key, "name": "candidate.g1e", "payload": bytes(candidate_target)}]},
                {"normalized_path": neutral_path, "source_members": [{"comparison_key": neutral_key, "name": "neutral.g1e", "payload": bytes(neutral_source)}], "target_members": [{"comparison_key": neutral_key, "name": "neutral.g1e", "payload": bytes(neutral_target)}]},
                {"normalized_path": eye_path, "source_members": [], "target_members": []},
                {"normalized_path": "data/x64/effect/dummies.elixir.gz", "source_members": [], "target_members": []},
            ]
            for name, source, target in eye_members:
                key = name.casefold() + "#0"
                containers[2]["source_members"].append({"comparison_key": key, "name": name, "payload": bytes(source)})
                containers[2]["target_members"].append({"comparison_key": key, "name": name, "payload": bytes(target)})
            for index in range(536):
                left, right = make_dummy_pair(f"dummy_{index:03d}.g1e")
                containers[3]["source_members"].append(left)
                containers[3]["target_members"].append(right)

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
            self.assertTrue(summary["exact_field_origin_resolved"])
            self.assertEqual(summary["resolved_field_origin"], "dword_start_relative")
            self.assertEqual(summary["dword_end_exact_header_rows"], 0)
            self.assertTrue(summary["masked_record_template_exact_across_candidate_and_neutral"])
            self.assertFalse(summary["shared_transition_candidate_specific"])
            self.assertEqual(summary["prototype_candidate_rows"], 0)
            self.assertFalse(summary["brightness_semantics_confirmed"])
            self.assertTrue((output / "SLOT_LIGHT_REFERENCE_ORIGIN_DISCRIMINATION.tsv").is_file())


if __name__ == "__main__":
    unittest.main()
