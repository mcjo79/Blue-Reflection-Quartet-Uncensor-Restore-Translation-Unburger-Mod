#!/usr/bin/env python3
"""Stage 166: same-PID compound wet-state neighborhood roundtrip trace (read-only).

Stage 165 found three exact references to newly resident
`PC00_Scl_W_P_School_Wet.g1m` strings. Two reference sites kept the same pointer
value after the native WET->DRY roundtrip while the pointed neighborhood became
classifiable as the dry school state; a third site changed to a freed/sentinel
value.  Stage 166 deliberately continues only that exact process and those exact
sites.  It captures bounded neighborhoods in current DRY, native WET, and DRY2,
then reports only typed reversible pointer/scalar candidates and bounded
pc00 component-token residency.

The user additionally observed that native Change Wetness affects clothing,
body/skin and hair together.  This collector therefore checks grounded pc00
school/body/face-rig wet token families in the exact anchor neighborhood.  It
does not assume that hair has a separate asset or that any observed field is a
transparency control.

No process memory or game file is written.  No raw process-memory dump,
absolute process path, or full command line is exported.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import importlib.util
import json
import math
import os
import re
import struct
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

TOOL_VERSION = "0.1.89"
STAGE = 166
REPORT_DIR = "wet_character_compound_state_neighborhood_evidence"
REPORT_NAME = "BR_quartet_restoration_wet_character_compound_state_neighborhood_evidence.tar.zst"
STAGE165_REPORT = "BR_quartet_restoration_wet_model_pointer_roundtrip_trace_evidence.tar.zst"
STAGE165_SHA256 = "19938c006845ea7decba0a1db4e88ecd5bd704f43861b79bf8f5207c6bbf4d33"
PACK10_02_BASELINE_SHA256 = "e798f39c3bcdbb11381197bddf9bd3ad8de6ccf5d7c0c78b22613046d47f5302"
ACCESS_DENIED_EXIT = 77
LOCAL_FIELD_RADIUS = 1024
COMPONENT_WINDOW_RADIUS = 32 * 1024 * 1024
COMPONENT_CHUNK_SIZE = 8 * 1024 * 1024
COMPONENT_OVERLAP = 512
MAX_REVERSIBLE_ROWS = 512


class Stage166Error(RuntimeError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise Stage166Error(message)


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
    spec = importlib.util.spec_from_file_location("br_restoration_stage164_for166", path)
    require(spec is not None and spec.loader is not None, "cannot load stage164 helper")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def _load_stage165():
    path = Path(__file__).with_name("165_trace_wet_model_pointer_roundtrip.py")
    spec = importlib.util.spec_from_file_location("br_restoration_stage165_for166", path)
    require(spec is not None and spec.loader is not None, "cannot load stage165 helper")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


S164 = _load_stage164()
S165 = _load_stage165()


@dataclass(frozen=True)
class ComponentToken:
    label: str
    text: str
    state: str
    component: str
    exact_dry_boundary: bool = False


COMPONENT_TOKENS: tuple[ComponentToken, ...] = (
    ComponentToken("school_dry", "pc00_scl", "dry", "school_costume", True),
    ComponentToken("school_wet", "pc00_scl_w", "wet", "school_costume"),
    ComponentToken("school_wet_model", "PC00_Scl_W_P_School_Wet.g1m", "wet", "school_costume"),
    ComponentToken("school_wet_default", "PC00_Scl_W_default.g1m", "wet", "school_costume"),
    ComponentToken("body_dry", "pc00_nkd", "dry", "body_skin", True),
    ComponentToken("body_wet", "pc00_nkd_w", "wet", "body_skin"),
    ComponentToken("body_wet_model", "PC00_Nkd_W.g1m", "wet", "body_skin"),
    ComponentToken("body_wet_default", "PC00_Nkd_W_default.g1m", "wet", "body_skin"),
    ComponentToken("school_face_rig_dry", "pc00_scl_face_rig", "dry", "face_rig", True),
    ComponentToken("school_face_rig_wet", "pc00_scl_w_face_rig", "wet", "face_rig"),
)


def _archive_member_bytes(archive: Path, suffix: str) -> bytes:
    cp = subprocess.run(["tar", "--zstd", "-tf", str(archive)], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    require(cp.returncode == 0, cp.stderr.decode("utf-8", errors="replace").strip() or "cannot list stage165 archive")
    names = cp.stdout.decode("utf-8", errors="replace").splitlines()
    matches = [n for n in names if n.endswith("/" + suffix) or n == suffix]
    require(len(matches) == 1, f"stage165 archive expected exactly one {suffix}, found {len(matches)}")
    cp = subprocess.run(["tar", "--zstd", "-xOf", str(archive), matches[0]], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    require(cp.returncode == 0, cp.stderr.decode("utf-8", errors="replace").strip() or f"cannot read {suffix} from stage165 archive")
    return cp.stdout


def load_stage165_contract(project_root: Path) -> dict[str, Any]:
    archive = project_root / ".local/reports/quartet_restoration" / STAGE165_REPORT
    require(archive.is_file(), f"missing prerequisite stage165 report: {archive}")
    actual = sha256_file(archive)
    require(actual == STAGE165_SHA256, f"stage165 report SHA-256 drift: {actual}")
    summary = json.loads(_archive_member_bytes(archive, "SUMMARY.json").decode("utf-8"))
    require(summary.get("stage") == 165, "stage165 SUMMARY stage drift")
    require(summary.get("same_pid_trace") is True, "stage165 was not a same-PID trace")
    require(int(summary.get("roundtrip_site_rows", 0)) >= 1, "stage165 has no roundtrip sites")
    require(int(summary.get("roundtrip_to_dry_school_token_rows", 0)) >= 1, "stage165 has no DRY roundtrip school-token anchor")

    ptr_text = _archive_member_bytes(archive, "WET_MODEL_POINTER_REFERENCES.tsv").decode("utf-8")
    rt_text = _archive_member_bytes(archive, "POINTER_SITE_ROUNDTRIP.tsv").decode("utf-8")
    ptr_rows = list(csv.DictReader(ptr_text.splitlines(), delimiter="\t"))
    rt_rows = list(csv.DictReader(rt_text.splitlines(), delimiter="\t"))
    by_site = {r["site_address_hex"]: r for r in ptr_rows}
    sites: list[dict[str, Any]] = []
    for r in rt_rows:
        site_hex = r["site_address_hex"]
        require(site_hex in by_site, f"stage165 roundtrip site missing pointer metadata: {site_hex}")
        p = by_site[site_hex]
        sites.append({
            "site_address": int(site_hex, 16),
            "site_address_hex": site_hex,
            "wet_target_address": int(r["wet_target_address_hex"], 16),
            "wet_target_address_hex": r["wet_target_address_hex"],
            "site_mapping_key": p.get("site_mapping_key", ""),
            "site_mapping_relative_offset": int(p.get("site_mapping_relative_offset") or 0),
            "stage165_dry2_pointer_status": r.get("dry2_pointer_status", ""),
            "stage165_pointer_changed": r.get("pointer_changed", ""),
            "stage165_dry2_pointed_payload_class": r.get("dry2_pointed_payload_class", ""),
            "stage165_classification": r.get("classification", ""),
        })
    return {"archive": archive, "summary": summary, "sites": sites}


def verify_prerequisites(project_root: Path, game_root: Path) -> tuple[dict[str, Any], str]:
    contract = load_stage165_contract(project_root)
    pak = game_root / "Data/PACK10_02.PAK"
    require(pak.is_file(), f"missing Quartet PACK10_02: {pak}")
    baseline = sha256_file(pak)
    require(baseline == PACK10_02_BASELINE_SHA256, f"PACK10_02 is not exact baseline: {baseline}")
    return contract, baseline


def mapping_for_address(maps: Sequence[Any], address: int):
    for m in maps:
        if m.start <= address < m.end:
            return m
    return None


def pointer_mapping_descriptor(maps: Sequence[Any], game_root: Path, value: int) -> tuple[str, str]:
    if value == 0:
        return "null", ""
    if value in {0xCDCDCDCDCDCDCDCD, 0xDDDDDDDDDDDDDDDD, 0xFEEEFEEEFEEEFEEE}:
        return "sentinel_or_freed_pattern", ""
    m = mapping_for_address(maps, value)
    if m is None:
        return "unmapped", ""
    cls = S164.mapping_class(m, game_root)
    return f"mapped_{cls}", S164.mapping_key(m)


def capture_site_state(reader: Any, maps: Sequence[Any], game_root: Path, sites: Sequence[Mapping[str, Any]], label: str) -> tuple[dict[int, bytes], list[dict[str, Any]]]:
    blobs: dict[int, bytes] = {}
    rows: list[dict[str, Any]] = []
    for s in sites:
        site = int(s["site_address"])
        m = mapping_for_address(maps, site)
        require(m is not None and "r" in m.perms, f"stage165 site no longer readable in {label}: 0x{site:x}")
        require(site - m.start >= LOCAL_FIELD_RADIUS and m.end - site >= LOCAL_FIELD_RADIUS + 8, f"stage165 site too close to mapping boundary for fixed neighborhood in {label}: 0x{site:x}")
        lo = site - LOCAL_FIELD_RADIUS
        hi = site + LOCAL_FIELD_RADIUS + 8
        data = reader.read(lo, hi - lo)
        require(len(data) == hi - lo, f"short neighborhood read at 0x{site:x} in {label}")
        site_off = site - lo
        require(site_off + 8 <= len(data), "site qword outside captured neighborhood")
        pointer = struct.unpack_from("<Q", data, site_off)[0]
        pclass, pkey = pointer_mapping_descriptor(maps, game_root, pointer)
        payload_class, payload_hash = S165.classify_pointed_payload(reader, maps, pointer)
        blobs[site] = data
        rows.append({
            "snapshot": label,
            "site_address_hex": f"0x{site:x}",
            "site_mapping_key": S164.mapping_key(m),
            "site_mapping_relative_offset": site - m.start,
            "pointer_value_hex": f"0x{pointer:x}",
            "pointer_mapping_class": pclass,
            "pointer_target_mapping_key": pkey,
            "pointed_payload_class": payload_class,
            "pointed_payload_sha256": payload_hash,
            "neighborhood_sha256": sha256_bytes(data),
            "raw_neighborhood_exported": False,
        })
    return blobs, rows


def current_dry_anchor_count(site_rows: Sequence[Mapping[str, Any]]) -> int:
    return sum(1 for r in site_rows if r.get("pointed_payload_class") == "points_to_dry_school_token")


def merge_anchor_windows(maps: Sequence[Any], addresses: Sequence[int], radius: int = COMPONENT_WINDOW_RADIUS) -> list[tuple[Any, int, int]]:
    by_map: dict[str, list[tuple[Any, int, int]]] = {}
    for addr in addresses:
        m = mapping_for_address(maps, addr)
        if m is None or "r" not in m.perms:
            continue
        lo = max(m.start, addr - radius)
        hi = min(m.end, addr + radius)
        by_map.setdefault(S164.mapping_key(m), []).append((m, lo, hi))
    out: list[tuple[Any, int, int]] = []
    for entries in by_map.values():
        entries.sort(key=lambda x: x[1])
        m = entries[0][0]
        cur_lo, cur_hi = entries[0][1], entries[0][2]
        for _m, lo, hi in entries[1:]:
            if lo <= cur_hi:
                cur_hi = max(cur_hi, hi)
            else:
                out.append((m, cur_lo, cur_hi)); cur_lo, cur_hi = lo, hi
        out.append((m, cur_lo, cur_hi))
    out.sort(key=lambda x: (x[1], x[2]))
    return out


def _token_boundary_ok(data: bytes, at: int, raw: bytes, spec: ComponentToken, encoding: str) -> bool:
    if not spec.exact_dry_boundary:
        return True
    end = at + len(raw)
    if end >= len(data):
        return True
    if encoding == "ascii":
        nxt = data[end:end+2].lower()
        return not nxt.startswith(b"_w")
    nxt = data[end:end+4]
    return nxt.lower() != "_w".encode("utf-16le")


def scan_component_tokens(reader: Any, maps: Sequence[Any], game_root: Path, addresses: Sequence[int], label: str) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    windows = merge_anchor_windows(maps, addresses)
    total = sum(hi - lo for _m, lo, hi in windows)
    print(f"[stage166] {label}: component-token neighborhood scan planned {total/(1024**2):.1f} MiB across {len(windows)} merged windows", flush=True)
    rows: list[dict[str, Any]] = []
    seen: set[tuple[str, str, int]] = set()
    scanned = 0
    for m, lo, hi in windows:
        pos = lo
        carry = b""
        while pos < hi:
            want = min(COMPONENT_CHUNK_SIZE, hi - pos)
            data = reader.read(pos, want)
            require(data, f"component-token neighborhood read failed at 0x{pos:x}")
            buf = carry + data
            base = pos - len(carry)
            for spec in COMPONENT_TOKENS:
                for encoding, raw in (("ascii", spec.text.encode("ascii")), ("utf16le", spec.text.encode("utf-16le"))):
                    start = 0
                    while True:
                        at = buf.lower().find(raw.lower(), start)
                        if at < 0: break
                        start = at + 1
                        if not _token_boundary_ok(buf, at, raw, spec, encoding):
                            continue
                        addr = base + at
                        if addr < lo or addr >= hi:
                            continue
                        key = (spec.label, encoding, addr)
                        if key in seen: continue
                        seen.add(key)
                        rows.append({
                            "snapshot": label,
                            "token_label": spec.label,
                            "token_text": spec.text,
                            "token_state": spec.state,
                            "component": spec.component,
                            "encoding": encoding,
                            "address_hex": f"0x{addr:x}",
                            "mapping_key": S164.mapping_key(m),
                            "mapping_relative_offset": addr - m.start,
                            "classification": "bounded_anchor_neighborhood_token_residency_not_component_semantics",
                        })
            scanned += len(data)
            keep = min(COMPONENT_OVERLAP, len(buf))
            carry = buf[-keep:]
            pos += len(data)
    return rows, {"window_rows": len(windows), "planned_scan_bytes": total, "bytes_read": scanned, "token_rows": len(rows)}


def _field_slice(blob: bytes, site: int, rel: int, width: int) -> bytes | None:
    # capture_site_state stores [site-radius, site+radius+8]
    idx = LOCAL_FIELD_RADIUS + rel
    if idx < 0 or idx + width > len(blob):
        return None
    return blob[idx:idx+width]


def derive_reversible_fields(
    sites: Sequence[Mapping[str, Any]],
    dry1: Mapping[int, bytes],
    wet: Mapping[int, bytes],
    dry2: Mapping[int, bytes],
    maps_dry1: Sequence[Any], maps_wet: Sequence[Any], maps_dry2: Sequence[Any],
    game_root: Path,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for s in sites:
        site = int(s["site_address"])
        if site not in dry1 or site not in wet or site not in dry2:
            continue
        # qword pointer-like candidates
        for rel in range(-LOCAL_FIELD_RADIUS, LOCAL_FIELD_RADIUS + 1, 8):
            a = _field_slice(dry1[site], site, rel, 8); b = _field_slice(wet[site], site, rel, 8); c = _field_slice(dry2[site], site, rel, 8)
            if a is None or b is None or c is None or a != c or a == b:
                continue
            va, vb, vc = struct.unpack("<Q", a)[0], struct.unpack("<Q", b)[0], struct.unpack("<Q", c)[0]
            ca, ka = pointer_mapping_descriptor(maps_dry1, game_root, va)
            cb, kb = pointer_mapping_descriptor(maps_wet, game_root, vb)
            cc, kc = pointer_mapping_descriptor(maps_dry2, game_root, vc)
            pointerish = any(x.startswith("mapped_") or x in {"null", "sentinel_or_freed_pattern"} for x in (ca, cb, cc))
            if pointerish:
                rows.append({
                    "site_address_hex": f"0x{site:x}", "relative_offset": rel, "field_width": 8,
                    "field_kind": "reversible_qword_pointer_candidate",
                    "dry1_value": f"0x{va:x}", "wet_value": f"0x{vb:x}", "dry2_value": f"0x{vc:x}",
                    "dry1_class": ca, "wet_class": cb, "dry2_class": cc,
                    "dry1_target_mapping_key": ka, "wet_target_mapping_key": kb, "dry2_target_mapping_key": kc,
                    "reversible_roundtrip": True,
                    "classification": "exact_dry1_equals_dry2_wet_differs_pointer_candidate_not_wetness_or_transparency_semantics",
                })
        # dword scalar candidates; exclude offsets already represented as qword start only by allowing both but cap later.
        for rel in range(-LOCAL_FIELD_RADIUS, LOCAL_FIELD_RADIUS + 1, 4):
            a = _field_slice(dry1[site], site, rel, 4); b = _field_slice(wet[site], site, rel, 4); c = _field_slice(dry2[site], site, rel, 4)
            if a is None or b is None or c is None or a != c or a == b:
                continue
            ia, ib, ic = struct.unpack("<I", a)[0], struct.unpack("<I", b)[0], struct.unpack("<I", c)[0]
            # small integers are useful selector/flag candidates; plausible finite floats are useful material/state clues.
            if max(ia, ib, ic) <= 1_000_000:
                rows.append({
                    "site_address_hex": f"0x{site:x}", "relative_offset": rel, "field_width": 4,
                    "field_kind": "reversible_u32_scalar_candidate",
                    "dry1_value": ia, "wet_value": ib, "dry2_value": ic,
                    "dry1_class": "small_u32", "wet_class": "small_u32", "dry2_class": "small_u32",
                    "dry1_target_mapping_key": "", "wet_target_mapping_key": "", "dry2_target_mapping_key": "",
                    "reversible_roundtrip": True,
                    "classification": "exact_dry1_equals_dry2_wet_differs_small_scalar_candidate_not_wetness_or_transparency_semantics",
                })
            fa, fb, fc = struct.unpack("<f", a)[0], struct.unpack("<f", b)[0], struct.unpack("<f", c)[0]
            if all(math.isfinite(x) and abs(x) <= 10000 for x in (fa, fb, fc)) and not (fa == 0.0 and fb == 0.0 and fc == 0.0):
                rows.append({
                    "site_address_hex": f"0x{site:x}", "relative_offset": rel, "field_width": 4,
                    "field_kind": "reversible_f32_scalar_candidate",
                    "dry1_value": f"{fa:.9g}", "wet_value": f"{fb:.9g}", "dry2_value": f"{fc:.9g}",
                    "dry1_class": "finite_f32", "wet_class": "finite_f32", "dry2_class": "finite_f32",
                    "dry1_target_mapping_key": "", "wet_target_mapping_key": "", "dry2_target_mapping_key": "",
                    "reversible_roundtrip": True,
                    "classification": "exact_raw_dry1_equals_dry2_wet_differs_f32_candidate_not_wetness_or_transparency_semantics",
                })
    # deterministic de-dup and cap: pointer candidates first, then small ints, then floats.
    kind_rank = {"reversible_qword_pointer_candidate":0, "reversible_u32_scalar_candidate":1, "reversible_f32_scalar_candidate":2}
    uniq: dict[tuple[Any,...], dict[str,Any]] = {}
    for r in rows:
        key = (r["site_address_hex"], r["relative_offset"], r["field_kind"], r["dry1_value"], r["wet_value"], r["dry2_value"])
        uniq.setdefault(key, r)
    ordered = sorted(uniq.values(), key=lambda r:(kind_rank.get(r["field_kind"],9), r["site_address_hex"], int(r["relative_offset"])))
    return ordered[:MAX_REVERSIBLE_ROWS]


def component_roundtrip_rows(dry1: Sequence[Mapping[str, Any]], wet: Sequence[Mapping[str, Any]], dry2: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    def keyed(rows):
        return {(r["token_label"], r["encoding"], r["mapping_key"], int(r["mapping_relative_offset"])): r for r in rows}
    d1, w, d2 = keyed(dry1), keyed(wet), keyed(dry2)
    allkeys = sorted(set(d1)|set(w)|set(d2))
    out=[]
    for k in allkeys:
        sample = d1.get(k) or w.get(k) or d2.get(k)
        present = (k in d1, k in w, k in d2)
        if present == (False, True, False): cls="wet_only_reversible_residency_candidate_not_component_semantics"
        elif present == (True, False, True): cls="dry_only_reversible_residency_candidate_not_component_semantics"
        elif len(set(present)) > 1: cls="state_dependent_residency_candidate_not_component_semantics"
        else: cls="stable_residency_control"
        out.append({
            "token_label": sample["token_label"], "token_text": sample["token_text"], "component": sample["component"], "encoding": sample["encoding"],
            "mapping_key": sample["mapping_key"], "mapping_relative_offset": sample["mapping_relative_offset"],
            "dry1_present": present[0], "wet_present": present[1], "dry2_present": present[2], "classification": cls,
        })
    return out


def process_public_row(proc: Mapping[str, Any]) -> dict[str, Any]:
    return S164.process_public_row(proc)


def fresh_site_contracts(pointer_rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Deduplicate current-process WET pointer references into fresh site anchors.

    Stage165 absolute addresses are intentionally NOT reused across process restarts.
    """
    by_site: dict[int, dict[str, Any]] = {}
    for r in pointer_rows:
        site = int(r["site_address"])
        by_site.setdefault(site, {
            "site_address": site,
            "site_address_hex": f"0x{site:x}",
            "wet_target_address": int(r["wet_target_address"]),
            "wet_target_address_hex": r.get("wet_target_address_hex", f"0x{int(r['wet_target_address']):x}"),
            "site_mapping_key": r.get("site_mapping_key", ""),
            "site_mapping_relative_offset": int(r.get("site_mapping_relative_offset") or 0),
        })
    return [by_site[k] for k in sorted(by_site)]


