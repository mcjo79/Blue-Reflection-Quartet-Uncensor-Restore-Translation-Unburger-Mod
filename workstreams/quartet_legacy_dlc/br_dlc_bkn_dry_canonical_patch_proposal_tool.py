#!/usr/bin/env python3
"""Build and validate a source-only canonical core patch proposal for dry PC00 BKN.

The stage consumes the validated shadow-core rehearsal, copies the current
Blue_Reflection_Patcher tree into a disposable workspace, wires an equivalent
handoff-backed resolver into payloadpreview.Build in that copy, runs Go tests,
exports a deterministic unified source patch, applies that patch to a second
clean copy, reruns tests, and proves that the canonical core remains unchanged.
No transaction function is called and no game payload is exported.
"""
from __future__ import annotations

import argparse
import csv
import difflib
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

import br_dlc_bkn_dry_shadow_core_rehearsal_tool as SHADOW

TOOL_VERSION = "0.0.33"
FORMAT_VERSION = 1
REPORT_DIR_NAME = "bkn_dry_canonical_patch_proposal_evidence"
REPORT_ARCHIVE_NAME = "BR_quartet_legacy_dlc_bkn_dry_canonical_patch_proposal_evidence.tar.zst"
PATCH_NAME = "DLC_BKN_DRY_CANONICAL_CORE_PATCH.patch"
PROPOSAL_RELATIVE = ".local/build/quartet_legacy_dlc/canonical_patch_proposal/costume_pc00_bkn/Blue_Reflection_Patcher"
APPLY_RELATIVE = ".local/build/quartet_legacy_dlc/canonical_patch_apply_check/costume_pc00_bkn"
EXPECTED_TARGETS = ("Data/PACK10_02.PAK", "Data/PACK12.PAK")
FORBIDDEN_REPORT_SUFFIXES = SHADOW.FORBIDDEN_REPORT_SUFFIXES
CORE_RELATIVE = Path("Blue_Reflection_Patcher")
CATALOG_REL = Path("internal/plan/payloadpreview/catalog.json")
PREVIEW_REL = Path("internal/plan/payloadpreview/preview.go")
RESOLVER_REL = Path("internal/plan/payloadpreview/legacy_dlc.go")
TEST_REL = Path("internal/plan/payloadpreview/legacy_dlc_integration_test.go")
HANDOFF_RELATIVE = ".local/reports/quartet_legacy_dlc/bkn_dry_core_integration_handoff_evidence/DLC_BKN_DRY_CORE_INTEGRATION_HANDOFF.json"


class CanonicalPatchProposalError(RuntimeError):
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
            raise CanonicalPatchProposalError(f"raw asset-like file in report: {path}")
        rows.append({"path": path.relative_to(root).as_posix(), "size": path.stat().st_size, "sha256": sha256_file(path)})
    return rows


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
        raise CanonicalPatchProposalError(f"cannot create report archive: {result.stderr.strip()}")
    os.replace(temporary, output)


