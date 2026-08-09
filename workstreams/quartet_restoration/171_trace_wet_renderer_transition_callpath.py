#!/usr/bin/env python3
"""Stage 171: read-only renderer transition call-path sampling around Change Wetness.

Stages 167-170 exhausted bounded object/pointer neighborhoods without obtaining
renderer-module provenance. Stage 171 therefore changes the evidence class. It
uses Linux perf_event_open software CPU-clock sampling attached read-only to the
selected Quartet process threads during three short native Change Wetness
transition windows: DRY->WET1, WET1->DRY2, DRY2->WET2.

Evidence stores only normalized module-family / mapping-relative callchain
signatures and aggregate counts. It exports no PID, no absolute process address,
no full mapping path, no raw perf ring data and no process memory. No process or
game file write is performed.

A recurrent renderer-associated callchain seen in both wet transitions but not
in the dry transition is candidate execution-path evidence only. It does not by
itself prove material, shader, texture, alpha or transparency semantics.
"""
from __future__ import annotations

import argparse
import csv
import ctypes
import errno
import fcntl
import hashlib
import importlib.util
import json
import mmap
import os
import platform
import struct
import subprocess
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

TOOL_VERSION = "0.1.99"
STAGE = 171
REPORT_DIR = "wet_renderer_transition_callpath_evidence"
REPORT_NAME = "BR_quartet_restoration_wet_renderer_transition_callpath_evidence.tar.zst"
STAGE170_REPORT = "BR_quartet_restoration_wet_renderer_interface_vtable_provenance_evidence.tar.zst"
STAGE170_SHA256 = "6f73ad48d129e1215f110219bc908d02e0e37c1e9f417652cbd86ea88eb088d7"
PACK10_02_BASELINE_SHA256 = "e798f39c3bcdbb11381197bddf9bd3ad8de6ccf5d7c0c78b22613046d47f5302"
ACCESS_DENIED_EXIT = 77

CAPTURE_SECONDS = 8.0
SAMPLE_PERIOD_NS = 5_000_000
MAX_THREADS = 96
RING_DATA_PAGES = 8
MAX_CALLCHAIN_FRAMES = 24
MIN_WET_SAMPLES_PER_CAPTURE = 2

PERF_TYPE_SOFTWARE = 1
PERF_COUNT_SW_CPU_CLOCK = 0
PERF_SAMPLE_IP = 1 << 0
PERF_SAMPLE_TID = 1 << 1
PERF_SAMPLE_TIME = 1 << 2
PERF_SAMPLE_CALLCHAIN = 1 << 5
PERF_RECORD_LOST = 2
PERF_RECORD_SAMPLE = 9
PERF_FLAG_FD_CLOEXEC = 1 << 3
PERF_EVENT_IOC_ENABLE = 0x2400
PERF_EVENT_IOC_DISABLE = 0x2401
PERF_EVENT_IOC_RESET = 0x2403
PERF_CONTEXT_MAX = (1 << 64) - 4096

RENDERER_FAMILIES = {
    "d3d11", "d3d12", "dxgi", "dxvk", "vkd3d", "vulkan", "winevulkan",
    "opengl", "wined3d",
}


