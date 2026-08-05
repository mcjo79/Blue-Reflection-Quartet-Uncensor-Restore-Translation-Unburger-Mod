from __future__ import annotations

import csv
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
TOOL_PATH = ROOT / "workstreams/quartet_restoration/collect_wet_coverage_material_variant_evidence.py"
SPEC = importlib.util.spec_from_file_location("collect_wet_coverage_material_variant_evidence", TOOL_PATH)
assert SPEC and SPEC.loader
TOOL = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = TOOL
SPEC.loader.exec_module(TOOL)


def write_tsv(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields: list[str] = []
    for row in rows:
        for key in row:
            if key not in fields:
                fields.append(key)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def build_project(root: Path, rows: list[dict[str, object]]) -> None:
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
    material = report / TOOL.MATERIAL_DIR
    material.mkdir(parents=True)
    (material / "SUMMARY.json").write_text(json.dumps({
        "type": "br_quartet_restoration_material_delta_evidence_summary",
        "tool_version": "0.0.10",
        "focused_review_rows": len(rows),
        "skipped_rows": 0,
    }), encoding="utf-8")
    write_tsv(material / "FOCUSED_MATERIAL_REVIEW.tsv", rows)


def direct_row(**updates: object) -> dict[str, object]:
    row: dict[str, object] = {
        "evidence_kind": "semantic_pair",
        "review_priority": "critical",
        "review_basis": "direct_alpha_transparency_or_refraction_parameter",
        "relation": "original_scene_vs_quartet_scene",
        "context_id": "scene_1",
        "domain": "wet_fabric_material_response",
        "priority": "critical",
        "pair_id": "pair1",
        "source_archive_path": "data/x64/field/a.elixir.gz",
        "target_archive_path": "data/x64/field/a.elixir.gz",
        "source_member_name": "A.g1m",
        "target_member_name": "A.g1m",
        "parameter_name": "fTranslucency",
        "buffer_type": "1",
        "buffer_count": "1",
        "source_shader_block_index": "2",
        "target_shader_block_index": "3",
        "source_parameter_index": "4",
        "target_parameter_index": "5",
        "source_value_text": "0.5",
        "target_value_text": "0.25",
        "source_value_hex": "0000003f",
        "target_value_hex": "0000803e",
        "classification": "changed",
        "matching_basis": "semantic_name_type_count_nearest_numeric",
        "normalized_distance": "0.25",
        "keyword_hits": "translucency,wet",
    }
    row.update(updates)
    return row


class WetCoverageMaterialVariantTests(unittest.TestCase):
    def test_direct_high_value_change_is_queued(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            build_project(root, [direct_row()])
            output, archive, summary = TOOL.build_report(root, create_archive=False)
            self.assertIsNone(archive)
            self.assertEqual(summary["direct_numeric_restore_candidate_rows"], 1)
            self.assertEqual(summary["direct_numeric_member_groups_ready_for_occurrence_audit"], 1)
            groups = TOOL.read_tsv(output / "MATERIAL_MEMBER_GROUPS.tsv")
            self.assertEqual(groups[0]["classification"], "direct_numeric_member_candidate_ready_for_binary_occurrence_audit")
            self.assertEqual(groups[0]["safe_to_build_payload_now"], "False")

    def test_added_parameter_is_structural_not_direct(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            build_project(root, [direct_row(classification="added_in_target", source_value_hex="")])
            _output, _archive, summary = TOOL.build_report(root, create_archive=False)
            self.assertEqual(summary["direct_numeric_restore_candidate_rows"], 0)
            self.assertEqual(summary["structural_material_change_rows"], 1)

    def test_three_way_variant_is_review_only(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            row = direct_row(
                evidence_kind="three_way_variant",
                relation="",
                classification="variant_specific_change",
                source_archive_path="",
                target_archive_path="",
                source_member_name="",
                target_member_name="",
                quartet_variant_archive_path="data/x64/costume/variant.elixir.gz",
                quartet_variant_member_name="variant.g1m",
                original_base_values="0.1",
                quartet_base_values="0.1",
                quartet_variant_values="0.8",
            )
            build_project(root, [row])
            _output, _archive, summary = TOOL.build_report(root, create_archive=False)
            self.assertEqual(summary["three_way_variant_review_rows"], 1)
            self.assertEqual(summary["direct_numeric_restore_candidate_rows"], 0)

    def test_generic_mesh_blend_without_keywords_is_skipped(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            build_project(root, [direct_row(
                parameter_name="ParameterForMeshBlend",
                keyword_hits="",
                domain="other",
                review_priority="low",
            )])
            output, _archive, summary = TOOL.build_report(root, create_archive=False)
            self.assertEqual(summary["in_scope_material_rows"], 0)
            skipped = TOOL.read_tsv(output / "MATERIAL_VARIANT_SKIPPED.tsv")
            self.assertEqual(len(skipped), 1)

    def test_rejects_old_fourteen_profile_registry(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            build_project(root, [direct_row()])
            summary_path = root / ".local/reports/quartet_restoration" / TOOL.REGISTRY_DIR / "SUMMARY.json"
            summary = json.loads(summary_path.read_text(encoding="utf-8"))
            summary["profile_rows"] = 14
            summary_path.write_text(json.dumps(summary), encoding="utf-8")
            with self.assertRaisesRegex(TOOL.MaterialVariantEvidenceError, "15 profiles"):
                TOOL.build_report(root, create_archive=False)


if __name__ == "__main__":
    unittest.main()
