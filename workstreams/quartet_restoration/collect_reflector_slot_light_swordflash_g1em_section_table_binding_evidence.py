#!/usr/bin/env python3
"""Audit G1EM and section-table topology for the final two swordflash identities.

Stage 116 leaves exactly two PC00 swordflash G1E pairs unresolved.  Each has
three source occurrences and two target occurrences, with deletion ordinal 1
and deletion ordinal 2 both structurally valid.  This read-only stage
rehydrates only the bounded PC00 parent container and tests two independent
format channels:

* signed section-table entries in the G1E section headed at the stage-109
  endpoint; and
* aligned occurrence-identity encodings in an exact same-stem G1EM companion,
  when that companion exists on both source and target sides.

A model may resolve only when both channels support it without conflict and it
is the sole eligible model for the pair.  Missing G1EM companions, absent
bindings, duplicate bindings or disagreement between channels leave the pair
unresolved.  Paired-float values, numeric distance and semantic names are not
used.  No game payload is written.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import importlib.util
import json
import os
import struct
import subprocess
import sys
import tempfile
from collections import defaultdict
from pathlib import Path, PurePosixPath
from typing import Any, Callable, Iterable, Mapping, Sequence

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT_DEFAULT = SCRIPT_DIR.parent.parent
TOOL_VERSION = "0.1.34"
REPORT_NAME = "BR_quartet_restoration_reflector_slot_light_swordflash_g1em_section_table_binding_evidence.tar.zst"
REPORT_DIR = "reflector_slot_light_swordflash_g1em_section_table_binding_evidence"

STAGE108_DIR = "br1_official_source_retirement_closure_evidence"
STAGE108_ARCHIVE = "BR_quartet_restoration_br1_official_source_retirement_closure_evidence.tar.zst"
STAGE109_DIR = "reflector_slot_light_sibling_section_layout_evidence"
STAGE109_ARCHIVE = "BR_quartet_restoration_reflector_slot_light_sibling_section_layout_evidence.tar.zst"
STAGE111_DIR = "reflector_slot_light_edit_normalized_layout_alignment_evidence"
STAGE111_ARCHIVE = "BR_quartet_restoration_reflector_slot_light_edit_normalized_layout_alignment_evidence.tar.zst"
STAGE116_DIR = "reflector_slot_light_companion_topology_binding_evidence"
STAGE116_ARCHIVE = "BR_quartet_restoration_reflector_slot_light_companion_topology_binding_evidence.tar.zst"
STAGE79_DIR = "reflector_character_slot_render_member_evidence"
STAGE79_ARCHIVE = "BR_quartet_restoration_reflector_character_slot_render_member_evidence.tar.zst"

PC00_CONTAINER = "data/x64/effect/1000_pc00.elixir.gz"
SCOPE_MEMBERS = (
    "e_pc00_swordflash_02_bullet.g1e#0",
    "e_pc00_swordflash_02_bullet_x.g1e#0",
)
EXPECTED_STAGE109_OCCURRENCES = 1814
EXPECTED_STAGE111_MODELS = 23
EXPECTED_STAGE116_UNRESOLVED = 2
EXPECTED_SCOPE_PAIRS = 2
EXPECTED_SCOPE_MODELS = 4
EXPECTED_PC00_PARENT_SCOPE_ROWS = 3
EXPECTED_PC00_PARENT_SCOPE_MEMBERS = {
    "e_pc00_eyelight_00.g1e#0",
    "e_pc00_eyelight_01.g1e#0",
    "e_pc00_ringlight_a.g1e#0",
}
TABLE_RELATIVE_DWORD_MIN = -64
TABLE_RELATIVE_DWORD_MAX = 10
G1EM_ENCODINGS = (
    "absolute_byte_offset",
    "section_relative_byte_offset",
    "absolute_dword_offset",
    "section_relative_dword_offset",
)


class Stage117Error(RuntimeError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise Stage117Error(message)


def progress(message: str) -> None:
    print(f"[stage117] {message}", file=sys.stderr, flush=True)


def parse_int(value: Any, default: int = 0) -> int:
    try:
        text = str(value).strip()
        return int(text, 16) if text.casefold().startswith("0x") else int(text)
    except (TypeError, ValueError):
        return default


def parse_bool(value: Any) -> bool:
    return str(value).strip().casefold() in {"1", "true", "yes", "y"}


def signed_i32(value: int) -> int:
    return value - 0x100000000 if value & 0x80000000 else value


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


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
        raise Stage117Error(f"invalid JSON {path}: {exc}") from exc
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
    require(path.is_file(), f"missing prerequisite collector: {path}")
    spec = importlib.util.spec_from_file_location(name, path)
    require(spec is not None and spec.loader is not None, f"cannot load module: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def validate_pc00_parent_scope(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Validate the three stage-79 light-member rows that identify one PC00 parent container.

    Stage 81 intentionally returns member-level scope rows.  For PC00 this is
    two eyelight members plus one ringlight member, all sharing one
    (candidate_id, normalized_path) parent identity.  The parent loader groups
    those rows and rehydrates exactly one container.
    """
    scoped = [
        dict(row)
        for row in rows
        if str(row.get("normalized_path", "")).casefold() == PC00_CONTAINER
    ]
    require(
        len(scoped) == EXPECTED_PC00_PARENT_SCOPE_ROWS,
        f"expected {EXPECTED_PC00_PARENT_SCOPE_ROWS} PC00 light-member scope rows, found {len(scoped)}",
    )
    members = {str(row.get("member_key", "")).casefold() for row in scoped}
    require(members == EXPECTED_PC00_PARENT_SCOPE_MEMBERS, f"PC00 light-member scope set mismatch: {sorted(members)}")
    parent_keys = {
        (str(row.get("candidate_id", "")), str(row.get("normalized_path", "")).casefold())
        for row in scoped
    }
    require(len(parent_keys) == 1, f"expected one PC00 parent identity, found {len(parent_keys)}")
    candidate_id, normalized_path = next(iter(parent_keys))
    require(candidate_id, "PC00 parent candidate_id is empty")
    require(normalized_path == PC00_CONTAINER, "PC00 parent normalized path mismatch")
    return sorted(scoped, key=lambda row: str(row.get("member_key", "")))


