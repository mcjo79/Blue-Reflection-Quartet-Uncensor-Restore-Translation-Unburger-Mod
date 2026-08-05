#!/usr/bin/env python3
from __future__ import annotations

import csv
import importlib.util
import json
import shutil
import struct
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
PATH = ROOT / "workstreams/quartet_restoration/collect_reflector_ringlight_structural_shift_evidence.py"
spec = importlib.util.spec_from_file_location("stage83", PATH)
assert spec and spec.loader
TOOL = importlib.util.module_from_spec(spec)
spec.loader.exec_module(TOOL)


def write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value) + "\n", encoding="utf-8")


def write_tsv(path: Path, fields: list[str], rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def put(payload: bytearray, offset: int, value: int) -> None:
    payload[offset:offset + 4] = struct.pack("<I", value)


def member(name: str, key: str, payload: bytes) -> dict:
    return {"name": name, "comparison_key": key, "payload": payload, "sha256": TOOL.sha256(payload)}


def build_pair(slot: int = 0) -> tuple[bytes, bytes, list[dict], list[dict]]:
    source = bytearray(1400)
    target = bytearray(source)
    source[0:8] = b"G1FX5200"
    target[0:8] = b"G1FX5200"
    # Unrelated slot-specific metadata stays identical within the pair but
    # differs across slots, proving that only the delta profile is uniform.
    put(source, 64, 0x1000 + slot)
    put(target, 64, 0x1000 + slot)

    specs = [
        ("cluster_01", 128, 76, [0x3F800000, 0x14, 0x278, 0x2B4, 0x2E0, 0x30C, 0x358], [0, 12, 56, 60]),
        ("cluster_02", 512, 76, [0x3F800000, 0x01, 0x268, 0x2A4, 0x2D0, 0x2FC], [0, 12, 56, 60]),
        ("cluster_03", 896, 80, [0xCB, 0x268, 0x2A4, 0x2D0, 0x30C], [0, 12, 56, 60]),
    ]
    cluster_rows: list[dict] = []
    word_rows: list[dict] = []
    for cluster_id, start, pivot_rel, values, header_rels in specs:
        for index, rel in enumerate(header_rels):
            source_value = [0x5C, 0x64 if cluster_id == "cluster_01" else 0x60, 0x1C, 0x1C][index]
            target_value = source_value - 8
            put(source, start + rel, source_value)
            put(target, start + rel, target_value)
        pivot = start + pivot_rel
        put(source, pivot, 0)
        put(source, pivot + 4, 0)
        for index, value in enumerate(values):
            put(source, pivot + 8 + index * 4, value)
            target_value = value if index < 2 and cluster_id != "cluster_03" else value + 8
            if cluster_id == "cluster_03" and index == 0:
                target_value = value
            put(target, pivot + index * 4, target_value)
        put(target, pivot + len(values) * 4, 0)
        put(target, pivot + (len(values) + 1) * 4, 0)

        changed = [offset for offset in range(start, start + 128, 4) if source[offset:offset + 4] != target[offset:offset + 4]]
        cluster_rows.append({
            "cluster_id": cluster_id,
            "start_offset": changed[0],
            "end_offset_exclusive": changed[-1] + 4,
            "span_bytes": changed[-1] + 4 - changed[0],
            "changed_word_rows": len(changed),
            "signature_id": cluster_id,
            "slot_count": 15,
            "uniform_across_slots": True,
            "review_status": "test",
        })
        for offset in changed:
            left = bytes(source[offset:offset + 4])
            right = bytes(target[offset:offset + 4])
            word_rows.append({
                "cluster_id": cluster_id,
                "relative_offset": offset - changed[0],
                "word_offset": offset,
                "source_u32_hex": f"0x{int.from_bytes(left, 'little'):08x}",
                "target_u32_hex": f"0x{int.from_bytes(right, 'little'):08x}",
                "source_float32": "0",
                "target_float32": "0",
                "float_status": "finite_float_interpretation_available",
                "transition_id": TOOL.sha256(left + right),
                "neutral_individual_transition_matches": 0,
                "review_status": "test",
            })
    assert len(word_rows) == 36
    return bytes(source), bytes(target), cluster_rows, word_rows


class Stage83Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.project = Path(self.tmp.name)
        self.reports = self.project / ".local/reports/quartet_restoration"
        self.reports.mkdir(parents=True)
        workstream = self.project / "workstreams/quartet_restoration"
        workstream.mkdir(parents=True)
        for name in (
            "collect_reflector_ringlight_control_callsite_evidence.py",
            "collect_reflector_ringlight_g1e_record_shape_evidence.py",
        ):
            shutil.copy2(ROOT / "workstreams/quartet_restoration" / name, workstream / name)
        shutil.copytree(ROOT / "Blue_Reflection_Text_Tool", self.project / "Blue_Reflection_Text_Tool")

        self.scope: list[dict] = []
        for index in range(15):
            self.scope.append({
                "character_slot": f"PC{index:02d}", "asset_role": "ringlight",
                "family_key": "ringlight:e_cmn_ringlight_PCXX.g1e",
                "normalized_path": "data/x64/effect/100_common.elixir.gz",
                "member_name": f"e_cmn_ringlight_PC{index:02d}.g1e",
                "member_key": f"e_cmn_ringlight_pc{index:02d}.g1e#0",
                "candidate_id": "common",
            })
        extras = [
            ("PC00", "ringlight", "a", "data/x64/effect/1000_pc00.elixir.gz"),
            ("PC00", "eyelight", "b", "data/x64/effect/1000_pc00.elixir.gz"),
            ("PC01", "ringlight", "c", "data/x64/effect/1001_pc01.elixir.gz"),
            ("PC01", "eyelight", "d", "data/x64/effect/1001_pc01.elixir.gz"),
            ("PC02", "ringlight", "e", "data/x64/effect/1002_pc02.elixir.gz"),
            ("PC02", "ringlight", "f", "data/x64/effect/1002_pc02.elixir.gz"),
        ]
        for slot, role, suffix, path in extras:
            self.scope.append({
                "character_slot": slot, "asset_role": role,
                "family_key": f"{role}:extra_{suffix}", "normalized_path": path,
                "member_name": f"extra_{suffix}.g1e", "member_key": f"extra_{suffix}.g1e#0",
                "candidate_id": suffix,
            })

        stage79 = self.reports / TOOL.STAGE79_DIR
        write_json(stage79 / "SUMMARY.json", {
            "type": "br_quartet_restoration_reflector_character_slot_render_member_evidence_summary",
            "tool_version": "0.0.92", "character_slot_rows": 15,
        })
        write_tsv(stage79 / "REFLECTOR_SLOT_RENDER_MEMBERS.tsv", list(self.scope[0]), self.scope)

        self.pairs = [build_pair(index)[:2] for index in range(15)]
        _source0, _target0, cluster_rows, word_rows = build_pair(0)

        stage80 = self.reports / TOOL.STAGE80_DIR
        write_json(stage80 / "SUMMARY.json", {
            "type": "br_quartet_restoration_reflector_light_family_binary_evidence_summary",
            "tool_version": "0.0.93", "common_ringlight_member_rows": 15,
            "common_ringlight_family_classification": "uniform_exact_delta_across_slots",
            "skipped_rows": 0, "policy": {},
        })
        audits = []
        for index, row in enumerate(self.scope[:15]):
            source, target = self.pairs[index]
            audits.append({
                "normalized_path": row["normalized_path"], "member_key": row["member_key"],
                "source_sha256": TOOL.sha256(source), "target_sha256": TOOL.sha256(target),
            })
        write_tsv(stage80 / "REFLECTOR_LIGHT_MEMBER_BINARY_AUDIT.tsv", list(audits[0]), audits)

        stage81 = self.reports / TOOL.STAGE81_DIR
        write_json(stage81 / "SUMMARY.json", {
            "type": "br_quartet_restoration_reflector_ringlight_control_callsite_evidence_summary",
            "tool_version": "0.0.95", "common_ringlight_member_rows": 15,
            "common_ringlight_aligned_word_rows": 36, "parent_container_rows": 4,
            "prototype_candidate_rows": 0, "skipped_rows": 0, "policy": {},
        })
        canonical = []
        for row in word_rows:
            canonical.append({
                "word_offset": row["word_offset"], "source_u32_hex": row["source_u32_hex"],
                "target_u32_hex": row["target_u32_hex"], "source_float32": "0", "target_float32": "0",
                "float_status": "finite_float_interpretation_available", "transition_id": row["transition_id"],
                "slot_count": 15, "slots": ";".join(f"PC{i:02d}" for i in range(15)),
                "uniform_across_slots": True, "review_status": "test",
            })
        write_tsv(stage81 / "COMMON_RINGLIGHT_ALIGNED_WORD_TRANSITIONS.tsv", list(canonical[0]), canonical)

        stage82 = self.reports / TOOL.STAGE82_DIR
        write_json(stage82 / "SUMMARY.json", {
            "type": "br_quartet_restoration_reflector_ringlight_g1e_record_shape_evidence_summary",
            "tool_version": "0.0.96", "common_ringlight_member_rows": 15,
            "common_ringlight_aligned_word_rows": 36, "common_ringlight_cluster_rows": 3,
            "complete_cluster_match_rows": 0, "full_profile_match_rows": 0,
            "semantic_leaf_candidate_rows": 0, "prototype_candidate_rows": 0,
            "skipped_rows": 0, "policy": {},
        })
        write_tsv(stage82 / "COMMON_RINGLIGHT_CHANGE_CLUSTERS.tsv", list(cluster_rows[0]), cluster_rows)
        write_tsv(stage82 / "COMMON_RINGLIGHT_CLUSTER_WORDS.tsv", list(word_rows[0]), word_rows)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def container_loader(self, **kwargs):
        del kwargs
        grouped: dict[str, list[dict]] = {}
        for row in self.scope:
            grouped.setdefault(row["normalized_path"], []).append(row)
        containers = []
        for path, rows in sorted(grouped.items()):
            source_members = []
            target_members = []
            for row in rows:
                if row in self.scope[:15]:
                    index = int(row["character_slot"][2:])
                    source, target = self.pairs[index]
                else:
                    source = target = b"G1FX5200" + b"\0" * 120
                source_members.append(member(row["member_name"], row["member_key"], source))
                target_members.append(member(row["member_name"], row["member_key"], target))
            containers.append({
                "candidate_id": rows[0]["candidate_id"], "normalized_path": path,
                "scope_rows": rows, "source_members": source_members, "target_members": target_members,
            })
        return containers, []

    def test_discover_cluster_model_explains_compaction(self):
        source, target, _clusters, rows = build_pair(0)
        cluster_rows = [row for row in rows if row["cluster_id"] == "cluster_01"]
        model = TOOL.discover_cluster_model(source, target, "cluster_01", cluster_rows)
        self.assertEqual(model["shift_bytes"], 8)
        self.assertEqual(model["residual_word_rows"], 0)
        self.assertEqual(model["envelope_shrink_rows"], 4)
        self.assertEqual(model["tail_zero_fill_rows"], 2)

    def test_leaf_change_is_not_hidden_by_structural_model(self):
        source, target, _clusters, rows = build_pair(0)
        target = bytearray(target)
        put(target, 128 + 24, 0x40000000)
        left = source[152:156]
        right = bytes(target[152:156])
        rows.append({
            "cluster_id": "cluster_01", "word_offset": 152,
            "source_u32_hex": f"0x{int.from_bytes(left, 'little'):08x}",
            "target_u32_hex": f"0x{int.from_bytes(right, 'little'):08x}",
        })
        model = TOOL.discover_cluster_model(source, bytes(target), "cluster_01", [row for row in rows if row["cluster_id"] == "cluster_01"])
        self.assertGreater(model["residual_word_rows"], 0)

    def test_build_closes_common_family_as_structural_without_prototype(self):
        output, archive, summary = TOOL.build_report(
            self.project, create_archive=False, container_loader=self.container_loader,
        )
        self.assertIsNone(archive)
        self.assertEqual(summary["model_shift_values"], [8])
        self.assertEqual(summary["explained_dword_rows"], 36)
        self.assertEqual(summary["residual_dword_rows"], 0)
        self.assertEqual(summary["exact_slot_model_rows"], 15)
        self.assertEqual(summary["prototype_candidate_rows"], 0)
        self.assertIn("record_compaction", summary["status"])
        self.assertTrue((output / "COMMON_RINGLIGHT_STRUCTURAL_SHIFT_MODELS.tsv").is_file())

    def test_stage82_control_match_blocks_gate(self):
        path = self.reports / TOOL.STAGE82_DIR / "SUMMARY.json"
        summary = json.loads(path.read_text())
        summary["complete_cluster_match_rows"] = 1
        write_json(path, summary)
        with self.assertRaises(TOOL.Stage83Error):
            TOOL.build_report(self.project, create_archive=False, container_loader=self.container_loader)


if __name__ == "__main__":
    unittest.main()
