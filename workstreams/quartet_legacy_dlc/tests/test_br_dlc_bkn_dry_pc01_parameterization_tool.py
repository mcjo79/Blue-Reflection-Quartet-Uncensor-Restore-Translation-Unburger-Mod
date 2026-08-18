from __future__ import annotations

import csv
import hashlib
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

MODULE_PATH = Path(__file__).resolve().parents[1] / "br_dlc_bkn_dry_pc01_parameterization_tool.py"
spec = importlib.util.spec_from_file_location("bkn_pc01_parameterization", MODULE_PATH)
assert spec and spec.loader
mod = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = mod
spec.loader.exec_module(mod)


class PC01ParameterizationTests(unittest.TestCase):
    def stage83_fixture(self, root: Path) -> None:
        candidates = root / "DLC_BKN_DRY_FAMILY_CANDIDATES.tsv"
        with candidates.open("w", encoding="utf-8", newline="") as handle:
            fields = [
                "character_id", "candidate_state", "source_parent_count", "source_parent_paths",
                "source_texture_count", "source_texture_paths", "evidence_rows", "gaps",
                "build_authorized", "install_authorized", "runtime_validated",
            ]
            writer = csv.DictWriter(handle, delimiter="\t", lineterminator="\n", fieldnames=fields)
            writer.writeheader()
            writer.writerow({
                "character_id": "PC00", "candidate_state": "already_handled_pc00_reference",
                "source_parent_count": "2", "source_parent_paths": "[]", "source_texture_count": "2",
                "source_texture_paths": "[]", "evidence_rows": "78", "gaps": "[]",
                "build_authorized": "false", "install_authorized": "false", "runtime_validated": "false",
            })
            for character in ("PC01", "PC02"):
                low = character.lower()
                writer.writerow({
                    "character_id": character,
                    "candidate_state": "metadata_ready_for_bounded_dry_probe",
                    "source_parent_count": "2",
                    "source_parent_paths": json.dumps([
                        f"data/x64/character/{low}/{low}_dlc_bkn.elixir.gz",
                        f"data/x64/character/{low}/{low}_dlc_bkn_w.elixir.gz",
                    ]),
                    "source_texture_count": "2",
                    "source_texture_paths": json.dumps([
                        f"data/x64/character/{low}/{low}_dlc_bkn.g1t",
                        f"data/x64/character/{low}/{low}_dlc_bkn_w.g1t",
                    ]),
                    "evidence_rows": "45", "gaps": "[]", "build_authorized": "false",
                    "install_authorized": "false", "runtime_validated": "false",
                })
        for name, rows in {
            "DLC_BKN_DRY_FAMILY_EVIDENCE_ROWS.tsv": [["character_id", "value"], ["PC01", "costume_pc01_bkn"]],
            "DLC_BKN_DRY_FAMILY_GAPS.tsv": [["scope", "character_id", "gap", "blocking"]],
            "DLC_BKN_DRY_FAMILY_REPORT_SOURCES.tsv": [["report", "sha256"], ["x.tsv", "0" * 64]],
        }.items():
            with (root / name).open("w", encoding="utf-8", newline="") as handle:
                csv.writer(handle, delimiter="\t", lineterminator="\n").writerows(rows)
        (root / "SUMMARY.json").write_text(json.dumps({
            "status": "metadata_collected", "build_authorized": False, "prepare_allowed": False,
            "commit_allowed": False, "installation_allowed": False,
            "runtime_validation_allowed": False, "wet_bkn_included": False,
        }) + "\n", encoding="utf-8")
        (root / "VALIDATION.json").write_text(json.dumps({"status": "pass"}) + "\n", encoding="utf-8")
        files = []
        for path in sorted(root.iterdir()):
            if path.name in {"REPORT_MANIFEST.json"}:
                continue
            data = path.read_bytes()
            files.append({"path": path.name, "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()})
        (root / "REPORT_MANIFEST.json").write_text(json.dumps({"files": files}) + "\n", encoding="utf-8")

    def test_selects_pc01_and_snapshots_source(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            stage = base / "stage83"
            workstream = base / "workstream"
            output = base / "output"
            stage.mkdir(); workstream.mkdir()
            self.stage83_fixture(stage)
            (workstream / "tool.py").write_text(
                'OWNER = "costume_pc00_bkn"\nTAG = "PC00_DLC_BKN"\n', encoding="utf-8"
            )
            summary = mod.collect(workstream, output, stage83_dir=stage)
            mod.validate(output)
            self.assertEqual(summary["selected_character_id"], "PC01")
            self.assertGreater(summary["parameterization_point_count"], 0)
            self.assertTrue((output / "SOURCE_SNAPSHOTS/tool.py").is_file())

    def test_rejects_machine_specific_path_in_production_source(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            stage = base / "stage83"; workstream = base / "workstream"; output = base / "output"
            stage.mkdir(); workstream.mkdir(); self.stage83_fixture(stage)
            sep = chr(47)
            machine_path = sep.join(["", "home", "example", "project"])
            (workstream / "tool.py").write_text(
                f'ROOT = "{machine_path}"\nOWNER = "costume_pc00_bkn"\n', encoding="utf-8"
            )
            with self.assertRaises(mod.AuditError):
                mod.collect(workstream, output, stage83_dir=stage)

    def test_rejects_tampered_stage83_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp); stage = base / "stage83"; stage.mkdir(); self.stage83_fixture(stage)
            (stage / "SUMMARY.json").write_text("{}\n", encoding="utf-8")
            with self.assertRaises(mod.AuditError):
                mod.load_stage83_directory(stage)


if __name__ == "__main__":
    unittest.main()
