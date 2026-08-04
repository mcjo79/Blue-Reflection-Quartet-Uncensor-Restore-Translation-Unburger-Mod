package main

import (
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"flag"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"sort"
	"strconv"
	"strings"
	"time"

	"local/blue-reflection-patcher/internal/model"
	"local/blue-reflection-patcher/internal/plan/baseline"
	"local/blue-reflection-patcher/internal/plan/catalog"
	"local/blue-reflection-patcher/internal/plan/installstate"
	"local/blue-reflection-patcher/internal/plan/payloadpreview"
	"local/blue-reflection-patcher/internal/plan/transaction"
	"local/blue-reflection-patcher/internal/targets"
)

const (
	transactionPrepareReportType    = "br_transaction_prepare_report"
	transactionPrepareFormatVersion = 4
	transactionStatusReportType     = "br_transaction_status_report"
	transactionStatusFormatVersion  = 1
	transactionDiscardReportType    = "br_transaction_discard_report"
	transactionDiscardFormatVersion = 1
)

type transactionPrepareFile struct {
	RelativePath   string `json:"relative_path"`
	DesiredAction  string `json:"desired_action"`
	SourcePath     string `json:"source_path"`
	SourceSHA256   string `json:"source_sha256"`
	SourceBytes    int64  `json:"source_bytes"`
	TargetPath     string `json:"target_path"`
	TargetExisted  bool   `json:"target_existed"`
	TargetSHA256   string `json:"target_sha256,omitempty"`
	TargetBytes    int64  `json:"target_bytes,omitempty"`
	BackupPrepared bool   `json:"backup_prepared"`
	StagedPrepared bool   `json:"staged_prepared"`
}

type transactionPrepareReport struct {
	Type                   string                   `json:"type"`
	FormatVersion          int                      `json:"format_version"`
	Status                 string                   `json:"status"`
	GeneratedUTC           time.Time                `json:"generated_utc"`
	CommitEnabled          bool                     `json:"commit_enabled"`
	ProjectRoot            string                   `json:"project_root"`
	TargetID               string                   `json:"target_id"`
	DisplayName            string                   `json:"display_name"`
	GameRoot               string                   `json:"game_root"`
	StateDirectory         string                   `json:"state_directory"`
	SelectedModules        []string                 `json:"selected_modules"`
	PreviewType            string                   `json:"preview_type"`
	PreviewFormatVersion   int                      `json:"preview_format_version"`
	PreviewSHA256          string                   `json:"preview_sha256"`
	TransactionID          string                   `json:"transaction_id,omitempty"`
	JournalPath            string                   `json:"journal_path,omitempty"`
	PreparedChangeCount    int                      `json:"prepared_change_count"`
	NoopCount              int                      `json:"noop_count"`
	BackupCount            int                      `json:"backup_count"`
	StagedCount            int                      `json:"staged_count"`
	Files                  []transactionPrepareFile `json:"files"`
	BaselineID             string                   `json:"baseline_id,omitempty"`
	BaselineFingerprint    string                   `json:"baseline_fingerprint,omitempty"`
	BaselineManifestPath   string                   `json:"baseline_manifest_path,omitempty"`
	BaselineAction         string                   `json:"baseline_action,omitempty"`
	BaselineClassification string                   `json:"baseline_classification,omitempty"`
	BaselineFileCount      int                      `json:"baseline_file_count"`
	BaselineSource         string                   `json:"baseline_source"`
	ActiveStateStatus      string                   `json:"active_state_status"`
	ActiveTransactionID    string                   `json:"active_transaction_id,omitempty"`
	Warnings               []string                 `json:"warnings"`
	Policy                 string                   `json:"policy"`
}

type transactionSummary struct {
	TransactionID   string            `json:"transaction_id"`
	Status          string            `json:"status"`
	CreatedUTC      time.Time         `json:"created_utc"`
	UpdatedUTC      time.Time         `json:"updated_utc"`
	JournalPath     string            `json:"journal_path"`
	SelectedModules []string          `json:"selected_modules"`
	FileCount       int               `json:"file_count"`
	Metadata        map[string]string `json:"metadata,omitempty"`
}

