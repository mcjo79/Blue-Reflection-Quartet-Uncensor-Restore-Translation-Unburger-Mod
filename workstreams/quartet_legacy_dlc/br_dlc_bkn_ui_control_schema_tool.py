#!/usr/bin/env python3
"""Read-only schema probe for non-texture BKN numeric candidates in costume UI.

Stage 43 classified twenty-one target-side BKN numeric hits. Texture payload
collisions are already rejected; this stage reopens only the hash-gated UI
members that contain the remaining non-texture candidates. It classifies KSLT
header crossings and structural-boundary crossings, aligns KSCL control bodies
between BR1 and Quartet, and records bounded local pattern metadata for the
remaining control-body candidates.

The report contains hashes, offsets, integer metadata and alignment opcodes
only. No KSCL/KSLT bytes, textures, tables, PAKs, modules, profiles,
Translation records, Git state or installed game file is modified or exported.
"""
from __future__ import annotations

import argparse
import contextlib
import csv
import difflib
import hashlib
import json
import shutil
import subprocess
import sys
import tarfile
import tempfile
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable, Iterator, Mapping, Sequence

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import br_dlc_bkn_ui_index_tool as STAGE40  # noqa: E402
import br_dlc_bkn_ui_structure_tool as STAGE43  # noqa: E402

TOOL_VERSION = "0.0.19"
FORMAT_VERSION = 1
REPORT_DIR_NAME = "bkn_ui_control_schema_evidence"
REPORT_ARCHIVE_NAME = "BR_quartet_legacy_dlc_bkn_ui_control_schema_evidence.tar.zst"
CONTEXT_RADIUS = 32

FORBIDDEN_REPORT_SUFFIXES = {
    ".pak", ".ebm", ".ebd", ".g1m", ".g1t", ".g1a", ".g1e", ".g1s",
    ".elixir", ".gz", ".bin", ".swg", ".dds", ".wav", ".ogg", ".exe", ".dll",
    ".kscl", ".kslt",
}

KSLT_FIELDS = (
    (0x00, 0x04, "magic"),
    (0x04, 0x08, "unknown_04"),
    (0x08, 0x0C, "texture_count"),
    (0x0C, 0x10, "headerless_size"),
    (0x10, 0x14, "table_pointer"),
    (0x14, 0x18, "name_length"),
    (0x18, 0x1C, "name_count"),
    (0x1C, 0x20, "unknown_1c"),
    (0x20, 0x24, "unknown_20"),
    (0x24, 0x28, "unknown_24"),
    (0x28, 0x2C, "unknown_28"),
    (0x2C, 0x30, "unknown_2c"),
    (0x30, 0x34, "unknown_30"),
    (0x34, 0x38, "unknown_34"),
    (0x38, 0x3C, "unknown_38"),
    (0x3C, 0x40, "unknown_3c"),
)


class BknUiControlSchemaError(RuntimeError):
    pass


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def scalar(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (list, tuple, set, dict)):
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return str(value)


