#!/usr/bin/env python3
"""Read-only controlled force-point audit for legacy DLC costume visibility.

The audit intentionally stops looking for a platform entitlement owner. It
compares the original BLUE REFLECTION costume label blocks with Quartet's
preserved string-number sequence, the PCxx_DLC_BKN character records and the
accepted generation-8 charabase candidate. Its purpose is to decide whether a
strictly allowlisted, data-only str_costume restoration is the smallest safe
visibility experiment.

No game, candidate, manifest, save, executable, core, Translation, Restoration
or Git file is modified. No raw PAK member is exported.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import sys
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

TOOL_VERSION = "0.0.61"
FORMAT_VERSION = 1
EXPECTED_WORKSTREAM_VERSION = "0.0.61"
EXPECTED_GENERATION = 8
EXPECTED_MEMBERS = [f"costume_pc{i:02d}_bkn" for i in range(8)]
EXPECTED_TARGETS = {"Data/PACK10_02.PAK", "Data/PACK12.PAK"}
VISIBLE_LABELS = (
    "Hoshinomiya Uniform",
    "School Swimsuit",
    "Gym Uniform",
    "Cami",
)
BKN_LABEL_RE = re.compile(r"(?:^|\b)bikini(?:\b|$)|ビキニ", re.I)
PLACEHOLDER_VALUES = {"", "-", "－", "—", "–"}
BKN_DRY_TAGS = tuple(f"PC{i:02d}_DLC_BKN" for i in range(15))
BKN_WET_TAGS = tuple(f"PC{i:02d}_DLC_BKN_W" for i in range(15))
SELECTED_RECORD_FILES = (
    "chara/chara.xml",
    "chara/chara_no.xml",
    "chara/charabase.xml",
)
FORBIDDEN_OUTPUT_SUFFIXES = {
    ".pak", ".exe", ".dll", ".ebm", ".ebd", ".g1m", ".g1t", ".g1a",
    ".g1e", ".g1s", ".elixir", ".gz", ".swg", ".dds", ".kscl", ".kslt",
}


class ForcePointError(RuntimeError):
    pass


@dataclass(frozen=True)
class XmlRecord:
    side: str
    relative_path: str
    index: int
    element: str
    attrs: dict[str, str]
    text: str
    sha256: str


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def scalar(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (dict, list, tuple, set)):
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return str(value)


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def write_tsv(path: Path, rows: Sequence[Mapping[str, Any]], fields: Sequence[str] | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if fields is None:
        ordered: list[str] = []
        for row in rows:
            for key in row:
                if key not in ordered:
                    ordered.append(key)
        fields = ordered or ["status"]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(fields), delimiter="\t", lineterminator="\n")
        writer.writeheader()
        if rows:
            for row in rows:
                writer.writerow({field: scalar(row.get(field, "")) for field in fields})
        else:
            writer.writerow({fields[0]: "no_rows"})


def require_regular(path: Path, label: str) -> None:
    if not path.is_file() or path.is_symlink():
        raise ForcePointError(f"{label} is not a regular file: {path}")


def decode_xml(raw: bytes, label: str) -> str:
    payload = raw
    candidates: list[str] = []
    utf16_bom = raw.startswith((b"\xff\xfe", b"\xfe\xff"))
    if raw.startswith(b"\xef\xbb\xbf"):
        payload = raw[3:]
        candidates.append("utf-8")
    elif utf16_bom:
        candidates.append("utf-16")
    declaration = re.search(br"encoding=[\"']([^\"']+)", payload[:512], re.I)
    declared = declaration.group(1).decode("ascii", "replace") if declaration else ""
    aliases = {
        "shift-jis": "cp932", "shift_jis": "cp932", "shiftjis": "cp932",
        "sjis": "cp932", "windows-31j": "cp932", "ms932": "cp932",
        "utf-8": "utf-8", "utf8": "utf-8", "utf-16": "utf-16", "utf16": "utf-16",
    }
    if declared:
        candidates.append(aliases.get(declared.casefold(), declared))
    candidates.extend(("cp932", "utf-8"))
    errors: list[str] = []
    for encoding in dict.fromkeys(candidates):
        try:
            source = raw if encoding == "utf-16" and utf16_bom else payload
            return source.decode(encoding)
        except (UnicodeDecodeError, LookupError) as exc:
            errors.append(f"{encoding}: {exc}")
    raise ForcePointError(f"unable to decode XML {label}: {'; '.join(errors)}")


def parse_xml(path: Path, workspace: Path) -> list[XmlRecord]:
    text = decode_xml(path.read_bytes(), str(path))
    text = re.sub(r"<\?xml[^>]*\?>", "", text, count=1, flags=re.I)
    try:
        root = ET.fromstring(text)
    except ET.ParseError as exc:
        raise ForcePointError(f"failed to parse XML {path}: {exc}") from exc
    rel = path.relative_to(workspace).as_posix()
    folded = f"/{rel.casefold()}/"
    side = "original" if "/original/" in folded else "quartet" if "/quartet/" in folded else "unknown"
    rows: list[XmlRecord] = []
    for index, element in enumerate(root.iter()):
        if element is root:
            continue
        attrs = {str(key): str(value) for key, value in element.attrib.items()}
        element_text = (element.text or "").strip()
        canonical = json.dumps(
            {"element": str(element.tag), "attrs": attrs, "text": element_text},
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        rows.append(XmlRecord(
            side=side,
            relative_path=rel,
            index=index,
            element=str(element.tag),
            attrs=attrs,
            text=element_text,
            sha256=sha256_bytes(canonical.encode("utf-8")),
        ))
    return rows


def text_value(record: XmlRecord) -> str:
    for key in ("Text", "text", "String", "string", "Name", "name"):
        if key in record.attrs:
            return record.attrs[key].strip()
    return record.text.strip()


def string_number(record: XmlRecord) -> str:
    for key in ("String_No", "StringNo", "Id", "ID", "No"):
        value = record.attrs.get(key, "").strip()
        if value:
            return value
    return ""


def is_placeholder(value: str) -> bool:
    return value.strip() in PLACEHOLDER_VALUES


def locate_workspace_xml(workspace: Path) -> dict[str, Path]:
    candidates = {
        "original_str_costume": workspace / "original/archives/PACK02_1/saves_en/text/str_costume.xml",
        "quartet_str_costume": workspace / "quartet/archives/PACK12/saves/b1/text_en/str_costume.xml",
        "original_chara": workspace / "original/archives/PACK02_1/saves_en/chara/chara.xml",
        "quartet_chara": workspace / "quartet/archives/PACK12/saves/b1/chara/chara.xml",
        "original_chara_no": workspace / "original/archives/PACK02_1/saves_en/chara/chara_no.xml",
        "quartet_chara_no": workspace / "quartet/archives/PACK12/saves/b1/chara/chara_no.xml",
        "original_charabase": workspace / "original/archives/PACK02_1/saves_en/chara/charabase.xml",
        "quartet_charabase": workspace / "quartet/archives/PACK12/saves/b1/chara/charabase.xml",
    }
    for label, path in candidates.items():
        require_regular(path, label)
    return candidates


def load_records(paths: Mapping[str, Path], workspace: Path) -> dict[str, list[XmlRecord]]:
    return {label: parse_xml(path, workspace) for label, path in paths.items()}


def rows_by_string_number(records: Sequence[XmlRecord]) -> dict[str, XmlRecord]:
    result: dict[str, XmlRecord] = {}
    for record in records:
        number = string_number(record)
        if number:
            result[number] = record
    return result


def bkn_label_block(original_rows: Sequence[XmlRecord], quartet_rows: Sequence[XmlRecord]) -> tuple[list[dict[str, Any]], bool]:
    quartet_by_number = rows_by_string_number(quartet_rows)
    source_hits: list[XmlRecord] = [row for row in original_rows if BKN_LABEL_RE.search(text_value(row))]
    exact_family_block = len(source_hits) == 15
    output: list[dict[str, Any]] = []
    for position, source in enumerate(source_hits):
        number = string_number(source)
        target = quartet_by_number.get(number)
        source_label = text_value(source)
        target_label = text_value(target) if target else ""
        pc_slot = f"PC{position:02d}" if exact_family_block else ""
        output.append({
            "family_position": position,
            "pc_slot": pc_slot,
            "base_tag": f"{pc_slot}_DLC_BKN" if pc_slot else "",
            "string_no": number,
            "source_label": source_label,
            "quartet_label": target_label,
            "quartet_record_present": target is not None,
            "quartet_is_placeholder": target is not None and is_placeholder(target_label),
            "source_record_sha256": source.sha256,
            "quartet_record_sha256": target.sha256 if target else "",
            "raw_record_exported": False,
        })
    return output, exact_family_block


def visible_control_rows(quartet_rows: Sequence[XmlRecord]) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for record in quartet_rows:
        label = text_value(record)
        if label in VISIBLE_LABELS:
            output.append({
                "label": label,
                "string_no": string_number(record),
                "is_placeholder": is_placeholder(label),
                "record_sha256": record.sha256,
                "runtime_visible": True,
                "raw_record_exported": False,
            })
    return output


def all_placeholder_blocks(original_rows: Sequence[XmlRecord], quartet_rows: Sequence[XmlRecord]) -> list[dict[str, Any]]:
    quartet_by_number = rows_by_string_number(quartet_rows)
    grouped: dict[str, list[tuple[XmlRecord, XmlRecord]]] = defaultdict(list)
    for source in original_rows:
        number = string_number(source)
        target = quartet_by_number.get(number)
        source_label = text_value(source)
        target_label = text_value(target) if target else ""
        if source_label and target and is_placeholder(target_label):
            grouped[source_label].append((source, target))
    rows: list[dict[str, Any]] = []
    for label, pairs in sorted(grouped.items(), key=lambda item: (-len(item[1]), item[0].casefold())):
        rows.append({
            "source_label": label,
            "record_count": len(pairs),
            "first_string_no": string_number(pairs[0][0]),
            "last_string_no": string_number(pairs[-1][0]),
            "all_target_placeholders": all(is_placeholder(text_value(target)) for _, target in pairs),
            "candidate_for_future_allowlisted_restoration": True,
            "raw_records_exported": False,
        })
    return rows


def records_by_base_tag(records: Sequence[XmlRecord]) -> dict[str, XmlRecord]:
    result: dict[str, XmlRecord] = {}
    for record in records:
        tag = record.attrs.get("BaseTag", "")
        if tag:
            result[tag] = record
    return result


def attrs_without_runtime_paths(attrs: Mapping[str, str]) -> dict[str, str]:
    return {str(key): str(value) for key, value in attrs.items()}


def record_chain(records: Mapping[str, Sequence[XmlRecord]], label_rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    source_chara = records_by_base_tag(records["original_chara"])
    target_chara = records_by_base_tag(records["quartet_chara"])
    source_chara_no = records_by_base_tag(records["original_chara_no"])
    target_chara_no = records_by_base_tag(records["quartet_chara_no"])
    source_base = records_by_base_tag(records["original_charabase"])
    target_base = records_by_base_tag(records["quartet_charabase"])
    labels_by_tag = {str(row.get("base_tag", "")): row for row in label_rows}

    output: list[dict[str, Any]] = []
    for slot in range(8):
        tag = f"PC{slot:02d}_DLC_BKN"
        source_chara_row = source_chara.get(tag)
        target_chara_row = target_chara.get(tag)
        source_no_row = source_chara_no.get(tag)
        target_no_row = target_chara_no.get(tag)
        source_base_row = source_base.get(tag)
        target_base_row = target_base.get(tag)
        label = labels_by_tag.get(tag, {})

        source_model = source_base_row.attrs.get("Model", "") if source_base_row else ""
        target_model = target_base_row.attrs.get("Model", "") if target_base_row else ""
        source_texture = source_base_row.attrs.get("defaultTexture", "") if source_base_row else ""
        target_texture = target_base_row.attrs.get("defaultTexture", "") if target_base_row else ""
        source_and_target_chara_identical = bool(source_chara_row and target_chara_row and source_chara_row.sha256 == target_chara_row.sha256)
        source_and_target_chara_no_identical = bool(source_no_row and target_no_row and source_no_row.sha256 == target_no_row.sha256)
        baseline_is_scl_fallback = target_model.casefold().endswith("_scl") and target_texture.casefold().endswith("_scl")
        source_uses_bkn_assets = "_dlc_bkn" in source_model.casefold() and "_dlc_bkn" in source_texture.casefold()

        output.append({
            "pc_slot": f"PC{slot:02d}",
            "base_tag": tag,
            "string_no": label.get("string_no", ""),
            "source_label": label.get("source_label", ""),
            "quartet_label": label.get("quartet_label", ""),
            "quartet_label_placeholder": label.get("quartet_is_placeholder", False),
            "chara_record_present_both": source_chara_row is not None and target_chara_row is not None,
            "chara_record_identical": source_and_target_chara_identical,
            "chara_no_record_present_both": source_no_row is not None and target_no_row is not None,
            "chara_no_record_identical": source_and_target_chara_no_identical,
            "charabase_record_present_both": source_base_row is not None and target_base_row is not None,
            "source_model": source_model,
            "quartet_baseline_model": target_model,
            "source_default_texture": source_texture,
            "quartet_baseline_default_texture": target_texture,
            "source_uses_bkn_assets": source_uses_bkn_assets,
            "quartet_baseline_is_school_uniform_fallback": baseline_is_scl_fallback,
            "generation8_charabase_patch_required": True,
            "raw_record_exported": False,
        })
    return output


def load_active_manifest(project_root: Path) -> dict[str, Any]:
    path = project_root / ".local/reports/quartet_legacy_dlc/validated_payloads/ACTIVE.json"
    require_regular(path, "ACTIVE generation 8")
    value = json.loads(path.read_text(encoding="utf-8"))
    if value.get("type") != "validated_quartet_legacy_dlc_payload":
        raise ForcePointError("unexpected ACTIVE.json type")
    if value.get("family_id") != "bkn_dry" or value.get("generation") != EXPECTED_GENERATION:
        raise ForcePointError("ACTIVE.json is not BKN generation 8")
    if value.get("members") != EXPECTED_MEMBERS:
        raise ForcePointError("ACTIVE.json does not contain exactly PC00-PC07")
    targets = {str(row.get("target_path")) for row in value.get("artifacts", [])}
    if targets != EXPECTED_TARGETS:
        raise ForcePointError("ACTIVE.json target set changed")
    return value


def installation_rows(active: Mapping[str, Any], game_root: Path) -> tuple[list[dict[str, Any]], bool]:
    rows: list[dict[str, Any]] = []
    all_baseline = True
    for artifact in active.get("artifacts", []):
        target = str(artifact["target_path"])
        path = game_root / target
        require_regular(path, target)
        actual = sha256_file(path)
        baseline = str(artifact["baseline_sha256"])
        candidate = str(artifact["candidate_sha256"])
        state = "baseline" if actual == baseline else "generation8_candidate" if actual == candidate else "unknown"
        if state != "baseline":
            all_baseline = False
        rows.append({
            "target_path": target,
            "actual_sha256": actual,
            "baseline_sha256": baseline,
            "generation8_candidate_sha256": candidate,
            "state": state,
            "modified_by_audit": False,
        })
    if any(row["state"] == "unknown" for row in rows):
        raise ForcePointError("Quartet PAK state is not an accepted baseline or generation-8 candidate")
    return rows, all_baseline


def locate_generation8_candidate_charabase(project_root: Path) -> Path:
    expected = project_root / (
        ".local/build/quartet_legacy_dlc/family_expansion/"
        "costume_pc00_pc01_pc02_pc03_pc04_pc05_pc06_pc07_bkn_dry/"
        "candidate_member/saves/b1/chara/charabase.xml"
    )
    require_regular(expected, "generation-8 candidate charabase.xml")
    return expected


def candidate_charabase_rows(path: Path) -> list[dict[str, Any]]:
    records = parse_xml(path, path.parents[5])
    by_tag = records_by_base_tag(records)
    rows: list[dict[str, Any]] = []
    for slot in range(8):
        tag = f"PC{slot:02d}_DLC_BKN"
        record = by_tag.get(tag)
        model = record.attrs.get("Model", "") if record else ""
        texture = record.attrs.get("defaultTexture", "") if record else ""
        rows.append({
            "pc_slot": f"PC{slot:02d}",
            "base_tag": tag,
            "record_present": record is not None,
            "model": model,
            "default_texture": texture,
            "routes_to_bkn_assets": "_dlc_bkn" in model.casefold() and "_dlc_bkn" in texture.casefold(),
            "record_sha256": record.sha256 if record else "",
            "raw_record_exported": False,
        })
    return rows


def build_force_strategy(
    label_rows: Sequence[Mapping[str, Any]],
    control_rows: Sequence[Mapping[str, Any]],
    chain_rows: Sequence[Mapping[str, Any]],
    candidate_rows: Sequence[Mapping[str, Any]],
) -> tuple[list[dict[str, Any]], bool, list[str]]:
    blockers: list[str] = []
    exact_15 = len(label_rows) == 15 and all(row.get("pc_slot") for row in label_rows)
    if not exact_15:
        blockers.append("original BKN label block is not exactly fifteen ordered character rows")
    if not all(bool(row.get("quartet_record_present")) for row in label_rows[:8]):
        blockers.append("one or more PC00-PC07 target BKN string records are missing")
    if not all(bool(row.get("quartet_is_placeholder")) for row in label_rows[:8]):
        blockers.append("one or more PC00-PC07 BKN labels are not Quartet placeholders")
    if {str(row.get("label")) for row in control_rows} != set(VISIBLE_LABELS):
        blockers.append("runtime-visible control labels are not all present in Quartet str_costume")
    if not all(bool(row.get("chara_record_identical")) and bool(row.get("chara_no_record_identical")) for row in chain_rows):
        blockers.append("PC00-PC07 chara/chara_no records are not preserved source-to-target")
    if not all(bool(row.get("quartet_baseline_is_school_uniform_fallback")) for row in chain_rows):
        blockers.append("one or more Quartet baseline BKN charabase rows are not school-uniform fallbacks")
    if not all(bool(row.get("routes_to_bkn_assets")) for row in candidate_rows):
        blockers.append("accepted generation-8 charabase candidate does not route every PC00-PC07 row to BKN assets")

    eligible = not blockers
    ranking = [
        {
            "rank": 1,
            "strategy_id": "restore_allowlisted_bkn_str_costume_rows",
            "layer": "data_only",
            "target_parent": "Data/PACK12.PAK",
            "target_member": "saves/b1/text_en/str_costume.xml",
            "scope": "PC00-PC07 BKN rows only",
            "replaces_existing_costume": False,
            "global_show_all": False,
            "requires_save_edit": False,
            "requires_platform_entitlement": False,
            "requires_core_change": False,
            "eligible_for_next_bounded_build": eligible,
            "reason": (
                "The BKN character rows and generation-8 asset routing already exist; the same-number Quartet costume labels are placeholders, while runtime-visible controls have non-placeholder labels."
            ),
        },
        {
            "rank": 2,
            "strategy_id": "controlled_bkn_namespace_filter_bypass",
            "layer": "runtime_filter_fallback",
            "target_parent": "unassigned",
            "target_member": "PCxx_DLC_BKN allowlist only",
            "replaces_existing_costume": False,
            "global_show_all": False,
            "requires_save_edit": False,
            "requires_platform_entitlement": False,
            "requires_core_change": "only_if_new_artifact_or_operation_is_required",
            "eligible_for_next_bounded_build": False,
            "reason": "Use only if the data-only label restoration probe is runtime-tested and still invisible.",
        },
        {
            "rank": 3,
            "strategy_id": "synthetic_save_or_entitlement_grant",
            "layer": "state_mutation",
            "target_parent": "none",
            "target_member": "none",
            "replaces_existing_costume": False,
            "global_show_all": False,
            "requires_save_edit": True,
            "requires_platform_entitlement": True,
            "requires_core_change": False,
            "eligible_for_next_bounded_build": False,
            "reason": "Not preferred because the user authorized direct availability forcing and no exact owner was found.",
        },
        {
            "rank": 4,
            "strategy_id": "global_show_all_costume_records",
            "layer": "unsafe_global_bypass",
            "target_parent": "unassigned",
            "target_member": "all costume records",
            "replaces_existing_costume": False,
            "global_show_all": True,
            "requires_save_edit": False,
            "requires_platform_entitlement": False,
            "requires_core_change": False,
            "eligible_for_next_bounded_build": False,
            "reason": "Forbidden: it could expose dummy, incomplete or unrelated records outside the validated legacy-DLC allowlist.",
        },
    ]
    return ranking, eligible, blockers


def create_manifest(output_dir: Path) -> None:
    rows: list[dict[str, Any]] = []
    for path in sorted(output_dir.rglob("*"), key=lambda item: item.as_posix().casefold()):
        if not path.is_file() or path.name in {"REPORT_MANIFEST.json", "SHA256SUMS"}:
            continue
        if path.suffix.casefold() in FORBIDDEN_OUTPUT_SUFFIXES:
            raise ForcePointError(f"forbidden raw payload in report: {path.name}")
        rows.append({
            "relative_path": path.relative_to(output_dir).as_posix(),
            "size": path.stat().st_size,
            "sha256": sha256_file(path),
        })
    write_json(output_dir / "REPORT_MANIFEST.json", {
        "type": "br_report_manifest",
        "format_version": 1,
        "files": rows,
    })


def load_stage100_acceptance(workstream_root: Path) -> dict[str, Any]:
    path = workstream_root / "DLC_QUARTET_NATIVE_DLC_ID_OWNER_BINDING_RETURN_ACCEPTANCE.json"
    require_regular(path, "stage-100 owner-binding acceptance")
    value = json.loads(path.read_text(encoding="utf-8"))
    if value.get("status") != "accepted_exact_owner_not_proven_and_no_longer_required_for_forced_availability":
        raise ForcePointError("stage-100 owner-binding evidence is not accepted for the force-policy transition")
    if value.get("exact_owner_binding_proven") is not False:
        raise ForcePointError("stage-100 acceptance no longer represents the exact-owner-not-proven result")
    return value


def load_policy(workstream_root: Path) -> dict[str, Any]:
    path = workstream_root / "DLC_LEGACY_CONTENT_FORCE_POLICY.json"
    require_regular(path, "legacy content force policy")
    value = json.loads(path.read_text(encoding="utf-8"))
    if value.get("availability_forcing_allowed") is not True:
        raise ForcePointError("availability forcing is not authorized")
    if value.get("existing_costume_replacement_forbidden") is not True:
        raise ForcePointError("existing-costume replacement prohibition is missing")
    if value.get("allowlist_only") is not True:
        raise ForcePointError("force policy is not allowlist-only")
    return value


def run(project_root: Path, original_root: Path, game_root: Path, output_dir: Path) -> dict[str, Any]:
    workstream_root = project_root / "workstreams/quartet_legacy_dlc"
    version = (workstream_root / "VERSION").read_text(encoding="utf-8").strip()
    if version != EXPECTED_WORKSTREAM_VERSION:
        raise ForcePointError(f"quartet_legacy_dlc {EXPECTED_WORKSTREAM_VERSION} is required, got {version}")
    stage100 = load_stage100_acceptance(workstream_root)
    policy = load_policy(workstream_root)

    if not original_root.is_dir() or original_root.is_symlink():
        raise ForcePointError(f"original game root is not a regular directory: {original_root}")
    if not game_root.is_dir() or game_root.is_symlink():
        raise ForcePointError(f"Quartet game root is not a regular directory: {game_root}")

    workspace = project_root / "titles/blue_reflection/workspace"
    if not workspace.is_dir() or workspace.is_symlink():
        raise ForcePointError(f"missing canonical workspace: {workspace}")
    paths = locate_workspace_xml(workspace)
    records = load_records(paths, workspace)

    active = load_active_manifest(project_root)
    install_rows, all_baseline = installation_rows(active, game_root)
    candidate_path = locate_generation8_candidate_charabase(project_root)
    candidate_rows = candidate_charabase_rows(candidate_path)

    original_text_rows = records["original_str_costume"]
    quartet_text_rows = records["quartet_str_costume"]
    label_rows, exact_family_block = bkn_label_block(original_text_rows, quartet_text_rows)
    controls = visible_control_rows(quartet_text_rows)
    placeholder_blocks = all_placeholder_blocks(original_text_rows, quartet_text_rows)
    chain_rows = record_chain(records, label_rows)
    ranking, build_eligible, blockers = build_force_strategy(label_rows, controls, chain_rows, candidate_rows)

    patch_rows: list[dict[str, Any]] = []
    for row in label_rows[:8]:
        patch_rows.append({
            "pc_slot": row.get("pc_slot", ""),
            "base_tag": row.get("base_tag", ""),
            "target_path": "Data/PACK12.PAK",
            "member_path": "saves/b1/text_en/str_costume.xml",
            "string_no": row.get("string_no", ""),
            "expected_old_value": row.get("quartet_label", ""),
            "new_value_from_original": row.get("source_label", ""),
            "operation": "replace_text_value_in_existing_record",
            "allowlisted": True,
            "existing_quartet_costume_replaced": False,
            "other_records_must_remain_byte_semantically_identical": True,
            "candidate_build_authorized_by_this_audit": False,
        })

    output_dir.mkdir(parents=True, exist_ok=True)
    write_tsv(output_dir / "BKN_STR_COSTUME_BLOCK.tsv", label_rows)
    write_tsv(output_dir / "VISIBLE_COSTUME_LABEL_CONTROLS.tsv", controls)
    write_tsv(output_dir / "LEGACY_PLACEHOLDER_BLOCKS.tsv", placeholder_blocks)
    write_tsv(output_dir / "BKN_RECORD_CHAIN.tsv", chain_rows)
    write_tsv(output_dir / "GENERATION8_CANDIDATE_CHARABASE_GATES.tsv", candidate_rows)
    write_tsv(output_dir / "INSTALLATION_BASELINE_GATES.tsv", install_rows)
    write_tsv(output_dir / "BKN_DATA_ONLY_PATCH_PLAN.tsv", patch_rows)
    write_tsv(output_dir / "FORCE_STRATEGY_RANKING.tsv", ranking)

    acceptance = {
        "type": "br_quartet_legacy_dlc_controlled_visibility_force_point_acceptance",
        "format_version": 1,
        "status": "accepted_for_generation9_data_only_label_probe" if build_eligible else "blocked_force_point_not_closed",
        "generation8": EXPECTED_GENERATION,
        "members": EXPECTED_MEMBERS,
        "force_policy": {
            "availability_forcing_allowed": policy["availability_forcing_allowed"],
            "synthetic_unlock_allowed": policy["synthetic_unlock_allowed"],
            "allowlist_only": policy["allowlist_only"],
            "existing_costume_replacement_forbidden": policy["existing_costume_replacement_forbidden"],
            "global_show_all_forbidden": policy["global_show_all_forbidden"],
        },
        "selected_force_point": "saves/b1/text_en/str_costume.xml" if build_eligible else "",
        "selected_strategy": "restore_allowlisted_bkn_str_costume_rows" if build_eligible else "",
        "target_parent": "Data/PACK12.PAK" if build_eligible else "",
        "third_pak_required": False if build_eligible else None,
        "replacement_of_existing_quartet_costumes": False,
        "save_or_entitlement_required": False,
        "core_change_required": False,
        "generation9_build_allowed": build_eligible,
        "runtime_install_allowed": False,
        "blockers": blockers,
    }
    write_json(output_dir / "DATA_ONLY_FORCE_ACCEPTANCE.json", acceptance)

    summary = {
        "type": "br_quartet_legacy_dlc_controlled_visibility_force_point_audit",
        "format_version": FORMAT_VERSION,
        "tool_version": TOOL_VERSION,
        "status": acceptance["status"],
        "stage100_bundle_sha256": stage100["bundle_sha256"],
        "generation8": EXPECTED_GENERATION,
        "members": EXPECTED_MEMBERS,
        "installation_all_baseline": all_baseline,
        "bkn_source_label_rows": len(label_rows),
        "bkn_exact_fifteen_character_block": exact_family_block,
        "pc00_pc07_target_placeholder_rows": sum(1 for row in label_rows[:8] if row.get("quartet_is_placeholder")),
        "runtime_visible_control_rows": len(controls),
        "preserved_chara_chain_rows": len(chain_rows),
        "generation8_candidate_charabase_rows": len(candidate_rows),
        "legacy_placeholder_label_groups": len(placeholder_blocks),
        "selected_strategy": acceptance["selected_strategy"],
        "generation9_build_allowed": build_eligible,
        "third_pak_required": acceptance["third_pak_required"],
        "game_files_modified": False,
        "save_files_modified": False,
        "active_manifest_modified": False,
        "candidate_built": False,
        "prepare_called": False,
        "commit_called": False,
        "runtime_validation_performed": False,
        "raw_pak_members_exported": False,
        "required_next_action": (
            "build a checksum-gated generation-9 PC00-PC07 dry BKN candidate that preserves generation 8 and restores only the allowlisted BKN str_costume rows inside PACK12; canonical preview only"
            if build_eligible
            else "resolve the reported data-chain blockers before any candidate build"
        ),
    }
    write_json(output_dir / "SUMMARY.json", summary)
    create_manifest(output_dir)
    return summary


def parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", required=True)
    parser.add_argument("--original-dir", required=True)
    parser.add_argument("--game-dir", required=True)
    parser.add_argument("--output-dir", required=True)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    try:
        summary = run(
            Path(args.project_root).resolve(),
            Path(args.original_dir).resolve(),
            Path(args.game_dir).resolve(),
            Path(args.output_dir).resolve(),
        )
    except (ForcePointError, OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
