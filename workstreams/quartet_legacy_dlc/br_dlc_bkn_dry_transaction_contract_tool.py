#!/usr/bin/env python3
"""Build metadata-only evidence for a two-archive dry-BKN transaction contract.

The stage validates both local PAK candidates and both installed baselines, then
runs the real core transaction engine against two tiny isolated stand-ins.  It
never prepares a transaction for the actual game and never writes to the game.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path
from typing import Any, Iterable

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import br_dlc_dry_pak_insertion_tool as PACK10
import br_dlc_bkn_dry_pack12_repack_tool as PACK12

TOOL_VERSION = "0.0.26"
FORMAT_VERSION = 1
REPORT_DIR_NAME = "bkn_dry_transaction_contract_evidence"
REPORT_ARCHIVE_NAME = "BR_quartet_legacy_dlc_bkn_dry_transaction_contract_evidence.tar.zst"
PACK10_REPORT_DIR = "dry_pak_insertion_evidence"
PACK10_REPORT_ARCHIVE = "BR_quartet_legacy_dlc_dry_pak_insertion_evidence.tar.zst"
PACK12_REPORT_DIR = PACK12.REPORT_DIR_NAME
PACK12_REPORT_ARCHIVE = PACK12.REPORT_ARCHIVE_NAME
CORE_MODULE_RELATIVE = Path("Blue_Reflection_Patcher")
CORE_TRANSACTION_SOURCE = Path("internal/plan/transaction/transaction.go")
CORE_TRANSACTION_TEST = Path("internal/plan/transaction/transaction_test.go")
TARGETS = ("Data/PACK10_02.PAK", "Data/PACK12.PAK")
FORBIDDEN_REPORT_SUFFIXES = {
    ".pak", ".xml", ".kscl", ".kslt", ".g1t", ".g1m", ".swg", ".oid",
    ".elixir", ".gz", ".exe", ".dll", ".bin",
}


class BknDryTransactionContractError(RuntimeError):
    pass


def sha256_file(path: Path, chunk_size: int = 16 * 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(chunk_size)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def write_tsv(path: Path, fieldnames: Iterable[str], rows: Iterable[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(fieldnames), delimiter="\t", lineterminator="\n", extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({key: bool_text(value) for key, value in row.items()})


def read_tsv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def bool_text(value: Any) -> Any:
    if isinstance(value, bool):
        return "true" if value else "false"
    if value is None:
        return ""
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return value


def make_archive(root: Path, output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(output.name + ".tmp")
    temporary.unlink(missing_ok=True)
    command = ["tar", "--zstd", "-cf", str(temporary), "-C", str(root.parent), root.name]
    result = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if result.returncode != 0:
        temporary.unlink(missing_ok=True)
        raise BknDryTransactionContractError(f"cannot create report archive: {result.stderr.strip()}")
    os.replace(temporary, output)


def extract_archive(archive: Path, destination: Path) -> Path:
    destination.mkdir(parents=True, exist_ok=True)
    result = subprocess.run(
        ["tar", "--zstd", "-xf", str(archive), "-C", str(destination)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    if result.returncode != 0:
        raise BknDryTransactionContractError(f"cannot extract prerequisite report: {result.stderr.strip()}")
    children = [path for path in destination.iterdir() if path.is_dir()]
    if len(children) != 1:
        raise BknDryTransactionContractError("prerequisite archive must contain exactly one report directory")
    return children[0]


def locate_report(report_parent: Path, directory: str, archive_name: str, temporary: Path) -> Path:
    direct = report_parent / directory
    if direct.is_dir():
        return direct
    archive = report_parent / archive_name
    if not archive.is_file():
        raise BknDryTransactionContractError(f"missing prerequisite report: {direct} / {archive}")
    return extract_archive(archive, temporary / directory)


def report_manifest(root: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.name == "REPORT_MANIFEST.json":
            continue
        suffixes = {suffix.casefold() for suffix in path.suffixes}
        if suffixes & FORBIDDEN_REPORT_SUFFIXES:
            raise BknDryTransactionContractError(f"raw asset-like file in report: {path}")
        rows.append({
            "path": path.relative_to(root).as_posix(),
            "size": path.stat().st_size,
            "sha256": sha256_file(path),
        })
    return rows


def normalized_relative(path: str) -> str:
    return path.replace("\\", "/").lstrip("/")


def resolve_local_candidate(project_root: Path, relative: str) -> Path:
    candidate = (project_root / Path(normalized_relative(relative))).resolve()
    project = project_root.resolve()
    try:
        candidate.relative_to(project)
    except ValueError as exc:
        raise BknDryTransactionContractError(f"candidate escapes project root: {relative}") from exc
    if not candidate.is_file() or candidate.is_symlink():
        raise BknDryTransactionContractError(f"candidate is not a regular file: {candidate}")
    return candidate


def validate_prerequisites(project_root: Path) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, str]]]:
    report_parent = project_root / ".local/reports/quartet_legacy_dlc"
    with tempfile.TemporaryDirectory(prefix="br-dlc-contract-prereq-") as name:
        temp = Path(name)
        pack10_root = locate_report(report_parent, PACK10_REPORT_DIR, PACK10_REPORT_ARCHIVE, temp)
        pack12_root = locate_report(report_parent, PACK12_REPORT_DIR, PACK12_REPORT_ARCHIVE, temp)
        pack10_summary = PACK10.validate_report(pack10_root)
        pack12_summary = PACK12.validate_report(pack12_root)
        composition = read_tsv(pack12_root / "DLC_BKN_DRY_TWO_ARCHIVE_COMPOSITION.tsv")
    if pack10_summary.get("tool_version") != "0.0.13":
        raise BknDryTransactionContractError("dry PACK10_02 prerequisite is not the validated 0.0.13 report")
    if pack12_summary.get("tool_version") != "0.0.21":
        raise BknDryTransactionContractError("PACK12 prerequisite is not the validated 0.0.21 report")
    if len(composition) != 2:
        raise BknDryTransactionContractError("two-archive composition prerequisite is incomplete")
    return pack10_summary, pack12_summary, composition


def iter_go_call_arguments(source_text: str, function_name: str) -> Iterable[list[str]]:
    """Yield top-level arguments for calls to a Go function.

    The scanner is intentionally small but formatting-independent. It handles
    nested parentheses plus quoted strings and comments, which is sufficient
    for source-provenance checks without requiring a Go parser.
    """
    call_pattern = re.compile(rf"\b{re.escape(function_name)}\s*\(")

    def scan_balanced(open_index: int) -> tuple[str, int] | None:
        depth = 1
        index = open_index + 1
        start = index
        quote = ""
        escaped = False
        line_comment = False
        block_comment = False
        while index < len(source_text):
            char = source_text[index]
            nxt = source_text[index + 1] if index + 1 < len(source_text) else ""
            if line_comment:
                if char == "\n":
                    line_comment = False
                index += 1
                continue
            if block_comment:
                if char == "*" and nxt == "/":
                    block_comment = False
                    index += 2
                else:
                    index += 1
                continue
            if quote:
                if quote == "`":
                    if char == "`":
                        quote = ""
                elif escaped:
                    escaped = False
                elif char == "\\":
                    escaped = True
                elif char == quote:
                    quote = ""
                index += 1
                continue
            if char == "/" and nxt == "/":
                line_comment = True
                index += 2
                continue
            if char == "/" and nxt == "*":
                block_comment = True
                index += 2
                continue
            if char in {'"', "'", "`"}:
                quote = char
                index += 1
                continue
            if char == "(":
                depth += 1
            elif char == ")":
                depth -= 1
                if depth == 0:
                    return source_text[start:index], index + 1
            index += 1
        return None

    def split_arguments(arguments_text: str) -> list[str]:
        arguments: list[str] = []
        start = 0
        depth = 0
        quote = ""
        escaped = False
        line_comment = False
        block_comment = False
        index = 0
        while index < len(arguments_text):
            char = arguments_text[index]
            nxt = arguments_text[index + 1] if index + 1 < len(arguments_text) else ""
            if line_comment:
                if char == "\n":
                    line_comment = False
                index += 1
                continue
            if block_comment:
                if char == "*" and nxt == "/":
                    block_comment = False
                    index += 2
                else:
                    index += 1
                continue
            if quote:
                if quote == "`":
                    if char == "`":
                        quote = ""
                elif escaped:
                    escaped = False
                elif char == "\\":
                    escaped = True
                elif char == quote:
                    quote = ""
                index += 1
                continue
            if char == "/" and nxt == "/":
                line_comment = True
                index += 2
                continue
            if char == "/" and nxt == "*":
                block_comment = True
                index += 2
                continue
            if char in {'"', "'", "`"}:
                quote = char
            elif char in "([{":
                depth += 1
            elif char in ")]}":
                depth -= 1
            elif char == "," and depth == 0:
                arguments.append(arguments_text[start:index].strip())
                start = index + 1
            index += 1
        tail = arguments_text[start:].strip()
        if tail or arguments:
            arguments.append(tail)
        return arguments

    for match in call_pattern.finditer(source_text):
        open_index = match.end() - 1
        scanned = scan_balanced(open_index)
        if scanned is None:
            continue
        arguments_text, _ = scanned
        yield split_arguments(arguments_text)


def has_backup_copy_call(source_text: str) -> bool:
    """Recognize copyRegularFile(target, <backup identifier>, ...) calls."""
    for arguments in iter_go_call_arguments(source_text, "copyRegularFile"):
        if len(arguments) < 2:
            continue
        first = re.sub(r"\s+", "", arguments[0])
        second = re.sub(r"\s+", "", arguments[1])
        if first != "target":
            continue
        if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", second) and "backup" in second.lower():
            return True
    return False


def inspect_core_contract(core_root: Path) -> tuple[list[dict[str, Any]], str, str]:
    source = core_root / CORE_TRANSACTION_SOURCE
    tests = core_root / CORE_TRANSACTION_TEST
    if not source.is_file() or not tests.is_file():
        raise BknDryTransactionContractError("core transaction engine source/tests are missing")
    source_text = source.read_text(encoding="utf-8")
    test_text = tests.read_text(encoding="utf-8")

    def source_matches(pattern: str) -> bool:
        return re.search(pattern, source_text, flags=re.MULTILINE | re.DOTALL) is not None

    checks = [
        ("prepare_stages_and_hashes_payloads", source_matches(r"copyRegularFile\s*\(\s*stagedSource\s*,\s*stagedCopy\b") and "staged hash mismatch" in source_text),
        ("prepare_backs_up_and_hashes_existing_targets", has_backup_copy_call(source_text) and "backup hash mismatch" in source_text),
        ("commit_rechecks_original_hash", "target changed after prepare" in source_text),
        ("commit_uses_atomic_install", source_matches(r"atomicInstall\s*\(\s*staged\s*,\s*target\b")),
        ("journal_updated_per_file", 'record.CommitState = "committed"' in source_text and "writeJournal(journalPath, journal)" in source_text),
        ("rollback_runs_in_reverse", source_matches(r"for\s+index\s*:=\s*len\(journal\.Files\)\s*-\s*1\s*;\s*index\s*>=\s*0\s*;\s*index--")),
        ("rollback_requires_desired_hash", "refusing rollback because target changed after commit" in source_text),
        ("path_escape_and_duplicate_rejected", "duplicate transaction path" in source_text and "transaction path escapes root" in source_text),
        ("core_unit_tests_cover_prepare_commit_rollback", "TestPrepareCommitRollbackExistingAndNewFiles" in test_text),
        ("core_unit_tests_cover_commit_conflict", "TestCommitRejectsExternalModificationAfterPrepare" in test_text),
        ("core_unit_tests_cover_rollback_conflict", "TestRollbackRejectsExternalModificationAfterCommit" in test_text),
    ]
    rows = [
        {
            "capability": name,
            "present": passed,
            "validation_method": "static_source_or_test_scan",
            "validation_status": "passed" if passed else "pending_behavioral_probe",
        }
        for name, passed in checks
    ]
    return rows, sha256_file(source), sha256_file(tests)


def finalize_core_capabilities(rows: list[dict[str, Any]], probe: dict[str, Any]) -> list[dict[str, Any]]:
    """Resolve observable capabilities from the isolated runtime probe.

    Static source matches are provenance hints only.  A locally refactored core
    may use different helper names or variable names while preserving the same
    transaction behavior, so tests and report generation must not require the
    static matcher to recognize the current checkout.
    """
    behavioral = {
        "prepare_stages_and_hashes_payloads": bool(probe.get("staged_payloads_hash_verified")),
        "prepare_backs_up_and_hashes_existing_targets": bool(
            probe.get("backup_files_hash_verified") and probe.get("journal_hashes_verified")
        ),
        "commit_rechecks_original_hash": bool(
            probe.get("conflict_after_prepare_rejected") and probe.get("conflict_target_preserved")
        ),
        "journal_updated_per_file": bool(
            probe.get("journal_file_count") == 2
            and probe.get("commit_replaced_both")
            and probe.get("rollback_restored_both")
        ),
    }
    resolved: list[dict[str, Any]] = []
    for original in rows:
        row = dict(original)
        name = row["capability"]
        if not row.get("present") and behavioral.get(name):
            row["present"] = True
            row["validation_method"] = "isolated_behavioral_probe"
            row["validation_status"] = "passed"
        resolved.append(row)
    missing = [row["capability"] for row in resolved if not row.get("present")]
    if missing:
        raise BknDryTransactionContractError(f"core transaction contract capability missing: {missing}")
    return resolved


def run_core_probe(core_root: Path, work_root: Path, metadata: dict[str, str], timeout: int) -> dict[str, Any]:
    probe_root = work_root / "core_transaction_probe"
    if probe_root.exists():
        shutil.rmtree(probe_root)
    probe_root.mkdir(parents=True)
    # Go's replace directive does not quote filesystem paths.  An absolute
    # project path containing spaces is therefore parsed as multiple module
    # tokens.  Expose the existing core tree through a fixed relative symlink
    # inside the isolated probe and keep the directive free of host-path text.
    core_link = probe_root / "core_module"
    try:
        core_link.symlink_to(core_root.resolve(), target_is_directory=True)
    except OSError as exc:
        raise BknDryTransactionContractError(
            f"could not create local core-module link for transaction probe: {exc}"
        ) from exc
    (probe_root / "go.mod").write_text(
        "module local/blue-reflection-patcher/transactioncontractprobe\n\n"
        "go 1.22\n\n"
        "require local/blue-reflection-patcher v0.0.0\n\n"
        "replace local/blue-reflection-patcher => ./core_module\n",
        encoding="utf-8",
    )
    main_go = r'''package main

import (
    "crypto/sha256"
    "encoding/hex"
    "encoding/json"
    "fmt"
    "os"
    "path/filepath"

    tx "local/blue-reflection-patcher/internal/plan/transaction"
)

type report struct {
    Type string `json:"type"`
    FormatVersion int `json:"format_version"`
    Status string `json:"status"`
    PreparePreservedBothOriginals bool `json:"prepare_preserved_both_originals"`
    StagedPayloadsHashVerified bool `json:"staged_payloads_hash_verified"`
    BackupFilesHashVerified bool `json:"backup_files_hash_verified"`
    JournalHashesVerified bool `json:"journal_hashes_verified"`
    JournalFileCount int `json:"journal_file_count"`
    JournalPaths []string `json:"journal_paths"`
    CommitReplacedBoth bool `json:"commit_replaced_both"`
    RollbackRestoredBoth bool `json:"rollback_restored_both"`
    FinalJournalStatus string `json:"final_journal_status"`
    ConflictAfterPrepareRejected bool `json:"conflict_after_prepare_rejected"`
    ConflictTargetPreserved bool `json:"conflict_target_preserved"`
    SelectedModules []string `json:"selected_modules"`
    Metadata map[string]string `json:"metadata"`
}

func write(path, value string) error {
    if err := os.MkdirAll(filepath.Dir(path), 0755); err != nil { return err }
    return os.WriteFile(path, []byte(value), 0644)
}
func read(path string) string { value, _ := os.ReadFile(path); return string(value) }
func sum(value string) string { digest := sha256.Sum256([]byte(value)); return hex.EncodeToString(digest[:]) }

func main() {
    if len(os.Args) != 3 { panic("usage: probe ROOT METADATA_JSON") }
    root := os.Args[1]
    var metadata map[string]string
    if err := json.Unmarshal([]byte(os.Args[2]), &metadata); err != nil { panic(err) }
    game := filepath.Join(root, "game")
    state := filepath.Join(root, "state")
    payload := filepath.Join(root, "payload")
    a := filepath.Join(game, "Data", "PACK10_02.PAK")
    b := filepath.Join(game, "Data", "PACK12.PAK")
    pa := filepath.Join(payload, "PACK10_02.PAK")
    pb := filepath.Join(payload, "PACK12.PAK")
    for path, value := range map[string]string{a:"baseline-pack10", b:"baseline-pack12", pa:"candidate-pack10", pb:"candidate-pack12"} {
        if err := write(path, value); err != nil { panic(err) }
    }
    prepared, err := tx.Prepare(game, state, []tx.ChangeSpec{
        {RelativePath:"Data/PACK10_02.PAK", StagedPath:pa},
        {RelativePath:"Data/PACK12.PAK", StagedPath:pb},
    }, []string{"quartet_legacy_dlc"}, metadata)
    if err != nil { panic(err) }
    prepareClean := read(a)=="baseline-pack10" && read(b)=="baseline-pack12"
    originals := map[string]string{"Data/PACK10_02.PAK":"baseline-pack10", "Data/PACK12.PAK":"baseline-pack12"}
    desired := map[string]string{"Data/PACK10_02.PAK":"candidate-pack10", "Data/PACK12.PAK":"candidate-pack12"}
    stagedOK := true
    backupsOK := true
    journalHashesOK := true
    for _, file := range prepared.Journal.Files {
        original, okOriginal := originals[file.RelativePath]
        wanted, okDesired := desired[file.RelativePath]
        if !(okOriginal && okDesired) { stagedOK = false; backupsOK = false; journalHashesOK = false; continue }
        stagedPath := filepath.Join(prepared.Journal.TransactionRoot, filepath.FromSlash(file.StagedPath))
        backupPath := filepath.Join(prepared.Journal.TransactionRoot, filepath.FromSlash(file.BackupPath))
        if read(stagedPath) != wanted { stagedOK = false }
        if !file.OriginalExisted || file.BackupPath == "" || read(backupPath) != original { backupsOK = false }
        if file.OriginalSHA256 != sum(original) || file.DesiredSHA256 != sum(wanted) { journalHashesOK = false }
    }
    committed, err := tx.Commit(prepared.JournalPath)
    if err != nil { panic(err) }
    commitOK := read(a)=="candidate-pack10" && read(b)=="candidate-pack12"
    rolled, err := tx.Rollback(prepared.JournalPath)
    if err != nil { panic(err) }
    rollbackOK := read(a)=="baseline-pack10" && read(b)=="baseline-pack12"

    conflictState := filepath.Join(root, "conflict-state")
    conflictPayload := filepath.Join(root, "conflict-payload")
    cpa := filepath.Join(conflictPayload, "PACK10_02.PAK")
    cpb := filepath.Join(conflictPayload, "PACK12.PAK")
    if err := write(cpa, "second-candidate-pack10"); err != nil { panic(err) }
    if err := write(cpb, "second-candidate-pack12"); err != nil { panic(err) }
    conflictPrepared, err := tx.Prepare(game, conflictState, []tx.ChangeSpec{
        {RelativePath:"Data/PACK10_02.PAK", StagedPath:cpa},
        {RelativePath:"Data/PACK12.PAK", StagedPath:cpb},
    }, []string{"quartet_legacy_dlc"}, metadata)
    if err != nil { panic(err) }
    if err := write(b, "external-change"); err != nil { panic(err) }
    _, conflictErr := tx.Commit(conflictPrepared.JournalPath)
    conflictRejected := conflictErr != nil
    conflictPreserved := read(b)=="external-change"

    paths := []string{}
    for _, file := range committed.Files { paths = append(paths, file.RelativePath) }
    value := report{
        Type:"br_quartet_legacy_dlc_core_transaction_probe", FormatVersion:1, Status:"passed",
        PreparePreservedBothOriginals:prepareClean, StagedPayloadsHashVerified:stagedOK,
        BackupFilesHashVerified:backupsOK, JournalHashesVerified:journalHashesOK,
        JournalFileCount:len(committed.Files), JournalPaths:paths,
        CommitReplacedBoth:commitOK, RollbackRestoredBoth:rollbackOK, FinalJournalStatus:rolled.Status,
        ConflictAfterPrepareRejected:conflictRejected, ConflictTargetPreserved:conflictPreserved,
        SelectedModules:committed.SelectedModules, Metadata:committed.Metadata,
    }
    if !(prepareClean && stagedOK && backupsOK && journalHashesOK && len(committed.Files)==2 && commitOK && rollbackOK && rolled.Status==tx.StatusRolledBack && conflictRejected && conflictPreserved) {
        panic(fmt.Sprintf("probe invariant failed: %+v", value))
    }
    output, _ := json.MarshalIndent(value, "", "  ")
    fmt.Println(string(output))
}
'''
    (probe_root / "main.go").write_text(main_go, encoding="utf-8")
    run_root = probe_root / "run"
    run_root.mkdir()
    environment = os.environ.copy()
    environment["GOWORK"] = "off"
    environment["GOCACHE"] = str((work_root / "go_cache").resolve())
    environment["GOMODCACHE"] = str((work_root / "go_mod_cache").resolve())
    command = ["go", "run", ".", str(run_root), json.dumps(metadata, sort_keys=True, separators=(",", ":"))]
    result = subprocess.run(command, cwd=probe_root, env=environment, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=timeout)
    if result.returncode != 0:
        raise BknDryTransactionContractError(f"core transaction probe failed: {result.stderr.strip()}")
    try:
        value = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise BknDryTransactionContractError("core transaction probe returned invalid JSON") from exc
    if value.get("status") != "passed":
        raise BknDryTransactionContractError("core transaction probe did not pass")
    return value


def build_request(inputs: list[dict[str, Any]], source_hash: str, test_hash: str) -> dict[str, Any]:
    return {
        "type": "br_quartet_legacy_dlc_core_transaction_request",
        "format_version": 1,
        "request_version": TOOL_VERSION,
        "request_status": "ready_for_core_integration_not_prepared_not_committed",
        "target_id": "blue_reflection_quartet",
        "content_id": "costume_pc00_bkn",
        "workstream_id": "quartet_legacy_dlc",
        "selected_modules": ["quartet_legacy_dlc"],
        "transaction_files": inputs,
        "core_contract": {
            "journal_type": "br_file_transaction",
            "journal_format_version": 1,
            "source_sha256": source_hash,
            "test_sha256": test_hash,
            "single_journal_required": True,
            "backup_every_existing_target": True,
            "hash_gate_prepare_and_commit": True,
            "same_directory_atomic_replace_required": True,
            "reverse_order_guarded_rollback_required": True,
            "independent_archive_install_forbidden": True,
        },
        "authorization": {
            "core_integration_request_ready": True,
            "real_transaction_prepare_enabled": False,
            "commit_enabled": False,
            "candidate_installed": False,
            "profile_build_allowed": False,
            "profile_registered": False,
            "runtime_validated": False,
            "wet_variant_included": False,
        },
        "required_future_action": "core must explicitly wire this two-file request into one prepare/commit/rollback transaction; no real prepare or commit is authorized by this evidence stage",
    }


def audit(project_root: Path, quartet_root: Path, output_root: Path, timeout: int = 180) -> tuple[Path, dict[str, Any]]:
    project_root = project_root.resolve()
    quartet_root = quartet_root.resolve()
    report_parent = project_root / ".local/reports/quartet_legacy_dlc"
    output_root = output_root.resolve()
    if output_root.exists():
        shutil.rmtree(output_root)
    output_root.mkdir(parents=True)

    pack10_summary, pack12_summary, composition = validate_prerequisites(project_root)
    composition_by_archive = {row["archive"]: row for row in composition}
    if set(composition_by_archive) != set(TARGETS):
        raise BknDryTransactionContractError("composition archives differ from the fixed transaction scope")

    expected_baselines = {
        "Data/PACK10_02.PAK": (int(pack10_summary["baseline_size"]), pack10_summary["baseline_sha256"]),
        "Data/PACK12.PAK": (int(pack12_summary["candidate_pack12_size"]) - 8, pack12_summary["baseline_pack12_sha256"]),
    }
    candidates: dict[str, Path] = {}
    input_rows: list[dict[str, Any]] = []
    baseline_rows: list[dict[str, Any]] = []
    request_inputs: list[dict[str, Any]] = []

    for archive in TARGETS:
        row = composition_by_archive[archive]
        candidate = resolve_local_candidate(project_root, row["candidate_relative_path"])
        candidate_stat = candidate.stat()
        candidate_hash = sha256_file(candidate)
        if candidate_stat.st_size != int(row["candidate_size"]) or candidate_hash != row["candidate_sha256"]:
            raise BknDryTransactionContractError(f"candidate drift: {archive}")
        candidates[archive] = candidate

        installed = quartet_root / Path(archive)
        if not installed.is_file() or installed.is_symlink():
            raise BknDryTransactionContractError(f"installed baseline missing or not regular: {installed}")
        before = installed.stat()
        baseline_hash = sha256_file(installed)
        after = installed.stat()
        expected_size, expected_hash = expected_baselines[archive]
        if before.st_size != expected_size or baseline_hash != expected_hash:
            raise BknDryTransactionContractError(f"installed baseline drift: {archive}")
        unchanged = before.st_size == after.st_size and before.st_mtime_ns == after.st_mtime_ns
        if not unchanged:
            raise BknDryTransactionContractError(f"installed baseline changed during read-only audit: {archive}")
        role = row["role"]
        input_rows.append({
            "archive": archive,
            "role": role,
            "baseline_size": before.st_size,
            "baseline_sha256": baseline_hash,
            "candidate_relative_path": row["candidate_relative_path"],
            "candidate_size": candidate_stat.st_size,
            "candidate_sha256": candidate_hash,
            "candidate_hash_verified": True,
            "candidate_installed": False,
            "validation_status": "passed",
        })
        baseline_rows.append({
            "archive": archive,
            "installed_size_before": before.st_size,
            "installed_size_after": after.st_size,
            "installed_mtime_ns_before": before.st_mtime_ns,
            "installed_mtime_ns_after": after.st_mtime_ns,
            "installed_sha256": baseline_hash,
            "expected_sha256": expected_hash,
            "installed_archive_unchanged": unchanged,
            "game_write_performed": False,
            "validation_status": "passed",
        })
        request_inputs.append({
            "relative_path": archive,
            "role": role,
            "baseline_size": before.st_size,
            "baseline_sha256": baseline_hash,
            "candidate_relative_path": row["candidate_relative_path"],
            "candidate_size": candidate_stat.st_size,
            "candidate_sha256": candidate_hash,
        })

    core_root = project_root / CORE_MODULE_RELATIVE
    capability_rows, core_source_hash, core_test_hash = inspect_core_contract(core_root)
    build_root = project_root / ".local/build/quartet_legacy_dlc/transaction_contract/costume_pc00_bkn_dry"
    build_root.mkdir(parents=True, exist_ok=True)
    metadata = {
        "target_id": "blue_reflection_quartet",
        "content_id": "costume_pc00_bkn",
        "workstream_id": "quartet_legacy_dlc",
        "pack10_candidate_sha256": composition_by_archive["Data/PACK10_02.PAK"]["candidate_sha256"],
        "pack12_candidate_sha256": composition_by_archive["Data/PACK12.PAK"]["candidate_sha256"],
    }
    probe = run_core_probe(core_root, build_root, metadata, timeout)
    capability_rows = finalize_core_capabilities(capability_rows, probe)
    write_json(build_root / "CORE_TRANSACTION_PROBE.json", probe)

    rehearsal_rows = [{
        "engine": "Blue_Reflection_Patcher/internal/plan/transaction",
        "standin_target_count": probe["journal_file_count"],
        "standin_paths": probe["journal_paths"],
        "prepare_preserved_both_originals": probe["prepare_preserved_both_originals"],
        "staged_payloads_hash_verified": probe["staged_payloads_hash_verified"],
        "backup_files_hash_verified": probe["backup_files_hash_verified"],
        "journal_hashes_verified": probe["journal_hashes_verified"],
        "commit_replaced_both": probe["commit_replaced_both"],
        "rollback_restored_both": probe["rollback_restored_both"],
        "final_journal_status": probe["final_journal_status"],
        "conflict_after_prepare_rejected": probe["conflict_after_prepare_rejected"],
        "conflict_target_preserved": probe["conflict_target_preserved"],
        "real_game_files_used": False,
        "validation_status": "passed",
    }]

    requirement_rows = [
        {"requirement": "one_journal_spans_both_archives", "required": True, "proven_by_synthetic_core_probe": True, "real_integration_status": "not_wired", "blocks_commit": True},
        {"requirement": "prepare_hash_gates_both_installed_baselines", "required": True, "proven_by_synthetic_core_probe": True, "real_integration_status": "not_wired", "blocks_commit": True},
        {"requirement": "verified_backup_for_both_existing_archives", "required": True, "proven_by_synthetic_core_probe": True, "real_integration_status": "not_wired", "blocks_commit": True},
        {"requirement": "same_directory_atomic_replace_for_each_archive", "required": True, "proven_by_synthetic_core_probe": True, "real_integration_status": "not_wired", "blocks_commit": True},
        {"requirement": "reverse_order_hash_guarded_rollback", "required": True, "proven_by_synthetic_core_probe": True, "real_integration_status": "not_wired", "blocks_commit": True},
        {"requirement": "explicit_user_authorization_before_real_prepare_or_commit", "required": True, "proven_by_synthetic_core_probe": False, "real_integration_status": "not_authorized", "blocks_commit": True},
    ]
    gaps = [
        {"dependency": "core_two_archive_request_wiring", "status": "request_ready_not_integrated", "blocks_commit": True, "next_evidence": "core must consume the request as one transaction and keep commit disabled by default"},
        {"dependency": "explicit_real_transaction_authorization", "status": "not_granted", "blocks_commit": True, "next_evidence": "obtain explicit approval before any prepare or commit touching the game installation"},
        {"dependency": "runtime_availability_and_costume_selection", "status": "not_validated", "blocks_commit": True, "next_evidence": "perform a controlled runtime test only after transactional integration and explicit approval"},
        {"dependency": "owner_ui_icon_or_thumbnail", "status": "unresolved", "blocks_commit": True, "next_evidence": "observe runtime result or prove a format-specific owner binding; do not patch isolated UI integers"},
        {"dependency": "wet_variant_conversion", "status": "conversion_blocked", "blocks_commit": False, "next_evidence": "complete G1M/SWG conversion separately; dry-only test remains independently scoped"},
    ]

    request = build_request(request_inputs, core_source_hash, core_test_hash)
    write_tsv(output_root / "DLC_BKN_DRY_TRANSACTION_INPUTS.tsv", input_rows[0].keys(), input_rows)
    write_tsv(output_root / "DLC_BKN_DRY_BASELINE_GUARDS.tsv", baseline_rows[0].keys(), baseline_rows)
    write_tsv(output_root / "DLC_BKN_DRY_CORE_ENGINE_CAPABILITIES.tsv", capability_rows[0].keys(), capability_rows)
    write_tsv(output_root / "DLC_BKN_DRY_CORE_ENGINE_REHEARSAL.tsv", rehearsal_rows[0].keys(), rehearsal_rows)
    write_tsv(output_root / "DLC_BKN_DRY_TRANSACTION_REQUIREMENTS.tsv", requirement_rows[0].keys(), requirement_rows)
    write_tsv(output_root / "DLC_BKN_DRY_TRANSACTION_GAPS.tsv", gaps[0].keys(), gaps)
    write_json(output_root / "DLC_BKN_DRY_CORE_TARGET_REQUEST.json", request)

    summary = {
        "type": "br_quartet_legacy_dlc_bkn_dry_transaction_contract_summary",
        "format_version": FORMAT_VERSION,
        "tool_version": TOOL_VERSION,
        "status": "two_archive_transaction_contract_ready_core_integration_required_not_prepared_not_installed",
        "content_id": "costume_pc00_bkn",
        "target_id": "blue_reflection_quartet",
        "transaction_target_count": 2,
        "installed_baselines_hash_verified": 2,
        "local_candidates_hash_verified": 2,
        "core_capability_checks_passed": len(capability_rows),
        "core_synthetic_transaction_file_count": probe["journal_file_count"],
        "core_synthetic_prepare_passed": probe["prepare_preserved_both_originals"],
        "core_synthetic_commit_passed": probe["commit_replaced_both"],
        "core_synthetic_rollback_passed": probe["rollback_restored_both"],
        "core_synthetic_conflict_guard_passed": probe["conflict_after_prepare_rejected"] and probe["conflict_target_preserved"],
        "core_transaction_source_sha256": core_source_hash,
        "core_transaction_test_sha256": core_test_hash,
        "request_file": "DLC_BKN_DRY_CORE_TARGET_REQUEST.json",
        "unresolved_commit_blockers": sum(bool(row["blocks_commit"]) for row in gaps),
        "findings": [
            "both installed baselines and both local dry-BKN candidate archives match their prerequisite evidence hashes",
            "the real core transaction engine successfully prepared, committed and rolled back two isolated existing-file stand-ins",
            "the real core transaction engine rejected a target changed after prepare and preserved the external change",
            "a checksum-bound two-archive core target request is ready, but no real transaction was prepared or committed",
            "the installed game, Translation, restoration registry, profiles and Git remain untouched",
        ],
        "next_action": "hand the metadata-only request to core for explicit two-file transaction wiring; keep real prepare and commit disabled until separately approved",
        "policy": {
            "game_modified": False,
            "git_modified": False,
            "translation_modified": False,
            "restoration_registry_modified": False,
            "candidate_installed": False,
            "profile_build_allowed": False,
            "profile_registered": False,
            "runtime_validated": False,
            "wet_variant_included": False,
            "raw_assets_exported_in_report": False,
            "raw_assets_in_update": False,
            "real_transaction_prepared": False,
            "real_transaction_committed": False,
            "synthetic_core_transaction_rehearsed": True,
            "core_integration_request_ready": True,
            "independent_archive_install_allowed": False,
        },
    }
    write_json(output_root / "SUMMARY.json", summary)
    write_json(output_root / "REPORT_MANIFEST.json", {"type": "br_report_manifest", "format_version": 1, "files": report_manifest(output_root)})
    archive = report_parent / REPORT_ARCHIVE_NAME
    make_archive(output_root, archive)
    print(f"[stage55] request: {output_root / 'DLC_BKN_DRY_CORE_TARGET_REQUEST.json'}", flush=True)
    print(f"[stage55] report: {archive}", flush=True)
    return archive, summary


def validate_report(report_root: Path) -> dict[str, Any]:
    report_root = report_root.resolve()
    required = (
        "DLC_BKN_DRY_TRANSACTION_INPUTS.tsv",
        "DLC_BKN_DRY_BASELINE_GUARDS.tsv",
        "DLC_BKN_DRY_CORE_ENGINE_CAPABILITIES.tsv",
        "DLC_BKN_DRY_CORE_ENGINE_REHEARSAL.tsv",
        "DLC_BKN_DRY_TRANSACTION_REQUIREMENTS.tsv",
        "DLC_BKN_DRY_TRANSACTION_GAPS.tsv",
        "DLC_BKN_DRY_CORE_TARGET_REQUEST.json",
        "SUMMARY.json",
        "REPORT_MANIFEST.json",
    )
    for name in required:
        if not (report_root / name).is_file():
            raise BknDryTransactionContractError(f"missing report file: {name}")
    summary = json.loads((report_root / "SUMMARY.json").read_text(encoding="utf-8"))
    if summary.get("type") != "br_quartet_legacy_dlc_bkn_dry_transaction_contract_summary" or summary.get("tool_version") != TOOL_VERSION:
        raise BknDryTransactionContractError("invalid transaction-contract summary")
    if summary.get("status") != "two_archive_transaction_contract_ready_core_integration_required_not_prepared_not_installed":
        raise BknDryTransactionContractError("unexpected transaction-contract status")
    if summary.get("transaction_target_count") != 2 or summary.get("installed_baselines_hash_verified") != 2 or summary.get("local_candidates_hash_verified") != 2:
        raise BknDryTransactionContractError("transaction inputs were not completely verified")
    if not all(summary.get(key) is True for key in (
        "core_synthetic_prepare_passed", "core_synthetic_commit_passed",
        "core_synthetic_rollback_passed", "core_synthetic_conflict_guard_passed",
    )):
        raise BknDryTransactionContractError("core synthetic transaction rehearsal did not fully pass")
    policy = summary.get("policy", {})
    false_keys = (
        "game_modified", "git_modified", "translation_modified", "restoration_registry_modified",
        "candidate_installed", "profile_build_allowed", "profile_registered", "runtime_validated",
        "wet_variant_included", "raw_assets_exported_in_report", "raw_assets_in_update",
        "real_transaction_prepared", "real_transaction_committed", "independent_archive_install_allowed",
    )
    if any(policy.get(key) is not False for key in false_keys):
        raise BknDryTransactionContractError("transaction-contract report violates fail-closed policy")
    if policy.get("synthetic_core_transaction_rehearsed") is not True or policy.get("core_integration_request_ready") is not True:
        raise BknDryTransactionContractError("transaction contract lacks required readiness declarations")

    inputs = read_tsv(report_root / "DLC_BKN_DRY_TRANSACTION_INPUTS.tsv")
    if len(inputs) != 2 or {row.get("archive") for row in inputs} != set(TARGETS):
        raise BknDryTransactionContractError("transaction input set is not exactly PACK10_02 plus PACK12")
    if any(row.get("validation_status") != "passed" or row.get("candidate_installed") != "false" for row in inputs):
        raise BknDryTransactionContractError("transaction input validation failed")
    guards = read_tsv(report_root / "DLC_BKN_DRY_BASELINE_GUARDS.tsv")
    if len(guards) != 2 or any(row.get("installed_archive_unchanged") != "true" or row.get("game_write_performed") != "false" for row in guards):
        raise BknDryTransactionContractError("installed baseline preservation is incomplete")
    capabilities = read_tsv(report_root / "DLC_BKN_DRY_CORE_ENGINE_CAPABILITIES.tsv")
    if len(capabilities) < 10 or any(row.get("validation_status") != "passed" for row in capabilities):
        raise BknDryTransactionContractError("core transaction capabilities are incomplete")
    rehearsal = read_tsv(report_root / "DLC_BKN_DRY_CORE_ENGINE_REHEARSAL.tsv")
    if len(rehearsal) != 1 or rehearsal[0].get("validation_status") != "passed" or rehearsal[0].get("real_game_files_used") != "false":
        raise BknDryTransactionContractError("core transaction rehearsal is invalid")
    request = json.loads((report_root / "DLC_BKN_DRY_CORE_TARGET_REQUEST.json").read_text(encoding="utf-8"))
    if request.get("request_status") != "ready_for_core_integration_not_prepared_not_committed":
        raise BknDryTransactionContractError("core target request status is invalid")
    auth = request.get("authorization", {})
    if auth.get("core_integration_request_ready") is not True or any(auth.get(key) is not False for key in (
        "real_transaction_prepare_enabled", "commit_enabled", "candidate_installed",
        "profile_build_allowed", "profile_registered", "runtime_validated", "wet_variant_included",
    )):
        raise BknDryTransactionContractError("core target request authorization is not fail-closed")
    files = request.get("transaction_files", [])
    if len(files) != 2 or {row.get("relative_path") for row in files} != set(TARGETS):
        raise BknDryTransactionContractError("core target request file set is invalid")
    gaps = read_tsv(report_root / "DLC_BKN_DRY_TRANSACTION_GAPS.tsv")
    if len(gaps) < 4 or not any(row.get("blocks_commit") == "true" for row in gaps):
        raise BknDryTransactionContractError("transaction blockers are missing")
    manifest = json.loads((report_root / "REPORT_MANIFEST.json").read_text(encoding="utf-8"))
    for row in manifest.get("files", []):
        path = report_root / row["path"]
        if not path.is_file() or path.stat().st_size != row["size"] or sha256_file(path) != row["sha256"]:
            raise BknDryTransactionContractError(f"report manifest mismatch: {row.get('path')}")
        if {suffix.casefold() for suffix in path.suffixes} & FORBIDDEN_REPORT_SUFFIXES:
            raise BknDryTransactionContractError(f"raw asset in report: {path}")
    return summary


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    audit_parser = sub.add_parser("audit")
    audit_parser.add_argument("--project-root", type=Path, required=True)
    audit_parser.add_argument("--quartet-root", type=Path, required=True)
    audit_parser.add_argument("--output-root", type=Path)
    audit_parser.add_argument("--timeout", type=int, default=180)
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
            audit(project, args.quartet_root, output, args.timeout)
        elif args.command == "validate-report":
            summary = validate_report(args.report_root)
            print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
        elif args.command == "bundle-report":
            validate_report(args.report_root)
            make_archive(args.report_root.resolve(), args.output.resolve())
        else:
            raise BknDryTransactionContractError("unsupported command")
    except (BknDryTransactionContractError, PACK10.DryPakInsertionError, PACK12.BknDryPack12RepackError, OSError, subprocess.TimeoutExpired) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
