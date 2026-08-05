#!/usr/bin/env python3
"""Audit recurrence of stage-96 record/trailer residual shapes.

Stage 96 localized the remaining differences between Original ``150`` and the
two Quartet ``75`` anchored blocks, but neither target became an exact peer.
This stage is metadata-only.  It compares those record/trailer transition
seeds against the 634 format-aware aligned dword changes already exported by
stage 84 for the six non-common Reflector light members.

An exact transition or a matching signed delta is recurrence evidence only.
It cannot identify an occurrence, assign a field meaning, or authorize a G1E
write.  Missing recurrence is also not proof of uniqueness because stage 84's
alignment intentionally omits ambiguous insertions and size-changing regions.
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import subprocess
import sys
import tempfile
from collections import Counter, defaultdict
from pathlib import Path, PurePosixPath
from typing import Any, Iterable, Mapping, Sequence

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT_DEFAULT = SCRIPT_DIR.parent.parent

TOOL_VERSION = "0.1.11"
REPORT_NAME = "BR_quartet_restoration_reflector_slot_light_residual_shape_recurrence_evidence.tar.zst"
REPORT_DIR = "reflector_slot_light_residual_shape_recurrence_evidence"
STAGE84_DIR = "reflector_slot_light_g1e_structure_evidence"
STAGE84_ARCHIVE = "BR_quartet_restoration_reflector_slot_light_g1e_structure_evidence.tar.zst"
STAGE96_DIR = "reflector_slot_light_anchored_block_internal_change_evidence"
STAGE96_ARCHIVE = "BR_quartet_restoration_reflector_slot_light_anchored_block_internal_change_evidence.tar.zst"

EXPECTED_STAGE84_CHANGED_DWORDS = 634
EXPECTED_STAGE84_SCOPE_MEMBERS = 6
EXPECTED_STAGE96_SIBLING_PAIRS = 540
EXPECTED_STAGE96_FOCAL_OCCURRENCES = 21
EXPECTED_STAGE96_COMPARISONS = 5
EXPECTED_STAGE96_INTERNAL_DIFFS = 23
EXPECTED_STAGE96_AMBIGUOUS_SEEDS = 13
FOCAL_MEMBER = "e_pc02_w5_ringlight_01.g1e"


class Stage97Error(RuntimeError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise Stage97Error(message)


def progress(message: str) -> None:
    print(f"[stage97] {message}", file=sys.stderr, flush=True)


def parse_int(value: Any, default: int = 0) -> int:
    try:
        text = str(value).strip()
        return int(text, 16) if text.casefold().startswith("0x") else int(text)
    except (TypeError, ValueError):
        return default


def parse_bool(value: Any) -> bool:
    return str(value).strip().casefold() in {"1", "true", "yes", "y"}


def signed_i32(value: int) -> int:
    value &= 0xFFFFFFFF
    return value - 0x100000000 if value & 0x80000000 else value


def safe_name(raw: str) -> str:
    path = PurePosixPath(raw)
    require(not path.is_absolute() and path.parts and ".." not in path.parts, f"unsafe archive member: {raw}")
    return path.as_posix()


def read_tsv(path: Path) -> list[dict[str, str]]:
    require(path.is_file(), f"missing required TSV: {path}")
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
        raise Stage97Error(f"invalid JSON {path}: {exc}") from exc
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
    completed = subprocess.run(
        ["tar", "--zstd", "-cf", str(temporary), "-C", str(source.parent), source.name],
        text=True,
        capture_output=True,
    )
    require(completed.returncode == 0, completed.stderr.strip())
    os.replace(temporary, output)


def validate_stage84(root: Path) -> dict[str, Any]:
    summary = load_json(root / "SUMMARY.json")
    require(summary.get("type") == "br_quartet_restoration_reflector_slot_light_g1e_structure_evidence_summary", "stage84 type mismatch")
    require(summary.get("tool_version") == "0.0.98", "stage84 tool version mismatch")
    require(parse_int(summary.get("scope_member_rows"), -1) == EXPECTED_STAGE84_SCOPE_MEMBERS, "stage84 scope count mismatch")
    require(parse_int(summary.get("aligned_changed_dword_rows"), -1) == EXPECTED_STAGE84_CHANGED_DWORDS, "stage84 aligned-dword count mismatch")
    require(parse_int(summary.get("prototype_candidate_rows"), -1) == 0, "stage84 unexpectedly authorized a prototype")
    require(not parse_bool(summary.get("brightness_semantics_confirmed")), "stage84 unexpectedly confirmed brightness")
    require(parse_int(summary.get("skipped_rows"), -1) == 0, "stage84 contains skipped rows")
    return summary


def validate_stage96(root: Path) -> dict[str, Any]:
    summary = load_json(root / "SUMMARY.json")
    require(summary.get("type") == "br_quartet_restoration_reflector_slot_light_anchored_block_internal_change_evidence_summary", "stage96 type mismatch")
    require(summary.get("tool_version") == "0.1.10", "stage96 tool version mismatch")
    require(parse_int(summary.get("sibling_G1E_G1EM_member_rows"), -1) == EXPECTED_STAGE96_SIBLING_PAIRS, "stage96 sibling-pair count mismatch")
    require(parse_int(summary.get("focal_occurrence_rows"), -1) == EXPECTED_STAGE96_FOCAL_OCCURRENCES, "stage96 focal occurrence count mismatch")
    require(parse_int(summary.get("comparison_rows"), -1) == EXPECTED_STAGE96_COMPARISONS, "stage96 comparison count mismatch")
    require(parse_int(summary.get("internal_dword_difference_rows"), -1) == EXPECTED_STAGE96_INTERNAL_DIFFS, "stage96 internal-difference count mismatch")
    require(parse_int(summary.get("consensus_stable_transition_signatures"), -1) == 0, "stage96 unexpectedly found a consensus stable mask")
    require(not parse_bool(summary.get("candidate_target_occurrence_identity_resolved")), "stage96 unexpectedly resolved target identity")
    require(parse_int(summary.get("prototype_candidate_rows"), -1) == 0, "stage96 unexpectedly authorized a prototype")
    require(not parse_bool(summary.get("technical_leaf_semantics_resolved")), "stage96 unexpectedly resolved leaf semantics")
    require(not parse_bool(summary.get("brightness_semantics_confirmed")), "stage96 unexpectedly confirmed brightness")
    require(not parse_bool(summary.get("censorship_semantics_confirmed")), "stage96 unexpectedly confirmed censorship")
    require(parse_int(summary.get("skipped_rows"), -1) == 0, "stage96 contains skipped rows")
    return summary


def transition_key(source_hex: str, target_hex: str) -> tuple[int, int]:
    return (parse_int(source_hex, -1) & 0xFFFFFFFF, parse_int(target_hex, -1) & 0xFFFFFFFF)


def build_report(
    project_root: Path,
    *,
    create_archive: bool = True,
    report_root: Path | None = None,
) -> tuple[Path, Path | None, dict[str, Any]]:
    project_root = project_root.resolve()
    reports = (report_root or project_root / ".local/reports/quartet_restoration").resolve()
    require(reports.is_dir(), f"missing report root: {reports}")

    progress("validating stage 84 and stage 96 reports")
    with tempfile.TemporaryDirectory(prefix="br-stage97-") as temporary_name:
        temporary = Path(temporary_name)
        stage84_root = locate(reports, STAGE84_DIR, STAGE84_ARCHIVE, temporary / "84")
        stage96_root = locate(reports, STAGE96_DIR, STAGE96_ARCHIVE, temporary / "96")
        summary84 = validate_stage84(stage84_root)
        summary96 = validate_stage96(stage96_root)

        aligned84 = read_tsv(stage84_root / "SLOT_LIGHT_ALIGNED_CHANGED_DWORDS.tsv")
        internal96 = read_tsv(stage96_root / "SLOT_LIGHT_INTERNAL_DWORD_DIFFERENCES.tsv")
        require(len(aligned84) == EXPECTED_STAGE84_CHANGED_DWORDS, "stage84 aligned table row count mismatch")
        require(len(internal96) == EXPECTED_STAGE96_INTERNAL_DIFFS, "stage96 internal table row count mismatch")

        seeds = [
            dict(row)
            for row in internal96
            if row.get("comparison_role") == "ambiguous_candidate"
            and row.get("segment") in {"reference_record", "post_record_trailer"}
        ]
        require(len(seeds) == EXPECTED_STAGE96_AMBIGUOUS_SEEDS, "stage96 ambiguous seed count mismatch")

        aligned_by_pair: dict[tuple[int, int], list[dict[str, str]]] = defaultdict(list)
        aligned_by_delta: dict[int, list[dict[str, str]]] = defaultdict(list)
        aligned_source_counts: Counter[int] = Counter()
        aligned_target_counts: Counter[int] = Counter()
        for row in aligned84:
            source, target = transition_key(row.get("source_u32_hex", ""), row.get("target_u32_hex", ""))
            require(source >= 0 and target >= 0, "invalid stage84 transition value")
            aligned_by_pair[(source, target)].append(row)
            aligned_by_delta[signed_i32(target) - signed_i32(source)].append(row)
            aligned_source_counts[source] += 1
            aligned_target_counts[target] += 1

        seed_rows: list[dict[str, Any]] = []
        unique_seed_map: dict[tuple[int, int], dict[str, Any]] = {}
        positions_by_pair: dict[tuple[int, int], list[str]] = defaultdict(list)
        comparisons_by_pair: dict[tuple[int, int], set[str]] = defaultdict(set)
        for row in seeds:
            source, target = transition_key(row["left_u32_hex"], row["right_u32_hex"])
            key = (source, target)
            positions_by_pair[key].append(str(row["relative_dword"]))
            comparisons_by_pair[key].add(str(row["comparison"]))
            exact_hits = aligned_by_pair.get(key, [])
            delta = signed_i32(target) - signed_i32(source)
            delta_hits = aligned_by_delta.get(delta, [])
            exact_outside = [hit for hit in exact_hits if hit.get("member_name", "").casefold() != FOCAL_MEMBER]
            delta_outside = [hit for hit in delta_hits if hit.get("member_name", "").casefold() != FOCAL_MEMBER]
            seed_rows.append({
                "comparison": row["comparison"],
                "relative_dword": row["relative_dword"],
                "relative_byte": row["relative_byte"],
                "segment": row["segment"],
                "source_u32_hex": row["left_u32_hex"],
                "target_u32_hex": row["right_u32_hex"],
                "source_i32": signed_i32(source),
                "target_i32": signed_i32(target),
                "source_float32": row.get("left_float32", ""),
                "target_float32": row.get("right_float32", ""),
                "signed_delta": delta,
                "stage84_exact_transition_hits": len(exact_hits),
                "stage84_exact_transition_member_count": len({hit.get("member_name", "").casefold() for hit in exact_hits}),
                "stage84_exact_transition_hits_outside_focal_member": len(exact_outside),
                "stage84_signed_delta_hits": len(delta_hits),
                "stage84_signed_delta_member_count": len({hit.get("member_name", "").casefold() for hit in delta_hits}),
                "stage84_signed_delta_hits_outside_focal_member": len(delta_outside),
                "stage84_source_value_hits": aligned_source_counts[source],
                "stage84_target_value_hits": aligned_target_counts[target],
                "coverage_note": "stage84 covers only format-aware aligned changes; absent hits do not prove uniqueness",
            })
            unique_seed_map.setdefault(key, {
                "source": source,
                "target": target,
                "delta": delta,
                "segment_set": set(),
            })["segment_set"].add(row["segment"])

        exact_rows: list[dict[str, Any]] = []
        delta_rows: list[dict[str, Any]] = []
        classification_rows: list[dict[str, Any]] = []
        exact_outside_supported = 0
        delta_outside_supported = 0

        progress(f"auditing {len(unique_seed_map)} unique transition shapes against {len(aligned84)} aligned sibling changes")
        for seed_index, (key, info) in enumerate(sorted(unique_seed_map.items()), 1):
            source, target = key
            exact_hits = aligned_by_pair.get(key, [])
            delta_hits = aligned_by_delta.get(info["delta"], [])
            exact_outside = [hit for hit in exact_hits if hit.get("member_name", "").casefold() != FOCAL_MEMBER]
            delta_outside = [hit for hit in delta_hits if hit.get("member_name", "").casefold() != FOCAL_MEMBER]
            if exact_outside:
                exact_outside_supported += 1
            if delta_outside:
                delta_outside_supported += 1

            seed_id = f"seed_{seed_index:02d}"
            for hit in exact_hits:
                exact_rows.append({
                    "seed_id": seed_id,
                    "seed_source_u32_hex": f"0x{source:08x}",
                    "seed_target_u32_hex": f"0x{target:08x}",
                    "seed_relative_dwords": ",".join(sorted(set(positions_by_pair[key]), key=int)),
                    "seed_comparisons": ",".join(sorted(comparisons_by_pair[key])),
                    "character_slot": hit.get("character_slot", ""),
                    "asset_role": hit.get("asset_role", ""),
                    "normalized_path": hit.get("normalized_path", ""),
                    "member_key": hit.get("member_key", ""),
                    "member_name": hit.get("member_name", ""),
                    "segment_id": hit.get("segment_id", ""),
                    "source_offset": hit.get("source_offset", ""),
                    "target_offset": hit.get("target_offset", ""),
                    "transition_classification": hit.get("transition_classification", ""),
                    "outside_focal_member": hit.get("member_name", "").casefold() != FOCAL_MEMBER,
                })
            for hit in delta_hits:
                h_source, h_target = transition_key(hit.get("source_u32_hex", ""), hit.get("target_u32_hex", ""))
                delta_rows.append({
                    "seed_id": seed_id,
                    "seed_source_u32_hex": f"0x{source:08x}",
                    "seed_target_u32_hex": f"0x{target:08x}",
                    "seed_signed_delta": info["delta"],
                    "character_slot": hit.get("character_slot", ""),
                    "asset_role": hit.get("asset_role", ""),
                    "normalized_path": hit.get("normalized_path", ""),
                    "member_key": hit.get("member_key", ""),
                    "member_name": hit.get("member_name", ""),
                    "segment_id": hit.get("segment_id", ""),
                    "source_offset": hit.get("source_offset", ""),
                    "target_offset": hit.get("target_offset", ""),
                    "matched_source_u32_hex": f"0x{h_source:08x}",
                    "matched_target_u32_hex": f"0x{h_target:08x}",
                    "exact_transition_match": (h_source, h_target) == key,
                    "transition_classification": hit.get("transition_classification", ""),
                    "outside_focal_member": hit.get("member_name", "").casefold() != FOCAL_MEMBER,
                })

            if exact_outside:
                recurrence_class = "exact_transition_recurrent_outside_focal_member"
            elif exact_hits and delta_outside:
                recurrence_class = "exact_transition_focal_only_signed_delta_recurrent"
            elif exact_hits:
                recurrence_class = "exact_transition_observed_only_in_focal_member"
            elif delta_outside:
                recurrence_class = "exact_transition_absent_signed_delta_recurrent"
            else:
                recurrence_class = "no_recurrence_in_stage84_aligned_changes"

            classification_rows.append({
                "seed_id": seed_id,
                "source_u32_hex": f"0x{source:08x}",
                "target_u32_hex": f"0x{target:08x}",
                "source_i32": signed_i32(source),
                "target_i32": signed_i32(target),
                "signed_delta": info["delta"],
                "segments": ",".join(sorted(info["segment_set"])),
                "relative_dwords": ",".join(sorted(set(positions_by_pair[key]), key=int)),
                "comparisons": ",".join(sorted(comparisons_by_pair[key])),
                "exact_transition_hits": len(exact_hits),
                "exact_transition_member_count": len({hit.get("member_name", "").casefold() for hit in exact_hits}),
                "exact_transition_hits_outside_focal_member": len(exact_outside),
                "signed_delta_hits": len(delta_hits),
                "signed_delta_member_count": len({hit.get("member_name", "").casefold() for hit in delta_hits}),
                "signed_delta_hits_outside_focal_member": len(delta_outside),
                "recurrence_classification": recurrence_class,
                "semantic_classification": "unresolved_evidence_only",
            })

        exact_cross_member = [row for row in classification_rows if parse_int(row["exact_transition_hits_outside_focal_member"], 0) > 0]
        source150_pair = next((row for row in classification_rows if row["source_u32_hex"] == "0x43160000" and row["target_u32_hex"] == "0x42960000"), None)
        require(source150_pair is not None, "missing 150->75 seed classification")

        identity_resolved = False
        decision_rows = [
            {
                "question": "does any exact residual transition recur outside the focal PC02 member",
                "answer": bool(exact_cross_member),
                "classification": "cross_member_exact_recurrence_present" if exact_cross_member else "no_cross_member_exact_recurrence",
            },
            {
                "question": "does the 150 to 75 pair recur as an exact transition outside the focal PC02 member",
                "answer": parse_int(source150_pair["exact_transition_hits_outside_focal_member"], 0) > 0,
                "classification": "150_to_75_cross_member_recurrence" if parse_int(source150_pair["exact_transition_hits_outside_focal_member"], 0) > 0 else "150_to_75_focal_pair_only_in_stage84_alignment",
            },
            {
                "question": "can recurrence select first or second target 75 as the source 150 peer",
                "answer": identity_resolved,
                "classification": "target_occurrence_identity_unresolved",
            },
        ]

        skipped_rows: list[dict[str, Any]] = []
        output = reports / REPORT_DIR
        output.mkdir(parents=True, exist_ok=True)
        write_tsv(output / "SLOT_LIGHT_RESIDUAL_SHAPE_SEEDS.tsv", [
            "comparison", "relative_dword", "relative_byte", "segment", "source_u32_hex", "target_u32_hex",
            "source_i32", "target_i32", "source_float32", "target_float32", "signed_delta",
            "stage84_exact_transition_hits", "stage84_exact_transition_member_count",
            "stage84_exact_transition_hits_outside_focal_member", "stage84_signed_delta_hits",
            "stage84_signed_delta_member_count", "stage84_signed_delta_hits_outside_focal_member",
            "stage84_source_value_hits", "stage84_target_value_hits", "coverage_note",
        ], seed_rows)
        write_tsv(output / "SLOT_LIGHT_EXACT_TRANSITION_RECURRENCE.tsv", [
            "seed_id", "seed_source_u32_hex", "seed_target_u32_hex", "seed_relative_dwords", "seed_comparisons",
            "character_slot", "asset_role", "normalized_path", "member_key", "member_name", "segment_id",
            "source_offset", "target_offset", "transition_classification", "outside_focal_member",
        ], exact_rows)
        write_tsv(output / "SLOT_LIGHT_SIGNED_DELTA_RECURRENCE.tsv", [
            "seed_id", "seed_source_u32_hex", "seed_target_u32_hex", "seed_signed_delta", "character_slot",
            "asset_role", "normalized_path", "member_key", "member_name", "segment_id", "source_offset",
            "target_offset", "matched_source_u32_hex", "matched_target_u32_hex", "exact_transition_match",
            "transition_classification", "outside_focal_member",
        ], delta_rows)
        write_tsv(output / "SLOT_LIGHT_RESIDUAL_SHAPE_CLASSIFICATION.tsv", [
            "seed_id", "source_u32_hex", "target_u32_hex", "source_i32", "target_i32", "signed_delta",
            "segments", "relative_dwords", "comparisons", "exact_transition_hits", "exact_transition_member_count",
            "exact_transition_hits_outside_focal_member", "signed_delta_hits", "signed_delta_member_count",
            "signed_delta_hits_outside_focal_member", "recurrence_classification", "semantic_classification",
        ], classification_rows)
        write_tsv(output / "SLOT_LIGHT_RESIDUAL_RECURRENCE_IDENTITY_DECISION.tsv", [
            "question", "answer", "classification",
        ], decision_rows)
        write_tsv(output / "SLOT_LIGHT_RESIDUAL_SHAPE_RECURRENCE_SKIPPED.tsv", [
            "scope", "reason",
        ], skipped_rows)

        exact_match_row_count = len(exact_rows)
        delta_match_row_count = len(delta_rows)
        focal_only_exact = sum(row["recurrence_classification"] in {
            "exact_transition_focal_only_signed_delta_recurrent",
            "exact_transition_observed_only_in_focal_member",
        } for row in classification_rows)
        absent_exact = sum(not parse_int(row["exact_transition_hits"], 0) for row in classification_rows)
        summary = {
            "type": "br_quartet_restoration_reflector_slot_light_residual_shape_recurrence_evidence_summary",
            "format_version": 1,
            "tool_version": TOOL_VERSION,
            "source_stage84_tool_version": summary84.get("tool_version"),
            "source_stage96_tool_version": summary96.get("tool_version"),
            "status": "residual_shape_recurrence_audited_no_cross_member_exact_support_for_target_identity",
            "stage84_scope_member_rows": EXPECTED_STAGE84_SCOPE_MEMBERS,
            "stage84_aligned_changed_dword_rows": len(aligned84),
            "stage96_sibling_G1E_G1EM_member_rows": EXPECTED_STAGE96_SIBLING_PAIRS,
            "stage96_focal_occurrence_rows": EXPECTED_STAGE96_FOCAL_OCCURRENCES,
            "ambiguous_residual_seed_rows": len(seed_rows),
            "unique_residual_transition_shapes": len(classification_rows),
            "exact_transition_recurrence_rows": exact_match_row_count,
            "signed_delta_recurrence_rows": delta_match_row_count,
            "transition_shapes_with_exact_hits_outside_focal_member": exact_outside_supported,
            "transition_shapes_with_signed_delta_hits_outside_focal_member": delta_outside_supported,
            "transition_shapes_observed_exactly_only_in_focal_member": focal_only_exact,
            "transition_shapes_absent_from_stage84_exact_alignment": absent_exact,
            "source_150_to_target_75_exact_transition_hits": parse_int(source150_pair["exact_transition_hits"], 0),
            "source_150_to_target_75_exact_transition_hits_outside_focal_member": parse_int(source150_pair["exact_transition_hits_outside_focal_member"], 0),
            "candidate_target_occurrence_identity_resolved": identity_resolved,
            "candidate_target_occurrence_identity_reason": "stage84 recurrence can classify transition commonality but cannot align the ambiguous inserted target occurrence",
            "technical_leaf_semantics_resolved": False,
            "brightness_semantics_confirmed": False,
            "censorship_semantics_confirmed": False,
            "prototype_candidate_rows": 0,
            "skipped_rows": len(skipped_rows),
            "parameters": {
                "recurrence_corpus": "stage84 format-aware aligned dword changes from six non-common Reflector light members",
                "exact_recurrence_key": "source_u32,target_u32",
                "delta_recurrence_key": "signed_i32(target)-signed_i32(source)",
                "coverage_limit": "stage84 alignment excludes ambiguous insertions and some size-changing regions; absence is not uniqueness proof",
                "identity_gate": "recurrence alone cannot select one of two target occurrences without occurrence-level alignment",
            },
            "next_action": "Upload this report. If exact transition recurrence remains focal-only or absent, continue only with a read-only local trailer-record layout audit around the second target 75 and same-variant sibling blocks; do not write G1E or infer brightness/censorship.",
            "policy": {
                "render_payload_written": False,
                "full_proprietary_payloads_exported": False,
                "pak_repacked": False,
                "core_registry_modified": False,
                "profile_activated": False,
                "installed_game_modified": False,
                "runtime_validation_inferred": False,
                "technical_leaf_semantics_inferred": False,
                "brightness_semantics_inferred": False,
                "censorship_semantics_inferred": False,
                "canary_track_modified": False,
            },
        }
        (output / "SUMMARY.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        archive = reports / REPORT_NAME if create_archive else None
        if archive is not None:
            progress("creating compressed report archive")
            make_archive(output, archive)
        progress("completed")
        return output, archive, summary


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path, default=PROJECT_ROOT_DEFAULT)
    parser.add_argument("--no-report-archive", action="store_true")
    args = parser.parse_args(argv)
    try:
        output, archive, summary = build_report(args.project_root, create_archive=not args.no_report_archive)
    except Stage97Error as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print(f"Evidence directory: {output}")
    if archive is not None:
        print(f"Report: {archive}")
    print(f"Unique residual shapes: {summary['unique_residual_transition_shapes']}")
    print(f"Exact cross-member recurrence shapes: {summary['transition_shapes_with_exact_hits_outside_focal_member']}")
    print(f"Target identity resolved: {summary['candidate_target_occurrence_identity_resolved']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
