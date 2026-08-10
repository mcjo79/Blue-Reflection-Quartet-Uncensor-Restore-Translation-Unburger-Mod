package br1rebuild

import (
	"crypto/sha256"
	"encoding/hex"
	"errors"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"sort"
	"strings"
	"time"

	"local/blue-reflection-patcher/internal/plan/baseline"
	"local/blue-reflection-patcher/internal/plan/installstate"
	"local/blue-reflection-patcher/internal/plan/transaction"
)

const ReconstructionModuleID = "br1_reconstructed_content"

type BuildProgress struct {
	Phase        string `json:"phase"`
	CurrentFile  string `json:"current_file"`
	CurrentDone  int64  `json:"current_done"`
	CurrentTotal int64  `json:"current_total"`
	OverallDone  int64  `json:"overall_done"`
	OverallTotal int64  `json:"overall_total"`
}

type BuildProgressFunc func(BuildProgress)

type OutputArtifact struct {
	RelativePath string `json:"relative_path"`
	Path         string `json:"path"`
	Size         int64  `json:"size"`
	SHA256       string `json:"sha256"`
}

type ReconstructionBuildReport struct {
	Type             string                    `json:"type"`
	FormatVersion    int                       `json:"format_version"`
	Status           string                    `json:"status"`
	Survey           SurveyReport              `json:"survey"`
	Candidates       []OutputArtifact          `json:"candidates"`
	WardrobeAssets   CharacterAssetBuildReport `json:"wardrobe_assets"`
	Metadata         MetadataBuildReport       `json:"metadata"`
	ModuleLayout     BinaryLayoutReport        `json:"module_layout"`
	IslandMap        IslandMapReport           `json:"island_map"`
	IslandEvents     IslandEventReport         `json:"island_events"`
	CrossFileAudit   CrossFileAudit            `json:"cross_file_audit"`
	BaselineManifest string                    `json:"baseline_manifest"`
	TransactionID    string                    `json:"transaction_id"`
	JournalPath      string                    `json:"journal_path"`
	GameModified     bool                      `json:"game_modified"`
}

type ReconstructionBuildOptions struct {
	Survey            SurveyOptions
	StateRoot         string
	Workspace         string
	PreserveWorkspace bool
}

func hashPath(path string) (string, int64, error) {
	file, err := os.Open(path)
	if err != nil {
		return "", 0, err
	}
	defer file.Close()
	info, err := file.Stat()
	if err != nil {
		return "", 0, err
	}
	hash := sha256.New()
	buffer := make([]byte, 8<<20)
	for {
		n, readErr := file.Read(buffer)
		if n > 0 {
			_, _ = hash.Write(buffer[:n])
		}
		if readErr != nil {
			if errors.Is(readErr, io.EOF) {
				break
			}
			return "", 0, readErr
		}
	}
	return hex.EncodeToString(hash.Sum(nil)), info.Size(), nil
}

