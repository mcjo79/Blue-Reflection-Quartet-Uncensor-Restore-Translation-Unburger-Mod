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
SCRIPT = HERE.parent / "apply_br1_official_source_metadata_refresh.py"
TOOL_SOURCE = HERE.parents[2] / "Blue_Reflection_Text_Tool" / "br_restoration_tool.py"

spec = importlib.util.spec_from_file_location("stage107", SCRIPT)
assert spec and spec.loader
S = importlib.util.module_from_spec(spec)
spec.loader.exec_module(S)


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def write_tsv(path: Path, fields: list[str], rows: list[dict[str, object]], crlf: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, delimiter="\t", lineterminator="\r\n" if crlf else "\n")
        writer.writeheader()
        writer.writerows(rows)


def load_tool(project: Path):
    path = project / "Blue_Reflection_Text_Tool/br_restoration_tool.py"
    spec2 = importlib.util.spec_from_file_location("fixture_br", path)
    assert spec2 and spec2.loader
    module = importlib.util.module_from_spec(spec2)
    spec2.loader.exec_module(module)
    return module


def make_stage106_report(root: Path, archives: list[dict[str, str]], members: list[dict[str, str]], diffs: list[dict[str, str]], queues: list[dict[str, str]]) -> Path:
    report = root / "stage106/br1_official_source_inventory_refresh_preview_evidence"
    report.mkdir(parents=True)
    (report / "SUMMARY.json").write_text(json.dumps({
        "tool_version": "0.1.20",
        "archive_replacement_rows": 4,
        "member_replacement_rows": 33,
        "classification_changed_rows": 0,
        "affected_registered_profile_rows": 0,
        "stage104_slot_light_evidence_independent": True,
    }), encoding="utf-8")
    write_tsv(report / "OFFICIAL_SOURCE_ARCHIVE_REPLACEMENTS.tsv", list(archives[0]), archives)
    write_tsv(report / "OFFICIAL_SOURCE_MEMBER_REPLACEMENTS.tsv", list(members[0]), members)
    write_tsv(report / "OFFICIAL_SOURCE_DIFF_RECLASSIFICATION.tsv", list(diffs[0]), diffs)
    write_tsv(report / "OFFICIAL_SOURCE_QUEUE_REVALIDATION.tsv", list(queues[0]), queues)
    archive = root / "stage106.tar.zst"
    subprocess.run(["tar", "--zstd", "-cf", str(archive), "-C", str(report.parent), report.name], check=True)
    return archive


