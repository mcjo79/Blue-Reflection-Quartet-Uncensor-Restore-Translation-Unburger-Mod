#!/usr/bin/env python3
"""Verify BR1 official-source provenance after underscore PAK retirement.

Stage 108 is a read-only closure audit. It consumes the committed stage-107
report and the canonical metadata written by that transaction, verifies the
four official non-underscore Steam PAKs, requires all four historical
underscore PAK files to be absent, and proves that the retained provenance
ledger is sufficient for future work.

No inventory, report, profile, registry, PAK, installed game, or Git data is
modified. The only output is a deterministic evidence archive.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path, PurePosixPath
from typing import Any, Iterable, Mapping, Sequence

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT_DEFAULT = SCRIPT_DIR.parent.parent
TOOL_VERSION = "0.1.22"
REPORT_NAME = "BR_quartet_restoration_br1_official_source_retirement_closure_evidence.tar.zst"
REPORT_DIR = "br1_official_source_retirement_closure_evidence"
STAGE107_REPORT_NAME = "BR_quartet_restoration_br1_official_source_metadata_refresh_evidence.tar.zst"
LEDGER_REL = Path("provenance/br1_source_archive_provenance_ledger.json")
SOURCE_INVENTORY_REL = Path("inventories/br1_assets.source.json")
EXPECTED_ARCHIVES = (
    "DATA/PACK00_02.PAK",
    "DATA/PACK00_04_1.PAK",
    "DATA/PACK00_04_2.PAK",
    "DATA/PACK00_04_3.PAK",
)


class Stage108Error(RuntimeError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise Stage108Error(message)


def progress(message: str) -> None:
    print(f"[stage108] {message}", file=sys.stderr, flush=True)


def hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(4 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise Stage108Error(f"invalid JSON {path}: {exc}") from exc


def safe_int(value: Any, default: int = -1) -> int:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return default


def safe_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().casefold() in {"1", "true", "yes"}


def safe_rel(raw: str) -> str:
    value = raw.replace("\\", "/").lstrip("/")
    pure = PurePosixPath(value)
    require(pure.parts and ".." not in pure.parts, f"unsafe relative path: {raw!r}")
    return pure.as_posix()


def read_tsv(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    require(path.is_file(), f"missing TSV: {path}")
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        require(reader.fieldnames is not None, f"TSV has no header: {path}")
        return list(reader.fieldnames), list(reader)


def tsv_bytes(fields: Sequence[str], rows: Iterable[Mapping[str, Any]]) -> bytes:
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=list(fields), delimiter="\t", lineterminator="\n", extrasaction="ignore")
    writer.writeheader()
    for row in rows:
        writer.writerow({field: row.get(field, "") for field in fields})
    return buffer.getvalue().encode("utf-8")


def json_bytes(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def extract_stage107(report: Path, destination: Path) -> Path:
    destination.mkdir(parents=True, exist_ok=True)
    result = subprocess.run(["tar", "--zstd", "-xf", str(report), "-C", str(destination)], text=True, capture_output=True)
    require(result.returncode == 0, result.stderr.strip() or f"failed to extract {report}")
    root = destination / "br1_official_source_metadata_refresh_evidence"
    require(root.is_dir(), f"stage-107 report directory missing: {root}")
    return root


def make_archive(source: Path, output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(output.name + ".tmp")
    temporary.unlink(missing_ok=True)
    result = subprocess.run(
        [
            "tar", "--sort=name", "--mtime=@0", "--owner=0", "--group=0",
            "--numeric-owner", "--zstd", "-cf", str(temporary),
            "-C", str(source.parent), source.name,
        ],
        text=True,
        capture_output=True,
    )
    require(result.returncode == 0, result.stderr.strip() or "failed to create report archive")
    os.replace(temporary, output)


def index_archives(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    indexed: dict[str, dict[str, Any]] = {}
    for row in rows:
        archive = safe_rel(str(row.get("archive", "")))
        require(archive.casefold() not in indexed, f"duplicate archive row: {archive}")
        indexed[archive.casefold()] = row
    return indexed


def collect(*, project_root: Path, game_root: Path, stage107_report: Path, output: Path) -> dict[str, Any]:
    project_root = project_root.resolve()
    game_root = game_root.resolve()
    report_root = project_root / ".local/reports/quartet_restoration"
    require(stage107_report.is_file(), f"missing stage-107 report: {stage107_report}")
    require(game_root.is_dir(), f"invalid BR1 game root: {game_root}")

    with tempfile.TemporaryDirectory(prefix="br_stage108_") as temp_raw:
        temp = Path(temp_raw)
        stage107_dir = extract_stage107(stage107_report, temp / "stage107")
        stage107_summary = load_json(stage107_dir / "SUMMARY.json")
        require(stage107_summary.get("tool_version") == "0.1.21", "stage-107 tool version mismatch")
        require(stage107_summary.get("status") in {
            "official_source_metadata_refresh_committed",
            "official_source_metadata_refresh_already_applied_verified",
        }, "stage-107 refresh is not committed")
        transaction_mode = str(stage107_summary.get("transaction_mode", ""))
        require(transaction_mode in {"applied_transactionally", "already_applied_verified"}, "stage-107 transaction mode is not final")
        require(safe_bool(stage107_summary.get("underscore_archives_safe_to_delete")), "stage-107 did not authorize retirement")
        require(not safe_bool(stage107_summary.get("underscore_archives_read")), "stage-107 unexpectedly read underscore archives")
        require(not safe_bool(stage107_summary.get("underscore_archives_required_after_refresh")), "stage-107 still requires underscore archives")
        require(safe_int(stage107_summary.get("official_archive_rows")) == 4, "stage-107 official archive count mismatch")
        require(safe_int(stage107_summary.get("refreshed_member_rows")) == 33, "stage-107 member count mismatch")
        require(safe_int(stage107_summary.get("classification_changed_rows")) == 0, "stage-107 classification changes are nonzero")
        require(safe_int(stage107_summary.get("registered_profiles_affected")) == 0, "stage-107 reports affected profiles")

        _, verification_rows = read_tsv(stage107_dir / "OFFICIAL_SOURCE_ARCHIVE_VERIFICATION.tsv")
        require(len(verification_rows) == 4, "stage-107 archive verification row count mismatch")
        verification_by_archive = {safe_rel(row["archive"]).casefold(): row for row in verification_rows}
        require(set(verification_by_archive) == {x.casefold() for x in EXPECTED_ARCHIVES}, "stage-107 archive set mismatch")

        official_rows: list[dict[str, Any]] = []
        underscore_rows: list[dict[str, Any]] = []
        for archive in EXPECTED_ARCHIVES:
            expected = verification_by_archive[archive.casefold()]
            official_path = game_root / archive
            underscore_path = official_path.with_name(official_path.name + "_")
            require(official_path.is_file(), f"missing official archive: {official_path}")
            actual_size = official_path.stat().st_size
            actual_sha256 = hash_file(official_path)
            expected_size = safe_int(expected.get("official_size"))
            expected_sha256 = str(expected.get("official_sha256", "")).casefold()
            require(actual_size == expected_size, f"official archive size mismatch: {archive}")
            require(actual_sha256.casefold() == expected_sha256, f"official archive SHA-256 mismatch: {archive}")
            official_rows.append({
                "archive": archive,
                "size": actual_size,
                "sha256": actual_sha256,
                "verification": "official_nonunderscore_verified",
            })
            underscore_absent = not underscore_path.exists()
            require(underscore_absent, f"historical underscore archive still present: {underscore_path}")
            underscore_rows.append({
                "archive": archive,
                "historical_archive": archive + "_",
                "present": False,
                "retirement_state": "deleted_after_verified_refresh",
            })

        ledger_path = report_root / LEDGER_REL
        source_inventory_path = report_root / SOURCE_INVENTORY_REL
        require(ledger_path.is_file(), f"missing provenance ledger: {ledger_path}")
        require(source_inventory_path.is_file(), f"missing canonical source inventory: {source_inventory_path}")
        ledger = load_json(ledger_path)
        source_inventory = load_json(source_inventory_path)

        require(ledger.get("type") == "br1_source_archive_provenance_ledger", "provenance ledger type mismatch")
        require(ledger.get("tool_version") == "0.1.21", "provenance ledger tool version mismatch")
        policy = ledger.get("canonical_policy", {})
        retirement = ledger.get("retirement", {})
        source_evidence = ledger.get("source_evidence", {})
        require(safe_bool(policy.get("official_nonunderscore_archives_are_canonical")), "ledger does not mark official archives canonical")
        require(safe_bool(policy.get("underscore_archives_are_historical_analysis_only")), "ledger does not classify underscore archives as historical")
        require(not safe_bool(policy.get("underscore_archives_required_for_normal_workflow")), "ledger still requires underscore archives")
        require(safe_bool(policy.get("underscore_archives_safe_to_delete_after_committed_stage107")), "ledger does not authorize retirement")
        require(not safe_bool(retirement.get("file_payloads_retained_by_project")), "ledger claims historical payloads are retained")
        require(safe_bool(retirement.get("hashes_and_member_level_diff_retained")), "ledger does not retain hashes/member diff")
        require(not safe_bool(retirement.get("normal_workflow_dependency_after_refresh")), "ledger records a post-refresh dependency")
        require(safe_int(source_evidence.get("archive_pairs")) == 4, "ledger archive-pair count mismatch")
        require(safe_int(source_evidence.get("changed_members")) == 33, "ledger changed-member count mismatch")
        require(safe_int(source_evidence.get("classification_changes")) == 0, "ledger classification changes are nonzero")
        require(safe_int(source_evidence.get("affected_registered_profiles")) == 0, "ledger reports affected profiles")
        require(len(ledger.get("archives", [])) == 4, "ledger archive row count mismatch")
        require(len(ledger.get("members", [])) == 33, "ledger member row count mismatch")

        source_provenance = source_inventory.get("canonical_source_provenance", {})
        require(source_provenance.get("tool_version") == "0.1.21", "source inventory canonical provenance version mismatch")
        require(safe_int(source_provenance.get("stage")) == 107, "source inventory canonical stage mismatch")
        require(safe_int(source_provenance.get("official_archives")) == 4, "source inventory official archive count mismatch")
        require(safe_int(source_provenance.get("refreshed_members")) == 33, "source inventory refreshed-member count mismatch")
        require(not safe_bool(source_provenance.get("underscore_archives_required")), "source inventory still requires underscore archives")

        source_archive_rows = index_archives(list(source_inventory.get("archives", [])))
        metadata_rows: list[dict[str, Any]] = []
        for official in official_rows:
            archive = official["archive"]
            row = source_archive_rows.get(archive.casefold())
            require(row is not None, f"source inventory missing official archive: {archive}")
            require(str(row.get("provenance", "")) == "official_steam_canonical", f"source inventory provenance mismatch: {archive}")
            require(str(row.get("extraction_status", "")) == "official_steam_canonical", f"source inventory extraction status mismatch: {archive}")
            require(str(row.get("sha256", "")).casefold() == official["sha256"].casefold(), f"source inventory SHA-256 mismatch: {archive}")
            require(safe_int(row.get("size")) == official["size"], f"source inventory size mismatch: {archive}")
            preserved = row.get("preserved_untrusted_candidate", {})
            require(isinstance(preserved, dict), f"source inventory lacks preserved candidate metadata: {archive}")
            require(preserved.get("archive_filename") == Path(archive).name + "_", f"preserved filename mismatch: {archive}")
            require(not safe_bool(preserved.get("retained_as_file")), f"source inventory claims underscore file retained: {archive}")
            require(bool(preserved.get("sha256")), f"preserved SHA-256 missing: {archive}")
            metadata_rows.append({
                "archive": archive,
                "canonical_provenance": row.get("provenance", ""),
                "official_sha256": row.get("sha256", ""),
                "preserved_archive_filename": preserved.get("archive_filename", ""),
                "preserved_sha256_retained": bool(preserved.get("sha256")),
                "preserved_file_retained": safe_bool(preserved.get("retained_as_file")),
                "verification": "canonical_metadata_closed",
            })

        retention_rows = [
            {"item": "official archive identities", "retained": True, "source": "source_inventory_and_stage107_report"},
            {"item": "preserved archive identities", "retained": True, "source": "provenance_ledger_and_source_inventory"},
            {"item": "33 member old/new hashes", "retained": len(ledger.get("members", [])) == 33, "source": "provenance_ledger"},
            {"item": "member-level diff evidence", "retained": safe_bool(retirement.get("hashes_and_member_level_diff_retained")), "source": "stage105_stage106_and_ledger"},
            {"item": "historical payload files", "retained": False, "source": "user_managed_retirement"},
        ]
        dependency_rows = [
            {"question": "do normal analyses require underscore archives", "answer": False, "classification": "retired_historical_inputs"},
            {"question": "are official non-underscore PAKs canonical", "answer": True, "classification": "canonical_source_rule"},
            {"question": "are any registered profiles affected", "answer": False, "classification": "15_profiles_retained"},
            {"question": "is stage104 slot-light evidence independent", "answer": safe_bool(stage107_summary.get("stage104_slot_light_evidence_independent")), "classification": "independent_effect_container_branch"},
            {"question": "may future workflow depend on deleted payloads", "answer": False, "classification": "hash_and_report_only_history"},
        ]

        report_dir = temp / REPORT_DIR
        report_dir.mkdir()
        (report_dir / "OFFICIAL_SOURCE_POST_RETIREMENT_ARCHIVE_VERIFICATION.tsv").write_bytes(tsv_bytes(
            ["archive", "size", "sha256", "verification"], official_rows))
        (report_dir / "UNDERSCORE_ARCHIVE_ABSENCE.tsv").write_bytes(tsv_bytes(
            ["archive", "historical_archive", "present", "retirement_state"], underscore_rows))
        (report_dir / "OFFICIAL_SOURCE_POST_RETIREMENT_METADATA_VERIFICATION.tsv").write_bytes(tsv_bytes(
            ["archive", "canonical_provenance", "official_sha256", "preserved_archive_filename", "preserved_sha256_retained", "preserved_file_retained", "verification"], metadata_rows))
        (report_dir / "PROVENANCE_RETENTION_VERIFICATION.tsv").write_bytes(tsv_bytes(
            ["item", "retained", "source"], retention_rows))
        (report_dir / "NORMAL_WORKFLOW_DEPENDENCY_CLOSURE.tsv").write_bytes(tsv_bytes(
            ["question", "answer", "classification"], dependency_rows))

        summary = {
            "type": "br_quartet_restoration_br1_official_source_retirement_closure_evidence_summary",
            "format_version": 1,
            "tool_version": TOOL_VERSION,
            "status": "underscore_archive_retirement_closed",
            "stage107_transaction_mode": transaction_mode,
            "official_archive_rows": 4,
            "official_archives_verified": 4,
            "underscore_archive_rows": 4,
            "underscore_archives_absent": 4,
            "ledger_archive_rows": len(ledger.get("archives", [])),
            "ledger_member_rows": len(ledger.get("members", [])),
            "classification_changed_rows": 0,
            "registered_profiles_affected": 0,
            "stage104_slot_light_evidence_independent": safe_bool(stage107_summary.get("stage104_slot_light_evidence_independent")),
            "preserved_hashes_and_member_diff_retained": True,
            "underscore_archives_required_for_normal_workflow": False,
            "retirement_complete": True,
            "policy": {
                "official_nonunderscore_archives_are_canonical": True,
                "historical_payload_files_required": False,
                "pak_write_authorized": False,
                "G1E_G1EM_write_authorized": False,
                "profile_or_registry_write_authorized": False,
                "installed_game_write": False,
                "metadata_write": False,
                "unrelated_results_invalidated": False,
            },
            "next_action": "Resume normal restoration analysis from official non-underscore PAKs and retained provenance reports; continue the independent stage-104 slot-light branch without relying on deleted underscore archives.",
        }
        (report_dir / "SUMMARY.json").write_bytes(json_bytes(summary))
        make_archive(report_dir, output)
        return {"summary": summary, "report_path": str(output)}


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path, default=PROJECT_ROOT_DEFAULT)
    parser.add_argument("--game-root", type=Path, required=True)
    parser.add_argument("--stage107-report", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)

    project_root = args.project_root.resolve()
    report_root = project_root / ".local/reports/quartet_restoration"
    stage107_report = (args.stage107_report or (report_root / STAGE107_REPORT_NAME)).resolve()
    output = (args.output or (report_root / REPORT_NAME)).resolve()
    try:
        result = collect(project_root=project_root, game_root=args.game_root, stage107_report=stage107_report, output=output)
    except Stage108Error as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    progress(f"wrote {result['report_path']}")
    print(json.dumps(result["summary"], ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
