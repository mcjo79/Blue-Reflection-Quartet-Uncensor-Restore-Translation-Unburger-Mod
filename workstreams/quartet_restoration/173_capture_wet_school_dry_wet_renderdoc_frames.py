#!/usr/bin/env python3
"""Stage 173: controlled local-only RenderDoc DRY/WET frame capture.

Stage 172 selected the already-installed RenderDoc Vulkan capture backend.  This
stage launches the exact local Quartet process context recorded by stage 172
under .local/build/** and asks the user for two *stable-frame* captures of the
same wet-school scene: one native DRY frame and one native WET frame.

The .rdc files, full command line, environment values, PID/process details and
machine paths remain local-only under .local/build/**.  Evidence exports only
capture labels, sizes, hashes, backend capability and bounded status metadata.
No game file or process memory is modified.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

TOOL_VERSION = "0.2.01"
STAGE = 173
REPORT_DIR = "graphics_capture_dry_wet_evidence"
REPORT_NAME = "BR_quartet_restoration_wet_school_renderdoc_dry_wet_capture_evidence.tar.zst"
STAGE172_REPORT = "BR_quartet_restoration_graphics_capture_capability_evidence.tar.zst"
STAGE172_SHA256 = "d3844aa471b168c9fe24c21a9a08883c44c2632da8ec458f59599cc5e3357093"
PACK10_02_BASELINE_SHA256 = "e798f39c3bcdbb11381197bddf9bd3ad8de6ccf5d7c0c78b22613046d47f5302"
LOCAL_CONTEXT_REL = Path(".local/build/quartet_restoration/graphics_capture/launch_context.json")
LOCAL_STAGE173_REL = Path(".local/build/quartet_restoration/graphics_capture/stage173")
LOCAL_CURRENT_REL = Path(".local/build/quartet_restoration/graphics_capture/stage173_current.json")


class Stage173Error(RuntimeError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise Stage173Error(message)


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(8 * 1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def write_tsv(path: Path, fields: Sequence[str], rows: Iterable[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(fields), delimiter="\t", lineterminator="\n", extrasaction="ignore")
        w.writeheader()
        for row in rows:
            w.writerow({k: row.get(k, "") for k in fields})


def atomic_json(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(obj, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def make_archive(source: Path, output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    tmp = output.with_name(output.name + ".tmp")
    tmp.unlink(missing_ok=True)
    cp = subprocess.run(["tar", "--zstd", "-cf", str(tmp), "-C", str(source.parent), source.name], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    require(cp.returncode == 0, cp.stderr.decode("utf-8", errors="replace").strip() or "archive creation failed")
    os.replace(tmp, output)


def _load_stage172():
    path = Path(__file__).with_name("172_collect_graphics_capture_capability_evidence.py")
    spec = importlib.util.spec_from_file_location("br_restoration_stage172_for173", path)
    require(spec is not None and spec.loader is not None, "cannot load stage172 helper")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


S172 = _load_stage172()


def archive_member_bytes(archive: Path, suffix: str) -> bytes:
    return S172._archive_member_bytes(archive, suffix)


def verify_stage172_contract(project_root: Path) -> dict[str, Any]:
    archive = project_root / ".local/reports/quartet_restoration" / STAGE172_REPORT
    require(archive.is_file(), f"missing canonical stage172 report: {archive}")
    actual = sha256_file(archive)
    require(actual == STAGE172_SHA256, f"stage172 report SHA-256 drift: {actual}")
    summary = json.loads(archive_member_bytes(archive, "SUMMARY.json").decode("utf-8"))
    require(summary.get("stage") == 172, "stage172 SUMMARY stage drift")
    require(summary.get("quality") == "capture_backend_selected", "stage172 quality drift")
    require(summary.get("recommended_capture_backend") == "existing_renderdoc_capture", "stage172 did not select RenderDoc")
    require(summary.get("renderdoc_layer_available") is True, "stage172 RenderDoc layer missing")
    require(summary.get("renderdoccmd_available") is True, "stage172 renderdoccmd missing")
    require(summary.get("pack10_02_unchanged") is True, "stage172 did not preserve PACK10_02")
    require(summary.get("installed_game_modified") is False and summary.get("process_memory_written") is False, "stage172 was not read-only")
    return summary


def verify_game_root(game_root: Path) -> str:
    pak = game_root / "Data" / "PACK10_02.PAK"
    require(pak.is_file(), f"missing PACK10_02 under selected game root: {game_root}")
    actual = sha256_file(pak)
    require(actual == PACK10_02_BASELINE_SHA256, f"selected game root is not exact Restoration baseline: PACK10_02={actual}")
    return actual


def load_launch_context(project_root: Path, game_root: Path) -> dict[str, Any]:
    path = project_root / LOCAL_CONTEXT_REL
    require(path.is_file(), "missing local stage172 launch_context.json; rerun stage172 on this installation")
    obj = json.loads(path.read_text(encoding="utf-8"))
    require(obj.get("machine_specific_local_only") is True and obj.get("must_not_be_packaged_or_exported") is True, "launch context local-only contract drift")
    require(obj.get("pack10_02_sha256") == PACK10_02_BASELINE_SHA256, "launch context baseline hash drift")
    stored_root = Path(str(obj.get("game_root", ""))).resolve()
    require(stored_root == game_root.resolve(), "stage172 launch context belongs to a different Quartet installation; rerun stage172 with this --game-root")
    cmdline = obj.get("cmdline")
    require(isinstance(cmdline, list) and cmdline and all(isinstance(x, str) and x for x in cmdline), "launch context has no executable command line")
    cwd = str(obj.get("cwd", ""))
    require(cwd and Path(cwd).is_dir(), "launch context working directory is unavailable")
    env = obj.get("environment")
    require(isinstance(env, dict), "launch context environment is invalid")
    return obj


def renderdoc_capability(renderdoccmd: str) -> dict[str, Any]:
    cp = subprocess.run([renderdoccmd, "capture", "--help"], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=20)
    text = cp.stdout.decode("utf-8", errors="replace")
    low = text.casefold()
    return {
        "help_returncode": cp.returncode,
        "capture_file_option": "--capture-file" in low,
        "wait_for_exit_option": "--wait-for-exit" in low,
        "help_sha256": hashlib.sha256(cp.stdout).hexdigest(),
    }


def renderdoc_convert_capability(renderdoccmd: str) -> bool:
    cp = subprocess.run([renderdoccmd, "convert", "--help"], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=20)
    text = cp.stdout.decode("utf-8", errors="replace").casefold()
    return cp.returncode == 0 and "xml" in text and "convert-format" in text


def validate_rdc(path: Path) -> dict[str, Any]:
    require(path.is_file(), f"capture file missing: {path.name}")
    size = path.stat().st_size
    require(size >= 4096, f"capture file is unexpectedly small: {path.name} ({size} bytes)")
    with path.open("rb") as f:
        magic = f.read(4)
    require(magic == b"RDOC", f"capture file magic is not RDOC: {path.name}")
    return {"size_bytes": size, "sha256": sha256_file(path), "magic_ok": True}


def snapshot_rdc(run_dir: Path) -> set[Path]:
    return {p.resolve() for p in run_dir.glob("*.rdc") if p.is_file()}


def wait_for_one_new_capture(run_dir: Path, before: set[Path], *, timeout: float = 30.0) -> Path:
    deadline = time.monotonic() + timeout
    seen: set[Path] = set()
    while time.monotonic() < deadline:
        now = snapshot_rdc(run_dir)
        seen = now - before
        if len(seen) == 1:
            p = next(iter(seen))
            s1 = p.stat().st_size
            time.sleep(0.75)
            if p.exists() and p.stat().st_size == s1 and s1 > 0:
                return p
        elif len(seen) > 1:
            raise Stage173Error(f"expected exactly one new capture, found {len(seen)}; do not press the capture hotkey more than once per step")
        time.sleep(0.25)
    raise Stage173Error("no new .rdc capture appeared within 30 seconds; confirm RenderDoc overlay/capture hotkey and rerun stage173")


def _prompt(text: str, *, interactive: bool) -> None:
    print(text, flush=True)
    if interactive:
        input("Press Enter to continue... ")


def run_capture(project_root: Path, game_root: Path, *, interactive: bool = True) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    stage172 = verify_stage172_contract(project_root)
    baseline_before = verify_game_root(game_root)
    context = load_launch_context(project_root, game_root)

    renderdoccmd = shutil.which("renderdoccmd")
    require(renderdoccmd is not None, "renderdoccmd is no longer available")
    caps = renderdoc_capability(renderdoccmd)
    require(caps["capture_file_option"], "installed renderdoccmd capture command does not expose --capture-file")
    require(caps["wait_for_exit_option"], "installed renderdoccmd capture command does not expose --wait-for-exit")

    stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    run_dir = project_root / LOCAL_STAGE173_REL / stamp
    run_dir.mkdir(parents=True, exist_ok=False)
    prefix = run_dir / "wet_school"
    log_path = run_dir / "renderdoccmd.log"

    env = os.environ.copy()
    for key, value in context.get("environment", {}).items():
        if isinstance(key, str) and isinstance(value, str):
            env[key] = value
    cmdline = list(context["cmdline"])
    cwd = str(context["cwd"])
    launch = [renderdoccmd, "capture", "--wait-for-exit", "--capture-file", str(prefix), *cmdline]

    before_all = snapshot_rdc(run_dir)
    log = log_path.open("wb")
    try:
        proc = subprocess.Popen(launch, cwd=cwd, env=env, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
    except Exception:
        log.close()
        raise

    try:
        _prompt(
            "\n[stage173] RenderDoc launch started. Wait until Quartet is fully visible.\n"
            "Load the early wet-school save. Set Hinako to native School Uniform and make sure she is DRY.\n"
            "Do NOT enable any Restoration wet-clothing Fast Test profile. Keep the camera/menu as still as practical.\n"
            "When the DRY scene is fully visible, return to this terminal.",
            interactive=interactive,
        )

        dry_before = snapshot_rdc(run_dir)
        _prompt(
            "\n[stage173] CAPTURE DRY FRAME NOW:\n"
            "  1. Go to the game. DO NOT use Change Wetness.\n"
            "  2. Press RenderDoc's capture hotkey (normally F12) exactly ONCE.\n"
            "  3. Wait for the capture confirmation/overlay update.\n"
            "  4. Return to this terminal.\n",
            interactive=interactive,
        )
        dry_path = wait_for_one_new_capture(run_dir, dry_before)
        dry_meta = validate_rdc(dry_path)
        print(f"[stage173] DRY capture verified locally: {dry_meta['size_bytes']} bytes", flush=True)

        _prompt(
            "\n[stage173] CHANGE STATE TO WET — DO NOT CAPTURE YET:\n"
            "  1. Go to the game.\n"
            "  2. Use native Change Wetness exactly ONCE: DRY -> WET.\n"
            "  3. Wait until the wet appearance is fully visible.\n"
            "  4. Do not move the camera/menu unless necessary. Return to this terminal.\n",
            interactive=interactive,
        )

        wet_before = snapshot_rdc(run_dir)
        _prompt(
            "\n[stage173] CAPTURE WET FRAME NOW:\n"
            "  1. Go to the game. Keep Hinako WET.\n"
            "  2. Press RenderDoc's capture hotkey exactly ONCE.\n"
            "  3. Wait for the capture confirmation/overlay update.\n"
            "  4. Return to this terminal.\n",
            interactive=interactive,
        )
        wet_path = wait_for_one_new_capture(run_dir, wet_before)
        wet_meta = validate_rdc(wet_path)
        require(wet_path.resolve() != dry_path.resolve(), "DRY and WET capture resolved to the same file")
        print(f"[stage173] WET capture verified locally: {wet_meta['size_bytes']} bytes", flush=True)

        _prompt(
            "\n[stage173] Both captures are saved. Close Quartet completely now, then return here.\n"
            "The .rdc files stay local under .local/build/** and are NOT included in evidence.",
            interactive=interactive,
        )

        if interactive:
            try:
                proc.wait(timeout=30)
            except subprocess.TimeoutExpired:
                print("[stage173] renderdoccmd/game is still running; leaving it untouched. The captures are already complete.", flush=True)
    finally:
        log.close()

    all_after = snapshot_rdc(run_dir)
    require(dry_path.resolve() in all_after and wet_path.resolve() in all_after, "capture files disappeared before report finalization")
    baseline_after = verify_game_root(game_root)
    require(baseline_after == baseline_before, "PACK10_02 changed during stage173")

    rows = [
        {"label": "DRY", **dry_meta},
        {"label": "WET", **wet_meta},
    ]
    current = {
        "format_version": 1,
        "type": "br_quartet_restoration_local_stage173_capture_pair",
        "machine_specific_local_only": True,
        "must_not_be_packaged_or_exported": True,
        "run_dir": str(run_dir.resolve()),
        "dry_capture": str(dry_path.resolve()),
        "wet_capture": str(wet_path.resolve()),
        "dry_sha256": dry_meta["sha256"],
        "wet_sha256": wet_meta["sha256"],
        "game_root": str(game_root.resolve()),
        "renderdoccmd_log": str(log_path.resolve()),
    }
    atomic_json(project_root / LOCAL_CURRENT_REL, current)

    summary = {
        "format_version": 1,
        "type": "br_quartet_restoration_wet_school_renderdoc_dry_wet_capture_summary",
        "tool_version": TOOL_VERSION,
        "stage": STAGE,
        "status": "renderdoc_dry_wet_capture_complete_local_only",
        "quality": "two_valid_rdc_frames_captured",
        "stage172_report_sha256": STAGE172_SHA256,
        "stage172_recommended_backend": stage172.get("recommended_capture_backend"),
        "capture_backend": "existing_renderdoc_capture",
        "capture_count": 2,
        "capture_labels": ["DRY", "WET"],
        "dry_capture_sha256": dry_meta["sha256"],
        "wet_capture_sha256": wet_meta["sha256"],
        "dry_capture_size_bytes": dry_meta["size_bytes"],
        "wet_capture_size_bytes": wet_meta["size_bytes"],
        "rdc_magic_verified": True,
        "renderdoc_capture_file_option_verified": bool(caps["capture_file_option"]),
        "renderdoc_wait_for_exit_option_verified": bool(caps["wait_for_exit_option"]),
        "renderdoc_help_sha256": caps["help_sha256"],
        "renderdoc_xml_conversion_available": renderdoc_convert_capability(renderdoccmd),
        "pack10_02_baseline_sha256": baseline_before,
        "pack10_02_unchanged": True,
        "state_sequence_independently_verified": False,
        "state_sequence_user_directed": "stable DRY frame, native Change Wetness DRY->WET, stable WET frame",
        "same_camera_strictly_verified": False,
        "raw_rdc_exported": False,
        "capture_paths_exported": False,
        "selected_game_root_exported": False,
        "full_command_line_exported": False,
        "environment_values_exported": False,
        "current_pid_exported": False,
        "installed_game_modified": False,
        "process_memory_written": False,
        "wet_transparency_mechanism_confirmed": False,
        "render_resource_binding_confirmed": False,
        "material_binding_confirmed": False,
        "shader_binding_confirmed": False,
        "texture_binding_confirmed": False,
        "next_action": "Analyze the two local-only RDC captures by draw/pipeline/resource binding, using capture hashes as immutable identities; do not upload or package raw captures.",
    }
    return summary, rows


def build_report(project_root: Path, game_root: Path, *, interactive: bool = True, report_root: Path | None = None, output_report_root: Path | None = None, create_archive: bool = True) -> tuple[Path | None, dict[str, Any]]:
    summary, rows = run_capture(project_root, game_root, interactive=interactive)
    report_root = report_root or (project_root / ".local/reports/quartet_restoration")
    out_base = output_report_root or report_root
    out = out_base / REPORT_DIR
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    atomic_json(out / "SUMMARY.json", summary)
    write_tsv(out / "CAPTURE_FILES.tsv", ["label", "size_bytes", "sha256", "magic_ok"], rows)
    write_tsv(out / "CAPTURE_BACKEND.tsv", ["backend", "capture_count", "raw_rdc_exported", "capture_paths_exported", "installed_game_modified"], [{
        "backend": summary["capture_backend"],
        "capture_count": summary["capture_count"],
        "raw_rdc_exported": summary["raw_rdc_exported"],
        "capture_paths_exported": summary["capture_paths_exported"],
        "installed_game_modified": summary["installed_game_modified"],
    }])
    archive: Path | None = None
    if create_archive:
        archive = report_root / REPORT_NAME
        make_archive(out, archive)
    return archive, summary


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--project-root", required=True, type=Path)
    p.add_argument("--game-root", required=True, type=Path)
    p.add_argument("--report-root", type=Path)
    p.add_argument("--output-report-root", type=Path)
    p.add_argument("--no-archive", action="store_true")
    p.add_argument("--non-interactive", action="store_true")
    p.add_argument("--preflight", action="store_true")
    return p


def main(argv: Sequence[str] | None = None) -> int:
    a = parser().parse_args(argv)
    project_root = a.project_root.resolve()
    game_root = a.game_root.resolve()
    if a.preflight:
        s172 = verify_stage172_contract(project_root)
        baseline = verify_game_root(game_root)
        ctx = load_launch_context(project_root, game_root)
        rdc = shutil.which("renderdoccmd")
        require(rdc is not None, "renderdoccmd unavailable")
        caps = renderdoc_capability(rdc)
        require(caps["capture_file_option"] and caps["wait_for_exit_option"], "renderdoccmd capture options insufficient")
        print(json.dumps({
            "stage172_backend": s172.get("recommended_capture_backend"),
            "pack10_02_exact_baseline": baseline == PACK10_02_BASELINE_SHA256,
            "launch_context_matches_selected_root": Path(str(ctx.get("game_root", ""))).resolve() == game_root,
            "renderdoc_capture_options_ok": True,
        }, sort_keys=True))
        return 0
    archive, summary = build_report(project_root, game_root, interactive=not a.non_interactive, report_root=a.report_root, output_report_root=a.output_report_root, create_archive=not a.no_archive)
    print(json.dumps(summary, indent=2, sort_keys=True))
    if archive is not None:
        print(f"archive={archive}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
