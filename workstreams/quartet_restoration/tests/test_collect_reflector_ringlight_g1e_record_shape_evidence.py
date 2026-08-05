#!/usr/bin/env python3
from __future__ import annotations

import csv
import importlib.util
import json
import struct
import tempfile
import shutil
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
PATH = ROOT / "workstreams/quartet_restoration/collect_reflector_ringlight_g1e_record_shape_evidence.py"
spec = importlib.util.spec_from_file_location("stage82", PATH)
assert spec and spec.loader
TOOL = importlib.util.module_from_spec(spec)
spec.loader.exec_module(TOOL)


def write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data) + "\n", encoding="utf-8")


def write_tsv(path: Path, fields: list[str], rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def member(name: str, key: str, payload: bytes) -> dict:
    return {"name": name, "comparison_key": key, "payload": payload, "sha256": TOOL.sha256(payload)}


class Stage82Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.project = Path(self.tmp.name)
        self.reports = self.project / ".local/reports/quartet_restoration"
        self.reports.mkdir(parents=True)
        workstream = self.project / "workstreams/quartet_restoration"
        workstream.mkdir(parents=True)
        # Stage 82 dynamically loads the real stage-81 helper from the project.
        source81 = ROOT / "workstreams/quartet_restoration/collect_reflector_ringlight_control_callsite_evidence.py"
        (workstream / source81.name).write_bytes(source81.read_bytes())
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
                "character_slot": slot, "asset_role": role, "family_key": f"{role}:extra_{suffix}",
                "normalized_path": path, "member_name": f"extra_{suffix}.g1e",
                "member_key": f"extra_{suffix}.g1e#0", "candidate_id": suffix,
            })

        stage79 = self.reports / TOOL.STAGE79_DIR
        write_json(stage79 / "SUMMARY.json", {
            "type": "br_quartet_restoration_reflector_character_slot_render_member_evidence_summary",
            "tool_version": "0.0.92", "character_slot_rows": 15,
        })
        write_tsv(stage79 / "REFLECTOR_SLOT_RENDER_MEMBERS.tsv", list(self.scope[0]), self.scope)

        self.offsets = list(range(128, 176, 4)) + list(range(512, 560, 4)) + list(range(896, 944, 4))
        assert len(self.offsets) == 36
        self.source = bytearray(1280)
        self.target = bytearray(1280)
        self.source[0:8] = b"G1E_TEST"
        self.target[0:8] = b"G1E_TEST"
        for index, offset in enumerate(self.offsets):
            self.source[offset:offset + 4] = struct.pack("<I", 0x20 + index * 4)
            self.target[offset:offset + 4] = struct.pack("<I", 0x24 + index * 4)
        self.source = bytes(self.source)
        self.target = bytes(self.target)

        stage80 = self.reports / TOOL.STAGE80_DIR
        write_json(stage80 / "SUMMARY.json", {
            "type": "br_quartet_restoration_reflector_light_family_binary_evidence_summary",
            "tool_version": "0.0.93", "common_ringlight_member_rows": 15,
            "common_ringlight_family_classification": "uniform_exact_delta_across_slots",
            "skipped_rows": 0, "policy": {},
        })
        audit_rows = []
        for row in self.scope:
            source = self.source
            target = self.target
            audit_rows.append({
                "normalized_path": row["normalized_path"], "member_key": row["member_key"],
                "source_sha256": TOOL.sha256(source), "target_sha256": TOOL.sha256(target),
                "exact_source_inverse": True, "exact_target_roundtrip": True,
            })
        write_tsv(stage80 / "REFLECTOR_LIGHT_MEMBER_BINARY_AUDIT.tsv", list(audit_rows[0]), audit_rows)

        stage81 = self.reports / TOOL.STAGE81_DIR
        write_json(stage81 / "SUMMARY.json", {
            "type": "br_quartet_restoration_reflector_ringlight_control_callsite_evidence_summary",
            "tool_version": "0.0.95", "common_ringlight_member_rows": 15,
            "common_ringlight_aligned_word_rows": 36, "parent_container_rows": 4,
            "prototype_candidate_rows": 0, "skipped_rows": 0, "policy": {},
        })
        canonical = []
        for offset in self.offsets:
            left = self.source[offset:offset + 4]
            right = self.target[offset:offset + 4]
            sf = struct.unpack("<f", left)[0]
            tf = struct.unpack("<f", right)[0]
            canonical.append({
                "word_offset": offset,
                "source_u32_hex": f"0x{int.from_bytes(left, 'little'):08x}",
                "target_u32_hex": f"0x{int.from_bytes(right, 'little'):08x}",
                "source_float32": f"{sf:.9g}", "target_float32": f"{tf:.9g}",
                "float_status": "finite_float_interpretation_available",
                "transition_id": TOOL.sha256(left + right), "slot_count": 15,
                "slots": ";".join(f"PC{i:02d}" for i in range(15)),
                "uniform_across_slots": True, "review_status": "test",
            })
        write_tsv(stage81 / "COMMON_RINGLIGHT_ALIGNED_WORD_TRANSITIONS.tsv", list(canonical[0]), canonical)
        write_tsv(stage81 / "RINGLIGHT_CONTROL_TRANSITION_MATCHES.tsv", [
            "normalized_path", "member_key", "member_name", "control_scope", "control_word_offset",
            "common_word_offset", "source_u32_hex", "target_u32_hex", "source_float32", "target_float32",
            "float_status", "transition_id", "review_status",
        ], [])

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def container_loader(self, **kwargs):
        del kwargs
        grouped: dict[str, list[dict]] = {}
        for row in self.scope:
            grouped.setdefault(row["normalized_path"], []).append(row)
        containers = []
        for path, rows in sorted(grouped.items()):
            source_members = [member(row["member_name"], row["member_key"], self.source) for row in rows]
            target_members = [member(row["member_name"], row["member_key"], self.target) for row in rows]
            if path.endswith("100_common.elixir.gz"):
                # Full three-cluster profile translated by +32 bytes in a neutral control.
                neutral_source = bytearray(1344)
                neutral_target = bytearray(1344)
                for offset in self.offsets:
                    neutral_source[offset + 32:offset + 36] = self.source[offset:offset + 4]
                    neutral_target[offset + 32:offset + 36] = self.target[offset:offset + 4]
                source_members.append(member("e_idle_neutral.g1e", "e_idle_neutral.g1e#0", bytes(neutral_source)))
                target_members.append(member("e_idle_neutral.g1e", "e_idle_neutral.g1e#0", bytes(neutral_target)))
                # A size-changing control must remain separate.
                source_members.append(member("e_size_changed.g1e", "e_size_changed.g1e#0", b"A" * 64))
                target_members.append(member("e_size_changed.g1e", "e_size_changed.g1e#0", b"B" * 68))
            containers.append({
                "candidate_id": rows[0]["candidate_id"], "normalized_path": path,
                "scope_rows": rows, "source_members": source_members, "target_members": target_members,
            })
        return containers, []

    def test_cluster_changed_words_separates_three_regions(self):
        rows = TOOL.read_tsv(self.reports / TOOL.STAGE81_DIR / "COMMON_RINGLIGHT_ALIGNED_WORD_TRANSITIONS.tsv")
        clusters = TOOL.cluster_changed_words(rows, 0x100)
        self.assertEqual([len(cluster) for cluster in clusters], [12, 12, 12])

    def test_find_cluster_matches_uses_complete_relative_shape(self):
        canonical = TOOL.aligned_word_deltas(self.source, self.target)
        clusters = TOOL.cluster_changed_words(canonical, 0x100)
        shifted_source = bytearray(1344)
        shifted_target = bytearray(1344)
        for offset in self.offsets:
            shifted_source[offset + 32:offset + 36] = self.source[offset:offset + 4]
            shifted_target[offset + 32:offset + 36] = self.target[offset:offset + 4]
        control = TOOL.aligned_word_deltas(bytes(shifted_source), bytes(shifted_target))
        self.assertEqual(TOOL.find_cluster_matches(control, clusters[0]), [160])

    def test_build_detects_neutral_full_profile_and_generates_no_prototype(self):
        output, archive, summary = TOOL.build_report(
            self.project, create_archive=False, container_loader=self.container_loader,
        )
        self.assertIsNone(archive)
        self.assertEqual(summary["common_ringlight_cluster_rows"], 3)
        self.assertGreater(summary["neutral_full_profile_match_rows"], 0)
        self.assertEqual(summary["semantic_leaf_candidate_rows"], 0)
        self.assertEqual(summary["prototype_candidate_rows"], 0)
        self.assertIn("likely_shared_serialization_shape", summary["status"])
        self.assertTrue((output / "G1E_CONTROL_FULL_PROFILE_MATCHES.tsv").is_file())

    def test_duplicate_stage80_identity_is_rejected(self):
        path = self.reports / TOOL.STAGE80_DIR / "REFLECTOR_LIGHT_MEMBER_BINARY_AUDIT.tsv"
        rows = TOOL.read_tsv(path)
        rows.append(dict(rows[0]))
        write_tsv(path, list(rows[0]), rows)
        with self.assertRaises(TOOL.Stage82Error):
            TOOL.build_report(self.project, create_archive=False, container_loader=self.container_loader)


if __name__ == "__main__":
    unittest.main()