type transactionStatusReport struct {
	Type             string               `json:"type"`
	FormatVersion    int                  `json:"format_version"`
	Status           string               `json:"status"`
	GeneratedUTC     time.Time            `json:"generated_utc"`
	TargetID         string               `json:"target_id"`
	DisplayName      string               `json:"display_name"`
	GameRoot         string               `json:"game_root"`
	StateDirectory   string               `json:"state_directory"`
	TransactionCount int                  `json:"transaction_count"`
	Transactions     []transactionSummary `json:"transactions"`
	Warnings         []string             `json:"warnings"`
}

type transactionDiscardReport struct {
	Type            string    `json:"type"`
	FormatVersion   int       `json:"format_version"`
	Status          string    `json:"status"`
	GeneratedUTC    time.Time `json:"generated_utc"`
	TransactionID   string    `json:"transaction_id"`
	JournalPath     string    `json:"journal_path"`
	GameRoot        string    `json:"game_root"`
	FileCount       int       `json:"file_count"`
	GameFilesEdited bool      `json:"game_files_edited"`
	Policy          string    `json:"policy"`
}

func commandTransactionPrepare(args []string) error {
	flags := flag.NewFlagSet("transaction-prepare", flag.ContinueOnError)
	var roots rootsFlag
	var noPrompt bool
	var moduleList, output, projectRoot string
	flags.Var(&roots, "game-dir", "game directory; exactly one installation must be selected")
	flags.Var(&roots, "root", "alias for --game-dir")
	flags.BoolVar(&noPrompt, "no-prompt", false, "use default modules and fail instead of prompting")
	flags.StringVar(&moduleList, "modules", "", "comma-separated module IDs; 'none' disables all modules")
	flags.StringVar(&projectRoot, "project-root", "", "project root containing verified local build artifacts")
	flags.StringVar(&output, "json", "", "write transaction preparation report to this file")
	if err := flags.Parse(args); err != nil {
		return err
	}
	specs, err := targets.Load()
	if err != nil {
		return err
	}
	prompt := !noPrompt && stdinIsInteractive()
	detections, err := detectWithFallback(specs, roots, prompt, os.Stdin, os.Stdout)
	if err != nil {
		return err
	}
	if len(detections) != 1 {
		return fmt.Errorf("transaction preparation requires exactly one detected installation; found %d", len(detections))
	}
	modules, err := catalog.Load()
	if err != nil {
		return err
	}
	explicit, explicitSet := parseModuleList(moduleList)
	selected, err := chooseModules(modules, detections, explicit, explicitSet, prompt, os.Stdin, os.Stdout)
	if err != nil {
		return err
	}
	preview, err := buildPayloadPreview(projectRoot, selected)
	if err != nil {
		return err
	}
	report, err := preparePayloadTransaction(preview)
	if err != nil {
		return err
	}
	printHumanTransactionPrepare(os.Stdout, report)
	if output != "" {
		if err := emit(report, output); err != nil {
			return err
		}
		fmt.Printf("Transaction preparation report: %s\n", output)
	}
	return nil
}

func describePayloadPreviewReadiness(preview payloadpreview.Preview) string {
	parts := []string{fmt.Sprintf("status=%s", preview.Status), fmt.Sprintf("targets=%d", len(preview.Targets))}
	for _, target := range preview.Targets {
		if target.Status == "ready" && target.PendingModuleCount == 0 {
			continue
		}
		parts = append(parts, fmt.Sprintf("target=%s status=%s pending_modules=%d", target.TargetID, target.Status, target.PendingModuleCount))
		for _, module := range target.Modules {
			if module.Ready {
				continue
			}
			reason := strings.TrimSpace(module.Reason)
			if reason == "" {
				reason = "module is not ready"
			}
			parts = append(parts, fmt.Sprintf("module=%s reason=%s", module.ModuleID, reason))
			for _, artifact := range module.Artifacts {
				if artifact.TransactionReady {
					continue
				}
				detail := strings.TrimSpace(artifact.Error)
				if detail == "" {
					detail = strings.TrimSpace(artifact.Status)
				}
				parts = append(parts, fmt.Sprintf("artifact=%s detail=%s", artifact.RelativePath, detail))
			}
		}
	}
	return strings.Join(parts, "; ")
}

