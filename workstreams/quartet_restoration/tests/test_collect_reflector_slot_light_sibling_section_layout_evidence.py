#!/usr/bin/env python3
from __future__ import annotations

import csv
import importlib.util
import json
import shutil
import struct
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "workstreams/quartet_restoration/collect_reflector_slot_light_sibling_section_layout_evidence.py"
SPEC = importlib.util.spec_from_file_location("stage109", SCRIPT)
assert SPEC and SPEC.loader
S = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(S)

STAGE79_ARCHIVE = ROOT / ".local/reports/quartet_restoration/BR_quartet_restoration_reflector_character_slot_render_member_evidence.tar.zst"
BODY = b"".join((0x11111111 * i).to_bytes(4, "little") for i in range(1, 9))


def write_tsv(path: Path, fields: list[str], rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def make_payload(record_count: int = 907, *, mode: int = 7) -> tuple[bytes, list[int], str]:
    endpoint = 64
    first = 12000
    starts = [first + index * 44 for index in range(record_count)]
    size = starts[-1] + 44 + 512
    payload = bytearray(size)
    words = [
        size - endpoint, 0, record_count, record_count, record_count, mode, 56,
        56 + 4 * (record_count - 1), 56 + 8 * (record_count - 1), 56 + 12 * (record_count - 1),
        0x00010000, 0, 0, 0,
    ]
    for index, word in enumerate(words):
        struct.pack_into("<I", payload, endpoint + index * 4, word)
    leaf = struct.pack("<f", 1.0)
    for start in starts:
        payload[start:start + 4] = leaf
        payload[start + 4:start + 8] = leaf
        payload[start + 8:start + 40] = BODY
        displacement = endpoint - (start + 40)
        struct.pack_into("<I", payload, start + 40, displacement & 0xFFFFFFFF)
    header_sha = S.sha256(bytes(payload[endpoint:endpoint + 56]))
    return bytes(payload), starts, header_sha


def make_fixture(root: Path, *, corrupt_header_hash: bool = False):
    reports = root / "reports"
    stage104 = reports / S.STAGE104_DIR
    stage108 = reports / S.STAGE108_DIR
    stage104.mkdir(parents=True)
    stage108.mkdir(parents=True)
    shutil.copy2(STAGE79_ARCHIVE, reports / S.STAGE79_ARCHIVE)

    payload, starts, header_sha = make_payload()
    rows = []
    path = "data/x64/effect/1000_pc00.elixir.gz"
    key = "bulk.g1e#0"
    for side in ("source", "target"):
        for ordinal, start in enumerate(starts):
            known = len(rows) < 21
            rows.append({
                "normalized_path": path,
                "member_key": key,
                "member_name": "bulk.g1e",
                "side": side,
                "technical_member_role": "character_effect_container",
                "bounded_name_scope": "transformation_or_character_named_control",
                "character_slot": "PC00",
                "record_start": start,
                "body_offset": start + 8,
                "reference_offset": start + 40,
                "reference_u32_hex": f"0x{(64 - (start + 40)) & 0xffffffff:08x}",
                "reference_i32": 64 - (start + 40),
                "normalized_endpoint": 64,
                "leaf_u32_hex": "0x3f800000",
                "paired_float_value": "1",
                "section_count": 907,
                "section_declared_span": len(payload) - 64,
                "section_header_sha256": ("0" * 64 if corrupt_header_hash and len(rows) == 0 else header_sha),
                "record_sha256": S.sha256(payload[start:start + 44]),
                "non_leaf_body_sha256": S.sha256(BODY),
                "known_stage101_occurrence": known,
                "additional_sibling_occurrence": not known,
                "classification": "known" if known else "additional",
            })
    assert len(rows) == 1814
    write_tsv(stage104 / "SLOT_LIGHT_SIBLING_TEMPLATE_OCCURRENCES.tsv", list(rows[0]), rows)
    (stage104 / "SUMMARY.json").write_text(json.dumps({
        "type": "br_quartet_restoration_reflector_slot_light_sibling_template_expansion_evidence_summary",
        "tool_version": "0.1.18",
        "sibling_G1E_G1EM_pair_rows": 540,
        "format_valid_sibling_occurrence_rows": 1814,
        "known_stage101_occurrence_rows": 21,
        "additional_sibling_occurrence_rows": 1793,
        "technical_leaf_domain_semantics_resolved": False,
        "prototype_candidate_rows": 0,
        "skipped_rows": 0,
    }), encoding="utf-8")
    (stage108 / "SUMMARY.json").write_text(json.dumps({
        "type": "br_quartet_restoration_br1_official_source_retirement_closure_evidence_summary",
        "tool_version": "0.1.22",
        "status": "underscore_archive_retirement_closed",
        "retirement_complete": True,
        "official_archives_verified": 4,
        "underscore_archives_absent": 4,
        "registered_profiles_affected": 0,
        "stage104_slot_light_evidence_independent": True,
        "underscore_archives_required_for_normal_workflow": False,
    }), encoding="utf-8")

    parent_paths = [
        "data/x64/effect/100_common.elixir.gz",
        "data/x64/effect/1000_pc00.elixir.gz",
        "data/x64/effect/1001_pc01.elixir.gz",
        "data/x64/effect/1002_pc02.elixir.gz",
    ]
    grouped = {p: [] for p in parent_paths}
    grouped[path].append((key, "bulk.g1e", payload, payload))
    for index in range(539):
        p = parent_paths[index % 4]
        filler = bytes(256)
        grouped[p].append((f"filler_{index}.g1e#0", f"filler_{index}.g1e", filler, filler))
    containers = []
    for container_index, p in enumerate(parent_paths):
        source_members = []
        target_members = []
        for member_key, name, source, target in grouped[p]:
            source_members.append({"comparison_key": member_key, "name": name, "payload": source})
            target_members.append({"comparison_key": member_key, "name": name, "payload": target})
        containers.append({
            "candidate_id": f"container{container_index}",
            "normalized_path": p,
            "scope_rows": [],
            "source_members": source_members,
            "target_members": target_members,
        })

    def loader(**_kwargs):
        return containers, []

    return reports, loader


class Stage109Tests(unittest.TestCase):
    def test_revalidates_all_occurrences_and_exports_layout(self) -> None:
        with tempfile.TemporaryDirectory(prefix="stage109-test-") as name:
            reports, loader = make_fixture(Path(name))
            output, archive, summary = S.build_report(ROOT, create_archive=False, report_root=reports, container_loader=loader)
            self.assertIsNone(archive)
            self.assertEqual(summary["revalidated_occurrence_rows"], 1814)
            self.assertEqual(summary["section_anchored_layout_rows"], 2)
            self.assertEqual(summary["header_mode_flag_rows"], 1)
            self.assertEqual(summary["full_template_coverage_section_rows"], 2)
            self.assertFalse(summary["technical_leaf_domain_semantics_resolved"])
            self.assertEqual(summary["prototype_candidate_rows"], 0)
            self.assertTrue((output / "SLOT_LIGHT_SIBLING_SECTION_ANCHORED_LAYOUTS.tsv").is_file())

    def test_fails_if_stage104_header_hash_no_longer_matches(self) -> None:
        with tempfile.TemporaryDirectory(prefix="stage109-negative-") as name:
            reports, loader = make_fixture(Path(name), corrupt_header_hash=True)
            with self.assertRaises(S.Stage109Error):
                S.build_report(ROOT, create_archive=False, report_root=reports, container_loader=loader)


if __name__ == "__main__":
    unittest.main()
