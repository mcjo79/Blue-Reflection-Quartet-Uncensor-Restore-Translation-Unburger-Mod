#!/usr/bin/env python3
"""Audit indexed Reflector-transformation event families for every heroine.

Stage 77 localized one Quartet-only delta in Yuzuki/Yuzu's indexed RFL family,
but it deliberately used Raimu only as a same-slot control and did not inventory
all heroine families. Stage 78 scans the corrected BR1 event comparison for every
indexed `*_rfl_<slot>.ebd` family, reports every changed event, compares changed
word sequences with same-slot and same-family controls, and cross-references only
strict technical identifiers with the already narrowed stage-76 effect evidence.
Localized dialogue is never exported and no payload is written.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from collections import Counter, defaultdict
from pathlib import Path, PurePosixPath
from typing import Any, Iterable, Mapping, Sequence

TOOL_VERSION = "0.0.91"
REPORT_NAME = "BR_quartet_restoration_all_reflector_transformation_family_evidence.tar.zst"
REPORT_DIR = "all_reflector_transformation_family_evidence"
STAGE77_DIR = "yuzuki_rfl50_event_binding_evidence"
STAGE77_ARCHIVE = "BR_quartet_restoration_yuzuki_rfl50_event_binding_evidence.tar.zst"
STAGE76_DIR = "transformation_brightness_evidence"
STAGE76_ARCHIVE = "BR_quartet_restoration_transformation_brightness_evidence.tar.zst"

RFL_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("party", re.compile(r"^event/skill/skill_party_([a-z0-9_]+?)_rfl_(\d+)\.ebd$", re.IGNORECASE)),
    ("skill", re.compile(r"^event/skill/skill_([a-z0-9_]+?)_rfl_(\d+)\.ebd$", re.IGNORECASE)),
)
TRANSFORMATION_PATH_RE = re.compile(r"(?:^|[/_])(?:rfl|reflector|henshin|transform|transformation|magic_?change)(?:[/_.]|$)", re.IGNORECASE)


class AllReflectorFamilyError(RuntimeError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AllReflectorFamilyError(message)


def progress(message: str) -> None:
    print(f"[stage78] {message}", file=sys.stderr, flush=True)


def contains_word_sequence(haystack: Sequence[int], needle: Sequence[int]) -> bool:
    """Return sequence presence in linear time without per-offset list copies."""
    pattern = tuple(needle)
    if not pattern:
        return False
    if len(pattern) > len(haystack):
        return False
    prefix = [0] * len(pattern)
    matched = 0
    for index in range(1, len(pattern)):
        while matched and pattern[index] != pattern[matched]:
            matched = prefix[matched - 1]
        if pattern[index] == pattern[matched]:
            matched += 1
            prefix[index] = matched
    matched = 0
    for value in haystack:
        while matched and value != pattern[matched]:
            matched = prefix[matched - 1]
        if value == pattern[matched]:
            matched += 1
            if matched == len(pattern):
                return True
    return False


def parse_int(value: Any, default: int = 0) -> int:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return default


def folded(value: Any) -> str:
    return str(value or "").strip().casefold()


def normalize_path(value: Any) -> str:
    path = str(value or "").replace("\\", "/").strip()
    while path.startswith("./"):
        path = path[2:]
    return path.casefold()


def load_json(path: Path) -> dict[str, Any]:
    require(path.is_file(), f"missing required JSON: {path}")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise AllReflectorFamilyError(f"cannot read JSON {path}: {exc}") from exc
    require(isinstance(data, dict), f"JSON root must be an object: {path}")
    return data


def read_tsv(path: Path, *, required: bool = True) -> list[dict[str, str]]:
    if not path.is_file():
        if required:
            raise AllReflectorFamilyError(f"missing required TSV: {path}")
        return []
    with path.open("r", encoding="utf-8", newline="") as handle:
        return [dict(row) for row in csv.DictReader(handle, delimiter="\t")]


def write_tsv(path: Path, fields: Sequence[str], rows: Iterable[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(fields), delimiter="\t", lineterminator="\n", extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fields})


def atomic_json(path: Path, data: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(dict(data), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    temporary.replace(path)


def safe_member_name(raw: str) -> str:
    path = PurePosixPath(raw)
    require(not path.is_absolute() and bool(path.parts) and ".." not in path.parts, f"unsafe report member: {raw}")
    return path.as_posix()


def extract_archive(archive: Path, destination: Path) -> Path:
    require(archive.is_file(), f"missing prerequisite report archive: {archive}")
    listed = subprocess.run(["tar", "--zstd", "-tf", str(archive)], text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    require(listed.returncode == 0, f"cannot list {archive}: {listed.stderr.strip()}")
    roots = {PurePosixPath(safe_member_name(line.strip())).parts[0] for line in listed.stdout.splitlines() if line.strip()}
    require(len(roots) == 1, f"expected one report root in {archive}, found {sorted(roots)}")
    destination.mkdir(parents=True, exist_ok=True)
    done = subprocess.run(["tar", "--zstd", "-xf", str(archive), "-C", str(destination)], text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    require(done.returncode == 0, f"cannot extract {archive}: {done.stderr.strip()}")
    return destination / next(iter(roots))


def locate_report(report_root: Path, direct_name: str, archive_name: str, temporary: Path) -> Path:
    direct = report_root / direct_name
    if direct.is_dir():
        return direct
    return extract_archive(report_root / archive_name, temporary)


def load_stage77_module(project_root: Path) -> Any:
    path = project_root / "workstreams/quartet_restoration/collect_yuzuki_rfl50_event_binding_evidence.py"
    require(path.is_file(), f"missing stage-77 collector: {path}")
    spec = importlib.util.spec_from_file_location("collect_yuzuki_rfl50_event_binding_for_stage78", path)
    require(spec is not None and spec.loader is not None, f"cannot load stage-77 collector: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def parse_family_path(path: str) -> dict[str, Any] | None:
    normalized = normalize_path(path)
    for event_kind, pattern in RFL_PATTERNS:
        match = pattern.match(normalized)
        if match:
            family = match.group(1).casefold()
            slot = int(match.group(2))
            return {
                "normalized_path": normalized,
                "event_kind": event_kind,
                "family_name": family,
                "family_id": f"{event_kind}:{family}",
                "slot": slot,
            }
    return None


def validate_stage77(root: Path) -> dict[str, Any]:
    summary = load_json(root / "SUMMARY.json")
    require(summary.get("type") == "br_quartet_restoration_yuzuki_rfl50_event_binding_evidence_summary", "stage-77 report has unexpected type")
    require(summary.get("tool_version") == "0.0.89", "stage-77 report must be the 0.0.89 report")
    require(parse_int(summary.get("changed_yuzuki_rfl_rows"), -1) == 1, "stage-77 must contain one changed Yuzuki RFL event")
    require(parse_int(summary.get("other_yuzuki_rfl_changed_rows"), -1) == 0, "stage-77 Yuzuki family controls changed unexpectedly")
    require(summary.get("raimu_rfl50_identical") is True, "stage-77 Raimu same-slot control must be identical")
    require(parse_int(summary.get("effect_binding_candidate_rows"), -1) == 0, "stage-77 unexpectedly resolved an effect binding; review before broad audit")
    require(parse_int(summary.get("technical_identifier_rows"), -1) == 0, "stage-77 unexpectedly contains technical identifiers; review before broad audit")
    require(parse_int(summary.get("scene_local_target_word_delta_rows"), -1) >= 1, "stage-77 must retain the scene-local numeric/indexed delta")
    return summary


def make_report_archive(source_dir: Path, output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(output.name + ".tmp")
    temporary.unlink(missing_ok=True)
    done = subprocess.run(["tar", "--zstd", "-cf", str(temporary), "-C", str(source_dir.parent), source_dir.name], text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    require(done.returncode == 0, f"cannot create report archive: {done.stderr.strip()}")
    os.replace(temporary, output)


def inventory_size(entry: Mapping[str, Any], side: str) -> int:
    return parse_int((entry.get(side) or {}).get("size"), -1)


def inventory_sha(entry: Mapping[str, Any], side: str) -> str:
    return str((entry.get(side) or {}).get("sha256", ""))


def entry_changed(entry: Mapping[str, Any]) -> bool:
    classification = folded(entry.get("classification"))
    if classification in {"identical", "unchanged"}:
        return False
    if classification in {"changed", "modified", "different"}:
        return True
    return inventory_sha(entry, "source") != inventory_sha(entry, "target") or inventory_size(entry, "source") != inventory_size(entry, "target")


def sequence_count(stage77: Any, words: Sequence[int], needle: Sequence[int]) -> int:
    # Kept as a compatibility shim for tests/importers; stage77 is intentionally unused.
    del stage77
    return int(contains_word_sequence(words, needle))


def build_report(project_root: Path, *, create_archive: bool = True) -> tuple[Path, Path | None, dict[str, Any]]:
    project_root = project_root.expanduser().resolve()
    report_root = project_root / ".local/reports/quartet_restoration"
    workspace_root = project_root / ".local/build/quartet_restoration"
    require(report_root.is_dir(), f"missing restoration report root: {report_root}")
    require(workspace_root.is_dir(), f"missing restoration workspace: {workspace_root}")
    progress("starting prerequisite validation")
    stage77 = load_stage77_module(project_root)
    br = stage77.load_restoration_tool(project_root)

    with tempfile.TemporaryDirectory(prefix="br-all-rfl-families-") as temporary_name:
        temporary = Path(temporary_name)
        stage77_root = locate_report(report_root, STAGE77_DIR, STAGE77_ARCHIVE, temporary / "stage77")
        stage77_summary = validate_stage77(stage77_root)
        stage76_root = locate_report(report_root, STAGE76_DIR, STAGE76_ARCHIVE, temporary / "stage76")
        stage76_summary, _stage76_paths, stage76_review = stage77.validate_stage76(stage76_root)
        progress("prerequisite reports validated")

        progress("loading corrected BR1 event inventory")
        entries = stage77.load_event_entry(br, report_root)
        progress(f"loaded {len(entries)} in-scope event inventory rows")
        parsed_events: list[dict[str, Any]] = []
        nonindexed_rows: list[dict[str, Any]] = []
        for path, entry in sorted(entries.items()):
            parsed = parse_family_path(path)
            if parsed is None:
                if TRANSFORMATION_PATH_RE.search(path):
                    nonindexed_rows.append({
                        "normalized_path": path,
                        "classification": entry.get("classification", ""),
                        "source_size": inventory_size(entry, "source"),
                        "target_size": inventory_size(entry, "target"),
                        "review_status": "transformation_like_event_path_outside_indexed_rfl_family_requires_separate_naming_audit",
                    })
                continue
            changed = entry_changed(entry)
            parsed_events.append({
                **parsed,
                "classification": "changed" if changed else "identical",
                "source_size": inventory_size(entry, "source"),
                "target_size": inventory_size(entry, "target"),
                "size_delta": inventory_size(entry, "target") - inventory_size(entry, "source"),
                "source_sha256": inventory_sha(entry, "source"),
                "target_sha256": inventory_sha(entry, "target"),
                "review_status": "changed_event_requires_deep_binding_audit" if changed else "byte_identical_family_control",
                "_entry": entry,
            })

        require(parsed_events, "no indexed Reflector transformation event families found")
        progress(f"indexed {len(parsed_events)} transformation events across discovered families")
        target_matches = [row for row in parsed_events if row["normalized_path"] == stage77_summary.get("target_event_path")]
        require(len(target_matches) == 1 and target_matches[0]["classification"] == "changed", "stage-77 Yuzuki target missing from all-family inventory")

        by_family: dict[str, list[dict[str, Any]]] = defaultdict(list)
        by_slot: dict[int, list[dict[str, Any]]] = defaultdict(list)
        for row in parsed_events:
            by_family[row["family_id"]].append(row)
            by_slot[int(row["slot"])].append(row)

        family_rows: list[dict[str, Any]] = []
        for family_id, rows in sorted(by_family.items()):
            slots = sorted(int(row["slot"]) for row in rows)
            changed = [row for row in rows if row["classification"] == "changed"]
            family_rows.append({
                "family_id": family_id,
                "event_kind": rows[0]["event_kind"],
                "family_name": rows[0]["family_name"],
                "event_rows": len(rows),
                "changed_event_rows": len(changed),
                "identical_event_rows": len(rows) - len(changed),
                "slot_min": min(slots),
                "slot_max": max(slots),
                "slot_values": ";".join(str(value) for value in slots),
                "changed_event_paths": ";".join(row["normalized_path"] for row in changed),
                "classification": "contains_changed_event" if changed else "fully_byte_identical_family",
                "review_status": "deep_changed_event_audit_included" if changed else "family_control_no_static_event_delta",
            })

        pair_cache: dict[str, tuple[bytes, bytes, dict[str, Any], dict[str, Any]]] = {}
        analysis_cache: dict[str, dict[str, Any]] = {}

        def pair_for(row: Mapping[str, Any]) -> tuple[bytes, bytes, dict[str, Any], dict[str, Any]]:
            path = str(row["normalized_path"])
            if path not in pair_cache:
                pair_cache[path] = stage77.load_pair(br, workspace_root, row["_entry"])
            return pair_cache[path]

        def analysis_for(row: Mapping[str, Any]) -> dict[str, Any]:
            path = str(row["normalized_path"])
            if path not in analysis_cache:
                source, target, _source_ref, _target_ref = pair_for(row)
                analysis_cache[path] = stage77.analyze_pair(br, path, source, target)
            return analysis_cache[path]

        changed_rows = [row for row in parsed_events if row["classification"] == "changed"]
        require(changed_rows, "all indexed Reflector families are identical, contradicting stage 77")
        progress(f"deep-auditing {len(changed_rows)} changed transformation events")

        changed_summary_rows: list[dict[str, Any]] = []
        slot_control_rows: list[dict[str, Any]] = []
        word_rows: list[dict[str, Any]] = []
        identifier_rows: list[dict[str, Any]] = []
        binding_rows: list[dict[str, Any]] = []
        tag_rows: list[dict[str, Any]] = []

        # Word profiles are loaded only for controls needed by changed events.
        # Byte-identical controls are parsed once without running any SequenceMatcher.
        profile_cache: dict[str, tuple[Sequence[int], Sequence[int]]] = {}
        sequence_presence_cache: dict[tuple[str, str, tuple[int, ...]], bool] = {}

        def words_for(row: Mapping[str, Any]) -> tuple[Sequence[int], Sequence[int]]:
            path = str(row["normalized_path"])
            if path not in profile_cache:
                if row["classification"] == "identical":
                    source, target, _source_ref, _target_ref = pair_for(row)
                    require(source == target, f"inventory marked identical but payloads differ: {path}")
                    header = br.parse_ebd_header_schema(source)
                    require(header.get("classification") == "observed_ebd_name_description_header", f"control EBD header not recognized: {path}")
                    profile = br.profile_ebd_post_header_words(
                        source, int(header["header_end"]), maximum_words=max(1, len(source) // 4 + 8)
                    )
                    profile_cache[path] = (profile["words"], profile["words"])
                else:
                    analysis = analysis_for(row)
                    profile_cache[path] = (analysis["source_profile"]["words"], analysis["target_profile"]["words"])
            return profile_cache[path]

        def sequence_present(row: Mapping[str, Any], side: str, words: Sequence[int], needle: Sequence[int]) -> bool:
            key = (str(row["normalized_path"]), side, tuple(needle))
            if key not in sequence_presence_cache:
                sequence_presence_cache[key] = contains_word_sequence(words, needle)
            return sequence_presence_cache[key]

        ordered_changed = sorted(changed_rows, key=lambda row: (row["family_id"], int(row["slot"])))
        for changed_index, changed in enumerate(ordered_changed, start=1):
            progress(f"changed event {changed_index}/{len(ordered_changed)}: {changed['normalized_path']}")
            path = str(changed["normalized_path"])
            analysis = analysis_for(changed)
            source, target, source_ref, target_ref = pair_for(changed)
            controls = [row for row in by_slot[int(changed["slot"])] if row["normalized_path"] != path]
            same_family_controls = [row for row in by_family[str(changed["family_id"])] if row["normalized_path"] != path]
            changed_controls = [row for row in controls if row["classification"] == "changed"]

            identifiers = stage77.technical_identifier_rows(analysis)
            for row in identifiers:
                identifier_rows.append({
                    "family_id": changed["family_id"],
                    "family_name": changed["family_name"],
                    "slot": changed["slot"],
                    **row,
                })
            bindings = stage77.binding_candidates(analysis, stage76_review)
            for row in bindings:
                binding_rows.append({
                    "family_id": changed["family_id"],
                    "family_name": changed["family_name"],
                    "slot": changed["slot"],
                    **row,
                })

            for index, tag in enumerate(analysis["tag_deltas"]):
                tag_rows.append({
                    "family_id": changed["family_id"],
                    "family_name": changed["family_name"],
                    "slot": changed["slot"],
                    "normalized_path": path,
                    "delta_index": index,
                    "shape_id": br.event_residual_delta_shape_id(tag),
                    **tag,
                    "review_status": "tag_grammar_delta_not_effect_opcode_or_brightness_proof",
                })

            scene_local_word_count = 0
            for delta in analysis["word_deltas"]:
                source_values = list(delta.pop("_source_values"))
                target_values = list(delta.pop("_target_values"))
                same_slot_source_hits = 0
                same_slot_target_hits = 0
                same_family_source_hits = 0
                same_family_target_hits = 0
                for control in controls:
                    control_source_words, control_target_words = words_for(control)
                    same_slot_source_hits += int(sequence_present(control, "source", control_source_words, source_values))
                    same_slot_target_hits += int(sequence_present(control, "target", control_target_words, target_values))
                for control in same_family_controls:
                    control_source_words, control_target_words = words_for(control)
                    same_family_source_hits += int(sequence_present(control, "source", control_source_words, source_values))
                    same_family_target_hits += int(sequence_present(control, "target", control_target_words, target_values))
                scene_local = bool(target_values) and same_slot_target_hits == 0 and same_family_target_hits == 0
                scene_local_word_count += int(scene_local)
                word_rows.append({
                    "family_id": changed["family_id"],
                    "family_name": changed["family_name"],
                    "slot": changed["slot"],
                    **delta,
                    "same_slot_source_family_hits": same_slot_source_hits,
                    "same_slot_target_family_hits": same_slot_target_hits,
                    "same_family_other_source_event_hits": same_family_source_hits,
                    "same_family_other_target_event_hits": same_family_target_hits,
                    "scene_local_target_sequence": scene_local,
                })

            for control in sorted(controls, key=lambda row: row["family_id"]):
                slot_control_rows.append({
                    "changed_event_path": path,
                    "changed_family_id": changed["family_id"],
                    "slot": changed["slot"],
                    "control_event_path": control["normalized_path"],
                    "control_family_id": control["family_id"],
                    "control_classification": control["classification"],
                    "control_source_size": control["source_size"],
                    "control_target_size": control["target_size"],
                    "review_status": "same_slot_cross_family_control",
                })

            target_only_ids = sum(row.get("presence") == "target_only" for row in identifiers)
            changed_summary_rows.append({
                "normalized_path": path,
                "event_kind": changed["event_kind"],
                "family_id": changed["family_id"],
                "family_name": changed["family_name"],
                "slot": changed["slot"],
                "source_size": len(source),
                "target_size": len(target),
                "size_delta": len(target) - len(source),
                "changed_bytes": stage77.byte_difference_count(source, target),
                "source_sha256": hashlib.sha256(source).hexdigest(),
                "target_sha256": hashlib.sha256(target).hexdigest(),
                "source_inventory_sha256": source_ref.get("sha256", ""),
                "target_inventory_sha256": target_ref.get("sha256", ""),
                "raw_delta_rows": len(analysis["raw_deltas"]),
                "schema_token_delta_rows": len(analysis["token_deltas"]),
                "tag_delta_rows": len(analysis["tag_deltas"]),
                "word_delta_rows": len(analysis["word_deltas"]),
                "scene_local_target_word_delta_rows": scene_local_word_count,
                "technical_identifier_rows": len(identifiers),
                "target_only_technical_identifier_rows": target_only_ids,
                "effect_binding_candidate_rows": len(bindings),
                "same_slot_control_rows": len(controls),
                "same_slot_changed_control_rows": len(changed_controls),
                "same_family_control_rows": len(same_family_controls),
                "classification": (
                    "exact_effect_binding_candidate_located" if bindings else
                    "numeric_or_indexed_binding_unresolved" if scene_local_word_count or analysis["tag_deltas"] else
                    "changed_event_without_local_binding_identifier"
                ),
                "review_status": "event_delta_is_not_brightness_or_censorship_proof_without_effect_member_and_runtime_binding",
            })

        progress("writing metadata tables")
        event_rows = [{key: value for key, value in row.items() if key != "_entry"} for row in parsed_events]
        output = report_root / REPORT_DIR
        if output.exists():
            shutil.rmtree(output)
        output.mkdir(parents=True)

        write_tsv(output / "ALL_REFLECTOR_TRANSFORMATION_FAMILIES.tsv", [
            "family_id", "event_kind", "family_name", "event_rows", "changed_event_rows", "identical_event_rows",
            "slot_min", "slot_max", "slot_values", "changed_event_paths", "classification", "review_status",
        ], family_rows)
        write_tsv(output / "ALL_REFLECTOR_TRANSFORMATION_EVENTS.tsv", [
            "normalized_path", "event_kind", "family_id", "family_name", "slot", "classification", "source_size",
            "target_size", "size_delta", "source_sha256", "target_sha256", "review_status",
        ], event_rows)
        write_tsv(output / "ALL_REFLECTOR_TRANSFORMATION_CHANGED_EVENTS.tsv", [
            "normalized_path", "event_kind", "family_id", "family_name", "slot", "source_size", "target_size",
            "size_delta", "changed_bytes", "source_sha256", "target_sha256", "source_inventory_sha256",
            "target_inventory_sha256", "raw_delta_rows", "schema_token_delta_rows", "tag_delta_rows",
            "word_delta_rows", "scene_local_target_word_delta_rows", "technical_identifier_rows",
            "target_only_technical_identifier_rows", "effect_binding_candidate_rows", "same_slot_control_rows",
            "same_slot_changed_control_rows", "same_family_control_rows", "classification", "review_status",
        ], changed_summary_rows)
        write_tsv(output / "ALL_REFLECTOR_TRANSFORMATION_SLOT_CONTROLS.tsv", [
            "changed_event_path", "changed_family_id", "slot", "control_event_path", "control_family_id",
            "control_classification", "control_source_size", "control_target_size", "review_status",
        ], slot_control_rows)
        write_tsv(output / "ALL_REFLECTOR_TRANSFORMATION_WORD_DELTAS.tsv", [
            "family_id", "family_name", "slot", "normalized_path", "delta_index", "sequence_tag", "source_word_start",
            "source_word_end", "target_word_start", "target_word_end", "source_word_count", "target_word_count",
            "source_values_hex", "target_values_hex", "source_sequence_sha256", "target_sequence_sha256",
            "same_slot_source_family_hits", "same_slot_target_family_hits", "same_family_other_source_event_hits",
            "same_family_other_target_event_hits", "scene_local_target_sequence", "review_status",
        ], word_rows)
        write_tsv(output / "ALL_REFLECTOR_TRANSFORMATION_TAG_DELTAS.tsv", [
            "family_id", "family_name", "slot", "normalized_path", "delta_index", "shape_id", "sequence_tag",
            "source_atom_start", "source_atom_end", "target_atom_start", "target_atom_end", "source_atom_count",
            "target_atom_count", "source_first_word_index", "target_first_word_index", "source_tag_values",
            "target_tag_values", "source_atom_sequence_sha256", "target_atom_sequence_sha256", "classification",
            "review_status",
        ], tag_rows)
        write_tsv(output / "ALL_REFLECTOR_TRANSFORMATION_TECHNICAL_IDENTIFIERS.tsv", [
            "family_id", "family_name", "slot", "normalized_path", "presence", "identifier_kind",
            "technical_identifier", "source_hit_count", "target_hit_count", "source_first_offsets",
            "target_first_offsets", "focused_surface_term", "review_status",
        ], identifier_rows)
        write_tsv(output / "ALL_REFLECTOR_TRANSFORMATION_EFFECT_BINDING_CANDIDATES.tsv", [
            "family_id", "family_name", "slot", "event_path", "evidence_source", "effect_path", "effect_member_name",
            "effect_domain", "effect_priority", "lead_classification", "binding_basis", "matched_identifier", "review_status",
        ], binding_rows)
        write_tsv(output / "NON_INDEXED_TRANSFORMATION_EVENT_PATHS.tsv", [
            "normalized_path", "classification", "source_size", "target_size", "review_status",
        ], nonindexed_rows)

        changed_family_ids = sorted({str(row["family_id"]) for row in changed_rows})
        other_changed = [row for row in changed_rows if str(row["normalized_path"]) != str(stage77_summary.get("target_event_path"))]
        family_counts = Counter(row["classification"] for row in family_rows)
        changed_classifications = Counter(row["classification"] for row in changed_summary_rows)
        summary = {
            "type": "br_quartet_restoration_all_reflector_transformation_family_evidence_summary",
            "format_version": 1,
            "tool_version": TOOL_VERSION,
            "source_yuzuki_rfl50_binding_tool_version": stage77_summary.get("tool_version"),
            "source_transformation_brightness_tool_version": stage76_summary.get("tool_version"),
            "status": "all_indexed_reflector_transformation_families_audited_changed_events_localized_effect_and_brightness_binding_unresolved",
            "family_rows": len(family_rows),
            "event_rows": len(parsed_events),
            "changed_event_rows": len(changed_rows),
            "identical_event_rows": len(parsed_events) - len(changed_rows),
            "changed_family_rows": len(changed_family_ids),
            "changed_family_ids": changed_family_ids,
            "other_than_stage77_yuzuki_changed_event_rows": len(other_changed),
            "other_than_stage77_yuzuki_changed_event_paths": [row["normalized_path"] for row in other_changed],
            "non_indexed_transformation_event_path_rows": len(nonindexed_rows),
            "changed_event_word_delta_rows": len(word_rows),
            "changed_event_tag_delta_rows": len(tag_rows),
            "technical_identifier_rows": len(identifier_rows),
            "effect_binding_candidate_rows": len(binding_rows),
            "family_classification_counts": dict(sorted(family_counts.items())),
            "changed_event_classification_counts": dict(sorted(changed_classifications.items())),
            "policy": {
                "installed_game_modified": False,
                "event_payload_written": False,
                "shader_or_effect_payload_written": False,
                "global_bloom_hdr_gamma_or_exposure_restore_attempted": False,
                "pak_repacked": False,
                "core_registry_modified": False,
                "profile_activated": False,
                "localized_event_text_exported": False,
                "technical_identifiers_exported": True,
                "numeric_word_values_exported_as_binding_proof": False,
                "runtime_validation_inferred": False,
                "censorship_semantics_inferred": False,
                "canary_track_modified": False,
            },
            "next_action": (
                "Upload this report. Deep-audit every changed heroine transformation event reported here. If no event other than Yuzuki rfl_50 differs, move to a character-slot/render-member audit for all heroine transformation assets; do not infer that identical EBDs mean identical rendering and do not restore global bloom or exposure without a reversible event-to-member binding."
            ),
        }
        atomic_json(output / "SUMMARY.json", summary)
        archive = report_root / REPORT_NAME if create_archive else None
        if archive:
            progress("creating compressed report archive")
            archive.unlink(missing_ok=True)
            make_report_archive(output, archive)
        progress("completed")
        return output, archive, summary


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit indexed Reflector transformation event families for every heroine")
    parser.add_argument("--project-root", type=Path, required=True)
    parser.add_argument("--no-report-archive", action="store_true")
    args = parser.parse_args()
    output, archive, summary = build_report(args.project_root, create_archive=not args.no_report_archive)
    print(f"Reflector families: {summary['family_rows']}")
    print(f"Indexed transformation events: {summary['event_rows']}")
    print(f"Changed transformation events: {summary['changed_event_rows']}")
    print(f"Changed families: {','.join(summary['changed_family_ids'])}")
    print(f"Other-than-Yuzuki changed events: {summary['other_than_stage77_yuzuki_changed_event_rows']}")
    print(f"Effect binding candidates: {summary['effect_binding_candidate_rows']}")
    print(f"Report directory: {output}")
    if archive:
        print(f"Report: {archive}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except AllReflectorFamilyError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