def parse_pairs(text: str) -> set[tuple[int, int]]:
    pairs: set[tuple[int, int]] = set()
    for item in str(text).split(";"):
        if not item:
            continue
        left, sep, right = item.partition("->")
        require(sep == "->", f"invalid ordinal mapping: {item}")
        pairs.add((parse_int(left, -1), parse_int(right, -1)))
    return pairs


def companion_key(member_key: str) -> str:
    value = member_key.casefold()
    require(value.endswith(".g1e#0"), f"not a G1E member key: {member_key}")
    return value[:-6] + ".g1em#0"


def extract_section_table_entries(payload: bytes, endpoint: int, header: Mapping[str, Any]) -> list[dict[str, Any]]:
    require(parse_bool(header.get("exact_layout")), f"section header is not exact at {endpoint}")
    boundaries = [
        parse_int(header.get("fixed_header_size"), -1),
        parse_int(header.get("table_boundary_1"), -1),
        parse_int(header.get("table_boundary_2"), -1),
        parse_int(header.get("table_boundary_3"), -1),
    ]
    require(boundaries[0] == 56 and all(a <= b for a, b in zip(boundaries, boundaries[1:])), "invalid section table boundaries")
    rows: list[dict[str, Any]] = []
    for table_index in range(1, 4):
        start, end = boundaries[table_index - 1], boundaries[table_index]
        require((end - start) % 4 == 0, "unaligned section table")
        for entry_index, relative in enumerate(range(start, end, 4)):
            absolute = endpoint + relative
            require(0 <= absolute <= len(payload) - 4, "section table entry out of bounds")
            u32 = int.from_bytes(payload[absolute:absolute + 4], "little")
            rows.append({
                "table_index": table_index,
                "entry_index": entry_index,
                "entry_relative_offset": relative,
                "entry_absolute_offset": absolute,
                "entry_u32_hex": f"0x{u32:08x}",
                "entry_i32": signed_i32(u32),
                "signed_anchor": absolute + signed_i32(u32),
            })
    return rows


