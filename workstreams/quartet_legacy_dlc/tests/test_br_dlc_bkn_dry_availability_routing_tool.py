from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
TOOL = HERE / "br_dlc_bkn_dry_availability_routing_tool.py"
SPEC = importlib.util.spec_from_file_location("availability_tool", TOOL)
assert SPEC and SPEC.loader
MOD = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MOD
SPEC.loader.exec_module(MOD)


class AvailabilityRoutingToolTests(unittest.TestCase):
    def make_project(self, root: Path) -> tuple[Path, Path, Path, Path]:
        project = root / "project"
        ws = project / "workstreams/quartet_legacy_dlc"
        ws.mkdir(parents=True)
        (ws / "VERSION").write_text("0.0.56\n", encoding="utf-8")
        runtime = {
            "status": "accepted_failed_at_costume_visibility_stage",
            "tested_generation": 8,
            "tested_members": MOD.EXPECTED_MEMBERS,
            "observed_dressing_room_entries": list(MOD.RUNTIME_LABELS),
            "bkn_entry_visible": False,
            "accepted_interpretation": {
                "asset_installation_structurally_correct": True,
                "charabase_overlay_structurally_correct": True,
                "availability_ui_unlock_routing_restored": False,
                "availability_ui_unlock_routing_verified": False,
                "runtime_profile_complete": False,
            },
        }
        (ws / "BKN_DRY_GENERATION8_RUNTIME_VISIBILITY_RETURN.json").write_text(
            json.dumps(runtime), encoding="utf-8"
        )

        build = project / ".local/build/quartet_legacy_dlc/test"
        build.mkdir(parents=True)
        c10 = build / "PACK10_02.PAK"
        c12 = build / "PACK12.PAK"
        c10.write_bytes(b"candidate-pack10")
        c12.write_bytes(b"candidate-pack12")
        game = root / "quartet"
        (game / "Data").mkdir(parents=True)
        baseline10 = b"baseline-pack10"
        baseline12 = b"baseline-pack12"
        (game / "Data/PACK10_02.PAK").write_bytes(baseline10)
        (game / "Data/PACK12.PAK").write_bytes(baseline12)

        active = {
            "type": "validated_quartet_legacy_dlc_payload",
            "format_version": 1,
            "family_id": "bkn_dry",
            "generation": 8,
            "members": MOD.EXPECTED_MEMBERS,
            "source_kind": "validated_quartet_legacy_dlc_handoff",
            "target_id": "blue_reflection_quartet",
            "artifacts": [
                {
                    "target_path": "Data/PACK10_02.PAK",
                    "operation": "replace",
                    "candidate_relative_path": c10.relative_to(project).as_posix(),
                    "candidate_size": c10.stat().st_size,
                    "candidate_sha256": MOD.sha256_file(c10),
                    "baseline_size": len(baseline10),
                    "baseline_sha256": MOD.sha256_bytes(baseline10),
                },
                {
                    "target_path": "Data/PACK12.PAK",
                    "operation": "replace",
                    "candidate_relative_path": c12.relative_to(project).as_posix(),
                    "candidate_size": c12.stat().st_size,
                    "candidate_sha256": MOD.sha256_file(c12),
                    "baseline_size": len(baseline12),
                    "baseline_sha256": MOD.sha256_bytes(baseline12),
                },
            ],
            "transaction": {"group": "quartet_legacy_dlc_bkn_dry", "all_or_none": True, "commit_enabled": False},
        }
        active_path = project / ".local/reports/quartet_legacy_dlc/validated_payloads/ACTIVE.json"
        active_path.parent.mkdir(parents=True)
        active_path.write_text(json.dumps(active), encoding="utf-8")

        workspace = project / "titles/blue_reflection/workspace/quartet/archives/PACK12/saves/b1"
        (workspace / "chara").mkdir(parents=True)
        (workspace / "text_en").mkdir(parents=True)
        (workspace / "costume").mkdir(parents=True)
        (workspace / "chara/charabase.xml").write_text(
            '<?xml version="1.0" encoding="UTF-8"?><Root>'
            '<CharaBase BaseTag="PC00_DLC_BKN" Model="PC00/PC00_DLC_Bkn" defaultTexture="PC00/PC00_DLC_Bkn" />'
            '<CharaBase BaseTag="PC00_SCL" Model="PC00/PC00_Scl" defaultTexture="PC00/PC00_Scl" />'
            '</Root>', encoding="utf-8"
        )
        (workspace / "text_en/str_costume.xml").write_text(
            '<?xml version="1.0" encoding="UTF-8"?><Root>'
            '<String Id="10" Text="Hoshinomiya Uniform" />'
            '<String Id="11" Text="School Swimsuit" />'
            '<String Id="12" Text="Gym Uniform" />'
            '<String Id="13" Text="Cami" />'
            '</Root>', encoding="utf-8"
        )
        (workspace / "costume/costume.xml").write_text(
            '<?xml version="1.0" encoding="UTF-8"?><Root>'
            '<Costume BaseTag="PC00_SCL" ReleaseCondition="0" DisplayFlag="1" />'
            '<Costume BaseTag="PC00_DLC_BKN" ReleaseCondition="DLC" DisplayFlag="0" />'
            '</Root>', encoding="utf-8"
        )
        original = root / "original"
        original.mkdir()
        output = root / "report"
        return project, original, game, output

    def test_full_read_only_audit(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            project, original, game, output = self.make_project(Path(td))
            summary = MOD.run(project, original, game, output)
            self.assertEqual(summary["generation"], 8)
            self.assertFalse(summary["conclusion"]["pc08_build_allowed"])
            self.assertGreater(summary["workspace_scan"]["runtime_visible_label_hits"], 0)
            self.assertGreater(summary["workspace_scan"]["routing_field_candidates"], 0)
            self.assertTrue((output / "REPORT_MANIFEST.json").is_file())
            self.assertEqual((game / "Data/PACK10_02.PAK").read_bytes(), b"baseline-pack10")
            self.assertTrue(summary["installation"]["clean_baseline"])

    def test_installed_candidate_pair_is_accepted(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            project, original, game, output = self.make_project(Path(td))
            active = json.loads((project / ".local/reports/quartet_legacy_dlc/validated_payloads/ACTIVE.json").read_text())
            for artifact in active["artifacts"]:
                candidate = project / artifact["candidate_relative_path"]
                (game / artifact["target_path"]).write_bytes(candidate.read_bytes())
            summary = MOD.run(project, original, game, output)
            self.assertTrue(summary["installation"]["generation8_candidates_currently_installed"])

    def test_unknown_installed_state_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            project, original, game, output = self.make_project(Path(td))
            (game / "Data/PACK12.PAK").write_bytes(b"tampered")
            with self.assertRaises(MOD.AvailabilityRoutingError):
                MOD.run(project, original, game, output)

    def test_mixed_candidate_and_baseline_state_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            project, original, game, output = self.make_project(Path(td))
            active = json.loads((project / ".local/reports/quartet_legacy_dlc/validated_payloads/ACTIVE.json").read_text())
            first = active["artifacts"][0]
            candidate = project / first["candidate_relative_path"]
            (game / first["target_path"]).write_bytes(candidate.read_bytes())
            with self.assertRaises(MOD.AvailabilityRoutingError):
                MOD.run(project, original, game, output)

    def test_label_and_technical_hits_are_separate(self) -> None:
        record = MOD.XmlRecord(
            side="quartet",
            relative_path="quartet/test.xml",
            record_index=0,
            element="Row",
            attrs={"BaseTag": "PC00_DLC_BKN", "Text": "Cami"},
            text="",
            record_sha256="0" * 64,
        )
        result = MOD.analyze_records([record])
        self.assertEqual(len(result["technical"]), 1)
        self.assertEqual(len(result["labels"]), 1)

    def test_utf8_bom_with_cp932_body_falls_back_safely(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            workspace = Path(td) / "workspace"
            path = workspace / "quartet/mislabeled.xml"
            path.parent.mkdir(parents=True)
            xml = (
                '<?xml version="1.0" encoding="UTF-8"?><Root>'
                '<Row BaseTag="PC00_DLC_BKN" Text="テスト" />'
                '</Root>'
            )
            path.write_bytes(b"\xef\xbb\xbf" + xml.encode("cp932"))
            records = MOD.parse_xml_records(path, workspace)
            self.assertEqual(len(records), 1)
            self.assertEqual(records[0].attrs["Text"], "テスト")

    def test_unparseable_xml_is_reported_without_aborting_workspace_scan(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            project = Path(td) / "project"
            workspace = project / "titles/blue_reflection/workspace/quartet"
            workspace.mkdir(parents=True)
            (workspace / "broken.xml").write_bytes(b"<?xml version='1.0'?><Root><")
            records, failures = MOD.collect_workspace_records(project)
            self.assertEqual(records, [])
            self.assertEqual(len(failures), 1)
            self.assertEqual(failures[0]["status"], "parse_failed")


if __name__ == "__main__":
    unittest.main()
