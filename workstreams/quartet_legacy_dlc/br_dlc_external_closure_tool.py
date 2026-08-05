#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import shutil
import tarfile
import tempfile
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

TOOL_VERSION = "0.0.8"
FORMAT_VERSION = 1
REPORT_DIR_NAME = "external_dependency_closure_evidence"
REPORT_ARCHIVE_NAME = "BR_quartet_legacy_dlc_external_dependency_closure_evidence.tar.zst"
FORBIDDEN_SUFFIXES = {
    ".pak", ".ebm", ".ebd", ".g1m", ".g1t", ".g1s", ".g1e", ".g1em", ".g1a",
    ".bin", ".elixir", ".gz", ".dds", ".png", ".jpg", ".jpeg", ".ktx", ".wav", ".ogg",
}


class ExternalClosureError(RuntimeError):
    pass


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
        raise ExternalClosureError(f"missing prerequisite report file: {path}")
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


def clean_dir(path: Path) -> None:
    if path.exists():
        shutil.rmtree(path)
    path.mkdir(parents=True, exist_ok=True)


def split_list(value: str) -> list[str]:
    return [part.strip() for part in str(value or "").split(";") if part.strip()]


def truthy(value: str) -> bool:
    return str(value).strip().casefold() in {"1", "true", "yes"}


def locate_prerequisite(report_root: Path, directory: str, archive: str, temporary: Path) -> Path:
    direct = report_root / directory
    if direct.is_dir():
        return direct
    packed = report_root / archive
    if not packed.is_file():
        raise ExternalClosureError(f"missing prerequisite report directory/archive: {direct} / {packed}")
    extracted = temporary / directory
    extracted.mkdir(parents=True, exist_ok=True)
    try:
        import subprocess
        subprocess.run(["tar", "--zstd", "-xf", str(packed), "-C", str(temporary)], check=True)
    except Exception as exc:  # pragma: no cover - platform failure path
        raise ExternalClosureError(f"could not extract prerequisite report: {packed}: {exc}") from exc
    if extracted.is_dir():
        return extracted
    candidates = [item for item in temporary.iterdir() if item.is_dir()]
    if len(candidates) == 1:
        return candidates[0]
    raise ExternalClosureError(f"could not locate extracted prerequisite directory for {packed}")


def make_archive(source_dir: Path, output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="br_dlc_external_bundle_") as temp_name:
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
        suffixes = {suffix.casefold() for suffix in path.suffixes}
        if suffixes & FORBIDDEN_SUFFIXES:
            raise ExternalClosureError(f"forbidden asset-like file in report: {path}")
        rows.append({
            "path": path.relative_to(report_root).as_posix(),
            "size": path.stat().st_size,
            "sha256": sha256_file(path),
        })
    return rows


def index_binding_rows(rows: list[dict[str, str]]) -> dict[str, list[dict[str, str]]]:
    result: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in rows:
        path = row.get("normalized_path", "").replace("\\", "/").casefold()
        if path:
            result[path].append(row)
    return result


def resolve_member_binding(
    content_id: str,
    normalized_path: str,
    path_index: dict[str, list[dict[str, str]]],
) -> tuple[dict[str, str] | None, str]:
    matches = path_index.get(normalized_path.replace("\\", "/").casefold(), [])
    direct = [row for row in matches if row.get("content_id") == content_id]
    if len(direct) == 1:
        return direct[0], "direct_owner_and_path"
    if len(matches) == 1:
        return matches[0], "unique_path_reassigned_from_shared_registry"
    if not matches:
        return None, "no_member_binding"
    return None, "ambiguous_member_binding"


def required_external_roles(technical_types: set[str]) -> list[str]:
    if "accessory" in technical_types:
        return [
            "accessory_texture",
            "accessory_table_binding",
            "ui_icon_or_thumbnail",
            "unlock_or_availability_chain",
            "material_reference_semantics",
            "cloth_physics_semantics",
        ]
    return [
        "dry_texture",
        "wet_texture",
        "system_character_record",
        "ui_icon_or_thumbnail",
        "unlock_or_availability_chain",
        "material_reference_semantics",
        "cloth_physics_semantics",
    ]


