#!/usr/bin/env python3
"""Stage 172: read-only graphics-API capture capability audit.

Stage 171 closed the internal pointer/object/call-path instrumentation route:
three recurrent WET-only callpaths were observed, but none carried renderer
module provenance.  Stage 172 does not sample memory, callchains, or graphics
calls.  It establishes which *external graphics API capture* path is actually
available for the explicitly selected clean Quartet installation.

The audit inspects the selected running process' mapped renderer stack, queries
the Vulkan loader for discoverable layers, checks capture/build tools, and
stores a local-only launch context under .local/build for the next stage.  Full
machine paths, PID, command line, environment values, and mapped addresses are
never written to evidence.  No game file or process memory is modified.
"""
from __future__ import annotations

import argparse
import csv
import ctypes
import ctypes.util
import hashlib
import importlib.util
import json
import os
import platform
import shutil
import subprocess
import sys
import tempfile
import time
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

TOOL_VERSION = "0.2.00"
STAGE = 172
REPORT_DIR = "graphics_capture_capability_evidence"
REPORT_NAME = "BR_quartet_restoration_graphics_capture_capability_evidence.tar.zst"
STAGE171_REPORT = "BR_quartet_restoration_wet_renderer_transition_callpath_evidence.tar.zst"
STAGE171_SHA256 = "9fcc90452eed4bdd641da45aacdd280af4e8775c05cda2dba0589a0e5b1aebb5"
PACK10_02_BASELINE_SHA256 = "e798f39c3bcdbb11381197bddf9bd3ad8de6ccf5d7c0c78b22613046d47f5302"
LOCAL_LAUNCH_CONTEXT_REL = Path(".local/build/quartet_restoration/graphics_capture/launch_context.json")

CAPTURE_ENV_KEYS = {
    "DISPLAY", "WAYLAND_DISPLAY", "XDG_RUNTIME_DIR", "XDG_SESSION_TYPE",
    "WINEPREFIX", "WINEARCH", "WINEDLLOVERRIDES", "WINEDEBUG",
    "STEAM_COMPAT_DATA_PATH", "STEAM_COMPAT_CLIENT_INSTALL_PATH",
    "STEAM_RUNTIME", "STEAM_RUNTIME_LIBRARY_PATH",
    "PROTON_LOG", "PROTON_NO_ESYNC", "PROTON_NO_FSYNC", "PROTON_USE_WINED3D",
    "LD_LIBRARY_PATH", "PATH", "VK_ICD_FILENAMES", "VK_DRIVER_FILES",
    "VK_LAYER_PATH", "VK_ADD_LAYER_PATH", "VK_IMPLICIT_LAYER_PATH",
    "VK_ADD_IMPLICIT_LAYER_PATH", "VK_INSTANCE_LAYERS",
    "DXVK_CONFIG", "DXVK_CONFIG_FILE", "DXVK_LOG_LEVEL", "DXVK_LOG_PATH",
}


