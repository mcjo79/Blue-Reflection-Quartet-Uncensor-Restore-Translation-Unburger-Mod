#!/usr/bin/env python3
"""Stage 170: wet-school renderer-interface/vtable provenance trace (read-only).

Stage 169 failed to reacquire the stage-168 WET-only ``blend`` context and
explicitly closed that pointer-token branch.  Stage 170 therefore uses an
independent signal: C/C++ object-interface provenance.  It freshly reacquires
stage-166-class wet-school roots, then inspects only a small bounded qword
neighborhood around the selected current-process root targets.  Candidate
object pointers are classified by whether their first qword behaves like a
vtable and whether vtable entries resolve into executable mappings belonging
to renderer/translation families such as d3d11, dxgi, Vulkan/DXVK/VKD3D.

The DRY2 and WET2 controls compare stable root-relative field offsets plus
normalized module-family/vtable-offset signatures; absolute pointers may move
and are never exported.  This is code/module provenance evidence, not token
matching.  A recurrent WET-only renderer-interface signature is still only a
binding candidate and does not prove alpha/transparency semantics.

No process memory or game file is written.  Evidence exports no PID, no
absolute process address, no raw process memory, no full mapping path and no
arbitrary process string.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import importlib.util
import json
import os
import struct
import subprocess
import sys
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

TOOL_VERSION = "0.1.98"
STAGE = 170
REPORT_DIR = "wet_renderer_interface_vtable_provenance_evidence"
REPORT_NAME = "BR_quartet_restoration_wet_renderer_interface_vtable_provenance_evidence.tar.zst"
STAGE169_REPORT = "BR_quartet_restoration_wet_blend_context_binding_evidence.tar.zst"
STAGE169_SHA256 = "a4d4976e7449fe41d46133e6a81f790cb66489551ee0985eafe59e33088fdf2d"
PACK10_02_BASELINE_SHA256 = "e798f39c3bcdbb11381197bddf9bd3ad8de6ccf5d7c0c78b22613046d47f5302"
ACCESS_DENIED_EXIT = 77

ROOT_SCAN_RADIUS = 1024
VTABLE_ENTRY_COUNT = 6
MIN_EXEC_VTABLE_ENTRIES = 2
MAX_INTERFACE_ROWS_PER_ROOT = 64

RENDERER_FAMILIES = {
    "d3d11", "d3d12", "dxgi", "dxvk", "vkd3d", "vulkan", "winevulkan",
    "opengl", "wined3d",
}

class Stage170Error(RuntimeError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise Stage170Error(message)


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(8 * 1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def write_tsv(path: Path, fields: Sequence[str], rows: Iterable[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(fields), delimiter="\t", lineterminator="\n", extrasaction="ignore")
        w.writeheader()
        for row in rows:
            w.writerow({k: row.get(k, "") for k in fields})


def make_archive(source: Path, output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    tmp = output.with_name(output.name + ".tmp")
    tmp.unlink(missing_ok=True)
    cp = subprocess.run(["tar", "--zstd", "-cf", str(tmp), "-C", str(source.parent), source.name], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    require(cp.returncode == 0, cp.stderr.decode("utf-8", errors="replace").strip() or "archive creation failed")
    os.replace(tmp, output)


def _load_stage169():
    path = Path(__file__).with_name("169_trace_wet_blend_context_binding.py")
    spec = importlib.util.spec_from_file_location("br_restoration_stage169_for170", path)
    require(spec is not None and spec.loader is not None, "cannot load stage169 helper")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


S169 = _load_stage169()
S168 = S169.S168
S167 = S169.S167
S166 = S169.S166
S165 = S169.S165
S164 = S169.S164


def _thread_count(proc_dir: Path) -> int:
    try:
        return sum(1 for p in (proc_dir / "task").iterdir() if p.name.isdigit())
    except Exception:
        return 0


def _candidate_map_stats(pid: int, game_root: Path, *, proc_root: Path = Path("/proc")) -> dict[str, int]:
    """Return bounded process-identity stats without exporting mapping paths."""
    try:
        maps = S164.read_maps(pid, proc_root=proc_root)
    except Exception:
        return {"mapped_game_exe_count": 0, "mapped_game_root_exec_count": 0, "mapped_game_root_count": 0}
    exe_names = S164.game_executable_names(game_root)
    game_exe = 0
    game_root_exec = 0
    game_root_any = 0
    for row in maps:
        path = getattr(row, "path", "") or ""
        if not path or path.startswith("["):
            continue
        under = S164.path_under(path, game_root)
        if under:
            game_root_any += 1
            if "x" in row.perms:
                game_root_exec += 1
        try:
            base = Path(path).name.casefold()
        except Exception:
            base = ""
        if under and base in exe_names and "x" in row.perms:
            game_exe += 1
    return {
        "mapped_game_exe_count": game_exe,
        "mapped_game_root_exec_count": game_root_exec,
        "mapped_game_root_count": game_root_any,
    }


def _collect_game_process_candidates(game_root: Path, *, proc_root: Path = Path("/proc")) -> list[dict[str, Any]]:
    """Collect Stage164-compatible candidates plus stronger selected-root identity signals."""
    exe_names = S164.game_executable_names(game_root)
    root_text = str(S164.safe_resolve(game_root)).casefold()
    excluded_pids: set[int] = {os.getpid()}
    cur = os.getppid()
    for _ in range(8):
        if cur <= 1 or cur in excluded_pids:
            break
        excluded_pids.add(cur)
        try:
            stat_fields = (proc_root / str(cur) / "stat").read_text(errors="replace").split()
            cur = int(stat_fields[3]) if len(stat_fields) > 3 else 1
        except Exception:
            break
    out: list[dict[str, Any]] = []
    for pd in proc_root.iterdir():
        if not pd.name.isdigit():
            continue
        pid = int(pd.name)
        if pid in excluded_pids:
            continue
        cmd = S164._read_proc_bytes(pd / "cmdline")
        if not cmd:
            continue
        cmd_text = cmd.replace(b"\x00", b" ").decode("utf-8", errors="replace").casefold()
        cwd = S164._read_proc_link(pd / "cwd")
        exe = S164._read_proc_link(pd / "exe")
        score = 0
        if cwd and S164.path_under(cwd, game_root):
            score += 120
        if root_text and root_text in cmd_text:
            score += 100
        matched_names = sorted(n for n in exe_names if n and n in cmd_text)
        if matched_names:
            score += 90
        if "blue reflection" in cmd_text:
            score += 60
        if "quartet" in cmd_text:
            score += 30
        rss = S164._rss_bytes(pd)
        if rss >= 256 * 1024 * 1024:
            score += 10
        strong_identity = bool(matched_names) or bool(cwd and S164.path_under(cwd, game_root))
        if not (strong_identity and score >= 60):
            continue
        row = {
            "pid": pid, "score": score, "cmdline": cmd, "cwd": cwd, "exe": exe, "rss": rss,
            "thread_count": _thread_count(pd),
        }
        row.update(_candidate_map_stats(pid, game_root, proc_root=proc_root))
        out.append(row)
    out.sort(key=lambda r: (
        int(r["mapped_game_exe_count"]), int(r["mapped_game_root_exec_count"]), int(r["mapped_game_root_count"]),
        int(r["thread_count"]), int(r["rss"]), int(r["score"]),
    ), reverse=True)
    return out


def choose_game_process_candidate(candidates: Sequence[Mapping[str, Any]], *, interactive: bool = False, input_fn=input) -> tuple[dict[str, Any], str]:
    require(bool(candidates), "could not locate a running Quartet game process; start the game or pass --pid")
    rows = [dict(r) for r in candidates]
    if len(rows) == 1:
        return rows[0], "single_candidate"

    # Strongest signal: the process actually maps the selected installation's game EXE as executable code.
    max_game_exe = max(int(r.get("mapped_game_exe_count", 0)) for r in rows)
    if max_game_exe > 0:
        best = [r for r in rows if int(r.get("mapped_game_exe_count", 0)) == max_game_exe]
        if len(best) == 1:
            return best[0], "selected_root_game_exe_mapping"
        rows = best

    max_root_exec = max(int(r.get("mapped_game_root_exec_count", 0)) for r in rows)
    if max_root_exec > 0:
        best = [r for r in rows if int(r.get("mapped_game_root_exec_count", 0)) == max_root_exec]
        if len(best) == 1:
            return best[0], "selected_root_executable_mapping"
        rows = best

    # Wine helpers can inherit identical command lines.  A uniquely much larger thread count/RSS is a bounded
    # tiebreaker for the main process; otherwise fail closed or ask interactively.
    by_threads = sorted(rows, key=lambda r: int(r.get("thread_count", 0)), reverse=True)
    if len(by_threads) >= 2:
        t0, t1 = int(by_threads[0].get("thread_count", 0)), int(by_threads[1].get("thread_count", 0))
        if t0 >= 4 and t0 >= max(2 * t1, t1 + 8):
            return by_threads[0], "dominant_thread_count"

    by_rss = sorted(rows, key=lambda r: int(r.get("rss", 0)), reverse=True)
    if len(by_rss) >= 2:
        r0, r1 = int(by_rss[0].get("rss", 0)), int(by_rss[1].get("rss", 0))
        if r0 >= 16 * 1024 * 1024 and r0 >= int(1.5 * max(r1, 1)):
            return by_rss[0], "dominant_rss"

    if interactive:
        print("[stage170] Multiple equivalent Wine/Quartet processes remain after selected-root mapping checks:", file=sys.stderr)
        for r in by_rss[:8]:
            print(
                f"  pid={r['pid']} rss={int(r.get('rss',0))//(1024*1024)}MiB threads={r.get('thread_count',0)} "
                f"mapped_game_exe={r.get('mapped_game_exe_count',0)} mapped_root_exec={r.get('mapped_game_root_exec_count',0)}",
                file=sys.stderr,
            )
        allowed = {int(r["pid"]): r for r in rows}
        default_pid = int(by_rss[0]["pid"])
        raw = input_fn(f"[stage170] Enter PID to trace [default {default_pid}]: " ).strip()
        chosen = default_pid if not raw else int(raw)
        require(chosen in allowed, f"PID {chosen} is not one of the selected-root Quartet candidates")
        return allowed[chosen], "interactive_pid_selection"

    desc = ", ".join(
        f"pid={r['pid']} rss={r.get('rss',0)} threads={r.get('thread_count',0)} mapped_game_exe={r.get('mapped_game_exe_count',0)}"
        for r in by_rss[:5]
    )
    raise Stage170Error(f"ambiguous Quartet process candidates after selected-root mapping checks ({desc}); rerun with --pid")


def discover_game_process_stage170(game_root: Path, *, explicit_pid: int | None = None, interactive: bool = False, proc_root: Path = Path("/proc")) -> tuple[dict[str, Any], str]:
    if explicit_pid is not None:
        return S164.discover_game_process(game_root, proc_root=proc_root, explicit_pid=explicit_pid), "explicit_pid"
    return choose_game_process_candidate(_collect_game_process_candidates(game_root, proc_root=proc_root), interactive=interactive)


def _archive_member_bytes(archive: Path, suffix: str) -> bytes:
    cp = subprocess.run(["tar", "--zstd", "-tf", str(archive)], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    require(cp.returncode == 0, cp.stderr.decode("utf-8", errors="replace").strip() or "cannot list stage169 archive")
    names = cp.stdout.decode("utf-8", errors="replace").splitlines()
    matches = [n for n in names if n.endswith("/" + suffix) or n == suffix]
    require(len(matches) == 1, f"stage169 archive expected exactly one {suffix}, found {len(matches)}")
    cp = subprocess.run(["tar", "--zstd", "-xOf", str(archive), matches[0]], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    require(cp.returncode == 0, cp.stderr.decode("utf-8", errors="replace").strip() or f"cannot read {suffix} from stage169 archive")
    return cp.stdout


def verify_stage169_contract(project_root: Path) -> dict[str, Any]:
    archive = project_root / ".local/reports/quartet_restoration" / STAGE169_REPORT
    require(archive.is_file(), f"missing canonical stage169 report: {archive}")
    actual = sha256_file(archive)
    require(actual == STAGE169_SHA256, f"stage169 report SHA-256 drift: {actual}")
    summary = json.loads(_archive_member_bytes(archive, "SUMMARY.json").decode("utf-8"))
    require(summary.get("stage") == 169, "stage169 SUMMARY stage drift")
    require(summary.get("fresh_process_anchor_reacquisition_performed") is True, "stage169 did not freshly reacquire anchors")
    require(summary.get("stage168_historical_pid_reused") is False, "stage169 reused historical PID")
    require(summary.get("stage168_historical_absolute_addresses_reused") is False, "stage169 reused historical absolute addresses")
    require(summary.get("pack10_02_unchanged") is True, "stage169 did not preserve PACK10_02")
    require(summary.get("quality") == "no_fresh_recurrent_wet_only_blend_context_reacquired", "stage169 no longer closes the blend-token branch")
    require(int(summary.get("recurrent_wet_only_blend_context_rows", -1)) == 0, "stage169 unexpectedly has recurrent blend contexts")
    require(summary.get("wet_transparency_mechanism_confirmed") is False, "stage169 unexpectedly claims transparency")
    return summary


def verify_prerequisites(project_root: Path, game_root: Path) -> tuple[dict[str, Any], str]:
    summary = verify_stage169_contract(project_root)
    pak = game_root / "Data/PACK10_02.PAK"
    require(pak.is_file(), f"missing Quartet PACK10_02: {pak}")
    baseline = sha256_file(pak)
    require(baseline == PACK10_02_BASELINE_SHA256, f"PACK10_02 is not exact baseline: {baseline}")
    return summary, baseline


def module_family(mapping: Any, game_root: Path) -> str:
    """Return a coarse non-path module family safe for evidence export."""
    cls, base, _ph = S164.normalized_mapping_path(mapping, game_root)
    low = base.casefold()
    if cls == "game" and low.endswith(".exe"):
        return "game_executable"
    if "d3d11" in low:
        return "d3d11"
    if "d3d12" in low:
        return "d3d12"
    if "dxgi" in low:
        return "dxgi"
    if "dxvk" in low:
        return "dxvk"
    if "vkd3d" in low:
        return "vkd3d"
    if "winevulkan" in low:
        return "winevulkan"
    if "vulkan" in low:
        return "vulkan"
    if "wined3d" in low:
        return "wined3d"
    if "opengl" in low or "libgl" in low:
        return "opengl"
    if cls == "wine_or_translation":
        return "wine_translation_other"
    if cls == "device_or_gpu":
        return "gpu_driver_or_device"
    if cls == "system_or_other":
        return "system_other"
    if cls == "anonymous":
        return "anonymous"
    return cls


def _read_exact(reader: Any, mapping: Any, address: int, size: int) -> bytes:
    if mapping is None or "r" not in mapping.perms or address < mapping.start or address + size > mapping.end:
        return b""
    try:
        data = reader.read(address, size)
    except (OSError, PermissionError):
        return b""
    return data if len(data) == size else b""


def classify_vtable_candidate(reader: Any, maps: Sequence[Any], game_root: Path, child_pointer: int) -> dict[str, Any] | None:
    """Classify child_pointer as a probable C++/COM interface object.

    The object's first qword is treated as a possible vtable pointer.  A vtable
    is accepted only when at least MIN_EXEC_VTABLE_ENTRIES of its first entries
    resolve into executable mappings.  No symbol/string evidence is used.
    """
    cm = S166.mapping_for_address(maps, child_pointer)
    if cm is None or "r" not in cm.perms:
        return None
    head = _read_exact(reader, cm, child_pointer, 8)
    if not head:
        return None
    vtable = struct.unpack("<Q", head)[0]
    vm = S166.mapping_for_address(maps, vtable)
    if vm is None or "r" not in vm.perms:
        return None
    raw = _read_exact(reader, vm, vtable, VTABLE_ENTRY_COUNT * 8)
    if not raw:
        return None
    exec_targets: list[tuple[str, int]] = []
    for i in range(VTABLE_ENTRY_COUNT):
        fn = struct.unpack_from("<Q", raw, i * 8)[0]
        fm = S166.mapping_for_address(maps, fn)
        if fm is None or "x" not in fm.perms:
            continue
        exec_targets.append((module_family(fm, game_root), fn - fm.start))
    if len(exec_targets) < MIN_EXEC_VTABLE_ENTRIES:
        return None
    families = sorted({x[0] for x in exec_targets})
    primary = families[0] if len(families) == 1 else "mixed:" + "+".join(families)
    renderer_supported = any((fam in RENDERER_FAMILIES) or any(r in fam for r in RENDERER_FAMILIES) for fam in families)
    # Relative vtable offset is safe and useful within this same-process module mapping.
    return {
        "child_mapping_class": S164.mapping_class(cm, game_root),
        "vtable_mapping_class": S164.mapping_class(vm, game_root),
        "vtable_module_family": module_family(vm, game_root),
        "vtable_mapping_relative_offset": vtable - vm.start,
        "executable_entry_count": len(exec_targets),
        "function_module_families": ";".join(families),
        "primary_function_module_family": primary,
        "renderer_interface_supported": renderer_supported,
        "vtable_signature_sha256": hashlib.sha256(";".join(f"{fam}:{off:x}" for fam, off in exec_targets).encode("ascii")).hexdigest(),
    }


def trace_interface_neighborhood(reader: Any, maps: Sequence[Any], game_root: Path, root_pointer: int, *, root_id: str, state: str) -> list[dict[str, Any]]:
    rm = S166.mapping_for_address(maps, root_pointer)
    if rm is None or "r" not in rm.perms:
        return []
    rows: list[dict[str, Any]] = []
    seen: set[tuple[int, str]] = set()
    for rel in range(-ROOT_SCAN_RADIUS, ROOT_SCAN_RADIUS + 1, 8):
        field = root_pointer + rel
        if field < rm.start or field + 8 > rm.end:
            continue
        raw = _read_exact(reader, rm, field, 8)
        if not raw:
            continue
        child = struct.unpack("<Q", raw)[0]
        sig = classify_vtable_candidate(reader, maps, game_root, child)
        if sig is None:
            continue
        key = (rel, sig["vtable_signature_sha256"])
        if key in seen:
            continue
        seen.add(key)
        rows.append({
            "root_id": root_id,
            "state": state,
            "root_field_relative_offset": rel,
            **sig,
            "absolute_pointer_exported": False,
        })
    rows.sort(key=lambda r: (not bool(r["renderer_interface_supported"]), abs(int(r["root_field_relative_offset"])), int(r["root_field_relative_offset"])))
    return rows[:MAX_INTERFACE_ROWS_PER_ROOT]


def recurrent_interface_candidates(wet1: Sequence[Mapping[str, Any]], dry2: Sequence[Mapping[str, Any]], wet2: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    def key(r: Mapping[str, Any]) -> tuple[str, int, str, int, str]:
        return (
            str(r.get("root_id", "")),
            int(r.get("root_field_relative_offset", 0)),
            str(r.get("vtable_module_family", "")),
            int(r.get("vtable_mapping_relative_offset", 0)),
            str(r.get("vtable_signature_sha256", "")),
        )
    w1 = {key(r): r for r in wet1}
    d2 = {key(r): r for r in dry2}
    w2 = {key(r): r for r in wet2}
    out: list[dict[str, Any]] = []
    for k in sorted(set(w1) & set(w2)):
        if k in d2:
            continue
        a, b = w1[k], w2[k]
        out.append({
            "candidate_id": f"iface_{len(out)+1:03d}",
            "root_id": k[0],
            "root_field_relative_offset": k[1],
            "vtable_module_family": k[2],
            "vtable_mapping_relative_offset": k[3],
            "vtable_signature_sha256": k[4],
            "function_module_families": a.get("function_module_families", ""),
            "executable_entry_count": a.get("executable_entry_count", ""),
            "renderer_interface_supported": bool(a.get("renderer_interface_supported")),
            "same_signature_wet1_wet2": True,
            "dry2_same_signature_present": False,
            "render_resource_binding_confirmed": False,
            "material_binding_confirmed": False,
            "shader_binding_confirmed": False,
            "texture_binding_confirmed": False,
            "transparency_semantics_confirmed": False,
        })
    return out


def _root_pointer_from_blob(blob: bytes, site_addr: int, rel: int) -> int | None:
    return S168.pointer_at_field(blob, site_addr, rel)


def _public_root(root: Mapping[str, Any], rank: int, status: str, exact: bool) -> dict[str, Any]:
    return {
        "root_id": root.get("root_id", ""),
        "anchor_descriptor": root.get("anchor_descriptor", ""),
        "relative_offset": root.get("relative_offset", ""),
        "selected_rank": rank,
        "wet1_direct_asset_tokens": ";".join(root.get("direct_asset_tokens", [])),
        "wet1_direct_technical_terms": ";".join(root.get("direct_technical_terms", [])),
        "wet2_root_status": status,
        "wet1_wet2_exact_pointer_recurrence": exact,
        "absolute_pointer_exported": False,
    }


def run_trace(project_root: Path, game_root: Path, *, interactive: bool = True, initial_ready: bool = False, explicit_pid: int | None = None) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    stage169_summary, baseline = verify_prerequisites(project_root, game_root)
    proc, process_selection_mode = discover_game_process_stage170(game_root, explicit_pid=explicit_pid, interactive=interactive)
    pid = int(proc["pid"])
    print(f"[stage170] Process selected ({process_selection_mode}); PID is terminal-only and is not exported to evidence.", file=sys.stderr)

    def ensure_alive() -> None:
        require((Path("/proc") / str(pid)).is_dir(), "game process exited during stage170 trace")

    if interactive:
        print("\n[stage170] NEW PROCESS: no stage169 PID or absolute address is reused.")
        if initial_ready:
            print("[stage170] Launcher already confirmed Hinako / native School Uniform / DRY. Capturing DRY1 now.")
        else:
            print("[stage170] Prepare Hinako / native School Uniform / DRY. This trace follows object/vtable provenance, not renderer-token strings.")
            input("[stage170] Press Enter to capture DRY1 discovery baseline... ")

    ensure_alive()
    dry_maps1 = S164.read_maps(pid)
    with S164.ProcessMemoryReader(pid) as reader:
        dry_model_rows, _ = S165.scan_wet_model_token(reader, dry_maps1, game_root, "stage170_dry1")

    if interactive:
        print("[stage170] Use native Change Wetness: DRY -> WET.")
        input("[stage170] Press Enter when WET is fully visible... ")
    ensure_alive()
    wet_maps1 = S164.read_maps(pid)
    with S164.ProcessMemoryReader(pid) as reader:
        wet_model_rows, _ = S165.scan_wet_model_token(reader, wet_maps1, game_root, "stage170_wet1")
        dynamic = S165.dynamic_wet_occurrences(dry_model_rows, wet_model_rows)
        pointer_rows, _ = S165.scan_pointers_to_dynamic_wet(reader, wet_maps1, game_root, dynamic)
        sites = S166.fresh_site_contracts(pointer_rows)
        require(sites, "fresh stage166-class anchors were not reacquired; no historical address will be substituted")
        wet1_blobs, _ = S166.capture_site_state(reader, wet_maps1, game_root, sites, "stage170_wet1")
        roots = S168.direct_wet_model_root_candidates(reader, wet_maps1, game_root, sites, wet1_blobs)
        require(roots, "no current-process wet-school model root candidate found")
        dedup: dict[int, dict[str, Any]] = {}
        for r in roots:
            dedup.setdefault(int(r["pointer"]), r)
        selected, rank = S169.select_best_wet_roots(list(dedup.values()))
        require(selected and rank is not None, "no bounded wet-school root class available for vtable provenance trace")
        selected = selected[:4]
        wet1_rows: list[dict[str, Any]] = []
        for idx, root in enumerate(selected, 1):
            root["root_id"] = f"iface_root_{idx:02d}"
            wet1_rows.extend(trace_interface_neighborhood(reader, wet_maps1, game_root, int(root["pointer"]), root_id=root["root_id"], state="wet1"))

    if interactive:
        print(f"[stage170] Reacquired {len(sites)} anchor(s); selected {len(selected)} wet-school root(s) at rank {rank}. Toggle WET -> DRY.")
        input("[stage170] Press Enter when DRY is fully visible... ")
    ensure_alive()
    dry_maps2 = S164.read_maps(pid)
    dry2_rows: list[dict[str, Any]] = []
    with S164.ProcessMemoryReader(pid) as reader:
        dry2_blobs, _ = S166.capture_site_state(reader, dry_maps2, game_root, sites, "stage170_dry2")
        for root in selected:
            site_addr = int(root["site_address"])
            rel = int(root["relative_offset"])
            ptr = _root_pointer_from_blob(dry2_blobs[site_addr], site_addr, rel)
            if ptr is None:
                continue
            dry2_rows.extend(trace_interface_neighborhood(reader, dry_maps2, game_root, int(ptr), root_id=root["root_id"], state="dry2"))

    if interactive:
        print("[stage170] DRY interface provenance captured. Toggle DRY -> WET once more.")
        input("[stage170] Press Enter when WET is fully visible again... ")
    ensure_alive()
    wet_maps2 = S164.read_maps(pid)
    wet2_rows: list[dict[str, Any]] = []
    root_public: list[dict[str, Any]] = []
    with S164.ProcessMemoryReader(pid) as reader:
        wet2_blobs, _ = S166.capture_site_state(reader, wet_maps2, game_root, sites, "stage170_wet2")
        recurrent_root_count = 0
        for root in selected:
            site_addr = int(root["site_address"])
            rel = int(root["relative_offset"])
            ptr = _root_pointer_from_blob(wet2_blobs[site_addr], site_addr, rel)
            status, _assets, _terms = S168.classify_wet2_root_target(reader, wet_maps2, game_root, ptr)
            exact = bool(ptr is not None and int(ptr) == int(root["pointer"]))
            if status == "recurrent_wet_school" and ptr is not None:
                recurrent_root_count += 1
                wet2_rows.extend(trace_interface_neighborhood(reader, wet_maps2, game_root, int(ptr), root_id=root["root_id"], state="wet2"))
            root_public.append(_public_root(root, int(rank), status, exact))

    candidates = recurrent_interface_candidates(wet1_rows, dry2_rows, wet2_rows)
    baseline_after = sha256_file(game_root / "Data/PACK10_02.PAK")
    require(baseline_after == baseline == PACK10_02_BASELINE_SHA256, "PACK10_02 changed during read-only stage170 trace")
    stats = {
        "stage169_quality": stage169_summary.get("quality", ""),
        "fresh_dynamic_wet_model_rows": len(dynamic),
        "fresh_pointer_reference_rows": len(pointer_rows),
        "fresh_anchor_site_rows": len(sites),
        "selected_wet_school_root_rows": len(selected),
        "selected_root_rank": int(rank),
        "wet2_recurrent_selected_root_rows": recurrent_root_count,
        "wet1_interface_observation_rows": len(wet1_rows),
        "dry2_interface_observation_rows": len(dry2_rows),
        "wet2_interface_observation_rows": len(wet2_rows),
        "recurrent_wet_only_interface_candidate_rows": len(candidates),
        "recurrent_wet_only_renderer_interface_candidate_rows": sum(1 for r in candidates if r["renderer_interface_supported"]),
        "baseline_before": baseline,
        "baseline_after": baseline_after,
        "process_selection_mode": process_selection_mode,
    }
    observations = wet1_rows + dry2_rows + wet2_rows
    return stats, root_public, observations, candidates


def build_report(project_root: Path, game_root: Path, *, interactive: bool = True, initial_ready: bool = False, explicit_pid: int | None = None, report_root: Path | None = None, output_report_root: Path | None = None, create_archive: bool = True) -> tuple[Path | None, dict[str, Any]]:
    stats, roots, observations, candidates = run_trace(project_root, game_root, interactive=interactive, initial_ready=initial_ready, explicit_pid=explicit_pid)
    report_parent = output_report_root or report_root or (project_root / ".local/reports/quartet_restoration")
    outdir = report_parent / REPORT_DIR
    if outdir.exists():
        import shutil
        shutil.rmtree(outdir)
    outdir.mkdir(parents=True, exist_ok=True)

    renderer_count = stats["recurrent_wet_only_renderer_interface_candidate_rows"]
    if renderer_count:
        quality = "fresh_recurrent_wet_only_renderer_interface_provenance_candidates_observed"
        next_action = "Inspect only the recurrent renderer-interface candidate field(s) with an independently grounded API/call-site correlation. Do not infer transparency from module provenance alone."
    elif stats["recurrent_wet_only_interface_candidate_rows"]:
        quality = "recurrent_wet_only_object_interface_candidates_without_renderer_module_provenance"
        next_action = "No renderer module provenance was established. Do not broaden pointer/token scans; use an independently grounded API/call-path capture if continuing runtime binding work."
    else:
        quality = "no_recurrent_wet_only_object_interface_provenance_candidate"
        next_action = "Close the object-neighborhood memory route. Do not broaden pointer scans; move to an independently grounded API/call-path capture at native Change Wetness."

    summary = {
        "type": "br_quartet_restoration_wet_renderer_interface_vtable_provenance_evidence_summary",
        "format_version": 1,
        "tool_version": TOOL_VERSION,
        "stage": STAGE,
        "status": "fresh_process_wet_renderer_interface_vtable_provenance_trace_complete_read_only",
        "quality": quality,
        "capture_sequence": "fresh DRY1 discovery -> native WET1 wet-school roots + bounded object/vtable provenance -> native DRY2 control -> native WET2 recurrence",
        "stage169_report_sha256": STAGE169_SHA256,
        "stage169_quality": stats["stage169_quality"],
        "stage169_blend_token_branch_repeated": False,
        "fresh_process_anchor_reacquisition_performed": True,
        "stage169_historical_pid_reused": False,
        "stage169_historical_absolute_addresses_reused": False,
        "fresh_dynamic_wet_model_rows": stats["fresh_dynamic_wet_model_rows"],
        "fresh_pointer_reference_rows": stats["fresh_pointer_reference_rows"],
        "fresh_anchor_site_rows": stats["fresh_anchor_site_rows"],
        "selected_wet_school_root_rows": stats["selected_wet_school_root_rows"],
        "selected_root_rank": stats["selected_root_rank"],
        "wet2_recurrent_selected_root_rows": stats["wet2_recurrent_selected_root_rows"],
        "interface_observation_rows": len(observations),
        "recurrent_wet_only_interface_candidate_rows": stats["recurrent_wet_only_interface_candidate_rows"],
        "recurrent_wet_only_renderer_interface_candidate_rows": renderer_count,
        "object_vtable_provenance_used_as_independent_signal": True,
        "token_semantics_used_for_interface_classification": False,
        "numeric_or_pointer_field_semantics_inferred": False,
        "render_resource_binding_confirmed": False,
        "material_binding_confirmed": False,
        "shader_binding_confirmed": False,
        "texture_binding_confirmed": False,
        "wet_transparency_mechanism_confirmed": False,
        "pack10_02_baseline_sha256": PACK10_02_BASELINE_SHA256,
        "pack10_02_unchanged": stats["baseline_before"] == stats["baseline_after"] == PACK10_02_BASELINE_SHA256,
        "process_memory_written": False,
        "installed_game_modified": False,
        "generation10_v2_dependency_used": False,
        "process_selection_mode": stats["process_selection_mode"],
        "current_pid_exported": False,
        "absolute_process_addresses_exported": False,
        "raw_process_memory_exported": False,
        "full_mapping_paths_exported": False,
        "next_action": next_action,
    }

    write_tsv(outdir / "SELECTED_WET_SCHOOL_ROOTS.tsv", [
        "root_id", "anchor_descriptor", "relative_offset", "selected_rank", "wet1_direct_asset_tokens",
        "wet1_direct_technical_terms", "wet2_root_status", "wet1_wet2_exact_pointer_recurrence", "absolute_pointer_exported",
    ], roots)
    write_tsv(outdir / "INTERFACE_VTABLE_OBSERVATIONS.tsv", [
        "root_id", "state", "root_field_relative_offset", "child_mapping_class", "vtable_mapping_class",
        "vtable_module_family", "vtable_mapping_relative_offset", "executable_entry_count", "function_module_families",
        "primary_function_module_family", "renderer_interface_supported", "vtable_signature_sha256", "absolute_pointer_exported",
    ], observations)
    write_tsv(outdir / "RECURRENT_WET_ONLY_INTERFACE_CANDIDATES.tsv", [
        "candidate_id", "root_id", "root_field_relative_offset", "vtable_module_family", "vtable_mapping_relative_offset",
        "vtable_signature_sha256", "function_module_families", "executable_entry_count", "renderer_interface_supported",
        "same_signature_wet1_wet2", "dry2_same_signature_present", "render_resource_binding_confirmed",
        "material_binding_confirmed", "shader_binding_confirmed", "texture_binding_confirmed", "transparency_semantics_confirmed",
    ], candidates)
    (outdir / "SUMMARY.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    archive = report_parent / REPORT_NAME
    if create_archive:
        make_archive(outdir, archive)
        return archive, summary
    return None, summary


def probe(project_root: Path, game_root: Path, *, explicit_pid: int | None = None) -> dict[str, Any]:
    verify_prerequisites(project_root, game_root)
    proc, mode = discover_game_process_stage170(game_root, explicit_pid=explicit_pid, interactive=False)
    maps = S164.read_maps(int(proc["pid"]))
    ok, reason = S164._probe_memory_access(int(proc["pid"]), maps, game_root)
    return {"fresh_process_reacquisition": True, "historical_absolute_addresses_reused": False, "memory_readable": ok, "reason": reason, "process_selection_mode": mode}


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--project-root", type=Path, default=Path(__file__).resolve().parents[2])
    ap.add_argument("--game-root", type=Path)
    ap.add_argument("--pid", type=int, help="optional terminal-only explicit process override; never exported to evidence")
    ap.add_argument("--report-root", type=Path)
    ap.add_argument("--output-report-root", type=Path)
    ap.add_argument("--probe", action="store_true")
    ap.add_argument("--root-preflight", action="store_true", help="verify only the selected Quartet root and PACK10_02 baseline; do not inspect a process")
    ap.add_argument("--non-interactive", action="store_true")
    ap.add_argument("--initial-ready", action="store_true")
    ap.add_argument("--no-archive", action="store_true")
    return ap.parse_args(argv)


def _load_paths(project_root: Path) -> Path:
    env = os.environ.get("BR1_QUARTET_ROOT", "")
    if env:
        return Path(env)
    local = project_root / ".local/paths.sh"
    if local.is_file():
        cp = subprocess.run(["bash", "-lc", f"set -a; source {json.dumps(str(local))}; printf '%s' \"${{BR1_QUARTET_ROOT:-}}\""], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if cp.returncode == 0 and cp.stdout:
            return Path(cp.stdout.decode("utf-8", errors="replace"))
    raise Stage170Error("Quartet root unavailable; pass --game-root, set BR1_QUARTET_ROOT, or configure .local/paths.sh")


def resolve_game_root(project_root: Path, explicit_game_root: Path | None = None) -> tuple[Path, str]:
    # Deliberate precedence for parallel installations/workstreams:
    # explicit CLI > process-local environment > ignored project-local config.
    if explicit_game_root is not None:
        return explicit_game_root.resolve(), "explicit_cli"
    env = os.environ.get("BR1_QUARTET_ROOT", "")
    if env:
        return Path(env).resolve(), "environment"
    return _load_paths(project_root).resolve(), "local_paths"


def root_preflight(project_root: Path, game_root: Path, source: str) -> dict[str, Any]:
    verify_stage169_contract(project_root)
    pak = game_root / "Data/PACK10_02.PAK"
    require(pak.is_file(), f"missing Quartet PACK10_02 under selected game root: {game_root}")
    actual = sha256_file(pak)
    require(
        actual == PACK10_02_BASELINE_SHA256,
        f"selected Quartet root is not Restoration baseline: root={game_root} PACK10_02={actual} expected={PACK10_02_BASELINE_SHA256}",
    )
    return {
        "root_selection_source": source,
        "pack10_02_sha256": actual,
        "pack10_02_exact_baseline": True,
        "game_files_modified": False,
    }


def main(argv: Sequence[str] | None = None) -> int:
    a = parse_args(argv)
    project_root = a.project_root.resolve()
    game_root, root_source = resolve_game_root(project_root, a.game_root)
    try:
        print(f"[stage170] Resolved Quartet root ({root_source}): {game_root}", file=sys.stderr)
        if a.root_preflight:
            print(json.dumps(root_preflight(project_root, game_root, root_source), sort_keys=True))
            return 0
        if a.probe:
            print(json.dumps(probe(project_root, game_root, explicit_pid=a.pid), sort_keys=True))
            return 0
        archive, summary = build_report(project_root, game_root, interactive=not a.non_interactive, initial_ready=a.initial_ready, explicit_pid=a.pid, report_root=a.report_root, output_report_root=a.output_report_root, create_archive=not a.no_archive)
        print(json.dumps(summary, sort_keys=True))
        if archive is not None:
            print(archive)
        return 0
    except (PermissionError, OSError) as exc:
        if getattr(exc, "errno", None) in {1, 13}:
            print(f"[stage170] process-memory access denied: {exc}", file=sys.stderr)
            return ACCESS_DENIED_EXIT
        raise
    except Stage170Error as exc:
        print(f"[stage170] ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
