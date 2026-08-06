#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
import re
import stat
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Iterator, Sequence

TOOL_VERSION = "0.0.58"
EXPECTED_MEMBERS = [f"costume_pc{i:02d}_bkn" for i in range(8)]
TARGETS = {"Data/PACK10_02.PAK", "Data/PACK12.PAK"}

KEYWORDS = (
    "bkn", "costume", "outfit", "wardrobe", "dress", "dlc", "addon",
    "entitlement", "license", "ownership", "unlock", "inventory",
    "steam", "app_id", "appid", "depot", "proofofpurchase", "downloadable",
)
API_NAMES = (
    "BIsDlcInstalled", "GetDLCCount", "GetDLCDataByIndex",
    "InstallDLC", "UninstallDLC", "RequestAllProofOfPurchaseKeys",
    "GetAppOwner", "BIsSubscribedApp", "BIsSubscribedFromFamilySharing",
    "SteamApps", "ISteamApps",
)
TEXT_EXTENSIONS = {
    ".txt", ".ini", ".cfg", ".conf", ".json", ".xml", ".yaml", ".yml",
    ".toml", ".vdf", ".acf", ".reg", ".log", ".csv", ".tsv",
}
SAVE_EXTENSIONS = {".sav", ".save", ".dat", ".bin", ".slot", ".bak"}
BINARY_EXTENSIONS = {".exe", ".dll", ".so", ".bin"}
SKIP_DIR_NAMES = {
    ".git", "cache", "caches", "shadercache", "shader_cache", "temp", "tmp",
    "logs", "log", "crashdumps", "webcache", "code cache", "gpucache",
    "windows", "winsxs", "system32", "syswow64", "fonts", "installer",
}
SKIP_FILE_EXTENSIONS = {".pak", ".zip", ".7z", ".rar", ".zst", ".gz", ".xz", ".iso"}
MAX_TEXT_BYTES = 16 * 1024 * 1024
MAX_BINARY_BYTES = 128 * 1024 * 1024
MAX_SAVE_BYTES = 128 * 1024 * 1024
MAX_HITS_PER_FILE = 200


