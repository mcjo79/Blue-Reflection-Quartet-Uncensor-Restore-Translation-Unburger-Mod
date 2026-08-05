#!/usr/bin/env python3
from __future__ import annotations

import csv
import hashlib
import importlib.util
import json
import shutil
import struct
import tempfile
import unittest
from unittest import mock
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
TOOL_PATH = ROOT / "workstreams/quartet_restoration/collect_all_reflector_transformation_family_evidence.py"
BR_PATH = ROOT / "Blue_Reflection_Text_Tool/br_restoration_tool.py"
STAGE77_SOURCE = ROOT / "workstreams/quartet_restoration/collect_yuzuki_rfl50_event_binding_evidence.py"


def load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


TOOL = load_module(TOOL_PATH, "collect_all_reflector_transformation_family_evidence_for_test")
BR = load_module(BR_PATH, "br_restoration_tool_for_all_reflector_test")


def write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def write_tsv(path: Path, fields: list[str], rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def lp(value: bytes) -> bytes:
    return struct.pack("<I", len(value)) + value


def make_ebd(description: bytes, words: list[int], total_size: int) -> bytes:
    payload = struct.pack("<II", 1, 0) + lp(b"name\0") + lp(description + b"\0")
    payload += struct.pack(f"<{len(words)}I", *words)
    if len(payload) > total_size:
        raise ValueError("fixture payload too large")
    return payload + b"\0" * (total_size - len(payload))


class AllReflectorTransformationFamilyEvidenceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.project = Path(self.temp.name) / "project"
        shutil.copytree(ROOT / "Blue_Reflection_Text_Tool", self.project / "Blue_Reflection_Text_Tool")
        workstream = self.project / "workstreams/quartet_restoration"
        workstream.mkdir(parents=True)
        shutil.copy2(STAGE77_SOURCE, workstream / STAGE77_SOURCE.name)
        self.reports = self.project / ".local/reports/quartet_restoration"
        self.workspace = self.project / ".local/build/quartet_restoration"
        self.reports.mkdir(parents=True)
        self.workspace.mkdir(parents=True)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def add_entry(self, entries: list[dict], path: str, source: bytes, target: bytes) -> None:
        source_ref = {"archive": "PACK01.PAK", "path": path, "sha256": hashlib.sha256(source).hexdigest(), "size": len(source)}
        target_ref = {"archive": "PACK11.PAK", "path": path, "sha256": hashlib.sha256(target).hexdigest(), "size": len(target)}
        entries.append({
            "normalized_path": path,
            "scope_status": "in_scope",
            "classification": "identical" if source == target else "changed",
            "source": source_ref,
            "target": target_ref,
        })
        source_file = BR.inventory_workspace_file(self.workspace, "source", "br1_events", source_ref["archive"], source_ref["path"])
        target_file = BR.inventory_workspace_file(self.workspace, "target", "br1_events", target_ref["archive"], target_ref["path"])
        source_file.parent.mkdir(parents=True, exist_ok=True)
        target_file.parent.mkdir(parents=True, exist_ok=True)
        source_file.write_bytes(source)
        target_file.write_bytes(target)

    def prepare_stage_reports(self) -> None:
        stage77 = self.reports / TOOL.STAGE77_DIR
        write_json(stage77 / "SUMMARY.json", {
            "type": "br_quartet_restoration_yuzuki_rfl50_event_binding_evidence_summary",
            "tool_version": "0.0.89",
            "status": "single_changed_yuzuki_rfl50_event_delta_confirmed_numeric_or_indexed_effect_binding_unresolved",
            "target_event_path": "event/skill/skill_party_yuzuki_rfl_50.ebd",
            "changed_yuzuki_rfl_rows": 1,
            "other_yuzuki_rfl_changed_rows": 0,
            "raimu_rfl50_identical": True,
            "effect_binding_candidate_rows": 0,
            "technical_identifier_rows": 0,
            "scene_local_target_word_delta_rows": 1,
        })
        stage76 = self.reports / TOOL.STAGE76_DIR
        write_json(stage76 / "SUMMARY.json", {
            "type": "br_quartet_restoration_transformation_brightness_evidence_summary",
            "tool_version": "0.0.88",
            "registry_profile_rows": 15,
            "direct_yuzu_transformation_brightness_rows": 0,
            "yuzu_or_yuzuki_rows": 35,
        })
        asset_fields = [
            "pair_id", "normalized_path", "classification", "scope_status", "source_size", "target_size",
            "character_hits", "transformation_hits", "brightness_hits", "body_hits", "evidence_score",
            "lead_classification", "review_status",
        ]
        asset_rows = []
        for index in list(range(0, 31)) + [50, 51]:
            path = f"event/skill/skill_party_yuzuki_rfl_{index}.ebd"
            changed = index == 50
            asset_rows.append({
                "pair_id": "br1_events", "normalized_path": path,
                "classification": "changed" if changed else "identical", "scope_status": "in_scope",
                "source_size": 1411 if changed else 512, "target_size": 1423 if changed else 512,
                "character_hits": "yuzu,yuzuki", "transformation_hits": "rfl", "brightness_hits": "", "body_hits": "",
                "evidence_score": 8 if changed else 7, "lead_classification": "yuzu_transformation_locator",
                "review_status": "path_locator_only_not_censorship_proof",
            })
        asset_rows.append({
            "pair_id": "br1_events", "normalized_path": "event/skill/skill_party_raimu_rfl_50.ebd",
            "classification": "identical", "scope_status": "in_scope", "source_size": 512, "target_size": 512,
            "character_hits": "", "transformation_hits": "rfl", "brightness_hits": "", "body_hits": "",
            "evidence_score": 3, "lead_classification": "transformation_or_character_locator",
            "review_status": "path_locator_only_not_censorship_proof",
        })
        write_tsv(stage76 / "TRANSFORMATION_BRIGHTNESS_ASSET_PATHS.tsv", asset_fields, asset_rows)
        review_fields = [
            "evidence_source", "pair_id", "candidate_id", "domain", "priority", "normalized_path", "member_name",
            "member_key", "setting_path", "source_value", "target_value", "change_classification", "character_hits",
            "transformation_hits", "brightness_hits", "body_hits", "evidence_score", "lead_classification", "review_status",
        ]
        write_tsv(stage76 / "TRANSFORMATION_BRIGHTNESS_FOCUSED_REVIEW.tsv", review_fields, [])

    def prepare_fixture(self, *, hinako_changed: bool = False) -> None:
        self.prepare_stage_reports()
        entries: list[dict] = []
        words = [0x75400009, 1, 0x77000001, 1, 0x7540000A, 2]
        for family, prefix in (("yuzuki", "skill_party"), ("raimu", "skill_party"), ("hinako", "skill")):
            for slot in (0, 50):
                path = f"event/skill/{prefix}_{family}_rfl_{slot}.ebd"
                total = 1411 if family == "yuzuki" and slot == 50 else 512
                source = make_ebd(b"description", words + [slot], total)
                target = source
                if family == "yuzuki" and slot == 50:
                    target = make_ebd(b"description", words + [0x00001600, 0x00009700, 0x00271073, 0x00000100], 1423)
                if hinako_changed and family == "hinako" and slot == 50:
                    target = make_ebd(b"description", words + [0x00002200, 0x00003300], 520)
                self.add_entry(entries, path, source, target)
        ordinary = make_ebd(b"description", words, 512)
        self.add_entry(entries, "event/skill/henshin_intro.ebd", ordinary, ordinary)
        write_json(self.reports / "differences/br1_events.json", {
            "source_archive_group": "br1_events",
            "entries": entries,
        })

    def test_build_report_audits_all_families_and_keeps_only_yuzuki_changed(self) -> None:
        self.prepare_fixture()
        output, archive, summary = TOOL.build_report(self.project, create_archive=False)
        self.assertIsNone(archive)
        self.assertEqual(summary["family_rows"], 3)
        self.assertEqual(summary["event_rows"], 6)
        self.assertEqual(summary["changed_event_rows"], 1)
        self.assertEqual(summary["other_than_stage77_yuzuki_changed_event_rows"], 0)
        families = TOOL.read_tsv(output / "ALL_REFLECTOR_TRANSFORMATION_FAMILIES.tsv")
        by_id = {row["family_id"]: row for row in families}
        self.assertEqual(by_id["skill:hinako"]["classification"], "fully_byte_identical_family")
        self.assertEqual(by_id["party:raimu"]["classification"], "fully_byte_identical_family")
        self.assertEqual(by_id["party:yuzuki"]["changed_event_rows"], "1")
        nonindexed = TOOL.read_tsv(output / "NON_INDEXED_TRANSFORMATION_EVENT_PATHS.tsv")
        self.assertEqual(len(nonindexed), 1)


    def test_linear_sequence_presence_handles_repetitive_words(self) -> None:
        haystack = [1] * 5000 + [2, 3, 4] + [1] * 5000
        self.assertTrue(TOOL.contains_word_sequence(haystack, [1, 2, 3, 4, 1]))
        self.assertFalse(TOOL.contains_word_sequence(haystack, [1, 2, 4]))

    def test_identical_controls_skip_full_sequence_matcher_analysis(self) -> None:
        self.prepare_fixture()
        stage77 = TOOL.load_stage77_module(self.project)
        original = stage77.analyze_pair
        analyzed_paths: list[str] = []

        def counted(br, normalized_path, source, target):
            analyzed_paths.append(normalized_path)
            return original(br, normalized_path, source, target)

        stage77.analyze_pair = counted
        with mock.patch.object(TOOL, "load_stage77_module", return_value=stage77):
            TOOL.build_report(self.project, create_archive=False)
        self.assertEqual(analyzed_paths, ["event/skill/skill_party_yuzuki_rfl_50.ebd"])

    def test_other_heroine_changed_event_is_reported_not_rejected(self) -> None:
        self.prepare_fixture(hinako_changed=True)
        output, _archive, summary = TOOL.build_report(self.project, create_archive=False)
        self.assertEqual(summary["changed_event_rows"], 2)
        self.assertEqual(summary["other_than_stage77_yuzuki_changed_event_rows"], 1)
        self.assertEqual(summary["other_than_stage77_yuzuki_changed_event_paths"], ["event/skill/skill_hinako_rfl_50.ebd"])
        changed = TOOL.read_tsv(output / "ALL_REFLECTOR_TRANSFORMATION_CHANGED_EVENTS.tsv")
        self.assertEqual({row["family_id"] for row in changed}, {"party:yuzuki", "skill:hinako"})


if __name__ == "__main__":
    unittest.main()
