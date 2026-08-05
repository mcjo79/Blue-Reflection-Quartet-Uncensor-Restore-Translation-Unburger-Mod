#!/usr/bin/env python3
from __future__ import annotations

import csv
import json
import subprocess
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
COLLECTOR = HERE.parent / "collect_br1_official_source_inventory_refresh_preview_evidence.py"


def write_tsv(path: Path, fields: list[str], rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def make_stage105_report(root: Path, changed: list[dict[str, str]], pairs: list[dict[str, str]]) -> Path:
    report = root / "stage105" / "br1_source_archive_provenance_evidence"
    report.mkdir(parents=True)
    (report / "SUMMARY.json").write_text(json.dumps({
        "tool_version": "0.1.19",
        "changed_member_rows": 33,
        "layout_changed_member_rows": 0,
        "affected_registered_profile_rows": 0,
        "unaffected_registered_profile_rows": 15,
        "stage104_slot_light_evidence_independent": True,
        "direct_changed_member_dependency_artifact_rows": 26,
    }), encoding="utf-8")
    write_tsv(report / "SOURCE_ARCHIVE_PROVENANCE_PAIRS.tsv", list(pairs[0]), pairs)
    write_tsv(report / "SOURCE_ARCHIVE_CHANGED_MEMBERS.tsv", list(changed[0]), changed)
    dependencies = [{
        "artifact_path": f"artifact_{i}.tsv",
        "artifact_scope": "report_metadata",
        "dependency_classification": "direct_changed_member_dependency",
        "changed_member_count": "1",
        "required_action": "recheck_report_rows_referencing_changed_members",
    } for i in range(26)]
    dependencies += [{
        "artifact_path": f"identity_{i}.json",
        "artifact_scope": "build_or_payload_metadata",
        "dependency_classification": "archive_identity_reference_without_direct_changed_member",
        "changed_member_count": "0",
        "required_action": "retain_result_add_provenance_note_only",
    } for i in range(8)]
    write_tsv(report / "SOURCE_ARCHIVE_WORKSTREAM_DEPENDENCIES.tsv", list(dependencies[0]), dependencies)
    archive = root / "stage105.tar.zst"
    subprocess.run(["tar", "--zstd", "-cf", str(archive), "-C", str(report.parent), report.name], check=True)
    return archive


def fixture(root: Path, break_hash: bool = False) -> tuple[Path, Path]:
    reports = root / ".local/reports/quartet_restoration"
    (reports / "inventories").mkdir(parents=True)
    (reports / "differences").mkdir(parents=True)
    archives = [
        ("pack00_02", "DATA/PACK00_02.PAK", 30),
        ("pack00_04_1", "DATA/PACK00_04_1.PAK", 1),
        ("pack00_04_2", "DATA/PACK00_04_2.PAK", 1),
        ("pack00_04_3", "DATA/PACK00_04_3.PAK", 1),
    ]
    pairs: list[dict[str, str]] = []
    changed: list[dict[str, str]] = []
    source_archives = []
    source_files = []
    target_files = []
    diff_entries = []
    ordinal = 0
    for pair_id, canonical, count in archives:
        preserved_sha = (pair_id + "_preserved").encode().hex().ljust(64, "0")[:64]
        official_sha = (pair_id + "_official").encode().hex().ljust(64, "1")[:64]
        pairs.append({
            "pair_id": pair_id,
            "canonical_archive": canonical,
            "preserved_filename": canonical.split("/")[-1] + "_",
            "official_filename": canonical.split("/")[-1],
            "preserved_size": "1000",
            "official_size": "1000",
            "preserved_sha1": ("a" * 40),
            "official_sha1": ("b" * 40),
            "preserved_sha256": preserved_sha,
            "official_sha256": official_sha,
            "preserved_extraction_mode": "synthetic",
            "official_extraction_mode": "synthetic",
            "preserved_member_count": str(count),
            "official_member_count": str(count),
            "identical_member_rows": "0",
            "changed_payload_rows": str(count),
            "layout_changed_rows": "0",
            "added_member_rows": "0",
            "removed_member_rows": "0",
            "prior_inventory_binding": "prior_inventory_matches_preserved_untrusted",
        })
        source_archives.append({"archive": canonical, "size": 1000, "sha256": preserved_sha, "extraction_status": "unchanged"})
        for local in range(count):
            path = f"data/x64/synthetic/{pair_id}_{local:02d}.g1t"
            old_hash = f"{ordinal + 1:064x}"
            new_hash = f"{ordinal + 1001:064x}"
            if break_hash and ordinal == 0:
                inventory_hash = "f" * 64
            else:
                inventory_hash = old_hash
            dlc = "legacy_or_dlc_named" if ordinal >= 20 else "base_or_unspecified"
            changed.append({
                "pair_id": pair_id,
                "member_path": path,
                "member_basename": Path(path).name,
                "status": "payload_changed_layout_stable",
                "asset_type": "texture",
                "asset_domain": "character",
                "dlc_classification": dlc,
                "preserved_index": str(local),
                "official_index": str(local),
                "preserved_offset": "-1",
                "official_offset": "-1",
                "preserved_size": "44",
                "official_size": "44",
                "preserved_sha256": old_hash,
                "official_sha256": new_hash,
            })
            source_files.append({
                "archive": canonical,
                "path": path,
                "normalized_path": path,
                "comparison_key": path,
                "normalization_rule": None,
                "size": 44,
                "sha256": inventory_hash,
                "extension": ".g1t",
                "asset_type": "texture",
                "magic_hex": "00",
                "sample_block_size": 4096,
                "sample_hashes": [inventory_hash],
                "normalized_path_collision_count": 1,
            })
            old_class = "changed" if ordinal < 20 else "removed_in_target"
            target = None
            if ordinal < 20:
                target = {
                    "archive": "Data/PACK10_02.PAK",
                    "path": "data/b1/" + path.removeprefix("data/"),
                    "normalized_path": path,
                    "comparison_key": path,
                    "size": 44,
                    "sha256": f"{ordinal + 2001:064x}",
                    "extension": ".g1t",
                    "asset_type": "texture",
                    "magic_hex": "00",
                    "sample_block_size": 4096,
                    "sample_hashes": [],
                    "normalized_path_collision_count": 1,
                }
                target_files.append(target)
            diff_entries.append({
                "difference_id": f"diff_{ordinal:020d}",
                "classification": old_class,
                "normalized_path": path,
                "source": source_files[-1],
                "target": target,
            })
            ordinal += 1
    assert ordinal == 33
    source_inventory = {"archives": source_archives, "files": source_files}
    target_inventory = {"archives": [], "files": target_files}
    difference_report = {"entries": diff_entries}
    (reports / "inventories/br1_assets.source.json").write_text(json.dumps(source_inventory), encoding="utf-8")
    (reports / "inventories/br1_assets.target.json").write_text(json.dumps(target_inventory), encoding="utf-8")
    (reports / "differences/br1_assets.json").write_text(json.dumps(difference_report), encoding="utf-8")
    paths = [row["member_path"] for row in changed]
    (reports / "REVIEW_QUEUE.tsv").write_text("source_path\n" + "\n".join(paths[:20]) + "\n", encoding="utf-8")
    (reports / "FOCUSED_REVIEW_QUEUE.tsv").write_text("source_path\n" + "\n".join(paths[:17]) + "\n", encoding="utf-8")
    (reports / "DEFERRED_QUEUE.tsv").write_text("source_path\n" + "\n".join(paths[20:]) + "\n", encoding="utf-8")
    stage105 = make_stage105_report(root, changed, pairs)
    return stage105, reports


class Stage106Tests(unittest.TestCase):
    def test_preview_preserves_classifications_and_writes_no_existing_reports(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            stage105, reports = fixture(root)
            before = (reports / "inventories/br1_assets.source.json").read_bytes()
            output = root / "preview.tar.zst"
            subprocess.run([
                "python3", str(COLLECTOR), "--project-root", str(root),
                "--stage105-report", str(stage105), "--output", str(output),
            ], check=True)
            self.assertEqual(before, (reports / "inventories/br1_assets.source.json").read_bytes())
            extract = root / "extract"
            extract.mkdir()
            subprocess.run(["tar", "--zstd", "-xf", str(output), "-C", str(extract)], check=True)
            summary = json.loads((extract / "br1_official_source_inventory_refresh_preview_evidence/SUMMARY.json").read_text())
            self.assertEqual(summary["archive_replacement_rows"], 4)
            self.assertEqual(summary["member_replacement_rows"], 33)
            self.assertEqual(summary["classification_changed_rows"], 0)
            self.assertEqual(summary["new_classification_counts"], {"changed": 20, "removed_in_target": 13})
            self.assertFalse(summary["policy"]["existing_reports_modified"])
            self.assertFalse(summary["policy"]["pak_write_authorized"])

    def test_fails_closed_when_prior_source_row_no_longer_matches_preserved_hash(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            stage105, _ = fixture(root, break_hash=True)
            result = subprocess.run([
                "python3", str(COLLECTOR), "--project-root", str(root),
                "--stage105-report", str(stage105), "--output", str(root / "preview.tar.zst"),
            ], text=True, capture_output=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("source member hash does not match preserved candidate", result.stderr)


if __name__ == "__main__":
    unittest.main()