func BuildCandidateSet(opts ReconstructionBuildOptions, progress BuildProgressFunc) (ReconstructionBuildReport, error) {
	survey, err := SurveyInstallPair(opts.Survey)
	if err != nil {
		return ReconstructionBuildReport{}, err
	}
	report := ReconstructionBuildReport{Type: "br1_reconstruction_candidate_build", FormatVersion: 1, Status: "blocked", Survey: survey, GameModified: false}
	if !survey.Ready {
		return report, fmt.Errorf("source/target survey did not pass")
	}
	if opts.StateRoot == "" || opts.Workspace == "" {
		return report, fmt.Errorf("state root and candidate workspace are required")
	}

	active, activeExists, err := installstate.Load(opts.StateRoot, "blue_reflection_quartet", survey.TargetRoot)
	if err != nil {
		return report, fmt.Errorf("inspect active installation state: %w", err)
	}
	if activeExists {
		for _, item := range active.Files {
			relative := filepath.ToSlash(item.RelativePath)
			switch strings.ToLower(relative) {
			case "b1.dll", "data/pack10_02.pak", "data/pack10_03.pak", "data/pack11.pak", "data/pack12.pak":
				if strings.TrimSpace(opts.Survey.TargetFileOverrides[relative]) == "" {
					// Lookup case-insensitively because active-state paths are canonical
					// but callers may populate overrides from older metadata.
					found := false
					for key := range opts.Survey.TargetFileOverrides {
						if strings.EqualFold(filepath.ToSlash(key), relative) {
							found = true
							break
						}
					}
					if !found {
						return report, fmt.Errorf("active managed build source is missing preserved baseline override for %s", relative)
					}
				}
			}
		}
	}
	if err := rejectNonTerminalTransactions(opts.StateRoot, activeExists, progress); err != nil {
		return report, err
	}
	if err := os.MkdirAll(opts.Workspace, 0o755); err != nil {
		return report, err
	}
	buildDir, err := os.MkdirTemp(opts.Workspace, "br1-source-build-")
	if err != nil {
		return report, err
	}
	if !opts.PreserveWorkspace {
		defer os.RemoveAll(buildDir)
	}

	sourceFiles, targetFiles := ResolveContentFilesWithTargetOverrides(survey.Source.Root, survey.TargetRoot, opts.Survey.TargetFileOverrides)
	wardrobePlan, err := DeriveWardrobePlanWithTargetFiles(survey.Source.Root, survey.TargetRoot, targetFiles)
	if err != nil {
		return report, err
	}

	totals := map[string]int64{
		"Data/PACK10_02.PAK": fileSize(targetFiles["pack10_02"]) + expectedWardrobeImportBytes,
		"Data/PACK12.PAK":    fileSize(targetFiles["pack12"]),
		"B1.dll":             fileSize(targetFiles["dll"]) + 8192,
		"Data/PACK10_03.PAK": fileSize(targetFiles["pack10_03"]) + 64<<20,
		"Data/PACK11.PAK":    fileSize(targetFiles["pack11"]),
	}
	var overallTotal int64
	for _, size := range totals {
		overallTotal += size
	}
	var completed int64
	progressFor := func(relative string) byteProgress {
		return func(phase, name string, done, total int64) {
			if progress != nil {
				progress(BuildProgress{Phase: phase, CurrentFile: relative + ": " + name, CurrentDone: done, CurrentTotal: total, OverallDone: min64(completed+done, overallTotal), OverallTotal: overallTotal})
			}
		}
	}
	markComplete := func(relative string) { completed = min64(completed+totals[relative], overallTotal) }

	pack10Candidate := filepath.Join(buildDir, "character-content.bin")
	report.WardrobeAssets, err = BuildCharacterAssetArchive(sourceFiles["pack00_02"], targetFiles["pack10_02"], pack10Candidate, progressFor("Data/PACK10_02.PAK"))
	if err != nil {
		return report, err
	}
	markComplete("Data/PACK10_02.PAK")

	pack12Candidate := filepath.Join(buildDir, "content-index.bin")
	report.Metadata, err = BuildMetadataArchive(survey.Source.Root, targetFiles["pack12"], pack12Candidate, wardrobePlan, opts.Survey.TextTool, opts.Survey.UseHantForHans, progressFor("Data/PACK12.PAK"))
	if err != nil {
		return report, err
	}
	markComplete("Data/PACK12.PAK")

	moduleBytes, err := os.ReadFile(targetFiles["dll"])
	if err != nil {
		return report, err
	}
	moduleCandidateBytes, layout, err := RewriteBR1Module(moduleBytes, wardrobePlan)
	if err != nil {
		return report, err
	}
	report.ModuleLayout = *layout
	moduleCandidate := filepath.Join(buildDir, "module-layout.bin")
	if err := os.WriteFile(moduleCandidate, moduleCandidateBytes, 0o644); err != nil {
		return report, err
	}
	markComplete("B1.dll")

	islandMapCandidate := filepath.Join(buildDir, "field-content.bin")
	report.IslandMap, err = BuildIslandMapArchive(sourceFiles["pack00_03"], targetFiles["pack10_03"], islandMapCandidate, progressFor("Data/PACK10_03.PAK"))
	if err != nil {
		return report, err
	}
	markComplete("Data/PACK10_03.PAK")

	islandEventCandidate := filepath.Join(buildDir, "event-content.bin")
	report.IslandEvents, err = BuildIslandEventArchive(sourceFiles["pack01"], targetFiles["pack11"], islandEventCandidate, progressFor("Data/PACK11.PAK"))
	if err != nil {
		return report, err
	}
	markComplete("Data/PACK11.PAK")

	report.CrossFileAudit, err = AuditCrossFileWardrobe(moduleCandidate, pack10Candidate, pack12Candidate, wardrobePlan, opts.Survey.TextTool)
	if err != nil {
		return report, fmt.Errorf("cross-file candidate audit: %w", err)
	}

	staged := map[string]string{
		"B1.dll":             moduleCandidate,
		"Data/PACK10_02.PAK": pack10Candidate,
		"Data/PACK10_03.PAK": islandMapCandidate,
		"Data/PACK11.PAK":    islandEventCandidate,
		"Data/PACK12.PAK":    pack12Candidate,
	}
	ordered := []string{"B1.dll", "Data/PACK10_02.PAK", "Data/PACK10_03.PAK", "Data/PACK11.PAK", "Data/PACK12.PAK"}
	for _, relative := range ordered {
		hash, size, hashErr := hashPath(staged[relative])
		if hashErr != nil {
			return report, hashErr
		}
		report.Candidates = append(report.Candidates, OutputArtifact{RelativePath: relative, Path: staged[relative], Size: size, SHA256: hash})
	}

	report.Status = "candidates_verified"
	report.GameModified = false
	return report, nil
}

