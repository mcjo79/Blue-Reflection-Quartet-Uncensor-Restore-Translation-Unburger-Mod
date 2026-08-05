from __future__ import annotations

import gzip
import hashlib
import importlib.util
import json
import os
import shutil
import struct
import zipfile
import tempfile
import unittest
import zlib
from collections import Counter
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
TOOL_PATH = ROOT / "Blue_Reflection_Text_Tool" / "br_restoration_tool.py"
SPEC = importlib.util.spec_from_file_location("br_restoration_tool", TOOL_PATH)
assert SPEC and SPEC.loader
TOOL = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(TOOL)


def entry(path: str, content: bytes, archive: str = "A.PAK") -> dict:
    with tempfile.NamedTemporaryFile() as handle:
        handle.write(content)
        handle.flush()
        file_path = Path(handle.name)
        normalized = path.replace("\\\\", "/")
        magic = TOOL.read_magic(file_path)
        return {
            "archive": archive,
            "path": normalized,
            "normalized_path": normalized,
            "comparison_key": normalized.casefold(),
            "normalization_rule": None,
            "size": len(content),
            "sha256": TOOL.sha256_file(file_path),
            "extension": Path(normalized).suffix.casefold(),
            "asset_type": TOOL.classify_asset(normalized, magic),
            "magic_hex": magic,
            "sample_block_size": TOOL.SAMPLE_BLOCK_SIZE,
            "sample_hashes": TOOL.sample_hashes(file_path),
            "normalized_path_collision_count": 1,
        }


def inventory(
    target: str,
    files: list[dict],
    *,
    pair: str = "test_pair",
    side: str = "source",
) -> dict:
    return {
        "type": "br_asset_inventory",
        "format_version": 1,
        "tool_version": TOOL.TOOL_VERSION,
        "target_id": target,
        "archive_group": pair,
        "normalization_side": side,
        "files": files,
    }




def earc_archive(files: list[tuple[str, bytes]]) -> bytes:
    max_name = max([0x30, *(len(name.encode("utf-8")) + 1 for name, _ in files)])
    filename_size = (max_name - 0x20 + 0x0F) // 0x10
    entry_size = 8 + 0x20 + filename_size * 0x10
    table_size = len(files) * entry_size
    payload_offset = TOOL.EARC_HEADER_SIZE + table_size
    table = bytearray(table_size)
    payload = bytearray()
    current = payload_offset
    for index, (name, data) in enumerate(files):
        offset = index * entry_size
        struct.pack_into("<2I", table, offset, current, len(data))
        encoded = name.encode("utf-8")
        table[offset + 8 : offset + 8 + len(encoded)] = encoded
        payload.extend(data)
        current += len(data)
    header = struct.pack(
        "<7I",
        TOOL.EARC_MAGIC,
        filename_size,
        len(payload),
        TOOL.EARC_HEADER_SIZE,
        table_size,
        len(files),
        0,
    )
    return header + bytes(table) + bytes(payload)

def gust_chunked_zlib(payload: bytes, chunk_size: int = 0x4000) -> bytes:
    encoded = bytearray()
    for offset in range(0, len(payload), chunk_size):
        compressed = zlib.compress(payload[offset : offset + chunk_size])
        encoded.extend(len(compressed).to_bytes(4, "little"))
        encoded.extend(compressed)
    encoded.extend((0).to_bytes(4, "little"))
    return bytes(encoded)




def dxbc_program(
    *,
    stage_code: int = 0,
    resource_token: str = "g_WaterAlpha",
    instruction_marker: int = 1,
) -> bytes:
    version_token = (stage_code << 16) | (5 << 4)
    shdr_payload = struct.pack("<2I", version_token, instruction_marker)
    rdef_payload = resource_token.encode("ascii") + b"\x00"
    chunks = [(b"RDEF", rdef_payload), (b"SHDR", shdr_payload)]
    header_size = 32 + 4 * len(chunks)
    offsets = []
    body = bytearray()
    current = header_size
    for fourcc, payload in chunks:
        offsets.append(current)
        encoded = fourcc + struct.pack("<I", len(payload)) + payload
        body.extend(encoded)
        current += len(encoded)
    total_size = header_size + len(body)
    return (
        b"DXBC"
        + bytes(16)
        + struct.pack("<3I", 1, total_size, len(chunks))
        + struct.pack(f"<{len(offsets)}I", *offsets)
        + bytes(body)
    )