def fixture(root: Path, *, corrupt_official: bool = False) -> tuple[Path, Path, Path]:
    project = root / "project"
    game = root / "game"
    data = game / "DATA"
    data.mkdir(parents=True)
    (project / "Blue_Reflection_Text_Tool").mkdir(parents=True)
    (project / "Blue_Reflection_Text_Tool/br_restoration_tool.py").write_bytes(TOOL_SOURCE.read_bytes())
    br = load_tool(project)
    reports = project / ".local/reports/quartet_restoration"
    (reports / "inventories").mkdir(parents=True)
    (reports / "differences").mkdir(parents=True)
    (reports / "provenance").mkdir(parents=True)

    pair_defs = [
        ("pack00_02", "DATA/PACK00_02.PAK", 30),
        ("pack00_04_1", "DATA/PACK00_04_1.PAK", 1),
        ("pack00_04_2", "DATA/PACK00_04_2.PAK", 1),
        ("pack00_04_3", "DATA/PACK00_04_3.PAK", 1),
    ]
    archive_rows: list[dict[str, str]] = []
    member_rows: list[dict[str, str]] = []
    diff_preview: list[dict[str, str]] = []
    queue_preview: list[dict[str, str]] = []
    source_archives = []
    source_files = []
    target_files = []
    diff_entries = []
    changed_paths: list[str] = []
    official_payload_by_pair: dict[str, list[tuple[str, bytes]]] = {}

    ordinal = 0
    for pair_id, archive_rel, count in pair_defs:
        archive_payload = (f"official-{pair_id}-archive").encode("utf-8")
        archive_path = game / archive_rel
        archive_path.parent.mkdir(parents=True, exist_ok=True)
        archive_path.write_bytes(archive_payload + (b"x" if corrupt_official and pair_id == "pack00_02" else b""))
        official_sha = sha(archive_payload)
        old_archive_sha = sha((f"preserved-{pair_id}-archive").encode("utf-8"))
        archive_rows.append({
            "pair_id": pair_id,
            "archive": archive_rel,
            "old_provenance": "preserved_untrusted_candidate",
            "new_provenance": "official_steam_canonical",
            "old_sha1": "a" * 40,
            "new_sha1": "b" * 40,
            "old_sha256": old_archive_sha,
            "new_sha256": official_sha,
            "old_size": str(len(archive_payload)),
            "new_size": str(len(archive_payload)),
            "member_count": str(count),
            "changed_member_count": str(count),
            "layout_changed_member_count": "0",
            "required_action": "replace_archive_identity_in_canonical_source_inventory",
        })
        source_archives.append({"archive": archive_rel, "size": len(archive_payload), "sha256": old_archive_sha, "extraction_status": "unchanged"})
        official_payload_by_pair[pair_id] = []

        for local in range(count):
            if pair_id == "pack00_02":
                if local < 17:
                    member_path = f"data/x64/character/pc{local:02d}/pc{local:02d}_scl_w.g1t"
                    classification = "changed"
                elif local == 17:
                    member_path = "data/x64/character/pc17/pc17_dlc_twl_w.g1t"
                    classification = "changed"
                else:
                    member_path = f"data/x64/character/pc{local:02d}/pc{local:02d}_dlc_vac_w.g1t"
                    classification = "removed_in_target"
            elif pair_id == "pack00_04_1":
                member_path = "data/x64/res_en/layout/external/23_moviechannel.kslt"
                classification = "changed"
            elif pair_id == "pack00_04_2":
                member_path = "data/x64/res_ch/layout/external/23_moviechannel.kslt"
                classification = "removed_in_target"
            else:
                member_path = "data/x64/res_jp/layout/external/23_moviechannel.kslt"
                classification = "changed"

            old_payload = (f"old-{ordinal}-payload").encode("utf-8")
            new_payload = (f"new-{ordinal}-payload").encode("utf-8")
            old_sha = sha(old_payload)
            new_sha = sha(new_payload)
            official_payload_by_pair[pair_id].append((member_path, new_payload))
            changed_paths.append(member_path)
            dlc = "legacy_or_dlc_named" if "dlc" in member_path else "base_or_unspecified"
            asset_type = "texture" if member_path.endswith(".g1t") else "kslt"
            asset_domain = "character" if "/character/" in member_path else "interface"
            member_rows.append({
                "pair_id": pair_id,
                "archive": archive_rel,
                "member_path": member_path,
                "asset_type": asset_type,
                "asset_domain": asset_domain,
                "dlc_classification": dlc,
                "old_provenance": "preserved_untrusted_candidate",
                "new_provenance": "official_steam_canonical",
                "old_sha256": old_sha,
                "new_sha256": new_sha,
                "old_size": str(len(old_payload)),
                "new_size": str(len(new_payload)),
                "layout_stable": "True",
                "comparison_key": member_path,
                "required_action": "replace_source_inventory_hash_and_provenance_only",
            })
            source_row = {
                "archive": archive_rel,
                "path": member_path,
                "normalized_path": member_path,
                "comparison_key": member_path.casefold(),
                "normalization_rule": None,
                "size": len(old_payload),
                "sha256": old_sha,
                "extension": Path(member_path).suffix.casefold(),
                "asset_type": "texture" if member_path.endswith(".g1t") else "binary_or_unknown",
                "magic_hex": old_payload[:16].hex(),
                "sample_block_size": br.SAMPLE_BLOCK_SIZE,
                "sample_hashes": [old_sha],
                "normalized_path_collision_count": 1,
            }
            source_files.append(source_row)
            target_row = None
            if classification == "changed":
                target_payload = (f"target-{ordinal}-payload").encode("utf-8")
                target_row = {
                    "archive": "Data/PACK10_02.PAK" if member_path.endswith(".g1t") else "Data/PACK10_04_01.PAK",
                    "path": "data/b1/" + member_path.removeprefix("data/"),
                    "normalized_path": member_path,
                    "comparison_key": member_path.casefold(),
                    "normalization_rule": None,
                    "size": len(target_payload),
                    "sha256": sha(target_payload),
                    "extension": Path(member_path).suffix.casefold(),
                    "asset_type": source_row["asset_type"],
                    "magic_hex": target_payload[:16].hex(),
                    "sample_block_size": br.SAMPLE_BLOCK_SIZE,
                    "sample_hashes": [sha(target_payload)],
                    "normalized_path_collision_count": 1,
                }
                target_files.append(target_row)
            scope, reason = br.scope_status(classification, member_path, source_row, target_row)
            priority = br.manual_review_priority(classification, source_row, scope)
            diff_entry = {
                "difference_id": "diff_" + hashlib.sha256((classification + member_path).encode()).hexdigest()[:20],
                "classification": classification,
                "normalized_path": member_path,
                "source": br.file_ref(source_row),
                "target": br.file_ref(target_row),
                "binary_similarity": 0.0,
                "binary_similarity_method": "bounded_sample_hash_alignment_and_jaccard",
                "size_ratio": br.size_ratio(source_row, target_row) if target_row else 0.0,
                "confidence": "exact_path" if target_row else "structural",
                "mapping_basis": "normalized_path" if target_row else "no_target_match",
                "scope_status": scope,
                "scope_reason": reason,
                "manual_review_priority": priority,
                "dependencies": [],
                "references": [],
                "review_classification": "not_assessed",
                "review_note": "A structural or binary difference is not automatically a censorship change.",
            }
            diff_entries.append(diff_entry)
            diff_preview.append({
                "pair_id": pair_id,
                "member_path": member_path,
                "comparison_key": member_path,
                "old_difference_id": diff_entry["difference_id"],
                "canonical_difference_id": diff_entry["difference_id"],
                "old_classification": classification,
                "new_classification": classification,
                "classification_changed": "False",
                "official_source_sha256": new_sha,
                "target_match_count": "1" if target_row else "0",
                "target_archive": target_row["archive"] if target_row else "",
                "target_sha256": target_row["sha256"] if target_row else "",
                "semantic_conclusion": "none_provenance_only",
            })
            queue_preview.append({
                "member_path": member_path,
                "old_queue_memberships": "",
                "old_queue_membership_count": "0",
                "new_classification": classification,
                "recommended_queue_action": "refresh",
                "automatic_row_write_authorized": "False",
            })
            ordinal += 1

    assert ordinal == 33
    source_inventory = {
        "type": "br_asset_inventory", "format_version": 1, "tool_version": "0.0.3",
        "target_id": "blue_reflection_original", "archive_group": "br1_assets",
        "normalization_side": "source", "archives": source_archives, "files": source_files,
        "summary": {"archives": 4, "files": 33, "bytes": sum(row["size"] for row in source_files)},
    }
    target_inventory = {
        "type": "br_asset_inventory", "format_version": 1, "tool_version": "0.0.3",
        "target_id": "blue_reflection_quartet", "archive_group": "br1_assets",
        "normalization_side": "target", "archives": [], "files": target_files,
        "summary": {"archives": 0, "files": len(target_files)},
    }
    difference_report = {
        "type": "br_asset_difference_report", "format_version": 1, "tool_version": "0.0.3",
        "source_archive_group": "br1_assets", "entries": diff_entries,
        "summary": {
            "entries": 33,
            "classifications": {"changed": 20, "removed_in_target": 13},
            "manual_review_priorities": {}, "scope_statuses": {},
        },
    }
    (reports / "inventories/br1_assets.source.json").write_text(json.dumps(source_inventory, indent=2) + "\n", encoding="utf-8")
    (reports / "inventories/br1_assets.target.json").write_text(json.dumps(target_inventory, indent=2) + "\n", encoding="utf-8")
    (reports / "differences/br1_assets.json").write_text(json.dumps(difference_report, indent=2) + "\n", encoding="utf-8")

    for name in [
        "br1_events.source.json", "br1_events.target.json", "br1_language.source.json", "br1_language.target.json",
    ]:
        (reports / "inventories" / name).write_text("{}\n", encoding="utf-8")
    for name in ["br1_events.json", "br1_language.json"]:
        (reports / "differences" / name).write_text("{}\n", encoding="utf-8")

    review_rows, focused_rows, deferred_rows = [], [], []
    for entry in diff_entries:
        row = br.review_row("br1_assets", entry)
        if entry["scope_status"] == "in_scope":
            review_rows.append(row)
            if int(row["focus_score"]) >= 60:
                focused_rows.append(row)
        else:
            deferred_rows.append(row)
    fields = list(review_rows[0])
    write_tsv(reports / "REVIEW_QUEUE.tsv", fields, review_rows, crlf=True)
    write_tsv(reports / "FOCUSED_REVIEW_QUEUE.tsv", fields, focused_rows, crlf=True)
    write_tsv(reports / "DEFERRED_QUEUE.tsv", fields, deferred_rows, crlf=True)
    archive_inventory_rows = [{
        "pair_id": "br1_assets", "category": "assets", "side": "source",
        "target_id": "blue_reflection_original", "archive": row["archive"],
        "size": row["size"], "sha256": row["sha256"], "extraction_status": row["extraction_status"],
    } for row in source_archives]
    write_tsv(reports / "ARCHIVE_INVENTORY.tsv", list(archive_inventory_rows[0]), archive_inventory_rows, crlf=True)
    (reports / "SUMMARY.json").write_text(json.dumps({"type": "summary", "classifications": {"changed": 20, "removed_in_target": 13}}, indent=2) + "\n", encoding="utf-8")

    # Create official extraction caches keyed only by official SHA-256.
    for pair_id, archive_rel, _ in pair_defs:
        archive_payload = (f"official-{pair_id}-archive").encode("utf-8")
        official_sha = sha(archive_payload)
        workspace = project / f".local/workspaces/quartet_restoration/synthetic/{pair_id}"
        workspace.mkdir(parents=True)
        manifest_rows = []
        for index, (member_path, payload) in enumerate(official_payload_by_pair[pair_id]):
            target = workspace / member_path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(payload)
            manifest_rows.append({"name": member_path, "offset": 100 + index * 100, "size": len(payload), "flags": 0, "key": "00"})
        manifest_name = Path(archive_rel).stem + ".json"
        (workspace / manifest_name).write_text(json.dumps({
            "name": Path(archive_rel).name, "version": 1, "flags": 0,
            "nb_files": len(manifest_rows), "files": manifest_rows,
        }), encoding="utf-8")
        (workspace / ".br_restoration_extraction.json").write_text(json.dumps({
            "source_archive_sha256": official_sha, "manifest_name": manifest_name,
        }), encoding="utf-8")

    stage106 = make_stage106_report(root, archive_rows, member_rows, diff_preview, queue_preview)
    return project, game, stage106