def section_binding_candidates(
    table_rows: Sequence[Mapping[str, Any]], occurrences: Sequence[Mapping[str, Any]], side: str,
) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for entry in table_rows:
        anchor = parse_int(entry.get("signed_anchor"), -1)
        for occurrence in occurrences:
            record_start = parse_int(occurrence.get("record_start"), -1)
            delta = anchor - record_start
            if delta % 4:
                continue
            relative_dword = delta // 4
            if TABLE_RELATIVE_DWORD_MIN <= relative_dword <= TABLE_RELATIVE_DWORD_MAX:
                result.append({
                    **entry,
                    "side": side,
                    "occurrence_ordinal": parse_int(occurrence.get("template_ordinal_within_section"), -1),
                    "record_start": record_start,
                    "record_relative_dword": relative_dword,
                })
    return result


def occurrence_encoding_values(occurrence: Mapping[str, Any], endpoint: int) -> dict[str, int]:
    record_start = parse_int(occurrence.get("record_start"), -1)
    require(record_start >= 0 and endpoint >= 0 and record_start % 4 == 0 and (record_start - endpoint) % 4 == 0, "unaligned occurrence encoding")
    return {
        "absolute_byte_offset": record_start,
        "section_relative_byte_offset": record_start - endpoint,
        "absolute_dword_offset": record_start // 4,
        "section_relative_dword_offset": (record_start - endpoint) // 4,
    }


def scan_g1em_occurrence_bindings(
    payload: bytes, occurrences: Sequence[Mapping[str, Any]], endpoint: int, side: str,
) -> list[dict[str, Any]]:
    value_map: dict[tuple[str, int], list[int]] = defaultdict(list)
    for occurrence in occurrences:
        ordinal = parse_int(occurrence.get("template_ordinal_within_section"), -1)
        for encoding, value in occurrence_encoding_values(occurrence, endpoint).items():
            value_map[(encoding, value & 0xFFFFFFFF)].append(ordinal)
    rows: list[dict[str, Any]] = []
    for offset in range(0, len(payload) - 3, 4):
        u32 = int.from_bytes(payload[offset:offset + 4], "little")
        for encoding in G1EM_ENCODINGS:
            ordinals = value_map.get((encoding, u32), [])
            for ordinal in ordinals:
                rows.append({
                    "side": side,
                    "g1em_dword_offset": offset // 4,
                    "g1em_byte_offset": offset,
                    "g1em_u32_hex": f"0x{u32:08x}",
                    "encoding": encoding,
                    "occurrence_ordinal": ordinal,
                })
    return rows


