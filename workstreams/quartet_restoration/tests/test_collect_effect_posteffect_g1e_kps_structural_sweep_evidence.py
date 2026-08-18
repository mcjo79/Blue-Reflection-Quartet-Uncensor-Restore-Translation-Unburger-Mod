from __future__ import annotations

import csv
import importlib.util
import struct
import subprocess
import sys
import tempfile
import unittest
import zlib
from pathlib import Path

WORKSTREAM = Path(__file__).resolve().parents[1]
PROJECT = WORKSTREAM.parent.parent
TOOL_PATH = WORKSTREAM / "136_collect_effect_posteffect_g1e_kps_structural_sweep_evidence.py"
SPEC = importlib.util.spec_from_file_location("stage136_tool", TOOL_PATH)
assert SPEC and SPEC.loader
TOOL = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = TOOL
SPEC.loader.exec_module(TOOL)

BR_PATH = PROJECT / "Blue_Reflection_Text_Tool/br_restoration_tool.py"
BR_SPEC = importlib.util.spec_from_file_location("stage136_test_br", BR_PATH)
assert BR_SPEC and BR_SPEC.loader
BR = importlib.util.module_from_spec(BR_SPEC)
sys.modules[BR_SPEC.name] = BR
BR_SPEC.loader.exec_module(BR)


def read_tsv(path: Path):
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


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


def write_gust_chunked(path: Path, payload: bytes) -> None:
    compressed = zlib.compress(payload, 9)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(len(compressed).to_bytes(4, "little") + compressed + (0).to_bytes(4, "little"))


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
    version_token = (5 << 4)
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
    return b"DXBC" + bytes(16) + struct.pack("<3I", 1, total_size, len(chunks)) + struct.pack(f"<{len(offsets)}I", *offsets) + bytes(body)


def synthetic_g1e(index: int, side: str) -> bytes:
    header = bytearray(b"G1E_SYNTHETIC".ljust(96, b"\x00"))
    struct.pack_into("<I", header, 32, 4)
    body = bytearray((f"record-{index:04d}-".encode("ascii") * 16)[:192].ljust(192, b"R"))
    if side == "source":
        return bytes(header + body)
    mode = index % 4
    if mode == 0:
        struct.pack_into("<I", body, 64, index + 100)
    elif mode == 1:
        body[80:80] = b"INSERTED_RECORD!!"
    elif mode == 2:
        del body[80:96]
    else:
        body[48:72] = b"MIXED_TARGET_BLOCK_123456"
        body.extend(b"TAILPLUS")
    return bytes(header + body)


def synthetic_kps(index: int, side: str, added: bool) -> bytes | None:
    if added and side == "source":
        return None
    if side == "source":
        program = dxbc_program(creator="Compiler A", opcode_id=1, resource_name="sWater")
    elif index % 4 == 0:
        program = dxbc_program(creator="Compiler B", opcode_id=1, resource_name="sWater")
    elif index % 4 == 1:
        program = dxbc_program(creator="Compiler A", opcode_id=2, resource_name="sWater")
    elif index % 4 == 2:
        program = dxbc_program(creator="Compiler A", opcode_id=1, resource_name="sFog")
    else:
        program = dxbc_program(creator="Compiler B", opcode_id=2, resource_name="sFog")
    return b"KPS0" + index.to_bytes(4, "little") + program + b"KPS_END"