func preparePayloadTransaction(preview payloadpreview.Preview) (transactionPrepareReport, error) {
	if preview.Type != payloadpreview.PreviewType || preview.FormatVersion != payloadpreview.PreviewFormatVersion {
		return transactionPrepareReport{}, fmt.Errorf("unsupported payload preview type/version")
	}
	if preview.CommitEnabled {
		return transactionPrepareReport{}, fmt.Errorf("payload preview unexpectedly enables commit")
	}
	if preview.Status != "ready" || len(preview.Targets) != 1 {
		return transactionPrepareReport{}, fmt.Errorf("payload preview is not fully ready: %s", describePayloadPreviewReadiness(preview))
	}
	target := preview.Targets[0]
	if target.Status != "ready" || target.PendingModuleCount != 0 {
		return transactionPrepareReport{}, fmt.Errorf("target payload preview is not fully ready: status=%s pending_modules=%d", target.Status, target.PendingModuleCount)
	}
	if len(target.SelectedModules) == 0 {
		return transactionPrepareReport{}, fmt.Errorf("no modules are selected")
	}
	previewHash, err := hashJSON(preview)
	if err != nil {
		return transactionPrepareReport{}, err
	}
	report := transactionPrepareReport{
		Type: transactionPrepareReportType, FormatVersion: transactionPrepareFormatVersion,
		Status: "validating", GeneratedUTC: time.Now().UTC(), CommitEnabled: true,
		ProjectRoot: preview.ProjectRoot, TargetID: target.TargetID, DisplayName: target.DisplayName,
		GameRoot: target.GameRoot, StateDirectory: target.StateDirectory,
		SelectedModules: append([]string(nil), target.SelectedModules...), PreviewType: preview.Type,
		PreviewFormatVersion: preview.FormatVersion, PreviewSHA256: previewHash,
		Warnings: []string{}, Policy: "verify preview freshness, preserve an immutable versioned pre-install baseline, stage payloads and verified transaction backups, write journal, and require an explicit transaction-commit --yes before modifying game files",
	}
	active, activeExists, err := installstate.Load(target.StateDirectory, target.TargetID, target.GameRoot)
	if err != nil {
		return transactionPrepareReport{}, fmt.Errorf("read active installation state: %w", err)
	}
	activeInspection, err := installstate.Inspect(target.StateDirectory, target.TargetID, target.GameRoot)
	if err != nil {
		return transactionPrepareReport{}, fmt.Errorf("inspect active installation state: %w", err)
	}
	report.ActiveStateStatus = activeInspection.Status
	if activeExists {
		report.ActiveTransactionID = active.TransactionID
	}
	if err := rejectBlockingTransactions(target.StateDirectory, activeExists); err != nil {
		return transactionPrepareReport{}, err
	}

	seen := map[string]bool{}
	var changes []transaction.ChangeSpec
	for _, module := range target.Modules {
		if !module.Ready {
			return transactionPrepareReport{}, fmt.Errorf("selected module is not ready: %s", module.ModuleID)
		}
		for _, artifact := range module.Artifacts {
			if !artifact.TransactionReady || artifact.Status != "ready" {
				return transactionPrepareReport{}, fmt.Errorf("artifact is not transaction-ready: %s", artifact.RelativePath)
			}
			if err := validateArtifactFresh(artifact); err != nil {
				return transactionPrepareReport{}, fmt.Errorf("payload preview became stale for %s: %w", artifact.RelativePath, err)
			}
			key := strings.ToLower(filepath.ToSlash(filepath.Clean(filepath.FromSlash(artifact.RelativePath))))
			if seen[key] {
				return transactionPrepareReport{}, fmt.Errorf("multiple modules produced the same transaction path: %s", artifact.RelativePath)
			}
			seen[key] = true
			file := transactionPrepareFile{
				RelativePath: filepath.ToSlash(artifact.RelativePath), DesiredAction: artifact.DesiredAction,
				SourcePath: artifact.SourcePath, SourceSHA256: artifact.SourceSHA256, SourceBytes: artifact.SourceBytes,
				TargetPath: artifact.TargetPath, TargetExisted: artifact.TargetExists,
				TargetSHA256: artifact.TargetSHA256, TargetBytes: artifact.TargetBytes,
			}
			switch artifact.DesiredAction {
			case "noop":
				report.NoopCount++
			case "add", "replace":
				changes = append(changes, transaction.ChangeSpec{RelativePath: artifact.RelativePath, StagedPath: artifact.SourcePath})
			default:
				return transactionPrepareReport{}, fmt.Errorf("unsupported desired action %q for %s", artifact.DesiredAction, artifact.RelativePath)
			}
			report.Files = append(report.Files, file)
		}
	}
	sort.Slice(report.Files, func(i, j int) bool { return report.Files[i].RelativePath < report.Files[j].RelativePath })
	if len(changes) == 0 {
		report.Status = "no_changes"
		report.Warnings = append(report.Warnings, "all verified payloads already match the selected installation")
		return report, nil
	}
	baselinePaths := make([]string, 0, len(changes))
	for _, change := range changes {
		baselinePaths = append(baselinePaths, change.RelativePath)
	}
	var baselineResult baseline.EnsureResult
	if activeExists {
		switch activeInspection.Status {
		case installstate.InspectionMatchesInstalled:
			report.BaselineSource = "preserved_active_installation_baseline"
		case installstate.InspectionDisplacedToBaseline:
			report.BaselineSource = "preserved_baseline_after_active_displacement"
			report.Warnings = append(report.Warnings, "Recorded active mod files were displaced and the current files match the preserved baseline; preparation may proceed without treating the displaced modded files as a new baseline.")
		default:
			details := make([]string, 0, len(activeInspection.Files))
			for _, item := range activeInspection.Files {
				if item.MatchesInstalled || item.MatchesBaseline {
					continue
				}
				details = append(details, fmt.Sprintf("%s=%s", item.RelativePath, item.CurrentState))
			}
			detailText := ""
			if len(details) > 0 {
				detailText = "; files=" + strings.Join(details, ",")
			}
			return transactionPrepareReport{}, fmt.Errorf("active installation state is not safe for automatic preparation: %s%s; inspect with installation-status", activeInspection.Status, detailText)
		}
		baselineResult, err = baseline.EnsureWithInherited(target.GameRoot, target.StateDirectory, target.TargetID, baselinePaths, active.BaselineManifestPath)
	} else {
		report.BaselineSource = "observed_current_preinstall_state"
		baselineResult, err = baseline.Ensure(target.GameRoot, target.StateDirectory, target.TargetID, baselinePaths)
	}
	if err != nil {
		return transactionPrepareReport{}, fmt.Errorf("preserve persistent installation baseline: %w", err)
	}
	report.BaselineID = baselineResult.Manifest.BaselineID
	report.BaselineFingerprint = baselineResult.Manifest.Fingerprint
	report.BaselineManifestPath = baselineResult.ManifestPath
	report.BaselineAction = baselineResult.Action
	report.BaselineClassification = baselineResult.Manifest.Classification
	report.BaselineFileCount = len(baselineResult.Manifest.Files)
	if !activeExists {
		for index := range changes {
			if stored, ok := baselineResult.StoredFiles[filepath.ToSlash(changes[index].RelativePath)]; ok {
				changes[index].VerifiedBackupPath = stored
			}
		}
	}

	metadata := map[string]string{
		"prepared_by":                    "transaction-prepare",
		"commit_enabled":                 "true",
		"project_root":                   preview.ProjectRoot,
		"target_id":                      target.TargetID,
		"payload_preview_type":           preview.Type,
		"payload_preview_format_version": strconv.Itoa(preview.FormatVersion),
		"payload_preview_sha256":         previewHash,
		"payload_preview_generated_utc":  preview.GeneratedUTC.Format(time.RFC3339Nano),
		"source_policy":                  "verified local translation or content-aware composition payloads only",
		"baseline_id":                    baselineResult.Manifest.BaselineID,
		"baseline_fingerprint":           baselineResult.Manifest.Fingerprint,
		"baseline_manifest_path":         baselineResult.ManifestPath,
		"baseline_classification":        baselineResult.Manifest.Classification,
		"baseline_action":                baselineResult.Action,
		"baseline_source":                report.BaselineSource,
		"active_state_status":            report.ActiveStateStatus,
		"active_transaction_id":          report.ActiveTransactionID,
	}
	prepared, err := transaction.Prepare(target.GameRoot, target.StateDirectory, changes, target.SelectedModules, metadata)
	if err != nil {
		return transactionPrepareReport{}, err
	}
	if err := verifyPreparedMatchesReport(prepared, report); err != nil {
		_, _ = transaction.DiscardPrepared(prepared.JournalPath)
		return transactionPrepareReport{}, fmt.Errorf("prepared transaction verification failed: %w", err)
	}
	report.Status = "prepared"
	report.TransactionID = prepared.Journal.TransactionID
	report.JournalPath = prepared.JournalPath
	report.PreparedChangeCount = len(prepared.Journal.Files)
	report.StagedCount = len(prepared.Journal.Files)
	byPath := map[string]*transactionPrepareFile{}
	for index := range report.Files {
		byPath[strings.ToLower(report.Files[index].RelativePath)] = &report.Files[index]
	}
	for _, record := range prepared.Journal.Files {
		file := byPath[strings.ToLower(record.RelativePath)]
		if file == nil {
			return transactionPrepareReport{}, fmt.Errorf("prepared journal contains unexpected path: %s", record.RelativePath)
		}
		file.StagedPrepared = true
		if record.OriginalExisted {
			file.BackupPrepared = true
			report.BackupCount++
		}
	}
	return report, nil
}