def write_tsv(path: Path, fields: Sequence[str], rows: Iterable[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(fields), delimiter="\t", lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow({field: scalar(row.get(field, "")) for field in fields})


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def read_tsv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def clean_dir(path: Path) -> None:
    if path.exists():
        shutil.rmtree(path)
    path.mkdir(parents=True, exist_ok=True)


def make_archive(source: Path, output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="br_dlc_bkn_ui_control_schema_bundle_") as temp_name:
        temp_tar = Path(temp_name) / "report.tar"
        with tarfile.open(temp_tar, "w", format=tarfile.PAX_FORMAT) as archive:
            for path in sorted(source.rglob("*"), key=lambda item: item.relative_to(source).as_posix().casefold()):
                if not path.is_file():
                    continue
                info = archive.gettarinfo(str(path), arcname=f"{source.name}/{path.relative_to(source).as_posix()}")
                info.uid = info.gid = 0
                info.uname = info.gname = ""
                info.mtime = 0
                with path.open("rb") as handle:
                    archive.addfile(info, handle)
        subprocess.run(["zstd", "-q", "-f", "-19", str(temp_tar), "-o", str(output)], check=True)


def report_manifest(root: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for path in sorted(root.rglob("*"), key=lambda item: item.relative_to(root).as_posix().casefold()):
        if path.is_file() and path.name != "REPORT_MANIFEST.json":
            rows.append({
                "path": path.relative_to(root).as_posix(),
                "size": path.stat().st_size,
                "sha256": sha256_file(path),
            })
    return rows


@contextlib.contextmanager
def prerequisite_report(
    project_root: Path,
    dir_name: str,
    archive_name: str,
    validator: Any,
) -> Iterator[Path]:
    parent = project_root / ".local/reports/quartet_legacy_dlc"
    direct = parent / dir_name
    if direct.is_dir():
        validator(direct)
        yield direct
        return
    archive = parent / archive_name
    if not archive.is_file():
        raise BknUiControlSchemaError(f"missing prerequisite report: {archive_name}")
    with tempfile.TemporaryDirectory(prefix="br_dlc_bkn_ui_control_schema_prereq_") as temp_name:
        temp = Path(temp_name)
        subprocess.run(["tar", "--zstd", "-xf", str(archive), "-C", str(temp)], check=True)
        candidates = [path for path in temp.iterdir() if path.is_dir()]
        if len(candidates) != 1:
            raise BknUiControlSchemaError(f"could not locate extracted prerequisite: {archive_name}")
        validator(candidates[0])
        yield candidates[0]


def count_occurrences(payload: bytes, needle: bytes) -> int:
    if not needle:
        return 0
    total = 0
    start = 0
    while True:
        offset = payload.find(needle, start)
        if offset < 0:
            return total
        total += 1
        start = offset + 1


def intersecting_header_fields(relative_offset: int, width: int) -> list[str]:
    start = relative_offset
    end = relative_offset + width
    return [name for left, right, name in KSLT_FIELDS if start < right and end > left]


def find_opcode(opcodes: Sequence[tuple[str, int, int, int, int]], target_relative: int) -> tuple[str, int, int, int, int]:
    for opcode in opcodes:
        _tag, _i1, _i2, j1, j2 = opcode
        if j1 <= target_relative < j2:
            return opcode
    raise BknUiControlSchemaError(f"could not map target control offset {target_relative} to a diff opcode")


def family_value_sets(value_rows: Sequence[Mapping[str, str]]) -> dict[tuple[str, str], set[int]]:
    result: dict[tuple[str, str], set[int]] = defaultdict(set)
    for row in value_rows:
        result[(row["index_space"], row["family"])].add(int(row["numeric_value"]))
    return result


def scan_local_family_values(
    payload: bytes,
    start: int,
    end: int,
    index_space: str,
    value_sets: Mapping[tuple[str, str], set[int]],
) -> dict[str, list[int]]:
    output: dict[str, set[int]] = {"bkn": set(), "twl": set(), "scl": set()}
    for width in (2, 4):
        first = start + ((width - start % width) % width)
        for offset in range(first, max(first, end - width + 1), width):
            value = int.from_bytes(payload[offset:offset + width], "little")
            for family in output:
                if value in value_sets.get((index_space, family), set()):
                    output[family].add(value)
    return {family: sorted(values) for family, values in output.items()}


def control_body(parsed: STAGE43.ParsedUi, payload: bytes) -> bytes:
    if parsed.file_kind != "kscl_with_embedded_kslt" or parsed.kscl_length is None:
        raise BknUiControlSchemaError("control-body probe requires KSCL with embedded KSLT")
    return payload[STAGE43.KSCL_HEADER_SIZE:parsed.kscl_length]


def candidate_classification(
    opcode_tag: str,
    local_values: Mapping[str, Sequence[int]],
    target_window_repeats: int,
    source_window_repeats: int,
    other_target_window_repeats: int,
) -> tuple[str, bool]:
    bkn_count = len(local_values.get("bkn", ()))
    if opcode_tag == "equal":
        return "unchanged_control_numeric_collision", False
    if bkn_count >= 2:
        return "local_multi_bkn_control_pattern_candidate", True
    if source_window_repeats > 0 or other_target_window_repeats > 0 or target_window_repeats > 1:
        return "shared_control_pattern_numeric_collision", False
    return "isolated_changed_control_numeric_candidate", False


def audit(
    project_root: Path,
    br1_root: Path,
    quartet_root: Path,
    output_root: Path,
    *,
    create_report_archive: bool = True,
) -> tuple[Path | None, dict[str, Any]]:
    with prerequisite_report(
        project_root,
        STAGE43.REPORT_DIR_NAME,
        STAGE43.REPORT_ARCHIVE_NAME,
        STAGE43.validate_report,
    ) as stage43_root:
        stage43_summary = json.loads((stage43_root / "SUMMARY.json").read_text(encoding="utf-8"))
        candidate_rows = [
            row for row in read_tsv(stage43_root / "DLC_BKN_UI_INDEX_REGION_CLASSIFICATION.tsv")
            if row.get("side") == "target"
            and row.get("family") == "bkn"
            and row.get("owner_binding_evidence_strength") == "candidate_only"
            and row.get("region_role") != "texture_payload"
        ]
    if int(stage43_summary.get("target_bkn_structural_candidate_hits", -1)) != len(candidate_rows):
        raise BknUiControlSchemaError("stage-43 structural candidate count changed")
    if not candidate_rows:
        raise BknUiControlSchemaError("stage 46 requires at least one non-texture structural candidate")

    selected_members = sorted({row["member_path"] for row in candidate_rows})
    with prerequisite_report(
        project_root,
        STAGE40.REPORT_DIR_NAME,
        STAGE40.REPORT_ARCHIVE_NAME,
        STAGE40.validate_report,
    ) as stage40_root:
        member_rows = [
            row for row in read_tsv(stage40_root / "DLC_BKN_UI_INDEX_MEMBER_AUDIT.tsv")
            if row.get("normalized_path") in selected_members
        ]
        value_rows = read_tsv(stage40_root / "DLC_BKN_UI_INDEX_VALUE_HITS.tsv")
    if len(member_rows) != len(selected_members) * 2:
        raise BknUiControlSchemaError("selected structural candidates do not have complete source/target member pairs")

    clean_dir(output_root)
    print(f"[stage46] reopening {len(member_rows)} hash-gated UI members for {len(candidate_rows)} structural candidates", flush=True)
    payload_specs = [{
        "side": row["side"],
        "archive": row["archive"],
        "inventory_path": row["inventory_path"],
        "normalized_path": row["normalized_path"],
        "expected_size": int(row["actual_size"]),
        "expected_sha256": row["actual_sha256"],
    } for row in member_rows]
    payloads, rehydration_rows = STAGE40.read_ui_payloads(payload_specs, br1_root, quartet_root)
    parsed_map = {key: STAGE43.parse_ui_member(payload) for key, payload in payloads.items()}
    value_sets = family_value_sets(value_rows)

    paired: dict[str, dict[str, bytes]] = defaultdict(dict)
    for (side, member_path), payload in payloads.items():
        paired[member_path][side] = payload
    for member_path, sides in paired.items():
        if set(sides) != {"source", "target"}:
            raise BknUiControlSchemaError(f"incomplete selected UI pair: {member_path}")

    opcode_rows: list[dict[str, Any]] = []
    opcodes_by_member: dict[str, list[tuple[str, int, int, int, int]]] = {}
    target_bodies: dict[str, bytes] = {}
    source_bodies: dict[str, bytes] = {}
    for member_path in selected_members:
        source_parsed = parsed_map[("source", member_path)]
        target_parsed = parsed_map[("target", member_path)]
        if source_parsed.file_kind != "kscl_with_embedded_kslt" or target_parsed.file_kind != "kscl_with_embedded_kslt":
            continue
        source_body = control_body(source_parsed, paired[member_path]["source"])
        target_body = control_body(target_parsed, paired[member_path]["target"])
        source_bodies[member_path] = source_body
        target_bodies[member_path] = target_body
        matcher = difflib.SequenceMatcher(None, source_body, target_body, autojunk=False)
        opcodes = list(matcher.get_opcodes())
        opcodes_by_member[member_path] = opcodes
        for opcode_index, (tag, i1, i2, j1, j2) in enumerate(opcodes):
            opcode_rows.append({
                "member_path": member_path,
                "opcode_index": opcode_index,
                "opcode_tag": tag,
                "source_start": STAGE43.KSCL_HEADER_SIZE + i1,
                "source_end": STAGE43.KSCL_HEADER_SIZE + i2,
                "source_size": i2 - i1,
                "target_start": STAGE43.KSCL_HEADER_SIZE + j1,
                "target_end": STAGE43.KSCL_HEADER_SIZE + j2,
                "target_size": j2 - j1,
                "size_delta": (j2 - j1) - (i2 - i1),
                "raw_payload_exported": False,
            })

    structural_rows: list[dict[str, Any]] = []
    context_rows: list[dict[str, Any]] = []
    header_rows: list[dict[str, Any]] = []
    supported_candidates = 0
    rejected_collision_rows = 0
    control_candidates = 0
    for candidate_id, row in enumerate(sorted(candidate_rows, key=lambda item: (item["member_path"], int(item["offset"]), int(item["width_bits"]), item["index_space"])), 1):
        member_path = row["member_path"]
        target_payload = paired[member_path]["target"]
        target_parsed = parsed_map[("target", member_path)]
        offset = int(row["offset"])
        width = int(row["width_bits"]) // 8
        region_role = row["region_role"]
        base = {
            "candidate_id": candidate_id,
            "member_path": member_path,
            "index_space": row["index_space"],
            "variant": row["variant"],
            "ordinal": int(row["ordinal"]),
            "numeric_value": int(row["numeric_value"]),
            "width_bits": int(row["width_bits"]),
            "offset": offset,
            "region_role": region_role,
            "overlaps_source_target_delta": row["overlaps_source_target_delta"],
            "raw_payload_exported": False,
        }

        if region_role == "kslt_header":
            relative = offset - target_parsed.kslt_base
            fields = intersecting_header_fields(relative, width)
            crosses = len(fields) != 1 or relative % 4 + width > 4
            classification = "kslt_header_cross_field_collision" if crosses else "kslt_header_field_numeric_candidate"
            if crosses:
                rejected_collision_rows += 1
            structural_rows.append({
                **base,
                "candidate_classification": classification,
                "schema_supported": False,
                "owner_binding_evidence_strength": "not_owner_binding_evidence" if crosses else "candidate_only",
                "next_probe": "none_header_crossing" if crosses else "header_field_semantics_required",
            })
            header_rows.append({
                **base,
                "relative_header_offset": relative,
                "intersecting_fields": fields,
                "field_count": len(fields),
                "crosses_field_boundary": crosses,
                "candidate_classification": classification,
            })
            continue

        if region_role == "cross_region":
            start_role, start_region = STAGE43.region_for(target_parsed, offset, 1)
            end_role, end_region = STAGE43.region_for(target_parsed, offset + width - 1, 1)
            rejected_collision_rows += 1
            structural_rows.append({
                **base,
                "candidate_classification": "structural_boundary_numeric_collision",
                "schema_supported": False,
                "owner_binding_evidence_strength": "not_owner_binding_evidence",
                "next_probe": "none_crosses_structural_boundary",
            })
            header_rows.append({
                **base,
                "relative_header_offset": "",
                "intersecting_fields": [start_role, end_role],
                "field_count": 2,
                "crosses_field_boundary": True,
                "candidate_classification": "structural_boundary_numeric_collision",
                "start_region": start_region.role if start_region else start_role,
                "end_region": end_region.role if end_region else end_role,
            })
            continue

        if region_role in {"kslt_texture_table", "kslt_texture_names", "texture_header", "unclassified_or_padding", "kscl_header"}:
            if region_role == "texture_header":
                classification = "texture_header_numeric_collision"
                evidence_strength = "not_owner_binding_evidence"
                next_probe = "none_texture_metadata_collision"
                rejected_collision_rows += 1
            elif region_role == "unclassified_or_padding":
                classification = "unclassified_structural_numeric_candidate"
                evidence_strength = "candidate_only"
                next_probe = "bounded_format_semantics_required"
            else:
                classification = "kslt_or_kscl_structural_numeric_candidate"
                evidence_strength = "candidate_only"
                next_probe = "bounded_format_semantics_required"
            structural_rows.append({
                **base,
                "candidate_classification": classification,
                "schema_supported": False,
                "owner_binding_evidence_strength": evidence_strength,
                "next_probe": next_probe,
            })
            header_rows.append({
                **base,
                "relative_header_offset": offset - target_parsed.kslt_base if region_role.startswith("kslt_") else "",
                "intersecting_fields": [region_role],
                "field_count": 1,
                "crosses_field_boundary": False,
                "candidate_classification": classification,
            })
            continue

        if region_role != "kscl_control_body":
            raise BknUiControlSchemaError(f"unsupported non-texture candidate region: {region_role}")

        control_candidates += 1
        source_payload = paired[member_path]["source"]
        source_parsed = parsed_map[("source", member_path)]
        source_body = source_bodies[member_path]
        target_body = target_bodies[member_path]
        target_relative = offset - STAGE43.KSCL_HEADER_SIZE
        tag, i1, i2, j1, j2 = find_opcode(opcodes_by_member[member_path], target_relative)
        source_correspondence = ""
        source_absolute: int | str = ""
        if tag == "equal":
            source_absolute = STAGE43.KSCL_HEADER_SIZE + i1 + (target_relative - j1)
            source_correspondence = "exact_equal_opcode"
        elif tag == "replace" and (target_relative - j1) < (i2 - i1):
            source_absolute = STAGE43.KSCL_HEADER_SIZE + i1 + (target_relative - j1)
            source_correspondence = "positional_replace_only"
        elif tag == "insert":
            source_correspondence = "target_only_insert"
        else:
            source_correspondence = "no_exact_source_correspondence"

        window_start = max(STAGE43.KSCL_HEADER_SIZE, offset - CONTEXT_RADIUS)
        window_end = min(target_parsed.kscl_length or len(target_payload), offset + width + CONTEXT_RADIUS)
        window = target_payload[window_start:window_end]
        local_values = scan_local_family_values(
            target_payload,
            window_start,
            window_end,
            row["index_space"],
            value_sets,
        )
        target_repeats = count_occurrences(target_body, window)
        source_repeats = count_occurrences(source_body, window)
        other_target_repeats = sum(
            count_occurrences(body, window)
            for other_member, body in target_bodies.items()
            if other_member != member_path
        )
        classification, schema_supported = candidate_classification(
            tag,
            local_values,
            target_repeats,
            source_repeats,
            other_target_repeats,
        )
        if schema_supported:
            supported_candidates += 1

        structural_rows.append({
            **base,
            "candidate_classification": classification,
            "schema_supported": schema_supported,
            "owner_binding_evidence_strength": "candidate_only",
            "next_probe": "bounded_record_schema_required" if schema_supported else "none_isolated_or_shared_numeric_collision",
        })
        context_rows.append({
            **base,
            "opcode_tag": tag,
            "opcode_source_start": STAGE43.KSCL_HEADER_SIZE + i1,
            "opcode_source_end": STAGE43.KSCL_HEADER_SIZE + i2,
            "opcode_target_start": STAGE43.KSCL_HEADER_SIZE + j1,
            "opcode_target_end": STAGE43.KSCL_HEADER_SIZE + j2,
            "source_correspondence": source_correspondence,
            "source_corresponding_offset": source_absolute,
            "window_start": window_start,
            "window_end": window_end,
            "window_size": len(window),
            "window_sha256": sha256_bytes(window),
            "target_window_repeat_count": target_repeats,
            "source_window_repeat_count": source_repeats,
            "other_target_window_repeat_count": other_target_repeats,
            "local_bkn_values": local_values["bkn"],
            "local_twl_values": local_values["twl"],
            "local_scl_values": local_values["scl"],
            "local_distinct_bkn_values": len(local_values["bkn"]),
            "local_distinct_control_values": len(set(local_values["twl"]) | set(local_values["scl"])),
            "candidate_classification": classification,
            "schema_supported": schema_supported,
            "raw_payload_exported": False,
        })

    if supported_candidates:
        status = "bkn_ui_control_schema_candidates_require_bounded_record_parser"
        owner_status = "candidate_only"
        next_action = "build a bounded record parser only for schema-supported KSCL control candidates; retain all other numeric hits as rejected collisions"
    else:
        status = "bkn_ui_numeric_index_route_not_supported_by_local_schema"
        owner_status = "unresolved_numeric_route_closed_for_selected_members"
        next_action = "close the selected numeric-index UI route and continue availability discovery from proven table fallback and runtime behavior rather than isolated UI integers"

    gaps = [
        {
            "dependency": "owner_ui_slot",
            "status": owner_status,
            "blocks_installation": True,
            "next_evidence": next_action,
        },
        {
            "dependency": "exact_unlock_or_entitlement",
            "status": "unresolved",
            "blocks_installation": True,
            "next_evidence": "identify a proven availability condition without inventing an entitlement",
        },
        {
            "dependency": "wet_variant",
            "status": "conversion_blocked",
            "blocks_installation": True,
            "next_evidence": "complete G1M/SWG conversion and exact G1M-to-G1T binding",
        },
        {
            "dependency": "runtime_validation",
            "status": "not_performed",
            "blocks_installation": True,
            "next_evidence": "runtime validation remains forbidden until a complete transactional profile exists",
        },
    ]

    write_tsv(output_root / "DLC_BKN_UI_STRUCTURAL_CANDIDATES.tsv", [
        "candidate_id", "member_path", "index_space", "variant", "ordinal", "numeric_value", "width_bits",
        "offset", "region_role", "overlaps_source_target_delta", "candidate_classification", "schema_supported",
        "owner_binding_evidence_strength", "next_probe", "raw_payload_exported",
    ], structural_rows)
    write_tsv(output_root / "DLC_BKN_UI_CONTROL_DIFF_OPCODES.tsv", [
        "member_path", "opcode_index", "opcode_tag", "source_start", "source_end", "source_size",
        "target_start", "target_end", "target_size", "size_delta", "raw_payload_exported",
    ], opcode_rows)
    write_tsv(output_root / "DLC_BKN_UI_CONTROL_CANDIDATE_CONTEXT.tsv", [
        "candidate_id", "member_path", "index_space", "variant", "ordinal", "numeric_value", "width_bits",
        "offset", "region_role", "overlaps_source_target_delta", "opcode_tag", "opcode_source_start",
        "opcode_source_end", "opcode_target_start", "opcode_target_end", "source_correspondence",
        "source_corresponding_offset", "window_start", "window_end", "window_size", "window_sha256",
        "target_window_repeat_count", "source_window_repeat_count", "other_target_window_repeat_count",
        "local_bkn_values", "local_twl_values", "local_scl_values", "local_distinct_bkn_values",
        "local_distinct_control_values", "candidate_classification", "schema_supported", "raw_payload_exported",
    ], context_rows)
    write_tsv(output_root / "DLC_BKN_UI_HEADER_BOUNDARY_AUDIT.tsv", [
        "candidate_id", "member_path", "index_space", "variant", "ordinal", "numeric_value", "width_bits",
        "offset", "region_role", "overlaps_source_target_delta", "relative_header_offset", "intersecting_fields",
        "field_count", "crosses_field_boundary", "candidate_classification", "start_region", "end_region",
        "raw_payload_exported",
    ], header_rows)
    write_tsv(output_root / "DLC_BKN_UI_CONTROL_SCHEMA_GAPS.tsv", [
        "dependency", "status", "blocks_installation", "next_evidence",
    ], gaps)

    summary = {
        "type": "br_quartet_legacy_dlc_bkn_ui_control_schema_summary",
        "format_version": FORMAT_VERSION,
        "tool_version": TOOL_VERSION,
        "content_id": "costume_pc00_bkn",
        "status": status,
        "stage43_structural_candidates": len(candidate_rows),
        "selected_ui_member_pairs": len(selected_members),
        "selected_ui_members_rehydrated": len(rehydration_rows),
        "kscl_control_body_candidates": control_candidates,
        "header_or_boundary_collisions": len(header_rows),
        "rejected_header_or_boundary_collisions": rejected_collision_rows,
        "schema_supported_control_candidates": supported_candidates,
        "control_diff_opcodes": len(opcode_rows),
        "unresolved_installation_blockers": len(gaps),
        "findings": [
            "stage 43 rejected texture-payload integer collisions before this probe",
            "KSLT header candidates are classified by exact field boundaries and structural-boundary candidates are rejected as collisions",
            "KSCL control bodies are aligned source-to-target and only bounded window hashes, numeric metadata and diff opcodes are reported",
            "an isolated integer inside a changed control body is not treated as a costume owner, slot, availability or entitlement binding",
            "no UI payload, texture, table, PAK, module, profile, Translation record, Git state or installed game file is modified or exported",
        ],
        "next_action": next_action,
        "policy": {
            "game_modified": False,
            "git_modified": False,
            "candidate_installed": False,
            "profile_registered": False,
            "profile_build_allowed": False,
            "profiles_activated": False,
            "runtime_validated": False,
            "system_table_modified": False,
            "ui_modified": False,
            "translation_modified": False,
            "raw_assets_exported_in_report": False,
            "raw_assets_in_update": False,
            "raw_ui_payload_exported": False,
            "isolated_control_integer_is_ui_binding_proof": False,
            "header_crossing_integer_is_ui_binding_proof": False,
            "structural_boundary_integer_is_ui_binding_proof": False,
            "text_seed_unchanged": True,
        },
    }
    write_json(output_root / "SUMMARY.json", summary)
    write_json(output_root / "REPORT_MANIFEST.json", {
        "type": "br_report_manifest",
        "format_version": 1,
        "files": report_manifest(output_root),
    })

    archive: Path | None = None
    if create_report_archive:
        archive = output_root.parent / REPORT_ARCHIVE_NAME
        make_archive(output_root, archive)
        print(f"[stage46] report: {archive}", flush=True)
    return archive, summary


def validate_report(report_root: Path) -> dict[str, Any]:
    required = (
        "DLC_BKN_UI_STRUCTURAL_CANDIDATES.tsv",
        "DLC_BKN_UI_CONTROL_DIFF_OPCODES.tsv",
        "DLC_BKN_UI_CONTROL_CANDIDATE_CONTEXT.tsv",
        "DLC_BKN_UI_HEADER_BOUNDARY_AUDIT.tsv",
        "DLC_BKN_UI_CONTROL_SCHEMA_GAPS.tsv",
        "SUMMARY.json",
        "REPORT_MANIFEST.json",
    )
    for name in required:
        if not (report_root / name).is_file():
            raise BknUiControlSchemaError(f"missing report file: {name}")
    summary = json.loads((report_root / "SUMMARY.json").read_text(encoding="utf-8"))
    if summary.get("type") != "br_quartet_legacy_dlc_bkn_ui_control_schema_summary" or summary.get("tool_version") != TOOL_VERSION:
        raise BknUiControlSchemaError("invalid BKN UI control-schema summary")
    if int(summary.get("stage43_structural_candidates", 0)) <= 0:
        raise BknUiControlSchemaError("control-schema report has no stage-43 candidates")
    if int(summary.get("selected_ui_member_pairs", 0)) <= 0:
        raise BknUiControlSchemaError("control-schema report has no selected member pairs")
    if summary.get("unresolved_installation_blockers") != 4:
        raise BknUiControlSchemaError("expected four fail-closed blockers")
    policy = summary.get("policy", {})
    for key in (
        "game_modified", "git_modified", "candidate_installed", "profile_registered", "profile_build_allowed",
        "profiles_activated", "runtime_validated", "system_table_modified", "ui_modified", "translation_modified",
        "raw_assets_exported_in_report", "raw_assets_in_update", "raw_ui_payload_exported",
        "isolated_control_integer_is_ui_binding_proof", "header_crossing_integer_is_ui_binding_proof",
        "structural_boundary_integer_is_ui_binding_proof",
    ):
        if policy.get(key) is not False:
            raise BknUiControlSchemaError(f"fail-closed policy violation: {key}")
    if policy.get("text_seed_unchanged") is not True:
        raise BknUiControlSchemaError("text seed must remain unchanged")

    candidate_rows = read_tsv(report_root / "DLC_BKN_UI_STRUCTURAL_CANDIDATES.tsv")
    if len(candidate_rows) != int(summary["stage43_structural_candidates"]):
        raise BknUiControlSchemaError("structural candidate count mismatch")
    if not all(row.get("raw_payload_exported") == "false" for row in candidate_rows):
        raise BknUiControlSchemaError("candidate rows claim raw payload export")
    allowed = {
        "kslt_header_cross_field_collision",
        "kslt_header_field_numeric_candidate",
        "structural_boundary_numeric_collision",
        "unchanged_control_numeric_collision",
        "local_multi_bkn_control_pattern_candidate",
        "shared_control_pattern_numeric_collision",
        "isolated_changed_control_numeric_candidate",
        "texture_header_numeric_collision",
        "unclassified_structural_numeric_candidate",
        "kslt_or_kscl_structural_numeric_candidate",
    }
    if any(row.get("candidate_classification") not in allowed for row in candidate_rows):
        raise BknUiControlSchemaError("unknown control-schema classification")

    gap_rows = read_tsv(report_root / "DLC_BKN_UI_CONTROL_SCHEMA_GAPS.tsv")
    if len(gap_rows) != 4 or not all(row.get("blocks_installation") == "true" for row in gap_rows):
        raise BknUiControlSchemaError("installation blockers were weakened")
    for path in report_root.rglob("*"):
        if path.is_file() and ({suffix.casefold() for suffix in path.suffixes} & FORBIDDEN_REPORT_SUFFIXES):
            raise BknUiControlSchemaError(f"raw asset in report: {path}")
    manifest = json.loads((report_root / "REPORT_MANIFEST.json").read_text(encoding="utf-8"))
    for row in manifest.get("files", []):
        path = report_root / row["path"]
        if not path.is_file() or path.stat().st_size != row["size"] or sha256_file(path) != row["sha256"]:
            raise BknUiControlSchemaError(f"report manifest mismatch: {row['path']}")
    return summary


def main() -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    audit_parser = sub.add_parser("audit")
    audit_parser.add_argument("--project-root", required=True)
    audit_parser.add_argument("--source-game", required=True)
    audit_parser.add_argument("--target-game", required=True)
    audit_parser.add_argument("--output-root")
    audit_parser.add_argument("--no-report-archive", action="store_true")
    validate_parser = sub.add_parser("validate-report")
    validate_parser.add_argument("--report-root", required=True)
    args = parser.parse_args()
    try:
        if args.command == "audit":
            project_root = Path(args.project_root).resolve()
            output = Path(args.output_root).resolve() if args.output_root else project_root / ".local/reports/quartet_legacy_dlc" / REPORT_DIR_NAME
            audit(
                project_root,
                Path(args.source_game).resolve(),
                Path(args.target_game).resolve(),
                output,
                create_report_archive=not args.no_report_archive,
            )
        else:
            validate_report(Path(args.report_root).resolve())
    except (
        BknUiControlSchemaError,
        STAGE40.BknUiIndexError,
        STAGE43.BknUiStructureError,
        OSError,
        subprocess.SubprocessError,
        json.JSONDecodeError,
    ) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
