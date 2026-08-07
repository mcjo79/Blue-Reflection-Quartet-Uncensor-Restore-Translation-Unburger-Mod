#!/usr/bin/env python3
"""Stage 164: read-only native dry->wet process-state trace.

Stage 163 found no bounded structured numeric selector anchor for pc00.  This
stage therefore observes the live Quartet process at the native Change Wetness
boundary without writing process memory or game files.  It searches readable
process memory for exact pc00 school dry/wet asset tokens, records normalized
mapping residency and a deliberately bounded exact-address pointer-reference sample, and compares
DRY/WET snapshots from the same PID.

No raw process-memory bytes, full command lines or absolute mapping paths are
exported.  Reported context is hash-only.  The process may continue running
while a snapshot is collected; this is an observational trace, not a coherent
core dump and not proof of transparency semantics.
"""
from __future__ import annotations

import argparse
import csv
import ctypes
import errno
import hashlib
import json
import os
import re
import shutil
import struct
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence, NamedTuple

TOOL_VERSION = "0.1.86"
REPORT_DIR = "native_wetness_process_state_trace_evidence"
REPORT_NAME = "BR_quartet_restoration_native_wetness_process_state_trace_evidence.tar.zst"
STAGE163_REPORT = "BR_quartet_restoration_wetness_transition_structured_selector_binding_evidence.tar.zst"
STAGE163_SHA256 = "e51b9b69cf5896ca242471d3df1676020a999dcd42a786087747c0db06296202"
PACK10_02_BASELINE_SHA256 = "e798f39c3bcdbb11381197bddf9bd3ad8de6ccf5d7c0c78b22613046d47f5302"
MAX_SCAN_BYTES = 3 * 1024 * 1024 * 1024
MAX_POINTER_SCAN_BYTES = 128 * 1024 * 1024
MAX_POINTER_TARGETS = 64
POINTER_PROGRESS_BYTES = 32 * 1024 * 1024
CHUNK_SIZE = 8 * 1024 * 1024
CONTEXT_RADIUS = 128
PAGE_SIZE = 4096
ACCESS_DENIED_EXIT = 77


