#!/usr/bin/env python3
"""Read-only exact availability closure audit for generation-8 dry BKN.

The broad routing audit did not identify a direct unlock field. This tool narrows
that result by comparing exact costume string sequences, PC00/BKN records and
bounded XML/binary references. It never writes game files, ACTIVE.json,
candidates, saves, core, Translation, Restoration, profiles or Git.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import struct
import sys
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

TOOL_VERSION = "0.0.57"
FORMAT_VERSION = 1
EXPECTED_WORKSTREAM_VERSION = "0.0.57"
EXPECTED_GENERATION = 8
EXPECTED_MEMBERS = [f"costume_pc{i:02d}_bkn" for i in range(8)]
EXPECTED_ROUTING_BUNDLE_SHA256 = "54ba62fd7562e614e6bdcea742b91ae991869838282a72c54519367fbdb2fb4e"
RUNTIME_LABELS = ("Hoshinomiya Uniform", "School Swimsuit", "Gym Uniform", "Cami")
SELECTED_XML_SUFFIXES = (
    "chara/chara.xml", "chara/chara_no.xml", "chara/charabase.xml",
    "chara/charaeffect.xml", "text/str_costume.xml", "text_en/str_costume.xml",
    "costume/costume.xml", "costume/coschangechara.xml",
    "ez_eff_player/costume_change.xml",
)
BINARY_NAME_RE = re.compile(r"(?:costume|dress|wardrobe|22_costume_change|blue reflection)", re.I)
FORBIDDEN_OUTPUT_SUFFIXES = {
    ".pak", ".exe", ".dll", ".ebm", ".ebd", ".g1m", ".g1t", ".g1a",
    ".g1e", ".g1s", ".elixir", ".gz", ".swg", ".dds", ".kscl", ".kslt", ".bin",
}


class ClosureError(RuntimeError):
    pass


@dataclass(frozen=True)
class Record:
    side: str
    relative_path: str
    index: int
    element: str
    attrs: dict[str, str]
    text: str
    raw_xml: str
    sha256: str


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


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
        raise ClosureError(f"{label} is not a regular file: {path}")


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
    raise ClosureError(f"unable to decode XML {label}: {'; '.join(errors)}")


def parse_xml(path: Path, workspace: Path) -> list[Record]:
    text = decode_xml(path.read_bytes(), str(path))
    text = re.sub(r"<\?xml[^>]*\?>", "", text, count=1, flags=re.I)
    try:
        root = ET.fromstring(text)
    except ET.ParseError as exc:
        raise ClosureError(f"failed to parse XML {path}: {exc}") from exc
    rel = path.relative_to(workspace).as_posix()
    folded = f"/{rel.casefold()}/"
    side = "original" if "/original/" in folded else "quartet" if "/quartet/" in folded else "unknown"
    rows: list[Record] = []
    for index, element in enumerate(root.iter()):
        if element is root:
            continue
        attrs = {str(k): str(v) for k, v in element.attrib.items()}
        element_text = (element.text or "").strip()
        raw_xml = ET.tostring(element, encoding="unicode", short_empty_elements=True)
        canonical = json.dumps(
            {"element": str(element.tag), "attrs": attrs, "text": element_text},
            ensure_ascii=False, sort_keys=True, separators=(",", ":"),
        )
        rows.append(Record(side, rel, index, str(element.tag), attrs, element_text, raw_xml,
                           sha256_bytes(canonical.encode("utf-8"))))
    return rows


def selected_xml_files(workspace: Path) -> tuple[list[Path], list[dict[str, str]]]:
    found: list[Path] = []
    missing: list[dict[str, str]] = []
    expected = {
        "original": [
            "original/archives/PACK02_1/saves_en/chara/chara.xml",
            "original/archives/PACK02_1/saves_en/chara/chara_no.xml",
            "original/archives/PACK02_1/saves_en/chara/charabase.xml",
            "original/archives/PACK02_1/saves_en/chara/charaeffect.xml",
            "original/archives/PACK02_1/saves_en/text/str_costume.xml",
            "original/archives/PACK02_1/saves_en/costume/costume.xml",
            "original/archives/PACK02_1/saves_en/costume/coschangechara.xml",
            "original/archives/PACK02_1/saves_en/ez_eff_player/costume_change.xml",
        ],
        "quartet": [
            "quartet/archives/PACK12/saves/b1/chara/chara.xml",
            "quartet/archives/PACK12/saves/b1/chara/chara_no.xml",
            "quartet/archives/PACK12/saves/b1/chara/charabase.xml",
            "quartet/archives/PACK12/saves/b1/chara/charaeffect.xml",
            "quartet/archives/PACK12/saves/b1/text_en/str_costume.xml",
            "quartet/archives/PACK12/saves/b1/costume/costume.xml",
            "quartet/archives/PACK12/saves/b1/costume/coschangechara.xml",
            "quartet/archives/PACK12/saves/b1/ez_eff_player/costume_change.xml",
        ],
    }
    for side, rels in expected.items():
        for rel in rels:
            path = workspace / rel
            if path.is_file() and not path.is_symlink():
                found.append(path)
            else:
                missing.append({"side": side, "relative_path": rel, "status": "missing_or_not_regular"})
    return found, missing


def record_key(record: Record) -> str:
    for key in ("BaseTag", "CharaTag", "tag", "Tag", "String_No", "No", "ID", "id", "name"):
        if key in record.attrs:
            return f"{record.element}:{key}={record.attrs[key]}"
    return f"{record.element}:index={record.index}"


def attrs_json(attrs: Mapping[str, str]) -> str:
    return json.dumps(dict(attrs), ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def str_costume_rows(records: Sequence[Record]) -> list[Record]:
    return [r for r in records if r.relative_path.casefold().endswith("str_costume.xml") and r.element.casefold() == "str"]


def compare_str_costume(original: Sequence[Record], quartet: Sequence[Record]) -> tuple[list[dict[str, Any]], list[int]]:
    def by_number(rows: Sequence[Record]) -> dict[int, Record]:
        result: dict[int, Record] = {}
        for row in rows:
            raw = row.attrs.get("String_No", "")
            if raw.isdigit():
                result[int(raw)] = row
        return result
    left, right = by_number(original), by_number(quartet)
    rows: list[dict[str, Any]] = []
    original_only: list[int] = []
    for number in sorted(set(left) | set(right)):
        a, b = left.get(number), right.get(number)
        if a and b:
            status = "identical" if a.attrs.get("Text", a.text) == b.attrs.get("Text", b.text) else "text_changed"
        elif a:
            status = "original_only"
            original_only.append(number)
        else:
            status = "quartet_only"
        rows.append({
            "string_no": number,
            "status": status,
            "original_record_index": a.index if a else "",
            "quartet_record_index": b.index if b else "",
            "original_text": (a.attrs.get("Text", a.text) if a else ""),
            "quartet_text": (b.attrs.get("Text", b.text) if b else ""),
            "runtime_visible_label": any(label.casefold() in ((a.attrs.get("Text", a.text) if a else "") + " " + (b.attrs.get("Text", b.text) if b else "")).casefold() for label in RUNTIME_LABELS),
            "original_record_sha256": a.sha256 if a else "",
            "quartet_record_sha256": b.sha256 if b else "",
        })
    return rows, original_only


def relevant_character(record: Record) -> bool:
    blob = "\n".join([record.raw_xml, *record.attrs.values(), record.text]).casefold()
    return (
        "pc00" in blob or "dlc_bkn" in blob or "costume" in record.relative_path.casefold()
        or any(label.casefold() in blob for label in RUNTIME_LABELS)
    )


def compare_character_records(records: Sequence[Record]) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str], dict[str, Record]] = {}
    for record in records:
        if not any(record.relative_path.casefold().endswith(suffix) for suffix in (
            "chara/chara.xml", "chara/chara_no.xml", "chara/charabase.xml", "chara/charaeffect.xml",
        )):
            continue
        if not relevant_character(record):
            continue
        key = (record.relative_path.split("/saves", 1)[-1].replace("_en/", "/").replace("/b1/", "/"), record_key(record))
        grouped.setdefault(key, {})[record.side] = record
    rows: list[dict[str, Any]] = []
    for (logical_path, key), sides in sorted(grouped.items()):
        a, b = sides.get("original"), sides.get("quartet")
        if a and b:
            status = "identical" if a.sha256 == b.sha256 else "different"
        elif a:
            status = "original_only"
        else:
            status = "quartet_only"
        rows.append({
            "logical_path": logical_path,
            "record_key": key,
            "status": status,
            "original_index": a.index if a else "",
            "quartet_index": b.index if b else "",
            "original_attributes": a.attrs if a else {},
            "quartet_attributes": b.attrs if b else {},
            "original_record_sha256": a.sha256 if a else "",
            "quartet_record_sha256": b.sha256 if b else "",
        })
    return rows


def scan_xml_references(records: Sequence[Record], string_numbers: Sequence[int]) -> list[dict[str, Any]]:
    targets = {str(x) for x in string_numbers}
    rows: list[dict[str, Any]] = []
    for record in records:
        if record.relative_path.casefold().endswith("str_costume.xml"):
            continue
        hits: list[str] = []
        for value in [*record.attrs.values(), record.text]:
            for token in re.findall(r"\d+", value):
                if token in targets:
                    hits.append(token)
        if hits:
            rows.append({
                "side": record.side,
                "table_path": record.relative_path,
                "record_index": record.index,
                "record_key": record_key(record),
                "matched_string_numbers": sorted(set(hits), key=int),
                "attributes": record.attrs,
                "record_sha256": record.sha256,
                "raw_record_exported": False,
            })
    return rows


def candidate_binary_files(workspace: Path, game_root: Path) -> list[Path]:
    rows: list[Path] = []
    for path in workspace.rglob("*"):
        if not path.is_file() or path.is_symlink():
            continue
        if path.suffix.casefold() not in {".kscl", ".kslt", ".bin"}:
            continue
        if BINARY_NAME_RE.search(path.name) or BINARY_NAME_RE.search(path.as_posix()):
            rows.append(path)
    for path in game_root.iterdir():
        if path.is_file() and not path.is_symlink() and path.suffix.casefold() in {".exe", ".dll"} and BINARY_NAME_RE.search(path.name):
            rows.append(path)
    return sorted(set(rows))


def bounded_binary_scan(files: Sequence[Path], workspace: Path, game_root: Path,
                        string_numbers: Sequence[int], character_indices: Sequence[int]) -> list[dict[str, Any]]:
    values = sorted(set(string_numbers) | set(character_indices))
    rows: list[dict[str, Any]] = []
    for path in files:
        data = path.read_bytes()
        try:
            rel = path.relative_to(workspace).as_posix()
            source = "workspace"
        except ValueError:
            rel = path.relative_to(game_root).as_posix()
            source = "game_root"
        file_hash = sha256_bytes(data)
        for value in values:
            for width, fmt in ((2, "<H"), (4, "<I")):
                if value >= (1 << (width * 8)):
                    continue
                needle = struct.pack(fmt, value)
                offsets: list[int] = []
                start = 0
                while len(offsets) < 32:
                    off = data.find(needle, start)
                    if off < 0:
                        break
                    offsets.append(off)
                    start = off + 1
                if offsets:
                    rows.append({
                        "source": source,
                        "relative_path": rel,
                        "file_size": len(data),
                        "file_sha256": file_hash,
                        "value": value,
                        "value_class": "costume_string_no" if value in string_numbers else "character_record_index",
                        "width_bits": width * 8,
                        "hit_count_capped": len(offsets),
                        "offsets": offsets,
                        "raw_payload_exported": False,
                    })
    return rows


def verify_acceptance(project_root: Path) -> dict[str, Any]:
    ws = project_root / "workstreams/quartet_legacy_dlc"
    version = (ws / "VERSION").read_text(encoding="utf-8").strip()
    if version != EXPECTED_WORKSTREAM_VERSION:
        raise ClosureError(f"quartet_legacy_dlc {EXPECTED_WORKSTREAM_VERSION} is required, got {version}")
    acceptance_path = ws / "DLC_BKN_DRY_GENERATION8_AVAILABILITY_ROUTING_ACCEPTANCE.json"
    require_regular(acceptance_path, "availability-routing acceptance")
    acceptance = json.loads(acceptance_path.read_text(encoding="utf-8"))
    if acceptance.get("status") != "accepted_for_read_only_exact_availability_closure":
        raise ClosureError("availability-routing acceptance is not active")
    if acceptance.get("evidence_bundle_sha256") != EXPECTED_ROUTING_BUNDLE_SHA256:
        raise ClosureError("availability-routing evidence hash changed")
    return acceptance


def verify_active(project_root: Path) -> dict[str, Any]:
    path = project_root / ".local/reports/quartet_legacy_dlc/validated_payloads/ACTIVE.json"
    require_regular(path, "ACTIVE.json")
    active = json.loads(path.read_text(encoding="utf-8"))
    if active.get("generation") != EXPECTED_GENERATION or active.get("members") != EXPECTED_MEMBERS:
        raise ClosureError("ACTIVE.json is not accepted generation 8 PC00-PC07")
    return active


def run(project_root: Path, original_root: Path, game_root: Path, output_dir: Path) -> dict[str, Any]:
    acceptance = verify_acceptance(project_root)
    active = verify_active(project_root)
    workspace = project_root / "titles/blue_reflection/workspace"
    if not workspace.is_dir():
        raise ClosureError(f"workspace missing: {workspace}")
    if not original_root.is_dir() or not game_root.is_dir():
        raise ClosureError("original-dir and game-dir must be directories")
    output_dir.mkdir(parents=True, exist_ok=False)

    xml_files, missing_files = selected_xml_files(workspace)
    records: list[Record] = []
    parse_status: list[dict[str, Any]] = []
    for path in xml_files:
        try:
            parsed = parse_xml(path, workspace)
            records.extend(parsed)
            parse_status.append({"relative_path": path.relative_to(workspace).as_posix(), "status": "parsed", "record_count": len(parsed), "error": ""})
        except ClosureError as exc:
            parse_status.append({"relative_path": path.relative_to(workspace).as_posix(), "status": "parse_failed", "record_count": 0, "error": str(exc)})
    parse_status.extend({**row, "record_count": 0, "error": ""} for row in missing_files)

    original_strings = str_costume_rows([r for r in records if r.side == "original"])
    quartet_strings = str_costume_rows([r for r in records if r.side == "quartet"])
    string_diff, original_only_numbers = compare_str_costume(original_strings, quartet_strings)
    character_diff = compare_character_records(records)

    bkn_indices = sorted({
        r.index for r in records
        if r.side == "quartet" and any(tag.casefold() in r.raw_xml.casefold() for tag in ("PC00_DLC_BKN", "PC01_DLC_BKN", "PC02_DLC_BKN", "PC03_DLC_BKN", "PC04_DLC_BKN", "PC05_DLC_BKN", "PC06_DLC_BKN", "PC07_DLC_BKN"))
        and r.relative_path.casefold().endswith(("chara/chara.xml", "chara/chara_no.xml", "chara/charabase.xml"))
    })
    xml_refs = scan_xml_references(records, original_only_numbers)
    binary_files = candidate_binary_files(workspace, game_root)
    binary_refs = bounded_binary_scan(binary_files, workspace, game_root, original_only_numbers, bkn_indices)

    registry_rows: list[dict[str, Any]] = []
    for record in records:
        if not any(record.relative_path.casefold().endswith(suffix) for suffix in (
            "costume/costume.xml", "costume/coschangechara.xml", "ez_eff_player/costume_change.xml"
        )):
            continue
        blob = record.raw_xml.casefold()
        registry_rows.append({
            "side": record.side,
            "table_path": record.relative_path,
            "record_index": record.index,
            "record_key": record_key(record),
            "contains_bkn": "bkn" in blob,
            "contains_pc00": "pc00" in blob,
            "attributes": record.attrs,
            "record_sha256": record.sha256,
            "raw_record_exported": False,
        })

    original_only_rows = [row for row in string_diff if row["status"] == "original_only"]
    direct_xml_reference_count = len(xml_refs)
    binary_reference_count = len(binary_refs)
    if original_only_rows and direct_xml_reference_count:
        route_class = "table_or_index_driven_candidate"
        next_action = "review exact XML references to original-only costume String_No values and prepare a metadata-only patch proposal only if one canonical owner is proven"
    elif original_only_rows and binary_reference_count:
        route_class = "binary_index_driven_candidate"
        next_action = "review bounded costume-layout or module references; do not patch until a unique sequence and owner are proven"
    elif original_only_rows:
        route_class = "string_sequence_truncated_but_no_owner_reference_found"
        next_action = "perform a save/entitlement-state differential between original DLC-enabled and Quartet saves before building another payload"
    else:
        route_class = "no_costume_string_sequence_gap_found"
        next_action = "perform a save/entitlement-state differential because selected tables do not explain runtime visibility"

    summary = {
        "type": "br_quartet_legacy_dlc_bkn_dry_generation8_exact_availability_closure",
        "format_version": FORMAT_VERSION,
        "tool_version": TOOL_VERSION,
        "status": "exact_closure_evidence_collected_build_still_blocked",
        "generation": EXPECTED_GENERATION,
        "members": EXPECTED_MEMBERS,
        "routing_acceptance_bundle_sha256": acceptance["evidence_bundle_sha256"],
        "active_manifest_sha256": sha256_file(project_root / ".local/reports/quartet_legacy_dlc/validated_payloads/ACTIVE.json"),
        "workspace": {
            "selected_xml_files": len(xml_files),
            "parsed_records": len(records),
            "parse_failures_or_missing": sum(1 for x in parse_status if x["status"] != "parsed"),
        },
        "str_costume": {
            "original_records": len(original_strings),
            "quartet_records": len(quartet_strings),
            "original_only_records": len(original_only_rows),
            "quartet_only_records": sum(1 for x in string_diff if x["status"] == "quartet_only"),
            "text_changed_records": sum(1 for x in string_diff if x["status"] == "text_changed"),
            "original_only_string_numbers": original_only_numbers,
        },
        "character_records": {
            "compared_records": len(character_diff),
            "different_records": sum(1 for x in character_diff if x["status"] == "different"),
            "original_only_records": sum(1 for x in character_diff if x["status"] == "original_only"),
            "quartet_only_records": sum(1 for x in character_diff if x["status"] == "quartet_only"),
            "bkn_indices": bkn_indices,
        },
        "references": {
            "xml_references_to_original_only_string_numbers": direct_xml_reference_count,
            "bounded_binary_reference_rows": binary_reference_count,
            "binary_files_scanned": len(binary_files),
        },
        "conclusion": {
            "route_classification": route_class,
            "exact_availability_owner_proven": False,
            "next_payload_generation_allowed": False,
            "pc08_build_allowed": False,
            "core_change_required": False,
            "save_or_entitlement_state_differential_may_be_required": route_class in {
                "string_sequence_truncated_but_no_owner_reference_found", "no_costume_string_sequence_gap_found"
            },
            "required_next_action": next_action,
        },
        "authorization": {
            "candidate_build": False,
            "active_manifest_write": False,
            "prepare": False,
            "commit": False,
            "install": False,
            "runtime_validation": False,
            "pc08_build": False,
            "core_modification": False,
            "translation_modification": False,
            "restoration_modification": False,
            "git_modification": False,
        },
        "game_files_modified": False,
        "raw_assets_exported": False,
    }

    write_json(output_dir / "SUMMARY.json", summary)
    write_json(output_dir / "ACTIVE_GENERATION8.json", active)
    write_json(output_dir / "AVAILABILITY_ROUTING_ACCEPTANCE.json", acceptance)
    write_tsv(output_dir / "SELECTED_XML_PARSE_STATUS.tsv", parse_status)
    write_tsv(output_dir / "STR_COSTUME_SEQUENCE_DIFF.tsv", string_diff)
    write_tsv(output_dir / "CHARACTER_RECORD_DIFFERENTIAL.tsv", character_diff)
    write_tsv(output_dir / "ORIGINAL_ONLY_STRING_XML_REFERENCES.tsv", xml_refs)
    write_tsv(output_dir / "BOUNDED_COSTUME_BINARY_REFERENCES.tsv", binary_refs)
    write_tsv(output_dir / "COSTUME_REGISTRY_RECORDS.tsv", registry_rows)
    write_tsv(output_dir / "BINARY_FILES_SCANNED.tsv", [
        {"source": "workspace" if str(path).startswith(str(workspace)) else "game_root",
         "relative_path": path.relative_to(workspace).as_posix() if str(path).startswith(str(workspace)) else path.relative_to(game_root).as_posix(),
         "size": path.stat().st_size, "sha256": sha256_file(path), "status": "scanned"}
        for path in binary_files
    ])
    return summary


def ensure_metadata_only(output_dir: Path) -> None:
    for path in output_dir.rglob("*"):
        if path.is_file() and path.suffix.casefold() in FORBIDDEN_OUTPUT_SUFFIXES:
            raise ClosureError(f"forbidden raw output: {path}")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path, required=True)
    parser.add_argument("--original-dir", type=Path, required=True)
    parser.add_argument("--game-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        summary = run(args.project_root.resolve(), args.original_dir.resolve(), args.game_dir.resolve(), args.output_dir.resolve())
        ensure_metadata_only(args.output_dir.resolve())
    except (ClosureError, OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