def candidate_score(row: dict[str, Any], kind: str) -> int:
    source_nested = int(row.get("source_nested_member_count", 0))
    parent_count = int(row.get("parent_container_count", 0))
    target_missing = int(row.get("target_missing_parent_count", 0))
    modified = int(row.get("target_modified_dependency_count", 0))
    exact_tables = int(row.get("exact_system_record_count", 0))
    texture_count = int(row.get("external_texture_count", 0))
    score = 1000 - source_nested - parent_count * 10
    if kind == "positive_control":
        score += 500 if target_missing == 0 else -1000
        score += modified * 25
        score += texture_count * 5
    else:
        score += 500 if target_missing == parent_count and parent_count else -1000
        score += 100 if exact_tables else 0
        score += texture_count * 5
    return score


def validate_report(report_root: Path) -> dict[str, Any]:
    required = {
        "DLC_OWNER_EXTERNAL_DEPENDENCY_CLOSURE.tsv",
        "DLC_EXTERNAL_TEXTURE_BINDINGS.tsv",
        "DLC_SYSTEM_TABLE_OWNER_BINDINGS.tsv",
        "DLC_UI_UNLOCK_DEPENDENCY_MAP.tsv",
        "DLC_EXTERNAL_CLOSURE_GAPS.tsv",
        "DLC_EXTERNAL_CLOSURE_PROFILE_READINESS.tsv",
        "DLC_BOUNDED_FAMILY_CANDIDATES.tsv",
        "DLC_EXTERNAL_DEPENDENCY_GRAPH.json",
        "SUMMARY.json",
    }
    names = {path.name for path in report_root.iterdir() if path.is_file()}
    missing = sorted(required - names)
    if missing:
        raise ExternalClosureError("missing report files: " + ", ".join(missing))
    owner_rows = read_tsv(report_root / "DLC_OWNER_EXTERNAL_DEPENDENCY_CLOSURE.tsv")
    readiness = read_tsv(report_root / "DLC_EXTERNAL_CLOSURE_PROFILE_READINESS.tsv")
    candidates = read_tsv(report_root / "DLC_BOUNDED_FAMILY_CANDIDATES.tsv")
    if not owner_rows or len(owner_rows) != len(readiness):
        raise ExternalClosureError("owner/readiness rows are empty or inconsistent")
    if any(truthy(row.get("profile_build_allowed", "")) for row in readiness):
        raise ExternalClosureError("external closure report unexpectedly authorizes a profile build")
    selected = [row for row in candidates if truthy(row.get("selected_for_next_audit", ""))]
    selected_kinds = Counter(row.get("candidate_kind", "") for row in selected)
    if selected and (selected_kinds.get("positive_control", 0) > 1 or selected_kinds.get("portable_transfer_candidate", 0) > 1):
        raise ExternalClosureError("bounded family selection is not unique")
    summary = json.loads((report_root / "SUMMARY.json").read_text(encoding="utf-8"))
    if summary.get("policy", {}).get("profiles_built") is not False:
        raise ExternalClosureError("summary does not preserve no-build policy")
    manifest_rows(report_root)
    return summary


