#!/usr/bin/env python3
from __future__ import annotations

import csv
import hashlib
import importlib.util
import json
import subprocess
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCRIPT = HERE.parent / "collect_br1_official_source_retirement_closure_evidence.py"

spec = importlib.util.spec_from_file_location("stage108", SCRIPT)
assert spec and spec.loader
S = importlib.util.module_from_spec(spec)
spec.loader.exec_module(S)


def sha(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def write_tsv(path: Path, fields: list[str], rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def make_stage107_report(root: Path, verification: list[dict[str, object]]) -> Path:
    report = root / "stage107/br1_official_source_metadata_refresh_evidence"
    report.mkdir(parents=True)
    (report / "SUMMARY.json").write_text(json.dumps({
        "tool_version": "0.1.21",
        "status": "official_source_metadata_refresh_committed",
        "transaction_mode": "applied_transactionally",
        "official_archive_rows": 4,
        "refreshed_member_rows": 33,
        "classification_changed_rows": 0,
        "registered_profiles_affected": 0,
        "stage104_slot_light_evidence_independent": True,
        "underscore_archives_read": False,
        "underscore_archives_required_after_refresh": False,
        "underscore_archives_safe_to_delete": True,
    }), encoding="utf-8")
    write_tsv(report / "OFFICIAL_SOURCE_ARCHIVE_VERIFICATION.tsv", list(verification[0]), verification)
    archive = root / "stage107.tar.zst"
    subprocess.run(["tar", "--zstd", "-cf", str(archive), "-C", str(report.parent), report.name], check=True)
    return archive


def fixture(root: Path, *, underscore_present: bool = False, corrupt_official: bool = False) -> tuple[Path, Path, Path]:
    project = root / "project"
    game = root / "game"
    reports = project / ".local/reports/quartet_restoration"
    (reports / "inventories").mkdir(parents=True)
    (reports / "provenance").mkdir(parents=True)
    data = game / "DATA"
    data.mkdir(parents=True)

    verification = []
    source_archives = []
    ledger_archives = []
    expected = [
        "DATA/PACK00_02.PAK",
        "DATA/PACK00_04_1.PAK",
        "DATA/PACK00_04_2.PAK",
        "DATA/PACK00_04_3.PAK",
    ]
    for index, archive in enumerate(expected):
        payload = f"official-{index}".encode()
        official_path = game / archive
        official_path.write_bytes(payload + (b"!" if corrupt_official and index == 0 else b""))
        verification.append({
            "pair_id": f"pair-{index}",
            "archive": archive,
            "official_size": len(payload),
            "official_sha256": sha(payload),
            "extraction_mode": "fixture",
            "underscore_archive_read": False,
        })
        if underscore_present and index == 0:
            official_path.with_name(official_path.name + "_").write_bytes(b"historical")
        old_sha = sha(f"old-{index}".encode())
        source_archives.append({
            "archive": archive,
            "size": len(payload),
            "sha256": sha(payload),
            "extraction_status": "official_steam_canonical",
            "provenance": "official_steam_canonical",
            "preserved_untrusted_candidate": {
                "sha1": "a" * 40,
                "sha256": old_sha,
                "size": 10,
                "archive_filename": Path(archive).name + "_",
                "retained_as_file": False,
            },
        })
        ledger_archives.append({"archive": archive, "old_sha256": old_sha, "new_sha256": sha(payload)})

    source_inventory = {
        "type": "br_asset_inventory",
        "archives": source_archives,
        "files": [],
        "canonical_source_provenance": {
            "tool_version": "0.1.21",
            "stage": 107,
            "ledger": "provenance/br1_source_archive_provenance_ledger.json",
            "official_archives": 4,
            "refreshed_members": 33,
            "underscore_archives_required": False,
        },
    }
    (reports / "inventories/br1_assets.source.json").write_text(json.dumps(source_inventory), encoding="utf-8")
    ledger = {
        "type": "br1_source_archive_provenance_ledger",
        "format_version": 1,
        "tool_version": "0.1.21",
        "canonical_policy": {
            "official_nonunderscore_archives_are_canonical": True,
            "underscore_archives_are_historical_analysis_only": True,
            "underscore_archives_required_for_normal_workflow": False,
            "underscore_archives_safe_to_delete_after_committed_stage107": True,
        },
        "source_evidence": {
            "archive_pairs": 4,
            "changed_members": 33,
            "classification_changes": 0,
            "affected_registered_profiles": 0,
        },
        "archives": ledger_archives,
        "members": [{"member_path": f"member-{i}", "old_sha256": "a", "new_sha256": "b"} for i in range(33)],
        "retirement": {
            "preserved_files": [Path(x).name + "_" for x in expected],
            "file_payloads_retained_by_project": False,
            "hashes_and_member_level_diff_retained": True,
            "normal_workflow_dependency_after_refresh": False,
        },
    }
    (reports / "provenance/br1_source_archive_provenance_ledger.json").write_text(json.dumps(ledger), encoding="utf-8")
    return project, game, make_stage107_report(root, verification)


class RetirementClosureTest(unittest.TestCase):
    def test_collects_complete_closure_after_underscore_removal(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            project, game, report = fixture(root)
            output = root / "out.tar.zst"
            result = S.collect(project_root=project, game_root=game, stage107_report=report, output=output)
            summary = result["summary"]
            self.assertEqual(summary["status"], "underscore_archive_retirement_closed")
            self.assertEqual(summary["official_archives_verified"], 4)
            self.assertEqual(summary["underscore_archives_absent"], 4)
            self.assertEqual(summary["ledger_member_rows"], 33)
            self.assertTrue(summary["retirement_complete"])
            self.assertTrue(output.is_file())

    def test_fails_closed_while_underscore_archive_is_present(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            project, game, report = fixture(root, underscore_present=True)
            with self.assertRaisesRegex(S.Stage108Error, "still present"):
                S.collect(project_root=project, game_root=game, stage107_report=report, output=root / "out.tar.zst")

    def test_fails_closed_when_official_archive_drifts(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            project, game, report = fixture(root, corrupt_official=True)
            with self.assertRaisesRegex(S.Stage108Error, "size mismatch|SHA-256 mismatch"):
                S.collect(project_root=project, game_root=game, stage107_report=report, output=root / "out.tar.zst")


if __name__ == "__main__":
    unittest.main()