func PrepareArtifacts(gameRoot, stateRoot string, artifacts []OutputArtifact, selectedModules []string, metadata map[string]string) (string, string, error) {
	return PrepareArtifactsForTarget(gameRoot, stateRoot, "blue_reflection_quartet", artifacts, selectedModules, metadata)
}

func PrepareArtifactsForTarget(gameRoot, stateRoot, targetID string, artifacts []OutputArtifact, selectedModules []string, metadata map[string]string) (string, string, error) {
	return PrepareArtifactsForTargetWithProgress(gameRoot, stateRoot, targetID, artifacts, selectedModules, metadata, nil)
}

func PrepareArtifactsForTargetWithProgress(gameRoot, stateRoot, targetID string, artifacts []OutputArtifact, selectedModules []string, metadata map[string]string, progress transaction.ProgressFunc) (string, string, error) {
	if len(artifacts) == 0 {
		return "", "", fmt.Errorf("no verified artifacts were supplied")
	}
	byPath := map[string]OutputArtifact{}
	ordered := make([]string, 0, len(artifacts))
	for _, artifact := range artifacts {
		relative := filepath.ToSlash(strings.TrimSpace(artifact.RelativePath))
		if relative == "" {
			return "", "", fmt.Errorf("artifact has an empty target path")
		}
		key := strings.ToLower(relative)
		if _, exists := byPath[key]; exists {
			return "", "", fmt.Errorf("duplicate final artifact path: %s", relative)
		}
		trustedHash := strings.ToLower(strings.TrimSpace(artifact.SHA256))
		trustedSize := artifact.Size
		if trustedHash != "" && trustedSize > 0 {
			if len(trustedHash) != 64 {
				return "", "", fmt.Errorf("invalid verified artifact SHA-256: %s", relative)
			}
			if _, decodeErr := hex.DecodeString(trustedHash); decodeErr != nil {
				return "", "", fmt.Errorf("invalid verified artifact SHA-256: %s", relative)
			}
			info, statErr := os.Lstat(artifact.Path)
			if statErr != nil {
				return "", "", statErr
			}
			if info.Mode()&os.ModeSymlink != 0 || !info.Mode().IsRegular() {
				return "", "", fmt.Errorf("verified artifact is not a regular file: %s", relative)
			}
			if info.Size() != trustedSize {
				return "", "", fmt.Errorf("final artifact size drift: %s", relative)
			}
			artifact.RelativePath, artifact.SHA256, artifact.Size = relative, trustedHash, trustedSize
		} else {
			hash, size, err := hashPath(artifact.Path)
			if err != nil {
				return "", "", err
			}
			if trustedHash != "" && !strings.EqualFold(hash, trustedHash) {
				return "", "", fmt.Errorf("final artifact hash drift: %s", relative)
			}
			if trustedSize != 0 && size != trustedSize {
				return "", "", fmt.Errorf("final artifact size drift: %s", relative)
			}
			artifact.RelativePath, artifact.SHA256, artifact.Size = relative, hash, size
		}
		byPath[key] = artifact
		ordered = append(ordered, relative)
	}
	sort.Strings(ordered)
	transactionMetadata := map[string]string{}
	for key, value := range metadata {
		transactionMetadata[key] = value
	}
	activeHashes := map[string]string{}
	active, activeExists, err := installstate.Load(stateRoot, targetID, gameRoot)
	if err != nil {
		return "", "", fmt.Errorf("read active installation state before prepare: %w", err)
	}
	if activeExists {
		transactionMetadata["active_transaction_id"] = active.TransactionID
		transactionMetadata["active_state_prepare_guard"] = "expected_installed_sha256"
		for _, item := range active.Files {
			activeHashes[strings.ToLower(filepath.ToSlash(item.RelativePath))] = strings.ToLower(item.InstalledSHA256)
		}
	}
	if existing := strings.TrimSpace(transactionMetadata["target_id"]); existing != "" && existing != targetID {
		return "", "", fmt.Errorf("transaction target metadata mismatch: got %s, expected %s", existing, targetID)
	}
	transactionMetadata["target_id"] = targetID
	transactionMetadata["baseline_pending"] = "true"
	changes := make([]transaction.ChangeSpec, 0, len(ordered))
	for _, relative := range ordered {
		key := strings.ToLower(relative)
		artifact := byPath[key]
		changes = append(changes, transaction.ChangeSpec{
			RelativePath: relative, StagedPath: artifact.Path, DesiredSHA256: artifact.SHA256, DesiredBytes: artifact.Size,
			ExpectedOriginalSHA256: activeHashes[key],
		})
	}
	prepared, err := transaction.PrepareWithOptions(gameRoot, stateRoot, changes, selectedModules, transactionMetadata, transaction.PrepareOptions{
		Progress:                         progress,
		RequireHardlinkBackup:            true,
		UseSiblingFilesystemBackupStore:  true,
		UseSiblingFilesystemStagingStore: true,
	})
	if err != nil {
		return "", "", err
	}
	base, err := baseline.EnsureFromPreparedTransaction(stateRoot, targetID, prepared.Journal)
	if err != nil {
		_, _ = transaction.DiscardPrepared(prepared.JournalPath)
		return "", "", fmt.Errorf("publish game-side persistent baseline: %w", err)
	}
	preparedJournal, err := transaction.UpdatePreparedMetadata(prepared.JournalPath, map[string]string{
		"baseline_pending":        "false",
		"baseline_id":             base.Manifest.BaselineID,
		"baseline_fingerprint":    base.Manifest.Fingerprint,
		"baseline_manifest_path":  base.ManifestPath,
		"baseline_classification": base.Manifest.Classification,
		"baseline_action":         base.Action,
		"baseline_storage_policy": "game_side_transaction_backup",
	})
	if err != nil {
		return "", "", fmt.Errorf("attach persistent baseline metadata to prepared transaction: %w", err)
	}
	prepared.Journal = preparedJournal
	return prepared.JournalPath, base.ManifestPath, nil
}

