#!/usr/bin/env python3
"""Build and verify one local parent-Elixir repack for the Hinako bathroom river member.

Stage 69 wrote only the 252-byte river.bin candidate under .local/build. This
stage validates that report and local prototype, patches the same-size member in
the currently extracted Quartet Elixir payload, re-encodes the original
container kind, reopens the result and verifies every member. It writes only a
local candidate parent and local rollback copy; it never repacks a PAK, changes
registry state, activates a profile or writes to an installed game.
"""
from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
import os
import shutil
import struct
import subprocess
import sys
import tempfile
import zlib
from pathlib import Path, PurePosixPath
from typing import Any, Callable, Iterable, Mapping, Sequence

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT_DEFAULT = SCRIPT_DIR.parent.parent
TEXT_TOOL_DIR = PROJECT_ROOT_DEFAULT / "Blue_Reflection_Text_Tool"
for import_path in (SCRIPT_DIR, TEXT_TOOL_DIR):
    if str(import_path) not in sys.path:
        sys.path.insert(0, str(import_path))

import br_restoration_tool as BR  # noqa: E402
import build_bathroom_river_member_prototype as STAGE69  # noqa: E402

TOOL_VERSION = "0.0.80"
EXPECTED_STAGE69_TOOL_VERSION = "0.0.79"
REPORT_NAME = "BR_quartet_restoration_bathroom_river_parent_elixir_repack_test_evidence.tar.zst"
EVIDENCE_DIR_NAME = "bathroom_river_parent_elixir_repack_test_evidence"
STAGE69_DIR = "bathroom_river_member_prototype_evidence"
STAGE69_ARCHIVE = "BR_quartet_restoration_bathroom_river_member_prototype_evidence.tar.zst"
PROFILE_ID = "candidate_bathroom_river_parent_elixir_static_inverse_062e39915e7d"
SOURCE_PROFILE_ID = STAGE69.PROFILE_ID
PARENT_PATH = STAGE69.PARENT_PATH
MEMBER_KEY = STAGE69.MEMBER_KEY
EXPECTED_CANDIDATE_SHA256 = STAGE69.EXPECTED_CANDIDATE_SHA256
EXPECTED_TARGET_MEMBER_SHA256 = "2683b4e50507995c0ee779a3683b875fc76aa0fa1f63e17eff377c0731911a89"
EXPECTED_MEMBER_SIZE = STAGE69.EXPECTED_CANDIDATE_SIZE
EXPECTED_MEMBER_DISTANCE = STAGE69.EXPECTED_TARGET_DISTANCE
REPACK_SUBDIR = Path("repack_tests/bathroom_river_parent_elixir")


class BathroomRiverParentRepackError(RuntimeError):
    pass


def parse_bool(value: object) -> bool:
    return str(value).strip().casefold() in {"1", "true", "yes", "y"}


def parse_int(value: object, default: int = 0) -> int:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return default


def read_tsv(path: Path, *, required: bool = True) -> list[dict[str, str]]:
    if not path.is_file():
        if required:
            raise BathroomRiverParentRepackError(f"missing prerequisite table: {path}")
        return []
    with path.open("r", encoding="utf-8", newline="") as handle:
        return [dict(row) for row in csv.DictReader(handle, delimiter="\t")]


