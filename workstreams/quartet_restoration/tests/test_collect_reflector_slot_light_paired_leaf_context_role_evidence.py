from __future__ import annotations

import csv
import importlib.util
import json
import struct
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "workstreams/quartet_restoration/collect_reflector_slot_light_paired_leaf_context_role_evidence.py"
SPEC = importlib.util.spec_from_file_location("stage101_tool", SCRIPT)
assert SPEC and SPEC.loader
TOOL = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(TOOL)


def write_tsv(path: Path, fields: list[str], rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def f32_bits(value: float) -> int:
    return int.from_bytes(struct.pack("<f", value), "little")


def prepare_reports(root: Path, *, corrupt_focal_pair: bool = False) -> Path:
    reports = root / "reports"
    stage91 = reports / TOOL.STAGE91_DIR
    stage100 = reports / TOOL.STAGE100_DIR
    stage91.mkdir(parents=True)
    stage100.mkdir(parents=True)

    (stage91 / "SUMMARY.json").write_text(json.dumps({
        "type": "br_quartet_restoration_reflector_slot_light_section_cardinality_record_role_evidence_summary",
        "tool_version": "0.1.5", "reference_record_rows": 177,
        "reference_record_dword_rows": 1947, "skipped_rows": 0,
    }), encoding="utf-8")

    focal_specs = [
        ("data/x64/effect/1000_pc00.elixir.gz", "e_pc00_eyelight_00.g1e#0", "e_PC00_eyelight_00.g1e", "source", 412, 452, 1.0, 192),
        ("data/x64/effect/1000_pc00.elixir.gz", "e_pc00_eyelight_00.g1e#0", "e_PC00_eyelight_00.g1e", "target", 412, 452, 1.0, 192),
        ("data/x64/effect/1000_pc00.elixir.gz", "e_pc00_eyelight_01.g1e#0", "e_PC00_eyelight_01.g1e", "source", 412, 452, 1.0, 192),
        ("data/x64/effect/1000_pc00.elixir.gz", "e_pc00_eyelight_01.g1e#0", "e_PC00_eyelight_01.g1e", "target", 412, 452, 1.0, 192),
        ("data/x64/effect/1002_pc02.elixir.gz", "e_pc02_w5_ringlight_01.g1e#0", "e_PC02_w5_ringlight_01.g1e", "source", 20512, 20552, 30.0, 20276),
        ("data/x64/effect/1002_pc02.elixir.gz", "e_pc02_w5_ringlight_01.g1e#0", "e_PC02_w5_ringlight_01.g1e", "source", 21120, 21160, 150.0, 20276),
        ("data/x64/effect/1002_pc02.elixir.gz", "e_pc02_w5_ringlight_01.g1e#0", "e_PC02_w5_ringlight_01.g1e", "source", 21728, 21768, 2.0, 20276),
        ("data/x64/effect/1002_pc02.elixir.gz", "e_pc02_w5_ringlight_01.g1e#0", "e_PC02_w5_ringlight_01.g1e", "target", 20528, 20568, 30.0, 20276),
        ("data/x64/effect/1002_pc02.elixir.gz", "e_pc02_w5_ringlight_01.g1e#0", "e_PC02_w5_ringlight_01.g1e", "target", 21136, 21176, 75.0, 20276),
        ("data/x64/effect/1002_pc02.elixir.gz", "e_pc02_w5_ringlight_01.g1e#0", "e_PC02_w5_ringlight_01.g1e", "target", 21744, 21784, 75.0, 20276),
        ("data/x64/effect/1002_pc02.elixir.gz", "e_pc02_w5_ringlight_01.g1e#0", "e_PC02_w5_ringlight_01.g1e", "target", 22352, 22392, 2.0, 20276),
        ("data/x64/effect/100_common.elixir.gz", "e_cmn_pup_reflect_s.g1e#0", "e_cmn_pup_reflect_s.g1e", "source", 444, 484, 1.0, 192),
        ("data/x64/effect/100_common.elixir.gz", "e_cmn_pup_reflect_s.g1e#0", "e_cmn_pup_reflect_s.g1e", "source", 1004, 1044, 100.0, 192),
        ("data/x64/effect/100_common.elixir.gz", "e_cmn_pup_reflect_s.g1e#0", "e_cmn_pup_reflect_s.g1e", "source", 1644, 1684, 50.0, 192),
        ("data/x64/effect/100_common.elixir.gz", "e_cmn_pup_reflect_s.g1e#0", "e_cmn_pup_reflect_s.g1e", "source", 2284, 2324, 150.0, 192),
        ("data/x64/effect/100_common.elixir.gz", "e_cmn_pup_reflect_s.g1e#0", "e_cmn_pup_reflect_s.g1e", "source", 2924, 2964, 75.0, 192),
        ("data/x64/effect/100_common.elixir.gz", "e_cmn_pup_reflect_s.g1e#0", "e_cmn_pup_reflect_s.g1e", "target", 444, 484, 1.0, 192),
        ("data/x64/effect/100_common.elixir.gz", "e_cmn_pup_reflect_s.g1e#0", "e_cmn_pup_reflect_s.g1e", "target", 1004, 1044, 100.0, 192),
        ("data/x64/effect/100_common.elixir.gz", "e_cmn_pup_reflect_s.g1e#0", "e_cmn_pup_reflect_s.g1e", "target", 1644, 1684, 50.0, 192),
        ("data/x64/effect/100_common.elixir.gz", "e_cmn_pup_reflect_s.g1e#0", "e_cmn_pup_reflect_s.g1e", "target", 2284, 2324, 150.0, 192),
        ("data/x64/effect/100_common.elixir.gz", "e_cmn_pup_reflect_s.g1e#0", "e_cmn_pup_reflect_s.g1e", "target", 2924, 2964, 75.0, 192),
    ]
    records = list(focal_specs)
    for index in range(156):
        start = 40000 + index * 64
        records.append(("dummy/path", f"dummy_{index}.g1e#0", f"dummy_{index}.g1e", "source" if index % 2 == 0 else "target", start, start + 40, 0.0, 0))
    assert len(records) == 177

    fields = ["normalized_path", "member_key", "member_name", "side", "reference_offset", "record_start", "relative_dword", "is_relocation_dword", "u32_hex", "i32", "float32", "float_status"]
    rows: list[dict[str, object]] = []
    focal_context = [0x00000000, 0x00000001, 0x00000000, 0x3F800000, 0x00000000, 0x00000000, 0x00000000, 0x00000000]
    for record_index, (path, key, name, side, start, reference, value, endpoint) in enumerate(records):
        leaf0 = f32_bits(value)
        leaf1 = leaf0
        if record_index >= 21 and record_index - 21 >= 32:
            leaf1 = f32_bits(1.0)
        if corrupt_focal_pair and record_index == 0:
            leaf1 = f32_bits(2.0)
        context = focal_context if record_index < 21 else [record_index, 2, 3, 4, 5, 6, 7, 8]
        rel = endpoint - reference
        values = [leaf0, leaf1, *context, rel & 0xFFFFFFFF]
        for dword, raw in enumerate(values):
            signed = raw - (1 << 32) if raw & 0x80000000 else raw
            if dword in (0, 1):
                ftext = str(int(value)) if value.is_integer() else str(value)
                status = "finite" if value else "zero"
            else:
                ftext = "0"
                status = "zero"
            rows.append({
                "normalized_path": path, "member_key": key, "member_name": name, "side": side,
                "reference_offset": reference, "record_start": start, "relative_dword": dword,
                "is_relocation_dword": dword == 10, "u32_hex": f"0x{raw:08x}", "i32": signed,
                "float32": ftext, "float_status": status,
            })
    write_tsv(stage91 / "SLOT_LIGHT_REFERENCE_RECORD_DWORDS.tsv", fields, rows)

    (stage100 / "SUMMARY.json").write_text(json.dumps({
        "type": "br_quartet_restoration_reflector_slot_light_continuing_record_transition_partition_evidence_summary",
        "tool_version": "0.1.14",
        "status": "occurrence_identity_resolved_four_transitions_partitioned_two_numeric_leaves_remain_semantically_unresolved",
        "reference_record_rows": 177, "paired_equal_record_rows": 53,
        "paired_75_or_150_occurrence_rows": 7, "unresolved_paired_numeric_leaf_rows": 2,
        "candidate_target_occurrence_identity_resolved": True,
        "candidate_target_occurrence_identity": "second_target_75",
        "inserted_target_occurrence": "first_target_75",
        "technical_leaf_semantics_resolved": False,
        "prototype_candidate_rows": 0, "skipped_rows": 0,
    }), encoding="utf-8")

    interest_fields = ["normalized_path", "member_key", "side", "reference_offset", "record_start", "leaf0_u32_hex", "leaf1_u32_hex"]
    interest_rows = []
    for path, key, _name, side, start, reference, value, _endpoint in focal_specs:
        if value not in {75.0, 150.0}:
            continue
        raw = f32_bits(value)
        interest_rows.append({
            "normalized_path": path, "member_key": key, "side": side,
            "reference_offset": reference, "record_start": start,
            "leaf0_u32_hex": f"0x{raw:08x}", "leaf1_u32_hex": f"0x{raw:08x}",
        })
    assert len(interest_rows) == 7
    write_tsv(stage100 / "SLOT_LIGHT_PAIRED_LEAF_OCCURRENCE_INVENTORY.tsv", interest_fields, interest_rows)
    return reports


class Stage101Tests(unittest.TestCase):
    def test_classifies_focal_pair_storage_without_semantic_inference(self) -> None:
        with tempfile.TemporaryDirectory(prefix="stage101-test-") as temp_name:
            reports = prepare_reports(Path(temp_name))
            output, archive, summary = TOOL.build_report(ROOT, create_archive=False, report_root=reports)
            self.assertIsNone(archive)
            self.assertEqual(summary["reference_record_rows"], 177)
            self.assertEqual(summary["focal_context_record_rows"], 21)
            self.assertEqual(summary["focal_context_member_rows"], 4)
            self.assertEqual(summary["focal_context_endpoint_rows"], 2)
            self.assertEqual(summary["focal_context_values"], ["1", "2", "30", "50", "75", "100", "150"])
            self.assertTrue(summary["technical_leaf_storage_class_resolved"])
            self.assertEqual(summary["technical_leaf_storage_class"], "paired_equal_finite_float_payload_leaves")
            self.assertFalse(summary["technical_leaf_domain_semantics_resolved"])
            self.assertFalse(summary["brightness_semantics_confirmed"])
            self.assertEqual(summary["prototype_candidate_rows"], 0)
            self.assertTrue((output / "SLOT_LIGHT_FOCAL_EQUAL_FLOAT_VALUE_DOMAIN.tsv").is_file())

    def test_rejects_unequal_leaf_inside_focal_template(self) -> None:
        with tempfile.TemporaryDirectory(prefix="stage101-negative-") as temp_name:
            reports = prepare_reports(Path(temp_name), corrupt_focal_pair=True)
            with self.assertRaises(TOOL.Stage101Error):
                TOOL.build_report(ROOT, create_archive=False, report_root=reports)


if __name__ == "__main__":
    unittest.main()