func validateArtifactFresh(artifact payloadpreview.ArtifactPreview) error {
	info, err := os.Lstat(artifact.SourcePath)
	if err != nil {
		return fmt.Errorf("inspect source: %w", err)
	}
	if info.Mode()&os.ModeSymlink != 0 || !info.Mode().IsRegular() {
		return fmt.Errorf("source is not a regular file")
	}
	if info.Size() != artifact.SourceBytes {
		return fmt.Errorf("source size changed")
	}
	hash, err := hashRegularFile(artifact.SourcePath)
	if err != nil {
		return err
	}
	if hash != artifact.SourceSHA256 {
		return fmt.Errorf("source hash changed")
	}
	targetInfo, targetErr := os.Lstat(artifact.TargetPath)
	switch artifact.DesiredAction {
	case "add":
		if targetErr == nil {
			return fmt.Errorf("target appeared after preview")
		}
		if !errors.Is(targetErr, os.ErrNotExist) {
			return fmt.Errorf("inspect target: %w", targetErr)
		}
		return nil
	case "replace", "noop":
		if targetErr != nil {
			return fmt.Errorf("inspect target: %w", targetErr)
		}
		if targetInfo.Mode()&os.ModeSymlink != 0 || !targetInfo.Mode().IsRegular() {
			return fmt.Errorf("target is not a regular file")
		}
		if !artifact.TargetExists || targetInfo.Size() != artifact.TargetBytes {
			return fmt.Errorf("target size changed")
		}
		targetHash, err := hashRegularFile(artifact.TargetPath)
		if err != nil {
			return err
		}
		if targetHash != artifact.TargetSHA256 {
			return fmt.Errorf("target hash changed")
		}
		if artifact.DesiredAction == "noop" && targetHash != artifact.SourceSHA256 {
			return fmt.Errorf("noop target no longer matches source")
		}
		return nil
	default:
		return fmt.Errorf("unsupported action %q", artifact.DesiredAction)
	}
}

