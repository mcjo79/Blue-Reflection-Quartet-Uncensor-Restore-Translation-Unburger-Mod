#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Iterator, Sequence

TOOL_VERSION = "0.0.59"
EXPECTED_MEMBERS = [f"costume_pc{i:02d}_bkn" for i in range(8)]
TARGETS = {"Data/PACK10_02.PAK", "Data/PACK12.PAK"}
VISIBLE_LABELS = ("Hoshinomiya Uniform", "School Swimsuit", "Gym Uniform", "Cami")
LEGACY_LABELS = (
    "Sailor Swimsuit", "Summer Clothes", "Bath Towel", "Vacation Style",
    "Rorona", "Firis", "Nightless Saber",
)
TECHNICAL_PREFIXES = ("PC", "DLC_")
TEXT_EXTENSIONS = {".txt", ".ini", ".cfg", ".conf", ".json", ".xml", ".yaml", ".yml", ".toml", ".vdf", ".acf", ".reg", ".log", ".csv", ".tsv"}
STATE_EXTENSIONS = {".sav", ".save", ".dat", ".bin", ".slot", ".bak"}
BINARY_EXTENSIONS = {".exe", ".dll", ".so", ".bin"}
SKIP_EXTENSIONS = {".pak", ".zip", ".7z", ".rar", ".zst", ".gz", ".xz", ".iso"}
SKIP_DIRS = {".git", "cache", "caches", "shadercache", "shader_cache", "tmp", "temp", "logs", "log", "crashdumps", "webcache", "code cache", "gpucache", "windows", "winsxs", "system32", "syswow64"}
MAX_TEXT_BYTES = 16 * 1024 * 1024
MAX_STATE_BYTES = 128 * 1024 * 1024
MAX_BINARY_BYTES = 128 * 1024 * 1024
MAX_HITS_PER_FILE = 250


