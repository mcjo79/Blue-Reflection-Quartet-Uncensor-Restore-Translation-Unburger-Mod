from __future__ import annotations

import csv
import importlib.util
import json
import struct
import sys
import tempfile
import unittest
from unittest import mock
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
TOOL_PATH = ROOT / "workstreams/quartet_restoration/collect_structural_material_parameter_evidence.py"
SPEC = importlib.util.spec_from_file_location("collect_structural_material_parameter_evidence", TOOL_PATH)
assert SPEC and SPEC.loader
TOOL = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = TOOL
SPEC.loader.exec_module(TOOL)


def parameter_record(name: str, buffer_type: int, values: list[object], *, endian: str = "<") -> bytes:
    name_bytes = name.encode("utf-8") + b"\0"
    raw = bytearray()
    for value in values:
        if buffer_type == 1:
            raw.extend(struct.pack(endian + "f", float(value)))
        elif buffer_type == 4:
            raw.extend(struct.pack(endian + "4f", *value))
        elif buffer_type == 5:
            raw.extend(struct.pack(endian + "i", int(value)))
        else:
            raise ValueError(buffer_type)
    size = 16 + len(name_bytes) + len(raw)
    return struct.pack(endian + "3I2H", size, len(name_bytes), 0, buffer_type, len(values)) + name_bytes + raw


def g1m_blocks(blocks: list[list[tuple[str, int, list[object]]]], *, endian: str = "<") -> bytes:
    file_magic = b"_M1G" if endian == "<" else b"G1M_"
    block_payload = bytearray()
    for block in blocks:
        block_payload.extend(struct.pack(endian + "I", len(block)))
        for name, buffer_type, values in block:
            block_payload.extend(parameter_record(name, buffer_type, values, endian=endian))
    section = struct.pack(endian + "3I", TOOL.BR.G1MG_SHADER_PARAMS_SECTION, 12 + len(block_payload), len(blocks)) + block_payload
    g1mg_size = TOOL.BR.G1MG_HEADER_SIZE + len(section)
    g1mg = (
        b"G1MG"
        + struct.pack(endian + "2I", 0x30303430, g1mg_size)
        + b"DX11"
        + struct.pack(endian + "I6f", 0, 0.0, 0.0, 0.0, 1.0, 1.0, 1.0)
        + struct.pack(endian + "I", 1)
        + section
    )
    total = TOOL.BR.G1M_HEADER_SIZE + len(g1mg)
    return file_magic + struct.pack(endian + "5I", 0x30303430, total, TOOL.BR.G1M_HEADER_SIZE, 0, 1) + g1mg


