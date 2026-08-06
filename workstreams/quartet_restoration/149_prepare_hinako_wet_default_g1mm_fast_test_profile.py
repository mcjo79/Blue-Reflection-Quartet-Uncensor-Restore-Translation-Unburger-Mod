#!/usr/bin/env python3
"""Stage 149: build the second Hinako wet-school Fast Test Lab profile.

The stage-148 whole-member School_Wet probe was runtime-stable and restored one
visible Original-style uniform detail, but it did not restore blouse
transparency. This candidate retains that confirmed partial restoration and adds
one narrow material probe: Quartet's PC00_Scl_W_default.g1m is preserved except
for its same-version, same-size top-level G1MM chunk, which is replaced by the
exact Original G1MM chunk.

Exactly two inner members of pc00_scl_w are therefore expected to differ from
the Quartet baseline: the retained exact Original School_Wet member and the
G1MM-only Scl_W_default candidate. Every other inner member and every other
PACK10_02 member must remain byte-identical. The installed game is read-only.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import importlib.util
import json
import os
import shutil
import struct
import subprocess
import sys
import tempfile
import zlib
from pathlib import Path, PurePosixPath
from typing import Any, Iterable, Mapping, Sequence

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT_DEFAULT = SCRIPT_DIR.parent.parent
TOOL_VERSION = "0.1.67"
PROFILE_ID = "fast_test_pc00_scl_w_school_partial_plus_default_g1mm_c74bc813e41"
TARGET_RELATIVE_PATH = "Data/PACK10_02.PAK"
SOURCE_ARCHIVE_RELATIVE_PATH = "DATA/PACK00_02.PAK"
NORMALIZED_PARENT_PATH = "data/x64/character/pc00/pc00_scl_w.elixir.gz"
TARGET_PARENT_SUFFIX = "data/b1/x64/character/pc00/pc00_scl_w.elixir.gz"
SELECTED_MEMBER_KEY = "pc00_scl_w_default.g1m#0"
SELECTED_MEMBER_NAME = "PC00_Scl_W_default.g1m"
RETAINED_MEMBER_KEY = "pc00_scl_w_p_school_wet.g1m#0"
RETAINED_MEMBER_NAME = "PC00_Scl_W_P_School_Wet.g1m"
EXPECTED_RETAINED_SOURCE_MEMBER_SHA256 = "b98a68625fe3238d583f5f3115d4ab68beed4e00790eed137f8c192dec5e8f6e"
EXPECTED_RETAINED_TARGET_MEMBER_SHA256 = "b7c628698250976d13b45212ce3aee94ef771b1a1b2529bc779567a49a17d7e0"
EXPECTED_RETAINED_SOURCE_MEMBER_SIZE = 485640
EXPECTED_RETAINED_TARGET_MEMBER_SIZE = 482464
EXPECTED_SOURCE_PARENT_SHA256 = "83f50a2507671cfe6294e9fe23e510e19a22232bbc3dd647b3281137d5a94843"
EXPECTED_TARGET_PARENT_SHA256 = "9126342ff00977b68e38857e6638ed993b47175416d01078b62be9d2ab8ce8e6"
EXPECTED_SOURCE_MEMBER_SHA256 = "c19b234200c5eb6bc8f79715a21f60dfa22625c8ee8d44f88a3e6f36f4ac8501"
EXPECTED_TARGET_MEMBER_SHA256 = "d031638809cc633c36dc7d5185dc27b909a1c5a3c61730be2a00a6af134610b1"
EXPECTED_SOURCE_MEMBER_SIZE = 1522864
EXPECTED_TARGET_MEMBER_SIZE = 1524716
G1MM_CHUNK_MAGIC = "MM1G"
EXPECTED_G1MM_VERSION = "0x30303230"
EXPECTED_G1MM_SIZE = 8528
EXPECTED_SOURCE_G1MM_SHA256 = "c74bc813e415ad81a091469af508c0d2f563df9384f1fdbc75593abd3ef6e7fc"
EXPECTED_TARGET_G1MM_SHA256 = "23c30ec58bbee43ec5673f1b56fe35d28d192e4e992fc65f2bb654cd6b190ead"
STAGE125_REPORT = "BR_quartet_restoration_character_state_exact_rehydration_evidence.tar.zst"
STAGE125_SHA256 = "a6b6ae0d0f1276b3393f5292dd65f264b003901142f1965c108f6ad58729fe54"
STAGE125_ROOT = "character_state_exact_rehydration_evidence"
STAGE126_REPORT = "BR_quartet_restoration_character_state_g1m_material_classification_evidence.tar.zst"
STAGE126_SHA256 = "fd1a6992f9ef79264a33269fe1d12c94d34d7bb1e3c60dfec973ece0cb8c5371"
STAGE126_ROOT = "character_state_g1m_material_classification_evidence"
STAGE127_REPORT = "BR_quartet_restoration_character_state_g1m_delta_scope_triage_evidence.tar.zst"
STAGE127_SHA256 = "44fa2bc776a298a7ee7d21a382406fe8f8055fe3db6e627bc9a6b1b51544be63"
STAGE127_ROOT = "character_state_g1m_delta_scope_triage_evidence"
ACTIVATION_REPORT = "BR_quartet_restoration_hinako_wet_school_uniform_fast_test_lab_activation_evidence.tar.zst"
ACTIVATION_SHA256 = "9c6e9431e23a6fd0e96aa5ff08dc897ac003584bfaf4fdd4e20babd08f4f3e49"
ACTIVATION_ROOT = "hinako_wet_school_uniform_fast_test_lab_activation_evidence"
ROLLBACK_REPORT = "BR_quartet_restoration_hinako_wet_school_uniform_fast_test_lab_rollback_evidence.tar.zst"
ROLLBACK_SHA256 = "113d6527cda4c787013d9af070927a52f1bf89735835600a76ae22644677aaed"
ROLLBACK_ROOT = "hinako_wet_school_uniform_fast_test_lab_rollback_evidence"
OBSERVATION_PATH = SCRIPT_DIR / "WET_SCHOOL_RUNTIME_OBSERVATION.json"
EXPECTED_PACK10_02_BASELINE_SHA256 = "e798f39c3bcdbb11381197bddf9bd3ad8de6ccf5d7c0c78b22613046d47f5302"
REPORT_DIR = "hinako_wet_school_composite_g1mm_fast_test_profile_evidence"
REPORT_NAME = "BR_quartet_restoration_hinako_wet_school_composite_g1mm_fast_test_profile_evidence.tar.zst"
WORKSPACE_SUBDIR = Path("fast_test_lab/wet_school_composite_g1mm_pc00")
MANIFEST_SUBDIR = Path("core_profiles/fast_test_lab")
MAX_PARENT_BYTES = 64 * 1024 * 1024
FORBIDDEN_REPORT_EXTENSIONS = (
    ".pak", ".g1m", ".g1t", ".g1s", ".g1e", ".g1em", ".elixir", ".elixir.gz", ".ebd", ".ebm", ".kps"
)


class WetDefaultG1MMProfileError(RuntimeError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise WetDefaultG1MMProfileError(message)


def progress(message: str) -> None:
    print(f"[stage149] {message}", flush=True)


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(8 * 1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def safe_relative(value: str, label: str) -> str:
    path = PurePosixPath(str(value).replace("\\", "/"))
    require(path.parts and not path.is_absolute() and ".." not in path.parts, f"unsafe {label}: {value}")
    return path.as_posix()


def read_tsv(path: Path) -> list[dict[str, str]]:
    require(path.is_file(), f"missing TSV: {path}")
    with path.open(encoding="utf-8", newline="") as f:
        return [dict(row) for row in csv.DictReader(f, delimiter="\t")]


def write_tsv(path: Path, fields: Sequence[str], rows: Iterable[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(fields), delimiter="\t", lineterminator="\n", extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fields})


def atomic_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def make_archive(source: Path, output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    tmp = output.with_name(output.name + ".tmp")
    tmp.unlink(missing_ok=True)
    cp = subprocess.run(["tar", "--zstd", "-cf", str(tmp), "-C", str(source.parent), source.name], text=True, capture_output=True)
    require(cp.returncode == 0, cp.stderr.strip() or "report archive creation failed")
    os.replace(tmp, output)


def load_module(path: Path, name: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    require(spec is not None and spec.loader is not None, f"cannot load module: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def extract_report(archive: Path, expected_sha256: str, expected_root: str, destination: Path, label: str) -> Path:
    require(archive.is_file(), f"missing {label}: {archive}")
    actual = sha256_file(archive)
    require(actual == expected_sha256, f"{label} SHA-256 drift: {actual}")
    listed = subprocess.run(["tar", "--zstd", "-tf", str(archive)], text=True, capture_output=True)
    require(listed.returncode == 0, listed.stderr.strip() or f"cannot list {label}")
    names = [safe_relative(line.strip(), f"{label} member") for line in listed.stdout.splitlines() if line.strip()]
    require(names and {PurePosixPath(name).parts[0] for name in names} == {expected_root}, f"unexpected {label} root")
    require(not any(name.casefold().endswith(FORBIDDEN_REPORT_EXTENSIONS) for name in names), f"proprietary payload in {label}")
    destination.mkdir(parents=True, exist_ok=True)
    cp = subprocess.run(["tar", "--zstd", "-xf", str(archive), "-C", str(destination)], text=True, capture_output=True)
    require(cp.returncode == 0, cp.stderr.strip() or f"cannot extract {label}")
    return destination / expected_root


def validate_prerequisites(project_root: Path, report_root: Path) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="stage147-prereq-") as td:
        temp = Path(td)
        require(OBSERVATION_PATH.is_file(), "missing canonical wet-school runtime observation")
        observation = json.loads(OBSERVATION_PATH.read_text(encoding="utf-8"))
        require(observation.get("runtime_tested") is True and observation.get("runtime_stable") is True and observation.get("crash_observed") is False, "wet-school runtime stability observation drift")
        require(observation.get("target_transparency_restored") is False and observation.get("runtime_validated") is False and observation.get("production_eligible") is False, "wet-school visual result/promotion drift")
        require(observation.get("partial_visual_restoration_confirmed") is True, "wet-school retained partial restoration drift")
        partial = observation.get("partial_visual_restoration") or {}
        require(partial.get("must_be_retained_in_future_candidate") is True, "wet-school retained component policy drift")
        require(observation.get("exact_pack10_02_baseline_restored") is True and observation.get("pack10_02_baseline_sha256") == EXPECTED_PACK10_02_BASELINE_SHA256, "wet-school rollback observation drift")
        activation = extract_report(report_root / ACTIVATION_REPORT, ACTIVATION_SHA256, ACTIVATION_ROOT, temp / "activation", "stage-148 activation evidence")
        rollback = extract_report(report_root / ROLLBACK_REPORT, ROLLBACK_SHA256, ROLLBACK_ROOT, temp / "rollback", "stage-148 rollback evidence")
        activation_summary = json.loads((activation / "SUMMARY.json").read_text(encoding="utf-8")); rollback_summary = json.loads((rollback / "SUMMARY.json").read_text(encoding="utf-8"))
        require(activation_summary.get("status") == "wet_school_fast_test_profile_active_runtime_observation_pending", "stage-148 activation status drift")
        require(activation_summary.get("protected_archives_unchanged") is True and activation_summary.get("baseline_sha256") == EXPECTED_PACK10_02_BASELINE_SHA256, "stage-148 activation guard drift")
        require(rollback_summary.get("exact_pack10_02_baseline_restored") is True and rollback_summary.get("observed_target_sha256") == EXPECTED_PACK10_02_BASELINE_SHA256, "stage-148 rollback baseline drift")
        require(rollback_summary.get("protected_archives_unchanged") is True, "stage-148 rollback guard drift")

        s125 = extract_report(report_root / STAGE125_REPORT, STAGE125_SHA256, STAGE125_ROOT, temp / "a", "stage-125 evidence")
        ledger = read_tsv(s125 / "REHYDRATED_UNIVERSAL_MEMBER_LEDGER.tsv")
        rows = [row for row in ledger if row.get("character_id") == "pc00" and row.get("state_token") == "scl_w" and row.get("member_key") == SELECTED_MEMBER_KEY]
        require(len(rows) == 1, "stage-125 Scl_W_default row cardinality drift")
        row125 = rows[0]
        require(row125.get("source_member_name") == SELECTED_MEMBER_NAME and row125.get("target_member_name") == SELECTED_MEMBER_NAME, "Scl_W_default member name drift")
        require(row125.get("source_sha256") == EXPECTED_SOURCE_MEMBER_SHA256 and row125.get("target_sha256") == EXPECTED_TARGET_MEMBER_SHA256, "Scl_W_default member hash drift")
        require(int(row125.get("source_size", "-1")) == EXPECTED_SOURCE_MEMBER_SIZE and int(row125.get("target_size", "-1")) == EXPECTED_TARGET_MEMBER_SIZE, "Scl_W_default member size drift")

        s126 = extract_report(report_root / STAGE126_REPORT, STAGE126_SHA256, STAGE126_ROOT, temp / "b", "stage-126 evidence")
        audit = read_tsv(s126 / "UNIVERSAL_G1M_MEMBER_AUDIT.tsv")
        rows126 = [row for row in audit if row.get("character_id") == "pc00" and row.get("state_token") == "scl_w" and row.get("member_key") == SELECTED_MEMBER_KEY]
        require(len(rows126) == 1, "stage-126 Scl_W_default audit row drift")
        row126 = rows126[0]
        require(row126.get("source_parse_status") == "parsed" and row126.get("target_parse_status") == "parsed", "Scl_W_default G1M parser status drift")
        require(int(row126.get("semantic_parameter_diff_rows", "-1")) == 12, "Scl_W_default semantic parameter diff count drift")
        params = read_tsv(s126 / "UNIVERSAL_G1M_PARAMETER_DIFF.tsv")
        relevant = [row for row in params if row.get("character_id") == "pc00" and row.get("state_token") == "scl_w" and row.get("member_key") == SELECTED_MEMBER_KEY]
        require(len(relevant) == 12, "Scl_W_default parameter row count drift")
        require({row.get("parameter_name") for row in relevant} == {"parameterForMeshBlend", "emissiveColor"}, "Scl_W_default direct parameter family drift")
        require(all(row.get("classification") == "added_in_target" for row in relevant), "Scl_W_default parameter direction drift")
        require(all(row.get("semantics_confirmed") == "False" and row.get("write_authorized") == "False" for row in relevant), "Scl_W_default static evidence was unexpectedly promoted")
        chunk_rows = read_tsv(s126 / "UNIVERSAL_G1M_CHUNK_ROWS.tsv")
        selected_chunks = [row for row in chunk_rows if row.get("character_id") == "pc00" and row.get("state_token") == "scl_w" and row.get("member_key") == SELECTED_MEMBER_KEY and row.get("chunk_magic") == G1MM_CHUNK_MAGIC]
        require(len(selected_chunks) == 2, "Scl_W_default G1MM source/target row cardinality drift")
        source_chunk = next(row for row in selected_chunks if row.get("side") == "source")
        target_chunk = next(row for row in selected_chunks if row.get("side") == "target")
        require(source_chunk.get("chunk_version") == EXPECTED_G1MM_VERSION and target_chunk.get("chunk_version") == EXPECTED_G1MM_VERSION, "Scl_W_default G1MM version drift")
        require(int(source_chunk.get("chunk_size", "-1")) == EXPECTED_G1MM_SIZE and int(target_chunk.get("chunk_size", "-1")) == EXPECTED_G1MM_SIZE, "Scl_W_default G1MM size drift")
        require(source_chunk.get("chunk_sha256") == EXPECTED_SOURCE_G1MM_SHA256 and target_chunk.get("chunk_sha256") == EXPECTED_TARGET_G1MM_SHA256, "Scl_W_default G1MM hash drift")

        s127 = extract_report(report_root / STAGE127_REPORT, STAGE127_SHA256, STAGE127_ROOT, temp / "c", "stage-127 evidence")
        summary127 = json.loads((s127 / "SUMMARY.json").read_text(encoding="utf-8"))
        require(summary127.get("ubiquitous_mesh_blend_addition_rows") == 2047, "stage-127 mesh-blend count drift")
        require(summary127.get("visual_or_censorship_semantics_confirmed_rows") == 0 and summary127.get("write_authorized_rows") == 0, "stage-127 semantics/write policy drift")
        require((summary127.get("policy") or {}).get("broad_pattern_classification_is_not_visual_proof") is True, "stage-127 visual-proof policy drift")
        return {
            "stage148_activation_evidence_sha256": ACTIVATION_SHA256,
            "stage148_rollback_evidence_sha256": ROLLBACK_SHA256,
            "runtime_stable": True,
            "target_transparency_restored": False,
            "partial_visual_restoration_confirmed": True,
            "retained_school_wet_member_source_sha256": EXPECTED_RETAINED_SOURCE_MEMBER_SHA256,
            "exact_pack10_02_baseline_restored": True,
            "stage125_report_sha256": STAGE125_SHA256,
            "stage126_report_sha256": STAGE126_SHA256,
            "stage127_report_sha256": STAGE127_SHA256,
            "selected_member_source_sha256": EXPECTED_SOURCE_MEMBER_SHA256,
            "selected_member_target_sha256": EXPECTED_TARGET_MEMBER_SHA256,
            "selected_member_source_size": EXPECTED_SOURCE_MEMBER_SIZE,
            "selected_member_target_size": EXPECTED_TARGET_MEMBER_SIZE,
            "scl_w_default_parameter_diff_rows": 12,
            "scl_w_default_parameter_names": ["emissiveColor", "parameterForMeshBlend"],
            "g1mm_chunk_magic": G1MM_CHUNK_MAGIC,
            "g1mm_chunk_version": EXPECTED_G1MM_VERSION,
            "g1mm_chunk_size": EXPECTED_G1MM_SIZE,
            "source_g1mm_sha256": EXPECTED_SOURCE_G1MM_SHA256,
            "target_g1mm_sha256": EXPECTED_TARGET_G1MM_SHA256,
            "mesh_blend_broad_pattern_rows": 2047,
            "semantics_confirmed": False,
        }


def splice_g1mm_chunk(br: Any, target_payload: bytes, source_payload: bytes) -> tuple[bytes, dict[str, Any]]:
    require(len(target_payload) == EXPECTED_TARGET_MEMBER_SIZE and sha256_bytes(target_payload) == EXPECTED_TARGET_MEMBER_SHA256, "target Scl_W_default payload drift")
    require(len(source_payload) == EXPECTED_SOURCE_MEMBER_SIZE and sha256_bytes(source_payload) == EXPECTED_SOURCE_MEMBER_SHA256, "source Scl_W_default payload drift")
    source_parsed = br.parse_g1m_material_parameters(source_payload, label="source:PC00_Scl_W_default.g1m")
    target_parsed = br.parse_g1m_material_parameters(target_payload, label="target:PC00_Scl_W_default.g1m")
    source_rows = [row for row in source_parsed.get("chunks", []) if row.get("chunk_magic") == G1MM_CHUNK_MAGIC]
    target_rows = [row for row in target_parsed.get("chunks", []) if row.get("chunk_magic") == G1MM_CHUNK_MAGIC]
    require(len(source_rows) == 1 and len(target_rows) == 1, "expected exactly one G1MM chunk on each side")
    left, right = source_rows[0], target_rows[0]
    require(left.get("chunk_version") == EXPECTED_G1MM_VERSION and right.get("chunk_version") == EXPECTED_G1MM_VERSION, "G1MM version drift")
    require(int(left.get("chunk_size", -1)) == EXPECTED_G1MM_SIZE and int(right.get("chunk_size", -1)) == EXPECTED_G1MM_SIZE, "G1MM size drift")
    require(left.get("chunk_sha256") == EXPECTED_SOURCE_G1MM_SHA256 and right.get("chunk_sha256") == EXPECTED_TARGET_G1MM_SHA256, "G1MM hash drift")
    source_start = int(left["chunk_offset"]); target_start = int(right["chunk_offset"])
    source_chunk = source_payload[source_start:source_start + EXPECTED_G1MM_SIZE]
    candidate = target_payload[:target_start] + source_chunk + target_payload[target_start + EXPECTED_G1MM_SIZE:]
    require(len(candidate) == len(target_payload), "same-size G1MM splice changed G1M length")
    parsed_candidate = br.parse_g1m_material_parameters(candidate, label="candidate:PC00_Scl_W_default.g1m")
    before = list(target_parsed.get("chunks", [])); after = list(parsed_candidate.get("chunks", []))
    require(len(before) == len(after), "candidate top-level chunk count changed")
    changed_rows = []
    for old, new in zip(before, after):
        require(old.get("chunk_magic") == new.get("chunk_magic") and old.get("chunk_version") == new.get("chunk_version") and old.get("chunk_offset") == new.get("chunk_offset") and old.get("chunk_size") == new.get("chunk_size"), "candidate top-level chunk envelope changed")
        if old.get("chunk_sha256") != new.get("chunk_sha256"):
            changed_rows.append((old, new))
    require(len(changed_rows) == 1 and changed_rows[0][0].get("chunk_magic") == G1MM_CHUNK_MAGIC, "candidate changed more than G1MM")
    require(changed_rows[0][1].get("chunk_sha256") == EXPECTED_SOURCE_G1MM_SHA256, "candidate G1MM is not exact Original chunk")
    return candidate, {
        "candidate_member_sha256": sha256_bytes(candidate),
        "candidate_member_size": len(candidate),
        "g1mm_chunk_index": int(right["chunk_index"]),
        "g1mm_target_offset": target_start,
        "g1mm_source_offset": source_start,
        "g1mm_size": EXPECTED_G1MM_SIZE,
        "g1mm_version": EXPECTED_G1MM_VERSION,
        "source_g1mm_sha256": EXPECTED_SOURCE_G1MM_SHA256,
        "target_g1mm_sha256": EXPECTED_TARGET_G1MM_SHA256,
        "other_top_level_chunks_preserved": True,
    }


def rebuild_earc_with_members(
    br: Any,
    target_parent: Path,
    source_default_member: bytes,
    source_retained_member: bytes,
) -> tuple[bytes, list[dict[str, Any]], dict[str, Any]]:
    stage70 = load_module(SCRIPT_DIR / "prepare_bathroom_river_parent_elixir_repack_test.py", "stage149_stage70")
    decoded, container, _metadata = stage70.decode_parent(target_parent, MAX_PARENT_BYTES)
    parsed = br.parse_earc_payload(decoded, label=NORMALIZED_PARENT_PATH, include_member_payloads=True)
    members = list(parsed.get("members", []))
    require(members, "target pc00_scl_w parent has no members")
    by_key = {str(row["comparison_key"]): row for row in members}
    default_row = by_key.get(SELECTED_MEMBER_KEY)
    retained_row = by_key.get(RETAINED_MEMBER_KEY)
    require(default_row is not None, f"target parent lacks {SELECTED_MEMBER_KEY}")
    require(retained_row is not None, f"target parent lacks {RETAINED_MEMBER_KEY}")
    default_payload = default_row.get("payload")
    retained_target_payload = retained_row.get("payload")
    require(isinstance(default_payload, (bytes, bytearray)), "target Scl_W_default payload unavailable")
    require(isinstance(retained_target_payload, (bytes, bytearray)), "target School_Wet payload unavailable")
    default_payload = bytes(default_payload)
    retained_target_payload = bytes(retained_target_payload)
    require(len(retained_target_payload) == EXPECTED_RETAINED_TARGET_MEMBER_SIZE, "target School_Wet size drift")
    require(sha256_bytes(retained_target_payload) == EXPECTED_RETAINED_TARGET_MEMBER_SHA256, "target School_Wet hash drift")
    require(len(source_retained_member) == EXPECTED_RETAINED_SOURCE_MEMBER_SIZE, "source School_Wet size drift")
    require(sha256_bytes(source_retained_member) == EXPECTED_RETAINED_SOURCE_MEMBER_SHA256, "source School_Wet hash drift")
    candidate_default, splice_meta = splice_g1mm_chunk(br, default_payload, source_default_member)
    candidate_default_sha = sha256_bytes(candidate_default)

    filename_size = int(parsed.get("filename_size", 0))
    flags = int(parsed.get("flags", 0))
    header_size = 0x1C
    name_bytes = 0x20 + filename_size * 0x10
    entry_size = 8 + name_bytes
    table_size = len(members) * entry_size
    payloads: list[tuple[str, bytes]] = []
    for row in members:
        item = row.get("payload")
        require(isinstance(item, (bytes, bytearray)), f"member payload unavailable: {row.get('name')}")
        key = str(row["comparison_key"])
        if key == SELECTED_MEMBER_KEY:
            content = candidate_default
        elif key == RETAINED_MEMBER_KEY:
            content = source_retained_member
        else:
            content = bytes(item)
        payloads.append((str(row.get("name", "")), content))

    payload_size = sum(len(content) for _name, content in payloads)
    output = bytearray(header_size + table_size + payload_size)
    struct.pack_into("<7I", output, 0, 0x45415243, filename_size, payload_size, header_size, table_size, len(payloads), flags)
    offset = header_size + table_size
    for index, (name, content) in enumerate(payloads):
        table = header_size + index * entry_size
        encoded_name = name.encode("utf-8") + b"\x00"
        require(len(encoded_name) <= name_bytes, f"EARC member name no longer fits: {name}")
        struct.pack_into("<2I", output, table, offset, len(content))
        output[table + 8:table + 8 + len(encoded_name)] = encoded_name
        output[offset:offset + len(content)] = content
        offset += len(content)
    decoded_candidate = bytes(output)
    if container == "gust_chunked_zlib":
        encoded = bytearray()
        for start in range(0, len(decoded_candidate), 0x4000):
            compressed = zlib.compress(decoded_candidate[start:start + 0x4000], 9)
            encoded.extend(len(compressed).to_bytes(4, "little"))
            encoded.extend(compressed)
        encoded.extend((0).to_bytes(4, "little"))
        candidate = bytes(encoded)
    elif container == "gzip":
        import gzip
        candidate = gzip.compress(decoded_candidate, compresslevel=9, mtime=0)
    elif container == "zlib":
        candidate = zlib.compress(decoded_candidate, 9)
    elif container in {"raw", "raw_unrecognized_gz"}:
        candidate = decoded_candidate
    else:
        raise WetDefaultG1MMProfileError(f"unsupported variable-size parent container: {container}")

    with tempfile.TemporaryDirectory(prefix="stage149-parent-verify-") as td:
        verify_path = Path(td) / "candidate.elixir.gz"
        verify_path.write_bytes(candidate)
        reopened = br.read_earc_archive(verify_path, maximum_bytes=MAX_PARENT_BYTES, include_member_payloads=True)
    after = {str(row["comparison_key"]): row for row in reopened.get("members", [])}
    require(set(after) == set(by_key), "candidate parent member set changed")
    verification = []
    changed = 0
    for key in sorted(by_key, key=str.casefold):
        before = by_key[key]
        right = after[key]
        if key == SELECTED_MEMBER_KEY:
            expected_sha = candidate_default_sha
            role = "material_probe_default_g1mm"
        elif key == RETAINED_MEMBER_KEY:
            expected_sha = EXPECTED_RETAINED_SOURCE_MEMBER_SHA256
            role = "retained_confirmed_partial_school_wet"
        else:
            expected_sha = str(before.get("sha256", ""))
            role = "preserved"
        verified = right.get("sha256") == expected_sha and str(right.get("name", "")) == str(before.get("name", ""))
        if right.get("sha256") != before.get("sha256"):
            changed += 1
        verification.append({
            "member_key": key,
            "member_name": before.get("name", ""),
            "profile_role": role,
            "selected_for_profile": key in {SELECTED_MEMBER_KEY, RETAINED_MEMBER_KEY},
            "target_size": before.get("size", ""),
            "candidate_size": right.get("size", ""),
            "target_sha256": before.get("sha256", ""),
            "candidate_sha256": right.get("sha256", ""),
            "verified": verified,
        })
    require(changed == 2 and all(bool(row["verified"]) for row in verification), "candidate parent verification failed")
    return candidate, verification, {
        "container": container,
        "member_count": len(members),
        "decoded_candidate_size": len(decoded_candidate),
        "changed_inner_member_count": 2,
        "retained_school_wet_source_sha256": EXPECTED_RETAINED_SOURCE_MEMBER_SHA256,
        **splice_meta,
    }

def resolve_source_parent(project_root: Path, original_root: Path | None, gust_pak: Path, timeout_seconds: int) -> Path:
    br = load_module(project_root / "Blue_Reflection_Text_Tool/br_restoration_tool.py", "stage149_br_source")
    stage125 = load_module(SCRIPT_DIR / "125_collect_character_state_exact_rehydration_evidence.py", "stage149_stage125")
    inventories = stage125.load_asset_inventories(project_root)
    key = ("source", NORMALIZED_PARENT_PATH.casefold())
    require(key in inventories, "source pc00_scl_w inventory entry missing")
    pair_id, entry = inventories[key]
    workspace = project_root / ".local/build/quartet_restoration"
    local = br.inventory_workspace_file(workspace, "source", pair_id, str(entry["archive"]), str(entry["path"]))
    if not local.is_file():
        require(original_root is not None, "source extraction cache is missing; BR1_ORIGINAL_ROOT/original root is required")
        # Extract the Original source archive only. Stage 125's generic cache helper
        # deliberately requires both game roots because it serves paired analyses;
        # this profile builder needs no target cache and must not force an unrelated
        # Quartet extraction merely to obtain one Original parent.
        archive = stage125.resolve_game_archive(original_root, SOURCE_ARCHIVE_RELATIVE_PATH)
        gust_sha256 = sha256_file(gust_pak)
        br.extract_archive(
            archive=archive,
            game_root=original_root.expanduser().resolve(),
            gust_pak=gust_pak,
            gust_pak_sha256=gust_sha256,
            pair_id=pair_id,
            side="source",
            workspace_root=workspace,
            timeout_seconds=timeout_seconds,
        )
    require(local.is_file(), f"source pc00_scl_w extraction missing: {local}")
    require(sha256_file(local) == EXPECTED_SOURCE_PARENT_SHA256, "source pc00_scl_w parent hash drift")
    return local


def source_scl_w_members(project_root: Path, source_parent: Path) -> tuple[bytes, bytes]:
    br = load_module(project_root / "Blue_Reflection_Text_Tool/br_restoration_tool.py", "stage149_br_source_member")
    parsed = br.read_earc_archive(source_parent, maximum_bytes=MAX_PARENT_BYTES, include_member_payloads=True)
    by_key = {str(row["comparison_key"]): row for row in parsed.get("members", [])}
    default = by_key.get(SELECTED_MEMBER_KEY)
    retained = by_key.get(RETAINED_MEMBER_KEY)
    require(default is not None, "source pc00_scl_w lacks Scl_W_default member")
    require(retained is not None, "source pc00_scl_w lacks School_Wet member")
    default_payload = default.get("payload")
    retained_payload = retained.get("payload")
    require(isinstance(default_payload, (bytes, bytearray)), "source Scl_W_default payload unavailable")
    require(isinstance(retained_payload, (bytes, bytearray)), "source School_Wet payload unavailable")
    default_bytes = bytes(default_payload)
    retained_bytes = bytes(retained_payload)
    require(len(default_bytes) == EXPECTED_SOURCE_MEMBER_SIZE, "source Scl_W_default size drift")
    require(sha256_bytes(default_bytes) == EXPECTED_SOURCE_MEMBER_SHA256, "source Scl_W_default hash drift")
    require(len(retained_bytes) == EXPECTED_RETAINED_SOURCE_MEMBER_SIZE, "source School_Wet size drift")
    require(sha256_bytes(retained_bytes) == EXPECTED_RETAINED_SOURCE_MEMBER_SHA256, "source School_Wet hash drift")
    parsed_g1m = br.parse_g1m_material_parameters(default_bytes, label="source:PC00_Scl_W_default.g1m")
    require(bool(parsed_g1m.get("chunks")), "source Scl_W_default G1M did not parse")
    return default_bytes, retained_bytes

def find_parent_member(members: Mapping[str, Mapping[str, Any]]) -> tuple[str, Mapping[str, Any]]:
    matches = [(key, row) for key, row in members.items() if str(row.get("name", "")).replace("\\", "/").casefold().endswith(TARGET_PARENT_SUFFIX)]
    require(len(matches) == 1, f"expected exactly one pc00_scl_w parent in PACK10_02, found {len(matches)}")
    return matches[0]


def build_profile_from_inputs(
    project_root: Path,
    *, baseline_archive: Path,
    source_default_member: bytes,
    source_retained_member: bytes,
    gust_pak: Path,
    workspace_root: Path,
    manifest_root: Path,
    timeout_seconds: int,
) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    br = load_module(project_root / "Blue_Reflection_Text_Tool/br_restoration_tool.py", "stage149_br_build")
    baseline_archive = baseline_archive.resolve()
    require(baseline_archive.is_file(), f"missing current Quartet PACK10_02: {baseline_archive}")
    require(gust_pak.is_file() and os.access(gust_pak, os.X_OK), f"gust_pak missing or not executable: {gust_pak}")
    progress("hashing current installed PACK10_02 dynamic baseline (read-only)")
    baseline_sha = sha256_file(baseline_archive)
    baseline_size = baseline_archive.stat().st_size
    workspace_root.mkdir(parents=True, exist_ok=True)
    disk_free_before_build = shutil.disk_usage(workspace_root).free
    required_free_bytes = baseline_size * 2 + 2 * 1024 * 1024 * 1024
    progress(f"workspace free space: {disk_free_before_build} bytes; conservative minimum for build: {required_free_bytes} bytes")
    require(disk_free_before_build >= required_free_bytes,
            f"insufficient free space for local PACK10_02 build: free={disk_free_before_build}, required>={required_free_bytes}")

    profile_root = workspace_root / WORKSPACE_SUBDIR / PROFILE_ID
    harness_marker = profile_root / "HARNESS.json"
    if profile_root.exists():
        require(harness_marker.is_file(), f"refusing to remove unmarked profile root: {profile_root}")
        marker_data = json.loads(harness_marker.read_text(encoding="utf-8"))
        require(marker_data.get("type") == "br_quartet_restoration_wet_school_composite_g1mm_fast_test_profile_workspace"
                and marker_data.get("profile_id") == PROFILE_ID,
                f"refusing to remove foreign profile root: {profile_root}")
        shutil.rmtree(profile_root)
    profile_root.mkdir(parents=True, exist_ok=True)
    atomic_json(harness_marker, {
        "type": "br_quartet_restoration_wet_school_composite_g1mm_fast_test_profile_workspace",
        "format_version": 1,
        "profile_id": PROFILE_ID,
        "status": "building",
    })
    baseline_extract = profile_root / "baseline_extract"
    verify_extract = profile_root / "verify_extract"
    output_dir = profile_root / "output" / "Data"
    output_dir.mkdir(parents=True, exist_ok=True)

    validation_rows: list[dict[str, Any]] = []
    pak_rows: list[dict[str, Any]] = []
    parent_rows: list[dict[str, Any]] = []
    manifest_diff_rows: list[dict[str, Any]] = []
    try:
        progress("extracting current PACK10_02 into local workspace")
        manifest_path, baseline_manifest = br._extract_pak_for_repack_test(
            archive=baseline_archive, destination=baseline_extract, gust_pak=gust_pak,
            timeout_seconds=timeout_seconds, log_name="baseline_extract.log",
        )
        baseline_members = br._manifest_member_hashes(baseline_extract, baseline_manifest)
        baseline_signature = br._gust_manifest_semantic_signature(baseline_manifest)
        parent_key, parent_row = find_parent_member(baseline_members)
        target_parent = baseline_extract / Path(str(parent_row["name"]))
        require(sha256_file(target_parent) == EXPECTED_TARGET_PARENT_SHA256, "current PACK10_02 pc00_scl_w parent is not the expected Quartet baseline member")

        progress("rebuilding pc00_scl_w with retained Original School_Wet plus Original G1MM inside Quartet Scl_W_default")
        candidate_parent, parent_rows, parent_meta = rebuild_earc_with_members(br, target_parent, source_default_member, source_retained_member)
        candidate_parent_sha = sha256_bytes(candidate_parent)
        target_parent.write_bytes(candidate_parent)
        require(sha256_file(target_parent) == candidate_parent_sha, "candidate parent write verification failed")

        stage_manifest = br._load_gust_pak_manifest(manifest_path)
        output_name = str(stage_manifest["safe_output_name"])
        progress("repacking local PACK10_02 Fast Test profile")
        br._run_gust_pak(
            gust_pak=gust_pak, argument_name=manifest_path.name, cwd=baseline_extract,
            log_path=profile_root / "repack.log", timeout_seconds=timeout_seconds,
        )
        generated = baseline_extract / output_name
        require(generated.is_file(), "gust_pak did not produce PACK10_02 candidate")
        final_output = output_dir / "PACK10_02.PAK"
        os.replace(generated, final_output)
        output_sha = sha256_file(final_output)
        output_size = final_output.stat().st_size

        # Free the large extraction before the verification extraction.
        progress("freeing baseline extraction before full profile verification")
        shutil.rmtree(baseline_extract)
        progress("fully re-extracting local profile PAK for byte-level verification")
        verify_manifest_path, verify_manifest = br._extract_pak_for_repack_test(
            archive=final_output, destination=verify_extract, gust_pak=gust_pak,
            timeout_seconds=timeout_seconds, log_name="verify_extract.log",
        )
        verify_members = br._manifest_member_hashes(verify_extract, verify_manifest)
        verify_signature = br._gust_manifest_semantic_signature(verify_manifest)
        set_delta = set(baseline_members) ^ set(verify_members)
        changed_keys = sorted(
            key for key in set(baseline_members) | set(verify_members)
            if baseline_members.get(key, {}).get("sha256") != verify_members.get(key, {}).get("sha256")
        )
        require(not set_delta, f"PACK10_02 member set changed: {sorted(set_delta)[:8]}")
        require(changed_keys == [parent_key], f"PACK10_02 changed unexpected members: {changed_keys[:8]}")
        require(verify_signature == baseline_signature, "PACK10_02 stable manifest semantics changed")
        manifest_diff_rows = br._gust_manifest_metadata_differences(
            baseline_manifest, verify_manifest, profile_id=PROFILE_ID, modified_member_keys={parent_key},
        )
        require(not any(row.get("gate_effect") == "validation_gate" for row in manifest_diff_rows), "stable PACK10_02 manifest fields changed")
        verified_parent = verify_extract / Path(str(verify_members[parent_key]["name"]))
        require(sha256_file(verified_parent) == candidate_parent_sha, "repacked pc00_scl_w parent hash mismatch")
        stage70 = load_module(SCRIPT_DIR / "prepare_bathroom_river_parent_elixir_repack_test.py", "stage149_stage70_verify")
        decoded_verified, _kind, _meta = stage70.decode_parent(verified_parent, MAX_PARENT_BYTES)
        parsed_verified = br.parse_earc_payload(decoded_verified, label="verify:pc00_scl_w", include_member_payloads=True)
        verified_selected = {str(row["comparison_key"]): row for row in parsed_verified.get("members", [])}.get(SELECTED_MEMBER_KEY)
        require(verified_selected is not None and verified_selected.get("sha256") == parent_meta["candidate_member_sha256"], "repacked Scl_W_default G1MM-splice G1M mismatch")
        verified_payload = verified_selected.get("payload")
        require(isinstance(verified_payload, (bytes, bytearray)), "repacked Scl_W_default payload unavailable")
        verified_g1m = bytes(verified_payload)
        parsed_verify_g1m = br.parse_g1m_material_parameters(verified_g1m, label="verify:PC00_Scl_W_default.g1m")
        verify_g1mm = [row for row in parsed_verify_g1m.get("chunks", []) if row.get("chunk_magic") == G1MM_CHUNK_MAGIC]
        require(len(verify_g1mm) == 1 and verify_g1mm[0].get("chunk_sha256") == EXPECTED_SOURCE_G1MM_SHA256, "repacked G1MM chunk mismatch")
        progress("rechecking installed PACK10_02 remained byte-identical")
        require(sha256_file(baseline_archive) == baseline_sha and baseline_archive.stat().st_size == baseline_size, "installed PACK10_02 changed during local build")

        for key in sorted(baseline_members, key=str.casefold):
            left = baseline_members[key]
            right = verify_members[key]
            selected = key == parent_key
            pak_rows.append({
                "member_key": key,
                "member_name": left.get("name", ""),
                "selected_parent_member": selected,
                "baseline_size": left.get("size", ""),
                "profile_size": right.get("size", ""),
                "baseline_sha256": left.get("sha256", ""),
                "profile_sha256": right.get("sha256", ""),
                "verified": right.get("sha256") == (candidate_parent_sha if selected else left.get("sha256")),
            })
        require(all(row["verified"] for row in pak_rows), "PACK10_02 per-member verification failed")

        local_profile_path = final_output.relative_to(project_root).as_posix()
        manifest_path_out = manifest_root / f"{PROFILE_ID}.json"
        manifest = {
            "schema_version": 1,
            "profile_id": PROFILE_ID,
            "target_relative_path": TARGET_RELATIVE_PATH,
            "baseline_sha256": baseline_sha,
            "baseline_size": baseline_size,
            "disk_free_before_build": disk_free_before_build,
            "conservative_required_free_bytes": required_free_bytes,
            "profile_sha256": output_sha,
            "profile_size": output_size,
            "local_profile_path": local_profile_path,
            "changed_member_count": 1,
            "changed_members": [str(parent_row["name"]).replace("\\", "/")],
            "runtime_validated": False,
            "production_eligible": False,
            "normal_composer_eligible": False,
            "fast_test_only": True,
            "candidate_semantics": "retained_partial_school_wet_plus_default_material_g1mm_transparency_probe",
            "semantics_confirmed": False,
            "retained_partial_visual_restoration": True,
            "retained_inner_member": RETAINED_MEMBER_NAME,
            "retained_inner_member_source_sha256": EXPECTED_RETAINED_SOURCE_MEMBER_SHA256,
            "retained_inner_member_target_sha256": EXPECTED_RETAINED_TARGET_MEMBER_SHA256,
            "selected_inner_member": SELECTED_MEMBER_NAME,
            "selected_inner_member_source_sha256": EXPECTED_SOURCE_MEMBER_SHA256,
            "selected_inner_member_target_sha256": EXPECTED_TARGET_MEMBER_SHA256,
            "candidate_inner_member_sha256": parent_meta["candidate_member_sha256"],
            "g1mm_chunk_magic": G1MM_CHUNK_MAGIC,
            "g1mm_chunk_version": EXPECTED_G1MM_VERSION,
            "g1mm_chunk_size": EXPECTED_G1MM_SIZE,
            "g1mm_source_sha256": EXPECTED_SOURCE_G1MM_SHA256,
            "g1mm_target_sha256": EXPECTED_TARGET_G1MM_SHA256,
            "workstream_id": "quartet_restoration",
            "workstream_version": TOOL_VERSION,
        }
        atomic_json(manifest_path_out, manifest)
        atomic_json(profile_root / "PROFILE.json", manifest)
        atomic_json(harness_marker, {
            "type": "br_quartet_restoration_wet_school_composite_g1mm_fast_test_profile_workspace",
            "format_version": 1,
            "profile_id": PROFILE_ID,
            "status": "ready",
            "profile_sha256": output_sha,
        })
        checks = {
            "baseline_archive_unchanged": sha256_file(baseline_archive) == baseline_sha,
            "target_parent_precondition_exact": True,
            "source_scl_w_default_member_exact": sha256_bytes(source_default_member) == EXPECTED_SOURCE_MEMBER_SHA256,
            "source_school_wet_retained_member_exact": sha256_bytes(source_retained_member) == EXPECTED_RETAINED_SOURCE_MEMBER_SHA256,
            "exactly_two_inner_elixir_members_changed": sum(row["target_sha256"] != row["candidate_sha256"] for row in parent_rows) == 2,
            "all_other_inner_elixir_members_preserved": all(row["verified"] for row in parent_rows),
            "retained_school_wet_exact_original": next(row for row in parent_rows if row["member_key"] == RETAINED_MEMBER_KEY)["candidate_sha256"] == EXPECTED_RETAINED_SOURCE_MEMBER_SHA256,
            "source_scl_w_default_g1m_reparsed": True,
            "candidate_only_g1mm_chunk_changed": parent_meta.get("other_top_level_chunks_preserved") is True,
            "candidate_g1mm_exact_original": parent_meta.get("source_g1mm_sha256") == EXPECTED_SOURCE_G1MM_SHA256,
            "exactly_one_pack_member_changed": changed_keys == [parent_key],
            "all_other_pack_members_preserved": all(row["verified"] for row in pak_rows),
            "pack_manifest_semantics_preserved": verify_signature == baseline_signature,
            "profile_runtime_unvalidated": manifest["runtime_validated"] is False,
            "profile_nonproduction": manifest["production_eligible"] is False,
            "profile_fast_test_only": manifest["fast_test_only"] is True,
            "installed_game_unchanged": sha256_file(baseline_archive) == baseline_sha,
        }
        validation_rows = [{"check_name": name, "passed": passed} for name, passed in checks.items()]
        require(all(checks.values()), "wet-school composite G1MM profile validation failed")
        profile_summary = {
            **manifest,
            "candidate_parent_sha256": candidate_parent_sha,
            "candidate_parent_size": len(candidate_parent),
            "parent_container_kind": parent_meta["container"],
            "parent_member_count": parent_meta["member_count"],
            "pak_member_count": len(pak_rows),
            "baseline_manifest_parse_mode": baseline_manifest.get("safe_parse_mode", "unknown"),
            "verification_manifest_parse_mode": verify_manifest.get("safe_parse_mode", "unknown"),
            "manifest_relative_path": manifest_path_out.relative_to(project_root).as_posix(),
        }
        return profile_summary, parent_rows, pak_rows, validation_rows + [{"check_name": "stable_manifest_difference_rows_zero", "passed": not any(row.get("gate_effect") == "validation_gate" for row in manifest_diff_rows)}]
    finally:
        shutil.rmtree(baseline_extract, ignore_errors=True)
        shutil.rmtree(verify_extract, ignore_errors=True)


def build_report(
    project_root: Path,
    *, quartet_root: Path,
    original_root: Path | None,
    gust_pak: Path,
    report_root: Path | None = None,
    output_report_root: Path | None = None,
    workspace_root: Path | None = None,
    manifest_root: Path | None = None,
    baseline_archive: Path | None = None,
    source_parent_override: Path | None = None,
    timeout_seconds: int = 7200,
    validate_evidence: bool = True,
    create_archive: bool = True,
) -> tuple[Path | None, dict[str, Any]]:
    project_root = project_root.resolve()
    version = (project_root / "workstreams/quartet_restoration/VERSION").read_text(encoding="utf-8").strip()
    require(tuple(map(int, version.split("."))) >= tuple(map(int, TOOL_VERSION.split("."))), f"expected quartet_restoration {TOOL_VERSION} or newer, found {version}")
    report_root = (report_root or project_root / ".local/reports/quartet_restoration").resolve()
    output_report_root = (output_report_root or report_root).resolve()
    workspace_root = (workspace_root or project_root / ".local/build/quartet_restoration").resolve()
    manifest_root = (manifest_root or workspace_root / MANIFEST_SUBDIR).resolve()
    output = output_report_root / REPORT_DIR
    archive = output_report_root / REPORT_NAME
    if output.exists():
        shutil.rmtree(output)
    output.mkdir(parents=True, exist_ok=True)

    progress("validating immutable wet-state discovery prerequisites") if validate_evidence else progress("using synthetic prerequisite mode")
    prerequisite = validate_prerequisites(project_root, report_root) if validate_evidence else {
        "stage148_activation_evidence_sha256": "synthetic",
        "stage148_rollback_evidence_sha256": "synthetic",
        "runtime_stable": True,
        "target_transparency_restored": False,
        "exact_pack10_02_baseline_restored": True,
        "stage125_report_sha256": "synthetic",
        "stage126_report_sha256": "synthetic",
        "stage127_report_sha256": "synthetic",
        "selected_member_source_sha256": EXPECTED_SOURCE_MEMBER_SHA256,
        "selected_member_target_sha256": EXPECTED_TARGET_MEMBER_SHA256,
        "scl_w_default_parameter_diff_rows": 12,
        "scl_w_default_parameter_names": ["emissiveColor", "parameterForMeshBlend"],
        "mesh_blend_broad_pattern_rows": 2047,
        "semantics_confirmed": False,
    }
    progress("resolving exact Original pc00_scl_w source parent")
    source_parent = source_parent_override.resolve() if source_parent_override else resolve_source_parent(project_root, original_root, gust_pak, timeout_seconds)
    source_default_member, source_retained_member = source_scl_w_members(project_root, source_parent)
    baseline = baseline_archive.resolve() if baseline_archive else (quartet_root.resolve() / TARGET_RELATIVE_PATH)
    progress("building local wet-school composite G1MM Fast Test profile; installed game remains read-only")
    profile, parent_rows, pak_rows, validation_rows = build_profile_from_inputs(
        project_root,
        baseline_archive=baseline,
        source_default_member=source_default_member,
        source_retained_member=source_retained_member,
        gust_pak=gust_pak.resolve(),
        workspace_root=workspace_root,
        manifest_root=manifest_root,
        timeout_seconds=timeout_seconds,
    )

    write_tsv(output / "PROFILE.tsv", list(profile), [profile])
    write_tsv(output / "PC00_SCL_W_PARENT_MEMBER_VERIFICATION.tsv", list(parent_rows[0]), parent_rows)
    write_tsv(output / "PACK10_02_MEMBER_VERIFICATION.tsv", list(pak_rows[0]), pak_rows)
    write_tsv(output / "VALIDATIONS.tsv", ["check_name", "passed"], validation_rows)
    write_tsv(output / "PREREQUISITES.tsv", ["key", "value"], [{"key": key, "value": json.dumps(value, sort_keys=True) if isinstance(value, (list, dict)) else value} for key, value in prerequisite.items()])
    if OBSERVATION_PATH.is_file():
        (output / "RUNTIME_OBSERVATION.json").write_text(OBSERVATION_PATH.read_text(encoding="utf-8"), encoding="utf-8")
    summary = {
        "type": "br_quartet_restoration_hinako_wet_school_composite_g1mm_fast_test_profile_evidence_summary",
        "format_version": 1,
        "tool_version": TOOL_VERSION,
        "status": "retained_partial_school_wet_plus_default_g1mm_fast_test_profile_built_fully_reextracted_not_installed_runtime_unvalidated",
        "profile_id": PROFILE_ID,
        "target_relative_path": TARGET_RELATIVE_PATH,
        "baseline_sha256": profile["baseline_sha256"],
        "baseline_size": profile["baseline_size"],
        "profile_sha256": profile["profile_sha256"],
        "profile_size": profile["profile_size"],
        "selected_parent_member": profile["changed_members"][0],
        "retained_partial_inner_member": RETAINED_MEMBER_NAME,
        "retained_partial_inner_member_source_sha256": EXPECTED_RETAINED_SOURCE_MEMBER_SHA256,
        "retained_partial_inner_member_target_sha256": EXPECTED_RETAINED_TARGET_MEMBER_SHA256,
        "retained_partial_visual_restoration_confirmed": True,
        "selected_inner_member": SELECTED_MEMBER_NAME,
        "selected_inner_member_source_sha256": EXPECTED_SOURCE_MEMBER_SHA256,
        "selected_inner_member_target_sha256": EXPECTED_TARGET_MEMBER_SHA256,
        "selected_inner_member_source_size": EXPECTED_SOURCE_MEMBER_SIZE,
        "selected_inner_member_target_size": EXPECTED_TARGET_MEMBER_SIZE,
        "candidate_inner_member_sha256": profile["candidate_inner_member_sha256"],
        "g1mm_chunk_magic": G1MM_CHUNK_MAGIC,
        "g1mm_chunk_version": EXPECTED_G1MM_VERSION,
        "g1mm_chunk_size": EXPECTED_G1MM_SIZE,
        "g1mm_source_sha256": EXPECTED_SOURCE_G1MM_SHA256,
        "g1mm_target_sha256": EXPECTED_TARGET_G1MM_SHA256,
        "parent_changed_member_rows": sum(row["target_sha256"] != row["candidate_sha256"] for row in parent_rows),
        "parent_unchanged_member_rows": sum(row["target_sha256"] == row["candidate_sha256"] for row in parent_rows),
        "pak_changed_member_rows": sum(row["baseline_sha256"] != row["profile_sha256"] for row in pak_rows),
        "pak_unchanged_member_rows": sum(row["baseline_sha256"] == row["profile_sha256"] for row in pak_rows),
        "validation_rows": len(validation_rows),
        "validation_failures": sum(not bool(row["passed"]) for row in validation_rows),
        "runtime_validated": False,
        "production_eligible": False,
        "normal_composer_eligible": False,
        "fast_test_only": True,
        "visual_effect_confirmed": False,
        "censorship_semantics_confirmed": False,
        "previous_probe_runtime_stable": True,
        "previous_probe_transparency_restored": False,
        "previous_probe_insufficient_for_transparency_restoration": True,
        "previous_probe_partial_visual_restoration_must_be_retained": True,
        "stage148_activation_evidence_sha256": ACTIVATION_SHA256,
        "stage148_rollback_evidence_sha256": ROLLBACK_SHA256,
        "exact_pack10_02_baseline_restored_before_build": True,
        "glowlight_deferred": True,
        "policy": {
            "candidate_is_runtime_probe_not_final_restoration": True,
            "whole_pc00_scl_w_parent_not_transplanted": True,
            "whole_scl_w_default_g1m_not_transplanted": True,
            "exact_original_school_wet_member_retained_from_runtime_confirmed_partial_probe": True,
            "exactly_two_inner_members_changed": True,
            "only_same_size_g1mm_chunk_spliced_inside_quartet_scl_w_default_g1m": True,
            "all_other_top_level_g1m_chunks_preserved": True,
            "broad_parameterForMeshBlend_pattern_not_treated_as_censorship_proof": True,
            "g1mm_source_and_target_version_and_size_match": True,
            "g1mg_geometry_chunk_remains_quartet": True,
            "current_installed_pack10_02_used_read_only_as_repack_base": True,
            "profile_pak_built_only_under_local_workspace": True,
            "profile_pak_fully_reextracted": True,
            "installed_game_modified": False,
            "runtime_activation_performed": False,
            "core_modified": False,
            "translation_modified": False,
            "legacy_dlc_modified": False,
            "git_modified": False,
            "glowlight_activated": False,
        },
        "next_action": "Upload this metadata-only evidence. If it verifies, prepare one separately authorized PACK10_02 Fast Test Lab activation against this exact dynamic baseline, test the existing wet-school-uniform save, exit fully, then roll back exactly. Do not promote from build success alone.",
    }
    atomic_json(output / "SUMMARY.json", summary)
    progress("metadata-only evidence assembled; no game file was modified")
    require(not [p for p in output.rglob("*") if p.is_file() and p.name.casefold().endswith(FORBIDDEN_REPORT_EXTENSIONS)], "proprietary payload extension in evidence")
    if create_archive:
        make_archive(output, archive)
        return archive, summary
    return None, summary


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path, default=PROJECT_ROOT_DEFAULT)
    parser.add_argument("--quartet-root", type=Path, default=Path(os.environ["BR1_QUARTET_ROOT"]) if os.environ.get("BR1_QUARTET_ROOT") else None)
    parser.add_argument("--original-root", type=Path, default=Path(os.environ["BR1_ORIGINAL_ROOT"]) if os.environ.get("BR1_ORIGINAL_ROOT") else None)
    parser.add_argument("--gust-pak", type=Path)
    parser.add_argument("--timeout-seconds", type=int, default=7200)
    args = parser.parse_args(argv)
    project_root = args.project_root.expanduser().resolve()
    require(args.quartet_root is not None, "Quartet root is required via --quartet-root or BR1_QUARTET_ROOT")
    gust = args.gust_pak or (project_root / ".local/vendor/gust_tools/gust_pak")
    archive, summary = build_report(
        project_root,
        quartet_root=args.quartet_root.expanduser().resolve(),
        original_root=args.original_root.expanduser().resolve() if args.original_root else None,
        gust_pak=gust.expanduser().resolve(),
        timeout_seconds=args.timeout_seconds,
    )
    print(json.dumps(summary, indent=2, sort_keys=True))
    if archive:
        print(f"[stage149] report archive: {archive}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except WetDefaultG1MMProfileError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(2)