def derive_wet_roundtrip_fields(
    sites: Sequence[Mapping[str, Any]],
    wet1: Mapping[int, bytes],
    dry: Mapping[int, bytes],
    wet2: Mapping[int, bytes],
    maps_wet1: Sequence[Any], maps_dry: Sequence[Any], maps_wet2: Sequence[Any],
    game_root: Path,
) -> list[dict[str, Any]]:
    """Report exact WET1==WET2!=DRY typed candidates around reacquired sites."""
    rows: list[dict[str, Any]] = []
    for s in sites:
        site = int(s["site_address"])
        if site not in wet1 or site not in dry or site not in wet2:
            continue
        for rel in range(-LOCAL_FIELD_RADIUS, LOCAL_FIELD_RADIUS + 1, 8):
            a = _field_slice(wet1[site], site, rel, 8)
            b = _field_slice(dry[site], site, rel, 8)
            c = _field_slice(wet2[site], site, rel, 8)
            if a is None or b is None or c is None or a != c or a == b:
                continue
            va, vb, vc = struct.unpack("<Q", a)[0], struct.unpack("<Q", b)[0], struct.unpack("<Q", c)[0]
            ca, ka = pointer_mapping_descriptor(maps_wet1, game_root, va)
            cb, kb = pointer_mapping_descriptor(maps_dry, game_root, vb)
            cc, kc = pointer_mapping_descriptor(maps_wet2, game_root, vc)
            pointerish = any(x.startswith("mapped_") or x in {"null", "sentinel_or_freed_pattern"} for x in (ca, cb, cc))
            if pointerish:
                rows.append({
                    "site_address_hex": f"0x{site:x}", "relative_offset": rel, "field_width": 8,
                    "field_kind": "recurrent_wet_qword_pointer_candidate",
                    "wet1_value": f"0x{va:x}", "dry_value": f"0x{vb:x}", "wet2_value": f"0x{vc:x}",
                    "wet1_class": ca, "dry_class": cb, "wet2_class": cc,
                    "wet1_target_mapping_key": ka, "dry_target_mapping_key": kb, "wet2_target_mapping_key": kc,
                    "wet_roundtrip_recurrent": True,
                    "classification": "exact_wet1_equals_wet2_dry_differs_pointer_candidate_not_wetness_or_transparency_semantics",
                })
        for rel in range(-LOCAL_FIELD_RADIUS, LOCAL_FIELD_RADIUS + 1, 4):
            a = _field_slice(wet1[site], site, rel, 4)
            b = _field_slice(dry[site], site, rel, 4)
            c = _field_slice(wet2[site], site, rel, 4)
            if a is None or b is None or c is None or a != c or a == b:
                continue
            ia, ib, ic = struct.unpack("<I", a)[0], struct.unpack("<I", b)[0], struct.unpack("<I", c)[0]
            if max(ia, ib, ic) <= 1_000_000:
                rows.append({
                    "site_address_hex": f"0x{site:x}", "relative_offset": rel, "field_width": 4,
                    "field_kind": "recurrent_wet_u32_scalar_candidate",
                    "wet1_value": ia, "dry_value": ib, "wet2_value": ic,
                    "wet1_class": "small_u32", "dry_class": "small_u32", "wet2_class": "small_u32",
                    "wet1_target_mapping_key": "", "dry_target_mapping_key": "", "wet2_target_mapping_key": "",
                    "wet_roundtrip_recurrent": True,
                    "classification": "exact_wet1_equals_wet2_dry_differs_small_scalar_candidate_not_wetness_or_transparency_semantics",
                })
            fa, fb, fc = struct.unpack("<f", a)[0], struct.unpack("<f", b)[0], struct.unpack("<f", c)[0]
            if all(math.isfinite(x) and abs(x) <= 10000 for x in (fa, fb, fc)) and not (fa == 0.0 and fb == 0.0 and fc == 0.0):
                rows.append({
                    "site_address_hex": f"0x{site:x}", "relative_offset": rel, "field_width": 4,
                    "field_kind": "recurrent_wet_f32_scalar_candidate",
                    "wet1_value": f"{fa:.9g}", "dry_value": f"{fb:.9g}", "wet2_value": f"{fc:.9g}",
                    "wet1_class": "finite_f32", "dry_class": "finite_f32", "wet2_class": "finite_f32",
                    "wet1_target_mapping_key": "", "dry_target_mapping_key": "", "wet2_target_mapping_key": "",
                    "wet_roundtrip_recurrent": True,
                    "classification": "exact_raw_wet1_equals_wet2_dry_differs_f32_candidate_not_wetness_or_transparency_semantics",
                })
    rank = {"recurrent_wet_qword_pointer_candidate": 0, "recurrent_wet_u32_scalar_candidate": 1, "recurrent_wet_f32_scalar_candidate": 2}
    uniq: dict[tuple[Any, ...], dict[str, Any]] = {}
    for r in rows:
        key = (r["site_address_hex"], r["relative_offset"], r["field_kind"], r["wet1_value"], r["dry_value"], r["wet2_value"])
        uniq.setdefault(key, r)
    return sorted(uniq.values(), key=lambda r: (rank.get(r["field_kind"], 9), r["site_address_hex"], int(r["relative_offset"])))[:MAX_REVERSIBLE_ROWS]


