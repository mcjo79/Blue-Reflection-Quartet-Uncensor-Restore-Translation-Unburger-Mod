#!/usr/bin/env python3
"""Stage 142: build local no-install KPS target-dword prototypes.

Consumes the verified stage-141 metadata plan. It rehydrates the exact source and
Quartet KPS members, verifies every target dword precondition, applies only the
planned Original words to temporary Quartet copies, restamps each modified DXBC
checksum, reparses every program, and proves that interface metadata, opcode
sequence, instruction lengths, program layout and all unplanned bytes remain
unchanged. Prototype KPS files are written only under .local/build; the evidence
archive contains metadata only and authorizes no installation or runtime
promotion.
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
import tempfile
from collections import Counter, defaultdict
from pathlib import Path, PurePosixPath
from typing import Any, Callable, Iterable, Mapping, Sequence

TOOL_VERSION = "0.1.60"
REPORT_DIR = "effect_posteffect_kps_local_no_install_prototype_evidence"
REPORT_NAME = "BR_quartet_restoration_effect_posteffect_kps_local_no_install_prototype_evidence.tar.zst"
STAGE141_NAME = "BR_quartet_restoration_effect_posteffect_kps_target_dword_prototype_plan_evidence.tar.zst"
STAGE141_SHA256 = "4f5ad8c8f5d420d9d98b24a8aafa0ff367ba9e05c618498630bee6c46b624b6a"
STAGE141_DIR = "effect_posteffect_kps_target_dword_prototype_plan_evidence"
STAGE141_SUMMARY_SHA256 = "139a1797c3d55e7049ccada2026697815f540447ccb3f9e2f6eee3111a143f1f"
PROTOTYPE_DIR = "kps_target_dword_prototypes_0.1.60"
EXPECTED_PROGRAMS = 15
EXPECTED_MEMBERS = 2
EXPECTED_EDITS = 227
EXPECTED_CHANGED_INSTRUCTIONS = 58
EXPECTED_EXCLUDED = 28
FORBIDDEN_REPORT_EXTENSIONS = (
    ".pak", ".g1e", ".g1em", ".g1m", ".g1s", ".g1t", ".kps", ".dxbc",
    ".elixir", ".elixir.gz", ".ebd", ".ebm",
)


class CollectorError(RuntimeError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise CollectorError(message)


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def safe_relative(value: str, label: str) -> str:
    path = PurePosixPath(str(value).replace("\\", "/"))
    require(bool(path.parts) and not path.is_absolute() and ".." not in path.parts, f"unsafe {label}: {value}")
    return path.as_posix()


def parse_bool(value: object) -> bool:
    return str(value).strip().casefold() in {"1", "true", "yes", "y"}


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
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def load_module(path: Path, name: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    require(spec is not None and spec.loader is not None, f"cannot load module: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def extract_report(archive: Path, destination: Path) -> Path:
    listed = subprocess.run(["tar", "--zstd", "-tf", str(archive)], text=True, capture_output=True)
    require(listed.returncode == 0, listed.stderr.strip() or "cannot list stage-141 report")
    names = [safe_relative(line, "report member") for line in listed.stdout.splitlines() if line.strip()]
    require(names and {PurePosixPath(name).parts[0] for name in names} == {STAGE141_DIR}, "unexpected stage-141 report root")
    destination.mkdir(parents=True, exist_ok=True)
    completed = subprocess.run(["tar", "--zstd", "-xf", str(archive), "-C", str(destination)], text=True, capture_output=True)
    require(completed.returncode == 0, completed.stderr.strip() or "cannot extract stage-141 report")
    root = destination / STAGE141_DIR
    require(root.is_dir(), f"missing extracted report root: {root}")
    return root


def make_archive(source: Path, output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(output.name + ".tmp")
    temporary.unlink(missing_ok=True)
    completed = subprocess.run(["tar", "--zstd", "-cf", str(temporary), "-C", str(source.parent), source.name], text=True, capture_output=True)
    require(completed.returncode == 0, completed.stderr.strip() or "archive creation failed")
    os.replace(temporary, output)


def chunk_location(payload: bytes, program: Mapping[str, Any], comparison_key: str) -> tuple[int, int, str]:
    offset = int(program["offset"])
    total_size = int(program["size"])
    require(offset >= 0 and offset + total_size <= len(payload), "invalid DXBC program bounds")
    chunk_count = struct.unpack_from("<I", payload, offset + 28)[0]
    require(offset + 32 + chunk_count * 4 <= offset + total_size, "invalid DXBC chunk table")
    rel_offsets = struct.unpack_from(f"<{chunk_count}I", payload, offset + 32) if chunk_count else ()
    occurrences: Counter[str] = Counter()
    for relative in rel_offsets:
        start = offset + int(relative)
        require(start + 8 <= offset + total_size, "DXBC chunk header out of range")
        fourcc = payload[start:start + 4].decode("ascii", errors="replace")
        size = struct.unpack_from("<I", payload, start + 4)[0]
        end = start + 8 + size
        require(end <= offset + total_size, "DXBC chunk payload out of range")
        key = f"{fourcc}#{occurrences[fourcc]}"
        occurrences[fourcc] += 1
        if key == comparison_key:
            return start + 8, size, fourcc
    raise CollectorError(f"missing DXBC chunk: {comparison_key}")


def instruction_rows(br: Any, payload: bytes, program: Mapping[str, Any], chunk_key: str) -> tuple[int, int, list[dict[str, Any]]]:
    chunk_start, chunk_size, fourcc = chunk_location(payload, program, chunk_key)
    require(fourcc in {"SHDR", "SHEX"}, f"planned chunk is not executable: {chunk_key}")
    parsed = br.parse_dxbc_instruction_stream(payload[chunk_start:chunk_start + chunk_size])
    require(parsed.get("status") == "ok", f"DXBC instruction parser status is not ok: {parsed.get('status')}")
    return chunk_start, chunk_size, [dict(row) for row in parsed.get("instructions", [])]


def interface_fingerprint(br: Any, payload: bytes, program: Mapping[str, Any]) -> dict[str, Any]:
    chunks = {row["comparison_key"]: row for row in br.parse_dxbc_chunk_payloads(payload, dict(program))}
    rdef = br.parse_dxbc_rdef(chunks["RDEF#0"]["payload"]) if "RDEF#0" in chunks else {
        "reflection_semantic_sha256": "", "resource_semantic_sha256": "", "cbuffer_semantic_sha256": "",
    }
    input_signature = ""
    output_signature = ""
    for key, row in chunks.items():
        if key.startswith(("ISGN#", "ISG1#")):
            input_signature = br.parse_dxbc_signature(row["payload"], row["fourcc"]).get("semantic_sha256", "")
        elif key.startswith(("OSGN#", "OSG5#", "OSG1#")):
            output_signature = br.parse_dxbc_signature(row["payload"], row["fourcc"]).get("semantic_sha256", "")
    code_rows: list[tuple[str, list[int], list[int], str, int]] = []
    for key, row in sorted(chunks.items()):
        if row["fourcc"] not in {"SHDR", "SHEX"}:
            continue
        parsed = br.parse_dxbc_instruction_stream(row["payload"])
        require(parsed.get("status") == "ok", f"cannot fingerprint instruction stream: {key}")
        instructions = [dict(item) for item in parsed.get("instructions", [])]
        code_rows.append((
            key,
            [int(item["opcode_id"]) for item in instructions],
            [int(item["length_dwords"]) for item in instructions],
            str(parsed.get("version_token", "")),
            int(parsed.get("declared_dwords", 0)),
        ))
    noncode = {
        key: row["sha256"] for key, row in chunks.items() if row["fourcc"] not in {"SHDR", "SHEX"}
    }
    return {
        "reflection": rdef.get("reflection_semantic_sha256", ""),
        "resources": rdef.get("resource_semantic_sha256", ""),
        "cbuffers": rdef.get("cbuffer_semantic_sha256", ""),
        "input_signature": input_signature,
        "output_signature": output_signature,
        "code_envelopes": code_rows,
        "noncode_chunks": noncode,
    }


def verify_dxbc_checksum(br: Any, blob: bytes) -> bool:
    return len(blob) >= 32 and blob[:4] == b"DXBC" and blob[4:20] == br.calculate_dxbc_checksum(blob)


def build_report(
    project_root: Path,
    *,
    report_root: Path | None = None,
    output_report_root: Path | None = None,
    workspace_root: Path | None = None,
    prototype_root: Path | None = None,
    original_root: Path | None = None,
    quartet_root: Path | None = None,
    gust_pak_path: Path | None = None,
    create_archive: bool = True,
    timeout_seconds: int = 1800,
    payload_provider: Callable[[str, str, str], bytes | None] | None = None,
) -> tuple[Path | None, dict[str, Any]]:
    project_root = project_root.resolve()
    version_path = project_root / "workstreams/quartet_restoration/VERSION"
    require(version_path.is_file(), f"missing VERSION: {version_path}")
    version = tuple(int(part) for part in version_path.read_text(encoding="utf-8").strip().split("."))
    require(version >= (0, 1, 60), f"stage 142 requires quartet_restoration 0.1.60 or newer, found {version_path.read_text().strip()}")

    report_root = (report_root or project_root / ".local/reports/quartet_restoration").resolve()
    output_report_root = (output_report_root or report_root).resolve()
    workspace_root = (workspace_root or project_root / ".local/build/quartet_restoration").resolve()
    prototype_root = (prototype_root or workspace_root / PROTOTYPE_DIR).resolve()
    output = output_report_root / REPORT_DIR
    archive_output = output_report_root / REPORT_NAME
    shutil.rmtree(output, ignore_errors=True)
    output.mkdir(parents=True, exist_ok=True)

    archive141 = report_root / STAGE141_NAME
    require(archive141.is_file(), f"missing prerequisite report: {archive141}")
    archive_hash = sha256_file(archive141)
    require(archive_hash == STAGE141_SHA256, f"unexpected stage-141 SHA-256: {archive_hash}")

    stage134 = load_module(project_root / "workstreams/quartet_restoration/134_collect_effect_posteffect_namespace_member_saturation_evidence.py", "stage142_stage134")
    stage133 = load_module(project_root / "workstreams/quartet_restoration/133_collect_shader_namespace_executable_signature_reflection_sweep_evidence.py", "stage142_stage133")
    br = stage134.load_br_tool(project_root)

    with tempfile.TemporaryDirectory(prefix="stage142-prereq-") as temporary_text:
        temporary = Path(temporary_text)
        root141 = report_root / STAGE141_DIR
        if not root141.is_dir():
            root141 = extract_report(archive141, temporary)
        summary_path = root141 / "SUMMARY.json"
        require(summary_path.is_file(), f"missing stage-141 summary: {summary_path}")
        summary_hash = sha256_file(summary_path)
        require(summary_hash == STAGE141_SUMMARY_SHA256, f"unexpected stage-141 summary SHA-256: {summary_hash}")
        summary141 = json.loads(summary_path.read_text(encoding="utf-8"))
        require(summary141.get("kps_admitted_program_rows") == EXPECTED_PROGRAMS, "stage-141 program count drift")
        require(summary141.get("kps_admitted_member_rows") == EXPECTED_MEMBERS, "stage-141 member count drift")
        require(summary141.get("kps_planned_target_dword_edit_rows") == EXPECTED_EDITS, "stage-141 edit count drift")
        require(summary141.get("kps_changed_instruction_rows") == EXPECTED_CHANGED_INSTRUCTIONS, "stage-141 instruction count drift")
        require(summary141.get("kps_edit_coordinate_conflict_rows") == 0, "stage-141 coordinate conflicts")
        require(summary141.get("prototype_artifact_rows") == 0, "stage-141 unexpectedly contains prototype artifacts")
        require(summary141.get("runtime_validated_profile_rows_preserved") == 1, "runtime profile count drift")
        require(summary141.get("runtime_failed_shader_rows_preserved") == 2, "runtime-failed shader count drift")
        require(summary141.get("skipped_rows") == 0, "stage-141 contains skipped rows")

        member_plan = read_tsv(root141 / "KPS_MEMBER_PROTOTYPE_PLAN.tsv")
        program_plan = read_tsv(root141 / "KPS_PROGRAM_TARGET_DWORD_PROTOTYPE_PLAN.tsv")
        edit_plan = read_tsv(root141 / "KPS_TARGET_DWORD_EDIT_PLAN.tsv")
        excluded = read_tsv(root141 / "KPS_EXCLUDED_PROGRAMS.tsv")
        g1e_carry = read_tsv(root141 / "G1E_UNRESOLVED_CALIBRATION_CARRY_FORWARD.tsv")
        unresolved = read_tsv(root141 / "UNRESOLVED_G1EM_G1T_SHADER_CARRY_FORWARD.tsv")
        require(len(member_plan) == EXPECTED_MEMBERS, "stage-141 member plan drift")
        require(len(program_plan) == EXPECTED_PROGRAMS, "stage-141 program plan drift")
        require(len(edit_plan) == EXPECTED_EDITS, "stage-141 edit plan drift")
        require(len(excluded) == EXPECTED_EXCLUDED, "stage-141 excluded program drift")
        require(all(parse_bool(row["precondition_required"]) for row in edit_plan), "an edit lacks a mandatory precondition")

        candidate_paths = sorted({row["normalized_path"].casefold() for row in member_plan})
        require(candidate_paths == ["data/x64/posteffect/pe_pack.elixir.gz"], "unexpected KPS container queue")

        extraction_rows: list[dict[str, Any]] = []
        payload_maps: dict[tuple[str, str], dict[str, dict[str, Any]]] = {}
        if payload_provider is None:
            candidates = [{"namespace": "posteffect", "normalized_path": candidate_paths[0]}]
            inventories = {side: stage134.load_inventory(project_root, side) for side in ("source", "target")}
            extraction_rows = stage134.ensure_extraction_cache(
                project_root=project_root,
                workspace_root=workspace_root,
                candidates=candidates,
                inventories=inventories,
                original_root=original_root,
                quartet_root=quartet_root,
                gust_pak_path=gust_pak_path,
                br=br,
                timeout_seconds=timeout_seconds,
            )
            normalized = candidate_paths[0]
            for side in ("source", "target"):
                entry = inventories[side].get(normalized)
                require(entry is not None, f"missing inventory entry: {side}:{normalized}")
                local = br.inventory_workspace_file(workspace_root, side, "br1_assets", str(entry["archive"]), str(entry["path"]))
                require(local.is_file(), f"missing cached input: {local}")
                actual_hash = sha256_file(local)
                require(actual_hash == str(entry["sha256"]), f"payload hash drift: {side}:{normalized}:{actual_hash}")
                require(local.stat().st_size == int(entry["size"]), f"payload size drift: {side}:{normalized}")
                parsed = br.read_earc_archive(local, maximum_bytes=stage134.MAX_EARC_BYTES, include_member_payloads=True)
                payload_maps[(side, normalized)] = {str(row["comparison_key"]): row for row in parsed["members"]}

        def get_payload(side: str, normalized: str, member_key: str) -> bytes:
            if payload_provider is not None:
                value = payload_provider(side, normalized, member_key)
                require(value is not None, f"payload provider returned no data: {side}:{normalized}:{member_key}")
                return bytes(value)
            row = payload_maps.get((side, normalized), {}).get(member_key)
            require(row is not None and "payload" in row, f"missing cached KPS member: {side}:{normalized}:{member_key}")
            return bytes(row["payload"])

        programs_by_member: dict[tuple[str, str], list[dict[str, str]]] = defaultdict(list)
        edits_by_program: dict[str, list[dict[str, str]]] = defaultdict(list)
        program_by_id = {row["program_plan_id"]: row for row in program_plan}
        for row in program_plan:
            programs_by_member[(row["normalized_path"].casefold(), row["member_key"])].append(row)
        for row in edit_plan:
            require(row["program_plan_id"] in program_by_id, f"edit references unknown program: {row['program_plan_id']}")
            edits_by_program[row["program_plan_id"]].append(row)

        staging = prototype_root.with_name(prototype_root.name + ".tmp")
        shutil.rmtree(staging, ignore_errors=True)
        staging.mkdir(parents=True, exist_ok=True)
        artifact_rows: list[dict[str, Any]] = []
        program_rows: list[dict[str, Any]] = []
        applied_rows: list[dict[str, Any]] = []
        skipped_rows: list[dict[str, Any]] = []

        try:
            for member_index, member_row in enumerate(sorted(member_plan, key=lambda row: row["member_name"].casefold()), start=1):
                normalized = member_row["normalized_path"].casefold()
                member_key = member_row["member_key"]
                member_name = member_row["member_name"]
                source = get_payload("source", normalized, member_key)
                target = get_payload("target", normalized, member_key)
                source_programs = br.find_dxbc_programs(source, label=f"source:{normalized}:{member_key}")
                target_programs = br.find_dxbc_programs(target, label=f"target:{normalized}:{member_key}")
                pairs = stage133.pair_programs(source_programs, target_programs)
                mutable = bytearray(target)
                allowed_byte_offsets: set[int] = set()
                checksum_offsets: set[int] = set()
                modified_target_indexes: set[int] = set()
                member_program_rows = sorted(programs_by_member[(normalized, member_key)], key=lambda row: int(row["program_pair_index"]))
                require(len(member_program_rows) == int(member_row["planned_program_rows"]), f"member program count drift: {member_name}")

                for plan in member_program_rows:
                    pair_index = int(plan["program_pair_index"])
                    require(0 <= pair_index < len(pairs), f"program pair out of range: {member_name}:{pair_index}")
                    target_program = pairs[pair_index].get("target")
                    require(target_program is not None, f"planned pair has no target program: {member_name}:{pair_index}")
                    target_program_index = int(target_program["program_index"])
                    program_id = plan["program_plan_id"]
                    edits = sorted(edits_by_program[program_id], key=lambda row: int(row["edit_ordinal"]))
                    require(len(edits) == int(plan["planned_edit_rows"]), f"program edit count drift: {program_id}")
                    chunk_key = plan["code_chunk_key"]
                    chunk_start, _chunk_size, instructions = instruction_rows(br, target, target_program, chunk_key)
                    for edit in edits:
                        instruction_index = int(edit["instruction_index"])
                        dword_index = int(edit["instruction_dword_index"])
                        require(0 <= instruction_index < len(instructions), f"instruction index out of range: {program_id}:{instruction_index}")
                        instruction = instructions[instruction_index]
                        require(0 <= dword_index < int(instruction["length_dwords"]), f"instruction dword index out of range: {program_id}:{instruction_index}:{dword_index}")
                        byte_offset = chunk_start + 4 * (int(instruction["dword_offset"]) + dword_index)
                        actual = struct.unpack_from("<I", mutable, byte_offset)[0]
                        expected = int(edit["expected_target_u32_hex"], 16)
                        proposed = int(edit["proposed_original_u32_hex"], 16)
                        require(actual == expected, f"target precondition failed: {edit['edit_plan_id']}: 0x{actual:08x} != 0x{expected:08x}")
                        require(proposed != expected, f"no-op planned edit: {edit['edit_plan_id']}")
                        struct.pack_into("<I", mutable, byte_offset, proposed)
                        allowed_byte_offsets.update(range(byte_offset, byte_offset + 4))
                        applied_rows.append({
                            **edit,
                            "actual_target_u32_hex": f"0x{actual:08x}",
                            "prototype_u32_hex": f"0x{proposed:08x}",
                            "absolute_member_byte_offset": byte_offset,
                            "precondition_verified": True,
                            "edit_applied": True,
                            "prototype_built": True,
                            "runtime_confirmed": False,
                            "write_authorized": False,
                        })
                    modified_target_indexes.add(target_program_index)

                for target_program_index in sorted(modified_target_indexes):
                    program = target_programs[target_program_index]
                    start = int(program["offset"]); end = start + int(program["size"])
                    stamped = br.stamp_dxbc_checksum(bytes(mutable[start:end]))
                    require(len(stamped) == end - start, "DXBC checksum stamping changed program size")
                    mutable[start:end] = stamped
                    checksum_offsets.update(range(start + 4, start + 20))

                prototype = bytes(mutable)
                require(len(prototype) == len(target), f"prototype size drift: {member_name}")
                prototype_programs = br.find_dxbc_programs(prototype, label=f"prototype:{normalized}:{member_key}")
                require(len(prototype_programs) == len(target_programs), f"DXBC program count drift: {member_name}")
                require([(p["offset"], p["size"]) for p in prototype_programs] == [(p["offset"], p["size"]) for p in target_programs], f"DXBC program layout drift: {member_name}")

                unexpected_diff_offsets = [index for index, (before, after) in enumerate(zip(target, prototype)) if before != after and index not in allowed_byte_offsets and index not in checksum_offsets]
                require(not unexpected_diff_offsets, f"unplanned KPS byte changes: {member_name}:{unexpected_diff_offsets[:8]}")

                for plan in member_program_rows:
                    pair_index = int(plan["program_pair_index"])
                    target_program = pairs[pair_index]["target"]
                    target_program_index = int(target_program["program_index"])
                    prototype_program = prototype_programs[target_program_index]
                    before_fingerprint = interface_fingerprint(br, target, target_program)
                    after_fingerprint = interface_fingerprint(br, prototype, prototype_program)
                    require(before_fingerprint == after_fingerprint, f"DXBC interface or instruction envelope drift: {plan['program_plan_id']}")
                    start = int(prototype_program["offset"]); end = start + int(prototype_program["size"])
                    checksum_valid = verify_dxbc_checksum(br, prototype[start:end])
                    require(checksum_valid, f"invalid prototype DXBC checksum: {plan['program_plan_id']}")
                    program_edits = [row for row in applied_rows if row["program_plan_id"] == plan["program_plan_id"]]
                    require(len(program_edits) == int(plan["planned_edit_rows"]), f"applied edit count drift: {plan['program_plan_id']}")
                    program_rows.append({
                        "program_plan_id": plan["program_plan_id"],
                        "normalized_path": normalized,
                        "member_key": member_key,
                        "member_name": member_name,
                        "program_pair_index": pair_index,
                        "target_program_index": target_program_index,
                        "program_offset": target_program["offset"],
                        "program_size": target_program["size"],
                        "planned_edit_rows": len(program_edits),
                        "target_preconditions_verified": True,
                        "all_planned_words_applied": True,
                        "dxbc_checksum_valid": checksum_valid,
                        "program_layout_preserved": True,
                        "noncode_interface_preserved": True,
                        "opcode_sequence_preserved": True,
                        "instruction_length_sequence_preserved": True,
                        "prototype_built": True,
                        "runtime_confirmed": False,
                        "write_authorized": False,
                    })

                safe_name = Path(member_name).name
                destination = staging / safe_name
                destination.write_bytes(prototype)
                artifact_rows.append({
                    "normalized_path": normalized,
                    "member_key": member_key,
                    "member_name": member_name,
                    "prototype_relative_path": f".local/build/quartet_restoration/{PROTOTYPE_DIR}/{safe_name}",
                    "target_size": len(target),
                    "prototype_size": len(prototype),
                    "target_sha256": sha256_bytes(target),
                    "prototype_sha256": sha256_bytes(prototype),
                    "planned_program_rows": len(member_program_rows),
                    "planned_edit_rows": sum(int(row["planned_edit_rows"]) for row in member_program_rows),
                    "changed_byte_rows_including_checksums": sum(a != b for a, b in zip(target, prototype)),
                    "all_target_preconditions_verified": True,
                    "all_programs_reparsed": True,
                    "all_dxbc_checksums_valid": True,
                    "all_unplanned_bytes_preserved": True,
                    "prototype_built": True,
                    "installed_game_modified": False,
                    "runtime_confirmed": False,
                    "write_authorized": False,
                })

            require(len(artifact_rows) == EXPECTED_MEMBERS, "prototype artifact count drift")
            require(len(program_rows) == EXPECTED_PROGRAMS, "prototype program count drift")
            require(len(applied_rows) == EXPECTED_EDITS, "applied edit count drift")
            require(sum(int(row["planned_program_rows"]) for row in artifact_rows) == EXPECTED_PROGRAMS, "prototype program total drift")
            require(sum(int(row["planned_edit_rows"]) for row in artifact_rows) == EXPECTED_EDITS, "prototype edit total drift")
            shutil.rmtree(prototype_root, ignore_errors=True)
            prototype_root.parent.mkdir(parents=True, exist_ok=True)
            os.replace(staging, prototype_root)
        except Exception:
            shutil.rmtree(staging, ignore_errors=True)
            raise

        write_tsv(output / "INPUT_HASHES.tsv", ["input_id", "relative_path", "sha256", "verified"], [{
            "input_id": "stage141_report",
            "relative_path": f".local/reports/quartet_restoration/{STAGE141_NAME}",
            "sha256": archive_hash,
            "verified": True,
        }, {
            "input_id": "stage141_summary",
            "relative_path": f"{STAGE141_DIR}/SUMMARY.json",
            "sha256": summary_hash,
            "verified": True,
        }])
        write_tsv(output / "EXTRACTION_INPUTS.tsv", ["side", "archive", "status"], extraction_rows)
        write_tsv(output / "KPS_LOCAL_PROTOTYPE_ARTIFACTS.tsv", list(artifact_rows[0]), artifact_rows)
        write_tsv(output / "KPS_PROGRAM_REPARSE_VERIFICATION.tsv", list(program_rows[0]), program_rows)
        write_tsv(output / "KPS_EDIT_APPLICATION.tsv", [
            "program_plan_id", "edit_plan_id", "edit_ordinal", "normalized_path", "member_key", "member_name",
            "program_pair_index", "code_chunk_key", "instruction_index", "instruction_dword_index", "word_role",
            "expected_target_u32_hex", "actual_target_u32_hex", "proposed_original_u32_hex", "prototype_u32_hex",
            "absolute_member_byte_offset", "precondition_required", "precondition_verified", "edit_applied",
            "prototype_built", "runtime_confirmed", "write_authorized",
        ], applied_rows)
        write_tsv(output / "KPS_EXCLUDED_PROGRAMS_CARRY_FORWARD.tsv", list(excluded[0]), excluded)
        write_tsv(output / "G1E_UNRESOLVED_CALIBRATION_CARRY_FORWARD.tsv", list(g1e_carry[0]), g1e_carry)
        write_tsv(output / "UNRESOLVED_G1EM_G1T_SHADER_CARRY_FORWARD.tsv", list(unresolved[0]), unresolved)
        write_tsv(output / "PARSER_SKIPPED.tsv", ["scope", "identity", "reason"], skipped_rows)

        summary = {
            "type": "br_quartet_restoration_effect_posteffect_kps_local_no_install_prototype_evidence_summary",
            "format_version": 1,
            "tool_version": TOOL_VERSION,
            "status": "kps_local_no_install_prototypes_built_all_preconditions_verified_dxbc_reparsed_no_pak_no_install_no_runtime_promotion",
            "stage141_report_sha256": archive_hash,
            "stage141_summary_sha256": summary_hash,
            "kps_prototype_artifact_rows": len(artifact_rows),
            "kps_prototype_program_rows": len(program_rows),
            "kps_applied_target_dword_edit_rows": len(applied_rows),
            "kps_target_precondition_rows_verified": sum(parse_bool(row["precondition_verified"]) for row in applied_rows),
            "kps_programs_reparsed_rows": sum(parse_bool(row["prototype_built"]) for row in program_rows),
            "kps_programs_with_valid_checksum_rows": sum(parse_bool(row["dxbc_checksum_valid"]) for row in program_rows),
            "kps_programs_interface_preserved_rows": sum(parse_bool(row["noncode_interface_preserved"]) for row in program_rows),
            "kps_programs_opcode_sequence_preserved_rows": sum(parse_bool(row["opcode_sequence_preserved"]) for row in program_rows),
            "kps_programs_instruction_length_sequence_preserved_rows": sum(parse_bool(row["instruction_length_sequence_preserved"]) for row in program_rows),
            "kps_members_all_unplanned_bytes_preserved_rows": sum(parse_bool(row["all_unplanned_bytes_preserved"]) for row in artifact_rows),
            "kps_excluded_program_rows_preserved": len(excluded),
            "g1e_unresolved_calibration_family_rows": len(g1e_carry),
            "unresolved_g1em_g1t_shader_rows": len(unresolved),
            "runtime_validated_profile_rows_preserved": 1,
            "runtime_validated_profile_id_preserved": summary141["runtime_validated_profile_id_preserved"],
            "runtime_failed_shader_rows_preserved": 2,
            "prototype_relative_root": f".local/build/quartet_restoration/{PROTOTYPE_DIR}",
            "prototype_artifacts_in_evidence_rows": 0,
            "pak_built_rows": 0,
            "installed_artifact_rows": 0,
            "new_runtime_confirmed_rows": 0,
            "write_authorized_rows": 0,
            "skipped_rows": len(skipped_rows),
            "policy": {
                "local_proprietary_payloads_read": payload_provider is None,
                "local_proprietary_prototypes_built_outside_report": True,
                "proprietary_payloads_in_report": False,
                "every_target_dword_precondition_verified": True,
                "only_planned_dwords_and_dxbc_checksums_changed": True,
                "target_kps_program_layout_preserved": True,
                "target_rdef_signatures_and_noncode_chunks_preserved": True,
                "opcode_sequence_and_instruction_lengths_preserved": True,
                "prototype_treated_as_patch_or_runtime_validation": False,
                "pak_built_or_repacked": False,
                "installed_game_modified": False,
                "profile_or_registry_modified": False,
                "core_modified": False,
                "translation_modified": False,
                "legacy_dlc_modified": False,
                "git_modified": False,
            },
            "next_action": (
                "Upload this metadata-only report. Keep both prototype KPS files local and uninstalled. "
                "Prepare a separate Fast Test Lab request that packages one reversible prototype at a time, first PostEffectGamma and then PostEffectGlowLight, with explicit rollback and no runtime promotion until each variant is tested in game."
            ),
        }
        atomic_json(output / "SUMMARY.json", summary)

        bad = [path for path in output.rglob("*") if path.is_file() and path.name.casefold().endswith(FORBIDDEN_REPORT_EXTENSIONS)]
        require(not bad, "proprietary payload extension in evidence report: " + ", ".join(str(path) for path in bad))
        archive = archive_output if create_archive else None
        if create_archive:
            make_archive(output, archive_output)
        return archive, summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path, required=True)
    parser.add_argument("--report-root", type=Path)
    parser.add_argument("--output-report-root", type=Path)
    parser.add_argument("--workspace-root", type=Path)
    parser.add_argument("--prototype-root", type=Path)
    parser.add_argument("--original-root", type=Path)
    parser.add_argument("--quartet-root", type=Path)
    parser.add_argument("--gust-pak", type=Path)
    parser.add_argument("--timeout-seconds", type=int, default=1800)
    args = parser.parse_args()
    archive, summary = build_report(
        args.project_root,
        report_root=args.report_root,
        output_report_root=args.output_report_root,
        workspace_root=args.workspace_root,
        prototype_root=args.prototype_root,
        original_root=args.original_root,
        quartet_root=args.quartet_root,
        gust_pak_path=args.gust_pak,
        timeout_seconds=args.timeout_seconds,
    )
    print(json.dumps(summary, indent=2, sort_keys=True))
    if archive is not None:
        print(f"[stage142] report archive: {archive}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
