#!/usr/bin/env python3
"""Run a local shadow-core rehearsal for the dry PC00 BKN payload-preview resolver.

The stage validates the stage-70 metadata-only patch request, copies the current
Blue_Reflection_Patcher source tree into .local/build, patches only that shadow
copy, adds an unwired handoff-backed resolver prototype and Go regression tests,
and runs the payloadpreview package tests.  The canonical core tree and game
files remain read-only.  No transaction Prepare, Commit or Rollback call is
made and no PAK is copied into the report.
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
from pathlib import Path
from typing import Any, Iterable

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import br_dlc_bkn_dry_payload_preview_contract_tool as CONTRACT

TOOL_VERSION = "0.0.32"
FORMAT_VERSION = 1
REPORT_DIR_NAME = "bkn_dry_shadow_core_rehearsal_evidence"
REPORT_ARCHIVE_NAME = "BR_quartet_legacy_dlc_bkn_dry_shadow_core_rehearsal_evidence.tar.zst"
EXPECTED_TARGETS = ("Data/PACK10_02.PAK", "Data/PACK12.PAK")
FORBIDDEN_REPORT_SUFFIXES = CONTRACT.FORBIDDEN_REPORT_SUFFIXES
SHADOW_RELATIVE = ".local/build/quartet_legacy_dlc/shadow_core_rehearsal/costume_pc00_bkn/Blue_Reflection_Patcher"


class ShadowCoreRehearsalError(RuntimeError):
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
    names = list(fields)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=names, delimiter="\t", lineterminator="\n", extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({name: bool_text(row.get(name, "")) for name in names})


def read_tsv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(4 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def report_manifest(root: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.name == "REPORT_MANIFEST.json":
            continue
        if {suffix.casefold() for suffix in path.suffixes} & FORBIDDEN_REPORT_SUFFIXES:
            raise ShadowCoreRehearsalError(f"raw asset-like file in report: {path}")
        rows.append({"path": path.relative_to(root).as_posix(), "size": path.stat().st_size, "sha256": sha256_file(path)})
    return rows


def make_archive(root: Path, output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(output.name + ".tmp")
    temporary.unlink(missing_ok=True)
    result = subprocess.run(["tar", "--zstd", "-cf", str(temporary), "-C", str(root.parent), root.name], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if result.returncode != 0:
        temporary.unlink(missing_ok=True)
        raise ShadowCoreRehearsalError(f"cannot create report archive: {result.stderr.strip()}")
    os.replace(temporary, output)


def _load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ShadowCoreRehearsalError(f"cannot read JSON {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ShadowCoreRehearsalError(f"JSON root is not an object: {path}")
    return value


def validate_patch_request(request: dict[str, Any]) -> list[dict[str, Any]]:
    if request.get("type") != "br_quartet_legacy_dlc_core_payload_preview_patch_request":
        raise ShadowCoreRehearsalError("unexpected patch request type")
    if request.get("request_version") != "0.0.31":
        raise ShadowCoreRehearsalError("unexpected patch request version")
    authorization = request.get("authorization", {})
    if authorization.get("patch_request_ready") is not True:
        raise ShadowCoreRehearsalError("patch request is not ready")
    forbidden_true = (
        "core_modified", "core_patch_applied", "game_modified", "git_modified",
        "profile_build_allowed", "profile_registered", "real_transaction_commit_enabled",
        "real_transaction_prepare_enabled", "runtime_validated", "wet_variant_included",
        "candidate_installed",
    )
    if any(authorization.get(key) is not False for key in forbidden_true):
        raise ShadowCoreRehearsalError("patch request authorization is not fail-closed")
    artifacts = request.get("artifact_contract", [])
    if len(artifacts) != 2 or tuple(row.get("relative_path") for row in artifacts) != EXPECTED_TARGETS:
        raise ShadowCoreRehearsalError("patch request must contain ordered PACK10_02 and PACK12 contracts")
    for row in artifacts:
        for key in ("baseline_sha256", "candidate_sha256"):
            value = str(row.get(key, ""))
            if len(value) != 64 or any(ch not in "0123456789abcdef" for ch in value):
                raise ShadowCoreRehearsalError(f"invalid {key} for {row.get('relative_path')}")
        if int(row.get("baseline_size", 0)) <= 0 or int(row.get("candidate_size", 0)) <= 0:
            raise ShadowCoreRehearsalError("artifact sizes must be positive")
        if row.get("independent_preview_ready_allowed") is not False or row.get("transaction_prepare_allowed") is not False:
            raise ShadowCoreRehearsalError("artifact contract permits an unsafe independent/prepare state")
    return artifacts


def patch_catalog(path: Path, candidate: dict[str, Any]) -> dict[str, Any]:
    doc = _load_json(path)
    rows = doc.get("module_targets", [])
    matches = [row for row in rows if row.get("module_id") == "quartet_legacy_dlc" and row.get("target_id") == "blue_reflection_quartet"]
    if len(matches) != 1:
        raise ShadowCoreRehearsalError(f"expected one legacy-DLC catalog row, found {len(matches)}")
    row = matches[0]
    before = json.loads(json.dumps(row))
    row.clear()
    row.update(candidate)
    write_json(path, doc)
    return before


def prototype_go_source() -> str:
    return r'''package payloadpreview

import (
    "encoding/json"
    "fmt"
    "os"
    "path/filepath"
    "strings"
)

type legacyDLCArtifactContract struct {
    RelativePath string `json:"relative_path"`
    CandidateRelativePath string `json:"candidate_relative_path"`
    BaselineSize int64 `json:"baseline_size"`
    BaselineSHA256 string `json:"baseline_sha256"`
    CandidateSize int64 `json:"candidate_size"`
    CandidateSHA256 string `json:"candidate_sha256"`
    IndependentPreviewReadyAllowed bool `json:"independent_preview_ready_allowed"`
    TransactionPrepareAllowed bool `json:"transaction_prepare_allowed"`
}

type legacyDLCAuthorization struct {
    RealTransactionPrepareEnabled bool `json:"real_transaction_prepare_enabled"`
    RealTransactionCommitEnabled bool `json:"real_transaction_commit_enabled"`
    CandidateInstalled bool `json:"candidate_installed"`
    WetVariantIncluded bool `json:"wet_variant_included"`
}

type legacyDLCPreviewRequest struct {
    Type string `json:"type"`
    ArtifactContract []legacyDLCArtifactContract `json:"artifact_contract"`
    Authorization legacyDLCAuthorization `json:"authorization"`
}

func loadLegacyDLCPreviewRequest(path string) (legacyDLCPreviewRequest, error) {
    data, err := os.ReadFile(path)
    if err != nil { return legacyDLCPreviewRequest{}, err }
    var request legacyDLCPreviewRequest
    if err := json.Unmarshal(data, &request); err != nil { return legacyDLCPreviewRequest{}, err }
    if request.Type != "br_quartet_legacy_dlc_core_payload_preview_patch_request" { return legacyDLCPreviewRequest{}, fmt.Errorf("unexpected request type") }
    if request.Authorization.RealTransactionPrepareEnabled || request.Authorization.RealTransactionCommitEnabled || request.Authorization.CandidateInstalled || request.Authorization.WetVariantIncluded { return legacyDLCPreviewRequest{}, fmt.Errorf("request is not preview-only") }
    if len(request.ArtifactContract) != 2 { return legacyDLCPreviewRequest{}, fmt.Errorf("expected exactly two artifacts") }
    expected := []string{"Data/PACK10_02.PAK", "Data/PACK12.PAK"}
    for index, contract := range request.ArtifactContract {
        if filepath.ToSlash(contract.RelativePath) != expected[index] { return legacyDLCPreviewRequest{}, fmt.Errorf("unexpected artifact order/path") }
        if contract.IndependentPreviewReadyAllowed || contract.TransactionPrepareAllowed { return legacyDLCPreviewRequest{}, fmt.Errorf("unsafe artifact authorization") }
        if contract.BaselineSize <= 0 || contract.CandidateSize <= 0 || len(contract.BaselineSHA256) != 64 || len(contract.CandidateSHA256) != 64 { return legacyDLCPreviewRequest{}, fmt.Errorf("invalid artifact hash/size contract") }
    }
    return request, nil
}

func inspectLegacyDLCPreviewArtifacts(projectRoot, gameRoot, moduleID string, contracts []legacyDLCArtifactContract) ([]ArtifactPreview, bool) {
    artifacts := make([]ArtifactPreview, 0, len(contracts))
    allReady := len(contracts) == 2
    for _, contract := range contracts {
        artifact := ArtifactPreview{ModuleID: moduleID, RelativePath: filepath.ToSlash(contract.RelativePath), DesiredAction: "blocked", Status: "invalid"}
        source, err := secureProjectPath(projectRoot, contract.CandidateRelativePath)
        if err != nil { artifact.Error = err.Error(); artifacts = append(artifacts, artifact); allReady = false; continue }
        artifact.SourcePath = source
        info, err := os.Lstat(source)
        if err != nil || info.Mode()&os.ModeSymlink != 0 || !info.Mode().IsRegular() { artifact.Error = "candidate is not a regular non-symlink file"; artifacts = append(artifacts, artifact); allReady = false; continue }
        artifact.SourceBytes = info.Size()
        artifact.SourceSHA256, err = hashFile(source)
        if err != nil || artifact.SourceBytes != contract.CandidateSize || !strings.EqualFold(artifact.SourceSHA256, contract.CandidateSHA256) { artifact.Error = "candidate hash/size mismatch"; artifacts = append(artifacts, artifact); allReady = false; continue }
        targetPath, exists, err := resolveTargetPath(gameRoot, contract.RelativePath)
        artifact.TargetPath, artifact.TargetExists = targetPath, exists
        if err != nil || !exists { artifact.Error = "baseline target is missing"; artifacts = append(artifacts, artifact); allReady = false; continue }
        targetInfo, err := os.Lstat(targetPath)
        if err != nil || targetInfo.Mode()&os.ModeSymlink != 0 || !targetInfo.Mode().IsRegular() { artifact.Error = "baseline is not a regular non-symlink file"; artifacts = append(artifacts, artifact); allReady = false; continue }
        artifact.TargetBytes = targetInfo.Size()
        artifact.TargetSHA256, err = hashFile(targetPath)
        if err != nil || artifact.TargetBytes != contract.BaselineSize || !strings.EqualFold(artifact.TargetSHA256, contract.BaselineSHA256) { artifact.Error = "baseline hash/size mismatch"; artifacts = append(artifacts, artifact); allReady = false; continue }
        artifact.ReportSHA256 = contract.CandidateSHA256
        artifact.ReportBytes = contract.CandidateSize
        artifact.ReportVerified = true
        artifact.DesiredAction = "replace"
        artifact.TransactionReady = true
        artifact.Status = "ready"
        artifacts = append(artifacts, artifact)
    }
    if !allReady {
        for index := range artifacts { artifacts[index].TransactionReady = false }
    }
    return artifacts, allReady
}
'''


def prototype_go_test_source() -> str:
    return r'''package payloadpreview

import (
    "crypto/sha256"
    "encoding/hex"
    "encoding/json"
    "os"
    "path/filepath"
    "testing"
)

func shadowDigest(data []byte) string { sum := sha256.Sum256(data); return hex.EncodeToString(sum[:]) }

func writeShadowFile(t *testing.T, path string, data []byte) {
    t.Helper()
    if err := os.MkdirAll(filepath.Dir(path), 0o755); err != nil { t.Fatal(err) }
    if err := os.WriteFile(path, data, 0o644); err != nil { t.Fatal(err) }
}

func makeShadowRequest(t *testing.T, root, game string) string {
    t.Helper()
    candidates := [][]byte{[]byte("candidate-10"), []byte("candidate-12")}
    baselines := [][]byte{[]byte("baseline-10"), []byte("baseline-12")}
    relatives := []string{"Data/PACK10_02.PAK", "Data/PACK12.PAK"}
    candidateRelatives := []string{".local/build/dlc/PACK10_02.PAK", ".local/build/dlc/PACK12.PAK"}
    request := legacyDLCPreviewRequest{Type: "br_quartet_legacy_dlc_core_payload_preview_patch_request"}
    for index := range relatives {
        writeShadowFile(t, filepath.Join(root, filepath.FromSlash(candidateRelatives[index])), candidates[index])
        writeShadowFile(t, filepath.Join(game, filepath.FromSlash(relatives[index])), baselines[index])
        request.ArtifactContract = append(request.ArtifactContract, legacyDLCArtifactContract{
            RelativePath: relatives[index], CandidateRelativePath: candidateRelatives[index],
            BaselineSize: int64(len(baselines[index])), BaselineSHA256: shadowDigest(baselines[index]),
            CandidateSize: int64(len(candidates[index])), CandidateSHA256: shadowDigest(candidates[index]),
        })
    }
    data, err := json.Marshal(request); if err != nil { t.Fatal(err) }
    path := filepath.Join(root, "request.json"); writeShadowFile(t, path, data); return path
}

func TestLegacyDLCShadowResolverReadyAllOrNone(t *testing.T) {
    root := t.TempDir(); game := filepath.Join(root, "game")
    request, err := loadLegacyDLCPreviewRequest(makeShadowRequest(t, root, game)); if err != nil { t.Fatal(err) }
    artifacts, ready := inspectLegacyDLCPreviewArtifacts(root, game, "quartet_legacy_dlc", request.ArtifactContract)
    if !ready || len(artifacts) != 2 { t.Fatalf("unexpected ready result: %v %+v", ready, artifacts) }
    for _, artifact := range artifacts { if !artifact.ReportVerified || !artifact.TransactionReady || artifact.Status != "ready" { t.Fatalf("unexpected artifact: %+v", artifact) } }
}

func TestLegacyDLCShadowResolverRejectsMissingCandidate(t *testing.T) {
    root := t.TempDir(); game := filepath.Join(root, "game")
    request, err := loadLegacyDLCPreviewRequest(makeShadowRequest(t, root, game)); if err != nil { t.Fatal(err) }
    if err := os.Remove(filepath.Join(root, filepath.FromSlash(request.ArtifactContract[1].CandidateRelativePath))); err != nil { t.Fatal(err) }
    artifacts, ready := inspectLegacyDLCPreviewArtifacts(root, game, "quartet_legacy_dlc", request.ArtifactContract)
    if ready || artifacts[0].TransactionReady || artifacts[1].TransactionReady { t.Fatalf("all-or-none gate failed: %+v", artifacts) }
}

func TestLegacyDLCShadowResolverRejectsTamperedCandidate(t *testing.T) {
    root := t.TempDir(); game := filepath.Join(root, "game")
    request, err := loadLegacyDLCPreviewRequest(makeShadowRequest(t, root, game)); if err != nil { t.Fatal(err) }
    writeShadowFile(t, filepath.Join(root, filepath.FromSlash(request.ArtifactContract[0].CandidateRelativePath)), []byte("tampered"))
    _, ready := inspectLegacyDLCPreviewArtifacts(root, game, "quartet_legacy_dlc", request.ArtifactContract)
    if ready { t.Fatal("tampered candidate was accepted") }
}

func TestLegacyDLCShadowResolverRejectsChangedBaseline(t *testing.T) {
    root := t.TempDir(); game := filepath.Join(root, "game")
    request, err := loadLegacyDLCPreviewRequest(makeShadowRequest(t, root, game)); if err != nil { t.Fatal(err) }
    writeShadowFile(t, filepath.Join(game, filepath.FromSlash(request.ArtifactContract[0].RelativePath)), []byte("changed"))
    _, ready := inspectLegacyDLCPreviewArtifacts(root, game, "quartet_legacy_dlc", request.ArtifactContract)
    if ready { t.Fatal("changed baseline was accepted") }
}

func TestLegacyDLCShadowRequestRejectsSingleArtifact(t *testing.T) {
    root := t.TempDir(); game := filepath.Join(root, "game")
    path := makeShadowRequest(t, root, game)
    var request legacyDLCPreviewRequest
    data, err := os.ReadFile(path); if err != nil { t.Fatal(err) }
    if err := json.Unmarshal(data, &request); err != nil { t.Fatal(err) }
    request.ArtifactContract = request.ArtifactContract[:1]
    data, _ = json.Marshal(request); writeShadowFile(t, path, data)
    if _, err := loadLegacyDLCPreviewRequest(path); err == nil { t.Fatal("single-artifact request was accepted") }
}

func TestLegacyDLCShadowResolverRejectsSymlinkCandidate(t *testing.T) {
    root := t.TempDir(); game := filepath.Join(root, "game")
    request, err := loadLegacyDLCPreviewRequest(makeShadowRequest(t, root, game)); if err != nil { t.Fatal(err) }
    path := filepath.Join(root, filepath.FromSlash(request.ArtifactContract[0].CandidateRelativePath))
    if err := os.Remove(path); err != nil { t.Fatal(err) }
    target := filepath.Join(root, "real-candidate"); writeShadowFile(t, target, []byte("candidate-10"))
    if err := os.Symlink(target, path); err != nil { t.Fatal(err) }
    _, ready := inspectLegacyDLCPreviewArtifacts(root, game, "quartet_legacy_dlc", request.ArtifactContract)
    if ready { t.Fatal("symlink candidate was accepted") }
}

func TestLegacyDLCShadowCatalogDeclaresExactArtifacts(t *testing.T) {
    specs, err := LoadCatalog(); if err != nil { t.Fatal(err) }
    for _, spec := range specs {
        if spec.ModuleID == "quartet_legacy_dlc" && spec.TargetID == "blue_reflection_quartet" {
            if spec.SourceKind != "validated_quartet_legacy_dlc_handoff" || spec.ConnectionStatus != "connected_preview_only" || len(spec.Artifacts) != 2 { t.Fatalf("unexpected spec: %+v", spec) }
            return
        }
    }
    t.Fatal("legacy DLC catalog mapping missing")
}
'''


def _copy_shadow_core(project_root: Path, shadow_root: Path) -> None:
    source = project_root / "Blue_Reflection_Patcher"
    if not source.is_dir():
        raise ShadowCoreRehearsalError("Blue_Reflection_Patcher source tree is missing")
    if shadow_root.exists():
        shutil.rmtree(shadow_root)
    shadow_root.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(source, shadow_root, symlinks=True, ignore=shutil.ignore_patterns(".git", "dist", "build", "*.exe"))


def _core_file_guards(project_root: Path, request: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for item in request.get("current_core_files", []):
        relative = item["path"]
        path = project_root / relative
        if not path.is_file():
            raise ShadowCoreRehearsalError(f"missing canonical core file: {relative}")
        actual_size = path.stat().st_size
        actual_sha = sha256_file(path)
        if actual_size != int(item["size"]) or actual_sha != item["sha256"]:
            raise ShadowCoreRehearsalError(f"canonical core file drifted since stage 70: {relative}")
        rows.append({"path": relative, "expected_size": item["size"], "actual_size": actual_size, "expected_sha256": item["sha256"], "actual_sha256": actual_sha, "unchanged_before_rehearsal": True, "unchanged_after_rehearsal": "pending"})
    return rows


def build_report(project_root: Path, contract_root: Path | None = None) -> Path:
    if contract_root is None:
        contract_root = project_root / ".local/reports/quartet_legacy_dlc/bkn_dry_payload_preview_contract_evidence"
    CONTRACT.validate_report(contract_root)
    request = _load_json(contract_root / "DLC_BKN_DRY_PAYLOAD_PREVIEW_PATCH_REQUEST.json")
    artifacts = validate_patch_request(request)
    guards = _core_file_guards(project_root, request)

    report_root = project_root / ".local/reports/quartet_legacy_dlc" / REPORT_DIR_NAME
    if report_root.exists():
        shutil.rmtree(report_root)
    report_root.mkdir(parents=True)
    shadow_root = project_root / Path(SHADOW_RELATIVE)
    _copy_shadow_core(project_root, shadow_root)

    catalog_path = shadow_root / "internal/plan/payloadpreview/catalog.json"
    before_catalog = patch_catalog(catalog_path, request["catalog_candidate"])
    prototype_path = shadow_root / "internal/plan/payloadpreview/legacy_dlc_shadow.go"
    test_path = shadow_root / "internal/plan/payloadpreview/legacy_dlc_shadow_test.go"
    prototype_path.write_text(prototype_go_source(), encoding="utf-8")
    test_path.write_text(prototype_go_test_source(), encoding="utf-8")

    gofmt = subprocess.run(["gofmt", "-w", str(prototype_path), str(test_path)], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if gofmt.returncode != 0:
        raise ShadowCoreRehearsalError(f"gofmt failed: {gofmt.stderr.strip()}")
    test_result = subprocess.run(["go", "test", "./internal/plan/payloadpreview", "-count=1", "-v"], cwd=shadow_root, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=180)
    if test_result.returncode != 0:
        raise ShadowCoreRehearsalError(f"shadow core Go tests failed: {test_result.stderr.strip()}\n{test_result.stdout.strip()}")

    for row in guards:
        path = project_root / row["path"]
        row["unchanged_after_rehearsal"] = path.stat().st_size == int(row["expected_size"]) and sha256_file(path) == row["expected_sha256"]
        if not row["unchanged_after_rehearsal"]:
            raise ShadowCoreRehearsalError(f"canonical core changed during rehearsal: {row['path']}")

    catalog_rows = [{
        "module_id": "quartet_legacy_dlc", "target_id": "blue_reflection_quartet",
        "before_source_kind": before_catalog.get("source_kind", ""),
        "before_connection_status": before_catalog.get("connection_status", ""),
        "before_artifact_count": len(before_catalog.get("artifacts", [])),
        "after_source_kind": request["catalog_candidate"]["source_kind"],
        "after_connection_status": request["catalog_candidate"]["connection_status"],
        "after_artifact_count": len(request["catalog_candidate"]["artifacts"]),
        "shadow_only": True,
    }]
    capability_names = [
        "exact_two_artifact_contract", "candidate_regular_file_hash_gate", "baseline_regular_file_hash_gate",
        "all_or_none_readiness", "single_artifact_rejection", "tampered_candidate_rejection",
        "changed_baseline_rejection", "symlink_candidate_rejection", "preview_only_authorization",
    ]
    capability_rows = [{"capability": name, "implemented_in_shadow": True, "wired_into_canonical_build": False, "transaction_call_made": False} for name in capability_names]
    test_lines = [line.strip() for line in test_result.stdout.splitlines() if line.startswith("--- PASS:")]
    go_test_rows = [{"package": "./internal/plan/payloadpreview", "test": line.split(":", 1)[1].strip().split(" ", 1)[0], "status": "pass"} for line in test_lines]
    shadow_files = []
    for path, role in ((catalog_path, "shadow_catalog"), (prototype_path, "shadow_unwired_resolver_prototype"), (test_path, "shadow_regression_tests")):
        shadow_files.append({"relative_path": path.relative_to(project_root).as_posix(), "role": role, "size": path.stat().st_size, "sha256": sha256_file(path), "canonical_core_modified": False})

    gaps = [
        {"dependency": "canonical_core_patch_application", "status": "not_applied_shadow_only", "blocks_preview_ready": True, "blocks_prepare": True, "required_action": "core orchestrator applies reviewed changes in its own workstream and returns Go-test plus payload-preview evidence"},
        {"dependency": "canonical_build_dispatch_wiring", "status": "prototype_not_wired", "blocks_preview_ready": True, "blocks_prepare": True, "required_action": "wire validated_quartet_legacy_dlc_handoff into payloadpreview.Build without loading translation provenance for DLC artifacts"},
        {"dependency": "explicit_operator_prepare_authorization", "status": "not_granted", "blocks_preview_ready": False, "blocks_prepare": True, "required_action": "obtain separately only after canonical preview integration review"},
        {"dependency": "runtime_validation_and_ui_availability", "status": "not_run", "blocks_preview_ready": False, "blocks_prepare": False, "required_action": "perform only after a separately approved reversible commit"},
        {"dependency": "wet_bkn_conversion", "status": "excluded_conversion_blocked", "blocks_preview_ready": False, "blocks_prepare": False, "required_action": "keep wet BKN outside the dry-only contract"},
    ]
    handoff = {
        "type": "br_quartet_legacy_dlc_shadow_core_rehearsal_handoff", "format_version": FORMAT_VERSION,
        "handoff_version": TOOL_VERSION, "content_id": request["content_id"], "request_id": request["request_id"],
        "input_request_version": request["request_version"], "shadow_rehearsal_passed": True,
        "shadow_core_relative_path": SHADOW_RELATIVE, "canonical_core_modified": False,
        "production_wiring_applied": False, "go_package_test_passed": True,
        "artifact_contract": artifacts, "catalog_candidate": request["catalog_candidate"],
        "required_core_changes": request["required_core_changes"], "requirements": request["requirements"],
        "next_owner": "core_orchestrator",
        "next_action": "review the shadow prototype and apply an equivalent dedicated resolver in the core workstream; return canonical payload-preview evidence; no transaction prepare or commit is authorized",
        "authorization": {
            "core_patch_applied": False, "canonical_core_modified": False, "candidate_installed": False,
            "real_transaction_prepare_enabled": False, "real_transaction_commit_enabled": False,
            "profile_build_allowed": False, "profile_registered": False, "runtime_validated": False,
            "wet_variant_included": False, "game_modified": False, "git_modified": False,
        },
    }

    write_tsv(report_root / "DLC_BKN_DRY_SHADOW_CORE_FILES.tsv", ["relative_path", "role", "size", "sha256", "canonical_core_modified"], shadow_files)
    write_tsv(report_root / "DLC_BKN_DRY_SHADOW_CATALOG_PATCH.tsv", ["module_id", "target_id", "before_source_kind", "before_connection_status", "before_artifact_count", "after_source_kind", "after_connection_status", "after_artifact_count", "shadow_only"], catalog_rows)
    write_tsv(report_root / "DLC_BKN_DRY_SHADOW_RESOLVER_CAPABILITIES.tsv", ["capability", "implemented_in_shadow", "wired_into_canonical_build", "transaction_call_made"], capability_rows)
    write_tsv(report_root / "DLC_BKN_DRY_SHADOW_GO_TESTS.tsv", ["package", "test", "status"], go_test_rows)
    write_tsv(report_root / "DLC_BKN_DRY_SHADOW_CANONICAL_CORE_GUARD.tsv", ["path", "expected_size", "actual_size", "expected_sha256", "actual_sha256", "unchanged_before_rehearsal", "unchanged_after_rehearsal"], guards)
    write_tsv(report_root / "DLC_BKN_DRY_SHADOW_REHEARSAL_GAPS.tsv", ["dependency", "status", "blocks_preview_ready", "blocks_prepare", "required_action"], gaps)
    write_json(report_root / "DLC_BKN_DRY_SHADOW_CORE_HANDOFF.json", handoff)
    summary = {
        "type": "br_quartet_legacy_dlc_bkn_dry_shadow_core_rehearsal_summary", "format_version": FORMAT_VERSION,
        "tool_version": TOOL_VERSION, "status": "shadow_core_resolver_rehearsal_passed_canonical_core_unchanged_not_wired_no_prepare_no_commit",
        "content_id": request["content_id"], "artifact_count": len(artifacts), "shadow_file_count": len(shadow_files),
        "shadow_capability_count": len(capability_rows), "go_test_count": len(go_test_rows), "blocking_preview_gaps": 2,
        "findings": [
            "the exact two-artifact catalog mapping loads and validates in the isolated shadow core",
            "the unwired handoff-backed resolver prototype enforces candidate and baseline hash gates plus all-or-none readiness",
            "missing, tampered, changed-baseline, single-artifact and symlink cases are rejected by Go tests",
            "the canonical core tree remains byte-identical and no transaction function is called",
        ],
        "next_action": handoff["next_action"],
        "policy": {
            "shadow_core_modified": True, "canonical_core_modified": False, "core_patch_applied": False,
            "real_transaction_prepared": False, "real_transaction_committed": False, "candidate_installed": False,
            "profile_build_allowed": False, "profile_registered": False, "runtime_validated": False,
            "wet_variant_included": False, "raw_assets_exported_in_report": False,
            "translation_modified": False, "restoration_modified": False, "game_modified": False, "git_modified": False,
        },
    }
    write_json(report_root / "SUMMARY.json", summary)
    write_json(report_root / "REPORT_MANIFEST.json", {"type": "br_report_manifest", "format_version": 1, "files": report_manifest(report_root)})
    validate_report(report_root)
    make_archive(report_root, project_root / ".local/reports/quartet_legacy_dlc" / REPORT_ARCHIVE_NAME)
    return report_root


def validate_report(report_root: Path) -> dict[str, Any]:
    summary = _load_json(report_root / "SUMMARY.json")
    if summary.get("tool_version") != TOOL_VERSION or summary.get("status") != "shadow_core_resolver_rehearsal_passed_canonical_core_unchanged_not_wired_no_prepare_no_commit":
        raise ShadowCoreRehearsalError("unexpected summary version/status")
    policy = summary.get("policy", {})
    if policy.get("shadow_core_modified") is not True:
        raise ShadowCoreRehearsalError("shadow core modification was not recorded")
    for key in ("canonical_core_modified", "core_patch_applied", "real_transaction_prepared", "real_transaction_committed", "candidate_installed", "profile_build_allowed", "profile_registered", "runtime_validated", "wet_variant_included", "raw_assets_exported_in_report", "translation_modified", "restoration_modified", "game_modified", "git_modified"):
        if policy.get(key) is not False:
            raise ShadowCoreRehearsalError(f"unsafe policy flag: {key}")
    guards = read_tsv(report_root / "DLC_BKN_DRY_SHADOW_CANONICAL_CORE_GUARD.tsv")
    if len(guards) != 6 or any(row.get("unchanged_after_rehearsal") != "true" for row in guards):
        raise ShadowCoreRehearsalError("canonical core guard failed")
    capabilities = read_tsv(report_root / "DLC_BKN_DRY_SHADOW_RESOLVER_CAPABILITIES.tsv")
    if len(capabilities) != 9 or any(row.get("implemented_in_shadow") != "true" or row.get("wired_into_canonical_build") != "false" or row.get("transaction_call_made") != "false" for row in capabilities):
        raise ShadowCoreRehearsalError("shadow resolver capability report is invalid")
    tests = read_tsv(report_root / "DLC_BKN_DRY_SHADOW_GO_TESTS.tsv")
    if len(tests) < 7 or any(row.get("status") != "pass" for row in tests):
        raise ShadowCoreRehearsalError("shadow Go tests are incomplete")
    handoff = _load_json(report_root / "DLC_BKN_DRY_SHADOW_CORE_HANDOFF.json")
    if handoff.get("shadow_rehearsal_passed") is not True or handoff.get("canonical_core_modified") is not False or handoff.get("production_wiring_applied") is not False:
        raise ShadowCoreRehearsalError("shadow handoff flags are invalid")
    manifest = _load_json(report_root / "REPORT_MANIFEST.json")
    expected = {row["path"]: (int(row["size"]), row["sha256"]) for row in manifest.get("files", [])}
    actual = {row["path"]: (int(row["size"]), row["sha256"]) for row in report_manifest(report_root)}
    if expected != actual:
        raise ShadowCoreRehearsalError("report manifest mismatch")
    return summary


def main() -> None:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    build = sub.add_parser("build-rehearsal")
    build.add_argument("--project-root", required=True)
    build.add_argument("--contract-root")
    validate = sub.add_parser("validate-report")
    validate.add_argument("--report-root", required=True)
    bundle = sub.add_parser("bundle-report")
    bundle.add_argument("--report-root", required=True)
    bundle.add_argument("--output", required=True)
    args = parser.parse_args()
    try:
        if args.command == "build-rehearsal":
            root = build_report(Path(args.project_root).resolve(), Path(args.contract_root).resolve() if args.contract_root else None)
            print(root)
        elif args.command == "validate-report":
            summary = validate_report(Path(args.report_root).resolve())
            print(json.dumps(summary, indent=2, sort_keys=True))
        else:
            root = Path(args.report_root).resolve(); validate_report(root); make_archive(root, Path(args.output).resolve()); print(Path(args.output).resolve())
    except (ShadowCoreRehearsalError, CONTRACT.BknDryPayloadPreviewContractError, OSError, subprocess.SubprocessError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
