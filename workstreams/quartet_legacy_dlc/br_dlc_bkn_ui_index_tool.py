#!/usr/bin/env python3
"""Read-only BKN costume UI numeric-index and sequence audit.

This stage follows the PE report that found exact BKN/TWL/SCL strings but no
resolved static references. It reopens only the five JP costume/UI members on
each side, hash-gates them against stage 31, and searches for preserved
chara/charabase indices as little-endian numeric values and bounded ordered
sequences. Source/target UI deltas and positive-control families are reported
without exporting payload bytes or modifying UI, tables, PAKs, profiles, Git,
or either game installation.
"""
from __future__ import annotations

import argparse
import contextlib
import csv
import hashlib
import json
import shutil
import struct
import subprocess
import sys
import tarfile
import tempfile
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable, Iterator, Mapping, Sequence

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT_DEFAULT = SCRIPT_DIR.parent.parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import br_dlc_bkn_activation_ui_tool as STAGE31  # noqa: E402
import br_dlc_bkn_index_runtime_tool as STAGE34  # noqa: E402
import br_dlc_bkn_pe_reference_tool as STAGE37  # noqa: E402

TOOL_VERSION = "0.0.17"
FORMAT_VERSION = 1
REPORT_DIR_NAME = "bkn_ui_index_evidence"
REPORT_ARCHIVE_NAME = "BR_quartet_legacy_dlc_bkn_ui_index_evidence.tar.zst"

INDEX_WIDTHS = (2, 4, 8)
MAX_STRIDE = 64
SEQUENCE_MIN_COVERAGE = 8
INTERLEAVED_MIN_COVERAGE = 16
FORBIDDEN_REPORT_SUFFIXES = {
    ".pak", ".ebm", ".ebd", ".g1m", ".g1t", ".g1a", ".g1e", ".g1s",
    ".elixir", ".gz", ".bin", ".swg", ".dds", ".wav", ".ogg", ".exe", ".dll",
    ".kscl", ".kslt",
}


class BknUiIndexError(RuntimeError):
    pass


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


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


def clean_dir(path: Path) -> None:
    if path.exists():
        shutil.rmtree(path)
    path.mkdir(parents=True, exist_ok=True)


def read_tsv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def make_archive(source: Path, output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="br_dlc_bkn_ui_index_bundle_") as temp_name:
        temp_tar = Path(temp_name) / "report.tar"
        with tarfile.open(temp_tar, "w", format=tarfile.PAX_FORMAT) as archive:
            for path in sorted(source.rglob("*"), key=lambda p: p.relative_to(source).as_posix().casefold()):
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
    for path in sorted(root.rglob("*"), key=lambda p: p.relative_to(root).as_posix().casefold()):
        if path.is_file() and path.name != "REPORT_MANIFEST.json":
            rows.append({"path": path.relative_to(root).as_posix(), "size": path.stat().st_size, "sha256": sha256_file(path)})
    return rows


@contextlib.contextmanager
def prerequisite_report(project_root: Path, dir_name: str, archive_name: str, validator: Any) -> Iterator[Path]:
    parent = project_root / ".local/reports/quartet_legacy_dlc"
    direct = parent / dir_name
    if direct.is_dir():
        validator(direct)
        yield direct
        return
    archive = parent / archive_name
    if not archive.is_file():
        raise BknUiIndexError(f"missing prerequisite report: {archive_name}")
    with tempfile.TemporaryDirectory(prefix="br_dlc_bkn_ui_index_prereq_") as temp_name:
        temp = Path(temp_name)
        subprocess.run(["tar", "--zstd", "-xf", str(archive), "-C", str(temp)], check=True)
        candidates = [path for path in temp.iterdir() if path.is_dir()]
        if len(candidates) != 1:
            raise BknUiIndexError(f"could not locate extracted prerequisite: {archive_name}")
        validator(candidates[0])
        yield candidates[0]


def pack_value(value: int, width: int) -> bytes:
    if value < 0 or value >= 1 << (width * 8):
        raise BknUiIndexError(f"index {value} does not fit in {width} bytes")
    return value.to_bytes(width, "little", signed=False)