def write_tsv(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields: list[str] = []
    for row in rows:
        for key in row:
            if key not in fields:
                fields.append(key)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def structural_row(index: int, *, candidate: str, path: str, member: str, classification: str, name: str,
                   source_block: str = "", target_block: str = "", source_param: str = "", target_param: str = "",
                   source_hex: str = "", target_hex: str = "") -> dict[str, object]:
    return {
        "row_id": f"row{index}",
        "group_id": f"group{index}",
        "source_row_index": index,
        "evidence_kind": "semantic_pair",
        "review_priority": "critical",
        "review_basis": "focused_scene_or_wet_material_parameter",
        "relation": "original_scene_vs_quartet_scene",
        "context_id": candidate,
        "domain": "steam_and_water_visibility",
        "priority": "critical",
        "pair_id": "br1_assets",
        "candidate_token": "",
        "counterpart_token": "",
        "source_archive_path": path,
        "target_archive_path": path,
        "quartet_variant_archive_path": "",
        "source_member_name": member,
        "target_member_name": member,
        "quartet_variant_member_name": "",
        "parameter_name": name,
        "parameter_name_folded": name.casefold(),
        "buffer_type": 4,
        "buffer_count": 1,
        "source_shader_block_index": source_block,
        "target_shader_block_index": target_block,
        "source_parameter_index": source_param,
        "target_parameter_index": target_param,
        "source_value_text": "1,1,1,1" if source_hex else "",
        "target_value_text": "1,1,1,1" if target_hex else "",
        "source_value_hex": source_hex,
        "target_value_hex": target_hex,
        "classification": classification,
        "disposition": "direct_material_structure_change_requires_format_aware_rebuild",
    }


def build_stage74(root: Path, rows: list[dict[str, object]]) -> None:
    report = root / ".local/reports/quartet_restoration/wet_coverage_material_variant_evidence"
    report.mkdir(parents=True)
    (report / "SUMMARY.json").write_text(json.dumps({
        "type": "br_quartet_restoration_wet_coverage_material_variant_evidence_summary",
        "tool_version": "0.0.84",
        "registry_profile_rows": 15,
        "direct_numeric_restore_candidate_rows": 0,
        "structural_material_change_rows": len(rows),
        "policy": {
            "installed_game_modified": False,
            "g1m_payload_written": False,
            "parent_elixir_rebuilt": False,
            "pak_repacked": False,
            "core_registry_modified": False,
            "profile_activated": False,
        },
    }), encoding="utf-8")
    write_tsv(report / "STRUCTURAL_MATERIAL_CHANGES.tsv", rows)


class StructuralMaterialTests(unittest.TestCase):
    def test_parser_and_rebuilder_preserve_unchanged_payload(self) -> None:
        payload = g1m_blocks([[('base', 4, [(0.0, 1.0, 2.0, 3.0)])]])
        layout = TOOL.parse_g1m_layout(payload)
        records = [[bytes(row['raw']) for row in block['records']] for block in layout['shader_section']['blocks']]
        self.assertEqual(TOOL.rebuild_with_blocks(payload, layout, records), payload)

    def test_unique_removed_record_reconstructs_source_and_reverses(self) -> None:
        source = g1m_blocks([[('atColor', 4, [(1.0, 1.0, 1.0, 1.0)]), ('base', 4, [(0.0, 1.0, 2.0, 3.0)])]])
        target = g1m_blocks([[('base', 4, [(0.0, 1.0, 2.0, 3.0)])]])
        value_hex = struct.pack('<4f', 1.0, 1.0, 1.0, 1.0).hex()
        row = structural_row(
            0, candidate='effect1', path='data/x64/field/bath.elixir.gz', member='bath.g1m',
            classification='removed_in_target', name='atColor', source_block='0', source_param='0', source_hex=value_hex,
        )
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            build_stage74(root, [row])
            pair = {
                'candidate_id': 'effect1', 'normalized_path': 'data/x64/field/bath.elixir.gz',
                'source_member_name': 'bath.g1m', 'target_member_name': 'bath.g1m',
                'source_payload': source, 'target_payload': target,
            }
            output, summary = TOOL.collect(
                project_root=root,
                workspace_root=root / '.local/build/quartet_restoration',
                report_root=root / '.local/reports/quartet_restoration',
                pair_loader=lambda **_kwargs: ([pair], []),
                progress_callback=lambda _message: None,
            )
            self.assertEqual(summary['record_validation_failures'], 0)
            self.assertEqual(summary['unique_followup_candidate_member_rows'], 1)
            members = TOOL.read_tsv(output / 'STRUCTURAL_MATERIAL_MEMBERS.tsv')
            self.assertEqual(members[0]['classification'], 'unique_structural_inverse_candidate_ready_for_narrow_followup')
            self.assertEqual(members[0]['unique_candidate_sha256'], __import__('hashlib').sha256(source).hexdigest())
            self.assertEqual(members[0]['unique_reverse_roundtrip'], 'True')


    def test_default_structural_loader_includes_g1m_members(self) -> None:
        source = g1m_blocks([[('atColor', 4, [(1.0, 1.0, 1.0, 1.0)]), ('base', 4, [(0.0, 1.0, 2.0, 3.0)])]])
        target = g1m_blocks([[('base', 4, [(0.0, 1.0, 2.0, 3.0)])]])
        archive_path = 'data/x64/field/bath/bath_obj.elixir.gz'
        member_name = 'bath.g1m'
        structural = [{
            'source_archive_path': archive_path, 'target_archive_path': archive_path,
            'source_member_name': member_name, 'target_member_name': member_name,
        }]
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source_path = root / 'source.elixir.gz'
            target_path = root / 'target.elixir.gz'
            source_path.write_bytes(b'source')
            target_path.write_bytes(b'target')
            effect = {
                'candidate_id': 'recomputed_effect', 'rule_id': 'bathroom', 'pair_id': 'br1_assets',
                'normalized_path': archive_path, 'domain': 'steam_and_water_visibility',
                'priority': 'critical', 'evidence_kind': 'scene_container',
                'source': {'archive': 'PACK00.PAK', 'path': archive_path},
                'target': {'archive': 'PACK10_03.PAK', 'path': archive_path},
            }
            def inventory(_workspace, side, _pair_id, _archive, _path):
                return source_path if side == 'source' else target_path
            def read_archive(path, **_kwargs):
                payload = source if path == source_path else target
                return {'members': [{
                    'comparison_key': 'bath.g1m#0', 'extension': '.g1m', 'name': member_name,
                    'payload': payload, 'sha256': __import__('hashlib').sha256(payload).hexdigest(),
                }]}
            with (
                mock.patch.object(TOOL.BR, 'load_report_jsons', return_value=[{}]),
                mock.patch.object(TOOL.BR, 'load_effect_material_rules', return_value=[]),
                mock.patch.object(TOOL.BR, 'build_effect_material_candidates', return_value=[effect]),
                mock.patch.object(TOOL.BR, 'inventory_workspace_file', side_effect=inventory),
                mock.patch.object(TOOL.BR, 'read_earc_archive', side_effect=read_archive),
            ):
                pairs, skipped = TOOL.load_structural_g1m_pairs(
                    workspace_root=root, report_root=root, rules_file=root / 'rules.tsv',
                    maximum_earc_bytes=1024 * 1024, structural_rows=structural,
                )
            self.assertEqual(skipped, [])
            self.assertEqual(len(pairs), 1)
            self.assertEqual(pairs[0]['target_member_name'], member_name)
            self.assertEqual(pairs[0]['source_payload'], source)
            self.assertEqual(pairs[0]['target_payload'], target)

    def test_rehydration_falls_back_to_stable_archive_member_identity(self) -> None:
        source = g1m_blocks([[('atColor', 4, [(1.0, 1.0, 1.0, 1.0)]), ('base', 4, [(0.0, 1.0, 2.0, 3.0)])]])
        target = g1m_blocks([[('base', 4, [(0.0, 1.0, 2.0, 3.0)])]])
        value_hex = struct.pack('<4f', 1.0, 1.0, 1.0, 1.0).hex()
        row = structural_row(
            0, candidate='historical_effect_id', path='data/x64/field/bath.elixir.gz', member='bath.g1m',
            classification='removed_in_target', name='atColor', source_block='0', source_param='0', source_hex=value_hex,
        )
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            build_stage74(root, [row])
            pair = {
                'candidate_id': 'recomputed_effect_id', 'normalized_path': 'data/x64/field/bath.elixir.gz',
                'source_member_name': 'bath.g1m', 'target_member_name': 'bath.g1m',
                'source_payload': source, 'target_payload': target,
            }
            output, summary = TOOL.collect(
                project_root=root,
                workspace_root=root / '.local/build/quartet_restoration',
                report_root=root / '.local/reports/quartet_restoration',
                pair_loader=lambda **_kwargs: ([pair], []),
                progress_callback=lambda _message: None,
            )
            self.assertEqual(summary['audited_member_rows'], 1)
            self.assertEqual(summary['stable_rehydration_fallback_member_rows'], 1)
            self.assertEqual(summary['skipped_rows'], 0)
            members = TOOL.read_tsv(output / 'STRUCTURAL_MATERIAL_MEMBERS.tsv')
            self.assertEqual(members[0]['rehydration_match_basis'], 'stable_archive_member')
            self.assertEqual(members[0]['classification'], 'unique_structural_inverse_candidate_ready_for_narrow_followup')

    def test_recurrent_meshblend_additions_remain_confounded(self) -> None:
        source = g1m_blocks([[('base', 4, [(0.0, 1.0, 2.0, 3.0)])]])
        target = g1m_blocks([[('base', 4, [(0.0, 1.0, 2.0, 3.0)]), ('parameterForMeshBlend', 4, [(1.0, 1.0, 1.0, 1.0)])]])
        value_hex = struct.pack('<4f', 1.0, 1.0, 1.0, 1.0).hex()
        rows = []
        pairs = []
        for index in range(TOOL.RECURRENT_THRESHOLD):
            candidate = f'effect{index}'
            path = f'data/x64/field/f{index}.elixir.gz'
            member = f'f{index}.g1m'
            rows.append(structural_row(
                index, candidate=candidate, path=path, member=member,
                classification='added_in_target', name='parameterForMeshBlend',
                target_block='0', target_param='1', target_hex=value_hex,
            ))
            pairs.append({
                'candidate_id': candidate, 'normalized_path': path,
                'source_member_name': member, 'target_member_name': member,
                'source_payload': source, 'target_payload': target,
            })
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            build_stage74(root, rows)
            output, summary = TOOL.collect(
                project_root=root,
                workspace_root=root / '.local/build/quartet_restoration',
                report_root=root / '.local/reports/quartet_restoration',
                pair_loader=lambda **_kwargs: (pairs, []),
                progress_callback=lambda _message: None,
            )
            self.assertEqual(summary['recurrent_record_rows'], TOOL.RECURRENT_THRESHOLD)
            self.assertEqual(summary['unique_followup_candidate_member_rows'], 0)
            members = TOOL.read_tsv(output / 'STRUCTURAL_MATERIAL_MEMBERS.tsv')
            self.assertTrue(all(row['classification'] == 'exact_original_requires_recurrent_and_unique_structure_confounded' for row in members))

    def test_reported_value_mismatch_is_fail_closed(self) -> None:
        source = g1m_blocks([[('base', 4, [(0.0, 1.0, 2.0, 3.0)])]])
        target = g1m_blocks([[('base', 4, [(0.0, 1.0, 2.0, 3.0)]), ('parameterForMeshBlend', 4, [(1.0, 1.0, 1.0, 1.0)])]])
        row = structural_row(
            0, candidate='effect1', path='data/x64/field/a.elixir.gz', member='a.g1m',
            classification='added_in_target', name='parameterForMeshBlend',
            target_block='0', target_param='1', target_hex='00000000000000000000000000000000',
        )
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            build_stage74(root, [row])
            pair = {
                'candidate_id': 'effect1', 'normalized_path': 'data/x64/field/a.elixir.gz',
                'source_member_name': 'a.g1m', 'target_member_name': 'a.g1m',
                'source_payload': source, 'target_payload': target,
            }
            _output, summary = TOOL.collect(
                project_root=root,
                workspace_root=root / '.local/build/quartet_restoration',
                report_root=root / '.local/reports/quartet_restoration',
                pair_loader=lambda **_kwargs: ([pair], []),
                progress_callback=lambda _message: None,
            )
            self.assertEqual(summary['record_validation_failures'], 1)
            self.assertEqual(summary['unique_followup_candidate_member_rows'], 0)


if __name__ == '__main__':
    unittest.main()
