from __future__ import annotations

import csv
import hashlib
import importlib.util
import json
import shutil
import struct
import sys
import tempfile
import unittest
import zlib
from pathlib import Path
from unittest import mock

WORKSTREAM = Path(__file__).resolve().parents[1]
PROJECT = WORKSTREAM.parent.parent
TOOL_PATH = WORKSTREAM / "147_prepare_hinako_wet_school_uniform_fast_test_profile.py"
SPEC = importlib.util.spec_from_file_location("stage147_tool", TOOL_PATH)
assert SPEC and SPEC.loader
TOOL = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = TOOL
SPEC.loader.exec_module(TOOL)

STAGE120_PATH = WORKSTREAM / "120_collect_canary_all_synthetic_composer_contract_evidence.py"
S120_SPEC = importlib.util.spec_from_file_location("stage147_stage120", STAGE120_PATH)
assert S120_SPEC and S120_SPEC.loader
STAGE120 = importlib.util.module_from_spec(S120_SPEC)
sys.modules[S120_SPEC.name] = STAGE120
S120_SPEC.loader.exec_module(STAGE120)


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def parameter_record(name: str, value: float) -> bytes:
    name_bytes = name.encode("utf-8") + b"\0"
    raw = struct.pack("<f", value)
    size = 16 + len(name_bytes) + len(raw)
    return struct.pack("<3I2H", size, len(name_bytes), 0, 1, 1) + name_bytes + raw


def g1m(name: str, value: float, *, extra_padding: int = 0) -> bytes:
    record = parameter_record(name, value)
    block_payload = struct.pack("<I", 1) + record + (b"\0" * extra_padding)
    section = struct.pack("<3I", 0x00010003, 12 + len(block_payload), 1) + block_payload
    g1mg_size = 0x30 + len(section)
    g1mg = (
        b"G1MG"
        + struct.pack("<2I", 0x30303430, g1mg_size)
        + b"DX11"
        + struct.pack("<I6f", 0, 0.0, 0.0, 0.0, 1.0, 1.0, 1.0)
        + struct.pack("<I", 1)
        + section
    )
    total = 0x18 + len(g1mg)
    return b"_M1G" + struct.pack("<5I", 0x30303430, total, 0x18, 0, 1) + g1mg


def make_earc(members: list[tuple[str, bytes]]) -> bytes:
    header_size = 0x1C
    filename_size = 8
    name_bytes = 0x20 + filename_size * 0x10
    entry_size = 8 + name_bytes
    table_size = len(members) * entry_size
    payload_size = sum(len(payload) for _, payload in members)
    result = bytearray(header_size + table_size + payload_size)
    struct.pack_into("<7I", result, 0, 0x45415243, filename_size, payload_size, header_size, table_size, len(members), 0)
    offset = header_size + table_size
    for index, (name, payload) in enumerate(members):
        table = header_size + index * entry_size
        struct.pack_into("<2I", result, table, offset, len(payload))
        encoded = name.encode("utf-8") + b"\0"
        result[table + 8 : table + 8 + len(encoded)] = encoded
        result[offset : offset + len(payload)] = payload
        offset += len(payload)
    return bytes(result)


def gust_chunked(payload: bytes) -> bytes:
    out = bytearray()
    for start in range(0, len(payload), 0x4000):
        comp = zlib.compress(payload[start:start + 0x4000], 9)
        out.extend(len(comp).to_bytes(4, "little"))
        out.extend(comp)
    out.extend((0).to_bytes(4, "little"))
    return bytes(out)


def write_parent(path: Path, selected: bytes, sentinel: bytes = b"keep-me") -> None:
    payload = make_earc([
        ("dummy.bin", sentinel),
        (TOOL.SELECTED_MEMBER_NAME, selected),
    ])
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(gust_chunked(payload))


def read_tsv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


class HinakoWetSchoolUniformFastTestProfileTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(prefix="stage147-tests-")
        self.root = Path(self.tmp.name)
        self.target_g1m = g1m("targetWet", 0.4)
        self.source_g1m = g1m("sourceWet", 0.8, extra_padding=8)
        self.target_parent = self.root / "target_parent.elixir.gz"
        self.source_parent = self.root / "source_parent.elixir.gz"
        write_parent(self.target_parent, self.target_g1m)
        write_parent(self.source_parent, self.source_g1m)
        self.parent_member = TOOL.TARGET_PARENT_SUFFIX
        pack_root = self.root / "baseline_pack"
        manifest = STAGE120.write_fixture_tree(pack_root, "PACK10_02.PAK", {
            self.parent_member: self.target_parent.read_bytes(),
            "data/b1/x64/character/sentinel.bin": b"other-pack-member",
        })
        STAGE120.run_gust(PROJECT / ".local/vendor/gust_tools/gust_pak", manifest, pack_root, self.root / "fixture_pack.log")
        self.baseline = pack_root / "PACK10_02.PAK"
        self.baseline_sha = TOOL.sha256_file(self.baseline)
        self.workspace = PROJECT / ".local/build/quartet_restoration" / ("stage147_test_" + self.root.name)
        self.manifests = self.workspace / "manifests"
        self.patches = {
            "EXPECTED_TARGET_PARENT_SHA256": TOOL.sha256_file(self.target_parent),
            "EXPECTED_SOURCE_PARENT_SHA256": TOOL.sha256_file(self.source_parent),
            "EXPECTED_TARGET_MEMBER_SHA256": sha(self.target_g1m),
            "EXPECTED_SOURCE_MEMBER_SHA256": sha(self.source_g1m),
            "EXPECTED_TARGET_MEMBER_SIZE": len(self.target_g1m),
            "EXPECTED_SOURCE_MEMBER_SIZE": len(self.source_g1m),
        }
        self.patchers = [mock.patch.object(TOOL, key, value) for key, value in self.patches.items()]
        for patcher in self.patchers:
            patcher.start()

    def tearDown(self) -> None:
        for patcher in reversed(self.patchers):
            patcher.stop()
        shutil.rmtree(self.workspace, ignore_errors=True)
        self.tmp.cleanup()

    def build(self):
        return TOOL.build_profile_from_inputs(
            PROJECT,
            baseline_archive=self.baseline,
            source_member=self.source_g1m,
            gust_pak=PROJECT / ".local/vendor/gust_tools/gust_pak",
            workspace_root=self.workspace,
            manifest_root=self.manifests,
            timeout_seconds=60,
        )

    def test_parent_rebuild_changes_only_school_wet_member(self):
        br = TOOL.load_module(PROJECT / "Blue_Reflection_Text_Tool/br_restoration_tool.py", "stage147_test_br_parent")
        candidate, rows, meta = TOOL.rebuild_earc_with_member(br, self.target_parent, self.source_g1m)
        self.assertNotEqual(candidate, self.target_parent.read_bytes())
        self.assertEqual(sum(row["target_sha256"] != row["candidate_sha256"] for row in rows), 1)
        selected = [row for row in rows if row["selected_for_profile"]]
        self.assertEqual(len(selected), 1)
        self.assertEqual(selected[0]["candidate_sha256"], sha(self.source_g1m))
        self.assertTrue(all(row["verified"] for row in rows))
        self.assertEqual(meta["member_count"], 2)

    def test_profile_build_changes_exactly_one_pack_member(self):
        profile, parent_rows, pak_rows, validations = self.build()
        self.assertEqual(profile["changed_member_count"], 1)
        self.assertEqual(sum(row["baseline_sha256"] != row["profile_sha256"] for row in pak_rows), 1)
        self.assertEqual(sum(row["target_sha256"] != row["candidate_sha256"] for row in parent_rows), 1)
        self.assertTrue(all(row["verified"] for row in pak_rows))
        self.assertTrue(all(row["passed"] for row in validations))

    def test_dynamic_baseline_is_not_modified(self):
        self.build()
        self.assertEqual(TOOL.sha256_file(self.baseline), self.baseline_sha)

    def test_profile_is_fast_test_only_and_nonproduction(self):
        profile, _parent, _pak, _validations = self.build()
        self.assertFalse(profile["runtime_validated"])
        self.assertFalse(profile["production_eligible"])
        self.assertFalse(profile["normal_composer_eligible"])
        self.assertTrue(profile["fast_test_only"])
        manifest = json.loads((self.manifests / f"{TOOL.PROFILE_ID}.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["baseline_sha256"], self.baseline_sha)

    def test_rerun_is_safe_and_idempotent_at_workspace_level(self):
        first, *_ = self.build()
        second, *_ = self.build()
        self.assertEqual(first["profile_sha256"], second["profile_sha256"])
        marker = self.workspace / TOOL.WORKSPACE_SUBDIR / TOOL.PROFILE_ID / "HARNESS.json"
        self.assertEqual(json.loads(marker.read_text(encoding="utf-8"))["status"], "ready")

    def test_unmarked_existing_profile_root_is_rejected(self):
        root = self.workspace / TOOL.WORKSPACE_SUBDIR / TOOL.PROFILE_ID
        root.mkdir(parents=True, exist_ok=True)
        (root / "foreign.txt").write_text("do not remove", encoding="utf-8")
        with self.assertRaisesRegex(TOOL.WetSchoolProfileError, "unmarked profile root"):
            self.build()
        self.assertTrue((root / "foreign.txt").is_file())

    def test_foreign_marker_is_rejected(self):
        root = self.workspace / TOOL.WORKSPACE_SUBDIR / TOOL.PROFILE_ID
        root.mkdir(parents=True, exist_ok=True)
        (root / "HARNESS.json").write_text(json.dumps({"type": "other", "profile_id": "other"}), encoding="utf-8")
        with self.assertRaisesRegex(TOOL.WetSchoolProfileError, "foreign profile root"):
            self.build()

    def test_report_is_metadata_only(self):
        reports = self.root / "reports"
        archive, summary = TOOL.build_report(
            PROJECT,
            quartet_root=self.root,
            original_root=None,
            gust_pak=PROJECT / ".local/vendor/gust_tools/gust_pak",
            report_root=PROJECT / ".local/reports/quartet_restoration",
            output_report_root=reports,
            workspace_root=self.workspace,
            manifest_root=self.manifests,
            baseline_archive=self.baseline,
            source_parent_override=self.source_parent,
            timeout_seconds=60,
            validate_evidence=False,
            create_archive=True,
        )
        self.assertIsNotNone(archive)
        self.assertEqual(summary["pak_changed_member_rows"], 1)
        self.assertEqual(summary["parent_changed_member_rows"], 1)
        self.assertTrue(summary["fast_test_only"])
        report = reports / TOOL.REPORT_DIR
        forbidden = [p for p in report.rglob("*") if p.is_file() and p.name.casefold().endswith(TOOL.FORBIDDEN_REPORT_EXTENSIONS)]
        self.assertEqual(forbidden, [])
        self.assertEqual(len(read_tsv(report / "PACK10_02_MEMBER_VERIFICATION.tsv")), 2)


if __name__ == "__main__":
    unittest.main()
