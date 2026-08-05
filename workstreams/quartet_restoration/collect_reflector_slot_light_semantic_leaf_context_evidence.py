#!/usr/bin/env python3
"""Classify non-common Reflector light float leads using exact context and sibling controls.

Stage 84 aligned the six structurally distinct ringlight/eyelight G1E members
and exported 62 finite-float interpretations.  Most raw dwords can still be
record permutations, packed indices, offsets or serializer changes.  This
read-only stage rehydrates the same six members plus sibling G1E/G1EM controls,
checks dword-multiset conservation, reverse transitions, masked local contexts
and same-context values in sibling members.  It never assigns brightness
semantics or writes a render payload.
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
from collections import Counter, defaultdict
from pathlib import Path, PurePosixPath
from typing import Any, Callable, Iterable, Mapping, Sequence

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT_DEFAULT = SCRIPT_DIR.parent.parent

TOOL_VERSION = "0.0.99"
REPORT_NAME = "BR_quartet_restoration_reflector_slot_light_semantic_leaf_context_evidence.tar.zst"
REPORT_DIR = "reflector_slot_light_semantic_leaf_context_evidence"
STAGE79_DIR = "reflector_character_slot_render_member_evidence"
STAGE79_ARCHIVE = "BR_quartet_restoration_reflector_character_slot_render_member_evidence.tar.zst"
STAGE84_DIR = "reflector_slot_light_g1e_structure_evidence"
STAGE84_ARCHIVE = "BR_quartet_restoration_reflector_slot_light_g1e_structure_evidence.tar.zst"
COMMON_FAMILY_KEY = "ringlight:e_cmn_ringlight_PCXX.g1e"
EXPECTED_SCOPE_ROWS = 6
EXPECTED_STAGE84_FLOAT_ROWS = 62
CONTEXT_RADIUS_DWORDS = 4
EFFECT_EXTENSIONS = {".g1e", ".g1em"}


class Stage85Error(RuntimeError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise Stage85Error(message)


def progress(message: str) -> None:
    print(f"[stage85] {message}", file=sys.stderr, flush=True)


def parse_int(value: Any, default: int = 0) -> int:
    try:
        text = str(value).strip()
        return int(text, 16) if text.lower().startswith("0x") else int(text)
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
            raise Stage85Error(f"missing required TSV: {path}")
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
        raise Stage85Error(f"invalid JSON {path}: {exc}") from exc
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
    spec = importlib.util.spec_from_file_location(name, path)
    require(spec is not None and spec.loader is not None, f"cannot load module: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def stable_key(row: Mapping[str, Any]) -> tuple[str, str]:
    return (str(row.get("normalized_path", "")).casefold(), str(row.get("member_key", "")).casefold())


def validate_stage84(root: Path) -> dict[str, Any]:
    summary = load_json(root / "SUMMARY.json")
    require(summary.get("type") == "br_quartet_restoration_reflector_slot_light_g1e_structure_evidence_summary", "stage84 type mismatch")
    require(summary.get("tool_version") == "0.0.98", "stage84 tool version mismatch")
    require(summary.get("status") == "non_common_reflector_light_members_structurally_aligned_semantic_brightness_values_not_yet_resolved", "stage84 status mismatch")
    require(parse_int(summary.get("scope_member_rows"), -1) == EXPECTED_SCOPE_ROWS, "stage84 scope count mismatch")
    require(parse_int(summary.get("finite_float_lead_rows"), -1) == EXPECTED_STAGE84_FLOAT_ROWS, "stage84 finite-float count mismatch")
    require(parse_int(summary.get("prototype_candidate_rows"), -1) == 0, "stage84 unexpectedly produced a prototype")
    require(parse_int(summary.get("skipped_rows"), -1) == 0, "stage84 contains skipped rows")
    require(parse_bool(summary.get("common_ringlight_closed_as_structural_compaction")), "stage84 did not preserve common-ringlight closure")
    return summary


def dword_counter(payload: bytes) -> Counter[int]:
    usable = len(payload) - (len(payload) % 4)
    return Counter(int.from_bytes(payload[offset:offset + 4], "little") for offset in range(0, usable, 4))


def dword_counter_span(payload: bytes, start: int, end: int) -> Counter[int]:
    require(0 <= start <= end <= len(payload), "invalid dword span")
    start += (-start) % 4
    end -= end % 4
    if end <= start:
        return Counter()
    return Counter(int.from_bytes(payload[offset:offset + 4], "little") for offset in range(start, end, 4))


def packed_index_like(source_value: int, target_value: int) -> bool:
    return (source_value >> 16) == (target_value >> 16) and 0 < abs((source_value & 0xFFFF) - (target_value & 0xFFFF)) <= 4


def parse_finite_float(text: str) -> float | None:
    try:
        value = float(text)
    except (TypeError, ValueError):
        return None
    return value if math.isfinite(value) else None


def context_parts(payload: bytes, offset: int, radius_dwords: int = CONTEXT_RADIUS_DWORDS) -> tuple[bytes, bytes] | None:
    radius = radius_dwords * 4
    if offset % 4 or offset < radius or offset + 4 + radius > len(payload):
        return None
    return payload[offset - radius:offset], payload[offset + 4:offset + 4 + radius]


def find_masked_context(payload: bytes, pre: bytes, post: bytes, *, maximum_matches: int = 128) -> list[int]:
    require(len(pre) == len(post) and len(pre) % 4 == 0, "masked context must be symmetric and dword-aligned")
    matches: list[int] = []
    cursor = 0
    while True:
        position = payload.find(pre, cursor)
        if position < 0:
            break
        center = position + len(pre)
        if center % 4 == 0 and payload[center + 4:center + 4 + len(post)] == post:
            matches.append(center)
            if len(matches) >= maximum_matches:
                break
        cursor = position + 1
    return matches


def member_scope(stage81: Any, name: str) -> str:
    return stage81.control_scope(name)


def transition_similarity(left: Sequence[Mapping[str, Any]], right: Sequence[Mapping[str, Any]]) -> tuple[int, int, int, float]:
    a = Counter(str(row.get("transition_id", "")) for row in left if row.get("transition_id"))
    b = Counter(str(row.get("transition_id", "")) for row in right if row.get("transition_id"))
    intersection = sum((a & b).values())
    union = sum((a | b).values())
    score = intersection / union if union else 1.0
    return sum(a.values()), sum(b.values()), intersection, score


def classify_float_lead(
    row: Mapping[str, Any], *, source_payload: bytes, target_payload: bytes,
    segment: Mapping[str, Any], finite_rows_for_member: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    source_value = parse_int(row.get("source_u32_hex"), -1)
    target_value = parse_int(row.get("target_u32_hex"), -1)
    source_offset = parse_int(row.get("source_offset"), -1)
    target_offset = parse_int(row.get("target_offset"), -1)
    source_float = parse_finite_float(str(row.get("source_float32", "")))
    target_float = parse_finite_float(str(row.get("target_float32", "")))
    require(source_value >= 0 and target_value >= 0 and source_offset >= 0 and target_offset >= 0, "malformed finite-float row")
    require(source_offset + 4 <= len(source_payload) and target_offset + 4 <= len(target_payload), "finite-float offset outside payload")
    require(int.from_bytes(source_payload[source_offset:source_offset + 4], "little") == source_value, "finite-float source value does not match payload")
    require(int.from_bytes(target_payload[target_offset:target_offset + 4], "little") == target_value, "finite-float target value does not match payload")

    source_start = parse_int(segment.get("source_start"), -1)
    source_end = parse_int(segment.get("source_end_exclusive"), -1)
    target_start = parse_int(segment.get("target_start"), -1)
    target_end = parse_int(segment.get("target_end_exclusive"), -1)
    require(source_start >= 0 and target_start >= 0, "malformed segment row")
    source_segment_counter = dword_counter_span(source_payload, source_start, source_end)
    target_segment_counter = dword_counter_span(target_payload, target_start, target_end)
    source_member_counter = dword_counter(source_payload)
    target_member_counter = dword_counter(target_payload)
    reverse_count = sum(
        str(other.get("source_u32_hex", "")).casefold() == str(row.get("target_u32_hex", "")).casefold()
        and str(other.get("target_u32_hex", "")).casefold() == str(row.get("source_u32_hex", "")).casefold()
        for other in finite_rows_for_member
    )
    segment_multiset_equal = source_segment_counter == target_segment_counter
    source_removed_net = max(0, source_member_counter[source_value] - target_member_counter[source_value])
    target_added_net = max(0, target_member_counter[target_value] - source_member_counter[target_value])
    packed = packed_index_like(source_value, target_value)
    plausible = source_float is not None and target_float is not None and abs(source_float) <= 1.0e6 and abs(target_float) <= 1.0e6

    if packed:
        classification = "packed_index_or_flag_like_not_float_leaf"
    elif segment_multiset_equal or reverse_count:
        classification = "record_permutation_or_reordering_not_leaf"
    elif not source_removed_net or not target_added_net:
        classification = "word_reused_or_shifted_without_net_value_change"
    elif not plausible:
        classification = "finite_interpretation_outside_semantic_review_range"
    else:
        classification = "semantic_leaf_candidate_requires_masked_context_control"

    source_context = context_parts(source_payload, source_offset)
    target_context = context_parts(target_payload, target_offset)
    return {
        **dict(row),
        "segment_type": segment.get("segment_type", ""),
        "segment_multiset_equal": segment_multiset_equal,
        "reverse_transition_rows_in_member": reverse_count,
        "source_word_count_source_member": source_member_counter[source_value],
        "source_word_count_target_member": target_member_counter[source_value],
        "target_word_count_source_member": source_member_counter[target_value],
        "target_word_count_target_member": target_member_counter[target_value],
        "source_value_removed_net": source_removed_net,
        "target_value_added_net": target_added_net,
        "packed_index_like": packed,
        "source_context_available": source_context is not None,
        "target_context_available": target_context is not None,
        "masked_source_context_id": sha256((source_context[0] + source_context[1]) if source_context else b""),
        "masked_target_context_id": sha256((target_context[0] + target_context[1]) if target_context else b""),
        "lead_classification": classification,
    }


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

    stage80 = load_module(project_root / "workstreams/quartet_restoration/collect_reflector_light_family_binary_evidence.py", "stage80_for_stage85")
    stage81 = load_module(project_root / "workstreams/quartet_restoration/collect_reflector_ringlight_control_callsite_evidence.py", "stage81_for_stage85")
    progress("validating stage 79 and 84 reports")
    with tempfile.TemporaryDirectory(prefix="br-stage85-") as temporary_name:
        temporary = Path(temporary_name)
        stage79_root = locate(reports, STAGE79_DIR, STAGE79_ARCHIVE, temporary / "79")
        stage84_root = locate(reports, STAGE84_DIR, STAGE84_ARCHIVE, temporary / "84")
        summary79 = stage81.validate_stage79(stage79_root)
        summary84 = validate_stage84(stage84_root)

        scope = [row for row in stage80.select_scope(stage79_root) if row.get("family_key") != COMMON_FAMILY_KEY]
        require(len(scope) == EXPECTED_SCOPE_ROWS, f"expected {EXPECTED_SCOPE_ROWS} non-common light rows, found {len(scope)}")
        parent_scope = stage81.select_parent_scope(stage79_root)
        actual_rules = rules_file or project_root / "titles/blue_reflection/modules/quartet_restoration/mappings/effect_material_rules.tsv"
        loader = container_loader or stage81.load_parent_containers
        containers, skipped = loader(
            scope_rows=parent_scope, workspace_root=workspace, report_root=reports,
            rules_file=actual_rules, maximum_earc_bytes=maximum_earc_bytes,
        )
        require(not skipped, f"parent container loader skipped {len(skipped)} rows")
        require(len(containers) == 4, f"expected four parent containers, found {len(containers)}")

        pair_by_key: dict[tuple[str, str], dict[str, Any]] = {}
        all_pairs: list[dict[str, Any]] = []
        for index, container in enumerate(containers, start=1):
            progress(f"indexing sibling container {index}/{len(containers)}: {container.get('normalized_path', '')}")
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
                require(key not in pair_by_key, f"duplicate sibling member identity: {key}")
                pair_by_key[key] = pair
                all_pairs.append(pair)

        audit84 = read_tsv(stage84_root / "SLOT_LIGHT_MEMBER_STRUCTURE_AUDIT.tsv")
        segment84 = read_tsv(stage84_root / "SLOT_LIGHT_ALIGNMENT_SEGMENTS.tsv")
        dwords84 = read_tsv(stage84_root / "SLOT_LIGHT_ALIGNED_CHANGED_DWORDS.tsv")
        finite84 = read_tsv(stage84_root / "SLOT_LIGHT_FINITE_FLOAT_LEADS.tsv")
        require(len(audit84) == EXPECTED_SCOPE_ROWS, "stage84 member audit count mismatch")
        require(len(finite84) == EXPECTED_STAGE84_FLOAT_ROWS, "stage84 finite table count mismatch")

        segment_map: dict[tuple[tuple[str, str], str], dict[str, str]] = {}
        for row in segment84:
            key = (stable_key(row), str(row.get("segment_id", "")))
            require(all(key[0]) and key[1], "stage84 segment identity incomplete")
            require(key not in segment_map, f"duplicate stage84 segment identity: {key}")
            segment_map[key] = row

        audit_map = {stable_key(row): row for row in audit84}
        require(len(audit_map) == EXPECTED_SCOPE_ROWS, "stage84 audit identity is not unique")
        scope_by_key = {stable_key(row): row for row in scope}
        target_pairs: dict[tuple[str, str], dict[str, Any]] = {}
        for key, scope_row in scope_by_key.items():
            pair = pair_by_key.get(key)
            require(pair is not None, f"target pair missing from parent containers: {key}")
            audit = audit_map.get(key)
            require(audit is not None, f"stage84 audit row missing: {key}")
            require(audit.get("source_sha256") == sha256(pair["source_payload"]), f"stage84 source hash mismatch: {key}")
            require(audit.get("target_sha256") == sha256(pair["target_payload"]), f"stage84 target hash mismatch: {key}")
            target_pairs[key] = {**pair, **scope_row}

        finite_by_member: dict[tuple[str, str], list[dict[str, str]]] = defaultdict(list)
        for row in finite84:
            finite_by_member[stable_key(row)].append(row)

        classification_rows: list[dict[str, Any]] = []
        for key, rows in sorted(finite_by_member.items()):
            pair = target_pairs.get(key)
            require(pair is not None, f"finite lead member missing: {key}")
            for row in rows:
                segment = segment_map.get((key, str(row.get("segment_id", ""))))
                require(segment is not None, f"finite lead segment missing: {key} {row.get('segment_id', '')}")
                classification_rows.append(classify_float_lead(
                    row, source_payload=pair["source_payload"], target_payload=pair["target_payload"],
                    segment=segment, finite_rows_for_member=rows,
                ))

        progress(f"classified {len(classification_rows)} finite-float interpretations")
        candidate_rows = [row for row in classification_rows if row.get("lead_classification") == "semantic_leaf_candidate_requires_masked_context_control"]

        similarity_rows: list[dict[str, Any]] = []
        keys = sorted(target_pairs)
        dwords_by_key: dict[tuple[str, str], list[dict[str, str]]] = defaultdict(list)
        for row in dwords84:
            dwords_by_key[stable_key(row)].append(row)
        for left_index, left_key in enumerate(keys):
            for right_key in keys[left_index + 1:]:
                left = target_pairs[left_key]
                right = target_pairs[right_key]
                left_count, right_count, intersection, score = transition_similarity(dwords_by_key[left_key], dwords_by_key[right_key])
                similarity_rows.append({
                    "left_member_name": left.get("member_name", ""), "right_member_name": right.get("member_name", ""),
                    "left_asset_role": left.get("asset_role", ""), "right_asset_role": right.get("asset_role", ""),
                    "left_transition_rows": left_count, "right_transition_rows": right_count,
                    "shared_transition_rows": intersection, "multiset_jaccard": f"{score:.9f}",
                    "review_status": "delta_transition_similarity_not_record_binding_proof",
                })

        context_match_rows: list[dict[str, Any]] = []
        semantic_rows: list[dict[str, Any]] = []
        for index, candidate in enumerate(candidate_rows, start=1):
            progress(f"scanning masked context {index}/{len(candidate_rows)}: {candidate.get('member_name', '')}@{candidate.get('source_offset', '')}")
            key = stable_key(candidate)
            pair = target_pairs[key]
            source_offset = parse_int(candidate.get("source_offset"), -1)
            target_offset = parse_int(candidate.get("target_offset"), -1)
            source_context = context_parts(pair["source_payload"], source_offset)
            target_context = context_parts(pair["target_payload"], target_offset)
            require(source_context is not None and target_context is not None, f"candidate context unavailable: {key}")
            source_pre, source_post = source_context
            target_pre, target_post = target_context
            candidate_id = sha256(
                f"{key[0]}\0{key[1]}\0{source_offset}\0{target_offset}\0{candidate.get('transition_id', '')}".encode("utf-8")
            )[:24]
            exact_transition_siblings = 0
            unchanged_siblings = 0
            alternative_siblings = 0
            matched_pair_rows = 0
            source_value = parse_int(candidate.get("source_u32_hex"), -1)
            target_value = parse_int(candidate.get("target_u32_hex"), -1)
            for sibling in all_pairs:
                source_matches = find_masked_context(sibling["source_payload"], source_pre, source_post)
                target_matches = find_masked_context(sibling["target_payload"], target_pre, target_post)
                if not source_matches or not target_matches:
                    continue
                if len(source_matches) != 1 or len(target_matches) != 1:
                    context_match_rows.append({
                        "candidate_id": candidate_id, "candidate_member_name": candidate.get("member_name", ""),
                        "sibling_normalized_path": sibling["normalized_path"], "sibling_member_key": sibling["member_key"],
                        "sibling_member_name": sibling["member_name"], "control_scope": member_scope(stage81, sibling["member_name"]),
                        "source_context_match_count": len(source_matches), "target_context_match_count": len(target_matches),
                        "source_offset": "", "target_offset": "", "source_u32_hex": "", "target_u32_hex": "",
                        "transition_relation": "ambiguous_context_occurrence", "review_status": "not_counted_as_sibling_record_binding",
                    })
                    continue
                source_match = source_matches[0]
                target_match = target_matches[0]
                sibling_source = int.from_bytes(sibling["source_payload"][source_match:source_match + 4], "little")
                sibling_target = int.from_bytes(sibling["target_payload"][target_match:target_match + 4], "little")
                matched_pair_rows += 1
                if sibling_source == source_value and sibling_target == target_value:
                    relation = "exact_same_transition"
                    if stable_key(sibling) != key:
                        exact_transition_siblings += 1
                elif sibling_source == sibling_target:
                    relation = "same_context_stable_value"
                    if stable_key(sibling) != key:
                        unchanged_siblings += 1
                else:
                    relation = "same_context_alternative_transition"
                    if stable_key(sibling) != key:
                        alternative_siblings += 1
                context_match_rows.append({
                    "candidate_id": candidate_id, "candidate_member_name": candidate.get("member_name", ""),
                    "sibling_normalized_path": sibling["normalized_path"], "sibling_member_key": sibling["member_key"],
                    "sibling_member_name": sibling["member_name"], "control_scope": member_scope(stage81, sibling["member_name"]),
                    "source_context_match_count": 1, "target_context_match_count": 1,
                    "source_offset": source_match, "target_offset": target_match,
                    "source_u32_hex": f"0x{sibling_source:08x}", "target_u32_hex": f"0x{sibling_target:08x}",
                    "transition_relation": relation, "review_status": "masked_context_match_not_parameter_name_proof",
                })

            if exact_transition_siblings:
                status = "shared_transition_in_sibling_record_context_engine_or_family_change_possible"
            elif unchanged_siblings:
                status = "candidate_leaf_has_stable_sibling_record_control_semantic_role_still_unknown"
            elif alternative_siblings:
                status = "candidate_leaf_has_alternative_sibling_values_semantic_role_still_unknown"
            else:
                status = "isolated_candidate_leaf_context_no_sibling_binding"
            semantic_rows.append({
                "candidate_id": candidate_id,
                **{field: candidate.get(field, "") for field in (
                    "character_slot", "asset_role", "family_key", "normalized_path", "member_key", "member_name",
                    "segment_id", "source_offset", "target_offset", "source_u32_hex", "target_u32_hex",
                    "source_float32", "target_float32", "source_value_removed_net", "target_value_added_net",
                    "masked_source_context_id", "masked_target_context_id",
                )},
                "matched_record_pair_rows": matched_pair_rows,
                "exact_same_transition_sibling_rows": exact_transition_siblings,
                "stable_value_sibling_rows": unchanged_siblings,
                "alternative_transition_sibling_rows": alternative_siblings,
                "semantic_leaf_status": status,
                "brightness_semantics": "unresolved",
                "prototype_status": "evidence_only_no_G1E_write",
            })

        output_dir = reports / REPORT_DIR
        output_dir.mkdir(parents=True, exist_ok=True)
        write_tsv(output_dir / "SLOT_LIGHT_FLOAT_LEAD_CLASSIFICATION.tsv", [
            "character_slot", "asset_role", "family_key", "normalized_path", "member_key", "member_name", "segment_id",
            "source_offset", "target_offset", "source_u32_hex", "target_u32_hex", "source_float32", "target_float32",
            "segment_type", "segment_multiset_equal", "reverse_transition_rows_in_member",
            "source_word_count_source_member", "source_word_count_target_member",
            "target_word_count_source_member", "target_word_count_target_member",
            "source_value_removed_net", "target_value_added_net", "packed_index_like",
            "source_context_available", "target_context_available", "masked_source_context_id", "masked_target_context_id",
            "lead_classification", "transition_id",
        ], classification_rows)
        write_tsv(output_dir / "SLOT_LIGHT_MEMBER_DELTA_SIMILARITY.tsv", [
            "left_member_name", "right_member_name", "left_asset_role", "right_asset_role",
            "left_transition_rows", "right_transition_rows", "shared_transition_rows", "multiset_jaccard", "review_status",
        ], similarity_rows)
        write_tsv(output_dir / "SLOT_LIGHT_MASKED_CONTEXT_SIBLING_MATCHES.tsv", [
            "candidate_id", "candidate_member_name", "sibling_normalized_path", "sibling_member_key", "sibling_member_name",
            "control_scope", "source_context_match_count", "target_context_match_count", "source_offset", "target_offset",
            "source_u32_hex", "target_u32_hex", "transition_relation", "review_status",
        ], context_match_rows)
        write_tsv(output_dir / "SLOT_LIGHT_SEMANTIC_LEAF_CANDIDATES.tsv", [
            "candidate_id", "character_slot", "asset_role", "family_key", "normalized_path", "member_key", "member_name",
            "segment_id", "source_offset", "target_offset", "source_u32_hex", "target_u32_hex", "source_float32", "target_float32",
            "source_value_removed_net", "target_value_added_net", "masked_source_context_id", "masked_target_context_id",
            "matched_record_pair_rows", "exact_same_transition_sibling_rows", "stable_value_sibling_rows",
            "alternative_transition_sibling_rows", "semantic_leaf_status", "brightness_semantics", "prototype_status",
        ], semantic_rows)
        write_tsv(output_dir / "SLOT_LIGHT_SEMANTIC_CONTEXT_SKIPPED.tsv", [
            "scope", "normalized_path", "member_key", "side", "reason",
        ], [])

        class_counts = Counter(str(row.get("lead_classification", "")) for row in classification_rows)
        summary = {
            "type": "br_quartet_restoration_reflector_slot_light_semantic_leaf_context_evidence_summary",
            "format_version": 1,
            "tool_version": TOOL_VERSION,
            "source_stage84_tool_version": summary84.get("tool_version"),
            "source_stage79_tool_version": summary79.get("tool_version"),
            "status": "non_common_slot_light_float_interpretations_classified_by_multiset_and_masked_sibling_context_brightness_semantics_unresolved",
            "scope_member_rows": EXPECTED_SCOPE_ROWS,
            "sibling_G1E_G1EM_member_rows": len(all_pairs),
            "finite_float_input_rows": len(classification_rows),
            "packed_index_or_flag_rows": class_counts["packed_index_or_flag_like_not_float_leaf"],
            "record_permutation_or_reordering_rows": class_counts["record_permutation_or_reordering_not_leaf"],
            "word_reused_or_shifted_rows": class_counts["word_reused_or_shifted_without_net_value_change"],
            "semantic_leaf_candidate_rows": len(semantic_rows),
            "masked_context_match_rows": len(context_match_rows),
            "exact_same_transition_sibling_rows": sum(parse_int(row.get("exact_same_transition_sibling_rows")) for row in semantic_rows),
            "stable_value_sibling_rows": sum(parse_int(row.get("stable_value_sibling_rows")) for row in semantic_rows),
            "alternative_transition_sibling_rows": sum(parse_int(row.get("alternative_transition_sibling_rows")) for row in semantic_rows),
            "prototype_candidate_rows": 0,
            "brightness_semantics_confirmed": False,
            "heroine_name_bindings_resolved": 0,
            "skipped_rows": 0,
            "parameters": {
                "context_radius_dwords": CONTEXT_RADIUS_DWORDS,
                "context_match_method": "exact_pre_and_post_dword_windows_with_one_masked_center_dword",
                "semantic_leaf_gate": "net_source_value_removal_and_net_target_value_addition_without_reverse_transition_or_segment_multiset_conservation",
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
            "next_action": "Upload this report. Treat permutation, packed-index and no-net-value rows as structural evidence only. Review only surviving semantic-leaf candidates and their exact masked sibling contexts. Do not build a G1E prototype until a stable sibling field or format-aware record boundary proves a semantic leaf and separates it from inserted/remastered records.",
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
    except Stage85Error as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print(json.dumps({"output_dir": str(output), "archive": str(archive) if archive else None, "summary": summary}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
