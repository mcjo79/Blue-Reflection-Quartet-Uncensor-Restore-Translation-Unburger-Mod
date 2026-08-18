from __future__ import annotations

import csv
import importlib.util
import json
import struct
import subprocess
import tempfile
import unittest
from collections import defaultdict
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[3]
SCRIPT = PROJECT / "workstreams/quartet_restoration/140_collect_effect_posteffect_exact_section_content_kps_minimal_patch_feasibility_evidence.py"
SPEC = importlib.util.spec_from_file_location("stage140_collector", SCRIPT)
assert SPEC and SPEC.loader
TOOL = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(TOOL)


def read_tsv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def valid_rdef_payload() -> bytes:
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

    creator_offset = add_string("Compiler A")
    resource_name_offset = add_string("sFixture")
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


def signature_payload(name: str) -> bytes:
    name_offset = 8 + 24
    return struct.pack("<2I", 1, 0) + struct.pack("<5IBBH", name_offset, 0, 0, 3, 0, 0xF, 0xF, 0) + name.encode("ascii") + b"\x00"


def dxbc_program(*, opcode_id: int, operand: int) -> bytes:
    version_token = 5 << 4
    instruction_token = (2 << 24) | opcode_id
    code_payload = struct.pack("<4I", version_token, 4, instruction_token, operand)
    chunks = [
        (b"RDEF", valid_rdef_payload()),
        (b"ISGN", signature_payload("TEXCOORD")),
        (b"OSGN", signature_payload("SV_Target")),
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
    return b"DXBC" + bytes(16) + struct.pack("<3I", 1, total_size, len(chunks)) + struct.pack(f"<{len(offsets)}I", *offsets) + bytes(body)


def section_blob(*, count: int, span: int, seed: int, mutate: bool) -> bytes:
    boundary1 = 56 + 4 * (count - 1)
    boundary2 = 56 + 8 * (count - 1)
    boundary3 = 56 + 12 * (count - 1)
    assert span >= boundary3
    words = [span, 0, count, count, count, 0, 56, boundary1, boundary2, boundary3, 0x00010000, 0, 0, 0]
    out = bytearray(struct.pack("<14I", *words))
    for table in range(3):
        for row in range(count - 1):
            out.extend(struct.pack("<I", (table + 1) * 0x100 + row * 4 + seed))
    body = bytearray(bytes([(seed + 0x41) & 0xFF]) * (span - boundary3))
    if mutate and body:
        body[min(seed % len(body), len(body) - 1)] ^= 0x11
    out.extend(body)
    assert len(out) == span
    return bytes(out)


def g1e_payload(pair_rows: list[dict[str, str]], *, target: bool, seed: int) -> bytes:
    if not pair_rows:
        return b"G1E140_OPAQUE_" + bytes([seed & 0xFF]) * 64
    out = bytearray(b"G1E140".ljust(16, b"\x00"))
    for pair in sorted(pair_rows, key=lambda row: int(row["section_ordinal"])):
        count = int(pair["target_count"] if target else pair["source_count"])
        span = int(pair["target_declared_span"] if target else pair["source_declared_span"])
        mutate = target and pair["section_pair_disposition"] == "exact_section_stable_envelope_content_delta"
        out.extend(section_blob(count=count, span=span, seed=seed + int(pair["section_ordinal"]), mutate=mutate))
    out.extend(b"TAIL140".ljust(16, b"\x00"))
    return bytes(out)


class ExactSectionContentKpsFeasibilityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.report_root = PROJECT / ".local/reports/quartet_restoration"
        root139 = cls.report_root / TOOL.STAGE139_DIR
        member_rows = read_tsv(root139 / "G1E_BROAD_FAMILY_MEMBER_LAYOUT.tsv")
        pair_rows = read_tsv(root139 / "G1E_EXACT_SECTION_PAIRS.tsv")
        cls.pairs_by_member: dict[tuple[str, str], list[dict[str, str]]] = defaultdict(list)
        for row in pair_rows:
            cls.pairs_by_member[(row["normalized_path"].casefold(), row["member_key"])].append(row)
        cls.payloads: dict[tuple[str, str, str], bytes | None] = {}
        for index, row in enumerate(member_rows):
            normalized = row["normalized_path"].casefold(); key = row["member_key"]
            pairs = cls.pairs_by_member[(normalized, key)]
            cls.payloads[("source", normalized, key)] = g1e_payload(pairs, target=False, seed=index)
            cls.payloads[("target", normalized, key)] = g1e_payload(pairs, target=True, seed=index)

        program_rows = read_tsv(root139 / "KPS_EXACT_PROGRAM_LAYOUT.tsv")
        path_rows = read_tsv(root139 / "KPS_EXACT_PATH_LAYOUT.tsv")
        max_index: dict[tuple[str, str], int] = defaultdict(int)
        name_by_key: dict[tuple[str, str], str] = {}
        for row in program_rows:
            ident = (row["normalized_path"].casefold(), row["member_key"])
            max_index[ident] = max(max_index[ident], int(row["program_pair_index"]))
            name_by_key[ident] = row["member_name"]
        for path in path_rows:
            normalized = path["normalized_path"].casefold(); key = path["member_key"]
            count = max_index[(normalized, key)] + 1
            source = bytearray(b"KPS140")
            target = bytearray(b"KPS140")
            for index in range(count):
                source.extend(dxbc_program(opcode_id=1 + (index % 7), operand=0x1000 + index))
                target.extend(dxbc_program(opcode_id=1 + (index % 7), operand=0x2000 + index))
            cls.payloads[("source", normalized, key)] = bytes(source)
            cls.payloads[("target", normalized, key)] = bytes(target)

        cls.temp = tempfile.TemporaryDirectory(prefix="stage140-test-")
        cls.output_root = Path(cls.temp.name) / "reports"
        cls.archive, cls.summary = TOOL.build_report(
            PROJECT,
            report_root=cls.report_root,
            output_report_root=cls.output_root,
            create_archive=True,
            verify_payload_hashes=False,
            payload_provider=lambda side, normalized, key: cls.payloads.get((side, normalized, key)),
            enforce_production_cardinality=True,
        )
        cls.report = cls.output_root / TOOL.REPORT_DIR

    @classmethod
    def tearDownClass(cls) -> None:
        cls.temp.cleanup()

    def test_prerequisite_hashes_and_runtime_profile_are_preserved(self) -> None:
        self.assertEqual(self.summary["stage139_report_sha256"], TOOL.STAGE139_SHA256)
        self.assertEqual(self.summary["stage138_report_sha256"], TOOL.STAGE138_SHA256)
        self.assertEqual(self.summary["runtime_validated_profile_rows_preserved"], 1)

    def test_all_261_section_pairs_are_parsed(self) -> None:
        self.assertEqual(self.summary["g1e_section_pair_rows"], 261)
        self.assertEqual(len(read_tsv(self.report / "G1E_EXACT_SECTION_CONTENT_SUMMARY.tsv")), 261)

    def test_table_triplets_are_ordinal_evidence_not_record_bindings(self) -> None:
        rows = read_tsv(self.report / "G1E_EXACT_SECTION_TABLE_TRIPLETS.tsv")
        self.assertGreater(len(rows), 0)
        self.assertTrue(all(row["table_entries_treated_as_record_bindings"] == "False" for row in rows))
        self.assertEqual(self.summary["g1e_table_triplet_rows"], len(rows))

    def test_opaque_body_segments_are_hashed_without_semantic_claim(self) -> None:
        rows = read_tsv(self.report / "G1E_EXACT_SECTION_BODY_SEGMENTS.tsv")
        self.assertGreater(len(rows), 0)
        self.assertTrue(all(len(row["source_segment_sha256"]) == 64 for row in rows))
        self.assertTrue(all(row["body_segment_treated_as_record_semantics"] == "False" for row in rows))

    def test_no_whole_g1e_member_or_family_is_resolved(self) -> None:
        self.assertEqual(self.summary["g1e_whole_member_layout_resolved_rows"], 0)
        self.assertEqual(self.summary["g1e_whole_family_layout_resolved_rows"], 0)
        rows = read_tsv(self.report / "G1E_MEMBER_EXACT_SECTION_RESIDUAL_SCOPE.tsv")
        self.assertTrue(all(row["whole_member_layout_resolved"] == "False" for row in rows))

    def test_exact_interface_opcode_subset_is_sixteen_programs(self) -> None:
        rows = read_tsv(self.report / "KPS_MINIMAL_PATCH_FEASIBILITY.tsv")
        self.assertEqual(len(rows), 16)
        self.assertEqual(self.summary["kps_exact_interface_opcode_stable_program_rows"], 16)

    def test_synthetic_stable_programs_are_bounded_dword_edit_candidates(self) -> None:
        rows = read_tsv(self.report / "KPS_MINIMAL_PATCH_FEASIBILITY.tsv")
        self.assertTrue(all(row["minimal_patch_feasibility"] == "bounded_target_dword_edit_candidate" for row in rows))
        self.assertGreater(self.summary["kps_bounded_dword_edit_candidate_rows"], 0)

    def test_no_patch_is_built_or_authorized(self) -> None:
        rows = read_tsv(self.report / "KPS_BOUNDED_DWORD_EDIT_CANDIDATES.tsv")
        self.assertTrue(all(row["write_authorized"] == "False" for row in rows))
        self.assertEqual(self.summary["patch_built_rows"], 0)
        self.assertEqual(self.summary["write_authorized_rows"], 0)

    def test_nonminimal_kps_programs_are_carried_forward(self) -> None:
        rows = read_tsv(self.report / "KPS_NONMINIMAL_PROGRAM_CARRY_FORWARD.tsv")
        self.assertEqual(len(rows), 27)
        self.assertEqual(self.summary["kps_nonminimal_program_rows"], 27)

    def test_runtime_failed_shaders_remain_unresolved(self) -> None:
        rows = read_tsv(self.report / "UNRESOLVED_G1EM_G1T_SHADER_CARRY_FORWARD.tsv")
        failed = [row for row in rows if row["identity"] in {"data/x64/shader/heightfog.g1s", "data/x64/shader/swater.g1s"}]
        self.assertEqual(len(failed), 2)
        self.assertTrue(all("runtime_failed" in row["disposition"] for row in failed))

    def test_policy_is_read_only_and_nonsemantic(self) -> None:
        policy = self.summary["policy"]
        self.assertFalse(policy["proprietary_payloads_in_report"])
        self.assertFalse(policy["section_table_entries_treated_as_authoritative_record_bindings"])
        self.assertFalse(policy["partial_exact_section_coverage_treated_as_whole_member_resolution"])
        self.assertFalse(policy["kps_minimal_patch_feasibility_treated_as_patch_or_runtime_validation"])
        self.assertFalse(policy["installed_game_modified"])
        self.assertFalse(policy["profile_or_registry_modified"])

    def test_archive_contains_no_proprietary_payload_extensions(self) -> None:
        assert self.archive is not None
        names = subprocess.run(["tar", "--zstd", "-tf", str(self.archive)], text=True, capture_output=True, check=True).stdout.splitlines()
        self.assertFalse(any(name.casefold().endswith(TOOL.FORBIDDEN_EXTENSIONS) for name in names))

    def test_wrapper_uses_local_paths_configuration_without_hardcoded_paths(self) -> None:
        wrapper = (PROJECT / "workstreams/quartet_restoration/140_collect_effect_posteffect_exact_section_content_kps_minimal_patch_feasibility_evidence.sh").read_text()
        self.assertIn(".local/paths.sh", wrapper)
        self.assertIn("BR1_ORIGINAL_ROOT", wrapper)
        self.assertIn("BR1_QUARTET_ROOT", wrapper)
        self.assertNotIn("/" + "home/", wrapper)
        sep = chr(47)
        self.assertNotIn(sep.join(["", "mnt", "data"]), wrapper)


if __name__ == "__main__":
    unittest.main()
