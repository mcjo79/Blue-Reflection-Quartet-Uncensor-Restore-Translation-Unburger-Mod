#!/usr/bin/env python3
from __future__ import annotations

import csv
import importlib.util
import json
import struct
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
MODULE_PATH = ROOT / "workstreams/quartet_restoration/collect_reflector_slot_light_sibling_template_expansion_evidence.py"
SPEC = importlib.util.spec_from_file_location("stage104", MODULE_PATH)
assert SPEC and SPEC.loader
TOOL = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(TOOL)

BODY_WORDS = tuple(0x11111111 * i for i in range(1, 9))
BODY = b"".join(word.to_bytes(4, "little") for word in BODY_WORDS)


def write_tsv(path: Path, fields: list[str], rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def make_payload(values: list[float], starts: list[int], *, endpoint: int = 64, size: int = 4096) -> bytes:
    payload = bytearray(size)
    count = max(1, len(values))
    words = [
        size - endpoint, 0, count, count, count, 0, 56,
        56 + 4 * (count - 1), 56 + 8 * (count - 1), 56 + 12 * (count - 1),
        0x00010000, 0, 0, 0,
    ]
    for index, word in enumerate(words):
        payload[endpoint + index * 4:endpoint + index * 4 + 4] = int(word).to_bytes(4, "little")
    for value, start in zip(values, starts):
        leaf = struct.pack("<f", value)
        payload[start:start + 4] = leaf
        payload[start + 4:start + 8] = leaf
        payload[start + 8:start + 40] = BODY
        reference_offset = start + 40
        displacement = endpoint - reference_offset
        payload[reference_offset:reference_offset + 4] = int(displacement & 0xFFFFFFFF).to_bytes(4, "little")
    return bytes(payload)


def prepare_reports(root: Path) -> tuple[Path, list[dict[str, object]], dict[tuple[str, str], tuple[list[float], list[int], list[float], list[int]]]]:
    reports = root / "reports"
    stage101 = reports / TOOL.STAGE101_DIR
    stage103 = reports / TOOL.STAGE103_DIR
    stage79 = reports / TOOL.STAGE79_DIR
    stage81 = reports / TOOL.STAGE81_DIR
    for path in (stage101, stage103, stage79, stage81):
        path.mkdir(parents=True)

    specs = [
        ("data/x64/effect/100_common.elixir.gz", "e_cmn_pup_reflect_s.g1e#0", "e_cmn_pup_reflect_s.g1e", [1, 100, 50, 150, 75], [256, 320, 384, 448, 512], [1, 100, 50, 150, 75], [256, 320, 384, 448, 512]),
        ("data/x64/effect/1000_pc00.elixir.gz", "e_pc00_eyelight_00.g1e#0", "e_PC00_eyelight_00.g1e", [1], [256], [1], [256]),
        ("data/x64/effect/1000_pc00.elixir.gz", "e_pc00_eyelight_01.g1e#0", "e_PC00_eyelight_01.g1e", [1], [256], [1], [256]),
        ("data/x64/effect/1002_pc02.elixir.gz", "e_pc02_w5_ringlight_01.g1e#0", "e_PC02_w5_ringlight_01.g1e", [30, 150, 2], [256, 320, 384], [30, 75, 75, 2], [256, 320, 384, 448]),
    ]
    pair_specs: dict[tuple[str, str], tuple[list[float], list[int], list[float], list[int]]] = {}
    family_rows: list[dict[str, object]] = []
    inventory_rows: list[dict[str, object]] = []
    for path, key, name, source_values, source_starts, target_values, target_starts in specs:
        pair_specs[(path, key)] = (source_values, source_starts, target_values, target_starts)
        for side, values, starts in (("source", source_values, source_starts), ("target", target_values, target_starts)):
            for ordinal, (value, start) in enumerate(zip(values, starts)):
                role = "other_focal_template_occurrence"
                if key == "e_pc02_w5_ringlight_01.g1e#0" and side == "source" and value == 150:
                    role = "candidate_source_150"
                elif key == "e_pc02_w5_ringlight_01.g1e#0" and side == "target" and ordinal == 1:
                    role = "candidate_first_target_75_inserted"
                elif key == "e_pc02_w5_ringlight_01.g1e#0" and side == "target" and ordinal == 2:
                    role = "candidate_second_target_75_continuing"
                family_rows.append({
                    "normalized_path": path, "member_key": key, "member_name": name, "side": side,
                    "record_start": start, "reference_offset": start + 40, "normalized_endpoint": 64,
                    "leaf0_float32": value, "leaf1_float32": value,
                    "leaf0_u32_hex": f"0x{int.from_bytes(struct.pack('<f', value), 'little'):08x}",
                    "leaf1_u32_hex": f"0x{int.from_bytes(struct.pack('<f', value), 'little'):08x}",
                    "paired_equal_bits": True, "paired_finite_floats": True, "occurrence_role": role,
                })
                inventory_rows.append({
                    "normalized_path": path, "member_key": key, "member_name": name, "side": side,
                    "reference_offset": start + 40, "record_start": start,
                    "leaf0_u32_hex": f"0x{int.from_bytes(struct.pack('<f', value), 'little'):08x}",
                    "leaf1_u32_hex": f"0x{int.from_bytes(struct.pack('<f', value), 'little'):08x}",
                    "leaf0_float32": value, "leaf1_float32": value, "leaf0_float_status": "finite", "leaf1_float_status": "finite",
                    "paired_equal_bits": True, "paired_finite_floats": True,
                    "non_leaf_context_sha256": TOOL.sha256(BODY), "normalized_endpoint": 64,
                    "context_endpoint_sha256": "x", "is_focal_context": True, "occurrence_role": role,
                })

    (stage101 / "SUMMARY.json").write_text(json.dumps({
        "type": "br_quartet_restoration_reflector_slot_light_paired_leaf_context_role_evidence_summary",
        "tool_version": "0.1.15", "reference_record_rows": 177,
        "focal_context_record_rows": 21, "focal_context_values": ["1", "2", "30", "50", "75", "100", "150"],
        "technical_leaf_storage_class_resolved": True,
        "technical_leaf_storage_class": "paired_equal_finite_float_payload_leaves",
        "technical_leaf_domain_semantics_resolved": False, "prototype_candidate_rows": 0, "skipped_rows": 0,
    }), encoding="utf-8")
    family_fields = list(family_rows[0].keys())
    write_tsv(stage101 / "SLOT_LIGHT_FOCAL_EQUAL_FLOAT_FAMILY.tsv", family_fields, family_rows)
    inventory_fields = list(inventory_rows[0].keys())
    write_tsv(stage101 / "SLOT_LIGHT_PAIRED_LEAF_CONTEXT_INVENTORY.tsv", inventory_fields, inventory_rows)

    (stage103 / "SUMMARY.json").write_text(json.dumps({
        "type": "br_quartet_restoration_reflector_slot_light_paired_leaf_member_role_callsite_evidence_summary",
        "tool_version": "0.1.17", "focal_record_rows": 21,
        "exact_effect_container_callsite_rows": 0, "exact_transformation_event_callsite_rows": 0,
        "exact_name_callsite_binding_resolved": False, "technical_leaf_domain_semantics_resolved": False,
        "prototype_candidate_rows": 0, "skipped_rows": 0,
    }), encoding="utf-8")

    (stage79 / "SUMMARY.json").write_text(json.dumps({
        "type": "br_quartet_restoration_reflector_character_slot_render_member_evidence_summary",
        "tool_version": "0.0.92", "character_slot_rows": 15,
    }), encoding="utf-8")
    slot_fields = ["character_slot", "asset_role", "family_key", "normalized_path", "member_name", "member_key", "candidate_id"]
    role_rows = [
        {"character_slot": "", "asset_role": "neutral_pupil_reflect_control", "family_key": "neutral", "normalized_path": specs[0][0], "member_name": specs[0][2], "member_key": specs[0][1], "candidate_id": "c0"},
        {"character_slot": "PC00", "asset_role": "eyelight", "family_key": "eyelight", "normalized_path": specs[1][0], "member_name": specs[1][2], "member_key": specs[1][1], "candidate_id": "c1"},
        {"character_slot": "PC00", "asset_role": "eyelight", "family_key": "eyelight", "normalized_path": specs[2][0], "member_name": specs[2][2], "member_key": specs[2][1], "candidate_id": "c1"},
        {"character_slot": "PC02", "asset_role": "ringlight", "family_key": "ringlight", "normalized_path": specs[3][0], "member_name": specs[3][2], "member_key": specs[3][1], "candidate_id": "c2"},
    ]
    for index in range(18):
        role_rows.append({
            "character_slot": f"PC{index % 15:02d}", "asset_role": "ringlight", "family_key": "dummy",
            "normalized_path": f"data/x64/effect/dummy_{index % 4}.elixir.gz", "member_name": f"dummy_ringlight_{index}.g1e",
            "member_key": f"dummy_ringlight_{index}.g1e#0", "candidate_id": f"d{index % 4}",
        })
    write_tsv(stage79 / "REFLECTOR_SLOT_RENDER_MEMBERS.tsv", slot_fields, role_rows)

    (stage81 / "SUMMARY.json").write_text(json.dumps({
        "type": "br_quartet_restoration_reflector_ringlight_control_callsite_evidence_summary",
        "tool_version": "0.0.95", "skipped_rows": 0,
    }), encoding="utf-8")
    return reports, role_rows, pair_specs


def make_containers(pair_specs: dict[tuple[str, str], tuple[list[float], list[int], list[float], list[int]]], *, omit_known: bool = False) -> list[dict[str, object]]:
    members: list[tuple[str, str, str, bytes, bytes]] = []
    names = {
        "e_cmn_pup_reflect_s.g1e#0": "e_cmn_pup_reflect_s.g1e",
        "e_pc00_eyelight_00.g1e#0": "e_PC00_eyelight_00.g1e",
        "e_pc00_eyelight_01.g1e#0": "e_PC00_eyelight_01.g1e",
        "e_pc02_w5_ringlight_01.g1e#0": "e_PC02_w5_ringlight_01.g1e",
    }
    parent_paths = sorted({path for path, _key in pair_specs})
    assert len(parent_paths) == 3
    # Add a fourth bounded parent path to mirror the real corpus.
    parent_paths.append("data/x64/effect/1001_pc01.elixir.gz")
    for (path, key), (sv, ss, tv, ts) in pair_specs.items():
        source = make_payload(sv, ss)
        target = make_payload(tv, ts)
        if omit_known and key == "e_pc00_eyelight_00.g1e#0":
            source = bytes(len(source))
        members.append((path, key, names[key], source, target))
    additional_path = parent_paths[0]
    members.append((additional_path, "extra_neutral.g1e#0", "extra_neutral.g1e", make_payload([200], [256]), make_payload([200], [256])))
    filler_needed = 540 - len(members)
    for index in range(filler_needed):
        path = parent_paths[index % 4]
        key = f"filler_{index}.g1e#0"
        members.append((path, key, f"filler_{index}.g1e", bytes(256), bytes(256)))

    grouped: dict[str, list[tuple[str, str, str, bytes, bytes]]] = {path: [] for path in parent_paths}
    for row in members:
        grouped[row[0]].append(row)
    containers: list[dict[str, object]] = []
    for container_index, (path, rows) in enumerate(sorted(grouped.items())):
        source_members = []
        target_members = []
        for _path, key, name, source, target in rows:
            source_members.append({"comparison_key": key, "name": name, "payload": source})
            target_members.append({"comparison_key": key, "name": name, "payload": target})
        containers.append({
            "candidate_id": f"container{container_index}",
            "normalized_path": path,
            "scope_rows": [], "source_members": source_members, "target_members": target_members,
        })
    return containers


class Stage104Tests(unittest.TestCase):
    def test_expands_exact_template_and_preserves_semantic_block(self) -> None:
        with tempfile.TemporaryDirectory(prefix="stage104-test-") as temp_name:
            reports, _roles, pair_specs = prepare_reports(Path(temp_name))
            containers = make_containers(pair_specs)

            def loader(**_kwargs):
                return containers, []

            output, archive, summary = TOOL.build_report(ROOT, create_archive=False, report_root=reports, container_loader=loader)
            self.assertIsNone(archive)
            self.assertEqual(summary["sibling_G1E_G1EM_pair_rows"], 540)
            self.assertEqual(summary["known_stage101_occurrence_rows"], 21)
            self.assertEqual(summary["additional_sibling_occurrence_rows"], 2)
            self.assertEqual(summary["additional_sibling_member_rows"], 1)
            self.assertIn("200", summary["new_paired_values_outside_stage101_domain"])
            self.assertFalse(summary["technical_leaf_domain_semantics_resolved"])
            self.assertEqual(summary["prototype_candidate_rows"], 0)
            self.assertTrue((output / "SLOT_LIGHT_SIBLING_TEMPLATE_ADDITIONAL_OCCURRENCES.tsv").is_file())

    def test_fails_if_known_stage101_occurrence_is_not_rediscovered(self) -> None:
        with tempfile.TemporaryDirectory(prefix="stage104-negative-") as temp_name:
            reports, _roles, pair_specs = prepare_reports(Path(temp_name))
            containers = make_containers(pair_specs, omit_known=True)

            def loader(**_kwargs):
                return containers, []

            with self.assertRaises(TOOL.Stage104Error):
                TOOL.build_report(ROOT, create_archive=False, report_root=reports, container_loader=loader)


if __name__ == "__main__":
    unittest.main()
