#!/usr/bin/env python3
"""Read-only structured selector and water dependency collector.

Stage 129 consumes the verified stage-128 audit, rehydrates only bounded
structured XML and character OID inputs when needed, and emits metadata only.
It does not assign visual/censorship semantics and authorizes no write.
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
from pathlib import Path, PurePosixPath
from typing import Any, Iterable, Mapping, Sequence

TOOL_VERSION = "0.1.47"
REPORT_DIR = "structured_selector_water_dependency_evidence"
REPORT_NAME = "BR_quartet_restoration_structured_selector_water_dependency_evidence.tar.zst"
STAGE128_NAME = "BR_quartet_restoration_coverage_selector_standalone_render_path_audit_evidence.tar.zst"
STAGE128_ROOT = "coverage_selector_standalone_render_path_audit"
STAGE128_SHA256 = "4fe853bb18dc5980b9dd4f5868852d2d87065bff145511d61b7bc22d552a02c8"
STAGE128_SUMMARY_SHA256 = "ded81e006711c51c11d135c14323c52f36034a29effd8403fa100f4a3ae83e05"
DXBC_REPORT_NAME = "BR_quartet_restoration_dxbc_reflection_evidence.tar.zst"
DXBC_REPORT_SHA256 = "57cc49463d067120adc8f9fee63fcdb269615f0be001aaee7ae9011db199f37a"
DXBC_SUMMARY_SHA256 = "c5c645b5e69dd51b1c068b412d4938ba70376605d3fb2965163831ba8eee3d36"
MAX_EARC_BYTES = 256 * 1024 * 1024
FORBIDDEN_EXTENSIONS = (".pak", ".g1e", ".g1em", ".g1m", ".g1s", ".g1t", ".elixir", ".elixir.gz", ".ebd", ".ebm")

STRUCTURED_PATHS = (
    "saves/costume/coschangechara.xml",
    "saves/costume/costume.xml",
    "saves/ez_eff_player/costume_change.xml",
    "saves/chara/chara.xml",
    "saves/chara/charabase.xml",
    "saves/chara/charapartsmodel.xml",
    "saves/field/s86_s_shower_room_01.xml",
    "saves/field/s89_s_hinako_bath_room_01.xml",
    "saves/fieldmap/caustics_param.xml",
)
WATER_SHADER_PATHS = ("data/x64/shader/cwater.g1s", "data/x64/shader/cwater2.g1s")
CAUSTICS_TEXTURE_PATH = "data/x64/shader/texture/caustics.g1t"


class CollectorError(RuntimeError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise CollectorError(message)


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


def read_tsv(path: Path) -> list[dict[str, str]]:
    require(path.is_file(), f"missing TSV: {path}")
    with path.open(encoding="utf-8", newline="") as handle:
        return [dict(row) for row in csv.DictReader(handle, delimiter="\t")]


def write_tsv(path: Path, fields: Sequence[str], rows: Iterable[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(fields), delimiter="\t", lineterminator="\n", extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fields})


def atomic_json(path: Path, value: Mapping[str, Any]) -> None:
    temp = path.with_name(path.name + ".tmp")
    temp.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temp, path)


def make_archive(source: Path, output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    temp = output.with_name(output.name + ".tmp")
    temp.unlink(missing_ok=True)
    result = subprocess.run(["tar", "--zstd", "-cf", str(temp), "-C", str(source.parent), source.name], text=True, capture_output=True)
    require(result.returncode == 0, result.stderr.strip() or "archive creation failed")
    os.replace(temp, output)


def safe_member(name: str) -> str:
    path = PurePosixPath(name.replace("\\", "/"))
    require(not path.is_absolute() and ".." not in path.parts, f"unsafe archive member: {name}")
    return path.as_posix()


def extract_verified_report(archive: Path, expected_hash: str, root_name: str, expected_summary_hash: str, destination: Path) -> Path:
    require(archive.is_file(), f"missing prerequisite report: {archive}")
    actual = sha256_file(archive)
    require(actual == expected_hash, f"unexpected prerequisite SHA-256: {archive.name}: {actual}")
    listed = subprocess.run(["tar", "--zstd", "-tf", str(archive)], text=True, capture_output=True)
    require(listed.returncode == 0, listed.stderr.strip() or "cannot list prerequisite")
    names = [safe_member(line) for line in listed.stdout.splitlines() if line.strip()]
    require(names and {PurePosixPath(name).parts[0] for name in names} == {root_name}, f"unexpected report root: {archive}")
    destination.mkdir(parents=True, exist_ok=True)
    unpack = subprocess.run(["tar", "--zstd", "-xf", str(archive), "-C", str(destination)], text=True, capture_output=True)
    require(unpack.returncode == 0, unpack.stderr.strip() or "cannot extract prerequisite")
    root = destination / root_name
    summary = root / "SUMMARY.json"
    require(summary.is_file(), f"missing prerequisite SUMMARY.json: {root_name}")
    require(sha256_file(summary) == expected_summary_hash, f"unexpected prerequisite summary SHA-256: {root_name}")
    return root


def load_br_tool(project_root: Path):
    path = project_root / "Blue_Reflection_Text_Tool/br_restoration_tool.py"
    require(path.is_file(), f"missing restoration tool: {path}")
    spec = importlib.util.spec_from_file_location("stage129_br_restoration_tool", path)
    require(spec is not None and spec.loader is not None, "cannot load restoration tool")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def load_inventory(project_root: Path, group: str) -> dict[tuple[str, str], tuple[str, dict[str, Any]]]:
    root = project_root / ".local/reports/quartet_restoration/inventories"
    result: dict[tuple[str, str], tuple[str, dict[str, Any]]] = {}
    for side in ("source", "target"):
        path = root / f"{group}.{side}.json"
        require(path.is_file(), f"missing inventory: {path}")
        data = json.loads(path.read_text(encoding="utf-8"))
        require(data.get("archive_group") == group, f"inventory group drift: {path}")
        for entry in data.get("files", []):
            normalized = str(entry.get("normalized_path", "")).casefold()
            if normalized:
                result[(side, normalized)] = (group, dict(entry))
    return result


def find_gust_pak(project_root: Path, explicit: Path | None) -> Path:
    candidates = []
    if explicit:
        candidates.append(explicit.expanduser())
    candidates.append(project_root / ".local/vendor/gust_tools/gust_pak")
    found = shutil.which("gust_pak")
    if found:
        candidates.append(Path(found))
    for candidate in candidates:
        resolved = candidate.resolve()
        if resolved.is_file() and os.access(resolved, os.X_OK):
            return resolved
    raise CollectorError("gust_pak not found; provide --gust-pak or install it in .local/vendor/gust_tools")


def resolve_game_archive(game_root: Path, relative: str) -> Path:
    root = game_root.expanduser().resolve()
    require(root.is_dir(), f"game root does not exist: {root}")
    direct = root / PurePosixPath(relative)
    if direct.is_file():
        return direct.resolve()
    wanted = relative.casefold()
    matches = [p.resolve() for p in root.rglob("*.PAK") if p.relative_to(root).as_posix().casefold() == wanted]
    require(len(matches) == 1, f"cannot uniquely resolve {relative} below {root}; matches={len(matches)}")
    return matches[0]


def selected_records(stage128_root: Path) -> list[dict[str, str]]:
    rows = read_tsv(stage128_root / "COVERAGE_SELECTOR_CHANNEL_AUDIT.tsv")
    require(len(rows) == 19, f"expected 19 stage-128 coverage rows, found {len(rows)}")
    return rows


def candidate_asset_path(row: Mapping[str, str]) -> str:
    token = row["token"]
    if token.startswith("item_"):
        return f"data/x64/character/{token}/{token}.elixir.gz"
    character = row["character_id"]
    return f"data/x64/character/{character}/{token}.elixir.gz"


def sibling_asset_path(row: Mapping[str, str]) -> str | None:
    if row["family"] != "underwear_coverage_variant":
        return None
    character = row["character_id"]
    return f"data/x64/character/{character}/{character}_udw.elixir.gz"


def decode_text(payload: bytes) -> tuple[str, str]:
    for encoding in ("utf-8-sig", "utf-8", "cp932"):
        try:
            return payload.decode(encoding), encoding
        except UnicodeDecodeError:
            continue
    return payload.decode("latin-1"), "latin-1"


def xml_hits(payload: bytes, tokens: Sequence[str]) -> tuple[dict[str, int], list[dict[str, Any]], dict[str, Any]]:
    text, encoding = decode_text(payload)
    folded = text.casefold()
    token_counts = {token: folded.count(token.casefold()) for token in tokens}
    hits: list[dict[str, Any]] = []
    parse_status = "ok"
    element_count = 0
    attribute_count = 0
    try:
        root = ET.fromstring(text)
        stack = [(root, f"/{root.tag}")]
        while stack:
            element, xpath = stack.pop()
            element_count += 1
            attribute_count += len(element.attrib)
            fields = [("text", element.text or "")] + [(f"attr:{key}", value) for key, value in element.attrib.items()]
            for field, value in fields:
                folded_value = value.casefold()
                for token in tokens:
                    if token.casefold() in folded_value:
                        hits.append({"token": token, "xpath": xpath, "field": field, "value_sha256": hashlib.sha256(value.encode("utf-8", errors="replace")).hexdigest(), "value_length": len(value)})
            for index, child in enumerate(reversed(list(element))):
                stack.append((child, f"{xpath}/{child.tag}[{len(element)-index}]") )
    except ET.ParseError:
        parse_status = "parse_error_raw_text_scan_only"
    return token_counts, hits, {"encoding": encoding, "parse_status": parse_status, "element_count": element_count, "attribute_count": attribute_count, "payload_sha256": hashlib.sha256(payload).hexdigest(), "payload_size": len(payload)}


def oid_member(archive: Mapping[str, Any]) -> Mapping[str, Any]:
    rows = [row for row in archive.get("members", []) if str(row.get("name", "")).casefold().endswith("oid.bin")]
    require(len(rows) == 1, f"expected one Oid.bin member, found {len(rows)}")
    return rows[0]


def oid_shape(payload: bytes) -> dict[str, Any]:
    aligned = len(payload) // 4
    words = [int.from_bytes(payload[i:i+4], "little") for i in range(0, aligned * 4, 4)]
    ascii_tokens = sorted(set(match.decode("ascii", errors="ignore") for match in re.findall(rb"[A-Za-z0-9_./:-]{4,96}", payload)))
    return {
        "payload_size": len(payload),
        "payload_sha256": hashlib.sha256(payload).hexdigest(),
        "u32_word_rows": len(words),
        "nonzero_u32_rows": sum(1 for word in words if word),
        "unique_u32_rows": len(set(words)),
        "ascii_identifier_rows": len(ascii_tokens),
        "ascii_identifier_signature": hashlib.sha256("\n".join(ascii_tokens).encode()).hexdigest(),
        "words": words,
        "ascii_tokens": ascii_tokens,
    }


def common_prefix_bytes(left: bytes, right: bytes) -> int:
    count = 0
    for a, b in zip(left, right):
        if a != b:
            break
        count += 1
    return count


def common_suffix_bytes(left: bytes, right: bytes) -> int:
    count = 0
    for a, b in zip(reversed(left), reversed(right)):
        if a != b:
            break
        count += 1
    return count


def ensure_inputs(
    *, project_root: Path, workspace_root: Path, inventory_maps: Mapping[str, Mapping[tuple[str, str], tuple[str, dict[str, Any]]]],
    requirements: Sequence[tuple[str, str, str]], original_root: Path | None, quartet_root: Path | None,
    gust_pak_path: Path | None, br: Any, timeout_seconds: int, fixture_root: Path | None,
) -> tuple[dict[tuple[str, str, str], Path], list[dict[str, Any]]]:
    resolved: dict[tuple[str, str, str], Path] = {}
    missing_archives: dict[tuple[str, str, str], list[tuple[str, str, str]]] = defaultdict(list)
    for group, side, normalized in requirements:
        if fixture_root is not None:
            local = fixture_root / group / side / PurePosixPath(normalized)
            require(local.is_file(), f"missing fixture input: {local}")
            resolved[(group, side, normalized)] = local
            continue
        inventory = inventory_maps[group]
        key = (side, normalized.casefold())
        require(key in inventory, f"missing inventory entry: {group} {side} {normalized}")
        pair_id, entry = inventory[key]
        local = br.inventory_workspace_file(workspace_root, side, pair_id, str(entry["archive"]), str(entry["path"]))
        resolved[(group, side, normalized)] = local
        if not local.is_file():
            missing_archives[(group, side, str(entry["archive"]))].append((group, side, normalized))
    extraction_rows: list[dict[str, Any]] = []
    if missing_archives:
        require(fixture_root is None, "fixture inputs unexpectedly missing")
        require(original_root is not None and quartet_root is not None, "workspace inputs missing; provide --original-root and --quartet-root")
        gust = find_gust_pak(project_root, gust_pak_path)
        gust_sha = sha256_file(gust)
        roots = {"source": original_root, "target": quartet_root}
        for (group, side, archive_rel), members in sorted(missing_archives.items()):
            archive = resolve_game_archive(roots[side], archive_rel)
            result = br.extract_archive(archive=archive, game_root=roots[side].expanduser().resolve(), gust_pak=gust, gust_pak_sha256=gust_sha, pair_id=group, side=side, workspace_root=workspace_root, timeout_seconds=timeout_seconds)
            extraction_rows.append({"group": group, "side": side, "archive_relative": archive_rel, "required_path_rows": len(members), "archive_size": result["source_archive_size"], "archive_sha256": result["source_archive_sha256"], "gust_pak_sha256": gust_sha, "cache_action": result["status"]})
        for key, path in resolved.items():
            require(path.is_file(), f"missing extracted input after archive extraction: {key}: {path}")
    return resolved, extraction_rows


def build_report(
    project_root: Path, *, report_root: Path | None = None, output_report_root: Path | None = None,
    workspace_root: Path | None = None, original_root: Path | None = None, quartet_root: Path | None = None,
    gust_pak_path: Path | None = None, fixture_root: Path | None = None, timeout_seconds: int = 1800,
    verify_payload_hashes: bool = True, create_archive: bool = True,
    seed_rows_override: Sequence[Mapping[str, str]] | None = None,
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

    br = load_br_tool(project_root)
    with tempfile.TemporaryDirectory(prefix="stage129-prereq-") as temp:
        stage128 = extract_verified_report(report_root / STAGE128_NAME, STAGE128_SHA256, STAGE128_ROOT, STAGE128_SUMMARY_SHA256, Path(temp))
        stage128_summary = json.loads((stage128 / "SUMMARY.json").read_text(encoding="utf-8"))
        require(stage128_summary.get("unbound_coverage_family_rows") == 19, "stage-128 coverage row drift")
        require(stage128_summary.get("standalone_render_path_rows") == 5, "stage-128 render-path drift")
        candidates = selected_records(stage128)

    require(sha256_file(report_root / DXBC_REPORT_NAME) == DXBC_REPORT_SHA256, "DXBC report hash drift")
    require(sha256_file(report_root / "dxbc_reflection_evidence/SUMMARY.json") == DXBC_SUMMARY_SHA256, "DXBC summary hash drift")

    inventories = {"br1_language": load_inventory(project_root, "br1_language"), "br1_assets": load_inventory(project_root, "br1_assets")}
    requirements: list[tuple[str, str, str]] = []
    for path in STRUCTURED_PATHS:
        if ("source", path.casefold()) in inventories["br1_language"]:
            requirements.append(("br1_language", "source", path))
        requirements.append(("br1_language", "target", path))
    for row in candidates:
        requirements.append(("br1_assets", "target", candidate_asset_path(row)))
        sibling = sibling_asset_path(row)
        if sibling:
            requirements.append(("br1_assets", "target", sibling))
    resolved, extraction_rows = ensure_inputs(project_root=project_root, workspace_root=workspace_root, inventory_maps=inventories, requirements=requirements, original_root=original_root, quartet_root=quartet_root, gust_pak_path=gust_pak_path, br=br, timeout_seconds=timeout_seconds, fixture_root=fixture_root)

    all_tokens = [row["token"] for row in candidates]
    structured_rows: list[dict[str, Any]] = []
    selector_hits: list[dict[str, Any]] = []
    structured_payloads: dict[tuple[str, str], bytes] = {}
    for group, side, normalized in requirements:
        if group != "br1_language":
            continue
        path = resolved[(group, side, normalized)]
        payload = path.read_bytes()
        if fixture_root is None and verify_payload_hashes:
            _, entry = inventories[group][(side, normalized.casefold())]
            require(sha256_file(path) == str(entry["sha256"]), f"payload hash drift: {side} {normalized}")
        structured_payloads[(side, normalized)] = payload
        counts, hits, metadata = xml_hits(payload, all_tokens + ["caustics", "cwater", "cwater2"])
        structured_rows.append({"side": side, "normalized_path": normalized, **metadata, "exact_candidate_token_hit_rows": sum(counts[token] for token in all_tokens), "caustics_text_hit_rows": counts["caustics"], "cwater_text_hit_rows": counts["cwater"], "cwater2_text_hit_rows": counts["cwater2"], "payload_in_evidence": False})
        for hit in hits:
            selector_hits.append({"side": side, "normalized_path": normalized, **hit, "binding_confirmed": False, "visual_or_censorship_semantics_confirmed": False})

    oid_rows: list[dict[str, Any]] = []
    seed_hits: list[dict[str, Any]] = []
    matrix_rows: list[dict[str, Any]] = []
    seed_rows = list(seed_rows_override) if seed_rows_override is not None else read_tsv(report_root / "presentation_surface_evidence/COSTUME_OID_SIGNATURES.tsv")
    seeds_by_candidate: dict[str, list[tuple[str, bytes]]] = defaultdict(list)
    for row in seed_rows:
        seeds_by_candidate[row["candidate_id"]].append((row["seed_id"], bytes.fromhex(row["seed_sha256"][:0]) if False else b""))
    # Recover exact seed bytes from the owner OID member using recorded offset/length.
    oid_payload_by_candidate: dict[str, bytes] = {}
    bounded_oid_scan_payloads: dict[str, bytes] = {}
    for row in candidates:
        path = resolved[("br1_assets", "target", candidate_asset_path(row))]
        if fixture_root is None and verify_payload_hashes:
            _, entry = inventories["br1_assets"][("target", candidate_asset_path(row).casefold())]
            require(sha256_file(path) == str(entry["sha256"]), f"payload hash drift: target {candidate_asset_path(row)}")
        archive = br.read_earc_archive(path, maximum_bytes=MAX_EARC_BYTES, include_member_payloads=True)
        member = oid_member(archive)
        payload = bytes(member["payload"])
        oid_payload_by_candidate[row["candidate_id"]] = payload
        bounded_oid_scan_payloads[f"candidate:{row["candidate_id"]}"] = payload
        shape = oid_shape(payload)
        oid_rows.append({"candidate_id": row["candidate_id"], "token": row["token"], "family": row["family"], "character_id": row["character_id"], "role": "candidate", "asset_path": candidate_asset_path(row), "oid_member_name": member["name"], **{k: v for k, v in shape.items() if k not in {"words", "ascii_tokens"}}, "payload_in_evidence": False})
        sibling = sibling_asset_path(row)
        if sibling:
            sibling_file = resolved[("br1_assets", "target", sibling)]
            if fixture_root is None and verify_payload_hashes:
                _, entry = inventories["br1_assets"][("target", sibling.casefold())]
                require(sha256_file(sibling_file) == str(entry["sha256"]), f"payload hash drift: target {sibling}")
            sibling_archive = br.read_earc_archive(sibling_file, maximum_bytes=MAX_EARC_BYTES, include_member_payloads=True)
            sibling_member = oid_member(sibling_archive)
            sibling_payload = bytes(sibling_member["payload"])
            bounded_oid_scan_payloads[f"sibling_udw:{row["character_id"]}"] = sibling_payload
            sibling_shape = oid_shape(sibling_payload)
            oid_rows.append({"candidate_id": row["candidate_id"], "token": row["token"], "family": row["family"], "character_id": row["character_id"], "role": "sibling_udw", "asset_path": sibling, "oid_member_name": sibling_member["name"], **{k: v for k, v in sibling_shape.items() if k not in {"words", "ascii_tokens"}}, "payload_in_evidence": False})
            left_words, right_words = shape["words"], sibling_shape["words"]
            paired = min(len(left_words), len(right_words))
            matrix_rows.append({"candidate_id": row["candidate_id"], "token": row["token"], "character_id": row["character_id"], "candidate_oid_size": len(payload), "sibling_oid_size": len(sibling_payload), "common_prefix_bytes": common_prefix_bytes(payload, sibling_payload), "common_suffix_bytes": common_suffix_bytes(payload, sibling_payload), "paired_u32_rows": paired, "equal_u32_rows": sum(1 for i in range(paired) if left_words[i] == right_words[i]), "different_u32_rows": sum(1 for i in range(paired) if left_words[i] != right_words[i]), "candidate_only_u32_rows": max(0, len(left_words)-paired), "sibling_only_u32_rows": max(0, len(right_words)-paired), "exact_payload_equal": payload == sibling_payload, "selector_binding_confirmed": False})

    # Exact 12-byte seed scans across bounded OID and structured-table inputs.
    for seed in seed_rows:
        owner = oid_payload_by_candidate.get(seed["candidate_id"])
        if owner is None:
            continue
        offset, length = int(seed["seed_offset"]), int(seed["seed_length"])
        value = owner[offset:offset+length]
        require(len(value) == length and hashlib.sha256(value).hexdigest() == seed["seed_sha256"], f"OID seed reconstruction drift: {seed['seed_id']}")
        for scan_identity, payload in bounded_oid_scan_payloads.items():
            count = payload.count(value)
            if count:
                self_identity = f"candidate:{seed["candidate_id"]}"
                seed_hits.append({"seed_id": seed["seed_id"], "owner_candidate_id": seed["candidate_id"], "scan_domain": "bounded_candidate_and_sibling_oid_members", "scan_identity": scan_identity, "exact_hit_rows": count, "self_hit": scan_identity == self_identity, "independent_binding_hit": scan_identity != self_identity})
        for (side, path), payload in structured_payloads.items():
            count = payload.count(value)
            if count:
                seed_hits.append({"seed_id": seed["seed_id"], "owner_candidate_id": seed["candidate_id"], "scan_domain": "structured_xml_payload", "scan_identity": f"{side}:{path}", "exact_hit_rows": count, "self_hit": False, "independent_binding_hit": True})

    reflection = read_tsv(report_root / "dxbc_reflection_evidence/DXBC_REFLECTION_DIFF.tsv")
    water_rows: list[dict[str, Any]] = []
    for path in WATER_SHADER_PATHS:
        rows = [row for row in reflection if row["normalized_path"] == path]
        require(len(rows) == 5, f"expected five DXBC programs for {path}, found {len(rows)}")
        water_rows.append({"normalized_path": path, "paired_program_rows": len(rows), "code_chunks_identical_rows": sum(row["code_chunks_identical"].casefold() == "true" for row in rows), "signatures_semantically_identical_rows": sum(row["signatures_semantically_identical"].casefold() == "true" for row in rows), "compiler_or_reflection_metadata_only_rows": sum(row["classification"] == "compiler_or_reflection_metadata_only_delta" for row in rows), "executable_code_delta_rows": sum(row["code_chunks_identical"].casefold() != "true" for row in rows), "static_disposition": "compiler_or_reflection_metadata_only_no_executable_shader_delta", "profile_candidate_authorized": False})

    target_caustics_xml = structured_payloads[("target", "saves/fieldmap/caustics_param.xml")]
    source_caustics_exists = ("source", "saves/fieldmap/caustics_param.xml".casefold()) in inventories["br1_language"]
    target_texture_entry = inventories["br1_assets"][("target", CAUSTICS_TEXTURE_PATH.casefold())][1]
    caustics_counts, caustics_hits, caustics_meta = xml_hits(target_caustics_xml, ["caustics", "g1t", "texture"])
    caustics_rows = [{"texture_path": CAUSTICS_TEXTURE_PATH, "texture_target_only": True, "texture_size": target_texture_entry["size"], "texture_sha256": target_texture_entry["sha256"], "parameter_path": "saves/fieldmap/caustics_param.xml", "parameter_target_only": not source_caustics_exists, "parameter_size": caustics_meta["payload_size"], "parameter_sha256": caustics_meta["payload_sha256"], "parameter_xml_parse_status": caustics_meta["parse_status"], "parameter_element_rows": caustics_meta["element_count"], "direct_texture_name_hit_rows": caustics_counts["caustics"] + caustics_counts["g1t"], "target_only_subsystem_pair_confirmed": True, "direct_selector_binding_confirmed": False, "visual_or_censorship_semantics_confirmed": False, "write_authorized": False}]

    write_tsv(output / "EXTRACTION_INPUTS.tsv", ["group", "side", "archive_relative", "required_path_rows", "archive_size", "archive_sha256", "gust_pak_sha256", "cache_action"], extraction_rows)
    write_tsv(output / "STRUCTURED_SELECTOR_TABLES.tsv", ["side", "normalized_path", "encoding", "parse_status", "element_count", "attribute_count", "payload_size", "payload_sha256", "exact_candidate_token_hit_rows", "caustics_text_hit_rows", "cwater_text_hit_rows", "cwater2_text_hit_rows", "payload_in_evidence"], structured_rows)
    write_tsv(output / "STRUCTURED_SELECTOR_EXACT_HITS.tsv", ["side", "normalized_path", "token", "xpath", "field", "value_length", "value_sha256", "binding_confirmed", "visual_or_censorship_semantics_confirmed"], selector_hits)
    write_tsv(output / "OID_MEMBER_MATRIX.tsv", ["candidate_id", "token", "family", "character_id", "role", "asset_path", "oid_member_name", "payload_size", "payload_sha256", "u32_word_rows", "nonzero_u32_rows", "unique_u32_rows", "ascii_identifier_rows", "ascii_identifier_signature", "payload_in_evidence"], oid_rows)
    write_tsv(output / "UNDERWEAR_SIBLING_OID_MATRIX.tsv", ["candidate_id", "token", "character_id", "candidate_oid_size", "sibling_oid_size", "common_prefix_bytes", "common_suffix_bytes", "paired_u32_rows", "equal_u32_rows", "different_u32_rows", "candidate_only_u32_rows", "sibling_only_u32_rows", "exact_payload_equal", "selector_binding_confirmed"], matrix_rows)
    write_tsv(output / "EXACT_OID_SEED_SCAN.tsv", ["seed_id", "owner_candidate_id", "scan_domain", "scan_identity", "exact_hit_rows", "self_hit", "independent_binding_hit"], seed_hits)
    write_tsv(output / "WATER_SHADER_PAIR_CLASSIFICATION.tsv", ["normalized_path", "paired_program_rows", "code_chunks_identical_rows", "signatures_semantically_identical_rows", "compiler_or_reflection_metadata_only_rows", "executable_code_delta_rows", "static_disposition", "profile_candidate_authorized"], water_rows)
    write_tsv(output / "CAUSTICS_TARGET_ONLY_SUBSYSTEM.tsv", ["texture_path", "texture_target_only", "texture_size", "texture_sha256", "parameter_path", "parameter_target_only", "parameter_size", "parameter_sha256", "parameter_xml_parse_status", "parameter_element_rows", "direct_texture_name_hit_rows", "target_only_subsystem_pair_confirmed", "direct_selector_binding_confirmed", "visual_or_censorship_semantics_confirmed", "write_authorized"], caustics_rows)

    exact_structured_hits = sum(row["exact_candidate_token_hit_rows"] for row in structured_rows)
    independent_seed_hits = sum(int(row["exact_hit_rows"]) for row in seed_hits if row["independent_binding_hit"])
    summary: dict[str, Any] = {
        "type": "br_quartet_restoration_structured_selector_water_dependency_evidence_summary",
        "format_version": 1,
        "tool_version": TOOL_VERSION,
        "status": "structured_selector_and_water_dependency_scan_complete_bounded_channels_non_authorizing_no_semantics_no_write",
        "coverage_family_rows": len(candidates),
        "item_family_rows": sum(row["family"] != "underwear_coverage_variant" for row in candidates),
        "underwear_family_rows": sum(row["family"] == "underwear_coverage_variant" for row in candidates),
        "structured_table_payload_rows": len(structured_rows),
        "structured_exact_candidate_token_hit_rows": exact_structured_hits,
        "structured_exact_hit_detail_rows": len(selector_hits),
        "oid_member_rows": len(oid_rows),
        "underwear_sibling_matrix_rows": len(matrix_rows),
        "oid_seed_scan_hit_rows": len(seed_hits),
        "independent_oid_seed_exact_hit_rows": independent_seed_hits,
        "independent_selector_binding_confirmed_rows": 0,
        "water_shader_family_rows": len(water_rows),
        "water_shader_paired_program_rows": sum(row["paired_program_rows"] for row in water_rows),
        "water_shader_executable_code_delta_rows": sum(row["executable_code_delta_rows"] for row in water_rows),
        "water_shader_compiler_or_reflection_metadata_only_rows": sum(row["compiler_or_reflection_metadata_only_rows"] for row in water_rows),
        "caustics_target_only_texture_rows": 1,
        "caustics_target_only_parameter_table_rows": int(not source_caustics_exists),
        "caustics_target_only_subsystem_pair_rows": 1,
        "caustics_direct_selector_binding_rows": 0,
        "runtime_confirmed_rows": 0,
        "visual_or_censorship_semantics_confirmed_rows": 0,
        "write_authorized_rows": 0,
        "global_discovery_saturation_achieved": False,
        "policy": {
            "local_proprietary_payloads_read": fixture_root is None,
            "proprietary_payloads_in_report": False,
            "saves_required": False,
            "installed_game_modified": False,
            "pak_built_or_repacked": False,
            "profile_or_registry_modified": False,
            "core_modified": False,
            "translation_modified": False,
            "legacy_dlc_modified": False,
            "git_modified": False,
            "name_or_hash_hypotheses_treated_as_binding_proof": False,
            "shader_compiler_metadata_treated_as_executable_delta": False,
            "target_only_subsystem_pair_treated_as_visual_semantics": False,
        },
        "next_action": "Use exact structured-table hits and OID sibling matrices only to bound selector callsites. If no independent selector is recovered, keep the 19 coverage families unresolved and move to full static namespace discovery outside character assets. Remove cwater/cwater2 from executable restoration candidates because all ten paired DXBC code chunks are identical. Keep the caustics texture plus parameter table as a target-only subsystem pair without assigning visual or censorship semantics.",
    }
    atomic_json(output / "SUMMARY.json", summary)

    archive: Path | None = None
    if create_archive:
        archive = output_report_root / REPORT_NAME
        make_archive(output, archive)
        names = subprocess.run(["tar", "--zstd", "-tf", str(archive)], text=True, capture_output=True, check=True).stdout.splitlines()
        require(not any(name.casefold().endswith(FORBIDDEN_EXTENSIONS) for name in names), "proprietary payload extension in evidence archive")
    return archive, summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Collect read-only structured selector, OID sibling-matrix and water dependency evidence.")
    parser.add_argument("--project-root", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--report-root", type=Path)
    parser.add_argument("--output-report-root", type=Path)
    parser.add_argument("--workspace-root", type=Path)
    parser.add_argument("--original-root", type=Path, default=Path(os.environ["BR1_ORIGINAL_ROOT"]) if os.environ.get("BR1_ORIGINAL_ROOT") else None)
    parser.add_argument("--quartet-root", type=Path, default=Path(os.environ["BR1_QUARTET_ROOT"]) if os.environ.get("BR1_QUARTET_ROOT") else None)
    parser.add_argument("--gust-pak", type=Path)
    parser.add_argument("--timeout-seconds", type=int, default=1800)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    archive, summary = build_report(args.project_root, report_root=args.report_root, output_report_root=args.output_report_root, workspace_root=args.workspace_root, original_root=args.original_root, quartet_root=args.quartet_root, gust_pak_path=args.gust_pak, timeout_seconds=args.timeout_seconds)
    print(json.dumps(summary, indent=2, sort_keys=True))
    if archive:
        print(f"[stage129] report archive: {archive}")
        print(f"[stage129] report SHA-256: {sha256_file(archive)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