func verifyPreparedMatchesReport(prepared transaction.Prepared, report transactionPrepareReport) error {
	if prepared.Journal.Status != transaction.StatusPrepared {
		return fmt.Errorf("unexpected journal status %s", prepared.Journal.Status)
	}
	expected := map[string]transactionPrepareFile{}
	for _, file := range report.Files {
		if file.DesiredAction == "add" || file.DesiredAction == "replace" {
			expected[strings.ToLower(file.RelativePath)] = file
		}
	}
	if len(prepared.Journal.Files) != len(expected) {
		return fmt.Errorf("journal file count mismatch")
	}
	for _, record := range prepared.Journal.Files {
		file, ok := expected[strings.ToLower(record.RelativePath)]
		if !ok {
			return fmt.Errorf("unexpected journal path %s", record.RelativePath)
		}
		if record.DesiredSHA256 != file.SourceSHA256 || record.OriginalExisted != file.TargetExisted {
			return fmt.Errorf("journal fingerprint mismatch for %s", record.RelativePath)
		}
		if record.OriginalExisted && record.OriginalSHA256 != file.TargetSHA256 {
			return fmt.Errorf("journal original hash mismatch for %s", record.RelativePath)
		}
	}
	return nil
}

func rejectBlockingTransactions(stateDirectory string, activeStateExists bool) error {
	transactions, warnings, err := loadTransactionSummaries(stateDirectory)
	if err != nil {
		return err
	}
	if len(warnings) != 0 {
		return fmt.Errorf("transaction state contains unreadable journals: %s", strings.Join(warnings, "; "))
	}
	for _, item := range transactions {
		switch item.Status {
		case transaction.StatusRolledBack, transaction.StatusDiscarded:
			continue
		case transaction.StatusCommitted:
			if activeStateExists {
				continue
			}
			return fmt.Errorf("committed transaction %s is not represented by an active installation state; recovery is required before another prepare", item.TransactionID)
		default:
			return fmt.Errorf("installation already has a non-terminal transaction %s in status %s; inspect it with transaction-status", item.TransactionID, item.Status)
		}
	}
	return nil
}

