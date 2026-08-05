from __future__ import annotations

import csv
import importlib.util
import json
import re
import struct
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
WS = ROOT / "workstreams/quartet_legacy_dlc"
sys.path.insert(0, str(WS))
spec = importlib.util.spec_from_file_location("br_dlc_bkn_activation_ui_tool", WS / "br_dlc_bkn_activation_ui_tool.py")
assert spec and spec.loader
mod = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = mod
spec.loader.exec_module(mod)
N = mod.NESTED


def write_tsv(path: Path, fields: list[str], rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def make_manifest(root: Path) -> None:
    files = []
    for path in sorted(root.iterdir(), key=lambda p: p.name.casefold()):
        if path.is_file() and path.name != "REPORT_MANIFEST.json":
            files.append({"path": path.name, "size": path.stat().st_size, "sha256": mod.sha256_file(path)})
    (root / "REPORT_MANIFEST.json").write_text(json.dumps({"files": files}), encoding="utf-8")


def prepare_dry_report(project: Path) -> None:
    root = project / ".local/reports/quartet_legacy_dlc/dry_pak_insertion_evidence"
    root.mkdir(parents=True)
    summary = {
        "type": "br_quartet_legacy_dlc_dry_pak_insertion_summary",
        "tool_version": "0.0.13",
        "status": "local_asset_only_pack10_02_candidate_built_not_installed",
        "content_id": "costume_pc00_bkn",
        "candidate_sha256": "c" * 64,
        "added_member_count": 2,
        "existing_table_prefix_identical": True,
        "existing_encrypted_data_region_identical": True,
        "gust_pak_list_passed": True,
        "policy": {
            "game_modified": False, "git_modified": False, "candidate_installed": False,
            "profile_registered": False, "profile_build_allowed": False, "profiles_activated": False,
            "runtime_validated": False, "existing_pak_payloads_reencoded": False,
            "raw_assets_exported_in_report": False, "raw_assets_in_update": False,
            "wet_variant_included": False, "target_pak_repacked_locally": True,
            "raw_assets_in_local_build": True,
        },
    }
    (root / "SUMMARY.json").write_text(json.dumps(summary), encoding="utf-8")
    write_tsv(root / "DLC_DRY_PAK_INSERTED_MEMBERS.tsv", ["target_path", "validation_status"], [
        {"target_path": item["target_path"], "validation_status": "passed"} for item in mod.DRY.ADDED_MEMBERS
    ])
    write_tsv(root / "DLC_DRY_PAK_INSERTION_ARCHIVE.tsv", ["installed_archive_unchanged"], [{"installed_archive_unchanged": "true"}])
    write_tsv(root / "DLC_DRY_PAK_BASELINE_PRESERVATION.tsv", ["validation_status", "raw_existing_payloads_reencoded"], [{"validation_status": "passed", "raw_existing_payloads_reencoded": "false"}])
    write_tsv(root / "DLC_DRY_PAK_LAYOUT_VALIDATION.tsv", ["validation_status"], [{"validation_status": "passed"}])
    write_tsv(root / "DLC_DRY_PAK_GUST_LIST_VALIDATION.tsv", ["validation_status"], [{"validation_status": "passed"}])
    write_tsv(root / "DLC_DRY_PAK_INSERTION_GAPS.tsv", ["blocks_installation"], [{"blocks_installation": "true"} for _ in range(4)])
    make_manifest(root)


def xml_bytes(rows: list[tuple[str, dict[str, str]]]) -> bytes:
    body = ["<Root>"]
    for tag, attrs in rows:
        values = " ".join(f'{k}="{v}"' for k, v in attrs.items())
        body.append(f"  <{tag} {values}/>")
    body.append("</Root>")
    return "\n".join(body).encode("utf-8")


def prepare_tables(project: Path) -> None:
    source = project / mod.SOURCE_TABLE_ROOT
    target = project / mod.TARGET_TABLE_ROOT
    bkn = {"BaseTag": "PC00_DLC_BKN", "Directory": "Character", "Model": "PC00/PC00_DLC_Bkn", "defaultTexture": "PC00/PC00_DLC_Bkn", "motset0": "CHARA_MOTIONSET_PC00_SCL"}
    bkn_w = {"BaseTag": "PC00_DLC_BKN_W", "Directory": "Character", "Model": "PC00/PC00_DLC_Bkn_W", "defaultTexture": "PC00/PC00_DLC_Bkn_W", "motset0": "CHARA_MOTIONSET_PC00_SCL"}
    twl = {"BaseTag": "PC00_DLC_TWL", "Directory": "Character", "Model": "PC00/PC00_DLC_Twl", "defaultTexture": "PC00/PC00_DLC_Twl"}
    twl_w = {"BaseTag": "PC00_DLC_TWL_W", "Directory": "Character", "Model": "PC00/PC00_DLC_Twl_W", "defaultTexture": "PC00/PC00_DLC_Twl_W"}
    scl = {"BaseTag": "PC00_SCL", "Directory": "Character", "Model": "PC00/PC00_Scl", "defaultTexture": "PC00/PC00_Scl"}
    scl_w = {"BaseTag": "PC00_SCL_W", "Directory": "Character", "Model": "PC00/PC00_Scl_W", "defaultTexture": "PC00/PC00_Scl_W"}
    target_bkn = {**bkn, "Model": "PC00/PC00_Scl", "defaultTexture": "PC00/PC00_Scl", "Motion1": "PC00_SCL_BASE_MOTION1"}
    target_bkn_w = {**bkn_w, "Model": "PC00/PC00_Scl_W", "defaultTexture": "PC00/PC00_Scl_W"}
    for rel in mod.SYSTEM_TABLES:
        sp = source / rel
        tp = target / rel
        sp.parent.mkdir(parents=True, exist_ok=True)
        tp.parent.mkdir(parents=True, exist_ok=True)
        if rel == "chara/charabase.xml":
            sp.write_bytes(xml_bytes([("CharaBase", x) for x in (bkn, bkn_w, twl, twl_w, scl, scl_w)]))
            tp.write_bytes(xml_bytes([("CharaBase", x) for x in (target_bkn, target_bkn_w, twl, twl_w, scl, scl_w)]))
        elif rel in ("chara/chara.xml", "chara/chara_no.xml"):
            records = [("Chara", {"BaseTag": tag, "Height": "151"}) for tag in mod.BKN_TAGS + mod.CONTROL_TAGS + mod.FALLBACK_TAGS]
            sp.write_bytes(xml_bytes(records))
            tp.write_bytes(xml_bytes(records))
        else:
            sp.write_bytes(xml_bytes([("row", {"id": "neutral"})]))
            tp.write_bytes(xml_bytes([("row", {"id": "neutral"})]))
    (project / mod.SOURCE_TEXT).parent.mkdir(parents=True, exist_ok=True)
    (project / mod.TARGET_TEXT).parent.mkdir(parents=True, exist_ok=True)
    (project / mod.SOURCE_TEXT).write_bytes(xml_bytes([("str", {"String_No": "1", "Text": "source"})]))
    (project / mod.TARGET_TEXT).write_bytes(xml_bytes([("str", {"String_No": "1", "Text": "-"})]))


def xor(data: bytes, key: bytes) -> bytes:
    return bytes(value ^ key[index % len(key)] for index, value in enumerate(data))


def make_pak(path: Path, entries: list[tuple[str, bytes]], *, fmt: str = "a22_64", master_label: str = "A24_A29") -> None:
    specs = {name: (entry_struct, key_size, a22) for name, entry_struct, key_size, a22 in N.PAK_FORMATS}
    entry_struct, key_size, a22 = specs[fmt]
    master = dict(N.PAK_MASTER_KEYS)[master_label]
    table = bytearray()
    payload = bytearray()
    for index, (name, data) in enumerate(entries):
        key = bytes(((index + 11 + n) % 251) + 1 for n in range(key_size))
        effective = N.effective_entry_key(key, master)
        plain_name = name.encode("ascii") + b"\0" * (128 - len(name.encode("ascii")))
        raw_name = xor(plain_name, effective)
        raw_data = xor(data, effective)
        if a22:
            table.extend(entry_struct.pack(raw_name, len(data), key, 0, len(payload), 0))
        else:
            table.extend(entry_struct.pack(raw_name, len(data), key, len(payload), 0))
        payload.extend(raw_data)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(N.PAK_HEADER.pack(0x20000, len(entries), N.PAK_HEADER.size, 13) + table + payload)


def prepare_ui(project: Path, br1: Path, quartet: Path, *, include_bkn_token: bool = False) -> None:
    source_files = []
    target_files = []
    source_entries = []
    target_entries = []
    for index, name in enumerate(mod.UI_MEMBER_NAMES):
        source_path = f"data/x64/res_jp/layout/{name}"
        target_path = f"data/b1/x64/res_jp/layout/{name}"
        payload = b"UI" + (b"PC00_DLC_BKN" if include_bkn_token and index == 0 else b"NEUTRAL") + bytes([index])
        source_entries.append(("\\" + source_path.replace("/", "\\"), payload))
        target_entries.append(("\\" + target_path.replace("/", "\\"), payload))
        source_files.append({"archive": "DATA/PACK00_04_3.PAK", "path": source_path, "normalized_path": source_path, "size": len(payload), "sha256": mod.sha256_bytes(payload)})
        target_files.append({"archive": "Data/PACK10_04_03.PAK", "path": target_path, "normalized_path": source_path, "size": len(payload), "sha256": mod.sha256_bytes(payload)})
    inv = project / ".local/reports/quartet_restoration/inventories"
    inv.mkdir(parents=True, exist_ok=True)
    (inv / "br1_assets.source.json").write_text(json.dumps({"files": source_files}), encoding="utf-8")
    (inv / "br1_assets.target.json").write_text(json.dumps({"files": target_files}), encoding="utf-8")
    make_pak(br1 / "DATA/PACK00_04_3.PAK", source_entries)
    make_pak(quartet / "Data/PACK10_04_03.PAK", target_entries)


class BknActivationUiTest(unittest.TestCase):
    def test_audit_proves_scl_stub_and_keeps_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temp_name:
            base = Path(temp_name)
            project = base / "project"
            br1 = base / "br1"
            quartet = base / "quartet"
            project.mkdir()
            prepare_dry_report(project)
            prepare_tables(project)
            prepare_ui(project, br1, quartet)
            output = project / ".local/reports/quartet_legacy_dlc" / mod.REPORT_DIR_NAME
            archive, summary = mod.audit(project, br1, quartet, output)
            self.assertTrue(archive.is_file())
            self.assertEqual(summary["bkn_stub_rows"], 2)
            self.assertEqual(summary["direct_bkn_ui_token_hits"], 0)
            self.assertEqual(summary["exact_unlock_reference_rows"], 0)
            self.assertFalse(summary["policy"]["profile_build_allowed"])
            validated = mod.validate_report(output)
            self.assertEqual(validated["status"], "bkn_table_stub_proven_activation_and_ui_still_fail_closed")
            with (output / "DLC_BKN_CHARABASE_STUB_MAPPING.tsv").open(encoding="utf-8") as handle:
                rows = list(csv.DictReader(handle, delimiter="\t"))
            self.assertEqual({r["classification"] for r in rows}, {"present_but_disabled_via_scl_fallback"})

    def test_ui_exact_token_is_metadata_only_candidate(self) -> None:
        with tempfile.TemporaryDirectory() as temp_name:
            base = Path(temp_name)
            project = base / "project"
            br1 = base / "br1"
            quartet = base / "quartet"
            project.mkdir()
            prepare_dry_report(project)
            prepare_tables(project)
            prepare_ui(project, br1, quartet, include_bkn_token=True)
            output = project / ".local/reports/quartet_legacy_dlc" / mod.REPORT_DIR_NAME
            _, summary = mod.audit(project, br1, quartet, output)
            self.assertEqual(summary["direct_bkn_ui_token_hits"], 2)
            self.assertFalse(summary["policy"]["ui_modified"])

    def test_validate_rejects_profile_authorization(self) -> None:
        with tempfile.TemporaryDirectory() as temp_name:
            base = Path(temp_name)
            project = base / "project"
            br1 = base / "br1"
            quartet = base / "quartet"
            project.mkdir()
            prepare_dry_report(project)
            prepare_tables(project)
            prepare_ui(project, br1, quartet)
            output = project / ".local/reports/quartet_legacy_dlc" / mod.REPORT_DIR_NAME
            mod.audit(project, br1, quartet, output)
            summary_path = output / "SUMMARY.json"
            summary = json.loads(summary_path.read_text(encoding="utf-8"))
            summary["policy"]["profile_build_allowed"] = True
            summary_path.write_text(json.dumps(summary), encoding="utf-8")
            with self.assertRaises(mod.BknActivationUiError):
                mod.validate_report(output)


if __name__ == "__main__":
    unittest.main()
