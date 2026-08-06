#!/usr/bin/env python3
"""Stage 139: exact-layout calibration for broad G1E families and non-metadata KPS paths.

The collector consumes the immutable stage-137 parser queue and the canonical
stage-138 runtime integration. It rehydrates only the seven bounded effect/
posteffect containers, then:

* scans every member from the seven broad recurrent G1E families for the exact
  section-header/table layout already established by the earlier slot-light
  format work;
* binds conservative source/target alignment gaps to those exact section
  envelopes where possible;
* parses the six non-metadata KPS paths down to RDEF resources, constant
  buffers, variables, signatures and instruction-opcode inventories.

The report contains metadata only. It does not assign leaf meaning, visual or
censorship semantics, does not runtime-validate any additional profile and does
not authorize any write.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
from collections import Counter, defaultdict
from pathlib import Path, PurePosixPath
from typing import Any, Callable, Iterable, Mapping, Sequence

TOOL_VERSION = "0.1.57"
REPORT_DIR = "effect_posteffect_broad_g1e_exact_layout_kps_interface_evidence"
REPORT_NAME = "BR_quartet_restoration_effect_posteffect_broad_g1e_exact_layout_kps_interface_evidence.tar.zst"

STAGE137_NAME = "BR_quartet_restoration_effect_posteffect_bounded_exact_parser_queue_evidence.tar.zst"
STAGE137_SHA256 = "7fe36919b680bdb516d64b327fc717bbe545c611e80a90ecb695c65981af9a4f"
STAGE137_DIR = "effect_posteffect_bounded_exact_parser_queue_evidence"
STAGE137_SUMMARY_SHA256 = "424d5bf693f371264da73cc0c48c4982063370c8739fd8ab56660351723a1565"

STAGE138_NAME = "BR_quartet_restoration_runtime_validation_canonical_integration_evidence.tar.zst"
STAGE138_SHA256 = "8d818ee5035ece1221efda5d66388b6480cef8cbf128374dec2027c002e04089"
STAGE138_DIR = "runtime_validation_canonical_integration_evidence"
STAGE138_SUMMARY_SHA256 = "233ae264468623c84d094ce794e7ce095730d72c61af7041439a97ad608d2cdb"

STAGE136_NAME = "BR_quartet_restoration_effect_posteffect_g1e_kps_structural_sweep_evidence.tar.zst"
STAGE136_DIR = "effect_posteffect_g1e_kps_structural_sweep_evidence"
STAGE134_DIR = "effect_posteffect_namespace_member_saturation_evidence"

EXPECTED_BROAD_FAMILIES = 7
EXPECTED_BROAD_G1E_MEMBERS = 288
EXPECTED_KPS_PATHS = 6
EXPECTED_KPS_PROGRAM_ROWS = 43
EXPECTED_CONTAINER_PATHS = 7
MAX_EARC_BYTES = 1024 * 1024 * 1024
FORBIDDEN_EXTENSIONS = (
    ".pak", ".g1e", ".g1em", ".g1m", ".g1s", ".g1t", ".g1pf",
    ".elixir", ".elixir.gz", ".ebd", ".ebm", ".kps", ".dxbc",
)


class CollectorError(RuntimeError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise CollectorError(message)


def progress(message: str) -> None:
    print(f"[broad-g1e-kps-exact-layout] {message}", file=sys.stderr, flush=True)


def version_tuple(value: str) -> tuple[int, ...]:
    try:
        return tuple(int(part) for part in value.strip().split("."))
    except ValueError as exc:
        raise CollectorError(f"invalid version: {value}") from exc


def parse_bool(value: object) -> bool:
    return str(value).strip().casefold() in {"1", "true", "yes", "y"}


def parse_int(value: object, default: int = 0) -> int:
    try:
        return int(str(value).strip(), 0)
    except (TypeError, ValueError):
        return default


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def stable_json_sha256(value: object) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def safe_relative(value: str, label: str) -> str:
    path = PurePosixPath(str(value).replace("\\", "/"))
    require(bool(path.parts), f"empty {label}")
    require(not path.is_absolute() and ".." not in path.parts, f"unsafe {label}: {value}")
    return path.as_posix()


def read_tsv(path: Path) -> list[dict[str, str]]:
    require(path.is_file(), f"missing TSV: {path}")
    with path.open(encoding="utf-8", newline="") as handle:
        return [dict(row) for row in csv.DictReader(handle, delimiter="\t")]


def write_tsv(path: Path, fields: Sequence[str], rows: Iterable[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle, fieldnames=list(fields), delimiter="\t", lineterminator="\n", extrasaction="ignore"
        )
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fields})


def atomic_json(path: Path, value: Mapping[str, Any]) -> None:
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def make_archive(source: Path, output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(output.name + ".tmp")
    temporary.unlink(missing_ok=True)
    completed = subprocess.run(
        ["tar", "--zstd", "-cf", str(temporary), "-C", str(source.parent), source.name],
        text=True, capture_output=True,
    )
    require(completed.returncode == 0, completed.stderr.strip() or "archive creation failed")
    os.replace(temporary, output)


def extract_report(archive: Path, destination: Path, expected_root: str) -> Path:
    listed = subprocess.run(["tar", "--zstd", "-tf", str(archive)], text=True, capture_output=True)
    require(listed.returncode == 0, listed.stderr.strip() or f"cannot list {archive}")
    names = [safe_relative(line, "report member") for line in listed.stdout.splitlines() if line.strip()]
    require(names, f"empty report archive: {archive}")
    require({PurePosixPath(name).parts[0] for name in names} == {expected_root}, f"unexpected report root: {archive}")
    destination.mkdir(parents=True, exist_ok=True)
    completed = subprocess.run(["tar", "--zstd", "-xf", str(archive), "-C", str(destination)], text=True, capture_output=True)
    require(completed.returncode == 0, completed.stderr.strip() or f"cannot extract {archive}")
    root = destination / expected_root
    require(root.is_dir(), f"missing extracted report root: {root}")
    return root


def locate_report(
    report_root: Path,
    temporary: Path,
    archive_name: str,
    archive_hash: str | None,
    root_name: str,
    summary_hash: str | None,
) -> tuple[Path, dict[str, Any], list[dict[str, Any]]]:
    archive = report_root / archive_name
    require(archive.is_file(), f"missing prerequisite report: {archive}")
    actual_archive_hash = sha256_file(archive)
    if archive_hash:
        require(actual_archive_hash == archive_hash, f"unexpected {archive_name} SHA-256: {actual_archive_hash}")
    root = report_root / root_name
    if not root.is_dir():
        root = extract_report(archive, temporary / root_name, root_name)
    summary_path = root / "SUMMARY.json"
    require(summary_path.is_file(), f"missing prerequisite summary: {summary_path}")
    actual_summary_hash = sha256_file(summary_path)
    if summary_hash:
        require(actual_summary_hash == summary_hash, f"unexpected {root_name} summary SHA-256: {actual_summary_hash}")
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    return root, summary, [
        {"input_id": root_name, "relative_path": archive_name, "sha256": actual_archive_hash, "verified": True},
        {"input_id": f"{root_name}_summary", "relative_path": f"{root_name}/SUMMARY.json", "sha256": actual_summary_hash, "verified": True},
    ]


def load_module(path: Path, name: str):
    require(path.is_file(), f"missing module: {path}")
    spec = importlib.util.spec_from_file_location(name, path)
    require(spec is not None and spec.loader is not None, f"cannot load module: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def interval_overlap(start: int, end: int, section_start: int, section_end: int) -> int:
    return max(0, min(end, section_end) - max(start, section_start))


def scan_exact_section_headers(payload: bytes, parser: Callable[[bytes, int], Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Scan only the exact, already calibrated 14-dword section header layout."""
    rows: list[dict[str, Any]] = []
    version_bytes = (0x00010000).to_bytes(4, "little")
    cursor = 0
    while True:
        hit = payload.find(version_bytes, cursor)
        if hit < 0:
            break
        cursor = hit + 1
        endpoint = hit - 40  # version is header dword 10
        if endpoint < 0 or endpoint % 4:
            continue
        parsed = dict(parser(payload, endpoint))
        if not parse_bool(parsed.get("exact_layout")):
            continue
        declared_end = parse_int(parsed.get("declared_end"), -1)
        declared_span = parse_int(parsed.get("declared_span"), -1)
        count = parse_int(parsed.get("count"), -1)
        boundary1 = parse_int(parsed.get("table_boundary_1"), -1)
        boundary2 = parse_int(parsed.get("table_boundary_2"), -1)
        boundary3 = parse_int(parsed.get("table_boundary_3"), -1)
        if declared_end > len(payload) or min(declared_span, count, boundary1, boundary2, boundary3) < 0:
            continue
        table1 = payload[endpoint + 56:endpoint + boundary1]
        table2 = payload[endpoint + boundary1:endpoint + boundary2]
        table3 = payload[endpoint + boundary2:endpoint + boundary3]
        body = payload[endpoint + boundary3:declared_end]
        rows.append({
            **parsed,
            "section_ordinal": len(rows),
            "table_entry_rows": max(count - 1, 0),
            "table1_sha256": hashlib.sha256(table1).hexdigest(),
            "table2_sha256": hashlib.sha256(table2).hexdigest(),
            "table3_sha256": hashlib.sha256(table3).hexdigest(),
            "body_size": len(body),
            "body_sha256": hashlib.sha256(body).hexdigest(),
            "layout_semantic_sha256": stable_json_sha256({
                "count": count,
                "declared_span": declared_span,
                "table1": hashlib.sha256(table1).hexdigest(),
                "table2": hashlib.sha256(table2).hexdigest(),
                "table3": hashlib.sha256(table3).hexdigest(),
            }),
        })
    return rows


