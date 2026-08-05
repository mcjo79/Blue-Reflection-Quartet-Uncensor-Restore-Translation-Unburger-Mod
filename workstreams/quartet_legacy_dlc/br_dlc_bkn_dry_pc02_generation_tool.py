#!/usr/bin/env python3
"""Build a local PC00+PC01+PC02 dry-BKN two-archive family candidate.

The accepted generation-2 PC00+PC01 PACK10_02/PACK12 candidates are immutable parent inputs. This
stage appends only the PC02 dry parent/G1T to the accepted PACK10_02 candidate
and patches only PC02_DLC_BKN Model/defaultTexture in the accepted PACK12
candidate. Installed game archives and accepted generation-2 PC00+PC01 candidates remain read-only.
No transaction, installation, profile registration or runtime validation occurs.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT_DEFAULT = SCRIPT_DIR.parent.parent
TEXT_TOOL_DIR = PROJECT_ROOT_DEFAULT / "Blue_Reflection_Text_Tool"
for item in (SCRIPT_DIR, TEXT_TOOL_DIR):
    if str(item) not in sys.path:
        sys.path.insert(0, str(item))

import br_dlc_bkn_dry_pack12_repack_tool as PACK12_BASE  # noqa: E402
import br_dlc_dry_pak_insertion_tool as PACK10_BASE  # noqa: E402
import br_dlc_nested_container_tool as NESTED  # noqa: E402
import br_dlc_transfer_probe_tool as TRANSFER_BASE  # noqa: E402
import br_restoration_tool as BR  # noqa: E402

TOOL_VERSION = "0.0.45"
FORMAT_VERSION = 1
ACCEPTANCE_RELATIVE = Path("workstreams/quartet_legacy_dlc/DLC_BKN_DRY_PC02_GENERATION_ACCEPTANCE.json")
BUILD_RELATIVE = Path(".local/build/quartet_legacy_dlc/family_expansion/costume_pc00_pc01_pc02_bkn_dry")
REPORT_DIR_NAME = "bkn_dry_pc02_family_candidate_evidence"
REPORT_ARCHIVE_BASENAME = "BR_QUARTET_DLC_BKN_DRY_PC02_FAMILY_CANDIDATE"
TARGET_PACK10 = Path("Data/PACK10_02.PAK")
TARGET_PACK12 = Path("Data/PACK12.PAK")
TARGET_CHARABASE = "saves/b1/chara/charabase.xml"
FREE_SPACE_MARGIN = 256 * 1024 * 1024
COPY_BLOCK_SIZE = 8 * 1024 * 1024
FORBIDDEN_REPORT_SUFFIXES = {
    ".pak", ".xml", ".ebm", ".ebd", ".g1m", ".g1t", ".g1a", ".g1e",
    ".g1s", ".elixir", ".gz", ".bin", ".swg", ".dds", ".wav", ".ogg",
}


class Pc02FamilyCandidateError(RuntimeError):
    pass


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(COPY_BLOCK_SIZE), b""):
            digest.update(block)
    return digest.hexdigest()


def sha256_region(path: Path, offset: int, size: int) -> str:
    digest = hashlib.sha256()
    remaining = size
    with path.open("rb") as handle:
        handle.seek(offset)
        while remaining:
            block = handle.read(min(COPY_BLOCK_SIZE, remaining))
            if not block:
                raise Pc02FamilyCandidateError(f"truncated region while hashing: {path}")
            digest.update(block)
            remaining -= len(block)
    return digest.hexdigest()


def scalar(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (list, tuple, set, dict)):
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return str(value)


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")


def write_tsv(path: Path, fields: Sequence[str], rows: Iterable[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(fields), delimiter="\t", lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow({field: scalar(row.get(field, "")) for field in fields})


def read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise Pc02FamilyCandidateError(f"could not read JSON {path}: {exc}") from exc


def clean_dir(path: Path) -> None:
    if path.exists():
        shutil.rmtree(path)
    path.mkdir(parents=True, exist_ok=True)


def fsync_file(path: Path) -> None:
    with path.open("rb") as handle:
        os.fsync(handle.fileno())


def copy_region(source: Path, offset: int, size: int, output: Any) -> None:
    remaining = size
    with source.open("rb") as handle:
        handle.seek(offset)
        while remaining:
            block = handle.read(min(COPY_BLOCK_SIZE, remaining))
            if not block:
                raise Pc02FamilyCandidateError(f"truncated source region: {source}")
            output.write(block)
            remaining -= len(block)


def report_manifest(root: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for path in sorted(root.rglob("*"), key=lambda p: p.relative_to(root).as_posix().casefold()):
        if not path.is_file() or path.name == "REPORT_MANIFEST.json":
            continue
        if any(suffix.casefold() in FORBIDDEN_REPORT_SUFFIXES for suffix in path.suffixes):
            raise Pc02FamilyCandidateError(f"raw asset-like file in report: {path}")
        rows.append({
            "path": path.relative_to(root).as_posix(),
            "size": path.stat().st_size,
            "sha256": sha256_file(path),
        })
    return rows


def make_archive(source: Path, output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="br_dlc_pc02_family_bundle_") as temp_name:
        temporary_tar = Path(temp_name) / "report.tar"
        with tarfile.open(temporary_tar, "w", format=tarfile.PAX_FORMAT) as archive:
            for path in sorted(source.rglob("*"), key=lambda p: p.relative_to(source).as_posix().casefold()):
                if not path.is_file():
                    continue
                info = archive.gettarinfo(str(path), arcname=f"{source.name}/{path.relative_to(source).as_posix()}")
                info.uid = info.gid = 0
                info.uname = info.gname = ""
                info.mtime = 0
                with path.open("rb") as handle:
                    archive.addfile(info, handle)
        subprocess.run(["zstd", "-q", "-f", "-19", str(temporary_tar), "-o", str(output)], check=True)


def require_file_identity(path: Path, *, size: int, sha256: str, label: str) -> None:
    if not path.is_file():
        raise Pc02FamilyCandidateError(f"missing {label}: {path}")
    actual_size = path.stat().st_size
    if actual_size != size:
        raise Pc02FamilyCandidateError(f"{label} size mismatch: {actual_size} != {size}")
    actual_hash = sha256_file(path)
    if actual_hash != sha256:
        raise Pc02FamilyCandidateError(f"{label} SHA-256 mismatch: {actual_hash} != {sha256}")


def locate_archive(root: Path, relative: str) -> Path:
    direct = root / Path(relative)
    if direct.is_file():
        return direct
    name = Path(relative).name.casefold()
    candidates = [path for path in root.rglob("*") if path.is_file() and path.name.casefold() == name]
    if len(candidates) != 1:
        raise Pc02FamilyCandidateError(f"could not uniquely locate {relative} under {root}")
    return candidates[0]


def load_acceptance(project_root: Path) -> dict[str, Any]:
    path = project_root / ACCEPTANCE_RELATIVE
    acceptance = read_json(path)
    if acceptance.get("type") != "br_quartet_legacy_dlc_bkn_dry_pc02_generation_acceptance":
        raise Pc02FamilyCandidateError("unexpected PC02 acceptance type")
    if acceptance.get("status") != "accepted_for_checksum_gated_local_pc00_pc01_pc02_generation":
        raise Pc02FamilyCandidateError("PC02 parameterization is not accepted for local family build")
    auth = acceptance.get("authorization", {})
    if auth.get("local_candidate_build") is not True:
        raise Pc02FamilyCandidateError("local candidate build is not authorized")
    for key in (
        "prepare", "commit", "installation", "profile_registration", "runtime_validation",
        "wet_bkn", "translation_modification", "restoration_modification", "core_modification",
        "git_modification",
    ):
        if auth.get(key) is not False:
            raise Pc02FamilyCandidateError(f"acceptance does not fail closed for {key}")
    source_evidence = acceptance.get("source_evidence", {})
    if source_evidence.get("family_expansion_sha256") != "7c3e88602fd6408f30fabac378561eb6858ae44f4df39777943329c2a035974a":
        raise Pc02FamilyCandidateError("family-expansion evidence gate mismatch")
    if source_evidence.get("generic_generation2_preview_sha256") != "a07293b236a43fc2e8e7df4e923587e86749a550087105c6e781e9e5d13af13a":
        raise Pc02FamilyCandidateError("generation-2 generic preview gate mismatch")
    if source_evidence.get("selected_character_id") != "PC02" or source_evidence.get("validation_status") != "pass":
        raise Pc02FamilyCandidateError("PC02 generation acceptance is incomplete")
    return acceptance


def validate_helper_sources(project_root: Path, acceptance: Mapping[str, Any]) -> list[dict[str, Any]]:
    gates = acceptance.get("helper_source_gates", {})
    rows: list[dict[str, Any]] = []
    for name, expected in sorted(gates.items()):
        path = project_root / "workstreams/quartet_legacy_dlc" / name
        if not path.is_file():
            raise Pc02FamilyCandidateError(f"missing helper source: {path}")
        actual = sha256_file(path)
        if actual != expected:
            raise Pc02FamilyCandidateError(f"helper source changed since accepted generation-2 evidence: {name}: {actual} != {expected}")
        rows.append({"path": f"workstreams/quartet_legacy_dlc/{name}", "sha256": actual, "status": "passed"})
    return rows


def source_asset_rows(acceptance: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    rows = {str(row["role"]): dict(row) for row in acceptance.get("source_assets", [])}
    if set(rows) != {"dry_parent", "dry_external_texture"}:
        raise Pc02FamilyCandidateError("acceptance must declare exactly the PC02 dry parent and external texture")
    return rows


def copy_payload(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)
    fsync_file(path)


def extract_pc02_assets(
    project_root: Path,
    original_root: Path,
    build_root: Path,
    acceptance: Mapping[str, Any],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, bytes]]:
    specs = source_asset_rows(acceptance)
    archive_cache: dict[str, NESTED.PakIndex] = {}
    payloads: dict[str, bytes] = {}
    source_rows: list[dict[str, Any]] = []
    source_stats: dict[Path, tuple[int, int]] = {}
    for role, spec in specs.items():
        archive = locate_archive(original_root, str(spec["source_archive"]))
        if archive not in source_stats:
            stat = archive.stat()
            source_stats[archive] = (stat.st_size, stat.st_mtime_ns)
        key = str(archive.resolve())
        if key not in archive_cache:
            archive_cache[key] = NESTED.index_pak(archive)
        payload, entry = NESTED.read_pak_member(archive_cache[key], str(spec["source_member"]))
        if len(payload) != int(spec["size"]) or sha256_bytes(payload) != spec["sha256"]:
            raise Pc02FamilyCandidateError(f"PC02 {role} no longer matches accepted PC02 source evidence")
        local_path = build_root / "source_exact" / str(spec["source_member"])
        copy_payload(local_path, payload)
        payloads[role] = payload
        source_rows.append({
            "role": role,
            "source_archive": str(spec["source_archive"]),
            "source_member": str(spec["source_member"]),
            "source_entry_index": entry.index,
            "target_member": str(spec["target_member"]),
            "size": len(payload),
            "sha256": sha256_bytes(payload),
            "local_relative_path": local_path.relative_to(project_root).as_posix(),
            "raw_payload_exported_in_report": False,
        })
    for archive, before in source_stats.items():
        after = archive.stat()
        if before != (after.st_size, after.st_mtime_ns):
            raise Pc02FamilyCandidateError(f"source archive changed during read-only extraction: {archive}")

    parent = payloads["dry_parent"]
    parent_spec = specs["dry_parent"]
    decoded, decoded_sizes, _compressed_sizes = TRANSFER_BASE.gust_chunk_layout(parent, str(parent_spec["source_member"]))
    roundtrip = TRANSFER_BASE.encode_gust_chunks(decoded, decoded_sizes)
    roundtrip_decoded, roundtrip_sizes, _ = TRANSFER_BASE.gust_chunk_layout(roundtrip, "PC02 dry parent roundtrip")
    if roundtrip_decoded != decoded or roundtrip_sizes != decoded_sizes:
        raise Pc02FamilyCandidateError("PC02 dry parent wrapper roundtrip changed decoded bytes")
    source_earc = BR.parse_earc_payload(decoded, label="PC02 BKN dry source", include_member_payloads=True)
    roundtrip_earc = BR.parse_earc_payload(roundtrip_decoded, label="PC02 BKN dry roundtrip", include_member_payloads=True)
    source_inventory = [(row["name"], row["sha256"], row["size"]) for row in source_earc["members"]]
    roundtrip_inventory = [(row["name"], row["sha256"], row["size"]) for row in roundtrip_earc["members"]]
    if source_inventory != roundtrip_inventory:
        raise Pc02FamilyCandidateError("PC02 nested inventory changed during wrapper roundtrip")
    roundtrip_path = build_root / "roundtrip" / str(parent_spec["source_member"])
    copy_payload(roundtrip_path, roundtrip)
    nested_rows = [
        {
            "member_name": row["name"],
            "member_key": row["comparison_key"],
            "member_size": row["size"],
            "source_sha256": row["sha256"],
            "roundtrip_sha256": row["sha256"],
            "roundtrip_identical": True,
            "raw_payload_exported_in_report": False,
        }
        for row in source_earc["members"]
    ]
    return source_rows, nested_rows, payloads


def run_gust_list(gust_pak: Path, candidate: Path, required_members: Sequence[str], log_path: Path, timeout: int) -> dict[str, Any]:
    if not gust_pak.is_file() or not os.access(gust_pak, os.X_OK):
        raise Pc02FamilyCandidateError(f"gust_pak is not executable: {gust_pak}")
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("wb") as log:
        try:
            result = subprocess.run(
                [str(gust_pak), "-l", str(candidate)],
                stdin=subprocess.DEVNULL,
                stdout=log,
                stderr=subprocess.STDOUT,
                timeout=timeout,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise Pc02FamilyCandidateError(f"gust_pak listing timed out after {timeout}s") from exc
    text = log_path.read_text(encoding="utf-8", errors="replace")
    normalized = text.replace("\\", "/").casefold()
    missing = [member for member in required_members if member.casefold() not in normalized]
    if result.returncode != 0 or missing:
        tail = "\n".join(text.splitlines()[-20:])
        raise Pc02FamilyCandidateError(
            f"gust_pak list validation failed (exit {result.returncode}, missing={missing})\n{tail}"
        )
    return {
        "returncode": result.returncode,
        "log_size": log_path.stat().st_size,
        "log_sha256": sha256_file(log_path),
        "required_member_count": len(required_members),
        "required_members_found": True,
        "detected_format_line": next((line for line in text.splitlines() if line.startswith("Detected ")), ""),
        "master_key_line": next((line for line in text.splitlines() if line.startswith("Using ")), ""),
    }


def build_pack10_family_candidate(
    project_root: Path,
    quartet_root: Path,
    gust_pak: Path,
    build_root: Path,
    acceptance: Mapping[str, Any],
    payloads: Mapping[str, bytes],
    *,
    timeout: int,
) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]:
    parents = {Path(row["target_path"]).name: row for row in acceptance["accepted_generation2_parent_candidates"]}
    baselines = {Path(row["relative_path"]).name: row for row in acceptance["installed_baselines"]}
    parent_meta = parents["PACK10_02.PAK"]
    installed_meta = baselines["PACK10_02.PAK"]
    parent_pak = project_root / parent_meta["relative_path"]
    installed_pak = quartet_root / installed_meta["relative_path"]
    require_file_identity(parent_pak, size=int(parent_meta["size"]), sha256=parent_meta["sha256"], label="accepted generation-2 PC00+PC01 PACK10_02 candidate")
    require_file_identity(installed_pak, size=int(installed_meta["size"]), sha256=installed_meta["sha256"], label="installed PACK10_02 baseline")
    parent_stat = parent_pak.stat()
    installed_stat = installed_pak.stat()

    parent_index = NESTED.index_pak(parent_pak)
    layout = PACK10_BASE.read_raw_layout(parent_pak, parent_index)
    specs = source_asset_rows(acceptance)
    additions = []
    for role in ("dry_parent", "dry_external_texture"):
        spec = specs[role]
        target_name = str(spec["target_member"])
        if parent_index.by_name.get(NESTED.safe_internal_name(target_name).casefold()):
            raise Pc02FamilyCandidateError(f"accepted generation-2 PC00+PC01 candidate already contains PC02 member: {target_name}")
        additions.append({
            "role": role,
            "target_path": target_name,
            "data": payloads[role],
            "size": len(payloads[role]),
            "sha256": sha256_bytes(payloads[role]),
        })

    output_size = parent_pak.stat().st_size + len(additions) * layout.entry_struct.size + sum(row["size"] for row in additions)
    free = shutil.disk_usage(build_root).free
    if free < output_size + FREE_SPACE_MARGIN:
        raise Pc02FamilyCandidateError(f"insufficient free space for PACK10_02 family candidate: need {output_size + FREE_SPACE_MARGIN}, have {free}")

    candidate_dir = build_root / "candidate"
    candidate_dir.mkdir(parents=True, exist_ok=True)
    candidate = candidate_dir / "PACK10_02.PAK"
    temporary = candidate_dir / ".PACK10_02.PAK.tmp"
    master_key = PACK10_BASE.master_key_bytes(parent_index.master_key_label)
    raw_entries: list[bytes] = []
    encoded_payloads: list[bytes] = []
    added_metadata: list[dict[str, Any]] = []
    relative_offset = layout.raw_data_size
    for item in additions:
        raw_entry, encoded, metadata = PACK10_BASE.build_raw_added_entry(
            target_path=item["target_path"],
            payload=item["data"],
            relative_offset=relative_offset,
            layout=layout,
            master_key=master_key,
        )
        raw_entries.append(raw_entry)
        encoded_payloads.append(encoded)
        added_metadata.append({**metadata, "role": item["role"], "source_size": item["size"], "source_sha256": item["sha256"]})
        relative_offset += len(encoded)

    new_header = NESTED.PAK_HEADER.pack(layout.version, layout.file_count + len(additions), layout.header_size, layout.flags)
    try:
        with temporary.open("wb") as output:
            output.write(new_header)
            output.write(layout.raw_table)
            for raw_entry in raw_entries:
                output.write(raw_entry)
            copy_region(parent_pak, parent_index.file_data_offset, layout.raw_data_size, output)
            for encoded in encoded_payloads:
                output.write(encoded)
            output.flush()
            os.fsync(output.fileno())
        if temporary.stat().st_size != output_size:
            raise Pc02FamilyCandidateError(f"PACK10_02 candidate size mismatch: {temporary.stat().st_size} != {output_size}")
        os.replace(temporary, candidate)
        fsync_file(candidate)
    finally:
        temporary.unlink(missing_ok=True)

    candidate_index = NESTED.index_pak(candidate)
    existing_rows = PACK10_BASE.compare_existing_entries(parent_index, candidate_index)
    candidate_header_size = NESTED.PAK_HEADER.size + candidate_index.entry_size * len(candidate_index.entries)
    parent_region_sha = sha256_region(parent_pak, parent_index.file_data_offset, layout.raw_data_size)
    candidate_region_sha = sha256_region(candidate, candidate_header_size, layout.raw_data_size)
    if parent_region_sha != candidate_region_sha:
        raise Pc02FamilyCandidateError("accepted PC00 PACK10_02 encrypted data region changed in family candidate")
    with candidate.open("rb") as handle:
        handle.seek(NESTED.PAK_HEADER.size)
        candidate_parent_table = handle.read(len(layout.raw_table))
    if candidate_parent_table != layout.raw_table:
        raise Pc02FamilyCandidateError("accepted PC00 PACK10_02 table prefix changed in family candidate")

    inserted_rows: list[dict[str, Any]] = []
    for item in added_metadata:
        decoded, entry = NESTED.read_pak_member(candidate_index, item["target_path"])
        actual_hash = sha256_bytes(decoded)
        if len(decoded) != item["source_size"] or actual_hash != item["source_sha256"]:
            raise Pc02FamilyCandidateError(f"PC02 PACK10_02 inserted member validation failed: {item['target_path']}")
        inserted_rows.append({
            **item,
            "candidate_entry_index": entry.index,
            "candidate_decoded_size": len(decoded),
            "candidate_decoded_sha256": actual_hash,
            "validation_status": "passed",
            "raw_payload_exported_in_report": False,
        })

    gust = run_gust_list(
        gust_pak,
        candidate,
        [row["target_path"] for row in inserted_rows],
        build_root / "metadata" / "PACK10_02_gust_pak_list.log",
        timeout,
    )
    require_file_identity(parent_pak, size=int(parent_meta["size"]), sha256=parent_meta["sha256"], label="accepted generation-2 PC00+PC01 PACK10_02 candidate after expansion")
    require_file_identity(installed_pak, size=int(installed_meta["size"]), sha256=installed_meta["sha256"], label="installed PACK10_02 baseline after expansion")
    if parent_stat.st_mtime_ns != parent_pak.stat().st_mtime_ns or installed_stat.st_mtime_ns != installed_pak.stat().st_mtime_ns:
        raise Pc02FamilyCandidateError("PACK10_02 parent or installed baseline mtime changed")

    summary = {
        "archive": TARGET_PACK10.as_posix(),
        "installed_baseline_size": installed_meta["size"],
        "installed_baseline_sha256": installed_meta["sha256"],
        "parent_candidate_relative_path": parent_meta["relative_path"],
        "parent_candidate_size": parent_meta["size"],
        "parent_candidate_sha256": parent_meta["sha256"],
        "candidate_relative_path": candidate.relative_to(project_root).as_posix(),
        "candidate_size": candidate.stat().st_size,
        "candidate_sha256": sha256_file(candidate),
        "parent_entry_count": len(parent_index.entries),
        "candidate_entry_count": len(candidate_index.entries),
        "added_member_count": len(inserted_rows),
        "parent_table_prefix_identical": True,
        "parent_encrypted_data_region_identical": True,
        "existing_entries_validated": len(existing_rows),
        "gust_pak_validation": gust,
        "parent_candidate_unchanged": True,
        "installed_baseline_unchanged": True,
    }
    return summary, inserted_rows, existing_rows


def decode_xml(raw: bytes) -> tuple[str, str]:
    for encoding in ("cp932", "shift_jis", "utf-8-sig", "utf-8"):
        try:
            return raw.decode(encoding), encoding
        except UnicodeDecodeError:
            continue
    raise Pc02FamilyCandidateError("could not decode charabase XML")


def find_record(text: str, tag: str) -> re.Match[str]:
    pattern = re.compile(r"<CharaBase\b[^>]*\bBaseTag=\"" + re.escape(tag) + r"\"[^>]*/>")
    matches = list(pattern.finditer(text))
    if len(matches) != 1:
        raise Pc02FamilyCandidateError(f"expected exactly one {tag} record, found {len(matches)}")
    return matches[0]


def attrs_from_record(record: str) -> dict[str, str]:
    return {key: value for key, value in re.findall(r"([A-Za-z0-9_]+)=\"([^\"]*)\"", record)}


def patch_charabase(parent_raw: bytes, acceptance: Mapping[str, Any]) -> tuple[bytes, dict[str, Any]]:
    patch = acceptance["charabase_patch"]
    dry_tag = str(patch["dry_tag"])
    wet_tag = str(patch["wet_tag"])
    text, encoding = decode_xml(parent_raw)
    dry_match = find_record(text, dry_tag)
    before_record = dry_match.group(0)
    before_attrs = attrs_from_record(before_record)
    wet_before = attrs_from_record(find_record(text, wet_tag).group(0))
    pc00_before = attrs_from_record(find_record(text, "PC00_DLC_BKN").group(0))
    pc00_wet_before = attrs_from_record(find_record(text, "PC00_DLC_BKN_W").group(0))
    pc01_before = attrs_from_record(find_record(text, "PC01_DLC_BKN").group(0))
    pc01_wet_before = attrs_from_record(find_record(text, "PC01_DLC_BKN_W").group(0))
    expected_old = patch["expected_old_values"]
    new_values = patch["new_values"]
    after_record = before_record
    for field in patch["allowed_changed_fields"]:
        old = str(expected_old[field])
        new = str(new_values[field])
        if before_attrs.get(field) != old:
            raise Pc02FamilyCandidateError(f"PC02 charabase parent {field} is {before_attrs.get(field)!r}, expected {old!r}")
        expression = re.compile(r"(" + re.escape(field) + r"=\")" + re.escape(old) + r"(\")")
        after_record, count = expression.subn(lambda match, value=new: match.group(1) + value + match.group(2), after_record, count=1)
        if count != 1:
            raise Pc02FamilyCandidateError(f"could not patch exact PC02 charabase field {field}")
    after_text = text[:dry_match.start()] + after_record + text[dry_match.end():]
    try:
        candidate_raw = after_text.encode(encoding)
    except UnicodeEncodeError as exc:
        raise Pc02FamilyCandidateError(f"failed to encode charabase as {encoding}") from exc
    after_attrs = attrs_from_record(find_record(after_text, dry_tag).group(0))
    wet_after = attrs_from_record(find_record(after_text, wet_tag).group(0))
    pc00_after = attrs_from_record(find_record(after_text, "PC00_DLC_BKN").group(0))
    pc00_wet_after = attrs_from_record(find_record(after_text, "PC00_DLC_BKN_W").group(0))
    pc01_after = attrs_from_record(find_record(after_text, "PC01_DLC_BKN").group(0))
    pc01_wet_after = attrs_from_record(find_record(after_text, "PC01_DLC_BKN_W").group(0))
    changed = {
        key: [before_attrs.get(key, ""), after_attrs.get(key, "")]
        for key in sorted(set(before_attrs) | set(after_attrs))
        if before_attrs.get(key) != after_attrs.get(key)
    }
    if set(changed) != set(patch["allowed_changed_fields"]):
        raise Pc02FamilyCandidateError(f"unexpected PC02 charabase fields changed: {sorted(changed)}")
    if (
        wet_before != wet_after
        or pc00_before != pc00_after
        or pc00_wet_before != pc00_wet_after
        or pc01_before != pc01_after
        or pc01_wet_before != pc01_wet_after
    ):
        raise Pc02FamilyCandidateError("PC02 patch changed an earlier family or wet record")
    before_without = text[:dry_match.start()] + text[dry_match.end():]
    after_match = find_record(after_text, dry_tag)
    after_without = after_text[:after_match.start()] + after_text[after_match.end():]
    if before_without != after_without:
        raise Pc02FamilyCandidateError("bytes outside PC02 dry charabase record changed")
    return candidate_raw, {
        "encoding": encoding,
        "dry_tag": dry_tag,
        "wet_tag": wet_tag,
        "before_attrs": before_attrs,
        "after_attrs": after_attrs,
        "changed_fields": changed,
        "wet_record_unchanged": True,
        "prior_family_records_unchanged": True,
        "outside_pc02_record_unchanged": True,
    }


def build_pack12_family_candidate(
    project_root: Path,
    quartet_root: Path,
    gust_pak: Path,
    build_root: Path,
    acceptance: Mapping[str, Any],
    pack10_summary: Mapping[str, Any],
    *,
    timeout: int,
) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]]]:
    parents = {Path(row["target_path"]).name: row for row in acceptance["accepted_generation2_parent_candidates"]}
    baselines = {Path(row["relative_path"]).name: row for row in acceptance["installed_baselines"]}
    parent_meta = parents["PACK12.PAK"]
    installed_meta = baselines["PACK12.PAK"]
    parent_pak = project_root / parent_meta["relative_path"]
    installed_pak = quartet_root / installed_meta["relative_path"]
    require_file_identity(parent_pak, size=int(parent_meta["size"]), sha256=parent_meta["sha256"], label="accepted generation-2 PC00+PC01 PACK12 candidate")
    require_file_identity(installed_pak, size=int(installed_meta["size"]), sha256=installed_meta["sha256"], label="installed PACK12 baseline")
    parent_stat = parent_pak.stat()
    installed_stat = installed_pak.stat()

    parent_index = NESTED.index_pak(parent_pak)
    layout = PACK10_BASE.read_raw_layout(parent_pak, parent_index)
    matches = parent_index.by_name.get(NESTED.safe_internal_name(TARGET_CHARABASE).casefold(), [])
    if len(matches) != 1:
        raise Pc02FamilyCandidateError(f"expected exactly one {TARGET_CHARABASE} in accepted generation-2 PC00+PC01 PACK12 candidate")
    target = matches[0]
    parent_member = PACK12_BASE.read_entry_plain(parent_index, target)
    candidate_member, patch_detail = patch_charabase(parent_member, acceptance)
    member_path = build_root / "candidate_member" / TARGET_CHARABASE
    copy_payload(member_path, candidate_member)

    raw_table, table_rows, delta = PACK12_BASE.rewrite_table_for_replacement(layout, parent_index, target, len(candidate_member))
    output_size = parent_pak.stat().st_size + delta
    free = shutil.disk_usage(build_root).free
    if free < output_size + FREE_SPACE_MARGIN:
        raise Pc02FamilyCandidateError(f"insufficient free space for PACK12 family candidate: need {output_size + FREE_SPACE_MARGIN}, have {free}")

    candidate_dir = build_root / "candidate"
    candidate_dir.mkdir(parents=True, exist_ok=True)
    candidate = candidate_dir / "PACK12.PAK"
    temporary = candidate_dir / ".PACK12.PAK.tmp"
    encoded_member = NESTED.xor_bytes(candidate_member, target.key) if target.encrypted else candidate_member
    old_start = target.data_offset
    old_end = old_start + target.size
    data_size = parent_pak.stat().st_size - parent_index.file_data_offset
    try:
        with temporary.open("wb") as output:
            output.write(NESTED.PAK_HEADER.pack(layout.version, layout.file_count, layout.header_size, layout.flags))
            output.write(raw_table)
            copy_region(parent_pak, parent_index.file_data_offset, old_start, output)
            output.write(encoded_member)
            copy_region(parent_pak, parent_index.file_data_offset + old_end, data_size - old_end, output)
            output.flush()
            os.fsync(output.fileno())
        if temporary.stat().st_size != output_size:
            raise Pc02FamilyCandidateError(f"PACK12 candidate size mismatch: {temporary.stat().st_size} != {output_size}")
        os.replace(temporary, candidate)
        fsync_file(candidate)
    finally:
        temporary.unlink(missing_ok=True)

    candidate_index = NESTED.index_pak(candidate)
    if (candidate_index.format_name, candidate_index.master_key_label, len(candidate_index.entries)) != (
        parent_index.format_name, parent_index.master_key_label, len(parent_index.entries)
    ):
        raise Pc02FamilyCandidateError("PACK12 candidate layout differs from accepted generation-2 PC00+PC01 parent")

    validation_rows: list[dict[str, Any]] = []
    non_target_identical = 0
    expected_member_hash = sha256_bytes(candidate_member)
    for original, rebuilt, planned in zip(parent_index.entries, candidate_index.entries, table_rows):
        if original.name != rebuilt.name or original.key != rebuilt.key or original.encrypted != rebuilt.encrypted:
            raise Pc02FamilyCandidateError(f"PACK12 entry identity changed at index {original.index}")
        source_plain = PACK12_BASE.read_entry_plain(parent_index, original)
        rebuilt_plain = PACK12_BASE.read_entry_plain(candidate_index, rebuilt)
        if original.index == target.index:
            passed = len(rebuilt_plain) == len(candidate_member) and sha256_bytes(rebuilt_plain) == expected_member_hash
            status = "charabase_replaced_with_pc00_pc01_pc02_candidate"
        else:
            passed = len(source_plain) == len(rebuilt_plain) and sha256_bytes(source_plain) == sha256_bytes(rebuilt_plain)
            status = "parent_non_target_identical"
            non_target_identical += int(passed)
        if not passed:
            raise Pc02FamilyCandidateError(f"PACK12 member preservation failed at {original.index}: {original.name}")
        if rebuilt.size != int(planned["candidate_size"]) or rebuilt.data_offset != int(planned["candidate_relative_offset"]):
            raise Pc02FamilyCandidateError(f"PACK12 table geometry mismatch at {original.index}")
        validation_rows.append({
            **planned,
            "source_plain_sha256": sha256_bytes(source_plain),
            "candidate_plain_sha256": sha256_bytes(rebuilt_plain),
            "member_status": status,
            "validation_status": "passed",
        })

    pre_size = old_start
    post_size = data_size - old_end
    candidate_data_base = candidate_index.file_data_offset
    pre_parent_sha = sha256_region(parent_pak, parent_index.file_data_offset, pre_size)
    pre_candidate_sha = sha256_region(candidate, candidate_data_base, pre_size)
    post_parent_sha = sha256_region(parent_pak, parent_index.file_data_offset + old_end, post_size)
    post_candidate_sha = sha256_region(candidate, candidate_data_base + old_start + len(candidate_member), post_size)
    if pre_parent_sha != pre_candidate_sha or post_parent_sha != post_candidate_sha:
        raise Pc02FamilyCandidateError("PACK12 non-target encrypted data regions changed")

    gust = run_gust_list(
        gust_pak,
        candidate,
        [TARGET_CHARABASE],
        build_root / "metadata" / "PACK12_gust_pak_list.log",
        timeout,
    )
    require_file_identity(parent_pak, size=int(parent_meta["size"]), sha256=parent_meta["sha256"], label="accepted generation-2 PC00+PC01 PACK12 candidate after expansion")
    require_file_identity(installed_pak, size=int(installed_meta["size"]), sha256=installed_meta["sha256"], label="installed PACK12 baseline after expansion")
    if parent_stat.st_mtime_ns != parent_pak.stat().st_mtime_ns or installed_stat.st_mtime_ns != installed_pak.stat().st_mtime_ns:
        raise Pc02FamilyCandidateError("PACK12 parent or installed baseline mtime changed")

    summary = {
        "archive": TARGET_PACK12.as_posix(),
        "installed_baseline_size": installed_meta["size"],
        "installed_baseline_sha256": installed_meta["sha256"],
        "parent_candidate_relative_path": parent_meta["relative_path"],
        "parent_candidate_size": parent_meta["size"],
        "parent_candidate_sha256": parent_meta["sha256"],
        "candidate_relative_path": candidate.relative_to(project_root).as_posix(),
        "candidate_size": candidate.stat().st_size,
        "candidate_sha256": sha256_file(candidate),
        "parent_entry_count": len(parent_index.entries),
        "candidate_entry_count": len(candidate_index.entries),
        "target_member": TARGET_CHARABASE,
        "parent_target_member_sha256": sha256_bytes(parent_member),
        "candidate_target_member_sha256": expected_member_hash,
        "non_target_entries_validated": non_target_identical,
        "pre_target_encrypted_region_identical": True,
        "post_target_encrypted_region_identical": True,
        "size_delta": delta,
        "gust_pak_validation": gust,
        "parent_candidate_unchanged": True,
        "installed_baseline_unchanged": True,
        "pack10_family_candidate_sha256": pack10_summary["candidate_sha256"],
    }
    return summary, patch_detail, validation_rows


def audit(
    project_root: Path,
    original_root: Path,
    quartet_root: Path,
    gust_pak: Path,
    output_root: Path,
    *,
    timeout: int = 1200,
) -> tuple[Path, dict[str, Any]]:
    project_root = project_root.resolve()
    original_root = original_root.resolve()
    quartet_root = quartet_root.resolve()
    gust_pak = gust_pak.resolve()
    output_root = output_root.resolve()
    local_build_root = (project_root / ".local/build").resolve()
    build_root = (project_root / BUILD_RELATIVE).resolve()
    if not str(build_root).startswith(str(local_build_root) + os.sep):
        raise Pc02FamilyCandidateError("unsafe local build root")
    if output_root == project_root or not str(output_root).startswith(str((project_root / ".local/reports").resolve()) + os.sep):
        raise Pc02FamilyCandidateError("unsafe report output root")

    acceptance = load_acceptance(project_root)
    helper_rows = validate_helper_sources(project_root, acceptance)
    clean_dir(build_root)
    print("[stage88] extracting and validating PC02 dry source assets", flush=True)
    source_rows, nested_rows, payloads = extract_pc02_assets(project_root, original_root, build_root, acceptance)
    print("[stage88] extending accepted generation-2 PC00+PC01 PACK10_02 candidate with PC02", flush=True)
    pack10, inserted_rows, existing_pack10_rows = build_pack10_family_candidate(
        project_root, quartet_root, gust_pak, build_root, acceptance, payloads, timeout=timeout,
    )
    print("[stage88] extending accepted generation-2 PC00+PC01 PACK12 candidate with PC02 charabase redirect", flush=True)
    pack12, patch_detail, pack12_validation_rows = build_pack12_family_candidate(
        project_root, quartet_root, gust_pak, build_root, acceptance, pack10, timeout=timeout,
    )

    clean_dir(output_root)
    write_tsv(output_root / "DLC_BKN_DRY_PC02_HELPER_SOURCE_GATES.tsv", list(helper_rows[0]), helper_rows)
    write_tsv(output_root / "DLC_BKN_DRY_PC02_SOURCE_ASSETS.tsv", list(source_rows[0]), source_rows)
    write_tsv(output_root / "DLC_BKN_DRY_PC02_NESTED_ROUNDTRIP.tsv", list(nested_rows[0]), nested_rows)
    parent_rows = []
    for archive in (pack10, pack12):
        parent_rows.append({
            "archive": archive["archive"],
            "installed_baseline_size": archive["installed_baseline_size"],
            "installed_baseline_sha256": archive["installed_baseline_sha256"],
            "parent_candidate_relative_path": archive["parent_candidate_relative_path"],
            "parent_candidate_size": archive["parent_candidate_size"],
            "parent_candidate_sha256": archive["parent_candidate_sha256"],
            "parent_candidate_unchanged": archive["parent_candidate_unchanged"],
            "installed_baseline_unchanged": archive["installed_baseline_unchanged"],
        })
    write_tsv(output_root / "DLC_BKN_DRY_PC02_PARENT_GATES.tsv", list(parent_rows[0]), parent_rows)
    pack10_row = {key: value for key, value in pack10.items() if key != "gust_pak_validation"}
    pack10_row.update({f"gust_{key}": value for key, value in pack10["gust_pak_validation"].items()})
    write_tsv(output_root / "DLC_BKN_DRY_PC02_PACK10_EXPANSION.tsv", list(pack10_row), [pack10_row])
    write_tsv(output_root / "DLC_BKN_DRY_PC02_PACK10_INSERTED_MEMBERS.tsv", list(inserted_rows[0]), inserted_rows)
    write_tsv(
        output_root / "DLC_BKN_DRY_PC02_PACK10_PARENT_ENTRY_VALIDATION.tsv",
        list(existing_pack10_rows[0]),
        existing_pack10_rows,
    )
    patch_rows = [
        {
            "record_key": f"CharaBase:BaseTag={patch_detail['dry_tag']}",
            "field": field,
            "expected_old_value": values[0],
            "new_value": values[1],
            "wet_record_unchanged": patch_detail["wet_record_unchanged"],
            "prior_family_records_unchanged": patch_detail["prior_family_records_unchanged"],
            "outside_pc02_record_unchanged": patch_detail["outside_pc02_record_unchanged"],
            "candidate_installed": False,
        }
        for field, values in sorted(patch_detail["changed_fields"].items())
    ]
    write_tsv(output_root / "DLC_BKN_DRY_PC02_CHARABASE_PATCH.tsv", list(patch_rows[0]), patch_rows)
    pack12_row = {key: value for key, value in pack12.items() if key != "gust_pak_validation"}
    pack12_row.update({f"gust_{key}": value for key, value in pack12["gust_pak_validation"].items()})
    write_tsv(output_root / "DLC_BKN_DRY_PC02_PACK12_EXPANSION.tsv", list(pack12_row), [pack12_row])
    write_tsv(
        output_root / "DLC_BKN_DRY_PC02_PACK12_ENTRY_VALIDATION.tsv",
        list(pack12_validation_rows[0]),
        pack12_validation_rows,
    )
    composition_rows = [
        {
            "archive": pack10["archive"],
            "candidate_relative_path": pack10["candidate_relative_path"],
            "candidate_size": pack10["candidate_size"],
            "candidate_sha256": pack10["candidate_sha256"],
            "contains_content_ids": ["costume_pc00_bkn", "costume_pc01_bkn", "costume_pc02_bkn"],
            "candidate_installed": False,
            "profile_registered": False,
            "runtime_validated": False,
        },
        {
            "archive": pack12["archive"],
            "candidate_relative_path": pack12["candidate_relative_path"],
            "candidate_size": pack12["candidate_size"],
            "candidate_sha256": pack12["candidate_sha256"],
            "contains_content_ids": ["costume_pc00_bkn", "costume_pc01_bkn", "costume_pc02_bkn"],
            "candidate_installed": False,
            "profile_registered": False,
            "runtime_validated": False,
        },
    ]
    write_tsv(output_root / "DLC_BKN_DRY_PC02_TWO_ARCHIVE_COMPOSITION.tsv", list(composition_rows[0]), composition_rows)
    safety_rows = [
        {"gate": "prepare", "allowed": False, "observed": False},
        {"gate": "commit", "allowed": False, "observed": False},
        {"gate": "installation", "allowed": False, "observed": False},
        {"gate": "profile_registration", "allowed": False, "observed": False},
        {"gate": "runtime_validation", "allowed": False, "observed": False},
        {"gate": "wet_bkn", "allowed": False, "observed": False},
        {"gate": "game_file_write", "allowed": False, "observed": False},
        {"gate": "accepted_generation2_candidate_write", "allowed": False, "observed": False},
    ]
    write_tsv(output_root / "DLC_BKN_DRY_PC02_SAFETY_GATES.tsv", list(safety_rows[0]), safety_rows)

    summary = {
        "type": "br_quartet_legacy_dlc_bkn_dry_pc02_family_candidate_summary",
        "format_version": FORMAT_VERSION,
        "tool_version": TOOL_VERSION,
        "status": "local_pc00_pc01_pc02_dry_family_candidate_built_not_installed",
        "content_ids": ["costume_pc00_bkn", "costume_pc01_bkn", "costume_pc02_bkn"],
        "variant": "dry",
        "source_asset_count": len(source_rows),
        "nested_member_count": len(nested_rows),
        "candidate_artifact_count": 2,
        "candidate_artifacts": composition_rows,
        "accepted_generation2_parent_candidates_unchanged": True,
        "installed_game_archives_unchanged": True,
        "pack10_parent_entries_preserved": len(existing_pack10_rows),
        "pack12_non_target_entries_preserved": pack12["non_target_entries_validated"],
        "pc02_charabase_changed_fields": sorted(patch_detail["changed_fields"]),
        "prior_family_charabase_records_unchanged": True,
        "wet_records_unchanged": True,
        "build_root": build_root.relative_to(project_root).as_posix(),
        "next_action": "publish generation 3 through the existing generic manifest adapter and run the read-only canonical preview; do not modify core or install either PAK",
        "policy": {
            "game_modified": False,
            "accepted_generation2_candidates_modified": False,
            "git_modified": False,
            "prepare_called": False,
            "commit_called": False,
            "candidate_installed": False,
            "profile_registered": False,
            "runtime_validated": False,
            "wet_variant_included": False,
            "raw_assets_in_local_build": True,
            "raw_assets_exported_in_report": False,
            "raw_assets_in_update": False,
            "translation_modified": False,
            "restoration_modified": False,
            "core_modified": False,
        },
    }
    write_json(output_root / "SUMMARY.json", summary)
    write_json(output_root / "REPORT_MANIFEST.json", {
        "type": "br_report_manifest",
        "format_version": 1,
        "files": report_manifest(output_root),
    })
    archive = output_root.parent / f"{REPORT_ARCHIVE_BASENAME}.tar.zst"
    make_archive(output_root, archive)
    print(f"[stage88] combined PACK10_02 candidate: {project_root / pack10['candidate_relative_path']}", flush=True)
    print(f"[stage88] combined PACK12 candidate: {project_root / pack12['candidate_relative_path']}", flush=True)
    print(f"[stage88] report: {archive}", flush=True)
    return archive, summary


def validate_report(report_root: Path) -> dict[str, Any]:
    report_root = report_root.resolve()
    required = {
        "DLC_BKN_DRY_PC02_HELPER_SOURCE_GATES.tsv",
        "DLC_BKN_DRY_PC02_SOURCE_ASSETS.tsv",
        "DLC_BKN_DRY_PC02_NESTED_ROUNDTRIP.tsv",
        "DLC_BKN_DRY_PC02_PARENT_GATES.tsv",
        "DLC_BKN_DRY_PC02_PACK10_EXPANSION.tsv",
        "DLC_BKN_DRY_PC02_PACK10_INSERTED_MEMBERS.tsv",
        "DLC_BKN_DRY_PC02_PACK10_PARENT_ENTRY_VALIDATION.tsv",
        "DLC_BKN_DRY_PC02_CHARABASE_PATCH.tsv",
        "DLC_BKN_DRY_PC02_PACK12_EXPANSION.tsv",
        "DLC_BKN_DRY_PC02_PACK12_ENTRY_VALIDATION.tsv",
        "DLC_BKN_DRY_PC02_TWO_ARCHIVE_COMPOSITION.tsv",
        "DLC_BKN_DRY_PC02_SAFETY_GATES.tsv",
        "SUMMARY.json",
        "REPORT_MANIFEST.json",
    }
    missing = sorted(name for name in required if not (report_root / name).is_file())
    if missing:
        raise Pc02FamilyCandidateError("missing report files: " + ", ".join(missing))
    summary = read_json(report_root / "SUMMARY.json")
    if summary.get("type") != "br_quartet_legacy_dlc_bkn_dry_pc02_family_candidate_summary":
        raise Pc02FamilyCandidateError("unexpected report summary type")
    if summary.get("tool_version") != TOOL_VERSION:
        raise Pc02FamilyCandidateError("report tool version mismatch")
    if summary.get("status") != "local_pc00_pc01_pc02_dry_family_candidate_built_not_installed":
        raise Pc02FamilyCandidateError("unexpected report status")
    if summary.get("candidate_artifact_count") != 2:
        raise Pc02FamilyCandidateError("report must contain exactly two candidate artifacts")
    if summary.get("accepted_generation2_parent_candidates_unchanged") is not True or summary.get("installed_game_archives_unchanged") is not True:
        raise Pc02FamilyCandidateError("parent or installed archive preservation is not proven")
    if summary.get("pc02_charabase_changed_fields") != ["Model", "defaultTexture"]:
        raise Pc02FamilyCandidateError("PC02 charabase patch changed unexpected fields")
    policy = summary.get("policy", {})
    false_keys = (
        "game_modified", "accepted_generation2_candidates_modified", "git_modified", "prepare_called",
        "commit_called", "candidate_installed", "profile_registered", "runtime_validated",
        "wet_variant_included", "raw_assets_exported_in_report", "raw_assets_in_update",
        "translation_modified", "restoration_modified", "core_modified",
    )
    if any(policy.get(key) is not False for key in false_keys):
        raise Pc02FamilyCandidateError("report violates fail-closed policy")
    if policy.get("raw_assets_in_local_build") is not True:
        raise Pc02FamilyCandidateError("local raw-asset build declaration missing")
    composition = []
    with (report_root / "DLC_BKN_DRY_PC02_TWO_ARCHIVE_COMPOSITION.tsv").open("r", encoding="utf-8", newline="") as handle:
        composition = list(csv.DictReader(handle, delimiter="\t"))
    if len(composition) != 2 or {row["archive"] for row in composition} != {"Data/PACK10_02.PAK", "Data/PACK12.PAK"}:
        raise Pc02FamilyCandidateError("two-archive composition is incomplete")
    if any(row["candidate_installed"] != "false" or row["profile_registered"] != "false" or row["runtime_validated"] != "false" for row in composition):
        raise Pc02FamilyCandidateError("composition improperly authorizes installation/profile/runtime")
    manifest = read_json(report_root / "REPORT_MANIFEST.json")
    expected = {row["path"]: row for row in manifest.get("files", [])}
    actual_files = [path for path in report_root.rglob("*") if path.is_file() and path.name != "REPORT_MANIFEST.json"]
    if set(expected) != {path.relative_to(report_root).as_posix() for path in actual_files}:
        raise Pc02FamilyCandidateError("report manifest file set mismatch")
    for path in actual_files:
        relative = path.relative_to(report_root).as_posix()
        row = expected[relative]
        if path.stat().st_size != int(row["size"]) or sha256_file(path) != row["sha256"]:
            raise Pc02FamilyCandidateError(f"report manifest mismatch: {relative}")
        if any(suffix.casefold() in FORBIDDEN_REPORT_SUFFIXES for suffix in path.suffixes):
            raise Pc02FamilyCandidateError(f"raw asset-like file in report: {relative}")
    return summary


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    audit_parser = sub.add_parser("audit")
    audit_parser.add_argument("--project-root", type=Path, default=PROJECT_ROOT_DEFAULT)
    audit_parser.add_argument("--original-root", type=Path, required=True)
    audit_parser.add_argument("--quartet-root", type=Path, required=True)
    audit_parser.add_argument("--gust-pak", type=Path, required=True)
    audit_parser.add_argument("--output-root", type=Path)
    audit_parser.add_argument("--timeout", type=int, default=1200)
    validate_parser = sub.add_parser("validate-report")
    validate_parser.add_argument("--report-root", type=Path, required=True)
    bundle_parser = sub.add_parser("bundle-report")
    bundle_parser.add_argument("--report-root", type=Path, required=True)
    bundle_parser.add_argument("--output", type=Path, required=True)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        if args.command == "audit":
            project = args.project_root.resolve()
            output = args.output_root or project / ".local/reports/quartet_legacy_dlc" / REPORT_DIR_NAME
            archive, summary = audit(
                project,
                args.original_root,
                args.quartet_root,
                args.gust_pak,
                output,
                timeout=args.timeout,
            )
            print(json.dumps({"archive": str(archive), "status": summary["status"]}, sort_keys=True))
        elif args.command == "validate-report":
            summary = validate_report(args.report_root)
            print(json.dumps(summary, sort_keys=True))
        else:
            validate_report(args.report_root)
            make_archive(args.report_root, args.output)
            print(args.output)
        return 0
    except (
        Pc02FamilyCandidateError,
        OSError,
        subprocess.SubprocessError,
        json.JSONDecodeError,
        NESTED.NestedContainerError,
        PACK10_BASE.DryPakInsertionError,
        PACK12_BASE.BknDryPack12RepackError,
        TRANSFER_BASE.TransferProbeError,
    ) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
