#!/usr/bin/env python3
"""Collect conservative inverse-delta evidence for opaque scene-effect members.

Stage 63 exhausted the remaining medium-or-higher cue-positive EBD subset queue.
This stage returns to the earlier render/effect evidence and analyzes only the
small scene-specific G1E/G1EM/OPL2/BIN members that stage 8 already marked for
controlled probing.  It reconstructs source bytes only in memory, exports
metadata and hashes, and never writes a candidate payload, PAK, registry entry,
activation state or installed-game file.
"""

from __future__ import annotations

import argparse
import csv
import difflib
import hashlib
import itertools
import json
import os
import shutil
import subprocess
import sys
import tempfile
from collections import Counter
from pathlib import Path, PurePosixPath
from typing import Any, Callable, Iterable, Mapping, Sequence

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT_DEFAULT = SCRIPT_DIR.parent.parent
TEXT_TOOL_DIR = PROJECT_ROOT_DEFAULT / "Blue_Reflection_Text_Tool"
if str(TEXT_TOOL_DIR) not in sys.path:
    sys.path.insert(0, str(TEXT_TOOL_DIR))

import br_restoration_tool as BR  # noqa: E402

TOOL_VERSION = "0.0.73"
REPORT_NAME = "BR_quartet_restoration_opaque_scene_effect_member_evidence.tar.zst"
EVIDENCE_DIR_NAME = "opaque_scene_effect_member_evidence"

EXPECTED_PROFILE_ROWS = 14
EXPECTED_PACK11_ROWS = 12
EXPECTED_PACK10_ROWS = 2

ALLOWED_PROTOTYPE_ACTIONS = {
    "controlled_scene_or_wet_effect_member_probe",
    "controlled_scene_descriptor_probe",
}
ALLOWED_EXTENSIONS = {".g1e", ".g1em", ".opl2", ".bin"}
ALLOWED_PRIORITIES = {"critical", "high"}
GLOBAL_OR_REMATER_TOKENS = (
    "pe_pack",
    "posteffect",
    "post_effect",
    "unsharpmask",
)

REPORT_SPECS = {
    "core": (
        "core_profile_manifest_evidence",
        "BR_quartet_restoration_core_profile_manifest_evidence.tar.zst",
    ),
    "stage63": (
        "remaining_cue_positive_backlog_evidence",
        "BR_quartet_restoration_remaining_cue_positive_backlog_evidence.tar.zst",
    ),
    "shader": (
        "shader_effect_evidence",
        "BR_quartet_restoration_shader_effect_evidence.tar.zst",
    ),
    "binary": (
        "binary_delta_evidence",
        "BR_quartet_restoration_binary_delta_evidence.tar.zst",
    ),
}


class OpaqueEffectError(RuntimeError):
    pass


def parse_bool(value: object) -> bool:
    return str(value).strip().casefold() in {"1", "true", "yes", "y"}


def parse_int(value: object, default: int = 0) -> int:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return default


def parse_float(value: object, default: float = 0.0) -> float:
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        return default


def safe_member_name(raw: str) -> str:
    path = PurePosixPath(raw)
    if path.is_absolute() or not path.parts or ".." in path.parts:
        raise OpaqueEffectError(f"unsafe report archive member: {raw}")
    return path.as_posix()


def read_tsv(path: Path, *, required: bool = True) -> list[dict[str, str]]:
    if not path.is_file():
        if required:
            raise OpaqueEffectError(f"missing prerequisite table: {path}")
        return []
    with path.open("r", encoding="utf-8", newline="") as handle:
        return [dict(row) for row in csv.DictReader(handle, delimiter="\t")]


