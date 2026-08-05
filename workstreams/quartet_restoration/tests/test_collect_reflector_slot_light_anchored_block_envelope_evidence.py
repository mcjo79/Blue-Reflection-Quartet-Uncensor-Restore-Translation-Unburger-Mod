from __future__ import annotations

import csv
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
TOOL_PATH = ROOT / "workstreams/quartet_restoration/collect_reflector_slot_light_anchored_block_envelope_evidence.py"
SPEC = importlib.util.spec_from_file_location("stage95_tested", TOOL_PATH)
assert SPEC and SPEC.loader
TOOL = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(TOOL)


def write_tsv(path: Path, fields: list[str], rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fields})


class Stage95Tests(unittest.TestCase):
    def test_anchored_block_envelope_keeps_duplicate_identity_unresolved(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_name:
            temp = Path(temporary_name)
            reports = temp / "reports"
            stage79 = reports / TOOL.STAGE79_DIR
            stage94 = reports / TOOL.STAGE94_DIR
            stage79.mkdir(parents=True)
            stage94.mkdir(parents=True)

            (stage79 / "SUMMARY.json").write_text(json.dumps({
                "type": "br_quartet_restoration_reflector_character_slot_render_member_evidence_summary",
                "tool_version": "0.0.92",
                "character_slot_rows": 15,
            }), encoding="utf-8")
            render_rows = [
                {
                    "candidate_id": f"c{index}",
                    "normalized_path": f"data/x64/effect/container{index % 4}.elixir.gz",
                    "member_key": f"m{index}.g1e#0",
                    "asset_role": "ringlight" if index < 19 else "eyelight",
                }
                for index in range(21)
            ]
            write_tsv(stage79 / "REFLECTOR_SLOT_RENDER_MEMBERS.tsv", ["candidate_id", "normalized_path", "member_key", "asset_role"], render_rows)

            (stage94 / "SUMMARY.json").write_text(json.dumps({
                "type": "br_quartet_restoration_reflector_slot_light_pre_record_anchor_header_evidence_summary",
                "tool_version": "0.1.8",
                "sibling_G1E_G1EM_member_rows": 540,
                "focal_occurrence_rows": 21,
                "pre_record_dword_rows": 567,
                "dominant_binding_rows": 13,
                "pre_record_anchor_geometry_confirmed": True,
                "candidate_target_occurrence_identity_resolved": False,
                "pre_record_header_role_resolved": False,
                "prototype_candidate_rows": 0,
                "brightness_semantics_confirmed": False,
                "censorship_semantics_confirmed": False,
                "skipped_rows": 0,
            }), encoding="utf-8")

            candidate_path = "data/x64/effect/container0.elixir.gz"
            candidate_key = "e_pc02_w5_ringlight_01.g1e#0"
            neutral_path = "data/x64/effect/container1.elixir.gz"
            neutral_key = "e_cmn_pup_reflect_s.g1e#0"
            eye0_path = "data/x64/effect/container2.elixir.gz"
            eye0_key = "e_pc00_eyelight_00.g1e#0"
            eye1_path = "data/x64/effect/container3.elixir.gz"
            eye1_key = "e_pc00_eyelight_01.g1e#0"

            candidate_source = [(1000, "equal_float_30"), (1608, "equal_float_150"), (2216, "equal_float_2")]
            candidate_target = [(1016, "equal_float_30"), (1624, "equal_float_75"), (2232, "equal_float_75"), (2840, "equal_float_2")]
            neutral = [(400, "equal_float_1", 560), (960, "equal_float_100", 640), (1600, "equal_float_50", 640), (2240, "equal_float_150", 640), (2880, "equal_float_75", 640)]
            eyes = [(320, "equal_float_1", 560)]

            audit_fields = [
                "cluster_role", "normalized_path", "member_key", "member_name", "side", "reference_index", "variant_label",
                "endpoint", "anchor", "record_start", "reference_offset",
            ]
            audit_rows: list[dict[str, object]] = []
            candidate_sequence: list[dict[str, object]] = []

            def add_rows(role: str, path: str, key: str, side: str, values: list[tuple[int, str, int]]) -> None:
                for index, (anchor, variant, _span) in enumerate(values):
                    record = anchor + 108
                    row = {
                        "cluster_role": role, "normalized_path": path, "member_key": key, "member_name": key.split("#")[0],
                        "side": side, "reference_index": index, "variant_label": variant, "endpoint": 192,
                        "anchor": anchor, "record_start": record, "reference_offset": record + 40,
                    }
                    audit_rows.append(row)
                    if role == "candidate_ringlight":
                        candidate_sequence.append(row)

            add_rows("candidate_ringlight", candidate_path, candidate_key, "source", [(a, v, 608) for a, v in candidate_source])
            add_rows("candidate_ringlight", candidate_path, candidate_key, "target", [(a, v, 608) for a, v in candidate_target])
            add_rows("neutral_control", neutral_path, neutral_key, "source", neutral)
            add_rows("neutral_control", neutral_path, neutral_key, "target", neutral)
            add_rows("neutral_control", eye0_path, eye0_key, "source", eyes)
            add_rows("neutral_control", eye0_path, eye0_key, "target", eyes)
            add_rows("neutral_control", eye1_path, eye1_key, "source", eyes)
            add_rows("neutral_control", eye1_path, eye1_key, "target", eyes)
            self.assertEqual(len(audit_rows), 21)
            self.assertEqual(len(candidate_sequence), 7)
            write_tsv(stage94 / "SLOT_LIGHT_PRE_RECORD_ANCHOR_AUDIT.tsv", audit_fields, audit_rows)
            write_tsv(stage94 / "SLOT_LIGHT_CANDIDATE_PRE_RECORD_SEQUENCE.tsv", audit_fields, candidate_sequence)

            def put_u32(payload: bytearray, offset: int, value: int) -> None:
                payload[offset:offset + 4] = int(value & 0xFFFFFFFF).to_bytes(4, "little")

            def build_block(payload: bytearray, anchor: int, span: int, variant: str, endpoint: int, marker: int) -> None:
                put_u32(payload, anchor, span)
                put_u32(payload, anchor + 4, marker)
                put_u32(payload, anchor + 8, 0)
                for relative in range(3, 27):
                    put_u32(payload, anchor + relative * 4, 0x3F800000)
                record = anchor + 108
                value = int(variant.rsplit("_", 1)[1])
                put_u32(payload, record, value)
                put_u32(payload, record + 4, value)
                for relative in range(2, 10):
                    put_u32(payload, record + relative * 4, 0x40000000 + relative)
                put_u32(payload, record + 40, endpoint - (record + 40))
                # A deterministic trailer.  The two target 75 blocks are the same after relocation normalization.
                for offset in range(record + 44, anchor + span, 4):
                    put_u32(payload, offset, 0xABC00000 + ((offset - anchor) // 4))

            candidate_source_payload = bytearray(4096)
            candidate_target_payload = bytearray(4096)
            for anchor, variant in candidate_source:
                build_block(candidate_source_payload, anchor, 608, variant, 192, 497 if variant != "equal_float_30" else 433)
            for anchor, variant in candidate_target:
                build_block(candidate_target_payload, anchor, 608, variant, 192, 497 if variant != "equal_float_30" else 433)

            neutral_source_payload = bytearray(4096)
            neutral_target_payload = bytearray(4096)
            for anchor, variant, span in neutral:
                build_block(neutral_source_payload, anchor, span, variant, 192, 496 if variant == "equal_float_1" else 497)
                build_block(neutral_target_payload, anchor, span, variant, 192, 496 if variant == "equal_float_1" else 497)
            eye0_source = bytearray(1024)
            eye0_target = bytearray(1024)
            eye1_source = bytearray(1024)
            eye1_target = bytearray(1024)
            for payload in (eye0_source, eye0_target, eye1_source, eye1_target):
                build_block(payload, 320, 560, "equal_float_1", 192, 496)

            def member(name: str, key: str, payload: bytes) -> dict[str, object]:
                return {"name": name, "comparison_key": key, "payload": payload}

            focal_by_container = {
                0: (candidate_key, bytes(candidate_source_payload), bytes(candidate_target_payload)),
                1: (neutral_key, bytes(neutral_source_payload), bytes(neutral_target_payload)),
                2: (eye0_key, bytes(eye0_source), bytes(eye0_target)),
                3: (eye1_key, bytes(eye1_source), bytes(eye1_target)),
            }
            containers = []
            total = 0
            for container_index in range(4):
                key, source_payload, target_payload = focal_by_container[container_index]
                source_members = [member(key.split("#")[0], key, source_payload)]
                target_members = [member(key.split("#")[0], key, target_payload)]
                while len(source_members) < 135:
                    dummy_key = f"dummy_{container_index}_{total}.g1e#0"
                    source_members.append(member(dummy_key.split("#")[0], dummy_key, bytes(256)))
                    target_members.append(member(dummy_key.split("#")[0], dummy_key, bytes(256)))
                    total += 1
                containers.append({
                    "normalized_path": f"data/x64/effect/container{container_index}.elixir.gz",
                    "source_members": source_members,
                    "target_members": target_members,
                })
            self.assertEqual(sum(len(container["source_members"]) for container in containers), 540)

            output, archive, summary = TOOL.build_report(
                ROOT,
                create_archive=False,
                report_root=reports,
                workspace_root=temp / "workspace",
                container_loader=lambda **_kwargs: (containers, []),
            )
            self.assertIsNone(archive)
            self.assertEqual(summary["focal_occurrence_rows"], 21)
            self.assertEqual(summary["nonterminal_focal_occurrence_rows"], 13)
            self.assertEqual(summary["nonterminal_declared_span_chain_exact_rows"], 13)
            self.assertTrue(summary["anchored_block_span_field_confirmed"])
            self.assertTrue(summary["candidate_target_duplicate_75_normalized_full_blocks_exact"])
            self.assertTrue(summary["candidate_source_150_to_target_75_normalized_diff_equal"])
            self.assertFalse(summary["candidate_target_occurrence_identity_resolved"])
            self.assertEqual(summary["prototype_candidate_rows"], 0)
            self.assertEqual(summary["skipped_rows"], 0)
            self.assertTrue((output / "SLOT_LIGHT_ANCHORED_BLOCK_PAIRWISE_COMPARISON.tsv").is_file())
            self.assertTrue((output / "SLOT_LIGHT_ANCHORED_BLOCK_IDENTITY_DECISION.tsv").is_file())


if __name__ == "__main__":
    unittest.main()
