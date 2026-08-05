#!/usr/bin/env python3
"""Compare paired-float values only inside exact source-target section-layout classes.

Stage 109 exported 999 section-anchored layout rows and 1,814 exact record
occurrences.  This metadata-only stage pairs a source and target section only
when normalized path, member key and the exact section-anchored layout signature
match uniquely.  Values are then compared at the same template ordinal and
relative offset.

The stage does not interpret the numeric domain, does not compare unmatched
layout classes, and cannot authorize a G1E/G1EM write or prototype.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import subprocess
import tempfile
from collections import Counter, defaultdict
from pathlib import Path, PurePosixPath
from typing import Any, Iterable, Mapping, Sequence

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT_DEFAULT = SCRIPT_DIR.parent.parent
TOOL_VERSION = "0.1.24"
REPORT_NAME = "BR_quartet_restoration_reflector_slot_light_identical_layout_value_transition_evidence.tar.zst"
REPORT_DIR = "reflector_slot_light_identical_layout_value_transition_evidence"
STAGE109_DIR = "reflector_slot_light_sibling_section_layout_evidence"
STAGE109_ARCHIVE = "BR_quartet_restoration_reflector_slot_light_sibling_section_layout_evidence.tar.zst"
EXPECTED_OCCURRENCES = 1814
EXPECTED_SECTIONS = 999
EXPECTED_PAIRS = 540


class Stage110Error(RuntimeError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise Stage110Error(message)


def parse_int(value: Any, default: int = 0) -> int:
    try:
        text = str(value).strip()
        return int(text, 16) if text.casefold().startswith("0x") else int(text)
    except (TypeError, ValueError):
        return default


def parse_bool(value: Any) -> bool:
    return str(value).strip().casefold() in {"1", "true", "yes", "y"}


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
        raise Stage110Error(f"invalid JSON {path}: {exc}") from exc
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


def validate_stage109(root: Path) -> dict[str, Any]:
    summary = load_json(root / "SUMMARY.json")
    require(summary.get("type") == "br_quartet_restoration_reflector_slot_light_sibling_section_layout_evidence_summary", "stage109 type mismatch")
    require(summary.get("tool_version") == "0.1.23", "stage109 tool version mismatch")
    require(parse_int(summary.get("sibling_G1E_G1EM_pair_rows"), -1) == EXPECTED_PAIRS, "stage109 pair count mismatch")
    require(parse_int(summary.get("revalidated_occurrence_rows"), -1) == EXPECTED_OCCURRENCES, "stage109 occurrence count mismatch")
    require(parse_int(summary.get("section_anchored_layout_rows"), -1) == EXPECTED_SECTIONS, "stage109 section count mismatch")
    require(parse_int(summary.get("skipped_rows"), -1) == 0, "stage109 contains skipped rows")
    require(not parse_bool(summary.get("technical_leaf_domain_semantics_resolved")), "stage109 unexpectedly resolved value semantics")
    require(parse_int(summary.get("prototype_candidate_rows"), -1) == 0, "stage109 unexpectedly authorized a prototype")
    policy = summary.get("policy")
    require(isinstance(policy, dict), "stage109 policy missing")
    require(parse_bool(policy.get("official_nonunderscore_archives_are_canonical")), "stage109 canonical-source policy mismatch")
    require(not parse_bool(policy.get("underscore_archives_required")), "stage109 still requires underscore archives")
    return summary


def section_identity(row: Mapping[str, Any]) -> tuple[str, str, str, int]:
    return (
        str(row.get("normalized_path", "")).casefold(),
        str(row.get("member_key", "")).casefold(),
        str(row.get("side", "")),
        parse_int(row.get("normalized_endpoint"), -1),
    )


def layout_class_identity(row: Mapping[str, Any]) -> tuple[str, str, str]:
    return (
        str(row.get("normalized_path", "")).casefold(),
        str(row.get("member_key", "")).casefold(),
        str(row.get("exact_section_anchored_layout_sha256", "")),
    )


def build_report(project_root: Path, *, create_archive: bool = True, report_root: Path | None = None) -> tuple[Path, Path | None, dict[str, Any]]:
    project_root = project_root.resolve()
    reports = (report_root or project_root / ".local/reports/quartet_restoration").resolve()
    require(reports.is_dir(), f"missing report root: {reports}")

    with tempfile.TemporaryDirectory(prefix="br-stage110-") as temporary_name:
        temporary = Path(temporary_name)
        stage109_root = locate(reports, STAGE109_DIR, STAGE109_ARCHIVE, temporary / "109")
        summary109 = validate_stage109(stage109_root)
        section_rows = read_tsv(stage109_root / "SLOT_LIGHT_SIBLING_SECTION_ANCHORED_LAYOUTS.tsv")
        occurrence_rows = read_tsv(stage109_root / "SLOT_LIGHT_SIBLING_SECTION_LAYOUT_OCCURRENCES.tsv")
        require(len(section_rows) == EXPECTED_SECTIONS, "stage109 section table length mismatch")
        require(len(occurrence_rows) == EXPECTED_OCCURRENCES, "stage109 occurrence table length mismatch")

        sections_by_identity: dict[tuple[str, str, str, int], dict[str, str]] = {}
        for row in section_rows:
            identity = section_identity(row)
            require(identity not in sections_by_identity, f"duplicate section identity: {identity}")
            sections_by_identity[identity] = row

        occurrences_by_section: dict[tuple[str, str, str, int], list[dict[str, str]]] = defaultdict(list)
        occurrence_identities: set[tuple[str, str, str, int]] = set()
        for row in occurrence_rows:
            identity = (
                str(row.get("normalized_path", "")).casefold(),
                str(row.get("member_key", "")).casefold(),
                str(row.get("side", "")),
                parse_int(row.get("record_start"), -1),
            )
            require(identity not in occurrence_identities, f"duplicate occurrence identity: {identity}")
            occurrence_identities.add(identity)
            section_key = section_identity(row)
            require(section_key in sections_by_identity, f"occurrence references unknown section: {section_key}")
            occurrences_by_section[section_key].append(row)

        for section_key, section in sections_by_identity.items():
            rows = occurrences_by_section.get(section_key, [])
            rows.sort(key=lambda item: parse_int(item.get("template_ordinal_within_section"), -1))
            expected = parse_int(section.get("template_occurrences_in_section"), -1)
            require(len(rows) == expected, f"section occurrence count mismatch: {section_key}")
            require([parse_int(row.get("template_ordinal_within_section"), -1) for row in rows] == list(range(expected)), f"non-contiguous template ordinals: {section_key}")
            relative_offsets = ";".join(str(parse_int(row.get("record_relative_offset"), -1)) for row in rows)
            values = ";".join(str(row.get("paired_float_value", "")) for row in rows)
            require(relative_offsets == str(section.get("template_relative_offsets", "")), f"relative-offset vector mismatch: {section_key}")
            require(values == str(section.get("template_values_in_order", "")), f"value vector mismatch: {section_key}")

        classes: dict[tuple[str, str, str], dict[str, list[dict[str, str]]]] = defaultdict(lambda: {"source": [], "target": []})
        for row in section_rows:
            side = str(row.get("side", ""))
            require(side in {"source", "target"}, f"unexpected side: {side}")
            classes[layout_class_identity(row)][side].append(row)

        class_rows: list[dict[str, Any]] = []
        transition_rows: list[dict[str, Any]] = []
        skipped_rows: list[dict[str, Any]] = []

        for class_key, sides in sorted(classes.items()):
            source = sorted(sides["source"], key=lambda item: parse_int(item.get("normalized_endpoint"), -1))
            target = sorted(sides["target"], key=lambda item: parse_int(item.get("normalized_endpoint"), -1))
            if source and target and len(source) == 1 and len(target) == 1:
                classification = "shared_unique_identical_layout_class"
            elif source and not target:
                classification = "source_only_layout_class"
            elif target and not source:
                classification = "target_only_layout_class"
            else:
                classification = "ambiguous_duplicate_identical_layout_class"
                skipped_rows.append({
                    "normalized_path": class_key[0],
                    "member_key": class_key[1],
                    "exact_section_anchored_layout_sha256": class_key[2],
                    "source_section_rows": len(source),
                    "target_section_rows": len(target),
                    "reason": "non_unique_source_target_layout_class",
                })

            representative = (source or target)[0]
            class_rows.append({
                "normalized_path": class_key[0],
                "member_key": class_key[1],
                "member_name": representative.get("member_name", ""),
                "technical_member_role": representative.get("technical_member_role", ""),
                "character_slot": representative.get("character_slot", ""),
                "exact_section_anchored_layout_sha256": class_key[2],
                "section_mode_or_flag_word": representative.get("section_mode_or_flag_word", ""),
                "section_mode_or_flag_hex": representative.get("section_mode_or_flag_hex", ""),
                "section_count": representative.get("section_count", ""),
                "section_declared_span": representative.get("section_declared_span", ""),
                "template_relative_offsets": representative.get("template_relative_offsets", ""),
                "template_occurrences_in_section": representative.get("template_occurrences_in_section", ""),
                "template_coverage_of_section_count": representative.get("template_coverage_of_section_count", ""),
                "source_section_rows": len(source),
                "target_section_rows": len(target),
                "classification": classification,
            })

            if classification != "shared_unique_identical_layout_class":
                continue

            source_section = source[0]
            target_section = target[0]
            structural_fields = [
                "section_mode_or_flag_word", "section_count", "section_declared_span",
                "section_table_boundary_1", "section_table_boundary_2", "section_table_boundary_3",
                "template_relative_offsets", "template_occurrences_in_section",
                "template_coverage_of_section_count",
            ]
            for field in structural_fields:
                require(str(source_section.get(field, "")) == str(target_section.get(field, "")), f"identical layout class changed {field}: {class_key}")

            source_key = section_identity(source_section)
            target_key = section_identity(target_section)
            source_occurrences = occurrences_by_section[source_key]
            target_occurrences = occurrences_by_section[target_key]
            require(len(source_occurrences) == len(target_occurrences), f"identical layout occurrence count mismatch: {class_key}")

            for source_occurrence, target_occurrence in zip(source_occurrences, target_occurrences):
                source_ordinal = parse_int(source_occurrence.get("template_ordinal_within_section"), -1)
                target_ordinal = parse_int(target_occurrence.get("template_ordinal_within_section"), -1)
                source_offset = parse_int(source_occurrence.get("record_relative_offset"), -1)
                target_offset = parse_int(target_occurrence.get("record_relative_offset"), -1)
                require(source_ordinal == target_ordinal, f"ordinal mismatch in identical layout class: {class_key}")
                require(source_offset == target_offset, f"relative-offset mismatch in identical layout class: {class_key}")
                source_value = str(source_occurrence.get("paired_float_value", ""))
                target_value = str(target_occurrence.get("paired_float_value", ""))
                transition_rows.append({
                    "normalized_path": class_key[0],
                    "member_key": class_key[1],
                    "member_name": source_section.get("member_name", ""),
                    "technical_member_role": source_section.get("technical_member_role", ""),
                    "character_slot": source_section.get("character_slot", ""),
                    "exact_section_anchored_layout_sha256": class_key[2],
                    "section_mode_or_flag_word": source_section.get("section_mode_or_flag_word", ""),
                    "section_mode_or_flag_hex": source_section.get("section_mode_or_flag_hex", ""),
                    "section_count": source_section.get("section_count", ""),
                    "section_declared_span": source_section.get("section_declared_span", ""),
                    "template_coverage_of_section_count": source_section.get("template_coverage_of_section_count", ""),
                    "template_ordinal_within_section": source_ordinal,
                    "record_relative_offset": source_offset,
                    "source_record_start": source_occurrence.get("record_start", ""),
                    "target_record_start": target_occurrence.get("record_start", ""),
                    "source_paired_float_value": source_value,
                    "target_paired_float_value": target_value,
                    "classification": "stable_value_in_identical_layout" if source_value == target_value else "changed_value_in_identical_layout",
                })

        transition_counter = Counter((row["source_paired_float_value"], row["target_paired_float_value"]) for row in transition_rows)
        transition_distribution = []
        for (source_value, target_value), count in sorted(transition_counter.items(), key=lambda item: (float(item[0][0]), float(item[0][1]))):
            rows = [row for row in transition_rows if row["source_paired_float_value"] == source_value and row["target_paired_float_value"] == target_value]
            transition_distribution.append({
                "source_paired_float_value": source_value,
                "target_paired_float_value": target_value,
                "transition_rows": count,
                "member_rows": len({(row["normalized_path"], row["member_key"]) for row in rows}),
                "layout_class_rows": len({(row["normalized_path"], row["member_key"], row["exact_section_anchored_layout_sha256"]) for row in rows}),
                "section_mode_flags": ";".join(str(value) for value in sorted({parse_int(row["section_mode_or_flag_word"], -1) for row in rows})),
                "technical_member_roles": ";".join(sorted({str(row["technical_member_role"]) for row in rows})),
                "classification": "stable_transition_shape" if source_value == target_value else "changed_transition_shape",
            })

        mode_role_groups: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
        for row in transition_rows:
            mode_role_groups[(str(row["section_mode_or_flag_word"]), str(row["technical_member_role"]), str(row["template_coverage_of_section_count"]))].append(row)
        mode_role_rows = []
        for (mode, role, coverage), rows in sorted(mode_role_groups.items()):
            mode_role_rows.append({
                "section_mode_or_flag_word": mode,
                "section_mode_or_flag_hex": f"0x{parse_int(mode) & 0xffffffff:08x}",
                "technical_member_role": role,
                "template_coverage_of_section_count": coverage,
                "transition_rows": len(rows),
                "layout_class_rows": len({(row["normalized_path"], row["member_key"], row["exact_section_anchored_layout_sha256"]) for row in rows}),
                "paired_values": ";".join(sorted({str(row["source_paired_float_value"]) for row in rows}, key=float)),
                "changed_transition_rows": sum(row["classification"] == "changed_value_in_identical_layout" for row in rows),
                "classification": "identical_layout_mode_role_transition_group",
            })

        shared_classes = sum(row["classification"] == "shared_unique_identical_layout_class" for row in class_rows)
        source_only = sum(row["classification"] == "source_only_layout_class" for row in class_rows)
        target_only = sum(row["classification"] == "target_only_layout_class" for row in class_rows)
        ambiguous = sum(row["classification"] == "ambiguous_duplicate_identical_layout_class" for row in class_rows)
        stable_rows = sum(row["classification"] == "stable_value_in_identical_layout" for row in transition_rows)
        changed_rows = sum(row["classification"] == "changed_value_in_identical_layout" for row in transition_rows)

        decision_rows = [
            {"question": "were stage109 section and occurrence tables fully cross-validated", "answer": True, "classification": "999_sections_and_1814_occurrences_cross_validated"},
            {"question": "were shared exact layout classes uniquely pairable", "answer": ambiguous == 0, "classification": "all_shared_classes_unique" if ambiguous == 0 else "ambiguous_layout_classes_present"},
            {"question": "did any paired value change inside an exact identical layout class", "answer": changed_rows > 0, "classification": "changed_values_observed" if changed_rows > 0 else "no_changed_values_observed"},
            {"question": "does value stability prove that the paired leaves encode layout identity", "answer": False, "classification": "correlation_only_not_semantic_identity"},
            {"question": "were source-only or target-only layout classes used for semantic inference", "answer": False, "classification": "unmatched_layout_classes_excluded"},
            {"question": "does this authorize G1E G1EM write or prototype", "answer": False, "classification": "evidence_only_no_write"},
        ]

        output_root = reports / REPORT_DIR
        if output_root.exists():
            import shutil
            shutil.rmtree(output_root)
        output_root.mkdir(parents=True)
        write_tsv(output_root / "SLOT_LIGHT_IDENTICAL_LAYOUT_CLASSES.tsv", [
            "normalized_path", "member_key", "member_name", "technical_member_role", "character_slot",
            "exact_section_anchored_layout_sha256", "section_mode_or_flag_word", "section_mode_or_flag_hex",
            "section_count", "section_declared_span", "template_relative_offsets", "template_occurrences_in_section",
            "template_coverage_of_section_count", "source_section_rows", "target_section_rows", "classification",
        ], class_rows)
        write_tsv(output_root / "SLOT_LIGHT_IDENTICAL_LAYOUT_VALUE_TRANSITIONS.tsv", [
            "normalized_path", "member_key", "member_name", "technical_member_role", "character_slot",
            "exact_section_anchored_layout_sha256", "section_mode_or_flag_word", "section_mode_or_flag_hex",
            "section_count", "section_declared_span", "template_coverage_of_section_count",
            "template_ordinal_within_section", "record_relative_offset", "source_record_start", "target_record_start",
            "source_paired_float_value", "target_paired_float_value", "classification",
        ], transition_rows)
        write_tsv(output_root / "SLOT_LIGHT_IDENTICAL_LAYOUT_TRANSITION_DISTRIBUTION.tsv", [
            "source_paired_float_value", "target_paired_float_value", "transition_rows", "member_rows",
            "layout_class_rows", "section_mode_flags", "technical_member_roles", "classification",
        ], transition_distribution)
        write_tsv(output_root / "SLOT_LIGHT_IDENTICAL_LAYOUT_MODE_ROLE_DISTRIBUTION.tsv", [
            "section_mode_or_flag_word", "section_mode_or_flag_hex", "technical_member_role",
            "template_coverage_of_section_count", "transition_rows", "layout_class_rows", "paired_values",
            "changed_transition_rows", "classification",
        ], mode_role_rows)
        write_tsv(output_root / "SLOT_LIGHT_IDENTICAL_LAYOUT_SOURCE_TARGET_DECISION.tsv", ["question", "answer", "classification"], decision_rows)
        write_tsv(output_root / "SLOT_LIGHT_IDENTICAL_LAYOUT_VALUE_TRANSITION_SKIPPED.tsv", [
            "normalized_path", "member_key", "exact_section_anchored_layout_sha256", "source_section_rows",
            "target_section_rows", "reason",
        ], skipped_rows)

        summary = {
            "type": "br_quartet_restoration_reflector_slot_light_identical_layout_value_transition_evidence_summary",
            "format_version": 1,
            "tool_version": TOOL_VERSION,
            "source_stage109_tool_version": summary109.get("tool_version"),
            "stage109_section_rows": len(section_rows),
            "stage109_occurrence_rows": len(occurrence_rows),
            "layout_class_rows": len(class_rows),
            "shared_unique_identical_layout_class_rows": shared_classes,
            "source_only_layout_class_rows": source_only,
            "target_only_layout_class_rows": target_only,
            "ambiguous_duplicate_layout_class_rows": ambiguous,
            "matched_occurrence_transition_rows": len(transition_rows),
            "stable_value_transition_rows": stable_rows,
            "changed_value_transition_rows": changed_rows,
            "unique_transition_shapes": len(transition_distribution),
            "unique_changed_transition_shapes": sum(row["classification"] == "changed_transition_shape" for row in transition_distribution),
            "shared_section_mode_flag_rows": len({str(row["section_mode_or_flag_word"]) for row in transition_rows}),
            "prototype_candidate_rows": 0,
            "skipped_rows": len(skipped_rows),
            "technical_leaf_domain_semantics_resolved": False,
            "brightness_semantics_confirmed": False,
            "censorship_semantics_confirmed": False,
            "policy": {
                "official_nonunderscore_archives_are_canonical": True,
                "underscore_archives_required": False,
                "unmatched_layout_classes_used_for_semantics": False,
                "technical_leaf_domain_semantics_inferred": False,
                "brightness_semantics_inferred": False,
                "censorship_semantics_inferred": False,
                "render_payload_written": False,
                "profile_activated": False,
                "pak_repacked": False,
                "installed_game_modified": False,
            },
            "status": "identical_section_layout_value_transitions_audited_domain_semantics_unresolved",
            "next_action": "Upload this report. Continue only with a read-only insertion/deletion-aware normalization of source-only and target-only section-layout classes. Use the resolved PC02 first-target-75 insertion and second-target-75 continuation as a structural canary. Do not infer brightness/intensity and do not write G1E/G1EM.",
        }
        (output_root / "SUMMARY.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")

        archive_path = reports / REPORT_NAME if create_archive else None
        if archive_path is not None:
            make_archive(output_root, archive_path)
        return output_root, archive_path, summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path, default=PROJECT_ROOT_DEFAULT)
    parser.add_argument("--report-root", type=Path)
    parser.add_argument("--no-archive", action="store_true")
    args = parser.parse_args()
    try:
        output_root, archive, summary = build_report(args.project_root, create_archive=not args.no_archive, report_root=args.report_root)
    except Stage110Error as exc:
        print(f"ERROR: {exc}", file=os.sys.stderr)
        return 1
    print(f"Report directory: {output_root}")
    if archive is not None:
        print(f"Report archive: {archive}")
    print(f"Shared exact layout classes: {summary['shared_unique_identical_layout_class_rows']}")
    print(f"Matched value transitions: {summary['matched_occurrence_transition_rows']}")
    print(f"Changed transitions: {summary['changed_value_transition_rows']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
