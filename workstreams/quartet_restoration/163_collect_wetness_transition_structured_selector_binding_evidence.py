#!/usr/bin/env python3
"""Stage 163: read-only wetness transition structured-selector binding audit.

This stage is motivated by the observation that Change Wetness can re-resolve a
correct character/model state even when a dry wardrobe state is broken.  It does
not assume that the wetness handler controls transparency.  Instead it searches
bounded structured game tables for exact school dry/wet asset tokens and exact
cross-references that could later serve as runtime trace anchors.

No proprietary XML payloads are exported.  Evidence contains only exact token
labels already present in the known asset namespace, structural locations,
field names, hashes, numeric literals, counts and classifications.
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
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

TOOL_VERSION = "0.1.84"
REPORT_DIR = "wetness_transition_structured_selector_binding_evidence"
REPORT_NAME = "BR_quartet_restoration_wetness_transition_structured_selector_binding_evidence.tar.zst"
STAGE129_REPORT = "BR_quartet_restoration_structured_selector_water_dependency_evidence.tar.zst"
STAGE129_SHA256 = "d695940c5e326cb1f351dd87102a57002c48d604c212f96a3a708af053e6ff34"
STAGE129_SUMMARY_SHA256 = "286ba6607b1d87ea4807174a968b8267c2d49d1c3b80f6f91c5c65efa60731be"
STAGE129_ROOT = "structured_selector_water_dependency_evidence"
CORE_OBSERVATION_FILE = "WETNESS_RUNTIME_OBSERVATION_RETURN_20260807.json"
STAGE162_PROFILE_ID = "fast_test_pc00_scl_w_school_entry23_target_native_alpha43_568fc2f9a095"
STAGE162_ACTIVATION_SHA256 = "b7638a714e5b1e035f7541435980e1f2f9e6bfc3e305ccee17560dfec98e468f"
STAGE162_ROLLBACK_SHA256 = "3720f8c1ac589456ad491816cf4ce8ace894e383ce44c51e1b65242cd96ec89c"

STRUCTURED_PATHS = (
    "saves/costume/coschangechara.xml",
    "saves/costume/costume.xml",
    "saves/ez_eff_player/costume_change.xml",
    "saves/chara/chara.xml",
    "saves/chara/charabase.xml",
    "saves/chara/charapartsmodel.xml",
)
CHARACTERS = tuple(f"pc{i:02d}" for i in range(15))
STATES = ("scl", "scl_w")
TOKEN_RE = re.compile(r"(?i)(pc(?:0[0-9]|1[0-4])_scl(?:_w)?)")
PURE_NUMERIC_RE = re.compile(r"^(?:[-+]?\d+|0x[0-9a-fA-F]+)$")


class Stage163Error(RuntimeError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise Stage163Error(message)


def version_tuple(value: str) -> tuple[int, ...]:
    try:
        return tuple(int(x) for x in value.strip().split("."))
    except ValueError as exc:
        raise Stage163Error(f"invalid version: {value}") from exc


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(8 * 1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def hash_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8", errors="replace")).hexdigest()


def write_tsv(path: Path, fields: Sequence[str], rows: Iterable[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(fields), delimiter="\t", lineterminator="\n", extrasaction="ignore")
        w.writeheader()
        for row in rows:
            w.writerow({k: row.get(k, "") for k in fields})


def make_archive(source: Path, output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    tmp = output.with_name(output.name + ".tmp")
    tmp.unlink(missing_ok=True)
    cp = subprocess.run(["tar", "--zstd", "-cf", str(tmp), "-C", str(source.parent), source.name], capture_output=True, text=True)
    require(cp.returncode == 0, cp.stderr.strip() or "archive creation failed")
    os.replace(tmp, output)


def load_stage129(project_root: Path):
    path = project_root / "workstreams/quartet_restoration/129_collect_structured_selector_water_dependency_evidence.py"
    require(path.is_file(), f"missing stage129 helper: {path}")
    spec = importlib.util.spec_from_file_location("stage163_stage129", path)
    require(spec is not None and spec.loader is not None, "cannot load stage129 helper")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def load_inventory(project_root: Path, group: str) -> dict[tuple[str, str], tuple[str, dict[str, Any]]]:
    root = project_root / ".local/reports/quartet_restoration/inventories"
    out: dict[tuple[str, str], tuple[str, dict[str, Any]]] = {}
    for side in ("source", "target"):
        p = root / f"{group}.{side}.json"
        require(p.is_file(), f"missing inventory: {p}")
        data = json.loads(p.read_text(encoding="utf-8"))
        require(data.get("archive_group") == group, f"inventory group drift: {p}")
        for e in data.get("files", []):
            n = str(e.get("normalized_path", "")).casefold()
            if n:
                out[(side, n)] = (group, dict(e))
    return out


def decode_text(payload: bytes) -> tuple[str, str]:
    for enc in ("utf-8-sig", "utf-8", "cp932"):
        try:
            return payload.decode(enc), enc
        except UnicodeDecodeError:
            pass
    return payload.decode("latin-1"), "latin-1"


def element_records(text: str) -> tuple[str, list[dict[str, Any]]]:
    try:
        root = ET.fromstring(text)
    except ET.ParseError:
        return "parse_error", []
    rows: list[dict[str, Any]] = []
    stack: list[tuple[ET.Element, str]] = [(root, f"/{root.tag}[1]")]
    while stack:
        el, xpath = stack.pop()
        fields: list[tuple[str, str]] = [("text", el.text or "")]
        fields.extend((f"attr:{k}", v) for k, v in el.attrib.items())
        token_hits: list[tuple[str, str, str]] = []
        numeric_fields: list[tuple[str, str]] = []
        for field, value in fields:
            for m in TOKEN_RE.finditer(value):
                token_hits.append((m.group(1).casefold(), field, value))
            stripped = value.strip()
            if PURE_NUMERIC_RE.fullmatch(stripped):
                numeric_fields.append((field, stripped))
        rows.append({
            "tag": el.tag,
            "xpath": xpath,
            "fields": fields,
            "token_hits": token_hits,
            "numeric_fields": numeric_fields,
            "attribute_names": tuple(sorted(el.attrib)),
        })
        children = list(el)
        for idx in range(len(children) - 1, -1, -1):
            child = children[idx]
            stack.append((child, f"{xpath}/{child.tag}[{idx+1}]"))
    return "ok", rows


def token_character_state(token: str) -> tuple[str, str]:
    token = token.casefold()
    require(TOKEN_RE.fullmatch(token) is not None, f"unexpected token: {token}")
    character = token[:4]
    state = "scl_w" if token.endswith("_scl_w") else "scl"
    return character, state


def validate_prerequisites(project_root: Path, report_root: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    stage129_archive = report_root / STAGE129_REPORT
    stage129_summary_path = report_root / STAGE129_ROOT / "SUMMARY.json"
    require(stage129_archive.is_file(), f"missing stage129 report: {stage129_archive}")
    require(sha256_file(stage129_archive) == STAGE129_SHA256, "stage129 report SHA-256 drift")
    require(stage129_summary_path.is_file(), f"missing stage129 summary: {stage129_summary_path}")
    require(sha256_file(stage129_summary_path) == STAGE129_SUMMARY_SHA256, "stage129 summary SHA-256 drift")
    stage129_summary = json.loads(stage129_summary_path.read_text(encoding="utf-8"))
    require(stage129_summary.get("status") == "structured_selector_and_water_dependency_scan_complete_bounded_channels_non_authorizing_no_semantics_no_write", "unexpected stage129 status")

    obs_path = project_root / "workstreams/quartet_restoration" / CORE_OBSERVATION_FILE
    require(obs_path.is_file(), f"missing core observation return: {obs_path}")
    obs = json.loads(obs_path.read_text(encoding="utf-8"))
    require(obs.get("source_scope") == "observation_only", "core wetness observation scope drift")
    require(obs.get("generation10_v2_dependency_forbidden") is True, "Generation 10 v2 dependency gate drift")
    return stage129_summary, obs


def build_report(
    project_root: Path,
    *,
    report_root: Path | None = None,
    output_report_root: Path | None = None,
    workspace_root: Path | None = None,
    original_root: Path | None = None,
    quartet_root: Path | None = None,
    gust_pak_path: Path | None = None,
    fixture_root: Path | None = None,
    timeout_seconds: int = 1800,
    verify_payload_hashes: bool = True,
    create_archive: bool = True,
    skip_prerequisite_hashes_for_fixture: bool = False,
) -> tuple[Path | None, dict[str, Any]]:
    project_root = project_root.resolve()
    workstream = project_root / "workstreams/quartet_restoration"
    version = (workstream / "VERSION").read_text(encoding="utf-8").strip()
    require(version_tuple(version) >= version_tuple(TOOL_VERSION), f"expected quartet_restoration {TOOL_VERSION} or newer, found {version}")
    report_root = (report_root or project_root / ".local/reports/quartet_restoration").resolve()
    output_report_root = (output_report_root or report_root).resolve()
    workspace_root = (workspace_root or project_root / ".local/build/quartet_restoration").resolve()
    output = output_report_root / REPORT_DIR
    if output.exists():
        shutil.rmtree(output)
    output.mkdir(parents=True)

    if skip_prerequisite_hashes_for_fixture:
        stage129_summary = {"status": "fixture"}
        obs = {"source_scope": "observation_only", "generation10_v2_dependency_forbidden": True}
    else:
        stage129_summary, obs = validate_prerequisites(project_root, report_root)

    stage129 = load_stage129(project_root)
    inventories = {"br1_language": load_inventory(project_root, "br1_language")}
    requirements: list[tuple[str, str, str]] = []
    for path in STRUCTURED_PATHS:
        for side in ("source", "target"):
            if (side, path.casefold()) in inventories["br1_language"]:
                requirements.append(("br1_language", side, path))
    require(requirements, "no structured table requirements resolved")

    br = stage129.load_br_tool(project_root)
    resolved, extraction_rows = stage129.ensure_inputs(
        project_root=project_root,
        workspace_root=workspace_root,
        inventory_maps=inventories,
        requirements=requirements,
        original_root=original_root,
        quartet_root=quartet_root,
        gust_pak_path=gust_pak_path,
        br=br,
        timeout_seconds=timeout_seconds,
        fixture_root=fixture_root,
    )

    table_rows: list[dict[str, Any]] = []
    token_rows: list[dict[str, Any]] = []
    numeric_seed_rows: list[dict[str, Any]] = []
    parsed_elements: dict[tuple[str, str], list[dict[str, Any]]] = {}

    for group, side, normalized in requirements:
        p = resolved[(group, side, normalized)]
        payload = p.read_bytes()
        if fixture_root is None and verify_payload_hashes:
            _, entry = inventories[group][(side, normalized.casefold())]
            require(sha256_file(p) == str(entry["sha256"]), f"payload hash drift: {side} {normalized}")
        text, encoding = decode_text(payload)
        parse_status, elements = element_records(text)
        parsed_elements[(side, normalized)] = elements
        table_rows.append({
            "side": side,
            "normalized_path": normalized,
            "encoding": encoding,
            "parse_status": parse_status,
            "element_rows": len(elements),
            "payload_size": len(payload),
            "payload_sha256": hashlib.sha256(payload).hexdigest(),
            "payload_in_evidence": False,
        })
        for el in elements:
            if not el["token_hits"]:
                continue
            element_tokens = sorted({hit[0] for hit in el["token_hits"]})
            dry = sorted(t for t in element_tokens if not t.endswith("_scl_w"))
            wet = sorted(t for t in element_tokens if t.endswith("_scl_w"))
            for token, field, full_value in el["token_hits"]:
                character, state = token_character_state(token)
                token_rows.append({
                    "side": side,
                    "normalized_path": normalized,
                    "character_id": character,
                    "state_token": state,
                    "exact_token": token,
                    "xpath": el["xpath"],
                    "tag": el["tag"],
                    "field": field,
                    "value_length": len(full_value),
                    "value_sha256": hash_text(full_value),
                    "element_attribute_names": ";".join(el["attribute_names"]),
                    "same_element_dry_token_rows": len(dry),
                    "same_element_wet_token_rows": len(wet),
                    "dry_wet_colocated": bool(dry and wet),
                    "raw_value_in_evidence": False,
                })
            for field, literal in el["numeric_fields"]:
                numeric_seed_rows.append({
                    "side": side,
                    "normalized_path": normalized,
                    "xpath": el["xpath"],
                    "tag": el["tag"],
                    "field": field,
                    "numeric_literal": literal,
                    "element_tokens": ";".join(element_tokens),
                })

    # Exact numeric cross-reference scan.  Only literals originating in elements
    # that already contain a known school dry/wet token are used as seeds.
    # Trivial/common literals are excluded: a useful runtime anchor must be
    # discriminating enough to avoid the combinatorial noise of flags such as
    # 0/1/-1.  Occurrence counts are computed separately per side.
    numeric_occurrence_counts: Counter[tuple[str, str]] = Counter()
    for (scan_side, _scan_path), elements in parsed_elements.items():
        for el in elements:
            for _field, value in el["fields"]:
                stripped = value.strip()
                if PURE_NUMERIC_RE.fullmatch(stripped):
                    numeric_occurrence_counts[(scan_side, stripped)] += 1
    for row in numeric_seed_rows:
        count = numeric_occurrence_counts[(row["side"], row["numeric_literal"])]
        row["side_occurrence_rows"] = count
        row["cross_reference_eligible"] = row["numeric_literal"] not in {"-1", "0", "+0", "1", "+1"} and 2 <= count <= 32
    seed_literals = sorted({row["numeric_literal"] for row in numeric_seed_rows if row["cross_reference_eligible"]})
    xref_rows: list[dict[str, Any]] = []
    for (side, normalized), elements in parsed_elements.items():
        for el in elements:
            for field, value in el["fields"]:
                stripped = value.strip()
                if stripped not in seed_literals:
                    continue
                origin_matches = [r for r in numeric_seed_rows if r["numeric_literal"] == stripped and r["cross_reference_eligible"]]
                if not origin_matches:
                    continue
                direct_tokens = sorted({hit[0] for hit in el["token_hits"]})
                for origin in origin_matches:
                    same_origin = side == origin["side"] and normalized == origin["normalized_path"] and el["xpath"] == origin["xpath"] and field == origin["field"]
                    if same_origin:
                        continue
                    xref_rows.append({
                        "seed_side": origin["side"],
                        "seed_path": origin["normalized_path"],
                        "seed_xpath": origin["xpath"],
                        "seed_field": origin["field"],
                        "seed_tokens": origin["element_tokens"],
                        "numeric_literal": stripped,
                        "hit_side": side,
                        "hit_path": normalized,
                        "hit_xpath": el["xpath"],
                        "hit_tag": el["tag"],
                        "hit_field": field,
                        "hit_element_tokens": ";".join(direct_tokens),
                        "independent_table_hit": normalized != origin["normalized_path"],
                        "independent_element_hit": normalized != origin["normalized_path"] or el["xpath"] != origin["xpath"],
                    })

    pair_rows: list[dict[str, Any]] = []
    for side in ("source", "target"):
        for character in CHARACTERS:
            dry_token = f"{character}_scl"
            wet_token = f"{character}_scl_w"
            dry_rows = [r for r in token_rows if r["side"] == side and r["exact_token"] == dry_token]
            wet_rows = [r for r in token_rows if r["side"] == side and r["exact_token"] == wet_token]
            dry_paths = sorted({r["normalized_path"] for r in dry_rows})
            wet_paths = sorted({r["normalized_path"] for r in wet_rows})
            colocated = sum(1 for r in dry_rows + wet_rows if r["dry_wet_colocated"])
            xrefs = [r for r in xref_rows if r["seed_side"] == side and character in r["seed_tokens"]]
            pair_rows.append({
                "side": side,
                "character_id": character,
                "dry_token": dry_token,
                "wet_token": wet_token,
                "dry_exact_hit_rows": len(dry_rows),
                "wet_exact_hit_rows": len(wet_rows),
                "dry_table_rows": len(dry_paths),
                "wet_table_rows": len(wet_paths),
                "dry_paths": ";".join(dry_paths),
                "wet_paths": ";".join(wet_paths),
                "same_element_colocation_rows": colocated,
                "numeric_cross_reference_rows": len(xrefs),
                "independent_numeric_cross_reference_rows": sum(1 for r in xrefs if r["independent_table_hit"]),
            })

    # Bounded candidate: an exact target dry/wet token pair plus at least one
    # independent numeric cross-reference.  This is a trace anchor, not semantic
    # proof and not a write target.
    candidate_rows: list[dict[str, Any]] = []
    for pair in pair_rows:
        if pair["side"] != "target":
            continue
        if pair["dry_exact_hit_rows"] and pair["wet_exact_hit_rows"] and pair["independent_numeric_cross_reference_rows"]:
            candidate_rows.append({
                "character_id": pair["character_id"],
                "dry_token": pair["dry_token"],
                "wet_token": pair["wet_token"],
                "dry_exact_hit_rows": pair["dry_exact_hit_rows"],
                "wet_exact_hit_rows": pair["wet_exact_hit_rows"],
                "independent_numeric_cross_reference_rows": pair["independent_numeric_cross_reference_rows"],
                "classification": "bounded_structured_runtime_trace_anchor_not_selector_semantics",
                "runtime_trace_priority": "highest" if pair["character_id"] == "pc00" else "supporting_control",
                "selector_binding_confirmed": False,
                "transparency_semantics_confirmed": False,
                "write_authorized": False,
            })

    summary = {
        "format_version": 1,
        "type": "br_quartet_restoration_wetness_transition_structured_selector_binding_evidence_summary",
        "tool_version": TOOL_VERSION,
        "stage": 163,
        "status": "read_only_structured_dry_wet_selector_anchor_audit_complete_no_write",
        "stage129_report_sha256": STAGE129_SHA256,
        "core_observation_scope": obs.get("source_scope", "observation_only"),
        "stage162_profile_id": STAGE162_PROFILE_ID,
        "stage162_activation_evidence_sha256": STAGE162_ACTIVATION_SHA256,
        "stage162_rollback_evidence_sha256": STAGE162_ROLLBACK_SHA256,
        "stage162_entry43_transparency_runtime_result": "negative_no_visible_difference",
        "structured_table_rows": len(table_rows),
        "exact_school_dry_wet_token_hit_rows": len(token_rows),
        "numeric_seed_rows": len(numeric_seed_rows),
        "numeric_cross_reference_rows": len(xref_rows),
        "independent_numeric_cross_reference_rows": sum(1 for r in xref_rows if r["independent_table_hit"]),
        "pair_matrix_rows": len(pair_rows),
        "target_bounded_trace_anchor_rows": len(candidate_rows),
        "pc00_target_bounded_trace_anchor_rows": sum(1 for r in candidate_rows if r["character_id"] == "pc00"),
        "generation10_v2_dependency_forbidden": True,
        "selector_binding_confirmed": False,
        "wet_transparency_mechanism_confirmed": False,
        "runtime_trace_performed": False,
        "write_authorized_rows": 0,
        "installed_game_modified": False,
        "pak_built_or_repacked": False,
        "proprietary_payloads_in_report": False,
        "next_action": (
            "If pc00 obtains bounded structured trace anchors, use those exact tokens/IDs as the observation set for a read-only native dry->wet runtime trace. "
            "If no pc00 structured anchor survives, proceed to a process/render-state trace without inventing another texture/material write candidate."
        ),
    }

    write_tsv(output / "STRUCTURED_TABLES.tsv",
              ["side", "normalized_path", "encoding", "parse_status", "element_rows", "payload_size", "payload_sha256", "payload_in_evidence"], table_rows)
    write_tsv(output / "SCHOOL_DRY_WET_TOKEN_HITS.tsv",
              ["side", "normalized_path", "character_id", "state_token", "exact_token", "xpath", "tag", "field", "value_length", "value_sha256", "element_attribute_names", "same_element_dry_token_rows", "same_element_wet_token_rows", "dry_wet_colocated", "raw_value_in_evidence"], token_rows)
    write_tsv(output / "TOKEN_ELEMENT_NUMERIC_SEEDS.tsv",
              ["side", "normalized_path", "xpath", "tag", "field", "numeric_literal", "element_tokens", "side_occurrence_rows", "cross_reference_eligible"], numeric_seed_rows)
    write_tsv(output / "NUMERIC_CROSS_REFERENCES.tsv",
              ["seed_side", "seed_path", "seed_xpath", "seed_field", "seed_tokens", "numeric_literal", "hit_side", "hit_path", "hit_xpath", "hit_tag", "hit_field", "hit_element_tokens", "independent_table_hit", "independent_element_hit"], xref_rows)
    write_tsv(output / "DRY_WET_PAIR_MATRIX.tsv",
              ["side", "character_id", "dry_token", "wet_token", "dry_exact_hit_rows", "wet_exact_hit_rows", "dry_table_rows", "wet_table_rows", "dry_paths", "wet_paths", "same_element_colocation_rows", "numeric_cross_reference_rows", "independent_numeric_cross_reference_rows"], pair_rows)
    write_tsv(output / "BOUNDED_RUNTIME_TRACE_ANCHORS.tsv",
              ["character_id", "dry_token", "wet_token", "dry_exact_hit_rows", "wet_exact_hit_rows", "independent_numeric_cross_reference_rows", "classification", "runtime_trace_priority", "selector_binding_confirmed", "transparency_semantics_confirmed", "write_authorized"], candidate_rows)
    write_tsv(output / "EXTRACTION_INPUTS.tsv",
              ["group", "side", "archive_relative", "required_path_rows", "archive_size", "archive_sha256", "gust_pak_sha256", "cache_action"], extraction_rows)
    (output / "SUMMARY.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    archive: Path | None = None
    if create_archive:
        archive = output_report_root / REPORT_NAME
        make_archive(output, archive)
    return archive, summary


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("project_root", type=Path)
    ap.add_argument("--report-root", type=Path)
    ap.add_argument("--output-report-root", type=Path)
    ap.add_argument("--workspace-root", type=Path)
    ap.add_argument("--original-root", type=Path)
    ap.add_argument("--quartet-root", type=Path)
    ap.add_argument("--gust-pak", type=Path)
    ap.add_argument("--timeout-seconds", type=int, default=1800)
    ap.add_argument("--no-verify-payload-hashes", action="store_true")
    ap.add_argument("--no-archive", action="store_true")
    args = ap.parse_args()
    archive, summary = build_report(
        args.project_root,
        report_root=args.report_root,
        output_report_root=args.output_report_root,
        workspace_root=args.workspace_root,
        original_root=args.original_root,
        quartet_root=args.quartet_root,
        gust_pak_path=args.gust_pak,
        timeout_seconds=args.timeout_seconds,
        verify_payload_hashes=not args.no_verify_payload_hashes,
        create_archive=not args.no_archive,
    )
    print(json.dumps({"archive": str(archive) if archive else None, "summary": summary}, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
