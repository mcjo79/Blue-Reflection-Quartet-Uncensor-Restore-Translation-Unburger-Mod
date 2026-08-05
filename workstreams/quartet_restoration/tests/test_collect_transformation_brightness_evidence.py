from __future__ import annotations

import csv
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
TOOL_PATH = ROOT / "workstreams/quartet_restoration/collect_transformation_brightness_evidence.py"
SPEC = importlib.util.spec_from_file_location("collect_transformation_brightness_evidence", TOOL_PATH)
assert SPEC and SPEC.loader
TOOL = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = TOOL
SPEC.loader.exec_module(TOOL)


def write_tsv(path: Path, rows: list[dict[str, object]], fields: list[str] | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if fields is None:
        fields = []
        for row in rows:
            for key in row:
                if key not in fields:
                    fields.append(key)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def build_project(root: Path, *, direct_row: bool = True, bad_stage75: bool = False) -> None:
    report = root / ".local/reports/quartet_restoration"
    registry = report / TOOL.REGISTRY_DIR
    registry.mkdir(parents=True)
    (registry / "SUMMARY.json").write_text(json.dumps({
        "type": "br_quartet_restoration_core_profile_manifest_evidence_summary",
        "tool_version": "0.0.83",
        "profile_rows": 15,
        "pack11_profile_rows": 12,
        "pack10_01_profile_rows": 2,
        "pack10_03_profile_rows": 1,
        "runtime_validated_profile_rows": 0,
    }), encoding="utf-8")

    structural = report / TOOL.STRUCTURAL_DIR
    structural.mkdir(parents=True)
    (structural / "SUMMARY.json").write_text(json.dumps({
        "type": "br_quartet_restoration_structural_material_parameter_evidence_summary",
        "tool_version": "0.0.87",
        "audited_member_rows": 0 if bad_stage75 else 16,
        "record_rows": 48,
        "record_validation_failures": 0,
        "skipped_rows": 0,
        "unique_followup_candidate_member_rows": 0,
    }), encoding="utf-8")
    write_tsv(structural / "STRUCTURAL_PARAMETER_RECORDS.tsv", [{
        "parameter_name": "atColor",
        "structural_class": "unique_scene_local_structure",
    }])
    write_tsv(structural / "STRUCTURAL_MEMBER_CANDIDATES.tsv", [
        {
            "candidate_mode": "unique_only",
            "selected_row_count": "1",
            "candidate_available": "False",
            "unresolved_reasons": "source block 5 has no target mapping",
            "member_name": "obj-s89-s-hinako-bath-room-01_hi.g1m",
            "distance_improvement": "",
        },
        {
            "candidate_mode": "recurrent_only",
            "selected_row_count": "5",
            "candidate_available": "True",
            "unresolved_reasons": "",
            "member_name": "obj-s89-s-hinako-bath-room-01_hi.g1m",
            "distance_improvement": "-6232",
        },
    ])

    presentation = report / TOOL.PRESENTATION_DIR
    presentation.mkdir(parents=True)
    (presentation / "SUMMARY.json").write_text(json.dumps({
        "type": "br_quartet_restoration_presentation_surface_evidence_summary",
        "tool_version": "0.0.17",
    }), encoding="utf-8")
    write_tsv(presentation / "LIGHTSHAFT_ASSET_CANDIDATES.tsv", [])
    write_tsv(presentation / "LIGHTSHAFT_PRESET_SETTINGS.tsv", [{
        "pair_id": "br1_assets",
        "normalized_path": "effect/yuzuki_henshin/lightshaftpreset.xml",
        "setting_path": "Bloom/Intensity",
        "source_value": "1.0",
        "target_value": "2.0",
        "delta": "value_changed",
    }] if direct_row else [])
    write_tsv(presentation / "LIGHTSHAFT_EFFECT_MEMBERS.tsv", [])

    shader = report / TOOL.SHADER_DIR
    shader.mkdir(parents=True)
    (shader / "SUMMARY.json").write_text(json.dumps({
        "type": "br_quartet_restoration_shader_effect_evidence_summary",
        "tool_version": "0.0.12",
    }), encoding="utf-8")
    write_tsv(shader / "FOCUSED_SHADER_EFFECT_REVIEW.tsv", [])

    binary = report / TOOL.BINARY_DIR
    binary.mkdir(parents=True)
    (binary / "SUMMARY.json").write_text(json.dumps({
        "type": "br_quartet_restoration_binary_delta_evidence_summary",
        "tool_version": "0.0.13",
    }), encoding="utf-8")
    write_tsv(binary / "PAYLOAD_BINARY_DELTA.tsv", [])
    write_tsv(binary / "RESTORATION_PROTOTYPE_CANDIDATES.tsv", [])

    differences = report / "differences"
    differences.mkdir()
    (differences / "br1_assets.json").write_text(json.dumps({
        "source_archive_group": "br1_assets",
        "entries": [{
            "normalized_path": "effect/yuzuki_henshin/body_brightness.g1e",
            "classification": "changed",
            "scope_status": "in_scope",
            "source": {"size": 100},
            "target": {"size": 100},
        }] if direct_row else [{
            "normalized_path": "field/ordinary_wall.bin",
            "classification": "changed",
            "scope_status": "in_scope",
            "source": {"size": 100},
            "target": {"size": 100},
        }],
    }), encoding="utf-8")


class TransformationBrightnessEvidenceTests(unittest.TestCase):
    def test_direct_yuzu_transformation_brightness_is_focused(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            build_project(root)
            output, archive, summary = TOOL.build_report(root, create_archive=False)
            self.assertIsNone(archive)
            self.assertGreaterEqual(summary["direct_yuzu_transformation_brightness_rows"], 1)
            rows = TOOL.read_tsv(output / "TRANSFORMATION_BRIGHTNESS_FOCUSED_REVIEW.tsv")
            self.assertTrue(any(row["lead_classification"] == "yuzu_transformation_brightness_direct_lead" for row in rows))
            self.assertFalse(summary["policy"]["user_report_treated_as_confirmed_fact"])

    def test_ordinary_unrelated_path_is_not_focused(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            build_project(root, direct_row=False)
            _output, _archive, summary = TOOL.build_report(root, create_archive=False)
            self.assertEqual(summary["focused_review_rows"], 0)
            self.assertEqual(summary["direct_yuzu_transformation_brightness_rows"], 0)

    def test_rejects_invalid_stage75_report(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            build_project(root, bad_stage75=True)
            with self.assertRaisesRegex(TOOL.TransformationBrightnessEvidenceError, "16 G1M"):
                TOOL.build_report(root, create_archive=False)

    def test_short_tokens_use_component_boundaries(self) -> None:
        self.assertEqual(TOOL.token_hits("foo_rfl_bar", {"rfl"}), ["rfl"])
        self.assertEqual(TOOL.token_hits("carefully", {"rfl"}), [])


if __name__ == "__main__":
    unittest.main()
