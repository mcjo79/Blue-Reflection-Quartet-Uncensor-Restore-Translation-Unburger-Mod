#!/usr/bin/env python3
"""Read-only audit of append-only synthetic labels for PC00-PC07 BKN.

This tool diagnoses the invalid literal-label assumption from stage 101 and
checks whether Quartet's shipped str_costume extension provides a collision-free
append range for a later, non-installing BKN visibility experiment.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

TOOL_VERSION = "0.0.62"
EXPECTED_VERSION = "0.0.62"
EXPECTED_GENERATION = 8
EXPECTED_MEMBERS = [f"costume_pc{i:02d}_bkn" for i in range(8)]
EXPECTED_TARGETS = {"Data/PACK10_02.PAK", "Data/PACK12.PAK"}
CURRENT_LABEL = "Bikini"


class AuditError(RuntimeError):
    pass


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def scalar(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (dict, list, tuple, set)):
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return str(value)


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def write_tsv(path: Path, rows: Sequence[Mapping[str, Any]], fields: Sequence[str] | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if fields is None:
        ordered: list[str] = []
        for row in rows:
            for key in row:
                if key not in ordered:
                    ordered.append(key)
        fields = ordered or ["status"]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(fields), delimiter="\t", lineterminator="\n")
        writer.writeheader()
        if rows:
            for row in rows:
                writer.writerow({field: scalar(row.get(field, "")) for field in fields})
        else:
            writer.writerow({fields[0]: "no_rows"})


def read_tsv(path: Path) -> list[dict[str, str]]:
    if not path.is_file() or path.is_symlink():
        raise AuditError(f"required TSV is missing or unsafe: {path}")
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def read_json(path: Path) -> dict[str, Any]:
    if not path.is_file() or path.is_symlink():
        raise AuditError(f"required JSON is missing or unsafe: {path}")
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise AuditError(f"expected object in {path}")
    return value


def newest_report(project_root: Path, pattern: str, required: Sequence[str]) -> Path:
    root = project_root / ".local/reports/quartet_legacy_dlc"
    candidates: list[Path] = []
    for path in root.glob(pattern):
        if not path.is_dir() or path.is_symlink():
            continue
        if all((path / relative).is_file() for relative in required):
            candidates.append(path)
    if not candidates:
        raise AuditError(f"no report matching {pattern} with required files")
    return max(candidates, key=lambda value: value.stat().st_mtime_ns)


def load_active(project_root: Path) -> dict[str, Any]:
    active = read_json(project_root / ".local/reports/quartet_legacy_dlc/validated_payloads/ACTIVE.json")
    if active.get("type") != "validated_quartet_legacy_dlc_payload":
        raise AuditError("unexpected ACTIVE.json type")
    if active.get("family_id") != "bkn_dry" or active.get("generation") != EXPECTED_GENERATION:
        raise AuditError("ACTIVE.json is not BKN generation 8")
    if active.get("members") != EXPECTED_MEMBERS:
        raise AuditError("ACTIVE.json members are not exactly PC00-PC07")
    targets = {str(row.get("target_path")) for row in active.get("artifacts", [])}
    if targets != EXPECTED_TARGETS:
        raise AuditError("ACTIVE.json targets changed")
    return active


def verify_installation(active: Mapping[str, Any], game_root: Path) -> tuple[list[dict[str, Any]], bool]:
    rows: list[dict[str, Any]] = []
    all_baseline = True
    for artifact in active.get("artifacts", []):
        target = str(artifact["target_path"])
        path = game_root / target
        if not path.is_file() or path.is_symlink():
            raise AuditError(f"unsafe or missing game artifact: {target}")
        actual = sha256_file(path)
        baseline = str(artifact["baseline_sha256"])
        candidate = str(artifact["candidate_sha256"])
        state = "baseline" if actual == baseline else "generation8_candidate" if actual == candidate else "unknown"
        if state != "baseline":
            all_baseline = False
        rows.append({
            "target_path": target,
            "actual_sha256": actual,
            "baseline_sha256": baseline,
            "generation8_candidate_sha256": candidate,
            "state": state,
            "modified_by_audit": False,
        })
    if any(row["state"] == "unknown" for row in rows):
        raise AuditError("game PAK state is neither accepted baseline nor generation-8 candidate")
    return rows, all_baseline


def integer(value: str, label: str) -> int:
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise AuditError(f"invalid integer {label}: {value!r}") from exc


def pc00_family_order(inventory_rows: Sequence[Mapping[str, str]]) -> list[dict[str, Any]]:
    wanted = ("SLR", "TWL", "VAC", "BKN")
    result: list[dict[str, Any]] = []
    previous: int | None = None
    for code in wanted:
        tag = f"Chara:BaseTag=PC00_DLC_{code}"
        matches = [
            row for row in inventory_rows
            if row.get("table_path") == "saves/chara/chara.xml" and row.get("record_key") == tag
        ]
        if len(matches) != 1:
            raise AuditError(f"expected one source record for {tag}, got {len(matches)}")
        row = matches[0]
        index = integer(row.get("record_index", ""), tag)
        result.append({
            "family_code": code,
            "base_tag": tag.removeprefix("Chara:BaseTag="),
            "content_id": row.get("content_id", ""),
            "subtype": row.get("subtype", ""),
            "dry_record_index": index,
            "delta_from_previous_family": "" if previous is None else index - previous,
            "known_repeated_str_costume_label": code in {"SLR", "TWL", "VAC"},
            "bkn_literal_label_in_original_str_costume": False,
            "record_present_identical_in_quartet": row.get("target_record_status") == "present_identical",
        })
        previous = index
    return result


def analyze_sequence(rows: Sequence[Mapping[str, str]]) -> tuple[list[dict[str, Any]], dict[str, Any], list[dict[str, Any]]]:
    parsed: list[dict[str, Any]] = []
    used_numbers: set[int] = set()
    original_numbers: list[int] = []
    quartet_only: list[dict[str, Any]] = []
    literal_bkn_rows = 0

    for row in rows:
        number = integer(row.get("string_no", ""), "string_no")
        used_numbers.add(number)
        original_text = row.get("original_text", "")
        quartet_text = row.get("quartet_text", "")
        status = row.get("status", "")
        if original_text and ("bikini" in original_text.casefold() or "ビキニ" in original_text):
            literal_bkn_rows += 1
        if original_text:
            original_numbers.append(number)
        if status == "quartet_only":
            quartet_only.append({
                "string_no": number,
                "quartet_record_index": integer(row.get("quartet_record_index", ""), "quartet_record_index"),
                "quartet_text": quartet_text,
                "is_placeholder": quartet_text.strip() in {"", "-", "－", "—", "–"},
                "runtime_visible_label": row.get("runtime_visible_label", "").casefold() == "true",
                "record_sha256": row.get("quartet_record_sha256", ""),
            })
        parsed.append({
            "string_no": number,
            "status": status,
            "original_text": original_text,
            "quartet_text": quartet_text,
        })

    if not original_numbers:
        raise AuditError("no original str_costume rows")
    original_max = max(original_numbers)
    quartet_only_sorted = sorted(quartet_only, key=lambda item: item["string_no"])
    contiguous_append = [row["string_no"] for row in quartet_only_sorted] == list(
        range(original_max + 1, original_max + 1 + len(quartet_only_sorted))
    )
    placeholder_rows = [row for row in quartet_only_sorted if row["is_placeholder"]]
    proposed_start = max(used_numbers) + 1
    proposed = [
        {
            "family_position": slot,
            "pc_slot": f"PC{slot:02d}",
            "base_tag": f"PC{slot:02d}_DLC_BKN",
            "proposed_string_no": proposed_start + slot,
            "proposed_label": CURRENT_LABEL,
            "operation": "append_new_record",
            "existing_record_replaced": False,
            "binding_to_costume_record_proven": False,
            "purpose": "non_installing_generation9_visibility_probe",
        }
        for slot in range(8)
    ]
    summary = {
        "original_row_count": sum(1 for row in parsed if row["original_text"]),
        "quartet_total_row_count": len(parsed),
        "original_max_string_no": original_max,
        "quartet_max_string_no": max(used_numbers),
        "quartet_only_row_count": len(quartet_only_sorted),
        "quartet_only_contiguous_append": contiguous_append,
        "quartet_only_placeholder_count": len(placeholder_rows),
        "quartet_only_runtime_visible_count": sum(1 for row in quartet_only_sorted if row["runtime_visible_label"]),
        "literal_bkn_rows_in_original": literal_bkn_rows,
        "current_bkn_member_count": 8,
        "eventual_full_family_count": 15,
        "existing_placeholder_capacity_sufficient_current": len(placeholder_rows) >= 8,
        "existing_placeholder_capacity_sufficient_full": len(placeholder_rows) >= 15,
        "proposed_append_start": proposed_start,
        "proposed_append_end": proposed_start + 7,
        "proposed_range_collision_free": all((proposed_start + slot) not in used_numbers for slot in range(8)),
    }
    return quartet_only_sorted, summary, proposed


def options(summary: Mapping[str, Any]) -> list[dict[str, Any]]:
    return [
        {
            "rank": 1,
            "strategy": "restore_existing_original_bkn_label_rows",
            "eligible": False,
            "reason": "the original English str_costume table contains no literal BKN/Bikini rows",
            "replaces_existing_costume": False,
        },
        {
            "rank": 2,
            "strategy": "reuse_quartet_only_placeholder_rows_393335_393336",
            "eligible": False,
            "reason": "only two unknown placeholder rows exist; eight current and fifteen eventual BKN entries are required",
            "replaces_existing_costume": False,
        },
        {
            "rank": 3,
            "strategy": "append_eight_new_bkn_label_records",
            "eligible": bool(summary["quartet_only_contiguous_append"] and summary["proposed_range_collision_free"]),
            "reason": "Quartet ships a contiguous four-row extension beyond the original table and the next eight String_No values are unused; runtime label-to-costume binding remains unproven",
            "replaces_existing_costume": False,
        },
        {
            "rank": 4,
            "strategy": "insert_rows_inside_existing_per_character_blocks",
            "eligible": False,
            "reason": "insertion would shift established row order and could mislabel existing costumes",
            "replaces_existing_costume": "possible_runtime_misalignment",
        },
        {
            "rank": 5,
            "strategy": "controlled_bkn_namespace_list_insertion_or_filter_bypass",
            "eligible": True,
            "reason": "fallback if an append-only data probe does not create selectable BKN entries",
            "replaces_existing_costume": False,
        },
    ]


def report_manifest(output_dir: Path) -> None:
    files = []
    for path in sorted(output_dir.rglob("*"), key=lambda value: value.as_posix().casefold()):
        if path.is_file() and path.name not in {"REPORT_MANIFEST.json", "SHA256SUMS"}:
            files.append({
                "relative_path": path.relative_to(output_dir).as_posix(),
                "size": path.stat().st_size,
                "sha256": sha256_file(path),
            })
    write_json(output_dir / "REPORT_MANIFEST.json", {
        "type": "br_report_manifest",
        "format_version": 1,
        "files": files,
    })


def run(project_root: Path, game_root: Path, output_dir: Path) -> dict[str, Any]:
    version = (project_root / "workstreams/quartet_legacy_dlc/VERSION").read_text(encoding="utf-8").strip()
    if version != EXPECTED_VERSION:
        raise AuditError(f"quartet_legacy_dlc {EXPECTED_VERSION} is required, got {version}")

    stage101 = newest_report(
        project_root,
        "BR_QUARTET_CONTROLLED_VISIBILITY_FORCE_POINT_*",
        ("SUMMARY.json", "DATA_ONLY_FORCE_ACCEPTANCE.json", "SHA256SUMS"),
    )
    stage101_summary = read_json(stage101 / "SUMMARY.json")
    if stage101_summary.get("status") != "blocked_force_point_not_closed":
        raise AuditError("unexpected stage 101 status")

    closure = newest_report(
        project_root,
        "BR_QUARTET_DLC_BKN_DRY_GENERATION8_EXACT_AVAILABILITY_CLOSURE_*",
        ("STR_COSTUME_SEQUENCE_DIFF.tsv", "CHARACTER_RECORD_DIFFERENTIAL.tsv", "SHA256SUMS"),
    )
    sequence = read_tsv(closure / "STR_COSTUME_SEQUENCE_DIFF.tsv")
    inventory_path = project_root / ".local/reports/quartet_legacy_dlc/nonscenario_inventory_evidence/DLC_SYSTEM_TABLE_RECORDS.tsv"
    inventory = read_tsv(inventory_path)
    active = load_active(project_root)
    installation, all_baseline = verify_installation(active, game_root)

    family_order = pc00_family_order(inventory)
    quartet_only, sequence_summary, append_plan = analyze_sequence(sequence)
    delta_pattern = [row["delta_from_previous_family"] for row in family_order[1:]]
    regular_family_stride = delta_pattern == [30, 30, 30]
    bkn_distinct_family = regular_family_stride and family_order[-1]["family_code"] == "BKN"

    safe_append_build = bool(
        bkn_distinct_family
        and sequence_summary["literal_bkn_rows_in_original"] == 0
        and sequence_summary["quartet_only_contiguous_append"]
        and not sequence_summary["existing_placeholder_capacity_sufficient_current"]
        and sequence_summary["proposed_range_collision_free"]
        and all_baseline
    )

    decision_status = (
        "accepted_for_generation9_append_only_synthetic_label_candidate_build"
        if safe_append_build
        else "blocked_synthetic_label_slot_not_closed"
    )

    diagnosis = [
        {
            "check": "stage101_integrity",
            "result": "pass",
            "detail": "stage 101 bundle and internal manifests were previously accepted",
        },
        {
            "check": "stage101_literal_bikini_detector",
            "result": "invalid_for_identity",
            "detail": "zero literal Bikini rows cannot identify the internal PCxx_DLC_BKN family",
        },
        {
            "check": "bkn_internal_family_order",
            "result": "pass" if bkn_distinct_family else "fail",
            "detail": f"PC00 SLR/TWL/VAC/BKN dry indices use deltas {delta_pattern}",
        },
        {
            "check": "existing_placeholder_capacity",
            "result": "insufficient",
            "detail": f"{sequence_summary['quartet_only_placeholder_count']} spare rows for 8 current / 15 eventual members",
        },
        {
            "check": "append_only_range",
            "result": "pass" if sequence_summary["proposed_range_collision_free"] else "fail",
            "detail": f"proposed String_No {sequence_summary['proposed_append_start']}-{sequence_summary['proposed_append_end']}",
        },
        {
            "check": "runtime_binding",
            "result": "unproven",
            "detail": "candidate build may be authorized, installation and runtime remain separately gated",
        },
    ]

    output_dir.mkdir(parents=True, exist_ok=True)
    write_tsv(output_dir / "STAGE101_DETECTOR_DIAGNOSIS.tsv", diagnosis)
    write_tsv(output_dir / "PC00_COSTUME_FAMILY_ORDER.tsv", family_order)
    write_tsv(output_dir / "QUARTET_ONLY_STR_COSTUME_ROWS.tsv", quartet_only)
    write_tsv(output_dir / "SYNTHETIC_BKN_LABEL_APPEND_PLAN.tsv", append_plan)
    write_tsv(output_dir / "SYNTHETIC_SLOT_STRATEGY_RANKING.tsv", options(sequence_summary))
    write_tsv(output_dir / "INSTALLATION_BASELINE_GATES.tsv", installation)

    acceptance = {
        "type": "br_quartet_legacy_dlc_bkn_synthetic_label_slot_acceptance",
        "format_version": 1,
        "status": decision_status,
        "source_stage101_report": stage101.name,
        "source_exact_closure_report": closure.name,
        "bkn_is_distinct_internal_family": bkn_distinct_family,
        "regular_pc00_family_stride": regular_family_stride,
        "literal_bkn_label_exists_in_original_str_costume": sequence_summary["literal_bkn_rows_in_original"] > 0,
        "existing_spare_rows_sufficient_for_pc00_pc07": sequence_summary["existing_placeholder_capacity_sufficient_current"],
        "existing_spare_rows_sufficient_for_full_pc00_pc14": sequence_summary["existing_placeholder_capacity_sufficient_full"],
        "quartet_shipped_contiguous_append_rows": sequence_summary["quartet_only_contiguous_append"],
        "proposed_append_range_collision_free": sequence_summary["proposed_range_collision_free"],
        "proposed_string_no_start": sequence_summary["proposed_append_start"],
        "proposed_string_no_end": sequence_summary["proposed_append_end"],
        "append_only_candidate_build_allowed": safe_append_build,
        "candidate_installation_allowed": False,
        "runtime_validation_allowed": False,
        "existing_costume_replacement_allowed": False,
        "global_show_all_allowed": False,
        "binding_to_bkn_runtime_records_proven": False,
        "fallback_if_probe_fails": "controlled PCxx_DLC_BKN namespace list insertion or availability-filter bypass",
    }
    write_json(output_dir / "BKN_SYNTHETIC_LABEL_SLOT_ACCEPTANCE.json", acceptance)

    summary = {
        "type": "br_quartet_legacy_dlc_bkn_synthetic_label_slot_audit",
        "format_version": 1,
        "tool_version": TOOL_VERSION,
        "status": decision_status,
        "generation8": EXPECTED_GENERATION,
        "members": EXPECTED_MEMBERS,
        "stage101_detector_corrected": True,
        "bkn_distinct_family": bkn_distinct_family,
        "pc00_family_stride": delta_pattern,
        **sequence_summary,
        "installation_all_baseline": all_baseline,
        "append_only_candidate_build_allowed": safe_append_build,
        "candidate_built": False,
        "active_manifest_modified": False,
        "game_files_modified": False,
        "save_files_modified": False,
        "prepare_called": False,
        "commit_called": False,
        "runtime_validation_performed": False,
        "required_next_action": (
            "build and canonical-preview an append-only generation-9 label candidate; do not install it"
            if safe_append_build
            else "resolve the failed synthetic-slot checks before any candidate build"
        ),
    }
    write_json(output_dir / "SUMMARY.json", summary)
    report_manifest(output_dir)
    return summary


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-root", required=True)
    parser.add_argument("--game-dir", required=True)
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args()
    try:
        summary = run(
            Path(args.project_root).resolve(),
            Path(args.game_dir).resolve(),
            Path(args.output_dir).resolve(),
        )
    except (AuditError, OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}", file=__import__("sys").stderr)
        return 1
    print(f"Status: {summary['status']}")
    print(f"Append-only candidate build allowed: {str(summary['append_only_candidate_build_allowed']).lower()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