def find_aligned(payload: bytes, needle: bytes, alignment: int) -> list[int]:
    result: list[int] = []
    start = 0
    while True:
        offset = payload.find(needle, start)
        if offset < 0:
            return result
        if offset % alignment == 0:
            result.append(offset)
        start = offset + 1


def diff_ranges(source: bytes, target: bytes) -> tuple[int, list[tuple[int, int]]]:
    changed = 0
    ranges: list[tuple[int, int]] = []
    limit = min(len(source), len(target))
    start: int | None = None
    for index in range(limit):
        different = source[index] != target[index]
        if different:
            changed += 1
            if start is None:
                start = index
        elif start is not None:
            ranges.append((start, index))
            start = None
    if start is not None:
        ranges.append((start, limit))
    if len(source) != len(target):
        ranges.append((limit, max(len(source), len(target))))
        changed += abs(len(source) - len(target))
    return changed, ranges


def in_ranges(offset: int, width: int, ranges: Sequence[tuple[int, int]]) -> bool:
    end = offset + width
    return any(offset < range_end and end > range_start for range_start, range_end in ranges)


def load_ui_rows(report_root: Path) -> list[dict[str, Any]]:
    rows = read_tsv(report_root / "DLC_BKN_UI_MEMBER_AUDIT.tsv")
    if len(rows) != 10:
        raise BknUiIndexError("stage-31 UI member audit must contain exactly ten rows")
    result: list[dict[str, Any]] = []
    for row in rows:
        if row.get("validation_status") != "passed" or row.get("raw_payload_exported") != "false":
            raise BknUiIndexError("stage-31 UI member row is not clean")
        result.append({
            "side": row["side"],
            "archive": row["archive"],
            "inventory_path": row["inventory_path"],
            "normalized_path": row["normalized_path"],
            "expected_size": int(row["decoded_size"]),
            "expected_sha256": row["decoded_sha256"],
        })
    return result


def read_ui_payloads(rows: Sequence[Mapping[str, Any]], br1_root: Path, quartet_root: Path) -> tuple[dict[tuple[str, str], bytes], list[dict[str, Any]]]:
    indexes: dict[tuple[str, str], Any] = {}
    payloads: dict[tuple[str, str], bytes] = {}
    audit_rows: list[dict[str, Any]] = []
    for row in rows:
        side = str(row["side"])
        game_root = br1_root if side == "source" else quartet_root
        key = (side, str(row["archive"]))
        if key not in indexes:
            indexes[key] = STAGE31.NESTED.index_pak(STAGE31.archive_path(game_root, str(row["archive"])))
        index = indexes[key]
        payload, _entry = STAGE31.NESTED.read_pak_member(index, str(row["inventory_path"]))
        actual_hash = sha256_bytes(payload)
        if len(payload) != int(row["expected_size"]) or actual_hash != str(row["expected_sha256"]):
            raise BknUiIndexError(f"UI member changed since stage 31: {side} {row['normalized_path']}")
        normalized = str(row["normalized_path"])
        payloads[(side, normalized)] = payload
        audit_rows.append({
            **row,
            "detected_pak_format": index.format_name,
            "detected_master_key": index.master_key_label,
            "actual_size": len(payload),
            "actual_sha256": actual_hash,
            "validation_status": "passed",
            "raw_payload_exported": False,
        })
    return payloads, audit_rows


def family_tags(family: str, variant: str) -> tuple[str, ...]:
    suffix = "_W" if variant == "wet" else ""
    if family == "bkn":
        return tuple(f"PC{pc:02d}_DLC_BKN{suffix}" for pc in range(15))
    if family == "twl":
        return tuple(f"PC{pc:02d}_DLC_TWL{suffix}" for pc in range(15))
    if family == "scl":
        return tuple(f"PC{pc:02d}_SCL{suffix}" for pc in range(15))
    raise BknUiIndexError(f"unknown family: {family}")


def index_space_name(table_path: str) -> str:
    return "chara_shared" if table_path in {"chara/chara.xml", "chara/chara_no.xml"} else "charabase"


