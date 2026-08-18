from __future__ import annotations

import csv
import importlib.util
import json
import struct
import subprocess
import tempfile
import unittest
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[3]
SCRIPT = PROJECT / "workstreams/quartet_restoration/139_collect_effect_posteffect_broad_g1e_exact_layout_kps_interface_evidence.py"
SPEC = importlib.util.spec_from_file_location("stage139_collector", SCRIPT)
assert SPEC and SPEC.loader
TOOL = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(TOOL)


def read_tsv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def valid_rdef_payload(*, creator: str = "Compiler A", resource_name: str = "sWater") -> bytes:
    header_size = 60
    resource_offset = header_size
    cbuffer_offset = resource_offset + 32
    variable_offset = cbuffer_offset + 24
    type_offset = variable_offset + 40
    strings_offset = type_offset + 36
    strings = bytearray()

    def add_string(value: str) -> int:
        offset = strings_offset + len(strings)
        strings.extend(value.encode("ascii") + b"\x00")
        return offset

    creator_offset = add_string(creator)
    resource_name_offset = add_string(resource_name)
    cbuffer_name_offset = add_string("Globals")
    variable_name_offset = add_string("value")
    type_name_offset = add_string("float")
    header = (
        struct.pack("<4I", 1, cbuffer_offset, 1, resource_offset)
        + struct.pack("<2H", 0x0500, 0xFFFF)
        + struct.pack("<2I", 0, creator_offset)
        + struct.pack("<8I", *([0] * 8))
    )
    resource = struct.pack("<4Ii3I", resource_name_offset, 2, 5, 4, -1, 0, 1, 0)
    cbuffer = struct.pack("<6I", cbuffer_name_offset, 1, variable_offset, 16, 0, 0)
    variable = struct.pack("<6I4I", variable_name_offset, 0, 4, 0, type_offset, 0, 0, 0, 0, 0)
    type_record = struct.pack("<6HI5I", 0, 3, 1, 1, 0, 0, 0, 0, 0, 0, 0, type_name_offset)
    return header + resource + cbuffer + variable + type_record + bytes(strings)


def valid_signature_payload(name: str) -> bytes:
    name_offset = 8 + 24
    return (
        struct.pack("<2I", 1, 0)
        + struct.pack("<5IBBH", name_offset, 0, 0, 3, 0, 0xF, 0xF, 0)
        + name.encode("ascii") + b"\x00"
    )


def dxbc_program(*, creator: str = "Compiler A", opcode_id: int = 1, resource_name: str = "sWater") -> bytes:
    version_token = 5 << 4
    code_payload = struct.pack("<3I", version_token, 3, (1 << 24) | opcode_id)
    chunks = [
        (b"RDEF", valid_rdef_payload(creator=creator, resource_name=resource_name)),
        (b"ISGN", valid_signature_payload("TEXCOORD")),
        (b"OSGN", valid_signature_payload("SV_Target")),
        (b"SHDR", code_payload),
        (b"STAT", struct.pack("<37I", *([opcode_id] + [0] * 36))),
    ]
    header_size = 32 + 4 * len(chunks)
    offsets: list[int] = []
    body = bytearray()
    current = header_size
    for fourcc, payload in chunks:
        offsets.append(current)
        encoded = fourcc + struct.pack("<I", len(payload)) + payload
        body.extend(encoded)
        current += len(encoded)
    total_size = header_size + len(body)
    return (
        b"DXBC" + bytes(16) + struct.pack("<3I", 1, total_size, len(chunks))
        + struct.pack(f"<{len(offsets)}I", *offsets) + bytes(body)
    )


def exact_section_payload(seed: int, *, target: bool) -> bytes:
    prefix = bytearray(b"G1E_STAGE139".ljust(16, b"\x00"))
    count = 3
    span = 96
    words = [span, 0, count, count, count, 0, 56, 64, 72, 80, 0x00010000, 0, 0, 0]
    section = bytearray(struct.pack("<14I", *words))
    section.extend(struct.pack("<2I", 8, 16))
    section.extend(struct.pack("<2I", 24, 32))
    section.extend(struct.pack("<2I", 40, 48))
    body = bytearray((f"record-{seed:04d}".encode("ascii") * 4)[:16].ljust(16, b"R"))
    if target:
        body[seed % 12] ^= 0x11
    section.extend(body)
    assert len(section) == span
    return bytes(prefix + section + b"TAIL" * 4)


class BroadG1eExactLayoutKpsInterfaceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.report_root = PROJECT / ".local/reports/quartet_restoration"
        root137 = cls.report_root / TOOL.STAGE137_DIR
        root136 = cls.report_root / TOOL.STAGE136_DIR
        broad = [
            row for row in read_tsv(root137 / "G1E_RECURRENT_STRUCTURE_FAMILY_PARSER_QUEUE.tsv")
            if row["recurrence_tier"] == "broad_ge_10_members"
        ]
        ids = {row["structure_family_id"] for row in broad}
        cls.g1e_rows = [
            row for row in read_tsv(root136 / "G1E_STRUCTURAL_PAIR_AUDIT.tsv")
            if row["structure_family_id"] in ids
        ]
        cls.kps_rows = read_tsv(root137 / "KPS_EXACT_PARSER_PATH_QUEUE.tsv")
        cls.payloads: dict[tuple[str, str, str], bytes | None] = {}
        for index, row in enumerate(cls.g1e_rows):
            normalized = row["normalized_path"].casefold()
            key = row["member_key"]
            cls.payloads[("source", normalized, key)] = exact_section_payload(index, target=False)
            cls.payloads[("target", normalized, key)] = exact_section_payload(index, target=True)
        for index, row in enumerate(cls.kps_rows):
            normalized = row["normalized_path"].casefold()
            key = row["member_key"]
            disposition = row["kps_path_disposition"]
            if disposition == "target_added_kps":
                source = None
                target = dxbc_program(opcode_id=10 + index)
            elif disposition == "dxbc_program_inventory_delta":
                shared = dxbc_program(opcode_id=1)
                source = b"KPS0" + shared
                target = b"KPS0" + shared + dxbc_program(opcode_id=20 + index)
            elif disposition == "executable_code_delta_with_interface_delta":
                source = b"KPS0" + dxbc_program(opcode_id=1, resource_name="sWater")
                target = b"KPS0" + dxbc_program(opcode_id=2, resource_name="sFog")
            else:
                source = b"KPS0" + dxbc_program(opcode_id=1, resource_name="sWater")
                target = b"KPS0" + dxbc_program(opcode_id=2, resource_name="sWater")
            cls.payloads[("source", normalized, key)] = source
            cls.payloads[("target", normalized, key)] = target

        cls.temp = tempfile.TemporaryDirectory(prefix="stage139-test-")
        cls.output_root = Path(cls.temp.name) / "reports"
        cls.archive, cls.summary = TOOL.build_report(
            PROJECT,
            report_root=cls.report_root,
            output_report_root=cls.output_root,
            create_archive=True,
            verify_payload_hashes=False,
            payload_provider=lambda side, normalized, key: cls.payloads.get((side, normalized, key)),
            enforce_production_cardinality=False,
        )
        cls.report = cls.output_root / TOOL.REPORT_DIR

    @classmethod
    def tearDownClass(cls) -> None:
        cls.temp.cleanup()

    def test_exact_prerequisite_hashes_and_runtime_state(self) -> None:
        self.assertEqual(self.summary["stage137_report_sha256"], TOOL.STAGE137_SHA256)
        self.assertEqual(self.summary["stage138_report_sha256"], TOOL.STAGE138_SHA256)
        self.assertEqual(self.summary["runtime_validated_profile_rows_preserved"], 1)

    def test_production_queue_is_seven_families_and_288_members(self) -> None:
        self.assertEqual(len(self.g1e_rows), 288)
        self.assertEqual(self.summary["broad_g1e_structure_family_rows"], 7)
        self.assertEqual(self.summary["broad_g1e_member_rows"], 288)

    def test_exact_section_scanner_finds_calibrated_layout(self) -> None:
        stage90 = TOOL.load_module(
            PROJECT / "workstreams/quartet_restoration/collect_reflector_slot_light_target_section_layout_evidence.py",
            "stage139_test_stage90",
        )
        rows = TOOL.scan_exact_section_headers(exact_section_payload(1, target=False), stage90.parse_section_header)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["count"], 3)
        self.assertEqual(rows[0]["table_entry_rows"], 2)

    def test_all_synthetic_members_have_exact_layout(self) -> None:
        rows = read_tsv(self.report / "G1E_BROAD_FAMILY_MEMBER_LAYOUT.tsv")
        self.assertEqual(len(rows), 288)
        self.assertTrue(all(int(row["source_exact_section_rows"]) == 1 for row in rows))
        self.assertTrue(all(int(row["target_exact_section_rows"]) == 1 for row in rows))
        self.assertEqual(self.summary["g1e_members_with_any_exact_section_rows"], 288)

    def test_changed_segments_are_bound_without_semantic_claim(self) -> None:
        rows = read_tsv(self.report / "G1E_CHANGE_SEGMENT_SECTION_BINDING.tsv")
        self.assertGreater(len(rows), 0)
        self.assertGreater(self.summary["g1e_fully_bound_changed_segment_rows"], 0)
        self.assertTrue(all(row["field_semantics_confirmed"] == "False" for row in rows))
        self.assertTrue(all(row["write_authorized"] == "False" for row in rows))

    def test_all_six_kps_paths_are_parsed(self) -> None:
        rows = read_tsv(self.report / "KPS_EXACT_PATH_LAYOUT.tsv")
        self.assertEqual(len(rows), 6)
        self.assertEqual(self.summary["kps_exact_path_rows"], 6)
        self.assertGreater(self.summary["kps_exact_program_rows"], 0)

    def test_kps_rdef_and_signature_tables_are_materialized(self) -> None:
        self.assertGreater(len(read_tsv(self.report / "KPS_RDEF_RESOURCES.tsv")), 0)
        self.assertGreater(len(read_tsv(self.report / "KPS_RDEF_CBUFFERS.tsv")), 0)
        self.assertGreater(len(read_tsv(self.report / "KPS_RDEF_VARIABLES.tsv")), 0)
        self.assertGreater(len(read_tsv(self.report / "KPS_SIGNATURE_ELEMENTS.tsv")), 0)
        self.assertGreater(len(read_tsv(self.report / "KPS_INSTRUCTION_OPCODE_SUMMARY.tsv")), 0)

    def test_stage137_exact_program_queue_is_43(self) -> None:
        rows = read_tsv(self.report_root / TOOL.STAGE137_DIR / "KPS_EXACT_PARSER_PROGRAM_QUEUE.tsv")
        self.assertEqual(len(rows), 43)

    def test_runtime_failed_shaders_stay_unresolved(self) -> None:
        rows = read_tsv(self.report / "UNRESOLVED_G1EM_G1T_SHADER_CARRY_FORWARD.tsv")
        failed = [row for row in rows if row["identity"] in {"data/x64/shader/heightfog.g1s", "data/x64/shader/swater.g1s"}]
        self.assertEqual(len(failed), 2)
        self.assertTrue(all("runtime_failed" in row["disposition"] for row in failed))
        self.assertTrue(all(row["write_authorized"] == "False" for row in failed))

    def test_policy_is_read_only_and_nonsemantic(self) -> None:
        policy = self.summary["policy"]
        self.assertFalse(policy["proprietary_payloads_in_report"])
        self.assertFalse(policy["runtime_failed_shader_promoted"])
        self.assertFalse(policy["event_profiles_promoted"])
        self.assertFalse(policy["installed_game_modified"])
        self.assertFalse(policy["profile_or_registry_modified"])
        self.assertEqual(self.summary["write_authorized_rows"], 0)

    def test_report_archive_contains_no_payload_extensions(self) -> None:
        assert self.archive is not None
        names = subprocess.run(
            ["tar", "--zstd", "-tf", str(self.archive)], text=True, capture_output=True, check=True
        ).stdout.splitlines()
        self.assertFalse(any(name.casefold().endswith(TOOL.FORBIDDEN_EXTENSIONS) for name in names))

    def test_wrapper_uses_local_paths_configuration_without_hardcoded_paths(self) -> None:
        wrapper = (PROJECT / "workstreams/quartet_restoration/139_collect_effect_posteffect_broad_g1e_exact_layout_kps_interface_evidence.sh").read_text()
        self.assertIn(".local/paths.sh", wrapper)
        self.assertIn("BR1_ORIGINAL_ROOT", wrapper)
        self.assertIn("BR1_QUARTET_ROOT", wrapper)
        self.assertNotIn("/" + "home/", wrapper)
        sep = chr(47)
        self.assertNotIn(sep.join(["", "mnt", "data"]), wrapper)


if __name__ == "__main__":
    unittest.main()
