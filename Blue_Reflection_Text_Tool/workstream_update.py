#!/usr/bin/env python3
"""Apply a checksum-protected update to one independent Blue Reflection workstream.

Format 1 supports strict whole-file add/replace/delete operations.
Format 2 additionally supports ``json_merge`` for status-like JSON documents.
Format 3 adds the versioned ``translation_records_merge/v1`` capability for
canonical translation units. Both merge operations verify only their declared
logical fields; every other file operation remains protected by strict
whole-file SHA-256 checks.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import re
import shutil
import stat
import sys
import tempfile
import time
import zipfile
from pathlib import Path, PurePosixPath
from typing import Any

SUPPORTED_FORMAT_VERSIONS = {1, 2, 3}
JSON_MERGE_FORMAT_VERSION = 1
TRANSLATION_RECORDS_MERGE_FORMAT_VERSION = 1
TRANSLATION_RECORDS_MERGE_CAPABILITY = "translation_records_merge/v1"
TRANSLATION_UNIT_TYPES = {
    "br_event_translation_unit",
    "br_system_translation_unit",
}
TRANSLATION_RECORDS_ENTRY_KEYS = {
    "path",
    "action",
    "capability",
    "patch_sha256",
    "mode",
}
TRANSLATION_RECORDS_PATH_RE = re.compile(
    r"^titles/(?:blue_reflection|second_light|blue_reflection_sun|blue_reflection_ray)/translation/.+\.json$"
)
_MISSING = object()


class UpdateError(RuntimeError):
    pass


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_ownership(project_root: Path, workstream_id: str) -> list[str]:
    path = project_root / "config/workstream_ownership.tsv"
    with path.open("r", encoding="utf-8", newline="") as handle:
        rows = csv.DictReader(handle, delimiter="\t")
        prefixes = [
            row["path_prefix"]
            for row in rows
            if row["workstream_id"] == workstream_id and row["permission"] == "write"
        ]
    if not prefixes:
        raise UpdateError(f"unknown workstream or no writable paths: {workstream_id}")
    return prefixes


def safe_relpath(raw: str) -> str:
    path = PurePosixPath(raw)
    if path.is_absolute() or ".." in path.parts or not path.parts:
        raise UpdateError(f"unsafe update path: {raw}")
    return path.as_posix()


def parse_mode(value: Any, rel: str) -> int | None:
    if value is None:
        return None
    if isinstance(value, int):
        mode = value
    elif isinstance(value, str):
        text = value.strip()
        if not re.fullmatch(r"[0-7]{3,4}", text):
            raise UpdateError(f"invalid mode for {rel}: {value}")
        mode = int(text, 8)
    else:
        raise UpdateError(f"invalid mode type for {rel}")
    mode &= 0o7777
    if mode & 0o7000:
        raise UpdateError(f"special permission bits are not allowed for {rel}")
    return mode


def zip_member_mode(info: zipfile.ZipInfo) -> int | None:
    mode = (info.external_attr >> 16) & 0o7777
    if mode:
        return mode & 0o777
    return None


def path_allowed(rel: str, prefixes: list[str]) -> bool:
    for prefix in prefixes:
        normalized = prefix.rstrip("/")
        if rel == normalized or rel.startswith(normalized + "/"):
            return True
    return False


def read_version(project_root: Path, workstream_id: str) -> str:
    path = project_root / "workstreams" / workstream_id / "VERSION"
    try:
        return path.read_text(encoding="utf-8").strip()
    except FileNotFoundError as exc:
        raise UpdateError(f"missing workstream version file: {path}") from exc


def acquire_lock(project_root: Path, workstream_id: str) -> Path:
    lock_root = project_root / ".local" / "locks"
    lock_root.mkdir(parents=True, exist_ok=True)
    lock = lock_root / f"{workstream_id}.lock"
    try:
        lock.mkdir()
    except FileExistsError as exc:
        raise UpdateError(f"another {workstream_id} update is already active: {lock}") from exc
    (lock / "owner").write_text(
        f"pid={os.getpid()}\nstarted={time.time()}\n", encoding="utf-8"
    )
    return lock


def load_manifest(archive: zipfile.ZipFile) -> dict[str, Any]:
    try:
        raw = archive.read("WORKSTREAM_UPDATE.json")
    except KeyError as exc:
        raise UpdateError("update package has no WORKSTREAM_UPDATE.json") from exc
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise UpdateError(f"invalid workstream manifest: {exc}") from exc
    version = data.get("format_version")
    if data.get("type") != "br_workstream_update" or version not in SUPPORTED_FORMAT_VERSIONS:
        raise UpdateError("unsupported workstream update format")
    return data


def load_json_merge_document(
    archive: zipfile.ZipFile, rel: str, expected_sha: Any
) -> dict[str, Any]:
    member = f"patches/{rel}.json"
    try:
        raw = archive.read(member)
    except KeyError as exc:
        raise UpdateError(f"missing JSON merge member: {member}") from exc
    if not isinstance(expected_sha, str) or sha256_bytes(raw) != expected_sha:
        raise UpdateError(f"JSON merge checksum mismatch: {rel}")
    try:
        document = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise UpdateError(f"invalid JSON merge document for {rel}: {exc}") from exc
    if (
        not isinstance(document, dict)
        or document.get("type") != "br_json_merge"
        or document.get("format_version") != JSON_MERGE_FORMAT_VERSION
    ):
        raise UpdateError(f"unsupported JSON merge document for {rel}")
    changes = document.get("changes")
    if not isinstance(changes, list) or not changes:
        raise UpdateError(f"JSON merge has no changes: {rel}")
    return document


def load_translation_records_merge_document(
    archive: zipfile.ZipFile, rel: str, expected_sha: Any
) -> dict[str, Any]:
    member = f"patches/{rel}.records.json"
    try:
        raw = archive.read(member)
    except KeyError as exc:
        raise UpdateError(f"missing translation record merge member: {member}") from exc
    if not isinstance(expected_sha, str) or sha256_bytes(raw) != expected_sha:
        raise UpdateError(f"translation record merge checksum mismatch: {rel}")
    try:
        document = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise UpdateError(f"invalid translation record merge document for {rel}: {exc}") from exc
    if (
        not isinstance(document, dict)
        or document.get("type") != "br_translation_records_merge"
        or document.get("format_version") != TRANSLATION_RECORDS_MERGE_FORMAT_VERSION
    ):
        raise UpdateError(f"unsupported translation record merge document for {rel}")
    allowed_document_keys = {
        "type",
        "format_version",
        "target_array",
        "stable_key",
        "mutable_field",
        "changes",
    }
    extra_document_keys = set(document) - allowed_document_keys
    if extra_document_keys:
        raise UpdateError(
            f"translation record merge document has unsupported fields in {rel}: "
            + ", ".join(sorted(extra_document_keys))
        )
    if document.get("target_array") != "/records":
        raise UpdateError(f"translation record merge target must be /records: {rel}")
    if document.get("stable_key") != "logical_id":
        raise UpdateError(f"translation record merge stable key must be logical_id: {rel}")
    if document.get("mutable_field") != "en":
        raise UpdateError(f"translation record merge may modify only en: {rel}")
    changes = document.get("changes")
    if not isinstance(changes, list) or not changes:
        raise UpdateError(f"translation record merge has no changes: {rel}")
    return document


def decode_pointer(pointer: Any, rel: str) -> list[str]:
    if not isinstance(pointer, str) or not pointer.startswith("/") or pointer == "/":
        raise UpdateError(f"invalid non-root JSON pointer in {rel}: {pointer}")
    return [part.replace("~1", "/").replace("~0", "~") for part in pointer[1:].split("/")]


def get_at(root: Any, parts: list[str]) -> Any:
    node = root
    for part in parts:
        if isinstance(node, dict):
            if part not in node:
                return _MISSING
            node = node[part]
        elif isinstance(node, list):
            try:
                index = int(part)
            except ValueError:
                return _MISSING
            if index < 0 or index >= len(node):
                return _MISSING
            node = node[index]
        else:
            return _MISSING
    return node


def parent_at(root: Any, parts: list[str], rel: str) -> tuple[Any, str]:
    node = root
    for part in parts[:-1]:
        if isinstance(node, dict):
            if part not in node:
                raise UpdateError(
                    f"missing JSON merge parent in {rel}: /{'/'.join(parts[:-1])}"
                )
            node = node[part]
        elif isinstance(node, list):
            try:
                index = int(part)
            except ValueError as exc:
                raise UpdateError(f"invalid JSON list index in {rel}: {part}") from exc
            if index < 0 or index >= len(node):
                raise UpdateError(f"JSON list index out of range in {rel}: {index}")
            node = node[index]
        else:
            raise UpdateError(f"non-container JSON merge parent in {rel}")
    return node, parts[-1]


def set_at(root: Any, parts: list[str], value: Any, rel: str) -> None:
    parent, key = parent_at(root, parts, rel)
    if isinstance(parent, dict):
        parent[key] = value
        return
    if isinstance(parent, list):
        try:
            index = int(key)
        except ValueError as exc:
            raise UpdateError(f"invalid JSON list index in {rel}: {key}") from exc
        if index < 0 or index >= len(parent):
            raise UpdateError(f"JSON list index out of range in {rel}: {index}")
        parent[index] = value
        return
    raise UpdateError(f"invalid JSON merge parent in {rel}")


def delete_at(root: Any, parts: list[str], rel: str) -> None:
    parent, key = parent_at(root, parts, rel)
    if isinstance(parent, dict):
        if key not in parent:
            raise UpdateError(f"missing JSON key during merge in {rel}: {key}")
        del parent[key]
        return
    if isinstance(parent, list):
        try:
            index = int(key)
        except ValueError as exc:
            raise UpdateError(f"invalid JSON list index in {rel}: {key}") from exc
        if index < 0 or index >= len(parent):
            raise UpdateError(f"JSON list index out of range in {rel}: {index}")
        del parent[index]
        return
    raise UpdateError(f"invalid JSON merge parent in {rel}")


def json_equal(left: Any, right: Any) -> bool:
    return json.dumps(left, ensure_ascii=False, sort_keys=True, separators=(",", ":")) == json.dumps(
        right, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )


def describe_json_value(value: Any) -> str:
    if value is _MISSING:
        return "<missing>"
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def parse_json_merge_changes(document: dict[str, Any], rel: str) -> list[dict[str, Any]]:
    parsed: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, change in enumerate(document["changes"], 1):
        if not isinstance(change, dict):
            raise UpdateError(f"invalid JSON merge change {index}: {rel}")
        pointer = change.get("path")
        parts = decode_pointer(pointer, rel)
        if pointer in seen:
            raise UpdateError(f"duplicate JSON merge pointer in {rel}: {pointer}")
        seen.add(pointer)

        has_old = "old" in change
        old_missing = change.get("old_missing") is True
        if has_old == old_missing:
            raise UpdateError(
                f"JSON merge change {index} must define exactly one of old or old_missing: {rel}"
            )

        has_new = "new" in change
        delete = change.get("delete") is True
        if has_new == delete:
            raise UpdateError(
                f"JSON merge change {index} must define exactly one of new or delete: {rel}"
            )

        expected_old = _MISSING if old_missing else change["old"]
        desired_new = _MISSING if delete else change["new"]
        if expected_old is not _MISSING and desired_new is not _MISSING:
            if json_equal(expected_old, desired_new):
                raise UpdateError(f"JSON merge change {index} has identical old/new: {rel}")
        parsed.append(
            {
                "path": pointer,
                "parts": parts,
                "expected_old": expected_old,
                "desired_new": desired_new,
            }
        )
    return parsed


def apply_json_merge(
    current: bytes, document: dict[str, Any], rel: str
) -> tuple[bytes, list[dict[str, Any]]]:
    try:
        root = json.loads(current)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise UpdateError(f"json_merge target is not valid UTF-8 JSON: {rel}: {exc}") from exc
    parsed = parse_json_merge_changes(document, rel)

    # Validate every touched pointer before mutating any of them.
    for change in parsed:
        actual = get_at(root, change["parts"])
        desired = change["desired_new"]
        if desired is _MISSING and actual is _MISSING:
            continue
        if desired is not _MISSING and actual is not _MISSING and json_equal(actual, desired):
            continue
        expected = change["expected_old"]
        matches_expected = (
            actual is _MISSING
            if expected is _MISSING
            else actual is not _MISSING and json_equal(actual, expected)
        )
        if not matches_expected:
            raise UpdateError(
                f"JSON merge conflict in {rel} at {change['path']}: expected "
                f"{describe_json_value(expected)}, found {describe_json_value(actual)}"
            )

    for change in parsed:
        actual = get_at(root, change["parts"])
        desired = change["desired_new"]
        if desired is _MISSING:
            if actual is not _MISSING:
                delete_at(root, change["parts"], rel)
        elif actual is _MISSING or not json_equal(actual, desired):
            set_at(root, change["parts"], desired, rel)

    output = (json.dumps(root, indent=2, ensure_ascii=False) + "\n").encode("utf-8")
    return output, parsed


def verify_json_merge(path: Path, changes: list[dict[str, Any]], rel: str) -> None:
    try:
        root = json.loads(path.read_text(encoding="utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise UpdateError(f"post-update JSON is invalid for {rel}: {exc}") from exc
    for change in changes:
        actual = get_at(root, change["parts"])
        desired = change["desired_new"]
        if desired is _MISSING:
            if actual is not _MISSING:
                raise UpdateError(f"post-update JSON pointer still exists in {rel}: {change['path']}")
        elif actual is _MISSING or not json_equal(actual, desired):
            raise UpdateError(f"post-update JSON pointer mismatch in {rel}: {change['path']}")


def parse_translation_record_changes(
    document: dict[str, Any], rel: str
) -> list[dict[str, str]]:
    parsed: list[dict[str, str]] = []
    seen: set[str] = set()
    for index, change in enumerate(document["changes"], 1):
        if not isinstance(change, dict):
            raise UpdateError(f"invalid translation record change {index}: {rel}")
        allowed_keys = {"logical_id", "old_value", "new_value"}
        extra = set(change) - allowed_keys
        if extra:
            raise UpdateError(
                f"translation record change {index} has unsupported fields in {rel}: "
                + ", ".join(sorted(extra))
            )
        logical_id = change.get("logical_id")
        old_value = change.get("old_value")
        new_value = change.get("new_value")
        if not isinstance(logical_id, str) or not logical_id:
            raise UpdateError(f"invalid logical_id in translation record change {index}: {rel}")
        if logical_id in seen:
            raise UpdateError(f"duplicate logical_id in translation merge patch for {rel}: {logical_id}")
        seen.add(logical_id)
        if not isinstance(old_value, str) or not isinstance(new_value, str):
            raise UpdateError(
                f"old_value and new_value must be strings for {logical_id} in {rel}"
            )
        if old_value == new_value:
            raise UpdateError(f"translation record change has identical old/new for {logical_id}: {rel}")
        parsed.append(
            {
                "logical_id": logical_id,
                "old_value": old_value,
                "new_value": new_value,
            }
        )
    return parsed


def apply_translation_records_merge(
    current: bytes, document: dict[str, Any], rel: str
) -> tuple[bytes, list[dict[str, str]]]:
    try:
        root = json.loads(current)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise UpdateError(
            f"translation_records_merge target is not valid UTF-8 JSON: {rel}: {exc}"
        ) from exc
    if not isinstance(root, dict):
        raise UpdateError(f"translation unit root must be an object: {rel}")
    unit_type = root.get("type")
    if unit_type not in TRANSLATION_UNIT_TYPES:
        raise UpdateError(
            f"translation_records_merge/v1 target has unsupported unit type in {rel}: "
            f"{unit_type!r}"
        )
    if root.get("format_version") != 1:
        raise UpdateError(
            f"translation_records_merge/v1 requires translation unit format_version 1: {rel}"
        )
    records = root.get("records")
    if not isinstance(records, list):
        raise UpdateError(f"translation unit has no /records array: {rel}")

    parsed = parse_translation_record_changes(document, rel)
    wanted = {change["logical_id"] for change in parsed}
    matches: dict[str, list[dict[str, Any]]] = {logical_id: [] for logical_id in wanted}
    for record_index, record in enumerate(records):
        if not isinstance(record, dict):
            raise UpdateError(f"record {record_index} is not an object in {rel}")
        logical_id = record.get("logical_id")
        if logical_id in matches:
            matches[logical_id].append(record)

    # Preflight every requested record and value before mutating any record.
    for change in parsed:
        logical_id = change["logical_id"]
        found = matches[logical_id]
        if not found:
            raise UpdateError(f"logical_id not found in {rel}: {logical_id}")
        if len(found) != 1:
            raise UpdateError(
                f"logical_id must occur exactly once in {rel}: {logical_id} (found {len(found)})"
            )
        record = found[0]
        current_value = record.get("en", _MISSING)
        if current_value is _MISSING:
            raise UpdateError(f"record has no en field in {rel}: {logical_id}")
        if not isinstance(current_value, str):
            raise UpdateError(f"record en field is not a string in {rel}: {logical_id}")
        if current_value == change["new_value"]:
            continue
        if current_value != change["old_value"]:
            raise UpdateError(
                f"translation record conflict in {rel} for {logical_id}: expected "
                f"{json.dumps(change['old_value'], ensure_ascii=False)}, found "
                f"{json.dumps(current_value, ensure_ascii=False)}"
            )

    for change in parsed:
        record = matches[change["logical_id"]][0]
        if record["en"] == change["old_value"]:
            record["en"] = change["new_value"]

    output = (json.dumps(root, indent=2, ensure_ascii=False) + "\n").encode("utf-8")
    return output, parsed


def verify_translation_records_merge(
    path: Path, changes: list[dict[str, str]], rel: str
) -> None:
    try:
        root = json.loads(path.read_text(encoding="utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise UpdateError(f"post-update translation JSON is invalid for {rel}: {exc}") from exc
    if not isinstance(root, dict) or not isinstance(root.get("records"), list):
        raise UpdateError(f"post-update translation unit has no /records array: {rel}")
    records = root["records"]
    for change in changes:
        logical_id = change["logical_id"]
        found = [
            record
            for record in records
            if isinstance(record, dict) and record.get("logical_id") == logical_id
        ]
        if len(found) != 1:
            raise UpdateError(
                f"post-update logical_id must occur exactly once in {rel}: {logical_id}"
            )
        if found[0].get("en", _MISSING) != change["new_value"]:
            raise UpdateError(
                f"post-update en mismatch in {rel} for logical_id: {logical_id}"
            )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", required=True)
    parser.add_argument("--package", required=True)
    args = parser.parse_args()

    project_root = Path(args.project_root).expanduser().resolve()
    package = Path(args.package).expanduser().resolve()
    if not project_root.is_dir():
        raise UpdateError(f"project root does not exist: {project_root}")
    if not package.is_file():
        raise UpdateError(f"update package does not exist: {package}")

    lock: Path | None = None
    staging: Path | None = None
    try:
        with zipfile.ZipFile(package) as archive:
            bad = archive.testzip()
            if bad:
                raise UpdateError(f"corrupt update member: {bad}")
            manifest = load_manifest(archive)
            format_version = manifest["format_version"]
            workstream_id = str(manifest.get("workstream_id", ""))
            from_version = str(manifest.get("from_version", ""))
            to_version = str(manifest.get("to_version", ""))
            files = manifest.get("files")
            if not workstream_id or not from_version or not to_version:
                raise UpdateError("manifest is missing workstream/version fields")
            if not isinstance(files, list) or not files:
                raise UpdateError("manifest files must be a non-empty array")

            prefixes = load_ownership(project_root, workstream_id)
            current_version = read_version(project_root, workstream_id)
            if current_version == to_version:
                print(f"{workstream_id} is already at {to_version}.")
                return 0
            if current_version != from_version:
                raise UpdateError(
                    f"{workstream_id} expects {from_version}, current version is {current_version}"
                )

            version_rel = f"workstreams/{workstream_id}/VERSION"
            if not path_allowed(version_rel, prefixes):
                prefixes = prefixes + [f"workstreams/{workstream_id}/"]

            lock = acquire_lock(project_root, workstream_id)
            normalized_files: list[dict[str, Any]] = []
            seen: set[str] = set()
            allowed_actions = {"add", "replace", "delete"}
            if format_version >= 2:
                allowed_actions.add("json_merge")
            if format_version >= 3:
                allowed_actions.add("translation_records_merge")

            for entry in files:
                if not isinstance(entry, dict):
                    raise UpdateError("file manifest entry is not an object")
                rel = safe_relpath(str(entry.get("path", "")))
                if rel in seen:
                    raise UpdateError(f"duplicate update path: {rel}")
                seen.add(rel)
                if not path_allowed(rel, prefixes):
                    raise UpdateError(f"{workstream_id} update is not allowed to write: {rel}")

                action = entry.get("action")
                if action not in allowed_actions:
                    raise UpdateError(f"unsupported action for {rel}: {action}")
                target = project_root / rel
                requested_mode = parse_mode(entry.get("mode"), rel)
                existing_mode = stat.S_IMODE(target.stat().st_mode) if target.exists() else None
                staged_bytes: bytes | None = None
                merge_changes: list[dict[str, Any]] | None = None
                payload_mode: int | None = None

                if action == "json_merge":
                    if target.suffix.lower() != ".json":
                        raise UpdateError(f"json_merge target must use .json: {rel}")
                    if not target.is_file():
                        raise UpdateError(f"expected JSON file is missing: {target}")
                    document = load_json_merge_document(
                        archive, rel, entry.get("patch_sha256")
                    )
                    staged_bytes, merge_changes = apply_json_merge(
                        target.read_bytes(), document, rel
                    )
                elif action == "translation_records_merge":
                    extra_entry_keys = set(entry) - TRANSLATION_RECORDS_ENTRY_KEYS
                    if extra_entry_keys:
                        raise UpdateError(
                            f"translation_records_merge manifest entry has unsupported fields "
                            f"for {rel}: " + ", ".join(sorted(extra_entry_keys))
                        )
                    if entry.get("capability") != TRANSLATION_RECORDS_MERGE_CAPABILITY:
                        raise UpdateError(
                            f"translation_records_merge requires capability "
                            f"{TRANSLATION_RECORDS_MERGE_CAPABILITY} for {rel}"
                        )
                    if workstream_id != "translation":
                        raise UpdateError(
                            "translation_records_merge is allowed only for the translation workstream"
                        )
                    if not TRANSLATION_RECORDS_PATH_RE.fullmatch(rel):
                        raise UpdateError(
                            f"translation_records_merge target is outside canonical translation paths: {rel}"
                        )
                    if not target.is_file():
                        raise UpdateError(f"expected translation JSON file is missing: {target}")
                    forbidden_hashes = [
                        key for key in ("old_sha256", "new_sha256") if key in entry
                    ]
                    if forbidden_hashes:
                        raise UpdateError(
                            f"translation_records_merge must not declare whole-file hashes for {rel}: "
                            + ", ".join(forbidden_hashes)
                        )
                    document = load_translation_records_merge_document(
                        archive, rel, entry.get("patch_sha256")
                    )
                    staged_bytes, merge_changes = apply_translation_records_merge(
                        target.read_bytes(), document, rel
                    )
                else:
                    old_sha = entry.get("old_sha256")
                    new_sha = entry.get("new_sha256")
                    if target.exists():
                        current_sha = sha256_file(target)
                        if action == "add" and current_sha != new_sha:
                            raise UpdateError(f"refusing to overwrite existing file: {target}")
                        if action in {"replace", "delete"} and current_sha not in {
                            old_sha,
                            new_sha,
                        }:
                            raise UpdateError(f"locally modified managed file: {target}")
                    elif action in {"replace", "delete"}:
                        raise UpdateError(f"expected existing file is missing: {target}")

                    if action != "delete":
                        member = f"payload/{rel}"
                        try:
                            info = archive.getinfo(member)
                            staged_bytes = archive.read(member)
                        except KeyError as exc:
                            raise UpdateError(f"missing payload member: {member}") from exc
                        if not isinstance(new_sha, str) or sha256_bytes(staged_bytes) != new_sha:
                            raise UpdateError(f"payload checksum mismatch: {rel}")
                        payload_mode = zip_member_mode(info)

                effective_mode = requested_mode
                if effective_mode is None:
                    effective_mode = existing_mode if existing_mode is not None else payload_mode
                if effective_mode is None and action != "delete":
                    effective_mode = 0o644

                normalized_files.append(
                    {
                        **entry,
                        "path": rel,
                        "_effective_mode": effective_mode,
                        "_staged_bytes": staged_bytes,
                        "_merge_changes": merge_changes,
                    }
                )

            staging = Path(
                tempfile.mkdtemp(prefix=f"br-{workstream_id}-", dir=project_root / ".local")
            )
            backup = (
                project_root
                / ".local"
                / "backups"
                / "workstreams"
                / workstream_id
                / time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
            )
            backup.mkdir(parents=True, exist_ok=True)

            for entry in normalized_files:
                if entry["action"] == "delete":
                    continue
                rel = entry["path"]
                destination = staging / rel
                destination.parent.mkdir(parents=True, exist_ok=True)
                staged_bytes = entry["_staged_bytes"]
                if not isinstance(staged_bytes, bytes):
                    raise UpdateError(f"internal staging error: {rel}")
                destination.write_bytes(staged_bytes)
                mode = entry.get("_effective_mode")
                if mode is not None:
                    os.chmod(destination, mode)

            applied: list[tuple[str, bool]] = []
            try:
                for entry in normalized_files:
                    rel = entry["path"]
                    target = project_root / rel
                    existed = target.exists()
                    if existed:
                        backup_target = backup / rel
                        backup_target.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copy2(target, backup_target)
                    if entry["action"] == "delete":
                        target.unlink()
                    else:
                        source = staging / rel
                        target.parent.mkdir(parents=True, exist_ok=True)
                        temporary = target.with_name(target.name + ".brupdate.tmp")
                        shutil.copy2(source, temporary)
                        mode = entry.get("_effective_mode")
                        if mode is not None:
                            os.chmod(temporary, mode)
                        os.replace(temporary, target)
                    applied.append((rel, existed))

                for entry in normalized_files:
                    if entry["action"] == "delete":
                        continue
                    rel = entry["path"]
                    target = project_root / rel
                    if entry["action"] == "json_merge":
                        changes = entry.get("_merge_changes")
                        if not isinstance(changes, list):
                            raise UpdateError(f"internal JSON merge verification error: {rel}")
                        verify_json_merge(target, changes, rel)
                    elif entry["action"] == "translation_records_merge":
                        changes = entry.get("_merge_changes")
                        if not isinstance(changes, list):
                            raise UpdateError(
                                f"internal translation record merge verification error: {rel}"
                            )
                        verify_translation_records_merge(target, changes, rel)
                    elif sha256_file(target) != entry["new_sha256"]:
                        raise UpdateError(f"post-update checksum mismatch: {rel}")
                    expected_mode = entry.get("_effective_mode")
                    if expected_mode is not None:
                        actual_mode = stat.S_IMODE(target.stat().st_mode)
                        if actual_mode != expected_mode:
                            raise UpdateError(
                                f"post-update mode mismatch for {rel}: "
                                f"{actual_mode:04o} != {expected_mode:04o}"
                            )

                version_path = project_root / version_rel
                version_backup = backup / version_rel
                version_backup.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(version_path, version_backup)
                version_tmp = version_path.with_name(version_path.name + ".brupdate.tmp")
                version_tmp.write_text(to_version + "\n", encoding="utf-8")
                os.replace(version_tmp, version_path)
            except Exception:
                for rel, existed in reversed(applied):
                    target = project_root / rel
                    backup_target = backup / rel
                    if existed and backup_target.exists():
                        target.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copy2(backup_target, target)
                    elif not existed and target.exists():
                        target.unlink()
                raise

            print(f"Updated {workstream_id}: {from_version} -> {to_version}")
            print(f"Backup: {backup}")
            return 0
    finally:
        if staging and staging.exists():
            shutil.rmtree(staging, ignore_errors=True)
        if lock and lock.exists():
            shutil.rmtree(lock, ignore_errors=True)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except UpdateError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