def build_index_sets(project_root: Path, stage34_root: Path) -> list[dict[str, Any]]:
    bkn_rows = read_tsv(stage34_root / "DLC_BKN_INDEX_BLOCK_AUDIT.tsv")
    if len(bkn_rows) != 90:
        raise BknUiIndexError("stage-34 BKN index audit must contain 90 rows")
    output: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str, str]] = set()
    for row in bkn_rows:
        if row.get("index_preserved") != "true":
            raise BknUiIndexError("BKN index preservation prerequisite failed")
        space = index_space_name(row["table_path"])
        key = (space, "bkn", row["variant"], row["base_tag"])
        if key in seen:
            continue
        seen.add(key)
        output.append({
            "index_space": space,
            "family": "bkn",
            "variant": row["variant"],
            "base_tag": row["base_tag"],
            "source_index": int(row["source_index"]),
            "target_index": int(row["target_index"]),
            "index_preserved": True,
        })

    for side, root in (("source", STAGE34.SOURCE_TABLE_ROOT), ("target", STAGE34.TARGET_TABLE_ROOT)):
        for table_path in ("chara/chara.xml", "chara/charabase.xml"):
            parsed = STAGE34.parse_xml(project_root / root / table_path)
            space = index_space_name(table_path)
            for family in ("twl", "scl"):
                for variant in ("dry", "wet"):
                    tags = family_tags(family, variant)
                    selected = STAGE34.selected_by_attr(parsed, "BaseTag", tags)
                    for tag in tags:
                        key = (space, family, variant, tag)
                        row = next((item for item in output if (item["index_space"], item["family"], item["variant"], item["base_tag"]) == key), None)
                        index = int(selected[tag]["index"])
                        if row is None:
                            output.append({
                                "index_space": space,
                                "family": family,
                                "variant": variant,
                                "base_tag": tag,
                                f"{side}_index": index,
                                "index_preserved": False,
                            })
                        else:
                            row[f"{side}_index"] = index
    for row in output:
        if row["family"] != "bkn":
            if "source_index" not in row or "target_index" not in row:
                raise BknUiIndexError(f"incomplete control index mapping: {row}")
            row["index_preserved"] = row["source_index"] == row["target_index"]
    return sorted(output, key=lambda row: (row["index_space"], row["family"], row["variant"], row["base_tag"]))


def sequences_from_index_sets(rows: Sequence[Mapping[str, Any]], side: str) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    field = f"{side}_index"
    for space in sorted({str(row["index_space"]) for row in rows}):
        for family in ("bkn", "twl", "scl"):
            dry = [row for row in rows if row["index_space"] == space and row["family"] == family and row["variant"] == "dry"]
            wet = [row for row in rows if row["index_space"] == space and row["family"] == family and row["variant"] == "wet"]
            dry.sort(key=lambda row: row["base_tag"])
            wet.sort(key=lambda row: row["base_tag"])
            if len(dry) != 15 or len(wet) != 15:
                raise BknUiIndexError(f"incomplete {space}/{family} control sequence")
            dry_values = [int(row[field]) for row in dry]
            wet_values = [int(row[field]) for row in wet]
            interleaved: list[int] = []
            for dry_value, wet_value in zip(dry_values, wet_values):
                interleaved.extend((dry_value, wet_value))
            for variant, values in (("dry", dry_values), ("wet", wet_values), ("interleaved", interleaved)):
                result.append({
                    "side": side,
                    "index_space": space,
                    "family": family,
                    "variant": variant,
                    "values": values,
                })
    return result


def scan_individual_hits(payload: bytes, sequence_specs: Sequence[Mapping[str, Any]], side: str, member_path: str, changed_ranges: Sequence[tuple[int, int]]) -> list[dict[str, Any]]:
    hits: list[dict[str, Any]] = []
    dedup: set[tuple[str, str, int, int, int]] = set()
    for spec in sequence_specs:
        if spec["side"] != side or spec["variant"] == "interleaved":
            continue
        for ordinal, value in enumerate(spec["values"]):
            for width in INDEX_WIDTHS:
                needle = pack_value(int(value), width)
                for offset in find_aligned(payload, needle, width):
                    key = (spec["index_space"], spec["family"], int(value), width, offset)
                    if key in dedup:
                        continue
                    dedup.add(key)
                    hits.append({
                        "side": side,
                        "member_path": member_path,
                        "member_sha256": sha256_bytes(payload),
                        "index_space": spec["index_space"],
                        "family": spec["family"],
                        "variant": spec["variant"],
                        "ordinal": ordinal,
                        "numeric_value": int(value),
                        "width_bits": width * 8,
                        "endianness": "little",
                        "offset": offset,
                        "offset_aligned": True,
                        "overlaps_source_target_delta": in_ranges(offset, width, changed_ranges),
                        "raw_payload_exported": False,
                    })
    return hits


