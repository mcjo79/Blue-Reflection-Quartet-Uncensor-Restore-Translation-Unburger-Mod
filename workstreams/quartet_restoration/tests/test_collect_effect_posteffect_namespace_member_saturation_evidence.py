from __future__ import annotations

import csv
import importlib.util
import struct
import sys
import tempfile
import unittest
import zlib
from pathlib import Path

WORKSTREAM = Path(__file__).resolve().parents[1]
PROJECT = WORKSTREAM.parent.parent
TOOL_PATH = WORKSTREAM / "134_collect_effect_posteffect_namespace_member_saturation_evidence.py"
SPEC = importlib.util.spec_from_file_location("stage134_tool", TOOL_PATH)
assert SPEC and SPEC.loader
TOOL = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = TOOL
SPEC.loader.exec_module(TOOL)


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
        result[table + 8 : table + 8 + len(encoded)] = encoded
        result[offset : offset + len(payload)] = payload
        offset += len(payload)
    return bytes(result)


def write_gust_chunked(path: Path, payload: bytes) -> None:
    compressed = zlib.compress(payload, 9)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(len(compressed).to_bytes(4, "little") + compressed + (0).to_bytes(4, "little"))


class EffectPosteffectNamespaceMemberSaturationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.tmp = tempfile.TemporaryDirectory(prefix="stage134-tests-")
        cls.root = Path(cls.tmp.name)
        cls.workspace = cls.root / "workspace"
        cls.report_root = PROJECT / ".local/reports/quartet_restoration"
        stage130 = cls.report_root / TOOL.STAGE130_DIR
        cls.candidates = [
            row for row in read_tsv(stage130 / "NON_CHARACTER_TECHNICAL_CANDIDATES.tsv")
            if row["namespace"] in {"effect", "posteffect"}
        ]
        cls.inventories = {side: TOOL.load_inventory(PROJECT, side) for side in ("source", "target")}
        br = TOOL.load_br_tool(PROJECT)
        for index, row in enumerate(sorted(cls.candidates, key=lambda item: item["normalized_path"])):
            normalized = row["normalized_path"].casefold()
            for side in ("source", "target"):
                entry = cls.inventories[side][normalized]
                local = br.inventory_workspace_file(
                    cls.workspace, side, "br1_assets", str(entry["archive"]), str(entry["path"])
                )
                members = [
                    ("common.bin", b"same"),
                    (f"pc{index:02d}_effect.g1e", b"source" if side == "source" else b"target"),
                ]
                if index == 0:
                    members.append(("heightfog_binding.bin", b"source" if side == "source" else b"target"))
                if index == 1 and side == "target":
                    members.append(("swater_binding.bin", b"target-only"))
                write_gust_chunked(local, make_earc(members))
        cls.profile_manifest_root = Path(__file__).resolve().parent / "fixtures" / "stage119_historical_core_profile_manifests"
        cls.archive, cls.summary = TOOL.build_report(
            PROJECT,
            report_root=cls.report_root,
            output_report_root=cls.root / "reports",
            workspace_root=cls.workspace,
            create_archive=True,
            verify_payload_hashes=False,
            profile_manifest_root=cls.profile_manifest_root,
        )
        cls.report = cls.root / "reports" / TOOL.REPORT_DIR
        cls.paths = read_tsv(cls.report / "EFFECT_POSTEFFECT_PATH_SUMMARY.tsv")
        cls.members = read_tsv(cls.report / "EFFECT_POSTEFFECT_MEMBER_LEDGER.tsv")
        cls.roles = read_tsv(cls.report / "EFFECT_POSTEFFECT_MEMBER_ROLE_FAMILIES.tsv")
        cls.shaders = read_tsv(cls.report / "BOUNDED_SHADER_STATIC_DEPENDENCY_AUDIT.tsv")

    @classmethod
    def tearDownClass(cls) -> None:
        cls.tmp.cleanup()

    def test_all_seven_container_paths_are_saturated(self):
        self.assertEqual(self.summary["container_path_rows"], 7)
        self.assertEqual(self.summary["effect_path_rows"], 6)
        self.assertEqual(self.summary["posteffect_path_rows"], 1)
        self.assertEqual(len(self.paths), 7)
        self.assertTrue(all(row["exact_member_saturation_complete"] == "True" for row in self.paths))

    def test_full_member_ledger_includes_identical_and_nonidentical(self):
        self.assertEqual(len(self.members), self.summary["member_rows"])
        self.assertGreater(self.summary["identical_member_rows"], 0)
        self.assertGreater(self.summary["changed_member_rows"], 0)
        self.assertGreater(self.summary["added_member_rows"], 0)
        self.assertEqual(self.summary["removed_member_rows"], 0)

    def test_member_roles_are_metadata_only(self):
        self.assertGreater(len(self.roles), 0)
        self.assertTrue(all(row["semantic_classification"] == "unresolved_metadata_only" for row in self.roles))
        self.assertTrue(all(row["write_authorized"] == "False" for row in self.roles))

    def test_all_fifteen_bounded_shader_candidates_are_audited(self):
        self.assertEqual(self.summary["bounded_shader_candidate_rows"], 15)
        self.assertEqual(len(self.shaders), 15)
        self.assertTrue(all(row["dependency_binding_resolved"] == "False" for row in self.shaders))

    def test_exact_member_name_references_are_not_treated_as_binding(self):
        by_token = {row["shader_basename_token"]: row for row in self.shaders}
        self.assertGreater(int(by_token["heightfog"]["effect_posteffect_member_name_hit_rows"]), 0)
        self.assertGreater(int(by_token["swater"]["effect_posteffect_member_name_hit_rows"]), 0)
        self.assertEqual(by_token["heightfog"]["dependency_binding_resolved"], "False")
        self.assertEqual(by_token["swater"]["dependency_binding_resolved"], "False")

    def test_inactive_profiles_are_recorded_without_runtime_validation(self):
        by_token = {row["shader_basename_token"]: row for row in self.shaders}
        self.assertEqual(int(by_token["heightfog"]["inactive_profile_rows"]), 1)
        self.assertEqual(int(by_token["swater"]["inactive_profile_rows"]), 1)
        self.assertEqual(self.summary["runtime_confirmed_rows"], 0)

    def test_report_contains_no_payload_extensions(self):
        bad = [
            path.name for path in self.report.rglob("*") if path.is_file()
            and any(path.name.casefold().endswith(ext) for ext in TOOL.FORBIDDEN_EXTENSIONS)
        ]
        self.assertEqual(bad, [])

    def test_policy_is_fail_closed(self):
        policy = self.summary["policy"]
        self.assertTrue(policy["local_proprietary_payloads_read"])
        for key in (
            "proprietary_payloads_in_report", "installed_game_modified", "pak_built_or_repacked",
            "effect_or_posteffect_payload_written", "shader_payload_written", "profile_or_registry_modified",
            "core_modified", "translation_modified", "legacy_dlc_modified", "git_modified",
            "save_or_runtime_required", "shader_basename_or_member_name_treated_as_dependency_proof",
            "shader_or_member_name_treated_as_visual_semantics", "restoration_prototype_authorized",
        ):
            self.assertFalse(policy[key], key)

    def test_prerequisite_hashes_are_immutable(self):
        self.assertEqual(TOOL.sha256_file(self.report_root / TOOL.STAGE130_NAME), TOOL.STAGE130_SHA256)
        self.assertEqual(TOOL.sha256_file(self.report_root / TOOL.STAGE131_NAME), TOOL.STAGE131_SHA256)
        self.assertEqual(TOOL.sha256_file(self.report_root / TOOL.STAGE133_NAME), TOOL.STAGE133_SHA256)

    def test_wrapper_uses_local_paths_configuration(self):
        wrapper = (WORKSTREAM / "134_collect_effect_posteffect_namespace_member_saturation_evidence.sh").read_text(encoding="utf-8")
        self.assertIn(".local/paths.sh", wrapper)
        self.assertIn("BR1_ORIGINAL_ROOT", wrapper)
        self.assertIn("BR1_QUARTET_ROOT", wrapper)
        self.assertNotIn("/" + "home" + "/", wrapper)
        self.assertNotIn("/" + "mnt" + "/" + "data", wrapper)

    def test_version_gate_rejects_old_tree(self):
        with tempfile.TemporaryDirectory() as text:
            project = Path(text)
            version = project / "workstreams/quartet_restoration/VERSION"
            version.parent.mkdir(parents=True)
            version.write_text("0.1.51\n", encoding="utf-8")
            with self.assertRaisesRegex(TOOL.CollectorError, "0.1.52"):
                TOOL.build_report(project, create_archive=False)

    def test_archive_is_created(self):
        self.assertIsNotNone(self.archive)
        self.assertTrue(self.archive.is_file())


if __name__ == "__main__":
    unittest.main()
