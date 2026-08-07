#!/usr/bin/env python3
"""Stage 169: recurrent WET-only blend-context binding trace (read-only).

Stage 168 proved that fresh wet-school model roots can be recurrently reacquired
across WET1/WET2 and produced 68 WET-only renderer-adjacent paths.  Most of the
asset-name hits were clearly global/unrelated resources.  The strongest narrow
technical clue was a single recurrent WET-only path whose bounded context
contained the technical term ``blend`` with no arbitrary G1T/G1S basename.

Stage 169 does not reuse the stage-168 PID or any absolute process address.  It
freshly reacquires stage-166-class anchors, narrows to current WET school roots,
then identifies recurrent WET1/WET2 blend-context paths that are absent in DRY2.
Only those blend contexts are inspected through a small bounded qword-pointer
neighborhood for allowlisted renderer terms and asset basenames.

Evidence contains only hashes, mapping-relative descriptors, relative edge/
field offsets and allowlisted technical tokens.  It never exports a PID,
absolute process address, raw process memory, full process path or command line.
No process memory or game file is written.  A recurrent blend/material/shader/
texture term is candidate evidence only and does not prove transparency or an
active renderer binding by itself.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import importlib.util
import json
import os
import re
import struct
import subprocess
import sys
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

TOOL_VERSION = "0.1.95"
STAGE = 169
REPORT_DIR = "wet_blend_context_binding_evidence"
REPORT_NAME = "BR_quartet_restoration_wet_blend_context_binding_evidence.tar.zst"
STAGE168_REPORT = "BR_quartet_restoration_wet_renderer_adjacent_pointer_graph_evidence.tar.zst"
STAGE168_SHA256 = "4c68380b71491180cbfbf98dfae2846b9dc37e600a8ba879d0c26e96ee8604e1"
PACK10_02_BASELINE_SHA256 = "e798f39c3bcdbb11381197bddf9bd3ad8de6ccf5d7c0c78b22613046d47f5302"
ACCESS_DENIED_EXIT = 77

# Keep the new trace intentionally much smaller than stage 168.
ROOT_GRAPH_MAX_DEPTH = 2
ROOT_GRAPH_MAX_NODES = 72
BLEND_CONTEXT_RADIUS = 1536
CHILD_PREVIEW_RADIUS = 512
MAX_NEIGHBOR_POINTERS = 64
MAX_RICH_TOKENS = 32

WET_MODEL_MARKERS = {
    "PC00_Scl_W.g1m",
    "PC00_Scl_W_default.g1m",
}
STRONG_WET_MARKERS = {
    "PC00_Scl_W.g1m",
    "PC00_Scl_W_default.g1m",
    "PC00_Scl_W_P_School_Wet.g1m",
}

# Safe, explicit vocabulary only.  We export the matched vocabulary terms, not
# arbitrary process strings.
RICH_RENDER_TERMS = (
    "material",
    "shader",
    "texture",
    "sampler",
    "blend",
    "blendstate",
    "blend_state",
    "srcblend",
    "dstblend",
    "blendop",
    "blend_op",
    "alpha",
    "alphatest",
    "alpha_test",
    "opacity",
    "transparent",
    "transparency",
    "translucent",
    "renderstate",
    "render_state",
    "technique",
)
STRONG_BINDING_TERMS = {
    "material", "shader", "texture", "sampler", "blendstate", "blend_state",
    "srcblend", "dstblend", "blendop", "blend_op", "alpha", "alphatest",
    "alpha_test", "opacity", "transparent", "transparency", "translucent",
}
ASSET_SUFFIXES = (".g1m", ".g1t", ".g1s", ".g1e", ".g1em", ".kps", ".dds")


class Stage169Error(RuntimeError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise Stage169Error(message)


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


def _load_stage168():
    path = Path(__file__).with_name("168_trace_wet_renderer_adjacent_pointer_graph.py")
    spec = importlib.util.spec_from_file_location("br_restoration_stage168_for169", path)
    require(spec is not None and spec.loader is not None, "cannot load stage168 helper")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


S168 = _load_stage168()
S167 = S168.S167
S166 = S168.S166
S165 = S168.S165
S164 = S168.S164


def _archive_member_bytes(archive: Path, suffix: str) -> bytes:
    cp = subprocess.run(["tar", "--zstd", "-tf", str(archive)], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    require(cp.returncode == 0, cp.stderr.decode("utf-8", errors="replace").strip() or "cannot list stage168 archive")
    names = cp.stdout.decode("utf-8", errors="replace").splitlines()
    matches = [n for n in names if n.endswith("/" + suffix) or n == suffix]
    require(len(matches) == 1, f"stage168 archive expected exactly one {suffix}, found {len(matches)}")
    cp = subprocess.run(["tar", "--zstd", "-xOf", str(archive), matches[0]], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    require(cp.returncode == 0, cp.stderr.decode("utf-8", errors="replace").strip() or f"cannot read {suffix} from stage168 archive")
    return cp.stdout


def verify_stage168_contract(project_root: Path) -> dict[str, Any]:
    archive = project_root / ".local/reports/quartet_restoration" / STAGE168_REPORT
    require(archive.is_file(), f"missing canonical stage168 report: {archive}")
    actual = sha256_file(archive)
    require(actual == STAGE168_SHA256, f"stage168 report SHA-256 drift: {actual}")
    summary = json.loads(_archive_member_bytes(archive, "SUMMARY.json").decode("utf-8"))
    require(summary.get("stage") == 168, "stage168 SUMMARY stage drift")
    require(summary.get("fresh_process_anchor_reacquisition_performed") is True, "stage168 did not freshly reacquire anchors")
    require(summary.get("stage167_historical_pid_reused") is False, "stage168 reused historical PID")
    require(summary.get("stage167_historical_absolute_addresses_reused") is False, "stage168 reused historical absolute addresses")
    require(int(summary.get("wet2_recurrent_wet_school_root_rows", 0)) >= 1, "stage168 has no recurrent wet-school roots")
    require(int(summary.get("recurrent_wet_renderer_adjacent_path_rows", 0)) >= 1, "stage168 has no recurrent renderer-adjacent paths")
    require(summary.get("material_binding_confirmed") is False, "stage168 unexpectedly claims material binding")

    rows = list(csv.DictReader(_archive_member_bytes(archive, "RECURRENT_WET_RENDERER_ADJACENT_PATH_CANDIDATES.tsv").decode("utf-8").splitlines(), delimiter="\t"))
    blend_only = [
        r for r in rows
        if r.get("wet_render_technical_terms") == "blend"
        and not r.get("wet_render_asset_tokens")
        and r.get("same_context_hash_wet1_wet2") == "True"
    ]
    require(len(blend_only) >= 1, "stage168 no longer contains the recurrent WET-only blend-context clue")
    return summary


def verify_prerequisites(project_root: Path, game_root: Path) -> tuple[dict[str, Any], str]:
    summary = verify_stage168_contract(project_root)
    pak = game_root / "Data/PACK10_02.PAK"
    require(pak.is_file(), f"missing Quartet PACK10_02: {pak}")
    baseline = sha256_file(pak)
    require(baseline == PACK10_02_BASELINE_SHA256, f"PACK10_02 is not exact baseline: {baseline}")
    return summary, baseline


def _ascii_runs(data: bytes) -> list[str]:
    return [m.group().decode("ascii", errors="ignore") for m in re.finditer(rb"[\x20-\x7e]{4,192}", data)]


def _utf16_runs(data: bytes) -> list[str]:
    out: list[str] = []
    for shift in (0, 1):
        text = data[shift:].decode("utf-16le", errors="ignore")
        out.extend(m.group() for m in re.finditer(r"[\x20-\x7e]{4,192}", text))
    return out


def extract_rich_allowlisted_tokens(data: bytes) -> tuple[list[str], list[str]]:
    """Return only safe asset basenames and a fixed renderer vocabulary."""
    assets, _legacy_terms = S167.extract_allowlisted_tokens(data)
    terms: set[str] = set()
    for text in _ascii_runs(data) + _utf16_runs(data):
        low = text.casefold()
        for term in RICH_RENDER_TERMS:
            if term in low:
                terms.add(term)
    return sorted(set(assets))[:MAX_RICH_TOKENS], sorted(terms)[:MAX_RICH_TOKENS]


def wet_root_rank(assets: Sequence[str], terms: Sequence[str] = ()) -> int | None:
    """Rank only fresh stage-166-class wet-school roots.

    Runtime token windows can legitimately shift between processes.  The
    strongest class exposes both PC00_Scl_W.g1m and PC00_Scl_W_default.g1m,
    but stage 168 already proved recurrent wet-school roots can expose only one
    of those markers in a given bounded direct window.  We therefore degrade
    only to the best available *wet-school* class instead of failing the trace.
    """
    aset = set(assets)
    tset = {str(t).casefold() for t in terms}
    wet_term = bool({"pc00_scl_w", "scl_w"} & tset)
    if WET_MODEL_MARKERS <= aset:
        return 0
    if wet_term and ("PC00_Scl_W_default.g1m" in aset or "PC00_Scl_W.g1m" in aset):
        return 1
    if wet_term and "PC00_Scl_W_P_School_Wet.g1m" in aset:
        return 2
    if wet_term and any(a.startswith("PC00_Scl_W_") and a.endswith(".g1m") for a in aset):
        return 3
    return None


def select_best_wet_roots(roots: Sequence[Mapping[str, Any]]) -> tuple[list[dict[str, Any]], int | None]:
    ranked: list[tuple[int, dict[str, Any]]] = []
    for root in roots:
        rank = wet_root_rank(root.get("direct_asset_tokens", []), root.get("direct_technical_terms", []))
        if rank is not None:
            ranked.append((rank, dict(root)))
    if not ranked:
        return [], None
    best = min(rank for rank, _root in ranked)
    # Keep only the strongest class present in this fresh process.  This is a
    # bounded fallback, not a return to the broad stage-168 resource graph.
    selected = [root for rank, root in ranked if rank == best]
    return selected, best


def is_strong_wet_root_assets(assets: Sequence[str]) -> bool:
    # Backward-compatible helper retained for historical/unit-test callers.
    return wet_root_rank(assets, ("pc00_scl_w",)) == 0


def _read_node_window(reader: Any, maps: Sequence[Any], address: int, radius: int) -> tuple[Any | None, int, bytes]:
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


def trace_root_graph_private(reader: Any, maps: Sequence[Any], game_root: Path, root_pointer: int, *, state: str, root_id: str) -> list[dict[str, Any]]:
    """Stage-168 style graph, depth <=2, retaining address only in memory."""
    from collections import deque
    rows: list[dict[str, Any]] = []
    q = deque([(root_pointer, 0, tuple())])
    visited: set[int] = set()
    while q and len(visited) < ROOT_GRAPH_MAX_NODES:
        address, depth, edge_path = q.popleft()
        if address in visited:
            continue
        visited.add(address)
        m, lo, data = _read_node_window(reader, maps, address, S168.GRAPH_RADIUS)
        if m is None or not data:
            continue
        pub = S168._node_public(m, game_root, address, data)
        assets = list(pub["asset_tokens"])
        terms = list(pub["technical_terms"])
        row = {
            "root_id": root_id,
            "state": state,
            "depth": depth,
            "edge_relative_path": ";".join(str(x) for x in edge_path),
            "context_sha256": pub["context_sha256"],
            "asset_tokens": ";".join(assets),
            "technical_terms": ";".join(terms),
            "mapping_key": pub["mapping_key"],
            "mapping_class": pub["mapping_class"],
            "mapping_permissions": pub["mapping_permissions"],
            "mapping_relative_offset": pub["mapping_relative_offset"],
            "_address": address,
        }
        rows.append(row)
        if depth >= ROOT_GRAPH_MAX_DEPTH:
            continue
        children: list[tuple[int, int, int, int]] = []
        seen_child: set[int] = set()
        for off in range(0, len(data) - 7, 8):
            child = struct.unpack_from("<Q", data, off)[0]
            if child == address or child in visited or child in seen_child:
                continue
            cm = S166.mapping_for_address(maps, child)
            if cm is None or "r" not in cm.perms:
                continue
            seen_child.add(child)
            _cm, _clo, preview = _read_node_window(reader, maps, child, S168.CHILD_PREVIEW_RADIUS)
            pa, pt = S167.extract_allowlisted_tokens(preview) if preview else ([], [])
            priority = 0 if (pa or pt) else 1
            edge_rel = (lo + off) - address
            children.append((priority, abs(edge_rel), edge_rel, child))
        children.sort(key=lambda x: (x[0], x[1], x[2]))
        for _priority, _dist, edge_rel, child in children[:S168.MAX_FANOUT]:
            q.append((child, depth + 1, edge_path + (edge_rel,)))
    return rows


def recurrent_blend_contexts(wet1: Sequence[Mapping[str, Any]], dry2: Sequence[Mapping[str, Any]], wet2: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Return WET1/WET2 blend paths absent at the same semantic path in DRY2."""
    def key(r: Mapping[str, Any]) -> tuple[str, int]:
        return str(r.get("edge_relative_path", "")), int(r.get("depth", 0))
    w1 = {key(r): r for r in wet1 if "blend" in str(r.get("technical_terms", "")).split(";")}
    d2 = {key(r): r for r in dry2 if "blend" in str(r.get("technical_terms", "")).split(";")}
    w2 = {key(r): r for r in wet2 if "blend" in str(r.get("technical_terms", "")).split(";")}
    out: list[dict[str, Any]] = []
    for k in sorted(set(w1) & set(w2)):
        if k in d2:
            continue
        a, b = w1[k], w2[k]
        if a.get("context_sha256") != b.get("context_sha256"):
            continue
        out.append({
            "root_id": str(a.get("root_id", "")),
            "depth": k[1],
            "edge_relative_path": k[0],
            "wet1_context_sha256": str(a.get("context_sha256", "")),
            "wet2_context_sha256": str(b.get("context_sha256", "")),
            "same_context_hash_wet1_wet2": True,
            "_wet1_address": int(a.get("_address", 0)),
            "_wet2_address": int(b.get("_address", 0)),
        })
    return out