class Stage172Error(RuntimeError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise Stage172Error(message)


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(8 * 1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()


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


def _load_stage171():
    path = Path(__file__).with_name("171_trace_wet_renderer_transition_callpath.py")
    spec = importlib.util.spec_from_file_location("br_restoration_stage171_for172", path)
    require(spec is not None and spec.loader is not None, "cannot load stage171 helper")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


S171 = _load_stage171()
S170 = S171.S170
S164 = S170.S164


def _archive_member_bytes(archive: Path, suffix: str) -> bytes:
    cp = subprocess.run(["tar", "--zstd", "-tf", str(archive)], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    require(cp.returncode == 0, cp.stderr.decode("utf-8", errors="replace").strip() or "cannot list archive")
    names = cp.stdout.decode("utf-8", errors="replace").splitlines()
    matches = [n for n in names if n.endswith("/" + suffix) or n == suffix]
    require(len(matches) == 1, f"archive expected exactly one {suffix}, found {len(matches)}")
    cp = subprocess.run(["tar", "--zstd", "-xOf", str(archive), matches[0]], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    require(cp.returncode == 0, cp.stderr.decode("utf-8", errors="replace").strip() or f"cannot read {suffix}")
    return cp.stdout


def verify_stage171_contract(project_root: Path) -> dict[str, Any]:
    archive = project_root / ".local/reports/quartet_restoration" / STAGE171_REPORT
    require(archive.is_file(), f"missing canonical stage171 report: {archive}")
    actual = sha256_file(archive)
    require(actual == STAGE171_SHA256, f"stage171 report SHA-256 drift: {actual}")
    summary = json.loads(_archive_member_bytes(archive, "SUMMARY.json").decode("utf-8"))
    require(summary.get("stage") == 171, "stage171 SUMMARY stage drift")
    require(summary.get("quality") == "no_recurrent_wet_only_renderer_associated_callpath_candidate", "stage171 quality drift")
    require(int(summary.get("recurrent_wet_only_callpath_candidate_rows", -1)) == 3, "stage171 recurrent callpath count drift")
    require(int(summary.get("recurrent_wet_only_renderer_callpath_candidate_rows", -1)) == 0, "stage171 renderer callpath count drift")
    require(summary.get("pack10_02_unchanged") is True, "stage171 did not preserve PACK10_02")
    require(summary.get("process_memory_written") is False and summary.get("installed_game_modified") is False, "stage171 was not read-only")
    require(summary.get("wet_transparency_mechanism_confirmed") is False, "stage171 unexpectedly claims transparency")
    return summary


def verify_game_root(game_root: Path) -> str:
    pak = game_root / "Data" / "PACK10_02.PAK"
    require(pak.is_file(), f"missing PACK10_02 under selected game root: {game_root}")
    actual = sha256_file(pak)
    require(actual == PACK10_02_BASELINE_SHA256, f"selected game root is not exact Restoration baseline: PACK10_02={actual}")
    return actual


def parse_proc_environ(pid: int, *, proc_root: Path = Path("/proc")) -> dict[str, str]:
    try:
        raw = (proc_root / str(pid) / "environ").read_bytes()
    except (OSError, PermissionError):
        return {}
    out: dict[str, str] = {}
    for item in raw.split(b"\x00"):
        if not item or b"=" not in item:
            continue
        k, v = item.split(b"=", 1)
        key = k.decode("utf-8", errors="replace")
        if key in CAPTURE_ENV_KEYS:
            out[key] = v.decode("utf-8", errors="replace")
    return out


def parse_proc_cmdline(pid: int, *, proc_root: Path = Path("/proc")) -> list[str]:
    try:
        raw = (proc_root / str(pid) / "cmdline").read_bytes()
    except (OSError, PermissionError):
        return []
    return [p.decode("utf-8", errors="replace") for p in raw.split(b"\x00") if p]


def parse_proc_cwd(pid: int, *, proc_root: Path = Path("/proc")) -> str:
    try:
        return os.readlink(proc_root / str(pid) / "cwd")
    except (OSError, PermissionError):
        return ""


def launch_mode(cmdline: Sequence[str], env: Mapping[str, str]) -> str:
    text = " ".join(cmdline).casefold()
    if "STEAM_COMPAT_DATA_PATH" in env or "proton" in text:
        return "steam_or_proton_managed"
    if "WINEPREFIX" in env or any(token in text for token in ("wine64", "wine-preloader", "wine ", "wine")):
        return "wine_managed"
    return "unknown"


def local_launch_context(project_root: Path, game_root: Path, proc: Mapping[str, Any], mode: str) -> Path:
    pid = int(proc["pid"])
    env = parse_proc_environ(pid)
    obj = {
        "format_version": 1,
        "type": "br_quartet_restoration_local_graphics_capture_launch_context",
        "created_unix": int(time.time()),
        "game_root": str(game_root.resolve()),
        "pack10_02_sha256": PACK10_02_BASELINE_SHA256,
        "process_selection_mode": mode,
        "pid_at_capture": pid,
        "cmdline": parse_proc_cmdline(pid),
        "cwd": parse_proc_cwd(pid),
        "environment": env,
        "launch_mode": launch_mode(parse_proc_cmdline(pid), env),
        "machine_specific_local_only": True,
        "must_not_be_packaged_or_exported": True,
    }
    path = project_root / LOCAL_LAUNCH_CONTEXT_REL
    atomic_json(path, obj)
    return path


def renderer_family_from_basename(base: str) -> str:
    low = base.casefold()
    if "d3d11" in low:
        return "d3d11"
    if "d3d12" in low:
        return "d3d12"
    if "dxgi" in low:
        return "dxgi"
    if "dxvk" in low:
        return "dxvk_named"
    if "vkd3d" in low:
        return "vkd3d"
    if "winevulkan" in low:
        return "winevulkan"
    if low.startswith("libvulkan") or low == "vulkan-1.dll":
        return "vulkan_loader_or_icd"
    if "vulkan" in low:
        return "vulkan_other"
    if "wined3d" in low:
        return "wined3d"
    if "libgl" in low or "opengl" in low:
        return "opengl"
    return "other"


def process_renderer_stack_rows(maps: Sequence[Any]) -> tuple[list[dict[str, Any]], dict[str, bool], Path | None]:
    by_key: dict[tuple[str, str], dict[str, Any]] = {}
    vulkan_loader_path: Path | None = None
    flags = {
        "d3d11_mapped": False,
        "dxgi_mapped": False,
        "winevulkan_mapped": False,
        "vulkan_loader_mapped": False,
        "wined3d_mapped": False,
    }
    for m in maps:
        path_text = getattr(m, "path", "") or ""
        if not path_text or path_text.startswith("["):
            continue
        base = Path(path_text).name
        family = renderer_family_from_basename(base)
        if family == "other":
            continue
        key = (family, base)
        row = by_key.setdefault(key, {"module_family": family, "module_basename": base, "mapping_rows": 0, "executable_mapping_rows": 0})
        row["mapping_rows"] += 1
        if "x" in getattr(m, "perms", ""):
            row["executable_mapping_rows"] += 1
        if family == "d3d11": flags["d3d11_mapped"] = True
        if family == "dxgi": flags["dxgi_mapped"] = True
        if family == "winevulkan": flags["winevulkan_mapped"] = True
        if family == "vulkan_loader_or_icd":
            flags["vulkan_loader_mapped"] = True
            p = Path(path_text)
            if vulkan_loader_path is None and p.is_file() and base.startswith("libvulkan"):
                vulkan_loader_path = p
        if family == "wined3d": flags["wined3d_mapped"] = True
    rows = sorted(by_key.values(), key=lambda r: (r["module_family"], r["module_basename"]))
    return rows, flags, vulkan_loader_path


class VkLayerProperties(ctypes.Structure):
    _fields_ = [
        ("layerName", ctypes.c_char * 256),
        ("specVersion", ctypes.c_uint32),
        ("implementationVersion", ctypes.c_uint32),
        ("description", ctypes.c_char * 256),
    ]


def _decode_cbuf(buf: Any) -> str:
    raw = bytes(buf)
    return raw.split(b"\x00", 1)[0].decode("utf-8", errors="replace")


def enumerate_vulkan_layers(loader_path: Path | None = None) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    candidates: list[str] = []
    if loader_path is not None:
        candidates.append(str(loader_path))
    libname = ctypes.util.find_library("vulkan")
    if libname and libname not in candidates:
        candidates.append(libname)
    candidates.extend(x for x in ("libvulkan.so.1", "libvulkan.so") if x not in candidates)
    last_error = ""
    for candidate in candidates:
        try:
            lib = ctypes.CDLL(candidate)
            fn = lib.vkEnumerateInstanceLayerProperties
            fn.argtypes = [ctypes.POINTER(ctypes.c_uint32), ctypes.POINTER(VkLayerProperties)]
            fn.restype = ctypes.c_int32
            count = ctypes.c_uint32(0)
            rc = int(fn(ctypes.byref(count), None))
            if rc != 0:
                last_error = f"enumerate_count_vkresult_{rc}"
                continue
            arr = (VkLayerProperties * int(count.value))()
            if count.value:
                rc = int(fn(ctypes.byref(count), arr))
                if rc not in (0, 5):  # VK_SUCCESS or VK_INCOMPLETE
                    last_error = f"enumerate_rows_vkresult_{rc}"
                    continue
            rows: list[dict[str, Any]] = []
            for i in range(int(count.value)):
                name = _decode_cbuf(arr[i].layerName)
                desc = _decode_cbuf(arr[i].description)
                low = name.casefold()
                if "renderdoc" in low:
                    category = "renderdoc_capture"
                elif "api_dump" in low or "apidump" in low:
                    category = "api_dump"
                elif "validation" in low:
                    category = "validation"
                else:
                    category = "other"
                rows.append({
                    "layer_name": name,
                    "category": category,
                    "spec_version": int(arr[i].specVersion),
                    "implementation_version": int(arr[i].implementationVersion),
                    "description_sha256": sha256_text(desc),
                })
            rows.sort(key=lambda r: r["layer_name"])
            return rows, {"ok": True, "layer_count": len(rows), "loader_source": "process_mapped" if loader_path is not None and candidate == str(loader_path) else "host_loader"}
        except Exception as exc:
            last_error = type(exc).__name__
    return [], {"ok": False, "layer_count": 0, "loader_source": "unavailable", "reason": last_error or "no_vulkan_loader"}


def safe_version_line(command: Sequence[str], *, timeout: float = 4.0) -> str:
    try:
        cp = subprocess.run(list(command), stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=timeout, check=False)
    except Exception:
        return ""
    text = cp.stdout.decode("utf-8", errors="replace").replace("\x00", "")
    for line in text.splitlines():
        line = line.strip()
        if line:
            return line[:240]
    return ""


def host_tool_rows() -> tuple[list[dict[str, Any]], dict[str, bool]]:
    specs = [
        ("renderdoccmd", ["renderdoccmd", "version"]),
        ("qrenderdoc", None),
        ("vulkaninfo", None),
        ("cc", ["cc", "--version"]),
        ("clang", ["clang", "--version"]),
        ("gcc", ["gcc", "--version"]),
    ]
    rows: list[dict[str, Any]] = []
    flags: dict[str, bool] = {}
    for name, version_cmd in specs:
        resolved = shutil.which(name)
        available = resolved is not None
        flags[f"{name}_available"] = available
        version = safe_version_line(version_cmd) if available and version_cmd else ""
        rows.append({
            "tool": name,
            "available": available,
            "version_line_sha256": sha256_text(version) if version else "",
            "version_line_present": bool(version),
        })
    return rows, flags


def compile_shared_library_probe() -> tuple[bool, str]:
    cc = shutil.which("cc") or shutil.which("gcc") or shutil.which("clang")
    if not cc:
        return False, "no_c_compiler"
    src = b"int br_capture_probe(void){return 172;}\n"
    with tempfile.TemporaryDirectory(prefix="br_stage172_cc_") as td:
        out = Path(td) / "probe.so"
        try:
            cp = subprocess.run([cc, "-shared", "-fPIC", "-O2", "-x", "c", "-", "-o", str(out)], input=src, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=20)
        except Exception as exc:
            return False, type(exc).__name__
        if cp.returncode != 0 or not out.is_file():
            return False, "compile_failed"
        try:
            ctypes.CDLL(str(out))
        except Exception as exc:
            return False, f"dlopen_{type(exc).__name__}"
    return True, "ok"


def vulkan_headers_compile_probe() -> tuple[bool, str]:
    cc = shutil.which("cc") or shutil.which("gcc") or shutil.which("clang")
    if not cc:
        return False, "no_c_compiler"
    src = b"#include <vulkan/vulkan.h>\nint main(void){return VK_SUCCESS;}\n"
    try:
        cp = subprocess.run([cc, "-fsyntax-only", "-x", "c", "-"], input=src, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=20)
    except Exception as exc:
        return False, type(exc).__name__
    return (cp.returncode == 0, "ok" if cp.returncode == 0 else "headers_unavailable_or_compile_failed")


def choose_capture_backend(stack_flags: Mapping[str, bool], layer_rows: Sequence[Mapping[str, Any]], tool_flags: Mapping[str, bool], compiler_ok: bool, loader_ok: bool) -> tuple[str, str]:
    names = {str(r.get("category")) for r in layer_rows}
    vulkan_stack = bool(stack_flags.get("vulkan_loader_mapped") or stack_flags.get("winevulkan_mapped"))
    if not vulkan_stack:
        return "blocked_no_active_vulkan_stack", "The selected game process did not expose a Vulkan/winevulkan stack; do not attempt a Vulkan capture layer yet."
    if "renderdoc_capture" in names and tool_flags.get("renderdoccmd_available"):
        return "existing_renderdoc_capture", "Use the already installed RenderDoc Vulkan capture layer/toolchain in the next stage; no project-local layer build is needed."
    if "api_dump" in names:
        return "existing_vulkan_api_dump", "Use the already discoverable Vulkan API-dump layer for a bounded transition capture before building a custom layer."
    if compiler_ok and loader_ok:
        return "project_local_vulkan_layer", "No suitable existing capture layer is discoverable. Build and enable a project-local explicit Vulkan layer for pipeline/blend-state capture in the next stage."
    return "blocked_missing_capture_prerequisites", "Vulkan is active but neither an existing capture layer nor a validated local shared-library toolchain is available."


def root_preflight(project_root: Path, game_root: Path) -> dict[str, Any]:
    summary = verify_stage171_contract(project_root)
    baseline = verify_game_root(game_root)
    return {
        "stage171_sha256": STAGE171_SHA256,
        "stage171_quality": summary.get("quality"),
        "pack10_02_sha256": baseline,
        "game_root_source": "explicit_cli",
        "selected_game_root_exported_to_evidence": False,
    }


def run_audit(project_root: Path, game_root: Path, *, explicit_pid: int | None = None, interactive: bool = True) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    stage171_summary = verify_stage171_contract(project_root)
    baseline = verify_game_root(game_root)
    proc, process_selection_mode = S170.discover_game_process_stage170(game_root, explicit_pid=explicit_pid, interactive=interactive)
    pid = int(proc["pid"])
    maps = S164.read_maps(pid)
    stack_rows, stack_flags, loader_path = process_renderer_stack_rows(maps)
    layer_rows, loader_info = enumerate_vulkan_layers(loader_path)
    tool_rows, tool_flags = host_tool_rows()
    compiler_ok, compiler_reason = compile_shared_library_probe()
    headers_ok, headers_reason = vulkan_headers_compile_probe()
    env = parse_proc_environ(pid)
    cmdline = parse_proc_cmdline(pid)
    mode = launch_mode(cmdline, env)
    context_path = local_launch_context(project_root, game_root, proc, process_selection_mode)
    backend, backend_reason = choose_capture_backend(stack_flags, layer_rows, tool_flags, compiler_ok, bool(loader_info.get("ok")))
    baseline_after = sha256_file(game_root / "Data" / "PACK10_02.PAK")
    require(baseline_after == baseline == PACK10_02_BASELINE_SHA256, "PACK10_02 changed during capability audit")
    summary = {
        "format_version": 1,
        "type": "br_quartet_restoration_graphics_capture_capability_evidence_summary",
        "stage": STAGE,
        "tool_version": TOOL_VERSION,
        "status": "graphics_api_capture_capability_audit_complete_read_only",
        "quality": "capture_backend_selected" if not backend.startswith("blocked_") else backend,
        "stage171_report_sha256": STAGE171_SHA256,
        "stage171_quality": stage171_summary.get("quality"),
        "stage171_recurrent_wet_only_callpath_candidate_rows": int(stage171_summary.get("recurrent_wet_only_callpath_candidate_rows", 0)),
        "stage171_recurrent_renderer_callpath_candidate_rows": int(stage171_summary.get("recurrent_wet_only_renderer_callpath_candidate_rows", 0)),
        "stage171_state_sequence_independently_verified": False,
        "stage171_state_sequence_acceptance_note": "The user reported the stage171 prompts were unclear. Capture windows were technically complete and the 3 recurrent WET-only signatures were consistent with the intended sequence, but stage171 did not independently read back DRY/WET state labels.",
        "process_selection_mode": process_selection_mode,
        "current_pid_exported": False,
        "selected_game_root_exported": False,
        "full_mapping_paths_exported": False,
        "full_command_line_exported": False,
        "environment_values_exported": False,
        "launch_context_written_local_only": context_path.is_file(),
        "launch_context_relative_path": str(LOCAL_LAUNCH_CONTEXT_REL),
        "launch_context_path_exported": False,
        "launch_mode": mode,
        "launch_environment_key_presence": sorted(k for k in CAPTURE_ENV_KEYS if k in env),
        **stack_flags,
        "process_renderer_stack_row_count": len(stack_rows),
        "vulkan_layer_enumeration_ok": bool(loader_info.get("ok")),
        "vulkan_layer_count": int(loader_info.get("layer_count", 0)),
        "vulkan_loader_source": loader_info.get("loader_source", "unavailable"),
        "renderdoc_layer_available": any(r.get("category") == "renderdoc_capture" for r in layer_rows),
        "api_dump_layer_available": any(r.get("category") == "api_dump" for r in layer_rows),
        "renderdoccmd_available": bool(tool_flags.get("renderdoccmd_available")),
        "c_shared_library_build_probe_ok": compiler_ok,
        "c_shared_library_build_probe_reason": compiler_reason,
        "system_vulkan_headers_compile_ok": headers_ok,
        "system_vulkan_headers_compile_reason": headers_reason,
        "recommended_capture_backend": backend,
        "recommended_capture_backend_reason": backend_reason,
        "external_graphics_capture_started": False,
        "external_graphics_capture_file_exported": False,
        "process_memory_written": False,
        "raw_process_memory_exported": False,
        "installed_game_modified": False,
        "pack10_02_baseline_sha256": baseline,
        "pack10_02_unchanged": True,
        "generation10_v2_dependency_used": False,
        "render_resource_binding_confirmed": False,
        "material_binding_confirmed": False,
        "shader_binding_confirmed": False,
        "texture_binding_confirmed": False,
        "wet_transparency_mechanism_confirmed": False,
        "next_action": backend_reason,
    }
    decision_rows = [{
        "recommended_backend": backend,
        "active_vulkan_stack": bool(stack_flags.get("vulkan_loader_mapped") or stack_flags.get("winevulkan_mapped")),
        "renderdoc_layer_available": summary["renderdoc_layer_available"],
        "renderdoccmd_available": summary["renderdoccmd_available"],
        "api_dump_layer_available": summary["api_dump_layer_available"],
        "local_shared_library_build_ok": compiler_ok,
        "vulkan_loader_enumeration_ok": summary["vulkan_layer_enumeration_ok"],
        "capture_started": False,
    }]
    return summary, stack_rows, layer_rows, tool_rows + decision_rows


def build_report(project_root: Path, game_root: Path, *, explicit_pid: int | None = None, interactive: bool = True, report_root: Path | None = None, output_report_root: Path | None = None, create_archive: bool = True) -> tuple[Path | None, dict[str, Any]]:
    summary, stack_rows, layer_rows, mixed_rows = run_audit(project_root, game_root, explicit_pid=explicit_pid, interactive=interactive)
    # mixed_rows contains host tools followed by one decision row; split without exporting machine paths.
    tool_rows = [r for r in mixed_rows if "tool" in r]
    decision_rows = [r for r in mixed_rows if "recommended_backend" in r]
    base = (output_report_root or report_root or (project_root / ".local/reports/quartet_restoration"))
    out = base / REPORT_DIR
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True, exist_ok=True)
    atomic_json(out / "SUMMARY.json", summary)
    write_tsv(out / "PROCESS_RENDERER_STACK.tsv", ["module_family", "module_basename", "mapping_rows", "executable_mapping_rows"], stack_rows)
    write_tsv(out / "VULKAN_LAYER_CAPABILITIES.tsv", ["layer_name", "category", "spec_version", "implementation_version", "description_sha256"], layer_rows)
    write_tsv(out / "HOST_CAPTURE_TOOLS.tsv", ["tool", "available", "version_line_present", "version_line_sha256"], tool_rows)
    write_tsv(out / "CAPTURE_BACKEND_DECISION.tsv", ["recommended_backend", "active_vulkan_stack", "renderdoc_layer_available", "renderdoccmd_available", "api_dump_layer_available", "local_shared_library_build_ok", "vulkan_loader_enumeration_ok", "capture_started"], decision_rows)
    archive: Path | None = None
    if create_archive:
        archive = base / REPORT_NAME
        make_archive(out, archive)
    return archive, summary


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--project-root", type=Path, required=True)
    p.add_argument("--game-root", type=Path, required=True)
    p.add_argument("--pid", type=int)
    p.add_argument("--non-interactive", action="store_true")
    p.add_argument("--root-preflight", action="store_true")
    p.add_argument("--report-root", type=Path)
    p.add_argument("--output-report-root", type=Path)
    p.add_argument("--no-archive", action="store_true")
    return p


def main() -> int:
    a = parser().parse_args()
    project_root = a.project_root.resolve()
    game_root = a.game_root.resolve()
    try:
        if a.root_preflight:
            print(json.dumps(root_preflight(project_root, game_root), sort_keys=True))
            return 0
        archive, summary = build_report(project_root, game_root, explicit_pid=a.pid, interactive=not a.non_interactive, report_root=a.report_root, output_report_root=a.output_report_root, create_archive=not a.no_archive)
        print(json.dumps(summary, sort_keys=True))
        if archive is not None:
            print(str(archive))
        return 0
    except Stage172Error as exc:
        print(f"[stage172] ERROR: {exc}", file=sys.stderr)
        return 1
    except getattr(S170, "Stage170Error", RuntimeError) as exc:
        print(f"[stage172] ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
