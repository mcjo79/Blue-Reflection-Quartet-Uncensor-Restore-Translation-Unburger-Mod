#!/usr/bin/env python3
"""Build a durable canonical BR1 source-resolution contract.

This stage consumes the validated official-source refresh report and reads only
canonical no-underscore BR1 sources.  It verifies the thirteen changed wet DLC
G1T members, resolves all thirty-nine superseded binding rows to their official
overlay rows, audits active operational code for trailing-underscore source
dependencies, and classifies matching local wet-DLC payloads without exporting
raw assets.

Historical provenance tools and reports may continue to describe preserved
underscore copies, but future operational consumers must use the canonical
registry and official binding overlays emitted here.  The underscore archives
are not inputs to this stage and may be removed after verification.
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
from collections import Counter
from pathlib import Path
from typing import Any, Iterable

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import br_dlc_nested_container_tool as NESTED
import br_dlc_br1_source_provenance_tool as PROV
import br_dlc_br1_official_source_refresh_tool as REFRESH

TOOL_VERSION = "0.0.29"
FORMAT_VERSION = 1
REPORT_DIR_NAME = "br1_canonical_source_contract_evidence"
REPORT_ARCHIVE_NAME = "BR_quartet_legacy_dlc_br1_canonical_source_contract_evidence.tar.zst"
FORBIDDEN_REPORT_SUFFIXES = PROV.FORBIDDEN_REPORT_SUFFIXES
OFFICIAL_ARCHIVE = "DATA/PACK00_02.PAK"
OFFICIAL_ARCHIVE_SHA1 = PROV.EXPECTED_PACK00_02_OFFICIAL_SHA1
UNDERSCORE_PATH_RE = re.compile(r"(?:DATA[\\/])?PACK00_(?:02|04_[123])\.PAK_", re.IGNORECASE)

BINDING_SPECS = (
    {
        "source_report": "technical_registry_evidence/DLC_TECHNICAL_MEMBER_BINDINGS.tsv",
        "overlay_report": "DLC_BR1_OFFICIAL_TECHNICAL_MEMBER_BINDINGS.tsv",
        "identity_field": "registry_id",
        "path_field": "normalized_path",
        "family": "technical_registry",
    },
    {
        "source_report": "nonscenario_inventory_evidence/DLC_NONSCRIPT_MEMBER_BINDINGS.tsv",
        "overlay_report": "DLC_BR1_OFFICIAL_NONSCRIPT_MEMBER_BINDINGS.tsv",
        "identity_field": "content_id",
        "path_field": "normalized_path",
        "family": "nonscenario_inventory",
    },
    {
        "source_report": "external_dependency_closure_evidence/DLC_EXTERNAL_TEXTURE_BINDINGS.tsv",
        "overlay_report": "DLC_BR1_OFFICIAL_EXTERNAL_TEXTURE_BINDINGS.tsv",
        "identity_field": "closure_id",
        "path_field": "normalized_path",
        "family": "external_texture_closure",
    },
)


class CanonicalSourceContractError(RuntimeError):
    pass


def bool_text(value: Any) -> Any:
    if isinstance(value, bool):
        return "true" if value else "false"
    if value is None:
        return ""
    if isinstance(value, (dict, list, tuple, set)):
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return value


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def write_tsv(path: Path, fields: Iterable[str], rows: Iterable[dict[str, Any]]) -> None:
    fieldnames = list(fields)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, delimiter="\t", lineterminator="\n", extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({field: bool_text(row.get(field, "")) for field in fieldnames})


def read_tsv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def hash_file(path: Path, algorithm: str = "sha256") -> str:
    digest = hashlib.new(algorithm)
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(16 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def make_archive(root: Path, output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(output.name + ".tmp")
    temporary.unlink(missing_ok=True)
    result = subprocess.run(
        ["tar", "--zstd", "-cf", str(temporary), "-C", str(root.parent), root.name],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    if result.returncode != 0:
        temporary.unlink(missing_ok=True)
        raise CanonicalSourceContractError(f"cannot create report archive: {result.stderr.strip()}")
    os.replace(temporary, output)


def report_manifest(root: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.name == "REPORT_MANIFEST.json":
            continue
        if {suffix.casefold() for suffix in path.suffixes} & FORBIDDEN_REPORT_SUFFIXES:
            raise CanonicalSourceContractError(f"raw asset-like file in report: {path}")
        rows.append({
            "path": path.relative_to(root).as_posix(),
            "size": path.stat().st_size,
            "sha256": hash_file(path),
        })
    return rows


def _verification_rows(refresh_root: Path) -> list[dict[str, str]]:
    rows = read_tsv(refresh_root / "DLC_BR1_OFFICIAL_CHANGED_MEMBER_VERIFICATION.tsv")
    if len(rows) != 13:
        raise CanonicalSourceContractError(f"expected 13 official verification rows, found {len(rows)}")
    expected = PROV.KNOWN_PACK00_02_DLC_CHANGED_BASENAMES
    actual = {Path(row["member_name"]).name.casefold() for row in rows}
    if actual != expected:
        raise CanonicalSourceContractError(
            f"official changed-member set mismatch: missing={sorted(expected-actual)} extra={sorted(actual-expected)}"
        )
    return sorted(rows, key=lambda row: row["member_name"].casefold())


def verify_canonical_archive(br1_root: Path, refresh_root: Path) -> tuple[list[dict[str, Any]], str]:
    archive = br1_root / OFFICIAL_ARCHIVE
    if not archive.is_file():
        raise CanonicalSourceContractError(f"canonical official archive missing: {archive}")
    archive_sha1 = hash_file(archive, "sha1")
    if archive_sha1 != OFFICIAL_ARCHIVE_SHA1:
        raise CanonicalSourceContractError(
            f"canonical PACK00_02 SHA-1 mismatch: expected {OFFICIAL_ARCHIVE_SHA1}, got {archive_sha1}"
        )
    index = NESTED.index_pak(archive)
    registry: list[dict[str, Any]] = []
    for row in _verification_rows(refresh_root):
        if row.get("official_archive") != OFFICIAL_ARCHIVE:
            raise CanonicalSourceContractError(f"noncanonical archive in refresh row: {row.get('member_name')}")
        if row.get("official_archive_designation") != "canonical_official_no_trailing_underscore":
            raise CanonicalSourceContractError(f"canonical source designation missing: {row.get('member_name')}")
        member = row["member_name"]
        payload, entry = NESTED.read_pak_member(index, member)
        digest = hashlib.sha256(payload).hexdigest()
        if digest != row["official_payload_sha256"]:
            raise CanonicalSourceContractError(f"official payload drift after stage 61: {member}")
        if entry.size != int(row["official_size"]) or entry.data_offset != int(row["official_data_offset"]):
            raise CanonicalSourceContractError(f"official layout drift after stage 61: {member}")
        if row.get("official_entry_index") and entry.index != int(row["official_entry_index"]):
            raise CanonicalSourceContractError(f"official entry index drift after stage 61: {member}")
        registry.append({
            "resolver_key": member.casefold(),
            "member_name": member,
            "content_basename": Path(member).name,
            "canonical_archive": OFFICIAL_ARCHIVE,
            "canonical_archive_sha1": archive_sha1,
            "canonical_entry_index": entry.index,
            "canonical_size": entry.size,
            "canonical_data_offset": entry.data_offset,
            "canonical_payload_sha256": digest,
            "superseded_modified_payload_sha256": row["modified_payload_sha256"],
            "source_precedence": "official_no_underscore_archive",
            "underscore_source_required": False,
            "raw_payload_exported": False,
        })
    return registry, archive_sha1


def _normalized_binding_path(value: str) -> str:
    return value.replace("\\", "/").lstrip("/").casefold()


def _binding_key(row: dict[str, str], spec: dict[str, str]) -> tuple[str, str]:
    identity = row.get(spec["identity_field"], "")
    member = _normalized_binding_path(row.get(spec["path_field"], ""))
    if not identity or not member:
        raise CanonicalSourceContractError(
            f"incomplete binding identity in {spec['source_report']}: {identity!r} {member!r}"
        )
    return identity, member


def build_overlay_resolution(reports_root: Path, refresh_root: Path) -> list[dict[str, Any]]:
    supersession = read_tsv(refresh_root / "DLC_BR1_OFFICIAL_BINDING_SUPERSESSION.tsv")
    if len(supersession) != 39:
        raise CanonicalSourceContractError(f"expected 39 supersession rows, found {len(supersession)}")
    supersession_index = {
        (
            row["source_report"],
            row["source_row_identity"],
            _normalized_binding_path(row["member_name"]),
        ): row
        for row in supersession
    }
    if len(supersession_index) != 39:
        raise CanonicalSourceContractError("duplicate official binding supersession composite identity")

    resolved: list[dict[str, Any]] = []
    for spec in BINDING_SPECS:
        source_path = reports_root / spec["source_report"]
        overlay_path = refresh_root / spec["overlay_report"]
        if not source_path.is_file() or not overlay_path.is_file():
            raise CanonicalSourceContractError(f"binding input missing for {spec['family']}")
        old_rows = read_tsv(source_path)
        overlay_rows = read_tsv(overlay_path)
        if len(overlay_rows) != 13:
            raise CanonicalSourceContractError(f"official overlay row count mismatch for {spec['family']}")

        old_by_key: dict[tuple[str, str], dict[str, str]] = {}
        for row in old_rows:
            key = _binding_key(row, spec)
            if key in old_by_key:
                raise CanonicalSourceContractError(
                    f"duplicate source composite identity in {spec['source_report']}: {key[0]} + {key[1]}"
                )
            old_by_key[key] = row

        overlay_seen: set[tuple[str, str]] = set()
        for overlay in overlay_rows:
            key = _binding_key(overlay, spec)
            if key in overlay_seen:
                raise CanonicalSourceContractError(
                    f"duplicate overlay composite identity in {spec['overlay_report']}: {key[0]} + {key[1]}"
                )
            overlay_seen.add(key)
            identity, normalized_member = key
            old = old_by_key.get(key)
            if old is None:
                raise CanonicalSourceContractError(
                    f"overlay composite identity missing from source report: {identity} + {normalized_member}"
                )
            sup = supersession_index.get((spec["source_report"], identity, normalized_member))
            if sup is None:
                raise CanonicalSourceContractError(
                    f"supersession row missing: {spec['family']}:{identity}:{normalized_member}"
                )
            member = overlay[spec["path_field"]]
            if _normalized_binding_path(old.get(spec["path_field"], "")) != normalized_member:
                raise CanonicalSourceContractError(f"source member identity mismatch: {identity}")
            if _normalized_binding_path(sup.get("member_name", "")) != normalized_member:
                raise CanonicalSourceContractError(f"overlay member identity mismatch: {identity}")
            if old.get("source_sha256") != sup.get("old_modified_source_sha256"):
                raise CanonicalSourceContractError(f"old hash mismatch in source binding: {identity}:{member}")
            if overlay.get("source_sha256") != sup.get("replacement_official_source_sha256"):
                raise CanonicalSourceContractError(f"official hash mismatch in overlay binding: {identity}:{member}")
            changed_fields = sorted(
                field for field in set(old) | set(overlay)
                if old.get(field, "") != overlay.get(field, "")
            )
            if changed_fields != ["source_sha256"]:
                raise CanonicalSourceContractError(
                    f"overlay changes fields other than source_sha256 for {identity}:{member}: {changed_fields}"
                )
            resolved.append({
                "binding_family": spec["family"],
                "source_report": spec["source_report"],
                "overlay_report": spec["overlay_report"],
                "row_identity": identity,
                "member_name": member,
                "composite_resolver_key": f"{identity}|{normalized_member}",
                "prior_modified_source_sha256": old["source_sha256"],
                "selected_official_source_sha256": overlay["source_sha256"],
                "selected_source_archive": overlay.get("source_archive", OFFICIAL_ARCHIVE),
                "selection_precedence": "official_overlay_over_prior_hash_row",
                "resolution_status": "official_overlay_selected",
            })
    if len(resolved) != 39:
        raise CanonicalSourceContractError(f"resolved overlay row count mismatch: {len(resolved)}")
    return sorted(resolved, key=lambda row: (row["binding_family"], row["member_name"].casefold()))

def _operational_files(workstream_root: Path) -> list[Path]:
    files: set[Path] = set()
    for path in workstream_root.glob("[0-9][0-9]_*.sh"):
        try:
            stage = int(path.name[:2])
        except ValueError:
            continue
        if stage >= 61:
            files.add(path)
    for name in (
        "br_dlc_br1_official_source_refresh_tool.py",
        "br_dlc_br1_canonical_source_tool.py",
    ):
        path = workstream_root / name
        if path.is_file():
            files.add(path)
    return sorted(files)


def audit_operational_underscore_dependencies(project_root: Path) -> list[dict[str, Any]]:
    workstream_root = project_root / "workstreams/quartet_legacy_dlc"
    rows: list[dict[str, Any]] = []
    for path in _operational_files(workstream_root):
        text = path.read_text(encoding="utf-8", errors="replace")
        for match in UNDERSCORE_PATH_RE.finditer(text):
            rows.append({
                "file": path.relative_to(project_root).as_posix(),
                "line": text.count("\n", 0, match.start()) + 1,
                "reference": match.group(0).replace("\\", "/"),
                "classification": "forbidden_active_operational_underscore_dependency",
                "required_action": "remove dependency and use canonical source contract",
            })
    if rows:
        details = ", ".join(f"{row['file']}:{row['line']}" for row in rows[:8])
        raise CanonicalSourceContractError(f"active operational underscore dependency found: {details}")
    return [{
        "file": "workstreams/quartet_legacy_dlc/stages_61_and_later",
        "line": "",
        "reference": "",
        "classification": "no_active_operational_underscore_dependency",
        "required_action": "historical stage-58 provenance files may remain but are not future inputs",
    }]


def scan_local_payload_provenance(project_root: Path, registry_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    build_root = project_root / ".local/build/quartet_legacy_dlc"
    by_basename = {row["content_basename"].casefold(): row for row in registry_rows}
    rows: list[dict[str, Any]] = []
    if build_root.is_dir():
        for path in sorted(build_root.rglob("*")):
            if not path.is_file() or path.is_symlink():
                continue
            registry = by_basename.get(path.name.casefold())
            if registry is None:
                continue
            digest = hash_file(path)
            if digest == registry["canonical_payload_sha256"]:
                classification = "matches_official_canonical_payload"
                selected_for_future_use = True
                action = "may_be_used_only_through_hash_gated_canonical_resolver"
            elif digest == registry["superseded_modified_payload_sha256"]:
                classification = "matches_untrusted_modified_candidate"
                selected_for_future_use = False
                action = "quarantine_for_research_only_or_delete; never select as canonical"
            else:
                classification = "unknown_local_payload"
                selected_for_future_use = False
                action = "do_not_use; investigate provenance before any future payload build"
            rows.append({
                "local_path": path.relative_to(project_root).as_posix(),
                "member_name": registry["member_name"],
                "local_size": path.stat().st_size,
                "local_sha256": digest,
                "classification": classification,
                "selected_for_future_use": selected_for_future_use,
                "required_action": action,
            })
    if not rows:
        rows.append({
            "local_path": "",
            "member_name": "",
            "local_size": "",
            "local_sha256": "",
            "classification": "no_matching_local_wet_dlc_payloads_found",
            "selected_for_future_use": False,
            "required_action": "future extraction must read canonical no-underscore archive through the registry",
        })
    return rows


def build_contract(
    project_root: Path,
    br1_root: Path,
    reports_root: Path,
    refresh_root: Path,
    output_root: Path,
) -> tuple[Path, dict[str, Any]]:
    project_root = project_root.resolve()
    br1_root = br1_root.resolve()
    reports_root = reports_root.resolve()
    refresh_root = refresh_root.resolve()
    output_root = output_root.resolve()

    refresh_summary = REFRESH.validate_report(refresh_root)
    if refresh_summary.get("policy", {}).get("official_binding_overlay_required_for_future_consumers") is not True:
        raise CanonicalSourceContractError("official source refresh does not require overlay consumption")
    if output_root.exists():
        shutil.rmtree(output_root)
    output_root.mkdir(parents=True)

    registry_rows, archive_sha1 = verify_canonical_archive(br1_root, refresh_root)
    overlay_rows = build_overlay_resolution(reports_root, refresh_root)
    dependency_rows = audit_operational_underscore_dependencies(project_root)
    local_rows = scan_local_payload_provenance(project_root, registry_rows)
    dry_rows = read_tsv(refresh_root / "DLC_BR1_DRY_BKN_TRANSACTION_VALIDITY.tsv")
    if len(dry_rows) != 3 or any(row.get("current_candidate_valid") != "true" for row in dry_rows):
        raise CanonicalSourceContractError("dry BKN continuity rows are incomplete")

    write_tsv(output_root / "DLC_BR1_CANONICAL_SOURCE_REGISTRY.tsv", registry_rows[0].keys(), registry_rows)
    write_tsv(output_root / "DLC_BR1_OFFICIAL_OVERLAY_RESOLUTION.tsv", overlay_rows[0].keys(), overlay_rows)
    write_tsv(output_root / "DLC_BR1_OPERATIONAL_SOURCE_DEPENDENCY_AUDIT.tsv", dependency_rows[0].keys(), dependency_rows)
    write_tsv(output_root / "DLC_BR1_LOCAL_WET_DLC_PAYLOAD_PROVENANCE.tsv", local_rows[0].keys(), local_rows)
    write_tsv(output_root / "DLC_BR1_DRY_BKN_CONTINUITY.tsv", dry_rows[0].keys(), dry_rows)

    local_counts = Counter(row["classification"] for row in local_rows)
    contract = {
        "type": "br_quartet_legacy_dlc_br1_canonical_source_consumer_contract",
        "format_version": FORMAT_VERSION,
        "tool_version": TOOL_VERSION,
        "resolver_id": "br1_official_source_overlay_v1",
        "canonical_archive": OFFICIAL_ARCHIVE,
        "canonical_archive_sha1": archive_sha1,
        "registry_report": "DLC_BR1_CANONICAL_SOURCE_REGISTRY.tsv",
        "overlay_resolution_report": "DLC_BR1_OFFICIAL_OVERLAY_RESOLUTION.tsv",
        "binding_precedence": [
            {
                "binding_family": spec["family"],
                "source_report": spec["source_report"],
                "overlay_report": spec["overlay_report"],
                "join_key": f"{spec["identity_field"]}+{spec["path_field"]}",
                "member_path_field": spec["path_field"],
                "selected_hash_field": "source_sha256",
            }
            for spec in BINDING_SPECS
        ],
        "rules": {
            "canonical_source_name_must_not_end_with_underscore": True,
            "underscore_archives_required": False,
            "underscore_archives_are_research_only": True,
            "official_overlay_replaces_prior_hash_row": True,
            "prior_path_size_offset_identity_metadata_may_be_retained": True,
            "old_modified_hash_may_be_selected": False,
            "local_payload_auto_selection_allowed": False,
            "future_payload_extraction_requires_registry_hash_gate": True,
        },
        "policy": {
            "game_modified": False,
            "source_archives_modified": False,
            "prior_reports_modified": False,
            "git_modified": False,
            "translation_modified": False,
            "restoration_modified": False,
            "profile_build_allowed": False,
            "candidate_installed": False,
            "runtime_validated": False,
            "raw_assets_exported_in_report": False,
            "underscore_inputs_read_by_stage": False,
            "underscore_files_required_after_stage": False,
            "dry_bkn_transaction_request_retained": True,
        },
    }
    write_json(output_root / "DLC_BR1_CANONICAL_SOURCE_CONSUMER_CONTRACT.json", contract)

    gaps: list[dict[str, Any]] = []
    unsafe_local = sum(
        count for classification, count in local_counts.items()
        if classification in {"matches_untrusted_modified_candidate", "unknown_local_payload"}
    )
    if unsafe_local:
        gaps.append({
            "gap_id": "local_untrusted_or_unknown_wet_dlc_payloads_present",
            "severity": "quarantine_required_before_future_wet_payload_use",
            "details": unsafe_local,
            "required_action": "follow DLC_BR1_LOCAL_WET_DLC_PAYLOAD_PROVENANCE.tsv; resolver must never select these files",
        })
    gaps.append({
        "gap_id": "older_tools_not_yet_migrated_to_canonical_resolver",
        "severity": "nonblocking_for_current_metadata",
        "details": "prior reports remain immutable and must be consumed with the stage-64 overlay contract",
        "required_action": "all new wet-DLC payload stages must load DLC_BR1_CANONICAL_SOURCE_CONSUMER_CONTRACT.json",
    })
    gaps.append({
        "gap_id": "no_profile_or_runtime_authorization",
        "severity": "blocking_installation",
        "details": "source provenance resolution does not prove runtime compatibility or unlock/UI behavior",
        "required_action": "keep profile build, install and runtime validation disabled",
    })
    write_tsv(output_root / "DLC_BR1_CANONICAL_SOURCE_GAPS.tsv", gaps[0].keys(), gaps)

    summary = {
        "type": "br_quartet_legacy_dlc_br1_canonical_source_contract_summary",
        "format_version": FORMAT_VERSION,
        "tool_version": TOOL_VERSION,
        "status": "canonical_official_source_registry_and_overlay_resolver_ready_underscore_inputs_not_required_dry_bkn_retained_no_game_writes",
        "canonical_registry_members": len(registry_rows),
        "official_overlay_rows_resolved": len(overlay_rows),
        "binding_families_resolved": len(BINDING_SPECS),
        "active_operational_underscore_dependencies": 0,
        "local_payload_classifications": dict(sorted(local_counts.items())),
        "dry_bkn_continuity_rows": len(dry_rows),
        "dry_bkn_transaction_contract_still_valid": True,
        "underscore_files_required_for_future_workflow": False,
        "findings": [
            "all thirteen changed wet DLC G1T members resolve to the canonical no-underscore PACK00_02 with verified official hashes",
            "all thirty-nine prior hash-bearing binding rows resolve deterministically to the three official overlay families",
            "active stages 61 and later contain no operational dependency on trailing-underscore archive paths",
            "historical underscore copies are no longer required by this workstream after provenance verification",
            "the dry PC00 BKN candidates and two-archive transaction contract remain valid and unchanged",
        ],
        "next_action": "future wet-DLC consumers must use the canonical source contract and official overlay; underscore archives may be removed after any separate workstream provenance checks; dry-BKN real prepare/commit remains disabled pending explicit core integration",
        "policy": contract["policy"] | {
            "canonical_source_contract_ready": True,
            "official_overlay_consumer_required": True,
            "underscore_files_may_be_removed_after_workstream_verification": True,
        },
    }
    write_json(output_root / "SUMMARY.json", summary)
    write_json(output_root / "REPORT_MANIFEST.json", {
        "type": "br_report_manifest",
        "format_version": 1,
        "files": report_manifest(output_root),
    })
    archive = project_root / ".local/reports/quartet_legacy_dlc" / REPORT_ARCHIVE_NAME
    make_archive(output_root, archive)
    print(f"[stage64] canonical registry members: {len(registry_rows)}", flush=True)
    print(f"[stage64] official overlay rows resolved: {len(overlay_rows)}", flush=True)
    print("[stage64] operational underscore dependencies: 0", flush=True)
    print(f"[stage64] report: {archive}", flush=True)
    return archive, summary


def validate_report(report_root: Path) -> dict[str, Any]:
    report_root = report_root.resolve()
    required = (
        "DLC_BR1_CANONICAL_SOURCE_REGISTRY.tsv",
        "DLC_BR1_OFFICIAL_OVERLAY_RESOLUTION.tsv",
        "DLC_BR1_OPERATIONAL_SOURCE_DEPENDENCY_AUDIT.tsv",
        "DLC_BR1_LOCAL_WET_DLC_PAYLOAD_PROVENANCE.tsv",
        "DLC_BR1_DRY_BKN_CONTINUITY.tsv",
        "DLC_BR1_CANONICAL_SOURCE_CONSUMER_CONTRACT.json",
        "DLC_BR1_CANONICAL_SOURCE_GAPS.tsv",
        "SUMMARY.json",
        "REPORT_MANIFEST.json",
    )
    for name in required:
        if not (report_root / name).is_file():
            raise CanonicalSourceContractError(f"missing report file: {name}")
    summary = json.loads((report_root / "SUMMARY.json").read_text(encoding="utf-8"))
    if summary.get("type") != "br_quartet_legacy_dlc_br1_canonical_source_contract_summary":
        raise CanonicalSourceContractError("invalid canonical source summary type")
    if summary.get("tool_version") != TOOL_VERSION:
        raise CanonicalSourceContractError("canonical source tool version mismatch")
    if summary.get("status") != "canonical_official_source_registry_and_overlay_resolver_ready_underscore_inputs_not_required_dry_bkn_retained_no_game_writes":
        raise CanonicalSourceContractError("unexpected canonical source summary status")
    if summary.get("canonical_registry_members") != 13 or summary.get("official_overlay_rows_resolved") != 39:
        raise CanonicalSourceContractError("canonical source counts incomplete")
    if summary.get("binding_families_resolved") != 3 or summary.get("active_operational_underscore_dependencies") != 0:
        raise CanonicalSourceContractError("canonical overlay families or dependency audit invalid")
    if summary.get("underscore_files_required_for_future_workflow") is not False:
        raise CanonicalSourceContractError("underscore inputs remain required")

    registry = read_tsv(report_root / "DLC_BR1_CANONICAL_SOURCE_REGISTRY.tsv")
    if len(registry) != 13:
        raise CanonicalSourceContractError("canonical source registry row count mismatch")
    if any(row.get("canonical_archive") != OFFICIAL_ARCHIVE or row.get("underscore_source_required") != "false" for row in registry):
        raise CanonicalSourceContractError("noncanonical source selected in registry")
    if any(row.get("canonical_archive_sha1") != OFFICIAL_ARCHIVE_SHA1 for row in registry):
        raise CanonicalSourceContractError("canonical archive SHA-1 mismatch in registry")

    overlay = read_tsv(report_root / "DLC_BR1_OFFICIAL_OVERLAY_RESOLUTION.tsv")
    if len(overlay) != 39 or any(row.get("resolution_status") != "official_overlay_selected" for row in overlay):
        raise CanonicalSourceContractError("official overlay resolution incomplete")
    if Counter(row["binding_family"] for row in overlay) != Counter({
        "technical_registry": 13,
        "nonscenario_inventory": 13,
        "external_texture_closure": 13,
    }):
        raise CanonicalSourceContractError("official overlay family counts invalid")

    deps = read_tsv(report_root / "DLC_BR1_OPERATIONAL_SOURCE_DEPENDENCY_AUDIT.tsv")
    if len(deps) != 1 or deps[0].get("classification") != "no_active_operational_underscore_dependency":
        raise CanonicalSourceContractError("operational underscore dependency remains")
    dry = read_tsv(report_root / "DLC_BR1_DRY_BKN_CONTINUITY.tsv")
    if len(dry) != 3 or any(row.get("current_candidate_valid") != "true" for row in dry):
        raise CanonicalSourceContractError("dry BKN continuity invalid")

    contract = json.loads((report_root / "DLC_BR1_CANONICAL_SOURCE_CONSUMER_CONTRACT.json").read_text(encoding="utf-8"))
    if contract.get("type") != "br_quartet_legacy_dlc_br1_canonical_source_consumer_contract":
        raise CanonicalSourceContractError("invalid canonical source contract")
    rules = contract.get("rules", {})
    if rules.get("underscore_archives_required") is not False or rules.get("old_modified_hash_may_be_selected") is not False:
        raise CanonicalSourceContractError("canonical source contract permits untrusted source selection")
    if rules.get("official_overlay_replaces_prior_hash_row") is not True or rules.get("future_payload_extraction_requires_registry_hash_gate") is not True:
        raise CanonicalSourceContractError("canonical source contract lacks resolver requirements")

    policy = summary.get("policy", {})
    false_keys = (
        "game_modified", "source_archives_modified", "prior_reports_modified", "git_modified",
        "translation_modified", "restoration_modified", "profile_build_allowed", "candidate_installed",
        "runtime_validated", "raw_assets_exported_in_report", "underscore_inputs_read_by_stage",
        "underscore_files_required_after_stage",
    )
    if any(policy.get(key) is not False for key in false_keys):
        raise CanonicalSourceContractError("canonical source report violates fail-closed policy")
    true_keys = (
        "dry_bkn_transaction_request_retained", "canonical_source_contract_ready",
        "official_overlay_consumer_required", "underscore_files_may_be_removed_after_workstream_verification",
    )
    if any(policy.get(key) is not True for key in true_keys):
        raise CanonicalSourceContractError("canonical source policy flags missing")

    manifest = json.loads((report_root / "REPORT_MANIFEST.json").read_text(encoding="utf-8"))
    for row in manifest.get("files", []):
        path = report_root / row["path"]
        if not path.is_file() or path.stat().st_size != row["size"] or hash_file(path) != row["sha256"]:
            raise CanonicalSourceContractError(f"report manifest mismatch: {row.get('path')}")
        if {suffix.casefold() for suffix in path.suffixes} & FORBIDDEN_REPORT_SUFFIXES:
            raise CanonicalSourceContractError(f"raw asset in report: {path}")
    return summary


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    build = sub.add_parser("build-contract")
    build.add_argument("--project-root", type=Path, required=True)
    build.add_argument("--br1-root", type=Path, required=True)
    build.add_argument("--reports-root", type=Path)
    build.add_argument("--refresh-root", type=Path)
    build.add_argument("--output-root", type=Path)
    validate = sub.add_parser("validate-report")
    validate.add_argument("--report-root", type=Path, required=True)
    bundle = sub.add_parser("bundle-report")
    bundle.add_argument("--report-root", type=Path, required=True)
    bundle.add_argument("--output", type=Path, required=True)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        if args.command == "build-contract":
            project = args.project_root.resolve()
            reports = (args.reports_root or project / ".local/reports/quartet_legacy_dlc").resolve()
            refresh = (args.refresh_root or reports / REFRESH.REPORT_DIR_NAME).resolve()
            output = (args.output_root or reports / REPORT_DIR_NAME).resolve()
            build_contract(project, args.br1_root, reports, refresh, output)
        elif args.command == "validate-report":
            print(json.dumps(validate_report(args.report_root), ensure_ascii=False, sort_keys=True))
        elif args.command == "bundle-report":
            validate_report(args.report_root)
            make_archive(args.report_root.resolve(), args.output.resolve())
        else:
            raise CanonicalSourceContractError("unsupported command")
    except (
        CanonicalSourceContractError,
        REFRESH.OfficialSourceRefreshError,
        PROV.Br1SourceProvenanceError,
        NESTED.NestedContainerError,
        OSError,
        subprocess.TimeoutExpired,
    ) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