def pointer_neighborhood(reader: Any, maps: Sequence[Any], game_root: Path, address: int, *, state: str, candidate_id: str) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Inspect one bounded blend context and only renderer-looking qword targets."""
    m, lo, data = _read_node_window(reader, maps, address, BLEND_CONTEXT_RADIUS)
    if m is None or not data:
        return ({
            "candidate_id": candidate_id,
            "state": state,
            "context_readable": False,
            "context_sha256": "",
            "direct_asset_tokens": "",
            "direct_render_terms": "",
            "mapping_key": "",
            "mapping_class": "",
            "mapping_relative_offset": "",
            "absolute_address_exported": False,
        }, [])
    cls, _base, _path_hash = S164.normalized_mapping_path(m, game_root)
    assets, terms = extract_rich_allowlisted_tokens(data)
    context = {
        "candidate_id": candidate_id,
        "state": state,
        "context_readable": True,
        "context_sha256": sha256_bytes(data),
        "direct_asset_tokens": ";".join(assets),
        "direct_render_terms": ";".join(terms),
        "mapping_key": S164.mapping_key(m),
        "mapping_class": cls,
        "mapping_relative_offset": address - m.start,
        "absolute_address_exported": False,
    }

    candidates: list[tuple[int, int, int, dict[str, Any]]] = []
    seen_child: set[int] = set()
    for off in range(0, len(data) - 7, 8):
        child = struct.unpack_from("<Q", data, off)[0]
        if child == address or child in seen_child:
            continue
        cm = S166.mapping_for_address(maps, child)
        if cm is None or "r" not in cm.perms:
            continue
        seen_child.add(child)
        _cm, _clo, preview = _read_node_window(reader, maps, child, CHILD_PREVIEW_RADIUS)
        if not preview:
            continue
        ca, ct = extract_rich_allowlisted_tokens(preview)
        renderer_assets = [a for a in ca if a.casefold().endswith((".g1t", ".g1s"))]
        strong_terms = sorted(set(ct) & STRONG_BINDING_TERMS)
        if not renderer_assets and not strong_terms:
            continue
        field_rel = (lo + off) - address
        priority = 0 if strong_terms else 1
        candidates.append((priority, abs(field_rel), field_rel, {
            "candidate_id": candidate_id,
            "state": state,
            "field_relative_offset": field_rel,
            "child_mapping_key": S164.mapping_key(cm),
            "child_mapping_class": S164.normalized_mapping_path(cm, game_root)[0],
            "child_mapping_permissions": cm.perms,
            "child_mapping_relative_offset": child - cm.start,
            "child_context_sha256": sha256_bytes(preview),
            "child_asset_tokens": ";".join(ca),
            "child_render_terms": ";".join(ct),
            "renderer_asset_supported": bool(renderer_assets),
            "strong_binding_term_supported": bool(strong_terms),
            "absolute_pointer_exported": False,
        }))
    candidates.sort(key=lambda x: (x[0], x[1], x[2]))
    return context, [x[3] for x in candidates[:MAX_NEIGHBOR_POINTERS]]


def recurrent_binding_rows(wet1: Sequence[Mapping[str, Any]], dry2: Sequence[Mapping[str, Any]], wet2: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    def key(r: Mapping[str, Any]) -> tuple[int, str, str]:
        return (
            int(r.get("field_relative_offset", 0)),
            str(r.get("child_asset_tokens", "")),
            str(r.get("child_render_terms", "")),
        )
    w1 = {key(r): r for r in wet1}
    d2 = {key(r): r for r in dry2}
    w2 = {key(r): r for r in wet2}
    out: list[dict[str, Any]] = []
    for k in sorted(set(w1) & set(w2)):
        if k in d2:
            continue
        a, b = w1[k], w2[k]
        same_hash = a.get("child_context_sha256") == b.get("child_context_sha256")
        if not same_hash:
            continue
        terms = set(filter(None, str(a.get("child_render_terms", "")).split(";")))
        assets = [x for x in str(a.get("child_asset_tokens", "")).split(";") if x]
        out.append({
            "candidate_id": a.get("candidate_id", ""),
            "field_relative_offset": k[0],
            "wet_child_asset_tokens": ";".join(assets),
            "wet_child_render_terms": ";".join(sorted(terms)),
            "wet1_child_context_sha256": a.get("child_context_sha256", ""),
            "wet2_child_context_sha256": b.get("child_context_sha256", ""),
            "same_context_hash_wet1_wet2": same_hash,
            "renderer_asset_supported": bool([x for x in assets if x.casefold().endswith((".g1t", ".g1s"))]),
            "strong_binding_term_supported": bool(terms & STRONG_BINDING_TERMS),
            "alpha_or_transparency_term_supported": bool(terms & {"alpha", "alphatest", "alpha_test", "opacity", "transparent", "transparency", "translucent"}),
            "render_resource_binding_confirmed": False,
            "material_binding_confirmed": False,
            "shader_binding_confirmed": False,
            "texture_binding_confirmed": False,
            "transparency_semantics_confirmed": False,
        })
    return out


def _public_root_row(root: Mapping[str, Any], *, wet2_status: str, wet2_assets: Sequence[str], wet2_terms: Sequence[str], exact_recurrence: bool) -> dict[str, Any]:
    return {
        "root_id": root.get("root_id", ""),
        "anchor_descriptor": root.get("anchor_descriptor", ""),
        "relative_offset": root.get("relative_offset", ""),
        "wet1_direct_asset_tokens": ";".join(root.get("direct_asset_tokens", [])),
        "wet1_direct_technical_terms": ";".join(root.get("direct_technical_terms", [])),
        "wet2_root_status": wet2_status,
        "wet2_direct_asset_tokens": ";".join(wet2_assets),
        "wet2_direct_technical_terms": ";".join(wet2_terms),
        "wet1_wet2_exact_pointer_recurrence": exact_recurrence,
        "absolute_pointer_exported": False,
    }


def run_trace(project_root: Path, game_root: Path, *, interactive: bool = True, initial_ready: bool = False) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    stage168_summary, baseline = verify_prerequisites(project_root, game_root)
    proc = S164.discover_game_process(game_root)
    pid = int(proc["pid"])

    def ensure_alive() -> None:
        require((Path("/proc") / str(pid)).is_dir(), "game process exited during stage169 trace")

    if interactive:
        print("\n[stage169] NEW PROCESS: no stage168 PID or absolute address is reused.")
        if initial_ready:
            print("[stage169] Launcher already confirmed Hinako / native School Uniform / DRY. Capturing DRY1 now.")
        else:
            print("[stage169] Prepare Hinako / native School Uniform / DRY. This trace follows only recurrent WET-only blend contexts.")
            input("[stage169] Press Enter to capture DRY1 discovery baseline... ")

    ensure_alive()
    dry_maps1 = S164.read_maps(pid)
    with S164.ProcessMemoryReader(pid) as reader:
        dry_model_rows, _ = S165.scan_wet_model_token(reader, dry_maps1, game_root, "stage169_dry1")

    if interactive:
        print("[stage169] Use native Change Wetness: DRY -> WET.")
        input("[stage169] Press Enter when WET is fully visible... ")
    ensure_alive()
    wet_maps1 = S164.read_maps(pid)
    with S164.ProcessMemoryReader(pid) as reader:
        wet_model_rows, _ = S165.scan_wet_model_token(reader, wet_maps1, game_root, "stage169_wet1")
        dynamic = S165.dynamic_wet_occurrences(dry_model_rows, wet_model_rows)
        pointer_rows, _ = S165.scan_pointers_to_dynamic_wet(reader, wet_maps1, game_root, dynamic)
        sites = S166.fresh_site_contracts(pointer_rows)
        require(sites, "fresh stage166-class anchors were not reacquired; no historical address will be substituted")
        wet1_blobs, _ = S166.capture_site_state(reader, wet_maps1, game_root, sites, "stage169_wet1")
        roots = S168.direct_wet_model_root_candidates(reader, wet_maps1, game_root, sites, wet1_blobs)
        # Deduplicate by current pointer.  Prefer the strongest root class, but
        # do not fail merely because a fresh process exposes only one of the two
        # main wet-model markers in the bounded direct token window.
        dedup: dict[int, dict[str, Any]] = {}
        for r in roots:
            dedup.setdefault(int(r["pointer"]), r)
        roots, root_rank = select_best_wet_roots(list(dedup.values()))
        require(roots, "no fresh bounded wet-school root could be reacquired from stage166-class anchors")
        wet1_graph_by_root: dict[str, list[dict[str, Any]]] = {}
        wet1_blend_capture_by_key: dict[tuple[str, int, str], tuple[dict[str, Any], list[dict[str, Any]]]] = {}
        for idx, root in enumerate(roots, 1):
            root_id = f"blend_root_{idx:02d}"
            root["root_id"] = root_id
            graph = trace_root_graph_private(reader, wet_maps1, game_root, int(root["pointer"]), state="wet1", root_id=root_id)
            wet1_graph_by_root[root_id] = graph
            for row in graph:
                if "blend" not in str(row.get("technical_terms", "")).split(";"):
                    continue
                key = (root_id, int(row.get("depth", 0)), str(row.get("edge_relative_path", "")))
                candidate_id = f"{root_id}_path_{int(row.get('depth',0))}_{str(row.get('edge_relative_path','')).replace(';','_').replace('-','m') or 'root'}"
                wet1_blend_capture_by_key[key] = pointer_neighborhood(
                    reader, wet_maps1, game_root, int(row["_address"]), state="wet1", candidate_id=candidate_id
                )

    if interactive:
        print(f"[stage169] Reacquired {len(sites)} anchor(s), selected {len(roots)} wet-school root(s) at rank {root_rank}. Toggle WET -> DRY.")
        input("[stage169] Press Enter when DRY is fully visible... ")
    ensure_alive()
    dry_maps2 = S164.read_maps(pid)
    dry_graph_by_root: dict[str, list[dict[str, Any]]] = {}
    dry_blend_capture_by_key: dict[tuple[str, int, str], tuple[dict[str, Any], list[dict[str, Any]]]] = {}
    dry_blobs: dict[int, bytes] = {}
    with S164.ProcessMemoryReader(pid) as reader:
        dry_blobs, _ = S166.capture_site_state(reader, dry_maps2, game_root, sites, "stage169_dry2")
        for root in roots:
            site_addr = int(root["site_address"])
            rel = int(root["relative_offset"])
            pointer = S168.pointer_at_field(dry_blobs[site_addr], site_addr, rel)
            root["dry2_pointer"] = pointer
            if pointer is not None:
                graph = trace_root_graph_private(reader, dry_maps2, game_root, int(pointer), state="dry2", root_id=root["root_id"])
            else:
                graph = []
            dry_graph_by_root[root["root_id"]] = graph
            by_path = {(int(r.get("depth",0)), str(r.get("edge_relative_path",""))): r for r in graph}
            for key, (w1ctx, _w1rows) in wet1_blend_capture_by_key.items():
                if key[0] != root["root_id"]:
                    continue
                row = by_path.get((key[1], key[2]))
                if row is None:
                    continue
                dry_blend_capture_by_key[key] = pointer_neighborhood(
                    reader, dry_maps2, game_root, int(row["_address"]), state="dry2", candidate_id=str(w1ctx.get("candidate_id", ""))
                )

    if interactive:
        print("[stage169] DRY control captured. Toggle DRY -> WET once more.")
        input("[stage169] Press Enter when WET is fully visible again... ")
    ensure_alive()
    wet_maps2 = S164.read_maps(pid)

    root_rows: list[dict[str, Any]] = []
    blend_context_rows: list[dict[str, Any]] = []
    neighborhood_rows: list[dict[str, Any]] = []
    recurrent_rows: list[dict[str, Any]] = []
    recurrent_root_count = 0
    rejected_root_count = 0
    recurrent_blend_count = 0
    with S164.ProcessMemoryReader(pid) as reader:
        wet2_blobs, _ = S166.capture_site_state(reader, wet_maps2, game_root, sites, "stage169_wet2")
        for root in roots:
            site_addr = int(root["site_address"])
            rel = int(root["relative_offset"])
            wet2_pointer = S168.pointer_at_field(wet2_blobs[site_addr], site_addr, rel)
            status, wet2_assets, wet2_terms = S168.classify_wet2_root_target(reader, wet_maps2, game_root, wet2_pointer)
            exact_recurrence = bool(wet2_pointer is not None and int(wet2_pointer) == int(root["pointer"]))
            root_rows.append(_public_root_row(root, wet2_status=status, wet2_assets=wet2_assets, wet2_terms=wet2_terms, exact_recurrence=exact_recurrence))
            if status != "recurrent_wet_school" or wet2_pointer is None:
                rejected_root_count += 1
                continue
            recurrent_root_count += 1
            w1_graph = wet1_graph_by_root[root["root_id"]]
            d2_graph = dry_graph_by_root[root["root_id"]]
            w2_graph = trace_root_graph_private(reader, wet_maps2, game_root, int(wet2_pointer), state="wet2", root_id=root["root_id"])
            blend_candidates = recurrent_blend_contexts(w1_graph, d2_graph, w2_graph)
            for n, bc in enumerate(blend_candidates, 1):
                recurrent_blend_count += 1
                key = (root["root_id"], int(bc["depth"]), str(bc["edge_relative_path"]))
                w1_capture = wet1_blend_capture_by_key.get(key)
                require(w1_capture is not None, "missing WET1 blend-context capture for recurrent path")
                w1_ctx, w1_neighbors = w1_capture
                candidate_id = str(w1_ctx.get("candidate_id", "")) or f"{root['root_id']}_blend_{n:02d}"
                bc_pub = {
                    "candidate_id": candidate_id,
                    "root_id": root["root_id"],
                    "depth": bc["depth"],
                    "edge_relative_path": bc["edge_relative_path"],
                    "wet1_context_sha256": bc["wet1_context_sha256"],
                    "wet2_context_sha256": bc["wet2_context_sha256"],
                    "same_context_hash_wet1_wet2": True,
                    "dry2_same_blend_path_present": False,
                    "absolute_address_exported": False,
                    "binding_semantics_confirmed": False,
                }
                blend_context_rows.append(bc_pub)
                w2_ctx, w2_neighbors = pointer_neighborhood(
                    reader, wet_maps2, game_root, int(bc["_wet2_address"]), state="wet2", candidate_id=candidate_id
                )
                if key in dry_blend_capture_by_key:
                    d2_ctx, d2_neighbors = dry_blend_capture_by_key[key]
                else:
                    d2_ctx = {
                        "candidate_id": candidate_id,
                        "state": "dry2",
                        "context_readable": False,
                        "context_sha256": "",
                        "direct_asset_tokens": "",
                        "direct_render_terms": "",
                        "mapping_key": "",
                        "mapping_class": "",
                        "mapping_relative_offset": "",
                        "absolute_address_exported": False,
                    }
                    d2_neighbors = []
                blend_context_rows.extend([w1_ctx, d2_ctx, w2_ctx])
                neighborhood_rows.extend(w1_neighbors)
                neighborhood_rows.extend(d2_neighbors)
                neighborhood_rows.extend(w2_neighbors)
                recurrent_rows.extend(recurrent_binding_rows(w1_neighbors, d2_neighbors, w2_neighbors))

        if interactive:
            print(f"[stage169] WET2 filter: {recurrent_root_count}/{len(roots)} recurrent strong wet-school roots; {rejected_root_count} rejected.")
            print(f"[stage169] Recurrent WET-only blend contexts: {recurrent_blend_count}.")

    baseline_after = sha256_file(game_root / "Data/PACK10_02.PAK")
    require(baseline_after == baseline == PACK10_02_BASELINE_SHA256, "PACK10_02 changed during read-only stage169 trace")

    stats = {
        "stage168_recurrent_renderer_adjacent_path_rows": int(stage168_summary.get("recurrent_wet_renderer_adjacent_path_rows", 0)),
        "fresh_dynamic_wet_model_rows": len(dynamic),
        "fresh_pointer_reference_rows": len(pointer_rows),
        "fresh_anchor_site_rows": len(sites),
        "fresh_strong_wet_school_root_rows": len(roots),
        "fresh_wet_school_root_selection_rank": root_rank,
        "wet2_recurrent_strong_wet_school_root_rows": recurrent_root_count,
        "wet2_rejected_strong_root_rows": rejected_root_count,
        "recurrent_wet_only_blend_context_rows": recurrent_blend_count,
        "blend_context_neighborhood_rows": len(neighborhood_rows),
        "recurrent_wet_blend_binding_candidate_rows": len(recurrent_rows),
        "recurrent_alpha_or_transparency_candidate_rows": sum(1 for r in recurrent_rows if r["alpha_or_transparency_term_supported"]),
        "recurrent_renderer_asset_candidate_rows": sum(1 for r in recurrent_rows if r["renderer_asset_supported"]),
        "recurrent_strong_binding_term_candidate_rows": sum(1 for r in recurrent_rows if r["strong_binding_term_supported"]),
        "baseline_before": baseline,
        "baseline_after": baseline_after,
    }
    return stats, root_rows, blend_context_rows, neighborhood_rows, recurrent_rows


def build_report(project_root: Path, game_root: Path, *, interactive: bool = True, initial_ready: bool = False, report_root: Path | None = None, output_report_root: Path | None = None, create_archive: bool = True) -> tuple[Path | None, dict[str, Any]]:
    project_root = S164.safe_resolve(project_root)
    game_root = S164.safe_resolve(game_root)
    report_root = report_root or project_root / ".local/reports/quartet_restoration" / REPORT_DIR
    output_report_root = output_report_root or project_root / ".local/reports/quartet_restoration"
    if report_root.exists():
        import shutil
        shutil.rmtree(report_root)
    report_root.mkdir(parents=True, exist_ok=True)

    stats, roots, blend_contexts, neighborhoods, recurrent = run_trace(project_root, game_root, interactive=interactive, initial_ready=initial_ready)
    if stats["recurrent_alpha_or_transparency_candidate_rows"]:
        quality = "fresh_recurrent_wet_blend_context_with_alpha_or_transparency_adjacent_candidate_observed"
        next_action = "Bind the recurrent alpha/transparency-adjacent child to an actual active renderer/material object before any write. Do not patch based on terminology alone."
    elif stats["recurrent_wet_blend_binding_candidate_rows"]:
        quality = "fresh_recurrent_wet_blend_context_with_renderer_adjacent_children_observed"
        next_action = "Review the recurrent blend-context children and correlate only the strongest material/shader/texture/sampler candidate with active renderer state; do not broaden back to unrelated global resources."
    elif stats["recurrent_wet_only_blend_context_rows"]:
        quality = "fresh_recurrent_wet_blend_context_observed_without_stronger_binding_child"
        next_action = "Treat the blend context as a bounded runtime clue only. Use an external renderer/resource correlation seeded from this context or return to static shader/material identity evidence; do not infer transparency."
    else:
        quality = "no_fresh_recurrent_wet_only_blend_context_reacquired"
        next_action = "Do not interpret this as a failed user toggle. The stage168 blend clue may be transient. Stop this path and use another independently grounded binding signal rather than broadening pointer scans."

    summary = {
        "format_version": 1,
        "type": "br_quartet_restoration_wet_blend_context_binding_evidence_summary",
        "tool_version": TOOL_VERSION,
        "stage": STAGE,
        "status": "fresh_process_wet_blend_context_binding_trace_complete_read_only",
        "stage168_report_sha256": STAGE168_SHA256,
        "stage168_historical_pid_reused": False,
        "stage168_historical_absolute_addresses_reused": False,
        "stage168_broad_68_candidate_graph_repeated": False,
        "fresh_process_anchor_reacquisition_performed": True,
        "capture_sequence": "fresh DRY1 discovery -> native WET1 strong wet-school roots + depth<=2 blend discovery -> native DRY2 control -> native WET2 recurrence + bounded blend-context neighborhood",
        "stage168_recurrent_renderer_adjacent_path_rows": stats["stage168_recurrent_renderer_adjacent_path_rows"],
        "fresh_dynamic_wet_model_rows": stats["fresh_dynamic_wet_model_rows"],
        "fresh_pointer_reference_rows": stats["fresh_pointer_reference_rows"],
        "fresh_anchor_site_rows": stats["fresh_anchor_site_rows"],
        "fresh_strong_wet_school_root_rows": stats["fresh_strong_wet_school_root_rows"],
        "wet2_recurrent_strong_wet_school_root_rows": stats["wet2_recurrent_strong_wet_school_root_rows"],
        "wet2_rejected_strong_root_rows": stats["wet2_rejected_strong_root_rows"],
        "recurrent_wet_only_blend_context_rows": stats["recurrent_wet_only_blend_context_rows"],
        "blend_context_neighborhood_rows": stats["blend_context_neighborhood_rows"],
        "recurrent_wet_blend_binding_candidate_rows": stats["recurrent_wet_blend_binding_candidate_rows"],
        "recurrent_alpha_or_transparency_candidate_rows": stats["recurrent_alpha_or_transparency_candidate_rows"],
        "recurrent_renderer_asset_candidate_rows": stats["recurrent_renderer_asset_candidate_rows"],
        "recurrent_strong_binding_term_candidate_rows": stats["recurrent_strong_binding_term_candidate_rows"],
        "pack10_02_baseline_sha256": stats["baseline_before"],
        "pack10_02_unchanged": stats["baseline_before"] == stats["baseline_after"] == PACK10_02_BASELINE_SHA256,
        "process_memory_written": False,
        "installed_game_modified": False,
        "raw_process_memory_exported": False,
        "current_pid_exported": False,
        "absolute_process_addresses_exported": False,
        "numeric_or_pointer_field_semantics_inferred": False,
        "generation10_v2_dependency_used": False,
        "render_resource_binding_confirmed": False,
        "material_binding_confirmed": False,
        "shader_binding_confirmed": False,
        "texture_binding_confirmed": False,
        "wet_transparency_mechanism_confirmed": False,
        "quality": quality,
        "next_action": next_action,
    }

    # Only public/safe rows are written.  Internal _address fields never leave RAM.
    public_blend = [r for r in blend_contexts if "_wet1_address" not in r and "_wet2_address" not in r]
    write_tsv(report_root / "STRONG_WET_SCHOOL_ROOTS.tsv", [
        "root_id", "anchor_descriptor", "relative_offset", "wet1_direct_asset_tokens", "wet1_direct_technical_terms",
        "wet2_root_status", "wet2_direct_asset_tokens", "wet2_direct_technical_terms", "wet1_wet2_exact_pointer_recurrence",
        "absolute_pointer_exported",
    ], roots)
    write_tsv(report_root / "RECURRENT_WET_BLEND_CONTEXTS.tsv", [
        "candidate_id", "root_id", "depth", "edge_relative_path", "wet1_context_sha256", "wet2_context_sha256",
        "same_context_hash_wet1_wet2", "dry2_same_blend_path_present", "absolute_address_exported", "binding_semantics_confirmed",
        "state", "context_readable", "context_sha256", "direct_asset_tokens", "direct_render_terms", "mapping_key", "mapping_class",
        "mapping_relative_offset",
    ], public_blend)
    write_tsv(report_root / "BLEND_CONTEXT_POINTER_NEIGHBORHOOD.tsv", [
        "candidate_id", "state", "field_relative_offset", "child_mapping_key", "child_mapping_class", "child_mapping_permissions",
        "child_mapping_relative_offset", "child_context_sha256", "child_asset_tokens", "child_render_terms", "renderer_asset_supported",
        "strong_binding_term_supported", "absolute_pointer_exported",
    ], neighborhoods)
    write_tsv(report_root / "RECURRENT_WET_BLEND_BINDING_CANDIDATES.tsv", [
        "candidate_id", "field_relative_offset", "wet_child_asset_tokens", "wet_child_render_terms", "wet1_child_context_sha256",
        "wet2_child_context_sha256", "same_context_hash_wet1_wet2", "renderer_asset_supported", "strong_binding_term_supported",
        "alpha_or_transparency_term_supported", "render_resource_binding_confirmed", "material_binding_confirmed", "shader_binding_confirmed",
        "texture_binding_confirmed", "transparency_semantics_confirmed",
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
    return {
        "memory_readable": ok,
        "reason": reason,
        "fresh_process_reacquisition": True,
        "historical_absolute_addresses_reused": False,
    }


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("project_root", type=Path)
    ap.add_argument("--game-root", type=Path, required=True)
    ap.add_argument("--probe-access", action="store_true")
    ap.add_argument("--no-interactive", action="store_true")
    ap.add_argument("--initial-ready", action="store_true", help="launcher already confirmed initial DRY; avoid duplicate prompt")
    ap.add_argument("--report-root", type=Path)
    ap.add_argument("--output-report-root", type=Path)
    ap.add_argument("--no-archive", action="store_true")
    return ap.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    a = parse_args(argv)
    try:
        if a.probe_access:
            print(json.dumps(probe(a.project_root, a.game_root), sort_keys=True))
            return 0
        archive, summary = build_report(
            a.project_root,
            a.game_root,
            interactive=not a.no_interactive,
            initial_ready=a.initial_ready,
            report_root=a.report_root,
            output_report_root=a.output_report_root,
            create_archive=not a.no_archive,
        )
        print(json.dumps(summary, indent=2, sort_keys=True))
        if archive is not None:
            print(f"[stage169] report: {archive}")
        return 0
    except PermissionError as exc:
        print(f"[stage169] process memory access denied: {exc}", file=sys.stderr)
        return ACCESS_DENIED_EXIT
    except (Stage169Error, S168.Stage168Error, S167.Stage167Error, OSError) as exc:
        print(f"[stage169] ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