func PrepareCandidateSet(report ReconstructionBuildReport, stateRoot string, selectedModules []string) (ReconstructionBuildReport, error) {
	if report.Status != "candidates_verified" {
		return report, fmt.Errorf("candidate set is not verified: %s", report.Status)
	}
	if strings.TrimSpace(stateRoot) == "" {
		return report, fmt.Errorf("state root is required")
	}
	modules := append([]string{}, selectedModules...)
	if len(modules) == 0 {
		modules = []string{ReconstructionModuleID}
	}
	metadata := map[string]string{
		"target_id":     "blue_reflection_quartet",
		"purpose":       "br1_legacy_content",
		"capability":    "br1_legacy_content_rebuild_v1",
		"source_origin": report.Survey.Source.Origin,
	}
	journal, baselineManifest, err := PrepareArtifacts(report.Survey.TargetRoot, stateRoot, report.Candidates, modules, metadata)
	if err != nil {
		return report, err
	}
	report.BaselineManifest = baselineManifest
	report.JournalPath = journal
	loaded, err := transaction.Load(journal)
	if err != nil {
		return report, err
	}
	report.TransactionID = loaded.TransactionID
	report.Status = "staged_ready_for_apply"
	report.GameModified = false
	return report, nil
}

func BuildReconstructionSet(opts ReconstructionBuildOptions, progress BuildProgressFunc) (ReconstructionBuildReport, error) {
	report, err := BuildCandidateSet(opts, progress)
	if err != nil {
		return report, err
	}
	return PrepareCandidateSet(report, opts.StateRoot, []string{ReconstructionModuleID})
}