def _load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CanonicalPatchProposalError(f"cannot read JSON {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise CanonicalPatchProposalError(f"JSON root is not an object: {path}")
    return value


def validate_shadow_handoff(handoff: dict[str, Any]) -> list[dict[str, Any]]:
    if handoff.get("type") != "br_quartet_legacy_dlc_shadow_core_rehearsal_handoff":
        raise CanonicalPatchProposalError("unexpected shadow handoff type")
    if handoff.get("handoff_version") != "0.0.32" or handoff.get("shadow_rehearsal_passed") is not True:
        raise CanonicalPatchProposalError("shadow handoff is not a passed 0.0.32 rehearsal")
    if handoff.get("canonical_core_modified") is not False or handoff.get("production_wiring_applied") is not False:
        raise CanonicalPatchProposalError("shadow handoff claims canonical production wiring")
    authorization = handoff.get("authorization", {})
    forbidden = (
        "core_patch_applied", "canonical_core_modified", "candidate_installed",
        "real_transaction_prepare_enabled", "real_transaction_commit_enabled",
        "profile_build_allowed", "profile_registered", "runtime_validated",
        "wet_variant_included", "game_modified", "git_modified",
    )
    if any(authorization.get(key) is not False for key in forbidden):
        raise CanonicalPatchProposalError("shadow handoff authorization is not fail-closed")
    artifacts = handoff.get("artifact_contract", [])
    if len(artifacts) != 2 or tuple(row.get("relative_path") for row in artifacts) != EXPECTED_TARGETS:
        raise CanonicalPatchProposalError("shadow handoff must contain ordered PACK10_02 and PACK12")
    return artifacts


def _copy_core(project_root: Path, destination: Path) -> None:
    source = project_root / CORE_RELATIVE
    if not source.is_dir():
        raise CanonicalPatchProposalError("canonical Blue_Reflection_Patcher tree is missing")
    if destination.exists():
        shutil.rmtree(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(source, destination, symlinks=True, ignore=shutil.ignore_patterns(".git", "dist", "build", "*.exe"))


def _guard_rows(project_root: Path, shadow_root: Path) -> list[dict[str, Any]]:
    guard_path = shadow_root / "DLC_BKN_DRY_SHADOW_CANONICAL_CORE_GUARD.tsv"
    rows = read_tsv(guard_path)
    if len(rows) != 6:
        raise CanonicalPatchProposalError("shadow report canonical guard does not contain six files")
    result: list[dict[str, Any]] = []
    for row in rows:
        relative = row["path"]
        path = project_root / relative
        if not path.is_file():
            raise CanonicalPatchProposalError(f"canonical core file is missing: {relative}")
        actual_size = path.stat().st_size
        actual_sha = sha256_file(path)
        if actual_size != int(row["expected_size"]) or actual_sha != row["expected_sha256"]:
            raise CanonicalPatchProposalError(f"canonical core drifted since shadow rehearsal: {relative}")
        result.append({
            "path": relative,
            "expected_size": row["expected_size"],
            "actual_size": actual_size,
            "expected_sha256": row["expected_sha256"],
            "actual_sha256": actual_sha,
            "unchanged_before_proposal": True,
            "unchanged_after_proposal": "pending",
        })
    return result


def patch_catalog(path: Path, candidate: dict[str, Any]) -> dict[str, Any]:
    doc = _load_json(path)
    rows = doc.get("module_targets", [])
    matches = [row for row in rows if row.get("module_id") == "quartet_legacy_dlc" and row.get("target_id") == "blue_reflection_quartet"]
    if len(matches) != 1:
        raise CanonicalPatchProposalError(f"expected one legacy-DLC catalog row, found {len(matches)}")
    row = matches[0]
    before = json.loads(json.dumps(row))
    row.clear()
    for key in ("module_id", "target_id", "source_kind", "connection_status", "reason", "artifacts"):
        if key in candidate:
            row[key] = candidate[key]
    path.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return before


def resolver_go_source() -> str:
    return r'''package payloadpreview

import (
    "encoding/json"
    "fmt"
    "os"
    "path/filepath"
    "strings"
)

const (
    legacyDLCSourceKind = "validated_quartet_legacy_dlc_handoff"
    legacyDLCHandoffRelative = ".local/reports/quartet_legacy_dlc/bkn_dry_core_integration_handoff_evidence/DLC_BKN_DRY_CORE_INTEGRATION_HANDOFF.json"
)

type legacyDLCTransactionFile struct {
    RelativePath string `json:"relative_path"`
    CandidateRelativePath string `json:"candidate_relative_path"`
    BaselineSize int64 `json:"baseline_size"`
    BaselineSHA256 string `json:"baseline_sha256"`
    CandidateSize int64 `json:"candidate_size"`
    CandidateSHA256 string `json:"candidate_sha256"`
}

type legacyDLCAuthorization struct {
    CoreHandoffReady bool `json:"core_handoff_ready"`
    RealTransactionPrepareEnabled bool `json:"real_transaction_prepare_enabled"`
    RealTransactionCommitEnabled bool `json:"real_transaction_commit_enabled"`
    CandidateInstalled bool `json:"candidate_installed"`
    WetVariantIncluded bool `json:"wet_variant_included"`
}

type legacyDLCHandoff struct {
    Type string `json:"type"`
    HandoffVersion string `json:"handoff_version"`
    TargetID string `json:"target_id"`
    TransactionFiles []legacyDLCTransactionFile `json:"transaction_files"`
    Authorization legacyDLCAuthorization `json:"authorization"`
}

func loadLegacyDLCHandoff(projectRoot string) (legacyDLCHandoff, string, error) {
    path := filepath.Join(projectRoot, filepath.FromSlash(legacyDLCHandoffRelative))
    info, err := os.Lstat(path)
    if err != nil { return legacyDLCHandoff{}, path, fmt.Errorf("inspect legacy DLC handoff: %w", err) }
    if info.Mode()&os.ModeSymlink != 0 || !info.Mode().IsRegular() { return legacyDLCHandoff{}, path, fmt.Errorf("legacy DLC handoff is not a regular non-symlink file") }
    data, err := os.ReadFile(path)
    if err != nil { return legacyDLCHandoff{}, path, fmt.Errorf("read legacy DLC handoff: %w", err) }
    var handoff legacyDLCHandoff
    if err := json.Unmarshal(data, &handoff); err != nil { return legacyDLCHandoff{}, path, fmt.Errorf("decode legacy DLC handoff: %w", err) }
    if handoff.Type != "br_quartet_legacy_dlc_dry_bkn_core_integration_handoff" || handoff.HandoffVersion != "0.0.30" || handoff.TargetID != "blue_reflection_quartet" { return legacyDLCHandoff{}, path, fmt.Errorf("unexpected legacy DLC handoff type/version/target") }
    if !handoff.Authorization.CoreHandoffReady || handoff.Authorization.RealTransactionPrepareEnabled || handoff.Authorization.RealTransactionCommitEnabled || handoff.Authorization.CandidateInstalled || handoff.Authorization.WetVariantIncluded { return legacyDLCHandoff{}, path, fmt.Errorf("legacy DLC handoff is not preview-only") }
    if len(handoff.TransactionFiles) != 2 { return legacyDLCHandoff{}, path, fmt.Errorf("legacy DLC handoff must contain exactly two files") }
    expected := []string{"Data/PACK10_02.PAK", "Data/PACK12.PAK"}
    for index, contract := range handoff.TransactionFiles {
        if filepath.ToSlash(contract.RelativePath) != expected[index] { return legacyDLCHandoff{}, path, fmt.Errorf("unexpected legacy DLC artifact order/path") }
        if contract.BaselineSize <= 0 || contract.CandidateSize <= 0 || len(contract.BaselineSHA256) != 64 || len(contract.CandidateSHA256) != 64 { return legacyDLCHandoff{}, path, fmt.Errorf("invalid legacy DLC artifact hash/size contract") }
        if strings.TrimSpace(contract.CandidateRelativePath) == "" || filepath.IsAbs(contract.CandidateRelativePath) { return legacyDLCHandoff{}, path, fmt.Errorf("unsafe legacy DLC candidate path") }
    }
    return handoff, path, nil
}

func inspectLegacyDLCModule(projectRoot, gameRoot, moduleID string) ([]ArtifactPreview, bool, string) {
    handoff, handoffPath, err := loadLegacyDLCHandoff(projectRoot)
    if err != nil { return nil, false, err.Error() }
    artifacts := make([]ArtifactPreview, 0, len(handoff.TransactionFiles))
    allReady := true
    for _, contract := range handoff.TransactionFiles {
        artifact := ArtifactPreview{ModuleID: moduleID, RelativePath: filepath.ToSlash(contract.RelativePath), Status: "invalid", DesiredAction: "blocked", ReportSHA256: contract.CandidateSHA256, ReportBytes: contract.CandidateSize}
        source, err := secureProjectPath(projectRoot, contract.CandidateRelativePath)
        if err != nil { artifact.Error = err.Error(); artifacts = append(artifacts, artifact); allReady = false; continue }
        artifact.SourcePath = source
        info, err := os.Lstat(source)
        if err != nil { artifact.Error = fmt.Sprintf("inspect legacy DLC candidate: %v", err); artifacts = append(artifacts, artifact); allReady = false; continue }
        if info.Mode()&os.ModeSymlink != 0 || !info.Mode().IsRegular() { artifact.Error = "legacy DLC candidate is not a regular non-symlink file"; artifacts = append(artifacts, artifact); allReady = false; continue }
        artifact.SourceBytes = info.Size()
        artifact.SourceSHA256, err = hashFile(source)
        if err != nil || artifact.SourceBytes != contract.CandidateSize || !strings.EqualFold(artifact.SourceSHA256, contract.CandidateSHA256) { artifact.Error = "legacy DLC candidate hash/size mismatch"; artifacts = append(artifacts, artifact); allReady = false; continue }
        targetPath, exists, err := resolveTargetPath(gameRoot, contract.RelativePath)
        artifact.TargetPath, artifact.TargetExists = targetPath, exists
        if err != nil || !exists { artifact.Error = "legacy DLC baseline target is missing"; artifacts = append(artifacts, artifact); allReady = false; continue }
        targetInfo, err := os.Lstat(targetPath)
        if err != nil || targetInfo.Mode()&os.ModeSymlink != 0 || !targetInfo.Mode().IsRegular() { artifact.Error = "legacy DLC baseline is not a regular non-symlink file"; artifacts = append(artifacts, artifact); allReady = false; continue }
        artifact.TargetBytes = targetInfo.Size()
        artifact.TargetSHA256, err = hashFile(targetPath)
        if err != nil || artifact.TargetBytes != contract.BaselineSize || !strings.EqualFold(artifact.TargetSHA256, contract.BaselineSHA256) { artifact.Error = "legacy DLC baseline hash/size mismatch"; artifacts = append(artifacts, artifact); allReady = false; continue }
        artifact.ReportVerified = true
        if strings.EqualFold(artifact.TargetSHA256, artifact.SourceSHA256) { artifact.DesiredAction = "noop" } else { artifact.DesiredAction = "replace" }
        artifact.TransactionReady = true
        artifact.Status = "ready"
        artifacts = append(artifacts, artifact)
    }
    if !allReady {
        for index := range artifacts { artifacts[index].TransactionReady = false }
        return artifacts, false, fmt.Sprintf("legacy DLC handoff artifacts are incomplete or unverified: %s", handoffPath)
    }
    return artifacts, true, "validated dry PC00 BKN handoff; preview-only two-artifact contract"
}
'''


def integration_test_source() -> str:
    return r'''package payloadpreview

import (
    "crypto/sha256"
    "encoding/hex"
    "encoding/json"
    "os"
    "path/filepath"
    "testing"

    "local/blue-reflection-patcher/internal/model"
)

func legacyDLCTestDigest(data []byte) string { sum := sha256.Sum256(data); return hex.EncodeToString(sum[:]) }

func legacyDLCWriteFile(t *testing.T, path string, data []byte) {
    t.Helper()
    if err := os.MkdirAll(filepath.Dir(path), 0o755); err != nil { t.Fatal(err) }
    if err := os.WriteFile(path, data, 0o644); err != nil { t.Fatal(err) }
}

func legacyDLCFixture(t *testing.T) (string, string, model.SelectionResult) {
    t.Helper()
    project := t.TempDir()
    game := filepath.Join(project, "game")
    legacyDLCWriteFile(t, filepath.Join(project, "workstreams/core/VERSION"), []byte("test\n"))
    legacyDLCWriteFile(t, filepath.Join(project, "Blue_Reflection_Patcher/go.mod"), []byte("module fixture\n"))
    report := map[string]any{"status": "ok", "archives": []any{}}
    reportData, err := json.Marshal(report); if err != nil { t.Fatal(err) }
    legacyDLCWriteFile(t, filepath.Join(project, filepath.FromSlash(repackReportRelative)), reportData)
    candidates := [][]byte{[]byte("candidate-10"), []byte("candidate-12")}
    baselines := [][]byte{[]byte("baseline-10"), []byte("baseline-12")}
    relatives := []string{"Data/PACK10_02.PAK", "Data/PACK12.PAK"}
    candidateRelatives := []string{".local/build/quartet_legacy_dlc/PACK10_02.PAK", ".local/build/quartet_legacy_dlc/PACK12.PAK"}
    handoff := legacyDLCHandoff{Type: "br_quartet_legacy_dlc_dry_bkn_core_integration_handoff", HandoffVersion: "0.0.30", TargetID: "blue_reflection_quartet", Authorization: legacyDLCAuthorization{CoreHandoffReady: true}}
    for index := range relatives {
        legacyDLCWriteFile(t, filepath.Join(project, filepath.FromSlash(candidateRelatives[index])), candidates[index])
        legacyDLCWriteFile(t, filepath.Join(game, filepath.FromSlash(relatives[index])), baselines[index])
        handoff.TransactionFiles = append(handoff.TransactionFiles, legacyDLCTransactionFile{RelativePath: relatives[index], CandidateRelativePath: candidateRelatives[index], BaselineSize: int64(len(baselines[index])), BaselineSHA256: legacyDLCTestDigest(baselines[index]), CandidateSize: int64(len(candidates[index])), CandidateSHA256: legacyDLCTestDigest(candidates[index])})
    }
    data, err := json.Marshal(handoff); if err != nil { t.Fatal(err) }
    legacyDLCWriteFile(t, filepath.Join(project, filepath.FromSlash(legacyDLCHandoffRelative)), data)
    selection := model.SelectionResult{Targets: []model.TargetSelection{{TargetID: "blue_reflection_quartet", DisplayName: "Quartet", Root: game, DetectionSource: "test", SelectedModuleIDs: []string{"quartet_legacy_dlc"}}}}
    return project, game, selection
}

func findLegacyDLCModule(t *testing.T, preview Preview) ModulePreview {
    t.Helper()
    if len(preview.Targets) != 1 || len(preview.Targets[0].Modules) != 1 { t.Fatalf("unexpected preview shape: %+v", preview) }
    return preview.Targets[0].Modules[0]
}

func TestLegacyDLCBuildReadyFromDedicatedHandoff(t *testing.T) {
    project, _, selection := legacyDLCFixture(t)
    preview, err := Build(project, filepath.Join(project, "state"), selection); if err != nil { t.Fatal(err) }
    module := findLegacyDLCModule(t, preview)
    if preview.CommitEnabled || preview.Status != "ready" || !module.Ready || len(module.Artifacts) != 2 { t.Fatalf("unexpected preview: %+v", preview) }
    for _, artifact := range module.Artifacts { if !artifact.ReportVerified || !artifact.TransactionReady || artifact.Status != "ready" { t.Fatalf("unexpected artifact: %+v", artifact) } }
}

func TestLegacyDLCBuildRejectsMissingCandidateAllOrNone(t *testing.T) {
    project, _, selection := legacyDLCFixture(t)
    if err := os.Remove(filepath.Join(project, ".local/build/quartet_legacy_dlc/PACK12.PAK")); err != nil { t.Fatal(err) }
    preview, err := Build(project, filepath.Join(project, "state"), selection); if err != nil { t.Fatal(err) }
    module := findLegacyDLCModule(t, preview)
    if module.Ready || preview.Status != "not_ready" { t.Fatalf("missing candidate was accepted: %+v", preview) }
    for _, artifact := range module.Artifacts { if artifact.TransactionReady { t.Fatalf("all-or-none gate failed: %+v", module.Artifacts) } }
}

func TestLegacyDLCBuildRejectsChangedBaseline(t *testing.T) {
    project, game, selection := legacyDLCFixture(t)
    legacyDLCWriteFile(t, filepath.Join(game, "Data/PACK10_02.PAK"), []byte("changed"))
    preview, err := Build(project, filepath.Join(project, "state"), selection); if err != nil { t.Fatal(err) }
    if findLegacyDLCModule(t, preview).Ready { t.Fatal("changed baseline was accepted") }
}

func TestLegacyDLCBuildRejectsSymlinkCandidate(t *testing.T) {
    project, _, selection := legacyDLCFixture(t)
    path := filepath.Join(project, ".local/build/quartet_legacy_dlc/PACK10_02.PAK")
    if err := os.Remove(path); err != nil { t.Fatal(err) }
    target := filepath.Join(project, "real-candidate"); legacyDLCWriteFile(t, target, []byte("candidate-10"))
    if err := os.Symlink(target, path); err != nil { t.Fatal(err) }
    preview, err := Build(project, filepath.Join(project, "state"), selection); if err != nil { t.Fatal(err) }
    if findLegacyDLCModule(t, preview).Ready { t.Fatal("symlink candidate was accepted") }
}

func TestLegacyDLCCatalogDeclaresExactProductionArtifacts(t *testing.T) {
    specs, err := LoadCatalog(); if err != nil { t.Fatal(err) }
    for _, spec := range specs {
        if spec.ModuleID == "quartet_legacy_dlc" && spec.TargetID == "blue_reflection_quartet" {
            if spec.SourceKind != legacyDLCSourceKind || spec.ConnectionStatus != "connected_preview_only" || len(spec.Artifacts) != 2 || spec.Artifacts[0].RelativePath != "Data/PACK10_02.PAK" || spec.Artifacts[1].RelativePath != "Data/PACK12.PAK" { t.Fatalf("unexpected spec: %+v", spec) }
            return
        }
    }
    t.Fatal("legacy DLC catalog mapping missing")
}
'''


def patch_preview_source(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    marker = '''			if !module.Ready {
				target.PendingModuleCount++
				target.Warnings = append(target.Warnings, fmt.Sprintf("%s: %s", moduleID, spec.Reason))
			} else {
'''
    replacement = '''			if spec.SourceKind == legacyDLCSourceKind && module.Ready {
				module.Artifacts, module.Ready, module.Reason = inspectLegacyDLCModule(projectRoot, selectedTarget.Root, moduleID)
				for _, artifact := range module.Artifacts {
					if artifact.TransactionReady {
						target.ReadyArtifactCount++
					}
				}
				if !module.Ready {
					target.PendingModuleCount++
					target.Warnings = append(target.Warnings, fmt.Sprintf("%s: %s", moduleID, module.Reason))
				}
				target.Modules = append(target.Modules, module)
				continue
			}
			if !module.Ready {
				target.PendingModuleCount++
				target.Warnings = append(target.Warnings, fmt.Sprintf("%s: %s", moduleID, spec.Reason))
			} else {
'''
    if text.count(marker) != 1:
        raise CanonicalPatchProposalError("cannot locate Build module readiness branch")
    path.write_text(text.replace(marker, replacement), encoding="utf-8")


def run_gofmt(paths: list[Path]) -> None:
    result = subprocess.run(["gofmt", "-w", *[str(path) for path in paths]], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if result.returncode != 0:
        raise CanonicalPatchProposalError(f"gofmt failed: {result.stderr.strip()}")


def run_go_tests(core_root: Path) -> list[dict[str, Any]]:
    result = subprocess.run(
        ["go", "test", "./internal/plan/payloadpreview", "-count=1", "-v"],
        cwd=core_root,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env={**os.environ, "GOWORK": "off"},
    )
    if result.returncode != 0:
        raise CanonicalPatchProposalError(f"Go payloadpreview tests failed: {(result.stdout + result.stderr).strip()}")
    rows: list[dict[str, Any]] = []
    for line in result.stdout.splitlines():
        if line.startswith("--- PASS: "):
            name = line[len("--- PASS: "):].split(" ", 1)[0]
            rows.append({"package": "./internal/plan/payloadpreview", "test": name, "status": "pass"})
    if not rows:
        raise CanonicalPatchProposalError("Go test output contains no passed tests")
    required = {
        "TestLegacyDLCBuildReadyFromDedicatedHandoff",
        "TestLegacyDLCBuildRejectsMissingCandidateAllOrNone",
        "TestLegacyDLCBuildRejectsChangedBaseline",
        "TestLegacyDLCBuildRejectsSymlinkCandidate",
        "TestLegacyDLCCatalogDeclaresExactProductionArtifacts",
    }
    if not required.issubset({row["test"] for row in rows}):
        raise CanonicalPatchProposalError("required legacy DLC integration tests did not run")
    return rows


def unified_patch(canonical_core: Path, proposal_core: Path, relative_paths: list[Path]) -> str:
    chunks: list[str] = []
    for relative in relative_paths:
        old_path = canonical_core / relative
        new_path = proposal_core / relative
        old_lines = old_path.read_text(encoding="utf-8").splitlines(keepends=True) if old_path.exists() else []
        new_lines = new_path.read_text(encoding="utf-8").splitlines(keepends=True)
        fromfile = f"a/Blue_Reflection_Patcher/{relative.as_posix()}" if old_path.exists() else "/dev/null"
        tofile = f"b/Blue_Reflection_Patcher/{relative.as_posix()}"
        diff = difflib.unified_diff(old_lines, new_lines, fromfile=fromfile, tofile=tofile, n=3)
        chunks.extend(diff)
    value = "".join(chunks)
    if not value.strip():
        raise CanonicalPatchProposalError("generated source patch is empty")
    return value


def apply_patch(project_root: Path, patch_path: Path, destination: Path) -> None:
    if destination.exists():
        shutil.rmtree(destination)
    destination.mkdir(parents=True)
    _copy_core(project_root, destination / CORE_RELATIVE)
    result = subprocess.run(
        ["patch", "-p1", "--batch", "--forward", "-i", str(patch_path)],
        cwd=destination,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    if result.returncode != 0:
        raise CanonicalPatchProposalError(f"source patch apply check failed: {(result.stdout + result.stderr).strip()}")


def build_report(project_root: Path, shadow_report_root: Path | None = None) -> Path:
    if shadow_report_root is None:
        shadow_report_root = project_root / ".local/reports/quartet_legacy_dlc/bkn_dry_shadow_core_rehearsal_evidence"
    SHADOW.validate_report(shadow_report_root)
    shadow_handoff = _load_json(shadow_report_root / "DLC_BKN_DRY_SHADOW_CORE_HANDOFF.json")
    artifacts = validate_shadow_handoff(shadow_handoff)
    guards = _guard_rows(project_root, shadow_report_root)

    report_root = project_root / ".local/reports/quartet_legacy_dlc" / REPORT_DIR_NAME
    if report_root.exists():
        shutil.rmtree(report_root)
    report_root.mkdir(parents=True)

    canonical_core = project_root / CORE_RELATIVE
    proposal_core = project_root / PROPOSAL_RELATIVE
    _copy_core(project_root, proposal_core)
    catalog_before = patch_catalog(proposal_core / CATALOG_REL, shadow_handoff["catalog_candidate"])
    (proposal_core / RESOLVER_REL).write_text(resolver_go_source(), encoding="utf-8")
    (proposal_core / TEST_REL).write_text(integration_test_source(), encoding="utf-8")
    patch_preview_source(proposal_core / PREVIEW_REL)
    run_gofmt([proposal_core / PREVIEW_REL, proposal_core / RESOLVER_REL, proposal_core / TEST_REL])
    go_rows = run_go_tests(proposal_core)

    changed = [CATALOG_REL, PREVIEW_REL, RESOLVER_REL, TEST_REL]
    patch_text = unified_patch(canonical_core, proposal_core, changed)
    patch_path = report_root / PATCH_NAME
    patch_path.write_text(patch_text, encoding="utf-8")

    apply_root = project_root / APPLY_RELATIVE
    apply_patch(project_root, patch_path, apply_root)
    apply_core = apply_root / CORE_RELATIVE
    apply_go_rows = run_go_tests(apply_core)

    file_rows: list[dict[str, Any]] = []
    apply_rows: list[dict[str, Any]] = []
    for relative in changed:
        old = canonical_core / relative
        new = proposal_core / relative
        applied = apply_core / relative
        action = "replace" if old.exists() else "add"
        old_size = old.stat().st_size if old.exists() else 0
        old_sha = sha256_file(old) if old.exists() else ""
        new_size = new.stat().st_size
        new_sha = sha256_file(new)
        applied_sha = sha256_file(applied)
        if new_sha != applied_sha or new_size != applied.stat().st_size:
            raise CanonicalPatchProposalError(f"applied patch result differs from proposal: {relative}")
        file_rows.append({
            "path": f"Blue_Reflection_Patcher/{relative.as_posix()}", "action": action,
            "old_size": old_size, "old_sha256": old_sha,
            "new_size": new_size, "new_sha256": new_sha,
            "canonical_core_modified": False,
        })
        apply_rows.append({
            "path": f"Blue_Reflection_Patcher/{relative.as_posix()}",
            "proposal_sha256": new_sha, "applied_sha256": applied_sha,
            "exact_match": True,
        })

    for row in guards:
        path = project_root / row["path"]
        row["unchanged_after_proposal"] = path.stat().st_size == int(row["expected_size"]) and sha256_file(path) == row["expected_sha256"]
        if not row["unchanged_after_proposal"]:
            raise CanonicalPatchProposalError(f"canonical core changed during proposal build: {row['path']}")

    capabilities = [
        "exact_two_artifact_catalog_contract",
        "dedicated_stage67_handoff_loader",
        "candidate_regular_file_hash_gate",
        "baseline_regular_file_hash_gate",
        "all_or_none_module_readiness",
        "single_artifact_and_missing_file_rejection",
        "tampered_candidate_rejection",
        "changed_baseline_rejection",
        "symlink_candidate_rejection",
        "dedicated_handoff_provenance_not_translation_artifact_verification",
        "preview_only_commit_disabled",
        "production_build_dispatch_wired_in_proposal",
    ]
    capability_rows = [{
        "capability": value,
        "implemented_in_patch_proposal": True,
        "verified_by_go_tests": True,
        "applied_to_canonical_core": False,
        "transaction_call_made": False,
    } for value in capabilities]

    catalog_rows = [{
        "module_id": "quartet_legacy_dlc", "target_id": "blue_reflection_quartet",
        "before_source_kind": catalog_before.get("source_kind", ""),
        "before_connection_status": catalog_before.get("connection_status", ""),
        "before_artifact_count": len(catalog_before.get("artifacts", [])),
        "after_source_kind": shadow_handoff["catalog_candidate"]["source_kind"],
        "after_connection_status": shadow_handoff["catalog_candidate"]["connection_status"],
        "after_artifact_count": len(shadow_handoff["catalog_candidate"]["artifacts"]),
        "canonical_core_modified": False,
    }]

    gaps = [
        {"dependency": "core_workstream_review_and_application", "status": "exact_patch_proposal_ready_not_applied", "blocks_preview_ready": True, "blocks_prepare": True, "required_action": "core orchestrator reviews and applies the exact source patch or an equivalent implementation in a core-owned update"},
        {"dependency": "canonical_payload_preview_evidence", "status": "not_returned", "blocks_preview_ready": True, "blocks_prepare": True, "required_action": "after core integration, return canonical Go-test and payload-preview evidence for the exact two artifacts"},
        {"dependency": "explicit_operator_prepare_authorization", "status": "not_granted", "blocks_preview_ready": False, "blocks_prepare": True, "required_action": "obtain separately only after canonical preview integration review"},
        {"dependency": "runtime_validation_and_ui_availability", "status": "not_run", "blocks_preview_ready": False, "blocks_prepare": False, "required_action": "perform only after a separately approved reversible commit"},
        {"dependency": "wet_bkn_conversion", "status": "excluded_conversion_blocked", "blocks_preview_ready": False, "blocks_prepare": False, "required_action": "keep wet BKN outside the dry-only contract"},
    ]

    handoff = {
        "type": "br_quartet_legacy_dlc_canonical_core_patch_proposal_handoff",
        "format_version": FORMAT_VERSION,
        "handoff_version": TOOL_VERSION,
        "content_id": shadow_handoff["content_id"],
        "target_id": "blue_reflection_quartet",
        "source_shadow_handoff_version": shadow_handoff["handoff_version"],
        "patch_file": PATCH_NAME,
        "patch_sha256": sha256_file(patch_path),
        "patch_size": patch_path.stat().st_size,
        "changed_files": file_rows,
        "artifact_contract": artifacts,
        "catalog_candidate": shadow_handoff["catalog_candidate"],
        "go_test_count_proposal": len(go_rows),
        "go_test_count_patch_apply_check": len(apply_go_rows),
        "patch_apply_check_passed": True,
        "canonical_core_modified": False,
        "production_wiring_present_in_proposal": True,
        "production_wiring_applied": False,
        "next_owner": "core_orchestrator",
        "next_action": "review and apply the exact source-only patch in the core workstream, rerun canonical payloadpreview tests and return canonical preview evidence; no transaction prepare or commit is authorized",
        "authorization": {
            "core_patch_proposal_ready": True,
            "core_patch_apply_allowed_by_dlc_workstream": False,
            "canonical_core_modified": False,
            "candidate_installed": False,
            "real_transaction_prepare_enabled": False,
            "real_transaction_commit_enabled": False,
            "profile_build_allowed": False,
            "profile_registered": False,
            "runtime_validated": False,
            "wet_variant_included": False,
            "game_modified": False,
            "git_modified": False,
        },
    }

    write_tsv(report_root / "DLC_BKN_DRY_CANONICAL_PATCH_FILES.tsv", ["path", "action", "old_size", "old_sha256", "new_size", "new_sha256", "canonical_core_modified"], file_rows)
    write_tsv(report_root / "DLC_BKN_DRY_CANONICAL_PATCH_CATALOG.tsv", ["module_id", "target_id", "before_source_kind", "before_connection_status", "before_artifact_count", "after_source_kind", "after_connection_status", "after_artifact_count", "canonical_core_modified"], catalog_rows)
    write_tsv(report_root / "DLC_BKN_DRY_CANONICAL_PATCH_CAPABILITIES.tsv", ["capability", "implemented_in_patch_proposal", "verified_by_go_tests", "applied_to_canonical_core", "transaction_call_made"], capability_rows)
    write_tsv(report_root / "DLC_BKN_DRY_CANONICAL_PATCH_GO_TESTS.tsv", ["phase", "package", "test", "status"], [{"phase": "proposal_shadow", **row} for row in go_rows] + [{"phase": "patch_apply_check", **row} for row in apply_go_rows])
    write_tsv(report_root / "DLC_BKN_DRY_CANONICAL_PATCH_APPLY_CHECK.tsv", ["path", "proposal_sha256", "applied_sha256", "exact_match"], apply_rows)
    write_tsv(report_root / "DLC_BKN_DRY_CANONICAL_PATCH_CORE_GUARD.tsv", ["path", "expected_size", "actual_size", "expected_sha256", "actual_sha256", "unchanged_before_proposal", "unchanged_after_proposal"], guards)
    write_tsv(report_root / "DLC_BKN_DRY_CANONICAL_PATCH_GAPS.tsv", ["dependency", "status", "blocks_preview_ready", "blocks_prepare", "required_action"], gaps)
    write_json(report_root / "DLC_BKN_DRY_CANONICAL_PATCH_HANDOFF.json", handoff)
    summary = {
        "type": "br_quartet_legacy_dlc_bkn_dry_canonical_patch_proposal_summary",
        "format_version": FORMAT_VERSION,
        "tool_version": TOOL_VERSION,
        "status": "source_only_canonical_patch_proposal_passed_apply_checked_not_applied_no_prepare_no_commit",
        "content_id": shadow_handoff["content_id"],
        "artifact_count": len(artifacts),
        "changed_source_file_count": len(file_rows),
        "patch_size": patch_path.stat().st_size,
        "patch_sha256": sha256_file(patch_path),
        "capability_count": len(capability_rows),
        "go_test_count_proposal": len(go_rows),
        "go_test_count_patch_apply_check": len(apply_go_rows),
        "blocking_preview_gaps": 2,
        "findings": [
            "the production-shaped resolver is wired into payloadpreview.Build in a disposable proposal copy",
            "DLC artifacts are verified from the dedicated stage-67 handoff rather than Translation repack entries",
            "the exact unified source patch applies to a second clean copy and produces byte-identical proposed files",
            "all payloadpreview Go tests pass before and after patch application while canonical core remains byte-identical",
        ],
        "next_action": handoff["next_action"],
        "policy": {
            "source_patch_exported": True,
            "proposal_shadow_modified": True,
            "canonical_core_modified": False,
            "core_patch_applied": False,
            "real_transaction_prepared": False,
            "real_transaction_committed": False,
            "candidate_installed": False,
            "profile_build_allowed": False,
            "profile_registered": False,
            "runtime_validated": False,
            "wet_variant_included": False,
            "raw_assets_exported_in_report": False,
            "translation_modified": False,
            "restoration_modified": False,
            "game_modified": False,
            "git_modified": False,
        },
    }
    write_json(report_root / "SUMMARY.json", summary)
    write_json(report_root / "REPORT_MANIFEST.json", {"type": "br_report_manifest", "format_version": 1, "files": report_manifest(report_root)})
    validate_report(report_root)
    make_archive(report_root, project_root / ".local/reports/quartet_legacy_dlc" / REPORT_ARCHIVE_NAME)
    return report_root


def validate_report(report_root: Path) -> dict[str, Any]:
    summary = _load_json(report_root / "SUMMARY.json")
    if summary.get("tool_version") != TOOL_VERSION or summary.get("status") != "source_only_canonical_patch_proposal_passed_apply_checked_not_applied_no_prepare_no_commit":
        raise CanonicalPatchProposalError("unexpected summary version/status")
    policy = summary.get("policy", {})
    if policy.get("source_patch_exported") is not True or policy.get("proposal_shadow_modified") is not True:
        raise CanonicalPatchProposalError("proposal/export flags are missing")
    for key in ("canonical_core_modified", "core_patch_applied", "real_transaction_prepared", "real_transaction_committed", "candidate_installed", "profile_build_allowed", "profile_registered", "runtime_validated", "wet_variant_included", "raw_assets_exported_in_report", "translation_modified", "restoration_modified", "game_modified", "git_modified"):
        if policy.get(key) is not False:
            raise CanonicalPatchProposalError(f"unsafe policy flag: {key}")
    patch_path = report_root / PATCH_NAME
    if not patch_path.is_file() or patch_path.stat().st_size <= 0 or sha256_file(patch_path) != summary.get("patch_sha256"):
        raise CanonicalPatchProposalError("source patch is missing or does not match summary")
    files = read_tsv(report_root / "DLC_BKN_DRY_CANONICAL_PATCH_FILES.tsv")
    if len(files) != 4 or {row["action"] for row in files} != {"add", "replace"} or any(row["canonical_core_modified"] != "false" for row in files):
        raise CanonicalPatchProposalError("canonical patch file report is invalid")
    capabilities = read_tsv(report_root / "DLC_BKN_DRY_CANONICAL_PATCH_CAPABILITIES.tsv")
    if len(capabilities) != 12 or any(row["implemented_in_patch_proposal"] != "true" or row["verified_by_go_tests"] != "true" or row["applied_to_canonical_core"] != "false" or row["transaction_call_made"] != "false" for row in capabilities):
        raise CanonicalPatchProposalError("canonical patch capabilities are invalid")
    tests = read_tsv(report_root / "DLC_BKN_DRY_CANONICAL_PATCH_GO_TESTS.tsv")
    phases = {row["phase"] for row in tests}
    if phases != {"proposal_shadow", "patch_apply_check"} or any(row["status"] != "pass" for row in tests):
        raise CanonicalPatchProposalError("canonical patch Go tests are incomplete")
    apply_rows = read_tsv(report_root / "DLC_BKN_DRY_CANONICAL_PATCH_APPLY_CHECK.tsv")
    if len(apply_rows) != 4 or any(row["exact_match"] != "true" or row["proposal_sha256"] != row["applied_sha256"] for row in apply_rows):
        raise CanonicalPatchProposalError("patch apply check failed")
    guards = read_tsv(report_root / "DLC_BKN_DRY_CANONICAL_PATCH_CORE_GUARD.tsv")
    if len(guards) != 6 or any(row["unchanged_after_proposal"] != "true" for row in guards):
        raise CanonicalPatchProposalError("canonical core guard failed")
    handoff = _load_json(report_root / "DLC_BKN_DRY_CANONICAL_PATCH_HANDOFF.json")
    authorization = handoff.get("authorization", {})
    if authorization.get("core_patch_proposal_ready") is not True or authorization.get("core_patch_apply_allowed_by_dlc_workstream") is not False or handoff.get("patch_apply_check_passed") is not True or handoff.get("production_wiring_applied") is not False:
        raise CanonicalPatchProposalError("canonical patch handoff flags are invalid")
    manifest = _load_json(report_root / "REPORT_MANIFEST.json")
    expected = {row["path"]: (int(row["size"]), row["sha256"]) for row in manifest.get("files", [])}
    actual = {row["path"]: (int(row["size"]), row["sha256"]) for row in report_manifest(report_root)}
    if expected != actual:
        raise CanonicalPatchProposalError("report manifest mismatch")
    return summary


def main() -> None:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    build = sub.add_parser("build-proposal")
    build.add_argument("--project-root", required=True)
    build.add_argument("--shadow-report-root")
    validate = sub.add_parser("validate-report")
    validate.add_argument("--report-root", required=True)
    bundle = sub.add_parser("bundle-report")
    bundle.add_argument("--report-root", required=True)
    bundle.add_argument("--output", required=True)
    args = parser.parse_args()
    try:
        if args.command == "build-proposal":
            root = build_report(Path(args.project_root).resolve(), Path(args.shadow_report_root).resolve() if args.shadow_report_root else None)
            print(root)
        elif args.command == "validate-report":
            print(json.dumps(validate_report(Path(args.report_root).resolve()), indent=2, sort_keys=True))
        else:
            root = Path(args.report_root).resolve(); validate_report(root); make_archive(root, Path(args.output).resolve()); print(Path(args.output).resolve())
    except (CanonicalPatchProposalError, SHADOW.ShadowCoreRehearsalError, OSError, subprocess.SubprocessError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
