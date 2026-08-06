from __future__ import annotations

import csv
import hashlib
import importlib.util
import json
import shutil
import struct
import subprocess
import sys
import tempfile
import unittest
import uuid
import zlib
from pathlib import Path

WORKSTREAM = Path(__file__).resolve().parents[1]
PROJECT = WORKSTREAM.parent.parent
MODULE_PATH = WORKSTREAM / "143_prepare_effect_posteffect_kps_fast_test_lab_profiles.py"
SPEC = importlib.util.spec_from_file_location("stage143", MODULE_PATH)
assert SPEC and SPEC.loader
stage143 = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = stage143
SPEC.loader.exec_module(stage143)

STAGE120_PATH = WORKSTREAM / "120_collect_canary_all_synthetic_composer_contract_evidence.py"
SPEC120 = importlib.util.spec_from_file_location("stage143_stage120_test", STAGE120_PATH)
assert SPEC120 and SPEC120.loader
stage120 = importlib.util.module_from_spec(SPEC120)
sys.modules[SPEC120.name] = stage120
SPEC120.loader.exec_module(stage120)


def read_tsv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def write_tsv(path: Path, fields: list[str], rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def make_earc(members: list[tuple[str, bytes]]) -> bytes:
    magic = 0x45415243
    header_size = 0x1C
    filename_size = 8
    name_bytes = 0x20 + filename_size * 0x10
    entry_size = 8 + name_bytes
    table_size = len(members) * entry_size
    payload_size = sum(len(payload) for _, payload in members)
    result = bytearray(header_size + table_size + payload_size)
    struct.pack_into("<7I", result, 0, magic, filename_size, payload_size, header_size, table_size, len(members), 0)
    offset = header_size + table_size
    for index, (name, payload) in enumerate(members):
        table = header_size + index * entry_size
        struct.pack_into("<2I", result, table, offset, len(payload))
        encoded = name.encode("utf-8") + b"\x00"
        if len(encoded) > name_bytes:
            raise AssertionError(name)
        result[table + 8:table + 8 + len(encoded)] = encoded
        result[offset:offset + len(payload)] = payload
        offset += len(payload)
    return bytes(result)


def gust_chunked(payload: bytes) -> bytes:
    compressed = zlib.compress(payload, 9)
    return len(compressed).to_bytes(4, "little") + compressed + (0).to_bytes(4, "little")


def make_stage142_report(root: Path, prototype_root: Path, target_payloads: dict[str, bytes], prototypes: dict[str, bytes]) -> tuple[str, str]:
    report_dir = root / stage143.STAGE142_DIR
    report_dir.mkdir(parents=True)
    summary = {
        "type": "br_quartet_restoration_effect_posteffect_kps_local_no_install_prototype_evidence_summary",
        "format_version": 1,
        "tool_version": "0.1.60",
        "status": "kps_local_no_install_prototypes_built_all_preconditions_verified_dxbc_reparsed_no_pak_no_install_no_runtime_promotion",
        "kps_prototype_artifact_rows": 2,
        "kps_prototype_program_rows": 15,
        "kps_applied_target_dword_edit_rows": 227,
        "kps_target_precondition_rows_verified": 227,
        "runtime_validated_profile_rows_preserved": 1,
        "runtime_failed_shader_rows_preserved": 2,
        "skipped_rows": 0,
        "policy": {
            "every_target_dword_precondition_verified": True,
            "only_planned_dwords_and_dxbc_checksums_changed": True,
            "installed_game_modified": False,
            "pak_built_or_repacked": False,
        },
    }
    summary_path = report_dir / "SUMMARY.json"
    summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    prototype_root.mkdir(parents=True)
    rows: list[dict[str, object]] = []
    specs = [
        ("PostEffectGamma.kps", "posteffectgamma.kps#0", 1, 3),
        ("PostEffectGlowLight.kps", "posteffectglowlight.kps#0", 14, 224),
    ]
    for name, key, programs, edits in specs:
        (prototype_root / name).write_bytes(prototypes[name])
        rows.append({
            "normalized_path": "data/x64/posteffect/pe_pack.elixir.gz",
            "member_key": key,
            "member_name": name,
            "prototype_relative_path": f".local/build/quartet_restoration/kps_target_dword_prototypes_0.1.60/{name}",
            "target_size": len(target_payloads[name]),
            "prototype_size": len(prototypes[name]),
            "target_sha256": hashlib.sha256(target_payloads[name]).hexdigest(),
            "prototype_sha256": hashlib.sha256(prototypes[name]).hexdigest(),
            "planned_program_rows": programs,
            "planned_edit_rows": edits,
            "changed_byte_rows_including_checksums": sum(a != b for a, b in zip(target_payloads[name], prototypes[name])),
            "all_target_preconditions_verified": True,
            "all_programs_reparsed": True,
            "all_dxbc_checksums_valid": True,
            "all_unplanned_bytes_preserved": True,
            "prototype_built": True,
            "installed_game_modified": False,
            "runtime_confirmed": False,
            "write_authorized": False,
        })
    write_tsv(report_dir / "KPS_LOCAL_PROTOTYPE_ARTIFACTS.tsv", list(rows[0]), rows)
    archive = root / stage143.STAGE142_NAME
    cp = subprocess.run(["tar", "--zstd", "-cf", str(archive), "-C", str(root), stage143.STAGE142_DIR], text=True, capture_output=True)
    if cp.returncode:
        raise AssertionError(cp.stderr)
    return hashlib.sha256(archive.read_bytes()).hexdigest(), hashlib.sha256(summary_path.read_bytes()).hexdigest()


class FastTestLabProfilePreparationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.temp = tempfile.TemporaryDirectory(prefix="stage143-tests-")
        cls.root = Path(cls.temp.name)
        cls.report_root = cls.root / "reports"
        cls.output_root = cls.root / "output"
        cls.quartet_root = cls.root / "quartet"
        token = uuid.uuid4().hex
        cls.prototype_root = PROJECT / ".local/build/quartet_restoration/tests" / f"stage143_prototypes_{token}"
        cls.workspace_root = PROJECT / ".local/build/quartet_restoration/tests" / f"stage143_profiles_{token}"
        cls.manifest_root = PROJECT / ".local/build/quartet_restoration/core_profiles/tests" / f"stage143_manifests_{token}"
        cls.target_payloads = {
            "PostEffectGamma.kps": bytes(range(64)),
            "PostEffectGlowLight.kps": bytes((index * 3) & 0xFF for index in range(96)),
        }
        cls.prototypes = {
            "PostEffectGamma.kps": cls.target_payloads["PostEffectGamma.kps"][:8] + b"GAMMA123" + cls.target_payloads["PostEffectGamma.kps"][16:],
            "PostEffectGlowLight.kps": cls.target_payloads["PostEffectGlowLight.kps"][:20] + b"GLOWLIGHT-PROT" + cls.target_payloads["PostEffectGlowLight.kps"][34:],
        }
        # Keep exact target sizes.
        cls.prototypes["PostEffectGlowLight.kps"] = cls.prototypes["PostEffectGlowLight.kps"][:96].ljust(96, b"\0")
        cls.report_root.mkdir(parents=True)
        cls.stage142_hash, cls.stage142_summary_hash = make_stage142_report(
            cls.report_root, cls.prototype_root, cls.target_payloads, cls.prototypes
        )
        pe_pack = gust_chunked(make_earc([
            ("PostEffectGamma.kps", cls.target_payloads["PostEffectGamma.kps"]),
            ("PostEffectGlowLight.kps", cls.target_payloads["PostEffectGlowLight.kps"]),
            ("PostEffectUntouched.kps", b"untouched"),
        ]))
        payloads = {
            stage143.PARENT_SUFFIX: pe_pack,
            "data/b1/x64/shader/sentinel.g1s": b"sentinel",
        }
        pack_root = cls.root / "baseline_pack"
        manifest = stage120.write_fixture_tree(pack_root, "PACK10_01.PAK", payloads)
        gust = PROJECT / ".local/vendor/gust_tools/gust_pak"
        stage120.run_gust(gust, manifest, pack_root, cls.root / "pack.log", timeout_seconds=30)
        cls.baseline_archive = pack_root / "PACK10_01.PAK"
        cls.baseline_hash = hashlib.sha256(cls.baseline_archive.read_bytes()).hexdigest()
        cls.baseline_size = cls.baseline_archive.stat().st_size
        cls.archive, cls.summary = stage143.build_report(
            PROJECT,
            quartet_root=cls.quartet_root,
            gust_pak=gust,
            report_root=cls.report_root,
            output_report_root=cls.output_root,
            workspace_root=cls.workspace_root,
            prototype_root=cls.prototype_root,
            manifest_root=cls.manifest_root,
            baseline_archive=cls.baseline_archive,
            timeout_seconds=60,
            expected_stage142_sha256=cls.stage142_hash,
            expected_stage142_summary_sha256=cls.stage142_summary_hash,
            expected_baseline_sha256=cls.baseline_hash,
            expected_baseline_size=cls.baseline_size,
        )
        cls.report = cls.output_root / stage143.REPORT_DIR

    @classmethod
    def tearDownClass(cls) -> None:
        shutil.rmtree(cls.prototype_root, ignore_errors=True)
        shutil.rmtree(cls.workspace_root, ignore_errors=True)
        shutil.rmtree(cls.manifest_root, ignore_errors=True)
        cls.temp.cleanup()

    def test_two_separate_profiles_are_built(self) -> None:
        rows = read_tsv(self.report / "FAST_TEST_LAB_PROFILES.tsv")
        self.assertEqual(len(rows), 2)
        self.assertEqual({row["member_name"] for row in rows}, stage143.EXPECTED_MEMBER_NAMES)
        self.assertTrue(all(row["runtime_validated"] == "False" for row in rows))
        self.assertTrue(all(row["normal_composer_eligible"] == "False" for row in rows))

    def test_test_order_is_gamma_then_glowlight(self) -> None:
        rows = sorted(read_tsv(self.report / "FAST_TEST_ORDER.tsv"), key=lambda row: int(row["test_order"]))
        self.assertEqual([row["variant"] for row in rows], ["gamma", "glowlight"])
        self.assertTrue(all(row["must_be_tested_alone"] == "True" for row in rows))
        self.assertTrue(all(row["rollback_required_before_next_variant"] == "True" for row in rows))

    def test_each_pak_changes_exactly_one_parent_member(self) -> None:
        rows = read_tsv(self.report / "PACK10_01_MEMBER_VERIFICATION.tsv")
        by_profile: dict[str, list[dict[str, str]]] = {}
        for row in rows:
            by_profile.setdefault(row["profile_id"], []).append(row)
        self.assertEqual(len(by_profile), 2)
        for profile_rows in by_profile.values():
            changed = [row for row in profile_rows if row["baseline_sha256"] != row["profile_sha256"]]
            self.assertEqual(len(changed), 1)
            self.assertEqual(changed[0]["selected_parent_member"], "True")
            self.assertTrue(all(row["verified"] == "True" for row in profile_rows))

    def test_each_parent_changes_exactly_one_kps(self) -> None:
        rows = read_tsv(self.report / "PE_PACK_MEMBER_VERIFICATION.tsv")
        by_profile: dict[str, list[dict[str, str]]] = {}
        for row in rows:
            by_profile.setdefault(row["profile_id"], []).append(row)
        for profile_rows in by_profile.values():
            selected = [row for row in profile_rows if row["selected_for_profile"] == "True"]
            self.assertEqual(len(selected), 1)
            self.assertTrue(all(row["verified"] == "True" for row in profile_rows))

    def test_manifests_are_runtime_unvalidated_and_local(self) -> None:
        manifests = sorted(self.manifest_root.glob("*.json"))
        self.assertEqual(len(manifests), 2)
        for path in manifests:
            manifest = json.loads(path.read_text())
            self.assertFalse(manifest["runtime_validated"])
            self.assertEqual(manifest["target_relative_path"], stage143.TARGET_RELATIVE_PATH)
            self.assertEqual(manifest["changed_member_count"], 1)
            expected_prefix = self.workspace_root.relative_to(PROJECT).as_posix() + "/"
            self.assertTrue(manifest["local_profile_path"].startswith(expected_prefix))

    def test_built_profile_paks_exist_outside_evidence(self) -> None:
        rows = read_tsv(self.report / "FAST_TEST_LAB_PROFILES.tsv")
        for row in rows:
            path = PROJECT / row["local_profile_path"]
            self.assertTrue(path.is_file())
            self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), row["profile_pak_sha256"])

    def test_baseline_is_not_modified(self) -> None:
        self.assertEqual(hashlib.sha256(self.baseline_archive.read_bytes()).hexdigest(), self.baseline_hash)
        self.assertFalse(self.summary["policy"]["installed_game_modified"])
        self.assertEqual(self.summary["installed_artifact_rows"], 0)

    def test_normal_composer_cannot_select_profiles(self) -> None:
        self.assertEqual(self.summary["runtime_validated_profile_rows_created"], 0)
        self.assertEqual(self.summary["normal_composer_eligible_profile_rows_created"], 0)
        self.assertFalse(self.summary["policy"]["profiles_runtime_validated"])
        self.assertFalse(self.summary["policy"]["profiles_normal_composer_eligible"])

    def test_profile_validation_rows_all_pass(self) -> None:
        rows = read_tsv(self.report / "PROFILE_VALIDATIONS.tsv")
        self.assertGreater(len(rows), 0)
        self.assertTrue(all(row["passed"] == "True" for row in rows))

    def test_prototype_hash_drift_fails_closed(self) -> None:
        path = self.prototype_root / "PostEffectGamma.kps"
        original = path.read_bytes()
        try:
            path.write_bytes(original[:-1] + bytes([original[-1] ^ 1]))
            with self.assertRaises(stage143.FastTestProfileError):
                stage143.load_stage142(
                    PROJECT,
                    self.report_root,
                    self.root / "drift_extract",
                    expected_archive_sha256=self.stage142_hash,
                    expected_summary_sha256=self.stage142_summary_hash,
                    prototype_root=self.prototype_root,
                )
        finally:
            path.write_bytes(original)

    def test_baseline_hash_drift_fails_closed(self) -> None:
        with self.assertRaisesRegex(stage143.FastTestProfileError, "baseline SHA-256 drift"):
            stage143.build_report(
                PROJECT,
                quartet_root=self.quartet_root,
                gust_pak=PROJECT / ".local/vendor/gust_tools/gust_pak",
                report_root=self.report_root,
                output_report_root=self.root / "bad_output",
                workspace_root=PROJECT / ".local/build/quartet_restoration/tests" / f"stage143_bad_{uuid.uuid4().hex}",
                prototype_root=self.prototype_root,
                manifest_root=PROJECT / ".local/build/quartet_restoration/core_profiles/tests" / f"stage143_bad_{uuid.uuid4().hex}",
                baseline_archive=self.baseline_archive,
                create_archive=False,
                expected_stage142_sha256=self.stage142_hash,
                expected_stage142_summary_sha256=self.stage142_summary_hash,
                expected_baseline_sha256="0" * 64,
                expected_baseline_size=self.baseline_size,
            )

    def test_report_contains_metadata_only(self) -> None:
        bad = [
            path.name for path in self.report.rglob("*") if path.is_file()
            and any(path.name.casefold().endswith(ext) for ext in stage143.FORBIDDEN_REPORT_EXTENSIONS)
        ]
        self.assertEqual(bad, [])
        self.assertFalse(self.summary["policy"]["proprietary_payloads_in_report"])

    def test_wrapper_uses_local_path_configuration(self) -> None:
        wrapper = (WORKSTREAM / "143_prepare_effect_posteffect_kps_fast_test_lab_profiles.sh").read_text(encoding="utf-8")
        self.assertIn(".local/paths.sh", wrapper)
        self.assertIn("BR1_QUARTET_ROOT", wrapper)
        self.assertNotIn("/home/", wrapper)
        self.assertNotIn("/mnt" + "/data", wrapper)

    def test_archive_and_summary_are_emitted(self) -> None:
        self.assertIsNotNone(self.archive)
        self.assertTrue(self.archive.is_file())
        self.assertEqual(json.loads((self.report / "SUMMARY.json").read_text()), self.summary)


if __name__ == "__main__":
    unittest.main()
