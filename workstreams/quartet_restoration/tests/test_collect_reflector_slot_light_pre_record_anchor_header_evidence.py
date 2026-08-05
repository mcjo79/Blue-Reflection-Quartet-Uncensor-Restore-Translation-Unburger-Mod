from __future__ import annotations

import csv
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
TOOL_PATH = ROOT / "workstreams/quartet_restoration/collect_reflector_slot_light_pre_record_anchor_header_evidence.py"
SPEC = importlib.util.spec_from_file_location("stage94_tested", TOOL_PATH)
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


class Stage94Tests(unittest.TestCase):
    def test_pre_record_anchor_audit(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_name:
            temp = Path(temporary_name)
            reports = temp / "reports"
            stage79 = reports / TOOL.STAGE79_DIR
            stage91 = reports / TOOL.STAGE91_DIR
            stage92 = reports / TOOL.STAGE92_DIR
            stage93 = reports / TOOL.STAGE93_DIR
            for path in (stage79, stage91, stage92, stage93):
                path.mkdir(parents=True)

            (stage79 / "SUMMARY.json").write_text(json.dumps({
                "type": "br_quartet_restoration_reflector_character_slot_render_member_evidence_summary",
                "tool_version": "0.0.92",
                "character_slot_rows": 15,
            }), encoding="utf-8")
            render_fields = ["candidate_id", "normalized_path", "member_key", "asset_role"]
            render_rows = []
            for index in range(21):
                render_rows.append({
                    "candidate_id": f"c{index}",
                    "normalized_path": f"data/x64/effect/container{index % 4}.elixir.gz",
                    "member_key": f"m{index}.g1e#0",
                    "asset_role": "ringlight" if index < 19 else "eyelight",
                })
            write_tsv(stage79 / "REFLECTOR_SLOT_RENDER_MEMBERS.tsv", render_fields, render_rows)

            (stage91 / "SUMMARY.json").write_text(json.dumps({
                "type": "br_quartet_restoration_reflector_slot_light_section_cardinality_record_role_evidence_summary",
                "tool_version": "0.1.5",
                "reference_record_rows": 177,
                "section_table_entry_rows": 51,
                "resolved_reference_origin": "dword_start_relative",
                "prototype_candidate_rows": 0,
                "brightness_semantics_confirmed": False,
                "censorship_semantics_confirmed": False,
                "skipped_rows": 0,
            }), encoding="utf-8")
            candidate_path = "data/x64/effect/container0.elixir.gz"
            candidate_key = "e_pc02_w5_ringlight_01.g1e#0"
            neutral_path = "data/x64/effect/container1.elixir.gz"
            neutral_key = "e_cmn_pup_reflect_s.g1e#0"
            cardinality_fields = ["cluster_role", "normalized_path", "member_key", "member_name", "side", "endpoint", "section_count"]
            write_tsv(stage91 / "SLOT_LIGHT_SECTION_CARDINALITY.tsv", cardinality_fields, [
                {"cluster_role": "candidate_ringlight", "normalized_path": candidate_path, "member_key": candidate_key, "member_name": candidate_key.split("#")[0], "side": "source", "endpoint": 192, "section_count": 3},
                {"cluster_role": "candidate_ringlight", "normalized_path": candidate_path, "member_key": candidate_key, "member_name": candidate_key.split("#")[0], "side": "target", "endpoint": 192, "section_count": 4},
                {"cluster_role": "neutral_control", "normalized_path": neutral_path, "member_key": neutral_key, "member_name": neutral_key.split("#")[0], "side": "source", "endpoint": 192, "section_count": 5},
                {"cluster_role": "neutral_control", "normalized_path": neutral_path, "member_key": neutral_key, "member_name": neutral_key.split("#")[0], "side": "target", "endpoint": 192, "section_count": 5},
            ])

            (stage92 / "SUMMARY.json").write_text(json.dumps({
                "type": "br_quartet_restoration_reflector_slot_light_record_occurrence_identity_evidence_summary",
                "tool_version": "0.1.6",
                "reference_record_rows": 177,
                "neutral_focal_variants_coexist_unchanged": True,
                "candidate_target_occurrence_identity_resolved": False,
                "prototype_candidate_rows": 0,
                "skipped_rows": 0,
            }), encoding="utf-8")
            occurrence_fields = [
                "cluster_role", "normalized_path", "member_key", "member_name", "side", "reference_index",
                "reference_offset", "record_start", "variant_label", "is_focal_family",
            ]
            occurrences: list[dict[str, object]] = []

            candidate_source = [(1024, "equal_float_30"), (1632, "equal_float_150"), (2240, "equal_float_2")]
            candidate_target = [(1040, "equal_float_30"), (1648, "equal_float_75"), (2256, "equal_float_75"), (2864, "equal_float_2")]
            neutral = [(444, "equal_float_1"), (1004, "equal_float_100"), (1644, "equal_float_50"), (2284, "equal_float_150"), (2924, "equal_float_75")]
            for side, values in (("source", candidate_source), ("target", candidate_target)):
                for index, (start, variant) in enumerate(values):
                    occurrences.append({
                        "cluster_role": "candidate_ringlight", "normalized_path": candidate_path, "member_key": candidate_key,
                        "member_name": candidate_key.split("#")[0], "side": side, "reference_index": index,
                        "reference_offset": start + 40, "record_start": start, "variant_label": variant, "is_focal_family": True,
                    })
            for side in ("source", "target"):
                for index, (start, variant) in enumerate(neutral):
                    occurrences.append({
                        "cluster_role": "neutral_control", "normalized_path": neutral_path, "member_key": neutral_key,
                        "member_name": neutral_key.split("#")[0], "side": side, "reference_index": index,
                        "reference_offset": start + 40, "record_start": start, "variant_label": variant, "is_focal_family": True,
                    })
            for index in range(160):
                occurrences.append({
                    "cluster_role": "other", "normalized_path": "data/x64/effect/container2.elixir.gz", "member_key": f"dummy{index}.g1e#0",
                    "member_name": f"dummy{index}.g1e", "side": "source" if index % 2 == 0 else "target",
                    "reference_index": index, "reference_offset": 40, "record_start": 0, "variant_label": f"other_{index}", "is_focal_family": False,
                })
            self.assertEqual(len(occurrences), 177)
            write_tsv(stage92 / "SLOT_LIGHT_RECORD_OCCURRENCE_INVENTORY.tsv", occurrence_fields, occurrences)

            (stage93 / "SUMMARY.json").write_text(json.dumps({
                "type": "br_quartet_restoration_reflector_slot_light_section_table_record_binding_evidence_summary",
                "tool_version": "0.1.7",
                "reference_record_rows": 177,
                "section_table_entry_rows": 51,
                "dominant_record_relative_bytes": -108,
                "dominant_record_relative_binding_rows": 13,
                "dominant_record_relative_offset_unique": True,
                "target_table_binding_bulk_reencoding_supported": True,
                "candidate_target_occurrence_identity_resolved": False,
                "prototype_candidate_rows": 0,
                "brightness_semantics_confirmed": False,
                "censorship_semantics_confirmed": False,
                "skipped_rows": 0,
            }), encoding="utf-8")
            binding_fields = [
                "normalized_path", "member_key", "member_name", "side", "table_index", "entry_index", "entry_absolute_offset",
                "entry_i32", "signed_anchor", "best_record_start", "exact_dominant_binding",
            ]
            bindings: list[dict[str, object]] = []
            for index, (start, _variant) in enumerate(candidate_target[:3]):
                entry_offset = 200 + index * 4
                anchor = start - 108
                bindings.append({
                    "normalized_path": candidate_path, "member_key": candidate_key, "member_name": candidate_key.split("#")[0],
                    "side": "target", "table_index": 3, "entry_index": index, "entry_absolute_offset": entry_offset,
                    "entry_i32": anchor - entry_offset, "signed_anchor": anchor, "best_record_start": start, "exact_dominant_binding": True,
                })
            for side in ("source", "target"):
                for index, (start, _variant) in enumerate(neutral):
                    entry_offset = 280 + index * 4
                    anchor = start - 108
                    bindings.append({
                        "normalized_path": neutral_path, "member_key": neutral_key, "member_name": neutral_key.split("#")[0],
                        "side": side, "table_index": 3, "entry_index": index, "entry_absolute_offset": entry_offset,
                        "entry_i32": anchor - entry_offset, "signed_anchor": anchor, "best_record_start": start, "exact_dominant_binding": True,
                    })
            self.assertEqual(len(bindings), 13)
            write_tsv(stage93 / "SLOT_LIGHT_SECTION_TABLE_RECORD_BINDING_CANDIDATES.tsv", binding_fields, bindings)
            write_tsv(stage93 / "SLOT_LIGHT_TABLE_BINDING_IDENTITY_DECISION.tsv", ["occurrence_identity_resolved"], [{"occurrence_identity_resolved": False}])

            def preamble(payload: bytearray, start: int, endpoint: int, marker: int) -> None:
                anchor = start - 108
                words = [0x10000000 + i for i in range(27)]
                words[0] = marker
                for index, target in ((2, start), (3, start + 40), (4, endpoint)):
                    field_offset = anchor + index * 4
                    words[index] = (target - field_offset) & 0xFFFFFFFF
                for index, value in enumerate(words):
                    payload[anchor + index * 4:anchor + index * 4 + 4] = value.to_bytes(4, "little")
                payload[start + 40:start + 44] = ((endpoint - (start + 40)) & 0xFFFFFFFF).to_bytes(4, "little")

            candidate_source_payload = bytearray(4096)
            candidate_target_payload = bytearray(4096)
            for index, (start, _variant) in enumerate(candidate_source):
                preamble(candidate_source_payload, start, 192, 0xAA00 + index)
            for index, (start, _variant) in enumerate(candidate_target):
                preamble(candidate_target_payload, start, 192, 0xBB00 + index)
            neutral_source_payload = bytearray(4096)
            neutral_target_payload = bytearray(4096)
            for index, (start, _variant) in enumerate(neutral):
                preamble(neutral_source_payload, start, 192, 0xCC00 + index)
                preamble(neutral_target_payload, start, 192, 0xCC00 + index)

            def member(name: str, key: str, payload: bytes) -> dict[str, object]:
                return {"name": name, "comparison_key": key, "payload": payload}

            containers = []
            total = 0
            for container_index in range(4):
                source_members = []
                target_members = []
                if container_index == 0:
                    source_members.append(member(candidate_key.split("#")[0], candidate_key, bytes(candidate_source_payload)))
                    target_members.append(member(candidate_key.split("#")[0], candidate_key, bytes(candidate_target_payload)))
                elif container_index == 1:
                    source_members.append(member(neutral_key.split("#")[0], neutral_key, bytes(neutral_source_payload)))
                    target_members.append(member(neutral_key.split("#")[0], neutral_key, bytes(neutral_target_payload)))
                while len(source_members) < 135:
                    dummy_index = total
                    key = f"dummy_{container_index}_{dummy_index}.g1e#0"
                    data = bytes(256)
                    source_members.append(member(key.split("#")[0], key, data))
                    target_members.append(member(key.split("#")[0], key, data))
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
            self.assertEqual(summary["sibling_G1E_G1EM_member_rows"], 540)
            self.assertEqual(summary["focal_occurrence_rows"], 17)
            self.assertEqual(summary["pre_record_dword_rows"], 17 * 27)
            self.assertEqual(summary["dominant_binding_rows"], 13)
            self.assertEqual(summary["dominant_binding_anchor_exact_rows"], 13)
            self.assertTrue(summary["pre_record_anchor_geometry_confirmed"])
            self.assertEqual(summary["candidate_target_duplicate_75_rows"], 2)
            self.assertTrue(summary["candidate_target_duplicate_75_raw_preambles_distinct"])
            self.assertFalse(summary["candidate_target_occurrence_identity_resolved"])
            self.assertFalse(summary["pre_record_header_role_resolved"])
            self.assertEqual(summary["prototype_candidate_rows"], 0)
            self.assertTrue((output / "SLOT_LIGHT_PRE_RECORD_ANCHOR_DWORDS.tsv").is_file())
            self.assertTrue((output / "SLOT_LIGHT_PRE_RECORD_HEADER_DECISION.tsv").is_file())


if __name__ == "__main__":
    unittest.main()
