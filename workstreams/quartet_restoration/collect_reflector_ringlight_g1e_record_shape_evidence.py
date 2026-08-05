#!/usr/bin/env python3
"""Audit complete G1E change-cluster shapes for the common Reflector ringlight.

Stage 81 showed that individual 32-bit transitions from the uniform
``e_cmn_ringlight_PC00-PC14`` delta also occur in many neutral effects.  This
stage therefore stops treating isolated words as evidence and compares the
ordered, relative-offset shape of each complete changed cluster, plus the full
three-cluster profile, against every same-size changed G1E/G1EM control in the
four parent containers.  It also records conservative length/count/offset
field candidates around the clusters and emits only metadata.
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
TOOL_VERSION = "0.0.96"
REPORT_NAME = "BR_quartet_restoration_reflector_ringlight_g1e_record_shape_evidence.tar.zst"
REPORT_DIR = "reflector_ringlight_g1e_record_shape_evidence"
STAGE81_DIR = "reflector_ringlight_control_callsite_evidence"
STAGE81_ARCHIVE = "BR_quartet_restoration_reflector_ringlight_control_callsite_evidence.tar.zst"
STAGE80_DIR = "reflector_light_family_binary_evidence"
STAGE80_ARCHIVE = "BR_quartet_restoration_reflector_light_family_binary_evidence.tar.zst"
STAGE79_DIR = "reflector_character_slot_render_member_evidence"
STAGE79_ARCHIVE = "BR_quartet_restoration_reflector_character_slot_render_member_evidence.tar.zst"
EXPECTED_COMMON_ROWS = 15
EXPECTED_ALIGNED_WORD_ROWS = 36
EXPECTED_PARENT_CONTAINERS = 4
CLUSTER_GAP_BYTES_DEFAULT = 0x100
ENVELOPE_WINDOW_BYTES_DEFAULT = 0x80
EFFECT_EXTENSIONS = {".g1e", ".g1em"}


class Stage82Error(RuntimeError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise Stage82Error(message)


def progress(message: str) -> None:
    print(f"[stage82] {message}", file=sys.stderr, flush=True)


def parse_int(value: Any, default: int = 0) -> int:
    try:
        return int(str(value).strip())
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
            raise Stage82Error(f"missing required TSV: {path}")
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
        raise Stage82Error(f"invalid JSON {path}: {exc}") from exc
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


def load_module(path: Path, name: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    require(spec is not None and spec.loader is not None, f"cannot load module: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def validate_stage81(root: Path) -> dict[str, Any]:
    summary = load_json(root / "SUMMARY.json")
    require(summary.get("type") == "br_quartet_restoration_reflector_ringlight_control_callsite_evidence_summary", "stage81 type mismatch")
    require(summary.get("tool_version") == "0.0.95", "stage81 must use corrected tool version 0.0.95")
    require(parse_int(summary.get("common_ringlight_member_rows"), -1) == EXPECTED_COMMON_ROWS, "stage81 common member count mismatch")
    require(parse_int(summary.get("common_ringlight_aligned_word_rows"), -1) == EXPECTED_ALIGNED_WORD_ROWS, "stage81 aligned word count mismatch")
    require(parse_int(summary.get("parent_container_rows"), -1) == EXPECTED_PARENT_CONTAINERS, "stage81 parent container count mismatch")
    require(parse_int(summary.get("skipped_rows"), -1) == 0, "stage81 contains skipped rows")
    require(parse_int(summary.get("prototype_candidate_rows"), -1) == 0, "stage81 unexpectedly contains prototype candidates")
    policy = summary.get("policy") or {}
    require(isinstance(policy, dict), "stage81 policy malformed")
    for field in ("installed_game_modified", "render_payload_written", "event_payload_written", "pak_repacked", "core_registry_modified", "profile_activated"):
        require(not parse_bool(policy.get(field)), f"stage81 performed forbidden action: {field}")
    return summary


def stage80_audit_key(row: Mapping[str, Any]) -> tuple[str, str]:
    return (str(row.get("normalized_path", "")).casefold(), str(row.get("member_key", "")).casefold())


def transition_tuple(row: Mapping[str, Any]) -> tuple[int, str, str]:
    return (
        parse_int(row.get("word_offset"), -1),
        str(row.get("source_u32_hex", "")).casefold(),
        str(row.get("target_u32_hex", "")).casefold(),
    )


def cluster_changed_words(rows: Sequence[Mapping[str, Any]], maximum_gap_bytes: int) -> list[list[dict[str, Any]]]:
    ordered = sorted((dict(row) for row in rows), key=lambda row: parse_int(row.get("word_offset"), -1))
    require(ordered, "cannot cluster an empty aligned-word profile")
    clusters: list[list[dict[str, Any]]] = [[ordered[0]]]
    for row in ordered[1:]:
        previous = parse_int(clusters[-1][-1].get("word_offset"), -1)
        current = parse_int(row.get("word_offset"), -1)
        require(previous >= 0 and current > previous, "aligned word offsets must be strictly increasing")
        if current - previous > maximum_gap_bytes:
            clusters.append([row])
        else:
            clusters[-1].append(row)
    return clusters


def cluster_signature(rows: Sequence[Mapping[str, Any]]) -> tuple[tuple[int, str, str], ...]:
    start = parse_int(rows[0].get("word_offset"), -1)
    return tuple(
        (
            parse_int(row.get("word_offset"), -1) - start,
            str(row.get("source_u32_hex", "")).casefold(),
            str(row.get("target_u32_hex", "")).casefold(),
        )
        for row in rows
    )


def aligned_word_deltas(source: bytes, target: bytes) -> list[dict[str, Any]]:
    require(len(source) == len(target), "aligned word audit requires equal sizes")
    require(len(source) % 4 == 0, "aligned word audit requires dword-sized payload")
    rows: list[dict[str, Any]] = []
    for offset in range(0, len(source), 4):
        left = source[offset:offset + 4]
        right = target[offset:offset + 4]
        if left == right:
            continue
        source_u32 = int.from_bytes(left, "little")
        target_u32 = int.from_bytes(right, "little")
        source_float = struct.unpack("<f", left)[0]
        target_float = struct.unpack("<f", right)[0]
        rows.append({
            "word_offset": offset,
            "source_u32_hex": f"0x{source_u32:08x}",
            "target_u32_hex": f"0x{target_u32:08x}",
            "source_u32": source_u32,
            "target_u32": target_u32,
            "source_float32": source_float,
            "target_float32": target_float,
            "transition_id": hashlib.sha256(left + right).hexdigest(),
        })
    return rows


def find_cluster_matches(control_rows: Sequence[Mapping[str, Any]], cluster_rows: Sequence[Mapping[str, Any]]) -> list[int]:
    by_offset = {parse_int(row.get("word_offset"), -1): row for row in control_rows}
    signature = cluster_signature(cluster_rows)
    first_source = signature[0][1]
    first_target = signature[0][2]
    matches: list[int] = []
    for candidate in control_rows:
        if str(candidate.get("source_u32_hex", "")).casefold() != first_source or str(candidate.get("target_u32_hex", "")).casefold() != first_target:
            continue
        base = parse_int(candidate.get("word_offset"), -1)
        ok = True
        for relative, source_hex, target_hex in signature:
            row = by_offset.get(base + relative)
            if row is None or str(row.get("source_u32_hex", "")).casefold() != source_hex or str(row.get("target_u32_hex", "")).casefold() != target_hex:
                ok = False
                break
        if ok:
            matches.append(base)
    return matches


def is_normal_or_zero_float(value: float) -> bool:
    if not math.isfinite(value):
        return False
    if value == 0.0:
        return True
    magnitude = abs(value)
    return 1.0e-20 <= magnitude <= 1.0e20


def classify_word(source_u32: int, target_u32: int, source_float: float, target_float: float) -> str:
    if source_u32 <= 0x10000 and target_u32 <= 0x10000:
        if source_u32 in {0, 1} and target_u32 in {0, 1}:
            return "flag_or_boolean_candidate"
        if source_u32 % 4 == 0 and target_u32 % 4 == 0:
            return "small_count_size_or_relative_offset_candidate"
        return "small_integer_or_enum_candidate"
    if is_normal_or_zero_float(source_float) and is_normal_or_zero_float(target_float):
        return "normal_float_leaf_candidate"
    return "opaque_or_pointer_like_word"


def control_scope(stage81_module: Any, member_name: str) -> str:
    return str(stage81_module.control_scope(member_name))


def header_ascii(word: bytes) -> str:
    return "".join(chr(byte) if 32 <= byte <= 126 else "." for byte in word)


def build_report(
    project_root: Path, *, create_archive: bool = True,
    workspace_root: Path | None = None, report_root: Path | None = None,
    rules_file: Path | None = None, maximum_earc_bytes: int = 512 * 1024 * 1024,
    cluster_gap_bytes: int = CLUSTER_GAP_BYTES_DEFAULT,
    envelope_window_bytes: int = ENVELOPE_WINDOW_BYTES_DEFAULT,
    container_loader: Callable[..., tuple[list[dict[str, Any]], list[dict[str, Any]]]] | None = None,
) -> tuple[Path, Path | None, dict[str, Any]]:
    project_root = project_root.resolve()
    reports = (report_root or project_root / ".local/reports/quartet_restoration").resolve()
    workspace = (workspace_root or project_root / ".local/build/quartet_restoration").resolve()
    require(reports.is_dir(), f"missing report root: {reports}")
    require(cluster_gap_bytes >= 4 and cluster_gap_bytes % 4 == 0, "cluster gap must be a positive dword multiple")
    require(envelope_window_bytes >= 16 and envelope_window_bytes % 4 == 0, "envelope window must be a dword multiple")

    stage81_module = load_module(project_root / "workstreams/quartet_restoration/collect_reflector_ringlight_control_callsite_evidence.py", "stage81_for_stage82")
    progress("validating stage 79-81 reports")
    with tempfile.TemporaryDirectory(prefix="br-stage82-") as temporary_name:
        temporary = Path(temporary_name)
        stage81_root = locate(reports, STAGE81_DIR, STAGE81_ARCHIVE, temporary / "81")
        stage80_root = locate(reports, STAGE80_DIR, STAGE80_ARCHIVE, temporary / "80")
        stage79_root = locate(reports, STAGE79_DIR, STAGE79_ARCHIVE, temporary / "79")
        summary81 = validate_stage81(stage81_root)
        summary80 = stage81_module.validate_stage80(stage80_root)
        summary79 = stage81_module.validate_stage79(stage79_root)

        canonical_rows = read_tsv(stage81_root / "COMMON_RINGLIGHT_ALIGNED_WORD_TRANSITIONS.tsv")
        require(len(canonical_rows) == EXPECTED_ALIGNED_WORD_ROWS, "stage81 canonical aligned-word table count mismatch")
        clusters = cluster_changed_words(canonical_rows, cluster_gap_bytes)
        require(len(clusters) >= 2, "common ringlight profile did not separate into multiple changed clusters")
        transition_matches81 = read_tsv(stage81_root / "RINGLIGHT_CONTROL_TRANSITION_MATCHES.tsv")
        neutral_individual_counts = Counter(
            row.get("transition_id", "")
            for row in transition_matches81
            if row.get("control_scope") == "neutral_non_transformation_name_control"
        )

        common_scope = stage81_module.select_common_scope(stage79_root)
        parent_scope = stage81_module.select_parent_scope(stage79_root)
        actual_rules = rules_file or project_root / "titles/blue_reflection/modules/quartet_restoration/mappings/effect_material_rules.tsv"
        actual_loader = container_loader or stage81_module.load_parent_containers
        containers, skipped = actual_loader(
            scope_rows=parent_scope,
            workspace_root=workspace,
            report_root=reports,
            rules_file=actual_rules,
            maximum_earc_bytes=maximum_earc_bytes,
        )
        require(not skipped, f"parent container loader skipped {len(skipped)} rows")
        require(len(containers) == EXPECTED_PARENT_CONTAINERS, f"expected four parent containers, found {len(containers)}")

        audit80_rows = read_tsv(stage80_root / "REFLECTOR_LIGHT_MEMBER_BINARY_AUDIT.tsv")
        audit80: dict[tuple[str, str], dict[str, str]] = {}
        for row in audit80_rows:
            key = stage80_audit_key(row)
            require(all(key), f"stage80 audit identity incomplete: {key}")
            require(key not in audit80, f"duplicate stage80 audit identity: {key}")
            audit80[key] = row
        require(len(audit80) == 21, "stage80 member audit count mismatch")

        common_keys = {(str(row.get("normalized_path", "")).casefold(), str(row.get("member_key", "")).casefold()) for row in common_scope}
        pair_by_key: dict[tuple[str, str], dict[str, Any]] = {}
        all_control_pairs: list[dict[str, Any]] = []
        for index, container in enumerate(containers, start=1):
            progress(f"indexing parent container {index}/{len(containers)}: {container.get('normalized_path', '')}")
            source_members = {str(row.get("comparison_key", "")).casefold(): row for row in container.get("source_members", [])}
            target_members = {str(row.get("comparison_key", "")).casefold(): row for row in container.get("target_members", [])}
            for member_key in sorted(set(source_members) & set(target_members)):
                left = source_members[member_key]
                right = target_members[member_key]
                name = str(right.get("name") or left.get("name") or "")
                extension = Path(name).suffix.casefold()
                if extension not in EFFECT_EXTENSIONS:
                    continue
                pair = {
                    "normalized_path": str(container.get("normalized_path", "")).casefold(),
                    "member_key": member_key,
                    "member_name": name,
                    "source_payload": bytes(left.get("payload") or b""),
                    "target_payload": bytes(right.get("payload") or b""),
                }
                pair_by_key[(pair["normalized_path"], member_key)] = pair
                if (pair["normalized_path"], member_key) not in common_keys:
                    all_control_pairs.append(pair)

        common_pairs: list[dict[str, Any]] = []
        canonical_delta: list[dict[str, Any]] | None = None
        for scope in common_scope:
            key = (str(scope.get("normalized_path", "")).casefold(), str(scope.get("member_key", "")).casefold())
            pair = pair_by_key.get(key)
            require(pair is not None, f"common ringlight pair missing: {key}")
            audit = audit80.get(key)
            require(audit is not None, f"stage80 common audit row missing: {key}")
            require(audit.get("source_sha256") == sha256(pair["source_payload"]), f"stage80 source hash mismatch: {key}")
            require(audit.get("target_sha256") == sha256(pair["target_payload"]), f"stage80 target hash mismatch: {key}")
            deltas = aligned_word_deltas(pair["source_payload"], pair["target_payload"])
            simplified = [(row["word_offset"], row["source_u32_hex"], row["target_u32_hex"]) for row in deltas]
            expected = [transition_tuple(row) for row in canonical_rows]
            require(simplified == expected, f"common ringlight aligned profile mismatch: {key}")
            if canonical_delta is None:
                canonical_delta = deltas
            else:
                require(simplified == [(row["word_offset"], row["source_u32_hex"], row["target_u32_hex"]) for row in canonical_delta], "common ringlight profile is not uniform")
            common_pairs.append({**pair, "character_slot": scope.get("character_slot", "")})
        require(canonical_delta is not None, "common ringlight canonical payload missing")

        cluster_rows: list[dict[str, Any]] = []
        cluster_word_rows: list[dict[str, Any]] = []
        cluster_signatures: list[tuple[tuple[int, str, str], ...]] = []
        for index, rows in enumerate(clusters, start=1):
            signature = cluster_signature(rows)
            cluster_signatures.append(signature)
            start = parse_int(rows[0].get("word_offset"), -1)
            end = parse_int(rows[-1].get("word_offset"), -1) + 4
            signature_id = hashlib.sha256(json.dumps(signature, separators=(",", ":")).encode("utf-8")).hexdigest()
            cluster_rows.append({
                "cluster_id": f"cluster_{index:02d}", "start_offset": start, "end_offset_exclusive": end,
                "span_bytes": end - start, "changed_word_rows": len(rows), "signature_id": signature_id,
                "slot_count": len(common_pairs), "uniform_across_slots": True,
                "review_status": "complete_ordered_transition_cluster_requires_control_shape_comparison",
            })
            for row in rows:
                cluster_word_rows.append({
                    "cluster_id": f"cluster_{index:02d}",
                    "relative_offset": parse_int(row.get("word_offset"), -1) - start,
                    **row,
                    "neutral_individual_transition_matches": neutral_individual_counts.get(row.get("transition_id", ""), 0),
                    "review_status": "isolated_word_match_not_semantic_proof",
                })

        control_rows: list[dict[str, Any]] = []
        cluster_match_rows: list[dict[str, Any]] = []
        full_profile_rows: list[dict[str, Any]] = []
        semantic_candidate_rows: list[dict[str, Any]] = []
        neutral_cluster_matches_by_id: Counter[str] = Counter()
        named_cluster_matches_by_id: Counter[str] = Counter()

        for index, pair in enumerate(all_control_pairs, start=1):
            if index == 1 or index % 50 == 0 or index == len(all_control_pairs):
                progress(f"auditing G1E/G1EM control {index}/{len(all_control_pairs)}")
            source = pair["source_payload"]
            target = pair["target_payload"]
            scope = control_scope(stage81_module, pair["member_name"])
            if source == target:
                control_rows.append({
                    **{k: pair[k] for k in ("normalized_path", "member_key", "member_name")},
                    "control_scope": scope, "source_size": len(source), "target_size": len(target),
                    "classification": "identical_control", "changed_word_rows": 0,
                    "matched_cluster_count": 0, "full_profile_match": False,
                    "review_status": "no_change_profile_to_compare",
                })
                continue
            if len(source) != len(target) or len(source) % 4:
                control_rows.append({
                    **{k: pair[k] for k in ("normalized_path", "member_key", "member_name")},
                    "control_scope": scope, "source_size": len(source), "target_size": len(target),
                    "classification": "size_or_structure_changed_control", "changed_word_rows": 0,
                    "matched_cluster_count": 0, "full_profile_match": False,
                    "review_status": "separate_format_aware_audit_required",
                })
                continue
            deltas = aligned_word_deltas(source, target)
            matched_starts: list[list[int]] = []
            for cluster_index, cluster in enumerate(clusters, start=1):
                starts = find_cluster_matches(deltas, cluster)
                matched_starts.append(starts)
                for start in starts:
                    row = {
                        **{k: pair[k] for k in ("normalized_path", "member_key", "member_name")},
                        "control_scope": scope, "cluster_id": f"cluster_{cluster_index:02d}",
                        "control_cluster_start": start,
                        "common_cluster_start": parse_int(cluster[0].get("word_offset"), -1),
                        "translation_delta": start - parse_int(cluster[0].get("word_offset"), -1),
                        "cluster_signature_id": cluster_rows[cluster_index - 1]["signature_id"],
                        "review_status": "complete_cluster_shape_match_not_parameter_semantics_proof",
                    }
                    cluster_match_rows.append(row)
                    if scope == "neutral_non_transformation_name_control":
                        neutral_cluster_matches_by_id[row["cluster_id"]] += 1
                    else:
                        named_cluster_matches_by_id[row["cluster_id"]] += 1

            translations: set[int] | None = None
            for cluster, starts in zip(clusters, matched_starts):
                common_start = parse_int(cluster[0].get("word_offset"), -1)
                current = {start - common_start for start in starts}
                translations = current if translations is None else translations & current
            full_translations = sorted(translations or set())
            for translation in full_translations:
                full_profile_rows.append({
                    **{k: pair[k] for k in ("normalized_path", "member_key", "member_name")},
                    "control_scope": scope, "translation_delta": translation,
                    "cluster_count": len(clusters), "changed_word_rows": len(deltas),
                    "review_status": "full_common_three_cluster_profile_match_likely_shared_record_or_serialization_shape",
                })
            control_rows.append({
                **{k: pair[k] for k in ("normalized_path", "member_key", "member_name")},
                "control_scope": scope, "source_size": len(source), "target_size": len(target),
                "classification": "same_size_changed_control", "changed_word_rows": len(deltas),
                "matched_cluster_count": sum(bool(starts) for starts in matched_starts),
                "full_profile_match": bool(full_translations),
                "review_status": "full_profile_overlap_found" if full_translations else ("partial_cluster_overlap_found" if any(matched_starts) else "no_complete_cluster_overlap"),
            })

        # Conservative structural field candidates around the canonical PC00 clusters.
        source0 = common_pairs[0]["source_payload"]
        target0 = common_pairs[0]["target_payload"]
        envelope_rows: list[dict[str, Any]] = []
        changed_offsets = {row["word_offset"] for row in canonical_delta}
        for cluster_index, cluster in enumerate(clusters, start=1):
            start = parse_int(cluster[0].get("word_offset"), -1)
            end = parse_int(cluster[-1].get("word_offset"), -1) + 4
            scan_start = max(0, (start - envelope_window_bytes) // 4 * 4)
            scan_end = min(len(source0), ((end + envelope_window_bytes + 3) // 4) * 4)
            for offset in range(scan_start, scan_end, 4):
                source_word = source0[offset:offset + 4]
                target_word = target0[offset:offset + 4]
                if len(source_word) != 4 or len(target_word) != 4:
                    continue
                source_u32 = int.from_bytes(source_word, "little")
                target_u32 = int.from_bytes(target_word, "little")
                source_float = struct.unpack("<f", source_word)[0]
                target_float = struct.unpack("<f", target_word)[0]
                field_class = classify_word(source_u32, target_u32, source_float, target_float)
                changed = offset in changed_offsets
                span_contains_cluster = False
                possible_bases: list[str] = []
                for basis_name, basis in (("field_start", offset), ("after_field", offset + 4)):
                    source_end = basis + source_u32
                    target_end = basis + target_u32
                    if 0 <= source_end <= len(source0) and 0 <= target_end <= len(target0) and source_u32 >= 8 and target_u32 >= 8:
                        if source_end >= start and target_end >= start:
                            span_contains_cluster = True
                            possible_bases.append(basis_name)
                if not changed and not span_contains_cluster:
                    continue
                if changed or field_class in {"small_count_size_or_relative_offset_candidate", "flag_or_boolean_candidate"}:
                    envelope_rows.append({
                        "cluster_id": f"cluster_{cluster_index:02d}", "field_offset": offset,
                        "relative_to_cluster_start": offset - start,
                        "source_u32_hex": f"0x{source_u32:08x}", "target_u32_hex": f"0x{target_u32:08x}",
                        "source_float32": f"{source_float:.9g}" if math.isfinite(source_float) else str(source_float),
                        "target_float32": f"{target_float:.9g}" if math.isfinite(target_float) else str(target_float),
                        "changed_word": changed, "field_class": field_class,
                        "span_contains_cluster": span_contains_cluster, "possible_length_bases": ";".join(possible_bases),
                        "review_status": "candidate_envelope_or_leaf_field_requires_exact_g1e_parser",
                    })

        neutral_full_profiles = [row for row in full_profile_rows if row.get("control_scope") == "neutral_non_transformation_name_control"]
        named_full_profiles = [row for row in full_profile_rows if row.get("control_scope") != "neutral_non_transformation_name_control"]
        neutral_cluster_ids = {row.get("cluster_id") for row in cluster_match_rows if row.get("control_scope") == "neutral_non_transformation_name_control"}
        for row in canonical_delta:
            source_u32 = int(row["source_u32"])
            target_u32 = int(row["target_u32"])
            source_float = float(row["source_float32"])
            target_float = float(row["target_float32"])
            transition_id = str(row["transition_id"])
            field_class = classify_word(source_u32, target_u32, source_float, target_float)
            cluster_id = next(
                f"cluster_{index:02d}" for index, cluster in enumerate(clusters, start=1)
                if parse_int(cluster[0].get("word_offset"), -1) <= row["word_offset"] <= parse_int(cluster[-1].get("word_offset"), -1)
            )
            if (
                field_class == "normal_float_leaf_candidate"
                and neutral_individual_counts.get(transition_id, 0) == 0
                and cluster_id not in neutral_cluster_ids
                and not neutral_full_profiles
            ):
                semantic_candidate_rows.append({
                    "cluster_id": cluster_id, "word_offset": row["word_offset"],
                    "source_u32_hex": row["source_u32_hex"], "target_u32_hex": row["target_u32_hex"],
                    "source_float32": f"{source_float:.9g}", "target_float32": f"{target_float:.9g}",
                    "transition_id": transition_id, "field_class": field_class,
                    "neutral_individual_transition_matches": 0,
                    "neutral_complete_cluster_matches": neutral_cluster_matches_by_id.get(cluster_id, 0),
                    "review_status": "metadata_only_semantic_leaf_candidate_not_brightness_proof",
                })

        header_rows: list[dict[str, Any]] = []
        header_bytes = min(0x80, len(source0), len(target0))
        header_bytes -= header_bytes % 4
        for offset in range(0, header_bytes, 4):
            left = source0[offset:offset + 4]
            right = target0[offset:offset + 4]
            header_rows.append({
                "word_offset": offset,
                "source_u32_hex": f"0x{int.from_bytes(left, 'little'):08x}",
                "target_u32_hex": f"0x{int.from_bytes(right, 'little'):08x}",
                "source_ascii4": header_ascii(left), "target_ascii4": header_ascii(right),
                "identical": left == right,
                "review_status": "technical_header_profile_only",
            })

        if neutral_full_profiles:
            status = "common_ringlight_full_three_cluster_profile_occurs_in_neutral_g1e_controls_likely_shared_serialization_shape"
            next_action = "Upload this report. Treat the common ringlight delta as a likely shared G1E record/serialization change, not a brightness prototype. Continue with the structurally different slot-specific ringlight/eyelight members and exact G1E record parsing."
        elif neutral_cluster_ids:
            status = "common_ringlight_complete_clusters_partially_overlap_neutral_g1e_controls_record_parser_required"
            next_action = "Upload this report. Individual complete clusters, but not necessarily the full profile, occur in neutral controls. Parse exact G1E record boundaries before selecting any semantic leaf value."
        else:
            status = "common_ringlight_complete_cluster_profile_isolated_but_semantics_unresolved"
            next_action = "Upload this report. The complete cluster profile is isolated from neutral controls, but exact G1E record boundaries and semantic parameter identities remain required before any prototype."

        output_dir = reports / REPORT_DIR
        if output_dir.exists():
            import shutil
            shutil.rmtree(output_dir)
        output_dir.mkdir(parents=True)
        write_tsv(output_dir / "COMMON_RINGLIGHT_CHANGE_CLUSTERS.tsv", [
            "cluster_id", "start_offset", "end_offset_exclusive", "span_bytes", "changed_word_rows",
            "signature_id", "slot_count", "uniform_across_slots", "review_status",
        ], cluster_rows)
        write_tsv(output_dir / "COMMON_RINGLIGHT_CLUSTER_WORDS.tsv", [
            "cluster_id", "relative_offset", "word_offset", "source_u32_hex", "target_u32_hex",
            "source_float32", "target_float32", "float_status", "transition_id",
            "neutral_individual_transition_matches", "review_status",
        ], cluster_word_rows)
        write_tsv(output_dir / "G1E_CONTROL_CLUSTER_MATCHES.tsv", [
            "normalized_path", "member_key", "member_name", "control_scope", "cluster_id",
            "control_cluster_start", "common_cluster_start", "translation_delta", "cluster_signature_id", "review_status",
        ], cluster_match_rows)
        write_tsv(output_dir / "G1E_CONTROL_FULL_PROFILE_MATCHES.tsv", [
            "normalized_path", "member_key", "member_name", "control_scope", "translation_delta",
            "cluster_count", "changed_word_rows", "review_status",
        ], full_profile_rows)
        write_tsv(output_dir / "G1E_CONTROL_RECORD_SHAPE_SUMMARY.tsv", [
            "normalized_path", "member_key", "member_name", "control_scope", "source_size", "target_size",
            "classification", "changed_word_rows", "matched_cluster_count", "full_profile_match", "review_status",
        ], control_rows)
        write_tsv(output_dir / "G1E_RECORD_ENVELOPE_CANDIDATES.tsv", [
            "cluster_id", "field_offset", "relative_to_cluster_start", "source_u32_hex", "target_u32_hex",
            "source_float32", "target_float32", "changed_word", "field_class", "span_contains_cluster",
            "possible_length_bases", "review_status",
        ], envelope_rows)
        write_tsv(output_dir / "G1E_SEMANTIC_LEAF_CANDIDATES.tsv", [
            "cluster_id", "word_offset", "source_u32_hex", "target_u32_hex", "source_float32", "target_float32",
            "transition_id", "field_class", "neutral_individual_transition_matches",
            "neutral_complete_cluster_matches", "review_status",
        ], semantic_candidate_rows)
        write_tsv(output_dir / "G1E_TECHNICAL_HEADER_PROFILE.tsv", [
            "word_offset", "source_u32_hex", "target_u32_hex", "source_ascii4", "target_ascii4", "identical", "review_status",
        ], header_rows)
        write_tsv(output_dir / "G1E_RECORD_SHAPE_SKIPPED.tsv", [
            "scope", "normalized_path", "member_key", "side", "reason",
        ], skipped)

        summary = {
            "type": "br_quartet_restoration_reflector_ringlight_g1e_record_shape_evidence_summary",
            "format_version": 1,
            "tool_version": TOOL_VERSION,
            "source_stage81_tool_version": summary81.get("tool_version"),
            "source_stage80_tool_version": summary80.get("tool_version"),
            "source_stage79_tool_version": summary79.get("tool_version"),
            "status": status,
            "common_ringlight_member_rows": len(common_pairs),
            "common_ringlight_aligned_word_rows": len(canonical_delta),
            "common_ringlight_cluster_rows": len(clusters),
            "control_member_rows": len(control_rows),
            "identical_control_rows": sum(row.get("classification") == "identical_control" for row in control_rows),
            "same_size_changed_control_rows": sum(row.get("classification") == "same_size_changed_control" for row in control_rows),
            "size_or_structure_changed_control_rows": sum(row.get("classification") == "size_or_structure_changed_control" for row in control_rows),
            "complete_cluster_match_rows": len(cluster_match_rows),
            "neutral_complete_cluster_match_rows": sum(row.get("control_scope") == "neutral_non_transformation_name_control" for row in cluster_match_rows),
            "full_profile_match_rows": len(full_profile_rows),
            "neutral_full_profile_match_rows": len(neutral_full_profiles),
            "named_full_profile_match_rows": len(named_full_profiles),
            "record_envelope_candidate_rows": len(envelope_rows),
            "semantic_leaf_candidate_rows": len(semantic_candidate_rows),
            "header_profile_rows": len(header_rows),
            "brightness_semantics_confirmed": False,
            "prototype_candidate_rows": 0,
            "skipped_rows": len(skipped),
            "parameters": {
                "maximum_earc_bytes": maximum_earc_bytes,
                "cluster_gap_bytes": cluster_gap_bytes,
                "envelope_window_bytes": envelope_window_bytes,
                "control_scope": "all_other_G1E_G1EM_members_in_the_four_parent_containers",
                "cluster_match_definition": "ordered_source_target_dword_transitions_at_identical_relative_offsets",
                "full_profile_match_definition": "all_common_clusters_present_under_one_translation_delta",
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
            "next_action": next_action,
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
    parser.add_argument("--cluster-gap-bytes", type=int, default=CLUSTER_GAP_BYTES_DEFAULT)
    parser.add_argument("--envelope-window-bytes", type=int, default=ENVELOPE_WINDOW_BYTES_DEFAULT)
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
            cluster_gap_bytes=args.cluster_gap_bytes,
            envelope_window_bytes=args.envelope_window_bytes,
        )
        print(f"Report directory: {output}")
        print(
            f"Clusters: {summary['common_ringlight_cluster_rows']}; "
            f"neutral full-profile matches: {summary['neutral_full_profile_match_rows']}; "
            f"semantic leaf candidates: {summary['semantic_leaf_candidate_rows']}"
        )
        if archive:
            print(f"Report: {archive}")
        return 0
    except Stage82Error as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