def write_tsv(path: Path, fields: Sequence[str], rows: Iterable[Mapping[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fields})


def load_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise BathroomRiverParentRepackError(f"missing prerequisite JSON: {path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise BathroomRiverParentRepackError(f"invalid JSON {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise BathroomRiverParentRepackError(f"expected JSON object: {path}")
    return value


def safe_member_name(raw: str) -> str:
    path = PurePosixPath(raw)
    if path.is_absolute() or not path.parts or ".." in path.parts:
        raise BathroomRiverParentRepackError(f"unsafe report archive member: {raw}")
    return path.as_posix()


def extract_archive(archive: Path, destination: Path) -> Path:
    if not archive.is_file():
        raise BathroomRiverParentRepackError(f"missing prerequisite report: {archive}")
    listed = subprocess.run(
        ["tar", "--zstd", "-tf", str(archive)], text=True,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False,
    )
    if listed.returncode:
        raise BathroomRiverParentRepackError(f"cannot list {archive}: {listed.stderr.strip()}")
    roots = {
        PurePosixPath(safe_member_name(line.strip())).parts[0]
        for line in listed.stdout.splitlines() if line.strip()
    }
    if len(roots) != 1:
        raise BathroomRiverParentRepackError(f"expected one report root in {archive}, found {sorted(roots)}")
    destination.mkdir(parents=True, exist_ok=True)
    done = subprocess.run(
        ["tar", "--zstd", "-xf", str(archive), "-C", str(destination)], text=True,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False,
    )
    if done.returncode:
        raise BathroomRiverParentRepackError(f"cannot extract {archive}: {done.stderr.strip()}")
    return destination / next(iter(roots))


def locate_report_root(report_root: Path, directory_name: str, archive_name: str, temporary: Path) -> Path:
    direct = report_root / directory_name
    if direct.is_dir():
        return direct
    return extract_archive(report_root / archive_name, temporary)


def atomic_bytes(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_bytes(data)
    os.replace(temporary, path)


def atomic_json(path: Path, value: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def make_report_archive(source_dir: Path, output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(output.name + ".tmp")
    temporary.unlink(missing_ok=True)
    done = subprocess.run(
        ["tar", "--zstd", "-cf", str(temporary), "-C", str(source_dir.parent), source_dir.name],
        text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False,
    )
    if done.returncode:
        raise BathroomRiverParentRepackError(f"cannot create report archive: {done.stderr.strip()}")
    os.replace(temporary, output)


def hamming_distance(left: bytes, right: bytes) -> int:
    if len(left) != len(right):
        raise BathroomRiverParentRepackError("cannot compare differently sized decoded parents")
    return sum(a != b for a, b in zip(left, right))


def validate_stage69(root: Path) -> tuple[dict[str, Any], dict[str, str], dict[str, str]]:
    summary = load_json(root / "SUMMARY.json")
    if summary.get("type") != "br_quartet_restoration_bathroom_river_member_prototype_evidence_summary":
        raise BathroomRiverParentRepackError("stage-69 report has an unexpected summary type")
    if summary.get("tool_version") != EXPECTED_STAGE69_TOOL_VERSION:
        raise BathroomRiverParentRepackError("stage-69 report must use tool version 0.0.79")
    if summary.get("status") != "exact_bathroom_river_member_prototype_built_not_repacked_or_installed":
        raise BathroomRiverParentRepackError("stage-69 report is not complete")
    expected = {
        "proposed_profile_rows": 1,
        "promoted_profile_rows": 1,
        "prototype_file_rows": 1,
        "selected_word_rows": 7,
        "validation_rows": 17,
        "validation_failures": 0,
        "skipped_rows": 0,
        "candidate_size": EXPECTED_MEMBER_SIZE,
        "candidate_distance_to_original": 0,
    }
    for field, value in expected.items():
        if parse_int(summary.get(field), -1) != value:
            raise BathroomRiverParentRepackError(f"stage-69 {field} must be {value}")
    if summary.get("candidate_sha256") != EXPECTED_CANDIDATE_SHA256:
        raise BathroomRiverParentRepackError("stage-69 candidate hash changed")
    policy = summary.get("policy") or {}
    if not isinstance(policy, dict):
        raise BathroomRiverParentRepackError("stage-69 policy is malformed")
    forbidden_true = (
        "installed_games_modified", "candidate_member_payload_exported_in_report",
        "parent_archive_repack_performed", "pak_repack_performed", "core_registry_modified",
        "activation_or_rollback_invoked", "runtime_validation_inferred",
        "censorship_classification_inferred", "opaque_binary_field_semantics_inferred",
        "opl2_payload_built", "translation_or_dlc_workstreams_modified",
    )
    for field in forbidden_true:
        if parse_bool(policy.get(field)):
            raise BathroomRiverParentRepackError(f"stage-69 policy field {field} must be false")
    if not parse_bool(policy.get("candidate_member_payload_written_only_under_local_workspace")):
        raise BathroomRiverParentRepackError("stage-69 local member prototype flag must be true")

    profiles = read_tsv(root / "BATHROOM_RIVER_MEMBER_PROTOTYPE_PROFILES.tsv")
    files = read_tsv(root / "BATHROOM_RIVER_MEMBER_PROTOTYPE_FILES.tsv")
    validations = read_tsv(root / "BATHROOM_RIVER_MEMBER_PROTOTYPE_VALIDATIONS.tsv")
    skipped = read_tsv(root / "BATHROOM_RIVER_MEMBER_PROTOTYPE_SKIPPED.tsv")
    if len(profiles) != 1 or len(files) != 1 or len(validations) != 17 or skipped:
        raise BathroomRiverParentRepackError("stage-69 report row counts changed")
    if any(not parse_bool(row.get("passed")) for row in validations):
        raise BathroomRiverParentRepackError("stage-69 contains a failed validation")
    profile = profiles[0]
    file_row = files[0]
    checks = {
        "profile_id": profile.get("profile_id") == SOURCE_PROFILE_ID,
        "parent_container": profile.get("parent_container") == PARENT_PATH,
        "member_key": profile.get("member_key") == MEMBER_KEY,
        "candidate_sha256": profile.get("candidate_sha256") == EXPECTED_CANDIDATE_SHA256,
        "candidate_size": parse_int(profile.get("candidate_size"), -1) == EXPECTED_MEMBER_SIZE,
        "selected_cell_count": parse_int(profile.get("selected_cell_count"), -1) == 7,
        "validation_status": profile.get("validation_status") == "passed",
        "semantics_unassigned": not parse_bool(profile.get("semantics_assigned")),
        "runtime_unvalidated": not parse_bool(profile.get("runtime_validated")),
        "file_source_hash": file_row.get("source_sha256") == EXPECTED_CANDIDATE_SHA256,
        "file_target_hash": file_row.get("target_sha256") == EXPECTED_TARGET_MEMBER_SHA256,
        "file_candidate_hash": file_row.get("candidate_sha256") == EXPECTED_CANDIDATE_SHA256,
        "file_sizes": all(parse_int(file_row.get(field), -1) == EXPECTED_MEMBER_SIZE for field in ("source_size", "target_size", "candidate_size")),
        "file_distance": parse_int(file_row.get("target_distance_to_source"), -1) == EXPECTED_MEMBER_DISTANCE,
        "file_candidate_exact": parse_int(file_row.get("candidate_distance_to_source"), -1) == 0,
    }
    failed = [name for name, passed in checks.items() if not passed]
    if failed:
        raise BathroomRiverParentRepackError("stage-69 canonical rows changed: " + ", ".join(failed))
    return summary, profile, file_row


def resolve_local_prototype(project_root: Path, profile_row: Mapping[str, str], file_row: Mapping[str, str]) -> tuple[Path, dict[str, Any], bytes]:
    root_text = str(profile_row.get("local_profile_root", ""))
    root_path = Path(root_text)
    if not root_path.is_absolute():
        root_path = project_root / root_path
    root_path = root_path.resolve()
    workspace = (project_root / ".local/build/quartet_restoration").resolve()
    if not root_path.is_relative_to(workspace):
        raise BathroomRiverParentRepackError("stage-69 local profile root escapes restoration workspace")
    manifest = load_json(root_path / "PROTOTYPE.json")
    if manifest.get("type") != "br_quartet_restoration_local_member_prototype":
        raise BathroomRiverParentRepackError("stage-69 local prototype manifest type changed")
    checks = {
        "profile_id": manifest.get("profile_id") == SOURCE_PROFILE_ID,
        "parent_container": manifest.get("parent_container") == PARENT_PATH,
        "member_key": manifest.get("member_key") == MEMBER_KEY,
        "candidate_sha256": manifest.get("candidate_sha256") == EXPECTED_CANDIDATE_SHA256,
        "candidate_size": parse_int(manifest.get("candidate_size"), -1) == EXPECTED_MEMBER_SIZE,
        "parent_not_rebuilt": not parse_bool(manifest.get("parent_archive_rebuilt")),
        "pak_not_repacked": not parse_bool(manifest.get("pak_repacked")),
        "game_not_modified": not parse_bool(manifest.get("installed_game_modified")),
        "semantics_unassigned": not parse_bool(manifest.get("semantics_assigned")),
        "runtime_unvalidated": not parse_bool(manifest.get("runtime_validated")),
    }
    failed = [name for name, passed in checks.items() if not passed]
    if failed:
        raise BathroomRiverParentRepackError("stage-69 local prototype manifest changed: " + ", ".join(failed))
    relative = PurePosixPath(safe_member_name(str(file_row.get("candidate_relative_path", ""))))
    candidate_path = root_path.joinpath(*relative.parts)
    if not candidate_path.is_file():
        raise BathroomRiverParentRepackError(f"missing stage-69 candidate member: {candidate_path}")
    payload = candidate_path.read_bytes()
    if len(payload) != EXPECTED_MEMBER_SIZE or hashlib.sha256(payload).hexdigest() != EXPECTED_CANDIDATE_SHA256:
        raise BathroomRiverParentRepackError("stage-69 candidate member bytes changed")
    return root_path, manifest, payload


def locate_target_parent(workspace_root: Path, report_root: Path) -> Path:
    matches: list[Path] = []
    for report in BR.load_report_jsons(report_root, "differences"):
        pair_id = str(report.get("source_archive_group", ""))
        for entry in report.get("entries", []):
            source_ref = entry.get("source") or {}
            target_ref = entry.get("target") or {}
            normalized = str(entry.get("normalized_path") or target_ref.get("normalized_path") or source_ref.get("normalized_path") or "")
            if normalized.casefold() != PARENT_PATH.casefold():
                continue
            if not target_ref:
                raise BathroomRiverParentRepackError("target parent reference is missing from inventory differences")
            local = BR.inventory_workspace_file(
                workspace_root, "target", pair_id, str(target_ref.get("archive", "")), str(target_ref.get("path", ""))
            )
            matches.append(local)
    unique = sorted({path.resolve() for path in matches}, key=str)
    if len(unique) != 1:
        raise BathroomRiverParentRepackError(f"expected one target parent workspace file, found {len(unique)}")
    if not unique[0].is_file():
        raise BathroomRiverParentRepackError(f"target parent workspace file is missing: {unique[0]}")
    return unique[0]


def parse_gust_chunks(raw: bytes) -> tuple[list[bytes], list[int]]:
    chunks: list[bytes] = []
    decoded_sizes: list[int] = []
    offset = 0
    while True:
        if offset + 4 > len(raw):
            raise BathroomRiverParentRepackError("truncated Gust chunk size")
        size = int.from_bytes(raw[offset:offset + 4], "little")
        offset += 4
        if size == 0:
            if offset != len(raw):
                raise BathroomRiverParentRepackError("trailing bytes after Gust chunk terminator")
            if not chunks:
                raise BathroomRiverParentRepackError("empty Gust chunked-zlib parent")
            return chunks, decoded_sizes
        if offset + size > len(raw):
            raise BathroomRiverParentRepackError("truncated Gust compressed chunk")
        compressed = raw[offset:offset + size]
        offset += size
        try:
            decoded = zlib.decompress(compressed)
        except zlib.error as exc:
            raise BathroomRiverParentRepackError(f"invalid Gust compressed chunk: {exc}") from exc
        chunks.append(compressed)
        decoded_sizes.append(len(decoded))


def decode_parent(path: Path, maximum_bytes: int) -> tuple[bytes, str, dict[str, Any]]:
    raw = path.read_bytes()
    decoded, container = BR.read_reference_payload(path, maximum_bytes)
    metadata: dict[str, Any] = {"raw": raw}
    if container == "gust_chunked_zlib":
        _chunks, sizes = parse_gust_chunks(raw)
        metadata["decoded_chunk_sizes"] = sizes
    elif container.startswith("prefixed_zlib"):
        prefix_size = parse_int(container.removeprefix("prefixed_zlib"), -1)
        if prefix_size < 0:
            raise BathroomRiverParentRepackError("invalid prefixed-zlib container label")
        metadata["prefix"] = raw[:prefix_size]
    elif container not in {"gzip", "zlib", "raw", "raw_unrecognized_gz"}:
        raise BathroomRiverParentRepackError(f"unsupported parent container kind: {container}")
    return decoded, container, metadata


def encode_parent(decoded: bytes, container: str, metadata: Mapping[str, Any]) -> bytes:
    if container == "gzip":
        return gzip.compress(decoded, compresslevel=9, mtime=0)
    if container == "zlib":
        return zlib.compress(decoded, level=9)
    if container.startswith("prefixed_zlib"):
        prefix = metadata.get("prefix")
        if not isinstance(prefix, (bytes, bytearray)):
            raise BathroomRiverParentRepackError("prefixed-zlib metadata lacks prefix bytes")
        return bytes(prefix) + zlib.compress(decoded, level=9)
    if container == "gust_chunked_zlib":
        sizes = metadata.get("decoded_chunk_sizes")
        if not isinstance(sizes, list) or not sizes or any(not isinstance(value, int) or value < 0 for value in sizes):
            raise BathroomRiverParentRepackError("Gust chunk metadata is malformed")
        if sum(sizes) != len(decoded):
            raise BathroomRiverParentRepackError("decoded parent size no longer matches Gust chunk boundaries")
        output = bytearray()
        offset = 0
        for size in sizes:
            compressed = zlib.compress(decoded[offset:offset + size], level=9)
            output.extend(len(compressed).to_bytes(4, "little"))
            output.extend(compressed)
            offset += size
        output.extend(b"\x00\x00\x00\x00")
        return bytes(output)
    if container in {"raw", "raw_unrecognized_gz"}:
        return decoded
    raise BathroomRiverParentRepackError(f"unsupported parent container kind: {container}")


def patch_member(decoded_target: bytes, candidate_member: bytes) -> tuple[bytes, dict[str, Any], dict[str, Any], list[dict[str, object]]]:
    before = BR.parse_earc_payload(decoded_target, label=PARENT_PATH, include_member_payloads=True)
    members = {str(row["comparison_key"]): row for row in before.get("members", [])}
    selected = members.get(MEMBER_KEY)
    if selected is None:
        raise BathroomRiverParentRepackError(f"target parent lacks selected member {MEMBER_KEY}")
    if parse_int(selected.get("size"), -1) != len(candidate_member):
        raise BathroomRiverParentRepackError("candidate member size differs from target parent entry")
    target_payload = selected.get("payload")
    if not isinstance(target_payload, (bytes, bytearray)):
        raise BathroomRiverParentRepackError("selected target member payload is unavailable")
    target_payload = bytes(target_payload)
    if hashlib.sha256(target_payload).hexdigest() != EXPECTED_TARGET_MEMBER_SHA256:
        raise BathroomRiverParentRepackError("selected target member hash differs from stage 69")
    start = parse_int(selected.get("offset"), -1)
    end = start + len(candidate_member)
    if start < 0 or end > len(decoded_target):
        raise BathroomRiverParentRepackError("selected target member bounds are invalid")
    patched = bytearray(decoded_target)
    patched[start:end] = candidate_member
    decoded_candidate = bytes(patched)
    after = BR.parse_earc_payload(decoded_candidate, label=PARENT_PATH + "#candidate", include_member_payloads=True)

    before_rows = {str(row["comparison_key"]): row for row in before.get("members", [])}
    after_rows = {str(row["comparison_key"]): row for row in after.get("members", [])}
    if set(before_rows) != set(after_rows):
        raise BathroomRiverParentRepackError("parent member keys changed after in-place patch")
    member_rows: list[dict[str, object]] = []
    for key in sorted(before_rows, key=str.casefold):
        left = before_rows[key]
        right = after_rows[key]
        classification = "changed_selected" if key == MEMBER_KEY else "unchanged"
        member_rows.append({
            "member_key": key,
            "member_name": left.get("name", ""),
            "target_index": left.get("index", ""),
            "candidate_index": right.get("index", ""),
            "target_offset": left.get("offset", ""),
            "candidate_offset": right.get("offset", ""),
            "target_size": left.get("size", ""),
            "candidate_size": right.get("size", ""),
            "target_sha256": left.get("sha256", ""),
            "candidate_sha256": right.get("sha256", ""),
            "classification": classification,
            "verified": (
                left.get("index") == right.get("index")
                and left.get("offset") == right.get("offset")
                and left.get("size") == right.get("size")
                and (
                    right.get("sha256") == EXPECTED_CANDIDATE_SHA256
                    if key == MEMBER_KEY else right.get("sha256") == left.get("sha256")
                )
            ),
        })
    return decoded_candidate, before, after, member_rows


def build(
    *, project_root: Path, workspace_root: Path, report_root: Path,
    maximum_earc_bytes: int = 512 * 1024 * 1024,
    target_parent_loader: Callable[[], Path] | None = None,
) -> tuple[Path, dict[str, Any]]:
    with tempfile.TemporaryDirectory(prefix="br-stage70-") as temporary_name:
        temporary = Path(temporary_name)
        stage69_root = locate_report_root(report_root, STAGE69_DIR, STAGE69_ARCHIVE, temporary / "stage69")
        stage69_summary, stage69_profile, stage69_file = validate_stage69(stage69_root)
        prototype_root, prototype_manifest, candidate_member = resolve_local_prototype(project_root, stage69_profile, stage69_file)
        target_parent = (target_parent_loader or (lambda: locate_target_parent(workspace_root, report_root)))().resolve()
        if not target_parent.is_file():
            raise BathroomRiverParentRepackError(f"target parent does not exist: {target_parent}")

        target_parent_hash_before = hashlib.sha256(target_parent.read_bytes()).hexdigest()
        decoded_target, container_kind, container_metadata = decode_parent(target_parent, maximum_earc_bytes)
        decoded_candidate, before_archive, after_archive, member_rows = patch_member(decoded_target, candidate_member)
        encoded_candidate = encode_parent(decoded_candidate, container_kind, container_metadata)

        repack_root = workspace_root / REPACK_SUBDIR
        if repack_root.exists():
            shutil.rmtree(repack_root)
        profile_root = repack_root / PROFILE_ID
        candidate_path = profile_root / "candidate" / PurePosixPath(PARENT_PATH)
        rollback_path = profile_root / "rollback" / PurePosixPath(PARENT_PATH)
        atomic_bytes(candidate_path, encoded_candidate)
        atomic_bytes(rollback_path, target_parent.read_bytes())

        decoded_reopened, reopened_kind, _reopened_metadata = decode_parent(candidate_path, maximum_earc_bytes)
        reopened_archive = BR.parse_earc_payload(decoded_reopened, label=str(candidate_path), include_member_payloads=True)
        reopened_rows = {str(row["comparison_key"]): row for row in reopened_archive.get("members", [])}
        candidate_parent_hash = hashlib.sha256(encoded_candidate).hexdigest()
        decoded_target_hash = hashlib.sha256(decoded_target).hexdigest()
        decoded_candidate_hash = hashlib.sha256(decoded_candidate).hexdigest()
        target_parent_hash_after = hashlib.sha256(target_parent.read_bytes()).hexdigest()
        table_end = parse_int(before_archive.get("header_size"), -1) + parse_int(before_archive.get("table_size"), -1)
        changed_rows = [row for row in member_rows if row["target_sha256"] != row["candidate_sha256"]]
        unchanged_rows = [row for row in member_rows if row["classification"] == "unchanged"]

        checks = {
            "stage69_report_canonical": stage69_summary.get("tool_version") == EXPECTED_STAGE69_TOOL_VERSION,
            "stage69_local_prototype_manifest_canonical": prototype_manifest.get("profile_id") == SOURCE_PROFILE_ID,
            "stage69_candidate_member_hash_matches": hashlib.sha256(candidate_member).hexdigest() == EXPECTED_CANDIDATE_SHA256,
            "target_parent_workspace_file_present": target_parent.is_file(),
            "target_parent_container_supported": container_kind in {"gzip", "zlib", "gust_chunked_zlib", "raw", "raw_unrecognized_gz"} or container_kind.startswith("prefixed_zlib"),
            "selected_member_present_once": sum(row["member_key"] == MEMBER_KEY for row in member_rows) == 1,
            "selected_target_member_hash_expected": next(row for row in member_rows if row["member_key"] == MEMBER_KEY)["target_sha256"] == EXPECTED_TARGET_MEMBER_SHA256,
            "selected_candidate_member_hash_expected": next(row for row in member_rows if row["member_key"] == MEMBER_KEY)["candidate_sha256"] == EXPECTED_CANDIDATE_SHA256,
            "selected_member_size_preserved": next(row for row in member_rows if row["member_key"] == MEMBER_KEY)["candidate_size"] == EXPECTED_MEMBER_SIZE,
            "decoded_parent_size_preserved": len(decoded_candidate) == len(decoded_target),
            "earc_header_and_table_preserved": decoded_candidate[:table_end] == decoded_target[:table_end],
            "earc_file_count_preserved": before_archive.get("file_count") == after_archive.get("file_count") == reopened_archive.get("file_count"),
            "earc_member_keys_preserved": set(reopened_rows) == {row["member_key"] for row in member_rows},
            "exactly_one_member_changed": len(changed_rows) == 1 and changed_rows[0]["member_key"] == MEMBER_KEY,
            "all_other_members_preserved": len(unchanged_rows) + 1 == len(member_rows) and all(parse_bool(row["verified"]) for row in unchanged_rows),
            "selected_member_verified": parse_bool(next(row for row in member_rows if row["member_key"] == MEMBER_KEY)["verified"]),
            "decoded_parent_distance_expected": hamming_distance(decoded_target, decoded_candidate) == EXPECTED_MEMBER_DISTANCE,
            "candidate_parent_reopens_exactly": decoded_reopened == decoded_candidate,
            "candidate_container_kind_preserved": reopened_kind == container_kind,
            "reopened_selected_member_hash_expected": reopened_rows.get(MEMBER_KEY, {}).get("sha256") == EXPECTED_CANDIDATE_SHA256,
            "reopened_all_other_members_preserved": all(
                reopened_rows.get(row["member_key"], {}).get("sha256") == row["target_sha256"]
                for row in unchanged_rows
            ),
            "rollback_copy_exact_target_parent": hashlib.sha256(rollback_path.read_bytes()).hexdigest() == target_parent_hash_before,
            "installed_workspace_parent_unchanged": target_parent_hash_after == target_parent_hash_before,
            "candidate_and_rollback_are_local_only": candidate_path.is_relative_to(workspace_root) and rollback_path.is_relative_to(workspace_root),
            "no_opl2_member_changed": all(not (row["member_key"].endswith(".opl2#0") and row["classification"] != "unchanged") for row in member_rows),
        }
        validation_rows = [
            {
                "profile_id": PROFILE_ID,
                "parent_container": PARENT_PATH,
                "check_name": name,
                "passed": passed,
                "review_status": "local_parent_elixir_repack_validation",
            }
            for name, passed in checks.items()
        ]
        failures = [name for name, passed in checks.items() if not passed]
        skipped_rows: list[dict[str, object]] = []
        profile_rows: list[dict[str, object]] = []
        file_rows: list[dict[str, object]] = []

        if failures:
            shutil.rmtree(profile_root, ignore_errors=True)
            skipped_rows.append({"profile_id": PROFILE_ID, "parent_container": PARENT_PATH, "reason": "parent_repack_validation_failed:" + ";".join(failures)})
        else:
            manifest = {
                "type": "br_quartet_restoration_local_parent_elixir_repack_test",
                "format_version": 1,
                "tool_version": TOOL_VERSION,
                "profile_id": PROFILE_ID,
                "source_profile_id": SOURCE_PROFILE_ID,
                "classification": "single_member_same_size_parent_elixir_repack_test",
                "parent_container": PARENT_PATH,
                "selected_member_key": MEMBER_KEY,
                "container_kind": container_kind,
                "target_parent_sha256": target_parent_hash_before,
                "candidate_parent_sha256": candidate_parent_hash,
                "rollback_parent_sha256": target_parent_hash_before,
                "decoded_target_sha256": decoded_target_hash,
                "decoded_candidate_sha256": decoded_candidate_hash,
                "target_parent_size": target_parent.stat().st_size,
                "candidate_parent_size": len(encoded_candidate),
                "decoded_parent_size": len(decoded_candidate),
                "member_count": len(member_rows),
                "changed_member_count": 1,
                "unchanged_member_count": len(unchanged_rows),
                "selected_member_target_sha256": EXPECTED_TARGET_MEMBER_SHA256,
                "selected_member_candidate_sha256": EXPECTED_CANDIDATE_SHA256,
                "candidate_relative_path": candidate_path.relative_to(profile_root).as_posix(),
                "rollback_relative_path": rollback_path.relative_to(profile_root).as_posix(),
                "semantics_assigned": False,
                "runtime_validated": False,
                "pak_repacked": False,
                "core_registry_modified": False,
                "installed_game_modified": False,
            }
            atomic_json(profile_root / "REPACK_TEST.json", manifest)
            profile_rows.append({
                "profile_id": PROFILE_ID,
                "source_profile_id": SOURCE_PROFILE_ID,
                "classification": manifest["classification"],
                "parent_container": PARENT_PATH,
                "selected_member_key": MEMBER_KEY,
                "container_kind": container_kind,
                "member_count": len(member_rows),
                "changed_member_count": 1,
                "unchanged_member_count": len(unchanged_rows),
                "target_parent_sha256": target_parent_hash_before,
                "candidate_parent_sha256": candidate_parent_hash,
                "rollback_parent_sha256": target_parent_hash_before,
                "local_profile_root": str(profile_root.relative_to(project_root)) if profile_root.is_relative_to(project_root) else str(profile_root),
                "validation_status": "passed",
                "runtime_validated": False,
                "review_status": "local_parent_elixir_only_not_pak_repacked_not_registered_not_installed",
            })
            file_rows.append({
                "profile_id": PROFILE_ID,
                "parent_container": PARENT_PATH,
                "container_kind": container_kind,
                "target_parent_sha256": target_parent_hash_before,
                "candidate_parent_sha256": candidate_parent_hash,
                "target_parent_size": target_parent.stat().st_size,
                "candidate_parent_size": len(encoded_candidate),
                "decoded_target_sha256": decoded_target_hash,
                "decoded_candidate_sha256": decoded_candidate_hash,
                "decoded_parent_size": len(decoded_candidate),
                "decoded_distance": hamming_distance(decoded_target, decoded_candidate),
                "candidate_relative_path": candidate_path.relative_to(profile_root).as_posix(),
                "rollback_relative_path": rollback_path.relative_to(profile_root).as_posix(),
            })

        outdir = report_root / EVIDENCE_DIR_NAME
        if outdir.exists():
            shutil.rmtree(outdir)
        outdir.mkdir(parents=True, exist_ok=True)
        write_tsv(outdir / "BATHROOM_RIVER_PARENT_ELIXIR_REPACK_PROFILES.tsv", [
            "profile_id", "source_profile_id", "classification", "parent_container", "selected_member_key",
            "container_kind", "member_count", "changed_member_count", "unchanged_member_count",
            "target_parent_sha256", "candidate_parent_sha256", "rollback_parent_sha256",
            "local_profile_root", "validation_status", "runtime_validated", "review_status",
        ], profile_rows)
        write_tsv(outdir / "BATHROOM_RIVER_PARENT_ELIXIR_REPACK_FILES.tsv", [
            "profile_id", "parent_container", "container_kind", "target_parent_sha256", "candidate_parent_sha256",
            "target_parent_size", "candidate_parent_size", "decoded_target_sha256", "decoded_candidate_sha256",
            "decoded_parent_size", "decoded_distance", "candidate_relative_path", "rollback_relative_path",
        ], file_rows)
        write_tsv(outdir / "BATHROOM_RIVER_PARENT_ELIXIR_REPACK_MEMBERS.tsv", [
            "member_key", "member_name", "target_index", "candidate_index", "target_offset", "candidate_offset",
            "target_size", "candidate_size", "target_sha256", "candidate_sha256", "classification", "verified",
        ], member_rows)
        write_tsv(outdir / "BATHROOM_RIVER_PARENT_ELIXIR_REPACK_VALIDATIONS.tsv", [
            "profile_id", "parent_container", "check_name", "passed", "review_status",
        ], validation_rows)
        write_tsv(outdir / "BATHROOM_RIVER_PARENT_ELIXIR_REPACK_SKIPPED.tsv", [
            "profile_id", "parent_container", "reason",
        ], skipped_rows)
        summary = {
            "type": "br_quartet_restoration_bathroom_river_parent_elixir_repack_test_evidence_summary",
            "format_version": 1,
            "tool_version": TOOL_VERSION,
            "source_stage69_tool_version": EXPECTED_STAGE69_TOOL_VERSION,
            "status": "bathroom_river_parent_elixir_local_repack_verified_not_pak_repacked_or_installed" if profile_rows else "bathroom_river_parent_elixir_local_repack_not_built",
            "proposed_profile_rows": 1,
            "repacked_profile_rows": len(profile_rows),
            "parent_file_rows": len(file_rows),
            "member_rows": len(member_rows),
            "changed_member_rows": len(changed_rows),
            "unchanged_member_rows": len(unchanged_rows),
            "validation_rows": len(validation_rows),
            "validation_failures": sum(not parse_bool(row.get("passed")) for row in validation_rows),
            "skipped_rows": len(skipped_rows),
            "container_kind": container_kind,
            "selected_member_key": MEMBER_KEY,
            "selected_member_candidate_sha256": EXPECTED_CANDIDATE_SHA256 if profile_rows else "",
            "target_parent_sha256": target_parent_hash_before if profile_rows else "",
            "candidate_parent_sha256": candidate_parent_hash if profile_rows else "",
            "decoded_parent_distance": EXPECTED_MEMBER_DISTANCE if profile_rows else None,
            "policy": {
                "installed_games_modified": False,
                "candidate_parent_written_only_under_local_workspace": True,
                "rollback_parent_written_only_under_local_workspace": True,
                "candidate_parent_payload_exported_in_report": False,
                "selected_member_payload_exported_in_report": False,
                "pak_repack_performed": False,
                "core_registry_modified": False,
                "activation_or_rollback_invoked": False,
                "runtime_validation_inferred": False,
                "censorship_classification_inferred": False,
                "opaque_binary_field_semantics_inferred": False,
                "opl2_payload_modified": False,
                "translation_or_dlc_workstreams_modified": False,
            },
            "next_action": "Upload this metadata report. If repacked_profile_rows is 1 with zero failures/skips and exactly one changed member, prepare a separate local containing-PAK repack test next; do not modify registry, activate or write to the game yet.",
        }
        atomic_json(outdir / "SUMMARY.json", summary)
        output = report_root / REPORT_NAME
        make_report_archive(outdir, output)
        return output, summary


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path, default=PROJECT_ROOT_DEFAULT)
    parser.add_argument("--workspace-root", type=Path)
    parser.add_argument("--report-root", type=Path)
    parser.add_argument("--maximum-earc-bytes", type=int, default=512 * 1024 * 1024)
    args = parser.parse_args(argv)
    project_root = args.project_root.resolve()
    workspace_root = (args.workspace_root or project_root / ".local/build/quartet_restoration").resolve()
    report_root = (args.report_root or project_root / ".local/reports/quartet_restoration").resolve()
    try:
        output, summary = build(
            project_root=project_root,
            workspace_root=workspace_root,
            report_root=report_root,
            maximum_earc_bytes=args.maximum_earc_bytes,
        )
    except (BathroomRiverParentRepackError, STAGE69.BathroomRiverPrototypeError, BR.RestorationError, OSError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print(f"Bathroom river parent Elixir repacks built: {summary['repacked_profile_rows']}")
    print(f"Changed members: {summary['changed_member_rows']}")
    print(f"Unchanged members verified: {summary['unchanged_member_rows']}")
    print(f"Validation failures: {summary['validation_failures']}")
    print(f"Report: {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