func commandTransactionStatus(args []string) error {
	flags := flag.NewFlagSet("transaction-status", flag.ContinueOnError)
	var roots rootsFlag
	var output string
	flags.Var(&roots, "game-dir", "game directory; exactly one installation must be selected")
	flags.Var(&roots, "root", "alias for --game-dir")
	flags.StringVar(&output, "json", "", "write transaction status report to this file")
	if err := flags.Parse(args); err != nil {
		return err
	}
	specs, err := targets.Load()
	if err != nil {
		return err
	}
	detections, err := detectWithFallback(specs, roots, false, os.Stdin, os.Stdout)
	if err != nil {
		return err
	}
	if len(detections) != 1 {
		return fmt.Errorf("transaction status requires exactly one detected installation; found %d", len(detections))
	}
	base, err := stateRoot()
	if err != nil {
		return err
	}
	detection := detections[0]
	stateDirectory := installationStateDirectory(base, detection.TargetID, detection.Root)
	transactions, warnings, err := loadTransactionSummaries(stateDirectory)
	if err != nil {
		return err
	}
	report := transactionStatusReport{
		Type: transactionStatusReportType, FormatVersion: transactionStatusFormatVersion,
		Status: "ok", GeneratedUTC: time.Now().UTC(), TargetID: detection.TargetID,
		DisplayName: detection.DisplayName, GameRoot: detection.Root, StateDirectory: stateDirectory,
		TransactionCount: len(transactions), Transactions: transactions, Warnings: warnings,
	}
	if len(warnings) != 0 {
		report.Status = "warning"
	}
	printHumanTransactionStatus(os.Stdout, report)
	if output != "" {
		if err := emit(report, output); err != nil {
			return err
		}
		fmt.Printf("Transaction status report: %s\n", output)
	}
	return nil
}

func loadTransactionSummaries(stateDirectory string) ([]transactionSummary, []string, error) {
	root := filepath.Join(stateDirectory, "transactions")
	entries, err := os.ReadDir(root)
	if errors.Is(err, os.ErrNotExist) {
		return []transactionSummary{}, []string{}, nil
	}
	if err != nil {
		return nil, nil, fmt.Errorf("read transaction state: %w", err)
	}
	var results []transactionSummary
	var warnings []string
	for _, entry := range entries {
		if !entry.IsDir() {
			continue
		}
		journalPath := filepath.Join(root, entry.Name(), "journal.json")
		journal, err := transaction.Load(journalPath)
		if err != nil {
			warnings = append(warnings, fmt.Sprintf("%s: %v", journalPath, err))
			continue
		}
		results = append(results, transactionSummary{
			TransactionID: journal.TransactionID, Status: journal.Status, CreatedUTC: journal.CreatedUTC,
			UpdatedUTC: journal.UpdatedUTC, JournalPath: journalPath,
			SelectedModules: append([]string(nil), journal.SelectedModules...), FileCount: len(journal.Files),
			Metadata: journal.Metadata,
		})
	}
	sort.Slice(results, func(i, j int) bool { return results[i].CreatedUTC.Before(results[j].CreatedUTC) })
	sort.Strings(warnings)
	return results, warnings, nil
}

