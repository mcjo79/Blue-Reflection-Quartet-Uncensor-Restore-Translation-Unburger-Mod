#!/usr/bin/env python3
"""Isolate adaptive local change islands around the two surviving PC02 ringlight leaves.

Stage 86 proved that both adjacent 150 -> 75 transitions share an exact local
source/target profile with neutral-named e_cmn_pup_reflect_s only through a
radius of eight dwords; the profiles diverge at radius sixteen.  This read-only
stage replaces arbitrary symmetric windows with adaptive islands bounded by
stable runs of unchanged aligned dwords.  It exports transition metadata and
hashes only and never writes a G1E, Elixir, PAK, registry or installed game.
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
from typing import Any, Callable, Iterable, Mapping, Sequence

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT_DEFAULT = SCRIPT_DIR.parent.parent

TOOL_VERSION = "0.1.1"
REPORT_NAME = "BR_quartet_restoration_reflector_slot_light_local_change_island_evidence.tar.zst"
REPORT_DIR = "reflector_slot_light_local_change_island_evidence"
STAGE86_DIR = "reflector_slot_light_shared_record_template_evidence"
STAGE86_ARCHIVE = "BR_quartet_restoration_reflector_slot_light_shared_record_template_evidence.tar.zst"
STAGE79_DIR = "reflector_character_slot_render_member_evidence"
STAGE79_ARCHIVE = "BR_quartet_restoration_reflector_character_slot_render_member_evidence.tar.zst"
EXPECTED_CANDIDATE_ROWS = 2
EXPECTED_PARENT_CONTAINERS = 4
STABLE_RUN_DWORDS = 16
MAX_SCAN_RADIUS_DWORDS = 2048


class Stage87Error(RuntimeError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise Stage87Error(message)


def progress(message: str) -> None:
    print(f"[stage87] {message}", file=sys.stderr, flush=True)


def parse_int(value: Any, default: int = 0) -> int:
    try:
        text = str(value).strip()
        return int(text, 16) if text.casefold().startswith("0x") else int(text)
    except (TypeError, ValueError):
        return default


def parse_bool(value: Any) -> bool:
    return str(value).strip().casefold() in {"1", "true", "yes", "y"}


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def safe_name(raw: str) -> str:
    path = PurePosixPath(raw)
    require(not path.is_absolute() and path.parts and ".." not in path.parts, f"unsafe archive member: {raw}")
    return path.as_posix()


def read_tsv(path: Path, required: bool = True) -> list[dict[str, str]]:
    if not path.is_file():
        if required:
            raise Stage87Error(f"missing required TSV: {path}")
        return []
    with path.open(encoding="utf-8", newline="") as handle:
        return [dict(row) for row in csv.DictReader(handle, delimiter="\t")]


def write_tsv(path: Path, fields: Sequence[str], rows: Iterable[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(fields), delimiter="\t", lineterminator="\n", extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fields})


def load_json(path: Path) -> dict[str, Any]:
    require(path.is_file(), f"missing required JSON: {path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise Stage87Error(f"invalid JSON {path}: {exc}") from exc
    require(isinstance(value, dict), f"JSON root must be object: {path}")
    return value


def extract_archive(archive: Path, destination: Path) -> Path:
    require(archive.is_file(), f"missing prerequisite report: {archive}")
    listed = subprocess.run(["tar", "--zstd", "-tf", str(archive)], text=True, capture_output=True)
    require(listed.returncode == 0, listed.stderr.strip())
    roots = {PurePosixPath(safe_name(line.strip())).parts[0] for line in listed.stdout.splitlines() if line.strip()}
    require(len(roots) == 1, f"expected one report root in {archive}")
    destination.mkdir(parents=True, exist_ok=True)
    completed = subprocess.run(["tar", "--zstd", "-xf", str(archive), "-C", str(destination)], text=True, capture_output=True)
    require(completed.returncode == 0, completed.stderr.strip())
    return destination / next(iter(roots))


def locate(report_root: Path, direct: str, archive: str, temporary: Path) -> Path:
    direct_path = report_root / direct
    return direct_path if direct_path.is_dir() else extract_archive(report_root / archive, temporary)


def make_archive(source: Path, output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(output.name + ".tmp")
    temporary.unlink(missing_ok=True)
    completed = subprocess.run(["tar", "--zstd", "-cf", str(temporary), "-C", str(source.parent), source.name], text=True, capture_output=True)
    require(completed.returncode == 0, completed.stderr.strip())
    os.replace(temporary, output)


def load_module(path: Path, name: str):
    require(path.is_file(), f"missing prerequisite collector: {path}")
    spec = importlib.util.spec_from_file_location(name, path)
    require(spec is not None and spec.loader is not None, f"cannot load module: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def stable_key(path: str, member_key: str) -> tuple[str, str]:
    return path.casefold(), member_key.casefold()


def validate_stage86(root: Path) -> dict[str, Any]:
    summary = load_json(root / "SUMMARY.json")
    require(summary.get("type") == "br_quartet_restoration_reflector_slot_light_shared_record_template_evidence_summary", "stage86 type mismatch")
    require(summary.get("tool_version") == "0.1.0", "stage86 tool version mismatch")
    require(summary.get("status") == "surviving_PC02_ringlight_150_to_75_leaves_tested_against_expanded_shared_record_templates_brightness_semantics_unresolved", "stage86 status mismatch")
    require(parse_int(summary.get("semantic_leaf_candidate_rows"), -1) == EXPECTED_CANDIDATE_ROWS, "stage86 candidate count mismatch")
    require(parse_int(summary.get("exact_same_transition_pair_rows"), -1) == EXPECTED_CANDIDATE_ROWS, "stage86 pair count mismatch")
    require(parse_int(summary.get("shared_neutral_record_template_rows"), -1) == 0, "stage86 unexpectedly closed the rows as a large neutral template")
    require(parse_int(summary.get("shared_neutral_local_record_rows"), -1) == EXPECTED_CANDIDATE_ROWS, "stage86 local neutral match count mismatch")
    require(parse_int(summary.get("prototype_candidate_rows"), -1) == 0, "stage86 unexpectedly authorized a prototype")
    require(parse_int(summary.get("skipped_rows"), -1) == 0, "stage86 contains skipped rows")
    require(not parse_bool(summary.get("brightness_semantics_confirmed")), "stage86 unexpectedly confirmed brightness")
    return summary



def resolve_stage86_pair_rows(
    pair_rows: Sequence[Mapping[str, Any]], radius_rows: Sequence[Mapping[str, Any]], *, radius_dwords: int = 8,
) -> list[dict[str, Any]]:
    resolved: list[dict[str, Any]] = []
    for pair in pair_rows:
        candidate_id = str(pair.get("candidate_id", ""))
        sibling_path = str(pair.get("sibling_normalized_path", "")).casefold()
        sibling_member_key = str(pair.get("sibling_member_key", "")).casefold()
        require(candidate_id and sibling_path and sibling_member_key, "stage86 pair identity missing")
        matches = [
            row for row in radius_rows
            if str(row.get("candidate_id", "")) == candidate_id
            and str(row.get("sibling_normalized_path", "")).casefold() == sibling_path
            and str(row.get("sibling_member_key", "")).casefold() == sibling_member_key
            and parse_int(row.get("radius_dwords"), -1) == radius_dwords
            and parse_bool(row.get("transition_profile_equal"))
        ]
        require(len(matches) == 1, f"expected one stage86 radius-{radius_dwords} sibling row for {candidate_id}, found {len(matches)}")
        merged = dict(pair)
        merged["sibling_source_offset"] = matches[0].get("sibling_source_offset", "")
        merged["sibling_target_offset"] = matches[0].get("sibling_target_offset", "")
        resolved.append(merged)
    return resolved

def index_pairs(containers: Sequence[Mapping[str, Any]]) -> dict[tuple[str, str], dict[str, Any]]:
    result: dict[tuple[str, str], dict[str, Any]] = {}
    for container in containers:
        path = str(container.get("normalized_path", "")).casefold()
        source = {str(row.get("comparison_key", "")).casefold(): row for row in container.get("source_members", [])}
        target = {str(row.get("comparison_key", "")).casefold(): row for row in container.get("target_members", [])}
        for member_key in sorted(set(source) & set(target)):
            left = source[member_key]
            right = target[member_key]
            name = str(right.get("name") or left.get("name") or "")
            if Path(name).suffix.casefold() not in {".g1e", ".g1em"}:
                continue
            key = stable_key(path, member_key)
            require(key not in result, f"duplicate G1E/G1EM identity: {key}")
            result[key] = {
                "normalized_path": path,
                "member_key": member_key,
                "member_name": name,
                "source_payload": bytes(left.get("payload") or b""),
                "target_payload": bytes(right.get("payload") or b""),
            }
    return result


def dword(payload: bytes, offset: int) -> int:
    require(offset >= 0 and offset + 4 <= len(payload) and offset % 4 == 0, f"invalid dword offset: {offset}")
    return int.from_bytes(payload[offset:offset + 4], "little")


def float_text(value: int) -> tuple[str, str]:
    number = struct.unpack("<f", value.to_bytes(4, "little"))[0]
    if not math.isfinite(number):
        return "", "nonfinite"
    if 0 < abs(number) < 1.0e-30:
        return f"{number:.9g}", "subnormal_or_tiny"
    return f"{number:.9g}", "finite"


def discover_change_island(
    source: bytes,
    target: bytes,
    source_centers: Sequence[int],
    target_centers: Sequence[int],
    *,
    stable_run_dwords: int = STABLE_RUN_DWORDS,
    maximum_scan_radius_dwords: int = MAX_SCAN_RADIUS_DWORDS,
) -> dict[str, Any]:
    require(len(source_centers) == len(target_centers) and source_centers, "center lists must be non-empty and equal")
    source_centers = tuple(sorted(source_centers))
    target_centers = tuple(sorted(target_centers))
    require(all(offset % 4 == source_centers[0] % 4 for offset in source_centers), "source centers have inconsistent dword phase")
    require(all(offset % 4 == target_centers[0] % 4 for offset in target_centers), "target centers have inconsistent dword phase")
    shifts = {right - left for left, right in zip(source_centers, target_centers)}
    require(len(shifts) == 1, "candidate fields do not share one local alignment shift")
    shift = next(iter(shifts))
    require(all(dword(source, left) != dword(target, right) for left, right in zip(source_centers, target_centers)), "candidate center is not changed")

    phase = source_centers[0] % 4
    lower = max(0, -shift)
    lower += (phase - lower) % 4
    upper_exclusive = min(len(source), len(target) - shift)
    upper_exclusive -= (upper_exclusive - phase) % 4
    require(lower <= source_centers[0] and source_centers[-1] + 4 <= upper_exclusive, "centers fall outside aligned overlap")

    max_bytes = maximum_scan_radius_dwords * 4
    left_limit = max(lower, source_centers[0] - max_bytes)
    right_limit = min(upper_exclusive, source_centers[-1] + 4 + max_bytes)

    left_boundary = None
    unchanged = 0
    cursor = source_centers[0] - 4
    while cursor >= left_limit:
        if source[cursor:cursor + 4] == target[cursor + shift:cursor + shift + 4]:
            unchanged += 1
            if unchanged == stable_run_dwords:
                left_boundary = cursor + stable_run_dwords * 4
                break
        else:
            unchanged = 0
        cursor -= 4

    right_boundary = None
    unchanged = 0
    cursor = source_centers[-1] + 4
    while cursor + 4 <= right_limit:
        if source[cursor:cursor + 4] == target[cursor + shift:cursor + shift + 4]:
            unchanged += 1
            if unchanged == stable_run_dwords:
                right_boundary = cursor - (stable_run_dwords - 1) * 4
                break
        else:
            unchanged = 0
        cursor += 4

    require(left_boundary is not None, "stable left boundary not found")
    require(right_boundary is not None, "stable right boundary not found")
    require(left_boundary <= source_centers[0] < right_boundary, "invalid change-island boundaries")

    transitions: list[dict[str, Any]] = []
    for source_offset in range(left_boundary, right_boundary, 4):
        target_offset = source_offset + shift
        source_value = dword(source, source_offset)
        target_value = dword(target, target_offset)
        if source_value == target_value:
            continue
        source_float, source_float_status = float_text(source_value)
        target_float, target_float_status = float_text(target_value)
        transitions.append({
            "source_offset": source_offset,
            "target_offset": target_offset,
            "relative_dword": (source_offset - source_centers[0]) // 4,
            "source_u32_hex": f"0x{source_value:08x}",
            "target_u32_hex": f"0x{target_value:08x}",
            "source_float32": source_float,
            "target_float32": target_float,
            "source_float_status": source_float_status,
            "target_float_status": target_float_status,
            "transition_sha256": sha256(source_value.to_bytes(4, "little") + target_value.to_bytes(4, "little")),
        })

    require(transitions, "change island contains no changed dwords")
    signature_raw = bytearray()
    for row in transitions:
        signature_raw.extend(int(row["relative_dword"]).to_bytes(4, "little", signed=True))
        signature_raw.extend(int(row["source_u32_hex"], 16).to_bytes(4, "little"))
        signature_raw.extend(int(row["target_u32_hex"], 16).to_bytes(4, "little"))
    left_source_stable = source[left_boundary - stable_run_dwords * 4:left_boundary]
    left_target_stable = target[left_boundary + shift - stable_run_dwords * 4:left_boundary + shift]
    right_source_stable = source[right_boundary:right_boundary + stable_run_dwords * 4]
    right_target_stable = target[right_boundary + shift:right_boundary + shift + stable_run_dwords * 4]
    return {
        "shift_bytes": shift,
        "source_start": left_boundary,
        "source_end_exclusive": right_boundary,
        "target_start": left_boundary + shift,
        "target_end_exclusive": right_boundary + shift,
        "source_length": right_boundary - left_boundary,
        "target_length": right_boundary - left_boundary,
        "left_distance_dwords": (source_centers[0] - left_boundary) // 4,
        "right_distance_dwords": (right_boundary - source_centers[-1] - 4) // 4,
        "changed_dword_rows": len(transitions),
        "transition_profile_sha256": sha256(bytes(signature_raw)),
        "left_stable_source_sha256": sha256(left_source_stable),
        "left_stable_target_sha256": sha256(left_target_stable),
        "right_stable_source_sha256": sha256(right_source_stable),
        "right_stable_target_sha256": sha256(right_target_stable),
        "transitions": transitions,
    }


def transition_identity(row: Mapping[str, Any]) -> tuple[int, str, str]:
    return parse_int(row.get("relative_dword")), str(row.get("source_u32_hex", "")).casefold(), str(row.get("target_u32_hex", "")).casefold()


def build_report(
    project_root: Path,
    *,
    create_archive: bool = True,
    workspace_root: Path | None = None,
    report_root: Path | None = None,
    rules_file: Path | None = None,
    maximum_earc_bytes: int = 512 * 1024 * 1024,
    container_loader: Callable[..., tuple[list[dict[str, Any]], list[dict[str, Any]]]] | None = None,
) -> tuple[Path, Path | None, dict[str, Any]]:
    project_root = project_root.resolve()
    reports = (report_root or project_root / ".local/reports/quartet_restoration").resolve()
    workspace = (workspace_root or project_root / ".local/build/quartet_restoration").resolve()
    require(reports.is_dir(), f"missing report root: {reports}")

    stage81 = load_module(project_root / "workstreams/quartet_restoration/collect_reflector_ringlight_control_callsite_evidence.py", "stage81_for_stage87")
    progress("validating stage 79 and 86 reports")
    with tempfile.TemporaryDirectory(prefix="br-stage87-") as temporary_name:
        temporary = Path(temporary_name)
        stage86_root = locate(reports, STAGE86_DIR, STAGE86_ARCHIVE, temporary / "86")
        stage79_root = locate(reports, STAGE79_DIR, STAGE79_ARCHIVE, temporary / "79")
        summary86 = validate_stage86(stage86_root)
        summary79 = stage81.validate_stage79(stage79_root)
        pair_rows_raw = read_tsv(stage86_root / "SLOT_LIGHT_SHARED_RECORD_TEMPLATE_PAIRS.tsv")
        radius_rows = read_tsv(stage86_root / "SLOT_LIGHT_SHARED_RECORD_CONTEXT_RADII.tsv")
        require(len(pair_rows_raw) == EXPECTED_CANDIDATE_ROWS, "stage86 pair-table count mismatch")
        require(all(parse_int(row.get("maximum_transition_profile_radius_dwords"), -1) == 8 for row in pair_rows_raw), "stage86 pair is not an eight-dword-only local match")
        pair_rows = resolve_stage86_pair_rows(pair_rows_raw, radius_rows, radius_dwords=8)

        parent_scope = stage81.select_parent_scope(stage79_root)
        actual_rules = rules_file or project_root / "titles/blue_reflection/modules/quartet_restoration/mappings/effect_material_rules.tsv"
        loader = container_loader or stage81.load_parent_containers
        containers, skipped = loader(
            scope_rows=parent_scope,
            workspace_root=workspace,
            report_root=reports,
            rules_file=actual_rules,
            maximum_earc_bytes=maximum_earc_bytes,
        )
        require(not skipped, f"parent container loader skipped {len(skipped)} rows")
        require(len(containers) == EXPECTED_PARENT_CONTAINERS, f"expected {EXPECTED_PARENT_CONTAINERS} parent containers, found {len(containers)}")
        pairs = index_pairs(containers)
        progress(f"indexed {len(pairs)} G1E/G1EM payload pairs")

        candidate_path = "data/x64/effect/1002_pc02.elixir.gz"
        candidate_key = "e_pc02_w5_ringlight_01.g1e#0"
        sibling_path = str(pair_rows[0].get("sibling_normalized_path", "")).casefold()
        sibling_key = str(pair_rows[0].get("sibling_member_key", "")).casefold()
        require(sibling_path and sibling_key, "stage86 sibling identity missing")
        require(all(str(row.get("sibling_normalized_path", "")).casefold() == sibling_path and str(row.get("sibling_member_key", "")).casefold() == sibling_key for row in pair_rows), "stage86 rows do not share one neutral sibling")
        candidate_pair = pairs.get(stable_key(candidate_path, candidate_key))
        sibling_pair = pairs.get(stable_key(sibling_path, sibling_key))
        require(candidate_pair is not None, "candidate G1E payload pair missing")
        require(sibling_pair is not None, "neutral sibling G1E payload pair missing")

        ordered = sorted(pair_rows, key=lambda row: parse_int(row.get("candidate_source_offset"), -1))
        candidate_source_centers = [parse_int(row.get("candidate_source_offset"), -1) for row in ordered]
        candidate_target_centers = [parse_int(row.get("candidate_target_offset"), -1) for row in ordered]
        sibling_source_centers = [parse_int(row.get("sibling_source_offset"), -1) for row in ordered]
        sibling_target_centers = [parse_int(row.get("sibling_target_offset"), -1) for row in ordered]
        for centers in (candidate_source_centers, candidate_target_centers, sibling_source_centers, sibling_target_centers):
            require(all(value >= 0 for value in centers), "stage86 offsets malformed")
            require(centers[1] - centers[0] == 4, "surviving fields are not adjacent dwords")

        progress("discovering adaptive island for PC02 w5 ringlight")
        candidate_island = discover_change_island(
            candidate_pair["source_payload"], candidate_pair["target_payload"],
            candidate_source_centers, candidate_target_centers,
        )
        progress("discovering adaptive island for neutral pup_reflect control")
        sibling_island = discover_change_island(
            sibling_pair["source_payload"], sibling_pair["target_payload"],
            sibling_source_centers, sibling_target_centers,
        )

        candidate_map = {transition_identity(row): row for row in candidate_island["transitions"]}
        sibling_map = {transition_identity(row): row for row in sibling_island["transitions"]}
        shared = set(candidate_map) & set(sibling_map)
        candidate_only = set(candidate_map) - set(sibling_map)
        sibling_only = set(sibling_map) - set(candidate_map)
        exact_island_profile = (
            not candidate_only and not sibling_only
            and candidate_island["left_distance_dwords"] == sibling_island["left_distance_dwords"]
            and candidate_island["right_distance_dwords"] == sibling_island["right_distance_dwords"]
        )

        island_rows: list[dict[str, Any]] = []
        transition_rows: list[dict[str, Any]] = []
        for role, pair, centers_source, centers_target, island in (
            ("candidate_ringlight", candidate_pair, candidate_source_centers, candidate_target_centers, candidate_island),
            ("neutral_control", sibling_pair, sibling_source_centers, sibling_target_centers, sibling_island),
        ):
            island_rows.append({
                "island_role": role,
                "normalized_path": pair["normalized_path"],
                "member_key": pair["member_key"],
                "member_name": pair["member_name"],
                "source_center_0": centers_source[0],
                "source_center_1": centers_source[1],
                "target_center_0": centers_target[0],
                "target_center_1": centers_target[1],
                **{key: value for key, value in island.items() if key != "transitions"},
                "boundary_status": "stable_unchanged_runs_found",
            })
            own_map = candidate_map if role == "candidate_ringlight" else sibling_map
            other_map = sibling_map if role == "candidate_ringlight" else candidate_map
            for row in island["transitions"]:
                identity = transition_identity(row)
                relation = "shared_exact_transition" if identity in other_map else ("candidate_only_transition" if role == "candidate_ringlight" else "neutral_only_transition")
                transition_rows.append({
                    "island_role": role,
                    "normalized_path": pair["normalized_path"],
                    "member_key": pair["member_key"],
                    "member_name": pair["member_name"],
                    **row,
                    "cross_island_relation": relation,
                })

        classification = "shared_complete_adaptive_change_island" if exact_island_profile else "shared_two_leaf_core_with_divergent_adaptive_residuals"
        comparison_rows = [{
            "candidate_member_name": candidate_pair["member_name"],
            "neutral_member_name": sibling_pair["member_name"],
            "shared_exact_transition_rows": len(shared),
            "candidate_only_transition_rows": len(candidate_only),
            "neutral_only_transition_rows": len(sibling_only),
            "candidate_changed_dword_rows": candidate_island["changed_dword_rows"],
            "neutral_changed_dword_rows": sibling_island["changed_dword_rows"],
            "candidate_left_distance_dwords": candidate_island["left_distance_dwords"],
            "neutral_left_distance_dwords": sibling_island["left_distance_dwords"],
            "candidate_right_distance_dwords": candidate_island["right_distance_dwords"],
            "neutral_right_distance_dwords": sibling_island["right_distance_dwords"],
            "exact_adaptive_island_profile": exact_island_profile,
            "classification": classification,
            "brightness_semantics": "unresolved",
            "prototype_status": "evidence_only_no_G1E_write",
        }]

        output_dir = reports / REPORT_DIR
        output_dir.mkdir(parents=True, exist_ok=True)
        write_tsv(output_dir / "SLOT_LIGHT_LOCAL_CHANGE_ISLANDS.tsv", [
            "island_role", "normalized_path", "member_key", "member_name",
            "source_center_0", "source_center_1", "target_center_0", "target_center_1",
            "shift_bytes", "source_start", "source_end_exclusive", "target_start", "target_end_exclusive",
            "source_length", "target_length", "left_distance_dwords", "right_distance_dwords",
            "changed_dword_rows", "transition_profile_sha256",
            "left_stable_source_sha256", "left_stable_target_sha256",
            "right_stable_source_sha256", "right_stable_target_sha256", "boundary_status",
        ], island_rows)
        write_tsv(output_dir / "SLOT_LIGHT_LOCAL_CHANGE_ISLAND_TRANSITIONS.tsv", [
            "island_role", "normalized_path", "member_key", "member_name",
            "source_offset", "target_offset", "relative_dword",
            "source_u32_hex", "target_u32_hex", "source_float32", "target_float32",
            "source_float_status", "target_float_status", "transition_sha256", "cross_island_relation",
        ], sorted(transition_rows, key=lambda row: (row["island_role"], parse_int(row["relative_dword"]))))
        write_tsv(output_dir / "SLOT_LIGHT_LOCAL_CHANGE_ISLAND_COMPARISON.tsv", [
            "candidate_member_name", "neutral_member_name", "shared_exact_transition_rows",
            "candidate_only_transition_rows", "neutral_only_transition_rows",
            "candidate_changed_dword_rows", "neutral_changed_dword_rows",
            "candidate_left_distance_dwords", "neutral_left_distance_dwords",
            "candidate_right_distance_dwords", "neutral_right_distance_dwords",
            "exact_adaptive_island_profile", "classification", "brightness_semantics", "prototype_status",
        ], comparison_rows)
        write_tsv(output_dir / "SLOT_LIGHT_LOCAL_CHANGE_ISLAND_SKIPPED.tsv", ["scope", "reason"], [])

        summary = {
            "type": "br_quartet_restoration_reflector_slot_light_local_change_island_evidence_summary",
            "format_version": 1,
            "tool_version": TOOL_VERSION,
            "source_stage86_tool_version": summary86.get("tool_version"),
            "source_stage79_tool_version": summary79.get("tool_version"),
            "status": "PC02_ringlight_and_neutral_control_adaptive_change_islands_compared_brightness_semantics_unresolved",
            "semantic_leaf_candidate_rows": EXPECTED_CANDIDATE_ROWS,
            "adaptive_change_island_rows": len(island_rows),
            "shared_exact_transition_rows": len(shared),
            "candidate_only_transition_rows": len(candidate_only),
            "neutral_only_transition_rows": len(sibling_only),
            "exact_adaptive_island_profile_rows": int(exact_island_profile),
            "prototype_candidate_rows": 0,
            "brightness_semantics_confirmed": False,
            "heroine_name_bindings_resolved": 0,
            "skipped_rows": 0,
            "parameters": {
                "stable_boundary_run_dwords": STABLE_RUN_DWORDS,
                "maximum_scan_radius_dwords": MAX_SCAN_RADIUS_DWORDS,
                "alignment_method": "one_constant_local_target_minus_source_shift_per_adjacent_field_pair",
                "island_boundary_method": "nearest_stable_runs_of_unchanged_aligned_dwords_before_and_after_both_fields",
            },
            "policy": {
                "installed_game_modified": False,
                "render_payload_written": False,
                "event_payload_written": False,
                "global_bloom_hdr_gamma_or_exposure_restore_attempted": False,
                "pak_repacked": False,
                "core_registry_modified": False,
                "profile_activated": False,
                "runtime_validation_inferred": False,
                "censorship_semantics_inferred": False,
                "heroine_names_inferred_from_slot_numbers": False,
                "canary_track_modified": False,
                "full_proprietary_payloads_exported": False,
            },
            "next_action": "Upload this report. If the adaptive islands are identical, close both 150 -> 75 leaves as one shared local engine/effect-record change. If residual transitions differ, retain only candidate-only residuals for a later format-aware G1E record-boundary audit. Do not infer brightness or build a prototype from numeric appearance alone.",
        }
        (output_dir / "SUMMARY.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        archive_path: Path | None = None
        if create_archive:
            archive_path = reports / REPORT_NAME
            make_archive(output_dir, archive_path)
        progress("completed")
        return output_dir, archive_path, summary


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path, default=PROJECT_ROOT_DEFAULT)
    parser.add_argument("--no-archive", action="store_true")
    args = parser.parse_args(argv)
    try:
        output, archive, summary = build_report(args.project_root, create_archive=not args.no_archive)
    except Stage87Error as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print(json.dumps({"output_dir": str(output), "archive": str(archive) if archive else None, "summary": summary}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
