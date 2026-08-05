#!/usr/bin/env python3
"""Correct focal slot-light record identity before any semantic interpretation.

Stage 91 correctly inventoried 177 section-header reference records, but its
cross-context transition interpretation treated one 150/150 record in the
neutral member as the source counterpart of a different 75/75 record. The
neutral member actually contains both variants at stable offsets in both
Original and Quartet. This metadata-only stage reconstructs every 11-dword
record from the stage-91 report, separates template identity from occurrence
identity, and audits the candidate PC02 family as an ordered sequence.

No G1E/G1EM, Elixir, PAK, registry or installed-game payload is written. The
stage does not infer brightness, censorship, timing, scale or intensity.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import subprocess
import sys
from collections import Counter, defaultdict
from pathlib import Path, PurePosixPath
from typing import Any, Iterable, Mapping, Sequence

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT_DEFAULT = SCRIPT_DIR.parent.parent

TOOL_VERSION = "0.1.6"
REPORT_NAME = "BR_quartet_restoration_reflector_slot_light_record_occurrence_identity_evidence.tar.zst"
REPORT_DIR = "reflector_slot_light_record_occurrence_identity_evidence"
STAGE91_DIR = "reflector_slot_light_section_cardinality_record_role_evidence"
STAGE91_ARCHIVE = "BR_quartet_restoration_reflector_slot_light_section_cardinality_record_role_evidence.tar.zst"
EXPECTED_REFERENCE_ROWS = 177
EXPECTED_DWORD_ROWS = EXPECTED_REFERENCE_ROWS * 11
EXPECTED_TEMPLATE_GROUP_ROWS = 116
EXPECTED_CLUSTER_MEMBERS = 4
RECORD_DWORDS = 11
RELOCATION_DWORD = 10
LEAF_DWORDS = (0, 1)


class Stage92Error(RuntimeError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise Stage92Error(message)


def progress(message: str) -> None:
    print(f"[stage92] {message}", file=sys.stderr, flush=True)


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


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def load_json(path: Path) -> dict[str, Any]:
    require(path.is_file(), f"missing required JSON: {path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise Stage92Error(f"invalid JSON {path}: {exc}") from exc
    require(isinstance(value, dict), f"JSON root must be object: {path}")
    return value


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


def masked_hash(words: Sequence[int], masked_dwords: Sequence[int]) -> str:
    masked = set(masked_dwords)
    payload = b"".join((0 if index in masked else int(value) & 0xFFFFFFFF).to_bytes(4, "little") for index, value in enumerate(words))
    return sha256(payload)


def variant_label(words: Sequence[int], float_values: Sequence[str]) -> str:
    if len(float_values) >= 2 and float_values[0] and float_values[0] == float_values[1]:
        return f"equal_float_{float_values[0]}"
    return f"leaf_hex_{words[0] & 0xFFFFFFFF:08x}_{words[1] & 0xFFFFFFFF:08x}"


def stable_key(row: Mapping[str, Any]) -> tuple[str, str, str, int]:
    return (
        str(row.get("normalized_path", "")).casefold(),
        str(row.get("member_key", "")).casefold(),
        str(row.get("side", "")).casefold(),
        parse_int(row.get("reference_offset"), -1),
    )


def validate_stage91(root: Path) -> dict[str, Any]:
    summary = load_json(root / "SUMMARY.json")
    require(summary.get("type") == "br_quartet_restoration_reflector_slot_light_section_cardinality_record_role_evidence_summary", "stage91 type mismatch")
    require(summary.get("tool_version") == "0.1.5", "stage91 tool version mismatch")
    require(parse_int(summary.get("sibling_G1E_G1EM_member_rows"), -1) == 540, "stage91 sibling count mismatch")
    require(parse_int(summary.get("reference_cluster_member_rows"), -1) == EXPECTED_CLUSTER_MEMBERS, "stage91 cluster-member count mismatch")
    require(parse_int(summary.get("reference_record_rows"), -1) == EXPECTED_REFERENCE_ROWS, "stage91 reference-record count mismatch")
    require(parse_int(summary.get("reference_record_dword_rows"), -1) == EXPECTED_DWORD_ROWS, "stage91 dword count mismatch")
    require(parse_int(summary.get("reference_record_template_group_rows"), -1) == EXPECTED_TEMPLATE_GROUP_ROWS, "stage91 template-group count mismatch")
    require(parse_int(summary.get("focal_source_template_occurrence_rows"), -1) == 2, "stage91 focal source occurrence count mismatch")
    require(parse_int(summary.get("focal_target_template_occurrence_rows"), -1) == 3, "stage91 focal target occurrence count mismatch")
    require(parse_int(summary.get("shared_record_transition_context_rows"), -1) == 2, "stage91 focal context count mismatch")
    require(parse_bool(summary.get("shared_record_transition_independent_of_section_count_delta")), "stage91 transition/cardinality test missing")
    require(summary.get("resolved_reference_origin") == "dword_start_relative", "stage91 reference origin mismatch")
    require(parse_int(summary.get("prototype_candidate_rows"), -1) == 0, "stage91 unexpectedly authorized prototype")
    require(not parse_bool(summary.get("brightness_semantics_confirmed")), "stage91 unexpectedly confirmed brightness")
    require(not parse_bool(summary.get("censorship_semantics_confirmed")), "stage91 unexpectedly confirmed censorship")
    require(parse_int(summary.get("skipped_rows"), -1) == 0, "stage91 contains skipped rows")
    return summary


def common_prefix(left: Sequence[str], right: Sequence[str]) -> int:
    count = 0
    for a, b in zip(left, right):
        if a != b:
            break
        count += 1
    return count


def common_suffix(left: Sequence[str], right: Sequence[str], prefix: int) -> int:
    count = 0
    max_count = min(len(left), len(right)) - prefix
    while count < max_count and left[len(left) - 1 - count] == right[len(right) - 1 - count]:
        count += 1
    return count


def build_report(
    project_root: Path,
    *,
    create_archive: bool = True,
    report_root: Path | None = None,
    workspace_root: Path | None = None,
) -> tuple[Path, Path | None, dict[str, Any]]:
    project_root = project_root.resolve()
    reports = (report_root or project_root / ".local/reports/quartet_restoration").resolve()
    workspace = (workspace_root or project_root / ".local/build/quartet_restoration/stage92_record_occurrence_identity").resolve()
    reports.mkdir(parents=True, exist_ok=True)
    workspace.mkdir(parents=True, exist_ok=True)

    progress("validating stage-91 metadata report")
    stage91 = locate(reports, STAGE91_DIR, STAGE91_ARCHIVE, workspace / "stage91")
    summary91 = validate_stage91(stage91)
    template_rows = read_tsv(stage91 / "SLOT_LIGHT_REFERENCE_RECORD_TEMPLATES.tsv")
    dword_rows = read_tsv(stage91 / "SLOT_LIGHT_REFERENCE_RECORD_DWORDS.tsv")
    transition_rows = read_tsv(stage91 / "SLOT_LIGHT_SHARED_RECORD_TRANSITION_CARDINALITY.tsv")
    cardinality_rows = read_tsv(stage91 / "SLOT_LIGHT_SECTION_CARDINALITY.tsv")
    require(len(template_rows) == EXPECTED_REFERENCE_ROWS, "stage91 template row count mismatch")
    require(len(dword_rows) == EXPECTED_DWORD_ROWS, "stage91 dword row count mismatch")
    require(len(transition_rows) == 2, "stage91 focal transition row count mismatch")

    transition_pairs = {row.get("shared_transition_hash_pair", "") for row in transition_rows}
    require(len(transition_pairs) == 1, "stage91 focal hash pairs differ")
    source_template_hash = transition_rows[0].get("source_record_masked_sha256", "")
    target_template_hash = transition_rows[0].get("target_record_masked_sha256", "")
    require(len(source_template_hash) == 64 and len(target_template_hash) == 64 and source_template_hash != target_template_hash, "invalid focal template hashes")

    progress("reconstructing 177 reference-record images from technical dwords")
    dwords_by_key: dict[tuple[str, str, str, int], dict[int, dict[str, str]]] = defaultdict(dict)
    for row in dword_rows:
        key = stable_key(row)
        relative = parse_int(row.get("relative_dword"), -1)
        require(0 <= relative < RECORD_DWORDS, f"invalid relative dword: {relative}")
        require(relative not in dwords_by_key[key], f"duplicate dword {relative} for {key}")
        dwords_by_key[key][relative] = row

    records: list[dict[str, Any]] = []
    template_by_key = {stable_key(row): row for row in template_rows}
    require(len(template_by_key) == EXPECTED_REFERENCE_ROWS, "duplicate stage91 template identity")
    for key, template in sorted(template_by_key.items()):
        rows = dwords_by_key.get(key, {})
        require(set(rows) == set(range(RECORD_DWORDS)), f"incomplete record dwords for {key}")
        words = [parse_int(rows[index].get("u32_hex"), -1) for index in range(RECORD_DWORDS)]
        require(all(value >= 0 for value in words), f"invalid record dword for {key}")
        relocation_masked = masked_hash(words, [RELOCATION_DWORD])
        require(relocation_masked == template.get("masked_template_sha256"), f"template hash mismatch for {key}")
        family_hash = masked_hash(words, [*LEAF_DWORDS, RELOCATION_DWORD])
        float_values = [rows[index].get("float32", "") for index in LEAF_DWORDS]
        record = {
            **template,
            "reference_offset": parse_int(template.get("reference_offset"), -1),
            "record_start": parse_int(template.get("record_start"), -1),
            "masked_template_sha256": relocation_masked,
            "family_core_sha256": family_hash,
            "leaf0_u32_hex": f"0x{words[0] & 0xFFFFFFFF:08x}",
            "leaf1_u32_hex": f"0x{words[1] & 0xFFFFFFFF:08x}",
            "leaf0_float32": float_values[0],
            "leaf1_float32": float_values[1],
            "variant_label": variant_label(words, float_values),
            "words": words,
        }
        records.append(record)

    by_member_side_offset = {
        (row["normalized_path"].casefold(), row["member_key"].casefold(), row["side"], row["record_start"]): row
        for row in records
    }
    for row in records:
        other_side = "target" if row["side"] == "source" else "source"
        peer = by_member_side_offset.get((row["normalized_path"].casefold(), row["member_key"].casefold(), other_side, row["record_start"]))
        exact = bool(peer and peer["masked_template_sha256"] == row["masked_template_sha256"])
        row["exact_same_offset_peer"] = exact
        row["exact_same_offset_peer_side"] = other_side if exact else ""
        row["exact_same_offset_peer_reference_offset"] = peer["reference_offset"] if exact and peer else ""

    focal_records = [row for row in records if row["masked_template_sha256"] in {source_template_hash, target_template_hash}]
    focal_family_hashes = {row["family_core_sha256"] for row in focal_records}
    require(len(focal_family_hashes) == 1, "focal templates do not share one leaf-masked family")
    focal_family_hash = next(iter(focal_family_hashes))

    role_rows = {row["island_role"]: row for row in transition_rows}
    require(set(role_rows) == {"candidate_ringlight", "neutral_control"}, "unexpected focal roles")
    candidate_id = (role_rows["candidate_ringlight"]["normalized_path"].casefold(), role_rows["candidate_ringlight"]["member_key"].casefold())
    neutral_id = (role_rows["neutral_control"]["normalized_path"].casefold(), role_rows["neutral_control"]["member_key"].casefold())

    inventory_rows: list[dict[str, Any]] = []
    for row in records:
        member_id = (row["normalized_path"].casefold(), row["member_key"].casefold())
        inventory_rows.append({
            "cluster_role": row.get("cluster_role", ""),
            "normalized_path": row["normalized_path"],
            "member_key": row["member_key"],
            "member_name": row["member_name"],
            "side": row["side"],
            "reference_index": row.get("reference_index", ""),
            "reference_offset": row["reference_offset"],
            "record_start": row["record_start"],
            "masked_template_sha256": row["masked_template_sha256"],
            "family_core_sha256": row["family_core_sha256"],
            "leaf0_u32_hex": row["leaf0_u32_hex"],
            "leaf1_u32_hex": row["leaf1_u32_hex"],
            "leaf0_float32": row["leaf0_float32"],
            "leaf1_float32": row["leaf1_float32"],
            "variant_label": row["variant_label"],
            "is_focal_family": row["family_core_sha256"] == focal_family_hash,
            "is_stage91_source_template": row["masked_template_sha256"] == source_template_hash,
            "is_stage91_target_template": row["masked_template_sha256"] == target_template_hash,
            "member_focal_role": "candidate" if member_id == candidate_id else "neutral" if member_id == neutral_id else "control",
            "exact_same_offset_peer": row["exact_same_offset_peer"],
            "exact_same_offset_peer_side": row["exact_same_offset_peer_side"],
            "exact_same_offset_peer_reference_offset": row["exact_same_offset_peer_reference_offset"],
        })

    progress("auditing focal-family occurrence identity and ordered sequences")
    family_group_rows: list[dict[str, Any]] = []
    grouped: dict[tuple[str, str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in records:
        grouped[(row["normalized_path"], row["member_key"], row["member_name"], row["side"])].append(row)
    for (path, member_key, member_name, side), member_rows in sorted(grouped.items()):
        family_rows = sorted((row for row in member_rows if row["family_core_sha256"] == focal_family_hash), key=lambda row: row["reference_offset"])
        variants = [row["variant_label"] for row in family_rows]
        templates = [row["masked_template_sha256"] for row in family_rows]
        family_group_rows.append({
            "normalized_path": path,
            "member_key": member_key,
            "member_name": member_name,
            "side": side,
            "focal_family_occurrence_rows": len(family_rows),
            "ordered_variant_sequence": " | ".join(variants),
            "ordered_template_sequence": " | ".join(templates),
            "stage91_source_template_rows": sum(row["masked_template_sha256"] == source_template_hash for row in family_rows),
            "stage91_target_template_rows": sum(row["masked_template_sha256"] == target_template_hash for row in family_rows),
            "exact_same_offset_peer_rows": sum(bool(row["exact_same_offset_peer"]) for row in family_rows),
        })

    def member_side_records(member_id: tuple[str, str], side: str) -> list[dict[str, Any]]:
        return sorted(
            [row for row in records if (row["normalized_path"].casefold(), row["member_key"].casefold()) == member_id and row["side"] == side and row["family_core_sha256"] == focal_family_hash],
            key=lambda row: row["reference_offset"],
        )

    neutral_source = member_side_records(neutral_id, "source")
    neutral_target = member_side_records(neutral_id, "target")
    candidate_source = member_side_records(candidate_id, "source")
    candidate_target = member_side_records(candidate_id, "target")
    require(neutral_source and neutral_target and candidate_source and candidate_target, "missing focal family sequences")

    neutral_source_template_source = [row for row in neutral_source if row["masked_template_sha256"] == source_template_hash]
    neutral_source_template_target = [row for row in neutral_target if row["masked_template_sha256"] == source_template_hash]
    neutral_target_template_source = [row for row in neutral_source if row["masked_template_sha256"] == target_template_hash]
    neutral_target_template_target = [row for row in neutral_target if row["masked_template_sha256"] == target_template_hash]
    require(len(neutral_source_template_source) == len(neutral_source_template_target) == 1, "neutral source-template occurrence mismatch")
    require(len(neutral_target_template_source) == len(neutral_target_template_target) == 1, "neutral target-template occurrence mismatch")
    source_variant_stable = neutral_source_template_source[0]["record_start"] == neutral_source_template_target[0]["record_start"]
    target_variant_stable = neutral_target_template_source[0]["record_start"] == neutral_target_template_target[0]["record_start"]
    require(source_variant_stable and target_variant_stable, "neutral focal variants are not stable at the same offsets")

    cohabitation_rows = []
    for label, source_rows, target_rows in (
        ("stage91_source_template", neutral_source_template_source, neutral_source_template_target),
        ("stage91_target_template", neutral_target_template_source, neutral_target_template_target),
    ):
        source_row, target_row = source_rows[0], target_rows[0]
        cohabitation_rows.append({
            "member_role": "neutral_control",
            "normalized_path": source_row["normalized_path"],
            "member_key": source_row["member_key"],
            "member_name": source_row["member_name"],
            "variant_role": label,
            "masked_template_sha256": source_row["masked_template_sha256"],
            "variant_label": source_row["variant_label"],
            "source_record_start": source_row["record_start"],
            "target_record_start": target_row["record_start"],
            "source_reference_offset": source_row["reference_offset"],
            "target_reference_offset": target_row["reference_offset"],
            "same_record_start": source_row["record_start"] == target_row["record_start"],
            "same_reference_offset": source_row["reference_offset"] == target_row["reference_offset"],
            "exact_occurrence_stable": source_row["record_start"] == target_row["record_start"] and source_row["masked_template_sha256"] == target_row["masked_template_sha256"],
        })

    source_hashes = [row["masked_template_sha256"] for row in candidate_source]
    target_hashes = [row["masked_template_sha256"] for row in candidate_target]
    prefix = common_prefix(source_hashes, target_hashes)
    suffix = common_suffix(source_hashes, target_hashes, prefix)
    source_middle = candidate_source[prefix:len(candidate_source) - suffix if suffix else len(candidate_source)]
    target_middle = candidate_target[prefix:len(candidate_target) - suffix if suffix else len(candidate_target)]
    require(len(source_middle) == 1 and len(target_middle) == 2, "unexpected candidate focal-family middle interval")
    require(source_middle[0]["masked_template_sha256"] == source_template_hash, "candidate middle source is not stage91 source template")
    require(all(row["masked_template_sha256"] == target_template_hash for row in target_middle), "candidate middle target rows are not duplicate stage91 target templates")

    alignment_rows: list[dict[str, Any]] = []
    for side, sequence in (("source", candidate_source), ("target", candidate_target)):
        for index, row in enumerate(sequence):
            region = "prefix" if index < prefix else "suffix" if suffix and index >= len(sequence) - suffix else "middle"
            alignment_rows.append({
                "member_role": "candidate_ringlight",
                "normalized_path": row["normalized_path"],
                "member_key": row["member_key"],
                "member_name": row["member_name"],
                "side": side,
                "family_sequence_index": index,
                "alignment_region": region,
                "reference_offset": row["reference_offset"],
                "record_start": row["record_start"],
                "masked_template_sha256": row["masked_template_sha256"],
                "variant_label": row["variant_label"],
            })

    edit_model_rows = [
        {
            "model_id": "minimal_substitute_to_first_then_insert_second",
            "source_middle_variants": source_middle[0]["variant_label"],
            "target_middle_variants": " | ".join(row["variant_label"] for row in target_middle),
            "substitution_rows": 1,
            "insertion_rows": 1,
            "deletion_rows": 0,
            "edit_cost": 2,
            "continuing_target_middle_index": 0,
            "minimal_edit_model": True,
            "occurrence_identity_resolved": False,
            "classification": "one possible minimum-cost alignment; duplicate target templates prevent identity resolution",
        },
        {
            "model_id": "minimal_insert_first_then_substitute_to_second",
            "source_middle_variants": source_middle[0]["variant_label"],
            "target_middle_variants": " | ".join(row["variant_label"] for row in target_middle),
            "substitution_rows": 1,
            "insertion_rows": 1,
            "deletion_rows": 0,
            "edit_cost": 2,
            "continuing_target_middle_index": 1,
            "minimal_edit_model": True,
            "occurrence_identity_resolved": False,
            "classification": "equally valid minimum-cost alignment; duplicate target templates prevent identity resolution",
        },
        {
            "model_id": "remove_source_then_insert_two_targets",
            "source_middle_variants": source_middle[0]["variant_label"],
            "target_middle_variants": " | ".join(row["variant_label"] for row in target_middle),
            "substitution_rows": 0,
            "insertion_rows": 2,
            "deletion_rows": 1,
            "edit_cost": 3,
            "continuing_target_middle_index": "",
            "minimal_edit_model": False,
            "occurrence_identity_resolved": False,
            "classification": "non-minimal but structurally possible without external binding evidence",
        },
    ]

    correction_rows = [
        {
            "prior_scope": "neutral_control_stage87_to_stage91_pairing",
            "prior_source_template_sha256": source_template_hash,
            "prior_target_template_sha256": target_template_hash,
            "prior_interpretation": "source-to-target record transition in neutral control",
            "new_source_exact_target_counterpart_start": neutral_source_template_target[0]["record_start"],
            "new_target_exact_source_counterpart_start": neutral_target_template_source[0]["record_start"],
            "source_variant_stable_across_versions": source_variant_stable,
            "target_variant_stable_across_versions": target_variant_stable,
            "neutral_transition_supported": False,
            "corrected_classification": "cross_occurrence_pairing_from_local_change_island_alignment; both variants coexist unchanged",
        }
    ]

    cardinality_by_id = {(row["normalized_path"].casefold(), row["member_key"].casefold()): row for row in cardinality_rows}
    candidate_cardinality = cardinality_by_id.get(candidate_id)
    neutral_cardinality = cardinality_by_id.get(neutral_id)
    require(candidate_cardinality is not None and neutral_cardinality is not None, "missing focal cardinality rows")

    skipped_rows: list[dict[str, Any]] = []
    output = reports / REPORT_DIR
    if output.exists():
        import shutil
        shutil.rmtree(output)
    output.mkdir(parents=True)

    write_tsv(output / "SLOT_LIGHT_RECORD_OCCURRENCE_INVENTORY.tsv", [
        "cluster_role", "normalized_path", "member_key", "member_name", "side", "reference_index",
        "reference_offset", "record_start", "masked_template_sha256", "family_core_sha256",
        "leaf0_u32_hex", "leaf1_u32_hex", "leaf0_float32", "leaf1_float32", "variant_label",
        "is_focal_family", "is_stage91_source_template", "is_stage91_target_template", "member_focal_role",
        "exact_same_offset_peer", "exact_same_offset_peer_side", "exact_same_offset_peer_reference_offset",
    ], inventory_rows)
    write_tsv(output / "SLOT_LIGHT_RECORD_FAMILY_SEQUENCES.tsv", [
        "normalized_path", "member_key", "member_name", "side", "focal_family_occurrence_rows",
        "ordered_variant_sequence", "ordered_template_sequence", "stage91_source_template_rows",
        "stage91_target_template_rows", "exact_same_offset_peer_rows",
    ], family_group_rows)
    write_tsv(output / "SLOT_LIGHT_NEUTRAL_VARIANT_COHABITATION.tsv", [
        "member_role", "normalized_path", "member_key", "member_name", "variant_role",
        "masked_template_sha256", "variant_label", "source_record_start", "target_record_start",
        "source_reference_offset", "target_reference_offset", "same_record_start", "same_reference_offset",
        "exact_occurrence_stable",
    ], cohabitation_rows)
    write_tsv(output / "SLOT_LIGHT_CANDIDATE_FAMILY_SEQUENCE_ALIGNMENT.tsv", [
        "member_role", "normalized_path", "member_key", "member_name", "side", "family_sequence_index",
        "alignment_region", "reference_offset", "record_start", "masked_template_sha256", "variant_label",
    ], alignment_rows)
    write_tsv(output / "SLOT_LIGHT_CANDIDATE_EDIT_MODELS.tsv", [
        "model_id", "source_middle_variants", "target_middle_variants", "substitution_rows",
        "insertion_rows", "deletion_rows", "edit_cost", "continuing_target_middle_index",
        "minimal_edit_model", "occurrence_identity_resolved", "classification",
    ], edit_model_rows)
    write_tsv(output / "SLOT_LIGHT_PRIOR_ALIGNMENT_CORRECTION.tsv", [
        "prior_scope", "prior_source_template_sha256", "prior_target_template_sha256", "prior_interpretation",
        "new_source_exact_target_counterpart_start", "new_target_exact_source_counterpart_start",
        "source_variant_stable_across_versions", "target_variant_stable_across_versions",
        "neutral_transition_supported", "corrected_classification",
    ], correction_rows)
    write_tsv(output / "SLOT_LIGHT_RECORD_OCCURRENCE_IDENTITY_SKIPPED.tsv", ["scope", "member_name", "side", "offset", "reason"], skipped_rows)

    minimal_models = [row for row in edit_model_rows if row["minimal_edit_model"]]
    summary: dict[str, Any] = {
        "type": "br_quartet_restoration_reflector_slot_light_record_occurrence_identity_evidence_summary",
        "format_version": 1,
        "tool_version": TOOL_VERSION,
        "source_stage91_tool_version": summary91.get("tool_version"),
        "status": "stage91_structural_inventory_valid_neutral_cross_occurrence_transition_interpretation_corrected_candidate_duplicate_target_identity_unresolved",
        "reference_record_rows": len(records),
        "reference_record_dword_rows": len(dword_rows),
        "reference_cluster_member_rows": EXPECTED_CLUSTER_MEMBERS,
        "focal_family_sha256": focal_family_hash,
        "stage91_source_template_occurrence_rows_all_sides": sum(row["masked_template_sha256"] == source_template_hash for row in records),
        "stage91_target_template_occurrence_rows_all_sides": sum(row["masked_template_sha256"] == target_template_hash for row in records),
        "neutral_source_template_stable_occurrence_rows": int(source_variant_stable),
        "neutral_target_template_stable_occurrence_rows": int(target_variant_stable),
        "neutral_focal_variants_coexist_unchanged": source_variant_stable and target_variant_stable,
        "neutral_150_to_75_transition_supported": False,
        "prior_cross_context_record_migration_confirmed": False,
        "prior_transition_interpretation_corrected": True,
        "candidate_section_count_delta": parse_int(candidate_cardinality.get("count_delta"), 0),
        "neutral_section_count_delta": parse_int(neutral_cardinality.get("count_delta"), 0),
        "candidate_focal_family_source_occurrence_rows": len(candidate_source),
        "candidate_focal_family_target_occurrence_rows": len(candidate_target),
        "candidate_family_common_prefix_rows": prefix,
        "candidate_family_common_suffix_rows": suffix,
        "candidate_family_middle_source_rows": len(source_middle),
        "candidate_family_middle_target_rows": len(target_middle),
        "candidate_middle_source_variant": source_middle[0]["variant_label"],
        "candidate_middle_target_variant": target_middle[0]["variant_label"],
        "candidate_middle_target_duplicate_rows": len(target_middle),
        "candidate_minimum_sequence_edit_cost": min(parse_int(row["edit_cost"], 999) for row in edit_model_rows),
        "candidate_minimum_edit_model_rows": len(minimal_models),
        "candidate_target_occurrence_identity_resolved": False,
        "record_family_variant_values_confirmed": True,
        "technical_leaf_semantics_resolved": False,
        "prototype_candidate_rows": 0,
        "brightness_semantics_confirmed": False,
        "censorship_semantics_confirmed": False,
        "skipped_rows": len(skipped_rows),
        "parameters": {
            "record_dwords": RECORD_DWORDS,
            "relocation_dword": RELOCATION_DWORD,
            "variant_leaf_dwords": list(LEAF_DWORDS),
            "template_identity_mask": "relocation dword 10 only",
            "family_identity_mask": "leaf dwords 0 and 1 plus relocation dword 10",
            "sequence_order": "ascending reference offset within member/side/family",
            "occurrence_identity_rule": "same member, same record start, same relocation-masked template",
        },
        "policy": {
            "installed_game_modified": False,
            "render_payload_written": False,
            "event_payload_written": False,
            "pak_repacked": False,
            "core_registry_modified": False,
            "profile_activated": False,
            "runtime_validation_inferred": False,
            "censorship_semantics_inferred": False,
            "brightness_semantics_inferred": False,
            "record_numeric_leaf_semantics_inferred": False,
            "canary_track_modified": False,
            "full_proprietary_payloads_exported": False,
        },
        "next_action": "Upload this report. The neutral member must no longer be used as evidence of a 150-to-75 migration because both variants coexist unchanged. Continue only with a read-only section-table/reference-to-record binding audit to distinguish the added PC02 target occurrence from the unresolved continuation occurrence; do not write G1E or infer brightness/censorship.",
    }
    (output / "SUMMARY.json").write_text(json.dumps(summary, indent=2, sort_keys=False) + "\n", encoding="utf-8")

    archive = reports / REPORT_NAME if create_archive else None
    if archive is not None:
        progress("creating compressed metadata-only report archive")
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
    except Stage92Error as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print(f"Report directory: {output}")
    if archive is not None:
        print(f"Report archive: {archive}")
    print(f"Neutral variants coexist unchanged: {summary['neutral_focal_variants_coexist_unchanged']}")
    print(f"Candidate occurrence identity resolved: {summary['candidate_target_occurrence_identity_resolved']}")
    print(f"Prototype candidates: {summary['prototype_candidate_rows']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