class EffectPosteffectG1eKpsStructuralSweepTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.tmp = tempfile.TemporaryDirectory(prefix="stage136-tests-")
        cls.root = Path(cls.tmp.name)
        cls.workspace = cls.root / "workspace"
        cls.report_root = PROJECT / ".local/reports/quartet_restoration"
        stage135 = cls.report_root / TOOL.STAGE135_DIR
        cls.selected = [
            row for row in read_tsv(stage135 / "EFFECT_POSTEFFECT_MEMBER_FORMAT_CLASSIFICATION.tsv")
            if row["member_extension"] in {".g1e", ".kps"}
        ]
        stage134 = cls.report_root / TOOL.STAGE134_DIR
        cls.candidates = [
            {"namespace": row["namespace"], "normalized_path": row["normalized_path"]}
            for row in read_tsv(stage134 / "EFFECT_POSTEFFECT_PATH_SUMMARY.tsv")
        ]
        cls.inventories = {side: TOOL.load_module(
            PROJECT / "workstreams/quartet_restoration/134_collect_effect_posteffect_namespace_member_saturation_evidence.py",
            f"stage136_test_stage134_{side}",
        ).load_inventory(PROJECT, side) for side in ("source", "target")}

        by_path: dict[str, list[dict[str, str]]] = {}
        for row in cls.selected:
            by_path.setdefault(row["normalized_path"].casefold(), []).append(row)
        for candidate in cls.candidates:
            normalized = candidate["normalized_path"].casefold()
            rows = sorted(by_path.get(normalized, []), key=lambda row: row["member_key"])
            for side in ("source", "target"):
                entry = cls.inventories[side][normalized]
                local = BR.inventory_workspace_file(cls.workspace, side, "br1_assets", str(entry["archive"]), str(entry["path"]))
                members: list[tuple[str, bytes]] = []
                for index, row in enumerate(rows):
                    name = row["target_member_name"] or row["source_member_name"]
                    if row["member_extension"] == ".g1e":
                        payload = synthetic_g1e(index, side)
                    else:
                        payload = synthetic_kps(index, side, row["classification"] == "added_in_target")
                    if payload is not None:
                        members.append((name, payload))
                write_gust_chunked(local, make_earc(members))

        cls.archive, cls.summary = TOOL.build_report(
            PROJECT,
            report_root=cls.report_root,
            output_report_root=cls.root / "reports",
            workspace_root=cls.workspace,
            create_archive=True,
            verify_payload_hashes=False,
        )
        cls.report = cls.root / "reports" / TOOL.REPORT_DIR
        cls.g1e = read_tsv(cls.report / "G1E_STRUCTURAL_PAIR_AUDIT.tsv")
        cls.families = read_tsv(cls.report / "G1E_STRUCTURE_FAMILIES.tsv")
        cls.kps = read_tsv(cls.report / "KPS_PATH_CLASSIFICATION.tsv")
        cls.programs = read_tsv(cls.report / "KPS_DXBC_PROGRAM_CLASSIFICATION.tsv")
        cls.carry = read_tsv(cls.report / "UNRESOLVED_G1EM_G1T_SHADER_CARRY_FORWARD.tsv")

    @classmethod
    def tearDownClass(cls) -> None:
        cls.tmp.cleanup()

    def test_exact_prerequisite_hashes(self):
        self.assertEqual(self.summary["stage134_report_sha256"], TOOL.STAGE134_SHA256)
        self.assertEqual(self.summary["stage135_report_sha256"], TOOL.STAGE135_SHA256)

    def test_all_g1e_members_are_structurally_swept(self):
        self.assertEqual(len(self.g1e), 621)
        self.assertEqual(self.summary["g1e_member_rows"], 621)
        self.assertEqual(self.summary["skipped_rows"], 0)

    def test_g1e_alignment_partitions_have_multiple_shapes(self):
        dispositions = {row["g1e_structure_disposition"] for row in self.g1e}
        self.assertIn("same_size_replacement_only", dispositions)
        self.assertTrue(any("insertion" in value or "mixed" in value for value in dispositions))
        self.assertGreater(len(self.families), 1)

    def test_g1e_dword_transitions_remain_unresolved(self):
        self.assertGreater(self.summary["g1e_changed_word_rows"], 0)
        self.assertTrue(all(row["visual_or_censorship_semantics_confirmed"] == "False" for row in self.g1e))
        self.assertTrue(all(row["write_authorized"] == "False" for row in self.g1e))

    def test_all_kps_members_are_classified(self):
        self.assertEqual(len(self.kps), 27)
        self.assertEqual(self.summary["kps_member_rows"], 27)
        self.assertEqual(self.summary["kps_target_added_member_rows"], 1)

    def test_kps_dxbc_program_classes_are_separated(self):
        classes = {row["classification"] for row in self.programs}
        self.assertIn("nonexecutive_metadata_or_compiler_delta", classes)
        self.assertIn("executable_code_delta_interface_stable", classes)
        self.assertIn("interface_delta_without_executable_code_delta", classes)
        self.assertIn("program_added_in_target", classes)

    def test_g1em_g1t_and_shaders_are_carried_unresolved(self):
        self.assertEqual(self.summary["unresolved_g1em_g1t_rows"], 10)
        self.assertEqual(self.summary["unresolved_shader_rows"], 15)
        self.assertEqual(len(self.carry), 25)
        self.assertTrue(all(row["write_authorized"] == "False" for row in self.carry))

    def test_policy_is_read_only_and_nonsemantic(self):
        policy = self.summary["policy"]
        self.assertTrue(policy["local_proprietary_payloads_read"])
        for key in (
            "proprietary_payloads_in_report", "g1e_alignment_or_dword_shape_treated_as_field_semantics",
            "kps_dxbc_code_or_interface_delta_treated_as_visual_semantics",
            "member_name_size_recurrence_or_float_appearance_treated_as_censorship_proof",
            "runtime_or_save_required", "pak_built_or_repacked", "installed_game_modified",
            "profile_or_registry_modified", "core_modified", "translation_modified", "legacy_dlc_modified", "git_modified",
        ):
            self.assertFalse(policy[key], key)

    def test_report_contains_no_payload_extensions(self):
        names = subprocess.run(
            ["tar", "--zstd", "-tf", str(self.archive)], text=True, capture_output=True, check=True
        ).stdout.splitlines()
        self.assertFalse(any(name.casefold().endswith(TOOL.FORBIDDEN_EXTENSIONS) for name in names))

    def test_wrapper_uses_local_paths_configuration(self):
        wrapper = (WORKSTREAM / "136_collect_effect_posteffect_g1e_kps_structural_sweep_evidence.sh").read_text(encoding="utf-8")
        self.assertIn(".local/paths.sh", wrapper)
        self.assertIn("BR1_ORIGINAL_ROOT", wrapper)
        self.assertIn("BR1_QUARTET_ROOT", wrapper)
        self.assertNotIn("/" + "home" + "/", wrapper)
        sep = chr(47)
        self.assertNotIn(sep.join(["", "mnt", "data"]), wrapper)

    def test_version_gate_rejects_old_tree(self):
        with tempfile.TemporaryDirectory() as text:
            project = Path(text)
            version = project / "workstreams/quartet_restoration/VERSION"
            version.parent.mkdir(parents=True)
            version.write_text("0.1.53\n", encoding="utf-8")
            with self.assertRaisesRegex(TOOL.CollectorError, "0.1.54"):
                TOOL.build_report(project, create_archive=False)

    def test_archive_is_created(self):
        self.assertIsNotNone(self.archive)
        self.assertTrue(self.archive.is_file())


if __name__ == "__main__":
    unittest.main()
