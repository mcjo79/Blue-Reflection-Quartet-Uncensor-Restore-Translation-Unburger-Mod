#!/usr/bin/env python3
"""Audit the single changed Yuzuki transformation EBD and its effect bindings.

Stage 76 found no direct Yuzu+transformation+brightness metadata row, but it
localized one unique changed event in the Yuzuki Reflector family:
`event/skill/skill_party_yuzuki_rfl_50.ebd`.  Stage 77 reopens the real
Original and Quartet payloads, compares schema tokens, tagged atoms, raw byte
ranges and aligned post-header words, and uses the identical Raimu `_rfl_50`
event plus the remaining Yuzuki `_rfl_*` family as controls.  Strict technical
identifiers may be cross-referenced with stage-76 effect-member locators, but
localized text is never exported.  No payload is written.
"""
from __future__ import annotations

import argparse
import csv
import difflib
import hashlib
import importlib
import json
import os
import re
import shutil
import struct
import subprocess
import sys
import tempfile
from collections import Counter
from pathlib import Path, PurePosixPath
from typing import Any, Iterable, Mapping, Sequence

TOOL_VERSION = "0.0.89"
REPORT_NAME = "BR_quartet_restoration_yuzuki_rfl50_event_binding_evidence.tar.zst"
REPORT_DIR = "yuzuki_rfl50_event_binding_evidence"
STAGE76_DIR = "transformation_brightness_evidence"
STAGE76_ARCHIVE = "BR_quartet_restoration_transformation_brightness_evidence.tar.zst"
TARGET_PATH = "event/skill/skill_party_yuzuki_rfl_50.ebd"
CONTROL_PATH = "event/skill/skill_party_raimu_rfl_50.ebd"
YUZUKI_RE = re.compile(r"^event/skill/skill_party_yuzuki_rfl_(\d+)\.ebd$", re.IGNORECASE)
PC_TOKEN_RE = re.compile(rb"(?<![A-Za-z0-9_])pc\d{2}[A-Za-z0-9_]*", re.IGNORECASE)


