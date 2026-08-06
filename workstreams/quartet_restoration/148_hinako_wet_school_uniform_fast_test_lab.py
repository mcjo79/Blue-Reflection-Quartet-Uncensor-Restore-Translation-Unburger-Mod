#!/usr/bin/env python3
"""Stage 148: isolated Hinako wet-school-uniform Fast Test Lab transaction.

The transaction targets only Data/PACK10_02.PAK.  It requires the exact stage-147
baseline and the exact stage-147 locally built Fast Test profile.  The installed
baseline is preserved by a same-filesystem hard-link backup before the atomic
replacement.  PACK10_01, PACK10_03 and PACK11 are read-only guards and must stay
byte-identical across activation and rollback.

This harness never promotes runtime validation.  A successful activation merely
creates a reversible runtime probe; the user's visual observation is recorded in
a later, separate stage.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Iterable, Mapping, Sequence

TOOL_VERSION = "0.1.66"
PROFILE_ID = "fast_test_pc00_scl_w_school_wet_original_member_b98a68625fe3"
TARGET_RELATIVE_PATH = "Data/PACK10_02.PAK"
BASELINE_SHA256 = "e798f39c3bcdbb11381197bddf9bd3ad8de6ccf5d7c0c78b22613046d47f5302"
BASELINE_SIZE = 11402829898
PROFILE_SHA256 = "6dc56b3c743dec99dc7ed13828fbecec583077cdd481d879862177a2c5f30162"
PROFILE_SIZE = 11402818129
PROFILE_RELATIVE_PATH = ".local/build/quartet_restoration/fast_test_lab/wet_school_uniform_pc00/fast_test_pc00_scl_w_school_wet_original_member_b98a68625fe3/output/Data/PACK10_02.PAK"
MANIFEST_RELATIVE_PATH = ".local/build/quartet_restoration/core_profiles/fast_test_lab/fast_test_pc00_scl_w_school_wet_original_member_b98a68625fe3.json"
STAGE147_REPORT = "BR_quartet_restoration_hinako_wet_school_uniform_fast_test_profile_evidence.tar.zst"
STAGE147_SHA256 = "5e15a3b5c7fa4f37e3d1a8aedeb40a7cf40ceb6f0b5d9490fe94de287141e8d5"
STAGE147_ROOT = "hinako_wet_school_uniform_fast_test_profile_evidence"
STATE_RELATIVE_PATH = ".local/state/quartet_restoration/hinako_wet_school_uniform_fast_test_lab.json"
GUARD_RELATIVE_PATHS = (
    "Data/PACK10_01.PAK",
    "Data/PACK10_03.PAK",
    "Data/PACK11.PAK",
)
ACTIVATION_REPORT_DIR = "hinako_wet_school_uniform_fast_test_lab_activation_evidence"
ACTIVATION_REPORT_NAME = "BR_quartet_restoration_hinako_wet_school_uniform_fast_test_lab_activation_evidence.tar.zst"
ROLLBACK_REPORT_DIR = "hinako_wet_school_uniform_fast_test_lab_rollback_evidence"
ROLLBACK_REPORT_NAME = "BR_quartet_restoration_hinako_wet_school_uniform_fast_test_lab_rollback_evidence.tar.zst"
FORBIDDEN_REPORT_EXTENSIONS = (
    ".pak", ".kps", ".dxbc", ".elixir", ".elixir.gz", ".g1e", ".g1em",
    ".g1m", ".g1s", ".g1t", ".ebd", ".ebm",
)
OPEN_STATES = {"prepared", "active", "activation_uncertain", "rolling_back", "rollback_uncertain"}


class WetSchoolFastTestError(RuntimeError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise WetSchoolFastTestError(message)


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def safe_relative(value: str, label: str) -> str:
    path = PurePosixPath(str(value).replace("\\", "/"))
    require(bool(path.parts) and not path.is_absolute() and ".." not in path.parts, f"unsafe {label}: {value}")
    return path.as_posix()


def human_bytes(value: int) -> str:
    n = float(value)
    units = ["B", "KiB", "MiB", "GiB", "TiB"]
    for unit in units:
        if n < 1024.0 or unit == units[-1]:
            return f"{n:.2f} {unit}" if unit != "B" else f"{int(n)} B"
        n /= 1024.0
    return f"{value} B"


def progress_line(label: str, done: int, total: int, start: float) -> None:
    if total <= 0:
        return
    width = 28
    ratio = min(1.0, max(0.0, done / total))
    filled = int(width * ratio)
    bar = "#" * filled + "-" * (width - filled)
    elapsed = max(time.monotonic() - start, 1e-6)
    speed = done / elapsed
    sys.stderr.write(
        f"\r[{label}] [{bar}] {ratio * 100:6.2f}%  {human_bytes(done)}/{human_bytes(total)}  {human_bytes(int(speed))}/s"
    )
    sys.stderr.flush()
    if done >= total:
        sys.stderr.write("\n")
        sys.stderr.flush()


def sha256_file(path: Path, *, show_progress: bool = False, label: str | None = None) -> str:
    total = path.stat().st_size
    h = hashlib.sha256()
    done = 0
    start = time.monotonic()
    last = 0.0
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(16 * 1024 * 1024), b""):
            h.update(chunk)
            done += len(chunk)
            if show_progress:
                now = time.monotonic()
                if now - last >= 0.25 or done == total:
                    progress_line(label or f"hash {path.name}", done, total, start)
                    last = now
    return h.hexdigest()


def read_json(path: Path, label: str) -> dict[str, Any]:
    require(path.is_file(), f"missing {label}: {path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise WetSchoolFastTestError(f"cannot parse {label}: {path}: {exc}") from exc
    require(isinstance(value, dict), f"{label} must be a JSON object")
    return value


def atomic_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + ".tmp")
    with temp.open("w", encoding="utf-8") as handle:
        json.dump(value, handle, indent=2, sort_keys=True)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temp, path)
    fsync_dir(path.parent)


def write_tsv(path: Path, fields: Sequence[str], rows: Iterable[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(fields), delimiter="\t", lineterminator="\n", extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fields})


def fsync_dir(path: Path) -> None:
    fd = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def copy_profile_to_temp(source: Path, destination: Path, expected_sha256: str, expected_size: int, *, show_progress: bool) -> None:
    require(source.is_file(), f"missing local Fast Test profile: {source}")
    require(source.stat().st_size == expected_size, f"local Fast Test profile size drift: {source.stat().st_size}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    h = hashlib.sha256()
    done = 0
    start = time.monotonic()
    last = 0.0
    try:
        with source.open("rb") as src, destination.open("xb") as dst:
            while True:
                chunk = src.read(16 * 1024 * 1024)
                if not chunk:
                    break
                dst.write(chunk)
                h.update(chunk)
                done += len(chunk)
                if show_progress:
                    now = time.monotonic()
                    if now - last >= 0.25 or done == expected_size:
                        progress_line("copy profile PACK10_02", done, expected_size, start)
                        last = now
            dst.flush()
            os.fsync(dst.fileno())
        require(done == expected_size, f"copied profile size drift: {done}")
        actual = h.hexdigest()
        require(actual == expected_sha256, f"local Fast Test profile SHA-256 drift while copying: {actual}")
    except Exception:
        destination.unlink(missing_ok=True)
        raise


def validate_stage147_report(report_root: Path) -> dict[str, Any]:
    archive = report_root / STAGE147_REPORT
    require(archive.is_file(), f"missing locally verified stage-147 evidence: {archive}")
    actual = sha256_file(archive)
    require(actual == STAGE147_SHA256, f"stage-147 evidence SHA-256 drift: {actual}")
    listed = subprocess.run(["tar", "--zstd", "-tf", str(archive)], text=True, capture_output=True)
    require(listed.returncode == 0, listed.stderr.strip() or "cannot list stage-147 evidence")
    names = [safe_relative(line.strip(), "stage-147 member") for line in listed.stdout.splitlines() if line.strip()]
    require(names and {PurePosixPath(name).parts[0] for name in names} == {STAGE147_ROOT}, "unexpected stage-147 archive root")
    require(not any(name.casefold().endswith(FORBIDDEN_REPORT_EXTENSIONS) for name in names), "proprietary payload extension in stage-147 evidence")
    with tempfile.TemporaryDirectory(prefix="stage148-stage147-") as td:
        cp = subprocess.run(["tar", "--zstd", "-xf", str(archive), "-C", td], text=True, capture_output=True)
        require(cp.returncode == 0, cp.stderr.strip() or "cannot extract stage-147 evidence")
        summary = read_json(Path(td) / STAGE147_ROOT / "SUMMARY.json", "stage-147 SUMMARY")
    expected = {
        "tool_version": "0.1.65",
        "status": "one_local_pc00_wet_school_source_member_fast_test_profile_built_fully_reextracted_not_installed_runtime_unvalidated",
        "profile_id": PROFILE_ID,
        "target_relative_path": TARGET_RELATIVE_PATH,
        "baseline_sha256": BASELINE_SHA256,
        "baseline_size": BASELINE_SIZE,
        "profile_sha256": PROFILE_SHA256,
        "profile_size": PROFILE_SIZE,
        "pak_changed_member_rows": 1,
        "parent_changed_member_rows": 1,
        "runtime_validated": False,
        "production_eligible": False,
        "normal_composer_eligible": False,
        "fast_test_only": True,
        "visual_effect_confirmed": False,
        "glowlight_deferred": True,
        "validation_failures": 0,
    }
    for key, value in expected.items():
        require(summary.get(key) == value, f"stage-147 summary mismatch: {key}: {summary.get(key)!r} != {value!r}")
    policy = summary.get("policy") or {}
    require(policy.get("installed_game_modified") is False, "stage-147 unexpectedly modified the game")
    require(policy.get("runtime_activation_performed") is False, "stage-147 unexpectedly activated a profile")
    require(policy.get("only_school_wet_g1m_transplanted_inside_parent") is True, "stage-147 inner-member scope drift")
    return summary


def validate_manifest(project_root: Path) -> dict[str, Any]:
    manifest = read_json(project_root / MANIFEST_RELATIVE_PATH, "stage-147 Fast Test manifest")
    expected = {
        "schema_version": 1,
        "profile_id": PROFILE_ID,
        "target_relative_path": TARGET_RELATIVE_PATH,
        "baseline_sha256": BASELINE_SHA256,
        "baseline_size": BASELINE_SIZE,
        "profile_sha256": PROFILE_SHA256,
        "profile_size": PROFILE_SIZE,
        "changed_member_count": 1,
        "runtime_validated": False,
        "workstream_id": "quartet_restoration",
    }
    for key, value in expected.items():
        require(manifest.get(key) == value, f"Fast Test manifest mismatch: {key}: {manifest.get(key)!r} != {value!r}")
    require(manifest.get("changed_members") == ["data/b1/x64/character/pc00/pc00_scl_w.elixir.gz"], "Fast Test changed-member drift")
    require(str(manifest.get("local_profile_path")) == PROFILE_RELATIVE_PATH, "Fast Test local-profile path drift")
    return manifest


def guard_snapshot(quartet_root: Path, *, show_progress: bool) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for index, relative in enumerate(GUARD_RELATIVE_PATHS, start=1):
        path = quartet_root / relative
        require(path.is_file(), f"missing protected archive: {path}")
        digest = sha256_file(path, show_progress=show_progress, label=f"guard {index}/{len(GUARD_RELATIVE_PATHS)} {path.name}")
        rows.append({"relative_path": relative, "sha256": digest, "size": path.stat().st_size})
    return rows


def compare_guards(quartet_root: Path, expected: Sequence[Mapping[str, Any]], *, show_progress: bool) -> list[dict[str, Any]]:
    current = {row["relative_path"]: row for row in guard_snapshot(quartet_root, show_progress=show_progress)}
    output: list[dict[str, Any]] = []
    for row in expected:
        relative = str(row["relative_path"])
        now = current.get(relative)
        require(now is not None, f"protected archive disappeared: {relative}")
        unchanged = now["sha256"] == row["sha256"] and int(now["size"]) == int(row["size"])
        require(unchanged, f"protected archive changed during wet-school Fast Test transaction: {relative}")
        output.append({
            "relative_path": relative,
            "before_sha256": row["sha256"],
            "before_size": row["size"],
            "after_sha256": now["sha256"],
            "after_size": now["size"],
            "unchanged": True,
        })
    return output


def state_path(project_root: Path) -> Path:
    return project_root / STATE_RELATIVE_PATH


def load_state(project_root: Path) -> dict[str, Any] | None:
    path = state_path(project_root)
    if not path.exists():
        return None
    state = read_json(path, "wet-school Fast Test state")
    require(state.get("type") == "br_quartet_restoration_hinako_wet_school_uniform_fast_test_state", "unsupported wet-school state type")
    require(state.get("format_version") == 1, "unsupported wet-school state format")
    require(state.get("profile_id") == PROFILE_ID, "wet-school state profile drift")
    require(state.get("target_relative_path") == TARGET_RELATIVE_PATH, "wet-school state target drift")
    return state


def validate_common(project_root: Path, quartet_root: Path, *, require_version: bool = True) -> tuple[dict[str, Any], Path, Path]:
    require(project_root.is_dir(), f"invalid project root: {project_root}")
    require(quartet_root.is_dir(), f"invalid Quartet root: {quartet_root}")
    if require_version:
        version = (project_root / "workstreams/quartet_restoration/VERSION").read_text(encoding="utf-8").strip()
        require(version == TOOL_VERSION, f"quartet_restoration version must be {TOOL_VERSION}, got {version}")
    report_root = project_root / ".local/reports/quartet_restoration"
    validate_stage147_report(report_root)
    validate_manifest(project_root)
    profile_path = project_root / PROFILE_RELATIVE_PATH
    require(profile_path.is_file(), f"missing local Fast Test profile: {profile_path}")
    require(profile_path.stat().st_size == PROFILE_SIZE, f"local Fast Test profile size drift: {profile_path.stat().st_size}")
    target = quartet_root / TARGET_RELATIVE_PATH
    require(target.is_file(), f"missing installed target: {target}")
    return {"report_root": report_root}, profile_path, target


def preflight(project_root: Path, quartet_root: Path, *, show_progress: bool) -> dict[str, Any]:
    _, profile_path, target = validate_common(project_root, quartet_root)
    state = load_state(project_root)
    if state and state.get("status") in OPEN_STATES:
        current_hash = sha256_file(target, show_progress=show_progress, label="hash installed PACK10_02")
        current_size = target.stat().st_size
        if current_hash == PROFILE_SHA256 and current_size == PROFILE_SIZE and state.get("status") in {"prepared", "active", "activation_uncertain"}:
            mode = "already_active_or_recoverable"
        elif current_hash == BASELINE_SHA256 and current_size == BASELINE_SIZE and state.get("status") == "prepared":
            mode = "prepared_baseline_intact"
        else:
            raise WetSchoolFastTestError(f"open wet-school transaction is not in a recoverable state: {state.get('status')} {current_hash} ({current_size})")
    else:
        current_hash = sha256_file(target, show_progress=show_progress, label="hash installed baseline PACK10_02")
        current_size = target.stat().st_size
        require(current_hash == BASELINE_SHA256 and current_size == BASELINE_SIZE, f"installed PACK10_02 is not the exact stage-147 baseline: {current_hash} ({current_size})")
        mode = "activate"
    profile_hash = sha256_file(profile_path, show_progress=show_progress, label="hash local Fast Test profile")
    require(profile_hash == PROFILE_SHA256, f"local Fast Test profile SHA-256 drift: {profile_hash}")
    guards = guard_snapshot(quartet_root, show_progress=show_progress)
    return {
        "type": "br_quartet_restoration_hinako_wet_school_uniform_fast_test_preflight",
        "format_version": 1,
        "tool_version": TOOL_VERSION,
        "status": "ok",
        "mode": mode,
        "profile_id": PROFILE_ID,
        "target_relative_path": TARGET_RELATIVE_PATH,
        "installed_sha256": current_hash,
        "installed_size": current_size,
        "baseline_sha256": BASELINE_SHA256,
        "baseline_size": BASELINE_SIZE,
        "profile_sha256": PROFILE_SHA256,
        "profile_size": PROFILE_SIZE,
        "guard_rows": guards,
        "runtime_validated": False,
        "production_eligible": False,
        "visual_effect_confirmed": False,
        "writes_performed": False,
    }


def backup_relative(transaction_id: str) -> str:
    return f"Data/.PACK10_02.PAK.brq-wet-school-{transaction_id}.baseline"


def temp_relative(transaction_id: str) -> str:
    return f"Data/.PACK10_02.PAK.brq-wet-school-{transaction_id}.tmp"


def make_state(transaction_id: str, guards: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    return {
        "type": "br_quartet_restoration_hinako_wet_school_uniform_fast_test_state",
        "format_version": 1,
        "tool_version": TOOL_VERSION,
        "status": "prepared",
        "transaction_id": transaction_id,
        "profile_id": PROFILE_ID,
        "target_relative_path": TARGET_RELATIVE_PATH,
        "baseline_sha256": BASELINE_SHA256,
        "baseline_size": BASELINE_SIZE,
        "profile_sha256": PROFILE_SHA256,
        "profile_size": PROFILE_SIZE,
        "backup_relative_path": backup_relative(transaction_id),
        "temp_relative_path": temp_relative(transaction_id),
        "guard_rows": [dict(row) for row in guards],
        "created_utc": utc_now(),
        "updated_utc": utc_now(),
        "runtime_validated": False,
        "production_eligible": False,
        "visual_effect_confirmed": False,
    }


def activate(project_root: Path, quartet_root: Path, *, show_progress: bool) -> dict[str, Any]:
    _, profile_path, target = validate_common(project_root, quartet_root)
    existing = load_state(project_root)
    if existing and existing.get("status") in OPEN_STATES:
        current_hash = sha256_file(target, show_progress=show_progress, label="hash current PACK10_02")
        current_size = target.stat().st_size
        if current_hash == PROFILE_SHA256 and current_size == PROFILE_SIZE:
            existing["status"] = "active"
            existing["updated_utc"] = utc_now()
            atomic_json(state_path(project_root), existing)
            compare_guards(quartet_root, existing.get("guard_rows") or [], show_progress=show_progress)
            return existing
        if current_hash == BASELINE_SHA256 and current_size == BASELINE_SIZE and existing.get("status") == "prepared":
            # Continue the interrupted activation with the existing transaction.
            state = existing
        else:
            raise WetSchoolFastTestError("an open wet-school Fast Test transaction exists in an unsafe state; rollback or inspect before activation")
    else:
        print("[wet-school-fast-test] 1/5 verifying exact installed PACK10_02 baseline", file=sys.stderr)
        baseline_hash = sha256_file(target, show_progress=show_progress, label="hash baseline PACK10_02")
        baseline_size = target.stat().st_size
        require(baseline_hash == BASELINE_SHA256 and baseline_size == BASELINE_SIZE, f"installed PACK10_02 baseline drift: {baseline_hash} ({baseline_size})")
        print("[wet-school-fast-test] 2/5 hashing protected PAK guards", file=sys.stderr)
        guards = guard_snapshot(quartet_root, show_progress=show_progress)
        transaction_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:10]
        state = make_state(transaction_id, guards)
        atomic_json(state_path(project_root), state)

    backup = quartet_root / safe_relative(str(state["backup_relative_path"]), "backup path")
    temp = quartet_root / safe_relative(str(state["temp_relative_path"]), "temp path")
    backup.parent.mkdir(parents=True, exist_ok=True)
    temp.unlink(missing_ok=True)

    target_replaced = False
    try:
        print("[wet-school-fast-test] 3/5 preparing verified profile temp file", file=sys.stderr)
        copy_profile_to_temp(profile_path, temp, PROFILE_SHA256, PROFILE_SIZE, show_progress=show_progress)
        if not backup.exists():
            os.link(target, backup)
            fsync_dir(backup.parent)
        require(backup.is_file(), f"baseline backup was not created: {backup}")
        require(backup.stat().st_size == BASELINE_SIZE, "baseline hard-link backup size drift")
        require(os.path.samefile(target, backup), "pre-activation baseline backup is not a hard link to the verified installed baseline")
        # The hard link is created from the exact baseline target verified above.
        state["backup_inode"] = backup.stat().st_ino
        state["backup_device"] = backup.stat().st_dev
        state["status"] = "prepared"
        state["updated_utc"] = utc_now()
        atomic_json(state_path(project_root), state)

        print("[wet-school-fast-test] 4/5 atomically activating one PACK10_02 Fast Test profile", file=sys.stderr)
        os.replace(temp, target)
        target_replaced = True
        fsync_dir(target.parent)
        require(target.stat().st_size == PROFILE_SIZE, "activated target size drift")
        state["status"] = "active"
        state["activated_utc"] = utc_now()
        state["updated_utc"] = utc_now()
        atomic_json(state_path(project_root), state)

        print("[wet-school-fast-test] 5/5 verifying protected PAK guards", file=sys.stderr)
        compare_guards(quartet_root, state.get("guard_rows") or [], show_progress=show_progress)
        return state
    except Exception as exc:
        temp.unlink(missing_ok=True)
        recovered = False
        # Any failure after the atomic activation is immediately rolled back using
        # the exact same-filesystem baseline hard link.  A failed post-check must
        # never leave the experimental PACK10_02 active.
        if target_replaced and backup.exists():
            os.replace(backup, target)
            fsync_dir(target.parent)
            recovered = True
        elif not target.exists() and backup.exists():
            os.replace(backup, target)
            fsync_dir(target.parent)
            recovered = True
        state["status"] = "rolled_back" if recovered else "activation_uncertain"
        state["activation_failed"] = True
        state["activation_failure"] = str(exc)
        state["exact_baseline_restored"] = recovered
        state["updated_utc"] = utc_now()
        try:
            atomic_json(state_path(project_root), state)
        finally:
            pass
        raise


def validate_runtime_roots(project_root: Path, quartet_root: Path) -> Path:
    require(project_root.is_dir(), f"invalid project root: {project_root}")
    require(quartet_root.is_dir(), f"invalid Quartet root: {quartet_root}")
    version_path = project_root / "workstreams/quartet_restoration/VERSION"
    require(version_path.is_file(), f"missing quartet_restoration VERSION: {version_path}")
    version = version_path.read_text(encoding="utf-8").strip()
    require(version == TOOL_VERSION, f"quartet_restoration version must be {TOOL_VERSION}, got {version}")
    target = quartet_root / TARGET_RELATIVE_PATH
    require(target.is_file(), f"missing installed target: {target}")
    return target


def status(project_root: Path, quartet_root: Path, *, show_progress: bool) -> dict[str, Any]:
    target = validate_runtime_roots(project_root, quartet_root)
    state = load_state(project_root)
    digest = sha256_file(target, show_progress=show_progress, label="hash installed PACK10_02")
    size = target.stat().st_size
    if digest == BASELINE_SHA256 and size == BASELINE_SIZE:
        observed = "baseline"
    elif digest == PROFILE_SHA256 and size == PROFILE_SIZE:
        observed = "fast_test_profile"
    else:
        observed = "unknown_drift"
    return {
        "type": "br_quartet_restoration_hinako_wet_school_uniform_fast_test_status",
        "format_version": 1,
        "tool_version": TOOL_VERSION,
        "state_status": state.get("status") if state else "none",
        "observed_target_state": observed,
        "observed_sha256": digest,
        "observed_size": size,
        "transaction_id": state.get("transaction_id") if state else None,
        "runtime_validated": False,
        "production_eligible": False,
        "visual_effect_confirmed": False,
    }


def rollback(project_root: Path, quartet_root: Path, *, show_progress: bool) -> dict[str, Any]:
    target = validate_runtime_roots(project_root, quartet_root)
    state = load_state(project_root)
    require(state is not None, "no wet-school Fast Test transaction state exists")
    require(state.get("status") in OPEN_STATES or state.get("status") == "rolled_back", f"unsupported transaction state: {state.get('status')}")
    if state.get("status") == "rolled_back":
        digest = sha256_file(target, show_progress=show_progress, label="hash restored PACK10_02")
        require(digest == BASELINE_SHA256 and target.stat().st_size == BASELINE_SIZE, "rolled-back state does not match baseline")
        compare_guards(quartet_root, state.get("guard_rows") or [], show_progress=show_progress)
        return state

    backup = quartet_root / safe_relative(str(state["backup_relative_path"]), "backup path")
    temp = quartet_root / safe_relative(str(state["temp_relative_path"]), "temp path")
    temp.unlink(missing_ok=True)
    require(backup.is_file(), f"missing exact baseline backup: {backup}")

    print("[wet-school-fast-test] 1/4 verifying current active PACK10_02", file=sys.stderr)
    current_hash = sha256_file(target, show_progress=show_progress, label="hash active PACK10_02")
    current_size = target.stat().st_size
    if current_hash == BASELINE_SHA256 and current_size == BASELINE_SIZE:
        # Activation never completed, or an exact baseline was externally restored.
        backup.unlink(missing_ok=True)
        fsync_dir(target.parent)
    else:
        require(current_hash == PROFILE_SHA256 and current_size == PROFILE_SIZE, f"active PACK10_02 drift; refusing rollback overwrite: {current_hash} ({current_size})")
        print("[wet-school-fast-test] 2/4 verifying exact baseline backup", file=sys.stderr)
        backup_hash = sha256_file(backup, show_progress=show_progress, label="hash baseline backup PACK10_02")
        require(backup_hash == BASELINE_SHA256 and backup.stat().st_size == BASELINE_SIZE, f"baseline backup drift: {backup_hash} ({backup.stat().st_size})")
        state["status"] = "rolling_back"
        state["updated_utc"] = utc_now()
        atomic_json(state_path(project_root), state)
        print("[wet-school-fast-test] 3/4 atomically restoring exact baseline PACK10_02", file=sys.stderr)
        os.replace(backup, target)
        fsync_dir(target.parent)
        require(target.stat().st_size == BASELINE_SIZE, "restored baseline size drift")

    print("[wet-school-fast-test] 4/4 verifying protected PAK guards", file=sys.stderr)
    compare_guards(quartet_root, state.get("guard_rows") or [], show_progress=show_progress)
    state["status"] = "rolled_back"
    state["rolled_back_utc"] = utc_now()
    state["updated_utc"] = utc_now()
    state["exact_baseline_restored"] = True
    atomic_json(state_path(project_root), state)
    return state


def ensure_no_payloads(report_dir: Path) -> None:
    for path in report_dir.rglob("*"):
        if path.is_file():
            low = path.name.casefold()
            require(not any(low.endswith(ext) for ext in FORBIDDEN_REPORT_EXTENSIONS), f"proprietary payload leaked into evidence: {path.name}")


def build_report(project_root: Path, quartet_root: Path, state: Mapping[str, Any], *, operation: str, show_progress: bool) -> Path:
    require(operation in {"activation", "rollback"}, f"unsupported report operation: {operation}")
    report_root = project_root / ".local/reports/quartet_restoration"
    directory_name = ACTIVATION_REPORT_DIR if operation == "activation" else ROLLBACK_REPORT_DIR
    archive_name = ACTIVATION_REPORT_NAME if operation == "activation" else ROLLBACK_REPORT_NAME
    report_dir = report_root / directory_name
    if report_dir.exists():
        shutil.rmtree(report_dir)
    report_dir.mkdir(parents=True, exist_ok=True)
    target = quartet_root / TARGET_RELATIVE_PATH
    observed_hash = sha256_file(target, show_progress=show_progress, label=f"hash PACK10_02 for {operation} evidence")
    observed_size = target.stat().st_size
    expected_hash = PROFILE_SHA256 if operation == "activation" else BASELINE_SHA256
    expected_size = PROFILE_SIZE if operation == "activation" else BASELINE_SIZE
    require(observed_hash == expected_hash and observed_size == expected_size, f"{operation} target verification failed")
    guards = compare_guards(quartet_root, state.get("guard_rows") or [], show_progress=show_progress)

    summary = {
        "type": f"br_quartet_restoration_hinako_wet_school_uniform_fast_test_lab_{operation}_evidence_summary",
        "format_version": 1,
        "tool_version": TOOL_VERSION,
        "status": "wet_school_fast_test_profile_active_runtime_observation_pending" if operation == "activation" else "wet_school_fast_test_exact_pack10_02_baseline_restored_runtime_observation_not_yet_canonicalized",
        "operation": operation,
        "transaction_id": state.get("transaction_id"),
        "profile_id": PROFILE_ID,
        "target_relative_path": TARGET_RELATIVE_PATH,
        "observed_target_sha256": observed_hash,
        "observed_target_size": observed_size,
        "baseline_sha256": BASELINE_SHA256,
        "baseline_size": BASELINE_SIZE,
        "profile_sha256": PROFILE_SHA256,
        "profile_size": PROFILE_SIZE,
        "stage147_report_sha256": STAGE147_SHA256,
        "runtime_tested": False,
        "runtime_stable": False,
        "visual_effect_confirmed": False,
        "runtime_validated": False,
        "production_eligible": False,
        "glowlight_deferred": True,
        "protected_archive_rows": len(guards),
        "protected_archives_unchanged": all(row["unchanged"] for row in guards),
        "exact_pack10_02_baseline_restored": operation == "rollback",
        "policy": {
            "only_pack10_02_targeted": True,
            "pack10_01_must_not_change": True,
            "pack10_03_must_not_change": True,
            "pack11_must_not_change": True,
            "same_filesystem_hardlink_baseline_backup_used": True,
            "atomic_target_replace_used": True,
            "core_modified": False,
            "translation_modified": False,
            "legacy_dlc_modified": False,
            "git_modified": False,
            "glowlight_activated": False,
            "runtime_success_does_not_auto_promote_profile": True,
        },
        "next_action": (
            "Launch Quartet, load the existing wet-school-uniform save, observe crash/stability and the wet/see-through appearance, exit the game completely, then run exact rollback before any other PACK10_02 experiment."
            if operation == "activation"
            else "Report the runtime observation together with this rollback evidence. Keep the profile runtime_validated=false until the observation is reviewed and canonically recorded."
        ),
    }
    (report_dir / "SUMMARY.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    write_tsv(report_dir / "TRANSACTION.tsv", [
        "transaction_id", "operation", "profile_id", "target_relative_path", "observed_target_sha256", "observed_target_size", "baseline_sha256", "profile_sha256", "runtime_validated", "production_eligible"
    ], [{
        "transaction_id": state.get("transaction_id"), "operation": operation, "profile_id": PROFILE_ID,
        "target_relative_path": TARGET_RELATIVE_PATH, "observed_target_sha256": observed_hash,
        "observed_target_size": observed_size, "baseline_sha256": BASELINE_SHA256,
        "profile_sha256": PROFILE_SHA256, "runtime_validated": False, "production_eligible": False,
    }])
    write_tsv(report_dir / "GUARDS.tsv", [
        "relative_path", "before_sha256", "before_size", "after_sha256", "after_size", "unchanged"
    ], guards)
    validations = [
        {"check": "stage147_exact_evidence", "passed": True, "detail": STAGE147_SHA256},
        {"check": "target_exact_expected_state", "passed": True, "detail": observed_hash},
        {"check": "protected_paks_unchanged", "passed": True, "detail": str(len(guards))},
        {"check": "runtime_not_auto_promoted", "passed": True, "detail": "runtime_validated=false"},
        {"check": "glowlight_deferred", "passed": True, "detail": "true"},
        {"check": "proprietary_payloads_excluded", "passed": True, "detail": "metadata-only evidence"},
    ]
    write_tsv(report_dir / "VALIDATIONS.tsv", ["check", "passed", "detail"], validations)
    ensure_no_payloads(report_dir)

    archive = report_root / archive_name
    archive.unlink(missing_ok=True)
    with tempfile.TemporaryDirectory(prefix="stage148-tar-") as td:
        tar_path = Path(td) / "evidence.tar"
        cp = subprocess.run([
            "tar", "--sort=name", "--mtime=@0", "--owner=0", "--group=0", "--numeric-owner",
            "-cf", str(tar_path), "-C", str(report_root), directory_name,
        ], text=True, capture_output=True)
        require(cp.returncode == 0, cp.stderr.strip() or "cannot create stage-148 tar")
        cp = subprocess.run(["zstd", "-q", "-f", "-19", str(tar_path), "-o", str(archive)], text=True, capture_output=True)
        require(cp.returncode == 0, cp.stderr.strip() or "cannot compress stage-148 evidence")
    return archive


def cli() -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    for command in ("preflight", "activate", "status", "rollback", "collect-activation", "collect-rollback"):
        p = sub.add_parser(command)
        p.add_argument("--project-root", required=True)
        p.add_argument("--quartet-root", required=True)
        p.add_argument("--quiet-progress", action="store_true")
    args = parser.parse_args()
    project_root = Path(args.project_root).resolve()
    quartet_root = Path(args.quartet_root).resolve()
    show_progress = not args.quiet_progress
    try:
        if args.command == "preflight":
            result = preflight(project_root, quartet_root, show_progress=show_progress)
            print(json.dumps(result, indent=2, sort_keys=True))
        elif args.command == "activate":
            state = activate(project_root, quartet_root, show_progress=show_progress)
            print(json.dumps({"status": state.get("status"), "transaction_id": state.get("transaction_id")}, indent=2, sort_keys=True))
        elif args.command == "status":
            print(json.dumps(status(project_root, quartet_root, show_progress=show_progress), indent=2, sort_keys=True))
        elif args.command == "rollback":
            state = rollback(project_root, quartet_root, show_progress=show_progress)
            print(json.dumps({"status": state.get("status"), "transaction_id": state.get("transaction_id"), "exact_baseline_restored": state.get("exact_baseline_restored", False)}, indent=2, sort_keys=True))
        elif args.command == "collect-activation":
            state = load_state(project_root)
            require(state is not None and state.get("status") == "active", "wet-school Fast Test profile is not active")
            print(build_report(project_root, quartet_root, state, operation="activation", show_progress=show_progress))
        elif args.command == "collect-rollback":
            state = load_state(project_root)
            require(state is not None and state.get("status") == "rolled_back", "wet-school Fast Test transaction is not rolled back")
            print(build_report(project_root, quartet_root, state, operation="rollback", show_progress=show_progress))
    except WetSchoolFastTestError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(cli())