@dataclass(frozen=True)
class ScanRoot:
    label: str
    path: Path
    kind: str


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def safe_json(path: Path) -> dict:
    if not path.is_file() or path.is_symlink():
        raise ValueError(f"not a regular JSON file: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def validate_active(project_root: Path, game_root: Path) -> tuple[dict, list[dict]]:
    path = project_root / ".local/reports/quartet_legacy_dlc/validated_payloads/ACTIVE.json"
    active = safe_json(path)
    if active.get("type") != "validated_quartet_legacy_dlc_payload":
        raise ValueError("unexpected ACTIVE.json type")
    if active.get("generation") != 8:
        raise ValueError(f"generation 8 required, got {active.get('generation')}")
    if active.get("members") != EXPECTED_MEMBERS:
        raise ValueError("ACTIVE members are not exactly PC00-PC07")
    tx = active.get("transaction", {})
    if tx.get("all_or_none") is not True or tx.get("commit_enabled") is not False:
        raise ValueError("ACTIVE transaction policy mismatch")
    artifacts = active.get("artifacts", [])
    if len(artifacts) != 2 or {x.get("target_path") for x in artifacts} != TARGETS:
        raise ValueError("ACTIVE must declare exactly the two canonical targets")

    rows: list[dict] = []
    states: list[str] = []
    for artifact in sorted(artifacts, key=lambda x: x["target_path"]):
        target = artifact["target_path"]
        installed = game_root / Path(target)
        if not installed.is_file() or installed.is_symlink():
            state = "missing"
            actual_sha = ""
            size = 0
        else:
            actual_sha = sha256_file(installed)
            size = installed.stat().st_size
            if actual_sha == artifact["baseline_sha256"]:
                state = "baseline"
            elif actual_sha == artifact["candidate_sha256"]:
                state = "candidate"
            else:
                state = "other"
        states.append(state)
        rows.append({
            "target_path": target,
            "installed_state": state,
            "installed_size": size,
            "installed_sha256": actual_sha,
            "candidate_sha256": artifact["candidate_sha256"],
            "baseline_sha256": artifact["baseline_sha256"],
        })
    if not all(state == "baseline" for state in states):
        raise ValueError(f"full rollback baseline required for this audit, got {states}")
    return active, rows


def normalize_roots(original_dir: Path, quartet_dir: Path, state_roots: Sequence[Path]) -> list[ScanRoot]:
    roots = [
        ScanRoot("original_game", original_dir.resolve(), "game"),
        ScanRoot("quartet_game", quartet_dir.resolve(), "game"),
    ]
    for index, root in enumerate(state_roots, start=1):
        resolved = root.resolve()
        roots.append(ScanRoot(f"state_root_{index}", resolved, "state"))
    return roots


def should_skip_dir(path: Path) -> bool:
    return path.name.casefold() in SKIP_DIR_NAMES


def candidate_subroots(root: ScanRoot) -> list[Path]:
    path = root.path
    if root.kind == "game":
        return [path]
    candidates: list[Path] = []
    if (path / "drive_c/users").is_dir():
        candidates.append(path / "drive_c/users")
        for name in ("user.reg", "system.reg"):
            if (path / name).is_file():
                candidates.append(path / name)
    for rel in ("steam_settings", "settings", "config", "userdata", "remote"):
        if (path / rel).exists():
            candidates.append(path / rel)
    if not candidates:
        candidates.append(path)
    return candidates


def iter_files(scan_root: ScanRoot) -> Iterator[Path]:
    seen: set[Path] = set()
    for subroot in candidate_subroots(scan_root):
        if subroot.is_file():
            resolved = subroot.resolve()
            if resolved not in seen:
                seen.add(resolved)
                yield resolved
            continue
        for dirpath, dirnames, filenames in os.walk(subroot, followlinks=False):
            base = Path(dirpath)
            dirnames[:] = [d for d in dirnames if not should_skip_dir(base / d)]
            for filename in filenames:
                path = base / filename
                try:
                    if path.is_symlink() or not path.is_file():
                        continue
                    resolved = path.resolve()
                    if resolved in seen:
                        continue
                    seen.add(resolved)
                    yield resolved
                except OSError:
                    continue


def classify(path: Path) -> str:
    lower_name = path.name.casefold()
    suffix = path.suffix.casefold()
    lower_path = path.as_posix().casefold()
    if suffix in SAVE_EXTENSIONS or any(x in lower_name for x in ("save", "savedata", "systemdata", "profile")):
        return "save_or_state"
    if suffix in TEXT_EXTENSIONS or lower_name in {
        "steam_appid.txt", "dlc.txt", "cream_api.ini", "steam_emu.ini",
        "coldclientloader.ini", "koalageddon.config.json",
    }:
        return "text_config"
    if suffix in BINARY_EXTENSIONS:
        return "binary"
    if any(k in lower_path for k in ("steam_settings", "entitlement", "license", "dlc", "userdata", "remote")):
        return "state_metadata"
    return "other"


def relevant_file(path: Path, file_class: str) -> bool:
    if path.suffix.casefold() in SKIP_FILE_EXTENSIONS:
        return False
    size = path.stat().st_size
    if file_class == "text_config":
        return size <= MAX_TEXT_BYTES
    if file_class == "binary":
        return size <= MAX_BINARY_BYTES
    if file_class == "save_or_state":
        return size <= MAX_SAVE_BYTES
    if file_class == "state_metadata":
        return size <= MAX_TEXT_BYTES
    lower = path.as_posix().casefold()
    return size <= MAX_TEXT_BYTES and any(k in lower for k in KEYWORDS)


def decode_candidates(raw: bytes) -> list[tuple[str, str]]:
    outputs: list[tuple[str, str]] = []
    for encoding in ("utf-8-sig", "utf-16-le", "utf-16-be", "cp932", "latin-1"):
        try:
            text = raw.decode(encoding)
        except UnicodeDecodeError:
            continue
        if text and (encoding == "latin-1" or "\x00" not in text[:2048]):
            outputs.append((encoding, text))
    return outputs


def bounded_text_hits(raw: bytes) -> tuple[str, list[dict]]:
    best_encoding = "binary"
    hits: list[dict] = []
    lowered_keywords = tuple(k.casefold() for k in KEYWORDS + API_NAMES)
    for encoding, text in decode_candidates(raw):
        current: list[dict] = []
        for line_no, line in enumerate(text.splitlines(), start=1):
            folded = line.casefold()
            matched = sorted({k for k in lowered_keywords if k in folded})
            if not matched:
                continue
            clean = " ".join(line.strip().split())[:500]
            ids = sorted(set(re.findall(r"(?<!\d)\d{5,10}(?!\d)", line)))[:20]
            current.append({
                "line": line_no,
                "keywords": ",".join(matched),
                "numeric_ids": ",".join(ids),
                "snippet": clean,
            })
            if len(current) >= MAX_HITS_PER_FILE:
                break
        if len(current) > len(hits):
            best_encoding, hits = encoding, current
    return best_encoding, hits


def binary_hits(raw: bytes) -> list[dict]:
    hits: list[dict] = []
    needles = list(API_NAMES) + list(KEYWORDS)
    for needle in needles:
        for encoding, encoded in (("ascii", needle.encode("ascii", errors="ignore")), ("utf16le", needle.encode("utf-16-le"))):
            if not encoded:
                continue
            start = 0
            count = 0
            while True:
                offset = raw.lower().find(encoded.lower(), start)
                if offset < 0:
                    break
                hits.append({"needle": needle, "encoding": encoding, "offset": offset})
                count += 1
                if len(hits) >= MAX_HITS_PER_FILE or count >= 20:
                    return hits
                start = offset + max(1, len(encoded))
    return hits


def entropy_sample(path: Path) -> float:
    with path.open("rb") as handle:
        data = handle.read(1024 * 1024)
    if not data:
        return 0.0
    counts = [0] * 256
    for byte in data:
        counts[byte] += 1
    length = len(data)
    return round(-sum((c / length) * math.log2(c / length) for c in counts if c), 4)


def relative_label(scan_root: ScanRoot, path: Path) -> str:
    try:
        return path.relative_to(scan_root.path).as_posix()
    except ValueError:
        return path.name


def write_tsv(path: Path, rows: list[dict]) -> None:
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
            writer.writerow({k: json.dumps(v, ensure_ascii=False, sort_keys=True) if isinstance(v, (list, dict, bool)) else v for k, v in row.items()})


def run(project_root: Path, original_dir: Path, quartet_dir: Path, state_roots: Sequence[Path], output_dir: Path) -> dict:
    version = (project_root / "workstreams/quartet_legacy_dlc/VERSION").read_text(encoding="utf-8").strip()
    if version != TOOL_VERSION:
        raise ValueError(f"quartet_legacy_dlc {TOOL_VERSION} required, got {version}")
    acceptance = safe_json(project_root / "workstreams/quartet_legacy_dlc/DLC_BKN_DRY_GENERATION8_EXACT_AVAILABILITY_CLOSURE_ACCEPTANCE.json")
    if acceptance.get("status") != "accepted_for_read_only_save_entitlement_surface_audit":
        raise ValueError("exact availability closure acceptance is missing")
    active, install_rows = validate_active(project_root, quartet_dir)

    output_dir.mkdir(parents=True, exist_ok=False)
    roots = normalize_roots(original_dir, quartet_dir, state_roots)
    inventory_rows: list[dict] = []
    text_rows: list[dict] = []
    binary_rows: list[dict] = []
    failures: list[dict] = []

    for scan_root in roots:
        if not scan_root.path.exists():
            failures.append({"root": scan_root.label, "path": str(scan_root.path), "error": "missing_root"})
            continue
        for path in iter_files(scan_root):
            try:
                file_class = classify(path)
                if not relevant_file(path, file_class):
                    continue
                size = path.stat().st_size
                digest = sha256_file(path)
                row = {
                    "root": scan_root.label,
                    "root_kind": scan_root.kind,
                    "relative_path": relative_label(scan_root, path),
                    "file_class": file_class,
                    "size": size,
                    "sha256": digest,
                    "mtime_ns": path.stat().st_mtime_ns,
                    "entropy_first_mib": entropy_sample(path),
                    "raw_content_exported": False,
                }
                inventory_rows.append(row)
                raw = path.read_bytes()
                if file_class in {"text_config", "state_metadata", "save_or_state"}:
                    encoding, hits = bounded_text_hits(raw)
                    for hit in hits:
                        text_rows.append({**row, "detected_encoding": encoding, **hit})
                if file_class == "binary" or (file_class == "save_or_state" and not text_rows):
                    for hit in binary_hits(raw):
                        binary_rows.append({**row, **hit})
            except Exception as exc:  # evidence should preserve individual failures
                failures.append({"root": scan_root.label, "relative_path": relative_label(scan_root, path), "error": f"{type(exc).__name__}: {exc}"})

    write_tsv(output_dir / "INSTALLATION_ROLLBACK_STATE.tsv", install_rows)
    write_tsv(output_dir / "STATE_FILE_INVENTORY.tsv", inventory_rows)
    write_tsv(output_dir / "TEXT_ENTITLEMENT_REFERENCES.tsv", text_rows)
    write_tsv(output_dir / "BINARY_DLC_API_REFERENCES.tsv", binary_rows)
    write_tsv(output_dir / "SCAN_FAILURES.tsv", failures)

    api_names = sorted({row["needle"] for row in binary_rows if row.get("needle") in API_NAMES})
    candidate_state_files = [row for row in inventory_rows if row["file_class"] in {"save_or_state", "state_metadata"}]
    exact_owner_proven = False
    summary = {
        "type": "br_quartet_legacy_dlc_bkn_dry_generation8_save_entitlement_surface",
        "format_version": 1,
        "tool_version": TOOL_VERSION,
        "status": "save_entitlement_surface_collected_controlled_differential_required",
        "generation": 8,
        "members": EXPECTED_MEMBERS,
        "active_manifest_sha256": sha256_file(project_root / ".local/reports/quartet_legacy_dlc/validated_payloads/ACTIVE.json"),
        "runtime_status": "failed_at_costume_visibility_stage",
        "installation_state": "full_rollback_to_baseline",
        "scan": {
            "roots": [{"label": r.label, "kind": r.kind, "path_recorded": False} for r in roots],
            "files_inventoried": len(inventory_rows),
            "text_reference_rows": len(text_rows),
            "binary_reference_rows": len(binary_rows),
            "candidate_state_files": len(candidate_state_files),
            "failures": len(failures),
            "dlc_api_names": api_names,
        },
        "conclusion": {
            "exact_availability_owner_proven": exact_owner_proven,
            "candidate_state_or_entitlement_files_found": bool(candidate_state_files or text_rows or binary_rows),
            "controlled_before_after_differential_required": True,
            "next_payload_generation_allowed": False,
            "pc08_build_allowed": False,
            "core_change_required": False,
            "required_next_action": "review candidate save and entitlement surfaces, then capture checksum-only before/after snapshots around a known visible costume unlock or platform entitlement change",
        },
        "authorization": {
            "raw_save_export": False,
            "raw_registry_export": False,
            "candidate_build": False,
            "active_manifest_write": False,
            "prepare": False,
            "commit": False,
            "install": False,
            "runtime_validation": False,
            "core_modification": False,
            "translation_modification": False,
            "restoration_modification": False,
            "git_modification": False,
            "pc08_build": False,
        },
        "game_files_modified": False,
        "save_files_modified": False,
        "raw_contents_exported": False,
    }
    (output_dir / "SUMMARY.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (output_dir / "ACTIVE_GENERATION8.json").write_text(json.dumps(active, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (output_dir / "EXACT_AVAILABILITY_CLOSURE_ACCEPTANCE.json").write_text(json.dumps(acceptance, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return summary


def parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-root", type=Path, required=True)
    parser.add_argument("--original-dir", type=Path, required=True)
    parser.add_argument("--game-dir", type=Path, required=True)
    parser.add_argument("--state-root", type=Path, action="append", default=[])
    parser.add_argument("--output-dir", type=Path, required=True)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    try:
        summary = run(args.project_root.resolve(), args.original_dir.resolve(), args.game_dir.resolve(), [p.resolve() for p in args.state_root], args.output_dir.resolve())
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