def scan_sequence_candidates(payload: bytes, specs: Sequence[Mapping[str, Any]], side: str, member_path: str, changed_ranges: Sequence[tuple[int, int]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str, int, int, int, int]] = set()
    for spec in specs:
        if spec["side"] != side:
            continue
        values = [int(value) for value in spec["values"]]
        required = INTERLEAVED_MIN_COVERAGE if spec["variant"] == "interleaved" else SEQUENCE_MIN_COVERAGE
        for width in INDEX_WIDTHS:
            first = pack_value(values[0], width)
            for start in find_aligned(payload, first, width):
                for stride in range(width, MAX_STRIDE + 1, width):
                    matched = 0
                    for ordinal, value in enumerate(values):
                        offset = start + ordinal * stride
                        if offset + width > len(payload) or payload[offset:offset + width] != pack_value(value, width):
                            break
                        matched += 1
                    if matched < required:
                        continue
                    key = (spec["index_space"], spec["family"], spec["variant"], width, start, stride, matched)
                    if key in seen:
                        continue
                    seen.add(key)
                    span_end = start + (matched - 1) * stride + width
                    rows.append({
                        "side": side,
                        "member_path": member_path,
                        "member_sha256": sha256_bytes(payload),
                        "index_space": spec["index_space"],
                        "family": spec["family"],
                        "variant": spec["variant"],
                        "width_bits": width * 8,
                        "endianness": "little",
                        "start_offset": start,
                        "stride_bytes": stride,
                        "matched_values": matched,
                        "expected_values": len(values),
                        "coverage_ratio": matched / len(values),
                        "exact_complete_sequence": matched == len(values),
                        "sequence_span_bytes": span_end - start,
                        "overlaps_source_target_delta": any(start < end and span_end > begin for begin, end in changed_ranges),
                        "raw_payload_exported": False,
                    })
    return rows


