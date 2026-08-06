from __future__ import annotations

import csv
import importlib.util
import json
import shutil
import struct
import sys
import tempfile
import unittest
from collections import defaultdict
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
MODULE_PATH = PROJECT_ROOT / "workstreams/quartet_restoration/142_collect_effect_posteffect_kps_local_no_install_prototype_evidence.py"
SPEC = importlib.util.spec_from_file_location("stage142", MODULE_PATH)
assert SPEC and SPEC.loader
stage142 = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = stage142
SPEC.loader.exec_module(stage142)

STAGE141_ARCHIVE = PROJECT_ROOT / ".local/reports/quartet_restoration" / stage142.STAGE141_NAME


def read_tsv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def make_dxbc(br, instruction_lengths: list[int], word_values: dict[tuple[int, int], int], *, seed: int) -> bytes:
    dwords = [0x00000050, 0]
    for instruction_index, length in enumerate(instruction_lengths):
        length = max(1, length)
        token = ((length & 0x7F) << 24) | ((seed + instruction_index + 1) & 0x7FF)
        words = [token] + [((seed << 16) ^ (instruction_index << 8) ^ index) & 0xFFFFFFFF for index in range(1, length)]
        for dword_index in range(length):
            if (instruction_index, dword_index) in word_values:
                words[dword_index] = word_values[(instruction_index, dword_index)]
        dwords.extend(words)
    dwords[1] = len(dwords)
    code = struct.pack(f"<{len(dwords)}I", *dwords)
    header_size = 36
    total_size = header_size + 8 + len(code)
    raw = (
        b"DXBC" + bytes(16) + struct.pack("<3I", 1, total_size, 1)
        + struct.pack("<I", header_size)
        + b"SHEX" + struct.pack("<I", len(code)) + code
    )
    return br.stamp_dxbc_checksum(raw)


def synthetic_payloads(plan_root: Path, br) -> dict[tuple[str, str, str], bytes]:
    program_rows = read_tsv(plan_root / "KPS_PROGRAM_TARGET_DWORD_PROTOTYPE_PLAN.tsv")
    edit_rows = read_tsv(plan_root / "KPS_TARGET_DWORD_EDIT_PLAN.tsv")
    edits_by_program: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in edit_rows:
        edits_by_program[row["program_plan_id"]].append(row)
    programs_by_member: dict[tuple[str, str, str], dict[int, dict[str, str]]] = defaultdict(dict)
    for row in program_rows:
        key = (row["normalized_path"].casefold(), row["member_key"], row["member_name"])
        programs_by_member[key][int(row["program_pair_index"])] = row

    result: dict[tuple[str, str, str], bytes] = {}
    for (normalized, member_key, member_name), planned in programs_by_member.items():
        max_pair = max(planned)
        source_parts = [b"KPS-SYNTHETIC\0"]
        target_parts = [b"KPS-SYNTHETIC\0"]
        for pair_index in range(max_pair + 1):
            plan = planned.get(pair_index)
            edits = edits_by_program.get(plan["program_plan_id"], []) if plan else []
            max_instruction = max([int(row["instruction_index"]) for row in edits] + [pair_index + 2])
            lengths = [1] * (max_instruction + 1)
            for row in edits:
                index = int(row["instruction_index"])
                lengths[index] = max(lengths[index], int(row["instruction_dword_index"]) + 1)
            source_values = {
                (int(row["instruction_index"]), int(row["instruction_dword_index"])): int(row["proposed_original_u32_hex"], 16)
                for row in edits
            }
            target_values = {
                (int(row["instruction_index"]), int(row["instruction_dword_index"])): int(row["expected_target_u32_hex"], 16)
                for row in edits
            }
            seed = 1000 + pair_index * 37 + (1 if member_name == "PostEffectGamma.kps" else 200)
            source_parts.append(make_dxbc(br, lengths, source_values, seed=seed))
            source_parts.append(bytes([pair_index & 0xFF]) * (pair_index + 1))
            target_parts.append(make_dxbc(br, lengths, target_values, seed=seed))
            target_parts.append(bytes([pair_index & 0xFF]) * (pair_index + 1))
        result[("source", normalized, member_key)] = b"".join(source_parts)
        result[("target", normalized, member_key)] = b"".join(target_parts)
    return result


class KpsLocalNoInstallPrototypeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        if not STAGE141_ARCHIVE.is_file():
            raise unittest.SkipTest("stage-141 report unavailable")
        cls.temporary = tempfile.TemporaryDirectory(prefix="stage142-test-")
        cls.root = Path(cls.temporary.name)
        cls.report_root = cls.root / "reports"
        cls.output_root = cls.root / "output"
        cls.workspace = cls.root / "workspace"
        cls.prototypes = cls.root / "prototypes"
        cls.report_root.mkdir(parents=True)
        shutil.copy2(STAGE141_ARCHIVE, cls.report_root / stage142.STAGE141_NAME)
        extracted = stage142.extract_report(cls.report_root / stage142.STAGE141_NAME, cls.root / "plan")
        stage134 = stage142.load_module(PROJECT_ROOT / "workstreams/quartet_restoration/134_collect_effect_posteffect_namespace_member_saturation_evidence.py", "stage142_test_stage134")
        br = stage134.load_br_tool(PROJECT_ROOT)
        payloads = synthetic_payloads(extracted, br)
        cls.payloads = payloads
        cls.archive, cls.summary = stage142.build_report(
            PROJECT_ROOT,
            report_root=cls.report_root,
            output_report_root=cls.output_root,
            workspace_root=cls.workspace,
            prototype_root=cls.prototypes,
            create_archive=True,
            payload_provider=lambda side, normalized, member_key: payloads.get((side, normalized, member_key)),
        )
        cls.report = cls.output_root / stage142.REPORT_DIR

    @classmethod
    def tearDownClass(cls) -> None:
        cls.temporary.cleanup()

    def test_summary_cardinality(self) -> None:
        self.assertEqual(self.summary["kps_prototype_artifact_rows"], 2)
        self.assertEqual(self.summary["kps_prototype_program_rows"], 15)
        self.assertEqual(self.summary["kps_applied_target_dword_edit_rows"], 227)
        self.assertEqual(self.summary["kps_target_precondition_rows_verified"], 227)

    def test_two_local_kps_prototypes_are_built(self) -> None:
        self.assertEqual({path.name for path in self.prototypes.iterdir()}, {"PostEffectGamma.kps", "PostEffectGlowLight.kps"})
        self.assertTrue(all(path.stat().st_size > 0 for path in self.prototypes.iterdir()))

    def test_every_planned_edit_is_applied_after_precondition(self) -> None:
        rows = read_tsv(self.report / "KPS_EDIT_APPLICATION.tsv")
        self.assertEqual(len(rows), 227)
        self.assertTrue(all(row["precondition_verified"] == "True" for row in rows))
        self.assertTrue(all(row["edit_applied"] == "True" for row in rows))
        self.assertTrue(all(row["prototype_u32_hex"] == row["proposed_original_u32_hex"] for row in rows))

    def test_every_program_reparses_and_preserves_interface(self) -> None:
        rows = read_tsv(self.report / "KPS_PROGRAM_REPARSE_VERIFICATION.tsv")
        self.assertEqual(len(rows), 15)
        for row in rows:
            self.assertEqual(row["dxbc_checksum_valid"], "True")
            self.assertEqual(row["program_layout_preserved"], "True")
            self.assertEqual(row["noncode_interface_preserved"], "True")
            self.assertEqual(row["opcode_sequence_preserved"], "True")
            self.assertEqual(row["instruction_length_sequence_preserved"], "True")

    def test_unplanned_bytes_are_preserved(self) -> None:
        rows = read_tsv(self.report / "KPS_LOCAL_PROTOTYPE_ARTIFACTS.tsv")
        self.assertEqual(len(rows), 2)
        self.assertTrue(all(row["all_unplanned_bytes_preserved"] == "True" for row in rows))
        self.assertTrue(all(row["target_size"] == row["prototype_size"] for row in rows))

    def test_precondition_drift_fails_closed(self) -> None:
        corrupted = dict(self.payloads)
        key = next(key for key in corrupted if key[0] == "target" and key[2] == "posteffectgamma.kps#0")
        value = bytearray(corrupted[key])
        needle = struct.pack("<I", 0x001000F2)
        offset = bytes(value).find(needle)
        self.assertGreaterEqual(offset, 0)
        value[offset] ^= 0x01
        corrupted[key] = bytes(value)
        with self.assertRaises(stage142.CollectorError):
            stage142.build_report(
                PROJECT_ROOT,
                report_root=self.report_root,
                output_report_root=self.root / "drift-output",
                workspace_root=self.root / "drift-workspace",
                prototype_root=self.root / "drift-prototypes",
                create_archive=False,
                payload_provider=lambda side, normalized, member_key: corrupted.get((side, normalized, member_key)),
            )

    def test_excluded_programs_are_not_prototyped(self) -> None:
        rows = read_tsv(self.report / "KPS_EXCLUDED_PROGRAMS_CARRY_FORWARD.tsv")
        self.assertEqual(len(rows), 28)
        self.assertTrue(all(row["prototype_built"] == "False" for row in rows))

    def test_runtime_state_is_preserved(self) -> None:
        self.assertEqual(self.summary["runtime_validated_profile_rows_preserved"], 1)
        self.assertEqual(self.summary["runtime_failed_shader_rows_preserved"], 2)
        self.assertEqual(self.summary["new_runtime_confirmed_rows"], 0)

    def test_report_contains_no_proprietary_payloads(self) -> None:
        names = [path.name.casefold() for path in self.report.rglob("*") if path.is_file()]
        self.assertFalse(any(name.endswith(stage142.FORBIDDEN_REPORT_EXTENSIONS) for name in names))
        self.assertEqual(self.summary["prototype_artifacts_in_evidence_rows"], 0)

    def test_safety_contract(self) -> None:
        policy = self.summary["policy"]
        self.assertTrue(policy["local_proprietary_prototypes_built_outside_report"])
        self.assertTrue(policy["every_target_dword_precondition_verified"])
        self.assertTrue(policy["only_planned_dwords_and_dxbc_checksums_changed"])
        self.assertFalse(policy["installed_game_modified"])
        self.assertFalse(policy["pak_built_or_repacked"])
        self.assertFalse(policy["prototype_treated_as_patch_or_runtime_validation"])
        self.assertEqual(self.summary["write_authorized_rows"], 0)

    def test_archive_and_summary_are_emitted(self) -> None:
        self.assertIsNotNone(self.archive)
        self.assertTrue(self.archive.is_file())
        self.assertEqual(json.loads((self.report / "SUMMARY.json").read_text()), self.summary)


if __name__ == "__main__":
    unittest.main()