class YuzukiRfl50BindingError(RuntimeError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise YuzukiRfl50BindingError(message)


def folded(value: Any) -> str:
    return str(value or "").strip().casefold()


def parse_int(value: Any, default: int = 0) -> int:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return default


def normalize_path(value: Any) -> str:
    path = str(value or "").replace("\\", "/").strip()
    while path.startswith("./"):
        path = path[2:]
    return path.casefold()


def load_json(path: Path) -> dict[str, Any]:
    require(path.is_file(), f"missing required JSON: {path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise YuzukiRfl50BindingError(f"cannot read JSON {path}: {exc}") from exc
    require(isinstance(value, dict), f"JSON root must be an object: {path}")
    return value


def read_tsv(path: Path, *, required: bool = True) -> list[dict[str, str]]:
    if not path.is_file():
        if required:
            raise YuzukiRfl50BindingError(f"missing required TSV: {path}")
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


def locate_stage76(report_root: Path, temporary: Path) -> Path:
    direct = report_root / STAGE76_DIR
    if direct.is_dir():
        return direct
    return extract_archive(report_root / STAGE76_ARCHIVE, temporary / "stage76")


def load_restoration_tool(project_root: Path) -> Any:
    tool_root = project_root / "Blue_Reflection_Text_Tool"
    tool = tool_root / "br_restoration_tool.py"
    require(tool.is_file(), f"missing restoration tool: {tool}")
    sys.path.insert(0, str(tool_root))
    try:
        return importlib.import_module("br_restoration_tool")
    finally:
        try:
            sys.path.remove(str(tool_root))
        except ValueError:
            pass


def make_report_archive(source_dir: Path, output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(output.name + ".tmp")
    temporary.unlink(missing_ok=True)
    done = subprocess.run(["tar", "--zstd", "-cf", str(temporary), "-C", str(source_dir.parent), source_dir.name], text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    require(done.returncode == 0, f"cannot create report archive: {done.stderr.strip()}")
    os.replace(temporary, output)


def byte_difference_count(left: bytes, right: bytes) -> int:
    overlap = min(len(left), len(right))
    return sum(a != b for a, b in zip(left[:overlap], right[:overlap])) + abs(len(left) - len(right))


def sequence_sha(values: Sequence[int]) -> str:
    return hashlib.sha256("|".join(f"{value:08x}" for value in values).encode("ascii")).hexdigest()


def find_word_sequence(haystack: Sequence[int], needle: Sequence[int]) -> int:
    if not needle:
        return 0
    if len(needle) > len(haystack):
        return 0
    return sum(1 for index in range(0, len(haystack) - len(needle) + 1) if list(haystack[index:index + len(needle)]) == list(needle))


def normalized_token(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", value.casefold()).strip("_")


def validate_stage76(root: Path) -> tuple[dict[str, Any], list[dict[str, str]], list[dict[str, str]]]:
    summary = load_json(root / "SUMMARY.json")
    require(summary.get("type") == "br_quartet_restoration_transformation_brightness_evidence_summary", "stage-76 report has unexpected type")
    require(summary.get("tool_version") == "0.0.88", "stage-76 report must be the 0.0.88 report")
    require(parse_int(summary.get("registry_profile_rows"), -1) == 15, "stage-76 report must validate 15 profiles")
    require(parse_int(summary.get("direct_yuzu_transformation_brightness_rows"), -1) == 0, "stage-76 unexpectedly contains a direct Yuzu brightness binding")
    require(parse_int(summary.get("yuzu_or_yuzuki_rows"), -1) >= 30, "stage-76 Yuzu locator corpus is unexpectedly incomplete")

    paths = read_tsv(root / "TRANSFORMATION_BRIGHTNESS_ASSET_PATHS.tsv")
    review = read_tsv(root / "TRANSFORMATION_BRIGHTNESS_FOCUSED_REVIEW.tsv")
    yuzuki_family = [row for row in paths if YUZUKI_RE.match(normalize_path(row.get("normalized_path")))]
    require(len(yuzuki_family) >= 30, "stage-76 must contain the Yuzuki RFL event family")
    changed = [row for row in yuzuki_family if folded(row.get("classification")) == "changed"]
    require(len(changed) == 1 and normalize_path(changed[0].get("normalized_path")) == TARGET_PATH, "stage-76 must localize exactly one changed Yuzuki RFL event: rfl_50")
    require(parse_int(changed[0].get("source_size"), -1) == 1411 and parse_int(changed[0].get("target_size"), -1) == 1423, "stage-76 Yuzuki rfl_50 sizes changed unexpectedly")
    other = [row for row in yuzuki_family if normalize_path(row.get("normalized_path")) != TARGET_PATH]
    require(all(folded(row.get("classification")) == "identical" for row in other), "another Yuzuki RFL event is no longer identical")
    controls = [row for row in paths if normalize_path(row.get("normalized_path")) == CONTROL_PATH]
    require(len(controls) == 1 and folded(controls[0].get("classification")) == "identical", "Raimu rfl_50 control must remain identical")
    return summary, paths, review


def load_event_entry(br: Any, report_root: Path) -> dict[str, dict[str, Any]]:
    reports = br.load_report_jsons(report_root, "differences")
    event_report = next((report for report in reports if str(report.get("source_archive_group", "")) == "br1_events"), None)
    require(event_report is not None, "missing br1_events corrected difference report")
    return {
        normalize_path(row.get("normalized_path")): row
        for row in event_report.get("entries", [])
        if row.get("scope_status") == "in_scope" and row.get("source") and row.get("target")
    }


def load_pair(br: Any, workspace_root: Path, entry: Mapping[str, Any]) -> tuple[bytes, bytes, dict[str, Any], dict[str, Any]]:
    source_ref = dict(entry.get("source") or {})
    target_ref = dict(entry.get("target") or {})
    source_path = br.inventory_workspace_file(workspace_root, "source", "br1_events", str(source_ref.get("archive", "")), str(source_ref.get("path", "")))
    target_path = br.inventory_workspace_file(workspace_root, "target", "br1_events", str(target_ref.get("archive", "")), str(target_ref.get("path", "")))
    require(source_path.is_file() and target_path.is_file(), f"missing event workspace payload: {entry.get('normalized_path')}")
    source = source_path.read_bytes()
    target = target_path.read_bytes()
    if source_ref.get("sha256"):
        require(hashlib.sha256(source).hexdigest() == str(source_ref.get("sha256")), f"source hash mismatch: {entry.get('normalized_path')}")
    if target_ref.get("sha256"):
        require(hashlib.sha256(target).hexdigest() == str(target_ref.get("sha256")), f"target hash mismatch: {entry.get('normalized_path')}")
    return source, target, source_ref, target_ref


def raw_delta_rows(br: Any, source: bytes, target: bytes) -> list[dict[str, Any]]:
    matcher = difflib.SequenceMatcher(a=source, b=target, autojunk=False)
    rows: list[dict[str, Any]] = []
    for index, (tag, i1, i2, j1, j2) in enumerate(matcher.get_opcodes()):
        if tag == "equal":
            continue
        source_slice = source[i1:i2]
        target_slice = target[j1:j2]
        classification = "opaque_binary_delta"
        ascii_ratio = 0.0
        utf16_ratio = 0.0
        try:
            classification, _changed, ascii_ratio, utf16_ratio = br.classify_event_delta_region(source_slice, target_slice)
        except Exception:
            pass
        rows.append({
            "delta_index": index,
            "sequence_tag": tag,
            "source_offset": i1,
            "source_end": i2,
            "target_offset": j1,
            "target_end": j2,
            "source_size": len(source_slice),
            "target_size": len(target_slice),
            "source_sha256": hashlib.sha256(source_slice).hexdigest(),
            "target_sha256": hashlib.sha256(target_slice).hexdigest(),
            "ascii_printable_ratio": round(float(ascii_ratio), 6),
            "utf16_ascii_ratio": round(float(utf16_ratio), 6),
            "classification": classification,
            "review_status": "raw_event_delta_metadata_not_brightness_or_binding_proof",
        })
    return rows


def analyze_pair(br: Any, normalized_path: str, source: bytes, target: bytes) -> dict[str, Any]:
    source_header = br.parse_ebd_header_schema(source)
    target_header = br.parse_ebd_header_schema(target)
    require(source_header.get("classification") == "observed_ebd_name_description_header", f"source EBD header not recognized: {normalized_path}")
    require(target_header.get("classification") == "observed_ebd_name_description_header", f"target EBD header not recognized: {normalized_path}")
    source_tokens = br.scan_length_prefixed_text(source)
    target_tokens = br.scan_length_prefixed_text(target)
    token_deltas = br.compare_event_schema_tokens(source_tokens, target_tokens)
    source_ids = br.extract_event_technical_identifiers(source)
    target_ids = br.extract_event_technical_identifiers(target)
    source_id_set = {(str(row.get("identifier_kind", "")), str(row.get("technical_identifier", ""))) for row in source_ids}
    target_id_set = {(str(row.get("identifier_kind", "")), str(row.get("technical_identifier", ""))) for row in target_ids}
    source_profile = br.profile_ebd_post_header_words(source, int(source_header["header_end"]), maximum_words=max(1, len(source) // 4 + 8))
    target_profile = br.profile_ebd_post_header_words(target, int(target_header["header_end"]), maximum_words=max(1, len(target) // 4 + 8))
    tag_deltas = br.compare_ebd_tag_atoms(source_profile["atoms"], target_profile["atoms"])
    word_matcher = difflib.SequenceMatcher(a=list(source_profile["words"]), b=list(target_profile["words"]), autojunk=False)
    word_deltas: list[dict[str, Any]] = []
    for delta_index, (tag, i1, i2, j1, j2) in enumerate(word_matcher.get_opcodes()):
        if tag == "equal":
            continue
        source_values = list(source_profile["words"])[i1:i2]
        target_values = list(target_profile["words"])[j1:j2]
        word_deltas.append({
            "normalized_path": normalized_path,
            "delta_index": delta_index,
            "sequence_tag": tag,
            "source_word_start": i1,
            "source_word_end": i2,
            "target_word_start": j1,
            "target_word_end": j2,
            "source_word_count": len(source_values),
            "target_word_count": len(target_values),
            "source_values_hex": ";".join(f"0x{value:08x}" for value in source_values[:32]),
            "target_values_hex": ";".join(f"0x{value:08x}" for value in target_values[:32]),
            "source_sequence_sha256": sequence_sha(source_values),
            "target_sequence_sha256": sequence_sha(target_values),
            "review_status": "word_delta_not_opcode_effect_binding_or_censorship_proof",
            "_source_values": source_values,
            "_target_values": target_values,
        })
    return {
        "path": normalized_path,
        "source": source,
        "target": target,
        "source_header": source_header,
        "target_header": target_header,
        "source_tokens": source_tokens,
        "target_tokens": target_tokens,
        "token_deltas": token_deltas,
        "source_ids": source_ids,
        "target_ids": target_ids,
        "source_only_ids": sorted(source_id_set - target_id_set),
        "target_only_ids": sorted(target_id_set - source_id_set),
        "shared_ids": sorted(source_id_set & target_id_set),
        "source_profile": source_profile,
        "target_profile": target_profile,
        "tag_deltas": tag_deltas,
        "word_deltas": word_deltas,
        "raw_deltas": raw_delta_rows(br, source, target),
    }


def technical_identifier_rows(analysis: Mapping[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    status_by_key: dict[tuple[str, str], str] = {}
    for key in analysis["source_only_ids"]:
        status_by_key[key] = "source_only"
    for key in analysis["target_only_ids"]:
        status_by_key[key] = "target_only"
    for key in analysis["shared_ids"]:
        status_by_key[key] = "shared"
    source_map = {(str(row.get("identifier_kind")), str(row.get("technical_identifier"))): row for row in analysis["source_ids"]}
    target_map = {(str(row.get("identifier_kind")), str(row.get("technical_identifier"))): row for row in analysis["target_ids"]}
    for key in sorted(status_by_key, key=lambda item: (item[0], item[1].casefold())):
        source_row = source_map.get(key, {})
        target_row = target_map.get(key, {})
        rows.append({
            "normalized_path": analysis["path"],
            "presence": status_by_key[key],
            "identifier_kind": key[0],
            "technical_identifier": key[1],
            "source_hit_count": source_row.get("hit_count", 0),
            "target_hit_count": target_row.get("hit_count", 0),
            "source_first_offsets": source_row.get("first_offsets", ""),
            "target_first_offsets": target_row.get("first_offsets", ""),
            "focused_surface_term": source_row.get("focused_surface_term") or target_row.get("focused_surface_term") or False,
            "review_status": "technical_identifier_not_effect_binding_or_brightness_proof",
        })
    for side, payload in (("source", analysis["source"]), ("target", analysis["target"])):
        grouped = Counter(match.group(0).decode("ascii", errors="ignore") for match in PC_TOKEN_RE.finditer(payload))
        for token, count in sorted(grouped.items(), key=lambda item: item[0].casefold()):
            rows.append({
                "normalized_path": analysis["path"],
                "presence": side + "_raw_pc_token",
                "identifier_kind": "character_slot_identifier",
                "technical_identifier": token,
                "source_hit_count": count if side == "source" else 0,
                "target_hit_count": count if side == "target" else 0,
                "source_first_offsets": "",
                "target_first_offsets": "",
                "focused_surface_term": True,
                "review_status": "raw_ascii_character_slot_locator_not_binding_proof",
            })
    return rows


def binding_candidates(analysis: Mapping[str, Any], stage76_review: Sequence[Mapping[str, str]]) -> list[dict[str, Any]]:
    target_only = [identifier for _kind, identifier in analysis["target_only_ids"]]
    all_target = [str(row.get("technical_identifier", "")) for row in analysis["target_ids"] if row.get("technical_identifier")]
    raw_pc_tokens = {match.group(0).decode("ascii", errors="ignore").casefold() for match in PC_TOKEN_RE.finditer(analysis["target"])}
    raw_pc = sorted(raw_pc_tokens | {match.group(0).casefold() for token in raw_pc_tokens for match in re.finditer(r"pc\d{2}", token, re.IGNORECASE)})
    rows: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    for evidence in stage76_review:
        member = str(evidence.get("member_name", ""))
        path = str(evidence.get("normalized_path", ""))
        if not member and not path:
            continue
        if evidence.get("lead_classification") not in {
            "transformation_body_brightness_lead", "transformation_brightness_lead", "generic_brightness_control"
        }:
            continue
        joined = normalized_token(path + " " + member)
        bases: list[tuple[str, str]] = []
        for identifier in target_only:
            token = normalized_token(identifier)
            if token and (token in joined or joined.endswith(token)):
                bases.append(("target_only_technical_identifier_match", identifier))
        for identifier in all_target:
            token = normalized_token(identifier)
            if token and len(token) >= 5 and token in joined:
                bases.append(("shared_technical_identifier_match", identifier))
        for pc in raw_pc:
            if pc and pc in joined:
                bases.append(("character_slot_family_match", pc))
        for basis, matched in bases:
            key = (path.casefold(), member.casefold(), basis + "|" + matched.casefold())
            if key in seen:
                continue
            seen.add(key)
            rows.append({
                "event_path": analysis["path"],
                "evidence_source": evidence.get("evidence_source", ""),
                "effect_path": path,
                "effect_member_name": member,
                "effect_domain": evidence.get("domain", ""),
                "effect_priority": evidence.get("priority", ""),
                "lead_classification": evidence.get("lead_classification", ""),
                "binding_basis": basis,
                "matched_identifier": matched,
                "review_status": "candidate_cross_reference_only_exact_runtime_or_numeric_binding_not_confirmed",
            })
    return rows


def build_report(project_root: Path, *, create_archive: bool = True) -> tuple[Path, Path | None, dict[str, Any]]:
    project_root = project_root.expanduser().resolve()
    report_root = project_root / ".local/reports/quartet_restoration"
    workspace_root = project_root / ".local/build/quartet_restoration"
    require(report_root.is_dir(), f"missing restoration report root: {report_root}")
    require(workspace_root.is_dir(), f"missing restoration workspace: {workspace_root}")
    br = load_restoration_tool(project_root)

    with tempfile.TemporaryDirectory(prefix="br-yuzuki-rfl50-") as temporary_name:
        stage76_root = locate_stage76(report_root, Path(temporary_name))
        stage76_summary, _stage76_paths, stage76_review = validate_stage76(stage76_root)
        entries = load_event_entry(br, report_root)
        require(TARGET_PATH in entries, "corrected differences missing Yuzuki rfl_50")
        require(CONTROL_PATH in entries, "corrected differences missing Raimu rfl_50 control")

        family_paths = sorted(path for path in entries if YUZUKI_RE.match(path))
        require(len(family_paths) >= 30, "corrected differences missing the Yuzuki RFL family")
        target_source, target_target, target_source_ref, target_target_ref = load_pair(br, workspace_root, entries[TARGET_PATH])
        control_source, control_target, _control_source_ref, _control_target_ref = load_pair(br, workspace_root, entries[CONTROL_PATH])
        require(control_source == control_target, "Raimu rfl_50 control is no longer byte-identical")
        target_analysis = analyze_pair(br, TARGET_PATH, target_source, target_target)
        control_analysis = analyze_pair(br, CONTROL_PATH, control_source, control_target)

        family_analyses: dict[str, dict[str, Any]] = {}
        for path in family_paths:
            source, target, _source_ref, _target_ref = load_pair(br, workspace_root, entries[path])
            family_analyses[path] = analyze_pair(br, path, source, target)
        changed_family = [path for path, analysis in family_analyses.items() if analysis["source"] != analysis["target"]]
        require(changed_family == [TARGET_PATH], f"expected only Yuzuki rfl_50 to differ, found {changed_family}")

        other_source_words = [analysis["source_profile"]["words"] for path, analysis in family_analyses.items() if path != TARGET_PATH]
        other_target_words = [analysis["target_profile"]["words"] for path, analysis in family_analyses.items() if path != TARGET_PATH]
        control_source_words = control_analysis["source_profile"]["words"]
        control_target_words = control_analysis["target_profile"]["words"]
        word_rows: list[dict[str, Any]] = []
        for row in target_analysis["word_deltas"]:
            source_values = list(row.pop("_source_values"))
            target_values = list(row.pop("_target_values"))
            row.update({
                "source_sequence_in_raimu_source": find_word_sequence(control_source_words, source_values),
                "target_sequence_in_raimu_target": find_word_sequence(control_target_words, target_values),
                "source_sequence_yuzuki_other_event_count": sum(find_word_sequence(words, source_values) > 0 for words in other_source_words),
                "target_sequence_yuzuki_other_event_count": sum(find_word_sequence(words, target_values) > 0 for words in other_target_words),
                "scene_local_target_sequence": bool(target_values) and find_word_sequence(control_target_words, target_values) == 0 and sum(find_word_sequence(words, target_values) > 0 for words in other_target_words) == 0,
            })
            word_rows.append(row)

        identifier_rows = technical_identifier_rows(target_analysis)
        binding_rows = binding_candidates(target_analysis, stage76_review)
        token_rows = []
        for row in target_analysis["token_deltas"]:
            token_rows.append({"normalized_path": TARGET_PATH, **row})
        tag_rows = []
        for index, row in enumerate(target_analysis["tag_deltas"]):
            tag_rows.append({
                "normalized_path": TARGET_PATH,
                "delta_index": index,
                **row,
                "shape_id": br.event_residual_delta_shape_id(row),
            })

        control_rows = [{
            "target_event_path": TARGET_PATH,
            "same_slot_control_path": CONTROL_PATH,
            "yuzuki_source_size": len(target_source),
            "yuzuki_target_size": len(target_target),
            "yuzuki_size_delta": len(target_target) - len(target_source),
            "yuzuki_changed_bytes": byte_difference_count(target_source, target_target),
            "yuzuki_raw_delta_rows": len(target_analysis["raw_deltas"]),
            "yuzuki_schema_token_delta_rows": len(target_analysis["token_deltas"]),
            "yuzuki_tag_delta_rows": len(target_analysis["tag_deltas"]),
            "yuzuki_word_delta_rows": len(word_rows),
            "raimu_control_source_size": len(control_source),
            "raimu_control_target_size": len(control_target),
            "raimu_control_identical": control_source == control_target,
            "other_yuzuki_rfl_event_count": len(family_paths) - 1,
            "other_yuzuki_rfl_changed_count": len(changed_family) - 1,
            "classification": "single_changed_yuzuki_rfl50_event_with_identical_same_slot_and_family_controls",
            "review_status": "event_localization_strong_binding_and_brightness_semantics_unresolved",
        }]

        output = report_root / REPORT_DIR
        if output.exists():
            shutil.rmtree(output)
        output.mkdir(parents=True)
        write_tsv(output / "YUZUKI_RFL50_CONTROL_COMPARISON.tsv", list(control_rows[0]), control_rows)
        write_tsv(output / "YUZUKI_RFL50_RAW_DELTAS.tsv", [
            "delta_index", "sequence_tag", "source_offset", "source_end", "target_offset", "target_end", "source_size", "target_size", "source_sha256", "target_sha256", "ascii_printable_ratio", "utf16_ascii_ratio", "classification", "review_status"
        ], target_analysis["raw_deltas"])
        write_tsv(output / "YUZUKI_RFL50_SCHEMA_TOKEN_DELTAS.tsv", [
            "normalized_path", "sequence_tag", "source_token_start", "source_token_end", "target_token_start", "target_token_end", "source_token_count", "target_token_count", "source_technical_identifiers", "target_technical_identifiers", "source_localized_token_count", "target_localized_token_count", "source_token_sequence_sha256", "target_token_sequence_sha256", "classification", "review_status"
        ], token_rows)
        write_tsv(output / "YUZUKI_RFL50_TAG_DELTAS.tsv", [
            "normalized_path", "delta_index", "shape_id", "sequence_tag", "source_atom_start", "source_atom_end", "target_atom_start", "target_atom_end", "source_atom_count", "target_atom_count", "source_first_word_index", "target_first_word_index", "source_tag_values", "target_tag_values", "source_atom_sequence_sha256", "target_atom_sequence_sha256", "classification", "review_status"
        ], tag_rows)
        write_tsv(output / "YUZUKI_RFL50_WORD_DELTAS.tsv", [
            "normalized_path", "delta_index", "sequence_tag", "source_word_start", "source_word_end", "target_word_start", "target_word_end", "source_word_count", "target_word_count", "source_values_hex", "target_values_hex", "source_sequence_sha256", "target_sequence_sha256", "source_sequence_in_raimu_source", "target_sequence_in_raimu_target", "source_sequence_yuzuki_other_event_count", "target_sequence_yuzuki_other_event_count", "scene_local_target_sequence", "review_status"
        ], word_rows)
        write_tsv(output / "YUZUKI_RFL50_TECHNICAL_IDENTIFIERS.tsv", [
            "normalized_path", "presence", "identifier_kind", "technical_identifier", "source_hit_count", "target_hit_count", "source_first_offsets", "target_first_offsets", "focused_surface_term", "review_status"
        ], identifier_rows)
        write_tsv(output / "YUZUKI_RFL50_EFFECT_BINDING_CANDIDATES.tsv", [
            "event_path", "evidence_source", "effect_path", "effect_member_name", "effect_domain", "effect_priority", "lead_classification", "binding_basis", "matched_identifier", "review_status"
        ], binding_rows)

        scene_local_word_rows = sum(str(row.get("scene_local_target_sequence")).casefold() == "true" for row in word_rows)
        target_only_id_rows = sum(row.get("presence") == "target_only" for row in identifier_rows)
        if binding_rows:
            result_classification = "scene_specific_effect_identifier_cross_references_located_runtime_and_exact_binding_still_required"
        elif target_only_id_rows or scene_local_word_rows or tag_rows:
            result_classification = "single_changed_yuzuki_rfl50_event_delta_confirmed_numeric_or_indexed_effect_binding_unresolved"
        else:
            result_classification = "single_changed_yuzuki_rfl50_event_confirmed_no_binding_identifier_localized"
        summary = {
            "type": "br_quartet_restoration_yuzuki_rfl50_event_binding_evidence_summary",
            "format_version": 1,
            "tool_version": TOOL_VERSION,
            "source_transformation_brightness_tool_version": stage76_summary.get("tool_version"),
            "status": result_classification,
            "target_event_path": TARGET_PATH,
            "same_slot_control_path": CONTROL_PATH,
            "yuzuki_rfl_family_rows": len(family_paths),
            "changed_yuzuki_rfl_rows": len(changed_family),
            "target_source_size": len(target_source),
            "target_quartet_size": len(target_target),
            "target_size_delta": len(target_target) - len(target_source),
            "target_changed_bytes": byte_difference_count(target_source, target_target),
            "raw_delta_rows": len(target_analysis["raw_deltas"]),
            "schema_token_delta_rows": len(token_rows),
            "tag_delta_rows": len(tag_rows),
            "word_delta_rows": len(word_rows),
            "scene_local_target_word_delta_rows": scene_local_word_rows,
            "technical_identifier_rows": len(identifier_rows),
            "target_only_technical_identifier_rows": target_only_id_rows,
            "effect_binding_candidate_rows": len(binding_rows),
            "raimu_rfl50_identical": control_source == control_target,
            "other_yuzuki_rfl_changed_rows": len(changed_family) - 1,
            "source_sha256": hashlib.sha256(target_source).hexdigest(),
            "target_sha256": hashlib.sha256(target_target).hexdigest(),
            "source_inventory_sha256": target_source_ref.get("sha256", ""),
            "target_inventory_sha256": target_target_ref.get("sha256", ""),
            "policy": {
                "installed_game_modified": False,
                "event_payload_written": False,
                "shader_or_effect_payload_written": False,
                "global_bloom_or_exposure_restore_attempted": False,
                "pak_repacked": False,
                "core_registry_modified": False,
                "profile_activated": False,
                "localized_event_text_exported": False,
                "technical_identifiers_exported": True,
                "numeric_word_values_exported_as_binding_proof": False,
                "runtime_validation_inferred": False,
                "censorship_semantics_inferred": False,
                "user_report_treated_as_confirmed_fact": False,
                "canary_track_modified": False,
            },
            "next_action": (
                "Upload this report. If Yuzuki rfl_50 exposes a scene-local target word, tag delta or technical identifier, perform a separate read-only numeric/effect-member occurrence audit against the narrowed effect families. Do not restore global bloom, gamma, HDR or exposure without an exact event-to-member binding and reversible local candidate."
            ),
        }
        atomic_json(output / "SUMMARY.json", summary)
        archive = report_root / REPORT_NAME if create_archive else None
        if archive:
            archive.unlink(missing_ok=True)
            make_report_archive(output, archive)
        return output, archive, summary


def main() -> int:
    parser = argparse.ArgumentParser(description="Collect read-only binding evidence for the single changed Yuzuki rfl_50 event")
    parser.add_argument("--project-root", type=Path, required=True)
    parser.add_argument("--no-report-archive", action="store_true")
    args = parser.parse_args()
    output, archive, summary = build_report(args.project_root, create_archive=not args.no_report_archive)
    print(f"Yuzuki RFL family rows: {summary['yuzuki_rfl_family_rows']}")
    print(f"Changed Yuzuki RFL rows: {summary['changed_yuzuki_rfl_rows']}")
    print(f"Yuzuki rfl_50 changed bytes: {summary['target_changed_bytes']}")
    print(f"Scene-local target word deltas: {summary['scene_local_target_word_delta_rows']}")
    print(f"Target-only technical identifiers: {summary['target_only_technical_identifier_rows']}")
    print(f"Effect binding candidates: {summary['effect_binding_candidate_rows']}")
    print(f"Report directory: {output}")
    if archive:
        print(f"Report: {archive}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except YuzukiRfl50BindingError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
