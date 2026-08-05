#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import importlib.util
import json
import shutil
import struct
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
TOOL_PATH = ROOT / "workstreams/quartet_restoration/build_residual_shared_presentation_prototype.py"
SPEC = importlib.util.spec_from_file_location("build_residual_shared_presentation_prototype", TOOL_PATH)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)

BR_SPEC = importlib.util.spec_from_file_location(
    "br_restoration_tool", ROOT / "Blue_Reflection_Text_Tool/br_restoration_tool.py"
)
assert BR_SPEC and BR_SPEC.loader
BR = importlib.util.module_from_spec(BR_SPEC)
sys.modules[BR_SPEC.name] = BR
BR_SPEC.loader.exec_module(BR)


def payload(words: list[int], trailing: bytes = b"") -> bytes:
    def lp(raw: bytes) -> bytes:
        return struct.pack("<I", len(raw)) + raw

    prefix = struct.pack("<II", 3, 0) + lp(b"name\0") + lp("説明".encode("cp932") + b"\0")
    return prefix + struct.pack(f"<{len(words)}I", *words) + trailing


def occurrence_for(source: bytes, target: bytes, path: str, cue_domains: str, archetype: str) -> tuple[str, dict[str, object], dict[str, object]]:
    source_header = BR.parse_ebd_header_schema(source)
    target_header = BR.parse_ebd_header_schema(target)
    source_profile = BR.profile_ebd_post_header_words(source, int(source_header["header_end"]))
    target_profile = BR.profile_ebd_post_header_words(target, int(target_header["header_end"]))
    delta = BR.compare_ebd_tag_atoms(source_profile["atoms"], target_profile["atoms"])[0]
    shape_id = BR.event_residual_delta_shape_id(delta)
    source_start, source_end = BR.event_atom_word_span(
        source_profile["atoms"], int(delta["source_atom_start"]), int(delta["source_atom_end"]),
        int(source_profile["word_count"]),
    )
    target_start, target_end = BR.event_atom_word_span(
        target_profile["atoms"], int(delta["target_atom_start"]), int(delta["target_atom_end"]),
        int(target_profile["word_count"]),
    )
    occurrence = {
        "shape_id": shape_id,
        "normalized_path": path,
        "occurrence_index": 0,
        "cue_positive_occurrence": True,
        "cue_domains": cue_domains,
        "pair_context_archetype_id": archetype,
        "source_span_start_word_index": source_start,
        "source_span_end_word_index": source_end,
        "target_span_start_word_index": target_start,
        "target_span_end_word_index": target_end,
    }
    candidate, metadata = MODULE.construct_exact_inverse_candidate(
        br=BR, source_payload=source, target_payload=target, occurrence=occurrence,
    )
    return shape_id, occurrence, {**metadata, "candidate": candidate}