def valid_rdef_payload(
    *,
    creator: str = "Microsoft HLSL Compiler A",
    resource_name: str = "sWater",
    cbuffer_name: str = "Globals",
    variable_name: str = "waterAlpha",
    bind_point: int = 0,
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
    resource = struct.pack(
        "<4Ii3I",
        resource_name_offset,
        2,
        5,
        4,
        -1,
        bind_point,
        1,
        0,
    )
    cbuffer = struct.pack(
        "<6I",
        cbuffer_name_offset,
        1,
        variable_offset,
        16,
        0,
        0,
    )
    variable = struct.pack(
        "<6I4I",
        variable_name_offset,
        0,
        4,
        0,
        type_offset,
        0,
        0,
        0,
        0,
        0,
    )
    type_record = struct.pack(
        "<6HI5I",
        0,
        3,
        1,
        1,
        0,
        0,
        0,
        0,
        0,
        0,
        0,
        type_name_offset,
    )
    return header + resource + cbuffer + variable + type_record + bytes(strings)


def valid_signature_payload(name: str, *, register: int = 0) -> bytes:
    name_offset = 8 + 24
    return (
        struct.pack("<2I", 1, 0)
        + struct.pack("<5IBBH", name_offset, 0, 0, 3, register, 0xF, 0xF, 0)
        + name.encode("ascii")
        + b"\x00"
    )


def dxbc_reflection_program(
    *,
    creator: str,
    opcode_id: int,
    stat_marker: int,
    stage_code: int = 0,
    extra_instructions: int = 0,
) -> bytes:
    version_token = (stage_code << 16) | (5 << 4)
    instructions = [(1 << 24) | ((opcode_id + index) & 0x7FF) for index in range(1 + extra_instructions)]
    code_payload = struct.pack(f"<{2 + len(instructions)}I", version_token, 2 + len(instructions), *instructions)
    chunks = [
        (b"RDEF", valid_rdef_payload(creator=creator)),
        (b"ISGN", valid_signature_payload("TEXCOORD")),
        (b"OSGN", valid_signature_payload("SV_Target")),
        (b"SHDR", code_payload),
        (b"STAT", struct.pack("<37I", *([stat_marker] + [0] * 36))),
    ]
    header_size = 32 + 4 * len(chunks)
    offsets = []
    body = bytearray()
    current = header_size
    for fourcc, payload in chunks:
        offsets.append(current)
        encoded = fourcc + struct.pack("<I", len(payload)) + payload
        body.extend(encoded)
        current += len(encoded)
    total_size = header_size + len(body)
    return (
        b"DXBC"
        + bytes(16)
        + struct.pack("<3I", 1, total_size, len(chunks))
        + struct.pack(f"<{len(offsets)}I", *offsets)
        + bytes(body)
    )


def g1s_envelope(programs: list[bytes], *, magic: bytes = b"_S2G7000", prefix_size: int = 512) -> bytes:
    if len(magic) != 8 or prefix_size < 192 or not programs:
        raise ValueError("invalid synthetic G1S")
    prefix = bytearray(prefix_size)
    prefix[:8] = magic
    struct.pack_into("<I", prefix, 176, prefix_size)
    table_offset = prefix_size - 32
    struct.pack_into("<I", prefix, table_offset, len(programs[0]))
    struct.pack_into("<I", prefix, table_offset + 4, len(programs[0]))
    for index, program in enumerate(programs[1:], start=1):
        struct.pack_into("<I", prefix, table_offset + 4 + index * 4, len(program))
    payload = bytes(prefix) + b"".join(programs)
    mutable = bytearray(payload)
    struct.pack_into("<I", mutable, 8, len(mutable))
    return bytes(mutable)

def g1m_shader_payload(
    parameters: list[tuple[str, int, list[object]]],
    *,
    endian: str = "<",
) -> bytes:
    if endian == "<":
        file_magic = b"_M1G"
    elif endian == ">":
        file_magic = b"G1M_"
    else:
        raise ValueError(endian)
    parameter_payload = bytearray()
    for name, buffer_type, values in parameters:
        name_bytes = name.encode("utf-8") + b"\x00"
        raw_values = bytearray()
        for value in values:
            if buffer_type == 1:
                raw_values.extend(struct.pack(endian + "f", float(value)))
            elif buffer_type == 2:
                raw_values.extend(struct.pack(endian + "2f", *value))
            elif buffer_type == 3:
                raw_values.extend(struct.pack(endian + "3f", *value))
            elif buffer_type == 4:
                raw_values.extend(struct.pack(endian + "4f", *value))
            elif buffer_type == 5:
                raw_values.extend(struct.pack(endian + "i", int(value)))
            else:
                raise ValueError(buffer_type)
        parameter_size = 16 + len(name_bytes) + len(raw_values)
        parameter_payload.extend(
            struct.pack(
                endian + "3I2H",
                parameter_size,
                len(name_bytes),
                0,
                buffer_type,
                len(values),
            )
        )
        parameter_payload.extend(name_bytes)
        parameter_payload.extend(raw_values)
    shader_block = struct.pack(endian + "I", len(parameters)) + bytes(parameter_payload)
    section_size = 12 + len(shader_block)
    section = (
        struct.pack(
            endian + "3I",
            TOOL.G1MG_SHADER_PARAMS_SECTION,
            section_size,
            1,
        )
        + shader_block
    )
    g1mg_size = TOOL.G1MG_HEADER_SIZE + len(section)
    g1mg = (
        b"G1MG"
        + struct.pack(endian + "2I", 0x30303430, g1mg_size)
        + b"DX11"
        + struct.pack(endian + "I6f", 0, 0.0, 0.0, 0.0, 1.0, 1.0, 1.0)
        + struct.pack(endian + "I", 1)
        + section
    )
    total_size = TOOL.G1M_HEADER_SIZE + len(g1mg)
    return (
        file_magic
        + struct.pack(
            endian + "5I",
            0x30303430,
            total_size,
            TOOL.G1M_HEADER_SIZE,
            0,
            1,
        )
        + g1mg
    )


class RestorationToolTests(unittest.TestCase):
    def test_path_rule_is_case_insensitive(self) -> None:
        value, rule = TOOL.normalize_internal_path(
            "Event/B1/demo/test.ebm", [("event/b1/", "event/", "quartet_events")]
        )
        self.assertEqual(value, "event/demo/test.ebm")
        self.assertEqual(rule, "quartet_events")

    def test_identical_changed_removed_new_and_moved(self) -> None:
        source = inventory(
            "original",
            [
                entry("same/a.bin", b"same"),
                entry("changed/b.bin", b"before"),
                entry("gone/c.bin", b"gone"),
                entry("old/location/d.bin", b"moved"),
            ],
        )
        target = inventory(
            "quartet",
            [
                entry("same/a.bin", b"same", "B.PAK"),
                entry("changed/b.bin", b"after", "B.PAK"),
                entry("new/e.bin", b"new", "B.PAK"),
                entry("new/location/d.bin", b"moved", "B.PAK"),
            ],
            side="target",
        )
        report = TOOL.compare_inventories(source, target)
        counts = report["summary"]["classifications"]
        self.assertEqual(counts["identical"], 1)
        self.assertEqual(counts["changed"], 1)
        self.assertEqual(counts["removed_in_target"], 1)
        self.assertEqual(counts["new_in_target"], 1)
        self.assertEqual(counts["probably_moved"], 1)
        self.assertEqual(report["summary"]["censorship_candidates"], 0)

    def test_duplicate_normalized_paths_do_not_collapse(self) -> None:
        source = inventory(
            "original",
            [entry("dup.bin", b"one", "A1.PAK"), entry("dup.bin", b"two", "A2.PAK")],
        )
        target = inventory(
            "quartet",
            [entry("dup.bin", b"one", "B1.PAK"), entry("dup.bin", b"three", "B2.PAK")],
            side="target",
        )
        report = TOOL.compare_inventories(source, target)
        self.assertEqual(len(report["entries"]), 2)
        self.assertEqual(report["summary"]["classifications"]["identical"], 1)
        self.assertEqual(report["summary"]["classifications"]["changed"], 1)

    def test_event_profile_collapses_duplicate_locale_ebd(self) -> None:
        jp = entry("event/event_jp/demo/a.ebd", b"shared")
        en = entry("event/event_en/demo/a.ebd", b"shared")
        tc = entry("event/event_tc/demo/a.ebd", b"shared")
        source = inventory(
            "original", [jp, en, tc], pair="br1_events", side="source"
        )
        target = inventory(
            "quartet",
            [entry("event/event_jp/demo/a.ebd", b"shared", "B.PAK")],
            pair="br1_events",
            side="target",
        )
        report = TOOL.compare_inventories(source, target)
        self.assertEqual(report["summary"]["classifications"], {"identical": 1})
        profile = report["comparison_profiles"]["source"]
        self.assertEqual(profile["collapsed_source_locale_copies"], 2)

    def test_language_profile_uses_japanese_shared_copy(self) -> None:
        source = inventory(
            "original",
            [
                entry("saves_en/ui/a.xml", b"en"),
                entry("saves_ch/ui/a.xml", b"ch"),
                entry("saves_jp/ui/a.xml", b"jp"),
                entry("saves/text_en/a.xml", b"text-en"),
            ],
            pair="br1_language",
            side="source",
        )
        target = inventory(
            "quartet",
            [
                entry("saves_jp/ui/a.xml", b"jp", "B.PAK"),
                entry("saves/text_en/a.xml", b"text-en", "B.PAK"),
            ],
            pair="br1_language",
            side="target",
        )
        # The normalized shared source path would be saves/ui/a.xml in a real run.
        source["files"][2]["normalized_path"] = "saves/ui/a.xml"
        source["files"][2]["comparison_key"] = "saves/ui/a.xml"
        target["files"][0]["normalized_path"] = "saves/ui/a.xml"
        target["files"][0]["comparison_key"] = "saves/ui/a.xml"
        report = TOOL.compare_inventories(source, target)
        self.assertEqual(report["summary"]["classifications"], {"identical": 2})
        self.assertEqual(
            report["comparison_profiles"]["source"]["collapsed_source_locale_copies"],
            2,
        )

    def test_dlc_and_simplified_chinese_are_deferred(self) -> None:
        source = inventory(
            "original",
            [entry("data/character/pc00_dlc_test.g1t", b"old")],
        )
        target = inventory(
            "quartet",
            [
                entry("data/character/pc00_dlc_test.g1t", b"new", "B.PAK"),
                entry("event/event_sc/demo/a.ebm", b"sc", "B.PAK"),
            ],
            side="target",
        )
        report = TOOL.compare_inventories(source, target)
        scopes = {item["normalized_path"]: item["scope_status"] for item in report["entries"]}
        self.assertEqual(
            scopes["data/character/pc00_dlc_test.g1t"], "deferred_legacy_dlc"
        )
        self.assertEqual(scopes["event/event_sc/demo/a.ebm"], "expected_target_addition")

    def test_old_extraction_marker_reuses_data_across_tool_version(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            marker = root / TOOL.EXTRACTION_MARKER
            (root / "A.json").write_text("{}", encoding="utf-8")
            current = {
                "type": "br_restoration_extraction_marker",
                "format_version": 1,
                "tool_version": "0.0.2",
                "source_archive_relative": "DATA/A.PAK",
                "source_archive_size": 123,
                "source_archive_sha256": "a" * 64,
                "gust_pak_sha256": "b" * 64,
                "manifest_name": "A.json",
            }
            marker.write_text(json.dumps(current), encoding="utf-8")
            expected = {**current, "tool_version": TOOL.TOOL_VERSION}
            self.assertTrue(TOOL.marker_matches(marker, expected, "A.json"))


    def test_candidate_rules_group_quartet_only_asset_pairs(self) -> None:
        rules = [
            {
                "rule_id": "udw2",
                "status": "active",
                "normalized_path_glob": "data/x64/character/pc*/pc*_udw2.*",
                "family": "underwear_coverage_variant",
                "priority": "critical",
                "counterpart_templates": "{character}_udw,{character}_tng",
                "note": "test",
            }
        ]
        target_files = [
            entry("data/x64/character/pc00/pc00_udw2.g1t", b"texture", "B.PAK"),
            entry(
                "data/x64/character/pc00/pc00_udw2.elixir.gz",
                b"descriptor",
                "B.PAK",
            ),
            entry("data/x64/character/pc00/pc00_udw.g1t", b"old", "B.PAK"),
            entry("data/x64/character/pc00/pc00_tng.g1t", b"old2", "B.PAK"),
        ]
        target = inventory(
            "quartet", target_files, pair="br1_assets", side="target"
        )
        new_entries = []
        for target_entry in target_files[:2]:
            new_entries.append(
                {
                    "classification": "new_in_target",
                    "scope_status": "in_scope",
                    "normalized_path": target_entry["normalized_path"],
                    "target": TOOL.file_ref(target_entry),
                }
            )
        differences = [
            {
                "source_archive_group": "br1_assets",
                "entries": new_entries,
            }
        ]
        candidates = TOOL.build_candidate_families(
            differences=differences,
            target_inventories=[target],
            rules=rules,
        )
        self.assertEqual(len(candidates), 1)
        candidate = candidates[0]
        self.assertEqual(candidate["token"], "pc00_udw2")
        self.assertEqual(candidate["character_id"], "pc00")
        self.assertEqual(len(candidate["asset_files"]), 2)
        self.assertEqual(
            candidate["counterpart_tokens"], ["pc00_udw", "pc00_tng"]
        )
        self.assertEqual(len(candidate["counterpart_asset_paths"]), 2)

    def test_reference_evidence_scans_gust_zlib_ascii_and_utf16(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            workspace = project / ".local/build/quartet_restoration"
            reports = project / ".local/reports/quartet_restoration"
            inventories_dir = reports / "inventories"
            differences_dir = reports / "differences"
            mappings = (
                project
                / "titles/blue_reflection/modules/quartet_restoration/mappings"
            )
            inventories_dir.mkdir(parents=True)
            differences_dir.mkdir(parents=True)
            mappings.mkdir(parents=True)

            rules_file = mappings / "candidate_rules.tsv"
            rules_file.write_text(
                "rule_id\tstatus\tnormalized_path_glob\tfamily\tpriority\tcounterpart_templates\tnote\n"
                "udw2\tactive\tdata/x64/character/pc*/pc*_udw2.*\tunderwear_coverage_variant\tcritical\t{character}_udw\ttest\n",
                encoding="utf-8",
            )
            TOOL.atomic_json(
                reports / "SUMMARY.json",
                {
                    "type": "br_quartet_restoration_research_summary",
                    "format_version": 1,
                    "tool_version": "0.0.3",
                },
            )

            archive = "Data/PACK10_02.PAK"
            candidate_texture = entry(
                "data/x64/character/pc00/pc00_udw2.g1t", b"texture", archive
            )
            candidate_descriptor = entry(
                "data/x64/character/pc00/pc00_udw2.elixir.gz",
                b"placeholder",
                archive,
            )
            event_entry = entry(
                "event/b1/event_jp/test/event_test_010.ebd",
                b"placeholder",
                archive,
            )
            event_entry["normalized_path"] = "event/event_jp/test/event_test_010.ebd"
            event_entry["comparison_key"] = event_entry["normalized_path"].casefold()
            table_entry = entry("data/b1/table/test.bin", b"placeholder", archive)
            table_entry["normalized_path"] = "data/table/test.bin"
            table_entry["comparison_key"] = table_entry["normalized_path"].casefold()
            target_inventory = inventory(
                "quartet",
                [candidate_texture, candidate_descriptor, event_entry, table_entry],
                pair="br1_assets",
                side="target",
            )
            TOOL.atomic_json(
                inventories_dir / "br1_assets.target.json", target_inventory
            )
            TOOL.atomic_json(
                differences_dir / "br1_assets.json",
                {
                    "source_archive_group": "br1_assets",
                    "entries": [
                        {
                            "classification": "new_in_target",
                            "scope_status": "in_scope",
                            "normalized_path": candidate_texture["normalized_path"],
                            "target": TOOL.file_ref(candidate_texture),
                        },
                        {
                            "classification": "new_in_target",
                            "scope_status": "in_scope",
                            "normalized_path": candidate_descriptor["normalized_path"],
                            "target": TOOL.file_ref(candidate_descriptor),
                        },
                    ],
                },
            )

            archive_root = (
                workspace
                / "target/br1_assets"
                / TOOL.archive_workspace_name(archive)
            )
            descriptor_path = archive_root / candidate_descriptor["path"]
            descriptor_path.parent.mkdir(parents=True, exist_ok=True)
            descriptor_path.write_bytes(
                gust_chunked_zlib(
                    b"x" * 0x4000 + b"self pc00_udw2 descriptor",
                    chunk_size=0x4000,
                )
            )
            event_path = archive_root / event_entry["path"]
            event_path.parent.mkdir(parents=True, exist_ok=True)
            event_path.write_bytes(b"bind pc00_udw2 here")
            table_path = archive_root / table_entry["path"]
            table_path.parent.mkdir(parents=True, exist_ok=True)
            table_path.write_bytes("pc00_udw2".encode("utf-16le"))
            texture_path = archive_root / candidate_texture["path"]
            texture_path.parent.mkdir(parents=True, exist_ok=True)
            texture_path.write_bytes(b"texture")

            output, summary = TOOL.collect_reference_evidence(
                project_root=project,
                workspace_root=workspace,
                report_root=reports,
                candidate_rules_file=rules_file,
                maximum_scan_bytes=1024 * 1024,
            )
            self.assertTrue(output.is_file())
            self.assertEqual(summary["candidate_families"], 1)
            self.assertEqual(summary["event_reference_files"], 1)
            self.assertGreaterEqual(summary["external_reference_hit_rows"], 2)
            hits = TOOL.read_tsv(
                reports / TOOL.REFERENCE_EVIDENCE_DIR / "REFERENCE_HITS.tsv"
            )
            encodings = {row["encoding"] for row in hits if row["self_reference"] == "no"}
            self.assertIn("ascii", encodings)
            self.assertIn("utf16le", encodings)
            self.assertEqual(summary["decoded_gust_zlib_files"], 1)
            containers = TOOL.read_tsv(
                reports / TOOL.REFERENCE_EVIDENCE_DIR / "REFERENCE_SCAN_CONTAINERS.tsv"
            )
            by_name = {row["container"]: row for row in containers}
            self.assertEqual(by_name["gust_chunked_zlib"]["file_count"], "1")

    def test_reference_payload_decodes_standard_gzip(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "test.elixir.gz"
            with gzip.open(path, "wb") as handle:
                handle.write(b"standard gzip payload")
            payload, container = TOOL.read_reference_payload(path, 1024)
            self.assertEqual(payload, b"standard gzip payload")
            self.assertEqual(container, "gzip")

    def test_reference_payload_decodes_all_gust_chunks(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "test.elixir.gz"
            expected = b"a" * 0x4000 + b"candidate pc00_udw2 after first chunk"
            path.write_bytes(gust_chunked_zlib(expected))
            payload, container = TOOL.read_reference_payload(path, 1024 * 1024)
            self.assertEqual(payload, expected)
            self.assertEqual(container, "gust_chunked_zlib")
            self.assertIn(b"pc00_udw2", payload[0x4000:])

    def test_reference_payload_preserves_legacy_single_prefixed_zlib(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "legacy.elixir.gz"
            expected = b"candidate pc00_udw2 inside legacy container"
            path.write_bytes(b"\x03\x15\x00\x00" + zlib.compress(expected))
            payload, container = TOOL.read_reference_payload(path, 1024)
            self.assertEqual(payload, expected)
            self.assertEqual(container, "prefixed_zlib4")

    def test_reference_payload_rejects_missing_gust_terminator(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "truncated.elixir.gz"
            compressed = zlib.compress(b"one complete chunk")
            path.write_bytes(len(compressed).to_bytes(4, "little") + compressed)
            with self.assertRaisesRegex(
                TOOL.RestorationError, "truncated Gust chunk-size field"
            ):
                TOOL.read_reference_payload(path, 1024)

    def test_reference_payload_rejects_truncated_gust_chunk(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "truncated_chunk.elixir.gz"
            first = zlib.compress(b"first complete chunk")
            second = zlib.compress(b"second truncated chunk")
            path.write_bytes(
                len(first).to_bytes(4, "little")
                + first
                + (len(second) + 8).to_bytes(4, "little")
                + second
            )
            with self.assertRaisesRegex(
                TOOL.RestorationError, "truncated Gust chunk 2"
            ):
                TOOL.read_reference_payload(path, 1024)

    def test_reference_payload_enforces_decompressed_limit_across_gust_chunks(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "large.elixir.gz"
            path.write_bytes(gust_chunked_zlib(b"x" * 4096, chunk_size=64))
            with self.assertRaisesRegex(
                TOOL.RestorationError, "decompressed payload exceeds scan limit"
            ):
                TOOL.read_reference_payload(path, 128)

    def test_unrecognized_gz_is_reported_as_raw(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "unknown.elixir.gz"
            path.write_bytes(b"not a compressed container")
            payload, container = TOOL.read_reference_payload(path, 1024)
            self.assertEqual(payload, b"not a compressed container")
            self.assertEqual(container, "raw_unrecognized_gz")


    def test_streaming_reference_scan_crosses_chunk_boundary(self) -> None:
        patterns = TOOL.build_token_patterns(["pc00_udw2"])
        occurrences, size = TOOL.scan_token_stream(
            [b"prefix pc00_", b"udw2 suffix"], patterns
        )
        self.assertEqual(size, len(b"prefix pc00_udw2 suffix"))
        self.assertEqual(occurrences["ascii"]["pc00_udw2"][0], 1)
        self.assertEqual(occurrences["ascii"]["pc00_udw2"][1], [7])

    def test_streaming_gust_scan_ignores_legacy_decompressed_limit(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "large.elixir.gz"
            payload = b"x" * 4096 + b" pc00_udw2 "
            path.write_bytes(gust_chunked_zlib(payload, chunk_size=64))
            patterns = TOOL.build_token_patterns(["pc00_udw2"])
            occurrences, payload_bytes, container = TOOL.scan_reference_file(
                path, patterns, maximum_raw_bytes=128
            )
            self.assertEqual(container, "gust_chunked_zlib")
            self.assertEqual(payload_bytes, len(payload))
            self.assertEqual(occurrences["ascii"]["pc00_udw2"][0], 1)

    def test_effect_candidate_rules_are_path_driven(self) -> None:
        rules = [
            {
                "rule_id": "shower",
                "status": "active",
                "normalized_path_glob": "data/x64/field/s86_s_shower_room_01/*.elixir.gz",
                "domain": "steam_and_wet_clothing",
                "priority": "critical",
                "evidence_kind": "scene_container",
                "keywords": "steam,water,wet",
                "note": "test",
            }
        ]
        source_entry = entry(
            "data/x64/field/s86_s_shower_room_01/s86_s_shower_room_01.elixir.gz",
            b"old",
        )
        target_entry = entry(
            "data/x64/field/s86_s_shower_room_01/s86_s_shower_room_01.elixir.gz",
            b"new",
            "B.PAK",
        )
        candidates = TOOL.build_effect_material_candidates(
            [
                {
                    "source_archive_group": "br1_assets",
                    "entries": [
                        {
                            "classification": "changed",
                            "scope_status": "in_scope",
                            "normalized_path": source_entry["normalized_path"],
                            "source": TOOL.file_ref(source_entry),
                            "target": TOOL.file_ref(target_entry),
                            "binary_similarity": 0.1,
                            "size_ratio": 1.0,
                        }
                    ],
                }
            ],
            rules,
        )
        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0]["domain"], "steam_and_wet_clothing")
        self.assertEqual(candidates[0]["keywords"], ["steam", "water", "wet"])

    def test_scene_effect_evidence_reports_signatures_and_identifier_deltas(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            workspace = project / ".local/build/quartet_restoration"
            reports = project / ".local/reports/quartet_restoration"
            differences_dir = reports / "differences"
            mappings = project / "titles/blue_reflection/modules/quartet_restoration/mappings"
            differences_dir.mkdir(parents=True)
            mappings.mkdir(parents=True)
            TOOL.atomic_json(
                reports / "SUMMARY.json",
                {
                    "type": "br_quartet_restoration_research_summary",
                    "format_version": 1,
                    "tool_version": "0.0.3",
                },
            )
            rules_file = mappings / "effect_material_rules.tsv"
            rules_file.write_text(
                "rule_id\tstatus\tnormalized_path_glob\tdomain\tpriority\tevidence_kind\tkeywords\tnote\n"
                "water\tactive\tdata/x64/shader/cwater.g1s\twater_visibility\tcritical\tshader\twater,alpha,reflect\ttest\n",
                encoding="utf-8",
            )
            source_entry = entry("data/x64/shader/cwater.g1s", b"old", "DATA/PACK00_02.PAK")
            target_entry = entry("data/x64/shader/cwater.g1s", b"new", "Data/PACK10_02.PAK")
            TOOL.atomic_json(
                differences_dir / "br1_assets.json",
                {
                    "source_archive_group": "br1_assets",
                    "entries": [
                        {
                            "classification": "changed",
                            "scope_status": "in_scope",
                            "normalized_path": "data/x64/shader/cwater.g1s",
                            "source": TOOL.file_ref(source_entry),
                            "target": TOOL.file_ref(target_entry),
                            "binary_similarity": 0.0,
                            "size_ratio": 1.0,
                        }
                    ],
                },
            )
            source_path = TOOL.inventory_workspace_file(
                workspace,
                "source",
                "br1_assets",
                source_entry["archive"],
                source_entry["path"],
            )
            target_path = TOOL.inventory_workspace_file(
                workspace,
                "target",
                "br1_assets",
                target_entry["archive"],
                target_entry["path"],
            )
            source_path.parent.mkdir(parents=True, exist_ok=True)
            target_path.parent.mkdir(parents=True, exist_ok=True)
            source_path.write_bytes(b"water_alpha water_reflect")
            target_path.write_bytes(b"water_alpha water_reflect water_reflect")

            output, summary = TOOL.collect_scene_effect_evidence(
                project_root=project,
                workspace_root=workspace,
                report_root=reports,
                rules_file=rules_file,
                maximum_raw_bytes=1024,
            )
            self.assertTrue(output.is_file())
            self.assertEqual(summary["candidate_files"], 1)
            self.assertEqual(summary["technical_token_differences"], 1)
            token_rows = TOOL.read_tsv(
                reports / TOOL.SCENE_EFFECT_EVIDENCE_DIR / "TECHNICAL_TOKEN_DIFF.tsv"
            )
            self.assertEqual(token_rows[0]["token"], "water_reflect")
            self.assertEqual(token_rows[0]["delta"], "count_changed")
            signature_rows = TOOL.read_tsv(
                reports
                / TOOL.SCENE_EFFECT_EVIDENCE_DIR
                / "DECOMPRESSED_PAIR_SIGNATURES.tsv"
            )
            self.assertEqual(signature_rows[0]["changed_aligned_blocks"], "1")


    def test_parse_earc_payload_reports_member_metadata(self) -> None:
        payload = earc_archive(
            [("PC00_Rfl_W.g1m", b"model"), ("PC00_Rfl_WOid.bin", b"oid")]
        )
        parsed = TOOL.parse_earc_payload(payload, include_member_payloads=True)
        self.assertEqual(parsed["file_count"], 2)
        self.assertEqual(parsed["members"][0]["name"], "PC00_Rfl_W.g1m")
        self.assertEqual(parsed["members"][0]["payload"], b"model")
        self.assertEqual(parsed["members"][1]["size"], 3)

    def test_compare_earc_members_is_member_level(self) -> None:
        source = TOOL.parse_earc_payload(
            earc_archive([("same.bin", b"same"), ("change.bin", b"old"), ("gone.bin", b"gone")])
        )
        target = TOOL.parse_earc_payload(
            earc_archive([("same.bin", b"same"), ("change.bin", b"new"), ("added.bin", b"added")])
        )
        rows, counts = TOOL.compare_earc_members(source, target, keywords=["change"])
        self.assertEqual(counts["identical"], 1)
        self.assertEqual(counts["changed"], 1)
        self.assertEqual(counts["removed_in_target"], 1)
        self.assertEqual(counts["added_in_target"], 1)
        changed = next(row for row in rows if row["classification"] == "changed")
        self.assertEqual(changed["target_member_name"], "change.bin")
        self.assertEqual(changed["keyword_hits"], "change")

    def test_derived_identifiers_preserve_actual_case(self) -> None:
        parsed = TOOL.parse_earc_payload(
            earc_archive(
                [
                    (
                        "PC00_Rfl_W.g1m",
                        b"ObjectID:PC00_Rfl_W fTranslucency PC00_Rfl_W_default.g1m",
                    )
                ]
            ),
            include_member_payloads=True,
        )
        rows = TOOL.derive_candidate_identifiers(
            parsed,
            candidate_id="restcand_test",
            family="wet_reflector_variant",
            priority="high",
            token="pc00_rfl_w",
            normalized_path="data/x64/character/pc00/pc00_rfl_w.elixir.gz",
        )
        identifiers = {row["identifier"] for row in rows}
        self.assertIn("PC00_Rfl_W.g1m", identifiers)
        self.assertIn("ObjectID:PC00_Rfl_W", identifiers)
        self.assertIn("PC00_Rfl_W_default.g1m", identifiers)

    def test_variant_member_comparison_normalizes_variant_token(self) -> None:
        candidate = TOOL.parse_earc_payload(
            earc_archive([("PC00_Rfl_W.g1m", b"wet"), ("common.bin", b"same")])
        )
        counterpart = TOOL.parse_earc_payload(
            earc_archive([("PC00_Rfl.g1m", b"dry"), ("common.bin", b"same")])
        )
        rows, counts = TOOL.compare_variant_members(
            candidate,
            counterpart,
            candidate_token="pc00_rfl_w",
            counterpart_token="pc00_rfl",
        )
        self.assertEqual(counts["changed_payload"], 1)
        self.assertEqual(counts["identical_payload"], 1)
        changed = next(row for row in rows if row["classification"] == "changed_payload")
        self.assertEqual(changed["candidate_member_name"], "PC00_Rfl_W.g1m")
        self.assertEqual(changed["counterpart_member_name"], "PC00_Rfl.g1m")


    def test_parse_g1m_material_parameters_reads_numeric_values(self) -> None:
        payload = g1m_shader_payload(
            [
                ("fTranslucency", 1, [0.25]),
                ("fRrTransparency", 4, [(0.1, 0.2, 0.3, 0.4)]),
                ("iWetMode", 5, [2]),
            ]
        )
        parsed = TOOL.parse_g1m_material_parameters(payload, label="synthetic.g1m")
        self.assertEqual(parsed["endian"], "little")
        self.assertEqual(parsed["chunk_count"], 1)
        rows = {row["parameter_name"]: row for row in parsed["parameters"]}
        self.assertEqual(rows["fTranslucency"]["value_text"], "0.25")
        self.assertEqual(rows["fRrTransparency"]["value_text"], "0.100000001,0.200000003,0.300000012,0.400000006")
        self.assertEqual(rows["iWetMode"]["value_text"], "2")
        self.assertEqual(rows["fTranslucency"]["keyword_hits"], "trans,translucency")
        self.assertEqual(rows["fRrTransparency"]["keyword_hits"], "trans,transparency")
        self.assertEqual(rows["iWetMode"]["keyword_hits"], "wet")

    def test_compare_g1m_material_parameters_reports_changed_added_removed(self) -> None:
        source = TOOL.parse_g1m_material_parameters(
            g1m_shader_payload(
                [
                    ("fTranslucency", 1, [0.75]),
                    ("fWaterAlpha", 1, [0.9]),
                ]
            )
        )
        target = TOOL.parse_g1m_material_parameters(
            g1m_shader_payload(
                [
                    ("fTranslucency", 1, [0.25]),
                    ("fSteamDensity", 1, [1.5]),
                ]
            )
        )
        rows, counts = TOOL.compare_g1m_material_parameters(source, target)
        self.assertEqual(counts["changed"], 1)
        self.assertEqual(counts["removed_in_target"], 1)
        self.assertEqual(counts["added_in_target"], 1)
        by_name = {row["parameter_name"]: row for row in rows}
        self.assertEqual(by_name["fTranslucency"]["source_value_text"], "0.75")
        self.assertEqual(by_name["fTranslucency"]["target_value_text"], "0.25")
        self.assertEqual(by_name["fWaterAlpha"]["classification"], "removed_in_target")
        self.assertEqual(by_name["fSteamDensity"]["classification"], "added_in_target")

    def test_material_parameter_evidence_compares_scene_g1m_members(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            workspace = project / ".local/build/quartet_restoration"
            reports = project / ".local/reports/quartet_restoration"
            inventories_dir = reports / "inventories"
            differences_dir = reports / "differences"
            mappings = project / "titles/blue_reflection/modules/quartet_restoration/mappings"
            inventories_dir.mkdir(parents=True)
            differences_dir.mkdir(parents=True)
            mappings.mkdir(parents=True)
            TOOL.atomic_json(
                reports / "SUMMARY.json",
                {
                    "type": "br_quartet_restoration_research_summary",
                    "format_version": 1,
                    "tool_version": "0.0.8",
                },
            )
            candidate_rules = mappings / "candidate_rules.tsv"
            candidate_rules.write_text(
                "rule_id\tstatus\tnormalized_path_glob\tfamily\tpriority\tcounterpart_templates\tnote\n"
                "dummy\tactive\tdata/x64/character/never/*.elixir.gz\tunused\tlow\t{character}_none\ttest-only non-match\n",
                encoding="utf-8",
            )
            effect_rules = mappings / "effect_material_rules.tsv"
            effect_rules.write_text(
                "rule_id\tstatus\tnormalized_path_glob\tdomain\tpriority\tevidence_kind\tkeywords\tnote\n"
                "pool\tactive\tdata/x64/field/pool/pool.elixir.gz\twater_visibility\tcritical\tscene_container\twater,alpha,transparency\ttest\n",
                encoding="utf-8",
            )
            source_entry = entry(
                "data/x64/field/pool/pool.elixir.gz",
                b"old",
                "DATA/PACK00_02.PAK",
            )
            target_entry = entry(
                "data/x64/field/pool/pool.elixir.gz",
                b"new",
                "Data/PACK10_02.PAK",
            )
            source_inventory = inventory(
                "original", [source_entry], pair="br1_assets", side="source"
            )
            target_inventory = inventory(
                "quartet", [target_entry], pair="br1_assets", side="target"
            )
            TOOL.atomic_json(inventories_dir / "br1_assets.source.json", source_inventory)
            TOOL.atomic_json(inventories_dir / "br1_assets.target.json", target_inventory)
            TOOL.atomic_json(
                differences_dir / "br1_assets.json",
                {
                    "source_archive_group": "br1_assets",
                    "entries": [
                        {
                            "classification": "changed",
                            "scope_status": "in_scope",
                            "normalized_path": source_entry["normalized_path"],
                            "source": TOOL.file_ref(source_entry),
                            "target": TOOL.file_ref(target_entry),
                            "binary_similarity": 0.1,
                            "size_ratio": 1.0,
                        }
                    ],
                },
            )
            source_g1m = g1m_shader_payload(
                [("fWaterAlpha", 1, [0.8]), ("fSteamDensity", 1, [0.5])]
            )
            target_g1m = g1m_shader_payload(
                [("fWaterAlpha", 1, [0.35]), ("fSteamDensity", 1, [1.25])]
            )
            source_path = TOOL.inventory_workspace_file(
                workspace, "source", "br1_assets", source_entry["archive"], source_entry["path"]
            )
            target_path = TOOL.inventory_workspace_file(
                workspace, "target", "br1_assets", target_entry["archive"], target_entry["path"]
            )
            source_path.parent.mkdir(parents=True, exist_ok=True)
            target_path.parent.mkdir(parents=True, exist_ok=True)
            source_path.write_bytes(gust_chunked_zlib(earc_archive([("PoolWater.g1m", source_g1m)])))
            target_path.write_bytes(gust_chunked_zlib(earc_archive([("PoolWater.g1m", target_g1m)])))

            output, summary = TOOL.collect_material_parameter_evidence(
                project_root=project,
                workspace_root=workspace,
                report_root=reports,
                candidate_rules_file=candidate_rules,
                effect_rules_file=effect_rules,
                maximum_earc_bytes=1024 * 1024,
            )
            self.assertTrue(output.is_file())
            self.assertEqual(summary["parsed_g1m_payloads"], 2)
            self.assertEqual(summary["g1m_shader_parameter_differences"], 2)
            self.assertEqual(summary["technical_parameter_differences"], 2)
            rows = TOOL.read_tsv(
                reports
                / TOOL.MATERIAL_PARAMETER_EVIDENCE_DIR
                / "G1M_SHADER_PARAMETER_DIFF.tsv"
            )
            by_name = {row["parameter_name"]: row for row in rows}
            self.assertEqual(by_name["fWaterAlpha"]["source_value_text"], "0.800000012")
            self.assertEqual(by_name["fWaterAlpha"]["target_value_text"], "0.349999994")
            self.assertEqual(by_name["fSteamDensity"]["classification"], "changed")


    def test_semantic_parameter_comparison_ignores_shader_block_relocation(self) -> None:
        source = {
            "parameters": [
                {
                    "parameter_name": "fTranslucency",
                    "shader_block_index": 0,
                    "parameter_index": 0,
                    "buffer_type": 1,
                    "buffer_count": 1,
                    "value_text": "0.5",
                    "value_hex": "0000003f",
                    "keyword_hits": "trans,translucency",
                },
                {
                    "parameter_name": "parameterForMeshBlend",
                    "shader_block_index": 0,
                    "parameter_index": 1,
                    "buffer_type": 4,
                    "buffer_count": 1,
                    "value_text": "1,1,1,1",
                    "value_hex": "0000803f0000803f0000803f0000803f",
                    "keyword_hits": "blend",
                },
            ]
        }
        target = {
            "parameters": [
                {
                    "parameter_name": "parameterForMeshBlend",
                    "shader_block_index": 7,
                    "parameter_index": 3,
                    "buffer_type": 4,
                    "buffer_count": 1,
                    "value_text": "1,1,1,1",
                    "value_hex": "0000803f0000803f0000803f0000803f",
                    "keyword_hits": "blend",
                },
                {
                    "parameter_name": "fTranslucency",
                    "shader_block_index": 9,
                    "parameter_index": 2,
                    "buffer_type": 1,
                    "buffer_count": 1,
                    "value_text": "0.829999983",
                    "value_hex": "e17a543f",
                    "keyword_hits": "trans,translucency",
                },
            ]
        }
        rows, counts = TOOL.compare_g1m_material_parameters_semantic(source, target)
        self.assertEqual(counts["identical_relocated"], 1)
        self.assertEqual(counts["changed"], 1)
        self.assertNotIn("added_in_target", counts)
        self.assertNotIn("removed_in_target", counts)
        self.assertEqual(rows[0]["parameter_name"], "fTranslucency")
        self.assertEqual(rows[0]["source_value_text"], "0.5")
        self.assertEqual(rows[0]["target_value_text"], "0.829999983")

    def test_three_way_parameter_classifies_variant_specific_change(self) -> None:
        original = TOOL.parse_g1m_material_parameters(
            g1m_shader_payload([("fTranslucency", 1, [0.5])])
        )
        quartet_base = TOOL.parse_g1m_material_parameters(
            g1m_shader_payload([("fTranslucency", 1, [0.5])])
        )
        quartet_variant = TOOL.parse_g1m_material_parameters(
            g1m_shader_payload([("fTranslucency", 1, [0.83])])
        )
        rows = TOOL.compare_three_way_parameter_multisets(
            original, quartet_base, quartet_variant
        )
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["classification"], "variant_specific_change")
        self.assertEqual(rows[0]["original_base_values"], "0.5")
        self.assertEqual(rows[0]["quartet_variant_values"], "0.829999983")

    def test_material_delta_evidence_builds_three_way_variant_report(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            workspace = project / ".local/build/quartet_restoration"
            reports = project / ".local/reports/quartet_restoration"
            inventories_dir = reports / "inventories"
            differences_dir = reports / "differences"
            material_dir = reports / TOOL.MATERIAL_PARAMETER_EVIDENCE_DIR
            mappings = project / "titles/blue_reflection/modules/quartet_restoration/mappings"
            inventories_dir.mkdir(parents=True)
            differences_dir.mkdir(parents=True)
            material_dir.mkdir(parents=True)
            mappings.mkdir(parents=True)
            TOOL.atomic_json(
                reports / "SUMMARY.json",
                {
                    "type": "br_quartet_restoration_research_summary",
                    "format_version": 1,
                    "tool_version": "0.0.9",
                },
            )
            TOOL.atomic_json(
                material_dir / "SUMMARY.json",
                {
                    "type": "br_quartet_restoration_material_parameter_evidence_summary",
                    "format_version": 1,
                    "tool_version": "0.0.9",
                },
            )
            candidate_rules = mappings / "candidate_rules.tsv"
            candidate_rules.write_text(
                "rule_id\tstatus\tnormalized_path_glob\tfamily\tpriority\tcounterpart_templates\tnote\n"
                "wet\tactive\tdata/x64/character/pc*/pc*_rfl_w.*\twet_reflector_variant\tcritical\t{character}_rfl\ttest\n",
                encoding="utf-8",
            )
            effect_rules = mappings / "effect_material_rules.tsv"
            effect_rules.write_text(
                "rule_id\tstatus\tnormalized_path_glob\tdomain\tpriority\tevidence_kind\tkeywords\tnote\n"
                "none\tactive\tdata/x64/field/never/*.elixir.gz\tunused\tlow\tscene_container\twater\ttest\n",
                encoding="utf-8",
            )
            base_path = "data/x64/character/pc00/pc00_rfl.elixir.gz"
            variant_path = "data/x64/character/pc00/pc00_rfl_w.elixir.gz"
            source_base = entry(base_path, b"source-base", "DATA/PACK00_02.PAK")
            target_base = entry(base_path, b"target-base", "Data/PACK10_02.PAK")
            target_variant = entry(variant_path, b"target-variant", "Data/PACK10_02.PAK")
            TOOL.atomic_json(
                inventories_dir / "br1_assets.source.json",
                inventory("original", [source_base], pair="br1_assets", side="source"),
            )
            TOOL.atomic_json(
                inventories_dir / "br1_assets.target.json",
                inventory(
                    "quartet", [target_base, target_variant],
                    pair="br1_assets", side="target",
                ),
            )
            TOOL.atomic_json(
                differences_dir / "br1_assets.json",
                {
                    "source_archive_group": "br1_assets",
                    "entries": [
                        {
                            "classification": "new_in_target",
                            "scope_status": "in_scope",
                            "normalized_path": variant_path,
                            "source": None,
                            "target": TOOL.file_ref(target_variant),
                        }
                    ],
                },
            )
            source_payload = g1m_shader_payload([("fTranslucency", 1, [0.5])])
            target_base_payload = g1m_shader_payload([("fTranslucency", 1, [0.5])])
            target_variant_payload = g1m_shader_payload([("fTranslucency", 1, [0.83])])
            for side, ref, member_name, payload in (
                ("source", source_base, "PC00_Rfl_default.g1m", source_payload),
                ("target", target_base, "PC00_Rfl_default.g1m", target_base_payload),
                ("target", target_variant, "PC00_Rfl_W_default.g1m", target_variant_payload),
            ):
                path = TOOL.inventory_workspace_file(
                    workspace, side, "br1_assets", ref["archive"], ref["path"]
                )
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(
                    gust_chunked_zlib(earc_archive([(member_name, payload)]))
                )

            output, summary = TOOL.collect_material_delta_evidence(
                project_root=project,
                workspace_root=workspace,
                report_root=reports,
                candidate_rules_file=candidate_rules,
                effect_rules_file=effect_rules,
                maximum_earc_bytes=1024 * 1024,
            )
            self.assertTrue(output.is_file())
            self.assertGreaterEqual(summary["three_way_variant_rows"], 1)
            rows = TOOL.read_tsv(
                reports
                / TOOL.MATERIAL_DELTA_EVIDENCE_DIR
                / "THREE_WAY_VARIANT_PARAMETERS.tsv"
            )
            translucency = [row for row in rows if row["parameter_name"] == "fTranslucency"]
            self.assertEqual(len(translucency), 1)
            self.assertEqual(translucency[0]["classification"], "variant_specific_change")
            self.assertEqual(translucency[0]["quartet_variant_values"], "0.829999983")


    def test_parse_embedded_dxbc_program_reports_stage_and_resources(self) -> None:
        payload = b"prefix" + dxbc_program(stage_code=0, resource_token="g_WaterAlpha") + b"suffix"
        programs = TOOL.find_dxbc_programs(payload, label="synthetic.g1s")
        self.assertEqual(len(programs), 1)
        self.assertEqual(programs[0]["stage"], "pixel")
        self.assertEqual(programs[0]["shader_model"], "5_0")
        self.assertIn("RDEF", programs[0]["chunk_fourccs"])
        self.assertIn("g_WaterAlpha", programs[0]["resource_tokens"])

    def test_compare_dxbc_programs_pairs_same_stage_and_chunk_layout(self) -> None:
        source = TOOL.find_dxbc_programs(
            dxbc_program(resource_token="g_WaterAlpha", instruction_marker=1)
        )
        target = TOOL.find_dxbc_programs(
            dxbc_program(resource_token="g_WaterOpacity", instruction_marker=2)
        )
        rows = TOOL.compare_dxbc_programs(source, target)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["classification"], "changed_same_stage_and_chunk_layout")
        self.assertEqual(rows[0]["source_stage"], "pixel")

    def test_shader_effect_evidence_handles_direct_g1s_pair(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            workspace = project / ".local/build/quartet_restoration"
            reports = project / ".local/reports/quartet_restoration"
            differences_dir = reports / "differences"
            mappings = project / "titles/blue_reflection/modules/quartet_restoration/mappings"
            differences_dir.mkdir(parents=True)
            mappings.mkdir(parents=True)
            material_dir = reports / TOOL.MATERIAL_DELTA_EVIDENCE_DIR
            material_dir.mkdir(parents=True)
            TOOL.atomic_json(
                material_dir / "SUMMARY.json",
                {
                    "type": "br_quartet_restoration_material_delta_evidence_summary",
                    "format_version": 1,
                    "tool_version": "0.0.10",
                },
            )
            rules = mappings / "effect_material_rules.tsv"
            rules.write_text(
                "rule_id\tstatus\tnormalized_path_glob\tdomain\tpriority\tevidence_kind\tkeywords\tnote\n"
                "water\tactive\tdata/x64/shader/cwater.g1s\twater_visibility\tcritical\tshader\twater,alpha,trans,opacity,refract\ttest\n",
                encoding="utf-8",
            )
            source_entry = entry(
                "data/x64/shader/cwater.g1s",
                b"old",
                "DATA/PACK00_02.PAK",
            )
            target_entry = entry(
                "data/x64/shader/cwater.g1s",
                b"new",
                "Data/PACK10_02.PAK",
            )
            TOOL.atomic_json(
                differences_dir / "br1_assets.json",
                {
                    "source_archive_group": "br1_assets",
                    "entries": [
                        {
                            "classification": "changed",
                            "scope_status": "in_scope",
                            "normalized_path": "data/x64/shader/cwater.g1s",
                            "source": TOOL.file_ref(source_entry),
                            "target": TOOL.file_ref(target_entry),
                            "binary_similarity": 0.0,
                            "size_ratio": 1.0,
                        }
                    ],
                },
            )
            source_path = TOOL.inventory_workspace_file(
                workspace, "source", "br1_assets", source_entry["archive"], source_entry["path"]
            )
            target_path = TOOL.inventory_workspace_file(
                workspace, "target", "br1_assets", target_entry["archive"], target_entry["path"]
            )
            source_path.parent.mkdir(parents=True, exist_ok=True)
            target_path.parent.mkdir(parents=True, exist_ok=True)
            source_path.write_bytes(
                b"water_alpha\x00" + dxbc_program(resource_token="g_WaterAlpha", instruction_marker=1)
            )
            target_path.write_bytes(
                b"water_opacity\x00steam_density\x00"
                + dxbc_program(resource_token="g_WaterOpacity", instruction_marker=2)
            )

            output, summary = TOOL.collect_shader_effect_evidence(
                project_root=project,
                workspace_root=workspace,
                report_root=reports,
                rules_file=rules,
                maximum_earc_bytes=1024 * 1024,
                maximum_payload_bytes=1024 * 1024,
            )
            self.assertTrue(output.is_file())
            self.assertEqual(summary["render_payload_rows"], 2)
            self.assertEqual(summary["embedded_dxbc_program_rows"], 2)
            self.assertEqual(summary["dxbc_program_difference_rows"], 1)
            self.assertGreaterEqual(summary["technical_token_difference_rows"], 2)
            dxbc_rows = TOOL.read_tsv(
                reports / TOOL.SHADER_EFFECT_EVIDENCE_DIR / "DXBC_PROGRAM_DIFF.tsv"
            )
            self.assertEqual(dxbc_rows[0]["classification"], "changed_same_stage_and_chunk_layout")
            token_rows = TOOL.read_tsv(
                reports / TOOL.SHADER_EFFECT_EVIDENCE_DIR / "RENDER_TECHNICAL_TOKEN_DIFF.tsv"
            )
            tokens = {row["token_key"] for row in token_rows}
            self.assertIn("water_alpha", tokens)
            self.assertIn("steam_density", tokens)


    def test_shader_effect_evidence_reads_changed_g1e_member_from_elixir(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            workspace = project / ".local/build/quartet_restoration"
            reports = project / ".local/reports/quartet_restoration"
            differences_dir = reports / "differences"
            mappings = project / "titles/blue_reflection/modules/quartet_restoration/mappings"
            differences_dir.mkdir(parents=True)
            mappings.mkdir(parents=True)
            material_dir = reports / TOOL.MATERIAL_DELTA_EVIDENCE_DIR
            material_dir.mkdir(parents=True)
            TOOL.atomic_json(
                material_dir / "SUMMARY.json",
                {
                    "type": "br_quartet_restoration_material_delta_evidence_summary",
                    "format_version": 1,
                    "tool_version": "0.0.10",
                },
            )
            rules = mappings / "effect_material_rules.tsv"
            rules.write_text(
                "rule_id\tstatus\tnormalized_path_glob\tdomain\tpriority\tevidence_kind\tkeywords\tnote\n"
                "shower\tactive\tdata/x64/effect/100_common.elixir.gz\tsteam_and_wet_clothing\thigh\tcommon_effect_container\tsteam,water,wet,alpha\ttest\n",
                encoding="utf-8",
            )
            normalized = "data/x64/effect/100_common.elixir.gz"
            source_entry = entry(normalized, b"old", "DATA/PACK00_02.PAK")
            target_entry = entry(normalized, b"new", "Data/PACK10_02.PAK")
            TOOL.atomic_json(
                differences_dir / "br1_assets.json",
                {
                    "source_archive_group": "br1_assets",
                    "entries": [
                        {
                            "classification": "changed",
                            "scope_status": "in_scope",
                            "normalized_path": normalized,
                            "source": TOOL.file_ref(source_entry),
                            "target": TOOL.file_ref(target_entry),
                            "binary_similarity": 0.0,
                            "size_ratio": 1.0,
                        }
                    ],
                },
            )
            source_path = TOOL.inventory_workspace_file(
                workspace, "source", "br1_assets", source_entry["archive"], source_entry["path"]
            )
            target_path = TOOL.inventory_workspace_file(
                workspace, "target", "br1_assets", target_entry["archive"], target_entry["path"]
            )
            source_path.parent.mkdir(parents=True, exist_ok=True)
            target_path.parent.mkdir(parents=True, exist_ok=True)
            source_path.write_bytes(
                gust_chunked_zlib(earc_archive([("steam.g1e", b"steam_alpha\x00")]))
            )
            target_path.write_bytes(
                gust_chunked_zlib(earc_archive([("steam.g1e", b"steam_alpha\x00water_opacity\x00")]))
            )

            _output, summary = TOOL.collect_shader_effect_evidence(
                project_root=project,
                workspace_root=workspace,
                report_root=reports,
                rules_file=rules,
                maximum_earc_bytes=1024 * 1024,
                maximum_payload_bytes=1024 * 1024,
            )
            self.assertEqual(summary["render_payload_rows"], 2)
            self.assertEqual(summary["render_pair_classifications"]["changed"], 1)
            rows = TOOL.read_tsv(
                reports / TOOL.SHADER_EFFECT_EVIDENCE_DIR / "RENDER_TECHNICAL_TOKEN_DIFF.tsv"
            )
            self.assertIn("water_opacity", {row["token_key"] for row in rows})


    def test_compare_dxbc_chunks_identifies_code_only_delta(self) -> None:
        source_payload = dxbc_program(resource_token="g_WaterAlpha", instruction_marker=1)
        target_payload = dxbc_program(resource_token="g_WaterAlpha", instruction_marker=2)
        source_program = TOOL.find_dxbc_programs(source_payload)[0]
        target_program = TOOL.find_dxbc_programs(target_payload)[0]
        chunks, summary, instructions = TOOL.compare_dxbc_chunks(
            source_payload, target_payload, source_program, target_program
        )
        by_fourcc = {row["fourcc"]: row for row in chunks}
        self.assertEqual(by_fourcc["RDEF"]["classification"], "identical")
        self.assertEqual(by_fourcc["SHDR"]["classification"], "changed")
        self.assertEqual(
            summary["program_structure_classification"],
            "code_delta_with_stable_resources_and_signatures",
        )
        self.assertEqual(len(instructions), 1)

    def test_payload_binary_delta_records_small_aligned_change(self) -> None:
        source = b"A" * 32 + struct.pack("<f", 0.25) + b"Z" * 32
        target = b"A" * 32 + struct.pack("<f", 0.75) + b"Z" * 32
        row = TOOL.analyze_payload_binary_delta(source, target, extension=".bin")
        self.assertEqual(row["classification"], "changed")
        self.assertEqual(row["size_delta"], 0)
        self.assertGreaterEqual(row["common_prefix_bytes"], 32)
        self.assertIn("0x20:0.25->0.75", row["undecoded_float_delta_candidates"])

    def test_binary_delta_evidence_selects_direct_shader_prototype(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            workspace = project / ".local/build/quartet_restoration"
            reports = project / ".local/reports/quartet_restoration"
            differences_dir = reports / "differences"
            mappings = project / "titles/blue_reflection/modules/quartet_restoration/mappings"
            differences_dir.mkdir(parents=True)
            mappings.mkdir(parents=True)
            shader_dir = reports / TOOL.SHADER_EFFECT_EVIDENCE_DIR
            shader_dir.mkdir(parents=True)
            TOOL.atomic_json(
                shader_dir / "SUMMARY.json",
                {
                    "type": "br_quartet_restoration_shader_effect_evidence_summary",
                    "format_version": 1,
                    "tool_version": "0.0.11",
                },
            )
            rules = mappings / "effect_material_rules.tsv"
            rules.write_text(
                "rule_id\tstatus\tnormalized_path_glob\tdomain\tpriority\tevidence_kind\tkeywords\tnote\n"
                "water\tactive\tdata/x64/shader/cwater.g1s\twater_visibility\tcritical\tshader\twater,alpha,trans,opacity,refract\ttest\n",
                encoding="utf-8",
            )
            source_entry = entry("data/x64/shader/cwater.g1s", b"old", "DATA/PACK00_02.PAK")
            target_entry = entry("data/x64/shader/cwater.g1s", b"new", "Data/PACK10_02.PAK")
            TOOL.atomic_json(
                differences_dir / "br1_assets.json",
                {
                    "source_archive_group": "br1_assets",
                    "entries": [
                        {
                            "classification": "changed",
                            "scope_status": "in_scope",
                            "normalized_path": "data/x64/shader/cwater.g1s",
                            "source": TOOL.file_ref(source_entry),
                            "target": TOOL.file_ref(target_entry),
                            "binary_similarity": 0.0,
                            "size_ratio": 1.0,
                        }
                    ],
                },
            )
            source_path = TOOL.inventory_workspace_file(
                workspace, "source", "br1_assets", source_entry["archive"], source_entry["path"]
            )
            target_path = TOOL.inventory_workspace_file(
                workspace, "target", "br1_assets", target_entry["archive"], target_entry["path"]
            )
            source_path.parent.mkdir(parents=True, exist_ok=True)
            target_path.parent.mkdir(parents=True, exist_ok=True)
            source_path.write_bytes(dxbc_program(resource_token="g_WaterAlpha", instruction_marker=1))
            target_path.write_bytes(dxbc_program(resource_token="g_WaterAlpha", instruction_marker=2))

            output, summary = TOOL.collect_binary_delta_evidence(
                project_root=project,
                workspace_root=workspace,
                report_root=reports,
                rules_file=rules,
                maximum_earc_bytes=1024 * 1024,
                maximum_payload_bytes=1024 * 1024,
            )
            self.assertTrue(output.is_file())
            self.assertEqual(summary["focused_payload_pairs"], 1)
            self.assertEqual(summary["prototype_candidate_rows"], 1)
            programs = TOOL.read_tsv(
                reports / TOOL.BINARY_DELTA_EVIDENCE_DIR / "DXBC_PROGRAM_STRUCTURE.tsv"
            )
            self.assertEqual(
                programs[0]["program_structure_classification"],
                "code_delta_with_stable_resources_and_signatures",
            )
            prototypes = TOOL.read_tsv(
                reports / TOOL.BINARY_DELTA_EVIDENCE_DIR / "RESTORATION_PROTOTYPE_CANDIDATES.tsv"
            )
            self.assertEqual(
                prototypes[0]["prototype_action"],
                "controlled_original_direct_shader_override_test",
            )


    def test_rdef_semantic_hash_ignores_creator_string(self) -> None:
        source = TOOL.parse_dxbc_rdef(valid_rdef_payload(creator="Compiler A"))
        target = TOOL.parse_dxbc_rdef(valid_rdef_payload(creator="Compiler B"))
        self.assertEqual(source["status"], "ok")
        self.assertEqual(target["status"], "ok")
        self.assertNotEqual(source["creator"], target["creator"])
        self.assertEqual(
            source["reflection_semantic_sha256"],
            target["reflection_semantic_sha256"],
        )
        self.assertEqual(source["resources"][0]["bind_point"], 0)
        self.assertEqual(source["variables"][0]["name"], "waterAlpha")

    def test_signature_semantics_are_decoded(self) -> None:
        parsed = TOOL.parse_dxbc_signature(valid_signature_payload("TEXCOORD"), "ISGN")
        self.assertEqual(parsed["status"], "ok")
        self.assertEqual(parsed["elements"][0]["semantic_name"], "TEXCOORD")
        self.assertEqual(parsed["elements"][0]["mask"], 0xF)
        self.assertTrue(parsed["semantic_sha256"])

    def test_dxbc_reflection_evidence_separates_metadata_only_and_code_delta(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            workspace = project / ".local/build/quartet_restoration"
            reports = project / ".local/reports/quartet_restoration"
            differences_dir = reports / "differences"
            mappings = project / "titles/blue_reflection/modules/quartet_restoration/mappings"
            differences_dir.mkdir(parents=True)
            mappings.mkdir(parents=True)
            binary_dir = reports / TOOL.BINARY_DELTA_EVIDENCE_DIR
            binary_dir.mkdir(parents=True)
            TOOL.atomic_json(
                binary_dir / "SUMMARY.json",
                {
                    "type": "br_quartet_restoration_binary_delta_evidence_summary",
                    "format_version": 1,
                    "tool_version": "0.0.12",
                },
            )
            rules = mappings / "effect_material_rules.tsv"
            rules.write_text(
                "rule_id\tstatus\tnormalized_path_glob\tdomain\tpriority\tevidence_kind\tkeywords\tnote\n"
                "water\tactive\tdata/x64/shader/cwater.g1s\twater_visibility\tcritical\tshader\twater\ttest\n"
                "fog\tactive\tdata/x64/shader/heightfog.g1s\tsteam_or_vapor_occlusion\thigh\tshader\tfog\ttest\n",
                encoding="utf-8",
            )
            entries = []
            for normalized in (
                "data/x64/shader/cwater.g1s",
                "data/x64/shader/heightfog.g1s",
            ):
                source_entry = entry(normalized, b"old-" + normalized.encode(), "DATA/PACK00_02.PAK")
                target_entry = entry(normalized, b"new-" + normalized.encode(), "Data/PACK10_02.PAK")
                entries.append(
                    {
                        "classification": "changed",
                        "scope_status": "in_scope",
                        "normalized_path": normalized,
                        "source": TOOL.file_ref(source_entry),
                        "target": TOOL.file_ref(target_entry),
                        "binary_similarity": 0.0,
                        "size_ratio": 1.0,
                    }
                )
                source_path = TOOL.inventory_workspace_file(
                    workspace, "source", "br1_assets", source_entry["archive"], source_entry["path"]
                )
                target_path = TOOL.inventory_workspace_file(
                    workspace, "target", "br1_assets", target_entry["archive"], target_entry["path"]
                )
                source_path.parent.mkdir(parents=True, exist_ok=True)
                target_path.parent.mkdir(parents=True, exist_ok=True)
                if normalized.endswith("cwater.g1s"):
                    source_path.write_bytes(
                        dxbc_reflection_program(creator="Compiler A", opcode_id=10, stat_marker=1)
                    )
                    target_path.write_bytes(
                        dxbc_reflection_program(creator="Compiler B", opcode_id=10, stat_marker=2)
                    )
                else:
                    source_path.write_bytes(
                        dxbc_reflection_program(creator="Compiler A", opcode_id=10, stat_marker=1)
                    )
                    target_path.write_bytes(
                        dxbc_reflection_program(creator="Compiler B", opcode_id=11, stat_marker=2)
                    )
            TOOL.atomic_json(
                differences_dir / "br1_assets.json",
                {"source_archive_group": "br1_assets", "entries": entries},
            )

            output, summary = TOOL.collect_dxbc_reflection_evidence(
                project_root=project,
                workspace_root=workspace,
                report_root=reports,
                rules_file=rules,
                maximum_earc_bytes=1024 * 1024,
                maximum_payload_bytes=1024 * 1024,
            )
            self.assertTrue(output.is_file())
            self.assertEqual(summary["direct_shader_files"], 2)
            programs = TOOL.read_tsv(
                reports / TOOL.DXBC_REFLECTION_EVIDENCE_DIR / "DXBC_REFLECTION_PROGRAMS.tsv"
            )
            by_path = {row["normalized_path"]: row for row in programs}
            self.assertEqual(
                by_path["data/x64/shader/cwater.g1s"]["classification"],
                "compiler_or_reflection_metadata_only_delta",
            )
            self.assertEqual(
                by_path["data/x64/shader/heightfog.g1s"]["classification"],
                "code_delta_with_stable_reflection",
            )
            readiness = TOOL.read_tsv(
                reports / TOOL.DXBC_REFLECTION_EVIDENCE_DIR / "PROTOTYPE_READINESS.tsv"
            )
            ready_by_path = {row["normalized_path"]: row for row in readiness}
            self.assertEqual(
                ready_by_path["data/x64/shader/cwater.g1s"]["readiness"],
                "not_a_shader_code_restoration_candidate",
            )
            self.assertEqual(
                ready_by_path["data/x64/shader/heightfog.g1s"]["readiness"],
                "ready_for_reversible_prototype_generation",
            )


    def test_dxbc_checksum_stamp_roundtrip(self) -> None:
        raw = dxbc_reflection_program(creator="Compiler A", opcode_id=10, stat_marker=1)
        stamped = TOOL.stamp_dxbc_checksum(raw)
        self.assertNotEqual(stamped[4:20], bytes(16))
        self.assertEqual(stamped[4:20], TOOL.calculate_dxbc_checksum(stamped))
        mutated = bytearray(stamped)
        mutated[-1] ^= 1
        self.assertNotEqual(mutated[4:20], TOOL.calculate_dxbc_checksum(bytes(mutated)))

    def test_rebuild_dxbc_with_source_code_preserves_target_reflection(self) -> None:
        source = TOOL.stamp_dxbc_checksum(
            dxbc_reflection_program(creator="Compiler A", opcode_id=10, stat_marker=1)
        )
        target = TOOL.stamp_dxbc_checksum(
            dxbc_reflection_program(creator="Compiler B", opcode_id=11, stat_marker=2)
        )
        source_program = TOOL.find_dxbc_programs(source)[0]
        target_program = TOOL.find_dxbc_programs(target)[0]
        rebuilt, metadata = TOOL.rebuild_dxbc_with_source_code(
            source, target, source_program, target_program
        )
        self.assertTrue(metadata["non_code_chunks_preserved"])
        self.assertTrue(metadata["source_code_chunks_preserved"])
        self.assertTrue(metadata["checksum_matches"])
        rebuilt_program = TOOL.find_dxbc_programs(rebuilt)[0]
        source_chunks = TOOL._chunk_map(source, source_program)
        target_chunks = TOOL._chunk_map(target, target_program)
        rebuilt_chunks = TOOL._chunk_map(rebuilt, rebuilt_program)
        self.assertEqual(rebuilt_chunks["SHDR#0"]["sha256"], source_chunks["SHDR#0"]["sha256"])
        self.assertEqual(rebuilt_chunks["RDEF#0"]["sha256"], target_chunks["RDEF#0"]["sha256"])

    def test_g1s_envelope_evidence_dry_runs_transplant_without_writing_prototype(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            workspace = project / ".local/build/quartet_restoration"
            reports = project / ".local/reports/quartet_restoration"
            differences_dir = reports / "differences"
            reflection_dir = reports / TOOL.DXBC_REFLECTION_EVIDENCE_DIR
            mappings = project / "titles/blue_reflection/modules/quartet_restoration/mappings"
            differences_dir.mkdir(parents=True)
            reflection_dir.mkdir(parents=True)
            mappings.mkdir(parents=True)
            TOOL.atomic_json(
                reflection_dir / "SUMMARY.json",
                {
                    "type": "br_quartet_restoration_dxbc_reflection_evidence_summary",
                    "format_version": 1,
                    "tool_version": "0.0.13",
                },
            )
            TOOL.write_tsv(
                reflection_dir / "PROTOTYPE_READINESS.tsv",
                ["normalized_path", "readiness"],
                [{"normalized_path": "data/x64/shader/heightfog.g1s", "readiness": "ready_for_reversible_prototype_generation"}],
            )
            TOOL.write_tsv(
                reflection_dir / "DXBC_REFLECTION_DIFF.tsv",
                ["normalized_path", "source_program_index", "target_program_index", "classification"],
                [{"normalized_path": "data/x64/shader/heightfog.g1s", "source_program_index": 0, "target_program_index": 0, "classification": "code_delta_with_stable_reflection"}],
            )
            rules = mappings / "effect_material_rules.tsv"
            rules.write_text(
                "rule_id\tstatus\tnormalized_path_glob\tdomain\tpriority\tevidence_kind\tkeywords\tnote\n"
                "fog\tactive\tdata/x64/shader/heightfog.g1s\tsteam_or_vapor_occlusion\thigh\tshader\tfog\ttest\n",
                encoding="utf-8",
            )
            normalized = "data/x64/shader/heightfog.g1s"
            source_entry = entry(normalized, b"old", "DATA/PACK00_02.PAK")
            target_entry = entry(normalized, b"new", "Data/PACK10_02.PAK")
            TOOL.atomic_json(
                differences_dir / "br1_assets.json",
                {
                    "source_archive_group": "br1_assets",
                    "entries": [{
                        "classification": "changed",
                        "scope_status": "in_scope",
                        "normalized_path": normalized,
                        "source": TOOL.file_ref(source_entry),
                        "target": TOOL.file_ref(target_entry),
                        "binary_similarity": 0.0,
                        "size_ratio": 1.0,
                    }],
                },
            )
            source_program = TOOL.stamp_dxbc_checksum(
                dxbc_reflection_program(creator="Compiler A", opcode_id=10, stat_marker=1)
            )
            target_program = TOOL.stamp_dxbc_checksum(
                dxbc_reflection_program(creator="Compiler B", opcode_id=11, stat_marker=2)
            )
            def wrap(program: bytes) -> bytes:
                offset = 32
                total = offset + len(program) + 8
                header = b"_S1G" + struct.pack("<III", offset, len(program), total) + bytes(16)
                return header + program + b"TRAILER!"
            source_path = TOOL.inventory_workspace_file(workspace, "source", "br1_assets", source_entry["archive"], source_entry["path"])
            target_path = TOOL.inventory_workspace_file(workspace, "target", "br1_assets", target_entry["archive"], target_entry["path"])
            source_path.parent.mkdir(parents=True, exist_ok=True)
            target_path.parent.mkdir(parents=True, exist_ok=True)
            source_path.write_bytes(wrap(source_program))
            target_path.write_bytes(wrap(target_program))
            output, summary = TOOL.collect_g1s_envelope_evidence(
                project_root=project,
                workspace_root=workspace,
                report_root=reports,
                rules_file=rules,
                maximum_earc_bytes=1024 * 1024,
                maximum_payload_bytes=1024 * 1024,
            )
            self.assertTrue(output.is_file())
            self.assertEqual(summary["ready_shader_files"], 1)
            self.assertEqual(summary["dry_run_transplant_rows"], 1)
            dry_runs = TOOL.read_tsv(reports / TOOL.G1S_ENVELOPE_EVIDENCE_DIR / "DXBC_TRANSPLANT_DRY_RUN.tsv")
            self.assertEqual(dry_runs[0]["dry_run_status"], "valid_rebuilt_DXBC_not_written_to_disk")
            self.assertEqual(dry_runs[0]["checksum_matches"], "true")
            plans = TOOL.read_tsv(reports / TOOL.G1S_ENVELOPE_EVIDENCE_DIR / "G1S_SERIALIZATION_PLAN.tsv")
            self.assertEqual(plans[0]["prototype_generated"], "false")
            self.assertFalse((workspace / "prototypes").exists())


    def test_g1s_serializer_updates_only_validated_size_fields(self) -> None:
        source0 = TOOL.stamp_dxbc_checksum(
            dxbc_reflection_program(creator="Compiler A", opcode_id=10, stat_marker=1, extra_instructions=2)
        )
        target0 = TOOL.stamp_dxbc_checksum(
            dxbc_reflection_program(creator="Compiler B", opcode_id=11, stat_marker=2)
        )
        target1 = TOOL.stamp_dxbc_checksum(
            dxbc_reflection_program(creator="Compiler B", opcode_id=20, stat_marker=3, stage_code=1, extra_instructions=1)
        )
        source_payload = g1s_envelope([source0, target1], magic=b"_S2G3000")
        target_payload = g1s_envelope([target0, target1])
        source_programs = TOOL.find_dxbc_programs(source_payload)
        target_programs = TOOL.find_dxbc_programs(target_payload)
        rebuilt0, metadata = TOOL.rebuild_dxbc_with_source_code(
            source_payload, target_payload, source_programs[0], target_programs[0]
        )
        self.assertTrue(metadata["checksum_matches"])
        prototype, serializer, fields = TOOL.serialize_g1s_code_transplant(
            target_payload, target_programs, {0: rebuilt0}
        )
        self.assertEqual(struct.unpack_from("<I", prototype, 8)[0], len(prototype))
        self.assertTrue(serializer["only_approved_prefix_fields_changed"])
        self.assertEqual(serializer["size_delta"], len(rebuilt0) - len(target0))
        field_kinds = [row["field_kind"] for row in fields]
        self.assertEqual(field_kinds.count("program_size"), 2)
        self.assertEqual(field_kinds.count("file_size"), 1)
        programs = TOOL.find_dxbc_programs(prototype)
        self.assertEqual(len(programs), 2)
        second = prototype[int(programs[1]["offset"]):int(programs[1]["offset"]) + int(programs[1]["size"])]
        self.assertEqual(second, target1)
        rebuilt_chunks = TOOL._chunk_map(prototype, programs[0])
        source_chunks = TOOL._chunk_map(source_payload, source_programs[0])
        target_chunks = TOOL._chunk_map(target_payload, target_programs[0])
        self.assertEqual(rebuilt_chunks["SHDR#0"]["sha256"], source_chunks["SHDR#0"]["sha256"])
        self.assertEqual(rebuilt_chunks["RDEF#0"]["sha256"], target_chunks["RDEF#0"]["sha256"])

    def test_build_g1s_prototypes_writes_only_local_validated_output(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            workspace = project / ".local/build/quartet_restoration"
            reports = project / ".local/reports/quartet_restoration"
            differences_dir = reports / "differences"
            envelope_dir = reports / TOOL.G1S_ENVELOPE_EVIDENCE_DIR
            mappings = project / "titles/blue_reflection/modules/quartet_restoration/mappings"
            differences_dir.mkdir(parents=True)
            envelope_dir.mkdir(parents=True)
            mappings.mkdir(parents=True)
            TOOL.atomic_json(
                envelope_dir / "SUMMARY.json",
                {
                    "type": "br_quartet_restoration_g1s_envelope_evidence_summary",
                    "format_version": 1,
                    "tool_version": "0.0.14",
                },
            )
            normalized = "data/x64/shader/heightfog.g1s"
            TOOL.write_tsv(
                envelope_dir / "G1S_SERIALIZATION_PLAN.tsv",
                ["normalized_path", "readiness", "all_rebuilt_DXBC_valid", "all_rebuilt_checksums_valid"],
                [{
                    "normalized_path": normalized,
                    "readiness": "G1S_outer_reference_table_candidates_detected_serializer_not_implemented",
                    "all_rebuilt_DXBC_valid": "true",
                    "all_rebuilt_checksums_valid": "true",
                }],
            )
            TOOL.write_tsv(
                envelope_dir / "DXBC_TRANSPLANT_DRY_RUN.tsv",
                ["normalized_path", "source_program_index", "target_program_index", "dry_run_status", "reflection_preserved", "checksum_matches"],
                [{
                    "normalized_path": normalized,
                    "source_program_index": 0,
                    "target_program_index": 0,
                    "dry_run_status": "valid_rebuilt_DXBC_not_written_to_disk",
                    "reflection_preserved": "true",
                    "checksum_matches": "true",
                }],
            )
            rules = mappings / "effect_material_rules.tsv"
            rules.write_text(
                "rule_id\tstatus\tnormalized_path_glob\tdomain\tpriority\tevidence_kind\tkeywords\tnote\n"
                "fog\tactive\tdata/x64/shader/heightfog.g1s\tsteam_or_vapor_occlusion\thigh\tshader\tfog\ttest\n",
                encoding="utf-8",
            )
            source0 = TOOL.stamp_dxbc_checksum(
                dxbc_reflection_program(creator="Compiler A", opcode_id=10, stat_marker=1, extra_instructions=2)
            )
            target0 = TOOL.stamp_dxbc_checksum(
                dxbc_reflection_program(creator="Compiler B", opcode_id=11, stat_marker=2)
            )
            shared1 = TOOL.stamp_dxbc_checksum(
                dxbc_reflection_program(creator="Compiler B", opcode_id=20, stat_marker=3, stage_code=1, extra_instructions=1)
            )
            source_g1s = g1s_envelope([source0, shared1], magic=b"_S2G3000")
            target_g1s = g1s_envelope([target0, shared1])
            source_entry = entry(normalized, source_g1s, "DATA/PACK00_02.PAK")
            target_entry = entry(normalized, target_g1s, "Data/PACK10_02.PAK")
            TOOL.atomic_json(
                differences_dir / "br1_assets.json",
                {
                    "source_archive_group": "br1_assets",
                    "entries": [{
                        "classification": "changed",
                        "scope_status": "in_scope",
                        "normalized_path": normalized,
                        "source": TOOL.file_ref(source_entry),
                        "target": TOOL.file_ref(target_entry),
                        "binary_similarity": 0.0,
                        "size_ratio": 1.0,
                    }],
                },
            )
            source_path = TOOL.inventory_workspace_file(workspace, "source", "br1_assets", source_entry["archive"], source_entry["path"])
            target_path = TOOL.inventory_workspace_file(workspace, "target", "br1_assets", target_entry["archive"], target_entry["path"])
            source_path.parent.mkdir(parents=True, exist_ok=True)
            target_path.parent.mkdir(parents=True, exist_ok=True)
            source_path.write_bytes(source_g1s)
            target_path.write_bytes(target_g1s)
            output, summary = TOOL.build_g1s_prototypes(
                project_root=project,
                workspace_root=workspace,
                report_root=reports,
                rules_file=rules,
                maximum_earc_bytes=1024 * 1024,
                maximum_payload_bytes=1024 * 1024,
            )
            self.assertTrue(output.is_file())
            self.assertEqual(summary["prototype_rows"], 1)
            self.assertEqual(summary["validation_failures"], 0)
            prototypes = TOOL.read_tsv(reports / TOOL.G1S_PROTOTYPE_EVIDENCE_DIR / "G1S_PROTOTYPES.tsv")
            local_output = project / prototypes[0]["local_output_path"]
            self.assertTrue(local_output.is_file())
            self.assertTrue(TOOL.is_relative_to(local_output.resolve(), workspace.resolve()))
            self.assertEqual(target_path.read_bytes(), target_g1s)
            self.assertNotEqual(local_output.read_bytes(), target_g1s)
            self.assertFalse((reports / TOOL.G1S_PROTOTYPE_EVIDENCE_DIR / "heightfog.g1s").exists())


    def test_costume_family_for_path_covers_scene_state_families(self) -> None:
        self.assertEqual(TOOL.costume_family_for_path("data/x64/character/pc00/pc00_udw2.elixir.gz"), "underwear_variant_2")
        self.assertEqual(TOOL.costume_family_for_path("data/x64/character/pc01/pc01_nkd.g1t"), "unclothed_body")
        self.assertEqual(TOOL.costume_family_for_path("data/x64/character/pc02/pc02_rfl_w.elixir.gz"), "wet_reflector")
        self.assertEqual(TOOL.costume_family_for_path("data/x64/character/item_bathtowel_00/item_bathtowel_00.elixir.gz"), "bath_towel")

    def test_flatten_xml_settings_reads_lightshaft_values(self) -> None:
        rows = TOOL.flatten_xml_settings(
            b'<LightShaft enabled="1"><Density>0.75</Density><Bloom intensity="2.0"/></LightShaft>'
        )
        values = {row["setting_path"]: row["value"] for row in rows}
        self.assertEqual(values["LightShaft/@enabled"], "1")
        self.assertIn("0.75", values.values())
        self.assertIn("2.0", values.values())

    def test_oid_seed_windows_are_binary_and_deterministic(self) -> None:
        payload = bytes.fromhex("102030405566778899aabbccddeeff00112233445566778899aabbccddeeff00")
        first = TOOL.oid_seed_windows(payload)
        second = TOOL.oid_seed_windows(payload)
        self.assertEqual(first, second)
        self.assertTrue(first)
        self.assertTrue(all(len(seed) >= 8 for _offset, seed, _kind in first))
        self.assertFalse(TOOL.oid_seed_windows(b"ObjectID:PC00_Udw2"))

    def test_collect_presentation_surfaces_detects_costume_substitution_and_lightshaft_preset(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            workspace = project / ".local/build/quartet_restoration"
            reports = project / ".local/reports/quartet_restoration"
            differences_dir = reports / "differences"
            inventories_dir = reports / "inventories"
            prototype_dir = reports / TOOL.G1S_PROTOTYPE_EVIDENCE_DIR
            mappings = project / "titles/blue_reflection/modules/quartet_restoration/mappings"
            differences_dir.mkdir(parents=True)
            inventories_dir.mkdir(parents=True)
            prototype_dir.mkdir(parents=True)
            mappings.mkdir(parents=True)
            TOOL.atomic_json(
                reports / "SUMMARY.json",
                {
                    "type": "br_quartet_restoration_research_summary",
                    "format_version": 1,
                    "tool_version": "0.0.3",
                },
            )
            TOOL.atomic_json(
                prototype_dir / "SUMMARY.json",
                {
                    "type": "br_quartet_restoration_g1s_prototype_evidence_summary",
                    "format_version": 1,
                    "tool_version": "0.0.15",
                    "prototype_rows": 2,
                    "validation_failures": 0,
                },
            )
            candidate_rules = mappings / "candidate_rules.tsv"
            candidate_rules.write_text(
                "rule_id\tstatus\tnormalized_path_glob\tfamily\tpriority\tcounterpart_templates\tnote\n"
                "udw2\tactive\tdata/x64/character/pc*/pc*_udw2.*\tunderwear_coverage_variant\tcritical\t{character}_udw\ttest\n",
                encoding="utf-8",
            )
            effect_rules = mappings / "effect_material_rules.tsv"
            effect_rules.write_text(
                "rule_id\tstatus\tnormalized_path_glob\tdomain\tpriority\tevidence_kind\tkeywords\tnote\n"
                "light\tactive\tsaves/graphicssetting/lightshaftpreset.xml\tgodray_or_lightshaft_occlusion\tcritical\trender_preset\tlightshaft,bloom\ttest\n",
                encoding="utf-8",
            )
            dimensions = mappings / "restoration_dimensions.tsv"
            dimensions.write_text(
                "dimension_id\tstatus\tpriority\tevidence_surfaces\tnote\n"
                "scene_costume_state_binding\tactive\tcritical\tevent and OID\ttest\n"
                "alternate_costume_substitution\tactive\tcritical\tevent and OID\ttest\n"
                "godray_or_lightshaft_occlusion\tactive\tcritical\tpreset\ttest\n",
                encoding="utf-8",
            )

            base_oid = bytes.fromhex("102030405566778899aabbccddeeff00112233445566778899aabbccddeeff00")
            variant_oid = bytes.fromhex("fedcba98765432100123456789abcdeff0e1d2c3b4a5968778695a4b3c2d1e0f")
            source_base_payload = earc_archive([("PC00_UdwOid.bin", base_oid)])
            target_base_payload = earc_archive([("PC00_UdwOid.bin", base_oid)])
            target_variant_payload = earc_archive([("PC00_Udw2Oid.bin", variant_oid)])
            source_event_payload = b"HEAD" + base_oid + b"TAIL"
            target_event_payload = b"HEAD" + variant_oid + b"TAIL"
            light_xml = b'<LightShaft enabled="1"><Density>0.85</Density><Bloom intensity="1.5"/></LightShaft>'

            source_base = entry("data/x64/character/pc00/pc00_udw.elixir.gz", source_base_payload, "DATA/PACK00_02.PAK")
            target_base = entry("data/b1/x64/character/pc00/pc00_udw.elixir.gz", target_base_payload, "Data/PACK10_02.PAK")
            target_base["normalized_path"] = "data/x64/character/pc00/pc00_udw.elixir.gz"
            target_base["comparison_key"] = target_base["normalized_path"].casefold()
            target_variant = entry("data/b1/x64/character/pc00/pc00_udw2.elixir.gz", target_variant_payload, "Data/PACK10_02.PAK")
            target_variant["normalized_path"] = "data/x64/character/pc00/pc00_udw2.elixir.gz"
            target_variant["comparison_key"] = target_variant["normalized_path"].casefold()
            source_event = entry("event/event_jp/te99/event_te99_010.ebd", source_event_payload, "DATA/PACK01.PAK")
            target_event = entry("event/b1/event_jp/te99/event_te99_010.ebd", target_event_payload, "Data/PACK11.PAK")
            target_event["normalized_path"] = source_event["normalized_path"]
            target_event["comparison_key"] = source_event["comparison_key"]
            target_light = entry("saves/b1/graphicssetting/lightshaftpreset.xml", light_xml, "Data/PACK12.PAK")
            target_light["normalized_path"] = "saves/graphicssetting/lightshaftpreset.xml"
            target_light["comparison_key"] = target_light["normalized_path"].casefold()

            TOOL.atomic_json(inventories_dir / "br1_assets.source.json", inventory("original", [source_base], pair="br1_assets", side="source"))
            TOOL.atomic_json(inventories_dir / "br1_assets.target.json", inventory("quartet", [target_base, target_variant], pair="br1_assets", side="target"))
            TOOL.atomic_json(inventories_dir / "br1_events.source.json", inventory("original", [source_event], pair="br1_events", side="source"))
            TOOL.atomic_json(inventories_dir / "br1_events.target.json", inventory("quartet", [target_event], pair="br1_events", side="target"))
            TOOL.atomic_json(inventories_dir / "br1_language.source.json", inventory("original", [], pair="br1_language", side="source"))
            TOOL.atomic_json(inventories_dir / "br1_language.target.json", inventory("quartet", [target_light], pair="br1_language", side="target"))

            TOOL.atomic_json(
                differences_dir / "br1_assets.json",
                {
                    "source_archive_group": "br1_assets",
                    "entries": [{
                        "classification": "new_in_target", "scope_status": "in_scope",
                        "normalized_path": target_variant["normalized_path"], "source": None,
                        "target": TOOL.file_ref(target_variant), "binary_similarity": 0.0, "size_ratio": 0.0,
                    }],
                },
            )
            TOOL.atomic_json(
                differences_dir / "br1_events.json",
                {
                    "source_archive_group": "br1_events",
                    "entries": [{
                        "classification": "changed", "scope_status": "in_scope",
                        "normalized_path": source_event["normalized_path"],
                        "source": TOOL.file_ref(source_event), "target": TOOL.file_ref(target_event),
                        "binary_similarity": 0.0, "size_ratio": 1.0,
                    }],
                },
            )
            TOOL.atomic_json(
                differences_dir / "br1_language.json",
                {
                    "source_archive_group": "br1_language",
                    "entries": [{
                        "classification": "new_in_target", "scope_status": "in_scope",
                        "normalized_path": target_light["normalized_path"], "source": None,
                        "target": TOOL.file_ref(target_light), "binary_similarity": 0.0, "size_ratio": 0.0,
                    }],
                },
            )

            for side, pair_id, item, payload in (
                ("source", "br1_assets", source_base, source_base_payload),
                ("target", "br1_assets", target_base, target_base_payload),
                ("target", "br1_assets", target_variant, target_variant_payload),
                ("source", "br1_events", source_event, source_event_payload),
                ("target", "br1_events", target_event, target_event_payload),
                ("target", "br1_language", target_light, light_xml),
            ):
                path = TOOL.inventory_workspace_file(workspace, side, pair_id, item["archive"], item["path"])
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(payload)

            output, summary = TOOL.collect_presentation_surface_evidence(
                project_root=project, workspace_root=workspace, report_root=reports,
                candidate_rules_file=candidate_rules, effect_rules_file=effect_rules,
                dimensions_file=dimensions, maximum_earc_bytes=1024 * 1024,
                maximum_payload_bytes=1024 * 1024,
            )
            self.assertTrue(output.is_file())
            self.assertEqual(summary["g1s_prototypes_validated"], 2)
            self.assertGreater(summary["unique_oid_seed_rows"], 0)
            self.assertGreater(summary["event_costume_binding_hit_rows"], 0)
            self.assertGreater(summary["lightshaft_preset_setting_differences"], 0)
            bindings = TOOL.read_tsv(reports / TOOL.PRESENTATION_SURFACE_EVIDENCE_DIR / "SCENE_COSTUME_BINDING_CANDIDATES.tsv")
            self.assertTrue(any(row["classification"] == "candidate_costume_substitution" for row in bindings))
            self.assertTrue(all("seed" not in row for row in TOOL.read_tsv(reports / TOOL.PRESENTATION_SURFACE_EVIDENCE_DIR / "COSTUME_OID_SIGNATURES.tsv")))


    def test_build_event_identifier_seeds_keeps_candidate_role_unique_u32(self) -> None:
        variant_value = 0x12345678
        counterpart_value = 0x87654321
        assets = [
            {
                "candidate_id": "cand_a", "family": "wet_reflector", "character_id": "pc00",
                "role": "variant", "side": "target", "asset_path": "data/x64/character/pc00_rfl_w/a.elixir.gz",
                "member_name": "aOid.bin", "payload": struct.pack("<4I", 0, variant_value, 1, 2),
            },
            {
                "candidate_id": "cand_a", "family": "wet_reflector", "character_id": "pc00",
                "role": "variant", "side": "target", "asset_path": "data/x64/character/pc00_rfl_w/b.elixir.gz",
                "member_name": "bOid.bin", "payload": struct.pack("<4I", 0, variant_value, 3, 4),
            },
            {
                "candidate_id": "cand_a", "family": "wet_reflector", "character_id": "pc00",
                "role": "counterpart_original", "side": "source", "asset_path": "data/x64/character/pc00_rfl/a.elixir.gz",
                "member_name": "aOid.bin", "payload": struct.pack("<4I", 0, counterpart_value, 1, 2),
            },
        ]
        numeric, hashes = TOOL.build_event_identifier_seeds(assets)
        self.assertTrue(any(row["value_hex"] == "0x12345678" and row["role"] == "variant" for row in numeric))
        self.assertTrue(any(row["value_hex"] == "0x87654321" and row["role"] == "counterpart_original" for row in numeric))
        self.assertTrue(hashes)

    def test_aligned_seed_hits_finds_u32_and_pair(self) -> None:
        one = {"seed": struct.pack("<I", 0x12345678), "seed_id": "one"}
        pair = {"seed": struct.pack("<II", 0x12345678, 0x87654321), "seed_id": "pair"}
        payload = struct.pack("<4I", 0, 0x12345678, 0x87654321, 0)
        hits = TOOL.aligned_seed_hits(payload, [one, pair])
        by_id = {row["seed_id"]: offsets for row, offsets in hits}
        self.assertEqual(by_id["one"], [4])
        self.assertEqual(by_id["pair"], [4])

    def test_sequence_word_delta_runs_records_numeric_transition(self) -> None:
        source = struct.pack("<5I", 1, 0x12345678, 3, 4, 5)
        target = struct.pack("<5I", 1, 0x87654321, 3, 4, 5)
        runs, transitions = TOOL.sequence_word_delta_runs(source, target)
        self.assertEqual(len(runs), 1)
        self.assertEqual(runs[0]["tag"], "replace")
        self.assertEqual(transitions[(0x12345678, 0x87654321)], 1)

    def test_presentation_surface_triage_filters_non_scene_beams_and_presets(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / TOOL.PRESENTATION_SURFACE_EVIDENCE_DIR
            root.mkdir(parents=True)
            TOOL.write_tsv(
                root / "LIGHTSHAFT_ASSET_CANDIDATES.tsv",
                ["pair_id", "normalized_path", "classification", "source_size", "target_size", "path_keywords", "review_status"],
                [{"pair_id": "br1_language", "normalized_path": "saves/graphicssetting/lightshaftpreset.xml", "classification": "new_in_target", "source_size": "", "target_size": 10, "path_keywords": "lightshaft", "review_status": "x"}],
            )
            TOOL.write_tsv(
                root / "LIGHTSHAFT_EFFECT_MEMBERS.tsv",
                ["candidate_id", "domain", "normalized_path", "member_key", "source_member_name", "target_member_name", "status", "keyword_hits", "review_status"],
                [{"candidate_id": "x", "domain": "x", "normalized_path": "data/x64/effect/1000_pc00.elixir.gz", "member_key": "beam", "source_member_name": "e_PC00_beam.g1e", "target_member_name": "e_PC00_beam.g1e", "status": "changed", "keyword_hits": "beam", "review_status": "x"}],
            )
            TOOL.write_tsv(
                root / "LIGHTSHAFT_PRESET_SETTINGS.tsv",
                ["pair_id", "normalized_path", "setting_path", "source_value", "target_value", "delta", "review_status"],
                [{"pair_id": "br1_language", "normalized_path": "saves/graphicssetting/lightshaftpreset.xml", "setting_path": "Root/Enable", "source_value": "", "target_value": "1", "delta": "added", "review_status": "x"}],
            )
            rows = TOOL.presentation_surface_triage(Path(temp))
            classes = {row["triage_classification"] for row in rows}
            self.assertIn("gameplay_attack_effect_false_positive", classes)
            self.assertIn("render_option_schema_not_scene_evidence", classes)


    def test_monotonic_anchor_segments_map_inserted_destination(self) -> None:
        source = b"PREFIX_UNIQUE_1234" + b"PAYLOAD_DESTINATION_UNIQUE_567890"
        target = b"PREFIX_UNIQUE_1234" + b"INSERTED" + b"PAYLOAD_DESTINATION_UNIQUE_567890"
        segments = TOOL.monotonic_anchor_segments(source, target, block_size=12, stride=1)
        source_offset = source.index(b"PAYLOAD")
        mapped, anchor_size = TOOL.map_source_event_offset(
            source_offset, segments, source_size=len(source), target_size=len(target)
        )
        self.assertEqual(mapped, target.index(b"PAYLOAD"))
        self.assertGreaterEqual(anchor_size, 12)

    def test_analyze_event_structure_confirms_unaligned_internal_offset(self) -> None:
        source = bytearray(b"HEADER00" + b"\x00" * 24 + b"UNIQUE_BLOCK_BEFORE_1234567890" + b"PAYLOAD_DESTINATION_UNIQUE_ABCDEFGHIJ")
        source_destination = source.index(b"PAYLOAD")
        struct.pack_into("<I", source, 8, source_destination)
        target = bytearray(source[:source_destination] + b"INSERTED_TEXT" + source[source_destination:])
        struct.pack_into("<I", target, 8, source_destination + len(b"INSERTED_TEXT"))
        result = TOOL.analyze_event_structure_pair(bytes(source), bytes(target))
        self.assertEqual(result["classification"], "relocation_and_text_dominated")
        self.assertTrue(any(row["width"] == 4 and row["mapping_error"] == 0 for row in result["pointers"]))
        self.assertEqual(result["unresolved_bytes"], 0)

    def test_analyze_event_structure_keeps_non_pointer_scalar_candidate(self) -> None:
        source = bytearray(b"HEADER00" + b"\x00" * 24 + b"UNIQUE_BLOCK_BEFORE_1234567890" + b"PAYLOAD_DESTINATION_UNIQUE_ABCDEFGHIJ")
        source_destination = source.index(b"PAYLOAD")
        struct.pack_into("<I", source, 8, source_destination)
        target = bytearray(source[:source_destination] + b"INSERTED_TEXT" + source[source_destination:])
        struct.pack_into("<I", target, 8, source_destination + len(b"INSERTED_TEXT"))
        source[24] = 5
        target[24] = 7
        result = TOOL.analyze_event_structure_pair(bytes(source), bytes(target))
        self.assertEqual(result["classification"], "focused_unresolved_binary_candidate")
        self.assertEqual(result["unresolved_bytes"], 1)
        self.assertTrue(any(row["classification"] == "unresolved_small_scalar_delta" for row in result["scalars"]))

    def test_collect_event_structure_evidence_writes_metadata_only_report(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            workspace = project / ".local/build/quartet_restoration"
            reports = project / ".local/reports/quartet_restoration"
            differences_dir = reports / "differences"
            inventories_dir = reports / "inventories"
            identifier_dir = reports / TOOL.EVENT_IDENTIFIER_EVIDENCE_DIR
            differences_dir.mkdir(parents=True)
            inventories_dir.mkdir(parents=True)
            identifier_dir.mkdir(parents=True)
            TOOL.atomic_json(
                reports / "SUMMARY.json",
                {"type": "br_quartet_restoration_research_summary", "format_version": 1, "tool_version": "0.0.3"},
            )
            TOOL.atomic_json(
                identifier_dir / "SUMMARY.json",
                {
                    "type": "br_quartet_restoration_event_identifier_evidence_summary",
                    "format_version": 1,
                    "tool_version": "0.0.17",
                    "event_u32_transition_rows": 12,
                    "event_identifier_hit_rows": 0,
                },
            )
            source_payload = bytearray(b"HEADER00" + b"\x00" * 24 + b"UNIQUE_BLOCK_BEFORE_1234567890" + b"PAYLOAD_DESTINATION_UNIQUE_ABCDEFGHIJ")
            source_destination = source_payload.index(b"PAYLOAD")
            struct.pack_into("<I", source_payload, 8, source_destination)
            target_payload = bytearray(source_payload[:source_destination] + b"INSERTED_TEXT" + source_payload[source_destination:])
            struct.pack_into("<I", target_payload, 8, source_destination + len(b"INSERTED_TEXT"))
            source_entry = entry("event/event_jp/te99/event_te99_010.ebd", bytes(source_payload), "DATA/PACK01.PAK")
            target_entry = entry("event/b1/event_jp/te99/event_te99_010.ebd", bytes(target_payload), "Data/PACK11.PAK")
            target_entry["normalized_path"] = source_entry["normalized_path"]
            target_entry["comparison_key"] = source_entry["comparison_key"]
            TOOL.atomic_json(inventories_dir / "br1_events.source.json", inventory("original", [source_entry], pair="br1_events", side="source"))
            TOOL.atomic_json(inventories_dir / "br1_events.target.json", inventory("quartet", [target_entry], pair="br1_events", side="target"))
            TOOL.atomic_json(
                differences_dir / "br1_events.json",
                {
                    "source_archive_group": "br1_events",
                    "entries": [{
                        "classification": "changed", "scope_status": "in_scope",
                        "normalized_path": source_entry["normalized_path"],
                        "source": TOOL.file_ref(source_entry), "target": TOOL.file_ref(target_entry),
                        "binary_similarity": 0.5, "size_ratio": len(source_payload) / len(target_payload),
                    }],
                },
            )
            for side, item, payload in (("source", source_entry, source_payload), ("target", target_entry, target_payload)):
                path = TOOL.inventory_workspace_file(workspace, side, "br1_events", item["archive"], item["path"])
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(payload)
            output, summary = TOOL.collect_event_structure_evidence(
                project_root=project,
                workspace_root=workspace,
                report_root=reports,
                maximum_event_bytes=1024 * 1024,
                anchor_block_size=12,
                anchor_stride=1,
            )
            self.assertTrue(output.is_file())
            self.assertEqual(summary["ebd_files_analyzed"], 1)
            self.assertGreater(summary["relocation_pointer_rows"], 0)
            pointers = TOOL.read_tsv(reports / TOOL.EVENT_STRUCTURE_EVIDENCE_DIR / "EBD_RELOCATION_FIELDS.tsv")
            self.assertTrue(any(row["classification"] == "relocated_internal_offset" for row in pointers))
            report_text = "\n".join(path.read_text(encoding="utf-8") for path in (reports / TOOL.EVENT_STRUCTURE_EVIDENCE_DIR).glob("*.tsv"))
            self.assertNotIn("PAYLOAD_DESTINATION_UNIQUE", report_text)


    def test_analyze_event_structure_ignores_identical_anchor_gaps(self) -> None:
        source = b"UNIQUE_ANCHOR_A_123456" + b"\x00\x00\x00\x00" + b"UNIQUE_ANCHOR_B_654321" + b"\x05" + b"UNIQUE_ANCHOR_C_ABCDEF"
        target = b"UNIQUE_ANCHOR_A_123456" + b"\x00\x00\x00\x00" + b"UNIQUE_ANCHOR_B_654321" + b"\x07" + b"UNIQUE_ANCHOR_C_ABCDEF"
        result = TOOL.analyze_event_structure_pair(source, target, anchor_block_size=12, anchor_stride=1)
        self.assertEqual(result["unresolved_bytes"], 1)
        self.assertTrue(all(row["source_sha256"] != row["target_sha256"] for row in result["regions"]))
        self.assertEqual(result["classification"], "focused_unresolved_binary_candidate")

    def test_derive_and_scan_scene_identifier_seeds(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            rules = Path(tmp) / "effect.tsv"
            TOOL.write_tsv(
                rules,
                ["rule_id","status","normalized_path_glob","domain","priority","evidence_kind","keywords","note"],
                [{"rule_id":"pool_scene","status":"active","normalized_path_glob":"data/x64/field/s84_m_pool_01/*.elixir.gz","domain":"water_visibility","priority":"critical","evidence_kind":"scene_container","keywords":"water","note":"x"}],
            )
            seeds = TOOL.derive_scene_identifier_seeds(rules)
            self.assertTrue(any(row["encoding"] == "full_ascii" and row["field_identifier"] == "s84_m_pool_01" for row in seeds))
            hits = TOOL.scan_scene_identifier_hits(b"prefix s84_m_pool_01 suffix", seeds)
            self.assertTrue(any(row["confidence"] == "high" and row["hit_count"] == 1 for row in hits))

    def test_event_process_header_count_correlates_with_ebm_inventory(self) -> None:
        source = struct.pack("<4I", 1758, 2, 1, 0x7F000000) + b"x" * 20
        target = struct.pack("<4I", 1758, 2, 1, 0x7F000000) + b"x" * 32
        row = TOOL.event_process_header_metadata(source, target, 1758)
        self.assertTrue(row["count_matches_in_scope_ebm"])
        self.assertEqual(row["size_delta"], 12)

    def test_collect_event_record_evidence_corrects_and_links_scene(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            workspace = project / ".local/build/quartet_restoration"
            reports = project / ".local/reports/quartet_restoration"
            differences_dir = reports / "differences"
            inventories_dir = reports / "inventories"
            structure_dir = reports / TOOL.EVENT_STRUCTURE_EVIDENCE_DIR
            rules_dir = project / "titles/blue_reflection/modules/quartet_restoration/mappings"
            differences_dir.mkdir(parents=True)
            inventories_dir.mkdir(parents=True)
            structure_dir.mkdir(parents=True)
            rules_dir.mkdir(parents=True)
            TOOL.atomic_json(
                structure_dir / "SUMMARY.json",
                {"type":"br_quartet_restoration_event_structure_evidence_summary","format_version":1,"tool_version":"0.0.18","focused_scene_binary_record_candidates":99},
            )
            rules = rules_dir / "effect_material_rules.tsv"
            TOOL.write_tsv(
                rules,
                ["rule_id","status","normalized_path_glob","domain","priority","evidence_kind","keywords","note"],
                [{"rule_id":"pool_scene","status":"active","normalized_path_glob":"data/x64/field/s84_m_pool_01/*.elixir.gz","domain":"water_visibility","priority":"critical","evidence_kind":"scene_container","keywords":"water","note":"x"}],
            )
            ebd_source = b"UNIQUE_A_12345678" + b"s84_m_pool_01" + b"UNIQUE_B_12345678" + b"\x05" + b"UNIQUE_C_12345678"
            ebd_target = b"UNIQUE_A_12345678" + b"s84_m_pool_01" + b"UNIQUE_B_12345678" + b"\x07" + b"UNIQUE_C_12345678"
            epd_source = struct.pack("<4I", 1, 2, 1, 0x7F000000) + b"s84_m_pool_01" + b"\x00" * 20
            epd_target = struct.pack("<4I", 1, 2, 1, 0x7F000000) + b"s84_m_pool_01" + b"\x00" * 20 + b"ABCD"
            ebm_entry = entry("event/event_jp/te99/event_te99_010.ebm", b"text", "DATA/PACK01.PAK")
            source_ebd = entry("event/event_jp/te99/event_te99_010.ebd", ebd_source, "DATA/PACK01.PAK")
            target_ebd = entry("event/b1/event_jp/te99/event_te99_010.ebd", ebd_target, "Data/PACK11.PAK")
            target_ebd["normalized_path"] = source_ebd["normalized_path"]
            target_ebd["comparison_key"] = source_ebd["comparison_key"]
            source_epd = entry("event/eventprocess/eventprocessdataall.epd", epd_source, "DATA/PACK01.PAK")
            target_epd = entry("event/b1/eventprocess/eventprocessdataall.epd", epd_target, "Data/PACK11.PAK")
            target_epd["normalized_path"] = source_epd["normalized_path"]
            target_epd["comparison_key"] = source_epd["comparison_key"]
            TOOL.atomic_json(inventories_dir / "br1_events.source.json", inventory("original", [ebm_entry, source_ebd, source_epd], pair="br1_events", side="source"))
            TOOL.atomic_json(inventories_dir / "br1_events.target.json", inventory("quartet", [target_ebd, target_epd], pair="br1_events", side="target"))
            diff_entries = [{"classification":"identical","scope_status":"in_scope","normalized_path":ebm_entry["normalized_path"],"source":TOOL.file_ref(ebm_entry),"target":TOOL.file_ref(ebm_entry)}]
            for left, right in ((source_ebd, target_ebd), (source_epd, target_epd)):
                diff_entries.append({"classification":"changed","scope_status":"in_scope","normalized_path":left["normalized_path"],"source":TOOL.file_ref(left),"target":TOOL.file_ref(right)})
            TOOL.atomic_json(differences_dir / "br1_events.json", {"source_archive_group":"br1_events","entries":diff_entries})
            for side, item, payload in (("source",source_ebd,ebd_source),("target",target_ebd,ebd_target),("source",source_epd,epd_source),("target",target_epd,epd_target)):
                out = TOOL.inventory_workspace_file(workspace, side, "br1_events", item["archive"], item["path"])
                out.parent.mkdir(parents=True, exist_ok=True)
                out.write_bytes(payload)
            output, summary = TOOL.collect_event_record_evidence(
                project_root=project, workspace_root=workspace, report_root=reports,
                effect_material_rules_file=rules, maximum_event_bytes=1024*1024,
                anchor_block_size=8, anchor_stride=1,
            )
            self.assertTrue(output.is_file())
            self.assertEqual(summary["event_binaries_analyzed"], 2)
            self.assertTrue(summary["event_process_count_matches_in_scope_ebm"])
            self.assertGreater(summary["exact_scene_identifier_hit_rows"], 0)
            candidates = TOOL.read_tsv(reports / TOOL.EVENT_RECORD_EVIDENCE_DIR / "SCENE_LINKED_EVENT_CANDIDATES.tsv")
            self.assertTrue(any(row["normalized_path"] == source_ebd["normalized_path"] for row in candidates))


    def test_event_message_to_data_path_maps_sibling(self) -> None:
        self.assertEqual(
            TOOL.event_message_to_data_path("event/event_jp/ce01/event_message_ce01_020.ebm"),
            "event/event_jp/ce01/event_ce01_020.ebd",
        )
        self.assertEqual(TOOL.event_message_to_data_path("event/event_jp/ce01/not_message.ebm"), "")

    def test_extract_event_technical_identifiers_is_strict_and_focused(self) -> None:
        payload = b"dialogue words s84_m_pool_01 item_bathtowel_00 PC00_Rfl_W PostEffectUnsharpMask plainword"
        rows = TOOL.extract_event_technical_identifiers(payload)
        tokens = {row["technical_identifier"]: row for row in rows}
        self.assertIn("s84_m_pool_01", tokens)
        self.assertIn("item_bathtowel_00", tokens)
        self.assertIn("PC00_Rfl_W", tokens)
        self.assertIn("PostEffectUnsharpMask", tokens)
        self.assertTrue(tokens["s84_m_pool_01"]["focused_surface_term"])
        self.assertNotIn("plainword", tokens)

    def test_collect_event_family_evidence_pairs_ebm_and_ebd(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            workspace = project / ".local/build/quartet_restoration"
            reports = project / ".local/reports/quartet_restoration"
            differences_dir = reports / "differences"
            inventories_dir = reports / "inventories"
            record_dir = reports / TOOL.EVENT_RECORD_EVIDENCE_DIR
            rules_dir = project / "titles/blue_reflection/modules/quartet_restoration/mappings"
            differences_dir.mkdir(parents=True)
            inventories_dir.mkdir(parents=True)
            record_dir.mkdir(parents=True)
            rules_dir.mkdir(parents=True)
            TOOL.atomic_json(record_dir / "SUMMARY.json", {
                "type":"br_quartet_restoration_event_record_evidence_summary",
                "format_version":1,"tool_version":"0.0.19",
            })
            TOOL.write_tsv(record_dir / "EVENT_STRUCTURE_CORRECTION.tsv", [
                "normalized_path","corrected_unresolved_changed_bytes"
            ], [{"normalized_path":"event/event_jp/te99/event_te99_010.ebd","corrected_unresolved_changed_bytes":1}])
            TOOL.write_tsv(record_dir / "EVENT_RECORD_CONTEXTS.tsv", [
                "normalized_path","delta_signature_sha256","context_signature_sha256"
            ], [{"normalized_path":"event/event_jp/te99/event_te99_010.ebd","delta_signature_sha256":"d","context_signature_sha256":"c"}])
            TOOL.write_tsv(record_dir / "EVENT_DELTA_SIGNATURE_CLUSTERS.tsv", [
                "delta_signature_sha256","context_signature_sha256","cluster_classification"
            ], [{"delta_signature_sha256":"d","context_signature_sha256":"c","cluster_classification":"rare_event_record_delta"}])
            TOOL.write_tsv(record_dir / "EVENT_PROCESS_LAYOUT.tsv", [
                "normalized_path","source_leading_count"
            ], [{"normalized_path":"event/eventprocess/eventprocessdataall.epd","source_leading_count":1}])
            rules = rules_dir / "effect_material_rules.tsv"
            TOOL.write_tsv(rules, [
                "rule_id","status","normalized_path_glob","domain","priority","evidence_kind","keywords","note"
            ], [{"rule_id":"pool_scene","status":"active","normalized_path_glob":"data/x64/field/s84_m_pool_01/*.elixir.gz","domain":"water_visibility","priority":"critical","evidence_kind":"scene_container","keywords":"water","note":"x"}])

            ebm_source_payload = b"header s84_m_pool_01 item_swimsuit"
            ebm_target_payload = b"header s84_m_pool_01 item_swimsuit item_bathtowel_00"
            ebd_source_payload = b"AAAA\x05BBBB"
            ebd_target_payload = b"AAAA\x07BBBB"
            ebm_source = entry("event/event_jp/te99/event_message_te99_010.ebm", ebm_source_payload, "DATA/PACK01.PAK")
            ebm_target = entry("event/b1/event_jp/te99/event_message_te99_010.ebm", ebm_target_payload, "Data/PACK11.PAK")
            ebm_target["normalized_path"] = ebm_source["normalized_path"]
            ebm_target["comparison_key"] = ebm_source["comparison_key"]
            ebd_source = entry("event/event_jp/te99/event_te99_010.ebd", ebd_source_payload, "DATA/PACK01.PAK")
            ebd_target = entry("event/b1/event_jp/te99/event_te99_010.ebd", ebd_target_payload, "Data/PACK11.PAK")
            ebd_target["normalized_path"] = ebd_source["normalized_path"]
            ebd_target["comparison_key"] = ebd_source["comparison_key"]
            TOOL.atomic_json(inventories_dir / "br1_events.source.json", inventory("original", [ebm_source, ebd_source], pair="br1_events", side="source"))
            TOOL.atomic_json(inventories_dir / "br1_events.target.json", inventory("quartet", [ebm_target, ebd_target], pair="br1_events", side="target"))
            TOOL.atomic_json(differences_dir / "br1_events.json", {
                "source_archive_group":"br1_events",
                "entries":[
                    {"classification":"changed","scope_status":"in_scope","normalized_path":ebm_source["normalized_path"],"source":TOOL.file_ref(ebm_source),"target":TOOL.file_ref(ebm_target)},
                    {"classification":"changed","scope_status":"in_scope","normalized_path":ebd_source["normalized_path"],"source":TOOL.file_ref(ebd_source),"target":TOOL.file_ref(ebd_target)},
                ],
            })
            for side, item, payload in (
                ("source",ebm_source,ebm_source_payload),("target",ebm_target,ebm_target_payload),
                ("source",ebd_source,ebd_source_payload),("target",ebd_target,ebd_target_payload),
            ):
                out = TOOL.inventory_workspace_file(workspace, side, "br1_events", item["archive"], item["path"])
                out.parent.mkdir(parents=True, exist_ok=True)
                out.write_bytes(payload)
            output, summary = TOOL.collect_event_family_evidence(
                project_root=project, workspace_root=workspace, report_root=reports,
                effect_material_rules_file=rules, maximum_payload_bytes=1024*1024,
            )
            self.assertTrue(output.is_file())
            self.assertEqual(summary["event_message_families"], 1)
            self.assertGreater(summary["exact_scene_identifier_hit_rows"], 0)
            rows = TOOL.read_tsv(reports / TOOL.EVENT_FAMILY_EVIDENCE_DIR / "FOCUSED_EVENT_FAMILY_REVIEW.tsv")
            self.assertEqual(rows[0]["classification"], "exact_scene_binding_with_event_delta")
            self.assertIn("item_bathtowel_00", rows[0]["target_only_technical_identifiers"])


    def test_parse_event_record_stream_u16_total(self) -> None:
        payload = b"EBD0HEAD" + struct.pack("<HH4s", 0x101, 8, b"AAAA") + struct.pack("<HH4s", 0x202, 8, b"BBBB") + struct.pack("<HH4s", 0x303, 8, b"CCCC")
        layout = next(row for row in TOOL.EVENT_RECORD_LAYOUTS if row["layout_id"] == "u16_opcode_u16_total")
        parsed = TOOL.parse_event_record_stream(payload, start_offset=8, layout=layout)
        self.assertTrue(parsed["exact_eof"])
        self.assertEqual([row["opcode"] for row in parsed["records"]], [0x101, 0x202, 0x303])
        self.assertEqual(parsed["coverage"], 1.0)

    def test_infer_event_record_layouts_selects_common_layout(self) -> None:
        def payload(marker: bytes) -> bytes:
            return b"EBD0HEAD" + struct.pack("<HH4s", 0x101, 8, marker) + struct.pack("<HH4s", 0x202, 8, b"BBBB") + struct.pack("<HH4s", 0x303, 8, b"CCCC")
        samples = []
        for index in range(3):
            samples.append((f"event_{index}.ebd", "source", payload(bytes([65 + index]) * 4)))
            samples.append((f"event_{index}.ebd", "target", payload(bytes([70 + index]) * 4)))
        rows = TOOL.infer_event_record_layouts(samples, maximum_start_offset=16)
        selected = TOOL.choose_common_event_layout(rows, {"source":3, "target":3})
        self.assertIsNotNone(selected)
        self.assertEqual(selected["layout_id"], "u16_opcode_u16_total")
        self.assertEqual(selected["start_offset"], 8)

    def test_compare_event_record_sequences_marks_same_opcode_change(self) -> None:
        layout = next(row for row in TOOL.EVENT_RECORD_LAYOUTS if row["layout_id"] == "u16_opcode_u16_total")
        source = b"EBD0HEAD" + struct.pack("<HH4s", 0x101, 8, b"AAAA") + struct.pack("<HH4s", 0x202, 8, b"BBBB") + struct.pack("<HH4s", 0x303, 8, b"CCCC")
        target = b"EBD0HEAD" + struct.pack("<HH4s", 0x101, 8, b"AAAA") + struct.pack("<HH4s", 0x202, 8, b"ZZZZ") + struct.pack("<HH4s", 0x303, 8, b"CCCC")
        left = TOOL.parse_event_record_stream(source, start_offset=8, layout=layout)["records"]
        right = TOOL.parse_event_record_stream(target, start_offset=8, layout=layout)["records"]
        rows = TOOL.compare_event_record_sequences(left, right)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["classification"], "changed_record_same_opcode")
        self.assertEqual(rows[0]["source_opcode"], "0x00000202")

    def test_collect_event_opcode_evidence_writes_metadata_only_report(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            workspace = project / ".local/build/quartet_restoration"
            reports = project / ".local/reports/quartet_restoration"
            differences_dir = reports / "differences"
            family_dir = reports / TOOL.EVENT_FAMILY_EVIDENCE_DIR
            differences_dir.mkdir(parents=True)
            family_dir.mkdir(parents=True)
            TOOL.atomic_json(family_dir / "SUMMARY.json", {
                "type":"br_quartet_restoration_event_family_evidence_summary",
                "format_version":1,"tool_version":"0.0.20","exact_scene_identifier_hit_rows":0,
            })
            family_rows=[]
            diff_rows=[]
            for index in range(3):
                stem=f"te99_{index+1:03d}"
                ebd_path=f"event/event_jp/te99/event_{stem}.ebd"
                ebm_path=f"event/event_jp/te99/event_message_{stem}.ebm"
                source_payload=(b"EBD0HEAD" + struct.pack("<HH4s",0x101,8,b"AAAA") + struct.pack("<HH4s",0x202,8,bytes([66+index])*4) + struct.pack("<HH4s",0x303,8,b"CCCC"))
                target_payload=(b"EBD0HEAD" + struct.pack("<HH4s",0x101,8,b"AAAA") + struct.pack("<HH4s",0x202,8,bytes([76+index])*4) + struct.pack("<HH4s",0x303,8,b"CCCC"))
                source_item=entry(ebd_path,source_payload,"DATA/PACK01.PAK")
                target_item=entry("event/b1/"+ebd_path[len("event/"):],target_payload,"Data/PACK11.PAK")
                target_item["normalized_path"]=ebd_path
                target_item["comparison_key"]=ebd_path.casefold()
                diff_rows.append({"classification":"changed","scope_status":"in_scope","normalized_path":ebd_path,"source":TOOL.file_ref(source_item),"target":TOOL.file_ref(target_item)})
                family_rows.append({"event_family_id":f"f{index}","event_message_path":ebm_path,"event_data_path":ebd_path,"event_message_classification":"identical","event_data_classification":"changed"})
                for side,item,payload in (("source",source_item,source_payload),("target",target_item,target_payload)):
                    out=TOOL.inventory_workspace_file(workspace,side,"br1_events",item["archive"],item["path"])
                    out.parent.mkdir(parents=True,exist_ok=True)
                    out.write_bytes(payload)
            TOOL.atomic_json(differences_dir / "br1_events.json", {"source_archive_group":"br1_events","entries":diff_rows})
            TOOL.write_tsv(family_dir / "EVENT_FAMILY_PAIRS.tsv", ["event_family_id","event_message_path","event_data_path","event_message_classification","event_data_classification"], family_rows)
            output,summary=TOOL.collect_event_opcode_evidence(project_root=project,workspace_root=workspace,report_root=reports,maximum_event_bytes=1024*1024,discovery_files=16,maximum_start_offset=16)
            self.assertTrue(output.is_file())
            self.assertEqual(summary["selected_common_layout"]["layout_id"],"u16_opcode_u16_total")
            self.assertEqual(summary["record_delta_rows"],3)
            focused=TOOL.read_tsv(reports / TOOL.EVENT_OPCODE_EVIDENCE_DIR / "FOCUSED_EVENT_OPCODE_REVIEW.tsv")
            self.assertEqual(len(focused),3)
            self.assertTrue(all(row["classification"]=="compact_control_delta_with_identical_message" for row in focused))


    def test_parse_ebd_header_schema_recognizes_unaligned_name_description_fields(self) -> None:
        description = "説明".encode("cp932") + b"\0"
        payload = struct.pack("<II", 3, 0) + struct.pack("<I", 5) + b"name\0" + struct.pack("<I", len(description)) + description + struct.pack("<I", 7)
        header = TOOL.parse_ebd_header_schema(payload)
        self.assertEqual(header["declared_count"], 3)
        self.assertEqual(header["reserved_u32"], 0)
        self.assertEqual(header["first_field_identifier"], "name")
        self.assertEqual(header["second_field_class"], "cp932_text_redacted")
        self.assertEqual(header["header_end"], 26)
        self.assertEqual(header["classification"], "observed_ebd_name_description_header")

    def test_choose_common_event_layout_rejects_partial_nonterminating_parse(self) -> None:
        rows = [
            {"layout_id":"u16_opcode_u16_payload","start_offset":2,"side":"source","file_count":68,"median_coverage":0.95,"exact_eof_ratio":0.0,"hypothesis_score":49.0},
            {"layout_id":"u16_opcode_u16_payload","start_offset":2,"side":"target","file_count":61,"median_coverage":0.96,"exact_eof_ratio":0.0,"hypothesis_score":44.0},
        ]
        self.assertIsNone(TOOL.choose_common_event_layout(rows, {"source":256,"target":256}))

    def test_collect_event_schema_evidence_rejects_old_opcode_and_reports_technical_delta(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            workspace = project / ".local/build/quartet_restoration"
            reports = project / ".local/reports/quartet_restoration"
            differences_dir = reports / "differences"
            family_dir = reports / TOOL.EVENT_FAMILY_EVIDENCE_DIR
            opcode_dir = reports / TOOL.EVENT_OPCODE_EVIDENCE_DIR
            differences_dir.mkdir(parents=True)
            family_dir.mkdir(parents=True)
            opcode_dir.mkdir(parents=True)

            TOOL.atomic_json(family_dir / "SUMMARY.json", {
                "type":"br_quartet_restoration_event_family_evidence_summary",
                "format_version":1,"tool_version":"0.0.20","exact_scene_identifier_hit_rows":0,
            })
            TOOL.atomic_json(opcode_dir / "SUMMARY.json", {
                "type":"br_quartet_restoration_event_opcode_evidence_summary",
                "format_version":1,"tool_version":"0.0.21","record_delta_rows":3,
                "discovery_sample_files_per_side":{"source":4,"target":4},
                "selected_common_layout":{"layout_id":"u16_opcode_u16_payload","start_offset":2},
            })
            TOOL.write_tsv(opcode_dir / "EBD_RECORD_LAYOUT_HYPOTHESES.tsv", [
                "layout_id","start_offset","side","file_count","exact_eof_files","median_coverage",
                "median_record_count","median_trailing_bytes","exact_eof_ratio","first_sample_paths",
                "hypothesis_score","review_status",
            ], [
                {"layout_id":"u16_opcode_u16_payload","start_offset":2,"side":"source","file_count":1,"exact_eof_files":0,"median_coverage":0.95,"median_record_count":3,"median_trailing_bytes":5,"exact_eof_ratio":0.0,"first_sample_paths":"x","hypothesis_score":1,"review_status":"x"},
                {"layout_id":"u16_opcode_u16_payload","start_offset":2,"side":"target","file_count":1,"exact_eof_files":0,"median_coverage":0.96,"median_record_count":3,"median_trailing_bytes":5,"exact_eof_ratio":0.0,"first_sample_paths":"x","hypothesis_score":1,"review_status":"x"},
            ])

            def lp(raw: bytes) -> bytes:
                return struct.pack("<I", len(raw)) + raw
            description = "説明".encode("cp932") + b"\0"
            source_payload = struct.pack("<II", 2, 0) + lp(b"name\0") + lp(description) + struct.pack("<I", 1) + lp(b"costume\0") + lp(b"pc00_rfl\0")
            target_payload = struct.pack("<II", 3, 0) + lp(b"name\0") + lp(description) + struct.pack("<I", 1) + lp(b"costume\0") + lp(b"pc00_rfl_w\0")
            ebd_path = "event/event_jp/te99/event_te99_010.ebd"
            ebm_path = "event/event_jp/te99/event_message_te99_010.ebm"
            source_item = entry(ebd_path, source_payload, "DATA/PACK01.PAK")
            target_item = entry("event/b1/event_jp/te99/event_te99_010.ebd", target_payload, "Data/PACK11.PAK")
            target_item["normalized_path"] = ebd_path
            target_item["comparison_key"] = ebd_path.casefold()
            TOOL.atomic_json(differences_dir / "br1_events.json", {
                "source_archive_group":"br1_events",
                "entries":[{"classification":"changed","scope_status":"in_scope","normalized_path":ebd_path,"source":TOOL.file_ref(source_item),"target":TOOL.file_ref(target_item)}],
            })
            TOOL.write_tsv(family_dir / "EVENT_FAMILY_PAIRS.tsv", [
                "event_family_id","event_message_path","event_data_path","event_message_classification","event_data_classification",
            ], [{"event_family_id":"f1","event_message_path":ebm_path,"event_data_path":ebd_path,"event_message_classification":"identical","event_data_classification":"changed"}])
            for side, item, payload in (("source",source_item,source_payload),("target",target_item,target_payload)):
                out = TOOL.inventory_workspace_file(workspace, side, "br1_events", item["archive"], item["path"])
                out.parent.mkdir(parents=True, exist_ok=True)
                out.write_bytes(payload)

            output, summary = TOOL.collect_event_schema_evidence(
                project_root=project, workspace_root=workspace, report_root=reports,
                maximum_event_bytes=1024*1024, maximum_token_length=1024,
            )
            self.assertTrue(output.is_file())
            self.assertTrue(summary["prior_opcode_layout_rejected"])
            self.assertEqual(summary["prior_opcode_delta_rows_superseded"], 3)
            correction = TOOL.read_tsv(reports / TOOL.EVENT_SCHEMA_EVIDENCE_DIR / "EVENT_OPCODE_HYPOTHESIS_CORRECTION.tsv")
            self.assertEqual(correction[0]["classification"], "rejected_spurious_partial_parse")
            focused = TOOL.read_tsv(reports / TOOL.EVENT_SCHEMA_EVIDENCE_DIR / "FOCUSED_EVENT_SCHEMA_REVIEW.tsv")
            self.assertEqual(len(focused), 1)
            self.assertEqual(focused[0]["classification"], "focused_presentation_identifier_schema_delta")
            self.assertIn("pc00_rfl_w", focused[0]["target_only_technical_identifiers"])


    def test_profile_ebd_post_header_words_detects_common_tagged_prefix(self) -> None:
        words = [15, 0x75400009, 0x77000001, 1, 0x7540000A, 0x77000004, 2, 0x74200011]
        payload = b"X" * 26 + struct.pack("<8I", *words)
        profile = TOOL.profile_ebd_post_header_words(payload, 26)
        self.assertEqual(profile["family"], "common_tagged_prefix_7540_7700")
        self.assertEqual(profile["tag_count"], 5)
        self.assertEqual(profile["atoms"][0]["tag_high_u16_hex"], "0x7540")
        self.assertEqual(profile["atoms"][0]["tag_operand_u16"], 9)

    def test_profile_ebd_post_header_words_detects_minimal_stub(self) -> None:
        words = [1, 0x7F000000, 1, 1, 0x7F000000, 1]
        payload = b"X" * 26 + struct.pack("<6I", *words)
        profile = TOOL.profile_ebd_post_header_words(payload, 26)
        self.assertEqual(profile["family"], "minimal_dual_7f_stub")
        self.assertEqual(profile["sentinel_count"], 2)

    def test_compare_ebd_tag_atoms_detects_tag_change(self) -> None:
        source_payload = b"X" * 26 + struct.pack("<5I", 1, 0x75400009, 2, 0x74200011, 3)
        target_payload = b"X" * 26 + struct.pack("<5I", 1, 0x75400009, 2, 0x74200012, 3)
        source = TOOL.profile_ebd_post_header_words(source_payload, 26)["atoms"]
        target = TOOL.profile_ebd_post_header_words(target_payload, 26)["atoms"]
        rows = TOOL.compare_ebd_tag_atoms(source, target)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["classification"], "changed_tagged_atoms")
        self.assertIn("0x74200011", rows[0]["source_tag_values"])
        self.assertIn("0x74200012", rows[0]["target_tag_values"])

    def test_collect_event_tag_grammar_evidence_corrects_free_scan_noise(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            workspace = project / ".local/build/quartet_restoration"
            reports = project / ".local/reports/quartet_restoration"
            differences_dir = reports / "differences"
            family_dir = reports / TOOL.EVENT_FAMILY_EVIDENCE_DIR
            schema_dir = reports / TOOL.EVENT_SCHEMA_EVIDENCE_DIR
            differences_dir.mkdir(parents=True)
            family_dir.mkdir(parents=True)
            schema_dir.mkdir(parents=True)
            TOOL.atomic_json(family_dir / "SUMMARY.json", {
                "type":"br_quartet_restoration_event_family_evidence_summary",
                "format_version":1,"tool_version":"0.0.20",
            })
            TOOL.atomic_json(schema_dir / "SUMMARY.json", {
                "type":"br_quartet_restoration_event_schema_evidence_summary",
                "format_version":1,"tool_version":"0.0.22",
            })
            TOOL.write_tsv(schema_dir / "EBD_LENGTH_PREFIXED_TOKENS.tsv", [
                "normalized_path","side","prefix_offset","technical_identifier"
            ], [
                {"normalized_path":"x","side":"source","prefix_offset":0,"technical_identifier":""},
                {"normalized_path":"x","side":"source","prefix_offset":40,"technical_identifier":"d"},
            ])
            TOOL.write_tsv(schema_dir / "EBD_SCHEMA_TOKEN_DELTAS.tsv", ["normalized_path"], [{"normalized_path":"x"}])
            TOOL.write_tsv(schema_dir / "FOCUSED_EVENT_SCHEMA_REVIEW.tsv", ["normalized_path"], [{"normalized_path":"x"}])

            def lp(raw: bytes) -> bytes:
                return struct.pack("<I", len(raw)) + raw
            description = "説明".encode("cp932") + b"\0"
            prefix = struct.pack("<II", 3, 0) + lp(b"name\0") + lp(description)
            source_words = [15, 0x75400009, 0x77000001, 1, 0x7540000A, 0x77000004, 2, 0x74200011, 3]
            target_words = [15, 0x75400009, 0x77000001, 1, 0x7540000A, 0x77000004, 2, 0x74200012, 3]
            source_payload = prefix + struct.pack("<9I", *source_words)
            target_payload = prefix + struct.pack("<9I", *target_words)
            ebd_path = "event/event_jp/te99/event_te99_010.ebd"
            ebm_path = "event/event_jp/te99/event_message_te99_010.ebm"
            source_item = entry(ebd_path, source_payload, "DATA/PACK01.PAK")
            target_item = entry("event/b1/event_jp/te99/event_te99_010.ebd", target_payload, "Data/PACK11.PAK")
            target_item["normalized_path"] = ebd_path
            target_item["comparison_key"] = ebd_path.casefold()
            TOOL.atomic_json(differences_dir / "br1_events.json", {
                "source_archive_group":"br1_events",
                "entries":[{"classification":"changed","scope_status":"in_scope","normalized_path":ebd_path,"source":TOOL.file_ref(source_item),"target":TOOL.file_ref(target_item)}],
            })
            TOOL.write_tsv(family_dir / "EVENT_FAMILY_PAIRS.tsv", [
                "event_family_id","event_message_path","event_data_path","event_message_classification","event_data_classification",
            ], [{"event_family_id":"f1","event_message_path":ebm_path,"event_data_path":ebd_path,"event_message_classification":"identical","event_data_classification":"changed"}])
            for side, item, payload in (("source",source_item,source_payload),("target",target_item,target_payload)):
                out = TOOL.inventory_workspace_file(workspace, side, "br1_events", item["archive"], item["path"])
                out.parent.mkdir(parents=True, exist_ok=True)
                out.write_bytes(payload)

            output, summary = TOOL.collect_event_tag_grammar_evidence(
                project_root=project, workspace_root=workspace, report_root=reports,
                maximum_event_bytes=1024 * 1024, maximum_words=1000,
            )
            self.assertTrue(output.is_file())
            self.assertEqual(summary["stage18_offset_zero_false_token_rows"], 1)
            self.assertEqual(summary["stage18_single_character_identifier_rows"], 1)
            self.assertEqual(summary["changed_pairs_with_tag_deltas"], 1)
            focused = TOOL.read_tsv(reports / TOOL.EVENT_TAG_GRAMMAR_EVIDENCE_DIR / "FOCUSED_EVENT_TAG_GRAMMAR_REVIEW.tsv")
            self.assertEqual(len(focused), 1)
            self.assertEqual(focused[0]["classification"], "compact_tag_grammar_delta_with_identical_message")


    def test_classify_event_tag_migration_signature_uses_cross_family_support(self) -> None:
        broad = TOOL.classify_event_tag_migration_signature(
            file_count=60, route_family_count=9, changed_pair_count=658,
            minimum_broad_files=32, minimum_broad_support_ratio=0.08,
            minimum_broad_route_families=8, minimum_recurrent_files=12,
            minimum_recurrent_route_families=2,
        )
        recurrent = TOOL.classify_event_tag_migration_signature(
            file_count=40, route_family_count=3, changed_pair_count=658,
            minimum_broad_files=32, minimum_broad_support_ratio=0.08,
            minimum_broad_route_families=8, minimum_recurrent_files=12,
            minimum_recurrent_route_families=2,
        )
        rare = TOOL.classify_event_tag_migration_signature(
            file_count=3, route_family_count=1, changed_pair_count=658,
            minimum_broad_files=32, minimum_broad_support_ratio=0.08,
            minimum_broad_route_families=8, minimum_recurrent_files=12,
            minimum_recurrent_route_families=2,
        )
        self.assertEqual(broad, "broad_schema_migration_candidate")
        self.assertEqual(recurrent, "recurrent_schema_delta_candidate")
        self.assertEqual(rare, "rare_event_delta_candidate")

    def test_build_ebd_sentinel_frames_preserves_trailing_frame(self) -> None:
        rows = [
            {"atom_index":0,"tag_value_hex":"0x75400009","atom_signature_sha256":"a"},
            {"atom_index":1,"tag_value_hex":"0x7f000000","atom_signature_sha256":"b"},
            {"atom_index":2,"tag_value_hex":"0x750000a2","atom_signature_sha256":"c"},
        ]
        frames = TOOL.build_ebd_sentinel_frames(rows)
        self.assertEqual(len(frames), 2)
        self.assertTrue(frames[0]["ends_with_7f_sentinel"])
        self.assertFalse(frames[1]["ends_with_7f_sentinel"])
        self.assertEqual(frames[1]["tag_values_preview"], "0x750000a2")
        deltas = TOOL.compare_ebd_sentinel_frames(frames[:1], frames)
        self.assertEqual(deltas[0]["classification"], "sentinel_frames_added_in_quartet")

    def test_collect_event_tag_migration_evidence_filters_broad_transform(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            reports = project / ".local/reports/quartet_restoration"
            grammar = reports / TOOL.EVENT_TAG_GRAMMAR_EVIDENCE_DIR
            families = reports / TOOL.EVENT_FAMILY_EVIDENCE_DIR
            grammar.mkdir(parents=True)
            families.mkdir(parents=True)
            TOOL.atomic_json(grammar / "SUMMARY.json", {
                "type":"br_quartet_restoration_event_tag_grammar_evidence_summary",
                "format_version":1,"tool_version":"0.0.23","changed_event_pairs":2,
            })
            TOOL.atomic_json(families / "SUMMARY.json", {
                "type":"br_quartet_restoration_event_family_evidence_summary",
                "format_version":1,"tool_version":"0.0.20",
            })
            paths = ["event/event_jp/aa01/event_aa01_010.ebd", "event/event_jp/bb01/event_bb01_010.ebd"]
            TOOL.write_tsv(families / "EVENT_FAMILY_PAIRS.tsv", [
                "event_data_path","event_message_path","event_message_classification"
            ], [
                {"event_data_path":paths[0],"event_message_path":"event/event_jp/aa01/event_message_aa01_010.ebm","event_message_classification":"identical"},
                {"event_data_path":paths[1],"event_message_path":"event/event_jp/bb01/event_message_bb01_010.ebm","event_message_classification":"identical"},
            ])
            delta_fields = [
                "normalized_path","sequence_tag","source_atom_start","source_atom_end","target_atom_start","target_atom_end",
                "source_atom_count","target_atom_count","source_first_word_index","target_first_word_index",
                "source_tag_values","target_tag_values","source_atom_sequence_sha256","target_atom_sequence_sha256",
                "classification","review_status",
            ]
            delta_rows = []
            for index, event_path in enumerate(paths):
                delta_rows.append({
                    "normalized_path":event_path,"sequence_tag":"insert","source_atom_count":0,"target_atom_count":1,
                    "source_tag_values":"","target_tag_values":"0x750000a2","source_atom_sequence_sha256":"empty",
                    "target_atom_sequence_sha256":"a2","source_first_word_index":"","target_first_word_index":5,
                })
                if index == 1:
                    delta_rows.append({
                        "normalized_path":event_path,"sequence_tag":"insert","source_atom_count":0,"target_atom_count":1,
                        "source_tag_values":"","target_tag_values":"0x750000ff","source_atom_sequence_sha256":"empty",
                        "target_atom_sequence_sha256":"ff","source_first_word_index":"","target_first_word_index":7,
                    })
            TOOL.write_tsv(grammar / "EBD_TAG_ATOM_DELTAS.tsv", delta_fields, delta_rows)
            atom_fields = [
                "normalized_path","side","atom_index","word_index","byte_offset","tag_value","tag_value_hex",
                "tag_high_u16_hex","tag_operand_u16","gap_words_to_next_tag","small_scalar_values","small_scalar_count",
                "opaque_gap_word_count","is_7f_sentinel_candidate","atom_signature_sha256","review_status",
            ]
            atom_rows = []
            for event_path in paths:
                for side, tags in (("source",["0x75400009","0x7f000000"]),("target",["0x75400009","0x750000a2","0x7f000000"])):
                    for atom_index, tag in enumerate(tags):
                        atom_rows.append({
                            "normalized_path":event_path,"side":side,"atom_index":atom_index,"word_index":atom_index,
                            "tag_value_hex":tag,"gap_words_to_next_tag":0,"small_scalar_values":"",
                            "opaque_gap_word_count":0,"atom_signature_sha256":f"{side}-{tag}-{atom_index}",
                        })
            TOOL.write_tsv(grammar / "EBD_TAG_ATOMS.tsv", atom_fields, atom_rows)
            TOOL.write_tsv(grammar / "EBD_POST_HEADER_PROFILES.tsv", [
                "normalized_path","side","declared_count","sentinel_7f_count"
            ], [
                {"normalized_path":event_path,"side":side,"declared_count":1,"sentinel_7f_count":1}
                for event_path in paths for side in ("source","target")
            ])
            TOOL.write_tsv(grammar / "FOCUSED_EVENT_TAG_GRAMMAR_REVIEW.tsv", [
                "normalized_path","classification"
            ], [{"normalized_path":event_path,"classification":"compact_tag_grammar_delta_with_identical_message"} for event_path in paths])

            output, summary = TOOL.collect_event_tag_migration_evidence(
                project_root=project, report_root=reports,
                minimum_broad_files=2, minimum_broad_support_ratio=0.0,
                minimum_broad_route_families=2, minimum_recurrent_files=2,
                minimum_recurrent_route_families=2,
            )
            self.assertTrue(output.is_file())
            self.assertEqual(summary["broad_schema_migration_signature_rows"], 1)
            self.assertEqual(summary["broad_schema_migration_only_files"], 1)
            self.assertEqual(summary["files_with_rare_residual"], 1)
            self.assertEqual(summary["identical_message_files_with_rare_residual"], 1)
            focused = TOOL.read_tsv(reports / TOOL.EVENT_TAG_MIGRATION_EVIDENCE_DIR / "FOCUSED_EVENT_TAG_RESIDUAL_REVIEW.tsv")
            self.assertEqual(len(focused), 1)
            self.assertEqual(focused[0]["normalized_path"], paths[1])
            residual = TOOL.read_tsv(reports / TOOL.EVENT_TAG_MIGRATION_EVIDENCE_DIR / "RESIDUAL_EVENT_TAG_DELTAS.tsv")
            self.assertEqual(residual[0]["target_tag_values"], "0x750000ff")


    def test_scan_event_scene_cues_detects_cp932_without_exporting_literal(self) -> None:
        rules = [{
            "rule_id":"shower","domain":"shower","priority":"critical","cue_label":"shower",
            "literal":"シャワー","literal_sha256":TOOL.sha256_text("シャワー"),
            "literal_char_count":4,"encodings":["cp932","utf-8"],"note":"",
        }]
        payload = b"HEAD" + "シャワーへ行こう。シャワー".encode("cp932")
        rows = TOOL.scan_event_scene_cues(payload, rules)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["encoding"], "cp932")
        self.assertEqual(rows[0]["hit_count"], 2)
        self.assertNotIn("literal", rows[0])

    def test_classify_event_scene_cue_frequency_uses_corpus_and_route_support(self) -> None:
        self.assertEqual(TOOL.classify_event_scene_cue_frequency(
            file_count=150, route_family_count=12, total_families=1000,
            minimum_broad_files=32, minimum_broad_ratio=0.08,
            minimum_broad_route_families=8, minimum_recurrent_files=8,
            minimum_recurrent_route_families=2,
        ), "broad_dialogue_cue")
        self.assertEqual(TOOL.classify_event_scene_cue_frequency(
            file_count=12, route_family_count=3, total_families=1000,
            minimum_broad_files=32, minimum_broad_ratio=0.08,
            minimum_broad_route_families=8, minimum_recurrent_files=8,
            minimum_recurrent_route_families=2,
        ), "recurrent_scene_cue")
        self.assertEqual(TOOL.classify_event_scene_cue_frequency(
            file_count=2, route_family_count=1, total_families=1000,
            minimum_broad_files=32, minimum_broad_ratio=0.08,
            minimum_broad_route_families=8, minimum_recurrent_files=8,
            minimum_recurrent_route_families=2,
        ), "rare_scene_cue")

    def test_collect_event_scene_cue_evidence_correlates_compound_cue_without_dialogue(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            workspace = project / ".local/build/quartet_restoration"
            reports = project / ".local/reports/quartet_restoration"
            differences = reports / "differences"
            migration = reports / TOOL.EVENT_TAG_MIGRATION_EVIDENCE_DIR
            families = reports / TOOL.EVENT_FAMILY_EVIDENCE_DIR
            differences.mkdir(parents=True)
            migration.mkdir(parents=True)
            families.mkdir(parents=True)
            TOOL.atomic_json(migration / "SUMMARY.json", {
                "type":"br_quartet_restoration_event_tag_migration_evidence_summary",
                "format_version":1,"tool_version":"0.0.24","files_with_rare_residual":2,
            })
            TOOL.atomic_json(families / "SUMMARY.json", {
                "type":"br_quartet_restoration_event_family_evidence_summary",
                "format_version":1,"tool_version":"0.0.20","event_message_families":2,
            })
            cue_rules = project / "cue_rules.tsv"
            TOOL.write_tsv(cue_rules, [
                "rule_id","status","domain","priority","cue_label","literal","encodings","note",
            ], [
                {"rule_id":"shower","status":"active","domain":"shower","priority":"critical","cue_label":"shower","literal":"シャワー","encodings":"cp932,utf-8","note":""},
                {"rule_id":"swimsuit","status":"active","domain":"costume_or_coverage","priority":"critical","cue_label":"swimsuit","literal":"水着","encodings":"cp932,utf-8","note":""},
            ])
            family_rows=[]
            diff_rows=[]
            focused=[]
            residual=[]
            cases=[
                ("ce99","010","シャワーの後で水着に着替える。"),
                ("ce99","020","普通の会話です。"),
            ]
            for family_id, number, text in cases:
                ebm_path=f"event/event_jp/{family_id}/event_message_{family_id}_{number}.ebm"
                ebd_path=f"event/event_jp/{family_id}/event_{family_id}_{number}.ebd"
                payload=b"EBM0"+text.encode("cp932")
                source_item=entry(ebm_path,payload,"DATA/PACK01.PAK")
                target_item=entry(ebm_path,payload,"Data/PACK11.PAK")
                diff_rows.append({
                    "classification":"identical","scope_status":"in_scope","normalized_path":ebm_path,
                    "source":TOOL.file_ref(source_item),"target":TOOL.file_ref(target_item),
                })
                family_rows.append({
                    "event_family_id":family_id+number,"event_message_path":ebm_path,
                    "event_data_path":ebd_path,"event_message_classification":"identical",
                    "event_data_classification":"changed",
                })
                focused.append({
                    "normalized_path":ebd_path,"event_message_path":ebm_path,
                    "event_message_classification":"identical","stage19_classification":"compact",
                    "total_tag_delta_regions":1,"broad_migration_regions":0,"recurrent_schema_regions":0,
                    "rare_residual_regions":1,"broad_migration_atom_span":0,"recurrent_schema_atom_span":0,
                    "rare_residual_atom_span":1,"classification":"rare_event_tag_residual_with_identical_message",
                    "review_priority":"high","review_status":"test",
                })
                residual.append({
                    "normalized_path":ebd_path,"event_message_path":ebm_path,
                    "event_message_classification":"identical","migration_classification":"rare_event_delta_candidate",
                    "signature_file_count":1,"signature_route_family_count":1,"sequence_tag":"replace",
                    "source_atom_count":1,"target_atom_count":1,"source_tag_values":"0x75000001",
                    "target_tag_values":"0x75000002","source_first_word_index":10,"target_first_word_index":10,
                    "source_atom_sequence_sha256":"a","target_atom_sequence_sha256":"b","review_status":"test",
                })
                for side,item in (("source",source_item),("target",target_item)):
                    out=TOOL.inventory_workspace_file(workspace,side,"br1_events",item["archive"],item["path"])
                    out.parent.mkdir(parents=True,exist_ok=True)
                    out.write_bytes(payload)
            TOOL.atomic_json(differences / "br1_events.json", {
                "source_archive_group":"br1_events","entries":diff_rows,
            })
            TOOL.write_tsv(families / "EVENT_FAMILY_PAIRS.tsv", [
                "event_family_id","event_message_path","event_data_path","event_message_classification","event_data_classification",
            ], family_rows)
            TOOL.write_tsv(migration / "FOCUSED_EVENT_TAG_RESIDUAL_REVIEW.tsv", [
                "normalized_path","event_message_path","event_message_classification","stage19_classification",
                "total_tag_delta_regions","broad_migration_regions","recurrent_schema_regions","rare_residual_regions",
                "broad_migration_atom_span","recurrent_schema_atom_span","rare_residual_atom_span",
                "classification","review_priority","review_status",
            ], focused)
            TOOL.write_tsv(migration / "RESIDUAL_EVENT_TAG_DELTAS.tsv", [
                "normalized_path","event_message_path","event_message_classification","migration_classification",
                "signature_file_count","signature_route_family_count","sequence_tag","source_atom_count","target_atom_count",
                "source_tag_values","target_tag_values","source_first_word_index","target_first_word_index",
                "source_atom_sequence_sha256","target_atom_sequence_sha256","review_status",
            ], residual)
            output, summary = TOOL.collect_event_scene_cue_evidence(
                project_root=project, workspace_root=workspace, report_root=reports,
                cue_rules_file=cue_rules, maximum_payload_bytes=1024*1024,
                minimum_broad_files=2, minimum_broad_ratio=0.5,
                minimum_broad_route_families=2, minimum_recurrent_files=2,
                minimum_recurrent_route_families=2,
            )
            self.assertTrue(output.is_file())
            self.assertEqual(summary["event_message_families_scanned"],2)
            self.assertEqual(summary["focused_residual_events_with_any_cue"],1)
            self.assertEqual(summary["focused_residual_events_with_compound_cues"],1)
            review=TOOL.read_tsv(reports / TOOL.EVENT_SCENE_CUE_EVIDENCE_DIR / "FOCUSED_PRESENTATION_EVENT_REVIEW.tsv")
            self.assertEqual(len(review),1)
            self.assertEqual(review[0]["review_priority"],"critical")
            self.assertEqual(review[0]["compound_location_and_presentation_cue"],"True")
            for report_file in (reports / TOOL.EVENT_SCENE_CUE_EVIDENCE_DIR).glob("*.tsv"):
                text=report_file.read_text(encoding="utf-8")
                self.assertNotIn("シャワーの後で",text)
                self.assertNotIn("水着に着替える",text)


    def test_parse_event_sequence_identity_extracts_route_and_slot(self) -> None:
        row = TOOL.parse_event_sequence_identity("event/event_jp/fo14/event_fo14_090.ebd")
        self.assertEqual(row["route_family"], "fo14")
        self.assertEqual(row["route_stem"], "fo")
        self.assertEqual(row["route_index"], 14)
        self.assertEqual(row["event_slot"], 90)
        self.assertEqual(row["classification"], "parsed_event_sequence_name")

    def test_classify_presentation_delta_shape_requires_repetition_or_singleton(self) -> None:
        classification, _, enrichment = TOOL.classify_presentation_delta_shape(
            cue_file_count=6, identical_cue_file_count=6, all_file_count=9,
            cue_event_count=23, all_residual_event_count=186,
        )
        self.assertEqual(classification, "presentation_repeated_delta_shape_candidate")
        self.assertGreater(enrichment, 1.5)
        singleton, _, _ = TOOL.classify_presentation_delta_shape(
            cue_file_count=1, identical_cue_file_count=1, all_file_count=1,
            cue_event_count=23, all_residual_event_count=186,
        )
        self.assertEqual(singleton, "presentation_single_scene_delta_shape_candidate")

    def test_collect_event_presentation_cohort_evidence_finds_repeated_slot(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            reports = project / ".local/reports/quartet_restoration"
            cue_dir = reports / TOOL.EVENT_SCENE_CUE_EVIDENCE_DIR
            migration_dir = reports / TOOL.EVENT_TAG_MIGRATION_EVIDENCE_DIR
            family_dir = reports / TOOL.EVENT_FAMILY_EVIDENCE_DIR
            cue_dir.mkdir(parents=True)
            migration_dir.mkdir(parents=True)
            family_dir.mkdir(parents=True)
            TOOL.atomic_json(cue_dir / "SUMMARY.json", {
                "type":"br_quartet_restoration_event_scene_cue_evidence_summary",
                "format_version":1,"tool_version":"0.0.25",
            })
            TOOL.atomic_json(migration_dir / "SUMMARY.json", {
                "type":"br_quartet_restoration_event_tag_migration_evidence_summary",
                "format_version":1,"tool_version":"0.0.24",
            })
            TOOL.atomic_json(family_dir / "SUMMARY.json", {
                "type":"br_quartet_restoration_event_family_evidence_summary",
                "format_version":1,"tool_version":"0.0.20",
            })
            paths = [
                "event/event_jp/fo03/event_fo03_090.ebd",
                "event/event_jp/fo05/event_fo05_090.ebd",
                "event/event_jp/fo10/event_fo10_090.ebd",
                "event/event_jp/te02/event_te02_180.ebd",
                "event/event_jp/te02/event_te02_220.ebd",
                "event/event_jp/ce01/event_ce01_010.ebd",
            ]
            family_rows=[]
            correlation_rows=[]
            focused_cue_rows=[]
            migration_focused=[]
            residual_rows=[]
            for index, path in enumerate(paths):
                identity=TOOL.parse_event_sequence_identity(path)
                family_id=identity["route_family"]
                slot=int(identity["event_slot"])
                ebm=f"event/event_jp/{family_id}/event_message_{family_id}_{slot:03d}.ebm"
                family_rows.append({
                    "event_data_path":path,"event_message_path":ebm,
                    "event_message_classification":"identical",
                })
                migration_focused.append({
                    "normalized_path":path,"event_message_path":ebm,"event_message_classification":"identical",
                    "rare_residual_regions":1,"rare_residual_atom_span":1,
                })
                if index < 3:
                    cue_domains="bath_or_hot_spring"
                    cue_rule_ids="bath_ofuro"
                elif index < 5:
                    cue_domains="shower"
                    cue_rule_ids="shower"
                else:
                    cue_domains=""
                    cue_rule_ids=""
                correlation={
                    "normalized_path":path,"event_message_path":ebm,"event_message_classification":"identical",
                    "rare_residual_regions":1,"rare_residual_atom_span":1,"residual_delta_rows":1,
                    "cue_rule_ids":cue_rule_ids,"cue_domains":cue_domains,"cue_frequency_classes":"rare_scene_cue" if cue_domains else "",
                    "cue_side_relations":"both_identical_payload" if cue_domains else "","cue_hit_count":1 if cue_domains else 0,
                    "location_cue_domains":cue_domains,"presentation_cue_domains":"",
                    "compound_location_and_presentation_cue":False,"classification":"test","review_priority":"high","review_status":"test",
                }
                correlation_rows.append(correlation)
                if cue_domains:
                    focused_cue_rows.append(correlation)
                if index < 3:
                    target="0x74100014"
                    source=""
                    sequence="insert"
                elif index < 5:
                    target=""
                    source="0x75100001;0x75000012;0x7500002c;0x70000001"
                    sequence="delete"
                else:
                    target="0x750000ff"
                    source=""
                    sequence="insert"
                residual_rows.append({
                    "normalized_path":path,"event_message_path":ebm,"event_message_classification":"identical",
                    "migration_classification":"rare_event_delta_candidate","signature_file_count":1,
                    "signature_route_family_count":1,"sequence_tag":sequence,"source_atom_count":0 if sequence=="insert" else 4,
                    "target_atom_count":1 if sequence=="insert" else 0,"source_tag_values":source,"target_tag_values":target,
                    "source_first_word_index":10,"target_first_word_index":10,
                    "source_atom_sequence_sha256":"source","target_atom_sequence_sha256":"target","review_status":"test",
                })
            # A recurrent row outside the focused rare-residual queue must not
            # expand the denominator or shape support.
            residual_rows.append({
                "normalized_path":"event/event_jp/zz01/event_zz01_010.ebd",
                "event_message_path":"event/event_jp/zz01/event_message_zz01_010.ebm",
                "event_message_classification":"identical","migration_classification":"recurrent_schema_delta_candidate",
                "sequence_tag":"insert","source_atom_count":0,"target_atom_count":1,"source_tag_values":"",
                "target_tag_values":"0x74100014","source_atom_sequence_sha256":"source","target_atom_sequence_sha256":"target",
            })
            TOOL.write_tsv(family_dir / "EVENT_FAMILY_PAIRS.tsv", [
                "event_data_path","event_message_path","event_message_classification",
            ], family_rows)
            correlation_fields=[
                "normalized_path","event_message_path","event_message_classification","rare_residual_regions",
                "rare_residual_atom_span","residual_delta_rows","cue_rule_ids","cue_domains","cue_frequency_classes",
                "cue_side_relations","cue_hit_count","location_cue_domains","presentation_cue_domains",
                "compound_location_and_presentation_cue","classification","review_priority","review_status",
            ]
            TOOL.write_tsv(cue_dir / "EVENT_RESIDUAL_CUE_CORRELATION.tsv", correlation_fields, correlation_rows)
            TOOL.write_tsv(cue_dir / "FOCUSED_PRESENTATION_EVENT_REVIEW.tsv", correlation_fields, focused_cue_rows)
            TOOL.write_tsv(migration_dir / "FOCUSED_EVENT_TAG_RESIDUAL_REVIEW.tsv", [
                "normalized_path","event_message_path","event_message_classification","rare_residual_regions","rare_residual_atom_span",
            ], migration_focused)
            TOOL.write_tsv(migration_dir / "RESIDUAL_EVENT_TAG_DELTAS.tsv", [
                "normalized_path","event_message_path","event_message_classification","migration_classification",
                "signature_file_count","signature_route_family_count","sequence_tag","source_atom_count","target_atom_count",
                "source_tag_values","target_tag_values","source_first_word_index","target_first_word_index",
                "source_atom_sequence_sha256","target_atom_sequence_sha256","review_status",
            ], residual_rows)
            output, summary = TOOL.collect_event_presentation_cohort_evidence(
                project_root=project, report_root=reports,
                minimum_repeated_cue_files=3, minimum_associated_cue_files=2,
                minimum_enrichment_ratio=1.2, minimum_slot_cohort_members=2,
                common_shape_ratio=0.75, maximum_sequence_gap=50,
            )
            self.assertTrue(output.is_file())
            self.assertEqual(summary["all_residual_events"],6)
            self.assertEqual(summary["slot_cohort_rows"],1)
            self.assertEqual(summary["critical_slot_cohort_rows"],1)
            shapes=TOOL.read_tsv(reports / TOOL.EVENT_PRESENTATION_COHORT_EVIDENCE_DIR / "EVENT_RESIDUAL_DELTA_SHAPE_FREQUENCY.tsv")
            bath=[row for row in shapes if row.get("target_tag_values")=="0x74100014" and row.get("sequence_tag")=="insert"]
            self.assertEqual(len(bath),1)
            self.assertEqual(bath[0]["cue_positive_file_count"],"3")
            self.assertEqual(bath[0]["all_residual_file_count"],"3")
            self.assertEqual(bath[0]["classification"],"presentation_repeated_delta_shape_candidate")
            cohorts=TOOL.read_tsv(reports / TOOL.EVENT_PRESENTATION_COHORT_EVIDENCE_DIR / "EVENT_PRESENTATION_SLOT_COHORTS.tsv")
            self.assertEqual(cohorts[0]["route_stem"],"fo")
            self.assertEqual(cohorts[0]["event_slot"],"90")
            self.assertEqual(cohorts[0]["cue_residual_member_count"],"3")
            self.assertNotIn("シャワー", (reports / TOOL.EVENT_PRESENTATION_COHORT_EVIDENCE_DIR / "SUMMARY.json").read_text(encoding="utf-8"))


    def test_event_atom_word_span_handles_insert_boundary(self) -> None:
        atoms = [
            {"word_index": 1}, {"word_index": 3}, {"word_index": 7},
        ]
        self.assertEqual(TOOL.event_atom_word_span(atoms, 1, 1, 10), (3, 3))
        self.assertEqual(TOOL.event_atom_word_span(atoms, 1, 3, 10), (3, 10))

    def test_export_event_context_word_redacts_opaque_value(self) -> None:
        tag = TOOL.export_event_context_word(0x74100014)
        self.assertEqual(tag["safe_value_hex"], "0x74100014")
        opaque = TOOL.export_event_context_word(0x12345678)
        self.assertEqual(opaque["word_kind"], "opaque_u32")
        self.assertEqual(opaque["safe_value_hex"], "")
        self.assertEqual(len(opaque["opaque_word_sha256"]), 64)

    def test_collect_event_delta_context_evidence_tests_inverse_insert_in_memory(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            workspace = project / ".local/build/quartet_restoration"
            reports = project / ".local/reports/quartet_restoration"
            differences = reports / "differences"
            cohort = reports / TOOL.EVENT_PRESENTATION_COHORT_EVIDENCE_DIR
            migration = reports / TOOL.EVENT_TAG_MIGRATION_EVIDENCE_DIR
            differences.mkdir(parents=True)
            cohort.mkdir(parents=True)
            migration.mkdir(parents=True)
            TOOL.atomic_json(cohort / "SUMMARY.json", {
                "type":"br_quartet_restoration_event_presentation_cohort_evidence_summary",
                "format_version":1,"tool_version":"0.0.26",
            })
            TOOL.atomic_json(migration / "SUMMARY.json", {
                "type":"br_quartet_restoration_event_tag_migration_evidence_summary",
                "format_version":1,"tool_version":"0.0.24",
            })

            def lp(raw: bytes) -> bytes:
                return struct.pack("<I", len(raw)) + raw
            description = "説明".encode("cp932") + b"\0"
            prefix = struct.pack("<II", 3, 0) + lp(b"name\0") + lp(description)
            source_words = [1, 0x75400009, 0x77000001, 1, 0x7540000A, 0x74100013, 0x7F000000]
            target_words = [1, 0x75400009, 0x77000001, 1, 0x7540000A, 0x74100013, 0x74100014, 0x7F000000]
            source_payload = prefix + struct.pack("<7I", *source_words)
            target_payload = prefix + struct.pack("<8I", *target_words)
            source_profile = TOOL.profile_ebd_post_header_words(source_payload, len(prefix))
            target_profile = TOOL.profile_ebd_post_header_words(target_payload, len(prefix))
            delta = TOOL.compare_ebd_tag_atoms(source_profile["atoms"], target_profile["atoms"])[0]
            shape_id = TOOL.event_residual_delta_shape_id(delta)

            path = "event/event_jp/fo03/event_fo03_090.ebd"
            ebm = "event/event_jp/fo03/event_message_fo03_090.ebm"
            source_item = entry(path, source_payload, "DATA/PACK01.PAK")
            target_item = entry("event/b1/event_jp/fo03/event_fo03_090.ebd", target_payload, "Data/PACK11.PAK")
            target_item["normalized_path"] = path
            target_item["comparison_key"] = path.casefold()
            TOOL.atomic_json(differences / "br1_events.json", {
                "source_archive_group":"br1_events",
                "entries":[{"classification":"changed","scope_status":"in_scope","normalized_path":path,"source":TOOL.file_ref(source_item),"target":TOOL.file_ref(target_item)}],
            })
            for side, item, payload in (("source", source_item, source_payload), ("target", target_item, target_payload)):
                out = TOOL.inventory_workspace_file(workspace, side, "br1_events", item["archive"], item["path"])
                out.parent.mkdir(parents=True, exist_ok=True)
                out.write_bytes(payload)

            TOOL.write_tsv(cohort / "EVENT_RESIDUAL_DELTA_SHAPE_FREQUENCY.tsv", [
                "shape_id","sequence_tag","source_atom_count","target_atom_count","source_tag_values","target_tag_values",
                "all_residual_file_count","cue_positive_file_count","identical_message_cue_file_count","cue_domains",
                "cue_enrichment_ratio","classification",
            ], [{
                "shape_id":shape_id,"sequence_tag":"insert","source_atom_count":0,"target_atom_count":1,
                "source_tag_values":"","target_tag_values":"0x74100014","all_residual_file_count":1,
                "cue_positive_file_count":1,"identical_message_cue_file_count":1,"cue_domains":"bath_or_hot_spring",
                "cue_enrichment_ratio":8.0,"classification":"presentation_repeated_delta_shape_candidate",
            }])
            TOOL.write_tsv(cohort / "EVENT_PRESENTATION_SLOT_COHORTS.tsv", [
                "cohort_id","enriched_common_delta_shape_ids","review_priority",
            ], [{"cohort_id":"cohort1","enriched_common_delta_shape_ids":shape_id,"review_priority":"critical"}])
            TOOL.write_tsv(cohort / "EVENT_ROUTE_SEQUENCE_CLUSTERS.tsv", [
                "sequence_id","enriched_common_delta_shape_ids","review_priority",
            ], [])
            TOOL.write_tsv(cohort / "FOCUSED_PRESENTATION_COHORT_REVIEW.tsv", [
                "normalized_path","review_priority",
            ], [{"normalized_path":path,"review_priority":"critical"}])
            TOOL.write_tsv(cohort / "CUE_LINKED_RESIDUAL_DELTA_SHAPES.tsv", [
                "normalized_path","event_message_path","event_message_classification","cue_rule_ids","cue_domains",
                "compound_location_and_presentation_cue","shape_id","shape_classification","cue_enrichment_ratio","review_status",
            ], [{
                "normalized_path":path,"event_message_path":ebm,"event_message_classification":"identical",
                "cue_rule_ids":"bath_ofuro","cue_domains":"bath_or_hot_spring",
                "compound_location_and_presentation_cue":False,"shape_id":shape_id,
                "shape_classification":"presentation_repeated_delta_shape_candidate","cue_enrichment_ratio":8.0,"review_status":"test",
            }])
            TOOL.write_tsv(migration / "RESIDUAL_EVENT_TAG_DELTAS.tsv", [
                "normalized_path","event_message_path","event_message_classification","migration_classification",
                "signature_file_count","signature_route_family_count","sequence_tag","source_atom_count","target_atom_count",
                "source_tag_values","target_tag_values","source_first_word_index","target_first_word_index",
                "source_atom_sequence_sha256","target_atom_sequence_sha256","review_status",
            ], [{
                "normalized_path":path,"event_message_path":ebm,"event_message_classification":"identical",
                "migration_classification":"rare_event_delta_candidate","signature_file_count":1,"signature_route_family_count":1,
                "sequence_tag":"insert","source_atom_count":0,"target_atom_count":1,"source_tag_values":"",
                "target_tag_values":"0x74100014","source_first_word_index":"","target_first_word_index":6,
                "source_atom_sequence_sha256":delta["source_atom_sequence_sha256"],
                "target_atom_sequence_sha256":delta["target_atom_sequence_sha256"],"review_status":"test",
            }])

            output, summary = TOOL.collect_event_delta_context_evidence(
                project_root=project, workspace_root=workspace, report_root=reports,
                maximum_event_bytes=1024*1024, context_words=3,
                maximum_single_scene_shapes_per_event=8,
            )
            self.assertTrue(output.is_file())
            self.assertEqual(summary["selected_delta_shape_rows"], 1)
            self.assertEqual(summary["context_occurrence_rows"], 1)
            self.assertEqual(summary["in_memory_splice_rows"], 1)
            self.assertEqual(summary["isolated_in_memory_splice_rows"], 1)
            splices = TOOL.read_tsv(reports / TOOL.EVENT_DELTA_CONTEXT_EVIDENCE_DIR / "IN_MEMORY_EVENT_DELTA_SPLICE_READINESS.tsv")
            self.assertEqual(splices[0]["in_memory_splice_status"], "selected_shape_removed_without_other_coarse_delta_changes")
            words = TOOL.read_tsv(reports / TOOL.EVENT_DELTA_CONTEXT_EVIDENCE_DIR / "EVENT_DELTA_CONTEXT_WORDS.tsv")
            self.assertTrue(any(row["safe_value_hex"] == "0x74100014" for row in words))



    def test_construct_inverse_event_delta_candidate_roundtrips_target(self) -> None:
        def lp(raw: bytes) -> bytes:
            return struct.pack("<I", len(raw)) + raw
        prefix = struct.pack("<II", 2, 0) + lp(b"name\0") + lp("説明".encode("cp932") + b"\0")
        source_words = [1, 0x75400009, 0x77000001, 1, 0x7540000A, 0x74100013, 0x7F000000]
        target_words = [1, 0x75400009, 0x77000001, 1, 0x7540000A, 0x74100013, 0x74100014, 0x7F000000]
        source = prefix + struct.pack("<7I", *source_words)
        target = prefix + struct.pack("<8I", *target_words)
        source_header = TOOL.parse_ebd_header_schema(source)
        target_header = TOOL.parse_ebd_header_schema(target)
        source_profile = TOOL.profile_ebd_post_header_words(source, len(prefix))
        target_profile = TOOL.profile_ebd_post_header_words(target, len(prefix))
        delta = TOOL.compare_ebd_tag_atoms(source_profile["atoms"], target_profile["atoms"])[0]
        shape_id = TOOL.event_residual_delta_shape_id(delta)
        candidate, metadata = TOOL.construct_inverse_event_delta_candidate(
            source_payload=source, target_payload=target,
            source_header=source_header, target_header=target_header,
            source_profile=source_profile, target_profile=target_profile,
            delta=delta, shape_id=shape_id,
        )
        self.assertEqual(candidate, source)
        self.assertTrue(metadata["target_roundtrip_exact"])
        self.assertTrue(metadata["target_prefix_preserved"])
        self.assertTrue(metadata["target_suffix_preserved"])
        self.assertTrue(metadata["target_trailing_bytes_preserved"])

    def test_event_prototype_profile_id_is_stable_and_safe(self) -> None:
        profile = TOOL._event_prototype_profile_id("route_sequence", "a" * 64, "TE02 / Shower")
        self.assertEqual(profile, "route_sequence_te02_shower_aaaaaaaaaa")

    def test_build_event_prototypes_keeps_repeated_and_route_profiles_separate(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            workspace = project / ".local/build/quartet_restoration"
            reports = project / ".local/reports/quartet_restoration"
            differences = reports / "differences"
            context = reports / TOOL.EVENT_DELTA_CONTEXT_EVIDENCE_DIR
            differences.mkdir(parents=True)
            context.mkdir(parents=True)
            TOOL.atomic_json(context / "SUMMARY.json", {
                "type":"br_quartet_restoration_event_delta_context_evidence_summary",
                "format_version":1,"tool_version":"0.0.27",
            })

            def lp(raw: bytes) -> bytes:
                return struct.pack("<I", len(raw)) + raw
            prefix = struct.pack("<II", 3, 0) + lp(b"name\0") + lp("説明".encode("cp932") + b"\0")
            bath_source_words = [1, 0x75400009, 0x77000001, 1, 0x7540000A, 0x74100013, 0x7F000000]
            bath_target_words = [1, 0x75400009, 0x77000001, 1, 0x7540000A, 0x74100013, 0x74100014, 0x7F000000]
            route_source_words = [1, 0x75400009, 0x75100001, 0x75000012, 0x7500002C, 0x70000001, 0x7F000000]
            route_target_words = [1, 0x75400009, 0x7F000000]
            bath_source = prefix + struct.pack("<7I", *bath_source_words)
            bath_target = prefix + struct.pack("<8I", *bath_target_words)
            route_source = prefix + struct.pack("<7I", *route_source_words)
            route_target = prefix + struct.pack("<3I", *route_target_words)

            def shape_and_candidate(source: bytes, target: bytes):
                sh = TOOL.parse_ebd_header_schema(source)
                th = TOOL.parse_ebd_header_schema(target)
                sp = TOOL.profile_ebd_post_header_words(source, len(prefix))
                tp = TOOL.profile_ebd_post_header_words(target, len(prefix))
                delta = TOOL.compare_ebd_tag_atoms(sp["atoms"], tp["atoms"])[0]
                shape = TOOL.event_residual_delta_shape_id(delta)
                candidate, meta = TOOL.construct_inverse_event_delta_candidate(
                    source_payload=source,target_payload=target,source_header=sh,target_header=th,
                    source_profile=sp,target_profile=tp,delta=delta,shape_id=shape,
                )
                return shape, delta, candidate, meta

            bath_shape, bath_delta, bath_candidate, bath_meta = shape_and_candidate(bath_source, bath_target)
            route_shape, route_delta, route_candidate, route_meta = shape_and_candidate(route_source, route_target)
            entries=[]
            occurrence_rows=[]
            splice_rows=[]
            bath_paths=[f"event/event_jp/fo{index:02d}/event_fo{index:02d}_090.ebd" for index in (3,5,10)]
            route_paths=[f"event/event_jp/te02/event_te02_{slot:03d}.ebd" for slot in (150,170,180,220)]
            for path, source, target, shape, archetype, cue, domains, candidate, meta in [
                *[(path,bath_source,bath_target,bath_shape,"bath_arch",True,"bath_or_hot_spring",bath_candidate,bath_meta) for path in bath_paths],
                *[(path,route_source,route_target,route_shape,f"route_arch_{i}",i>=2,"shower",route_candidate,route_meta) for i,path in enumerate(route_paths)],
            ]:
                source_item=entry(path,source,"DATA/PACK01.PAK")
                target_actual="event/b1/"+path[len("event/"):]
                target_item=entry(target_actual,target,"Data/PACK11.PAK")
                target_item["normalized_path"]=path
                target_item["comparison_key"]=path.casefold()
                entries.append({"classification":"changed","scope_status":"in_scope","normalized_path":path,"source":TOOL.file_ref(source_item),"target":TOOL.file_ref(target_item)})
                for side,item,payload in (("source",source_item,source),("target",target_item,target)):
                    out=TOOL.inventory_workspace_file(workspace,side,"br1_events",item["archive"],item["path"])
                    out.parent.mkdir(parents=True,exist_ok=True)
                    out.write_bytes(payload)
                occurrence_rows.append({
                    "normalized_path":path,"shape_id":shape,"occurrence_index":0,
                    "cue_positive_occurrence":cue,"cue_domains":domains,
                    "pair_context_archetype_id":archetype,
                })
                splice_rows.append({
                    "normalized_path":path,"shape_id":shape,"occurrence_index":0,
                    "candidate_sha256":meta["candidate_sha256"],
                    "in_memory_splice_status":"selected_shape_removed_without_other_coarse_delta_changes",
                })
            TOOL.atomic_json(differences / "br1_events.json", {"source_archive_group":"br1_events","entries":entries})
            TOOL.write_tsv(context / "SELECTED_EVENT_DELTA_SHAPES.tsv", [
                "shape_id","selection_reasons","selection_priority","sequence_tag","source_tag_values","target_tag_values","cue_domains",
            ], [
                {"shape_id":bath_shape,"selection_reasons":"repeated_slot_enriched_common_shape","selection_priority":"critical","sequence_tag":"insert","source_tag_values":"","target_tag_values":"0x74100014","cue_domains":"bath_or_hot_spring"},
                {"shape_id":route_shape,"selection_reasons":"route_sequence_enriched_common_shape","selection_priority":"high","sequence_tag":"delete","source_tag_values":"0x75100001;0x75000012;0x7500002c;0x70000001","target_tag_values":"","cue_domains":"shower"},
            ])
            TOOL.write_tsv(context / "FOCUSED_EVENT_DELTA_CONTEXT_REVIEW.tsv", [
                "shape_id","selection_reasons","total_occurrence_count","isolated_splice_success_count","classification","review_priority",
            ], [
                {"shape_id":bath_shape,"selection_reasons":"repeated_slot_enriched_common_shape","total_occurrence_count":3,"isolated_splice_success_count":3,"classification":"repeated_context_and_in_memory_inverse_splice_consistent","review_priority":"critical"},
                {"shape_id":route_shape,"selection_reasons":"route_sequence_enriched_common_shape","total_occurrence_count":4,"isolated_splice_success_count":4,"classification":"context_decoding_only_not_ready_for_prototype","review_priority":"high"},
            ])
            TOOL.write_tsv(context / "EVENT_DELTA_CONTEXT_OCCURRENCES.tsv", [
                "normalized_path","shape_id","occurrence_index","cue_positive_occurrence","cue_domains","pair_context_archetype_id",
            ], occurrence_rows)
            TOOL.write_tsv(context / "IN_MEMORY_EVENT_DELTA_SPLICE_READINESS.tsv", [
                "normalized_path","shape_id","occurrence_index","candidate_sha256","in_memory_splice_status",
            ], splice_rows)

            output, summary = TOOL.build_event_prototypes(
                project_root=project,workspace_root=workspace,report_root=reports,
                maximum_event_bytes=1024*1024,minimum_repeated_files=3,minimum_route_files=4,
            )
            self.assertTrue(output.is_file())
            self.assertEqual(summary["promoted_profile_rows"],2)
            self.assertEqual(summary["high_confidence_profile_rows"],1)
            self.assertEqual(summary["experimental_profile_rows"],1)
            self.assertEqual(summary["prototype_file_rows"],7)
            self.assertEqual(summary["validation_failures"],0)
            profiles=TOOL.read_tsv(reports / TOOL.EVENT_PROTOTYPE_EVIDENCE_DIR / "EVENT_PROTOTYPE_PROFILES.tsv")
            self.assertEqual({row["prototype_confidence"] for row in profiles},{"high","experimental"})
            self.assertEqual(len(list((workspace / TOOL.EVENT_PROTOTYPE_BUILD_DIR).rglob("*.ebd"))),7)
            self.assertFalse(any(path.suffix.casefold()==".ebd" for path in (reports / TOOL.EVENT_PROTOTYPE_EVIDENCE_DIR).rglob("*")))


class EventRepackTestHarnessTests(unittest.TestCase):
    def _write_fake_gust_pak(self, path: Path) -> None:
        script = r'''#!/usr/bin/env python3
import hashlib, json, pathlib, re, sys, zipfile

def load_compatible(path):
    text = path.read_text(encoding="utf-8")
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    text = re.sub(r"(?m)//.*$", "", text)
    text = re.sub(r"(?<![A-Za-z0-9_.$])0[xX]([0-9A-Fa-f]+)(?![A-Za-z0-9_.$])", lambda m: str(int(m.group(0), 16)), text)
    text = re.sub(r",\s*([}\]])", r"\1", text)
    return json.loads(text)

arg = pathlib.Path(sys.argv[-1])
if arg.suffix.casefold() == ".json":
    data = load_compatible(arg)
    out = arg.parent / data["name"]
    payloads = []
    for row in data["files"]:
        member = row["name"].replace("\\", "/")
        payload = (arg.parent / pathlib.Path(member)).read_bytes()
        row["key"] = hashlib.sha1(payload).hexdigest()
        payloads.append((member, payload))
    data["master_key"] = hashlib.sha1("".join(row["key"] for row in data["files"]).encode("ascii")).hexdigest()
    data["header_size"] = int(data.get("header_size", 0)) + 4
    with zipfile.ZipFile(out, "w", compression=zipfile.ZIP_STORED) as zf:
        zf.writestr("__gust_manifest__.json", json.dumps(data, sort_keys=True))
        for member, payload in payloads:
            zf.writestr(member, payload)
else:
    with zipfile.ZipFile(arg, "r") as zf:
        data = json.loads(zf.read("__gust_manifest__.json"))
        for row in data["files"]:
            member = row["name"].replace("\\", "/")
            target = arg.parent / pathlib.Path(member)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(zf.read(member))
    manifest = arg.parent / f"{arg.stem}.json"
    text = json.dumps(data, indent=4)
    text = re.sub(r'("version"\s*:\s*)\d+', lambda m: m.group(1) + f"0x{data['version']:08x}", text, count=1)
    text = re.sub(r'("header_size"\s*:\s*)\d+', lambda m: m.group(1) + f"0x{data['header_size']:08x}", text, count=1)
    text = re.sub(r'("flags"\s*:\s*)\d+', lambda m: m.group(1) + f"0x{data['flags']:08x}", text, count=1)
    text = text.replace(f"0x{data['version']:08x}", f"0x{data['version']:08x} /* gust_pak hex header */", 1)
    text = text.rstrip()
    text = text[:-1].rstrip() + "," + chr(10) + "}" + chr(10)
    manifest.write_text(text, encoding="utf-8")
'''
        path.write_text(script, encoding="utf-8")
        path.chmod(0o755)

    def _write_fake_pak(self, path: Path, members: dict[str, bytes]) -> dict:
        manifest = {
            "name": "PACK11.pak",
            "version": 0x20000,
            "header_size": 16,
            "flags": 0,
            "nb_files": len(members),
            "64-bit": True,
            "files": [
                {"name": name, "key": "00" * 20, "flags": index}
                for index, name in enumerate(members)
            ],
        }
        path.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_STORED) as zf:
            zf.writestr("__gust_manifest__.json", json.dumps(manifest, sort_keys=True))
            for name, payload in members.items():
                zf.writestr(name, payload)
        return manifest

    def _read_fake_pak_member(self, path: Path, member: str) -> bytes:
        with zipfile.ZipFile(path, "r") as zf:
            return zf.read(member)

    def _prepare_project(self, root: Path, *, corrupt_current_target: bool = False):
        project = root / "project"
        workspace = project / ".local/build/quartet_restoration"
        reports = project / ".local/reports/quartet_restoration"
        quartet = root / "quartet"
        tool = root / "gust_pak"
        self._write_fake_gust_pak(tool)
        prototype_evidence = reports / TOOL.EVENT_PROTOTYPE_EVIDENCE_DIR
        prototype_evidence.mkdir(parents=True, exist_ok=True)
        TOOL.atomic_json(prototype_evidence / "SUMMARY.json", {
            "type": "br_quartet_restoration_event_prototype_evidence_summary",
            "format_version": 1,
            "tool_version": "0.0.28",
            "validation_failures": 0,
        })
        current_a = b"quartet-event-a" if not corrupt_current_target else b"other-mod-event-a"
        current_b = b"quartet-event-b"
        unrelated = b"translated-English-member-must-survive"
        archive = quartet / "Data/PACK11.PAK"
        self._write_fake_pak(archive, {
            "event/b1/event_jp/fo03/event_fo03_090.ebd": current_a,
            "event/b1/event_jp/te02/event_te02_150.ebd": current_b,
            "event/b1/event_en/fo03/event_message_fo03_090.ebm": unrelated,
        })
        reports.mkdir(parents=True, exist_ok=True)
        TOOL.write_tsv(reports / "ARCHIVE_INVENTORY.tsv", [
            "pair_id","category","side","target_id","archive","size","sha256","extraction_status",
        ], [{
            "pair_id":"br1_events","category":"events","side":"target",
            "target_id":"blue_reflection_quartet","archive":"Data/PACK11.PAK",
            "size":archive.stat().st_size,"sha256":"f"*64,"extraction_status":"unchanged",
        }])
        specs = [
            ("repeated_context_test", "high_confidence_repeated_exact_context_local_prototype", "high",
             "event/event_jp/fo03/event_fo03_090.ebd", "event/b1/event_jp/fo03/event_fo03_090.ebd", b"candidate-event-a", b"quartet-event-a"),
            ("route_sequence_test", "experimental_route_sequence_local_prototype", "experimental",
             "event/event_jp/te02/event_te02_150.ebd", "event/b1/event_jp/te02/event_te02_150.ebd", b"candidate-event-b", current_b),
        ]
        for profile_id, classification, confidence, normalized, target_member, candidate, expected_target in specs:
            profile = workspace / TOOL.EVENT_PROTOTYPE_BUILD_DIR / profile_id
            candidate_rel = TOOL.PurePosixPath("payload") / TOOL.PurePosixPath(normalized)
            candidate_path = profile / Path(candidate_rel.as_posix())
            candidate_path.parent.mkdir(parents=True, exist_ok=True)
            candidate_path.write_bytes(candidate)
            TOOL.atomic_json(profile / "PROTOTYPE.json", {
                "type":"br_quartet_restoration_local_event_prototype",
                "format_version":1,"tool_version":"0.0.28",
                "profile_id":profile_id,"profile_classification":classification,
                "prototype_confidence":confidence,"installable_package_generated":False,
                "files":[{
                    "normalized_path":normalized,"target_archive":"Data/PACK11.PAK",
                    "target_member_path":target_member,
                    "target_sha256":TOOL.hashlib.sha256(expected_target).hexdigest(),
                    "candidate_sha256":TOOL.hashlib.sha256(candidate).hexdigest(),
                    "candidate_relative_path":candidate_rel.as_posix(),
                }],
            })
        return project, workspace, reports, quartet, tool, archive, unrelated

    def test_event_repack_harness_preserves_unrelated_current_archive_members(self):
        with tempfile.TemporaryDirectory() as temporary:
            project, workspace, reports, quartet, tool, archive, unrelated = self._prepare_project(Path(temporary))
            installed_before = TOOL.sha256_file(archive)
            output, summary = TOOL.prepare_event_repack_tests(
                project_root=project, quartet_root=quartet, gust_pak=tool,
                workspace_root=workspace, report_root=reports, timeout_seconds=30,
            )
            self.assertTrue(output.is_file())
            self.assertEqual(summary["profile_rows"], 2)
            self.assertEqual(summary["validation_failures"], 0)
            self.assertGreater(summary["derived_manifest_difference_rows"], 0)
            self.assertEqual(summary["stable_manifest_difference_rows"], 0)
            self.assertFalse(summary["inventory_pristine_archive_match"])
            manifest_diffs = TOOL.read_tsv(
                reports / TOOL.EVENT_REPACK_TEST_EVIDENCE_DIR / "EVENT_REPACK_TEST_MANIFEST_DIFFERENCES.tsv"
            )
            self.assertTrue(manifest_diffs)
            self.assertTrue(all(row["gate_effect"] == "diagnostic_only" for row in manifest_diffs))
            self.assertTrue(all(not row["baseline_value"] for row in manifest_diffs if row["field"] in {"key", "master_key"}))
            self.assertEqual(TOOL.sha256_file(archive), installed_before)
            root = workspace / TOOL.EVENT_REPACK_TEST_BUILD_DIR
            self.assertEqual(TOOL.sha256_file(root / "baseline/Data/PACK11.PAK"), installed_before)
            bath = root / "profiles/repeated_context_test/output/Data/PACK11.PAK"
            route = root / "profiles/route_sequence_test/output/Data/PACK11.PAK"
            self.assertEqual(self._read_fake_pak_member(bath, "event/b1/event_jp/fo03/event_fo03_090.ebd"), b"candidate-event-a")
            self.assertEqual(self._read_fake_pak_member(route, "event/b1/event_jp/te02/event_te02_150.ebd"), b"candidate-event-b")
            self.assertEqual(self._read_fake_pak_member(bath, "event/b1/event_en/fo03/event_message_fo03_090.ebm"), unrelated)
            self.assertEqual(self._read_fake_pak_member(route, "event/b1/event_en/fo03/event_message_fo03_090.ebm"), unrelated)
            self.assertEqual(self._read_fake_pak_member(bath, "event/b1/event_jp/te02/event_te02_150.ebd"), b"quartet-event-b")
            self.assertEqual(self._read_fake_pak_member(route, "event/b1/event_jp/fo03/event_fo03_090.ebd"), b"quartet-event-a")
            self.assertFalse(any(path.suffix.casefold() == ".pak" for path in (reports / TOOL.EVENT_REPACK_TEST_EVIDENCE_DIR).rglob("*")))

    def test_event_repack_harness_rejects_modified_target_member_but_keeps_other_profile(self):
        with tempfile.TemporaryDirectory() as temporary:
            project, workspace, reports, quartet, tool, archive, _ = self._prepare_project(Path(temporary), corrupt_current_target=True)
            installed_before = TOOL.sha256_file(archive)
            _, summary = TOOL.prepare_event_repack_tests(
                project_root=project, quartet_root=quartet, gust_pak=tool,
                workspace_root=workspace, report_root=reports, timeout_seconds=30,
            )
            self.assertEqual(summary["profile_rows"], 1)
            self.assertGreater(summary["skipped_rows"], 0)
            self.assertEqual(TOOL.sha256_file(archive), installed_before)
            root = workspace / TOOL.EVENT_REPACK_TEST_BUILD_DIR
            self.assertFalse((root / "profiles/repeated_context_test/output/Data/PACK11.PAK").exists())
            self.assertTrue((root / "profiles/route_sequence_test/output/Data/PACK11.PAK").is_file())
            skipped = TOOL.read_tsv(reports / TOOL.EVENT_REPACK_TEST_EVIDENCE_DIR / "EVENT_REPACK_TEST_BUILD_SKIPPED.tsv")
            self.assertIn("current_target_member_sha256_mismatch", {row["reason"] for row in skipped})

    def test_gust_manifest_loader_accepts_hex_comments_and_trailing_commas(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "PACK11.json"
            path.write_text(
                "{\n"
                '    "name": "PACK11.pak",\n'
                '    "version": 0x00020000, /* header signature */\n'
                '    "header_size": 0x10,\n'
                '    "flags": 0x0,\n'
                '    "nb_files": 1,\n'
                '    "64-bit": true,\n'
                '    "files": [{"name": "event/0xkeep/literal.ebd", "key": "' + "00" * 20 + '"}],\n'
                "}\n",
                encoding="utf-8",
            )
            manifest = TOOL._load_gust_pak_manifest(path)
            self.assertEqual(manifest["version"], 0x20000)
            self.assertEqual(manifest["header_size"], 16)
            self.assertEqual(manifest["safe_files"][0]["safe_name"], "event/0xkeep/literal.ebd")
            self.assertEqual(manifest["safe_parse_mode"], "gust_json_compatible:comments+hex_numbers+trailing_commas")

    def test_gust_manifest_loader_rejects_unterminated_comment(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "PACK11.json"
            path.write_text('{"name":"PACK11.pak", /* broken', encoding="utf-8")
            with self.assertRaises(TOOL.RestorationError):
                TOOL._load_gust_pak_manifest(path)

    def test_gust_manifest_semantic_signature_ignores_derived_serialization_metadata(self):
        base = {
            "name":"PACK11.pak","version":0x20000,"header_size":16,"flags":0,"nb_files":1,"64-bit":True,
            "master_key":"aa"*20,
            "safe_files":[{"safe_name":"event/a.ebd","key":"00"*20,"flags":7,"extra":1,"size":10,"offset":1}],
        }
        changed = json.loads(json.dumps(base))
        changed["header_size"] = 32
        changed["master_key"] = "bb" * 20
        changed["safe_files"][0]["key"] = "11" * 20
        changed["safe_files"][0]["extra"] = 99
        changed["safe_files"][0]["size"] = 999
        changed["safe_files"][0]["offset"] = 555
        self.assertEqual(TOOL._gust_manifest_semantic_signature(base), TOOL._gust_manifest_semantic_signature(changed))
        rows = TOOL._gust_manifest_metadata_differences(
            base, changed, profile_id="test", modified_member_keys={"event/a.ebd"},
        )
        self.assertEqual({row["field"] for row in rows}, {"header_size", "master_key", "key", "extra"})
        self.assertTrue(all(row["gate_effect"] == "diagnostic_only" for row in rows))
        key_row = next(row for row in rows if row["field"] == "key")
        self.assertEqual(key_row["baseline_value"], "")
        self.assertEqual(key_row["verification_value"], "")
        self.assertTrue(key_row["baseline_value_sha256"])

    def test_gust_manifest_semantic_signature_detects_stable_member_flag_change(self):
        base = {
            "name":"PACK11.pak","version":0x20000,"flags":0,"nb_files":1,"64-bit":True,
            "safe_files":[{"safe_name":"event/a.ebd","key":"00"*20,"flags":7}],
        }
        changed = json.loads(json.dumps(base))
        changed["safe_files"][0]["flags"] = 8
        self.assertNotEqual(TOOL._gust_manifest_semantic_signature(base), TOOL._gust_manifest_semantic_signature(changed))
        rows = TOOL._gust_manifest_metadata_differences(
            base, changed, profile_id="test", modified_member_keys=set(),
        )
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["field"], "flags")
        self.assertEqual(rows[0]["gate_effect"], "validation_gate")


    def test_event_activation_request_validates_local_profiles_without_game_write(self):
        with tempfile.TemporaryDirectory() as temporary:
            project, workspace, reports, quartet, tool, archive, _ = self._prepare_project(Path(temporary))
            installed_before = TOOL.sha256_file(archive)
            TOOL.prepare_event_repack_tests(
                project_root=project, quartet_root=quartet, gust_pak=tool,
                workspace_root=workspace, report_root=reports, timeout_seconds=30,
            )
            output, summary = TOOL.prepare_event_activation_request(
                project_root=project, quartet_root=quartet,
                workspace_root=workspace, report_root=reports,
            )
            self.assertTrue(output.is_file())
            self.assertEqual(summary["profile_rows"], 2)
            self.assertTrue(summary["target_sha256_matches_baseline"])
            self.assertFalse(summary["installed_game_modified"])
            self.assertFalse(summary["activation_or_rollback_generated"])
            self.assertEqual(TOOL.sha256_file(archive), installed_before)
            evidence = reports / TOOL.EVENT_ACTIVATION_REQUEST_EVIDENCE_DIR
            request = TOOL.load_json(evidence / "CORE_ACTIVATION_REQUEST.json")
            self.assertEqual(request["transaction_owner"], "core_unified_patcher")
            self.assertEqual(len(request["profiles"]), 2)
            self.assertTrue(all(item["expected_target_sha256_before_activation"] == installed_before for item in request["profiles"]))
            self.assertFalse(any(path.suffix.casefold() == ".pak" for path in evidence.rglob("*")))
            requirements = TOOL.read_tsv(evidence / "CORE_TRANSACTION_REQUIREMENTS.tsv")
            self.assertTrue(any("atomically replace" in row["requirement"] for row in requirements))

    def test_event_activation_request_rejects_changed_installed_pack11(self):
        with tempfile.TemporaryDirectory() as temporary:
            project, workspace, reports, quartet, tool, archive, _ = self._prepare_project(Path(temporary))
            TOOL.prepare_event_repack_tests(
                project_root=project, quartet_root=quartet, gust_pak=tool,
                workspace_root=workspace, report_root=reports, timeout_seconds=30,
            )
            archive.write_bytes(archive.read_bytes() + b"changed-after-stage25")
            with self.assertRaisesRegex(TOOL.RestorationError, "changed after stage 25"):
                TOOL.prepare_event_activation_request(
                    project_root=project, quartet_root=quartet,
                    workspace_root=workspace, report_root=reports,
                )

    def test_event_activation_request_rejects_tampered_local_profile(self):
        with tempfile.TemporaryDirectory() as temporary:
            project, workspace, reports, quartet, tool, archive, _ = self._prepare_project(Path(temporary))
            TOOL.prepare_event_repack_tests(
                project_root=project, quartet_root=quartet, gust_pak=tool,
                workspace_root=workspace, report_root=reports, timeout_seconds=30,
            )
            profile = workspace / TOOL.EVENT_REPACK_TEST_BUILD_DIR / "profiles/repeated_context_test/output/Data/PACK11.PAK"
            profile.write_bytes(profile.read_bytes() + b"tampered")
            with self.assertRaisesRegex(TOOL.RestorationError, "checksum mismatch"):
                TOOL.prepare_event_activation_request(
                    project_root=project, quartet_root=quartet,
                    workspace_root=workspace, report_root=reports,
                )



class G1SRepackTestHarnessTests(unittest.TestCase):
    def test_g1s_repack_harness_builds_separate_pack10_profiles(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            project = root / "project"
            workspace = project / ".local/build/quartet_restoration"
            reports = project / ".local/reports/quartet_restoration"
            quartet = root / "quartet"
            tool = root / "gust_pak"
            helper = EventRepackTestHarnessTests(methodName="runTest")
            helper._write_fake_gust_pak(tool)

            members = {
                "data/b1/x64/shader/heightfog.g1s": b"quartet-heightfog",
                "data/b1/x64/shader/swater.g1s": b"quartet-swater",
                "data/b1/x64/shader/cwater.g1s": b"unrelated-water-shader",
            }
            archive = quartet / "Data/PACK10_01.PAK"
            manifest = {
                "name": "PACK10_01.pak",
                "version": 0x20000,
                "header_size": 16,
                "flags": 0,
                "nb_files": len(members),
                "64-bit": True,
                "files": [
                    {"name": name, "key": "00" * 20, "flags": index}
                    for index, name in enumerate(members)
                ],
            }
            archive.parent.mkdir(parents=True, exist_ok=True)
            with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_STORED) as zf:
                zf.writestr("__gust_manifest__.json", json.dumps(manifest, sort_keys=True))
                for name, payload in members.items():
                    zf.writestr(name, payload)
            installed_before = TOOL.sha256_file(archive)

            evidence = reports / TOOL.G1S_PROTOTYPE_EVIDENCE_DIR
            evidence.mkdir(parents=True, exist_ok=True)
            TOOL.atomic_json(evidence / "SUMMARY.json", {
                "type": "br_quartet_restoration_g1s_prototype_evidence_summary",
                "format_version": 1,
                "tool_version": "0.0.15",
                "prototype_rows": 2,
                "validation_failures": 0,
            })
            prototype_rows = []
            diff_entries = []
            definitions = [
                ("height_fog_shader_original_code", "height_fog_shader", "steam_or_vapor_occlusion", "high", "data/x64/shader/heightfog.g1s", "data/b1/x64/shader/heightfog.g1s", b"prototype-heightfog"),
                ("water_shader_swater_original_code", "water_shader_swater", "water_visibility", "critical", "data/x64/shader/swater.g1s", "data/b1/x64/shader/swater.g1s", b"prototype-swater"),
            ]
            for prototype_id, rule_id, domain, priority, normalized, target_member, candidate in definitions:
                target_payload = members[target_member]
                prototype_dir = workspace / TOOL.G1S_PROTOTYPE_BUILD_DIR / prototype_id
                candidate_path = prototype_dir / "override" / Path(normalized)
                candidate_path.parent.mkdir(parents=True, exist_ok=True)
                candidate_path.write_bytes(candidate)
                TOOL.atomic_json(prototype_dir / "PROTOTYPE.json", {
                    "type": "br_quartet_restoration_local_g1s_prototype",
                    "format_version": 1,
                    "tool_version": "0.0.15",
                    "prototype_id": prototype_id,
                    "rule_id": rule_id,
                    "domain": domain,
                    "normalized_target_path": normalized,
                    "selected_target_program_indices": [0],
                    "target_sha256": TOOL.hashlib.sha256(target_payload).hexdigest(),
                    "prototype_sha256": TOOL.hashlib.sha256(candidate).hexdigest(),
                    "target_size": len(target_payload),
                    "prototype_size": len(candidate),
                    "status": "local_reversible_prototype_not_installed",
                })
                prototype_rows.append({
                    "prototype_id": prototype_id,
                    "candidate_id": "candidate",
                    "rule_id": rule_id,
                    "domain": domain,
                    "priority": priority,
                    "normalized_path": normalized,
                    "local_output_path": candidate_path.relative_to(project).as_posix(),
                    "selected_program_indices": "0",
                    "target_size": len(target_payload),
                    "prototype_size": len(candidate),
                    "size_delta": len(candidate) - len(target_payload),
                    "target_sha256": TOOL.hashlib.sha256(target_payload).hexdigest(),
                    "prototype_sha256": TOOL.hashlib.sha256(candidate).hexdigest(),
                    "g1s_magic": "_S2G7000",
                    "first_program_offset": 0,
                    "program_table_start": 0,
                    "program_table_end": 0,
                    "status": "local_reversible_prototype_built_not_installed",
                })
                diff_entries.append({
                    "classification": "changed",
                    "normalized_path": normalized,
                    "target": {
                        "archive": "Data/PACK10_01.PAK",
                        "path": target_member,
                        "normalized_path": normalized,
                        "size": len(target_payload),
                        "sha256": TOOL.hashlib.sha256(target_payload).hexdigest(),
                    },
                })
            TOOL.write_tsv(evidence / "G1S_PROTOTYPES.tsv", [
                "prototype_id","candidate_id","rule_id","domain","priority","normalized_path","local_output_path",
                "selected_program_indices","target_size","prototype_size","size_delta","target_sha256","prototype_sha256",
                "g1s_magic","first_program_offset","program_table_start","program_table_end","status",
            ], prototype_rows)
            (reports / "differences").mkdir(parents=True, exist_ok=True)
            TOOL.atomic_json(reports / "differences/br1_assets.json", {
                "source_archive_group": "br1_assets",
                "entries": diff_entries,
            })
            TOOL.write_tsv(reports / "ARCHIVE_INVENTORY.tsv", [
                "pair_id","side","archive","size","sha256",
            ], [{
                "pair_id": "br1_assets",
                "side": "target",
                "archive": "Data/PACK10_01.PAK",
                "size": archive.stat().st_size,
                "sha256": installed_before,
            }])

            output, summary = TOOL.prepare_g1s_repack_tests(
                project_root=project,
                quartet_root=quartet,
                gust_pak=tool,
                workspace_root=workspace,
                report_root=reports,
                timeout_seconds=30,
            )
            self.assertTrue(output.is_file())
            self.assertEqual(summary["profile_rows"], 2)
            self.assertEqual(summary["file_rows"], 2)
            self.assertEqual(summary["validation_failures"], 0)
            self.assertEqual(TOOL.sha256_file(archive), installed_before)
            harness = workspace / TOOL.G1S_REPACK_TEST_BUILD_DIR
            height_pack = harness / "profiles/height_fog_shader_original_code/output/Data/PACK10_01.PAK"
            water_pack = harness / "profiles/water_shader_swater_original_code/output/Data/PACK10_01.PAK"
            self.assertEqual(helper._read_fake_pak_member(height_pack, "data/b1/x64/shader/heightfog.g1s"), b"prototype-heightfog")
            self.assertEqual(helper._read_fake_pak_member(height_pack, "data/b1/x64/shader/swater.g1s"), b"quartet-swater")
            self.assertEqual(helper._read_fake_pak_member(water_pack, "data/b1/x64/shader/swater.g1s"), b"prototype-swater")
            self.assertEqual(helper._read_fake_pak_member(water_pack, "data/b1/x64/shader/heightfog.g1s"), b"quartet-heightfog")
            self.assertEqual(helper._read_fake_pak_member(height_pack, "data/b1/x64/shader/cwater.g1s"), b"unrelated-water-shader")
            self.assertFalse(any(path.suffix.casefold() == ".pak" for path in (reports / TOOL.G1S_REPACK_TEST_EVIDENCE_DIR).rglob("*")))


class G1SActivationRequestTests(unittest.TestCase):
    def _prepare_stage27_artifacts(self, root: Path):
        project = root / "project"
        workspace = project / ".local/build/quartet_restoration"
        reports = project / ".local/reports/quartet_restoration"
        quartet = root / "quartet"
        archive = quartet / "Data/PACK10_01.PAK"
        archive.parent.mkdir(parents=True, exist_ok=True)
        archive.write_bytes(b"stage27-baseline-pack10")
        baseline_sha = TOOL.sha256_file(archive)
        baseline_size = archive.stat().st_size

        harness = workspace / TOOL.G1S_REPACK_TEST_BUILD_DIR
        baseline_archive = harness / "baseline/Data/PACK10_01.PAK"
        baseline_archive.parent.mkdir(parents=True, exist_ok=True)
        baseline_archive.write_bytes(archive.read_bytes())
        TOOL.atomic_json(harness / "baseline/BASELINE.json", {
            "type": "br_quartet_restoration_local_g1s_repack_test_baseline",
            "format_version": 1,
            "tool_version": "0.0.33",
            "archive_relative_path": "Data/PACK10_01.PAK",
            "installed_archive_sha256": baseline_sha,
            "installed_archive_size": baseline_size,
            "member_count": 3,
            "local_rollback_archive": "baseline/Data/PACK10_01.PAK",
            "installed_game_modified": False,
        })
        TOOL.atomic_json(harness / TOOL.G1S_REPACK_TEST_MARKER, {
            "type": "br_quartet_restoration_local_g1s_repack_test_harness",
            "format_version": 1,
            "tool_version": "0.0.33",
            "input_archive_relative_path": "Data/PACK10_01.PAK",
            "input_archive_sha256": baseline_sha,
            "input_archive_size": baseline_size,
            "successful_profile_ids": [
                "height_fog_shader_original_code",
                "water_shader_swater_original_code",
            ],
            "installed_game_modified": False,
        })

        evidence = reports / TOOL.G1S_REPACK_TEST_EVIDENCE_DIR
        evidence.mkdir(parents=True, exist_ok=True)
        TOOL.atomic_json(evidence / "SUMMARY.json", {
            "type": "br_quartet_restoration_g1s_repack_test_evidence_summary",
            "format_version": 1,
            "tool_version": "0.0.33",
            "status": "local_checksum_gated_g1s_repack_test_archives_built_not_installed",
            "profile_rows": 2,
            "file_rows": 2,
            "validation_rows": 4,
            "validation_failures": 0,
            "input_archive_relative_path": "Data/PACK10_01.PAK",
            "input_archive_sha256": baseline_sha,
            "input_archive_size": baseline_size,
        })
        definitions = [
            (
                "height_fog_shader_original_code", "height_fog_shader",
                "steam_or_vapor_occlusion", "high", b"height-profile-pack10",
                "data/b1/x64/shader/heightfog.g1s",
            ),
            (
                "water_shader_swater_original_code", "water_shader_swater",
                "water_visibility", "critical", b"water-profile-pack10",
                "data/b1/x64/shader/swater.g1s",
            ),
        ]
        profile_rows = []
        file_rows = []
        validation_rows = []
        for profile_id, rule_id, domain, priority, payload, member in definitions:
            output = harness / f"profiles/{profile_id}/output/Data/PACK10_01.PAK"
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_bytes(payload)
            output_sha = TOOL.sha256_file(output)
            profile_rows.append({
                "prototype_id": profile_id,
                "rule_id": rule_id,
                "domain": domain,
                "priority": priority,
                "input_archive_relative_path": "Data/PACK10_01.PAK",
                "input_archive_sha256": baseline_sha,
                "input_archive_size": baseline_size,
                "output_archive_sha256": output_sha,
                "output_archive_size": output.stat().st_size,
                "replaced_member_count": 1,
                "unchanged_member_count_verified": 489,
                "local_output_archive": output.relative_to(project).as_posix(),
                "local_rollback_archive": baseline_archive.relative_to(project).as_posix(),
                "validation_status": "passed",
                "runtime_validation_status": "deferred_until_relevant_scene_save_available",
                "activation_status": "not_generated_requires_unified_patcher_core_transaction",
            })
            file_rows.append({
                "prototype_id": profile_id,
                "rule_id": rule_id,
                "domain": domain,
                "priority": priority,
                "normalized_path": member.replace("data/b1/", "data/"),
                "target_archive": "Data/PACK10_01.PAK",
                "target_member_path": member,
                "validation_status": "passed",
            })
            validation_rows.extend([
                {"prototype_id": profile_id, "check_name": "modified_member_matches_candidate", "passed": True, "details": ""},
                {"prototype_id": profile_id, "check_name": "all_unchanged_members_preserved", "passed": True, "details": "checked=489;mismatches=0"},
            ])
        TOOL.write_tsv(evidence / "G1S_REPACK_TEST_PROFILES.tsv", [
            "prototype_id", "rule_id", "domain", "priority",
            "input_archive_relative_path", "input_archive_sha256", "input_archive_size",
            "output_archive_sha256", "output_archive_size", "replaced_member_count",
            "unchanged_member_count_verified", "local_output_archive", "local_rollback_archive",
            "validation_status", "runtime_validation_status", "activation_status",
        ], profile_rows)
        TOOL.write_tsv(evidence / "G1S_REPACK_TEST_FILES.tsv", [
            "prototype_id", "rule_id", "domain", "priority", "normalized_path",
            "target_archive", "target_member_path", "validation_status",
        ], file_rows)
        TOOL.write_tsv(evidence / "G1S_REPACK_TEST_VALIDATION.tsv", [
            "prototype_id", "check_name", "passed", "details",
        ], validation_rows)
        return project, workspace, reports, quartet, archive, harness

    def test_g1s_activation_request_validates_profiles_without_game_write(self):
        with tempfile.TemporaryDirectory() as temporary:
            project, workspace, reports, quartet, archive, _ = self._prepare_stage27_artifacts(Path(temporary))
            installed_before = TOOL.sha256_file(archive)
            output, summary = TOOL.prepare_g1s_activation_request(
                project_root=project, quartet_root=quartet,
                workspace_root=workspace, report_root=reports,
            )
            self.assertTrue(output.is_file())
            self.assertEqual(summary["profile_rows"], 2)
            self.assertTrue(summary["target_sha256_matches_baseline"])
            self.assertEqual(summary["runtime_validated_profile_rows"], 0)
            self.assertFalse(summary["installed_game_modified"])
            self.assertFalse(summary["activation_or_rollback_generated"])
            self.assertEqual(TOOL.sha256_file(archive), installed_before)
            evidence = reports / TOOL.G1S_ACTIVATION_REQUEST_EVIDENCE_DIR
            request = TOOL.load_json(evidence / "CORE_ACTIVATION_REQUEST.json")
            self.assertEqual(request["type"], "br_quartet_restoration_core_g1s_activation_request")
            self.assertEqual(request["installed_target_relative_path"], "Data/PACK10_01.PAK")
            self.assertEqual([row["profile_id"] for row in request["profiles"]], [
                "height_fog_shader_original_code", "water_shader_swater_original_code",
            ])
            self.assertTrue(all(row["expected_target_sha256_before_activation"] == installed_before for row in request["profiles"]))
            self.assertFalse(any(path.suffix.casefold() == ".pak" for path in evidence.rglob("*")))
            runtime = TOOL.read_tsv(evidence / "RUNTIME_TEST_MATRIX.tsv")
            self.assertEqual([row["test_order"] for row in runtime], ["1", "2"])
            requirements = TOOL.read_tsv(evidence / "CORE_TRANSACTION_REQUIREMENTS.tsv")
            self.assertTrue(any("PACK10_01.PAK" in row["requirement"] for row in requirements))

    def test_g1s_activation_request_rejects_changed_installed_pack10(self):
        with tempfile.TemporaryDirectory() as temporary:
            project, workspace, reports, quartet, archive, _ = self._prepare_stage27_artifacts(Path(temporary))
            archive.write_bytes(archive.read_bytes() + b"changed-after-stage27")
            with self.assertRaisesRegex(TOOL.RestorationError, "changed after stage 27"):
                TOOL.prepare_g1s_activation_request(
                    project_root=project, quartet_root=quartet,
                    workspace_root=workspace, report_root=reports,
                )

    def test_g1s_activation_request_rejects_tampered_local_profile(self):
        with tempfile.TemporaryDirectory() as temporary:
            project, workspace, reports, quartet, _, harness = self._prepare_stage27_artifacts(Path(temporary))
            profile = harness / "profiles/height_fog_shader_original_code/output/Data/PACK10_01.PAK"
            profile.write_bytes(profile.read_bytes() + b"tampered")
            with self.assertRaisesRegex(TOOL.RestorationError, "checksum mismatch"):
                TOOL.prepare_g1s_activation_request(
                    project_root=project, quartet_root=quartet,
                    workspace_root=workspace, report_root=reports,
                )


class SingleSceneCompositeEvidenceTests(unittest.TestCase):
    @staticmethod
    def _payload(words):
        def lp(raw: bytes) -> bytes:
            return struct.pack("<I", len(raw)) + raw
        prefix = struct.pack("<II", 3, 0) + lp(b"name\0") + lp("説明".encode("cp932") + b"\0")
        return prefix + struct.pack(f"<{len(words)}I", *words)

    def test_construct_composite_inverse_event_candidate_restores_two_separate_inserts(self):
        source = self._payload([
            1, 0x75400009, 0x74100013, 0x7F000000,
            1, 0x7540000A, 0x75100001, 0x7F000000,
        ])
        target = self._payload([
            1, 0x75400009, 0x74100013, 0x74100014, 0x7F000000,
            1, 0x7540000A, 0x75100001, 0x7500002C, 0x7F000000,
        ])
        sh = TOOL.parse_ebd_header_schema(source)
        th = TOOL.parse_ebd_header_schema(target)
        sp = TOOL.profile_ebd_post_header_words(source, int(sh["header_end"]))
        tp = TOOL.profile_ebd_post_header_words(target, int(th["header_end"]))
        deltas = TOOL.compare_ebd_tag_atoms(sp["atoms"], tp["atoms"])
        selected = []
        per_shape = Counter()
        for delta in deltas:
            shape_id = TOOL.event_residual_delta_shape_id(delta)
            selected.append({
                "shape_id": shape_id,
                "occurrence_index": per_shape[shape_id],
                "cue_domains": "steam_or_vapor",
                "selection_reasons": "domain_single_scene_context_shape",
            })
            per_shape[shape_id] += 1
        candidate, metadata, residuals = TOOL.construct_composite_inverse_event_candidate(
            source_payload=source, target_payload=target, selected_occurrences=selected,
        )
        self.assertEqual(candidate, source)
        self.assertTrue(metadata["all_selected_shapes_removed"])
        self.assertTrue(metadata["candidate_equals_source_payload"])
        self.assertEqual(metadata["introduced_coarse_shape_count"], 0)
        self.assertEqual(residuals, [])

    def test_collect_single_scene_composite_evidence_reports_exact_match_without_writing_candidate(self):
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary)
            workspace = project / ".local/build/quartet_restoration"
            reports = project / ".local/reports/quartet_restoration"
            context = reports / TOOL.EVENT_DELTA_CONTEXT_EVIDENCE_DIR
            migration = reports / TOOL.EVENT_TAG_MIGRATION_EVIDENCE_DIR
            differences = reports / "differences"
            context.mkdir(parents=True)
            migration.mkdir(parents=True)
            differences.mkdir(parents=True)
            TOOL.atomic_json(context / "SUMMARY.json", {
                "type": "br_quartet_restoration_event_delta_context_evidence_summary",
                "tool_version": "0.0.27",
            })
            TOOL.atomic_json(migration / "SUMMARY.json", {
                "type": "br_quartet_restoration_event_tag_migration_evidence_summary",
                "tool_version": "0.0.24",
            })
            TOOL.write_tsv(migration / "EVENT_TAG_SCHEMA_MIGRATION_CANDIDATES.tsv", [
                "sequence_tag","source_atom_count","target_atom_count","source_tag_values","target_tag_values","classification",
            ], [])

            source = self._payload([
                1, 0x75400009, 0x74100013, 0x7F000000,
                1, 0x7540000A, 0x75100001, 0x7F000000,
            ])
            target = self._payload([
                1, 0x75400009, 0x74100013, 0x74100014, 0x7F000000,
                1, 0x7540000A, 0x75100001, 0x7500002C, 0x7F000000,
            ])
            sh = TOOL.parse_ebd_header_schema(source)
            th = TOOL.parse_ebd_header_schema(target)
            sp = TOOL.profile_ebd_post_header_words(source, int(sh["header_end"]))
            tp = TOOL.profile_ebd_post_header_words(target, int(th["header_end"]))
            deltas = TOOL.compare_ebd_tag_atoms(sp["atoms"], tp["atoms"])
            path = "event/event_jp/ce11/event_ce11_070.ebd"
            source_item = entry(path, source, "DATA/PACK01.PAK")
            target_item = entry("event/b1/event_jp/ce11/event_ce11_070.ebd", target, "Data/PACK11.PAK")
            target_item["normalized_path"] = path
            target_item["comparison_key"] = path.casefold()
            TOOL.atomic_json(differences / "br1_events.json", {
                "source_archive_group": "br1_events",
                "entries": [{
                    "classification": "changed", "scope_status": "in_scope", "normalized_path": path,
                    "source": TOOL.file_ref(source_item), "target": TOOL.file_ref(target_item),
                }],
            })
            for side, item, payload in (("source", source_item, source), ("target", target_item, target)):
                output = TOOL.inventory_workspace_file(workspace, side, "br1_events", item["archive"], item["path"])
                output.parent.mkdir(parents=True, exist_ok=True)
                output.write_bytes(payload)

            occurrence_rows = []
            splice_rows = []
            per_shape = Counter()
            for delta in deltas:
                shape_id = TOOL.event_residual_delta_shape_id(delta)
                index = per_shape[shape_id]
                per_shape[shape_id] += 1
                occurrence_rows.append({
                    "normalized_path": path, "shape_id": shape_id, "occurrence_index": index,
                    "sequence_tag": delta["sequence_tag"], "event_message_classification": "identical",
                    "cue_positive_occurrence": True, "cue_rule_ids": "steam_yuge",
                    "cue_domains": "steam_or_vapor", "selection_reasons": "domain_single_scene_context_shape",
                })
                splice_rows.append({
                    "normalized_path": path, "shape_id": shape_id, "occurrence_index": index,
                    "cue_positive_occurrence": True, "cue_domains": "steam_or_vapor",
                    "selection_reasons": "domain_single_scene_context_shape",
                    "candidate_sha256": "a" * 64,
                    "in_memory_splice_status": "selected_shape_removed_without_other_coarse_delta_changes",
                })
            TOOL.write_tsv(context / "EVENT_DELTA_CONTEXT_OCCURRENCES.tsv", [
                "normalized_path","shape_id","occurrence_index","sequence_tag","event_message_classification",
                "cue_positive_occurrence","cue_rule_ids","cue_domains","selection_reasons",
            ], occurrence_rows)
            TOOL.write_tsv(context / "IN_MEMORY_EVENT_DELTA_SPLICE_READINESS.tsv", [
                "normalized_path","shape_id","occurrence_index","cue_positive_occurrence","cue_domains",
                "selection_reasons","candidate_sha256","in_memory_splice_status",
            ], splice_rows)

            output, summary = TOOL.collect_single_scene_composite_evidence(
                project_root=project, workspace_root=workspace, report_root=reports,
                maximum_event_bytes=1024 * 1024, maximum_splices_per_event=16,
            )
            self.assertTrue(output.is_file())
            self.assertEqual(summary["analyzed_event_rows"], 1)
            self.assertEqual(summary["critical_candidate_rows"], 1)
            self.assertEqual(summary["exact_original_match_rows"], 1)
            rows = TOOL.read_tsv(reports / TOOL.SINGLE_SCENE_COMPOSITE_EVIDENCE_DIR / "SINGLE_SCENE_COMPOSITE_EVENTS.tsv")
            self.assertEqual(rows[0]["classification"], "exact_original_payload_match_after_composite_inverse")
            self.assertFalse(any(path.suffix.casefold() == ".ebd" for path in (reports / TOOL.SINGLE_SCENE_COMPOSITE_EVIDENCE_DIR).rglob("*")))


class SingleSceneEventPrototypeTests(unittest.TestCase):
    @staticmethod
    def _payload(words):
        def lp(raw: bytes) -> bytes:
            return struct.pack("<I", len(raw)) + raw
        prefix = struct.pack("<II", 3, 0) + lp(b"name\0") + lp("説明".encode("cp932") + b"\0")
        return prefix + struct.pack(f"<{len(words)}I", *words)

    def test_restore_target_from_composite_operations_roundtrips_two_splices(self):
        source = self._payload([
            1, 0x75400009, 0x74100013, 0x7F000000,
            1, 0x7540000A, 0x75100001, 0x7F000000,
        ])
        target = self._payload([
            1, 0x75400009, 0x74100013, 0x74100014, 0x7F000000,
            1, 0x7540000A, 0x75100001, 0x7500002C, 0x7F000000,
        ])
        sh = TOOL.parse_ebd_header_schema(source)
        th = TOOL.parse_ebd_header_schema(target)
        sp = TOOL.profile_ebd_post_header_words(source, int(sh["header_end"]))
        tp = TOOL.profile_ebd_post_header_words(target, int(th["header_end"]))
        deltas = TOOL.compare_ebd_tag_atoms(sp["atoms"], tp["atoms"])
        selected = []
        per_shape = Counter()
        for delta in deltas:
            shape_id = TOOL.event_residual_delta_shape_id(delta)
            selected.append({"shape_id": shape_id, "occurrence_index": per_shape[shape_id]})
            per_shape[shape_id] += 1
        candidate, _, _ = TOOL.construct_composite_inverse_event_candidate(
            source_payload=source, target_payload=target, selected_occurrences=selected,
        )
        self.assertEqual(candidate, source)
        operations = []
        for row in selected:
            matches = [d for d in deltas if TOOL.event_residual_delta_shape_id(d) == row["shape_id"]]
            delta = matches[row["occurrence_index"]]
            ss, se = TOOL.event_atom_word_span(sp["atoms"], int(delta["source_atom_start"]), int(delta["source_atom_end"]), int(sp["word_count"]))
            ts, te = TOOL.event_atom_word_span(tp["atoms"], int(delta["target_atom_start"]), int(delta["target_atom_end"]), int(tp["word_count"]))
            operations.append({
                "target_start": ts, "target_end": te,
                "source_words": list(sp["words"])[ss:se],
                "target_words": list(tp["words"])[ts:te],
            })
        rebuilt = TOOL._restore_target_from_composite_operations(
            candidate_payload=candidate, target_payload=target,
            target_header_end=int(th["header_end"]), operations=operations,
        )
        self.assertEqual(rebuilt, target)

    def test_build_single_scene_event_prototype_accepts_known_schema_only_residual(self):
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary)
            workspace = project / ".local/build/quartet_restoration"
            reports = project / ".local/reports/quartet_restoration"
            composite = reports / TOOL.SINGLE_SCENE_COMPOSITE_EVIDENCE_DIR
            migration = reports / TOOL.EVENT_TAG_MIGRATION_EVIDENCE_DIR
            differences = reports / "differences"
            composite.mkdir(parents=True)
            migration.mkdir(parents=True)
            differences.mkdir(parents=True)
            TOOL.atomic_json(composite / "SUMMARY.json", {
                "type": "br_quartet_restoration_single_scene_composite_evidence_summary",
                "tool_version": "0.0.35",
            })
            TOOL.atomic_json(migration / "SUMMARY.json", {
                "type": "br_quartet_restoration_event_tag_migration_evidence_summary",
                "tool_version": "0.0.24",
            })

            source = self._payload([
                1, 0x75400009, 0x74100013, 0x7F000000,
                1, 0x7540000A, 0x75100001, 0x7F000000,
            ])
            target = self._payload([
                1, 0x75400009, 0x74100013, 0x74100014, 0x7F000000,
                1, 0x7540000A, 0x75100001, 0x750000A2, 0x7F000000,
            ])
            sh = TOOL.parse_ebd_header_schema(source)
            th = TOOL.parse_ebd_header_schema(target)
            sp = TOOL.profile_ebd_post_header_words(source, int(sh["header_end"]))
            tp = TOOL.profile_ebd_post_header_words(target, int(th["header_end"]))
            deltas = TOOL.compare_ebd_tag_atoms(sp["atoms"], tp["atoms"])
            self.assertEqual(len(deltas), 2)
            selected_delta = next(row for row in deltas if "0x74100014" in str(row.get("target_tag_values", "")))
            migration_delta = next(row for row in deltas if "0x750000a2" in str(row.get("target_tag_values", "")).casefold())
            selected_shape = TOOL.event_residual_delta_shape_id(selected_delta)
            candidate, metadata, residuals = TOOL.construct_composite_inverse_event_candidate(
                source_payload=source, target_payload=target,
                selected_occurrences=[{
                    "shape_id": selected_shape, "occurrence_index": 0,
                    "cue_domains": "shower", "selection_reasons": "domain_single_scene_context_shape",
                }],
            )
            self.assertIsNotNone(candidate)
            self.assertEqual(len(residuals), 1)
            migration_row = dict(migration_delta)
            migration_row["classification"] = "broad_schema_migration_candidate"
            TOOL.write_tsv(migration / "EVENT_TAG_SCHEMA_MIGRATION_CANDIDATES.tsv", [
                "sequence_tag","source_atom_count","target_atom_count","source_tag_values","target_tag_values","classification",
            ], [migration_row])

            path = "event/event_jp/te02/event_te02_230.ebd"
            source_item = entry(path, source, "DATA/PACK01.PAK")
            target_item = entry("event/b1/event_jp/te02/event_te02_230.ebd", target, "Data/PACK11.PAK")
            target_item["normalized_path"] = path
            target_item["comparison_key"] = path.casefold()
            TOOL.atomic_json(differences / "br1_events.json", {
                "source_archive_group": "br1_events",
                "entries": [{
                    "classification": "changed", "scope_status": "in_scope", "normalized_path": path,
                    "source": TOOL.file_ref(source_item), "target": TOOL.file_ref(target_item),
                }],
            })
            for side, item, payload in (("source", source_item, source), ("target", target_item, target)):
                output = TOOL.inventory_workspace_file(workspace, side, "br1_events", item["archive"], item["path"])
                output.parent.mkdir(parents=True, exist_ok=True)
                output.write_bytes(payload)

            TOOL.write_tsv(composite / "SINGLE_SCENE_COMPOSITE_EVENTS.tsv", [
                "normalized_path","cue_domains","selected_splice_count","candidate_sha256","classification",
                "known_schema_residual_rows","unknown_residual_rows","candidate_byte_difference_to_source",
                "target_byte_difference_to_source",
            ], [{
                "normalized_path": path, "cue_domains": "shower", "selected_splice_count": 1,
                "candidate_sha256": metadata["candidate_sha256"],
                "classification": "residual_only_known_schema_migrations_after_composite_inverse",
                "known_schema_residual_rows": 1, "unknown_residual_rows": 0,
                "candidate_byte_difference_to_source": metadata["candidate_byte_difference_to_source"],
                "target_byte_difference_to_source": metadata["target_byte_difference_to_source"],
            }])
            TOOL.write_tsv(composite / "FOCUSED_SINGLE_SCENE_COMPOSITE_REVIEW.tsv", [
                "normalized_path","classification","review_priority","next_gate",
            ], [{
                "normalized_path": path,
                "classification": "residual_only_known_schema_migrations_after_composite_inverse",
                "review_priority": "critical",
                "next_gate": "eligible_for_separate_local_single_scene_prototype_review",
            }])
            TOOL.write_tsv(composite / "SINGLE_SCENE_COMPOSITE_SPLICES.tsv", [
                "normalized_path","shape_id","occurrence_index","cue_domains","selection_reasons",
            ], [{
                "normalized_path": path, "shape_id": selected_shape, "occurrence_index": 0,
                "cue_domains": "shower", "selection_reasons": "domain_single_scene_context_shape",
            }])

            output, summary = TOOL.build_single_scene_event_prototypes(
                project_root=project, workspace_root=workspace, report_root=reports,
                maximum_event_bytes=1024 * 1024,
            )
            self.assertTrue(output.is_file())
            self.assertEqual(summary["eligible_profile_rows"], 1)
            self.assertEqual(summary["validation_failures"], 0)
            profile_rows = TOOL.read_tsv(reports / TOOL.SINGLE_SCENE_EVENT_PROTOTYPE_EVIDENCE_DIR / "SINGLE_SCENE_EVENT_PROTOTYPE_PROFILES.tsv")
            self.assertEqual(profile_rows[0]["normalized_path"], path)
            profile_id = profile_rows[0]["profile_id"]
            candidate_path = workspace / TOOL.SINGLE_SCENE_EVENT_PROTOTYPE_BUILD_DIR / profile_id / "payload" / path
            self.assertEqual(candidate_path.read_bytes(), candidate)
            self.assertFalse(any(item.suffix.casefold() == ".ebd" for item in (reports / TOOL.SINGLE_SCENE_EVENT_PROTOTYPE_EVIDENCE_DIR).rglob("*")))

    def test_build_single_scene_event_prototype_does_not_promote_high_unknown_residual(self):
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary)
            reports = project / ".local/reports/quartet_restoration"
            composite = reports / TOOL.SINGLE_SCENE_COMPOSITE_EVIDENCE_DIR
            migration = reports / TOOL.EVENT_TAG_MIGRATION_EVIDENCE_DIR
            composite.mkdir(parents=True)
            migration.mkdir(parents=True)
            TOOL.atomic_json(composite / "SUMMARY.json", {"type": "br_quartet_restoration_single_scene_composite_evidence_summary", "tool_version": "0.0.35"})
            TOOL.atomic_json(migration / "SUMMARY.json", {"type": "br_quartet_restoration_event_tag_migration_evidence_summary", "tool_version": "0.0.24"})
            TOOL.write_tsv(migration / "EVENT_TAG_SCHEMA_MIGRATION_CANDIDATES.tsv", [
                "sequence_tag","source_atom_count","target_atom_count","source_tag_values","target_tag_values","classification",
            ], [])
            TOOL.write_tsv(composite / "SINGLE_SCENE_COMPOSITE_EVENTS.tsv", [
                "normalized_path","classification","unknown_residual_rows",
            ], [{"normalized_path": "event/event_jp/ce11/event_ce11_070.ebd", "classification": "selected_single_scene_shapes_removed_unknown_residuals_remain", "unknown_residual_rows": 3}])
            TOOL.write_tsv(composite / "FOCUSED_SINGLE_SCENE_COMPOSITE_REVIEW.tsv", [
                "normalized_path","classification","review_priority","next_gate",
            ], [{
                "normalized_path": "event/event_jp/ce11/event_ce11_070.ebd",
                "classification": "selected_single_scene_shapes_removed_unknown_residuals_remain",
                "review_priority": "high",
                "next_gate": "retain_as_evidence_until_additional_context_or_runtime_scene_confirmation",
            }])
            TOOL.write_tsv(composite / "SINGLE_SCENE_COMPOSITE_SPLICES.tsv", [
                "normalized_path","shape_id","occurrence_index","cue_domains","selection_reasons",
            ], [])
            (reports / "differences").mkdir(parents=True)
            TOOL.atomic_json(reports / "differences/br1_events.json", {"source_archive_group": "br1_events", "entries": []})
            output, summary = TOOL.build_single_scene_event_prototypes(
                project_root=project,
                workspace_root=project / ".local/build/quartet_restoration",
                report_root=reports,
                maximum_event_bytes=1024 * 1024,
            )
            self.assertTrue(output.is_file())
            self.assertEqual(summary["eligible_profile_rows"], 0)
            self.assertEqual(summary["prototype_file_rows"], 0)


class SingleSceneEventRepackTestHarnessTests(unittest.TestCase):
    def test_single_scene_event_repack_harness_builds_separate_pack11_profile(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            project = root / "project"
            workspace = project / ".local/build/quartet_restoration"
            reports = project / ".local/reports/quartet_restoration"
            quartet = root / "quartet"
            gust_pak = root / "gust_pak"
            helper = EventRepackTestHarnessTests(methodName="runTest")
            helper._write_fake_gust_pak(gust_pak)

            target_member = "event/b1/event_jp/te02/event_te02_230.ebd"
            members = {
                target_member: b"quartet-single-scene-target",
                "event/b1/event_en/te02/event_te02_230.ebd": b"unrelated-current-translation",
                "event/b1/event_jp/ce01/event_ce01_010.ebd": b"unrelated-event",
            }
            archive = quartet / "Data/PACK11.PAK"
            helper._write_fake_pak(archive, members)
            installed_before = TOOL.sha256_file(archive)

            reports.mkdir(parents=True)
            TOOL.write_tsv(reports / "ARCHIVE_INVENTORY.tsv", [
                "pair_id", "side", "archive", "sha256",
            ], [{
                "pair_id": "br1_events", "side": "target", "archive": "Data/PACK11.PAK",
                "sha256": installed_before,
            }])

            evidence = reports / TOOL.SINGLE_SCENE_EVENT_PROTOTYPE_EVIDENCE_DIR
            evidence.mkdir(parents=True)
            profile_id = "single_scene_event_te02_230_test"
            candidate = b"candidate-single-scene-restoration"
            target_sha = hashlib.sha256(members[target_member]).hexdigest()
            candidate_sha = hashlib.sha256(candidate).hexdigest()
            TOOL.atomic_json(evidence / "SUMMARY.json", {
                "type": "br_quartet_restoration_single_scene_event_prototype_evidence_summary",
                "tool_version": "0.0.36",
                "validation_failures": 0,
            })
            TOOL.write_tsv(evidence / "SINGLE_SCENE_EVENT_PROTOTYPE_FILES.tsv", [
                "profile_id", "normalized_path", "target_archive", "target_member_path",
                "target_sha256", "candidate_sha256", "local_relative_path",
            ], [{
                "profile_id": profile_id,
                "normalized_path": "event/event_jp/te02/event_te02_230.ebd",
                "target_archive": "Data/PACK11.PAK",
                "target_member_path": target_member,
                "target_sha256": target_sha,
                "candidate_sha256": candidate_sha,
                "local_relative_path": "payload/event/event_jp/te02/event_te02_230.ebd",
            }])

            profile_root = workspace / TOOL.SINGLE_SCENE_EVENT_PROTOTYPE_BUILD_DIR / profile_id
            candidate_rel = "payload/event/event_jp/te02/event_te02_230.ebd"
            candidate_path = profile_root / candidate_rel
            candidate_path.parent.mkdir(parents=True, exist_ok=True)
            candidate_path.write_bytes(candidate)
            TOOL.atomic_json(profile_root / "PROTOTYPE.json", {
                "type": "br_quartet_restoration_local_single_scene_event_prototype",
                "format_version": 1,
                "tool_version": "0.0.36",
                "profile_id": profile_id,
                "profile_classification": "critical_single_scene_known_schema_only_local_prototype",
                "prototype_confidence": "critical_structural_runtime_unvalidated",
                "normalized_path": "event/event_jp/te02/event_te02_230.ebd",
                "target_sha256": target_sha,
                "candidate_sha256": candidate_sha,
                "candidate_relative_path": candidate_rel,
                "installable_package_generated": False,
                "runtime_validated": False,
            })

            old_event_root = workspace / TOOL.EVENT_REPACK_TEST_BUILD_DIR
            old_event_root.mkdir(parents=True)
            (old_event_root / "existing-stage25-sentinel.txt").write_text("keep", encoding="utf-8")

            output, summary = TOOL.prepare_single_scene_event_repack_tests(
                project_root=project,
                quartet_root=quartet,
                gust_pak=gust_pak,
                workspace_root=workspace,
                report_root=reports,
                timeout_seconds=30,
            )
            self.assertTrue(output.is_file())
            self.assertEqual(summary["profile_rows"], 1)
            self.assertEqual(summary["critical_profile_rows"], 1)
            self.assertEqual(summary["validation_failures"], 0)
            self.assertEqual(TOOL.sha256_file(archive), installed_before)
            self.assertTrue((old_event_root / "existing-stage25-sentinel.txt").is_file())

            output_pak = (
                workspace / TOOL.SINGLE_SCENE_EVENT_REPACK_TEST_BUILD_DIR
                / "profiles" / profile_id / "output/Data/PACK11.PAK"
            )
            self.assertTrue(output_pak.is_file())
            self.assertEqual(helper._read_fake_pak_member(output_pak, target_member), candidate)
            self.assertEqual(
                helper._read_fake_pak_member(output_pak, "event/b1/event_en/te02/event_te02_230.ebd"),
                b"unrelated-current-translation",
            )
            self.assertFalse(any(path.suffix.casefold() == ".pak" for path in evidence.rglob("*")))

    def test_single_scene_event_repack_rejects_changed_target_member(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            project = root / "project"
            workspace = project / ".local/build/quartet_restoration"
            reports = project / ".local/reports/quartet_restoration"
            quartet = root / "quartet"
            gust_pak = root / "gust_pak"
            helper = EventRepackTestHarnessTests(methodName="runTest")
            helper._write_fake_gust_pak(gust_pak)
            target_member = "event/b1/event_jp/te02/event_te02_230.ebd"
            archive = quartet / "Data/PACK11.PAK"
            helper._write_fake_pak(archive, {target_member: b"changed-current-target"})
            archive_sha = TOOL.sha256_file(archive)
            reports.mkdir(parents=True)
            TOOL.write_tsv(reports / "ARCHIVE_INVENTORY.tsv", ["pair_id","side","archive","sha256"], [{
                "pair_id":"br1_events","side":"target","archive":"Data/PACK11.PAK","sha256":archive_sha,
            }])
            evidence = reports / TOOL.SINGLE_SCENE_EVENT_PROTOTYPE_EVIDENCE_DIR
            evidence.mkdir(parents=True)
            TOOL.atomic_json(evidence / "SUMMARY.json", {
                "type":"br_quartet_restoration_single_scene_event_prototype_evidence_summary",
                "tool_version":"0.0.36","validation_failures":0,
            })
            profile_id = "single_scene_event_te02_230_test"
            expected_target = b"older-target"
            candidate = b"candidate"
            TOOL.write_tsv(evidence / "SINGLE_SCENE_EVENT_PROTOTYPE_FILES.tsv", [
                "profile_id","normalized_path","target_archive","target_member_path","target_sha256","candidate_sha256","local_relative_path",
            ], [{
                "profile_id":profile_id,"normalized_path":"event/event_jp/te02/event_te02_230.ebd",
                "target_archive":"Data/PACK11.PAK","target_member_path":target_member,
                "target_sha256":hashlib.sha256(expected_target).hexdigest(),
                "candidate_sha256":hashlib.sha256(candidate).hexdigest(),
                "local_relative_path":"payload/event/event_jp/te02/event_te02_230.ebd",
            }])
            profile_root = workspace / TOOL.SINGLE_SCENE_EVENT_PROTOTYPE_BUILD_DIR / profile_id
            candidate_path = profile_root / "payload/event/event_jp/te02/event_te02_230.ebd"
            candidate_path.parent.mkdir(parents=True, exist_ok=True)
            candidate_path.write_bytes(candidate)
            TOOL.atomic_json(profile_root / "PROTOTYPE.json", {
                "type":"br_quartet_restoration_local_single_scene_event_prototype",
                "profile_id":profile_id,"profile_classification":"critical_single_scene_known_schema_only_local_prototype",
                "prototype_confidence":"critical_structural_runtime_unvalidated",
                "target_sha256":hashlib.sha256(expected_target).hexdigest(),
                "candidate_sha256":hashlib.sha256(candidate).hexdigest(),
                "candidate_relative_path":"payload/event/event_jp/te02/event_te02_230.ebd",
                "installable_package_generated":False,
            })
            _, summary = TOOL.prepare_single_scene_event_repack_tests(
                project_root=project, quartet_root=quartet, gust_pak=gust_pak,
                workspace_root=workspace, report_root=reports, timeout_seconds=30,
            )
            self.assertEqual(summary["profile_rows"], 0)
            self.assertGreater(summary["skipped_rows"], 0)
            skipped = TOOL.read_tsv(
                reports / TOOL.SINGLE_SCENE_EVENT_REPACK_TEST_EVIDENCE_DIR
                / "SINGLE_SCENE_EVENT_REPACK_TEST_BUILD_SKIPPED.tsv"
            )
            self.assertIn("current_target_member_sha256_mismatch", {row["reason"] for row in skipped})
            self.assertEqual(TOOL.sha256_file(archive), archive_sha)


class SingleSceneEventActivationRequestTests(unittest.TestCase):
    def _prepare_fixture(self, root: Path):
        project = root / "project"
        workspace = project / ".local/build/quartet_restoration"
        reports = project / ".local/reports/quartet_restoration"
        quartet = root / "quartet"
        archive = quartet / "Data/PACK11.PAK"
        archive.parent.mkdir(parents=True, exist_ok=True)
        archive.write_bytes(b"shared-pack11-baseline")
        baseline_sha = TOOL.sha256_file(archive)
        baseline_size = archive.stat().st_size

        evidence = reports / TOOL.SINGLE_SCENE_EVENT_REPACK_TEST_EVIDENCE_DIR
        evidence.mkdir(parents=True, exist_ok=True)
        profile_id = "single_scene_event_te02_230_test"
        profile_payload = b"single-scene-pack11-profile"
        output_rel = (
            ".local/build/quartet_restoration/repack_tests/events_single_scene/"
            f"profiles/{profile_id}/output/Data/PACK11.PAK"
        )
        output_path = project / output_rel
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(profile_payload)
        output_sha = TOOL.sha256_file(output_path)
        output_size = output_path.stat().st_size

        TOOL.atomic_json(evidence / "SUMMARY.json", {
            "type": "br_quartet_restoration_single_scene_event_repack_test_evidence_summary",
            "tool_version": "0.0.37",
            "validation_failures": 0,
            "profile_rows": 1,
            "input_archive_relative_path": "Data/PACK11.PAK",
            "input_archive_sha256": baseline_sha,
            "input_archive_size": baseline_size,
        })
        TOOL.write_tsv(evidence / "SINGLE_SCENE_EVENT_REPACK_TEST_PROFILES.tsv", [
            "profile_id", "profile_classification", "prototype_confidence",
            "output_archive_sha256", "output_archive_size", "replaced_member_count",
            "unchanged_member_count_verified", "local_output_archive", "validation_status",
        ], [{
            "profile_id": profile_id,
            "profile_classification": "critical_single_scene_known_schema_only_local_prototype",
            "prototype_confidence": "critical_structural_runtime_unvalidated",
            "output_archive_sha256": output_sha,
            "output_archive_size": output_size,
            "replaced_member_count": 1,
            "unchanged_member_count_verified": 9396,
            "local_output_archive": output_rel,
            "validation_status": "passed",
        }])
        TOOL.write_tsv(evidence / "SINGLE_SCENE_EVENT_REPACK_TEST_FILES.tsv", [
            "profile_id", "target_member_path", "validation_status",
        ], [{
            "profile_id": profile_id,
            "target_member_path": "event/b1/event_jp/te02/event_te02_230.ebd",
            "validation_status": "passed",
        }])
        TOOL.write_tsv(evidence / "SINGLE_SCENE_EVENT_REPACK_TEST_VALIDATION.tsv", [
            "profile_id", "check_name", "passed", "details",
        ], [
            {"profile_id": profile_id, "check_name": "all_unchanged_members_preserved", "passed": True, "details": "checked=9396;mismatches=0"},
            {"profile_id": profile_id, "check_name": "modified_members_match_candidates", "passed": True, "details": ""},
        ])

        harness = workspace / TOOL.SINGLE_SCENE_EVENT_REPACK_TEST_BUILD_DIR
        baseline = harness / "baseline/Data/PACK11.PAK"
        baseline.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(archive, baseline)
        TOOL.atomic_json(harness / "baseline/BASELINE.json", {
            "type": "br_quartet_restoration_local_single_scene_event_repack_test_baseline",
            "local_rollback_archive": "baseline/Data/PACK11.PAK",
        })
        TOOL.atomic_json(harness / TOOL.SINGLE_SCENE_EVENT_REPACK_TEST_MARKER, {
            "type": "br_quartet_restoration_local_single_scene_event_repack_test_harness",
            "successful_profile_ids": [profile_id],
        })
        return project, workspace, reports, quartet, archive, output_path, baseline_sha

    def test_single_scene_activation_request_registers_additional_existing_pack11_profile(self):
        with tempfile.TemporaryDirectory() as temporary:
            project, workspace, reports, quartet, archive, output_path, baseline_sha = self._prepare_fixture(Path(temporary))
            before = TOOL.sha256_file(archive)
            output, summary = TOOL.prepare_single_scene_event_activation_request(
                project_root=project, quartet_root=quartet,
                workspace_root=workspace, report_root=reports,
            )
            self.assertTrue(output.is_file())
            self.assertEqual(summary["profile_rows"], 1)
            self.assertTrue(summary["target_sha256_matches_baseline"])
            self.assertFalse(summary["installed_game_modified"])
            self.assertEqual(TOOL.sha256_file(archive), before)
            evidence = reports / TOOL.SINGLE_SCENE_EVENT_ACTIVATION_REQUEST_EVIDENCE_DIR
            request = TOOL.load_json(evidence / "CORE_ACTIVATION_REQUEST.json")
            self.assertEqual(request["type"], "br_quartet_restoration_core_single_scene_event_activation_request")
            self.assertTrue(request["policy"]["extend_existing_pack11_transaction_only"])
            self.assertTrue(request["policy"]["preserve_existing_event_profiles"])
            self.assertEqual(request["profiles"][0]["scene_id"], "te02_230")
            self.assertEqual(request["profiles"][0]["expected_target_sha256_before_activation"], baseline_sha)
            self.assertFalse(request["profiles"][0]["runtime_validated"])
            self.assertFalse(any(path.suffix.casefold() == ".pak" for path in evidence.rglob("*")))

    def test_single_scene_activation_request_rejects_changed_installed_pack11(self):
        with tempfile.TemporaryDirectory() as temporary:
            project, workspace, reports, quartet, archive, output_path, baseline_sha = self._prepare_fixture(Path(temporary))
            archive.write_bytes(archive.read_bytes() + b"changed-after-stage31")
            with self.assertRaisesRegex(TOOL.RestorationError, "changed after stage 31"):
                TOOL.prepare_single_scene_event_activation_request(
                    project_root=project, quartet_root=quartet,
                    workspace_root=workspace, report_root=reports,
                )

    def test_single_scene_activation_request_rejects_tampered_local_profile(self):
        with tempfile.TemporaryDirectory() as temporary:
            project, workspace, reports, quartet, archive, output_path, baseline_sha = self._prepare_fixture(Path(temporary))
            output_path.write_bytes(output_path.read_bytes() + b"tampered")
            with self.assertRaisesRegex(TOOL.RestorationError, "checksum mismatch"):
                TOOL.prepare_single_scene_event_activation_request(
                    project_root=project, quartet_root=quartet,
                    workspace_root=workspace, report_root=reports,
                )


if __name__ == "__main__":
    unittest.main()
