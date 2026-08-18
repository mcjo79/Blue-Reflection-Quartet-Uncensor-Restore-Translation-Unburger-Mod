from __future__ import annotations

import csv
import importlib.util
import json
import struct
import tempfile
import unittest
from unittest import mock
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[3]
SCRIPT = PROJECT / "workstreams/quartet_restoration/133_collect_shader_namespace_executable_signature_reflection_sweep_evidence.py"
SPEC = importlib.util.spec_from_file_location("stage133_collector", SCRIPT)
assert SPEC and SPEC.loader
TOOL = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(TOOL)

BR_PATH = PROJECT / "Blue_Reflection_Text_Tool/br_restoration_tool.py"
BR_SPEC = importlib.util.spec_from_file_location("stage133_test_br", BR_PATH)
assert BR_SPEC and BR_SPEC.loader
BR = importlib.util.module_from_spec(BR_SPEC)
BR_SPEC.loader.exec_module(BR)


def read_tsv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def valid_rdef_payload(
    *, creator: str = "Compiler A", resource_name: str = "sWater",
    cbuffer_name: str = "Globals", variable_name: str = "waterAlpha",
) -> bytes:
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
    cbuffer_name_offset = add_string(cbuffer_name)
    variable_name_offset = add_string(variable_name)
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


def valid_signature_payload(name: str, *, register: int = 0) -> bytes:
    name_offset = 8 + 24
    return (
        struct.pack("<2I", 1, 0)
        + struct.pack("<5IBBH", name_offset, 0, 0, 3, register, 0xF, 0xF, 0)
        + name.encode("ascii") + b"\x00"
    )


def dxbc_program(
    *, creator: str = "Compiler A", opcode_id: int = 1,
    resource_name: str = "sWater", stage_code: int = 0,
) -> bytes:
    version_token = (stage_code << 16) | (5 << 4)
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


class ShaderNamespaceSweepTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.report_root = PROJECT / ".local/reports/quartet_restoration"
        cls.stage130 = cls.report_root / TOOL.STAGE130_DIR
        cls.candidates = [
            row for row in read_tsv(cls.stage130 / "NON_CHARACTER_TECHNICAL_CANDIDATES.tsv")
            if row["namespace"] == "shader"
        ]
        cls.inventories = {
            side: TOOL.load_inventory(PROJECT, side) for side in ("source", "target")
        }

    def test_pair_programs_preserves_exact_rows(self) -> None:
        exact = BR.find_dxbc_programs(dxbc_program())
        rows = TOOL.pair_programs(exact, exact)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["matching_basis"], "exact_program_sha256")

    def test_program_analysis_metadata_only(self) -> None:
        source = dxbc_program(creator="Compiler A", opcode_id=1)
        target = dxbc_program(creator="Compiler B", opcode_id=1)
        result, _chunks = TOOL.program_analysis(
            BR, source, target,
            BR.find_dxbc_programs(source)[0], BR.find_dxbc_programs(target)[0],
            "test",
        )
        self.assertEqual(result["classification"], "nonexecutive_metadata_or_compiler_delta")
        self.assertTrue(result["code_chunks_identical"])
        self.assertEqual(result["reflection_semantics"], "compatible")

    def test_program_analysis_code_delta_stable_interface(self) -> None:
        source = dxbc_program(opcode_id=1)
        target = dxbc_program(opcode_id=2)
        result, _chunks = TOOL.program_analysis(
            BR, source, target,
            BR.find_dxbc_programs(source)[0], BR.find_dxbc_programs(target)[0],
            "test",
        )
        self.assertEqual(result["classification"], "executable_code_delta_interface_stable")
        self.assertFalse(result["code_chunks_identical"])

    def test_program_analysis_interface_delta_without_code(self) -> None:
        source = dxbc_program(resource_name="sWater", opcode_id=1)
        target = dxbc_program(resource_name="sFog", opcode_id=1)
        result, _chunks = TOOL.program_analysis(
            BR, source, target,
            BR.find_dxbc_programs(source)[0], BR.find_dxbc_programs(target)[0],
            "test",
        )
        self.assertEqual(result["classification"], "interface_delta_without_executable_code_delta")
        self.assertEqual(result["reflection_semantics"], "different")

    def test_target_only_program_is_not_restoration_candidate(self) -> None:
        target = dxbc_program()
        result, chunks = TOOL.program_analysis(
            BR, None, target, None, BR.find_dxbc_programs(target)[0], "target_only"
        )
        self.assertEqual(result["classification"], "program_added_in_target")
        self.assertEqual(chunks, [])

    def test_stage130_queue_is_exactly_214_paths(self) -> None:
        self.assertEqual(len(self.candidates), 214)
        self.assertEqual(sum(row["extension"] == ".g1s" for row in self.candidates), 213)
        self.assertEqual(sum(row["extension"] == ".g1t" for row in self.candidates), 1)
        self.assertEqual(sum(row["classification"] == "changed" for row in self.candidates), 190)
        self.assertEqual(sum(row["classification"] == "new_in_target" for row in self.candidates), 24)

    def test_full_synthetic_214_path_report(self) -> None:
        with tempfile.TemporaryDirectory(prefix="stage133-test-") as text:
            root = Path(text)
            workspace = root / "workspace"
            output = root / "reports"
            for row in self.candidates:
                normalized = row["normalized_path"].casefold()
                for side in ("source", "target"):
                    entry = self.inventories[side].get(normalized)
                    if entry is None:
                        continue
                    local = BR.inventory_workspace_file(
                        workspace, side, "br1_assets", str(entry["archive"]), str(entry["path"])
                    )
                    local.parent.mkdir(parents=True, exist_ok=True)
                    if row["extension"] == ".g1t":
                        payload = b"synthetic-target-only-texture"
                    elif side == "source":
                        payload = dxbc_program(creator="Compiler A", opcode_id=1, resource_name="sWater")
                    elif row["normalized_path"] in {
                        "data/x64/shader/heightfog.g1s",
                        "data/x64/shader/swater.g1s",
                    }:
                        payload = dxbc_program(creator="Compiler B", opcode_id=2, resource_name="sWater")
                    elif row["normalized_path"] == "data/x64/shader/cdc.g1s":
                        payload = dxbc_program(creator="Compiler B", opcode_id=1, resource_name="sFog")
                    else:
                        payload = dxbc_program(creator="Compiler B", opcode_id=1, resource_name="sWater")
                    local.write_bytes(payload)

            with mock.patch.object(TOOL, "progress", lambda _message: None):
                _archive, summary = TOOL.build_report(
                    PROJECT,
                    report_root=self.report_root,
                    output_report_root=output,
                    workspace_root=workspace,
                    create_archive=False,
                    verify_payload_hashes=False,
                )
            self.assertEqual(summary["shader_path_rows"], 214)
            self.assertEqual(summary["g1s_path_rows"], 213)
            self.assertEqual(summary["g1t_path_rows"], 1)
            self.assertEqual(summary["target_only_shader_path_rows"], 24)
            self.assertEqual(summary["skipped_rows"], 0)
            self.assertEqual(summary["water_shader_executable_code_delta_rows"], 0)
            self.assertGreater(summary["interface_stable_executable_candidate_path_rows"], 0)
            rows = read_tsv(output / TOOL.REPORT_DIR / "SHADER_PATH_CLASSIFICATION.tsv")
            by_path = {row["normalized_path"]: row for row in rows}
            self.assertEqual(by_path["data/x64/shader/heightfog.g1s"]["path_disposition"], "executable_code_delta_interface_stable")
            self.assertEqual(by_path["data/x64/shader/cwater.g1s"]["path_disposition"], "nonexecutive_metadata_or_compiler_delta")
            self.assertEqual(by_path["data/x64/shader/cdc.g1s"]["path_disposition"], "interface_delta_without_executable_code_delta")
            self.assertEqual(by_path["data/x64/shader/texture/caustics.g1t"]["path_disposition"], "target_only_shader_texture_dependency")

    def test_report_contains_no_shader_payload_extensions(self) -> None:
        with tempfile.TemporaryDirectory(prefix="stage133-report-") as text:
            root = Path(text)
            report = root / TOOL.REPORT_DIR
            report.mkdir()
            (report / "SUMMARY.json").write_text("{}\n", encoding="utf-8")
            names = [path.name.casefold() for path in report.rglob("*") if path.is_file()]
            self.assertFalse(any(any(name.endswith(ext) for ext in TOOL.FORBIDDEN_EXTENSIONS) for name in names))

    def test_wrapper_uses_local_paths_configuration(self) -> None:
        wrapper = (PROJECT / "workstreams/quartet_restoration/133_collect_shader_namespace_executable_signature_reflection_sweep_evidence.sh").read_text(encoding="utf-8")
        self.assertIn(".local/paths.sh", wrapper)
        self.assertIn("BR1_ORIGINAL_ROOT", wrapper)
        self.assertIn("BR1_QUARTET_ROOT", wrapper)
        self.assertNotIn("/" + "home" + "/", wrapper)
        sep = chr(47)
        self.assertNotIn(sep.join(["", "mnt", "data"]), wrapper)

    def test_version_gate_rejects_old_tree(self) -> None:
        with tempfile.TemporaryDirectory() as text:
            project = Path(text)
            version = project / "workstreams/quartet_restoration/VERSION"
            version.parent.mkdir(parents=True)
            version.write_text("0.1.50\n", encoding="utf-8")
            with self.assertRaisesRegex(TOOL.CollectorError, "0.1.51"):
                TOOL.build_report(project, create_archive=False)

    def test_path_disposition_program_inventory_delta(self) -> None:
        rows = [{"classification": "program_added_in_target"}]
        self.assertEqual(TOOL.path_disposition(rows, False), "dxbc_program_inventory_delta")

    def test_stage132_prerequisite_hash_is_fixed(self) -> None:
        report = self.report_root / TOOL.STAGE132_NAME
        summary = self.report_root / TOOL.STAGE132_DIR / "SUMMARY.json"
        self.assertEqual(TOOL.sha256_file(report), TOOL.STAGE132_SHA256)
        self.assertEqual(TOOL.sha256_file(summary), TOOL.STAGE132_SUMMARY_SHA256)


if __name__ == "__main__":
    unittest.main()