class ResidualSharedPresentationPrototypeTests(unittest.TestCase):
    def test_exact_inverse_candidate_roundtrips_and_preserves_other_shapes(self) -> None:
        source = payload([1, 0x75400009, 0x73000005, 0x74200012, 0x7F000000], b"tail")
        target = payload([1, 0x75400009, 0x750000A3, 0x73000005, 0x74200012, 0x7F000000], b"tail")
        shape_id, occurrence, _ = occurrence_for(
            source, target, "event/event_jp/ce11/event_ce11_070.ebd", "steam_or_vapor", "a",
        )
        occurrence["shape_id"] = shape_id
        candidate, metadata = MODULE.construct_exact_inverse_candidate(
            br=BR, source_payload=source, target_payload=target, occurrence=occurrence,
        )
        self.assertEqual(candidate, source)
        self.assertTrue(metadata["selected_occurrence_removed"])
        self.assertTrue(metadata["other_residual_shape_counter_unchanged"])
        self.assertTrue(metadata["target_roundtrip_exact"])
        self.assertTrue(metadata["target_header_preserved"])
        self.assertTrue(metadata["target_trailing_bytes_preserved"])

    def test_stage35_gate_rejects_unexpected_eligible_shape(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            stage35 = Path(temporary)
            (stage35 / "SUMMARY.json").write_text(json.dumps({
                "type": "br_quartet_restoration_residual_exact_context_evidence_summary",
                "tool_version": "0.0.41",
                "stage36_eligible_shape_ids": ["unexpected"],
            }), encoding="utf-8")
            with self.assertRaises(MODULE.SharedPresentationPrototypeError):
                MODULE.validate_stage35(stage35)

    def test_builds_one_two_file_local_profile_and_metadata_only_report(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary)
            tool_dir = project / "Blue_Reflection_Text_Tool"
            tool_dir.mkdir(parents=True)
            shutil.copy2(ROOT / "Blue_Reflection_Text_Tool/br_restoration_tool.py", tool_dir / "br_restoration_tool.py")
            reports = project / ".local/reports/quartet_restoration"
            workspace = project / ".local/build/quartet_restoration"
            stage35 = reports / MODULE.STAGE35_DIR
            differences = reports / "differences"
            stage35.mkdir(parents=True)
            differences.mkdir(parents=True)

            pairs = [
                (
                    "event/event_jp/ce11/event_ce11_070.ebd",
                    payload([1, 0x75400009, 0x70000001, 0x73000005, 0x74200012, 0x7F000000]),
                    payload([1, 0x75400009, 0x70000001, 0x750000A3, 0x73000005, 0x74200012, 0x7F000000]),
                    "steam_or_vapor", "arch_ce11",
                ),
                (
                    "event/event_jp/em01/event_em01_090.ebd",
                    payload([1, 0x75400009, 0x7100000C, 0x73000005, 0x74100014, 0x7F000000], b"zz"),
                    payload([1, 0x75400009, 0x7100000C, 0x750000A3, 0x73000005, 0x74100014, 0x7F000000], b"zz"),
                    "pool_or_swimming", "arch_em01",
                ),
            ]
            occurrence_rows = []
            splice_rows = []
            difference_entries = []
            computed_shape = ""
            for index, (path, source, target, domains, archetype) in enumerate(pairs):
                shape_id, occurrence, metadata = occurrence_for(source, target, path, domains, archetype)
                if computed_shape:
                    self.assertEqual(shape_id, computed_shape)
                computed_shape = shape_id
                occurrence_rows.append(occurrence)
                splice_rows.append({
                    "shape_id": shape_id,
                    "normalized_path": path,
                    "occurrence_index": 0,
                    "candidate_sha256": metadata["candidate_sha256"],
                    "candidate_size": metadata["candidate_size"],
                    "source_span_sha256": metadata["source_span_sha256"],
                    "target_span_sha256": metadata["target_span_sha256"],
                    "selected_occurrence_removed": True,
                    "other_residual_shape_counter_unchanged": True,
                    "target_header_preserved": True,
                    "target_trailing_bytes_preserved": True,
                    "splice_status": "isolated_exact_inverse_splice_passed",
                })
                source_archive = "DATA/PACK01.PAK"
                target_archive = "Data/PACK11.PAK"
                target_internal = "event/b1/" + path[len("event/"):]
                source_item = {
                    "archive": source_archive, "path": path, "normalized_path": path,
                    "size": len(source), "sha256": hashlib.sha256(source).hexdigest(),
                    "extension": ".ebd", "asset_type": "event_data", "magic_hex": source[:8].hex(),
                }
                target_item = {
                    "archive": target_archive, "path": target_internal, "normalized_path": path,
                    "size": len(target), "sha256": hashlib.sha256(target).hexdigest(),
                    "extension": ".ebd", "asset_type": "event_data", "magic_hex": target[:8].hex(),
                }
                difference_entries.append({
                    "classification": "changed", "scope_status": "in_scope", "normalized_path": path,
                    "source": BR.file_ref(source_item), "target": BR.file_ref(target_item),
                })
                for side, item, raw in (("source", source_item, source), ("target", target_item, target)):
                    out = BR.inventory_workspace_file(workspace, side, "br1_events", item["archive"], item["path"])
                    out.parent.mkdir(parents=True, exist_ok=True)
                    out.write_bytes(raw)

            BR.atomic_json(differences / "br1_events.json", {
                "source_archive_group": "br1_events",
                "entries": difference_entries,
            })
            (stage35 / "SUMMARY.json").write_text(json.dumps({
                "type": "br_quartet_restoration_residual_exact_context_evidence_summary",
                "tool_version": "0.0.41",
                "stage36_eligible_shape_ids": [computed_shape],
            }), encoding="utf-8")
            BR.write_tsv(stage35 / "RESIDUAL_SHAPE_PROMOTION_GATES.tsv", [
                "shape_id", "stage35_classification", "stage36_gate", "noncue_occurrence_count",
                "route_family_count", "all_splices_isolated",
            ], [{
                "shape_id": computed_shape,
                "stage35_classification": "shared_presentation_exact_span_prototype_candidate",
                "stage36_gate": "eligible_for_stage_36_local_prototype_review",
                "noncue_occurrence_count": 0,
                "route_family_count": 2,
                "all_splices_isolated": True,
            }])
            BR.write_tsv(stage35 / "RESIDUAL_EXACT_CONTEXT_OCCURRENCES.tsv", [
                "shape_id", "normalized_path", "occurrence_index", "cue_positive_occurrence", "cue_domains",
                "pair_context_archetype_id", "source_span_start_word_index", "source_span_end_word_index",
                "target_span_start_word_index", "target_span_end_word_index",
            ], occurrence_rows)
            BR.write_tsv(stage35 / "RESIDUAL_IN_MEMORY_SPLICE_VALIDATION.tsv", [
                "shape_id", "normalized_path", "occurrence_index", "candidate_sha256", "candidate_size",
                "source_span_sha256", "target_span_sha256", "selected_occurrence_removed",
                "other_residual_shape_counter_unchanged", "target_header_preserved",
                "target_trailing_bytes_preserved", "splice_status",
            ], splice_rows)

            old_shape = MODULE.EXPECTED_SHAPE_ID
            old_profile = MODULE.EXPECTED_PROFILE_ID
            old_paths = MODULE.EXPECTED_PATHS
            try:
                MODULE.EXPECTED_SHAPE_ID = computed_shape
                MODULE.EXPECTED_PROFILE_ID = "shared_presentation_testshape"
                MODULE.EXPECTED_PATHS = {row[0] for row in pairs}
                output, summary = MODULE.build_residual_shared_presentation_prototype(
                    project_root=project, workspace_root=workspace, report_root=reports,
                )
            finally:
                MODULE.EXPECTED_SHAPE_ID = old_shape
                MODULE.EXPECTED_PROFILE_ID = old_profile
                MODULE.EXPECTED_PATHS = old_paths

            self.assertTrue(output.is_file())
            self.assertEqual(summary["promoted_profile_rows"], 1)
            self.assertEqual(summary["prototype_file_rows"], 2)
            self.assertEqual(summary["validation_failures"], 0)
            profile = workspace / MODULE.PROTOTYPE_SUBDIR / "shared_presentation_testshape"
            manifest = json.loads((profile / "PROTOTYPE.json").read_text(encoding="utf-8"))
            self.assertEqual(len(manifest["files"]), 2)
            self.assertFalse(manifest["runtime_validated"])
            for path, source, _target, _domains, _archetype in pairs:
                self.assertEqual((profile / "payload" / path).read_bytes(), source)
            self.assertFalse(any(workspace.rglob("*.PAK")))
            evidence_text = "\n".join(
                p.read_text(encoding="utf-8") for p in (reports / MODULE.EVIDENCE_DIR_NAME).glob("*")
                if p.is_file() and p.suffix in {".tsv", ".json"}
            )
            self.assertNotIn("説明", evidence_text)


if __name__ == "__main__":
    unittest.main()
