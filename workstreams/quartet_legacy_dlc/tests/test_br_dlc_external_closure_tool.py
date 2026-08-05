from __future__ import annotations

import csv
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

TOOL_PATH = Path(__file__).resolve().parents[1] / "br_dlc_external_closure_tool.py"
SPEC = importlib.util.spec_from_file_location("br_dlc_external_closure_tool", TOOL_PATH)
assert SPEC and SPEC.loader
TOOL = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(TOOL)


def write_tsv(path: Path, fields: list[str], rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow({field: TOOL.scalar(row.get(field, "")) for field in fields})


class ExternalClosureToolTests(unittest.TestCase):
    def fixture(self, root: Path) -> Path:
        reports = root / ".local/reports/quartet_legacy_dlc"
        nested = reports / "nested_container_evidence"
        exact = reports / "exact_closure_evidence"
        technical = reports / "technical_registry_evidence"
        for directory in (nested, exact, technical):
            directory.mkdir(parents=True, exist_ok=True)
        (nested / "SUMMARY.json").write_text(json.dumps({
            "status": "canonical_parent_container_nested_inventory_complete_metadata_only"
        }), encoding="utf-8")

        owners = [
            ("closure_twl", "costume_pc00_twl", "costume_or_outfit"),
            ("closure_bkn", "costume_pc00_bkn", "costume_or_outfit"),
            ("closure_acc", "accessory_item_accessory_00", "accessory"),
        ]
        canonical_fields = ["closure_id", "content_id", "technical_types"]
        write_tsv(exact / "DLC_CANONICAL_CONTENT_CLOSURE.tsv", canonical_fields, [
            {"closure_id": closure, "content_id": content, "technical_types": types}
            for closure, content, types in owners
        ])
        nested_inventory_fields = [
            "container_id", "closure_id", "content_id", "source_nested_member_count",
            "target_nested_member_count", "target_path",
        ]
        nested_rows = []
        for suffix in ("dry", "wet"):
            nested_rows.append({"container_id": f"twl_{suffix}", "closure_id": "closure_twl", "content_id": "costume_pc00_twl", "source_nested_member_count": 6, "target_nested_member_count": 6, "target_path": f"target/twl_{suffix}.elixir.gz"})
            nested_rows.append({"container_id": f"bkn_{suffix}", "closure_id": "closure_bkn", "content_id": "costume_pc00_bkn", "source_nested_member_count": 6, "target_nested_member_count": "", "target_path": ""})
        nested_rows.append({"container_id": "acc", "closure_id": "closure_acc", "content_id": "accessory_item_accessory_00", "source_nested_member_count": 4, "target_nested_member_count": 4, "target_path": "target/accessory.elixir.gz"})
        write_tsv(nested / "DLC_NESTED_CONTAINER_INVENTORY.tsv", nested_inventory_fields, nested_rows)
        readiness_fields = ["closure_id", "content_id"]
        write_tsv(nested / "DLC_NESTED_PROFILE_READINESS.tsv", readiness_fields, [
            {"closure_id": closure, "content_id": content} for closure, content, _ in owners
        ])

        role_fields = ["closure_id", "content_id", "role", "resolution_status", "evidence"]
        role_rows = []
        for closure, content, prefix in (("closure_twl", "costume_pc00_twl", "twl"), ("closure_bkn", "costume_pc00_bkn", "bkn")):
            role_rows.extend([
                {"closure_id": closure, "content_id": content, "role": "dry_texture", "resolution_status": "resolved", "evidence": f"data/{prefix}.g1t"},
                {"closure_id": closure, "content_id": content, "role": "wet_texture", "resolution_status": "resolved", "evidence": f"data/{prefix}_w.g1t"},
                {"closure_id": closure, "content_id": content, "role": "system_character_record", "resolution_status": "resolved", "evidence": ""},
                {"closure_id": closure, "content_id": content, "role": "ui_icon_or_thumbnail", "resolution_status": "shared_atlas_or_table_index_unresolved", "evidence": ""},
                {"closure_id": closure, "content_id": content, "role": "unlock_or_availability_chain", "resolution_status": "missing", "evidence": ""},
            ])
        role_rows.extend([
            {"closure_id": "closure_acc", "content_id": "accessory_item_accessory_00", "role": "accessory_texture", "resolution_status": "resolved", "evidence": "data/accessory.g1t"},
            {"closure_id": "closure_acc", "content_id": "accessory_item_accessory_00", "role": "accessory_table_binding", "resolution_status": "missing", "evidence": ""},
            {"closure_id": "closure_acc", "content_id": "accessory_item_accessory_00", "role": "ui_icon_or_thumbnail", "resolution_status": "shared_atlas_or_table_index_unresolved", "evidence": ""},
            {"closure_id": "closure_acc", "content_id": "accessory_item_accessory_00", "role": "unlock_or_availability_chain", "resolution_status": "missing", "evidence": ""},
        ])
        write_tsv(exact / "DLC_EXACT_ROLE_CLOSURE.tsv", role_fields, role_rows)

        table_fields = [
            "closure_id", "content_id", "evidence_type", "source_table", "record_key", "field_name",
            "identifier", "target_status", "exact_owner_match", "semantics_proven",
        ]
        table_rows = []
        for closure, content, token in (("closure_twl", "costume_pc00_twl", "TWL"), ("closure_bkn", "costume_pc00_bkn", "BKN")):
            for variant in ("", "_W"):
                table_rows.append({
                    "closure_id": closure, "content_id": content, "evidence_type": "system_record",
                    "source_table": "saves/chara/chara_no.xml", "record_key": f"Chara:BaseTag=PC00_DLC_{token}{variant}",
                    "field_name": "", "identifier": f"PC00_DLC_{token}{variant}", "target_status": "present_identical",
                    "exact_owner_match": True, "semantics_proven": False,
                })
        write_tsv(exact / "DLC_TABLE_AND_UNLOCK_CLOSURE.tsv", table_fields, table_rows)

        binding_fields = [
            "content_id", "normalized_path", "source_archive", "source_path", "source_size", "source_sha256",
            "target_archive", "target_path", "target_size", "target_sha256", "compatibility_status",
            "fallback_from_br1_allowed",
        ]
        bindings = [
            {"content_id": "costume_pc00_twl", "normalized_path": "data/twl.g1t", "source_archive": "src.pak", "source_path": "data/twl.g1t", "source_size": 10, "source_sha256": "a"*64, "target_archive": "tgt.pak", "target_path": "data/twl.g1t", "target_size": 10, "target_sha256": "a"*64, "compatibility_status": "present_identical", "fallback_from_br1_allowed": False},
            {"content_id": "costume_pc00_twl", "normalized_path": "data/twl_w.g1t", "source_archive": "src.pak", "source_path": "data/twl_w.g1t", "source_size": 11, "source_sha256": "b"*64, "target_archive": "tgt.pak", "target_path": "data/twl_w.g1t", "target_size": 12, "target_sha256": "c"*64, "compatibility_status": "present_modified", "fallback_from_br1_allowed": False},
            {"content_id": "costume_pc00_bkn", "normalized_path": "data/bkn.g1t", "source_archive": "src.pak", "source_path": "data/bkn.g1t", "source_size": 10, "source_sha256": "d"*64, "target_archive": "", "target_path": "", "target_size": "", "target_sha256": "", "compatibility_status": "missing_portable_from_br1", "fallback_from_br1_allowed": True},
            {"content_id": "costume_pc00_bkn", "normalized_path": "data/bkn_w.g1t", "source_archive": "src.pak", "source_path": "data/bkn_w.g1t", "source_size": 10, "source_sha256": "e"*64, "target_archive": "", "target_path": "", "target_size": "", "target_sha256": "", "compatibility_status": "missing_portable_from_br1", "fallback_from_br1_allowed": True},
            {"content_id": "shared_asset_deadbeef", "normalized_path": "data/accessory.g1t", "source_archive": "src.pak", "source_path": "data/accessory.g1t", "source_size": 5, "source_sha256": "f"*64, "target_archive": "tgt.pak", "target_path": "data/accessory.g1t", "target_size": 5, "target_sha256": "f"*64, "compatibility_status": "present_identical", "fallback_from_br1_allowed": False},
        ]
        write_tsv(technical / "DLC_TECHNICAL_MEMBER_BINDINGS.tsv", binding_fields, bindings)
        return reports

    def test_audit_crosslinks_external_dependencies_and_selects_bounded_families(self) -> None:
        with tempfile.TemporaryDirectory() as temp_name:
            root = Path(temp_name)
            self.fixture(root)
            output, summary = TOOL.audit(root)
            self.assertTrue(output.is_file())
            self.assertEqual(summary["canonical_owner_count"], 3)
            self.assertEqual(summary["external_texture_binding_count"], 5)
            self.assertEqual(summary["external_texture_compatibility_counts"]["missing_portable_from_br1"], 2)
            selected = {row["candidate_kind"]: row["content_id"] for row in summary["selected_bounded_families"]}
            self.assertEqual(selected["positive_control"], "costume_pc00_twl")
            self.assertEqual(selected["portable_transfer_candidate"], "costume_pc00_bkn")

    def test_unique_path_binding_can_reassign_shared_accessory_member(self) -> None:
        with tempfile.TemporaryDirectory() as temp_name:
            root = Path(temp_name)
            reports = self.fixture(root)
            TOOL.audit(root, create_archive=False)
            rows = TOOL.read_tsv(reports / TOOL.REPORT_DIR_NAME / "DLC_EXTERNAL_TEXTURE_BINDINGS.tsv")
            accessory = next(row for row in rows if row["content_id"] == "accessory_item_accessory_00")
            self.assertEqual(accessory["binding_basis"], "unique_path_reassigned_from_shared_registry")
            self.assertEqual(accessory["compatibility_status"], "present_identical")

    def test_all_profile_readiness_remains_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temp_name:
            root = Path(temp_name)
            reports = self.fixture(root)
            TOOL.audit(root, create_archive=False)
            readiness = TOOL.read_tsv(reports / TOOL.REPORT_DIR_NAME / "DLC_EXTERNAL_CLOSURE_PROFILE_READINESS.tsv")
            self.assertTrue(readiness)
            self.assertTrue(all(row["profile_build_allowed"] == "false" for row in readiness))
            self.assertTrue(all(row["runtime_validated"] == "false" for row in readiness))

    def test_validate_rejects_profile_authorization(self) -> None:
        with tempfile.TemporaryDirectory() as temp_name:
            root = Path(temp_name)
            reports = self.fixture(root)
            TOOL.audit(root, create_archive=False)
            report_root = reports / TOOL.REPORT_DIR_NAME
            path = report_root / "DLC_EXTERNAL_CLOSURE_PROFILE_READINESS.tsv"
            rows = TOOL.read_tsv(path)
            rows[0]["profile_build_allowed"] = "true"
            TOOL.write_tsv(path, list(rows[0]), rows)
            with self.assertRaises(TOOL.ExternalClosureError):
                TOOL.validate_report(report_root)

    def test_bundle_is_deterministic(self) -> None:
        with tempfile.TemporaryDirectory() as temp_name:
            root = Path(temp_name)
            reports = self.fixture(root)
            TOOL.audit(root, create_archive=False)
            report_root = reports / TOOL.REPORT_DIR_NAME
            first = root / "first.tar.zst"
            second = root / "second.tar.zst"
            TOOL.make_archive(report_root, first)
            TOOL.make_archive(report_root, second)
            self.assertEqual(TOOL.sha256_file(first), TOOL.sha256_file(second))


if __name__ == "__main__":
    unittest.main()