def audit(
    project_root: Path,
    br1_root: Path,
    quartet_root: Path,
    output_root: Path,
    *,
    create_report_archive: bool = True,
) -> tuple[Path | None, dict[str, Any]]:
    print("[stage40] validating stage-31 UI, stage-34 index and stage-37 PE reports", flush=True)
    with prerequisite_report(project_root, STAGE31.REPORT_DIR_NAME, STAGE31.REPORT_ARCHIVE_NAME, STAGE31.validate_report) as stage31_root, \
         prerequisite_report(project_root, STAGE34.REPORT_DIR_NAME, STAGE34.REPORT_ARCHIVE_NAME, STAGE34.validate_report) as stage34_root, \
         prerequisite_report(project_root, STAGE37.REPORT_DIR_NAME, STAGE37.REPORT_ARCHIVE_NAME, STAGE37.validate_report) as stage37_root:
        stage37_summary = json.loads((stage37_root / "SUMMARY.json").read_text(encoding="utf-8"))
        if stage37_summary.get("bkn_total_xref_candidates") != 0:
            raise BknUiIndexError("stage 40 is reserved for the no-resolved-PE-reference path")
        ui_rows = load_ui_rows(stage31_root)
        index_sets = build_index_sets(project_root, stage34_root)

    clean_dir(output_root)
    print("[stage40] selectively reopening ten hash-gated JP costume UI members", flush=True)
    payloads, member_audit = read_ui_payloads(ui_rows, br1_root, quartet_root)
    source_specs = sequences_from_index_sets(index_sets, "source")
    target_specs = sequences_from_index_sets(index_sets, "target")
    all_specs = source_specs + target_specs

    paired: dict[str, dict[str, bytes]] = defaultdict(dict)
    for (side, normalized), payload in payloads.items():
        paired[normalized][side] = payload
    delta_rows: list[dict[str, Any]] = []
    delta_map: dict[tuple[str, str], list[tuple[int, int]]] = {}
    for normalized, sides in sorted(paired.items()):
        if set(sides) != {"source", "target"}:
            raise BknUiIndexError(f"UI member pair incomplete: {normalized}")
        changed, ranges = diff_ranges(sides["source"], sides["target"])
        for side in ("source", "target"):
            delta_map[(side, normalized)] = ranges
        delta_rows.append({
            "normalized_path": normalized,
            "source_size": len(sides["source"]),
            "source_sha256": sha256_bytes(sides["source"]),
            "target_size": len(sides["target"]),
            "target_sha256": sha256_bytes(sides["target"]),
            "same_offset_changed_bytes": changed,
            "difference_range_count": len(ranges),
            "size_delta": len(sides["target"]) - len(sides["source"]),
            "payload_identical": sides["source"] == sides["target"],
            "raw_payload_exported": False,
        })

    value_hits: list[dict[str, Any]] = []
    sequence_rows: list[dict[str, Any]] = []
    print("[stage40] scanning aligned 16/32/64-bit values and bounded ordered sequences", flush=True)
    for (side, normalized), payload in sorted(payloads.items()):
        ranges = delta_map[(side, normalized)]
        member_hits = scan_individual_hits(payload, all_specs, side, normalized, ranges)
        member_sequences = scan_sequence_candidates(payload, all_specs, side, normalized, ranges)
        value_hits.extend(member_hits)
        sequence_rows.extend(member_sequences)
        print(f"[stage40] {side}: {normalized} values={len(member_hits)} sequences={len(member_sequences)}", flush=True)

    control_rows: list[dict[str, Any]] = []
    for side, normalized in sorted(payloads):
        for space in ("chara_shared", "charabase"):
            for family in ("bkn", "twl", "scl"):
                hits = [row for row in value_hits if row["side"] == side and row["member_path"] == normalized and row["index_space"] == space and row["family"] == family]
                sequences = [row for row in sequence_rows if row["side"] == side and row["member_path"] == normalized and row["index_space"] == space and row["family"] == family]
                unique_values = sorted({int(row["numeric_value"]) for row in hits})
                classification = "no_index_evidence"
                if sequences:
                    classification = "ordered_index_sequence_candidate"
                elif hits:
                    classification = "isolated_numeric_value_hits"
                control_rows.append({
                    "side": side,
                    "member_path": normalized,
                    "index_space": space,
                    "family": family,
                    "individual_hit_rows": len(hits),
                    "unique_numeric_values": len(unique_values),
                    "sequence_candidates": len(sequences),
                    "complete_sequence_candidates": sum(1 for row in sequences if row["exact_complete_sequence"]),
                    "classification": classification,
                    "ui_owner_binding_proven": False,
                })

    bkn_target_hits = [row for row in value_hits if row["side"] == "target" and row["family"] == "bkn"]
    bkn_target_sequences = [row for row in sequence_rows if row["side"] == "target" and row["family"] == "bkn"]
    if bkn_target_sequences:
        status = "bkn_ui_index_sequence_candidates_found_semantics_unproven"
        owner_status = "candidate_only"
    elif bkn_target_hits:
        status = "bkn_ui_index_value_hits_found_without_sequence"
        owner_status = "candidate_only"
    else:
        status = "bkn_ui_index_values_not_found_in_selected_members"
        owner_status = "unresolved"

    gaps = [
        {"dependency": "owner_ui_slot", "status": owner_status, "blocks_installation": True, "next_evidence": "validate candidate numeric structure against a parsed KSCL/KSLT schema or runtime capture; numeric coincidence is insufficient"},
        {"dependency": "exact_unlock_or_entitlement", "status": "unresolved", "blocks_installation": True, "next_evidence": "identify a proven availability condition without inventing a DLC entitlement"},
        {"dependency": "wet_variant", "status": "conversion_blocked", "blocks_installation": True, "next_evidence": "complete G1M/SWG conversion and exact G1M-to-G1T binding"},
        {"dependency": "runtime_validation", "status": "not_performed", "blocks_installation": True, "next_evidence": "runtime validation remains forbidden until a complete transactional profile exists"},
    ]

    write_tsv(output_root / "DLC_BKN_UI_INDEX_MEMBER_AUDIT.tsv", [
        "side", "archive", "inventory_path", "normalized_path", "expected_size", "expected_sha256", "detected_pak_format", "detected_master_key", "actual_size", "actual_sha256", "validation_status", "raw_payload_exported",
    ], member_audit)
    write_tsv(output_root / "DLC_BKN_UI_SOURCE_TARGET_DELTA.tsv", [
        "normalized_path", "source_size", "source_sha256", "target_size", "target_sha256", "same_offset_changed_bytes", "difference_range_count", "size_delta", "payload_identical", "raw_payload_exported",
    ], delta_rows)
    write_tsv(output_root / "DLC_BKN_UI_INDEX_VALUE_HITS.tsv", [
        "side", "member_path", "member_sha256", "index_space", "family", "variant", "ordinal", "numeric_value", "width_bits", "endianness", "offset", "offset_aligned", "overlaps_source_target_delta", "raw_payload_exported",
    ], sorted(value_hits, key=lambda row: (row["side"], row["member_path"], row["offset"], row["width_bits"], row["index_space"], row["family"], row["numeric_value"])))
    write_tsv(output_root / "DLC_BKN_UI_INDEX_SEQUENCE_CANDIDATES.tsv", [
        "side", "member_path", "member_sha256", "index_space", "family", "variant", "width_bits", "endianness", "start_offset", "stride_bytes", "matched_values", "expected_values", "coverage_ratio", "exact_complete_sequence", "sequence_span_bytes", "overlaps_source_target_delta", "raw_payload_exported",
    ], sorted(sequence_rows, key=lambda row: (row["side"], row["member_path"], row["start_offset"], row["index_space"], row["family"], row["variant"], row["width_bits"], row["stride_bytes"])))
    write_tsv(output_root / "DLC_BKN_UI_INDEX_CONTROL_COMPARISON.tsv", [
        "side", "member_path", "index_space", "family", "individual_hit_rows", "unique_numeric_values", "sequence_candidates", "complete_sequence_candidates", "classification", "ui_owner_binding_proven",
    ], control_rows)
    write_tsv(output_root / "DLC_BKN_UI_INDEX_GAPS.tsv", ["dependency", "status", "blocks_installation", "next_evidence"], gaps)

    summary = {
        "type": "br_quartet_legacy_dlc_bkn_ui_index_summary",
        "format_version": FORMAT_VERSION,
        "tool_version": TOOL_VERSION,
        "content_id": "costume_pc00_bkn",
        "status": status,
        "ui_members_scanned": len(member_audit),
        "ui_member_pairs": len(delta_rows),
        "index_definition_rows": len(index_sets),
        "individual_index_value_hits": len(value_hits),
        "sequence_candidates": len(sequence_rows),
        "bkn_target_value_hits": len(bkn_target_hits),
        "bkn_target_sequence_candidates": len(bkn_target_sequences),
        "complete_bkn_target_sequence_candidates": sum(1 for row in bkn_target_sequences if row["exact_complete_sequence"]),
        "control_comparison_rows": len(control_rows),
        "unresolved_installation_blockers": len(gaps),
        "findings": [
            "stage-37 PE strings have no resolved static references, so this stage moves to numeric index evidence in the selected costume UI members",
            "BKN, TWL and SCL chara/charabase indices are scanned as aligned little-endian 16/32/64-bit values and bounded ordered sequences",
            "source-target UI changes are recorded only as hashes, sizes and difference counts; no KSCL/KSLT payload bytes are exported",
            "isolated integer hits and even ordered sequences remain candidate-only until a real KSCL/KSLT schema or runtime observation proves ownership",
            "no UI, table, PAK, module, profile, Translation record, Git state or game installation is modified",
        ],
        "next_action": "use any bounded BKN sequence candidates to identify a KSCL/KSLT structure; otherwise retain the proven charabase fallback and continue availability discovery without inventing an entitlement",
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
            "numeric_index_hit_is_ui_binding_proof": False,
            "ordered_numeric_sequence_is_ui_binding_proof": False,
            "text_seed_unchanged": True,
        },
    }
    write_json(output_root / "SUMMARY.json", summary)
    write_json(output_root / "REPORT_MANIFEST.json", {"type": "br_report_manifest", "format_version": 1, "files": report_manifest(output_root)})
    archive: Path | None = None
    if create_report_archive:
        archive = output_root.parent / REPORT_ARCHIVE_NAME
        make_archive(output_root, archive)
        print(f"[stage40] report: {archive}", flush=True)
    return archive, summary


