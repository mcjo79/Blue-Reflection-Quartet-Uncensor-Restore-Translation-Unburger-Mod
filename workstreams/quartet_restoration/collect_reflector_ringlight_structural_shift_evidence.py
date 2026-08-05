#!/usr/bin/env python3
"""Test whether the uniform common-ringlight delta is a record-layout shift.

Stage 82 isolated three complete change clusters from every sibling G1E/G1EM
control.  Their word pattern nevertheless resembles an eight-byte record
compaction: several envelope lengths shrink by eight, a two-dword zero gap is
removed, following values move left, relative offsets increase by eight, and
the vacated tail is zero-filled.  This stage tests that model explicitly on all
15 ``e_cmn_ringlight_PCxx.g1e`` pairs and emits metadata only.  Any changed
word not explained by one uniform structural model remains a semantic residual
and blocks closure of the common family.
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
from collections import Counter, defaultdict
from pathlib import Path, PurePosixPath
from typing import Any, Callable, Iterable, Mapping, Sequence

SCRIPT_DIR = Path(__file__).resolve().parent
TOOL_VERSION = "0.0.97"
REPORT_NAME = "BR_quartet_restoration_reflector_ringlight_structural_shift_evidence.tar.zst"
REPORT_DIR = "reflector_ringlight_structural_shift_evidence"
STAGE82_DIR = "reflector_ringlight_g1e_record_shape_evidence"
STAGE82_ARCHIVE = "BR_quartet_restoration_reflector_ringlight_g1e_record_shape_evidence.tar.zst"
STAGE81_DIR = "reflector_ringlight_control_callsite_evidence"
STAGE81_ARCHIVE = "BR_quartet_restoration_reflector_ringlight_control_callsite_evidence.tar.zst"
STAGE80_DIR = "reflector_light_family_binary_evidence"
STAGE80_ARCHIVE = "BR_quartet_restoration_reflector_light_family_binary_evidence.tar.zst"
STAGE79_DIR = "reflector_character_slot_render_member_evidence"
STAGE79_ARCHIVE = "BR_quartet_restoration_reflector_character_slot_render_member_evidence.tar.zst"
EXPECTED_COMMON_ROWS = 15
EXPECTED_CLUSTER_ROWS = 3
EXPECTED_CHANGED_WORD_ROWS = 36
EXPECTED_PARENT_CONTAINERS = 4
DEFAULT_SHIFT_CANDIDATES = (4, 8, 12, 16)
EFFECT_EXTENSIONS = {".g1e", ".g1em"}


class Stage83Error(RuntimeError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise Stage83Error(message)


def progress(message: str) -> None:
    print(f"[stage83] {message}", file=sys.stderr, flush=True)


def parse_int(value: Any, default: int = 0) -> int:
    try:
        return int(str(value).strip(), 0)
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
            raise Stage83Error(f"missing required TSV: {path}")
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
        raise Stage83Error(f"invalid JSON {path}: {exc}") from exc
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


def validate_stage82(root: Path) -> dict[str, Any]:
    summary = load_json(root / "SUMMARY.json")
    require(summary.get("type") == "br_quartet_restoration_reflector_ringlight_g1e_record_shape_evidence_summary", "stage82 type mismatch")
    require(summary.get("tool_version") == "0.0.96", "stage82 tool version mismatch")
    require(parse_int(summary.get("common_ringlight_member_rows"), -1) == EXPECTED_COMMON_ROWS, "stage82 common member count mismatch")
    require(parse_int(summary.get("common_ringlight_aligned_word_rows"), -1) == EXPECTED_CHANGED_WORD_ROWS, "stage82 changed word count mismatch")
    require(parse_int(summary.get("common_ringlight_cluster_rows"), -1) == EXPECTED_CLUSTER_ROWS, "stage82 cluster count mismatch")
    require(parse_int(summary.get("complete_cluster_match_rows"), -1) == 0, "stage82 complete cluster matches must be zero for this gate")
    require(parse_int(summary.get("full_profile_match_rows"), -1) == 0, "stage82 full-profile matches must be zero for this gate")
    require(parse_int(summary.get("semantic_leaf_candidate_rows"), -1) == 0, "stage82 unexpectedly contains semantic candidates")
    require(parse_int(summary.get("prototype_candidate_rows"), -1) == 0, "stage82 unexpectedly contains prototype candidates")
    require(parse_int(summary.get("skipped_rows"), -1) == 0, "stage82 contains skipped rows")
    policy = summary.get("policy") or {}
    require(isinstance(policy, dict), "stage82 policy malformed")
    for field in ("installed_game_modified", "render_payload_written", "event_payload_written", "pak_repacked", "core_registry_modified", "profile_activated"):
        require(not parse_bool(policy.get(field)), f"stage82 performed forbidden action: {field}")
    return summary


def u32(payload: bytes, offset: int) -> int:
    require(offset >= 0 and offset + 4 <= len(payload), f"dword offset outside payload: {offset}")
    return int.from_bytes(payload[offset:offset + 4], "little")


def changed_dword_offsets(source: bytes, target: bytes) -> list[int]:
    require(len(source) == len(target), "structural shift audit requires equal payload sizes")
    require(len(source) % 4 == 0, "structural shift audit requires dword-sized payloads")
    return [offset for offset in range(0, len(source), 4) if source[offset:offset + 4] != target[offset:offset + 4]]


def is_small_aligned_offset(value: int) -> bool:
    return 0 < value <= 0x1000000 and value % 4 == 0


def infer_shift_candidates(cluster_rows: Sequence[Mapping[str, Any]], allowed: Sequence[int]) -> list[int]:
    counts: Counter[int] = Counter()
    for row in cluster_rows:
        source = parse_int(row.get("source_u32_hex"), -1)
        target = parse_int(row.get("target_u32_hex"), -1)
        difference = source - target
        if difference in allowed and is_small_aligned_offset(source) and target >= 0:
            counts[difference] += 1
    return [shift for shift, _count in sorted(counts.items(), key=lambda item: (-item[1], item[0]))]


def classify_model_word(source: bytes, target: bytes, offset: int, pivot: int, shift: int, tail_offsets: set[int]) -> tuple[str, int | None]:
    source_value = u32(source, offset)
    target_value = u32(target, offset)
    if offset < pivot and source_value >= shift and target_value == source_value - shift:
        return "envelope_length_shrunk_by_shift", None
    if offset in tail_offsets and target_value == 0 and source_value != 0:
        return "vacated_tail_zero_fill", None
    if offset >= pivot and offset + shift + 4 <= len(source):
        shifted_source = u32(source, offset + shift)
        if target_value == shifted_source:
            return "payload_word_shifted_left_exact", offset + shift
        if is_small_aligned_offset(shifted_source) and target_value == shifted_source + shift:
            return "relative_offset_shifted_left_and_rebased", offset + shift
    if offset in tail_offsets and target_value == 0:
        return "vacated_tail_zero_fill", None
    return "unexplained_changed_word", None


def discover_cluster_model(
    source: bytes,
    target: bytes,
    cluster_id: str,
    cluster_rows: Sequence[Mapping[str, Any]],
    allowed_shifts: Sequence[int] = DEFAULT_SHIFT_CANDIDATES,
) -> dict[str, Any]:
    ordered = sorted((dict(row) for row in cluster_rows), key=lambda row: parse_int(row.get("word_offset"), -1))
    require(ordered, f"{cluster_id}: empty cluster")
    offsets = [parse_int(row.get("word_offset"), -1) for row in ordered]
    require(all(offset >= 0 and offset % 4 == 0 for offset in offsets), f"{cluster_id}: invalid dword offsets")
    candidates = infer_shift_candidates(ordered, allowed_shifts)
    if not candidates:
        candidates = list(allowed_shifts)

    best: dict[str, Any] | None = None
    for shift in candidates:
        words = shift // 4
        if shift <= 0 or shift % 4 != 0 or words <= 0:
            continue
        for pivot in offsets:
            if pivot + shift > len(source) or source[pivot:pivot + shift] != b"\x00" * shift:
                continue
            tail_offsets = set(offsets[-words:])
            details: list[dict[str, Any]] = []
            counts: Counter[str] = Counter()
            for offset in offsets:
                classification, mapped_source_offset = classify_model_word(source, target, offset, pivot, shift, tail_offsets)
                counts[classification] += 1
                details.append({
                    "cluster_id": cluster_id,
                    "word_offset": offset,
                    "relative_to_cluster_start": offset - offsets[0],
                    "source_u32_hex": f"0x{u32(source, offset):08x}",
                    "target_u32_hex": f"0x{u32(target, offset):08x}",
                    "model_classification": classification,
                    "mapped_source_offset": "" if mapped_source_offset is None else mapped_source_offset,
                    "mapped_source_u32_hex": "" if mapped_source_offset is None else f"0x{u32(source, mapped_source_offset):08x}",
                    "shift_bytes": shift,
                    "pivot_offset": pivot,
                })
            explained = len(offsets) - counts["unexplained_changed_word"]
            score = (
                explained,
                counts["payload_word_shifted_left_exact"] + counts["relative_offset_shifted_left_and_rebased"],
                counts["envelope_length_shrunk_by_shift"],
                counts["vacated_tail_zero_fill"],
                -pivot,
            )
            candidate = {
                "cluster_id": cluster_id,
                "cluster_start": offsets[0],
                "cluster_end_exclusive": offsets[-1] + 4,
                "shift_bytes": shift,
                "pivot_offset": pivot,
                "zero_gap_words": words,
                "changed_word_rows": len(offsets),
                "explained_word_rows": explained,
                "residual_word_rows": counts["unexplained_changed_word"],
                "envelope_shrink_rows": counts["envelope_length_shrunk_by_shift"],
                "shifted_exact_rows": counts["payload_word_shifted_left_exact"],
                "shifted_rebased_offset_rows": counts["relative_offset_shifted_left_and_rebased"],
                "tail_zero_fill_rows": counts["vacated_tail_zero_fill"],
                "model_complete": counts["unexplained_changed_word"] == 0,
                "details": details,
                "score": score,
            }
            if best is None or candidate["score"] > best["score"]:
                best = candidate
    require(best is not None, f"{cluster_id}: no zero-gap shift model candidate")
    return best


def generate_model_target(source: bytes, target: bytes, model_rows: Sequence[Mapping[str, Any]]) -> bytes:
    candidate = bytearray(source)
    for row in model_rows:
        classification = str(row.get("model_classification", ""))
        require(classification != "unexplained_changed_word", "cannot generate target from incomplete model")
        offset = parse_int(row.get("word_offset"), -1)
        candidate[offset:offset + 4] = target[offset:offset + 4]
    return bytes(candidate)


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

    stage82 = load_module(project_root / "workstreams/quartet_restoration/collect_reflector_ringlight_g1e_record_shape_evidence.py", "stage82_for_stage83")
    stage81 = load_module(project_root / "workstreams/quartet_restoration/collect_reflector_ringlight_control_callsite_evidence.py", "stage81_for_stage83")
    progress("validating stage 79-82 reports")
    with tempfile.TemporaryDirectory(prefix="br-stage83-") as temporary_name:
        temporary = Path(temporary_name)
        stage82_root = locate(reports, STAGE82_DIR, STAGE82_ARCHIVE, temporary / "82")
        stage81_root = locate(reports, STAGE81_DIR, STAGE81_ARCHIVE, temporary / "81")
        stage80_root = locate(reports, STAGE80_DIR, STAGE80_ARCHIVE, temporary / "80")
        stage79_root = locate(reports, STAGE79_DIR, STAGE79_ARCHIVE, temporary / "79")
        summary82 = validate_stage82(stage82_root)
        summary81 = stage82.validate_stage81(stage81_root)
        summary80 = stage81.validate_stage80(stage80_root)
        summary79 = stage81.validate_stage79(stage79_root)

        cluster_table = read_tsv(stage82_root / "COMMON_RINGLIGHT_CHANGE_CLUSTERS.tsv")
        cluster_words = read_tsv(stage82_root / "COMMON_RINGLIGHT_CLUSTER_WORDS.tsv")
        require(len(cluster_table) == EXPECTED_CLUSTER_ROWS, "stage82 cluster table count mismatch")
        require(len(cluster_words) == EXPECTED_CHANGED_WORD_ROWS, "stage82 cluster word table count mismatch")
        words_by_cluster: dict[str, list[dict[str, str]]] = defaultdict(list)
        for row in cluster_words:
            words_by_cluster[str(row.get("cluster_id", ""))].append(row)
        require(set(words_by_cluster) == {str(row.get("cluster_id", "")) for row in cluster_table}, "stage82 cluster identities mismatch")

        common_scope = stage81.select_common_scope(stage79_root)
        parent_scope = stage81.select_parent_scope(stage79_root)
        actual_rules = rules_file or project_root / "titles/blue_reflection/modules/quartet_restoration/mappings/effect_material_rules.tsv"
        actual_loader = container_loader or stage81.load_parent_containers
        containers, skipped = actual_loader(
            scope_rows=parent_scope,
            workspace_root=workspace,
            report_root=reports,
            rules_file=actual_rules,
            maximum_earc_bytes=maximum_earc_bytes,
        )
        require(not skipped, f"parent container loader skipped {len(skipped)} rows")
        require(len(containers) == EXPECTED_PARENT_CONTAINERS, f"expected four parent containers, found {len(containers)}")

        pair_by_key: dict[tuple[str, str], dict[str, Any]] = {}
        for index, container in enumerate(containers, start=1):
            progress(f"indexing parent container {index}/{len(containers)}: {container.get('normalized_path', '')}")
            source_members = {str(row.get("comparison_key", "")).casefold(): row for row in container.get("source_members", [])}
            target_members = {str(row.get("comparison_key", "")).casefold(): row for row in container.get("target_members", [])}
            for member_key in sorted(set(source_members) & set(target_members)):
                left = source_members[member_key]
                right = target_members[member_key]
                name = str(right.get("name") or left.get("name") or "")
                if Path(name).suffix.casefold() not in EFFECT_EXTENSIONS:
                    continue
                key = (str(container.get("normalized_path", "")).casefold(), member_key)
                require(key not in pair_by_key, f"duplicate rehydrated member identity: {key}")
                pair_by_key[key] = {
                    "normalized_path": key[0], "member_key": member_key, "member_name": name,
                    "source_payload": bytes(left.get("payload") or b""),
                    "target_payload": bytes(right.get("payload") or b""),
                }

        audit80_rows = read_tsv(stage80_root / "REFLECTOR_LIGHT_MEMBER_BINARY_AUDIT.tsv")
        audit80: dict[tuple[str, str], dict[str, str]] = {}
        for row in audit80_rows:
            key = stage82.stage80_audit_key(row)
            require(all(key) and key not in audit80, f"invalid or duplicate stage80 audit identity: {key}")
            audit80[key] = row

        slot_pairs: list[dict[str, Any]] = []
        canonical_source: bytes | None = None
        canonical_target: bytes | None = None
        canonical_changed: list[int] | None = None
        expected_transitions = sorted(
            (
                parse_int(row.get("word_offset"), -1),
                str(row.get("source_u32_hex", "")).casefold(),
                str(row.get("target_u32_hex", "")).casefold(),
            )
            for row in cluster_words
        )
        for index, scope in enumerate(common_scope, start=1):
            key = (str(scope.get("normalized_path", "")).casefold(), str(scope.get("member_key", "")).casefold())
            pair = pair_by_key.get(key)
            require(pair is not None, f"common ringlight pair missing: {key}")
            audit = audit80.get(key)
            require(audit is not None, f"stage80 audit row missing: {key}")
            require(audit.get("source_sha256") == sha256(pair["source_payload"]), f"stage80 source hash mismatch: {key}")
            require(audit.get("target_sha256") == sha256(pair["target_payload"]), f"stage80 target hash mismatch: {key}")
            changed = changed_dword_offsets(pair["source_payload"], pair["target_payload"])
            require(len(changed) == EXPECTED_CHANGED_WORD_ROWS, f"unexpected changed dword count: {key}")
            actual_transitions = [
                (
                    offset,
                    f"0x{u32(pair['source_payload'], offset):08x}",
                    f"0x{u32(pair['target_payload'], offset):08x}",
                )
                for offset in changed
            ]
            require(actual_transitions == expected_transitions, f"common transition profile differs by slot: {key}")
            if canonical_source is None:
                canonical_source = pair["source_payload"]
                canonical_target = pair["target_payload"]
                canonical_changed = changed
            else:
                require(changed == canonical_changed, f"common changed offsets differ by slot: {key}")
            slot_pairs.append({**pair, "character_slot": scope.get("character_slot", "")})
            progress(f"validated common ringlight slot {index}/{len(common_scope)}: {scope.get('character_slot', '')}")
        require(canonical_source is not None and canonical_target is not None and canonical_changed is not None, "canonical common ringlight payload missing")

        model_rows: list[dict[str, Any]] = []
        model_word_rows: list[dict[str, Any]] = []
        residual_rows: list[dict[str, Any]] = []
        models: list[dict[str, Any]] = []
        for index, cluster in enumerate(cluster_table, start=1):
            cluster_id = str(cluster.get("cluster_id", ""))
            progress(f"testing structural model {index}/{len(cluster_table)}: {cluster_id}")
            model = discover_cluster_model(canonical_source, canonical_target, cluster_id, words_by_cluster[cluster_id])
            models.append(model)
            model_rows.append({
                "cluster_id": cluster_id,
                "cluster_start": model["cluster_start"],
                "cluster_end_exclusive": model["cluster_end_exclusive"],
                "shift_bytes": model["shift_bytes"],
                "pivot_offset": model["pivot_offset"],
                "zero_gap_words": model["zero_gap_words"],
                "changed_word_rows": model["changed_word_rows"],
                "explained_word_rows": model["explained_word_rows"],
                "residual_word_rows": model["residual_word_rows"],
                "envelope_shrink_rows": model["envelope_shrink_rows"],
                "shifted_exact_rows": model["shifted_exact_rows"],
                "shifted_rebased_offset_rows": model["shifted_rebased_offset_rows"],
                "tail_zero_fill_rows": model["tail_zero_fill_rows"],
                "model_complete": model["model_complete"],
                "review_status": "complete_record_compaction_model" if model["model_complete"] else "semantic_or_structural_residuals_remain",
            })
            for detail in model["details"]:
                row = {
                    **detail,
                    "review_status": "structural_model_component_not_brightness_leaf" if detail["model_classification"] != "unexplained_changed_word" else "unexplained_semantic_or_structure_candidate",
                }
                model_word_rows.append(row)
                if detail["model_classification"] == "unexplained_changed_word":
                    residual_rows.append(row)

        uniform_shift = len({model["shift_bytes"] for model in models}) == 1
        all_complete = all(model["model_complete"] for model in models)
        generated = generate_model_target(canonical_source, canonical_target, model_word_rows) if all_complete else b""
        exact_model_target = all_complete and generated == canonical_target
        changed_covered = sorted(parse_int(row.get("word_offset"), -1) for row in model_word_rows) == canonical_changed
        require(changed_covered, "model word coverage does not equal canonical changed dwords")

        slot_validation_rows: list[dict[str, Any]] = []
        for pair in slot_pairs:
            generated_slot = generate_model_target(pair["source_payload"], pair["target_payload"], model_word_rows) if all_complete else b""
            slot_validation_rows.append({
                "character_slot": pair["character_slot"],
                "normalized_path": pair["normalized_path"],
                "member_key": pair["member_key"],
                "source_sha256": sha256(pair["source_payload"]),
                "target_sha256": sha256(pair["target_payload"]),
                "model_target_sha256": sha256(generated_slot) if generated_slot else "",
                "exact_model_target": bool(generated_slot and generated_slot == pair["target_payload"]),
                "changed_dword_rows": len(changed_dword_offsets(pair["source_payload"], pair["target_payload"])),
                "residual_dword_rows": len(residual_rows),
                "review_status": "uniform_structural_model_exact" if generated_slot and generated_slot == pair["target_payload"] and not residual_rows else "model_incomplete_or_nonuniform",
            })

        if all_complete and uniform_shift and exact_model_target and not residual_rows and all(parse_bool(row["exact_model_target"]) for row in slot_validation_rows):
            status = "common_ringlight_delta_fully_explained_by_uniform_eight_byte_record_compaction_no_brightness_leaf_residual"
            next_action = "Upload this report. Close the common e_cmn_ringlight_PC00-PC14 family as a direct brightness-scalar lead: its entire delta is a uniform record-layout compaction with no residual changed word. Continue with the structurally different slot-specific ringlight and eyelight members in a separate format-aware audit."
        else:
            status = "common_ringlight_structural_shift_model_incomplete_semantic_or_layout_residuals_remain"
            next_action = "Upload this report. Do not prototype the common ringlight family. Review every residual changed word and derive exact G1E record boundaries before interpreting brightness semantics."

        output_dir = reports / REPORT_DIR
        if output_dir.exists():
            import shutil
            shutil.rmtree(output_dir)
        output_dir.mkdir(parents=True)
        write_tsv(output_dir / "COMMON_RINGLIGHT_STRUCTURAL_SHIFT_MODELS.tsv", [
            "cluster_id", "cluster_start", "cluster_end_exclusive", "shift_bytes", "pivot_offset", "zero_gap_words",
            "changed_word_rows", "explained_word_rows", "residual_word_rows", "envelope_shrink_rows",
            "shifted_exact_rows", "shifted_rebased_offset_rows", "tail_zero_fill_rows", "model_complete", "review_status",
        ], model_rows)
        write_tsv(output_dir / "COMMON_RINGLIGHT_STRUCTURAL_SHIFT_WORDS.tsv", [
            "cluster_id", "word_offset", "relative_to_cluster_start", "source_u32_hex", "target_u32_hex",
            "model_classification", "mapped_source_offset", "mapped_source_u32_hex", "shift_bytes", "pivot_offset", "review_status",
        ], model_word_rows)
        write_tsv(output_dir / "COMMON_RINGLIGHT_STRUCTURAL_RESIDUALS.tsv", [
            "cluster_id", "word_offset", "relative_to_cluster_start", "source_u32_hex", "target_u32_hex",
            "model_classification", "mapped_source_offset", "mapped_source_u32_hex", "shift_bytes", "pivot_offset", "review_status",
        ], residual_rows)
        write_tsv(output_dir / "COMMON_RINGLIGHT_SLOT_MODEL_VALIDATION.tsv", [
            "character_slot", "normalized_path", "member_key", "source_sha256", "target_sha256", "model_target_sha256",
            "exact_model_target", "changed_dword_rows", "residual_dword_rows", "review_status",
        ], slot_validation_rows)
        write_tsv(output_dir / "COMMON_RINGLIGHT_STRUCTURAL_SHIFT_SKIPPED.tsv", [
            "scope", "normalized_path", "member_key", "side", "reason",
        ], skipped)

        shift_values = sorted({model["shift_bytes"] for model in models})
        summary = {
            "type": "br_quartet_restoration_reflector_ringlight_structural_shift_evidence_summary",
            "format_version": 1,
            "tool_version": TOOL_VERSION,
            "source_stage82_tool_version": summary82.get("tool_version"),
            "source_stage81_tool_version": summary81.get("tool_version"),
            "source_stage80_tool_version": summary80.get("tool_version"),
            "source_stage79_tool_version": summary79.get("tool_version"),
            "status": status,
            "common_ringlight_member_rows": len(slot_pairs),
            "common_ringlight_cluster_rows": len(models),
            "common_ringlight_changed_dword_rows": len(canonical_changed),
            "model_shift_values": shift_values,
            "uniform_shift_across_clusters": uniform_shift,
            "complete_cluster_model_rows": sum(model["model_complete"] for model in models),
            "explained_dword_rows": sum(model["explained_word_rows"] for model in models),
            "residual_dword_rows": len(residual_rows),
            "envelope_shrink_rows": sum(model["envelope_shrink_rows"] for model in models),
            "shifted_exact_rows": sum(model["shifted_exact_rows"] for model in models),
            "shifted_rebased_offset_rows": sum(model["shifted_rebased_offset_rows"] for model in models),
            "tail_zero_fill_rows": sum(model["tail_zero_fill_rows"] for model in models),
            "exact_model_target": exact_model_target,
            "exact_slot_model_rows": sum(parse_bool(row["exact_model_target"]) for row in slot_validation_rows),
            "brightness_leaf_residual_rows": len(residual_rows),
            "brightness_semantics_confirmed": False,
            "prototype_candidate_rows": 0,
            "skipped_rows": len(skipped),
            "parameters": {
                "maximum_earc_bytes": maximum_earc_bytes,
                "allowed_shift_candidates": list(DEFAULT_SHIFT_CANDIDATES),
                "model_components": [
                    "envelope_length_shrunk_by_shift",
                    "zero_gap_removed",
                    "payload_word_shifted_left_exact",
                    "relative_offset_shifted_left_and_rebased",
                    "vacated_tail_zero_fill",
                ],
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
        )
        print(f"Report directory: {output}")
        print(
            f"Clusters: {summary['common_ringlight_cluster_rows']}; "
            f"explained dwords: {summary['explained_dword_rows']}/{summary['common_ringlight_changed_dword_rows']}; "
            f"residuals: {summary['residual_dword_rows']}"
        )
        if archive:
            print(f"Report: {archive}")
        return 0
    except Stage83Error as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