def write_tsv(path: Path, fieldnames: Sequence[str], rows: Iterable[Mapping[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fieldnames})


def load_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise OpaqueEffectError(f"missing prerequisite JSON: {path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise OpaqueEffectError(f"invalid JSON {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise OpaqueEffectError(f"expected JSON object: {path}")
    return value


def atomic_json(path: Path, value: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def extract_archive(archive: Path, destination: Path) -> Path:
    if not archive.is_file():
        raise OpaqueEffectError(f"missing prerequisite report archive: {archive}")
    listed = subprocess.run(
        ["tar", "--zstd", "-tf", str(archive)],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if listed.returncode != 0:
        raise OpaqueEffectError(f"cannot list {archive}: {listed.stderr.strip()}")
    roots: set[str] = set()
    for raw in listed.stdout.splitlines():
        if raw.strip():
            roots.add(PurePosixPath(safe_member_name(raw.strip())).parts[0])
    if len(roots) != 1:
        raise OpaqueEffectError(f"expected one report root in {archive}, found {sorted(roots)}")
    destination.mkdir(parents=True, exist_ok=True)
    completed = subprocess.run(
        ["tar", "--zstd", "-xf", str(archive), "-C", str(destination)],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if completed.returncode != 0:
        raise OpaqueEffectError(f"cannot extract {archive}: {completed.stderr.strip()}")
    return destination / next(iter(roots))


def locate_report_root(report_root: Path, key: str, temporary: Path) -> Path:
    directory_name, archive_name = REPORT_SPECS[key]
    direct = report_root / directory_name
    if direct.is_dir():
        return direct
    return extract_archive(report_root / archive_name, temporary / key)


def make_report_archive(source_dir: Path, output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(output.name + ".tmp")
    if temporary.exists():
        temporary.unlink()
    completed = subprocess.run(
        ["tar", "--zstd", "-cf", str(temporary), "-C", str(source_dir.parent), source_dir.name],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if completed.returncode != 0:
        raise OpaqueEffectError(f"cannot create report archive: {completed.stderr.strip()}")
    os.replace(temporary, output)


def validate_core_report(root: Path) -> dict[str, Any]:
    summary = load_json(root / "SUMMARY.json")
    if summary.get("type") != "br_quartet_restoration_core_profile_manifest_evidence_summary":
        raise OpaqueEffectError("core report has an unexpected summary type")
    if summary.get("tool_version") != "0.0.71":
        raise OpaqueEffectError("core report must be the stage-62 registry replacement report")
    if summary.get("status") != "all_current_local_profiles_registered_runtime_unvalidated":
        raise OpaqueEffectError("core report is not in the clean runtime-unvalidated state")
    if parse_int(summary.get("profile_rows"), -1) != EXPECTED_PROFILE_ROWS:
        raise OpaqueEffectError("core report must contain 14 profiles")
    if parse_int(summary.get("pack11_profile_rows"), -1) != EXPECTED_PACK11_ROWS:
        raise OpaqueEffectError("core report must contain 12 PACK11 profiles")
    if parse_int(summary.get("pack10_01_profile_rows"), -1) != EXPECTED_PACK10_ROWS:
        raise OpaqueEffectError("core report must contain 2 PACK10_01 profiles")
    if parse_int(summary.get("runtime_validated_profile_rows"), -1) != 0:
        raise OpaqueEffectError("core report contains a runtime-validated profile")
    rows = read_tsv(root / "CORE_PROFILE_MANIFESTS.tsv")
    if len(rows) != EXPECTED_PROFILE_ROWS:
        raise OpaqueEffectError("core manifest table must contain 14 rows")
    if any(parse_bool(row.get("runtime_validated")) for row in rows):
        raise OpaqueEffectError("core manifest table contains a runtime-validated profile")
    if any(str(row.get("validation_status", "")) != "passed" for row in rows):
        raise OpaqueEffectError("core manifest table contains a failed profile")
    return summary


def validate_stage63_report(root: Path) -> dict[str, Any]:
    summary = load_json(root / "SUMMARY.json")
    if summary.get("type") != "br_quartet_restoration_remaining_cue_positive_backlog_evidence_summary":
        raise OpaqueEffectError("stage-63 report has an unexpected summary type")
    if summary.get("tool_version") != "0.0.72":
        raise OpaqueEffectError("stage-63 report must use tool version 0.0.72")
    if parse_int(summary.get("registry_profile_rows"), -1) != EXPECTED_PROFILE_ROWS:
        raise OpaqueEffectError("stage-63 report did not use the 14-profile registry")
    if parse_int(summary.get("candidate_backlog_rows"), -1) != 0:
        raise OpaqueEffectError("stage-63 report still contains an unanalyzed EBD candidate backlog")
    if parse_int(summary.get("promotable_event_rows"), -1) != 0:
        raise OpaqueEffectError("stage-63 report contains a promotable EBD candidate")
    policy = summary.get("policy") or {}
    if not isinstance(policy, dict):
        raise OpaqueEffectError("stage-63 policy is malformed")
    forbidden_true = (
        "installed_games_modified",
        "candidate_ebd_payloads_written",
        "pak_repack_performed",
        "core_registry_modified",
        "activation_or_rollback_invoked",
    )
    if any(parse_bool(policy.get(key)) for key in forbidden_true):
        raise OpaqueEffectError("stage-63 report performed a forbidden write")
    return summary


def validate_shader_report(root: Path) -> dict[str, Any]:
    summary = load_json(root / "SUMMARY.json")
    if summary.get("type") != "br_quartet_restoration_shader_effect_evidence_summary":
        raise OpaqueEffectError("shader/effect report has an unexpected summary type")
    if summary.get("status") != "focused_shader_effect_posteffect_evidence_complete_manual_confirmation_required":
        raise OpaqueEffectError("shader/effect report is not complete")
    if parse_int(summary.get("skipped_rows"), -1) != 0:
        raise OpaqueEffectError("shader/effect report contains skipped rows")
    return summary


def validate_binary_report(root: Path) -> dict[str, Any]:
    summary = load_json(root / "SUMMARY.json")
    if summary.get("type") != "br_quartet_restoration_binary_delta_evidence_summary":
        raise OpaqueEffectError("binary-delta report has an unexpected summary type")
    if summary.get("status") != "focused_binary_and_DXBC_chunk_delta_complete_controlled_prototypes_not_generated":
        raise OpaqueEffectError("binary-delta report is not complete")
    if parse_int(summary.get("skipped_rows"), -1) != 0:
        raise OpaqueEffectError("binary-delta report contains skipped rows")
    return summary


def row_key(row: Mapping[str, object]) -> tuple[str, str, str, str, str]:
    return (
        str(row.get("candidate_id", "")),
        str(row.get("normalized_path", "")),
        str(row.get("member_key", "")),
        str(row.get("source_member_name", "")),
        str(row.get("target_member_name", "")),
    )


def pair_key(row: Mapping[str, object]) -> tuple[str, str, str, str, str]:
    return row_key(row)


def hamming_distance(left: bytes, right: bytes) -> int:
    if len(left) != len(right):
        raise OpaqueEffectError("hamming distance requires equal payload sizes")
    return sum(a != b for a, b in zip(left, right))


def operation_shape_id(
    *, extension: str, source_span: bytes, target_span: bytes,
    before_context: bytes, after_context: bytes,
) -> str:
    digest = hashlib.sha256()
    digest.update(extension.encode("utf-8"))
    digest.update(len(source_span).to_bytes(8, "little"))
    digest.update(hashlib.sha256(source_span).digest())
    digest.update(hashlib.sha256(target_span).digest())
    digest.update(hashlib.sha256(before_context).digest())
    digest.update(hashlib.sha256(after_context).digest())
    return digest.hexdigest()


def build_operations(
    *, source: bytes, target: bytes, extension: str,
    context_bytes: int, header_guard_bytes: int, tail_guard_bytes: int,
    maximum_operation_bytes: int,
) -> list[dict[str, Any]]:
    matcher = difflib.SequenceMatcher(None, source, target, autojunk=False)
    operations: list[dict[str, Any]] = []
    ordinal = 0
    for tag, source_start, source_end, target_start, target_end in matcher.get_opcodes():
        if tag == "equal":
            continue
        source_span = source[source_start:source_end]
        target_span = target[target_start:target_end]
        before = target[max(0, target_start - context_bytes):target_start]
        after = target[target_end:min(len(target), target_end + context_bytes)]
        reasons: list[str] = []
        if tag != "replace":
            reasons.append(f"sequence_opcode_{tag}_not_equal_size_replace")
        if len(source_span) != len(target_span):
            reasons.append("source_target_span_size_mismatch")
        if not source_span or not target_span:
            reasons.append("empty_source_or_target_span")
        if target_start < header_guard_bytes:
            reasons.append("touches_guarded_header")
        if target_end > len(target) - tail_guard_bytes:
            reasons.append("touches_guarded_tail")
        if target_start % 4 or target_end % 4 or len(target_span) % 4:
            reasons.append("not_32bit_aligned")
        if len(target_span) > maximum_operation_bytes:
            reasons.append("operation_exceeds_size_limit")
        shape_id = operation_shape_id(
            extension=extension,
            source_span=source_span,
            target_span=target_span,
            before_context=before,
            after_context=after,
        )
        operations.append({
            "operation_index": ordinal,
            "sequence_opcode": tag,
            "source_start": source_start,
            "source_end": source_end,
            "target_start": target_start,
            "target_end": target_end,
            "source_span_size": len(source_span),
            "target_span_size": len(target_span),
            "source_span_sha256": hashlib.sha256(source_span).hexdigest(),
            "target_span_sha256": hashlib.sha256(target_span).hexdigest(),
            "before_context_sha256": hashlib.sha256(before).hexdigest(),
            "after_context_sha256": hashlib.sha256(after).hexdigest(),
            "shape_id": shape_id,
            "base_eligible": not reasons,
            "base_exclusion_reasons": ";".join(reasons),
            "source_span": source_span,
            "target_span": target_span,
        })
        ordinal += 1
    return operations


def apply_operations(target: bytes, operations: Sequence[Mapping[str, Any]]) -> bytes:
    candidate = bytearray(target)
    for row in operations:
        start = int(row["target_start"])
        end = int(row["target_end"])
        source_span = bytes(row["source_span"])
        if end - start != len(source_span):
            raise OpaqueEffectError("operation is not size-preserving")
        candidate[start:end] = source_span
    return bytes(candidate)


def reverse_operations(candidate: bytes, operations: Sequence[Mapping[str, Any]]) -> bytes:
    target = bytearray(candidate)
    for row in operations:
        start = int(row["target_start"])
        end = int(row["target_end"])
        target_span = bytes(row["target_span"])
        if end - start != len(target_span):
            raise OpaqueEffectError("reverse operation is not size-preserving")
        target[start:end] = target_span
    return bytes(target)


def candidate_rows_from_reports(
    binary_root: Path,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    prototype_rows = read_tsv(binary_root / "RESTORATION_PROTOTYPE_CANDIDATES.tsv")
    payload_rows = read_tsv(binary_root / "PAYLOAD_BINARY_DELTA.tsv")
    payload_by_key = {row_key(row): row for row in payload_rows}
    selected: list[dict[str, Any]] = []
    exclusions: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str, str, str]] = set()
    for prototype in prototype_rows:
        key = row_key(prototype)
        if key in seen:
            continue
        seen.add(key)
        payload = payload_by_key.get(key)
        reason = ""
        extension = str(prototype.get("extension", "")).casefold()
        priority = str(prototype.get("priority", ""))
        action = str(prototype.get("prototype_action", ""))
        joined_name = "|".join(str(prototype.get(field, "")) for field in (
            "normalized_path", "source_member_name", "target_member_name",
        )).casefold()
        if action not in ALLOWED_PROTOTYPE_ACTIONS:
            reason = "prototype_action_not_scene_specific_opaque_probe"
        elif extension not in ALLOWED_EXTENSIONS:
            reason = "extension_not_in_opaque_scene_effect_scope"
        elif priority not in ALLOWED_PRIORITIES:
            reason = "priority_below_high"
        elif any(token in joined_name for token in GLOBAL_OR_REMATER_TOKENS):
            reason = "global_or_remaster_confounded_member"
        elif payload is None:
            reason = "matching_payload_binary_delta_row_missing"
        elif str(payload.get("classification", "")) != "changed":
            reason = "payload_not_changed_on_both_sides"
        elif parse_int(payload.get("delta_cluster_size"), 0) >= 8:
            reason = "broad_or_recurrent_delta_cluster"
        elif not str(prototype.get("source_member_name", "")) or not str(prototype.get("target_member_name", "")):
            reason = "source_or_target_member_missing"
        else:
            density = parse_float(payload.get("changed_density"), 1.0)
            limit = 0.05 if extension in {".opl2", ".bin"} else 0.10
            if density > limit:
                reason = "changed_density_above_conservative_limit"
        if reason:
            exclusions.append({**prototype, "exclusion_reason": reason})
            continue
        selected.append({**prototype, **{
            "classification": payload.get("classification", ""),
            "source_size": payload.get("source_size", ""),
            "target_size": payload.get("target_size", ""),
            "changed_density": payload.get("changed_density", ""),
            "changed_range_count": payload.get("changed_range_count", ""),
            "delta_cluster_id": payload.get("delta_cluster_id", ""),
            "delta_cluster_size": payload.get("delta_cluster_size", ""),
        }})
    return selected, exclusions


def collect(
    *, project_root: Path, workspace_root: Path, report_root: Path,
    effect_rules_file: Path | None = None,
    maximum_earc_bytes: int = 512 * 1024 * 1024,
    maximum_payload_bytes: int = 8 * 1024 * 1024,
    maximum_operation_bytes: int = 4096,
    maximum_operations_per_member: int = 12,
    maximum_combinations_per_member: int = 4095,
    recurrent_shape_threshold: int = 8,
    context_bytes: int = 16,
    header_guard_bytes: int = 16,
    tail_guard_bytes: int = 16,
    pair_loader: Callable[..., tuple[list[dict[str, Any]], list[dict[str, Any]]]] | None = None,
) -> tuple[Path, dict[str, Any]]:
    if maximum_operations_per_member < 1 or maximum_operations_per_member > 20:
        raise OpaqueEffectError("maximum_operations_per_member must be between 1 and 20")
    if maximum_combinations_per_member < 1:
        raise OpaqueEffectError("maximum_combinations_per_member must be positive")
    if recurrent_shape_threshold < 2:
        raise OpaqueEffectError("recurrent_shape_threshold must be at least 2")
    if maximum_payload_bytes < 1 or maximum_operation_bytes < 1:
        raise OpaqueEffectError("payload and operation size limits must be positive")

    with tempfile.TemporaryDirectory(prefix="br-stage64-") as temporary_name:
        temporary = Path(temporary_name)
        roots = {key: locate_report_root(report_root, key, temporary) for key in REPORT_SPECS}
        core_summary = validate_core_report(roots["core"])
        stage63_summary = validate_stage63_report(roots["stage63"])
        shader_summary = validate_shader_report(roots["shader"])
        binary_summary = validate_binary_report(roots["binary"])

        selected_rows, exclusion_rows = candidate_rows_from_reports(roots["binary"])
        payload_metadata_rows = read_tsv(roots["shader"] / "RENDER_PAYLOADS.tsv")
        payload_metadata: dict[tuple[str, str, str, str], dict[str, str]] = {}
        for row in payload_metadata_rows:
            key = (
                str(row.get("candidate_id", "")),
                str(row.get("normalized_path", "")),
                str(row.get("member_key", "")),
                str(row.get("side", "")),
            )
            if key in payload_metadata:
                raise OpaqueEffectError(f"duplicate shader payload metadata row: {key}")
            payload_metadata[key] = row

        rules_file = effect_rules_file or (
            project_root / "titles/blue_reflection/modules/quartet_restoration/mappings/effect_material_rules.tsv"
        )
        loader = pair_loader or BR.load_focused_render_pairs
        pairs, loader_skipped = loader(
            workspace_root=workspace_root,
            report_root=report_root,
            rules_file=rules_file,
            maximum_earc_bytes=maximum_earc_bytes,
        )
        if loader_skipped:
            raise OpaqueEffectError(f"focused render pair loader skipped {len(loader_skipped)} rows")
        pair_by_key = {pair_key(row): row for row in pairs}

        candidate_work: list[dict[str, Any]] = []
        skipped_rows: list[dict[str, Any]] = []
        all_operations: list[dict[str, Any]] = []
        for selected in selected_rows:
            key = row_key(selected)
            pair = pair_by_key.get(key)
            if pair is None:
                skipped_rows.append({**selected, "reason": "rehydrated_render_pair_missing"})
                continue
            source = pair.get("source_payload")
            target = pair.get("target_payload")
            if not isinstance(source, (bytes, bytearray)) or not isinstance(target, (bytes, bytearray)):
                skipped_rows.append({**selected, "reason": "source_or_target_payload_missing"})
                continue
            source = bytes(source)
            target = bytes(target)
            if len(source) > maximum_payload_bytes or len(target) > maximum_payload_bytes:
                skipped_rows.append({**selected, "reason": "payload_exceeds_stage64_limit"})
                continue
            for side, payload in (("source", source), ("target", target)):
                metadata = payload_metadata.get((key[0], key[1], key[2], side))
                if metadata is None:
                    raise OpaqueEffectError(f"missing shader payload metadata for {key[:3]} side={side}")
                if parse_int(metadata.get("payload_size"), -1) != len(payload):
                    raise OpaqueEffectError(f"payload size mismatch for {key[:3]} side={side}")
                if str(metadata.get("payload_sha256", "")) != hashlib.sha256(payload).hexdigest():
                    raise OpaqueEffectError(f"payload hash mismatch for {key[:3]} side={side}")
            if len(source) != len(target):
                skipped_rows.append({**selected, "reason": "source_target_payload_size_mismatch"})
                continue
            if source == target:
                skipped_rows.append({**selected, "reason": "rehydrated_payloads_are_identical"})
                continue
            operations = build_operations(
                source=source,
                target=target,
                extension=str(selected.get("extension", "")),
                context_bytes=context_bytes,
                header_guard_bytes=header_guard_bytes,
                tail_guard_bytes=tail_guard_bytes,
                maximum_operation_bytes=maximum_operation_bytes,
            )
            if not operations:
                skipped_rows.append({**selected, "reason": "no_nonidentical_sequence_operations"})
                continue
            candidate_index = len(candidate_work)
            for operation in operations:
                operation["candidate_index"] = candidate_index
                operation["candidate_id"] = key[0]
                operation["normalized_path"] = key[1]
                operation["member_key"] = key[2]
                operation["source_member_name"] = key[3]
                operation["target_member_name"] = key[4]
                all_operations.append(operation)
            candidate_work.append({
                "selected": selected,
                "source": source,
                "target": target,
                "operations": operations,
            })

        shape_counts = Counter(str(row["shape_id"]) for row in all_operations)
        operation_rows: list[dict[str, Any]] = []
        combination_rows: list[dict[str, Any]] = []
        member_rows: list[dict[str, Any]] = []
        for work in candidate_work:
            selected = work["selected"]
            source = work["source"]
            target = work["target"]
            operations = work["operations"]
            eligible: list[dict[str, Any]] = []
            for operation in operations:
                recurrent = shape_counts[str(operation["shape_id"])] >= recurrent_shape_threshold
                reasons = [part for part in str(operation["base_exclusion_reasons"]).split(";") if part]
                if recurrent:
                    reasons.append("recurrent_operation_shape")
                operation["shape_occurrence_count"] = shape_counts[str(operation["shape_id"])]
                operation["eligible"] = bool(operation["base_eligible"]) and not recurrent
                operation["exclusion_reasons"] = ";".join(reasons)
                if operation["eligible"]:
                    eligible.append(operation)
                operation_rows.append({
                    **{field: selected.get(field, "") for field in (
                        "candidate_id", "rule_id", "domain", "priority", "evidence_kind",
                        "normalized_path", "member_key", "source_member_name", "target_member_name", "extension",
                    )},
                    **{field: operation.get(field, "") for field in (
                        "operation_index", "sequence_opcode", "source_start", "source_end", "target_start", "target_end",
                        "source_span_size", "target_span_size", "source_span_sha256", "target_span_sha256",
                        "before_context_sha256", "after_context_sha256", "shape_id", "shape_occurrence_count",
                        "eligible", "exclusion_reasons",
                    )},
                    "review_status": "opaque_binary_range_metadata_only_no_field_semantics",
                })

            target_distance = hamming_distance(source, target)
            member_combinations: list[dict[str, Any]] = []
            if 0 < len(eligible) <= maximum_operations_per_member:
                possible = (1 << len(eligible)) - 1
                if possible <= maximum_combinations_per_member:
                    for count in range(1, len(eligible) + 1):
                        for chosen in itertools.combinations(eligible, count):
                            candidate = apply_operations(target, chosen)
                            reversed_target = reverse_operations(candidate, chosen)
                            distance = hamming_distance(source, candidate)
                            improvement = target_distance - distance
                            prefix_preserved = candidate[:header_guard_bytes] == target[:header_guard_bytes]
                            suffix_preserved = (
                                candidate[len(candidate) - tail_guard_bytes:] == target[len(target) - tail_guard_bytes:]
                                if tail_guard_bytes else True
                            )
                            exact_reverse = reversed_target == target
                            selected_indices = ";".join(str(row["operation_index"]) for row in chosen)
                            subset_id = hashlib.sha256(
                                (row_key(selected)[0] + "|" + row_key(selected)[1] + "|" + row_key(selected)[2] + "|" + selected_indices).encode("utf-8")
                            ).hexdigest()[:16]
                            passes = (
                                len(candidate) == len(target)
                                and prefix_preserved
                                and suffix_preserved
                                and exact_reverse
                                and improvement > 0
                            )
                            row = {
                                **{field: selected.get(field, "") for field in (
                                    "candidate_id", "rule_id", "domain", "priority", "evidence_kind",
                                    "normalized_path", "member_key", "source_member_name", "target_member_name", "extension",
                                )},
                                "subset_id": subset_id,
                                "selected_operation_indices": selected_indices,
                                "selected_operation_count": len(chosen),
                                "selected_shape_count": len({str(item["shape_id"]) for item in chosen}),
                                "selected_shape_ids": ";".join(sorted({str(item["shape_id"]) for item in chosen})),
                                "candidate_sha256": hashlib.sha256(candidate).hexdigest(),
                                "candidate_size": len(candidate),
                                "target_distance_to_source": target_distance,
                                "candidate_distance_to_source": distance,
                                "distance_improvement": improvement,
                                "exact_original": candidate == source,
                                "guarded_header_preserved": prefix_preserved,
                                "guarded_tail_preserved": suffix_preserved,
                                "exact_target_reverse_roundtrip": exact_reverse,
                                "passes_all_static_gates": passes,
                                "review_status": "opaque_inverse_combination_metadata_only_runtime_required",
                            }
                            member_combinations.append(row)
                            combination_rows.append(row)
            passing = [row for row in member_combinations if parse_bool(row["passes_all_static_gates"])]
            best = min(
                passing,
                key=lambda row: (
                    parse_int(row["candidate_distance_to_source"], 1 << 60),
                    parse_int(row["selected_operation_count"], 1 << 30),
                    str(row["subset_id"]),
                ),
                default=None,
            )
            all_operations_eligible = bool(operations) and len(eligible) == len(operations)
            exact_original_ready = bool(best and parse_bool(best["exact_original"]) and all_operations_eligible)
            if exact_original_ready:
                classification = "opaque_scene_effect_exact_original_candidate_ready_for_local_prototype"
                next_gate = "build_one_isolated_local_member_prototype_then_repack_its_own_parent_archive"
            elif best:
                classification = "opaque_scene_effect_partial_inverse_evidence_only"
                next_gate = "retain_metadata_and_decode_or_isolate_excluded_ranges_before_payload_build"
            else:
                classification = "opaque_scene_effect_member_not_promotable_by_conservative_inverse_ranges"
                next_gate = "retain_as_evidence_only"
            member_rows.append({
                **{field: selected.get(field, "") for field in (
                    "candidate_id", "rule_id", "domain", "priority", "evidence_kind",
                    "normalized_path", "member_key", "source_member_name", "target_member_name", "extension",
                    "prototype_action", "risk", "delta_cluster_id", "delta_cluster_size", "changed_density",
                )},
                "source_size": len(source),
                "target_size": len(target),
                "target_distance_to_source": target_distance,
                "operation_count": len(operations),
                "eligible_operation_count": len(eligible),
                "excluded_operation_count": len(operations) - len(eligible),
                "combination_count_tested": len(member_combinations),
                "passing_combination_count": len(passing),
                "best_subset_id": (best or {}).get("subset_id", ""),
                "best_selected_operation_count": (best or {}).get("selected_operation_count", ""),
                "best_selected_shape_ids": (best or {}).get("selected_shape_ids", ""),
                "best_candidate_sha256": (best or {}).get("candidate_sha256", ""),
                "best_candidate_distance_to_source": (best or {}).get("candidate_distance_to_source", ""),
                "best_distance_improvement": (best or {}).get("distance_improvement", ""),
                "best_exact_original": (best or {}).get("exact_original", False),
                "all_operations_eligible": all_operations_eligible,
                "classification": classification,
                "safe_to_build_local_prototype_without_runtime": exact_original_ready,
                "runtime_test_deferred": True,
                "next_gate": next_gate,
            })

        evidence_root = report_root / EVIDENCE_DIR_NAME
        if evidence_root.exists():
            shutil.rmtree(evidence_root)
        evidence_root.mkdir(parents=True, exist_ok=True)

        member_fields = [
            "candidate_id", "rule_id", "domain", "priority", "evidence_kind", "normalized_path", "member_key",
            "source_member_name", "target_member_name", "extension", "prototype_action", "risk", "delta_cluster_id",
            "delta_cluster_size", "changed_density", "source_size", "target_size", "target_distance_to_source",
            "operation_count", "eligible_operation_count", "excluded_operation_count", "combination_count_tested",
            "passing_combination_count", "best_subset_id", "best_selected_operation_count", "best_selected_shape_ids",
            "best_candidate_sha256", "best_candidate_distance_to_source", "best_distance_improvement",
            "best_exact_original", "all_operations_eligible", "classification",
            "safe_to_build_local_prototype_without_runtime", "runtime_test_deferred", "next_gate",
        ]
        operation_fields = [
            "candidate_id", "rule_id", "domain", "priority", "evidence_kind", "normalized_path", "member_key",
            "source_member_name", "target_member_name", "extension", "operation_index", "sequence_opcode",
            "source_start", "source_end", "target_start", "target_end", "source_span_size", "target_span_size",
            "source_span_sha256", "target_span_sha256", "before_context_sha256", "after_context_sha256",
            "shape_id", "shape_occurrence_count", "eligible", "exclusion_reasons", "review_status",
        ]
        combination_fields = [
            "candidate_id", "rule_id", "domain", "priority", "evidence_kind", "normalized_path", "member_key",
            "source_member_name", "target_member_name", "extension", "subset_id", "selected_operation_indices",
            "selected_operation_count", "selected_shape_count", "selected_shape_ids", "candidate_sha256",
            "candidate_size", "target_distance_to_source", "candidate_distance_to_source", "distance_improvement",
            "exact_original", "guarded_header_preserved", "guarded_tail_preserved",
            "exact_target_reverse_roundtrip", "passes_all_static_gates", "review_status",
        ]
        exclusion_fields = [
            "candidate_id", "rule_id", "domain", "priority", "evidence_kind", "normalized_path", "member_key",
            "source_member_name", "target_member_name", "extension", "prototype_action", "risk", "exclusion_reason",
        ]
        skipped_fields = exclusion_fields[:-1] + ["reason"]
        write_tsv(evidence_root / "OPAQUE_SCENE_EFFECT_MEMBERS.tsv", member_fields, member_rows)
        write_tsv(evidence_root / "OPAQUE_SCENE_EFFECT_OPERATIONS.tsv", operation_fields, operation_rows)
        write_tsv(evidence_root / "OPAQUE_SCENE_EFFECT_COMBINATIONS.tsv", combination_fields, combination_rows)
        write_tsv(evidence_root / "OPAQUE_SCENE_EFFECT_CANDIDATE_EXCLUSIONS.tsv", exclusion_fields, exclusion_rows)
        write_tsv(evidence_root / "OPAQUE_SCENE_EFFECT_SKIPPED.tsv", skipped_fields, skipped_rows)

        promotable = [row for row in member_rows if parse_bool(row.get("safe_to_build_local_prototype_without_runtime"))]
        partial = [row for row in member_rows if row.get("classification") == "opaque_scene_effect_partial_inverse_evidence_only"]
        summary = {
            "type": "br_quartet_restoration_opaque_scene_effect_member_evidence_summary",
            "format_version": 1,
            "tool_version": TOOL_VERSION,
            "source_core_tool_version": core_summary.get("tool_version"),
            "source_stage63_tool_version": stage63_summary.get("tool_version"),
            "source_shader_effect_tool_version": shader_summary.get("tool_version"),
            "source_binary_delta_tool_version": binary_summary.get("tool_version"),
            "status": "opaque_scene_effect_member_inverse_range_audit_complete_no_payload_written_runtime_deferred",
            "registry_profile_rows": EXPECTED_PROFILE_ROWS,
            "stage63_remaining_ebd_candidate_rows": parse_int(stage63_summary.get("candidate_backlog_rows")),
            "stage8_scene_specific_probe_rows_selected": len(selected_rows),
            "rehydrated_member_rows": len(candidate_work),
            "analyzed_member_rows": len(member_rows),
            "promotable_exact_original_member_rows": len(promotable),
            "partial_inverse_evidence_member_rows": len(partial),
            "operation_rows": len(operation_rows),
            "eligible_operation_rows": sum(parse_bool(row.get("eligible")) for row in operation_rows),
            "combination_rows": len(combination_rows),
            "passing_combination_rows": sum(parse_bool(row.get("passes_all_static_gates")) for row in combination_rows),
            "candidate_exclusion_rows": len(exclusion_rows),
            "skipped_rows": len(skipped_rows),
            "parameters": {
                "maximum_earc_bytes": maximum_earc_bytes,
                "maximum_payload_bytes": maximum_payload_bytes,
                "maximum_operation_bytes": maximum_operation_bytes,
                "maximum_operations_per_member": maximum_operations_per_member,
                "maximum_combinations_per_member": maximum_combinations_per_member,
                "recurrent_shape_threshold": recurrent_shape_threshold,
                "context_bytes": context_bytes,
                "header_guard_bytes": header_guard_bytes,
                "tail_guard_bytes": tail_guard_bytes,
            },
            "policy": {
                "installed_games_modified": False,
                "candidate_effect_payloads_written": False,
                "parent_archive_repack_performed": False,
                "core_registry_modified": False,
                "activation_or_rollback_invoked": False,
                "runtime_validation_inferred": False,
                "censorship_classification_inferred": False,
                "opaque_binary_field_semantics_inferred": False,
                "global_posteffect_pack_selected": False,
                "direct_shader_profiles_rebuilt": False,
                "only_stage8_scene_specific_probe_rows_considered": True,
                "same_size_32bit_aligned_guarded_replace_operations_required": True,
                "broad_or_recurrent_operation_shapes_selected": False,
                "exact_target_reverse_roundtrip_required": True,
                "strict_original_distance_improvement_required": True,
                "exact_original_required_for_local_prototype_promotion": True,
                "translation_or_dlc_workstreams_modified": False,
            },
            "next_action": (
                "Upload this report. Build isolated local member prototypes only for rows marked "
                "opaque_scene_effect_exact_original_candidate_ready_for_local_prototype. If none promote, "
                "retain the report and move to focused wet/coverage material-variant analysis or the deferred debug-event-checker track."
            ),
        }
        atomic_json(evidence_root / "SUMMARY.json", summary)
        output = report_root / REPORT_NAME
        make_report_archive(evidence_root, output)
        return output, summary


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", required=True)
    parser.add_argument("--workspace-root")
    parser.add_argument("--report-root")
    parser.add_argument("--effect-rules-file")
    parser.add_argument("--maximum-earc-bytes", type=int, default=512 * 1024 * 1024)
    parser.add_argument("--maximum-payload-bytes", type=int, default=8 * 1024 * 1024)
    parser.add_argument("--maximum-operation-bytes", type=int, default=4096)
    parser.add_argument("--maximum-operations-per-member", type=int, default=12)
    parser.add_argument("--maximum-combinations-per-member", type=int, default=4095)
    parser.add_argument("--recurrent-shape-threshold", type=int, default=8)
    parser.add_argument("--context-bytes", type=int, default=16)
    parser.add_argument("--header-guard-bytes", type=int, default=16)
    parser.add_argument("--tail-guard-bytes", type=int, default=16)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    project_root = Path(args.project_root).expanduser().resolve()
    if not project_root.is_dir():
        raise OpaqueEffectError(f"project root does not exist: {project_root}")
    default_workspace = project_root / ".local/build/quartet_restoration"
    default_reports = project_root / ".local/reports/quartet_restoration"
    workspace_root = Path(args.workspace_root).expanduser().resolve() if args.workspace_root else default_workspace
    report_root = Path(args.report_root).expanduser().resolve() if args.report_root else default_reports
    rules_file = Path(args.effect_rules_file).expanduser().resolve() if args.effect_rules_file else None
    output, summary = collect(
        project_root=project_root,
        workspace_root=workspace_root,
        report_root=report_root,
        effect_rules_file=rules_file,
        maximum_earc_bytes=args.maximum_earc_bytes,
        maximum_payload_bytes=args.maximum_payload_bytes,
        maximum_operation_bytes=args.maximum_operation_bytes,
        maximum_operations_per_member=args.maximum_operations_per_member,
        maximum_combinations_per_member=args.maximum_combinations_per_member,
        recurrent_shape_threshold=args.recurrent_shape_threshold,
        context_bytes=args.context_bytes,
        header_guard_bytes=args.header_guard_bytes,
        tail_guard_bytes=args.tail_guard_bytes,
    )
    print(f"Report: {output}")
    print(f"Analyzed opaque members: {summary['analyzed_member_rows']}")
    print(f"Promotable exact-Original members: {summary['promotable_exact_original_member_rows']}")
    print(f"Partial inverse evidence members: {summary['partial_inverse_evidence_member_rows']}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OpaqueEffectError, BR.RestorationError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
