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
MODULE_PATH = ROOT / "workstreams/quartet_restoration/collect_reflector_slot_light_shared_record_template_evidence.py"
spec = importlib.util.spec_from_file_location("stage86", MODULE_PATH)
assert spec and spec.loader
TOOL = importlib.util.module_from_spec(spec)
spec.loader.exec_module(TOOL)


def write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def write_tsv(path: Path, fields: list[str], rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def member(name: str, payload: bytes) -> dict:
    return {"name": name, "comparison_key": name.casefold() + "#0", "payload": payload}


def patterned(size: int, seed: int) -> bytearray:
    out = bytearray(((index * 29 + seed * 47) ^ (index >> 3)) & 0xFF for index in range(size))
    out[:8] = b"G1FX5200"
    return out


class PureTests(unittest.TestCase):
    def test_transition_profile_tracks_relative_words(self):
        source = bytearray(128)
        target = bytearray(128)
        source[60:64] = struct.pack("<f", 150.0)
        target[60:64] = struct.pack("<f", 75.0)
        profile = TOOL.transition_profile(bytes(source), bytes(target), 60, 60, 4)
        self.assertIsNotNone(profile)
        self.assertEqual(profile[4][1:], (0x43160000, 0x42960000))
        self.assertEqual(TOOL.changed_profile_rows(profile), 1)

    def test_neutral_large_profile_is_shared_template(self):
        self.assertEqual(TOOL.classify_pair("neutral_non_transformation_name_control", 16), "shared_neutral_record_template_transition")
        self.assertEqual(TOOL.classify_pair("neutral_non_transformation_name_control", 4), "same_center_transition_small_context_only")


class BuildTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.project = Path(self.tmp.name)
        reports = self.project / ".local/reports/quartet_restoration"
        reports.mkdir(parents=True)
        workstream = self.project / "workstreams/quartet_restoration"
        workstream.mkdir(parents=True)
        for name in (
            "collect_reflector_slot_light_semantic_leaf_context_evidence.py",
            "collect_reflector_ringlight_control_callsite_evidence.py",
        ):
            shutil.copy2(ROOT / "workstreams/quartet_restoration" / name, workstream)
        shutil.copytree(ROOT / "Blue_Reflection_Text_Tool", self.project / "Blue_Reflection_Text_Tool")

        stage79 = reports / TOOL.STAGE79_DIR
        write_json(stage79 / "SUMMARY.json", {
            "type": "br_quartet_restoration_reflector_character_slot_render_member_evidence_summary",
            "tool_version": "0.0.92", "character_slot_rows": 15, "slot_member_rows": 220,
            "ringlight_family_rows": 5, "eyelight_family_rows": 2,
        })
        rows = []
        for index in range(15):
            rows.append({
                "candidate_id": "common", "character_slot": f"PC{index:02d}", "asset_role": "ringlight",
                "family_key": "ringlight:e_cmn_ringlight_PCXX.g1e", "normalized_path": "data/x64/effect/100_common.elixir.gz",
                "member_name": f"e_cmn_ringlight_PC{index:02d}.g1e", "member_key": f"e_cmn_ringlight_pc{index:02d}.g1e#0",
            })
        extras = [
            ("a", "PC00", "ringlight", "e_PC00_ringlight_a.g1e", "data/x64/effect/1000_pc00.elixir.gz"),
            ("b", "PC00", "eyelight", "e_PC00_eyelight_00.g1e", "data/x64/effect/1000_pc00.elixir.gz"),
            ("c", "PC00", "eyelight", "e_PC00_eyelight_01.g1e", "data/x64/effect/1000_pc00.elixir.gz"),
            ("d", "PC01", "ringlight", "e_PC01_h2_ringlight_00.g1e", "data/x64/effect/1001_pc01.elixir.gz"),
            ("e", "PC01", "ringlight", "e_PC01_ringlight_00.g1e", "data/x64/effect/1001_pc01.elixir.gz"),
            ("f", "PC02", "ringlight", "e_PC02_w5_ringlight_01.g1e", "data/x64/effect/1002_pc02.elixir.gz"),
        ]
        for cid, slot, role, name, path in extras:
            rows.append({
                "candidate_id": cid, "character_slot": slot, "asset_role": role,
                "family_key": f"{role}:{name}", "normalized_path": path,
                "member_name": name, "member_key": name.casefold() + "#0",
            })
        write_tsv(stage79 / "REFLECTOR_SLOT_RENDER_MEMBERS.tsv", list(rows[0]), rows)

        self.candidate_name = "e_PC02_w5_ringlight_01.g1e"
        self.sibling_name = "e_cmn_pup_reflect_s.g1e"
        self.candidate_path = "data/x64/effect/1002_pc02.elixir.gz"
        self.sibling_path = "data/x64/effect/100_common.elixir.gz"
        self.candidate_source_center = 512
        self.candidate_target_center = 528
        self.sibling_source_center = 1024
        self.sibling_target_center = 1040

        candidate_source = patterned(4096, 1)
        candidate_target = patterned(4096, 2)
        sibling_source = patterned(4096, 3)
        sibling_target = patterned(4096, 4)
        radius = 64 * 4
        source_template = patterned(radius * 2 + 4, 10)
        target_template = patterned(radius * 2 + 4, 11)
        source_template[radius:radius + 4] = struct.pack("<f", 150.0)
        source_template[radius + 4:radius + 8] = struct.pack("<f", 150.0)
        target_template[radius:radius + 4] = struct.pack("<f", 75.0)
        target_template[radius + 4:radius + 8] = struct.pack("<f", 75.0)
        for payload, center, template in (
            (candidate_source, self.candidate_source_center, source_template),
            (sibling_source, self.sibling_source_center, source_template),
            (candidate_target, self.candidate_target_center, target_template),
            (sibling_target, self.sibling_target_center, target_template),
        ):
            payload[center - radius:center + radius + 4] = template
        self.candidate_pair = (bytes(candidate_source), bytes(candidate_target))
        self.sibling_pair = (bytes(sibling_source), bytes(sibling_target))

        stage85 = reports / TOOL.STAGE85_DIR
        write_json(stage85 / "SUMMARY.json", {
            "type": "br_quartet_restoration_reflector_slot_light_semantic_leaf_context_evidence_summary",
            "tool_version": "0.0.99",
            "status": "non_common_slot_light_float_interpretations_classified_by_multiset_and_masked_sibling_context_brightness_semantics_unresolved",
            "finite_float_input_rows": 62, "semantic_leaf_candidate_rows": 2,
            "exact_same_transition_sibling_rows": 2, "prototype_candidate_rows": 0,
            "brightness_semantics_confirmed": False, "skipped_rows": 0,
            "policy": {"installed_game_modified": False, "render_payload_written": False, "pak_repacked": False, "core_registry_modified": False, "profile_activated": False},
        })
        candidates = []
        matches = []
        for index, delta in enumerate((0, 4), start=1):
            cid = f"candidate{index}"
            candidates.append({
                "candidate_id": cid, "character_slot": "PC02", "asset_role": "ringlight",
                "family_key": "ringlight:e_PCXX_w5_ringlight_01.g1e", "normalized_path": self.candidate_path,
                "member_key": self.candidate_name.casefold() + "#0", "member_name": self.candidate_name,
                "segment_id": "segment", "source_offset": self.candidate_source_center + delta,
                "target_offset": self.candidate_target_center + delta, "source_u32_hex": "0x43160000",
                "target_u32_hex": "0x42960000", "source_float32": "150", "target_float32": "75",
            })
            matches.append({
                "candidate_id": cid, "candidate_member_name": self.candidate_name,
                "sibling_normalized_path": self.sibling_path,
                "sibling_member_key": self.sibling_name.casefold() + "#0", "sibling_member_name": self.sibling_name,
                "control_scope": "neutral_non_transformation_name_control", "source_context_match_count": 1,
                "target_context_match_count": 1, "source_offset": self.sibling_source_center + delta,
                "target_offset": self.sibling_target_center + delta, "source_u32_hex": "0x43160000",
                "target_u32_hex": "0x42960000", "transition_relation": "exact_same_transition",
                "review_status": "masked_context_match_not_parameter_name_proof",
            })
        write_tsv(stage85 / "SLOT_LIGHT_SEMANTIC_LEAF_CANDIDATES.tsv", list(candidates[0]), candidates)
        write_tsv(stage85 / "SLOT_LIGHT_MASKED_CONTEXT_SIBLING_MATCHES.tsv", list(matches[0]), matches)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def loader(self, **kwargs):
        containers = []
        for path in (
            "data/x64/effect/1000_pc00.elixir.gz",
            "data/x64/effect/1001_pc01.elixir.gz",
            self.candidate_path,
            self.sibling_path,
        ):
            source_members = []
            target_members = []
            if path == self.candidate_path:
                source_members.append(member(self.candidate_name, self.candidate_pair[0]))
                target_members.append(member(self.candidate_name, self.candidate_pair[1]))
            if path == self.sibling_path:
                source_members.append(member(self.sibling_name, self.sibling_pair[0]))
                target_members.append(member(self.sibling_name, self.sibling_pair[1]))
            containers.append({"normalized_path": path, "source_members": source_members, "target_members": target_members})
        return containers, []

    def test_build_confirms_large_shared_neutral_record_template(self):
        output, archive, summary = TOOL.build_report(self.project, create_archive=False, container_loader=self.loader)
        self.assertIsNone(archive)
        self.assertEqual(summary["semantic_leaf_candidate_rows"], 2)
        self.assertEqual(summary["shared_neutral_record_template_rows"], 2)
        self.assertEqual(summary["prototype_candidate_rows"], 0)
        with (output / "SLOT_LIGHT_SHARED_RECORD_TEMPLATE_PAIRS.tsv").open(encoding="utf-8") as handle:
            rows = list(csv.DictReader(handle, delimiter="\t"))
        self.assertEqual(len(rows), 2)
        self.assertTrue(all(int(row["maximum_transition_profile_radius_dwords"]) >= 16 for row in rows))


if __name__ == "__main__":
    unittest.main()