@dataclass(frozen=True)
class ScanRoot:
    label: str
    path: Path
    kind: str


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def safe_json(path: Path) -> dict:
    if not path.is_file() or path.is_symlink():
        raise ValueError(f"not a regular JSON file: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def read_tsv(path: Path) -> list[dict[str, str]]:
    if not path.is_file() or path.is_symlink():
        raise ValueError(f"not a regular TSV file: {path}")
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def write_tsv(path: Path, rows: Sequence[dict]) -> None:
    fields: list[str] = []
    for row in rows:
        for key in row:
            if key not in fields:
                fields.append(key)
    if not fields:
        path.write_text("status\nno_rows\n", encoding="utf-8")
        return
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        for row in rows:
            normalized = {}
            for key in fields:
                value = row.get(key, "")
                if isinstance(value, (dict, list, bool)):
                    value = json.dumps(value, ensure_ascii=False, sort_keys=True)
                normalized[key] = value
            writer.writerow(normalized)


def latest_report(reports: Path, prefix: str, required: Sequence[str]) -> Path:
    candidates = sorted((p for p in reports.glob(prefix + "*") if p.is_dir()), key=lambda p: p.name, reverse=True)
    for candidate in candidates:
        if all((candidate / name).is_file() for name in required):
            return candidate
    raise ValueError(f"required report not found: {prefix}")


def validate_active_and_rollback(project_root: Path, game_root: Path) -> tuple[dict, list[dict]]:
    active_path = project_root / ".local/reports/quartet_legacy_dlc/validated_payloads/ACTIVE.json"
    active = safe_json(active_path)
    if active.get("type") != "validated_quartet_legacy_dlc_payload":
        raise ValueError("unexpected ACTIVE.json type")
    if active.get("generation") != 8 or active.get("members") != EXPECTED_MEMBERS:
        raise ValueError("generation 8 PC00-PC07 ACTIVE.json required")
    transaction = active.get("transaction", {})
    if transaction.get("all_or_none") is not True or transaction.get("commit_enabled") is not False:
        raise ValueError("ACTIVE transaction policy mismatch")
    artifacts = active.get("artifacts", [])
    if len(artifacts) != 2 or {row.get("target_path") for row in artifacts} != TARGETS:
        raise ValueError("ACTIVE must declare the two canonical targets")
    rows: list[dict] = []
    for artifact in sorted(artifacts, key=lambda row: row["target_path"]):
        target = artifact["target_path"]
        path = game_root / Path(target)
        if not path.is_file() or path.is_symlink():
            state, actual, size = "missing", "", 0
        else:
            actual = sha256_file(path)
            size = path.stat().st_size
            if actual == artifact["baseline_sha256"]:
                state = "baseline"
            elif actual == artifact["candidate_sha256"]:
                state = "candidate"
            else:
                state = "other"
        rows.append({
            "target_path": target,
            "installed_state": state,
            "installed_size": size,
            "installed_sha256": actual,
            "baseline_sha256": artifact["baseline_sha256"],
            "candidate_sha256": artifact["candidate_sha256"],
        })
    if {row["installed_state"] for row in rows} != {"baseline"}:
        raise ValueError(f"full rollback baseline required: {[row['installed_state'] for row in rows]}")
    return active, rows


def classify_visible_labels(sequence_rows: Sequence[dict[str, str]], acceptance: dict) -> list[dict]:
    accepted = {row["label"]: row for row in acceptance["runtime_visible_labels"]}
    output: list[dict] = []
    for label in VISIBLE_LABELS:
        matches = [row for row in sequence_rows if row.get("quartet_text") == label or row.get("original_text") == label]
        state = accepted[label]
        output.append({
            "label": label,
            "sequence_rows": len(matches),
            "string_numbers": ",".join(sorted({row.get("string_no", "") for row in matches if row.get("string_no")})),
            "sequence_statuses": ",".join(sorted({row.get("status", "") for row in matches if row.get("status")})),
            "classification": state["classification"],
            "runtime_visible": True,
            "positive_control_eligible": False,
            "reason": state["reason"],
        })
    return output


def classify_legacy_labels(sequence_rows: Sequence[dict[str, str]]) -> list[dict]:
    output: list[dict] = []
    for label in LEGACY_LABELS:
        rows = [row for row in sequence_rows if row.get("original_text") == label]
        target_values = sorted({row.get("quartet_text", "") for row in rows})
        output.append({
            "label": label,
            "original_rows": len(rows),
            "quartet_values": ",".join(target_values),
            "all_replaced_by_dash": bool(rows) and set(target_values) == {"-"},
            "runtime_visible": label in VISIBLE_LABELS,
            "positive_control_eligible": False,
        })
    return output


def extract_member_records(system_rows: Sequence[dict[str, str]], member_id: str) -> list[dict]:
    return [row for row in system_rows if row.get("content_id") == member_id]


def technical_tokens(system_rows: Sequence[dict[str, str]]) -> list[str]:
    tokens: set[str] = set()
    for row in system_rows:
        member = row.get("content_id", "")
        if member.startswith("costume_"):
            for key in ("dlc_identifiers", "linked_identifiers", "record_key"):
                value = row.get(key, "")
                for token in re.findall(r"PC\d{2}_DLC_[A-Z0-9_]+", value):
                    tokens.add(token)
    tokens.update(VISIBLE_LABELS)
    tokens.update(LEGACY_LABELS)
    return sorted(tokens, key=lambda value: (-len(value), value.casefold()))


def classify_path(path: Path) -> str:
    name = path.name.casefold()
    suffix = path.suffix.casefold()
    if suffix in STATE_EXTENSIONS or any(token in name for token in ("save", "savedata", "systemdata", "profile")):
        return "save_or_state"
    if suffix in TEXT_EXTENSIONS or name in {"steam_emu.ini", "cream_api.ini", "dlc.txt", "steam_appid.txt"}:
        return "text_config"
    if suffix in BINARY_EXTENSIONS:
        return "binary"
    return "other"


def iter_files(root: ScanRoot) -> Iterator[Path]:
    seen: set[Path] = set()
    for dirpath, dirnames, filenames in os.walk(root.path, followlinks=False):
        base = Path(dirpath)
        dirnames[:] = [name for name in dirnames if name.casefold() not in SKIP_DIRS]
        for name in filenames:
            path = base / name
            try:
                if path.is_symlink() or not path.is_file() or path.suffix.casefold() in SKIP_EXTENSIONS:
                    continue
                resolved = path.resolve()
                if resolved in seen:
                    continue
                seen.add(resolved)
                yield resolved
            except OSError:
                continue


def decode_text(raw: bytes) -> list[tuple[str, str]]:
    output: list[tuple[str, str]] = []
    for encoding in ("utf-8-sig", "utf-16-le", "utf-16-be", "cp932", "latin-1"):
        try:
            text = raw.decode(encoding)
        except UnicodeDecodeError:
            continue
        if encoding == "latin-1" or "\x00" not in text[:2048]:
            output.append((encoding, text))
    return output


def text_token_hits(raw: bytes, tokens: Sequence[str]) -> tuple[str, list[dict]]:
    best_encoding = "binary"
    best: list[dict] = []
    for encoding, text in decode_text(raw):
        rows: list[dict] = []
        for line_no, line in enumerate(text.splitlines(), 1):
            folded = line.casefold()
            matched = [token for token in tokens if token.casefold() in folded]
            if not matched:
                continue
            rows.append({
                "line": line_no,
                "tokens": matched,
                "snippet": " ".join(line.strip().split())[:600],
            })
            if len(rows) >= MAX_HITS_PER_FILE:
                break
        if len(rows) > len(best):
            best_encoding, best = encoding, rows
    return best_encoding, best


def binary_token_hits(raw: bytes, tokens: Sequence[str]) -> list[dict]:
    rows: list[dict] = []
    lowered = raw.lower()
    for token in tokens:
        for encoding, needle in (("ascii", token.encode("ascii", errors="ignore")), ("utf16le", token.encode("utf-16-le"))):
            if not needle:
                continue
            start = 0
            count = 0
            while True:
                offset = lowered.find(needle.lower(), start)
                if offset < 0:
                    break
                rows.append({"token": token, "encoding": encoding, "offset": offset})
                count += 1
                if len(rows) >= MAX_HITS_PER_FILE or count >= 20:
                    return rows
                start = offset + max(1, len(needle))
    return rows


def parse_auxiliary_dlc_config(path: Path) -> list[dict]:
    if not path.is_file() or path.is_symlink() or path.stat().st_size > MAX_TEXT_BYTES:
        return []
    raw = path.read_bytes()
    rows: list[dict] = []
    for encoding, text in decode_text(raw):
        section = ""
        for line_no, raw_line in enumerate(text.splitlines(), 1):
            line = raw_line.strip()
            if not line or line.startswith((";", "#")):
                continue
            if line.startswith("[") and line.endswith("]"):
                section = line[1:-1].strip()
                continue
            if "=" not in line:
                continue
            key, value = (part.strip() for part in line.split("=", 1))
            folded = f"{section} {key}".casefold()
            if "dlc" not in folded and "appid" not in folded and "app_id" not in folded:
                continue
            rows.append({
                "relative_path": path.name,
                "encoding": encoding,
                "line": line_no,
                "section": section,
                "key": key,
                "value": value[:300],
                "evidence_role": "auxiliary_platform_configuration",
                "semantic_authority": False,
                "original_appid_mapping_used": False,
            })
        if rows:
            break
    return rows


def scan_roots(game_root: Path, state_roots: Sequence[Path], tokens: Sequence[str]) -> tuple[list[dict], list[dict], list[dict], list[dict]]:
    roots = [ScanRoot("quartet_game", game_root.resolve(), "game")]
    roots.extend(ScanRoot(f"state_root_{index}", path.resolve(), "state") for index, path in enumerate(state_roots, 1))
    inventory: list[dict] = []
    text_hits: list[dict] = []
    binary_hits: list[dict] = []
    auxiliary: list[dict] = []
    for root in roots:
        if not root.path.exists():
            inventory.append({"root": root.label, "relative_path": "", "status": "missing_root", "raw_content_exported": False})
            continue
        for path in iter_files(root):
            file_class = classify_path(path)
            size = path.stat().st_size
            if file_class == "other":
                continue
            limit = MAX_TEXT_BYTES if file_class == "text_config" else MAX_STATE_BYTES if file_class == "save_or_state" else MAX_BINARY_BYTES
            if size > limit:
                continue
            rel = path.relative_to(root.path).as_posix()
            base = {
                "root": root.label,
                "root_kind": root.kind,
                "relative_path": rel,
                "file_class": file_class,
                "size": size,
                "sha256": sha256_file(path),
                "mtime_ns": path.stat().st_mtime_ns,
                "raw_content_exported": False,
            }
            inventory.append(base)
            raw = path.read_bytes()
            if file_class in {"text_config", "save_or_state"}:
                encoding, hits = text_token_hits(raw, tokens)
                for hit in hits:
                    text_hits.append({**base, "detected_encoding": encoding, **hit})
            if file_class in {"binary", "save_or_state"}:
                for hit in binary_token_hits(raw, tokens):
                    binary_hits.append({**base, **hit})
            if root.kind == "game" and path.name.casefold() in {"steam_emu.ini", "cream_api.ini", "dlc.txt", "steam_appid.txt"}:
                for row in parse_auxiliary_dlc_config(path):
                    auxiliary.append({"root": root.label, **row, "config_sha256": base["sha256"]})
    return inventory, text_hits, binary_hits, auxiliary


def candidate_rows(visible_rows: Sequence[dict], system_rows: Sequence[dict[str, str]], text_hits: Sequence[dict], binary_hits: Sequence[dict], auxiliary_rows: Sequence[dict]) -> list[dict]:
    output: list[dict] = []
    hit_tokens = {token for row in text_hits for token in row.get("tokens", [])}
    hit_tokens.update(row.get("token", "") for row in binary_hits)
    for visible in visible_rows:
        output.append({
            "candidate_id": "visible_label:" + visible["label"].lower().replace(" ", "_"),
            "label": visible["label"],
            "runtime_visible_label": True,
            "exact_character_costume_record": False,
            "exact_asset_parent_member_binding": False,
            "exact_quartet_native_availability_owner": False,
            "ui_or_save_state_binding": visible["label"] in hit_tokens,
            "auxiliary_platform_hit": any(visible["label"].casefold() in row.get("value", "").casefold() for row in auxiliary_rows),
            "original_appid_semantics_used": False,
            "positive_control_proven": False,
            "blocking_reason": visible["reason"],
        })
    for member_id, label in (("costume_pc00_twl", "Bath Towel"), ("costume_pc00_bkn", "BKN target")):
        records = extract_member_records(system_rows, member_id)
        identifiers = sorted({token for row in records for token in re.findall(r"PC\d{2}_DLC_[A-Z0-9_]+", " ".join(row.values()))})
        token_hit = any(token in hit_tokens for token in identifiers)
        output.append({
            "candidate_id": member_id,
            "label": label,
            "runtime_visible_label": label in VISIBLE_LABELS,
            "exact_character_costume_record": len(records) >= 3,
            "exact_asset_parent_member_binding": member_id == "costume_pc00_twl",
            "exact_quartet_native_availability_owner": False,
            "ui_or_save_state_binding": token_hit,
            "auxiliary_platform_hit": False,
            "original_appid_semantics_used": False,
            "positive_control_proven": False,
            "blocking_reason": "runtime visibility and exact Quartet-native availability owner are not both proven",
            "technical_identifiers": identifiers,
            "system_record_rows": len(records),
        })
    return output


def run(project_root: Path, game_root: Path, state_roots: Sequence[Path], output_dir: Path) -> dict:
    version = (project_root / "workstreams/quartet_legacy_dlc/VERSION").read_text(encoding="utf-8").strip()
    if version != TOOL_VERSION:
        raise ValueError(f"quartet_legacy_dlc {TOOL_VERSION} required, got {version}")
    acceptance_path = project_root / "workstreams/quartet_legacy_dlc/DLC_QUARTET_NATIVE_COSTUME_POSITIVE_CONTROL_ACCEPTANCE.json"
    acceptance = safe_json(acceptance_path)
    if acceptance.get("status") != "no_valid_dlc_positive_control_in_existing_evidence_read_only_collector_required":
        raise ValueError("positive-control acceptance status mismatch")

    reports = project_root / ".local/reports/quartet_legacy_dlc"
    availability = latest_report(reports, "BR_QUARTET_DLC_BKN_DRY_GENERATION8_AVAILABILITY_ROUTING_", ["DLC_BKN_RUNTIME_VISIBLE_LABEL_HITS.tsv", "SUMMARY.json"])
    closure = latest_report(reports, "BR_QUARTET_DLC_BKN_DRY_GENERATION8_EXACT_AVAILABILITY_CLOSURE_", ["STR_COSTUME_SEQUENCE_DIFF.tsv", "SUMMARY.json"])
    sequence_rows = read_tsv(closure / "STR_COSTUME_SEQUENCE_DIFF.tsv")
    system_rows = read_tsv(reports / "nonscenario_inventory_evidence/DLC_SYSTEM_TABLE_RECORDS.tsv")
    active, rollback_rows = validate_active_and_rollback(project_root, game_root)

    visible_rows = classify_visible_labels(sequence_rows, acceptance)
    legacy_rows = classify_legacy_labels(sequence_rows)
    tokens = technical_tokens(system_rows)
    inventory, text_hits, binary_hits, auxiliary = scan_roots(game_root, state_roots, tokens)
    candidates = candidate_rows(visible_rows, system_rows, text_hits, binary_hits, auxiliary)
    controls = [row for row in candidates if row["positive_control_proven"]]

    output_dir.mkdir(parents=True, exist_ok=False)
    write_tsv(output_dir / "INSTALLATION_ROLLBACK_STATE.tsv", rollback_rows)
    write_tsv(output_dir / "VISIBLE_LABEL_CLASSIFICATION.tsv", visible_rows)
    write_tsv(output_dir / "LEGACY_DLC_LABEL_CLASSIFICATION.tsv", legacy_rows)
    write_tsv(output_dir / "QUARTET_NATIVE_FILE_INVENTORY.tsv", inventory)
    write_tsv(output_dir / "QUARTET_NATIVE_COSTUME_TOKEN_HITS.tsv", text_hits)
    write_tsv(output_dir / "QUARTET_NATIVE_BINARY_TOKEN_HITS.tsv", binary_hits)
    write_tsv(output_dir / "QUARTET_NATIVE_PLATFORM_CONFIG_AUXILIARY.tsv", auxiliary)
    write_tsv(output_dir / "POSITIVE_CONTROL_CANDIDATES.tsv", candidates)

    bkn_delta = []
    for row in candidates:
        bkn_delta.append({
            "control_candidate": row["candidate_id"],
            "control_proven": row["positive_control_proven"],
            "bkn_assets_structurally_valid": True,
            "bkn_character_records_present": True,
            "bkn_availability_owner_proven": False,
            "bkn_runtime_visible": False,
            "additional_route_members_identified": False,
            "blocking_gap": "exact Quartet-native availability/UI/unlock/inventory/ownership owner remains unproven",
        })
    write_tsv(output_dir / "BKN_CONTROL_DELTA.tsv", bkn_delta)

    summary = {
        "type": "br_quartet_native_costume_positive_control_audit",
        "format_version": 1,
        "tool_version": TOOL_VERSION,
        "status": "positive_control_proven" if controls else "no_dlc_positive_control_proven",
        "generation": 8,
        "members": EXPECTED_MEMBERS,
        "source_evidence": {
            "availability_report": availability.name,
            "exact_closure_report": closure.name,
            "acceptance_sha256": sha256_file(acceptance_path),
        },
        "runtime_visible_labels": list(VISIBLE_LABELS),
        "positive_controls": [row["candidate_id"] for row in controls],
        "scan": {
            "state_roots_supplied": len(state_roots),
            "files_inventoried": len(inventory),
            "text_token_hits": len(text_hits),
            "binary_token_hits": len(binary_hits),
            "auxiliary_platform_rows": len(auxiliary),
            "paths_recorded_as_relative_only": True,
            "raw_contents_exported": False,
        },
        "conclusion": {
            "valid_positive_control_found": bool(controls),
            "four_visible_labels_are_dlc_controls": False,
            "twl_is_runtime_control": False,
            "original_appid_semantics_used": False,
            "platform_configuration_semantic_authority": False,
            "exact_additional_payload_members_identified": False,
            "pc08_allowed": False,
            "required_next_action": "If no control is proven, use the bounded token/config candidates to design a controlled read-only state differential around a Quartet-native DLC costume that the user can actually confirm as visible; do not reinstall BKN.",
        },
        "authorization": {
            "prepare": False,
            "commit": False,
            "install": False,
            "runtime_validation": False,
            "candidate_build": False,
            "active_manifest_write": False,
            "pc08_build": False,
            "wet_bkn": False,
            "core_modification": False,
            "translation_modification": False,
            "restoration_modification": False,
            "git_modification": False,
        },
        "game_files_modified": False,
        "save_files_modified": False,
    }
    (output_dir / "SUMMARY.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (output_dir / "ACTIVE_GENERATION8.json").write_text(json.dumps(active, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (output_dir / "POSITIVE_CONTROL_ACCEPTANCE.json").write_text(json.dumps(acceptance, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return summary


def parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-root", type=Path, required=True)
    parser.add_argument("--game-dir", type=Path, required=True)
    parser.add_argument("--state-root", type=Path, action="append", default=[])
    parser.add_argument("--output-dir", type=Path, required=True)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    try:
        summary = run(args.project_root.resolve(), args.game_dir.resolve(), [path.resolve() for path in args.state_root], args.output_dir.resolve())
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