func rejectNonTerminalTransactions(stateRoot string, activeStateExists bool, progress BuildProgressFunc) error {
	root := filepath.Join(stateRoot, "transactions")
	entries, err := os.ReadDir(root)
	if errors.Is(err, os.ErrNotExist) {
		return nil
	}
	if err != nil {
		return fmt.Errorf("inspect transaction state: %w", err)
	}
	for _, entry := range entries {
		if !entry.IsDir() {
			continue
		}
		journalPath := filepath.Join(root, entry.Name(), "journal.json")
		journal, loadErr := transaction.Load(journalPath)
		if loadErr != nil {
			return fmt.Errorf("unreadable transaction journal %s: %w", entry.Name(), loadErr)
		}
		switch journal.Status {
		case transaction.StatusRolledBack, transaction.StatusDiscarded:
			continue
		case transaction.StatusCommitted:
			if activeStateExists {
				continue
			}
			return fmt.Errorf("candidate build blocked by orphan committed transaction %s; this installation has no active managed state, so select the intended installation or run transaction/installation recovery", journal.TransactionID)
		case transaction.StatusPrepared:
			if legacyPreparedJournalNeedsMetadataRecovery(journal) {
				if progress != nil {
					progress(BuildProgress{Phase: "state_recovery", CurrentFile: "Discarding incomplete prepared transaction " + journal.TransactionID})
				}
				if _, discardErr := transaction.DiscardPrepared(journalPath); discardErr != nil {
					return fmt.Errorf("discard incomplete prepared transaction %s: %w", journal.TransactionID, discardErr)
				}
				continue
			}
		}
		return fmt.Errorf("candidate build blocked by transaction %s in status %s", journal.TransactionID, journal.Status)
	}
	return nil
}

func legacyPreparedJournalNeedsMetadataRecovery(journal transaction.Journal) bool {
	if journal.Status != transaction.StatusPrepared {
		return false
	}
	if strings.TrimSpace(journal.Metadata["target_id"]) == "" || strings.TrimSpace(journal.Metadata["baseline_manifest_path"]) != "" {
		return false
	}
	switch strings.TrimSpace(journal.Metadata["purpose"]) {
	case "br1_legacy_content", "translation_records":
		return true
	default:
		return false
	}
}

func fileSize(path string) int64 {
	info, err := os.Stat(path)
	if err != nil {
		return 0
	}
	return info.Size()
}

func DefaultCandidateWorkspace(stateRoot string) string {
	return filepath.Join(stateRoot, "builds", "br1-source-content")
}

func ReconstructionTimestamp() string { return time.Now().UTC().Format("20060102T150405Z") }

func min64(a, b int64) int64 {
	if a < b {
		return a
	}
	return b
}