class Stage164Error(RuntimeError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise Stage164Error(message)


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(8 * 1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def hash_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8", errors="replace")).hexdigest()


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
    cp = subprocess.run(
        ["tar", "--zstd", "-cf", str(tmp), "-C", str(source.parent), source.name],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    require(cp.returncode == 0, cp.stderr.decode("utf-8", errors="replace").strip() or "archive creation failed")
    os.replace(tmp, output)


class TokenSpec(NamedTuple):
    label: str
    text: str
    state: str
    primary: bool = False
    exact_dry_boundary: bool = False


TOKEN_SPECS: tuple[TokenSpec, ...] = (
    TokenSpec("pc00_school_dry", "pc00_scl", "dry", True, True),
    TokenSpec("pc00_school_wet", "pc00_scl_w", "wet", True, False),
    TokenSpec("pc00_school_wet_g1t", "pc00_scl_w.g1t", "wet", False, False),
    TokenSpec("pc00_school_wet_elixir", "pc00_scl_w.elixir.gz", "wet", False, False),
    TokenSpec("pc00_school_wet_model", "PC00_Scl_W_P_School_Wet.g1m", "wet", False, False),
)


class MapRow(NamedTuple):
    start: int
    end: int
    perms: str
    offset: int
    dev: str
    inode: int
    path: str

    @property
    def size(self) -> int:
        return self.end - self.start


MAP_RE = re.compile(
    r"^([0-9a-fA-F]+)-([0-9a-fA-F]+)\s+([rwxps-]{4})\s+([0-9a-fA-F]+)\s+(\S+)\s+(\d+)\s*(.*)$"
)


def parse_maps_text(text: str) -> list[MapRow]:
    out: list[MapRow] = []
    for line in text.splitlines():
        m = MAP_RE.match(line)
        if not m:
            continue
        out.append(MapRow(
            start=int(m.group(1), 16),
            end=int(m.group(2), 16),
            perms=m.group(3),
            offset=int(m.group(4), 16),
            dev=m.group(5),
            inode=int(m.group(6)),
            path=m.group(7).strip(),
        ))
    return out


def safe_resolve(path: Path) -> Path:
    try:
        return path.resolve(strict=False)
    except OSError:
        return path.absolute()


def path_under(path: str, root: Path) -> bool:
    if not path or path.startswith("["):
        return False
    try:
        p = safe_resolve(Path(path))
        r = safe_resolve(root)
        return p == r or r in p.parents
    except Exception:
        return False


def mapping_class(row: MapRow, game_root: Path) -> str:
    p = row.path
    low = p.casefold()
    if path_under(p, game_root):
        return "game"
    if p in ("[heap]", "[stack]") or not p or p.startswith("[anon:"):
        return "anonymous"
    if p.startswith("["):
        return "kernel_pseudo"
    if low.startswith("/dev/") or "dri" in low or "nvidia" in low or "amdgpu" in low:
        return "device_or_gpu"
    if any(x in low for x in ("/wine", "wine64", "wine-preloader", "/proton", "dxvk", "vkd3d")):
        return "wine_or_translation"
    return "system_or_other"


def normalized_mapping_path(row: MapRow, game_root: Path) -> tuple[str, str, str]:
    cls = mapping_class(row, game_root)
    if not row.path:
        return cls, "", ""
    if row.path.startswith("["):
        return cls, row.path, hash_text(row.path)
    return cls, Path(row.path).name, hash_text(row.path)


def mapping_key(row: MapRow) -> str:
    # Same-process comparison key. Absolute virtual addresses are intentionally
    # retained only as a hash in the evidence-facing key.
    raw = f"{row.start:x}:{row.end:x}:{row.perms}:{row.offset:x}:{row.inode}:{row.path}"
    return hash_text(raw)[:24]


def map_evidence_row(index: int, row: MapRow, game_root: Path) -> dict[str, Any]:
    cls, base, ph = normalized_mapping_path(row, game_root)
    return {
        "mapping_index": index,
        "mapping_key": mapping_key(row),
        "mapping_class": cls,
        "permissions": row.perms,
        "size": row.size,
        "file_offset": row.offset,
        "inode": row.inode,
        "path_basename": base,
        "path_sha256": ph,
    }


def game_executable_names(game_root: Path) -> set[str]:
    names: set[str] = set()
    try:
        for p in game_root.iterdir():
            if p.is_file() and p.suffix.casefold() == ".exe":
                names.add(p.name.casefold())
        data = game_root / "Data"
        if data.is_dir():
            for p in data.iterdir():
                if p.is_file() and p.suffix.casefold() == ".exe":
                    names.add(p.name.casefold())
    except OSError:
        pass
    return names


def _read_proc_bytes(path: Path) -> bytes:
    try:
        return path.read_bytes()
    except (OSError, PermissionError):
        return b""


def _read_proc_link(path: Path) -> str:
    try:
        return os.readlink(path)
    except (OSError, PermissionError):
        return ""


def _rss_bytes(proc_dir: Path) -> int:
    try:
        parts = (proc_dir / "statm").read_text().split()
        return int(parts[1]) * os.sysconf("SC_PAGE_SIZE") if len(parts) >= 2 else 0
    except Exception:
        return 0


def discover_game_process(game_root: Path, *, proc_root: Path = Path("/proc"), explicit_pid: int | None = None) -> dict[str, Any]:
    exe_names = game_executable_names(game_root)
    if explicit_pid is not None:
        pd = proc_root / str(explicit_pid)
        require(pd.is_dir(), f"PID {explicit_pid} not found")
        return {
            "pid": explicit_pid,
            "score": 9999,
            "cmdline": _read_proc_bytes(pd / "cmdline"),
            "cwd": _read_proc_link(pd / "cwd"),
            "exe": _read_proc_link(pd / "exe"),
            "rss": _rss_bytes(pd),
        }

    candidates: list[dict[str, Any]] = []
    root_text = str(safe_resolve(game_root)).casefold()
    excluded_pids: set[int] = {os.getpid()}
    # Exclude this collector's launcher/sudo/shell ancestry. Their command lines
    # necessarily contain --game-root and must never be mistaken for the game.
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
    for pd in proc_root.iterdir():
        if not pd.name.isdigit():
            continue
        pid = int(pd.name)
        if pid in excluded_pids:
            continue
        cmd = _read_proc_bytes(pd / "cmdline")
        if not cmd:
            continue
        cmd_text = cmd.replace(b"\x00", b" ").decode("utf-8", errors="replace").casefold()
        cwd = _read_proc_link(pd / "cwd")
        exe = _read_proc_link(pd / "exe")
        score = 0
        reasons: list[str] = []
        if cwd and path_under(cwd, game_root):
            score += 120; reasons.append("cwd_under_game_root")
        if root_text and root_text in cmd_text:
            score += 100; reasons.append("game_root_in_cmdline")
        matched_names = sorted(n for n in exe_names if n and n in cmd_text)
        if matched_names:
            score += 90; reasons.append("game_exe_name_in_cmdline")
        if "blue reflection" in cmd_text:
            score += 60; reasons.append("blue_reflection_in_cmdline")
        if "quartet" in cmd_text:
            score += 30; reasons.append("quartet_in_cmdline")
        rss = _rss_bytes(pd)
        if rss >= 256 * 1024 * 1024:
            score += 10
        # A path passed as an argument to an unrelated helper is not process
        # identity. Require either the actual game EXE basename in cmdline or a
        # process whose working directory is inside the game root.
        strong_identity = bool(matched_names) or bool(cwd and path_under(cwd, game_root))
        if strong_identity and score >= 60:
            candidates.append({"pid": pid, "score": score, "cmdline": cmd, "cwd": cwd, "exe": exe, "rss": rss, "reasons": reasons})
    require(candidates, "could not locate a running Quartet game process; start the game or pass --pid")
    candidates.sort(key=lambda r: (r["score"], r["rss"]), reverse=True)
    if len(candidates) > 1 and candidates[0]["score"] == candidates[1]["score"] and abs(candidates[0]["rss"] - candidates[1]["rss"]) < 64 * 1024 * 1024:
        desc = ", ".join(f"pid={r['pid']} score={r['score']} rss={r['rss']}" for r in candidates[:5])
        raise Stage164Error(f"ambiguous Quartet process candidates ({desc}); rerun with --pid")
    return candidates[0]


class IOVec(ctypes.Structure):
    _fields_ = [("iov_base", ctypes.c_void_p), ("iov_len", ctypes.c_size_t)]


class ProcessMemoryReader:
    def __init__(self, pid: int):
        self.pid = int(pid)
        self.libc = ctypes.CDLL(None, use_errno=True)
        self.fn = getattr(self.libc, "process_vm_readv", None)
        self.mem_fd: int | None = None
        if self.fn is not None:
            self.fn.argtypes = [ctypes.c_int, ctypes.POINTER(IOVec), ctypes.c_ulong, ctypes.POINTER(IOVec), ctypes.c_ulong, ctypes.c_ulong]
            self.fn.restype = ctypes.c_ssize_t

    def close(self) -> None:
        if self.mem_fd is not None:
            try:
                os.close(self.mem_fd)
            except OSError:
                pass
            self.mem_fd = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        self.close()

    def read(self, address: int, size: int) -> bytes:
        if size <= 0:
            return b""
        if self.fn is not None:
            buf = ctypes.create_string_buffer(size)
            local = IOVec(ctypes.cast(buf, ctypes.c_void_p), size)
            remote = IOVec(ctypes.c_void_p(address), size)
            ctypes.set_errno(0)
            n = self.fn(self.pid, ctypes.byref(local), 1, ctypes.byref(remote), 1, 0)
            if n >= 0:
                return bytes(buf.raw[:n])
            err = ctypes.get_errno()
            if err not in (errno.ENOSYS, errno.EPERM, errno.EACCES):
                raise OSError(err, os.strerror(err))
        if self.mem_fd is None:
            self.mem_fd = os.open(f"/proc/{self.pid}/mem", os.O_RDONLY | getattr(os, "O_CLOEXEC", 0))
        return os.pread(self.mem_fd, size, address)


def read_maps(pid: int, *, proc_root: Path = Path("/proc")) -> list[MapRow]:
    p = proc_root / str(pid) / "maps"
    require(p.is_file(), f"cannot read process maps for PID {pid}")
    return parse_maps_text(p.read_text(encoding="utf-8", errors="replace"))


def select_scan_mappings(maps: Sequence[MapRow], game_root: Path, max_bytes: int = MAX_SCAN_BYTES) -> list[MapRow]:
    eligible = [m for m in maps if "r" in m.perms and m.size > 0 and mapping_class(m, game_root) not in {"device_or_gpu", "kernel_pseudo"}]
    def priority(m: MapRow) -> tuple[int, int]:
        cls = mapping_class(m, game_root)
        if m.path == "[heap]":
            p = 0
        elif cls == "anonymous" and "w" in m.perms:
            p = 1
        elif cls == "game":
            p = 2
        elif "w" in m.perms:
            p = 3
        elif cls == "wine_or_translation":
            p = 4
        else:
            p = 5
        return p, m.size
    eligible.sort(key=priority)
    out: list[MapRow] = []
    total = 0
    for m in eligible:
        if total >= max_bytes:
            break
        if m.size > 1024 * 1024 * 1024 and mapping_class(m, game_root) not in {"anonymous", "game"}:
            continue
        out.append(m)
        total += m.size
    return out


def select_pointer_mappings(maps: Sequence[MapRow], game_root: Path, max_bytes: int = MAX_POINTER_SCAN_BYTES) -> list[MapRow]:
    eligible = [m for m in maps if "r" in m.perms and "w" in m.perms and m.size > 0 and mapping_class(m, game_root) not in {"device_or_gpu", "kernel_pseudo"}]
    eligible.sort(key=lambda m: (0 if m.path == "[heap]" else 1 if mapping_class(m, game_root) == "anonymous" else 2, m.size))
    out: list[MapRow] = []
    total = 0
    for m in eligible:
        if total >= max_bytes:
            break
        out.append(m); total += m.size
    return out


def _token_variants(spec: TokenSpec) -> list[tuple[str, bytes]]:
    return [("ascii", spec.text.encode("ascii")), ("utf16le", spec.text.encode("utf-16le"))]


def _dry_boundary_ok(data: bytes, at: int, pat: bytes, encoding: str) -> bool:
    end = at + len(pat)
    if encoding == "ascii":
        return data[end:end+2].lower() != b"_w"
    return data[end:end+4].lower() != "_w".encode("utf-16le")


def _containing_string_base(data: bytes, at: int, encoding: str, max_back: int = 192) -> int:
    if encoding == "ascii":
        pos = at
        floor = max(0, at - max_back)
        while pos > floor and 0x20 <= data[pos - 1] <= 0x7e:
            pos -= 1
        return pos
    pos = at
    floor = max(0, at - max_back * 2)
    # UTF-16LE ASCII-like path/name: printable low byte + zero high byte.
    while pos - 2 >= floor:
        lo, hi = data[pos - 2], data[pos - 1]
        if hi != 0 or not (0x20 <= lo <= 0x7e):
            break
        pos -= 2
    return pos


def _containing_string_hash(data: bytes, base: int, encoding: str, max_len: int = 384) -> str:
    end = base
    if encoding == "ascii":
        limit = min(len(data), base + max_len)
        while end < limit and 0x20 <= data[end] <= 0x7e:
            end += 1
    else:
        limit = min(len(data), base + max_len * 2)
        while end + 1 < limit and data[end + 1] == 0 and 0x20 <= data[end] <= 0x7e:
            end += 2
    return sha256_bytes(data[base:end])


def scan_buffer_for_tokens(data: bytes, base_address: int, mapping: MapRow, map_index: int, game_root: Path) -> list[dict[str, Any]]:
    cls, basename, ph = normalized_mapping_path(mapping, game_root)
    rows: list[dict[str, Any]] = []
    for spec in TOKEN_SPECS:
        for enc, pat in _token_variants(spec):
            start = 0
            while True:
                at = data.find(pat, start)
                if at < 0:
                    break
                start = at + 1
                if spec.exact_dry_boundary and not _dry_boundary_ok(data, at, pat, enc):
                    continue
                address = base_address + at
                string_base_at = _containing_string_base(data, at, enc)
                string_base_address = base_address + string_base_at
                lo = max(0, at - CONTEXT_RADIUS)
                hi = min(len(data), at + len(pat) + CONTEXT_RADIUS)
                page_lo = max(0, (at // PAGE_SIZE) * PAGE_SIZE)
                page_hi = min(len(data), page_lo + PAGE_SIZE)
                rows.append({
                    "token_label": spec.label,
                    "token_text": spec.text,
                    "token_state": spec.state,
                    "primary_token": spec.primary,
                    "encoding": enc,
                    "address": address,
                    "address_hex": f"0x{address:x}",
                    "string_base_address": string_base_address,
                    "string_base_address_hex": f"0x{string_base_address:x}",
                    "string_base_delta": address - string_base_address,
                    "containing_string_sha256": _containing_string_hash(data, string_base_at, enc),
                    "mapping_index": map_index,
                    "mapping_key": mapping_key(mapping),
                    "mapping_class": cls,
                    "mapping_permissions": mapping.perms,
                    "mapping_path_basename": basename,
                    "mapping_path_sha256": ph,
                    "mapping_relative_offset": address - mapping.start,
                    "context_sha256": sha256_bytes(data[lo:hi]),
                    "page_sha256": sha256_bytes(data[page_lo:page_hi]),
                })
    return rows


def read_mapping_chunks(reader: ProcessMemoryReader, mapping: MapRow, *, chunk_size: int = CHUNK_SIZE, overlap: int = 128, max_bytes: int | None = None):
    pos = mapping.start
    scan_end = mapping.end if max_bytes is None else min(mapping.end, mapping.start + max(0, int(max_bytes)))
    tail = b""
    tail_base = pos
    while pos < scan_end:
        want = min(chunk_size, scan_end - pos)
        try:
            block = reader.read(pos, want)
        except (OSError, PermissionError):
            pos += want
            tail = b""
            tail_base = pos
            continue
        if not block:
            pos += want
            tail = b""
            tail_base = pos
            continue
        if tail:
            combined = tail + block
            combined_base = tail_base
        else:
            combined = block
            combined_base = pos
        yield combined_base, combined, len(block)
        keep = min(overlap, len(block))
        tail = block[-keep:]
        tail_base = pos + len(block) - keep
        pos += want


def scan_tokens(reader: ProcessMemoryReader, maps: Sequence[MapRow], game_root: Path, *, label: str, max_bytes: int = MAX_SCAN_BYTES) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    selected = select_scan_mappings(maps, game_root, max_bytes)
    map_index_by_key = {mapping_key(m): i for i, m in enumerate(maps)}
    seen: set[tuple[str, str, int]] = set()
    rows: list[dict[str, Any]] = []
    scanned = 0
    read_failures = 0
    last_progress = 0
    overlap = max(len(s.text.encode("utf-16le")) for s in TOKEN_SPECS) + CONTEXT_RADIUS * 2
    planned = min(sum(m.size for m in selected), max_bytes)
    print(f"[stage164] {label}: token scan planned {planned / (1024**2):.1f} MiB across {len(selected)} mappings", flush=True)
    for m in selected:
        if scanned >= max_bytes:
            break
        before = scanned
        remaining = max_bytes - scanned
        for base, data, nread in read_mapping_chunks(reader, m, overlap=overlap, max_bytes=remaining):
            scanned += nread
            found = scan_buffer_for_tokens(data, base, m, map_index_by_key[mapping_key(m)], game_root)
            for r in found:
                key = (r["token_label"], r["encoding"], r["address"])
                if key not in seen:
                    seen.add(key); rows.append(r)
            if scanned - last_progress >= 256 * 1024 * 1024:
                pct = (100.0 * scanned / planned) if planned else 100.0
                print(f"[stage164] {label}: token scan {scanned / (1024**2):.0f}/{planned / (1024**2):.0f} MiB ({min(pct,100):.1f}%)", flush=True)
                last_progress = scanned
        if scanned == before:
            read_failures += 1
    return rows, {
        "selected_mapping_rows": len(selected),
        "planned_scan_bytes": planned,
        "bytes_read": scanned,
        "mapping_read_failure_rows": read_failures,
    }


def _pointer_target_priority(ref: Mapping[str, Any], kind: str) -> tuple[int, int, int, int]:
    """Prefer dynamic/writable string instances, then game-backed instances.

    This is only a bounded sampling policy for observational pointer candidates;
    absence of a hit is never interpreted as absence of a runtime reference.
    """
    writable = "w" in str(ref.get("mapping_permissions", ""))
    cls = str(ref.get("mapping_class", ""))
    if writable and cls == "anonymous":
        tier = 0
    elif writable:
        tier = 1
    elif cls == "game":
        tier = 2
    else:
        tier = 3
    # Pointers to a containing string base are more conventional than pointers
    # into the middle of an asset token, but retain both forms when budget allows.
    kind_tier = 0 if kind == "containing_string_base" else 1
    state_tier = 0 if ref.get("token_state") == "dry" else 1
    return tier, kind_tier, state_tier, int(ref.get("mapping_relative_offset", 0))


def select_pointer_targets(token_rows: Sequence[Mapping[str, Any]], max_targets: int = MAX_POINTER_TARGETS) -> tuple[dict[bytes, list[tuple[Mapping[str, Any], str, int]]], dict[str, Any]]:
    candidates: dict[bytes, list[tuple[Mapping[str, Any], str, int]]] = {}
    priorities: dict[bytes, tuple[int, int, int, int]] = {}
    states: dict[bytes, set[str]] = {}
    for r in token_rows:
        if not r.get("primary_token"):
            continue
        for kind, addr in (("token_occurrence", int(r["address"])), ("containing_string_base", int(r.get("string_base_address", r["address"])))):
            pat = struct.pack("<Q", addr)
            candidates.setdefault(pat, []).append((r, kind, addr))
            prio = _pointer_target_priority(r, kind)
            if pat not in priorities or prio < priorities[pat]:
                priorities[pat] = prio
            states.setdefault(pat, set()).add(str(r.get("token_state", "")))

    ordered = sorted(candidates, key=lambda pat: (priorities[pat], pat))
    # Preserve representation of both dry and wet targets when both exist.
    # Reserve half of the bounded budget for each state first, then fill any
    # unused capacity by global priority.
    chosen: list[bytes] = []
    per_state_quota = max(1, max_targets // 2) if max_targets else 0
    for wanted_state in ("dry", "wet"):
        added = 0
        for pat in ordered:
            if pat in chosen or wanted_state not in states.get(pat, set()):
                continue
            chosen.append(pat)
            added += 1
            if len(chosen) >= max_targets or added >= per_state_quota:
                break
    if len(chosen) < max_targets:
        for pat in ordered:
            if pat not in chosen:
                chosen.append(pat)
                if len(chosen) >= max_targets:
                    break
    selected = {pat: candidates[pat] for pat in chosen}
    return selected, {
        "target_pattern_rows_total": len(candidates),
        "target_pattern_rows_selected": len(selected),
        "target_pattern_rows_skipped": max(0, len(candidates) - len(selected)),
        "target_selection_bounded": len(candidates) > len(selected),
        "max_target_patterns": int(max_targets),
    }


def scan_pointer_references(reader: ProcessMemoryReader, maps: Sequence[MapRow], game_root: Path, token_rows: Sequence[Mapping[str, Any]], *, label: str, max_bytes: int = MAX_POINTER_SCAN_BYTES, max_targets: int = MAX_POINTER_TARGETS) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    targets, target_stats = select_pointer_targets(token_rows, max_targets=max_targets)
    if not targets:
        return [], {
            "selected_mapping_rows": 0,
            "planned_scan_bytes": 0,
            "bytes_read": 0,
            "target_address_rows": 0,
            "pointer_scan_bounded": True,
            **target_stats,
        }
    pattern = re.compile(b"|".join(re.escape(x) for x in sorted(targets)))
    selected = select_pointer_mappings(maps, game_root, max_bytes)
    map_index_by_key = {mapping_key(m): i for i, m in enumerate(maps)}
    rows: list[dict[str, Any]] = []
    seen: set[tuple[int, int]] = set()
    scanned = 0
    planned = min(sum(m.size for m in selected), max_bytes)
    last_progress = 0
    print(
        f"[stage164] {label}: bounded pointer scan planned {planned / (1024**2):.1f} MiB "
        f"across <= {len(selected)} writable mappings; {len(targets)}/{target_stats['target_pattern_rows_total']} target patterns",
        flush=True,
    )
    for m in selected:
        if scanned >= max_bytes:
            break
        remaining = max_bytes - scanned
        for base, data, nread in read_mapping_chunks(reader, m, overlap=16, max_bytes=remaining):
            scanned += nread
            for match in pattern.finditer(data):
                site = base + match.start()
                # Pointer fields are normally naturally aligned. Keep 8-byte and
                # 4-byte aligned sites to avoid drowning the report in accidental data.
                if site % 4:
                    continue
                key = (site, int.from_bytes(match.group(0), "little"))
                if key in seen:
                    continue
                seen.add(key)
                cls, basename, ph = normalized_mapping_path(m, game_root)
                lo = max(0, match.start() - CONTEXT_RADIUS)
                hi = min(len(data), match.end() + CONTEXT_RADIUS)
                for target, target_kind, target_pointer_value in targets[match.group(0)]:
                    rows.append({
                        "site_address": site,
                        "site_address_hex": f"0x{site:x}",
                        "site_mapping_index": map_index_by_key[mapping_key(m)],
                        "site_mapping_key": mapping_key(m),
                        "site_mapping_class": cls,
                        "site_mapping_permissions": m.perms,
                        "site_mapping_path_basename": basename,
                        "site_mapping_path_sha256": ph,
                        "site_mapping_relative_offset": site - m.start,
                        "site_context_sha256": sha256_bytes(data[lo:hi]),
                        "target_token_label": target["token_label"],
                        "target_token_state": target["token_state"],
                        "target_encoding": target["encoding"],
                        "target_address_kind": target_kind,
                        "target_address": target_pointer_value,
                        "target_address_hex": f"0x{target_pointer_value:x}",
                        "classification": "bounded_exact_address_pointer_reference_candidate_not_object_semantics",
                    })
            if scanned - last_progress >= POINTER_PROGRESS_BYTES:
                pct = (100.0 * scanned / planned) if planned else 100.0
                print(f"[stage164] {label}: bounded pointer scan {scanned / (1024**2):.0f}/{planned / (1024**2):.0f} MiB ({min(pct,100):.1f}%)", flush=True)
                last_progress = scanned
    return rows, {
        "selected_mapping_rows": len(selected),
        "planned_scan_bytes": planned,
        "bytes_read": scanned,
        "target_address_rows": sum(len(v) for v in targets.values()),
        "pointer_scan_bounded": True,
        "max_pointer_scan_bytes": int(max_bytes),
        **target_stats,
    }


def _probe_memory_access(pid: int, maps: Sequence[MapRow], game_root: Path) -> tuple[bool, str]:
    selected = select_scan_mappings(maps, game_root, 64 * 1024 * 1024)
    if not selected:
        return False, "no eligible readable mapping"
    with ProcessMemoryReader(pid) as reader:
        for m in selected[:20]:
            try:
                b = reader.read(m.start, min(16, m.size))
                if b:
                    return True, "ok"
            except OSError as exc:
                if exc.errno in (errno.EPERM, errno.EACCES):
                    return False, f"permission denied: {exc}"
                continue
            except PermissionError as exc:
                return False, f"permission denied: {exc}"
    return False, "readable mappings exist but no memory byte could be read"


def snapshot_process(pid: int, game_root: Path, label: str) -> dict[str, Any]:
    maps = read_maps(pid)
    require(maps, f"PID {pid} has no readable /proc maps")
    ok, reason = _probe_memory_access(pid, maps, game_root)
    if not ok:
        if "permission" in reason.casefold():
            raise PermissionError(reason)
        raise Stage164Error(reason)
    with ProcessMemoryReader(pid) as reader:
        token_rows, token_stats = scan_tokens(reader, maps, game_root, label=label)
        pointer_rows, pointer_stats = scan_pointer_references(reader, maps, game_root, token_rows, label=label)
    return {
        "label": label,
        "captured_unix": int(time.time()),
        "maps": maps,
        "token_rows": token_rows,
        "pointer_rows": pointer_rows,
        "token_scan_stats": token_stats,
        "pointer_scan_stats": pointer_stats,
    }


def token_residency_rows(dry: Mapping[str, Any], wet: Mapping[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for spec in TOKEN_SPECS:
        for enc in ("ascii", "utf16le"):
            d = [r for r in dry["token_rows"] if r["token_label"] == spec.label and r["encoding"] == enc]
            w = [r for r in wet["token_rows"] if r["token_label"] == spec.label and r["encoding"] == enc]
            d_classes: dict[str, int] = {}
            w_classes: dict[str, int] = {}
            for r in d: d_classes[r["mapping_class"]] = d_classes.get(r["mapping_class"], 0) + 1
            for r in w: w_classes[r["mapping_class"]] = w_classes.get(r["mapping_class"], 0) + 1
            rows.append({
                "token_label": spec.label,
                "token_text": spec.text,
                "token_state": spec.state,
                "encoding": enc,
                "dry_occurrence_rows": len(d),
                "wet_occurrence_rows": len(w),
                "occurrence_delta": len(w) - len(d),
                "dry_mapping_class_counts_json": json.dumps(d_classes, sort_keys=True, separators=(",", ":")),
                "wet_mapping_class_counts_json": json.dumps(w_classes, sort_keys=True, separators=(",", ":")),
            })
    return rows


def pointer_switch_rows(dry: Mapping[str, Any], wet: Mapping[str, Any]) -> list[dict[str, Any]]:
    # Same PID + same mapped site. A switch from a pointer into a dry primary
    # token to a pointer into a wet primary token is a bounded runtime anchor,
    # not proof of object/material/transparency semantics.
    d_by_site: dict[int, list[Mapping[str, Any]]] = {}
    w_by_site: dict[int, list[Mapping[str, Any]]] = {}
    for r in dry["pointer_rows"]: d_by_site.setdefault(int(r["site_address"]), []).append(r)
    for r in wet["pointer_rows"]: w_by_site.setdefault(int(r["site_address"]), []).append(r)
    out: list[dict[str, Any]] = []
    for site in sorted(set(d_by_site) & set(w_by_site)):
        for d in d_by_site[site]:
            for w in w_by_site[site]:
                if d["target_token_state"] == "dry" and w["target_token_state"] == "wet":
                    out.append({
                        "site_address_hex": f"0x{site:x}",
                        "site_mapping_key": d["site_mapping_key"],
                        "site_mapping_class": d["site_mapping_class"],
                        "site_mapping_path_basename": d["site_mapping_path_basename"],
                        "site_mapping_relative_offset": d["site_mapping_relative_offset"],
                        "dry_target_token_label": d["target_token_label"],
                        "wet_target_token_label": w["target_token_label"],
                        "dry_site_context_sha256": d["site_context_sha256"],
                        "wet_site_context_sha256": w["site_context_sha256"],
                        "context_changed": d["site_context_sha256"] != w["site_context_sha256"],
                        "classification": "same_address_dry_to_wet_pointer_switch_candidate_not_selector_or_transparency_semantics",
                    })
    return out


def token_site_context_changes(dry: Mapping[str, Any], wet: Mapping[str, Any]) -> list[dict[str, Any]]:
    d = {(r["address"], r["token_label"], r["encoding"]): r for r in dry["token_rows"]}
    w = {(r["address"], r["token_label"], r["encoding"]): r for r in wet["token_rows"]}
    out: list[dict[str, Any]] = []
    for key in sorted(set(d) & set(w)):
        a, label, enc = key
        dr, wr = d[key], w[key]
        if dr["context_sha256"] == wr["context_sha256"] and dr["page_sha256"] == wr["page_sha256"]:
            continue
        out.append({
            "token_address_hex": f"0x{a:x}",
            "token_label": label,
            "encoding": enc,
            "mapping_key": dr["mapping_key"],
            "mapping_class": dr["mapping_class"],
            "mapping_path_basename": dr["mapping_path_basename"],
            "mapping_relative_offset": dr["mapping_relative_offset"],
            "dry_context_sha256": dr["context_sha256"],
            "wet_context_sha256": wr["context_sha256"],
            "dry_page_sha256": dr["page_sha256"],
            "wet_page_sha256": wr["page_sha256"],
            "context_changed": dr["context_sha256"] != wr["context_sha256"],
            "page_changed": dr["page_sha256"] != wr["page_sha256"],
            "classification": "token_resident_memory_context_changed_not_field_semantics",
        })
    return out


def wet_only_dynamic_rows(dry: Mapping[str, Any], wet: Mapping[str, Any]) -> list[dict[str, Any]]:
    d_sites = {(r["token_label"], r["encoding"], r["mapping_key"], r["mapping_relative_offset"]) for r in dry["token_rows"]}
    out: list[dict[str, Any]] = []
    for r in wet["token_rows"]:
        key = (r["token_label"], r["encoding"], r["mapping_key"], r["mapping_relative_offset"])
        if key in d_sites or r["token_state"] != "wet":
            continue
        out.append({
            "token_label": r["token_label"],
            "encoding": r["encoding"],
            "mapping_key": r["mapping_key"],
            "mapping_class": r["mapping_class"],
            "mapping_path_basename": r["mapping_path_basename"],
            "mapping_relative_offset": r["mapping_relative_offset"],
            "context_sha256": r["context_sha256"],
            "classification": "wet_snapshot_only_token_residency_candidate_not_resolution_semantics",
        })
    return out


def _render_stack_flags(maps: Sequence[MapRow]) -> dict[str, bool]:
    names = "\n".join(m.path.casefold() for m in maps)
    return {
        "dxvk_observed": "dxvk" in names or "d3d11.dll" in names or "dxgi.dll" in names,
        "vkd3d_observed": "vkd3d" in names,
        "wined3d_observed": "wined3d" in names,
        "renderdoc_observed": "renderdoc" in names,
        "vulkan_loader_observed": "libvulkan" in names or "vulkan-1" in names,
    }


def verify_stage163_report(project_root: Path) -> None:
    p = project_root / ".local/reports/quartet_restoration" / STAGE163_REPORT
    require(p.is_file(), f"missing prerequisite stage163 report: {p}")
    actual = sha256_file(p)
    require(actual == STAGE163_SHA256, f"stage163 report SHA-256 drift: {actual}")


def verify_clean_pack10_02(game_root: Path) -> str:
    p = game_root / "Data/PACK10_02.PAK"
    require(p.is_file(), f"missing Quartet PACK10_02: {p}")
    actual = sha256_file(p)
    require(actual == PACK10_02_BASELINE_SHA256, f"PACK10_02 is not the exact clean baseline required for native trace: {actual}")
    return actual


def process_public_row(proc: Mapping[str, Any]) -> dict[str, Any]:
    cmd = bytes(proc.get("cmdline", b""))
    exe = str(proc.get("exe", ""))
    cwd = str(proc.get("cwd", ""))
    return {
        "pid": proc["pid"],
        "selection_score": proc.get("score", 0),
        "rss_bytes": proc.get("rss", 0),
        "exe_basename": Path(exe).name if exe else "",
        "exe_path_sha256": hash_text(exe) if exe else "",
        "cwd_basename": Path(cwd).name if cwd else "",
        "cwd_path_sha256": hash_text(cwd) if cwd else "",
        "cmdline_sha256": sha256_bytes(cmd),
        "full_cmdline_exported": False,
        "absolute_paths_exported": False,
    }


def _export_token_rows(snapshot_label: str, rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    out = []
    for r in rows:
        x = dict(r)
        x["snapshot"] = snapshot_label
        x.pop("address", None)
        out.append(x)
    return out


def _export_pointer_rows(snapshot_label: str, rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    out = []
    for r in rows:
        x = dict(r)
        x["snapshot"] = snapshot_label
        x.pop("site_address", None)
        x.pop("target_address", None)
        out.append(x)
    return out


def build_report(
    project_root: Path,
    game_root: Path,
    *,
    pid: int | None = None,
    report_root: Path | None = None,
    output_report_root: Path | None = None,
    create_archive: bool = True,
    interactive: bool = True,
    fixture_snapshots: tuple[Mapping[str, Any], Mapping[str, Any]] | None = None,
    skip_prerequisites_for_fixture: bool = False,
) -> tuple[Path | None, dict[str, Any]]:
    project_root = safe_resolve(project_root)
    game_root = safe_resolve(game_root)
    report_root = report_root or project_root / ".local/reports/quartet_restoration"
    output_report_root = output_report_root or report_root
    out = report_root / REPORT_DIR
    if out.exists(): shutil.rmtree(out)
    out.mkdir(parents=True, exist_ok=True)

    if not skip_prerequisites_for_fixture:
        verify_stage163_report(project_root)
        baseline_before = verify_clean_pack10_02(game_root)
    else:
        baseline_before = PACK10_02_BASELINE_SHA256

    if fixture_snapshots is None:
        proc = discover_game_process(game_root, explicit_pid=pid)
        selected_pid = int(proc["pid"])
        maps0 = read_maps(selected_pid)
        ok, reason = _probe_memory_access(selected_pid, maps0, game_root)
        if not ok:
            if "permission" in reason.casefold():
                raise PermissionError(reason)
            raise Stage164Error(reason)
        if interactive:
            print("\n[stage164] Prepare the NATIVE DRY control:", flush=True)
            print("  - Hinako / pc00", flush=True)
            print("  - native School Uniform", flush=True)
            print("  - DRY state", flush=True)
            print("  - do not use Generation 10 v2 synthetic wardrobe state", flush=True)
            input("[stage164] Keep the game idle, return here and press Enter to capture DRY... ")
        dry = snapshot_process(selected_pid, game_root, "dry")
        if interactive:
            print("\n[stage164] DRY captured. Return to the SAME game process.", flush=True)
            print("Use native Change Wetness only. Do not change character, costume or scene/menu context if avoidable.", flush=True)
            input("[stage164] When the same School Uniform is visibly WET, return here and press Enter to capture WET... ")
        require((Path("/proc") / str(selected_pid)).is_dir(), "game process exited between DRY and WET captures")
        wet = snapshot_process(selected_pid, game_root, "wet")
        proc_row = process_public_row(proc)
    else:
        dry, wet = fixture_snapshots
        selected_pid = int(dry.get("pid", 4242))
        proc_row = {"pid": selected_pid, "selection_score": 0, "rss_bytes": 0, "exe_basename": "fixture.exe", "exe_path_sha256": "fixture", "cwd_basename": "fixture", "cwd_path_sha256": "fixture", "cmdline_sha256": "fixture", "full_cmdline_exported": False, "absolute_paths_exported": False}

    require(dry["label"] == "dry" and wet["label"] == "wet", "snapshot labels drift")
    residency = token_residency_rows(dry, wet)
    switches = pointer_switch_rows(dry, wet)
    context_changes = token_site_context_changes(dry, wet)
    wet_only = wet_only_dynamic_rows(dry, wet)

    map_rows: list[dict[str, Any]] = []
    for label, snap in (("dry", dry), ("wet", wet)):
        for i, m in enumerate(snap["maps"]):
            r = map_evidence_row(i, m, game_root); r["snapshot"] = label; map_rows.append(r)

    token_rows = _export_token_rows("dry", dry["token_rows"]) + _export_token_rows("wet", wet["token_rows"])
    pointer_rows = _export_pointer_rows("dry", dry["pointer_rows"]) + _export_pointer_rows("wet", wet["pointer_rows"])
    render_flags = _render_stack_flags(wet["maps"])

    if switches:
        quality = "bounded_same_address_dry_to_wet_pointer_switches_observed"
        next_action = "Use the exact same-address pointer-switch sites as bounded anchors for a narrower second native trace that records nearby pointer/scalar fields before considering any runtime write. Do not assign material/shader/transparency semantics yet."
    elif wet_only:
        quality = "wet_only_process_token_residency_observed_without_pointer_switch"
        next_action = "Use wet-only heap/token residency sites as bounded object-neighborhood anchors for one narrower read-only trace. If no stable object neighborhood emerges, move to render-state capture rather than guessing another asset write."
    elif context_changes:
        quality = "resident_token_context_changes_observed_without_selector_pointer_switch"
        next_action = "Use changed token-context pages only as bounded memory neighborhoods for a narrower trace; if they do not yield stable state fields, move to render-state capture."
    else:
        quality = "no_dynamic_pc00_asset_token_anchor_observed"
        next_action = "Do not invent another texture/material write. Move to a render-state capture at the native dry/wet boundary (pipeline/shader/resource bindings), because process token residency did not expose a bounded selector/object anchor."

    # Re-hash only outside fixture mode. This proves the observational harness
    # did not alter the installed target archive.
    if not skip_prerequisites_for_fixture:
        baseline_after = sha256_file(game_root / "Data/PACK10_02.PAK")
        require(baseline_after == baseline_before == PACK10_02_BASELINE_SHA256, "PACK10_02 changed during read-only trace")
    else:
        baseline_after = baseline_before

    summary = {
        "format_version": 1,
        "type": "br_quartet_restoration_native_wetness_process_state_trace_evidence_summary",
        "tool_version": TOOL_VERSION,
        "stage": 164,
        "status": "native_dry_wet_process_state_trace_complete_read_only",
        "stage163_report_sha256": STAGE163_SHA256,
        "stage163_pc00_bounded_trace_anchor_rows": 0,
        "stage163_selector_binding_confirmed": False,
        "same_pid_dry_wet_capture": True,
        "pid": selected_pid,
        "runtime_trace_performed": True,
        "runtime_process_memory_read": True,
        "runtime_process_memory_written": False,
        "ptrace_or_debugger_write_performed": False,
        "raw_process_memory_exported": False,
        "absolute_process_paths_exported": False,
        "full_process_cmdline_exported": False,
        "installed_game_modified": False,
        "pak_built_or_repacked": False,
        "pack10_02_baseline_before_sha256": baseline_before,
        "pack10_02_baseline_after_sha256": baseline_after,
        "generation10_v2_dependency_forbidden": True,
        "native_change_wetness_control_required": True,
        "dry_token_occurrence_rows": len(dry["token_rows"]),
        "wet_token_occurrence_rows": len(wet["token_rows"]),
        "dry_pointer_reference_rows": len(dry["pointer_rows"]),
        "wet_pointer_reference_rows": len(wet["pointer_rows"]),
        "pointer_scan_exhaustive": False,
        "pointer_scan_strategy": "bounded_priority_sample_after_full_token_scan",
        "pointer_scan_max_bytes_per_snapshot": MAX_POINTER_SCAN_BYTES,
        "pointer_target_pattern_cap_per_snapshot": MAX_POINTER_TARGETS,
        "dry_pointer_scan_planned_bytes": int(dry.get("pointer_scan_stats", {}).get("planned_scan_bytes", 0)),
        "dry_pointer_scan_bytes_read": int(dry.get("pointer_scan_stats", {}).get("bytes_read", 0)),
        "dry_pointer_target_patterns_total": int(dry.get("pointer_scan_stats", {}).get("target_pattern_rows_total", 0)),
        "dry_pointer_target_patterns_selected": int(dry.get("pointer_scan_stats", {}).get("target_pattern_rows_selected", 0)),
        "wet_pointer_scan_planned_bytes": int(wet.get("pointer_scan_stats", {}).get("planned_scan_bytes", 0)),
        "wet_pointer_scan_bytes_read": int(wet.get("pointer_scan_stats", {}).get("bytes_read", 0)),
        "wet_pointer_target_patterns_total": int(wet.get("pointer_scan_stats", {}).get("target_pattern_rows_total", 0)),
        "wet_pointer_target_patterns_selected": int(wet.get("pointer_scan_stats", {}).get("target_pattern_rows_selected", 0)),
        "same_address_dry_to_wet_pointer_switch_rows": len(switches),
        "wet_only_token_residency_rows": len(wet_only),
        "resident_token_context_change_rows": len(context_changes),
        "trace_quality": quality,
        "selector_binding_confirmed": False,
        "material_binding_confirmed": False,
        "shader_binding_confirmed": False,
        "wet_transparency_mechanism_confirmed": False,
        "write_authorized_rows": 0,
        "next_action": next_action,
        **render_flags,
    }

    write_tsv(out / "PROCESS.tsv", list(proc_row.keys()), [proc_row])
    write_tsv(out / "PROCESS_MODULES.tsv", ["snapshot","mapping_index","mapping_key","mapping_class","permissions","size","file_offset","inode","path_basename","path_sha256"], map_rows)
    write_tsv(out / "TOKEN_OCCURRENCES.tsv", ["snapshot","token_label","token_text","token_state","primary_token","encoding","address_hex","string_base_address_hex","string_base_delta","containing_string_sha256","mapping_index","mapping_key","mapping_class","mapping_permissions","mapping_path_basename","mapping_path_sha256","mapping_relative_offset","context_sha256","page_sha256"], token_rows)
    write_tsv(out / "TOKEN_RESIDENCY_DIFF.tsv", ["token_label","token_text","token_state","encoding","dry_occurrence_rows","wet_occurrence_rows","occurrence_delta","dry_mapping_class_counts_json","wet_mapping_class_counts_json"], residency)
    write_tsv(out / "POINTER_REFERENCES.tsv", ["snapshot","site_address_hex","site_mapping_index","site_mapping_key","site_mapping_class","site_mapping_permissions","site_mapping_path_basename","site_mapping_path_sha256","site_mapping_relative_offset","site_context_sha256","target_token_label","target_token_state","target_encoding","target_address_kind","target_address_hex","classification"], pointer_rows)
    write_tsv(out / "POINTER_SWITCH_CANDIDATES.tsv", ["site_address_hex","site_mapping_key","site_mapping_class","site_mapping_path_basename","site_mapping_relative_offset","dry_target_token_label","wet_target_token_label","dry_site_context_sha256","wet_site_context_sha256","context_changed","classification"], switches)
    write_tsv(out / "WET_ONLY_TOKEN_RESIDENCY.tsv", ["token_label","encoding","mapping_key","mapping_class","mapping_path_basename","mapping_relative_offset","context_sha256","classification"], wet_only)
    write_tsv(out / "TOKEN_CONTEXT_CHANGE_CANDIDATES.tsv", ["token_address_hex","token_label","encoding","mapping_key","mapping_class","mapping_path_basename","mapping_relative_offset","dry_context_sha256","wet_context_sha256","dry_page_sha256","wet_page_sha256","context_changed","page_changed","classification"], context_changes)
    (out / "SUMMARY.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    archive = output_report_root / REPORT_NAME if create_archive else None
    if archive is not None:
        make_archive(out, archive)
    return archive, summary


def probe(project_root: Path, game_root: Path, pid: int | None = None) -> dict[str, Any]:
    verify_stage163_report(project_root)
    # Avoid a multi-hundred-MiB baseline hash during a privilege-only probe;
    # the full trace verifies it before capture.
    proc = discover_game_process(game_root, explicit_pid=pid)
    maps = read_maps(int(proc["pid"]))
    ok, reason = _probe_memory_access(int(proc["pid"]), maps, game_root)
    return {"pid": proc["pid"], "memory_readable": ok, "reason": reason}


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    ap = argparse.ArgumentParser()
    ap.add_argument("project_root", type=Path)
    ap.add_argument("--game-root", type=Path, required=True)
    ap.add_argument("--pid", type=int)
    ap.add_argument("--probe-access", action="store_true")
    ap.add_argument("--no-interactive", action="store_true")
    ap.add_argument("--report-root", type=Path)
    ap.add_argument("--output-report-root", type=Path)
    ap.add_argument("--no-archive", action="store_true")
    return ap.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    a = parse_args(argv)
    project_root = safe_resolve(a.project_root)
    game_root = safe_resolve(a.game_root)
    try:
        if a.probe_access:
            result = probe(project_root, game_root, a.pid)
            print(json.dumps(result, sort_keys=True))
            return 0 if result["memory_readable"] else ACCESS_DENIED_EXIT
        archive, summary = build_report(
            project_root,
            game_root,
            pid=a.pid,
            report_root=a.report_root,
            output_report_root=a.output_report_root,
            create_archive=not a.no_archive,
            interactive=not a.no_interactive,
        )
        print(json.dumps(summary, indent=2, sort_keys=True))
        if archive:
            print(f"[stage164] evidence: {archive}")
        return 0
    except PermissionError as exc:
        print(f"[stage164] process-memory access denied: {exc}", file=sys.stderr)
        return ACCESS_DENIED_EXIT
    except Stage164Error as exc:
        print(f"[stage164] ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
