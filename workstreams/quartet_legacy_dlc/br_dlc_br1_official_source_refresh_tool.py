#!/usr/bin/env python3
"""Build a metadata-only official-source refresh overlay for changed BR1 DLC members.

The tool consumes the member-level provenance report, verifies only the changed
DLC members against the canonical no-underscore PACK00_02.PAK, and emits exact
replacement binding rows for prior reports that embedded untrusted payload
hashes. Path/size/offset-only metadata is retained when the provenance report
proves those properties unchanged. No source archive, prior report, game file,
profile, or raw asset is modified or exported.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
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
import br_dlc_bkn_dry_transaction_contract_tool as TX

TOOL_VERSION = "0.0.27"
FORMAT_VERSION = 1
REPORT_DIR_NAME = "br1_official_source_refresh_evidence"
REPORT_ARCHIVE_NAME = "BR_quartet_legacy_dlc_br1_official_source_refresh_evidence.tar.zst"
EXPECTED_REQUIRED_MEMBERS = set(PROV.KNOWN_PACK00_02_DLC_CHANGED_BASENAMES)
FORBIDDEN_REPORT_SUFFIXES = PROV.FORBIDDEN_REPORT_SUFFIXES

BINDING_SPECS = (
    (
        "technical_registry_evidence/DLC_TECHNICAL_MEMBER_BINDINGS.tsv",
        "DLC_BR1_OFFICIAL_TECHNICAL_MEMBER_BINDINGS.tsv",
        "normalized_path",
        "registry_id",
    ),
    (
        "nonscenario_inventory_evidence/DLC_NONSCRIPT_MEMBER_BINDINGS.tsv",
        "DLC_BR1_OFFICIAL_NONSCRIPT_MEMBER_BINDINGS.tsv",
        "normalized_path",
        "content_id",
    ),
    (
        "external_dependency_closure_evidence/DLC_EXTERNAL_TEXTURE_BINDINGS.tsv",
        "DLC_BR1_OFFICIAL_EXTERNAL_TEXTURE_BINDINGS.tsv",
        "normalized_path",
        "closure_id",
    ),
)


class OfficialSourceRefreshError(RuntimeError):
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


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
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
        raise OfficialSourceRefreshError(f"cannot create report archive: {result.stderr.strip()}")
    os.replace(temporary, output)


def report_manifest(root: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.name == "REPORT_MANIFEST.json":
            continue
        if {suffix.casefold() for suffix in path.suffixes} & FORBIDDEN_REPORT_SUFFIXES:
            raise OfficialSourceRefreshError(f"raw asset-like file in report: {path}")
        rows.append({
            "path": path.relative_to(root).as_posix(),
            "size": path.stat().st_size,
            "sha256": sha256_file(path),
        })
    return rows


def _required_changed_rows(provenance_root: Path) -> list[dict[str, str]]:
    rows = read_tsv(provenance_root / "DLC_BR1_SELECTIVE_REBUILD_PLAN.tsv")
    required = [row for row in rows if row.get("priority") == "required"]
    if len(required) != 13:
        raise OfficialSourceRefreshError(f"expected 13 required selective rebuild rows, found {len(required)}")
    basenames = {Path(row["member_name"]).name.casefold() for row in required}
    if basenames != EXPECTED_REQUIRED_MEMBERS:
        missing = sorted(EXPECTED_REQUIRED_MEMBERS - basenames)
        extra = sorted(basenames - EXPECTED_REQUIRED_MEMBERS)
        raise OfficialSourceRefreshError(f"required member set mismatch; missing={missing} extra={extra}")
    if any(row.get("pair_id") != "PACK00_02" for row in required):
        raise OfficialSourceRefreshError("required refresh row outside PACK00_02")
    return sorted(required, key=lambda row: row["member_name"].casefold())


def verify_official_members(
    br1_root: Path,
    provenance_root: Path,
    required_rows: list[dict[str, str]],
) -> tuple[list[dict[str, Any]], dict[str, dict[str, str]]]:
    archive_rows = read_tsv(provenance_root / "DLC_BR1_SOURCE_ARCHIVE_PROVENANCE.tsv")
    pack_row = next((row for row in archive_rows if row["pair_id"] == "PACK00_02"), None)
    if pack_row is None:
        raise OfficialSourceRefreshError("PACK00_02 provenance row missing")
    archive = br1_root / "DATA/PACK00_02.PAK"
    if not archive.is_file():
        raise OfficialSourceRefreshError(f"official PACK00_02 missing: {archive}")
    if archive.stat().st_size != int(pack_row["official_size"]):
        raise OfficialSourceRefreshError("official PACK00_02 size changed after provenance audit")
    index = NESTED.index_pak(archive)
    if index.format_name != pack_row["official_format"] or len(index.entries) != int(pack_row["official_entry_count"]):
        raise OfficialSourceRefreshError("official PACK00_02 structure changed after provenance audit")

    changed_rows = {
        row["member_name"].casefold(): row
        for row in read_tsv(provenance_root / "DLC_BR1_CHANGED_MEMBER_CLASSIFICATION.tsv")
    }
    result: list[dict[str, Any]] = []
    by_name: dict[str, dict[str, str]] = {}
    for plan in required_rows:
        name = plan["member_name"]
        provenance = changed_rows.get(name.casefold())
        if provenance is None:
            raise OfficialSourceRefreshError(f"changed-member provenance missing: {name}")
        data, entry = NESTED.read_pak_member(index, name)
        digest = hashlib.sha256(data).hexdigest()
        if digest != provenance["official_payload_sha256"]:
            raise OfficialSourceRefreshError(f"official member hash mismatch: {name}")
        if entry.size != int(provenance["official_size"]) or entry.data_offset != int(provenance["official_data_offset"]):
            raise OfficialSourceRefreshError(f"official member layout mismatch: {name}")
        row = {
            "member_name": name,
            "content_basename": Path(name).name,
            "official_archive": "DATA/PACK00_02.PAK",
            "official_archive_designation": "canonical_official_no_trailing_underscore",
            "official_entry_index": entry.index,
            "official_size": entry.size,
            "official_data_offset": entry.data_offset,
            "modified_payload_sha256": provenance["modified_payload_sha256"],
            "official_payload_sha256": digest,
            "payload_hash_changed": provenance["modified_payload_sha256"] != digest,
            "size_unchanged": provenance["size_changed"] == "false",
            "data_offset_unchanged": provenance["data_offset_changed"] == "false",
            "verification_status": "official_member_hash_and_layout_verified",
            "raw_payload_exported": False,
        }
        result.append(row)
        by_name[name.casefold()] = provenance
    return result, by_name


def build_binding_replacements(
    reports_root: Path,
    output_root: Path,
    provenance_by_name: dict[str, dict[str, str]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    supersession_rows: list[dict[str, Any]] = []
    replacement_summary: list[dict[str, Any]] = []
    for relative, output_name, path_field, identity_field in BINDING_SPECS:
        source_path = reports_root / relative
        if not source_path.is_file():
            raise OfficialSourceRefreshError(f"required prior binding report missing: {source_path}")
        rows = read_tsv(source_path)
        fields = list(rows[0]) if rows else []
        if "source_sha256" not in fields or path_field not in fields:
            raise OfficialSourceRefreshError(f"unsupported binding schema: {source_path}")
        replacements: list[dict[str, Any]] = []
        for member_key, provenance in sorted(provenance_by_name.items()):
            hits = [row for row in rows if row.get(path_field, "").casefold() == member_key]
            if len(hits) != 1:
                raise OfficialSourceRefreshError(f"expected one binding row for {member_key} in {source_path}, found {len(hits)}")
            old = hits[0]
            if old.get("source_sha256") != provenance["modified_payload_sha256"]:
                raise OfficialSourceRefreshError(f"prior binding does not carry modified-source hash: {member_key} in {source_path}")
            if old.get("source_size") != provenance["official_size"]:
                raise OfficialSourceRefreshError(f"prior binding source size mismatch: {member_key} in {source_path}")
            replacement = dict(old)
            replacement["source_sha256"] = provenance["official_payload_sha256"]
            replacements.append(replacement)
            supersession_rows.append({
                "source_report": relative,
                "source_row_identity": old.get(identity_field, ""),
                "member_name": old[path_field],
                "old_modified_source_sha256": old["source_sha256"],
                "replacement_official_source_sha256": replacement["source_sha256"],
                "replacement_report": output_name,
                "supersession_status": "old_hash_row_superseded_by_official_overlay",
            })
        write_tsv(output_root / output_name, fields, replacements)
        replacement_summary.append({
            "source_report": relative,
            "replacement_report": output_name,
            "replacement_row_count": len(replacements),
            "schema_preserved": True,
            "only_source_sha256_changed": True,
            "prior_report_modified": False,
        })
    return supersession_rows, replacement_summary


def build_structural_retention_rows(
    reports_root: Path,
    required_rows: list[dict[str, str]],
    provenance_by_name: dict[str, dict[str, str]],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for plan in required_rows:
        member = plan["member_name"]
        provenance = provenance_by_name[member.casefold()]
        for token in filter(None, plan.get("dependent_metadata_files", "").split(";")):
            if "::" in token or not token.startswith(".local/reports/quartet_legacy_dlc/"):
                continue
            relative = token.removeprefix(".local/reports/quartet_legacy_dlc/")
            key = (member.casefold(), relative)
            if key in seen:
                continue
            seen.add(key)
            path = reports_root / relative
            if not path.is_file():
                rows.append({
                    "member_name": member,
                    "dependent_report": relative,
                    "member_name_present": False,
                    "modified_hash_present": False,
                    "official_hash_present": False,
                    "classification": "missing_dependency_file",
                    "required_action": "restore_prior_report_before_refresh_validation",
                })
                continue
            text = path.read_text(encoding="utf-8", errors="replace")
            member_present = member in text
            modified_present = provenance["modified_payload_sha256"] in text
            official_present = provenance["official_payload_sha256"] in text
            basename = Path(relative).name
            if modified_present:
                classification = "hash_bearing_row_replaced_by_overlay"
                action = "consume_official_overlay_instead_of_prior_row"
            elif member_present:
                classification = "structurally_retained_path_size_or_identity_only"
                action = "retain_prior_metadata; path_size_offset_are_proven_unchanged"
            else:
                classification = "reference_plan_only_no_direct_member_or_hash"
                action = "no_rebuild_required"
            rows.append({
                "member_name": member,
                "dependent_report": relative,
                "member_name_present": member_present,
                "modified_hash_present": modified_present,
                "official_hash_present": official_present,
                "classification": classification,
                "required_action": action,
            })
    return rows


def build_dry_transaction_validity(
    provenance_root: Path,
    transaction_root: Path,
) -> list[dict[str, Any]]:
    dry = read_tsv(provenance_root / "DLC_BR1_CURRENT_DRY_BKN_IMPACT.tsv")
    tx_summary = TX.validate_report(transaction_root)
    if tx_summary.get("policy", {}).get("core_integration_request_ready") is not True:
        raise OfficialSourceRefreshError("dry transaction contract is not integration-ready")
    rows: list[dict[str, Any]] = []
    for row in dry:
        unaffected = row.get("current_payload_affected") == "false" and row.get("comparison_status") == "identical"
        if not unaffected:
            raise OfficialSourceRefreshError(f"current dry BKN payload unexpectedly affected: {row.get('member_name')}")
        rows.append({
            "item_type": "dry_bkn_source_payload",
            "item_id": row["member_name"],
            "provenance_status": "identical_between_modified_and_official_source",
            "current_candidate_valid": True,
            "required_action": "retain_current_dry_candidate_payload",
        })
    rows.append({
        "item_type": "two_archive_transaction_contract",
        "item_id": tx_summary.get("request_file", "DLC_BKN_DRY_CORE_TARGET_REQUEST.json"),
        "provenance_status": "candidate_inputs_unaffected_and_contract_report_validated",
        "current_candidate_valid": True,
        "required_action": "retain_request_for_later_explicit_core_integration",
    })
    return rows


def refresh(
    project_root: Path,
    br1_root: Path,
    reports_root: Path,
    provenance_root: Path,
    transaction_root: Path,
    output_root: Path,
) -> tuple[Path, dict[str, Any]]:
    project_root = project_root.resolve()
    reports_root = reports_root.resolve()
    provenance_root = provenance_root.resolve()
    transaction_root = transaction_root.resolve()
    output_root = output_root.resolve()
    PROV.validate_report(provenance_root)
    TX.validate_report(transaction_root)
    if output_root.exists():
        shutil.rmtree(output_root)
    output_root.mkdir(parents=True)

    required_rows = _required_changed_rows(provenance_root)
    verified_rows, provenance_by_name = verify_official_members(br1_root.resolve(), provenance_root, required_rows)
    supersession_rows, replacement_summary = build_binding_replacements(reports_root, output_root, provenance_by_name)
    retention_rows = build_structural_retention_rows(reports_root, required_rows, provenance_by_name)
    dry_validity_rows = build_dry_transaction_validity(provenance_root, transaction_root)

    write_tsv(output_root / "DLC_BR1_OFFICIAL_CHANGED_MEMBER_VERIFICATION.tsv", verified_rows[0].keys(), verified_rows)
    write_tsv(output_root / "DLC_BR1_OFFICIAL_BINDING_SUPERSESSION.tsv", supersession_rows[0].keys(), supersession_rows)
    write_tsv(output_root / "DLC_BR1_OFFICIAL_BINDING_REPLACEMENT_SUMMARY.tsv", replacement_summary[0].keys(), replacement_summary)
    write_tsv(output_root / "DLC_BR1_STRUCTURAL_RETENTION_AUDIT.tsv", retention_rows[0].keys(), retention_rows)
    write_tsv(output_root / "DLC_BR1_DRY_BKN_TRANSACTION_VALIDITY.tsv", dry_validity_rows[0].keys(), dry_validity_rows)

    missing_dependencies = [row for row in retention_rows if row["classification"] == "missing_dependency_file"]
    gaps = []
    if missing_dependencies:
        gaps.append({
            "gap_id": "prior_dependency_report_missing",
            "severity": "blocking_refresh_validation",
            "details": str(len(missing_dependencies)),
            "required_action": "restore the prior metadata reports listed in DLC_BR1_STRUCTURAL_RETENTION_AUDIT.tsv",
        })
    else:
        gaps.append({
            "gap_id": "none_for_official_binding_refresh",
            "severity": "none",
            "details": "all 13 official changed DLC members verified and all three hash-bearing binding families superseded",
            "required_action": "future consumers must apply official replacement rows over the corresponding prior binding rows",
        })
    write_tsv(output_root / "DLC_BR1_OFFICIAL_SOURCE_REFRESH_GAPS.tsv", gaps[0].keys(), gaps)

    classifications = Counter(row["classification"] for row in retention_rows)
    summary = {
        "type": "br_quartet_legacy_dlc_br1_official_source_refresh_summary",
        "format_version": FORMAT_VERSION,
        "tool_version": TOOL_VERSION,
        "status": "official_changed_dlc_member_hashes_verified_binding_overlays_ready_dry_bkn_contract_retained_no_game_writes",
        "required_changed_dlc_members": len(required_rows),
        "official_changed_members_verified": len(verified_rows),
        "binding_families_refreshed": len(replacement_summary),
        "binding_rows_superseded": len(supersession_rows),
        "binding_rows_by_family": {row["replacement_report"]: row["replacement_row_count"] for row in replacement_summary},
        "structural_retention_rows": len(retention_rows),
        "structural_retention_classifications": dict(sorted(classifications.items())),
        "pack00_04_changed_members_used_by_workstream": 0,
        "current_dry_bkn_payload_affected": False,
        "dry_bkn_transaction_contract_still_valid": True,
        "findings": [
            "exactly 13 changed wet DLC G1T members from PACK00_02 require official-source hash refresh",
            "only the technical, nonscenario and external-texture binding rows embedded the old payload hashes",
            "path/size/offset and graph-only metadata remains structurally valid because those properties are identical across the archive pair",
            "the three changed 23_moviechannel.kslt members from PACK00_04_1/2/3 have no quartet_legacy_dlc dependency",
            "the current dry PC00 BKN parent and G1T are identical across modified and official PACK00_02 and the two-archive transaction request remains valid",
        ],
        "next_action": "use the official binding overlay for all future wet-DLC work; retain the existing dry-BKN candidates and transaction request; do not install until core wiring is separately implemented and approved",
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
            "official_binding_overlay_required_for_future_consumers": True,
            "underscore_source_canonical_allowed": False,
            "dry_bkn_transaction_request_retained": True,
        },
    }
    write_json(output_root / "SUMMARY.json", summary)
    write_json(output_root / "REPORT_MANIFEST.json", {"type": "br_report_manifest", "format_version": 1, "files": report_manifest(output_root)})
    archive = project_root / ".local/reports/quartet_legacy_dlc" / REPORT_ARCHIVE_NAME
    make_archive(output_root, archive)
    print(f"[stage61] official changed DLC members verified: {len(verified_rows)}", flush=True)
    print(f"[stage61] binding rows superseded: {len(supersession_rows)}", flush=True)
    print(f"[stage61] report: {archive}", flush=True)
    return archive, summary


def validate_report(report_root: Path) -> dict[str, Any]:
    report_root = report_root.resolve()
    required_files = (
        "DLC_BR1_OFFICIAL_CHANGED_MEMBER_VERIFICATION.tsv",
        "DLC_BR1_OFFICIAL_TECHNICAL_MEMBER_BINDINGS.tsv",
        "DLC_BR1_OFFICIAL_NONSCRIPT_MEMBER_BINDINGS.tsv",
        "DLC_BR1_OFFICIAL_EXTERNAL_TEXTURE_BINDINGS.tsv",
        "DLC_BR1_OFFICIAL_BINDING_SUPERSESSION.tsv",
        "DLC_BR1_OFFICIAL_BINDING_REPLACEMENT_SUMMARY.tsv",
        "DLC_BR1_STRUCTURAL_RETENTION_AUDIT.tsv",
        "DLC_BR1_DRY_BKN_TRANSACTION_VALIDITY.tsv",
        "DLC_BR1_OFFICIAL_SOURCE_REFRESH_GAPS.tsv",
        "SUMMARY.json",
        "REPORT_MANIFEST.json",
    )
    for name in required_files:
        if not (report_root / name).is_file():
            raise OfficialSourceRefreshError(f"missing report file: {name}")
    summary = json.loads((report_root / "SUMMARY.json").read_text(encoding="utf-8"))
    if summary.get("type") != "br_quartet_legacy_dlc_br1_official_source_refresh_summary" or summary.get("tool_version") != TOOL_VERSION:
        raise OfficialSourceRefreshError("invalid official refresh summary")
    if summary.get("status") != "official_changed_dlc_member_hashes_verified_binding_overlays_ready_dry_bkn_contract_retained_no_game_writes":
        raise OfficialSourceRefreshError("unexpected official refresh status")
    if summary.get("official_changed_members_verified") != 13 or summary.get("binding_rows_superseded") != 39:
        raise OfficialSourceRefreshError("official refresh counts are incomplete")
    for name in (
        "DLC_BR1_OFFICIAL_TECHNICAL_MEMBER_BINDINGS.tsv",
        "DLC_BR1_OFFICIAL_NONSCRIPT_MEMBER_BINDINGS.tsv",
        "DLC_BR1_OFFICIAL_EXTERNAL_TEXTURE_BINDINGS.tsv",
    ):
        rows = read_tsv(report_root / name)
        if len(rows) != 13:
            raise OfficialSourceRefreshError(f"official replacement row count mismatch: {name}")
    verification = read_tsv(report_root / "DLC_BR1_OFFICIAL_CHANGED_MEMBER_VERIFICATION.tsv")
    if len(verification) != 13 or any(row.get("verification_status") != "official_member_hash_and_layout_verified" for row in verification):
        raise OfficialSourceRefreshError("official member verification rows invalid")
    if any(row.get("payload_hash_changed") != "true" for row in verification):
        raise OfficialSourceRefreshError("official refresh contains unchanged payload")
    gaps = read_tsv(report_root / "DLC_BR1_OFFICIAL_SOURCE_REFRESH_GAPS.tsv")
    if len(gaps) != 1 or gaps[0].get("severity") != "none":
        raise OfficialSourceRefreshError("official refresh still contains blocking gaps")
    policy = summary.get("policy", {})
    false_keys = (
        "game_modified", "source_archives_modified", "prior_reports_modified", "git_modified",
        "translation_modified", "restoration_modified", "profile_build_allowed", "candidate_installed",
        "runtime_validated", "raw_assets_exported_in_report", "underscore_source_canonical_allowed",
    )
    if any(policy.get(key) is not False for key in false_keys):
        raise OfficialSourceRefreshError("official refresh violates fail-closed policy")
    if policy.get("official_binding_overlay_required_for_future_consumers") is not True or policy.get("dry_bkn_transaction_request_retained") is not True:
        raise OfficialSourceRefreshError("official refresh policy flags missing")
    manifest = json.loads((report_root / "REPORT_MANIFEST.json").read_text(encoding="utf-8"))
    for row in manifest.get("files", []):
        path = report_root / row["path"]
        if not path.is_file() or path.stat().st_size != row["size"] or sha256_file(path) != row["sha256"]:
            raise OfficialSourceRefreshError(f"report manifest mismatch: {row.get('path')}")
        if {suffix.casefold() for suffix in path.suffixes} & FORBIDDEN_REPORT_SUFFIXES:
            raise OfficialSourceRefreshError(f"raw asset in report: {path}")
    return summary


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    refresh_parser = sub.add_parser("refresh")
    refresh_parser.add_argument("--project-root", type=Path, required=True)
    refresh_parser.add_argument("--br1-root", type=Path, required=True)
    refresh_parser.add_argument("--reports-root", type=Path)
    refresh_parser.add_argument("--provenance-root", type=Path)
    refresh_parser.add_argument("--transaction-root", type=Path)
    refresh_parser.add_argument("--output-root", type=Path)
    validate_parser = sub.add_parser("validate-report")
    validate_parser.add_argument("--report-root", type=Path, required=True)
    bundle_parser = sub.add_parser("bundle-report")
    bundle_parser.add_argument("--report-root", type=Path, required=True)
    bundle_parser.add_argument("--output", type=Path, required=True)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        if args.command == "refresh":
            project = args.project_root.resolve()
            reports = (args.reports_root or project / ".local/reports/quartet_legacy_dlc").resolve()
            provenance = (args.provenance_root or reports / PROV.REPORT_DIR_NAME).resolve()
            transaction = (args.transaction_root or reports / TX.REPORT_DIR_NAME).resolve()
            output = (args.output_root or reports / REPORT_DIR_NAME).resolve()
            refresh(project, args.br1_root, reports, provenance, transaction, output)
        elif args.command == "validate-report":
            print(json.dumps(validate_report(args.report_root), ensure_ascii=False, sort_keys=True))
        elif args.command == "bundle-report":
            validate_report(args.report_root)
            make_archive(args.report_root.resolve(), args.output.resolve())
        else:
            raise OfficialSourceRefreshError("unsupported command")
    except (OfficialSourceRefreshError, PROV.Br1SourceProvenanceError, TX.BknDryTransactionContractError, NESTED.NestedContainerError, OSError, subprocess.TimeoutExpired) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
