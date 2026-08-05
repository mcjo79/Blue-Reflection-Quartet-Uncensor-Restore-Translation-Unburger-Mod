#!/usr/bin/env python3
"""Test whether surviving slot-light numeric leaves belong to a shared G1E record template.

Stage 85 reduced 62 finite-float interpretations to two adjacent 150 -> 75
leaves in e_PC02_w5_ringlight_01.g1e.  The same transition was found under the
same masked four-dword context in neutral-named e_cmn_pup_reflect_s.g1e.  This
read-only stage rehydrates the same four parent containers, expands context
matching to larger symmetric windows, and compares complete local source/target
dword-transition profiles around each center.  It exports hashes and counts
only; it never writes a G1E or assigns brightness/censorship semantics.
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
from collections import Counter
from pathlib import Path, PurePosixPath
from typing import Any, Callable, Iterable, Mapping, Sequence

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT_DEFAULT = SCRIPT_DIR.parent.parent

TOOL_VERSION = "0.1.0"
REPORT_NAME = "BR_quartet_restoration_reflector_slot_light_shared_record_template_evidence.tar.zst"
REPORT_DIR = "reflector_slot_light_shared_record_template_evidence"
STAGE85_DIR = "reflector_slot_light_semantic_leaf_context_evidence"
STAGE85_ARCHIVE = "BR_quartet_restoration_reflector_slot_light_semantic_leaf_context_evidence.tar.zst"
STAGE79_DIR = "reflector_character_slot_render_member_evidence"
STAGE79_ARCHIVE = "BR_quartet_restoration_reflector_character_slot_render_member_evidence.tar.zst"
EXPECTED_CANDIDATE_ROWS = 2
EXPECTED_EXACT_SIBLING_ROWS = 2
EXPECTED_PARENT_CONTAINERS = 4
CONTEXT_RADII_DWORDS = (4, 8, 16, 32, 64)
EFFECT_EXTENSIONS = {".g1e", ".g1em"}


class Stage86Error(RuntimeError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise Stage86Error(message)


def progress(message: str) -> None:
    print(f"[stage86] {message}", file=sys.stderr, flush=True)


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
            raise Stage86Error(f"missing required TSV: {path}")
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
        raise Stage86Error(f"invalid JSON {path}: {exc}") from exc
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


def stable_key(row: Mapping[str, Any]) -> tuple[str, str]:
    return (str(row.get("normalized_path", "")).casefold(), str(row.get("member_key", "")).casefold())


def sibling_key(row: Mapping[str, Any]) -> tuple[str, str]:
    return (str(row.get("sibling_normalized_path", "")).casefold(), str(row.get("sibling_member_key", "")).casefold())


def validate_stage85(root: Path) -> dict[str, Any]:
    summary = load_json(root / "SUMMARY.json")
    require(summary.get("type") == "br_quartet_restoration_reflector_slot_light_semantic_leaf_context_evidence_summary", "stage85 type mismatch")
    require(summary.get("tool_version") == "0.0.99", "stage85 tool version mismatch")
    require(summary.get("status") == "non_common_slot_light_float_interpretations_classified_by_multiset_and_masked_sibling_context_brightness_semantics_unresolved", "stage85 status mismatch")
    require(parse_int(summary.get("finite_float_input_rows"), -1) == 62, "stage85 finite-float count mismatch")
    require(parse_int(summary.get("semantic_leaf_candidate_rows"), -1) == EXPECTED_CANDIDATE_ROWS, "stage85 semantic-leaf count mismatch")
    require(parse_int(summary.get("exact_same_transition_sibling_rows"), -1) == EXPECTED_EXACT_SIBLING_ROWS, "stage85 exact sibling count mismatch")
    require(parse_int(summary.get("prototype_candidate_rows"), -1) == 0, "stage85 unexpectedly authorized a prototype")
    require(parse_int(summary.get("skipped_rows"), -1) == 0, "stage85 contains skipped rows")
    require(not parse_bool(summary.get("brightness_semantics_confirmed")), "stage85 unexpectedly confirmed brightness semantics")
    policy = summary.get("policy") or {}
    require(isinstance(policy, dict), "stage85 policy malformed")
    for field in ("installed_game_modified", "render_payload_written", "pak_repacked", "core_registry_modified", "profile_activated"):
        require(not parse_bool(policy.get(field)), f"stage85 performed forbidden action: {field}")
    return summary


def context_parts(payload: bytes, offset: int, radius_dwords: int) -> tuple[bytes, bytes] | None:
    radius = radius_dwords * 4
    if offset % 4 or offset < radius or offset + 4 + radius > len(payload):
        return None
    return payload[offset - radius:offset], payload[offset + 4:offset + 4 + radius]


def transition_profile(
    source: bytes, target: bytes, source_center: int, target_center: int, radius_dwords: int,
) -> tuple[tuple[int, int, int], ...] | None:
    source_parts = context_parts(source, source_center, radius_dwords)
    target_parts = context_parts(target, target_center, radius_dwords)
    if source_parts is None or target_parts is None:
        return None
    rows: list[tuple[int, int, int]] = []
    for relative in range(-radius_dwords, radius_dwords + 1):
        source_offset = source_center + relative * 4
        target_offset = target_center + relative * 4
        source_value = int.from_bytes(source[source_offset:source_offset + 4], "little")
        target_value = int.from_bytes(target[target_offset:target_offset + 4], "little")
        rows.append((relative, source_value, target_value))
    return tuple(rows)


def profile_hash(profile: Sequence[tuple[int, int, int]] | None) -> str:
    if profile is None:
        return ""
    raw = bytearray()
    for relative, source_value, target_value in profile:
        raw.extend(int(relative).to_bytes(4, "little", signed=True))
        raw.extend(int(source_value).to_bytes(4, "little"))
        raw.extend(int(target_value).to_bytes(4, "little"))
    return sha256(bytes(raw))


def changed_profile_rows(profile: Sequence[tuple[int, int, int]] | None) -> int:
    return sum(source != target for _relative, source, target in (profile or ()))


def index_pairs(containers: Sequence[Mapping[str, Any]]) -> tuple[dict[tuple[str, str], dict[str, Any]], list[dict[str, Any]]]:
    pair_by_key: dict[tuple[str, str], dict[str, Any]] = {}
    all_pairs: list[dict[str, Any]] = []
    for container in containers:
        source_members = {str(row.get("comparison_key", "")).casefold(): row for row in container.get("source_members", [])}
        target_members = {str(row.get("comparison_key", "")).casefold(): row for row in container.get("target_members", [])}
        for member_key in sorted(set(source_members) & set(target_members)):
            left = source_members[member_key]
            right = target_members[member_key]
            name = str(right.get("name") or left.get("name") or "")
            if Path(name).suffix.casefold() not in EFFECT_EXTENSIONS:
                continue
            pair = {
                "normalized_path": str(container.get("normalized_path", "")).casefold(),
                "member_key": member_key,
                "member_name": name,
                "source_payload": bytes(left.get("payload") or b""),
                "target_payload": bytes(right.get("payload") or b""),
            }
            key = stable_key(pair)
            require(key not in pair_by_key, f"duplicate member identity: {key}")
            pair_by_key[key] = pair
            all_pairs.append(pair)
    return pair_by_key, all_pairs


def classify_pair(control_scope: str, maximum_profile_radius: int) -> str:
    neutral = control_scope == "neutral_non_transformation_name_control"
    if neutral and maximum_profile_radius >= 16:
        return "shared_neutral_record_template_transition"
    if neutral and maximum_profile_radius >= 8:
        return "shared_neutral_local_record_transition"
    if maximum_profile_radius >= 8:
        return "shared_named_effect_local_record_transition"
    return "same_center_transition_small_context_only"


def build_report(
    project_root: Path, *, create_archive: bool = True, workspace_root: Path | None = None,
    report_root: Path | None = None, rules_file: Path | None = None,
    maximum_earc_bytes: int = 512 * 1024 * 1024,
    container_loader: Callable[..., tuple[list[dict[str, Any]], list[dict[str, Any]]]] | None = None,
) -> tuple[Path, Path | None, dict[str, Any]]:
    project_root = project_root.resolve()
    reports = (report_root or project_root / ".local/reports/quartet_restoration").resolve()
    workspace = (workspace_root or project_root / ".local/build/quartet_restoration").resolve()
    require(reports.is_dir(), f"missing report root: {reports}")

    stage85 = load_module(project_root / "workstreams/quartet_restoration/collect_reflector_slot_light_semantic_leaf_context_evidence.py", "stage85_for_stage86")
    stage81 = load_module(project_root / "workstreams/quartet_restoration/collect_reflector_ringlight_control_callsite_evidence.py", "stage81_for_stage86")

    progress("validating stage 79 and 85 reports")
    with tempfile.TemporaryDirectory(prefix="br-stage86-") as temporary_name:
        temporary = Path(temporary_name)
        stage85_root = locate(reports, STAGE85_DIR, STAGE85_ARCHIVE, temporary / "85")
        stage79_root = locate(reports, STAGE79_DIR, STAGE79_ARCHIVE, temporary / "79")
        summary85 = validate_stage85(stage85_root)
        summary79 = stage81.validate_stage79(stage79_root)

        candidate_rows = read_tsv(stage85_root / "SLOT_LIGHT_SEMANTIC_LEAF_CANDIDATES.tsv")
        match_rows = read_tsv(stage85_root / "SLOT_LIGHT_MASKED_CONTEXT_SIBLING_MATCHES.tsv")
        require(len(candidate_rows) == EXPECTED_CANDIDATE_ROWS, "stage85 candidate table count mismatch")
        require(all(row.get("source_u32_hex", "").casefold() == "0x43160000" and row.get("target_u32_hex", "").casefold() == "0x42960000" for row in candidate_rows), "stage85 surviving transitions are not the expected 150 -> 75 pair")

        parent_scope = stage81.select_parent_scope(stage79_root)
        actual_rules = rules_file or project_root / "titles/blue_reflection/modules/quartet_restoration/mappings/effect_material_rules.tsv"
        loader = container_loader or stage81.load_parent_containers
        containers, skipped = loader(
            scope_rows=parent_scope, workspace_root=workspace, report_root=reports,
            rules_file=actual_rules, maximum_earc_bytes=maximum_earc_bytes,
        )
        require(not skipped, f"parent container loader skipped {len(skipped)} rows")
        require(len(containers) == EXPECTED_PARENT_CONTAINERS, f"expected {EXPECTED_PARENT_CONTAINERS} parent containers, found {len(containers)}")
        pair_by_key, all_pairs = index_pairs(containers)
        progress(f"indexed {len(all_pairs)} sibling G1E/G1EM member pairs")

        exact_matches_by_candidate: dict[str, list[dict[str, str]]] = {}
        for candidate in candidate_rows:
            candidate_id = str(candidate.get("candidate_id", ""))
            require(candidate_id, "stage85 candidate id missing")
            exact = [
                row for row in match_rows
                if row.get("candidate_id") == candidate_id
                and row.get("transition_relation") == "exact_same_transition"
                and sibling_key(row) != stable_key(candidate)
            ]
            require(exact, f"stage85 exact sibling transition missing for {candidate_id}")
            exact_matches_by_candidate[candidate_id] = exact

        radius_rows: list[dict[str, Any]] = []
        pair_rows: list[dict[str, Any]] = []
        recurrence_rows: list[dict[str, Any]] = []
        skipped_rows: list[dict[str, Any]] = []

        for candidate_index, candidate in enumerate(candidate_rows, start=1):
            candidate_id = str(candidate.get("candidate_id", ""))
            candidate_key = stable_key(candidate)
            candidate_pair = pair_by_key.get(candidate_key)
            require(candidate_pair is not None, f"candidate payload pair missing: {candidate_key}")
            candidate_source_offset = parse_int(candidate.get("source_offset"), -1)
            candidate_target_offset = parse_int(candidate.get("target_offset"), -1)
            require(candidate_source_offset >= 0 and candidate_target_offset >= 0, f"candidate offsets malformed: {candidate_id}")
            progress(f"auditing candidate {candidate_index}/{len(candidate_rows)}: {candidate.get('member_name', '')}@{candidate_source_offset}")

            # Scan the full four-container sibling corpus at progressively larger radii.
            for radius in CONTEXT_RADII_DWORDS:
                candidate_source_context = context_parts(candidate_pair["source_payload"], candidate_source_offset, radius)
                candidate_target_context = context_parts(candidate_pair["target_payload"], candidate_target_offset, radius)
                if candidate_source_context is None or candidate_target_context is None:
                    skipped_rows.append({"candidate_id": candidate_id, "scope": "recurrence", "radius_dwords": radius, "reason": "candidate_context_out_of_bounds"})
                    continue
                source_pre, source_post = candidate_source_context
                target_pre, target_post = candidate_target_context
                for sibling in all_pairs:
                    source_matches = stage85.find_masked_context(sibling["source_payload"], source_pre, source_post)
                    target_matches = stage85.find_masked_context(sibling["target_payload"], target_pre, target_post)
                    if not source_matches or not target_matches:
                        continue
                    relation = "ambiguous_context_occurrence"
                    source_value_hex = target_value_hex = ""
                    if len(source_matches) == 1 and len(target_matches) == 1:
                        source_center = source_matches[0]
                        target_center = target_matches[0]
                        source_value = int.from_bytes(sibling["source_payload"][source_center:source_center + 4], "little")
                        target_value = int.from_bytes(sibling["target_payload"][target_center:target_center + 4], "little")
                        source_value_hex = f"0x{source_value:08x}"
                        target_value_hex = f"0x{target_value:08x}"
                        if source_value_hex == str(candidate.get("source_u32_hex", "")).casefold() and target_value_hex == str(candidate.get("target_u32_hex", "")).casefold():
                            relation = "exact_same_transition"
                        elif source_value == target_value:
                            relation = "same_context_stable_value"
                        else:
                            relation = "same_context_alternative_transition"
                    recurrence_rows.append({
                        "candidate_id": candidate_id,
                        "radius_dwords": radius,
                        "sibling_normalized_path": sibling["normalized_path"],
                        "sibling_member_key": sibling["member_key"],
                        "sibling_member_name": sibling["member_name"],
                        "control_scope": stage81.control_scope(sibling["member_name"]),
                        "source_context_match_count": len(source_matches),
                        "target_context_match_count": len(target_matches),
                        "source_u32_hex": source_value_hex,
                        "target_u32_hex": target_value_hex,
                        "transition_relation": relation,
                    })

            for exact in exact_matches_by_candidate[candidate_id]:
                sibling_key_value = sibling_key(exact)
                sibling_pair = pair_by_key.get(sibling_key_value)
                require(sibling_pair is not None, f"exact sibling payload pair missing: {sibling_key_value}")
                sibling_source_offset = parse_int(exact.get("source_offset"), -1)
                sibling_target_offset = parse_int(exact.get("target_offset"), -1)
                require(sibling_source_offset >= 0 and sibling_target_offset >= 0, f"exact sibling offsets malformed: {sibling_key_value}")
                maximum_source_radius = maximum_target_radius = maximum_joint_radius = maximum_profile_radius = 0
                for radius in CONTEXT_RADII_DWORDS:
                    candidate_source_context = context_parts(candidate_pair["source_payload"], candidate_source_offset, radius)
                    candidate_target_context = context_parts(candidate_pair["target_payload"], candidate_target_offset, radius)
                    sibling_source_context = context_parts(sibling_pair["source_payload"], sibling_source_offset, radius)
                    sibling_target_context = context_parts(sibling_pair["target_payload"], sibling_target_offset, radius)
                    available = all(item is not None for item in (candidate_source_context, candidate_target_context, sibling_source_context, sibling_target_context))
                    source_equal = bool(available and candidate_source_context == sibling_source_context)
                    target_equal = bool(available and candidate_target_context == sibling_target_context)
                    candidate_profile = transition_profile(candidate_pair["source_payload"], candidate_pair["target_payload"], candidate_source_offset, candidate_target_offset, radius) if available else None
                    sibling_profile = transition_profile(sibling_pair["source_payload"], sibling_pair["target_payload"], sibling_source_offset, sibling_target_offset, radius) if available else None
                    profile_equal = bool(available and candidate_profile == sibling_profile)
                    if source_equal:
                        maximum_source_radius = radius
                    if target_equal:
                        maximum_target_radius = radius
                    if source_equal and target_equal:
                        maximum_joint_radius = radius
                    if profile_equal:
                        maximum_profile_radius = radius
                    radius_rows.append({
                        "candidate_id": candidate_id,
                        "candidate_member_name": candidate.get("member_name", ""),
                        "candidate_source_offset": candidate_source_offset,
                        "candidate_target_offset": candidate_target_offset,
                        "sibling_normalized_path": sibling_pair["normalized_path"],
                        "sibling_member_key": sibling_pair["member_key"],
                        "sibling_member_name": sibling_pair["member_name"],
                        "control_scope": stage81.control_scope(sibling_pair["member_name"]),
                        "sibling_source_offset": sibling_source_offset,
                        "sibling_target_offset": sibling_target_offset,
                        "radius_dwords": radius,
                        "context_available": available,
                        "source_masked_context_equal": source_equal,
                        "target_masked_context_equal": target_equal,
                        "joint_masked_context_equal": source_equal and target_equal,
                        "transition_profile_equal": profile_equal,
                        "candidate_changed_dwords_in_window": changed_profile_rows(candidate_profile),
                        "sibling_changed_dwords_in_window": changed_profile_rows(sibling_profile),
                        "candidate_profile_sha256": profile_hash(candidate_profile),
                        "sibling_profile_sha256": profile_hash(sibling_profile),
                    })
                scope = stage81.control_scope(sibling_pair["member_name"])
                pair_rows.append({
                    "candidate_id": candidate_id,
                    "candidate_member_name": candidate.get("member_name", ""),
                    "candidate_source_offset": candidate_source_offset,
                    "candidate_target_offset": candidate_target_offset,
                    "source_u32_hex": candidate.get("source_u32_hex", ""),
                    "target_u32_hex": candidate.get("target_u32_hex", ""),
                    "source_float32": candidate.get("source_float32", ""),
                    "target_float32": candidate.get("target_float32", ""),
                    "sibling_normalized_path": sibling_pair["normalized_path"],
                    "sibling_member_key": sibling_pair["member_key"],
                    "sibling_member_name": sibling_pair["member_name"],
                    "control_scope": scope,
                    "maximum_source_context_radius_dwords": maximum_source_radius,
                    "maximum_target_context_radius_dwords": maximum_target_radius,
                    "maximum_joint_context_radius_dwords": maximum_joint_radius,
                    "maximum_transition_profile_radius_dwords": maximum_profile_radius,
                    "record_template_classification": classify_pair(scope, maximum_profile_radius),
                    "brightness_semantics": "unresolved",
                    "prototype_status": "evidence_only_no_G1E_write",
                })

        output_dir = reports / REPORT_DIR
        output_dir.mkdir(parents=True, exist_ok=True)
        write_tsv(output_dir / "SLOT_LIGHT_SHARED_RECORD_TEMPLATE_PAIRS.tsv", [
            "candidate_id", "candidate_member_name", "candidate_source_offset", "candidate_target_offset",
            "source_u32_hex", "target_u32_hex", "source_float32", "target_float32",
            "sibling_normalized_path", "sibling_member_key", "sibling_member_name", "control_scope",
            "maximum_source_context_radius_dwords", "maximum_target_context_radius_dwords",
            "maximum_joint_context_radius_dwords", "maximum_transition_profile_radius_dwords",
            "record_template_classification", "brightness_semantics", "prototype_status",
        ], pair_rows)
        write_tsv(output_dir / "SLOT_LIGHT_SHARED_RECORD_CONTEXT_RADII.tsv", [
            "candidate_id", "candidate_member_name", "candidate_source_offset", "candidate_target_offset",
            "sibling_normalized_path", "sibling_member_key", "sibling_member_name", "control_scope",
            "sibling_source_offset", "sibling_target_offset", "radius_dwords", "context_available",
            "source_masked_context_equal", "target_masked_context_equal", "joint_masked_context_equal",
            "transition_profile_equal", "candidate_changed_dwords_in_window", "sibling_changed_dwords_in_window",
            "candidate_profile_sha256", "sibling_profile_sha256",
        ], radius_rows)
        write_tsv(output_dir / "SLOT_LIGHT_SHARED_RECORD_CONTEXT_RECURRENCE.tsv", [
            "candidate_id", "radius_dwords", "sibling_normalized_path", "sibling_member_key", "sibling_member_name",
            "control_scope", "source_context_match_count", "target_context_match_count", "source_u32_hex",
            "target_u32_hex", "transition_relation",
        ], recurrence_rows)
        write_tsv(output_dir / "SLOT_LIGHT_SHARED_RECORD_TEMPLATE_SKIPPED.tsv", [
            "candidate_id", "scope", "radius_dwords", "reason",
        ], skipped_rows)

        class_counts = Counter(str(row.get("record_template_classification", "")) for row in pair_rows)
        neutral_template_rows = class_counts["shared_neutral_record_template_transition"]
        neutral_local_rows = class_counts["shared_neutral_local_record_transition"]
        shared_neutral_rows = neutral_template_rows + neutral_local_rows
        summary = {
            "type": "br_quartet_restoration_reflector_slot_light_shared_record_template_evidence_summary",
            "format_version": 1,
            "tool_version": TOOL_VERSION,
            "source_stage85_tool_version": summary85.get("tool_version"),
            "source_stage79_tool_version": summary79.get("tool_version"),
            "status": "surviving_PC02_ringlight_150_to_75_leaves_tested_against_expanded_shared_record_templates_brightness_semantics_unresolved",
            "semantic_leaf_candidate_rows": len(candidate_rows),
            "exact_same_transition_pair_rows": len(pair_rows),
            "sibling_G1E_G1EM_member_rows": len(all_pairs),
            "context_radius_rows": len(radius_rows),
            "context_recurrence_rows": len(recurrence_rows),
            "shared_neutral_record_template_rows": neutral_template_rows,
            "shared_neutral_local_record_rows": neutral_local_rows,
            "shared_neutral_transition_rows": shared_neutral_rows,
            "isolated_candidate_rows": sum(row.get("record_template_classification") == "same_center_transition_small_context_only" for row in pair_rows),
            "prototype_candidate_rows": 0,
            "brightness_semantics_confirmed": False,
            "heroine_name_bindings_resolved": 0,
            "skipped_rows": len(skipped_rows),
            "parameters": {
                "context_radii_dwords": list(CONTEXT_RADII_DWORDS),
                "profile_method": "relative_source_target_dword_transition_vectors_centered_on_the_candidate_field",
                "neutral_template_gate": "neutral_named_sibling_with_exact_same_transition_and_equal_local_transition_profile_at_radius_16_or_greater",
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
            "next_action": "Upload this report. If both 150 -> 75 leaves share an expanded local transition profile with neutral e_cmn_pup_reflect_s, close them as shared engine/family record changes and do not restore them. Otherwise retain only the unmatched residual context for a later format-aware parser. In either case, do not infer brightness or build a G1E prototype from numeric appearance alone.",
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
    except Stage86Error as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print(json.dumps({"output_dir": str(output), "archive": str(archive) if archive else None, "summary": summary}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
