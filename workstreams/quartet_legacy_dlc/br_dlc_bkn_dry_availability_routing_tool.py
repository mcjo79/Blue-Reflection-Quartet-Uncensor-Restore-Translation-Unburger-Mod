#!/usr/bin/env python3
"""Read-only generation-8 BKN availability, unlock, inventory and UI-routing audit.

The tool accepts the failed-at-visibility runtime return, verifies the accepted
generation-8 candidates, and accepts either a still-installed generation 8 or a
complete rollback to the manifest baseline. It then compares BKN records with
the runtime-visible Hinako costume entries across canonical XML workspaces and
prior metadata evidence.

It never writes the game, ACTIVE.json, candidates, core, Translation,
Restoration, profiles, saves, or Git. No raw PAK member or executable payload is
exported.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import shutil
import sys
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

TOOL_VERSION = "0.0.56"
FORMAT_VERSION = 1
EXPECTED_WORKSTREAM_VERSION = "0.0.56"
EXPECTED_GENERATION = 8
EXPECTED_MEMBERS = [f"costume_pc{i:02d}_bkn" for i in range(8)]
EXPECTED_TARGETS = {"Data/PACK10_02.PAK", "Data/PACK12.PAK"}
RUNTIME_LABELS = (
    "Hoshinomiya Uniform",
    "School Swimsuit",
    "Gym Uniform",
    "Cami",
)
BKN_TAGS = tuple(f"PC{i:02d}_DLC_BKN{suffix}" for i in range(15) for suffix in ("", "_W"))
BKN_PATHS = tuple(
    f"PC{i:02d}/PC{i:02d}_DLC_Bkn{suffix}" for i in range(15) for suffix in ("", "_W")
)
TECHNICAL_TOKENS = BKN_TAGS + BKN_PATHS + ("DLC_BKN", "dlc_bkn")
ACTIVATION_FIELD_RE = re.compile(
    r"(?:dlc|entitlement|permit|enable|active|availability|unlock|release|condition|flag|event|st_ev|product|inventory|item|shop|grant|owned|display|visible|select|list|wardrobe|dress|costume)",
    re.I,
)
ROUTING_PATH_RE = re.compile(
    r"(?:costume|coschange|dress|wardrobe|mainmenu|release|condition|unlock|entitlement|inventory|item|chara)",
    re.I,
)
SAFE_ATTRIBUTE_RE = re.compile(
    r"(?:tag|id|no|index|model|texture|costume|chara|item|flag|event|release|condition|unlock|dlc|entitlement|visible|display|select|list|shop|inventory|grant|name|text|string)",
    re.I,
)
PRIOR_TERMS = tuple(
    x.casefold()
    for x in (
        "PC00_DLC_BKN",
        "DLC_BKN",
        "bkn",
        "unlock",
        "entitlement",
        "availability",
        "Dressing Room",
        *RUNTIME_LABELS,
    )
)
ALLOWED_METADATA_SUFFIXES = {".json", ".tsv", ".csv", ".md", ".txt", ".log"}
FORBIDDEN_OUTPUT_SUFFIXES = {
    ".pak", ".exe", ".dll", ".ebm", ".ebd", ".g1m", ".g1t", ".g1a",
    ".g1e", ".g1s", ".elixir", ".gz", ".swg", ".dds", ".wav", ".ogg",
    ".kscl", ".kslt", ".bin",
}


class AvailabilityRoutingError(RuntimeError):
    pass


@dataclass(frozen=True)
class XmlRecord:
    side: str
    relative_path: str
    record_index: int
    element: str
    attrs: dict[str, str]
    text: str
    record_sha256: str


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
        raise AvailabilityRoutingError(f"{label} is not a regular file: {path}")


def decode_xml_bytes(raw: bytes, label: str) -> str:
    # Some extracted Gust XML files carry an UTF-8 BOM even though their body
    # is CP932. A BOM is therefore a strong hint, not unconditional proof.
    payload = raw
    bom_candidates: list[str] = []
    utf16_bom = raw.startswith((b"\xff\xfe", b"\xfe\xff"))
    if raw.startswith(b"\xef\xbb\xbf"):
        payload = raw[3:]
        bom_candidates.append("utf-8")
    elif utf16_bom:
        bom_candidates.append("utf-16")

    declaration = re.search(br"encoding=[\"']([^\"']+)", payload[:512], re.I)
    declared = declaration.group(1).decode("ascii", "replace") if declaration else ""
    aliases = {
        "shift-jis": "cp932", "shift_jis": "cp932", "shiftjis": "cp932",
        "sjis": "cp932", "windows-31j": "cp932", "ms932": "cp932",
        "utf-8": "utf-8", "utf8": "utf-8",
        "utf-16": "utf-16", "utf16": "utf-16",
    }
    declared_codec = aliases.get(declared.casefold(), declared)
    candidates = [*bom_candidates, declared_codec, "cp932", "utf-8"]
    errors: list[str] = []
    for encoding in dict.fromkeys(x for x in candidates if x):
        try:
            source = raw if encoding == "utf-16" and utf16_bom else payload
            return source.decode(encoding)
        except (UnicodeDecodeError, LookupError) as exc:
            errors.append(f"{encoding}: {exc}")
    raise AvailabilityRoutingError(f"unable to decode XML {label}: {'; '.join(errors)}")


def parse_xml_records(path: Path, workspace_root: Path) -> list[XmlRecord]:
    raw = path.read_bytes()
    text = decode_xml_bytes(raw, str(path))
    text_without_decl = re.sub(r"<\?xml[^>]*\?>", "", text, count=1, flags=re.I)
    try:
        root = ET.fromstring(text_without_decl)
    except ET.ParseError as exc:
        raise AvailabilityRoutingError(f"failed to parse XML {path}: {exc}") from exc
    rel = path.relative_to(workspace_root).as_posix()
    folded = f"/{rel.casefold()}/"
    side = "original" if "/original/" in folded else "quartet" if "/quartet/" in folded else "unknown"
    rows: list[XmlRecord] = []
    for index, element in enumerate(root.iter()):
        if element is root:
            continue
        attrs = {str(k): str(v) for k, v in element.attrib.items()}
        element_text = (element.text or "").strip()
        canonical = json.dumps(
            {"element": str(element.tag), "attrs": attrs, "text": element_text},
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        rows.append(
            XmlRecord(
                side=side,
                relative_path=rel,
                record_index=index,
                element=str(element.tag),
                attrs=attrs,
                text=element_text,
                record_sha256=sha256_bytes(canonical.encode("utf-8")),
            )
        )
    return rows


def selected_attributes(attrs: Mapping[str, str]) -> dict[str, str]:
    result: dict[str, str] = {}
    for key, value in attrs.items():
        if SAFE_ATTRIBUTE_RE.search(key) or any(token.casefold() in value.casefold() for token in TECHNICAL_TOKENS):
            result[key] = value
    return result


def record_blob(record: XmlRecord) -> str:
    return "\n".join([record.element, record.text, *record.attrs.keys(), *record.attrs.values()])


def matched_tokens(blob: str, tokens: Sequence[str]) -> list[str]:
    folded = blob.casefold()
    return sorted({token for token in tokens if token.casefold() in folded}, key=str.casefold)


def active_manifest_gates(project_root: Path, game_root: Path) -> tuple[dict[str, Any], list[dict[str, Any]], str]:
    active_path = project_root / ".local/reports/quartet_legacy_dlc/validated_payloads/ACTIVE.json"
    require_regular(active_path, "ACTIVE.json")
    active = json.loads(active_path.read_text(encoding="utf-8"))
    if active.get("type") != "validated_quartet_legacy_dlc_payload":
        raise AvailabilityRoutingError("unexpected ACTIVE.json type")
    if active.get("family_id") != "bkn_dry" or active.get("generation") != EXPECTED_GENERATION:
        raise AvailabilityRoutingError("ACTIVE.json is not accepted BKN generation 8")
    if active.get("members") != EXPECTED_MEMBERS:
        raise AvailabilityRoutingError("ACTIVE.json members are not exactly PC00-PC07")
    transaction = active.get("transaction", {})
    if transaction.get("all_or_none") is not True:
        raise AvailabilityRoutingError("ACTIVE.json is not all-or-none")
    artifacts = active.get("artifacts", [])
    if len(artifacts) != 2 or {x.get("target_path") for x in artifacts} != EXPECTED_TARGETS:
        raise AvailabilityRoutingError("ACTIVE.json does not declare the two canonical artifacts")

    rows: list[dict[str, Any]] = []
    observed_states: set[str] = set()
    for artifact in artifacts:
        target = str(artifact["target_path"])
        candidate = project_root / str(artifact["candidate_relative_path"])
        installed = game_root / target
        require_regular(candidate, f"candidate {target}")
        require_regular(installed, f"installed {target}")

        candidate_size = candidate.stat().st_size
        candidate_sha = sha256_file(candidate)
        installed_size = installed.stat().st_size
        installed_sha = sha256_file(installed)
        declared_candidate_size = int(artifact["candidate_size"])
        declared_candidate_sha = str(artifact["candidate_sha256"])
        declared_baseline_size = int(artifact["baseline_size"])
        declared_baseline_sha = str(artifact["baseline_sha256"])

        if candidate_size != declared_candidate_size or candidate_sha != declared_candidate_sha:
            raise AvailabilityRoutingError(f"candidate gate mismatch for {target}")

        if installed_size == candidate_size and installed_sha == candidate_sha:
            state = "candidate"
        elif installed_size == declared_baseline_size and installed_sha == declared_baseline_sha:
            state = "baseline"
        else:
            raise AvailabilityRoutingError(
                f"installed {target} matches neither accepted generation-8 candidate nor manifest baseline"
            )
        observed_states.add(state)
        rows.append({
            "target_path": target,
            "candidate_relative_path": str(artifact["candidate_relative_path"]),
            "candidate_size": candidate_size,
            "candidate_sha256": candidate_sha,
            "baseline_size_from_manifest": declared_baseline_size,
            "baseline_sha256_from_manifest": declared_baseline_sha,
            "installed_size": installed_size,
            "installed_sha256": installed_sha,
            "installed_state": state,
            "installed_matches_generation8_candidate": state == "candidate",
            "current_installation_is_clean_baseline": state == "baseline",
            "status": "passed",
        })

    if observed_states == {"candidate"}:
        installation_state = "generation8_candidates_installed"
    elif observed_states == {"baseline"}:
        installation_state = "generation8_runtime_tested_then_fully_rolled_back_to_baseline"
    else:
        raise AvailabilityRoutingError(
            "mixed installation state: generation-8 artifacts must be all candidate or all baseline"
        )
    return active, rows, installation_state


def runtime_return_gate(workstream_root: Path) -> dict[str, Any]:
    path = workstream_root / "BKN_DRY_GENERATION8_RUNTIME_VISIBILITY_RETURN.json"
    require_regular(path, "runtime visibility return")
    value = json.loads(path.read_text(encoding="utf-8"))
    if value.get("status") != "accepted_failed_at_costume_visibility_stage":
        raise AvailabilityRoutingError("runtime visibility return is not accepted")
    if value.get("tested_generation") != EXPECTED_GENERATION:
        raise AvailabilityRoutingError("runtime visibility return generation mismatch")
    if value.get("tested_members") != EXPECTED_MEMBERS:
        raise AvailabilityRoutingError("runtime visibility return member mismatch")
    if value.get("bkn_entry_visible") is not False:
        raise AvailabilityRoutingError("runtime visibility return does not record the BKN visibility failure")
    if value.get("observed_dressing_room_entries") != list(RUNTIME_LABELS):
        raise AvailabilityRoutingError("runtime visible control list changed")
    return value


def collect_workspace_records(project_root: Path) -> tuple[list[XmlRecord], list[dict[str, Any]]]:
    workspace = project_root / "titles/blue_reflection/workspace"
    if not workspace.is_dir():
        raise AvailabilityRoutingError(f"missing workspace: {workspace}")
    records: list[XmlRecord] = []
    failures: list[dict[str, Any]] = []
    for path in sorted(workspace.rglob("*.xml"), key=lambda p: p.as_posix().casefold()):
        if path.is_symlink() or not path.is_file():
            continue
        if path.stat().st_size > 128 * 1024 * 1024:
            failures.append({
                "relative_path": path.relative_to(workspace).as_posix(),
                "status": "skipped_oversize",
                "size": path.stat().st_size,
            })
            continue
        try:
            records.extend(parse_xml_records(path, workspace))
        except AvailabilityRoutingError as exc:
            failures.append({
                "relative_path": path.relative_to(workspace).as_posix(),
                "status": "parse_failed",
                "error": str(exc),
            })
    return records, failures


def analyze_records(records: Sequence[XmlRecord]) -> dict[str, list[dict[str, Any]]]:
    by_file: dict[tuple[str, str], list[XmlRecord]] = defaultdict(list)
    technical: list[dict[str, Any]] = []
    labels: list[dict[str, Any]] = []
    routing: list[dict[str, Any]] = []
    neighbors: list[dict[str, Any]] = []
    table_scores: Counter[tuple[str, str]] = Counter()
    table_reasons: dict[tuple[str, str], set[str]] = defaultdict(set)

    for record in records:
        key = (record.side, record.relative_path)
        by_file[key].append(record)
        blob = record_blob(record)
        tech_hits = matched_tokens(blob, TECHNICAL_TOKENS)
        label_hits = matched_tokens(blob, RUNTIME_LABELS)
        activation_fields = sorted(field for field in record.attrs if ACTIVATION_FIELD_RE.search(field))
        route_path = bool(ROUTING_PATH_RE.search(record.relative_path))
        safe_attrs = selected_attributes(record.attrs)

        if tech_hits:
            technical.append({
                "side": record.side,
                "table_path": record.relative_path,
                "record_index": record.record_index,
                "element": record.element,
                "record_sha256": record.record_sha256,
                "matched_tokens": tech_hits,
                "selected_attributes": safe_attrs,
                "raw_record_exported": False,
            })
            table_scores[key] += 8
            table_reasons[key].add("bkn_technical_reference")
        if label_hits:
            labels.append({
                "side": record.side,
                "table_path": record.relative_path,
                "record_index": record.record_index,
                "element": record.element,
                "record_sha256": record.record_sha256,
                "matched_runtime_labels": label_hits,
                "selected_attributes": safe_attrs,
                "raw_record_exported": False,
            })
            table_scores[key] += 6
            table_reasons[key].add("runtime_visible_label")
        if activation_fields and (tech_hits or label_hits or route_path or "pc00" in blob.casefold()):
            routing.append({
                "side": record.side,
                "table_path": record.relative_path,
                "record_index": record.record_index,
                "element": record.element,
                "record_sha256": record.record_sha256,
                "activation_or_routing_fields": activation_fields,
                "matched_technical_tokens": tech_hits,
                "matched_runtime_labels": label_hits,
                "selected_attributes": safe_attrs,
                "semantics_proven": False,
            })
            table_scores[key] += 4 + len(activation_fields)
            table_reasons[key].add("activation_or_routing_field")
        if route_path:
            table_scores[key] += 1
            table_reasons[key].add("routing_related_path")

    for key, file_records in by_file.items():
        indices = [i for i, record in enumerate(file_records) if matched_tokens(record_blob(record), TECHNICAL_TOKENS)]
        for center in indices:
            for offset in range(-4, 5):
                pos = center + offset
                if pos < 0 or pos >= len(file_records):
                    continue
                record = file_records[pos]
                neighbors.append({
                    "side": record.side,
                    "table_path": record.relative_path,
                    "bkn_record_position": center,
                    "neighbor_offset": offset,
                    "record_index": record.record_index,
                    "element": record.element,
                    "record_sha256": record.record_sha256,
                    "selected_attributes": selected_attributes(record.attrs),
                    "contains_bkn_token": bool(matched_tokens(record_blob(record), TECHNICAL_TOKENS)),
                    "contains_runtime_visible_label": bool(matched_tokens(record_blob(record), RUNTIME_LABELS)),
                    "raw_record_exported": False,
                })

    ranking = [
        {
            "side": side,
            "table_path": path,
            "score": score,
            "reasons": sorted(table_reasons[(side, path)]),
            "classification": "high_priority" if score >= 12 else "candidate" if score >= 5 else "context",
        }
        for (side, path), score in table_scores.most_common()
    ]
    return {
        "technical": technical,
        "labels": labels,
        "routing": routing,
        "neighbors": neighbors,
        "ranking": ranking,
    }


def collect_prior_evidence_hits(project_root: Path, output_dir: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    roots = [
        project_root / ".local/reports/quartet_legacy_dlc",
        project_root / "workstreams/quartet_legacy_dlc",
    ]
    hits: list[dict[str, Any]] = []
    indexed: list[dict[str, Any]] = []
    seen_paths: set[Path] = set()
    for root in roots:
        if not root.is_dir():
            continue
        for path in sorted(root.rglob("*"), key=lambda p: p.as_posix().casefold()):
            if path in seen_paths or path.is_symlink() or not path.is_file():
                continue
            seen_paths.add(path)
            try:
                path.resolve().relative_to(output_dir.resolve())
                continue
            except ValueError:
                pass
            if path.suffix.casefold() not in ALLOWED_METADATA_SUFFIXES:
                continue
            size = path.stat().st_size
            if size > 32 * 1024 * 1024:
                continue
            rel = path.relative_to(project_root).as_posix()
            indexed.append({
                "relative_path": rel,
                "size": size,
                "sha256": sha256_file(path),
            })
            try:
                text = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            for line_no, line in enumerate(text.splitlines(), start=1):
                folded = line.casefold()
                matched = sorted({term for term in PRIOR_TERMS if term in folded})
                if not matched:
                    continue
                hits.append({
                    "relative_path": rel,
                    "line": line_no,
                    "matched_terms": matched,
                    "line_excerpt": line[:600],
                    "line_sha256": sha256_bytes(line.encode("utf-8", "replace")),
                })
                if len(hits) >= 15000:
                    return hits, indexed
    return hits, indexed


def build_gaps(runtime_return: Mapping[str, Any], analysis: Mapping[str, Sequence[Mapping[str, Any]]], installation_state: str) -> list[dict[str, Any]]:
    routing_rows = analysis["routing"]
    label_rows = analysis["labels"]
    technical_rows = analysis["technical"]
    direct_activation = [
        row for row in routing_rows
        if row.get("matched_technical_tokens")
    ]
    inventory_like = [
        row for row in routing_rows
        if re.search(r"(?:inventory|item|costume|coschange)", str(row.get("table_path", "")), re.I)
    ]
    ui_like = [
        row for row in analysis["ranking"]
        if re.search(r"(?:layout|ui|menu|costume|dress)", str(row.get("table_path", "")), re.I)
    ]
    return [
        {
            "category": "generation8_payload_runtime_state",
            "status": "pass",
            "evidence": (
                "PACK10_02 and PACK12 still match ACTIVE generation-8 candidates"
                if installation_state == "generation8_candidates_installed"
                else "runtime-tested generation 8 was fully rolled back; installed PACK10_02 and PACK12 match ACTIVE manifest baselines"
            ),
            "installation_state": installation_state,
            "build_authorized": False,
        },
        {
            "category": "asset_and_charabase_structure",
            "status": "pass_structurally_only",
            "evidence": runtime_return["accepted_interpretation"],
            "build_authorized": False,
        },
        {
            "category": "dressing_room_visibility",
            "status": "fail",
            "evidence": runtime_return["observed_dressing_room_entries"],
            "build_authorized": False,
        },
        {
            "category": "runtime_visible_positive_control_mapping",
            "status": "candidate_rows_found" if label_rows else "unresolved",
            "evidence_count": len(label_rows),
            "build_authorized": False,
        },
        {
            "category": "direct_bkn_unlock_release_entitlement_fields",
            "status": "candidate_rows_found" if direct_activation else "unresolved",
            "evidence_count": len(direct_activation),
            "semantics_proven": False,
            "build_authorized": False,
        },
        {
            "category": "costume_inventory_or_selection_registry",
            "status": "candidate_rows_found" if inventory_like else "unresolved",
            "evidence_count": len(inventory_like),
            "semantics_proven": False,
            "build_authorized": False,
        },
        {
            "category": "ui_or_dressing_room_registry",
            "status": "candidate_tables_found" if ui_like else "unresolved",
            "evidence_count": len(ui_like),
            "semantics_proven": False,
            "build_authorized": False,
        },
        {
            "category": "bkn_technical_records",
            "status": "present",
            "evidence_count": len(technical_rows),
            "runtime_availability_proven": False,
            "build_authorized": False,
        },
        {
            "category": "next_payload_generation",
            "status": "blocked_pending_exact_availability_routing_closure",
            "pc08_build_allowed": False,
            "core_change_required": False,
            "build_authorized": False,
        },
    ]


def create_report_manifest(output_dir: Path) -> None:
    rows: list[dict[str, Any]] = []
    for path in sorted(output_dir.rglob("*"), key=lambda p: p.as_posix().casefold()):
        if path.is_symlink():
            raise AvailabilityRoutingError(f"symlink in report: {path}")
        if not path.is_file() or path.name == "REPORT_MANIFEST.json":
            continue
        if path.suffix.casefold() in FORBIDDEN_OUTPUT_SUFFIXES:
            raise AvailabilityRoutingError(f"forbidden payload in report: {path}")
        rows.append({
            "relative_path": path.relative_to(output_dir).as_posix(),
            "size": path.stat().st_size,
            "sha256": sha256_file(path),
        })
    write_json(output_dir / "REPORT_MANIFEST.json", {
        "type": "br_quartet_legacy_dlc_bkn_dry_generation8_availability_routing_report_manifest",
        "format_version": 1,
        "files": rows,
    })


def run(project_root: Path, original_root: Path, game_root: Path, output_dir: Path) -> dict[str, Any]:
    workstream_root = project_root / "workstreams/quartet_legacy_dlc"
    version_path = workstream_root / "VERSION"
    require_regular(version_path, "workstream VERSION")
    version = version_path.read_text(encoding="utf-8").strip()
    if version != EXPECTED_WORKSTREAM_VERSION:
        raise AvailabilityRoutingError(
            f"quartet_legacy_dlc {EXPECTED_WORKSTREAM_VERSION} is required, got {version}"
        )
    if not original_root.is_dir():
        raise AvailabilityRoutingError(f"missing original game root: {original_root}")
    if not game_root.is_dir():
        raise AvailabilityRoutingError(f"missing Quartet game root: {game_root}")
    if output_dir.exists():
        shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    runtime_return = runtime_return_gate(workstream_root)
    active, install_gates, installation_state = active_manifest_gates(project_root, game_root)
    game_stats_before = {
        row["target_path"]: (game_root / row["target_path"]).stat().st_mtime_ns
        for row in install_gates
    }

    records, parse_failures = collect_workspace_records(project_root)
    analysis = analyze_records(records)
    prior_hits, prior_index = collect_prior_evidence_hits(project_root, output_dir)
    gaps = build_gaps(runtime_return, analysis, installation_state)

    write_json(output_dir / "BKN_DRY_GENERATION8_RUNTIME_VISIBILITY_RETURN.json", runtime_return)
    write_json(output_dir / "ACTIVE_GENERATION8.json", active)
    write_tsv(output_dir / "DLC_BKN_GENERATION8_RUNTIME_INSTALLATION_GATES.tsv", install_gates)
    write_tsv(output_dir / "DLC_BKN_RUNTIME_VISIBLE_LABEL_HITS.tsv", analysis["labels"])
    write_tsv(output_dir / "DLC_BKN_TECHNICAL_REFERENCE_HITS.tsv", analysis["technical"])
    write_tsv(output_dir / "DLC_BKN_ROUTING_FIELD_CANDIDATES.tsv", analysis["routing"])
    write_tsv(output_dir / "DLC_BKN_ADJACENT_TABLE_RECORDS.tsv", analysis["neighbors"])
    write_tsv(output_dir / "DLC_BKN_ROUTING_TABLE_RANKING.tsv", analysis["ranking"])
    write_tsv(output_dir / "DLC_BKN_WORKSPACE_XML_PARSE_STATUS.tsv", parse_failures)
    write_tsv(output_dir / "DLC_BKN_PRIOR_EVIDENCE_HITS.tsv", prior_hits)
    write_tsv(output_dir / "DLC_BKN_PRIOR_EVIDENCE_INDEX.tsv", prior_index)
    write_tsv(output_dir / "DLC_BKN_AVAILABILITY_ROUTING_GAPS.tsv", gaps)

    game_stats_after = {
        row["target_path"]: (game_root / row["target_path"]).stat().st_mtime_ns
        for row in install_gates
    }
    if game_stats_before != game_stats_after:
        raise AvailabilityRoutingError("game PAK metadata changed during read-only audit")

    summary = {
        "type": "br_quartet_legacy_dlc_bkn_dry_generation8_availability_routing_audit",
        "format_version": FORMAT_VERSION,
        "tool_version": TOOL_VERSION,
        "status": "runtime_visibility_failed_exact_routing_closure_required",
        "workstream_version": version,
        "family_id": "bkn_dry",
        "generation": EXPECTED_GENERATION,
        "members": EXPECTED_MEMBERS,
        "runtime_validation": {
            "status": "failed_at_costume_visibility_stage",
            "commit": "pass",
            "game_boot": "pass",
            "translation": "pass",
            "unburger_marker": "pass",
            "bkn_visible": False,
            "visible_positive_controls": list(RUNTIME_LABELS),
        },
        "installation": {
            "state": installation_state,
            "artifact_count": len(install_gates),
            "clean_baseline": installation_state == "generation8_runtime_tested_then_fully_rolled_back_to_baseline",
            "generation8_candidates_currently_installed": installation_state == "generation8_candidates_installed",
            "runtime_test_and_visibility_result_preserved": True,
            "game_files_written_by_this_audit": False,
        },
        "workspace_scan": {
            "xml_records": len(records),
            "parse_failures_or_skips": len(parse_failures),
            "bkn_technical_reference_hits": len(analysis["technical"]),
            "runtime_visible_label_hits": len(analysis["labels"]),
            "routing_field_candidates": len(analysis["routing"]),
            "ranked_tables": len(analysis["ranking"]),
        },
        "prior_evidence": {
            "indexed_metadata_files": len(prior_index),
            "matching_lines": len(prior_hits),
        },
        "conclusion": {
            "assets_and_charabase_structurally_valid": True,
            "availability_ui_unlock_routing_complete": False,
            "current_payload_profile_complete": False,
            "next_generation_build_allowed": False,
            "pc08_build_allowed": False,
            "core_change_required": False,
            "required_next_action": "review ranked table and record candidates, identify exact availability-routing closure, then build a new DLC payload generation containing that closure",
        },
        "authorization": {
            "prepare": False,
            "commit": False,
            "install": False,
            "runtime_validation": False,
            "active_manifest_write": False,
            "candidate_build": False,
            "pc08_build": False,
            "wet_bkn": False,
            "core_modification": False,
            "translation_modification": False,
            "restoration_modification": False,
            "git_modification": False,
        },
        "raw_assets_exported": False,
        "game_files_modified": False,
    }
    write_json(output_dir / "SUMMARY.json", summary)
    create_report_manifest(output_dir)
    return summary


def parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path, required=True)
    parser.add_argument("--original-dir", type=Path, required=True)
    parser.add_argument("--game-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    try:
        summary = run(
            args.project_root.resolve(),
            args.original_dir.resolve(),
            args.game_dir.resolve(),
            args.output_dir.resolve(),
        )
    except AvailabilityRoutingError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
