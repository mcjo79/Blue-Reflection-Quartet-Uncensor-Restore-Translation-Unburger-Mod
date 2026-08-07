#!/usr/bin/env python3
"""Stage 160: read-only target-native BC3 alpha-injection feasibility audit.

Stage 159 showed that Original and Quartet both alter school-wet BC3 entry 43,
but the transitions are materially different.  Original wet entry 43 is a
256x256 BC3 payload whose decoded RGB is all zero and whose alpha mask is also
shared exactly by Original scl_wh:47.  Quartet wet entry 43 is 2048x2048 BC3
with its own RGB and a different alpha distribution.

This stage does NOT transplant the Original entry.  It constructs a temporary
Quartet-native candidate that preserves the complete target entry/header,
2048x2048 resolution, target BC3 colour blocks and all other G1T entries, while
replacing only the 8-byte BC3 alpha sub-blocks with the corresponding Original
wet alpha blocks replicated 8x8 in block space for each of the three mip
levels.  The candidate is reparsed and validated with gust_g1t, but is never
written to a PAK or installed game and is not included in evidence.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path, PurePosixPath
from typing import Any, Iterable, Mapping, Sequence

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT_DEFAULT = SCRIPT_DIR.parent.parent
TOOL_VERSION = "0.1.81"
REPORT_DIR = "hinako_wet_school_bc3_target_native_alpha_injection_feasibility_evidence"
REPORT_NAME = "BR_quartet_restoration_hinako_wet_school_bc3_target_native_alpha_injection_feasibility_evidence.tar.zst"
WORKSPACE_SUBDIR = Path("hinako_wet_texture_entry_differential")

STAGE159_REPORT = "BR_quartet_restoration_hinako_wet_school_bc3_alpha_transition_evidence.tar.zst"
STAGE159_SHA256 = "91c077ca408bed741d2cc297f4deec574bad361c16fc32b334f18666092e260d"
PACK10_02_BASELINE_SHA256 = "e798f39c3bcdbb11381197bddf9bd3ad8de6ccf5d7c0c78b22613046d47f5302"
SOURCE_WET_43_SHA = "17b555e973afa9a3c69d4db703daa104a848477095d0ad1e13ae35a900a88a7b"
TARGET_WET_43_SHA = "37b40e340476d9b7c6879aecace13a374854f011a838a7fe2b8bc54205fd0719"
SOURCE_PATH = "data/x64/character/pc00/pc00_scl_w.g1t"
TARGET_PATH = SOURCE_PATH
ENTRY_INDEX = 43
FORBIDDEN_REPORT_EXTENSIONS = (
    ".pak", ".g1m", ".g1t", ".g1s", ".g1e", ".g1em", ".elixir", ".elixir.gz",
    ".ebd", ".ebm", ".kps", ".dds", ".png", ".jpg", ".jpeg", ".webp",
)


class Stage160Error(RuntimeError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise Stage160Error(message)


def progress(message: str) -> None:
    print(f"[stage160] {message}", flush=True)


def histogram_scaled_exactly(source_hist: Sequence[int], candidate_hist: Sequence[int], scale: int) -> bool:
    """Return true when nearest-block replication preserves the source distribution exactly.

    Stage 160 expands each source BC3 block 8x8 in target block space, so each
    decoded source pixel occurs exactly 64 times in the 2048x2048 candidate.
    Raw histogram counts therefore must scale by 64; they must not be equal.
    """
    if scale <= 0 or len(source_hist) != len(candidate_hist):
        return False
    return all(int(c) == int(s) * scale for s, c in zip(source_hist, candidate_hist))


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(8 * 1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def load_module(path: Path, name: str) -> Any:
    require(path.is_file(), f"missing module: {path}")
    spec = importlib.util.spec_from_file_location(name, path)
    require(spec is not None and spec.loader is not None, f"cannot load module: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def safe_relative(value: str, label: str) -> str:
    p = PurePosixPath(str(value).replace("\\", "/"))
    require(p.parts and not p.is_absolute() and ".." not in p.parts, f"unsafe {label}: {value}")
    return p.as_posix()


def write_tsv(path: Path, fields: Sequence[str], rows: Iterable[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(fields), delimiter="\t", lineterminator="\n", extrasaction="ignore")
        w.writeheader()
        for row in rows:
            w.writerow({field: row.get(field, "") for field in fields})


def make_archive(source: Path, output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    tmp = output.with_name(output.name + ".tmp")
    tmp.unlink(missing_ok=True)
    cp = subprocess.run(["tar", "--zstd", "-cf", str(tmp), "-C", str(source.parent), source.name], capture_output=True, text=True)
    require(cp.returncode == 0, cp.stderr.strip() or "report archive creation failed")
    os.replace(tmp, output)


def verify_stage159(report_root: Path) -> dict[str, Any]:
    archive = report_root / STAGE159_REPORT
    require(archive.is_file(), f"missing prerequisite report: {archive}")
    actual = sha256_file(archive)
    require(actual == STAGE159_SHA256, f"stage159 evidence SHA-256 drift: {actual}")
    with tempfile.TemporaryDirectory(prefix="stage160-prereq-") as td:
        cp = subprocess.run(["tar", "--zstd", "-tf", str(archive)], capture_output=True, text=True)
        require(cp.returncode == 0, cp.stderr.strip() or "cannot list stage159 report")
        names = [safe_relative(x.strip(), "report member") for x in cp.stdout.splitlines() if x.strip()]
        roots = {PurePosixPath(x).parts[0] for x in names}
        require(len(roots) == 1 and names, "unexpected stage159 report structure")
        require(not any(x.casefold().endswith(FORBIDDEN_REPORT_EXTENSIONS) for x in names), "proprietary payload in stage159 evidence")
        cp = subprocess.run(["tar", "--zstd", "-xf", str(archive), "-C", td], capture_output=True, text=True)
        require(cp.returncode == 0, cp.stderr.strip() or "cannot extract stage159 report")
        root = Path(td) / next(iter(roots))
        summary = json.loads((root / "SUMMARY.json").read_text(encoding="utf-8"))
    require(summary.get("tool_version") == "0.1.79", "stage159 tool version drift")
    require(summary.get("source_school_alpha_changed_ratio", 0) > 0.99, "stage159 source alpha transition drift")
    require(summary.get("target_school_alpha_changed_ratio", 0) > 0.99, "stage159 target alpha transition drift")
    require(summary.get("source_wet_sibling_alpha_exact_equal") is True, "stage159 source sibling control drift")
    require(summary.get("target_wet_sibling_alpha_exact_equal") is False, "stage159 target sibling control drift")
    require(summary.get("write_candidate_rows") == 0, "stage159 unexpectedly authorized writes")
    return summary


def bc3_mip_layout(width: int, height: int, mipmaps: int) -> list[dict[str, int]]:
    require(width > 0 and height > 0 and mipmaps > 0, "invalid mip layout")
    rows: list[dict[str, int]] = []
    offset = 0
    w, h = width, height
    for level in range(mipmaps):
        bw = max(1, (w + 3) // 4)
        bh = max(1, (h + 3) // 4)
        size = bw * bh * 16
        rows.append({"level": level, "width": w, "height": h, "block_width": bw, "block_height": bh, "offset": offset, "size": size})
        offset += size
        w = max(1, w // 2)
        h = max(1, h // 2)
    return rows


def inject_scaled_bc3_alpha(source_payload: bytes, source_width: int, source_height: int, source_mips: int,
                            target_payload: bytes, target_width: int, target_height: int, target_mips: int) -> tuple[bytes, list[dict[str, Any]]]:
    """Preserve target BC3 colour blocks and inject nearest block-scaled source alpha blocks."""
    require(source_mips == target_mips, "source/target mip count mismatch")
    src_layout = bc3_mip_layout(source_width, source_height, source_mips)
    tgt_layout = bc3_mip_layout(target_width, target_height, target_mips)
    require(sum(x["size"] for x in src_layout) == len(source_payload), "source BC3 payload size mismatch")
    require(sum(x["size"] for x in tgt_layout) == len(target_payload), "target BC3 payload size mismatch")
    out = bytearray(target_payload)
    audit: list[dict[str, Any]] = []
    for s, t in zip(src_layout, tgt_layout):
        require(t["block_width"] % s["block_width"] == 0 and t["block_height"] % s["block_height"] == 0, "non-integral BC3 block scaling")
        sx = t["block_width"] // s["block_width"]
        sy = t["block_height"] // s["block_height"]
        require(sx == sy and sx > 0, "anisotropic/zero BC3 block scaling")
        changed_alpha_bytes = 0
        for ty in range(t["block_height"]):
            syi = ty // sy
            for tx in range(t["block_width"]):
                sxi = tx // sx
                so = s["offset"] + (syi * s["block_width"] + sxi) * 16
                to = t["offset"] + (ty * t["block_width"] + tx) * 16
                src_alpha = source_payload[so:so + 8]
                old_alpha = bytes(out[to:to + 8])
                changed_alpha_bytes += sum(a != b for a, b in zip(old_alpha, src_alpha))
                out[to:to + 8] = src_alpha
                # bytes 8:16 are deliberately target colour and remain untouched
        audit.append({
            "mip_level": s["level"],
            "source_width": s["width"], "source_height": s["height"],
            "target_width": t["width"], "target_height": t["height"],
            "source_block_width": s["block_width"], "source_block_height": s["block_height"],
            "target_block_width": t["block_width"], "target_block_height": t["block_height"],
            "block_scale": sx,
            "target_blocks": t["block_width"] * t["block_height"],
            "changed_alpha_bytes": changed_alpha_bytes,
            "target_color_bytes_preserved": True,
        })
    return bytes(out), audit


def _raw_entry(data: bytes, parsed: Mapping[str, Any], idx: int) -> bytes:
    row = parsed["entries"][idx]
    start = int(row["entry_offset"])
    return data[start:start + int(row["entry_size"])]


def _payload(data: bytes, parsed: Mapping[str, Any], idx: int) -> bytes:
    row = parsed["entries"][idx]
    raw = _raw_entry(data, parsed, idx)
    return raw[int(row["payload_offset_in_entry"]):]


def build_report(project_root: Path, *, report_root: Path | None = None, output_report_root: Path | None = None,
                 workspace_root: Path | None = None, original_root: Path | None = None, quartet_root: Path | None = None,
                 gust_pak_path: Path | None = None, gust_g1t_path: Path | None = None,
                 verify_payload_hashes: bool = True, create_archive: bool = True, timeout_seconds: int = 1800) -> tuple[Path | None, dict[str, Any]]:
    project_root = project_root.resolve()
    version = (project_root / "workstreams/quartet_restoration/VERSION").read_text(encoding="utf-8").strip()
    require(tuple(map(int, version.split("."))) >= tuple(map(int, TOOL_VERSION.split("."))), f"expected {TOOL_VERSION} or newer, found {version}")
    report_root = (report_root or project_root / ".local/reports/quartet_restoration").resolve()
    output_report_root = (output_report_root or report_root).resolve()
    workspace_root = (workspace_root or project_root / ".local/workspaces/quartet_restoration" / WORKSPACE_SUBDIR).resolve()
    gust_g1t_path = (gust_g1t_path or project_root / ".local/vendor/gust_tools/gust_g1t").resolve()
    out = output_report_root / REPORT_DIR
    archive = output_report_root / REPORT_NAME
    if out.exists():
        import shutil
        shutil.rmtree(out)
    out.mkdir(parents=True)

    stage159 = verify_stage159(report_root)
    progress("stage159 verified; rehydrating source/target scl_w G1T read-only")
    st125 = load_module(project_root / "workstreams/quartet_restoration/125_collect_character_state_exact_rehydration_evidence.py", "stage160_st125")
    st155 = load_module(project_root / "workstreams/quartet_restoration/155_collect_hinako_wet_texture_entry_differential_evidence.py", "stage160_st155")
    st156 = load_module(project_root / "workstreams/quartet_restoration/156_collect_hinako_wet_texture_content_alpha_rebuild_feasibility_evidence.py", "stage160_st156")
    st159 = load_module(project_root / "workstreams/quartet_restoration/159_collect_hinako_wet_school_bc3_alpha_transition_evidence.py", "stage160_st159")
    br = load_module(project_root / "Blue_Reflection_Text_Tool/br_restoration_tool.py", "stage160_br")
    inventories = st125.load_asset_inventories(project_root)
    extraction = st125.ensure_extraction_cache(project_root=project_root, workspace_root=workspace_root, inventories=inventories,
        required_paths=[SOURCE_PATH], original_root=original_root, quartet_root=quartet_root, gust_pak_path=gust_pak_path, br=br,
        timeout_seconds=timeout_seconds)

    loaded: dict[str, tuple[bytes, dict[str, Any], dict[str, Any]]] = {}
    input_rows: list[dict[str, Any]] = []
    for side in ("source", "target"):
        key = (side, SOURCE_PATH.casefold())
        require(key in inventories, f"missing inventory row: {key}")
        pair_id, inv = inventories[key]
        local = br.inventory_workspace_file(workspace_root, side, pair_id, str(inv["archive"]), str(inv["path"]))
        require(local.is_file(), f"missing extracted G1T: {local}")
        actual = sha256_file(local)
        if verify_payload_hashes:
            require(actual == str(inv["sha256"]), f"payload hash drift {side}: {actual}")
        data = local.read_bytes()
        parsed = st155.parse_g1t(data, f"{side}:scl_w")
        require(parsed["texture_count"] == 54, f"unexpected texture count {side}: {parsed['texture_count']}")
        row = parsed["entries"][ENTRY_INDEX]
        require(int(row["texture_type"]) == 0x5B and int(row["mipmaps"]) == 3, f"unexpected BC3 contract {side}:43")
        loaded[side] = (data, parsed, row)
        input_rows.append({"side": side, "normalized_path": SOURCE_PATH, "sha256": actual, "size": len(data), "texture_count": parsed["texture_count"], "payload_in_evidence": False})

    source_data, source_parsed, source_row = loaded["source"]
    target_data, target_parsed, target_row = loaded["target"]
    require(source_row["payload_sha256"] == SOURCE_WET_43_SHA, "source wet entry43 payload drift")
    require(target_row["payload_sha256"] == TARGET_WET_43_SHA, "target wet entry43 payload drift")
    require((int(source_row["width"]), int(source_row["height"])) == (256, 256), "source dimensions drift")
    require((int(target_row["width"]), int(target_row["height"])) == (2048, 2048), "target dimensions drift")
    source_payload = _payload(source_data, source_parsed, ENTRY_INDEX)
    target_payload = _payload(target_data, target_parsed, ENTRY_INDEX)
    candidate_payload, mip_rows = inject_scaled_bc3_alpha(source_payload, 256, 256, 3, target_payload, 2048, 2048, 3)

    # BC3 alpha injection must preserve every target colour byte.
    target_layout = bc3_mip_layout(2048, 2048, 3)
    for mip in target_layout:
        for off in range(mip["offset"], mip["offset"] + mip["size"], 16):
            require(candidate_payload[off + 8:off + 16] == target_payload[off + 8:off + 16], "target BC3 colour block changed")

    target_raw = _raw_entry(target_data, target_parsed, ENTRY_INDEX)
    po = int(target_row["payload_offset_in_entry"])
    require(len(candidate_payload) == len(target_payload), "candidate target payload size changed")
    candidate_raw = target_raw[:po] + candidate_payload
    require(len(candidate_raw) == len(target_raw), "candidate raw entry size changed")
    require(candidate_raw[:po] == target_raw[:po], "target G1T entry header changed")

    start = int(target_row["entry_offset"])
    candidate_g1t = target_data[:start] + candidate_raw + target_data[start + len(target_raw):]
    require(len(candidate_g1t) == len(target_data), "candidate G1T size changed")
    candidate_parsed = st155.parse_g1t(candidate_g1t, "candidate:scl_w")
    require(candidate_parsed["texture_count"] == target_parsed["texture_count"], "candidate texture count drift")

    changed_entries: list[int] = []
    for idx in range(target_parsed["texture_count"]):
        if _raw_entry(candidate_g1t, candidate_parsed, idx) != _raw_entry(target_data, target_parsed, idx):
            changed_entries.append(idx)
    require(changed_entries == [ENTRY_INDEX], f"candidate changed unexpected G1T entries: {changed_entries}")

    src_alpha, src_luma = st159.decode_bc3_base_channels(source_payload, 256, 256)
    tgt_alpha, tgt_luma = st159.decode_bc3_base_channels(target_payload, 2048, 2048)
    cand_alpha, cand_luma = st159.decode_bc3_base_channels(candidate_payload, 2048, 2048)
    require(cand_luma == tgt_luma, "candidate luma/RGB changed")
    src_stats = st159.channel_stats(src_alpha)
    tgt_stats = st159.channel_stats(tgt_alpha)
    cand_stats = st159.channel_stats(cand_alpha)
    require(len(cand_alpha) % len(src_alpha) == 0, "candidate/source alpha sample count ratio is non-integral")
    alpha_sample_scale = len(cand_alpha) // len(src_alpha)
    require(alpha_sample_scale == 64, f"unexpected candidate/source alpha sample scale: {alpha_sample_scale}")
    require(histogram_scaled_exactly(src_stats["histogram"], cand_stats["histogram"], alpha_sample_scale),
            "candidate alpha histogram does not preserve source mask distribution after 8x8 replication")
    require(src_stats["mean"] == cand_stats["mean"], "candidate alpha mean drift from source mask")

    with tempfile.TemporaryDirectory(prefix="stage160-candidate-") as tempdir:
        candidate_path = Path(tempdir) / "pc00_scl_w.g1t"
        candidate_path.write_bytes(candidate_g1t)
        gust_status, gust_count = st156.gust_list(gust_g1t_path, candidate_path, timeout=timeout_seconds)
    require(gust_status == "ok" and gust_count == 54, f"gust_g1t validation failed: status={gust_status} count={gust_count}")

    alpha_rows = [
        {"variant": "source_original_wet", "width": 256, "height": 256, "alpha_min": src_stats["min"], "alpha_max": src_stats["max"], "alpha_mean": src_stats["mean"], "alpha_std": src_stats["std"], "alpha_zero_ratio": src_stats["zero_ratio"], "payload_sha256": SOURCE_WET_43_SHA, "payload_in_evidence": False},
        {"variant": "target_quartet_wet", "width": 2048, "height": 2048, "alpha_min": tgt_stats["min"], "alpha_max": tgt_stats["max"], "alpha_mean": tgt_stats["mean"], "alpha_std": tgt_stats["std"], "alpha_zero_ratio": tgt_stats["zero_ratio"], "payload_sha256": TARGET_WET_43_SHA, "payload_in_evidence": False},
        {"variant": "candidate_target_rgb_source_alpha", "width": 2048, "height": 2048, "alpha_min": cand_stats["min"], "alpha_max": cand_stats["max"], "alpha_mean": cand_stats["mean"], "alpha_std": cand_stats["std"], "alpha_zero_ratio": cand_stats["zero_ratio"], "payload_sha256": sha256_bytes(candidate_payload), "payload_in_evidence": False},
    ]
    validation_rows = [
        {"check": "stage159_prerequisite_verified", "passed": True},
        {"check": "source_target_mip_count_equal_3", "passed": True},
        {"check": "integer_block_scale_8_all_mips", "passed": all(r["block_scale"] == 8 for r in mip_rows)},
        {"check": "target_resolution_preserved_2048", "passed": True},
        {"check": "target_entry_header_preserved", "passed": True},
        {"check": "target_bc3_colour_blocks_preserved", "passed": True},
        {"check": "candidate_g1t_size_preserved", "passed": True},
        {"check": "candidate_changed_exactly_entry43", "passed": changed_entries == [43]},
        {"check": "candidate_luma_exactly_target_wet", "passed": cand_luma == tgt_luma},
        {"check": "candidate_alpha_histogram_scaled_exactly_source_wet", "passed": histogram_scaled_exactly(src_stats["histogram"], cand_stats["histogram"], alpha_sample_scale)},
        {"check": "candidate_alpha_sample_scale_exactly_64", "passed": alpha_sample_scale == 64},
        {"check": "candidate_reparse_ok", "passed": True},
        {"check": "gust_g1t_lists_54", "passed": gust_status == "ok" and gust_count == 54},
    ]
    require(all(r["passed"] for r in validation_rows), "candidate validation failure")

    write_tsv(out / "INPUTS.tsv", ["side", "normalized_path", "sha256", "size", "texture_count", "payload_in_evidence"], input_rows)
    write_tsv(out / "MIP_ALPHA_INJECTION.tsv", ["mip_level", "source_width", "source_height", "target_width", "target_height", "source_block_width", "source_block_height", "target_block_width", "target_block_height", "block_scale", "target_blocks", "changed_alpha_bytes", "target_color_bytes_preserved"], mip_rows)
    write_tsv(out / "ALPHA_STATS.tsv", ["variant", "width", "height", "alpha_min", "alpha_max", "alpha_mean", "alpha_std", "alpha_zero_ratio", "payload_sha256", "payload_in_evidence"], alpha_rows)
    write_tsv(out / "CANDIDATE_VALIDATION.tsv", ["check", "passed"], validation_rows)
    extraction_fields = sorted({k for row in extraction for k in row}) if extraction else ["side", "archive_relative", "cache_action"]
    write_tsv(out / "EXTRACTION_INPUTS.tsv", extraction_fields, extraction)

    summary = {
        "type": "br_quartet_restoration_hinako_wet_school_bc3_target_native_alpha_injection_feasibility_evidence_summary",
        "format_version": 1,
        "tool_version": TOOL_VERSION,
        "status": "target_native_bc3_alpha_injection_candidate_structurally_feasible_no_write",
        "stage159_evidence_sha256": STAGE159_SHA256,
        "pack10_02_baseline_sha256": PACK10_02_BASELINE_SHA256,
        "source_entry43_payload_sha256": SOURCE_WET_43_SHA,
        "target_entry43_payload_sha256": TARGET_WET_43_SHA,
        "candidate_entry43_payload_sha256": sha256_bytes(candidate_payload),
        "source_resolution": [256, 256],
        "target_resolution": [2048, 2048],
        "mip_levels": 3,
        "block_scale_each_axis": 8,
        "changed_g1t_entry_rows": 1,
        "changed_g1t_entry_indices": [43],
        "target_entry_header_preserved": True,
        "target_bc3_colour_blocks_preserved": True,
        "target_luma_exactly_preserved": True,
        "source_alpha_histogram_preserved_in_candidate": True,
        "source_alpha_histogram_replication_scale": alpha_sample_scale,
        "candidate_reparse_ok": True,
        "gust_g1t_status": gust_status,
        "gust_g1t_texture_count": gust_count,
        "candidate_profile_built": False,
        "transparency_semantics_confirmed": False,
        "runtime_validated": False,
        "production_eligible": False,
        "validation_failures": 0,
        "policy": {
            "read_only": True,
            "candidate_payload_in_evidence": False,
            "source_payload_in_evidence": False,
            "whole_g1t_transplant": False,
            "whole_g1mm_or_g1mg_transplant": False,
            "target_rgb_replaced": False,
            "pak_repacked": False,
            "installed_game_modified": False,
            "write_authorized": False,
            "core_modified": False,
            "translation_modified": False,
            "legacy_dlc_modified": False,
            "git_modified": False,
        },
        "next_action": "Build a separate no-install Fast Test profile only if this evidence is reviewed: retain the runtime-supported School_Wet geometry and entry23 wet-surface component, and add only the target-native entry43 candidate that preserves Quartet RGB/resolution while injecting the scaled Original wet alpha mask. Do not activate without separate authorization and exact rollback safeguards.",
    }
    (out / "SUMMARY.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    for path in out.rglob("*"):
        if path.is_file():
            rel = path.relative_to(out).as_posix().casefold()
            require(not rel.endswith(FORBIDDEN_REPORT_EXTENSIONS), f"forbidden payload in report: {rel}")
    if create_archive:
        make_archive(out, archive)
        progress(f"report archive: {archive}")
        return archive, summary
    return None, summary


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--project-root", type=Path, default=PROJECT_ROOT_DEFAULT)
    p.add_argument("--report-root", type=Path)
    p.add_argument("--output-report-root", type=Path)
    p.add_argument("--workspace-root", type=Path)
    p.add_argument("--original-root", type=Path)
    p.add_argument("--quartet-root", type=Path)
    p.add_argument("--gust-pak", type=Path)
    p.add_argument("--gust-g1t", type=Path)
    p.add_argument("--timeout-seconds", type=int, default=1800)
    p.add_argument("--no-verify-payload-hashes", action="store_true")
    p.add_argument("--no-archive", action="store_true")
    return p.parse_args()


def main() -> int:
    a = parse_args()
    archive, summary = build_report(a.project_root, report_root=a.report_root, output_report_root=a.output_report_root,
        workspace_root=a.workspace_root, original_root=a.original_root, quartet_root=a.quartet_root,
        gust_pak_path=a.gust_pak, gust_g1t_path=a.gust_g1t, timeout_seconds=a.timeout_seconds,
        verify_payload_hashes=not a.no_verify_payload_hashes, create_archive=not a.no_archive)
    print(json.dumps(summary, indent=2, sort_keys=True))
    if archive:
        print(archive)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