def evaluate_model(
    model: Mapping[str, Any],
    source_table: Sequence[Mapping[str, Any]],
    target_table: Sequence[Mapping[str, Any]],
    source_g1em: Sequence[Mapping[str, Any]],
    target_g1em: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    mapping = parse_pairs(str(model.get("matched_ordinal_pairs", "")))
    table_support: set[tuple[int, int, int, int]] = set()
    table_conflicts: set[tuple[int, int, int, int]] = set()
    for left in source_table:
        for right in target_table:
            if parse_int(left.get("table_index"), -1) != parse_int(right.get("table_index"), -1):
                continue
            if parse_int(left.get("entry_index"), -1) != parse_int(right.get("entry_index"), -1):
                continue
            if parse_int(left.get("record_relative_dword"), 9999) != parse_int(right.get("record_relative_dword"), 9998):
                continue
            pair = (parse_int(left.get("occurrence_ordinal"), -1), parse_int(right.get("occurrence_ordinal"), -1))
            identity = (
                parse_int(left.get("table_index"), -1),
                parse_int(left.get("entry_index"), -1),
                parse_int(left.get("record_relative_dword"), 9999),
                pair[0] * 1000 + pair[1],
            )
            (table_support if pair in mapping else table_conflicts).add(identity)

    companion_support: set[tuple[int, str, int, int]] = set()
    companion_conflicts: set[tuple[int, str, int, int]] = set()
    for left in source_g1em:
        for right in target_g1em:
            if parse_int(left.get("g1em_dword_offset"), -1) != parse_int(right.get("g1em_dword_offset"), -1):
                continue
            if str(left.get("encoding", "")) != str(right.get("encoding", "")):
                continue
            pair = (parse_int(left.get("occurrence_ordinal"), -1), parse_int(right.get("occurrence_ordinal"), -1))
            identity = (
                parse_int(left.get("g1em_dword_offset"), -1),
                str(left.get("encoding", "")),
                pair[0],
                pair[1],
            )
            (companion_support if pair in mapping else companion_conflicts).add(identity)

    table_indices = {item[0] for item in table_support}
    eligible = (
        len(table_support) >= 2
        and len(table_indices) >= 2
        and not table_conflicts
        and len(companion_support) >= 1
        and not companion_conflicts
    )
    return {
        "pair_id": model.get("pair_id", ""),
        "model_id": model.get("model_id", ""),
        "edit_kind": model.get("edit_kind", ""),
        "edit_ordinal": model.get("edit_ordinal", ""),
        "section_table_support_rows": len(table_support),
        "section_table_support_distinct_tables": len(table_indices),
        "section_table_conflict_rows": len(table_conflicts),
        "g1em_support_rows": len(companion_support),
        "g1em_conflict_rows": len(companion_conflicts),
        "identity_eligible_joint_topology_model": eligible,
        "classification": "joint_g1em_section_table_model_eligible" if eligible else "joint_topology_support_insufficient_or_conflicting",
    }


def decide_pair(pair: Mapping[str, Any], model_rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    eligible = [row for row in model_rows if parse_bool(row.get("identity_eligible_joint_topology_model"))]
    selected = eligible[0] if len(eligible) == 1 else None
    return {
        "pair_id": pair.get("pair_id", ""),
        "normalized_path": pair.get("normalized_path", ""),
        "member_key": pair.get("member_key", ""),
        "member_name": pair.get("member_name", ""),
        "source_values": pair.get("source_values", ""),
        "target_values": pair.get("target_values", ""),
        "candidate_model_rows": len(model_rows),
        "eligible_joint_topology_model_rows": len(eligible),
        "selected_model_id": selected.get("model_id", "") if selected else "",
        "selection_basis": "unique_exact_g1em_and_section_table_topology_binding" if selected else "",
        "classification": "occurrence_identity_resolved_by_joint_g1em_section_table_binding" if selected else "occurrence_identity_unresolved_after_joint_g1em_section_table_binding",
    }


def validate_summaries(stage108_root: Path, stage109_root: Path, stage111_root: Path, stage116_root: Path) -> tuple[dict[str, Any], ...]:
    s108 = load_json(stage108_root / "SUMMARY.json")
    s109 = load_json(stage109_root / "SUMMARY.json")
    s111 = load_json(stage111_root / "SUMMARY.json")
    s116 = load_json(stage116_root / "SUMMARY.json")
    require(s108.get("status") == "underscore_archive_retirement_closed" and parse_bool(s108.get("retirement_complete")), "stage108 retirement closure mismatch")
    require(s109.get("tool_version") == "0.1.23" and parse_int(s109.get("revalidated_occurrence_rows"), -1) == EXPECTED_STAGE109_OCCURRENCES, "stage109 summary mismatch")
    require(s111.get("tool_version") == "0.1.25" and parse_int(s111.get("one_edit_alignment_model_rows"), -1) == EXPECTED_STAGE111_MODELS, "stage111 summary mismatch")
    require(s116.get("tool_version") == "0.1.31" and parse_int(s116.get("still_unresolved_noncanary_pair_rows"), -1) == EXPECTED_STAGE116_UNRESOLVED, "stage116 summary mismatch")
    require(parse_bool(s116.get("canary_identity_preserved")), "stage116 canary drift")
    require(parse_int(s116.get("prototype_candidate_rows"), -1) == 0 and parse_int(s116.get("skipped_rows"), -1) == 0, "stage116 forbidden output")
    return s108, s109, s111, s116


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

    stage81 = load_module(SCRIPT_DIR / "collect_reflector_ringlight_control_callsite_evidence.py", "stage81_for_stage117")
    stage86 = load_module(SCRIPT_DIR / "collect_reflector_slot_light_shared_record_template_evidence.py", "stage86_for_stage117")
    stage90 = load_module(SCRIPT_DIR / "collect_reflector_slot_light_target_section_layout_evidence.py", "stage90_for_stage117")

    with tempfile.TemporaryDirectory(prefix="br-stage117-") as temporary_name:
        temporary = Path(temporary_name)
        r108 = locate(reports, STAGE108_DIR, STAGE108_ARCHIVE, temporary / "108")
        r109 = locate(reports, STAGE109_DIR, STAGE109_ARCHIVE, temporary / "109")
        r111 = locate(reports, STAGE111_DIR, STAGE111_ARCHIVE, temporary / "111")
        r116 = locate(reports, STAGE116_DIR, STAGE116_ARCHIVE, temporary / "116")
        r79 = locate(reports, STAGE79_DIR, STAGE79_ARCHIVE, temporary / "79")
        s108, s109, s111, s116 = validate_summaries(r108, r109, r111, r116)
        stage81.validate_stage79(r79)

        occurrence_rows = read_tsv(r109 / "SLOT_LIGHT_SIBLING_SECTION_LAYOUT_OCCURRENCES.tsv")
        pair_rows_all = read_tsv(r111 / "SLOT_LIGHT_EDIT_NORMALIZED_SECTION_PAIR_CANDIDATES.tsv")
        model_rows_all = read_tsv(r111 / "SLOT_LIGHT_EDIT_NORMALIZED_ALIGNMENT_MODELS.tsv")
        decision116 = read_tsv(r116 / "SLOT_LIGHT_COMPANION_TOPOLOGY_PAIR_DECISIONS.tsv")
        unresolved_keys = {str(row.get("member_key", "")).casefold() for row in decision116 if not row.get("selected_model_id")}
        require(unresolved_keys == set(SCOPE_MEMBERS), f"stage116 unresolved member set mismatch: {sorted(unresolved_keys)}")

        pair_rows = [row for row in pair_rows_all if str(row.get("member_key", "")).casefold() in SCOPE_MEMBERS]
        model_rows = [row for row in model_rows_all if str(row.get("member_key", "")).casefold() in SCOPE_MEMBERS]
        require(len(pair_rows) == EXPECTED_SCOPE_PAIRS and len(model_rows) == EXPECTED_SCOPE_MODELS, "swordflash pair/model count mismatch")

        parent_scope = validate_pc00_parent_scope(stage81.select_parent_scope(r79))
        actual_rules = rules_file or project_root / "titles/blue_reflection/modules/quartet_restoration/mappings/effect_material_rules.tsv"
        loader = container_loader or stage81.load_parent_containers
        progress("rehydrating bounded PC00 parent effect container")
        containers, loader_skipped = loader(scope_rows=parent_scope, workspace_root=workspace, report_root=reports, rules_file=actual_rules, maximum_earc_bytes=maximum_earc_bytes)
        require(not loader_skipped and len(containers) == 1, "PC00 parent container rehydration mismatch")
        pair_by_key, _all_pairs = stage86.index_pairs(containers)

        companion_inventory: list[dict[str, Any]] = []
        table_binding_rows: list[dict[str, Any]] = []
        g1em_binding_rows: list[dict[str, Any]] = []
        support_rows: list[dict[str, Any]] = []
        pair_decisions: list[dict[str, Any]] = []
        skipped_rows: list[dict[str, Any]] = []

        occurrences_by_member_side: dict[tuple[str, str], list[dict[str, str]]] = defaultdict(list)
        for row in occurrence_rows:
            key = str(row.get("member_key", "")).casefold()
            if key in SCOPE_MEMBERS:
                occurrences_by_member_side[(key, str(row.get("side", "")).casefold())].append(row)
        for rows in occurrences_by_member_side.values():
            rows.sort(key=lambda row: parse_int(row.get("template_ordinal_within_section"), -1))

        for pair in pair_rows:
            member_key = str(pair.get("member_key", "")).casefold()
            key = (PC00_CONTAINER, member_key)
            g1e_pair = pair_by_key.get(key)
            require(g1e_pair is not None, f"missing scoped G1E pair: {member_key}")
            g1em_key = companion_key(member_key)
            g1em_pair = pair_by_key.get((PC00_CONTAINER, g1em_key))
            companion_inventory.append({
                "normalized_path": PC00_CONTAINER,
                "g1e_member_key": member_key,
                "g1e_member_name": g1e_pair.get("member_name", ""),
                "g1em_member_key": g1em_key,
                "g1em_member_name": g1em_pair.get("member_name", "") if g1em_pair else "",
                "same_stem_g1em_present": bool(g1em_pair),
                "source_g1em_size": len(bytes(g1em_pair.get("source_payload") or b"")) if g1em_pair else 0,
                "target_g1em_size": len(bytes(g1em_pair.get("target_payload") or b"")) if g1em_pair else 0,
                "source_g1em_sha256": sha256(bytes(g1em_pair.get("source_payload") or b"")) if g1em_pair else "",
                "target_g1em_sha256": sha256(bytes(g1em_pair.get("target_payload") or b"")) if g1em_pair else "",
                "classification": "same_stem_g1em_companion_present" if g1em_pair else "same_stem_g1em_companion_absent_non_authorizing",
            })

            source_occ = occurrences_by_member_side[(member_key, "source")]
            target_occ = occurrences_by_member_side[(member_key, "target")]
            require(len(source_occ) == 3 and len(target_occ) == 2, f"unexpected swordflash occurrence counts: {member_key}")
            source_endpoint = parse_int(pair.get("source_endpoint"), -1)
            target_endpoint = parse_int(pair.get("target_endpoint"), -1)
            source_payload = bytes(g1e_pair.get("source_payload") or b"")
            target_payload = bytes(g1e_pair.get("target_payload") or b"")
            source_header = stage90.parse_section_header(source_payload, source_endpoint)
            target_header = stage90.parse_section_header(target_payload, target_endpoint)
            require(parse_bool(source_header.get("exact_layout")) and parse_bool(target_header.get("exact_layout")), f"invalid scoped section header: {member_key}")
            source_table = section_binding_candidates(extract_section_table_entries(source_payload, source_endpoint, source_header), source_occ, "source")
            target_table = section_binding_candidates(extract_section_table_entries(target_payload, target_endpoint, target_header), target_occ, "target")
            for row in source_table + target_table:
                table_binding_rows.append({"member_key": member_key, "member_name": pair.get("member_name", ""), **row})

            source_g1em: list[dict[str, Any]] = []
            target_g1em: list[dict[str, Any]] = []
            if g1em_pair:
                source_g1em = scan_g1em_occurrence_bindings(bytes(g1em_pair.get("source_payload") or b""), source_occ, source_endpoint, "source")
                target_g1em = scan_g1em_occurrence_bindings(bytes(g1em_pair.get("target_payload") or b""), target_occ, target_endpoint, "target")
                for row in source_g1em + target_g1em:
                    g1em_binding_rows.append({"member_key": member_key, "member_name": pair.get("member_name", ""), "g1em_member_key": g1em_key, **row})
            else:
                skipped_rows.append({"scope": "same_stem_g1em", "identity": member_key, "reason": "same_stem_g1em_companion_absent_pair_remains_unresolved"})

            pair_models = [row for row in model_rows if row.get("pair_id") == pair.get("pair_id")]
            require(len(pair_models) == 2, f"expected two swordflash models: {member_key}")
            evaluated = [evaluate_model(model, source_table, target_table, source_g1em, target_g1em) for model in pair_models]
            support_rows.extend(evaluated)
            pair_decisions.append(decide_pair(pair, evaluated))

        newly_resolved = sum(bool(row.get("selected_model_id")) for row in pair_decisions)
        still_unresolved = len(pair_decisions) - newly_resolved
        canary_rows = [
            {"question": "stage116 immutable PC02 canary preserved", "answer": s116.get("canary_identity_preserved", False), "classification": "prerequisite_canary_unchanged"},
            {"question": "canary included in stage117 scope", "answer": False, "classification": "swordflash_only_scope"},
            {"question": "paired-float values used for selection", "answer": False, "classification": "topology_only"},
            {"question": "numeric closeness used for selection", "answer": False, "classification": "exact_binding_only"},
        ]

        output = reports / REPORT_DIR
        if output.exists():
            import shutil
            shutil.rmtree(output)
        output.mkdir(parents=True)
        write_tsv(output / "SLOT_LIGHT_SWORDFLASH_G1EM_COMPANION_INVENTORY.tsv", [
            "normalized_path", "g1e_member_key", "g1e_member_name", "g1em_member_key", "g1em_member_name", "same_stem_g1em_present",
            "source_g1em_size", "target_g1em_size", "source_g1em_sha256", "target_g1em_sha256", "classification",
        ], companion_inventory)
        write_tsv(output / "SLOT_LIGHT_SWORDFLASH_SECTION_TABLE_BINDINGS.tsv", [
            "member_key", "member_name", "side", "table_index", "entry_index", "entry_relative_offset", "entry_absolute_offset",
            "entry_u32_hex", "entry_i32", "signed_anchor", "occurrence_ordinal", "record_start", "record_relative_dword",
        ], table_binding_rows)
        write_tsv(output / "SLOT_LIGHT_SWORDFLASH_G1EM_OCCURRENCE_BINDINGS.tsv", [
            "member_key", "member_name", "g1em_member_key", "side", "g1em_dword_offset", "g1em_byte_offset", "g1em_u32_hex", "encoding", "occurrence_ordinal",
        ], g1em_binding_rows)
        write_tsv(output / "SLOT_LIGHT_SWORDFLASH_MODEL_TOPOLOGY_SUPPORT.tsv", [
            "pair_id", "model_id", "edit_kind", "edit_ordinal", "section_table_support_rows", "section_table_support_distinct_tables",
            "section_table_conflict_rows", "g1em_support_rows", "g1em_conflict_rows", "identity_eligible_joint_topology_model", "classification",
        ], support_rows)
        write_tsv(output / "SLOT_LIGHT_SWORDFLASH_PAIR_DECISIONS.tsv", [
            "pair_id", "normalized_path", "member_key", "member_name", "source_values", "target_values", "candidate_model_rows",
            "eligible_joint_topology_model_rows", "selected_model_id", "selection_basis", "classification",
        ], pair_decisions)
        write_tsv(output / "SLOT_LIGHT_SWORDFLASH_G1EM_SECTION_TABLE_CANARY_CHECK.tsv", ["question", "answer", "classification"], canary_rows)
        write_tsv(output / "SLOT_LIGHT_SWORDFLASH_G1EM_SECTION_TABLE_BINDING_SKIPPED.tsv", ["scope", "identity", "reason"], skipped_rows)

        summary = {
            "type": "br_quartet_restoration_reflector_slot_light_swordflash_g1em_section_table_binding_evidence_summary",
            "format_version": 1,
            "tool_version": TOOL_VERSION,
            "status": "bounded_swordflash_g1em_and_section_table_topology_audited_semantics_unresolved_no_write",
            "stage109_occurrence_rows": parse_int(s109.get("revalidated_occurrence_rows"), -1),
            "stage111_one_edit_model_rows": parse_int(s111.get("one_edit_alignment_model_rows"), -1),
            "stage116_input_unresolved_noncanary_pair_rows": parse_int(s116.get("still_unresolved_noncanary_pair_rows"), -1),
            "scoped_swordflash_pair_rows": len(pair_rows),
            "scoped_swordflash_model_rows": len(model_rows),
            "same_stem_g1em_companion_rows": sum(parse_bool(row.get("same_stem_g1em_present")) for row in companion_inventory),
            "section_table_binding_candidate_rows": len(table_binding_rows),
            "g1em_occurrence_binding_candidate_rows": len(g1em_binding_rows),
            "model_topology_support_rows": len(support_rows),
            "newly_resolved_noncanary_pair_rows": newly_resolved,
            "still_unresolved_noncanary_pair_rows": still_unresolved,
            "total_resolved_noncanary_pair_rows_after_stage117": parse_int(s116.get("total_resolved_noncanary_pair_rows_after_stage116"), 0) + newly_resolved,
            "canary_identity_preserved": True,
            "prototype_candidate_rows": 0,
            "technical_leaf_domain_semantics_resolved": False,
            "brightness_semantics_confirmed": False,
            "intensity_semantics_confirmed": False,
            "censorship_semantics_confirmed": False,
            "skipped_rows": len(skipped_rows),
            "policy": {
                "official_nonunderscore_archives_are_canonical": True,
                "underscore_archives_required": False,
                "same_stem_name_is_semantic_evidence": False,
                "section_table_minimum_support_rows": 2,
                "section_table_minimum_distinct_tables": 2,
                "g1em_minimum_support_rows": 1,
                "both_binding_channels_required": True,
                "paired_float_leaf_values_used_for_identity": False,
                "numeric_closeness_used": False,
                "field_semantic_names_assigned": False,
                "G1E_G1EM_write_authorized": False,
                "pak_repack_authorized": False,
                "profile_or_registry_write_authorized": False,
                "installed_game_modified": False,
            },
            "next_action": "Upload this report. Preserve only uniquely joint-bound swordflash identities. Any missing, duplicate or conflicting G1EM/section-table binding remains unresolved. Do not infer value semantics or write G1E/G1EM.",
        }
        (output / "SUMMARY.json").write_text(json.dumps(summary, indent=2, sort_keys=False) + "\n", encoding="utf-8")
        archive = reports / REPORT_NAME if create_archive else None
        if archive:
            make_archive(output, archive)
        return output, archive, summary


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path, default=PROJECT_ROOT_DEFAULT)
    parser.add_argument("--no-report-archive", action="store_true")
    args = parser.parse_args(argv)
    try:
        output, archive, summary = build_report(args.project_root, create_archive=not args.no_report_archive)
    except Stage117Error as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print(f"Output: {output}")
    if archive:
        print(f"Report: {archive}")
    print(f"Newly resolved swordflash pairs: {summary['newly_resolved_noncanary_pair_rows']}")
    print(f"Still unresolved swordflash pairs: {summary['still_unresolved_noncanary_pair_rows']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
