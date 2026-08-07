#!/usr/bin/env python3
"""Stage 167: fresh-process wet render-resource/material-binding trace (read-only).

Stage 166 established recurrent WET1==WET2!=DRY2 typed fields around freshly
reacquired native wet-school model pointer anchors.  Stage 167 does not reuse
stage-166 PIDs or absolute addresses and does not repeat its broad component
scan.  It performs only the minimum fresh-process anchor reacquisition needed
for a new process, then follows recurrent pointer fields into bounded pointed
object/resource neighborhoods.

The trace reports only hashes, mapping-relative descriptors, allowlisted asset
basenames/technical tokens, and one-hop token-supported pointer-chain
candidates.  It never exports raw process memory, current absolute addresses,
full process paths or command lines.  No process memory or game file is written.

A token-supported pointer chain is still a candidate, not proof that a field is
wetness, transparency, alpha, material, shader, or texture control.  Those
semantics require independent binding evidence.
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

TOOL_VERSION = "0.1.90"
STAGE = 167
REPORT_DIR = "wet_render_resource_material_binding_trace_evidence"
REPORT_NAME = "BR_quartet_restoration_wet_render_resource_material_binding_trace_evidence.tar.zst"
STAGE166_REPORT = "BR_quartet_restoration_wet_character_compound_state_neighborhood_evidence.tar.zst"
STAGE166_SHA256 = "7426be534a10ae601c0934ca2c36fd001d1edcae2a11d0d900df2173edd53e7a"
PACK10_02_BASELINE_SHA256 = "e798f39c3bcdbb11381197bddf9bd3ad8de6ccf5d7c0c78b22613046d47f5302"
ACCESS_DENIED_EXIT = 77
TARGET_RADIUS = 2048
SECONDARY_RADIUS = 384
MAX_SECONDARY_POINTERS = 12
MAX_TOKEN_LENGTH = 160
MAX_TOKENS_PER_OBSERVATION = 24

ASSET_RE = re.compile(r"(?i)(?:[A-Za-z0-9_.-]+[\\/])*([A-Za-z0-9_.-]{2,}\.(?:g1m|g1t|g1s|g1e|g1em|kps|dds))")
TECHNICAL_TERMS = (
    "material", "shader", "texture", "sampler", "blend", "alpha", "wetness",
    "pc00_scl_w", "pc00_nkd_w", "school_wet", "scl_w", "nkd_w",
)


class Stage167Error(RuntimeError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise Stage167Error(message)


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


def _load_stage166():
    path = Path(__file__).with_name("166_trace_wet_character_compound_state_neighborhood.py")
    spec = importlib.util.spec_from_file_location("br_restoration_stage166_for167", path)
    require(spec is not None and spec.loader is not None, "cannot load stage166 helper")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


S166 = _load_stage166()
S164 = S166.S164
S165 = S166.S165


def _archive_member_bytes(archive: Path, suffix: str) -> bytes:
    cp = subprocess.run(["tar", "--zstd", "-tf", str(archive)], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    require(cp.returncode == 0, cp.stderr.decode("utf-8", errors="replace").strip() or "cannot list stage166 archive")
    names = cp.stdout.decode("utf-8", errors="replace").splitlines()
    matches = [n for n in names if n.endswith("/" + suffix) or n == suffix]
    require(len(matches) == 1, f"stage166 archive expected exactly one {suffix}, found {len(matches)}")
    cp = subprocess.run(["tar", "--zstd", "-xOf", str(archive), matches[0]], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    require(cp.returncode == 0, cp.stderr.decode("utf-8", errors="replace").strip() or f"cannot read {suffix} from stage166 archive")
    return cp.stdout


def verify_stage166_contract(project_root: Path) -> dict[str, Any]:
    archive = project_root / ".local/reports/quartet_restoration" / STAGE166_REPORT
    require(archive.is_file(), f"missing canonical stage166 report: {archive}")
    actual = sha256_file(archive)
    require(actual == STAGE166_SHA256, f"stage166 report SHA-256 drift: {actual}")
    summary = json.loads(_archive_member_bytes(archive, "SUMMARY.json").decode("utf-8"))
    require(summary.get("stage") == 166, "stage166 SUMMARY stage drift")
    require(summary.get("fresh_process_anchor_reacquisition_performed") is True, "stage166 did not use fresh-process reacquisition")
    require(summary.get("historical_stage165_absolute_addresses_reused") is False, "stage166 reused historical absolute addresses")
    require(int(summary.get("fresh_anchor_site_rows", 0)) >= 1, "stage166 has no fresh anchor sites")
    require(int(summary.get("recurrent_wet_pointer_candidate_rows", 0)) >= 1, "stage166 has no recurrent wet pointer candidates")
    return summary


def verify_prerequisites(project_root: Path, game_root: Path) -> tuple[dict[str, Any], str]:
    summary = verify_stage166_contract(project_root)
    pak = game_root / "Data/PACK10_02.PAK"
    require(pak.is_file(), f"missing Quartet PACK10_02: {pak}")
    baseline = sha256_file(pak)
    require(baseline == PACK10_02_BASELINE_SHA256, f"PACK10_02 is not exact baseline: {baseline}")
    return summary, baseline


def safe_site_id(site: Mapping[str, Any]) -> str:
    raw = f"{site.get('site_mapping_key','')}:{int(site.get('site_mapping_relative_offset') or 0)}"
    return "anchor_" + hashlib.sha256(raw.encode()).hexdigest()[:12]


def _printable_ascii_runs(data: bytes) -> list[str]:
    out: list[str] = []
    for m in re.finditer(rb"[\x20-\x7e]{4,160}", data):
        try:
            out.append(m.group().decode("ascii"))
        except UnicodeDecodeError:
            pass
    return out


def _utf16_runs(data: bytes) -> list[str]:
    out: list[str] = []
    for shift in (0, 1):
        text = data[shift:].decode("utf-16le", errors="ignore")
        for m in re.finditer(r"[\x20-\x7e]{4,160}", text):
            out.append(m.group())
    return out


def extract_allowlisted_tokens(data: bytes) -> tuple[list[str], list[str]]:
    """Return safe asset basenames and bounded technical keywords only."""
    strings = _printable_ascii_runs(data) + _utf16_runs(data)
    assets: set[str] = set()
    terms: set[str] = set()
    for text in strings:
        for match in ASSET_RE.finditer(text):
            token = match.group(1).replace("\\", "/").split("/")[-1]
            if 2 <= len(token) <= MAX_TOKEN_LENGTH:
                assets.add(token)
        low = text.casefold()
        for term in TECHNICAL_TERMS:
            if term in low:
                terms.add(term)
    return sorted(assets)[:MAX_TOKENS_PER_OBSERVATION], sorted(terms)[:MAX_TOKENS_PER_OBSERVATION]


def _mapping_public(m: Any, game_root: Path, pointer: int) -> dict[str, Any]:
    cls, base, path_hash = S164.normalized_mapping_path(m, game_root)
    return {
        "mapping_key": S164.mapping_key(m),
        "mapping_class": cls,
        "mapping_permissions": m.perms,
        "mapping_path_basename": base,
        "mapping_path_sha256": path_hash,
        "mapping_relative_offset": pointer - m.start,
    }


def _read_bounded(reader: Any, m: Any, address: int, radius: int) -> bytes:
    lo = max(m.start, address - radius)
    hi = min(m.end, address + radius)
    if hi <= lo:
        return b""
    try:
        data = reader.read(lo, hi - lo)
    except (OSError, PermissionError):
        return b""
    return data if len(data) == hi - lo else b""


def observe_pointer_target(reader: Any, maps: Sequence[Any], game_root: Path, pointer: int) -> dict[str, Any]:
    m = S166.mapping_for_address(maps, pointer)
    if m is None or "r" not in m.perms:
        return {
            "mapped": False, "mapping_key": "", "mapping_class": "unmapped", "mapping_permissions": "",
            "mapping_path_basename": "", "mapping_path_sha256": "", "mapping_relative_offset": "",
            "context_sha256": "", "direct_asset_tokens": [], "direct_technical_terms": [],
            "one_hop_asset_tokens": [], "one_hop_technical_terms": [], "one_hop_token_pointer_rows": 0,
        }
    data = _read_bounded(reader, m, pointer, TARGET_RADIUS)
    assets, terms = extract_allowlisted_tokens(data)
    one_assets: set[str] = set()
    one_terms: set[str] = set()
    one_rows = 0
    seen: set[int] = set()
    if data:
        # Bounded one-hop discovery. We export no secondary absolute pointers.
        for off in range(0, len(data) - 7, 8):
            value = struct.unpack_from("<Q", data, off)[0]
            if value in seen or value == pointer:
                continue
            sm = S166.mapping_for_address(maps, value)
            if sm is None or "r" not in sm.perms:
                continue
            seen.add(value)
            secondary = _read_bounded(reader, sm, value, SECONDARY_RADIUS)
            if not secondary:
                continue
            a2, t2 = extract_allowlisted_tokens(secondary)
            if not a2 and not t2:
                continue
            one_assets.update(a2)
            one_terms.update(t2)
            one_rows += 1
            if one_rows >= MAX_SECONDARY_POINTERS:
                break
    result = {"mapped": True, "context_sha256": sha256_bytes(data) if data else ""}
    result.update(_mapping_public(m, game_root, pointer))
    result.update({
        "direct_asset_tokens": assets,
        "direct_technical_terms": terms,
        "one_hop_asset_tokens": sorted(one_assets)[:MAX_TOKENS_PER_OBSERVATION],
        "one_hop_technical_terms": sorted(one_terms)[:MAX_TOKENS_PER_OBSERVATION],
        "one_hop_token_pointer_rows": one_rows,
    })
    return result


def changed_pointer_fields(
    sites: Sequence[Mapping[str, Any]],
    wet_blobs: Mapping[int, bytes],
    dry_blobs: Mapping[int, bytes],
    wet_maps: Sequence[Any],
    dry_maps: Sequence[Any],
    game_root: Path,
) -> list[dict[str, Any]]:
    """Provisional WET1!=DRY qword pointers; semantics intentionally unresolved."""
    rows: list[dict[str, Any]] = []
    for site in sites:
        addr = int(site["site_address"])
        if addr not in wet_blobs or addr not in dry_blobs:
            continue
        sid = safe_site_id(site)
        for rel in range(-S166.LOCAL_FIELD_RADIUS, S166.LOCAL_FIELD_RADIUS + 1, 8):
            wa = S166._field_slice(wet_blobs[addr], addr, rel, 8)
            da = S166._field_slice(dry_blobs[addr], addr, rel, 8)
            if wa is None or da is None or wa == da:
                continue
            wv = struct.unpack("<Q", wa)[0]
            dv = struct.unpack("<Q", da)[0]
            wc, _ = S166.pointer_mapping_descriptor(wet_maps, game_root, wv)
            dc, _ = S166.pointer_mapping_descriptor(dry_maps, game_root, dv)
            if not (wc.startswith("mapped_") or dc.startswith("mapped_")):
                continue
            rows.append({
                "anchor_id": sid,
                "relative_offset": rel,
                "wet_pointer": wv,
                "dry_pointer": dv,
                "wet_pointer_class": wc,
                "dry_pointer_class": dc,
            })
    return rows


def observation_public(anchor_id: str, rel: int, state: str, obs: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "anchor_id": anchor_id,
        "relative_offset": rel,
        "state": state,
        "target_mapped": bool(obs.get("mapped")),
        "target_mapping_key": obs.get("mapping_key", ""),
        "target_mapping_class": obs.get("mapping_class", ""),
        "target_mapping_permissions": obs.get("mapping_permissions", ""),
        "target_mapping_path_basename": obs.get("mapping_path_basename", ""),
        "target_mapping_path_sha256": obs.get("mapping_path_sha256", ""),
        "target_mapping_relative_offset": obs.get("mapping_relative_offset", ""),
        "target_context_sha256": obs.get("context_sha256", ""),
        "direct_asset_tokens": ";".join(obs.get("direct_asset_tokens", [])),
        "direct_technical_terms": ";".join(obs.get("direct_technical_terms", [])),
        "one_hop_asset_tokens": ";".join(obs.get("one_hop_asset_tokens", [])),
        "one_hop_technical_terms": ";".join(obs.get("one_hop_technical_terms", [])),
        "one_hop_token_pointer_rows": int(obs.get("one_hop_token_pointer_rows", 0)),
        "absolute_pointer_exported": False,
    }


def classify_binding_candidate(anchor_id: str, rel: int, dry: Mapping[str, Any], wet: Mapping[str, Any]) -> dict[str, Any]:
    dry_assets = set(dry.get("direct_asset_tokens", [])) | set(dry.get("one_hop_asset_tokens", []))
    wet_assets = set(wet.get("direct_asset_tokens", [])) | set(wet.get("one_hop_asset_tokens", []))
    dry_terms = set(dry.get("direct_technical_terms", [])) | set(dry.get("one_hop_technical_terms", []))
    wet_terms = set(wet.get("direct_technical_terms", [])) | set(wet.get("one_hop_technical_terms", []))
    wet_only_assets = sorted(wet_assets - dry_assets)
    dry_only_assets = sorted(dry_assets - wet_assets)
    wet_only_terms = sorted(wet_terms - dry_terms)
    token_supported = bool(wet_assets or dry_assets or wet_terms or dry_terms)
    state_distinct = (
        dry.get("mapping_key", "") != wet.get("mapping_key", "")
        or dry.get("context_sha256", "") != wet.get("context_sha256", "")
        or wet_only_assets or dry_only_assets or wet_only_terms
    )
    if wet_only_assets:
        cls = "wet_recurrent_pointer_chain_with_wet_only_asset_token_candidate_not_binding_semantics"
    elif wet_assets and state_distinct:
        cls = "wet_recurrent_pointer_chain_with_asset_token_state_difference_candidate_not_binding_semantics"
    elif wet_only_terms:
        cls = "wet_recurrent_pointer_chain_with_wet_only_render_term_candidate_not_binding_semantics"
    elif token_supported and state_distinct:
        cls = "wet_recurrent_pointer_chain_token_supported_state_difference_candidate_not_binding_semantics"
    elif state_distinct:
        cls = "wet_recurrent_pointer_target_state_difference_without_token_support"
    else:
        cls = "wet_recurrent_pointer_target_no_bounded_resource_difference"
    return {
        "anchor_id": anchor_id,
        "relative_offset": rel,
        "wet_only_asset_tokens": ";".join(wet_only_assets),
        "dry_only_asset_tokens": ";".join(dry_only_assets),
        "wet_only_technical_terms": ";".join(wet_only_terms),
        "dry_asset_tokens": ";".join(sorted(dry_assets)),
        "wet_asset_tokens": ";".join(sorted(wet_assets)),
        "dry_technical_terms": ";".join(sorted(dry_terms)),
        "wet_technical_terms": ";".join(sorted(wet_terms)),
        "token_supported": token_supported,
        "target_state_distinct": bool(state_distinct),
        "classification": cls,
        "material_binding_confirmed": False,
        "shader_binding_confirmed": False,
        "texture_binding_confirmed": False,
        "transparency_semantics_confirmed": False,
    }


def run_trace(project_root: Path, game_root: Path, *, interactive: bool = True) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    stage166_summary, baseline = verify_prerequisites(project_root, game_root)
    proc = S164.discover_game_process(game_root)
    pid = int(proc["pid"])

    def ensure_alive() -> None:
        require((Path("/proc") / str(pid)).is_dir(), "game process exited during stage167 trace")

    if interactive:
        print("\n[stage167] NEW PROCESS: no stage166 PID or absolute address is reused.")
        print("[stage167] Prepare Hinako / native School Uniform / DRY. Keep the same menu/state for all four captures.")
        input("[stage167] Press Enter to capture the fresh DRY1 discovery baseline... ")
    ensure_alive()
    dry_maps1 = S164.read_maps(pid)
    with S164.ProcessMemoryReader(pid) as reader:
        dry_model_rows, _ = S165.scan_wet_model_token(reader, dry_maps1, game_root, "stage167_dry1")

    if interactive:
        print("[stage167] Use native Change Wetness: DRY -> WET.")
        input("[stage167] Press Enter when WET is fully visible... ")
    ensure_alive()
    wet_maps1 = S164.read_maps(pid)
    with S164.ProcessMemoryReader(pid) as reader:
        wet_model_rows, _ = S165.scan_wet_model_token(reader, wet_maps1, game_root, "stage167_wet1")
        dynamic = S165.dynamic_wet_occurrences(dry_model_rows, wet_model_rows)
        pointer_rows, _ = S165.scan_pointers_to_dynamic_wet(reader, wet_maps1, game_root, dynamic)
    sites = S166.fresh_site_contracts(pointer_rows)
    require(sites, "fresh stage166-class wet-model pointer anchors were not reacquired; no historical addresses will be substituted")

    with S164.ProcessMemoryReader(pid) as reader:
        wet1_blobs, _ = S166.capture_site_state(reader, wet_maps1, game_root, sites, "stage167_wet1")

    if interactive:
        print(f"[stage167] Reacquired {len(sites)} fresh anchor site(s). Toggle WET -> DRY.")
        input("[stage167] Press Enter when DRY is fully visible... ")
    ensure_alive()
    dry_maps2 = S164.read_maps(pid)
    with S164.ProcessMemoryReader(pid) as reader:
        dry_blobs, _ = S166.capture_site_state(reader, dry_maps2, game_root, sites, "stage167_dry2")
        provisional = changed_pointer_fields(sites, wet1_blobs, dry_blobs, wet_maps1, dry_maps2, game_root)
        dry_observations: dict[tuple[str, int], dict[str, Any]] = {}
        for row in provisional:
            key = (row["anchor_id"], int(row["relative_offset"]))
            dry_observations[key] = observe_pointer_target(reader, dry_maps2, game_root, int(row["dry_pointer"]))

    if interactive:
        print(f"[stage167] DRY comparison found {len(provisional)} changed pointer-like fields. Toggle DRY -> WET once more.")
        input("[stage167] Press Enter when WET is fully visible again... ")
    ensure_alive()
    wet_maps2 = S164.read_maps(pid)
    with S164.ProcessMemoryReader(pid) as reader:
        wet2_blobs, _ = S166.capture_site_state(reader, wet_maps2, game_root, sites, "stage167_wet2")

    recurrent = S166.derive_wet_roundtrip_fields(sites, wet1_blobs, dry_blobs, wet2_blobs, wet_maps1, dry_maps2, wet_maps2, game_root)
    recurrent_ptr = [r for r in recurrent if r["field_kind"] == "recurrent_wet_qword_pointer_candidate"]
    site_by_hex = {f"0x{int(s['site_address']):x}": s for s in sites}

    observation_rows: list[dict[str, Any]] = []
    binding_rows: list[dict[str, Any]] = []
    with S164.ProcessMemoryReader(pid) as reader:
        for row in recurrent_ptr:
            site = site_by_hex.get(str(row["site_address_hex"]))
            if site is None:
                continue
            anchor_id = safe_site_id(site)
            rel = int(row["relative_offset"])
            key = (anchor_id, rel)
            dry_obs = dry_observations.get(key, {
                "mapped": False, "mapping_key": "", "mapping_class": "not_captured", "mapping_permissions": "",
                "mapping_path_basename": "", "mapping_path_sha256": "", "mapping_relative_offset": "",
                "context_sha256": "", "direct_asset_tokens": [], "direct_technical_terms": [],
                "one_hop_asset_tokens": [], "one_hop_technical_terms": [], "one_hop_token_pointer_rows": 0,
            })
            wet_pointer = int(str(row["wet2_value"]), 16)
            wet_obs = observe_pointer_target(reader, wet_maps2, game_root, wet_pointer)
            observation_rows.append(observation_public(anchor_id, rel, "dry2", dry_obs))
            observation_rows.append(observation_public(anchor_id, rel, "wet2", wet_obs))
            binding_rows.append(classify_binding_candidate(anchor_id, rel, dry_obs, wet_obs))

    baseline_after = sha256_file(game_root / "Data/PACK10_02.PAK")
    require(baseline_after == baseline == PACK10_02_BASELINE_SHA256, "PACK10_02 changed during read-only stage167 trace")

    stats = {
        "stage166_recurrent_pointer_candidate_rows": int(stage166_summary.get("recurrent_wet_pointer_candidate_rows", 0)),
        "fresh_dynamic_wet_model_rows": len(dynamic),
        "fresh_pointer_reference_rows": len(pointer_rows),
        "fresh_anchor_site_rows": len(sites),
        "provisional_changed_pointer_rows": len(provisional),
        "fresh_recurrent_pointer_rows": len(recurrent_ptr),
        "pointer_target_observation_rows": len(observation_rows),
        "token_supported_pointer_chain_rows": sum(1 for r in binding_rows if r["token_supported"]),
        "wet_only_asset_token_candidate_rows": sum(1 for r in binding_rows if r["wet_only_asset_tokens"]),
        "target_state_distinct_rows": sum(1 for r in binding_rows if r["target_state_distinct"]),
        "baseline_before": baseline,
        "baseline_after": baseline_after,
    }
    return stats, observation_rows, binding_rows, [
        {
            "anchor_id": safe_site_id(s),
            "site_mapping_key": s.get("site_mapping_key", ""),
            "site_mapping_relative_offset": int(s.get("site_mapping_relative_offset") or 0),
            "absolute_site_address_exported": False,
        }
        for s in sites
    ]


def build_report(project_root: Path, game_root: Path, *, interactive: bool = True, report_root: Path | None = None, output_report_root: Path | None = None, create_archive: bool = True) -> tuple[Path | None, dict[str, Any]]:
    project_root = S164.safe_resolve(project_root)
    game_root = S164.safe_resolve(game_root)
    report_root = report_root or project_root / ".local/reports/quartet_restoration" / REPORT_DIR
    output_report_root = output_report_root or project_root / ".local/reports/quartet_restoration"
    if report_root.exists():
        import shutil
        shutil.rmtree(report_root)
    report_root.mkdir(parents=True, exist_ok=True)

    stats, observations, bindings, anchors = run_trace(project_root, game_root, interactive=interactive)
    token_rows = [r for r in bindings if r["token_supported"]]
    wet_only_asset_rows = [r for r in bindings if r["wet_only_asset_tokens"]]

    if wet_only_asset_rows:
        quality = "fresh_recurrent_pointer_chain_wet_only_asset_token_candidates_observed"
        next_action = "Inspect the token-supported candidate chains and correlate them with actual renderer/material state before any write; do not infer transparency from asset names alone."
    elif token_rows:
        quality = "fresh_recurrent_pointer_chain_token_supported_state_differences_observed"
        next_action = "Use the bounded token-supported pointer chains as the next renderer/material inspection anchors; no scalar or texture write is authorized."
    elif bindings:
        quality = "fresh_recurrent_pointer_targets_observed_without_bounded_resource_token_support"
        next_action = "Do not guess numeric fields. Escalate to an external render-state/resource capture synchronized to native Change Wetness, using only the fresh anchor classes for timing."
    else:
        quality = "fresh_stage166_class_anchor_reacquisition_failed_to_yield_recurrent_pointer_targets"
        next_action = "Do not repeat stage166 merely for counts. Recheck native state certainty or move to external render-state capture; never reuse historical absolute addresses."

    summary = {
        "format_version": 1,
        "type": "br_quartet_restoration_wet_render_resource_material_binding_trace_evidence_summary",
        "tool_version": TOOL_VERSION,
        "stage": STAGE,
        "status": "fresh_process_recurrent_pointer_target_resource_neighborhood_trace_complete_read_only",
        "stage166_report_sha256": STAGE166_SHA256,
        "stage166_broad_compound_scan_repeated": False,
        "stage166_historical_pid_reused": False,
        "stage166_historical_absolute_addresses_reused": False,
        "fresh_process_anchor_reacquisition_performed": True,
        "capture_sequence": "fresh DRY1 discovery -> native WET1 minimal anchor reacquisition -> native DRY2 changed-pointer target capture -> native WET2 recurrence + wet target capture",
        "fresh_dynamic_wet_model_rows": stats["fresh_dynamic_wet_model_rows"],
        "fresh_pointer_reference_rows": stats["fresh_pointer_reference_rows"],
        "fresh_anchor_site_rows": stats["fresh_anchor_site_rows"],
        "provisional_changed_pointer_rows": stats["provisional_changed_pointer_rows"],
        "fresh_recurrent_pointer_rows": stats["fresh_recurrent_pointer_rows"],
        "pointer_target_observation_rows": stats["pointer_target_observation_rows"],
        "token_supported_pointer_chain_rows": stats["token_supported_pointer_chain_rows"],
        "wet_only_asset_token_candidate_rows": stats["wet_only_asset_token_candidate_rows"],
        "target_state_distinct_rows": stats["target_state_distinct_rows"],
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

    write_tsv(report_root / "FRESH_ANCHOR_DESCRIPTORS.tsv", ["anchor_id", "site_mapping_key", "site_mapping_relative_offset", "absolute_site_address_exported"], anchors)
    write_tsv(report_root / "POINTER_TARGET_RESOURCE_OBSERVATIONS.tsv", [
        "anchor_id", "relative_offset", "state", "target_mapped", "target_mapping_key", "target_mapping_class",
        "target_mapping_permissions", "target_mapping_path_basename", "target_mapping_path_sha256", "target_mapping_relative_offset",
        "target_context_sha256", "direct_asset_tokens", "direct_technical_terms", "one_hop_asset_tokens",
        "one_hop_technical_terms", "one_hop_token_pointer_rows", "absolute_pointer_exported",
    ], observations)
    write_tsv(report_root / "RECURRENT_POINTER_RESOURCE_BINDING_CANDIDATES.tsv", [
        "anchor_id", "relative_offset", "wet_only_asset_tokens", "dry_only_asset_tokens", "wet_only_technical_terms",
        "dry_asset_tokens", "wet_asset_tokens", "dry_technical_terms", "wet_technical_terms", "token_supported",
        "target_state_distinct", "classification", "material_binding_confirmed", "shader_binding_confirmed",
        "texture_binding_confirmed", "transparency_semantics_confirmed",
    ], bindings)
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
        archive, summary = build_report(project_root, game_root, interactive=not a.no_interactive, report_root=a.report_root, output_report_root=a.output_report_root, create_archive=not a.no_archive)
        print(json.dumps(summary, indent=2, sort_keys=True))
        if archive:
            print(f"[stage167] evidence: {archive}")
        return 0
    except PermissionError as exc:
        print(f"[stage167] process-memory permission denied: {exc}", file=sys.stderr)
        return ACCESS_DENIED_EXIT
    except Stage167Error as exc:
        print(f"[stage167] ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
