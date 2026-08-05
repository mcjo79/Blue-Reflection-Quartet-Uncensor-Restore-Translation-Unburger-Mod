#!/usr/bin/env python3
"""Audit common Reflector ringlight words, neutral controls and exact call sites.

Stage 80 proved that e_cmn_ringlight_PC00-PC14 share one exact reversible byte
layout, but its changed runs cut across 32-bit words and therefore were not
eligible for a static prototype. Stage 81 rehydrates the four parent effect
containers, converts the common family delta to complete aligned word
transitions, scans sibling G1E/G1EM members for the same transitions, and scans
both parent containers and all 68 indexed transformation EBDs for exact ASCII
or UTF-16LE references to the common ringlight member names. Metadata only is
written; brightness/censorship semantics are not inferred.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import importlib.util
import json
import math
import os
import re
import struct
import subprocess
import sys
import tempfile
from collections import defaultdict
from pathlib import Path, PurePosixPath
from typing import Any, Callable, Iterable, Mapping, Sequence

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT_DEFAULT = SCRIPT_DIR.parent.parent
TEXT_TOOL_DIR = PROJECT_ROOT_DEFAULT / "Blue_Reflection_Text_Tool"
if str(TEXT_TOOL_DIR) not in sys.path:
    sys.path.insert(0, str(TEXT_TOOL_DIR))
import br_restoration_tool as BR  # noqa: E402

TOOL_VERSION = "0.0.95"
REPORT_NAME = "BR_quartet_restoration_reflector_ringlight_control_callsite_evidence.tar.zst"
REPORT_DIR = "reflector_ringlight_control_callsite_evidence"
STAGE80_DIR = "reflector_light_family_binary_evidence"
STAGE80_ARCHIVE = "BR_quartet_restoration_reflector_light_family_binary_evidence.tar.zst"
STAGE79_DIR = "reflector_character_slot_render_member_evidence"
STAGE79_ARCHIVE = "BR_quartet_restoration_reflector_character_slot_render_member_evidence.tar.zst"
STAGE78_DIR = "all_reflector_transformation_family_evidence"
STAGE78_ARCHIVE = "BR_quartet_restoration_all_reflector_transformation_family_evidence.tar.zst"
COMMON_FAMILY_KEY = "ringlight:e_cmn_ringlight_PCXX.g1e"
EXPECTED_COMMON_ROWS = 15
EXPECTED_EVENT_ROWS = 68
EFFECT_EXTENSIONS = {".g1e", ".g1em"}
TRANSFORMATION_NAME_RE = re.compile(r"(?:rfl|reflector|henshin|transform|ringlight|eyelight|pc\d{2})", re.IGNORECASE)
LIGHT_NAME_RE = re.compile(r"(?:ringlight|eyelight|light|glow|bloom|illum|emiss)", re.IGNORECASE)


class Stage81Error(RuntimeError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise Stage81Error(message)


def progress(message: str) -> None:
    print(f"[stage81] {message}", file=sys.stderr, flush=True)


def parse_int(value: Any, default: int = 0) -> int:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return default


def parse_bool(value: Any) -> bool:
    return str(value).strip().casefold() in {"1", "true", "yes", "y"}


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def safe_name(raw: str) -> str:
    path = PurePosixPath(raw)
    require(not path.is_absolute() and path.parts and ".." not in path.parts, f"unsafe archive member: {raw}")
    return path.as_posix()


def read_tsv(path: Path, required: bool = True) -> list[dict[str, str]]:
    if not path.is_file():
        if required:
            raise Stage81Error(f"missing required TSV: {path}")
        return []
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
        raise Stage81Error(f"invalid JSON {path}: {exc}") from exc
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
    require(spec is not None and spec.loader is not None, f"cannot load collector: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def stable_key(row: Mapping[str, Any]) -> tuple[str, str, str]:
    return (
        str(row.get("candidate_id", "")),
        str(row.get("normalized_path", "")).casefold(),
        str(row.get("member_key", "")).casefold(),
    )


def stage80_audit_key(row: Mapping[str, Any]) -> tuple[str, str]:
    """Return the stable identity actually exported by stage 80.

    REFLECTOR_LIGHT_MEMBER_BINARY_AUDIT.tsv intentionally contains the parent
    path and member comparison key, but not candidate_id.  Stage 81 must not
    fabricate an empty candidate_id and compare it with the stage-79 candidate
    identity.  Parent path + member key is unique within the 21-member audited
    scope; duplicate rows are rejected when the map is built.
    """
    return (
        str(row.get("normalized_path", "")).casefold(),
        str(row.get("member_key", "")).casefold(),
    )


def validate_stage80(root: Path) -> dict[str, Any]:
    summary = load_json(root / "SUMMARY.json")
    require(summary.get("type") == "br_quartet_restoration_reflector_light_family_binary_evidence_summary", "stage80 type mismatch")
    require(summary.get("tool_version") == "0.0.93", "stage80 must use tool version 0.0.93")
    require(parse_int(summary.get("common_ringlight_member_rows"), -1) == EXPECTED_COMMON_ROWS, "stage80 common family count mismatch")
    require(summary.get("common_ringlight_family_classification") == "uniform_exact_delta_across_slots", "stage80 common family is not uniform")
    require(parse_int(summary.get("skipped_rows"), -1) == 0, "stage80 contains skipped rows")
    policy = summary.get("policy") or {}
    require(isinstance(policy, dict), "stage80 policy malformed")
    for field in ("installed_game_modified", "render_payload_written", "pak_repacked", "core_registry_modified", "profile_activated"):
        require(not parse_bool(policy.get(field)), f"stage80 performed forbidden action: {field}")
    return summary


def validate_stage79(root: Path) -> dict[str, Any]:
    summary = load_json(root / "SUMMARY.json")
    require(summary.get("type") == "br_quartet_restoration_reflector_character_slot_render_member_evidence_summary", "stage79 type mismatch")
    require(summary.get("tool_version") == "0.0.92", "stage79 must use tool version 0.0.92")
    require(parse_int(summary.get("character_slot_rows"), -1) == 15, "stage79 character slot count mismatch")
    return summary


def validate_stage78(root: Path) -> dict[str, Any]:
    summary = load_json(root / "SUMMARY.json")
    require(summary.get("type") == "br_quartet_restoration_all_reflector_transformation_family_evidence_summary", "stage78 type mismatch")
    require(summary.get("tool_version") == "0.0.91", "stage78 must use corrected tool version 0.0.91")
    require(parse_int(summary.get("event_rows"), -1) == EXPECTED_EVENT_ROWS, "stage78 event count mismatch")
    require(parse_int(summary.get("changed_event_rows"), -1) == 1, "stage78 changed event count mismatch")
    return summary


def select_common_scope(stage79_root: Path) -> list[dict[str, str]]:
    rows = read_tsv(stage79_root / "REFLECTOR_SLOT_RENDER_MEMBERS.tsv")
    common = [row for row in rows if row.get("family_key") == COMMON_FAMILY_KEY]
    require(len(common) == EXPECTED_COMMON_ROWS, f"expected {EXPECTED_COMMON_ROWS} common ringlight rows, found {len(common)}")
    require(sorted(row.get("character_slot", "") for row in common) == [f"PC{i:02d}" for i in range(15)], "common ringlight slots mismatch")
    return sorted(common, key=lambda row: row.get("character_slot", ""))


def select_parent_scope(stage79_root: Path) -> list[dict[str, str]]:
    rows = read_tsv(stage79_root / "REFLECTOR_SLOT_RENDER_MEMBERS.tsv")
    scope = [row for row in rows if row.get("asset_role") in {"ringlight", "eyelight"}]
    require(len(scope) == 21, f"expected 21 light members, found {len(scope)}")
    return sorted(scope, key=lambda row: (row.get("normalized_path", ""), row.get("member_key", "")))


def load_parent_containers(
    *, scope_rows: Sequence[Mapping[str, Any]], workspace_root: Path, report_root: Path,
    rules_file: Path, maximum_earc_bytes: int,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    differences = BR.load_report_jsons(report_root, "differences")
    effects = BR.build_effect_material_candidates(differences, BR.load_effect_material_rules(rules_file))
    effect_map: dict[tuple[str, str], dict[str, Any]] = {}
    for effect in effects:
        key = (str(effect.get("candidate_id", "")), str(effect.get("normalized_path", "")).casefold())
        require(key not in effect_map, f"duplicate effect candidate identity: {key}")
        effect_map[key] = effect
    grouped: dict[tuple[str, str], list[Mapping[str, Any]]] = defaultdict(list)
    for row in scope_rows:
        grouped[(str(row.get("candidate_id", "")), str(row.get("normalized_path", "")).casefold())].append(row)
    containers: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    for index, ((candidate_id, folded_path), rows) in enumerate(sorted(grouped.items()), start=1):
        progress(f"rehydrating parent container {index}/{len(grouped)}: {folded_path}")
        effect = effect_map.get((candidate_id, folded_path))
        require(effect is not None, f"effect candidate missing for {candidate_id} {folded_path}")
        archives: dict[str, dict[str, Any] | None] = {"source": None, "target": None}
        for side in ("source", "target"):
            ref = effect.get(side)
            if not ref:
                skipped.append({"scope": "container", "normalized_path": folded_path, "member_key": "<archive>", "side": side, "reason": "archive_reference_missing"})
                continue
            local = BR.inventory_workspace_file(workspace_root, side, str(effect.get("pair_id", "")), str(ref.get("archive", "")), str(ref.get("path", "")))
            if not local.is_file():
                skipped.append({"scope": "container", "normalized_path": folded_path, "member_key": "<archive>", "side": side, "reason": "workspace_file_missing"})
                continue
            try:
                archives[side] = BR.read_earc_archive(local, maximum_bytes=maximum_earc_bytes, include_member_payloads=True)
            except Exception as exc:
                skipped.append({"scope": "container", "normalized_path": folded_path, "member_key": "<archive>", "side": side, "reason": f"archive_parse_failed:{exc}"})
        if archives["source"] is None or archives["target"] is None:
            continue
        containers.append({
            "candidate_id": candidate_id,
            "normalized_path": folded_path,
            "scope_rows": list(rows),
            "source_members": list((archives["source"] or {}).get("members", [])),
            "target_members": list((archives["target"] or {}).get("members", [])),
        })
    return containers, skipped


def load_transformation_events(
    *, project_root: Path, stage78_root: Path, workspace_root: Path, report_root: Path,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    stage78 = load_module(project_root / "workstreams/quartet_restoration/collect_all_reflector_transformation_family_evidence.py", "stage78_for_stage81")
    stage77 = stage78.load_stage77_module(project_root)
    br = stage77.load_restoration_tool(project_root)
    inventory = stage77.load_event_entry(br, report_root)
    event_rows = read_tsv(stage78_root / "ALL_REFLECTOR_TRANSFORMATION_EVENTS.tsv")
    require(len(event_rows) == EXPECTED_EVENT_ROWS, "stage78 event table count mismatch")
    pairs: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    for index, row in enumerate(event_rows, start=1):
        if index == 1 or index % 10 == 0 or index == len(event_rows):
            progress(f"rehydrating transformation event {index}/{len(event_rows)}")
        path = str(row.get("normalized_path", "")).casefold()
        entry = inventory.get(path)
        if entry is None:
            skipped.append({"scope": "event", "normalized_path": path, "member_key": "<direct>", "side": "pair", "reason": "event_inventory_entry_missing"})
            continue
        try:
            source, target, _source_ref, _target_ref = stage77.load_pair(br, workspace_root, entry)
        except Exception as exc:
            skipped.append({"scope": "event", "normalized_path": path, "member_key": "<direct>", "side": "pair", "reason": f"event_rehydrate_failed:{exc}"})
            continue
        if row.get("source_sha256") and sha256(source) != row.get("source_sha256"):
            raise Stage81Error(f"stage78 source hash mismatch: {path}")
        if row.get("target_sha256") and sha256(target) != row.get("target_sha256"):
            raise Stage81Error(f"stage78 target hash mismatch: {path}")
        pairs.append({**row, "source_payload": source, "target_payload": target})
    return pairs, skipped


def aligned_word_deltas(source: bytes, target: bytes) -> list[dict[str, Any]]:
    require(len(source) == len(target), "aligned word audit requires equal sizes")
    require(len(source) % 4 == 0, "aligned word audit requires dword-sized payload")
    rows: list[dict[str, Any]] = []
    for offset in range(0, len(source), 4):
        left = source[offset:offset + 4]
        right = target[offset:offset + 4]
        if left == right:
            continue
        source_u32 = int.from_bytes(left, "little")
        target_u32 = int.from_bytes(right, "little")
        source_float = struct.unpack("<f", left)[0]
        target_float = struct.unpack("<f", right)[0]
        if math.isfinite(source_float) and math.isfinite(target_float):
            float_status = "finite_float_interpretation_available"
        else:
            float_status = "nonfinite_float_interpretation"
        transition_id = hashlib.sha256(left + right).hexdigest()
        rows.append({
            "word_offset": offset,
            "source_u32_hex": f"0x{source_u32:08x}",
            "target_u32_hex": f"0x{target_u32:08x}",
            "source_float32": f"{source_float:.9g}" if math.isfinite(source_float) else str(source_float),
            "target_float32": f"{target_float:.9g}" if math.isfinite(target_float) else str(target_float),
            "float_status": float_status,
            "transition_id": transition_id,
            "source_word": left,
            "target_word": right,
        })
    return rows


def control_scope(member_name: str) -> str:
    if re.search(r"ringlight", member_name, re.IGNORECASE):
        return "ringlight_named_control"
    if re.search(r"eyelight", member_name, re.IGNORECASE):
        return "eyelight_named_control"
    if TRANSFORMATION_NAME_RE.search(member_name):
        return "transformation_or_character_named_control"
    if LIGHT_NAME_RE.search(member_name):
        return "other_light_named_control"
    return "neutral_non_transformation_name_control"


def find_offsets(payload: bytes, needle: bytes, maximum: int = 32) -> list[int]:
    if not needle:
        return []
    offsets: list[int] = []
    start = 0
    while len(offsets) < maximum:
        found = payload.find(needle, start)
        if found < 0:
            break
        offsets.append(found)
        start = found + 1
    return offsets


def reference_tokens(common_rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    tokens: dict[tuple[str, str, str], dict[str, Any]] = {}
    for row in common_rows:
        slot = str(row.get("character_slot", ""))
        for name in {str(row.get("member_name", "")), f"e_cmn_ringlight_{slot}.g1e"}:
            if not name:
                continue
            stem = Path(name).stem
            for form, text in (("full_name", name), ("stem", stem), ("full_name_lower", name.casefold()), ("stem_lower", stem.casefold())):
                for encoding, encoded in (("ascii", text.encode("ascii", errors="ignore")), ("utf16le", text.encode("utf-16le"))):
                    if encoded:
                        tokens[(slot, form, encoding)] = {"referenced_slot": slot, "token_form": form, "encoding": encoding, "token": encoded, "token_sha256": sha256(encoded)}
    return sorted(tokens.values(), key=lambda row: (row["referenced_slot"], row["token_form"], row["encoding"]))


def scan_references(payload: bytes, tokens: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    hits: list[dict[str, Any]] = []
    for token in tokens:
        offsets = find_offsets(payload, bytes(token["token"]))
        if offsets:
            hits.append({
                "referenced_slot": token["referenced_slot"],
                "token_form": token["token_form"],
                "encoding": token["encoding"],
                "token_sha256": token["token_sha256"],
                "hit_count": len(offsets),
                "first_offsets": ";".join(str(value) for value in offsets),
            })
    return hits


def build_report(
    project_root: Path, *, create_archive: bool = True,
    workspace_root: Path | None = None, report_root: Path | None = None,
    rules_file: Path | None = None, maximum_earc_bytes: int = 512 * 1024 * 1024,
    container_loader: Callable[..., tuple[list[dict[str, Any]], list[dict[str, Any]]]] | None = None,
    event_loader: Callable[..., tuple[list[dict[str, Any]], list[dict[str, Any]]]] | None = None,
) -> tuple[Path, Path | None, dict[str, Any]]:
    project_root = project_root.resolve()
    reports = (report_root or project_root / ".local/reports/quartet_restoration").resolve()
    workspace = (workspace_root or project_root / ".local/build/quartet_restoration").resolve()
    require(reports.is_dir(), f"missing report root: {reports}")
    progress("validating stage 78-80 reports")
    with tempfile.TemporaryDirectory(prefix="br-stage81-") as temporary_name:
        temporary = Path(temporary_name)
        stage80_root = locate(reports, STAGE80_DIR, STAGE80_ARCHIVE, temporary / "80")
        stage79_root = locate(reports, STAGE79_DIR, STAGE79_ARCHIVE, temporary / "79")
        stage78_root = locate(reports, STAGE78_DIR, STAGE78_ARCHIVE, temporary / "78")
        summary80 = validate_stage80(stage80_root)
        summary79 = validate_stage79(stage79_root)
        summary78 = validate_stage78(stage78_root)
        common_scope = select_common_scope(stage79_root)
        parent_scope = select_parent_scope(stage79_root)
        audit80 = read_tsv(stage80_root / "REFLECTOR_LIGHT_MEMBER_BINARY_AUDIT.tsv")
        audit_map: dict[tuple[str, str], dict[str, str]] = {}
        for row in audit80:
            key = stage80_audit_key(row)
            require(all(key), f"stage80 member audit identity incomplete: {key}")
            require(key not in audit_map, f"duplicate stage80 member audit identity: {key}")
            audit_map[key] = row
        require(len(audit_map) == 21, "stage80 member audit count mismatch")

        actual_rules = rules_file or project_root / "titles/blue_reflection/modules/quartet_restoration/mappings/effect_material_rules.tsv"
        actual_container_loader = container_loader or load_parent_containers
        containers, skipped = actual_container_loader(
            scope_rows=parent_scope,
            workspace_root=workspace,
            report_root=reports,
            rules_file=actual_rules,
            maximum_earc_bytes=maximum_earc_bytes,
        )
        require(not skipped, f"parent container loader skipped {len(skipped)} rows")
        require(len(containers) == 4, f"expected four parent containers, found {len(containers)}")

        pair_map: dict[tuple[str, str, str], dict[str, Any]] = {}
        for container in containers:
            source_members = {str(row.get("comparison_key", "")).casefold(): row for row in container.get("source_members", [])}
            target_members = {str(row.get("comparison_key", "")).casefold(): row for row in container.get("target_members", [])}
            for scope in container.get("scope_rows", []):
                key = stable_key(scope)
                member_key = str(scope.get("member_key", "")).casefold()
                left = source_members.get(member_key)
                right = target_members.get(member_key)
                require(left is not None and right is not None, f"scoped light member missing from parent container: {key}")
                pair_map[key] = {
                    **scope,
                    "source_member_name": str(left.get("name", "")),
                    "target_member_name": str(right.get("name", "")),
                    "source_payload": bytes(left.get("payload") or b""),
                    "target_payload": bytes(right.get("payload") or b""),
                }
        require(len(pair_map) == 21, f"rehydrated {len(pair_map)} of 21 light members")

        slot_word_rows: list[dict[str, Any]] = []
        canonical_profile: list[tuple[int, bytes, bytes]] | None = None
        for scope in common_scope:
            key = stable_key(scope)
            pair = pair_map.get(key)
            require(pair is not None, f"common ringlight pair missing: {key}")
            source = pair["source_payload"]; target = pair["target_payload"]
            audit_key = stage80_audit_key(scope)
            stage80_row = audit_map.get(audit_key)
            require(stage80_row is not None, f"stage80 audit row missing: {audit_key}")
            require(stage80_row.get("source_sha256") == sha256(source), f"stage80 source hash mismatch: {key}")
            require(stage80_row.get("target_sha256") == sha256(target), f"stage80 target hash mismatch: {key}")
            require(parse_bool(stage80_row.get("exact_source_inverse")) and parse_bool(stage80_row.get("exact_target_roundtrip")), f"stage80 inverse gate failed: {key}")
            words = aligned_word_deltas(source, target)
            profile = [(int(row["word_offset"]), bytes(row["source_word"]), bytes(row["target_word"])) for row in words]
            if canonical_profile is None:
                canonical_profile = profile
            else:
                require(profile == canonical_profile, f"common ringlight aligned word profile differs for {scope.get('character_slot')}")
            for row in words:
                slot_word_rows.append({
                    "character_slot": scope.get("character_slot", ""),
                    "normalized_path": scope.get("normalized_path", ""),
                    "member_key": scope.get("member_key", ""),
                    "member_name": pair.get("target_member_name", ""),
                    **{k: v for k, v in row.items() if k not in {"source_word", "target_word"}},
                    "review_status": "aligned_word_interpretation_not_parameter_or_brightness_proof",
                })
        require(canonical_profile is not None and canonical_profile, "common ringlight has no aligned word deltas")
        canonical_rows: list[dict[str, Any]] = []
        first_slot_rows = [row for row in slot_word_rows if row["character_slot"] == "PC00"]
        require(len(first_slot_rows) == len(canonical_profile), "PC00 canonical word count mismatch")
        for row in first_slot_rows:
            canonical_rows.append({
                "word_offset": row["word_offset"],
                "source_u32_hex": row["source_u32_hex"],
                "target_u32_hex": row["target_u32_hex"],
                "source_float32": row["source_float32"],
                "target_float32": row["target_float32"],
                "float_status": row["float_status"],
                "transition_id": row["transition_id"],
                "slot_count": 15,
                "slots": ";".join(f"PC{i:02d}" for i in range(15)),
                "uniform_across_slots": True,
                "review_status": "uniform_aligned_word_transition_semantics_unresolved",
            })
        canonical_transition_map = {str(row["transition_id"]): row for row in canonical_rows}

        control_rows: list[dict[str, Any]] = []
        control_match_rows: list[dict[str, Any]] = []
        container_reference_rows: list[dict[str, Any]] = []
        common_member_keys = {str(row.get("member_key", "")).casefold() for row in common_scope}
        tokens = reference_tokens(common_scope)
        for container_index, container in enumerate(containers, start=1):
            progress(f"scanning controls and references in container {container_index}/{len(containers)}")
            source_members = {str(row.get("comparison_key", "")).casefold(): row for row in container.get("source_members", [])}
            target_members = {str(row.get("comparison_key", "")).casefold(): row for row in container.get("target_members", [])}
            all_keys = sorted(set(source_members) | set(target_members))
            for member_key in all_keys:
                left = source_members.get(member_key); right = target_members.get(member_key)
                if left is None or right is None:
                    skipped.append({"scope": "control", "normalized_path": container["normalized_path"], "member_key": member_key, "side": "pair", "reason": "source_or_target_member_missing"})
                    continue
                source_payload = bytes(left.get("payload") or b"")
                target_payload = bytes(right.get("payload") or b"")
                member_name = str(right.get("name") or left.get("name") or "")
                extension = Path(member_name).suffix.casefold()
                for side, payload, current_name in (("source", source_payload, str(left.get("name", ""))), ("target", target_payload, str(right.get("name", "")))):
                    for hit in scan_references(payload, tokens):
                        referenced_name = f"e_cmn_ringlight_{hit['referenced_slot']}.g1e"
                        self_reference = current_name.casefold() == referenced_name.casefold()
                        container_reference_rows.append({
                            "normalized_path": container["normalized_path"],
                            "side": side,
                            "referencing_member_key": member_key,
                            "referencing_member_name": current_name,
                            **hit,
                            "self_reference": self_reference,
                            "binding_status": "self_name_metadata" if self_reference else "exact_container_member_reference_candidate",
                        })
                if extension not in EFFECT_EXTENSIONS or member_key in common_member_keys:
                    continue
                if len(source_payload) != len(target_payload) or len(source_payload) % 4:
                    control_rows.append({
                        "normalized_path": container["normalized_path"], "member_key": member_key,
                        "member_name": member_name, "extension": extension,
                        "source_size": len(source_payload), "target_size": len(target_payload),
                        "classification": "size_or_structure_changed_control", "control_scope": control_scope(member_name),
                        "changed_word_rows": 0, "matched_common_transition_rows": 0,
                        "review_status": "format_aware_control_audit_required",
                    })
                    continue
                deltas = aligned_word_deltas(source_payload, target_payload)
                matches = [row for row in deltas if str(row["transition_id"]) in canonical_transition_map]
                control_rows.append({
                    "normalized_path": container["normalized_path"], "member_key": member_key,
                    "member_name": member_name, "extension": extension,
                    "source_size": len(source_payload), "target_size": len(target_payload),
                    "classification": "identical_control" if not deltas else "same_size_changed_control",
                    "control_scope": control_scope(member_name),
                    "changed_word_rows": len(deltas), "matched_common_transition_rows": len(matches),
                    "review_status": "exact_common_transition_overlap_found" if matches else "no_exact_common_transition_overlap",
                })
                for match in matches:
                    canonical = canonical_transition_map[str(match["transition_id"])]
                    control_match_rows.append({
                        "normalized_path": container["normalized_path"], "member_key": member_key,
                        "member_name": member_name, "control_scope": control_scope(member_name),
                        "control_word_offset": match["word_offset"],
                        "common_word_offset": canonical["word_offset"],
                        "source_u32_hex": match["source_u32_hex"], "target_u32_hex": match["target_u32_hex"],
                        "source_float32": match["source_float32"], "target_float32": match["target_float32"],
                        "float_status": match["float_status"], "transition_id": match["transition_id"],
                        "review_status": "shared_word_transition_not_shared_parameter_or_semantics_proof",
                    })

        actual_event_loader = event_loader or load_transformation_events
        event_pairs, event_skipped = actual_event_loader(
            project_root=project_root, stage78_root=stage78_root,
            workspace_root=workspace, report_root=reports,
        )
        skipped.extend(event_skipped)
        require(len(event_pairs) == EXPECTED_EVENT_ROWS, f"rehydrated {len(event_pairs)} of {EXPECTED_EVENT_ROWS} transformation events")
        event_reference_rows: list[dict[str, Any]] = []
        for index, event in enumerate(event_pairs, start=1):
            if index == 1 or index % 10 == 0 or index == len(event_pairs):
                progress(f"scanning exact ringlight names in event {index}/{len(event_pairs)}")
            for side in ("source", "target"):
                payload = bytes(event.get(f"{side}_payload") or b"")
                for hit in scan_references(payload, tokens):
                    event_reference_rows.append({
                        "normalized_path": event.get("normalized_path", ""),
                        "family_id": event.get("family_id", ""),
                        "family_name": event.get("family_name", ""),
                        "event_slot": event.get("slot", ""),
                        "event_classification": event.get("classification", ""),
                        "side": side,
                        **hit,
                        "binding_status": "exact_member_name_reference_in_transformation_event",
                    })

        nonself_container_refs = [row for row in container_reference_rows if not parse_bool(row.get("self_reference"))]
        neutral_matches = [row for row in control_match_rows if row.get("control_scope") == "neutral_non_transformation_name_control"]
        named_light_matches = [row for row in control_match_rows if row.get("control_scope") in {"ringlight_named_control", "eyelight_named_control", "other_light_named_control"}]
        exact_callsite_resolved = bool(nonself_container_refs or event_reference_rows)
        if neutral_matches:
            status = "uniform_ringlight_word_delta_has_neutral_control_overlap_brightness_semantics_unresolved"
            next_action = "Upload this report. Shared neutral-control word transitions must be treated as possible engine/remaster-wide serialization or parameter changes. Parse the exact G1E record structure before any prototype; do not restore the common family as a group."
        elif exact_callsite_resolved:
            status = "uniform_ringlight_word_delta_has_exact_name_callsite_no_neutral_overlap_semantics_unresolved"
            next_action = "Upload this report. Audit the exact referenced G1E records and their parameter structure around the uniform aligned words. An exact name reference is a binding lead, not brightness or censorship proof."
        else:
            status = "uniform_ringlight_word_delta_no_neutral_overlap_no_exact_name_callsite_format_audit_required"
            next_action = "Upload this report. Exact filename call sites remain unresolved; perform a format-aware G1E record audit of the uniform word offsets and compare them with structurally homologous non-transformation effects before any prototype."

        output_dir = reports / REPORT_DIR
        if output_dir.exists():
            import shutil
            shutil.rmtree(output_dir)
        output_dir.mkdir(parents=True)
        write_tsv(output_dir / "COMMON_RINGLIGHT_ALIGNED_WORD_TRANSITIONS.tsv", [
            "word_offset", "source_u32_hex", "target_u32_hex", "source_float32", "target_float32",
            "float_status", "transition_id", "slot_count", "slots", "uniform_across_slots", "review_status",
        ], canonical_rows)
        write_tsv(output_dir / "COMMON_RINGLIGHT_SLOT_ALIGNED_WORDS.tsv", [
            "character_slot", "normalized_path", "member_key", "member_name", "word_offset",
            "source_u32_hex", "target_u32_hex", "source_float32", "target_float32", "float_status",
            "transition_id", "review_status",
        ], slot_word_rows)
        write_tsv(output_dir / "RINGLIGHT_PARENT_CONTAINER_CONTROLS.tsv", [
            "normalized_path", "member_key", "member_name", "extension", "source_size", "target_size",
            "classification", "control_scope", "changed_word_rows", "matched_common_transition_rows", "review_status",
        ], control_rows)
        write_tsv(output_dir / "RINGLIGHT_CONTROL_TRANSITION_MATCHES.tsv", [
            "normalized_path", "member_key", "member_name", "control_scope", "control_word_offset",
            "common_word_offset", "source_u32_hex", "target_u32_hex", "source_float32", "target_float32",
            "float_status", "transition_id", "review_status",
        ], control_match_rows)
        write_tsv(output_dir / "RINGLIGHT_EFFECT_CONTAINER_EXACT_REFERENCES.tsv", [
            "normalized_path", "side", "referencing_member_key", "referencing_member_name", "referenced_slot",
            "token_form", "encoding", "token_sha256", "hit_count", "first_offsets", "self_reference", "binding_status",
        ], container_reference_rows)
        write_tsv(output_dir / "RINGLIGHT_TRANSFORMATION_EVENT_EXACT_REFERENCES.tsv", [
            "normalized_path", "family_id", "family_name", "event_slot", "event_classification", "side",
            "referenced_slot", "token_form", "encoding", "token_sha256", "hit_count", "first_offsets", "binding_status",
        ], event_reference_rows)
        write_tsv(output_dir / "RINGLIGHT_CONTROL_CALLSITE_SKIPPED.tsv", [
            "scope", "normalized_path", "member_key", "side", "reason",
        ], skipped)
        summary = {
            "type": "br_quartet_restoration_reflector_ringlight_control_callsite_evidence_summary",
            "format_version": 1,
            "tool_version": TOOL_VERSION,
            "source_stage80_tool_version": summary80.get("tool_version"),
            "source_stage79_tool_version": summary79.get("tool_version"),
            "source_stage78_tool_version": summary78.get("tool_version"),
            "status": status,
            "common_ringlight_member_rows": len(common_scope),
            "common_ringlight_aligned_word_rows": len(canonical_rows),
            "common_ringlight_slot_word_rows": len(slot_word_rows),
            "common_ringlight_uniform_aligned_word_profile": True,
            "parent_container_rows": len(containers),
            "control_member_rows": len(control_rows),
            "control_transition_match_rows": len(control_match_rows),
            "neutral_control_transition_match_rows": len(neutral_matches),
            "named_light_control_transition_match_rows": len(named_light_matches),
            "container_exact_reference_rows": len(container_reference_rows),
            "container_nonself_exact_reference_rows": len(nonself_container_refs),
            "transformation_event_rows_scanned": len(event_pairs),
            "transformation_event_exact_reference_rows": len(event_reference_rows),
            "exact_name_callsite_binding_resolved": exact_callsite_resolved,
            "heroine_name_bindings_resolved": 0,
            "brightness_semantics_confirmed": False,
            "prototype_candidate_rows": 0,
            "skipped_rows": len(skipped),
            "parameters": {
                "maximum_earc_bytes": maximum_earc_bytes,
                "word_width_bytes": 4,
                "word_endianness": "little",
                "reference_encodings": ["ascii", "utf16le"],
                "reference_forms": ["full_name", "stem", "full_name_lower", "stem_lower"],
                "control_scope": "all_other_G1E_G1EM_members_in_the_four_parent_containers",
            },
            "policy": {
                "installed_game_modified": False,
                "render_payload_written": False,
                "event_payload_written": False,
                "global_bloom_hdr_gamma_or_exposure_restore_attempted": False,
                "pak_repacked": False,
                "core_registry_modified": False,
                "profile_activated": False,
                "runtime_validation_inferred": False,
                "censorship_semantics_inferred": False,
                "heroine_names_inferred_from_slot_numbers": False,
                "canary_track_modified": False,
                "full_proprietary_payloads_exported": False,
            },
            "next_action": next_action,
        }
        (output_dir / "SUMMARY.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        archive_path = None
        if create_archive:
            archive_path = reports / REPORT_NAME
            make_archive(output_dir, archive_path)
        progress("completed")
        return output_dir, archive_path, summary


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", required=True, type=Path)
    parser.add_argument("--workspace-root", type=Path)
    parser.add_argument("--report-root", type=Path)
    parser.add_argument("--effect-rules-file", type=Path)
    parser.add_argument("--maximum-earc-bytes", type=int, default=512 * 1024 * 1024)
    parser.add_argument("--no-report-archive", action="store_true")
    args = parser.parse_args(argv)
    try:
        output, archive, summary = build_report(
            args.project_root,
            create_archive=not args.no_report_archive,
            workspace_root=args.workspace_root,
            report_root=args.report_root,
            rules_file=args.effect_rules_file,
            maximum_earc_bytes=args.maximum_earc_bytes,
        )
        print(f"Report directory: {output}")
        print(f"Common aligned words: {summary['common_ringlight_aligned_word_rows']}; neutral matches: {summary['neutral_control_transition_match_rows']}")
        if archive:
            print(f"Report: {archive}")
        return 0
    except Stage81Error as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
