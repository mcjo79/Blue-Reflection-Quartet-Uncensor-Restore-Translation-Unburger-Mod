#!/usr/bin/env python3
"""Stage 136: format-specific structural sweep of all changed G1E and KPS members.

The collector consumes the immutable stage-134 member saturation report and the
verified stage-135 format classification. It reads the already extracted local
workspace, or prepares that workspace read-only from the two configured asset
PAKs, then analyzes all 621 changed G1E members and all 27 changed/added KPS
members.

G1E analysis is structural only: exact hashes and sizes, conservative anchor
alignment, gap kinds, bounded dword transition classes and recurring structural
shape families. KPS analysis parses embedded DXBC envelopes and independently
classifies executable-code, reflection/signature and outer-envelope changes.
No field meaning, visual/censorship semantics, runtime validation or write is
inferred. Evidence contains metadata only and no proprietary payload.
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
from typing import Any, Iterable, Mapping, Sequence

TOOL_VERSION = "0.1.54"
REPORT_DIR = "effect_posteffect_g1e_kps_structural_sweep_evidence"
REPORT_NAME = "BR_quartet_restoration_effect_posteffect_g1e_kps_structural_sweep_evidence.tar.zst"

STAGE134_NAME = "BR_quartet_restoration_effect_posteffect_namespace_member_saturation_evidence.tar.zst"
STAGE134_SHA256 = "597238b7b85606b07e50131428a028b37f2233a83fc2f0c063bd812a39738263"
STAGE134_DIR = "effect_posteffect_namespace_member_saturation_evidence"
STAGE134_SUMMARY_SHA256 = "4459b5a464015d7cabd09b44e7d60c26b31287765014f33a7ccc1221ff1530ce"

STAGE135_NAME = "BR_quartet_restoration_effect_posteffect_member_role_format_classification_evidence.tar.zst"
STAGE135_SHA256 = "f19420c6dbfde35272690957128814f4eedc6c39323fd8b56a41693c176bd623"
STAGE135_DIR = "effect_posteffect_member_role_format_classification_evidence"
STAGE135_SUMMARY_SHA256 = "1a1f4a0a74988c0528987338a2467e4aabe43fc924d239c1a1988746dca0a7a3"

EXPECTED_G1E_ROWS = 621
EXPECTED_KPS_ROWS = 27
EXPECTED_CONTAINER_PATHS = 7
MAX_EARC_BYTES = 1024 * 1024 * 1024
MAX_G1E_CHANGED_WORD_ROWS_PER_MEMBER = 4096
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
    print(f"[g1e-kps-structural-sweep] {message}", file=sys.stderr, flush=True)


def version_tuple(value: str) -> tuple[int, ...]:
    try:
        return tuple(int(part) for part in value.strip().split("."))
    except ValueError as exc:
        raise CollectorError(f"invalid version: {value}") from exc


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def safe_relative(value: str, label: str) -> str:
    path = PurePosixPath(str(value).replace("\\", "/"))
    require(bool(path.parts), f"empty {label}")
    require(not path.is_absolute() and ".." not in path.parts, f"unsafe {label}: {value}")
    return path.as_posix()


def parse_bool(value: object) -> bool:
    return str(value).strip().casefold() in {"1", "true", "yes", "y"}


def read_tsv(path: Path) -> list[dict[str, str]]:
    require(path.is_file(), f"missing TSV: {path}")
    with path.open(encoding="utf-8", newline="") as handle:
        return [dict(row) for row in csv.DictReader(handle, delimiter="\t")]


def write_tsv(path: Path, fields: Sequence[str], rows: Iterable[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle, fieldnames=list(fields), delimiter="\t", lineterminator="\n",
            extrasaction="ignore",
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
    archive_hash: str,
    root_name: str,
    summary_hash: str,
) -> tuple[Path, dict[str, Any], list[dict[str, Any]]]:
    archive = report_root / archive_name
    require(archive.is_file(), f"missing prerequisite report: {archive}")
    actual_archive_hash = sha256_file(archive)
    require(actual_archive_hash == archive_hash, f"unexpected {archive_name} SHA-256: {actual_archive_hash}")
    root = report_root / root_name
    if not root.is_dir():
        root = extract_report(archive, temporary / root_name, root_name)
    summary_path = root / "SUMMARY.json"
    require(summary_path.is_file(), f"missing prerequisite summary: {summary_path}")
    actual_summary_hash = sha256_file(summary_path)
    require(actual_summary_hash == summary_hash, f"unexpected {root_name} summary SHA-256: {actual_summary_hash}")
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    hashes = [
        {"input_id": root_name, "relative_path": archive_name, "sha256": actual_archive_hash, "verified": True},
        {"input_id": f"{root_name}_summary", "relative_path": f"{root_name}/SUMMARY.json", "sha256": actual_summary_hash, "verified": True},
    ]
    return root, summary, hashes


def load_module(path: Path, name: str):
    require(path.is_file(), f"missing module: {path}")
    spec = importlib.util.spec_from_file_location(name, path)
    require(spec is not None and spec.loader is not None, f"cannot load module: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def bucket_count(value: int) -> str:
    if value == 0:
        return "0"
    if value == 1:
        return "1"
    if value <= 4:
        return "2_4"
    if value <= 16:
        return "5_16"
    if value <= 64:
        return "17_64"
    return "gt_64"


def g1e_disposition(size_delta: int, segment_counts: Counter[str], match_run_count: int) -> str:
    insertion = segment_counts["target_insertion"]
    deletion = segment_counts["target_deletion"]
    same = segment_counts["same_size_replacement"]
    changing = segment_counts["size_changing_replacement"]
    if size_delta == 0 and same and not insertion and not deletion and not changing:
        return "same_size_replacement_only"
    if (insertion or deletion) and not same and not changing:
        return "pure_insertion_deletion_alignment_candidate"
    if changing and not same and not insertion and not deletion:
        return "size_changing_replacement_only"
    if match_run_count == 0:
        return "no_stable_anchor_run_whole_payload_structurally_unresolved"
    return "mixed_structural_delta"


def g1e_shape_key(row: Mapping[str, Any]) -> str:
    value = "|".join([
        str(row["g1e_structure_disposition"]),
        str(row["delta_shape"]),
        f"runs_{bucket_count(int(row['match_run_rows']))}",
        f"segments_{bucket_count(int(row['alignment_segment_rows']))}",
        f"header_{bucket_count(int(row['header_changed_dword_rows']))}",
        f"flags_{bucket_count(int(row['small_integer_or_flag_transition_rows']))}",
        f"floats_{bucket_count(int(row['finite_float_transition_unresolved_rows']))}",
        f"offsets_{bucket_count(int(row['possible_relative_offset_or_length_rebase_rows']))}",
    ])
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def kps_path_disposition(program_rows: Sequence[Mapping[str, Any]], source_exists: bool, target_exists: bool, outer_delta_shape: str) -> str:
    if not source_exists:
        return "target_added_kps"
    if not target_exists:
        return "target_removed_kps"
    classes = Counter(str(row.get("classification", "")) for row in program_rows)
    if classes["program_added_in_target"] or classes["program_removed_in_target"]:
        return "dxbc_program_inventory_delta"
    if classes["executable_code_delta_with_interface_delta"]:
        return "executable_code_delta_with_interface_delta"
    if classes["executable_code_delta_interface_unresolved"]:
        return "executable_code_delta_interface_unresolved"
    if classes["executable_code_delta_interface_stable"]:
        return "executable_code_delta_interface_stable"
    if classes["interface_delta_without_executable_code_delta"]:
        return "interface_delta_without_executable_code_delta"
    if classes["noncode_delta_interface_parse_unresolved"]:
        return "noncode_delta_interface_parse_unresolved"
    if classes["nonexecutive_metadata_or_compiler_delta"]:
        return "nonexecutive_metadata_or_compiler_delta"
    if classes["identical_program"] and outer_delta_shape != "identical":
        return "outer_kps_envelope_only"
    if not program_rows:
        return "no_valid_dxbc_program_found_structurally_unresolved"
    return "mixed_kps_delta"


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
    if output.exists():
        shutil.rmtree(output)
    output.mkdir(parents=True, exist_ok=True)

    stage134_module = load_module(
        project_root / "workstreams/quartet_restoration/134_collect_effect_posteffect_namespace_member_saturation_evidence.py",
        "stage136_stage134",
    )
    stage84_module = load_module(
        project_root / "workstreams/quartet_restoration/collect_reflector_slot_light_g1e_structure_evidence.py",
        "stage136_stage84",
    )
    stage133_module = load_module(
        project_root / "workstreams/quartet_restoration/133_collect_shader_namespace_executable_signature_reflection_sweep_evidence.py",
        "stage136_stage133",
    )
    br = stage134_module.load_br_tool(project_root)

    with tempfile.TemporaryDirectory(prefix="stage136-prereq-") as temp_text:
        temporary = Path(temp_text)
        stage134, summary134, input134 = locate_report(
            report_root, temporary, STAGE134_NAME, STAGE134_SHA256,
            STAGE134_DIR, STAGE134_SUMMARY_SHA256,
        )
        stage135, summary135, input135 = locate_report(
            report_root, temporary, STAGE135_NAME, STAGE135_SHA256,
            STAGE135_DIR, STAGE135_SUMMARY_SHA256,
        )
        require(summary134.get("nonidentical_member_rows") == 658, "stage-134 non-identical count drift")
        require(summary135.get("g1e_member_rows") == EXPECTED_G1E_ROWS, "stage-135 G1E count drift")
        require(summary135.get("kps_member_rows") == EXPECTED_KPS_ROWS, "stage-135 KPS count drift")
        require(summary135.get("skipped_rows") == 0, "stage-135 contains skipped rows")

        classified = read_tsv(stage135 / "EFFECT_POSTEFFECT_MEMBER_FORMAT_CLASSIFICATION.tsv")
        selected = [row for row in classified if row["member_extension"] in {".g1e", ".kps"}]
        g1e_input_rows = [row for row in selected if row["member_extension"] == ".g1e"]
        kps_input_rows = [row for row in selected if row["member_extension"] == ".kps"]
        require(len(g1e_input_rows) == EXPECTED_G1E_ROWS, f"expected {EXPECTED_G1E_ROWS} G1E rows, found {len(g1e_input_rows)}")
        require(len(kps_input_rows) == EXPECTED_KPS_ROWS, f"expected {EXPECTED_KPS_ROWS} KPS rows, found {len(kps_input_rows)}")

        container_candidates = [
            {"namespace": row["namespace"], "normalized_path": row["normalized_path"]}
            for row in read_tsv(stage134 / "EFFECT_POSTEFFECT_PATH_SUMMARY.tsv")
        ]
        require(len(container_candidates) == EXPECTED_CONTAINER_PATHS, "stage-134 container path count drift")
        inventories = {side: stage134_module.load_inventory(project_root, side) for side in ("source", "target")}
        extraction_rows = stage134_module.ensure_extraction_cache(
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

        payload_maps: dict[tuple[str, str], dict[str, dict[str, Any]]] = {}
        payload_bytes_read = 0
        container_input_rows: list[dict[str, Any]] = []
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

        g1e_rows: list[dict[str, Any]] = []
        g1e_transition_rows: list[dict[str, Any]] = []
        skipped_rows: list[dict[str, Any]] = []
        for index, row in enumerate(sorted(g1e_input_rows, key=lambda item: (item["normalized_path"], item["member_key"])), start=1):
            if index == 1 or index % 50 == 0 or index == EXPECTED_G1E_ROWS:
                progress(f"analyzing G1E {index}/{EXPECTED_G1E_ROWS}")
            normalized = row["normalized_path"].casefold()
            key = row["member_key"]
            left = payload_maps[("source", normalized)].get(key)
            right = payload_maps[("target", normalized)].get(key)
            require(left is not None and right is not None, f"missing G1E member payload pair: {normalized}:{key}")
            source = bytes(left["payload"])
            target = bytes(right["payload"])
            if verify_payload_hashes:
                require(hashlib.sha256(source).hexdigest() == row["source_sha256"], f"source G1E member hash drift: {normalized}:{key}")
                require(hashlib.sha256(target).hexdigest() == row["target_sha256"], f"target G1E member hash drift: {normalized}:{key}")
                require(len(source) == int(row["source_size"]), f"source G1E member size drift: {normalized}:{key}")
                require(len(target) == int(row["target_size"]), f"target G1E member size drift: {normalized}:{key}")
            binary = br.analyze_payload_binary_delta(source, target, extension=".g1e")
            segments, runs = stage84_module.build_alignment_segments(source, target)
            segment_counts = Counter(str(segment["segment_type"]) for segment in segments)
            transition_counts: Counter[str] = Counter()
            emitted = 0
            truncated = False
            for segment_index, segment in enumerate(segments):
                words = stage84_module.changed_words_for_segment(source, target, segment, len(target) - len(source))
                for word in words:
                    transition_counts[str(word["transition_classification"])] += 1
                    if emitted >= MAX_G1E_CHANGED_WORD_ROWS_PER_MEMBER:
                        truncated = True
                        continue
                    g1e_transition_rows.append({
                        "normalized_path": normalized,
                        "member_key": key,
                        "member_name": row["target_member_name"] or row["source_member_name"],
                        "segment_index": segment_index,
                        **word,
                        "visual_or_censorship_semantics_confirmed": False,
                        "runtime_confirmed": False,
                        "write_authorized": False,
                    })
                    emitted += 1
            header_limit = min(96, len(source), len(target))
            header_changed_offsets = [
                offset for offset in range(0, header_limit - 3, 4)
                if source[offset:offset + 4] != target[offset:offset + 4]
            ]
            disposition = g1e_disposition(len(target) - len(source), segment_counts, len(runs))
            enriched = {
                "normalized_path": normalized,
                "member_key": key,
                "normalized_member_role": row["normalized_member_role"],
                "member_name": row["target_member_name"] or row["source_member_name"],
                "source_size": len(source),
                "target_size": len(target),
                "source_sha256": row["source_sha256"],
                "target_sha256": row["target_sha256"],
                "source_magic_hex": source[:16].hex(),
                "target_magic_hex": target[:16].hex(),
                **binary,
                "match_run_rows": len(runs),
                "alignment_segment_rows": len(segments),
                "target_insertion_segment_rows": segment_counts["target_insertion"],
                "target_deletion_segment_rows": segment_counts["target_deletion"],
                "same_size_replacement_segment_rows": segment_counts["same_size_replacement"],
                "size_changing_replacement_segment_rows": segment_counts["size_changing_replacement"],
                "header_changed_dword_rows": len(header_changed_offsets),
                "header_changed_dword_offsets": ",".join(f"0x{offset:x}" for offset in header_changed_offsets),
                "possible_relative_offset_or_length_rebase_rows": transition_counts["possible_relative_offset_or_length_rebase"],
                "small_integer_or_flag_transition_rows": transition_counts["small_integer_or_flag_transition"],
                "finite_float_transition_unresolved_rows": transition_counts["finite_float_transition_unresolved"],
                "opaque_dword_transition_rows": transition_counts["opaque_dword_transition"],
                "changed_word_rows": sum(transition_counts.values()),
                "changed_word_rows_emitted": emitted,
                "changed_word_rows_truncated": truncated,
                "g1e_structure_disposition": disposition,
                "structure_family_id": "",
                "payload_in_evidence": False,
                "visual_or_censorship_semantics_confirmed": False,
                "runtime_confirmed": False,
                "write_authorized": False,
            }
            enriched["structure_family_id"] = g1e_shape_key(enriched)
            g1e_rows.append(enriched)

        g1e_family_groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for row in g1e_rows:
            g1e_family_groups[row["structure_family_id"]].append(row)
        g1e_family_rows: list[dict[str, Any]] = []
        for family_id, rows in sorted(g1e_family_groups.items(), key=lambda item: (-len(item[1]), item[0])):
            g1e_family_rows.append({
                "structure_family_id": family_id,
                "g1e_structure_disposition": rows[0]["g1e_structure_disposition"],
                "delta_shapes": ",".join(sorted({str(row["delta_shape"]) for row in rows})),
                "member_rows": len(rows),
                "container_path_rows": len({str(row["normalized_path"]) for row in rows}),
                "normalized_role_rows": len({str(row["normalized_member_role"]) for row in rows}),
                "recurrent_family": len(rows) >= 2,
                "member_examples": " || ".join(str(row["member_name"]) for row in rows[:12]),
                "semantic_classification": "structural_shape_only_unresolved",
                "write_authorized": False,
            })

        kps_path_rows: list[dict[str, Any]] = []
        kps_program_rows: list[dict[str, Any]] = []
        kps_chunk_rows: list[dict[str, Any]] = []
        for index, row in enumerate(sorted(kps_input_rows, key=lambda item: (item["normalized_path"], item["member_key"])), start=1):
            progress(f"analyzing KPS {index}/{EXPECTED_KPS_ROWS}: {row['target_member_name'] or row['source_member_name']}")
            normalized = row["normalized_path"].casefold()
            key = row["member_key"]
            left = payload_maps[("source", normalized)].get(key)
            right = payload_maps[("target", normalized)].get(key)
            source = bytes(left["payload"]) if left is not None else None
            target = bytes(right["payload"]) if right is not None else None
            require(target is not None, f"missing target KPS payload: {normalized}:{key}")
            if verify_payload_hashes:
                if source is not None:
                    require(hashlib.sha256(source).hexdigest() == row["source_sha256"], f"source KPS member hash drift: {normalized}:{key}")
                    require(len(source) == int(row["source_size"]), f"source KPS member size drift: {normalized}:{key}")
                require(hashlib.sha256(target).hexdigest() == row["target_sha256"], f"target KPS member hash drift: {normalized}:{key}")
                require(len(target) == int(row["target_size"]), f"target KPS member size drift: {normalized}:{key}")
            source_programs = br.find_dxbc_programs(source or b"", label=f"source:{normalized}:{key}")
            target_programs = br.find_dxbc_programs(target, label=f"target:{normalized}:{key}")
            pairs = stage133_module.pair_programs(source_programs, target_programs)
            local_program_rows: list[dict[str, Any]] = []
            for pair_index, pair in enumerate(pairs):
                analysis, chunks = stage133_module.program_analysis(
                    br, source, target, pair.get("source"), pair.get("target"), str(pair["matching_basis"])
                )
                source_program = pair.get("source") or {}
                target_program = pair.get("target") or {}
                program_row = {
                    "normalized_path": normalized,
                    "member_key": key,
                    "member_name": row["target_member_name"] or row["source_member_name"],
                    "program_pair_index": pair_index,
                    "source_program_index": source_program.get("program_index", ""),
                    "target_program_index": target_program.get("program_index", ""),
                    "source_stage": source_program.get("stage", ""),
                    "target_stage": target_program.get("stage", ""),
                    "source_shader_model": source_program.get("shader_model", ""),
                    "target_shader_model": target_program.get("shader_model", ""),
                    "source_program_size": source_program.get("size", ""),
                    "target_program_size": target_program.get("size", ""),
                    "source_program_sha256": source_program.get("sha256", ""),
                    "target_program_sha256": target_program.get("sha256", ""),
                    **analysis,
                    "visual_or_censorship_semantics_confirmed": False,
                    "runtime_confirmed": False,
                    "write_authorized": False,
                }
                local_program_rows.append(program_row)
                kps_program_rows.append(program_row)
                for chunk in chunks:
                    kps_chunk_rows.append({
                        "normalized_path": normalized,
                        "member_key": key,
                        "member_name": row["target_member_name"] or row["source_member_name"],
                        "program_pair_index": pair_index,
                        **chunk,
                        "visual_or_censorship_semantics_confirmed": False,
                        "runtime_confirmed": False,
                        "write_authorized": False,
                    })
            binary = br.analyze_payload_binary_delta(source, target, extension=".kps")
            disposition = kps_path_disposition(local_program_rows, source is not None, target is not None, str(binary["delta_shape"]))
            counts = Counter(str(program["classification"]) for program in local_program_rows)
            kps_path_rows.append({
                "normalized_path": normalized,
                "member_key": key,
                "normalized_member_role": row["normalized_member_role"],
                "member_name": row["target_member_name"] or row["source_member_name"],
                "classification": row["classification"],
                "source_size": len(source) if source is not None else "",
                "target_size": len(target),
                "source_sha256": row["source_sha256"],
                "target_sha256": row["target_sha256"],
                **binary,
                "source_dxbc_program_rows": len(source_programs),
                "target_dxbc_program_rows": len(target_programs),
                "paired_program_rows": len(local_program_rows),
                "identical_program_rows": counts["identical_program"],
                "metadata_only_program_rows": counts["nonexecutive_metadata_or_compiler_delta"],
                "interface_stable_code_delta_program_rows": counts["executable_code_delta_interface_stable"],
                "interface_delta_code_delta_program_rows": counts["executable_code_delta_with_interface_delta"],
                "interface_unresolved_code_delta_program_rows": counts["executable_code_delta_interface_unresolved"],
                "interface_delta_without_code_program_rows": counts["interface_delta_without_executable_code_delta"],
                "program_added_rows": counts["program_added_in_target"],
                "program_removed_rows": counts["program_removed_in_target"],
                "kps_path_disposition": disposition,
                "payload_in_evidence": False,
                "visual_or_censorship_semantics_confirmed": False,
                "runtime_confirmed": False,
                "write_authorized": False,
            })

        unresolved_rows = []
        for row in read_tsv(stage135 / "EFFECT_POSTEFFECT_MEMBER_FORMAT_CLASSIFICATION.tsv"):
            if row["member_extension"] not in {".g1em", ".g1t"}:
                continue
            unresolved_rows.append({
                "scope": "effect_member",
                "identity": f"{row['normalized_path']}::{row['member_key']}",
                "format_family": row["format_family"],
                "disposition": "carry_forward_unresolved_not_in_stage136_scope",
                "visual_or_censorship_semantics_confirmed": False,
                "runtime_confirmed": False,
                "write_authorized": False,
            })
        for row in read_tsv(stage135 / "BOUNDED_SHADER_UNRESOLVED_CARRY_FORWARD.tsv"):
            unresolved_rows.append({
                "scope": "bounded_shader",
                "identity": row["normalized_path"],
                "format_family": "shader_g1s",
                "disposition": "carry_forward_unresolved_no_independent_binding_channel",
                "visual_or_censorship_semantics_confirmed": False,
                "runtime_confirmed": False,
                "write_authorized": False,
            })

        input_hashes = input134 + input135
        write_tsv(output / "INPUT_HASHES.tsv", ["input_id", "relative_path", "sha256", "verified"], input_hashes)
        write_tsv(output / "EXTRACTION_INPUTS.tsv", ["side", "archive_relative", "archive_size", "archive_sha256", "gust_pak_sha256", "cache_action"], extraction_rows)
        write_tsv(output / "CONTAINER_INPUTS.tsv", [
            "side", "namespace", "normalized_path", "container_archive", "input_size", "input_sha256",
            "decoded_bytes", "decoded_sha256", "member_count", "payload_in_evidence", "write_authorized",
        ], container_input_rows)
        write_tsv(output / "G1E_STRUCTURAL_PAIR_AUDIT.tsv", [
            "normalized_path", "member_key", "normalized_member_role", "member_name", "source_size", "target_size",
            "source_sha256", "target_sha256", "source_magic_hex", "target_magic_hex", "classification", "size_delta",
            "common_prefix_bytes", "common_suffix_bytes", "aligned_changed_bytes", "changed_density", "changed_range_count",
            "first_changed_ranges", "changed_dword_count", "delta_shape", "delta_signature", "match_run_rows",
            "alignment_segment_rows", "target_insertion_segment_rows", "target_deletion_segment_rows",
            "same_size_replacement_segment_rows", "size_changing_replacement_segment_rows", "header_changed_dword_rows",
            "header_changed_dword_offsets", "possible_relative_offset_or_length_rebase_rows",
            "small_integer_or_flag_transition_rows", "finite_float_transition_unresolved_rows", "opaque_dword_transition_rows",
            "changed_word_rows", "changed_word_rows_emitted", "changed_word_rows_truncated", "g1e_structure_disposition",
            "structure_family_id", "payload_in_evidence", "visual_or_censorship_semantics_confirmed", "runtime_confirmed",
            "write_authorized",
        ], g1e_rows)
        write_tsv(output / "G1E_DWORD_TRANSITION_AUDIT.tsv", [
            "normalized_path", "member_key", "member_name", "segment_index", "source_offset", "target_offset", "relative_offset",
            "source_u32_hex", "target_u32_hex", "source_float32", "target_float32", "source_float_status", "target_float_status",
            "transition_classification", "transition_id", "visual_or_censorship_semantics_confirmed", "runtime_confirmed", "write_authorized",
        ], g1e_transition_rows)
        write_tsv(output / "G1E_STRUCTURE_FAMILIES.tsv", [
            "structure_family_id", "g1e_structure_disposition", "delta_shapes", "member_rows", "container_path_rows",
            "normalized_role_rows", "recurrent_family", "member_examples", "semantic_classification", "write_authorized",
        ], g1e_family_rows)
        write_tsv(output / "KPS_PATH_CLASSIFICATION.tsv", [
            "normalized_path", "member_key", "normalized_member_role", "member_name", "classification", "source_size", "target_size",
            "source_sha256", "target_sha256", "size_delta", "common_prefix_bytes", "common_suffix_bytes", "aligned_changed_bytes",
            "changed_density", "changed_range_count", "first_changed_ranges", "changed_dword_count", "delta_shape", "delta_signature",
            "source_dxbc_program_rows", "target_dxbc_program_rows", "paired_program_rows", "identical_program_rows",
            "metadata_only_program_rows", "interface_stable_code_delta_program_rows", "interface_delta_code_delta_program_rows",
            "interface_unresolved_code_delta_program_rows", "interface_delta_without_code_program_rows", "program_added_rows",
            "program_removed_rows", "kps_path_disposition", "payload_in_evidence", "visual_or_censorship_semantics_confirmed",
            "runtime_confirmed", "write_authorized",
        ], kps_path_rows)
        write_tsv(output / "KPS_DXBC_PROGRAM_CLASSIFICATION.tsv", [
            "normalized_path", "member_key", "member_name", "program_pair_index", "source_program_index", "target_program_index",
            "source_stage", "target_stage", "source_shader_model", "target_shader_model", "source_program_size", "target_program_size",
            "source_program_sha256", "target_program_sha256", "classification", "matching_basis", "reflection_semantics",
            "signature_semantics", "code_chunks_identical", "source_rdef_status", "target_rdef_status",
            "source_reflection_semantic_sha256", "target_reflection_semantic_sha256", "source_creator_sha256", "target_creator_sha256",
            "source_signature_semantic_sha256", "target_signature_semantic_sha256", "visual_or_censorship_semantics_confirmed",
            "runtime_confirmed", "write_authorized",
        ], kps_program_rows)
        write_tsv(output / "KPS_DXBC_CHUNK_CLASSIFICATION.tsv", [
            "normalized_path", "member_key", "member_name", "program_pair_index", "chunk_key", "fourcc", "source_size", "target_size",
            "source_sha256", "target_sha256", "classification", "visual_or_censorship_semantics_confirmed", "runtime_confirmed", "write_authorized",
        ], kps_chunk_rows)
        write_tsv(output / "UNRESOLVED_G1EM_G1T_SHADER_CARRY_FORWARD.tsv", [
            "scope", "identity", "format_family", "disposition", "visual_or_censorship_semantics_confirmed", "runtime_confirmed", "write_authorized",
        ], unresolved_rows)
        write_tsv(output / "STRUCTURAL_SWEEP_SKIPPED.tsv", ["scope", "identity", "reason"], skipped_rows)

        g1e_dispositions = Counter(str(row["g1e_structure_disposition"]) for row in g1e_rows)
        kps_dispositions = Counter(str(row["kps_path_disposition"]) for row in kps_path_rows)
        kps_program_classes = Counter(str(row["classification"]) for row in kps_program_rows)
        summary = {
            "type": "br_quartet_restoration_effect_posteffect_g1e_kps_structural_sweep_evidence_summary",
            "format_version": 1,
            "tool_version": TOOL_VERSION,
            "status": "all_changed_g1e_and_kps_members_structurally_swept_metadata_only_semantics_unresolved_no_write",
            "stage134_report_sha256": STAGE134_SHA256,
            "stage135_report_sha256": STAGE135_SHA256,
            "container_path_rows": EXPECTED_CONTAINER_PATHS,
            "g1e_member_rows": len(g1e_rows),
            "g1e_structure_family_rows": len(g1e_family_rows),
            "g1e_recurrent_structure_family_rows": sum(parse_bool(row["recurrent_family"]) for row in g1e_family_rows),
            "g1e_changed_word_rows": sum(int(row["changed_word_rows"]) for row in g1e_rows),
            "g1e_changed_word_rows_emitted": len(g1e_transition_rows),
            "g1e_changed_word_truncated_member_rows": sum(parse_bool(row["changed_word_rows_truncated"]) for row in g1e_rows),
            "g1e_structure_dispositions": dict(sorted(g1e_dispositions.items())),
            "kps_member_rows": len(kps_path_rows),
            "kps_changed_member_rows": sum(row["classification"] == "changed" for row in kps_path_rows),
            "kps_target_added_member_rows": sum(row["classification"] == "added_in_target" for row in kps_path_rows),
            "kps_dxbc_program_rows": len(kps_program_rows),
            "kps_dxbc_chunk_rows": len(kps_chunk_rows),
            "kps_path_dispositions": dict(sorted(kps_dispositions.items())),
            "kps_program_classifications": dict(sorted(kps_program_classes.items())),
            "unresolved_g1em_g1t_rows": sum(row["scope"] == "effect_member" for row in unresolved_rows),
            "unresolved_shader_rows": sum(row["scope"] == "bounded_shader" for row in unresolved_rows),
            "payload_bytes_read": payload_bytes_read,
            "skipped_rows": len(skipped_rows),
            "visual_or_censorship_semantics_confirmed_rows": 0,
            "runtime_confirmed_rows": 0,
            "write_authorized_rows": 0,
            "policy": {
                "local_proprietary_payloads_read": True,
                "proprietary_payloads_in_report": False,
                "g1e_alignment_or_dword_shape_treated_as_field_semantics": False,
                "kps_dxbc_code_or_interface_delta_treated_as_visual_semantics": False,
                "member_name_size_recurrence_or_float_appearance_treated_as_censorship_proof": False,
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
                "Use recurring G1E structural families and KPS executable/interface classifications to isolate bounded format families for exact parser work. "
                "Keep all G1EM/G1T members and fifteen shaders unresolved unless an independent binding or semantic channel appears. "
                "Do not require saves, build Canary-all or authorize writes."
            ),
        }
        atomic_json(output / "SUMMARY.json", summary)

    forbidden = [
        path for path in output.rglob("*") if path.is_file()
        and any(path.name.casefold().endswith(ext) for ext in FORBIDDEN_EXTENSIONS)
    ]
    require(not forbidden, f"forbidden payload files in report: {[path.name for path in forbidden]}")
    if create_archive:
        make_archive(output, archive)
        return archive, summary
    return None, summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--report-root", type=Path)
    parser.add_argument("--output-report-root", type=Path)
    parser.add_argument("--workspace-root", type=Path)
    parser.add_argument("--original-root", type=Path)
    parser.add_argument("--quartet-root", type=Path)
    parser.add_argument("--gust-pak", type=Path)
    parser.add_argument("--timeout-seconds", type=int, default=1800)
    parser.add_argument("--no-archive", action="store_true")
    parser.add_argument("--skip-payload-hash-verification", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
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
        print(f"[g1e-kps-structural-sweep] report archive: {archive}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