def pair_section_headers(source: Sequence[Mapping[str, Any]], target: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    maximum = max(len(source), len(target))
    for ordinal in range(maximum):
        left = source[ordinal] if ordinal < len(source) else None
        right = target[ordinal] if ordinal < len(target) else None
        if left is None:
            disposition = "target_only_exact_section"
        elif right is None:
            disposition = "source_only_exact_section"
        elif left["layout_semantic_sha256"] == right["layout_semantic_sha256"] and left["body_sha256"] == right["body_sha256"]:
            disposition = "exact_section_identical"
        elif left["count"] == right["count"] and left["declared_span"] == right["declared_span"]:
            disposition = "exact_section_stable_envelope_content_delta"
        elif left["count"] == right["count"]:
            disposition = "exact_section_stable_cardinality_span_delta"
        else:
            disposition = "exact_section_cardinality_delta"
        rows.append({
            "section_ordinal": ordinal,
            "source_endpoint": left.get("endpoint", "") if left else "",
            "target_endpoint": right.get("endpoint", "") if right else "",
            "source_declared_span": left.get("declared_span", "") if left else "",
            "target_declared_span": right.get("declared_span", "") if right else "",
            "source_count": left.get("count", "") if left else "",
            "target_count": right.get("count", "") if right else "",
            "source_layout_semantic_sha256": left.get("layout_semantic_sha256", "") if left else "",
            "target_layout_semantic_sha256": right.get("layout_semantic_sha256", "") if right else "",
            "source_body_sha256": left.get("body_sha256", "") if left else "",
            "target_body_sha256": right.get("body_sha256", "") if right else "",
            "section_pair_disposition": disposition,
        })
    return rows


def exact_section_binding(start: int, end: int, headers: Sequence[Mapping[str, Any]]) -> tuple[str, str, int]:
    if start == end:
        return "empty_side", "", 0
    overlaps: list[tuple[int, int]] = []
    for row in headers:
        overlap = interval_overlap(start, end, int(row["endpoint"]), int(row["declared_end"]))
        if overlap:
            overlaps.append((int(row["section_ordinal"]), overlap))
    if not overlaps:
        return "outside_exact_section_envelope", "", 0
    total = sum(value for _ordinal, value in overlaps)
    ordinals = ",".join(str(ordinal) for ordinal, _value in overlaps)
    if len(overlaps) == 1 and total == end - start:
        return "fully_inside_one_exact_section", ordinals, total
    if total == end - start:
        return "fully_inside_multiple_exact_sections", ordinals, total
    return "partially_overlaps_exact_section", ordinals, total


def instruction_summary(br: Any, payload: bytes, program: Mapping[str, Any]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    chunks = {row["comparison_key"]: row for row in br.parse_dxbc_chunk_payloads(payload, dict(program))}
    code_keys = [key for key in sorted(chunks) if key.startswith("SHDR#") or key.startswith("SHEX#")]
    opcode_counter: Counter[int] = Counter()
    status_counter: Counter[str] = Counter()
    instruction_rows = 0
    declared_dwords = 0
    version_tokens: set[str] = set()
    for key in code_keys:
        parsed = br.parse_dxbc_instruction_stream(chunks[key]["payload"])
        status_counter[str(parsed.get("status", ""))] += 1
        declared_dwords += parse_int(parsed.get("declared_dwords"), 0)
        version_tokens.add(str(parsed.get("version_token", "")))
        for row in parsed.get("instructions", []):
            opcode_counter[int(row["opcode_id"])] += 1
            instruction_rows += 1
    rows = [
        {"opcode_id": opcode, "instruction_rows": count}
        for opcode, count in sorted(opcode_counter.items())
    ]
    return rows, {
        "code_chunk_rows": len(code_keys),
        "instruction_rows": instruction_rows,
        "declared_dwords": declared_dwords,
        "instruction_statuses": " || ".join(f"{key}:{value}" for key, value in sorted(status_counter.items())),
        "version_tokens": " || ".join(sorted(version_tokens)),
        "opcode_inventory_sha256": stable_json_sha256(rows),
    }


def build_report(
    project_root: Path,
    *,
    report_root: Path | None = None,
    output_report_root: Path | None = None,
    workspace_root: Path | None = None,
    original_root: Path | None = None,
    quartet_root: Path | None = None,
    gust_pak_path: Path | None = None,
    create_archive: bool = True,
    timeout_seconds: int = 1800,
    verify_payload_hashes: bool = True,
    payload_provider: Callable[[str, str, str], bytes | None] | None = None,
    enforce_production_cardinality: bool = True,
) -> tuple[Path | None, dict[str, Any]]:
    project_root = project_root.resolve()
    version_path = project_root / "workstreams/quartet_restoration/VERSION"
    require(version_path.is_file(), f"missing VERSION: {version_path}")
    version = version_path.read_text(encoding="utf-8").strip()
    require(version_tuple(version) >= version_tuple(TOOL_VERSION), f"expected quartet_restoration {TOOL_VERSION} or newer, found {version}")

    report_root = (report_root or project_root / ".local/reports/quartet_restoration").resolve()
    output_report_root = (output_report_root or report_root).resolve()
    workspace_root = (workspace_root or project_root / ".local/build/quartet_restoration").resolve()
    output = output_report_root / REPORT_DIR
    archive = output_report_root / REPORT_NAME
    shutil.rmtree(output, ignore_errors=True)
    output.mkdir(parents=True, exist_ok=True)

    stage134 = load_module(
        project_root / "workstreams/quartet_restoration/134_collect_effect_posteffect_namespace_member_saturation_evidence.py",
        "stage139_stage134",
    )
    stage84 = load_module(
        project_root / "workstreams/quartet_restoration/collect_reflector_slot_light_g1e_structure_evidence.py",
        "stage139_stage84",
    )
    stage90 = load_module(
        project_root / "workstreams/quartet_restoration/collect_reflector_slot_light_target_section_layout_evidence.py",
        "stage139_stage90",
    )
    stage133 = load_module(
        project_root / "workstreams/quartet_restoration/133_collect_shader_namespace_executable_signature_reflection_sweep_evidence.py",
        "stage139_stage133",
    )
    br = stage134.load_br_tool(project_root)

    with tempfile.TemporaryDirectory(prefix="stage139-prereq-") as temporary_text:
        temporary = Path(temporary_text)
        root137, summary137, hashes137 = locate_report(
            report_root, temporary, STAGE137_NAME, STAGE137_SHA256, STAGE137_DIR, STAGE137_SUMMARY_SHA256,
        )
        root138, summary138, hashes138 = locate_report(
            report_root, temporary, STAGE138_NAME, STAGE138_SHA256, STAGE138_DIR, STAGE138_SUMMARY_SHA256,
        )
        root136, summary136, hashes136 = locate_report(
            report_root, temporary, STAGE136_NAME, None, STAGE136_DIR, None,
        )
        root134 = report_root / STAGE134_DIR
        require(root134.is_dir(), f"missing extracted stage-134 report: {root134}")

        require(summary137.get("g1e_recurrent_structure_family_queue_rows") == 83, "stage-137 family queue drift")
        require(summary137.get("kps_exact_parser_path_queue_rows") == EXPECTED_KPS_PATHS, "stage-137 KPS path drift")
        require(summary137.get("kps_exact_parser_program_queue_rows") == EXPECTED_KPS_PROGRAM_ROWS, "stage-137 KPS program drift")
        require(summary138.get("runtime_validated_profile_rows") == 1, "stage-138 runtime profile count drift")
        require(summary138.get("runtime_validated_profile_ids") == ["candidate_bathroom_river_containing_pak_static_inverse_062e39915e7d"], "stage-138 production profile drift")
        require(summary136.get("g1e_member_rows") == 621 and summary136.get("kps_member_rows") == 27, "stage-136 member count drift")

        family_queue = read_tsv(root137 / "G1E_RECURRENT_STRUCTURE_FAMILY_PARSER_QUEUE.tsv")
        broad_families = [row for row in family_queue if row["recurrence_tier"] == "broad_ge_10_members"]
        require(len(broad_families) == EXPECTED_BROAD_FAMILIES, f"expected {EXPECTED_BROAD_FAMILIES} broad families")
        broad_ids = {row["structure_family_id"] for row in broad_families}
        structural_rows = read_tsv(root136 / "G1E_STRUCTURAL_PAIR_AUDIT.tsv")
        selected_g1e = [row for row in structural_rows if row["structure_family_id"] in broad_ids]
        require(len(selected_g1e) == EXPECTED_BROAD_G1E_MEMBERS, f"expected {EXPECTED_BROAD_G1E_MEMBERS} broad G1E members, found {len(selected_g1e)}")
        kps_queue = read_tsv(root137 / "KPS_EXACT_PARSER_PATH_QUEUE.tsv")
        require(len(kps_queue) == EXPECTED_KPS_PATHS, "KPS queue cardinality drift")

        container_candidates = [
            {"namespace": row["namespace"], "normalized_path": row["normalized_path"]}
            for row in read_tsv(root134 / "EFFECT_POSTEFFECT_PATH_SUMMARY.tsv")
        ]
        require(len(container_candidates) == EXPECTED_CONTAINER_PATHS, "container path count drift")

        payload_maps: dict[tuple[str, str], dict[str, dict[str, Any]]] = {}
        container_input_rows: list[dict[str, Any]] = []
        extraction_rows: list[dict[str, Any]] = []
        payload_bytes_read = 0
        if payload_provider is None:
            inventories = {side: stage134.load_inventory(project_root, side) for side in ("source", "target")}
            extraction_rows = stage134.ensure_extraction_cache(
                project_root=project_root,
                workspace_root=workspace_root,
                candidates=container_candidates,
                inventories=inventories,
                original_root=original_root,
                quartet_root=quartet_root,
                gust_pak_path=gust_pak_path,
                br=br,
                timeout_seconds=timeout_seconds,
            )
            for index, candidate in enumerate(sorted(container_candidates, key=lambda row: row["normalized_path"]), start=1):
                normalized = candidate["normalized_path"].casefold()
                progress(f"reading container {index}/{EXPECTED_CONTAINER_PATHS}: {normalized}")
                for side in ("source", "target"):
                    entry = inventories[side].get(normalized)
                    require(entry is not None, f"missing inventory entry: {side}:{normalized}")
                    local = br.inventory_workspace_file(workspace_root, side, "br1_assets", str(entry["archive"]), str(entry["path"]))
                    require(local.is_file(), f"missing cached input: {local}")
                    actual_hash = sha256_file(local)
                    if verify_payload_hashes:
                        require(actual_hash == str(entry["sha256"]), f"payload hash drift: {side}:{normalized}: {actual_hash}")
                        require(local.stat().st_size == int(entry["size"]), f"payload size drift: {side}:{normalized}")
                    parsed = br.read_earc_archive(local, maximum_bytes=MAX_EARC_BYTES, include_member_payloads=True)
                    payload_bytes_read += int(parsed["decoded_bytes"])
                    payload_maps[(side, normalized)] = {str(row["comparison_key"]): row for row in parsed["members"]}
                    container_input_rows.append({
                        "side": side,
                        "namespace": candidate["namespace"],
                        "normalized_path": normalized,
                        "container_archive": entry["archive"],
                        "input_size": local.stat().st_size,
                        "input_sha256": actual_hash,
                        "decoded_bytes": parsed["decoded_bytes"],
                        "decoded_sha256": parsed["decoded_sha256"],
                        "member_count": parsed["file_count"],
                        "payload_in_evidence": False,
                        "write_authorized": False,
                    })

        def get_payload(side: str, normalized: str, member_key: str) -> bytes | None:
            if payload_provider is not None:
                return payload_provider(side, normalized, member_key)
            row = payload_maps.get((side, normalized), {}).get(member_key)
            return bytes(row["payload"]) if row is not None else None

        g1e_member_rows: list[dict[str, Any]] = []
        g1e_header_rows: list[dict[str, Any]] = []
        g1e_pair_rows: list[dict[str, Any]] = []
        g1e_segment_rows: list[dict[str, Any]] = []
        family_accumulator: dict[str, dict[str, Any]] = defaultdict(lambda: {
            "member_rows": 0, "members_with_source_headers": 0, "members_with_target_headers": 0,
            "members_with_paired_headers": 0, "members_all_changed_segments_exactly_bound": 0,
            "source_exact_section_rows": 0, "target_exact_section_rows": 0,
            "paired_exact_section_rows": 0, "unpaired_exact_section_rows": 0,
            "changed_segment_rows": 0, "fully_bound_changed_segment_rows": 0,
            "pair_dispositions": Counter(), "member_examples": [],
        })
        for index, row in enumerate(sorted(selected_g1e, key=lambda item: (item["normalized_path"], item["member_key"])), start=1):
            if index == 1 or index % 40 == 0 or index == EXPECTED_BROAD_G1E_MEMBERS:
                progress(f"exact-layout G1E {index}/{EXPECTED_BROAD_G1E_MEMBERS}")
            normalized = row["normalized_path"].casefold()
            key = row["member_key"]
            member_name = row["member_name"]
            source = get_payload("source", normalized, key)
            target = get_payload("target", normalized, key)
            require(source is not None and target is not None, f"missing broad G1E payload pair: {normalized}:{key}")
            if verify_payload_hashes and payload_provider is None:
                require(hashlib.sha256(source).hexdigest() == row["source_sha256"], f"source G1E hash drift: {normalized}:{key}")
                require(hashlib.sha256(target).hexdigest() == row["target_sha256"], f"target G1E hash drift: {normalized}:{key}")
            source_headers = scan_exact_section_headers(source, stage90.parse_section_header)
            target_headers = scan_exact_section_headers(target, stage90.parse_section_header)
            pairs = pair_section_headers(source_headers, target_headers)
            segments, _runs = stage84.build_alignment_segments(source, target)
            family_id = row["structure_family_id"]
            acc = family_accumulator[family_id]
            acc["member_rows"] += 1
            acc["source_exact_section_rows"] += len(source_headers)
            acc["target_exact_section_rows"] += len(target_headers)
            acc["members_with_source_headers"] += bool(source_headers)
            acc["members_with_target_headers"] += bool(target_headers)
            acc["members_with_paired_headers"] += bool(pairs and any(pair["source_endpoint"] != "" and pair["target_endpoint"] != "" for pair in pairs))
            acc["paired_exact_section_rows"] += sum(pair["source_endpoint"] != "" and pair["target_endpoint"] != "" for pair in pairs)
            acc["unpaired_exact_section_rows"] += sum(pair["source_endpoint"] == "" or pair["target_endpoint"] == "" for pair in pairs)
            acc["pair_dispositions"].update(pair["section_pair_disposition"] for pair in pairs)
            if len(acc["member_examples"]) < 12:
                acc["member_examples"].append(member_name)

            for side, headers in (("source", source_headers), ("target", target_headers)):
                for header in headers:
                    g1e_header_rows.append({
                        "structure_family_id": family_id,
                        "normalized_path": normalized,
                        "member_key": key,
                        "member_name": member_name,
                        "side": side,
                        **header,
                        "payload_in_evidence": False,
                        "field_semantics_confirmed": False,
                        "visual_or_censorship_semantics_confirmed": False,
                        "runtime_confirmed": False,
                        "write_authorized": False,
                    })
            for pair in pairs:
                g1e_pair_rows.append({
                    "structure_family_id": family_id,
                    "normalized_path": normalized,
                    "member_key": key,
                    "member_name": member_name,
                    **pair,
                    "field_semantics_confirmed": False,
                    "visual_or_censorship_semantics_confirmed": False,
                    "runtime_confirmed": False,
                    "write_authorized": False,
                })

            changed_segment_rows = 0
            fully_bound_rows = 0
            for segment_index, segment in enumerate(segments):
                if segment["segment_type"] == "identical":
                    continue
                changed_segment_rows += 1
                source_binding, source_ordinals, source_overlap = exact_section_binding(
                    int(segment["source_start"]), int(segment["source_end_exclusive"]), source_headers
                )
                target_binding, target_ordinals, target_overlap = exact_section_binding(
                    int(segment["target_start"]), int(segment["target_end_exclusive"]), target_headers
                )
                source_full = source_binding.startswith("fully_inside") or source_binding == "empty_side"
                target_full = target_binding.startswith("fully_inside") or target_binding == "empty_side"
                fully_bound = source_full and target_full and (source_binding != "outside_exact_section_envelope") and (target_binding != "outside_exact_section_envelope")
                fully_bound_rows += fully_bound
                g1e_segment_rows.append({
                    "structure_family_id": family_id,
                    "normalized_path": normalized,
                    "member_key": key,
                    "member_name": member_name,
                    "segment_index": segment_index,
                    **segment,
                    "source_section_binding": source_binding,
                    "source_section_ordinals": source_ordinals,
                    "source_section_overlap_bytes": source_overlap,
                    "target_section_binding": target_binding,
                    "target_section_ordinals": target_ordinals,
                    "target_section_overlap_bytes": target_overlap,
                    "fully_bound_by_exact_sections": fully_bound,
                    "field_semantics_confirmed": False,
                    "visual_or_censorship_semantics_confirmed": False,
                    "runtime_confirmed": False,
                    "write_authorized": False,
                })
            acc["changed_segment_rows"] += changed_segment_rows
            acc["fully_bound_changed_segment_rows"] += fully_bound_rows
            all_bound = changed_segment_rows > 0 and changed_segment_rows == fully_bound_rows
            acc["members_all_changed_segments_exactly_bound"] += all_bound
            member_dispositions = Counter(pair["section_pair_disposition"] for pair in pairs)
            if not source_headers and not target_headers:
                parser_disposition = "no_exact_section_header_layout_detected"
            elif all_bound and not member_dispositions.get("source_only_exact_section") and not member_dispositions.get("target_only_exact_section"):
                parser_disposition = "all_changed_segments_bound_to_paired_exact_sections"
            elif pairs:
                parser_disposition = "partial_exact_section_layout_coverage"
            else:
                parser_disposition = "unpaired_exact_section_layout_only"
            g1e_member_rows.append({
                "structure_family_id": family_id,
                "normalized_path": normalized,
                "member_key": key,
                "member_name": member_name,
                "source_size": len(source),
                "target_size": len(target),
                "source_exact_section_rows": len(source_headers),
                "target_exact_section_rows": len(target_headers),
                "paired_exact_section_rows": sum(pair["source_endpoint"] != "" and pair["target_endpoint"] != "" for pair in pairs),
                "unpaired_exact_section_rows": sum(pair["source_endpoint"] == "" or pair["target_endpoint"] == "" for pair in pairs),
                "changed_segment_rows": changed_segment_rows,
                "fully_bound_changed_segment_rows": fully_bound_rows,
                "all_changed_segments_exactly_bound": all_bound,
                "exact_layout_parser_disposition": parser_disposition,
                "field_semantics_confirmed": False,
                "visual_or_censorship_semantics_confirmed": False,
                "runtime_confirmed": False,
                "write_authorized": False,
            })

        family_rows: list[dict[str, Any]] = []
        broad_by_id = {row["structure_family_id"]: row for row in broad_families}
        for family_id in sorted(broad_ids, key=lambda item: (-int(broad_by_id[item]["member_rows"]), item)):
            acc = family_accumulator[family_id]
            require(acc["member_rows"] == int(broad_by_id[family_id]["member_rows"]), f"family member count drift: {family_id}")
            family_rows.append({
                "structure_family_id": family_id,
                "recurrence_tier": broad_by_id[family_id]["recurrence_tier"],
                "member_rows": acc["member_rows"],
                "members_with_source_exact_sections": acc["members_with_source_headers"],
                "members_with_target_exact_sections": acc["members_with_target_headers"],
                "members_with_paired_exact_sections": acc["members_with_paired_headers"],
                "members_all_changed_segments_exactly_bound": acc["members_all_changed_segments_exactly_bound"],
                "source_exact_section_rows": acc["source_exact_section_rows"],
                "target_exact_section_rows": acc["target_exact_section_rows"],
                "paired_exact_section_rows": acc["paired_exact_section_rows"],
                "unpaired_exact_section_rows": acc["unpaired_exact_section_rows"],
                "changed_segment_rows": acc["changed_segment_rows"],
                "fully_bound_changed_segment_rows": acc["fully_bound_changed_segment_rows"],
                "section_pair_dispositions": " || ".join(f"{key}:{value}" for key, value in sorted(acc["pair_dispositions"].items())),
                "member_examples": " || ".join(acc["member_examples"]),
                "layout_semantics_confirmed": False,
                "visual_or_censorship_semantics_confirmed": False,
                "runtime_confirmed": False,
                "write_authorized": False,
            })

        kps_path_rows: list[dict[str, Any]] = []
        kps_program_rows: list[dict[str, Any]] = []
        resource_rows: list[dict[str, Any]] = []
        cbuffer_rows: list[dict[str, Any]] = []
        variable_rows: list[dict[str, Any]] = []
        signature_rows: list[dict[str, Any]] = []
        opcode_rows: list[dict[str, Any]] = []
        for path_index, row in enumerate(sorted(kps_queue, key=lambda item: (item["normalized_path"], item["member_key"])), start=1):
            normalized = row["normalized_path"].casefold()
            key = row["member_key"]
            member_name = row["member_name"]
            progress(f"exact-interface KPS {path_index}/{EXPECTED_KPS_PATHS}: {member_name}")
            source = get_payload("source", normalized, key)
            target = get_payload("target", normalized, key)
            require(target is not None, f"missing target KPS payload: {normalized}:{key}")
            source_programs = br.find_dxbc_programs(source or b"", label=f"source:{normalized}:{key}")
            target_programs = br.find_dxbc_programs(target, label=f"target:{normalized}:{key}")
            pairs = stage133.pair_programs(source_programs, target_programs)
            path_program_rows: list[dict[str, Any]] = []
            for pair_index, pair in enumerate(pairs):
                source_program = pair.get("source")
                target_program = pair.get("target")
                analysis, _chunks = stage133.program_analysis(br, source, target, source_program, target_program, str(pair["matching_basis"]))
                sides: dict[str, dict[str, Any]] = {}
                for side, payload, program in (("source", source, source_program), ("target", target, target_program)):
                    if payload is None or program is None:
                        sides[side] = {
                            "rdef_status": "missing", "reflection_semantic_sha256": "",
                            "resource_semantic_sha256": "", "cbuffer_semantic_sha256": "",
                            "input_signature_sha256": "", "output_signature_sha256": "",
                            "instruction_rows": 0, "opcode_inventory_sha256": "", "code_chunk_rows": 0,
                            "instruction_statuses": "", "version_tokens": "", "declared_dwords": 0,
                        }
                        continue
                    chunks = {chunk["comparison_key"]: chunk for chunk in br.parse_dxbc_chunk_payloads(payload, dict(program))}
                    rdef = br.parse_dxbc_rdef(chunks["RDEF#0"]["payload"]) if "RDEF#0" in chunks else {
                        "status": "missing", "resources": [], "cbuffers": [], "variables": [],
                        "reflection_semantic_sha256": "", "resource_semantic_sha256": "", "cbuffer_semantic_sha256": "",
                    }
                    input_signature = {"status": "missing", "elements": [], "semantic_sha256": ""}
                    output_signature = {"status": "missing", "elements": [], "semantic_sha256": ""}
                    for comparison_key, chunk in chunks.items():
                        if comparison_key.startswith("ISGN#") or comparison_key.startswith("ISG1#"):
                            input_signature = br.parse_dxbc_signature(chunk["payload"], chunk["fourcc"])
                        elif comparison_key.startswith("OSGN#") or comparison_key.startswith("OSG5#") or comparison_key.startswith("OSG1#"):
                            output_signature = br.parse_dxbc_signature(chunk["payload"], chunk["fourcc"])
                    opcodes, instruction = instruction_summary(br, payload, program)
                    sides[side] = {
                        "rdef_status": rdef.get("status", ""),
                        "reflection_semantic_sha256": rdef.get("reflection_semantic_sha256", ""),
                        "resource_semantic_sha256": rdef.get("resource_semantic_sha256", ""),
                        "cbuffer_semantic_sha256": rdef.get("cbuffer_semantic_sha256", ""),
                        "input_signature_sha256": input_signature.get("semantic_sha256", ""),
                        "output_signature_sha256": output_signature.get("semantic_sha256", ""),
                        **instruction,
                    }
                    for resource in rdef.get("resources", []):
                        resource_rows.append({
                            "normalized_path": normalized, "member_key": key, "member_name": member_name,
                            "program_pair_index": pair_index, "side": side, **resource,
                            "field_semantics_confirmed": False, "visual_or_censorship_semantics_confirmed": False,
                            "runtime_confirmed": False, "write_authorized": False,
                        })
                    for cbuffer in rdef.get("cbuffers", []):
                        cbuffer_rows.append({
                            "normalized_path": normalized, "member_key": key, "member_name": member_name,
                            "program_pair_index": pair_index, "side": side, **cbuffer,
                            "field_semantics_confirmed": False, "visual_or_censorship_semantics_confirmed": False,
                            "runtime_confirmed": False, "write_authorized": False,
                        })
                    for variable in rdef.get("variables", []):
                        variable_rows.append({
                            "normalized_path": normalized, "member_key": key, "member_name": member_name,
                            "program_pair_index": pair_index, "side": side, **variable,
                            "field_semantics_confirmed": False, "visual_or_censorship_semantics_confirmed": False,
                            "runtime_confirmed": False, "write_authorized": False,
                        })
                    for signature_kind, signature in (("input", input_signature), ("output", output_signature)):
                        for element in signature.get("elements", []):
                            signature_rows.append({
                                "normalized_path": normalized, "member_key": key, "member_name": member_name,
                                "program_pair_index": pair_index, "side": side, "signature_kind": signature_kind, **element,
                                "field_semantics_confirmed": False, "visual_or_censorship_semantics_confirmed": False,
                                "runtime_confirmed": False, "write_authorized": False,
                            })
                    for opcode in opcodes:
                        opcode_rows.append({
                            "normalized_path": normalized, "member_key": key, "member_name": member_name,
                            "program_pair_index": pair_index, "side": side, **opcode,
                            "field_semantics_confirmed": False, "visual_or_censorship_semantics_confirmed": False,
                            "runtime_confirmed": False, "write_authorized": False,
                        })
                if analysis["classification"] == "nonexecutive_metadata_or_compiler_delta":
                    continue
                program_row = {
                    "normalized_path": normalized,
                    "member_key": key,
                    "member_name": member_name,
                    "program_pair_index": pair_index,
                    "matching_basis": pair["matching_basis"],
                    "classification": analysis["classification"],
                    "source_program_index": (source_program or {}).get("program_index", ""),
                    "target_program_index": (target_program or {}).get("program_index", ""),
                    "source_stage": (source_program or {}).get("stage", ""),
                    "target_stage": (target_program or {}).get("stage", ""),
                    "source_shader_model": (source_program or {}).get("shader_model", ""),
                    "target_shader_model": (target_program or {}).get("shader_model", ""),
                    "source_rdef_status": sides["source"]["rdef_status"],
                    "target_rdef_status": sides["target"]["rdef_status"],
                    "source_reflection_semantic_sha256": sides["source"]["reflection_semantic_sha256"],
                    "target_reflection_semantic_sha256": sides["target"]["reflection_semantic_sha256"],
                    "source_resource_semantic_sha256": sides["source"]["resource_semantic_sha256"],
                    "target_resource_semantic_sha256": sides["target"]["resource_semantic_sha256"],
                    "source_cbuffer_semantic_sha256": sides["source"]["cbuffer_semantic_sha256"],
                    "target_cbuffer_semantic_sha256": sides["target"]["cbuffer_semantic_sha256"],
                    "source_input_signature_sha256": sides["source"]["input_signature_sha256"],
                    "target_input_signature_sha256": sides["target"]["input_signature_sha256"],
                    "source_output_signature_sha256": sides["source"]["output_signature_sha256"],
                    "target_output_signature_sha256": sides["target"]["output_signature_sha256"],
                    "source_instruction_rows": sides["source"]["instruction_rows"],
                    "target_instruction_rows": sides["target"]["instruction_rows"],
                    "source_opcode_inventory_sha256": sides["source"]["opcode_inventory_sha256"],
                    "target_opcode_inventory_sha256": sides["target"]["opcode_inventory_sha256"],
                    "source_version_tokens": sides["source"]["version_tokens"],
                    "target_version_tokens": sides["target"]["version_tokens"],
                    "exact_interface_equal": bool(
                        sides["source"]["reflection_semantic_sha256"]
                        and sides["source"]["reflection_semantic_sha256"] == sides["target"]["reflection_semantic_sha256"]
                        and sides["source"]["input_signature_sha256"] == sides["target"]["input_signature_sha256"]
                        and sides["source"]["output_signature_sha256"] == sides["target"]["output_signature_sha256"]
                    ),
                    "exact_opcode_inventory_equal": bool(
                        sides["source"]["opcode_inventory_sha256"]
                        and sides["source"]["opcode_inventory_sha256"] == sides["target"]["opcode_inventory_sha256"]
                    ),
                    "field_semantics_confirmed": False,
                    "visual_or_censorship_semantics_confirmed": False,
                    "runtime_confirmed": False,
                    "write_authorized": False,
                }
                path_program_rows.append(program_row)
                kps_program_rows.append(program_row)
            path_classes = Counter(str(item["classification"]) for item in path_program_rows)
            kps_path_rows.append({
                "normalized_path": normalized,
                "member_key": key,
                "member_name": member_name,
                "stage137_disposition": row["kps_path_disposition"],
                "source_program_rows": len(source_programs),
                "target_program_rows": len(target_programs),
                "paired_program_rows": len(pairs),
                "queued_nonmetadata_program_rows": len(path_program_rows),
                "metadata_only_control_program_rows": sum(
                    1 for pair in pairs
                    if stage133.program_analysis(
                        br, source, target, pair.get("source"), pair.get("target"), str(pair["matching_basis"])
                    )[0]["classification"] == "nonexecutive_metadata_or_compiler_delta"
                ),
                "program_classifications": " || ".join(f"{key_}:{value}" for key_, value in sorted(path_classes.items())),
                "exact_interface_equal_program_rows": sum(parse_bool(item["exact_interface_equal"]) for item in path_program_rows),
                "exact_opcode_inventory_equal_program_rows": sum(parse_bool(item["exact_opcode_inventory_equal"]) for item in path_program_rows),
                "field_semantics_confirmed": False,
                "visual_or_censorship_semantics_confirmed": False,
                "runtime_confirmed": False,
                "write_authorized": False,
            })
        if enforce_production_cardinality:
            require(len(kps_program_rows) == EXPECTED_KPS_PROGRAM_ROWS, f"expected {EXPECTED_KPS_PROGRAM_ROWS} KPS program rows, found {len(kps_program_rows)}")

        carry_rows = read_tsv(root137 / "UNRESOLVED_G1EM_G1T_SHADER_CARRY_FORWARD.tsv")
        require(len(carry_rows) == 25, "stage-137 unresolved carry-forward count drift")
        for row in carry_rows:
            if row["identity"] in {"data/x64/shader/heightfog.g1s", "data/x64/shader/swater.g1s"}:
                row["runtime_confirmed"] = "False"
                row["disposition"] = "runtime_failed_profile_remains_nonproduction_unresolved_for_minimal_target_bytecode_repair"

        write_tsv(output / "INPUT_HASHES.tsv", ["input_id", "relative_path", "sha256", "verified"], hashes137 + hashes138 + hashes136)
        write_tsv(output / "CONTAINER_INPUTS.tsv", [
            "side", "namespace", "normalized_path", "container_archive", "input_size", "input_sha256",
            "decoded_bytes", "decoded_sha256", "member_count", "payload_in_evidence", "write_authorized",
        ], container_input_rows)
        write_tsv(output / "EXTRACTION_INPUTS.tsv", sorted({key for row in extraction_rows for key in row}) if extraction_rows else ["status"], extraction_rows)
        write_tsv(output / "G1E_BROAD_FAMILY_MEMBER_LAYOUT.tsv", [
            "structure_family_id", "normalized_path", "member_key", "member_name", "source_size", "target_size",
            "source_exact_section_rows", "target_exact_section_rows", "paired_exact_section_rows", "unpaired_exact_section_rows",
            "changed_segment_rows", "fully_bound_changed_segment_rows", "all_changed_segments_exactly_bound",
            "exact_layout_parser_disposition", "field_semantics_confirmed", "visual_or_censorship_semantics_confirmed",
            "runtime_confirmed", "write_authorized",
        ], g1e_member_rows)
        write_tsv(output / "G1E_EXACT_SECTION_HEADERS.tsv", [
            "structure_family_id", "normalized_path", "member_key", "member_name", "side", "section_ordinal", "endpoint",
            "declared_span", "declared_end", "count", "table_entry_rows", "table_boundary_1", "table_boundary_2",
            "table_boundary_3", "table1_sha256", "table2_sha256", "table3_sha256", "body_size", "body_sha256",
            "layout_semantic_sha256", "payload_in_evidence", "field_semantics_confirmed",
            "visual_or_censorship_semantics_confirmed", "runtime_confirmed", "write_authorized",
        ], g1e_header_rows)
        write_tsv(output / "G1E_EXACT_SECTION_PAIRS.tsv", [
            "structure_family_id", "normalized_path", "member_key", "member_name", "section_ordinal",
            "source_endpoint", "target_endpoint", "source_declared_span", "target_declared_span", "source_count", "target_count",
            "source_layout_semantic_sha256", "target_layout_semantic_sha256", "source_body_sha256", "target_body_sha256",
            "section_pair_disposition", "field_semantics_confirmed", "visual_or_censorship_semantics_confirmed",
            "runtime_confirmed", "write_authorized",
        ], g1e_pair_rows)
        write_tsv(output / "G1E_CHANGE_SEGMENT_SECTION_BINDING.tsv", [
            "structure_family_id", "normalized_path", "member_key", "member_name", "segment_index", "segment_type",
            "source_start", "source_end_exclusive", "target_start", "target_end_exclusive", "source_length", "target_length",
            "size_delta", "shift_before", "shift_after", "source_section_binding", "source_section_ordinals",
            "source_section_overlap_bytes", "target_section_binding", "target_section_ordinals", "target_section_overlap_bytes",
            "fully_bound_by_exact_sections", "field_semantics_confirmed", "visual_or_censorship_semantics_confirmed",
            "runtime_confirmed", "write_authorized",
        ], g1e_segment_rows)
        write_tsv(output / "G1E_BROAD_FAMILY_LAYOUT_SUMMARY.tsv", [
            "structure_family_id", "recurrence_tier", "member_rows", "members_with_source_exact_sections",
            "members_with_target_exact_sections", "members_with_paired_exact_sections", "members_all_changed_segments_exactly_bound",
            "source_exact_section_rows", "target_exact_section_rows", "paired_exact_section_rows", "unpaired_exact_section_rows",
            "changed_segment_rows", "fully_bound_changed_segment_rows", "section_pair_dispositions", "member_examples",
            "layout_semantics_confirmed", "visual_or_censorship_semantics_confirmed", "runtime_confirmed", "write_authorized",
        ], family_rows)
        write_tsv(output / "KPS_EXACT_PATH_LAYOUT.tsv", [
            "normalized_path", "member_key", "member_name", "stage137_disposition", "source_program_rows", "target_program_rows",
            "paired_program_rows", "queued_nonmetadata_program_rows", "metadata_only_control_program_rows", "program_classifications", "exact_interface_equal_program_rows",
            "exact_opcode_inventory_equal_program_rows", "field_semantics_confirmed",
            "visual_or_censorship_semantics_confirmed", "runtime_confirmed", "write_authorized",
        ], kps_path_rows)
        write_tsv(output / "KPS_EXACT_PROGRAM_LAYOUT.tsv", [
            "normalized_path", "member_key", "member_name", "program_pair_index", "matching_basis", "classification",
            "source_program_index", "target_program_index", "source_stage", "target_stage", "source_shader_model", "target_shader_model",
            "source_rdef_status", "target_rdef_status", "source_reflection_semantic_sha256", "target_reflection_semantic_sha256",
            "source_resource_semantic_sha256", "target_resource_semantic_sha256", "source_cbuffer_semantic_sha256",
            "target_cbuffer_semantic_sha256", "source_input_signature_sha256", "target_input_signature_sha256",
            "source_output_signature_sha256", "target_output_signature_sha256", "source_instruction_rows", "target_instruction_rows",
            "source_opcode_inventory_sha256", "target_opcode_inventory_sha256", "source_version_tokens", "target_version_tokens",
            "exact_interface_equal", "exact_opcode_inventory_equal", "field_semantics_confirmed",
            "visual_or_censorship_semantics_confirmed", "runtime_confirmed", "write_authorized",
        ], kps_program_rows)
        write_tsv(output / "KPS_RDEF_RESOURCES.tsv", [
            "normalized_path", "member_key", "member_name", "program_pair_index", "side", "resource_index", "name", "name_status",
            "resource_type", "return_type", "dimension", "sample_count", "bind_point", "bind_count", "flags", "space", "resource_id",
            "field_semantics_confirmed", "visual_or_censorship_semantics_confirmed", "runtime_confirmed", "write_authorized",
        ], resource_rows)
        write_tsv(output / "KPS_RDEF_CBUFFERS.tsv", [
            "normalized_path", "member_key", "member_name", "program_pair_index", "side", "cbuffer_index", "name", "name_status",
            "variable_count", "size", "flags", "buffer_type", "field_semantics_confirmed",
            "visual_or_censorship_semantics_confirmed", "runtime_confirmed", "write_authorized",
        ], cbuffer_rows)
        write_tsv(output / "KPS_RDEF_VARIABLES.tsv", [
            "normalized_path", "member_key", "member_name", "program_pair_index", "side", "cbuffer_index", "cbuffer_name",
            "variable_index", "name", "name_status", "start_offset", "size", "flags", "type_class", "type_code", "rows", "columns",
            "elements", "members", "type_name", "type_name_status", "default_status", "default_sha256",
            "field_semantics_confirmed", "visual_or_censorship_semantics_confirmed", "runtime_confirmed", "write_authorized",
        ], variable_rows)
        write_tsv(output / "KPS_SIGNATURE_ELEMENTS.tsv", [
            "normalized_path", "member_key", "member_name", "program_pair_index", "side", "signature_kind", "element_index", "stream",
            "semantic_name", "name_status", "semantic_index", "system_value", "component_type", "register", "mask", "rw_mask", "precision",
            "field_semantics_confirmed", "visual_or_censorship_semantics_confirmed", "runtime_confirmed", "write_authorized",
        ], signature_rows)
        write_tsv(output / "KPS_INSTRUCTION_OPCODE_SUMMARY.tsv", [
            "normalized_path", "member_key", "member_name", "program_pair_index", "side", "opcode_id", "instruction_rows",
            "field_semantics_confirmed", "visual_or_censorship_semantics_confirmed", "runtime_confirmed", "write_authorized",
        ], opcode_rows)
        write_tsv(output / "UNRESOLVED_G1EM_G1T_SHADER_CARRY_FORWARD.tsv", list(carry_rows[0]), carry_rows)
        write_tsv(output / "EXACT_LAYOUT_PARSER_SKIPPED.tsv", ["scope", "identity", "reason"], [])

        g1e_dispositions = Counter(row["exact_layout_parser_disposition"] for row in g1e_member_rows)
        section_pair_dispositions = Counter(row["section_pair_disposition"] for row in g1e_pair_rows)
        kps_program_classes = Counter(row["classification"] for row in kps_program_rows)
        summary = {
            "type": "br_quartet_restoration_effect_posteffect_broad_g1e_exact_layout_kps_interface_evidence_summary",
            "format_version": 1,
            "tool_version": TOOL_VERSION,
            "status": "broad_g1e_exact_section_layout_and_nonmetadata_kps_interfaces_parsed_metadata_only_semantics_unresolved_no_write",
            "stage137_report_sha256": STAGE137_SHA256,
            "stage138_report_sha256": STAGE138_SHA256,
            "runtime_validated_profile_rows_preserved": 1,
            "runtime_validated_profile_id_preserved": summary138["runtime_validated_profile_ids"][0],
            "broad_g1e_structure_family_rows": len(family_rows),
            "broad_g1e_member_rows": len(g1e_member_rows),
            "g1e_source_exact_section_rows": sum(int(row["source_exact_section_rows"]) for row in g1e_member_rows),
            "g1e_target_exact_section_rows": sum(int(row["target_exact_section_rows"]) for row in g1e_member_rows),
            "g1e_paired_exact_section_rows": sum(int(row["paired_exact_section_rows"]) for row in g1e_member_rows),
            "g1e_unpaired_exact_section_rows": sum(int(row["unpaired_exact_section_rows"]) for row in g1e_member_rows),
            "g1e_members_with_any_exact_section_rows": sum(
                int(row["source_exact_section_rows"]) > 0 or int(row["target_exact_section_rows"]) > 0 for row in g1e_member_rows
            ),
            "g1e_members_all_changed_segments_exactly_bound": sum(parse_bool(row["all_changed_segments_exactly_bound"]) for row in g1e_member_rows),
            "g1e_changed_segment_rows": len(g1e_segment_rows),
            "g1e_fully_bound_changed_segment_rows": sum(parse_bool(row["fully_bound_by_exact_sections"]) for row in g1e_segment_rows),
            "g1e_exact_layout_parser_dispositions": dict(sorted(g1e_dispositions.items())),
            "g1e_section_pair_dispositions": dict(sorted(section_pair_dispositions.items())),
            "kps_exact_path_rows": len(kps_path_rows),
            "kps_exact_program_rows": len(kps_program_rows),
            "kps_program_classifications": dict(sorted(kps_program_classes.items())),
            "kps_rdef_resource_rows": len(resource_rows),
            "kps_rdef_cbuffer_rows": len(cbuffer_rows),
            "kps_rdef_variable_rows": len(variable_rows),
            "kps_signature_element_rows": len(signature_rows),
            "kps_opcode_summary_rows": len(opcode_rows),
            "kps_exact_interface_equal_program_rows": sum(parse_bool(row["exact_interface_equal"]) for row in kps_program_rows),
            "kps_exact_opcode_inventory_equal_program_rows": sum(parse_bool(row["exact_opcode_inventory_equal"]) for row in kps_program_rows),
            "unresolved_g1em_g1t_shader_rows": len(carry_rows),
            "runtime_failed_shader_rows_preserved": sum(
                row["identity"] in {"data/x64/shader/heightfog.g1s", "data/x64/shader/swater.g1s"} for row in carry_rows
            ),
            "payload_bytes_read": payload_bytes_read,
            "skipped_rows": 0,
            "field_semantics_confirmed_rows": 0,
            "visual_or_censorship_semantics_confirmed_rows": 0,
            "new_runtime_confirmed_rows": 0,
            "write_authorized_rows": 0,
            "policy": {
                "local_proprietary_payloads_read": payload_provider is None,
                "proprietary_payloads_in_report": False,
                "exact_section_layout_treated_as_record_semantics": False,
                "rdef_resource_cbuffer_variable_or_signature_name_treated_as_visual_semantics": False,
                "opcode_inventory_treated_as_censorship_or_field_semantics": False,
                "runtime_failed_shader_promoted": False,
                "event_profiles_promoted": False,
                "runtime_or_save_required": False,
                "pak_built_or_repacked": False,
                "installed_game_modified": False,
                "profile_or_registry_modified": False,
                "core_modified": False,
                "translation_modified": False,
                "legacy_dlc_modified": False,
                "git_modified": False,
            },
            "next_action": (
                "Use the exact-section coverage result to decide whether the seven broad G1E families share the previously calibrated section layout. "
                "Where exact envelopes cover changed segments, parse only their table/record contents in a bounded follow-up; where they do not, retain them as separate opaque format families. "
                "Use the exact KPS RDEF/signature/opcode inventories to isolate minimal target-side program edits. Keep leaf meaning, G1EM/G1T and all unresolved shaders nonproduction; do not require saves or authorize writes."
            ),
        }
        atomic_json(output / "SUMMARY.json", summary)

    forbidden = [
        path for path in output.rglob("*") if path.is_file()
        and any(path.name.casefold().endswith(extension) for extension in FORBIDDEN_EXTENSIONS)
    ]
    require(not forbidden, f"forbidden payload files in report: {[path.name for path in forbidden]}")
    if create_archive:
        make_archive(output, archive)
        return archive, summary
    return None, summary


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--report-root", type=Path)
    parser.add_argument("--output-report-root", type=Path)
    parser.add_argument("--workspace-root", type=Path)
    parser.add_argument("--original-root", type=Path)
    parser.add_argument("--quartet-root", type=Path)
    parser.add_argument("--gust-pak", type=Path)
    parser.add_argument("--timeout-seconds", type=int, default=1800)
    parser.add_argument("--skip-payload-hash-verification", action="store_true")
    parser.add_argument("--no-archive", action="store_true")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    archive, summary = build_report(
        args.project_root,
        report_root=args.report_root,
        output_report_root=args.output_report_root,
        workspace_root=args.workspace_root,
        original_root=args.original_root,
        quartet_root=args.quartet_root,
        gust_pak_path=args.gust_pak,
        create_archive=not args.no_archive,
        timeout_seconds=args.timeout_seconds,
        verify_payload_hashes=not args.skip_payload_hash_verification,
    )
    print(json.dumps(summary, indent=2, sort_keys=True))
    if archive:
        print(f"[broad-g1e-kps-exact-layout] report archive: {archive}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
