#!/usr/bin/env python3
"""Deep-audit Reflector ringlight and eyelight members across all PC slots.

Stage 79 inventoried names and families only. Stage 80 rehydrates the exact
Original/Quartet G1E payloads for the 21 ringlight/eyelight members, verifies
stage-7/8 hashes and metadata, computes linear equal-offset delta runs and
compares cross-slot transition/layout signatures. It writes metadata only.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import subprocess
import sys
import tempfile
from collections import Counter, defaultdict
from pathlib import Path, PurePosixPath
from typing import Any, Callable, Iterable, Mapping, Sequence

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT_DEFAULT = SCRIPT_DIR.parent.parent
TEXT_TOOL_DIR = PROJECT_ROOT_DEFAULT / "Blue_Reflection_Text_Tool"
if str(TEXT_TOOL_DIR) not in sys.path:
    sys.path.insert(0, str(TEXT_TOOL_DIR))
import br_restoration_tool as BR  # noqa: E402

TOOL_VERSION = "0.0.93"
REPORT_NAME = "BR_quartet_restoration_reflector_light_family_binary_evidence.tar.zst"
REPORT_DIR = "reflector_light_family_binary_evidence"
STAGE79_DIR = "reflector_character_slot_render_member_evidence"
STAGE79_ARCHIVE = "BR_quartet_restoration_reflector_character_slot_render_member_evidence.tar.zst"
SHADER_DIR = "shader_effect_evidence"
SHADER_ARCHIVE = "BR_quartet_restoration_shader_effect_evidence.tar.zst"
BINARY_DIR = "binary_delta_evidence"
BINARY_ARCHIVE = "BR_quartet_restoration_binary_delta_evidence.tar.zst"
EXPECTED_SCOPE_ROWS = 21
EXPECTED_RINGLIGHT_ROWS = 19
EXPECTED_EYELIGHT_ROWS = 2
EXPECTED_COMMON_RINGLIGHT_ROWS = 15

class Stage80Error(RuntimeError):
    pass

def require(condition: bool, message: str) -> None:
    if not condition:
        raise Stage80Error(message)

def progress(message: str) -> None:
    print(f"[stage80] {message}", file=sys.stderr, flush=True)

def parse_int(value: Any, default: int = 0) -> int:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return default

def parse_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(str(value).strip())
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
            raise Stage80Error(f"missing required TSV: {path}")
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
        raise Stage80Error(f"invalid JSON {path}: {exc}") from exc
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
    path = report_root / direct
    return path if path.is_dir() else extract_archive(report_root / archive, temporary)

def make_archive(source: Path, output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(output.name + ".tmp")
    temporary.unlink(missing_ok=True)
    completed = subprocess.run(["tar", "--zstd", "-cf", str(temporary), "-C", str(source.parent), source.name], text=True, capture_output=True)
    require(completed.returncode == 0, completed.stderr.strip())
    os.replace(temporary, output)

def stable_key(row: Mapping[str, Any]) -> tuple[str, str, str]:
    return (
        str(row.get("candidate_id", "")),
        str(row.get("normalized_path", "")).casefold(),
        str(row.get("member_key", "")).casefold(),
    )

def validate_stage79(root: Path) -> dict[str, Any]:
    summary = load_json(root / "SUMMARY.json")
    require(summary.get("type") == "br_quartet_restoration_reflector_character_slot_render_member_evidence_summary", "stage79 type mismatch")
    require(summary.get("tool_version") == "0.0.92", "stage79 must use tool version 0.0.92")
    require(parse_int(summary.get("character_slot_rows"), -1) == 15, "stage79 must contain 15 PC slots")
    require(parse_int(summary.get("slot_member_rows"), -1) == 220, "stage79 slot member count mismatch")
    require(parse_int(summary.get("ringlight_family_rows"), -1) == 5, "stage79 ringlight family count mismatch")
    require(parse_int(summary.get("eyelight_family_rows"), -1) == 2, "stage79 eyelight family count mismatch")
    policy = summary.get("policy") or {}
    require(isinstance(policy, dict), "stage79 policy malformed")
    for field in ("installed_game_modified", "render_payload_written", "pak_repacked", "core_registry_modified", "profile_activated"):
        require(not parse_bool(policy.get(field)), f"stage79 performed forbidden action: {field}")
    return summary

def validate_shader(root: Path) -> dict[str, Any]:
    summary = load_json(root / "SUMMARY.json")
    require(summary.get("type") == "br_quartet_restoration_shader_effect_evidence_summary", "shader report type mismatch")
    require(summary.get("status") == "focused_shader_effect_posteffect_evidence_complete_manual_confirmation_required", "shader report incomplete")
    require(parse_int(summary.get("skipped_rows"), -1) == 0, "shader report contains skipped rows")
    return summary

def validate_binary(root: Path) -> dict[str, Any]:
    summary = load_json(root / "SUMMARY.json")
    require(summary.get("type") == "br_quartet_restoration_binary_delta_evidence_summary", "binary report type mismatch")
    require(summary.get("status") == "focused_binary_and_DXBC_chunk_delta_complete_controlled_prototypes_not_generated", "binary report incomplete")
    require(parse_int(summary.get("skipped_rows"), -1) == 0, "binary report contains skipped rows")
    return summary

def select_scope(stage79_root: Path) -> list[dict[str, str]]:
    rows = read_tsv(stage79_root / "REFLECTOR_SLOT_RENDER_MEMBERS.tsv")
    scope = [row for row in rows if row.get("asset_role") in {"ringlight", "eyelight"}]
    require(len(scope) == EXPECTED_SCOPE_ROWS, f"expected {EXPECTED_SCOPE_ROWS} ringlight/eyelight rows, found {len(scope)}")
    require(sum(row.get("asset_role") == "ringlight" for row in scope) == EXPECTED_RINGLIGHT_ROWS, "ringlight member count mismatch")
    require(sum(row.get("asset_role") == "eyelight" for row in scope) == EXPECTED_EYELIGHT_ROWS, "eyelight member count mismatch")
    common = [row for row in scope if row.get("family_key") == "ringlight:e_cmn_ringlight_PCXX.g1e"]
    require(len(common) == EXPECTED_COMMON_RINGLIGHT_ROWS, "common ringlight family must contain PC00-PC14")
    require(sorted(row.get("character_slot", "") for row in common) == [f"PC{i:02d}" for i in range(15)], "common ringlight slots mismatch")
    return sorted(scope, key=lambda row: (row.get("family_key", ""), row.get("character_slot", ""), row.get("member_key", "")))

def targeted_rehydrate(
    *, scope_rows: Sequence[Mapping[str, Any]], workspace_root: Path, report_root: Path,
    rules_file: Path, maximum_earc_bytes: int,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    differences = BR.load_report_jsons(report_root, "differences")
    effects = BR.build_effect_material_candidates(differences, BR.load_effect_material_rules(rules_file))
    effect_map: dict[tuple[str, str], dict[str, Any]] = {}
    for effect in effects:
        key = (str(effect.get("candidate_id", "")), str(effect.get("normalized_path", "")).casefold())
        if key in effect_map:
            raise Stage80Error(f"duplicate effect candidate identity: {key}")
        effect_map[key] = effect
    grouped: dict[tuple[str, str], list[Mapping[str, Any]]] = defaultdict(list)
    for row in scope_rows:
        grouped[(str(row.get("candidate_id", "")), str(row.get("normalized_path", "")).casefold())].append(row)
    pairs: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    for group_index, ((candidate_id, folded_path), rows) in enumerate(sorted(grouped.items()), start=1):
        progress(f"rehydrating container {group_index}/{len(grouped)}: {folded_path}")
        effect = effect_map.get((candidate_id, folded_path))
        if effect is None:
            raise Stage80Error(f"effect candidate missing for {candidate_id} {folded_path}")
        archives: dict[str, dict[str, Any] | None] = {"source": None, "target": None}
        for side in ("source", "target"):
            ref = effect.get(side)
            if not ref:
                skipped.append({"candidate_id": candidate_id, "normalized_path": folded_path, "member_key": "<archive>", "side": side, "reason": "archive_reference_missing"})
                continue
            local = BR.inventory_workspace_file(workspace_root, side, str(effect.get("pair_id", "")), str(ref.get("archive", "")), str(ref.get("path", "")))
            if not local.is_file():
                skipped.append({"candidate_id": candidate_id, "normalized_path": folded_path, "member_key": "<archive>", "side": side, "reason": "workspace_file_missing"})
                continue
            try:
                archives[side] = BR.read_earc_archive(local, maximum_bytes=maximum_earc_bytes, include_member_payloads=True)
            except Exception as exc:
                skipped.append({"candidate_id": candidate_id, "normalized_path": folded_path, "member_key": "<archive>", "side": side, "reason": f"archive_parse_failed:{exc}"})
        source_members = {str(member["comparison_key"]).casefold(): member for member in (archives["source"] or {}).get("members", [])}
        target_members = {str(member["comparison_key"]).casefold(): member for member in (archives["target"] or {}).get("members", [])}
        for row in rows:
            member_key = str(row.get("member_key", "")).casefold()
            left = source_members.get(member_key)
            right = target_members.get(member_key)
            if left is None or right is None:
                skipped.append({"candidate_id": candidate_id, "normalized_path": folded_path, "member_key": member_key, "side": "pair", "reason": "source_or_target_member_missing"})
                continue
            pairs.append({
                **effect,
                "member_key": member_key,
                "source_member_name": str(left.get("name", "")),
                "target_member_name": str(right.get("name", "")),
                "source_payload": left.get("payload"),
                "target_payload": right.get("payload"),
            })
    return pairs, skipped

def changed_runs(source: bytes, target: bytes) -> list[tuple[int, int]]:
    require(len(source) == len(target), "changed_runs requires equal sizes")
    runs: list[tuple[int, int]] = []
    cursor = 0
    while cursor < len(source):
        if source[cursor] == target[cursor]:
            cursor += 1
            continue
        start = cursor
        cursor += 1
        while cursor < len(source) and source[cursor] != target[cursor]:
            cursor += 1
        runs.append((start, cursor))
    return runs

def transition_id(source_span: bytes, target_span: bytes) -> str:
    digest = hashlib.sha256()
    digest.update(len(source_span).to_bytes(8, "little"))
    digest.update(source_span)
    digest.update(target_span)
    return digest.hexdigest()

def signature(parts: Sequence[str]) -> str:
    return hashlib.sha256("\n".join(parts).encode("utf-8")).hexdigest()

def build_report(
    project_root: Path, *, create_archive: bool = True,
    workspace_root: Path | None = None, report_root: Path | None = None,
    rules_file: Path | None = None, maximum_earc_bytes: int = 512 * 1024 * 1024,
    maximum_payload_bytes: int = 16 * 1024 * 1024,
    header_guard_bytes: int = 16, tail_guard_bytes: int = 16,
    pair_loader: Callable[..., tuple[list[dict[str, Any]], list[dict[str, Any]]]] | None = None,
) -> tuple[Path, Path | None, dict[str, Any]]:
    project_root = project_root.resolve()
    reports = (report_root or project_root / ".local/reports/quartet_restoration").resolve()
    workspace = (workspace_root or project_root / ".local/build/quartet_restoration").resolve()
    require(reports.is_dir(), f"missing report root: {reports}")
    progress("validating stage 79 and stage-7/8 reports")
    with tempfile.TemporaryDirectory(prefix="br-stage80-") as temporary_name:
        temporary = Path(temporary_name)
        stage79 = locate(reports, STAGE79_DIR, STAGE79_ARCHIVE, temporary / "79")
        shader = locate(reports, SHADER_DIR, SHADER_ARCHIVE, temporary / "7")
        binary = locate(reports, BINARY_DIR, BINARY_ARCHIVE, temporary / "8")
        summary79 = validate_stage79(stage79)
        summary7 = validate_shader(shader)
        summary8 = validate_binary(binary)
        scope_rows = select_scope(stage79)
        progress(f"selected {len(scope_rows)} ringlight/eyelight members across 15 slots")

        binary_rows = read_tsv(binary / "PAYLOAD_BINARY_DELTA.tsv")
        binary_map: dict[tuple[str, str, str], dict[str, str]] = {}
        for row in binary_rows:
            key = stable_key(row)
            if key in binary_map:
                raise Stage80Error(f"duplicate binary member row: {key}")
            binary_map[key] = row
        payload_rows = read_tsv(shader / "RENDER_PAYLOADS.tsv")
        payload_map: dict[tuple[str, str, str, str], dict[str, str]] = {}
        for row in payload_rows:
            key = (*stable_key(row), str(row.get("side", "")))
            if key in payload_map:
                raise Stage80Error(f"duplicate render payload row: {key}")
            payload_map[key] = row

        actual_rules = rules_file or project_root / "titles/blue_reflection/modules/quartet_restoration/mappings/effect_material_rules.tsv"
        loader = pair_loader or targeted_rehydrate
        pairs, loader_skipped = loader(
            scope_rows=scope_rows,
            workspace_root=workspace,
            report_root=reports,
            rules_file=actual_rules,
            maximum_earc_bytes=maximum_earc_bytes,
        )
        if loader_skipped:
            raise Stage80Error(f"targeted render loader skipped {len(loader_skipped)} rows")
        pair_map: dict[tuple[str, str, str], dict[str, Any]] = {}
        for pair in pairs:
            key = stable_key(pair)
            if key in pair_map:
                raise Stage80Error(f"duplicate rehydrated pair: {key}")
            pair_map[key] = pair
        require(len(pair_map) == len(scope_rows), f"rehydrated {len(pair_map)} of {len(scope_rows)} scoped members")

        member_rows: list[dict[str, Any]] = []
        operation_rows: list[dict[str, Any]] = []
        transition_groups: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
        for index, scope in enumerate(scope_rows, start=1):
            key = stable_key(scope)
            progress(f"auditing member {index}/{len(scope_rows)}: {scope.get('character_slot')} {scope.get('member_name')}")
            pair = pair_map.get(key)
            require(pair is not None, f"rehydrated pair missing: {key}")
            binary_row = binary_map.get(key)
            require(binary_row is not None, f"binary delta row missing: {key}")
            require(binary_row.get("classification") == "changed", f"member is not changed in binary report: {key}")
            source = pair.get("source_payload")
            target = pair.get("target_payload")
            require(isinstance(source, (bytes, bytearray)) and isinstance(target, (bytes, bytearray)), f"payload missing: {key}")
            source = bytes(source); target = bytes(target)
            require(len(source) <= maximum_payload_bytes and len(target) <= maximum_payload_bytes, f"payload exceeds stage80 limit: {key}")
            for side, payload in (("source", source), ("target", target)):
                metadata = payload_map.get((*key, side))
                require(metadata is not None, f"render payload metadata missing: {key} side={side}")
                require(parse_int(metadata.get("payload_size"), -1) == len(payload), f"payload size mismatch: {key} side={side}")
                require(metadata.get("payload_sha256") == sha256(payload), f"payload hash mismatch: {key} side={side}")
            source_name = str(pair.get("source_member_name", ""))
            target_name = str(pair.get("target_member_name", ""))
            require(source_name and target_name, f"member names missing: {key}")
            same_size = len(source) == len(target)
            operations: list[dict[str, Any]] = []
            if same_size:
                for operation_index, (start, end) in enumerate(changed_runs(source, target)):
                    source_span = source[start:end]
                    target_span = target[start:end]
                    tid = transition_id(source_span, target_span)
                    eligible = start >= header_guard_bytes and end <= len(target) - tail_guard_bytes and start % 4 == 0 and end % 4 == 0
                    row = {
                        "character_slot": scope.get("character_slot", ""),
                        "asset_role": scope.get("asset_role", ""),
                        "family_key": scope.get("family_key", ""),
                        "normalized_path": scope.get("normalized_path", ""),
                        "member_key": scope.get("member_key", ""),
                        "operation_index": operation_index,
                        "start": start,
                        "end": end,
                        "span_size": end - start,
                        "source_span_sha256": sha256(source_span),
                        "target_span_sha256": sha256(target_span),
                        "transition_id": tid,
                        "offset_transition_id": signature([str(start), str(end), tid]),
                        "aligned_32bit": start % 4 == 0 and end % 4 == 0,
                        "outside_header_tail_guards": start >= header_guard_bytes and end <= len(target) - tail_guard_bytes,
                        "base_eligible": eligible,
                    }
                    operations.append(row)
                    operation_rows.append(row)
                    transition_groups[(str(scope.get("family_key", "")), tid)].append(row)
            content_signature = signature([f"{row['span_size']}:{row['transition_id']}" for row in operations]) if operations else ""
            layout_signature = signature([f"{row['start']}:{row['end']}:{row['transition_id']}" for row in operations]) if operations else ""
            if same_size:
                candidate = bytearray(target)
                for row in operations:
                    candidate[int(row["start"]):int(row["end"])] = source[int(row["start"]):int(row["end"])]
                candidate_bytes = bytes(candidate)
                reverse = bytearray(candidate_bytes)
                for row in operations:
                    reverse[int(row["start"]):int(row["end"])] = target[int(row["start"]):int(row["end"])]
                exact_source = candidate_bytes == source
                exact_target = bytes(reverse) == target
            else:
                exact_source = exact_target = False
            changed_bytes = sum(a != b for a, b in zip(source, target)) + abs(len(source) - len(target))
            member_rows.append({
                "character_slot": scope.get("character_slot", ""),
                "asset_role": scope.get("asset_role", ""),
                "family_key": scope.get("family_key", ""),
                "normalized_path": scope.get("normalized_path", ""),
                "member_key": scope.get("member_key", ""),
                "source_member_name": source_name,
                "target_member_name": target_name,
                "source_size": len(source),
                "target_size": len(target),
                "size_delta": len(target) - len(source),
                "source_sha256": sha256(source),
                "target_sha256": sha256(target),
                "changed_bytes": changed_bytes,
                "changed_density": f"{changed_bytes / max(len(source), len(target), 1):.9f}",
                "operation_rows": len(operations),
                "eligible_operation_rows": sum(parse_bool(row.get("base_eligible")) for row in operations),
                "content_signature": content_signature,
                "layout_signature": layout_signature,
                "exact_source_inverse": exact_source,
                "exact_target_roundtrip": exact_target,
                "all_operations_base_eligible": bool(operations) and all(parse_bool(row.get("base_eligible")) for row in operations),
                "audit_status": "exact_static_inverse_metadata_only" if exact_source and exact_target else "size_or_structure_changed_requires_format_aware_audit",
                "heroine_name_binding": "unresolved",
                "brightness_semantics": "unresolved",
            })

        family_groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for row in member_rows:
            family_groups[str(row["family_key"])].append(row)
        family_rows: list[dict[str, Any]] = []
        candidate_rows: list[dict[str, Any]] = []
        for family_key, rows in sorted(family_groups.items()):
            content_signatures = {str(row["content_signature"]) for row in rows if row["content_signature"]}
            layout_signatures = {str(row["layout_signature"]) for row in rows if row["layout_signature"]}
            all_exact = all(parse_bool(row["exact_source_inverse"]) and parse_bool(row["exact_target_roundtrip"]) for row in rows)
            all_eligible = all(parse_bool(row["all_operations_base_eligible"]) for row in rows)
            if len(rows) == 1:
                classification = "slot_selective_single_member"
            elif all_exact and len(content_signatures) == 1 and len(layout_signatures) == 1:
                classification = "uniform_exact_delta_across_slots"
            elif all_exact and len(content_signatures) == 1:
                classification = "uniform_transition_different_layout"
            else:
                classification = "mixed_cross_slot_delta"
            if family_key == "ringlight:e_cmn_ringlight_PCXX.g1e" and len(rows) == 15 and all_exact and all_eligible:
                promotion = "uniform_cross_slot_candidate_requires_semantic_control"
            elif len(rows) == 1 and all_exact and all_eligible:
                promotion = "slot_selective_candidate_requires_character_and_scene_binding"
            else:
                promotion = "evidence_only_binary_family_audit_complete"
            family_row = {
                "family_key": family_key,
                "asset_role": rows[0]["asset_role"],
                "member_rows": len(rows),
                "slot_count": len({str(row["character_slot"]) for row in rows}),
                "slots": ";".join(sorted({str(row["character_slot"]) for row in rows})),
                "same_size_member_rows": sum(parse_int(row["size_delta"]) == 0 for row in rows),
                "exact_inverse_member_rows": sum(parse_bool(row["exact_source_inverse"]) for row in rows),
                "all_eligible_member_rows": sum(parse_bool(row["all_operations_base_eligible"]) for row in rows),
                "unique_content_signatures": len(content_signatures),
                "unique_layout_signatures": len(layout_signatures),
                "family_classification": classification,
                "promotion_status": promotion,
                "heroine_name_binding": "unresolved",
                "brightness_semantics": "unresolved",
            }
            family_rows.append(family_row)
            if promotion != "evidence_only_binary_family_audit_complete":
                candidate_rows.append(family_row)

        cross_rows: list[dict[str, Any]] = []
        for (family_key, tid), rows in sorted(transition_groups.items()):
            cross_rows.append({
                "family_key": family_key,
                "transition_id": tid,
                "member_rows": len(rows),
                "slot_count": len({str(row["character_slot"]) for row in rows}),
                "slots": ";".join(sorted({str(row["character_slot"]) for row in rows})),
                "span_sizes": ";".join(str(value) for value in sorted({parse_int(row["span_size"]) for row in rows})),
                "offsets": ";".join(str(value) for value in sorted({parse_int(row["start"]) for row in rows})),
                "all_base_eligible": all(parse_bool(row["base_eligible"]) for row in rows),
            })

        output_dir = reports / REPORT_DIR
        if output_dir.exists():
            import shutil
            shutil.rmtree(output_dir)
        output_dir.mkdir(parents=True)
        write_tsv(output_dir / "REFLECTOR_LIGHT_MEMBER_BINARY_AUDIT.tsv", [
            "character_slot", "asset_role", "family_key", "normalized_path", "member_key",
            "source_member_name", "target_member_name", "source_size", "target_size", "size_delta",
            "source_sha256", "target_sha256", "changed_bytes", "changed_density", "operation_rows",
            "eligible_operation_rows", "content_signature", "layout_signature", "exact_source_inverse",
            "exact_target_roundtrip", "all_operations_base_eligible", "audit_status", "heroine_name_binding",
            "brightness_semantics",
        ], member_rows)
        write_tsv(output_dir / "REFLECTOR_LIGHT_DELTA_OPERATIONS.tsv", [
            "character_slot", "asset_role", "family_key", "normalized_path", "member_key", "operation_index",
            "start", "end", "span_size", "source_span_sha256", "target_span_sha256", "transition_id",
            "offset_transition_id", "aligned_32bit", "outside_header_tail_guards", "base_eligible",
        ], operation_rows)
        write_tsv(output_dir / "REFLECTOR_LIGHT_FAMILY_BINARY_COMPARISON.tsv", [
            "family_key", "asset_role", "member_rows", "slot_count", "slots", "same_size_member_rows",
            "exact_inverse_member_rows", "all_eligible_member_rows", "unique_content_signatures",
            "unique_layout_signatures", "family_classification", "promotion_status", "heroine_name_binding",
            "brightness_semantics",
        ], family_rows)
        write_tsv(output_dir / "REFLECTOR_LIGHT_CROSS_SLOT_TRANSITIONS.tsv", [
            "family_key", "transition_id", "member_rows", "slot_count", "slots", "span_sizes", "offsets",
            "all_base_eligible",
        ], cross_rows)
        write_tsv(output_dir / "REFLECTOR_LIGHT_STATIC_CANDIDATES.tsv", [
            "family_key", "asset_role", "member_rows", "slot_count", "slots", "same_size_member_rows",
            "exact_inverse_member_rows", "all_eligible_member_rows", "unique_content_signatures",
            "unique_layout_signatures", "family_classification", "promotion_status", "heroine_name_binding",
            "brightness_semantics",
        ], candidate_rows)
        write_tsv(output_dir / "REFLECTOR_LIGHT_BINARY_SKIPPED.tsv", ["candidate_id", "normalized_path", "member_key", "side", "reason"], [])
        common_family = next(row for row in family_rows if row["family_key"] == "ringlight:e_cmn_ringlight_PCXX.g1e")
        summary = {
            "type": "br_quartet_restoration_reflector_light_family_binary_evidence_summary",
            "format_version": 1,
            "tool_version": TOOL_VERSION,
            "source_stage79_tool_version": summary79.get("tool_version"),
            "source_shader_tool_version": summary7.get("tool_version", ""),
            "source_binary_tool_version": summary8.get("tool_version", ""),
            "status": "ringlight_eyelight_exact_binary_families_audited_brightness_semantics_and_heroine_binding_unresolved",
            "scope_member_rows": len(scope_rows),
            "ringlight_member_rows": sum(row["asset_role"] == "ringlight" for row in member_rows),
            "eyelight_member_rows": sum(row["asset_role"] == "eyelight" for row in member_rows),
            "family_rows": len(family_rows),
            "operation_rows": len(operation_rows),
            "candidate_family_rows": len(candidate_rows),
            "common_ringlight_member_rows": parse_int(common_family["member_rows"]),
            "common_ringlight_family_classification": common_family["family_classification"],
            "common_ringlight_promotion_status": common_family["promotion_status"],
            "heroine_name_bindings_resolved": 0,
            "brightness_semantics_confirmed": False,
            "skipped_rows": 0,
            "parameters": {
                "maximum_earc_bytes": maximum_earc_bytes,
                "maximum_payload_bytes": maximum_payload_bytes,
                "header_guard_bytes": header_guard_bytes,
                "tail_guard_bytes": tail_guard_bytes,
                "operation_discovery": "linear_equal_offset_changed_runs",
                "cross_slot_comparison": "content_and_offset_layout_signatures",
            },
            "policy": {
                "installed_game_modified": False,
                "render_payload_written": False,
                "global_bloom_hdr_gamma_or_exposure_restore_attempted": False,
                "pak_repacked": False,
                "core_registry_modified": False,
                "profile_activated": False,
                "runtime_validation_inferred": False,
                "censorship_semantics_inferred": False,
                "heroine_names_inferred_from_slot_numbers": False,
                "canary_track_modified": False,
            },
            "next_action": "Upload this report. If the common ringlight family has a uniform reversible delta, audit neutral non-transformation ringlight controls and exact effect-container call sites before building any cross-slot prototype. Treat slot-selective ringlight/eyelight rows separately and do not infer heroine names from PC numbers.",
        }
        (output_dir / "SUMMARY.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        archive_path = None
        if create_archive:
            archive_path = reports / REPORT_NAME
            make_archive(output_dir, archive_path)
        progress("completed")
        return output_dir, archive_path, summary

def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", required=True, type=Path)
    parser.add_argument("--workspace-root", type=Path)
    parser.add_argument("--report-root", type=Path)
    parser.add_argument("--effect-rules-file", type=Path)
    parser.add_argument("--maximum-earc-bytes", type=int, default=512 * 1024 * 1024)
    parser.add_argument("--maximum-payload-bytes", type=int, default=16 * 1024 * 1024)
    parser.add_argument("--no-report-archive", action="store_true")
    args = parser.parse_args(argv)
    try:
        output, archive, summary = build_report(
            args.project_root,
            create_archive=not args.no_report_archive,
            workspace_root=args.workspace_root,
            report_root=args.report_root,
            rules_file=args.effect_rules_file,
            maximum_earc_bytes=args.maximum_earc_bytes,
            maximum_payload_bytes=args.maximum_payload_bytes,
        )
        print(f"Report directory: {output}")
        print(f"Audited light members: {summary['scope_member_rows']}; families: {summary['family_rows']}")
        if archive:
            print(f"Report: {archive}")
        return 0
    except Stage80Error as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

if __name__ == "__main__":
    raise SystemExit(main())