def audit(project_root: Path, report_root: Path | None = None, create_archive: bool = True) -> tuple[Path, dict[str, Any]]:
    reports_root = project_root / ".local/reports/quartet_legacy_dlc"
    report_root = report_root or reports_root / REPORT_DIR_NAME
    with tempfile.TemporaryDirectory(prefix="br_dlc_external_prereq_") as temp_name:
        temp = Path(temp_name)
        nested_root = locate_prerequisite(
            reports_root,
            "nested_container_evidence",
            "BR_quartet_legacy_dlc_nested_container_evidence.tar.zst",
            temp,
        )
        exact_root = locate_prerequisite(
            reports_root,
            "exact_closure_evidence",
            "BR_quartet_legacy_dlc_exact_closure_evidence.tar.zst",
            temp,
        )
        technical_root = locate_prerequisite(
            reports_root,
            "technical_registry_evidence",
            "BR_quartet_legacy_dlc_technical_registry_evidence.tar.zst",
            temp,
        )

        nested_summary = json.loads((nested_root / "SUMMARY.json").read_text(encoding="utf-8"))
        if nested_summary.get("status") != "canonical_parent_container_nested_inventory_complete_metadata_only":
            raise ExternalClosureError("nested prerequisite report is not complete")
        nested_inventory = read_tsv(nested_root / "DLC_NESTED_CONTAINER_INVENTORY.tsv")
        nested_readiness = read_tsv(nested_root / "DLC_NESTED_PROFILE_READINESS.tsv")
        canonical = read_tsv(exact_root / "DLC_CANONICAL_CONTENT_CLOSURE.tsv")
        exact_roles = read_tsv(exact_root / "DLC_EXACT_ROLE_CLOSURE.tsv")
        table_unlock = read_tsv(exact_root / "DLC_TABLE_AND_UNLOCK_CLOSURE.tsv")
        technical_bindings = read_tsv(technical_root / "DLC_TECHNICAL_MEMBER_BINDINGS.tsv")

        canonical_by_content = {row["content_id"]: row for row in canonical}
        nested_by_content: dict[str, list[dict[str, str]]] = defaultdict(list)
        for row in nested_inventory:
            nested_by_content[row["content_id"]].append(row)
        nested_ready_by_content = {row["content_id"]: row for row in nested_readiness}
        owner_ids = sorted(nested_ready_by_content, key=str.casefold)
        role_index: dict[tuple[str, str], dict[str, str]] = {}
        for row in exact_roles:
            role_index[(row.get("content_id", ""), row.get("role", ""))] = row
        table_index: dict[str, list[dict[str, str]]] = defaultdict(list)
        for row in table_unlock:
            table_index[row.get("content_id", "")].append(row)
        path_index = index_binding_rows(technical_bindings)

        clean_dir(report_root)
        owner_rows: list[dict[str, Any]] = []
        texture_rows: list[dict[str, Any]] = []
        system_rows: list[dict[str, Any]] = []
        ui_unlock_rows: list[dict[str, Any]] = []
        gap_rows: list[dict[str, Any]] = []
        readiness_rows: list[dict[str, Any]] = []
        candidate_rows: list[dict[str, Any]] = []
        graph_nodes: dict[str, dict[str, Any]] = {}
        graph_edges: list[dict[str, Any]] = []

        print(f"[stage16] cross-linking {len(owner_ids)} canonical costume/accessory owners", flush=True)
        for content_id in owner_ids:
            closure = canonical_by_content.get(content_id)
            if not closure:
                raise ExternalClosureError(f"nested owner is missing from canonical closure: {content_id}")
            technical_types = set(split_list(closure.get("technical_types", "")))
            owner_node = f"owner:{content_id}"
            graph_nodes[owner_node] = {"id": owner_node, "kind": "canonical_owner", "content_id": content_id}
            parent_rows = nested_by_content[content_id]
            nested_ready = nested_ready_by_content[content_id]
            source_nested_count = sum(int(row.get("source_nested_member_count") or 0) for row in parent_rows)
            target_nested_count = sum(int(row.get("target_nested_member_count") or 0) for row in parent_rows)
            target_missing_parents = sum(not bool(row.get("target_path")) for row in parent_rows)

            external_texture_count = 0
            external_texture_statuses: Counter[str] = Counter()
            exact_system_records = [
                row for row in table_index.get(content_id, [])
                if row.get("evidence_type") == "system_record" and truthy(row.get("exact_owner_match", ""))
            ]
            exact_unlock_rows = [
                row for row in table_index.get(content_id, [])
                if row.get("evidence_type") == "unlock_or_flag" and truthy(row.get("exact_owner_match", ""))
            ]
            system_semantics_proven = bool(exact_system_records) and all(truthy(row.get("semantics_proven", "")) for row in exact_system_records)
            unlock_semantics_proven = bool(exact_unlock_rows) and all(truthy(row.get("semantics_proven", "")) for row in exact_unlock_rows)

            for role in required_external_roles(technical_types):
                exact = role_index.get((content_id, role))
                if role in {"dry_texture", "wet_texture", "accessory_texture"}:
                    if not exact or exact.get("resolution_status") != "resolved":
                        gap_rows.append({
                            "gap_id": f"{closure['closure_id']}:{role}",
                            "closure_id": closure["closure_id"],
                            "content_id": content_id,
                            "dependency_role": role,
                            "status": "missing_exact_external_texture_binding",
                            "priority": "critical",
                            "next_evidence_needed": "locate an exact top-level G1T owner binding",
                            "profile_build_allowed": False,
                        })
                        continue
                    for path in split_list(exact.get("evidence", "")):
                        binding, basis = resolve_member_binding(content_id, path, path_index)
                        if not binding:
                            gap_rows.append({
                                "gap_id": f"{closure['closure_id']}:{role}:{hashlib.sha256(path.encode()).hexdigest()[:12]}",
                                "closure_id": closure["closure_id"],
                                "content_id": content_id,
                                "dependency_role": role,
                                "status": basis,
                                "priority": "critical",
                                "next_evidence_needed": "resolve the exact technical member binding",
                                "profile_build_allowed": False,
                            })
                            continue
                        external_texture_count += 1
                        status = binding.get("compatibility_status", "unknown_dependency")
                        external_texture_statuses[status] += 1
                        texture_id = "texture:" + hashlib.sha256(path.casefold().encode()).hexdigest()[:20]
                        graph_nodes[texture_id] = {
                            "id": texture_id,
                            "kind": "external_texture_member",
                            "path": path,
                            "compatibility_status": status,
                        }
                        graph_edges.append({"source": owner_node, "target": texture_id, "relation": role})
                        texture_rows.append({
                            "closure_id": closure["closure_id"],
                            "content_id": content_id,
                            "technical_types": closure["technical_types"],
                            "texture_role": role,
                            "normalized_path": path,
                            "binding_basis": basis,
                            "source_archive": binding.get("source_archive", ""),
                            "source_path": binding.get("source_path", ""),
                            "source_size": binding.get("source_size", ""),
                            "source_sha256": binding.get("source_sha256", ""),
                            "target_archive": binding.get("target_archive", ""),
                            "target_path": binding.get("target_path", ""),
                            "target_size": binding.get("target_size", ""),
                            "target_sha256": binding.get("target_sha256", ""),
                            "compatibility_status": status,
                            "fallback_from_br1_allowed": binding.get("fallback_from_br1_allowed", ""),
                            "raw_payload_exported": False,
                        })
                elif role in {"system_character_record", "accessory_table_binding"}:
                    role_rows = exact_system_records
                    status = (
                        "exact_records_present_semantics_proven" if system_semantics_proven
                        else "exact_records_present_semantics_unproven" if role_rows
                        else "missing_exact_system_record"
                    )
                    system_rows.append({
                        "closure_id": closure["closure_id"],
                        "content_id": content_id,
                        "technical_types": closure["technical_types"],
                        "table_role": role,
                        "record_count": len(role_rows),
                        "source_tables": sorted({row.get("source_table", "") for row in role_rows if row.get("source_table")}),
                        "record_keys": [row.get("record_key", "") for row in role_rows],
                        "target_status_counts": dict(sorted(Counter(row.get("target_status", "") for row in role_rows).items())),
                        "semantics_proven": system_semantics_proven,
                        "binding_status": status,
                        "raw_text_exported": False,
                    })
                    if status != "exact_records_present_semantics_proven":
                        gap_rows.append({
                            "gap_id": f"{closure['closure_id']}:{role}",
                            "closure_id": closure["closure_id"],
                            "content_id": content_id,
                            "dependency_role": role,
                            "status": status,
                            "priority": "high",
                            "next_evidence_needed": (
                                "prove the runtime role of exact system records" if role_rows
                                else "locate an exact owner-specific system-table record"
                            ),
                            "profile_build_allowed": False,
                        })
                    for table_row in role_rows:
                        node_id = "record:" + hashlib.sha256(
                            (table_row.get("source_table", "") + "\0" + table_row.get("record_key", "")).encode()
                        ).hexdigest()[:20]
                        graph_nodes[node_id] = {
                            "id": node_id,
                            "kind": "system_table_record",
                            "table": table_row.get("source_table", ""),
                            "record_key": table_row.get("record_key", ""),
                            "target_status": table_row.get("target_status", ""),
                            "semantics_proven": truthy(table_row.get("semantics_proven", "")),
                        }
                        graph_edges.append({"source": owner_node, "target": node_id, "relation": role})
                elif role == "ui_icon_or_thumbnail":
                    exact_status = exact.get("resolution_status", "missing") if exact else "missing"
                    ui_unlock_rows.append({
                        "closure_id": closure["closure_id"],
                        "content_id": content_id,
                        "dependency_role": role,
                        "exact_resolution_status": exact_status,
                        "evidence": exact.get("evidence", "") if exact else "",
                        "semantics_proven": False,
                        "dependency_status": "shared_atlas_or_table_index_unresolved",
                        "profile_build_allowed": False,
                    })
                    gap_rows.append({
                        "gap_id": f"{closure['closure_id']}:{role}",
                        "closure_id": closure["closure_id"],
                        "content_id": content_id,
                        "dependency_role": role,
                        "status": "shared_atlas_or_table_index_unresolved",
                        "priority": "high",
                        "next_evidence_needed": "resolve exact owner-specific icon/thumbnail index or member",
                        "profile_build_allowed": False,
                    })
                elif role == "unlock_or_availability_chain":
                    status = (
                        "exact_unlock_present_semantics_proven" if unlock_semantics_proven
                        else "exact_unlock_present_semantics_unproven" if exact_unlock_rows
                        else "missing_exact_unlock_or_entitlement_binding"
                    )
                    ui_unlock_rows.append({
                        "closure_id": closure["closure_id"],
                        "content_id": content_id,
                        "dependency_role": role,
                        "exact_resolution_status": exact.get("resolution_status", "missing") if exact else "missing",
                        "evidence": [
                            {
                                "source_table": row.get("source_table", ""),
                                "record_key": row.get("record_key", ""),
                                "field_name": row.get("field_name", ""),
                                "identifier": row.get("identifier", ""),
                                "target_status": row.get("target_status", ""),
                            }
                            for row in exact_unlock_rows
                        ],
                        "semantics_proven": unlock_semantics_proven,
                        "dependency_status": status,
                        "profile_build_allowed": False,
                    })
                    if status != "exact_unlock_present_semantics_proven":
                        gap_rows.append({
                            "gap_id": f"{closure['closure_id']}:{role}",
                            "closure_id": closure["closure_id"],
                            "content_id": content_id,
                            "dependency_role": role,
                            "status": status,
                            "priority": "critical",
                            "next_evidence_needed": (
                                "prove runtime/platform semantics of the exact activation field" if exact_unlock_rows
                                else "locate an exact owner-specific unlock, availability or entitlement chain"
                            ),
                            "profile_build_allowed": False,
                        })
                elif role in {"material_reference_semantics", "cloth_physics_semantics"}:
                    status = "pending_bounded_nested_payload_reference_audit"
                    gap_rows.append({
                        "gap_id": f"{closure['closure_id']}:{role}",
                        "closure_id": closure["closure_id"],
                        "content_id": content_id,
                        "dependency_role": role,
                        "status": status,
                        "priority": "high",
                        "next_evidence_needed": (
                            "parse exact G1M material/texture references for a bounded family"
                            if role == "material_reference_semantics"
                            else "identify cloth/physics ownership and semantics for a bounded family"
                        ),
                        "profile_build_allowed": False,
                    })

            modified_count = external_texture_statuses.get("present_modified", 0)
            unresolved_count = sum(1 for row in gap_rows if row["content_id"] == content_id)
            owner_status = (
                "external_textures_and_exact_system_records_crosslinked_semantics_pending"
                if exact_system_records
                else "external_textures_crosslinked_system_record_missing"
            )
            owner_row = {
                "closure_id": closure["closure_id"],
                "content_id": content_id,
                "technical_types": closure["technical_types"],
                "parent_container_count": len(parent_rows),
                "source_nested_member_count": source_nested_count,
                "target_nested_member_count": target_nested_count,
                "target_missing_parent_count": target_missing_parents,
                "external_texture_count": external_texture_count,
                "external_texture_status_counts": dict(sorted(external_texture_statuses.items())),
                "exact_system_record_count": len(exact_system_records),
                "exact_unlock_record_count": len(exact_unlock_rows),
                "ui_binding_status": "shared_atlas_or_table_index_unresolved",
                "system_semantics_proven": system_semantics_proven,
                "unlock_semantics_proven": unlock_semantics_proven,
                "material_reference_status": "pending_bounded_nested_payload_reference_audit",
                "cloth_physics_status": "pending_bounded_nested_payload_reference_audit",
                "unresolved_dependency_count": unresolved_count,
                "closure_status": owner_status,
                "raw_assets_exported": False,
            }
            owner_rows.append(owner_row)
            readiness_rows.append({
                "closure_id": closure["closure_id"],
                "content_id": content_id,
                "technical_types": closure["technical_types"],
                "external_texture_count": external_texture_count,
                "exact_system_record_count": len(exact_system_records),
                "exact_unlock_record_count": len(exact_unlock_rows),
                "unresolved_dependency_count": unresolved_count,
                "profile_readiness": "blocked_external_semantics_ui_unlock_and_runtime_closure",
                "profile_build_allowed": False,
                "default_enabled": False,
                "runtime_validated": False,
            })
            candidate_base = {
                **owner_row,
                "target_modified_dependency_count": modified_count,
            }
            if "costume_or_outfit" in technical_types:
                if target_missing_parents == 0:
                    kind = "positive_control"
                elif target_missing_parents == len(parent_rows):
                    kind = "portable_transfer_candidate"
                else:
                    kind = "mixed_target_presence_review"
                score = candidate_score(candidate_base, kind)
                candidate_rows.append({
                    "closure_id": closure["closure_id"],
                    "content_id": content_id,
                    "candidate_kind": kind,
                    "candidate_score": score,
                    "parent_container_count": len(parent_rows),
                    "source_nested_member_count": source_nested_count,
                    "target_missing_parent_count": target_missing_parents,
                    "external_texture_count": external_texture_count,
                    "target_modified_dependency_count": modified_count,
                    "exact_system_record_count": len(exact_system_records),
                    "unresolved_dependency_count": unresolved_count,
                    "selection_basis": "bounded family ranking only; no profile authorization",
                    "selected_for_next_audit": False,
                    "profile_build_allowed": False,
                })

        # Deterministically select one target-present positive control and one BR1-only transfer candidate.
        for kind in ("positive_control", "portable_transfer_candidate"):
            eligible = [row for row in candidate_rows if row["candidate_kind"] == kind and row["external_texture_count"] >= 2]
            if kind == "portable_transfer_candidate":
                exact_table_eligible = [row for row in eligible if row["exact_system_record_count"] > 0]
                if exact_table_eligible:
                    eligible = exact_table_eligible
            if eligible:
                selected = sorted(eligible, key=lambda row: (-int(row["candidate_score"]), row["content_id"].casefold()))[0]
                selected["selected_for_next_audit"] = True

        write_tsv(report_root / "DLC_OWNER_EXTERNAL_DEPENDENCY_CLOSURE.tsv", [
            "closure_id", "content_id", "technical_types", "parent_container_count", "source_nested_member_count",
            "target_nested_member_count", "target_missing_parent_count", "external_texture_count",
            "external_texture_status_counts", "exact_system_record_count", "exact_unlock_record_count",
            "ui_binding_status", "system_semantics_proven", "unlock_semantics_proven", "material_reference_status",
            "cloth_physics_status", "unresolved_dependency_count", "closure_status", "raw_assets_exported",
        ], owner_rows)
        write_tsv(report_root / "DLC_EXTERNAL_TEXTURE_BINDINGS.tsv", [
            "closure_id", "content_id", "technical_types", "texture_role", "normalized_path", "binding_basis",
            "source_archive", "source_path", "source_size", "source_sha256", "target_archive", "target_path",
            "target_size", "target_sha256", "compatibility_status", "fallback_from_br1_allowed", "raw_payload_exported",
        ], texture_rows)
        write_tsv(report_root / "DLC_SYSTEM_TABLE_OWNER_BINDINGS.tsv", [
            "closure_id", "content_id", "technical_types", "table_role", "record_count", "source_tables", "record_keys",
            "target_status_counts", "semantics_proven", "binding_status", "raw_text_exported",
        ], system_rows)
        write_tsv(report_root / "DLC_UI_UNLOCK_DEPENDENCY_MAP.tsv", [
            "closure_id", "content_id", "dependency_role", "exact_resolution_status", "evidence", "semantics_proven",
            "dependency_status", "profile_build_allowed",
        ], ui_unlock_rows)
        write_tsv(report_root / "DLC_EXTERNAL_CLOSURE_GAPS.tsv", [
            "gap_id", "closure_id", "content_id", "dependency_role", "status", "priority", "next_evidence_needed",
            "profile_build_allowed",
        ], gap_rows)
        write_tsv(report_root / "DLC_EXTERNAL_CLOSURE_PROFILE_READINESS.tsv", [
            "closure_id", "content_id", "technical_types", "external_texture_count", "exact_system_record_count",
            "exact_unlock_record_count", "unresolved_dependency_count", "profile_readiness", "profile_build_allowed",
            "default_enabled", "runtime_validated",
        ], readiness_rows)
        write_tsv(report_root / "DLC_BOUNDED_FAMILY_CANDIDATES.tsv", [
            "closure_id", "content_id", "candidate_kind", "candidate_score", "parent_container_count",
            "source_nested_member_count", "target_missing_parent_count", "external_texture_count",
            "target_modified_dependency_count", "exact_system_record_count", "unresolved_dependency_count",
            "selection_basis", "selected_for_next_audit", "profile_build_allowed",
        ], sorted(candidate_rows, key=lambda row: (row["candidate_kind"], -int(row["candidate_score"]), row["content_id"].casefold())))
        write_json(report_root / "DLC_EXTERNAL_DEPENDENCY_GRAPH.json", {
            "type": "br_quartet_legacy_dlc_external_dependency_graph",
            "format_version": FORMAT_VERSION,
            "tool_version": TOOL_VERSION,
            "nodes": sorted(graph_nodes.values(), key=lambda row: row["id"]),
            "edges": sorted(graph_edges, key=lambda row: (row["source"], row["target"], row["relation"])),
            "raw_assets_embedded": False,
        })

        selected_candidates = [row for row in candidate_rows if truthy(row.get("selected_for_next_audit", ""))]
        summary = {
            "type": "br_quartet_legacy_dlc_external_dependency_closure_summary",
            "format_version": FORMAT_VERSION,
            "tool_version": TOOL_VERSION,
            "status": "external_texture_table_ui_unlock_crosslink_complete_metadata_only",
            "canonical_owner_count": len(owner_rows),
            "external_texture_binding_count": len(texture_rows),
            "external_texture_compatibility_counts": dict(sorted(Counter(row["compatibility_status"] for row in texture_rows).items())),
            "system_table_owner_rows": len(system_rows),
            "exact_system_record_count": sum(int(row["record_count"]) for row in system_rows),
            "system_record_target_status_counts": dict(sorted(Counter(
                status
                for row in system_rows
                for status, count in json.loads(scalar(row["target_status_counts"])).items()
                for _ in range(int(count))
            ).items())),
            "ui_dependency_rows": sum(row["dependency_role"] == "ui_icon_or_thumbnail" for row in ui_unlock_rows),
            "unlock_dependency_rows": sum(row["dependency_role"] == "unlock_or_availability_chain" for row in ui_unlock_rows),
            "unresolved_dependency_rows": len(gap_rows),
            "profile_readiness_counts": dict(sorted(Counter(row["profile_readiness"] for row in readiness_rows).items())),
            "bounded_family_candidates": len(candidate_rows),
            "selected_bounded_families": [
                {"content_id": row["content_id"], "candidate_kind": row["candidate_kind"], "score": row["candidate_score"]}
                for row in sorted(selected_candidates, key=lambda row: row["candidate_kind"])
            ],
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
            },
            "limitations": [
                "exact G1T ownership is cross-linked by member identity but texture contents are not exported or interpreted",
                "system records are exact owner matches but runtime semantics remain unproven",
                "owner-specific UI atlas indices and unlock/entitlement chains remain unresolved",
                "nested G1M material references and cloth-physics semantics remain pending a bounded family audit",
                "all profile readiness remains fail-closed pending runtime validation",
            ],
            "next_action": "read-only material and cloth-physics reference audit for the selected target-present control and BR1-only portable costume family",
        }
        write_json(report_root / "SUMMARY.json", summary)
        write_json(report_root / "REPORT_MANIFEST.json", {
            "type": "br_quartet_legacy_dlc_external_dependency_closure_manifest",
            "format_version": FORMAT_VERSION,
            "tool_version": TOOL_VERSION,
            "files": manifest_rows(report_root),
            "raw_assets_embedded": False,
        })
        validate_report(report_root)
        output = reports_root / REPORT_ARCHIVE_NAME
        if create_archive:
            make_archive(report_root, output)
        return output, summary


