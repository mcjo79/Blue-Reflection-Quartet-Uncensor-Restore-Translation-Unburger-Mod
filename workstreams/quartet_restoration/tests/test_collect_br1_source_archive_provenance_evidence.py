from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import tempfile
import unittest
from pathlib import Path

MODULE_PATH = Path(__file__).resolve().parents[1] / "collect_br1_source_archive_provenance_evidence.py"
spec = importlib.util.spec_from_file_location("stage105", MODULE_PATH)
assert spec and spec.loader
S = importlib.util.module_from_spec(spec)
spec.loader.exec_module(S)


class Stage105Tests(unittest.TestCase):
    def make_fake_gust(self, root: Path) -> Path:
        tool = root / "gust_pak"
        tool.write_text(
            """#!/usr/bin/env python3
import json, sys
from pathlib import Path
archive = Path(sys.argv[1])
data = json.loads(archive.read_text().rstrip())
files = []
offset = 256
for row in data['members']:
    name = row['name']
    payload = bytes.fromhex(row['hex'])
    path = Path(name)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)
    files.append({'name': name, 'offset': row.get('offset', offset), 'size': len(payload), 'flags': row.get('flags', 0), 'key': '00'})
    offset += len(payload)
manifest = {'name': archive.stem + '.PAK', 'version': 1, 'flags': 0, 'nb_files': len(files), 'files': files}
Path(archive.stem + '.json').write_text(json.dumps(manifest), encoding='utf-8')
""",
            encoding="utf-8",
        )
        tool.chmod(0o755)
        return tool

    def write_archive(self, path: Path, members: list[dict], size: int | None = None) -> None:
        text = json.dumps({"members": members}, separators=(",", ":"))
        target = max(len(text), size or 0)
        path.write_text(text + " " * (target - len(text)), encoding="utf-8")

    def member_path(self, basename: str) -> str:
        stem = basename.split("_", 1)[0]
        return f"data/x64/character/{stem}/{basename}"

    def make_project(self, root: Path, preserved_hashes: dict[str, str]) -> Path:
        project = root / "project"
        (project / "Blue_Reflection_Text_Tool").mkdir(parents=True)
        source_tool = MODULE_PATH.parents[2] / "Blue_Reflection_Text_Tool" / "br_restoration_tool.py"
        (project / "Blue_Reflection_Text_Tool" / "br_restoration_tool.py").write_bytes(source_tool.read_bytes())
        report = project / ".local/reports/quartet_restoration"
        (report / "inventories").mkdir(parents=True)
        archives = []
        for name, sha in preserved_hashes.items():
            archives.append({"archive": f"DATA/{name}", "size": 1, "sha256": sha, "extraction_status": "unchanged"})
        source_inventory = {"type": "x", "archives": archives, "files": []}
        (report / "inventories/br1_assets.source.json").write_text(json.dumps(source_inventory), encoding="utf-8")
        changed = self.member_path(S.EXPECTED_PACK00_02_CHANGED_BASENAMES[0])
        (report / "differences").mkdir()
        (report / "differences/br1_assets.json").write_text(json.dumps({"path": changed}), encoding="utf-8")
        (report / "REVIEW_QUEUE.tsv").write_text("source_path\n" + changed + "\n", encoding="utf-8")
        profiles = project / ".local/build/quartet_restoration/core_profiles/generated"
        profiles.mkdir(parents=True)
        (profiles / "safe.json").write_text(json.dumps({
            "profile_id": "safe", "target_relative_path": "Data/PACK11.PAK",
            "changed_members": ["event/b1/event_jp/test.ebd"], "runtime_validated": False,
        }), encoding="utf-8")
        (project / "workstreams/quartet_restoration").mkdir(parents=True)
        return project

    def test_member_diff_and_scoped_dependency_audit(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_s:
            tmp = Path(tmp_s)
            game = tmp / "game"
            data = game / "DATA"
            data.mkdir(parents=True)
            fake_gust = self.make_fake_gust(tmp)

            base_members = []
            official_members = []
            for index, basename in enumerate(S.EXPECTED_PACK00_02_CHANGED_BASENAMES):
                name = self.member_path(basename)
                base_members.append({"name": name, "hex": f"{index % 256:02x}00", "offset": 1000 + index * 16})
                official_members.append({"name": name, "hex": f"{index % 256:02x}ff", "offset": 1000 + index * 16})
            base_members.append({"name": "data/x64/shader/stable.g1s", "hex": "0102", "offset": 9000})
            official_members.append({"name": "data/x64/shader/stable.g1s", "hex": "0102", "offset": 9000})
            p02_old = data / "PACK00_02.PAK_"
            p02_new = data / "PACK00_02.PAK"
            self.write_archive(p02_old, base_members)
            self.write_archive(p02_new, official_members, p02_old.stat().st_size)
            size02 = p02_old.stat().st_size

            for number in (1, 2, 3):
                old = data / f"PACK00_04_{number}.PAK_"
                new = data / f"PACK00_04_{number}.PAK"
                old_members = [{"name": f"data/x64/res/ui_{number}.g1t", "hex": "0102", "offset": 100}]
                new_members = [{"name": f"data/x64/res/ui_{number}.g1t", "hex": "0103", "offset": 100}]
                self.write_archive(old, old_members)
                self.write_archive(new, new_members, old.stat().st_size)

            preserved_hashes = {
                "PACK00_02.PAK": S.sha256_file(p02_old),
                **{f"PACK00_04_{n}.PAK": S.sha256_file(data / f"PACK00_04_{n}.PAK_") for n in (1, 2, 3)},
            }
            project = self.make_project(tmp, preserved_hashes)
            report_root = project / ".local/reports/quartet_restoration"
            result = S.collect(
                project_root=project,
                game_root=game,
                gust_pak=fake_gust,
                report_root=report_root,
                expected_preserved_sha1=S.hash_file(p02_old, "sha1"),
                expected_official_sha1=S.hash_file(p02_new, "sha1"),
                expected_pack00_02_size=size02,
                create_archive=True,
            )
            summary = result["summary"]
            self.assertEqual(summary["archive_pair_rows"], 4)
            self.assertEqual(summary["pack00_02_changed_member_rows"], 30)
            self.assertEqual(summary["pack00_04_changed_member_rows"], 3)
            self.assertEqual(summary["affected_registered_profile_rows"], 0)
            self.assertEqual(summary["unaffected_registered_profile_rows"], 1)
            self.assertTrue(Path(result["report_path"]).is_file())

    def test_profile_intersection_fails_closed(self) -> None:
        changed = ["data/x64/character/pc03/pc03_scl_w.g1t"]
        with tempfile.TemporaryDirectory() as tmp_s:
            project = Path(tmp_s)
            profiles = project / ".local/build/quartet_restoration/core_profiles/generated"
            profiles.mkdir(parents=True)
            (profiles / "bad.json").write_text(json.dumps({
                "profile_id": "bad", "changed_members": changed,
            }), encoding="utf-8")
            affected, unaffected = S.validate_profile_dependencies(project, changed)
            self.assertEqual(len(affected), 1)
            self.assertEqual(unaffected, [])


if __name__ == "__main__":
    unittest.main()
