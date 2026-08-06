#!/usr/bin/env python3
"""Stage 152: read-only exact-field audit of Hinako wet accessory G1MM/MM1G.

Stage 151 established that no parsed G1MG MATERIALS/SHADER_PARAMS/SUBMESH/
MESH_LOD row provides an exact-base-control write candidate for the wet school
uniform.  The existing character-state material ledger nevertheless exposes a
more bounded clue: for pc00 school state P_ACCESSORY, Original dry and wet G1M
members differ while Quartet dry and wet are bit-identical, and the Original
wet transition is confined to the 80-byte G1MM/MM1G chunk.

This collector rehydrates only pc00 nkd/nkd_w, scl/scl_w and swm/swm_w,
extracts the P_ACCESSORY G1M member and compares its G1MM/MM1G chunk at aligned
4-byte field granularity.  It records exact target-side locators only when the
four chunks have the same layout.  No field receives semantic meaning or write
authorization.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import importlib.util
import json
import os
import shutil
import struct
import subprocess
import sys
import tempfile
from pathlib import Path, PurePosixPath
from typing import Any, Iterable, Mapping, Sequence

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT_DEFAULT = SCRIPT_DIR.parent.parent
TOOL_VERSION = "0.1.70"
REPORT_DIR = "hinako_wet_accessory_g1mm_exact_field_evidence"
REPORT_NAME = "BR_quartet_restoration_hinako_wet_accessory_g1mm_exact_field_evidence.tar.zst"
WORKSPACE_SUBDIR = Path("wet_accessory_g1mm_exact_field")

CHARACTER_ID = "pc00"
STATE_PAIRS = (
    ("nkd", "nkd_w"),
    ("scl", "scl_w"),
    ("swm", "swm_w"),
)
ROLE = "{pc}_{state}_p_accessory.g1m"
MAX_EARC_BYTES = 128 * 1024 * 1024

STAGE151_REPORT = "BR_quartet_restoration_hinako_wet_school_g1mg_binding_differential_evidence.tar.zst"
STAGE151_SHA256 = "68bb8760691bb01833af87c7ff6ed5c05868e360b1a4a6363bb9a8c187c5f1b9"
STAGE151_ROOT = "hinako_wet_school_g1mg_binding_differential_evidence"

FAILED_PROFILE_ID = "fast_test_pc00_scl_w_school_partial_plus_default_g1mm_c74bc813e41"
EXPECTED_BASELINE_SHA256 = "e798f39c3bcdbb11381197bddf9bd3ad8de6ccf5d7c0c78b22613046d47f5302"

FORBIDDEN_REPORT_EXTENSIONS = (
    ".pak", ".g1m", ".g1t", ".g1s", ".g1e", ".g1em", ".elixir", ".elixir.gz", ".ebd", ".ebm", ".kps"
)


class WetAccessoryG1MMError(RuntimeError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise WetAccessoryG1MMError(message)


def progress(message: str) -> None:
    print(f"[stage152] {message}", flush=True)


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(8 * 1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


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


def extract_report(archive: Path, expected_sha256: str, expected_root: str, destination: Path) -> Path:
    require(archive.is_file(), f"missing prerequisite report: {archive}")
    actual = sha256_file(archive)
    require(actual == expected_sha256, f"stage-151 evidence SHA-256 drift: {actual}")
    cp = subprocess.run(["tar", "--zstd", "-tf", str(archive)], text=True, capture_output=True)
    require(cp.returncode == 0, cp.stderr.strip() or "cannot list stage-151 evidence")
    names = [safe_relative(x.strip(), "stage-151 member") for x in cp.stdout.splitlines() if x.strip()]
    require(names and {PurePosixPath(x).parts[0] for x in names} == {expected_root}, "unexpected stage-151 archive root")
    require(not any(x.casefold().endswith(FORBIDDEN_REPORT_EXTENSIONS) for x in names), "proprietary payload in stage-151 evidence")
    destination.mkdir(parents=True, exist_ok=True)
    cp = subprocess.run(["tar", "--zstd", "-xf", str(archive), "-C", str(destination)], text=True, capture_output=True)
    require(cp.returncode == 0, cp.stderr.strip() or "cannot extract stage-151 evidence")
    return destination / expected_root


def validate_stage151(report_root: Path) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="stage152-prereq-") as td:
        root = extract_report(report_root / STAGE151_REPORT, STAGE151_SHA256, STAGE151_ROOT, Path(td))
        summary = json.loads((root / "SUMMARY.json").read_text(encoding="utf-8"))
        require(summary.get("tool_version") == "0.1.69", "stage-151 version drift")
        require(summary.get("stage150_severe_model_corruption_observed") is True, "stage-150 runtime failure missing from stage 151")
        require(summary.get("stage150_exact_pack10_02_baseline_restored") is True, "stage-150 exact rollback missing from stage 151")
        require(summary.get("whole_g1mm_transplant_reuse_forbidden") is True, "whole-G1MM reuse guard missing")
        require(summary.get("exact_base_control_material_rows") == 0, "unexpected stage-151 material exact-base candidate count")
        require(summary.get("exact_base_control_direct_scalar_probe_rows") == 0, "unexpected stage-151 scalar exact-base candidate count")
        require(summary.get("exact_base_control_submesh_rows") == 0, "unexpected stage-151 submesh exact-base candidate count")
        require(summary.get("exact_base_control_mesh_lod_rows") == 0, "unexpected stage-151 mesh-lod exact-base candidate count")
        require(summary.get("runtime_validated") is False and summary.get("production_eligible") is False, "stage-151 promotion drift")
        return summary


def _endian(payload: bytes, label: str) -> str:
    require(len(payload) >= 24, f"G1M too small: {label}")
    if payload[:4] == b"_M1G":
        return "<"
    if payload[:4] == b"G1M_":
        return ">"
    raise WetAccessoryG1MMError(f"not a G1M payload: {label}")


def extract_g1mm_chunk(payload: bytes, *, label: str = "<memory>") -> dict[str, Any]:
    e = _endian(payload, label)
    file_version, file_size, chunk_offset, reserved, chunk_count = struct.unpack_from(e + "5I", payload, 4)
    require(chunk_offset >= 24 and chunk_offset <= len(payload), f"unsafe G1M chunk offset: {label}")
    require(chunk_count <= 0x1000, f"unsafe G1M chunk count: {label}")
    require(not file_size or file_size <= len(payload), f"declared G1M size exceeds payload: {label}")
    offset = chunk_offset
    found: list[dict[str, Any]] = []
    chunk_rows: list[dict[str, Any]] = []
    for chunk_index in range(chunk_count):
        require(offset + 12 <= len(payload), f"truncated G1M chunk header: {label}")
        magic_raw = payload[offset:offset+4]
        try:
            magic = magic_raw.replace(b"\0", b"").decode("ascii")
        except UnicodeDecodeError:
            magic = magic_raw.hex()
        version, size = struct.unpack_from(e + "2I", payload, offset + 4)
        require(size >= 12 and offset + size <= len(payload), f"unsafe G1M chunk size: {label}")
        chunk = payload[offset:offset+size]
        row = {
            "chunk_index": chunk_index,
            "chunk_magic": magic,
            "chunk_version": f"0x{version:08x}",
            "chunk_offset": offset,
            "chunk_size": size,
            "chunk_sha256": sha256_bytes(chunk),
        }
        chunk_rows.append(row)
        if magic in {"MM1G", "G1MM"}:
            found.append({**row, "payload": chunk, "endian": e})
        offset += size
    require(len(found) == 1, f"expected exactly one G1MM/MM1G chunk: {label}; found={len(found)}")
    found[0]["all_chunks"] = chunk_rows
    found[0]["file_version"] = f"0x{file_version:08x}"
    found[0]["g1m_sha256"] = sha256_bytes(payload)
    found[0]["g1m_size"] = len(payload)
    return found[0]


def classify_four_way(sd: bytes, sw: bytes, td: bytes, tw: bytes) -> str:
    source_changed = sd != sw
    target_changed = td != tw
    if source_changed and not target_changed:
        return "original_wet_transition_missing_in_quartet_exact_base_control" if sd == td else "original_wet_transition_missing_in_quartet_base_differs"
    if source_changed and target_changed:
        if sd == td and sw == tw:
            return "matching_wet_transition"
        return "wet_transition_differs_between_games"
    if not source_changed and target_changed:
        return "quartet_only_wet_transition"
    return "dry_wet_identical_both_games"


def changed_runs(before: bytes, after: bytes) -> list[tuple[int, int]]:
    require(len(before) == len(after), "changed-run comparison requires equal sizes")
    out: list[tuple[int, int]] = []
    start: int | None = None
    for i, (a, b) in enumerate(zip(before, after)):
        if a != b and start is None:
            start = i
        elif a == b and start is not None:
            out.append((start, i - start))
            start = None
    if start is not None:
        out.append((start, len(before) - start))
    return out


def analyze_chunks(pair_name: str, variants: Mapping[str, dict[str, Any]]) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]:
    names = ("source_dry", "source_wet", "target_dry", "target_wet")
    chunks = [variants[n]["payload"] for n in names]
    sizes = [len(x) for x in chunks]
    versions = [variants[n]["chunk_version"] for n in names]
    magics = [variants[n]["chunk_magic"] for n in names]
    exact_layout = len(set(sizes)) == 1 and len(set(versions)) == 1 and len(set(magics)) == 1 and sizes[0] % 4 == 0
    control = {
        "state_pair": pair_name,
        "source_dry_sha256": variants["source_dry"]["chunk_sha256"],
        "source_wet_sha256": variants["source_wet"]["chunk_sha256"],
        "target_dry_sha256": variants["target_dry"]["chunk_sha256"],
        "target_wet_sha256": variants["target_wet"]["chunk_sha256"],
        "source_dry_wet_changed": chunks[0] != chunks[1],
        "target_dry_wet_changed": chunks[2] != chunks[3],
        "all_chunk_sizes_equal": len(set(sizes)) == 1,
        "all_chunk_versions_equal": len(set(versions)) == 1,
        "all_chunk_magics_equal": len(set(magics)) == 1,
        "chunk_size": sizes[0] if len(set(sizes)) == 1 else "",
        "chunk_version": versions[0] if len(set(versions)) == 1 else "",
        "exact_aligned_layout": exact_layout,
        "write_authorized": False,
    }
    field_rows: list[dict[str, Any]] = []
    run_rows: list[dict[str, Any]] = []
    if exact_layout:
        e = variants["target_wet"]["endian"]
        for off in range(0, sizes[0], 4):
            vals = [x[off:off+4] for x in chunks]
            cls = classify_four_way(*vals)
            if cls == "dry_wet_identical_both_games":
                continue
            field_rows.append({
                "state_pair": pair_name,
                "chunk_relative_offset": off,
                "target_wet_g1m_absolute_offset": int(variants["target_wet"]["chunk_offset"]) + off,
                "classification": cls,
                "source_dry_hex": vals[0].hex(),
                "source_wet_hex": vals[1].hex(),
                "target_dry_hex": vals[2].hex(),
                "target_wet_hex": vals[3].hex(),
                "source_dry_u32": struct.unpack(e + "I", vals[0])[0],
                "source_wet_u32": struct.unpack(e + "I", vals[1])[0],
                "target_dry_u32": struct.unpack(e + "I", vals[2])[0],
                "target_wet_u32": struct.unpack(e + "I", vals[3])[0],
                "exact_base_control": vals[0] == vals[2],
                "exact_target_locator": True,
                "target_precondition_hex": vals[3].hex(),
                "source_wet_desired_hex": vals[1].hex() if cls == "original_wet_transition_missing_in_quartet_exact_base_control" else "",
                "semantics_confirmed": False,
                "write_authorized": False,
            })
        for direction, before, after in (("source_dry_to_wet", chunks[0], chunks[1]), ("target_dry_to_wet", chunks[2], chunks[3])):
            for idx, (off, length) in enumerate(changed_runs(before, after)):
                run_rows.append({
                    "state_pair": pair_name,
                    "direction": direction,
                    "run_index": idx,
                    "chunk_relative_offset": off,
                    "run_length": length,
                    "before_sha256": sha256_bytes(before[off:off+length]),
                    "after_sha256": sha256_bytes(after[off:off+length]),
                    "raw_payload_in_evidence": False,
                })
    return control, field_rows, run_rows


def build_report(
    project_root: Path, *, report_root: Path | None = None, output_report_root: Path | None = None,
    workspace_root: Path | None = None, original_root: Path | None = None, quartet_root: Path | None = None,
    gust_pak_path: Path | None = None, create_archive: bool = True, timeout_seconds: int = 1800,
    verify_payload_hashes: bool = True,
) -> tuple[Path | None, dict[str, Any]]:
    project_root = project_root.resolve()
    version = (project_root / "workstreams/quartet_restoration/VERSION").read_text(encoding="utf-8").strip()
    require(tuple(map(int, version.split("."))) >= tuple(map(int, TOOL_VERSION.split("."))), f"expected {TOOL_VERSION} or newer, found {version}")
    report_root = (report_root or project_root / ".local/reports/quartet_restoration").resolve()
    output_report_root = (output_report_root or report_root).resolve()
    workspace_root = (workspace_root or project_root / ".local/build/quartet_restoration" / WORKSPACE_SUBDIR).resolve()
    output = output_report_root / REPORT_DIR
    archive = output_report_root / REPORT_NAME
    if output.exists():
        shutil.rmtree(output)
    output.mkdir(parents=True, exist_ok=True)

    validate_stage151(report_root)
    br = load_module(project_root / "Blue_Reflection_Text_Tool/br_restoration_tool.py", "stage152_br")
    stage125 = load_module(project_root / "workstreams/quartet_restoration/125_collect_character_state_exact_rehydration_evidence.py", "stage152_stage125")
    inventories = stage125.load_asset_inventories(project_root)
    required_paths: list[str] = []
    pair_paths: dict[str, tuple[str, str]] = {}
    for dry, wet in STATE_PAIRS:
        dry_path = f"data/x64/character/{CHARACTER_ID}/{CHARACTER_ID}_{dry}.elixir.gz"
        wet_path = f"data/x64/character/{CHARACTER_ID}/{CHARACTER_ID}_{wet}.elixir.gz"
        required_paths.extend((dry_path, wet_path))
        pair_paths[dry] = (dry_path, wet_path)
    extraction_rows = stage125.ensure_extraction_cache(
        project_root=project_root, workspace_root=workspace_root, inventories=inventories,
        required_paths=required_paths, original_root=original_root, quartet_root=quartet_root,
        gust_pak_path=gust_pak_path, br=br, timeout_seconds=timeout_seconds,
    )

    input_rows: list[dict[str, Any]] = []
    chunk_rows: list[dict[str, Any]] = []
    control_rows: list[dict[str, Any]] = []
    field_rows: list[dict[str, Any]] = []
    run_rows: list[dict[str, Any]] = []
    skipped_rows: list[dict[str, Any]] = []

    for dry, wet in STATE_PAIRS:
        pair = f"{dry}->{wet}"
        variant_chunks: dict[str, dict[str, Any]] = {}
        for side in ("source", "target"):
            for state, normalized, label_suffix in ((dry, pair_paths[dry][0], "dry"), (wet, pair_paths[dry][1], "wet")):
                key = (side, normalized.casefold())
                require(key in inventories, f"missing inventory entry: {key}")
                pair_id, entry = inventories[key]
                local = br.inventory_workspace_file(workspace_root, side, pair_id, str(entry["archive"]), str(entry["path"]))
                require(local.is_file(), f"missing extracted input: {side} {normalized}: {local}")
                actual = sha256_file(local)
                if verify_payload_hashes:
                    require(actual == str(entry["sha256"]), f"payload hash drift: {side} {normalized}: {actual}")
                progress(f"reading {side} {state}: {normalized}")
                parsed = br.read_earc_archive(local, maximum_bytes=MAX_EARC_BYTES, include_member_payloads=True)
                role_matches = []
                for member in parsed["members"]:
                    if str(member.get("extension", "")).casefold() != ".g1m":
                        continue
                    role = stage125.normalized_role(str(member["name"]), CHARACTER_ID, state)
                    if role == ROLE:
                        role_matches.append(member)
                require(len(role_matches) == 1, f"expected exactly one {ROLE} in {side}:{state}; found={len(role_matches)}")
                member = role_matches[0]
                variant_name = f"{side}_{label_suffix}"
                try:
                    g1mm = extract_g1mm_chunk(member["payload"], label=f"{pair}:{variant_name}:{member['name']}")
                    variant_chunks[variant_name] = g1mm
                    input_rows.append({
                        "state_pair": pair, "side": side, "state_token": state, "archive_path": normalized,
                        "archive_input_sha256": actual, "member_name": member["name"], "member_sha256": member["sha256"],
                        "member_size": len(member["payload"]), "g1mm_chunk_sha256": g1mm["chunk_sha256"],
                        "g1mm_chunk_size": g1mm["chunk_size"], "g1mm_chunk_version": g1mm["chunk_version"],
                        "payload_in_evidence": False,
                    })
                    for crow in g1mm["all_chunks"]:
                        chunk_rows.append({"state_pair": pair, "variant": variant_name, **crow})
                except Exception as exc:
                    skipped_rows.append({
                        "state_pair": pair, "variant": variant_name, "member_name": member["name"],
                        "reason": f"{type(exc).__name__}:{exc}", "write_authorized": False,
                    })
        if len(variant_chunks) == 4:
            control, fields, runs = analyze_chunks(pair, variant_chunks)
            control_rows.append(control)
            field_rows.extend(fields)
            run_rows.extend(runs)

    exact_rows = [r for r in field_rows if r["classification"] == "original_wet_transition_missing_in_quartet_exact_base_control"]
    scl_exact = [r for r in exact_rows if r["state_pair"] == "scl->scl_w"]
    school_control = next((r for r in control_rows if r["state_pair"] == "scl->scl_w"), None)
    require(school_control is not None, "missing school G1MM control")
    # The known clue must remain true; otherwise the local inputs no longer match
    # the reviewed stage-126/151 state and no later probe may be planned.
    require(school_control["source_dry_wet_changed"] is True, "Original school P_ACCESSORY G1MM no longer changes dry->wet")
    require(school_control["target_dry_wet_changed"] is False, "Quartet school P_ACCESSORY G1MM unexpectedly changes dry->wet")
    require(school_control["exact_aligned_layout"] is True, "school P_ACCESSORY G1MM is not exact-layout comparable")

    write_tsv(output / "INPUTS.tsv", [
        "state_pair","side","state_token","archive_path","archive_input_sha256","member_name","member_sha256","member_size",
        "g1mm_chunk_sha256","g1mm_chunk_size","g1mm_chunk_version","payload_in_evidence"
    ], input_rows)
    write_tsv(output / "G1M_CHUNK_INVENTORY.tsv", [
        "state_pair","variant","chunk_index","chunk_magic","chunk_version","chunk_offset","chunk_size","chunk_sha256"
    ], chunk_rows)
    write_tsv(output / "G1MM_PAIR_CONTROLS.tsv", [
        "state_pair","source_dry_sha256","source_wet_sha256","target_dry_sha256","target_wet_sha256",
        "source_dry_wet_changed","target_dry_wet_changed","all_chunk_sizes_equal","all_chunk_versions_equal",
        "all_chunk_magics_equal","chunk_size","chunk_version","exact_aligned_layout","write_authorized"
    ], control_rows)
    write_tsv(output / "G1MM_DWORD_TRANSITIONS.tsv", [
        "state_pair","chunk_relative_offset","target_wet_g1m_absolute_offset","classification","source_dry_hex","source_wet_hex",
        "target_dry_hex","target_wet_hex","source_dry_u32","source_wet_u32","target_dry_u32","target_wet_u32",
        "exact_base_control","exact_target_locator","target_precondition_hex","source_wet_desired_hex","semantics_confirmed","write_authorized"
    ], field_rows)
    write_tsv(output / "G1MM_CHANGED_RUNS.tsv", [
        "state_pair","direction","run_index","chunk_relative_offset","run_length","before_sha256","after_sha256","raw_payload_in_evidence"
    ], run_rows)
    write_tsv(output / "EXACT_FIELD_CANDIDATES.tsv", [
        "state_pair","chunk_relative_offset","target_wet_g1m_absolute_offset","classification","target_precondition_hex",
        "source_wet_desired_hex","semantics_confirmed","write_authorized"
    ], exact_rows)
    write_tsv(output / "PARSE_SKIPPED.tsv", ["state_pair","variant","member_name","reason","write_authorized"], skipped_rows)
    extraction_fields = sorted({k for r in extraction_rows for k in r.keys()}) if extraction_rows else ["side","archive_relative","cache_action"]
    write_tsv(output / "EXTRACTION_INPUTS.tsv", extraction_fields, extraction_rows)

    summary = {
        "type": "br_quartet_restoration_hinako_wet_accessory_g1mm_exact_field_evidence_summary",
        "format_version": 1,
        "tool_version": TOOL_VERSION,
        "status": "stage151_zero_exact_g1mg_candidates_school_accessory_80byte_g1mm_exact_field_audit_complete_no_write",
        "stage151_evidence_sha256": STAGE151_SHA256,
        "stage151_exact_base_control_rows_total": 0,
        "state_pair_rows": len(control_rows),
        "parse_skip_rows": len(skipped_rows),
        "dword_transition_rows": len(field_rows),
        "exact_field_candidate_rows": len(exact_rows),
        "school_exact_field_candidate_rows": len(scl_exact),
        "school_source_dry_wet_changed": school_control["source_dry_wet_changed"],
        "school_target_dry_wet_changed": school_control["target_dry_wet_changed"],
        "school_g1mm_chunk_size": school_control["chunk_size"],
        "school_g1mm_exact_aligned_layout": school_control["exact_aligned_layout"],
        "runtime_validated": False,
        "production_eligible": False,
        "policy": {
            "whole_g1mm_transplant_reuse_forbidden": True,
            "complete_g1mm_chunk_transplant_authorized": False,
            "field_rows_are_candidates_only": True,
            "field_write_authorized": False,
            "wet_skin_droplet_semantics_inferred": False,
            "blouse_transparency_semantics_inferred": False,
            "p_accessory_name_used_as_semantic_proof": False,
            "installed_game_modified": False,
            "pak_repacked": False,
            "core_modified": False,
            "translation_modified": False,
            "legacy_dlc_modified": False,
            "git_modified": False,
            "proprietary_payloads_in_evidence": False,
        },
        "next_action": (
            "If the school P_ACCESSORY 80-byte G1MM exposes one or more exact-base-control fields, review their recurrence in nkd/swm controls "
            "and build at most one preconditioned target-native field probe. If no exact field exists, do not patch this chunk; move to another bounded wet-only structure."
        ),
    }
    (output / "SUMMARY.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    for p in output.rglob("*"):
        if p.is_file():
            rel = p.relative_to(output).as_posix().casefold()
            require(not rel.endswith(FORBIDDEN_REPORT_EXTENSIONS), f"proprietary payload in report: {rel}")

    if create_archive:
        make_archive(output, archive)
        return archive, summary
    return None, summary


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("--project-root", type=Path, default=PROJECT_ROOT_DEFAULT)
    p.add_argument("--report-root", type=Path)
    p.add_argument("--output-report-root", type=Path)
    p.add_argument("--workspace-root", type=Path)
    p.add_argument("--original-root", type=Path)
    p.add_argument("--quartet-root", type=Path)
    p.add_argument("--gust-pak", type=Path)
    p.add_argument("--timeout-seconds", type=int, default=1800)
    p.add_argument("--no-verify-payload-hashes", action="store_true")
    return p.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        archive, summary = build_report(
            args.project_root, report_root=args.report_root, output_report_root=args.output_report_root,
            workspace_root=args.workspace_root, original_root=args.original_root, quartet_root=args.quartet_root,
            gust_pak_path=args.gust_pak, timeout_seconds=args.timeout_seconds,
            verify_payload_hashes=not args.no_verify_payload_hashes,
        )
        print(json.dumps(summary, indent=2, sort_keys=True))
        if archive is not None:
            print(f"[stage152] report archive: {archive}")
            print(f"[stage152] SHA-256: {sha256_file(archive)}")
        return 0
    except WetAccessoryG1MMError as exc:
        print(f"[stage152] ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