def cmd_audit(args: argparse.Namespace) -> int:
    output, summary = audit(Path(args.project_root).resolve(), Path(args.report_root).resolve() if args.report_root else None, not args.no_archive)
    print(f"External closure owners: {summary['canonical_owner_count']}")
    print(f"External texture bindings: {summary['external_texture_binding_count']}")
    print(f"Unresolved dependencies: {summary['unresolved_dependency_rows']}")
    if not args.no_archive:
        print(f"Report: {output}")
    return 0


def cmd_validate(args: argparse.Namespace) -> int:
    summary = validate_report(Path(args.report_root).resolve())
    print(f"Validated external dependency closure report: {args.report_root}")
    print(f"Owners: {summary['canonical_owner_count']}")
    return 0


def cmd_bundle(args: argparse.Namespace) -> int:
    report_root = Path(args.report_root).resolve()
    validate_report(report_root)
    make_archive(report_root, Path(args.output).resolve())
    print(f"Built metadata-only report bundle: {args.output}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Cross-link Quartet legacy DLC external dependencies metadata-only")
    sub = parser.add_subparsers(dest="command", required=True)
    audit_parser = sub.add_parser("audit")
    audit_parser.add_argument("--project-root", required=True)
    audit_parser.add_argument("--report-root")
    audit_parser.add_argument("--no-archive", action="store_true")
    audit_parser.set_defaults(func=cmd_audit)
    validate_parser = sub.add_parser("validate-report")
    validate_parser.add_argument("--report-root", required=True)
    validate_parser.set_defaults(func=cmd_validate)
    bundle_parser = sub.add_parser("bundle-report")
    bundle_parser.add_argument("--report-root", required=True)
    bundle_parser.add_argument("--output", required=True)
    bundle_parser.set_defaults(func=cmd_bundle)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        return int(args.func(args))
    except ExternalClosureError as exc:
        print(f"ERROR: {exc}", file=__import__("sys").stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
