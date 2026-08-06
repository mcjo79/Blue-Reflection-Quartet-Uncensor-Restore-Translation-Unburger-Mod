#!/usr/bin/env python3
"""Stage 159: read-only BC3 alpha transition audit for Hinako wet-school textures.

Runtime stage 158 established that restoring G1T entry 23 adds a visible wet
skin/droplet component but does not restore wet-shirt transparency.  Stage 155
also identified a separate school-wet-only BC3 payload shared exactly by
Original ``scl_w:43`` and ``scl_wh:47``.  Quartet retains BC3 entries at the
same logical positions, but with different payloads and higher resolution.

This stage therefore compares alpha and luma transitions without exporting any
image payloads and without authorizing a write:

* Original scl:43 dry -> scl_w:43 wet;
* Quartet  scl:43 dry -> scl_w:43 wet;
* Original scl_w:43 -> scl_wh:47 sibling wet control;
* Quartet  scl_w:43 -> scl_wh:47 sibling wet control.

The output is metadata/statistics only.  No G1T, PAK or installed game is
modified and no texture is assigned transparency semantics from statistics
alone.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import importlib.util
import json
import math
import os
import struct
import subprocess
import sys
import tempfile
from pathlib import Path, PurePosixPath
from typing import Any, Iterable, Mapping, Sequence

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT_DEFAULT = SCRIPT_DIR.parent.parent
TOOL_VERSION = "0.1.79"
REPORT_DIR = "hinako_wet_school_bc3_alpha_transition_evidence"
REPORT_NAME = "BR_quartet_restoration_hinako_wet_school_bc3_alpha_transition_evidence.tar.zst"
WORKSPACE_SUBDIR = Path("hinako_wet_texture_entry_differential")

STAGE155_REPORT = "BR_quartet_restoration_hinako_wet_texture_entry_differential_evidence.tar.zst"
STAGE155_SHA256 = "91944b1da27e935695cb8c8c6781b276995cf9798b60262e810bfe385573da0d"
STAGE158_ACTIVATION_REPORT = "BR_quartet_restoration_hinako_wet_school_entry23_fast_test_lab_activation_evidence.tar.zst"
STAGE158_ACTIVATION_SHA256 = "e792b19ebe128469db689b68059ddb4de5180dbc1c0765df1b4e1fb9a967084e"
STAGE158_ROLLBACK_REPORT = "BR_quartet_restoration_hinako_wet_school_entry23_fast_test_lab_rollback_evidence.tar.zst"
STAGE158_ROLLBACK_SHA256 = "7789949d0e99d1f530ea92d6f5d2f90c6c94b89049061319f1f8ce0703340c6b"
STAGE158_PROFILE_SHA256 = "9b70d0cff0ef86666b223fdcfe105b54dff25d6db664a3c965d9e748d85fa9fc"
PACK10_02_BASELINE_SHA256 = "e798f39c3bcdbb11381197bddf9bd3ad8de6ccf5d7c0c78b22613046d47f5302"

SOURCE_DRY_43_SHA = "52f2edd564c6ddd9b4c267d0804089d0e86660edc447810011d6e7d7cd1618d6"
SOURCE_WET_43_SHA = "17b555e973afa9a3c69d4db703daa104a848477095d0ad1e13ae35a900a88a7b"
SOURCE_WET_SIBLING_47_SHA = SOURCE_WET_43_SHA
TARGET_DRY_43_SHA = "011cd8d85dbe02d8639ccaad1a2dc3352ac7488824372c859734f671439f9fed"
TARGET_WET_43_SHA = "37b40e340476d9b7c6879aecace13a374854f011a838a7fe2b8bc54205fd0719"
TARGET_WET_SIBLING_47_SHA = "875073e887267e6760d3c406f151a0e2689120cf86b370ee3b80875559fd2649"

PACKS = (
    ("scl", "data/x64/character/pc00/pc00_scl.g1t"),
    ("scl_w", "data/x64/character/pc00/pc00_scl_w.g1t"),
    ("scl_wh", "data/x64/character/pc00/pc00_scl_wh.g1t"),
)
FORBIDDEN_REPORT_EXTENSIONS = (
    ".pak", ".g1m", ".g1t", ".g1s", ".g1e", ".g1em", ".elixir", ".elixir.gz",
    ".ebd", ".ebm", ".kps", ".dds", ".png", ".jpg", ".jpeg", ".webp",
)


class Stage159Error(RuntimeError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise Stage159Error(message)


def progress(message: str) -> None:
    print(f"[stage159] {message}", flush=True)


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(8 * 1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def safe_relative(value: str, label: str) -> str:
    p = PurePosixPath(str(value).replace("\\", "/"))
    require(p.parts and not p.is_absolute() and ".." not in p.parts, f"unsafe {label}: {value}")
    return p.as_posix()


def load_module(path: Path, name: str) -> Any:
    require(path.is_file(), f"missing module: {path}")
    spec = importlib.util.spec_from_file_location(name, path)
    require(spec is not None and spec.loader is not None, f"cannot load module: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


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
    cp = subprocess.run(["tar", "--zstd", "-cf", str(tmp), "-C", str(source.parent), source.name], text=True, capture_output=True)
    require(cp.returncode == 0, cp.stderr.strip() or "report archive creation failed")
    os.replace(tmp, output)


def _verified_report_summary(report_root: Path, name: str, expected_sha256: str) -> dict[str, Any]:
    archive = report_root / name
    require(archive.is_file(), f"missing prerequisite report: {archive}")
    actual = sha256_file(archive)
    require(actual == expected_sha256, f"evidence SHA-256 drift for {name}: {actual}")
    with tempfile.TemporaryDirectory(prefix="stage159-prereq-") as td:
        cp = subprocess.run(["tar", "--zstd", "-tf", str(archive)], text=True, capture_output=True)
        require(cp.returncode == 0, cp.stderr.strip() or f"cannot list {name}")
        names = [safe_relative(x.strip(), "report member") for x in cp.stdout.splitlines() if x.strip()]
        require(names, f"empty report archive: {name}")
        roots = {PurePosixPath(x).parts[0] for x in names}
        require(len(roots) == 1, f"unexpected report roots for {name}: {sorted(roots)}")
        require(not any(x.casefold().endswith(FORBIDDEN_REPORT_EXTENSIONS) for x in names), f"proprietary payload in {name}")
        cp = subprocess.run(["tar", "--zstd", "-xf", str(archive), "-C", td], text=True, capture_output=True)
        require(cp.returncode == 0, cp.stderr.strip() or f"cannot extract {name}")
        root = Path(td) / next(iter(roots))
        return json.loads((root / "SUMMARY.json").read_text(encoding="utf-8"))


def validate_runtime_prerequisites(report_root: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    activation = _verified_report_summary(report_root, STAGE158_ACTIVATION_REPORT, STAGE158_ACTIVATION_SHA256)
    rollback = _verified_report_summary(report_root, STAGE158_ROLLBACK_REPORT, STAGE158_ROLLBACK_SHA256)
    require(activation.get("operation") == "activation", "stage158 activation operation drift")
    require(rollback.get("operation") == "rollback", "stage158 rollback operation drift")
    for row in (activation, rollback):
        require(row.get("profile_sha256") == STAGE158_PROFILE_SHA256, "stage158 profile hash drift")
        require(row.get("baseline_sha256") == PACK10_02_BASELINE_SHA256, "stage158 baseline hash drift")
        require(row.get("protected_archives_unchanged") is True, "stage158 protected archive guard failed")
        require(row.get("runtime_validated") is False and row.get("production_eligible") is False, "stage158 promotion drift")
    require(activation.get("observed_target_sha256") == STAGE158_PROFILE_SHA256, "stage158 activation target drift")
    require(rollback.get("observed_target_sha256") == PACK10_02_BASELINE_SHA256, "stage158 rollback target drift")
    require(rollback.get("exact_pack10_02_baseline_restored") is True, "stage158 exact rollback not confirmed")
    return activation, rollback


def rgb565(value: int) -> tuple[int, int, int]:
    r = (value >> 11) & 31
    g = (value >> 5) & 63
    b = value & 31
    return ((r * 255 + 15) // 31, (g * 255 + 31) // 63, (b * 255 + 15) // 31)


def _interp(a: int, b: int, wa: int, wb: int, d: int) -> int:
    return (wa * a + wb * b) // d


def decode_bc3_base_channels(payload: bytes, width: int, height: int) -> tuple[bytes, bytes]:
    """Decode BC3 base mip to alpha + luma bytes, without exporting pixels."""
    require(width > 0 and height > 0, "invalid BC3 dimensions")
    bw = (width + 3) // 4
    bh = (height + 3) // 4
    need = bw * bh * 16
    require(len(payload) >= need, f"BC3 payload shorter than base mip: {len(payload)} < {need}")
    alpha = bytearray(width * height)
    luma = bytearray(width * height)
    off = 0
    for by in range(bh):
        for bx in range(bw):
            block = payload[off:off + 16]
            off += 16
            a0, a1 = block[0], block[1]
            abits = int.from_bytes(block[2:8], "little")
            ap = [a0, a1]
            if a0 > a1:
                ap += [((7 - i) * a0 + i * a1) // 7 for i in range(1, 7)]
            else:
                ap += [((5 - i) * a0 + i * a1) // 5 for i in range(1, 5)] + [0, 255]
            c0, c1, cbits = struct.unpack("<HHI", block[8:16])
            p0 = rgb565(c0)
            p1 = rgb565(c1)
            cp = [
                p0,
                p1,
                tuple(_interp(p0[j], p1[j], 2, 1, 3) for j in range(3)),
                tuple(_interp(p0[j], p1[j], 1, 2, 3) for j in range(3)),
            ]
            for py in range(4):
                y = by * 4 + py
                if y >= height:
                    continue
                for px in range(4):
                    x = bx * 4 + px
                    if x >= width:
                        continue
                    pi = py * 4 + px
                    ai = (abits >> (3 * pi)) & 7
                    ci = (cbits >> (2 * pi)) & 3
                    r, g, b = cp[ci]
                    idx = y * width + x
                    alpha[idx] = ap[ai]
                    luma[idx] = (54 * r + 183 * g + 19 * b + 128) // 256
    return bytes(alpha), bytes(luma)


def channel_stats(values: bytes) -> dict[str, Any]:
    require(values, "empty channel")
    n = len(values)
    total = sum(values)
    total2 = sum(v * v for v in values)
    mean = total / n
    var = max(0.0, total2 / n - mean * mean)
    hist = [0] * 16
    for v in values:
        hist[min(15, v // 16)] += 1
    nonopaque = sum(1 for v in values if v < 255)
    zero = sum(1 for v in values if v == 0)
    return {
        "min": min(values),
        "max": max(values),
        "mean": round(mean, 6),
        "std": round(math.sqrt(var), 6),
        "zero_ratio": round(zero / n, 8),
        "nonopaque_ratio": round(nonopaque / n, 8),
        "histogram": hist,
    }


def transition_stats(before: bytes, after: bytes) -> dict[str, Any]:
    require(len(before) == len(after) and before, "transition channels must be equal non-zero length")
    n = len(before)
    changed = 0
    abs_sum = 0
    signed_sum = 0
    sq_sum = 0
    sa = sb = saa = sbb = sab = 0
    for a, b in zip(before, after):
        d = int(b) - int(a)
        if d:
            changed += 1
        abs_sum += abs(d)
        signed_sum += d
        sq_sum += d * d
        sa += a
        sb += b
        saa += a * a
        sbb += b * b
        sab += a * b
    num = n * sab - sa * sb
    den_a = n * saa - sa * sa
    den_b = n * sbb - sb * sb
    corr = (num / math.sqrt(den_a * den_b)) if den_a > 0 and den_b > 0 else None
    return {
        "pixels": n,
        "changed_pixels": changed,
        "changed_ratio": round(changed / n, 8),
        "mean_abs_delta": round(abs_sum / n, 6),
        "mean_signed_delta": round(signed_sum / n, 6),
        "rms_delta": round(math.sqrt(sq_sum / n), 6),
        "correlation": "" if corr is None else round(corr, 8),
        "exact_equal": changed == 0,
    }


def _raw_entry(data: bytes, parsed: Mapping[str, Any], idx: int) -> bytes:
    row = parsed["entries"][idx]
    start = int(row["entry_offset"])
    return data[start:start + int(row["entry_size"])]


def _payload(data: bytes, parsed: Mapping[str, Any], idx: int) -> bytes:
    row = parsed["entries"][idx]
    raw = _raw_entry(data, parsed, idx)
    return raw[int(row["payload_offset_in_entry"]):]


def build_report(
    project_root: Path,
    *,
    report_root: Path | None = None,
    output_report_root: Path | None = None,
    workspace_root: Path | None = None,
    original_root: Path | None = None,
    quartet_root: Path | None = None,
    gust_pak_path: Path | None = None,
    verify_payload_hashes: bool = True,
    create_archive: bool = True,
    timeout_seconds: int = 1800,
) -> tuple[Path | None, dict[str, Any]]:
    project_root = project_root.resolve()
    version = (project_root / "workstreams/quartet_restoration/VERSION").read_text(encoding="utf-8").strip()
    require(tuple(map(int, version.split("."))) >= tuple(map(int, TOOL_VERSION.split("."))), f"expected {TOOL_VERSION} or newer, found {version}")
    report_root = (report_root or project_root / ".local/reports/quartet_restoration").resolve()
    output_report_root = (output_report_root or report_root).resolve()
    workspace_root = (workspace_root or project_root / ".local/workspaces/quartet_restoration" / WORKSPACE_SUBDIR).resolve()
    out = output_report_root / REPORT_DIR
    archive = output_report_root / REPORT_NAME
    if out.exists():
        import shutil
        shutil.rmtree(out)
    out.mkdir(parents=True)

    # Verify the static texture inventory and exact runtime activation/rollback chain.
    s155 = _verified_report_summary(report_root, STAGE155_REPORT, STAGE155_SHA256)
    require(s155.get("tool_version") == "0.1.73", "stage155 version drift")
    require(s155.get("candidate_common_wet_layer_rows") == 1, "stage155 candidate count drift")
    activation, rollback = validate_runtime_prerequisites(report_root)

    progress("stage-155 and stage-158 evidence verified; rehydrating school texture packs read-only")
    st155 = load_module(project_root / "workstreams/quartet_restoration/155_collect_hinako_wet_texture_entry_differential_evidence.py", "stage159_st155")
    st125 = load_module(project_root / "workstreams/quartet_restoration/125_collect_character_state_exact_rehydration_evidence.py", "stage159_st125")
    br = load_module(project_root / "Blue_Reflection_Text_Tool/br_restoration_tool.py", "stage159_br")
    inventories = st125.load_asset_inventories(project_root)
    required = [p for _, p in PACKS]
    extraction = st125.ensure_extraction_cache(
        project_root=project_root,
        workspace_root=workspace_root,
        inventories=inventories,
        required_paths=required,
        original_root=original_root,
        quartet_root=quartet_root,
        gust_pak_path=gust_pak_path,
        br=br,
        timeout_seconds=timeout_seconds,
    )

    data_map: dict[tuple[str, str], bytes] = {}
    parsed_map: dict[tuple[str, str], dict[str, Any]] = {}
    input_rows: list[dict[str, Any]] = []
    for side in ("source", "target"):
        for token, normalized in PACKS:
            key = (side, normalized.casefold())
            require(key in inventories, f"missing inventory entry: {key}")
            pair_id, entry = inventories[key]
            local = br.inventory_workspace_file(workspace_root, side, pair_id, str(entry["archive"]), str(entry["path"]))
            require(local.is_file(), f"missing extracted G1T: {local}")
            actual = sha256_file(local)
            if verify_payload_hashes:
                require(actual == str(entry["sha256"]), f"payload hash drift {side}:{token}:{actual}")
            data = local.read_bytes()
            parsed = st155.parse_g1t(data, f"{side}:{token}")
            data_map[(side, token)] = data
            parsed_map[(side, token)] = parsed
            input_rows.append({
                "side": side,
                "state_token": token,
                "normalized_path": normalized,
                "size": len(data),
                "sha256": actual,
                "texture_count": parsed["texture_count"],
                "payload_in_evidence": False,
            })

    specs = [
        ("source", "scl", 43, SOURCE_DRY_43_SHA, 256, 256),
        ("source", "scl_w", 43, SOURCE_WET_43_SHA, 256, 256),
        ("source", "scl_wh", 47, SOURCE_WET_SIBLING_47_SHA, 256, 256),
        ("target", "scl", 43, TARGET_DRY_43_SHA, 2048, 2048),
        ("target", "scl_w", 43, TARGET_WET_43_SHA, 2048, 2048),
        ("target", "scl_wh", 47, TARGET_WET_SIBLING_47_SHA, 2048, 2048),
    ]
    channels: dict[tuple[str, str, int], tuple[bytes, bytes]] = {}
    stats_rows: list[dict[str, Any]] = []
    histogram_rows: list[dict[str, Any]] = []
    for side, token, idx, expected_sha, expected_w, expected_h in specs:
        parsed = parsed_map[(side, token)]
        require(idx < parsed["texture_count"], f"missing texture index {side}:{token}:{idx}")
        row = parsed["entries"][idx]
        require(row["payload_sha256"] == expected_sha, f"payload SHA drift {side}:{token}:{idx}")
        require(int(row["texture_type"]) == 0x5B, f"expected BC3 at {side}:{token}:{idx}")
        require(int(row["width"]) == expected_w and int(row["height"]) == expected_h, f"dimension drift {side}:{token}:{idx}")
        payload = _payload(data_map[(side, token)], parsed, idx)
        alpha, luma = decode_bc3_base_channels(payload, expected_w, expected_h)
        channels[(side, token, idx)] = (alpha, luma)
        ast = channel_stats(alpha)
        lst = channel_stats(luma)
        stats_rows.append({
            "side": side,
            "state_token": token,
            "texture_index": idx,
            "payload_sha256": row["payload_sha256"],
            "width": expected_w,
            "height": expected_h,
            "format": "BC3",
            "alpha_min": ast["min"],
            "alpha_max": ast["max"],
            "alpha_mean": ast["mean"],
            "alpha_std": ast["std"],
            "alpha_zero_ratio": ast["zero_ratio"],
            "alpha_nonopaque_ratio": ast["nonopaque_ratio"],
            "luma_min": lst["min"],
            "luma_max": lst["max"],
            "luma_mean": lst["mean"],
            "luma_std": lst["std"],
            "payload_in_evidence": False,
        })
        for bin_index, count in enumerate(ast["histogram"]):
            histogram_rows.append({
                "side": side,
                "state_token": token,
                "texture_index": idx,
                "channel": "alpha",
                "bin_index": bin_index,
                "value_min": bin_index * 16,
                "value_max": 255 if bin_index == 15 else bin_index * 16 + 15,
                "pixel_count": count,
                "pixel_ratio": round(count / len(alpha), 8),
            })

    def pair_row(label: str, side: str, before_token: str, before_idx: int, after_token: str, after_idx: int) -> dict[str, Any]:
        ba, bl = channels[(side, before_token, before_idx)]
        aa, al = channels[(side, after_token, after_idx)]
        ad = transition_stats(ba, aa)
        ld = transition_stats(bl, al)
        return {
            "comparison": label,
            "side": side,
            "before": f"{before_token}:{before_idx}",
            "after": f"{after_token}:{after_idx}",
            "alpha_changed_pixels": ad["changed_pixels"],
            "alpha_changed_ratio": ad["changed_ratio"],
            "alpha_mean_abs_delta": ad["mean_abs_delta"],
            "alpha_mean_signed_delta": ad["mean_signed_delta"],
            "alpha_rms_delta": ad["rms_delta"],
            "alpha_correlation": ad["correlation"],
            "alpha_exact_equal": ad["exact_equal"],
            "luma_changed_ratio": ld["changed_ratio"],
            "luma_mean_abs_delta": ld["mean_abs_delta"],
            "luma_rms_delta": ld["rms_delta"],
            "luma_correlation": ld["correlation"],
            "transparency_semantics_confirmed": False,
            "write_authorized": False,
        }

    transition_rows = [
        pair_row("school_dry_to_wet", "source", "scl", 43, "scl_w", 43),
        pair_row("school_dry_to_wet", "target", "scl", 43, "scl_w", 43),
        pair_row("wet_school_sibling", "source", "scl_w", 43, "scl_wh", 47),
        pair_row("wet_school_sibling", "target", "scl_w", 43, "scl_wh", 47),
    ]
    src_transition = next(r for r in transition_rows if r["comparison"] == "school_dry_to_wet" and r["side"] == "source")
    tgt_transition = next(r for r in transition_rows if r["comparison"] == "school_dry_to_wet" and r["side"] == "target")
    src_sibling = next(r for r in transition_rows if r["comparison"] == "wet_school_sibling" and r["side"] == "source")
    tgt_sibling = next(r for r in transition_rows if r["comparison"] == "wet_school_sibling" and r["side"] == "target")

    runtime_rows = [{
        "profile_id": activation.get("profile_id", ""),
        "profile_sha256": STAGE158_PROFILE_SHA256,
        "runtime_tested": True,
        "runtime_stable": True,
        "model_integrity_preserved": True,
        "canonical_smaller_blue_neck_component_present": True,
        "wet_skin_or_droplet_effect_observed": True,
        "wet_skin_or_droplet_effect_matches_original_exactly": False,
        "wet_skin_or_droplet_user_description": "visible but somewhat more monolithic than Original reference",
        "wet_shirt_transparency_changed_vs_quartet_baseline": False,
        "wet_shirt_transparency_restored": False,
        "entry23_supported_as_wet_surface_component": True,
        "entry23_supported_as_transparency_component": False,
        "entry23_is_sole_droplet_mechanism_proven": False,
        "runtime_validated": False,
        "production_eligible": False,
        "exact_pack10_02_baseline_restored": rollback.get("exact_pack10_02_baseline_restored") is True,
    }]

    stats_fields = [
        "side", "state_token", "texture_index", "payload_sha256", "width", "height", "format",
        "alpha_min", "alpha_max", "alpha_mean", "alpha_std", "alpha_zero_ratio", "alpha_nonopaque_ratio",
        "luma_min", "luma_max", "luma_mean", "luma_std", "payload_in_evidence",
    ]
    transition_fields = [
        "comparison", "side", "before", "after", "alpha_changed_pixels", "alpha_changed_ratio",
        "alpha_mean_abs_delta", "alpha_mean_signed_delta", "alpha_rms_delta", "alpha_correlation", "alpha_exact_equal",
        "luma_changed_ratio", "luma_mean_abs_delta", "luma_rms_delta", "luma_correlation",
        "transparency_semantics_confirmed", "write_authorized",
    ]
    histogram_fields = ["side", "state_token", "texture_index", "channel", "bin_index", "value_min", "value_max", "pixel_count", "pixel_ratio"]
    runtime_fields = list(runtime_rows[0].keys())
    input_fields = ["side", "state_token", "normalized_path", "size", "sha256", "texture_count", "payload_in_evidence"]
    extraction_fields = sorted({k for row in extraction for k in row}) if extraction else ["side", "archive_relative", "cache_action"]

    write_tsv(out / "TEXTURE_ALPHA_LUMA_STATS.tsv", stats_fields, stats_rows)
    write_tsv(out / "ALPHA_HISTOGRAM_16BIN.tsv", histogram_fields, histogram_rows)
    write_tsv(out / "DRY_WET_AND_SIBLING_TRANSITIONS.tsv", transition_fields, transition_rows)
    write_tsv(out / "RUNTIME_OBSERVATION.tsv", runtime_fields, runtime_rows)
    write_tsv(out / "INPUTS.tsv", input_fields, input_rows)
    write_tsv(out / "EXTRACTION_INPUTS.tsv", extraction_fields, extraction)

    summary = {
        "type": "br_quartet_restoration_hinako_wet_school_bc3_alpha_transition_evidence_summary",
        "format_version": 1,
        "tool_version": TOOL_VERSION,
        "status": "entry23_runtime_droplet_component_confirmed_transparency_negative_bc3_alpha_audit_complete_no_write",
        "stage155_evidence_sha256": STAGE155_SHA256,
        "stage158_activation_evidence_sha256": STAGE158_ACTIVATION_SHA256,
        "stage158_rollback_evidence_sha256": STAGE158_ROLLBACK_SHA256,
        "stage158_profile_sha256": STAGE158_PROFILE_SHA256,
        "pack10_02_baseline_sha256": PACK10_02_BASELINE_SHA256,
        "runtime_observation": {
            "runtime_stable": True,
            "model_integrity_preserved": True,
            "canonical_smaller_blue_neck_component_present": True,
            "wet_skin_or_droplet_effect_observed": True,
            "wet_skin_or_droplet_effect_matches_original_exactly": False,
            "wet_shirt_transparency_restored": False,
            "entry23_runtime_supported_as_wet_surface_component": True,
            "entry23_runtime_supported_as_transparency_component": False,
            "exact_pack10_02_baseline_restored": True,
        },
        "texture_rows": len(stats_rows),
        "alpha_histogram_rows": len(histogram_rows),
        "transition_rows": len(transition_rows),
        "source_school_alpha_changed_ratio": src_transition["alpha_changed_ratio"],
        "source_school_alpha_mean_abs_delta": src_transition["alpha_mean_abs_delta"],
        "target_school_alpha_changed_ratio": tgt_transition["alpha_changed_ratio"],
        "target_school_alpha_mean_abs_delta": tgt_transition["alpha_mean_abs_delta"],
        "source_school_luma_mean_abs_delta": src_transition["luma_mean_abs_delta"],
        "target_school_luma_mean_abs_delta": tgt_transition["luma_mean_abs_delta"],
        "source_wet_sibling_alpha_exact_equal": src_sibling["alpha_exact_equal"],
        "target_wet_sibling_alpha_exact_equal": tgt_sibling["alpha_exact_equal"],
        "source_wet_sibling_payload_exact_by_stage155": True,
        "target_wet_sibling_payload_exact_by_stage155": False,
        "entry43_47_transparency_semantics_confirmed": False,
        "write_candidate_rows": 0,
        "runtime_validated": False,
        "production_eligible": False,
        "policy": {
            "read_only": True,
            "image_payload_exported": False,
            "raw_g1t_entry_exported": False,
            "g1t_rebuilt": False,
            "pak_repacked": False,
            "installed_game_modified": False,
            "entry43_or_47_write_authorized": False,
            "alpha_statistics_alone_assign_transparency_semantics": False,
            "entry23_promoted_as_complete_wet_restoration": False,
            "glowlight_modified": False,
            "core_modified": False,
            "legacy_dlc_modified": False,
            "translation_modified": False,
            "git_modified": False,
        },
        "next_action": "Review source-vs-target BC3 dry->wet alpha/luma transitions. If Original has a materially distinct alpha transition that Quartet lacks or substantially alters, perform a separate target-native content feasibility audit before any runtime texture probe; otherwise move to the Change Wetness before/after runtime resolution trace rather than guessing more asset fields.",
    }
    (out / "SUMMARY.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    # Fail closed on payload leakage.
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
    p.add_argument("--timeout-seconds", type=int, default=1800)
    p.add_argument("--no-verify-payload-hashes", action="store_true")
    p.add_argument("--no-archive", action="store_true")
    return p.parse_args()


def main() -> int:
    a = parse_args()
    archive, summary = build_report(
        a.project_root,
        report_root=a.report_root,
        output_report_root=a.output_report_root,
        workspace_root=a.workspace_root,
        original_root=a.original_root,
        quartet_root=a.quartet_root,
        gust_pak_path=a.gust_pak,
        timeout_seconds=a.timeout_seconds,
        verify_payload_hashes=not a.no_verify_payload_hashes,
        create_archive=not a.no_archive,
    )
    print(json.dumps(summary, indent=2, sort_keys=True))
    if archive:
        print(archive)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
