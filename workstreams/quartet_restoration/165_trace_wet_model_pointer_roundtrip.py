#!/usr/bin/env python3
"""Stage 165: targeted wet-model pointer roundtrip trace (read-only).

Stage 164 observed three WET-only resident copies of the exact Hinako wet-school
model token `PC00_Scl_W_P_School_Wet.g1m`, but its bounded generic pointer
sample did not target that auxiliary token.  Stage 165 turns only *newly
resident* WET-model token addresses into exact 64-bit pointer targets, scans
writable process memory for references, and—if any sites are found—asks the
user to toggle native Change Wetness back to DRY and re-reads only those exact
sites.

No process memory or game file is written.  No raw process-memory bytes,
absolute process paths, or full command lines are exported.  Pointed-to
payloads are classified by exact already-grounded pc00 school tokens and hash
only; arbitrary pointed-to bytes are not exported.
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
import time
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

TOOL_VERSION = "0.1.87"
STAGE = 165
REPORT_DIR = "wet_model_pointer_roundtrip_trace_evidence"
REPORT_NAME = "BR_quartet_restoration_wet_model_pointer_roundtrip_trace_evidence.tar.zst"
STAGE164_REPORT = "BR_quartet_restoration_native_wetness_process_state_trace_evidence.tar.zst"
STAGE164_SHA256 = "b1763e27075d47287bb64e71c6d2f8454c3f49a058747422ed1ddcaf06fa70dc"
PACK10_02_BASELINE_SHA256 = "e798f39c3bcdbb11381197bddf9bd3ad8de6ccf5d7c0c78b22613046d47f5302"
WET_MODEL_TOKEN = b"PC00_Scl_W_P_School_Wet.g1m"
DRY_SCHOOL_TOKEN = b"pc00_scl"
WET_SCHOOL_TOKEN = b"pc00_scl_w"
MAX_TOKEN_SCAN_BYTES = 4 * 1024 * 1024 * 1024
MAX_POINTER_SCAN_BYTES = 4 * 1024 * 1024 * 1024
CHUNK_SIZE = 16 * 1024 * 1024
PROGRESS_BYTES = 256 * 1024 * 1024
CONTEXT_RADIUS = 128
POINTED_READ_BYTES = 384
ACCESS_DENIED_EXIT = 77


class Stage165Error(RuntimeError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise Stage165Error(message)


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


def _load_stage164():
    path = Path(__file__).with_name("164_trace_native_wetness_process_state.py")
    spec = importlib.util.spec_from_file_location("br_restoration_stage164", path)
    require(spec is not None and spec.loader is not None, "cannot load stage164 helper")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


S164 = _load_stage164()


def verify_prerequisites(project_root: Path, game_root: Path) -> str:
    stage164 = project_root / ".local/reports/quartet_restoration" / STAGE164_REPORT
    require(stage164.is_file(), f"missing prerequisite stage164 report: {stage164}")
    actual = sha256_file(stage164)
    require(actual == STAGE164_SHA256, f"stage164 report SHA-256 drift: {actual}")
    pak = game_root / "Data/PACK10_02.PAK"
    require(pak.is_file(), f"missing Quartet PACK10_02: {pak}")
    baseline = sha256_file(pak)
    require(baseline == PACK10_02_BASELINE_SHA256, f"PACK10_02 is not exact baseline: {baseline}")
    return baseline


def eligible_scan_maps(maps: Sequence[Any], game_root: Path) -> list[Any]:
    rows = [m for m in maps if "r" in m.perms and m.size > 0 and S164.mapping_class(m, game_root) not in {"device_or_gpu", "kernel_pseudo"}]
    def prio(m: Any) -> tuple[int, int]:
        cls = S164.mapping_class(m, game_root)
        if "w" in m.perms and cls == "anonymous": return (0, m.size)
        if m.path == "[heap]": return (1, m.size)
        if "w" in m.perms: return (2, m.size)
        if cls == "game": return (3, m.size)
        return (4, m.size)
    rows.sort(key=prio)
    return rows


def writable_scan_maps(maps: Sequence[Any], game_root: Path) -> list[Any]:
    rows = [m for m in maps if "r" in m.perms and "w" in m.perms and m.size > 0 and S164.mapping_class(m, game_root) not in {"device_or_gpu", "kernel_pseudo"}]
    rows.sort(key=lambda m: (0 if S164.mapping_class(m, game_root) == "anonymous" else 1, m.size))
    return rows


def _read_chunks_exact_cap(reader: Any, maps: Sequence[Any], max_bytes: int, *, overlap: int = 64):
    scanned = 0
    for m in maps:
        if scanned >= max_bytes:
            break
        remaining = max_bytes - scanned
        cap = min(m.size, remaining)
        for base, data, nread in S164.read_mapping_chunks(reader, m, chunk_size=CHUNK_SIZE, overlap=overlap, max_bytes=cap):
            scanned += nread
            yield m, base, data, nread, scanned
            if scanned >= max_bytes:
                break


def scan_wet_model_token(reader: Any, maps: Sequence[Any], game_root: Path, label: str, max_bytes: int = MAX_TOKEN_SCAN_BYTES) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    selected = eligible_scan_maps(maps, game_root)
    planned = min(sum(m.size for m in selected), max_bytes)
    print(f"[stage165] {label}: wet-model token scan planned {planned / (1024**2):.1f} MiB", flush=True)
    rows: list[dict[str, Any]] = []
    seen: set[int] = set()
    last_progress = 0
    map_index = {S164.mapping_key(m): i for i, m in enumerate(maps)}
    scanned = 0
    for m, base, data, _nread, scanned in _read_chunks_exact_cap(reader, selected, max_bytes, overlap=len(WET_MODEL_TOKEN) + CONTEXT_RADIUS * 2):
        start = 0
        while True:
            at = data.find(WET_MODEL_TOKEN, start)
            if at < 0: break
            start = at + 1
            addr = base + at
            if addr in seen: continue
            seen.add(addr)
            lo = max(0, at - CONTEXT_RADIUS); hi = min(len(data), at + len(WET_MODEL_TOKEN) + CONTEXT_RADIUS)
            cls, basename, ph = S164.normalized_mapping_path(m, game_root)
            rows.append({
                "snapshot": label,
                "address": addr,
                "address_hex": f"0x{addr:x}",
                "mapping_index": map_index[S164.mapping_key(m)],
                "mapping_key": S164.mapping_key(m),
                "mapping_class": cls,
                "mapping_permissions": m.perms,
                "mapping_path_basename": basename,
                "mapping_path_sha256": ph,
                "mapping_relative_offset": addr - m.start,
                "context_sha256": sha256_bytes(data[lo:hi]),
                "classification": "exact_wet_model_token_residency_not_object_semantics",
            })
        if scanned - last_progress >= PROGRESS_BYTES:
            pct = 100.0 * scanned / planned if planned else 100.0
            print(f"[stage165] {label}: wet-model token scan {scanned/(1024**2):.0f}/{planned/(1024**2):.0f} MiB ({min(pct,100):.1f}%)", flush=True)
            last_progress = scanned
    return rows, {"planned_scan_bytes": planned, "bytes_read": scanned, "occurrence_rows": len(rows)}


def dynamic_wet_occurrences(dry_rows: Sequence[Mapping[str, Any]], wet_rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    dry_sites = {(r["mapping_key"], int(r["mapping_relative_offset"])) for r in dry_rows}
    out = []
    for r in wet_rows:
        key = (r["mapping_key"], int(r["mapping_relative_offset"]))
        if key not in dry_sites:
            x = dict(r)
            x["classification"] = "new_wet_model_token_residency_runtime_anchor_not_semantics"
            out.append(x)
    return out


def scan_pointers_to_dynamic_wet(reader: Any, maps: Sequence[Any], game_root: Path, targets: Sequence[Mapping[str, Any]], max_bytes: int = MAX_POINTER_SCAN_BYTES) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    pats: dict[bytes, list[Mapping[str, Any]]] = {}
    for t in targets:
        addr = int(t["address"])
        pats.setdefault(struct.pack("<Q", addr), []).append(t)
    if not pats:
        return [], {"planned_scan_bytes": 0, "bytes_read": 0, "target_patterns": 0, "reference_rows": 0}
    require(len(pats) <= 32, f"unexpectedly many dynamic wet-model pointer targets: {len(pats)}")
    selected = writable_scan_maps(maps, game_root)
    planned = min(sum(m.size for m in selected), max_bytes)
    print(f"[stage165] wet: targeted pointer scan planned {planned/(1024**2):.1f} MiB for {len(pats)} wet-model addresses", flush=True)
    rows: list[dict[str, Any]] = []
    seen: set[tuple[int, bytes]] = set()
    last_progress = 0
    map_index = {S164.mapping_key(m): i for i, m in enumerate(maps)}
    scanned = 0
    for m, base, data, _nread, scanned in _read_chunks_exact_cap(reader, selected, max_bytes, overlap=16):
        for pat, target_rows in pats.items():
            start = 0
            while True:
                at = data.find(pat, start)
                if at < 0: break
                start = at + 1
                site = base + at
                if site % 4: continue
                key = (site, pat)
                if key in seen: continue
                seen.add(key)
                cls, basename, ph = S164.normalized_mapping_path(m, game_root)
                lo = max(0, at - CONTEXT_RADIUS); hi = min(len(data), at + 8 + CONTEXT_RADIUS)
                for target in target_rows:
                    rows.append({
                        "site_address": site,
                        "site_address_hex": f"0x{site:x}",
                        "site_mapping_index": map_index[S164.mapping_key(m)],
                        "site_mapping_key": S164.mapping_key(m),
                        "site_mapping_class": cls,
                        "site_mapping_permissions": m.perms,
                        "site_mapping_path_basename": basename,
                        "site_mapping_path_sha256": ph,
                        "site_mapping_relative_offset": site - m.start,
                        "wet_site_context_sha256": sha256_bytes(data[lo:hi]),
                        "wet_target_address": int(target["address"]),
                        "wet_target_address_hex": target["address_hex"],
                        "wet_target_mapping_key": target["mapping_key"],
                        "wet_target_mapping_relative_offset": target["mapping_relative_offset"],
                        "classification": "exact_pointer_to_new_wet_model_token_candidate_not_object_semantics",
                    })
        if scanned - last_progress >= PROGRESS_BYTES:
            pct = 100.0 * scanned / planned if planned else 100.0
            print(f"[stage165] wet: targeted pointer scan {scanned/(1024**2):.0f}/{planned/(1024**2):.0f} MiB ({min(pct,100):.1f}%)", flush=True)
            last_progress = scanned
    return rows, {"planned_scan_bytes": planned, "bytes_read": scanned, "target_patterns": len(pats), "reference_rows": len(rows)}


def _mapping_for_address(maps: Sequence[Any], address: int):
    for m in maps:
        if m.start <= address < m.end:
            return m
    return None


def classify_pointed_payload(reader: Any, maps: Sequence[Any], pointer: int) -> tuple[str, str]:
    if pointer == 0:
        return "null", ""
    m = _mapping_for_address(maps, pointer)
    if m is None or "r" not in m.perms:
        return "unmapped_or_unreadable", ""
    want = min(POINTED_READ_BYTES, max(0, m.end - pointer))
    if want <= 0:
        return "unmapped_or_unreadable", ""
    try:
        data = reader.read(pointer, want)
    except (OSError, PermissionError):
        return "unreadable", ""
    if not data:
        return "unreadable", ""
    low = data.lower()
    if WET_MODEL_TOKEN.lower() in low or WET_SCHOOL_TOKEN in low:
        cls = "points_to_wet_school_token"
    elif DRY_SCHOOL_TOKEN in low and WET_SCHOOL_TOKEN not in low:
        cls = "points_to_dry_school_token"
    else:
        printable = sum(1 for b in data[:128] if b in (9,10,13) or 0x20 <= b <= 0x7e)
        cls = "other_mostly_printable_payload" if printable >= max(8, min(len(data[:128]), 128) * 3 // 4) else "other_binary_payload"
    return cls, sha256_bytes(data)


def read_roundtrip_sites(reader: Any, maps: Sequence[Any], wet_pointer_rows: Sequence[Mapping[str, Any]], game_root: Path) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    dedup: dict[int, Mapping[str, Any]] = {}
    for r in wet_pointer_rows:
        dedup.setdefault(int(r["site_address"]), r)
    for site, wet in sorted(dedup.items()):
        m = _mapping_for_address(maps, site)
        if m is None or "r" not in m.perms or site + 8 > m.end:
            out.append({
                "site_address_hex": f"0x{site:x}",
                "wet_target_address_hex": wet["wet_target_address_hex"],
                "dry2_pointer_status": "site_unmapped_or_unreadable",
                "pointer_changed": "",
                "dry2_pointer_value_hex": "",
                "dry2_pointed_payload_class": "",
                "dry2_pointed_payload_sha256": "",
                "dry2_site_context_sha256": "",
                "classification": "roundtrip_site_unavailable_not_semantics",
            })
            continue
        try:
            raw = reader.read(site, 8)
            require(len(raw) == 8, "short read at roundtrip pointer site")
            value = struct.unpack("<Q", raw)[0]
            lo = max(m.start, site - CONTEXT_RADIUS); hi = min(m.end, site + 8 + CONTEXT_RADIUS)
            ctx = reader.read(lo, hi - lo)
            payload_class, payload_hash = classify_pointed_payload(reader, maps, value)
            changed = value != int(wet["wet_target_address"])
            if not changed:
                classification = "pointer_still_targets_wet_model_after_dry_roundtrip_not_selector_semantics"
            elif payload_class == "points_to_dry_school_token":
                classification = "wet_model_pointer_site_changed_to_dry_school_token_high_value_roundtrip_anchor_not_transparency_semantics"
            else:
                classification = "wet_model_pointer_site_changed_after_dry_roundtrip_candidate_object_anchor_not_semantics"
            out.append({
                "site_address_hex": f"0x{site:x}",
                "wet_target_address_hex": wet["wet_target_address_hex"],
                "dry2_pointer_status": "readable",
                "pointer_changed": changed,
                "dry2_pointer_value_hex": f"0x{value:x}",
                "dry2_pointed_payload_class": payload_class,
                "dry2_pointed_payload_sha256": payload_hash,
                "dry2_site_context_sha256": sha256_bytes(ctx),
                "classification": classification,
            })
        except (OSError, PermissionError, Stage165Error):
            out.append({
                "site_address_hex": f"0x{site:x}",
                "wet_target_address_hex": wet["wet_target_address_hex"],
                "dry2_pointer_status": "read_failed",
                "pointer_changed": "",
                "dry2_pointer_value_hex": "",
                "dry2_pointed_payload_class": "",
                "dry2_pointed_payload_sha256": "",
                "dry2_site_context_sha256": "",
                "classification": "roundtrip_site_read_failed_not_semantics",
            })
    return out


def process_row(proc: Mapping[str, Any]) -> dict[str, Any]:
    return S164.process_public_row(proc)


def run_trace(project_root: Path, game_root: Path, *, pid: int | None = None, interactive: bool = True) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    baseline = verify_prerequisites(project_root, game_root)
    proc = S164.discover_game_process(game_root, explicit_pid=pid)
    selected_pid = int(proc["pid"])

    def ensure_alive():
        require((Path("/proc") / str(selected_pid)).is_dir(), "game process exited during stage165 trace")

    if interactive:
        print("\n[stage165] Prepare native DRY control: Hinako / School Uniform / DRY.")
        print("[stage165] Earlier WET use is allowed; this capture establishes the current baseline.")
        input("[stage165] Keep the game idle, return here and press Enter to capture DRY1... ")
    ensure_alive()
    dry_maps = S164.read_maps(selected_pid)
    with S164.ProcessMemoryReader(selected_pid) as reader:
        dry_rows, dry_stats = scan_wet_model_token(reader, dry_maps, game_root, "dry1")

    if interactive:
        print(f"[stage165] DRY1 complete: {len(dry_rows)} resident exact wet-model token copies.")
        print("[stage165] Use native Change Wetness only: DRY -> WET. Do not change character/costume.")
        input("[stage165] Return here and press Enter when WET is fully visible... ")
    ensure_alive()
    wet_maps = S164.read_maps(selected_pid)
    with S164.ProcessMemoryReader(selected_pid) as reader:
        wet_rows, wet_stats = scan_wet_model_token(reader, wet_maps, game_root, "wet")
        dynamic = dynamic_wet_occurrences(dry_rows, wet_rows)
        pointer_rows, pointer_stats = scan_pointers_to_dynamic_wet(reader, wet_maps, game_root, dynamic)

    roundtrip_rows: list[dict[str, Any]] = []
    dry2_maps = wet_maps
    if pointer_rows and interactive:
        print(f"[stage165] Found {len(pointer_rows)} exact pointer-reference rows to new WET model token copies.")
        print("[stage165] Toggle native Change Wetness back to DRY, keeping the same character/costume/menu.")
        input("[stage165] Return here and press Enter when DRY is fully visible again... ")
        ensure_alive()
        dry2_maps = S164.read_maps(selected_pid)
        with S164.ProcessMemoryReader(selected_pid) as reader:
            roundtrip_rows = read_roundtrip_sites(reader, dry2_maps, pointer_rows, game_root)
    elif pointer_rows:
        # Fixture/non-interactive callers can invoke read_roundtrip_sites directly.
        roundtrip_rows = []

    baseline_after = sha256_file(game_root / "Data/PACK10_02.PAK")
    require(baseline_after == baseline == PACK10_02_BASELINE_SHA256, "PACK10_02 changed during read-only trace")
    stats = {
        "pid": selected_pid,
        "baseline_before": baseline,
        "baseline_after": baseline_after,
        "dry_stats": dry_stats,
        "wet_stats": wet_stats,
        "pointer_stats": pointer_stats,
        "dry_map_rows": len(dry_maps),
        "wet_map_rows": len(wet_maps),
        "dry2_map_rows": len(dry2_maps),
    }
    return proc, stats, dry_rows, wet_rows, pointer_rows, roundtrip_rows


def build_report(project_root: Path, game_root: Path, *, pid: int | None = None, interactive: bool = True, report_root: Path | None = None, output_report_root: Path | None = None, create_archive: bool = True) -> tuple[Path | None, dict[str, Any]]:
    project_root = S164.safe_resolve(project_root); game_root = S164.safe_resolve(game_root)
    report_root = report_root or project_root / ".local/reports/quartet_restoration" / REPORT_DIR
    output_report_root = output_report_root or project_root / ".local/reports/quartet_restoration"
    out = report_root
    if out.exists():
        import shutil; shutil.rmtree(out)
    out.mkdir(parents=True, exist_ok=True)

    proc, stats, dry_rows, wet_rows, pointer_rows, roundtrip_rows = run_trace(project_root, game_root, pid=pid, interactive=interactive)
    dynamic = dynamic_wet_occurrences(dry_rows, wet_rows)
    changed_rows = [r for r in roundtrip_rows if r.get("pointer_changed") is True]
    dry_token_rows = [r for r in roundtrip_rows if r.get("dry2_pointed_payload_class") == "points_to_dry_school_token"]

    if dry_token_rows:
        quality = "wet_model_pointer_roundtrip_to_dry_school_token_observed"
        next_action = "Use only the exact roundtrip pointer sites as bounded object-neighborhood anchors for a narrower read-only field/pointer trace. Do not write memory or assign transparency semantics yet."
    elif changed_rows:
        quality = "wet_model_pointer_roundtrip_change_observed_without_dry_token_identity"
        next_action = "Use changed exact pointer sites as bounded object-neighborhood anchors for one narrower read-only trace; if no stable object neighborhood emerges, move to render-state capture."
    elif pointer_rows:
        quality = "wet_model_pointer_references_observed_without_roundtrip_switch"
        next_action = "Do not infer selector semantics. Prefer render-state/resource binding capture unless a second independent object-neighborhood clue appears."
    elif dynamic:
        quality = "dynamic_wet_model_residency_confirmed_without_exact_pointer_reference"
        next_action = "Move to render-state capture at native Change Wetness rather than another blind asset or memory-field probe; the targeted full writable pointer scan found no exact reference to the dynamic wet-model strings."
    else:
        quality = "no_new_wet_model_residency_in_this_run"
        next_action = "Do not infer failure of wetness. Repeat only if the native state/costume was uncertain; otherwise move to render-state capture."

    summary = {
        "format_version": 1,
        "type": "br_quartet_restoration_wet_model_pointer_roundtrip_trace_evidence_summary",
        "tool_version": TOOL_VERSION,
        "stage": STAGE,
        "status": "wet_model_pointer_roundtrip_trace_complete_read_only",
        "stage164_report_sha256": STAGE164_SHA256,
        "same_pid_trace": True,
        "pid": stats["pid"],
        "dry1_exact_wet_model_occurrence_rows": len(dry_rows),
        "wet_exact_wet_model_occurrence_rows": len(wet_rows),
        "new_wet_model_residency_rows": len(dynamic),
        "exact_pointer_reference_rows": len(pointer_rows),
        "roundtrip_site_rows": len(roundtrip_rows),
        "roundtrip_changed_pointer_rows": len(changed_rows),
        "roundtrip_to_dry_school_token_rows": len(dry_token_rows),
        "targeted_pointer_scan_exhaustive_within_selected_readable_writable_set": True,
        "pointer_target_semantics": "exact_addresses_of_new_wet_model_token_copies_only",
        "pack10_02_baseline_before_sha256": stats["baseline_before"],
        "pack10_02_baseline_after_sha256": stats["baseline_after"],
        "runtime_process_memory_read": True,
        "runtime_process_memory_written": False,
        "ptrace_or_debugger_write_performed": False,
        "raw_process_memory_exported": False,
        "absolute_process_paths_exported": False,
        "full_process_cmdline_exported": False,
        "installed_game_modified": False,
        "pak_built_or_repacked": False,
        "generation10_v2_dependency_forbidden": True,
        "selector_binding_confirmed": False,
        "material_binding_confirmed": False,
        "shader_binding_confirmed": False,
        "wet_transparency_mechanism_confirmed": False,
        "write_authorized_rows": 0,
        "trace_quality": quality,
        "next_action": next_action,
        "dry_token_scan_bytes_read": stats["dry_stats"].get("bytes_read", 0),
        "wet_token_scan_bytes_read": stats["wet_stats"].get("bytes_read", 0),
        "wet_targeted_pointer_scan_bytes_read": stats["pointer_stats"].get("bytes_read", 0),
        "wet_targeted_pointer_pattern_rows": stats["pointer_stats"].get("target_patterns", 0),
    }

    public_proc = process_row(proc)
    write_tsv(out / "PROCESS.tsv", list(public_proc.keys()), [public_proc])
    token_fields = ["snapshot","address_hex","mapping_index","mapping_key","mapping_class","mapping_permissions","mapping_path_basename","mapping_path_sha256","mapping_relative_offset","context_sha256","classification"]
    write_tsv(out / "WET_MODEL_OCCURRENCES.tsv", token_fields, [{k:v for k,v in r.items() if k != "address"} for r in [*dry_rows,*wet_rows]])
    write_tsv(out / "NEW_WET_MODEL_RESIDENCY.tsv", token_fields, [{k:v for k,v in r.items() if k != "address"} for r in dynamic])
    ptr_fields = ["site_address_hex","site_mapping_index","site_mapping_key","site_mapping_class","site_mapping_permissions","site_mapping_path_basename","site_mapping_path_sha256","site_mapping_relative_offset","wet_site_context_sha256","wet_target_address_hex","wet_target_mapping_key","wet_target_mapping_relative_offset","classification"]
    write_tsv(out / "WET_MODEL_POINTER_REFERENCES.tsv", ptr_fields, [{k:v for k,v in r.items() if k not in {"site_address","wet_target_address"}} for r in pointer_rows])
    rt_fields = ["site_address_hex","wet_target_address_hex","dry2_pointer_status","pointer_changed","dry2_pointer_value_hex","dry2_pointed_payload_class","dry2_pointed_payload_sha256","dry2_site_context_sha256","classification"]
    write_tsv(out / "POINTER_SITE_ROUNDTRIP.tsv", rt_fields, roundtrip_rows)
    (out / "SUMMARY.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    archive = output_report_root / REPORT_NAME if create_archive else None
    if archive is not None: make_archive(out, archive)
    return archive, summary


def probe(project_root: Path, game_root: Path, pid: int | None = None) -> dict[str, Any]:
    verify_prerequisites(project_root, game_root)
    proc = S164.discover_game_process(game_root, explicit_pid=pid)
    maps = S164.read_maps(int(proc["pid"]))
    ok, reason = S164._probe_memory_access(int(proc["pid"]), maps, game_root)
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
    project_root = S164.safe_resolve(a.project_root); game_root = S164.safe_resolve(a.game_root)
    try:
        if a.probe_access:
            result = probe(project_root, game_root, a.pid)
            print(json.dumps(result, sort_keys=True))
            return 0 if result["memory_readable"] else ACCESS_DENIED_EXIT
        archive, summary = build_report(project_root, game_root, pid=a.pid, interactive=not a.no_interactive, report_root=a.report_root, output_report_root=a.output_report_root, create_archive=not a.no_archive)
        print(json.dumps(summary, indent=2, sort_keys=True))
        if archive: print(f"[stage165] evidence: {archive}")
        return 0
    except PermissionError as exc:
        print(f"[stage165] process-memory permission denied: {exc}", file=sys.stderr)
        return ACCESS_DENIED_EXIT
    except Stage165Error as exc:
        print(f"[stage165] ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
