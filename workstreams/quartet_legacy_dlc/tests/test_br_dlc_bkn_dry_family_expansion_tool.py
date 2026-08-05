from __future__ import annotations

import csv
import importlib.util
import json
import tempfile
import unittest
import sys
from pathlib import Path

MODULE_PATH = (
    Path(__file__).resolve().parents[1]
    / "br_dlc_bkn_dry_family_expansion_tool.py"
)
spec = importlib.util.spec_from_file_location("bkn_family_tool", MODULE_PATH)
assert spec and spec.loader
mod = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = mod
spec.loader.exec_module(mod)


class BKNFamilyExpansionTests(unittest.TestCase):
    def write_tsv(self, root: Path, name: str, rows: list[list[str]]) -> None:
        path = root / name
        with path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.writer(handle, delimiter="\t", lineterminator="\n")
            writer.writerows(rows)

    def fixture(self, root: Path) -> None:
        self.write_tsv(
            root,
            "DLC_TECHNICAL_REGISTRY.tsv",
            [
                ["content_id", "source_member", "status"],
                [
                    "costume_pc01_bkn",
                    "chara/pc01_dlc_bkn.elixir.gz",
                    "missing_portable_from_br1",
                ],
            ],
        )
        self.write_tsv(
            root,
            "DLC_NESTED_MEMBER_BINDINGS.tsv",
            [
                ["owner", "member", "status"],
                [
                    "costume_pc01_bkn",
                    "chara/pc01_dlc_bkn.elixir.gz",
                    "missing_portable_from_br1",
                ],
            ],
        )
        self.write_tsv(
            root,
            "DLC_EXTERNAL_TEXTURE_BINDINGS.tsv",
            [
                ["owner", "member", "status"],
                [
                    "costume_pc01_bkn",
                    "chara/pc01_dlc_bkn.g1t",
                    "missing_portable_from_br1",
                ],
            ],
        )
        self.write_tsv(
            root,
            "DLC_BKN_FAMILY_FALLBACK_MAP.tsv",
            [
                ["record", "model", "texture"],
                ["PC01_DLC_BKN", "PC01_SCL", "PC01_SCL"],
                ["PC01_DLC_BKN_W", "PC01_SCL_W", "PC01_SCL_W"],
            ],
        )
        self.write_tsv(
            root,
            "DLC_BR1_CANONICAL_SOURCE_REGISTRY.tsv",
            [
                ["owner", "source", "status"],
                ["costume_pc01_bkn", "official no-underscore", "canonical"],
            ],
        )
        (root / "SUMMARY.json").write_text(
            json.dumps({"scope": "costume_pc01_bkn", "status": "assets_identified"})
            + "\n",
            encoding="utf-8",
        )

    def test_collects_metadata_ready_candidate_without_authorizing_build(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            reports = base / "reports"
            output = reports / "out"
            reports.mkdir()
            self.fixture(reports)

            summary = mod.collect(reports, output)
            mod.validate(output)

            self.assertIn("PC01", summary["metadata_ready_for_bounded_dry_probe"])
            self.assertFalse(summary["build_authorized"])
            self.assertFalse(summary["prepare_allowed"])
            self.assertFalse(summary["commit_allowed"])
            self.assertFalse(summary["installation_allowed"])
            self.assertFalse(summary["runtime_validation_allowed"])
            self.assertFalse(summary["wet_bkn_included"])

            with (output / "DLC_BKN_DRY_FAMILY_CANDIDATES.tsv").open(
                encoding="utf-8", newline=""
            ) as handle:
                rows = {row["character_id"]: row for row in csv.DictReader(handle, delimiter="\t")}
            self.assertEqual(
                rows["PC01"]["candidate_state"],
                "metadata_ready_for_bounded_dry_probe",
            )
            self.assertEqual(rows["PC01"]["build_authorized"], "false")
            self.assertEqual(rows["PC00"]["candidate_state"], "already_handled_pc00_reference")

    def test_missing_asset_binding_remains_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            reports = base / "reports"
            output = reports / "out"
            reports.mkdir()
            self.write_tsv(
                reports,
                "DLC_TECHNICAL_REGISTRY.tsv",
                [["content_id"], ["costume_pc02_bkn"]],
            )
            self.write_tsv(
                reports,
                "DLC_NESTED_MEMBER_BINDINGS.tsv",
                [["owner"], ["costume_pc02_bkn"]],
            )
            self.write_tsv(
                reports,
                "DLC_EXTERNAL_TEXTURE_BINDINGS.tsv",
                [["owner"], ["costume_pc02_bkn"]],
            )
            self.write_tsv(
                reports,
                "DLC_BKN_FAMILY_FALLBACK_MAP.tsv",
                [["record", "model"], ["PC02_DLC_BKN", "PC02_SCL"]],
            )

            summary = mod.collect(reports, output)
            mod.validate(output)
            self.assertIn("PC02", summary["requires_metadata_closure"])
            self.assertNotIn("PC02", summary["metadata_ready_for_bounded_dry_probe"])

    def test_raw_assets_are_never_selected_as_reports(self) -> None:
        self.assertFalse(mod.safe_report_member("x/pc01_dlc_bkn.g1t"))
        self.assertFalse(mod.safe_report_member("x/PACK10_02.PAK"))
        self.assertTrue(mod.safe_report_member("x/DLC_TECHNICAL_REGISTRY.tsv"))


if __name__ == "__main__":
    unittest.main()
