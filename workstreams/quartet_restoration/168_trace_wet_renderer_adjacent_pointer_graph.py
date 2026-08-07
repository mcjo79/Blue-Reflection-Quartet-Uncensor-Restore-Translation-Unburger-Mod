#!/usr/bin/env python3
"""Stage 168: recurrent wet-school renderer-adjacent pointer graph trace (read-only).

Stage 167 established two strong fresh recurrent pointer chains whose DRY targets
were native PC00 school resources and whose WET targets contained
PC00_Scl_W.g1m / PC00_Scl_W_default.g1m.  Stage 168 does not reuse a stage-167
PID or absolute address.  It freshly reacquires stage-166-class anchors, then
selects current-process WET1 pointer-root candidates that directly expose the
native wet-school model tokens.  WET2 then filters those candidates for actual
wet-school recurrence; transient neighborhood roots are recorded and rejected
without aborting the trace.  Recurrent roots are followed through a bounded
pointer graph (maximum three hops) in WET1, DRY2 and WET2.

Evidence contains only hashes, mapping-relative descriptors, relative edge
offsets and allowlisted asset/technical tokens.  It never exports a PID,
absolute pointer/address, raw process memory, full process path or command line.
No process memory or game file is written.

A recurrent pointer-graph path to G1T/G1S or material/shader/texture terminology
is renderer-adjacent evidence only.  It does not by itself prove an active
material binding or transparency semantics.
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
from collections import deque
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

TOOL_VERSION = "0.1.93"
STAGE = 168
REPORT_DIR = "wet_renderer_adjacent_pointer_graph_evidence"
REPORT_NAME = "BR_quartet_restoration_wet_renderer_adjacent_pointer_graph_evidence.tar.zst"
STAGE167_REPORT = "BR_quartet_restoration_wet_render_resource_material_binding_trace_evidence.tar.zst"
STAGE167_SHA256 = "81e749680b78804802703dda0735911883f7be5335f7fd7553427fd2d484d55a"
PACK10_02_BASELINE_SHA256 = "e798f39c3bcdbb11381197bddf9bd3ad8de6ccf5d7c0c78b22613046d47f5302"
ACCESS_DENIED_EXIT = 77
GRAPH_RADIUS = 768
CHILD_PREVIEW_RADIUS = 256
MAX_DEPTH = 3
MAX_FANOUT = 24
MAX_GRAPH_NODES = 96
WET_MODEL_MARKERS = {"PC00_Scl_W.g1m", "PC00_Scl_W_default.g1m"}
RENDER_TERMS = {"material", "shader", "texture", "sampler", "blend", "alpha"}
RENDER_ASSET_SUFFIXES = (".g1t", ".g1s")


class Stage168Error(RuntimeError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise Stage168Error(message)


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


def make_archive(source: Path, output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    tmp = output.with_name(output.name + ".tmp")
    tmp.unlink(missing_ok=True)
    cp = subprocess.run(["tar", "--zstd", "-cf", str(tmp), "-C", str(source.parent), source.name], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    require(cp.returncode == 0, cp.stderr.decode("utf-8", errors="replace").strip() or "archive creation failed")
    os.replace(tmp, output)


def _load_stage167():
    path = Path(__file__).with_name("167_trace_wet_render_resource_material_binding.py")
    spec = importlib.util.spec_from_file_location("br_restoration_stage167_for168", path)
    require(spec is not None and spec.loader is not None, "cannot load stage167 helper")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


S167 = _load_stage167()
S166 = S167.S166
S165 = S167.S165
S164 = S167.S164


def _archive_member_bytes(archive: Path, suffix: str) -> bytes:
    cp = subprocess.run(["tar", "--zstd", "-tf", str(archive)], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    require(cp.returncode == 0, cp.stderr.decode("utf-8", errors="replace").strip() or "cannot list stage167 archive")
    names = cp.stdout.decode("utf-8", errors="replace").splitlines()
    matches = [n for n in names if n.endswith("/" + suffix) or n == suffix]
    require(len(matches) == 1, f"stage167 archive expected exactly one {suffix}, found {len(matches)}")
    cp = subprocess.run(["tar", "--zstd", "-xOf", str(archive), matches[0]], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    require(cp.returncode == 0, cp.stderr.decode("utf-8", errors="replace").strip() or f"cannot read {suffix} from stage167 archive")
    return cp.stdout


def verify_stage167_contract(project_root: Path) -> dict[str, Any]:
    archive = project_root / ".local/reports/quartet_restoration" / STAGE167_REPORT
    require(archive.is_file(), f"missing canonical stage167 report: {archive}")
    actual = sha256_file(archive)
    require(actual == STAGE167_SHA256, f"stage167 report SHA-256 drift: {actual}")
    summary = json.loads(_archive_member_bytes(archive, "SUMMARY.json").decode("utf-8"))
    require(summary.get("stage") == 167, "stage167 SUMMARY stage drift")
    require(summary.get("fresh_process_anchor_reacquisition_performed") is True, "stage167 did not freshly reacquire anchors")
    require(summary.get("stage166_historical_pid_reused") is False, "stage167 reused historical PID")
    require(summary.get("stage166_historical_absolute_addresses_reused") is False, "stage167 reused historical absolute addresses")
    require(int(summary.get("wet_only_asset_token_candidate_rows", 0)) >= 2, "stage167 has fewer than two wet-only asset-token candidates")
    require(summary.get("material_binding_confirmed") is False, "stage167 unexpectedly claims material binding")
    candidates = list(csv.DictReader(_archive_member_bytes(archive, "RECURRENT_POINTER_RESOURCE_BINDING_CANDIDATES.tsv").decode("utf-8").splitlines(), delimiter="\t"))
    strong = [r for r in candidates if "PC00_Scl_W.g1m" in r.get("wet_only_asset_tokens", "") and r.get("target_state_distinct") == "True"]
    require(len(strong) >= 2, f"stage167 expected >=2 recurrent PC00_Scl_W wet-only chains, found {len(strong)}")
    return summary


def verify_prerequisites(project_root: Path, game_root: Path) -> tuple[dict[str, Any], str]:
    summary = verify_stage167_contract(project_root)
    pak = game_root / "Data/PACK10_02.PAK"
    require(pak.is_file(), f"missing Quartet PACK10_02: {pak}")
    baseline = sha256_file(pak)
    require(baseline == PACK10_02_BASELINE_SHA256, f"PACK10_02 is not exact baseline: {baseline}")
    return summary, baseline


def _read_node_window(reader: Any, maps: Sequence[Any], address: int, radius: int = GRAPH_RADIUS) -> tuple[Any | None, int, bytes]:
    m = S166.mapping_for_address(maps, address)
    if m is None or "r" not in m.perms:
        return None, 0, b""
    lo = max(m.start, address - radius)
    hi = min(m.end, address + radius)
    if hi <= lo:
        return m, lo, b""
    try:
        data = reader.read(lo, hi - lo)
    except (OSError, PermissionError):
        return m, lo, b""
    if len(data) != hi - lo:
        return m, lo, b""
    return m, lo, data


def _node_public(m: Any, game_root: Path, address: int, data: bytes) -> dict[str, Any]:
    cls, base, path_hash = S164.normalized_mapping_path(m, game_root)
    assets, terms = S167.extract_allowlisted_tokens(data)
    return {
        "mapping_key": S164.mapping_key(m),
        "mapping_class": cls,
        "mapping_permissions": m.perms,
        "mapping_path_basename": base,
        "mapping_path_sha256": path_hash,
        "mapping_relative_offset": address - m.start,
        "context_sha256": hashlib.sha256(data).hexdigest() if data else "",
        "asset_tokens": assets,
        "technical_terms": terms,
    }


def direct_wet_model_root_candidates(reader: Any, maps: Sequence[Any], game_root: Path, sites: Sequence[Mapping[str, Any]], wet_blobs: Mapping[int, bytes]) -> list[dict[str, Any]]:
    """Select only current-process qword roots directly exposing wet school model tokens."""
    rows: list[dict[str, Any]] = []
    seen: set[tuple[int, int]] = set()
    for site in sites:
        addr = int(site["site_address"])
        blob = wet_blobs.get(addr)
        if not blob:
            continue
        for rel in range(-S166.LOCAL_FIELD_RADIUS, S166.LOCAL_FIELD_RADIUS + 1, 8):
            raw = S166._field_slice(blob, addr, rel, 8)
            if raw is None:
                continue
            pointer = struct.unpack("<Q", raw)[0]
            m, _lo, data = _read_node_window(reader, maps, pointer, S167.TARGET_RADIUS)
            if m is None or not data:
                continue
            assets, terms = S167.extract_allowlisted_tokens(data)
            if not (WET_MODEL_MARKERS & set(assets)):
                continue
            key = (addr, rel)
            if key in seen:
                continue
            seen.add(key)
            rows.append({
                "site_address": addr,
                "anchor_descriptor": S167.safe_site_id(site),
                "relative_offset": rel,
                "pointer": pointer,
                "direct_asset_tokens": assets,
                "direct_technical_terms": terms,
            })
    return rows


def pointer_at_field(blob: bytes, site_addr: int, rel: int) -> int | None:
    raw = S166._field_slice(blob, site_addr, rel, 8)
    return struct.unpack("<Q", raw)[0] if raw is not None else None




def classify_wet2_root_target(reader: Any, maps: Sequence[Any], game_root: Path, pointer: int | None) -> tuple[str, list[str], list[str]]:
    """Classify one WET2 root without making candidate drift fatal.

    WET1 root discovery intentionally starts from a wider local neighborhood than
    the already-proven recurrent fields.  A transient WET1 pointer is therefore a
    candidate to reject, not a reason to abort the entire trace.
    """
    if pointer is None:
        return "missing_field", [], []
    m, _lo, data = _read_node_window(reader, maps, pointer, S167.TARGET_RADIUS)
    if m is None or not data:
        return "unreadable_target", [], []
    assets, terms = S167.extract_allowlisted_tokens(data)
    if WET_MODEL_MARKERS & set(assets):
        return "recurrent_wet_school", assets, terms
    return "non_wet_school_target", assets, terms

def graph_terminal_key(row: Mapping[str, Any]) -> str:
    material = "|".join([
        str(row.get("depth", "")),
        str(row.get("edge_relative_path", "")),
        str(row.get("asset_tokens", "")),
        str(row.get("technical_terms", "")),
        str(row.get("mapping_class", "")),
    ])
    return sha256_text(material)[:24]


def trace_pointer_graph(reader: Any, maps: Sequence[Any], game_root: Path, root_pointer: int, *, state: str, root_id: str) -> list[dict[str, Any]]:
    """Bounded graph traversal; exports only relative edge paths and safe tokens."""
    rows: list[dict[str, Any]] = []
    q: deque[tuple[int, int, tuple[int, ...]]] = deque([(root_pointer, 0, tuple())])
    visited: set[int] = set()
    while q and len(visited) < MAX_GRAPH_NODES:
        address, depth, edge_path = q.popleft()
        if address in visited:
            continue
        visited.add(address)
        m, lo, data = _read_node_window(reader, maps, address)
        if m is None or not data:
            continue
        pub = _node_public(m, game_root, address, data)
        assets = list(pub["asset_tokens"])
        terms = list(pub["technical_terms"])
        render_assets = [a for a in assets if a.casefold().endswith(RENDER_ASSET_SUFFIXES)]
        render_terms = sorted(set(terms) & RENDER_TERMS)
        row = {
            "root_id": root_id,
            "state": state,
            "depth": depth,
            "edge_relative_path": ";".join(str(x) for x in edge_path),
            "mapping_key": pub["mapping_key"],
            "mapping_class": pub["mapping_class"],
            "mapping_permissions": pub["mapping_permissions"],
            "mapping_path_basename": pub["mapping_path_basename"],
            "mapping_path_sha256": pub["mapping_path_sha256"],
            "mapping_relative_offset": pub["mapping_relative_offset"],
            "context_sha256": pub["context_sha256"],
            "asset_tokens": ";".join(assets),
            "technical_terms": ";".join(terms),
            "render_asset_tokens": ";".join(render_assets),
            "render_technical_terms": ";".join(render_terms),
            "renderer_adjacent": bool(render_assets or render_terms),
            "absolute_address_exported": False,
        }
        row["terminal_key"] = graph_terminal_key(row)
        rows.append(row)
        if depth >= MAX_DEPTH:
            continue
        children: list[tuple[int, int, int]] = []
        seen_child: set[int] = set()
        for off in range(0, len(data) - 7, 8):
            child = struct.unpack_from("<Q", data, off)[0]
            if child == address or child in visited or child in seen_child:
                continue
            cm = S166.mapping_for_address(maps, child)
            if cm is None or "r" not in cm.perms:
                continue
            seen_child.add(child)
            # Prefer edges near the current root and children with safe render/resource tokens.
            _cm, _clo, preview = _read_node_window(reader, maps, child, CHILD_PREVIEW_RADIUS)
            pa, pt = S167.extract_allowlisted_tokens(preview) if preview else ([], [])
            priority = 0 if (pa or pt) else 1
            edge_rel = (lo + off) - address
            children.append((priority, abs(edge_rel), edge_rel, child))
        children.sort(key=lambda x: (x[0], x[1], x[2]))
        for _priority, _dist, edge_rel, child in children[:MAX_FANOUT]:
            q.append((child, depth + 1, edge_path + (edge_rel,)))
    return rows


def recurrent_renderer_rows(wet1: Sequence[Mapping[str, Any]], dry2: Sequence[Mapping[str, Any]], wet2: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    def semantic_key(r: Mapping[str, Any]) -> tuple[str, str, str, int]:
        return (
            str(r.get("edge_relative_path", "")),
            str(r.get("render_asset_tokens", "")),
            str(r.get("render_technical_terms", "")),
            int(r.get("depth", 0)),
        )
    w1 = {semantic_key(r): r for r in wet1 if r.get("renderer_adjacent")}
    d2 = {semantic_key(r): r for r in dry2 if r.get("renderer_adjacent")}
    w2 = {semantic_key(r): r for r in wet2 if r.get("renderer_adjacent")}
    rows: list[dict[str, Any]] = []
    for key in sorted(set(w1) & set(w2)):
        if key in d2:
            continue
        a, b = w1[key], w2[key]
        rows.append({
            "root_id": a.get("root_id", ""),
            "depth": key[3],
            "edge_relative_path": key[0],
            "wet_render_asset_tokens": key[1],
            "wet_render_technical_terms": key[2],
            "wet1_context_sha256": a.get("context_sha256", ""),
            "wet2_context_sha256": b.get("context_sha256", ""),
            "same_context_hash_wet1_wet2": a.get("context_sha256", "") == b.get("context_sha256", ""),
            "g1t_or_g1s_supported": bool(key[1]),
            "material_shader_term_supported": bool(set(filter(None, key[2].split(";"))) & {"material", "shader", "texture", "sampler", "blend", "alpha"}),
            "render_resource_binding_confirmed": False,
            "material_binding_confirmed": False,
            "shader_binding_confirmed": False,
            "texture_binding_confirmed": False,
            "transparency_semantics_confirmed": False,
        })
    return rows


def run_trace(project_root: Path, game_root: Path, *, interactive: bool = True, initial_ready: bool = False) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    stage167_summary, baseline = verify_prerequisites(project_root, game_root)
    proc = S164.discover_game_process(game_root)
    pid = int(proc["pid"])

    def ensure_alive() -> None:
        require((Path("/proc") / str(pid)).is_dir(), "game process exited during stage168 trace")

    if interactive:
        print("\n[stage168] NEW PROCESS: no stage167 PID or absolute address is reused.")
        if initial_ready:
            print("[stage168] Launcher already confirmed Hinako / native School Uniform / DRY. Capturing DRY1 now.")
        else:
            print("[stage168] Prepare Hinako / native School Uniform / DRY. This trace follows only fresh wet-school model resource roots.")
            input("[stage168] Press Enter to capture DRY1 discovery baseline... ")
    ensure_alive()
    dry_maps1 = S164.read_maps(pid)
    with S164.ProcessMemoryReader(pid) as reader:
        dry_model_rows, _ = S165.scan_wet_model_token(reader, dry_maps1, game_root, "stage168_dry1")

    if interactive:
        print("[stage168] Use native Change Wetness: DRY -> WET.")
        input("[stage168] Press Enter when WET is fully visible... ")
    ensure_alive()
    wet_maps1 = S164.read_maps(pid)
    with S164.ProcessMemoryReader(pid) as reader:
        wet_model_rows, _ = S165.scan_wet_model_token(reader, wet_maps1, game_root, "stage168_wet1")
        dynamic = S165.dynamic_wet_occurrences(dry_model_rows, wet_model_rows)
        pointer_rows, _ = S165.scan_pointers_to_dynamic_wet(reader, wet_maps1, game_root, dynamic)
        sites = S166.fresh_site_contracts(pointer_rows)
        require(sites, "fresh stage166-class anchors were not reacquired; no historical address will be substituted")
        wet1_blobs, _ = S166.capture_site_state(reader, wet_maps1, game_root, sites, "stage168_wet1")
        roots = direct_wet_model_root_candidates(reader, wet_maps1, game_root, sites, wet1_blobs)
        require(roots, "no current-process wet-school model root candidate found")
        # Keep one root per unique current wet pointer to avoid duplicate anchor aliases.
        dedup: dict[int, dict[str, Any]] = {}
        for r in roots:
            dedup.setdefault(int(r["pointer"]), r)
        roots = list(dedup.values())
        wet1_graph_by_root: dict[str, list[dict[str, Any]]] = {}
        for idx, root in enumerate(roots, 1):
            root_id = f"wet_school_root_{idx:02d}"
            root["root_id"] = root_id
            wet1_graph_by_root[root_id] = trace_pointer_graph(reader, wet_maps1, game_root, int(root["pointer"]), state="wet1", root_id=root_id)

    if interactive:
        print(f"[stage168] Reacquired {len(sites)} anchor(s), narrowed to {len(roots)} unique wet-school root(s). Toggle WET -> DRY.")
        input("[stage168] Press Enter when DRY is fully visible... ")
    ensure_alive()
    dry_maps2 = S164.read_maps(pid)
    dry_graph_by_root: dict[str, list[dict[str, Any]]] = {}
    with S164.ProcessMemoryReader(pid) as reader:
        dry_blobs, _ = S166.capture_site_state(reader, dry_maps2, game_root, sites, "stage168_dry2")
        for root in roots:
            site_addr = int(root["site_address"])
            rel = int(root["relative_offset"])
            pointer = pointer_at_field(dry_blobs[site_addr], site_addr, rel)
            require(pointer is not None, "candidate root field missing in DRY2")
            root["dry2_pointer"] = pointer
            dry_graph_by_root[root["root_id"]] = trace_pointer_graph(reader, dry_maps2, game_root, pointer, state="dry2", root_id=root["root_id"])

    if interactive:
        print("[stage168] DRY graph captured. Toggle DRY -> WET once more.")
        input("[stage168] Press Enter when WET is fully visible again... ")
    ensure_alive()
    wet_maps2 = S164.read_maps(pid)
    graph_rows: list[dict[str, Any]] = []
    recurrent_rows: list[dict[str, Any]] = []
    root_public: list[dict[str, Any]] = []
    wet2_recurrent_root_rows = 0
    wet2_rejected_root_rows = 0
    with S164.ProcessMemoryReader(pid) as reader:
        wet2_blobs, _ = S166.capture_site_state(reader, wet_maps2, game_root, sites, "stage168_wet2")
        for root in roots:
            site_addr = int(root["site_address"])
            rel = int(root["relative_offset"])
            wet2_pointer = pointer_at_field(wet2_blobs[site_addr], site_addr, rel)
            status, wet2_assets, wet2_terms = classify_wet2_root_target(reader, wet_maps2, game_root, wet2_pointer)
            w1 = wet1_graph_by_root[root["root_id"]]
            d2 = dry_graph_by_root[root["root_id"]]
            # WET1 roots are candidates from a bounded neighborhood.  Preserve
            # their WET1/DRY2 observations even when an individual field drifts
            # by WET2; only recurrent wet-school roots proceed to WET2 graphing.
            graph_rows.extend(w1)
            graph_rows.extend(d2)
            exact_recurrence = bool(wet2_pointer is not None and int(wet2_pointer) == int(root["pointer"]))
            if status == "recurrent_wet_school":
                wet2_recurrent_root_rows += 1
                wet2_graph = trace_pointer_graph(reader, wet_maps2, game_root, int(wet2_pointer), state="wet2", root_id=root["root_id"])
                graph_rows.extend(wet2_graph)
                recurrent_rows.extend(recurrent_renderer_rows(w1, d2, wet2_graph))
            else:
                wet2_rejected_root_rows += 1
            root_public.append({
                "root_id": root["root_id"],
                "anchor_descriptor": root["anchor_descriptor"],
                "relative_offset": rel,
                "wet1_direct_asset_tokens": ";".join(root["direct_asset_tokens"]),
                "wet1_direct_technical_terms": ";".join(root["direct_technical_terms"]),
                "wet2_root_status": status,
                "wet2_recurrent_wet_school": status == "recurrent_wet_school",
                "wet2_direct_asset_tokens": ";".join(wet2_assets),
                "wet2_direct_technical_terms": ";".join(wet2_terms),
                "dry2_pointer_differs_from_wet1": int(root.get("dry2_pointer", 0)) != int(root["pointer"]),
                "wet1_wet2_exact_pointer_recurrence": exact_recurrence,
                "absolute_pointer_exported": False,
            })
        if interactive:
            print(f"[stage168] WET2 root filter: {wet2_recurrent_root_rows}/{len(roots)} recurrent wet-school; {wet2_rejected_root_rows} transient/nonmatching candidate(s) rejected without aborting.")

    baseline_after = sha256_file(game_root / "Data/PACK10_02.PAK")
    require(baseline_after == baseline == PACK10_02_BASELINE_SHA256, "PACK10_02 changed during read-only stage168 trace")
    stats = {
        "stage167_wet_only_asset_token_candidate_rows": int(stage167_summary.get("wet_only_asset_token_candidate_rows", 0)),
        "fresh_dynamic_wet_model_rows": len(dynamic),
        "fresh_pointer_reference_rows": len(pointer_rows),
        "fresh_anchor_site_rows": len(sites),
        "fresh_unique_wet_school_root_rows": len(roots),
        "wet2_recurrent_wet_school_root_rows": wet2_recurrent_root_rows,
        "wet2_rejected_root_rows": wet2_rejected_root_rows,
        "pointer_graph_observation_rows": len(graph_rows),
        "recurrent_wet_renderer_adjacent_path_rows": len(recurrent_rows),
        "recurrent_wet_g1t_or_g1s_path_rows": sum(1 for r in recurrent_rows if r["g1t_or_g1s_supported"]),
        "recurrent_wet_material_shader_term_path_rows": sum(1 for r in recurrent_rows if r["material_shader_term_supported"]),
        "baseline_before": baseline,
        "baseline_after": baseline_after,
    }
    return stats, root_public, graph_rows, recurrent_rows


def build_report(project_root: Path, game_root: Path, *, interactive: bool = True, initial_ready: bool = False, report_root: Path | None = None, output_report_root: Path | None = None, create_archive: bool = True) -> tuple[Path | None, dict[str, Any]]:
    project_root = S164.safe_resolve(project_root)
    game_root = S164.safe_resolve(game_root)
    report_root = report_root or project_root / ".local/reports/quartet_restoration" / REPORT_DIR
    output_report_root = output_report_root or project_root / ".local/reports/quartet_restoration"
    if report_root.exists():
        import shutil
        shutil.rmtree(report_root)
    report_root.mkdir(parents=True, exist_ok=True)

    stats, roots, graph_rows, recurrent = run_trace(project_root, game_root, interactive=interactive, initial_ready=initial_ready)
    if recurrent:
        quality = "fresh_recurrent_wet_renderer_adjacent_pointer_graph_candidates_observed"
        next_action = "Inspect recurrent wet-only G1T/G1S or material/shader-term paths and bind them to actual renderer state before any write. Do not infer transparency from token presence alone."
    elif stats["wet2_recurrent_wet_school_root_rows"]:
        quality = "fresh_recurrent_wet_school_roots_traced_without_renderer_adjacent_recurrence"
        next_action = "Do not broaden back to scalar guessing. Use an external renderer/resource capture synchronized to native Change Wetness, seeded only by the verified recurrent wet-school roots."
    else:
        quality = "wet1_neighborhood_candidates_not_recurrent_as_wet_school_roots_in_wet2"
        next_action = "Treat the WET1 neighborhood roots as transient candidates, not a failed user toggle. Reacquire wet-school roots semantically across WET states before any deeper renderer inference; do not write or guess scalar semantics."

    summary = {
        "format_version": 1,
        "type": "br_quartet_restoration_wet_renderer_adjacent_pointer_graph_evidence_summary",
        "tool_version": TOOL_VERSION,
        "stage": STAGE,
        "status": "fresh_process_wet_school_renderer_adjacent_pointer_graph_trace_complete_read_only",
        "stage167_report_sha256": STAGE167_SHA256,
        "stage167_historical_pid_reused": False,
        "stage167_historical_absolute_addresses_reused": False,
        "stage167_broad_pointer_target_scan_repeated": False,
        "fresh_process_anchor_reacquisition_performed": True,
        "capture_sequence": "fresh DRY1 discovery -> native WET1 wet-school root selection + graph -> native DRY2 same-field graph -> native WET2 recurrence + graph",
        "stage167_wet_only_asset_token_candidate_rows": stats["stage167_wet_only_asset_token_candidate_rows"],
        "fresh_dynamic_wet_model_rows": stats["fresh_dynamic_wet_model_rows"],
        "fresh_pointer_reference_rows": stats["fresh_pointer_reference_rows"],
        "fresh_anchor_site_rows": stats["fresh_anchor_site_rows"],
        "fresh_unique_wet_school_root_rows": stats["fresh_unique_wet_school_root_rows"],
        "wet2_recurrent_wet_school_root_rows": stats["wet2_recurrent_wet_school_root_rows"],
        "wet2_rejected_root_rows": stats["wet2_rejected_root_rows"],
        "wet1_neighborhood_candidate_drift_is_nonfatal": True,
        "pointer_graph_observation_rows": stats["pointer_graph_observation_rows"],
        "recurrent_wet_renderer_adjacent_path_rows": stats["recurrent_wet_renderer_adjacent_path_rows"],
        "recurrent_wet_g1t_or_g1s_path_rows": stats["recurrent_wet_g1t_or_g1s_path_rows"],
        "recurrent_wet_material_shader_term_path_rows": stats["recurrent_wet_material_shader_term_path_rows"],
        "quality": quality,
        "render_resource_binding_confirmed": False,
        "material_binding_confirmed": False,
        "shader_binding_confirmed": False,
        "texture_binding_confirmed": False,
        "wet_transparency_mechanism_confirmed": False,
        "numeric_or_pointer_field_semantics_inferred": False,
        "current_pid_exported": False,
        "absolute_process_addresses_exported": False,
        "raw_process_memory_exported": False,
        "process_memory_written": False,
        "installed_game_modified": False,
        "pack10_02_baseline_sha256": stats["baseline_before"],
        "pack10_02_unchanged": stats["baseline_before"] == stats["baseline_after"] == PACK10_02_BASELINE_SHA256,
        "generation10_v2_dependency_used": False,
        "next_action": next_action,
    }

    write_tsv(report_root / "WET_SCHOOL_ROOT_CANDIDATES.tsv", [
        "root_id", "anchor_descriptor", "relative_offset", "wet1_direct_asset_tokens", "wet1_direct_technical_terms",
        "wet2_root_status", "wet2_recurrent_wet_school", "wet2_direct_asset_tokens", "wet2_direct_technical_terms",
        "dry2_pointer_differs_from_wet1", "wet1_wet2_exact_pointer_recurrence", "absolute_pointer_exported",
    ], roots)
    write_tsv(report_root / "POINTER_GRAPH_OBSERVATIONS.tsv", [
        "root_id", "state", "depth", "edge_relative_path", "mapping_key", "mapping_class", "mapping_permissions",
        "mapping_path_basename", "mapping_path_sha256", "mapping_relative_offset", "context_sha256", "asset_tokens",
        "technical_terms", "render_asset_tokens", "render_technical_terms", "renderer_adjacent", "terminal_key", "absolute_address_exported",
    ], graph_rows)
    write_tsv(report_root / "RECURRENT_WET_RENDERER_ADJACENT_PATH_CANDIDATES.tsv", [
        "root_id", "depth", "edge_relative_path", "wet_render_asset_tokens", "wet_render_technical_terms",
        "wet1_context_sha256", "wet2_context_sha256", "same_context_hash_wet1_wet2", "g1t_or_g1s_supported",
        "material_shader_term_supported", "render_resource_binding_confirmed", "material_binding_confirmed",
        "shader_binding_confirmed", "texture_binding_confirmed", "transparency_semantics_confirmed",
    ], recurrent)
    (report_root / "SUMMARY.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    archive: Path | None = None
    if create_archive:
        archive = output_report_root / REPORT_NAME
        make_archive(report_root, archive)
    return archive, summary


def probe(project_root: Path, game_root: Path) -> dict[str, Any]:
    verify_prerequisites(project_root, game_root)
    proc = S164.discover_game_process(game_root)
    maps = S164.read_maps(int(proc["pid"]))
    ok, reason = S164._probe_memory_access(int(proc["pid"]), maps, game_root)
    return {"memory_readable": ok, "reason": reason, "fresh_process_reacquisition": True, "historical_absolute_addresses_reused": False}


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("project_root", type=Path)
    ap.add_argument("--game-root", type=Path, required=True)
    ap.add_argument("--probe-access", action="store_true")
    ap.add_argument("--no-interactive", action="store_true")
    ap.add_argument("--initial-ready", action="store_true", help="launcher already confirmed the initial DRY state; avoid a duplicate DRY1 prompt")
    ap.add_argument("--report-root", type=Path)
    ap.add_argument("--output-report-root", type=Path)
    ap.add_argument("--no-archive", action="store_true")
    return ap.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    a = parse_args(argv)
    project_root = S164.safe_resolve(a.project_root)
    game_root = S164.safe_resolve(a.game_root)
    try:
        if a.probe_access:
            result = probe(project_root, game_root)
            print(json.dumps(result, sort_keys=True))
            return 0 if result["memory_readable"] else ACCESS_DENIED_EXIT
        archive, summary = build_report(project_root, game_root, interactive=not a.no_interactive, initial_ready=a.initial_ready, report_root=a.report_root, output_report_root=a.output_report_root, create_archive=not a.no_archive)
        print(json.dumps(summary, indent=2, sort_keys=True))
        if archive:
            print(f"[stage168] evidence: {archive}")
        return 0
    except PermissionError as exc:
        print(f"[stage168] process-memory permission denied: {exc}", file=sys.stderr)
        return ACCESS_DENIED_EXIT
    except Stage168Error as exc:
        print(f"[stage168] ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