def component_wet_roundtrip_rows(wet1: Sequence[Mapping[str, Any]], dry: Sequence[Mapping[str, Any]], wet2: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    def keyed(rows):
        return {(r["token_label"], r["encoding"], r["mapping_key"], int(r["mapping_relative_offset"])): r for r in rows}
    w1, d, w2 = keyed(wet1), keyed(dry), keyed(wet2)
    allkeys = sorted(set(w1) | set(d) | set(w2))
    out: list[dict[str, Any]] = []
    for k in allkeys:
        sample = w1.get(k) or d.get(k) or w2.get(k)
        present = (k in w1, k in d, k in w2)
        if present == (True, False, True):
            cls = "wet_recurrent_residency_candidate_not_component_semantics"
        elif present == (False, True, False):
            cls = "dry_only_between_wet_captures_candidate_not_component_semantics"
        elif len(set(present)) > 1:
            cls = "state_dependent_residency_candidate_not_component_semantics"
        else:
            cls = "stable_residency_control"
        out.append({
            "token_label": sample["token_label"], "token_text": sample["token_text"], "component": sample["component"], "encoding": sample["encoding"],
            "mapping_key": sample["mapping_key"], "mapping_relative_offset": sample["mapping_relative_offset"],
            "wet1_present": present[0], "dry_present": present[1], "wet2_present": present[2], "classification": cls,
        })
    return out


def run_trace(project_root: Path, game_root: Path, *, interactive: bool = True) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    historical, baseline = verify_prerequisites(project_root, game_root)
    proc = S164.discover_game_process(game_root)
    pid = int(proc["pid"])

    def ensure_alive() -> None:
        require((Path("/proc") / str(pid)).is_dir(), "game process exited during stage166 reacquisition trace")

    if interactive:
        print("\n[stage166] SELF-CONTAINED REACQUISITION: the old stage165 PID is NOT reused.")
        print("[stage166] Prepare Hinako / native School Uniform / DRY in the current Quartet process.")
        input("[stage166] Keep the game idle and press Enter to capture DRY1 discovery baseline... ")
    ensure_alive()
    dry_maps = S164.read_maps(pid)
    with S164.ProcessMemoryReader(pid) as reader:
        dry_model_rows, dry_discovery_stats = S165.scan_wet_model_token(reader, dry_maps, game_root, "dry1_reacquire")

    if interactive:
        print(f"[stage166] DRY1 discovery complete: {len(dry_model_rows)} exact wet-model token copies.")
        print("[stage166] Use native Change Wetness only: DRY -> WET. Clothing, body/skin and hair may all change; keep the same character/costume/menu.")
        input("[stage166] Press Enter when WET is fully visible... ")
    ensure_alive()
    wet_maps1 = S164.read_maps(pid)
    with S164.ProcessMemoryReader(pid) as reader:
        wet_model_rows, wet_discovery_stats = S165.scan_wet_model_token(reader, wet_maps1, game_root, "wet1_reacquire")
        dynamic = S165.dynamic_wet_occurrences(dry_model_rows, wet_model_rows)
        pointer_rows, pointer_stats = S165.scan_pointers_to_dynamic_wet(reader, wet_maps1, game_root, dynamic)

    sites = fresh_site_contracts(pointer_rows)
    if not sites:
        baseline_after = sha256_file(game_root / "Data/PACK10_02.PAK")
        require(baseline_after == baseline == PACK10_02_BASELINE_SHA256, "PACK10_02 changed during read-only trace")
        stats = {
            "pid": pid, "baseline_before": baseline, "baseline_after": baseline_after,
            "historical_stage165_pid": int(historical["summary"]["pid"]),
            "current_pid_reacquired": pid,
            "dry_discovery_stats": dry_discovery_stats, "wet_discovery_stats": wet_discovery_stats,
            "pointer_stats": pointer_stats, "dynamic_rows": len(dynamic), "site_rows": 0,
            "dry_anchor_count": 0,
        }
        return proc, stats, [], [], [], [], [], dynamic, pointer_rows

    with S164.ProcessMemoryReader(pid) as reader:
        wet1_blobs, wet1_sites = capture_site_state(reader, wet_maps1, game_root, sites, "wet1")
        addresses = [int(x["site_address"]) for x in sites] + [int(x["wet_target_address"]) for x in sites]
        comp_wet1, comp_stats_wet1 = scan_component_tokens(reader, wet_maps1, game_root, addresses, "wet1")

    if interactive:
        print(f"[stage166] Reacquired {len(sites)} fresh current-process pointer site(s).")
        print("[stage166] Toggle native Change Wetness WET -> DRY; keep Hinako / School Uniform and the same menu.")
        input("[stage166] Press Enter when DRY is fully visible... ")
    ensure_alive()
    dry_maps2 = S164.read_maps(pid)
    with S164.ProcessMemoryReader(pid) as reader:
        dry_blobs, dry_sites = capture_site_state(reader, dry_maps2, game_root, sites, "dry2")
        comp_dry, comp_stats_dry = scan_component_tokens(reader, dry_maps2, game_root, addresses, "dry2")
    dry_anchor_count = current_dry_anchor_count(dry_sites)

    if interactive:
        print(f"[stage166] DRY captured; {dry_anchor_count} site(s) point into a dry school-token neighborhood.")
        print("[stage166] Toggle native Change Wetness DRY -> WET once more for the recurrence control.")
        input("[stage166] Press Enter when WET is fully visible again... ")
    ensure_alive()
    wet_maps2 = S164.read_maps(pid)
    with S164.ProcessMemoryReader(pid) as reader:
        wet2_blobs, wet2_sites = capture_site_state(reader, wet_maps2, game_root, sites, "wet2")
        comp_wet2, comp_stats_wet2 = scan_component_tokens(reader, wet_maps2, game_root, addresses, "wet2")

    reversible = derive_wet_roundtrip_fields(sites, wet1_blobs, dry_blobs, wet2_blobs, wet_maps1, dry_maps2, wet_maps2, game_root)
    comp_roundtrip = component_wet_roundtrip_rows(comp_wet1, comp_dry, comp_wet2)
    baseline_after = sha256_file(game_root / "Data/PACK10_02.PAK")
    require(baseline_after == baseline == PACK10_02_BASELINE_SHA256, "PACK10_02 changed during read-only trace")
    stats = {
        "pid": pid, "baseline_before": baseline, "baseline_after": baseline_after,
        "historical_stage165_pid": int(historical["summary"]["pid"]),
        "current_pid_reacquired": pid,
        "dry_discovery_stats": dry_discovery_stats, "wet_discovery_stats": wet_discovery_stats,
        "pointer_stats": pointer_stats, "dynamic_rows": len(dynamic), "site_rows": len(sites),
        "dry_anchor_count": dry_anchor_count,
        "wet1_component_stats": comp_stats_wet1, "dry_component_stats": comp_stats_dry, "wet2_component_stats": comp_stats_wet2,
    }
    return proc, stats, wet1_sites, dry_sites, wet2_sites, reversible, comp_roundtrip, dynamic, pointer_rows


def build_report(project_root: Path, game_root: Path, *, interactive: bool = True, report_root: Path | None = None, output_report_root: Path | None = None, create_archive: bool = True) -> tuple[Path | None, dict[str, Any]]:
    project_root = S164.safe_resolve(project_root); game_root = S164.safe_resolve(game_root)
    report_root = report_root or project_root / ".local/reports/quartet_restoration" / REPORT_DIR
    output_report_root = output_report_root or project_root / ".local/reports/quartet_restoration"
    out = report_root
    if out.exists():
        import shutil; shutil.rmtree(out)
    out.mkdir(parents=True, exist_ok=True)

    proc, stats, wet1_sites, dry_sites, wet2_sites, reversible, comp_roundtrip, dynamic, pointer_rows = run_trace(project_root, game_root, interactive=interactive)
    reversible_ptr = [r for r in reversible if r["field_kind"] == "recurrent_wet_qword_pointer_candidate"]
    reversible_scalar = [r for r in reversible if r["field_kind"] != "recurrent_wet_qword_pointer_candidate"]
    wet_body = [r for r in comp_roundtrip if r["component"] == "body_skin" and r["wet1_present"] and not r["dry_present"] and r["wet2_present"]]
    wet_face = [r for r in comp_roundtrip if r["component"] == "face_rig" and r["wet1_present"] and not r["dry_present"] and r["wet2_present"]]
    wet_school = [r for r in comp_roundtrip if r["component"] == "school_costume" and r["wet1_present"] and not r["dry_present"] and r["wet2_present"]]

    if reversible_ptr:
        quality = "fresh_process_reacquired_recurrent_wet_pointer_candidates_observed"
        next_action = "Use only fresh-process recurrent exact pointer candidates and synchronized component residency as bounded anchors for render-resource/material binding capture; do not write memory or assign transparency semantics."
    elif reversible_scalar:
        quality = "fresh_process_reacquired_recurrent_wet_scalar_candidates_observed"
        next_action = "Use only exact WET1==WET2!=DRY scalar sites as observational anchors; prefer render-resource/material binding capture before any write."
    elif pointer_rows:
        quality = "fresh_process_pointer_sites_reacquired_without_recurrent_typed_field_candidate"
        next_action = "Stop local memory-field probing and move to render-state/resource-binding capture at native Change Wetness using the fresh pointer sites only as timing/object-neighborhood anchors."
    else:
        quality = "fresh_process_wet_model_pointer_sites_not_reacquired"
        next_action = "Do not reuse stale addresses. Move to render-state/resource-binding capture; repeat this discovery only if the native state/costume was uncertain."

    summary = {
        "format_version": 1,
        "type": "br_quartet_restoration_wet_character_compound_state_neighborhood_evidence_summary",
        "tool_version": TOOL_VERSION,
        "stage": STAGE,
        "status": "fresh_process_reacquisition_wet_character_compound_state_trace_complete_read_only",
        "stage165_report_sha256": STAGE165_SHA256,
        "historical_stage165_pid": stats["historical_stage165_pid"],
        "current_pid": stats["current_pid_reacquired"],
        "historical_stage165_absolute_addresses_reused": False,
        "fresh_process_anchor_reacquisition_performed": True,
        "capture_sequence": "current DRY1 discovery -> native WET1 discovery/anchor capture -> native DRY2 local capture -> native WET2 recurrence capture",
        "new_wet_model_residency_rows": stats["dynamic_rows"],
        "fresh_exact_pointer_reference_rows": len(pointer_rows),
        "fresh_anchor_site_rows": stats["site_rows"],
        "dry_verified_dry_anchor_rows": stats["dry_anchor_count"],
        "recurrent_wet_typed_field_rows": len(reversible),
        "recurrent_wet_pointer_candidate_rows": len(reversible_ptr),
        "recurrent_wet_scalar_candidate_rows": len(reversible_scalar),
        "wet_recurrent_school_component_token_rows": len(wet_school),
        "wet_recurrent_body_skin_component_token_rows": len(wet_body),
        "wet_recurrent_face_rig_component_token_rows": len(wet_face),
        "hair_visual_wetness_user_observed": True,
        "hair_separate_asset_binding_confirmed": False,
        "body_skin_visual_wetness_user_observed": True,
        "compound_wetness_visual_observation_scope": "clothing + body/skin + hair",
        "component_token_scan_scope": "bounded merged windows around fresh current-process pointer sites and wet targets only",
        "absence_of_component_token_not_global_absence": True,
        "pack10_02_baseline_before_sha256": stats["baseline_before"],
        "pack10_02_baseline_after_sha256": stats["baseline_after"],
        "runtime_process_memory_read": True,
        "runtime_process_memory_written": False,
        "ptrace_or_debugger_write_performed": False,
        "raw_process_memory_exported": False,
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
    }

    public_proc = process_public_row(proc)
    write_tsv(out / "PROCESS.tsv", list(public_proc.keys()), [public_proc])
    token_fields = ["snapshot","address_hex","mapping_index","mapping_key","mapping_class","mapping_permissions","mapping_path_basename","mapping_path_sha256","mapping_relative_offset","context_sha256","classification"]
    write_tsv(out / "NEW_WET_MODEL_RESIDENCY.tsv", token_fields, [{k:v for k,v in r.items() if k != "address"} for r in dynamic])
    ptr_fields = ["site_address_hex","site_mapping_index","site_mapping_key","site_mapping_class","site_mapping_permissions","site_mapping_path_basename","site_mapping_path_sha256","site_mapping_relative_offset","wet_site_context_sha256","wet_target_address_hex","wet_target_mapping_key","wet_target_mapping_relative_offset","classification"]
    write_tsv(out / "FRESH_WET_MODEL_POINTER_REFERENCES.tsv", ptr_fields, [{k:v for k,v in r.items() if k not in {"site_address","wet_target_address"}} for r in pointer_rows])
    site_fields = ["snapshot","site_address_hex","site_mapping_key","site_mapping_relative_offset","pointer_value_hex","pointer_mapping_class","pointer_target_mapping_key","pointed_payload_class","pointed_payload_sha256","neighborhood_sha256","raw_neighborhood_exported"]
    write_tsv(out / "ANCHOR_SITE_STATES.tsv", site_fields, [*wet1_sites,*dry_sites,*wet2_sites])
    field_fields = ["site_address_hex","relative_offset","field_width","field_kind","wet1_value","dry_value","wet2_value","wet1_class","dry_class","wet2_class","wet1_target_mapping_key","dry_target_mapping_key","wet2_target_mapping_key","wet_roundtrip_recurrent","classification"]
    write_tsv(out / "RECURRENT_WET_TYPED_FIELDS.tsv", field_fields, reversible)
    comp_fields = ["token_label","token_text","component","encoding","mapping_key","mapping_relative_offset","wet1_present","dry_present","wet2_present","classification"]
    write_tsv(out / "COMPONENT_TOKEN_WET_ROUNDTRIP.tsv", comp_fields, comp_roundtrip)
    (out / "SUMMARY.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    archive = output_report_root / REPORT_NAME if create_archive else None
    if archive is not None: make_archive(out, archive)
    return archive, summary


def probe(project_root: Path, game_root: Path) -> dict[str, Any]:
    _historical, _baseline = verify_prerequisites(project_root, game_root)
    proc = S164.discover_game_process(game_root)
    maps = S164.read_maps(int(proc["pid"]))
    ok, reason = S164._probe_memory_access(int(proc["pid"]), maps, game_root)
    return {"pid": proc["pid"], "memory_readable": ok, "reason": reason, "fresh_process_reacquisition": True}


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    ap = argparse.ArgumentParser()
    ap.add_argument("project_root", type=Path)
    ap.add_argument("--game-root", type=Path, required=True)
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
            result = probe(project_root, game_root)
            print(json.dumps(result, sort_keys=True))
            return 0 if result["memory_readable"] else ACCESS_DENIED_EXIT
        archive, summary = build_report(project_root, game_root, interactive=not a.no_interactive, report_root=a.report_root, output_report_root=a.output_report_root, create_archive=not a.no_archive)
        print(json.dumps(summary, indent=2, sort_keys=True))
        if archive: print(f"[stage166] evidence: {archive}")
        return 0
    except PermissionError as exc:
        print(f"[stage166] process-memory permission denied: {exc}", file=sys.stderr)
        return ACCESS_DENIED_EXIT
    except Stage166Error as exc:
        print(f"[stage166] ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