func commandTransactionDiscard(args []string) error {
	flags := flag.NewFlagSet("transaction-discard", flag.ContinueOnError)
	var journalPath, output string
	flags.StringVar(&journalPath, "journal", "", "prepared transaction journal to discard")
	flags.StringVar(&output, "json", "", "write discard report to this file")
	if err := flags.Parse(args); err != nil {
		return err
	}
	if strings.TrimSpace(journalPath) == "" {
		return fmt.Errorf("--journal is required")
	}
	journal, err := transaction.DiscardPrepared(journalPath)
	if err != nil {
		return err
	}
	report := transactionDiscardReport{
		Type: transactionDiscardReportType, FormatVersion: transactionDiscardFormatVersion,
		Status: journal.Status, GeneratedUTC: time.Now().UTC(), TransactionID: journal.TransactionID,
		JournalPath: journalPath, GameRoot: journal.GameRoot, FileCount: len(journal.Files),
		GameFilesEdited: false, Policy: "discard only a fully verified prepared transaction; retain audit journal and remove staged payloads/backups",
	}
	printHumanTransactionDiscard(os.Stdout, report)
	if output != "" {
		if err := emit(report, output); err != nil {
			return err
		}
		fmt.Printf("Transaction discard report: %s\n", output)
	}
	return nil
}

func printHumanTransactionPrepare(out io.Writer, report transactionPrepareReport) {
	fmt.Fprintf(out, "\n%s%sTransaction preparation%s\n", ansiBold, ansiCyan, ansiReset)
	fmt.Fprintf(out, "%sStatus:%s %s\n", ansiBold, ansiReset, report.Status)
	fmt.Fprintf(out, "Target: %s\n", report.DisplayName)
	fmt.Fprintf(out, "Game:   %s\n", report.GameRoot)
	fmt.Fprintf(out, "State:  %s\n", report.StateDirectory)
	if report.BaselineManifestPath != "" {
		fmt.Fprintf(out, "Baseline: %s (%s, %s)\n", report.BaselineID, report.BaselineAction, report.BaselineClassification)
		fmt.Fprintf(out, "          %s\n", report.BaselineManifestPath)
	}
	if report.JournalPath != "" {
		fmt.Fprintf(out, "Journal: %s\n", report.JournalPath)
	}
	fmt.Fprintf(out, "Changes prepared: %d; no-op payloads: %d; backups: %d\n", report.PreparedChangeCount, report.NoopCount, report.BackupCount)
	fmt.Fprintf(out, "%sNo game file was modified during preparation. Guided installation may continue immediately; standalone preparation can be installed with transaction-commit --journal <path> --yes or removed with transaction-discard.%s\n", ansiDim, ansiReset)
}

func printHumanTransactionStatus(out io.Writer, report transactionStatusReport) {
	fmt.Fprintf(out, "\n%s%sTransaction status%s\n", ansiBold, ansiCyan, ansiReset)
	fmt.Fprintf(out, "Target: %s\nState:  %s\n", report.DisplayName, report.StateDirectory)
	if len(report.Transactions) == 0 {
		fmt.Fprintln(out, "No transactions found.")
	}
	for _, item := range report.Transactions {
		fmt.Fprintf(out, "  [%s] %s (%d file(s))\n", item.Status, item.TransactionID, item.FileCount)
		fmt.Fprintf(out, "      %s\n", item.JournalPath)
	}
	for _, warning := range report.Warnings {
		fmt.Fprintf(out, "  %sWARNING:%s %s\n", ansiYellow, ansiReset, warning)
	}
}

func printHumanTransactionDiscard(out io.Writer, report transactionDiscardReport) {
	fmt.Fprintf(out, "\n%s%sTransaction discarded%s\n", ansiBold, ansiCyan, ansiReset)
	fmt.Fprintf(out, "Transaction: %s\nJournal:     %s\n", report.TransactionID, report.JournalPath)
	fmt.Fprintf(out, "%sStaged payloads and backups were removed after verifying that the game still matched the pre-prepare state. No game file was modified.%s\n", ansiDim, ansiReset)
}

func hashJSON(value any) (string, error) {
	data, err := json.Marshal(value)
	if err != nil {
		return "", err
	}
	digest := sha256.Sum256(data)
	return hex.EncodeToString(digest[:]), nil
}

func hashRegularFile(path string) (string, error) {
	file, err := os.Open(path)
	if err != nil {
		return "", err
	}
	defer file.Close()
	digest := sha256.New()
	if _, err := io.Copy(digest, file); err != nil {
		return "", err
	}
	return hex.EncodeToString(digest.Sum(nil)), nil
}

func sortedStrings(values []string) []string {
	result := append([]string(nil), values...)
	sort.Strings(result)
	return result
}

var _ model.SelectionResult
var _ = sortedStrings