def validate_report(report_root: Path) -> dict[str, Any]:
    required = (
        "DLC_BKN_UI_INDEX_MEMBER_AUDIT.tsv",
        "DLC_BKN_UI_SOURCE_TARGET_DELTA.tsv",
        "DLC_BKN_UI_INDEX_VALUE_HITS.tsv",
        "DLC_BKN_UI_INDEX_SEQUENCE_CANDIDATES.tsv",
        "DLC_BKN_UI_INDEX_CONTROL_COMPARISON.tsv",
        "DLC_BKN_UI_INDEX_GAPS.tsv",
        "SUMMARY.json",
        "REPORT_MANIFEST.json",
    )
    for name in required:
        if not (report_root / name).is_file():
            raise BknUiIndexError(f"missing report file: {name}")
    summary = json.loads((report_root / "SUMMARY.json").read_text(encoding="utf-8"))
    if summary.get("type") != "br_quartet_legacy_dlc_bkn_ui_index_summary" or summary.get("tool_version") != TOOL_VERSION:
        raise BknUiIndexError("invalid BKN UI index summary")
    if summary.get("ui_members_scanned") != 10 or summary.get("ui_member_pairs") != 5:
        raise BknUiIndexError("incomplete BKN UI index member audit")
    if summary.get("index_definition_rows") != 180:
        raise BknUiIndexError("expected 180 deduplicated BKN/TWL/SCL index definitions")
    if summary.get("unresolved_installation_blockers") != 4:
        raise BknUiIndexError("expected four fail-closed blockers")
    policy = summary.get("policy", {})
    for key in (
        "game_modified", "git_modified", "candidate_installed", "profile_registered", "profile_build_allowed",
        "profiles_activated", "runtime_validated", "system_table_modified", "ui_modified", "translation_modified",
        "raw_assets_exported_in_report", "raw_assets_in_update", "raw_ui_payload_exported",
        "numeric_index_hit_is_ui_binding_proof", "ordered_numeric_sequence_is_ui_binding_proof",
    ):
        if policy.get(key) is not False:
            raise BknUiIndexError(f"fail-closed policy violation: {key}")
    if policy.get("text_seed_unchanged") is not True:
        raise BknUiIndexError("text seed must remain unchanged")
    member_rows = read_tsv(report_root / "DLC_BKN_UI_INDEX_MEMBER_AUDIT.tsv")
    if len(member_rows) != 10 or not all(row.get("validation_status") == "passed" and row.get("raw_payload_exported") == "false" for row in member_rows):
        raise BknUiIndexError("invalid UI member audit rows")
    gap_rows = read_tsv(report_root / "DLC_BKN_UI_INDEX_GAPS.tsv")
    if len(gap_rows) != 4 or not all(row.get("blocks_installation") == "true" for row in gap_rows):
        raise BknUiIndexError("installation blockers were weakened")
    for path in report_root.rglob("*"):
        if path.is_file() and ({suffix.casefold() for suffix in path.suffixes} & FORBIDDEN_REPORT_SUFFIXES):
            raise BknUiIndexError(f"raw asset in report: {path}")
    manifest = json.loads((report_root / "REPORT_MANIFEST.json").read_text(encoding="utf-8"))
    for row in manifest.get("files", []):
        path = report_root / row["path"]
        if not path.is_file() or path.stat().st_size != row["size"] or sha256_file(path) != row["sha256"]:
            raise BknUiIndexError(f"report manifest mismatch: {row['path']}")
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
            audit(project_root, Path(args.source_game).resolve(), Path(args.target_game).resolve(), output, create_report_archive=not args.no_report_archive)
        else:
            validate_report(Path(args.report_root).resolve())
    except (BknUiIndexError, STAGE31.BknActivationUiError, STAGE34.BknIndexRuntimeError, STAGE37.BknPeReferenceError, OSError, subprocess.SubprocessError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