class Stage107Tests(unittest.TestCase):
    def test_transaction_refreshes_only_metadata_and_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            project, game, stage106 = fixture(root)
            output = project / ".local/reports/quartet_restoration/BR_quartet_restoration_br1_official_source_metadata_refresh_evidence.tar.zst"
            result = S.collect(
                project_root=project, game_root=game, stage106_report=stage106,
                output=output, gust_pak=None, apply=True,
            )
            self.assertEqual(result["summary"]["transaction_mode"], "applied_transactionally")
            self.assertTrue(result["summary"]["underscore_archives_safe_to_delete"])
            self.assertTrue(output.is_file())
            inventory = json.loads((project / ".local/reports/quartet_restoration/inventories/br1_assets.source.json").read_text())
            self.assertEqual(inventory["canonical_source_provenance"]["refreshed_members"], 33)
            self.assertFalse(inventory["canonical_source_provenance"]["underscore_archives_required"])
            self.assertTrue((project / ".local/reports/quartet_restoration/provenance/br1_source_archive_provenance_ledger.json").is_file())

            second = S.collect(
                project_root=project, game_root=game, stage106_report=stage106,
                output=output, gust_pak=None, apply=True,
            )
            self.assertEqual(second["summary"]["transaction_mode"], "already_applied_verified")

    def test_official_archive_hash_mismatch_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            project, game, stage106 = fixture(root, corrupt_official=True)
            with self.assertRaisesRegex(S.Stage107Error, "official archive (size|SHA-256) mismatch"):
                S.collect(
                    project_root=project, game_root=game, stage106_report=stage106,
                    output=root / "out.tar.zst", gust_pak=None, apply=False,
                )


if __name__ == "__main__":
    unittest.main()
