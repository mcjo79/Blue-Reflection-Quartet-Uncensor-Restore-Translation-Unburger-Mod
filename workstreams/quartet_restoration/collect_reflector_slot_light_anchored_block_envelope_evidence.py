#!/usr/bin/env python3
"""Audit full anchored block envelopes around focal slot-light records.

Stage 94 confirmed that thirteen section-table bindings land exactly 108 bytes
before their selected records, but the 27-dword pre-record structures do not
distinguish the duplicate target 75 occurrences.  The first dword of those
structures appears to encode the distance to the next anchor (560/608/640
bytes), so this stage tests that block-span model against the actual bounded
G1E/G1EM payloads and compares complete anchored blocks rather than only their
108-byte prefixes.

The collector is read-only.  It exports only offsets, numeric classifications,
counts and SHA-256 hashes.  It never writes G1E/G1EM, Elixir, PAK, registry or
installed-game payloads and never infers brightness or censorship semantics.
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
PROJECT_ROOT_DEFAULT = SCRIPT_DIR.parent.parent

TOOL_VERSION = "0.1.9"
REPORT_NAME = "BR_quartet_restoration_reflector_slot_light_anchored_block_envelope_evidence.tar.zst"
REPORT_DIR = "reflector_slot_light_anchored_block_envelope_evidence"
STAGE79_DIR = "reflector_character_slot_render_member_evidence"
STAGE79_ARCHIVE = "BR_quartet_restoration_reflector_character_slot_render_member_evidence.tar.zst"
STAGE94_DIR = "reflector_slot_light_pre_record_anchor_header_evidence"
STAGE94_ARCHIVE = "BR_quartet_restoration_reflector_slot_light_pre_record_anchor_header_evidence.tar.zst"

EXPECTED_PARENT_CONTAINERS = 4
EXPECTED_SIBLING_PAIRS = 540
EXPECTED_FOCAL_OCCURRENCES = 21
EXPECTED_PRE_RECORD_DWORDS = 567
EXPECTED_DOMINANT_BINDINGS = 13
PRE_RECORD_BYTES = 108
RECORD_BYTES = 44
REFERENCE_DWORD = 10


class Stage95Error(RuntimeError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise Stage95Error(message)


def progress(message: str) -> None:
    print(f"[stage95] {message}", file=sys.stderr, flush=True)


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


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def stable_key(path: str, member_key: str) -> tuple[str, str]:
    return path.casefold(), member_key.casefold()


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
        raise Stage95Error(f"invalid JSON {path}: {exc}") from exc
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


def load_module(path: Path, name: str):
    require(path.is_file(), f"missing prerequisite collector: {path}")
    spec = importlib.util.spec_from_file_location(name, path)
    require(spec is not None and spec.loader is not None, f"cannot load module: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def u32(payload: bytes, offset: int) -> int:
    require(offset >= 0 and offset + 4 <= len(payload) and offset % 4 == 0, f"invalid dword offset {offset}")
    return int.from_bytes(payload[offset:offset + 4], "little")


def byte_diff(left: bytes, right: bytes) -> int:
    if len(left) != len(right):
        return max(len(left), len(right))
    return sum(a != b for a, b in zip(left, right))


def dword_diff(left: bytes, right: bytes) -> int:
    require(len(left) == len(right) and len(left) % 4 == 0, "dword comparison requires equal aligned blocks")
    return sum(left[offset:offset + 4] != right[offset:offset + 4] for offset in range(0, len(left), 4))


def validate_stage94(root: Path) -> dict[str, Any]:
    summary = load_json(root / "SUMMARY.json")
    require(summary.get("type") == "br_quartet_restoration_reflector_slot_light_pre_record_anchor_header_evidence_summary", "stage94 type mismatch")
    require(summary.get("tool_version") == "0.1.8", "stage94 tool version mismatch")
    require(parse_int(summary.get("sibling_G1E_G1EM_member_rows"), -1) == EXPECTED_SIBLING_PAIRS, "stage94 sibling-pair count mismatch")
    require(parse_int(summary.get("focal_occurrence_rows"), -1) == EXPECTED_FOCAL_OCCURRENCES, "stage94 focal occurrence count mismatch")
    require(parse_int(summary.get("pre_record_dword_rows"), -1) == EXPECTED_PRE_RECORD_DWORDS, "stage94 dword count mismatch")
    require(parse_int(summary.get("dominant_binding_rows"), -1) == EXPECTED_DOMINANT_BINDINGS, "stage94 dominant binding count mismatch")
    require(parse_bool(summary.get("pre_record_anchor_geometry_confirmed")), "stage94 anchor geometry not confirmed")
    require(not parse_bool(summary.get("candidate_target_occurrence_identity_resolved")), "stage94 unexpectedly resolved occurrence identity")
    require(not parse_bool(summary.get("pre_record_header_role_resolved")), "stage94 unexpectedly resolved header role")
    require(parse_int(summary.get("prototype_candidate_rows"), -1) == 0, "stage94 unexpectedly authorized prototype")
    require(not parse_bool(summary.get("brightness_semantics_confirmed")), "stage94 unexpectedly confirmed brightness")
    require(not parse_bool(summary.get("censorship_semantics_confirmed")), "stage94 unexpectedly confirmed censorship")
    require(parse_int(summary.get("skipped_rows"), -1) == 0, "stage94 contains skipped rows")
    return summary


def structural_targets(rows: Sequence[Mapping[str, Any]], endpoint: int) -> dict[int, set[str]]:
    result: dict[int, set[str]] = defaultdict(set)
    if endpoint >= 0:
        result[endpoint].add("section_header")
    for row in rows:
        anchor = parse_int(row.get("anchor"), -1)
        record_start = parse_int(row.get("record_start"), -1)
        reference_offset = parse_int(row.get("reference_offset"), record_start + REFERENCE_DWORD * 4)
        declared_span = parse_int(row.get("declared_block_span"), -1)
        if anchor >= 0:
            result[anchor].add("block_anchor")
        if record_start >= 0:
            result[record_start].add("record_start")
        if reference_offset >= 0:
            result[reference_offset].add("reference_field")
        if anchor >= 0 and declared_span > 0:
            result[anchor + declared_span].add("block_end")
    return result


def normalize_block(payload: bytes, anchor: int, span: int, targets: Mapping[int, set[str]]) -> tuple[bytes, list[dict[str, Any]]]:
    block = bytearray(payload[anchor:anchor + span])
    rows: list[dict[str, Any]] = []
    for relative in range(0, span, 4):
        field_offset = anchor + relative
        value = int.from_bytes(block[relative:relative + 4], "little")
        displacement = signed_i32(value)
        if displacement == 0:
            continue
        target = field_offset + displacement
        roles = targets.get(target)
        if not roles:
            continue
        rows.append({
            "relative_dword": relative // 4,
            "field_offset": field_offset,
            "u32_hex": f"0x{value:08x}",
            "i32": displacement,
            "field_relative_target": target,
            "target_roles": " | ".join(sorted(roles)),
        })
        block[relative:relative + 4] = b"\0\0\0\0"
    return bytes(block), rows


def build_report(
    project_root: Path,
    *,
    create_archive: bool = True,
    report_root: Path | None = None,
    workspace_root: Path | None = None,
    rules_file: Path | None = None,
    maximum_earc_bytes: int = 512 * 1024 * 1024,
    container_loader: Callable[..., tuple[list[dict[str, Any]], list[dict[str, Any]]]] | None = None,
) -> tuple[Path, Path | None, dict[str, Any]]:
    project_root = project_root.resolve()
    reports = (report_root or project_root / ".local/reports/quartet_restoration").resolve()
    workspace = (workspace_root or project_root / ".local/build/quartet_restoration").resolve()
    require(reports.is_dir(), f"missing report root: {reports}")

    stage81 = load_module(project_root / "workstreams/quartet_restoration/collect_reflector_ringlight_control_callsite_evidence.py", "stage81_for_stage95")
    stage86 = load_module(project_root / "workstreams/quartet_restoration/collect_reflector_slot_light_shared_record_template_evidence.py", "stage86_for_stage95")

    progress("validating stage 79 and stage 94 reports")
    with tempfile.TemporaryDirectory(prefix="br-stage95-") as temporary_name:
        temporary = Path(temporary_name)
        stage79_root = locate(reports, STAGE79_DIR, STAGE79_ARCHIVE, temporary / "79")
        stage94_root = locate(reports, STAGE94_DIR, STAGE94_ARCHIVE, temporary / "94")
        stage81.validate_stage79(stage79_root)
        summary94 = validate_stage94(stage94_root)
        audit_rows = read_tsv(stage94_root / "SLOT_LIGHT_PRE_RECORD_ANCHOR_AUDIT.tsv")
        candidate_sequence = read_tsv(stage94_root / "SLOT_LIGHT_CANDIDATE_PRE_RECORD_SEQUENCE.tsv")
        require(len(audit_rows) == EXPECTED_FOCAL_OCCURRENCES, "stage94 anchor audit count mismatch")
        require(len(candidate_sequence) == 7, "stage94 candidate sequence count mismatch")

        parent_scope = stage81.select_parent_scope(stage79_root)
        actual_rules = rules_file or project_root / "titles/blue_reflection/modules/quartet_restoration/mappings/effect_material_rules.tsv"
        loader = container_loader or stage81.load_parent_containers
        progress("rehydrating the four bounded parent effect containers")
        containers, skipped = loader(
            scope_rows=parent_scope,
            workspace_root=workspace,
            report_root=reports,
            rules_file=actual_rules,
            maximum_earc_bytes=maximum_earc_bytes,
        )
        require(not skipped, f"parent container loader skipped {len(skipped)} rows")
        require(len(containers) == EXPECTED_PARENT_CONTAINERS, f"expected {EXPECTED_PARENT_CONTAINERS} parent containers, found {len(containers)}")
        pair_by_key, all_pairs = stage86.index_pairs(containers)
        require(len(all_pairs) == EXPECTED_SIBLING_PAIRS, f"expected {EXPECTED_SIBLING_PAIRS} sibling pairs, found {len(all_pairs)}")

        grouped: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
        for row in audit_rows:
            key = (row.get("normalized_path", "").casefold(), row.get("member_key", "").casefold(), row.get("side", "").casefold())
            grouped[key].append(dict(row))
        for rows in grouped.values():
            rows.sort(key=lambda row: parse_int(row.get("anchor"), -1))
            for index, row in enumerate(rows):
                row["next_anchor"] = parse_int(rows[index + 1].get("anchor"), -1) if index + 1 < len(rows) else -1

        layout_rows: list[dict[str, Any]] = []
        relocation_rows: list[dict[str, Any]] = []
        segment_rows: list[dict[str, Any]] = []
        skipped_rows: list[dict[str, Any]] = []
        occurrence_data: dict[tuple[str, str, str, int], dict[str, Any]] = {}
        nonterminal_rows = 0
        nonterminal_chain_exact = 0

        progress(f"auditing {len(audit_rows)} full anchored block envelopes")
        for group_key, rows in grouped.items():
            path_cf, member_cf, side = group_key
            pair = pair_by_key.get((path_cf, member_cf))
            require(pair is not None, f"missing focal pair: {group_key}")
            payload = pair[f"{side}_payload"]
            endpoint = parse_int(rows[0].get("endpoint"), -1)

            # Read declared spans first so structural-target normalization can include block ends.
            for row in rows:
                anchor = parse_int(row.get("anchor"), -1)
                require(anchor >= 0 and anchor % 4 == 0 and anchor + 4 <= len(payload), f"invalid anchor {anchor}")
                row["declared_block_span"] = u32(payload, anchor)
                row["reference_offset"] = parse_int(row.get("reference_offset"), parse_int(row.get("record_start"), -1) + REFERENCE_DWORD * 4)
            targets = structural_targets(rows, endpoint)

            for row in rows:
                anchor = parse_int(row.get("anchor"), -1)
                record_start = parse_int(row.get("record_start"), -1)
                reference_offset = parse_int(row.get("reference_offset"), -1)
                span = parse_int(row.get("declared_block_span"), -1)
                next_anchor = parse_int(row.get("next_anchor"), -1)
                block_end = anchor + span
                in_bounds = span > 0 and span % 4 == 0 and block_end <= len(payload)
                if not in_bounds or record_start != anchor + PRE_RECORD_BYTES or reference_offset != record_start + REFERENCE_DWORD * 4 or record_start + RECORD_BYTES > block_end:
                    skipped_rows.append({
                        "scope": "occurrence", "member_name": row.get("member_name", pair.get("member_name", "")), "side": side,
                        "anchor": anchor, "record_start": record_start, "reason": "invalid_declared_span_or_record_geometry",
                    })
                    continue
                chain_exact = ""
                if next_anchor >= 0:
                    nonterminal_rows += 1
                    chain_exact = block_end == next_anchor
                    nonterminal_chain_exact += int(bool(chain_exact))
                block = payload[anchor:block_end]
                normalized, relocations = normalize_block(payload, anchor, span, targets)
                prefix = block[:PRE_RECORD_BYTES]
                record = block[PRE_RECORD_BYTES:PRE_RECORD_BYTES + RECORD_BYTES]
                trailer = block[PRE_RECORD_BYTES + RECORD_BYTES:]
                normalized_prefix = normalized[:PRE_RECORD_BYTES]
                normalized_record = normalized[PRE_RECORD_BYTES:PRE_RECORD_BYTES + RECORD_BYTES]
                normalized_trailer = normalized[PRE_RECORD_BYTES + RECORD_BYTES:]
                occurrence_key = (path_cf, member_cf, side, parse_int(row.get("reference_index"), -1))
                occurrence_data[occurrence_key] = {
                    "row": row, "raw": block, "normalized": normalized,
                    "prefix": prefix, "record": record, "trailer": trailer,
                    "normalized_prefix": normalized_prefix, "normalized_record": normalized_record, "normalized_trailer": normalized_trailer,
                }
                for relocation in relocations:
                    relocation_rows.append({
                        "cluster_role": row.get("cluster_role", ""), "normalized_path": row.get("normalized_path", ""),
                        "member_key": row.get("member_key", ""), "member_name": row.get("member_name", pair.get("member_name", "")),
                        "side": side, "reference_index": row.get("reference_index", ""), "variant_label": row.get("variant_label", ""),
                        "anchor": anchor, **relocation,
                    })
                layout_rows.append({
                    "cluster_role": row.get("cluster_role", ""), "normalized_path": row.get("normalized_path", ""),
                    "member_key": row.get("member_key", ""), "member_name": row.get("member_name", pair.get("member_name", "")),
                    "side": side, "reference_index": row.get("reference_index", ""), "variant_label": row.get("variant_label", ""),
                    "endpoint": endpoint, "anchor": anchor, "record_start": record_start, "reference_offset": reference_offset,
                    "declared_block_span": span, "block_end": block_end, "next_anchor": "" if next_anchor < 0 else next_anchor,
                    "nonterminal_chain_exact": chain_exact, "block_in_bounds": in_bounds,
                    "header_word1_u32": u32(payload, anchor + 4), "header_word2_u32": u32(payload, anchor + 8),
                    "record_offset_within_block": record_start - anchor, "reference_offset_within_block": reference_offset - anchor,
                    "trailer_bytes": len(trailer), "relocation_fields_normalized": len(relocations),
                    "raw_block_sha256": sha256(block), "normalized_block_sha256": sha256(normalized),
                })
                for name, raw_segment, normalized_segment, offset in (
                    ("pre_record_prefix", prefix, normalized_prefix, 0),
                    ("reference_record", record, normalized_record, PRE_RECORD_BYTES),
                    ("post_record_trailer", trailer, normalized_trailer, PRE_RECORD_BYTES + RECORD_BYTES),
                    ("full_anchored_block", block, normalized, 0),
                ):
                    segment_rows.append({
                        "cluster_role": row.get("cluster_role", ""), "member_name": row.get("member_name", pair.get("member_name", "")),
                        "side": side, "reference_index": row.get("reference_index", ""), "variant_label": row.get("variant_label", ""),
                        "anchor": anchor, "segment": name, "relative_offset": offset, "segment_bytes": len(raw_segment),
                        "raw_sha256": sha256(raw_segment), "normalized_sha256": sha256(normalized_segment),
                    })

        require(not skipped_rows, f"anchored block audit skipped {len(skipped_rows)} rows")
        require(len(layout_rows) == EXPECTED_FOCAL_OCCURRENCES, "anchored block layout count mismatch")

        def candidate_occurrence(side: str, variant: str, ordinal: int = 0) -> dict[str, Any]:
            matches = [value for key, value in occurrence_data.items() if key[2] == side and value["row"].get("cluster_role") == "candidate_ringlight" and value["row"].get("variant_label") == variant]
            matches.sort(key=lambda value: parse_int(value["row"].get("reference_index"), -1))
            require(ordinal < len(matches), f"missing candidate occurrence {side} {variant} #{ordinal}")
            return matches[ordinal]

        source30 = candidate_occurrence("source", "equal_float_30")
        target30 = candidate_occurrence("target", "equal_float_30")
        source150 = candidate_occurrence("source", "equal_float_150")
        target75a = candidate_occurrence("target", "equal_float_75", 0)
        target75b = candidate_occurrence("target", "equal_float_75", 1)
        source2 = candidate_occurrence("source", "equal_float_2")
        target2 = candidate_occurrence("target", "equal_float_2")

        comparisons: list[dict[str, Any]] = []
        comparison_specs = [
            ("stable_30_source_target", source30, target30),
            ("ambiguous_150_to_first_75", source150, target75a),
            ("ambiguous_150_to_second_75", source150, target75b),
            ("duplicate_target_75_pair", target75a, target75b),
            ("stable_2_source_target", source2, target2),
        ]
        for label, left, right in comparison_specs:
            same_size = len(left["raw"]) == len(right["raw"])
            comparisons.append({
                "comparison": label,
                "left_side": left["row"].get("side", ""), "left_reference_index": left["row"].get("reference_index", ""),
                "left_variant_label": left["row"].get("variant_label", ""), "left_anchor": left["row"].get("anchor", ""),
                "right_side": right["row"].get("side", ""), "right_reference_index": right["row"].get("reference_index", ""),
                "right_variant_label": right["row"].get("variant_label", ""), "right_anchor": right["row"].get("anchor", ""),
                "same_declared_span": same_size, "left_bytes": len(left["raw"]), "right_bytes": len(right["raw"]),
                "raw_byte_differences": byte_diff(left["raw"], right["raw"]),
                "normalized_byte_differences": byte_diff(left["normalized"], right["normalized"]),
                "normalized_dword_differences": dword_diff(left["normalized"], right["normalized"]) if same_size else "",
                "raw_exact": left["raw"] == right["raw"], "normalized_exact": left["normalized"] == right["normalized"],
                "prefix_normalized_exact": left["normalized_prefix"] == right["normalized_prefix"],
                "record_normalized_exact": left["normalized_record"] == right["normalized_record"],
                "trailer_normalized_exact": left["normalized_trailer"] == right["normalized_trailer"],
            })

        by_label = {row["comparison"]: row for row in comparisons}
        first_diff = parse_int(by_label["ambiguous_150_to_first_75"]["normalized_byte_differences"], -1)
        second_diff = parse_int(by_label["ambiguous_150_to_second_75"]["normalized_byte_differences"], -1)
        duplicate_normalized_exact = parse_bool(by_label["duplicate_target_75_pair"]["normalized_exact"])
        unique_exact_source_peer = (
            parse_bool(by_label["ambiguous_150_to_first_75"]["normalized_exact"])
            != parse_bool(by_label["ambiguous_150_to_second_75"]["normalized_exact"])
        )
        identity_resolved = bool(unique_exact_source_peer and not duplicate_normalized_exact)
        identity_reason = (
            "one target 75 has an exact normalized full-block source-150 counterpart and the other does not"
            if identity_resolved else
            "duplicate target blocks are equivalent or neither has a unique exact normalized source-150 counterpart"
        )

        sequence_rows: list[dict[str, Any]] = []
        for layout in sorted(
            [row for row in layout_rows if row.get("cluster_role") == "candidate_ringlight"],
            key=lambda row: (0 if row.get("side") == "source" else 1, parse_int(row.get("reference_index"), -1)),
        ):
            sequence_rows.append({
                "side": layout.get("side", ""), "reference_index": layout.get("reference_index", ""),
                "variant_label": layout.get("variant_label", ""), "anchor": layout.get("anchor", ""),
                "declared_block_span": layout.get("declared_block_span", ""), "header_word1_u32": layout.get("header_word1_u32", ""),
                "raw_block_sha256": layout.get("raw_block_sha256", ""), "normalized_block_sha256": layout.get("normalized_block_sha256", ""),
            })

        output = reports / REPORT_DIR
        if output.exists():
            import shutil
            shutil.rmtree(output)
        output.mkdir(parents=True)
        write_tsv(output / "SLOT_LIGHT_ANCHORED_BLOCK_LAYOUT.tsv", [
            "cluster_role", "normalized_path", "member_key", "member_name", "side", "reference_index", "variant_label", "endpoint",
            "anchor", "record_start", "reference_offset", "declared_block_span", "block_end", "next_anchor", "nonterminal_chain_exact",
            "block_in_bounds", "header_word1_u32", "header_word2_u32", "record_offset_within_block", "reference_offset_within_block",
            "trailer_bytes", "relocation_fields_normalized", "raw_block_sha256", "normalized_block_sha256",
        ], layout_rows)
        write_tsv(output / "SLOT_LIGHT_ANCHORED_BLOCK_RELOCATION_FIELDS.tsv", [
            "cluster_role", "normalized_path", "member_key", "member_name", "side", "reference_index", "variant_label", "anchor",
            "relative_dword", "field_offset", "u32_hex", "i32", "field_relative_target", "target_roles",
        ], relocation_rows)
        write_tsv(output / "SLOT_LIGHT_ANCHORED_BLOCK_SEGMENT_HASHES.tsv", [
            "cluster_role", "member_name", "side", "reference_index", "variant_label", "anchor", "segment", "relative_offset",
            "segment_bytes", "raw_sha256", "normalized_sha256",
        ], segment_rows)
        write_tsv(output / "SLOT_LIGHT_ANCHORED_BLOCK_PAIRWISE_COMPARISON.tsv", [
            "comparison", "left_side", "left_reference_index", "left_variant_label", "left_anchor", "right_side", "right_reference_index",
            "right_variant_label", "right_anchor", "same_declared_span", "left_bytes", "right_bytes", "raw_byte_differences",
            "normalized_byte_differences", "normalized_dword_differences", "raw_exact", "normalized_exact", "prefix_normalized_exact",
            "record_normalized_exact", "trailer_normalized_exact",
        ], comparisons)
        write_tsv(output / "SLOT_LIGHT_CANDIDATE_ANCHORED_BLOCK_SEQUENCE.tsv", [
            "side", "reference_index", "variant_label", "anchor", "declared_block_span", "header_word1_u32", "raw_block_sha256", "normalized_block_sha256",
        ], sequence_rows)
        decision_rows = [
            {"question": "does dword 0 define the next anchored-block boundary for every nonterminal focal occurrence", "answer": nonterminal_rows > 0 and nonterminal_chain_exact == nonterminal_rows, "classification": "anchored_block_span_field_confirmed" if nonterminal_rows > 0 and nonterminal_chain_exact == nonterminal_rows else "span_model_not_confirmed"},
            {"question": "are the two target 75 full blocks distinct after structural-reference normalization", "answer": not duplicate_normalized_exact, "classification": "duplicate_target_blocks_distinct" if not duplicate_normalized_exact else "duplicate_target_blocks_equivalent"},
            {"question": "does exactly one target 75 have an exact normalized full-block counterpart in source 150", "answer": identity_resolved, "classification": "target_occurrence_identity_resolved" if identity_resolved else "target_occurrence_identity_unresolved"},
        ]
        write_tsv(output / "SLOT_LIGHT_ANCHORED_BLOCK_IDENTITY_DECISION.tsv", ["question", "answer", "classification"], decision_rows)
        write_tsv(output / "SLOT_LIGHT_ANCHORED_BLOCK_ENVELOPE_SKIPPED.tsv", ["scope", "member_name", "side", "anchor", "record_start", "reason"], skipped_rows)

        summary = {
            "type": "br_quartet_restoration_reflector_slot_light_anchored_block_envelope_evidence_summary",
            "format_version": 1,
            "tool_version": TOOL_VERSION,
            "source_stage94_tool_version": summary94.get("tool_version"),
            "sibling_G1E_G1EM_member_rows": len(all_pairs),
            "focal_occurrence_rows": len(layout_rows),
            "anchored_block_layout_rows": len(layout_rows),
            "nonterminal_focal_occurrence_rows": nonterminal_rows,
            "nonterminal_declared_span_chain_exact_rows": nonterminal_chain_exact,
            "anchored_block_span_field_confirmed": nonterminal_rows > 0 and nonterminal_chain_exact == nonterminal_rows,
            "block_prefix_geometry_confirmed": len(layout_rows) == EXPECTED_FOCAL_OCCURRENCES and not skipped_rows,
            "relocation_field_rows": len(relocation_rows),
            "segment_hash_rows": len(segment_rows),
            "pairwise_comparison_rows": len(comparisons),
            "candidate_target_duplicate_75_normalized_full_blocks_exact": duplicate_normalized_exact,
            "candidate_source_150_to_target_75_normalized_diff_equal": first_diff == second_diff,
            "candidate_source_150_to_first_target_75_normalized_byte_differences": first_diff,
            "candidate_source_150_to_second_target_75_normalized_byte_differences": second_diff,
            "candidate_target_occurrence_identity_resolved": identity_resolved,
            "candidate_target_occurrence_identity_reason": identity_reason,
            "pre_record_header_role_resolved": False,
            "technical_leaf_semantics_resolved": False,
            "brightness_semantics_confirmed": False,
            "censorship_semantics_confirmed": False,
            "prototype_candidate_rows": 0,
            "skipped_rows": len(skipped_rows),
            "status": "anchored_block_span_geometry_audited_duplicate_target_identity_requires_unique_full_block_peer",
            "next_action": "Upload this report. If the two target 75 full blocks remain equivalent or have equal distance to the source 150 block, continue only with a read-only internal trailer/subrecord audit; do not write G1E or infer brightness/censorship.",
            "parameters": {
                "pre_record_bytes": PRE_RECORD_BYTES,
                "record_bytes": RECORD_BYTES,
                "reference_dword": REFERENCE_DWORD,
                "normalization": "zero only exact signed field-relative references to bounded section/anchor/record/reference/block landmarks",
                "identity_gate": "exactly one target 75 must have an exact normalized full-block source-150 counterpart and the duplicate target blocks must not be equivalent",
            },
            "policy": {
                "full_proprietary_payloads_exported": False,
                "render_payload_written": False,
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
    except Stage95Error as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print(f"Output: {output}")
    if archive is not None:
        print(f"Report: {archive}")
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
