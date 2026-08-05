#!/usr/bin/env python3
from __future__ import annotations

import csv
import hashlib
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
TOOL_PATH = ROOT / "workstreams/quartet_restoration/collect_reflector_slot_light_record_occurrence_identity_evidence.py"
spec = importlib.util.spec_from_file_location("stage92", TOOL_PATH)
assert spec and spec.loader
TOOL = importlib.util.module_from_spec(spec)
spec.loader.exec_module(TOOL)


def write_tsv(path: Path, fields: list[str], rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def record_words(first: float, tail_seed: int, endpoint: int, reference_offset: int) -> list[int]:
    import struct
    leaf = int.from_bytes(struct.pack("<f", first), "little")
    return [leaf, leaf, tail_seed, 1, 1, 304, 0, 280, 0, 276, (endpoint - reference_offset) & 0xFFFFFFFF]


def masked_hash(words: list[int], mask: set[int]) -> str:
    data = b"".join((0 if index in mask else value).to_bytes(4, "little") for index, value in enumerate(words))
    return hashlib.sha256(data).hexdigest()


class HelperTests(unittest.TestCase):
    def test_common_prefix_and_suffix(self):
        self.assertEqual(TOOL.common_prefix(["a", "b"], ["a", "x", "b"]), 1)
        self.assertEqual(TOOL.common_suffix(["a", "b"], ["a", "x", "b"], 1), 1)


class SyntheticStage92Report(unittest.TestCase):
    def test_corrects_neutral_cross_occurrence_pairing_and_keeps_candidate_identity_unresolved(self):
        with tempfile.TemporaryDirectory(prefix="stage92-test-") as temp_name:
            temp = Path(temp_name)
            reports = temp / "reports"
            workspace = temp / "workspace"
            stage91 = reports / TOOL.STAGE91_DIR
            stage91.mkdir(parents=True)

            template_rows: list[dict[str, object]] = []
            dword_rows: list[dict[str, object]] = []

            def add_record(role: str, path: str, key: str, name: str, side: str, index: int, start: int, first: float, tail_seed: int, endpoint: int) -> str:
                reference_offset = start + 40
                words = record_words(first, tail_seed, endpoint, reference_offset)
                template = masked_hash(words, {10})
                template_rows.append({
                    "cluster_role": role,
                    "normalized_path": path,
                    "member_key": key,
                    "member_name": name,
                    "side": side,
                    "endpoint": endpoint,
                    "section_count": 3 if role == "candidate_ringlight" and side == "source" else 4 if role == "candidate_ringlight" else 5,
                    "reference_index": index,
                    "reference_offset": reference_offset,
                    "reference_u32_hex": f"0x{words[10]:08x}",
                    "reference_i32": words[10] - 0x100000000 if words[10] & 0x80000000 else words[10],
                    "record_start": start,
                    "record_end_exclusive": start + 44,
                    "record_length": 44,
                    "masked_template_sha256": template,
                    "record_classification": "other_section_reference_record",
                })
                import struct
                for relative, value in enumerate(words):
                    number = struct.unpack("<f", value.to_bytes(4, "little"))[0]
                    finite = number == number and number not in (float("inf"), float("-inf"))
                    dword_rows.append({
                        "normalized_path": path,
                        "member_key": key,
                        "member_name": name,
                        "side": side,
                        "reference_offset": reference_offset,
                        "record_start": start,
                        "relative_dword": relative,
                        "is_relocation_dword": relative == 10,
                        "u32_hex": f"0x{value:08x}",
                        "i32": value - 0x100000000 if value & 0x80000000 else value,
                        "float32": f"{number:g}" if finite else "",
                        "float_status": "finite" if finite else "nonfinite",
                    })
                return template

            candidate_path = "data/x64/effect/candidate.elixir.gz"
            candidate_key = "candidate.g1e#0"
            neutral_path = "data/x64/effect/neutral.elixir.gz"
            neutral_key = "neutral.g1e#0"

            candidate_source_templates = [
                add_record("candidate_ringlight", candidate_path, candidate_key, "candidate.g1e", "source", 0, 1000, 30, 0, 128),
                add_record("candidate_ringlight", candidate_path, candidate_key, "candidate.g1e", "source", 1, 1600, 150, 0, 128),
                add_record("candidate_ringlight", candidate_path, candidate_key, "candidate.g1e", "source", 2, 2200, 2, 0, 128),
            ]
            candidate_target_templates = [
                add_record("candidate_ringlight", candidate_path, candidate_key, "candidate.g1e", "target", 0, 1016, 30, 0, 128),
                add_record("candidate_ringlight", candidate_path, candidate_key, "candidate.g1e", "target", 1, 1616, 75, 0, 128),
                add_record("candidate_ringlight", candidate_path, candidate_key, "candidate.g1e", "target", 2, 2216, 75, 0, 128),
                add_record("candidate_ringlight", candidate_path, candidate_key, "candidate.g1e", "target", 3, 2816, 2, 0, 128),
            ]
            source_template = candidate_source_templates[1]
            target_template = candidate_target_templates[1]

            neutral_values = [1, 100, 50, 150, 75]
            for side in ("source", "target"):
                for index, value in enumerate(neutral_values):
                    template = add_record("neutral_control", neutral_path, neutral_key, "neutral.g1e", side, index, 4000 + index * 600, value, 0, 192)
                    if value == 150:
                        self.assertEqual(template, source_template)
                    if value == 75:
                        self.assertEqual(template, target_template)

            # Fill to exactly 177 records without reusing the focal family core.
            filler_needed = TOOL.EXPECTED_REFERENCE_ROWS - len(template_rows)
            for index in range(filler_needed):
                side = "source" if index % 2 == 0 else "target"
                add_record("neutral_control", "data/x64/effect/filler.elixir.gz", "filler.g1e#0", "filler.g1e", side, index, 10000 + index * 48, float(200 + index), 1000 + index, 256)

            self.assertEqual(len(template_rows), TOOL.EXPECTED_REFERENCE_ROWS)
            self.assertEqual(len(dword_rows), TOOL.EXPECTED_DWORD_ROWS)

            (stage91 / "SUMMARY.json").write_text(json.dumps({
                "type": "br_quartet_restoration_reflector_slot_light_section_cardinality_record_role_evidence_summary",
                "tool_version": "0.1.5",
                "sibling_G1E_G1EM_member_rows": 540,
                "reference_cluster_member_rows": 4,
                "reference_record_rows": 177,
                "reference_record_dword_rows": 1947,
                "reference_record_template_group_rows": 116,
                "focal_source_template_occurrence_rows": 2,
                "focal_target_template_occurrence_rows": 3,
                "shared_record_transition_context_rows": 2,
                "shared_record_transition_independent_of_section_count_delta": True,
                "resolved_reference_origin": "dword_start_relative",
                "prototype_candidate_rows": 0,
                "brightness_semantics_confirmed": False,
                "censorship_semantics_confirmed": False,
                "skipped_rows": 0,
            }), encoding="utf-8")
            write_tsv(stage91 / "SLOT_LIGHT_REFERENCE_RECORD_TEMPLATES.tsv", list(template_rows[0]), template_rows)
            write_tsv(stage91 / "SLOT_LIGHT_REFERENCE_RECORD_DWORDS.tsv", list(dword_rows[0]), dword_rows)
            transition_rows = [
                {"island_role": "candidate_ringlight", "normalized_path": candidate_path, "member_key": candidate_key, "member_name": "candidate.g1e", "source_record_masked_sha256": source_template, "target_record_masked_sha256": target_template, "shared_transition_hash_pair": f"{source_template}->{target_template}"},
                {"island_role": "neutral_control", "normalized_path": neutral_path, "member_key": neutral_key, "member_name": "neutral.g1e", "source_record_masked_sha256": source_template, "target_record_masked_sha256": target_template, "shared_transition_hash_pair": f"{source_template}->{target_template}"},
            ]
            write_tsv(stage91 / "SLOT_LIGHT_SHARED_RECORD_TRANSITION_CARDINALITY.tsv", list(transition_rows[0]), transition_rows)
            cardinality_rows = [
                {"normalized_path": candidate_path, "member_key": candidate_key, "count_delta": 1},
                {"normalized_path": neutral_path, "member_key": neutral_key, "count_delta": 0},
            ]
            write_tsv(stage91 / "SLOT_LIGHT_SECTION_CARDINALITY.tsv", list(cardinality_rows[0]), cardinality_rows)

            output, archive, summary = TOOL.build_report(
                ROOT,
                create_archive=False,
                report_root=reports,
                workspace_root=workspace,
            )
            self.assertIsNone(archive)
            self.assertTrue(summary["neutral_focal_variants_coexist_unchanged"])
            self.assertFalse(summary["neutral_150_to_75_transition_supported"])
            self.assertTrue(summary["prior_transition_interpretation_corrected"])
            self.assertFalse(summary["prior_cross_context_record_migration_confirmed"])
            self.assertEqual(summary["candidate_focal_family_source_occurrence_rows"], 3)
            self.assertEqual(summary["candidate_focal_family_target_occurrence_rows"], 4)
            self.assertEqual(summary["candidate_family_middle_source_rows"], 1)
            self.assertEqual(summary["candidate_family_middle_target_rows"], 2)
            self.assertEqual(summary["candidate_minimum_edit_model_rows"], 2)
            self.assertFalse(summary["candidate_target_occurrence_identity_resolved"])
            self.assertEqual(summary["prototype_candidate_rows"], 0)
            self.assertTrue((output / "SLOT_LIGHT_PRIOR_ALIGNMENT_CORRECTION.tsv").is_file())
            self.assertTrue((output / "SLOT_LIGHT_CANDIDATE_EDIT_MODELS.tsv").is_file())


if __name__ == "__main__":
    unittest.main()
