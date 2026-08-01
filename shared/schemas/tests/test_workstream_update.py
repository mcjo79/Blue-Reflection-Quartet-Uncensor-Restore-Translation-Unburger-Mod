#!/usr/bin/env python3
from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

MODULE_PATH = (
    Path(__file__).resolve().parents[3]
    / "Blue_Reflection_Text_Tool"
    / "workstream_update.py"
)
FIXTURE_ROOT = Path(__file__).resolve().parent / "fixtures"
SPEC = importlib.util.spec_from_file_location("br_workstream_update", MODULE_PATH)
assert SPEC and SPEC.loader
wu = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(wu)


def fixture(name: str) -> dict[str, object]:
    return json.loads((FIXTURE_ROOT / name).read_text(encoding="utf-8"))


def encoded(document: dict[str, object]) -> bytes:
    return (json.dumps(document, indent=2, ensure_ascii=False) + "\n").encode("utf-8")


def merge_document(
    changes: list[dict[str, str]], mutable_field: str = "en"
) -> dict[str, object]:
    return {
        "type": "br_translation_records_merge",
        "format_version": 1,
        "target_array": "/records",
        "stable_key": "logical_id",
        "mutable_field": mutable_field,
        "changes": changes,
    }


class TranslationRecordsMergeV1Tests(unittest.TestCase):
    def test_merge_two_records_in_one_event_unit(self) -> None:
        current = fixture("br_event_translation_unit.json")
        original = copy.deepcopy(current)
        output, _ = wu.apply_translation_records_merge(
            encoded(current),
            merge_document(
                [
                    {
                        "logical_id": "fixture:event:0",
                        "old_value": "old-event-a",
                        "new_value": "new-event-a",
                    },
                    {
                        "logical_id": "fixture:event:1",
                        "old_value": "old-event-b",
                        "new_value": "new-event-b",
                    },
                ]
            ),
            "titles/blue_reflection/translation/events/synthetic_event.json",
        )
        parsed = json.loads(output)
        self.assertEqual(parsed["records"][0]["en"], "new-event-a")
        self.assertEqual(parsed["records"][1]["en"], "new-event-b")
        self.assertEqual(parsed["records"][2], original["records"][2])
        self.assertEqual(
            parsed["records"][0]["fixture_metadata"],
            original["records"][0]["fixture_metadata"],
        )
        for key in current:
            if key != "records":
                self.assertEqual(parsed[key], original[key])

    def test_preserves_prior_change_to_other_system_record(self) -> None:
        current = fixture("br_system_translation_unit.json")
        current["records"][1]["en"] = "independent-system-edit"
        output, _ = wu.apply_translation_records_merge(
            encoded(current),
            merge_document(
                [
                    {
                        "logical_id": "fixture:system:0",
                        "old_value": "old-system-a",
                        "new_value": "new-system-a",
                    }
                ]
            ),
            "titles/second_light/translation/system/synthetic_system.json",
        )
        parsed = json.loads(output)
        self.assertEqual(parsed["records"][0]["en"], "new-system-a")
        self.assertEqual(parsed["records"][1]["en"], "independent-system-edit")
        self.assertEqual(
            parsed["records"][1]["fixture_metadata"], {"preserve": "system-b"}
        )

    def test_idempotent_reapplication(self) -> None:
        patch = merge_document(
            [
                {
                    "logical_id": "fixture:system:0",
                    "old_value": "old-system-a",
                    "new_value": "new-system-a",
                }
            ]
        )
        once, _ = wu.apply_translation_records_merge(
            encoded(fixture("br_system_translation_unit.json")),
            patch,
            "titles/second_light/translation/system/synthetic_system.json",
        )
        twice, _ = wu.apply_translation_records_merge(
            once,
            patch,
            "titles/second_light/translation/system/synthetic_system.json",
        )
        self.assertEqual(json.loads(once), json.loads(twice))

    def test_conflict_on_same_logical_id(self) -> None:
        current = fixture("br_event_translation_unit.json")
        current["records"][0]["en"] = "third-value"
        with self.assertRaisesRegex(wu.UpdateError, "translation record conflict"):
            wu.apply_translation_records_merge(
                encoded(current),
                merge_document(
                    [
                        {
                            "logical_id": "fixture:event:0",
                            "old_value": "old-event-a",
                            "new_value": "new-event-a",
                        }
                    ]
                ),
                "titles/blue_reflection/translation/events/synthetic_event.json",
            )

    def test_missing_logical_id(self) -> None:
        with self.assertRaisesRegex(wu.UpdateError, "logical_id not found"):
            wu.apply_translation_records_merge(
                encoded(fixture("br_event_translation_unit.json")),
                merge_document(
                    [
                        {
                            "logical_id": "fixture:event:missing",
                            "old_value": "old",
                            "new_value": "new",
                        }
                    ]
                ),
                "titles/blue_reflection/translation/events/synthetic_event.json",
            )

    def test_duplicate_logical_id_in_target(self) -> None:
        current = fixture("br_event_translation_unit.json")
        current["records"].append(copy.deepcopy(current["records"][0]))
        with self.assertRaisesRegex(wu.UpdateError, "must occur exactly once"):
            wu.apply_translation_records_merge(
                encoded(current),
                merge_document(
                    [
                        {
                            "logical_id": "fixture:event:0",
                            "old_value": "old-event-a",
                            "new_value": "new-event-a",
                        }
                    ]
                ),
                "titles/blue_reflection/translation/events/synthetic_event.json",
            )

    def test_rejects_mutable_field_other_than_en(self) -> None:
        rel = "titles/blue_reflection/translation/events/synthetic_event.json"
        raw = encoded(
            merge_document(
                [
                    {
                        "logical_id": "fixture:event:0",
                        "old_value": "old-event-a",
                        "new_value": "new-event-a",
                    }
                ],
                mutable_field="jp",
            )
        )
        with tempfile.TemporaryDirectory() as tmp:
            archive_path = Path(tmp) / "patch.zip"
            with zipfile.ZipFile(archive_path, "w") as archive:
                archive.writestr(f"patches/{rel}.records.json", raw)
            with zipfile.ZipFile(archive_path) as archive:
                with self.assertRaisesRegex(wu.UpdateError, "may modify only en"):
                    wu.load_translation_records_merge_document(
                        archive, rel, hashlib.sha256(raw).hexdigest()
                    )

    def test_full_preflight_prevents_partial_write_on_last_conflict(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "project"
            (root / "config").mkdir(parents=True)
            (root / "workstreams/translation").mkdir(parents=True)
            translation_rel = Path(
                "titles/blue_reflection/translation/events/synthetic_event.json"
            )
            translation_path = root / translation_rel
            translation_path.parent.mkdir(parents=True)
            status_path = root / "workstreams/translation/STATUS.json"
            version_path = root / "workstreams/translation/VERSION"

            (root / "config/workstream_ownership.tsv").write_text(
                "workstream_id\tpath_prefix\tpermission\tnote\n"
                "translation\ttitles/blue_reflection/translation/\twrite\tcontent\n"
                "translation\tworkstreams/translation/\twrite\tstatus\n",
                encoding="utf-8",
            )
            version_path.write_text("0.0.0\n", encoding="utf-8")
            old_status = b'{"status":"old"}\n'
            new_status = b'{"status":"new"}\n'
            status_path.write_bytes(old_status)
            current = fixture("br_event_translation_unit.json")
            current["records"][0]["en"] = "divergent"
            original_unit = encoded(current)
            translation_path.write_bytes(original_unit)

            merge_raw = encoded(
                merge_document(
                    [
                        {
                            "logical_id": "fixture:event:0",
                            "old_value": "old-event-a",
                            "new_value": "new-event-a",
                        }
                    ]
                )
            )
            manifest = {
                "type": "br_workstream_update",
                "format_version": 3,
                "workstream_id": "translation",
                "from_version": "0.0.0",
                "to_version": "0.0.1",
                "description": "synthetic full-preflight fixture",
                "files": [
                    {
                        "path": "workstreams/translation/STATUS.json",
                        "action": "replace",
                        "old_sha256": hashlib.sha256(old_status).hexdigest(),
                        "new_sha256": hashlib.sha256(new_status).hexdigest(),
                        "mode": "0644",
                    },
                    {
                        "path": translation_rel.as_posix(),
                        "action": "translation_records_merge",
                        "capability": "translation_records_merge/v1",
                        "patch_sha256": hashlib.sha256(merge_raw).hexdigest(),
                        "mode": "0644",
                    },
                ],
            }
            package = Path(tmp) / "update.zip"
            with zipfile.ZipFile(package, "w") as archive:
                archive.writestr(
                    "WORKSTREAM_UPDATE.json", json.dumps(manifest, indent=2) + "\n"
                )
                archive.writestr(
                    "payload/workstreams/translation/STATUS.json", new_status
                )
                archive.writestr(
                    f"patches/{translation_rel.as_posix()}.records.json", merge_raw
                )

            result = subprocess.run(
                [
                    sys.executable,
                    str(MODULE_PATH),
                    "--project-root",
                    str(root),
                    "--package",
                    str(package),
                ],
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("translation record conflict", result.stderr)
            self.assertEqual(status_path.read_bytes(), old_status)
            self.assertEqual(translation_path.read_bytes(), original_unit)
            self.assertEqual(version_path.read_text(encoding="utf-8"), "0.0.0\n")

    def test_manifest_entry_requires_versioned_capability(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "project"
            (root / "config").mkdir(parents=True)
            (root / "workstreams/translation").mkdir(parents=True)
            rel = Path("titles/blue_reflection/translation/events/synthetic_event.json")
            target = root / rel
            target.parent.mkdir(parents=True)
            target.write_bytes(encoded(fixture("br_event_translation_unit.json")))
            (root / "config/workstream_ownership.tsv").write_text(
                "workstream_id\tpath_prefix\tpermission\tnote\n"
                "translation\ttitles/blue_reflection/translation/\twrite\tcontent\n",
                encoding="utf-8",
            )
            (root / "workstreams/translation/VERSION").write_text(
                "0.0.0\n", encoding="utf-8"
            )
            patch_raw = encoded(
                merge_document(
                    [
                        {
                            "logical_id": "fixture:event:0",
                            "old_value": "old-event-a",
                            "new_value": "new-event-a",
                        }
                    ]
                )
            )
            manifest = {
                "type": "br_workstream_update",
                "format_version": 3,
                "workstream_id": "translation",
                "from_version": "0.0.0",
                "to_version": "0.0.1",
                "files": [
                    {
                        "path": rel.as_posix(),
                        "action": "translation_records_merge",
                        "patch_sha256": hashlib.sha256(patch_raw).hexdigest(),
                    }
                ],
            }
            package = Path(tmp) / "missing-capability.zip"
            with zipfile.ZipFile(package, "w") as archive:
                archive.writestr(
                    "WORKSTREAM_UPDATE.json", json.dumps(manifest, indent=2) + "\n"
                )
                archive.writestr(
                    f"patches/{rel.as_posix()}.records.json", patch_raw
                )
            result = subprocess.run(
                [
                    sys.executable,
                    str(MODULE_PATH),
                    "--project-root",
                    str(root),
                    "--package",
                    str(package),
                ],
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("requires capability translation_records_merge/v1", result.stderr)
            self.assertEqual(
                (root / "workstreams/translation/VERSION").read_text(encoding="utf-8"),
                "0.0.0\n",
            )

    def test_rejects_unsupported_translation_unit_type(self) -> None:
        current = fixture("br_event_translation_unit.json")
        current["type"] = "other_translation_unit"
        with self.assertRaisesRegex(wu.UpdateError, "unsupported unit type"):
            wu.apply_translation_records_merge(
                encoded(current),
                merge_document(
                    [
                        {
                            "logical_id": "fixture:event:0",
                            "old_value": "old-event-a",
                            "new_value": "new-event-a",
                        }
                    ]
                ),
                "titles/blue_reflection/translation/events/synthetic_event.json",
            )


if __name__ == "__main__":
    unittest.main()
