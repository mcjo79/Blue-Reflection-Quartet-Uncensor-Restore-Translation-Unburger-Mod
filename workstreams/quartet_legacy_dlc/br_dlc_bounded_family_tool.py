#!/usr/bin/env python3
"""Bounded read-only material and cloth-structure audit for two DLC families.

The stage consumes the validated external-dependency and nested-container
reports. It reopens only the selected parent members for one target-present
positive control and one BR1-only portable candidate, inventories nested G1M
material parameters and safe technical reference tokens, and records structural
metadata for SWG/Oid descriptors. It exports no raw payloads, builds no profile,
and never modifies either game installation.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import re
import shutil
import statistics
import sys
import tarfile
import tempfile
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT_DEFAULT = SCRIPT_DIR.parent.parent
TEXT_TOOL_DIR = PROJECT_ROOT_DEFAULT / "Blue_Reflection_Text_Tool"
for import_path in (SCRIPT_DIR, TEXT_TOOL_DIR):
    if str(import_path) not in sys.path:
        sys.path.insert(0, str(import_path))

import br_dlc_nested_container_tool as NESTED  # noqa: E402
import br_restoration_tool as BR  # noqa: E402

TOOL_VERSION = "0.0.10"
FORMAT_VERSION = 1
REPORT_DIR_NAME = "bounded_family_evidence"
REPORT_ARCHIVE_NAME = "BR_quartet_legacy_dlc_bounded_family_evidence.tar.zst"
FORBIDDEN_SUFFIXES = {
    ".pak", ".ebm", ".ebd", ".g1m", ".g1t", ".g1a", ".g1e", ".g1s",
    ".elixir", ".gz", ".bin", ".swg", ".dds", ".ktid", ".kts", ".wav", ".ogg",
}
TECHNICAL_TOKEN_RE = re.compile(rb"[A-Za-z0-9_./\\:-]{4,128}")
TOKEN_HINTS = (
    ".g1t", ".g1m", ".swg", ".ktid", ".kts", "texture", "material",
    "cloth", "physics", "skirt", "bone", "joint", "accessory", "tear",
    "default", "pc00", "dlc", "wet", "alpha", "trans", "shader",
)


class BoundedFamilyError(RuntimeError):
    pass


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def scalar(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (dict, list, tuple, set)):
        return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return str(value)


def read_tsv(path: Path) -> list[dict[str, str]]:
    if not path.is_file():
        raise BoundedFamilyError(f"missing prerequisite TSV: {path}")
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return [dict(row) for row in csv.DictReader(handle, delimiter="\t")]


def write_tsv(path: Path, fields: Sequence[str], rows: Iterable[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(fields), delimiter="\t", lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow({field: scalar(row.get(field, "")) for field in fields})


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")


def truthy(value: str) -> bool:
    return str(value).strip().casefold() in {"1", "true", "yes"}


def clean_dir(path: Path) -> None:
    if path.exists():
        shutil.rmtree(path)
    path.mkdir(parents=True, exist_ok=True)


def locate_prerequisite(report_root: Path, directory: str, archive: str, temporary: Path) -> Path:
    direct = report_root / directory
    if direct.is_dir():
        return direct
    packed = report_root / archive
    if not packed.is_file():
        raise BoundedFamilyError(f"missing prerequisite report: {direct} / {packed}")
    import subprocess
    subprocess.run(["tar", "--zstd", "-xf", str(packed), "-C", str(temporary)], check=True)
    extracted = temporary / directory
    if extracted.is_dir():
        return extracted
    candidates = [item for item in temporary.iterdir() if item.is_dir()]
    if len(candidates) == 1:
        return candidates[0]
    raise BoundedFamilyError(f"could not locate extracted prerequisite directory for {packed}")


def make_archive(source_dir: Path, output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="br_dlc_bounded_bundle_") as temp_name:
        temp_tar = Path(temp_name) / "report.tar"
        with tarfile.open(temp_tar, "w", format=tarfile.PAX_FORMAT) as archive:
            for path in sorted(source_dir.rglob("*"), key=lambda item: item.relative_to(source_dir).as_posix().casefold()):
                if not path.is_file():
                    continue
                info = archive.gettarinfo(str(path), arcname=f"{source_dir.name}/{path.relative_to(source_dir).as_posix()}")
                info.uid = info.gid = 0
                info.uname = info.gname = ""
                info.mtime = 0
                with path.open("rb") as handle:
                    archive.addfile(info, handle)
        import subprocess
        subprocess.run(["zstd", "-q", "-f", "-19", str(temp_tar), "-o", str(output)], check=True)


def manifest_rows(report_root: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for path in sorted(report_root.rglob("*"), key=lambda item: item.relative_to(report_root).as_posix().casefold()):
        if not path.is_file() or path.name == "REPORT_MANIFEST.json":
            continue
        if {suffix.casefold() for suffix in path.suffixes} & FORBIDDEN_SUFFIXES:
            raise BoundedFamilyError(f"forbidden asset-like report file: {path}")
        rows.append({
            "path": path.relative_to(report_root).as_posix(),
            "size": path.stat().st_size,
            "sha256": sha256_file(path),
        })
    return rows


def safe_tokens(payload: bytes) -> list[str]:
    result: set[str] = set()
    for raw in TECHNICAL_TOKEN_RE.findall(payload):
        try:
            text = raw.decode("ascii").replace("\\", "/")
        except UnicodeDecodeError:
            continue
        folded = text.casefold()
        if any(hint in folded for hint in TOKEN_HINTS):
            result.add(text)
    return sorted(result, key=str.casefold)


def structural_signature(payload: bytes) -> dict[str, Any]:
    word_count = len(payload) // 4
    words = [int.from_bytes(payload[offset:offset + 4], "little") for offset in range(0, word_count * 4, 4)]
    zero_words = sum(value == 0 for value in words)
    unique_words = len(set(words))
    finite_float_words = 0
    plausible_small_float_words = 0
    for offset in range(0, word_count * 4, 4):
        import struct
        value = struct.unpack_from("<f", payload, offset)[0]
        if math.isfinite(value):
            finite_float_words += 1
            if abs(value) <= 100000.0:
                plausible_small_float_words += 1
    byte_counts = Counter(payload)
    entropy = 0.0
    if payload:
        for count in byte_counts.values():
            p = count / len(payload)
            entropy -= p * math.log2(p)
    tokens = safe_tokens(payload)
    return {
        "size": len(payload),
        "sha256": sha256_bytes(payload),
        "aligned_u32_words": word_count,
        "trailing_bytes": len(payload) % 4,
        "zero_u32_words": zero_words,
        "unique_u32_words": unique_words,
        "finite_float_words": finite_float_words,
        "plausible_small_float_words": plausible_small_float_words,
        "byte_entropy": format(entropy, ".6f"),
        "technical_token_count": len(tokens),
        "technical_tokens": tokens,
        "technical_token_set_sha256": sha256_bytes("\n".join(tokens).encode("utf-8")),
    }


def parse_parent(index: NESTED.PakIndex, internal_path: str, expected_sha256: str, label: str) -> dict[str, Any]:
    raw, entry = NESTED.read_pak_member(index, internal_path)
    actual = sha256_bytes(raw)
    if expected_sha256 and actual != expected_sha256:
        raise BoundedFamilyError(f"parent SHA-256 mismatch for {label}: {actual} != {expected_sha256}")
    decoded, kind, chunks = NESTED.decode_container_bytes(raw, label)
    archive = BR.parse_earc_payload(decoded, label=label, include_member_payloads=True)
    archive["container_kind"] = kind
    archive["chunk_count"] = chunks
    archive["compressed_sha256"] = actual
    archive["compressed_size"] = entry.size
    archive["decoded_sha256"] = sha256_bytes(decoded)
    return archive


def member_map(archive: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
    return {str(row["comparison_key"]): row for row in (archive or {"members": []})["members"]}


def parse_g1m(payload: bytes, label: str) -> tuple[dict[str, Any] | None, str]:
    try:
        return BR.parse_g1m_material_parameters(payload, label=label), "parsed"
    except BR.RestorationError as exc:
        return None, f"parse_error:{exc}"


def compare_structural(left: dict[str, Any], right: dict[str, Any] | None) -> str:
    if right is None:
        return "target_missing"
    if left["sha256"] == right["sha256"]:
        return "present_identical"
    if left["size"] == right["size"]:
        return "present_modified_same_size"
    return "present_modified_size_changed"


def validate_report(report_root: Path) -> dict[str, Any]:
    required = {
        "DLC_BOUNDED_FAMILY_MEMBER_AUDIT.tsv",
        "DLC_BOUNDED_G1M_MATERIAL_PARAMETERS.tsv",
        "DLC_BOUNDED_G1M_MATERIAL_DIFFS.tsv",
        "DLC_BOUNDED_TECHNICAL_REFERENCE_TOKENS.tsv",
        "DLC_BOUNDED_CLOTH_STRUCTURE_AUDIT.tsv",
        "DLC_BOUNDED_SHARED_MEMBER_BINDINGS.tsv",
        "DLC_BOUNDED_FAMILY_GAPS.tsv",
        "DLC_BOUNDED_PROFILE_READINESS.tsv",
        "DLC_BOUNDED_FAMILY_GRAPH.json",
        "SUMMARY.json",
    }
    names = {path.name for path in report_root.iterdir() if path.is_file()}
    missing = sorted(required - names)
    if missing:
        raise BoundedFamilyError("missing report files: " + ", ".join(missing))
    readiness = read_tsv(report_root / "DLC_BOUNDED_PROFILE_READINESS.tsv")
    if len(readiness) != 2:
        raise BoundedFamilyError(f"expected exactly two bounded readiness rows, found {len(readiness)}")
    if any(truthy(row.get("profile_build_allowed", "")) for row in readiness):
        raise BoundedFamilyError("bounded report unexpectedly authorizes profile build")
    kinds = Counter(row.get("candidate_kind", "") for row in readiness)
    if kinds != Counter({"positive_control": 1, "portable_transfer_candidate": 1}):
        raise BoundedFamilyError(f"unexpected bounded candidate kinds: {dict(kinds)}")
    summary = json.loads((report_root / "SUMMARY.json").read_text(encoding="utf-8"))
    if summary.get("policy", {}).get("raw_assets_exported") is not False:
        raise BoundedFamilyError("summary does not preserve metadata-only policy")
    if summary.get("policy", {}).get("profiles_built") is not False:
        raise BoundedFamilyError("summary unexpectedly claims profiles built")
    manifest_rows(report_root)
    return summary


def audit(project_root: Path, original_root: Path, quartet_root: Path, report_root: Path) -> tuple[Path, dict[str, Any]]:
    if not original_root.is_dir() or not quartet_root.is_dir():
        raise BoundedFamilyError("selected BR1 or Quartet installation root does not exist")
    reports_root = project_root / ".local/reports/quartet_legacy_dlc"
    with tempfile.TemporaryDirectory(prefix="br_dlc_bounded_prereq_") as temp_name:
        temp = Path(temp_name)
        external_root = locate_prerequisite(
            reports_root, "external_dependency_closure_evidence",
            "BR_quartet_legacy_dlc_external_dependency_closure_evidence.tar.zst", temp,
        )
        nested_root = locate_prerequisite(
            reports_root, "nested_container_evidence",
            "BR_quartet_legacy_dlc_nested_container_evidence.tar.zst", temp,
        )
        selected = [
            row for row in read_tsv(external_root / "DLC_BOUNDED_FAMILY_CANDIDATES.tsv")
            if truthy(row.get("selected_for_next_audit", ""))
        ]
        selected_kinds = Counter(row.get("candidate_kind", "") for row in selected)
        if len(selected) != 2 or selected_kinds != Counter({"positive_control": 1, "portable_transfer_candidate": 1}):
            raise BoundedFamilyError(f"expected one selected positive control and one portable candidate, got {dict(selected_kinds)}")
        selected_by_content = {row["content_id"]: row for row in selected}
        containers = [
            row for row in read_tsv(nested_root / "DLC_NESTED_CONTAINER_INVENTORY.tsv")
            if row.get("content_id") in selected_by_content
        ]
        nested_bindings = [
            row for row in read_tsv(nested_root / "DLC_NESTED_MEMBER_BINDINGS.tsv")
            if row.get("content_id") in selected_by_content
        ]
        if len(containers) != 4:
            raise BoundedFamilyError(f"expected four selected parent containers, found {len(containers)}")

        clean_dir(report_root)
        source_paks: dict[Path, NESTED.PakIndex] = {}
        target_paks: dict[Path, NESTED.PakIndex] = {}
        parsed_containers: dict[tuple[str, str], dict[str, Any]] = {}
        target_containers: dict[tuple[str, str], dict[str, Any] | None] = {}
        print("[stage19] validating selected bounded families and parent hashes", flush=True)
        for number, row in enumerate(sorted(containers, key=lambda item: (item["content_id"], item["parent_role"])), 1):
            source_archive = original_root / row["source_archive"]
            if source_archive not in source_paks:
                source_paks[source_archive] = NESTED.index_pak(source_archive)
            source = parse_parent(
                source_paks[source_archive], row["source_path"], row["source_sha256"],
                f"source:{row['content_id']}:{row['parent_role']}",
            )
            if row.get("source_decoded_sha256") and source["decoded_sha256"] != row["source_decoded_sha256"]:
                raise BoundedFamilyError(
                    f"source decoded parent SHA-256 mismatch for {row['content_id']} / {row['parent_role']}"
                )
            parsed_containers[(row["content_id"], row["parent_role"])] = source
            target: dict[str, Any] | None = None
            if row.get("target_path"):
                target_archive = quartet_root / row["target_archive"]
                if target_archive not in target_paks:
                    target_paks[target_archive] = NESTED.index_pak(target_archive)
                target = parse_parent(
                    target_paks[target_archive], row["target_path"], "",
                    f"target:{row['content_id']}:{row['parent_role']}",
                )
                if row.get("target_decoded_sha256") and target["decoded_sha256"] != row["target_decoded_sha256"]:
                    raise BoundedFamilyError(
                        f"target decoded parent SHA-256 mismatch for {row['content_id']} / {row['parent_role']}"
                    )
                # Compressed target hashes are not present in the nested report; decoded parent and nested member hashes gate contents.
            target_containers[(row["content_id"], row["parent_role"])] = target
            print(f"[stage19] rehydrated parent {number}/{len(containers)}: {row['content_id']} {row['parent_role']}", flush=True)

        binding_index: dict[tuple[str, str], list[dict[str, str]]] = defaultdict(list)
        for row in nested_bindings:
            binding_index[(row["content_id"], row["parent_path"])].append(row)

        member_rows: list[dict[str, Any]] = []
        parameter_rows: list[dict[str, Any]] = []
        diff_rows: list[dict[str, Any]] = []
        token_rows: list[dict[str, Any]] = []
        structure_rows: list[dict[str, Any]] = []
        shared_rows: list[dict[str, Any]] = []
        gap_rows: list[dict[str, Any]] = []
        readiness_rows: list[dict[str, Any]] = []
        graph_nodes: dict[str, dict[str, Any]] = {}
        graph_edges: list[dict[str, Any]] = []
        payload_fingerprints: dict[str, list[dict[str, Any]]] = defaultdict(list)
        g1m_parse_counts: Counter[str] = Counter()
        material_diff_counts: Counter[str] = Counter()

        for container_row in sorted(containers, key=lambda item: (item["content_id"], item["parent_role"])):
            content_id = container_row["content_id"]
            parent_role = container_row["parent_role"]
            candidate_kind = selected_by_content[content_id]["candidate_kind"]
            source_archive = parsed_containers[(content_id, parent_role)]
            target_archive = target_containers[(content_id, parent_role)]
            source_members = member_map(source_archive)
            target_members = member_map(target_archive)
            expected = binding_index[(content_id, container_row["normalized_path"])]
            for binding in sorted(expected, key=lambda row: row["member_key"].casefold()):
                key = binding["member_key"]
                expected_source = bool(binding.get("source_sha256"))
                expected_target = bool(binding.get("target_sha256"))
                source_member = source_members.get(key)
                target_member = target_members.get(key)

                if expected_source and source_member is None:
                    raise BoundedFamilyError(f"source nested member disappeared: {content_id} / {key}")
                if not expected_source and source_member is not None:
                    raise BoundedFamilyError(f"source nested member unexpectedly appeared: {content_id} / {key}")
                if expected_target and target_member is None:
                    raise BoundedFamilyError(f"target nested member disappeared: {content_id} / {key}")
                if not expected_target and target_member is not None:
                    raise BoundedFamilyError(f"target nested member unexpectedly appeared: {content_id} / {key}")

                source_payload = None if source_member is None else source_member["payload"]
                target_payload = None if target_member is None else target_member["payload"]
                if source_payload is not None and sha256_bytes(source_payload) != binding["source_sha256"]:
                    raise BoundedFamilyError(f"source nested SHA mismatch: {content_id} / {key}")
                if target_payload is not None and sha256_bytes(target_payload) != binding["target_sha256"]:
                    raise BoundedFamilyError(f"target nested SHA mismatch: {content_id} / {key}")

                suffix = Path(binding["member_name"]).suffix.casefold()
                source_tokens = safe_tokens(source_payload or b"")
                target_tokens = safe_tokens(target_payload or b"")
                source_g1m: dict[str, Any] | None = None
                target_g1m: dict[str, Any] | None = None
                source_parse = "source_missing_expected_target_only" if source_payload is None else "not_g1m"
                target_parse = "target_missing_expected_source_only" if target_payload is None else "not_g1m"
                if suffix == ".g1m":
                    if source_payload is not None:
                        source_g1m, source_parse = parse_g1m(source_payload, f"source:{content_id}:{binding['member_name']}")
                        g1m_parse_counts[source_parse] += 1
                    if target_payload is not None:
                        target_g1m, target_parse = parse_g1m(target_payload, f"target:{content_id}:{binding['member_name']}")
                        g1m_parse_counts[target_parse] += 1
                    for side, parsed in (("source", source_g1m), ("target", target_g1m)):
                        if parsed is None:
                            continue
                        for param in parsed["parameters"]:
                            parameter_rows.append({
                                "content_id": content_id,
                                "candidate_kind": candidate_kind,
                                "parent_role": parent_role,
                                "member_name": binding["member_name"],
                                "side": side,
                                "parameter_key": param["parameter_key"],
                                "parameter_name": param["parameter_name"],
                                "shader_block_index": param["shader_block_index"],
                                "parameter_occurrence": param["parameter_occurrence"],
                                "buffer_type": param["buffer_type"],
                                "buffer_count": param["buffer_count"],
                                "value_text": param["value_text"],
                                "value_hex_sha256": sha256_bytes(bytes.fromhex(param["value_hex"])),
                                "keyword_hits": param["keyword_hits"],
                                "raw_payload_exported": False,
                            })
                    if source_g1m is not None and target_g1m is not None:
                        differences, counts = BR.compare_g1m_material_parameters(source_g1m, target_g1m)
                        material_diff_counts.update(counts)
                        for diff in differences:
                            diff_rows.append({
                                "content_id": content_id,
                                "candidate_kind": candidate_kind,
                                "parent_role": parent_role,
                                "member_name": binding["member_name"],
                                **diff,
                                "raw_payload_exported": False,
                            })
                member_rows.append({
                    "content_id": content_id,
                    "candidate_kind": candidate_kind,
                    "parent_role": parent_role,
                    "parent_path": container_row["normalized_path"],
                    "member_key": key,
                    "member_name": binding["member_name"],
                    "nested_role": binding["nested_role"],
                    "source_size": "" if source_payload is None else len(source_payload),
                    "source_sha256": "" if source_payload is None else sha256_bytes(source_payload),
                    "target_size": "" if target_payload is None else len(target_payload),
                    "target_sha256": "" if target_payload is None else sha256_bytes(target_payload),
                    "compatibility_status": binding["compatibility_status"],
                    "source_parse_status": source_parse,
                    "target_parse_status": target_parse,
                    "source_parameter_count": 0 if source_g1m is None else len(source_g1m["parameters"]),
                    "target_parameter_count": "" if target_g1m is None else len(target_g1m["parameters"]),
                    "source_technical_token_count": len(source_tokens),
                    "target_technical_token_count": len(target_tokens),
                    "raw_payload_exported": False,
                })
                for side, tokens in (("source", source_tokens), ("target", target_tokens)):
                    if side == "source" and source_payload is None:
                        continue
                    if side == "target" and target_payload is None:
                        continue
                    for token in tokens:
                        token_rows.append({
                            "content_id": content_id,
                            "candidate_kind": candidate_kind,
                            "parent_role": parent_role,
                            "member_name": binding["member_name"],
                            "side": side,
                            "technical_token": token,
                            "token_kind": "external_texture_reference" if token.casefold().endswith(".g1t") else "technical_identifier",
                            "token_sha256": sha256_bytes(token.encode("ascii", errors="ignore")),
                            "raw_payload_exported": False,
                        })
                if suffix in {".swg", ".bin"}:
                    source_signature = None if source_payload is None else structural_signature(source_payload)
                    target_signature = None if target_payload is None else structural_signature(target_payload)
                    if source_signature is None:
                        structural_compatibility = "source_missing_target_only"
                    else:
                        structural_compatibility = compare_structural(source_signature, target_signature)
                    structure_rows.append({
                        "content_id": content_id,
                        "candidate_kind": candidate_kind,
                        "parent_role": parent_role,
                        "member_name": binding["member_name"],
                        "member_kind": "cloth_structure_candidate" if suffix == ".swg" else "auxiliary_object_descriptor",
                        "source_size": "" if source_signature is None else source_signature["size"],
                        "source_sha256": "" if source_signature is None else source_signature["sha256"],
                        "source_aligned_u32_words": "" if source_signature is None else source_signature["aligned_u32_words"],
                        "source_zero_u32_words": "" if source_signature is None else source_signature["zero_u32_words"],
                        "source_unique_u32_words": "" if source_signature is None else source_signature["unique_u32_words"],
                        "source_finite_float_words": "" if source_signature is None else source_signature["finite_float_words"],
                        "source_byte_entropy": "" if source_signature is None else source_signature["byte_entropy"],
                        "source_technical_token_count": "" if source_signature is None else source_signature["technical_token_count"],
                        "source_token_set_sha256": "" if source_signature is None else source_signature["technical_token_set_sha256"],
                        "target_size": "" if target_signature is None else target_signature["size"],
                        "target_sha256": "" if target_signature is None else target_signature["sha256"],
                        "target_aligned_u32_words": "" if target_signature is None else target_signature["aligned_u32_words"],
                        "target_zero_u32_words": "" if target_signature is None else target_signature["zero_u32_words"],
                        "target_unique_u32_words": "" if target_signature is None else target_signature["unique_u32_words"],
                        "target_finite_float_words": "" if target_signature is None else target_signature["finite_float_words"],
                        "target_byte_entropy": "" if target_signature is None else target_signature["byte_entropy"],
                        "target_technical_token_count": "" if target_signature is None else target_signature["technical_token_count"],
                        "target_token_set_sha256": "" if target_signature is None else target_signature["technical_token_set_sha256"],
                        "structural_compatibility": structural_compatibility,
                        "semantics_status": "format_and_structure_metadata_only_physics_semantics_unproven",
                        "raw_payload_exported": False,
                    })
                if source_payload is not None:
                    payload_fingerprints[sha256_bytes(source_payload)].append({
                        "content_id": content_id,
                        "candidate_kind": candidate_kind,
                        "parent_role": parent_role,
                        "member_name": binding["member_name"],
                        "side": "source",
                        "size": len(source_payload),
                    })
                if target_payload is not None:
                    payload_fingerprints[sha256_bytes(target_payload)].append({
                        "content_id": content_id,
                        "candidate_kind": candidate_kind,
                        "parent_role": parent_role,
                        "member_name": binding["member_name"],
                        "side": "target",
                        "size": len(target_payload),
                    })

        for digest, occurrences in sorted(payload_fingerprints.items()):
            if len(occurrences) < 2:
                continue
            owners = {row["content_id"] for row in occurrences}
            sides = {row["side"] for row in occurrences}
            if len(owners) < 2 and sides == {"source"}:
                continue
            shared_rows.append({
                "payload_sha256": digest,
                "payload_size": occurrences[0]["size"],
                "occurrence_count": len(occurrences),
                "content_ids": sorted(owners),
                "candidate_kinds": sorted({row["candidate_kind"] for row in occurrences}),
                "members": [f"{row['content_id']}:{row['parent_role']}:{row['side']}:{row['member_name']}" for row in occurrences],
                "binding_status": "exact_payload_identity_shared_dependency_or_control_match",
                "profile_build_allowed": False,
            })

        for content_id, candidate in sorted(selected_by_content.items()):
            rows = [row for row in member_rows if row["content_id"] == content_id]
            source_rows = [row for row in rows if row["source_sha256"]]
            g1m_rows = [row for row in source_rows if row["member_name"].casefold().endswith(".g1m")]
            swg_rows = [row for row in source_rows if row["member_name"].casefold().endswith(".swg")]
            unresolved: list[tuple[str, str]] = []
            if not g1m_rows or any(not str(row["source_parse_status"]).startswith("parsed") for row in g1m_rows):
                unresolved.append(("g1m_material_parse", "obtain a stable parser or classify unsupported G1M layout"))
            if not swg_rows:
                unresolved.append(("cloth_structure_member", "locate the owner-specific SWG or alternate physics member"))
            unresolved.extend([
                ("material_texture_slot_semantics", "map parsed material parameters and technical tokens to exact external G1T slots"),
                ("cloth_physics_semantics", "decode SWG/Oid field meaning or validate against a known-working Quartet control"),
                ("ui_icon_or_thumbnail", "prove owner-specific UI atlas/index binding"),
                ("unlock_or_entitlement_semantics", "prove owner-specific availability chain without synthesizing platform entitlement"),
                ("runtime_compatibility", "perform later local runtime validation through transactional core"),
            ])
            for dependency, needed in unresolved:
                gap_rows.append({
                    "content_id": content_id,
                    "candidate_kind": candidate["candidate_kind"],
                    "dependency_type": dependency,
                    "status": "unresolved",
                    "next_evidence_needed": needed,
                    "profile_build_allowed": False,
                })
            parsed_g1m_count = sum(row["source_parse_status"] == "parsed" for row in g1m_rows)
            target_g1m_count = sum(bool(row["target_sha256"]) for row in g1m_rows)
            target_parsed_g1m_count = sum(row["target_parse_status"] == "parsed" for row in g1m_rows)
            readiness_rows.append({
                "content_id": content_id,
                "candidate_kind": candidate["candidate_kind"],
                "source_member_count": len(source_rows),
                "source_g1m_count": len(g1m_rows),
                "source_g1m_parsed_count": parsed_g1m_count,
                "target_g1m_count": target_g1m_count,
                "target_g1m_parsed_count": target_parsed_g1m_count,
                "cloth_structure_member_count": len(swg_rows),
                "technical_reference_token_count": sum(row["source_technical_token_count"] for row in rows),
                "unresolved_dependency_count": len(unresolved),
                "profile_readiness": "bounded_material_and_structure_inventory_complete_semantics_ui_unlock_and_runtime_pending" if parsed_g1m_count == len(g1m_rows) and swg_rows else "blocked_bounded_payload_parse_or_member_gap",
                "profile_build_allowed": False,
                "default_enabled": False,
                "runtime_validated": False,
            })
            graph_nodes[content_id] = {"id": content_id, "type": "bounded_family", "candidate_kind": candidate["candidate_kind"]}

        for row in member_rows:
            node_id = f"member:{row['content_id']}:{row['parent_role']}:{row['member_key']}"
            graph_nodes[node_id] = {"id": node_id, "type": "nested_member", "name": row["member_name"], "compatibility": row["compatibility_status"]}
            graph_edges.append({"source": row["content_id"], "target": node_id, "relation": "contains"})
        for row in token_rows:
            token_id = "token:" + row["token_sha256"][:20]
            graph_nodes[token_id] = {"id": token_id, "type": "technical_reference", "token": row["technical_token"], "token_kind": row["token_kind"]}
            source_node = next((node_id for node_id, node in graph_nodes.items() if node.get("type") == "nested_member" and node.get("name") == row["member_name"] and node_id.startswith(f"member:{row['content_id']}:")), None)
            if source_node:
                graph_edges.append({"source": source_node, "target": token_id, "relation": "references_or_contains_identifier"})

        write_tsv(report_root / "DLC_BOUNDED_FAMILY_MEMBER_AUDIT.tsv", [
            "content_id", "candidate_kind", "parent_role", "parent_path", "member_key", "member_name", "nested_role",
            "source_size", "source_sha256", "target_size", "target_sha256", "compatibility_status",
            "source_parse_status", "target_parse_status", "source_parameter_count", "target_parameter_count",
            "source_technical_token_count", "target_technical_token_count", "raw_payload_exported",
        ], member_rows)
        write_tsv(report_root / "DLC_BOUNDED_G1M_MATERIAL_PARAMETERS.tsv", [
            "content_id", "candidate_kind", "parent_role", "member_name", "side", "parameter_key", "parameter_name",
            "shader_block_index", "parameter_occurrence", "buffer_type", "buffer_count", "value_text",
            "value_hex_sha256", "keyword_hits", "raw_payload_exported",
        ], parameter_rows)
        write_tsv(report_root / "DLC_BOUNDED_G1M_MATERIAL_DIFFS.tsv", [
            "content_id", "candidate_kind", "parent_role", "member_name", "parameter_key", "parameter_name",
            "shader_block_index", "parameter_occurrence", "source_buffer_type", "target_buffer_type",
            "source_buffer_count", "target_buffer_count", "source_value_text", "target_value_text",
            "source_value_hex", "target_value_hex", "classification", "keyword_hits", "review_status", "raw_payload_exported",
        ], diff_rows)
        write_tsv(report_root / "DLC_BOUNDED_TECHNICAL_REFERENCE_TOKENS.tsv", [
            "content_id", "candidate_kind", "parent_role", "member_name", "side", "technical_token",
            "token_kind", "token_sha256", "raw_payload_exported",
        ], token_rows)
        write_tsv(report_root / "DLC_BOUNDED_CLOTH_STRUCTURE_AUDIT.tsv", [
            "content_id", "candidate_kind", "parent_role", "member_name", "member_kind",
            "source_size", "source_sha256", "source_aligned_u32_words", "source_zero_u32_words",
            "source_unique_u32_words", "source_finite_float_words", "source_byte_entropy",
            "source_technical_token_count", "source_token_set_sha256", "target_size", "target_sha256",
            "target_aligned_u32_words", "target_zero_u32_words", "target_unique_u32_words",
            "target_finite_float_words", "target_byte_entropy", "target_technical_token_count",
            "target_token_set_sha256", "structural_compatibility", "semantics_status", "raw_payload_exported",
        ], structure_rows)
        write_tsv(report_root / "DLC_BOUNDED_SHARED_MEMBER_BINDINGS.tsv", [
            "payload_sha256", "payload_size", "occurrence_count", "content_ids", "candidate_kinds", "members",
            "binding_status", "profile_build_allowed",
        ], shared_rows)
        write_tsv(report_root / "DLC_BOUNDED_FAMILY_GAPS.tsv", [
            "content_id", "candidate_kind", "dependency_type", "status", "next_evidence_needed", "profile_build_allowed",
        ], gap_rows)
        write_tsv(report_root / "DLC_BOUNDED_PROFILE_READINESS.tsv", [
            "content_id", "candidate_kind", "source_member_count", "source_g1m_count", "source_g1m_parsed_count",
            "target_g1m_count", "target_g1m_parsed_count", "cloth_structure_member_count",
            "technical_reference_token_count", "unresolved_dependency_count", "profile_readiness",
            "profile_build_allowed", "default_enabled", "runtime_validated",
        ], readiness_rows)
        write_json(report_root / "DLC_BOUNDED_FAMILY_GRAPH.json", {
            "type": "br_quartet_legacy_dlc_bounded_family_graph",
            "format_version": FORMAT_VERSION,
            "tool_version": TOOL_VERSION,
            "nodes": sorted(graph_nodes.values(), key=lambda row: row["id"]),
            "edges": sorted(graph_edges, key=lambda row: (row["source"], row["target"], row["relation"])),
            "raw_assets_embedded": False,
        })

        summary = {
            "type": "br_quartet_legacy_dlc_bounded_family_summary",
            "format_version": FORMAT_VERSION,
            "tool_version": TOOL_VERSION,
            "status": "bounded_material_and_cloth_structure_audit_complete_metadata_only",
            "selected_families": [
                {"content_id": row["content_id"], "candidate_kind": row["candidate_kind"]}
                for row in sorted(selected, key=lambda item: item["candidate_kind"])
            ],
            "parent_container_count": len(containers),
            "member_audit_rows": len(member_rows),
            "nested_compatibility_status_counts": dict(sorted(Counter(row["compatibility_status"] for row in member_rows).items())),
            "target_only_member_rows": sum(row["compatibility_status"] == "target_only_nested_member" for row in member_rows),
            "g1m_member_count": sum(row["member_name"].casefold().endswith(".g1m") for row in member_rows),
            "g1m_parse_status_counts": dict(sorted(g1m_parse_counts.items())),
            "material_parameter_rows": len(parameter_rows),
            "material_difference_rows": len(diff_rows),
            "material_difference_counts": dict(sorted(material_diff_counts.items())),
            "technical_reference_token_rows": len(token_rows),
            "cloth_structure_rows": len(structure_rows),
            "shared_exact_payload_rows": len(shared_rows),
            "unresolved_dependency_rows": len(gap_rows),
            "profile_readiness_counts": dict(sorted(Counter(row["profile_readiness"] for row in readiness_rows).items())),
            "selective_pak_reader": {
                "source_archives_opened": len(source_paks),
                "target_archives_opened": len(target_paks),
                "source_formats": sorted({index.format_name for index in source_paks.values()}),
                "target_formats": sorted({index.format_name for index in target_paks.values()}),
                "target_master_keys": sorted({index.master_key_label for index in target_paks.values()}),
                "full_pak_extraction": False,
            },
            "policy": {
                "text_seed_unchanged": True,
                "translation_text_source": "titles/blue_reflection/translation",
                "separate_translation_database": False,
                "selected_game_installations_read_only": True,
                "raw_assets_exported": False,
                "game_modified": False,
                "profiles_built": False,
                "profiles_activated": False,
                "git_modified": False,
                "br1_fallback_asset_allowed": True,
            },
            "limitations": [
                "G1M parsing is limited to stable chunk metadata and named G1MG shader parameters",
                "technical strings are reference candidates and do not by themselves prove texture-slot semantics",
                "SWG and Oid payloads are structurally fingerprinted but field semantics remain unproven",
                "owner-specific UI indices and unlock/entitlement chains remain unresolved",
                "no profile can be built before exact dependency closure and later runtime validation",
            ],
            "next_action": "use the positive control to map recurring material/cloth structures, then prove exact texture slots and owner-specific availability for the BR1-only candidate",
        }
        write_json(report_root / "SUMMARY.json", summary)
        write_json(report_root / "REPORT_MANIFEST.json", {"files": manifest_rows(report_root)})
        validate_report(report_root)
        output = reports_root / REPORT_ARCHIVE_NAME
        make_archive(report_root, output)
        return output, summary


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    audit_p = sub.add_parser("audit")
    audit_p.add_argument("--project-root", required=True)
    audit_p.add_argument("--original-root", required=True)
    audit_p.add_argument("--quartet-root", required=True)
    def run_audit(args: argparse.Namespace) -> int:
        project_root = Path(args.project_root).expanduser().resolve()
        report_root = project_root / ".local/reports/quartet_legacy_dlc" / REPORT_DIR_NAME
        output, summary = audit(
            project_root,
            Path(args.original_root).expanduser().resolve(),
            Path(args.quartet_root).expanduser().resolve(),
            report_root,
        )
        print(f"Selected families: {len(summary['selected_families'])}")
        print(f"G1M members: {summary['g1m_member_count']}")
        print(f"Metadata-only report: {output}")
        print("Installed games were not modified.")
        return 0
    audit_p.set_defaults(func=run_audit)
    validate_p = sub.add_parser("validate-report")
    validate_p.add_argument("--report-root", required=True)
    validate_p.set_defaults(func=lambda args: (validate_report(Path(args.report_root).expanduser().resolve()), print(f"Validated bounded-family report: {Path(args.report_root).resolve()}"), 0)[-1])
    bundle_p = sub.add_parser("bundle-report")
    bundle_p.add_argument("--report-root", required=True)
    bundle_p.add_argument("--output", required=True)
    def run_bundle(args: argparse.Namespace) -> int:
        root = Path(args.report_root).expanduser().resolve()
        validate_report(root)
        output = Path(args.output).expanduser().resolve()
        make_archive(root, output)
        print(output)
        return 0
    bundle_p.set_defaults(func=run_bundle)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        return int(args.func(args))
    except (BoundedFamilyError, NESTED.NestedContainerError, BR.RestorationError, OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
