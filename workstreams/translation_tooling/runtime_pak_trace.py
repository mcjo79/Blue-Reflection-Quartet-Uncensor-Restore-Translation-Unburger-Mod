#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any

TARGET_ARCHIVES = {
    "blue_reflection_original": {
        "required": ("DATA/PACK01.PAK", "DATA/PACK02_1.PAK"),
        "optional": ("DATA/PACK02_3.PAK",),
    },
    "blue_reflection_quartet": {
        "required": ("Data/PACK11.PAK", "Data/PACK12.PAK"),
        "optional": (),
    },
    "second_light_original": {
        "required": ("Data/PACK01.PAK", "Data/PACK02.PAK"),
        "optional": (),
    },
}


class TraceError(RuntimeError):
    pass


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_json(path: Path, expected_type: str | None = None) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise TraceError(f"Required file is missing: {path}") from exc
    except json.JSONDecodeError as exc:
        raise TraceError(f"Invalid JSON {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise TraceError(f"Unexpected JSON root: {path}")
    if expected_type is not None and value.get("type") != expected_type:
        raise TraceError(f"Unexpected JSON type: {path}")
    return value


def sanitize(value: str, project_root: Path, game_root: Path) -> str:
    replacements = [
        (str(game_root), "<GAME_ROOT>"),
        (str(project_root), "<PROJECT_ROOT>"),
        (str(Path.home()), "<HOME>"),
    ]
    result = value
    for source, target in replacements:
        if source:
            result = result.replace(source, target)
    return result


def process_sampler(
    stop: threading.Event,
    output_path: Path,
    project_root: Path,
    game_root: Path,
) -> None:
    uid = os.getuid()
    seen: set[str] = set()
    keywords = (
        "blue reflection",
        "blue_reflection",
        "steam_app_658260",
        "steam_app_3825390",
        "steam_app_1423600",
        "wine",
        "proton",
    )

    with output_path.open("w", encoding="utf-8") as output:
        while not stop.wait(0.75):
            for proc in Path("/proc").glob("[0-9]*"):
                try:
                    if proc.stat().st_uid != uid:
                        continue
                    pid = proc.name
                    command = (
                        (proc / "cmdline")
                        .read_bytes()
                        .replace(b"\0", b" ")
                        .decode(errors="replace")
                        .strip()
                    )
                    comm = (proc / "comm").read_text(errors="replace").strip()
                    try:
                        cwd = os.readlink(proc / "cwd")
                    except OSError:
                        cwd = ""
                    try:
                        executable = os.readlink(proc / "exe")
                    except OSError:
                        executable = ""
                    combined = " ".join((command, comm, cwd, executable)).casefold()
                    candidate = any(keyword in combined for keyword in keywords)

                    pak_fds: list[str] = []
                    if candidate:
                        for fd in (proc / "fd").glob("*"):
                            try:
                                target = os.readlink(fd)
                            except OSError:
                                continue
                            if target.casefold().endswith(".pak"):
                                pak_fds.append(target)

                    if not candidate and not pak_fds:
                        continue

                    observation = {
                        "timestamp_utc": time.strftime(
                            "%Y-%m-%dT%H:%M:%SZ", time.gmtime()
                        ),
                        "pid": int(pid),
                        "comm": sanitize(comm, project_root, game_root),
                        "command": sanitize(command, project_root, game_root),
                        "cwd": sanitize(cwd, project_root, game_root),
                        "executable": sanitize(
                            executable, project_root, game_root
                        ),
                        "pak_fds": sorted(
                            sanitize(path, project_root, game_root)
                            for path in pak_fds
                        ),
                    }
                    key = json.dumps(observation, sort_keys=True)
                    if key in seen:
                        continue
                    seen.add(key)
                    output.write(
                        json.dumps(observation, ensure_ascii=False) + "\n"
                    )
                    output.flush()
                except (FileNotFoundError, PermissionError, ProcessLookupError, OSError):
                    continue


def parse_events(
    raw_path: Path,
    game_root: Path,
    project_root: Path,
) -> tuple[list[dict[str, str]], list[str]]:
    events: list[dict[str, str]] = []
    pak_paths: set[str] = set()
    if not raw_path.is_file():
        return events, []

    for line in raw_path.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            timestamp, path = line.split("\t", 1)
        except ValueError:
            continue
        normalized = str(Path(path))
        sanitized = sanitize(normalized, project_root, game_root)
        events.append({"timestamp": timestamp, "path": sanitized})
        if normalized.casefold().endswith(".pak"):
            try:
                relative = Path(normalized).resolve().relative_to(game_root.resolve())
                pak_paths.add(relative.as_posix())
            except (ValueError, OSError):
                pak_paths.add(sanitized)
    return events, sorted(pak_paths)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Trace which game PAKs are opened at runtime."
    )
    parser.add_argument("--project-root", required=True)
    parser.add_argument("--game-root", required=True)
    parser.add_argument("--target", required=True, choices=sorted(TARGET_ARCHIVES))
    parser.add_argument(
        "--duration",
        type=float,
        default=0,
        help="non-interactive trace duration in seconds; 0 waits for Enter",
    )
    args = parser.parse_args()

    project_root = Path(args.project_root).expanduser().resolve()
    game_root = Path(args.game_root).expanduser().resolve()
    target = args.target

    if shutil.which("inotifywait") is None:
        raise TraceError(
            "inotifywait is missing. On Arch/CachyOS install package: "
            "sudo pacman -S inotify-tools"
        )
    if not game_root.is_dir():
        raise TraceError(f"Game root is missing: {game_root}")

    state_path = (
        project_root
        / ".local/state/translation_game_test"
        / f"{target}.json"
    )
    state = load_json(state_path, "br_translation_game_test_state")
    if state.get("status") != "installed":
        raise TraceError(
            "The diagnostic build must remain installed while tracing. "
            "Run step 09 install first."
        )
    if Path(str(state.get("game_root", ""))).resolve() != game_root:
        raise TraceError("Configured game root differs from test-install state")

    rules = TARGET_ARCHIVES[target]
    state_files = {
        str(item.get("relative_path")): item
        for item in state.get("files", [])
        if isinstance(item, dict)
    }
    present = set(state_files)
    allowed = set(rules["required"]) | set(rules["optional"])
    if not set(rules["required"]).issubset(present) or not present.issubset(allowed):
        raise TraceError(
            f"Unexpected installed test files: {sorted(state_files)}"
        )
    expected = tuple(
        relative for relative in (*rules["required"], *rules["optional"])
        if relative in state_files
    )

    file_status: list[dict[str, Any]] = []
    for relative in expected:
        item = state_files[relative]
        path = game_root / relative
        if not path.is_file():
            raise TraceError(f"Installed test PAK is missing: {path}")
        current_hash = sha256_file(path)
        expected_hash = str(item.get("installed_sha256", ""))
        if current_hash != expected_hash:
            raise TraceError(
                f"Current PAK does not match the installed diagnostic build: "
                f"{path}\n{current_hash} != {expected_hash}"
            )
        file_status.append(
            {
                "relative_path": relative,
                "sha256": current_hash,
                "bytes": path.stat().st_size,
                "matches_installed_test": True,
            }
        )

    transaction_id = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    trace_root = (
        project_root
        / ".local/reports/translation/runtime_trace"
        / transaction_id
    )
    trace_root.mkdir(parents=True, exist_ok=False)
    raw_events = trace_root / "inotify_raw.tsv"
    stderr_path = trace_root / "inotify_stderr.txt"
    process_path = trace_root / "process_observations.jsonl"

    stop = threading.Event()
    sampler = threading.Thread(
        target=process_sampler,
        args=(stop, process_path, project_root, game_root),
        daemon=True,
    )
    sampler.start()

    with raw_events.open("w", encoding="utf-8") as event_output, stderr_path.open(
        "w", encoding="utf-8"
    ) as error_output:
        monitor = subprocess.Popen(
            [
                "inotifywait",
                "-m",
                "-r",
                "-q",
                "-e",
                "open",
                "--format",
                "%T\t%w%f",
                "--timefmt",
                "%Y-%m-%dT%H:%M:%S%z",
                str(game_root),
            ],
            stdout=event_output,
            stderr=error_output,
            text=True,
        )
        time.sleep(1.0)
        if monitor.poll() is not None:
            raise TraceError(
                f"inotifywait exited before tracing began; see {stderr_path}"
            )

        print()
        print("Runtime PAK trace is active.")
        print("1. Launch the game normally.")
        print("2. Reach the title screen and start/load one dialogue scene.")
        print("3. Exit the game completely.")
        if args.duration > 0:
            print(f"Tracing for {args.duration:.1f} seconds...")
            time.sleep(args.duration)
        else:
            input("4. Return here and press Enter to finish the trace: ")

        monitor.terminate()
        try:
            monitor.wait(timeout=5)
        except subprocess.TimeoutExpired:
            monitor.kill()
            monitor.wait(timeout=5)

    stop.set()
    sampler.join(timeout=3)

    events, opened_paks = parse_events(raw_events, game_root, project_root)
    expected_opened = [
        relative for relative in expected if relative in opened_paks
    ]
    unexpected_opened = [
        path for path in opened_paks if path not in expected
    ]

    if expected_opened:
        diagnosis = "configured_test_archives_were_opened"
    elif events:
        diagnosis = "configured_game_root_used_but_expected_paks_not_observed"
    else:
        diagnosis = "no_access_to_configured_game_root_observed"

    sanitized_events = trace_root / "events.tsv"
    with sanitized_events.open("w", encoding="utf-8") as output:
        for event in events:
            output.write(f"{event['timestamp']}\t{event['path']}\n")
    raw_events.unlink(missing_ok=True)

    process_observations = 0
    pak_fd_paths: set[str] = set()
    if process_path.is_file():
        for line in process_path.read_text(
            encoding="utf-8", errors="replace"
        ).splitlines():
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                continue
            process_observations += 1
            for path in item.get("pak_fds", []):
                if isinstance(path, str):
                    pak_fd_paths.add(path)

    report = {
        "type": "br_runtime_pak_trace_report",
        "format_version": 1,
        "status": "ok",
        "target": target,
        "transaction_id": transaction_id,
        "game_root": "<GAME_ROOT>",
        "diagnostic_test_state": state.get("transaction_id"),
        "installed_test_files": file_status,
        "inotify": {
            "event_count": len(events),
            "opened_paks": opened_paks,
            "expected_paks_opened": expected_opened,
            "unexpected_paks_opened": unexpected_opened,
        },
        "process_sampling": {
            "observations": process_observations,
            "pak_fd_paths": sorted(pak_fd_paths),
        },
        "diagnosis": diagnosis,
        "next_action": "upload_report_before_restoring_the_test_build",
    }
    report_path = (
        project_root
        / ".local/reports/translation/BR_RUNTIME_PAK_TRACE_REPORT.json"
    )
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    print()
    print(f"Trace diagnosis: {diagnosis}")
    print(f"Expected PAKs observed: {len(expected_opened)}/{len(expected)}")
    print(f"Report: {report_path}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (TraceError, KeyboardInterrupt) as exc:
        if isinstance(exc, KeyboardInterrupt):
            print("ERROR: trace interrupted", file=sys.stderr)
        else:
            print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
