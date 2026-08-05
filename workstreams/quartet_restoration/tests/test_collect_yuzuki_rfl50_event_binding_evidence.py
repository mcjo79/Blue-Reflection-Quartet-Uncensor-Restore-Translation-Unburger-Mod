from __future__ import annotations

import csv
import hashlib
import importlib.util
import json
import shutil
import struct
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
TOOL_PATH = ROOT / "workstreams/quartet_restoration/collect_yuzuki_rfl50_event_binding_evidence.py"
BR_PATH = ROOT / "Blue_Reflection_Text_Tool/br_restoration_tool.py"


def load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


TOOL = load_module(TOOL_PATH, "collect_yuzuki_rfl50_event_binding_evidence_for_test")
BR = load_module(BR_PATH, "br_restoration_tool_for_yuzuki_test")


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


class YuzukiRfl50BindingEvidenceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.project = Path(self.temp.name) / "project"
        shutil.copytree(ROOT / "Blue_Reflection_Text_Tool", self.project / "Blue_Reflection_Text_Tool")
        (self.project / "workstreams/quartet_restoration").mkdir(parents=True)
        self.reports = self.project / ".local/reports/quartet_restoration"
        self.workspace = self.project / ".local/build/quartet_restoration"
        self.reports.mkdir(parents=True)
        self.workspace.mkdir(parents=True)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def add_entry(self, entries: list[dict], path: str, source: bytes, target: bytes, *, classification: str) -> None:
        source_ref = {"archive": "PACK01.PAK", "path": path, "sha256": hashlib.sha256(source).hexdigest(), "size": len(source)}
        target_ref = {"archive": "PACK11.PAK", "path": path, "sha256": hashlib.sha256(target).hexdigest(), "size": len(target)}
        entries.append({
            "normalized_path": path,
            "scope_status": "in_scope",
            "classification": classification,
            "source": source_ref,
            "target": target_ref,
        })
        source_file = BR.inventory_workspace_file(self.workspace, "source", "br1_events", source_ref["archive"], source_ref["path"])
        target_file = BR.inventory_workspace_file(self.workspace, "target", "br1_events", target_ref["archive"], target_ref["path"])
        source_file.parent.mkdir(parents=True, exist_ok=True)
        target_file.parent.mkdir(parents=True, exist_ok=True)
        source_file.write_bytes(source)
        target_file.write_bytes(target)

    def prepare_fixture(self, *, second_changed: bool = False) -> None:
        stage76 = self.reports / "transformation_brightness_evidence"
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
        asset_rows: list[dict] = []
        entries: list[dict] = []
        source_words = [0x75400009, 1, 0x77000001, 1, 0x7540000A, 2]
        target_words = source_words + [0x7A000001, 5, 6]
        source_target = make_ebd(b"description", source_words, 1411)
        target_target = make_ebd(b"pc01_rfl_w", target_words, 1423)
        self.add_entry(entries, TOOL.TARGET_PATH, source_target, target_target, classification="changed")
        asset_rows.append({
            "pair_id": "br1_events", "normalized_path": TOOL.TARGET_PATH, "classification": "changed",
            "scope_status": "in_scope", "source_size": 1411, "target_size": 1423, "character_hits": "yuzu,yuzuki",
            "transformation_hits": "rfl", "brightness_hits": "", "body_hits": "", "evidence_score": 8,
            "lead_classification": "yuzu_transformation_locator", "review_status": "path_locator_only_not_censorship_proof",
        })
        for index in list(range(0, 31)) + [51]:
            path = f"event/skill/skill_party_yuzuki_rfl_{index}.ebd"
            if path == TOOL.TARGET_PATH:
                continue
            payload = make_ebd(b"description", source_words + [index], 512)
            target = payload
            classification = "identical"
            if second_changed and index == 1:
                target = payload[:-4] + b"ABCD"
                classification = "changed"
            self.add_entry(entries, path, payload, target, classification=classification)
            asset_rows.append({
                "pair_id": "br1_events", "normalized_path": path, "classification": classification,
                "scope_status": "in_scope", "source_size": len(payload), "target_size": len(target),
                "character_hits": "yuzu,yuzuki", "transformation_hits": "rfl", "brightness_hits": "", "body_hits": "",
                "evidence_score": 7, "lead_classification": "yuzu_transformation_locator",
                "review_status": "path_locator_only_not_censorship_proof",
            })
        control = make_ebd(b"description", source_words + [50], 512)
        self.add_entry(entries, TOOL.CONTROL_PATH, control, control, classification="identical")
        asset_rows.append({
            "pair_id": "br1_events", "normalized_path": TOOL.CONTROL_PATH, "classification": "identical",
            "scope_status": "in_scope", "source_size": len(control), "target_size": len(control), "character_hits": "",
            "transformation_hits": "rfl", "brightness_hits": "", "body_hits": "", "evidence_score": 3,
            "lead_classification": "transformation_or_character_locator", "review_status": "path_locator_only_not_censorship_proof",
        })
        write_tsv(stage76 / "TRANSFORMATION_BRIGHTNESS_ASSET_PATHS.tsv", asset_fields, asset_rows)
        review_fields = [
            "evidence_source", "pair_id", "candidate_id", "domain", "priority", "normalized_path", "member_name",
            "member_key", "setting_path", "source_value", "target_value", "change_classification", "character_hits",
            "transformation_hits", "brightness_hits", "body_hits", "evidence_score", "lead_classification", "review_status",
        ]
        write_tsv(stage76 / "TRANSFORMATION_BRIGHTNESS_FOCUSED_REVIEW.tsv", review_fields, [{
            "evidence_source": "PAYLOAD_BINARY_DELTA.tsv", "pair_id": "", "candidate_id": "effect_pc01",
            "domain": "wet_fabric_material_response", "priority": "high",
            "normalized_path": "data/x64/effect/1001_pc01.elixir.gz", "member_name": "e_PC01_ringlight_00.g1e",
            "member_key": "e_pc01_ringlight_00.g1e#0", "setting_path": "", "source_value": "", "target_value": "",
            "change_classification": "changed", "character_hits": "", "transformation_hits": "change",
            "brightness_hits": "light", "body_hits": "chara,character", "evidence_score": 9,
            "lead_classification": "transformation_body_brightness_lead",
            "review_status": "user_reported_transformation_brightness_lead_requires_asset_and_runtime_confirmation",
        }])
        write_json(self.reports / "differences/br1_events.json", {
            "source_archive_group": "br1_events",
            "entries": entries,
        })

    def test_build_report_localizes_event_and_pc01_effect_family(self) -> None:
        self.prepare_fixture()
        output, archive, summary = TOOL.build_report(self.project, create_archive=False)
        self.assertIsNone(archive)
        self.assertEqual(summary["changed_yuzuki_rfl_rows"], 1)
        self.assertTrue(summary["raimu_rfl50_identical"])
        self.assertGreaterEqual(summary["target_only_technical_identifier_rows"], 1)
        self.assertGreaterEqual(summary["effect_binding_candidate_rows"], 1)
        bindings = TOOL.read_tsv(output / "YUZUKI_RFL50_EFFECT_BINDING_CANDIDATES.tsv")
        self.assertTrue(any(row["binding_basis"] == "character_slot_family_match" and row["matched_identifier"] == "pc01" for row in bindings))
        controls = TOOL.read_tsv(output / "YUZUKI_RFL50_CONTROL_COMPARISON.tsv")
        self.assertEqual(controls[0]["classification"], "single_changed_yuzuki_rfl50_event_with_identical_same_slot_and_family_controls")

    def test_second_changed_yuzuki_event_fails_closed(self) -> None:
        self.prepare_fixture(second_changed=True)
        with self.assertRaisesRegex(TOOL.YuzukiRfl50BindingError, "exactly one changed Yuzuki RFL event"):
            TOOL.build_report(self.project, create_archive=False)


if __name__ == "__main__":
    unittest.main()
