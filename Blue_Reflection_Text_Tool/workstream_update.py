#!/usr/bin/env python3
"""Apply a checksum-protected update to one independent Blue Reflection workstream."""

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

FORMAT_VERSION = 1


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
    p = PurePosixPath(raw)
    if p.is_absolute() or ".." in p.parts or not p.parts:
        raise UpdateError(f"unsafe update path: {raw}")
    return p.as_posix()



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
    if data.get("type") != "br_workstream_update" or data.get("format_version") != FORMAT_VERSION:
        raise UpdateError("unsupported workstream update format")
    return data


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
            workstream_id = str(manifest.get("workstream_id", ""))
            from_version = str(manifest.get("from_version", ""))
            to_version = str(manifest.get("to_version", ""))
            files = manifest.get("files")
            if not workstream_id or not from_version or not to_version:
                raise UpdateError("manifest is missing workstream/version fields")
            if not isinstance(files, list) or not files:
                raise UpdateError("manifest files must be a non-empty array")

            prefixes = load_ownership(project_root, workstream_id)
            current = read_version(project_root, workstream_id)
            if current == to_version:
                print(f"{workstream_id} is already at {to_version}.")
                return 0
            if current != from_version:
                raise UpdateError(
                    f"{workstream_id} expects {from_version}, current version is {current}"
                )

            version_rel = f"workstreams/{workstream_id}/VERSION"
            if not path_allowed(version_rel, prefixes):
                # VERSION is always implicitly owned by its workstream.
                prefixes = prefixes + [f"workstreams/{workstream_id}/"]

            normalized_files: list[dict[str, Any]] = []
            seen: set[str] = set()
            for entry in files:
                if not isinstance(entry, dict):
                    raise UpdateError("file manifest entry is not an object")
                rel = safe_relpath(str(entry.get("path", "")))
                if rel in seen:
                    raise UpdateError(f"duplicate update path: {rel}")
                seen.add(rel)
                if not path_allowed(rel, prefixes):
                    raise UpdateError(
                        f"{workstream_id} update is not allowed to write: {rel}"
                    )
                action = entry.get("action")
                if action not in {"add", "replace", "delete"}:
                    raise UpdateError(f"unsupported action for {rel}: {action}")
                old_sha = entry.get("old_sha256")
                new_sha = entry.get("new_sha256")
                requested_mode = parse_mode(entry.get("mode"), rel)
                target = project_root / rel
                existing_mode = None
                if target.exists():
                    existing_mode = stat.S_IMODE(target.stat().st_mode)
                    current_sha = sha256_file(target)
                    if action == "add" and current_sha != new_sha:
                        raise UpdateError(f"refusing to overwrite existing file: {target}")
                    if action in {"replace", "delete"} and current_sha not in {old_sha, new_sha}:
                        raise UpdateError(f"locally modified managed file: {target}")
                elif action in {"replace", "delete"}:
                    raise UpdateError(f"expected existing file is missing: {target}")
                payload_mode = None
                if action != "delete":
                    member = f"payload/{rel}"
                    try:
                        info = archive.getinfo(member)
                        payload = archive.read(member)
                    except KeyError as exc:
                        raise UpdateError(f"missing payload member: {member}") from exc
                    if sha256_bytes(payload) != new_sha:
                        raise UpdateError(f"payload checksum mismatch: {rel}")
                    payload_mode = zip_member_mode(info)
                effective_mode = requested_mode
                if effective_mode is None:
                    effective_mode = existing_mode if existing_mode is not None else payload_mode
                if effective_mode is None and action != "delete":
                    effective_mode = 0o644
                normalized_files.append({
                    **entry,
                    "path": rel,
                    "_effective_mode": effective_mode,
                })

            lock = acquire_lock(project_root, workstream_id)
            staging = Path(tempfile.mkdtemp(prefix=f"br-{workstream_id}-", dir=project_root / ".local"))
            backup = (
                project_root / ".local" / "backups" / "workstreams" /
                workstream_id / time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
            )
            backup.mkdir(parents=True, exist_ok=True)

            # Extract all payload before changing the project.
            for entry in normalized_files:
                if entry["action"] == "delete":
                    continue
                rel = entry["path"]
                destination = staging / rel
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(archive.read(f"payload/{rel}"))
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
                    if sha256_file(target) != entry["new_sha256"]:
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