class Stage171Error(RuntimeError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise Stage171Error(message)


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(8 * 1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


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


def _load_stage170():
    path = Path(__file__).with_name("170_trace_wet_renderer_interface_vtable_provenance.py")
    spec = importlib.util.spec_from_file_location("br_restoration_stage170_for171", path)
    require(spec is not None and spec.loader is not None, "cannot load stage170 helper")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


S170 = _load_stage170()
S164 = S170.S164


class PerfEventAttr(ctypes.Structure):
    _fields_ = [
        ("type", ctypes.c_uint32),
        ("size", ctypes.c_uint32),
        ("config", ctypes.c_uint64),
        ("sample_period", ctypes.c_uint64),
        ("sample_type", ctypes.c_uint64),
        ("read_format", ctypes.c_uint64),
        ("flags", ctypes.c_uint64),
        ("wakeup_events", ctypes.c_uint32),
        ("bp_type", ctypes.c_uint32),
        ("config1", ctypes.c_uint64),
        ("config2", ctypes.c_uint64),
        ("branch_sample_type", ctypes.c_uint64),
        ("sample_regs_user", ctypes.c_uint64),
        ("sample_stack_user", ctypes.c_uint32),
        ("clockid", ctypes.c_int32),
        ("sample_regs_intr", ctypes.c_uint64),
        ("aux_watermark", ctypes.c_uint32),
        ("sample_max_stack", ctypes.c_uint16),
        ("reserved2", ctypes.c_uint16),
    ]


def perf_event_open_number() -> int:
    machine = platform.machine().lower()
    if machine in {"x86_64", "amd64"}:
        return 298
    raise Stage171Error(f"unsupported architecture for built-in perf_event_open sampler: {machine}")


def make_perf_attr() -> PerfEventAttr:
    attr = PerfEventAttr()
    attr.type = PERF_TYPE_SOFTWARE
    attr.size = ctypes.sizeof(PerfEventAttr)
    attr.config = PERF_COUNT_SW_CPU_CLOCK
    attr.sample_period = SAMPLE_PERIOD_NS
    attr.sample_type = PERF_SAMPLE_IP | PERF_SAMPLE_TID | PERF_SAMPLE_TIME | PERF_SAMPLE_CALLCHAIN
    # disabled, exclude_kernel, exclude_hv, exclude_idle, exclude_callchain_kernel
    attr.flags = (1 << 0) | (1 << 5) | (1 << 6) | (1 << 7) | (1 << 21)
    attr.wakeup_events = 1
    attr.sample_max_stack = MAX_CALLCHAIN_FRAMES
    return attr


def open_perf_fd(tid: int) -> int:
    libc = ctypes.CDLL(None, use_errno=True)
    attr = make_perf_attr()
    nr = perf_event_open_number()
    fd = libc.syscall(nr, ctypes.byref(attr), ctypes.c_int(tid), ctypes.c_int(-1), ctypes.c_int(-1), ctypes.c_ulong(PERF_FLAG_FD_CLOEXEC))
    if fd < 0:
        e = ctypes.get_errno()
        raise OSError(e, os.strerror(e))
    return int(fd)


def probe_perf_access(tid: int) -> tuple[bool, str]:
    try:
        fd = open_perf_fd(tid)
    except OSError as exc:
        if exc.errno in {errno.EPERM, errno.EACCES}:
            return False, "permission_denied"
        return False, f"open_failed_errno_{exc.errno}"
    else:
        os.close(fd)
        return True, "ok"


def _ring_read(mm: mmap.mmap, data_offset: int, data_size: int, absolute_pos: int, size: int) -> bytes:
    pos = absolute_pos % data_size
    first = min(size, data_size - pos)
    start = data_offset + pos
    out = mm[start:start + first]
    if first < size:
        out += mm[data_offset:data_offset + (size - first)]
    return bytes(out)


def parse_perf_sample_payload(payload: bytes) -> dict[str, Any]:
    require(len(payload) >= 32, "short perf sample payload")
    off = 0
    ip = struct.unpack_from("<Q", payload, off)[0]; off += 8
    pid, tid = struct.unpack_from("<II", payload, off); off += 8
    ts = struct.unpack_from("<Q", payload, off)[0]; off += 8
    nr = struct.unpack_from("<Q", payload, off)[0]; off += 8
    require(nr <= 4096, "implausible perf callchain length")
    need = off + int(nr) * 8
    require(need <= len(payload), "truncated perf callchain")
    ips = list(struct.unpack_from(f"<{int(nr)}Q", payload, off)) if nr else []
    return {"ip": ip, "pid": pid, "tid": tid, "time": ts, "callchain": ips}


def drain_perf_ring(mm: mmap.mmap) -> tuple[list[dict[str, Any]], int]:
    # perf_event_mmap_page places ring metadata at fixed offsets in the first 4 KiB header.
    head = struct.unpack_from("<Q", mm, 1024)[0]
    tail = struct.unpack_from("<Q", mm, 1032)[0]
    data_offset = struct.unpack_from("<Q", mm, 1040)[0] or os.sysconf("SC_PAGE_SIZE")
    data_size = struct.unpack_from("<Q", mm, 1048)[0] or (len(mm) - data_offset)
    require(data_offset + data_size <= len(mm), "invalid perf ring metadata")
    samples: list[dict[str, Any]] = []
    lost = 0
    pos = tail
    while pos < head:
        hdr = _ring_read(mm, int(data_offset), int(data_size), int(pos), 8)
        typ, misc, size = struct.unpack("<IHH", hdr)
        require(size >= 8 and size <= data_size, "invalid perf record size")
        rec = _ring_read(mm, int(data_offset), int(data_size), int(pos), int(size))
        payload = rec[8:]
        if typ == PERF_RECORD_SAMPLE:
            try:
                samples.append(parse_perf_sample_payload(payload))
            except Stage171Error:
                pass
        elif typ == PERF_RECORD_LOST and len(payload) >= 16:
            lost += int(struct.unpack_from("<Q", payload, 8)[0])
        pos += size
    struct.pack_into("<Q", mm, 1032, head)
    return samples, lost


class ThreadSampler:
    def __init__(self, tid: int):
        self.tid = tid
        self.fd = open_perf_fd(tid)
        self.mm = mmap.mmap(self.fd, (1 + RING_DATA_PAGES) * os.sysconf("SC_PAGE_SIZE"), flags=mmap.MAP_SHARED, prot=mmap.PROT_READ | mmap.PROT_WRITE)

    def enable(self) -> None:
        fcntl.ioctl(self.fd, PERF_EVENT_IOC_RESET, 0)
        fcntl.ioctl(self.fd, PERF_EVENT_IOC_ENABLE, 0)

    def disable_and_read(self) -> tuple[list[dict[str, Any]], int]:
        fcntl.ioctl(self.fd, PERF_EVENT_IOC_DISABLE, 0)
        return drain_perf_ring(self.mm)

    def close(self) -> None:
        try:
            self.mm.close()
        finally:
            os.close(self.fd)


def list_threads(pid: int, proc_root: Path = Path("/proc")) -> list[int]:
    task = proc_root / str(pid) / "task"
    tids = sorted(int(p.name) for p in task.iterdir() if p.name.isdigit())
    require(bool(tids), "selected game process has no visible threads")
    return tids[:MAX_THREADS]


def classify_ip(ip: int, maps: Sequence[Any], game_root: Path) -> tuple[str, int] | None:
    if not ip or ip >= PERF_CONTEXT_MAX:
        return None
    for row in maps:
        if int(row.start) <= ip < int(row.end):
            fam = S170.module_family(row, game_root)
            rel = ip - int(row.start)
            return fam, rel
    return None


def normalize_callchain(sample: Mapping[str, Any], maps: Sequence[Any], game_root: Path) -> dict[str, Any] | None:
    raw = [int(sample.get("ip", 0))] + [int(x) for x in sample.get("callchain", [])]
    frames: list[tuple[str, int]] = []
    for ip in raw:
        c = classify_ip(ip, maps, game_root)
        if c is None:
            continue
        fam, rel = c
        frame = (fam, (int(rel) // 16) * 16)
        if not frames or frames[-1] != frame:
            frames.append(frame)
        if len(frames) >= MAX_CALLCHAIN_FRAMES:
            break
    if not frames:
        return None
    exact_text = ";".join(f"{fam}+{rel:x}" for fam, rel in frames)
    fams: list[str] = []
    for fam, _ in frames:
        if not fams or fams[-1] != fam:
            fams.append(fam)
    family_text = ";".join(fams)
    renderer = sorted({fam for fams0 in [fams] for fam in fams0 if fam in RENDERER_FAMILIES})
    return {
        "exact_signature_sha256": sha256_text(exact_text),
        "family_signature_sha256": sha256_text(family_text),
        "module_families": family_text,
        "renderer_families": ";".join(renderer),
        "renderer_associated": bool(renderer),
        "frame_count": len(frames),
    }


def aggregate_capture(samples: Sequence[Mapping[str, Any]], maps: Sequence[Any], game_root: Path) -> tuple[Counter[str], Counter[str], dict[str, dict[str, Any]]]:
    exact: Counter[str] = Counter()
    family: Counter[str] = Counter()
    meta: dict[str, dict[str, Any]] = {}
    for sample in samples:
        row = normalize_callchain(sample, maps, game_root)
        if not row:
            continue
        es = row["exact_signature_sha256"]
        fs = row["family_signature_sha256"]
        exact[es] += 1
        family[fs] += 1
        meta.setdefault(es, row)
        meta.setdefault(fs, row)
    return exact, family, meta


def recurrent_candidates(captures: Mapping[str, tuple[Counter[str], Counter[str], dict[str, dict[str, Any]]]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for kind, idx in (("exact", 0), ("family", 1)):
        w1 = captures["wet1"][idx]
        d2 = captures["dry2"][idx]
        w2 = captures["wet2"][idx]
        meta = captures["wet1"][2]
        for sig in sorted(set(w1) & set(w2)):
            if w1[sig] < MIN_WET_SAMPLES_PER_CAPTURE or w2[sig] < MIN_WET_SAMPLES_PER_CAPTURE:
                continue
            if d2.get(sig, 0):
                continue
            m = meta.get(sig, {})
            rows.append({
                "candidate_id": f"call_{len(rows)+1:03d}",
                "signature_kind": kind,
                "signature_sha256": sig,
                "wet1_samples": int(w1[sig]),
                "dry2_samples": int(d2.get(sig, 0)),
                "wet2_samples": int(w2[sig]),
                "module_families": m.get("module_families", ""),
                "renderer_families": m.get("renderer_families", ""),
                "renderer_associated": bool(m.get("renderer_associated", False)),
                "frame_count": int(m.get("frame_count", 0)),
                "api_or_call_path_binding_confirmed": False,
                "transparency_semantics_confirmed": False,
            })
    rows.sort(key=lambda r: (not bool(r["renderer_associated"]), r["signature_kind"] != "exact", -(r["wet1_samples"] + r["wet2_samples"]), r["signature_sha256"]))
    for i, row in enumerate(rows, 1):
        row["candidate_id"] = f"call_{i:03d}"
    return rows


def root_preflight(project_root: Path, game_root: Path) -> dict[str, Any]:
    pack = game_root / "Data" / "PACK10_02.PAK"
    require(pack.is_file(), f"missing PACK10_02 under selected game root: {game_root}")
    got = sha256_file(pack)
    require(got == PACK10_02_BASELINE_SHA256, f"PACK10_02 is not exact Restoration baseline under selected game root: {got}")
    prior = project_root / ".local" / "reports" / "quartet_restoration" / STAGE170_REPORT
    require(prior.is_file(), f"missing required stage170 report: {prior}")
    require(sha256_file(prior) == STAGE170_SHA256, "stage170 report SHA-256 drift")
    return {"pack10_02_sha256": got, "stage170_sha256": STAGE170_SHA256}


def select_process(game_root: Path, *, pid_override: int | None, interactive: bool) -> tuple[int, str]:
    if pid_override is not None:
        row = S170.validate_explicit_pid(pid_override, game_root)
        return int(row["pid"]), "explicit_pid"
    candidates = S170._collect_game_process_candidates(game_root)
    row, mode = S170.choose_game_process_candidate(candidates, interactive=interactive)
    return int(row["pid"]), mode


def capture_window(pid: int, game_root: Path, label: str, *, duration: float = CAPTURE_SECONDS) -> dict[str, Any]:
    maps = S164.read_maps(pid)
    tids = list_threads(pid)
    samplers: list[ThreadSampler] = []
    open_errors = 0
    try:
        for tid in tids:
            try:
                samplers.append(ThreadSampler(tid))
            except OSError:
                open_errors += 1
        require(bool(samplers), "perf_event_open could not attach to any selected game thread")
        for s in samplers:
            s.enable()
        started = time.monotonic()
        while time.monotonic() - started < duration:
            time.sleep(0.05)
        samples: list[dict[str, Any]] = []
        lost = 0
        for s in samplers:
            ss, ll = s.disable_and_read()
            samples.extend(ss)
            lost += ll
    finally:
        for s in samplers:
            try:
                s.close()
            except Exception:
                pass
    exact, family, meta = aggregate_capture(samples, maps, game_root)
    return {
        "label": label,
        "thread_rows_visible": len(tids),
        "thread_samplers_opened": len(samplers),
        "thread_sampler_open_errors": open_errors,
        "raw_sample_rows_consumed": len(samples),
        "lost_sample_rows": lost,
        "normalized_exact_signature_rows": len(exact),
        "normalized_family_signature_rows": len(family),
        "aggregates": (exact, family, meta),
    }


def _prompt_transition(label: str, instruction: str, duration: float) -> None:
    print()
    print(f"[stage171] {label}: {instruction}")
    print(f"[stage171] After pressing Enter, immediately switch to the game and perform exactly ONE Change Wetness toggle during the next {duration:.0f} seconds.")
    print("[stage171] Do not change costume/character or perform another toggle during that window.")
    input(f"[stage171] Press Enter to start the {label} sampling window... ")


def run_trace(project_root: Path, game_root: Path, *, interactive: bool, initial_ready: bool, pid_override: int | None, duration: float = CAPTURE_SECONDS) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]:
    root_preflight(project_root, game_root)
    pid, process_mode = select_process(game_root, pid_override=pid_override, interactive=interactive)
    ok, reason = probe_perf_access(pid)
    if not ok:
        if reason == "permission_denied":
            raise PermissionError(errno.EPERM, "perf_event_open permission denied")
        raise Stage171Error(f"perf_event_open capability probe failed: {reason}")

    if interactive and not initial_ready:
        input("[stage171] Prepare Hinako in native School Uniform / DRY, then press Enter... ")

    captures: dict[str, dict[str, Any]] = {}
    sequence = [
        ("wet1", "Starting from DRY, toggle DRY -> WET once."),
        ("dry2", "Starting from WET, toggle WET -> DRY once."),
        ("wet2", "Starting from DRY, toggle DRY -> WET once more."),
    ]
    for label, instruction in sequence:
        if interactive:
            _prompt_transition(label.upper(), instruction, duration)
        captures[label] = capture_window(pid, game_root, label, duration=duration)
        print(f"[stage171] {label.upper()} captured: {captures[label]['raw_sample_rows_consumed']} samples across {captures[label]['thread_samplers_opened']} thread samplers.")

    agg = {k: v["aggregates"] for k, v in captures.items()}
    candidates = recurrent_candidates(agg)
    capture_rows = []
    for label in ("wet1", "dry2", "wet2"):
        row = dict(captures[label])
        row.pop("aggregates", None)
        capture_rows.append(row)
    stats = {
        "process_selection_mode": process_mode,
        "candidate_rows": len(candidates),
        "renderer_candidate_rows": sum(bool(r["renderer_associated"]) for r in candidates),
        "capture_sample_rows": sum(int(r["raw_sample_rows_consumed"]) for r in capture_rows),
        "lost_sample_rows": sum(int(r["lost_sample_rows"]) for r in capture_rows),
    }
    return stats, capture_rows, candidates


def build_report(project_root: Path, game_root: Path, *, interactive: bool = True, initial_ready: bool = False, pid_override: int | None = None, report_root: Path | None = None, output_report_root: Path | None = None, create_archive: bool = True, duration: float = CAPTURE_SECONDS) -> tuple[Path | None, dict[str, Any]]:
    project_root = project_root.resolve()
    game_root = game_root.resolve()
    pre = root_preflight(project_root, game_root)
    stats, captures, candidates = run_trace(project_root, game_root, interactive=interactive, initial_ready=initial_ready, pid_override=pid_override, duration=duration)
    base = output_report_root or report_root or (project_root / ".local" / "reports" / "quartet_restoration")
    out = Path(base) / REPORT_DIR
    if out.exists():
        import shutil
        shutil.rmtree(out)
    out.mkdir(parents=True, exist_ok=True)

    write_tsv(out / "CAPTURE_WINDOWS.tsv", [
        "label", "thread_rows_visible", "thread_samplers_opened", "thread_sampler_open_errors", "raw_sample_rows_consumed", "lost_sample_rows", "normalized_exact_signature_rows", "normalized_family_signature_rows",
    ], captures)
    write_tsv(out / "RECURRENT_WET_ONLY_CALLPATH_CANDIDATES.tsv", [
        "candidate_id", "signature_kind", "signature_sha256", "wet1_samples", "dry2_samples", "wet2_samples", "module_families", "renderer_families", "renderer_associated", "frame_count", "api_or_call_path_binding_confirmed", "transparency_semantics_confirmed",
    ], candidates)

    renderer_rows = sum(bool(r["renderer_associated"]) for r in candidates)
    if renderer_rows:
        quality = "recurrent_wet_only_renderer_associated_callpath_candidates_observed"
        next_action = "Review only recurrent renderer-associated wet-transition callpath candidates. They are execution-path candidates, not transparency semantics; independently bind any candidate to an active D3D/Vulkan resource operation before considering a write." 
    else:
        quality = "no_recurrent_wet_only_renderer_associated_callpath_candidate"
        next_action = "No recurrent renderer-associated wet-transition callpath candidate was observed. Do not broaden pointer/object scans. Reassess whether the remaining transparency difference is asset-side or requires an explicit external graphics API capture layer before further runtime instrumentation."

    summary = {
        "type": "br_quartet_restoration_wet_renderer_transition_callpath_evidence_summary",
        "format_version": 1,
        "tool_version": TOOL_VERSION,
        "stage": STAGE,
        "status": "fresh_process_wet_renderer_transition_callpath_trace_complete_read_only",
        "quality": quality,
        "capture_sequence": "native DRY->WET1 sampled transition -> native WET1->DRY2 sampled transition control -> native DRY2->WET2 sampled transition",
        "sampling_backend": "linux_perf_event_open_software_cpu_clock_callchain",
        "capture_seconds_each": duration,
        "sample_period_ns": SAMPLE_PERIOD_NS,
        "max_threads": MAX_THREADS,
        "capture_sample_rows": stats["capture_sample_rows"],
        "lost_sample_rows": stats["lost_sample_rows"],
        "recurrent_wet_only_callpath_candidate_rows": stats["candidate_rows"],
        "recurrent_wet_only_renderer_callpath_candidate_rows": renderer_rows,
        "process_selection_mode": stats["process_selection_mode"],
        "stage170_report_sha256": pre["stage170_sha256"],
        "stage170_quality": "recurrent_wet_only_object_interface_candidates_without_renderer_module_provenance",
        "pack10_02_baseline_sha256": pre["pack10_02_sha256"],
        "pack10_02_unchanged": sha256_file(game_root / "Data" / "PACK10_02.PAK") == PACK10_02_BASELINE_SHA256,
        "fresh_process_capture_required": True,
        "historical_pid_reused": False,
        "historical_absolute_addresses_reused": False,
        "current_pid_exported": False,
        "absolute_process_addresses_exported": False,
        "full_mapping_paths_exported": False,
        "raw_perf_ring_exported": False,
        "raw_process_memory_exported": False,
        "process_memory_written": False,
        "installed_game_modified": False,
        "generation10_v2_dependency_used": False,
        "api_or_call_path_binding_confirmed": False,
        "render_resource_binding_confirmed": False,
        "material_binding_confirmed": False,
        "shader_binding_confirmed": False,
        "texture_binding_confirmed": False,
        "wet_transparency_mechanism_confirmed": False,
        "numeric_or_pointer_field_semantics_inferred": False,
        "next_action": next_action,
    }
    atomic_json(out / "SUMMARY.json", summary)

    archive = None
    if create_archive:
        archive_root = Path(report_root or (project_root / ".local" / "reports" / "quartet_restoration"))
        archive = archive_root / REPORT_NAME
        make_archive(out, archive)
    return archive, summary


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--project-root", type=Path, required=True)
    ap.add_argument("--game-root", type=Path, required=True)
    ap.add_argument("--pid", type=int)
    ap.add_argument("--initial-ready", action="store_true")
    ap.add_argument("--non-interactive", action="store_true")
    ap.add_argument("--root-preflight", action="store_true")
    ap.add_argument("--probe-access", action="store_true")
    ap.add_argument("--report-root", type=Path)
    ap.add_argument("--output-report-root", type=Path)
    ap.add_argument("--no-archive", action="store_true")
    ap.add_argument("--capture-seconds", type=float, default=CAPTURE_SECONDS)
    a = ap.parse_args(argv)
    require(a.capture_seconds > 0.1 and a.capture_seconds <= 30.0, "capture seconds out of bounded range")
    pre = root_preflight(a.project_root, a.game_root)
    if a.root_preflight:
        print(json.dumps({"root_preflight": True, "pack10_02_sha256": pre["pack10_02_sha256"], "stage170_sha256": pre["stage170_sha256"]}, sort_keys=True))
        return 0
    if a.probe_access:
        pid, mode = select_process(a.game_root.resolve(), pid_override=a.pid, interactive=False)
        ok, reason = probe_perf_access(pid)
        print(json.dumps({"perf_event_readable": ok, "reason": reason, "process_selection_mode": mode}, sort_keys=True))
        return 0 if ok else (ACCESS_DENIED_EXIT if reason == "permission_denied" else 1)
    try:
        archive, summary = build_report(a.project_root, a.game_root, interactive=not a.non_interactive, initial_ready=a.initial_ready, pid_override=a.pid, report_root=a.report_root, output_report_root=a.output_report_root, create_archive=not a.no_archive, duration=a.capture_seconds)
    except PermissionError as exc:
        print(f"[stage171] perf_event_open permission denied: {exc}", file=sys.stderr)
        return ACCESS_DENIED_EXIT
    print(json.dumps(summary, sort_keys=True))
    if archive:
        print(archive)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
