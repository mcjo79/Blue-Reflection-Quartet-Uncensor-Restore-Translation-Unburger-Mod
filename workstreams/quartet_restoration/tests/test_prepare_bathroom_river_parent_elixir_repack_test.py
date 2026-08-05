from __future__ import annotations

import csv
import gzip
import hashlib
import importlib.util
import json
import struct
import sys
import tempfile
import unittest
import zlib
from pathlib import Path

WORKSTREAM = Path(__file__).resolve().parents[1]
TOOL_PATH = WORKSTREAM / "prepare_bathroom_river_parent_elixir_repack_test.py"
SPEC = importlib.util.spec_from_file_location("stage70_tool", TOOL_PATH)
assert SPEC and SPEC.loader
TOOL = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = TOOL
SPEC.loader.exec_module(TOOL)


def write_tsv(path: Path, fields: list[str], rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def build_earc(members: list[tuple[str, bytes]], filename_size: int = 4) -> bytes:
    header_size = 0x1C
    entry_size = 8 + 0x20 + filename_size * 0x10
    table_size = len(members) * entry_size
    payload_start = header_size + table_size
    payload_size = sum(len(payload) for _name, payload in members)
    output = bytearray(struct.pack("<7I", TOOL.BR.EARC_MAGIC, filename_size, payload_size, header_size, table_size, len(members), 0))
    current = payload_start
    name_bytes = entry_size - 8
    for name, payload in members:
        encoded = name.encode("utf-8") + b"\x00"
        if len(encoded) > name_bytes:
            raise AssertionError("fixture name too long")
        output.extend(struct.pack("<2I", current, len(payload)))
        output.extend(encoded.ljust(name_bytes, b"\x00"))
        current += len(payload)
    for _name, payload in members:
        output.extend(payload)
    return bytes(output)


def gust_chunked(payload: bytes) -> bytes:
    split = max(1, len(payload) // 2)
    output = bytearray()
    for part in (payload[:split], payload[split:]):
        compressed = zlib.compress(part, 9)
        output.extend(len(compressed).to_bytes(4, "little"))
        output.extend(compressed)
    output.extend(b"\x00\x00\x00\x00")
    return bytes(output)


class Stage70Tests(unittest.TestCase):
    def make_fixture(self, root: Path, *, container: str = "gzip") -> tuple[Path, Path, bytes, bytes]:
        project = root / "project"
        report_root = project / ".local/reports/quartet_restoration"
        workspace = project / ".local/build/quartet_restoration"
        stage69 = report_root / TOOL.STAGE69_DIR
        stage69.mkdir(parents=True)

        candidate = bytes((index * 13 + 7) & 0xFF for index in range(252))
        target = bytearray(candidate)
        for offset in range(22):
            target[20 + offset] ^= 0x5A
        target = bytes(target)
        candidate_hash = hashlib.sha256(candidate).hexdigest()
        target_hash = hashlib.sha256(target).hexdigest()
        distance = sum(a != b for a, b in zip(candidate, target))

        old = (
            TOOL.EXPECTED_CANDIDATE_SHA256,
            TOOL.EXPECTED_TARGET_MEMBER_SHA256,
            TOOL.EXPECTED_MEMBER_SIZE,
            TOOL.EXPECTED_MEMBER_DISTANCE,
        )
        self.addCleanup(self.restore_constants, old)
        TOOL.EXPECTED_CANDIDATE_SHA256 = candidate_hash
        TOOL.EXPECTED_TARGET_MEMBER_SHA256 = target_hash
        TOOL.EXPECTED_MEMBER_SIZE = len(candidate)
        TOOL.EXPECTED_MEMBER_DISTANCE = distance

        profile_root = workspace / "prototypes/bathroom_river_member" / TOOL.SOURCE_PROFILE_ID
        candidate_rel = Path("members") / TOOL.MEMBER_KEY.rsplit("#", 1)[0]
        candidate_path = profile_root / candidate_rel
        candidate_path.parent.mkdir(parents=True, exist_ok=True)
        candidate_path.write_bytes(candidate)
        manifest = {
            "type": "br_quartet_restoration_local_member_prototype",
            "profile_id": TOOL.SOURCE_PROFILE_ID,
            "parent_container": TOOL.PARENT_PATH,
            "member_key": TOOL.MEMBER_KEY,
            "candidate_sha256": candidate_hash,
            "candidate_size": len(candidate),
            "parent_archive_rebuilt": False,
            "pak_repacked": False,
            "installed_game_modified": False,
            "semantics_assigned": False,
            "runtime_validated": False,
        }
        (profile_root / "PROTOTYPE.json").write_text(json.dumps(manifest), encoding="utf-8")

        summary = {
            "type": "br_quartet_restoration_bathroom_river_member_prototype_evidence_summary",
            "tool_version": "0.0.79",
            "status": "exact_bathroom_river_member_prototype_built_not_repacked_or_installed",
            "proposed_profile_rows": 1,
            "promoted_profile_rows": 1,
            "prototype_file_rows": 1,
            "selected_word_rows": 7,
            "validation_rows": 17,
            "validation_failures": 0,
            "skipped_rows": 0,
            "candidate_sha256": candidate_hash,
            "candidate_size": len(candidate),
            "candidate_distance_to_original": 0,
            "policy": {
                "installed_games_modified": False,
                "candidate_member_payload_written_only_under_local_workspace": True,
                "candidate_member_payload_exported_in_report": False,
                "parent_archive_repack_performed": False,
                "pak_repack_performed": False,
                "core_registry_modified": False,
                "activation_or_rollback_invoked": False,
                "runtime_validation_inferred": False,
                "censorship_classification_inferred": False,
                "opaque_binary_field_semantics_inferred": False,
                "opl2_payload_built": False,
                "translation_or_dlc_workstreams_modified": False,
            },
        }
        (stage69 / "SUMMARY.json").write_text(json.dumps(summary), encoding="utf-8")
        profile_row = {
            "profile_id": TOOL.SOURCE_PROFILE_ID,
            "parent_container": TOOL.PARENT_PATH,
            "member_key": TOOL.MEMBER_KEY,
            "candidate_sha256": candidate_hash,
            "candidate_size": len(candidate),
            "selected_cell_count": 7,
            "local_profile_root": str(profile_root.relative_to(project)),
            "validation_status": "passed",
            "semantics_assigned": False,
            "runtime_validated": False,
        }
        write_tsv(stage69 / "BATHROOM_RIVER_MEMBER_PROTOTYPE_PROFILES.tsv", list(profile_row), [profile_row])
        file_row = {
            "source_sha256": candidate_hash,
            "target_sha256": target_hash,
            "candidate_sha256": candidate_hash,
            "source_size": len(candidate),
            "target_size": len(target),
            "candidate_size": len(candidate),
            "target_distance_to_source": distance,
            "candidate_distance_to_source": 0,
            "candidate_relative_path": candidate_rel.as_posix(),
        }
        write_tsv(stage69 / "BATHROOM_RIVER_MEMBER_PROTOTYPE_FILES.tsv", list(file_row), [file_row])
        validations = [{"check_name": f"check_{index}", "passed": True} for index in range(17)]
        write_tsv(stage69 / "BATHROOM_RIVER_MEMBER_PROTOTYPE_VALIDATIONS.tsv", ["check_name", "passed"], validations)
        write_tsv(stage69 / "BATHROOM_RIVER_MEMBER_PROTOTYPE_SKIPPED.tsv", ["profile_id", "member_key", "reason"], [])

        other_a = bytes(range(64))
        other_b = b"OPL2" * 40
        decoded_parent = build_earc([
            ("other_a.bin", other_a),
            (TOOL.MEMBER_KEY.rsplit("#", 1)[0], target),
            ("S89_S_HINAKO_BATH_ROOM_01.opl2", other_b),
        ])
        parent = root / "target_parent.elixir.gz"
        if container == "gzip":
            parent.write_bytes(gzip.compress(decoded_parent, mtime=0))
        elif container == "gust_chunked_zlib":
            parent.write_bytes(gust_chunked(decoded_parent))
        else:
            raise AssertionError(container)
        return project, parent, candidate, decoded_parent

    @staticmethod
    def restore_constants(old: tuple[str, str, int, int]) -> None:
        (
            TOOL.EXPECTED_CANDIDATE_SHA256,
            TOOL.EXPECTED_TARGET_MEMBER_SHA256,
            TOOL.EXPECTED_MEMBER_SIZE,
            TOOL.EXPECTED_MEMBER_DISTANCE,
        ) = old

    def test_builds_gzip_parent_and_preserves_other_members(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            project, parent, candidate, _decoded_parent = self.make_fixture(root, container="gzip")
            report, summary = TOOL.build(
                project_root=project,
                workspace_root=project / ".local/build/quartet_restoration",
                report_root=project / ".local/reports/quartet_restoration",
                target_parent_loader=lambda: parent,
            )
            self.assertTrue(report.is_file())
            self.assertEqual(summary["repacked_profile_rows"], 1)
            self.assertEqual(summary["changed_member_rows"], 1)
            self.assertEqual(summary["validation_failures"], 0)
            profile_root = project / ".local/build/quartet_restoration/repack_tests/bathroom_river_parent_elixir" / TOOL.PROFILE_ID
            manifest = json.loads((profile_root / "REPACK_TEST.json").read_text())
            candidate_parent = profile_root / manifest["candidate_relative_path"]
            archive = TOOL.BR.read_earc_archive(candidate_parent, include_member_payloads=True)
            members = {row["comparison_key"]: row for row in archive["members"]}
            self.assertEqual(members[TOOL.MEMBER_KEY]["payload"], candidate)
            self.assertEqual(manifest["changed_member_count"], 1)

    def test_preserves_gust_chunked_container_kind(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            project, parent, _candidate, _decoded_parent = self.make_fixture(root, container="gust_chunked_zlib")
            _report, summary = TOOL.build(
                project_root=project,
                workspace_root=project / ".local/build/quartet_restoration",
                report_root=project / ".local/reports/quartet_restoration",
                target_parent_loader=lambda: parent,
            )
            self.assertEqual(summary["container_kind"], "gust_chunked_zlib")
            self.assertEqual(summary["repacked_profile_rows"], 1)

    def test_encode_gust_rejects_changed_decoded_size(self) -> None:
        with self.assertRaises(TOOL.BathroomRiverParentRepackError):
            TOOL.encode_parent(b"abc", "gust_chunked_zlib", {"decoded_chunk_sizes": [2, 2]})


if __name__ == "__main__":
    unittest.main()
